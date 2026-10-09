"""ADR-0300 §6:5-§6:9: the understanding stage renders the candidate stories and links them.

The stage alone, over a scripted model and hand-built short views: the fourth section,
its ``S`` labels and the instruction (§6:5, §6:9), ``story_labels`` resolved into
``story_links`` (§6:6, §6:7), and a defective story label repaired once and then
dropped and counted (§6:8). An ``H`` label naming a place-window item that links to an
activation resolves to it, as a ``P`` label naming that activation's episode would, and
one naming an item that links to nothing is rendered not linkable and is dropped and
counted with no repair (ADR-0303 §7, ADR-0301 §1:1). An ``S`` label cited in
``meaning_labels``, a reference or a relationship resolves to a ``story`` referent with
no repair, and links nothing (ADR-0304 §8). A recalled fact named as a story label is
dropped and counted with no repair, and a pass that may not be shown a note is told
nothing about notes (ADR-0305). Which candidates are assembled is
``test_story_links.py``'s.
"""

from __future__ import annotations

import asyncio
import itertools
import json
from datetime import timedelta
from typing import TYPE_CHECKING, Any, Final

import pytest
from story_support import (
    AT,
    CONVERSATION,
    EVENTS,
    OWNER_ONLY,
    activation,
    address,
    episode,
    memory_of,
    story,
)

from ai_assistant.core.types import (
    UNDERSTANDING_REFERENT_EXCERPT_CHARS,
    ActivationRecall,
    BeliefBand,
    ChannelContext,
    ChannelContextItem,
    MemoryKind,
    MemorySource,
    MessageAuthor,
    Provenance,
    RecallCue,
    RecalledItem,
    RecallOutcome,
    RecallProvenance,
    SemanticMemory,
    StoryActor,
    StoryNote,
    StoryNoteAuthor,
    StorySummaryLine,
    TranscriptMessage,
    UnderstandingGround,
    UnderstandingReferent,
)
from ai_assistant.orchestration.disclosure import BoundedAudienceSupply, UnboundedAudienceSupply
from ai_assistant.orchestration.story_links import Candidates, ShortView, StoryCandidates
from ai_assistant.orchestration.understanding import (
    ConversationWindow,
    SuppliedWindow,
    TranscriptWindow,
    UnderstandingStage,
    place_window_links,
)
from ai_assistant.testing import FakeModelProvider, FakeStoryStore

if TYPE_CHECKING:
    from ai_assistant.core.types import ActivationUnderstanding, EpisodicMemory
    from ai_assistant.orchestration.disclosure import TurnSupply
    from ai_assistant.orchestration.understanding import ChannelWindow

BOUNDED: Final = BoundedAudienceSupply(speakable_attested_sources=frozenset())
UNBOUNDED: Final = UnboundedAudienceSupply(speakable_attested_sources=frozenset())
WINDOW: Final = SuppliedWindow(
    ChannelContext(history=(ChannelContextItem(text="Trip plans", item_id="item-1"),))
)


