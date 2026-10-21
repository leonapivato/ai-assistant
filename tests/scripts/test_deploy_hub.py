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

import fcntl
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path
from types import SimpleNamespace
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


def _rendered(repo: Path, monkeypatch: pytest.MonkeyPatch, token: str) -> str:
    """The plan ``--dry-run`` prints, rendered here with a chosen per-run token.

    The token is drawn once per :class:`Plan`, and :func:`_dry_run` runs the script
    as a *subprocess*, where nothing in this process can reach that draw. Two draws
    left to chance is what issue #1492 is about: they differ with probability
    1 - 2^-32, which is a test that passes almost always rather than a test that
    passes. Rendering in process instead is the same ``render()`` the script's own
    ``--dry-run`` calls on the same ``Plan``, over arguments the script's own parser
    produced — so what is asserted is still the printed plan, and the token in it is
    the one this call chose.
    """
    monkeypatch.setattr(_MODULE, "secrets", SimpleNamespace(token_hex=lambda _bytes: token))
    parsed = _MODULE._parser().parse_args(["hub.example", "--repo", str(repo)])
    return "\n".join(_MODULE.render(_MODULE.Plan(parsed, "w.whl"), "abc1234"))


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
        "--env-file",
        "/etc/hub/env",
        "--backup-dir",
        "/srv/backups",
        "--backup-passphrase-file",
        "/etc/hub/backup-pass",
    )

    for expected in (
        "ops@hub.example",
        "su - svc -c",
        "other-hub",
        "/opt/env/bin/python",
        "/opt/bin/uv pip install",
        "/var/lib/DEPLOYED",
        "custom-9.9.whl",
        "' /etc/hub/env /opt/env/bin/ai-assistant-backup /srv/backups/pre-deploy-",
        "--passphrase-file /etc/hub/backup-pass",
    ):
        assert expected in plan, expected
    assert _staged(plan).startswith("/srv/stage/deploy-hub-")


def test_with_deps_is_the_locked_path_and_never_an_index_resolve(tmp_path: Path) -> None:
    # Issue #2511: `--with-deps` used to drop `--no-deps` and let uv resolve the
    # wheel's requirements against the index, which pulled forty-odd packages
    # newer than uv.lock onto the hub. It now forces the locked set instead.
    plan = _dry_run(_repo(tmp_path), "--with-deps")

    assert "uv export --locked --offline --no-dev --no-emit-project" in plan
    assert "--no-deps -r /tmp/deploy-hub-" in plan
    assert "--no-deps --force-reinstall" in plan
    # Only the locked plan: there is no routine alternative left to print.
    assert "# otherwise" not in plan
    _assert_every_install_is_no_deps(plan)


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


def test_the_staged_path_is_unique_per_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # The staging directory is shared. A fixed name lets a second deploy of the
    # same version overwrite the first's wheel between scp and install, so one
    # build is installed while the other's commit and digest go into the marker.
    # What makes the name safe is that it CARRIES the run's own token, which is
    # what is asserted here — two runs differing is then a consequence rather than
    # a coin the test tosses (issue #1492).
    repo = _repo(tmp_path)

    first = _staged(_rendered(repo, monkeypatch, "1111aaaa"))
    second = _staged(_rendered(repo, monkeypatch, "2222bbbb"))

    assert first == f"{_MODULE.DEFAULT_STAGE_DIR}/deploy-hub-1111aaaa/w.whl"
    assert second == f"{_MODULE.DEFAULT_STAGE_DIR}/deploy-hub-2222bbbb/w.whl"
    # And the script itself, run as it really is, stages under that same shape —
    # the token it drew is unknowable from out here, but the shape is not.
    assert _staged(_dry_run(repo)).startswith(f"{_MODULE.DEFAULT_STAGE_DIR}/deploy-hub-")


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
        _MODULE._install_and_verify(plan, "abc1234", "", "0.0.1", backup=None)

    assert any("rmdir" in command for command in issued), issued
    # And nothing is recorded for a deploy that did not happen.
    assert not any("commit=abc1234" in command for command in issued), issued


def test_a_failed_digest_check_removes_the_staging_directory_and_installs_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = _staged_plan(_repo(tmp_path))
    issued = _remote_recorder(monkeypatch, plan, fail_at="sha256sum")

    with pytest.raises(_MODULE.DeployError, match="could not digest the staged wheel"):
        _MODULE._install_and_verify(plan, "abc1234", "", "0.0.1", backup=None)

    assert any("rmdir" in command for command in issued), issued
    assert not any("uv pip install" in command for command in issued), issued


def test_a_successful_deploy_still_unstages_exactly_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = _staged_plan(_repo(tmp_path))
    issued = _remote_recorder(monkeypatch, plan, fail_at="nothing fails")

    _MODULE._install_and_verify(plan, "abc1234", "", "0.0.1", backup=None)

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


# --------------------------------------------------------------------------- #
# A label a banner also prints: the LAST match is the answer (issue #1413)      #
# --------------------------------------------------------------------------- #
#
# A label is only a prefix, and `su -` starts a login shell by design — so a
# profile or MOTD that prints one of these labels sits AHEAD of the command's
# own answer in stdout. Every command that ends in a labelled line puts that
# `echo` last, after the profile, after the MOTD and after whatever the work
# itself printed, so the last match is the honest rule and the first match is a
# banner's.


def test_a_banner_that_prints_the_same_label_does_not_shadow_the_answer() -> None:
    # The consequence, which is why this is not cosmetic: an INVOCATION_ID taken
    # from a profile names an EARLIER start of the unit, whose journal already
    # holds hub_ready — so `_wait_for_ready` would be satisfied instantly and a
    # deploy that never came up would report as one that did.
    shadowed = "INVOCATION_ID=from-the-profile\nMOTD\nINVOCATION_ID=this-start\n"

    assert _MODULE.invocation_id(shadowed) == "this-start"


def test_an_empty_answer_is_not_rescued_by_an_earlier_label() -> None:
    # The safe direction. An empty id means a systemd too old to report one, and
    # accepting the banner's would bind the readiness check to an unrelated start
    # rather than refusing.
    with pytest.raises(_MODULE.DeployError, match="printed no unit InvocationID"):
        _MODULE.invocation_id("INVOCATION_ID=from-the-profile\nINVOCATION_ID=\n")


def test_a_shadowed_unit_state_reports_the_state_the_command_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    shadowed = "UNIT_STATE=active\nlast login\nUNIT_STATE=failed\n"
    monkeypatch.setattr(_MODULE, "_probe", lambda _argv: (0, shadowed, ""))

    with pytest.raises(_MODULE.DeployError, match="the unit is failed"):
        _MODULE._assert_active(_plan(_repo(tmp_path)))


