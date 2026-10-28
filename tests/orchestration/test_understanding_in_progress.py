"""ADR-0349 §5, §7:7, §10:1-§10:2: understanding reads taken-in input and running work.

The stage alone, over a scripted model: an input a merge brought renders with the input,
each kept apart and dated and marked as taken over (§7:7); the in-progress section
renders each entry exactly as §5:6 has it, under ``R`` labels, with how many more run
(§5:7, §5:10); the reply's ``meant_for`` is a list, each label resolving to its
activation's id, once and in order, into ``continues`` (ADR-0353 §10:4); a label there
naming no shown activation is dropped and counted with no repair (§9:11); and an ``R``
label is citable anywhere, in ``cites`` as a ``running`` referent and in ``belongs_to``
as an activation member the story-links stage links (§10:1-§10:3). What the engine shows
the stage is ``test_matters``'s and ``test_phases_matters``'s.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Final

import pytest
from understanding_support import Rendered, TextAsStructured

from ai_assistant.core.reply_shapes import read_reply
from ai_assistant.core.types import (
    OWNER_PERSON_ID,
    UNDERSTANDING_REFERENT_EXCERPT_CHARS,
    ChannelContext,
    ChannelIdentity,
    InputOrigin,
    JoinedInput,
    ProposedActivationUnderstanding,
    RecordedInputMessage,
    ReplyFailure,
    StoryActor,
    StoryMember,
    StoryMemberKind,
    SupportHolder,
    UnderstandingReferent,
)
from ai_assistant.orchestration.disclosure import BoundedAudienceSupply
from ai_assistant.orchestration.matters import InProgressEntry
from ai_assistant.orchestration.story_links import StoryLinksStage
from ai_assistant.orchestration.understanding import (
    UNDERSTANDING_PROMPT,
    SuppliedWindow,
    UnderstandingStage,
)
from ai_assistant.testing import FakeModelProvider, FakeStoryStore, default_prompt

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.core.types import ActivationUnderstanding

_AT: Final = datetime(2026, 10, 21, 9, tzinfo=UTC)
_HERE: Final = ChannelIdentity(channel_type="conversation", instance_id="c-here")
_THERE: Final = ChannelIdentity(channel_type="telegram", instance_id="line:42")
_RIVERSIDE: Final = "0b8f8f0e-2a5c-4c55-9a6c-6a2c1f0b0d11"
_SATURDAY: Final = "1c9a9f1f-3b6d-4d66-8b7d-7b3d2a1c1e22"
_WEATHER: Final = "2d0b0a2a-4c7e-4e77-9c8e-8c4e3b2d2f33"
#: The activation whose understanding these cases record.
_HOLDER: Final = "3e1c1b3b-5d8f-4f88-8d9f-9d5f4c3e3a44"


def _proposal(**fields: Any) -> str:
    return json.dumps({"understanding": "Book Riverside for Saturday."} | fields)


def _message(text: str, *, seconds: int = 0, position: int | None = None) -> RecordedInputMessage:
    return RecordedInputMessage(
        text=text,
        sent_at=_AT + timedelta(seconds=seconds),
        position=position,
        party=SupportHolder.person(OWNER_PERSON_ID),
    )


def _entry(
    activation_id: str,
    text: str | None,
    *,
    acted: bool = False,
    origin: InputOrigin = InputOrigin.USER,
) -> InProgressEntry:
    return InProgressEntry(
        activation_id=activation_id, channel=_THERE, input=text, acted=acted, origin=origin
    )


async def _understand(
    model: FakeModelProvider,
    *,
    joined: Sequence[JoinedInput] = (),
    running: Sequence[InProgressEntry] | None = None,
    more: int = 0,
) -> ActivationUnderstanding:
    stage = UnderstandingStage(
        model=TextAsStructured(model),
        excerpt_chars=2000,
        prompt=default_prompt(UNDERSTANDING_PROMPT),
    )
    return await stage.understand(
        "book Riverside",
        channel=_HERE,
        window=SuppliedWindow(ChannelContext()),
        audience=BoundedAudienceSupply(speakable_attested_sources=frozenset()),
        episodes=None,
        version=2,
        now=lambda: _AT,
        deadline=asyncio.get_running_loop().time() + 60,
        joined=joined,
        running=running,
        running_more=more,
    )


def _payload(model: FakeModelProvider, call: int = 0) -> Rendered:
    return Rendered(model.calls[call].messages[1].content)


def _parsed(reply: str) -> ProposedActivationUnderstanding | None:
    """A reply read as the stage reads it: ``core``'s one rule with its shape (ADR-0354 §3:4)."""
    read = read_reply(ProposedActivationUnderstanding, reply)
    return None if isinstance(read, ReplyFailure) else read


