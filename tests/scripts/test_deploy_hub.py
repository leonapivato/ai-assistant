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

import hashlib
import os
import re
import sys
from pathlib import Path
from typing import Any

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


def _staged(plan: str) -> str:
    """The staged wheel path out of a rendered plan — the scp destination."""
    line = next(line for line in plan.splitlines() if line.startswith("stage   :"))
    return line.split(":")[-1]


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

    assert "export XDG_RUNTIME_DIR=/run/user/$(id -u); systemctl --user restart" in plan
    assert "XDG_RUNTIME_DIR=/run/user/$(id -u) journalctl --user -u ai-assistant-hub" in plan
    assert "XDG_RUNTIME_DIR=/run/user/$(id -u) systemctl --user is-active" in plan


def test_the_runtime_dir_is_assigned_inside_the_login_shell_not_before_su(tmp_path: Path) -> None:
    # `su -` resets the environment, so an assignment ahead of it never reaches
    # the inner shell. The uid must likewise be resolved on the box.
    plan = _dry_run(_repo(tmp_path))

    assert "XDG_RUNTIME_DIR=/run/user/$(id -u) su - " not in plan
    assert "su - assistant -c 'XDG_RUNTIME_DIR=" in plan


def test_readiness_is_bound_to_this_start_of_the_unit(tmp_path: Path) -> None:
    # A timestamp window is captured before the restart is issued, so it can
    # contain the *previous* process's hub_ready and verify a replacement that
    # never became ready. The InvocationID names one start and only that one.
    plan = _dry_run(_repo(tmp_path))

    assert "systemctl --user show -p InvocationID --value ai-assistant-hub" in plan
    assert "journalctl --user -u ai-assistant-hub" in plan
    assert "_SYSTEMD_INVOCATION_ID=" in plan
    assert "--since" not in plan
    assert "date +%s" not in plan


def test_the_invocation_id_is_printed_only_when_the_restart_succeeded(tmp_path: Path) -> None:
    # With `;` a failed restart would still report an id — the OLD invocation's,
    # whose journal does contain hub_ready.
    plan = _dry_run(_repo(tmp_path))

    assert "systemctl --user restart ai-assistant-hub && echo INVOCATION_ID=" in plan


def test_a_restart_that_reports_no_invocation_id_refuses(tmp_path: Path) -> None:
    with pytest.raises(_MODULE.DeployError, match="no unit InvocationID"):
        _MODULE.invocation_id("some other output\n")


def test_an_empty_invocation_id_refuses_rather_than_matching_everything(tmp_path: Path) -> None:
    with pytest.raises(_MODULE.DeployError, match="no unit InvocationID"):
        _MODULE.invocation_id("INVOCATION_ID=\n")


def test_an_invocation_id_is_read_back(tmp_path: Path) -> None:
    assert _MODULE.invocation_id("noise\nINVOCATION_ID=abc123\n") == "abc123"


def test_verification_asserts_the_unit_is_active(tmp_path: Path) -> None:
    plan = _dry_run(_repo(tmp_path))

    assert "echo UNIT_STATE=$(" in plan
    assert "systemctl --user is-active ai-assistant-hub" in plan
    assert "hub_ready" in plan


def test_the_marker_is_written_after_the_install_not_before(tmp_path: Path) -> None:
    plan = _dry_run(_repo(tmp_path))
    lines = plan.splitlines()

    install = next(i for i, line in enumerate(lines) if "uv pip install" in line)
    marker = next(i for i, line in enumerate(lines) if "commit=" in line)
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
        "/elsewhere/custom-9.9.whl",
        "--wheel-commit",
        "HEAD",
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
        "custom-9.9.whl",
    ):
        assert expected in plan, expected
    assert _staged(plan).startswith("/srv/stage/deploy-hub-")


