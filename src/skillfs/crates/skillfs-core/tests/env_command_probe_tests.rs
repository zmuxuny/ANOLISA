//! Test PATH probing in subprocesses so concurrent tests never mutate global state.
#![cfg(unix)]

use skillfs_core::{compiler, env::EnvironmentProfile};
use std::ffi::OsStr;
use std::fs;
use std::os::unix::ffi::OsStringExt;
use std::os::unix::fs::{PermissionsExt, symlink};
use std::path::Path;
use std::process::Command;

fn executable(path: &Path) {
    // Probing must inspect this file, never run it.
    fs::write(path, "#!/bin/sh\nexit 99\n").expect("write command fixture");
    fs::set_permissions(path, fs::Permissions::from_mode(0o755)).expect("make fixture executable");
}

fn check_path(path: Option<&OsStr>, cwd: &Path, available: bool) {
    let mut command = Command::new(std::env::current_exe().expect("test executable"));
    if let Some(path) = path {
        command.env("PATH", path);
    } else {
        command.env_remove("PATH");
    }
    let output = command
        .args(["--exact", "probe_in_child", "--nocapture"])
        .env("SKILLFS_EXPECT_UV", if available { "yes" } else { "no" })
        .current_dir(cwd)
        .output()
        .expect("run isolated environment probe");
    assert!(
        output.status.success(),
        "probe child failed: {}{}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
}

fn check(path: &OsStr, cwd: &Path, available: bool) {
    check_path(Some(path), cwd, available);
}

#[test]
fn probe_in_child() {
    let Ok(expected) = std::env::var("SKILLFS_EXPECT_UV") else {
        return;
    };
    let profile = EnvironmentProfile::detect();
    assert_eq!(profile.has_command("uv"), expected == "yes");
    if std::env::var_os("PATH").is_some() {
        assert!(!profile.has_command("git"));
    } else {
        assert!(
            profile.has_command("sh"),
            "system default PATH must find sh"
        );
    }
    let compiled = compiler::compile(
        "<!-- @if has_command(\"uv\") -->\nuse uv\n<!-- @else -->\nuse fallback\n<!-- @endif -->\n",
        &profile,
    );
    assert_eq!(
        compiled,
        if expected == "yes" {
            "use uv\n"
        } else {
            "use fallback\n"
        }
    );
}

#[test]
fn detects_executable_without_which() {
    let temp = tempfile::tempdir().expect("temporary PATH");
    executable(&temp.path().join("uv"));
    check(temp.path().as_os_str(), temp.path(), true);
}

#[test]
fn ignores_a_broken_which_program() {
    let temp = tempfile::tempdir().expect("temporary PATH");
    executable(&temp.path().join("uv"));
    executable(&temp.path().join("which"));
    check(temp.path().as_os_str(), temp.path(), true);
}

#[test]
fn rejects_nonexecutable_files_and_directories() {
    let temp = tempfile::tempdir().expect("temporary PATH");
    let uv = temp.path().join("uv");
    fs::write(&uv, "not executable").expect("write nonexecutable");
    fs::set_permissions(&uv, fs::Permissions::from_mode(0o644)).expect("clear execute bits");
    check(temp.path().as_os_str(), temp.path(), false);
    fs::remove_file(&uv).expect("remove fixture");
    fs::create_dir(&uv).expect("create command-shaped directory");
    check(temp.path().as_os_str(), temp.path(), false);
}

#[test]
fn follows_executable_symlinks_but_rejects_dangling_links() {
    let temp = tempfile::tempdir().expect("temporary PATH");
    let target = temp.path().join("real-uv");
    executable(&target);
    symlink(&target, temp.path().join("uv")).expect("symlink command");
    check(temp.path().as_os_str(), temp.path(), true);
    fs::remove_file(target).expect("make symlink dangling");
    check(temp.path().as_os_str(), temp.path(), false);
}

#[test]
fn continues_past_nonexecutable_path_candidates() {
    let temp = tempfile::tempdir().expect("temporary PATH");
    let first = temp.path().join("first");
    let second = temp.path().join("second");
    fs::create_dir(&first).expect("first PATH directory");
    fs::create_dir(&second).expect("second PATH directory");
    fs::write(first.join("uv"), "not executable").expect("write first candidate");
    executable(&second.join("uv"));
    check(
        &std::env::join_paths([first, second]).expect("join PATH"),
        temp.path(),
        true,
    );
}

#[test]
fn empty_path_component_searches_current_directory() {
    let temp = tempfile::tempdir().expect("temporary PATH");
    executable(&temp.path().join("uv"));
    check(OsStr::new(""), temp.path(), true);
    check(OsStr::new("/skillfs-probe-missing-dir:"), temp.path(), true);
}

#[test]
fn supports_non_utf8_path_directories() {
    let temp = tempfile::tempdir().expect("temporary PATH");
    let bin = temp
        .path()
        .join(std::ffi::OsString::from_vec(b"bin-\xff".to_vec()));
    fs::create_dir(&bin).expect("non-UTF8 PATH directory");
    executable(&bin.join("uv"));
    check(bin.as_os_str(), temp.path(), true);
}

#[test]
fn unset_path_does_not_search_current_directory() {
    let temp = tempfile::tempdir().expect("temporary PATH");
    executable(&temp.path().join("uv"));
    check_path(None, temp.path(), false);
}
