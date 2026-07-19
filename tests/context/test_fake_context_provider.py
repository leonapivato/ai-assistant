"""The canonical FakeContextProvider passes the shared ContextProvider suite.

This is what lets other subsystems trust ``ai_assistant.testing.FakeContextProvider``
as a stand-in for a real provider: it is held to the same contract as
``AssemblingContextProvider``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from context_provider_contract import ContextProviderContract

from ai_assistant.core.errors import ContextError
from ai_assistant.core.types import CurrentContext, TimeOfDay
from ai_assistant.testing import FakeContextProvider

if TYPE_CHECKING:
    from ai_assistant.core.protocols import ContextProvider


def _saturday_night() -> CurrentContext:
    return CurrentContext(
        now=datetime(2026, 6, 6, 23, 0, tzinfo=UTC),
        time_of_day=TimeOfDay.NIGHT,
        is_weekend=True,
        within_working_hours=False,
    )


class TestFakeContextProviderContract(ContextProviderContract):
    """Runs the default FakeContextProvider through the shared suite."""

    @pytest.fixture
    def provider(self) -> ContextProvider:
        return FakeContextProvider()


class TestFakeContextProviderWithSuppliedContextContract(ContextProviderContract):
    """The suite must also hold for a caller-supplied context, not just the default.

    The default is a weekday inside working hours; a supplied weekend/out-of-hours
    context exercises the opposite value of every boolean facet.
    """

    @pytest.fixture
    def provider(self) -> ContextProvider:
        return FakeContextProvider(_saturday_night())


# Behaviour specific to FakeContextProvider, beyond the shared contract: the
# contract deliberately says nothing about *which* context comes back or how many
# times assembly was asked, so the fake's own affordances are pinned here.


async def test_default_context_is_a_weekday_inside_working_hours() -> None:
    context = await FakeContextProvider().assemble()

    # The exact instant, not just the facets: the default is advertised as a fixed,
    # deterministic context, so a drift to some other weekday morning is a change
    # to what consumers' tests are pinned against, not an implementation detail.
    assert context.now == datetime(2026, 6, 3, 10, 0, tzinfo=UTC)
    assert context.time_of_day is TimeOfDay.MORNING
    assert context.is_weekend is False
    assert context.within_working_hours is True


async def test_returns_the_supplied_context_unchanged() -> None:
    expected = _saturday_night()

    context = await FakeContextProvider(expected).assemble()

    assert context == expected


async def test_repeated_assembly_returns_an_equal_context() -> None:
    # The fake's clock is fixed, so unlike a wall-clock provider it may promise
    # value stability — that is what makes it usable as a test fixture.
    provider = FakeContextProvider(_saturday_night())

    assert await provider.assemble() == await provider.assemble()


async def test_mutating_the_supplied_context_after_construction_has_no_effect() -> None:
    # Ingress: the caller keeps its reference to the context it passed in. The
    # context is fixed at construction, so a later mutation must not reach the fake.
    supplied = _saturday_night()
    provider = FakeContextProvider(supplied)

    supplied.is_weekend = False
    supplied.time_of_day = TimeOfDay.MORNING

    context = await provider.assemble()
    assert context.is_weekend is True
    assert context.time_of_day is TimeOfDay.NIGHT


async def test_mutating_a_returned_context_does_not_affect_later_calls() -> None:
    provider = FakeContextProvider(_saturday_night())

    first = await provider.assemble()
    first.is_weekend = False
    first.time_of_day = TimeOfDay.MORNING

    second = await provider.assemble()
    assert second.is_weekend is True
    assert second.time_of_day is TimeOfDay.NIGHT


async def test_the_default_context_cannot_be_corrupted_between_instances() -> None:
    # The default lives in a module-level constant shared by every instance, so a
    # leak here would contaminate unrelated test modules — the worst failure mode
    # a shared fake can have.
    first = await FakeContextProvider().assemble()
    first.is_weekend = True
    first.time_of_day = TimeOfDay.NIGHT

    fresh = await FakeContextProvider().assemble()
    assert fresh.is_weekend is False
    assert fresh.time_of_day is TimeOfDay.MORNING


async def test_counts_calls() -> None:
    provider = FakeContextProvider()
    assert provider.call_count == 0

    await provider.assemble()
    await provider.assemble()

    assert provider.call_count == 2


async def test_failure_is_raised_and_still_counted() -> None:
    # Counting the failed call too keeps `call_count` an honest record of what the
    # consumer asked for, not of what succeeded.
    provider = FakeContextProvider(failure=ContextError("no valid context"))

    with pytest.raises(ContextError, match="no valid context"):
        await provider.assemble()

    assert provider.call_count == 1


async def test_failure_repeats_as_a_distinct_instance_each_call() -> None:
    # Each call raises a fresh equivalent, never the stored instance: re-raising
    # one object would accumulate a traceback on it across calls.
    provider = FakeContextProvider(failure=ContextError("still broken"))

    raised = []
    for _ in range(2):
        with pytest.raises(ContextError, match="still broken") as caught:
            await provider.assemble()
        raised.append(caught.value)

    assert raised[0] is not raised[1]
    assert all(error.__traceback__ is not None for error in raised)


async def test_a_context_error_subclass_keeps_its_type() -> None:
    class _NarrowerContextError(ContextError):
        pass

    provider = FakeContextProvider(failure=_NarrowerContextError("specific"))

    with pytest.raises(_NarrowerContextError):
        await provider.assemble()


def test_an_out_of_contract_failure_type_is_rejected() -> None:
    # ContextError is the subsystem's failure boundary, so the canonical fake must
    # not be configurable to raise anything else — a consumer that correctly
    # catches ContextError would then fail only under test. The annotation catches
    # typed callers; this guard catches the Any-typed and untyped ones.
    with pytest.raises(TypeError, match="must be a ContextError"):
        FakeContextProvider(failure=ValueError("boom"))  # type: ignore[arg-type]


def test_context_and_failure_together_is_rejected() -> None:
    with pytest.raises(ValueError, match="not both"):
        FakeContextProvider(_saturday_night(), failure=ContextError("boom"))
