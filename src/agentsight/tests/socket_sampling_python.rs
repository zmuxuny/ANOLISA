//! Keep active socket samples useful while process descriptors close.

use std::path::Path;
use std::process::Command;

#[test]
fn socket_sampling_python_regressions() {
    let tests = Path::new(env!("CARGO_MANIFEST_DIR")).join("scripts/benchmark/tests");
    let output = Command::new("python3")
        .args(["-m", "unittest", "discover", "-s"])
        .arg(tests)
        .args(["-p", "test_socket_sampling_race.py", "-v"])
        .output()
        .expect("python3 must be available to test socket samples");
    assert!(
        output.status.success(),
        "socket sampling regressions failed:\n{}\n{}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr),
    );
}
