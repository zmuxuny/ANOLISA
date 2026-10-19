"""Exercise dependency checks against an isolated, real dpkg status database."""

import os
import shlex
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "check-deps.sh"
DPKG = shutil.which("dpkg")
PACKAGES = ("libssl-dev", "libelf-dev", "perl", "libbpf-dev")


@unittest.skipUnless(DPKG and os.name == "posix", "requires Debian dpkg")
class DependencyPackageStateTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="agentsight-deps-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.db = self.root / "dpkg"
        self.db.mkdir()
        for name in ("awk", "grep", "head", "sed", "cut", "dpkg-query"):
            target = shutil.which(name)
            self.assertIsNotNone(target, name)
            (self.bin / name).symlink_to(target)
        self.executable("dpkg", f'exec {shlex.quote(DPKG)} --admindir={shlex.quote(str(self.db))} "$@"')
        for name in ("apt", "cargo", "clang", "llvm-strip", "bpftool"):
            self.executable(name, "exit 0")
        self.executable("rustc", "echo 'rustc 1.89.0 (fixture)'")
        self.executable("uname", "echo '6.1.0-fixture'")

    def executable(self, name, body):
        path = self.bin / name
        path.write_text("#!/bin/sh\n" + body + "\n", encoding="utf-8")
        path.chmod(0o755)

    def run_check(self, states=None, absent=()):
        states = states or {}
        entries = []
        for package in PACKAGES:
            if package in absent:
                continue
            state = states.get(package, "install ok installed")
            entries.append(
                f"Package: {package}\nStatus: {state}\n"
                "Architecture: all\nVersion: 1.2.3\n"
                "Maintainer: Fixture <fixture@example.invalid>\n"
                "Description: isolated dependency-check fixture\n"
            )
        (self.db / "status").write_text("\n".join(entries), encoding="utf-8")
        return subprocess.run(
            ["/bin/bash", str(SCRIPT)],
            env={"PATH": str(self.bin), "HOME": str(self.root), "LC_ALL": "C", "BASH_ENV": "/dev/null"},
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

    def test_config_files_are_not_installed_dependencies(self):
        result = self.run_check({"libssl-dev": "deinstall ok config-files"})
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("1 dependency(s) missing", result.stdout)
        self.assertIn("sudo apt install -y libssl-dev", result.stdout)
        self.assertNotIn("All dependencies present", result.stdout)

    def test_incomplete_and_broken_packages_are_missing(self):
        for state in ("install ok unpacked", "install ok half-configured", "install reinstreq installed"):
            with self.subTest(state=state):
                result = self.run_check({"libelf-dev": state})
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertIn("1 dependency(s) missing", result.stdout)

    def test_installed_packages_preserve_version_report(self):
        result = self.run_check()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout.count("(dpkg: 1.2.3)"), 4)
        self.assertIn("All dependencies present", result.stdout)

    def test_held_installed_package_is_usable(self):
        result = self.run_check({"libssl-dev": "hold ok installed"})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("OpenSSL devel (dpkg: 1.2.3)", result.stdout)

    def test_absent_package_stays_missing(self):
        result = self.run_check(absent=("libbpf-dev",))
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("1 dependency(s) missing", result.stdout)
        self.assertIn("sudo apt install -y libbpf-dev", result.stdout)

    def test_all_removed_packages_are_counted(self):
        result = self.run_check({package: "deinstall ok config-files" for package in PACKAGES})
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("4 dependency(s) missing", result.stdout)


if __name__ == "__main__":
    unittest.main()
