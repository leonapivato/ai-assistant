"""ADR-0300 §6:5-§6:9: the understanding stage renders the candidate stories and links them.

The stage alone, over a scripted model and hand-built short views: the fourth section,
its ``S`` labels and the instruction (§6:5, §6:9), the reply's ``belongs_to`` resolved
into ``story_links`` (§6:6, §6:7, ADR-0353 §9:4), and a defective label there repaired
once and then dropped and counted (§6:8). An ``H`` label naming a place-window item that
links to an activation resolves to it, as a ``P`` label naming that activation's episode
would, and one naming an item that links to nothing is dropped and counted with no
repair (ADR-0303 §7, ADR-0301 §1:1, ADR-0353 §9:12). An ``S`` label cited in ``cites``
resolves to a ``story`` referent with no repair, and links nothing (ADR-0304 §8). A
recalled fact named in ``belongs_to`` is dropped and counted with no repair, and a pass
that may not be shown a note is told nothing about notes (ADR-0305). Which candidates
are assembled is ``test_story_links.py``'s.
"""

from __future__ import annotations

import asyncio
import itertools
import json
from typing import TYPE_CHECKING, Any, Final

import pytest
from story_support import (
    AT,
    CONVERSATION,
    EVENTS,
    activation,
    address,
    episode,
    memory_of,
    story,
)
from understanding_support import Container, Rendered, TextAsStructured

from ai_assistant.core.diagnostics import diagnosed_activation
from ai_assistant.core.types import (
    UNDERSTANDING_REFERENT_EXCERPT_CHARS,
    ActivationRecall,
    BeliefBand,
    ChannelContext,
    ChannelContextItem,
    DiagnosticKind,
    DiagnosticSource,
    Memory,
    MemoryKind,
    MessageAuthor,
    RecallCue,
    RecalledItem,
    RecallOutcome,
    RecallProvenance,
    StoryActor,
    StoryNote,
    StoryNoteAuthor,
    StorySummaryLine,
    TranscriptMessage,
    UnderstandingReferent,
)
from ai_assistant.orchestration.disclosure import BoundedAudienceSupply, UnboundedAudienceSupply
from ai_assistant.orchestration.story_links import Candidates, ShortView, StoryCandidates
from ai_assistant.orchestration.understanding import (
    UNDERSTANDING_PROMPT,
    SuppliedWindow,
    TranscriptWindow,
    UnderstandingStage,
    place_window_links,
)
from ai_assistant.testing import (
    FakeDiagnosticSink,
    FakeModelProvider,
    FakeStoryStore,
    default_prompt,
)
from ai_assistant.testing.memories import memory, remembered_support

if TYPE_CHECKING:
    from ai_assistant.core.prompts import PromptTemplate
    from ai_assistant.core.types import ActivationUnderstanding, EpisodicMemory
    from ai_assistant.orchestration.disclosure import TurnSupply
    from ai_assistant.orchestration.understanding import ChannelWindow

BOUNDED: Final = BoundedAudienceSupply(speakable_attested_sources=frozenset())
UNBOUNDED: Final = UnboundedAudienceSupply(speakable_attested_sources=frozenset())
WINDOW: Final = SuppliedWindow(
    ChannelContext(history=(ChannelContextItem(text="Trip plans", item_id="item-1"),))
)

#: Understanding's shipped template, as the composition root hands it the stage.
_UNDERSTANDING = default_prompt(UNDERSTANDING_PROMPT)


def _proposal(**fields: Any) -> str:
    return json.dumps({"understanding": "The canoe is booked."} | fields)


def _note(note_id: int, text: str, **fields: Any) -> StoryNote:
    values: dict[str, Any] = {
        "note_id": note_id,
        "text": text,
        "author": StoryNoteAuthor.PLANNING,
        "written_during": "a-1",
        "outside": False,
        "written_at": AT,
    }
    return StoryNote.model_validate(values | fields)


