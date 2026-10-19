"""Keep old and current h2load summaries distinct through report generation."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SINGLE_RUN = Path(__file__).resolve().parents[1] / "single_run"
sys.path.insert(0, str(SINGLE_RUN))
import h2load_stats

# nghttp2 v1.69.0 and v1.70.0 src/h2load.cc emit this column order and
# the shortened "request" label. Older releases use "time for request".
MODERN = """finished in 1.10s, 90.83 req/s, 10.65KB/s
requests: 100 total, 100 started, 100 done, 98 succeeded, 2 failed, 1 errored, 1 timeout
                 min         max         median     p95        p99        mean         sd        +/- sd
request     :   120us      1.20s       9.00ms      90.00ms     120.00ms    12.50ms     2.00ms    98.00%
connect     :   1.00ms     4.00ms      2.00ms      3.00ms      4.00ms     2.50ms      0.50ms    90.00%
"""


class H2loadLayoutTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="h2load-layout-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.log = self.root / "h2load.log"

    def parse(self, text):
        self.log.write_text(text, encoding="utf-8")
        return h2load_stats.summarize_h2load(self.log)

    def test_current_layout_keeps_mean_and_percentiles_separate(self):
        result = self.parse(MODERN)
        self.assertEqual(result["latency"], {
            "first": None, "last": None, "min": 0.12, "max": 1200.0,
            "avg": 12.5, "p50": 9.0, "p95": 90.0, "p99": 120.0,
        })
        self.assertEqual((result["requests"], result["http_success"], result["timeouts"]), (100, 98, 1))
        self.assertEqual(result["throughput"], 90.83)

    def test_legacy_layout_does_not_invent_percentiles(self):
        result = self.parse("time for request: 120us 1.20s 12.50ms 2.00ms 98.00%\n")
        self.assertEqual(result["latency"]["avg"], 12.5)
        self.assertEqual(result["latency"]["min"], 0.12)
        self.assertEqual(result["latency"]["max"], 1200.0)
        for key in ("p50", "p95", "p99"):
            self.assertIsNone(result["latency"][key])

    def test_current_layout_accepts_tabs_and_crlf(self):
        result = self.parse(MODERN.replace("request     :", "\trequest\t:").replace("\n", "\r\n"))
        self.assertEqual(result["latency"]["avg"], 12.5)
        self.assertEqual(result["latency"]["p99"], 120.0)

    def test_incomplete_current_row_does_not_shift_mean(self):
        result = self.parse("request: 1ms 20ms 3ms 4ms\n")
        self.assertTrue(all(value is None for value in result["latency"].values()))

    def test_bad_duration_stays_unavailable_without_shifting_columns(self):
        result = self.parse(MODERN.replace("90.00ms", "unavailable"))
        self.assertIsNone(result["latency"]["p95"])
        self.assertEqual(result["latency"]["avg"], 12.5)
        self.assertEqual(result["latency"]["p99"], 120.0)

    def test_missing_request_timing_does_not_consume_connect_row(self):
        result = self.parse("\n".join(line for line in MODERN.splitlines() if not line.startswith("request ")))
        self.assertTrue(result["available"])
        self.assertTrue(all(value is None for value in result["latency"].values()))

    def test_real_report_cli_preserves_current_latency(self):
        self.log.write_text(MODERN, encoding="utf-8")
        report = self.root / "report.md"
        summary = self.root / "summary.json"
        result = subprocess.run(
            [sys.executable, str(SINGLE_RUN / "render_report.py"),
             "--output", str(report), "--summary-output", str(summary),
             "--protocol", "h2", "--qps", "100", "--duration", "1.1",
             "--load-log", str(self.log)],
            capture_output=True, text=True, timeout=10, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        latency = json.loads(summary.read_text(encoding="utf-8"))["latency_ms"]
        self.assertEqual(latency["avg"], 12.5)
        self.assertEqual(latency["p99"], 120.0)
        rendered = report.read_text(encoding="utf-8")
        self.assertIn("h2load request time", rendered)
        self.assertIn("120.00", rendered)
        self.assertIn("12.50", rendered)


if __name__ == "__main__":
    unittest.main()
