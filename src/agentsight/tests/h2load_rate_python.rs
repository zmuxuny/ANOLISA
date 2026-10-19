//! Keep HTTP/2 benchmark rate contracts in the standard test gate.

use std::path::Path;
use std::process::Command;

#[test]
fn h2load_distributes_the_requested_rate() {
    let root = Path::new(env!("CARGO_MANIFEST_DIR"));
    let output = Command::new("python3")
        .arg("-W")
        .arg("error::ResourceWarning")
        .arg(root.join("scripts/benchmark/tests/test_h2load_rate.py"))
        .output()
        .expect("python3 must be available for benchmark regressions");
    assert!(
        output.status.success(),
        "h2load rate regressions failed:\n{}\n{}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
}
