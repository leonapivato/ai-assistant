"""Shared conformance suite for the ContextProvider Protocol.

Every ``ContextProvider`` implementation must pass this suite (CONTRIBUTING,
"Protocol conformance suites"). A concrete test subclasses
:class:`ContextProviderContract` and overrides the ``provider`` fixture; the
suite asserts only behaviour *universal* to the contract — that assembly yields a
valid, tz-aware context, that it can be asked repeatedly, that a returned context
is the caller's to keep, and that it is recomputed per request — never how any one
implementation derives its facets (composed sources vs. a fixture), which stays in
the per-implementation test modules.

Recomputation needs a clock the suite cannot inject itself, so it is a hook:
override :meth:`ContextProviderContract.provider_with_advancing_clock`, or set
``serves_a_fixed_instant`` if the implementation is a deliberately-fixed double.
It defaults to *required*, so a provider that caches its startup context fails
rather than passing silently.

Two things this suite deliberately does **not** assert:

- **Cross-facet consistency with ``now``.** ``time_of_day`` and ``is_weekend``
  are derived in the *configured local* timezone while ``now`` is normalised to
  UTC, so "10:00 UTC implies morning" is false for most locales. Agreement
  between the instant and the facets is a property of a given implementation's
  locale configuration, and is pinned where that configuration lives.
- **Monotonic ``now`` across calls.** A provider on a real clock never goes
  backwards, but the contract says only "the context for right now", and a
  legitimate test double may serve a fixed or scripted instant. Asserting it here
  would encode an implementation's clock choice as a contract.

Named ``*_contract`` (not ``test_*``) so pytest collects it only via a
``Test``-prefixed subclass, never the abstract base directly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from ai_assistant.core.protocols import ContextProvider
from ai_assistant.core.types import CurrentContext, TimeOfDay

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime


class ContextProviderContract:
    """The behavioural contract every ``ContextProvider`` implementation must satisfy."""

    #: Whether this implementation deliberately serves a *fixed* instant, as a test
    #: double does. Left ``False``, the suite requires the implementation to prove
    #: it recomputes per request (ADR-0008 §5) by overriding
    #: :meth:`provider_with_advancing_clock`. A provider that caches its startup
    #: context would otherwise satisfy every other test here — the facets it serves
    #: are never compared across calls, precisely so a wall-clock provider may
    #: cross a boundary between two of them. Opting out is a visible declaration in
    #: the subclass rather than a silent gap.
    serves_a_fixed_instant: bool = False

    @pytest.fixture
    def provider(self) -> ContextProvider:
        """Override in a subclass to supply the implementation under test."""
        raise NotImplementedError

    def provider_with_advancing_clock(self) -> tuple[ContextProvider, Sequence[datetime]]:
        """Supply a provider whose clock advances, plus the instants it will serve.

        Override unless :attr:`serves_a_fixed_instant` is set. Returns the provider
        and the successive instants its clock is scripted to return, so the suite
        can assert each ``assemble`` reflects the next one. How the clock is
        injected is implementation-specific, which is why this is a hook rather
        than a fixture the suite could build itself.
        """
        raise NotImplementedError

    def test_conforms_to_protocol(self, provider: ContextProvider) -> None:
        assert isinstance(provider, ContextProvider)

    async def test_assemble_returns_a_valid_current_context(
        self, provider: ContextProvider
    ) -> None:
        context = await provider.assemble()

        assert isinstance(context, CurrentContext)
        # Every facet of the required temporal core is populated and well-typed;
        # pydantic enforces the types, so this pins that none is left to a default.
        assert isinstance(context.time_of_day, TimeOfDay)
        assert isinstance(context.is_weekend, bool)
        assert isinstance(context.within_working_hours, bool)

    async def test_reference_instant_is_timezone_aware(self, provider: ContextProvider) -> None:
        # Downstream code compares ``now`` against UTC-aware timestamps; a naive
        # value would raise at the comparison, far from the provider that made it.
        context = await provider.assemble()

        assert context.now.tzinfo is not None
        assert context.now.utcoffset() is not None

    async def test_assemble_can_be_called_repeatedly(self, provider: ContextProvider) -> None:
        # Assembly is per-request, not a one-shot: a provider that consumed its
        # sources on first use would serve exactly one request in production.
        first = await provider.assemble()
        second = await provider.assemble()

        assert isinstance(first, CurrentContext)
        assert isinstance(second, CurrentContext)

    async def test_each_assembly_returns_a_distinct_context(
        self, provider: ContextProvider
    ) -> None:
        # The context is advisory and assembled fresh per request, never shared
        # durable state — so a caller that mutates what it got back cannot reach
        # the next caller. ``CurrentContext`` is all scalars, so a distinct object
        # is the whole of that isolation; there is no nested state to alias.
        #
        # Identity, not field values: a provider on a wall clock may legitimately
        # cross a time-of-day or weekend boundary between two calls, so comparing
        # facets would encode a fixed clock into the contract.
        first = await provider.assemble()
        second = await provider.assemble()

        assert second is not first

    async def test_each_assembly_recomputes_from_the_clock(self) -> None:
        # ADR-0008 §5: the context is computed fresh per request. A provider that
        # assembled once at startup and served copies of that context forever would
        # pass every other test in this suite while answering an evening request
        # with "morning, within working hours" — an advancing clock is the only
        # thing that distinguishes the two.
        if self.serves_a_fixed_instant:
            pytest.skip("implementation deliberately serves a fixed instant")

        provider, instants = self.provider_with_advancing_clock()

        assembled = [await provider.assemble() for _ in instants]

        assert [context.now for context in assembled] == list(instants)