def test_a_shadowed_digest_is_the_commands_own_not_the_banners(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Reading the banner's digest here would install a truncated wheel while
    # reporting the transfer verified.
    shadowed = "STAGED_SHA256=cafe1234\nSTAGED_SHA256=deadbeef\n"
    monkeypatch.setattr(_MODULE, "_probe", lambda _argv: (0, shadowed, ""))

    with pytest.raises(_MODULE.DeployError, match="not the one that was sent"):
        _MODULE._assert_staged(_plan(_repo(tmp_path)), "cafe1234")


def test_the_label_rule_is_last_match_wins() -> None:
    assert _MODULE._labelled("X=one\nX=two\nX=three\n", "X=") == "three"
    assert _MODULE._labelled("nothing labelled here\n", "X=") is None


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


def _plan(repo: Path, *args: str) -> Any:
    """A plan built from parsed arguments, for the checks that run before any ssh."""
    parsed = _MODULE._parser().parse_args(["hub.example", "--repo", str(repo), *args])
    return _MODULE.Plan(parsed, "w.whl")


def test_an_uncommitted_lockfile_is_visible(tmp_path: Path) -> None:
    repo = _repo(tmp_path)

    assert not _MODULE.lockfile_uncommitted(repo)
    (repo / "uv.lock").write_text("version = 2\n")
    assert _MODULE.lockfile_uncommitted(repo)


def test_an_uncommitted_lockfile_takes_the_locked_path(tmp_path: Path) -> None:
    # With --allow-dirty the deployed commit is HEAD, so `git diff HEAD HEAD` sees
    # nothing — the commit range reads clean while the wheel being built needs a
    # dependency the box does not have. A marker that would otherwise show the
    # lockfile unchanged does not rescue it.
    repo = _repo(tmp_path)
    head = git(repo, "rev-parse", "HEAD")
    (repo / "uv.lock").write_text("version = 2\n")

    reason = _MODULE._rule_on_dependencies(
        _plan(repo, "--allow-dirty"), repo, f"{head}-dirty", f"commit={head}\n", "0.1.0\n"
    )

    assert reason is not None
    assert "uv.lock is modified in the working tree" in reason


def test_a_supplied_wheel_ignores_this_trees_uncommitted_lockfile(tmp_path: Path) -> None:
    # A supplied wheel did not come from this tree, so this tree's lockfile says
    # nothing about what it needs; its attested commit's lockfile does.
    repo = _repo(tmp_path)
    head = git(repo, "rev-parse", "HEAD")
    (repo / "uv.lock").write_text("version = 2\n")
    plan = _plan(repo, "--wheel", "/elsewhere/w.whl", "--wheel-commit", head)

    reason = _MODULE._rule_on_dependencies(plan, repo, head, f"commit={head}\n", "0.1.0\n")

    assert reason is None


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
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A fixed pair could simply be printed by the service user's profile, ahead
    # of the command that emits the real ones — and it is the FIRST pair that
    # gets read. So what has to hold is that the brackets carry THIS run's token;
    # two runs drawing different ones follows from that, and asserting it directly
    # is what makes the test deterministic (issue #1492).
    repo = _repo(tmp_path)

    first = re.findall(r"MARKER_BEGIN_(\w+)", _rendered(repo, monkeypatch, "1111aaaa"))
    second = re.findall(r"MARKER_BEGIN_(\w+)", _rendered(repo, monkeypatch, "2222bbbb"))

    # Once per install mode the dry run prints, and always this run's token.
    assert set(first) == {"1111aaaa"}
    assert set(second) == {"2222bbbb"}


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


def test_the_drift_check_reads_the_marker_through_the_brackets(tmp_path: Path) -> None:
    # End to end for the same blocker: a banner naming a commit this clone really
    # holds must still leave drift UNKNOWN, not clean — and unknown installs the
    # locked set rather than trusting the venv.
    repo = _repo(tmp_path)
    real = git(repo, "rev-parse", "--short", "HEAD")
    plan = _plan(repo)
    banner = f"Last login from {real}\nMARKER_BEGIN_{plan.token}\n\nMARKER_END_{plan.token}\n"

    marker = _MODULE.marker_body(banner, plan.token)

    assert marker == ""
    reason = _MODULE._rule_on_dependencies(plan, repo, "HEAD", marker, "0.1.0\n")
    assert reason is not None
    assert "no deployed-commit marker" in reason


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


# --------------------------------------------------------------------------- #
# The locked set: the box runs what uv.lock says (issue #2511)                 #
# --------------------------------------------------------------------------- #
#
# The run below is the real `_deploy`, with the two seams every remote step goes
# through — `_run_local` and `_probe` — answered by a fake box. `uv build` and
# `uv export` are answered there too, so nothing here builds, resolves or
# contacts a host; the real export is exercised on its own, offline, further down.

LOCKED = _MODULE.LOCKED_REQUIREMENTS
_LOCKED_SET = (
    "anthropic==0.117.0 \\\n"
    "    --hash=sha256:451a0a6905f11dff7663d13e4ee5dbf909eb8942b1d049803c7b937a13ac47ec\n"
    "    # via pydantic-ai-slim\n"
)


def _assert_every_install_is_no_deps(text: str) -> None:
    """No `pip install` anywhere in ``text`` may resolve dependencies."""
    for segment in re.split(r"&&|\n", text):
        if "pip install" in segment:
            assert "--no-deps" in segment, segment


_DATA_DIR = "/home/assistant/data-m44"
#: What the tool says first about the directory it copies.
_DISCLOSED = f"{_MODULE._BACKUP_DISCLOSES}{_DATA_DIR}"


def _healthy_probe(**overrides: object) -> str:
    """The backup preflight's answers from a box that can take the backup.

    Args:
        **overrides: Report fields to answer differently; ``HUB_STATE`` is the
            unit's state, on its own line.

    Returns:
        The probe's output, as :meth:`Plan.probe_backup` prints it.
    """
    hub = overrides.pop("HUB_STATE", "active")
    report: dict[str, object] = {
        "env": "present",
        "data_dir": _DATA_DIR,
        "tool": True,
        "passphrase": "present",
        "passphrase_mode": 0o600,
        "passphrase_path": "/home/assistant/.assistant-backup-pass",
        "backup_dir": "/home/assistant/backups",
        "lock": "held",
        **overrides,
    }
    return f"BACKUP_PROBE={json.dumps(report)}\nHUB_STATE={hub}\n"


class _FakeBox:
    """Answers every local and remote command one deploy issues, and records them."""

    #: The most recent box, for a test whose deploy raised before returning it.
    last: _FakeBox

    def __init__(self, plan: Any, *, marker: str, version: str = "0.1.0") -> None:
        _FakeBox.last = self
        self.plan = plan
        self.marker = marker
        self.version = version
        #: What the backup preflight answers: a healthy box by default.
        self.backup_probe = _healthy_probe()
        #: What the backup tool prints and the status it exits with.
        self.backup_said = f"{_DISCLOSED}\nwrote the artifact\n{_MODULE._BACKUP_VERIFIED}"
        self.backup_status = 0
        self.issued: list[str] = []
        #: The cwd each `uv export` ran in.
        self.exports: list[Path | None] = []
        #: Remote path -> the bytes scp put there.
        self.staged: dict[str, bytes] = {}
        #: Under --delta: what the box answers the delta check, the base it holds,
        #: whether rsync really sends, and what the keep step left as the next base.
        self.delta_probe = "DELTA_RSYNC=/usr/bin/rsync\nDELTA_BASE=usable\nDELTA_KEEP=writable\n"
        self.base = b"an earlier wheel"
        self.rsync_sends = True
        self.keep_status = 0
        self.kept: bytes | None = None
        #: The deploy lock: how the holder answers when it cannot hold it, whether
        #: it still holds it, the command after which it no longer does, how often
        #: it was released, and every ssh command that was sent unfenced.
        self.hold_refused: tuple[int, str, str] | None = None
        self.lease_held = True
        self.lose_lock_after: str | None = None
        self.released = 0
        self.unfenced: list[str] = []

    def hold(self, argv: list[str], said: str) -> Any:
        assert said == self.plan.lock_said
        assert argv == self.plan.holder_command()
        self.issued.append("hold the deploy lock")
        return self.hold_refused or _FakeLease(self)

    def _unfence(self, argv: list[str]) -> list[str]:
        """The ssh command the fence carries, recording any sent without one."""
        if argv[0] != "ssh":
            return argv
        words = shlex.split(argv[-1])
        owner, token = self.plan.owner_file, self.plan.token
        fenced = ["flock", "--", owner, "sh", "-c", _MODULE.FENCE, "sh", owner, token]
        if self.plan.lease is None or words[:-1] != fenced:
            self.unfenced.append(" ".join(argv))
            return argv
        return [*argv[:-1], words[-1]]

    def _issue(self, argv: list[str]) -> None:
        self.issued.append(" ".join(self._unfence(argv)))

    def _after(self) -> None:
        if self.lose_lock_after is not None and self.lose_lock_after in self.issued[-1]:
            self.lease_held = False

    def run_local(self, argv: list[str], *, check: bool = True, cwd: Path | None = None) -> str:
        self._issue(argv)
        try:
            return self._run_local(argv, check=check, cwd=cwd)
        finally:
            self._after()

    def _run_local(self, argv: list[str], *, check: bool, cwd: Path | None) -> str:
        del check
        if argv[:2] == ["uv", "build"]:
            out = Path(argv[argv.index("--out-dir") + 1])
            (out / "ai_assistant-0.1.0-py3-none-any.whl").write_bytes(b"the built wheel")
        elif argv[:2] == ["uv", "export"]:
            self.exports.append(cwd)
            Path(argv[argv.index("--output-file") + 1]).write_text(_LOCKED_SET)
        elif argv[0] == "scp":
            self.staged[argv[2].split(":", 1)[1]] = Path(argv[1]).read_bytes()
        elif argv[0] == "rsync":
            if self.rsync_sends:
                self.staged[argv[-1].split(":", 1)[1]] = Path(argv[-2]).read_bytes()
        elif self.plan.delta and self.plan.seed() in self.issued[-1]:
            self.staged[self.plan.staged] = self.base
        else:
            return self._remote(self.issued[-1])
        return ""

    def _remote(self, text: str) -> str:
        token = self.plan.token
        if "MARKER_BEGIN_" in text:
            return f"Welcome\nMARKER_BEGIN_{token}\n{self.marker}\n\nMARKER_END_{token}\n"
        if "import ai_assistant" in text:
            return f"Welcome\n{self.version}\n"
        if "INVOCATION_ID" in text:
            return "INVOCATION_ID=inv\n"
        return ""

    def probe(self, argv: list[str]) -> tuple[int, str, str]:
        self._issue(argv)
        try:
            return self._probe(self.issued[-1])
        finally:
            self._after()

    def _probe(self, text: str) -> tuple[int, str, str]:
        if "BACKUP_PROBE=" in text:
            return 0, f"Welcome\n{self.backup_probe}", ""
        if "BACKUP_BEGIN_" in text:
            token = self.plan.token
            out = (
                f"Welcome\nBACKUP_BEGIN_{token}\n{self.backup_said}\n\n"
                f"BACKUP_END_{token}={self.backup_status}\nBACKUP_ARTIFACT=present\n"
            )
            return 0, out, ""
        if "sha256sum" in text:
            answers = []
            for label, path in (
                ("STAGED_SHA256=", self.plan.staged),
                ("STAGED_REQUIREMENTS_SHA256=", self.plan.staged_requirements),
            ):
                if path in self.staged:
                    answers.append(f"{label}{hashlib.sha256(self.staged[path]).hexdigest()}")
            return 0, "\n".join(answers) + "\n", ""
        if "is-active" in text:
            return 0, "UNIT_STATE=active\n", ""
        if "journalctl" in text:
            return 0, "hub_ready jobs=[]\n", ""
        return self._delta(text) or (0, "", "")

    def _delta(self, text: str) -> tuple[int, str, str] | None:
        """Answer the delta check and the keep step, or ``None`` for anything else."""
        if "DELTA_BASE=" in text:
            return 0, f"Welcome\n{self.delta_probe}", ""
        if not (self.plan.delta and self.plan.keep_base() in text):
            return None
        if self.keep_status == 0:
            self.kept = self.staged[self.plan.staged]
        return self.keep_status, "", "cp: No space left on device" * bool(self.keep_status)

    def installs(self) -> list[str]:
        return [command for command in self.issued if "pip install" in command]


class _FakeLease:
    """The deploy lock as a fake box holds it."""

    def __init__(self, box: _FakeBox) -> None:
        self.box = box

    def held(self) -> bool:
        return self.box.lease_held

    def release(self) -> None:
        self.box.released += 1


def _deploy_against(
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    *args: str,
    marker: str,
    version: str = "0.1.0",
) -> _FakeBox:
    """Run a real deploy of ``repo`` against a fake box and return what it saw."""
    parsed = _MODULE._parser().parse_args(["hub.example", "--repo", str(repo), *args])
    plan = _MODULE.Plan(parsed, _MODULE.wheel_name(repo))
    box = _FakeBox(plan, marker=marker, version=version)
    monkeypatch.setattr(_MODULE, "_run_local", box.run_local)
    monkeypatch.setattr(_MODULE, "_probe", box.probe)
    monkeypatch.setattr(_MODULE, "_hold", box.hold)
    commit = _MODULE._deployed_commit(parsed, repo)

    _MODULE._deploy(plan, repo, commit)
    # Every deploy that ends holds the lock throughout, and lets it go once.
    assert box.issued[0] == "hold the deploy lock", box.issued
    assert box.unfenced == []
    assert box.released == 1
    return box


def _bump_lockfile(repo: Path) -> str:
    """Commit a lockfile move and return the commit it moved FROM."""
    deployed = git(repo, "rev-parse", "HEAD")
    (repo / "uv.lock").write_text("version = 2\n")
    git(repo, "commit", "-qam", "bump deps")
    return deployed


def test_a_lockfile_move_installs_the_exported_locked_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The ec0a23d4 deploy: uv.lock moved, so the venv's set is stale. The remedy
    # is the lockfile's own set, exported here and shipped beside the wheel.
    repo = _repo(tmp_path)
    deployed = _bump_lockfile(repo)

    box = _deploy_against(repo, monkeypatch, marker=f"commit={deployed}\n")

    assert box.exports == [repo.resolve()]
    staged = box.plan.staged_requirements
    assert box.staged[staged].decode() == _LOCKED_SET
    [install] = box.installs()
    assert f"--no-deps -r {staged} && " in install
    assert install.index("-r ") < install.index("--force-reinstall")
    assert any("deps=locked" in command for command in box.issued)


def test_the_locked_set_is_what_is_installed_and_nothing_is_resolved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo(tmp_path)
    deployed = _bump_lockfile(repo)

    box = _deploy_against(repo, monkeypatch, marker=f"commit={deployed}\n")

    # The file installed from is the very file the export wrote, byte for byte,
    # and the box was made to prove it held that file before anything installed.
    digest = hashlib.sha256(_LOCKED_SET.encode()).hexdigest()
    verify = next(c for c in box.issued if "STAGED_REQUIREMENTS_SHA256=" in c)
    assert box.issued.index(verify) < box.issued.index(box.installs()[0])
    assert box.staged[box.plan.staged_requirements] == _LOCKED_SET.encode()
    assert digest == hashlib.sha256(box.staged[box.plan.staged_requirements]).hexdigest()
    # Every install is --no-deps, so uv on the box has nothing to resolve; and
    # nothing anywhere in the run locks, compiles or resolves.
    _assert_every_install_is_no_deps("\n".join(box.issued))
    for resolver in ("uv lock", "pip compile", "uv sync", "--upgrade"):
        assert not any(resolver in command for command in box.issued), resolver
    # Both staged files go with the directory.
    unstage = next(c for c in box.issued if "rmdir" in c)
    assert box.plan.staged_requirements in unstage


def test_a_first_deploy_into_an_empty_venv_gets_its_dependencies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # No marker, nothing installed: there is no dependency set to keep, and a
    # --no-deps wheel alone would not even import.
    repo = _repo(tmp_path)

    box = _deploy_against(repo, monkeypatch, marker="", version="(not installed)")

    assert len(box.exports) == 1
    [install] = box.installs()
    assert f"-r {box.plan.staged_requirements}" in install


def test_an_absent_marker_alone_takes_the_locked_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Unknown is not clean: something is installed, but nothing shows what set it
    # was installed against. (Nor what commit: ADR-0326 §5:4's ruling wants the flag.)
    box = _deploy_against(_repo(tmp_path), monkeypatch, "--allow-earlier", marker="")

    assert len(box.exports) == 1


def test_an_empty_venv_takes_the_locked_path_whatever_the_marker_says(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A venv recreated under a marker that survived it: the marker shows uv.lock
    # unchanged, and the venv holds nothing that the marker describes. Ruled on
    # its own, because the deploy as a whole now refuses this box before it
    # exports anything: a hub has served there, and no earlier build is left to
    # back its directory up with (ADR-0326 §6:1).
    repo = _repo(tmp_path)
    head = git(repo, "rev-parse", "HEAD")
    marker = f"commit={head}\n"

    reason = _MODULE._rule_on_dependencies(_plan(repo), repo, head, marker, "(not installed)\n")

    assert reason is not None
    assert "no ai_assistant installed" in reason
    with pytest.raises(_MODULE.DeployError, match="holds no build, but the marker shows"):
        _deploy_against(repo, monkeypatch, marker=marker, version="(not installed)")
    assert _FakeBox.last.exports == []


def test_a_deployed_commit_this_clone_lacks_takes_the_locked_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    box = _deploy_against(
        _repo(tmp_path), monkeypatch, "--allow-earlier", marker=f"commit={'0' * 40}\n"
    )

    assert len(box.exports) == 1


def test_an_unchanged_lockfile_deploys_as_cheaply_as_before(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The routine deploy: code moved, uv.lock did not. No export, one file
    # staged, one install command, and that command is exactly today's.
    repo = _repo(tmp_path)
    deployed = git(repo, "rev-parse", "HEAD")
    (repo / "f.txt").write_text("code only\n")
    git(repo, "commit", "-qam", "code only")

    box = _deploy_against(repo, monkeypatch, marker=f"commit={deployed}\n")

    assert box.exports == []
    assert list(box.staged) == [box.plan.staged]
    assert sum(command.startswith("scp ") for command in box.issued) == 1
    [install] = box.installs()
    assert install.endswith(
        "su - assistant -c '~/.local/bin/uv pip install --python ~/venv/bin/python "
        f"--no-deps --force-reinstall {box.plan.staged}'"
    )
    assert LOCKED not in " ".join(box.issued)
    assert any("deps=kept" in command for command in box.issued)


def test_with_deps_forces_the_locked_set_over_an_unchanged_lockfile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The way to put a drifted box back on uv.lock without waiting for a move.
    repo = _repo(tmp_path)
    head = git(repo, "rev-parse", "HEAD")

    box = _deploy_against(repo, monkeypatch, "--with-deps", marker=f"commit={head}\n")

    assert len(box.exports) == 1
    assert f"-r {box.plan.staged_requirements}" in box.installs()[0]


def test_a_supplied_wheel_exports_its_attested_commits_lockfile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The checkout need not be at the commit the wheel came from, so the lockfile
    # exported is read out of git at that commit, not off the working tree.
    repo = _repo(tmp_path)
    attested = git(repo, "rev-parse", "HEAD")
    (repo / "uv.lock").write_text("version = 2\n")
    git(repo, "commit", "-qam", "lockfile moved after the wheel was built")
    wheel = tmp_path / "ai_assistant-0.1.0-py3-none-any.whl"
    wheel.write_bytes(b"a supplied wheel")
    seen: dict[str, str] = {}
    box_run = _FakeBox.run_local

    def _run_local(self: _FakeBox, argv: list[str], **kwargs: Any) -> str:
        if argv[:2] == ["uv", "export"]:
            project = Path(kwargs["cwd"])
            seen["lock"] = (project / "uv.lock").read_text()
            seen["pyproject"] = (project / "pyproject.toml").read_text()
        return box_run(self, argv, **kwargs)

    monkeypatch.setattr(_FakeBox, "run_local", _run_local)

    # No marker, so the commit installed is unknown: ADR-0326 §5:4 wants the flag.
    box = _deploy_against(
        repo,
        monkeypatch,
        "--wheel",
        str(wheel),
        "--wheel-commit",
        attested,
        "--allow-earlier",
        marker="",
    )

    assert len(box.exports) == 1
    assert box.exports[0] != repo.resolve()
    assert seen == {"lock": "version = 1\n", "pyproject": _PYPROJECT}


def test_a_failed_export_stops_the_deploy_before_the_box_is_touched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo(tmp_path)
    deployed = _bump_lockfile(repo)
    box_run = _FakeBox.run_local

    def _run_local(self: _FakeBox, argv: list[str], **kwargs: Any) -> str:
        if argv[:2] == ["uv", "export"]:
            self.issued.append(" ".join(argv))
            raise _MODULE.DeployError("uv failed: the lockfile needs to be updated")
        return box_run(self, argv, **kwargs)

    monkeypatch.setattr(_FakeBox, "run_local", _run_local)
    parsed = _MODULE._parser().parse_args(["hub.example", "--repo", str(repo)])
    plan = _MODULE.Plan(parsed, _MODULE.wheel_name(repo))
    box = _FakeBox(plan, marker=f"commit={deployed}\n")
    monkeypatch.setattr(_MODULE, "_run_local", box.run_local)
    monkeypatch.setattr(_MODULE, "_probe", box.probe)
    monkeypatch.setattr(_MODULE, "_hold", box.hold)

    with pytest.raises(_MODULE.DeployError, match="lockfile needs to be updated"):
        _MODULE._deploy(plan, repo, git(repo, "rev-parse", "HEAD"))

    assert not any("mkdir" in c or c.startswith("scp ") or "uv build" in c for c in box.issued)


def test_an_export_with_no_pinned_requirement_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # An empty file installs nothing and would still read as the locked set.
    def _run_local(argv: list[str], **_kwargs: object) -> str:
        Path(argv[argv.index("--output-file") + 1]).write_text("# nothing here\n")
        return ""

    monkeypatch.setattr(_MODULE, "_run_local", _run_local)
    out = tmp_path / "out"
    out.mkdir()

    with pytest.raises(_MODULE.DeployError, match="no pinned requirement"):
        _MODULE.export_locked(_repo(tmp_path), out, None)


def test_a_truncated_locked_set_is_caught_before_the_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = _plan(_repo(tmp_path), "--with-deps")
    answers = "STAGED_SHA256=cafe1234\nSTAGED_REQUIREMENTS_SHA256=deadbeef\n"
    monkeypatch.setattr(_MODULE, "_probe", lambda _argv: (0, answers, ""))

    with pytest.raises(_MODULE.DeployError, match="staged locked set is not the one"):
        _MODULE._assert_staged(plan, "cafe1234", "0123abcd")


def test_the_dry_run_shows_both_installs_without_with_deps(tmp_path: Path) -> None:
    # A dry run never reads the marker, so it cannot know which install a real
    # run takes; it shows the routine one and then the locked one.
    plan = _dry_run(_repo(tmp_path))
    routine, _, locked = plan.partition("# otherwise")

    assert "uv export" not in routine
    assert "--no-deps -r " not in routine
    assert "uv export --locked --offline --no-dev --no-emit-project" in locked
    assert f"/{LOCKED} && " in locked
    _assert_every_install_is_no_deps(plan)


@pytest.mark.skipif(shutil.which("uv") is None, reason="uv is not on PATH")
def test_the_real_export_pins_exactly_what_uv_lock_records(tmp_path: Path) -> None:
    # The export the deploy runs, for real and offline, over this repository's
    # own pyproject.toml and uv.lock committed into a throwaway clone: every
    # requirement is one pinned version with its hashes, and the versions are
    # the lockfile's — anthropic among them, the package #2511 saw jump a major.
    source = Path(__file__).parents[2]
    repo = tmp_path / "clone"
    init_repo(repo)
    for name in ("pyproject.toml", "uv.lock"):
        shutil.copyfile(source / name, repo / name)
    git(repo, "add", "pyproject.toml", "uv.lock")
    git(repo, "commit", "-qm", "the real project")
    out = tmp_path / "out"
    out.mkdir()

    exported = _MODULE.export_locked(repo, out, git(repo, "rev-parse", "HEAD"))

    lock = tomllib.loads((source / "uv.lock").read_text())
    locked = {(p["name"], p["version"]) for p in lock["package"] if "version" in p}
    requirements = [
        line.rstrip(" \\")
        for line in exported.read_text().splitlines()
        if line and not line.startswith((" ", "#"))
    ]
    assert requirements
    for requirement in requirements:
        name, _, rest = requirement.partition("==")
        version = rest.split(";", 1)[0].strip()
        assert (name.strip(), version) in locked, requirement
    anthropic = next(version for name, version in locked if name == "anthropic")
    assert any(r.startswith(f"anthropic=={anthropic}") for r in requirements)
    assert "--hash=sha256:" in exported.read_text()
    # The project itself is the wheel, never a line of the locked set.
    assert not any(r.startswith("ai-assistant") for r in requirements)


@pytest.mark.skipif(shutil.which("uv") is None, reason="uv is not on PATH")
def test_the_real_export_refuses_a_lockfile_pyproject_has_outgrown(tmp_path: Path) -> None:
    # The wheel's requirements come from pyproject.toml. A lockfile that does not
    # record one of them would export a set the wheel is missing a package from.
    source = Path(__file__).parents[2]
    repo = tmp_path / "clone"
    init_repo(repo)
    pyproject = (source / "pyproject.toml").read_text()
    assert "dependencies = [\n" in pyproject
    outgrown = pyproject.replace("dependencies = [\n", 'dependencies = [\n    "six>=1",\n', 1)
    (repo / "pyproject.toml").write_text(outgrown)
    shutil.copyfile(source / "uv.lock", repo / "uv.lock")
    git(repo, "add", "pyproject.toml", "uv.lock")
    git(repo, "commit", "-qm", "a requirement the lockfile never recorded")
    out = tmp_path / "out"
    out.mkdir()

    # What uv says depends on its cache — "needs to be updated" when it can
    # re-resolve offline, "no solution found" when it cannot — so the assertion
    # is the refusal itself, and that nothing was exported.
    with pytest.raises(_MODULE.DeployError, match="uv failed"):
        _MODULE.export_locked(repo, out, git(repo, "rev-parse", "HEAD"))
    assert not (out / _MODULE.LOCKED_REQUIREMENTS).exists()


def _written_marker(command: str) -> str:
    """The marker body a marker-writing remote command puts in place.

    Unwrapped the way the two shells do it: the ssh argv's remote command is a
    `su -c` whose argument is the inner command line, and in that line the body
    is the word after `printf %s`.
    """
    inner = shlex.split(command)[-1]
    words = shlex.split(inner)
    return words[words.index("%s") + 1]


def test_a_failed_locked_install_leaves_no_marker_vouching_for_the_old_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Commit A is deployed; B moves uv.lock. B's locked set installs and then
    # its wheel install fails. Had the marker still named A, redeploying A would
    # diff A's lockfile against itself, keep the venv, and run A on B's set.
    repo = _repo(tmp_path)
    deployed = _bump_lockfile(repo)
    box_run = _FakeBox.run_local

    def _run_local(self: _FakeBox, argv: list[str], **kwargs: Any) -> str:
        if "pip install" in " ".join(argv):
            self.issued.append(" ".join(argv))
            raise _MODULE.DeployError("ssh failed: the wheel would not install")
        return box_run(self, argv, **kwargs)

    monkeypatch.setattr(_FakeBox, "run_local", _run_local)

    with pytest.raises(_MODULE.DeployError, match="the wheel would not install"):
        _deploy_against(repo, monkeypatch, marker=f"commit={deployed}\n")
    box = _FakeBox.last

    unmark = next(i for i, c in enumerate(box.issued) if "deps=unknown" in c)
    install = next(i for i, c in enumerate(box.issued) if "pip install" in c)
    assert unmark < install
    assert not any("commit=" in c for c in box.issued[install:])
    # What the box is left holding reads as UNKNOWN, so the redeploy of A takes
    # the locked path rather than keeping the venv B half-replaced.
    left = _written_marker(box.issued[unmark])
    assert _MODULE.marker_commit(left) is None
    reason = _MODULE._rule_on_dependencies(
        _plan(repo, "--wheel", "/elsewhere/w.whl", "--wheel-commit", deployed),
        repo,
        deployed,
        left,
        "0.1.0\n",
    )
    assert reason is not None


def test_the_routine_path_does_not_withdraw_the_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Its install touches the wheel alone, so the marker's dependency claim
    # stays true however the install ends.
    repo = _repo(tmp_path)
    head = git(repo, "rev-parse", "HEAD")

    box = _deploy_against(repo, monkeypatch, marker=f"commit={head}\n")

    assert not any("deps=unknown" in c for c in box.issued)


def test_a_dirty_deployed_marker_is_not_proof_of_the_committed_set(tmp_path: Path) -> None:
    # Deploy A with a modified uv.lock under --allow-dirty: the locked path
    # installs the TREE's lockfile and records A-dirty. Restore the tree to A
    # and deploy again: A's committed lockfile diffed against A is empty, and
    # keeping the venv would run A on the dirty set.
    repo = _repo(tmp_path)
    head = git(repo, "rev-parse", "HEAD")

    reason = _MODULE._rule_on_dependencies(
        _plan(repo), repo, head, f"commit={head}-dirty\nwheel_sha256=ff\n", "0.1.0\n"
    )

    assert reason is not None
    assert "was dirty" in reason


@pytest.mark.parametrize(
    ("text", "dirty"),
    [
        ("commit=abc1234-dirty\n", True),
        ("commit=abc1234\n", False),
        ("ece6d22d-dirty\n", True),
        ("ece6d22d\n", False),
        ("", False),
    ],
)
def test_a_dirty_marker_is_recognised_in_both_formats(text: str, dirty: bool) -> None:
    assert _MODULE.marker_is_dirty(text) is dirty


# --------------------------------------------------------------------------- #
# ADR-0326 §5:4: an earlier build is never started over a later one's data     #
# --------------------------------------------------------------------------- #


def _history(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    """A clone with a line of three commits and one that diverged from the first.

    Returns:
        The clone, and each commit by name: ``first``, ``second``, ``third`` in a
        line, and ``side`` branched from ``first``.
    """
    repo = _repo(tmp_path)
    commits = {"first": git(repo, "rev-parse", "HEAD")}
    for name in ("second", "third"):
        (repo / "f.txt").write_text(f"{name}\n")
        git(repo, "commit", "-qam", name)
        commits[name] = git(repo, "rev-parse", "HEAD")
    git(repo, "switch", "-qc", "side", commits["first"])
    (repo / "f.txt").write_text("side\n")
    git(repo, "commit", "-qam", "side")
    commits["side"] = git(repo, "rev-parse", "HEAD")
    git(repo, "switch", "-q", "main")
    return repo, commits


@pytest.mark.parametrize(
    ("installed", "deploying"),
    [("first", "first"), ("first", "second"), ("first", "third"), ("second", "third")],
)
def test_the_installed_commit_or_a_later_one_is_admitted(
    tmp_path: Path, installed: str, deploying: str
) -> None:
    repo, commits = _history(tmp_path)

    assert _MODULE.history_refusal(repo, commits[installed], commits[deploying]) is None


def test_an_abbreviated_installed_commit_is_read_as_the_commit_it_names(tmp_path: Path) -> None:
    # The pre-recipe marker is a bare sha, and may be a short one.
    repo, commits = _history(tmp_path)

    assert _MODULE.history_refusal(repo, commits["first"][:8], commits["second"]) is None


@pytest.mark.parametrize(
    ("installed", "deploying", "said"),
    [
        ("third", "first", "is an earlier build than"),
        ("second", "first", "is an earlier build than"),
        ("second", "side", "has diverged from"),
        ("side", "third", "has diverged from"),
    ],
)
def test_an_earlier_or_diverged_commit_is_refused(
    tmp_path: Path, installed: str, deploying: str, said: str
) -> None:
    repo, commits = _history(tmp_path)

    refusal = _MODULE.history_refusal(repo, commits[installed], commits[deploying])

    assert refusal is not None
    assert said in refusal
    assert commits[deploying][:12] in refusal
    assert commits[installed][:12] in refusal


@pytest.mark.parametrize(
    "installed",
    [
        "0" * 40,  # fetched nowhere here
        "",  # no marker, or one withdrawn mid-install
        "-dirty",
        "main",  # a ref, which a record cannot stand for
    ],
)
def test_an_installed_commit_this_clone_cannot_name_is_unknown_not_earlier(
    tmp_path: Path, installed: str
) -> None:
    repo, commits = _history(tmp_path)

    refusal = _MODULE.history_refusal(repo, installed, commits["third"])

    assert refusal is not None
    assert "is not one this clone holds" in refusal


def test_a_hex_named_branch_does_not_stand_in_for_an_abbreviated_commit(
    tmp_path: Path,
) -> None:
    # rev-parse prefers a ref to an object prefix: a branch named like the marker's
    # short sha, pointing at an earlier commit, must not make that commit "installed".
    repo, commits = _history(tmp_path)
    short = commits["third"][:8]
    git(repo, "branch", short, commits["first"])

    refusal = _MODULE.history_refusal(repo, short, commits["first"])

    assert refusal is not None
    assert "is an earlier build than" in refusal
    assert commits["third"][:12] in refusal


def test_a_recorded_object_that_is_not_a_commit_is_unknown(tmp_path: Path) -> None:
    repo, commits = _history(tmp_path)
    blob = git(repo, "rev-parse", "HEAD:f.txt")

    refusal = _MODULE.history_refusal(repo, blob, commits["third"])

    assert refusal is not None
    assert "is not one this clone holds" in refusal


def test_a_dirty_install_of_the_same_commit_is_unknown(tmp_path: Path) -> None:
    # A dirty deploy installed a tree no commit holds, so even its own commit is
    # not shown to be at least as late as it.
    repo, commits = _history(tmp_path)

    refusal = _MODULE.history_refusal(repo, f"{commits['third']}-dirty", commits["third"])

    assert refusal is not None
    assert "is not one this clone holds" in refusal


def test_a_deploying_commit_this_clone_cannot_name_is_unknown(tmp_path: Path) -> None:
    repo, commits = _history(tmp_path)

    refusal = _MODULE.history_refusal(repo, commits["first"], "f" * 40)

    assert refusal is not None
    assert f"{'f' * 40} is not a commit this clone holds" in refusal


def test_a_dirty_tree_is_unknown_even_over_its_own_commit(tmp_path: Path) -> None:
    # The tree may hold an earlier release's store code: no commit shows what it is.
    repo, commits = _history(tmp_path)

    refusal = _MODULE.history_refusal(repo, commits["third"], f"{commits['third']}-dirty")

    assert refusal is not None
    assert "-dirty is not a commit this clone holds" in refusal


def test_a_dirty_deploy_needs_allow_earlier(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo(tmp_path)
    head = git(repo, "rev-parse", "HEAD")
    (repo / "f.txt").write_text("an uncommitted change\n")

    with pytest.raises(_MODULE.DeployError, match="-dirty is not a commit this clone holds"):
        _deploy_against(repo, monkeypatch, "--allow-dirty", marker=f"commit={head}\n")
    box = _deploy_against(
        repo, monkeypatch, "--allow-dirty", "--allow-earlier", marker=f"commit={head}\n"
    )
    assert len(box.installs()) == 1


def _deploy_over(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, installed: str, *args: str
) -> _FakeBox:
    """Deploy ``first`` over a venv whose marker records ``installed``."""
    repo, commits = _history(tmp_path)
    git(repo, "switch", "-q", "--detach", commits["first"])
    return _deploy_against(repo, monkeypatch, *args, marker=f"commit={commits[installed]}\n")


def test_an_earlier_build_is_refused_before_anything_is_built_or_stopped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(_MODULE.DeployError) as caught:
        _deploy_over(tmp_path, monkeypatch, "third")

    message = str(caught.value)
    assert "is an earlier build than" in message
    assert "ADR-0326 §5:4" in message
    assert "restore the backup" in message
    assert "--allow-earlier" in message
    assert message.endswith("Nothing has been stopped or installed.")
    issued = "\n".join(_FakeBox.last.issued)
    for step in ("uv build", "uv export", "scp", "stop", "BACKUP_PROBE=", "pip install"):
        assert step not in issued, step


def test_allow_earlier_deploys_an_earlier_build_and_says_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    box = _deploy_over(tmp_path, monkeypatch, "third", "--allow-earlier")

    assert len(box.installs()) == 1
    said = capsys.readouterr().err
    assert "history: " in said
    assert "is an earlier build than" in said
    assert "as --allow-earlier says" in said


def test_a_first_deploy_has_no_earlier_build_to_rule_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # An empty venv and no marker: nothing is installed for this to be earlier than.
    box = _deploy_against(_repo(tmp_path), monkeypatch, marker="", version="(not installed)")

    assert len(box.installs()) == 1


def test_the_allow_earlier_help_says_the_operator_must_know_no_schema_change_lies_between() -> None:
    help_text = " ".join(_MODULE._parser().format_help().split())

    assert "--allow-earlier" in help_text
    assert "no schema change between the two, which the operator must know" in help_text


# --------------------------------------------------------------------------- #
# The backup before the install (ADR-0326 §6)                                  #
# --------------------------------------------------------------------------- #
#
# A deploy to a box whose venv holds an earlier build stops the hub, runs that
# build's `ai-assistant-backup` over the directory the hub serves, and installs
# only once the tool says the artifact is written and verified. What can be
# refused is refused before the hub is stopped.

_SOURCE = Path(__file__).parents[2] / "src" / "ai_assistant" / "service"


def _steps(mode: str) -> list[str]:
    """The step labels of one rendered install mode, in order."""
    return [line.split(":", 1)[0].strip() for line in mode.splitlines() if ": " in line[:10]]


@pytest.mark.parametrize("args", [(), ("--with-deps",)])
def test_the_backup_comes_before_any_install_on_every_path(
    tmp_path: Path, args: tuple[str, ...]
) -> None:
    # The routine install, the locked one, and --with-deps alike: the hub is
    # stopped and backed up after the wheel is staged and before the venv or
    # the marker changes.
    plan = _dry_run(_repo(tmp_path), *args)
    modes = plan.split("# otherwise")
    assert len(modes) == (1 if args else 2)

    for mode in modes:
        steps = _steps(mode)
        assert steps.index("backup?") < steps.index("stagedir")
        assert steps.index("verify") < steps.index("stop") < steps.index("backup")
        assert steps.index("backup") < steps.index("install")
        if "unmark" in steps:
            assert steps.index("backup") < steps.index("unmark")


def test_the_backup_is_the_earlier_builds_tool_reading_a_passphrase_file(tmp_path: Path) -> None:
    plan = _dry_run(_repo(tmp_path))

    assert "~/venv/bin/ai-assistant-backup ~/backups/pre-deploy-" in plan, (
        "the venv's own tool, before the install replaces it"
    )
    assert "--passphrase-file ~/.assistant-backup-pass </dev/null 2>&1" in plan
    # Through the env-file loader, so the tool copies the directory the hub serves.
    assert "' ~/hub.env ~/venv/bin/ai-assistant-backup ~/backups/pre-deploy-" in plan
    # Never a passphrase this script mints, shows or reads.
    assert "generate-passphrase" not in plan
    assert "cat ~/.assistant-backup-pass" not in plan


def test_the_backup_names_no_store_and_no_exclusion(tmp_path: Path) -> None:
    # ADR-0326 §6:4: the exclusions are exactly the tool's own. The script passes
    # the tool a destination and a passphrase file, and nothing else.
    words = shlex.split(_inner(_plan(_repo(tmp_path)).back_up()))
    tool = words.index("~/venv/bin/ai-assistant-backup")

    assert words[tool + 2 : tool + 4] == ["--passphrase-file", "~/.assistant-backup-pass"]
    assert words[tool + 4] == "</dev/null"
    assert words[words.index("-c") + 1] == _MODULE._RUN_BACKUP
    for word in ("--exclude", "trace", "diagnostics", ".db"):
        assert not any(word in w for w in words), word


def test_the_help_carries_the_operators_one_time_passphrase_step() -> None:
    result = run("deploy_hub", ["--help"])

    assert result.returncode == 0
    for expected in ("stty -echo", "~/.assistant-backup-pass", "umask 077", "OFF the box"):
        assert expected in result.stdout, expected


def test_the_tools_words_and_lock_name_are_the_ones_the_script_reads() -> None:
    # Exit 0 covers a verified artifact and an unverified one, so the script
    # tells them apart by the tool's own sentence. If that sentence changes,
    # every deploy refuses; this test says why before a deploy does.
    source = (_SOURCE / "backup.py").read_text(encoding="utf-8")

    assert f'"{_MODULE._BACKUP_VERIFIED}"' in source
    assert f'print(f"{_MODULE._BACKUP_DISCLOSES}{{data_dir}}")' in source
    assert _MODULE._BACKUP_UNVERIFIED in source
    assert f'LOCK_FILENAME: Final = "{_MODULE._LOCK_FILENAME}"' in (_SOURCE / "lock.py").read_text(
        encoding="utf-8"
    )


def test_each_run_writes_a_new_artifact_under_the_backup_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The tool refuses a destination that exists, and the deploy deletes none.
    repo = _repo(tmp_path)
    first = re.findall(
        r"~/backups/pre-deploy-\w+-1111aaaa\.age", _rendered(repo, monkeypatch, "1111aaaa")
    )
    second = re.findall(
        r"~/backups/pre-deploy-\w+-2222bbbb\.age", _rendered(repo, monkeypatch, "2222bbbb")
    )

    assert first
    assert second


# --- The preflight: refused while the hub still serves ---------------------- #

_NO_PASSPHRASE_FILE = dict.fromkeys(["passphrase"], "absent")


def test_a_healthy_box_names_the_directory_and_the_artifact(tmp_path: Path) -> None:
    plan = _plan(_repo(tmp_path))

    target = _MODULE.backup_target(plan, (0, f"Welcome\n{_healthy_probe()}", ""))

    assert target.data_dir == _DATA_DIR
    assert target.artifact == plan.backup_artifact
    assert target.artifact.startswith("~/backups/pre-deploy-")


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"env": "absent"}, "environment file ~/hub.env is absent"),
        ({"env": "unreadable"}, "environment file ~/hub.env is unreadable"),
        ({"env": "unsupported", "env_line": 7}, "line 7 of the hub's environment file"),
        ({"data_dir": None, "settings_error": "ValidationError data_dir"}, "ValidationError"),
        ({"tool": False}, "has no ai-assistant-backup"),
        ({"passphrase": "absent"}, "passphrase file ~/.assistant-backup-pass is absent"),
        ({"passphrase": "empty"}, "is empty on the box"),
        ({"passphrase": "unreadable"}, "is unreadable on the box"),
        ({"passphrase": "not-a-file"}, "is not-a-file on the box"),
        ({"passphrase_mode": 0o644}, "has mode 644"),
        ({"passphrase_mode": 0o620}, "has mode 620"),
        ({"passphrase_mode": None}, "has mode unknown"),
        ({"passphrase_path": f"{_DATA_DIR}/pass"}, "is not outside"),
        ({"backup_dir": f"{_DATA_DIR}/backups"}, "is not\noutside the data directory"),
        ({"backup_dir": _DATA_DIR}, "is not\noutside the data directory"),
        ({"lock": "free"}, "the instance lock of /home/assistant/data-m44 is free"),
        ({"lock": "absent"}, "does not name the directory the hub"),
        ({"lock": "unopenable PermissionError"}, "is unopenable PermissionError"),
    ],
)
def test_a_box_that_cannot_take_the_backup_is_refused_before_anything_stops(
    tmp_path: Path, overrides: dict[str, object], message: str
) -> None:
    plan = _plan(_repo(tmp_path))

    with pytest.raises(_MODULE.DeployError, match=re.escape(message)) as refused:
        _MODULE.backup_target(plan, (0, _healthy_probe(**overrides), ""))

    assert "Nothing has been stopped or installed." in str(refused.value)


def test_an_absent_passphrase_file_names_the_operators_step(tmp_path: Path) -> None:
    plan = _plan(_repo(tmp_path))

    with pytest.raises(_MODULE.DeployError) as refused:
        _MODULE.backup_target(plan, (0, _healthy_probe(**_NO_PASSPHRASE_FILE), ""))

    assert "stty -echo" in str(refused.value)
    assert "OFF the box" in str(refused.value)


@pytest.mark.parametrize("suffix", ["-backups", " archive", "  archive/pass"])
def test_a_path_beside_the_data_dirs_name_is_not_inside_it(tmp_path: Path, suffix: str) -> None:
    # A prefix of the string is not containment, and spaces survive the trip.
    plan = _plan(_repo(tmp_path))

    target = _MODULE.backup_target(plan, (0, _healthy_probe(backup_dir=f"{_DATA_DIR}{suffix}"), ""))

    assert target.data_dir == _DATA_DIR


def test_a_data_dir_with_runs_of_spaces_still_contains_its_own_files(tmp_path: Path) -> None:
    plan = _plan(_repo(tmp_path))
    spaced = "/home/assistant/data  archive"

    with pytest.raises(_MODULE.DeployError, match="is not outside"):
        _MODULE.backup_target(
            plan,
            (0, _healthy_probe(data_dir=spaced, passphrase_path=f"{spaced}/pass"), ""),
        )


@pytest.mark.parametrize("out", ["", "Welcome\n", "BACKUP_PROBE=not json\n", "BACKUP_PROBE=[1]\n"])
def test_an_unanswered_preflight_is_not_reported_as_a_box_fact(tmp_path: Path, out: str) -> None:
    with pytest.raises(_MODULE.DeployError, match="could not ask the box about the backup"):
        _MODULE.backup_target(_plan(_repo(tmp_path)), (255, out, "ssh: connect: refused"))


@pytest.mark.parametrize("state", ["inactive", "failed"])
def test_a_stopped_hub_is_backed_up_as_named_and_said_so(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], state: str
) -> None:
    probe = _healthy_probe(HUB_STATE=state, lock="free")

    target = _MODULE.backup_target(_plan(_repo(tmp_path)), (0, probe, ""))

    assert target.data_dir == _DATA_DIR
    assert f"the unit is {state}" in capsys.readouterr().err


