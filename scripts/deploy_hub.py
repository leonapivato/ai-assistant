#!/usr/bin/env python3
"""Deploy the hub wheel to a remote box, restart its unit, and verify the result.

The hub on rented hardware is a temporary exception (issue #879), but the
*procedure* is the project's, and two of the three redeploys on 2026-08-22 failed
on details that lived only in an operator's memory (issue #1389):

* the service venv is uv-managed and has **no ``pip``**, so the install is
  ``uv pip install --python <venv>/bin/python --no-deps --force-reinstall``;
* ``sudo -u <user>`` leaks root's ``HOME``, so uv reads ``/root/uv.toml`` and
  behaves as it does for root. The install therefore runs under a **login
  shell** — ``su - <user> -c ...`` — which is also what gives the ``--user``
  systemd calls below a correct ``XDG_RUNTIME_DIR``.

Nothing here is hard-coded to one box: host, login user, service user, unit
name, venv path, uv path, wheel name and marker path are all parameters. The
defaults describe the box that exists, not a requirement.

**Drift.** ``--no-deps`` installs the wheel and nothing else, so it is correct
only while the deployed dependency set already satisfies the new code. That is
knowable rather than remembered: the deploy records the commit it installed in a
marker file on the box, and the next deploy diffs ``uv.lock`` across that commit.
A changed lockfile refuses ``--no-deps`` and says what to do instead. An absent
or unreadable marker is *unknown*, not *clean* — it warns and proceeds, because
refusing would make the first deploy to a fresh box impossible and the warning is
in front of the operator either way.

**Verification is the point, not a postscript.** A restart that silently fails
leaves the old code running and the box reachable, which is the failure this
recipe exists to make loud. So the run ends by asserting the unit is active,
waiting a bounded time for ``hub_ready`` in that unit's journal *since the
restart*, and printing the installed version and marker before and after.

``--dry-run`` prints the exact commands the run would issue and contacts nothing.
It is what the tests drive, because the remote half cannot be exercised from a
gate that has no box to talk to.
"""

from __future__ import annotations

import argparse
import hashlib
import shlex
import shutil
import subprocess
import sys
import time
import tomllib
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

#: Default service user on the box, and the login user ssh authenticates as.
DEFAULT_SERVICE_USER = "assistant"
DEFAULT_SSH_USER = "root"
#: Default systemd --user unit, venv, uv binary and marker, all relative to the
#: service user's home so the login shell resolves them.
DEFAULT_UNIT = "ai-assistant-hub"
DEFAULT_VENV = "~/venv"
DEFAULT_UV = "~/.local/bin/uv"
DEFAULT_MARKER = "~/DEPLOYED_COMMIT"
#: Where the wheel is staged on the box before the service user installs it.
DEFAULT_STAGE_DIR = "/tmp"  # noqa: S108  # world-readable by design: root writes, the service user reads
#: Seconds to wait for ``hub_ready`` after the restart before calling it a failure.
DEFAULT_READY_TIMEOUT = 60
#: Seconds between journal polls while waiting for it.
_POLL_INTERVAL = 2.0
#: The marker's first field, so a reader (human or the next deploy) can parse it.
_MARKER_COMMIT_PREFIX = "commit="


class DeployError(Exception):
    """A deploy could not proceed, or could not be verified."""


# --------------------------------------------------------------------------- #
# Local side: the repository, the wheel, the drift question                    #
# --------------------------------------------------------------------------- #


def _binary(name: str) -> str:
    """Return an executable's absolute path.

    Args:
        name: The executable to resolve.

    Returns:
        The resolved absolute path.

    Raises:
        DeployError: If it is not on PATH.
    """
    found = shutil.which(name)
    if found is None:
        raise DeployError(f"{name} not found on PATH")
    return found


