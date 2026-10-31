"""What made an activation count as having read outside content, named (#2895).

ADR-0314 §4's authorizing row records whether the activation had read outside content,
"with each ground of ADR-0306 §4:5 that held and the record it rests on", so the owner
can see which records made it count. These cases drive planning and authorizing through
the phase path over fakes, with the diagnostic record on, and read the authorizing
entry: each ground once, and ``fetched_outside`` naming the record, the story view's
part or the moment that set it. The answer, yes or no, is not what they test; the
cases in ``test_engine_phases`` hold it.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Final

from phases_support import chat_turn, phase_path, phases_harness
from test_authorizer import _ACTIVATION, _episode
from test_planning import _episode as _past_episode
from test_planning import _recorded_trigger

from ai_assistant.core.diagnostics import diagnosed_activation
from ai_assistant.core.types import (
    ActivationDigest,
    ActivationRecall,
    BeliefBand,
    ControllerStage,
    DiagnosticSource,
    DigestOutcome,
    EvidenceItem,
    LabelKind,
    MemoryKind,
    PlanningLabel,
    ProposedCall,
    RecallCue,
    RecalledItem,
    RecallOutcome,
    RecallProvenance,
    RoundResponse,
    StageOutcome,
    StoryActor,
    StoryMember,
    StoryMemberKind,
    StoryNoteAuthor,
    StorySummaryDraft,
    StorySummaryLine,
)
from ai_assistant.orchestration.conversations import conversation_channel
from ai_assistant.orchestration.disclosure import BoundedAudienceSupply
from ai_assistant.orchestration.recall import Recalled
from ai_assistant.orchestration.understanding import Fetched, TranscriptWindow
from ai_assistant.testing import (
    FakeDiagnosticSink,
    FakeStoryStore,
    FakeToolCallingCompleter,
    FakeWebSearcher,
)
from ai_assistant.testing.parties import UNIDENTIFIED_WORDS

if TYPE_CHECKING:
    from test_engine import Harness

    from ai_assistant.core.types import ActivationUnderstanding, EpisodicMemory
    from ai_assistant.orchestration.disclosure import TurnSupply
    from ai_assistant.orchestration.phase_path import PhasePath, PhaseWorking
    from ai_assistant.orchestration.story_links import Candidates
    from ai_assistant.orchestration.understanding import Windows


_AT: Final = datetime(2026, 10, 11, 12, 0, tzinfo=UTC)
_SETTLE: Final = 5.0
_DIAGNOSED: Final = "7c1e4a2b-9d3f-4b6a-8e5c-1f2a3b4c5d6e"
_BOUNDED: Final = BoundedAudienceSupply(speakable_attested_sources=frozenset())


@dataclass(frozen=True)
class _Given:
    """A pass's working set as a phase stage reads it (``PhasePass``)."""

    deadline: float
    phases: PhaseWorking
    understanding: ActivationUnderstanding | None = None
    understanding_fetch: Fetched | None = None
    supply: TurnSupply = field(default_factory=lambda: _BOUNDED)
    windows: Windows | None = None
    recalled: Recalled | None = None
    story_candidates: Candidates | None = None


def _path(
    completer: FakeToolCallingCompleter,
    harness: Harness,
    sink: FakeDiagnosticSink,
    stories: FakeStoryStore | None = None,
    *,
    look_ups: bool = False,
) -> PhasePath:
    """The thin path over the harness's own stores, writing the diagnostic record.

    ``look_ups`` offers planning's look-ups, a story read among them (ADR-0307 §6:6).
    """
    return phase_path(
        completer,
        invoker=harness.invoker,
        memory=harness.memory,
        plans=harness.plans,
        trail=harness.trail,
        conversations=harness.conversation_store,
        stories=stories,
        look_ups=look_ups,
        diagnostics=sink,
    )


def _begun(path: PhasePath, labels: tuple[PlanningLabel, ...] = ()) -> PhaseWorking:
    return path.begin(
        activation_id=_ACTIVATION,
        window=TranscriptWindow(conversation=conversation_channel("c1"), messages=()),
        conversation_id="c1",
        trigger=_recorded_trigger(),
        owner_records=True,
        labels=labels,
    )


def _book() -> ProposedCall:
    return ProposedCall(call_id="c1", name="book", arguments={"date": "2026-10-12"})


def _evidenced(episode_id: str) -> EpisodicMemory:
    """An earlier episode clean by its provenance and origin, but for its evidence."""
    past = _past_episode(episode_id)
    assert past.processing_record is not None
    digest = ActivationDigest(
        result="R1",
        question="when is it",
        outcome=DigestOutcome.ANSWERED,
        evidence=(EvidenceItem(text="The appointment is Friday at 3pm.", source="R1"),),
        recorded_at=_AT,
    )
    return past.model_copy(
        update={
            "processing_record": past.processing_record.model_copy(update={"digests": (digest,)})
        }
    )


