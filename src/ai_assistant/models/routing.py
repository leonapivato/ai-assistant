"""Routing and fallback across several :class:`~ai_assistant.core.protocols.ModelProvider`s.

:class:`RoutingProvider` is the second wrapper built on the ADR-0011 seam: it
implements ``ModelProvider`` and holds an ordered list of candidates, so it is
substitutable for any single provider while quietly surviving the loss of one.

It consumes the ``routable`` flag the way
:class:`~ai_assistant.models.retry.RetryingProvider` consumes ``retryable``, and
the distinction is the whole reason both exist. Retry asks *"would this same
provider succeed on a second try?"*; routing asks *"would a different one
succeed at all?"*. An expired API key answers no to the first and yes to the
second.

Composition order is a real decision, not a detail::

    RoutingProvider([...RetryingProvider(p)...])   # retry within a provider,
                                                    # then fall back
    RetryingProvider(RoutingProvider([...]))        # re-route on every attempt

The first is the intended shape and the one ADR-0013 recommends: exhaust the
cheap in-provider retries before paying to re-send the prompt somewhere else.
Nothing here enforces that — the wrapper composes either way — so whoever wires
the pipeline chooses deliberately.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ai_assistant.core.errors import ConfigurationError, ModelError

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.core.protocols import ModelProvider
    from ai_assistant.core.types import Message


@dataclass(frozen=True, slots=True)
class Route:
    """One candidate in a :class:`RoutingProvider`'s preference order.

    Attributes:
        provider: The provider to call. Usually already wrapped in a
            ``RetryingProvider``, so this route exhausts its own retries before
            routing gives up on it.
        model: An optional ``"provider:model"`` override handed to that
            provider, so one underlying provider can appear as several routes
            (a cheap model first, a stronger one behind it). ``None`` uses the
            provider's own default.
        label: A short human name used in error messages, so an exhausted-route
            failure says which candidates were tried rather than listing bare
            object reprs. Defaults to the model name, or the provider's class
            name when the route carries no override.
    """

    provider: ModelProvider
    model: str | None = None
    label: str = ""

    def describe(self) -> str:
        """Return the label to use for this route in diagnostics."""
        return self.label or self.model or type(self.provider).__name__


class RoutingProvider:
    """A ``ModelProvider`` that tries candidates in order until one succeeds.

    Structurally implements
    :class:`~ai_assistant.core.protocols.ModelProvider`, so it can stand in
    anywhere a single provider is expected — callers do not know they are
    talking to a pool.

    Fallback is driven entirely by the failure's ``routable`` flag. A routable
    failure (the provider is down, throttled, or refusing our credentials) moves
    on to the next candidate; a non-routable one (a content-policy refusal)
    propagates immediately, because re-sending the same prompt elsewhere would
    fail the same way and would widen the set of providers that see it.

    This is *static* preference order: the first healthy candidate always wins.
    There is no health tracking, so a persistently dead primary is re-tried on
    every call. Ranking by latency, cost, or observed reliability — the VISION
    §6 ambition — needs state and belongs in a later slice.
    """

    def __init__(self, routes: Sequence[Route]) -> None:
        """Initialise the router.

        Args:
            routes: Candidates in preference order, most preferred first.

        Raises:
            ConfigurationError: If ``routes`` is empty. A router with nothing to
                route to would raise only when first called, far from the wiring
                mistake that caused it.
        """
        if not routes:
            msg = "RoutingProvider requires at least one route"
            raise ConfigurationError(msg)
        self._routes = tuple(routes)

    async def complete(
        self,
        messages: Sequence[Message],
        *,
        model: str | None = None,
    ) -> Message:
        """Complete via the first candidate that succeeds.

        Args:
            messages: Conversation history, oldest first.
            model: An explicit ``"provider:model"`` override. Supplying one
                **disables routing**: the call goes to the first route's
                provider with that model and does not fall back. Routing is the
                policy for picking a model when the caller has not expressed a
                preference, and silently answering from a different model than
                the one asked for would be a worse surprise than the failure.

        Returns:
            The assistant's reply from the first route that succeeds.

        Raises:
            ModelError: A non-routable failure, immediately and unchanged. If
                every route fails routably, the last failure is re-raised as-is,
                carrying a note (PEP 678) that names every candidate tried and
                why each one failed.
        """
        if model is not None:
            primary = self._routes[0]
            return await primary.provider.complete(messages, model=model)

        failures: list[tuple[str, ModelError]] = []

        for route in self._routes:
            try:
                return await route.provider.complete(messages, model=route.model)
            except ModelError as exc:
                if not exc.routable:
                    raise
                failures.append((route.describe(), exc))

        # Reaching here means every route failed routably, so `failures` mirrors
        # the (non-empty) route list. Reading the last failure off it — rather
        # than tracking a separate `ModelError | None` — keeps the type honest
        # without an assert to convince the type checker.
        last = failures[-1][1]
        summary = "; ".join(f"{label}: {exc}" for label, exc in failures)
        # Re-raise the last failure *itself*, annotated with what else was tried.
        #
        # The obvious alternative — `raise type(last)(msg) from last` — assumes
        # every ModelError subclass takes exactly one message argument. Our own
        # do, but a route may be any ModelProvider, and one raising a richer
        # subclass (say `ProviderQuotaError(limit, message)`) would turn that
        # reconstruction into a TypeError: not merely a worse message, but an
        # exception the caller's `except ModelError` no longer catches, with the
        # provider's real failure destroyed. A note makes no such assumption and
        # preserves the type, the traceback, and the original __cause__ exactly.
        last.add_note(f"routing: all {len(self._routes)} routes failed ({summary})")
        raise last
