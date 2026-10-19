"""The offset-table generator must emit file offsets, not ELF addresses."""

import contextlib
import importlib.util
import io
import json
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).parents[2] / "extract-codex-offsets.py"
SPEC = importlib.util.spec_from_file_location("codex_offset_generator", SCRIPT)
generator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(generator)


class CodexOffsetTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.binary = Path(temporary.name) / "fixture"

    def elf(self, bits=64, endian="<", filesz=64, flags=5):
        """One executable PT_LOAD, deliberately at a non-identity address."""
        data = bytearray(512)
        data[:7] = b"\x7fELF" + bytes([2 if bits == 64 else 1, 1 if endian == "<" else 2, 1])
        if bits == 64:
            struct.pack_into(endian + "HHIQQQIHHHHHH", data, 16,
                             2, 62, 1, 0, 64, 0, 0, 64, 56, 1, 0, 0, 0)
            struct.pack_into(endian + "IIQQQQQQ", data, 64,
                             1, flags, 256, 0x401000, 0, filesz, 128, 4096)
        else:
            struct.pack_into(endian + "HHIIIIIHHHHHH", data, 16,
                             2, 3, 1, 0, 52, 0, 0, 52, 32, 1, 0, 0, 0)
            struct.pack_into(endian + "IIIIIIII", data, 52,
                             1, 256, 0x401000, 0, filesz, 128, flags, 4096)
        return data

    def invoke(self, data, symbols=None):
        self.binary.write_bytes(data)
        symbols = symbols or dict(zip(generator.EX_SYMBOLS, (0x401000, 0x401010, 0x401020)))
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.object(sys, "argv", [str(SCRIPT), str(self.binary)]):
            with patch.object(generator, "nm_symbols", return_value=symbols):
                with patch.object(generator, "read_buildid", return_value=None):
                    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                        status = generator.main()
        return status, stdout.getvalue(), stderr.getvalue()

    def test_translate_both_elf_classes_and_byte_orders(self):
        for bits in (32, 64):
            for endian in ("<", ">"):
                with self.subTest(bits=bits, endian=endian):
                    status, output, _ = self.invoke(self.elf(bits, endian))
                    self.assertEqual(status, 0)
                    offsets = json.loads(output)["offsets"]
                    self.assertEqual([offsets[k] for k in ("ssl_write", "ssl_read", "ssl_do_handshake")],
                                     [256, 272, 288])
                    self.assertTrue(offsets["write_is_ex"])
                    self.assertTrue(offsets["read_is_ex"])

    def test_plain_symbol_fallback_preserves_abi_flags(self):
        symbols = dict(zip(generator.PLAIN_SYMBOLS, (0x401000, 0x401010, 0x401020)))
        status, output, _ = self.invoke(self.elf(), symbols)
        self.assertEqual(status, 0)
        offsets = json.loads(output)["offsets"]
        self.assertEqual(offsets["ssl_write"], 256)
        self.assertFalse(offsets["write_is_ex"])
        self.assertFalse(offsets["read_is_ex"])

    def test_reject_non_file_backed_or_non_executable_symbols(self):
        for data in (self.elf(filesz=16), self.elf(flags=4)):
            with self.subTest(filesz=struct.unpack_from("<Q", data, 96)[0]):
                status, output, diagnostic = self.invoke(data)
                self.assertNotEqual(status, 0)
                self.assertEqual(output, "")
                self.assertIn("file offset", diagnostic)

    def test_reject_invalid_or_truncated_program_headers(self):
        short_entry = self.elf()
        struct.pack_into("<H", short_entry, 54, 8)
        past_end = self.elf()
        struct.pack_into("<Q", past_end, 32, len(past_end))
        oversized_segment = self.elf(filesz=1024)
        for data in (b"not an ELF file", self.elf()[:40], self.elf()[:100],
                     short_entry, past_end, oversized_segment):
            with self.subTest(length=len(data)):
                status, output, diagnostic = self.invoke(data)
                self.assertNotEqual(status, 0)
                self.assertEqual(output, "")
                self.assertIn("file offset", diagnostic)

    @unittest.skipUnless(shutil.which("gcc") and shutil.which("nm") and shutil.which("readelf"),
                         "real ELF regression requires gcc and binutils")
    def test_real_pie_and_non_pie_binaries(self):
        source = self.binary.with_suffix(".c")
        source.write_text(
            "int SSL_write_ex(void){return 11;}\n"
            "int SSL_read_ex(void){return 12;}\n"
            "int SSL_do_handshake(void){return 13;}\n"
            "int main(void){return 0;}\n", encoding="utf-8"
        )
        for option in ("-pie", "-no-pie"):
            with self.subTest(option=option):
                subprocess.run(["gcc", option, "-o", str(self.binary), str(source)], check=True,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                result = subprocess.run([sys.executable, str(SCRIPT), str(self.binary)], check=True,
                                        text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                offsets = json.loads(result.stdout)["offsets"]
                # Independent oracle: readelf's section address/file-offset pair.
                sections = subprocess.check_output(["readelf", "-SW", str(self.binary)], text=True)
                text_section = next(line for line in sections.splitlines() if "] .text " in line)
                fields = text_section.split("]", 1)[1].split()
                address, file_offset = int(fields[2], 16), int(fields[3], 16)
                symbols = generator.nm_symbols(str(self.binary))
                for name, symbol in zip(("ssl_write", "ssl_read", "ssl_do_handshake"), generator.EX_SYMBOLS):
                    self.assertEqual(offsets[name], symbols[symbol] - address + file_offset)
                    self.assertLess(offsets[name], self.binary.stat().st_size)


if __name__ == "__main__":
    unittest.main()
