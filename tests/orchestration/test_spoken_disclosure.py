"""ADR-0199's ruling, applied at supply on the spoken channel (ADR-0200 §7, ADR-0203).

Three parts. The first is ``orchestration.disclosure`` on its own — the placement
rules of ADR-0199 §§2-3, decided from recorded origin and never from content. The
second is the engine driving them: a withheld class never reaching the composing
stage's inputs, the stage being told the audience and the bare fact of a
withholding, and nothing filtering the composed answer afterwards.

The third is **ADR-0203 §6's seven obligations**, which are about the withholding
binding the supply the *whole turn* runs over rather than the composing stage's
alone: #1692's two-turn chain, #1693's return value, the negative arm, the step
consequence §3 admits, the three degradation rules held unmoved on the withholding
route, and the bounded channel left as it was.

The fourth is **ADR-0204 §8's fifteen cases**, about what a record's warrant held.
Two of them — 4 and 9 — are restated under ADR-0210 §10 item 7 with the record
standing where §1 narrows the evaluation to, and the section's banner comment
accounts for the other thirteen one line each.

The fifth is **ADR-0210 §9's nine obligations**, about *which members* of a spoken
turn's supply may set the boolean ADR-0204 §2 carries to capture and ADR-0199 §5's
third clause carries to the composing stage: the retrieved groups and the context
facets, and never the conversation's own recent turns. The cases that turn on which
relevance read returned a record are driven through
:class:`~ai_assistant.orchestration.loop.LearningLoop`, where both reads and
ADR-0158 §4's deduplication happen; the cases about what the stage is told and what
capture writes are driven through the engine.
"""

from __future__ import annotations

import json
from base64 import b64encode
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final

import pytest
from test_engine import (
    AT,
    CAPABILITY,
    PARAMETERS,
    PATIENT,
    Harness,
    NoStepPlanner,
    OneStepPlanner,
    _fresh_facade,
    confirmable,
    tool,
)

from ai_assistant.core.errors import MemoryStoreError, SpeechError
from ai_assistant.core.types import (
    ActionPlan,
    Attestation,
    CalendarFacet,
    ContextFacet,
    CurrentContext,
    Disposition,
    EmailFacet,
    EpisodicMemory,
    Goal,
    MemoryRecord,
    MemorySource,
    Placement,
    PlacementReach,
    PlacementSetter,
    PlanStep,
    Provenance,
    Role,
    SemanticMemory,
    SpokenAudio,
    SpokenAudioFormat,
    TimeOfDay,
    TurnOutcome,
)
from ai_assistant.orchestration import LearningLoop, MemoryWriteStage, RoutingStage
from ai_assistant.orchestration.composing import ComposingStage
from ai_assistant.orchestration.disclosure import (
    UnboundedAudienceSupply,
    placed_facet_kinds,
    speakable_sources,
    supply_for_unbounded_audience,
)
from ai_assistant.testing import (
    FakeContextProvider,
    FakeDeferralStore,
    FakeFeedbackProcessor,
    FakeMemoryPolicy,
    FakeMemoryStore,
    FakeMemoryWriter,
    FakeModelProvider,
    FakePlanner,
    FakeRoutingRecorder,
    FakeSpeechSynthesizer,
    FakeSpeechTranscriber,
    FakeStreamingCompleter,
    FakeToolRegistry,
    StreamAttempt,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.core.types import MemoryWrite, TurnResult

_AT: Final = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)

#: The placement ADR-0217 §3's derivation writes for a record ADR-0204 §2 or §5
#: would have stamped ``True``: reach ``OWNER``, setter ``DERIVED``, at the instant
#: of the narrowing. Every fixture below that "carries the stamp" carries this.
_NARROWED: Final = Placement(reach=PlacementReach.OWNER, set_by=PlacementSetter.DERIVED, set_at=_AT)
_MP4: Final = SpokenAudioFormat.MP4
_CALENDAR: Final = "calendar"
_ANSWER: Final = "You went hiking on Tuesday."

#: What a withheld record says. Recognisable, so an assertion can look for the
#: span itself rather than for "something about somebody else".
_WITHHELD_CONTENT: Final = "Alice is seeing a cardiologist on Friday"

#: What a *placed* record says, beside it. Every ADR-0203 §6 case seeds both, so
#: "nothing was withheld" and "everything was withheld" are told apart by the same
#: assertion rather than by two.
_SPEAKABLE_CONTENT: Final = "the user hikes on Tuesdays"

#: The transcript ADR-0203 §6's cases are driven with. Chosen so that
#: ``FakeMemoryStore``'s lexical relevance retrieves both records above — the arms
#: are about what the subtraction removes, and a case whose store returned nothing
#: would pass every one of them vacuously.
_ASKED: Final = "what is on this week"

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


#: The situational context a case that does not care about facets is given.
_CONTEXT: Final = CurrentContext(
    now=_AT, time_of_day=TimeOfDay.AFTERNOON, is_weekend=False, within_working_hours=True
)


def _supply(
    *records: MemoryRecord,
    context: CurrentContext = _CONTEXT,
    sources: frozenset[str] = frozenset(),
    retrieved_ids: frozenset[str] | None = None,
) -> tuple[CurrentContext, tuple[MemoryRecord, ...], bool]:
    """ADR-0203 §1's subtraction, over one context and one group of records.

    The narrowing predicate is applied to what the turn assembled and retrieved
    rather than to a ``TurnResult``, because since ADR-0203 §1 there is no turn yet
    when it runs: it sits between retrieval and planning.

    ``retrieved_ids`` defaults to **every** record given, which is the reading the
    placement cases below want: ADR-0210 §1 narrows which members of a supply may
    set the boolean and changes no placement (§3), so a case about a placement puts
    its subject where a relevance read returned it. The cases that turn on the
    narrowing state the set themselves.
    """
    return supply_for_unbounded_audience(
        context,
        records,
        speakable_attested_sources=sources,
        retrieved_ids=(
            frozenset(one.id for one in records) if retrieved_ids is None else retrieved_ids
        ),
    )


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

    _, memories, withheld = _supply(record)

    assert withheld is False
    assert memories == (record,)


def test_a_belief_about_somebody_else_is_withheld() -> None:
    """§3: "any record whose ``MemoryBase.about_person`` is stated".

    The household clause, and it decides on its own: the person a belief is about
    is, in a household, exactly the person most likely to be in the room when it
    would be read aloud.
    """
    record = _belief("rec-1", _WITHHELD_CONTENT, about_person="Alice")

    _, memories, withheld = _supply(record)

    assert withheld is True
    assert memories == ()


def test_an_attested_belief_from_the_configured_calendar_is_speakable() -> None:
    """§3's second placement: ``ATTESTED`` **and** ``reported_by`` names the calendar."""
    record = _belief(
        "rec-1", "standup at 09:00", source=MemorySource.EXTERNAL, reported_by=_CALENDAR
    )

    _, memories, withheld = _supply(record, sources=frozenset({_CALENDAR}))

    assert withheld is False
    assert memories == (record,)


def test_an_attested_belief_from_any_other_source_is_withheld() -> None:
    """§3's fourth clause: an unplaced class is withheld until an ADR places it.

    The next source to land — a health integration, a message reader — is withheld
    on the day it merges rather than speakable by omission, which is the whole
    safety property of naming the speakable set rather than the withheld one.
    """
    record = _belief(
        "rec-1", "your test results are in", source=MemorySource.EXTERNAL, reported_by="health"
    )

    _, memories, withheld = _supply(record, sources=frozenset({_CALENDAR}))

    assert withheld is True
    assert memories == ()


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

    _, memories, withheld = _supply(unattested, sources=frozenset({_CALENDAR}))

    assert withheld is True
    assert memories == ()


def test_no_configured_calendar_withholds_every_attested_belief() -> None:
    """The composition root's empty set, which withholds rather than guessing a name."""
    record = _belief(
        "rec-1", "standup at 09:00", source=MemorySource.EXTERNAL, reported_by=_CALENDAR
    )

    _, memories, withheld = _supply(record)

    assert withheld is True
    assert memories == ()


def test_a_calendar_belief_about_somebody_else_is_still_withheld() -> None:
    """§3 places it "again where ``about_person`` is not stated" — the conjunction holds."""
    record = _belief(
        "rec-1",
        _WITHHELD_CONTENT,
        source=MemorySource.EXTERNAL,
        reported_by=_CALENDAR,
        about_person="Alice",
    )

    _, memories, withheld = _supply(record, sources=frozenset({_CALENDAR}))

    assert withheld is True
    assert memories == ()


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

    narrowed, _, withheld = _supply(context=context)

    assert withheld is False
    assert narrowed is context


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

    narrowed, _, withheld = _supply(context=context)

    assert withheld is True
    assert narrowed.calendar is None


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


# --- §2: the subtraction removes members and does nothing else ---------------


def test_a_supply_with_nothing_withheld_is_handed_over_unchanged() -> None:
    """ADR-0199 §5: "The withholding subtracts from what the turn produced and adds nothing".

    Identity rather than equality on the context, because a rebuilt-but-equal value
    would still be a second object the turn runs over and would hide a rebuild that
    dropped a member :class:`~ai_assistant.core.types.CurrentContext` grows later.
    """
    record = _belief("rec-1", "the user hikes")

    narrowed, memories, withheld = _supply(record)

    assert narrowed is _CONTEXT
    assert memories == (record,)
    assert withheld is False


