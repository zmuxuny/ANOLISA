//! Calibrate ATIF content-part messages using their text length.

use std::path::Path;
use std::process::Command;

#[test]
fn triage_content_parts_python_regressions() {
    let tests = Path::new(env!("CARGO_MANIFEST_DIR")).join("scripts/benchmark/tests");
    let output = Command::new("python3")
        .args(["-m", "unittest", "discover", "-s"])
        .arg(tests)
        .args(["-p", "test_calibrate_content_parts.py", "-v"])
        .output()
        .expect("python3 must be available for triage content parts regressions");
    assert!(
        output.status.success(),
        "triage content parts regressions failed:\n{}\n{}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr),
    );
}
