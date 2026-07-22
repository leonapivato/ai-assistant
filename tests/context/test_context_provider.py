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
    from collections.abc import Sequence

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

    def provider_with_advancing_clock(self) -> tuple[ContextProvider, Sequence[datetime]]:
        instants = (_THU_2PM, _THU_2PM + timedelta(hours=7))  # 14:00 → 21:00
        scripted = iter(instants)
        provider = AssemblingContextProvider([ClockContextSource(now=lambda: next(scripted))])
        return provider, instants


async def test_assembles_context_from_the_clock_source() -> None:
    provider = AssemblingContextProvider([_clock()])

    ctx = await provider.assemble()

    assert isinstance(ctx, CurrentContext)
    assert ctx.now == _THU_2PM
    assert ctx.time_of_day is TimeOfDay.AFTERNOON
    assert ctx.is_weekend is False
    assert ctx.within_working_hours is True


async def test_the_derived_facets_recompute_not_just_the_instant() -> None:
    # The shared suite's freshness test asserts `now` tracks the advancing clock.
    # This pins the stronger property for this implementation: the *derived* facets
    # are recomputed from that instant too, rather than `now` being refreshed over
    # a set of facets cached from the first assembly.
    instants = iter([_THU_2PM, _THU_2PM + timedelta(hours=7)])  # 14:00 → 21:00
    provider = AssemblingContextProvider([ClockContextSource(now=lambda: next(instants))])

    first = await provider.assemble()
    second = await provider.assemble()

    assert first.time_of_day is TimeOfDay.AFTERNOON
    assert second.time_of_day is TimeOfDay.NIGHT


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


class _RequiredFailingSource(_FailingSource):
    """A source that carries the ADR-0026 §4 marker and fails."""

    required = True


class _RequiredHangingSource(_HangingSource):
    """A required source that never returns, so the timeout path is covered too."""

    required = True


class _RequiredMarkerRaises:
    """A source whose ``required`` marker itself raises when read."""

    @property
    def name(self) -> str:
        return "shifty"

    @property
    def required(self) -> bool:
        msg = "even the marker is hostile"
        raise RuntimeError(msg)

    async def contribute(self) -> Mapping[str, object]:
        msg = "source down"
        raise RuntimeError(msg)


async def test_a_required_sources_failure_reaches_the_caller_with_its_cause() -> None:
    """ADR-0026 §4: the clock's failure must not be degraded into silence.

    Without the marker, ``_safe_contribute`` swallows it and the caller sees only
    a later "could not assemble a valid context" from the missing fields — the
    owner label and the cause both lost. Asserted on the *original* exception,
    since preserving it is the whole point.
    """
    provider = AssemblingContextProvider([_RequiredFailingSource()])

    with pytest.raises(RuntimeError, match="source down"):
        await provider.assemble()


async def test_a_required_sources_timeout_also_reaches_the_caller() -> None:
    """The other degradation path. A required source cannot be skipped either way."""
    provider = AssemblingContextProvider([_RequiredHangingSource()], source_timeout=0.01)

    with pytest.raises(TimeoutError):
        await provider.assemble()


async def test_the_clock_sources_context_error_is_not_degraded() -> None:
    """The concrete case the marker exists for, end to end through the provider."""
    naive = ClockContextSource(now=lambda: datetime(2026, 1, 1, 14))  # noqa: DTZ001
    provider = AssemblingContextProvider([naive])

    with pytest.raises(ContextError, match="ClockContextSource"):
        await provider.assemble()


async def test_an_optional_source_with_no_required_attribute_still_degrades() -> None:
    """Absent means optional, which is why the marker is not a Protocol member.

    ``_FailingSource`` implements ``name`` and ``contribute`` only — exactly the
    shape a ``Protocol`` member would have made non-conforming, and on which a
    bare ``source.required`` would raise ``AttributeError`` inside the very
    degradation path it was meant to select.
    """
    assert not hasattr(_FailingSource(), "required")
    provider = AssemblingContextProvider([_clock(), _FailingSource()])

    ctx = await provider.assemble()

    assert ctx.time_of_day is TimeOfDay.AFTERNOON


async def test_an_optional_source_raising_context_error_still_degrades() -> None:
    """The reason the decision is on the marker and not on the error's type.

    A future optional source is entitled to raise ``ContextError``; typing the
    decision would make it abort the request, which is the degradation rule
    ADR-0008 §4 keeps.
    """

    class _OptionalContextErrorSource:
        @property
        def name(self) -> str:
            return "optional"

        async def contribute(self) -> Mapping[str, object]:
            msg = "optional, and unhappy"
            raise ContextError(msg)

    provider = AssemblingContextProvider([_clock(), _OptionalContextErrorSource()])

    ctx = await provider.assemble()

    assert ctx.time_of_day is TimeOfDay.AFTERNOON


async def test_a_source_whose_required_marker_raises_is_read_as_optional() -> None:
    """The degradation path must not itself fail on a misbehaving source.

    Same defensiveness ``_safe_name`` already applies: a marker that cannot
    answer is absent, and absent means optional.
    """
    provider = AssemblingContextProvider([_clock(), _RequiredMarkerRaises()])

    ctx = await provider.assemble()

    assert ctx.time_of_day is TimeOfDay.AFTERNOON


class _WatchedHangingSource:
    """An optional source that blocks forever and records being cancelled."""

    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.cancelled = False

    @property
    def name(self) -> str:
        return "slow"

    async def contribute(self) -> Mapping[str, object]:
        self.started.set()
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        return {}


async def test_a_required_failure_cancels_its_still_running_siblings() -> None:
    """``asyncio.gather`` propagates the first failure but does not cancel the rest.

    Unreachable before ADR-0026 §4's required sources — ``_safe_contribute``
    degraded everything, so gather never raised. Now a fast-failing required
    source beside an optional one blocked in I/O would leave that source running
    after the caller has its failure: to its own timeout, or forever with
    ``source_timeout=None``, still able to perform a late side effect for a
    request that is over.
    """
    slow = _WatchedHangingSource()
    provider = AssemblingContextProvider([_RequiredFailingSource(), slow], source_timeout=None)

    with pytest.raises(RuntimeError, match="source down"):
        await provider.assemble()

    assert slow.started.is_set()  # it really was running, so cancelling it meant something
    assert slow.cancelled  # and it is finished, not merely abandoned
