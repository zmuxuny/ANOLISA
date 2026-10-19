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

"""UTF-8 hint assets do not depend on the process locale."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

CHILD = r"""
import importlib.util
import json
import locale
import logging
import sys
from types import ModuleType

for name, symbol in (
    ("harbor.agents.base", "BaseAgent"),
    ("harbor.environments.base", "BaseEnvironment"),
    ("harbor.models.agent.context", "AgentContext"),
):
    stub = ModuleType(name)
    setattr(stub, symbol, type(symbol, (), {}))
    sys.modules[name] = stub
spec = importlib.util.spec_from_file_location("skill_encoding_adapter", sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
agent = module.OpenClawExternalAgent.__new__(module.OpenClawExternalAgent)
agent.logger = logging.getLogger("skill_encoding")
agent._task_name = "task"
text = agent._load_skill_hint()
print(json.dumps({"text": text, "encoding": locale.getencoding(), "utf8": sys.flags.utf8_mode}))
"""


def read_hint_in_ascii_locale(dataset: Path, auto: bool) -> dict:
    env = {
        **os.environ,
        "LC_ALL": "C",
        "LANG": "C",
        "PYTHONCOERCECLOCALE": "0",
        "PYTHONUTF8": "0",
        "DATASET_DIR": str(dataset),
        "SKILL_FROM_SOLUTION": "1" if auto else "0",
    }
    source = Path(__file__).parents[1] / "external_agent" / "openclaw_external_agent.py"
    result = subprocess.run(
        [sys.executable, "-c", CHILD, str(source)],
        env=env,
        capture_output=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
    payload = json.loads(result.stdout)
    assert payload["utf8"] == 0
    assert payload["encoding"].lower() in ("ascii", "ansi_x3.4-1968", "us-ascii")
    return payload


@pytest.mark.skipif(os.name != "posix", reason="requires the POSIX C locale")
@pytest.mark.parametrize("kind", ["manual", "solution"])
@pytest.mark.parametrize("text", ["Inspect the files", "Inspect caf\u00e9 \u4e2d\u6587 files"])
def test_hint_assets_are_utf8_under_ascii_locale(tmp_path: Path, kind: str, text: str) -> None:
    task = tmp_path / "task"
    task.mkdir()
    if kind == "manual":
        (task / "skill.md").write_text(text, encoding="utf-8")
    else:
        (task / "solution").mkdir()
        (task / "solution" / "solve.sh").write_text(f"echo '{text}'\n", encoding="utf-8")
    payload = read_hint_in_ascii_locale(tmp_path, auto=kind == "solution")
    assert text in payload["text"]


@pytest.mark.skipif(os.name != "posix", reason="requires the POSIX C locale")
def test_utf8_solution_remains_opt_in(tmp_path: Path) -> None:
    solution = tmp_path / "task" / "solution"
    solution.mkdir(parents=True)
    (solution / "solve.sh").write_text("echo 'caf\u00e9'\n", encoding="utf-8")
    assert read_hint_in_ascii_locale(tmp_path, auto=False)["text"] == ""


@pytest.mark.skipif(os.name != "posix", reason="requires the POSIX C locale")
def test_manual_hint_still_takes_priority(tmp_path: Path) -> None:
    solution = tmp_path / "task" / "solution"
    solution.mkdir(parents=True)
    (solution.parent / "skill.md").write_text("Use the manual hint", encoding="utf-8")
    (solution / "solve.sh").write_text("echo 'caf\u00e9'\n", encoding="utf-8")
    assert read_hint_in_ascii_locale(tmp_path, auto=True)["text"] == "Use the manual hint"