_TRIP: Final = ShortView(
    story_id="story:trip",
    lines=(
        StorySummaryLine(text="A camping trip to Riverside."),
        StorySummaryLine(text="The park says the lake is closed."),
    ),
    outside=True,
    notes=(
        _note(
            4,
            "Waiting on your answer about the canoe.",
            author=StoryNoteAuthor.OWNER,
            written_during=None,
        ),
        _note(3, "The campground emailed a new rate.", outside=True),
    ),
    episodes=(episode("a-1", text="Book the canoe for Sunday."),),
)
_RUNNING: Final = ShortView(story_id="story:running", lines=(), notes=(), episodes=())


async def _understand(  # noqa: PLR0913 — the model, then one knob per input a case varies
    model: FakeModelProvider,
    *,
    stories: Candidates | None,
    episodes: tuple[EpisodicMemory, ...] | None = (),
    recalled: tuple[EpisodicMemory | Memory, ...] = (),
    window: ChannelWindow = WINDOW,
    audience: TurnSupply = BOUNDED,
    prompt: PromptTemplate = _UNDERSTANDING,
    diagnostics: FakeDiagnosticSink | None = None,
) -> ActivationUnderstanding:
    recall = None
    if recalled:
        recall = ActivationRecall(
            outcome=RecallOutcome.FOUND,
            cues=(RecallCue.ACTIVATION_INPUT,),
            items=tuple(_item(record.id, MemoryKind(record.kind)) for record in recalled),
        )
    stage = UnderstandingStage(
        model=TextAsStructured(model), excerpt_chars=2000, prompt=prompt, diagnostics=diagnostics
    )
    with diagnosed_activation("a-0", clock=lambda: AT):
        return await stage.understand(
            "The canoe is booked.",
            channel=EVENTS,
            window=window,
            audience=audience,
            episodes=episodes,
            version=1,
            now=lambda: AT,
            deadline=asyncio.get_running_loop().time() + 60,
            recall=recall,
            recalled=recalled,
            stories=stories,
        )


def _item(record_id: str, kind: MemoryKind) -> RecalledItem:
    return RecalledItem(
        kind=kind,
        id=record_id,
        excerpt="x",
        provenance=RecallProvenance.USER,
        standing=BeliefBand.DERIVED,
        rests_on_recorded_external_content=False,
        found_by=(RecallCue.ACTIVATION_INPUT,),
    )


_FACT: Final = memory("fact-1", "The canoe holds two.", remembered_support(when=AT, added_at=AT))


def _payload(model: FakeModelProvider, call: int = 0) -> Rendered:
    return Rendered(model.calls[call].messages[1].content)


def _matters(model: FakeModelProvider, call: int = 0) -> list[Container]:
    """The matters the call rendered, each with the tags it holds (ADR-0353 §2, §3:3)."""
    return _payload(model, call).containers("Matters")


def _instruction(model: FakeModelProvider) -> str:
    return model.calls[0].messages[0].content


# --- §6:5, §6:9: the fourth section and its instruction ------------------------------


async def test_no_candidates_say_the_system_does_not_have_them() -> None:
    model = FakeModelProvider(_proposal())

    understood = await _understand(model, stories=None)

    assert _payload(model).section("Matters").startswith("The system does not have it")
    assert understood.story_links == ()


@pytest.mark.parametrize(
    ("recalled", "stories"),
    [
        ((), None),
        ((_FACT,), None),
        ((), Candidates(views=())),
        ((_FACT,), Candidates(views=(_TRIP,))),
    ],
    ids=["neither", "recalled", "stories", "both"],
)
async def test_the_template_takes_no_flag_and_every_section_renders(
    recalled: tuple[Memory, ...], stories: Candidates | None
) -> None:
    """ADR-0353 §8:1, §8:3: every section on every call, and one instruction for all."""
    model = FakeModelProvider(_proposal())
    sink = FakeDiagnosticSink()

    await _understand(model, stories=stories, recalled=recalled, diagnostics=sink)

    assert _instruction(model) == _UNDERSTANDING.render(flags={})
    assert {"Recalled memories", "Matters"} <= set(_payload(model).headings())
    (given,) = sink.of(DiagnosticSource.UNDERSTANDING, DiagnosticKind.GIVEN)
    assert given.model_dump(mode="json")["body"]["prompt"]["flags"] == {}


