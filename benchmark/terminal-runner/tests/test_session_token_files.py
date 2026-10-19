# Copyright 2026 Alibaba Cloud
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Session-log discovery regressions, with real files and no Harbor runtime."""

from __future__ import annotations

import importlib.util
import json
import logging
import os
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest


@pytest.fixture
def adapter(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    path = Path(__file__).parents[1] / "external_agent" / "openclaw_external_agent.py"
    spec = importlib.util.spec_from_file_location("openclaw_session_files_test_adapter", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    with monkeypatch.context() as imports:
        for name, symbol in (
            ("harbor.agents.base", "BaseAgent"),
            ("harbor.environments.base", "BaseEnvironment"),
            ("harbor.models.agent.context", "AgentContext"),
        ):
            stub = ModuleType(name)
            setattr(stub, symbol, type(symbol, (), {}))
            imports.setitem(sys.modules, name, stub)
        spec.loader.exec_module(module)
    return module


def write_session(profile: Path, name: str, mtime: int) -> Path:
    path = profile / "agents" / "main" / "sessions" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    usage = {"input": 10, "output": 2, "totalTokens": 12}
    path.write_text(json.dumps({"type": "message", "message": {"usage": usage}}) + "\n")
    os.utime(path, (mtime, mtime))
    return path


def collect(adapter: ModuleType, profile: Path) -> dict | None:
    agent = SimpleNamespace(logger=logging.getLogger(__name__))
    return adapter.OpenClawExternalAgent._collect_session_tokens(agent, str(profile), "main")


@pytest.mark.parametrize("vanished_name", ["a-old.jsonl", "z-new.jsonl"])
def test_session_removed_after_glob_does_not_discard_survivor(
    adapter: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, vanished_name: str
) -> None:
    paths = [
        write_session(tmp_path, "a-old.jsonl", 100),
        write_session(tmp_path, "z-new.jsonl", 200),
    ]
    original_glob = adapter.glob.glob

    def glob_then_rotate(pattern: str) -> list[str]:
        matched = original_glob(pattern)
        next(path for path in paths if path.name == vanished_name).unlink()
        return matched

    monkeypatch.setattr(adapter.glob, "glob", glob_then_rotate)
    report = collect(adapter, tmp_path)
    survivor = next(path for path in paths if path.name != vanished_name)
    assert report is not None
    assert report["session_file"] == survivor.name
    assert report["total_tokens"] == 12
    assert report["num_rounds"] == 1


def test_all_sessions_removed_after_glob_returns_no_report(
    adapter: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = write_session(tmp_path, "gone.jsonl", 100)
    original_glob = adapter.glob.glob

    def glob_then_rotate(pattern: str) -> list[str]:
        matched = original_glob(pattern)
        path.unlink()
        return matched

    monkeypatch.setattr(adapter.glob, "glob", glob_then_rotate)
    assert collect(adapter, tmp_path) is None


def test_session_stat_error_does_not_discard_survivor(
    adapter: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_session(tmp_path, "healthy.jsonl", 100)
    unavailable = write_session(tmp_path, "unavailable.jsonl", 200)
    original_getmtime = adapter.os.path.getmtime

    def stat_with_permission_error(path: str) -> float:
        if path == str(unavailable):
            raise PermissionError("session directory became inaccessible")
        return original_getmtime(path)

    monkeypatch.setattr(adapter.os.path, "getmtime", stat_with_permission_error)
    report = collect(adapter, tmp_path)
    assert report is not None
    assert report["session_file"] == "healthy.jsonl"


def test_latest_mtime_wins_over_filename_order(adapter: ModuleType, tmp_path: Path) -> None:
    write_session(tmp_path, "a-new.jsonl", 200)
    write_session(tmp_path, "z-old.jsonl", 100)
    report = collect(adapter, tmp_path)
    assert report is not None
    assert report["session_file"] == "a-new.jsonl"


def test_equal_mtimes_keep_first_sorted_filename(adapter: ModuleType, tmp_path: Path) -> None:
    write_session(tmp_path, "z-last.jsonl", 100)
    write_session(tmp_path, "a-first.jsonl", 100)
    report = collect(adapter, tmp_path)
    assert report is not None
    assert report["session_file"] == "a-first.jsonl"


def test_missing_sessions_returns_no_report(adapter: ModuleType, tmp_path: Path) -> None:
    assert collect(adapter, tmp_path) is None
