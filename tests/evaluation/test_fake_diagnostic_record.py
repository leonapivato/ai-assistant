"""The two canonical diagnostic-record fakes, run through their shared suites (ADR-0314 §8).

One binding per Protocol, because the triad is per Protocol: ``FakeDiagnosticSink``
answers for ``DiagnosticSink`` and ``FakeDiagnosticRetention`` for
``DiagnosticRetention``. The cases at the bottom pin the fakes' own levers.
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, Any

import pytest
from diagnostic_contracts import DiagnosticRetentionContract, DiagnosticSinkContract

from ai_assistant.core.types import DiagnosticKind, DiagnosticSource
from ai_assistant.testing import FakeDiagnosticRetention, FakeDiagnosticSink, diagnostic_entry
from ai_assistant.testing.cancellation import SuspendedMidWrite
from ai_assistant.testing.diagnostics import DEFAULT_RECORDED_AT

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from datetime import datetime

    from ai_assistant.core.protocols import DiagnosticRetention, DiagnosticSink
    from ai_assistant.core.types import DiagnosticEntry


def _suspended[T: FakeDiagnosticSink | FakeDiagnosticRetention](
    subject: T,
) -> SuspendedMidWrite[T]:
    """Wrap ``subject`` as the harness ADR-0060's case drives."""
    return SuspendedMidWrite(
        store=subject,
        log=subject.resource.log,
        arm=lambda _operation: subject.resource.suspend_next(),
    )


class TestFakeDiagnosticSinkContract(DiagnosticSinkContract):
    """Runs ``FakeDiagnosticSink`` through the shared ``DiagnosticSink`` suite."""

    @pytest.fixture
    def sink(self) -> DiagnosticSink:
        return FakeDiagnosticSink()

    async def recorded(
        self, sink: DiagnosticSink, activation_id: str
    ) -> tuple[DiagnosticEntry, ...]:
        assert isinstance(sink, FakeDiagnosticSink)
        return tuple(one for one in sink.recorded if one.activation_id == activation_id)

    def failing_sink(self) -> DiagnosticSink:
        sink = FakeDiagnosticSink()
        sink.fail_write()
        return sink

    @contextlib.asynccontextmanager
    async def subject_suspended_mid_operation(self) -> AsyncIterator[SuspendedMidWrite[Any]]:
        """The fake models the resource it does not really own (ADR-0060 §3).

        Yields:
            The harness.
        """
        yield _suspended(FakeDiagnosticSink())


class TestFakeDiagnosticRetentionContract(DiagnosticRetentionContract):
    """Runs ``FakeDiagnosticRetention`` through the shared ``DiagnosticRetention`` suite."""

    @pytest.fixture
    def retention(self) -> DiagnosticRetention:
        return FakeDiagnosticRetention()

    async def hold(
        self, retention: DiagnosticRetention, activation_id: str, last_write: datetime
    ) -> None:
        assert isinstance(retention, FakeDiagnosticRetention)
        retention.hold(activation_id, last_write)

    async def remaining(self, retention: DiagnosticRetention) -> frozenset[str]:
        assert isinstance(retention, FakeDiagnosticRetention)
        return retention.remaining

    def failing_retention(self) -> DiagnosticRetention:
        retention = FakeDiagnosticRetention()
        retention.fail_purge()
        return retention

    @contextlib.asynccontextmanager
    async def subject_suspended_mid_operation(self) -> AsyncIterator[SuspendedMidWrite[Any]]:
        """As above.

        Yields:
            The harness.
        """
        yield _suspended(FakeDiagnosticRetention())


async def test_the_sink_reads_back_by_source_and_kind_for_a_test() -> None:
    """``of`` is the emitter tests' window: one source's entries of one kind, in order."""
    sink = FakeDiagnosticSink()
    given = diagnostic_entry(source=DiagnosticSource.RECALL, kind=DiagnosticKind.GIVEN)
    returned = diagnostic_entry(source=DiagnosticSource.RECALL, kind=DiagnosticKind.RETURNED)
    await sink.write(given)
    await sink.write(diagnostic_entry(source=DiagnosticSource.PLANNING))
    await sink.write(returned)

    assert sink.of(DiagnosticSource.RECALL) == (given, returned)
    assert sink.of(DiagnosticSource.RECALL, DiagnosticKind.RETURNED) == (returned,)


async def test_the_retention_fake_remembers_each_instant_it_was_asked_to_sweep() -> None:
    """``purged_at`` is how an engine test sees the horizon it computed."""
    retention = FakeDiagnosticRetention()

    await retention.purge_before(DEFAULT_RECORDED_AT)

    assert retention.purged_at == (DEFAULT_RECORDED_AT,)