# --- §7:7: the activation's whole input --------------------------------------------


async def test_each_taken_in_input_renders_with_the_input_apart_and_dated() -> None:
    model = FakeModelProvider(_proposal())
    joined = (
        JoinedInput(
            joined_at=_AT + timedelta(seconds=9),
            channel=_THERE,
            messages=(_message("for four", seconds=8, position=7),),
            taken_over_from=_SATURDAY,
        ),
    )

    await _understand(model, joined=joined)

    stimulus = _payload(model).section("The stimulus")
    trigger, taken = stimulus.split("\n\n")
    assert trigger.endswith('<said from="the owner">book Riverside</said>')
    # ADR-0353 §2:2, §7:1: the joined input after the trigger's, with its own framing
    # sentence, its time and origin, and that it was taken in from work that was stopped.
    assert taken.startswith(
        "A stimulus reached the system at 9:00 am on Wednesday 21 October 2026: a message "
        "the owner typed on Telegram, taken in from other work, which was stopped. It "
        "contains this text:"
    )
    assert taken.endswith("for four</said>")
    # The activation a merge stopped is never named to the model: it is no label.
    assert _SATURDAY not in stimulus


async def test_an_input_nothing_was_taken_into_renders_as_before() -> None:
    model = FakeModelProvider(_proposal())
    await _understand(model)
    assert "\n\n" not in _payload(model).section("The stimulus")
    # ADR-0353 §8:1: the section is always rendered, and says why it is empty.
    assert _payload(model).section("Concurrent stimuli").startswith("Nothing is shown")


# --- §5:6-§5:10: the in-progress section -------------------------------------------


async def test_each_entry_shows_exactly_what_caused_it_its_input_and_whether_it_acted() -> None:
    """§5:6: a label, its channel and place, its input in brief, and whether it acted."""
    model = FakeModelProvider(_proposal(meant_for=["R2"]))
    running = (
        _entry(_RIVERSIDE, "book Riverside", acted=True),
        _entry(_SATURDAY, "on Saturday"),
    )

    understood = await _understand(model, running=running)

    section = _payload(model).concurrent()
    assert section == [
        {"label": "R1", "origin": "Telegram", "acted": "yes", "input": "book Riverside"},
        {"label": "R2", "origin": "Telegram", "acted": "no", "input": "on Saturday"},
    ]
    # No id reaches the model: a label resolves to it here.
    assert _SATURDAY not in model.calls[0].messages[1].content
    assert understood.continues == (_SATURDAY,)
    assert understood.grounding_dropped == 0
    assert len(model.calls) == 1
    # The instruction says what the section is, and what meant_for names.
    instruction = model.calls[0].messages[0].content
    assert "Concurrent stimuli" in instruction
    assert "`meant_for`" in instruction
    assert "corrects, completes, cancels or changes" in instruction


async def test_a_withheld_input_says_why_and_never_appears() -> None:
    """§5:6: an entry's input is read through the peer view, so outside input never shows."""
    model = FakeModelProvider(_proposal())
    running = (
        _entry(_RIVERSIDE, None, origin=InputOrigin.OUTSIDE),
        _entry(_WEATHER, None, origin=InputOrigin.ASSISTANT),
    )
    await _understand(model, running=running)
    outside, task = _payload(model).containers("Concurrent stimuli")
    # ADR-0353 §2:7: the empty marker, its tag and from by its parties, and never its text.
    assert outside.get("outside") == "yes"
    assert [(one.name, one.get("from"), one.get("withheld"), one.text) for one in outside.tags] == [
        ("received", "an unknown sender", "yes", None)
    ]
    assert [(one.name, one.get("from"), one.get("withheld"), one.text) for one in task.tags] == [
        ("task", "the system", "yes", None)
    ]


async def test_the_section_says_how_many_more_run() -> None:
    """§5:10: at most the limit's entries, and how many more are running."""
    model = FakeModelProvider(_proposal())
    await _understand(model, running=(_entry(_RIVERSIDE, "book Riverside"),), more=3)
    assert "3 more are running" in _payload(model).section("Concurrent stimuli")


