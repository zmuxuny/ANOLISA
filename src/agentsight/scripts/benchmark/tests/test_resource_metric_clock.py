"""Use collected monotonic time for trends and resource recovery intervals."""

import csv
import gzip
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

BENCHMARK = Path(__file__).parents[1]
sys.path.insert(0, str(BENCHMARK / "single_run"))
sys.path.insert(0, str(BENCHMARK / "campaign"))

import campaign_evidence
import render_report


def write_metrics(root, walls, monotonic, values, compressed=False):
    folder = root / "measurement"
    folder.mkdir(exist_ok=True)
    path = folder / ("metrics.csv.gz" if compressed else "metrics.csv")
    fields = ["timestamp", "rss_mb"]
    if monotonic is not None:
        fields.append("monotonic_timestamp")
    text = io.StringIO(newline="")
    writer = csv.DictWriter(text, fieldnames=fields)
    writer.writeheader()
    for index, (wall, value) in enumerate(zip(walls, values)):
        row = {"timestamp": wall, "rss_mb": value}
        if monotonic is not None:
            row["monotonic_timestamp"] = monotonic[index]
        writer.writerow(row)
    data = text.getvalue().encode("utf-8")
    path.write_bytes(gzip.compress(data) if compressed else data)
    return path


class ResourceMetricClockTests(unittest.TestCase):
    def test_report_cli_uses_elapsed_time_across_forward_wall_jump(self):
        for compressed in (False, True):
            with self.subTest(
                compressed=compressed
            ), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                path = write_metrics(
                    root,
                    [100, 101, 3702, 3703],
                    [10, 11, 12, 13],
                    [10, 20, 30, 40],
                    compressed,
                )
                before = path.read_bytes()
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
                        "3",
                        "--metrics",
                        str(path),
                    ],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                summary = json.loads(
                    (root / "summary.json").read_text(encoding="utf-8")
                )["resources"]["rss_mb"]
                self.assertAlmostEqual(summary["slope_per_hour"], 36000)
                self.assertEqual(summary["rolling_5m_max_increase"], 30)
                self.assertIn(
                    "36000.00", (root / "report.md").read_text(encoding="utf-8")
                )
                self.assertEqual(path.read_bytes(), before)

    def test_wall_rollback_cannot_reverse_resource_growth(self):
        with tempfile.TemporaryDirectory() as directory:
            path = write_metrics(
                Path(directory), [100, 99, 98, 97], [10, 11, 12, 13], [10, 20, 30, 40]
            )
            self.assertAlmostEqual(
                render_report.summarize_resources(path)["rss_mb"]["slope_per_hour"],
                36000,
            )

    def test_recovery_window_uses_collected_monotonic_time(self):
        for compressed in (False, True):
            with self.subTest(
                compressed=compressed
            ), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                write_metrics(
                    root,
                    [100, 101, 3702, 3703],
                    [10, 11, 12, 13],
                    [20, 10, 10, 10],
                    compressed,
                )
                samples = campaign_evidence.resource_samples(
                    root / "run-result.json", "rss_mb"
                )
                self.assertEqual(samples, [(10, 20), (11, 10), (12, 10), (13, 10)])
                self.assertEqual(
                    campaign_evidence.continuous_recovery(
                        samples, 10, 0, 2, higher_is_better=False
                    ),
                    1,
                )

    def test_legacy_files_without_monotonic_column_keep_wall_time(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = write_metrics(root, [100, 101, 102], None, [10, 20, 30])
            self.assertAlmostEqual(
                render_report.summarize_resources(path)["rss_mb"]["slope_per_hour"],
                36000,
            )
            self.assertEqual(
                campaign_evidence.resource_samples(root / "run-result.json", "rss_mb"),
                [(100, 10), (101, 20), (102, 30)],
            )

    def test_invalid_monotonic_rows_do_not_mix_clock_epochs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = write_metrics(
                root, [100, 101, 102, 103], [10, "", "NaN", 13], [10, 10000, 10000, 40]
            )
            summary = render_report.summarize_resources(path)["rss_mb"]
            self.assertEqual(summary["max"], 40)
            self.assertAlmostEqual(summary["slope_per_hour"], 36000)
            self.assertEqual(
                campaign_evidence.resource_samples(root / "run-result.json", "rss_mb"),
                [(10, 10), (13, 40)],
            )

    def test_monotonic_column_rejects_calendar_dates(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = write_metrics(
                root, [100, 101, 103], [10, "2026-10-19T00:00:00Z", 13], [10, 9999, 40]
            )
            self.assertEqual(
                campaign_evidence.resource_samples(root / "run-result.json", "rss_mb"),
                [(10, 10), (13, 40)],
            )
            self.assertEqual(
                render_report.summarize_resources(path)["rss_mb"]["max"], 40
            )

    def test_legacy_recovery_accepts_rfc3339_wall_time(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_metrics(
                root,
                ["1970-01-01T00:01:40Z", "1970-01-01T00:01:41+00:00"],
                None,
                [10, 20],
            )
            self.assertEqual(
                campaign_evidence.resource_samples(root / "run-result.json", "rss_mb"),
                [(100, 10), (101, 20)],
            )

    def test_monotonic_zero_is_valid_without_wall_timestamp(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = write_metrics(root, ["", ""], [0, 1], [10, 20])
            self.assertAlmostEqual(
                render_report.summarize_resources(path)["rss_mb"]["slope_per_hour"],
                36000,
            )
            self.assertEqual(
                campaign_evidence.resource_samples(root / "run-result.json", "rss_mb"),
                [(0, 10), (1, 20)],
            )


if __name__ == "__main__":
    unittest.main()
