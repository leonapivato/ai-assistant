"""Tests for the retry/timeout wrapper.

Backoff sleeping and jitter are injected, so these tests are deterministic and
never wait in real time. The only real delay is the deadline test, which uses a
few milliseconds.
"""

from __future__ import annotations

import asyncio
import contextlib
import math
from typing import TYPE_CHECKING

import pytest
from model_provider_contract import ModelProviderContract
from pydantic import ValidationError

from ai_assistant.core.config import Settings
from ai_assistant.core.errors import (
    ConfigurationError,
    ModelAuthError,
    ModelError,
    ModelRateLimitError,
    ModelTimeoutError,
    ModelUnavailableError,
)
from ai_assistant.core.types import Message, Role
from ai_assistant.models import RetryingProvider
from ai_assistant.models.retry import RetryPolicy
from ai_assistant.testing import FakeModelProvider

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from ai_assistant.core.protocols import ModelProvider


class TestRetryingProviderContract(ModelProviderContract):
    """Runs RetryingProvider through the shared ModelProvider conformance suite.

    A wrapper is substitutable for what it wraps, so it owes the contract in its
    own right — over the canonical fake, which never fails, so the suite sees the
    pass-through path rather than the retry machinery.
    """

    @pytest.fixture
    def provider(self) -> ModelProvider:
        return RetryingProvider(FakeModelProvider())


class FakeProvider:
    """A ``ModelProvider`` that replays a scripted sequence of outcomes.

    Local rather than :class:`FakeModelProvider`: these tests need to script
    *typed failures* (a rate limit, then a success) to drive the retry loop, and
    the canonical fake deliberately wraps every reply failure in a bare
    ``ModelError``, which would erase the classification under test.
    """

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


async def test_a_providers_own_timeout_is_not_reported_as_our_deadline() -> None:
    # Regression (CI adversarial review): both arrive as TimeoutError, and
    # conflating them produced a false report — an instant "socket closed" was
    # re-labelled "exceeded its 30s deadline" with the provider's message
    # discarded. They are told apart by where they are caught: on expiry
    # asyncio.timeout cancels the inner call, so a TimeoutError seen *inside* it
    # can only have come from the provider.
    inner = FakeProvider(TimeoutError("socket closed"))
    sleep = SleepSpy()

    with pytest.raises(ModelTimeoutError, match="the provider raised a timeout: socket closed"):
        await _provider(inner, sleep, timeout_seconds=30.0, max_attempts=2).complete(PROMPT)

    # Still retried — a transport timeout is transient, so only the claim about
    # whose deadline expired was wrong, not the decision to try again.
    assert inner.calls == 2


async def test_a_providers_own_timeout_keeps_the_original_as_its_cause() -> None:
    inner = FakeProvider(TimeoutError("socket closed"))

    with pytest.raises(ModelTimeoutError) as caught:
        await _provider(inner, SleepSpy(), max_attempts=1).complete(PROMPT)

    assert isinstance(caught.value.__cause__, TimeoutError)
    assert str(caught.value.__cause__) == "socket closed"


async def test_a_provider_that_swallows_cancellation_still_times_out() -> None:
    # Regression (CI adversarial review): asyncio abandons a call by *cancelling*
    # it, and a provider that swallows that CancelledError returns normally — so
    # the timeout context exited quietly and its late reply was handed back as if
    # the deadline had held. Expiry is now checked explicitly.
    async def swallow(*_args: object, **_kwargs: object) -> Message:
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.sleep(5)  # refuses to die
        return Message(role=Role.ASSISTANT, content="LATE")

    inner = FakeProvider(REPLY)
    inner.complete = swallow  # type: ignore[method-assign]

    provider = RetryingProvider(
        inner,
        policy=RetryPolicy(timeout_seconds=0.01, max_attempts=1),
        sleep=SleepSpy(),
    )

    with pytest.raises(ModelTimeoutError, match=r"exceeded its 0\.01s deadline"):
        await provider.complete(PROMPT)


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


