"""The canonical FakeModelProvider passes the shared ModelProvider conformance suite.

This is what lets other subsystems trust ``ai_assistant.testing.FakeModelProvider``
as a stand-in for a real provider: it is held to the same contract as
``PydanticAIProvider``. Behaviour beyond the shared contract — call recording,
scripted replies, and record isolation — is pinned here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from model_provider_contract import ModelProviderContract
from pydantic import ValidationError

from ai_assistant.core.errors import ModelError
from ai_assistant.core.types import Message, Role
from ai_assistant.testing import FakeModelProvider

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.core.protocols import ModelProvider


class TestFakeModelProviderContract(ModelProviderContract):
    """Runs FakeModelProvider through the shared ModelProvider conformance suite."""

    @pytest.fixture
    def provider(self) -> ModelProvider:
        return FakeModelProvider()


async def test_a_refused_call_records_nothing() -> None:
    # ADR-0066 §6: a refused call must be inert. The fake makes that sharp,
    # because ``complete`` validates, *then* records, *then* evaluates the reply —
    # a check placed after the record would append a ModelCall for a request that
    # was rejected and put every ``call_count`` assertion above it off by one.
    # Every refused shape is checked, since position is a property of the method
    # rather than of any one check.
    provider = FakeModelProvider()
    refused: list[list[Message]] = [
        [],
        [Message(role=Role.USER, content="u"), Message(role=Role.ASSISTANT, content="cached")],
        [Message(role=Role.ASSISTANT, content="lone")],
        [Message(role=Role.TOOL, content="result")],
    ]

    for history in refused:
        with pytest.raises(ModelError):
            await provider.complete(history)

    assert provider.calls == []
    assert provider.call_count == 0


async def test_a_refused_call_does_not_advance_a_scripted_sequence() -> None:
    # The other half of inertness, and the one that corrupts a *later* assertion
    # rather than an earlier one: a refusal that popped the queue would leave the
    # next valid call returning the reply the refused one ate (ADR-0066 §6).
    provider = FakeModelProvider.scripted("first", "second")

    with pytest.raises(ModelError):
        await provider.complete(
            [
                Message(role=Role.USER, content="u"),
                Message(role=Role.ASSISTANT, content="cached"),
            ]
        )

    assert (await provider.complete([Message(role=Role.USER, content="go")])).content == "first"


async def test_a_conversation_awaiting_nothing_is_rejected_like_the_real_provider() -> None:
    # This *is* a shared-contract requirement now (ADR-0066), and the suite above
    # asserts the disposition on both implementations. Pinned again here for the
    # message, and because this is the shape the two used to disagree about: the
    # real provider echoed the trailing turn back without calling a model at all,
    # while the fake answered it normally — so a subsystem built against the fake
    # got behaviour production did not have. That divergence is why the promise
    # binds the Protocol rather than one class.
    provider = FakeModelProvider()

    with pytest.raises(ModelError, match="already ends with an assistant turn"):
        await provider.complete(
            [
                Message(role=Role.USER, content="u"),
                Message(role=Role.ASSISTANT, content="cached reply"),
            ]
        )


async def test_empty_conversation_is_rejected_like_the_real_provider() -> None:
    # Also a shared-contract requirement since ADR-0066 promoted it; kept here for
    # the parity statement, which the shared suite cannot make — that suite holds
    # each implementation to the contract, not the fake to PydanticAIProvider.
    provider = FakeModelProvider()

    with pytest.raises(ModelError, match="at least one message"):
        await provider.complete([])


async def test_constant_reply_is_returned_verbatim() -> None:
    provider = FakeModelProvider("always this")

    reply = await provider.complete([Message(role=Role.USER, content="anything")])

    assert reply.content == "always this"


async def test_callable_reply_sees_the_conversation() -> None:
    provider = FakeModelProvider(lambda messages: f"got {len(messages)} messages")

    reply = await provider.complete(
        [
            Message(role=Role.USER, content="one"),
            Message(role=Role.ASSISTANT, content="two"),
            Message(role=Role.USER, content="three"),
        ]
    )

    assert reply.content == "got 3 messages"


async def test_tool_role_message_is_rejected_like_the_real_provider() -> None:
    # Not a shared-contract requirement (tool support is implementation-specific),
    # but the fake mirrors PydanticAIProvider's rejection so orchestration code
    # cannot pass against the fake and fail in production.
    provider = FakeModelProvider()

    with pytest.raises(ModelError, match="tool-role"):
        await provider.complete([Message(role=Role.TOOL, content="result")])


async def test_callable_reply_failure_is_wrapped_in_model_error() -> None:
    # A failing reply simulates a model failure; mirror PydanticAIProvider so
    # code catching ModelError recovers identically against the fake.
    def boom(_messages: Sequence[Message]) -> str:
        msg = "reply exploded"
        raise RuntimeError(msg)

    provider = FakeModelProvider(boom)

    with pytest.raises(ModelError, match="model completion failed"):
        await provider.complete([Message(role=Role.USER, content="hi")])


async def test_callable_reply_assertion_error_is_wrapped_not_leaked() -> None:
    # Only scripted exhaustion is exempt; an ordinary AssertionError from a reply
    # is wrapped like any other failure, so it cannot bypass ModelError recovery.
    def boom(_messages: Sequence[Message]) -> str:
        msg = "not an exhaustion"
        raise AssertionError(msg)

    provider = FakeModelProvider(boom)

    with pytest.raises(ModelError, match="model completion failed"):
        await provider.complete([Message(role=Role.USER, content="hi")])


async def test_scripted_returns_each_reply_in_order_then_raises() -> None:
    provider = FakeModelProvider.scripted("first", "second")
    turn = [Message(role=Role.USER, content="go")]

    assert (await provider.complete(turn)).content == "first"
    assert (await provider.complete(turn)).content == "second"
    with pytest.raises(AssertionError, match="ran out of replies"):
        await provider.complete(turn)


async def test_calls_record_the_conversation_and_model_override() -> None:
    provider = FakeModelProvider()

    await provider.complete([Message(role=Role.USER, content="hi")], model="prov:model")

    assert provider.call_count == 1
    call = provider.calls[0]
    assert call.model == "prov:model"
    assert [m.content for m in call.messages] == ["hi"]
    assert provider.last_messages == call.messages


async def test_recorded_calls_cannot_be_corrupted_by_caller_mutation() -> None:
    provider = FakeModelProvider()
    sent = [Message(role=Role.USER, content="original")]

    await provider.complete(sent)
    # `Message` is frozen (ADR-0068), so a caller reusing its list cannot rewrite
    # a recorded turn's content after the call.
    with pytest.raises(ValidationError):
        sent[0].content = "mutated after the call"

    assert provider.calls[0].messages[0].content == "original"
