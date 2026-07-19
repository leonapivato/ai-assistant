"""Shared conformance suite for the ContextProvider Protocol.

Every ``ContextProvider`` implementation must pass this suite (CONTRIBUTING,
"Protocol conformance suites"). A concrete test subclasses
:class:`ContextProviderContract` and overrides the ``provider`` fixture; the
suite asserts only behaviour *universal* to the contract — that assembly yields a
valid, tz-aware context, that it can be asked repeatedly, and that a returned
context is the caller's to keep — never how any one implementation derives its
facets (composed sources vs. a fixture), which stays in the per-implementation
test modules.

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

import pytest

from ai_assistant.core.protocols import ContextProvider
from ai_assistant.core.types import CurrentContext, TimeOfDay


class ContextProviderContract:
    """The behavioural contract every ``ContextProvider`` implementation must satisfy."""

    @pytest.fixture
    def provider(self) -> ContextProvider:
        """Override in a subclass to supply the implementation under test."""
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
