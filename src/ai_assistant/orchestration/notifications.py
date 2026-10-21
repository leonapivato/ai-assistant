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

**Each ruling is handed the policy of its person's zone** (ADR-0338 §3:6, as §13 reads
it over ADR-0130 §6:4): quiet windows are read in the zone of the person a notification
is for, and in ``Settings.timezone`` where theirs is empty. A policy's zone stays a
construction-time property of the instance, as ``NotificationPolicy`` requires, so what
varies is *which* instance a ruling is handed: :class:`RulingPolicy` reads the zone just
before each ruling and picks the hub's policy or one built for that zone. Both ruling
paths, this stage's and the engine's reconsideration, pick through it.

Nothing concrete is imported: the store, the policy and the outbox all arrive by
injection and are seen only through their Protocols (CLAUDE.md golden rule 1).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from ai_assistant.core.errors import NotificationStoreError, PersonModelStoreError
from ai_assistant.core.types import OWNER_PERSON_ID, NotificationDispositionKind
from ai_assistant.orchestration.person_block import person_zone

if TYPE_CHECKING:
    from collections.abc import Callable
    from zoneinfo import ZoneInfo

    from ai_assistant.core.protocols import (
        NotificationOutbox,
        NotificationPolicy,
        NotificationStore,
        PersonModelStore,
    )
    from ai_assistant.core.types import NotificationCandidate, NotificationDisposition

_log = structlog.get_logger(__name__)

#: Builds the policy whose quiet windows are read in one zone: the composition root's,
#: over the concrete policy it holds (ADR-0338 §3:6).
type PolicyForZone = Callable[[ZoneInfo], NotificationPolicy]


class RulingPolicy:
    """The policy one ruling is handed, in its person's zone (ADR-0338 §3:6).

    **Whose notification it is.** A candidate names no person, and the person-model store
    holds one, the owner (§2:1), so every notification is the owner's: a producer notices
    for the user, from a source the owner connected (§2:2's third limb). A second person's
    notifications wait on the members decision (#691), which is where a candidate would
    gain whose it is.

    **Read just before each ruling, never cached**, so a zone the person changes governs
    the next ruling with no restart. A record already held keeps the ``reconsider_at`` its
    ruling computed in the zone then set, and is re-ruled in the new one when it falls due:
    no setting write re-rules on a zone (ADR-0130 §6:7 names three standing settings, and
    a profile field is none of them).

    **A store fault rules nothing.** Where the person-model store cannot be read,
    :meth:`pick` raises and the caller hands no policy to the notification store, so no
    record is written or changed and no unit of budget is spent. It raises the
    ``NotificationStoreError`` every ruling path already declares, chained to the
    person-model store's fault, so ``NotificationWriter``'s failure surface is unchanged:
    the ruling's standing state could not be read, and nothing was ruled. That is the one reading
    that cannot move the person's night: the hub's zone would put their quiet window at
    the wrong hours wherever the two differ, and a guess at their zone is no better. The
    held record stays due and the next reconsideration run tries it again, which ADR-0130
    §5 rules is no fault; a fresh candidate is offered again on the producer's next pass,
    which §8 rules is the normal case.

    **Inert unwired.** With no person-model store, or no factory, every ruling is handed
    the hub's policy, exactly as before the person model.
    """

    def __init__(
        self,
        *,
        default: NotificationPolicy,
        policy_for: PolicyForZone | None = None,
        people: PersonModelStore | None = None,
    ) -> None:
        """Wire the pick to the hub's policy, the factory and the person-model store.

        Args:
            default: The policy over ``Settings.timezone``, handed to every ruling whose
                person sets no zone, and to every ruling where either of the other two is
                ``None``.
            policy_for: Builds the policy for a person's zone, or ``None``.
            people: The person-model store the zone is read from, or ``None`` where the
                person model is off (``Settings.person_model``).
        """
        self._default = default
        self._policy_for = policy_for
        self._people = people

    @property
    def default(self) -> NotificationPolicy:
        """The policy over ``Settings.timezone``."""
        return self._default

    async def pick(self) -> NotificationPolicy:
        """The policy the next ruling is handed: its person's zone, or the hub's.

        Returns:
            A policy built for the owner's zone where their profile sets one that
            resolves, and the hub's policy otherwise, or where nothing is wired.

        Raises:
            NotificationStoreError: If the person-model store cannot be read, chained to
                its ``PersonModelStoreError``. Nothing has been ruled, and the caller
                rules nothing.
        """
        if self._people is None or self._policy_for is None:
            return self._default
        try:
            model = await self._people.read(OWNER_PERSON_ID)
        except PersonModelStoreError as exc:
            _log.warning("notification_zone_unread", stage="notifications", reason="store_fault")
            msg = (
                "the zone the quiet windows are read in could not be read from the "
                "person-model store, so nothing was ruled (ADR-0338 §3:6)"
            )
            raise NotificationStoreError(msg) from exc
        zone = person_zone(None if model is None else model.profile, stage="notifications")
        return self._default if zone is None else self._policy_for(zone)


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
    what this holds is the policy the store is handed per call, picked per call in
    the zone of the person the notification is for (:class:`RulingPolicy`). It adds
    exactly one thing of its own — ADR-0131 §3b's live handoff, on the way out.
    """

    def __init__(
        self,
        *,
        store: NotificationStore,
        policy: NotificationPolicy,
        outbox: NotificationOutbox | None,
        policy_for: PolicyForZone | None = None,
        people: PersonModelStore | None = None,
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
            policy_for: Builds the policy for a person's zone (ADR-0338 §3:6), or
                ``None``, where every ruling is handed ``policy``.
            people: The person-model store the owner's zone is read from before each
                ruling, or ``None`` where the person model is off, where every ruling
                is handed ``policy``.
        """
        self._store = store
        self._policies = RulingPolicy(default=policy, policy_for=policy_for, people=people)
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
            NotificationStoreError: If the store cannot be read or written, or the
                owner's zone could not be read from the person-model store
                (:class:`RulingPolicy`). Nothing was ruled and nothing was handed
                off, so the person's night is never read in a zone that is not
                theirs, and the producer's next pass offers the candidate again.
            NotificationOutboxError: If the ruling was ``INTERRUPT`` and the
                enqueue could not commit. The record stays actionable and the next
                reconciliation offers it (ADR-0131 §3b).
        """
        policy = await self._policies.pick()
        ruling = await self._store.admit(candidate, policy=policy)
        await hand_off(self._outbox, ruling, candidate)
        return ruling


__all__ = [
    "NotificationWriteStage",
    "PolicyForZone",
    "RulingPolicy",
    "hand_off",
]