async def test_meant_for_naming_two_activations_resolves_both_in_order_each_once() -> None:
    """ADR-0353 §10:4, ADR-0349 §10:2: in the reply's order, each once, into ``continues``."""
    model = FakeModelProvider(_proposal(meant_for=["R2", "R1", "R2"]))
    running = (_entry(_RIVERSIDE, "book Riverside"), _entry(_SATURDAY, "on Saturday"))
    understood = await _understand(model, running=running)
    assert understood.continues == (_SATURDAY, _RIVERSIDE)
    assert understood.grounding_dropped == 0


@pytest.mark.parametrize("label", ["R3", "H1", "P1", "running"])
async def test_a_meant_for_label_naming_no_shown_activation_is_dropped_with_no_repair(
    label: str,
) -> None:
    """ADR-0353 §9:11, §16:4: ``R`` form or not, dropped and counted, never a repair call."""
    model = FakeModelProvider.scripted(_proposal(meant_for=[label, "R1"]))

    understood = await _understand(model, running=(_entry(_RIVERSIDE, "book Riverside"),))

    assert len(model.calls) == 1
    assert understood.continues == (_RIVERSIDE,)
    assert understood.grounding_dropped == 1


async def test_with_nothing_shown_meant_for_resolves_to_nothing_with_no_repair() -> None:
    model = FakeModelProvider.scripted(_proposal(meant_for=["R1"]))
    understood = await _understand(model, running=())
    assert _payload(model).concurrent() == []
    assert len(model.calls) == 1
    assert understood.continues == ()
    assert understood.grounding_dropped == 1


async def test_a_reply_meant_for_nothing_records_none() -> None:
    model = FakeModelProvider(_proposal(meant_for=[]))
    understood = await _understand(model, running=(_entry(_RIVERSIDE, "book Riverside"),))
    assert understood.continues == ()
    assert understood.grounding_dropped == 0
    assert len(model.calls) == 1


async def test_a_reply_that_omits_meant_for_records_none() -> None:
    """§9:2: an absent ``meant_for`` reads as the empty sequence."""
    model = FakeModelProvider(_proposal())
    understood = await _understand(model, running=(_entry(_RIVERSIDE, "book Riverside"),))
    assert understood.continues == ()
    assert len(model.calls) == 1


def test_the_reply_is_read_as_a_list_of_labels() -> None:
    """§9:2: ``meant_for`` parses as a list; one label or ``null`` is refused."""
    named, none = _parsed(_proposal(meant_for=["R1", "R2"])), _parsed(_proposal(meant_for=[]))
    assert named is not None
    assert none is not None
    assert (named.meant_for, none.meant_for) == (("R1", "R2"), ())
    assert _parsed(_proposal(meant_for="R1")) is None
    assert _parsed(_proposal(meant_for=None)) is None
    assert _parsed(_proposal(meant_for=7)) is None


def test_a_continues_in_the_reply_is_a_key_the_shape_no_longer_names() -> None:
    """§9:2: the reply names running work in ``meant_for``; a ``continues`` is a key its
    shape does not name, so the reply does not parse (ADR-0354 §3:4, §10:1)."""
    assert _parsed(_proposal(continues=["R1"])) is None


# --- ADR-0353 §10: an R label is citable anywhere -----------------------------------------


async def test_an_r_label_in_cites_records_a_running_referent_and_costs_no_repair() -> None:
    """§10:1, §10:2, §16:4: the activation's episode id, its channel and the entry's brief,
    as the entry rendered it, on the first completion."""
    model = FakeModelProvider.scripted(_proposal(cites=["R2", "R1"]))
    running = (
        _entry(_RIVERSIDE, "book Riverside"),
        _entry(_SATURDAY, None, origin=InputOrigin.OUTSIDE),
    )

    understood = await _understand(model, running=running)

    assert len(model.calls) == 1
    assert understood.meaning_referents == (
        UnderstandingReferent(
            kind="running",
            id=f"activation:{_SATURDAY}",
            source="telegram:line:42",
            # As its entry rendered it: withheld, so nothing of it (§10:1).
            excerpt="",
        ),
        UnderstandingReferent(
            kind="running",
            id=f"activation:{_RIVERSIDE}",
            source="telegram:line:42",
            excerpt="book Riverside",
        ),
    )
    assert understood.grounding_dropped == 0


