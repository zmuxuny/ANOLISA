//! Exercise the shipped health probe's argument parser without requiring FUSE.

use std::path::Path;
use std::process::{Command, Output, Stdio};
use std::time::{Duration, Instant};

fn probe(args: &[&str]) -> Output {
    let script = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../container/mount-probe.sh");
    let mut child = Command::new("bash")
        .arg(script)
        .args(args)
        .env(
            "SKILLFS_MOUNTPOINT",
            "/skillfs-test-mountpoint-that-does-not-exist",
        )
        .env("SKILLFS_PROBE_FILE", "skills/skill-discover/SKILL.md")
        .env("SKILLFS_PROBE_TIMEOUT", "5")
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .expect("start health probe");
    let deadline = Instant::now() + Duration::from_secs(2);
    loop {
        if child.try_wait().expect("check health probe").is_some() {
            return child
                .wait_with_output()
                .expect("collect health probe output");
        }
        if Instant::now() >= deadline {
            child.kill().expect("kill hung health probe");
            let output = child.wait_with_output().expect("reap hung health probe");
            panic!(
                "health probe did not terminate for {args:?}: {}",
                String::from_utf8_lossy(&output.stderr)
            );
        }
        std::thread::sleep(Duration::from_millis(10));
    }
}

fn assert_missing_value(option: &str) {
    let output = probe(&[option]);
    assert_eq!(output.status.code(), Some(1));
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(
        stderr.contains(option),
        "missing option in diagnostic: {stderr}"
    );
    assert!(
        stderr.contains("requires a value"),
        "unclear diagnostic: {stderr}"
    );
}

#[test]
fn missing_mode_exits_with_configuration_error() {
    assert_missing_value("--mode");
}

#[test]
fn missing_timeout_exits_with_configuration_error() {
    assert_missing_value("--timeout");
}

#[test]
fn missing_mountpoint_exits_with_configuration_error() {
    assert_missing_value("--mountpoint");
}

#[test]
fn missing_file_exits_with_configuration_error() {
    assert_missing_value("--file");
}

#[test]
fn complete_options_reach_the_mount_check() {
    let output = probe(&[
        "--mode",
        "readiness",
        "--timeout",
        "5",
        "--mountpoint",
        "/skillfs-test-mountpoint-that-does-not-exist",
        "--file",
        "SKILL.md",
    ]);
    assert_eq!(output.status.code(), Some(2));
    assert!(
        String::from_utf8_lossy(&output.stderr).contains("not present in /proc/self/mountinfo")
    );
}

#[test]
fn explicit_empty_values_are_rejected_without_hanging() {
    for option in ["--mode", "--timeout", "--mountpoint", "--file"] {
        assert_eq!(probe(&[option, ""]).status.code(), Some(1), "{option}");
    }
}

#[test]
fn shorthand_modes_still_reach_the_mount_check() {
    for option in ["--startup", "--readiness", "--liveness"] {
        assert_eq!(probe(&[option]).status.code(), Some(2), "{option}");
    }
}
