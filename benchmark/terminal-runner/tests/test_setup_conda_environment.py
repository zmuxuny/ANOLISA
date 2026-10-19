# Copyright 2026 Alibaba Cloud
# SPDX-License-Identifier: Apache-2.0
"""Exercise setup's environment selection without installing any software."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

SETUP_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "setup.sh"


@pytest.mark.parametrize(
    ("requested", "existing", "active", "should_create"),
    [
        ("runner.py312", ["runnerXpy312"], False, True),
        ("runner[3]", ["runner[3]"], False, False),
        ("runner.py312", ["runner.py312"], False, False),
        ("runner", ["runner"], False, False),
        ("runner", [], False, True),
        ("runner", ["runner-extra"], False, True),
        ("runner", ["runner"], True, False),
        (None, ["terminal-runner-py312"], False, False),
        ("runner", ["runner", *[f"other-{i}" for i in range(10000)]], False, False),
    ],
    ids=[
        "dot-is-literal",
        "brackets-are-literal",
        "exact-dot",
        "plain-existing",
        "missing",
        "prefix-is-not-match",
        "active-marker",
        "default-name",
        "consume-full-list",
    ],
)
def test_setup_selects_exact_conda_environment(
    tmp_path, requested, existing, active, should_create
):
    root = tmp_path / "terminal-runner"
    (root / "scripts").mkdir(parents=True)
    setup = root / "scripts" / "setup.sh"
    shutil.copyfile(SETUP_SCRIPT, setup)
    (root / "harbor").mkdir()
    (root / "dataset").mkdir()
    home = tmp_path / "home"
    conda_init = home / "miniconda3" / "etc" / "profile.d" / "conda.sh"
    conda_init.parent.mkdir(parents=True)
    conda_init.write_text(
        r"""conda() {
    case "$1" in
        tos) return 0 ;; # Stub only: no real terms acceptance or network calls.
        env) cat "$FAKE_ENV_LIST" ;;
        create)
            [ "$3" = "-n" ] && [ "$4" = "$CONDA_ENV_NAME" ] || return 90
            if grep -Fx -- "$4" "$FAKE_EXISTING" >/dev/null; then
                echo "Attempted to recreate an existing environment" >&2
                return 91
            fi
            printf '%s\n' "$4" >> "$FAKE_CREATED"
            ;;
        activate)
            grep -Fx -- "$2" "$FAKE_EXISTING" >/dev/null ||
                grep -Fx -- "$2" "$FAKE_CREATED" >/dev/null || return 92
            ;;
        *) return 93 ;;
    esac
}
""",
        encoding="utf-8",
    )
    names = tmp_path / "existing.txt"
    names.write_text("".join(f"{name}\n" for name in existing), encoding="utf-8")
    listing = tmp_path / "environments.txt"
    listing.write_text(
        "# conda environments:\n#\n"
        + "".join(f"{name:<24} {'*' if active else ' '} /fake/envs/{name}\n" for name in existing),
        encoding="utf-8",
    )
    created = tmp_path / "created.txt"
    created.touch()
    binaries = tmp_path / "bin"
    binaries.mkdir()
    scripts = {
        "python3": r"""#!/bin/bash
if [ "$1" = "-c" ]; then
    echo 3.11.9
elif [ "$1" = "-m" ] && [ "$2" = "venv" ]; then
    mkdir -p "$3/bin"
    : > "$3/bin/activate"
else
    exit 94
fi
""",
        "git": "#!/bin/bash\nexit 0\n",
        "pip": "#!/bin/bash\nexit 0\n",
    }
    for name, script in scripts.items():
        path = binaries / name
        path.write_text(script, encoding="utf-8")
        path.chmod(0o755)
    env = {
        **os.environ,
        "HOME": str(home),
        "PATH": f"{binaries}:/usr/bin:/bin",
        "BASH_ENV": "/dev/null",
        "FAKE_ENV_LIST": str(listing),
        "FAKE_EXISTING": str(names),
        "FAKE_CREATED": str(created),
    }
    if requested is None:
        env.pop("CONDA_ENV_NAME", None)
    else:
        env["CONDA_ENV_NAME"] = requested
    result = subprocess.run(
        ["/bin/bash", str(setup)],
        cwd=root,
        text=True,
        capture_output=True,
        timeout=10,
        env=env,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert created.read_text(encoding="utf-8").splitlines() == (
        [requested] if should_create else []
    )
    assert "Setup complete." in result.stdout
