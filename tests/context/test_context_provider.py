"""Tests for the AssemblingContextProvider (merge, collisions, degradation)."""

from __future__ import annotations

import asyncio
import gc
import time
from collections.abc import Iterator, Mapping
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from context_provider_contract import ContextProviderContract

from ai_assistant.context import AssemblingContextProvider, ClockContextSource
from ai_assistant.context import provider as provider_module
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
    assert not provider_module._abandoned  # a cooperative source is joined, never abandoned


class _StubbornSource:
    """An optional source that swallows ``CancelledError`` and keeps going.

    Misbehaviour by Python's cancellation contract, and the shape ADR-0033 is
    about: nothing the assembler does can stop it. ``release`` lets the test
    retire it afterwards rather than leaving it running across the suite.
    """

    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.cancels = 0

    @property
    def name(self) -> str:
        return "stubborn"

    async def contribute(self) -> Mapping[str, object]:
        self.started.set()
        while not self.release.is_set():
            try:
                await asyncio.sleep(0.01)
            except asyncio.CancelledError:
                self.cancels += 1
        return {}


async def _retire(source: _StubbornSource) -> None:
    """Let a stubborn source finish, so it does not outlive its test."""
    source.release.set()
    outstanding = tuple(provider_module._abandoned)  # snapshot: the callbacks mutate the set
    async with asyncio.timeout(2):
        await asyncio.gather(*outstanding, return_exceptions=True)
    await asyncio.sleep(0)  # one turn, so the done-callbacks drop their references


