"""Tests for the pydantic-ai-backed StreamingCompleter (ADR-0173 §5).

The real :class:`PydanticAIStreamingCompleter` is exercised end to end by
injecting pydantic-ai's ``FunctionModel``/``TestModel`` as the default model, so
these tests are deterministic and never touch the network — the shape
``test_provider.py`` already uses for the completing seam.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final

import pytest
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.models.test import TestModel
from pydantic_transport import rendered_turns
from streaming_completer_contract import StreamingCompleterContract, Turn, drain_into

from ai_assistant.core.errors import (
    ModelError,
    ModelRateLimitError,
    ModelResponseError,
    ModelUnavailableError,
)
from ai_assistant.core.types import Message, Role
from ai_assistant.models import PydanticAIStreamingCompleter
from ai_assistant.models.streaming import (
    _cancelled_from_outside,  # pyright: ignore[reportPrivateUsage]
)
from ai_assistant.testing import StreamAttempt

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from pydantic_ai.messages import ModelMessage
    from pydantic_ai.models.function import AgentInfo

    from ai_assistant.core.protocols import StreamingCompleter

#: The status a scripted failure carries unless a case names another. 503 is what
#: ``_classify_status`` narrows to a retryable, routable ``ModelUnavailableError``
#: — the disposition the shared suite's boundary cases are written against.
_UNAVAILABLE: Final = 503

#: Long enough that a scheduling hiccup does not fail a case, short enough that a
#: genuine hang is a failure rather than a stalled run.
_A_MOMENT: Final = 5.0


def _a_question() -> list[Message]:
    """The shortest history this seam answers."""
    return [Message(role=Role.USER, content="hi")]


async def _drain(stream: AsyncIterator[str]) -> list[str]:
    """Read a stream to exhaustion, returning every delta it yielded."""
    return [delta async for delta in stream]


@dataclass
class _ScriptedTransport:
    """A pydantic-ai ``stream_function`` that plays one attempt per invocation.

    The provider-backed analogue of the canonical fake's script. Each call to
    :meth:`stream_function` is one attempt at the model: it records the rendered
    conversation it was handed, yields that attempt's deltas, then either returns
    or raises a ``ModelHTTPError``. Running past the script's end replays its last
    attempt, so a case can script two attempts to prove the second is never
    reached without also asserting the transport's own bookkeeping.
    """

    script: tuple[StreamAttempt, ...]
    status: int = _UNAVAILABLE
    observed: list[tuple[Turn, ...]] = field(default_factory=list)
    released: int = 0

    async def stream_function(
        self, messages: list[ModelMessage], _info: AgentInfo
    ) -> AsyncIterator[str]:
        """Play the next scripted attempt, recording what it observed."""
        attempt = self.script[min(len(self.observed), len(self.script) - 1)]
        self.observed.append(rendered_turns(messages))
        try:
            for delta in attempt.deltas:
                yield delta
        finally:
            # Reached on exhaustion and on close alike, which is what makes it
            # the observable form of "the provider exchange was released": the
            # library closes this generator when the run it drives is torn down.
            self.released += 1
        if attempt.fails:
            raise ModelHTTPError(status_code=self.status, model_name="scripted", body=None)


@dataclass(frozen=True)
class _ProviderWorld:
    """The suite's world over a :class:`PydanticAIStreamingCompleter`."""

    subject: PydanticAIStreamingCompleter
    transport: _ScriptedTransport

    @property
    def completer(self) -> StreamingCompleter:
        return self.subject

    @property
    def attempts(self) -> int:
        return len(self.transport.observed)

    @property
    def observed(self) -> tuple[tuple[Turn, ...], ...]:
        return tuple(self.transport.observed)

    @property
    def released(self) -> int:
        return self.transport.released


def _world(*attempts: StreamAttempt, status: int = _UNAVAILABLE) -> _ProviderWorld:
    """Build a completer whose transport plays ``attempts`` in order."""
    transport = _ScriptedTransport(script=attempts, status=status)
    model = FunctionModel(stream_function=transport.stream_function)
    return _ProviderWorld(
        subject=PydanticAIStreamingCompleter(default_model=model), transport=transport
    )


