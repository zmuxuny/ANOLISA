"""Real validator CLI checks for finite, bounded polling parameters."""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "single_run" / "validate_results.py"


class ValidatorTimingTests(unittest.TestCase):
    def run_validator(self, arguments: list[str], *, streaming: bool = False):
        with tempfile.TemporaryDirectory(prefix="validator-timing-") as directory:
            root = Path(directory)
            database = root / "capture.db"
            with sqlite3.connect(database) as connection:
                connection.execute("CREATE TABLE unrelated (value INTEGER)")
            ledger = root / "requests.jsonl"
            ledger.write_text(
                '{"request_id":"missing","http_status":200}\n', encoding="utf-8"
            )
            output = root / "result.json"
            command = [
                sys.executable,
                str(SCRIPT),
                "--db",
                str(database),
                "--load-results",
                str(ledger),
                "--request-log",
                str(ledger),
                "--output",
                str(output),
                *arguments,
            ]
            if streaming:
                marker = root / "completed"
                marker.touch()
                command.extend(["--completion-marker", str(marker)])
            try:
                result = subprocess.run(
                    command, capture_output=True, text=True, timeout=2
                )
            except subprocess.TimeoutExpired:
                self.fail("validator did not reject an unbounded polling parameter")
            report = (
                json.loads(output.read_text(encoding="utf-8"))
                if output.exists()
                else None
            )
            return result, report

    def assert_rejected(self, option: str, *, streaming: bool):
        for value in ("nan", "inf", "-inf"):
            with self.subTest(option=option, value=value, streaming=streaming):
                result, report = self.run_validator(
                    [
                        "--wait-seconds=0.01",
                        "--poll-interval=0.001",
                        f"{option}={value}",
                    ],
                    streaming=streaming,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("finite", result.stderr)
                self.assertNotIn("Traceback", result.stderr)
                self.assertIsNone(report)

    def test_nonfinite_wait_is_rejected(self):
        self.assert_rejected("--wait-seconds", streaming=False)

    def test_streaming_nonfinite_wait_is_rejected(self):
        self.assert_rejected("--wait-seconds", streaming=True)

    def test_nonfinite_poll_is_rejected(self):
        self.assert_rejected("--poll-interval", streaming=False)

    def test_streaming_nonfinite_poll_is_rejected(self):
        self.assert_rejected("--poll-interval", streaming=True)

    def test_zero_wait_keeps_incomplete_report(self):
        for streaming in (False, True):
            with self.subTest(streaming=streaming):
                result, report = self.run_validator(
                    ["--wait-seconds=0"], streaming=streaming
                )
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertEqual(report["sent"], 1)
                self.assertEqual(report["missing_ids"], ["missing"])

    def test_finite_polling_keeps_incomplete_report(self):
        result, report = self.run_validator(
            ["--wait-seconds=0.01", "--poll-interval=0.001"]
        )
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(report["complete"], 0)

    def test_existing_negative_and_zero_bounds_are_rejected(self):
        for argument in (
            "--wait-seconds=-1",
            "--poll-interval=0",
            "--poll-interval=-1",
        ):
            with self.subTest(argument=argument):
                result, report = self.run_validator([argument])
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("non-negative", result.stderr)
                self.assertIsNone(report)


if __name__ == "__main__":
    unittest.main()
