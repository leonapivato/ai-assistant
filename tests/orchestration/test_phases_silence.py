"""An activation that chose to say nothing has finished (ADR-0317).

Each case §2 and §3 decide, on an activation the chat's reader starts: a silent ending
writes nothing and ends done (§2); *couldn't finish* is written where the round limit,
the loop guard, a stage's failure or a deadline ended the activation, whatever earlier
rounds wrote (§3:2-§3:3), and where its last message was refused by authorizing or lost,
with none recorded after it (§3:4). Wherever it is written the episode freezes
``failed`` and the current state reads *couldn't finish* (§3:5).

Cases kept beside the code they drive: a stage failure before planning
(``test_phases_stage_endings``); a failure after messages were taken in and before the
first stage, which ``PhasePath.unbegun`` answers
(``test_phases_chat_reader.test_a_marking_that_fails_part_way_ends_as_couldnt_finish``); a
stop, a cancellation and a restart, which write nothing
(``test_engine_stop.test_a_stopped_chat_activation_writes_nothing_and_shows_stopped``,
``test_phases_chat_reader.test_a_shutdown_that_cancels_the_activation_writes_nothing``,
``test_activation_writer.test_a_close_puts_a_pass_that_died_unresolved_on_its_conversation``);
and an event, whose place takes no message
(``test_engine_phases.test_an_event_that_writes_nothing_is_done`` and
``test_an_event_ended_by_the_round_limit_couldnt_finish``).
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Any

import pytest
from structlog.testing import capture_logs
from test_engine import AT
from test_engine_phases import (
    _call,
    _classified,
    _conversation,
    _DownForTheReading,
    _event,
    _harness,
    _last_ended,
    _messages,
    _recalling_harness,
    _said,
    _say,
    _settled,
    _stages,
)

from ai_assistant.core.errors import ModelError, ModelTimeoutError
from ai_assistant.core.types import (
    ActivationEnding,
    ControllerRule,
    ControllerStage,
    MessageAuthor,
    ProcessingReason,
    ProcessingStatus,
    RecallOutcome,
    RoundResponse,
)
from ai_assistant.orchestration.authorizer import (
    AuthorizingStage,
    MessageVerdict,
    RoundAuthorization,
    RoundToAuthorize,
)
from ai_assistant.orchestration.chat import COULDNT_FINISH, ChatWriter, couldnt_finish
from ai_assistant.orchestration.phase_path import PhasePath
from ai_assistant.testing import FakeToolCallingCompleter

if TYPE_CHECKING:
    from collections.abc import Sequence

    from test_engine import Harness

    from ai_assistant.core.types import (
        EpisodicMemory,
        MessageReceipt,
        NewMessage,
        OfferedTool,
        PlanningExchange,
    )
    from ai_assistant.orchestration.phase_path import PhasePass

_ASSISTANT = MessageAuthor.ASSISTANT
_FAILED = (ProcessingStatus.FAILED, ProcessingReason.PROCESSING_FAILED)
_RETURNED = (ProcessingStatus.COMPLETED, ProcessingReason.RETURNED)

#: An earlier round's message, written beside a call that brings another round.
_FILLER = "Let me check."
#: A later round's message.
_ANSWER = "It's done."
#: *Couldn't finish*, listing the remember an earlier round made (ADR-0317 §3:1).
_LISTED = couldnt_finish(("the tool remember ran",)).text


def _remember() -> RoundResponse:
    """A call that brings a round (ADR-0315 §2:1), its text set by the case."""
    return RoundResponse(
        calls=(
            _call("c1", "remember", fact="The user likes tea.", why="a taste", rests_on_input=True),
        )
    )


def _filler() -> RoundResponse:
    return _remember().model_copy(update={"text": _FILLER})


async def _turn(harness: Harness, text: str = "hi") -> tuple[str, EpisodicMemory]:
    """One message's activation, once its episode froze, and the conversation it is in."""
    conversation = await _conversation(harness)
    with capture_logs():
        await _say(harness, conversation, text)
        episode = await _settled(harness, conversation)
    return conversation, episode


