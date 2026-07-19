"""Shared conformance suite for the ModelProvider Protocol.

Every ``ModelProvider`` implementation must pass this suite (CONTRIBUTING,
"Protocol conformance suites"). A concrete test subclasses
:class:`ModelProviderContract` and overrides the ``provider`` fixture; the suite
asserts only behaviour that is *universal* to the contract — that a completion
comes back as an assistant :class:`~ai_assistant.core.types.Message` — not what
any one model actually says, which stays in the per-implementation test modules.

Named ``*_contract`` (not ``test_*``) so pytest collects it only via a
``Test``-prefixed subclass, never the abstract base directly.
"""

from __future__ import annotations

import pytest

from ai_assistant.core.protocols import ModelProvider
from ai_assistant.core.types import Message, Role


def _conversation() -> list[Message]:
    """A history exercising every request/response role a provider must accept."""
    return [
        Message(role=Role.SYSTEM, content="be terse"),
        Message(role=Role.USER, content="hi"),
        Message(role=Role.ASSISTANT, content="hello"),
        Message(role=Role.USER, content="how are you?"),
    ]


class ModelProviderContract:
    """The behavioural contract every ``ModelProvider`` implementation must satisfy."""

    @pytest.fixture
    def provider(self) -> ModelProvider:
        """Override in a subclass to supply the implementation under test."""
        raise NotImplementedError

    def test_conforms_to_protocol(self, provider: ModelProvider) -> None:
        assert isinstance(provider, ModelProvider)

    async def test_complete_returns_an_assistant_message(self, provider: ModelProvider) -> None:
        reply = await provider.complete([Message(role=Role.USER, content="hello")])

        assert isinstance(reply, Message)
        assert reply.role is Role.ASSISTANT
        assert isinstance(reply.content, str)

    async def test_complete_handles_a_multi_turn_conversation(
        self, provider: ModelProvider
    ) -> None:
        # The provider must accept a full system/user/assistant history, not just
        # a single user turn.
        reply = await provider.complete(_conversation())

        assert reply.role is Role.ASSISTANT
        assert isinstance(reply.content, str)

    async def test_complete_accepts_the_model_keyword(self, provider: ModelProvider) -> None:
        # The ``model`` override is part of the contract's surface; passing it
        # explicitly (here as ``None``, the "use the default" value) must be
        # accepted without resolving a real model.
        reply = await provider.complete([Message(role=Role.USER, content="hi")], model=None)

        assert reply.role is Role.ASSISTANT