def test_what_survives_keeps_the_order_it_arrived_in() -> None:
    """ADR-0203 §2: "The subtraction removes members and reorders nothing".

    ADR-0074 §5's three groups — the conversation's recent turns, then the
    relevance-retrieved beliefs, then ADR-0158's episodic supplement — reach the
    planner in that order still, which is how this corpus expresses precedence into
    a prompt. A filter that partitioned rather than filtered would pass every
    membership assertion above and silently reorder the prompt.
    """
    first = _belief("rec-1", "the user hikes")
    dropped = _belief("rec-2", _WITHHELD_CONTENT, about_person="Alice")
    third = _belief("rec-3", "the user cycles")
    supplied = (first, dropped, third)

    _, memories, _ = _supply(*supplied)

    assert memories == (first, third)
    assert supplied == (first, dropped, third), "the sequence it was handed is not modified"


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


# --- §7: a routed spoken pass is told the audience too -----------------------


async def test_a_routed_spoken_pass_composes_for_the_unbounded_channel() -> None:
    """ADR-0200 §7: the audience reaches the stage on **every** composition of this call.

    A routed pass is composed from two enum values rather than from a turn
    (ADR-0197 §6), and it is still spoken aloud — so a path that skipped the
    audience would have the hub composing for a screen while the answer went to a
    loudspeaker, which is exactly what ADR-0200 §2 refuses to let the *gateway*
    cause and is no less wrong caused here.

    **And the audience is not the third value ADR-0197 §6 forbids.** That section's
    enumeration is about the routed result's data — "no query, no resolved argument,
    no candidate, no record, no listing and no count" — and its third clause forbids
    "rendering a routed result into text and supplying that text to a model". A
    statement about the channel is neither, and this case checks that nothing else
    moved: the routed prompt is still two phrases selected by enum member.
    """
    composing = FakeModelProvider("I have forgotten it.")
    harness = Harness(
        composing=ComposingStage(model=composing, streaming=FakeStreamingCompleter()),
        planner=NoStepPlanner(),
        routing=RoutingStage(
            model=FakeModelProvider(json.dumps({"operation": "forget", "query": "hiking"})),
            recorder=FakeRoutingRecorder(),
        ),
        transcriber=FakeSpeechTranscriber(transcripts=["forget what I said about hiking"]),
    )

    spoken = await harness.engine.converse_spoken(_RECORDING, plays=(_MP4,), timeout=PATIENT)

    assert spoken.outcome is not None
    assert spoken.outcome.routed is not None
    assert "SPOKEN ALOUD" in _messages(composing, Role.SYSTEM)
    # The material is untouched: two phrases from two closed vocabularies, and no
    # query, candidate, record, listing or count anywhere near it (ADR-0197 §6).
    user_turn = _messages(composing, Role.USER)
    assert "hiking" not in user_turn
    assert user_turn.startswith("The user asked the assistant to ")


async def test_a_routed_written_pass_is_not_told_a_spoken_channel() -> None:
    """The other side, so the clause is a property of the *operation* and not a default."""
    composing = FakeModelProvider("I have forgotten it.")
    harness = Harness(
        composing=ComposingStage(model=composing, streaming=FakeStreamingCompleter()),
        planner=NoStepPlanner(),
        routing=RoutingStage(
            model=FakeModelProvider(json.dumps({"operation": "forget", "query": "hiking"})),
            recorder=FakeRoutingRecorder(),
        ),
    )

    outcome = await harness.engine.converse("forget what I said about hiking", timeout=PATIENT)

    assert outcome.routed is not None
    assert "SPOKEN ALOUD" not in _messages(composing, Role.SYSTEM)


# --- ADR-0203 §6: the withholding binds the supply the whole turn runs over ---


class _EchoingPlanner:
    """A planner whose rationale names every record it was handed.

    The real planner's ``rationale`` is a model completion authored over the supply,
    which is exactly why ADR-0203 §1 exists: ``Engine._capture`` renders it into the
    episode's ``content``, and the episode's *own* recorded origin is ``OBSERVED``
    with ``about_person`` unset, which ADR-0199 §3 places as speakable — so storing
    an unplaced value launders it into a placed one. Echoing is the strongest form
    of that. A planner that cited what it saw is what a model does, and it makes
    "the episode carries no value derived from a withheld record" a claim these
    cases can fail on rather than one they have to trust.

    It plans a step only where ``needs`` appears in what it was supplied, which is
    how ADR-0203 §3's admission — that the plan's consequence is not independent of
    the plan — becomes observable.

    Structurally implements :class:`~ai_assistant.core.protocols.Planner`.
    """

    def __init__(self, *, needs: str | None = None) -> None:
        self._needs = needs
        self.calls: list[tuple[CurrentContext, tuple[MemoryRecord, ...]]] = []

    async def plan(
        self,
        goal: Goal,
        *,
        context: CurrentContext,
        memories: Sequence[MemoryRecord] = (),
        capabilities: Sequence[str],
    ) -> ActionPlan:
        """Record what this turn was supplied, and plan over exactly that."""
        supplied = tuple(memories)
        self.calls.append((context, supplied))
        planned = self._needs is not None and any(self._needs in one.content for one in supplied)
        steps = (
            (
                PlanStep(
                    id="step-1",
                    intent="send the note",
                    capability=CAPABILITY,
                    parameters=PARAMETERS,
                ),
            )
            if planned
            else ()
        )
        return ActionPlan(
            id=f"{goal.id}-plan",
            goal_id=goal.id,
            steps=steps,
            created_at=AT,
            rationale=" | ".join(one.content for one in supplied) or "nothing was supplied",
        )


def _prompt(model: FakeModelProvider, call: int = 0) -> str:
    """The user turn of the ``call``-th completion this provider was asked for."""
    return next(one.content for one in model.calls[call].messages if one.role is Role.USER)


def _episodes(records: Sequence[MemoryRecord]) -> tuple[EpisodicMemory, ...]:
    """Every captured episode among ``records``."""
    return tuple(one for one in records if isinstance(one, EpisodicMemory))


async def test_a_withheld_class_is_not_read_aloud_one_turn_later() -> None:
    """§6's first obligation, and #1692 as the QA run heard it.

    Turn one asks a question that retrieves a belief about somebody else and
    deflects. Its captured episode is then read: with ADR-0203 §1 in force the plan
    rationale that episode carries was authored over a supply the belief had already
    been removed from, so the episode carries no span of it and no value derived
    from one. Turn two, on the same conversation, is handed nothing naming what turn
    one withheld, which is the sentence #1691 heard spoken aloud.

    Before ADR-0203 every assertion below the first failed together: the planner saw
    the belief, wrote it into the rationale, capture stored that under an
    ``OBSERVED`` provenance §3 places as **speakable**, and the next turn retrieved
    it as ordinary supply.

    **What ADR-0204 §3 changes here is turn two's supply, and nothing else** — it
    partially supersedes ADR-0199 §3's third clause for a record whose warrant held
    withheld content, and turn one is exactly such a turn (#1703). So the episode
    turn one captured is *stamped* and no longer reaches turn two, where before it
    reached it thinned. ADR-0203 §6's obligation is unaffected and is now met twice
    over; the continuity guard below asserts the retrieval still happened rather than
    asserting the episode arrived, and
    ``test_a_deflecting_spoken_turns_episode_is_withheld_from_the_next_spoken_turn``
    pins the withholding itself.
    """
    planner = _EchoingPlanner()
    model = FakeModelProvider(_ANSWER)
    goals = iter(f"g-{n}" for n in range(1, 10))
    harness = _wired(
        model,
        planner=planner,
        loop_id_factory=lambda: next(goals),
        transcriber=FakeSpeechTranscriber(transcripts=[_ASKED, "what is on the record"]),
    )
    await _seed(
        harness,
        _belief("rec-1", _SPEAKABLE_CONTENT),
        _belief("rec-2", _WITHHELD_CONTENT, about_person="Alice"),
    )

    first = await harness.engine.converse_spoken(_RECORDING, plays=(_MP4,), timeout=PATIENT)

    # The planner never saw it, so nothing downstream of a model can have derived
    # from it — ADR-0203 §1's whole argument for binding on the input side.
    assert planner.calls, "the turn reached the planner"
    assert all(_WITHHELD_CONTENT not in one.content for one in planner.calls[0][1])
    assert _SPEAKABLE_CONTENT in {one.content for one in planner.calls[0][1]}, (
        "the case is only about the withheld half if the speakable half was retrieved"
    )
    assert first.outcome is not None
    assert first.outcome.turn is not None
    assert _WITHHELD_CONTENT not in (first.outcome.turn.plan.rationale or "")

    captured = _episodes(await harness.memory.export())
    assert len(captured) == 1, "one turn, one episode (ADR-0074 §3)"
    assert _WITHHELD_CONTENT not in captured[0].content
    assert "Alice" not in captured[0].content
    assert _SPEAKABLE_CONTENT in captured[0].content, (
        "the episode is thinner rather than absent — capture itself is unchanged"
    )

    second = await harness.engine.converse_spoken(
        _RECORDING,
        plays=(_MP4,),
        timeout=PATIENT,
        conversation_id=first.outcome.conversation_id,
    )

    # The second turn genuinely retrieved: without this, a case that had lost
    # retrieval altogether would pass vacuously. What it may no longer be supplied is
    # turn one's own episode, which ADR-0204 §3 withholds because turn one's warrant
    # held content ADR-0199 §3 withholds from this channel.
    assert second.outcome is not None
    assert second.outcome.turn is not None
    assert _SPEAKABLE_CONTENT in {one.content for one in second.outcome.turn.memories}
    assert not _episodes(second.outcome.turn.memories), (
        "the withholding turn's own episode is withheld from a later spoken turn"
    )
    assert len(model.calls) == 2
    assert _WITHHELD_CONTENT not in _prompt(model, 1)
    assert "Alice" not in _prompt(model, 1)


