"""A :class:`~ai_assistant.core.protocols.StreamingCompleter` backed by pydantic-ai.

The streaming sibling of :mod:`ai_assistant.models.provider`, and the second
place the vendor is reached (indirectly, via pydantic-ai) so the rest of the
system stays model-agnostic. ADR-0173 §5's Context named the gap this closes: the
library underneath does stream, and ``PydanticAIProvider`` uses only
``Agent.run()``.

**It is a separate class rather than a method on ``PydanticAIProvider``**,
because ADR-0173 §5 makes ``StreamingCompleter`` a separate Protocol and the
composition root injects one implementation of each. Nothing forbids one object
implementing both; keeping them apart is what lets a deployment stream through a
route it does not complete through, and keeps ``PydanticAIProvider``'s single
member single.

**Nothing here retries, re-routes or re-issues.** ADR-0173 §5 permits an
implementation to substitute freely until its first non-blank delta and never
after; this one substitutes at no point at all, which satisfies the clause the
strong way. That is not an accident of simplicity — ADR-0013 §3 wires
``RoutingProvider(RetryingProvider(PydanticAIProvider))`` around *completions*,
and ADR-0173 §5 is explicit that neither wrapper can forward a stream, so a
streaming route has no fallback and this module does not invent one. A caller
that wants the fallback calls ``ModelProvider.complete``.
"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pydantic_ai import Agent

from ai_assistant.core.errors import ModelError, ModelResponseError
from ai_assistant.core.types import Role, encodable_text
from ai_assistant.models.provider import _classify, _to_model_messages

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence

    from pydantic_ai import models
    from pydantic_ai.messages import ModelMessage

    from ai_assistant.core.types import EncodableText, Message


def _encodable(delta: str) -> EncodableText:
    """Refuse a delta with no UTF-8 encoding, **at the seam** (ADR-0173 §5, §14).

    ADR-0085 §4c's rule binds at this seam as it binds at
    ``ModelProvider.complete``'s, whose ``Message.content`` is already
    :data:`~ai_assistant.core.types.EncodableText`. Refusing here rather than
    leaving it to the caller's own construction is what keeps a lone surrogate
    from surfacing as a pydantic ``ValidationError`` several layers above the
    thing that produced it.

    :class:`~ai_assistant.core.errors.ModelResponseError` for its disposition:
    routable, because another provider may not emit half a character, and not
    retryable, because the same route reproduces it. Past the commit boundary a
    caller acts on neither (ADR-0173 §5).

    Raises:
        ModelResponseError: If ``delta`` has no UTF-8 encoding.
    """
    try:
        return encodable_text(delta)
    except ValueError as exc:
        msg = f"the model streamed a delta that cannot be encoded: {exc}"
        raise ModelResponseError(msg) from exc


@dataclass(frozen=True)
class _Delta:
    """One text delta the run produced."""

    text: str


@dataclass(frozen=True)
class _Failed:
    """The run ended by raising, carrying the failure unclassified."""

    error: Exception


@dataclass(frozen=True)
class _Ended:
    """The run ended normally, with no further deltas."""


#: What crosses the queue between the run and the consumer yielding from it.
#: Three cases and no fourth: a stream either produces a delta, fails, or ends,
#: and making the terminal states values rather than a sentinel is what lets the
#: consumer's ``match`` be exhaustive for mypy.
type _Streamed = _Delta | _Failed | _Ended


class PydanticAIStreamingCompleter:
    """Streaming completion client implemented on top of pydantic-ai.

    Structurally implements
    :class:`~ai_assistant.core.protocols.StreamingCompleter`. The default model
    may be a ``"provider:model"`` string (the production path) or a pydantic-ai
    :class:`~pydantic_ai.models.Model` instance (used by tests to inject a
    deterministic fake without network access), exactly as
    :class:`~ai_assistant.models.provider.PydanticAIProvider`'s is.
    """

    def __init__(self, default_model: models.Model | str) -> None:
        """Initialise the completer.

        Args:
            default_model: The model used when a call does not override it,
                either as a pydantic-ai ``"provider:model"`` name or a pre-built
                ``Model`` instance.
        """
        self._default_model = default_model
        # ``defer_model_check`` keeps construction offline, as it does for the
        # completing provider: a string model is resolved (and credentials
        # required) at the first stream rather than at wiring time.
        self._agent: Agent[None, str] = Agent(model=default_model, defer_model_check=True)

    def stream(
        self,
        messages: Sequence[Message],
        *,
        model: str | None = None,
    ) -> AsyncIterator[EncodableText]:
        """Stream the assistant's next message as text deltas, oldest first.

        Both malformed-argument shapes ADR-0066 §1 names are refused here, before
        :class:`Agent` is reached, and so is a ``Role.TOOL`` turn — the same
        boundary ``PydanticAIProvider.complete`` draws, for the same reasons. The
        trailing-assistant case is the one with teeth: pydantic-ai resolves a
        history whose last entry is already a response as a *finished* run, so it
        would replay that assistant turn's text as a stream without a round trip —
        an echo indistinguishable from a real answer (ADR-0066 §2, issue #351).

        **The conversation is rendered on the call**, not on the first iteration
        step, which is this seam's discharge of ADR-0065: everything the stream
        goes on to send derives from that one observation, so a caller mutating
        its own list while the stream is suspended cannot tear the request. The
        refusals therefore reach a caller that never iterates.

        Args:
            messages: Conversation history, oldest first. Must be non-empty, and
                must not end on a ``Role.ASSISTANT`` turn.
            model: Optional ``"provider:model"`` override; falls back to the
                configured default when ``None``.

        Returns:
            An async iterator over the reply's text deltas, in order.

        Raises:
            ModelError: If ``messages`` is empty, ends on a ``Role.ASSISTANT``
                turn, or contains a tool-role message. The bare class — neither
                retryable nor routable, which is the disposition the Protocol
                requires — because a caller fixes those at the call site rather
                than by trying again. A provider failure, or a delta with no UTF-8
                encoding, is raised from the iteration and narrowed to the most
                specific subclass.
        """
        if not messages:
            msg = "stream() requires at least one message"
            raise ModelError(msg)
        if messages[-1].role is Role.ASSISTANT:
            msg = (
                "stream() requires a conversation awaiting a reply; this "
                "history already ends with an assistant turn"
            )
            raise ModelError(msg)

        # `_to_model_messages` raises the bare `ModelError` for a `Role.TOOL`
        # turn, so the tool refusal rides the render and is not a fourth branch
        # here that could drift from the completing provider's.
        history = _to_model_messages(messages)
        return self._stream(history, model=model)

    async def _stream(
        self, history: list[ModelMessage], *, model: str | None
    ) -> AsyncIterator[EncodableText]:
        """Yield the run's deltas, driving the run itself in a task beside them.

        **The run is not held open across a ``yield``, and that indirection is the
        whole of this method.** The obvious shape — ``async with
        agent.run_stream(...)`` wrapped directly around ``yield`` — is broken
        under early termination and fails ADR-0060's resource clause. pydantic-ai
        drives a streamed run inside anyio cancel scopes, and unwinding those from
        inside an async generator that is being *closed* means awaiting during
        ``GeneratorExit``: ``aclose()`` on a partially consumed stream raises
        ``RuntimeError: coroutine ignored GeneratorExit`` and the run's teardown
        does not complete. A consumer that stops reading — a client that
        disconnected, a composing stage that hit ADR-0173 §3's ceiling — is the
        ordinary case here, not the exotic one.

        Running the exchange in its own task fixes it at the root: the task
        unwinds under an ordinary ``CancelledError``, which is exactly what
        anyio's scopes are built to take, and the generator's own cleanup only has
        to cancel it and watch it finish. That is ADR-0060's clause read
        literally — at the moment ``CancelledError`` leaves this method the run is
        "still held exclusively by work the method started and can observe
        finishing", and then it is released.

        ``debounce_by=None`` rather than pydantic-ai's default of 0.1 seconds.
        The default groups deltas arriving inside a window and emits them
        together, which delays the *first* word by up to that window — and time to
        first word is the entire product benefit ADR-0173 exists to buy. Grouping
        is the caller's job in any case: ADR-0173 §5 makes a delta's shape
        unpromised and coalescing the composing stage's, which has the chunk
        ceiling and the text-preservation rule that a transport-level debounce
        knows nothing about.
        """
        # Depth one, so the run stays at most one delta ahead of the consumer.
        # Unbounded would buffer a whole answer for a caller that stalled, and
        # this seam has no ceiling of its own to bound that by (ADR-0173 §3 puts
        # the ceiling above it, on the engine).
        deltas: asyncio.Queue[_Streamed] = asyncio.Queue(maxsize=1)
        run = asyncio.create_task(self._pump(history, model=model, deltas=deltas))
        try:
            while True:
                match await deltas.get():
                    case _Delta(text=text):
                        yield _encodable(text)
                    case _Failed(error=error):
                        raise _classify(error) from error
                    case _Ended():
                        return
        finally:
            run.cancel()
            # Suppressed because this cancellation is one we asked for, and a
            # `finally` re-raises whatever it was unwinding — so a cancellation
            # delivered from outside is still delivered onward (ADR-0060), it is
            # merely not delivered *twice*.
            with contextlib.suppress(asyncio.CancelledError):
                await run

    async def _pump(
        self,
        history: list[ModelMessage],
        *,
        model: str | None,
        deltas: asyncio.Queue[_Streamed],
    ) -> None:
        """Drive one streamed run, posting each delta and then how it ended.

        The failure is posted **unclassified**. Classification belongs to the
        consumer so that a narrowed subclass raised there — ``_encodable``'s
        refusal — cannot be flattened by passing back through ``_classify``, and
        so that the traceback the caller sees is chained from the exception rather
        than from a queue.

        ``CancelledError`` is re-raised rather than posted: it is not this run's
        answer, it is the consumer having gone away, and posting it would block on
        a queue nobody is reading.
        """
        try:
            async with self._agent.run_stream(
                user_prompt=None,
                message_history=history,
                model=model,
            ) as result:
                async for delta in result.stream_text(delta=True, debounce_by=None):
                    await deltas.put(_Delta(delta))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # Broad on purpose: `_classify` is the taxonomy, and its default for an
            # unrecognised failure is the conservative bare `ModelError` (ADR-0063).
            await deltas.put(_Failed(exc))
        else:
            await deltas.put(_Ended())