def test_with_deps_drops_the_no_deps_flag(tmp_path: Path) -> None:
    plan = _dry_run(_repo(tmp_path), "--with-deps")

    assert "--no-deps" not in plan
    assert "--force-reinstall" in plan


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/srv/wheel.whl", "/srv/wheel.whl"),
        ("/var/lib/deploy marker", "'/var/lib/deploy marker'"),
        # A leading tilde stays bare so the login shell expands it — these paths
        # are written relative to the service user's home precisely for that.
        ("~/DEPLOYED_COMMIT", "~/DEPLOYED_COMMIT"),
        ("~/my notes/DEPLOYED", "~/'my notes/DEPLOYED'"),
        ("~", "~"),
        ("~other/x y", "~other/'x y'"),
        # Anything that is not `~` or `~username` before the first slash is not a
        # tilde form; leaving it bare would make a path argument a second command.
        ("~; touch /tmp/pwned", "'~; touch /tmp/pwned'"),
        ("~ evil", "'~ evil'"),
        ("~$(id)/x", "'~$(id)/x'"),
        ("~-weird/x", "'~-weird/x'"),
    ],
)
def test_a_remote_path_is_one_shell_word_with_the_tilde_still_live(
    path: str, expected: str
) -> None:
    assert _MODULE.remote_path(path) == expected


def test_a_hostile_marker_cannot_become_a_second_command(tmp_path: Path) -> None:
    plan = _dry_run(_repo(tmp_path), "--marker", "~; touch /tmp/pwned")

    assert "> ~; touch /tmp/pwned" not in plan


def test_a_marker_path_with_a_space_is_not_split_by_the_redirection(tmp_path: Path) -> None:
    # Unquoted, `> /var/lib/deploy marker` redirects to /var/lib/deploy and hands
    # `marker` to printf as an argument — the marker lands in the wrong file.
    plan = _dry_run(_repo(tmp_path), "--marker", "/var/lib/deploy marker")

    assert "/var/lib/deploy marker" in plan
    assert "> /var/lib/deploy marker" not in plan


def test_the_default_paths_render_unquoted_so_the_tilde_expands(tmp_path: Path) -> None:
    plan = _dry_run(_repo(tmp_path))

    assert "--python ~/venv/bin/python" in plan
    assert re.search(r"mv -f ~/DEPLOYED_COMMIT\.[0-9a-f]+\.tmp ~/DEPLOYED_COMMIT;", plan)
    assert "~/.local/bin/uv pip install" in plan


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


def test_a_supplied_wheel_skips_the_build_entirely(tmp_path: Path) -> None:
    # The alternative — building, then looking for a *predicted* name in `dist/` —
    # ships whatever stale wheel happens to carry that name, recorded under
    # today's commit.
    plan = _dry_run(
        _repo(tmp_path), "--wheel", "/elsewhere/custom-9.9.whl", "--wheel-commit", "HEAD"
    )

    assert "deploying the supplied wheel /elsewhere/custom-9.9.whl" in plan
    assert "uv build" not in plan


def test_a_supplied_wheel_without_attested_provenance_refuses(tmp_path: Path) -> None:
    # The marker a deploy writes is what the NEXT deploy diffs uv.lock across, so
    # recording HEAD for a wheel that may have come from anywhere makes that
    # answer wrong rather than merely imprecise.
    result = run(
        "deploy_hub",
        ["hub.example", "--wheel", "/elsewhere/w.whl", "--repo", str(_repo(tmp_path)), "--dry-run"],
    )

    assert result.returncode == 1
    assert "--wheel needs --wheel-commit" in result.stderr