@pytest.mark.parametrize("state", ["", "activating", "deactivating", "maintenance", "unknown"])
def test_a_unit_neither_running_nor_stopped_is_refused(tmp_path: Path, state: str) -> None:
    # A failed query prints no state at all, and a unit in transition may be
    # serving another directory; either would otherwise skip the lock check
    # and back up a directory named by the wrong environment.
    probe = _healthy_probe(HUB_STATE=state, lock="free")

    with pytest.raises(_MODULE.DeployError, match="neither\nrunning nor stopped"):
        _MODULE.backup_target(_plan(_repo(tmp_path)), (0, probe, ""))


def test_a_reloading_hub_is_running_and_must_hold_the_lock(tmp_path: Path) -> None:
    plan = _plan(_repo(tmp_path))

    assert _MODULE.backup_target(plan, (0, _healthy_probe(HUB_STATE="reloading"), ""))
    with pytest.raises(_MODULE.DeployError, match="is free"):
        _MODULE.backup_target(plan, (0, _healthy_probe(HUB_STATE="reloading", lock="free"), ""))


def test_a_first_deploy_takes_no_backup(tmp_path: Path) -> None:
    plan = _plan(_repo(tmp_path))

    def _no_ssh(_remote: str) -> list[str]:
        raise AssertionError("a first deploy asks the box nothing about a backup")

    assert _MODULE._rule_on_backup(plan, "", "Welcome\n(not installed)\n", _no_ssh) is None