def _proposal(**fields: Any) -> str:
    return json.dumps({"meaning": "The canoe is booked.", "meaning_ground": "stated"} | fields)


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
    recalled: tuple[EpisodicMemory | SemanticMemory, ...] = (),
    window: ChannelWindow = WINDOW,
    audience: TurnSupply = BOUNDED,
) -> ActivationUnderstanding:
    recall = None
    if recalled:
        recall = ActivationRecall(
            outcome=RecallOutcome.FOUND,
            cues=(RecallCue.ACTIVATION_INPUT,),
            items=tuple(_item(record.id, MemoryKind(record.kind)) for record in recalled),
        )
    return await UnderstandingStage(model=model, excerpt_chars=2000).understand(
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


_FACT: Final = SemanticMemory(
    id="fact-1",
    content="The canoe holds two.",
    fact="The canoe holds two.",
    provenance=Provenance(source=MemorySource.OBSERVED, confidence=0.9, last_updated=AT),
)


def _payload(model: FakeModelProvider, call: int = 0) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(model.calls[call].messages[1].content)
    return loaded


def _instruction(model: FakeModelProvider) -> str:
    return model.calls[0].messages[0].content


# --- §6:5, §6:9: the fourth section and its instruction ------------------------------


async def test_no_candidates_render_no_section_and_leave_the_instruction_alone() -> None:
    model = FakeModelProvider(_proposal())

    understood = await _understand(model, stories=None)

    assert "stories" not in _payload(model)
    assert "story_labels" not in _instruction(model)
    assert "S1" not in _instruction(model)
    assert understood.story_links == ()


async def test_the_candidates_render_under_s_labels_attributed_by_their_records() -> None:
    model = FakeModelProvider(_proposal())

    await _understand(model, stories=Candidates(views=(_TRIP, _RUNNING)))

    first, second = _payload(model)["stories"]
    assert (first["label"], second["label"]) == ("S1", "S2")
    assert [line["text"] for line in first["summary"]] == [
        "A camping trip to Riverside.",
        "The park says the lake is closed.",
    ]
    # ADR-0303 §3:8: a marked summary or note is shown as outside content, never as the
    # user's words; a line carries no mark of its own (§2:7).
    assert all("outside_content" not in line for line in first["summary"])
    assert "never something the user said" in first["summary_outside_content"]
    assert "summary_outside_content" not in second
    owner, outside = first["newest_notes"]
    assert owner["written_by"] == "the user, writing on this story directly"
    assert "outside_content" not in owner
    assert "never something the user said" in outside["outside_content"]
    # §6:5: the episodes inside a short view take no label.
    (shown,) = first["latest_episodes"]
    assert "label" not in shown
    assert shown["input"] == "Book the canoe for Sunday."
    assert second["summary"].startswith("missing:")
    assert second["newest_notes"].startswith("missing:")
    assert second["latest_episodes"].startswith("missing:")


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

    first, second = _payload(model)["stories"]
    assert first["summary"].startswith("missing:")
    assert "withheld" in first["summary"]
    assert "this audience may not be shown it" in first["summary"]
    assert "behind" not in first["summary"]
    assert "summary_outside_content" not in first
    # The notes are decided on their own (§3:9), and a story with no summary is not withheld.
    assert len(first["newest_notes"]) == 2
    assert "withheld" not in second["summary"]


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

    (view,) = _payload(model)["stories"]
    assert "newest_notes" not in view
    assert "note" not in json.dumps(view)
    assert "this audience may not be shown it" in view["summary"]
    assert len(view["latest_episodes"]) == 1


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

    (view,) = _payload(spoken)["stories"]
    assert "newest_notes" not in view
    assert "Friday evening" not in spoken.calls[0].messages[1].content
    (note,) = _payload(bounded)["stories"][0]["newest_notes"]
    assert "Friday evening" in note["text"]
    # §4: the instruction is the same whether or not the pass may be shown notes.
    assert _instruction(spoken) == _instruction(bounded)
    assert "withheld" not in _instruction(spoken)


async def test_the_instruction_states_what_a_link_says_and_asks_for_story_labels() -> None:
    model = FakeModelProvider(_proposal())

    await _understand(model, stories=Candidates(views=(_TRIP,)))

    instruction = _instruction(model)
    # §6:9's three statements.
    assert "A link says the input belongs to that matter and nothing more." in instruction
    assert "One input may belong to several matters." in instruction
    assert "An input that belongs to none is linked to none" in instruction
    assert '"story_labels"' in instruction


async def test_the_instruction_says_where_an_s_label_may_be_cited_and_what_a_story_is() -> None:
    """ADR-0304 §8:5: the instruction's three statements, and #2776's rule gone."""
    model = FakeModelProvider(_proposal())

    await _understand(model, stories=Candidates(views=(_TRIP,)))

    instruction = _instruction(model)
    assert "An S label may be cited wherever a label may" in instruction
    assert "Citing an S label outside `story_labels` links nothing" in instruction
    assert (
        "A story's summary and notes are the assistant's own record of the matter, "
        "provisional and possibly out of date." in instruction
    )
    assert "A reading an S label supports is `supplied`, as for any label." in instruction
    assert "is cited in `story_labels` alone" not in instruction
    assert "Never cite one" not in instruction
    assert "story supports is `inferred`" not in instruction
    # The T1 rename's join left "folded into thesummary"; the paragraph reads whole.
    assert "folded into the summary" in instruction


@pytest.mark.parametrize(
    ("candidates", "said"),
    [
        (Candidates(unreadable=True), "the stories could not be read"),
        (Candidates(), "belongs to a story"),
    ],
)
async def test_a_section_with_no_story_says_why(candidates: Candidates, said: str) -> None:
    model = FakeModelProvider(_proposal())

    await _understand(model, stories=candidates)

    section = _payload(model)["stories"]
    assert isinstance(section, str)
    assert section.startswith("missing:")
    assert said in section


# --- §6:6, §6:7: story labels resolved -------------------------------------------------


async def test_story_labels_resolve_to_stories_and_earlier_activations_in_order_once() -> None:
    model = FakeModelProvider(_proposal(story_labels=["S2", "P1", "M1", "S2"]))
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
    bad = _proposal(story_labels=["S1", label])
    model = FakeModelProvider.scripted(bad, bad)

    understood = await _understand(
        model, stories=Candidates(views=(_TRIP,)), episodes=(episode("a-2"),), recalled=(_FACT,)
    )

    assert len(model.calls) == 2
    statement = model.calls[1].messages[-1].content
    assert "story labels name no story and no earlier episode" in statement
    assert "S1 (the stories section)" in statement
    assert understood.story_links == (story("story:trip"),)
    assert understood.grounding_dropped == 1


async def test_a_repaired_story_label_is_recorded() -> None:
    model = FakeModelProvider.scripted(
        _proposal(story_labels=["S9"]), _proposal(story_labels=["S1"])
    )

    understood = await _understand(model, stories=Candidates(views=(_TRIP,)))

    assert understood.story_links == (story("story:trip"),)
    assert understood.grounding_dropped == 0


async def test_an_episode_of_no_activation_is_not_a_story_label() -> None:
    legacy = episode("a-2").model_copy(update={"processing_record": None})
    model = FakeModelProvider.scripted(
        _proposal(story_labels=["P1"]), _proposal(story_labels=["P1"])
    )

    understood = await _understand(model, stories=Candidates(views=()), episodes=(legacy,))

    assert understood.story_links == ()
    assert understood.grounding_dropped == 1


# --- ADR-0305 §3: a remembered fact is never a story link -----------------------------


async def test_a_recalled_fact_named_as_a_story_label_is_dropped_with_no_repair() -> None:
    """#2808: the re-check's reply, ``["S5", "M1", "M2", "M3"]`` with M3 a fact.

    The fact's label links nothing: it is dropped and counted in ``grounding_dropped``,
    and calls for no second completion, so the reply passes with one (ADR-0305 §3).
    """
    model = FakeModelProvider.scripted(_proposal(story_labels=["S1", "M1", "M2", "M3"]))

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
        _proposal(story_labels=["S9", "M1"]), _proposal(story_labels=["S1", "M1"])
    )

    understood = await _understand(model, stories=Candidates(views=(_TRIP,)), recalled=(_FACT,))

    assert len(model.calls) == 2
    statement = _statement(model)
    assert '"S9"' in statement
    assert '"M1"' not in statement
    assert understood.story_links == (story("story:trip"),)
    assert understood.grounding_dropped == 1


