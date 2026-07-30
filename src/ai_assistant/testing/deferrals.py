"""A canonical in-memory :class:`~ai_assistant.core.protocols.DeferralStore` fake.

The shared test double for the ``DeferralStore`` contract (ADR-0078 §2), so a
subsystem that depends on the deferred-question queue — `orchestration`'s write
stage and answer path above all — can test against a real, contract-correct store
*without importing a subsystem's internals* (CLAUDE.md golden rule 1). It is
deliberately minimal: one dict of records, one dict of live claim tokens, an
injected clock and an injected token source.

It honours the whole contract, including the parts a dict gets for free only if
they are written down: the atomicity of an admission, the two compare-and-sets,
the physical-id refusal, the key's reach, the purge's two anchors and its
``APPLYING`` exclusion, and the rule that no read republishes a claim token.

**Its critical sections really suspend.** Every operation yields to the event loop
inside its exclusion, before reading the state it is about to change. Without
that, a fake backed by a dict would satisfy every concurrency case in the shared
suite by accident — nothing in it ever awaits, so nothing can interleave — and the
suite's compare-and-set clauses would be vacuous against exactly the
implementation they most need to hold for. With it, dropping the lock makes those
cases fail here as they would against a real store.

**Its token source is the same ``secrets``-backed default the production store
carries.** A fake that defaulted to a counter would let a consumer's test pass
against a capability anyone can guess (ADR-0078 §2).
"""

from __future__ import annotations

import asyncio
import contextlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from ai_assistant.core.clock import ClockReadingError, checked_clock
from ai_assistant.core.errors import DeferralIdConflictError, DeferralStoreError
from ai_assistant.core.types import (
    TERMINAL_DEFERRAL_STATES,
    DeferralAdmission,
    DeferralAdmissionOutcome,
    DeferralClaim,
    DeferralState,
    DeferredProposal,
    describe_untrusted,
)
from ai_assistant.testing.cancellation import SuspendableResource

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Iterable

    from ai_assistant.core.clock import Clock
    from ai_assistant.core.types import MemoryDecision, MemoryUpdateProposal
    from ai_assistant.testing.cancellation import LoopSuspension, ResourceLog

#: One past the largest value a paging argument accepts — the signed 64-bit
#: ceiling a SQLite bind parameter tops out at (ADR-0073 §2). Duplicated from the
#: production store rather than shared, exactly as ``MemoryStore``'s bound is:
#: ``ai_assistant.testing`` may not import a subsystem (golden rule 1), and a fake
#: looser than the contract would certify consumers a real store rejects.
_PAGE_BOUND = 2**63

#: How long a question stays answerable when nobody injects a lifetime (ADR-0078
#: §6). **Finite**, and deliberately ``episode_retention``'s own horizon: a
#: deferred question is about a belief, and for an observed one the evidence is
#: episodes on that clock. ``None`` means "ask me forever" and is the user's
#: deliberate choice.
_DEFAULT_DEFERRAL_TTL = timedelta(days=30)

#: The most answerable questions the queue holds (ADR-0078 §7). Strictly
#: positive: a cap of zero refuses every question while the system reports health.
#: Matches :meth:`FakeDeferralStore.pending`'s bounded default, so the whole
#: answerable queue fits one page.
_DEFAULT_QUEUE_LIMIT = 50

#: The bounded default both enumerations use (ADR-0073 §2, §8).
_DEFAULT_PAGE_LIMIT = 50

#: How many times :meth:`FakeDeferralStore.claim` re-draws a token that a live
#: claim already holds before giving up (ADR-0078 §2).
_CLAIM_RETRY_BUDGET = 8

#: Bytes drawn per claim token: 32 bytes is 256 bits, comfortably past ADR-0078
#: §2's 128-bit floor.
_CLAIM_TOKEN_BYTES = 32


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _secret_claim_id() -> str:
    """Draw a cryptographically unpredictable claim token (ADR-0078 §2).

    The **default**, not merely an injectable seam, and that split is the point:
    injection exists for determinism in tests, but injection alone would let a
    composition root wire a counter and satisfy every word of "fresh". So a
    conforming store defaults to this and a caller has to go out of its way to
    replace it.
    """
    return secrets.token_hex(_CLAIM_TOKEN_BYTES)