def test_an_empty_venv_under_a_marker_is_refused(tmp_path: Path) -> None:
    # A hub has served here, and nothing is left that could back it up.
    plan = _plan(_repo(tmp_path))

    with pytest.raises(_MODULE.DeployError, match="holds no build, but the marker shows"):
        _MODULE._rule_on_backup(plan, "commit=abc1234\n", "(not installed)\n", lambda r: [r])


# --- How the box reads the hub's environment file -------------------------- #


def _loader() -> Any:
    """The env-file loader the box runs, executed here as the box would."""
    namespace: dict[str, Any] = {}
    exec(_MODULE._ENV_LOADER, namespace)  # noqa: S102  # the script's own constant
    return namespace


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("ASSISTANT_DATA_DIR=/home/assistant/data-m44\n", "/home/assistant/data-m44"),
        ("  ASSISTANT_DATA_DIR=/srv/x  \n", "/srv/x"),
        ("ASSISTANT_DATA_DIR='/srv/hub data'\n", "/srv/hub data"),
        ('ASSISTANT_DATA_DIR="/srv/hub data"\n', "/srv/hub data"),
        # Single quotes are literal to systemd and to a shell alike.
        ("ASSISTANT_DATA_DIR='/srv/$HOME'\n", "/srv/$HOME"),
        ("ASSISTANT_DATA_DIR=\n", ""),
        ("# a comment\n; another\n\nASSISTANT_DATA_DIR=/srv/y\r\n", "/srv/y"),
        ("ASSISTANT_WEB_SEARCH_ORIGIN=https://api.example\nASSISTANT_DATA_DIR=/a\n", "/a"),
    ],
)
def test_the_loader_reads_what_systemd_and_a_shell_read_alike(
    tmp_path: Path, text: str, expected: str
) -> None:
    env = tmp_path / "hub.env"
    env.write_text(text)

    assert _loader()["load_env"](str(env))["ASSISTANT_DATA_DIR"] == expected


