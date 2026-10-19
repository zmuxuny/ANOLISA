"""Exercise collector deadlines and signal-driven final samples as real processes."""

import csv
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import contextmanager
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "single_run/collect_metrics.py"


def rows(path):
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


@contextmanager
def collector(root, *arguments):
    path = root / "metrics.csv"
    process = subprocess.Popen(
        [
            sys.executable,
            str(SCRIPT),
            "--pid",
            str(os.getpid()),
            "--output",
            str(path),
            *arguments,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        yield process, path
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=5)


def await_first_sample(process, path):
    deadline = time.monotonic() + 3
    while not rows(path):
        if process.poll() is not None:
            raise AssertionError("collector exited before its first sample")
        if time.monotonic() > deadline:
            raise AssertionError("collector did not publish its first sample")
        time.sleep(0.01)


@unittest.skipUnless(sys.platform == "linux", "collector requires Linux procfs")
class CollectorWaitTests(unittest.TestCase):
    def test_duration_bounds_a_long_sample_interval(self):
        with tempfile.TemporaryDirectory() as directory:
            start = time.monotonic()
            with collector(
                Path(directory), "--interval", "20", "--duration", "0.15"
            ) as (process, path):
                try:
                    _, errors = process.communicate(timeout=2)
                except subprocess.TimeoutExpired:
                    self.fail("collector slept past its duration deadline")
                self.assertEqual(process.returncode, 0, errors)
                self.assertGreaterEqual(time.monotonic() - start, 0.15)
                self.assertEqual(len(rows(path)), 2)

    def test_stop_signals_interrupt_wait_and_preserve_final_counter(self):
        for sig in (signal.SIGTERM, signal.SIGINT):
            with self.subTest(signal=sig), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                internal = root / "internal.txt"
                internal.write_text("completed=1\n", encoding="utf-8")
                with collector(
                    root, "--interval", "20", "--metrics-file", str(internal)
                ) as (process, path):
                    await_first_sample(process, path)
                    internal.write_text("completed=7\n", encoding="utf-8")
                    process.send_signal(sig)
                    try:
                        _, errors = process.communicate(timeout=2)
                    except subprocess.TimeoutExpired:
                        self.fail("stop signal did not interrupt the sampling wait")
                    self.assertEqual(process.returncode, 0, errors)
                    samples = rows(path)
                    self.assertEqual(len(samples), 2)
                    self.assertEqual(samples[0]["completed"], "1")
                    self.assertEqual(samples[-1]["completed"], "7")

    def test_regular_intervals_keep_multiple_samples(self):
        with tempfile.TemporaryDirectory() as directory, collector(
            Path(directory), "--interval", "0.02", "--duration", "0.1"
        ) as (process, path):
            _, errors = process.communicate(timeout=3)
            self.assertEqual(process.returncode, 0, errors)
            self.assertGreaterEqual(len(rows(path)), 3)
            self.assertEqual(rows(path)[0]["cpu_interval_seconds"], "")
            self.assertTrue(rows(path)[-1]["cpu_interval_seconds"])

    def test_signal_during_start_barrier_does_not_create_fake_samples(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with collector(root, "--start-file", str(root / "absent.json")) as (
                process,
                path,
            ):
                # The process is sleeping in the barrier, after signal handlers are installed.
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline:
                    status = Path(f"/proc/{process.pid}/status").read_text(
                        encoding="utf-8"
                    )
                    caught = next(
                        line.split()[1]
                        for line in status.splitlines()
                        if line.startswith("SigCgt:")
                    )
                    if int(caught, 16) & (1 << (signal.SIGTERM - 1)):
                        break
                    time.sleep(0.01)
                else:
                    self.fail("collector did not install its signal handler")
                process.send_signal(signal.SIGTERM)
                _, errors = process.communicate(timeout=2)
                self.assertEqual(process.returncode, 0, errors)
                self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