async def _replies(harness: Harness, conversation: str) -> list[str]:
    return [
        text
        for author, text in _said(await _messages(harness, conversation))
        if author is _ASSISTANT
    ]


async def _ended(harness: Harness, conversation: str, episode: EpisodicMemory) -> object:
    """How it ended, read off the episode's class and the conversation's current state."""
    return _classified(episode), await _last_ended(harness, conversation)


# --- §2: a silent ending -----------------------------------------------------------------


async def test_a_silent_round_with_no_call_ends_done_writing_nothing() -> None:
    """§2: the user's "sounds good", answered with silence, is a finish (#2943)."""
    harness = _harness(FakeToolCallingCompleter.scripted(RoundResponse()))

    conversation, episode = await _turn(harness, "sounds good")

    assert await _replies(harness, conversation) == []
    assert _stages(episode)[-1] == (ControllerStage.END, ControllerRule.NOTHING_DUE)
    assert episode.outcome is None
    assert await _ended(harness, conversation, episode) == (_RETURNED, ActivationEnding.DONE)


async def test_silence_after_calls_in_earlier_rounds_ends_the_same_way() -> None:
    """§2:1-§2:2: whatever its rounds did, its last made no call, and nothing is written.

    The effects the earlier round made are not listed to the user; they stay in the
    effect records (§2's note).
    """
    harness = _harness(FakeToolCallingCompleter.scripted(_remember(), RoundResponse()))

    conversation, episode = await _turn(harness)

    assert await _replies(harness, conversation) == []
    assert _stages(episode)[-1] == (ControllerStage.END, ControllerRule.NOTHING_DUE)
    assert await _ended(harness, conversation, episode) == (_RETURNED, ActivationEnding.DONE)
    effects = await harness.plans.activation_effects([episode.id.removeprefix("activation:")])
    assert [one.capability for one in effects] == ["remember"]


async def test_a_tolerated_failure_then_a_silent_end_writes_nothing() -> None:
    """§3:3: a failure a stage tolerates ends nothing, and §2 decides the ending."""
    completer = FakeToolCallingCompleter.scripted(RoundResponse())
    harness, _ = await _recalling_harness(completer, _DownForTheReading(now=lambda: AT))
    conversation = await _conversation(harness)
    await _say(harness, conversation, "when?")
    episode = await _settled(harness, conversation, seeded=frozenset({"activation:past"}))

    record = episode.processing_record
    assert record is not None
    assert record.recall_second_run is not None
    assert record.recall_second_run.outcome is RecallOutcome.FAILED
    assert await _replies(harness, conversation) == []
    assert await _ended(harness, conversation, episode) == (_RETURNED, ActivationEnding.DONE)


# --- §3:2-§3:3: the round limit, the loop guard, a stage's failure and a deadline ---------


@pytest.mark.parametrize("text", ["", "Trying."])
async def test_the_round_limit_writes_couldnt_finish_whatever_earlier_rounds_wrote(
    text: str,
) -> None:
    """§3:2: a loop of refused calls, silent or not, is ended by the round limit."""
    refused = RoundResponse(text=text, calls=(_call("c1", "nowhere"),))
    harness = _harness(FakeToolCallingCompleter.scripted(refused, refused, refused))

    conversation, episode = await _turn(harness)

    assert await _replies(harness, conversation) == [
        *([text] * 3 if text else []),
        COULDNT_FINISH,
    ]
    assert _stages(episode)[-1] == (ControllerStage.END, ControllerRule.ROUND_LIMIT_REACHED)
    assert await _ended(harness, conversation, episode) == (
        _FAILED,
        ActivationEnding.COULDNT_FINISH,
    )


