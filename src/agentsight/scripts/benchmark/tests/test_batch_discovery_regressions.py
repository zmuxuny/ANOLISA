"""Discovery must survive session rotation between metadata reads."""

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_batch_analyze import batch_analyze


class BatchDiscoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)

    def session(self, name: str, mtime: int) -> Path:
        path = self.directory / name
        events = [
            {"type": "user", "message": {"content": "Inspect the project. " * 60}},
            {"type": "assistant", "message": {"content": "Project inspected."}},
        ]
        path.write_text("".join(json.dumps(event) + "\n" for event in events), encoding="utf-8")
        os.utime(path, (mtime, mtime))
        return path

    def remove_after_stat(self, disappearing: Path):
        original_stat = Path.stat

        def stat(path, *args, **kwargs):
            result = original_stat(path, *args, **kwargs)
            if path == disappearing:
                # Deterministically model rotation immediately after discovery.
                path.unlink()
            return result

        return patch.object(Path, "stat", stat)

    def test_rotation_after_metadata_read_does_not_abort_sorting(self) -> None:
        old = self.session("old.jsonl", 10)
        disappearing = self.session("rotated.jsonl", 30)
        recent = self.session("recent.jsonl", 20)
        with patch.object(Path, "rglob", return_value=iter([old, disappearing, recent])):
            with self.remove_after_stat(disappearing):
                files = batch_analyze.find_conversation_files([self.directory], min_size=0)
        self.assertEqual(files, [disappearing, recent, old])
        self.assertFalse(disappearing.exists())

    def test_unreadable_metadata_does_not_hide_healthy_sessions(self) -> None:
        unreadable = self.session("unreadable.jsonl", 30)
        healthy = self.session("healthy.jsonl", 20)
        original_stat = Path.stat

        def stat(path, *args, **kwargs):
            if path == unreadable:
                raise PermissionError("fixture: metadata unavailable")
            return original_stat(path, *args, **kwargs)

        with patch.object(Path, "rglob", return_value=iter([unreadable, healthy])):
            with patch.object(Path, "stat", stat):
                files = batch_analyze.find_conversation_files([self.directory], min_size=0)
        self.assertEqual(files, [healthy])

    def test_size_subagent_and_newest_first_filters_are_preserved(self) -> None:
        old = self.session("old.jsonl", 10)
        recent = self.session("recent.jsonl", 20)
        self.session("subagent-hidden.jsonl", 30)
        (self.directory / "small.jsonl").write_text("{}\n", encoding="utf-8")
        files = batch_analyze.find_conversation_files(
            [self.directory / "absent", self.directory], min_size=100
        )
        self.assertEqual(files, [recent, old])

    def test_cli_skips_rotated_session_and_analyzes_remaining_file(self) -> None:
        disappearing = self.session("rotated.jsonl", 30)
        healthy = self.session("healthy.jsonl", 20)
        arguments = [
            "batch-analyze.py", "--dir", str(self.directory), "--dim", "cost",
            "--min-steps", "2", "--binary", "fixture-analyzer",
        ]
        stdout, stderr = io.StringIO(), io.StringIO()
        completed = subprocess.CompletedProcess([], 0, stdout="{}", stderr="")
        with patch.object(sys, "argv", arguments):
            with patch.object(Path, "rglob", return_value=iter([disappearing, healthy])):
                with self.remove_after_stat(disappearing):
                    with patch.object(batch_analyze.subprocess, "run", return_value=completed) as run:
                        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                            batch_analyze.main()
        run.assert_called_once()
        self.assertEqual(json.loads(stdout.getvalue())["_source_file"], str(healthy))
        self.assertIn("Done: 1 analyzed, 1 skipped, 0 failed", stderr.getvalue())
        self.assertFalse(Path(run.call_args.args[0][1]).exists())


if __name__ == "__main__":
    unittest.main()
