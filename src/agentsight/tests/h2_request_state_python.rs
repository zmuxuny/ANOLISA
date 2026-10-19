//! HTTP/2 mock streams retain request identity and release cancelled state.

use std::path::Path;
use std::process::Command;

#[test]
fn h2_request_state_python_regressions() {
    let tests = Path::new(env!("CARGO_MANIFEST_DIR")).join("scripts/benchmark/tests");
    let output = Command::new("python3")
        .args(["-m", "unittest", "discover", "-s"])
        .arg(tests)
        .args(["-p", "test_h2_request_state.py", "-v"])
        .output()
        .expect("python3 must be available for HTTP/2 request state regressions");
    assert!(
        output.status.success(),
        "HTTP/2 request state regressions failed:\n{}\n{}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr),
    );
}
