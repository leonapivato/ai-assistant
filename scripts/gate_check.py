"""Refuse the flip to ready unless CI's ``gate`` is green on the PR head.

ADR-0311 §4: a pull request is marked ready only while the ``gate`` check is
green on its current head commit, and ``just ready`` refuses while that check is
pending, failing, cancelled or absent, naming the state it saw. This is that
refusal; the ``ready`` recipe runs it after ``scripts/adr_ratify.py check-ready``.

It reads the PR's head commit and its check rollup in one ``gh pr view`` call, so
the verdict and the commit it is about cannot come from two different moments. It
also refuses unless that head is local ``HEAD``, so a push landing while it waits
is not certified by the run of the commit before it.

A pending or absent check is waited on, polling, up to ``--wait`` seconds (nine
minutes by default, inside one foreground tool call); it never flips on one. A
failing or cancelled check refuses at once, because waiting cannot change it.

Exit status: 0 green; 1 refused; 3 still pending or absent when the wait ran out,
so run it again.

Everything is stdlib and every external call is a fixed argv.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

CHECK_NAME = "gate"
GREEN = "green"
PENDING = "pending"
ABSENT = "absent"

# Conclusions that are a failed run rather than a run that did not finish.
_FAILING = frozenset({"FAILURE", "TIMED_OUT", "STARTUP_FAILURE"})
# States waiting can still change. Everything else is final for this commit.
_UNDECIDED = frozenset({PENDING, ABSENT})

EXIT_GREEN = 0
EXIT_REFUSED = 1
EXIT_STILL_PENDING = 3


class GateError(Exception):
    """A refusal that is not a state of the check: no PR, a moved head, a gh failure."""


def judge(rollup: Sequence[object]) -> str:
    """Return the state of the ``gate`` check in a ``statusCheckRollup`` list.

    Only a check run named ``gate`` counts, which is the name branch protection
    requires; a commit status of that name does not. Where the rollup carries
    more than one such run on the commit (a re-run, a reopened PR), any run still
    in progress makes the state ``pending``, and otherwise the most recently
    completed run decides.

    Args:
        rollup: The ``statusCheckRollup`` entries for one commit.

    Returns:
        ``green``, ``pending``, ``absent``, ``failing``, ``cancelled``, or any
        other conclusion GitHub reports, lowercased (``neutral``, ``skipped``...).
    """
    runs = [
        entry
        for entry in rollup
        if isinstance(entry, dict)
        and entry.get("__typename") == "CheckRun"
        and entry.get("name") == CHECK_NAME
    ]
    if not runs:
        return ABSENT
    if any(run.get("status") != "COMPLETED" for run in runs):
        return PENDING
    latest = max(runs, key=lambda run: str(run.get("completedAt") or ""))
    conclusion = str(latest.get("conclusion") or "").upper()
    if conclusion == "SUCCESS":
        return GREEN
    if conclusion in _FAILING:
        return "failing"
    if conclusion == "CANCELLED":
        return "cancelled"
    return conclusion.lower() or "unknown"


def _run(binary: str, *args: str) -> str:
    """Run a resolved binary with a fixed argv and return its stdout.

    Args:
        binary: The program name, resolved on ``PATH``.
        *args: Its arguments.

    Returns:
        Standard output, stripped.

    Raises:
        GateError: If the program is missing or exits non-zero.
    """
    found = shutil.which(binary)
    if found is None:
        raise GateError(f"{binary} not found on PATH")
    completed = subprocess.run(  # noqa: S603  # fixed argv, no shell, resolved binary
        [found, *args],
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", "replace").strip()
        raise GateError(f"{binary} {' '.join(args)}: {detail}")
    return completed.stdout.decode("utf-8", "replace").strip()


def read_pr() -> tuple[str, list[object]]:
    """Read the PR's head commit and that commit's check rollup in one call.

    Returns:
        The head SHA and its ``statusCheckRollup`` entries.

    Raises:
        GateError: If there is no PR or the answer is unreadable.
    """
    raw = _run("gh", "pr", "view", "--json", "headRefOid,statusCheckRollup")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise GateError(f"unreadable gh pr view output: {exc}") from exc
    if not isinstance(data, dict):
        raise GateError("unreadable gh pr view output: not an object")
    head = data.get("headRefOid")
    rollup = data.get("statusCheckRollup") or []
    if not isinstance(head, str) or not head:
        raise GateError("no PR found for this branch — open one first (gh pr create)")
    if not isinstance(rollup, list):
        raise GateError("unreadable gh pr view output: statusCheckRollup is not a list")
    return head, rollup


def local_head() -> str:
    """Return local ``HEAD``'s SHA.

    Returns:
        The commit SHA.
    """
    return _run("git", "rev-parse", "HEAD")


def _stderr(line: str) -> None:
    print(line, file=sys.stderr)


@dataclass(frozen=True)
class World:
    """What :func:`check` reads and does outside itself, injectable for tests.

    Attributes:
        read: Reads the PR head and its rollup.
        head: Reads local ``HEAD``.
        sleep: Sleeps between polls.
        clock: A monotonic clock.
        say: Reports progress once, when the wait starts.
    """

    read: Callable[[], tuple[str, list[object]]] = read_pr
    head: Callable[[], str] = local_head
    sleep: Callable[[float], None] = time.sleep
    clock: Callable[[], float] = time.monotonic
    say: Callable[[str], None] = _stderr


def check(*, wait: float, interval: float, world: World | None = None) -> tuple[int, str]:
    """Decide whether the PR may leave draft, waiting on an undecided check.

    Args:
        wait: Seconds to keep polling a pending or absent check.
        interval: Seconds between polls.
        world: The outside reads and effects; the real ones by default.

    Returns:
        The exit status and the message to print.
    """
    io = world or World()
    deadline = io.clock() + wait
    announced = False
    while True:
        try:
            pr_head, rollup = io.read()
            local = io.head()
        except GateError as exc:
            return EXIT_REFUSED, f"gate-check: {exc}"
        if pr_head != local:
            return EXIT_REFUSED, (
                f"gate-check: PR head is {pr_head[:12]} but HEAD is {local[:12]} — push "
                "first, or this would judge a commit the PR does not carry"
            )
        state = judge(rollup)
        where = f"`{CHECK_NAME}` is {state} on {pr_head[:12]}"
        if state == GREEN:
            return EXIT_GREEN, f"gate-check: {where}"
        if state not in _UNDECIDED:
            return EXIT_REFUSED, (
                f"gate-check: {where} — the PR stays in draft until it is green there (ADR-0311 §4)"
            )
        remaining = deadline - io.clock()
        if remaining <= 0:
            return EXIT_STILL_PENDING, (
                f"gate-check: `{CHECK_NAME}` is still {state} on {pr_head[:12]} — the PR "
                "stays in draft; run `just ready` again (ADR-0311 §4)"
            )
        if not announced:
            io.say(f"gate-check: {where}; waiting up to {wait:.0f}s")
            announced = True
        io.sleep(min(interval, remaining))


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI.

    Args:
        argv: Arguments, defaulting to ``sys.argv[1:]``.

    Returns:
        The process exit status.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--wait", type=float, default=540.0, help="seconds to wait (default 540)")
    parser.add_argument("--interval", type=float, default=15.0, help="seconds between polls")
    args = parser.parse_args(argv)
    status, message = check(wait=max(args.wait, 0.0), interval=max(args.interval, 1.0))
    print(message, file=sys.stdout if status == EXIT_GREEN else sys.stderr)
    return status


if __name__ == "__main__":
    raise SystemExit(main())
