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
    PlanStep,
    Provenance,
    Role,
    SemanticMemory,
    SpokenAudio,
    SpokenAudioFormat,
    TimeOfDay,
)
from ai_assistant.orchestration import RoutingStage
from ai_assistant.orchestration.composing import ComposingStage
from ai_assistant.orchestration.disclosure import (
    placed_facet_kinds,
    speakable_sources,
    supply_for_unbounded_audience,
)
from ai_assistant.testing import (
    FakeContextProvider,
    FakeMemoryStore,
    FakeModelProvider,
    FakeRoutingRecorder,
    FakeSpeechSynthesizer,
    FakeSpeechTranscriber,
    FakeStreamingCompleter,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.core.types import MemoryWrite

_AT: Final = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)
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
) -> tuple[CurrentContext, tuple[MemoryRecord, ...], bool]:
    """ADR-0203 §1's subtraction, over one context and one group of records.

    The narrowing predicate is applied to what the turn assembled and retrieved
    rather than to a ``TurnResult``, because since ADR-0203 §1 there is no turn yet
    when it runs: it sits between retrieval and planning.
    """
    return supply_for_unbounded_audience(context, records, speakable_attested_sources=sources)


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


def _stamped(records: Sequence[MemoryRecord]) -> set[str]:
    """The ids among ``records`` whose provenance carries ADR-0204 §1's field."""
    return {one.id for one in records if one.provenance.supplied_withheld_content}


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
    assert captured[0].provenance.supplied_withheld_content is True
    assert _WITHHELD_CONTENT in captured[0].content, (
        "the episode's content is unchanged — the stamp is what withholds it, not a filter"
    )


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
    assert captured[0].provenance.supplied_withheld_content is False


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
    """§8 case 4: #1703's path, refused.

    The withholding turn's own question is carried unrewritten into its episode
    (``_exchange_of``), which is why ADR-0203 §4's fifth clause recorded this path as
    open. It closes on the fact that the turn withheld something at all — a fact
    about the turn's supply, decided from recorded origin, and not a judgement about
    what its question said.
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

    first = await harness.engine.converse_spoken(_RECORDING, plays=(_MP4,), timeout=PATIENT)
    assert first.outcome is not None

    captured = _episodes(await harness.memory.export())
    assert len(captured) == 1
    assert captured[0].provenance.supplied_withheld_content is True

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
    assert captured[0].provenance.supplied_withheld_content is False

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
    """§8 case 9: both of one turn's episodes carry it, and neither is spoken back.

    ADR-0074 §3 captures a parking turn twice, and the second capture renders the
    **parked turn's** goal and plan from a pass that retrieves nothing of its own.
    So the value rides on the parked entry beside the turn it belongs to (ADR-0204
    §2's fourth clause): an implementation that recomputed it at the resolution
    would evaluate an empty supply, answer ``False``, and read that turn's own
    rationale aloud one turn later.
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
    assert resumption.provenance.supplied_withheld_content is False
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
    assert episode.provenance.supplied_withheld_content is False
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