async def test_the_candidates_render_under_s_labels_attributed_by_their_records() -> None:
    model = FakeModelProvider(_proposal())

    await _understand(model, stories=Candidates(views=(_TRIP, _RUNNING)))

    first, second = _matters(model)
    assert (first.label, second.label) == ("S1", "S2")
    summary, owner, outside = first.tags
    assert (summary.name, summary.get("from")) == ("summary", "the system")
    assert summary.text == "A camping trip to Riverside.\nThe park says the lake is closed."
    # ADR-0303 §3:8, ADR-0353 §3:7: marked outside by the record's mark, never its text.
    assert summary.get("outside") == "yes"
    assert (owner.name, owner.get("from"), owner.get("outside")) == ("note", "the owner", None)
    assert (outside.get("from"), outside.get("outside")) == ("the system", "yes")
    # §6:5: a short view's latest episodes take no label; with no meaning, none renders.
    assert 'label="' not in "".join(str(one.attributes) for one in first.tags)
    # A story with nothing written holds nothing.
    assert second.tags == []


async def test_a_withheld_summary_is_said_to_be_withheld_and_nothing_of_it_is_rendered() -> None:
    """ADR-0304 §4:2: the reader is told a summary was withheld, and is shown none of it.

    The reason it is told is its audience's, never what stands behind the summary (§4:3).
    """
    model = FakeModelProvider(_proposal())
    withheld = ShortView(
        story_id="story:withheld",
        lines=(),
        notes=_TRIP.notes,
        episodes=(),
        withheld=True,
    )

    await _understand(model, stories=Candidates(views=(withheld, _RUNNING)))

    first, second = _matters(model)
    summary, *notes = first.tags
    # ADR-0304 §4:2: said to be withheld, and nothing of it, its mark included.
    assert summary.attributes == {"from": "the system", "withheld": "yes"}
    assert summary.text is None
    # The notes are decided on their own (§3:9), and a story with no summary is not withheld.
    assert len(notes) == 2
    assert "withheld" not in str([one.attributes for one in second.tags])


# --- ADR-0305 §4: notes withheld from an audience are absent -----------------------


@pytest.mark.parametrize("notes", [_TRIP.notes, ()], ids=["notes pending", "no note pending"])
async def test_a_view_that_may_not_show_notes_renders_no_notes_part(
    notes: tuple[StoryNote, ...],
) -> None:
    """#2807: no note, no statement that none is waiting, and none that any was withheld.

    Whether the story holds a pending note or none, the part is left out alike, so its
    presence says nothing (ADR-0305 §4). The summary keeps its withheld statement and
    the latest episodes still render (ADR-0304 §4:2).
    """
    model = FakeModelProvider(_proposal())
    hidden = ShortView(
        story_id="story:trip",
        lines=(),
        notes=notes,
        episodes=_TRIP.episodes,
        withheld=True,
        notes_withheld=True,
    )

    await _understand(model, stories=Candidates(views=(hidden,)), audience=UNBOUNDED)

    (view,) = _matters(model)
    assert [one.name for one in view.tags] == ["summary"]
    assert view.tags[0].get("withheld") == "yes"


