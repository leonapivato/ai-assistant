"""ADR-0078's answer path, end to end: the assertions §10 names as owed.

These are properties of the **sequence** — ``claim`` → ``ingest`` → ``resolve``,
across two stores that share no transaction — so none of them belongs in either
store's conformance suite, and ADR-0078 §10 says so: "they are properties of the
sequence, and the sequence lives here."

**The real ``DefaultMemoryPolicy`` is wired deliberately**, and it is the one place
these tests reach across a subsystem boundary. The exit test is *about* the policy's
own behaviour meeting the queue's: a correction that contradicts a prior assertion
must produce a question, and answering it must flip that same policy's ruling from
``ASK_USER`` to ``SUPERSEDE`` through the authority a claim mints. A scripted policy
double could be made to produce either ruling on demand and would therefore prove
nothing about the join — it would be a second copy of the rule under test, which is
exactly what ``FakeMemoryPolicy``'s docstring says a double is *not* for. The
sequence's other properties — the compare-and-sets, the cancellation windows, the id
re-mints, the total outcome mapping — are independent of any policy's rules, and
those are driven with a scripted one.

``FakeMemoryWriter`` rather than ``MemoryIngestor``: ADR-0028 §8's shared suite binds
both, and the fake carries the confirmation exception and check 0 because a fake
looser than the contract would certify a consumer the real writer rejects.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from ai_assistant.core.errors import (
    DeferralStoreError,
    MemoryStoreError,
    UnresolvedEvidenceError,
)
from ai_assistant.core.types import (
    AnswerKind,
    DataTier,
    DeferralState,
    MemoryDecision,
    MemoryDecisionKind,
    MemorySource,
    MemoryUpdateProposal,
    Provenance,
    QuestionState,
    SemanticMemory,
    Validity,
)
from ai_assistant.memory import DefaultMemoryPolicy
from ai_assistant.orchestration import (
    MemoryWriteStage,
    QuestionStage,
)
from ai_assistant.testing import (
    FakeDeferralStore,
    FakeMemoryStore,
    FakeMemoryWriter,
)
from ai_assistant.testing.cancellation import settle

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from ai_assistant.core.protocols import MemoryPolicy
    from ai_assistant.core.types import (
        DeferralAdmission,
        DeferralClaim,
        DeferredProposal,
        MemoryIngestResult,
        MemoryRecord,
    )

AT = datetime(2026, 7, 1, tzinfo=UTC)

#: The `ASK_USER` ruling a scripted policy hands back, when a test needs a question
#: without depending on any policy's rules for it.
_ASK = MemoryDecision(kind=MemoryDecisionKind.ASK_USER, reason="fake: the user decides")

_LISBON = "the user works from Lisbon"
_MADRID = "the user works from Madrid"


def _clock() -> datetime:
    return AT


def _record(
    record_id: str,
    content: str,
    *,
    source: MemorySource = MemorySource.USER_ASSERTED,
    validity: Validity | None = None,
) -> SemanticMemory:
    """A semantic record; ``USER_ASSERTED`` carries the full confidence it must."""
    confidence = 1.0 if source is MemorySource.USER_ASSERTED else 0.6
    return SemanticMemory(
        id=record_id,
        content=content,
        fact=content,
        validity=validity if validity is not None else Validity(),
        provenance=Provenance(source=source, confidence=confidence, last_updated=AT),
    )


def _proposal(
    record_id: str,
    content: str,
    *,
    source: MemorySource = MemorySource.USER_ASSERTED,
    validity: Validity | None = None,
    sensitivity: DataTier = DataTier.PERSONAL,
) -> MemoryUpdateProposal:
    return MemoryUpdateProposal(
        proposed=_record(record_id, content, source=source, validity=validity),
        rationale="the user said so",
        sensitivity=sensitivity,
    )


class Harness:
    """One write stage and one question stage over one queue, as production wires them.

    The two stages share the ``DeferralStore`` instance and the ``MemoryWriter``
    instance, which is ADR-0078 §3's first two composition-root obligations
    discharged by construction — and the wiring test in ``tests/app`` proves the
    real composition root does the same.
    """

    def __init__(
        self,
        *,
        policy: MemoryPolicy | None = None,
        retention: timedelta | None = timedelta(days=30),
        queue_limit: int = 50,
        ids: Callable[[], str] | None = None,
        writer: FakeMemoryWriter | None = None,
    ) -> None:
        self._minted = iter(f"q-{n}" for n in range(1, 100))
        mint = ids if ids is not None else self._mint
        self.memory = FakeMemoryStore(now=_clock)
        self.policy = policy if policy is not None else DefaultMemoryPolicy()
        self.writer = (
            writer
            if writer is not None
            else FakeMemoryWriter(store=self.memory, policy=self.policy, now=_clock)
        )
        self.deferrals = FakeDeferralStore(now=_clock, retention=retention, queue_limit=queue_limit)
        self.writes = MemoryWriteStage(
            writer=self.writer, deferrals=self.deferrals, id_factory=mint
        )
        self.questions = QuestionStage(
            writer=self.writer,
            deferrals=self.deferrals,
            memory=self.memory,
            now=_clock,
            id_factory=mint,
        )

    def _mint(self) -> str:
        return next(self._minted)

    def restarted(self) -> QuestionStage:
        """A second question stage over the same durable state, holding no ids.

        What a restarted process has: the stores survive, every in-process handle is
        gone. ADR-0078 §9 makes ``interrupted`` the only way back to a stranded
        question after one, so a test that reused this harness's stage would prove
        nothing about it.
        """
        return QuestionStage(
            writer=self.writer,
            deferrals=self.deferrals,
            memory=self.memory,
            now=_clock,
            id_factory=self._mint,
        )


# --------------------------------------------------------------------------- #
# The exit test                                                               #
# --------------------------------------------------------------------------- #


async def test_a_correction_contradicting_an_assertion_becomes_a_question_and_lands() -> None:
    """Leg 4's exit test, and the assertion every other one here depends on (§10 item 3).

    A correction that contradicts something the user told us earlier is deferred
    rather than committed (ADR-0050 §2), the question **shows that assertion**, and
    answering it accept lands the correction — in **one round, with no
    re-deferral**.

    This is the assertion that fails when the write stage enqueues the caller's
    untouched proposal instead of a snapshot carrying ``result.conflicts`` (§3): the
    question would show no conflicting assertion, the answer's ``retires`` would be
    empty, and the re-ingest would find that assertion outside the authority and
    re-defer. The user answers, and is asked again.
    """
    harness = Harness()
    await harness.memory.add(_record("live-1", _LISBON))

    outcome = await harness.writes.write(_proposal("new-1", _LISBON))

    assert outcome.result.decision.kind is MemoryDecisionKind.ASK_USER
    assert outcome.result.record_id is None
    assert outcome.admission is not None
    parked = outcome.admission.deferral
    assert parked is not None

    [question] = await harness.questions.questions()
    assert question.id == parked.id
    assert question.state is QuestionState.OPEN
    assert question.content == _LISBON
    # The conflicting assertion is *shown*, resolved to its content. This is the
    # exact scope the answer will authorise.
    assert [(r.record_id, r.content) for r in question.retires] == [("live-1", _LISBON)]

    answered = await harness.questions.answer(question.id, accept=True)

    assert answered.kind is AnswerKind.APPLIED, "one round, no re-deferral"
    assert answered.record_id is not None
    assert answered.record_id not in {"live-1", "new-1"}, "a correction gets a fresh id"
    # The prior assertion is retired — retained, off the read path (ADR-0045 §4).
    assert await harness.memory.get("live-1") is None
    correction = await harness.memory.get(answered.record_id)
    assert correction is not None
    assert correction.content == _LISBON
    stored = await harness.deferrals.get(question.id)
    assert stored is not None
    assert stored.state is DeferralState.ACCEPTED
    assert stored.outcome_record_id == answered.record_id


async def test_the_question_shows_a_conflict_that_has_since_been_retired_as_no_longer_held() -> (
    None
):
    """A conflict the user was shown that has gone renders as *no longer held* (§8).

    ``MemoryStore.get`` hides a closed window (ADR-0045 §6), so the content does not
    resolve — and the row is **kept rather than omitted**, because the user should be
    told that the thing they would be overruling is already gone. Omitting it would
    understate the answer's scope in one direction and overstate it in the other.
    """
    harness = Harness()
    await harness.memory.add(_record("live-1", _LISBON))
    outcome = await harness.writes.write(_proposal("new-1", _LISBON))
    assert outcome.admission is not None
    await harness.memory.delete("live-1")

    [question] = await harness.questions.questions()

    assert [(r.record_id, r.content) for r in question.retires] == [("live-1", None)]


# --------------------------------------------------------------------------- #
# The write stage's snapshot, and what is never queued                        #
# --------------------------------------------------------------------------- #


async def test_the_enqueued_question_carries_the_conflicts_the_policy_ruled_against() -> None:
    """§3's snapshot, asserted directly as well as through the exit test.

    The writer resolves conflicts onto its *own* copy, so the caller's proposal still
    carries an empty ``conflicts`` when ``ingest`` returns. Enqueuing that original
    satisfies every store and writer conformance clause and produces a question that
    shows the user nothing.
    """
    harness = Harness()
    await harness.memory.add(_record("live-1", _LISBON))
    submitted = _proposal("new-1", _LISBON)

    outcome = await harness.writes.write(submitted)

    assert submitted.conflicts == (), "the caller's own proposal is untouched"
    assert outcome.result.conflicts == ("live-1",)
    assert outcome.admission is not None
    parked = outcome.admission.deferral
    assert parked is not None
    assert parked.proposal.conflicts == ("live-1",)


async def test_a_secret_tier_deferral_queues_nothing_and_raises_nothing() -> None:
    """§1's residue, and the arm ADR-0078 does not close (§10 item 3's secret pair).

    ADR-0004 §3 forbids Tier 0 content a committed file, and a durable queue is a
    file — so today's deferral is precisely what keeps such content out of storage.
    Nothing is queued, **nothing raises**, and the result carries no question id: an
    implementation that called ``defer`` anyway would surface the record type's
    validation failure as an error on a path that is supposed to be ordinary.
    """
    harness = Harness()

    outcome = await harness.writes.write(
        _proposal("secret-1", "the api key is hunter2", sensitivity=DataTier.SECRET)
    )

    assert outcome.result.decision.kind is MemoryDecisionKind.ASK_USER
    assert outcome.admission is None, "nothing was offered to the queue"
    assert await harness.deferrals.export() == []
    assert await harness.questions.questions() == ()


async def test_a_full_queue_refuses_the_new_question_and_says_so() -> None:
    """§7's refused branch — the one an implementation leaves as a silent no-op.

    Nothing raises, so a stage that ignored the admission would drop the correction
    the user just typed in complete silence. The refusal comes back on the outcome.
    """
    harness = Harness(queue_limit=1)
    await harness.memory.add(_record("live-1", _LISBON))
    await harness.memory.add(_record("live-2", _MADRID))
    first = await harness.writes.write(_proposal("new-1", _LISBON))
    assert first.admission is not None
    assert first.admission.outcome.value == "admitted"

    second = await harness.writes.write(_proposal("new-2", _MADRID))

    assert second.admission is not None
    assert second.admission.outcome.value == "refused"
    assert second.admission.deferral is None
    assert len(await harness.deferrals.export()) == 1


async def test_an_ordinary_admission_re_mints_a_colliding_id_and_parks_the_question() -> None:
    """§10 item 3: a forced collision is re-minted rather than propagated.

    The coordinator mints the id, so a physical collision is its fault to retry —
    which the store refuses to absorb, because absorbing it would hand the caller
    back a different question under an id it believes it just minted.
    """
    harness = Harness(ids=_scripted("q-1", "q-1", "q-2"))
    await harness.memory.add(_record("live-1", _LISBON))
    await harness.memory.add(_record("live-2", _MADRID))
    first = await harness.writes.write(_proposal("new-1", _LISBON))
    assert first.admission is not None
    assert first.admission.deferral is not None
    assert first.admission.deferral.id == "q-1"

    second = await harness.writes.write(_proposal("new-2", _MADRID))

    assert second.admission is not None
    assert second.admission.deferral is not None
    assert second.admission.deferral.id == "q-2"


async def test_an_always_colliding_id_factory_raises_with_zero_deferrals_persisted() -> None:
    """The bounded end, asserted: "bounded" without an exhaustion case is a loop
    nobody has counted (§10 item 3).

    A correction is then neither silently dropped nor half-written: the ruling stands
    (nothing was written, because the policy deferred) and the failure surfaces.
    """
    harness = Harness(ids=lambda: "q-1")
    await harness.memory.add(_record("live-1", _LISBON))
    await harness.memory.add(_record("live-2", _MADRID))
    await harness.writes.write(_proposal("new-1", _LISBON))

    with pytest.raises(DeferralStoreError, match="could not mint a free deferral id"):
        await harness.writes.write(_proposal("new-2", _MADRID))

    assert len(await harness.deferrals.export()) == 1, "nothing half-written"


def _scripted(*ids: str) -> Callable[[], str]:
    """An id factory returning ``ids`` in order, then raising."""
    minted = iter(ids)
    return lambda: next(minted)


# --------------------------------------------------------------------------- #
# Test-side doubles: the levers §10 requires be deterministic, not timed       #
# --------------------------------------------------------------------------- #


class _GatedWriter:
    """A ``MemoryWriter`` that suspends on entry, then delegates or raises.

    The lever for every clause about what happens *while* an ingest is in flight.
    It suspends **before** delegating, so a test can interleave a ``purge``, a
    ``forget_question`` or a cancellation with a claim that is genuinely
    ``APPLYING`` and then let the write land — which is the ordering ADR-0078 §9's
    disposal and sweep clauses are about.
    """

    def __init__(self, inner: FakeMemoryWriter, *, raises: BaseException | None = None) -> None:
        self._inner = inner
        self._raises = raises
        self.entered = asyncio.Event()
        self.proceed = asyncio.Event()

    async def ingest(self, proposal: MemoryUpdateProposal) -> MemoryIngestResult:
        """Announce arrival, wait to be let go, then delegate or raise."""
        self.entered.set()
        await self.proceed.wait()
        if self._raises is not None:
            raise self._raises
        return await self._inner.ingest(proposal)


class _InterceptedStore:
    """A ``DeferralStore`` that suspends immediately before or after one named call.

    ADR-0078 §10 requires the cancellation windows be driven "on injected clocks and
    deterministic suspension rather than timing", and two of them are about the
    instant *inside* a store call: a ``claim`` cancelled after its compare-and-set
    and before it returns, and a ``resolve`` cancelled on either side of its own. The
    canonical fake's exclusion yields *before* its body — deliberately, so the shared
    suite's concurrency clauses cannot pass vacuously — which is the wrong side for
    those two, so this wrapper puts a gate exactly where the clause names it.

    Every other method delegates untouched, and is written out rather than proxied so
    the wrapper still satisfies the Protocol structurally.
    """

    def __init__(
        self,
        inner: FakeDeferralStore,
        *,
        before: str | None = None,
        after: str | None = None,
    ) -> None:
        self._inner = inner
        self._before = before
        self._after = after
        self.entered = asyncio.Event()
        self.proceed = asyncio.Event()

    async def _gate(self, name: str, *, phase: str) -> None:
        if (self._before if phase == "before" else self._after) != name:
            return
        self.entered.set()
        await self.proceed.wait()

    async def defer(
        self,
        *,
        deferral_id: str,
        proposal: MemoryUpdateProposal,
        decision: MemoryDecision,
        predecessor_id: str | None = None,
        successor_to_claim: str | None = None,
    ) -> DeferralAdmission:
        """Delegate, gated on either side of the admission."""
        await self._gate("defer", phase="before")
        admission = await self._inner.defer(
            deferral_id=deferral_id,
            proposal=proposal,
            decision=decision,
            predecessor_id=predecessor_id,
            successor_to_claim=successor_to_claim,
        )
        await self._gate("defer", phase="after")
        return admission

    async def claim(self, deferral_id: str) -> DeferralClaim | None:
        """Delegate, gated on either side of the compare-and-set."""
        await self._gate("claim", phase="before")
        claimed = await self._inner.claim(deferral_id)
        await self._gate("claim", phase="after")
        return claimed

    async def resolve(
        self,
        deferral_id: str,
        *,
        claim_id: str | None,
        state: DeferralState,
        record_id: str | None = None,
        successor_id: str | None = None,
    ) -> bool:
        """Delegate, gated on either side of the terminal compare-and-set."""
        await self._gate("resolve", phase="before")
        recorded = await self._inner.resolve(
            deferral_id,
            claim_id=claim_id,
            state=state,
            record_id=record_id,
            successor_id=successor_id,
        )
        await self._gate("resolve", phase="after")
        return recorded

    async def get(self, deferral_id: str) -> DeferredProposal | None:
        """Delegate."""
        return await self._inner.get(deferral_id)

    async def pending(self, *, limit: int = 50, offset: int = 0) -> list[DeferredProposal]:
        """Delegate."""
        return await self._inner.pending(limit=limit, offset=offset)

    async def interrupted(self, *, limit: int = 50, offset: int = 0) -> list[DeferredProposal]:
        """Delegate."""
        return await self._inner.interrupted(limit=limit, offset=offset)

    async def delete(self, deferral_id: str) -> bool:
        """Delegate."""
        return await self._inner.delete(deferral_id)

    async def clear(self) -> int:
        """Delegate."""
        return await self._inner.clear()

    async def export(self) -> list[DeferredProposal]:
        """Delegate."""
        return await self._inner.export()

    async def purge(self) -> int:
        """Delegate."""
        return await self._inner.purge()


class _DefersThenRules:
    """A policy that defers an unconfirmed proposal and rules ``kind`` on a confirmed one.

    The only way to reach ADR-0078 §2's totality clause for ``REJECT``: a conforming
    policy that is not ``DefaultMemoryPolicy`` may rule ``REJECT`` on a confirmed
    proposal, and without a legal transition for it such an answer would strand
    ``APPLYING`` forever. "Which is exactly why it needs a test rather than an
    argument" (§10 item 3).
    """

    def __init__(self, kind: MemoryDecisionKind) -> None:
        self._kind = kind

    async def decide(
        self, proposal: MemoryUpdateProposal, *, conflicts: Sequence[MemoryRecord]
    ) -> MemoryDecision:
        """Defer until a confirmation arrives, then rule the configured kind."""
        if proposal.confirmation is None:
            return _ASK
        if self._kind in {MemoryDecisionKind.REINFORCE, MemoryDecisionKind.SUPERSEDE}:
            return MemoryDecision(
                kind=self._kind, reason="fake: the confirmed ruling", target_id=conflicts[0].id
            )
        return MemoryDecision(kind=self._kind, reason="fake: the confirmed ruling")


# --------------------------------------------------------------------------- #
# The claim: at most one apply, whatever the concurrency                      #
# --------------------------------------------------------------------------- #


async def test_two_concurrent_accepts_leave_one_correction_and_report_the_loser() -> None:
    """§9's whole guarantee (§10 item 3), driven through the store's own exclusion.

    Without the claim, two concurrent answers both read a ``PENDING`` deferral, both
    ingest, and **both write** — only one then wins the terminal compare-and-set, and
    the loser is reported as already answered while its memory mutation stands. A
    duplicate correction with no crash anywhere, produced by ordinary concurrent use.
    Claiming first turns it into a lost race that writes nothing.
    """
    harness = Harness()
    await harness.memory.add(_record("live-1", _LISBON))
    outcome = await harness.writes.write(_proposal("new-1", _LISBON))
    assert outcome.admission is not None
    assert outcome.admission.deferral is not None
    question_id = outcome.admission.deferral.id

    suspended = harness.deferrals.suspend_next_write()
    first = asyncio.ensure_future(harness.questions.answer(question_id, accept=True))
    await suspended.reached()
    second = asyncio.ensure_future(harness.questions.answer(question_id, accept=True))
    await settle()
    suspended.release()
    outcomes = [await first, await second]

    kinds = sorted(one.kind.value for one in outcomes)
    assert kinds == ["applied", "not_open"], "exactly one apply, the loser told plainly"
    live = [record.id for record in await harness.memory.export() if record.validity.live_at(AT)]
    assert len(live) == 1, "one correction in the store, not two"


async def test_an_accept_suspended_inside_ingest_survives_a_purge_and_resolves() -> None:
    """§2's ``APPLYING`` exclusion, from the coordinator's side (§10 item 3).

    A sweep that removed the row while its ingest was still running — a slow embed is
    enough — would let the memory write commit against a question that no longer
    exists, so the bookkeeping fails and the fact that an answer was given survives
    nowhere. ``purge`` may not make that decision.
    """
    harness = Harness()
    gated = _GatedWriter(harness.writer)
    stage = QuestionStage(
        writer=gated, deferrals=harness.deferrals, memory=harness.memory, now=_clock
    )
    await harness.memory.add(_record("live-1", _LISBON))
    outcome = await harness.writes.write(_proposal("new-1", _LISBON))
    assert outcome.admission is not None
    assert outcome.admission.deferral is not None
    question_id = outcome.admission.deferral.id

    answering = asyncio.ensure_future(stage.answer(question_id, accept=True))
    await gated.entered.wait()
    assert await harness.deferrals.purge() == 0, "an APPLYING row is never swept, at any age"
    gated.proceed.set()
    answered = await answering

    assert answered.kind is AnswerKind.APPLIED
    assert not answered.disposed
    stored = await harness.deferrals.get(question_id)
    assert stored is not None
    assert stored.state is DeferralState.ACCEPTED


async def test_an_accept_whose_question_is_destroyed_mid_apply_commits_and_reports_it() -> None:
    """A ``resolve`` that finds nothing is **reported, not raised** (§9, §10 item 3).

    And what it reports comes from the ingest, not from the failure: the coordinator
    still holds the ``MemoryIngestResult``, so it names the record written. The
    ``False`` adds one clause — the question is gone — and nothing else.
    """
    harness = Harness()
    gated = _GatedWriter(harness.writer)
    stage = QuestionStage(
        writer=gated, deferrals=harness.deferrals, memory=harness.memory, now=_clock
    )
    await harness.memory.add(_record("live-1", _LISBON))
    outcome = await harness.writes.write(_proposal("new-1", _LISBON))
    assert outcome.admission is not None
    assert outcome.admission.deferral is not None
    question_id = outcome.admission.deferral.id

    answering = asyncio.ensure_future(stage.answer(question_id, accept=True))
    await gated.entered.wait()
    assert await harness.questions.forget_question(question_id)
    gated.proceed.set()
    answered = await answering

    assert answered.kind is AnswerKind.APPLIED, "what is reported comes from the ingest"
    assert answered.record_id is not None
    assert answered.disposed, "and the disposal is reported alongside it"
    assert await harness.memory.get(answered.record_id) is not None
    assert await harness.deferrals.get(question_id) is None


@pytest.mark.parametrize(
    ("failure", "label"),
    [
        (UnresolvedEvidenceError("cited evidence is gone", ("ep-1",)), "lost evidence"),
        (MemoryStoreError("the store is unavailable"), "a store failure"),
        (asyncio.CancelledError(), "cancellation"),
    ],
    ids=["unresolved-evidence", "store-failure", "cancellation"],
)
async def test_an_accept_whose_ingest_fails_strands_the_claim_and_writes_no_bookkeeping(
    failure: BaseException, label: str
) -> None:
    """§9's raising path, driven three ways (§10 item 3).

    Not only a crash: a deferred derived proposal can cite evidence that resolved
    when the question was queued and has since been deleted, and a store failure
    arrives at a moment the coordinator cannot classify. The exception **propagates
    unchanged** — no error transport is invented — and the claim is neither resolved
    nor released nor deleted, because for a store failure the coordinator does not
    know whether the write landed, so ``ACCEPTED`` and ``REJECTED`` are both
    potentially false and stamping either is the lie §9 exists to prevent.

    The cancellation case is asserted rather than inferred from the other two,
    because it is the one an error boundary silently handles.
    """
    harness = Harness()
    failing = _GatedWriter(harness.writer, raises=failure)
    failing.proceed.set()
    stage = QuestionStage(
        writer=failing, deferrals=harness.deferrals, memory=harness.memory, now=_clock
    )
    await harness.memory.add(_record("live-1", _LISBON))
    outcome = await harness.writes.write(_proposal("new-1", _LISBON))
    assert outcome.admission is not None
    assert outcome.admission.deferral is not None
    question_id = outcome.admission.deferral.id

    with pytest.raises(type(failure)):
        await stage.answer(question_id, accept=True)

    stranded = await harness.deferrals.get(question_id)
    assert stranded is not None
    assert stranded.state is DeferralState.APPLYING, label
    assert stranded.answered_at is None, "no bookkeeping was written"
    # And it is reachable in a process that never held its id (§10 item 7).
    [shown] = await harness.restarted().interrupted_questions()
    assert shown.id == question_id
    assert shown.state is QuestionState.INTERRUPTED
    assert await harness.questions.questions() == (), "and not offered as answerable"


# --------------------------------------------------------------------------- #
# The re-deferral: a completed answer that raises a further question          #
# --------------------------------------------------------------------------- #


async def _question_over_one_assertion(harness: Harness) -> str:
    """Park a question about a correction contradicting exactly one assertion."""
    await harness.memory.add(_record("live-1", _LISBON))
    outcome = await harness.writes.write(_proposal("new-1", _LISBON))
    assert outcome.admission is not None
    assert outcome.admission.deferral is not None
    return outcome.admission.deferral.id


async def test_an_answer_meeting_an_unshown_assertion_writes_nothing_and_raises_a_successor() -> (
    None
):
    """§5a step 1 and §9's re-deferral, through §9's exact call (§10 item 3).

    An asserted conflict the user was **never shown** is outside the answer's
    authority: superseding the covered assertion while committing beside the
    uncovered one is the #245 gap reached by a new path, and extending the answer to
    a record they did not see would forge consent. So nothing is written, a fresh
    question is minted over the **new** set, and the original resolves ``REDEFERRED``
    naming it — a completed answer, not a failed one.

    ADR-0079 §2's ordering holds throughout: the set is complete before the ruling,
    only a ``SUPERSEDE`` retires anything, and a deferral therefore "retires nothing
    on its way".
    """
    harness = Harness()
    question_id = await _question_over_one_assertion(harness)
    # A second assertion appears after the question was frozen, so the answer's
    # authority does not name it.
    await harness.memory.add(_record("live-2", _LISBON))

    answered = await harness.questions.answer(question_id, accept=True)

    assert answered.kind is AnswerKind.REDEFERRED
    assert answered.record_id is None
    assert answered.successor is not None
    assert answered.successor.state is QuestionState.OPEN
    assert not answered.disposed
    # Nothing was written and nothing was retired on the way out.
    assert await harness.memory.get("live-1") is not None
    assert await harness.memory.get("live-2") is not None
    assert len(await harness.memory.export()) == 2

    parent = await harness.deferrals.get(question_id)
    assert parent is not None
    assert parent.state is DeferralState.REDEFERRED
    assert parent.successor_id == answered.successor.id
    successor = await harness.deferrals.get(answered.successor.id)
    assert successor is not None
    assert successor.predecessor_id == question_id, "the pair is symmetric on a fresh admission"
    # The successor asks about the *new* set — which is why its key differs from its
    # parent's and dedup did not suppress it.
    assert set(successor.proposal.conflicts) == {"live-1", "live-2"}
    assert successor.proposal.confirmation is None, "a queued question holds no authority"
    [shown] = await harness.questions.questions()
    assert shown.id == successor.id


async def test_a_re_deferral_admits_its_successor_past_a_full_queue() -> None:
    """The assertion that would have caught the stranded-claim hole (§10 item 3).

    A re-deferral does not consult the cap (§2), because the token the claim minted
    is the capability that buys the exemption — so a full queue cannot strand a
    claimed answer. Without it the alternative is worse in a way the cap was never
    meant to buy: a claimed answer with nowhere to go, and a newly-surfaced assertion
    never asked about, which is the exact drop ADR-0078 ends.
    """
    harness = Harness(queue_limit=1)
    question_id = await _question_over_one_assertion(harness)
    await harness.memory.add(_record("live-2", _LISBON))
    assert len(await harness.deferrals.pending()) == 1, "the queue is at its cap"

    answered = await harness.questions.answer(question_id, accept=True)

    assert answered.kind is AnswerKind.REDEFERRED
    assert answered.successor is not None
    parent = await harness.deferrals.get(question_id)
    assert parent is not None
    assert parent.state is DeferralState.REDEFERRED, "the claimed answer still resolves"


async def test_a_successor_admission_re_mints_a_colliding_id_and_still_resolves() -> None:
    """The successor path's own re-mint (§10 item 3).

    Named separately from the ordinary one because an implementation can correctly
    retry successors and still propagate the ordinary error — which parks nothing and
    loses exactly the correction the user just typed — or the reverse, which strands
    a claimed answer.
    """
    harness = Harness(ids=_scripted("q-1", "q-1", "q-2"))
    question_id = await _question_over_one_assertion(harness)
    assert question_id == "q-1"
    await harness.memory.add(_record("live-2", _LISBON))

    answered = await harness.questions.answer(question_id, accept=True)

    assert answered.successor is not None
    assert answered.successor.id == "q-2"
    parent = await harness.deferrals.get("q-1")
    assert parent is not None
    assert parent.state is DeferralState.REDEFERRED
    assert parent.successor_id == "q-2", "the parent names a reachable successor"


async def test_an_always_colliding_successor_id_leaves_the_parent_interrupted() -> None:
    """The bounded end of the successor path (§10 item 3).

    It raises, writes nothing, and leaves the parent ``APPLYING`` and reachable
    through the interrupted enumeration — visible and recoverable, never
    lost-and-silent.
    """
    harness = Harness(ids=lambda: "q-1")
    question_id = await _question_over_one_assertion(harness)
    await harness.memory.add(_record("live-2", _LISBON))

    with pytest.raises(DeferralStoreError, match="could not mint a free deferral id"):
        await harness.questions.answer(question_id, accept=True)

    parent = await harness.deferrals.get(question_id)
    assert parent is not None
    assert parent.state is DeferralState.APPLYING
    assert parent.successor_id is None
    assert len(await harness.deferrals.export()) == 1, "nothing was written"
    [shown] = await harness.restarted().interrupted_questions()
    assert shown.id == question_id


async def test_a_re_deferral_whose_parent_was_destroyed_takes_the_ordinary_path() -> None:
    """§9's care one step earlier: no parent means no exemption and no link.

    The successor's ``defer`` finds **no parent** — not merely no token — so it is
    admitted as an ordinary question, subject to the cap and linked to nothing, and
    nothing raises. Both conditions are things the user brought about, and both are
    told.
    """
    harness = Harness()
    question_id = await _question_over_one_assertion(harness)
    await harness.memory.add(_record("live-2", _LISBON))
    gated = _GatedWriter(harness.writer)
    stage = QuestionStage(
        writer=gated, deferrals=harness.deferrals, memory=harness.memory, now=_clock
    )

    answering = asyncio.ensure_future(stage.answer(question_id, accept=True))
    await gated.entered.wait()
    assert await harness.questions.forget_question(question_id)
    gated.proceed.set()
    answered = await answering

    assert answered.kind is AnswerKind.REDEFERRED
    assert answered.disposed, "the disposal is reported rather than raised"
    assert answered.successor is not None
    assert answered.successor.state is QuestionState.OPEN
    successor = await harness.deferrals.get(answered.successor.id)
    assert successor is not None
    assert successor.predecessor_id is None, "nothing to link to"


async def test_a_re_deferral_past_a_disposal_and_a_full_queue_queues_no_successor() -> None:
    """The one branch that must not be called "re-deferred and here is your question".

    Parent destroyed mid-apply *and* the queue full: the admission has no exemption
    to spend, so no follow-on question could be queued at all. Saying a question was
    asked when none was is the one sentence ADR-0078 cannot write (§9).
    """
    harness = Harness(queue_limit=1)
    question_id = await _question_over_one_assertion(harness)
    await harness.memory.add(_record("live-2", _LISBON))
    # A second answerable question fills the cap once the parent is gone.
    await harness.memory.add(_record("other-1", _MADRID))
    gated = _GatedWriter(harness.writer)
    stage = QuestionStage(
        writer=gated, deferrals=harness.deferrals, memory=harness.memory, now=_clock
    )

    answering = asyncio.ensure_future(stage.answer(question_id, accept=True))
    await gated.entered.wait()
    assert await harness.questions.forget_question(question_id)
    filler = await harness.writes.write(_proposal("new-2", _MADRID))
    assert filler.admission is not None
    assert filler.admission.outcome.value == "admitted"
    gated.proceed.set()
    answered = await answering

    assert answered.kind is AnswerKind.REDEFERRED
    assert answered.successor is None
    assert answered.successor_refused, "no follow-on question could be queued"
    assert answered.disposed


@pytest.mark.parametrize(
    "state",
    [DeferralState.PENDING, DeferralState.REJECTED, DeferralState.APPLYING],
    ids=["pending", "rejected", "applying"],
)
async def test_a_suppressed_successor_is_reported_by_the_state_that_suppressed_it(
    state: DeferralState,
) -> None:
    """§9's suppressed branch, driven per state — the split a suite skips (§10 item 3).

    Only the ``PENDING`` case is a follow-on the user can answer. A ``REJECTED`` one
    means they already declined this and must forget it to be asked again, and an
    ``APPLYING`` one is another interrupted answer. A suite that drives only the
    rejected suppression can render an interrupted row as an answerable follow-on and
    still pass, advertising a question the user cannot act on.
    """
    harness = Harness()
    question_id = await _question_over_one_assertion(harness)
    await harness.memory.add(_record("live-2", _LISBON))
    # Seed the successor's own key: the same proposal against the same *new* set.
    seeded = await harness.deferrals.defer(
        deferral_id="seeded",
        proposal=_proposal("new-1", _LISBON).model_copy(update={"conflicts": ("live-1", "live-2")}),
        decision=_ASK,
    )
    assert seeded.deferral is not None
    if state is DeferralState.REJECTED:
        assert await harness.deferrals.resolve(
            "seeded", claim_id=None, state=DeferralState.REJECTED
        )
    elif state is DeferralState.APPLYING:
        assert await harness.deferrals.claim("seeded") is not None

    answered = await harness.questions.answer(question_id, accept=True)

    assert answered.kind is AnswerKind.REDEFERRED
    assert answered.successor is not None
    assert answered.successor.id == "seeded", "the parent names the question that suppressed it"
    assert (
        answered.successor.state
        is {
            DeferralState.PENDING: QuestionState.OPEN,
            DeferralState.REJECTED: QuestionState.DECLINED,
            DeferralState.APPLYING: QuestionState.INTERRUPTED,
        }[state]
    )
    parent = await harness.deferrals.get(question_id)
    assert parent is not None
    assert parent.state is DeferralState.REDEFERRED
    assert parent.successor_id == "seeded"
    # One-way on the suppressed path: the existing question keeps its own origin.
    existing = await harness.deferrals.get("seeded")
    assert existing is not None
    assert existing.predecessor_id is None


# --------------------------------------------------------------------------- #
# Cancellation: five windows across the two paths (§9, §10 item 3)            #
# --------------------------------------------------------------------------- #


async def test_cancelling_claim_after_its_cas_strands_the_row_and_repairs_nothing() -> None:
    """The window that loses the token (§9's first cancellation case).

    Cancelled after ``claim``'s compare-and-set and before it returns, the row is
    ``APPLYING`` and **nobody holds the token**. Nothing can be applied — there is no
    token to authorise it — so it is stranded, which is the same state a crash inside
    a claim leaves. That the lost-token case and the lost-outcome case land
    identically is worth having: a user is never asked to distinguish two kinds of "I
    don't know".

    Driven through an interception rather than the canonical fake's own suspension,
    which yields *before* its body — the wrong side for this clause.
    """
    harness = Harness()
    question_id = await _question_over_one_assertion(harness)
    intercepted = _InterceptedStore(harness.deferrals, after="claim")
    stage = QuestionStage(
        writer=harness.writer, deferrals=intercepted, memory=harness.memory, now=_clock
    )

    answering = asyncio.ensure_future(stage.answer(question_id, accept=True))
    await intercepted.entered.wait()
    answering.cancel()
    intercepted.proceed.set()
    with pytest.raises(asyncio.CancelledError):
        await answering

    stranded = await harness.deferrals.get(question_id)
    assert stranded is not None
    assert stranded.state is DeferralState.APPLYING
    assert stranded.answered_at is None, "nothing was repaired"
    assert await harness.memory.get("live-1") is not None, "nothing was applied"
    # And a *fresh* process still finds it — the restart clause (§10 item 7).
    [shown] = await harness.restarted().interrupted_questions()
    assert shown.id == question_id


async def test_cancelling_resolve_after_its_commit_keeps_the_terminal_row() -> None:
    """The only window that can leave a **finished** question (§9).

    The terminal compare-and-set commits and the cancellation arrives before the call
    returns, so the deferral is ``ACCEPTED`` — correctly, the apply did happen — while
    the caller learned nothing. Nothing needs doing, and re-resolving to "tidy up"
    would be the repair §9 forbids.
    """
    harness = Harness()
    question_id = await _question_over_one_assertion(harness)
    intercepted = _InterceptedStore(harness.deferrals, after="resolve")
    stage = QuestionStage(
        writer=harness.writer, deferrals=intercepted, memory=harness.memory, now=_clock
    )

    answering = asyncio.ensure_future(stage.answer(question_id, accept=True))
    await intercepted.entered.wait()
    answering.cancel()
    intercepted.proceed.set()
    with pytest.raises(asyncio.CancelledError):
        await answering

    settled = await harness.deferrals.get(question_id)
    assert settled is not None
    assert settled.state is DeferralState.ACCEPTED
    assert settled.outcome_record_id is not None
    assert await harness.memory.get(settled.outcome_record_id) is not None


async def test_cancelling_resolve_before_its_commit_leaves_the_row_applying() -> None:
    """The same window on the other side of the compare-and-set (§9).

    Cancelled before it commits, the row is still ``APPLYING`` — stranded like the
    rest — and the memory write has already landed. Both states are already right, and
    the assertion is that neither is "repaired", because the coordinator cannot tell
    which it has.
    """
    harness = Harness()
    question_id = await _question_over_one_assertion(harness)
    intercepted = _InterceptedStore(harness.deferrals, before="resolve")
    stage = QuestionStage(
        writer=harness.writer, deferrals=intercepted, memory=harness.memory, now=_clock
    )

    answering = asyncio.ensure_future(stage.answer(question_id, accept=True))
    await intercepted.entered.wait()
    answering.cancel()
    intercepted.proceed.set()
    with pytest.raises(asyncio.CancelledError):
        await answering

    stranded = await harness.deferrals.get(question_id)
    assert stranded is not None
    assert stranded.state is DeferralState.APPLYING
    assert stranded.answered_at is None
    assert await harness.memory.get("live-1") is None, "the correction did land"


async def test_cancelling_the_successor_defer_after_its_commit_keeps_the_link() -> None:
    """The re-deferral branch's own window (§9).

    Cancelled after the admission commits and before it returns, the parent is
    ``APPLYING`` **and already carries a ``successor_id``**, with the successor
    admitted. Nothing is undone: deleting the successor to "unwind" a cancelled call
    would destroy the one thing that call got right.
    """
    harness = Harness()
    question_id = await _question_over_one_assertion(harness)
    await harness.memory.add(_record("live-2", _LISBON))
    intercepted = _InterceptedStore(harness.deferrals, after="defer")
    stage = QuestionStage(
        writer=harness.writer, deferrals=intercepted, memory=harness.memory, now=_clock
    )

    answering = asyncio.ensure_future(stage.answer(question_id, accept=True))
    await intercepted.entered.wait()
    answering.cancel()
    intercepted.proceed.set()
    with pytest.raises(asyncio.CancelledError):
        await answering

    parent = await harness.deferrals.get(question_id)
    assert parent is not None
    assert parent.state is DeferralState.APPLYING
    assert parent.successor_id is not None, "the successor's admission is not unwound"
    successor = await harness.deferrals.get(parent.successor_id)
    assert successor is not None
    assert successor.state is DeferralState.PENDING
    # The parent is shown with the row its answer raised, rendered by that row's own
    # state — a PENDING one being the only follow-on the user can act on (§9).
    [shown] = await harness.restarted().interrupted_questions()
    assert shown.successor is not None
    assert shown.successor.id == successor.id
    assert shown.successor.state is QuestionState.OPEN


async def test_cancelling_the_rejection_before_its_cas_leaves_the_question_answerable() -> None:
    """The rejection path's single window, before its unclaimed compare-and-set (§9).

    The gentlest of the five: a rejection takes no claim, so it leaves nothing
    half-done and the question is still ``PENDING`` and fully answerable. The
    accept-path cases cannot show this, because they all start from a claim.
    """
    harness = Harness()
    question_id = await _question_over_one_assertion(harness)
    intercepted = _InterceptedStore(harness.deferrals, before="resolve")
    stage = QuestionStage(
        writer=harness.writer, deferrals=intercepted, memory=harness.memory, now=_clock
    )

    answering = asyncio.ensure_future(stage.answer(question_id, accept=False))
    await intercepted.entered.wait()
    answering.cancel()
    intercepted.proceed.set()
    with pytest.raises(asyncio.CancelledError):
        await answering

    still_open = await harness.deferrals.get(question_id)
    assert still_open is not None
    assert still_open.state is DeferralState.PENDING
    [shown] = await harness.questions.questions()
    assert shown.id == question_id


async def test_cancelling_the_rejection_after_its_cas_keeps_the_retained_row() -> None:
    """The same window on the other side: a retained ``REJECTED`` row (§9).

    Which is what the answer meant. Retention is what makes the dedup honest — without
    it a chatty producer re-proposes tomorrow and the user is asked something they
    already declined.
    """
    harness = Harness()
    question_id = await _question_over_one_assertion(harness)
    intercepted = _InterceptedStore(harness.deferrals, after="resolve")
    stage = QuestionStage(
        writer=harness.writer, deferrals=intercepted, memory=harness.memory, now=_clock
    )

    answering = asyncio.ensure_future(stage.answer(question_id, accept=False))
    await intercepted.entered.wait()
    answering.cancel()
    intercepted.proceed.set()
    with pytest.raises(asyncio.CancelledError):
        await answering

    declined = await harness.deferrals.get(question_id)
    assert declined is not None
    assert declined.state is DeferralState.REJECTED
    assert declined.claimed_at is None, "a rejection takes no claim"


# --------------------------------------------------------------------------- #
# The other endings, and the total outcome mapping                            #
# --------------------------------------------------------------------------- #


async def test_rejecting_a_question_writes_nothing_and_retains_the_record() -> None:
    """§6's reject: nothing written, the record retained, no claim taken."""
    harness = Harness()
    question_id = await _question_over_one_assertion(harness)

    answered = await harness.questions.answer(question_id, accept=False)

    assert answered.kind is AnswerKind.REJECTED
    assert answered.record_id is None
    assert await harness.memory.get("live-1") is not None
    declined = await harness.deferrals.get(question_id)
    assert declined is not None
    assert declined.state is DeferralState.REJECTED
    assert await harness.questions.questions() == ()


async def test_answering_a_question_that_is_not_open_writes_nothing() -> None:
    """A second answer, and an id naming nothing, both come back as not open (§9)."""
    harness = Harness()
    question_id = await _question_over_one_assertion(harness)
    assert (await harness.questions.answer(question_id, accept=True)).kind is AnswerKind.APPLIED

    again = await harness.questions.answer(question_id, accept=True)
    unknown = await harness.questions.answer("no-such-question", accept=True)
    refused = await harness.questions.answer("no-such-question", accept=False)

    assert again.kind is AnswerKind.NOT_OPEN
    assert unknown.kind is AnswerKind.NOT_OPEN
    assert refused.kind is AnswerKind.NOT_OPEN


async def test_an_answer_to_a_proposal_whose_window_has_closed_is_stale() -> None:
    """§6's third ending, and it is not the same as a lapsed deadline (§10 item 3).

    The proposal's own **envelope** window was closed at the answer instant, so
    accepting would write a record every later read hides — a belief born dead. Two
    independent deadlines: ``expires_at`` says *the question* went unanswered too
    long, and ``STALE`` says *the answer arrived, and the thing it was about no longer
    applies*. Collapsing them would tell a user who answered promptly that they were
    too slow.
    """
    harness = Harness()
    await harness.memory.add(_record("live-1", _LISBON))
    outcome = await harness.writes.write(
        _proposal("new-1", _LISBON, validity=Validity(valid_until=AT - timedelta(days=1)))
    )
    assert outcome.admission is not None
    assert outcome.admission.deferral is not None
    question_id = outcome.admission.deferral.id

    answered = await harness.questions.answer(question_id, accept=True)

    assert answered.kind is AnswerKind.STALE
    assert answered.record_id is None
    assert not answered.disposed
    assert await harness.memory.get("live-1") is not None, "nothing was retired"
    assert len(await harness.memory.export()) == 1, "and nothing was written"
    stale = await harness.deferrals.get(question_id)
    assert stale is not None
    assert stale.state is DeferralState.STALE


async def test_an_accept_whose_confirmed_ingest_rules_reject_resolves_rather_than_stranding() -> (
    None
):
    """§2's totality clause, and the only thing that reaches it (§10 item 3).

    ``MemoryWriter`` takes an injected policy, and a conforming policy that is not
    ``DefaultMemoryPolicy`` may rule ``REJECT`` on a confirmed proposal. Without a
    legal ``APPLYING → REJECTED`` transition such an answer strands forever — which is
    exactly why this needs a test rather than an argument.
    """
    harness = Harness(policy=_DefersThenRules(MemoryDecisionKind.REJECT))
    question_id = await _question_over_one_assertion(harness)

    answered = await harness.questions.answer(question_id, accept=True)

    assert answered.kind is AnswerKind.REJECTED
    assert answered.record_id is None
    resolved = await harness.deferrals.get(question_id)
    assert resolved is not None
    assert resolved.state is DeferralState.REJECTED
    assert resolved.claimed_at is not None, "this one was claimed, unlike a user's rejection"
    assert await harness.deferrals.interrupted() == [], "and it did not strand"


# --------------------------------------------------------------------------- #
# §9's two-step recovery, and §7's reversal path                              #
# --------------------------------------------------------------------------- #


async def test_disposing_of_a_stranded_question_unblocks_a_re_learn() -> None:
    """§9's two-step recovery, end to end (§10 item 3).

    The ordering is the whole point: while the stranded row lives it holds its
    ``question_key``, so a re-proposal of the same correction collides with it and is
    handed back an id nothing can claim. Deleting destroys the key with the content,
    which unblocks it. Step 2 is ``beliefs`` then ``learn`` — the correction path
    ADR-0073 §6 says is the only one — and deliberately **not** a retry.
    """
    harness = Harness()
    question_id = await _question_over_one_assertion(harness)
    # A crash after the claim, reached by a cancellation inside the ingest.
    failing = _GatedWriter(harness.writer, raises=MemoryStoreError("the store went away"))
    failing.proceed.set()
    stranding = QuestionStage(
        writer=failing, deferrals=harness.deferrals, memory=harness.memory, now=_clock
    )
    with pytest.raises(MemoryStoreError):
        await stranding.answer(question_id, accept=True)

    # Step 0: a re-`learn` while the row lives is handed the stranded question back.
    blocked = await harness.writes.write(_proposal("new-1", _LISBON))
    assert blocked.admission is not None
    assert blocked.admission.outcome.value == "suppressed"
    assert blocked.admission.deferral is not None
    assert blocked.admission.deferral.id == question_id
    assert blocked.admission.deferral.state is DeferralState.APPLYING

    # Step 1: dispose of it.
    assert await harness.questions.forget_question(question_id)

    # Step 2: re-`learn` now admits a *fresh* question.
    fresh = await harness.writes.write(_proposal("new-1", _LISBON))
    assert fresh.admission is not None
    assert fresh.admission.outcome.value == "admitted"
    assert fresh.admission.deferral is not None
    assert fresh.admission.deferral.id != question_id


async def test_a_declined_question_must_be_forgotten_before_it_is_asked_again() -> None:
    """§7's reversal path, pinned rather than described — under ``deferral_ttl=None``.

    This is the claim an earlier revision of ADR-0078 made and could not keep: an
    immediate change of mind is *not* reachable by ``learn`` alone for an identical
    re-proposal, because ``learn`` produces the same key, the store hands back the
    rejected row, and that row is not ``PENDING`` so it cannot be answered —
    permanently, under "ask me forever". So the reversal is two steps: forget the
    prior question, then ``learn`` again. Waiting out the retention works too, when
    there is one; here there is not, which is the case that has to hold.
    """
    harness = Harness(retention=None)
    question_id = await _question_over_one_assertion(harness)
    assert (await harness.questions.answer(question_id, accept=False)).kind is AnswerKind.REJECTED

    # `learn` alone is suppressed, and the user is told which question stands in the
    # way and in what state.
    suppressed = await harness.writes.write(_proposal("new-1", _LISBON))
    assert suppressed.admission is not None
    assert suppressed.admission.outcome.value == "suppressed"
    assert suppressed.admission.deferral is not None
    assert suppressed.admission.deferral.id == question_id
    assert suppressed.admission.deferral.state is DeferralState.REJECTED
    assert await harness.questions.questions() == ()

    assert await harness.questions.forget_question(question_id)
    reversed_ = await harness.writes.write(_proposal("new-1", _LISBON))

    assert reversed_.admission is not None
    assert reversed_.admission.outcome.value == "admitted"
    [asked_again] = await harness.questions.questions()
    assert asked_again.id != question_id


async def test_a_proposal_mutated_mid_ingest_cannot_change_what_is_queued() -> None:
    """ADR-0065 at the write stage, and the hole it closes is a credential (§1).

    The tier check and the queued snapshot both happen *after* the ingest returns, so
    an unsnapshotted stage reads the caller's object across an await. A model tampered
    past ``frozen=True`` is inside this repository's threat model (ADR-0018 §3,
    ADR-0021 §4) — it is the very threat check 0 exists for — and the writer's own
    snapshot protects the *writer*, not this stage.

    So: rule on a secret, flip ``sensitivity`` to ``PERSONAL`` while the ingest is in
    flight, and let it return. An unsnapshotted stage queues the credential — ADR-0004
    §3's "never in a database", reached through the one filter written to prevent it.
    """
    harness = Harness()
    gated = _GatedWriter(harness.writer)
    stage = MemoryWriteStage(writer=gated, deferrals=harness.deferrals)
    secret = _proposal("secret-1", "the api key is hunter2", sensitivity=DataTier.SECRET)

    writing = asyncio.ensure_future(stage.write(secret))
    await gated.entered.wait()
    object.__setattr__(secret, "sensitivity", DataTier.PERSONAL)  # past `frozen=True`
    gated.proceed.set()
    outcome = await writing

    assert outcome.result.decision.kind is MemoryDecisionKind.ASK_USER
    assert outcome.admission is None, "the tier the writer ruled on is the tier queued"
    assert await harness.deferrals.export() == []


async def test_a_content_mutation_mid_ingest_cannot_change_the_queued_question() -> None:
    """The same window, seen on the ordinary path (ADR-0065).

    Not only the tier: the whole snapshot is built after the await, so a mutation
    landing there would park a question about words the policy never ruled on — and
    the user would be asked to confirm something nobody proposed.
    """
    harness = Harness()
    gated = _GatedWriter(harness.writer)
    stage = MemoryWriteStage(writer=gated, deferrals=harness.deferrals)
    await harness.memory.add(_record("live-1", _LISBON))
    submitted = _proposal("new-1", _LISBON)

    writing = asyncio.ensure_future(stage.write(submitted))
    await gated.entered.wait()
    object.__setattr__(submitted, "rationale", "something else entirely")
    gated.proceed.set()
    outcome = await writing

    assert outcome.admission is not None
    parked = outcome.admission.deferral
    assert parked is not None
    assert parked.proposal.rationale == "the user said so", "the version that was ruled on"
