"""Tests for the AssemblingContextProvider (merge, collisions, degradation)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from ai_assistant.context import AssemblingContextProvider, ClockContextSource
from ai_assistant.core.errors import ContextError
from ai_assistant.core.protocols import ContextProvider
from ai_assistant.core.types import CurrentContext, TimeOfDay

if TYPE_CHECKING:
    from collections.abc import Mapping

_THU_2PM = datetime(2026, 1, 1, 14, tzinfo=UTC)


class _StaticSource:
    """A source that returns a fixed contribution."""

    def __init__(self, name: str, contribution: Mapping[str, object]) -> None:
        self._name = name
        self._contribution = contribution

    @property
    def name(self) -> str:
        return self._name

    async def contribute(self) -> Mapping[str, object]:
        return self._contribution


class _FailingSource:
    """A source that always raises, to exercise graceful degradation."""

    @property
    def name(self) -> str:
        return "boom"

    async def contribute(self) -> Mapping[str, object]:
        msg = "source down"
        raise RuntimeError(msg)


def _clock() -> ClockContextSource:
    return ClockContextSource(now=lambda: _THU_2PM)


def test_conforms_to_provider_protocol() -> None:
    assert isinstance(AssemblingContextProvider([]), ContextProvider)


async def test_assembles_context_from_the_clock_source() -> None:
    provider = AssemblingContextProvider([_clock()])

    ctx = await provider.assemble()

    assert isinstance(ctx, CurrentContext)
    assert ctx.now == _THU_2PM
    assert ctx.time_of_day is TimeOfDay.AFTERNOON
    assert ctx.is_weekend is False
    assert ctx.within_working_hours is True


async def test_colliding_sources_raise_context_error() -> None:
    provider = AssemblingContextProvider(
        [_StaticSource("a", {"is_weekend": True}), _StaticSource("b", {"is_weekend": False})]
    )

    with pytest.raises(ContextError, match="collided on field 'is_weekend'"):
        await provider.assemble()


async def test_missing_required_field_raises_context_error() -> None:
    # No source supplies the required temporal fields, so no valid context exists.
    provider = AssemblingContextProvider([_StaticSource("partial", {"is_weekend": True})])

    with pytest.raises(ContextError, match="could not assemble a valid context"):
        await provider.assemble()


async def test_failing_source_is_skipped_not_fatal() -> None:
    # The clock still supplies the required core; the failing source degrades away.
    provider = AssemblingContextProvider([_clock(), _FailingSource()])

    ctx = await provider.assemble()

    assert ctx.time_of_day is TimeOfDay.AFTERNOON  # assembled despite the failure


async def test_failing_required_source_surfaces_as_context_error() -> None:
    # If the *only* source (supplying required fields) fails, degradation leaves
    # nothing to build a valid context from — that is a ContextError, not a crash.
    provider = AssemblingContextProvider([_FailingSource()])

    with pytest.raises(ContextError, match="could not assemble a valid context"):
        await provider.assemble()
