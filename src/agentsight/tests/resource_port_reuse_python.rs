//! Preserve sequential benchmark startup across closed TCP connections.

use std::path::Path;
use std::process::Command;

#[test]
fn resource_port_reuse_python_regressions() {
    let tests = Path::new(env!("CARGO_MANIFEST_DIR")).join("scripts/benchmark/tests");
    let output = Command::new("python3")
        .args(["-m", "unittest", "discover", "-s"])
        .arg(tests)
        .args(["-p", "test_resource_port_reuse.py", "-v"])
        .output()
        .expect("python3 must be available to test sequential benchmark ports");
    assert!(
        output.status.success(),
        "resource port reuse regressions failed:\n{}\n{}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr),
    );
}
