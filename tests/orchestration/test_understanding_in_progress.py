"""ADR-0349 §5, §7:7, §10:1-§10:2: understanding reads taken-in input and running work.

The stage alone, over a scripted model: an input a merge brought renders with the input,
each kept apart and dated and marked as taken over (§7:7); the in-progress section
renders each entry exactly as §5:6 has it, under ``R`` labels, with how many more run
(§5:7, §5:10); ``continues`` is a list, each label resolving to its activation's id, once
and in order (§10:1-§10:2); and a label naming no shown activation is repaired once and
then dropped and counted, never a parse failure (§10:2). What the engine shows the stage
is ``test_matters``'s and ``test_phases_matters``'s.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Final

from ai_assistant.core.types import (
    ChannelContext,
    ChannelIdentity,
    InputOrigin,
    JoinedInput,
    RecordedInputMessage,
)
from ai_assistant.orchestration.disclosure import BoundedAudienceSupply
from ai_assistant.orchestration.matters import InProgressEntry
from ai_assistant.orchestration.understanding import (
    UNDERSTANDING_PROMPT,
    SuppliedWindow,
    UnderstandingStage,
    _parsed,
)
from ai_assistant.testing import FakeModelProvider, default_prompt

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.core.types import ActivationUnderstanding

_AT: Final = datetime(2026, 10, 21, 9, tzinfo=UTC)
_HERE: Final = ChannelIdentity(channel_type="conversation", instance_id="c-here")
_THERE: Final = ChannelIdentity(channel_type="telegram", instance_id="line:42")
_RIVERSIDE: Final = "0b8f8f0e-2a5c-4c55-9a6c-6a2c1f0b0d11"
_SATURDAY: Final = "1c9a9f1f-3b6d-4d66-8b7d-7b3d2a1c1e22"
_WEATHER: Final = "2d0b0a2a-4c7e-4e77-9c8e-8c4e3b2d2f33"


def _proposal(**fields: Any) -> str:
    return json.dumps(
        {"meaning": "Book Riverside for Saturday.", "meaning_ground": "stated"} | fields
    )


def _message(text: str, *, seconds: int = 0, position: int | None = None) -> RecordedInputMessage:
    return RecordedInputMessage(
        text=text, sent_at=_AT + timedelta(seconds=seconds), position=position
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
        model=model, excerpt_chars=2000, prompt=default_prompt(UNDERSTANDING_PROMPT)
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


def _payload(model: FakeModelProvider, call: int = 0) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(model.calls[call].messages[1].content)
    return loaded


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

    received = _payload(model)["input"]
    assert received["text"] == "book Riverside"
    (taken,) = received["joined"]
    assert taken["place"] == "telegram:line:42"
    assert taken["messages"] == [
        {"sent_at": (_AT + timedelta(seconds=8)).isoformat(), "text": "for four", "position": 7}
    ]
    assert "stopped" in taken["taken_over"]
    # The activation a merge stopped is never named to the model: it is no label.
    assert _SATURDAY not in json.dumps(received)


async def test_an_input_nothing_was_taken_into_renders_as_before() -> None:
    model = FakeModelProvider(_proposal())
    await _understand(model)
    assert "joined" not in _payload(model)["input"]
    assert "in_progress" not in _payload(model)


# --- §5:6-§5:10: the in-progress section -------------------------------------------


async def test_each_entry_shows_exactly_what_caused_it_its_input_and_whether_it_acted() -> None:
    """§5:6: a label, its channel and place, its input in brief, and whether it acted."""
    model = FakeModelProvider(_proposal(continues=["R2"]))
    running = (
        _entry(_RIVERSIDE, "book Riverside", acted=True),
        _entry(_SATURDAY, "on Saturday"),
    )

    understood = await _understand(model, running=running)

    section = _payload(model)["in_progress"]
    assert section == [
        {
            "label": "R1",
            "place": "telegram:line:42",
            "input": "book Riverside",
            "has_acted": True,
        },
        {"label": "R2", "place": "telegram:line:42", "input": "on Saturday", "has_acted": False},
    ]
    # No id reaches the model: a label resolves to it here.
    assert _SATURDAY not in model.calls[0].messages[1].content
    assert understood.continues == (_SATURDAY,)
    assert understood.grounding_dropped == 0
    assert len(model.calls) == 1
    # The instruction says what the section is, and where an R label goes.
    instruction = model.calls[0].messages[0].content
    assert "in_progress" in instruction
    assert "`continues`" in instruction
    assert "corrects, completes, cancels or changes" in instruction


async def test_a_withheld_input_says_why_and_never_appears() -> None:
    """§5:6: an entry's input is read through the peer view, so outside input never shows."""
    model = FakeModelProvider(_proposal())
    running = (
        _entry(_RIVERSIDE, None, origin=InputOrigin.OUTSIDE),
        _entry(_WEATHER, None, origin=InputOrigin.ASSISTANT),
    )
    await _understand(model, running=running)
    shown = [one["input"] for one in _payload(model)["in_progress"]]
    assert shown == [
        "an outside report, not shown",
        "the assistant's own instruction for work it scheduled, not shown",
    ]


