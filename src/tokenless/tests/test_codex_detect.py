#!/usr/bin/env python3
"""Pin the Codex detector's JSON contract with and without jq."""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

DETECTOR = (
    Path(__file__).resolve().parents[1] / "adapters/tokenless/codex/scripts/detect.sh"
)


class CodexDetectTests(unittest.TestCase):
    def _detect(self, directory_name: str, *, with_jq: bool = False) -> dict:
        with tempfile.TemporaryDirectory(prefix="tokenless-codex-detect-") as temporary:
            root = Path(temporary)
            binary_dir = root / directory_name
            binary_dir.mkdir()
            # No jq or Python on the child's PATH unless explicitly requested.
            for name in ("grep", "head", "cat") + (("jq",) if with_jq else ()):
                source = shutil.which(name)
                self.assertIsNotNone(source, f"test dependency missing: {name}")
                (binary_dir / name).symlink_to(source)
            binary = binary_dir / "tokenless"
            binary.write_text(
                "#!/bin/sh\nprintf 'tokenless 1.2.3\\n'\n", encoding="utf-8"
            )
            binary.chmod(0o755)
            result = subprocess.run(
                [shutil.which("bash"), str(DETECTOR)],
                env={**os.environ, "HOME": str(root), "PATH": str(binary_dir)},
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            value = json.loads(result.stdout)
            self.assertEqual(
                value, {"installed": True, "version": "1.2.3", "path": str(binary)}
            )
            return value

    def test_no_jq_preserves_special_path_characters(self) -> None:
        for name in (
            'quoted"bin',
            "back\\slash",
            "literal\\tab",
            "line\nbreak",
            "tab\tpath",
            "control\x01path",
            "unicode-测试",
        ):
            with self.subTest(name=name):
                self._detect(name)

    def test_no_jq_escapes_all_json_control_characters(self) -> None:
        self._detect("controls-" + "".join(chr(code) for code in range(1, 32)))

    def test_no_jq_preserves_an_ordinary_path(self) -> None:
        self._detect("bin")

    @unittest.skipUnless(shutil.which("jq"), "jq is not installed")
    def test_jq_path_keeps_the_same_json_contract(self) -> None:
        self._detect('quoted"bin\\path\n测试', with_jq=True)


if __name__ == "__main__":
    unittest.main()
