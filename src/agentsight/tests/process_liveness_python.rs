//! Reject zombie processes in benchmark survival reports.

use std::path::Path;
use std::process::Command;

#[test]
fn process_liveness_python_regressions() {
    let tests = Path::new(env!("CARGO_MANIFEST_DIR")).join("scripts/benchmark/tests");
    let output = Command::new("python3")
        .args(["-m", "unittest", "discover", "-s"])
        .arg(tests)
        .args(["-p", "test_process_liveness.py", "-v"])
        .output()
        .expect("python3 must be available to test process liveness");
    assert!(
        output.status.success(),
        "process liveness regressions failed:\n{}\n{}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr),
    );
}
