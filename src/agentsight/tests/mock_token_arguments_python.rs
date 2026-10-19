//! Invalid token pacing must produce actionable CLI usage errors.

use std::path::Path;
use std::process::Command;

#[test]
fn mock_token_arguments_python_regressions() {
    let tests = Path::new(env!("CARGO_MANIFEST_DIR")).join("scripts/benchmark/tests");
    let output = Command::new("python3")
        .args(["-m", "unittest", "discover", "-s"])
        .arg(tests)
        .args(["-p", "test_mock_token_arguments.py", "-v"])
        .output()
        .expect("python3 must be available for mock token arguments regressions");
    assert!(
        output.status.success(),
        "mock token arguments regressions failed:\n{}\n{}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr),
    );
}
