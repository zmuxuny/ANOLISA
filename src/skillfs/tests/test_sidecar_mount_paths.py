"""Exercise sidecar path matching with real awk and an isolated mount table."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

COMPONENT = Path(__file__).resolve().parents[1]
PROBE = COMPONENT / "container/mount-probe.sh"
PREFLIGHT = COMPONENT / "container/preflight.sh"


def mountinfo_path(path: Path) -> str:
    return (
        str(path)
        .replace("\\", r"\134")
        .replace(" ", r"\040")
        .replace("\t", r"\011")
        .replace("\n", r"\012")
    )


class SidecarMountPathTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="skillfs-mount-path-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.table = self.root / "mountinfo"
        self.bin = self.root / "bin"
        self.bin.mkdir()
        real_awk = shutil.which("awk")
        self.assertIsNotNone(real_awk)
        shim = self.bin / "awk"
        # Only redirect the kernel table input. The shipped awk program and
        # actual command-line/environment argument handling execute unchanged.
        shim.write_text(
            f"#!{sys.executable}\nimport os, sys\n"
            "if sys.argv[-1] == '/proc/self/mountinfo':\n"
            "    sys.argv[-1] = os.environ['TEST_MOUNTINFO']\n"
            f"os.execv({real_awk!r}, [{real_awk!r}, *sys.argv[1:]])\n",
            encoding="utf-8",
        )
        shim.chmod(0o755)
        self.source = self.root / "source"
        self.source.mkdir()

    def run_script(self, script: Path, mount: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", str(script), *(["--cleanup-only"] if script == PREFLIGHT else [])],
            env={
                **os.environ,
                "PATH": f"{self.bin}{os.pathsep}{os.environ.get('PATH', '')}",
                "TEST_MOUNTINFO": str(self.table),
                "SKILLFS_SOURCE": str(self.source),
                "SKILLFS_MOUNTPOINT": str(mount),
                "SKILLFS_PROBE_FILE": "SKILL.md",
                "SKILLFS_PROBE_TIMEOUT": "2",
                "SKILLFS_RESIDUAL_UNMOUNT": "0",
            },
            capture_output=True,
            text=True,
            timeout=5,
        )

    def prepare_mount(self, name: str, fstype: str = "fuse.skillfs") -> Path:
        mount = self.root / name
        mount.mkdir()
        (mount / "SKILL.md").write_text("A readable skill.\n", encoding="utf-8")
        self.table.write_text(
            f"40 20 0:40 / {mountinfo_path(mount)} rw shared:1 master:2 - {fstype} skillfs rw\n",
            encoding="utf-8",
        )
        return mount

    def test_probe_accepts_space_tab_newline_and_backslash(self) -> None:
        for name in ["with space", "with\ttab", "with\nnewline", "with\\backslash"]:
            with self.subTest(name=name):
                mount = self.prepare_mount(name)
                result = self.run_script(PROBE, mount)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("read 18 bytes", result.stderr)

    def test_probe_does_not_reinterpret_literal_escape_sequences(self) -> None:
        for name in [r"literal\040", r"literal\011", r"literal\012", r"literal\134", r"literal\n"]:
            with self.subTest(name=name):
                result = self.run_script(PROBE, self.prepare_mount(name))
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_preflight_detects_escaped_residual_mounts_without_unmounting(self) -> None:
        for name in ["with space", "with\ttab", "with\nnewline", r"literal\040"]:
            with self.subTest(name=name):
                result = self.run_script(PREFLIGHT, self.prepare_mount(name))
                self.assertEqual(result.returncode, 16, result.stderr)
                self.assertIn("disables cleanup", result.stderr)
                self.assertIn("fstype='fuse.skillfs'", result.stderr)

    def test_preflight_refuses_an_escaped_non_fuse_mount(self) -> None:
        result = self.run_script(PREFLIGHT, self.prepare_mount("ordinary volume", "ext4"))
        self.assertEqual(result.returncode, 16, result.stderr)
        self.assertIn("not a FUSE mount", result.stderr)

    def test_unrelated_mount_does_not_match_by_prefix(self) -> None:
        mount = self.prepare_mount("with space")
        requested = self.root / "with"
        requested.mkdir()
        result = self.run_script(PROBE, requested)
        self.assertEqual(result.returncode, 2, result.stderr)
        result = self.run_script(PREFLIGHT, requested)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("residual mount detected", result.stderr)
        self.assertTrue(mount.exists())

    def test_plain_path_and_optional_mountinfo_fields_still_work(self) -> None:
        mount = self.prepare_mount("plain")
        self.assertEqual(self.run_script(PROBE, mount).returncode, 0)
        result = self.run_script(PREFLIGHT, mount)
        self.assertEqual(result.returncode, 16, result.stderr)
        self.assertIn("fstype='fuse.skillfs'", result.stderr)


if __name__ == "__main__":
    unittest.main()
