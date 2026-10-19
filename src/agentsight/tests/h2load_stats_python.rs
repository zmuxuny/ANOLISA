//! Preserve h2load latency summaries through the offline report CLI.

use std::path::Path;
use std::process::Command;

#[test]
fn h2load_summary_python_regressions() {
    let tests = Path::new(env!("CARGO_MANIFEST_DIR")).join("scripts/benchmark/tests");
    let output = Command::new("python3")
        .args(["-m", "unittest", "discover", "-s"])
        .arg(tests)
        .args(["-p", "test_h2load_layout_regressions.py", "-v"])
        .output()
        .expect("python3 must be available to test benchmark summaries");
    assert!(
        output.status.success(),
        "h2load summary regressions failed:\n{}\n{}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr),
    );
}
