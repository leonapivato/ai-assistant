"""A canonical :class:`~ai_assistant.core.protocols.ModelProvider` fake.

The shared test double for the ``ModelProvider`` contract, so a subsystem that
drives the model (orchestration, planning, ...) can test against a real,
contract-correct provider *without importing the models subsystem's internals*
(CLAUDE.md golden rule 1) and without touching the network. It lives in
``ai_assistant.testing`` so it is importable from any test while staying out of
production code paths (``lint-imports`` forbids production modules from importing
it).

It is deliberately minimal: it never calls a real model. The reply is either a
constant string or a callable over the conversation, and every call is recorded
so a test can assert what a subsystem sent to the model. For a scripted
multi-turn exchange use :meth:`FakeModelProvider.scripted`. Only the behaviour
asserted by the shared ``ModelProvider`` conformance suite is part of the
contract; the recording and scripting helpers are conveniences on top.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ai_assistant.core.errors import ModelError
from ai_assistant.core.types import Message, Role

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

_DEFAULT_REPLY = "fake model reply"


@dataclass(frozen=True)
class ModelCall:
    """One recorded call to a :class:`FakeModelProvider`.

    Attributes:
        messages: The conversation passed to ``complete``, as an independent
            snapshot (deep-copied on record, so later caller mutation cannot
            reach it).
        model: The per-call ``"provider:model"`` override, or ``None``.
    """

    messages: tuple[Message, ...]
    model: str | None


class FakeModelProvider:
    """A deterministic, offline ``ModelProvider`` test double.

    Structurally implements
    :class:`~ai_assistant.core.protocols.ModelProvider`. Each ``complete`` call
    is appended to :attr:`calls`; the reply is produced by ``reply`` — a constant
    string, or a callable mapping the conversation to the assistant's content.
    """

    def __init__(
        self,
        reply: str | Callable[[Sequence[Message]], str] = _DEFAULT_REPLY,
    ) -> None:
        """Create a provider that answers with ``reply``.

        Args:
            reply: Either a constant string returned for every call, or a
                callable given the conversation (oldest first) that returns the
                assistant's content. Defaults to a fixed placeholder reply.
        """
        self._reply = reply
        self.calls: list[ModelCall] = []

    @classmethod
    def scripted(cls, *replies: str) -> FakeModelProvider:
        """A provider that returns each of ``replies`` in turn, then raises.

        Use for multi-step exchanges where each model turn is known in advance.
        Calling ``complete`` more times than there are replies is a test-authoring
        error and raises :class:`AssertionError`.

        Args:
            replies: The assistant contents to return, in call order.
        """
        queue: deque[str] = deque(replies)

        def next_reply(_messages: Sequence[Message]) -> str:
            if not queue:
                msg = "FakeModelProvider.scripted ran out of replies"
                raise AssertionError(msg)
            return queue.popleft()

        return cls(reply=next_reply)

    async def complete(
        self,
        messages: Sequence[Message],
        *,
        model: str | None = None,
    ) -> Message:
        """Record the call and return the configured assistant reply.

        Args:
            messages: Conversation history, oldest first. Must be non-empty.
            model: Optional ``"provider:model"`` override; recorded but otherwise
                ignored (the fake has no real model to switch).

        Returns:
            The assistant's reply as a
            :class:`~ai_assistant.core.types.Message`.

        Raises:
            ModelError: If ``messages`` is empty — matching ``PydanticAIProvider``,
                so code exercised with this fake cannot pass on an empty
                conversation that the real provider would reject.
        """
        if not messages:
            msg = "complete() requires at least one message"
            raise ModelError(msg)

        snapshot = tuple(m.model_copy(deep=True) for m in messages)
        self.calls.append(ModelCall(messages=snapshot, model=model))
        reply = self._reply
        content = reply(messages) if callable(reply) else reply
        return Message(role=Role.ASSISTANT, content=content)

    @property
    def call_count(self) -> int:
        """How many times ``complete`` has been called."""
        return len(self.calls)

    @property
    def last_messages(self) -> tuple[Message, ...]:
        """The conversation from the most recent ``complete`` call.

        Raises:
            IndexError: If ``complete`` has not been called yet.
        """
        return self.calls[-1].messages