async def test_a_fact_s_label_cited_outside_story_labels_still_resolves_to_its_memory() -> None:
    """ADR-0305 §3 with ADR-0281 §7:5: only its story label links nothing."""
    model = FakeModelProvider.scripted(
        _proposal(meaning_ground="supplied", meaning_labels=["M1"], story_labels=["M1"])
    )

    understood = await _understand(model, stories=Candidates(views=(_TRIP,)), recalled=(_FACT,))

    assert len(model.calls) == 1
    (referent,) = understood.meaning_referents
    assert (referent.kind, referent.id) == ("memory", "fact-1")
    assert understood.meaning_ground is UnderstandingGround.SUPPLIED
    assert understood.story_links == ()
    assert understood.grounding_dropped == 1


async def test_a_recalled_fact_is_marked_not_linkable_and_the_instruction_says_why() -> None:
    """ADR-0305 §3: the place window's mark, and the stories paragraph's sentence."""
    model = FakeModelProvider(_proposal())

    await _understand(model, stories=Candidates(views=(_TRIP,)), recalled=(episode("a-7"), _FACT))

    shown_episode, shown_fact = _payload(model)["recalled"]
    assert shown_fact["not_linkable"] is True
    assert "not_linkable" not in shown_episode
    assert (
        "A remembered fact is never a story link: its M label is marked `not_linkable` and "
        "links nothing in `story_labels`." in _instruction(model)
    )


