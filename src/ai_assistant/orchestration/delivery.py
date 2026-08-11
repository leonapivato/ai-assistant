"""The engine's own view of the delivery outbox (ADR-0131 §2a, §3).

ADR-0131 §3 puts the outbox in the **engine's** domain — "behind the promoted
surface" — while §3b gives ``core`` a ``NotificationOutbox`` Protocol carrying
"exactly one method", ``offer``, which is what a *producer* holds. Serving a poll
needs three transitions that clause does not declare: select-and-lease,
acknowledge, and the startup reconciliation §3b requires. This module declares
them.

**A local ``Protocol`` rather than ``core`` surface, and the precedent is two
seams old.** :class:`ai_assistant.wire.server.Admission` is declared in ``wire``
and implemented in ``service`` for exactly this reason, and says so: "It is a
local ``Protocol``, not ``core/protocols.py`` surface: ADR-0124 §10 decides none,
and a listener's own collaborator is not a contract between subsystems (the
precedent is :mod:`ai_assistant.service.scheduler`'s)." The same three facts hold
here. ADR-0131 §3b decides one ``core`` Protocol and this is not it; golden rule 5
forbids a lane authoring a second unratified one; and no import edge is created,
because the composition root injects one object into both roles and neither
package names the other. ``lint-imports`` sees what it saw before.

**What that costs, stated rather than left to be found.** A second implementation
of the outbox is held to :class:`DeliveryOutbox` by ``mypy`` and by this package's
tests rather than by a shared conformance suite under ``tests/core``, because the
triad rule reaches ``core/protocols.py`` and this is not there. ADR-0131 §3b's
triad is owed for ``NotificationOutbox`` and is landed; this is the residue, and
promoting it is a decision for the ADR that next touches the seam.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from datetime import timedelta

    from ai_assistant.core.types import (
        NotificationCandidate,
        NotificationDelivery,
        NotificationEnqueue,
    )


@runtime_checkable
class DeliveryOutbox(Protocol):
    """The transitions :meth:`Engine.next_notification` drives (ADR-0131 §2a, §3).

    Every method raises
    :class:`~ai_assistant.core.errors.NotificationOutboxError` for a store fault,
    which is the failure ADR-0131 §4 declares on ``next_notification`` for exactly
    this reason.
    """

    async def offer(self, candidate: NotificationCandidate) -> NotificationEnqueue:
        """Hand one ruled interruption to the seam (ADR-0131 §3, §3b).

        **This one is ``core``'s**, and it is named here because the engine calls
        it too. :class:`~ai_assistant.core.protocols.NotificationOutbox` declares it
        for the *producer*; ADR-0131 §3b then says the same handoff runs on the
        reconsideration path — "ADR-0130 §5 rules a held record to ``INTERRUPT``
        through the same writer, so the same handoff runs" — and that path is this
        engine's. One object satisfies both Protocols, so naming the method here
        costs nothing and keeps this seam a complete statement of what the engine
        needs rather than a partial one the reader has to assemble.

        Args:
            candidate: The candidate whose disposition was ruled ``INTERRUPT``.

        Returns:
            Which of §3's four outcomes the offer reached.
        """
        ...

    async def claim(self) -> NotificationDelivery | None:
        """Select an entry, mint its identifier and lease it, in one step.

        ADR-0131 §2a makes the three indivisible and puts them **inside the engine
        call**: an earlier draft committed the lease at the result frame's write,
        which is not implementable behind this Protocol — ``_serve_requests``
        builds the result envelope from what the engine returned and writes
        afterwards, and an in-process caller has no write at all, so the same
        ``AssistantEngine`` would mean two different things on the two sides of
        the wire.

        Returns:
            The delivery to hand the caller, or ``None`` where nothing is
            available: the outbox is empty, or every entry is leased or departing.
        """
        ...

    async def acknowledge(self, delivery_id: str) -> None:
        """Retire the entry ``delivery_id`` is the current outstanding delivery of.

        Idempotent on anything else — an unknown identifier, a retired entry, or a
        delivery the entry has since superseded — which is what lets a client
        reconnect after any failure and acknowledge blindly (ADR-0131 §3).

        Args:
            delivery_id: What the device says it received.
        """
        ...

    async def withdraw(self, record_id: str) -> bool:
        """Give up the entry carrying one ADR-0130 record (ADR-0131 §3a).

        **The delete right reaches the outbox, and the order is forced.** §3a: "An
        act that **deletes** an ADR-0130 record — its per-record delete or its
        clear (ADR-0130 §9), which serve ADR-0004 §6's delete right and are not
        dismissals — withdraws the record's outbox entry **first**, and deletes the
        record only after the withdrawal has committed. No lane may delete a record
        whose entry it has not already withdrawn."

        Deleting the record first would leave an entry whose record is gone: not
        departing, not expired, undetectably stale, and delivered on the next poll
        — after the user had deleted the thing it was about. Withdrawing first
        cannot produce that, and the one state a crash between them leaves is an
        actionable record with no entry, which is exactly the incomplete-handoff
        case §3b's reconciliation already repairs.

        Args:
            record_id: The ADR-0130 record whose entry is given up.

        Returns:
            Whether the withdrawal **dismissed an actionable record**. That is what
            a dismissal surface can report as its own answer, and it is why the
            engine's dismissal goes through here rather than beside it: the entry is
            marked departing *before* the record is dismissed, so a failure at any
            step leaves an entry no poll can select rather than a dismissed record
            with a deliverable entry beside it.
        """
        ...

    async def recover_leases(self) -> None:
        """Void every lease inherited from the process before this one (§3).

        ADR-0131 §3: "A hub restart voids every lease… no lease survives the
        process that granted it." **This is unconditional and the caller owns the
        once-ness**, because §3 says a restart voids and deliberately does not say
        who detects a restart — an implementation that guarded itself would be
        guarding per *object*, and a second outbox object over one database in one
        live process would still strip a lease from the device holding it.

        :meth:`Engine.start` is the caller, once per engine: the engine is what the
        hub starts, so the chain reads instance lock → one hub process → one
        composition root → one engine → one recovery. Calling it a second time on a
        live hub would take a live lease and put one entry in two devices' hands,
        which §3 forbids outright.
        """
        ...

    async def reconcile(self) -> None:
        """Make the outbox and the ADR-0130 records agree, in both directions.

        Runs to completion **before any poll is served** (ADR-0131 §3b), and is a
        repair rather than the trigger a notification relies on. It is *repeatable*
        — it touches no lease, which is why :meth:`recover_leases` is a separate
        step rather than this method's first act.
        """
        ...

    async def wait_for_arrival(
        self,
        timeout: timedelta,  # noqa: ASYNC109 — the caller's own poll budget, not a deadline this seam owns (ADR-0029 §4)
    ) -> bool:
        """Park until an entry may be available, or until ``timeout`` elapses.

        **What it reports is a hint about arrivals and a fact about the timeout**,
        and the second half is load-bearing. A wake is only ever a hint: a caller
        that misses one falls back on its own deadline and re-reads, so correctness
        rests on the re-read. But an implementation that returned *without* waiting
        would turn the caller's loop into a spin — re-reading, finding nothing, and
        asking to wait again, forever where the caller's clock is injected and does
        not move. Reporting the timeout is what lets the caller end the poll on the
        one answer it can trust rather than on a deadline the wait never advanced
        towards.

        Args:
            timeout: How long to wait at most.

        Returns:
            Whether an arrival may have happened. ``False`` means the wait ran out,
            and a caller may take that as its budget being spent.
        """
        ...


__all__ = ["DeliveryOutbox"]
