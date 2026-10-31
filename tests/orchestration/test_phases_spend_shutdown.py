"""Shutdown reaching the spend holder while acting's invocation's admission is wedged.

``test_engine_spend_shutdown`` held ADR-0194 §11's shutdown clause — "a real gate whose
store read is wedged, reached through ``ToolInvoker.invoke`` … and the same holder taken
through shutdown while that read is outstanding" — over a parked confirmation resumed,
which retired at the cutover with ``resume`` (ADR-0309 §5:1). The clause survives it:
on the phases the call is invoked by acting, and acting runs inside the activation the
façade drains. So here the invocation is acting's, in an activation the chat's reader
runs on a message: planning proposes the call, authorizing allows it, and acting reaches
``invoke`` on the real ``InMemoryToolRegistry``, admitting through the real
``SqliteAuditTrail`` the trail the ruling was recorded in and the resource the façade
closes — one object, all the way down (ADR-0194 §5).

**Both directions are asserted**, as there: shutdown does not close the holder while the
worker is parked inside the spend read, and closes it once the worker is released.

Refs: ADR-0194 §3, §5, §11; ADR-0042 §2; ADR-0054; ADR-0306 §5.
"""

from __future__ import annotations

import asyncio
import sqlite3
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Final

import pytest
from test_engine_contract import CAPABILITY, PARAMETERS, _wire

from ai_assistant.core.types import (
    ActionRequest,
    ChatDevice,
    DeviceAccess,
    PermissionDecision,
    PermissionOutcome,
    PermissionRuling,
    ProposedCall,
    RoundResponse,
    ToolOutcome,
    UserMessage,
)
from ai_assistant.permissions.audit import SqliteAuditTrail
from ai_assistant.permissions.spend import SpendConfiguration
from ai_assistant.testing import FakeToolCallingCompleter
from ai_assistant.testing.cancellation import ThreadSuspension

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime
    from pathlib import Path

    from ai_assistant.core.types import OfferedTool, PlanningExchange, ToolInvocation

#: Long enough that a released worker finishes inside it on any machine this runs on.
_WAITING: Final = 5.0

#: Long enough for the drain to have completed if it were going to; a floor on the
#: evidence for a negative assertion, not a bound on the implementation.
_SETTLE: Final = 0.2

_PHONE: Final = ChatDevice(device_id="phone", access=DeviceAccess.READ_WRITE)


def _park_the_worker(trail: SqliteAuditTrail) -> ThreadSuspension:
    """Block the ``sqlite3`` worker inside the spend read, not the coroutine above it."""
    parked = ThreadSuspension()
    original = trail._spend_rows_sync

    def blocking(low: datetime, high: datetime) -> Sequence[object]:
        parked.hold()
        return original(low, high)

    trail._spend_rows_sync = blocking  # type: ignore[method-assign, assignment]
    return parked


class _Allows:
    """A policy allowing every call, so the call reaches acting's ``invoke``.

    The parked step the old case resumed was allowed by the user's answer; nothing
    parks on the phases (ADR-0306 §4:8), so the ruling that lets the call run is the
    policy's own.
    """

    async def decide(self, request: ActionRequest) -> PermissionRuling:
        del request
        return PermissionRuling(outcome=PermissionOutcome.ALLOW, reason="test: allowed")

    async def resolve(self, confirmed: PermissionDecision, *, approved: bool) -> PermissionRuling:
        del confirmed, approved
        return PermissionRuling(outcome=PermissionOutcome.ALLOW, reason="test: allowed")


def _proposes_the_call_once() -> FakeToolCallingCompleter:
    """Planning proposing the one call, then writing and proposing nothing."""
    proposed = [False]

    def respond(_exchange: PlanningExchange, _tools: Sequence[OfferedTool]) -> RoundResponse:
        if proposed[0]:
            return RoundResponse(text="Sent.")
        proposed[0] = True
        return RoundResponse(
            calls=(ProposedCall(call_id="call-1", name=CAPABILITY, arguments=PARAMETERS),)
        )

    return FakeToolCallingCompleter(response=respond)


async def test_shutdown_drains_acting_s_wedged_invocation_before_it_closes_the_holder(
    tmp_path: Path,
) -> None:
    """ADR-0042 §2's ordering, over acting's invocation parked inside its admission."""
    trail = SqliteAuditTrail(
        path=tmp_path / "audit.db",
        spend=SpendConfiguration(currency="USD", day_ceiling=Decimal("100")),
    )
    # One ordered record of the two things the clause orders: the invocation's completion
    # appended to the trail it admitted through, and the closer entered. An invocation
    # whose connection closed under it would come back failed or never complete, which a
    # drain absorbing the failure would otherwise hide.
    events: list[str] = []
    completed: list[ToolOutcome] = []
    complete = trail.complete_invocation

    async def _completing(**kwargs: Any) -> ToolInvocation:
        completion = await complete(**kwargs)
        events.append("completed")
        completed.append(kwargs["outcome"])
        return completion

    trail.complete_invocation = _completing  # type: ignore[method-assign]

    async def _close() -> None:
        events.append("close")
        trail.close()

    engine = _wire(
        parks=True,
        trail=trail,
        real_invoker=True,
        closers=(_close,),
        phases={
            "completer": _proposes_the_call_once(),
            "policy": _Allows(),
            "capabilities": (CAPABILITY,),
        },
    )
    await engine.start()
    parked = _park_the_worker(trail)
    try:
        await engine.set_my_devices([_PHONE])
        conversation = (await engine.start_conversation()).id
        await engine.write_message(
            conversation,
            message=UserMessage(device_id=_PHONE.device_id, message_id="m-1", text="send it"),
        )
        await parked.reached()

        closing = asyncio.ensure_future(engine.aclose())
        try:
            await asyncio.sleep(_SETTLE)
            assert not closing.done(), (
                "nothing is closed until every tracked task has completed (ADR-0042 §2); "
                "a shutdown returning here would have shut a connection an in-flight "
                "admission was still reading"
            )
            assert events == [], (
                "the closer was entered while an admission was still reading the "
                "connection it closes — the ordering ADR-0042 §2 fixes, inverted"
            )
        finally:
            parked.release()
        await asyncio.wait_for(closing, _WAITING)
        assert events == ["completed", "close"], (
            "the invocation completed on the connection before the closer was entered"
        )
    finally:
        parked.release()
        await engine.aclose()

    # The invocation did its work: had the connection closed under it, its completion
    # would read failed rather than succeeded.
    assert completed == [ToolOutcome.SUCCEEDED]
    # The close the drain preceded really happened.
    with pytest.raises(sqlite3.ProgrammingError):
        trail._conn.execute("SELECT 1")
