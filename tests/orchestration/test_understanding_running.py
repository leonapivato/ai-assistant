"""ADR-0332 §3:10, §4:1-§4:4, §7:4: understanding reads joined input and running work.

The stage alone, over a scripted model: an input that joined renders with the input,
each kept apart and dated, a takeover's marked as one (§3:10); the same person's
running work on their other places renders as a section of its own under ``R`` labels
(§4:1); ``continues`` resolves by its label to the running activation's id (§4:4,
§7:4); and a label naming no shown activation is repaired once and then dropped and
counted, never a parse failure (§7:4). What the engine shows the stage is
``test_joining``'s and ``test_phases_joining``'s.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Final

from ai_assistant.core.types import (
    ChannelContext,
    ChannelIdentity,
    JoinedInput,
    RecordedInputMessage,
)
from ai_assistant.orchestration.disclosure import BoundedAudienceSupply
from ai_assistant.orchestration.joining import RunningActivation
from ai_assistant.orchestration.understanding import (
    UNDERSTANDING_PROMPT,
    SuppliedWindow,
    UnderstandingStage,
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


def _proposal(**fields: Any) -> str:
    return json.dumps(
        {"meaning": "Book Riverside for Saturday.", "meaning_ground": "stated"} | fields
    )


def _message(text: str, *, seconds: int = 0, position: int | None = None) -> RecordedInputMessage:
    return RecordedInputMessage(
        text=text, sent_at=_AT + timedelta(seconds=seconds), position=position
    )


def _running(activation_id: str, text: str, *, committed: bool = False) -> RunningActivation:
    return RunningActivation(
        activation_id=activation_id,
        place=_THERE,
        started_at=_AT,
        messages=(_message(text),),
        committed=committed,
    )


async def _understand(
    model: FakeModelProvider,
    *,
    joined: Sequence[JoinedInput] = (),
    running: Sequence[RunningActivation] | None = None,
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
    )


def _payload(model: FakeModelProvider, call: int = 0) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(model.calls[call].messages[1].content)
    return loaded


# --- §3:10: the activation's whole input ---------------------------------------------


async def test_each_joined_input_renders_with_the_input_apart_and_dated() -> None:
    model = FakeModelProvider(_proposal())
    joined = (
        JoinedInput(
            joined_at=_AT + timedelta(seconds=4),
            channel=_HERE,
            messages=(_message("make it Saturday", seconds=3, position=7),),
        ),
        JoinedInput(
            joined_at=_AT + timedelta(seconds=9),
            channel=_THERE,
            messages=(_message("for four", seconds=8),),
            taken_over_from=_SATURDAY,
        ),
    )

    await _understand(model, joined=joined)

    received = _payload(model)["input"]
    assert received["text"] == "book Riverside"
    first, second = received["joined"]
    assert first == {
        "joined_at": (_AT + timedelta(seconds=4)).isoformat(),
        "place": "conversation:c-here",
        "messages": [
            {
                "sent_at": (_AT + timedelta(seconds=3)).isoformat(),
                "text": "make it Saturday",
                "position": 7,
            }
        ],
    }
    assert "taken_over" not in first
    assert second["place"] == "telegram:line:42"
    assert "stopped" in second["taken_over"]
    # The activation a takeover stopped is never named to the model: it is no label.
    assert _SATURDAY not in json.dumps(received)


async def test_an_input_nothing_joined_renders_as_before() -> None:
    model = FakeModelProvider(_proposal())
    await _understand(model)
    assert "joined" not in _payload(model)["input"]
    assert "running" not in _payload(model)


# --- §4:1, §4:4, §7:4: the running section and ``continues`` -------------------------


async def test_running_work_renders_under_r_labels_and_continues_resolves_to_it() -> None:
    model = FakeModelProvider(_proposal(continues="R2"))
    running = (
        _running(_RIVERSIDE, "book Riverside", committed=True),
        _running(_SATURDAY, "on Saturday"),
    )

    understood = await _understand(model, running=running)

    section = _payload(model)["running"]
    assert [(one["label"], one["has_acted"]) for one in section] == [("R1", True), ("R2", False)]
    assert section[1]["place"] == "telegram:line:42"
    assert section[1]["messages"] == [{"sent_at": _AT.isoformat(), "text": "on Saturday"}]
    # No id reaches the model: a label resolves to it here.
    assert _SATURDAY not in model.calls[0].messages[1].content
    assert understood.continues == _SATURDAY
    assert understood.grounding_dropped == 0
    assert len(model.calls) == 1
    # The instruction says what the section is, and where an R label goes.
    instruction = model.calls[0].messages[0].content
    assert "R1, R2" in instruction
    assert "`continues`" in instruction


async def test_a_continues_naming_no_shown_activation_is_repaired_once_then_dropped() -> None:
    """§7:4: a grounding defect (ADR-0276 §6), never a parse failure."""
    model = FakeModelProvider.scripted(_proposal(continues="R3"), _proposal(continues="R9"))

    understood = await _understand(model, running=(_running(_RIVERSIDE, "book Riverside"),))

    assert len(model.calls) == 2
    statement = model.calls[1].messages[-1].content
    assert '"R3"' in statement
    assert "R1 (the running section, cited only in `continues`)" in statement
    assert understood.continues is None
    assert understood.grounding_dropped == 1


async def test_a_continues_repaired_onto_a_shown_label_resolves() -> None:
    model = FakeModelProvider.scripted(_proposal(continues="H1"), _proposal(continues="R1"))
    understood = await _understand(model, running=(_running(_RIVERSIDE, "book Riverside"),))
    assert understood.continues == _RIVERSIDE
    assert understood.grounding_dropped == 0


async def test_with_nothing_shown_a_continues_resolves_to_nothing() -> None:
    model = FakeModelProvider.scripted(_proposal(continues="R1"), _proposal(continues="R1"))
    understood = await _understand(model, running=())
    assert "running" not in _payload(model)
    assert understood.continues is None
    assert understood.grounding_dropped == 1


async def test_a_reply_continuing_nothing_records_none() -> None:
    model = FakeModelProvider(_proposal(continues=None))
    understood = await _understand(model, running=(_running(_RIVERSIDE, "book Riverside"),))
    assert understood.continues is None
    assert understood.grounding_dropped == 0
    assert len(model.calls) == 1
