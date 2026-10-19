//! Keep coverage artifacts independent of Git display settings.

use std::path::Path;
use std::process::Command;

#[test]
fn coverage_diff_python_regressions() {
    let tests = Path::new(env!("CARGO_MANIFEST_DIR")).join("scripts/benchmark/tests");
    let output = Command::new("python3")
        .args(["-m", "unittest", "discover", "-s"])
        .arg(tests)
        .args(["-p", "test_coverage_diff_config.py", "-v"])
        .output()
        .expect("python3 must be available to test coverage diff generation");
    assert!(
        output.status.success(),
        "coverage diff regressions failed:\n{}\n{}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr),
    );
}
