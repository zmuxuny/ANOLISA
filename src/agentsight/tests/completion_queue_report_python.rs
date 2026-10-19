//! Completion queue metrics survive collector and report boundaries.

use std::path::Path;
use std::process::Command;

#[test]
fn completion_queue_report_python_regressions() {
    let tests = Path::new(env!("CARGO_MANIFEST_DIR")).join("scripts/benchmark/tests");
    let output = Command::new("python3")
        .args(["-m", "unittest", "discover", "-s"])
        .arg(tests)
        .args(["-p", "test_completion_queue_report.py", "-v"])
        .output()
        .expect("python3 must be available for completion queue report regressions");
    assert!(
        output.status.success(),
        "completion queue report regressions failed:\n{}\n{}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr),
    );
}
