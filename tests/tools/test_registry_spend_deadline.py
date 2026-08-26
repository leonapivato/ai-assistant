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


async def test_shutdown_reaching_this_holder_mid_read_returns_without_waiting(
    wedged: tuple[InMemoryToolRegistry, SqliteAuditTrail, ThreadSuspension],
) -> None:
    """The second half §11 names: **what happens to the connection at shutdown**.

    Stated rather than asserted as a bound, for the same reason the deadline case
    above is: what is not conforming is a lane that leaves a reader believing
    something the implementation does not do.

    What this holder does is close **without waiting**. ``SqliteAuditTrail.close``
    is ``suppress(sqlite3.Error)`` around ``conn.close()`` and takes no lock, so a
    shutdown arriving while the worker is parked inside a read returns straight
    away and the parked worker finds a closed connection when it is released. That
    is safe in the running system because ADR-0083 §4 has the engine **drain**
    every tracked operation to quiescence before it closes anything — the ordering
    is the façade's, not the store's — and it is stated here because the store on
    its own does not enforce it.

    What matters at *this* seam is the half that is enforced, and it is asserted:
    the store's own error type never reaches ``tools/``. ADR-0194 §4 requires a
    backend exception to be translated rather than propagated, and a closed
    connection is exactly such a backend exception arriving from underneath.
    """
    registry, trail, parked = wedged
    definition = tool(cost=_COST)
    registry.register(definition, Spy())
    call = call_for(definition)
    await trail.record(call.decision)

    # Patient, so what the call comes back as is the *store's* answer rather than
    # ADR-0029 §4's classification of an expiry — the case above owns that half.
    running = asyncio.ensure_future(registry.invoke(call, timeout=timedelta(seconds=30)))
    await parked.reached()

    closing = asyncio.get_running_loop().run_in_executor(None, trail.close)
    await asyncio.wait_for(closing, _WAITING)
    assert not running.done(), "the read is still parked; only the connection went away"

    parked.release()
    with pytest.raises(SpendUndeterminedError) as caught:
        await asyncio.wait_for(running, _WAITING)

    assert "store could not be read" in str(caught.value)
    assert not isinstance(caught.value, sqlite3.Error), (
        "a backend exception is translated rather than propagated (ADR-0194 §4), "
        "so `tools/` never sees a store's own error type"
    )