class _ThenFails(FakeToolCallingCompleter):
    """Planning whose first round answers ``first`` and whose next raises ``error``."""

    def __init__(self, first: RoundResponse, error: Exception) -> None:
        super().__init__()
        self._first: RoundResponse | None = first
        self._error = error

    async def respond(
        self,
        exchange: PlanningExchange,
        tools: Sequence[OfferedTool],
        *,
        model: str | None = None,
    ) -> RoundResponse:
        del exchange, tools, model
        first, self._first = self._first, None
        if first is None:
            raise self._error
        return first


@pytest.mark.parametrize(
    ("error", "rule", "reason"),
    [
        (ModelError("down"), ControllerRule.STAGE_FAILED, ProcessingReason.PROCESSING_FAILED),
        (ModelTimeoutError("late"), ControllerRule.STAGE_TIMED_OUT, ProcessingReason.TIMEOUT),
    ],
)
async def test_a_stage_failure_or_a_deadline_writes_couldnt_finish_after_earlier_messages(
    error: Exception, rule: ControllerRule, reason: ProcessingReason
) -> None:
    """§3:3: a message already sent does not tell the user the rest was cut short."""
    harness = _harness(_ThenFails(_filler(), error))

    conversation, episode = await _turn(harness)

    assert await _replies(harness, conversation) == [_FILLER, _LISTED]
    assert _stages(episode)[-1] == (ControllerStage.END, rule)
    assert await _ended(harness, conversation, episode) == (
        (ProcessingStatus.FAILED, reason),
        ActivationEnding.COULDNT_FINISH,
    )


class _ForgetsTheSecondRuling(PhasePath):
    """A path whose second round's authorizing holds no decision, so its row answers again.

    The controller's loop guard ends the activation there (ADR-0280 §4:6, ADR-0309 §3:5),
    which nothing on the real path reaches.
    """

    async def _authorize(self, given: PhasePass) -> None:
        working = given.phases
        if working is not None and working.rounds > 1:
            return
        await super()._authorize(given)


async def test_the_loop_guard_writes_couldnt_finish_after_earlier_messages() -> None:
    """§3:3: the loop guard ending the activation counts as a stage's failure (§3:5).

    The second round writes no text, so no message of the activation is undelivered:
    the guard alone owes the message.
    """
    completer = FakeToolCallingCompleter.scripted(_filler(), _remember())
    harness = _harness(completer, path=_ForgetsTheSecondRuling)

    conversation, episode = await _turn(harness)

    assert await _replies(harness, conversation) == [_FILLER, _LISTED]
    assert _stages(episode)[-1] == (ControllerStage.END, ControllerRule.STAGE_REPEATED)
    assert await _ended(harness, conversation, episode) == (
        _FAILED,
        ActivationEnding.COULDNT_FINISH,
    )


async def test_an_event_the_loop_guard_ends_couldnt_finish_and_writes_nothing() -> None:
    """§3:3 with ADR-0313 §4:5: a stage's failure is how an event fails to finish."""
    # The second round's call is what makes authorizing due on a place taking no message.
    completer = FakeToolCallingCompleter.scripted(_remember(), _remember())
    harness = _harness(completer, path=_ForgetsTheSecondRuling)

    result, episode = await _event(harness)

    assert _stages(episode)[-1] == (ControllerStage.END, ControllerRule.STAGE_REPEATED)
    assert result.ended is ActivationEnding.COULDNT_FINISH
    assert _classified(episode) == _FAILED
    assert await harness.conversation_store.recent() == []


# --- §3:4: a message refused or lost -----------------------------------------------------


def _refusing(texts: frozenset[str]) -> type[AuthorizingStage]:
    """Authorizing that refuses a round's message whose text is one of ``texts``."""

    class _Refusing(AuthorizingStage):
        async def authorize(self, given: RoundToAuthorize) -> RoundAuthorization:
            decided = await super().authorize(given)
            if decided.message is None or given.message is None or given.message.text not in texts:
                return decided
            refused = MessageVerdict(place=decided.message.place, allowed=False, reason="refused")
            return replace(decided, message=refused)

    return _Refusing