@pytest.mark.parametrize(
    "line",
    [
        # Whitespace, `$`, backslashes and backticks are where systemd and a
        # shell part ways; each is refused rather than read one way or the other.
        "ASSISTANT_DATA_DIR=/srv/hub data",
        "ASSISTANT_DATA_DIR=/srv/$USER",
        'ASSISTANT_DATA_DIR="/srv/${USER}"',
        'ASSISTANT_DATA_DIR="/srv/a\\b"',
        "ASSISTANT_DATA_DIR=/srv/`id`",
        "export ASSISTANT_DATA_DIR=/srv/x",
        "ASSISTANT_DATA_DIR='/srv/x",
        "ASSISTANT_DATA_DIR=/srv/x # note",
    ],
)
def test_the_loader_refuses_by_line_number_never_by_content(tmp_path: Path, line: str) -> None:
    env = tmp_path / "hub.env"
    env.write_text(f"ASSISTANT_KEY=sk-secret\n{line}\n")
    loader = _loader()

    with pytest.raises(loader["Unsupported"]) as refused:
        loader["load_env"](str(env))

    assert refused.value.args == (2,)


# --- The tool's report ------------------------------------------------------ #


@pytest.mark.parametrize(
    ("output", "expected"),
    [
        ("Welcome\nBACKUP_BEGIN_tok\nwrote x\n\nBACKUP_END_tok=0\n", (0, "wrote x")),
        ("BACKUP_BEGIN_tok\nrefused\nBACKUP_END_tok=78\nBACKUP_ARTIFACT=absent\n", (78, "refused")),
        # Cut off: the tool's words so far, and no status.
        ("BACKUP_BEGIN_tok\ncopying 9 file(s)\n", (None, "copying 9 file(s)")),
        ("ssh: connect: refused\n", (None, "")),
        # Another run's brackets are not this run's answer.
        ("BACKUP_BEGIN_other\nok\nBACKUP_END_other=0\n", (None, "")),
    ],
)
def test_only_the_bracketed_output_is_the_tools_report(
    output: str, expected: tuple[int | None, str]
) -> None:
    assert _MODULE.backup_report(output, "tok") == expected


def _backup_out(plan: Any, said: str, status: int = 0, artifact: str = "present") -> str:
    """The backup command's output from a box, as :meth:`Plan.back_up` prints it."""
    token = plan.token
    return (
        f"Welcome\nBACKUP_BEGIN_{token}\n{said}\n\nBACKUP_END_{token}={status}\n"
        f"BACKUP_ARTIFACT={artifact}\n"
    )


def _target(plan: Any) -> Any:
    return _MODULE.BackupTarget(data_dir=_DATA_DIR, artifact=plan.backup_artifact)


def test_a_verified_backup_admits_the_install(tmp_path: Path) -> None:
    plan = _plan(_repo(tmp_path))
    said = f"{_DISCLOSED}\nwrote {plan.backup_artifact} (9 bytes)\n{_MODULE._BACKUP_VERIFIED}"

    _MODULE._check_backup(plan, _target(plan), (0, _backup_out(plan, said), ""))


@pytest.mark.parametrize(
    ("said", "status", "artifact", "message"),
    [
        (
            "wrote x (9 bytes)\nwarning: the artifact is written but unverified: no scratch",
            0,
            "present",
            "is not verified",
        ),
        ("wrote x (9 bytes)", 0, "present", "is not verified"),
        ("the backup was refused: a sidecar", 78, "absent", "failed (exit 78)"),
        ("x is held by another instance", 1, "absent", "failed (exit 1)"),
        (f"{_DISCLOSED}\nwrote x\n{_MODULE._BACKUP_VERIFIED}", 0, "absent", "is absent or empty"),
        # Verified, and of some other directory than the one the preflight checked.
        (
            f"{_MODULE._BACKUP_DISCLOSES}/home/assistant/.ai-assistant\n{_MODULE._BACKUP_VERIFIED}",
            0,
            "present",
            "did not copy /home/assistant/data-m44",
        ),
    ],
)
def test_a_backup_not_written_and_verified_admits_no_install(
    tmp_path: Path, said: str, status: int, artifact: str, message: str
) -> None:
    plan = _plan(_repo(tmp_path))

    with pytest.raises(_MODULE.DeployError, match=re.escape(message)):
        _MODULE._check_backup(
            plan, _target(plan), (0, _backup_out(plan, said, status, artifact), "")
        )


def test_a_backup_that_never_reported_is_not_a_backup(tmp_path: Path) -> None:
    plan = _plan(_repo(tmp_path))

    with pytest.raises(_MODULE.DeployError, match="did not run to its end"):
        _MODULE._check_backup(plan, _target(plan), (255, "", "ssh: connect: refused"))


# --- The whole deploy, against a fake box ----------------------------------- #


def _code_only(repo: Path) -> str:
    """Commit a change that moves code and not uv.lock; return the deployed commit."""
    deployed = git(repo, "rev-parse", "HEAD")
    (repo / "f.txt").write_text("code only\n")
    git(repo, "commit", "-qam", "code only")
    return deployed


def _index(box: _FakeBox, needle: str) -> int:
    return next(i for i, command in enumerate(box.issued) if needle in command)


def test_a_routine_deploy_stops_backs_up_then_installs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _repo(tmp_path)
    deployed = _code_only(repo)

    box = _deploy_against(repo, monkeypatch, marker=f"commit={deployed}\n")

    stop = _index(box, "systemctl --user stop")
    backup = _index(box, "BACKUP_BEGIN_")
    assert _index(box, "BACKUP_PROBE=") < _index(box, "uv build") < stop < backup
    assert backup < _index(box, "pip install") < _index(box, "commit=")
    # The artifact is reported, and nothing deletes it.
    out = capsys.readouterr().out
    assert f"backup: {box.plan.backup_artifact} (of {_DATA_DIR}; verified, and kept)" in out
    assert not any(box.plan.backup_artifact in c and "rm " in c for c in box.issued)


def test_a_locked_deploy_backs_up_before_the_marker_is_withdrawn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo(tmp_path)
    deployed = _bump_lockfile(repo)

    box = _deploy_against(repo, monkeypatch, marker=f"commit={deployed}\n")

    assert _index(box, "BACKUP_BEGIN_") < _index(box, "deps=unknown") < _index(box, "pip install")


@pytest.mark.parametrize(
    ("said", "status"),
    [
        ("the backup was refused: hub.db-wal is a SQLite sidecar", 78),
        (f"wrote x\nwarning: {_MODULE._BACKUP_UNVERIFIED}: no owner-only scratch directory", 0),
    ],
)
def test_a_failed_or_unverified_backup_installs_nothing_and_restarts_the_hub(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, said: str, status: int
) -> None:
    repo = _repo(tmp_path)
    deployed = _code_only(repo)
    box_init = _FakeBox.__init__

    def _init(self: _FakeBox, *args: Any, **kwargs: Any) -> None:
        box_init(self, *args, **kwargs)
        self.backup_said, self.backup_status = said, status

    monkeypatch.setattr(_FakeBox, "__init__", _init)

    with pytest.raises(_MODULE.DeployError) as failed:
        _deploy_against(repo, monkeypatch, marker=f"commit={deployed}\n")
    box = _FakeBox.last

    assert "Nothing was installed." in str(failed.value)
    assert "started again on its earlier build, and logged hub_ready" in str(failed.value)
    assert box.installs() == []
    assert not any("commit=" in c or "deps=unknown" in c for c in box.issued)
    # Started again after the backup, and the staged wheel still cleaned up.
    assert _index(box, "BACKUP_BEGIN_") < _index(box, "systemctl --user restart")
    assert any("rmdir" in c for c in box.issued)


def test_a_hub_that_will_not_come_back_is_reported_beside_the_failed_backup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = _plan(_repo(tmp_path))
    out = _backup_out(plan, "the backup was refused: a sidecar", 78, "absent")
    monkeypatch.setattr(_MODULE, "_run_local", lambda _argv, **_k: "")
    monkeypatch.setattr(_MODULE, "_probe", lambda _argv: (0, out, ""))

    with pytest.raises(_MODULE.DeployError) as failed:
        _MODULE._take_backup(plan, _target(plan), lambda remote: [remote])

    message = str(failed.value)
    assert "failed (exit 78)" in message
    assert "could NOT be started again" in message
    assert "printed no unit InvocationID" in message


def test_a_hub_that_will_not_stop_is_a_failed_backup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = _plan(_repo(tmp_path))
    issued: list[str] = []

    def _run_local(argv: list[str], **_kwargs: object) -> str:
        issued.append(argv[0])
        if "systemctl --user stop" in argv[0]:
            raise _MODULE.DeployError("ssh failed: Job for ai-assistant-hub.service canceled")
        return "INVOCATION_ID=inv\n"

    monkeypatch.setattr(_MODULE, "_run_local", _run_local)
    monkeypatch.setattr(
        _MODULE, "_probe", lambda argv: (0, "UNIT_STATE=active\nhub_ready jobs=[]\n", "")
    )

    with pytest.raises(_MODULE.DeployError, match="canceled\nNothing was installed"):
        _MODULE._take_backup(plan, _target(plan), lambda remote: [remote])

    assert not any("BACKUP_BEGIN_" in command for command in issued)


def test_an_interrupted_backup_starts_the_hub_again_and_installs_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo(tmp_path)
    deployed = _code_only(repo)
    box_probe = _FakeBox.probe

    def _probe(self: _FakeBox, argv: list[str]) -> tuple[int, str, str]:
        if "BACKUP_BEGIN_" in " ".join(argv):
            self.issued.append(" ".join(argv))
            raise KeyboardInterrupt
        return box_probe(self, argv)

    monkeypatch.setattr(_FakeBox, "probe", _probe)

    with pytest.raises(_MODULE.DeployError) as failed:
        _deploy_against(repo, monkeypatch, marker=f"commit={deployed}\n")
    box = _FakeBox.last

    message = str(failed.value)
    assert "interrupted while the hub was stopped for its backup" in message
    assert "started again on its earlier build, and logged hub_ready" in message
    assert box.installs() == []
    assert _index(box, "BACKUP_BEGIN_") < _index(box, "systemctl --user restart")
    assert any("rmdir" in c for c in box.issued)