def test_a_supplied_wheels_attested_commit_is_what_gets_recorded(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    earlier = git(repo, "rev-parse", "HEAD~1")
    (repo / "f.txt").write_text("moved on\n")
    git(repo, "commit", "-aqm", "later")

    plan = _dry_run(repo, "--wheel", "/elsewhere/w.whl", "--wheel-commit", earlier)

    assert f"commit={earlier}" in plan
    assert git(repo, "rev-parse", "HEAD") not in plan


def test_an_unresolvable_attested_commit_refuses(tmp_path: Path) -> None:
    result = run(
        "deploy_hub",
        [
            "hub.example",
            "--wheel",
            "/elsewhere/w.whl",
            "--wheel-commit",
            "0" * 40,
            "--repo",
            str(_repo(tmp_path)),
            "--dry-run",
        ],
    )

    assert result.returncode == 1
    assert "is not a commit in" in result.stderr


def test_the_staged_path_is_unique_per_run(tmp_path: Path) -> None:
    # The staging directory is shared. A fixed name lets a second deploy of the
    # same version overwrite the first's wheel between scp and install, so one
    # build is installed while the other's commit and digest go into the marker.
    repo = _repo(tmp_path)

    first, second = _staged(_dry_run(repo)), _staged(_dry_run(repo))

    assert first != second
    assert first.startswith(f"{_MODULE.DEFAULT_STAGE_DIR}/deploy-hub-")


def test_the_staged_wheel_is_removed_after_the_install(tmp_path: Path) -> None:
    plan = _dry_run(_repo(tmp_path))
    lines = plan.splitlines()

    install = next(i for i, line in enumerate(lines) if "uv pip install" in line)
    unstage = next(i for i, line in enumerate(lines) if line.strip().startswith("rm -f "))
    assert install < unstage


# --------------------------------------------------------------------------- #
# Staging: a directory of this deploy's own, and the wheel's own name in it     #
# --------------------------------------------------------------------------- #


def test_the_staged_wheel_keeps_the_name_the_build_gave_it(tmp_path: Path) -> None:
    # The whole of issue #1481. A wheel's filename is its metadata — PEP 427 says
    # five or six dash-delimited components — so the per-run token cannot go in
    # it: `deploy-hub-<token>-` adds two more and `uv pip install` refuses the
    # file before reading a byte of it.
    repo = _repo(tmp_path)
    expected = _MODULE.wheel_name(repo)

    staged = _staged(_dry_run(repo))

    assert staged.rsplit("/", 1)[-1] == expected
    assert len(expected.removesuffix(".whl").split("-")) in (5, 6)


def test_the_per_run_token_names_the_directory_not_the_file(tmp_path: Path) -> None:
    directory, _, name = _staged(_dry_run(_repo(tmp_path))).rpartition("/")

    assert directory.startswith(f"{_MODULE.DEFAULT_STAGE_DIR}/deploy-hub-")
    assert "deploy-hub-" not in name


def test_the_staging_directory_is_created_before_the_wheel_is_copied(tmp_path: Path) -> None:
    # scp does not create the destination's parent, so a missing directory fails
    # the copy rather than the install — three minutes of transfer later.
    plan = _dry_run(_repo(tmp_path))
    lines = plan.splitlines()

    mkdir = next(i for i, line in enumerate(lines) if "mkdir -m 0755 " in line)
    stage = next(i for i, line in enumerate(lines) if line.startswith("stage   :"))
    assert mkdir < stage
    # 0755, because the service user reads the wheel the login user wrote.
    assert f"mkdir -m 0755 {_staged(plan).rsplit('/', 1)[0]}" in plan


def test_the_staging_directory_goes_with_the_wheel_and_not_recursively(tmp_path: Path) -> None:
    plan = _dry_run(_repo(tmp_path))
    lines = plan.splitlines()
    directory = _staged(plan).rsplit("/", 1)[0]

    install = next(i for i, line in enumerate(lines) if "uv pip install" in line)
    rmdir = next(i for i, line in enumerate(lines) if f"rmdir {directory}" in line)
    assert install < rmdir
    # An interpolated path is never handed to a recursive delete; the directory
    # holds one wheel, which the same command has just removed.
    assert "rm -rf" not in plan


def test_a_staging_directory_with_a_space_is_one_shell_word(tmp_path: Path) -> None:
    plan = _dry_run(_repo(tmp_path), "--stage-dir", "/srv/stage dir")

    assert "mkdir -p '/srv/stage dir'" in plan
    assert re.search(r"mkdir -m 0755 '/srv/stage dir/deploy-hub-[0-9a-f]+'", plan)


# --------------------------------------------------------------------------- #
# Verifying the staged wheel before anything installs it                       #
# --------------------------------------------------------------------------- #


def test_the_staged_wheel_is_digested_before_it_is_installed(tmp_path: Path) -> None:
    plan = _dry_run(_repo(tmp_path))
    lines = plan.splitlines()

    verify = next(i for i, line in enumerate(lines) if "sha256sum" in line)
    install = next(i for i, line in enumerate(lines) if "uv pip install" in line)
    assert verify < install
    # As the service user, so one answer settles both readability and integrity.
    assert "su - assistant -c 'echo STAGED_SHA256=$(sha256sum " in plan


def test_a_truncated_transfer_is_caught_before_the_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # An scp killed midway leaves a wheel that installs as far as "unable to
    # locate the end of central directory record", from inside uv.
    monkeypatch.setattr(_MODULE, "_probe", lambda _argv: (0, "STAGED_SHA256=deadbeef\n", ""))

    with pytest.raises(_MODULE.DeployError, match="not the one that was sent"):
        _MODULE._assert_staged(_plan(_repo(tmp_path)), "cafe1234")


def test_a_staged_wheel_the_service_user_cannot_read_is_named_as_that(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # sha256sum writes its complaint to stderr and nothing to stdout, so the
    # label arrives empty — which is a permission answer, not a digest mismatch.
    monkeypatch.setattr(_MODULE, "_probe", lambda _argv: (0, "STAGED_SHA256=\n", ""))

    with pytest.raises(_MODULE.DeployError, match="cannot read the staged wheel"):
        _MODULE._assert_staged(_plan(_repo(tmp_path)), "cafe1234")


def test_an_unanswered_digest_check_is_not_reported_as_a_bad_wheel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(_MODULE, "_probe", lambda _argv: (255, "", "ssh: connect: refused"))

    with pytest.raises(_MODULE.DeployError, match="could not digest the staged wheel"):
        _MODULE._assert_staged(_plan(_repo(tmp_path)), "cafe1234")


def test_a_login_banner_does_not_hide_the_staged_digest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    banner = "Welcome to Ubuntu 24.04 LTS\n\nSTAGED_SHA256=cafe1234\n"
    monkeypatch.setattr(_MODULE, "_probe", lambda _argv: (0, banner, ""))

    _MODULE._assert_staged(_plan(_repo(tmp_path)), "cafe1234")


# --------------------------------------------------------------------------- #
# Cleanup: the failure paths are the ones that get retried                     #
# --------------------------------------------------------------------------- #


def _staged_plan(repo: Path) -> Any:
    """A plan holding a local file to stand in for the built wheel."""
    wheel = repo / "ai_assistant-0.1.0-py3-none-any.whl"
    wheel.write_bytes(b"not really a wheel, but it has a digest")
    parsed = _MODULE._parser().parse_args(["hub.example", "--repo", str(repo)])
    plan = _MODULE.Plan(parsed, wheel.name)
    plan.use(wheel)
    return plan


def _remote_recorder(monkeypatch: pytest.MonkeyPatch, plan: Any, *, fail_at: str) -> list[str]:
    """Record every remote command, failing at the first one matching ``fail_at``.

    The digest probe answers correctly, so a run only stops where it is told to.
    """
    issued: list[str] = []
    digest = hashlib.sha256(plan.local.read_bytes()).hexdigest()
    answers = f"STAGED_SHA256={digest}\nINVOCATION_ID=inv\nUNIT_STATE=active\nhub_ready jobs=[]\n"

    def _record(argv: list[str], **_kwargs: object) -> str:
        issued.append(" ".join(argv))
        if fail_at in issued[-1]:
            raise _MODULE.DeployError(f"{fail_at} failed")
        return answers

    def _probe(argv: list[str]) -> tuple[int, str, str]:
        issued.append(" ".join(argv))
        if fail_at in issued[-1]:
            return 1, "", f"{fail_at} failed"
        return 0, answers, ""

    monkeypatch.setattr(_MODULE, "_run_local", _record)
    monkeypatch.setattr(_MODULE, "_probe", _probe)
    return issued


@pytest.mark.parametrize("step", ["scp", "chmod 0644", "uv pip install"])
def test_a_failed_deploy_still_removes_its_staging_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, step: str
) -> None:
    # A dropped transfer leaves tens of megabytes on the box, and a directory per
    # attempt under a name nothing will look for again. Unstaging only on the
    # happy path means the runs that get retried are the ones that accumulate.
    plan = _staged_plan(_repo(tmp_path))
    issued = _remote_recorder(monkeypatch, plan, fail_at=step)

    with pytest.raises(_MODULE.DeployError, match=step.split(maxsplit=1)[0]):
        _MODULE._install_and_verify(plan, "abc1234", "", "0.0.1")

    assert any("rmdir" in command for command in issued), issued
    # And nothing is recorded for a deploy that did not happen.
    assert not any("commit=abc1234" in command for command in issued), issued


def test_a_failed_digest_check_removes_the_staging_directory_and_installs_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = _staged_plan(_repo(tmp_path))
    issued = _remote_recorder(monkeypatch, plan, fail_at="sha256sum")

    with pytest.raises(_MODULE.DeployError, match="could not digest the staged wheel"):
        _MODULE._install_and_verify(plan, "abc1234", "", "0.0.1")

    assert any("rmdir" in command for command in issued), issued
    assert not any("uv pip install" in command for command in issued), issued


def test_a_successful_deploy_still_unstages_exactly_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = _staged_plan(_repo(tmp_path))
    issued = _remote_recorder(monkeypatch, plan, fail_at="nothing fails")

    _MODULE._install_and_verify(plan, "abc1234", "", "0.0.1")

    assert sum("rmdir" in command for command in issued) == 1, issued
    # The install happened, and the marker followed it rather than the cleanup.
    install = next(i for i, c in enumerate(issued) if "uv pip install" in c)
    marker = next(i for i, c in enumerate(issued) if "commit=abc1234" in c)
    assert install < marker


def test_a_cleanup_that_cannot_run_warns_rather_than_becoming_the_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # On the way out of an error it would replace the reason with a symptom, and
    # after a successful install it would fail a deploy that worked.
    monkeypatch.setattr(_MODULE, "_probe", lambda _argv: (255, "", "ssh: connect: refused"))

    _MODULE._discard_stage(_plan(_repo(tmp_path)))

    assert "could not remove the staging directory" in capsys.readouterr().err


def test_a_cleanup_with_no_ssh_at_all_warns_rather_than_raising(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def _no_ssh(_argv: list[str]) -> tuple[int, str, str]:
        raise _MODULE.DeployError("ssh not found on PATH")

    monkeypatch.setattr(_MODULE, "_probe", _no_ssh)

    _MODULE._discard_stage(_plan(_repo(tmp_path)))

    assert "ssh not found on PATH" in capsys.readouterr().err


def test_without_a_supplied_wheel_the_build_goes_to_a_fresh_directory(tmp_path: Path) -> None:
    plan = _dry_run(_repo(tmp_path))

    assert "uv build --wheel --out-dir" in plan
    assert "dist/" not in plan


@pytest.mark.parametrize("produced", [(), ("one.whl", "two.whl")])
def test_the_build_must_produce_exactly_one_wheel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, produced: tuple[str, ...]
) -> None:
    out = tmp_path / "out"
    out.mkdir()
    for name in produced:
        (out / name).write_bytes(b"x")
    monkeypatch.setattr(_MODULE, "_run_local", lambda *_a, **_k: "")

    with pytest.raises(_MODULE.DeployError, match="not exactly one wheel"):
        _MODULE.build_wheel(tmp_path, out)


def test_the_build_adopts_the_single_wheel_it_produced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = tmp_path / "out"
    out.mkdir()
    (out / "whatever_the_build_named_it.whl").write_bytes(b"x")
    monkeypatch.setattr(_MODULE, "_run_local", lambda *_a, **_k: "")

    assert _MODULE.build_wheel(tmp_path, out).name == "whatever_the_build_named_it.whl"


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


def test_an_unanswered_is_active_check_is_not_reported_as_an_inactive_unit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # `systemctl is-active` exits non-zero *because* the unit is not active, so a
    # status alone cannot separate that from a dropped connection. Empty output
    # means systemctl never spoke.
    monkeypatch.setattr(_MODULE, "_probe", lambda _argv: (255, "", "ssh: connect: refused"))

    with pytest.raises(_MODULE.DeployError, match="could not ask whether the unit is active"):
        _MODULE._assert_active(_plan(_repo(tmp_path)))


def test_an_inactive_unit_is_reported_as_inactive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(_MODULE, "_probe", lambda _argv: (0, "UNIT_STATE=failed\n", ""))

    with pytest.raises(_MODULE.DeployError, match="the unit is failed"):
        _MODULE._assert_active(_plan(_repo(tmp_path)))


def test_an_active_unit_passes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_MODULE, "_probe", lambda _argv: (0, "UNIT_STATE=active\n", ""))

    _MODULE._assert_active(_plan(_repo(tmp_path)))


