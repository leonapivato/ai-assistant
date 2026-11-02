"""A defect inside an activation is logged loudly, and answered as any failure is (#2904).

An activation that cannot finish is answered the same whatever ended it: an event
returns *couldn't finish* (ADR-0313 §4:5), and a conversation is written the fixed
message (ADR-0317 §3:3). So a ``ValueError`` from a bug reads to its caller exactly as a
model's failure does. What tells them apart is the log: a defect is logged under the
line its failure always was, at error level, naming the stage, the activation and the
exception's class, with its frames and without its message (ADR-0314 §3:2); an
expected failure keeps its level.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, Final

import pytest
from exchange_support import text_call
from phases_support import chat_turn, entries, event, phases_harness, processing, written
from structlog.testing import capture_logs
from test_engine import AT
from test_engine_phases import _call

from ai_assistant.core.errors import ConversationStoreError, ModelError
from ai_assistant.core.types import (
    ActivationEnding,
    ControllerRule,
    ControllerStage,
    InformationalEventResult,
    MessageAuthor,
    MessageReceipt,
    NewMessage,
    RoundResponse,
    StageOutcome,
)
from ai_assistant.orchestration.chat import COULDNT_FINISH
from ai_assistant.orchestration.defects import ToleratedStageError
from ai_assistant.orchestration.phase_path import is_defect, log_defect
from ai_assistant.testing import (
    FakeConversationStore,
    FakeModelProvider,
    FakeToolCallingCompleter,
    FakeWebSearcher,
)

if TYPE_CHECKING:
    from collections.abc import MutableMapping, Sequence

    from test_engine import Harness

    from ai_assistant.core.types import EpisodicMemory, Message, OfferedTool, PlanningExchange
    from ai_assistant.orchestration.chat import ChatWriter

#: Words a failure's message carries, which no log line may.
_PRIVATE: Final = "the user's private words"


class _Raising(FakeToolCallingCompleter):
    """Planning whose every round raises ``error`` as itself.

    The fake wraps a failing ``response`` callable in a ``ModelError``, as the
    provider-backed completer's boundary does, so the raise is here instead.
    """

    def __init__(self, error: Exception) -> None:
        super().__init__()
        self._error = error

    async def respond(
        self,
        exchange: PlanningExchange,
        tools: Sequence[OfferedTool],
        *,
        model: str | None = None,
    ) -> RoundResponse:
        del exchange, tools, model
        raise self._error


def _raising(error: Exception) -> FakeToolCallingCompleter:
    """Planning whose every round raises ``error``."""
    return _Raising(error)


def _errors(logs: Sequence[MutableMapping[str, Any]]) -> list[MutableMapping[str, Any]]:
    return [one for one in logs if one["log_level"] == "error"]


def _defect_line(logs: Sequence[MutableMapping[str, Any]], event: str) -> MutableMapping[str, Any]:
    """The one error-level line, ``event``, checked to carry no message and no content."""
    (line,) = _errors(logs)
    assert line["event"] == event
    assert "exc_info" not in line
    assert _PRIVATE not in repr(logs)
    return line


async def _replies(harness: Harness, episode: EpisodicMemory) -> list[str]:
    trigger = processing(episode).trigger
    conversation = trigger.channel.instance_id  # type: ignore[union-attr]  # a conversation's trigger
    return [
        one.text
        for one in await written(harness, conversation)
        if one.author is MessageAuthor.ASSISTANT
    ]


def _activation(episode: EpisodicMemory) -> str:
    return processing(episode).activation_id


# --- the rule -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("failure", "defect"),
    [
        (ValueError("bug"), True),
        (KeyError("bug"), True),
        (AttributeError("bug"), True),
        (ModelError("down"), False),
        (ConversationStoreError("busy"), False),
        (TimeoutError(), False),
        (ToleratedStageError("recall's digest failed"), False),
        (ExceptionGroup("both", [ModelError("down"), TimeoutError()]), False),
        (ExceptionGroup("both", [ModelError("down"), ValueError("bug")]), True),
    ],
)
def test_a_defect_is_any_exception_outside_the_projects_own_errors_and_timeouts(
    failure: Exception, defect: bool
) -> None:
    assert is_defect(failure) is defect


# --- the chat -----------------------------------------------------------------------------


async def test_a_defect_in_a_phase_is_logged_at_error_and_the_chat_still_told() -> None:
    harness = phases_harness(_raising(ValueError(_PRIVATE)))
    with capture_logs() as logs:
        _, episode = await chat_turn(harness, "book the campsite")

    line = _defect_line(logs, "chat_activation_failed")
    assert line["stage"] == "planning"
    assert line["activation_id"] == _activation(episode)
    assert line["error"] == "ValueError"
    assert "respond" in line["traceback"], "the frames it passed through"
    assert line["traceback"].rstrip().endswith("ValueError")
    # The caller is answered as for any failure: one *couldn't finish*, nothing more.
    assert await _replies(harness, episode) == [COULDNT_FINISH]


async def test_an_expected_failure_in_a_phase_keeps_its_level() -> None:
    harness = phases_harness(_raising(ModelError(_PRIVATE)))
    with capture_logs() as logs:
        _, episode = await chat_turn(harness, "book the campsite")

    assert _errors(logs) == []
    assert any(
        one["event"] == "chat_activation_failed" and one["log_level"] == "warning" for one in logs
    )
    assert await _replies(harness, episode) == [COULDNT_FINISH]


class _UnwritableReply(FakeConversationStore):
    """A store that refuses every assistant message with ``error``."""

    def __init__(self, error: Exception) -> None:
        super().__init__(now=lambda: AT)
        self._error = error

    async def append_message(self, conversation_id: str, message: NewMessage) -> MessageReceipt:
        if message.author is MessageAuthor.ASSISTANT:
            raise self._error
        return await super().append_message(conversation_id, message)


async def test_a_defect_writing_couldnt_finish_is_logged_and_never_raised() -> None:
    """The message's own write failing on a defect is logged at its stage, ``end``; the
    activation still ends on its own, expected, failure."""
    harness = phases_harness(
        _raising(ModelError(_PRIVATE)), conversation_store=_UnwritableReply(KeyError(_PRIVATE))
    )
    with capture_logs() as logs:
        _, episode = await chat_turn(harness, "book the campsite")

    line = _defect_line(logs, "phase_message_unwritten")
    assert line["stage"] == "end"
    assert line["activation_id"] == _activation(episode)
    assert line["error"] == "KeyError"
    assert await _replies(harness, episode) == []


async def test_a_store_failure_writing_couldnt_finish_keeps_its_level() -> None:
    harness = phases_harness(
        _raising(ModelError(_PRIVATE)),
        conversation_store=_UnwritableReply(ConversationStoreError(_PRIVATE)),
    )
    with capture_logs() as logs:
        await chat_turn(harness, "book the campsite")

    assert _errors(logs) == []


# --- an event -----------------------------------------------------------------------------


def _ended(harness_result: object) -> ActivationEnding:
    result = getattr(harness_result, "result", None)
    assert isinstance(result, InformationalEventResult)
    return result.ended


async def test_a_defect_in_an_event_is_logged_at_error_and_still_couldnt_finish() -> None:
    harness = phases_harness(_raising(ValueError(_PRIVATE)))
    with capture_logs() as logs:
        result, episode = await event(harness)

    line = _defect_line(logs, "event_activation_failed")
    assert line["stage"] == "planning"
    assert line["activation_id"] == _activation(episode)
    assert line["error"] == "ValueError"
    assert _ended(result) is ActivationEnding.COULDNT_FINISH


async def test_an_expected_failure_in_an_event_logs_nothing_at_error() -> None:
    harness = phases_harness(_raising(ModelError(_PRIVATE)))
    with capture_logs() as logs:
        result, _ = await event(harness)

    assert _errors(logs) == []
    assert _ended(result) is ActivationEnding.COULDNT_FINISH


# --- which stage ----------------------------------------------------------------------


class _BrokenWriter:
    """A place's writer that raises what no store does: a defect."""

    def __init__(self, writer: ChatWriter) -> None:
        self._writer = writer

    def fitted(self, conversation_id: str, message: NewMessage) -> NewMessage:
        return self._writer.fitted(conversation_id, message)

    async def send(self, conversation_id: str, message: NewMessage) -> MessageReceipt | None:
        del conversation_id, message
        raise RuntimeError(_PRIVATE)


