"""A canonical :class:`~ai_assistant.core.protocols.StreamingCompleter` fake.

The shared test double for the ``StreamingCompleter`` contract, so a subsystem
that streams an answer (orchestration's composing stage, and the wire lane above
it) can test against a real, contract-correct streaming seam *without importing
the models subsystem's internals* (CLAUDE.md golden rule 1) and without touching
the network. It lives in ``ai_assistant.testing`` so it is importable from any
test while staying out of production code paths (``lint-imports`` forbids
production modules from importing it).

**It is deliberately a double that would substitute if permitted** (ADR-0173
§14). Every other fake in this package cooperates; this one is scripted with a
*sequence of attempts* and moves to the next one on a routable failure, so the
shared conformance suite can pin ADR-0173 §5's commit boundary as a **boundary**
— a cooperative fake that never substitutes satisfies "substitution stops after
the first non-blank delta" vacuously, and would equally satisfy an implementation
that committed at the first delta of any kind, which is exactly the resilience
that clause refuses to give away for nothing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final

from ai_assistant.core.errors import ModelError, ModelResponseError, ModelUnavailableError
from ai_assistant.core.types import Role, encodable_text

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence

    from ai_assistant.core.types import EncodableText, Message

#: The deltas an unscripted fake yields, and their join.
DEFAULT_STREAM_DELTAS: Final = ("fake ", "streamed ", "reply")
DEFAULT_STREAM_REPLY: Final = "".join(DEFAULT_STREAM_DELTAS)


def _is_blank(delta: str) -> bool:
    """Whether ``delta`` carries no non-whitespace character (ADR-0173 §5).

    ``str.strip()``, deliberately, and not ``str.isspace()``: it is the same test
    :data:`~ai_assistant.core.types.NonBlankEncodableText` applies, so the seam's
    commit boundary and the type a caller builds a chunk out of can never
    disagree about whether a delta published anything. The empty string is blank
    under both and is not ``isspace()``.
    """
    return not delta.strip()


def _encodable(delta: str) -> EncodableText:
    """Refuse a delta with no UTF-8 encoding, **at the seam** (ADR-0173 §5, §14).

    The class is :class:`~ai_assistant.core.errors.ModelResponseError` here and in
    ``PydanticAIStreamingCompleter`` alike — a response we cannot use, routable
    because another provider may not emit half a character, not retryable because
    the same route reproduces it. A caller past the commit boundary ignores that
    disposition, as it ignores every other one (ADR-0173 §5).

    Raises:
        ModelResponseError: If ``delta`` has no UTF-8 encoding.
    """
    try:
        return encodable_text(delta)
    except ValueError as exc:
        msg = f"the model streamed a delta that cannot be encoded: {exc}"
        raise ModelResponseError(msg) from exc


@dataclass(frozen=True)
class StreamAttempt:
    """One scripted attempt at a stream: some deltas, then success or failure.

    Attributes:
        deltas: The text deltas this attempt yields, in order, before it ends.
            Each is yielded exactly as written — blank deltas included, since a
            blank delta is admissible at this seam and is the caller's to
            coalesce.
        fails: Whether the attempt ends by raising instead of completing. The
            failure is a :class:`~ai_assistant.core.errors.ModelUnavailableError`
            — both ``retryable`` and ``routable`` — because a failure a caller
            could *not* act on would make the commit-boundary cases below pass
            for the wrong reason: they must fail over the boundary, not over the
            disposition.
    """

    deltas: tuple[str, ...] = ()
    fails: bool = False


@dataclass(frozen=True)
class StreamCall:
    """One recorded attempt a :class:`FakeStreamingCompleter` made.

    One record per *attempt*, not per ``stream()`` call: a substituted route is a
    second attempt at one call, and the pair is what a conformance case reads to
    assert both attempts observed a single version of the caller's conversation.

    Attributes:
        messages: The conversation the attempt was handed, as an independent
            snapshot taken when ``stream`` was called.
        model: The per-call ``"provider:model"`` override, or ``None``.
    """

    messages: tuple[Message, ...]
    model: str | None


@dataclass
class FakeStreamingCompleter:
    """A deterministic, offline ``StreamingCompleter`` test double.

    Structurally implements
    :class:`~ai_assistant.core.protocols.StreamingCompleter`. Every attempt is
    appended to :attr:`calls`; what each attempt yields comes from :attr:`script`.

    **The substitution rule it implements is ADR-0173 §5's, in full.** On an
    attempt that fails it moves to the next scripted attempt only while nothing
    non-blank has been yielded *by this call*; past the first delta carrying a
    non-whitespace character it raises instead, however many attempts remain. A
    call that runs out of attempts raises the last failure.

    Attributes:
        script: The attempts, in order. Defaults to one successful attempt
            yielding :data:`DEFAULT_STREAM_DELTAS`.
        calls: One :class:`StreamCall` per attempt actually started.
    """

    script: tuple[StreamAttempt, ...] = (StreamAttempt(deltas=DEFAULT_STREAM_DELTAS),)
    calls: list[StreamCall] = field(default_factory=list)

    @classmethod
    def yielding(cls, *deltas: str) -> FakeStreamingCompleter:
        """A fake whose single attempt yields ``deltas`` and completes.

        The common case, spelled without a :class:`StreamAttempt`. Use the
        constructor's ``script`` for anything that has to fail or substitute.

        Args:
            deltas: The text deltas to yield, in order.
        """
        return cls(script=(StreamAttempt(deltas=deltas),))

    @property
    def attempt_count(self) -> int:
        """How many underlying attempts have been started, across every call."""
        return len(self.calls)

    @property
    def last_messages(self) -> tuple[Message, ...]:
        """The conversation the most recent attempt observed.

        Raises:
            IndexError: If no attempt has been started yet.
        """
        return self.calls[-1].messages

    def stream(
        self,
        messages: Sequence[Message],
        *,
        model: str | None = None,
    ) -> AsyncIterator[EncodableText]:
        """Refuse a malformed history, then stream the scripted deltas.

        The conversation is snapshotted **here**, on the call rather than on the
        first iteration step, which is this seam's discharge of ADR-0065: every
        attempt reads the one snapshot, so a caller mutating its own list while
        the stream is suspended cannot make two attempts describe two versions.

        Each rejection happens before any attempt is recorded, so a refused call
        is inert (ADR-0066 §6): it appends no :class:`StreamCall` and consumes no
        scripted attempt. Recording a refused request would leave the next valid
        call streaming the attempt the refused one ate.

        Args:
            messages: Conversation history, oldest first. Must be non-empty, and
                must not end on a ``Role.ASSISTANT`` turn.
            model: Optional ``"provider:model"`` override; recorded but otherwise
                ignored (the fake has no real model to switch).

        Returns:
            An async iterator over the scripted text deltas.

        Raises:
            ModelError: If ``messages`` is empty, ends on a ``Role.ASSISTANT``
                turn, or contains a tool-role message — each matching
                ``PydanticAIStreamingCompleter``'s failure boundary, so code
                exercised with this fake cannot pass on input differently than it
                would against the real seam. Raised from the call, so a caller
                that never iterates still sees it.
        """
        snapshot = tuple(messages)
        if not snapshot:
            msg = "stream() requires at least one message"
            raise ModelError(msg)
        if snapshot[-1].role is Role.ASSISTANT:
            msg = (
                "stream() requires a conversation awaiting a reply; this "
                "history already ends with an assistant turn"
            )
            raise ModelError(msg)
        if any(message.role is Role.TOOL for message in snapshot):
            msg = "tool-role messages are not supported"
            raise ModelError(msg)
        return self._stream(snapshot, model=model)

    async def _stream(
        self, messages: tuple[Message, ...], *, model: str | None
    ) -> AsyncIterator[EncodableText]:
        """Walk the script, substituting only while nothing non-blank has been sent."""
        committed = False
        failure: ModelError | None = None
        for attempt in self.script:
            self.calls.append(StreamCall(messages=messages, model=model))
            for delta in attempt.deltas:
                yield _encodable(delta)
                committed = committed or not _is_blank(delta)
            if not attempt.fails:
                return
            failure = ModelUnavailableError("the fake's scripted route failed")
            if committed:
                # Past the commit boundary: the caller has read real text, so a
                # second route would answer a question already half-answered.
                raise failure
        if failure is not None:
            raise failure
