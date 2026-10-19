"""Run real coverage gates against executed and wholly unexecuted sources."""

import contextlib
import importlib.util
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

CAMPAIGN = Path(__file__).resolve().parents[1] / "campaign"
sys.path.insert(0, str(CAMPAIGN))
import run_regression  # noqa: E402


@unittest.skipUnless(
    shutil.which("git")
    and all(
        importlib.util.find_spec(module) is not None
        for module in run_regression.REQUIRED_PYTHON_MODULES
    ),
    "requires Git and scripts/benchmark/requirements.txt coverage dependencies",
)
class SourceCoverageTests(unittest.TestCase):
    def run_fixture(self, section, *, execute_new=False, change_imported=False):
        with tempfile.TemporaryDirectory(prefix="sight-source-coverage-") as temporary:
            root = Path(temporary)
            benchmark = root / run_regression.BENCHMARK_PATH
            for directory in ("single_run", "campaign", "tests"):
                (benchmark / directory).mkdir(parents=True)
            existing = benchmark / "single_run" / "existing.py"
            existing.write_text("def value():\n    return 7\n", encoding="utf-8")
            # Coverage scope must not grow to unrelated repository source.
            (root / "unrelated.py").write_text(
                "raise RuntimeError('not benchmark source')\n", encoding="utf-8"
            )
            test_path = benchmark / "tests" / "test_fixture.py"
            test_path.write_text(
                "import runpy\n"
                "def test_existing():\n"
                f"    assert runpy.run_path({str(existing)!r})['value']() == 7\n",
                encoding="utf-8",
            )
            for command in (
                ["git", "init", "-q"],
                ["git", "add", "."],
                [
                    "git",
                    "-c",
                    "user.name=Fixture",
                    "-c",
                    "user.email=fixture@example.invalid",
                    "commit",
                    "-qm",
                    "fixture baseline",
                ],
            ):
                subprocess.run(command, cwd=root, check=True, capture_output=True)
            added = (
                existing if change_imported else benchmark / section / "unexecuted.py"
            )
            text = "".join(f"def value_{i}():\n    return {i}\n\n" for i in range(12))
            with added.open("a", encoding="utf-8") as handle:
                handle.write(text)
            if execute_new:
                with test_path.open("a", encoding="utf-8") as handle:
                    handle.write(
                        f"def test_new():\n    values = runpy.run_path({str(added)!r})\n"
                        "    for index in range(12):\n"
                        "        assert values[f'value_{index}']() == index\n"
                    )
            results = root / "results"
            original_check = run_regression.run_check

            def python_check(command, cwd, log_path, checks):
                if command[0] == "rustup":
                    # Rust gates are outside this Python coverage fixture.
                    checks.append({"command": "controlled Rust gate", "exit_code": 0})
                    return 0
                return original_check(command, cwd, log_path, checks)

            with (
                patch.object(run_regression, "REPO_ROOT", root),
                patch.object(run_regression, "AGENTSIGHT_DIR", root / "src/agentsight"),
                patch.object(run_regression, "run_check", python_check),
                patch.object(
                    sys,
                    "argv",
                    [
                        "run_regression.py",
                        "--results",
                        str(results),
                        "--compare-branch",
                        "HEAD",
                    ],
                ),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                result = run_regression.main()
            report = json.loads(
                (results / "regression.json").read_text(encoding="utf-8")
            )
            classes = ET.parse(results / "coverage.xml").findall(".//class")
            measured = {element.get("filename"): element for element in classes}
            added_name = added.name
            added_class = next(
                (
                    element
                    for name, element in measured.items()
                    if Path(name).name == added_name
                ),
                None,
            )
            return (
                result,
                report,
                added_class,
                (results / "diff-cover.log").read_text(encoding="utf-8"),
            )

    def test_never_imported_single_run_source_fails_both_gates(self):
        result, report, added, log = self.run_fixture("single_run")
        self.assertEqual(result, 1, log)
        self.assertNotEqual(report["checks"][1]["exit_code"], 0)
        self.assertNotEqual(report["checks"][3]["exit_code"], 0)
        self.assertIsNotNone(added)
        self.assertTrue(added.findall(".//line"))
        self.assertTrue(
            all(line.get("hits") == "0" for line in added.findall(".//line"))
        )

    def test_never_imported_campaign_source_fails_both_gates(self):
        result, report, added, log = self.run_fixture("campaign")
        self.assertEqual(result, 1, log)
        self.assertNotEqual(report["checks"][1]["exit_code"], 0)
        self.assertNotEqual(report["checks"][3]["exit_code"], 0)
        self.assertIsNotNone(added)

    def test_exercised_new_source_still_passes(self):
        result, report, added, log = self.run_fixture("campaign", execute_new=True)
        self.assertEqual(result, 0, log)
        self.assertTrue(all(check["exit_code"] == 0 for check in report["checks"]))
        self.assertIsNotNone(added)
        self.assertTrue(added.findall(".//line"))
        self.assertTrue(
            all(int(line.get("hits")) > 0 for line in added.findall(".//line"))
        )

    def test_uncovered_lines_in_imported_source_still_fail(self):
        result, report, added, log = self.run_fixture(
            "single_run", change_imported=True
        )
        self.assertEqual(result, 1, log)
        self.assertNotEqual(report["checks"][3]["exit_code"], 0)
        self.assertIsNotNone(added)


if __name__ == "__main__":
    unittest.main()