def _check_page_bound(name: str, value: object, *, floor: int = 0) -> None:
    """Refuse a paging argument that is not an exact ``int`` in ``[floor, 2**63)``.

    Duplicated from the production store rather than shared, for the reason given
    on :data:`_PAGE_BOUND`. **The type is part of the range**: without it this fake
    would slice a list on ``limit=1.5`` where the real store raises out of its
    driver, and two stores disagreeing about a bad argument is the failure
    ADR-0073 §2 exists to stop. ``bool`` is refused with the rest, being an
    ``int`` subclass that is not a page size.

    Raises:
        ValueError: If ``value`` is not an ``int``, is below ``floor``, or is
            beyond the signed 64-bit range.
    """
    if type(value) is not int or not floor <= value < _PAGE_BOUND:
        msg = f"{name} must be an int in [{floor}, 2**63), got {describe_untrusted(value)}"
        raise ValueError(msg)


def _check_tuning(retention: timedelta | None, queue_limit: object) -> None:
    """Refuse a lifetime or a cap the queue cannot work under (ADR-0078 §2, §7).

    The ``_check_tuning`` arrangement ADR-0022 §4a ratified, and for its reason: a
    bad value here disables a stage while the system keeps reporting health, so it
    is refused when the store is built rather than per call. A cap of ``0`` is at
    capacity before its first admission, so every question is refused and the drop
    ADR-0078 exists to end returns in full, by configuration.

    Raises:
        ValueError: If ``retention`` is set and not strictly positive, or
            ``queue_limit`` is not an ``int`` in ``[1, 2**63)``.
    """
    # The type is checked before the comparison, because `None <= timedelta(0)`
    # raises `TypeError` and this documents `ValueError` for a duration it will
    # not accept — whatever is wrong with it.
    if retention is not None and (
        not isinstance(retention, timedelta) or retention <= timedelta(0)
    ):
        described = describe_untrusted(retention)
        msg = f"retention must be a strictly positive timedelta or None, got {described}"
        raise ValueError(msg)
    _check_page_bound("queue_limit", queue_limit, floor=1)


def _transition(row: DeferredProposal, **changes: object) -> DeferredProposal:
    """Apply ``changes`` to ``row`` and **re-run the record's own validator**.

    ``model_copy(update=...)`` deliberately does not revalidate, so a transition
    built with it could persist a record :class:`DeferredProposal` forbids — an
    ``ACCEPTED`` row naming a successor, an ``APPLYING`` one with no
    ``claimed_at``. Revalidating means an illegal transition raises before
    anything is committed rather than leaving a stored record no read should ever
    return. Duplicated in the production store rather than shared, for the reason
    given on :data:`_PAGE_BOUND`.
    """
    return DeferredProposal.model_validate(row.model_copy(update=changes).model_dump())


def _oldest_first(rows: Iterable[DeferredProposal]) -> list[DeferredProposal]:
    """ADR-0078 §7's total order: ``deferred_at`` ascending, ``id`` ascending."""
    return sorted(rows, key=lambda row: (row.deferred_at, row.id))


