"""A canonical :class:`~ai_assistant.core.protocols.StructuredCompleter` fake.

The shared test double for the ``StructuredCompleter`` contract (ADR-0354 §11), so a
stage moving onto the seam can test against a real, contract-correct completer
*without importing the models subsystem's internals* (CLAUDE.md golden rule 1) and
without touching the network. It lives in ``ai_assistant.testing`` so it is
importable from any test while staying out of production code paths
(``lint-imports`` forbids production modules from importing it).

It never calls a model. Each call is answered by a scripted reply: the text the model
"wrote", read as the call's shape by :mod:`ai_assistant.core.reply_shapes`'s one rule,
exactly as the provider-backed implementation reads it, so a stage cannot pass on a
reply here that the seam would refuse. A scripted reply may instead carry a returned
failure the text alone cannot give, ``refused`` or ``cut``, and a script may hold a
:class:`~ai_assistant.core.errors.ModelError` the call raises, as a provider failure
would be raised. For a scripted sequence use :meth:`FakeStructuredCompleter.scripted`.
Only the behaviour the shared conformance suite asserts is part of the contract; the
recording and scripting helpers are conveniences on top.
"""

from __future__ import annotations

from collections import deque

# At runtime, not under TYPE_CHECKING: `StructuredAnswer` is a PEP 695 alias, whose
# value is read lazily and must resolve when it is (#1706).
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Final, Literal

from pydantic import BaseModel

from ai_assistant.core.errors import ModelError
from ai_assistant.core.reply_shapes import read_reply, reply_schema, schema_version
from ai_assistant.core.types import (
    Message,
    ReplyExchange,
    ReplyFailure,
    ReplyMode,
    ReplyUsage,
    Role,
    StructuredReply,
)

#: The ``"provider:model"`` an unscripted reply says answered.
DEFAULT_STRUCTURED_MODEL: Final = "fake:structured"

#: The finish reason each scripted outcome reports, in pydantic-ai's vocabulary, as the
#: provider-backed implementation records it.
_FINISH_REASONS: Final = {
    ReplyFailure.REFUSED: "content_filter",
    ReplyFailure.CUT: "length",
}


@dataclass(frozen=True)
class ScriptedReply:
    """One scripted response: what the model wrote, and how the response ended.

    Attributes:
        text: The reply as the model wrote it, read as the call's shape by the one
            rule unless ``failure`` is set.
        failure: ``refused`` or ``cut``, where the response is to end that way: the
            failure is returned whatever ``text`` holds, as §5:2's order puts both
            before the reply is read. ``None`` reads ``text``.
        refusal: The provider's statement of a refusal.
        refusal_category: The category the provider put a refusal in.
        usage: The tokens the response reports.
        model: The ``"provider:model"`` the response says answered.
        mode: The mode the request is reported as sent in.
    """

    text: str = ""
    failure: Literal[ReplyFailure.REFUSED, ReplyFailure.CUT] | None = None
    refusal: str | None = None
    refusal_category: str | None = None
    usage: ReplyUsage = field(default_factory=ReplyUsage)
    model: str = DEFAULT_STRUCTURED_MODEL
    mode: ReplyMode = ReplyMode.NATIVE


#: What a scripted call answers with: a reply's text, a scripted response, or a failure
#: the call raises.
type StructuredAnswer = str | ScriptedReply | ModelError

#: An answer computed from the call: its conversation and its shape.
type StructuredScript = Callable[[Sequence[Message], type[BaseModel]], StructuredAnswer]


class _ScriptExhaustedError(AssertionError):
    """A :meth:`FakeStructuredCompleter.scripted` fake ran out of answers.

    An ``AssertionError``, so it reads as a test-authoring error, and a distinct type,
    so ``complete_structured`` lets it through while wrapping every other script
    failure in ``ModelError``.
    """


@dataclass(frozen=True)
class StructuredCall:
    """One recorded call to a :class:`FakeStructuredCompleter`.

    Attributes:
        messages: The conversation passed to ``complete_structured``, as an
            independent snapshot taken before anything else is read.
        shape: The shape the reply was asked for as.
        model: The per-call ``"provider:model"`` override, or ``None``.
    """

    messages: tuple[Message, ...]
    shape: type[BaseModel]
    model: str | None


