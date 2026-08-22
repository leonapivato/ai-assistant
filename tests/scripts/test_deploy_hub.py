"""Tests for ``scripts/deploy_hub.py`` (issue #1389).

The remote half cannot be exercised from a gate that has no box to talk to, so
what is pinned here is everything decided *before* the first packet: the argument
parsing, the dependency-drift ruling, and the exact command lines ``--dry-run``
renders. That rendering is the deliverable — the recipe exists because two
redeploys failed on details of those command lines, so a test that lets
``sudo -u`` or a missing ``--no-deps`` back in is the test that matters.

``--dry-run`` is also asserted to contact *nothing*: the PATH is shimmed with
``ssh``/``scp``/``uv`` stubs that record being called, and the recording must be
empty.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from _operator_recipes import git, init_repo, load, run

_MODULE = load("deploy_hub")

_PYPROJECT = """\
[project]
name = "ai-assistant"
version = "0.1.0"
"""


def _repo(tmp_path: Path) -> Path:
    """A clone carrying a pyproject and a lockfile, committed."""
    repo = tmp_path / "clone"
    init_repo(repo)
    (repo / "pyproject.toml").write_text(_PYPROJECT)
    (repo / "uv.lock").write_text("version = 1\n")
    git(repo, "add", "pyproject.toml", "uv.lock")
    git(repo, "commit", "-qm", "project")
    return repo


def _dry_run(repo: Path, *args: str) -> str:
    """Render the plan for ``repo``, asserting the run succeeded."""
    result = run("deploy_hub", ["hub.example", *args, "--repo", str(repo), "--dry-run"])
    assert result.returncode == 0, result.stderr
    return result.stdout


# --------------------------------------------------------------------------- #
# The command lines the recipe exists to encode                                #
# --------------------------------------------------------------------------- #


def test_install_runs_in_a_login_shell_and_never_through_sudo(tmp_path: Path) -> None:
    plan = _dry_run(_repo(tmp_path))

    assert "su - assistant -c '~/.local/bin/uv pip install" in plan
    assert "sudo" not in plan


def test_install_targets_the_venv_python_with_no_deps_and_force_reinstall(tmp_path: Path) -> None:
    plan = _dry_run(_repo(tmp_path))

    assert "--python ~/venv/bin/python --no-deps --force-reinstall" in plan
    # The venv is uv-managed and has no `pip` at all, so this must never appear.
    assert "pip install" in plan
    assert "python -m pip" not in plan


def test_restart_and_journal_carry_the_user_session_bus(tmp_path: Path) -> None:
    plan = _dry_run(_repo(tmp_path))

    assert "XDG_RUNTIME_DIR=/run/user/$(id -u) systemctl --user restart ai-assistant-hub" in plan
    assert "XDG_RUNTIME_DIR=/run/user/$(id -u) journalctl --user -u ai-assistant-hub" in plan


def test_the_runtime_dir_is_assigned_inside_the_login_shell_not_before_su(tmp_path: Path) -> None:
    # `su -` resets the environment, so an assignment ahead of it never reaches
    # the inner shell. The uid must likewise be resolved on the box.
    plan = _dry_run(_repo(tmp_path))

    assert "XDG_RUNTIME_DIR=/run/user/$(id -u) su - " not in plan
    assert "su - assistant -c 'XDG_RUNTIME_DIR=" in plan


def test_journal_window_is_bounded_by_the_boxs_own_clock(tmp_path: Path) -> None:
    plan = _dry_run(_repo(tmp_path))

    # The epoch is read on the box and fed straight back to `--since`, so a clock
    # skew between here and there cannot narrow the window past the restart.
    assert "echo RESTART_EPOCH=$(date +%s);" in plan
    assert "--since" in plan
    assert "@<restart epoch>" in plan


def test_verification_asserts_the_unit_is_active(tmp_path: Path) -> None:
    plan = _dry_run(_repo(tmp_path))

    assert "systemctl --user is-active ai-assistant-hub" in plan
    assert "hub_ready" in plan


def test_the_marker_is_written_after_the_install_not_before(tmp_path: Path) -> None:
    plan = _dry_run(_repo(tmp_path))
    lines = plan.splitlines()

    install = next(i for i, line in enumerate(lines) if "uv pip install" in line)
    marker = next(i for i, line in enumerate(lines) if "> ~/DEPLOYED_COMMIT" in line)
    assert install < marker


# --------------------------------------------------------------------------- #
# Arguments: every box-specific value is a parameter                           #
# --------------------------------------------------------------------------- #


def test_service_user_is_positional_and_defaults_to_assistant(tmp_path: Path) -> None:
    repo = _repo(tmp_path)

    assert "su - assistant -c" in _dry_run(repo)
    assert "su - hub -c" in _dry_run(repo, "hub")


def test_no_box_specific_value_is_hardcoded(tmp_path: Path) -> None:
    plan = _dry_run(
        _repo(tmp_path),
        "svc",
        "--ssh-user",
        "ops",
        "--unit",
        "other-hub",
        "--venv",
        "/opt/env",
        "--uv",
        "/opt/bin/uv",
        "--marker",
        "/var/lib/DEPLOYED",
        "--wheel",
        "custom-9.9.whl",
        "--stage-dir",
        "/srv/stage",
    )

    for expected in (
        "ops@hub.example",
        "su - svc -c",
        "other-hub",
        "/opt/env/bin/python",
        "/opt/bin/uv pip install",
        "/var/lib/DEPLOYED",
        "/srv/stage/custom-9.9.whl",
    ):
        assert expected in plan, expected


def test_with_deps_drops_the_no_deps_flag(tmp_path: Path) -> None:
    plan = _dry_run(_repo(tmp_path), "--with-deps")

    assert "--no-deps" not in plan
    assert "--force-reinstall" in plan


def test_ready_timeout_is_a_parameter(tmp_path: Path) -> None:
    assert "up to 5s" in _dry_run(_repo(tmp_path), "--ready-timeout", "5")


# --------------------------------------------------------------------------- #
# A dry run is dry                                                             #
# --------------------------------------------------------------------------- #


def test_dry_run_contacts_nothing(tmp_path: Path) -> None:
    shim = tmp_path / "bin"
    shim.mkdir()
    log = tmp_path / "called.log"
    for name in ("ssh", "scp", "uv"):
        stub = shim / name
        stub.write_text(f'#!/bin/sh\necho {name} >> "{log}"\n')
        stub.chmod(0o755)
    env = dict(os.environ, PATH=f"{shim}{os.pathsep}{os.environ['PATH']}")

    result = run(
        "deploy_hub",
        ["hub.example", "--repo", str(_repo(tmp_path)), "--dry-run"],
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert not log.exists(), log.read_text()


# --------------------------------------------------------------------------- #
# The wheel name, and the tree it is built from                                #
# --------------------------------------------------------------------------- #


def test_wheel_name_is_derived_from_pyproject(tmp_path: Path) -> None:
    assert _MODULE.wheel_name(_repo(tmp_path)) == "ai_assistant-0.1.0-py3-none-any.whl"


@pytest.mark.parametrize(
    ("name", "expected"),
    [("a-b", "a_b"), ("a.b", "a_b"), ("a--b", "a_b"), ("a_.-b", "a_b")],
)
def test_wheel_name_normalises_the_distribution_name(
    tmp_path: Path, name: str, expected: str
) -> None:
    repo = _repo(tmp_path)
    (repo / "pyproject.toml").write_text(f'[project]\nname = "{name}"\nversion = "2.0"\n')

    assert _MODULE.wheel_name(repo) == f"{expected}-2.0-py3-none-any.whl"


def test_missing_project_metadata_is_an_error(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "pyproject.toml").write_text("[tool.other]\nx = 1\n")

    with pytest.raises(_MODULE.DeployError, match="no \\[project\\] name and version"):
        _MODULE.wheel_name(repo)


def test_a_dirty_tree_refuses_because_the_marker_would_lie(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "f.txt").write_text("changed\n")

    result = run("deploy_hub", ["hub.example", "--repo", str(repo), "--dry-run"])

    assert result.returncode == 1
    assert "uncommitted changes" in result.stderr


def test_allow_dirty_records_the_commit_as_dirty(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "f.txt").write_text("changed\n")

    plan = _dry_run(repo, "--allow-dirty")

    assert "-dirty to root@hub.example" in plan
    assert "commit=" in plan


# --------------------------------------------------------------------------- #
# Dependency drift                                                             #
# --------------------------------------------------------------------------- #


def test_an_unchanged_lockfile_is_no_drift(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    deployed = git(repo, "rev-parse", "HEAD")
    (repo / "f.txt").write_text("two\n")
    git(repo, "commit", "-aqm", "code only")

    assert _MODULE.lockfile_drift(repo, deployed) is None


def test_a_changed_lockfile_is_drift(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    deployed = git(repo, "rev-parse", "HEAD")
    (repo / "uv.lock").write_text("version = 2\n")
    git(repo, "commit", "-aqm", "bump deps")

    drift = _MODULE.lockfile_drift(repo, deployed)

    assert drift is not None
    assert "uv.lock" in drift


def test_an_unknown_deployed_commit_raises_rather_than_reading_as_clean(tmp_path: Path) -> None:
    repo = _repo(tmp_path)

    with pytest.raises(_MODULE.DeployError, match="not in this clone's history"):
        _MODULE.lockfile_drift(repo, "0" * 40)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("commit=abc123\nwheel_sha256=ff\n", "abc123"),
        ("wheel_sha256=ff\ncommit=abc123\n", "abc123"),
        ("commit=abc123-dirty\n", "abc123"),
        ("wheel_sha256=ff\n", None),
        ("", None),
        ("commit=\n", None),
    ],
)
def test_marker_commit_reads_the_commit_field(text: str, expected: str | None) -> None:
    assert _MODULE.marker_commit(text) == expected
