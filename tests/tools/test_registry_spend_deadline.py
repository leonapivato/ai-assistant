"""``invoke`` against the **primary** spend holder, not only a cooperative fake.

ADR-0194 §11's real-producer deadline clause: "The lane drives the deadline against
the **primary** holder and not only against the suite's cancellable fake … a real
gate whose store read is wedged, reached through ``ToolInvoker.invoke`` with a short
``timeout``, and the same holder taken through shutdown while that read is
outstanding."

**What is asserted is which of ADR-0029 §4's two sides this holder's read falls
on** — stated in the test rather than inherited. "Either is conforming; what is not
conforming is a lane that writes only cooperative-fake fixtures, inherits ADR-0054's
absorption without noticing, and leaves a reader of its tests believing the deadline
is a hard bound."

**What shutdown does is *not* here.** ADR-0042 §2 makes shutdown the façade's
ordered drain-then-close, so §11's shutdown half is driven through the engine that
owns that ordering, in ``tests/app/test_composition_spend_shutdown.py``. A bare
``SqliteAuditTrail.close`` mid-read is the resource race that ordering exists to
prevent, and calling it shutdown would be describing the wrong act.

**Why here and not beside the store.** ``tests/permissions/test_sqlite_spend.py``
already pins the same fact at ``admit_invocation`` — the paired lane's half, since
the absorption is the store's. What that lane could not write is the half through
``invoke``: ``ToolInvoker`` did not consult a ``SpendGate`` until this change, so the
composition path §11 names came into existence with it and the fixture belongs with
it. The two are complementary rather than duplicated: that one measures the member,
this one measures the seam ADR-0194 §3 put it behind.

Refs: ADR-0194 §3, §11; ADR-0029 §4; ADR-0054.
"""

from __future__ import annotations

import asyncio
import sqlite3
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Final

import pytest
from tool_invoker_contract import Spy, call_for, tool

from ai_assistant.core.errors import SpendUndeterminedError
from ai_assistant.core.types import CostBasis, ToolCost
from ai_assistant.permissions.audit import SqliteAuditTrail
from ai_assistant.permissions.spend import SpendConfiguration
from ai_assistant.testing.cancellation import ThreadSuspension
from ai_assistant.tools.registry import InMemoryToolRegistry

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence
    from pathlib import Path

#: Short enough that the case does not wait on it, long enough that a loop tick is
#: not the thing under test.
_BRIEF: Final = timedelta(milliseconds=50)

#: Long enough that a released worker finishes inside it on any machine this runs on.
_WAITING: Final = 5.0

#: A priced tool, so the admission has an amount to project and the ceiling is
#: reached through arithmetic rather than short-circuited (ADR-0194 §3).
_COST: Final = ToolCost(basis=CostBasis.PER_CALL, amount=Decimal("1"), currency="USD")


@pytest.fixture
def wedged(
    tmp_path: Path,
) -> Iterator[tuple[InMemoryToolRegistry, SqliteAuditTrail, ThreadSuspension]]:
    """A real holder whose spend read parks its ``sqlite3`` worker, behind a real invoker.

    The worker is blocked **inside** the read rather than on the event loop above
    it, which is where ADR-0029 §4's third bullet lives: ``_run_to_completion``
    waits on that thread and absorbs a cancellation until it physically finishes,
    because releasing the connection while the worker still holds it would let a
    second caller use it concurrently (ADR-0054).
    """
    trail = SqliteAuditTrail(
        path=tmp_path / "audit.db",
        now=lambda: datetime(2026, 3, 3, 12, 0, tzinfo=UTC),
        spend=SpendConfiguration(currency="USD", day_ceiling=Decimal("100")),
    )
    parked = ThreadSuspension()
    original = trail._spend_rows_sync

    def blocking(low: datetime, high: datetime) -> Sequence[object]:
        parked.hold()
        return original(low, high)

    trail._spend_rows_sync = blocking  # type: ignore[method-assign, assignment]
    registry = InMemoryToolRegistry(ledger=trail, gate=trail)
    try:
        yield registry, trail, parked
    finally:
        parked.release()
        trail.close()


async def test_this_holders_wedged_read_outlives_the_deadline_invoke_was_given(
    wedged: tuple[InMemoryToolRegistry, SqliteAuditTrail, ThreadSuspension],
) -> None:
    """The deadline is **outlived**, through ``invoke``, and that is conforming.

    ADR-0194 §3 puts the admission inside the window ADR-0029 §4 already enforces,
    and is explicit that what this buys is §4's guarantee and **not a stronger
    one**: "the seam stops waiting, not that the tool stops working". §4's third
    bullet then rules this case in as many words — "a tool that suppresses its own
    cancellation can outlive its deadline, and no seam can prevent that … This is a
    genuine hole and the honest position is that it is unclosable from this side".

    So what is measured is the fact rather than a bound this holder does not have:
    with the worker parked, ``invoke`` is **still running** well past the 50 ms
    ``timeout`` it was given, and it returns only once the worker is released.

    A reader looking for the hard bound should read that sentence and not this
    module's absence of one.
    """
    registry, _trail, parked = wedged
    definition = tool(cost=_COST)
    registry.register(definition, Spy())
    call = call_for(definition)
    await _trail.record(call.decision)

    running = asyncio.ensure_future(registry.invoke(call, timeout=_BRIEF))
    await parked.reached()
    await asyncio.sleep(_BRIEF.total_seconds() * 4)

    assert not running.done(), (
        "this holder's read absorbs its own cancellation (ADR-0054), so `invoke` "
        "outlives the deadline it was given — ADR-0029 §4's third bullet, unchanged"
    )

    parked.release()
    result = await asyncio.wait_for(running, _WAITING)
    assert result is not None


async def test_a_backend_failure_under_that_read_never_reaches_tools_as_its_own_type(
    wedged: tuple[InMemoryToolRegistry, SqliteAuditTrail, ThreadSuspension],
) -> None:
    """ADR-0194 §4: "a backend exception is translated rather than propagated".

    The failure is produced the way a real one arrives — from underneath, out of
    the ``sqlite3`` worker — rather than by raising a chosen class at the member.
    The connection is closed while the worker is parked inside the read, so the
    read meets a closed database when it is released, which is a genuine backend
    exception and not one this case authored.

    **This is not shutdown**, and is deliberately not called that: ``close`` takes
    no lock, so a bare one mid-read is the resource race ADR-0042 §2's ordered
    drain exists to prevent. What §11 asks about shutdown is driven through the
    façade that owns that ordering, in
    ``tests/app/test_composition_spend_shutdown.py``. What is here is the seam
    property alone — that ``tools/`` never sees a store's own error type, whatever
    the store's own error happens to be.
    """
    registry, trail, parked = wedged
    definition = tool(cost=_COST)
    registry.register(definition, Spy())
    call = call_for(definition)
    await trail.record(call.decision)

    # Patient, so what comes back is the *store's* answer rather than ADR-0029 §4's
    # classification of an expiry — the case above owns that half.
    running = asyncio.ensure_future(registry.invoke(call, timeout=timedelta(seconds=30)))
    await parked.reached()
    await asyncio.get_running_loop().run_in_executor(None, trail.close)
    parked.release()

    with pytest.raises(SpendUndeterminedError) as caught:
        await asyncio.wait_for(running, _WAITING)

    assert "store could not be read" in str(caught.value)
    assert not isinstance(caught.value, sqlite3.Error), (
        "a backend exception is translated rather than propagated (ADR-0194 §4), "
        "so `tools/` never sees a store's own error type"
    )
