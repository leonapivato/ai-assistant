"""Tests for the RuleBasedFeedbackProcessor (feedback -> memory proposal)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from feedback_processor_contract import FeedbackProcessorContract

from ai_assistant.core.clock import ClockReadingError
from ai_assistant.core.protocols import FeedbackProcessor
from ai_assistant.core.types import (
    FeedbackEvent,
    FeedbackKind,
    MemoryKind,
    MemorySource,
    PreferenceMemory,
    SemanticMemory,
)
from ai_assistant.learning import RuleBasedFeedbackProcessor

#: When the user *said* it: the event's own instant, and a fact about the world.
_WHEN = datetime(2026, 1, 1, tzinfo=UTC)

#: When *we* wrote it down: this processor's injected clock, and a fact about the
#: write. Deliberately a different value from ``_WHEN`` everywhere, because the
#: two are different quantities and only a live path puts them close together
#: (ADR-0045 §3, #775).
_WRITTEN_AT = datetime(2026, 3, 2, 17, 45, tzinfo=UTC)


def _event(  # noqa: PLR0913 — one keyword per event field a case may need to vary
    *,
    kind: FeedbackKind = FeedbackKind.PREFERENCE,
    memory_kind: MemoryKind = MemoryKind.PREFERENCE,
    content: str = "prefers concise replies",
    subject: str | None = None,
    about_person: str | None = None,
    evidence: tuple[str, ...] = (),
    created_at: datetime = _WHEN,
) -> FeedbackEvent:
    return FeedbackEvent(
        kind=kind,
        memory_kind=memory_kind,
        content=content,
        subject=subject,
        about_person=about_person,
        evidence=evidence,
        created_at=created_at,
    )


def _processor() -> RuleBasedFeedbackProcessor:
    return RuleBasedFeedbackProcessor(id_factory=lambda: "rec-1", now=lambda: _WRITTEN_AT)


class TestRuleBasedFeedbackProcessorContract(FeedbackProcessorContract):
    """Runs RuleBasedFeedbackProcessor through the shared FeedbackProcessor suite."""

    @pytest.fixture
    def processor(self) -> FeedbackProcessor:
        return RuleBasedFeedbackProcessor()


def test_conforms_to_protocol() -> None:
    assert isinstance(RuleBasedFeedbackProcessor(), FeedbackProcessor)


async def test_preference_feedback_becomes_a_user_asserted_preference() -> None:
    event = _event(subject="email tone", evidence=("ep-9",))

    [proposal] = await _processor().process(event)

    record = proposal.proposed
    assert isinstance(record, PreferenceMemory)
    assert record.id == "rec-1"
    assert record.preference == "prefers concise replies"
    assert record.context == "email tone"
    assert record.provenance.source is MemorySource.USER_ASSERTED
    assert record.provenance.confidence == 1.0
    assert record.provenance.evidence == ("ep-9",)
    assert record.provenance.last_updated == _WRITTEN_AT  # our clock, not the event's


async def test_semantic_correction_becomes_a_semantic_memory() -> None:
    event = _event(
        kind=FeedbackKind.CORRECTION,
        memory_kind=MemoryKind.SEMANTIC,
        content="office is in Boston",
    )

    [proposal] = await _processor().process(event)

    record = proposal.proposed
    assert isinstance(record, SemanticMemory)  # a fact-correction is not a preference
    assert record.fact == "office is in Boston"
    assert record.provenance.source is MemorySource.USER_ASSERTED


async def test_procedural_and_episodic_targets_are_deferred() -> None:
    processor = _processor()

    assert await processor.process(_event(memory_kind=MemoryKind.PROCEDURAL)) == []
    assert await processor.process(_event(memory_kind=MemoryKind.EPISODIC)) == []


# --- the subject axis: the user's route into it (ADR-0100 §7) ----------------


async def test_a_stated_subject_reaches_the_preference_branch() -> None:
    """The scope and the subject land in their own places, not each other's."""
    event = _event(subject="travel", about_person="Marta")

    [proposal] = await _processor().process(event)

    record = proposal.proposed
    assert isinstance(record, PreferenceMemory)
    assert record.about_person == "Marta"
    assert record.context == "travel"  # the scope axis, unmoved


