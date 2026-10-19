"""Coverage diffs must describe source lines regardless of Git display settings."""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "campaign"))
import run_regression


class CoverageDiffConfigTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.environment = mock.patch.dict(
            os.environ,
            {
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_CONFIG_GLOBAL": os.devnull,
            },
        )
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.git("init", "-q")
        self.benchmark = self.root / run_regression.BENCHMARK_PATH
        self.benchmark.mkdir(parents=True)
        self.tracked = self.benchmark / "tracked.py"
        self.tracked.write_text("VALUE = 1\n", encoding="utf-8")
        (self.root / ".gitattributes").write_text(
            "*.py diff=fixture\n", encoding="utf-8"
        )
        self.git("add", ".")
        self.git(
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "-qm",
            "fixture",
        )
        self.tracked.write_text("VALUE = 1\nUNCOVERED = 2\n", encoding="utf-8")
        (self.benchmark / "new.py").write_text("NEW_UNCOVERED = 3\n", encoding="utf-8")
        self.source = mock.patch.object(run_regression, "REPO_ROOT", self.root)
        self.source.start()
        self.addCleanup(self.source.stop)
        self.expected = self.diff()
        self.index_before = (self.root / ".git/index").read_bytes()
        self.head_before = self.git("rev-parse", "HEAD").stdout

    def git(self, *args):
        return subprocess.run(
            ["git", *args], cwd=self.root, capture_output=True, check=True
        )

    def diff(self):
        output = self.root / "benchmark.diff"
        run_regression.write_benchmark_diff("HEAD", output)
        return output.read_bytes()

    def assert_canonical_diff(self):
        config_before = (self.root / ".git/config").read_bytes()
        result = self.diff()
        self.assertEqual(result, self.expected)
        self.assertIn(b"+UNCOVERED = 2", result)
        self.assertIn(b"+NEW_UNCOVERED = 3", result)
        self.assertNotIn(b"\x1b[", result)
        self.assertEqual((self.root / ".git/index").read_bytes(), self.index_before)
        self.assertEqual(self.git("rev-parse", "HEAD").stdout, self.head_before)
        self.assertEqual((self.root / ".git/config").read_bytes(), config_before)

    def test_forced_color_cannot_hide_changed_lines(self):
        self.git("config", "color.ui", "always")
        self.assert_canonical_diff()

    def test_no_prefix_cannot_change_coverage_file_identity(self):
        self.git("config", "diff.noprefix", "true")
        self.assert_canonical_diff()

    def test_mnemonic_prefix_cannot_change_coverage_file_identity(self):
        self.git("config", "diff.mnemonicPrefix", "true")
        self.assert_canonical_diff()

    def test_textconv_cannot_replace_source_lines(self):
        converter = self.root / "display-filter.sh"
        converter.write_text("#!/bin/sh\nprintf 'rendered view\\n'\n", encoding="utf-8")
        converter.chmod(0o755)
        self.git("config", "diff.fixture.textconv", str(converter))
        self.assert_canonical_diff()

    def test_default_configuration_remains_unchanged(self):
        self.assert_canonical_diff()


if __name__ == "__main__":
    unittest.main()