async def test_what_the_operation_returns_carries_nothing_that_was_withheld() -> None:
    """§6's second obligation, and #1693.

    ADR-0200 §7's third clause — "nothing on this surface carries what was withheld"
    — is satisfied **literally** rather than on the narrow reading #1693 offers as
    the alternative: there is only one turn, and it did not see the withheld record.
    The plan is checked against the same supply, because a ``TurnResult`` whose
    ``memories`` were narrowed but whose ``plan`` was authored over everything would
    pass a membership assertion and still hand the caller a model-written summary of
    the withheld set.
    """
    planner = _EchoingPlanner()
    harness = _wired(
        FakeModelProvider(_ANSWER),
        planner=planner,
        transcriber=FakeSpeechTranscriber(transcripts=[_ASKED]),
    )
    await _seed(
        harness,
        _belief("rec-1", _SPEAKABLE_CONTENT),
        _belief("rec-2", _WITHHELD_CONTENT, about_person="Alice"),
    )

    spoken = await harness.engine.converse_spoken(_RECORDING, plays=(_MP4,), timeout=PATIENT)

    assert spoken.outcome is not None
    turn = spoken.outcome.turn
    assert turn is not None
    assert all(one.about_person is None for one in turn.memories)
    assert all(_WITHHELD_CONTENT not in one.content for one in turn.memories)
    assert turn.context.calendar is None
    assert turn.context.email is None
    # "and its plan was produced over that same supply": the tuple the planner was
    # handed *is* the one the turn carries, so nothing planned over a wider supply
    # and swapped the narrower one in afterwards.
    assert planner.calls[0][1] == turn.memories
    assert _WITHHELD_CONTENT not in (turn.plan.rationale or "")


async def test_a_wholly_speakable_store_reaches_the_planner_whole_and_is_answered() -> None:
    """§6's negative arm, "without which the two above are satisfiable by withholding everything".

    This is milestone 19's exit criterion asserted rather than argued — the owner
    asks aloud about their own life and hears an answer drawn from accumulated
    memory — and it is what bounds §3's step clause: on a supply the subtraction
    does not touch, the plan and the step are what the same transcript produces on
    either channel.
    """
    planner = _EchoingPlanner(needs="hikes")
    model = FakeModelProvider(_ANSWER)
    harness = _wired(
        model,
        planner=planner,
        tools=(tool(),),
        transcriber=FakeSpeechTranscriber(transcripts=[_ASKED]),
    )
    speakable = (
        _belief("rec-1", _SPEAKABLE_CONTENT),
        _belief("rec-2", "errands happen on a Monday", source=MemorySource.INFERRED),
        _belief("rec-3", "the user said they cycle on Sundays", source=MemorySource.USER_ASSERTED),
    )
    await _seed(harness, *speakable)

    spoken = await harness.engine.converse_spoken(_RECORDING, plays=(_MP4,), timeout=PATIENT)

    supplied = {one.id for one in planner.calls[0][1]}
    assert {one.id for one in speakable} <= supplied, "every placed record reached the planner"
    assert spoken.outcome is not None
    assert spoken.outcome.turn is not None
    assert {one.id for one in speakable} <= {one.id for one in spoken.outcome.turn.memories}
    assert spoken.outcome.step is not None, "the plan drove the step it chose"
    assert spoken.outcome.step.disposition is Disposition.EXECUTED
    assert spoken.outcome.reply == _ANSWER
    assert "NOT AVAILABLE ON THIS CHANNEL" not in _prompt(model)


async def test_the_step_follows_the_plan_the_subtracted_supply_produced() -> None:
    """§6's fourth obligation: §3's step consequence observed once rather than inferred.

    ``Engine._run_turn`` drives ``turn.plan.steps[0]``, so a plan authored over a
    narrower supply can drive a different step or leave the plan with no steps at
    all — the no-action branch. The arm exists so that a later lane cannot quietly
    restore the wider supply to keep the step stable: the *same* store and the
    *same* words drive a step on ``converse`` and drive none on ``converse_spoken``,
    and the subtraction is the whole of the difference.
    """
    withheld = _belief("rec-1", _WITHHELD_CONTENT, about_person="Alice")

    spoken_planner = _EchoingPlanner(needs=_WITHHELD_CONTENT)
    spoken_harness = _wired(
        FakeModelProvider(_ANSWER),
        planner=spoken_planner,
        tools=(tool(),),
        transcriber=FakeSpeechTranscriber(transcripts=[_ASKED]),
    )
    await _seed(spoken_harness, withheld)

    spoken = await spoken_harness.engine.converse_spoken(_RECORDING, plays=(_MP4,), timeout=PATIENT)

    assert spoken.outcome is not None
    assert spoken.outcome.turn is not None
    assert spoken.outcome.turn.plan.steps == (), "no step could be planned from what was left"
    assert spoken.outcome.step is None, "and the runner saw that plan, not a wider one"

    written_planner = _EchoingPlanner(needs=_WITHHELD_CONTENT)
    written_harness = _wired(FakeModelProvider(_ANSWER), planner=written_planner, tools=(tool(),))
    await _seed(written_harness, withheld)

    written = await written_harness.engine.converse(_ASKED, timeout=PATIENT)

    assert written.turn is not None
    assert written.turn.plan.steps != ()
    assert written.step is not None
    assert written.step.disposition is Disposition.EXECUTED


async def test_a_withholding_turn_that_cannot_compose_reports_reply_degraded() -> None:
    """§6's fifth obligation, first arm: ``reply_degraded`` on the ``withheld=True`` route.

    ADR-0203 §3 unpins the three degradation flags' **values** and keeps their
    **rules**, and this is the rule: a composition failure yields
    ``TurnOutcome.reply_degraded`` exactly as it does on ``converse`` (ADR-0170 §8).
    A blank completion is the forcing input, because ``NonBlankEncodableText``
    cannot hold one and the stage classifies it rather than raising.
    """
    harness = _wired(
        FakeModelProvider("   "),
        planner=_EchoingPlanner(),
        transcriber=FakeSpeechTranscriber(transcripts=[_ASKED]),
    )
    await _seed(harness, _belief("rec-1", _WITHHELD_CONTENT, about_person="Alice"))

    spoken = await harness.engine.converse_spoken(_RECORDING, plays=(_MP4,), timeout=PATIENT)

    assert spoken.outcome is not None
    assert spoken.outcome.reply is None
    assert spoken.outcome.reply_degraded is True
    assert spoken.spoken is None, "there is no answer to render"


async def test_a_withholding_turn_whose_capture_fails_reports_capture_degraded() -> None:
    """§6's fifth obligation, second arm: ``capture_degraded`` on the ``withheld=True`` route.

    The answer is still the answer and the user is told it went unrecorded, exactly
    as on ``converse``. Seeding happens before the store is armed, so what fails is
    the *capture* write and not the seed.
    """

    class _FailingCapture(FakeMemoryStore):
        """A store whose writes fail once armed."""

        armed = False

        async def write_atomic(self, writes: Sequence[MemoryWrite]) -> Sequence[str]:
            if self.armed:
                msg = "the embedder is down"
                raise MemoryStoreError(msg)
            return await super().write_atomic(writes)

    memory = _FailingCapture(now=lambda: AT)
    harness = _wired(
        FakeModelProvider(_ANSWER),
        planner=_EchoingPlanner(),
        memory=memory,
        transcriber=FakeSpeechTranscriber(transcripts=[_ASKED]),
    )
    await _seed(harness, _belief("rec-1", _WITHHELD_CONTENT, about_person="Alice"))
    memory.armed = True

    spoken = await harness.engine.converse_spoken(_RECORDING, plays=(_MP4,), timeout=PATIENT)

    assert spoken.outcome is not None
    assert spoken.outcome.turn is not None, "the turn still produced its answer"
    assert spoken.outcome.reply == _ANSWER
    assert spoken.outcome.capture_degraded is True