# --- ADR-0304 §8: an S label cited as a referent ---------------------------------------


def _story_referent(story_id: str, excerpt: str) -> UnderstandingReferent:
    return UnderstandingReferent(kind="story", id=story_id, source="story", excerpt=excerpt)


#: An S label cited outside `story_labels`, in each field that takes labels (ADR-0304 §8:1).
_S_OUTSIDE_STORY_LABELS: Final[dict[str, dict[str, Any]]] = {
    "meaning": {"meaning_ground": "supplied", "meaning_labels": ["S1"]},
    "reference": {"references": [{"phrase": "Riverside", "labels": ["S1"]}]},
    "relationship": {
        "relationships": [
            {
                "statement": "It changes the plan for the trip.",
                "labels": ["S1"],
                "ground": "supplied",
            }
        ]
    },
}


@pytest.mark.parametrize("field", list(_S_OUTSIDE_STORY_LABELS))
async def test_an_s_label_cited_as_a_referent_resolves_to_its_story(field: str) -> None:
    """ADR-0304 §8:1, §8:4: no label defect, no repair, and a `story` referent recorded."""
    model = FakeModelProvider.scripted(_proposal(**_S_OUTSIDE_STORY_LABELS[field]))

    understood = await _understand(model, stories=Candidates(views=(_TRIP,)))

    assert len(model.calls) == 1
    assert understood.grounding_dropped == 0
    trip = _story_referent("story:trip", "A camping trip to Riverside.")
    cited = (
        understood.meaning_referents
        + tuple(one for reference in understood.references for one in reference.referents)
        + tuple(one for relation in understood.relationships for one in relation.referents)
    )
    assert cited == (trip,)


async def test_a_reply_citing_s1_everywhere_passes_with_one_completion() -> None:
    """#2795: a reply citing S1 in a reference, a relationship and its meaning is not repaired.

    Fourteen of thirty-nine passes on #2792's hub paid the repair completion because the
    model cited an S label there. Each resolves to the story; the readings it supports
    stay `supplied` (§8:3); and none of it links the input to the story (§8:2).
    """
    model = FakeModelProvider.scripted(
        _proposal(
            meaning="A change of plan for the Riverside trip.",
            meaning_ground="supplied",
            meaning_labels=["S1"],
            references=[{"phrase": "Riverside", "labels": ["S1"]}],
            relationships=[
                {"statement": "It changes the trip's plan.", "labels": ["S1"], "ground": "supplied"}
            ],
        )
    )

    understood = await _understand(model, stories=Candidates(views=(_TRIP, _RUNNING)))

    assert len(model.calls) == 1
    trip = _story_referent("story:trip", "A camping trip to Riverside.")
    assert understood.meaning_ground is UnderstandingGround.SUPPLIED
    assert understood.meaning_referents == (trip,)
    (reference,) = understood.references
    assert reference.referents == (trip,)
    (relationship,) = understood.relationships
    assert relationship.referents == (trip,)
    assert relationship.ground is UnderstandingGround.SUPPLIED
    assert understood.grounding_dropped == 0
    # §8:2: a link is made only by `story_labels`.
    assert understood.story_links == ()


