"""Calibrate interoperable ATIF messages by characters, not array length."""

import hashlib
import importlib.util
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

SCRIPT = Path(__file__).parents[2] / "calibrate-triage.py"
spec = importlib.util.spec_from_file_location("calibrate_parts", SCRIPT)
calibrate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(calibrate)


def document(message):
    return {
        "steps": [
            {"step_id": 1, "source": "user", "message": "Question"},
            {"step_id": 2, "source": "agent", "message": message},
        ]
    }


def measure(message):
    return calibrate.measure(json.dumps(document(message)))


class ContentPartCalibrationTests(unittest.TestCase):
    def test_long_text_part_is_not_a_one_character_answer(self):
        message = [{"type": "text", "text": "x" * 3000}]
        metrics = measure(message)
        self.assertEqual(metrics["max_agent_len"], 3027)
        self.assertEqual(calibrate.classify(metrics, 2000), "substantive")

    def test_unicode_and_escapes_use_compact_unescaped_json_characters(self):
        message = [{"type": "text", "text": '你好é🙂"\n\\'}]
        # This is the compact text seen by the Rust ATIF message reader.
        flattened = '[{"text":"你好é🙂\\"\\n\\\\","type":"text"}]'
        self.assertEqual(measure(message)["max_agent_len"], len(flattened))

    def test_multimodal_parts_and_empty_array_follow_atif_flattening(self):
        message = [
            {"type": "text", "text": "inspect this"},
            {
                "type": "image",
                "source": {"media_type": "image/png", "path": "fixture.png"},
            },
        ]
        expected = len(
            '[{"text":"inspect this","type":"text"},{"source":{"media_type":"image/png","path":"fixture.png"},"type":"image"}]'
        )
        self.assertEqual(measure(message)["max_agent_len"], expected)
        self.assertEqual(measure([])["max_agent_len"], 2)

    def test_numeric_extension_is_json_text_not_an_item_count(self):
        # Numeric extensions use Python JSON formatting: 1e-07, not serde_json's
        # 1e-7. This fixes item-count truncation, not cross-language float spelling.
        message = [{"type": "text", "text": "x", "extra": {"score": 1e-7}}]
        python_text = '[{"type":"text","text":"x","extra":{"score":1e-07}}]'
        self.assertEqual(measure(message)["max_agent_len"], len(python_text))

    def test_plain_null_and_missing_messages_keep_their_contract(self):
        for message, length in [("你好é🙂", 4), ("", 0), (None, 0)]:
            with self.subTest(message=message):
                self.assertEqual(measure(message)["max_agent_len"], length)
        doc = document(None)
        del doc["steps"][1]["message"]
        self.assertEqual(calibrate.measure(json.dumps(doc))["max_agent_len"], 0)

    def test_array_length_boundary_remains_exclusive(self):
        message = [{"type": "text", "text": "x"}]
        metrics = measure(message)
        self.assertEqual(metrics["max_agent_len"], 28)
        self.assertEqual(calibrate.classify(metrics, 28), "substantive")
        self.assertEqual(calibrate.classify(metrics, 29), "useless")

    def test_real_database_cli_preserves_long_array_answers_and_read_only_data(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "trajectories.db"
            with closing(sqlite3.connect(db)) as conn:
                conn.execute(
                    "CREATE TABLE collected_trajectories (session_id TEXT, first_user_message TEXT, atif_json TEXT)"
                )
                for name, message in (
                    ("string", "x" * 3000),
                    ("array", [{"type": "text", "text": "x" * 3000}]),
                ):
                    conn.execute(
                        "INSERT INTO collected_trajectories VALUES (?, ?, ?)",
                        (name, "Question", json.dumps(document(message))),
                    )
                conn.commit()
            before = hashlib.sha256(db.read_bytes()).digest()
            result = subprocess.run(
                [sys.executable, str(SCRIPT), str(db)],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=10,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertRegex(result.stdout, r"substantive\s+2\s+\(100.0%\)")
            self.assertIn("would be excluded from retrieval: 0.0%", result.stdout)
            self.assertEqual(hashlib.sha256(db.read_bytes()).digest(), before)


if __name__ == "__main__":
    unittest.main()
