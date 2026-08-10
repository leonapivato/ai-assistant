"""ADR-0129's store-health census: its own console script (§5).

§5 rules that "the store-health mechanism lives in ``ai_assistant/memory/``, it is
wired in ``app/composition.py``, and its console entry point lives in
``ai_assistant/service/`` and imports no subsystem directly", and that the entry
point "is its **own** console script, beside ``ai-assistant-hub``,
``ai-assistant-reembed`` and ``ai-assistant-measures``, and never an ``assistant``
subcommand". This module is that entry point, and every term of its placement is
borrowed rather than chosen: ADR-0104 §5 settled the same question for the
re-embedding migration and ADR-0120 §9 transferred it once already. The tool takes
the instance lock, the lock lives in :mod:`ai_assistant.service.lock`, and
``lint-imports``' "nothing imports the service" contract means anything taking
that lock has to *be* in ``service``. ADR-0084 §6 closes the other door: a
subcommand "would live in ``interfaces``, which would then have to import
``service``".

**And it imports no subsystem.** The census belongs to ``memory``, which
``service`` may not name directly, so this module asks
:func:`~ai_assistant.app.build_store_health_reader` for a wired reader and drives
it — the same indirect route :mod:`ai_assistant.service.reembed` and
:mod:`ai_assistant.service.measures` take.

**Contention is refused, not retried** (§4), exactly as its two siblings refuse it
and for the reason ADR-0104 §5 gives: the holder of the lock, from this tool's
point of view, is a hub that is meant to be running, and the operator's next act
is to stop it. The lock is not hygiene here — §1 defines every figure at one
instant ``T``, and a census taken while supersessions are landing is a census of
no instant.

**It is synchronous, unlike the other two.** Their mechanisms have something to
await — a ``TraceStore.walk``, an ``Embedder`` — and this one issues SQL against a
file and consults nothing else, so there is no loop to run and none is started.

**The store's path is printed here rather than by the report.** ADR-0129 §7
enumerates what the report's output carries — counts, proportions, distributions,
instants, ``kind`` and ``BeliefBand`` labels, and the run's stated parameters — and
a filesystem path is not among them. It is genuinely useful to an operator, and
§4's own contention diagnostic names the data directory and the lock path, so it
is stated by the tool that owns those diagnostics instead.
"""

from __future__ import annotations

import argparse
import sys
from typing import TYPE_CHECKING

from ai_assistant.app import (
    STORE_HEALTH_DEFAULT_K,
    STORE_HEALTH_DEFAULT_SAMPLE,
    STORE_HEALTH_MAX_K,
    build_store_health_reader,
)
from ai_assistant.core.config import load_settings
from ai_assistant.core.errors import AssistantError, ConfigurationError
from ai_assistant.service import datadir
from ai_assistant.service.exits import EXIT_OK, EXIT_RESTART, classify
from ai_assistant.service.lock import LOCK_FILENAME, InstanceLock

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.core.config import Settings

_DESCRIPTION = """
Take a census of this deployment's memory store (ADR-0129): how much of it is
live, retired, not yet live and expired-but-unpurged at one instant; how
concentrated the retired material is in the store's own embedding geometry; how
long ago each retirement happened; and how the whole store divides by belief band.

Run it with the hub stopped: it takes the same instance lock, so it cannot run
beside one. It opens the memory store read-only and writes nothing, anywhere —
no record, and no walk cursor.

Every figure is a count of the store as it stands when the tool runs. None is a
rate over a window, none is a measure of the trace-stream report
(ai-assistant-measures), and none carries a threshold, a target or a verdict.
"""

_EPILOG = """
example:
  ai-assistant-store-health --sample 2000 --k 20
"""


def _counted(text: str, *, ceiling: int | None = None) -> int:
    """Parse a count that must be at least one, and at most ``ceiling``.

    Refused at the argument rather than after the lock is taken, so an operator
    who typed a zero is told immediately and in the vocabulary ``--help`` used.
    The mechanism refuses the same values on its own account (ADR-0129 §3 makes
    ``k`` a positive integer, and the vector index puts a ceiling on it), which is
    not a duplicate check but the same rule held at the two places it can be
    broken: this one covers the command line, and the mechanism's covers every
    caller — including one that never came through here.

    Args:
        text: The operator's argument.
        ceiling: The largest value accepted, where there is one.

    Returns:
        The count.

    Raises:
        argparse.ArgumentTypeError: If it is not a whole number in range.
    """
    try:
        value = int(text)
    except ValueError as exc:
        msg = f"{text!r} is not a whole number"
        raise argparse.ArgumentTypeError(msg) from exc
    if value < 1:
        msg = f"must be at least 1, got {text!r}"
        raise argparse.ArgumentTypeError(msg)
    if ceiling is not None and value > ceiling:
        msg = f"must be at most {ceiling} — the vector index serves no more; got {text!r}"
        raise argparse.ArgumentTypeError(msg)
    return value