async def test_a_source_that_suppresses_cancellation_cannot_stall_the_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADR-0033 §1: the required failure reaches the caller within the drain bound.

    Unbounded, this hangs forever — and so does an ``asyncio.timeout`` wrapped
    around the drain's ``gather``, because that deadline's cancellation is
    delivered into the gather, which re-cancels the same source and goes on
    awaiting it. Only ``asyncio.wait``'s observing timeout returns.

    Asserted with a *latency bound tied to the patched budget*, not merely
    eventual propagation (issue #232): an implementation that ignored the budget
    and waited seconds before abandoning the straggler would satisfy "the failure
    arrives" while violating the thing §1 decides. The ceiling is the budget plus
    generous scheduling slack, so it scales with the budget instead of sitting at
    a flat second that a seconds-scale overrun would slip under.
    """
    budget = 0.05
    monkeypatch.setattr(provider_module, "_DRAIN_SECONDS", budget)
    stubborn = _StubbornSource()
    provider = AssemblingContextProvider([_RequiredFailingSource(), stubborn], source_timeout=None)

    started = time.monotonic()
    with pytest.raises(RuntimeError, match="source down"):
        await provider.assemble()
    elapsed = time.monotonic() - started

    assert elapsed < budget + 0.5  # bounded by the drain budget, not seconds beyond it
    assert stubborn.started.is_set()
    assert stubborn.cancels >= 1  # it was cancelled, it simply declined to stop
    assert len(provider_module._abandoned) == 1  # detached, and held so it cannot vanish
    await _retire(stubborn)
    assert not provider_module._abandoned  # the reference is dropped when it finishes


class _RequiredStubbornFailingSource(_StubbornSource):
    """A straggler that fails *after* it has been abandoned.

    Marked ``required`` deliberately: ``_safe_contribute`` degrades an
    *optional* source's failure to an empty contribution, so an optional
    straggler's task can never carry an exception at all. Only a required one
    reaches the done-callback with something to retrieve.
    """

    required = True

    def __init__(self) -> None:
        super().__init__()
        self.failed = asyncio.Event()

    async def contribute(self) -> Mapping[str, object]:
        await super().contribute()
        self.failed.set()
        msg = "late failure, for a request that is already over"
        raise RuntimeError(msg)


async def test_an_abandoned_tasks_later_failure_is_consumed_and_recorded(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """ADR-0033 §3: the done-callback consumes an abandoned task's outcome.

    A straggler can still fail long after the request that spawned it. The
    callback retrieves that outcome and records its *class* — the ADR-0004 §5
    rule the degradation log already follows, applied to a failure that arrives
    with no request left to attribute it to.
    """
    configure_logging(Settings(log_level="DEBUG"))
    monkeypatch.setattr(provider_module, "_DRAIN_SECONDS", 0.05)
    stubborn = _RequiredStubbornFailingSource()
    provider = AssemblingContextProvider([_RequiredFailingSource(), stubborn], source_timeout=None)

    with pytest.raises(RuntimeError, match="source down"):
        await provider.assemble()

    assert len(provider_module._abandoned) == 1
    outstanding = tuple(provider_module._abandoned)
    stubborn.release.set()
    async with asyncio.timeout(2):
        await asyncio.wait(outstanding)
    await asyncio.sleep(0)  # one turn, for the done-callback

    assert stubborn.failed.is_set()  # it really did fail, after being abandoned
    assert not provider_module._abandoned  # and the reference was still dropped
    out = capsys.readouterr().out
    assert "abandoned context source finished" in out
    assert "RuntimeError" in out  # the class, retrieved from the task
    assert "late failure, for a request that is already over" not in out  # never the message


class _StubbornHostileNameSource(_StubbornSource):
    """A straggler whose ``name`` raises a ``BaseException`` when the log reads it."""

    @property
    def name(self) -> str:
        raise asyncio.CancelledError


async def test_a_stragglers_hostile_name_cannot_mask_the_required_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The abandonment log runs while the required failure waits to be re-raised.

    ``_safe_name`` stops at ``Exception``, so a ``name`` raising a
    ``BaseException`` would escape ``_abandon`` and *replace* the required
    source's error — the one outcome this whole path exists to deliver.
    """
    monkeypatch.setattr(provider_module, "_DRAIN_SECONDS", 0.05)
    stubborn = _StubbornHostileNameSource()
    provider = AssemblingContextProvider([_RequiredFailingSource(), stubborn], source_timeout=None)

    with pytest.raises(RuntimeError, match="source down"):
        await provider.assemble()

    assert len(provider_module._abandoned) == 1  # still abandoned, just unnamed
    await _retire(stubborn)


async def test_an_abandoned_source_is_named_in_a_warning(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """ADR-0033 §3: the log is the only signal a detached task leaves."""
    configure_logging(Settings())
    monkeypatch.setattr(provider_module, "_DRAIN_SECONDS", 0.05)
    stubborn = _StubbornSource()
    provider = AssemblingContextProvider([_RequiredFailingSource(), stubborn], source_timeout=None)

    with pytest.raises(RuntimeError, match="source down"):
        await provider.assemble()

    out = capsys.readouterr().out
    assert "outlasted the cancellation drain" in out
    assert "stubborn" in out
    await _retire(stubborn)


class _SlowUnwindingSource:
    """A source that accepts cancellation but takes a while to unwind.

    Cooperative — it re-raises — and still abandoned if its cleanup outlasts
    ``_DRAIN_SECONDS``. The budget is enforced on the clock, not on intent
    (ADR-0033 §1), because the assembler cannot observe intent.
    """

    def __init__(self, cleanup: float) -> None:
        self._cleanup = cleanup
        self.started = asyncio.Event()
        self.cleaned_up = asyncio.Event()

    @property
    def name(self) -> str:
        return "slow-unwind"

    async def contribute(self) -> Mapping[str, object]:
        self.started.set()
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            await asyncio.shield(asyncio.sleep(self._cleanup))  # an async `finally`
            self.cleaned_up.set()
            raise
        return {}


async def test_a_cooperative_source_whose_cleanup_outlasts_the_budget_is_abandoned_too(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADR-0033 §1: the budget is enforced on the clock, not on intent.

    The reviewer's case and the honest cost of §1: this source honours
    cancellation, so ADR-0026 §4's join would have completed — just not within
    the budget. It is abandoned like any other straggler, and the docstring and
    the log say "outlasted the drain" rather than "ignored cancellation" for
    exactly this reason.
    """
    monkeypatch.setattr(provider_module, "_DRAIN_SECONDS", 0.02)
    slow = _SlowUnwindingSource(cleanup=0.15)
    provider = AssemblingContextProvider([_RequiredFailingSource(), slow], source_timeout=None)

    with pytest.raises(RuntimeError, match="source down"):
        await provider.assemble()

    assert slow.started.is_set()
    assert not slow.cleaned_up.is_set()  # abandoned mid-cleanup, not joined
    assert len(provider_module._abandoned) == 1
    outstanding = tuple(provider_module._abandoned)
    async with asyncio.timeout(2):
        await asyncio.gather(*outstanding, return_exceptions=True)
    await asyncio.sleep(0)
    assert slow.cleaned_up.is_set()  # it did finish, cooperatively, after being let go
    assert not provider_module._abandoned


async def test_a_caller_cancelling_mid_drain_still_records_the_stragglers(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """ADR-0033 §3's promises must survive the drain being cancelled.

    If the caller cancels ``assemble()`` while ``_drain`` is awaiting, the
    ``await`` raises and a naive implementation skips registration entirely —
    leaving a task that outlives the method with no strong reference, no
    warning, and an outcome nobody retrieves.
    """
    configure_logging(Settings())
    monkeypatch.setattr(provider_module, "_DRAIN_SECONDS", 5.0)  # long, so we cancel mid-drain
    stubborn = _StubbornSource()
    provider = AssemblingContextProvider([_RequiredFailingSource(), stubborn], source_timeout=None)

    assembling = asyncio.ensure_future(provider.assemble())
    async with asyncio.timeout(2):
        await stubborn.started.wait()
    await asyncio.sleep(0.05)  # let the required source fail and the drain begin
    assembling.cancel()
    with pytest.raises(asyncio.CancelledError):
        await assembling

    assert len(provider_module._abandoned) == 1  # registered despite the cancellation
    # ...and reported as what it was. The drain spent 50 ms of a 5 s budget, so
    # blaming the source for outlasting it would point at the wrong party.
    out = capsys.readouterr().out
    assert "cancellation drain interrupted" in out
    assert "outlasted" not in out
    await _retire(stubborn)
    assert not provider_module._abandoned


class _LoopBlockingCleanupSource:
    """A source whose cleanup blocks the event loop instead of yielding to it."""

    def __init__(self, cleanup: float) -> None:
        self._cleanup = cleanup
        self.cleaned_up = asyncio.Event()

    @property
    def name(self) -> str:
        return "blocking"

    async def contribute(self) -> Mapping[str, object]:
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            time.sleep(self._cleanup)  # noqa: ASYNC251  the misbehaviour under test
            self.cleaned_up.set()
            raise
        return {}


async def test_the_budget_bounds_awaiting_not_wall_clock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADR-0033 Consequences: the bound is on what the assembler *awaits*.

    A source that blocks the event loop in its cleanup suspends every timer in
    the process, this drain's deadline included, so the failure is delivered
    late no matter how small the budget is. Nothing a single-threaded loop
    offers can pre-empt that — `CONTRIBUTING.md`'s "No blocking calls on async
    code paths" is what rules it out, not this drain. What the drain still owes
    is pinned here: the failure does arrive, and a source that finished while it
    held the loop is *joined*, not abandoned.
    """
    monkeypatch.setattr(provider_module, "_DRAIN_SECONDS", 0.001)
    blocking = _LoopBlockingCleanupSource(cleanup=0.15)
    provider = AssemblingContextProvider([_RequiredFailingSource(), blocking], source_timeout=None)

    started = time.monotonic()
    with pytest.raises(RuntimeError, match="source down"):
        await provider.assemble()
    elapsed = time.monotonic() - started

    assert elapsed >= 0.15  # far beyond the 1 ms budget, and unavoidably so
    assert blocking.cleaned_up.is_set()
    assert not provider_module._abandoned  # it completed while holding the loop, so it was joined


async def test_a_numeric_source_timeout_is_no_defence_against_a_suppressing_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADR-0033 §4: why forbidding ``source_timeout=None`` would buy nothing.

    ``asyncio.timeout`` delivers exactly one cancellation at its deadline, so a
    source that swallows it runs on and the deadline never fires again. Asserted
    with **no required source in the wiring**, so the drain cannot run and the
    only thing that could free the caller is ``source_timeout`` itself — which
    is set, fires, and does not.

    Observed through ``asyncio.wait`` on a task rather than by wrapping the
    ``await`` in a timeout: ``gather`` does not yield to a cancellation until
    every child has finished, so an outer deadline around ``assemble()`` is
    itself swallowed by this source (ADR-0033 Consequences).
    """
    monkeypatch.setattr(provider_module, "_DRAIN_SECONDS", 0.05)
    stubborn = _StubbornSource()
    provider = AssemblingContextProvider([_clock(), stubborn], source_timeout=0.02)

    assembling = asyncio.ensure_future(provider.assemble())
    _done, pending = await asyncio.wait([assembling], timeout=0.2)

    assert pending == {assembling}  # ten times the per-source deadline, still blocked
    assert stubborn.cancels >= 1  # that deadline fired; it was simply swallowed
    assert not provider_module._abandoned  # nothing failed, so no drain and no straggler
    stubborn.release.set()  # let it finish, so it does not outlive the test
    async with asyncio.timeout(2):
        await assembling


async def test_a_caller_timeout_around_assemble_is_honoured_against_a_suppressing_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Issue #231: with ``source_timeout=None`` the caller's own deadline must fire.

    ADR-0033 §4 offers the caller that deadline, but a bare ``gather`` on the
    success path reneged on it against a source that suppresses cancellation:
    ``gather`` does not yield a cancellation until every child has finished, so an
    ``asyncio.timeout`` wrapped around ``assemble()`` never fired and the pipeline
    hung behind the source. Observing the sources with ``asyncio.wait`` makes the
    offer real — the caller's timeout fires, and the straggler is drained and
    abandoned rather than awaited forever. No required source is involved, so the
    drain runs off the caller's cancellation alone.
    """
    budget = 0.05
    monkeypatch.setattr(provider_module, "_DRAIN_SECONDS", budget)
    stubborn = _StubbornSource()
    provider = AssemblingContextProvider([_clock(), stubborn], source_timeout=None)

    started = time.monotonic()
    with pytest.raises(TimeoutError):
        async with asyncio.timeout(0.05):
            await provider.assemble()
    elapsed = time.monotonic() - started

    assert elapsed < 0.05 + budget + 0.5  # the caller's deadline fired; it was not swallowed
    assert stubborn.cancels >= 1  # the drain cancelled it; it simply declined to stop
    assert len(provider_module._abandoned) == 1  # detached, and held so it cannot vanish
    await _retire(stubborn)
    assert not provider_module._abandoned


async def test_cancelling_the_assembling_task_propagates_past_a_suppressing_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Issue #231: a direct ``cancel()`` of ``assemble()`` must not be swallowed.

    The bare-``gather`` success path never yielded the cancellation while a
    suppressing source ran, so the ``CancelledError`` a cancelled request delivers
    vanished and the task hung. The observing ``asyncio.wait`` surfaces it, drains
    the straggler within the budget, and re-raises it to the caller.
    """
    budget = 0.05
    monkeypatch.setattr(provider_module, "_DRAIN_SECONDS", budget)
    stubborn = _StubbornSource()
    provider = AssemblingContextProvider([_clock(), stubborn], source_timeout=None)

    assembling = asyncio.ensure_future(provider.assemble())
    async with asyncio.timeout(2):
        await stubborn.started.wait()  # it is really running before we cancel
    assembling.cancel()

    started = time.monotonic()
    with pytest.raises(asyncio.CancelledError):
        await assembling
    elapsed = time.monotonic() - started

    assert elapsed < budget + 0.5  # bounded by the drain, not hung on the source
    assert stubborn.cancels >= 1
    assert len(provider_module._abandoned) == 1
    await _retire(stubborn)
    assert not provider_module._abandoned


class _RequiredCancellingSource:
    """A required source whose ``contribute()`` raises ``CancelledError`` itself.

    Its task ends *cancelled*, which ``asyncio.wait(FIRST_EXCEPTION)`` does not
    treat as a raised exception — so the assembler must scan for a cancelled task
    explicitly or a suppressing sibling holds it forever (a regression caught in
    review of the issue #231 fix).
    """

    required = True

    @property
    def name(self) -> str:
        return "cancels"

    async def contribute(self) -> Mapping[str, object]:
        raise asyncio.CancelledError


class _OtherRequiredFailingSource:
    """A second required source that fails, with a distinct message."""

    required = True

    @property
    def name(self) -> str:
        return "other-boom"

    async def contribute(self) -> Mapping[str, object]:
        msg = "second source down"
        raise RuntimeError(msg)


async def test_a_required_source_ending_in_cancellation_still_drains_and_propagates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A *cancelled* source task is terminal too, not only a raised exception.

    ``asyncio.wait(FIRST_EXCEPTION)`` would not return for a cancelled child, so a
    required source raising ``CancelledError`` beside a source that suppresses
    cancellation would hang the assembler. Looping on ``FIRST_COMPLETED`` and
    treating the cancelled task as terminal drains the sibling within the budget
    and propagates the cancellation.
    """
    budget = 0.05
    monkeypatch.setattr(provider_module, "_DRAIN_SECONDS", budget)
    stubborn = _StubbornSource()
    provider = AssemblingContextProvider(
        [_RequiredCancellingSource(), stubborn], source_timeout=None
    )

    started = time.monotonic()
    with pytest.raises(asyncio.CancelledError):
        await provider.assemble()
    elapsed = time.monotonic() - started

    assert elapsed < budget + 0.5  # bounded by the drain, not hung on the sibling
    assert stubborn.cancels >= 1
    assert len(provider_module._abandoned) == 1
    await _retire(stubborn)
    assert not provider_module._abandoned


async def test_concurrent_required_failures_leave_no_unretrieved_exception() -> None:
    """Simultaneous required failures must every one be retrieved.

    ``_first_failure`` selects one exception in source order; a sibling that
    failed in the same turn must not be left for asyncio to report as "Task
    exception was never retrieved" when it is garbage-collected. It is not,
    because ``_drain`` cancels every task before the failure is re-raised and
    ``asyncio.Task.cancel()`` marks an already-done task's exception retrieved
    (it clears ``_log_traceback`` ahead of its done-check). This pins that
    property — an implementation that stopped cancelling done siblings would
    resurrect the warning. Verified through the loop's exception handler, since
    the report only fires when the unretrieved task is collected.
    """
    loop = asyncio.get_running_loop()
    unhandled: list[dict[str, object]] = []
    previous = loop.get_exception_handler()
    loop.set_exception_handler(lambda _loop, ctx: unhandled.append(ctx))
    try:
        provider = AssemblingContextProvider(
            [_RequiredFailingSource(), _OtherRequiredFailingSource()]
        )
        with pytest.raises(RuntimeError, match="source down"):
            await provider.assemble()

        assert not provider_module._abandoned  # both failed synchronously; nothing abandoned
        del provider
        gc.collect()  # force the tasks' __del__, which is what would report an unread exception
        await asyncio.sleep(0)
    finally:
        loop.set_exception_handler(previous)

    assert not any("never retrieved" in str(ctx.get("message", "")) for ctx in unhandled)


async def test_each_assembly_abandons_its_own_straggler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADR-0033's count bound is **per assembly**, not per process.

    A permanently-suppressing source leaks one task per failing ``assemble()``,
    and repeated requests grow that set without limit. That is a real cost of
    §1's bound and is recorded as one: no cap is imposed, because the leak is
    the *task*, which exists whether or not this module holds a reference to it.
    Before the bound the count was one only because the first such failure
    deadlocked the caller and there was never a second request.
    """
    budget = 0.05
    monkeypatch.setattr(provider_module, "_DRAIN_SECONDS", budget)
    stubborn = _StubbornSource()
    provider = AssemblingContextProvider([_RequiredFailingSource(), stubborn], source_timeout=None)

    started = time.monotonic()
    for _ in range(3):
        with pytest.raises(RuntimeError, match="source down"):
            await provider.assemble()  # every call still propagates, which is the point
    elapsed = time.monotonic() - started

    assert len(provider_module._abandoned) == 3
    # Each assembly is bounded by the drain budget, not merely eventually
    # propagating (issue #232): three of them stay within three budgets plus
    # scheduling slack. An implementation that waited seconds past the budget
    # before abandoning each straggler would blow this even though the count held.
    assert elapsed < 3 * budget + 0.5
    await _retire(stubborn)
    assert not provider_module._abandoned
