//! Check Debian build dependencies with a private package status database.

use std::path::Path;
use std::process::Command;

#[test]
fn dependency_check_python_regressions() {
    let tests = Path::new(env!("CARGO_MANIFEST_DIR")).join("scripts/benchmark/tests");
    let output = Command::new("python3")
        .args(["-m", "unittest", "discover", "-s"])
        .arg(tests)
        .args(["-p", "test_check_deps_regressions.py", "-v"])
        .output()
        .expect("python3 must be available to test dependency checks");
    assert!(
        output.status.success(),
        "dependency check regressions failed:\n{}\n{}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr),
    );
}
