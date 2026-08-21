"""``FakeStreamingCompleter`` through the shared ``StreamingCompleter`` suite.

The canonical fake's binding, and the one the Protocol-triad check
(``tests/core/test_protocol_triad.py``) reads: without a ``Test…Contract``
subclass whose subject fixture supplies the fake and whose inherited obligations
actually ran, the fake is unverified however many files exist.

This is also the binding that carries the boundary cases, because the fake is
deliberately the double that *would* substitute if permitted (ADR-0173 §14). The
provider-backed binding substitutes at no point and satisfies those obligations
by reduction; here they run for real.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest
from streaming_completer_contract import StreamingCompleterContract, Turn, closing

from ai_assistant.core.errors import ModelError
from ai_assistant.core.types import Message, Role
from ai_assistant.testing import (
    DEFAULT_STREAM_DELTAS,
    DEFAULT_STREAM_REPLY,
    FakeStreamingCompleter,
    StreamAttempt,
)

if TYPE_CHECKING:
    from ai_assistant.core.protocols import StreamingCompleter


@dataclass(frozen=True)
class _FakeWorld:
    """The suite's world over a :class:`FakeStreamingCompleter`.

    The fake plays its own script, so the world is a thin reading of it: an
    attempt is a recorded :class:`~ai_assistant.testing.StreamCall`, and what an
    attempt observed is the snapshot ``stream`` took on the call.
    """

    subject: FakeStreamingCompleter

    @property
    def completer(self) -> StreamingCompleter:
        return self.subject

    @property
    def attempts(self) -> int:
        return self.subject.attempt_count

    @property
    def observed(self) -> tuple[tuple[Turn, ...], ...]:
        return tuple(
            tuple((message.role, message.content, message.name) for message in call.messages)
            for call in self.subject.calls
        )

    @property
    def released(self) -> int:
        return self.subject.released


class TestFakeStreamingCompleterContract(StreamingCompleterContract):
    """``FakeStreamingCompleter`` passes the shared ``StreamingCompleter`` contract."""

    #: The fake substitutes, on purpose: ADR-0173 §14 asks for the boundary to be
    #: "asserted against a double that would substitute if permitted", and a
    #: cooperative fake would certify a commit-at-any-delta implementation.
    substitutes_before_commit = True

    @pytest.fixture
    def completer(self) -> StreamingCompleter:
        return FakeStreamingCompleter()

    def world(self, *attempts: StreamAttempt) -> _FakeWorld:
        return _FakeWorld(subject=FakeStreamingCompleter(script=attempts))


class TestTheFakeBeyondTheContract:
    """What the fake promises its own users, over and above the shared contract."""

    async def test_an_unscripted_fake_streams_its_default_reply(self) -> None:
        completer = FakeStreamingCompleter()

        deltas = [
            delta async for delta in completer.stream([Message(role=Role.USER, content="hi")])
        ]

        assert tuple(deltas) == DEFAULT_STREAM_DELTAS
        assert "".join(deltas) == DEFAULT_STREAM_REPLY

    async def test_yielding_scripts_one_successful_attempt(self) -> None:
        completer = FakeStreamingCompleter.yielding("hello", " ", "world")

        deltas = [
            delta async for delta in completer.stream([Message(role=Role.USER, content="hi")])
        ]

        # The interleaved case ADR-0173 §5 names: the blank delta is a separator
        # the model emitted, so the fake yields it rather than filtering it, and
        # a caller that drops it would produce "helloworld".
        assert deltas == ["hello", " ", "world"]

    async def test_a_refused_call_consumes_no_scripted_attempt(self) -> None:
        completer = FakeStreamingCompleter.yielding("the only answer")

        with pytest.raises(ModelError):
            completer.stream([])

        deltas = [
            delta async for delta in completer.stream([Message(role=Role.USER, content="hi")])
        ]

        assert completer.attempt_count == 1
        assert "".join(deltas) == "the only answer"

    def test_a_refusal_reaches_a_caller_that_never_iterates(self) -> None:
        # The fake validates on the call rather than on the first iteration step,
        # which the Protocol permits either way — pinned here so a change of shape
        # is a deliberate one and not a silent regression for a caller that builds
        # the iterator before it drives it.
        completer = FakeStreamingCompleter()

        with pytest.raises(ModelError):
            completer.stream([Message(role=Role.ASSISTANT, content="already answered")])

    async def test_running_out_of_attempts_raises_the_last_failure(self) -> None:
        completer = FakeStreamingCompleter(
            script=(
                StreamAttempt(deltas=("",), fails=True),
                StreamAttempt(deltas=("  ",), fails=True),
            )
        )

        with pytest.raises(ModelError):
            _ = [delta async for delta in completer.stream([Message(role=Role.USER, content="hi")])]

        assert completer.attempt_count == 2

    async def test_an_abandoned_stream_is_held_until_it_is_closed(self) -> None:
        # What a consumer testing against the fake will see, which the shared
        # suite deliberately does not require of every implementation: the fake
        # produces nothing ahead of its reader, so an abandoned-but-unclosed
        # stream really is still holding its attempt. A consumer whose early-stop
        # handling forgets to close is caught here rather than in production.
        completer = FakeStreamingCompleter.yielding("one", "two", "three")
        stream = completer.stream([Message(role=Role.USER, content="hi")])

        async for _delta in stream:
            break

        assert completer.released == 0

        async with closing(stream):
            pass

        assert completer.released == 1

    async def test_the_snapshot_is_taken_on_the_call(self) -> None:
        completer = FakeStreamingCompleter.yielding("answer")
        conversation = [Message(role=Role.USER, content="hi")]

        stream = completer.stream(conversation)
        conversation.append(Message(role=Role.USER, content="wait, actually"))
        _ = [delta async for delta in stream]

        assert completer.last_messages == (Message(role=Role.USER, content="hi"),)
