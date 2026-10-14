"""The switch: the phases plan every activation, and the old path's entries refuse.

ADR-0309 §2:6 makes §3's table the controller's only one, and §5:1 retires
``converse`` and ``resume``; ADR-0313 §3:1 retires spoken conversation. The members
that would start the old path's turn stay on the surface until the engine-surface
deletion lane removes them, so each refuses before any work — no admission, no episode,
no model call — rather than half-running an activation the table has no rows for. A
chat activation and an event both run on the phases, with no opt-in to set.
"""

from __future__ import annotations

import importlib.util
import inspect
from datetime import timedelta
from typing import TYPE_CHECKING, Final

import pytest
from channel_receiver_contract import event_input
from phases_support import (
    PHASE_PATH_STAGES,
    chat_turn,
    episodes,
    event,
    open_conversation,
    phases_harness,
    processing,
)
from test_engine import Harness, NoStepPlanner

from ai_assistant.core.errors import ConfigurationError
from ai_assistant.core.types import (
    ActivationEnding,
    ChannelIdentity,
    ChannelInput,
    ContinuationToken,
    InformationalEventResult,
    NewConversation,
    SpeechChannelPayload,
    SpokenAudio,
    SpokenAudioFormat,
    SpokenReply,
)
from ai_assistant.orchestration.controller import ACTIVATION_RULES
from ai_assistant.orchestration.engine import Engine
from ai_assistant.testing import FakeToolCallingCompleter

if TYPE_CHECKING:
    from collections.abc import Awaitable

_BUDGET: Final = timedelta(seconds=10)
_RECORDING: Final = SpokenAudio(content="YXVkaW8=", media_type=SpokenAudioFormat.MP4)


async def test_a_chat_activation_runs_on_the_phases() -> None:
    """ADR-0309 §2:6: every stage that ran is one §3's table makes due."""
    completer = FakeToolCallingCompleter()
    harness = phases_harness(completer)

    _, episode = await chat_turn(harness, "hello")

    stages = {entry.stage for entry in processing(episode).stages}
    assert stages <= PHASE_PATH_STAGES
    assert completer.calls, "planning ran"


async def test_an_event_runs_on_the_phases() -> None:
    """ADR-0313 §4:3: one activation, its result how it ended."""
    completer = FakeToolCallingCompleter()
    harness = phases_harness(completer)

    result, episode = await event(harness)

    assert isinstance(result.result, InformationalEventResult)
    assert result.result.ended is ActivationEnding.DONE
    assert {entry.stage for entry in processing(episode).stages} <= PHASE_PATH_STAGES
    assert completer.calls, "planning ran"


def test_the_controller_runs_one_table() -> None:
    """§2:6, §7:1: ``ACTIVATION_RULES`` is the controller's default, and §3's."""
    from ai_assistant.orchestration import controller  # noqa: PLC0415 — the module's own name

    assert not hasattr(controller, "PHASE_RULES")
    init = controller.ActivationController.__init__
    assert init.__kwdefaults__ is not None
    assert init.__kwdefaults__["rules"] is ACTIVATION_RULES


def _retired_call(harness: Harness, member: str) -> Awaitable[object]:
    """A call to ``member``, one of the old path's entries the switch retired."""
    if member == "converse":
        return harness.engine.converse("hello", timeout=_BUDGET)
    return harness.engine.resume(
        ContinuationToken(handle="token-1"), approved=True, timeout=_BUDGET
    )


@pytest.mark.parametrize("member", ["converse", "resume"])
async def test_a_retired_member_refuses_before_any_work(member: str) -> None:
    """§5:1: a clear refusal, never a half-run activation.

    ``converse_spoken`` refused here too until ADR-0313 §3:1 took it off the surface,
    which ``ChannelReceiverContract`` pins on every implementation.
    """
    completer = FakeToolCallingCompleter()
    harness = phases_harness(completer)
    await open_conversation(harness)
    before = await harness.conversations.recent(limit=50)

    with pytest.raises(ConfigurationError, match=f"{member} retired at the cutover"):
        await _retired_call(harness, member)

    assert await episodes(harness.memory) == []
    assert completer.calls == []
    assert await harness.conversations.recent(limit=50) == before


@pytest.mark.parametrize("fresh", [True, False])
async def test_a_spoken_input_to_a_conversation_is_refused_and_starts_nothing(
    fresh: bool,
) -> None:
    """ADR-0313 §3:2, §4:1: spoken conversation retired, as the typed one did (ADR-0293 §11).

    Refused at admission, before processing: no activation, no model call and no
    conversation.
    """
    completer = FakeToolCallingCompleter()
    harness = phases_harness(completer)
    conversation = await open_conversation(harness)
    target = (
        NewConversation()
        if fresh
        else ChannelIdentity(channel_type="conversation", instance_id=conversation)
    )

    before = await harness.conversations.recent(limit=50)

    with pytest.raises(ValueError, match="unsupported channel input and reply combination"):
        await harness.engine.receive(
            ChannelInput(target=target, payload=SpeechChannelPayload(audio=_RECORDING)),
            reply=SpokenReply(plays=(SpokenAudioFormat.MP4,)),
            timeout=_BUDGET,
        )

    assert await episodes(harness.memory) == []
    assert completer.calls == []
    assert await harness.conversations.recent(limit=50) == before


async def test_an_engine_without_the_phases_refuses_an_event_and_runs_no_reader() -> None:
    """§2:6: an engine built without the phases runs no activation."""
    harness = Harness(planner=NoStepPlanner())

    with pytest.raises(ConfigurationError, match="informational event processing"):
        await harness.engine.receive(event_input(), reply=None, timeout=_BUDGET)
    assert await episodes(harness.memory) == []

    with pytest.raises(ConfigurationError, match="wired only beside them"):
        Harness(planner=NoStepPlanner(), chat_reader=True)


def test_the_interim_tidy_up_is_gone() -> None:
    """ADR-0309 §5:8: planning's tidy-up call replaces it (ADR-0307 §7)."""
    assert importlib.util.find_spec("ai_assistant.orchestration.story_tidy_up_interim") is None
    assert "interim_tidy_up" not in inspect.signature(Engine).parameters