class FakeDeferralStore:
    """A non-persistent ``DeferralStore`` test double backed by dicts.

    Structurally implements
    :class:`~ai_assistant.core.protocols.DeferralStore`.
    """

    def __init__(
        self,
        *,
        now: Clock = _utcnow,
        retention: timedelta | None = _DEFAULT_DEFERRAL_TTL,
        queue_limit: int = _DEFAULT_QUEUE_LIMIT,
        new_claim_id: Callable[[], str] = _secret_claim_id,
    ) -> None:
        """Create an empty queue.

        Args:
            now: Clock the store stamps and judges deadlines with; injectable for
                deterministic tests. Guarded by
                :func:`~ai_assistant.core.clock.checked_clock` exactly as the real
                store is, because a fake looser than the contract would certify
                consumers the real implementation rejects (ADR-0026 §7).
            retention: How long an admitted question stays answerable. Read
                **once**, here, and stamped onto each record at admission; no
                operation consults it again, which is what keeps a later
                configuration change from reaching back into a question already
                asked (ADR-0078 §2). ``None`` is the deliberate "ask me forever".
            queue_limit: The most answerable questions the queue holds. Strictly
                positive, with no unlimited spelling (ADR-0078 §7).
            new_claim_id: The injected source :meth:`claim` mints its token from.
                Defaults to a ``secrets``-backed draw, which a caller has to go out
                of its way to replace — injection alone would let a counter satisfy
                "fresh" while every interrupted question's id is public (ADR-0078
                §2).

        Raises:
            ValueError: If ``retention`` is set and not strictly positive, or
                ``queue_limit`` is not an ``int`` in ``[1, 2**63)``.
        """
        _check_tuning(retention, queue_limit)
        self._clock = checked_clock(now, owner="FakeDeferralStore")
        self._retention = retention
        self._queue_limit = queue_limit
        self._new_claim_id = new_claim_id
        self._rows: dict[str, DeferredProposal] = {}
        #: Live claim tokens by deferral id. Dropped when a claim resolves or its
        #: row is destroyed, which is what makes uniqueness a statement about
        #: *live* claims rather than about the store's whole history (ADR-0078 §2).
        self._claims: dict[str, str] = {}
        self._resource = SuspendableResource()

    # --- test-side levers ----------------------------------------------------

    def suspend_next_write(self) -> LoopSuspension:
        """Arm the next operation to suspend inside the store's one exclusion.

        What the shared suite's compare-and-set and no-resurrection clauses drive:
        a call held open inside the resource it acquired, so a second caller
        demonstrably queues rather than reaching the state beside it.
        """
        return self._resource.suspend_next()

    @property
    def resource_log(self) -> ResourceLog:
        """When each call was inside the exclusion (the suite's cases read it)."""
        return self._resource.log

    # --- internals -----------------------------------------------------------

    def _now(self) -> datetime:
        """The guarded clock's reading, as the error the real store raises.

        ``DeferralStoreError``, not the raw ``ValueError`` ``core`` raises: a fake
        that leaked it would certify a consumer's error handling against behaviour
        it will never meet in production (ADR-0026 §4).

        Raises:
            DeferralStoreError: If the reading is naive, indeterminate, or outside
                the localizable range.
        """
        try:
            return self._clock()
        except ClockReadingError as exc:
            raise DeferralStoreError(str(exc)) from exc

    @contextlib.asynccontextmanager
    async def _exclusive(self) -> AsyncIterator[None]:
        """Hold the store's one exclusion for the block.

        The suspension inside it is deliberate and load-bearing (see the module
        docstring): it hands the loop back *inside* the exclusion and before the
        body reads anything, so a second operation really has to queue. Remove the
        lock and the shared suite's admission-atomicity, claim, resolve and
        no-resurrection cases fail here rather than passing vacuously.
        """
        async with self._resource.held():
            await asyncio.sleep(0)
            yield

    def _checked_token(self, value: object) -> str:
        """Refuse a token source that did not return a usable identifier.

        The token is a capability, and a blank or non-``str`` one would be stored
        as a key that nothing can present — leaving a claim unresolvable while the
        call reported success. The guard the ``MemoryWriter``'s id factory already
        carries, applied to a second injected source.

        Raises:
            DeferralStoreError: If the source returned anything but a non-blank
                ``str``. Nothing is committed.
        """
        if type(value) is not str or not value.strip():
            msg = f"the claim token source returned an unusable token: {describe_untrusted(value)}"
            raise DeferralStoreError(msg)
        return value.strip()

    def _answerable_count(self, now: datetime) -> int:
        """How many questions count against the cap at ``now`` (ADR-0078 §7).

        The **answerable** queue only: lapsed and resolved rows awaiting a sweep do
        not count, so a queue cannot be held shut by questions nobody can answer.
        """
        return sum(1 for row in self._rows.values() if row.is_answerable_at(now))

    def _speaker_for(self, key: str, now: datetime) -> DeferredProposal | None:
        """The stored question whose key still speaks for ``key`` at ``now``.

        Oldest first, so which row a suppression names is deterministic across
        backends rather than a property of dict ordering.
        """
        matches = (
            row
            for row in self._rows.values()
            if row.proposal.question_key == key and row.speaks_for_its_key_at(now)
        )
        return next(iter(_oldest_first(matches)), None)

    def _validated_parent(
        self, predecessor_id: str | None, successor_to_claim: str | None
    ) -> DeferredProposal | None:
        """Judge the re-deferral exemption, returning the parent it protects.

        ``None`` when there is nothing to protect — either no exemption was
        claimed, or the parent was destroyed by the user mid-apply, in which case
        the successor is admitted as an **ordinary** question and nothing raises:
        the exemption exists to protect a waiting parent and there is none
        (ADR-0078 §2).

        Raises:
            DeferralStoreError: If the parent is alive and the exemption does not
                hold — a token that does not claim it, a parent no longer
                ``APPLYING``, or one that already names a successor. A live parent
                with a bad token is a caller fault that would otherwise leave a
                real answer with no ``successor_id`` to name and a
                ``resolve(REDEFERRED)`` that fails forever, so it is surfaced
                rather than absorbed.
        """
        if predecessor_id is None:
            return None
        parent = self._rows.get(predecessor_id)
        if parent is None:
            return None
        if parent.state is not DeferralState.APPLYING:
            described = describe_untrusted(predecessor_id)
            msg = f"the parent deferral {described} is not APPLYING, so no answer is in flight"
            raise DeferralStoreError(msg)
        if self._claims.get(parent.id) != successor_to_claim:
            described = describe_untrusted(predecessor_id)
            msg = f"the supplied claim token does not claim the parent deferral {described}"
            raise DeferralStoreError(msg)
        if parent.successor_id is not None:
            described = describe_untrusted(predecessor_id)
            msg = f"the parent deferral {described} already names a successor"
            raise DeferralStoreError(msg)
        return parent

    # --- the contract --------------------------------------------------------

    async def defer(
        self,
        *,
        deferral_id: str,
        proposal: MemoryUpdateProposal,
        decision: MemoryDecision,
        predecessor_id: str | None = None,
        successor_to_claim: str | None = None,
    ) -> DeferralAdmission:
        """Admit a question, reporting what happened and which deferral holds it.

        The full contract is on
        :meth:`~ai_assistant.core.protocols.DeferralStore.defer`. What is worth
        saying here is the *order*, because two rules can both fire on one input:
        the exemption is judged first (a bad token against a live parent strands a
        real answer, which is the worst outcome available), then the **physical id**
        (a caller-side minting fault that suppression would hide), then the key.

        Raises:
            DeferralIdConflictError: If ``deferral_id`` names a stored row carrying
                a different question, or one whose key no longer speaks for it.
            DeferralStoreError: If the exemption arguments disagree about being
                present, or the exemption does not hold against a live parent.
            ValueError: If the proposal or the ruling makes the record
                unconstructable; the store is left unchanged.
        """
        if (predecessor_id is None) != (successor_to_claim is None):
            msg = (
                "predecessor_id and successor_to_claim are given together or not at all: "
                "a parent with no token, or a token naming no parent, is a malformed call"
            )
            raise DeferralStoreError(msg)
        now = self._now()
        # Built here, before the store is touched at all, so an inadmissible
        # proposal (a `DataTier.SECRET` one, a ruling that is not `ASK_USER`)
        # leaves the queue unchanged by construction rather than by care.
        # Built with **no** parent link, whatever the caller named. Whether the
        # successor genuinely links is only knowable inside the atomic section — the
        # parent may have been destroyed by the user mid-apply — and ADR-0078 §2 is
        # explicit that a `predecessor_id` naming no stored deferral admits the
        # successor as an ordinary question "linked to nothing". A record carrying a
        # link to a row that no longer exists would claim a lineage nothing can walk,
        # which the surface would then try to resolve and fail.
        candidate = self._admission_record(deferral_id, proposal, decision, now)
        key = proposal.question_key
        async with self._exclusive():
            parent = self._validated_parent(predecessor_id, successor_to_claim)
            linked = (
                candidate if parent is None else _transition(candidate, predecessor_id=parent.id)
            )
            admission = self._admit(linked, key, exempt=parent is not None, now=now)
            if parent is not None and admission.deferral is not None:
                if admission.deferral.id == parent.id:
                    # A successor may not be the question it succeeds. Reachable only
                    # through a caller that re-offered the parent's *own* proposal: the
                    # key then collides with the parent, the suppression names it, and
                    # stamping would leave a row whose `successor_id` is itself — a
                    # `REDEFERRED` resolution that names no answerable question, which is
                    # the silent drop wearing a terminal state that ADR-0078 §9 forbids.
                    # A successor's conflict set differs from its parent's by construction
                    # (§2), so this is the coordinator having failed to build §3's
                    # snapshot; it raises and changes nothing, leaving the parent APPLYING
                    # and reachable through `interrupted`.
                    described = describe_untrusted(parent.id)
                    msg = (
                        f"a successor may not be the question it succeeds: the offered "
                        f"proposal is the same question as the parent deferral {described}"
                    )
                    raise DeferralStoreError(msg)
                self._rows[parent.id] = _transition(parent, successor_id=admission.deferral.id)
            return admission

    def _admission_record(
        self,
        deferral_id: str,
        proposal: MemoryUpdateProposal,
        decision: MemoryDecision,
        now: datetime,
    ) -> DeferredProposal:
        """Build the unlinked ``PENDING`` record this store would admit.

        Everything the store owns comes from the store: ``deferred_at`` from its
        clock, ``retention`` from the lifetime it was constructed with, and
        ``expires_at`` from their sum — with no argument able to change any of the
        three (ADR-0078 §2). The parent link is deliberately absent here and added
        only once a live parent has been validated.
        """
        return DeferredProposal(
            id=deferral_id,
            proposal=proposal,
            decision=decision,
            state=DeferralState.PENDING,
            deferred_at=now,
            retention=self._retention,
            expires_at=self._expiry_from(now),
        )

    def _expiry_from(self, now: datetime) -> datetime | None:
        """The answerability deadline for a question admitted at ``now`` (ADR-0078 §2).

        ``None`` under "ask me forever". Otherwise ``now + retention`` — and where
        that is not a representable instant, the admission is refused with **this
        seam's own error**, rather than letting a raw ``OverflowError`` cross a
        boundary that documents ``DeferralStoreError`` and would escape an adapter's
        ``AssistantError`` handler as a traceback.

        Refused here rather than at construction, and that placement is the
        decision: it is **not a property of the tuning alone**. A five-thousand-year
        lifetime yields a perfectly good deadline in 2026 and an unrepresentable one
        in 7026, so whether it works depends on *when* the question is admitted.
        ADR-0022 §4a's argument for refusing at construction covers values that are
        bad whatever the clock says — a non-positive lifetime, a cap of zero — and
        those are refused there; this one cannot honestly join them.

        Raises:
            DeferralStoreError: If the deadline is not representable. Nothing is
                admitted.
        """
        if self._retention is None:
            return None
        try:
            return now + self._retention
        except (OverflowError, ValueError) as exc:
            msg = (
                f"a question admitted at {now.isoformat()} under a lifetime of "
                f"{self._retention} has no representable deadline: the configured "
                f"deferral lifetime is too large for this clock"
            )
            raise DeferralStoreError(msg) from exc

    def _admit(
        self, candidate: DeferredProposal, key: str, *, exempt: bool, now: datetime
    ) -> DeferralAdmission:
        """Insert, suppress or refuse, inside the caller's exclusion."""
        held = self._rows.get(candidate.id)
        if held is not None:
            if held.proposal.question_key == key and held.speaks_for_its_key_at(now):
                # The one stated exception: an uncertain admission retried under
                # the same id names a question that is still open, so it is the
                # key-idempotent path rather than a minting fault.
                return DeferralAdmission(outcome=DeferralAdmissionOutcome.SUPPRESSED, deferral=held)
            described = describe_untrusted(candidate.id)
            msg = (
                f"the deferral id {described} already names a different question; re-mint and retry"
            )
            raise DeferralIdConflictError(msg)
        speaker = self._speaker_for(key, now)
        if speaker is not None:
            return DeferralAdmission(outcome=DeferralAdmissionOutcome.SUPPRESSED, deferral=speaker)
        if not exempt and self._answerable_count(now) >= self._queue_limit:
            return DeferralAdmission(outcome=DeferralAdmissionOutcome.REFUSED)
        self._rows[candidate.id] = candidate
        return DeferralAdmission(outcome=DeferralAdmissionOutcome.ADMITTED, deferral=candidate)

    async def get(self, deferral_id: str) -> DeferredProposal | None:
        """Return the deferral with ``deferral_id``, or ``None``, in any state."""
        async with self._exclusive():
            return self._rows.get(deferral_id)

    async def claim(self, deferral_id: str) -> DeferralClaim | None:
        """Take an answerable question to ``APPLYING`` and mint its token.

        Raises:
            DeferralStoreError: If the bounded re-draw was exhausted against a
                source that keeps returning a token a live claim already holds, or
                if the source returned an unusable value. The deferral is left
                ``PENDING`` and nothing is committed.
        """
        now = self._now()
        async with self._exclusive():
            row = self._rows.get(deferral_id)
            if row is None or not row.is_answerable_at(now):
                return None
            token = self._mint_claim_token()
            claimed = _transition(row, state=DeferralState.APPLYING, claimed_at=now)
            self._rows[deferral_id] = claimed
            self._claims[deferral_id] = token
            return DeferralClaim(deferral=claimed, claim_id=token)

    def _mint_claim_token(self) -> str:
        """Draw a token no live claim already holds, bounded.

        A duplicate is not a cosmetic clash: two live claims sharing a token lets
        either holder resolve the other's question or spend its successor
        exemption, which is the whole capability collapsing. Uniqueness is
        promised among **live** claims only — closing the historical case would
        need a ledger of every token ever issued, surviving ``delete`` and
        ``clear``, which is storage of exactly what the user asked to destroy.

        Raises:
            DeferralStoreError: If the budget was exhausted, having changed
                nothing.
        """
        live = set(self._claims.values())
        for _ in range(_CLAIM_RETRY_BUDGET):
            token = self._checked_token(self._new_claim_id())
            if token not in live:
                return token
        msg = (
            f"the claim token source returned a token already held by a live claim "
            f"{_CLAIM_RETRY_BUDGET} times; nothing was claimed"
        )
        raise DeferralStoreError(msg)

    async def pending(
        self, *, limit: int = _DEFAULT_PAGE_LIMIT, offset: int = 0
    ) -> list[DeferredProposal]:
        """Enumerate the answerable questions, oldest first.

        Raises:
            ValueError: If either paging argument is not an ``int`` in
                ``[0, 2**63)``.
        """
        return await self._page(DeferralState.PENDING, limit=limit, offset=offset)

    async def interrupted(
        self, *, limit: int = _DEFAULT_PAGE_LIMIT, offset: int = 0
    ) -> list[DeferredProposal]:
        """Enumerate the ``APPLYING`` questions, in :meth:`pending`'s order.

        Raises:
            ValueError: If either paging argument is not an ``int`` in
                ``[0, 2**63)``.
        """
        return await self._page(DeferralState.APPLYING, limit=limit, offset=offset)

    async def _page(
        self, state: DeferralState, *, limit: int, offset: int
    ) -> list[DeferredProposal]:
        """One bounded, totally ordered page of the rows in ``state``.

        The two enumerations are **disjoint** by construction: ``PENDING`` is
        further narrowed to the answerable ones, and ``APPLYING`` is a different
        state, so no row can appear in both — a store that offered an interrupted
        question among the answerable ones would present a claim that cannot be
        taken.

        Raises:
            ValueError: If either paging argument is out of range or the wrong
                type. Refused **before the first await**, so a bad call reaches no
                state at all.
        """
        _check_page_bound("limit", limit)
        _check_page_bound("offset", offset)
        # One clock reading for the whole page (ADR-0073 §8): a row dropping out
        # mid-scan would otherwise shift every subsequent offset.
        now = self._now()
        async with self._exclusive():
            if state is DeferralState.PENDING:
                matches = [row for row in self._rows.values() if row.is_answerable_at(now)]
            else:
                matches = [row for row in self._rows.values() if row.state is state]
            return _oldest_first(matches)[offset : offset + limit]

    async def resolve(
        self,
        deferral_id: str,
        *,
        claim_id: str | None,
        state: DeferralState,
        record_id: str | None = None,
        successor_id: str | None = None,
    ) -> bool:
        """Record a question's outcome, if this call is the one entitled to.

        Raises:
            ValueError: If ``state`` is not terminal, or the payload is malformed
                for it. Refused before any state is read.
            DeferralStoreError: If the store cannot be written.
        """
        _check_terminal_payload(state, record_id, successor_id)
        now = self._now()
        async with self._exclusive():
            row = self._rows.get(deferral_id)
            if row is None or not self._may_resolve(row, claim_id, state, successor_id, now):
                return False
            self._rows[deferral_id] = _transition(
                row,
                state=state,
                answered_at=now,
                outcome_record_id=record_id,
                successor_id=row.successor_id,
            )
            self._claims.pop(deferral_id, None)
            return True

    def _may_resolve(
        self,
        row: DeferredProposal,
        claim_id: str | None,
        state: DeferralState,
        successor_id: str | None,
        now: datetime,
    ) -> bool:
        """Whether this call may record ``state`` on ``row`` (ADR-0078 §2, §9)."""
        if claim_id is None:
            # The one unclaimed transition, and it is subject to the deadline too:
            # a question nobody could answer is not rejectable either, or a lapsed
            # row would become a retained REJECTED key that suppresses the next
            # honest proposal.
            return state is DeferralState.REJECTED and row.is_answerable_at(now)
        if row.state is not DeferralState.APPLYING or self._claims.get(row.id) != claim_id:
            return False
        if state is DeferralState.REDEFERRED:
            # Checked against the successor the store itself stamped, rather than
            # trusting the caller to name the right question.
            return row.successor_id == successor_id
        # A row that raised a successor has one outcome available to it, and it is
        # not this one — the record type forbids a successor on every other
        # terminal state, so recording one here would store a contradiction.
        return row.successor_id is None

    async def delete(self, deferral_id: str) -> bool:
        """Destroy one question unconditionally, whatever its state."""
        async with self._exclusive():
            self._claims.pop(deferral_id, None)
            return self._rows.pop(deferral_id, None) is not None

    async def clear(self) -> int:
        """Destroy every question, whatever its state, and report how many."""
        async with self._exclusive():
            removed = len(self._rows)
            self._rows.clear()
            self._claims.clear()
            return removed

    async def export(self) -> list[DeferredProposal]:
        """Return every stored question, in :meth:`pending`'s total order.

        Every state, lapsed and terminal alike — the content is the user's. No
        claim token appears here or on any other read.
        """
        async with self._exclusive():
            return _oldest_first(self._rows.values())

    async def purge(self) -> int:
        """Sweep the rows whose own stamped deadline has passed, and report how many.

        Never an ``APPLYING`` row, at any age: it is the only durable record that
        an answer was begun.
        """
        now = self._now()
        async with self._exclusive():
            doomed = [row.id for row in self._rows.values() if row.is_purgeable_at(now)]
            for row_id in doomed:
                del self._rows[row_id]
                self._claims.pop(row_id, None)
            return len(doomed)


