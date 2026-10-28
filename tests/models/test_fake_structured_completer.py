"""The canonical ``StructuredCompleter`` fake, through the shared contract and beyond it."""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest
from pydantic import BaseModel
from structured_completer_contract import (
    REFUSAL,
    REFUSAL_CATEGORY,
    VALID_REPLY,
    VALID_VALUE,
    Answer,
    StructuredCompleterContract,
    Verdict,
    request,
    scripted_reply,
)

from ai_assistant.core.errors import ModelError, ModelRateLimitError
from ai_assistant.core.types import Message, ReplyFailure, ReplyMode, ReplyUsage, Role
from ai_assistant.testing import (
    DEFAULT_STRUCTURED_MODEL,
    FakeStructuredCompleter,
    ScriptedReply,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence

    from ai_assistant.core.protocols import StructuredCompleter


class _Defaults(BaseModel):
    note: str = "none"


@dataclass
class _FakeWorld:
    subject: FakeStructuredCompleter

    @property
    def completer(self) -> StructuredCompleter:
        return self.subject

    @property
    def attempts(self) -> int:
        return self.subject.call_count

    @property
    def answered_by(self) -> str:
        return DEFAULT_STRUCTURED_MODEL

    @property
    def mode(self) -> ReplyMode:
        return ReplyMode.NATIVE


class TestFakeStructuredCompleterContract(StructuredCompleterContract):
    """``FakeStructuredCompleter`` passes the shared ``StructuredCompleter`` contract."""

    #: The fake answers without awaiting anything, so a caller's mutation has no
    #: window to land in (ADR-0069 §3).
    completes_without_suspending = True

    @pytest.fixture
    def completer(self) -> StructuredCompleter:
        return FakeStructuredCompleter()

    @contextlib.asynccontextmanager
    async def world(self, answer: Answer) -> AsyncIterator[_FakeWorld]:
        yield _FakeWorld(subject=FakeStructuredCompleter(scripted_reply(answer)))


class TestTheFakeBeyondTheContract:
    """What the fake promises its own users, over and above the shared contract."""

    async def test_a_scripted_fake_answers_in_turn_then_raises(self) -> None:
        fake = FakeStructuredCompleter.scripted(VALID_REPLY, "nope")
        first = await fake.complete_structured(request(), Verdict)
        second = await fake.complete_structured(request(), Verdict)
        assert first.value == VALID_VALUE
        assert second.failure is ReplyFailure.INVALID
        with pytest.raises(AssertionError):
            await fake.complete_structured(request(), Verdict)

    async def test_a_scripted_model_error_is_raised_as_given(self) -> None:
        limited = ModelRateLimitError("slow down")
        fake = FakeStructuredCompleter.scripted(limited)
        with pytest.raises(ModelRateLimitError) as caught:
            await fake.complete_structured(request(), Verdict)
        assert caught.value is limited

    async def test_a_failing_script_raises_a_bare_model_error(self) -> None:
        def broken(_messages: Sequence[Message], _shape: type[BaseModel]) -> str:
            raise ValueError

        with pytest.raises(ModelError) as caught:
            await FakeStructuredCompleter(broken).complete_structured(request(), Verdict)
        assert type(caught.value) is ModelError

    async def test_a_refused_call_is_inert(self) -> None:
        fake = FakeStructuredCompleter.scripted(VALID_REPLY)
        with pytest.raises(ModelError):
            await fake.complete_structured([], Verdict)
        assert fake.call_count == 0
        reply = await fake.complete_structured(request(), Verdict)
        assert reply.value == VALID_VALUE

    async def test_each_accepted_call_is_recorded_with_its_shape_and_model(self) -> None:
        fake = FakeStructuredCompleter(VALID_REPLY)
        conversation = request()
        await fake.complete_structured(conversation, Verdict, model="anthropic:x")
        conversation.append(Message(role=Role.USER, content="later"))
        assert fake.last_call.shape is Verdict
        assert fake.last_call.model == "anthropic:x"
        assert fake.last_call.messages == tuple(request())

    async def test_a_scripted_reply_reports_what_it_is_given(self) -> None:
        scripted = ScriptedReply(
            text="",
            failure=ReplyFailure.REFUSED,
            refusal=REFUSAL,
            refusal_category=REFUSAL_CATEGORY,
            usage=ReplyUsage(input_tokens=2),
            model="anthropic:claude-sonnet-5-5",
            mode=ReplyMode.PROMPTED,
        )
        reply = await FakeStructuredCompleter(scripted).complete_structured(request(), Verdict)
        assert reply.failure is ReplyFailure.REFUSED
        assert reply.exchange.refusal_category == REFUSAL_CATEGORY
        assert reply.exchange.model == "anthropic:claude-sonnet-5-5"
        assert reply.exchange.mode is ReplyMode.PROMPTED
        assert reply.exchange.usage == ReplyUsage(input_tokens=2)

    async def test_an_unscripted_fake_reads_an_empty_object(self) -> None:
        reply = await FakeStructuredCompleter().complete_structured(request(), _Defaults)
        assert reply.value == _Defaults()

    async def test_a_scripted_summary_comes_back_on_the_exchange_and_not_in_the_reply(
        self,
    ) -> None:
        """ADR-0355 §4:3."""
        scripted = ScriptedReply(text=VALID_REPLY, thinking="Blue light scatters \ud800 most.")
        reply = await FakeStructuredCompleter(scripted).complete_structured(request(), Verdict)
        assert reply.value == VALID_VALUE
        assert reply.exchange.reply == VALID_REPLY
        assert reply.exchange.thinking == "Blue light scatters � most."

    @pytest.mark.parametrize(
        "answer",
        [
            pytest.param(VALID_REPLY, id="text"),
            pytest.param(ScriptedReply(text=VALID_REPLY), id="unscripted-summary"),
            pytest.param(ScriptedReply(text=VALID_REPLY, thinking=""), id="empty-summary"),
        ],
    )
    async def test_an_unscripted_summary_is_none(self, answer: str | ScriptedReply) -> None:
        reply = await FakeStructuredCompleter(answer).complete_structured(request(), Verdict)
        assert reply.exchange.thinking is None