def test_a_login_banner_does_not_read_as_a_failed_unit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # `su -` starts a LOGIN shell by design, and a real box's profile and MOTD
    # print to stdout. Comparing all of stdout to "active" would abort a deploy
    # that worked, after the install and the restart had already happened.
    banner = "Welcome to Ubuntu 24.04 LTS\n\n * Support: https://example\nUNIT_STATE=active\n"
    monkeypatch.setattr(_MODULE, "_probe", lambda _argv: (0, banner, ""))

    _MODULE._assert_active(_plan(_repo(tmp_path)))


def test_a_banner_with_no_state_line_is_a_check_that_did_not_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(_MODULE, "_probe", lambda _argv: (255, "Welcome\n", "ssh: refused"))

    with pytest.raises(_MODULE.DeployError, match="could not ask whether the unit is active"):
        _MODULE._assert_active(_plan(_repo(tmp_path)))


def test_a_banner_does_not_hide_the_invocation_id(tmp_path: Path) -> None:
    assert _MODULE.invocation_id("Welcome to Ubuntu\nINVOCATION_ID=abc123\n") == "abc123"


def test_a_failed_journal_poll_is_reported_as_itself(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # journalctl exits 0 when a match selects nothing, so a non-zero status is ssh
    # or su or journalctl failing. Swallowing it spends the whole timeout and then
    # reports the one thing that is not wrong: that the unit never logged
    # hub_ready.
    monkeypatch.setattr(_MODULE, "_probe", lambda _argv: (255, "", "ssh: connect: refused"))
    plan = _plan(_repo(tmp_path))

    with pytest.raises(_MODULE.DeployError, match="could not read the unit's journal"):
        _MODULE._wait_for_ready(plan, "abc123")


def test_a_successful_but_silent_journal_still_times_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(_MODULE, "_probe", lambda _argv: (0, "-- No entries --\n", ""))
    plan = _plan(_repo(tmp_path), "--ready-timeout", "0")

    with pytest.raises(_MODULE.DeployError, match="did not log hub_ready"):
        _MODULE._wait_for_ready(plan, "abc123")


def test_hub_ready_in_this_invocations_journal_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(_MODULE, "_probe", lambda _argv: (0, "hub_ready jobs=[]\n", ""))

    _MODULE._wait_for_ready(_plan(_repo(tmp_path), "--ready-timeout", "0"), "abc123")


def _plan(repo: Path, *args: str) -> object:
    """A plan built from parsed arguments, for the checks that run before any ssh."""
    parsed = _MODULE._parser().parse_args(["hub.example", "--repo", str(repo), *args])
    return _MODULE.Plan(parsed, "w.whl")


def test_an_uncommitted_lockfile_is_visible(tmp_path: Path) -> None:
    repo = _repo(tmp_path)

    assert not _MODULE.lockfile_uncommitted(repo)
    (repo / "uv.lock").write_text("version = 2\n")
    assert _MODULE.lockfile_uncommitted(repo)


def test_an_uncommitted_lockfile_refuses_a_no_deps_install(tmp_path: Path) -> None:
    # With --allow-dirty the deployed commit is HEAD, so `git diff HEAD HEAD` sees
    # nothing — the commit range reads clean while the wheel being built needs a
    # dependency the box does not have. The refusal runs before the box is
    # contacted at all, which is why this needs no remote.
    repo = _repo(tmp_path)
    (repo / "uv.lock").write_text("version = 2\n")

    with pytest.raises(_MODULE.DeployError, match=r"uv\.lock is modified"):
        _MODULE._check_drift(_plan(repo, "--allow-dirty"), repo, "HEAD")


def test_with_deps_accepts_an_uncommitted_lockfile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo(tmp_path)
    (repo / "uv.lock").write_text("version = 2\n")
    reads: list[list[str]] = []

    def _record(argv: list[str], **_kwargs: object) -> str:
        reads.append(argv)
        return ""

    monkeypatch.setattr(_MODULE, "_run_local", _record)

    # Reaches the marker read rather than refusing — and the read is stubbed,
    # because a unit test does not contact a host (CONTRIBUTING.md, "Testing").
    _MODULE._check_drift(_plan(repo, "--allow-dirty", "--with-deps"), repo, "HEAD")

    assert len(reads) == 1
    assert reads[0][0] == "ssh"


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

    assert _MODULE.lockfile_drift(repo, deployed, "HEAD") is None


def test_a_changed_lockfile_is_drift(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    deployed = git(repo, "rev-parse", "HEAD")
    (repo / "uv.lock").write_text("version = 2\n")
    git(repo, "commit", "-aqm", "bump deps")

    drift = _MODULE.lockfile_drift(repo, deployed, "HEAD")

    assert drift is not None
    assert "uv.lock" in drift


def test_drift_is_measured_to_the_commit_being_deployed_not_to_head(tmp_path: Path) -> None:
    # With a supplied wheel, HEAD is not what is being installed.
    repo = _repo(tmp_path)
    deployed = git(repo, "rev-parse", "HEAD")
    target = git(repo, "rev-parse", "HEAD")
    (repo / "uv.lock").write_text("version = 2\n")
    git(repo, "commit", "-aqm", "bump deps after the wheel was built")

    assert _MODULE.lockfile_drift(repo, deployed, target) is None
    assert _MODULE.lockfile_drift(repo, deployed, "HEAD") is not None


def test_an_unknown_deployed_commit_raises_rather_than_reading_as_clean(tmp_path: Path) -> None:
    repo = _repo(tmp_path)

    with pytest.raises(_MODULE.DeployError, match="not in this clone's history"):
        _MODULE.lockfile_drift(repo, "0" * 40, "HEAD")


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


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # What a box deployed by hand before this recipe existed actually holds.
        ("ece6d22d\n", "ece6d22d"),
        ("ece6d22d", "ece6d22d"),
        ("ece6d22d-dirty\n", "ece6d22d"),
        ("0123456789abcdef0123456789abcdef01234567\n", "0123456789abcdef0123456789abcdef01234567"),
        # Too short to be a sha, and not hex at all: neither is a commit.
        ("abc123\n", None),
        ("deployed by hand\n", None),
        # The bare form was ONE line holding one sha. More than that is not it,
        # and guessing which line to trust is what a banner would exploit.
        ("Welcome to Ubuntu 24.04 LTS\n\nece6d22d\n", None),
        ("ece6d22d\nsomething else\n", None),
    ],
)
def test_a_pre_recipe_bare_sha_marker_is_read_rather_than_called_absent(
    text: str, expected: str | None
) -> None:
    # Reading it as absent says "dependency drift is UNKNOWN" about a box that
    # records exactly what is deployed (issue #1481).
    assert _MODULE.marker_commit(text) == expected


