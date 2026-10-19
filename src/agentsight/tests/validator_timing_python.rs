//! Keep the benchmark CLI's bounded polling checks in the Cargo test gate.

use std::path::Path;
use std::process::Command;

#[test]
fn validator_rejects_nonfinite_timing_parameters() {
    let root = Path::new(env!("CARGO_MANIFEST_DIR"));
    let output = Command::new("python3")
        .arg("-W")
        .arg("error::ResourceWarning")
        .arg(root.join("scripts/benchmark/tests/test_validator_timing.py"))
        .output()
        .expect("python3 must be available for benchmark regressions");
    assert!(
        output.status.success(),
        "validator timing regressions failed:\n{}\n{}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
}
