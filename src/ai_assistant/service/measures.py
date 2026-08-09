"""Leg 8's offline measure report: its own console script (ADR-0120 §9).

§9 rules that "the measures are computed by a **reporting tool that runs while
the hub is stopped**, in its own process, and never by the hub", and that "its
console entry point lives in ``ai_assistant/service/`` and imports no subsystem
directly". This module is that entry point, and every term of its placement is
borrowed rather than chosen — ADR-0104 §5 settled the same question for the
re-embedding migration and §9 transfers it: the entry point must take the
instance lock, the lock lives in :mod:`ai_assistant.service.lock`, and
``lint-imports``' "nothing imports the service" contract means anything taking
that lock has to *be* in ``service``.

**It is not the CLI command §9 forbids.** What is refused is a measure reachable
from the assistant client — an ``assistant`` subcommand, or anything routed over
the wire — because that is the read path ADR-0119 §7 exists to prevent. What is
required is a separate console script, and ADR-0084 §6's reasoning makes that the
only available shape: a subcommand "would live in ``interfaces``, which would then
have to import ``service`` — and ADR-0083 §8 forbids anything importing
``service`` at all". This is the third of that family, beside
``ai-assistant-hub`` and ``ai-assistant-reembed``.

**And it imports no subsystem**, which is the other half of ADR-0083 §8. The
mechanism belongs to ``evaluation``, which ``service`` may not name directly, so
this module asks :func:`~ai_assistant.app.build_measure_reader` for a wired reader
and drives it — the same indirect route :mod:`ai_assistant.service.reembed` takes.

**Contention is refused, not retried**, exactly as the re-embedder refuses it and
for the reason ADR-0104 §5 gives: the holder of the lock, from this tool's point
of view, is a hub that is meant to be running, and the operator's next act is to
stop it. Retrying would turn a one-line instruction into a wait.

**Reading a measure costs a hub restart, and ADR-0120 §9 accepts that cost by
name.** A measure is read at a decision point — is the baseline long enough, what
did the arming do, is the exit test met — not on a monitoring loop. The
alternative "buys a permanently-open read path into the instrument, and a read
path that exists is a read path a later lane can consume".
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime, timedelta
from math import isfinite
from typing import TYPE_CHECKING

from ai_assistant.app import build_measure_reader
from ai_assistant.core.config import load_settings
from ai_assistant.core.errors import AssistantError, ConfigurationError
from ai_assistant.service import datadir
from ai_assistant.service.exits import EXIT_DEPLOYMENT, EXIT_OK, EXIT_RESTART, classify
from ai_assistant.service.lock import LOCK_FILENAME, InstanceLock

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.core.config import Settings

_DESCRIPTION = """
Report leg 8's three measures over this deployment's trace stream (ADR-0120):
memory precision, the correction rate and the repeated-explanation rate, with the
diagnostics that travel with them.

Run it with the hub stopped: it takes the same instance lock, so it cannot run
beside one. It reads the trace store and writes nothing, anywhere.

A measure is a rate over an explicit half-open window of when events occurred,
and — where it looks forward from an event — an explicit settling period. Both
are part of the figure, so both are required: two windows are comparable only
when their settling agrees. No figure carries a threshold, a target or a verdict.
"""

_EPILOG = """
example:
  ai-assistant-measures --from 2026-07-01 --until 2026-08-01 --settling-hours 48
