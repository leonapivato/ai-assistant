"""The offline re-embedding tool: its own console script (ADR-0104 §5).

ADR-0083 §10 names this migration by name — "An offline tool — the re-embedding
migration (#425) is the first and for now the only one — takes the same instance
lock, which serialises it against the hub by construction and needs no new
mechanism." This module is that tool's entry point, and the placement follows
from rules already in force rather than from preference.

**It lives here because the lock does.** ``InstanceLock`` is in
:mod:`ai_assistant.service.lock`, and ``lint-imports``' "nothing imports the
service" contract means anything taking that lock has to *be* in ``service``. The
same rule forecloses the obvious alternative twice over: an ``assistant reembed``
subcommand would put a ``interfaces -> service`` edge in an interface adapter,
which is exactly the reasoning ADR-0084 §6 gives for the hub having its own
console script.

**And it imports no subsystem**, which is the other half of ADR-0083 §8:
``service`` may import ``app`` and ``core``. The migration itself belongs to
``memory``, the embedder to ``models``, and the composition root is the one layer
allowed to name both — so this module asks :func:`~ai_assistant.app.build_reembedder`
for a wired migration and drives it.

**Contention is refused, not retried**, and that is a deliberate departure from
what a losing *hub* does (ADR-0083 §1). A hub retries for a few seconds because
the holder may be draining and the supervisor's restart is automatic; neither
applies here. The holder of the lock, from this tool's point of view, is a hub
that is meant to be running, and the operator's next act is to stop it. Retrying
would turn a one-line instruction into a wait.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from typing import TYPE_CHECKING

from ai_assistant.app import build_reembedder
from ai_assistant.core.config import load_settings
from ai_assistant.core.errors import AssistantError, ConfigurationError
from ai_assistant.service import datadir
from ai_assistant.service.exits import EXIT_OK, EXIT_RESTART, classify
from ai_assistant.service.lock import LOCK_FILENAME, InstanceLock

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.core.config import Settings

_DESCRIPTION = """
Re-embed this deployment's memory store against the configured embedder.

Run it with the hub stopped: it takes the same instance lock, so it cannot run
beside one. It never writes the live store — the re-embedded store is built
beside it, verified against it, and moved into place in one step — and it resumes
where it left off if it is interrupted.
"""


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    """Read the two decisions this tool leaves to the operator.

    Deliberately small. The data directory and the embedder come from
    configuration (``ASSISTANT_DATA_DIR``, ``ASSISTANT_EMBEDDER``) rather than
    from flags, because a migration that could be pointed at a different store or
    a different embedding space than the hub uses would be a way to build exactly
    the mismatch this tool exists to repair.
    """
    parser = argparse.ArgumentParser(
        prog="ai-assistant-reembed",
        description=_DESCRIPTION,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report what would happen and change nothing",
    )
    parser.add_argument(
        "--upload-entire-memory-store",
        action="store_true",
        help=(
            "authorise sending every record in the memory store to a configured "
            "embedder that does not run on this machine (ADR-0104 §4)"
        ),
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the migration and return the process's exit code.

    Args:
        argv: Command-line arguments, for tests. ``None`` reads ``sys.argv``.

    Returns:
        ``0`` when the store was migrated or needed nothing, ``1`` when the lock
        was held or the attempt failed in a way a later attempt may not, and ``78``
        when a human must act first — the same vocabulary the hub's exit codes use
        (:mod:`ai_assistant.service.exits`), so an operator reads one set of
        meanings across both.
    """
    args = _parse_args(argv)
    try:
        settings = load_settings()
    except ConfigurationError as exc:
        return _report(exc)
    try:
        return asyncio.run(_migrate(settings, args))
    except KeyboardInterrupt:
        # ADR-0104 §2's whole point, said out loud: the work already committed is
        # kept, so this is a pause rather than a loss.
        print(
            "\ninterrupted. Nothing was swapped in and the work already done is kept — "
            "run this again to carry on from where it stopped.",
            file=sys.stderr,
        )
        return EXIT_RESTART


async def _migrate(settings: Settings, args: argparse.Namespace) -> int:
    """Take the lock, then plan, disclose, and run."""
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

    Written as a sequence of guarded exits rather than a nest, because every one
    of them is a distinct thing an operator reads and a distinct exit code. It
    names no ``memory`` type anywhere, which is not incidental: ADR-0104 §5 keeps
    this module free of subsystem imports, so the migration arrives as whatever
    the composition root returns and is only ever driven, never annotated.
    """
    try:
        reembedder = build_reembedder(
            settings, upload_entire_memory_store=args.upload_entire_memory_store
        )
        plan = reembedder.plan() if reembedder.store.exists() else None
    except AssistantError as exc:
        return _report(exc)

    if plan is None:
        # Not a failure: a deployment that has never run the hub has no store to
        # migrate, and the one it eventually writes is tagged correctly from its
        # first record. Saying so is more useful than a non-zero exit.
        print(f"there is no memory store at {reembedder.store} yet. Nothing to migrate.")
        return EXIT_OK

    if not plan.required:
        print(
            f"{plan.store} is already built with {plan.target_model} "
            f"({plan.target_dimensions} dimensions). Nothing to do."
        )
        return EXIT_OK

    # ADR-0104 §4's disclosure, on the path that got past the refusal.
    print(f"store:   {plan.store}")
    print(f"from:    {plan.source_model} ({plan.source_dimensions} dimensions)")
    print(f"to:      {plan.target_model} ({plan.target_dimensions} dimensions)")
    print(f"records: {plan.records}, of which {plan.outstanding} still need embedding")
    if args.dry_run:
        print("--dry-run: stopping here, nothing was changed.")
        return EXIT_OK

    try:
        outcome = await reembedder.run(progress=_Progress().report)
    except AssistantError as exc:
        return _report(exc)
    carried = f" ({outcome.resumed} carried over from an earlier run)" if outcome.resumed else ""
    print(f"done: {outcome.embedded} records re-embedded{carried}.")
    if not outcome.durable:
        # The swap happened; only its durability is unconfirmed. Said as a warning
        # rather than an error for exactly that reason (ADR-0104 §3).
        print(
            f"warning: {plan.store} was replaced, but the rename could not be flushed to "
            f"disk on this filesystem. It may not survive a power loss until the "
            f"filesystem next syncs.",
            file=sys.stderr,
        )
    print(f"the store as it was is kept at {plan.backup} — delete it when you are satisfied.")
    return EXIT_OK


class _Progress:
    """Prints how far along the run is, at most once per whole percent.

    A long run is otherwise indistinguishable from a stuck one, which matters more
    here than in most places: ADR-0104 §2 accepts an unbounded runtime rather than
    trying to shorten it, so "is it still going?" is the question an operator will
    actually have. Throttled because a chunk is small and a large store would
    otherwise scroll thousands of identical-looking lines past them.
    """

    def __init__(self) -> None:
        self._last = -1

    def report(self, done: int, total: int) -> None:
        """Print progress when the whole-percent figure has moved, and at the end."""
        percent = 100 if total == 0 else done * 100 // total
        if percent == self._last and done < total:
            return
        self._last = percent
        print(f"  {done}/{total} records ({percent}%)", flush=True)


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
    and uncopied: "would restarting, unchanged, ever succeed?" has one answer
    whether the process asking is the hub or this tool, and a second implementation
    of that test is a second thing to keep in step.
    """
    code, action = classify(exc)
    print(f"re-embedding did not run: {exc}", file=sys.stderr)
    if action:
        print(f"what to do: {action}", file=sys.stderr)
    return code
