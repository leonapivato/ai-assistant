"""The cross-field invariants that promote with the fields (ADR-0085 §4b).

**A field list is not the whole of a DTO's contract, and dropping an invariant
while promoting one is the quiet way to lose it.** Five of the promoted types
carry a cross-field rule — four state one in the text they carried in
`orchestration`, and ``BeliefSummary`` acquires one with its counts (§4a) — and
each becomes a model validator here, which is precisely the "what it adds is
validation" ADR-0084 §4 names as the reason for moving to pydantic at all.

Each case below asserts **both** directions where the rule has two, because an
invariant tested only in the direction that fires is half a rule: a model that
required a confirmation on a parked step but happily carried one on a denied step
would pass a one-sided test while offering a prompt for an action nobody is
waiting on.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from ai_assistant.core.types import (
    AnswerKind,
    AnswerOutcome,
    BeliefBand,
    BeliefSummary,
    Confirmation,
    ContinuationToken,
    Disposition,
    ExecutionState,
    IngestSummary,
    LearnDecision,
    MemoryKind,
    QuestionState,
    QueuedQuestion,
    QueueOutcome,
    StepOutcome,
)

AT = datetime(2026, 8, 1, 12, 0, 0, tzinfo=UTC)


def _state() -> ExecutionState:
    """One durable execution state, with no step to speak of."""
    return ExecutionState(id="e-1", plan_id="p-1", steps=(), updated_at=AT)


def _confirmation() -> Confirmation:
    """One confirmation, with its opaque token."""
    return Confirmation(
        tool_id="t-1",
        tool_description="send",
        parameters={},
        reason="an off-device disclosure",
        token=ContinuationToken(handle="h-1"),
    )


class TestStepOutcome:
    """The invariant a wire client cannot work around (§4b, listed first there)."""

    def test_a_parked_step_must_carry_its_confirmation(self) -> None:
        """ADR-0042 §4 obliges a parked result to carry what the adapter relays.

        A nullable field with no invariant permits an ``AWAITING_CONFIRMATION``
        outcome carrying neither content nor token, and a client handed one has
        nothing to resume with and no contract violation to point at.
        """
        with pytest.raises(ValidationError, match="AWAITING_CONFIRMATION"):
            StepOutcome(
                disposition=Disposition.AWAITING_CONFIRMATION, state=_state(), step_id="s-1"
            )

    def test_a_step_that_did_not_park_carries_no_confirmation(self) -> None:
        """The other direction: a prompt for an action nobody is waiting on."""
        with pytest.raises(ValidationError, match="DENIED"):
            StepOutcome(
                disposition=Disposition.DENIED,
                state=_state(),
                step_id="s-1",
                confirmation=_confirmation(),
            )

    def test_the_two_admissible_shapes_construct(self) -> None:
        """The discriminating half: the rule refuses what it must and nothing else."""
        parked = StepOutcome(
            disposition=Disposition.AWAITING_CONFIRMATION,
            state=_state(),
            step_id="s-1",
            confirmation=_confirmation(),
        )
        assert parked.confirmation is not None
        assert (
            StepOutcome(
                disposition=Disposition.EXECUTED, state=_state(), step_id="s-1"
            ).confirmation
            is None
        )

    def test_the_step_id_is_required_and_never_none(self) -> None:
        """§7: an optional field here would be an optionality nothing can produce.

        A turn whose plan had no step returns ``TurnOutcome(step=None)`` and
        constructs no :class:`StepOutcome` at all, so every client would carry a
        ``None`` branch it can never reach.
        """
        with pytest.raises(ValidationError):
            StepOutcome(disposition=Disposition.EXECUTED, state=_state())  # type: ignore[call-arg]

    def test_a_blank_step_id_is_refused(self) -> None:
        """It is the key that addresses ``state.steps``; a blank one addresses nothing."""
        with pytest.raises(ValidationError):
            StepOutcome(disposition=Disposition.EXECUTED, state=_state(), step_id="   ")


class TestIngestSummary:
    """ADR-0078 §10 item 9: a deferral says where its question went."""

    def test_a_deferral_must_say_where_its_question_went(self) -> None:
        """Including the secret-tier one nothing queues — that is the point of the rule."""
        with pytest.raises(ValidationError, match="DEFERRED"):
            IngestSummary(decision=LearnDecision.DEFERRED, record_id=None, reason="ask the user")

    def test_a_ruling_that_raised_no_question_queues_none(self) -> None:
        """A ``STORED`` outcome carrying a question would name one nobody can act on."""
        with pytest.raises(ValidationError, match="STORED"):
            IngestSummary(
                decision=LearnDecision.STORED,
                record_id="rec-1",
                reason="written",
                queued=QueuedQuestion(outcome=QueueOutcome.QUEUED, question_id="q-1"),
            )

    def test_the_two_admissible_shapes_construct(self) -> None:
        """A deferral with its question, and a write without one."""
        deferred = IngestSummary(
            decision=LearnDecision.DEFERRED,
            record_id=None,
            reason="ask the user",
            queued=QueuedQuestion(outcome=QueueOutcome.NOT_QUEUABLE),
        )
        assert deferred.stored is False
        stored = IngestSummary(decision=LearnDecision.STORED, record_id="rec-1", reason="written")
        assert stored.stored is True


class TestQueuedQuestion:
    """ADR-0078 §7, stated in one direction only and deliberately so."""

    @pytest.mark.parametrize("outcome", [QueueOutcome.QUEUE_FULL, QueueOutcome.NOT_QUEUABLE])
    def test_an_outcome_that_queued_nothing_names_nothing(self, outcome: QueueOutcome) -> None:
        """There is no question to read, so naming one would point at nothing."""
        with pytest.raises(ValidationError, match=outcome.name):
            QueuedQuestion(outcome=outcome, question_id="q-1")
        with pytest.raises(ValidationError, match=outcome.name):
            QueuedQuestion(outcome=outcome, question_state=QuestionState.OPEN)

    def test_the_converse_is_deliberately_not_asserted(self) -> None:
        """§4b: a ``QUEUED`` outcome naming no question still constructs.

        The converse is *nearly* true and is not asserted, because the projection
        keeps a defensive branch for an admission whose deferral is absent, which
        :class:`~ai_assistant.core.types.DeferralAdmission`'s own validator is
        supposed to make unreachable. Asserting it would turn a store-conformance
        fault into an unconstructable DTO — which is §4's ``confidence`` reasoning
        applied to a different field.
        """
        assert QueuedQuestion(outcome=QueueOutcome.QUEUED).question_id is None


class TestAnswerOutcome:
    """ADR-0078 §8's two rules about what an answer leaves behind."""

    def test_an_applied_answer_names_the_record_it_left_live(self) -> None:
        """Otherwise it claims a correction landed while naming nothing."""
        with pytest.raises(ValidationError, match="APPLIED"):
            AnswerOutcome(kind=AnswerKind.APPLIED, question_id="q-1")

    def test_an_answer_that_wrote_nothing_names_no_record(self) -> None:
        """The other direction: a rejection with a record id is a lie about a write."""
        with pytest.raises(ValidationError, match="REJECTED"):
            AnswerOutcome(kind=AnswerKind.REJECTED, question_id="q-1", record_id="rec-1")

    @pytest.mark.parametrize(
        "kind", [AnswerKind.APPLIED, AnswerKind.REJECTED, AnswerKind.STALE, AnswerKind.NOT_OPEN]
    )
    def test_only_a_re_deferral_carries_a_successor(self, kind: AnswerKind) -> None:
        """A follow-on question belongs to a re-deferral alone (§8)."""
        record_id = "rec-1" if kind is AnswerKind.APPLIED else None
        with pytest.raises(ValidationError, match=kind.name):
            AnswerOutcome(kind=kind, question_id="q-1", record_id=record_id, successor_refused=True)

    def test_a_re_deferral_may_carry_one_or_report_that_it_could_not(self) -> None:
        """The discriminating half, over the one outcome the rule admits."""
        assert (
            AnswerOutcome(
                kind=AnswerKind.REDEFERRED, question_id="q-1", successor_refused=True
            ).successor
            is None
        )