async def test_a_withholding_turn_whose_synthesis_fails_reports_spoken_degraded() -> None:
    """§6's fifth and sixth obligations: ``spoken_degraded`` **on the withholding route**.

    §6 pins this one there specifically, "because that is the route the existing
    spoken-path degradation tests do not reach: they run over supplies nothing is
    subtracted from, so an implementation that skipped synthesis on a deflection, or
    reported ``spoken_degraded`` ``False`` beside a ``None`` rendering there, would
    pass every one of them". ADR-0200 §4's exactly-when clause is unmoved, and the
    value handed to the seam is the deflection.
    """
    deflection = "There is something about that I would rather not say out loud."
    synthesizer = FakeSpeechSynthesizer()
    synthesizer.fail_next_synthesize(SpeechError("the voice model wedged"))
    harness = _wired(
        FakeModelProvider(deflection),
        planner=_EchoingPlanner(),
        synthesizer=synthesizer,
        transcriber=FakeSpeechTranscriber(transcripts=[_ASKED]),
    )
    await _seed(harness, _belief("rec-1", _WITHHELD_CONTENT, about_person="Alice"))

    spoken = await harness.engine.converse_spoken(_RECORDING, plays=(_MP4,), timeout=PATIENT)

    assert spoken.spoken is None
    assert spoken.spoken_degraded is True
    assert spoken.outcome is not None
    assert spoken.outcome.reply == deflection
    assert synthesizer.spoken_texts == (deflection,), "synthesis was attempted, on the deflection"


async def test_the_bounded_channel_still_plans_over_its_whole_supply() -> None:
    """§6's seventh obligation: a subtraction that leaked everywhere would pass every case above.

    ADR-0203 §1's last clause binds an **operation** and not a session, a transport,
    a device or a caller: ``converse``'s audience is bounded, so ADR-0199 §5's
    second clause governs it unchanged and its turn plans over everything it
    retrieved — the plan rationale included.
    """
    planner = _EchoingPlanner()
    harness = _wired(FakeModelProvider(_ANSWER), planner=planner)
    seeded = (
        _belief("rec-1", _SPEAKABLE_CONTENT),
        _belief("rec-2", _WITHHELD_CONTENT, about_person="Alice"),
    )
    await _seed(harness, *seeded)

    outcome = await harness.engine.converse(_ASKED, timeout=PATIENT)

    supplied = {one.id for one in planner.calls[0][1]}
    assert {one.id for one in seeded} <= supplied
    assert outcome.turn is not None
    assert {one.id for one in seeded} <= {one.id for one in outcome.turn.memories}
    assert _WITHHELD_CONTENT in (outcome.turn.plan.rationale or "")


# --- ADR-0204 §8: what a record's warrant held, stamped and read at supply ----
#
# **Two of §8's fifteen cases are restated by ADR-0210 §10 item 7**, whose header
# records the supersession. Test 4 states its input as "a `converse_spoken` turn
# whose supply held a withheld record" and test 9 as "a turn supplied a withheld
# record that parks", neither saying **where** in the supply the record stood — so
# each was satisfied by a fixture holding it in the conversation tail alone, and
# after ADR-0210 §1 such a fixture captures `False`. Both are written below with the
# record standing in the narrowed set — a relevance read of the turn's own goal
# statement returned it — and both assert the **same outcome** each test fixes.
# Neither is deleted and neither outcome is weakened.
#
# **The other thirteen are unaffected, one line each** (§10 item 7):
#
# * 1, 2, 5 and 14 run on `converse`, which ADR-0210 §1's last clause leaves whole.
# * 3's record is one "whose retrieval returns it" — its precondition already names
#   the narrowed set.
# * 6 withholds nothing, so there is no evaluation for §1 to narrow.
# * 7, 8, 10 and 15 reach no spoken turn's supply at all: a fold, a decode, a
#   resumption and a routed pass, and a supersession.
# * 11, 12 and 13 are about a producer that is **not** a turn — an observer
#   distilling from records it was supplied — which ADR-0210 §2's third clause
#   leaves untouched word for word.


def _stamped(records: Sequence[MemoryRecord]) -> set[str]:
    """The ids among ``records`` whose placement is narrowed (ADR-0217 §1)."""
    return {one.id for one in records if one.placement.reach is not PlacementReach.ANYONE}


async def test_a_typed_turn_supplied_a_withheld_record_stamps_its_episode() -> None:
    """§8 case 1: the bounded channel's turn is untouched and its capture is stamped.

    #1708 at its root. The typed turn runs over everything it retrieved — ADR-0203
    §1's last clause, which ADR-0204 §4 keeps whole — so the belief about Alice is
    still in ``turn.memories`` and still in the plan rationale the model authored.
    What changes is the one field of the episode that rationale is rendered into,
    because that episode is an input to a channel whose audience is not bounded.
    """
    planner = _EchoingPlanner()
    harness = _wired(FakeModelProvider(_ANSWER), planner=planner)
    await _seed(
        harness,
        _belief("rec-1", _SPEAKABLE_CONTENT),
        _belief("rec-2", _WITHHELD_CONTENT, about_person="Alice"),
    )

    outcome = await harness.engine.converse(_ASKED, timeout=PATIENT)

    assert outcome.turn is not None
    assert "rec-2" in {one.id for one in outcome.turn.memories}, (
        "§4: a bounded channel's supply is not narrowed by this ADR"
    )
    assert _WITHHELD_CONTENT in (outcome.turn.plan.rationale or "")
    captured = _episodes(await harness.memory.export())
    assert len(captured) == 1, "one turn, one episode (ADR-0074 §3)"
    assert captured[0].placement.reach is PlacementReach.OWNER
    assert _WITHHELD_CONTENT in captured[0].content, (
        "the episode's content is unchanged — the stamp is what withholds it, not a filter"
    )


async def test_a_streamed_turn_supplied_a_withheld_record_stamps_its_episode() -> None:
    """§8 case 1's third caller: ``converse_streaming`` (#1728).

    ADR-0204 §8's fifteen cases name ``converse`` and ``converse_spoken`` and no
    third operation, but :meth:`Engine._run_turn` has three callers and the streamed
    one mints its own
    :class:`~ai_assistant.orchestration.disclosure.BoundedAudienceSupply`. What held
    that in place was the type checker alone — ``supply`` is a required keyword
    argument, so removing it is a ``mypy`` error rather than a silent change — and
    what was unpinned is the weaker mutation: a streamed caller passing a
    differently configured supply, or a later lane restoring a ``None`` default on
    that parameter.

    The claim is ADR-0204 §4's, on the operation ADR-0173 §4 adds: the turn is
    supplied everything it retrieved, and its capture records that content ADR-0199
    §3 withholds stood in its warrant. ADR-0210 §1's last clause leaves this channel
    exactly here.
    """
    stage = ComposingStage(
        model=FakeModelProvider(_ANSWER),
        streaming=FakeStreamingCompleter(script=(StreamAttempt(deltas=(_ANSWER,)),)),
    )
    harness = Harness(composing=stage, planner=_EchoingPlanner())
    await _seed(
        harness,
        _belief("rec-1", _SPEAKABLE_CONTENT),
        _belief("rec-2", _WITHHELD_CONTENT, about_person="Alice"),
    )

    chunks: list[str] = []
    outcome: TurnOutcome | None = None
    async for value in harness.engine.converse_streaming(_ASKED, timeout=PATIENT):
        if isinstance(value, TurnOutcome):
            outcome = value
        else:
            chunks.append(value.text)

    assert outcome is not None, "ADR-0173 §4: the outcome is always the last value"
    assert outcome.turn is not None
    assert "rec-2" in _ids(outcome.turn.memories), (
        "§4: a bounded channel's supply is not narrowed, on this operation either"
    )
    captured = _episodes(await harness.memory.export())
    assert len(captured) == 1
    assert captured[0].placement.reach is PlacementReach.OWNER


async def test_a_typed_turn_supplied_nothing_withheld_does_not_stamp_its_episode() -> None:
    """§8 case 2: the negative arm, without which stamping everything would pass case 1.

    ``False`` is a measurement here rather than a default: this turn was supplied
    the owner's own beliefs, neither of ADR-0204 §1's two routes reached it, and
    that is what the field says.
    """
    harness = _wired(FakeModelProvider(_ANSWER), planner=_EchoingPlanner())
    await _seed(
        harness,
        _belief("rec-1", _SPEAKABLE_CONTENT),
        _belief("rec-2", "the user prefers short answers", source=MemorySource.USER_ASSERTED),
    )

    await harness.engine.converse(_ASKED, timeout=PATIENT)

    captured = _episodes(await harness.memory.export())
    assert len(captured) == 1
    assert captured[0].placement == Placement()


async def test_the_typed_turns_stamped_episode_is_withheld_from_a_later_spoken_turn() -> None:
    """§8 case 3: #1708's chain, refused.

    The typed turn's episode is ``OBSERVED`` with ``about_person`` unset, which
    ADR-0199 §3's third clause places **speakable** — and it carries a model
    rationale authored over the belief about Alice. ADR-0204 §3 withholds it anyway,
    which is the supersession scoped to exactly this record: the placement is
    unchanged and a second reason withholds it.

    The belief is deleted between the two turns so that the episode is the only
    withholdable thing left, which is what makes the deflection below evidence that
    the episode was retrieved and removed rather than never retrieved at all.
    """
    planner = _EchoingPlanner()
    model = FakeModelProvider(_ANSWER)
    goals = iter(f"g-{n}" for n in range(1, 10))
    harness = _wired(
        model,
        planner=planner,
        loop_id_factory=lambda: next(goals),
        transcriber=FakeSpeechTranscriber(transcripts=[_ASKED]),
    )
    await _seed(
        harness,
        _belief("rec-1", _SPEAKABLE_CONTENT),
        _belief("rec-2", _WITHHELD_CONTENT, about_person="Alice"),
    )

    typed = await harness.engine.converse(_ASKED, timeout=PATIENT)
    assert typed.conversation_id is not None
    # The belief itself is destroyed before the spoken turn, so the **only** thing
    # left for the subtraction to remove is the episode: the deflection asserted
    # below cannot come from anything else, and this case cannot pass on a spoken
    # turn whose retrieval simply never found the episode.
    await harness.memory.delete("rec-2")
    spoken = await harness.engine.converse_spoken(
        _RECORDING, plays=(_MP4,), timeout=PATIENT, conversation_id=typed.conversation_id
    )

    assert spoken.outcome is not None
    assert spoken.outcome.turn is not None
    assert not _episodes(spoken.outcome.turn.memories), (
        "the stamped episode reached no stage of the spoken turn (ADR-0199 §5's first clause)"
    )
    assert _WITHHELD_CONTENT not in _prompt(model, 1)
    assert "NOT AVAILABLE ON THIS CHANNEL" in _prompt(model, 1), (
        "ADR-0199 §5's third clause: the composing stage is told **that** it happened"
    )


