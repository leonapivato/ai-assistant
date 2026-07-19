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

import contextlib
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

import structlog

from ai_assistant.core.errors import ConfigurationError, ModelError

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.core.protocols import ModelProvider
    from ai_assistant.core.types import Message

_log = structlog.get_logger(__name__)

# Labels reach the log under a key the ADR-0004 §5 redactor treats as harmless,
# so their shape is checked at construction instead. See Route.__post_init__.
_SAFE_LABEL: Final = re.compile(r"[A-Za-z0-9._:-]+")


def _warn(event: str, **fields: object) -> None:
    """Emit a diagnostic warning, never letting it break the caller.

    Routing exists to survive a failing dependency, and the logger is a
    dependency like any other: an application-installed processor or sink that
    raises would otherwise abort the fallback before the backup route is even
    tried, and replace the ``ModelError`` the caller was promised with a
    logging error. Diagnostics are a side effect and must behave like one.

    ``Exception`` and not ``BaseException``: ``CancelledError`` is a
    ``BaseException``, so a caller cancelling mid-log still propagates.

    The failure is swallowed rather than reported, which would normally be the
    wrong instinct — but the only channel available to report it is the thing
    that just failed.
    """
    with contextlib.suppress(Exception):
        _log.warning(event, **fields)


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
        label: A short identifier used in diagnostics, so an exhausted-route
            failure says which candidates were tried rather than listing bare
            object reprs. Defaults to the model name, or the provider's class
            name when the route carries no override. Constrained to
            ``[A-Za-z0-9._:-]`` — see :meth:`__post_init__`.
    """

    provider: ModelProvider
    model: str | None = None
    label: str = ""

    def __post_init__(self) -> None:
        """Validate the label's shape.

        The label is written into logs under an innocuous ``route`` key, where
        the ADR-0004 §5 redactor — which matches on *key* names — will never
        look at it. So its safety cannot be delegated: it has to be established
        here.

        The realistic hazard is not a developer typing a secret, it is
        interpolation: ``label=f"route for {user_request}"`` is an easy mistake
        that would put a prompt straight into a Tier 2 log. Requiring a short
        token — no spaces, no punctuation beyond ``.``, ``_``, ``:`` and ``-``
        — rejects prose and free text while still allowing the things labels
        actually are (``primary``, ``eu-west-1``, ``anthropic:claude-haiku-4-5``).

        This is a tripwire, not a guarantee: a label of ``sk-live-abc`` matches
        the pattern and would still be logged. Nothing can stop a caller that
        deliberately puts a secret in a diagnostic field; what this stops is the
        accident.

        Raises:
            ConfigurationError: If the label contains anything outside
                ``[A-Za-z0-9._:-]``.
        """
        if self.label and not _SAFE_LABEL.fullmatch(self.label):
            msg = (
                f"route label must be a short token matching [A-Za-z0-9._:-], got "
                f"{self.label!r}; labels are written to logs, which are Tier 2 "
                f"and must not carry user data (ADR-0004 §5)"
            )
            raise ConfigurationError(msg)

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
                every route fails routably, the last failure is re-raised
                untouched; what every candidate was and why each failed is
                logged rather than attached to the exception, which the router
                does not own.
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
                # Logged here, not only on exhaustion: a failure that a later
                # route papers over is invisible otherwise, and a primary
                # degrading silently is exactly what an operator needs to see
                # *before* the fallback also fails. Class only, never the
                # message — see the note on the exhaustion log below.
                _warn(
                    "route failed; trying the next one",
                    route=route.describe(),
                    error=type(exc).__name__,
                )
                failures.append((route.describe(), exc))

        # Reaching here means every route failed routably, so `failures` mirrors
        # the (non-empty) route list. Reading the last failure off it — rather
        # than tracking a separate `ModelError | None` — keeps the type honest
        # without an assert to convince the type checker.
        last = failures[-1][1]
        # Aggregate diagnostics are logged, not attached to the exception, and
        # the last failure is re-raised untouched. Two tempting alternatives are
        # both wrong, each found by adversarial review:
        #
        # - `raise type(last)(summary) from last` assumes every ModelError
        #   subclass takes one message argument. A route may be any
        #   ModelProvider, so one raising a richer subclass turns that into a
        #   TypeError — which `except ModelError` does not even catch.
        # - `last.add_note(...)` mutates an exception the router does not own. A
        #   provider that raises a cached instance accumulates a note per call,
        #   and concurrent routers sharing it leak each other's route labels.
        #
        # Logging keeps the diagnostics richer *and* router-owned, and leaves the
        # caller a correctly-typed failure to inspect in full.
        #
        # Only the *class* of each failure is logged, never `str(exc)`. Provider
        # error messages routinely quote the offending request, so the message is
        # attacker- and vendor-controlled text that can carry a prompt — Tier 1
        # data that ADR-0004 §5 says must never reach a log. The class name is
        # vendor-independent, sufficient to diagnose which route failed and why,
        # and cannot carry content by construction. The full message still
        # travels to the caller on the raised exception.
        _warn(
            "all routes failed",
            routes=len(self._routes),
            failures=[{"route": label, "error": type(exc).__name__} for label, exc in failures],
        )
        raise last
