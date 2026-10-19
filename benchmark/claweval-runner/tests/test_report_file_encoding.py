# Copyright 2026 Alibaba Cloud
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Run both report entry points with UTF-8 assets and an ASCII file locale."""

import csv
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


@unittest.skipUnless(os.name == "posix", "requires a POSIX C locale")
class ReportEncodingTests(unittest.TestCase):
    def run_report(self, script_name, mode):
        unicode_text = "报告 café 📊"
        label = "ASCII task" if mode == "ascii" else unicode_text
        reason = "fixture reason" if mode == "ascii" else "缺少结果 café 📊"
        literal_unicode = mode == "unicode-input"
        with tempfile.TemporaryDirectory(prefix="ce-report-encoding-") as directory:
            root = Path(directory)
            traces = root / "traces"
            traces.mkdir()
            tasks = root / "tasks"
            task = tasks / "T001_demo"
            task.mkdir(parents=True)
            (task / "task.yaml").write_text(
                yaml.safe_dump(
                    {"task_id": "T001_demo", "task_name": label, "prompt": {"text": label}},
                    allow_unicode=literal_unicode,
                ),
                encoding="utf-8",
            )
            trace_name = "T001_demo_ab12.jsonl"
            records = [
                {"type": "trace_end", "wall_time_s": 1, "total_turns": 1, "note": label},
                {
                    "type": "grading_result",
                    "passed": False,
                    "task_score": 0.2,
                    "scores": {"completion": 0.2},
                    "judge_calls": [],
                },
            ]
            (traces / trace_name).write_text(
                "".join(
                    json.dumps(record, ensure_ascii=not literal_unicode) + "\n"
                    for record in records
                ),
                encoding="utf-8",
            )
            batch = [
                {
                    "task_id": "T001_demo",
                    "task_name": label,
                    "difficulty": "easy",
                    "avg_score": 0.2,
                    "avg_passed": False,
                    "trials": [
                        {
                            "trace": trace_name,
                            "passed": False,
                            "task_score": 0.2,
                            "wall_time_s": 1,
                            "input_tokens": 2,
                            "output_tokens": 1,
                        }
                    ],
                }
            ]
            (traces / "batch_results.json").write_text(
                json.dumps(batch, ensure_ascii=not literal_unicode), encoding="utf-8"
            )
            config = root / "config.yaml"
            config.write_text(
                ("# " + label + "\n" if literal_unicode else "")
                + yaml.safe_dump(
                    {
                        "defaults": {"trace_dir": str(traces), "tasks_dir": str(tasks)},
                        "judge": {"api_key": "fixture-key", "model_id": "fixture-model"},
                    }
                ),
                encoding="utf-8",
            )
            output = root / "output"
            program = """
import importlib.util
import json
import locale
import sys
import types
assert sys.flags.utf8_mode == 0
assert locale.getpreferredencoding(False).lower() in ("ascii", "ansi_x3.4-1968")
stub = types.ModuleType("openai")
def forbidden_client(*args, **kwargs):
    raise AssertionError("No external LLM client may be constructed")
stub.OpenAI = forbidden_client
sys.modules["openai"] = stub
spec = importlib.util.spec_from_file_location("report_entry", sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
reason = json.loads(sys.argv[2])
module.llm_classify_failure = lambda *args, **kwargs: {
    "category": "incorrect_execution", "key_reason_zh": reason,
}
sys.argv = [sys.argv[1], *sys.argv[3:]]
module.main()
"""
            result = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    program,
                    str(SCRIPTS / script_name),
                    json.dumps(reason),
                    "--config",
                    str(config),
                    "--trace-dir",
                    str(traces),
                    "--output-dir",
                    str(output),
                ],
                env={
                    **os.environ,
                    "LC_ALL": "C",
                    "LANG": "C",
                    "PYTHONUTF8": "0",
                    "PYTHONCOERCECLOCALE": "0",
                    "PYTHONIOENCODING": "utf-8",
                },
                cwd=root,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=10,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            report_dir = output / "traces" / "reports" if script_name == "analyze.py" else output
            report = json.loads((report_dir / "T001_demo_ab12.json").read_text(encoding="utf-8"))
            self.assertEqual(report["task_name"], label)
            self.assertEqual(report["failure_classification"]["key_reason_zh"], reason)
            if script_name == "analyze.py":
                run_dir = output / "traces"
                structured = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
                self.assertEqual(structured["tasks"][0]["task_name"], label)
                self.assertEqual(structured["tasks"][0]["trials"][0]["failure_reason"], reason)
                self.assertIn(label, (run_dir / "summary.txt").read_text(encoding="utf-8"))
                rows = list(
                    csv.reader(io.StringIO((run_dir / "summary.csv").read_text(encoding="utf-8")))
                )
                self.assertIn(label, rows[1])

    def test_generator_reads_utf8_inputs(self):
        self.run_report("generate_trial_reports.py", "unicode-input")

    def test_generator_writes_utf8_reports(self):
        self.run_report("generate_trial_reports.py", "unicode-output")

    def test_generator_keeps_ascii_reports(self):
        self.run_report("generate_trial_reports.py", "ascii")

    def test_analysis_reads_utf8_inputs(self):
        self.run_report("analyze.py", "unicode-input")

    def test_analysis_writes_utf8_formats(self):
        self.run_report("analyze.py", "unicode-output")

    def test_analysis_keeps_ascii_formats(self):
        self.run_report("analyze.py", "ascii")


if __name__ == "__main__":
    unittest.main()
