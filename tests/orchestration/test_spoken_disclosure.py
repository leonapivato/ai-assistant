"""ADR-0199's ruling, applied at supply on the spoken channel (ADR-0200 §7).

Two halves. The first is ``orchestration.disclosure`` on its own — the placement
rules of ADR-0199 §§2-3, decided from recorded origin and never from content. The
second is the engine driving them: a withheld class never reaching the composing
stage's inputs, the stage being told the audience and the bare fact of a
withholding, and nothing filtering the composed answer afterwards.
"""

from __future__ import annotations

from base64 import b64encode
from datetime import UTC, datetime
from typing import Final

import pytest
from test_engine import PATIENT, Harness

from ai_assistant.core.types import (
    ActionPlan,
    Attestation,
    CalendarFacet,
    ContextFacet,
    CurrentContext,
    EmailFacet,
    Goal,
    MemorySource,
    Provenance,
    Role,
    SemanticMemory,
    SpokenAudio,
    SpokenAudioFormat,
    TimeOfDay,
    TurnResult,
)
from ai_assistant.orchestration.composing import ComposingStage
from ai_assistant.orchestration.disclosure import (
    placed_facet_kinds,
    speakable_sources,
    supply_for_unbounded_audience,
)
from ai_assistant.testing import (
    FakeModelProvider,
    FakeSpeechSynthesizer,
    FakeSpeechTranscriber,
    FakeStreamingCompleter,
)

_AT: Final = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)
_MP4: Final = SpokenAudioFormat.MP4
_CALENDAR: Final = "calendar"
_ANSWER: Final = "You went hiking on Tuesday."

#: What a withheld record says. Recognisable, so an assertion can look for the
#: span itself rather than for "something about somebody else".
_WITHHELD_CONTENT: Final = "Alice is seeing a cardiologist on Friday"

_RECORDING: Final = SpokenAudio(content=b64encode(b"an utterance").decode("ascii"), media_type=_MP4)


def _belief(
    record_id: str,
    content: str,
    *,
    source: MemorySource = MemorySource.OBSERVED,
    about_person: str | None = None,
    reported_by: str | None = None,
) -> SemanticMemory:
    """One belief, with exactly the three fields ADR-0199 §2 decides a class from."""
    return SemanticMemory(
        id=record_id,
        content=content,
        fact=content,
        about_person=about_person,
        provenance=Provenance(
            source=source,
            confidence=1.0 if source is MemorySource.USER_ASSERTED else 0.6,
            last_updated=_AT,
            attestation=(
                None
                if reported_by is None
                else Attestation(reported_by=reported_by, reported_at=_AT)
            ),
        ),
    )


def _turn(*records: SemanticMemory, context: CurrentContext | None = None) -> TurnResult:
    """A turn carrying ``records`` and nothing else of interest."""
    goal = Goal(
        id="g-1",
        statement="what is on this week",
        provenance=Provenance(source=MemorySource.USER_ASSERTED, confidence=1.0, last_updated=_AT),
        created_at=_AT,
    )
    return TurnResult(
        goal=goal,
        context=context
        or CurrentContext(
            now=_AT, time_of_day=TimeOfDay.AFTERNOON, is_weekend=False, within_working_hours=True
        ),
        memories=records,
        plan=ActionPlan(id="p-1", goal_id=goal.id, steps=(), created_at=_AT),
    )


def _supply(turn: TurnResult, *, sources: frozenset[str] = frozenset()) -> tuple[TurnResult, bool]:
    return supply_for_unbounded_audience(turn, speakable_attested_sources=sources)


# --- §3: which classes are placed as speakable -------------------------------


@pytest.mark.parametrize(
    "source", [MemorySource.USER_ASSERTED, MemorySource.OBSERVED, MemorySource.INFERRED]
)
def test_the_owners_own_beliefs_are_speakable(source: MemorySource) -> None:
    """§3's first placement, and the one milestone 19's exit test runs on.

    "That answer is made of the owner's own beliefs and the calendar, and every one
    of those is placed speakable" — a rule that passed the safety test and failed
    the exit test would be a rule nobody could ship.
    """
    record = _belief("rec-1", "the user hikes on Tuesdays", source=source)

    supply, withheld = _supply(_turn(record))

    assert withheld is False
    assert supply.memories == (record,)