async def test_a_spoken_pass_with_a_pending_owner_note_is_told_nothing_of_notes() -> None:
    """#2807, composed: the candidates as assembled for an unbounded audience, rendered.

    Owner note #57's shape: pending on the camping story, written by the owner. The
    short view a spoken pass reads renders no notes part; a bounded pass's renders it.
    """
    ids = itertools.count(1)
    stories = FakeStoryStore(now=lambda: AT, new_id=lambda: f"{next(ids)}")
    created = await stories.create((activation("a-1"),), actor=StoryActor.OWNER)
    assert created.story_id is not None
    await stories.append_note(
        created.story_id,
        "Plans changed again: we'll arrive at Riverside on Friday evening after all.",
        author=StoryNoteAuthor.OWNER,
    )
    window = (episode("a-1"),)
    assembler = StoryCandidates(
        stories=stories, memory=await memory_of(*window), limit=5, lines=3, notes=2, episodes=2
    )
    spoken = FakeModelProvider(_proposal())
    bounded = FakeModelProvider(_proposal())

    await _understand(
        spoken,
        stories=await assembler.assemble(window, audience=UNBOUNDED),
        episodes=None,
        audience=UNBOUNDED,
    )
    await _understand(bounded, stories=await assembler.assemble(window, audience=BOUNDED))

    (view,) = _matters(spoken)
    assert [one.name for one in view.tags if one.name == "note"] == []
    assert "Friday evening" not in spoken.calls[0].messages[1].content
    (note,) = [one for one in _matters(bounded)[0].tags if one.name == "note"]
    assert "Friday evening" in (note.text or "")
    # §4: the instruction is the same whether or not the pass may be shown notes.
    assert _instruction(spoken) == _instruction(bounded)


@pytest.mark.parametrize(
    ("candidates", "said"),
    [
        (Candidates(unreadable=True), "It could not be read: the matters could not be read"),
        (Candidates(), "Nothing is shown: no matter is found"),
    ],
)
async def test_a_section_with_no_story_says_why(candidates: Candidates, said: str) -> None:
    model = FakeModelProvider(_proposal())

    await _understand(model, stories=candidates)

    assert _payload(model).section("Matters").startswith(said)


# --- §6:6, §6:7: story labels resolved -------------------------------------------------


async def test_story_labels_resolve_to_stories_and_earlier_activations_in_order_once() -> None:
    model = FakeModelProvider(_proposal(belongs_to=["S2", "P1", "M1", "S2"]))
    recalled = episode("a-7")

    understood = await _understand(
        model,
        stories=Candidates(views=(_TRIP, _RUNNING)),
        episodes=(episode("a-2"),),
        recalled=(recalled,),
    )

    assert understood.story_links == (story("story:running"), activation("a-2"), activation("a-7"))
    assert understood.grounding_dropped == 0
    assert len(model.calls) == 1


# --- §6:8: a defective story label ------------------------------------------------------


@pytest.mark.parametrize("label", ["S3", "M2", "P9", "H9", "trip"])
async def test_a_defective_story_label_is_repaired_once_then_dropped_and_counted(
    label: str,
) -> None:
    bad = _proposal(belongs_to=["S1", label])
    model = FakeModelProvider.scripted(bad, bad)

    understood = await _understand(
        model, stories=Candidates(views=(_TRIP,)), episodes=(episode("a-2"),), recalled=(_FACT,)
    )

    assert len(model.calls) == 2
    statement = model.calls[1].messages[-1].content
    assert "labels in `belongs_to` name no matter and no earlier stimulus" in statement
    assert "S1 (the matters)" in statement
    assert understood.story_links == (story("story:trip"),)
    assert understood.grounding_dropped == 1


async def test_a_repaired_story_label_is_recorded() -> None:
    model = FakeModelProvider.scripted(_proposal(belongs_to=["S9"]), _proposal(belongs_to=["S1"]))

    understood = await _understand(model, stories=Candidates(views=(_TRIP,)))

    assert understood.story_links == (story("story:trip"),)
    assert understood.grounding_dropped == 0


async def test_an_episode_of_no_activation_is_not_a_story_label() -> None:
    legacy = episode("a-2").model_copy(update={"processing_record": None})
    model = FakeModelProvider.scripted(_proposal(belongs_to=["P1"]), _proposal(belongs_to=["P1"]))

    understood = await _understand(model, stories=Candidates(views=()), episodes=(legacy,))

    assert understood.story_links == ()
    assert understood.grounding_dropped == 1


