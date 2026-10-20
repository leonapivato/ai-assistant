"""Shared conformance suites for ADR-0314's two diagnostic-record Protocols (§8).

Every ``DiagnosticSink`` implementation must pass :class:`DiagnosticSinkContract`, and
every ``DiagnosticRetention`` implementation :class:`DiagnosticRetentionContract`. A
concrete test subclasses what it implements and supplies its subject fixture and the
suite's window on it — the window being the *test's*, since neither Protocol carries a
read (§3).

**What is deliberately not in here.** The file's shape, its owner-only modes and its
byte bound (§6, §2:3) are the durable store's own: a sink with no file has no mode and
no bound to keep, so they are pinned in ``test_diagnostic_record.py`` against the store.

Named ``*_contracts`` (not ``test_*``) so pytest collects it only through a
``Test``-prefixed subclass.
"""

from __future__ import annotations

import asyncio
import contextlib
from datetime import timedelta
from typing import TYPE_CHECKING, Any

import pytest
import structlog

from ai_assistant.core.diagnostics import DIAGNOSTIC_NOT_WRITTEN
from ai_assistant.core.errors import DiagnosticRecordError
from ai_assistant.core.types import DiagnosticKind, DiagnosticSource
from ai_assistant.testing import diagnostic_entry
from ai_assistant.testing.cancellation import settle
from ai_assistant.testing.diagnostics import (
    DEFAULT_DIAGNOSED_ACTIVATION,
    DEFAULT_RECORDED_AT,
    UNREADABLE_DIAGNOSTIC_FIELD,
)

if TYPE_CHECKING:
    from collections.abc import Coroutine, Mapping, Sequence
    from contextlib import AbstractAsyncContextManager
    from datetime import datetime

    from ai_assistant.core.protocols import DiagnosticRetention, DiagnosticSink
    from ai_assistant.core.types import DiagnosticEntry
    from ai_assistant.testing.cancellation import SuspendedMidWrite

_RELEASED_EARLY = (
    "the cancelled call released its resource while its own work was still using it (ADR-0060 §3)"
)

#: A second activation, so a case can say "another file".
_OTHER = "9a1c7e52-6b3d-4f80-8e2a-1c5d7b9f0e46"

#: Ids no file may be named by (§6:1); one ending ``.observer`` would name its own file
#: like an observer's (ADR-0333 §3:1).
_NOT_PLAIN = ("", ".", "..", "../escape", "a/b", "x\0y", "e" * 250, "x.observer")

#: Text an entry's body carries, which no log record may (§2:4, ADR-0004 §5).
_CONTENT = "the user's private words"