def test_the_key_value_form_wins_over_a_trailing_hex_line() -> None:
    # `wheel_sha256=` is hex, and it is last. The field is the answer.
    marker = "commit=abc1234\nwheel_sha256=0123456789abcdef\n"

    assert _MODULE.marker_commit(marker) == "abc1234"


# --------------------------------------------------------------------------- #
# Telling an absent marker from a login banner                                 #
# --------------------------------------------------------------------------- #


def test_the_marker_read_brackets_what_cat_produced(tmp_path: Path) -> None:
    plan = _dry_run(_repo(tmp_path))

    assert re.search(
        r"echo MARKER_BEGIN_([0-9a-f]+); cat ~/DEPLOYED_COMMIT 2>/dev/null; "
        r"echo; echo MARKER_END_\1",
        plan,
    )


def test_the_brackets_carry_this_runs_token_so_a_banner_cannot_imitate_them(
    tmp_path: Path,
) -> None:
    # A fixed pair could simply be printed by the service user's profile, ahead
    # of the command that emits the real ones — and it is the FIRST pair that
    # gets read.
    repo = _repo(tmp_path)

    first = re.findall(r"MARKER_BEGIN_(\w+)", _dry_run(repo))
    second = re.findall(r"MARKER_BEGIN_(\w+)", _dry_run(repo))

    assert first
    assert second
    assert first[0] != second[0]


