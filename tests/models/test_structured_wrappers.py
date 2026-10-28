"""``RetryingProvider`` and ``RoutingProvider`` as structured completers (ADR-0354 §6).

Each wrapper owes the shared ``StructuredCompleter`` suite in its own right, over the
canonical fake. The cases after it pin §6:1 and §5:4 (ADR-0354 §12:5): a raised
retryable failure is retried and a raised routable one routed, as for ``complete``,
while a returned failure is a response that came back and is returned from the
attempt or the route that got it; the per-attempt deadline raises
``ModelTimeoutError``; and a wrapper whose inner does not implement the seam refuses
before any attempt.
"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest
from structured_completer_contract import (
    VALID_REPLY,
    VALID_VALUE,
    Answer,
    StructuredCompleterContract,
    Verdict,
    request,
    scripted_reply,
)

from ai_assistant.core.errors import (
    ModelAuthError,
    ModelContentFilterError,
    ModelError,
    ModelRateLimitError,
    ModelTimeoutError,
    ModelUnavailableError,
)
from ai_assistant.core.types import Message, ReplyFailure, ReplyMode, StructuredReply
from ai_assistant.models.retry import RetryingProvider, RetryPolicy
from ai_assistant.models.routing import Route, RoutingProvider
from ai_assistant.testing import (
    DEFAULT_STRUCTURED_MODEL,
    FakeModelProvider,
    FakeStructuredCompleter,
    ScriptedReply,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence
    from contextlib import AbstractAsyncContextManager

    from model_provider_contract import ConversationLog
    from pydantic import BaseModel

    from ai_assistant.core.protocols import StructuredCompleter
    from ai_assistant.testing.cancellation import SuspendedCall
    from ai_assistant.testing.structured import StructuredAnswer


async def _no_sleep(_delay: float) -> None:
    """Stand in for backoff, so no case waits in real time."""


class Both:
    """A provider implementing both seams: the canonical fakes, side by side.

    What a wrapper wraps in production implements both; each fake implements one.
    """

    def __init__(self, structured: FakeStructuredCompleter) -> None:
        """Answer structured calls with ``structured``, and completions with a fake."""
        self.structured = structured
        self._plain = FakeModelProvider()

    async def complete(self, messages: Sequence[Message], *, model: str | None = None) -> Message:
        """Complete through the canonical ``ModelProvider`` fake."""
        return await self._plain.complete(messages, model=model)

    async def complete_structured[T: BaseModel](
        self, messages: Sequence[Message], shape: type[T], *, model: str | None = None
    ) -> StructuredReply[T]:
        """Answer through the canonical ``StructuredCompleter`` fake."""
        return await self.structured.complete_structured(messages, shape, model=model)


def both(*answers: StructuredAnswer) -> Both:
    """A provider answering structured calls with each of ``answers`` in turn."""
    return Both(FakeStructuredCompleter.scripted(*answers))


@dataclass
class _WrappedWorld:
    completer: StructuredCompleter
    inner: FakeStructuredCompleter
    answered_by: str = DEFAULT_STRUCTURED_MODEL
    mode: ReplyMode = ReplyMode.NATIVE

    @property
    def attempts(self) -> int:
        return self.inner.call_count


class TestRetryingProviderStructuredContract(StructuredCompleterContract):
    """``RetryingProvider`` passes the shared ``StructuredCompleter`` contract."""

    @pytest.fixture
    def completer(self) -> StructuredCompleter:
        return RetryingProvider(Both(FakeStructuredCompleter()))

    @contextlib.asynccontextmanager
    async def world(self, answer: Answer) -> AsyncIterator[_WrappedWorld]:
        inner = FakeStructuredCompleter(scripted_reply(answer))
        yield _WrappedWorld(RetryingProvider(Both(inner), sleep=_no_sleep), inner)

    def completer_suspended_at_its_first_await(
        self,
    ) -> AbstractAsyncContextManager[tuple[StructuredCompleter, SuspendedCall, ConversationLog]]:
        # The loop hands the conversation to attempt 2 after attempt 1's await.
        return self._suspended_through_a_recording_inner(
            lambda primary, _secondary: RetryingProvider(primary, sleep=_no_sleep)
        )


class TestRoutingProviderStructuredContract(StructuredCompleterContract):
    """``RoutingProvider`` passes the shared ``StructuredCompleter`` contract."""

    @pytest.fixture
    def completer(self) -> StructuredCompleter:
        return RoutingProvider([Route(Both(FakeStructuredCompleter()))])

    @contextlib.asynccontextmanager
    async def world(self, answer: Answer) -> AsyncIterator[_WrappedWorld]:
        inner = FakeStructuredCompleter(scripted_reply(answer))
        yield _WrappedWorld(RoutingProvider([Route(Both(inner))]), inner)

    def completer_suspended_at_its_first_await(
        self,
    ) -> AbstractAsyncContextManager[tuple[StructuredCompleter, SuspendedCall, ConversationLog]]:
        # The loop hands the conversation to route 2 after route 1's await failed.
        return self._suspended_through_a_recording_inner(
            lambda primary, secondary: RoutingProvider([Route(primary), Route(secondary)])
        )


#: Each returned failure, as the inner provider scripts it.
_RETURNED = [
    pytest.param(ScriptedReply(failure=ReplyFailure.REFUSED), ReplyFailure.REFUSED, id="refused"),
    pytest.param(ScriptedReply(text="{", failure=ReplyFailure.CUT), ReplyFailure.CUT, id="cut"),
    pytest.param(ScriptedReply(text=" "), ReplyFailure.EMPTY, id="empty"),
    pytest.param(ScriptedReply(text="no"), ReplyFailure.INVALID, id="invalid"),
]


# --- retry (§6:1, §5:4) -----------------------------------------------------------


async def test_retry_retries_a_raised_retryable_failure() -> None:
    inner = both(ModelRateLimitError("slow down"), VALID_REPLY)
    reply = await RetryingProvider(inner, sleep=_no_sleep).complete_structured(request(), Verdict)
    assert reply.value == VALID_VALUE
    assert inner.structured.call_count == 2


@pytest.mark.parametrize(("scripted", "failure"), _RETURNED)
async def test_retry_returns_a_returned_failure_without_retrying_it(
    scripted: ScriptedReply, failure: ReplyFailure
) -> None:
    inner = both(scripted, VALID_REPLY)
    reply = await RetryingProvider(inner, sleep=_no_sleep).complete_structured(request(), Verdict)
    assert reply.failure is failure
    assert inner.structured.call_count == 1


async def test_retry_raises_a_non_retryable_failure_at_once() -> None:
    inner = both(ModelContentFilterError("refused"), VALID_REPLY)
    with pytest.raises(ModelContentFilterError):
        await RetryingProvider(inner, sleep=_no_sleep).complete_structured(request(), Verdict)
    assert inner.structured.call_count == 1


async def test_retry_raises_the_last_failure_once_its_attempts_are_spent() -> None:
    inner = both(*(ModelUnavailableError("503") for _ in range(3)))
    retrying = RetryingProvider(inner, policy=RetryPolicy(max_attempts=3), sleep=_no_sleep)
    with pytest.raises(ModelUnavailableError):
        await retrying.complete_structured(request(), Verdict)
    assert inner.structured.call_count == 3


class _Hangs(Both):
    """A provider whose structured call never answers."""

    async def complete_structured[T: BaseModel](
        self, messages: Sequence[Message], shape: type[T], *, model: str | None = None
    ) -> StructuredReply[T]:
        await asyncio.Event().wait()
        raise AssertionError


class _TimesOutItself(Both):
    """A provider whose structured call raises its own timeout."""

    async def complete_structured[T: BaseModel](
        self, messages: Sequence[Message], shape: type[T], *, model: str | None = None
    ) -> StructuredReply[T]:
        msg = "socket closed"
        raise TimeoutError(msg)


async def test_the_per_attempt_deadline_raises_a_timeout() -> None:
    policy = RetryPolicy(timeout_seconds=0.01, max_attempts=2)
    retrying = RetryingProvider(_Hangs(FakeStructuredCompleter()), policy=policy, sleep=_no_sleep)
    with pytest.raises(ModelTimeoutError) as caught:
        await retrying.complete_structured(request(), Verdict)
    assert caught.value.retryable
    assert caught.value.routable


async def test_a_timeout_the_provider_raises_is_a_timeout_too() -> None:
    policy = RetryPolicy(max_attempts=1)
    retrying = RetryingProvider(
        _TimesOutItself(FakeStructuredCompleter()), policy=policy, sleep=_no_sleep
    )
    with pytest.raises(ModelTimeoutError, match="the provider raised a timeout"):
        await retrying.complete_structured(request(), Verdict)


async def test_retry_passes_the_model_override_through() -> None:
    inner = both(VALID_REPLY)
    await RetryingProvider(inner).complete_structured(request(), Verdict, model="anthropic:x")
    assert inner.structured.last_call.model == "anthropic:x"


async def test_retry_over_an_inner_without_the_seam_refuses_before_any_attempt() -> None:
    plain = FakeModelProvider()
    with pytest.raises(ModelError) as caught:
        await RetryingProvider(plain).complete_structured(request(), Verdict)
    assert caught.value.retryable is False
    assert caught.value.routable is False
    assert plain.call_count == 0


# --- routing (§6:1, §5:4) ---------------------------------------------------------


async def test_routing_routes_a_raised_routable_failure() -> None:
    primary, secondary = both(ModelAuthError("expired")), both(VALID_REPLY)
    router = RoutingProvider([Route(primary), Route(secondary)])
    reply = await router.complete_structured(request(), Verdict)
    assert reply.value == VALID_VALUE
    assert primary.structured.call_count == 1
    assert secondary.structured.call_count == 1


@pytest.mark.parametrize(("scripted", "failure"), _RETURNED)
async def test_routing_returns_a_returned_failure_without_routing_it(
    scripted: ScriptedReply, failure: ReplyFailure
) -> None:
    primary, secondary = both(scripted), both(VALID_REPLY)
    router = RoutingProvider([Route(primary), Route(secondary)])
    reply = await router.complete_structured(request(), Verdict)
    assert reply.failure is failure
    assert secondary.structured.call_count == 0


async def test_routing_raises_a_non_routable_failure_at_once() -> None:
    primary, secondary = both(ModelContentFilterError("refused")), both(VALID_REPLY)
    router = RoutingProvider([Route(primary), Route(secondary)])
    with pytest.raises(ModelContentFilterError):
        await router.complete_structured(request(), Verdict)
    assert secondary.structured.call_count == 0


async def test_routing_raises_the_last_failure_when_every_route_fails() -> None:
    last = ModelUnavailableError("down too")
    router = RoutingProvider([Route(both(ModelUnavailableError("down"))), Route(both(last))])
    with pytest.raises(ModelUnavailableError) as caught:
        await router.complete_structured(request(), Verdict)
    assert caught.value is last


async def test_each_route_is_asked_with_its_own_model() -> None:
    primary, secondary = both(ModelUnavailableError("down")), both(VALID_REPLY)
    router = RoutingProvider([Route(primary, model="a:one"), Route(secondary, model="b:two")])
    await router.complete_structured(request(), Verdict)
    assert primary.structured.last_call.model == "a:one"
    assert secondary.structured.last_call.model == "b:two"


async def test_a_model_override_goes_to_the_first_route_and_routes_nowhere() -> None:
    primary, secondary = both(ModelUnavailableError("down")), both(VALID_REPLY)
    router = RoutingProvider([Route(primary, model="a:one"), Route(secondary)])
    with pytest.raises(ModelUnavailableError):
        await router.complete_structured(request(), Verdict, model="c:three")
    assert primary.structured.last_call.model == "c:three"
    assert secondary.structured.call_count == 0


async def test_routing_over_a_route_without_the_seam_refuses_before_any_route() -> None:
    primary = both(VALID_REPLY)
    router = RoutingProvider([Route(primary), Route(FakeModelProvider())])
    with pytest.raises(ModelError) as caught:
        await router.complete_structured(request(), Verdict)
    assert caught.value.retryable is False
    assert caught.value.routable is False
    assert primary.structured.call_count == 0


async def test_retry_inside_routing_is_the_composed_shape() -> None:
    """ADR-0013's composition: each route exhausts its retries before routing moves on."""
    primary = both(ModelUnavailableError("503"), ModelUnavailableError("503"))
    secondary = both(VALID_REPLY)
    policy = RetryPolicy(max_attempts=2)
    router = RoutingProvider(
        [
            Route(RetryingProvider(primary, policy=policy, sleep=_no_sleep)),
            Route(RetryingProvider(secondary, policy=policy, sleep=_no_sleep)),
        ]
    )
    reply = await router.complete_structured(request(), Verdict)
    assert reply.value == VALID_VALUE
    assert primary.structured.call_count == 2
    assert secondary.structured.call_count == 1