def _git(*args: str, repo: Path) -> str:
    """Run git in ``repo`` and return its stdout, stripped.

    Args:
        *args: The git arguments.
        repo: The repository to run in.

    Returns:
        Standard output with surrounding whitespace removed.

    Raises:
        DeployError: If git exits non-zero.
    """
    completed = subprocess.run(  # noqa: S603  # fixed argv, no shell, resolved binary
        [_binary("git"), *args],
        cwd=str(repo),
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise DeployError(f"git {' '.join(args)} failed: {completed.stderr.strip()}")
    return completed.stdout.strip()


def wheel_name(repo: Path) -> str:
    """Return the wheel filename ``uv build --wheel`` produces for this project.

    Derived from ``pyproject.toml`` rather than from a listing of ``dist/``, so a
    ``--dry-run`` can name the file without building it and a stale wheel left in
    ``dist/`` by an earlier version cannot be picked up by accident.

    Args:
        repo: The repository root.

    Returns:
        The wheel filename, e.g. ``ai_assistant-0.1.0-py3-none-any.whl``.

    Raises:
        DeployError: If ``pyproject.toml`` is missing, unreadable, or carries no
            ``[project]`` name and version.
    """
    path = repo / "pyproject.toml"
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise DeployError(f"cannot read {path}: {exc}") from exc
    project = data.get("project", {})
    name = project.get("name")
    version = project.get("version")
    if not isinstance(name, str) or not isinstance(version, str):
        raise DeployError(f"{path} has no [project] name and version to build a wheel name from")
    # PEP 427/491 normalisation: the distribution name's runs of `-`, `_` and `.`
    # become a single `_`. Spelled out rather than imported so this stays stdlib.
    normalised = name.replace("-", "_").replace(".", "_")
    while "__" in normalised:
        normalised = normalised.replace("__", "_")
    return f"{normalised}-{version}-py3-none-any.whl"


def head_commit(repo: Path, *, allow_dirty: bool) -> str:
    """Return the commit the wheel will be built from.

    Args:
        repo: The repository root.
        allow_dirty: Whether to proceed when the tree has uncommitted changes.

    Returns:
        The 40-character commit sha, suffixed ``-dirty`` when the tree is dirty
        and ``allow_dirty`` permitted it.

    Raises:
        DeployError: If the tree is dirty and ``allow_dirty`` is false.
    """
    sha = _git("rev-parse", "HEAD", repo=repo)
    status = _git("status", "--porcelain", repo=repo)
    if not status:
        return sha
    if not allow_dirty:
        raise DeployError(
            "the working tree has uncommitted changes, so the marker this deploy\n"
            "would write names a commit that is not what the wheel contains.\n"
            "Commit or stash first, or pass --allow-dirty to record it as dirty."
        )
    return f"{sha}-dirty"


def lockfile_drift(repo: Path, deployed: str) -> str | None:
    """Report whether ``uv.lock`` changed between the deployed commit and ``HEAD``.

    Args:
        repo: The repository root.
        deployed: The commit recorded by the previous deploy.

    Returns:
        The ``git diff --stat`` text when the lockfile moved; ``None`` when it did
        not; and ``None`` is never returned for an unknown commit — that case
        raises, so "unknown" cannot be read as "clean".

    Raises:
        DeployError: If ``deployed`` is not a commit this clone holds.
    """
    probe = subprocess.run(  # noqa: S603  # fixed argv, no shell, resolved binary
        [_binary("git"), "cat-file", "-e", f"{deployed}^{{commit}}"],
        cwd=str(repo),
        capture_output=True,
        check=False,
    )
    if probe.returncode != 0:
        raise DeployError(f"the deployed commit {deployed[:12]} is not in this clone's history")
    diff = _git("diff", "--stat", deployed, "HEAD", "--", "uv.lock", repo=repo)
    return diff or None


def marker_commit(marker_text: str) -> str | None:
    """Extract the commit from a marker file's contents.

    Args:
        marker_text: The marker file as read from the box.

    Returns:
        The recorded commit, or ``None`` when no ``commit=`` line is present.
        A ``-dirty`` suffix is stripped, because the dependency question is about
        the committed lockfile and a dirty deploy still answers it.
    """
    for line in marker_text.splitlines():
        stripped = line.strip()
        if stripped.startswith(_MARKER_COMMIT_PREFIX):
            value = stripped.removeprefix(_MARKER_COMMIT_PREFIX).strip()
            return value.removesuffix("-dirty") or None
    return None


# --------------------------------------------------------------------------- #
# Remote side: how a command reaches the service user                          #
# --------------------------------------------------------------------------- #


def as_service_user(command: str, user: str) -> str:
    """Wrap a command so it runs in the service user's **login** shell.

    ``su -`` rather than ``sudo -u`` is the whole point: ``sudo -u`` keeps the
    caller's ``HOME``, so uv reads root's ``uv.toml`` and the ``--user`` systemd
    calls address root's session bus (issue #1389).

    Args:
        command: The command line to run as that user.
        user: The service user.

    Returns:
        A single command line for the remote login shell.
    """
    return f"su - {shlex.quote(user)} -c {shlex.quote(command)}"


def with_user_bus(command: str) -> str:
    """Give a ``systemctl --user``/``journalctl --user`` call its runtime dir.

    ``XDG_RUNTIME_DIR`` is set *inside* the target shell, not before ``su``: a
    login shell resets the environment, so an assignment on the outer command
    never reaches the inner one. The uid is resolved on the box by ``id -u``,
    which is why this must stay inside single quotes all the way down.

    Args:
        command: The systemd command line.

    Returns:
        The command with its runtime directory assigned.
    """
    return f"XDG_RUNTIME_DIR=/run/user/$(id -u) {command}"


def ssh_command(host: str, ssh_user: str, remote: str) -> list[str]:
    """Return the local argv that runs ``remote`` on the box.

    Args:
        host: The box's hostname or address.
        ssh_user: The login user ssh authenticates as.
        remote: The command line for the remote shell.

    Returns:
        The argv, with the remote command as a single argument.
    """
    return ["ssh", f"{ssh_user}@{host}", remote]


def scp_command(host: str, ssh_user: str, local: Path, remote_path: str) -> list[str]:
    """Return the local argv that copies the wheel to the box.

    Args:
        host: The box's hostname or address.
        ssh_user: The login user ssh authenticates as.
        local: The local wheel.
        remote_path: The destination path on the box.

    Returns:
        The argv.
    """
    return ["scp", str(local), f"{ssh_user}@{host}:{remote_path}"]


# --------------------------------------------------------------------------- #
# The plan                                                                     #
# --------------------------------------------------------------------------- #


class Plan:
    """The remote command lines one deploy issues, in order.

    Built once from the parsed arguments so ``--dry-run`` prints exactly what a
    real run executes — the two cannot drift, because there is one construction.
    """

    def __init__(self, args: argparse.Namespace, wheel: str) -> None:
        """Build the plan.

        Args:
            args: The parsed arguments.
            wheel: The wheel filename.
        """
        self.args = args
        self.wheel = wheel
        self.staged = f"{args.stage_dir.rstrip('/')}/{wheel}"

    def read_marker(self) -> str:
        """Return the command that reads the deployed-commit marker.

        Returns:
            The remote command line. It tolerates an absent marker.
        """
        return as_service_user(f"cat {self.args.marker} 2>/dev/null || true", self.args.user)

    def read_version(self) -> str:
        """Return the command that prints the installed package version.

        Returns:
            The remote command line.
        """
        python = f"{self.args.venv.rstrip('/')}/bin/python"
        expr = "import ai_assistant; print(ai_assistant.__version__)"
        inner = f"{python} -c {shlex.quote(expr)} 2>/dev/null || echo '(not installed)'"
        return as_service_user(inner, self.args.user)

    def stage(self) -> list[str]:
        """Return the argv that copies the wheel to the box.

        Returns:
            The local argv.
        """
        return scp_command(
            self.args.host, self.args.ssh_user, Path(self.args.wheel_path), self.staged
        )

    def make_readable(self) -> str:
        """Return the command that makes the staged wheel readable by the service user.

        Returns:
            The remote command line. Explicit rather than relying on the login
            umask, because an unreadable wheel fails inside ``su`` with a message
            about the file rather than about the permission.
        """
        return f"chmod 0644 {shlex.quote(self.staged)}"

    def install(self) -> str:
        """Return the install command, run in the service user's login shell.

        Returns:
            The remote command line.
        """
        python = f"{self.args.venv.rstrip('/')}/bin/python"
        deps = "" if self.args.with_deps else "--no-deps "
        inner = (
            f"{self.args.uv} pip install --python {python} "
            f"{deps}--force-reinstall {shlex.quote(self.staged)}"
        )
        return as_service_user(inner, self.args.user)

    def write_marker(self, commit: str, digest: str) -> str:
        """Return the command that records what was just installed.

        Written **after** a successful install, so the marker never claims a
        deploy that did not happen. The wheel digest is recorded beside the commit
        so two deploys of one commit are still distinguishable.

        Args:
            commit: The commit the wheel was built from.
            digest: The wheel's sha256.

        Returns:
            The remote command line.
        """
        stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        body = f"{_MARKER_COMMIT_PREFIX}{commit}\nwheel_sha256={digest}\ndeployed_at={stamp}\n"
        inner = f"printf %s {shlex.quote(body)} > {self.args.marker}"
        return as_service_user(inner, self.args.user)

    def restart(self) -> str:
        """Return the restart command, which also prints the epoch it restarted at.

        The epoch comes from the **box**, so the journal window below is immune to
        clock skew between here and there.

        Returns:
            The remote command line.
        """
        inner = with_user_bus(f"systemctl --user restart {shlex.quote(self.args.unit)}")
        return as_service_user(f"echo RESTART_EPOCH=$(date +%s); {inner}", self.args.user)

    def is_active(self) -> str:
        """Return the command that asks whether the unit is active.

        Returns:
            The remote command line.
        """
        inner = with_user_bus(f"systemctl --user is-active {shlex.quote(self.args.unit)}")
        return as_service_user(inner, self.args.user)

    def journal_since(self, epoch: str) -> str:
        """Return the command that reads the unit's journal since ``epoch``.

        Args:
            epoch: Seconds since the epoch, as read from the box.

        Returns:
            The remote command line.
        """
        since = shlex.quote(f"@{epoch}")
        inner = with_user_bus(
            f"journalctl --user -u {shlex.quote(self.args.unit)} --since {since} --no-pager"
        )
        return as_service_user(inner, self.args.user)


def render(plan: Plan, commit: str) -> list[str]:
    """Render the plan as the lines ``--dry-run`` prints.

    Args:
        plan: The plan.
        commit: The commit the wheel would be built from.

    Returns:
        The lines to print. A remote step prints its ``ssh`` argv and then the
        remote command **verbatim** on its own line, because that command is one
        argv element rather than shell text: re-quoting it for display would show
        four levels of escaping nobody can check by eye, and the thing an operator
        needs to read is what the login shell will actually see.
    """
    args = plan.args
    ssh_prefix = f"ssh {args.ssh_user}@{args.host}"
    lines = [
        f"# deploying {commit} to {args.ssh_user}@{args.host} as service user {args.user}",
        f"build   : {shlex.join(['uv', 'build', '--wheel'])}",
    ]
    steps: list[tuple[str, str]] = [
        ("marker  ", plan.read_marker()),
        ("version ", plan.read_version()),
    ]
    lines.extend(_step_lines(ssh_prefix, steps))
    lines.append(f"stage   : {shlex.join(plan.stage())}")
    lines.extend(
        _step_lines(
            ssh_prefix,
            [
                ("perms   ", plan.make_readable()),
                ("install ", plan.install()),
                ("marker! ", plan.write_marker(commit, "<sha256 of the built wheel>")),
                ("restart ", plan.restart()),
                ("active? ", plan.is_active()),
                ("ready?  ", plan.journal_since("<restart epoch>")),
            ],
        )
    )
    lines.append(f"          (polled for up to {args.ready_timeout}s for hub_ready)")
    return lines


def _step_lines(ssh_prefix: str, steps: Sequence[tuple[str, str]]) -> list[str]:
    """Render remote steps as a label, the ssh argv, and the remote command.

    Args:
        ssh_prefix: The ``ssh user@host`` prefix.
        steps: Label and remote command pairs.

    Returns:
        Two or more lines per step.
    """
    lines: list[str] = []
    for label, remote in steps:
        lines.append(f"{label}: {ssh_prefix}")
        lines.extend(f"          {part}" for part in remote.splitlines())
    return lines


# --------------------------------------------------------------------------- #
# Execution                                                                    #
# --------------------------------------------------------------------------- #


def _run_local(argv: list[str], *, check: bool = True, cwd: Path | None = None) -> str:
    """Run a local command and return its stdout.

    Args:
        argv: The argv to run.
        check: Whether a non-zero status is an error.
        cwd: The directory to run in, defaulting to the current one.

    Returns:
        Standard output.

    Raises:
        DeployError: If the command fails and ``check`` is set.
    """
    resolved = [_binary(argv[0]), *argv[1:]]
    completed = subprocess.run(  # noqa: S603  # fixed argv, no shell, resolved binary
        resolved,
        cwd=None if cwd is None else str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )
    if check and completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise DeployError(f"{argv[0]} failed: {detail}")
    return completed.stdout


def _check_drift(plan: Plan, repo: Path) -> str:
    """Read the box's marker and rule on dependency drift.

    Args:
        plan: The plan.
        repo: The repository root.

    Returns:
        The marker text as read from the box (possibly empty).

    Raises:
        DeployError: If ``uv.lock`` moved since the deployed commit and this run
            would have installed with ``--no-deps``.
    """
    marker = _run_local(ssh_command(plan.args.host, plan.args.ssh_user, plan.read_marker()))
    deployed = marker_commit(marker)
    if deployed is None:
        print(
            "warning: no deployed-commit marker on the box, so dependency drift is\n"
            "         UNKNOWN, not clean. Proceeding; this deploy writes the marker,\n"
            "         and the next one can answer the question.",
            file=sys.stderr,
        )
        return marker
    try:
        drift = lockfile_drift(repo, deployed)
    except DeployError as exc:
        print(f"warning: {exc}; dependency drift is UNKNOWN, not clean.", file=sys.stderr)
        return marker
    if drift and not plan.args.with_deps:
        raise DeployError(
            f"uv.lock changed since the deployed commit {deployed[:12]}:\n"
            f"{drift}\n"
            "A --no-deps install would leave the venv on the old dependency set.\n"
            "Re-run with --with-deps to let uv resolve the wheel's requirements,\n"
            "and check the result against uv.lock — uv resolves from the index,\n"
            "not from this repository's lockfile."
        )
    return marker


def _wait_for_ready(plan: Plan, epoch: str) -> None:
    """Poll the unit's journal until ``hub_ready`` appears or the bound expires.

    Args:
        plan: The plan.
        epoch: The restart epoch, as read from the box.

    Raises:
        DeployError: If ``hub_ready`` does not appear within the bound.
    """
    deadline = time.monotonic() + plan.args.ready_timeout
    command = ssh_command(plan.args.host, plan.args.ssh_user, plan.journal_since(epoch))
    while True:
        if "hub_ready" in _run_local(command, check=False):
            return
        if time.monotonic() >= deadline:
            raise DeployError(
                f"the unit did not log hub_ready within {plan.args.ready_timeout}s of the\n"
                f"restart. The old code may still be running; read the journal:\n"
                f"  {shlex.join(command)}"
            )
        time.sleep(_POLL_INTERVAL)


def _restart_epoch(output: str) -> str:
    """Extract the restart epoch the restart command printed.

    Args:
        output: The restart command's stdout.

    Returns:
        The epoch as a string.

    Raises:
        DeployError: If the marker line is absent.
    """
    for line in output.splitlines():
        if line.startswith("RESTART_EPOCH="):
            return line.removeprefix("RESTART_EPOCH=").strip()
    raise DeployError("the restart command printed no RESTART_EPOCH; cannot bound the journal read")


def _deploy(plan: Plan, repo: Path, commit: str) -> None:
    """Run the deploy and verify it.

    Args:
        plan: The plan.
        repo: The repository root.
        commit: The commit being deployed.

    Raises:
        DeployError: If any step fails, or verification does not pass.
    """
    args = plan.args

    def ssh(remote: str) -> list[str]:
        return ssh_command(args.host, args.ssh_user, remote)

    before_marker = _check_drift(plan, repo)
    before_version = _run_local(ssh(plan.read_version())).strip()

    _run_local(["uv", "build", "--wheel"], cwd=repo)
    wheel_path = Path(args.wheel_path)
    if not wheel_path.is_file():
        raise DeployError(f"uv build --wheel produced no {wheel_path}")
    digest = hashlib.sha256(wheel_path.read_bytes()).hexdigest()

    _run_local(plan.stage())
    _run_local(ssh(plan.make_readable()))
    _run_local(ssh(plan.install()))
    _run_local(ssh(plan.write_marker(commit, digest)))

    epoch = _restart_epoch(_run_local(ssh(plan.restart())))
    active = _run_local(ssh(plan.is_active()), check=False).strip()
    if active != "active":
        raise DeployError(f"the unit is {active or '(no answer)'} after the restart, not active")
    _wait_for_ready(plan, epoch)

    after_marker = _run_local(ssh(plan.read_marker()))
    after_version = _run_local(ssh(plan.read_version())).strip()
    print("--- before ---")
    print(f"version: {before_version}")
    print((before_marker or "(no marker)\n").rstrip("\n"))
    print("--- after ----")
    print(f"version: {after_version}")
    print(after_marker.rstrip("\n"))
    print(f"unit {args.unit} is active and logged hub_ready; wheel sha256 {digest[:12]}")


def _parser() -> argparse.ArgumentParser:
    """Return the CLI parser.

    Returns:
        The parser.
    """
    parser = argparse.ArgumentParser(
        description="Build, install, restart and verify the hub on a remote box (issue #1389)."
    )
    parser.add_argument("host", help="the box's hostname or address")
    parser.add_argument(
        "user",
        nargs="?",
        default=DEFAULT_SERVICE_USER,
        help="the service user (default: assistant)",
    )
    parser.add_argument("--ssh-user", default=DEFAULT_SSH_USER, help="the login user for ssh")
    parser.add_argument("--unit", default=DEFAULT_UNIT, help="the systemd --user unit to restart")
    parser.add_argument("--venv", default=DEFAULT_VENV, help="the service venv on the box")
    parser.add_argument("--uv", default=DEFAULT_UV, help="the service user's uv binary")
    parser.add_argument("--marker", default=DEFAULT_MARKER, help="the deployed-commit marker")
    parser.add_argument("--stage-dir", default=DEFAULT_STAGE_DIR, help="where to stage the wheel")
    parser.add_argument("--wheel", help="the wheel filename (default: derived from pyproject.toml)")
    parser.add_argument("--repo", default=".", help="the repository root to build from")
    parser.add_argument(
        "--ready-timeout",
        type=int,
        default=DEFAULT_READY_TIMEOUT,
        help="seconds to wait for hub_ready after the restart",
    )
    parser.add_argument(
        "--with-deps", action="store_true", help="resolve dependencies instead of --no-deps"
    )
    parser.add_argument(
        "--allow-dirty", action="store_true", help="deploy an uncommitted tree, marked dirty"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="print the commands, contact nothing"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI.

    Args:
        argv: Arguments, defaulting to ``sys.argv[1:]``.

    Returns:
        The process exit status: 0, or 1 with the reason on stderr.
    """
    args = _parser().parse_args(argv)
    try:
        repo = Path(args.repo).resolve()
        wheel = args.wheel or wheel_name(repo)
        args.wheel_path = repo / "dist" / wheel
        commit = head_commit(repo, allow_dirty=args.allow_dirty)
        plan = Plan(args, wheel)
        if args.dry_run:
            for line in render(plan, commit):
                print(line)
            return 0
        _deploy(plan, repo, commit)
    except DeployError as exc:
        print(f"deploy-hub: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
