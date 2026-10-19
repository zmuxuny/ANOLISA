"""Invalid pacing options are argparse errors, before any server or TLS setup."""

import importlib.util
import subprocess
import sys
import unittest
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "single_run" / "mock_llm_server.py"


class MockTokenArgumentTests(unittest.TestCase):
    def run_cli(self, *options):
        return subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--cert",
                "unused.pem",
                "--key",
                "unused.key",
                *options,
            ],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=10,
        )

    def assert_pacing_error(self, options):
        result = self.run_cli(*options)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("usage:", result.stderr)
        self.assertIn(
            "positive --tokens-per-second and --output-tokens require HTTP/1.1 SSE",
            result.stderr,
        )
        self.assertNotIn("Traceback", result.stderr)
        self.assertNotIn("unused.pem", result.stderr)

    def test_both_token_options_are_required(self):
        for options in (("--tokens-per-second", "10"), ("--output-tokens", "3")):
            with self.subTest(options=options):
                self.assert_pacing_error(options)

    def test_invalid_rates_report_usage(self):
        for value in ("0", "-1", "nan", "inf"):
            with self.subTest(value=value):
                self.assert_pacing_error(
                    ("--tokens-per-second", value, "--output-tokens", "3")
                )

    def test_invalid_output_count_reports_usage(self):
        for value in ("0", "-1"):
            with self.subTest(value=value):
                self.assert_pacing_error(
                    ("--tokens-per-second", "10", "--output-tokens", value)
                )

    def test_pacing_requires_http1_sse(self):
        for flag in ("--json", "--http2"):
            with self.subTest(flag=flag):
                self.assert_pacing_error(
                    ("--tokens-per-second", "10", "--output-tokens", "3", flag)
                )

    def test_help_remains_successful(self):
        result = self.run_cli("--help")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--tokens-per-second", result.stdout)
        self.assertEqual(result.stderr, "")

    def test_valid_pacing_arguments_keep_their_values(self):
        spec = importlib.util.spec_from_file_location("mock_args", SCRIPT)
        server = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(server)
        args = server.build_parser().parse_args(
            [
                "--cert",
                "fixture.pem",
                "--key",
                "fixture.key",
                "--tokens-per-second",
                "2.5",
                "--output-tokens",
                "7",
            ]
        )
        self.assertEqual(args.tokens_per_second, 2.5)
        self.assertEqual(args.output_tokens, 7)
        self.assertFalse(args.json)
        self.assertFalse(args.http2)


if __name__ == "__main__":
    unittest.main()
