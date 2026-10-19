#!/usr/bin/env python3
"""Reject incomplete binary headers before prebuilt package assembly."""

import importlib.util
import struct
import tempfile
import unittest
from pathlib import Path

VERIFIER = Path(__file__).resolve().parents[1] / "packaging/raw/verify-binaries.py"
SPEC = importlib.util.spec_from_file_location("verify_binaries", VERIFIER)
assert SPEC and SPEC.loader
verify_binaries = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verify_binaries)


class BinaryHeaderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="tokenless-binary-header-")
        self.addCleanup(self.temporary.cleanup)
        self.binary = Path(self.temporary.name) / "tokenless"

    def _elf(self, arch: str) -> bytes:
        header = bytearray(64)
        header[:7] = b"\x7fELF\x02\x01\x01"
        struct.pack_into("<H", header, 18, verify_binaries.ELF_MACHINES[arch])
        return bytes(header)

    def _macho(self, arch: str, byte_order: str) -> bytes:
        return struct.pack(
            byte_order + "IIIIIIII",
            0xFEEDFACF,
            verify_binaries.MACHO_CPUS[arch],
            0,
            2,
            0,
            0,
            0,
            0,
        )

    def test_complete_elf_headers_remain_accepted(self) -> None:
        for arch in verify_binaries.ELF_MACHINES:
            with self.subTest(arch=arch):
                self.binary.write_bytes(self._elf(arch))
                verify_binaries.verify_elf(self.binary, arch)

    def test_truncated_elf_headers_are_rejected(self) -> None:
        for arch in verify_binaries.ELF_MACHINES:
            for length in (20, 40, 63):
                with self.subTest(arch=arch, length=length):
                    self.binary.write_bytes(self._elf(arch)[:length])
                    with self.assertRaises(ValueError):
                        verify_binaries.verify_elf(self.binary, arch)

    def test_complete_macho_headers_remain_accepted(self) -> None:
        for arch in verify_binaries.MACHO_CPUS:
            for byte_order in ("<", ">"):
                with self.subTest(arch=arch, byte_order=byte_order):
                    self.binary.write_bytes(self._macho(arch, byte_order))
                    verify_binaries.verify_macho(self.binary, arch)

    def test_truncated_macho_headers_are_rejected(self) -> None:
        for arch in verify_binaries.MACHO_CPUS:
            for byte_order in ("<", ">"):
                for length in (8, 16, 31):
                    with self.subTest(arch=arch, byte_order=byte_order, length=length):
                        self.binary.write_bytes(self._macho(arch, byte_order)[:length])
                        with self.assertRaises(ValueError):
                            verify_binaries.verify_macho(self.binary, arch)


if __name__ == "__main__":
    unittest.main()