def _found(*episode_ids: str) -> Recalled:
    """A first-run decision keeping ``episode_ids``, as recall records one."""
    items = tuple(
        RecalledItem(
            kind=MemoryKind.EPISODIC,
            id=one,
            excerpt="an earlier episode",
            provenance=RecallProvenance.USER,
            standing=BeliefBand.DERIVED,
            rests_on_recorded_external_content=False,
            found_by=(RecallCue.ACTIVATION_INPUT,),
        )
        for one in episode_ids
    )
    return Recalled(
        ActivationRecall(
            outcome=RecallOutcome.FOUND, cues=(RecallCue.ACTIVATION_INPUT,), items=items
        ),
        scores=tuple(0.9 for _ in items),
    )


async def _rounds(path: PhasePath, given: _Given, *stages: ControllerStage) -> None:
    """Run ``stages`` in order, the diagnostic record on, each done."""
    by_name = {one.name: one for one in path.stages()}
    with diagnosed_activation(_DIAGNOSED, clock=lambda: _AT):
        for stage in stages:
            assert (await by_name[stage].run(given)).outcome is StageOutcome.DONE


def _grounds(sink: FakeDiagnosticSink) -> list[list[dict[str, Any]]]:
    """The grounds of each authorizing entry, in the order written."""
    return [
        entry.model_dump(mode="json")["body"]["grounds"]
        for entry in sink.of(DiagnosticSource.AUTHORIZING)
    ]


async def test_a_record_fetched_twice_is_named_once_by_its_id() -> None:
    """#2895: what understanding fetched and what recall found, both one episode.

    The activation's own episode is clean; only the fetched episode's evidence is
    outside content, and it reaches planning both as understanding fetched it and as
    recall found it. The ground names it, once.
    """
    completer = FakeToolCallingCompleter.scripted(RoundResponse(calls=(_book(),)))
    harness = phases_harness(completer)
    await harness.memory.add(_episode())
    found = _evidenced("activation:found")
    await harness.memory.add(found)
    sink = FakeDiagnosticSink()
    path = _path(completer, harness, sink)
    working = _begun(path)
    fetched = Fetched(episodes=None, recalled=(found,), fetched=("activation:found",), missing=())
    given = _Given(
        deadline=asyncio.get_running_loop().time() + _SETTLE,
        phases=working,
        understanding_fetch=fetched,
        recalled=_found("activation:found"),
    )

    await _rounds(path, given, ControllerStage.PLANNING, ControllerStage.AUTHORIZING)

    assert working.fetched_outside
    assert list(working.fetched_outside_from) == ["activation:found"]
    # Planning was shown it under its own label too: another ground, on the same record.
    assert _grounds(sink) == [
        [
            {"ground": "fetched_outside", "record": "activation:found"},
            {"ground": "outside_episode_shown", "record": "activation:found"},
        ]
    ]


async def test_a_story_view_names_its_summary_note_and_moment_once_each_every_round() -> None:
    """#2895: a story view's marked summary, marked note and outside episode, named.

    The summary by its story's id, the note by its id, and the outside episode, shown
    both as a latest episode and as a marked moment of where the matter stands, by its
    address, once. The second round reads the views again, and they are still named
    once each.
    """
    completer = FakeToolCallingCompleter.scripted(
        RoundResponse(calls=(_book(),), text="the venue answered"),
        RoundResponse(text="Saturday."),
    )
    harness = phases_harness(completer)
    await harness.memory.add(_episode())
    await harness.memory.add(_past_episode("activation:report", parties=UNIDENTIFIED_WORDS))
    stories = FakeStoryStore(now=lambda: _AT)
    trip = (
        await stories.create(
            [
                StoryMember(kind=StoryMemberKind.ACTIVATION, id=_ACTIVATION),
                StoryMember(kind=StoryMemberKind.ACTIVATION, id="report"),
            ],
            actor=StoryActor.OWNER,
        )
    ).story_id
    assert trip is not None
    state = await stories.current_summary(trip)
    assert state is not None
    await stories.write_summary(
        trip,
        StorySummaryDraft(lines=(StorySummaryLine(text="A reply came."),), outside=True),
        as_of=state.as_of,
    )
    written = await stories.append_note(
        trip,
        "The venue says Saturday.",
        author=StoryNoteAuthor.PLANNING,
        written_during="report",
        outside=True,
    )
    note = written.note
    assert note is not None
    sink = FakeDiagnosticSink()
    path = _path(completer, harness, sink, stories)
    working = _begun(path)
    given = _Given(deadline=asyncio.get_running_loop().time() + _SETTLE, phases=working)

    await _rounds(
        path,
        given,
        ControllerStage.PLANNING,
        ControllerStage.AUTHORIZING,
        ControllerStage.ACTING,
        ControllerStage.PLANNING,
        ControllerStage.AUTHORIZING,
    )

    named = [trip, str(note.note_id), "activation:report"]
    assert list(working.fetched_outside_from) == named
    (marked, answered) = working.planning_rounds()
    fetched = [{"ground": "fetched_outside", "record": one} for one in named]
    shown = [
        {"ground": "note_shown_marked", "record": str(note.note_id)},
        {"ground": "outside_episode_shown", "record": "activation:report"},
    ]
    # The second round's text is its notes (ADR-0356 §7:2), marked too, and named once.
    notes = [{"ground": "notes_marked", "record": one.id} for one in (marked, answered)]
    assert _grounds(sink) == [
        [*fetched, notes[0], *shown],
        [*fetched, *notes, *shown],
    ]