@pytest.mark.parametrize(
    ("output", "expected"),
    [
        ("MARKER_BEGIN_tok\ncommit=abc1234\n\nMARKER_END_tok\n", "commit=abc1234\n"),
        ("Welcome to Ubuntu\nMARKER_BEGIN_tok\nece6d22d\n\nMARKER_END_tok\n", "ece6d22d\n"),
        # An absent marker: `cat` said nothing, and the brackets prove it.
        ("Welcome to Ubuntu\nMARKER_BEGIN_tok\n\nMARKER_END_tok\n", ""),
        # The command never ran at all, so nothing here is marker content.
        ("ssh: connect: refused\n", ""),
        ("", ""),
        # Brackets from some other run are not this run's answer.
        ("MARKER_BEGIN_other\ncommit=abc1234\nMARKER_END_other\n", ""),
    ],
)
def test_only_what_lies_between_the_brackets_is_marker(output: str, expected: str) -> None:
    assert _MODULE.marker_body(output, "tok") == expected


def test_a_banner_ending_in_a_short_revision_is_not_a_deployed_commit() -> None:
    # The blocker this bracketing exists for: on a fresh box the whole of the
    # read's output is banner, and a banner ending in a revision that resolves in
    # THIS clone would be diffed against — concluding uv.lock is clean, and
    # installing --no-deps, on a box with no deployed dependency state at all.
    fresh_box = "Last login: Sat Aug 23\nbuild ece6d22d\nMARKER_BEGIN_tok\n\nMARKER_END_tok\n"

    assert _MODULE.marker_commit(_MODULE.marker_body(fresh_box, "tok")) is None


