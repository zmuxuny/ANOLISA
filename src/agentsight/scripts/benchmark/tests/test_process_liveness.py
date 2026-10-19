"""An unreaped exited process must not pass benchmark survival checks."""

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "single_run"))
import collect_metrics
import fault_injector


@contextmanager
def exited_child():
    """Wait for our own child to exit without reaping its procfs record."""
    child = subprocess.Popen([sys.executable, "-c", "raise SystemExit(7)"])
    try:
        result = os.waitid(os.P_PID, child.pid, os.WEXITED | os.WNOWAIT)
        assert result.si_status == 7
        assert Path(f"/proc/{child.pid}/status").exists()
        yield child.pid
    finally:
        child.wait(timeout=5)


@unittest.skipUnless(sys.platform.startswith("linux"), "Linux procfs required")
class ProcessLivenessTests(unittest.TestCase):
    def test_exited_child_is_not_alive_before_reaping(self):
        with exited_child() as pid:
            self.assertFalse(fault_injector.process_alive(pid))

    def test_collector_does_not_sample_zombie_as_live(self):
        with exited_child() as pid:
            row, ticks, _ = collect_metrics.sample(pid, 17, time.monotonic(), 10, None)
            self.assertEqual(row["process_alive"], 0)
            self.assertEqual(row["cpu_pct"], "")
            self.assertEqual(row["active_connections"], "")
            self.assertEqual(ticks, 17)

    def test_fault_cli_returns_failure_and_records_dead_process(self):
        class Connection:
            def close(self):
                pass

        with exited_child() as pid, tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "fault-results.json"
            argv = [
                "fault_injector.py",
                "--watch-pid",
                str(pid),
                "--oversized-bytes",
                "8",
                "--output",
                str(output),
            ]
            with (
                mock.patch.object(sys, "argv", argv),
                mock.patch.object(fault_injector, "exchange", return_value="closed"),
                mock.patch.object(
                    fault_injector, "tls_socket", return_value=Connection()
                ),
                mock.patch.object(fault_injector, "health_check", return_value=True),
                mock.patch("builtins.print"),
            ):
                self.assertEqual(fault_injector.main(), 1)
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertTrue(report["server_healthy_after"])
            self.assertFalse(report["process_alive_before"])
            self.assertFalse(report["process_alive_after"])

    def test_current_process_still_counts_as_alive(self):
        self.assertTrue(fault_injector.process_alive(os.getpid()))
        row, _, _ = collect_metrics.sample(os.getpid(), 0, time.monotonic(), 10, None)
        self.assertEqual(row["process_alive"], 1)
        self.assertGreater(float(row["rss_mb"]), 0)

    def test_reaped_and_unwatched_processes_keep_existing_semantics(self):
        with exited_child() as pid:
            pass
        self.assertFalse(fault_injector.process_alive(pid))
        self.assertIsNone(fault_injector.process_alive(None))

    def test_procfs_state_parser_handles_terminal_and_live_states(self):
        for state in ("Z", "X", "x", "R", "S", "D", "T", "t", "I"):
            with self.subTest(state=state), mock.patch.object(
                Path,
                "read_text",
                return_value=(
                    f"Name:\ttest\nThreads:\t1\nState:\t{state} (state)\n"
                    "VmRSS:\t20 kB\n"
                ),
            ):
                status = collect_metrics.read_status(42)
                if state in {"Z", "X", "x"}:
                    self.assertFalse(status)
                else:
                    self.assertEqual(status, {"Threads": 1, "VmRSS": 20})


if __name__ == "__main__":
    unittest.main()