class TestBeliefSummary:
    """The price of counts-as-fields (§4a, §4b)."""

    def test_more_citations_cannot_be_gone_than_were_made(self) -> None:
        """On ``Belief`` the counts cannot disagree with the evidence; here they can.

        Moving them to fields is what buys the listing its shape — no field a
        citation's content could occupy — at the cost of the one constraint the
        model must now assert for itself.
        """
        with pytest.raises(ValidationError, match="lost_evidence"):
            _summary(evidence_count=1, lost_evidence=2)

    @pytest.mark.parametrize(
        ("cited", "lost", "unsupported"),
        [(0, 0, False), (2, 0, False), (2, 1, False), (2, 2, True)],
    )
    def test_unsupported_is_derived_from_the_two_counts(
        self, cited: int, lost: int, unsupported: bool
    ) -> None:
        """One definition everywhere, and a belief citing nothing is *not* unsupported.

        An assertion is supported by the user's own word (ADR-0038 §1a). It stays a
        property rather than a field because the counts already determine it: a
        field would be a second source of truth for a value a client can compute
        exactly, so one implementation could send it and another omit it, and the
        same call would measure two different sizes against the contract limit.
        """
        assert _summary(evidence_count=cited, lost_evidence=lost).unsupported is unsupported

    def test_it_has_no_evidence_field_at_all(self) -> None:
        """§4a's structural guarantee: the wrong behaviour is unrepresentable.

        Every alternative shape leaves a ``beliefs()`` implementation *able* to ship
        citation contents, so the ratified split survives only as a clause a
        conformance suite has to police.
        """
        assert "evidence" not in BeliefSummary.model_fields


def _summary(*, evidence_count: int = 0, lost_evidence: int = 0) -> BeliefSummary:
    """One listing row with the given counts."""
    return BeliefSummary(
        id="rec-1",
        band=BeliefBand.DERIVED,
        kind=MemoryKind.SEMANTIC,
        content="the office is in Boston",
        confidence=0.5,
        last_updated=AT,
        evidence_count=evidence_count,
        lost_evidence=lost_evidence,
    )
