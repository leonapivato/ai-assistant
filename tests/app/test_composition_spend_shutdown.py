"""Shutdown reaching the spend holder while its read is still outstanding.

ADR-0194 §11 requires the lane to take "the same holder **through shutdown** while
that read is outstanding", and to state what happens to the connection there. In
this tree *shutdown* is not a bare ``close()``: ADR-0042 §2 makes it the façade's
ordered act — "**nothing is closed until every tracked task has completed**" — and
ADR-0083 §4 gives it its drain. A test calling ``SqliteAuditTrail.close`` mid-read
would be exercising the resource race that ordering exists to prevent, and
labelling it shutdown.

So the subject here is the **composition root's own engine**, built by
:func:`~ai_assistant.app.composition.build_engine` over a real data directory —
the real holder, the real closers, the real drain — rather than a hand-assembled
approximation of one.

**§11's clause itself is discharged elsewhere, and this is its root-level
counterpart.** That clause names a read "reached through ``ToolInvoker.invoke``",
and ``tests/orchestration/test_engine_spend_shutdown.py`` drives exactly that — a
resumed confirmation whose step reaches the real invoker and the real gate, parked
inside its admission, with shutdown started on top of it. What that case cannot
say is anything about the **composition root**, because it wires its own engine:
whether ``build_engine`` puts this holder among the façade's closers at all, and
whether the operation this change added to the tracked set is drained before it,
are facts about ``app/composition.py`` and are what this module pins. The two are
complementary; neither is the other's substitute.

Refs: ADR-0194 §11; ADR-0042 §2; ADR-0083 §4; ADR-0054.
"""

from __future__ import annotations

import asyncio
import sqlite3
from decimal import Decimal
from typing import TYPE_CHECKING, Final

import pytest

from ai_assistant.app.composition import build_engine
from ai_assistant.core.config import EmbedderKind, Settings
from ai_assistant.permissions.audit import SqliteAuditTrail
from ai_assistant.testing.cancellation import ThreadSuspension

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime
    from pathlib import Path

#: Long enough that a released worker finishes inside it on any machine this runs
#: on, and short enough that a genuine hang fails rather than stalls the suite.
_WAITING: Final = 5.0

#: Long enough for the drain to have completed if it were going to, and short
#: enough to keep the case cheap. The assertion it supports is a negative one —
#: shutdown has *not* finished — so it is a floor on the evidence, not a bound.
_SETTLE: Final = 0.2


def _park_the_worker(trail: SqliteAuditTrail) -> ThreadSuspension:
    """Block the ``sqlite3`` worker inside the spend read, not the coroutine above it.

    Where ADR-0029 §4's third bullet lives: ``_run_to_completion`` waits on that
    thread and absorbs a cancellation until it physically finishes, because
    releasing the connection while the worker still holds it would let a second
    caller use it concurrently (ADR-0054). Parking the worker is what makes this
    deterministic — otherwise whether the thread is still inside the connection
    when shutdown arrives is a race between a disk read and an event-loop tick.
    """
    parked = ThreadSuspension()
    original = trail._spend_rows_sync

    def blocking(low: datetime, high: datetime) -> Sequence[object]:
        parked.hold()
        return original(low, high)

    trail._spend_rows_sync = blocking  # type: ignore[method-assign, assignment]
    return parked


async def test_shutdown_waits_for_the_wedged_spend_read_before_it_closes_anything(
    tmp_path: Path,
) -> None:
    """ADR-0042 §2's ordering, at the root that actually wires the closer.

    "A tracked task orphaned by a cancelled call is still using a connection
    ``close()`` would shut, so **nothing is closed until every tracked task has
    completed**." This is that rule met by the one operation this change added to
    the tracked set, on a holder whose read is wedged inside its worker.

    Both directions are asserted, because only the pair is evidence: shutdown does
    **not** finish while the worker is parked, and it does finish once the worker is
    released — so the wait is the drain rather than a coincidence of timing.

    What happens to the connection at shutdown is therefore: nothing, until the
    outstanding read has finished; then the ordered close, with no worker left
    holding it. That is the answer §11 asks this lane to state, and it is the
    façade's rather than the store's — ``SqliteAuditTrail.close`` takes no lock of
    its own, which is exactly why the ordering has to live one layer up.
    """
    engine = build_engine(
        Settings(
            embedder=EmbedderKind.HASHING,
            world_spend_currency="USD",
            world_spend_day_ceiling=Decimal("100"),
        ),
        data_dir=tmp_path,
    )
    trail = engine._trail
    assert isinstance(trail, SqliteAuditTrail)
    parked = _park_the_worker(trail)

    reading = asyncio.ensure_future(engine.spend_totals())
    await parked.reached()

    closing = asyncio.ensure_future(engine.aclose())
    try:
        await asyncio.sleep(_SETTLE)
        assert not closing.done(), (
            "nothing is closed until every tracked task has completed (ADR-0042 §2); "
            "a shutdown that returned here would have shut a connection still in use"
        )
        assert not reading.done()
    finally:
        # Released whatever the assertions did, so a failure is a failed test rather
        # than a parked worker occupying the default executor until
        # `ThreadSuspension`'s own emergency timeout (#376).
        parked.release()

    await asyncio.wait_for(closing, _WAITING)
    totals = await asyncio.wait_for(reading, _WAITING)

    # **The read produced its value**, which is what proves the ordering from the
    # call's side rather than only from the task's: had the closer run first, the
    # parked worker would have met a closed database and this would have raised
    # `SpendUndeterminedError` instead of answering. "Shutdown was still pending"
    # is not evidence on its own — a shutdown that closed first and drained second
    # would be pending too.
    assert len(totals) == 2, "the drained read produced its value rather than being torn off"
    # And the connection really is closed behind it, which is the other half of the
    # ordering: the drain is worth nothing if the close it precedes never happened.
    with pytest.raises(sqlite3.ProgrammingError):
        trail._conn.execute("SELECT 1")


async def test_a_second_shutdown_after_that_one_is_a_no_op(tmp_path: Path) -> None:
    """Idempotent, which is what a drain reaching an already-closed façade needs.

    Stated here rather than assumed because the case above leaves the holder in
    exactly the state a second shutdown would meet — closed connection, drained
    tracked set — and a closer that raised on it would turn an ordinary double
    shutdown into an error at the one moment nothing can be done about it.
    """
    engine = build_engine(
        Settings(
            embedder=EmbedderKind.HASHING,
            world_spend_currency="USD",
            world_spend_day_ceiling=Decimal("100"),
        ),
        data_dir=tmp_path,
    )

    await engine.aclose()
    await engine.aclose()
