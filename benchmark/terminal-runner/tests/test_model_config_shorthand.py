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

"""Verify model overrides through real profile preparation and the agent loop."""

import asyncio
import importlib.util
import json
import logging
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest


@pytest.fixture
def adapter(monkeypatch):
    path = Path(__file__).parents[1] / "external_agent" / "openclaw_external_agent.py"
    spec = importlib.util.spec_from_file_location("openclaw_model_config_test_adapter", path)
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


@pytest.mark.parametrize(
    ("model_defaults", "override", "expected"),
    [
        ({"model": "old/model"}, "new/model", {"primary": "new/model"}),
        (
            {"model": {"primary": "old/model", "fallbacks": ["backup/model"]}},
            "new/model",
            {"primary": "new/model", "fallbacks": ["backup/model"]},
        ),
        ({}, "new/model", {"primary": "new/model"}),
        ({"model": {}}, "new/model", {"primary": "new/model"}),
        ({"model": "old/model"}, None, "old/model"),
        (
            {"model": {"primary": "old/model", "fallbacks": ["backup/model"]}},
            None,
            {"primary": "old/model", "fallbacks": ["backup/model"]},
        ),
    ],
    ids=[
        "string-override",
        "object-fallbacks",
        "absent",
        "empty-object",
        "string-no-override",
        "object-no-override",
    ],
)
def test_model_override_preserves_supported_config_forms(
    adapter, tmp_path, monkeypatch, model_defaults, override, expected
):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("OPENCLAW_MAX_ITERATIONS", "1")
    monkeypatch.setenv("OPENCLAW_AGENT_ID", "main")
    monkeypatch.delenv("NEW_BASE_URL", raising=False)
    monkeypatch.delenv("NEW_API_KEY", raising=False)
    original = tmp_path / ".openclaw" / "openclaw.json"
    original.parent.mkdir()
    aliases = {"old/model": {"alias": "previous"}}
    original.write_text(
        json.dumps(
            {
                "agents": {
                    "defaults": {
                        **model_defaults,
                        "models": aliases,
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    original_bytes = original.read_bytes()
    agent = adapter.OpenClawExternalAgent.__new__(adapter.OpenClawExternalAgent)
    agent.logger = logging.getLogger(__name__)
    agent.model_name = override
    agent._extra_env = {}
    agent._profile_name = "model-config-regression"
    agent._harbor_container_id = "test-container"
    agent._harbor_image = "test-image"
    agent._harbor_workdir = "/app"
    agent._task_name = "test-task"
    agent._skill_hint = ""
    calls = []

    def run_openclaw(command, extra_env):
        calls.append(command)
        return 23, "", "fixture stops after profile preparation"

    monkeypatch.setattr(agent, "_sync_run_openclaw", run_openclaw)
    result = asyncio.run(agent._run_agent_loop("test instruction", SimpleNamespace()))
    assert result["returncode"] == 23
    assert len(calls) == 1
    profile = tmp_path / ".openclaw-model-config-regression" / "openclaw.json"
    defaults = json.loads(profile.read_text(encoding="utf-8"))["agents"]["defaults"]
    assert defaults["model"] == expected
    assert defaults["models"]["old/model"] == aliases["old/model"]
    if override:
        assert defaults["models"][override] == {}
        assert calls[0][calls[0].index("--model") + 1] == override
    else:
        assert "--model" not in calls[0]
    assert original.read_bytes() == original_bytes
