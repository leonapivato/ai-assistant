"""Tests for the AssemblingContextProvider (merge, collisions, degradation)."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator, Mapping
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from context_provider_contract import ContextProviderContract

from ai_assistant.context import AssemblingContextProvider, ClockContextSource
from ai_assistant.core.config import Settings
from ai_assistant.core.errors import ContextError
from ai_assistant.core.logging import configure_logging
from ai_assistant.core.types import CurrentContext, TimeOfDay

if TYPE_CHECKING:
    from ai_assistant.core.protocols import ContextProvider

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


class _LeakySource:
    """A source whose failure message quotes the personal data it was fetching.

    The realistic shape of the ADR-0004 §5 hazard: a calendar or email source
    raising ``RuntimeError(f"could not parse {record}")``.
    """

    @property
    def name(self) -> str:
        return "records"

    async def contribute(self) -> Mapping[str, object]:
        msg = "could not parse record: PATIENT SSN 123-45-6789"
        raise RuntimeError(msg)


class _FailingNameSource:
    """A pathological source whose contribute *and* name both raise."""

    @property
    def name(self) -> str:
        msg = "name unavailable"
        raise RuntimeError(msg)

    async def contribute(self) -> Mapping[str, object]:
        msg = "source down"
        raise RuntimeError(msg)


class _HangingSource:
    """A source whose contribute() never completes, to exercise the timeout."""

    @property
    def name(self) -> str:
        return "hang"

    async def contribute(self) -> Mapping[str, object]:
        await asyncio.Event().wait()  # never set → hangs until cancelled
        return {}


class _ExplodingMapping(Mapping[str, object]):
    """A Mapping whose iteration raises, mimicking a lazy/faulting contribution."""

    def __getitem__(self, key: str) -> object:
        raise KeyError(key)

    def __iter__(self) -> Iterator[str]:
        msg = "lazy decode failed"
        raise RuntimeError(msg)

    def __len__(self) -> int:
        return 1


class _LazyFailSource:
    """A source that returns successfully, but whose mapping faults on use."""

    @property
    def name(self) -> str:
        return "lazy"

    async def contribute(self) -> Mapping[str, object]:
        return _ExplodingMapping()


def _clock() -> ClockContextSource:
    return ClockContextSource(now=lambda: _THU_2PM)


class TestAssemblingContextProviderContract(ContextProviderContract):
    """Runs AssemblingContextProvider through the shared ContextProvider suite."""

    @pytest.fixture
    def provider(self) -> ContextProvider:
        # The clock source alone supplies the whole required core, so this is the
        # minimal wiring that assembles a valid context.
        return AssemblingContextProvider([_clock()])


async def test_assembles_context_from_the_clock_source() -> None:
    provider = AssemblingContextProvider([_clock()])

    ctx = await provider.assemble()

    assert isinstance(ctx, CurrentContext)
    assert ctx.now == _THU_2PM
    assert ctx.time_of_day is TimeOfDay.AFTERNOON
    assert ctx.is_weekend is False
    assert ctx.within_working_hours is True


async def test_each_assembly_recomputes_from_the_clock() -> None:
    # Assembly is per-request: a provider that read its sources once and served a
    # cached context forever would satisfy the shared contract (which asserts only
    # a distinct object, since a wall-clock provider's facets may legitimately
    # change between calls) while breaking ADR-0008. An advancing clock is what
    # distinguishes the two, so it is pinned here rather than in the suite.
    instants = iter([_THU_2PM, _THU_2PM + timedelta(hours=7)])  # 14:00 → 21:00
    provider = AssemblingContextProvider([ClockContextSource(now=lambda: next(instants))])

    first = await provider.assemble()
    second = await provider.assemble()

    assert first.now == _THU_2PM
    assert second.now == _THU_2PM + timedelta(hours=7)
    assert first.time_of_day is TimeOfDay.AFTERNOON
    assert second.time_of_day is TimeOfDay.NIGHT  # recomputed, not cached


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


async def test_degradation_log_carries_the_error_class_not_its_message(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # ADR-0004 §5: a context source wraps calendars, tasks and email, so its
    # exception message can quote the very Tier 1 data it was fetching. The
    # degradation log records the failure's class only.
    #
    # Asserted through the configured processor chain and rendered output, not
    # structlog.testing.capture_logs — that fixture replaces the processor chain,
    # so a test written against it would pass while production leaked. Note the
    # key-based redaction net cannot save us here: `error` looks innocuous, which
    # is exactly why the call site has to get this right.
    configure_logging(Settings())
    provider = AssemblingContextProvider([_clock(), _LeakySource()])

    await provider.assemble()

    out = capsys.readouterr().out
    assert "PATIENT SSN 123-45-6789" not in out
    assert "RuntimeError" in out


async def test_degradation_survives_a_source_whose_name_also_raises() -> None:
    # The degradation path must not itself raise while resolving a failing
    # source's name; the clock still supplies the required core.
    provider = AssemblingContextProvider([_clock(), _FailingNameSource()])

    ctx = await provider.assemble()

    assert ctx.time_of_day is TimeOfDay.AFTERNOON


async def test_hung_source_times_out_and_degrades() -> None:
    # A source that never returns must not stall assembly; it times out and the
    # clock still supplies the required core.
    provider = AssemblingContextProvider([_clock(), _HangingSource()], source_timeout=0.05)

    ctx = await provider.assemble()

    assert ctx.time_of_day is TimeOfDay.AFTERNOON


async def test_faulting_returned_mapping_degrades() -> None:
    # A source that returns a mapping which raises on consumption degrades within
    # _safe_contribute rather than leaking into the merge loop.
    provider = AssemblingContextProvider([_clock(), _LazyFailSource()])

    ctx = await provider.assemble()

    assert ctx.time_of_day is TimeOfDay.AFTERNOON


async def test_failing_required_source_surfaces_as_context_error() -> None:
    # If the *only* source (supplying required fields) fails, degradation leaves
    # nothing to build a valid context from — that is a ContextError, not a crash.
    provider = AssemblingContextProvider([_FailingSource()])

    with pytest.raises(ContextError, match="could not assemble a valid context"):
        await provider.assemble()
