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

"""Keep Harbor command failures in routing feedback and execution metadata."""

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
    spec = importlib.util.spec_from_file_location("openclaw_return_code_test_adapter", path)
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
    ("fields", "expected"),
    [
        ({"return_code": 0}, 0),
        ({"return_code": 17}, 17),
        ({"return_code": -9}, -9),
        ({"exit_code": "8"}, 8),
        ({"returncode": 12}, 12),
        ({"return_code": 9, "exit_code": 0, "returncode": 0}, 9),
        ({"exit_code": 7, "returncode": 0}, 7),
        ({}, 0),
    ],
)
def test_result_exit_code_accepts_harbor_and_legacy_fields(adapter, fields, expected):
    result = SimpleNamespace(**fields)
    assert adapter.OpenClawExternalAgent._result_exit_code(result) == expected


def test_timeout_result_keeps_negative_exit_code(adapter):
    agent = adapter.OpenClawExternalAgent
    assert agent._result_exit_code(agent._make_timeout_result("sleep 5", 1)) == -1


@pytest.mark.parametrize("return_code", [0, 7, -9])
def test_harbor_result_reaches_feedback_and_context(adapter, tmp_path, monkeypatch, return_code):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("OPENCLAW_MAX_ITERATIONS", "2")
    monkeypatch.setenv("OPENCLAW_AGENT_ID", "main")
    agent = adapter.OpenClawExternalAgent.__new__(adapter.OpenClawExternalAgent)
    agent.logger = logging.getLogger(__name__)
    agent.model_name = None
    agent._extra_env = {}
    agent._profile_name = "return-code-regression"
    agent._harbor_container_id = "test-container"
    agent._harbor_image = "test-image"
    agent._harbor_workdir = "/app"
    agent._task_name = "test-task"
    agent._skill_hint = ""
    prompts = []
    commands = []

    def run_openclaw(command, extra_env):
        prompts.append(command[command.index("--message") + 1])
        if len(prompts) == 1:
            return 0, json.dumps({"payloads": [{"text": "```bash\nfixture-command\n```"}]}), ""
        return 23, "", "fixture stops after feedback"

    async def execute(command):
        commands.append(command)
        # Harbor v0.15.0's ExecResult uses return_code, not returncode/exit_code.
        return SimpleNamespace(
            return_code=return_code, stdout="fixture output", stderr="fixture error"
        )

    monkeypatch.setattr(agent, "_sync_run_openclaw", run_openclaw)
    execution = asyncio.run(
        agent._run_agent_loop("test instruction", SimpleNamespace(exec=execute))
    )
    assert commands == ["fixture-command"]
    assert len(prompts) == 2
    assert f"Exit code: {return_code}\n" in prompts[1]
    assert "fixture output" in prompts[1]
    assert "fixture error" in prompts[1]
    assert execution["harbor_executions"][0]["returncode"] == return_code
    context = SimpleNamespace()
    agent._populate_context(context, execution)
    assert context.metadata["harbor_executions"][0]["returncode"] == return_code