async def test_a_running_referent_s_excerpt_is_cut_to_the_referent_bound() -> None:
    """ADR-0276 §2:5's bound, on the brief exactly as the entry rendered it."""
    brief = "x" * (UNDERSTANDING_REFERENT_EXCERPT_CHARS + 20)
    model = FakeModelProvider.scripted(_proposal(cites=["R1"]))

    understood = await _understand(model, running=(_entry(_RIVERSIDE, brief),))

    (referent,) = understood.meaning_referents
    assert referent.excerpt == brief[:UNDERSTANDING_REFERENT_EXCERPT_CHARS]


async def test_an_r_label_in_cites_alone_yields_an_empty_continues() -> None:
    """§10:4, §16:4: only ``meant_for`` makes the input part of running work; that no
    takeover follows is ``test_phases_matters``'s, over the engine."""
    model = FakeModelProvider.scripted(_proposal(cites=["R1"], belongs_to=["R1"]))

    understood = await _understand(model, running=(_entry(_RIVERSIDE, "book Riverside"),))

    assert understood.continues == ()


async def test_an_r_label_in_belongs_to_records_an_activation_member() -> None:
    """§10:3, §16:4: as a label naming an earlier stimulus resolves to its activation."""
    model = FakeModelProvider.scripted(_proposal(belongs_to=["R1"]))

    understood = await _understand(model, running=(_entry(_RIVERSIDE, "book Riverside"),))

    assert len(model.calls) == 1
    assert understood.story_links == (StoryMember(kind=StoryMemberKind.ACTIVATION, id=_RIVERSIDE),)
    assert understood.meaning_referents == ()
    assert understood.grounding_dropped == 0


@pytest.mark.parametrize("where", ["still-open", "later-absorbed"])
async def test_the_story_links_stage_links_a_running_activation_member(where: str) -> None:
    """§10:3, §16:4: the stage reads the story store by the activation's id and no
    episode, so it links the member whether the running activation's episode is still
    open — in no story yet, so a story is started holding both — or was since absorbed
    into another's matter, a story it is already a member of."""
    model = FakeModelProvider.scripted(_proposal(belongs_to=["R1"]))
    understood = await _understand(model, running=(_entry(_RIVERSIDE, "book Riverside"),))
    stories = FakeStoryStore()
    held = None
    if where == "later-absorbed":
        made = await stories.create(
            (StoryMember(kind=StoryMemberKind.ACTIVATION, id=_RIVERSIDE),),
            actor=StoryActor.UNDERSTANDING,
            trigger=_WEATHER,
        )
        held = made.story_id

    decision = await StoryLinksStage(stories=stories).record(
        understood.story_links, activation_id=_HOLDER
    )

    assert decision.refused == ()
    (header,) = await stories.stories_of(StoryMember(kind=StoryMemberKind.ACTIVATION, id=_HOLDER))
    if held is None:
        assert decision.started == header.story_id
    else:
        assert decision.linked == (held,) == (header.story_id,)
    assert [one.story_id for one in await stories.stories_of(understood.story_links[0])] == [
        header.story_id
    ]


@pytest.mark.parametrize("field", ["cites", "belongs_to"])
async def test_an_r_label_naming_no_shown_entry_is_dropped_with_no_repair(field: str) -> None:
    """§9:11, §16:4: in ``cites`` or ``belongs_to``, dropped and counted, never a repair."""
    model = FakeModelProvider.scripted(_proposal(**{field: ["R1", "R7"]}))

    understood = await _understand(model, running=(_entry(_RIVERSIDE, "book Riverside"),))

    assert len(model.calls) == 1
    assert understood.grounding_dropped == 1
    resolved = understood.meaning_referents if field == "cites" else understood.story_links
    assert len(resolved) == 1


@pytest.mark.parametrize("field", ["cites", "belongs_to"])
async def test_any_other_unresolved_label_there_earns_the_one_repair(field: str) -> None:
    """§9:10, §16:4: a label of another form naming nothing rendered is repaired once."""
    bad = _proposal(**{field: ["R1", "P4"]})
    model = FakeModelProvider.scripted(bad, bad)

    understood = await _understand(model, running=(_entry(_RIVERSIDE, "book Riverside"),))

    assert len(model.calls) == 2
    statement = model.calls[1].messages[-1].content
    assert '"P4"' in statement
    assert '"R1"' not in statement
    assert "R1 (the concurrent stimuli)" in statement
    assert understood.grounding_dropped == 1
