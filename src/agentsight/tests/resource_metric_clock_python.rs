//! Resource trends and recovery use the collected monotonic time axis.

use std::path::Path;
use std::process::Command;

#[test]
fn resource_metric_clock_python_regressions() {
    let tests = Path::new(env!("CARGO_MANIFEST_DIR")).join("scripts/benchmark/tests");
    let output = Command::new("python3")
        .args(["-m", "unittest", "discover", "-s"])
        .arg(tests)
        .args(["-p", "test_resource_metric_clock.py", "-v"])
        .output()
        .expect("python3 must be available for resource metric clock regressions");
    assert!(
        output.status.success(),
        "resource metric clock regressions failed:\n{}\n{}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr),
    );
}