def test_an_interrupted_install_after_the_backup_says_the_hub_is_stopped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo(tmp_path)
    deployed = _code_only(repo)
    box_run = _FakeBox.run_local

    def _run_local(self: _FakeBox, argv: list[str], **kwargs: Any) -> str:
        if "pip install" in " ".join(argv):
            raise KeyboardInterrupt
        return box_run(self, argv, **kwargs)

    monkeypatch.setattr(_FakeBox, "run_local", _run_local)

    with pytest.raises(_MODULE.DeployError, match="interrupted\nThe hub was stopped"):
        _deploy_against(repo, monkeypatch, marker=f"commit={deployed}\n")


def test_a_refused_preflight_touches_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo(tmp_path)
    deployed = _code_only(repo)
    box_init = _FakeBox.__init__

    def _init(self: _FakeBox, *args: Any, **kwargs: Any) -> None:
        box_init(self, *args, **kwargs)
        self.backup_probe = _healthy_probe(**_NO_PASSPHRASE_FILE)

    monkeypatch.setattr(_FakeBox, "__init__", _init)

    with pytest.raises(_MODULE.DeployError, match="passphrase file"):
        _deploy_against(repo, monkeypatch, marker=f"commit={deployed}\n")
    box = _FakeBox.last

    for step in ("uv build", "mkdir", "scp ", "systemctl --user stop", "BACKUP_BEGIN_"):
        assert not any(step in c for c in box.issued), step


def test_a_failed_install_after_the_backup_leaves_the_hub_stopped_and_says_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The venv may hold part of the new build; starting it could upgrade the
    # directory with nothing verified, so it is left for the operator.
    repo = _repo(tmp_path)
    deployed = _code_only(repo)
    box_run = _FakeBox.run_local

    def _run_local(self: _FakeBox, argv: list[str], **kwargs: Any) -> str:
        if "pip install" in " ".join(argv):
            self.issued.append(" ".join(argv))
            raise _MODULE.DeployError("ssh failed: No space left on device")
        return box_run(self, argv, **kwargs)

    monkeypatch.setattr(_FakeBox, "run_local", _run_local)

    with pytest.raises(_MODULE.DeployError) as failed:
        _deploy_against(repo, monkeypatch, marker=f"commit={deployed}\n")
    box = _FakeBox.last

    message = str(failed.value)
    assert "No space left on device" in message
    assert "is still stopped" in message
    assert box.plan.backup_artifact in message
    assert not any("systemctl --user restart" in c for c in box.issued)


