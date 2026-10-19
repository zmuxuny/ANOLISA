//! Comments and literals must not alter architecture boundary decisions.

use std::path::Path;
use std::process::Command;

#[test]
fn architecture_lexing_python_regressions() {
    let tests = Path::new(env!("CARGO_MANIFEST_DIR")).join("scripts/benchmark/tests");
    let output = Command::new("python3")
        .args(["-m", "unittest", "discover", "-s"])
        .arg(tests)
        .args(["-p", "test_arch_boundary_lexing.py", "-v"])
        .output()
        .expect("python3 must be available for architecture lexing regressions");
    assert!(
        output.status.success(),
        "architecture lexing regressions failed:\n{}\n{}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr),
    );
}
