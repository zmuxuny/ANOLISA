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

"""Application-ready patches must not inherit human-oriented Git display settings."""

import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from swe_runner.run.workspace.patches import extract_patch


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout


@pytest.fixture
def repository(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, str]:
    # Do not inherit the test machine's Git identity, filters, signing or hooks.
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "no-global-config"))
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "config", "user.email", "test@example.com")
    (repo / "foo.py").write_text("print('old')\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "base")
    revision = _git(repo, "rev-parse", "HEAD").strip()
    (repo / "foo.py").write_text("print('new')\n", encoding="utf-8")
    # These must still be removed by the existing helper/binary policies.
    (repo / "repro.py").write_text("print('helper')\n", encoding="utf-8")
    (repo / "asset.bin").write_bytes(b"\x00old\xff")
    return repo, revision


def _assert_roundtrip(repo: Path, revision: str, patch_text: str | None, target: Path) -> None:
    assert patch_text is not None
    assert patch_text.startswith("diff --git a/foo.py b/foo.py\n")
    assert "repro.py" not in patch_text
    assert "asset.bin" not in patch_text
    assert "-print('old')\n+print('new')\n" in patch_text
    assert _git(repo, "rev-parse", "HEAD").strip() == revision
    target.mkdir()
    (target / "foo.py").write_text(_git(repo, "show", f"{revision}:foo.py"), encoding="utf-8")
    # SWE-bench consumes patches with one leading path component stripped.
    subprocess.run(
        ["git", "apply", "-p1", "-"], input=patch_text, cwd=target, text=True, capture_output=True, check=True
    )
    assert (target / "foo.py").read_text(encoding="utf-8") == "print('new')\n"
    # Also exercise the plain patch consumer when installed.
    if shutil.which("patch"):
        (target / "foo.py").write_text("print('old')\n", encoding="utf-8")
        subprocess.run(
            ["patch", "--batch", "-p1"], input=patch_text, cwd=target, text=True, capture_output=True, check=True
        )
        assert (target / "foo.py").read_text(encoding="utf-8") == "print('new')\n"
    assert sorted(p.name for p in target.iterdir()) == ["foo.py"]


@pytest.mark.parametrize("explicit_base", [False, True])
@pytest.mark.parametrize(
    "settings",
    [
        (),
        (("diff.noprefix", "true"),),
        (("diff.mnemonicPrefix", "true"),),
        (("diff.srcPrefix", "before/source/"), ("diff.dstPrefix", "after/source/")),
    ],
    ids=["default", "no-prefix", "mnemonic-prefix", "custom-prefixes"],
)
def test_patch_ignores_display_prefixes(
    repository: tuple[Path, str], tmp_path: Path, explicit_base: bool, settings: tuple[tuple[str, str], ...]
) -> None:
    repo, revision = repository
    for key, value in settings:
        _git(repo, "config", key, value)
    config_before = (repo / ".git" / "config").read_bytes()

    patch_text = extract_patch(repo, base_revision=revision if explicit_base else None)

    _assert_roundtrip(repo, revision, patch_text, tmp_path / "applied")
    assert (repo / ".git" / "config").read_bytes() == config_before


@pytest.mark.parametrize("no_prefix", [False, True])
def test_patch_disables_textconv(repository: tuple[Path, str], tmp_path: Path, no_prefix: bool) -> None:
    repo, revision = repository
    converter = tmp_path / "preview.py"
    marker = tmp_path / "preview-called"
    converter.write_text(
        "import sys\nfrom pathlib import Path\n"
        f"Path({str(marker)!r}).write_text('called')\n"
        "print(Path(sys.argv[1]).read_text(errors='replace').replace('old', 'OLD'), end='')\n",
        encoding="utf-8",
    )
    (repo / ".git" / "info" / "attributes").write_text("* diff=preview\n", encoding="utf-8")
    _git(repo, "config", "diff.preview.textconv", shlex.join([sys.executable, str(converter)]))
    if no_prefix:
        _git(repo, "config", "diff.noprefix", "true")
    config_before = (repo / ".git" / "config").read_bytes()

    patch_text = extract_patch(repo, base_revision=revision)

    _assert_roundtrip(repo, revision, patch_text, tmp_path / "applied")
    assert not marker.exists(), "Patch extraction must not invoke a presentation-only converter"
    assert (repo / ".git" / "config").read_bytes() == config_before