def test_a_first_deploy_neither_stops_nor_backs_up(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    box = _deploy_against(_repo(tmp_path), monkeypatch, marker="", version="(not installed)")

    for step in ("BACKUP_PROBE=", "systemctl --user stop", "BACKUP_BEGIN_"):
        assert not any(step in c for c in box.issued), step
    assert "backup: none — a first deploy" in capsys.readouterr().out


# --- The remote commands, through a real shell ------------------------------ #
#
# The two commands above are shell and Python text, and a fake box only answers
# what they say. These run their inner commands under `sh` (dash, where it is
# installed), with HOME pointing at a scratch home whose venv's python is this
# interpreter — so the probe's `load_settings()` is the package's own — and with
# a fake systemctl and a real lock file a real flock can contend for.


def _inner(command: str) -> str:
    """The command line `su - <user> -c` would hand the service user's shell."""
    words = shlex.split(command)
    assert words[:2] == ["su", "-"], words
    return words[-1]


def _home(tmp_path: Path, *, unit: str = "active") -> tuple[Path, dict[str, str], Path]:
    """A service user's home with a venv, hub.env, a lock and a passphrase file.

    Returns:
        The home, the environment to run in, and the data directory.
    """
    home = tmp_path / "home"
    data = home / "data  m44"
    bin_dir = home / "venv" / "bin"
    shims = tmp_path / "shims"
    for directory in (data, bin_dir, shims):
        directory.mkdir(parents=True)
    python = bin_dir / "python"
    python.write_text(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n')
    (shims / "systemctl").write_text(f"#!/bin/sh\necho {unit}\n[ {unit} = active ]\n")
    for script in (python, shims / "systemctl"):
        script.chmod(0o755)
    (home / "hub.env").write_text(f"# the hub\nASSISTANT_DATA_DIR='{data}'\n")
    passphrase = home / ".assistant-backup-pass"
    passphrase.write_text("correct horse battery staple\n")
    passphrase.chmod(0o600)
    (data / "hub.lock").write_text("4242\n")
    tool = bin_dir / "ai-assistant-backup"
    tool.write_text("#!/bin/sh\n")
    tool.chmod(0o755)
    env = {"HOME": str(home), "PATH": f"{shims}{os.pathsep}{os.environ['PATH']}"}
    return home, env, data


def _sh(command: str, env: dict[str, str]) -> tuple[int, str, str]:
    shell = shutil.which("sh") or "/bin/sh"
    completed = subprocess.run(  # noqa: S603  # fixed shell, test-built command
        [shell, "-c", _inner(command)],
        input="typed at the terminal\n",
        capture_output=True,
        text=True,
        env=env,
        cwd=env["HOME"],
        check=False,
    )
    return completed.returncode, completed.stdout, completed.stderr


def _report(probed: tuple[int, str, str]) -> dict[str, Any]:
    report: dict[str, Any] | None = _MODULE._probe_report(probed[1])
    assert report is not None, probed
    return report


_NEEDS_SHELL = pytest.mark.skipif(shutil.which("sh") is None, reason="needs a POSIX sh")


@_NEEDS_SHELL
def test_the_real_probe_names_the_served_directory_while_the_hub_holds_it(
    tmp_path: Path,
) -> None:
    _home_dir, env, data = _home(tmp_path)
    plan = _plan(_repo(tmp_path))

    with (data / "hub.lock").open("rb") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        target = _MODULE.backup_target(plan, _sh(plan.probe_backup(), env))
    probed = _sh(plan.probe_backup(), env)

    # The package's own settings, under the loaded file: two spaces and all.
    assert target.data_dir == str(data.resolve())
    # And the same directory, once nothing holds its lock, is not the hub's.
    assert _report(probed)["lock"] == "free"
    with pytest.raises(_MODULE.DeployError, match="is free"):
        _MODULE.backup_target(plan, probed)


@_NEEDS_SHELL
def test_the_real_probe_sees_an_absent_or_exposed_passphrase_file(tmp_path: Path) -> None:
    home, env, _data = _home(tmp_path, unit="inactive")
    plan = _plan(_repo(tmp_path))
    passphrase = home / ".assistant-backup-pass"

    passphrase.chmod(0o644)
    assert _report(_sh(plan.probe_backup(), env))["passphrase_mode"] == 0o644
    passphrase.unlink()
    (home / "venv" / "bin" / "ai-assistant-backup").unlink()
    probed = _sh(plan.probe_backup(), env)

    assert _report(probed)["passphrase"] == "absent"  # noqa: S105  # a state, not a secret
    assert _report(probed)["tool"] is False
    assert "HUB_STATE=inactive" in probed[1]
    # The probe examines the file and never reads it.
    passphrase.write_text("correct horse battery staple\n")
    passphrase.chmod(0o600)
    assert "correct horse" not in "".join(_sh(plan.probe_backup(), env)[1:])


@_NEEDS_SHELL
def test_the_real_probe_refuses_an_env_file_systemd_would_read_otherwise(
    tmp_path: Path,
) -> None:
    home, env, _data = _home(tmp_path)
    (home / "hub.env").write_text("ASSISTANT_KEY=sk-secret\nASSISTANT_DATA_DIR=/srv/$USER\n")
    plan = _plan(_repo(tmp_path))

    probed = _sh(plan.probe_backup(), env)

    with pytest.raises(_MODULE.DeployError, match="line 2 of the hub's environment file"):
        _MODULE.backup_target(plan, probed)
    assert "sk-secret" not in "".join(probed[1:])


@_NEEDS_SHELL
def test_a_symlinked_passphrase_file_is_judged_by_what_it_names(tmp_path: Path) -> None:
    # The link's own mode is 777; the file's is what guards the passphrase, and
    # where the link points is what the containment test must see.
    home, env, data = _home(tmp_path, unit="inactive")
    plan = _plan(_repo(tmp_path))
    kept = tmp_path / "keys" / "pass"
    kept.parent.mkdir()
    (home / ".assistant-backup-pass").replace(kept)
    (home / ".assistant-backup-pass").symlink_to(kept)

    report = _report(_sh(plan.probe_backup(), env))
    assert report["passphrase_mode"] == 0o600
    assert report["passphrase_path"] == str(kept.resolve())

    inside = data / "pass"
    kept.replace(inside)
    (home / ".assistant-backup-pass").unlink()
    (home / ".assistant-backup-pass").symlink_to(inside)
    with pytest.raises(_MODULE.DeployError, match="is not outside"):
        _MODULE.backup_target(plan, _sh(plan.probe_backup(), env))


@_NEEDS_SHELL
@pytest.mark.parametrize(
    ("script", "verified"),
    [
        (f'echo "wrote $1"; echo "{_MODULE._BACKUP_VERIFIED}"', True),
        (f'echo "wrote $1"; echo "warning: {_MODULE._BACKUP_UNVERIFIED}: none" >&2', False),
        ('echo "the backup was refused: a sidecar" >&2; exit 78', False),
        # Says verified, and left nothing behind: not a backup either.
        (f'rm -f "$1"; echo "{_MODULE._BACKUP_VERIFIED}"', False),
    ],
)
def test_the_real_backup_command_reports_what_the_tool_said(
    tmp_path: Path, script: str, verified: bool
) -> None:
    home, env, data = _home(tmp_path)
    seen = tmp_path / "seen"
    tool = home / "venv" / "bin" / "ai-assistant-backup"
    # Records its argv, its data directory and what reached its stdin, then
    # writes a non-empty artifact and says what the real tool says.
    tool.write_text(
        "#!/bin/sh\n"
        f'printf "%s\\n" "$@" "$ASSISTANT_DATA_DIR" > "{seen}"\n'
        f'if read -r line; then echo "stdin: $line"; else echo "stdin: none"; fi >> "{seen}"\n'
        f'echo "{_MODULE._BACKUP_DISCLOSES}$ASSISTANT_DATA_DIR"; echo data > "$1"\n{script}\n'
    )
    tool.chmod(0o755)
    plan = _plan(_repo(tmp_path))

    probed = _sh(plan.back_up(), env)

    artifact = home / "backups" / Path(plan.backup_artifact).name
    assert seen.read_text().splitlines()[:4] == [
        str(artifact),
        "--passphrase-file",
        str(home / ".assistant-backup-pass"),
        str(data),
    ]
    # What an operator might have typed never reaches the tool: stdin is /dev/null.
    assert seen.read_text().splitlines()[-1] == "stdin: none"
    assert (home / "backups").stat().st_mode & 0o777 == 0o700
    target = _MODULE.BackupTarget(data_dir=str(data), artifact=plan.backup_artifact)
    if verified:
        _MODULE._check_backup(plan, target, probed)
    else:
        with pytest.raises(_MODULE.DeployError):
            _MODULE._check_backup(plan, target, probed)


@_NEEDS_SHELL
def test_the_real_backup_refuses_an_env_file_it_cannot_read_alike(tmp_path: Path) -> None:
    home, env, _data = _home(tmp_path)
    (home / "hub.env").write_text("ASSISTANT_DATA_DIR=/srv/a b\n")
    plan = _plan(_repo(tmp_path))

    probed = _sh(plan.back_up(), env)

    with pytest.raises(_MODULE.DeployError, match=r"failed \(exit 1\)"):
        _MODULE._check_backup(plan, _target(plan), probed)
    assert "cannot read: 1" in probed[1]


@pytest.mark.parametrize("name", ["_ENV_LOADER", "_PROBE", "_RUN_BACKUP"])
def test_the_box_side_python_carries_no_single_quote(name: str) -> None:
    # Each crosses two shells inside single quotes; a quote in it would print in
    # the dry run as the '"'"' escaping nobody can check by eye.
    assert "'" not in getattr(_MODULE, name)


# --------------------------------------------------------------------------- #
# --delta: only what changed crosses the link, and nothing else changes        #
# --------------------------------------------------------------------------- #


_DELTA_LABELS = ("delta?  :", "seed    :", "keep    :")


def _line_index(plan: str, needle: str) -> int:
    return next(i for i, line in enumerate(plan.splitlines()) if needle in line)


def test_without_delta_the_wheel_goes_whole_by_scp_as_before(tmp_path: Path) -> None:
    plan = _dry_run(_repo(tmp_path))

    assert "rsync" not in plan
    assert not any(line.startswith(_DELTA_LABELS) for line in plan.splitlines())
    assert "stage   : scp <the wheel above> root@hub.example:/tmp/deploy-hub-" in plan
    assert "find " not in plan


def test_the_delta_plan_checks_seeds_sends_the_difference_and_keeps_the_base(
    tmp_path: Path,
) -> None:
    plan = _dry_run(_repo(tmp_path), "--delta")

    for mode in plan.split("# otherwise"):
        order = [
            _line_index(mode, "delta?  :"),
            _line_index(mode, "stagedir:"),
            _line_index(mode, "seed    :"),
            _line_index(mode, "stage   : rsync"),
            _line_index(mode, "verify  :"),
            _line_index(mode, "stop    :"),
            _line_index(mode, "install :"),
            _line_index(mode, "keep    :"),
            _line_index(mode, "unstage :"),
            _line_index(mode, "marker! :"),
        ]
        assert order == sorted(order), order
        assert "scp <the wheel above>" not in mode
    rsync = next(line for line in plan.splitlines() if line.startswith("stage   : rsync"))
    assert "rsync -s --ignore-times --no-whole-file --bwlimit=40 <the wheel above> " in rsync
    # The base is the kept one, seeded into this run's own staging directory, and the
    # installed wheel replaces it through a scratch file renamed into place.
    assert re.search(r"cp -- ~/deploy-hub/base\.whl /tmp/deploy-hub-[0-9a-f]+/w?", plan)
    assert re.search(
        r"mv -fT -- ~/deploy-hub/base\.whl\.[0-9a-f]+\.tmp ~/deploy-hub/base\.whl;", plan
    )
    assert "mkdir -p -m 0700 ~/deploy-hub " in plan
    # The digest check is the same check, as the service user, before the stop.
    assert "su - assistant -c 'echo STAGED_SHA256=$(sha256sum " in plan
    assert "rm -rf" not in plan


def test_the_delta_settings_are_parameters(tmp_path: Path) -> None:
    plan = _dry_run(
        _repo(tmp_path),
        "--delta",
        "--delta-base",
        "/srv/old builds/w.whl",
        "--bwlimit",
        "0",
    )

    assert "--bwlimit=0 <the wheel above>" in plan
    assert re.search(r"cp -- '/srv/old builds/w\.whl' /tmp/deploy-hub-", plan)
    assert "[ ! -s '/srv/old builds/w.whl' ]" in plan
    # The base it names is read; the kept one is still where the next deploy looks.
    assert "mv -fT -- ~/deploy-hub/base.whl." in plan
    assert "[ ! -s ~/deploy-hub/base.whl ]" not in plan


def test_where_the_base_is_kept_is_not_a_parameter(tmp_path: Path) -> None:
    # The keep writes as the login user, root by default; a path an operator could
    # point through directories another user can rename would let that user aim it.
    result = run(
        "deploy_hub",
        ["hub.example", "--delta", "--delta-keep", "/srv/shared/base.whl", "--dry-run"],
    )

    assert result.returncode == 2
    assert _MODULE.DELTA_KEEP == "~/deploy-hub/base.whl"


@pytest.mark.parametrize("flag", [("--bwlimit", "10"), ("--delta-base", "/x")])
def test_a_delta_setting_without_delta_is_refused_not_ignored(
    tmp_path: Path, flag: tuple[str, str]
) -> None:
    result = run("deploy_hub", ["hub.example", *flag, "--repo", str(_repo(tmp_path)), "--dry-run"])

    assert result.returncode == 1
    assert f"{flag[0]} only applies with --delta" in result.stderr


@pytest.mark.parametrize("value", ["-1", "fast", "4.5"])
def test_a_bandwidth_limit_is_a_whole_number_of_kb_per_second(tmp_path: Path, value: str) -> None:
    result = run(
        "deploy_hub",
        ["hub.example", "--delta", "--bwlimit", value, "--repo", str(_repo(tmp_path)), "--dry-run"],
    )

    assert result.returncode == 2
    assert "KB/s" in result.stderr


def test_delta_refuses_a_stage_dir_rsync_would_not_expand(tmp_path: Path) -> None:
    result = run(
        "deploy_hub",
        [
            "hub.example",
            "--delta",
            "--stage-dir",
            "~/stage",
            "--repo",
            str(_repo(tmp_path)),
            "--dry-run",
        ],
    )

    assert result.returncode == 1
    assert "--delta needs an absolute --stage-dir" in result.stderr


def test_the_rsync_destination_is_the_path_itself_not_shell_text(tmp_path: Path) -> None:
    # Under -s no shell on the box reads it, so quoting it would put the quotes in
    # the file name; the seed, which a shell does read, quotes the same path.
    plan = _staged_plan(_repo(tmp_path))
    plan.args.stage_dir, plan.delta = "/srv/stage dir", True

    argv = plan.stage()

    assert argv[:5] == ["rsync", "-s", "--ignore-times", "--no-whole-file", "--bwlimit=40"]
    assert argv[-2] == str(plan.local)
    assert argv[-1] == f"root@hub.example:/srv/stage dir/deploy-hub-{plan.token}/{plan.wheel}"
    assert f"'/srv/stage dir/deploy-hub-{plan.token}/{plan.wheel}'" in plan.seed()


def test_a_delta_dry_run_contacts_nothing(tmp_path: Path) -> None:
    shim = tmp_path / "bin"
    shim.mkdir()
    log = tmp_path / "called.log"
    for name in ("ssh", "scp", "uv", "rsync"):
        stub = shim / name
        stub.write_text(f'#!/bin/sh\necho {name} >> "{log}"\n')
        stub.chmod(0o755)
    env = dict(os.environ, PATH=f"{shim}{os.pathsep}{os.environ['PATH']}")

    result = run(
        "deploy_hub",
        ["hub.example", "--delta", "--repo", str(_repo(tmp_path)), "--dry-run"],
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert not log.exists(), log.read_text()


def _with_rsync(monkeypatch: pytest.MonkeyPatch, *, present: bool) -> None:
    """Answer ``shutil.which("rsync")`` as asked, and every other name truthfully."""
    which = shutil.which

    def _which(name: str, *args: Any, **kwargs: Any) -> str | None:
        if name == "rsync":
            return "/usr/bin/rsync" if present else None
        return which(name, *args, **kwargs)

    monkeypatch.setattr(_MODULE.shutil, "which", _which)


def _delta_box(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *args: str, **answers: Any
) -> _FakeBox:
    """Deploy a code-only change with --delta to a fake box answering ``answers``."""
    repo = _repo(tmp_path)
    deployed = _code_only(repo)
    _with_rsync(monkeypatch, present=True)
    box_init = _FakeBox.__init__

    def _init(self: _FakeBox, *a: Any, **k: Any) -> None:
        box_init(self, *a, **k)
        for name, value in answers.items():
            setattr(self, name, value)

    monkeypatch.setattr(_FakeBox, "__init__", _init)
    return _deploy_against(repo, monkeypatch, "--delta", *args, marker=f"commit={deployed}\n")


def test_a_delta_deploy_sends_the_difference_and_keeps_what_it_installed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    box = _delta_box(tmp_path, monkeypatch)

    wheel = b"the built wheel"
    assert not any(c.startswith("scp ") for c in box.issued), box.issued
    rsync = _index(box, "rsync -s ")
    assert _index(box, "DELTA_BASE=") < _index(box, "uv build") < _index(box, "mkdir -m 0755")
    assert _index(box, "mkdir -m 0755") < _index(box, box.plan.seed()) < rsync
    assert rsync < _index(box, "sha256sum") < _index(box, "systemctl --user stop")
    keep = _index(box, box.plan.keep_base())
    assert _index(box, "pip install") < keep < _index(box, "rmdir") < _index(box, "commit=")
    # What the box holds is the wheel, digested so; and it is what the next one starts from.
    assert box.staged[box.plan.staged] == wheel
    assert box.kept == wheel
    assert "unit ai-assistant-hub is active and logged hub_ready" in capsys.readouterr().out


def test_a_transfer_that_left_the_base_in_place_is_caught_by_the_digest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A base is only ever bandwidth: whatever the transfer leaves at the staged
    # path is held to the local wheel's digest before anything stops.
    with pytest.raises(_MODULE.DeployError, match="not the one that was sent"):
        _delta_box(tmp_path, monkeypatch, rsync_sends=False)
    box = _FakeBox.last

    assert box.installs() == []
    assert not any("systemctl --user stop" in c for c in box.issued)
    assert box.kept is None
    assert any("rmdir" in c for c in box.issued)


@pytest.mark.parametrize(
    ("answers", "message"),
    [
        ("DELTA_RSYNC=\nDELTA_BASE=usable\nDELTA_KEEP=writable\n", "has no\nrsync on its PATH"),
        ("DELTA_RSYNC=/usr/bin/rsync\nDELTA_BASE=absent\nDELTA_KEEP=writable\n", "is absent"),
        ("DELTA_RSYNC=/usr/bin/rsync\nDELTA_BASE=empty\nDELTA_KEEP=writable\n", "is empty"),
        ("DELTA_RSYNC=/usr/bin/rsync\nDELTA_BASE=not-a-file\nDELTA_KEEP=writable\n", "not-a-file"),
        ("DELTA_RSYNC=/usr/bin/rsync\nDELTA_BASE=unreadable\nDELTA_KEEP=writable\n", "unreadable"),
        ("DELTA_RSYNC=/usr/bin/rsync\nDELTA_BASE=usable\nDELTA_KEEP=unwritable\n", "cannot write"),
        ("DELTA_RSYNC=/usr/bin/rsync\nDELTA_BASE=usable\nDELTA_KEEP=not-a-file\n", "is not a file"),
        (
            "DELTA_RSYNC=/usr/bin/rsync\nDELTA_BASE=usable\nDELTA_KEEP=shared\n",
            "is not root's alone",
        ),
        ("DELTA_RSYNC=/usr/bin/rsync\nDELTA_BASE=usable\nDELTA_KEEP=linked\n", "symbolic link"),
        ("", "could not ask the box what --delta needs"),
    ],
)
def test_a_delta_the_box_cannot_take_is_refused_before_anything_is_sent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, answers: str, message: str
) -> None:
    with pytest.raises(_MODULE.DeployError, match=message) as refused:
        _delta_box(tmp_path, monkeypatch, delta_probe=answers)
    box = _FakeBox.last

    # Never answered by sending the whole wheel instead: that is the operator's
    # call, which a refusal the box answered names.
    if answers:
        assert "Deploy without --delta to send the whole wheel with scp." in str(refused.value)
    assert _MODULE._UNTOUCHED in str(refused.value)
    for step in ("uv build", "mkdir -m 0755", "scp ", "rsync -s", "systemctl --user stop"):
        assert not any(step in c for c in box.issued), step


def test_an_absent_base_names_the_way_to_give_a_first_delta_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    answers = "DELTA_RSYNC=/usr/bin/rsync\nDELTA_BASE=absent\nDELTA_KEEP=writable\n"

    with pytest.raises(_MODULE.DeployError, match="--delta-base") as refused:
        _delta_box(tmp_path, monkeypatch, "--delta-base", "/srv/old.whl", delta_probe=answers)

    assert "/srv/old.whl, is absent" in str(refused.value)
    assert "/srv/old.whl" in _index_text(_FakeBox.last, "DELTA_BASE=")


def _index_text(box: _FakeBox, needle: str) -> str:
    return box.issued[_index(box, needle)]


def test_no_local_rsync_is_refused_before_the_box_is_asked_anything(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo(tmp_path)
    deployed = _code_only(repo)
    _with_rsync(monkeypatch, present=False)

    with pytest.raises(_MODULE.DeployError, match="no rsync on this machine's\nPATH"):
        _deploy_against(repo, monkeypatch, "--delta", marker=f"commit={deployed}\n")

    assert _FakeBox.last.issued == []


def test_a_base_that_could_not_be_kept_warns_and_the_deploy_stands(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    box = _delta_box(tmp_path, monkeypatch, keep_status=1)

    captured = capsys.readouterr()
    assert "could not keep the installed wheel at ~/deploy-hub/base.whl" in captured.err
    assert "No space left on device" in captured.err
    assert "logged hub_ready" in captured.out
    assert any("commit=" in c for c in box.issued)


# --- The delta's commands, through a real shell and a real rsync ------------ #


def _sh_login(command: str, env: dict[str, str]) -> tuple[int, str, str]:
    """Run a command as the login user's shell would: no ``su``, in its home."""
    shell = shutil.which("sh") or "/bin/sh"
    completed = subprocess.run(  # noqa: S603  # fixed shell, test-built command
        [shell, "-c", command],
        capture_output=True,
        text=True,
        env=env,
        cwd=env["HOME"],
        check=False,
    )
    return completed.returncode, completed.stdout, completed.stderr


def _login_home(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    home = tmp_path / "root"
    home.mkdir()
    # Explicit, so a shell whose umask leaves group write does not make it shared.
    home.chmod(0o755)
    return home, {"HOME": str(home), "PATH": os.environ["PATH"]}


def _delta_plan(tmp_path: Path, *args: str) -> Any:
    stage = tmp_path / "stage dir"
    stage.mkdir()
    return _plan(_repo(tmp_path), "--delta", "--stage-dir", str(stage), *args)


@_NEEDS_SHELL
def test_the_real_delta_check_reads_the_base_and_makes_the_keep_directory(tmp_path: Path) -> None:
    home, env = _login_home(tmp_path)
    plan = _delta_plan(tmp_path)

    first = _sh_login(plan.probe_delta(), env)
    (home / "deploy-hub" / "base.whl").write_bytes(b"")
    empty = _sh_login(plan.probe_delta(), env)
    (home / "deploy-hub" / "base.whl").write_bytes(b"an earlier wheel")
    usable = _sh_login(plan.probe_delta(), env)

    assert _MODULE._labelled(first[1], "DELTA_BASE=") == "absent"
    assert _MODULE._labelled(empty[1], "DELTA_BASE=") == "empty"
    assert _MODULE._labelled(usable[1], "DELTA_BASE=") == "usable"
    assert _MODULE._labelled(usable[1], "DELTA_KEEP=") == "writable"
    assert (home / "deploy-hub").stat().st_mode & 0o777 == 0o700
    assert _MODULE._labelled(usable[1], "DELTA_RSYNC=") == (shutil.which("rsync") or "")


@_NEEDS_SHELL
def test_the_real_seed_keep_and_unstage_leave_one_base_and_no_stage(tmp_path: Path) -> None:
    home, env = _login_home(tmp_path)
    plan = _delta_plan(tmp_path)
    (home / "deploy-hub").mkdir()
    (home / "deploy-hub" / "base.whl").write_bytes(b"an earlier wheel")
    stage = Path(plan.stage_dir)

    assert _sh_login(plan.make_stage_dir(), env)[0] == 0
    assert _sh_login(plan.seed(), env)[0] == 0
    assert (stage / plan.wheel).read_bytes() == b"an earlier wheel"
    # Whatever the base held is the login user's alone until the wheel replaces it.
    assert (stage / plan.wheel).stat().st_mode & 0o777 == 0o600
    (stage / plan.wheel).write_bytes(b"the new wheel")
    # What an rsync cut short leaves beside the wheel.
    (stage / f".{plan.wheel}.Ab12Cd").write_bytes(b"half")
    assert _sh_login(plan.keep_base(), env)[0] == 0
    assert _sh_login(plan.unstage(), env)[0] == 0

    assert (home / "deploy-hub" / "base.whl").read_bytes() == b"the new wheel"
    assert sorted(p.name for p in (home / "deploy-hub").iterdir()) == ["base.whl"]
    assert not stage.exists()


@_NEEDS_SHELL
@pytest.mark.skipif(shutil.which("rsync") is None, reason="rsync is not on PATH")
def test_the_real_rsync_replaces_a_base_that_matches_in_size_and_time(tmp_path: Path) -> None:
    # The quick check would leave such a base in place and call it sent. A remote
    # shell that runs the far side here stands in for ssh.
    rsh = tmp_path / "rsh"
    rsh.write_text('#!/bin/sh\nif [ "$1" = "-l" ]; then shift 2; fi\nshift\nexec "$@"\n')
    rsh.chmod(0o755)
    plan = _delta_plan(tmp_path)
    Path(plan.stage_dir).mkdir()
    local = tmp_path / plan.wheel
    local.write_bytes(b"the new wheel, one byte different: 1")
    seeded = Path(plan.staged)
    seeded.write_bytes(b"the new wheel, one byte different: 0")
    stamp = local.stat().st_mtime_ns
    os.utime(seeded, ns=(stamp, stamp))
    plan.use(local)

    completed = subprocess.run(  # noqa: S603  # the argv under test, a local stand-in for ssh
        plan.stage(), env=dict(os.environ, RSYNC_RSH=str(rsh)), capture_output=True, check=False
    )

    assert completed.returncode == 0, completed.stderr
    assert seeded.read_bytes() == local.read_bytes()


@_NEEDS_SHELL
@pytest.mark.parametrize("shape", ["directory", "link to a directory"])
def test_the_real_delta_check_refuses_a_keep_path_that_is_not_a_file(
    tmp_path: Path, shape: str
) -> None:
    # A rename onto a directory moves the wheel inside it and succeeds, so every
    # later deploy would find no base there and the explicit bases would pile up.
    home, env = _login_home(tmp_path)
    cache = tmp_path / "cache"
    cache.mkdir()
    (home / "deploy-hub").mkdir(mode=0o700)
    keep = home / "deploy-hub" / "base.whl"
    if shape == "directory":
        keep.mkdir()
    else:
        keep.symlink_to(cache)
    plan = _delta_plan(tmp_path)

    probed = _sh_login(plan.probe_delta(), env)

    assert _MODULE._labelled(probed[1], "DELTA_KEEP=") == "not-a-file"


@_NEEDS_SHELL
def test_the_real_keep_will_not_rename_into_a_directory_that_appeared(tmp_path: Path) -> None:
    home, env = _login_home(tmp_path)
    kept = home / "deploy-hub"
    kept.mkdir(mode=0o700)
    plan = _delta_plan(tmp_path)
    Path(plan.stage_dir).mkdir()
    Path(plan.staged).write_bytes(b"the new wheel")
    (kept / "base.whl").mkdir()

    status, _out, _err = _sh_login(plan.keep_base(), env)

    assert status != 0
    assert list((kept / "base.whl").iterdir()) == []
    assert sorted(p.name for p in kept.iterdir()) == ["base.whl"]


@_NEEDS_SHELL
@pytest.mark.parametrize(
    ("mode", "state"), [(0o777, "shared"), (0o775, "shared"), (0o755, "writable")]
)
def test_the_real_delta_check_keeps_only_in_a_directory_no_one_else_can_write(
    tmp_path: Path, mode: int, state: str
) -> None:
    # Anyone who can create names there could put a link at the scratch path the
    # keep step copies onto, as root, before it does. The probe makes it 0700; one
    # an operator made or loosened is judged as it stands.
    home, env = _login_home(tmp_path)
    (home / "deploy-hub").mkdir()
    (home / "deploy-hub").chmod(mode)
    plan = _delta_plan(tmp_path)

    probed = _sh_login(plan.probe_delta(), env)

    assert _MODULE._labelled(probed[1], "DELTA_KEEP=") == state


@_NEEDS_SHELL
@pytest.mark.parametrize("target_mode", [0o700, 0o777])
def test_a_keep_directory_that_is_a_link_is_refused_wherever_it_leads(
    tmp_path: Path, target_mode: int
) -> None:
    # Even to a private directory: its parent may be one another user can rename,
    # and swapping the directory under the write is the attack the check prevents.
    home, env = _login_home(tmp_path)
    shared = tmp_path / "shared"
    shared.mkdir()
    shared.chmod(0o777)
    private = shared / "private"
    private.mkdir()
    private.chmod(target_mode)
    (home / "deploy-hub").symlink_to(private)
    plan = _delta_plan(tmp_path)

    probed = _sh_login(plan.probe_delta(), env)

    assert _MODULE._labelled(probed[1], "DELTA_KEEP=") == "linked"
    # And a dangling one, which mkdir -p cannot replace, is a link all the same.
    private.rename(shared / "elsewhere")
    assert _MODULE._labelled(_sh_login(plan.probe_delta(), env)[1], "DELTA_KEEP=") == "linked"


# --------------------------------------------------------------------------- #
# The deploy lock (#3262): one deploy at a time, and the nightly backup off it #
# --------------------------------------------------------------------------- #


def _locked_box(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, **answers: Any
) -> tuple[Path, str, list[_FakeBox]]:
    """A code-only change, and a fake box answering ``answers``, for a deploy to run."""
    repo = _repo(tmp_path)
    deployed = _code_only(repo)
    box_init = _FakeBox.__init__
    boxes: list[_FakeBox] = []

    def _init(self: _FakeBox, *a: Any, **k: Any) -> None:
        box_init(self, *a, **k)
        boxes.append(self)
        for name, value in answers.items():
            setattr(self, name, value)

    monkeypatch.setattr(_FakeBox, "__init__", _init)
    return repo, f"commit={deployed}\n", boxes


def test_every_box_command_runs_under_the_lock_from_the_first_to_the_last(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo(tmp_path)
    deployed = _code_only(repo)

    box = _deploy_against(repo, monkeypatch, marker=f"commit={deployed}\n")

    # _deploy_against holds every deploy to it; this one is a routine deploy with
    # a backup, so the stop, the backup, the install and the restart are among them.
    for step in ("MARKER_BEGIN_", "systemctl --user stop", "pip install", "restart", "journalctl"):
        assert any(step in command for command in box.issued), step
    assert box.issued[0] == "hold the deploy lock"


@pytest.mark.parametrize(
    ("refused", "said"),
    [
        (
            (75, "", ""),
            r"another deploy, or the box's nightly backup, holds ~assistant/\.deploy-lock",
        ),
        ((78, "", ""), r"~assistant/\.deploy-lock is a directory"),
        ((255, "", "ssh: connect to host hub.example: refused"), r"\(exit 255\):\nssh: connect"),
    ],
)
def test_a_lock_that_cannot_be_had_refuses_before_the_box_is_asked_anything(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, refused: tuple[int, str, str], said: str
) -> None:
    repo, marker, boxes = _locked_box(tmp_path, monkeypatch, hold_refused=refused)

    with pytest.raises(_MODULE.DeployError, match=said) as failed:
        _deploy_against(repo, monkeypatch, marker=marker)

    assert str(failed.value).endswith(_MODULE._UNTOUCHED)
    assert boxes[0].issued == ["hold the deploy lock"]


def test_a_held_lock_says_how_to_find_its_holder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, marker, _boxes = _locked_box(tmp_path, monkeypatch, hold_refused=(75, "", ""))

    with pytest.raises(_MODULE.DeployError, match=r"fuser -v ~assistant/\.deploy-lock"):
        _deploy_against(repo, monkeypatch, marker=marker)


def test_a_lock_lost_after_the_backup_installs_nothing_and_starts_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, marker, boxes = _locked_box(tmp_path, monkeypatch, lose_lock_after="BACKUP_BEGIN_")

    with pytest.raises(_MODULE.LockLost, match="does not start the hub again"):
        _deploy_against(repo, monkeypatch, marker=marker)

    box = boxes[0]
    after = box.issued[_index(box, "BACKUP_BEGIN_") + 1 :]
    assert after == [], after
    assert box.released == 1
    # The staging directory is this run's alone, and a killed run leaves it too.
    assert box.plan.stage_dir in capsys.readouterr().err


def test_a_lock_lost_while_the_hub_is_stopped_does_not_start_it_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A failed backup starts the hub again on its earlier build; a lost lock does
    # not, since whoever holds the lock now may be at work on the hub.
    repo, marker, boxes = _locked_box(
        tmp_path, monkeypatch, lose_lock_after="systemctl --user stop"
    )

    with pytest.raises(_MODULE.LockLost):
        _deploy_against(repo, monkeypatch, marker=marker)

    box = boxes[0]
    assert box.issued[-1].endswith("systemctl --user stop ai-assistant-hub'"), box.issued
    assert not any("restart" in command for command in box.issued)


def test_a_lock_lost_before_the_copy_sends_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, marker, boxes = _locked_box(tmp_path, monkeypatch, lose_lock_after="mkdir -m 0755")

    with pytest.raises(_MODULE.LockLost, match="the link to the\nbox dropped"):
        _deploy_against(repo, monkeypatch, marker=marker)

    assert not any(command.startswith("scp ") for command in boxes[0].issued)


def test_a_command_the_box_fences_out_stops_the_deploy(tmp_path: Path) -> None:
    fenced = f"echo '{_MODULE._FENCED_SAID}: another deploy holds the lock' >&2; exit 77"

    with pytest.raises(_MODULE.LockLost, match="the box refused this deploy's command"):
        _MODULE._run_local(["sh", "-c", fenced])
    with pytest.raises(_MODULE.LockLost):
        _MODULE._probe(["sh", "-c", fenced])
    # The status alone is a command's own failure, and stays one.
    with pytest.raises(_MODULE.DeployError, match="sh failed"):
        _MODULE._run_local(["sh", "-c", "echo no >&2; exit 77"])
    assert _MODULE._probe(["sh", "-c", "exit 77"])[0] == 77


def test_a_lost_lock_is_reported_and_fails_the_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def _lost(*_args: object) -> None:
        raise _MODULE._lost("the link to the box dropped.")

    monkeypatch.setattr(_MODULE, "_deploy", _lost)

    assert _MODULE.main(["hub.example", "--repo", str(_repo(tmp_path))]) == 1
    assert "deploy-hub: the link to the box dropped." in capsys.readouterr().err


def test_the_dry_run_shows_the_lock_before_any_box_command(tmp_path: Path) -> None:
    plan = _dry_run(_repo(tmp_path), "hub")

    lines = plan.splitlines()
    lock = _line_index(plan, "lock    : ssh -o BatchMode=yes")
    assert lock < _line_index(plan, "marker  : ssh root@hub.example")
    assert "su - hub -c 'if [ -d ~/.deploy-lock ]" in lines[lock + 1]
    assert "flock -- /run/deploy-hub-hub.owner sh -c" in plan
    assert "held on ~hub/.deploy-lock" in plan


@pytest.mark.parametrize("user", ["../etc", "-c", ".hidden", "a b", "a/b", ""])
def test_a_service_user_that_cannot_name_a_file_is_refused(tmp_path: Path, user: str) -> None:
    repo = str(_repo(tmp_path))
    result = run("deploy_hub", ["--repo", repo, "--dry-run", "--", "hub.example", user])

    assert result.returncode == 1
    assert "is not a service user's name" in result.stderr
