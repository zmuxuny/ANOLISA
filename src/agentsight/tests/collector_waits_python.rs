//! Collector sampling waits honor duration deadlines and stop signals.

use std::path::Path;
use std::process::Command;

#[test]
fn collector_waits_python_regressions() {
    let tests = Path::new(env!("CARGO_MANIFEST_DIR")).join("scripts/benchmark/tests");
    let output = Command::new("python3")
        .args(["-m", "unittest", "discover", "-s"])
        .arg(tests)
        .args(["-p", "test_collector_waits.py", "-v"])
        .output()
        .expect("python3 must be available for collector waits regressions");
    assert!(
        output.status.success(),
        "collector waits regressions failed:\n{}\n{}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr),
    );
}