"""


def _instant(text: str) -> datetime:
    """Parse an ISO-8601 instant, reading a naive one as UTC.

    Naive input is accepted rather than refused because ``--from 2026-07-01`` is
    what an operator will type, and the resolved window is echoed in the report's
    own heading — so the assumption is visible in the output rather than only in
    this docstring.

    Args:
        text: The operator's argument.

    Returns:
        A timezone-aware instant.

    Raises:
        argparse.ArgumentTypeError: If it is not an ISO-8601 instant.
    """
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        msg = f"{text!r} is not an ISO-8601 instant (e.g. 2026-07-01 or 2026-07-01T12:00:00Z)"
        raise argparse.ArgumentTypeError(msg) from exc
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _settling(text: str) -> timedelta:
    """Parse the settling period, in hours, refusing what a duration cannot be.

    ``float`` alone is not enough and the gap is not theoretical: it accepts
    ``nan`` and ``inf``, and ``timedelta`` then raises — ``ValueError`` for the
    first and ``OverflowError`` for the second — from a line no ``except``
    clause in this module covers, so the tool would exit with a traceback
    instead of one of the codes it documents. A negative value is refused here
    too, ahead of the mechanism's own refusal, so that an operator who typed a
    minus sign is told at the argument rather than after the lock is taken.

    Args:
        text: The operator's argument.

    Returns:
        The settling period.

    Raises:
        argparse.ArgumentTypeError: If it is not a finite, non-negative number of
            hours a duration can hold.
    """
    try:
        hours = float(text)
    except ValueError as exc:
        msg = f"{text!r} is not a number of hours"
        raise argparse.ArgumentTypeError(msg) from exc
    if not isfinite(hours) or hours < 0:
        msg = f"a settling period must be a finite, non-negative number of hours; got {text!r}"
        raise argparse.ArgumentTypeError(msg)
    try:
        return timedelta(hours=hours)
    except OverflowError as exc:
        msg = f"a settling period of {text} hours is longer than any duration this tool can hold"
        raise argparse.ArgumentTypeError(msg) from exc


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    """Read the three decisions ADR-0120 §1 leaves to the operator.

    The data directory is not among them: it comes from configuration
    (``ASSISTANT_DATA_DIR``), because a report that could be pointed at a
    different deployment's store than the hub uses would be a way to attribute
    one deployment's numbers to another.
    """
    parser = argparse.ArgumentParser(
        prog="ai-assistant-measures",
        description=_DESCRIPTION,
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--from",
        dest="start",
        type=_instant,
        required=True,
        help="the window's inclusive start, as an ISO-8601 instant (naive is read as UTC)",
    )
    parser.add_argument(
        "--until",
        dest="end",
        type=_instant,
        required=True,
        help="the window's exclusive end, in the same form",
    )
    parser.add_argument(
        "--settling-hours",
        dest="settling",
        type=_settling,
        required=True,
        help=(
            "how long a surfaced record is given to be overturned before the window's "
            "figures are read. Part of the measure, not a tuning knob"
        ),
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the report and return the process's exit code.

    Args:
        argv: Command-line arguments, for tests. ``None`` reads ``sys.argv``.

    Returns:
        ``0`` when a report was printed, ``1`` when the lock was held or the
        attempt failed in a way a later one may not, and ``78`` when a human must
        act first — a refused window included, since the same command would refuse
        again. The same vocabulary the hub's exit codes use
        (:mod:`ai_assistant.service.exits`), so an operator reads one set of
        meanings across all three tools.
    """
    args = _parse_args(argv)
    try:
        settings = load_settings()
    except ConfigurationError as exc:
        return _report(exc)
    try:
        return asyncio.run(_measure(settings, args))
    except KeyboardInterrupt:
        # Nothing was written and nothing is half-done: the tool only reads.
        print("\ninterrupted. Nothing was changed — run this again when you like.", file=sys.stderr)
        return EXIT_RESTART


async def _measure(settings: Settings, args: argparse.Namespace) -> int:
    """Take the lock, then walk and report."""
    data_dir = settings.data_dir
    try:
        datadir.prepare(data_dir)
    except (AssistantError, OSError) as exc:
        return _report(exc)

    lock = InstanceLock(data_dir / LOCK_FILENAME)
    try:
        held = lock.acquire()
    except OSError as exc:
        return _report(exc)
    if not held:
        return _report_contention(lock)
    try:
        return await _run_locked(settings, args)
    finally:
        lock.release()


async def _run_locked(settings: Settings, args: argparse.Namespace) -> int:
    """Everything that must happen with the instance lock held.

    It names no ``evaluation`` type anywhere, which is not incidental: ADR-0120
    §9 keeps this module free of subsystem imports, so the reader arrives as
    whatever the composition root returns and is only ever driven.
    """
    reader = build_measure_reader(settings)
    if not reader.store.exists():
        # Not a failure. A deployment that has never run the hub has written no
        # trace, and ADR-0120 §8's disposition for a stream with nothing in it is
        # to say so rather than to state a figure or a zero.
        print(f"there is no trace store at {reader.store} yet. Nothing has been recorded.")
        return EXIT_OK

    try:
        report = await reader.report(start=args.start, end=args.end, settling=args.settling)
    except AssistantError as exc:
        return _report(exc)

    print(report.render())
    return EXIT_DEPLOYMENT if report.refusal is not None else EXIT_OK


def _report_contention(lock: InstanceLock) -> int:
    """Say that something else holds the lock, hedging the pid exactly as ADR-0083 §1 does."""
    pid = lock.recorded_pid()
    hint = f" (the lock file records pid {pid}, which may be stale)" if pid is not None else ""
    print(
        f"{lock.path} is held by another instance{hint}. Stop the hub, then run this again.",
        file=sys.stderr,
    )
    return EXIT_RESTART


def _report(exc: BaseException) -> int:
    """Print a failure and return the code ADR-0083 §5's test gives it.

    The classification is :func:`~ai_assistant.service.exits.classify`'s, unchanged
    and uncopied, for the reason :mod:`ai_assistant.service.reembed` states: the
    question "would restarting, unchanged, ever succeed?" has one answer whether
    the process asking is the hub or an offline tool.
    """
    code, action = classify(exc)
    print(f"the measure report did not run: {exc}", file=sys.stderr)
    if action:
        print(f"what to do: {action}", file=sys.stderr)
    return code