async def test_a_deflecting_spoken_turns_episode_is_withheld_from_the_next_spoken_turn() -> None:
    """§8 case 4 as ADR-0210 §10 item 7 restates it — and §9's sixth clause.

    The withholding turn's own question is carried unrewritten into its episode
    (``_exchange_of``), which is why ADR-0203 §4's fifth clause recorded this path as
    open. It closes on the fact that the turn withheld something at all — a fact
    about the turn's supply, decided from recorded origin, and not a judgement about
    what its question said.

    **The precondition is narrowed and the outcome is not** (ADR-0210 §8's header,
    §10 item 7). §8 case 4 says only "a `converse_spoken` turn whose supply held a
    withheld record"; after ADR-0210 §1 the record has to have stood in the narrowed
    set, so this fixture states that mechanically — the store holds **no episode**
    when the first turn runs, so ADR-0074 §5's first group is empty and the belief
    about Alice can only have reached the supply through the belief composition's
    relevance read. ADR-0210 §4 is the same point in the ADR's own words: "a turn
    that asks about the withheld class is a turn whose *retrieval* surfaces the
    withheld record — the question is the query".

    This is also §9's sixth clause: #1703's chain end to end, a deflecting spoken
    turn captured stamped and a later spoken turn not supplied that episode.
    """
    goals = iter(f"g-{n}" for n in range(1, 10))
    harness = _wired(
        FakeModelProvider(_ANSWER),
        planner=_EchoingPlanner(),
        loop_id_factory=lambda: next(goals),
        transcriber=FakeSpeechTranscriber(transcripts=[_ASKED, _ASKED]),
    )
    await _seed(
        harness,
        _belief("rec-1", _SPEAKABLE_CONTENT),
        _belief("rec-2", _WITHHELD_CONTENT, about_person="Alice"),
    )

    assert not _episodes(await harness.memory.export()), (
        "no episode exists yet, so the first turn's tail is empty and the withheld "
        "belief stands in ADR-0074 §5's second group (ADR-0210 §1)"
    )

    first = await harness.engine.converse_spoken(_RECORDING, plays=(_MP4,), timeout=PATIENT)
    assert first.outcome is not None

    captured = _episodes(await harness.memory.export())
    assert len(captured) == 1
    assert captured[0].placement.reach is PlacementReach.OWNER

    second = await harness.engine.converse_spoken(
        _RECORDING,
        plays=(_MP4,),
        timeout=PATIENT,
        conversation_id=first.outcome.conversation_id,
    )

    assert second.outcome is not None
    assert second.outcome.turn is not None
    assert not _episodes(second.outcome.turn.memories)
    assert _SPEAKABLE_CONTENT in {one.content for one in second.outcome.turn.memories}, (
        "the turn retrieved: without this the case would pass on a turn supplied nothing"
    )
    # And the episode is retrieved in this exact shape when it is *not* stamped —
    # `test_milestone_19s_exit_test_is_unaffected` asserts precisely that — so the
    # absence above is the withholding rather than a retrieval that found nothing.


async def test_a_stamped_episode_still_reaches_a_bounded_channel() -> None:
    """§8 case 5: §3's third clause, which leaves the bounded channel's supply alone.

    The other half of ADR-0204 §4, and what makes case 14 necessary: a stamped
    record is deliberately still supplied to a typed turn, so that turn's own
    capture has to inherit the stamp rather than the rule stopping here.
    """
    goals = iter(f"g-{n}" for n in range(1, 10))
    harness = _wired(
        FakeModelProvider(_ANSWER), planner=_EchoingPlanner(), loop_id_factory=lambda: next(goals)
    )
    await _seed(
        harness,
        _belief("rec-1", _SPEAKABLE_CONTENT),
        _belief("rec-2", _WITHHELD_CONTENT, about_person="Alice"),
    )

    first = await harness.engine.converse(_ASKED, timeout=PATIENT)
    assert first.conversation_id is not None
    second = await harness.engine.converse(
        _ASKED, timeout=PATIENT, conversation_id=first.conversation_id
    )

    assert second.turn is not None
    supplied = _episodes(second.turn.memories)
    assert supplied, "the first turn's episode reached the second typed turn, unchanged"
    assert _stamped(supplied) == {one.id for one in supplied}


async def test_milestone_19s_exit_test_is_unaffected() -> None:
    """§8 case 6: the negative arm at the whole-operation level.

    The owner asks aloud about their own life over a store of their own beliefs and
    a placed calendar facet: nothing is withheld, so nothing is stamped, and the
    spoken channel's conversational continuity survives (ADR-0074 §5). Without this
    case an implementation that stamped every episode would pass every case above
    and empty ADR-0199 §3's speakable set on the day it landed.
    """
    goals = iter(f"g-{n}" for n in range(1, 10))
    harness = _wired(
        FakeModelProvider(_ANSWER),
        planner=_EchoingPlanner(),
        loop_id_factory=lambda: next(goals),
        context=FakeContextProvider(
            CurrentContext(
                now=_AT,
                time_of_day=TimeOfDay.AFTERNOON,
                is_weekend=False,
                within_working_hours=True,
                calendar=CalendarFacet(
                    source=_CALENDAR, read_at=_AT, entries_in_progress=1, covers_until=_AT
                ),
            )
        ),
        transcriber=FakeSpeechTranscriber(transcripts=[_ASKED, _ASKED]),
    )
    await _seed(
        harness,
        _belief("rec-1", _SPEAKABLE_CONTENT, source=MemorySource.OBSERVED),
        _belief("rec-2", "the user prefers short answers", source=MemorySource.USER_ASSERTED),
        _belief("rec-3", "the user is an early riser", source=MemorySource.INFERRED),
    )

    first = await harness.engine.converse_spoken(_RECORDING, plays=(_MP4,), timeout=PATIENT)
    assert first.outcome is not None
    assert first.outcome.turn is not None
    assert first.outcome.turn.context.calendar is not None, "the placed facet reached the turn"

    captured = _episodes(await harness.memory.export())
    assert len(captured) == 1
    assert captured[0].placement == Placement()

    second = await harness.engine.converse_spoken(
        _RECORDING,
        plays=(_MP4,),
        timeout=PATIENT,
        conversation_id=first.outcome.conversation_id,
    )

    assert second.outcome is not None
    assert second.outcome.turn is not None
    assert _episodes(second.outcome.turn.memories), (
        "an unstamped episode still reaches the next spoken turn — §3 unplaces nothing"
    )


async def test_a_parked_turns_resolution_inherits_its_stamp() -> None:
    """§8 case 9 as ADR-0210 §10 item 7 restates it: both episodes carry it.

    ADR-0074 §3 captures a parking turn twice, and the second capture renders the
    **parked turn's** goal and plan from a pass that retrieves nothing of its own.
    So the value rides on the parked entry beside the turn it belongs to (ADR-0204
    §2's fourth clause): an implementation that recomputed it at the resolution
    would evaluate an empty supply, answer ``False``, and read that turn's own
    rationale aloud one turn later.

    **The precondition is narrowed and the outcome is not.** §8 case 9 says only "a
    turn supplied a withheld record that parks"; the parking turn here is the first
    of a fresh conversation over a store holding no episode, so its tail is empty
    and the belief about Alice reached its supply through the relevance read — the
    narrowed set ADR-0210 §1 names. Test 9's second half is untouched by a different
    route: ADR-0204 §2's fourth clause makes the resolution carry the parking turn's
    own retained value and forbids recomputing it, and ADR-0210 §2's first clause
    keeps that whole.
    """
    goals = iter(f"g-{n}" for n in range(1, 10))
    harness = _wired(
        FakeModelProvider(_ANSWER),
        planner=_EchoingPlanner(needs="hikes"),
        tools=(confirmable(),),
        loop_id_factory=lambda: next(goals),
        transcriber=FakeSpeechTranscriber(transcripts=[_ASKED, _ASKED]),
    )
    await _seed(
        harness,
        _belief("rec-1", _SPEAKABLE_CONTENT),
        _belief("rec-2", _WITHHELD_CONTENT, about_person="Alice"),
    )

    assert not _episodes(await harness.memory.export()), (
        "no episode exists yet, so the parking turn's tail is empty and the withheld "
        "belief stands in ADR-0074 §5's second group (ADR-0210 §1)"
    )

    parked = await harness.engine.converse_spoken(_RECORDING, plays=(_MP4,), timeout=PATIENT)
    assert parked.outcome is not None
    assert parked.outcome.step is not None
    assert parked.outcome.step.disposition is Disposition.AWAITING_CONFIRMATION
    token = parked.outcome.step.confirmation.token  # type: ignore[union-attr]

    resumed = await harness.engine.resume(token, approved=True, timeout=PATIENT)
    assert resumed.step is not None

    captured = _episodes(await harness.memory.export())
    assert len(captured) == 2, "the park and its resolution are two episodes (ADR-0074 §3)"
    assert _stamped(captured) == {one.id for one in captured}

    third = await harness.engine.converse_spoken(
        _RECORDING,
        plays=(_MP4,),
        timeout=PATIENT,
        conversation_id=parked.outcome.conversation_id,
    )

    assert third.outcome is not None
    assert third.outcome.turn is not None
    assert not _episodes(third.outcome.turn.memories)