def test_a_belief_about_somebody_else_is_withheld() -> None:
    """§3: "any record whose ``MemoryBase.about_person`` is stated".

    The household clause, and it decides on its own: the person a belief is about
    is, in a household, exactly the person most likely to be in the room when it
    would be read aloud.
    """
    record = _belief("rec-1", _WITHHELD_CONTENT, about_person="Alice")

    supply, withheld = _supply(_turn(record))

    assert withheld is True
    assert supply.memories == ()


def test_an_attested_belief_from_the_configured_calendar_is_speakable() -> None:
    """§3's second placement: ``ATTESTED`` **and** ``reported_by`` names the calendar."""
    record = _belief(
        "rec-1", "standup at 09:00", source=MemorySource.EXTERNAL, reported_by=_CALENDAR
    )

    supply, withheld = _supply(_turn(record), sources=frozenset({_CALENDAR}))

    assert withheld is False
    assert supply.memories == (record,)


def test_an_attested_belief_from_any_other_source_is_withheld() -> None:
    """§3's fourth clause: an unplaced class is withheld until an ADR places it.

    The next source to land — a health integration, a message reader — is withheld
    on the day it merges rather than speakable by omission, which is the whole
    safety property of naming the speakable set rather than the withheld one.
    """
    record = _belief(
        "rec-1", "your test results are in", source=MemorySource.EXTERNAL, reported_by="health"
    )

    supply, withheld = _supply(_turn(record), sources=frozenset({_CALENDAR}))

    assert withheld is True
    assert supply.memories == ()


def test_an_attested_belief_with_no_attestation_is_withheld() -> None:
    """No recorded origin, no class, and §2's third clause withholds it.

    ADR-0092 §1 makes that shape unconstructible — an ``EXTERNAL`` provenance
    without an attestation is refused at validation — so the case is reached the
    only way it can be, through ``model_construct``, which "bypasses every
    validator while still satisfying ``isinstance``" (ADR-0032 §6's own argument
    for revalidating at a seam). The placement fails closed on it rather than
    reaching for an attribute that is not there.
    """
    speakable = _belief(
        "rec-1", "standup at 09:00", source=MemorySource.EXTERNAL, reported_by=_CALENDAR
    )
    unattested = speakable.model_copy(
        update={
            "provenance": Provenance.model_construct(
                source=MemorySource.EXTERNAL, confidence=0.6, last_updated=_AT, attestation=None
            )
        }
    )

    supply, withheld = _supply(_turn(unattested), sources=frozenset({_CALENDAR}))

    assert withheld is True
    assert supply.memories == ()


def test_no_configured_calendar_withholds_every_attested_belief() -> None:
    """The composition root's empty set, which withholds rather than guessing a name."""
    record = _belief(
        "rec-1", "standup at 09:00", source=MemorySource.EXTERNAL, reported_by=_CALENDAR
    )

    supply, withheld = _supply(_turn(record))

    assert withheld is True
    assert supply.memories == ()


def test_a_calendar_belief_about_somebody_else_is_still_withheld() -> None:
    """§3 places it "again where ``about_person`` is not stated" — the conjunction holds."""
    record = _belief(
        "rec-1",
        _WITHHELD_CONTENT,
        source=MemorySource.EXTERNAL,
        reported_by=_CALENDAR,
        about_person="Alice",
    )

    supply, withheld = _supply(_turn(record), sources=frozenset({_CALENDAR}))

    assert withheld is True
    assert supply.memories == ()


def test_the_placed_sources_are_the_three_the_adr_names() -> None:
    assert speakable_sources() == {
        MemorySource.USER_ASSERTED,
        MemorySource.OBSERVED,
        MemorySource.INFERRED,
    }


# --- §3: the two facets, and the one that has not landed ---------------------


def test_both_placed_facets_reach_the_stage() -> None:
    """§3: neither discloses anything an utterance could leak, by its own construction."""
    context = CurrentContext(
        now=_AT,
        time_of_day=TimeOfDay.AFTERNOON,
        is_weekend=False,
        within_working_hours=True,
        calendar=CalendarFacet(
            source=_CALENDAR, read_at=_AT, entries_in_progress=1, covers_until=_AT
        ),
        email=EmailFacet(source="email", read_at=_AT, arrived_in_window=2, covers_from=_AT),
    )

    supply, withheld = _supply(_turn(context=context))

    assert withheld is False
    assert supply.context is context


