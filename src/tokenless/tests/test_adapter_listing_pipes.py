#!/usr/bin/env python3
"""Large CLI listings must not turn a matched registration into SIGPIPE."""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ADAPTERS = Path(__file__).resolve().parents[1] / "adapters/tokenless"


class AdapterListingTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="tokenless-listings-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.home = self.root / "home"
        self.bin = self.home / ".local/bin"
        self.bin.mkdir(parents=True)
        self.plugins = self.root / "adapters"
        for relative in (
            "claude-code/.claude-plugin/marketplace.json",
            "claude-code/.claude-plugin/plugin.json",
            "claude-code/hooks/run-hook.sh",
            "qwencode/qwen-extension.json",
            "qwencode/hooks/run-hook.sh",
        ):
            path = self.plugins / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{}\n", encoding="utf-8")
        (self.home / ".local/share/anolisa/adapters/tokenless/common/hooks").mkdir(
            parents=True
        )
        self.registered = self.root / "registered"
        self.log = self.root / "calls.jsonl"
        self.reset()
        for name in ("tokenless", "rtk"):
            path = self.bin / name
            path.write_text("#!/bin/sh\necho 1.2.3\n", encoding="utf-8")
            path.chmod(0o755)
        stub = r"""
import json, os, signal, sys
from pathlib import Path
signal.signal(signal.SIGPIPE, signal.SIG_DFL)
root = Path(os.environ["LISTING_TEST_ROOT"])
state = root / "registered"
args = sys.argv[1:]
with (root / "calls.jsonl").open("a") as log:
    log.write(json.dumps(args) + "\n")
if args == ["--version"]:
    print("1.2.3")
elif args in (["extensions", "list"], ["plugin", "list"], ["plugin", "marketplace", "list"]):
    if state.exists():
        if args == ["extensions", "list"]:
            print("tokenless 1.2.3")
        elif args == ["plugin", "marketplace", "list"]:
            print("anolisa-tokenless /fixture")
        elif Path(sys.argv[0]).name == "claude":
            print("tokenless@anolisa-tokenless 1.2.3")
    sys.stdout.flush()
    if os.environ.get("LISTING_SIZE") == "large":
        # More than a pipe buffer after the matching first row. A quiet grep
        # closes its pipe here, making an otherwise successful producer fail.
        sys.stdout.write("foreign-entry /some/other/plugin/path\n" * 20000)
        sys.stdout.flush()
    sys.exit(7 if os.environ.get("LISTING_FAIL") == "1" else 0)
elif args[:2] == ["extensions", "uninstall"] or args[:3] == ["plugin", "marketplace", "remove"]:
    if os.environ.get("REFUSE_REMOVE") == "1":
        sys.exit(1)
    state.unlink(missing_ok=True)
elif args[:2] == ["extensions", "link"] or args[:3] == ["plugin", "marketplace", "add"]:
    if state.exists():
        sys.exit(9)  # Do not silently accept a duplicate registration.
    state.touch()
elif args[:2] not in (["plugin", "validate"], ["plugin", "install"], ["plugin", "add"]):
    sys.exit(2)
"""
        for name in ("claude", "qwen", "codex"):
            path = self.bin / name
            path.write_text(f"#!{sys.executable}\n" + stub, encoding="utf-8")
            path.chmod(0o755)

    def reset(self, present=True):
        self.registered.unlink(missing_ok=True)
        if present:
            self.registered.touch()
        self.log.write_text("", encoding="utf-8")

    def run_adapter(self, host, action, **overrides):
        environment = {
            **os.environ,
            "HOME": str(self.home),
            "PATH": str(self.bin) + os.pathsep + os.environ.get("PATH", ""),
            "CLAUDE_BIN": str(self.bin / "claude"),
            "QWEN_BIN": str(self.bin / "qwen"),
            "CODEX_BIN": str(self.bin / "codex"),
            "ANOLISA_ADAPTER_DIR": str(self.plugins),
            "ANOLISA_COMPONENT": "tokenless",
            "ANOLISA_TARGET": host,
            "ANOLISA_DRY_RUN": "0",
            "TOKENLESS_INSTALL_PREFIX": str(self.home / ".local"),
            "TOKENLESS_DEREGISTER_ONLY": "1",
            "XDG_DATA_HOME": str(self.home / ".local/share"),
            "CODEX_HOME": str(self.home / ".codex"),
            "TOKENLESS_DETECT_RETRIES": "0",
            "TOKENLESS_DETECT_PLUGIN_RELISTS": "0",
            "TOKENLESS_DETECT_PLUGIN_RELIST_WINDOW": "0",
            "LISTING_TEST_ROOT": str(self.root),
            "LISTING_SIZE": "large",
            "LISTING_FAIL": "0",
            "REFUSE_REMOVE": "0",
            **overrides,
        }
        return subprocess.run(
            [
                "bash",
                str(ADAPTERS / host / "scripts" / f"{action}.sh"),
                "--non-interactive",
            ],
            env=environment,
            text=True,
            capture_output=True,
            timeout=15,
            check=False,
        )

    def test_installs_recognize_existing_large_listings(self):
        for host in ("claude-code", "qwencode", "codex"):
            with self.subTest(host=host):
                self.reset()
                result = self.run_adapter(host, "install")
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertTrue(self.registered.exists())
                if host == "qwencode":
                    self.assertIn("installed and linked", result.stdout)

    def test_detectors_recognize_large_listings(self):
        for host in ("claude-code", "qwencode"):
            with self.subTest(host=host):
                result = self.run_adapter(host, "detect")
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("plugin install", result.stdout)
                self.assertNotIn("not installed", result.stdout)

    def test_codex_uninstall_removes_listed_marketplace(self):
        result = self.run_adapter("codex", "uninstall")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(
            self.registered.exists(), "marketplace was silently left registered"
        )

    def test_codex_uninstall_rejects_surviving_large_listing(self):
        result = self.run_adapter("codex", "uninstall", REFUSE_REMOVE="1")
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("still lists", result.stderr)
        self.assertTrue(self.registered.exists())

    def test_short_listings_keep_the_same_behavior(self):
        for host in ("claude-code", "qwencode", "codex"):
            with self.subTest(host=host):
                self.reset()
                result = self.run_adapter(host, "install", LISTING_SIZE="small")
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_missing_registration_is_not_a_match(self):
        for host in ("claude-code", "qwencode"):
            with self.subTest(host=host):
                self.reset(present=False)
                result = self.run_adapter(host, "detect")
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertIn("not installed", result.stdout)

    def test_real_listing_failures_are_not_hidden(self):
        for host, action in (
            ("claude-code", "detect"),
            ("qwencode", "detect"),
            ("codex", "uninstall"),
        ):
            with self.subTest(host=host, action=action):
                result = self.run_adapter(host, action, LISTING_FAIL="1")
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertTrue(self.registered.exists())


if __name__ == "__main__":
    unittest.main()