@pytest.mark.parametrize(
    "field", ["timeout_seconds", "backoff_base_seconds", "backoff_max_seconds"]
)
@pytest.mark.parametrize("value", ["60", None, True, [1]], ids=["str", "none", "bool", "list"])
def test_non_numeric_configuration_is_rejected(field: str, value: object) -> None:
    # Regression (CI adversarial review): math.isfinite("60") raises TypeError,
    # which escaped as a builtin and contradicted the ConfigurationError this
    # class documents. Type is now checked before value.
    with pytest.raises(ConfigurationError, match="must be a real number"):
        RetryPolicy(**{field: value})  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "field", ["timeout_seconds", "backoff_base_seconds", "backoff_max_seconds"]
)
@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_configuration_is_rejected(field: str, value: float) -> None:
    # NaN compares False to everything and infinity counts as "positive", so
    # both slip past ordinary bounds checks and then degrade silently.
    with pytest.raises(ConfigurationError, match="finite"):
        RetryPolicy(**{field: value})  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "value",
    [float("nan"), float("inf"), float("-inf"), 1.5, True, "3", None],
    ids=["nan", "inf", "-inf", "fractional", "bool", "str", "none"],
)
def test_non_integer_max_attempts_is_rejected(value: object) -> None:
    # Regression (CI adversarial review): the non-finite guard covered the three
    # float fields and skipped this int one, so NaN reached the retry loop —
    # where `attempt >= nan` is False forever, i.e. an unbounded retry loop
    # against a provider that is already failing. A fractional value silently
    # rounded the attempt count, and True is an int by inheritance.
    with pytest.raises(ConfigurationError, match="must be an int"):
        RetryPolicy(max_attempts=value)  # type: ignore[arg-type]


async def test_a_nan_attempt_count_cannot_loop_forever() -> None:
    # The failure this prevents, stated as behaviour rather than as validation:
    # without the type check the loop below never terminates.
    inner, sleep = FakeProvider(ModelUnavailableError("503")), SleepSpy()

    with pytest.raises(ConfigurationError):
        await _provider(inner, sleep, max_attempts=float("nan")).complete(PROMPT)

    assert inner.calls == 0


async def test_backoff_does_not_overflow_at_extreme_attempt_counts() -> None:
    # 2.0 ** 1024 raises OverflowError; without clamping, a persistent failure
    # would surface that instead of the underlying ModelError.
    inner = FakeProvider(ModelUnavailableError("503"))
    sleep = SleepSpy()

    with pytest.raises(ModelUnavailableError):
        await _provider(inner, sleep, max_attempts=1100).complete(PROMPT)

    assert len(sleep.delays) == 1099
    assert all(d <= 30.0 for d in sleep.delays)


async def test_backoff_saturates_for_a_very_large_base() -> None:
    # base * growth would overflow to inf if computed before capping.
    inner = FakeProvider(ModelUnavailableError("503"))
    sleep = SleepSpy()

    with pytest.raises(ModelUnavailableError):
        await _provider(
            inner,
            sleep,
            max_attempts=3,
            backoff_base_seconds=1e300,
            backoff_max_seconds=1e308,
        ).complete(PROMPT)

    assert all(math.isfinite(d) for d in sleep.delays)
    assert sleep.delays == [1e300, 2e300]


def test_policy_is_built_from_settings() -> None:
    settings = Settings(
        model_timeout_seconds=12.5,
        model_max_attempts=7,
        model_backoff_base_seconds=0.25,
        model_backoff_max_seconds=9.0,
    )

    assert RetryPolicy.from_settings(settings) == RetryPolicy(
        timeout_seconds=12.5,
        max_attempts=7,
        backoff_base_seconds=0.25,
        backoff_max_seconds=9.0,
    )


@pytest.mark.parametrize(
    "make",
    [
        lambda v: Settings(model_timeout_seconds=v),
        lambda v: Settings(model_backoff_base_seconds=v),
        lambda v: Settings(model_backoff_max_seconds=v),
    ],
    ids=["timeout", "backoff_base", "backoff_max"],
)
def test_settings_reject_non_finite_values(make: Callable[[float], Settings]) -> None:
    # pydantic's gt=0 rejects NaN but accepts infinity, hence allow_inf_nan.
    with pytest.raises(ValidationError):
        make(float("inf"))


async def test_bare_model_error_is_treated_as_non_retryable() -> None:
    inner, sleep = FakeProvider(ModelError("something unrecognised")), SleepSpy()

    with pytest.raises(ModelError):
        await _provider(inner, sleep).complete(PROMPT)

    assert inner.calls == 1
