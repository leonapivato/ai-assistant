"""Shutdown reaching the spend holder while an **invocation's** admission is wedged.

ADR-0194 §11's shutdown clause, in the one composition that discharges it: "a real
gate whose store read is wedged, reached through ``ToolInvoker.invoke`` … and the
same holder taken through shutdown while that read is outstanding."

**Why the two halves have to be one case.** Driving a wedged read through a *direct*
engine operation proves the drain covers that operation; driving a wedged read
through ``invoke`` proves what the seam does with the deadline. Neither proves the
thing this clause is actually about — that an in-flight tool invocation is inside
the tracked set the façade drains, so that shutdown cannot close the shared audit
connection out from under an admission. A composition where the invocation's
admission ran detached would satisfy both split cases and fail this one.

**The path is a parked confirmation resumed**, which is the one engine operation
that reaches ``ToolInvoker.invoke`` without a model in the loop: the parking turn
records the ruling, and ``resume`` executes the step through the runner, the
executor and the invoker — the real ``InMemoryToolRegistry``, admitting through the
real ``SqliteAuditTrail``, which is also the trail the runner recorded into and the
resource the façade closes. One object, four faces, all the way down (ADR-0194 §5).

Refs: ADR-0194 §3, §5, §11; ADR-0042 §2; ADR-0083 §4; ADR-0054.
"""

from __future__ import annotations

import asyncio
import sqlite3
from datetime import timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Final

import pytest
from test_engine_contract import _wire

from ai_assistant.core.types import Disposition, StepStatus
from ai_assistant.permissions.audit import SqliteAuditTrail
from ai_assistant.permissions.spend import SpendConfiguration
from ai_assistant.testing.cancellation import ThreadSuspension

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime
    from pathlib import Path

#: ADR-0233 §15 leaves ``StepRunner._bound`` passing the fail-closed constant, and §6
#: refuses that value at construction — so every egress call in this tree is
#: unconstructable until the lane that follows computes it. This module's one case
#: drives a parked *egress* confirmation through ``resume``, which is the one engine
#: operation reaching ``ToolInvoker.invoke`` without a model in the loop, so the whole
#: module is affected and the marker is stated once here rather than on the case.
#: **Strict**, so it is an obligation rather than a licence: #2051's first act is
#: deleting it, a case that still fails then is a real defect, and one that passes
#: while still marked fails the suite. Not one assertion below is changed by it.
_REFUSED_UNTIL_THE_COMPOSER_LANDS: Final = (
    "ADR-0233 §15: the seam refuses every send until the composer lane (#2051) computes coverage"
)

pytestmark = pytest.mark.xfail(strict=True, reason=_REFUSED_UNTIL_THE_COMPOSER_LANDS)

#: Long enough that a released worker finishes inside it on any machine this runs
#: on, and short enough that a genuine hang fails rather than stalls the suite.
_WAITING: Final = 5.0

#: Long enough for the drain to have completed if it were going to. The assertion
#: it supports is a negative one — shutdown has *not* finished — so it is a floor
#: on the evidence rather than a bound on the implementation.
_SETTLE: Final = 0.2

#: A budget no case here waits on: the wait under test is the drain's.
_PATIENT: Final = timedelta(seconds=30)

#: The one step the parking fixture's plan carries.
STEP_ID: Final = "step-1"


def _park_the_worker(trail: SqliteAuditTrail) -> ThreadSuspension:
    """Block the ``sqlite3`` worker inside the spend read, not the coroutine above it.

    Where ADR-0029 §4's third bullet lives: ``_run_to_completion`` waits on that
    thread and absorbs a cancellation until it physically finishes, because
    releasing the connection while the worker still holds it would let a second
    caller use it concurrently (ADR-0054). Parking the worker is what makes the case
    deterministic — otherwise whether the thread is still inside the connection when
    shutdown arrives is a race between a disk read and an event-loop tick.
    """
    parked = ThreadSuspension()
    original = trail._spend_rows_sync

    def blocking(low: datetime, high: datetime) -> Sequence[object]:
        parked.hold()
        return original(low, high)

    trail._spend_rows_sync = blocking  # type: ignore[method-assign, assignment]
    return parked


