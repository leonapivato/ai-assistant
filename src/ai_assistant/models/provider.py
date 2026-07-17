"""A :class:`~ai_assistant.core.protocols.ModelProvider` backed by pydantic-ai.

This is the one place a provider SDK is reached (indirectly, via pydantic-ai),
so the rest of the system stays model-agnostic. The adapter's only jobs are to
translate our provider-independent :class:`~ai_assistant.core.types.Message`
list into pydantic-ai's message history, drive a single completion, and
translate the result (and any failure) back into our own types.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic_ai import Agent, models
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    SystemPromptPart,
    TextPart,
    UserPromptPart,
)

from ai_assistant.core.errors import ModelError
from ai_assistant.core.types import Message, Role

if TYPE_CHECKING:
    from collections.abc import Sequence

    from pydantic_ai.messages import ModelMessage, ModelRequestPart


def _to_model_messages(messages: Sequence[Message]) -> list[ModelMessage]:
    """Translate our flat message list into pydantic-ai message history.

    Consecutive request-side turns (system, user) are grouped into a single
    :class:`ModelRequest`; each assistant turn becomes a :class:`ModelResponse`.

    Args:
        messages: Conversation history in our provider-independent form.

    Returns:
        The equivalent pydantic-ai ``ModelMessage`` history.

    Raises:
        ModelError: If a tool-role message is encountered; tool exchanges are
            not yet representable at this layer (they need a tool-call id).
    """
    history: list[ModelMessage] = []
    pending: list[ModelRequestPart] = []

    def flush() -> None:
        if pending:
            history.append(ModelRequest(parts=list(pending)))
            pending.clear()

    for message in messages:
        match message.role:
            case Role.SYSTEM:
                pending.append(SystemPromptPart(content=message.content))
            case Role.USER:
                pending.append(UserPromptPart(content=message.content))
            case Role.ASSISTANT:
                flush()
                history.append(ModelResponse(parts=[TextPart(content=message.content)]))
            case Role.TOOL:
                msg = "tool-role messages are not yet supported by PydanticAIProvider"
                raise ModelError(msg)

    flush()
    return history


class PydanticAIProvider:
    """Model-agnostic completion client implemented on top of pydantic-ai.

    Structurally implements :class:`~ai_assistant.core.protocols.ModelProvider`.
    The default model may be a ``"provider:model"`` string (the production path)
    or a pydantic-ai :class:`~pydantic_ai.models.Model` instance (used by tests
    to inject a deterministic fake without network access).
    """

    def __init__(self, default_model: models.Model | str) -> None:
        """Initialise the provider.

        Args:
            default_model: The model used when a call does not override it,
                either as a pydantic-ai ``"provider:model"`` name or a
                pre-built ``Model`` instance.
        """
        self._default_model = default_model
        # ``defer_model_check`` keeps construction offline: a string model is
        # only resolved (and credentials required) at first completion.
        self._agent: Agent[None, str] = Agent(model=default_model, defer_model_check=True)

    async def complete(
        self,
        messages: Sequence[Message],
        *,
        model: str | None = None,
    ) -> Message:
        """Produce the assistant's next message given the conversation so far.

        Args:
            messages: Conversation history, oldest first. Must be non-empty.
            model: Optional ``"provider:model"`` override; falls back to the
                configured default when ``None``.

        Returns:
            The assistant's reply as a :class:`~ai_assistant.core.types.Message`.

        Raises:
            ModelError: If ``messages`` is empty or the provider call fails.
        """
        if not messages:
            msg = "complete() requires at least one message"
            raise ModelError(msg)

        history = _to_model_messages(messages)

        try:
            result = await self._agent.run(
                user_prompt=None,
                message_history=history,
                model=model,
            )
        except Exception as exc:
            msg = f"model completion failed: {exc}"
            raise ModelError(msg) from exc

        return Message(role=Role.ASSISTANT, content=result.output)
