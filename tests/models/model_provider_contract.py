"""Shared conformance suite for the ModelProvider Protocol.

Every ``ModelProvider`` implementation must pass this suite (CONTRIBUTING,
"Protocol conformance suites"). A concrete test subclasses
:class:`ModelProviderContract` and overrides the ``provider`` fixture; the suite
asserts only behaviour that is *universal* to the contract — that a completion
comes back as an assistant :class:`~ai_assistant.core.types.Message`, and which
conversations ``complete()`` will answer at all (ADR-0066) — not what any one
model actually says, which stays in the per-implementation test modules.

Named ``*_contract`` (not ``test_*``) so pytest collects it only via a
``Test``-prefixed subclass, never the abstract base directly.
"""

from __future__ import annotations

import pytest

from ai_assistant.core.errors import ModelError
from ai_assistant.core.protocols import ModelProvider
from ai_assistant.core.types import Message, Role

#: The shapes ADR-0066 §1's precondition refuses, as role sequences.
#:
#: The lone assistant turn is not a redundant copy of the two-message case: a
#: plausible ``len(messages) > 1 and messages[-1].role is Role.ASSISTANT`` guard
#: passes the two-message case and leaves this one live, and ADR-0066's Context
#: verified it echoes on its own.
_REFUSED_SHAPES = [
    pytest.param([], id="empty"),
    pytest.param([Role.USER, Role.ASSISTANT], id="ends-on-assistant"),
    pytest.param([Role.ASSISTANT], id="lone-assistant"),
]


def _history(roles: list[Role]) -> list[Message]:
    """Build a conversation of ``roles``, one message per role, in order."""
    return [Message(role=role, content=f"{role.name.lower()} turn") for role in roles]


def _conversation() -> list[Message]:
    """A multi-turn history of the system/user/assistant roles.

    Tool-role handling is intentionally excluded: the Protocol does not mandate
    it and support is implementation-specific (``PydanticAIProvider`` cannot yet
    represent a tool exchange), so it is asserted per implementation, not here.
    """
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
        # accepted without resolving a real model. That an override is actually
        # *honoured* can only be checked offline per implementation (a real
        # ``"provider:model"`` string would force network resolution), so those
        # assertions live in the per-implementation test modules.
        reply = await provider.complete([Message(role=Role.USER, content="hi")], model=None)

        assert reply.role is Role.ASSISTANT

    # ADR-0066 §1: ``complete()`` takes a conversation *awaiting an assistant
    # reply*. The two cases below pin both sides of that boundary — every shape
    # the rule refuses is refused, and the shape it admits is admitted. The
    # boundary is emptiness and the terminal turn, and only those: ``Role.TOOL``
    # is refused by both implementations for reasons prior to this ADR and
    # unchanged by it, so it stays out of the shared suite (§6).

    @pytest.mark.parametrize("roles", _REFUSED_SHAPES)
    async def test_complete_refuses_a_conversation_awaiting_nothing(
        self, provider: ModelProvider, roles: list[Role]
    ) -> None:
        # Asserted by the *raise*, deliberately, and never by an absent request:
        # "nothing went on the wire" is equally true of the defect this rule
        # exists to close (the echo made no request either), so a recorder-based
        # case here would certify the bug rather than the fix (ADR-0066 §6).
        with pytest.raises(ModelError) as caught:
            await provider.complete(_history(roles))

        # The *disposition*, not the class. ``pytest.raises(ModelError)`` alone is
        # satisfied by ModelUnavailableError, which is retryable and routable — so
        # an implementation could pass this case while RetryingProvider burned its
        # whole attempt budget and RoutingProvider walked a malformed conversation
        # down every fallback route. Identity is not asserted either: that would
        # forbid a future implementation from raising a well-behaved subclass, and
        # the flag pair was always the property (ADR-0066 §6).
        assert caught.value.retryable is False
        assert caught.value.routable is False

    async def test_complete_accepts_a_history_ending_on_a_system_turn(
        self, provider: ModelProvider
    ) -> None:
        # The other side of the boundary, and the reason it is worth a case: the
        # rule is "does not end on an assistant turn", *not* "ends on a user
        # turn". Every other positive case in this suite ends on a user turn, so
        # an implementation that wrote the over-broad ``if messages[-1].role is
        # not Role.USER: raise`` would satisfy the refusals and the conversation
        # cases alike while rejecting a call that works today — verified against
        # both real vendor stacks, which issue a request for this history
        # (ADR-0066 §1).
        reply = await provider.complete(_history([Role.USER, Role.SYSTEM]))

        assert reply.role is Role.ASSISTANT
        assert isinstance(reply.content, str)