async def test_a_stated_subject_reaches_the_semantic_branch_too() -> None:
    """The branch that discards a *scope* must still carry the subject.

    This is the specific way ADR-0100 §7 could be got wrong, because the two
    fields look alike at the call site: the semantic branch has nowhere to put a
    ``subject`` scope and drops it, as ADR-0009 §1 decided. Dropping the subject
    with it would write ``None``, which ADR-0100 §3 reads as *the owner's*, over a
    subject the user had just stated — the false record §7's route exists to
    avoid, reintroduced one layer down.
    """
    event = _event(
        kind=FeedbackKind.CORRECTION,
        memory_kind=MemoryKind.SEMANTIC,
        content="works from the Lisbon office",
        subject="offices",
        about_person="Marta",
    )

    [proposal] = await _processor().process(event)

    record = proposal.proposed
    assert isinstance(record, SemanticMemory)
    assert record.about_person == "Marta"


async def test_the_subject_is_carried_verbatim() -> None:
    """Nothing on the way in normalises a label (ADR-0100 §6)."""
    [proposal] = await _processor().process(_event(about_person="  marta  "))

    assert proposal.proposed.about_person == "  marta  "


@pytest.mark.parametrize("memory_kind", [MemoryKind.PREFERENCE, MemoryKind.SEMANTIC])
async def test_an_unstated_subject_stays_unstated(memory_kind: MemoryKind) -> None:
    """Silence is carried across as silence, never repaired into a name."""
    [proposal] = await _processor().process(_event(memory_kind=memory_kind))

    assert proposal.proposed.about_person is None


async def test_rationale_records_the_feedback() -> None:
    [proposal] = await _processor().process(_event(content="likes tea"))
    assert "likes tea" in proposal.rationale


async def test_deferred_target_does_not_consume_an_id() -> None:
    issued: list[str] = []

    def factory() -> str:
        issued.append(f"id-{len(issued) + 1}")
        return issued[-1]

    processor = RuleBasedFeedbackProcessor(id_factory=factory)

    assert await processor.process(_event(memory_kind=MemoryKind.PROCEDURAL)) == []
    assert issued == []  # a deferred target minted no id

    [proposal] = await processor.process(_event(memory_kind=MemoryKind.PREFERENCE))
    assert proposal.proposed.id == "id-1"  # the first id goes to the first real record


async def test_the_confirming_instant_is_the_utterances_and_not_the_write() -> None:
    """ADR-0109 §4's ``ASSERTED`` arm: the user stating it is the confirming event.

    ``last_confirmed_at`` is ``event.created_at``, so a feedback event re-processed
    a month later does not look freshly confirmed. That is the same discipline
    which keeps ``ATTESTED`` off our ingestion clock and ``DERIVED`` off the moment
    of derivation (ADR-0103 §9).

    ADR-0109 §10 recorded that the two fields coincided here by construction, and
    exempted this case from its distinctness rule for that reason. #775 removed the
    coincidence — the transaction stamp is now this processor's own clock — so the
    fixture *can* hold them apart, and the case below does. The exemption is
    therefore unused rather than wrong, and the two cases §10's third clause names
    (the calendar reader's ``read_at`` against its ``reported_at``, and the fold's
    survivor taking the two from different sides) still carry the obligation on
    their own.

    The equality is deliberately written against the event rather than against
    ``last_updated``, which is what keeps this claim about the *confirming* instant
    however the transaction stamp is later sourced.
    """
    when = datetime(2025, 11, 30, 9, 15, tzinfo=UTC)

    [proposal] = await _processor().process(_event(created_at=when))

    assert proposal.proposed.provenance.last_confirmed_at == when


async def test_a_feedback_event_created_in_our_future_is_stored_unchanged() -> None:
    """ADR-0109 §4's fourth clause, at the ``ASSERTED`` producer.

    ``FeedbackEvent.created_at`` has no upper bound, so this producer is separately
    capable of dropping or clamping an instant ahead of its own clock and must do
    neither — the usability test belongs to the fold, where two candidates exist.
    Asserting the exact instant refuses ``None``, a local clock reading and a clamp
    at once.
    """
    ahead = datetime(2027, 4, 1, tzinfo=UTC)

    [proposal] = await _processor().process(_event(created_at=ahead))

    assert proposal.proposed.provenance.last_confirmed_at == ahead


# --- the transaction stamp: our clock, not the event's (ADR-0045 §3, #775) ---


