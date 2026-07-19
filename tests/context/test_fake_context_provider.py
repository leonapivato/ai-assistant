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


async def test_mutating_a_returned_context_does_not_affect_later_calls() -> None:
    provider = FakeContextProvider(_saturday_night())

    first = await provider.assemble()
    first.is_weekend = False
    first.time_of_day = TimeOfDay.MORNING

    second = await provider.assemble()
    assert second.is_weekend is True
    assert second.time_of_day is TimeOfDay.NIGHT


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


async def test_failure_repeats_on_every_call() -> None:
    provider = FakeContextProvider(failure=ContextError("still broken"))

    for _ in range(2):
        with pytest.raises(ContextError):
            await provider.assemble()


def test_context_and_failure_together_is_rejected() -> None:
    with pytest.raises(ValueError, match="not both"):
        FakeContextProvider(_saturday_night(), failure=ContextError("boom"))
