//! Unexecuted benchmark source files must not disappear from coverage gates.

use std::path::Path;
use std::process::Command;

#[test]
fn regression_source_coverage_python_regressions() {
    let tests = Path::new(env!("CARGO_MANIFEST_DIR")).join("scripts/benchmark/tests");
    let output = Command::new("python3")
        .args(["-m", "unittest", "discover", "-s"])
        .arg(tests)
        .args(["-p", "test_regression_source_coverage.py", "-v"])
        .output()
        .expect("python3 and benchmark coverage dependencies must be available");
    assert!(
        output.status.success(),
        "benchmark source coverage regressions failed:\n{}\n{}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr),
    );
}