# --- ADR-0305 §3: a remembered fact is never a story link -----------------------------


async def test_a_recalled_fact_named_as_a_story_label_is_dropped_with_no_repair() -> None:
    """#2808: the re-check's reply, ``["S5", "M1", "M2", "M3"]`` with M3 a fact.

    The fact's label links nothing: it is dropped and counted in ``grounding_dropped``,
    and calls for no second completion, so the reply passes with one (ADR-0305 §3).
    """
    model = FakeModelProvider.scripted(_proposal(belongs_to=["S1", "M1", "M2", "M3"]))

    understood = await _understand(
        model,
        stories=Candidates(views=(_TRIP,)),
        recalled=(episode("a-7"), episode("a-8"), _FACT),
    )

    assert len(model.calls) == 1
    assert understood.story_links == (story("story:trip"), activation("a-7"), activation("a-8"))
    assert understood.grounding_dropped == 1


async def test_a_fact_s_label_is_not_named_by_a_repair_another_defect_calls_for() -> None:
    """ADR-0305 §3: the repair statement does not name it, and the second output's is dropped."""
    model = FakeModelProvider.scripted(
        _proposal(belongs_to=["S9", "M1"]), _proposal(belongs_to=["S1", "M1"])
    )

    understood = await _understand(model, stories=Candidates(views=(_TRIP,)), recalled=(_FACT,))

    assert len(model.calls) == 2
    statement = _statement(model)
    assert '"S9"' in statement
    assert '"M1"' not in statement
    assert understood.story_links == (story("story:trip"),)
    assert understood.grounding_dropped == 1


async def test_a_fact_s_label_cited_in_cites_still_resolves_to_its_memory() -> None:
    """ADR-0305 §3 with ADR-0281 §7:5: only its label in ``belongs_to`` links nothing."""
    model = FakeModelProvider.scripted(_proposal(cites=["M1"], belongs_to=["M1"]))

    understood = await _understand(model, stories=Candidates(views=(_TRIP,)), recalled=(_FACT,))

    assert len(model.calls) == 1
    (referent,) = understood.meaning_referents
    assert (referent.kind, referent.id) == ("memory", "fact-1")
    assert understood.story_links == ()
    assert understood.grounding_dropped == 1


async def test_a_recalled_fact_carries_no_mark() -> None:
    """ADR-0353 §18 (ADR-0305 §3:1, §3:3): a recalled fact is rendered with no mark, while
    a label in ``belongs_to`` naming it is still dropped (§9:12)."""
    model = FakeModelProvider(_proposal())

    await _understand(model, stories=Candidates(views=(_TRIP,)), recalled=(episode("a-7"), _FACT))

    assert "linkable" not in _payload(model).content
    assert _payload(model).labelled("Recalled memories") == ["M1", "M2"]


# --- ADR-0304 §8: an S label cited as a referent ---------------------------------------


def _story_referent(story_id: str, excerpt: str) -> UnderstandingReferent:
    return UnderstandingReferent(kind="story", id=story_id, source="story", excerpt=excerpt)


async def test_an_s_label_cited_in_cites_resolves_to_its_story_and_links_nothing() -> None:
    """#2795, ADR-0304 §8:1, §8:2, ADR-0353 §9:4: no label defect, no repair, a `story`
    referent recorded, and no link: only `belongs_to` makes one."""
    model = FakeModelProvider.scripted(
        _proposal(understanding="A change of plan for the Riverside trip.", cites=["S1", "S1"])
    )

    understood = await _understand(model, stories=Candidates(views=(_TRIP, _RUNNING)))

    assert len(model.calls) == 1
    trip = _story_referent("story:trip", "A camping trip to Riverside.")
    assert understood.meaning_referents == (trip,)
    assert understood.grounding_dropped == 0
    assert understood.story_links == ()


