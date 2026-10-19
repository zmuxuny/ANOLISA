"""Resource configuration and reports use UTF-8 independently of locale."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parents[1] / "single_run"
TEXT = "\u4e2d\u6587 caf\u00e9 \U0001f9ea"


@unittest.skipUnless(
    sys.platform == "linux", "resource tracing and C-locale fixtures require Linux"
)
class ResourceArtifactEncodingTests(unittest.TestCase):
    def run_child(self, root, body, *arguments):
        helper = root / "probe.py"
        helper.write_text(
            "import locale, sys\nfrom pathlib import Path\n"
            "assert locale.getencoding().lower() in ('ansi_x3.4-1968', 'ascii')\n"
            f"sys.path.insert(0, {str(HERE)!r})\n" + body,
            encoding="utf-8",
        )
        return subprocess.run(
            [sys.executable, str(helper), *map(str, arguments)],
            env={
                **os.environ,
                "LC_ALL": "C",
                "LANG": "C",
                "PYTHONUTF8": "0",
                "PYTHONCOERCECLOCALE": "0",
                "PYTHONIOENCODING": "utf-8",
            },
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=15,
        )

    def report_fixture(
        self, *, source="plain", worker_error=None, run_error=None, log=None
    ):
        with tempfile.TemporaryDirectory(
            prefix="sight-artifact-encoding-"
        ) as temporary:
            root = Path(temporary)
            (root / "run").mkdir()
            if worker_error is not None:
                (root / "run/worker-result.json").write_text(
                    json.dumps(
                        {"status": "failed", "error": worker_error}, ensure_ascii=False
                    ),
                    encoding="utf-8",
                )
            if run_error is not None:
                (root / "run-error.txt").write_text(run_error, encoding="utf-8")
            if log is not None:
                (root / "run/trace.log").write_bytes(log)
            child = self.run_child(
                root,
                "import resource_report\n"
                f"sources = {{'run': {{'path': {source!a}}}}}\n"
                "assert resource_report.report(Path(sys.argv[1]), sources) is False\n",
                root,
            )
            self.assertEqual(child.returncode, 0, child.stderr)
            text = (root / "resource-report.txt").read_text(encoding="utf-8")
            summary = json.loads(
                (root / "resource-summary.json").read_text(encoding="utf-8")
            )
            self.assertFalse(summary["valid"])
            return text, summary

    def test_report_preserves_non_ascii_source_label(self):
        text, summary = self.report_fixture(source=TEXT)
        self.assertIn(TEXT, text)
        self.assertEqual(summary["runs"]["run"]["source"]["path"], TEXT)

    def test_report_reads_utf8_worker_diagnostic(self):
        text, summary = self.report_fixture(worker_error=TEXT)
        self.assertIn(TEXT, text)
        self.assertEqual(summary["runs"]["run"]["error"], TEXT)

    def test_report_reads_utf8_run_error(self):
        text, _ = self.report_fixture(run_error=TEXT)
        self.assertIn("Error: " + TEXT, text)

    def test_log_tail_preserves_utf8_and_replaces_only_invalid_byte(self):
        text, _ = self.report_fixture(
            worker_error="trace.log", log=TEXT.encode("utf-8") + b"\xff\n"
        )
        self.assertIn(TEXT + "\ufffd", text)

    def test_ascii_missing_artifacts_remain_invalid(self):
        text, summary = self.report_fixture()
        self.assertIn("INVALID; do not infer", text)
        self.assertEqual(summary["runs"]["run"]["source"]["path"], "plain")

    def test_resource_cli_decodes_utf8_config_before_validation(self):
        with tempfile.TemporaryDirectory(prefix="sight-config-encoding-") as temporary:
            root = Path(temporary)
            config = root / "config.json"
            config.write_text(
                json.dumps(
                    {
                        "description": TEXT,
                        "features": {"sqlite_storage": {"enabled": False}},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            child = self.run_child(
                root,
                "import resource_run\n"
                "sys.argv = ['resource_run', '--no-sudo', '--config', sys.argv[1]]\n"
                "try:\n    resource_run.main()\n"
                "except RuntimeError as error:\n"
                "    expected = 'capture validation requires "
                "features.sqlite_storage.enabled=true'\n"
                "    assert str(error) == expected\n"
                "else:\n    raise AssertionError('disabled storage accepted')\n",
                config,
            )
            self.assertEqual(child.returncode, 0, child.stderr)
            self.assertEqual(
                sorted(p.name for p in root.iterdir()), ["config.json", "probe.py"]
            )

    def test_orchestration_keeps_utf8_setup_and_cleanup_errors(self):
        for cleanup_error in (False, True):
            with self.subTest(cleanup_error=cleanup_error), tempfile.TemporaryDirectory(
                prefix="sight-resource-error-"
            ) as temporary:
                root = Path(temporary)
                config = root / "config.json"
                config.write_text("{}", encoding="utf-8")
                output = root / "results"
                child = self.run_child(
                    root,
                    "import resource_run\nfrom unittest.mock import patch\n"
                    f"text = {TEXT!a}\ncleanup_error = {cleanup_error}\n"
                    "class Inputs:\n"
                    "    def __init__(self, *_): pass\n"
                    "    def prepare(self, *_):\n"
                    "        raise RuntimeError('setup failed' if cleanup_error else text)\n"
                    "    def close(self):\n"
                    "        if cleanup_error: raise RuntimeError(text)\n"
                    "sys.argv = ['resource_run', '--no-sudo', '--config', sys.argv[1], "
                    "'--output-dir', sys.argv[2]]\n"
                    "with patch.object(resource_run, 'Inputs', Inputs), "
                    "patch.object(resource_run, 'ensure_python'), "
                    "patch.object(resource_run, 'cache_directory', "
                    "return_value=Path(sys.argv[2])/'cache'), "
                    "patch.object(resource_run, 'run_logged', "
                    "side_effect=AssertionError('must not launch workloads')):\n"
                    "    assert resource_run.main() == 1\n",
                    config,
                    output,
                )
                self.assertEqual(child.returncode, 0, child.stderr)
                self.assertEqual(
                    (output / "run-error.txt").read_text(encoding="utf-8"), TEXT + "\n"
                )
                self.assertIn(
                    TEXT, (output / "resource-report.txt").read_text(encoding="utf-8")
                )


if __name__ == "__main__":
    unittest.main()
