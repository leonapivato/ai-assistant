"""A :class:`~ai_assistant.core.protocols.ModelProvider` backed by pydantic-ai.

This is the one place a provider SDK is reached (indirectly, via pydantic-ai),
so the rest of the system stays model-agnostic. The adapter's only jobs are to
translate our provider-independent :class:`~ai_assistant.core.types.Message`
list into pydantic-ai's message history, drive a single completion, and
translate the result (and any failure) back into our own types.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from pydantic_ai import Agent, models
from pydantic_ai.exceptions import (
    ContentFilterError,
    ModelAPIError,
    ModelHTTPError,
    UnexpectedModelBehavior,
)
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    SystemPromptPart,
    TextPart,
    UserPromptPart,
)

from ai_assistant.core.errors import (
    ModelAuthError,
    ModelContentFilterError,
    ModelError,
    ModelRateLimitError,
    ModelResponseError,
    ModelTimeoutError,
    ModelUnavailableError,
)
from ai_assistant.core.types import Message, Role

_HTTP_UNAUTHORIZED: Final = 401
_HTTP_FORBIDDEN: Final = 403
_HTTP_REQUEST_TIMEOUT: Final = 408
_HTTP_TOO_MANY_REQUESTS: Final = 429
_HTTP_SERVER_ERROR: Final = 500

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


def _classify_status(status_code: int, message: str) -> ModelError:
    """Map an HTTP status from the provider onto the error taxonomy.

    Args:
        status_code: The status code the provider returned.
        message: The already-formatted message for the resulting error.

    Returns:
        The most specific :class:`ModelError` subclass for ``status_code``.
    """
    if status_code in (_HTTP_UNAUTHORIZED, _HTTP_FORBIDDEN):
        return ModelAuthError(message)
    if status_code == _HTTP_TOO_MANY_REQUESTS:
        return ModelRateLimitError(message)
    if status_code == _HTTP_REQUEST_TIMEOUT:
        return ModelTimeoutError(message)
    if status_code >= _HTTP_SERVER_ERROR:
        return ModelUnavailableError(message)
    # Any other 4xx is a malformed request on our side: retrying is pointless.
    return ModelError(message)


def _classify(exc: Exception) -> ModelError:
    """Translate a pydantic-ai failure into our own error taxonomy.

    Every failure is still wrapped as a :class:`ModelError`, so the contract
    that ``complete`` raises only ``ModelError`` is unchanged; this only narrows
    the subclass. Unrecognised failures stay a bare, non-retryable
    ``ModelError`` — misclassifying something as retryable is worse than not
    classifying it at all.

    Args:
        exc: The exception pydantic-ai raised during a completion.

    Returns:
        The most specific :class:`ModelError` subclass for ``exc``.
    """
    message = f"model completion failed: {exc}"
    # Ordering matters: each pattern must precede its own base class.
    match exc:
        case ModelHTTPError():
            return _classify_status(exc.status_code, message)
        case ContentFilterError():
            return ModelContentFilterError(message)
        case UnexpectedModelBehavior():
            return ModelResponseError(message)
        case ModelAPIError():
            # Reached the provider layer but never got a status code — i.e. a
            # connection-level failure. A transport *timeout* also lands here,
            # not on the arm below: an SDK wraps it (e.g. anthropic's
            # APITimeoutError, a subclass of APIConnectionError) and pydantic-ai
            # re-raises it as ModelAPIError. Retryable either way, so the
            # behaviour is right; only the label is coarse. Classifying it as a
            # timeout would mean importing httpx here and depending on it
            # directly — deferred until streaming, where pydantic-ai does let
            # bare httpx errors escape from chunk reads.
            return ModelUnavailableError(message)
        case TimeoutError():
            # Our own deadline, not the provider's: asyncio.timeout() raises the
            # builtin TimeoutError. Nothing raises this today — it is here for
            # the timeout/retry slice that wraps this call.
            return ModelTimeoutError(message)
        case _:
            return ModelError(message)


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
            ModelError: If ``messages`` is empty or the provider call fails. A
                provider failure is narrowed to the most specific subclass
                (e.g. :class:`~ai_assistant.core.errors.ModelRateLimitError`),
                whose ``retryable`` attribute says whether another attempt could
                succeed.
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
            raise _classify(exc) from exc

        return Message(role=Role.ASSISTANT, content=result.output)