async def test_an_s_label_both_linked_and_cited_resolves_each_way() -> None:
    """The same S label names the matter in `belongs_to` and the referent in `cites`."""
    model = FakeModelProvider.scripted(_proposal(belongs_to=["S2"], cites=["S2"]))

    understood = await _understand(model, stories=Candidates(views=(_TRIP, _RUNNING)))

    assert len(model.calls) == 1
    assert understood.story_links == (story("story:running"),)
    # A story with no summary line rendered gives an empty excerpt (§8:1).
    assert understood.meaning_referents == (_story_referent("story:running", ""),)


async def test_a_withheld_summary_gives_a_story_referent_an_empty_excerpt() -> None:
    """ADR-0304 §8:1: the excerpt is what the short view rendered, and it rendered none."""
    withheld = ShortView(
        story_id="story:withheld", lines=_TRIP.lines, notes=(), episodes=(), withheld=True
    )
    model = FakeModelProvider.scripted(_proposal(cites=["S1"]))

    understood = await _understand(model, stories=Candidates(views=(withheld,)))

    assert understood.meaning_referents == (_story_referent("story:withheld", ""),)
    assert "A camping trip" not in model.calls[0].messages[1].content


async def test_a_story_referent_s_excerpt_is_cut_to_the_referent_bound() -> None:
    """ADR-0276 §2:5's bound, on the first line exactly as the short view rendered it."""
    first = "x" * (UNDERSTANDING_REFERENT_EXCERPT_CHARS + 30)
    long = ShortView(
        story_id="story:long",
        lines=(StorySummaryLine(text=first), StorySummaryLine(text="second")),
        notes=(),
        episodes=(),
    )
    model = FakeModelProvider.scripted(_proposal(cites=["S1"]))

    understood = await _understand(model, stories=Candidates(views=(long,)))

    (referent,) = understood.meaning_referents
    assert referent.excerpt == first[:UNDERSTANDING_REFERENT_EXCERPT_CHARS]
    assert (_matters(model)[0].tags[0].text or "").startswith(first)


async def test_an_unrendered_s_label_is_still_a_label_defect() -> None:
    """ADR-0276 §3:4: an S label beyond the stories rendered resolves to nothing."""
    bad = _proposal(cites=["S2"])
    model = FakeModelProvider.scripted(bad, bad)

    understood = await _understand(model, stories=Candidates(views=(_TRIP,)))

    assert len(model.calls) == 2
    assert '"S2"' in _statement(model)
    assert understood.meaning_referents == ()
    assert understood.grounding_dropped == 1


async def test_the_repair_statement_carries_no_rule_on_where_an_s_label_may_be_cited() -> None:
    """ADR-0304 §8:6: a repair another defect calls for says nothing of citing S labels."""
    bad = _proposal(cites=["S1", "P9"])
    model = FakeModelProvider.scripted(bad, bad)

    await _understand(model, stories=Candidates(views=(_TRIP,)))

    statement = _statement(model)
    assert '"P9"' in statement
    assert '"S1"' not in statement
    assert "S1 (the matters)" in statement
    assert "An S label" not in statement
    assert "belongs_to" not in statement


# --- ADR-0301 §1: an H label naming an episode the pass admitted -------------------------


def _statement(model: FakeModelProvider) -> str:
    return model.calls[1].messages[-1].content


async def test_an_h_label_cited_as_a_referent_stays_a_channel_item() -> None:
    model = FakeModelProvider(_proposal(cites=["H1"], belongs_to=["H1"]))

    window = SuppliedWindow(
        ChannelContext(history=(ChannelContextItem(text="Trip plans", item_id=address("a-3")),))
    )
    understood = await _understand(
        model, stories=Candidates(views=()), episodes=(episode("a-3"),), window=window
    )

    # §1's fifth clause: outside `belongs_to` the label resolves as it always did.
    (referent,) = understood.meaning_referents
    assert (referent.kind, referent.id) == ("channel_item", address("a-3"))
    assert understood.story_links == (activation("a-3"),)


