"""The notification write path: rule through the store, then hand off (ADR-0130 §3).

ADR-0130 §3's seam, concrete at last. Until a producer existed there was nothing
to hold it — ``app/composition.py`` said so in as many words — and the seam
therefore lived only as a Protocol and a canonical fake. ADR-0132's producer is
the first holder, and this module is what it holds.

**Two clauses meet here and neither is this module's own.** ADR-0130 §3 requires
that the duplicate lookup, the cap check, the budget read, the ruling and the
write are **one atomic act in the store**, so this stage's job is to hold the
policy and hand it to the store — never to sequence those steps itself. A writer
that read the state, ruled, and then wrote would satisfy every word of §3 except
the one that matters. And ADR-0131 §3b makes the **live handoff the primary
path**: "When a ``NotificationWriter`` call returns an actionable ``INTERRUPT``
disposition, the same call path calls ``NotificationOutbox.offer`` with that
candidate before it returns to the producer." That call path is this one, and
#964 is the record of it having had nowhere to land until now.

**The handoff is spelled once and used twice** (:func:`hand_off`). The engine's
reconsideration path rules a held record to ``INTERRUPT`` through the same store
and owes the same handoff — §3b: "It is also the reconsideration path's answer
without a second clause… so the same handoff runs" — and two copies of a
four-line rule are two places for it to drift.

Nothing concrete is imported: the store, the policy and the outbox all arrive by
injection and are seen only through their Protocols (CLAUDE.md golden rule 1).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ai_assistant.core.types import NotificationDispositionKind

if TYPE_CHECKING:
    from ai_assistant.core.protocols import (
        NotificationOutbox,
        NotificationPolicy,
        NotificationStore,
    )
    from ai_assistant.core.types import NotificationCandidate, NotificationDisposition


async def hand_off(
    outbox: NotificationOutbox | None,
    ruling: NotificationDisposition,
    candidate: NotificationCandidate,
) -> None:
    """Give a freshly ruled ``INTERRUPT`` to the outbox, now (ADR-0131 §3b).

    **The live handoff is the primary path**, and §3b's startup reconciliation is
    a repair for a handoff that did not happen rather than the trigger a
    notification relies on: "a repair that is also the primary path is a design
    where the ordinary case waits on a restart". Without this call, a hub that
    committed a disposition and spent its budget would leave a device sitting on
    an outstanding long poll receiving nothing — which §3b found on its
    forty-ninth round and forbade.

    **A terminal refusal ends the record, and the outbox does that itself.**
    ``offer`` dismisses on ``TOO_LARGE`` and ``KEY_COLLISION`` (§3b), so no
    refusal leaves an actionable record with no entry and nothing further is owed
    here. The outcome is deliberately not read: acting on it here would be a
    second author of a rule the seam already keeps, sited where a partial copy
    could disagree with it.

    **A ``NotificationOutboxError`` propagates**, which is §3b's own answer: no
    custody transferred, the record stays actionable, and the next reconciliation
    offers it. The failure reaches the caller rather than being absorbed.

    Args:
        outbox: Where a ruled interruption goes, or ``None`` where the deployment
            composed none. **A deployment with no outbox hands off nothing**,
            which is the CLI's case: it serves no poll, so there is nowhere for a
            notification to go.
        ruling: What the store ruled. Anything but ``INTERRUPT`` is left alone —
            a ``DROP`` wrote no record and a ``HOLD`` is not contact.
        candidate: The candidate that was ruled, carried rather than looked up:
            this path already holds both halves, which is why §3b puts the handoff
            here and needs no scheduler to exist.

    Raises:
        NotificationOutboxError: If the enqueue could not commit.
    """
    if outbox is None:
        return
    if ruling.kind is not NotificationDispositionKind.INTERRUPT:
        return
    await outbox.offer(candidate)


class NotificationWriteStage:
    """ADR-0130 §3's one producer seam, over a store, a policy and an outbox.

    Deliberately thin, and the thinness is the contract's shape rather than a
    shortcut: §3 puts the whole ruling inside the store's critical section, so
    what this holds is the policy the store is handed per call. It adds exactly
    one thing of its own — ADR-0131 §3b's live handoff, on the way out.
    """

    def __init__(
        self,
        *,
        store: NotificationStore,
        policy: NotificationPolicy,
        outbox: NotificationOutbox | None,
    ) -> None:
        """Wire the seam to the store it writes through, its policy and its outbox.

        Args:
            store: Where records live and where §3's atomic act happens. It must
                be the store the façade's held-notification surface reads and the
                store the outbox dismisses through — a composition-root obligation
                no type can express (ADR-0028 §4): wired to a second store, a
                ruled notification would be unreadable and undismissable through
                the surfaces the user actually has.
            policy: The deterministic ruling of ADR-0130 §4 and §5. Held here and
                handed to the store per call, never kept by the store: a
                composition that handed the store a policy to keep would be
                describing a different contract.
            outbox: ADR-0131 §3's delivery queue, or ``None`` where the deployment
                composed none. **Required with no default rather than defaulted to
                ``None``**, so a root that means "there is nowhere to deliver"
                says so: an omitted argument and a deliberate absence look
                identical afterwards, and the difference is whether §3b's primary
                path exists at all.
        """
        self._store = store
        self._policy = policy
        self._outbox = outbox

    async def offer(self, candidate: NotificationCandidate) -> NotificationDisposition:
        """Offer one candidate, hand off what it earned, and report the ruling.

        The order is forced and is not an implementation preference: ADR-0131 §3b
        requires the handoff on "the same call path" **before it returns to the
        producer**, so a producer that received an ``INTERRUPT`` has by then
        already had it enqueued, or has learnt that the enqueue failed.

        Args:
            candidate: What the producer noticed.

        Returns:
            The ruling, naming the condition that decided it and the record it
            produced where ADR-0130 §8 required one.

        Raises:
            NotificationStoreError: If the store cannot be read or written.
                Nothing was ruled and nothing was handed off.
            NotificationOutboxError: If the ruling was ``INTERRUPT`` and the
                enqueue could not commit. The record stays actionable and the next
                reconciliation offers it (ADR-0131 §3b).
        """
        ruling = await self._store.admit(candidate, policy=self._policy)
        await hand_off(self._outbox, ruling, candidate)
        return ruling


__all__ = [
    "NotificationWriteStage",
    "hand_off",
]