async def test_an_s_label_both_linked_and_cited_resolves_each_way() -> None:
    """The same S label names the matter in `story_labels` and the referent elsewhere."""
    model = FakeModelProvider.scripted(
        _proposal(
            story_labels=["S2"],
            references=[{"phrase": "the run", "labels": ["S2"]}],
        )
    )

    understood = await _understand(model, stories=Candidates(views=(_TRIP, _RUNNING)))

    assert len(model.calls) == 1
    assert understood.story_links == (story("story:running"),)
    (reference,) = understood.references
    # A story with no summary line rendered gives an empty excerpt (§8:1).
    assert reference.referents == (_story_referent("story:running", ""),)


async def test_a_withheld_summary_gives_a_story_referent_an_empty_excerpt() -> None:
    """ADR-0304 §8:1: the excerpt is what the short view rendered, and it rendered none."""
    withheld = ShortView(
        story_id="story:withheld", lines=_TRIP.lines, notes=(), episodes=(), withheld=True
    )
    model = FakeModelProvider.scripted(
        _proposal(references=[{"phrase": "the trip", "labels": ["S1"]}])
    )

    understood = await _understand(model, stories=Candidates(views=(withheld,)))

    (reference,) = understood.references
    assert reference.referents == (_story_referent("story:withheld", ""),)
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
    model = FakeModelProvider.scripted(_proposal(meaning_labels=["S1"]))

    understood = await _understand(model, stories=Candidates(views=(long,)))

    (referent,) = understood.meaning_referents
    assert referent.excerpt == first[:UNDERSTANDING_REFERENT_EXCERPT_CHARS]
    assert _payload(model)["stories"][0]["summary"][0]["text"] == first


async def test_an_unrendered_s_label_is_still_a_label_defect() -> None:
    """ADR-0276 §3:4: an S label beyond the stories rendered resolves to nothing."""
    bad = _proposal(references=[{"phrase": "the trip", "labels": ["S2"]}])
    model = FakeModelProvider.scripted(bad, bad)

    understood = await _understand(model, stories=Candidates(views=(_TRIP,)))

    assert len(model.calls) == 2
    assert '"S2"' in _statement(model)
    assert understood.references[0].referents == ()
    assert understood.grounding_dropped == 1


async def test_the_repair_statement_carries_no_rule_on_where_an_s_label_may_be_cited() -> None:
    """ADR-0304 §8:6: a repair another defect calls for says nothing of citing S labels."""
    bad = _proposal(meaning_labels=["S1", "P9"])
    model = FakeModelProvider.scripted(bad, bad)

    await _understand(model, stories=Candidates(views=(_TRIP,)))

    statement = _statement(model)
    assert '"P9"' in statement
    assert '"S1"' not in statement
    assert "S1 (the stories section)" in statement
    assert "An S label" not in statement
    assert "story_labels" not in statement


# --- ADR-0301 §1: an H label naming a stored episode the pass admitted ------------------


def _tail(*records: EpisodicMemory) -> ConversationWindow:
    return ConversationWindow(CONVERSATION, records)


def _statement(model: FakeModelProvider) -> str:
    return model.calls[1].messages[-1].content


@pytest.mark.parametrize(
    "episodes",
    [None, ()],
    ids=["a spoken turn, which takes no episode window", "beyond the selector's reach"],
)
async def test_a_tail_record_links_its_activation_through_its_h_label(
    episodes: tuple[EpisodicMemory, ...] | None,
) -> None:
    model = FakeModelProvider(_proposal(story_labels=["H2", "S1", "H1", "H2"]))

    understood = await _understand(
        model,
        stories=Candidates(views=(_TRIP,)),
        episodes=episodes,
        window=_tail(episode("a-3"), episode("a-4")),
    )

    first, second = _payload(model)["channel_window"]
    assert (first["label"], second["label"]) == ("H1", "H2")
    assert "also_in_episode_window" not in first
    assert understood.story_links == (activation("a-4"), story("story:trip"), activation("a-3"))
    assert understood.grounding_dropped == 0
    assert len(model.calls) == 1