def test_a_banner_that_prints_a_marker_of_its_own_is_not_this_runs_marker() -> None:
    # The profile runs BEFORE the command, so a fixed bracket pair would be the
    # first one in the output — and the one read.
    hostile = "MARKER_BEGIN_\ncommit=ece6d22d\nMARKER_END_\nMARKER_BEGIN_tok\n\nMARKER_END_tok\n"

    assert _MODULE.marker_body(hostile, "tok") == ""


def test_the_drift_check_reads_the_marker_through_the_brackets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # End to end for the same blocker: a banner naming a commit this clone really
    # holds must still leave drift UNKNOWN, not clean.
    repo = _repo(tmp_path)
    real = git(repo, "rev-parse", "--short", "HEAD")
    plan = _plan(repo)
    banner = f"Last login from {real}\nMARKER_BEGIN_{plan.token}\n\nMARKER_END_{plan.token}\n"  # type: ignore[attr-defined]
    monkeypatch.setattr(_MODULE, "_run_local", lambda *_a, **_k: banner)

    assert _MODULE._check_drift(plan, repo, "HEAD") == ""
    assert "no deployed-commit marker" in capsys.readouterr().err


def test_a_marker_that_swallows_its_own_closing_bracket_reads_as_less_not_more() -> None:
    # Truncating yields no `commit=` line, i.e. UNKNOWN — the safe direction.
    confused = "MARKER_BEGIN_tok\nMARKER_END_tok\ncommit=abc1234\nMARKER_END_tok\n"

    assert _MODULE.marker_commit(_MODULE.marker_body(confused, "tok")) is None