def _not_written(captured: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """The not-written records among ``captured`` structlog events."""
    return [one for one in captured if one.get("event") == DIAGNOSTIC_NOT_WRITTEN]


async def _assert_holds_its_resource(
    harness: SuspendedMidWrite[Any],
    operation: str,
    first: Coroutine[Any, Any, object],
    second: Coroutine[Any, Any, object],
) -> None:
    """ADR-0060 §3's choreography: cancel inside the resource, then race a second caller.

    Raises:
        AssertionError: If the resource was handed over early, or the first call did
            not re-raise its cancellation.
    """
    suspended = harness.arm(operation)
    started = asyncio.ensure_future(first)
    follower: asyncio.Task[object] | None = None
    try:
        await suspended.reached()
        started.cancel()
        await settle()
        follower = asyncio.ensure_future(second)
        await settle()
        assert not follower.done(), _RELEASED_EARLY
        suspended.release()
        with pytest.raises(asyncio.CancelledError):
            await started
        await follower
        assert not harness.log.overlapped, _RELEASED_EARLY
    finally:
        suspended.release()
        started.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await started
        if follower is not None:
            follower.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await follower


class _Cancellation:
    """The hook both suites' ADR-0060 case shares."""

    def subject_suspended_mid_operation(
        self,
    ) -> AbstractAsyncContextManager[SuspendedMidWrite[Any]]:
        """Supply a subject whose named operation can be stopped inside its resource.

        Raises:
            NotImplementedError: Until a binding overrides it.
        """
        raise NotImplementedError


class DiagnosticSinkContract(_Cancellation):
    """What every ``DiagnosticSink`` owes (ADR-0314 §2:4-§2:5, §6:1-§6:2)."""

    @pytest.fixture
    def sink(self) -> DiagnosticSink:
        """The subject: a sink holding nothing."""
        raise NotImplementedError

    async def recorded(
        self, sink: DiagnosticSink, activation_id: str
    ) -> tuple[DiagnosticEntry, ...]:
        """What ``sink`` holds for ``activation_id``, in the order written.

        The suite's window, not a seam: the Protocol has no read.
        """
        raise NotImplementedError

    def failing_sink(self) -> DiagnosticSink:
        """A sink whose backing store fails every write, by its own natural fault."""
        raise NotImplementedError

    async def test_a_written_entry_is_recorded(self, sink: DiagnosticSink) -> None:
        """The base case, so nothing below passes vacuously."""
        entry = diagnostic_entry(body={"text": _CONTENT})

        await sink.write(entry)

        assert await self.recorded(sink, DEFAULT_DIAGNOSED_ACTIVATION) == (entry,)

    async def test_write_returns_nothing(self, sink: DiagnosticSink) -> None:
        """A writer learns nothing back: the record answers no question (§3:1)."""
        assert await sink.write(diagnostic_entry()) is None  # type: ignore[func-returns-value]

    async def test_entries_keep_the_order_they_were_written_in_per_activation(
        self, sink: DiagnosticSink
    ) -> None:
        """§6:2: appended in the order written, each activation's apart."""
        first = diagnostic_entry(kind=DiagnosticKind.GIVEN, body={"n": 1})
        other = diagnostic_entry(_OTHER, source=DiagnosticSource.RECALL, body={"n": 2})
        second = diagnostic_entry(kind=DiagnosticKind.RETURNED, body={"n": 3})

        for one in (first, other, second):
            await sink.write(one)

        assert await self.recorded(sink, DEFAULT_DIAGNOSED_ACTIVATION) == (first, second)
        assert await self.recorded(sink, _OTHER) == (other,)

    async def test_the_recorded_entry_is_detached_from_the_callers_object(
        self, sink: DiagnosticSink
    ) -> None:
        """``frozen=True`` refuses ``x.kind = …`` and not ``x.__dict__["kind"] = …``."""
        entry = diagnostic_entry(kind=DiagnosticKind.GIVEN)
        await sink.write(entry)

        entry.__dict__["kind"] = DiagnosticKind.STEP

        held = await self.recorded(sink, DEFAULT_DIAGNOSED_ACTIVATION)
        assert [one.kind for one in held] == [DiagnosticKind.GIVEN]

    @pytest.mark.parametrize("activation_id", _NOT_PLAIN)
    async def test_an_id_that_is_not_a_plain_file_name_is_refused_and_logged(
        self, sink: DiagnosticSink, activation_id: str
    ) -> None:
        """§6:1: no file for such an id; the refusal is logged, and names no id."""
        entry = diagnostic_entry(body={"text": _CONTENT}).model_copy(
            update={"activation_id": activation_id}
        )

        with structlog.testing.capture_logs() as captured:
            await sink.write(entry)

        assert await self.recorded(sink, activation_id) == ()
        records = _not_written(captured)
        assert len(records) == 1
        assert records[0]["activation_id"] == UNREADABLE_DIAGNOSTIC_FIELD
        assert _CONTENT not in repr(captured)

    async def test_a_store_fault_does_not_escape_and_is_logged_without_content(self) -> None:
        """§2:4: the work goes on; the log names activation, source and class alone."""
        sink = self.failing_sink()

        with structlog.testing.capture_logs() as captured:
            await sink.write(diagnostic_entry(body={"text": _CONTENT}))

        records = _not_written(captured)
        assert len(records) == 1
        assert records[0]["activation_id"] == DEFAULT_DIAGNOSED_ACTIVATION
        assert records[0]["source"] == DiagnosticSource.PLANNING.value
        assert isinstance(records[0]["error_class"], str)
        assert _CONTENT not in repr(captured)

    async def test_a_cancelled_write_is_re_raised_and_keeps_its_resource(self) -> None:
        """§2:5, ADR-0060 §3: the write finishes inside its resource, then cancels."""
        async with self.subject_suspended_mid_operation() as harness:
            sink: DiagnosticSink = harness.store
            await _assert_holds_its_resource(
                harness,
                "write",
                sink.write(diagnostic_entry(body={"n": 1})),
                sink.write(diagnostic_entry(body={"n": 2})),
            )


class DiagnosticRetentionContract(_Cancellation):
    """What every ``DiagnosticRetention`` owes (ADR-0314 §7:2)."""

    @pytest.fixture
    def retention(self) -> DiagnosticRetention:
        """The subject: a record holding no file."""
        raise NotImplementedError

    async def hold(
        self, retention: DiagnosticRetention, activation_id: str, last_write: datetime
    ) -> None:
        """Arrange a file for ``activation_id`` last written at ``last_write``."""
        raise NotImplementedError

    async def remaining(self, retention: DiagnosticRetention) -> frozenset[str]:
        """The activations whose files ``retention`` still holds."""
        raise NotImplementedError

    def failing_retention(self) -> DiagnosticRetention:
        """A record whose sweep fails, by its own natural fault."""
        raise NotImplementedError

    async def test_a_file_older_than_the_instant_is_deleted_and_counted(
        self, retention: DiagnosticRetention
    ) -> None:
        """Only age deletes a file, and the count says how many went."""
        await self.hold(retention, DEFAULT_DIAGNOSED_ACTIVATION, DEFAULT_RECORDED_AT)
        await self.hold(retention, _OTHER, DEFAULT_RECORDED_AT + timedelta(hours=2))

        deleted = await retention.purge_before(DEFAULT_RECORDED_AT + timedelta(hours=1))

        assert deleted == 1
        assert await self.remaining(retention) == frozenset({_OTHER})

    async def test_a_file_written_at_the_instant_is_kept(
        self, retention: DiagnosticRetention
    ) -> None:
        """Strictly older: a file last written at the edge stays."""
        await self.hold(retention, DEFAULT_DIAGNOSED_ACTIVATION, DEFAULT_RECORDED_AT)

        assert await retention.purge_before(DEFAULT_RECORDED_AT) == 0
        assert await self.remaining(retention) == frozenset({DEFAULT_DIAGNOSED_ACTIVATION})

    async def test_an_empty_record_sweeps_to_nothing(self, retention: DiagnosticRetention) -> None:
        """No file, no directory: zero, not a failure."""
        assert await retention.purge_before(DEFAULT_RECORDED_AT) == 0

    async def test_a_sweep_that_cannot_run_raises(self) -> None:
        """A sweep is not the work described, so it raises rather than doing nothing."""
        with pytest.raises(DiagnosticRecordError):
            await self.failing_retention().purge_before(DEFAULT_RECORDED_AT)

    async def test_a_cancelled_sweep_is_re_raised_and_keeps_its_resource(self) -> None:
        """ADR-0060 §3: the sweep finishes inside its resource, then cancels."""
        async with self.subject_suspended_mid_operation() as harness:
            retention: DiagnosticRetention = harness.store
            await _assert_holds_its_resource(
                harness,
                "purge_before",
                retention.purge_before(DEFAULT_RECORDED_AT),
                retention.purge_before(DEFAULT_RECORDED_AT),
            )
