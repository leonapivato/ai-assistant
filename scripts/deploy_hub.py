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
waiting a bounded time for ``hub_ready`` in the journal of **this start of the
unit** — matched on the ``InvocationID`` systemd assigns each start, not on a
timestamp, because any timestamp window is captured before the restart is issued
and so can contain the *previous* process's readiness line — and printing the
installed version and marker before and after.

**The wheel is whatever the build produced.** It is built into a fresh temporary
directory and read back from there, never located by a name predicted from
``pyproject.toml``: a predicted name can miss the build's real output, or match a
stale wheel left in ``dist/`` by an earlier version and ship it under today's
commit. ``--wheel`` deploys an already-built file instead of building at all, and
then ``--wheel-commit`` is required: such a wheel need not have come from this
checkout, and the marker is what the next deploy trusts to rule on drift.

**It keeps that name on the box, in a directory of its own.** Two deploys of one
version must not overwrite each other's wheel between ``scp`` and install, so
something per-run has to distinguish them — but that something cannot be a
*filename* prefix: a wheel's name is its metadata (PEP 427, five or six
dash-delimited components), and ``deploy-hub-<token>-`` adds two more, so
``uv pip install`` rejects the file before reading a byte of it (issue #1481).
The per-run token therefore names a **directory**, created for this deploy and
removed after it, and the wheel inside keeps the name the build gave it.

**A staged wheel is verified before it is installed.** The wheel is tens of
megabytes over a link that takes minutes, and an ``scp`` killed midway leaves a
*truncated* file that installs as far as "unable to locate the end of central
directory record". So the deploy asks the box for the staged file's sha256 — as
the service user, which proves readability and integrity in one step — and
refuses unless it matches the digest of the local file, which is the same digest
the marker records.

``--dry-run`` prints the exact commands the run would issue and contacts nothing.
It is what the tests drive, because the remote half cannot be exercised from a
gate that has no box to talk to.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import secrets
import shlex
import shutil
import subprocess
import sys
import tempfile
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
#: Where the per-deploy staging directory is created on the box.
DEFAULT_STAGE_DIR = "/tmp"  # noqa: S108  # world-readable by design: root writes, the service user reads
#: The staging directory's name, before the per-run token is appended.
_STAGE_PREFIX = "deploy-hub-"
#: Seconds to wait for ``hub_ready`` after the restart before calling it a failure.
DEFAULT_READY_TIMEOUT = 60
#: Seconds between journal polls while waiting for it.
_POLL_INTERVAL = 2.0
#: The marker's first field, so a reader (human or the next deploy) can parse it.
_MARKER_COMMIT_PREFIX = "commit="
#: A marker written before this recipe existed: the bare sha, on a line of its own.
_BARE_COMMIT = re.compile(r"[0-9a-fA-F]{7,40}")
#: The only pre-slash segments left unquoted for the shell: `~` and `~username`.
_TILDE_SEGMENT = re.compile(r"~[A-Za-z0-9_][A-Za-z0-9_.-]*|~")


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


def resolve_commit(repo: Path, ref: str) -> str:
    """Resolve the commit a supplied wheel was built from.

    Args:
        repo: The repository root.
        ref: Whatever the operator attested — a sha, a tag, a branch.

    Returns:
        The 40-character commit sha.

    Raises:
        DeployError: If the ref does not resolve to a commit in this clone. It
            has to resolve *here*, because the marker it becomes is what the next
            deploy diffs ``uv.lock`` across.
    """
    completed = subprocess.run(  # noqa: S603  # fixed argv, no shell, resolved binary
        [_binary("git"), "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"],
        cwd=str(repo),
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0 or not completed.stdout.strip():
        raise DeployError(f"--wheel-commit {ref} is not a commit in {repo}")
    return completed.stdout.strip()


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


def lockfile_drift(repo: Path, deployed: str, target: str) -> str | None:
    """Report whether ``uv.lock`` changed between two commits.

    Args:
        repo: The repository root.
        deployed: The commit recorded by the previous deploy.
        target: The commit being deployed now — ``HEAD`` for a build, and the
            commit the operator attested for a supplied wheel. Never assumed,
            because a supplied wheel need not have been built from this checkout.

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
    diff = _git("diff", "--stat", deployed, target, "--", "uv.lock", repo=repo)
    return diff or None


def lockfile_uncommitted(repo: Path) -> bool:
    """Report whether ``uv.lock`` is modified in the working tree.

    Args:
        repo: The repository root.

    Returns:
        True when the lockfile differs from the index or from ``HEAD``.
    """
    return bool(_git("status", "--porcelain", "--", "uv.lock", repo=repo))


def marker_commit(marker_text: str) -> str | None:
    """Extract the commit from a marker file's contents.

    Two formats are read. This recipe writes ``key=value`` lines. A box deployed
    by hand before the recipe existed carries the older one — the bare sha and
    nothing else — and reading that as *absent* would say "drift is UNKNOWN" on a
    box that in fact records exactly what is deployed (issue #1481). The older
    form is recognised on the **last** non-blank line, because the marker is the
    last thing ``cat`` writes and everything before it may be the login shell's
    banner; a banner line that is itself a bare hex word would be misread, and
    the cost of that is a commit this clone does not hold, which already reports
    itself as unknown rather than as clean.

    Args:
        marker_text: The marker file as read from the box.

    Returns:
        The recorded commit, or ``None`` when neither form is present. A
        ``-dirty`` suffix is stripped, because the dependency question is about
        the committed lockfile and a dirty deploy still answers it.
    """
    for line in marker_text.splitlines():
        stripped = line.strip()
        if stripped.startswith(_MARKER_COMMIT_PREFIX):
            value = stripped.removeprefix(_MARKER_COMMIT_PREFIX).strip()
            return value.removesuffix("-dirty") or None
    lines = [line.strip() for line in marker_text.splitlines() if line.strip()]
    if lines and _BARE_COMMIT.fullmatch(lines[-1].removesuffix("-dirty")):
        return lines[-1].removesuffix("-dirty")
    return None


# --------------------------------------------------------------------------- #
# Remote side: how a command reaches the service user                          #
# --------------------------------------------------------------------------- #


def remote_path(path: str) -> str:
    """Quote a path for the remote shell without disabling ``~`` expansion.

    Every path here is a parameter, and an unquoted one with a space in it stops
    being a path: ``> /var/lib/deploy marker`` redirects to ``/var/lib/deploy``
    and passes ``marker`` as an argument. Plain ``shlex.quote`` would fix that and
    break the other half — ``'~/venv'`` is not tilde-expanded, and these paths are
    written relative to the service user's home precisely so the login shell
    resolves them. So the tilde segment is left bare and everything after the
    first ``/`` is quoted, which is what the shell's own rule for tilde expansion
    (an unquoted ``~`` up to the first unquoted ``/``) already allows.

    Args:
        path: The remote path.

    Returns:
        The path as one shell word.
    """
    head, separator, rest = path.partition("/")
    if not _TILDE_SEGMENT.fullmatch(head):
        # Not a tilde form at all, or not one worth trusting. `~; touch /tmp/x`
        # partitions to a head with no slash in it, and leaving that bare would
        # make a path argument a second command; a space in it would redirect
        # somewhere else entirely. Quoting the whole thing costs only the
        # expansion, which such a path was never going to get correctly anyway.
        return shlex.quote(path)
    if not separator:
        return head
    return f"{head}/{shlex.quote(rest)}" if rest else f"{head}/"


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


def scp_command(host: str, ssh_user: str, local: Path, destination: str) -> list[str]:
    """Return the local argv that copies the wheel to the box.

    Args:
        host: The box's hostname or address.
        ssh_user: The login user ssh authenticates as.
        local: The local wheel.
        destination: The destination path on the box.

    Returns:
        The argv.
    """
    # The destination path is expanded by a shell on the far side, so it is
    # quoted for that shell rather than passed raw.
    return ["scp", str(local), f"{ssh_user}@{host}:{remote_path(destination)}"]


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
        #: A per-run token naming the staging DIRECTORY. The parent is shared and
        #: world-readable, so a fixed location lets two deploys of one version
        #: overwrite each other's wheel between `scp` and install — installing one
        #: build while recording the other's commit and digest in the marker,
        #: which is exactly the provenance the drift check later trusts. The token
        #: cannot go in the filename: a wheel's name is its metadata, and a prefix
        #: makes it unreadable to `uv pip install` (issue #1481).
        self.token = secrets.token_hex(4)
        #: The wheel on THIS machine. `None` until a real run has one — a dry run
        #: never resolves it, because a dry run never builds.
        self._local: Path | None = None

    @property
    def local(self) -> Path:
        """The wheel to copy.

        Returns:
            The local path.

        Raises:
            DeployError: If no wheel has been resolved yet.
        """
        if self._local is None:
            raise DeployError("no wheel has been built or supplied yet")
        return self._local

    def use(self, wheel: Path) -> None:
        """Adopt the wheel a build produced, or the one the operator supplied.

        Args:
            wheel: The local wheel.
        """
        self._local = wheel
        self.wheel = wheel.name

    @property
    def stage_dir(self) -> str:
        """The directory this deploy stages its wheel in, and nothing else does.

        Returns:
            The remote directory path.
        """
        return f"{self.args.stage_dir.rstrip('/')}/{_STAGE_PREFIX}{self.token}"

    @property
    def staged(self) -> str:
        """Where the wheel lands on the box, under the name the build gave it.

        Derived rather than stored, because the name is only *predicted* until
        the build has run: a real deploy replaces :attr:`wheel` with the file the
        build actually produced, and every command below must follow it.

        Returns:
            The staged path.
        """
        return f"{self.stage_dir}/{self.wheel}"

    def make_stage_dir(self) -> str:
        """Return the command that creates this deploy's staging directory.

        Returns:
            The remote command line. The parent is created if it is missing, and
            the per-deploy directory is created **without** ``-p``, so a name
            that somehow already exists is an error rather than a directory
            somebody else owns; ``0755`` is what lets the service user read the
            wheel inside it.
        """
        parent = remote_path(self.args.stage_dir)
        return f"mkdir -p {parent} && mkdir -m 0755 {remote_path(self.stage_dir)}"

    def read_marker(self) -> str:
        """Return the command that reads the deployed-commit marker.

        Returns:
            The remote command line. It tolerates an absent marker.
        """
        marker = remote_path(self.args.marker)
        return as_service_user(f"cat {marker} 2>/dev/null || true", self.args.user)

    def read_version(self) -> str:
        """Return the command that prints the installed package version.

        Returns:
            The remote command line.
        """
        python = remote_path(f"{self.args.venv.rstrip('/')}/bin/python")
        expr = "import ai_assistant; print(ai_assistant.__version__)"
        inner = f"{python} -c {shlex.quote(expr)} 2>/dev/null || echo '(not installed)'"
        return as_service_user(inner, self.args.user)

    def stage(self) -> list[str]:
        """Return the argv that copies the wheel to the box.

        Returns:
            The local argv.
        """
        return scp_command(self.args.host, self.args.ssh_user, self.local, self.staged)

    def make_readable(self) -> str:
        """Return the command that makes the staged wheel readable by the service user.

        Returns:
            The remote command line. Explicit rather than relying on the login
            umask, because an unreadable wheel fails inside ``su`` with a message
            about the file rather than about the permission.
        """
        return f"chmod 0644 {remote_path(self.staged)}"

    def verify_staged(self) -> str:
        """Return the command that digests the staged wheel on the box.

        Run **as the service user**, so one answer settles both questions the
        install is about to ask of that file: that it is readable by the identity
        that installs it, and that it is the whole file rather than what a
        killed transfer left behind.

        Returns:
            The remote command line. The digest is emitted on a labelled line
            because a login shell prints its own banner alongside it, and it is
            empty rather than absent when the file cannot be read at all.
        """
        inner = f"echo STAGED_SHA256=$(sha256sum {remote_path(self.staged)} | cut -d' ' -f1)"
        return as_service_user(inner, self.args.user)

    def install(self) -> str:
        """Return the install command, run in the service user's login shell.

        Returns:
            The remote command line.
        """
        python = remote_path(f"{self.args.venv.rstrip('/')}/bin/python")
        deps = "" if self.args.with_deps else "--no-deps "
        inner = (
            f"{remote_path(self.args.uv)} pip install --python {python} "
            f"{deps}--force-reinstall {remote_path(self.staged)}"
        )
        return as_service_user(inner, self.args.user)

    def write_marker(self, commit: str, digest: str) -> str:
        """Return the command that records what was just installed.

        Written **after** a successful install, so the marker never claims a
        deploy that did not happen. The wheel digest is recorded beside the commit
        so two deploys of one commit are still distinguishable.

        Written to a neighbouring temporary file and *renamed* over the marker
        rather than redirected onto it. Redirection opens the existing file, which
        fails outright when a hand-run deploy left one owned by root (issue
        #1481); ``mv`` needs only write permission on the directory, which the
        service user has because the marker lives in its own home — and the file
        the next deploy reads is then always a whole one, never a half-written
        marker from a run that died mid-write.

        Args:
            commit: The commit the wheel was built from.
            digest: The wheel's sha256.

        Returns:
            The remote command line.
        """
        stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        body = f"{_MARKER_COMMIT_PREFIX}{commit}\nwheel_sha256={digest}\ndeployed_at={stamp}\n"
        marker = remote_path(self.args.marker)
        scratch = remote_path(f"{self.args.marker}.{self.token}.tmp")
        write = f"printf %s {shlex.quote(body)} > {scratch} && mv -f {scratch} {marker}"
        # A failed rename must not leave the scratch file behind to accumulate
        # under a name nothing will ever look for again.
        inner = f"{{ {write}; }} || {{ rm -f {scratch}; exit 1; }}"
        return as_service_user(inner, self.args.user)

    def unstage(self) -> str:
        """Return the command that removes the staged wheel and its directory.

        Returns:
            The remote command line. Run as the login user, which owns both. The
            directory goes with ``rmdir`` rather than a recursive delete: it is
            an interpolated path, and the only thing that should ever be in it is
            the one wheel just removed.
        """
        return f"rm -f {remote_path(self.staged)} && rmdir {remote_path(self.stage_dir)}"

    def restart(self) -> str:
        """Return the restart command, which also prints the new invocation id.

        A timestamp cannot bound the readiness check correctly. ``date +%s`` has
        one-second granularity, and whatever instant is captured, the restart is
        issued *after* it — so a ``hub_ready`` logged by the **old** process in
        between falls inside the window, and a replacement that starts but never
        becomes ready would then be verified by the log line of the process it
        replaced. systemd already answers the question exactly: every start of a
        unit gets its own ``InvocationID``, and the journal is filterable by it.

        The ``&&`` is load-bearing. On a failed restart the id would still be
        readable — it would just be the *previous* invocation's, whose journal
        does contain ``hub_ready`` — so the id is printed only when the restart
        succeeded, and a run with no id refuses rather than verifying the old one.

        Returns:
            The remote command line.
        """
        unit = shlex.quote(self.args.unit)
        inner = (
            "export XDG_RUNTIME_DIR=/run/user/$(id -u); "
            f"systemctl --user restart {unit} && "
            f"echo INVOCATION_ID=$(systemctl --user show -p InvocationID --value {unit})"
        )
        return as_service_user(inner, self.args.user)

    def is_active(self) -> str:
        """Return the command that asks whether the unit is active.

        The answer is emitted on its own labelled line, for the same reason the
        restart labels the invocation id: this runs in a **login** shell by
        design, and a login shell on a real box prints whatever its profile and
        MOTD print. Comparing the whole of stdout to ``active`` would read a
        banner as a failed unit and abort a deploy that worked.

        Returns:
            The remote command line.
        """
        state = with_user_bus(f"systemctl --user is-active {shlex.quote(self.args.unit)}")
        # `|| true`: `is-active` exits non-zero *because* the unit is not active,
        # and that answer must reach the label rather than killing the command.
        return as_service_user(f"echo UNIT_STATE=$({state} || true)", self.args.user)

    def journal_for(self, invocation: str) -> str:
        """Return the command that reads the journal of one unit *start*.

        Args:
            invocation: The unit's ``InvocationID`` for the start being verified.

        Returns:
            The remote command line.
        """
        match = shlex.quote(f"_SYSTEMD_INVOCATION_ID={invocation}")
        inner = with_user_bus(
            f"journalctl --user -u {shlex.quote(self.args.unit)} {match} --no-pager"
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
    if args.wheel:
        build = f"(none — deploying the supplied wheel {args.wheel})"
    else:
        build = "uv build --wheel --out-dir <a fresh temp dir>"
    lines = [
        f"# deploying {commit} to {args.ssh_user}@{args.host} as service user {args.user}",
        f"build   : {build}",
    ]
    steps: list[tuple[str, str]] = [
        ("marker  ", plan.read_marker()),
        ("version ", plan.read_version()),
    ]
    lines.extend(_step_lines(ssh_prefix, steps))
    lines.extend(_step_lines(ssh_prefix, [("stagedir", plan.make_stage_dir())]))
    staged = f"{args.ssh_user}@{args.host}:{plan.staged}"
    lines.append(f"stage   : scp <the wheel above> {staged}")
    lines.extend(
        _step_lines(
            ssh_prefix,
            [
                ("perms   ", plan.make_readable()),
                ("verify  ", plan.verify_staged()),
                ("install ", plan.install()),
                ("unstage ", plan.unstage()),
                ("marker! ", plan.write_marker(commit, "<sha256 of the built wheel>")),
                ("restart ", plan.restart()),
                ("active? ", plan.is_active()),
                ("ready?  ", plan.journal_for("<the id the restart printed>")),
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


def _probe(argv: list[str]) -> tuple[int, str, str]:
    """Run a command and return its status alongside its output.

    Args:
        argv: The argv to run.

    Returns:
        The exit status, standard output and standard error.

    Raises:
        DeployError: If the executable is not on PATH.
    """
    completed = subprocess.run(  # noqa: S603  # fixed argv, no shell, resolved binary
        [_binary(argv[0]), *argv[1:]], capture_output=True, text=True, check=False
    )
    return completed.returncode, completed.stdout, completed.stderr


def _check_drift(plan: Plan, repo: Path, commit: str) -> str:
    """Read the box's marker and rule on dependency drift.

    Args:
        plan: The plan.
        repo: The repository root.
        commit: The commit being deployed.

    Returns:
        The marker text as read from the box (possibly empty).

    Raises:
        DeployError: If ``uv.lock`` moved since the deployed commit and this run
            would have installed with ``--no-deps``.
    """
    # Checked FIRST, and independently of the marker. A lockfile modified in the
    # working tree is a dependency change no commit range can see: with
    # --allow-dirty the deployed commit is HEAD, `git diff HEAD HEAD` is empty,
    # and a --no-deps install would ship a wheel whose new requirement is not on
    # the box. Only when this run builds the wheel — a supplied one did not come
    # from this tree, so this tree's lockfile says nothing about it.
    building = not plan.args.wheel and not plan.args.with_deps
    if building and lockfile_uncommitted(repo):
        raise DeployError(
            "uv.lock is modified in the working tree, so the wheel this builds may\n"
            "need a dependency the box does not have — and no commit range can show\n"
            "it. Commit the lockfile, or re-run with --with-deps."
        )
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
        drift = lockfile_drift(repo, deployed, commit.removesuffix("-dirty"))
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


def _discard_stage(plan: Plan) -> None:
    """Remove this deploy's staged wheel and its directory, best effort.

    Best effort in both directions, because it runs on the failure path too. A
    cleanup that cannot run must not *become* the failure — on the way out of an
    error it would replace the reason with a symptom, and after a successful
    install it would fail a deploy that worked. So it warns and names the path,
    which is the one thing an operator cannot reconstruct.

    Args:
        plan: The plan, carrying the staging directory to remove.
    """
    command = ssh_command(plan.args.host, plan.args.ssh_user, plan.unstage())
    try:
        status, out, error = _probe(command)
    except DeployError as exc:  # ssh itself is unavailable
        status, out, error = 1, "", str(exc)
    if status != 0:
        print(
            f"warning: could not remove the staging directory {plan.stage_dir} on\n"
            f"         {plan.args.host}: {(error or out).strip() or f'exit {status}'}\n"
            f"         The wheel in it is this deploy's; remove it by hand.",
            file=sys.stderr,
        )


def _assert_staged(plan: Plan, digest: str) -> None:
    """Confirm the box holds the whole wheel, before anything installs it.

    The wheel is tens of megabytes over a link that takes minutes. A transfer
    killed midway leaves a *truncated* file that ``scp`` may still have exited
    non-zero for — but which, if the deploy is retried past it, installs as far
    as "unable to locate the end of central directory record", from inside uv,
    naming nothing an operator can act on (issue #1481).

    Args:
        plan: The plan.
        digest: The sha256 of the local wheel, which is also what the marker
            records for this deploy.

    Raises:
        DeployError: If the check could not run, the staged file is unreadable,
            or its digest is not the local wheel's.
    """
    command = ssh_command(plan.args.host, plan.args.ssh_user, plan.verify_staged())
    status, out, error = _probe(command)
    staged = _labelled(out, "STAGED_SHA256=")
    if staged is None:
        raise DeployError(
            f"could not digest the staged wheel (exit {status}):\n"
            f"{error.strip() or out.strip() or '(no output)'}\n"
            f"Nothing has been installed; the check is what could not run."
        )
    if not staged:
        raise DeployError(
            f"the service user {plan.args.user} cannot read the staged wheel at\n"
            f"  {plan.staged}\n"
            "so the install would fail inside su with a message about the file."
        )
    if staged != digest:
        raise DeployError(
            f"the staged wheel is not the one that was sent:\n"
            f"  local  {digest}\n"
            f"  staged {staged}\n"
            "A transfer cut short leaves a truncated wheel that installs as far as\n"
            "'unable to locate the end of central directory record'. Nothing has\n"
            "been installed; re-run the deploy."
        )


def _assert_active(plan: Plan) -> None:
    """Confirm the unit came back up.

    ``systemctl is-active`` exits non-zero *because* the unit is not active, so
    unlike the journal poll a status alone cannot separate that answer from a
    dropped connection. The ANSWER can: an empty stdout means systemctl never
    spoke, and reporting that as "the unit is (no answer), not active" would send
    an operator to look at the unit instead of at the link.

    Args:
        plan: The plan.

    Raises:
        DeployError: If the check could not run, or the unit is not active.
    """
    command = ssh_command(plan.args.host, plan.args.ssh_user, plan.is_active())
    status, out, error = _probe(command)
    active = _labelled(out, "UNIT_STATE=")
    if active is None:
        raise DeployError(
            f"could not ask whether the unit is active (exit {status}):\n"
            f"{error.strip() or out.strip() or '(no output)'}\n"
            "The wheel is installed and the restart was issued; the check is what\n"
            "could not run."
        )
    if active != "active":
        raise DeployError(f"the unit is {active or '(no state)'} after the restart, not active")


def _wait_for_ready(plan: Plan, invocation: str) -> None:
    """Poll this unit start's journal until ``hub_ready`` appears, or time out.

    Args:
        plan: The plan.
        invocation: The ``InvocationID`` of the start being verified, so a
            ``hub_ready`` from any earlier start of the unit cannot satisfy it.

    Raises:
        DeployError: If ``hub_ready`` does not appear within the bound.
    """
    deadline = time.monotonic() + plan.args.ready_timeout
    command = ssh_command(plan.args.host, plan.args.ssh_user, plan.journal_for(invocation))
    while True:
        # A failed poll is NOT an empty journal. `journalctl` exits 0 when a match
        # selects nothing — "-- No entries --" is success — so a non-zero status
        # here is ssh, su or journalctl failing, and swallowing it would spend the
        # whole timeout and then report the one thing that is not wrong: that the
        # unit never logged hub_ready.
        status, out, err = _probe(command)
        if status != 0:
            raise DeployError(
                f"could not read the unit's journal (exit {status}):\n"
                f"{(err or out).strip()}\n"
                f"The wheel is installed and the restart was issued; the readiness\n"
                f"check is what could not run. Retry:\n  {shlex.join(command)}"
            )
        if "hub_ready" in out:
            return
        if time.monotonic() >= deadline:
            raise DeployError(
                f"the unit did not log hub_ready within {plan.args.ready_timeout}s of the\n"
                f"restart. The old code may still be running; read the journal:\n"
                f"  {shlex.join(command)}"
            )
        time.sleep(_POLL_INTERVAL)


def _labelled(output: str, label: str) -> str | None:
    """Read one labelled line out of a login shell's output.

    Every remote answer is labelled because ``su -`` starts a login shell, and a
    login shell prints whatever its profile and MOTD print. A bare value would be
    indistinguishable from a banner.

    Args:
        output: The command's standard output.
        label: The line prefix, including its ``=``.

    Returns:
        The value, or ``None`` when no line carries the label.
    """
    for line in output.splitlines():
        if line.startswith(label):
            return line.removeprefix(label).strip()
    return None


def invocation_id(output: str) -> str:
    """Extract the ``InvocationID`` the restart command printed.

    Args:
        output: The restart command's stdout.

    Returns:
        The id.

    Raises:
        DeployError: If it is absent or empty. It is absent when the restart
            itself failed, and empty on a systemd too old to report one — and in
            both cases the alternative is verifying against a journal window that
            can contain an *earlier* start of the unit, which is the failure this
            replaced. Refusing leaves a deploy that has installed and restarted
            and only lacks its readiness proof, so the message says exactly that.
    """
    invocation = _labelled(output, "INVOCATION_ID=")
    if invocation:
        return invocation
    raise DeployError(
        "the restart printed no unit InvocationID, so the readiness check cannot be\n"
        "bound to THIS start of the unit and would accept an earlier one's hub_ready.\n"
        "The wheel is installed and the restart was issued; verify by hand with\n"
        "  systemctl --user status <unit>  and  journalctl --user -u <unit> -n 50"
    )


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

    before_marker = _check_drift(plan, repo, commit)
    before_version = _run_local(ssh(plan.read_version())).strip()

    if args.wheel:
        supplied = Path(args.wheel).resolve()
        if not supplied.is_file():
            raise DeployError(f"--wheel {supplied} is not a file")
        plan.use(supplied)
        _install_and_verify(plan, commit, before_marker, before_version)
        return
    # Built into a FRESH directory, and the wheel is then whatever that directory
    # holds — never a name predicted beforehand. A predicted name can miss the
    # build's real output (so the deploy fails) or, worse, match a stale wheel
    # left in `dist/` by an earlier version, which would be shipped and recorded
    # under today's commit. An empty directory cannot do either.
    with tempfile.TemporaryDirectory(prefix="deploy-hub-") as out:
        plan.use(build_wheel(repo, Path(out)))
        _install_and_verify(plan, commit, before_marker, before_version)


def build_wheel(repo: Path, out: Path) -> Path:
    """Build the wheel into ``out`` and return the file it produced.

    Args:
        repo: The repository root.
        out: An empty directory to build into.

    Returns:
        The wheel.

    Raises:
        DeployError: If the build produced anything other than exactly one wheel.
    """
    _run_local(["uv", "build", "--wheel", "--out-dir", str(out)], cwd=repo)
    wheels = sorted(out.glob("*.whl"))
    if len(wheels) != 1:
        names = ", ".join(w.name for w in wheels) or "nothing"
        raise DeployError(f"uv build --wheel produced {names}, not exactly one wheel")
    return wheels[0]


def _install_and_verify(plan: Plan, commit: str, before_marker: str, before_version: str) -> None:
    """Stage, install, restart and verify, then print before and after.

    Args:
        plan: The plan, carrying the wheel to deploy.
        commit: The commit being deployed.
        before_marker: The marker as it stood before this deploy.
        before_version: The installed version before this deploy.

    Raises:
        DeployError: If any step fails, or verification does not pass.
    """
    args = plan.args

    def ssh(remote: str) -> list[str]:
        return ssh_command(args.host, args.ssh_user, remote)

    # Streamed: the wheel carries a vendored model (ADR-0024 §4) and is tens of
    # megabytes today, with no ceiling that says it stays there.
    with plan.local.open("rb") as wheel_file:
        digest = hashlib.file_digest(wheel_file, "sha256").hexdigest()
    _run_local(ssh(plan.make_stage_dir()))
    # Everything from here to the install is cleaned up whichever way it ends. A
    # dropped transfer leaves tens of megabytes on the box, and a directory per
    # attempt under a name nothing will look for again; unstaging only on the
    # happy path means the failures — the runs that get retried — are exactly the
    # ones that accumulate. `finally` rather than a second call in an `except`,
    # so the error the operator needs to see is still the one that propagates.
    try:
        _run_local(plan.stage())
        _run_local(ssh(plan.make_readable()))
        _assert_staged(plan, digest)
        _run_local(ssh(plan.install()))
    finally:
        _discard_stage(plan)
    _run_local(ssh(plan.write_marker(commit, digest)))

    invocation = invocation_id(_run_local(ssh(plan.restart())))
    _assert_active(plan)
    _wait_for_ready(plan, invocation)

    after_marker = _run_local(ssh(plan.read_marker()))
    after_version = _run_local(ssh(plan.read_version())).strip()
    print("--- before ---")
    print(f"version: {before_version}")
    print((before_marker or "(no marker)\n").rstrip("\n"))
    print("--- after ----")
    print(f"version: {after_version}")
    print(after_marker.rstrip("\n"))
    print(f"unit {args.unit} is active and logged hub_ready; wheel sha256 {digest[:12]}")


def _deployed_commit(args: argparse.Namespace, repo: Path) -> str:
    """Return the commit this run will record on the box.

    A built wheel is this checkout by construction. A **supplied** one is not:
    it may have come from another commit or another clone entirely, and recording
    the current ``HEAD`` for it would put a false provenance in the marker — which
    the next deploy then trusts to rule on dependency drift. So ``--wheel``
    requires the operator to say what it was built from.

    Args:
        args: The parsed arguments.
        repo: The repository root.

    Returns:
        The commit to record, with a ``-dirty`` suffix where one applies.

    Raises:
        DeployError: If a supplied wheel carries no attested commit.
    """
    if not args.wheel:
        return head_commit(repo, allow_dirty=args.allow_dirty)
    if not args.wheel_commit:
        raise DeployError(
            "--wheel needs --wheel-commit <ref>: a supplied wheel need not have been\n"
            "built from this checkout, and the marker this deploy writes is what the\n"
            "NEXT deploy diffs uv.lock across to decide whether --no-deps is safe.\n"
            "Recording HEAD for a wheel built elsewhere makes that answer wrong."
        )
    return resolve_commit(repo, args.wheel_commit)


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
    parser.add_argument(
        "--stage-dir",
        default=DEFAULT_STAGE_DIR,
        help="where this deploy's staging directory is created",
    )
    parser.add_argument(
        "--wheel", help="deploy this already-built wheel instead of running uv build"
    )
    parser.add_argument(
        "--wheel-commit", help="the commit --wheel was built from (required with --wheel)"
    )
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
        # Only ever a *prediction*, used to render the plan and to name the file
        # on the box. A real run replaces it with the build's actual output.
        wheel = Path(args.wheel).name if args.wheel else wheel_name(repo)
        commit = _deployed_commit(args, repo)
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