def test_the_marker_is_renamed_into_place_not_redirected_onto(tmp_path: Path) -> None:
    # A marker left root-owned by a hand-run deploy cannot be reopened by the
    # service user (issue #1481). `mv` needs only the directory, which is its
    # home — and the next deploy then never reads a half-written marker.
    plan = _MODULE.Plan(
        _MODULE._parser().parse_args(["hub.example", "--repo", str(_repo(tmp_path))]), "w.whl"
    )

    command = plan.write_marker("abc1234", "ff")

    assert f"> ~/DEPLOYED_COMMIT.{plan.token}.tmp && mv -f " in command
    assert f"mv -f ~/DEPLOYED_COMMIT.{plan.token}.tmp ~/DEPLOYED_COMMIT;" in command
    # And a failed rename takes the scratch file with it, rather than leaving one
    # per attempt under a name nothing will look for again.
    assert f"|| {{ rm -f ~/DEPLOYED_COMMIT.{plan.token}.tmp; exit 1; }}" in command


def test_a_hostile_marker_path_is_quoted_in_the_scratch_name_too(tmp_path: Path) -> None:
    plan = _dry_run(_repo(tmp_path), "--marker", "~; touch /tmp/pwned")

    assert "> ~; touch" not in plan
    assert "mv -f ~; touch" not in plan
    assert "rm -f ~; touch" not in plan