class _Loses:
    """A place's writer that records no message whose text is one of ``texts``."""

    def __init__(self, writer: ChatWriter, texts: frozenset[str]) -> None:
        self._writer = writer
        self._texts = texts

    def fitted(self, conversation_id: str, message: NewMessage) -> NewMessage:
        return self._writer.fitted(conversation_id, message)

    async def send(self, conversation_id: str, message: NewMessage) -> MessageReceipt | None:
        if message.text in self._texts:
            return None
        return await self._writer.send(conversation_id, message)


def _undelivering(how: str, *texts: str) -> dict[str, Any]:
    """The knobs that keep a message whose text is one of ``texts`` from the conversation.

    ``refused`` has authorizing refuse it; ``lost`` has its write not come back done
    (ADR-0306 §5), which §3:4 treats the same.
    """
    held = frozenset(texts)
    if how == "refused":
        return {"authorizing": _refusing(held)}

    def wrap(writer: ChatWriter) -> _Loses:
        return _Loses(writer, held)

    return {"wrap": wrap}


_HOW = pytest.mark.parametrize("how", ["refused", "lost"])


@_HOW
async def test_an_undelivered_message_with_nothing_after_it_writes_couldnt_finish(
    how: str,
) -> None:
    """§3:4: the only message did not reach the conversation."""
    completer = FakeToolCallingCompleter.scripted(RoundResponse(text=_ANSWER))
    harness = _harness(completer, **_undelivering(how, _ANSWER))

    conversation, episode = await _turn(harness)

    assert await _replies(harness, conversation) == [COULDNT_FINISH]
    assert _stages(episode)[-1] == (ControllerStage.END, ControllerRule.NOTHING_DUE)
    assert await _ended(harness, conversation, episode) == (
        _FAILED,
        ActivationEnding.COULDNT_FINISH,
    )


@_HOW
async def test_an_undelivered_answer_after_delivered_filler_writes_couldnt_finish(
    how: str,
) -> None:
    """§3:4: "Let me check…" reached the user, and the answer that would follow did not."""
    completer = FakeToolCallingCompleter.scripted(_filler(), RoundResponse(text=_ANSWER))
    harness = _harness(completer, **_undelivering(how, _ANSWER))

    conversation, episode = await _turn(harness)

    assert await _replies(harness, conversation) == [_FILLER, _LISTED]
    assert await _ended(harness, conversation, episode) == (
        _FAILED,
        ActivationEnding.COULDNT_FINISH,
    )


@_HOW
async def test_an_undelivered_message_a_later_one_answered_writes_nothing_more(
    how: str,
) -> None:
    """§3:4: a later round that wrote again has answered, and §2:1 decides the ending."""
    completer = FakeToolCallingCompleter.scripted(_filler(), RoundResponse(text=_ANSWER))
    harness = _harness(completer, **_undelivering(how, _FILLER))

    conversation, episode = await _turn(harness)

    assert await _replies(harness, conversation) == [_ANSWER]
    assert episode.outcome == _ANSWER
    assert await _ended(harness, conversation, episode) == (_RETURNED, ActivationEnding.DONE)


@_HOW
async def test_an_undelivered_message_then_a_silent_round_writes_couldnt_finish(
    how: str,
) -> None:
    """§3:4: a later round that wrote nothing recorded no message, so nothing excuses it."""
    completer = FakeToolCallingCompleter.scripted(_filler(), RoundResponse())
    harness = _harness(completer, **_undelivering(how, _FILLER))

    conversation, episode = await _turn(harness)

    assert await _replies(harness, conversation) == [_LISTED]
    assert await _ended(harness, conversation, episode) == (
        _FAILED,
        ActivationEnding.COULDNT_FINISH,
    )