async def test_shutdown_drains_a_wedged_invocation_before_it_closes_the_holder(
    tmp_path: Path,
) -> None:
    """ADR-0042 §2's ordering, over an invocation parked inside its admission.

    "A tracked task orphaned by a cancelled call is still using a connection
    ``close()`` would shut, so **nothing is closed until every tracked task has
    completed**." Here the tracked task is a ``resume`` whose step has reached
    ``ToolInvoker.invoke``, whose admission has reached the real holder, and whose
    read is parked inside the ``sqlite3`` worker — which is the state ADR-0194 §11
    names and the one a split fixture cannot produce.

    Both directions are asserted, because only the pair is evidence: shutdown does
    **not** finish while the worker is parked, and it does once the worker is
    released — so the wait is the drain rather than a coincidence of timing.

    What happens to the connection at shutdown is therefore: nothing, until the
    outstanding admission has finished; then the ordered close, with no worker left
    holding it. That answer is the **façade's** and not the store's —
    ``SqliteAuditTrail.close`` takes no lock of its own, which is exactly why the
    ordering has to live one layer up.
    """
    trail = SqliteAuditTrail(
        path=tmp_path / "audit.db",
        spend=SpendConfiguration(currency="USD", day_ceiling=Decimal("100")),
    )

    entered_close: list[str] = []

    async def _close() -> None:
        # Recorded rather than inferred from ``aclose()`` still being pending: a
        # shutdown that closed the connection *first* and only then drained would
        # leave the task pending too, so "not done" is not evidence of the ordering
        # on its own. This is.
        entered_close.append("close")
        trail.close()

    engine = _wire(parks=True, trail=trail, real_invoker=True, closers=(_close,))
    await engine.start()
    parked: ThreadSuspension | None = None
    try:
        outcome = await engine.converse("send the note", timeout=_PATIENT)
        assert outcome.step is not None
        assert outcome.step.disposition is Disposition.AWAITING_CONFIRMATION
        pending = await engine.pending_confirmations()
        assert len(pending) == 1

        parked = _park_the_worker(trail)
        resuming = asyncio.ensure_future(
            engine.resume(pending[0].token, approved=True, timeout=_PATIENT)
        )
        await parked.reached()

        closing = asyncio.ensure_future(engine.aclose())
        try:
            await asyncio.sleep(_SETTLE)
            assert not closing.done(), (
                "nothing is closed until every tracked task has completed "
                "(ADR-0042 §2); a shutdown returning here would have shut a "
                "connection an in-flight admission was still reading"
            )
            assert not resuming.done()
            assert entered_close == [], (
                "the closer was entered while an admission was still reading the "
                "connection it closes — the ordering ADR-0042 §2 fixes, inverted"
            )
        finally:
            # Released whatever the assertions above did, so a failure is a failed
            # test rather than a parked worker occupying the default executor until
            # `ThreadSuspension`'s own emergency timeout (#376).
            parked.release()

        await asyncio.wait_for(closing, _WAITING)
        resumed = await asyncio.wait_for(resuming, _WAITING)
        assert entered_close == ["close"], "and it was entered once the drain finished"
    finally:
        if parked is not None:
            parked.release()
        await engine.aclose()

    # **The invocation finished its work**, which is the other half of the same
    # ordering read from the call's side: had the connection closed underneath it,
    # the admission would have come back `SpendUndeterminedError` and the executor
    # would have committed the step `FAILED` — a value this case would still have
    # awaited without noticing.
    assert resumed.step is not None
    executed = resumed.step.state.step(STEP_ID)
    assert executed is not None
    assert executed.status is StepStatus.SUCCEEDED, executed.failure

    # And the close the drain preceded really happened: waiting is worth nothing if
    # nothing is closed afterwards.
    with pytest.raises(sqlite3.ProgrammingError):
        trail._conn.execute("SELECT 1")
