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

from ai_assistant.core.errors import ModelError
from ai_assistant.core.types import Message, Role
from ai_assistant.testing import FakeModelProvider

if TYPE_CHECKING:
    from ai_assistant.core.protocols import ModelProvider


class TestFakeModelProviderContract(ModelProviderContract):
    """Runs FakeModelProvider through the shared ModelProvider conformance suite."""

    @pytest.fixture
    def provider(self) -> ModelProvider:
        return FakeModelProvider()


async def test_empty_conversation_is_rejected_like_the_real_provider() -> None:
    # Not a shared-contract requirement (the Protocol is silent on empty input),
    # but the fake mirrors PydanticAIProvider so code exercised against it cannot
    # pass on an empty conversation the real provider would reject.
    provider = FakeModelProvider()

    with pytest.raises(ModelError):
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


async def test_recorded_calls_are_isolated_from_caller_mutation() -> None:
    provider = FakeModelProvider()
    sent = [Message(role=Role.USER, content="original")]

    await provider.complete(sent)
    sent[0].content = "mutated after the call"  # caller keeps and mutates its list

    assert provider.calls[0].messages[0].content == "original"