async def test_a_one_exchange_supplied_item_links_the_window_episode_s_activation() -> None:
    window = SuppliedWindow(
        ChannelContext(history=(ChannelContextItem(text="Trip plans", item_id=address("a-2")),))
    )
    model = FakeModelProvider(_proposal(belongs_to=["H1"]))

    understood = await _understand(
        model, stories=Candidates(views=()), episodes=(episode("a-2"),), window=window
    )

    (item,) = _payload(model).tags("Stimulus origin knowledge", "message")
    assert item.text == "Trip plans"
    assert _payload(model).containers("Short-term memory") == []
    assert understood.story_links == (activation("a-2"),)
    assert understood.grounding_dropped == 0
    assert len(model.calls) == 1


# --- ADR-0303 §7: an item that links to nothing, and the transcript's links ------------


def _message(
    position: int, text: str, *, author: MessageAuthor = MessageAuthor.USER
) -> TranscriptMessage:
    return TranscriptMessage(
        conversation_id="c-1",
        position=position,
        written_at=AT,
        author=author,
        text=text,
        device_id="phone" if author is MessageAuthor.USER else None,
        message_id=f"m-{position}" if author is MessageAuthor.USER else None,
    )


#: A transcript of three messages: the user's two, which the reader's bookkeeping
#: records as taken in by a-1 and a-2, and the assistant's reply between them, which
#: nothing records the writer of before the phases (§7's closing paragraph).
_TRANSCRIPT: Final = TranscriptWindow(
    CONVERSATION,
    (
        _message(1, "Plan the camping trip to Riverside."),
        _message(2, "Riverside has space.", author=MessageAuthor.ASSISTANT),
        _message(3, "Book the canoe too."),
    ),
    links={1: "a-1", 3: "a-2"},
)


async def test_a_transcript_message_links_the_activation_that_took_it_in() -> None:
    """§7:3, §7:4: the reader's bookkeeping, brought with the window, resolves an H label."""
    model = FakeModelProvider(_proposal(belongs_to=["H3", "H1", "S1"]))

    understood = await _understand(
        model, stories=Candidates(views=(_TRIP,)), episodes=(), window=_TRANSCRIPT
    )

    assert understood.story_links == (activation("a-2"), activation("a-1"), story("story:trip"))
    assert understood.grounding_dropped == 0
    assert len(model.calls) == 1


async def test_an_item_that_links_to_nothing_carries_no_mark() -> None:
    """ADR-0353 §18 (ADR-0303 §7:5, §7:8): no item is marked as not linkable."""
    model = FakeModelProvider(_proposal())

    await _understand(model, stories=Candidates(views=(_TRIP,)), episodes=(), window=_TRANSCRIPT)

    _, reply, _ = _payload(model).tags("Stimulus origin knowledge", "message")
    assert reply.attributes == {
        "label": "H2",
        "from": "the system",
        "at": "Thu 8 Oct 2026, 12:00 pm",
    }
    assert reply.text == "Riverside has space."
    assert "linkable" not in _payload(model).content


async def test_a_story_label_naming_an_unlinkable_item_is_dropped_and_counted_unrepaired() -> None:
    """§7:6: no label defect, so no repair completion; the rest of the links stand."""
    model = FakeModelProvider(_proposal(belongs_to=["H2", "H1"]))

    understood = await _understand(
        model, stories=Candidates(views=()), episodes=(), window=_TRANSCRIPT
    )

    assert len(model.calls) == 1
    assert understood.story_links == (activation("a-1"),)
    assert understood.grounding_dropped == 1


