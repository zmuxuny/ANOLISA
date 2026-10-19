//! Resource artifact encoding must not depend on the host locale.

use std::path::Path;
use std::process::Command;

#[test]
fn resource_artifact_encoding_python_regressions() {
    let tests = Path::new(env!("CARGO_MANIFEST_DIR")).join("scripts/benchmark/tests");
    let output = Command::new("python3")
        .args(["-m", "unittest", "discover", "-s"])
        .arg(tests)
        .args(["-p", "test_resource_artifact_encoding.py", "-v"])
        .output()
        .expect("python3 must be available for resource artifact regressions");
    assert!(
        output.status.success(),
        "resource artifact regressions failed:\n{}\n{}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr),
    );
}