async def test_a_recovered_resumption_and_a_routed_pass_carry_false() -> None:
    """§8 case 10: ``False`` because their episodes hold no turn, not because nothing ran.

    ADR-0204 §2's fifth clause, both halves in one case, with the captured
    ``content`` read to show why the value is true of each rather than a hole: a
    recovered resumption renders the bare fact of the resumption, and a routed pass
    renders the utterance and a phrase for the route's outcome (ADR-0197 §10).
    Both stores hold a record ADR-0199 §3 withholds, so a pass that had evaluated a
    supply would have found one.
    """
    harness = Harness(tools=(confirmable(),), planner=OneStepPlanner())
    await _seed(harness, _belief("rec-2", _WITHHELD_CONTENT, about_person="Alice"))
    parked = await harness.engine.converse("send it", timeout=PATIENT)
    assert parked.step is not None

    fresh = _fresh_facade(harness)
    pending = await fresh.pending_confirmations()
    assert len(pending) == 1
    recovered = await fresh.resume(pending[0].token, approved=True, timeout=PATIENT)
    assert recovered.turn is None, "a recovered park has no live turn (ADR-0052 §3)"

    resumption = _episodes(await harness.memory.export())[-1]
    assert resumption.placement == Placement()
    assert "The user asked:" not in resumption.content
    assert "The assistant's plan:" not in resumption.content

    routed_harness = Harness(
        composing=ComposingStage(
            model=FakeModelProvider("I have forgotten it."), streaming=FakeStreamingCompleter()
        ),
        planner=NoStepPlanner(),
        routing=RoutingStage(
            model=FakeModelProvider(json.dumps({"operation": "forget", "query": "cardiology"})),
            recorder=FakeRoutingRecorder(),
        ),
    )
    await _seed(routed_harness, _belief("rec-2", _WITHHELD_CONTENT, about_person="Alice"))

    routed = await routed_harness.engine.converse("forget what I said", timeout=PATIENT)

    assert routed.routed is not None
    episode = _episodes(await routed_harness.memory.export())[-1]
    assert episode.placement == Placement()
    assert episode.content == "The user asked: forget what I said", (
        "no goal statement and no plan rationale of any turn — there was no turn"
    )


async def test_a_bounded_turn_supplied_a_stamped_episode_captures_a_stamped_episode() -> None:
    """§8 case 14: §2's second term, and the hop it closes.

    The direct evaluation alone reads the stamped episode as ``OBSERVED`` with
    ``about_person`` unset, places it speakable and yields ``False`` — so without
    the disjunction one typed turn over a stamped episode strips the stamp off the
    whole warrant, and the next spoken turn reads the laundered rendering aloud.
    """
    goals = iter(f"g-{n}" for n in range(1, 10))
    harness = _wired(
        FakeModelProvider(_ANSWER),
        planner=_EchoingPlanner(),
        loop_id_factory=lambda: next(goals),
        transcriber=FakeSpeechTranscriber(transcripts=[_ASKED]),
    )
    # The stamped episode of case 1, and *only* it: the belief about Alice is gone,
    # so the second turn's stamp can only have come from §2's second term.
    await _seed(harness, _belief("rec-2", _WITHHELD_CONTENT, about_person="Alice"))
    first = await harness.engine.converse(_ASKED, timeout=PATIENT)
    assert first.conversation_id is not None
    await harness.memory.delete("rec-2")

    second = await harness.engine.converse(
        _ASKED, timeout=PATIENT, conversation_id=first.conversation_id
    )

    assert second.turn is not None
    assert _stamped(second.turn.memories), "the stamped episode was in the second turn's supply"
    captured = _episodes(await harness.memory.export())
    assert len(captured) == 2
    assert _stamped(captured) == {one.id for one in captured}

    spoken = await harness.engine.converse_spoken(
        _RECORDING, plays=(_MP4,), timeout=PATIENT, conversation_id=first.conversation_id
    )

    assert spoken.outcome is not None
    assert spoken.outcome.turn is not None
    assert not _episodes(spoken.outcome.turn.memories), "neither episode reached the spoken turn"


async def test_a_belief_derived_from_a_stamped_episode_is_stamped_and_withheld() -> None:
    """§8 case 11: §5's inheritance clause, pinned end to end.

    The observer distils a belief from the stamped episode a typed turn captured,
    and what it produces is ``OBSERVED`` with ``about_person`` unset — a class
    ADR-0199 §3's third clause places **speakable**. Without §5's derivation rule
    the stage writes that belief unstamped and #1708's laundering simply moves one
    distillation along; with it, the belief carries the stamp and §3 withholds it
    from the spoken channel like the episode it came from.
    """
    goals = iter(f"g-{n}" for n in range(1, 10))
    harness = _wired(
        FakeModelProvider(_ANSWER),
        planner=_EchoingPlanner(),
        loop_id_factory=lambda: next(goals),
        transcriber=FakeSpeechTranscriber(transcripts=[_ASKED]),
    )
    await _seed(harness, _belief("rec-2", _WITHHELD_CONTENT, about_person="Alice"))
    typed = await harness.engine.converse(_ASKED, timeout=PATIENT)
    assert typed.conversation_id is not None
    # Only the episode is left to derive from, and only it can be the stamp's source.
    await harness.memory.delete("rec-2")

    report = await harness.engine.observe(conversation_id=typed.conversation_id)

    assert report.proposals, "the observer distilled something from the episode"
    distilled = tuple(
        one
        for one in await harness.memory.export()
        if not isinstance(one, EpisodicMemory) and one.id != "rec-2"
    )
    assert distilled, "the distilled belief was written"
    assert _stamped(distilled) == {one.id for one in distilled}

    spoken = await harness.engine.converse_spoken(
        _RECORDING, plays=(_MP4,), timeout=PATIENT, conversation_id=typed.conversation_id
    )

    assert spoken.outcome is not None
    assert spoken.outcome.turn is not None
    supplied = {one.id for one in spoken.outcome.turn.memories}
    assert not supplied & {one.id for one in distilled}, (
        "a belief derived from a stamped record is withheld from this channel too"
    )


# --- ADR-0210 §9: what the evaluation is taken over --------------------------
# ADR-0210 §1 narrows one boolean on one channel: on a channel of unbounded
# audience ADR-0204 §2's disjunction and the fact ADR-0199 §5's third clause
# carries to the composing stage are evaluated over the members of the supply a
# relevance read taken with this turn's own goal statement returned — ADR-0074
# §5's second and third groups, named by the read and not by the group — together
# with the turn's context facets, and never over a member the supply holds only
# because it stands in the conversation's own recent turns.
#
# The **subtraction is untouched** and runs over the whole supply, first group
# included (§1's fourth clause), which is why every case below that asserts a
# boolean also asserts what the turn was supplied. What a member of the first
# group loses is the power to set a boolean.


def _ids(records: Sequence[MemoryRecord]) -> tuple[str, ...]:
    """The ids of ``records`` in order.

    Compared instead of the records themselves because the belief composition
    hands the loop ``model_copy`` results carrying a ``score`` — the same records
    at the same ids, and not the objects a test seeded.
    """
    return tuple(one.id for one in records)


def _stamped_belief(record_id: str, content: str) -> SemanticMemory:
    """§9's inherited-term fixture: a belief ADR-0199 §3 would place **speakable**.

    ``about_person`` unset and a placed ``Provenance.source``, so §3's third clause
    places it and the *first* term of ADR-0204 §2's disjunction is false of it. What
    withholds it is its own **placement** alone (ADR-0217 §2) — §5's inherited route,
    which is the term §9's third clause requires pinned separately. A fixture §3
    withholds on its own account would fire the first term and prove nothing about
    the second.
    """
    return SemanticMemory(
        id=record_id,
        content=content,
        fact=content,
        provenance=Provenance(
            source=MemorySource.OBSERVED,
            confidence=0.6,
            last_updated=_AT,
        ),
        placement=_NARROWED,
    )