async def test_a_repair_called_for_by_another_defect_does_not_name_an_unlinkable_item() -> None:
    """§7:6: an unlinkable item takes no part in the repair, whatever else calls for one."""
    bad = _proposal(belongs_to=["H2", "S9"])
    model = FakeModelProvider.scripted(bad, bad)

    understood = await _understand(
        model, stories=Candidates(views=(_TRIP,)), episodes=(), window=_TRANSCRIPT
    )

    assert len(model.calls) == 2
    statement = _statement(model)
    assert '"S9"' in statement
    assert '"H2"' not in statement
    assert understood.story_links == ()
    assert understood.grounding_dropped == 2


async def test_a_message_the_bookkeeping_records_no_activation_for_links_to_nothing() -> None:
    """A message no activation is recorded as having taken in is rendered not linkable."""
    model = FakeModelProvider(_proposal(belongs_to=["H1"]))

    understood = await _understand(
        model,
        stories=Candidates(views=(_TRIP,)),
        episodes=(episode("a-2"),),
        window=TranscriptWindow(CONVERSATION, (_message(1, "Plan the camping trip."),)),
    )

    (item,) = _payload(model).tags("Stimulus origin knowledge", "message")
    assert item.get("label") == "H1"
    assert len(model.calls) == 1
    assert understood.story_links == ()
    assert understood.grounding_dropped == 1


async def test_a_supplied_item_naming_an_episode_the_window_does_not_hold_links_nothing() -> None:
    # The item's id is a stored episode's id, but the episode window does not hold that
    # episode: a supplied identifier establishes nothing, and nothing is fetched for it
    # (ADR-0301 §1:1, §1:4). It is rendered not linkable, and naming it is dropped quietly.
    window = SuppliedWindow(
        ChannelContext(history=(ChannelContextItem(text="Trip plans", item_id=address("a-9")),))
    )
    model = FakeModelProvider(_proposal(belongs_to=["H1"]))

    understood = await _understand(
        model, stories=Candidates(views=()), episodes=(episode("a-2"),), window=window
    )

    (item,) = _payload(model).tags("Stimulus origin knowledge")
    assert item.name == "message"
    assert len(model.calls) == 1
    assert understood.story_links == ()
    assert understood.grounding_dropped == 1


async def test_a_linkable_item_carries_no_mark() -> None:
    model = FakeModelProvider(_proposal())

    window = SuppliedWindow(
        ChannelContext(history=(ChannelContextItem(text="Trip plans", item_id=address("a-2")),))
    )
    await _understand(
        model, stories=Candidates(views=()), episodes=(episode("a-2"),), window=window
    )

    assert "linkable" not in _payload(model).content


# --- ADR-0303 §7:9: the place window's links, newest item first -------------------------


def test_a_transcript_s_links_are_newest_message_first_each_activation_once() -> None:
    # Positions 1 and 2 were taken in together by a-1, as one input (ADR-0293 §6:3); the
    # message replied to is shown after the recent ones but is older than position 4.
    window = TranscriptWindow(
        CONVERSATION,
        (
            _message(1, "Plan the camping trip."),
            _message(2, "To Riverside."),
            _message(4, "Riverside has space.", author=MessageAuthor.ASSISTANT),
            _message(5, "Book the canoe."),
        ),
        replied_to=(_message(3, "Which weekend?"),),
        links={1: "a-1", 2: "a-1", 3: "a-2", 5: "a-3"},
    )

    assert place_window_links(window, audience=BOUNDED, episodes=()) == ("a-3", "a-2", "a-1")


def test_a_supplied_item_links_only_as_one_exchange_with_the_episode_window() -> None:
    window = SuppliedWindow(
        ChannelContext(
            history=(
                ChannelContextItem(text="Trip plans", item_id=address("a-2")),
                ChannelContextItem(text="Other plans", item_id=address("a-9")),
            )
        )
    )

    assert place_window_links(window, audience=BOUNDED, episodes=(episode("a-2"),)) == ("a-2",)
    assert place_window_links(window, audience=BOUNDED, episodes=None) == ()