def _check_terminal_payload(state: object, record_id: str | None, successor_id: str | None) -> None:
    """Refuse a resolution whose state is not terminal or whose payload is not its.

    Each terminal state requires its own payload and forbids the other's, in the
    shape ``MemoryDecision._outcome_fields_are_consistent`` enforces for a ruling.
    Without it a valid claim can resolve ``ACCEPTED`` naming nothing that was
    written — a terminal state that lies, reached through the one call whose whole
    job is to record what happened. Duplicated in the production store rather than
    shared, for the reason given on :data:`_PAGE_BOUND`.

    ``state`` is typed ``object`` deliberately, the way ``_check_page_bound``'s
    value is: the annotation on the seam is not a runtime guard, and this is the one
    place that can hold the type.

    Raises:
        ValueError: If ``state`` is not a :class:`DeferralState` at all, if it is not
            terminal, or if the two ids do not match what it requires and forbids.
    """
    if not isinstance(state, DeferralState):
        # The annotation is not a runtime guard, and the two backends disagree
        # without this one: ``"accepted"`` satisfies membership in the terminal set
        # (a ``StrEnum`` member compares and hashes equal to its value), after which
        # a dict-backed store lets pydantic coerce it into the record while a SQL one
        # reaches for ``.value`` and raises ``AttributeError`` — outside the
        # ``ValueError`` this call documents. ADR-0078 §2 makes the same argument for
        # the paging arguments: a value that passes one check while meaning something
        # no two backends agree on is refused on its type.
        msg = f"resolve records a DeferralState, got {describe_untrusted(state)}"
        raise ValueError(msg)
    if state not in TERMINAL_DEFERRAL_STATES:
        msg = f"resolve records a terminal state, got {state.name}"
        raise ValueError(msg)
    if state is DeferralState.ACCEPTED:
        if record_id is None:
            msg = "an ACCEPTED resolution requires record_id: it names what was written"
            raise ValueError(msg)
        if successor_id is not None:
            msg = "an ACCEPTED resolution raised no successor question"
            raise ValueError(msg)
        return
    if state is DeferralState.REDEFERRED:
        if successor_id is None:
            msg = "a REDEFERRED resolution requires successor_id: it names the question it raised"
            raise ValueError(msg)
        if record_id is not None:
            msg = "a REDEFERRED resolution wrote no record"
            raise ValueError(msg)
        return
    if record_id is not None or successor_id is not None:
        msg = f"a {state.name} resolution carries neither a record id nor a successor id"
        raise ValueError(msg)
