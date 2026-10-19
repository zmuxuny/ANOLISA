"""Rust comments and literals must not change architecture-gate decisions."""

import importlib.util
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).parents[2] / "check-arch-boundaries.py"
spec = importlib.util.spec_from_file_location("arch_lexing_checker", SCRIPT)
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


def targets(source):
    return list(checker.extract_imports(source))


class ArchitectureLexingTests(unittest.TestCase):
    def test_literal_braces_do_not_hide_production_after_tests(self):
        literals = [
            '"{"',
            '"\\"{"',
            'r"{"',
            'r###"{ "# "##"###',
            'b"{"',
            'br##"{"##',
            'c"{"',
            'cr##"{"##',
            "'{'",
            "b'{'",
            "'\\u{007b}'",
            '"first\n{\nlast"',
        ]
        for literal in literals:
            with self.subTest(literal=literal):
                source = (
                    "#[cfg(test)]\nmod tests {\n"
                    f"    fn fixture() {{ let _ = {literal}; }}\n"
                    "}\nuse crate::server::forbidden;\n"
                )
                imports = targets(source)
                self.assertTrue(imports, source)
                self.assertEqual({target for _, target in imports}, {"server"})
                self.assertEqual(imports[0][0], source.count("\n"))

    def test_nested_comments_do_not_change_test_block_depth(self):
        source = (
            "#[cfg(test)]\nmod tests {\n"
            "    /* { /* } */ { */\n"
            '    const DATA: &str = "/* not a comment */"; // {\n'
            "}\nuse crate::server::forbidden;\n"
        )
        self.assertEqual(set(targets(source)), {(6, "server")})

    def test_comments_in_grouped_imports_preserve_every_target(self):
        source = (
            "use crate::{ /* server is a real dependency */\n"
            "    server /* nested /* , } */ comment */,\n"
            "    // storage is next\n"
            "    storage::{self, Store},\n"
            "};\n"
        )
        self.assertEqual(targets(source), [(1, "server"), (1, "storage")])

    def test_non_code_paths_never_become_dependencies(self):
        source = """// use crate::server::forbidden;
/* outer /* nested */ use crate::server::forbidden; */
const DOC: &str = "use crate::server::forbidden;";
const RAW: &str = r##"quote \"# crate::server::forbidden()"##;
const BYTES: &[u8] = b"crate::server::forbidden()";
const C: &std::ffi::CStr = c"crate::server::forbidden()";
fn harmless() {} // crate::server::forbidden()
"""
        self.assertEqual(targets(source), [])

    def test_fake_cfg_attribute_does_not_exempt_real_module(self):
        source = (
            'const DOC: &str = "#[cfg(test)]";\n'
            "mod production {\n    use crate::server::forbidden;\n}\n"
        )
        self.assertEqual(set(targets(source)), {(3, "server")})

    def test_lifetimes_labels_and_character_escapes_keep_real_paths(self):
        source = r"""fn live<'a>(value: &'a str) {
    let _: char = '\'';
    let _ = '\\';
    let _ = '"';
    'label: loop { crate::server::forbidden(); break 'label; }
}
"""
        self.assertEqual(set(targets(source)), {(5, "server")})

    def test_original_line_numbers_survive_multiline_tokens_and_crlf(self):
        source = (
            'const TEXT: &str = r##"\r\ncrate::server::fake();\r\n"##;\r\n'
            "/* ignored\r\n * crate::server::fake(); */\r\n"
            "use crate::server::forbidden;\r\n"
        )
        self.assertEqual(set(targets(source)), {(6, "server")})

    def run_gate(self, source):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "scripts").mkdir()
            (root / "src").mkdir()
            shutil.copyfile(SCRIPT, root / "scripts" / SCRIPT.name)
            (root / "src" / "genai.rs").write_text(source, encoding="utf-8")
            return subprocess.run(
                [sys.executable, str(root / "scripts" / SCRIPT.name)],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=10,
            )

    def test_cli_rejects_real_violation_after_json_fixture(self):
        result = self.run_gate(
            '#[cfg(test)]\nmod tests {\n const JSON: &str = r#"{"#;\n}\n'
            "use crate::server::forbidden;\n"
        )
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("genai.rs:5", result.stdout)
        self.assertIn("genai (L5) -> server (L7)", result.stdout)

    def test_cli_rejects_commented_group_but_allows_documentation(self):
        result = self.run_gate("use crate::{ /* documented dependency */ server };\n")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("1 violations", result.stdout)
        result = self.run_gate('const DOC: &str = "use crate::server::forbidden;";\n')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_real_test_imports_and_allowed_production_remain_allowed(self):
        result = self.run_gate(
            "#[cfg(test)]\nmod tests {\n use crate::server::forbidden;\n}\n"
            "use crate::parser::parse;\n"
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
