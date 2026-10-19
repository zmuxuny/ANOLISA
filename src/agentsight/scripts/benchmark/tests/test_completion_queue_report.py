"""Preserve exported completion queue gauges through benchmark reports."""

import csv
import gzip
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

BENCHMARK = Path(__file__).parents[1]
sys.path.insert(0, str(BENCHMARK / "single_run"))
sys.path.insert(0, str(BENCHMARK / "campaign"))

import aggregate_report


class CompletionQueueReportTests(unittest.TestCase):
    def render(self, root, metrics):
        result = subprocess.run(
            [
                sys.executable,
                str(BENCHMARK / "single_run/render_report.py"),
                "--output",
                str(root / "report.md"),
                "--summary-output",
                str(root / "summary.json"),
                "--protocol",
                "sse",
                "--qps",
                "1",
                "--duration",
                "1",
                "--metrics",
                str(metrics),
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads((root / "summary.json").read_text(encoding="utf-8"))

    @unittest.skipUnless(sys.platform == "linux", "collector requires Linux procfs")
    def test_real_collector_gauges_reach_summary_and_markdown(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot = root / "internal.prom"
            snapshot.write_text(
                "agentsight_completion_queue_count 5\nagentsight_completion_queue_bytes 4096\n",
                encoding="utf-8",
            )
            metrics = root / "metrics.csv"
            result = subprocess.run(
                [
                    sys.executable,
                    str(BENCHMARK / "single_run/collect_metrics.py"),
                    "--pid",
                    str(os.getpid()),
                    "--output",
                    str(metrics),
                    "--metrics-file",
                    str(snapshot),
                    "--interval",
                    "0.01",
                    "--duration",
                    "0.03",
                ],
                capture_output=True,
                text=True,
                check=False,
                timeout=5,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            with metrics.open(encoding="utf-8", newline="") as handle:
                samples = list(csv.DictReader(handle))
            self.assertTrue(samples)
            self.assertEqual(samples[0]["completion_queue_bytes"], "4096")
            before = metrics.read_bytes()
            summary = self.render(root, metrics)
            self.assertEqual(summary["resources"]["completion_queue_count"]["max"], 5)
            self.assertEqual(
                summary["resources"]["completion_queue_bytes"]["avg"], 4096
            )
            markdown = (root / "report.md").read_text(encoding="utf-8")
            self.assertIn("| completion_queue_count |", markdown)
            self.assertIn("| completion_queue_bytes | 4096.00 bytes |", markdown)
            self.assertEqual(metrics.read_bytes(), before)

    def test_gzip_metrics_include_queue_growth_statistics(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "metrics.csv.gz"
            path.write_bytes(
                gzip.compress(
                    b"timestamp,completion_queue_count,completion_queue_bytes\n1,0,0\n2,2,1024\n3,4,2048\n"
                )
            )
            summary = self.render(root, path)["resources"]
            self.assertEqual(summary["completion_queue_count"]["p99"], 4)
            self.assertEqual(
                summary["completion_queue_bytes"]["slope_per_hour"], 3686400
            )
            self.assertEqual(
                summary["completion_queue_bytes"]["rolling_5m_max_increase"], 2048
            )

    def test_missing_queue_samples_remain_unknown_not_zero(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "metrics.csv"
            path.write_text("timestamp,rss_mb\n1,50\n", encoding="utf-8")
            summary = self.render(root, path)["resources"]
            self.assertTrue(
                all(
                    value is None
                    for value in summary["completion_queue_count"].values()
                )
            )
            self.assertTrue(
                all(
                    value is None
                    for value in summary["completion_queue_bytes"].values()
                )
            )
            self.assertNotIn(
                "| completion_queue_count |",
                (root / "report.md").read_text(encoding="utf-8"),
            )

    def test_soak_report_displays_both_queue_peak_units(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run = {
                "scenario": "soak",
                "version": "baseline",
                "duration_seconds": 3,
                "summary": {
                    "resources": {
                        "completion_queue_count": {"max": 7},
                        "completion_queue_bytes": {"max": 8192},
                    }
                },
                "evaluation": {"verdict": "INCONCLUSIVE"},
            }
            aggregate_report.write_soak(root, [(root / "run-result.json", run)])
            report = (root / "soak-report.md").read_text(encoding="utf-8")
            self.assertIn("Completion queue count/bytes max", report)
            self.assertIn("7.00/8192.00 bytes", report)
            widths = [
                len(line.split("|"))
                for line in report.splitlines()
                if line.startswith("|")
            ]
            self.assertEqual(len(set(widths)), 1)

    def test_empty_soak_report_keeps_a_complete_table_row(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            aggregate_report.write_soak(root, [])
            report = (root / "soak-report.md").read_text(encoding="utf-8")
            self.assertIn("NOT EXECUTED", report)
            widths = [
                len(line.split("|"))
                for line in report.splitlines()
                if line.startswith("|")
            ]
            self.assertEqual(len(set(widths)), 1)


if __name__ == "__main__":
    unittest.main()