def test_a_facet_kind_no_adr_has_placed_is_withheld_by_construction() -> None:
    """§3's fourth clause, made structural rather than remembered.

    A facet added to :class:`~ai_assistant.core.types.CurrentContext` without a
    placement is withheld the day it lands, because the match is by **exact type**
    — a subclass of a placed facet is a different class and no ratified ADR has
    placed it.
    """

    class HealthFacet(CalendarFacet):
        """A facet nobody has placed, standing in for the next source to land."""

    context = CurrentContext(
        now=_AT,
        time_of_day=TimeOfDay.AFTERNOON,
        is_weekend=False,
        within_working_hours=True,
        calendar=HealthFacet(source="health", read_at=_AT, entries_in_progress=1, covers_until=_AT),
    )

    supply, withheld = _supply(_turn(context=context))

    assert withheld is True
    assert supply.context.calendar is None


def test_the_placed_kinds_cover_every_facet_the_context_can_hold() -> None:
    """The tripwire for a *third* facet: it fails here until an ADR places it.

    Read off :class:`~ai_assistant.core.types.CurrentContext`'s own annotations, so
    a member added there is compared against §3's list rather than silently
    withheld and never noticed.
    """
    held = {
        kind
        for name in CurrentContext.model_fields
        for kind in _facet_kinds(CurrentContext.model_fields[name].annotation)
    }
    assert held == placed_facet_kinds(), (
        "CurrentContext holds a facet kind ADR-0199 §3 has not placed; it is "
        "withheld from an unbounded channel until an ADR places it, and this "
        "assertion is where that is noticed"
    )


def _facet_kinds(annotation: object) -> set[type[ContextFacet]]:
    """Every ``ContextFacet`` subclass named inside one field annotation."""
    from typing import get_args  # noqa: PLC0415 — local to this walk

    if isinstance(annotation, type) and issubclass(annotation, ContextFacet):
        return {annotation}
    return {kind for arm in get_args(annotation) for kind in _facet_kinds(arm)}


# --- §5: the withholding subtracts, and changes nothing else -----------------


def test_a_turn_with_nothing_withheld_is_handed_over_unchanged() -> None:
    """§5: "The withholding subtracts from what the turn produced and adds nothing".

    Identity rather than equality, because a rebuilt-but-equal value would still be
    a second object the stage composes from and would hide a rebuild that dropped a
    member ``TurnResult`` grows later.
    """
    turn = _turn(_belief("rec-1", "the user hikes"))

    supply, withheld = _supply(turn)

    assert supply is turn
    assert withheld is False


def test_the_turn_the_reduction_was_made_from_is_not_modified() -> None:
    """§5: "The ``TurnResult`` the turn produced is unchanged"."""
    kept = _belief("rec-1", "the user hikes")
    dropped = _belief("rec-2", _WITHHELD_CONTENT, about_person="Alice")
    turn = _turn(kept, dropped)

    supply, _ = _supply(turn)

    assert turn.memories == (kept, dropped)
    assert supply.memories == (kept,)
    assert supply.goal is turn.goal
    assert supply.plan is turn.plan
    assert supply.memory_degraded == turn.memory_degraded


# --- §7: the engine driving it -----------------------------------------------


def _wired(model: FakeModelProvider, **knobs: object) -> Harness:
    """A harness whose composing stage runs over ``model``."""
    stage = ComposingStage(model=model, streaming=FakeStreamingCompleter())
    return Harness(composing=stage, **knobs)  # type: ignore[arg-type]  # heterogeneous knobs


def _messages(model: FakeModelProvider, role: Role) -> str:
    return next(one.content for one in model.calls[0].messages if one.role is role)


async def _seed(harness: Harness, *records: SemanticMemory) -> None:
    for record in records:
        await harness.memory.add(record)


async def test_a_withheld_class_never_reaches_the_composing_stages_inputs() -> None:
    """§7, ADR-0199 §5: withheld **at supply**, not filtered out of composed prose.

    The span is not in the prompt at all, which is a stronger claim than its being
    absent from the answer: a filter over composed prose is content inspection,
    which ADR-0199 §2 forbids as a decision procedure and which "fails silently on
    the first sentence phrased in a way the filter did not anticipate".
    """
    model = FakeModelProvider(_ANSWER)
    harness = _wired(model, transcriber=FakeSpeechTranscriber(transcripts=["what is on"]))
    await _seed(
        harness,
        _belief("rec-1", "the user hikes on Tuesdays"),
        _belief("rec-2", _WITHHELD_CONTENT, about_person="Alice"),
    )

    await harness.engine.converse_spoken(_RECORDING, plays=(_MP4,), timeout=PATIENT)

    prompt = _messages(model, Role.USER)
    assert "the user hikes on Tuesdays" in prompt
    assert _WITHHELD_CONTENT not in prompt
    assert "Alice" not in prompt