async def test_the_transaction_stamp_is_our_clock_and_not_the_events() -> None:
    """``last_updated`` is when *we* revised the belief, not when the user spoke.

    ADR-0045 §3 defines the field as transaction time — "the clock of the store
    changing its mind, not the clock of when the belief holds" — and
    ``FeedbackEvent.created_at`` is a fact about the world instead. A queued,
    retried or replayed event separates the two by exactly its delay, so the case
    below dates the utterance months before the write: taking the stamp from the
    event would have the record claim a revision at an instant nothing was revised
    at (#775).

    Both instants are asserted in one case, because the defect was precisely that
    one value stood in for both. The inequality is asserted as well as the two
    equalities, so a future edit that re-coupled the fields would have to delete a
    line that says so rather than quietly satisfy a pair of equalities.
    """
    spoken_at = datetime(2025, 11, 30, 9, 15, tzinfo=UTC)

    [proposal] = await _processor().process(_event(created_at=spoken_at))

    provenance = proposal.proposed.provenance
    assert provenance.last_updated == _WRITTEN_AT
    assert provenance.last_confirmed_at == spoken_at
    assert provenance.last_updated != provenance.last_confirmed_at


async def test_the_clock_is_read_at_each_write_not_once_at_construction() -> None:
    """A clock is a callable whose readings move, and each write takes its own.

    A processor that read the clock in ``__init__`` would stamp every record of its
    lifetime with the instant it was wired, which is a transaction time only for
    the first write. The two events here are identical apart from the reading the
    clock has moved on to.
    """
    readings = iter([_WRITTEN_AT, _WRITTEN_AT + timedelta(hours=3)])
    processor = RuleBasedFeedbackProcessor(id_factory=lambda: "rec-1", now=lambda: next(readings))

    [first] = await processor.process(_event())
    [second] = await processor.process(_event())

    assert first.proposed.provenance.last_updated == _WRITTEN_AT
    assert second.proposed.provenance.last_updated == _WRITTEN_AT + timedelta(hours=3)


async def test_a_deferred_target_reads_no_clock() -> None:
    """The clock is read where a record is minted, beside the id and not before it.

    The sibling of ``test_deferred_target_does_not_consume_an_id``: a deferred kind
    proposes nothing, so it has nothing to stamp. Reading anyway would consume a
    reading from a scripted clock and would make a misconfigured clock fail a call
    that today returns an empty sequence and touches no seam at all.
    """
    readings: list[datetime] = []

    def clock() -> datetime:
        readings.append(_WRITTEN_AT)
        return readings[-1]

    processor = RuleBasedFeedbackProcessor(id_factory=lambda: "rec-1", now=clock)

    assert await processor.process(_event(memory_kind=MemoryKind.PROCEDURAL)) == []
    assert await processor.process(_event(memory_kind=MemoryKind.EPISODIC)) == []
    assert readings == []  # a deferred target read nothing

    [proposal] = await processor.process(_event(memory_kind=MemoryKind.PREFERENCE))
    assert proposal.proposed.provenance.last_updated == _WRITTEN_AT
    assert len(readings) == 1  # one write, one reading


async def test_a_non_conforming_clock_reading_is_refused_and_names_this_seam() -> None:
    """ADR-0026 §§2, 7: the seam is guarded, and its diagnostic names it.

    A naive reading is the one every seam used to accept: ``astimezone`` would
    treat it as host-local and hand on a confidently wrong instant. `learning` has
    no error class of its own, so the ``ClockReadingError`` propagates unwrapped —
    a ``ValueError``, as ADR-0026 §4 requires, carrying the owner label that says
    which of two seams sharing one fixture got the bad reading.
    """
    naive = datetime(2026, 3, 2, 17, 45)  # noqa: DTZ001 — the naive reading is the subject
    processor = RuleBasedFeedbackProcessor(now=lambda: naive)

    with pytest.raises(ClockReadingError, match="RuleBasedFeedbackProcessor"):
        await processor.process(_event())


async def test_a_failure_of_the_clock_itself_is_not_relabelled() -> None:
    """ADR-0026 §2's reading/invocation boundary, at this seam.

    A clock provider that is simply down raises on its own account, and that
    failure keeps its own type and message: reporting it as a non-conforming
    *reading* would destroy the diagnosis. The guard is around the reading, never
    around the call.
    """

    def broken() -> datetime:
        msg = "the clock provider is down"
        raise RuntimeError(msg)

    processor = RuleBasedFeedbackProcessor(now=broken)

    with pytest.raises(RuntimeError, match="the clock provider is down"):
        await processor.process(_event())