async def test_an_h_label_cited_as_a_referent_stays_a_channel_item() -> None:
    model = FakeModelProvider(
        _proposal(meaning_ground="supplied", meaning_labels=["H1"], story_labels=["H1"])
    )

    understood = await _understand(
        model, stories=Candidates(views=()), episodes=None, window=_tail(episode("a-3"))
    )

    # §1's fifth clause: outside `story_labels` the label resolves as it always did.
    (referent,) = understood.meaning_referents
    assert (referent.kind, referent.id) == ("channel_item", address("a-3"))
    assert understood.story_links == (activation("a-3"),)


async def test_a_tail_record_also_in_the_episode_window_links_once_under_h() -> None:
    model = FakeModelProvider(_proposal(story_labels=["H1"]))

    understood = await _understand(
        model,
        stories=Candidates(views=()),
        episodes=(episode("a-3"),),
        window=_tail(episode("a-3")),
    )

    (item,) = _payload(model)["channel_window"]
    assert item["also_in_episode_window"] is True
    assert understood.story_links == (activation("a-3"),)
    assert len(model.calls) == 1


async def test_a_one_exchange_supplied_item_links_the_window_episode_s_activation() -> None:
    window = SuppliedWindow(
        ChannelContext(history=(ChannelContextItem(text="Trip plans", item_id=address("a-2")),))
    )
    model = FakeModelProvider(_proposal(story_labels=["H1"]))

    understood = await _understand(
        model, stories=Candidates(views=()), episodes=(episode("a-2"),), window=window
    )

    (item,) = _payload(model)["channel_window"]
    assert item["also_in_episode_window"] is True
    assert _payload(model)["episode_window"].startswith("missing")
    assert understood.story_links == (activation("a-2"),)
    assert understood.grounding_dropped == 0
    assert len(model.calls) == 1


async def test_a_withheld_tail_record_takes_no_label_to_cite() -> None:
    bad = _proposal(story_labels=["H1", "H2"])
    model = FakeModelProvider.scripted(bad, bad)

    understood = await _understand(
        model,
        stories=Candidates(views=()),
        episodes=None,
        window=_tail(episode("a-3", placement=OWNER_ONLY), episode("a-4")),
        audience=UNBOUNDED,
    )

    # ADR-0276 §4:9: on a turn of unbounded audience the owner-placed record reaches no
    # rendering and no label, so the one H label is the record that was admitted.
    (item,) = _payload(model)["channel_window"]
    assert item["label"] == "H1"
    assert '"H2"' in _statement(model)
    assert understood.story_links == (activation("a-4"),)
    assert understood.grounding_dropped == 1


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
    model = FakeModelProvider(_proposal(story_labels=["H3", "H1", "S1"]))

    understood = await _understand(
        model, stories=Candidates(views=(_TRIP,)), episodes=(), window=_TRANSCRIPT
    )

    assert understood.story_links == (activation("a-2"), activation("a-1"), story("story:trip"))
    assert understood.grounding_dropped == 0
    assert len(model.calls) == 1


async def test_an_item_that_links_to_nothing_is_rendered_not_linkable() -> None:
    """§7:5: the assistant's message carries the mark; nothing else of the window changes."""
    model = FakeModelProvider(_proposal())

    await _understand(model, stories=Candidates(views=(_TRIP,)), episodes=(), window=_TRANSCRIPT)

    first, reply, second = _payload(model)["channel_window"]
    assert reply["not_linkable"] is True
    assert "not_linkable" not in first
    assert "not_linkable" not in second
    # The rest of the item is rendered as it was before the mark (§7: "changes no
    # rendering of it but the mark below").
    assert {key: value for key, value in reply.items() if key != "not_linkable"} == {
        "label": "H2",
        "item": "a recent message of this conversation",
        "position": 2,
        "author": "the assistant",
        "written_at": AT.isoformat(),
        "text": "Riverside has space.",
    }


