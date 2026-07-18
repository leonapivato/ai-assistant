"""Tests for the retry/timeout wrapper.

Backoff sleeping and jitter are injected, so these tests are deterministic and
never wait in real time. The only real delay is the deadline test, which uses a
few milliseconds.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

from ai_assistant.core.errors import (
    ConfigurationError,
    ModelAuthError,
    ModelError,
    ModelRateLimitError,
    ModelTimeoutError,
    ModelUnavailableError,
)
from ai_assistant.core.protocols import ModelProvider
from ai_assistant.core.types import Message, Role
from ai_assistant.models import RetryingProvider
from ai_assistant.models.retry import RetryPolicy

if TYPE_CHECKING:
    from collections.abc import Sequence


class FakeProvider:
    """A ``ModelProvider`` that replays a scripted sequence of outcomes."""

    def __init__(self, *outcomes: Message | Exception) -> None:
        self._outcomes = list(outcomes)
        self.calls = 0
        self.models: list[str | None] = []

    async def complete(
        self,
        messages: Sequence[Message],
        *,
        model: str | None = None,
    ) -> Message:
        self.calls += 1
        self.models.append(model)
        outcome = self._outcomes[min(self.calls - 1, len(self._outcomes) - 1)]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class SleepSpy:
    """Records requested backoff delays instead of waiting."""

    def __init__(self) -> None:
        self.delays: list[float] = []

    async def __call__(self, delay: float) -> None:
        self.delays.append(delay)


REPLY = Message(role=Role.ASSISTANT, content="ok")
PROMPT = [Message(role=Role.USER, content="hi")]


def _provider(inner: FakeProvider, sleep: SleepSpy, **kwargs: float | int) -> RetryingProvider:
    return RetryingProvider(inner, policy=RetryPolicy(**kwargs), sleep=sleep, jitter=lambda: 1.0)  # type: ignore[arg-type]


def test_conforms_to_protocol() -> None:
    assert isinstance(_provider(FakeProvider(REPLY), SleepSpy()), ModelProvider)


async def test_succeeds_without_retrying() -> None:
    inner, sleep = FakeProvider(REPLY), SleepSpy()

    reply = await _provider(inner, sleep).complete(PROMPT)

    assert reply is REPLY
    assert inner.calls == 1
    assert sleep.delays == []


async def test_retries_a_transient_failure_then_succeeds() -> None:
    inner = FakeProvider(ModelUnavailableError("503"), REPLY)
    sleep = SleepSpy()

    reply = await _provider(inner, sleep).complete(PROMPT)

    assert reply is REPLY
    assert inner.calls == 2
    assert len(sleep.delays) == 1


async def test_non_retryable_failure_is_not_retried() -> None:
    inner, sleep = FakeProvider(ModelAuthError("401")), SleepSpy()

    with pytest.raises(ModelAuthError):
        await _provider(inner, sleep).complete(PROMPT)

    # Bad credentials would be refused identically every time.
    assert inner.calls == 1
    assert sleep.delays == []


async def test_exhausted_attempts_raise_the_last_failure() -> None:
    inner = FakeProvider(ModelRateLimitError("429"))
    sleep = SleepSpy()

    with pytest.raises(ModelRateLimitError):
        await _provider(inner, sleep, max_attempts=3).complete(PROMPT)

    assert inner.calls == 3
    # Three attempts means two waits — never sleep after the final failure.
    assert len(sleep.delays) == 2


async def test_max_attempts_of_one_disables_retrying() -> None:
    inner, sleep = FakeProvider(ModelUnavailableError("503")), SleepSpy()

    with pytest.raises(ModelUnavailableError):
        await _provider(inner, sleep, max_attempts=1).complete(PROMPT)

    assert inner.calls == 1
    assert sleep.delays == []


async def test_backoff_grows_exponentially_and_is_capped() -> None:
    inner = FakeProvider(ModelUnavailableError("503"))
    sleep = SleepSpy()

    with pytest.raises(ModelUnavailableError):
        await _provider(
            inner,
            sleep,
            max_attempts=5,
            backoff_base_seconds=1.0,
            backoff_max_seconds=4.0,
        ).complete(PROMPT)

    # jitter() == 1.0 pins each delay to its ceiling: 1, 2, 4, then capped.
    assert sleep.delays == [1.0, 2.0, 4.0, 4.0]


async def test_jitter_scales_the_delay() -> None:
    inner = FakeProvider(ModelUnavailableError("503"))
    sleep = SleepSpy()
    provider = RetryingProvider(
        inner,
        policy=RetryPolicy(max_attempts=2, backoff_base_seconds=8.0),
        sleep=sleep,
        jitter=lambda: 0.25,
    )

    with pytest.raises(ModelUnavailableError):
        await provider.complete(PROMPT)

    # Full jitter draws from [0, ceiling), so a 0.25 draw is a quarter of it.
    assert sleep.delays == [2.0]


async def test_deadline_surfaces_as_a_timeout_error() -> None:
    async def hang(*_args: object, **_kwargs: object) -> Message:
        await asyncio.Event().wait()
        raise AssertionError  # pragma: no cover - unreachable

    inner = FakeProvider(REPLY)
    inner.complete = hang  # type: ignore[method-assign]
    sleep = SleepSpy()

    provider = RetryingProvider(
        inner,
        policy=RetryPolicy(timeout_seconds=0.01, max_attempts=2),
        sleep=sleep,
        jitter=lambda: 0.0,
    )

    with pytest.raises(ModelTimeoutError, match="deadline on attempt 2 of 2"):
        await provider.complete(PROMPT)

    # A hung attempt is abandoned and retried, not waited on forever.
    assert len(sleep.delays) == 1


async def test_a_slow_but_finishing_call_is_not_cut_off() -> None:
    async def slow(*_args: object, **_kwargs: object) -> Message:
        await asyncio.sleep(0.01)
        return REPLY

    inner = FakeProvider(REPLY)
    inner.complete = slow  # type: ignore[method-assign]

    provider = RetryingProvider(inner, policy=RetryPolicy(timeout_seconds=5.0), sleep=SleepSpy())

    assert await provider.complete(PROMPT) is REPLY


async def test_outer_cancellation_is_not_swallowed() -> None:
    started = asyncio.Event()

    async def hang(*_args: object, **_kwargs: object) -> Message:
        started.set()
        await asyncio.Event().wait()
        raise AssertionError  # pragma: no cover - unreachable

    inner = FakeProvider(REPLY)
    inner.complete = hang  # type: ignore[method-assign]

    provider = RetryingProvider(inner, policy=RetryPolicy(timeout_seconds=30.0), sleep=SleepSpy())
    task = asyncio.create_task(provider.complete(PROMPT))
    await started.wait()
    task.cancel()

    # Cancellation must propagate, not be retried as if it were a timeout.
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_model_override_is_passed_through() -> None:
    inner = FakeProvider(ModelUnavailableError("503"), REPLY)

    await _provider(inner, SleepSpy()).complete(PROMPT, model="anthropic:claude-haiku-4-5")

    assert inner.models == ["anthropic:claude-haiku-4-5"] * 2


@pytest.mark.parametrize(
    "kwargs",
    [
        {"timeout_seconds": 0},
        {"timeout_seconds": -1.0},
        {"max_attempts": 0},
        {"backoff_base_seconds": 0},
        {"backoff_base_seconds": 10.0, "backoff_max_seconds": 1.0},
    ],
)
def test_invalid_configuration_is_rejected(kwargs: dict[str, float | int]) -> None:
    with pytest.raises(ConfigurationError):
        RetryPolicy(**kwargs)  # type: ignore[arg-type]


async def test_bare_model_error_is_treated_as_non_retryable() -> None:
    inner, sleep = FakeProvider(ModelError("something unrecognised")), SleepSpy()

    with pytest.raises(ModelError):
        await _provider(inner, sleep).complete(PROMPT)

    assert inner.calls == 1