def _neighbourhood(text: str) -> int:
    """Parse ``--k``, which the vector index bounds above as well as below."""
    return _counted(text, ceiling=STORE_HEALTH_MAX_K)


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    """Read the two decisions ADR-0129 §3 leaves to the operator.

    Neither the data directory nor the instant is among them. The directory comes
    from configuration (``ASSISTANT_DATA_DIR``), for the reason the measure
    report gives — a census that could be pointed at another deployment's store
    would be a way to attribute one deployment's state to another. The instant is
    not an option at all (§1): the store keeps no history, so a past ``T`` would
    classify records that did not exist then and miss ones that did.
    """
    parser = argparse.ArgumentParser(
        prog="ai-assistant-store-health",
        description=_DESCRIPTION,
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--sample",
        type=_counted,
        default=STORE_HEALTH_DEFAULT_SAMPLE,
        help=(
            "how many vector-bearing records the concentration figure is taken over. "
            "The exhaustive figure is quadratic against a backend with no ANN index, "
            "so this is a sample by design; it is stated on the report"
        ),
    )
    parser.add_argument(
        "--k",
        dest="k",
        type=_neighbourhood,
        default=STORE_HEALTH_DEFAULT_K,
        help="how many nearest neighbours each sampled record's density is taken over",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Take the census and return the process's exit code.

    Args:
        argv: Command-line arguments, for tests. ``None`` reads ``sys.argv``.

    Returns:
        ``0`` when a report was printed — including over an absent or empty
        store, neither of which is a failure (ADR-0129 §4) — ``1`` when the lock
        was held or the attempt failed in a way a later one may not, and ``78``
        when a human must act first. The same vocabulary the hub's exit codes use
        (:mod:`ai_assistant.service.exits`), so an operator reads one set of
        meanings across every tool.
    """
    args = _parse_args(argv)
    try:
        settings = load_settings()
    except ConfigurationError as exc:
        return _report(exc)
    try:
        return _census(settings, args)
    except KeyboardInterrupt:
        # Nothing was written and nothing is half-done: the connection is opened
        # read-only, so an interrupted census leaves the store exactly as it was.
        print("\ninterrupted. Nothing was changed — run this again when you like.", file=sys.stderr)
        return EXIT_RESTART


def _census(settings: Settings, args: argparse.Namespace) -> int:
    """Take the lock, then read and report."""
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
        return _run_locked(settings, args)
    finally:
        lock.release()


def _run_locked(settings: Settings, args: argparse.Namespace) -> int:
    """Everything that must happen with the instance lock held.

    It names no ``memory`` type anywhere, which is not incidental: ADR-0129 §5
    keeps this module free of subsystem imports, so the reader arrives as whatever
    the composition root returns and is only ever driven.
    """
    reader = build_store_health_reader(settings)
    print(f"store:   {reader.store}")
    try:
        report = reader.report(sample=args.sample, k=args.k)
    except AssistantError as exc:
        return _report(exc)
    print(report.render())
    return EXIT_OK


def _report_contention(lock: InstanceLock) -> int:
    """Say that something else holds the lock, hedging the pid exactly as ADR-0083 §1 does.

    ADR-0129 §4 requires the diagnostic to name the data directory and the lock
    path, and requires the refusal to be immediate: the tool does not retry.
    """
    pid = lock.recorded_pid()
    hint = f" (the lock file records pid {pid}, which may be stale)" if pid is not None else ""
    print(
        f"{lock.path} is held by another instance{hint}, so this deployment's store at "
        f"{lock.path.parent} is being written to. Stop the hub, then run this again.",
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
    print(f"the store-health census did not run: {exc}", file=sys.stderr)
    if action:
        print(f"what to do: {action}", file=sys.stderr)
    return code