async def test_the_stage_is_told_that_a_withholding_occurred_and_nothing_about_it() -> None:
    """ADR-0199 §5: "the composing stage is told **that** a withholding occurred".

    One line of this system's own text, written by the renderer — which was never
    given the withheld material, so the line cannot carry a span, a paraphrase, a
    summary, a count, a category or a subject label however a later editor writes
    it.
    """
    model = FakeModelProvider(_ANSWER)
    harness = _wired(model, transcriber=FakeSpeechTranscriber(transcripts=["what is on"]))
    await _seed(harness, _belief("rec-2", _WITHHELD_CONTENT, about_person="Alice"))

    await harness.engine.converse_spoken(_RECORDING, plays=(_MP4,), timeout=PATIENT)

    assert "NOT AVAILABLE ON THIS CHANNEL" in _messages(model, Role.USER)


async def test_nothing_is_reported_withheld_when_nothing_was() -> None:
    """The other side: an ordinary answer says nothing about a withholding."""
    model = FakeModelProvider(_ANSWER)
    harness = _wired(model, transcriber=FakeSpeechTranscriber(transcripts=["what is on"]))
    await _seed(harness, _belief("rec-1", "the user hikes on Tuesdays"))

    await harness.engine.converse_spoken(_RECORDING, plays=(_MP4,), timeout=PATIENT)

    assert "NOT AVAILABLE ON THIS CHANNEL" not in _messages(model, Role.USER)


async def test_the_audience_reaches_the_stage_from_the_operation_being_executed() -> None:
    """ADR-0200 §3, §7: from the operation, never from an argument or a session.

    ``converse`` and ``converse_spoken`` differ in exactly this, and the difference
    is visible in the instruction the stage was given rather than asserted about a
    parameter nobody can see.
    """
    spoken_model = FakeModelProvider(_ANSWER)
    spoken = _wired(spoken_model, transcriber=FakeSpeechTranscriber(transcripts=["what is on"]))
    await spoken.engine.converse_spoken(_RECORDING, plays=(_MP4,), timeout=PATIENT)

    written_model = FakeModelProvider(_ANSWER)
    written = _wired(written_model)
    await written.engine.converse("what is on", timeout=PATIENT)

    assert "SPOKEN ALOUD" in _messages(spoken_model, Role.SYSTEM)
    assert "SPOKEN ALOUD" not in _messages(written_model, Role.SYSTEM)


async def test_a_written_turn_is_supplied_everything_the_spoken_one_is_not() -> None:
    """ADR-0199 §1: a posture decided for one channel does not reach another.

    The same belief on ``converse``, whose caller reads what it gets, is supplied
    to the stage — so what this lane added is a rule about *this channel* rather
    than a narrowing of what the assistant may know.
    """
    model = FakeModelProvider(_ANSWER)
    harness = _wired(model)
    await _seed(harness, _belief("rec-2", _WITHHELD_CONTENT, about_person="Alice"))

    await harness.engine.converse("what is on", timeout=PATIENT)

    assert _WITHHELD_CONTENT in _messages(model, Role.USER)


async def test_nothing_rewrites_the_composed_answer_and_the_rendering_is_that_value() -> None:
    """§7: "no component filters, redacts or post-processes ``outcome.reply``".

    There is **one** answer on this call: what the stage composed is what the
    outcome carries, and it is byte-for-byte what was handed to the synthesizer —
    so where a class was withheld, the deflection is the thing that is heard.
    """
    deflection = "There is something about that I would rather not say out loud."
    model = FakeModelProvider(deflection)
    harness = _wired(model, transcriber=FakeSpeechTranscriber(transcripts=["what is on"]))
    await _seed(harness, _belief("rec-2", _WITHHELD_CONTENT, about_person="Alice"))

    spoken = await harness.engine.converse_spoken(_RECORDING, plays=(_MP4,), timeout=PATIENT)

    assert spoken.outcome is not None
    assert spoken.outcome.reply == deflection
    assert _WITHHELD_CONTENT not in (spoken.outcome.reply or "")
    assert isinstance(harness.synthesizer, FakeSpeechSynthesizer)
    assert harness.synthesizer.spoken_texts == (deflection,)
    assert spoken.spoken is not None
