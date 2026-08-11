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

    from ai_assistant.core.types import NotificationDelivery


@runtime_checkable
class DeliveryOutbox(Protocol):
    """The transitions :meth:`Engine.next_notification` drives (ADR-0131 §2a, §3).

    Every method raises
    :class:`~ai_assistant.core.errors.NotificationOutboxError` for a store fault,
    which is the failure ADR-0131 §4 declares on ``next_notification`` for exactly
    this reason.
    """

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

    async def reconcile(self) -> None:
        """Make the outbox and the ADR-0130 records agree, in both directions.

        Runs to completion **before any poll is served** (ADR-0131 §3b), and is a
        repair rather than the trigger a notification relies on.
        """
        ...

    async def wait_for_arrival(self, timeout: timedelta) -> None:  # noqa: ASYNC109 — the caller's own poll budget, not a deadline this seam owns (ADR-0029 §4)
        """Park until an entry may be available, or until ``timeout`` elapses.

        **A hint and never a guarantee.** A caller that misses a wake falls back on
        its own deadline and re-reads, so correctness rests on the re-read and this
        buys latency alone. That is what keeps a conforming implementation free to
        be a plain sleep.

        Args:
            timeout: How long to wait at most.
        """
        ...


__all__ = ["DeliveryOutbox"]