async def test_the_section_says_how_many_more_run() -> None:
    """§5:10: at most the limit's entries, and how many more are running."""
    model = FakeModelProvider(_proposal())
    await _understand(model, running=(_entry(_RIVERSIDE, "book Riverside"),), more=3)
    assert "3 more running" in _payload(model)["in_progress_more"]


async def test_continues_naming_two_activations_resolves_both_in_order_each_once() -> None:
    """§10:1-§10:2: in the proposal's order, each once."""
    model = FakeModelProvider(_proposal(continues=["R2", "R1", "R2"]))
    running = (_entry(_RIVERSIDE, "book Riverside"), _entry(_SATURDAY, "on Saturday"))
    understood = await _understand(model, running=running)
    assert understood.continues == (_SATURDAY, _RIVERSIDE)
    assert understood.grounding_dropped == 0


async def test_a_continues_naming_no_shown_activation_is_repaired_once_then_dropped() -> None:
    """§10:2: a grounding defect (ADR-0276 §6), never a parse failure."""
    model = FakeModelProvider.scripted(_proposal(continues=["R3"]), _proposal(continues=["R9"]))

    understood = await _understand(model, running=(_entry(_RIVERSIDE, "book Riverside"),))

    assert len(model.calls) == 2
    statement = model.calls[1].messages[-1].content
    assert '"R3"' in statement
    assert "R1 (the in_progress section, cited only in `continues`)" in statement
    assert understood.continues == ()
    assert understood.grounding_dropped == 1


async def test_a_continues_repaired_onto_a_shown_label_resolves() -> None:
    model = FakeModelProvider.scripted(_proposal(continues=["H1"]), _proposal(continues=["R1"]))
    understood = await _understand(model, running=(_entry(_RIVERSIDE, "book Riverside"),))
    assert understood.continues == (_RIVERSIDE,)
    assert understood.grounding_dropped == 0


async def test_with_nothing_shown_a_continues_resolves_to_nothing() -> None:
    model = FakeModelProvider.scripted(_proposal(continues=["R1"]), _proposal(continues=["R1"]))
    understood = await _understand(model, running=())
    assert "in_progress" not in _payload(model)
    assert understood.continues == ()
    assert understood.grounding_dropped == 1


async def test_a_reply_continuing_nothing_records_none() -> None:
    model = FakeModelProvider(_proposal(continues=[]))
    understood = await _understand(model, running=(_entry(_RIVERSIDE, "book Riverside"),))
    assert understood.continues == ()
    assert understood.grounding_dropped == 0
    assert len(model.calls) == 1


async def test_a_reply_that_omits_continues_records_none() -> None:
    """§10:1: an absent ``continues`` reads as the empty sequence."""
    model = FakeModelProvider(_proposal())
    understood = await _understand(model, running=(_entry(_RIVERSIDE, "book Riverside"),))
    assert understood.continues == ()
    assert len(model.calls) == 1


def test_the_reply_is_read_as_a_list_of_labels() -> None:
    """§10:1: ``continues`` parses as a list; one label or ``null`` is the old shape."""
    named, none = _parsed(_proposal(continues=["R1", "R2"])), _parsed(_proposal(continues=[]))
    assert named is not None
    assert none is not None
    assert (named.continues, none.continues) == (("R1", "R2"), ())
    assert _parsed(_proposal(continues="R1")) is None
    assert _parsed(_proposal(continues=None)) is None
    assert _parsed(_proposal(continues=7)) is None
