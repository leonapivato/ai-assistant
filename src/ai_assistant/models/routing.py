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
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

import structlog

from ai_assistant.core import errors as _errors
from ai_assistant.core.errors import ConfigurationError, ModelError

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.core.protocols import ModelProvider
    from ai_assistant.core.types import Message

_log = structlog.get_logger(__name__)

# The failure classes this project defines, captured by identity at import so a
# later-defined class cannot join the set by claiming our __module__. Read out
# of the errors module's own namespace rather than listed by name, so a class
# added to the taxonomy is picked up without editing this file.
_TAXONOMY: Final[frozenset[type[ModelError]]] = frozenset(
    obj for obj in vars(_errors).values() if isinstance(obj, type) and issubclass(obj, ModelError)
)


def _classify(exc: ModelError) -> str:
    """Name a failure using only the project's own taxonomy.

    ``type(exc).__name__`` is provider-controlled: a route may be any
    ``ModelProvider``, so the class it raises can be named anything at all, and
    that name reaches a Tier 2 log under a key the ADR-0004 §5 redactor treats
    as innocuous. Walking the MRO for the nearest *known* class keeps the
    diagnostic value — a third-party ``ProviderQuotaError(ModelRateLimitError)``
    still logs as ``ModelRateLimitError`` — while the emitted string can only
    ever be one we wrote.

    Membership is by **object identity** against :data:`_TAXONOMY`, a set frozen
    at import. An earlier version compared ``cls.__module__`` to this project's
    errors module, which a class can simply claim:
    ``type("PATIENT_SSN_...", (ModelRateLimitError,), {"__module__":
    "ai_assistant.core.errors"})`` passed that check and had its name logged.
    ``__module__`` is a writable attribute; identity is not forgeable.

    The threat model is narrow — a provider spoofing ``__module__`` to smuggle
    text into a log already runs in this process and could log directly. The
    realistic version is duller: a provider that names its exception after the
    tenant, customer, or record it failed on.
    """
    for cls in type(exc).__mro__:
        if cls in _TAXONOMY:
            return cls.__name__
    return ModelError.__name__


def _warn(event: str, **fields: object) -> None:
    """Emit a diagnostic warning, never letting it break the caller.

    Routing exists to survive a failing dependency, and the logger is a
    dependency like any other: an application-installed processor or sink that
    raises would otherwise abort the fallback before the backup route is even
    tried, and replace the ``ModelError`` the caller was promised with a
    logging error. Diagnostics are a side effect and must behave like one.

    ``Exception`` and not ``BaseException``: ``CancelledError`` is a
    ``BaseException``, so a caller cancelling mid-log still propagates.

    ``structlog.DropEvent`` is also a ``BaseException`` and so is *not* caught
    here — deliberately, and it does not need to be: structlog raises it as its
    own control-flow signal for "drop this event" and handles it internally, so
    it never reaches this frame. Checked, because a review argued otherwise and
    the redaction processor in `core/logging.py` raises exactly that on its
    fail-closed path. A regression test pins it.

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

    There is deliberately **no caller-supplied label**. Diagnostics identify a
    route by its position (see :meth:`describe`), and the reasoning is worth
    keeping because two weaker versions were tried first:

    1. The route's ``model`` id was used as its diagnostic name. That put
       ``model="patient-SSN-123-45-6789"`` straight into a Tier 2 log.
    2. A caller-supplied ``label`` was added and constrained to
       ``[A-Za-z0-9._:-]``. That rejects interpolated prose, but
       ``sk-live-abc`` and a tenant name are token-shaped too — the check
       cannot tell a route name from a credential or a person, because
       structurally they are the same string.

    Any rule that admits *some* caller-provided text into a log has to decide
    which text, and there is no test for that which does not eventually get a
    counterexample. A position carries no data by construction, so the question
    does not arise. Operators map positions to the configured order, which is
    the thing they control.
    """

    provider: ModelProvider
    model: str | None = None

    def describe(self, position: int) -> str:
        """Return this route's diagnostic identifier: its 1-based position."""
        return f"route[{position}]"


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

        for position, route in enumerate(self._routes, start=1):
            try:
                return await route.provider.complete(messages, model=route.model)
            except ModelError as exc:
                if not exc.routable:
                    # Deliberately not logged. The routable case is logged
                    # because a later route may paper over it, leaving a
                    # degrading provider invisible behind a successful call.
                    # This one is raised to the caller, so it is already
                    # visible; logging it too would only duplicate.
                    raise
                # Logged here, not only on exhaustion: a failure that a later
                # route papers over is invisible otherwise, and a primary
                # degrading silently is exactly what an operator needs to see
                # *before* the fallback also fails. Class only, never the
                # message — see the note on the exhaustion log below.
                #
                # Only when a next route actually exists. Announcing a
                # transition that is not about to happen — then immediately
                # logging "all routes failed" — reads as a fallback that was
                # tried and also failed, which is a different incident from
                # having nowhere left to go.
                if position < len(self._routes):
                    _warn(
                        "route failed; trying the next one",
                        route=route.describe(position),
                        error=_classify(exc),
                    )
                failures.append((route.describe(position), exc))

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
        # data that ADR-0004 §5 says must never reach a log. The class name is no
        # safer on its own: a route may be any ModelProvider, so
        # `type(exc).__name__` is provider-controlled text too. What keeps the
        # emitted string content-free is `_classify` mapping it through this
        # project's own taxonomy by object identity — see its docstring, and
        # ADR-0013 §5. The full message still travels to the caller on the raised
        # exception.
        _warn(
            "all routes failed",
            routes=len(self._routes),
            failures=[{"route": label, "error": _classify(exc)} for label, exc in failures],
        )
        raise last