def _episode(
    episode_id: str,
    content: str,
    *,
    stamped: bool = False,
    about_person: str | None = None,
) -> EpisodicMemory:
    """A captured turn, as ``orchestration.conversations`` writes one.

    ``OBSERVED``, which ``band_of`` maps to ``DERIVED`` — the band ADR-0158 §3 pins
    the episodic supplement to, and the band every episode this system writes lands
    in. ``about_person`` is the knob that makes §3 withhold it on its own account;
    ``stamped`` is the knob that narrows its **placement**, which ADR-0217 §2
    withholds while §3's third
    clause still places it speakable.
    """
    return EpisodicMemory(
        id=episode_id,
        content=content,
        occurred_at=_AT,
        about_person=about_person,
        provenance=Provenance(
            source=MemorySource.OBSERVED,
            confidence=0.6,
            last_updated=_AT,
        ),
        placement=_NARROWED if stamped else Placement(),
    )


def _spoken_loop(memory: FakeMemoryStore) -> LearningLoop:
    """A :class:`LearningLoop` over ``memory``, canonical fakes everywhere else.

    The seam ADR-0210 §10 item 1 puts the read set on is
    :data:`~ai_assistant.orchestration.loop.SupplyFilter`, between retrieval and
    planning, and the loop is where both relevance reads happen — so the cases that
    turn on *which* read returned a record are driven here rather than through the
    engine, where the store, the query and the deduplication would all be several
    stages away. The engine cases below drive the consequences: what the composing
    stage is told, and what capture writes down.
    """
    return LearningLoop(
        context=FakeContextProvider(),
        memory=memory,
        writes=MemoryWriteStage(
            writer=FakeMemoryWriter(store=memory, policy=FakeMemoryPolicy(), now=lambda: _AT),
            deferrals=FakeDeferralStore(now=lambda: _AT),
        ),
        planner=FakePlanner(now=lambda: _AT),
        feedback=FakeFeedbackProcessor(),
        now=lambda: _AT,
        id_factory=lambda: "goal-1",
        registry=FakeToolRegistry(),
    )


async def _spoken_supply(
    memory: FakeMemoryStore, utterance: str, *, history: Sequence[MemoryRecord] = ()
) -> tuple[TurnResult, UnboundedAudienceSupply]:
    """One turn through the loop under the unbounded channel's filter.

    Returns the turn and the filter, so a case can assert both halves of §1 — what
    the turn was supplied (the subtraction, unnarrowed) and what the filter
    recorded (the evaluation, narrowed).
    """
    supply = UnboundedAudienceSupply(speakable_attested_sources=frozenset())
    turn = await _spoken_loop(memory).respond(utterance, history=history, narrow=supply)
    return turn, supply


async def _store(*records: MemoryRecord) -> FakeMemoryStore:
    memory = FakeMemoryStore(now=lambda: _AT)
    for record in records:
        await memory.add(record)
    return memory


async def test_the_inherited_term_fires_from_the_relevance_retrieved_group() -> None:
    """§9's third clause, first placement: the second term, over ADR-0074 §5's second group.

    ADR-0210 §1's third clause keeps **both** terms of ADR-0204 §2's disjunction and
    changes only the set they range over. This fixture is placed speakable by
    ADR-0199 §3's third clause on its own account, so the only thing that withholds
    it is the stamp — which is what makes this case able to fail an implementation
    that narrowed §1 by dropping the inherited route instead.
    """
    stamped = _stamped_belief("b-1", "the user hikes on Tuesdays")

    turn, supply = await _spoken_supply(await _store(stamped), "hikes")

    assert supply.withheld is True
    assert _ids(turn.memories) == (), "and it is subtracted, exactly as before"
    unstamped = _belief("b-1", "the user hikes on Tuesdays")
    _, kept, would_withhold = _supply(unstamped)
    assert (would_withhold, _ids(kept)) == (False, ("b-1",)), (
        "ADR-0199 §3 places this class speakable, so the stamp is the whole of the finding"
    )


async def test_the_inherited_term_fires_from_the_episodic_supplement() -> None:
    """§9's third clause, second placement — and §9's fourth clause's second arm.

    The same fixture in ADR-0158's supplement rather than in the belief
    composition. §9 requires **both** placements because an implementation reaching
    the supplement only through the deduplication collision below would carry the
    belief composition's records and the colliding ids and nothing of an ordinary
    supplemented turn — passing every other case here and under-firing on the
    commonest supplement there is.
    """
    separator = _belief("b-1", "the user hikes on Tuesdays")
    stamped = _episode("e-1", "the user asked what they do on hikes", stamped=True)

    turn, supply = await _spoken_supply(await _store(separator, stamped), "hikes")

    assert supply.withheld is True
    assert _ids(turn.memories) == ("b-1",), "the episode was subtracted; the belief was not"
    unstamped = _episode("e-1", "the user asked what they do on hikes")
    _, kept, would_withhold = _supply(separator, unstamped)
    assert (would_withhold, _ids(kept)) == (False, ("b-1", "e-1")), (
        "an unstamped episode of this class is speakable, so the stamp is the finding"
    )


async def test_a_withheld_class_in_the_episodic_supplement_fires_the_direct_term() -> None:
    """§9's fourth clause, first arm: the supplement standing on its own, first term.

    A record ADR-0199 §3 withholds on its own account, returned by
    ``_supplement``'s own read and kept by ADR-0158 §4's deduplication because
    neither the conversation tail nor the belief composition holds it. The pair with
    the case above is what §9's fourth clause asks for: both terms, on the third
    group, separately from the collision.
    """
    separator = _belief("b-1", "the user hikes on Tuesdays")
    withheld = _episode("e-1", "the user asked about hikes with Alice", about_person="Alice")

    turn, supply = await _spoken_supply(await _store(separator, withheld), "hikes")

    assert supply.withheld is True
    assert _ids(turn.memories) == ("b-1",)


async def test_a_supplement_read_that_collides_with_the_tail_still_fires() -> None:
    """§9's eighth clause, and the reason ADR-0210 §1's second clause is stated over the reads.

    ``LearningLoop._supplement`` computes ``held = {record.id for record in
    preceding}`` and returns only what is not in it, so an episode of this
    conversation that the supplement's read **does** return is deduplicated away and
    survives at the tail's position alone. §1's second clause rules that such a
    record fires — "the supplement's read selected it for this goal, and the
    deduplication decides where one copy sits rather than why it was chosen" — so an
    implementation evaluating over the composed groups answers ``False`` here.

    The second drive is the same collision with the stamp removed, and it is what
    shows the collision is real rather than assumed: one copy of the episode, at
    index 0, the tail's position, and none in the supplement.
    """
    separator = _belief("b-1", "the user hikes on Tuesdays")
    stamped = _episode("e-1", "the user asked what they do on hikes", stamped=True)

    turn, supply = await _spoken_supply(
        await _store(separator, stamped), "hikes", history=(stamped,)
    )

    assert supply.withheld is True
    assert _ids(turn.memories) == ("b-1",)

    unstamped = _episode("e-1", "the user asked what they do on hikes")
    plain, plain_supply = await _spoken_supply(
        await _store(separator, unstamped), "hikes", history=(unstamped,)
    )
    assert _ids(plain.memories) == ("e-1", "b-1"), (
        "one copy, at the tail's position: ADR-0158 §4 deduplicated the supplement's"
    )
    assert plain_supply.withheld is False


async def test_a_tail_no_relevance_read_returned_fires_nothing() -> None:
    """§9's eighth clause's negative twin, and #1775's mechanism at the loop.

    The same stamped episode in the tail, and a supplement read that does **not**
    return it. Nothing a relevance read of this turn returned was withheld, so §1's
    evaluation is ``False`` — while the episode is still subtracted from everything
    the turn runs over. Without this twin the case above passes on an implementation
    that simply evaluated the whole supply.
    """
    separator = _belief("b-1", "the user hikes on Tuesdays")
    stamped = _episode("e-1", "the user asked about a cardiology appointment", stamped=True)

    turn, supply = await _spoken_supply(
        await _store(separator, stamped), "hikes", history=(stamped,)
    )

    assert supply.withheld is False, (
        "no relevance read of this turn returned it: ADR-0210 §1's first clause"
    )
    assert _ids(turn.memories) == ("b-1",), (
        "and it is still removed — §1's fourth clause leaves the subtraction whole"
    )


#: A later question sharing no term with the episode the first turn captured.
#: ``FakeMemoryStore`` scores by substring, so "the withheld record is in the
#: conversation tail and in no retrieved group" is arranged by choosing words —
#: neither ``cycles`` nor ``weekends`` occurs in ``The user asked: what is on this
#: week`` or in either belief that turn was supplied.
_LATER: Final = "cycles weekends"

#: The one belief the later question does retrieve. Seeded **after** the first
#: turn, so it is not in that turn's rationale and therefore not in the episode
#: the tail carries — which is what keeps the two queries independent.
_LATER_CONTENT: Final = "the user cycles at weekends"


