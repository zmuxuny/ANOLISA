//! Exercise the offline Codex offset-table generator in the Cargo test gate.

use std::path::Path;
use std::process::Command;

#[test]
fn codex_offset_python_regressions() {
    let tests = Path::new(env!("CARGO_MANIFEST_DIR")).join("scripts/benchmark/tests");
    let output = Command::new("python3")
        .args(["-m", "unittest", "discover", "-s"])
        .arg(tests)
        .args(["-p", "test_codex_offset_regressions.py", "-v"])
        .output()
        .expect("python3 must be available to test the Codex offset generator");
    assert!(
        output.status.success(),
        "Codex offset regressions failed:\n{}\n{}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr),
    );
}