async def test_a_story_label_naming_an_unlinkable_item_is_dropped_and_counted_unrepaired() -> None:
    """§7:6: no label defect, so no repair completion; the rest of the links stand."""
    model = FakeModelProvider(_proposal(story_labels=["H2", "H1"]))

    understood = await _understand(
        model, stories=Candidates(views=()), episodes=(), window=_TRANSCRIPT
    )

    assert len(model.calls) == 1
    assert understood.story_links == (activation("a-1"),)
    assert understood.grounding_dropped == 1


async def test_a_repair_called_for_by_another_defect_does_not_name_an_unlinkable_item() -> None:
    """§7:6: an unlinkable item takes no part in the repair, whatever else calls for one."""
    bad = _proposal(story_labels=["H2", "S9"])
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
    model = FakeModelProvider(_proposal(story_labels=["H1"]))

    understood = await _understand(
        model,
        stories=Candidates(views=(_TRIP,)),
        episodes=(episode("a-2"),),
        window=TranscriptWindow(CONVERSATION, (_message(1, "Plan the camping trip."),)),
    )

    (item,) = _payload(model)["channel_window"]
    assert item["not_linkable"] is True
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
    model = FakeModelProvider(_proposal(story_labels=["H1"]))

    understood = await _understand(
        model, stories=Candidates(views=()), episodes=(episode("a-2"),), window=window
    )

    (item,) = _payload(model)["channel_window"]
    assert "also_in_episode_window" not in item
    assert item["not_linkable"] is True
    assert len(model.calls) == 1
    assert understood.story_links == ()
    assert understood.grounding_dropped == 1


async def test_a_tail_record_of_no_activation_links_nothing() -> None:
    legacy = episode("a-3").model_copy(update={"processing_record": None})
    model = FakeModelProvider(_proposal(story_labels=["H1"]))

    understood = await _understand(
        model, stories=Candidates(views=()), episodes=None, window=_tail(legacy)
    )

    (item,) = _payload(model)["channel_window"]
    assert item["not_linkable"] is True
    assert len(model.calls) == 1
    assert understood.story_links == ()
    assert understood.grounding_dropped == 1


async def test_a_linkable_item_carries_no_mark() -> None:
    model = FakeModelProvider(_proposal())

    await _understand(
        model,
        stories=Candidates(views=()),
        episodes=(episode("a-2"),),
        window=_tail(episode("a-2"), episode("a-3")),
    )

    assert all("not_linkable" not in item for item in _payload(model)["channel_window"])


async def test_the_instruction_says_any_item_not_marked_not_linkable_may_be_named() -> None:
    """§7:8, in the instruction the first completion is given."""
    model = FakeModelProvider(_proposal())

    await _understand(model, stories=Candidates(views=(_TRIP,)))

    instruction = _instruction(model)
    assert (
        "Any H label may be named in `story_labels` except one whose item is marked "
        "`not_linkable`, which links nothing." in instruction
    )
    assert "No other H label may be named" not in instruction


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


def test_a_tail_s_links_are_newest_episode_first_and_a_withheld_record_brings_none() -> None:
    window = _tail(
        episode("a-3", at=AT - timedelta(hours=2)),
        episode("a-4", at=AT - timedelta(hours=1), placement=OWNER_ONLY),
        episode("a-5", at=AT),
    )

    assert place_window_links(window, audience=BOUNDED, episodes=None) == ("a-5", "a-4", "a-3")
    # ADR-0276 §4:9: on a turn of unbounded audience the owner-placed record reaches no
    # rendering and no label, so it brings no candidate either.
    assert place_window_links(window, audience=UNBOUNDED, episodes=None) == ("a-5", "a-3")


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
