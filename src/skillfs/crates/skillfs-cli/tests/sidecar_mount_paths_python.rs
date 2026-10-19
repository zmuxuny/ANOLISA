//! Run sidecar mount-table path regressions without requiring a FUSE mount.

#[test]
fn sidecar_mount_paths_match_kernel_escaping() {
    let tests = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../../tests/test_sidecar_mount_paths.py");
    let output = std::process::Command::new("python3")
        .arg(tests)
        .arg("-v")
        .output()
        .expect("run Python 3 sidecar path regressions");
    assert!(
        output.status.success(),
        "sidecar mount path regressions failed:\n{}\n{}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
}