class _StalledDigests(FakeModelProvider):
    """A digest that answers only once any case here has ended."""

    async def complete(self, messages: Sequence[Message], *, model: str | None = None) -> Message:
        await asyncio.sleep(10)
        return await super().complete(messages, model=model)


async def test_a_defect_in_acting_is_named_acting_not_the_digest_cancelled_beside_it() -> None:
    """ADR-0309 §3:4: the digest beside the failed step is recorded failed once
    cancelled, but acting's failure is what ended the pass, and what the line names."""
    completer = FakeToolCallingCompleter.scripted(
        RoundResponse(
            calls=(
                text_call("Let me look that up."),
                _call("c1", "search_web", query="museum hours", looking_for="opening"),
            ),
        )
    )
    harness = phases_harness(
        completer,
        phases={
            "searcher": FakeWebSearcher(results=("Open daily from 9:00.",)),
            "wrap": _BrokenWriter,
            "digests": _StalledDigests(reply="unused"),
        },
    )
    with capture_logs() as logs:
        _, episode = await chat_turn(harness, "when does the museum open?")

    assert entries(processing(episode))[-3:] == [
        (ControllerStage.ACTING, ControllerRule.ROUND_AUTHORIZED, StageOutcome.FAILED),
        (ControllerStage.DIGESTING, ControllerRule.ROUND_AUTHORIZED, StageOutcome.FAILED),
        (ControllerStage.END, ControllerRule.STAGE_FAILED, StageOutcome.DONE),
    ]
    defects = [one for one in _errors(logs) if one["event"] == "chat_activation_failed"]
    (line,) = defects
    assert (line["stage"], line["error"]) == ("acting", "RuntimeError")
    assert _PRIVATE not in repr(logs)


# --- a group --------------------------------------------------------------------------


def _child_raises() -> None:
    raise ValueError(_PRIVATE)


async def _task_group_failure() -> ExceptionGroup[Exception]:
    """A task group whose two children raise: a defect and a model's error."""

    async def child() -> None:
        _child_raises()

    async def other() -> None:
        raise ModelError(_PRIVATE)

    try:
        async with asyncio.TaskGroup() as group:
            group.create_task(child())
            group.create_task(other())
    except ExceptionGroup as caught:
        return caught
    raise AssertionError  # pragma: no cover - the group above always raises


async def test_a_group_is_logged_with_each_exception_it_holds_and_where_it_was_raised() -> None:
    nested = ExceptionGroup("outer", [await _task_group_failure(), KeyError(_PRIVATE)])

    with capture_logs() as logs:
        log_defect("chat_activation_failed", nested, stage="acting", activation_id="a-1")

    line = _defect_line(logs, "chat_activation_failed")
    held = ("ExceptionGroup(ExceptionGroup(", "ValueError", "ModelError", "KeyError")
    assert all(one in line["error"] for one in held)
    assert "_child_raises" in line["traceback"], "the child's own raising frame"
    assert "| | ValueError" in line["traceback"], "listed under both groups"