class FakeStructuredCompleter:
    """A deterministic, offline ``StructuredCompleter`` test double.

    Structurally implements
    :class:`~ai_assistant.core.protocols.StructuredCompleter`. Each accepted call is
    appended to :attr:`calls`, and its answer is produced by ``answer``.
    """

    def __init__(self, answer: StructuredAnswer | StructuredScript = "{}") -> None:
        """Create a fake answering with ``answer``.

        Args:
            answer: A constant answer for every call, or a callable given the
                conversation and the shape that returns one. An answer is a reply's
                text, a :class:`ScriptedReply`, or a ``ModelError`` the call raises.
                Defaults to the reply ``{}``, which a shape whose every field has a
                default reads as its value.
        """
        self._answer = answer
        self.calls: list[StructuredCall] = []

    @classmethod
    def scripted(cls, *answers: StructuredAnswer) -> FakeStructuredCompleter:
        """A fake that answers with each of ``answers`` in turn, then raises.

        Calling ``complete_structured`` more times than there are answers is a
        test-authoring error and raises :class:`AssertionError`.

        Args:
            answers: The answers, in call order.

        Returns:
            The scripted fake.
        """
        queue: deque[StructuredAnswer] = deque(answers)

        def next_answer(_messages: Sequence[Message], _shape: type[BaseModel]) -> StructuredAnswer:
            if not queue:
                msg = "FakeStructuredCompleter.scripted ran out of answers"
                raise _ScriptExhaustedError(msg)
            return queue.popleft()

        return cls(answer=next_answer)

    async def complete_structured[T: BaseModel](
        self,
        messages: Sequence[Message],
        shape: type[T],
        *,
        model: str | None = None,
    ) -> StructuredReply[T]:
        """Record the call and answer it as scripted, reading a reply by the one rule.

        Every refusal happens **before** the call is recorded and before ``answer``
        is evaluated, so a refused call is inert: it records nothing and does not
        advance a :meth:`scripted` queue (ADR-0066 §6).

        Args:
            messages: Conversation history, oldest first.
            shape: The pydantic model class the reply is read as.
            model: Optional ``"provider:model"`` override; recorded and otherwise
                ignored.

        Returns:
            The shape's value or a returned failure, with the exchange beside it.

        Raises:
            ModelError: The bare class if ``messages`` is empty, ends on a
                ``Role.ASSISTANT`` turn or carries a ``Role.TOOL`` turn, or
                ``shape``'s schema cannot be closed; a scripted ``ModelError`` as
                given; and the bare class where a callable ``answer`` fails.
            AssertionError: If a :meth:`scripted` fake runs out of answers.
        """
        snapshot = tuple(message.model_copy(deep=True) for message in messages)
        _refuse_malformed(snapshot)
        version = schema_version(reply_schema(shape))
        self.calls.append(StructuredCall(messages=snapshot, shape=shape, model=model))
        scripted = self._scripted(snapshot, shape)
        if isinstance(scripted, ModelError):
            raise scripted
        if isinstance(scripted, str):
            scripted = ScriptedReply(text=scripted)
        exchange = ReplyExchange(
            reply=scripted.text,
            model=scripted.model,
            mode=scripted.mode,
            finish_reason="stop" if scripted.failure is None else _FINISH_REASONS[scripted.failure],
            refusal=scripted.refusal,
            refusal_category=scripted.refusal_category,
            usage=scripted.usage,
            shape=shape.__name__,
            shape_version=version,
        )
        read = (
            scripted.failure if scripted.failure is not None else read_reply(shape, scripted.text)
        )
        if isinstance(read, ReplyFailure):
            return StructuredReply(failure=read, exchange=exchange)
        return StructuredReply(value=read, exchange=exchange)

    def _scripted(self, messages: tuple[Message, ...], shape: type[BaseModel]) -> StructuredAnswer:
        """The answer for this call, a callable's failure wrapped as a provider's is."""
        answer = self._answer
        if not callable(answer):
            return answer
        try:
            return answer(messages, shape)
        except _ScriptExhaustedError:
            raise
        except Exception as exc:
            msg = f"model completion failed: {exc}"
            raise ModelError(msg) from exc

    @property
    def call_count(self) -> int:
        """How many calls ``complete_structured`` has accepted."""
        return len(self.calls)

    @property
    def last_call(self) -> StructuredCall:
        """The most recent accepted call.

        Raises:
            IndexError: If ``complete_structured`` has accepted no call yet.
        """
        return self.calls[-1]


def _refuse_malformed(messages: tuple[Message, ...]) -> None:
    """ADR-0066 §1's precondition and the tool-role refusal (ADR-0354 §2:3).

    Raises:
        ModelError: The bare class, neither retryable nor routable.
    """
    if not messages:
        msg = "complete_structured() requires at least one message"
        raise ModelError(msg)
    if messages[-1].role is Role.ASSISTANT:
        msg = "complete_structured() requires a conversation awaiting a reply"
        raise ModelError(msg)
    if any(message.role is Role.TOOL for message in messages):
        msg = "complete_structured() carries no tool exchange"
        raise ModelError(msg)