class TestPydanticAIStreamingCompleterContract(StreamingCompleterContract):
    """Runs the real seam through the shared ``StreamingCompleter`` conformance suite.

    ``substitutes_before_commit`` stays at its default ``False``: ADR-0173 §5
    permits substitution before the boundary and never requires it, and this seam
    takes exactly one attempt at the model. That is the strong way to satisfy the
    clause — ADR-0013 §3's wrappers sit around *completions*, neither can forward
    a stream (ADR-0173 §5), so a streaming route has no fallback to invent.
    """

    @pytest.fixture
    def completer(self) -> StreamingCompleter:
        return PydanticAIStreamingCompleter(default_model=TestModel())

    def world(self, *attempts: StreamAttempt) -> _ProviderWorld:
        return _world(*attempts)


class TestTheStreamingSeamItself:
    """Behaviour of this implementation that the shared contract does not fix."""

    async def test_the_deltas_arrive_undebounced_and_unjoined(self) -> None:
        # pydantic-ai's `stream_text` debounces by 0.1s unless told otherwise,
        # which would group these three into one delta and delay the first word by
        # the window — the one thing ADR-0173 exists to buy.
        world = _world(StreamAttempt(deltas=("hello", " ", "world")))

        deltas = await _drain(world.completer.stream(_a_question()))

        assert deltas == ["hello", " ", "world"]

    async def test_the_conversation_is_rendered_on_the_call(self) -> None:
        """ADR-0065's discharge: one observation, taken before the first await.

        The mutation lands after ``stream`` returned its iterator and before the
        transport is reached, which is precisely the window an implementation that
        rendered the history lazily inside its generator would tear in.
        """
        world = _world(StreamAttempt(deltas=("answer",)))
        conversation = _a_question()

        stream = world.completer.stream(conversation)
        conversation.append(Message(role=Role.USER, content="wait, actually"))
        await _drain(stream)

        assert world.observed == (((Role.USER, "hi", None),),)

    async def test_a_system_and_user_history_reaches_the_model_whole(self) -> None:
        world = _world(StreamAttempt(deltas=("answer",)))

        await _drain(
            world.completer.stream(
                [
                    Message(role=Role.SYSTEM, content="be terse"),
                    Message(role=Role.USER, content="hi"),
                ]
            )
        )

        assert world.observed == (((Role.SYSTEM, "be terse", None), (Role.USER, "hi", None)),)

    async def test_a_refusal_reaches_a_caller_that_never_iterates(self) -> None:
        # This seam validates and renders on the call, which the Protocol permits
        # either way. Pinned so a change of shape is deliberate, and because the
        # trailing-assistant case is the one with teeth: pydantic-ai resolves such
        # a history as a finished run and would replay it as a stream, an echo no
        # caller above this seam could tell from a real answer (ADR-0066 §2).
        world = _world(StreamAttempt(deltas=("answer",)))

        with pytest.raises(ModelError):
            world.completer.stream([Message(role=Role.ASSISTANT, content="already answered")])

        assert world.attempts == 0

    async def test_a_tool_turn_is_refused_by_the_render_the_two_seams_share(self) -> None:
        # The refusal rides `_to_model_messages`, the same function the completing
        # provider uses, so the two seams cannot drift about which histories they
        # will represent.
        world = _world(StreamAttempt(deltas=("answer",)))

        with pytest.raises(ModelError):
            world.completer.stream(
                [
                    Message(role=Role.USER, content="what is the weather"),
                    Message(role=Role.TOOL, content="sunny", name="weather"),
                ]
            )

        assert world.attempts == 0

    @pytest.mark.parametrize(
        ("status", "expected"),
        [
            pytest.param(429, ModelRateLimitError, id="rate-limited"),
            pytest.param(503, ModelUnavailableError, id="unavailable"),
        ],
    )
    async def test_a_mid_stream_failure_takes_the_completing_taxonomy(
        self, status: int, expected: type[ModelError]
    ) -> None:
        """ADR-0011 §1 binds this seam, through ``_classify``, unchanged.

        Read at two statuses the classifier narrows different ways, so the case
        cannot pass on a handler that wraps everything as one class. The failure
        is injected *after* a non-blank delta, which is where ADR-0173 §5 says it
        is raised from the iteration rather than repaired beneath it — and the
        text already handed over stays handed over.
        """
        world = _world(StreamAttempt(deltas=("partial ",), fails=True), status=status)
        seen: list[str] = []

        with pytest.raises(expected) as caught:
            await drain_into(world.completer.stream(_a_question()), seen)

        assert seen == ["partial "]
        assert caught.value.retryable is True

    async def test_an_unencodable_delta_is_a_response_error(self) -> None:
        # The class matters, not only that something raised: ADR-0173 §5 keeps a
        # pre-commit failure actionable, and the bare `ModelError` a naive handler
        # would produce carries neither disposition.
        world = _world(StreamAttempt(deltas=("\ud800",)))

        with pytest.raises(ModelResponseError) as caught:
            await _drain(world.completer.stream(_a_question()))

        assert caught.value.routable is True
        assert caught.value.retryable is False

    async def test_an_already_classified_failure_is_not_reclassified(self) -> None:
        # The encodability refusal is raised from inside the same `try` that wraps
        # the run, so a handler that classified everything would flatten
        # `ModelResponseError` into whatever `_classify` makes of a `ModelError` —
        # a bare one, losing `routable`.
        world = _world(StreamAttempt(deltas=("ok ", "\ud800")))

        with pytest.raises(ModelResponseError):
            await _drain(world.completer.stream(_a_question()))

    def test_construction_resolves_no_model_and_needs_no_credential(self) -> None:
        # `defer_model_check=True`, as on the completing provider: wiring the hub
        # must not demand a live key, and ADR-0083 §3 keeps startup local-only.
        completer = PydanticAIStreamingCompleter(default_model="anthropic:not-a-real-model")

        assert isinstance(completer, PydanticAIStreamingCompleter)