async def test_a_story_read_names_the_marked_note_its_view_shows_once() -> None:
    """#2922: a story's full view, read by a story read, names what it rests on.

    The story is none of the activation's own and no referent of understanding's, so
    planning is shown no view of it before it reads one: only the read can say outside
    content was read. Its full view shows a marked note, which the next authorizing
    entry names once, by its id, as the story views' notes are named.
    """
    completer = FakeToolCallingCompleter.scripted(
        RoundResponse(
            calls=(ProposedCall(call_id="c1", name="read_story", arguments={"story": "S1"}),)
        ),
        RoundResponse(calls=(_book(),), text="the venue answered"),
    )
    harness = phases_harness(completer)
    await harness.memory.add(_episode())
    await harness.memory.add(_past_episode("activation:past"))
    stories = FakeStoryStore(now=lambda: _AT)
    trip = (
        await stories.create(
            [StoryMember(kind=StoryMemberKind.ACTIVATION, id="past")], actor=StoryActor.OWNER
        )
    ).story_id
    assert trip is not None
    written = await stories.append_note(
        trip,
        "The venue says Saturday.",
        author=StoryNoteAuthor.PLANNING,
        written_during="past",
        outside=True,
    )
    note = written.note
    assert note is not None
    sink = FakeDiagnosticSink()
    path = _path(completer, harness, sink, stories, look_ups=True)
    working = _begun(path, (PlanningLabel(label="S1", kind=LabelKind.STORY, id=trip),))
    given = _Given(deadline=asyncio.get_running_loop().time() + _SETTLE, phases=working)

    await _rounds(
        path,
        given,
        ControllerStage.PLANNING,
        ControllerStage.AUTHORIZING,
        ControllerStage.ACTING,
        ControllerStage.PLANNING,
        ControllerStage.AUTHORIZING,
    )

    (view,) = working.pages.values()
    assert view.story_id == trip
    (_, marked) = working.planning_rounds()
    # Before the read, nothing outside; after it, the note, named once by its id.
    assert _grounds(sink) == [
        [],
        [
            {"ground": "fetched_outside", "record": str(note.note_id)},
            {"ground": "notes_marked", "record": marked.id},
            {"ground": "note_shown_marked", "record": str(note.note_id)},
        ],
    ]
    assert list(working.fetched_outside_from) == [str(note.note_id)]


async def test_a_digest_the_episode_and_the_working_set_both_hold_is_one_ground() -> None:
    """#2895: through the engine, the episode's record holds what the working set holds.

    A search is digested after the first round, and the second round proposes a
    booking. By the rulings after it, the episode's record holds the earlier rounds and
    the digest, as the working set does, and each authorizing entry lists each once.
    """
    completer = FakeToolCallingCompleter.scripted(
        RoundResponse(
            text="Let me look that up.",
            calls=(
                ProposedCall(
                    call_id="c1",
                    name="web_search",
                    arguments={"query": "museum hours", "looking_for": "when it opens"},
                ),
            ),
        ),
        # Its own call id: a work's exchange holds each once (ADR-0356 §13).
        RoundResponse(
            calls=(_book().model_copy(update={"call_id": "c2"}),), text="it opens at nine"
        ),
        RoundResponse(text="It opens at nine."),
    )
    sink = FakeDiagnosticSink()
    harness = phases_harness(
        completer,
        phases={
            "searcher": FakeWebSearcher(results=("Open daily from 9:00 to 17:00.",)),
            "diagnostics": sink,
        },
        diagnostics=sink,
    )

    _, episode = await chat_turn(harness, "when does the museum open?")

    record = episode.processing_record
    assert record is not None
    (digest,) = record.digests
    assert digest.outcome is DigestOutcome.ANSWERED
    (_, marked, answered) = record.rounds
    assert marked.notes_marked
    each_once = [
        {"ground": "digest_answered", "record": "R1"},
        {"ground": "notes_marked", "record": marked.id},
    ]
    # The last round's text is its notes alone (ADR-0356 §7:2-§7:3), marked too; with no
    # call, it has nothing to authorize, so it brings no entry of its own.
    assert answered.notes_marked
    assert _grounds(sink) == [[], each_once]