async def _tail_holding_a_stamped_episode(
    model: FakeModelProvider, planner: _EchoingPlanner
) -> tuple[Harness, str, str]:
    """#1775's fixture: a conversation whose tail holds a stamped episode.

    A typed turn over a store holding a belief about Alice captures an episode
    ADR-0204 §2 stamps. The belief is then deleted and a fresh speakable one seeded,
    so a second turn in the same conversation retrieves something and retrieves
    **nothing withheld** — the stamped episode stands in ADR-0074 §5's first group
    and in no other, which is exactly the state #1775 measured and the state
    ADR-0210 §1 is about.

    Returns:
        The harness, the conversation the turns share, and the id of the stamped
        episode the first turn captured.
    """
    goals = iter(f"g-{n}" for n in range(1, 10))
    harness = _wired(
        model,
        planner=planner,
        loop_id_factory=lambda: next(goals),
        transcriber=FakeSpeechTranscriber(transcripts=[_LATER]),
    )
    await _seed(
        harness,
        _belief("rec-1", _SPEAKABLE_CONTENT),
        _belief("rec-2", _WITHHELD_CONTENT, about_person="Alice"),
    )

    typed = await harness.engine.converse(_ASKED, timeout=PATIENT)
    assert typed.conversation_id is not None
    await harness.memory.delete("rec-2")
    await _seed(harness, _belief("rec-3", _LATER_CONTENT))

    captured = _episodes(await harness.memory.export())
    assert len(captured) == 1
    assert captured[0].placement.reach is PlacementReach.OWNER, (
        "the tail's episode is stamped — ADR-0204 §2 over the typed turn's own supply"
    )
    return harness, typed.conversation_id, captured[0].id


async def test_a_stamped_episode_in_the_tail_alone_is_not_reported_as_a_withholding() -> None:
    """§9's first clause: #1775's engine, pinned.

    Before ADR-0210 this turn deflected and its episode was stamped, so the next
    turn's tail held two stamped episodes and the next held three — "monotonic and
    unbounded in practice", and the reason ADR-0204 §6's continuity claim stopped
    being true after the first withholding. The stamped episode is still removed
    from everything this turn runs over; what it no longer does is set a boolean.
    """
    model = FakeModelProvider(_ANSWER)
    planner = _EchoingPlanner()
    harness, conversation, stamped_id = await _tail_holding_a_stamped_episode(model, planner)

    spoken = await harness.engine.converse_spoken(
        _RECORDING, plays=(_MP4,), timeout=PATIENT, conversation_id=conversation
    )

    assert spoken.outcome is not None
    assert spoken.outcome.turn is not None
    assert _ids(spoken.outcome.turn.memories) == ("rec-3",), (
        "this turn's relevance reads returned one belief, and nothing withheld"
    )
    assert "NOT AVAILABLE ON THIS CHANNEL" not in _prompt(model, 1), (
        "ADR-0199 §5's third clause as ADR-0210 narrows it: the stage is not told"
    )
    captured = _episodes(await harness.memory.export())
    assert len(captured) == 2
    assert _stamped(captured) == {stamped_id}, (
        "the spoken turn's own episode carries False, so the spoken channel keeps "
        "its conversation (ADR-0204 §6, restored)"
    )


async def test_a_stamped_episode_in_the_tail_alone_is_still_subtracted() -> None:
    """§9's ninth clause: §1's fourth clause, which leaves the subtraction whole.

    The boolean is ``False`` and the record is gone anyway — from the supply the
    ``TurnResult`` carries, from what the planner was handed, and from what the
    composing stage was handed. ADR-0210 "gives no stage a record it did not have
    before", and without this case a narrowing that also stopped removing would pass
    the case above.
    """
    model = FakeModelProvider(_ANSWER)
    planner = _EchoingPlanner()
    harness, conversation, stamped_id = await _tail_holding_a_stamped_episode(model, planner)

    spoken = await harness.engine.converse_spoken(
        _RECORDING, plays=(_MP4,), timeout=PATIENT, conversation_id=conversation
    )

    assert spoken.outcome is not None
    assert spoken.outcome.turn is not None
    assert stamped_id not in _ids(spoken.outcome.turn.memories)
    assert stamped_id not in _ids(planner.calls[-1][1]), "not among the planner's inputs"
    prompt = _prompt(model, 1)
    assert _WITHHELD_CONTENT not in prompt
    assert _ASKED not in prompt, "the earlier turn's own question, carried in that episode"
    assert "NOT AVAILABLE ON THIS CHANNEL" not in prompt, "and the boolean is False"


async def test_the_bounded_channel_still_fires_on_the_conversation_tail() -> None:
    """§9's fifth clause: ADR-0210 §1's last clause, and #1708's path left alone.

    The same conversation and the same stamped episode, typed. Nothing is
    subtracted, the disjunction ranges over the whole supply — first group included
    — and the capture is stamped. A narrowing on this channel would let one typed
    turn strip the stamp off the whole warrant, which is what ADR-0204 §2 was
    written to close.
    """
    model = FakeModelProvider(_ANSWER)
    planner = _EchoingPlanner()
    harness, conversation, stamped_id = await _tail_holding_a_stamped_episode(model, planner)

    typed = await harness.engine.converse(_LATER, timeout=PATIENT, conversation_id=conversation)

    assert typed.turn is not None
    assert stamped_id in _ids(typed.turn.memories), (
        "ADR-0204 §4: a bounded channel's turn is supplied everything it retrieved"
    )
    captured = _episodes(await harness.memory.export())
    assert len(captured) == 2
    assert _stamped(captured) == {one.id for one in captured}


async def test_a_withheld_record_a_relevance_read_returned_is_told_and_stamped() -> None:
    """§9's second clause: the exit test's arm, unchanged by ADR-0210.

    The turn is the first of a fresh conversation, so ADR-0074 §5's first group is
    empty and every member of its supply stood in a group a relevance read taken
    with this turn's own goal statement returned. §1 narrows what may fire and
    narrows nothing here: the composing stage is told and the episode is stamped
    exactly as before.
    """
    model = FakeModelProvider(_ANSWER)
    harness = _wired(
        model,
        planner=_EchoingPlanner(),
        transcriber=FakeSpeechTranscriber(transcripts=[_ASKED]),
    )
    await _seed(
        harness,
        _belief("rec-1", _SPEAKABLE_CONTENT),
        _belief("rec-2", _WITHHELD_CONTENT, about_person="Alice"),
    )
    assert not _episodes(await harness.memory.export()), "no episode exists, so the tail is empty"

    spoken = await harness.engine.converse_spoken(_RECORDING, plays=(_MP4,), timeout=PATIENT)

    assert spoken.outcome is not None
    assert spoken.outcome.turn is not None
    assert _ids(spoken.outcome.turn.memories) == ("rec-1",)
    assert "NOT AVAILABLE ON THIS CHANNEL" in _prompt(model, 0)
    captured = _episodes(await harness.memory.export())
    assert len(captured) == 1
    assert captured[0].placement.reach is PlacementReach.OWNER


class _FixedContext:
    """A ``ContextProvider`` returning one context **without revalidating it**.

    ``FakeContextProvider`` snapshots by ``model_dump`` and
    ``CurrentContext.model_validate``, which is right for what it is for and
    coerces a *subclass* of a placed facet back to the declared type — so the
    canonical fake cannot deliver an unplaced facet to a turn at all. ADR-0199 §3's
    fourth clause is entirely about that case, so it needs a double that hands the
    object over as it is.

    Structurally implements
    :class:`~ai_assistant.core.protocols.ContextProvider`.
    """

    def __init__(self, context: CurrentContext) -> None:
        self._context = context

    async def assemble(self) -> CurrentContext:
        """The configured context, unchanged. ``CurrentContext`` is frozen."""
        return self._context


async def test_an_unplaced_facet_fires_both_consequences_over_a_clean_retrieval() -> None:
    """§9's seventh clause: the facet arm unmoved, and both of its consequences.

    A facet is *assembled* rather than retrieved, so it is the one arm on which §1's
    set is not what a relevance read returned — and ADR-0210 §1 keeps it in
    deliberately, on ADR-0199 §3's sixth clause: an unplaced facet should be loud
    rather than quiet. Both consequences are asserted because a test reading only
    "the evaluation fires" would not distinguish an implementation that dropped the
    facet from the notification while keeping it in the stamp.
    """

    class HealthFacet(CalendarFacet):
        """A facet nobody has placed, standing in for the next source to land."""

    model = FakeModelProvider(_ANSWER)
    harness = _wired(
        model,
        planner=_EchoingPlanner(),
        context=_FixedContext(
            CurrentContext(
                now=_AT,
                time_of_day=TimeOfDay.AFTERNOON,
                is_weekend=False,
                within_working_hours=True,
                calendar=HealthFacet(
                    source="health", read_at=_AT, entries_in_progress=1, covers_until=_AT
                ),
            )
        ),
        transcriber=FakeSpeechTranscriber(transcripts=[_ASKED]),
    )
    await _seed(harness, _belief("rec-1", _SPEAKABLE_CONTENT))

    spoken = await harness.engine.converse_spoken(_RECORDING, plays=(_MP4,), timeout=PATIENT)

    assert spoken.outcome is not None
    assert spoken.outcome.turn is not None
    assert _ids(spoken.outcome.turn.memories) == ("rec-1",), "nothing retrieved is withheld"
    assert spoken.outcome.turn.context.calendar is None, "the unplaced facet was subtracted"
    assert "NOT AVAILABLE ON THIS CHANNEL" in _prompt(model, 0), "consequence one"
    captured = _episodes(await harness.memory.export())
    assert len(captured) == 1
    assert captured[0].placement.reach is PlacementReach.OWNER, "consequence two"
    assert placed_facet_kinds() == {CalendarFacet, EmailFacet}, (
        "and §3's list is what it was — this ADR places and unplaces nothing"
    )
