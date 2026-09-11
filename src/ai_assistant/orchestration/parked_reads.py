"""Answering the question a parked read left standing (ADR-0244 §§5-7, §10, §11).

The operations behind :meth:`~ai_assistant.core.protocols.AssistantEngine.resume`
for a parked read, :meth:`~ai_assistant.core.protocols.AssistantEngine.cancel_read`,
and the read half of :meth:`~ai_assistant.core.protocols.AssistantEngine.pending_confirmations`.
It is :mod:`ai_assistant.orchestration.recipient_grants`' shape one decision over:
`orchestration` owns the sequence, `permissions` owns the gate and the store, and
``core`` transcribes.

**Five contracts and one of them is another stage.** The store is reached through
:class:`~ai_assistant.core.protocols.ParkedReads`, the conversation's budget through
:class:`~ai_assistant.core.protocols.ConversationStore`, and the binder, the policy,
the trail and the searcher through the
:class:`~ai_assistant.orchestration.reads.SearchServicer` this deployment already
wired — never through second holders of its own. That is ADR-0244 §16's "no second
route, no second servicing site, no second asker" kept by construction: there is one
object in this process that can send a search, and this module asks it.

**It composes nothing and captures nothing.** ADR-0244 §8's continuation is a *turn*,
assembled by :meth:`~ai_assistant.orchestration.loop.LearningLoop.resumed_read` and
captured by the engine's own capture stage; what this module produces is the answer's
disposition and the records the read minted. Splitting it there is what keeps the
gate, the ruling and the send in one place and the turn in another.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ai_assistant.core.clock import checked_clock
from ai_assistant.core.types import (
    ActionRequest,
    ParkedRead,
    ParkedReadDisposition,
    PermissionOutcome,
    ReadAnswerOutcome,
    ReadCancellation,
    ToolCall,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime

    from ai_assistant.core.protocols import ConversationStore, ParkedReads
    from ai_assistant.core.types import MemoryRecord
    from ai_assistant.orchestration.reads import SearchServicer


@dataclass(frozen=True, slots=True)
class AnsweredRead:
    """What became of one answer to a parked read (ADR-0244 §6, §9).

    Attributes:
        outcome: Which of ADR-0244 §9's seven members this answer reached. **Where
            more than one is true the first in that enumeration's declared order is
            the one carried**, which the sequence below produces by construction: each
            clause is taken in §6's order and returns on its own failure.
        park: The park as it stood **when the answer was taken** — carrying its
            ``goal`` and ``plan`` where this call won the gate, so the continuation
            composes over the parked turn's own two members without a second read of a
            row the settlement has since cleared. ``None`` where no park was found.
        records: What the dispatched read minted, in the order it minted them. Empty on
            every member but :attr:`ReadAnswerOutcome.DISPATCHED`, and empty on that one
            too where the read was refused, expired, interrupted or returned nothing —
            on which the turn still composes (ADR-0244 §8).
    """

    outcome: ReadAnswerOutcome
    park: ParkedRead | None = None
    records: tuple[MemoryRecord, ...] = ()


@dataclass(slots=True)
class _Dispatches:
    """The reads this process has dispatched and not finished, by park id.

    **Process-scoped and deliberately not durable** (ADR-0244 §11). A cancellation
    reaches only a dispatch running in the process that received it: there is no
    durable cancellation record, no cross-process signal and no cancellation queue,
    which is honest under ADR-0043's one-resident-process-per-data-directory posture
    rather than in spite of it.
    """

    running: dict[str, object] = field(default_factory=dict)


class ParkedReadOperations:
    """The park's enumeration, its answer and its cancellation, over one store.

    **The store may be absent**, and that is ADR-0244 §18's lane order rather than a
    degradation: Lane 1 lands the contract, the suite, the fake and this consumer, and
    Lane 2 wires ``SqliteParkedReads`` into the composition root. With no store no park
    is ever written (:meth:`~ai_assistant.orchestration.reads.SearchServicer._park`),
    so every operation here answers what is true of a deployment holding no questions:
    an empty enumeration, and a token that names nothing.
    """

    def __init__(
        self,
        *,
        store: ParkedReads | None,
        conversations: ConversationStore,
        search: SearchServicer | None,
        max_calls: int,
        clock: Callable[[], datetime],
    ) -> None:
        """Wire the operations from the store, the conversation index and the servicer.

        Args:
            store: Where the questions live, or ``None`` where this deployment wired
                none. **Passed rather than defaulted**, so a composition root states the
                absence instead of inheriting it.
            conversations: The durable conversation index — the **same instance** the
                capture stage and the footing hold, which is the composition-root
                single-instance obligation ADR-0238 §8 already states: the counter and
                the flag are that store's own row state, and a second store over the
                same rows would answer about a draw this one never took.
            search: The one object in this process that can send a search, or ``None``
                where this deployment connected no search account. An answer that
                reached the dispatch with none is ``UNAVAILABLE_NOW``: nothing was ruled
                and nothing was dispatched, which is true of what this deployment can
                do.
            max_calls: ``Settings.search_calls_per_conversation``, passed rather than
                read, because ADR-0238 §8 puts "every judgement about what a bound is"
                in ``orchestration``. A bound of ``0`` is that section's "no search is
                serviced in any conversation", which ADR-0244 §6's clause 2 reads as a
                refusal of the answer.
            clock: Reads the instant every comparison and settlement here carries.
                **Guarded at the moment it is stored** (ADR-0026 §2), so every reading
                below is aware, UTC and localizable.
        """
        self._store = store
        self._conversations = conversations
        self._search = search
        self._max_calls = max_calls
        self._clock = checked_clock(clock, owner="ParkedReadOperations")
        self._dispatches = _Dispatches()

    # --- the enumeration (ADR-0244 §5) --------------------------------------

    async def outstanding(self) -> tuple[ParkedRead, ...]:
        """Every open park that can still be answered, expiring the ones that cannot.

        **The enumeration settles an expired park rather than offering it** (ADR-0244
        §5), so ``pending_confirmations`` never offers a question that cannot be
        answered and the settlement happens **at the read** rather than in a sweep of
        its own. **It settles nothing else**: an ``OPEN`` park that has not expired is
        offered, never closed, whatever any other record says — §6's one-gate clause —
        and no lane adds a background task, a reclaim pass or a scheduler.

        **Expiry is the one settlement no party takes for itself, and it can take
        nothing from anyone** (ADR-0244 §6): §6's clause 1 refuses to answer an expired
        park at all, so there is no live answerer for this settlement to race.

        Returns:
            The open, unexpired parks, oldest first.

        Raises:
            AssistantError: If the store could not be read or an expiry could not be
                written.
        """
        store = self._store
        if store is None:
            return ()
        now = self._clock()
        live: list[ParkedRead] = []
        for park in await store.outstanding():
            if park.expires_at <= now:
                await store.settle(park.id, disposition=ParkedReadDisposition.EXPIRED, at=now)
                continue
            live.append(park)
        return tuple(live)

    async def get(self, park_id: str) -> ParkedRead | None:
        """The park under that id, or ``None``.

        Args:
            park_id: The park's own identifier.

        Returns:
            The park, whatever its disposition, or ``None``.

        Raises:
            AssistantError: If the store could not be read.
        """
        return None if self._store is None else await self._store.get(park_id)

    async def park_of_decision(self, decision_id: str) -> ParkedRead | None:
        """The park naming that decision, whatever its disposition (ADR-0244 §5).

        What ``grantable_decisions``' eighth condition is decided from, **through the
        contract and never from a concrete store** (golden rule 1), and what makes the
        exclusion survive a restart: the row does, so this read does.

        Args:
            decision_id: The recorded ``CONFIRM`` to look for.

        Returns:
            The park naming it, or ``None`` where none does.

        Raises:
            AssistantError: If the store could not be read.
        """
        return None if self._store is None else await self._store.park_of_decision(decision_id)

    async def drop_for_conversation(self, conversation_id: str) -> int:
        """Remove every park of that conversation (ADR-0244 §3, §15).

        The conversation's deletion sequence's route, reached **through the Protocol**
        by the capture/lifecycle stage — "the one layer that legitimately holds both
        handles by injection" (ADR-0074 §9). It is idempotent, and it adds no
        cross-store reconciliation walk, tombstone, stamp or second lifecycle.

        Args:
            conversation_id: The conversation whose parks to remove.

        Returns:
            How many rows went, and ``0`` where this deployment wired no store.

        Raises:
            AssistantError: If the store could not be written.
        """
        if self._store is None:
            return 0
        return await self._store.drop_for_conversation(conversation_id)

    # --- the answer (ADR-0244 §6, §7, §10) ----------------------------------

    async def answer(  # noqa: C901, PLR0911, PLR0912 — one exit per clause ADR-0244 §6 states, in §6's own order, so that §9's "the first member in the declared order" holds by construction rather than by a fold; collapsing any pair would report one clause's refusal under another's member
        self, park_id: str, *, approved: bool
    ) -> AnsweredRead:
        """Take ADR-0244 §6's six establishments and dispatch where every one holds.

        **In §6's order, and the read is dispatched only where every one of them
        holds.** Each clause returns on its own failure, which is what makes ADR-0244
        §9's "where more than one member is true, the first in the order above is the
        one carried" a property of the sequence rather than of a comparison.

        **The gate is the park's compare-and-swap, and it is taken before the policy is
        asked** (clause 5 before clause 6). That order is the decision rather than an
        accident: recording first and settling after leaves a window in which a second
        party sees an answered decision beside an open park and has to guess whether the
        first is still running — and any rule it follows there either strands the park or
        takes the settlement away from a live dispatcher, so that an approved read
        dispatches **zero** times. Settling first has no such window.

        **What the order costs is stated rather than hidden.** A process that dies
        between clause 5 and clause 6 leaves a park ``APPROVED`` with no resolution
        recorded and nothing sent: the answer was accepted, the question is closed, and
        the lookup did not happen. **Nothing re-opens it** — the recourse is to ask
        again — and nothing is unrecorded in ADR-0004 §7's sense, because no decision
        was taken: the policy was never asked. A bounded loss of one answer, preferred
        to the unbounded hazard the other order carries.

        **``admit_search`` is not called and no second call is drawn** (clause 2). The
        conversation's call was admitted before the ruling and is consumed whatever the
        outcome, and parking does not refund it (ADR-0238 §8); what clause 2 takes is a
        *read* of the draw.

        **Nothing else is consulted for authority** (ADR-0244 §6, §16). No standing
        recipient grant is read, established, extended or implied; ``trust_of`` is not
        asked again and no destination's recorded trust is written; and no threshold,
        floor or ``Settings`` value is relaxed to reach the ``ALLOW``. **The approval is
        the authority**, and it is ADR-0148 §3's route (a) — a recorded resolution of a
        ``CONFIRM`` about this request — and no other.

        Args:
            park_id: The park the presented token names.
            approved: The user's own answer, relayed unchanged.

        Returns:
            The member, the park as it stood at the answer, and what the read minted.

        Raises:
            AssistantError: If a store or the trail could not be read. A **refusal** is
                returned rather than raised (ADR-0244 §9); a fault is not a refusal.
        """
        store = self._store
        search = self._search
        if store is None or search is None:
            # No store holds questions, or no account can answer one. Nothing was ruled
            # and nothing was dispatched, which is what `UNAVAILABLE_NOW` says.
            return AnsweredRead(ReadAnswerOutcome.UNAVAILABLE_NOW)
        now = self._clock()
        # **Clause 1 — the park.**
        park = await store.get(park_id)
        if park is None:
            # The only member that removes a row is `drop_for_conversation`, so a park
            # the store no longer holds is one whose conversation was deleted — which is
            # `UNAVAILABLE_NOW`'s own first limb read from this end.
            return AnsweredRead(ReadAnswerOutcome.UNAVAILABLE_NOW)
        if park.disposition is not ParkedReadDisposition.OPEN:
            # **A duplicate answer dispatches nothing and says so** (ADR-0244 §6): it
            # consults no policy, opens no channel, records nothing and mints nothing.
            # `EXPIRED` is stated over the **disposition** rather than over which call
            # discovered it, so a park an enumeration settled reads the same to the user
            # as one this answer settled.
            return AnsweredRead(
                ReadAnswerOutcome.EXPIRED
                if park.disposition is ParkedReadDisposition.EXPIRED
                else ReadAnswerOutcome.ALREADY_SETTLED,
                park,
            )
        if park.expires_at <= now:
            # ADR-0059 §1's comparison. Settled here and refused as stale, which is safe
            # for §6's stated reason: clause 1 refuses to answer such a park at all, so
            # there is no live answerer for the settlement to race.
            await store.settle(park.id, disposition=ParkedReadDisposition.EXPIRED, at=now)
            return AnsweredRead(ReadAnswerOutcome.EXPIRED, park)
        # **Clause 2 — the conversation.**
        draw = await self._conversations.search_draw(park.conversation_id)
        if draw is None or self._max_calls == 0:
            # `search_draw` answers `None` for an id that names nothing and for a
            # conversation stamped deleted (ADR-0238 §14), and a bound of `0` is that
            # decision's "no search is serviced in any conversation".
            return AnsweredRead(ReadAnswerOutcome.UNAVAILABLE_NOW, park)
        # **Clause 3 — the decision.**
        confirmed = await search.recorded(park.decision_id)
        if (
            confirmed is None
            or confirmed.ruling.outcome is not PermissionOutcome.CONFIRM
            or (confirmed.expires_at is not None and confirmed.expires_at <= now)
        ):
            # Each of these says the recorded operation is no longer the one the
            # question was about, which is what `OPERATION_CHANGED` names. **The park
            # stays `OPEN`**, exactly as it does when the subject or the binding fails:
            # these clauses precede the gate, so nothing has been spent. Every limb is
            # unreachable by construction on a park this process wrote — the trail is
            # append-only, the ruling was a `CONFIRM` when the park was written, and the
            # decision carries the park's own deadline, which clause 1 has already
            # compared — and each is stated because the types admit it.
            return AnsweredRead(ReadAnswerOutcome.OPERATION_CHANGED, park)
        # **Clause 4 — the subject, and the binding derived afresh.**
        parameters = park.parameters
        if parameters is None:  # pragma: no cover — an OPEN park carries its parameters
            # `ParkedRead`'s own validator refuses an open park with no parameters, so
            # this is unconstructable for a conforming record and is written for the type
            # checker rather than for a caller.
            return AnsweredRead(ReadAnswerOutcome.OPERATION_CHANGED, park)
        bound = await search.rebound(confirmed, parameters)
        if bound is None:
            return AnsweredRead(ReadAnswerOutcome.OPERATION_CHANGED, park)
        request = ActionRequest(
            tool=bound.tool, parameters=bound.parameters, egress_binding=bound.binding
        )
        if (
            request.parameters_digest != confirmed.parameters_digest
            or request.tool != confirmed.tool
            or request.step_id is not None
            or request.execution_id is not None
        ):
            # **The three facts a `CONFIRM` fixes about its subject** (ADR-0021 §1,
            # ADR-0044 §1), checked against the recorded decision rather than trusted
            # from the store. `PermissionDecision.authorises` is **not** this check and
            # cannot be: it is `True` only of an `ALLOW`, so it is `False` of every
            # `CONFIRM` by construction, and it is applied where it belongs — to the
            # **resolving** decision, by `ToolCall`'s own validator and again at the
            # seam. A lane collapsing them would refuse every parked read.
            return AnsweredRead(ReadAnswerOutcome.OPERATION_CHANGED, park)
        # **Clause 5 — the gate.**
        settled = ParkedReadDisposition.APPROVED if approved else ParkedReadDisposition.DENIED
        if not await store.settle(park.id, disposition=settled, at=now):
            # **A caller answered `False` has not taken the park's one answer**: it
            # rules nothing, records nothing, sends nothing. That is what makes "one
            # answer, at most one dispatch" a property of one atomic write rather than
            # of an agreement between several readers.
            return AnsweredRead(ReadAnswerOutcome.ALREADY_SETTLED, park)
        # **Clause 6 — the ruling, recorded whatever it is.**
        answer = await search.ruled_on_answer(confirmed, approved=approved)
        if answer is None:
            # A refused append, returned and not raised (ADR-0244 §6, §9): the answer is
            # **not** recorded, the park stays spent, and nothing is dispatched.
            return AnsweredRead(ReadAnswerOutcome.OPERATION_CHANGED, park)
        if not approved:
            # The recorded answer is the `DENY` the user asked for, and the outcome is
            # `DECLINED` — `turn` and `reply` both `None`, ADR-0170 §4's second shape
            # exactly (ADR-0244 §10). Nothing is sent, no channel is opened, no claim is
            # appended, and no minted record exists.
            return AnsweredRead(ReadAnswerOutcome.DECLINED, park)
        if answer.ruling.outcome is not PermissionOutcome.ALLOW:
            # **Reserved for an approving answer the policy refused** (ADR-0244 §6). The
            # ruling **is** recorded — ADR-0004 §7's reason — nothing was dispatched, and
            # the park is spent either way.
            return AnsweredRead(ReadAnswerOutcome.AUTHORITY_CHANGED, park)
        records = await self._dispatched(park, ToolCall(request=request, decision=answer))
        return AnsweredRead(ReadAnswerOutcome.DISPATCHED, park, records)

    async def _dispatched(self, park: ParkedRead, call: ToolCall) -> tuple[MemoryRecord, ...]:
        """Run the one call, registered so that a cancellation can reach it.

        **The dispatch is one call** (ADR-0244 §7). ``settle`` is the gate and it was
        taken before the policy was asked, so an approval that raced another, a token
        presented twice, a restart between the answer and the send, and two engines over
        one data directory can none of them produce a second call.

        **The records are ADR-0231 §10's, unchanged**, and they are supply and never a
        store write (ADR-0231 §16): they carry their provenance and their attestation
        exactly as they do on an unparked servicing, and they resolve in no store. A
        park's approval changes **where a search happens in time** and changes nothing
        about what a search *is*.

        **A refusal yields no records and is not an error** (ADR-0244 §8). Where the
        dispatched read was refused, expired, interrupted or returned nothing the turn
        still composes, and ADR-0242 §6's carrier gives the composing stage its member
        exactly as it does on any other turn.

        **Registered for the length of the send and no longer** (ADR-0244 §11). The
        entry is what :meth:`cancel` reaches, and the ``finally`` is what keeps a
        finished dispatch from answering ``INTERRUPTED`` to a cancellation that arrived
        after the outcome was established — "a cancellation delivered after the outcome
        was established changes no row".

        Args:
            park: The park this dispatch answers, spent and ``APPROVED``.
            call: The call over the resolving ``ALLOW``.

        Returns:
            What the read minted, empty on a refusal.
        """
        self._dispatches.running[park.id] = asyncio.current_task()
        try:
            outcome = await self._search.dispatch(call)  # type: ignore[union-attr]  # `answer` returned early where `_search` is None
        finally:
            self._dispatches.running.pop(park.id, None)
        return () if outcome.refusal is not None else outcome.records

    # --- the cancellation (ADR-0244 §11) ------------------------------------

    async def cancel(self, park_id: str) -> ReadCancellation:
        """Withdraw the question, or interrupt the read it dispatched.

        **Cancelling an ``OPEN`` park withdraws the question and records no answer.**
        ``ActionPolicy.resolve`` is not called, no ruling is recorded, and the decision
        on the trail stays the unresolved ``CONFIRM`` it was — the whole difference from
        a denial. The park is settled ``CANCELLED`` and its content is cleared in the
        same step, so a cancellation and a concurrent answer cannot both take effect.

        **It takes §6's gate and takes it the same way**: a cancellation that lost the
        compare-and-swap answers ``NOTHING_TO_CANCEL`` where the answer is already
        running or done, and an answer that lost it returns ``ALREADY_SETTLED``.
        **Neither party acts on a park the other took.**

        **Cancelling a dispatched read cancels the task running it**, and the seam's
        accounting is ADR-0241 §7's, unchanged: the claim is completed before the
        cancellation re-raises, with ``interrupted_outcome`` and an ``UNKNOWN`` cost, and
        the channel is released. **The park stays ``APPROVED`` and is not re-opened**:
        no caller assumes the query did not leave.

        Args:
            park_id: The park the presented token names.

        Returns:
            Which of ADR-0244 §11's three states this call reached.

        Raises:
            AssistantError: If the store could not be read or written.
        """
        store = self._store
        if store is None:
            return ReadCancellation.NOTHING_TO_CANCEL
        now = self._clock()
        park = await store.get(park_id)
        if park is not None and park.disposition is ParkedReadDisposition.OPEN:
            if await store.settle(park.id, disposition=ParkedReadDisposition.CANCELLED, at=now):
                return ReadCancellation.WITHDRAWN
            # Lost the gate to a concurrent answer, which is now running or done.
            return self._interrupt(park_id)
        return self._interrupt(park_id)

    def _interrupt(self, park_id: str) -> ReadCancellation:
        """Cancel a dispatch this process is running, or answer that there is none.

        **A cancellation reaches only a dispatch running in the process that received
        it** (ADR-0244 §11). A park settled ``APPROVED`` whose dispatch is running
        elsewhere answers ``NOTHING_TO_CANCEL``, which is true of what this process can
        do; §20 defers the general case by name to #2173's L7 obligation.

        Args:
            park_id: The park whose dispatch to reach.

        Returns:
            ``INTERRUPTED`` where a running dispatch was cancelled, ``NOTHING_TO_CANCEL``
            otherwise.
        """
        running = self._dispatches.running.get(park_id)
        if isinstance(running, asyncio.Task):
            running.cancel()
            return ReadCancellation.INTERRUPTED
        return ReadCancellation.NOTHING_TO_CANCEL


__all__ = ["AnsweredRead", "ParkedReadOperations"]
