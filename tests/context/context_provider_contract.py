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

import asyncio
import gc
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest

from ai_assistant.core.protocols import ContextProvider
from ai_assistant.core.types import CurrentContext, TimeOfDay
from ai_assistant.testing.cancellation import settle

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Sequence
    from contextlib import AbstractAsyncContextManager
    from datetime import datetime

#: Ceiling on every wait the cancellation case makes, so a provider that defers
#: unboundedly fails instead of hanging the suite. Generous: it is a liveness
#: bound, not a latency assertion — how *fast* a given implementation must give
#: up on a straggler is its own drain budget's business (ADR-0033 §1), not
#: something the shared contract fixes for every provider.
_SCENARIO_SECONDS = 5.0


@dataclass(frozen=True)
class AbandonedStraggler:
    """One assembly with a source that will outlive it, plus the levers to drive it.

    What ADR-0060 §3's ``ContextProvider`` case needs from an implementation, and
    no more. ``quiesce`` is the documented hook the ADR requires: the retention
    property has no positive signal through ``assemble()``, so the suite has to
    be handed a way to await the implementation's outstanding abandoned work.

    Attributes:
        provider: The subject, wired with the suppressing source.
        started: Waits until that source is really running.
        fail: Releases it into a *failure* — the outcome that leaves a trace if
            nobody retrieves it.
        finished: Waits until that failure has actually happened, observed from
            the *source* rather than from the provider. Separate from
            ``quiesce`` on purpose: a provider that forgot its straggler
            entirely has nothing outstanding to quiesce, and would otherwise
            race the suite to the end of the case and pass.
        quiesce: Waits until the implementation's outstanding abandoned work has
            finished and been accounted for. Must not consume the outcome it
            waits on — ``asyncio.wait`` rather than a ``gather`` with
            ``return_exceptions``, which would retrieve the exception on the
            implementation's behalf and mask the very thing the case looks for.
    """

    provider: ContextProvider
    started: Callable[[], Awaitable[object]]
    fail: Callable[[], None]
    finished: Callable[[], Awaitable[object]]
    quiesce: Callable[[], Awaitable[object]]


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

    @pytest.mark.optional_obligation
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

    # --- cancellation (ADR-0060) -------------------------------------------

    #: Whether this implementation spawns nothing that can outlive an
    #: ``assemble()`` — no per-source task, no background work a cancellation
    #: could leave running. ``core.protocols``' clause is then vacuously
    #: satisfied and there is nothing for the case below to observe. Left
    #: ``False``, the suite requires the implementation to prove the invariant by
    #: overriding :meth:`assembly_with_a_suppressing_source`, so a provider that
    #: fans out and drops its stragglers fails here rather than passing a suite
    #: that never looked. Opting out is a visible declaration in the subclass,
    #: exactly as :attr:`serves_a_fixed_instant` is.
    spawns_no_abandonable_work: bool = False

    def assembly_with_a_suppressing_source(
        self,
    ) -> AbstractAsyncContextManager[AbandonedStraggler]:
        """Supply a provider whose assembly has one source that suppresses cancellation.

        Override unless :attr:`spawns_no_abandonable_work` is set. A source that
        swallows its own ``CancelledError`` is the shape the rule is about
        (ADR-0033/ADR-0057): the caller's cancellation must still surface, and
        whatever keeps running must stay observed until it finishes.

        Building that source means knowing how this implementation composes, so
        it is a hook. So is :attr:`AbandonedStraggler.quiesce` — retention
        against mid-flight collection has **no** positive signal reachable
        through ``assemble()``, and requiring the affordance on the *suite's*
        fixture is what keeps it off the ``ContextProvider`` Protocol, where a
        test-only member would widen the contract every consumer depends on
        (ADR-0060 §3).
        """
        raise NotImplementedError

    @pytest.mark.optional_obligation
    async def test_a_cancelled_assembly_surfaces_and_keeps_its_straggler_observed(self) -> None:
        """``core.protocols``' cancellation clause, on the assembly path (ADR-0060).

        Two properties, and promptness alone is not enough. A provider that
        cancels its sources, waits out its budget, drops its last reference and
        re-raises passes any promptness-only case while orphaning exactly what the
        rule forbids — ``asyncio`` holds only weak references to running tasks, so
        a dropped one can be collected mid-flight.

        So the straggler is driven to **fail**. A failure is the one outcome that
        leaves a trace when it goes unobserved: an unretrieved task exception is
        reported to the event loop's exception handler when the task is collected.
        A straggler that merely *succeeds* reports nothing, which is why "nothing
        was logged" is not on its own evidence of observation (ADR-0060 §3).
        """
        if self.spawns_no_abandonable_work:
            pytest.skip("implementation spawns nothing that can outlive an assembly")

        loop = asyncio.get_running_loop()
        reported: list[str] = []
        previous = loop.get_exception_handler()
        loop.set_exception_handler(
            lambda _loop, context: reported.append(str(context.get("message", "")))
        )
        try:
            async with self.assembly_with_a_suppressing_source() as straggler:
                assembling = asyncio.ensure_future(straggler.provider.assemble())
                try:
                    async with asyncio.timeout(_SCENARIO_SECONDS):
                        await straggler.started()
                    assembling.cancel()

                    # Delivered onward, and without waiting for the source: the
                    # source is still suspended when this returns, so an
                    # implementation that joined it unbounded would time out here.
                    async with asyncio.timeout(_SCENARIO_SECONDS):
                        with pytest.raises(asyncio.CancelledError):
                            await assembling
                finally:
                    straggler.fail()

                async with asyncio.timeout(_SCENARIO_SECONDS):
                    await straggler.finished()
                    await straggler.quiesce()

            # Collect anything the provider has now let go of, so an unretrieved
            # exception would be reported before the assertion reads the log.
            gc.collect()
            await settle()

            assert not [message for message in reported if "never retrieved" in message], (
                f"the abandoned source's late failure went unobserved: {reported}"
            )
        finally:
            loop.set_exception_handler(previous)
