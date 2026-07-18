"""Timeout and retry for any :class:`~ai_assistant.core.protocols.ModelProvider`.

:class:`RetryingProvider` *wraps* another provider rather than extending one: it
implements ``ModelProvider`` and delegates to an inner ``ModelProvider``, so
resilience composes with any implementation — the pydantic-ai adapter today, a
router or a fake tomorrow — without either side knowing about the other.

It is the first consumer of the ``retryable`` flag on
:class:`~ai_assistant.core.errors.ModelError`: a transient failure is retried
with exponential backoff, and one that would fail identically on every attempt
(bad credentials, a refused prompt) is re-raised immediately rather than burning
quota.

The deadline lives here, not in the adapter, for two reasons: every provider
gets it uniformly, and a retry loop must be able to abandon a hung attempt to
start the next one.
"""

from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ai_assistant.core.errors import ConfigurationError, ModelError, ModelTimeoutError

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Sequence

    from ai_assistant.core.protocols import ModelProvider
    from ai_assistant.core.types import Message


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """How hard, and how patiently, to retry a failing model call.

    A plain dataclass rather than a pydantic model in ``core``: this never
    crosses a subsystem boundary, it only configures an implementation inside
    `models`.

    Attributes:
        timeout_seconds: Deadline applied to each individual attempt, not to
            the call as a whole.
        max_attempts: Total attempts including the first. ``1`` disables
            retrying while keeping the deadline.
        backoff_base_seconds: Ceiling of the delay after the first failure; it
            doubles per subsequent attempt.
        backoff_max_seconds: Upper bound on that ceiling.
    """

    timeout_seconds: float = 60.0
    max_attempts: int = 3
    backoff_base_seconds: float = 0.5
    backoff_max_seconds: float = 30.0

    def __post_init__(self) -> None:
        """Validate the policy at construction.

        Raises:
            ConfigurationError: If any bound is non-positive, ``max_attempts``
                is below 1, or the base delay exceeds the cap.
        """
        if self.timeout_seconds <= 0:
            msg = f"timeout_seconds must be positive, got {self.timeout_seconds}"
            raise ConfigurationError(msg)
        if self.max_attempts < 1:
            msg = f"max_attempts must be at least 1, got {self.max_attempts}"
            raise ConfigurationError(msg)
        if self.backoff_base_seconds <= 0:
            msg = f"backoff_base_seconds must be positive, got {self.backoff_base_seconds}"
            raise ConfigurationError(msg)
        if self.backoff_max_seconds < self.backoff_base_seconds:
            msg = (
                f"backoff_max_seconds ({self.backoff_max_seconds}) must be at least "
                f"backoff_base_seconds ({self.backoff_base_seconds})"
            )
            raise ConfigurationError(msg)


class RetryingProvider:
    """A ``ModelProvider`` that adds a per-attempt deadline and retries.

    Structurally implements
    :class:`~ai_assistant.core.protocols.ModelProvider`, so it can stand in for
    the provider it wraps anywhere the contract is expected.

    Backoff is *full jitter* — a delay drawn uniformly from ``[0, ceiling)``
    where the ceiling doubles each attempt up to a cap. Spreading retries this
    way stops many callers that failed together from retrying in lockstep and
    re-overloading a provider that is already struggling.
    """

    def __init__(
        self,
        inner: ModelProvider,
        *,
        policy: RetryPolicy | None = None,
        sleep: Callable[[float], Awaitable[None]] | None = None,
        jitter: Callable[[], float] | None = None,
    ) -> None:
        """Initialise the wrapper.

        Args:
            inner: The provider to delegate to.
            policy: How hard to retry. Defaults to :class:`RetryPolicy`'s own
                defaults.
            sleep: Injected for tests, so they need not sleep in real time.
                Defaults to :func:`asyncio.sleep`.
            jitter: Injected for tests, so backoff is deterministic. Returns a
                fraction in ``[0, 1)``. Defaults to :func:`random.random`.
        """
        self._inner = inner
        self._policy = policy if policy is not None else RetryPolicy()
        self._sleep = sleep if sleep is not None else asyncio.sleep
        # Jitter is a load-spreading device, not a security primitive, so the
        # non-cryptographic generator is the right one.
        self._jitter: Callable[[], float] = jitter if jitter is not None else random.random

    def _delay_for(self, attempt: int) -> float:
        """Return the backoff delay to wait after a failed attempt.

        Args:
            attempt: The 1-based attempt that just failed.

        Returns:
            A delay in seconds, drawn from ``[0, ceiling)`` where ``ceiling``
            grows exponentially with ``attempt`` and is capped.
        """
        # 2.0 rather than 2: ``int ** int`` is typed as Any (it may return a
        # float for a negative exponent), which would leak into the return type.
        ceiling = min(
            self._policy.backoff_base_seconds * 2.0 ** (attempt - 1),
            self._policy.backoff_max_seconds,
        )
        return ceiling * self._jitter()

    async def complete(
        self,
        messages: Sequence[Message],
        *,
        model: str | None = None,
    ) -> Message:
        """Complete via the wrapped provider, retrying transient failures.

        Args:
            messages: Conversation history, oldest first.
            model: Optional ``"provider:model"`` override, passed through
                unchanged.

        Returns:
            The assistant's reply from the first attempt that succeeds.

        Raises:
            ModelError: The failure from the final attempt. A non-retryable
                failure propagates immediately, without consuming attempts;
                an attempt that overruns its deadline surfaces as
                :class:`~ai_assistant.core.errors.ModelTimeoutError`.
        """
        attempt = 0
        while True:
            attempt += 1
            try:
                async with asyncio.timeout(self._policy.timeout_seconds):
                    return await self._inner.complete(messages, model=model)
            except TimeoutError as exc:
                # Our deadline, not the provider's. Note this does not catch an
                # outer cancellation: asyncio.timeout only converts the
                # CancelledError it raised itself.
                if attempt >= self._policy.max_attempts:
                    msg = (
                        f"model call exceeded its {self._policy.timeout_seconds:g}s "
                        f"deadline on attempt {attempt} of {self._policy.max_attempts}"
                    )
                    raise ModelTimeoutError(msg) from exc
            except ModelError as exc:
                if not exc.retryable or attempt >= self._policy.max_attempts:
                    raise

            await self._sleep(self._delay_for(attempt))