class TestCancellationOnTheCleanupPath:
    """ADR-0060's propagation clause, on the path where it is easiest to lose.

    Releasing the run means catching ``CancelledError`` in the generator's
    cleanup — to tell the pump acknowledging the cancellation we asked for from
    one delivered to us — and a blanket suppression there eats the second kind
    silently, reporting a clean close for a call that really was cancelled.
    """

    async def test_a_cancelled_reader_is_given_its_cancellation(self) -> None:
        held = asyncio.Event()

        async def slow(_messages: list[ModelMessage], _info: AgentInfo) -> AsyncIterator[str]:
            yield "one"
            await held.wait()  # pragma: no cover - the case never releases it
            yield "two"

        completer = PydanticAIStreamingCompleter(default_model=FunctionModel(stream_function=slow))
        stream = completer.stream(_a_question())
        seen: list[str] = []
        reading = asyncio.Event()

        async def read() -> None:
            async for delta in stream:
                seen.append(delta)
                reading.set()

        reader = asyncio.ensure_future(read())
        await asyncio.wait_for(reading.wait(), _A_MOMENT)
        # The reader is now suspended waiting for a delta the run will not send,
        # so its cancellation lands *inside* the generator's own await — the
        # window whose cleanup this class is about.
        await asyncio.sleep(0)
        reader.cancel()

        with pytest.raises(asyncio.CancelledError):
            await reader
        assert seen == ["one"]

    async def test_a_run_cancelled_by_something_else_fails_the_reader(self) -> None:
        """A run that stops without answering owes the caller an error, not a wait.

        The run is driven beside the iterator, so the iterator learns how it ended
        by being told. A cancellation arriving in the run from anywhere other than
        this stream's own cleanup — a deadline inside the library, an anyio scope,
        a provider raising it — ends the run with the reader still parked, and an
        implementation that re-raises without saying so leaves it parked forever.
        Read under `wait_for`, so the defect is a failed case rather than a hung
        suite.
        """

        async def cancels_itself(
            _messages: list[ModelMessage], _info: AgentInfo
        ) -> AsyncIterator[str]:
            yield "one"
            raise asyncio.CancelledError

        completer = PydanticAIStreamingCompleter(
            default_model=FunctionModel(stream_function=cancels_itself)
        )
        seen: list[str] = []

        with pytest.raises(ModelError) as caught:
            await asyncio.wait_for(drain_into(completer.stream(_a_question()), seen), _A_MOMENT)

        assert seen == ["one"], "the text read before the cancellation is still the caller's"
        # The bare class: a cancellation says nothing about whether another
        # attempt or another route would fare better (ADR-0063).
        assert caught.value.retryable is False
        assert caught.value.routable is False

    async def test_the_cleanup_tells_our_cancellation_from_the_pump_s(self) -> None:
        # The predicate the cleanup branches on, asserted in both states rather
        # than only in the one an integration test happens to reach. `cancelling()`
        # is what distinguishes them, and reading it wrong in either direction is
        # a silent bug: one way absorbs a real cancellation, the other invents one.
        assert not _cancelled_from_outside()

        async def cancels_itself() -> bool:
            task = asyncio.current_task()
            assert task is not None
            task.cancel()
            try:
                await asyncio.sleep(_A_MOMENT)
            except asyncio.CancelledError:
                return _cancelled_from_outside()
            return False  # pragma: no cover - the sleep is always cancelled

        assert await asyncio.ensure_future(cancels_itself())
