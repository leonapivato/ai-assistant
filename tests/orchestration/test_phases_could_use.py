"""What each work is offered and shown, end to end through the engine (ADR-0368 §8).

The phases narrow what a work is offered, at its first round, and what its Connections
section shows, to what its authority could use, over the same line store the authorizer's
check reads. For the owner at normal with no made line nothing changes: every round's
request, the exchange and the tools, is byte for byte what it is with no line store wired,
which is the path as it stood before the filter (a work's hub chat message, and the work of
the task it sets). An unidentified sender's work, at none, is offered only the reply into
its own place and shown only that place, and nothing says why; a call it makes to a
capability it was not offered is still checked, and refused as the check refuses it (§8:5).
An event's place is recorded as the owner's before the hub reads it (ADR-0381 §4:2).
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import TYPE_CHECKING, Final

from channel_receiver_contract import event_input
from exchange_support import section
from phases_support import open_conversation, phases_harness, said, until, written
from structlog.testing import capture_logs
from task_support import seams
from test_engine_phases import _BOOK
from test_phases_check import _linked, _texting_its_place
from test_phases_task_scheduler import _responder, _spawning, _until_scheduled
from test_phases_work_facts import _one_frozen

from ai_assistant.core.types import (
    OWNER_PERSON_ID,
    CallCheck,
    CallCheckKind,
    CallOutcomeKind,
    CheckedFor,
    CheckOutcome,
    CheckOutcomeKind,
    CheckRun,
    DefaultGrant,
    GrantHow,
    MessageAuthor,
    ProposedCall,
    RoundResponse,
    Sureness,
    ThingKey,
    ThingKind,
    ThingRecord,
    ThingRecording,
    ToolDefinition,
)
from ai_assistant.testing import (
    FakeIdentityStore,
    FakePermissionLineStore,
    FakeThingRecordStore,
    FakeToolCallingCompleter,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.core.types import OfferedTool, PlanningExchange
    from ai_assistant.testing.tool_calling import RoundCall

_EVENT_PLACE: Final = ThingKey(
    kind=ThingKind.CONNECTION, identifier="informational_event:thermostat-1"
)


#: The harness's booking tool, declaring its default grant as every tool does (ADR-0367
#: §4:3): one that declared none would be refused by the check, and so not offered.
_DECLARED_BOOK: Final = ToolDefinition.model_validate(
    {
        **_BOOK.model_dump(),
        "default_grant": DefaultGrant(how=GrantHow.ALLOWED, bar=Sureness.NORMAL),
    }
)


async def _owners_rounds(*, filtered: bool) -> list[RoundCall]:
    """The owner's message at normal, which sets a task, and the task's work: every round."""
    completer = _responder(_spawning(connections="first place"), _texting_its_place)
    harness = phases_harness(
        completer,
        tools=(_DECLARED_BOOK,),
        task_scheduler=seams(),
        identities=_linked(),
        phases={
            "lines": FakePermissionLineStore() if filtered else None,
            "things": FakeThingRecordStore() if filtered else None,
            "look_ups": True,
        },
    )
    await harness.engine.start()
    try:
        conversation = await open_conversation(harness)
        await harness.engine.write_message(conversation, message=said("m-1", "say hello soon"))
        await _until_scheduled(harness, 1)

        async def spoken() -> bool:
            return any(
                one.author is MessageAuthor.ASSISTANT and one.text == "hello"
                for one in await written(harness, conversation)
            )

        await until(spoken, what="the task's message")
    finally:
        await harness.engine.aclose()
    return completer.calls


async def test_the_owner_at_normal_with_no_made_line_is_offered_and_shown_as_before() -> None:
    """Nothing changes for the owner at normal: each round's request is byte-equal."""
    before = await _owners_rounds(filtered=False)
    after = await _owners_rounds(filtered=True)

    assert len(after) == len(before) >= 2
    for one, other in zip(before, after, strict=True):
        assert other.tools == one.tools
        assert other.exchange.model_dump_json() == one.exchange.model_dump_json()


def _calling_unoffered(exchange: PlanningExchange, _tools: Sequence[OfferedTool]) -> RoundResponse:
    """A first round calling a capability it was not offered, then nothing."""
    if exchange.steps:
        return RoundResponse()
    return RoundResponse(
        calls=(
            ProposedCall(
                call_id="r1",
                name="remember_fact",
                arguments={
                    "fact": "The owner waters the plants on Sundays.",
                    "why": "worth keeping",
                    "rests_on_this_stimulus": True,
                },
            ),
        )
    )


async def test_an_unidentified_senders_work_is_offered_its_reply_alone_and_still_checked() -> None:
    """ADR-0368 §7:2, §8:1, §8:2, §8:4, §8:5: at none no default grant applies to anyone
    and no one is asked, so only the reply into its own place is offered, and only that
    place is shown; nothing says why, and a call it makes to what it was not offered is
    checked and refused as before."""
    completer = FakeToolCallingCompleter(response=_calling_unoffered)
    harness = phases_harness(
        completer,
        # The phone is linked to no one, so its message's sender is unidentified.
        identities=FakeIdentityStore(),
        phases={"lines": FakePermissionLineStore(), "things": FakeThingRecordStore()},
    )
    await open_conversation(harness)
    other = (await harness.engine.start_conversation()).id
    conversation = (await harness.engine.start_conversation()).id
    await harness.engine.write_message(conversation, message=said("m-1", "remember this"))

    episode = await _one_frozen(harness)

    first = completer.calls[0]
    assert [one.name for one in first.tools] == ["send_text"]
    shown = section(first.exchange.briefing, "## Connections")
    # Its own place alone, of the three conversations the hub's chat holds.
    assert shown.count("<connection") == 1
    assert "a conversation in the system's own chat" in shown
    del other
    assert episode.processing_record is not None
    (entry,) = [one for one in episode.processing_record.call_records if one.call_id == "r1"]
    assert entry.outcome is CallOutcomeKind.REFUSED
    assert entry.check == CallCheck(
        kind=CallCheckKind.CHECKED,
        runs=(
            CheckRun(
                checked_for=CheckedFor.anyone(),
                outcome=CheckOutcome(kind=CheckOutcomeKind.NEEDS_YES_SHORTFALL, bar=Sureness.WEAK),
            ),
        ),
    )


class _Ordered:
    """The canonical fake, each write noted in ``order`` beside the rounds noted there."""

    def __init__(self, order: list[str]) -> None:
        self.held = FakeThingRecordStore()
        self.order = order

    async def whose(self, key: ThingKey) -> ThingRecord | None:
        return await self.held.whose(key)

    async def record_whose(self, key: ThingKey, *, person: str) -> ThingRecording:
        self.order.append(f"recorded {key.identifier}")
        return await self.held.record_whose(key, person=person)

    async def export(self) -> tuple[ThingRecord, ...]:
        return await self.held.export()


async def test_an_events_place_is_recorded_as_the_owners_before_it_is_read() -> None:
    """ADR-0381 §4:2: written where none stands, before planning is shown the event."""
    order: list[str] = []

    def planned(exchange: PlanningExchange, _tools: Sequence[OfferedTool]) -> RoundResponse:
        if not exchange.steps:
            order.append("planned")
        return RoundResponse()

    things = _Ordered(order)
    harness = phases_harness(FakeToolCallingCompleter(response=planned), things=things)

    await harness.engine.receive(event_input(), reply=None, timeout=timedelta(seconds=10))
    await harness.engine.receive(event_input(), reply=None, timeout=timedelta(seconds=10))

    record = await things.whose(_EVENT_PLACE)
    assert record is not None
    assert str(record.person) == OWNER_PERSON_ID
    # Once per place while the hub runs, and before the first round.
    assert order == [f"recorded {_EVENT_PLACE.identifier}", "planned", "planned"]


async def test_a_record_that_cannot_be_written_leaves_the_place_no_ones_and_the_event_runs() -> (
    None
):
    """ADR-0381 §5:1: a failed write leaves no record, which lets nothing through."""
    things = FakeThingRecordStore()
    things.fail_next()
    harness = phases_harness(things=things)

    with capture_logs() as logs:
        await harness.engine.receive(event_input(), reply=None, timeout=timedelta(seconds=10))

    assert {"event": "thing_record_unwritten", "stage": "receive", "reason": "store"} in [
        {key: one[key] for key in ("event", "stage", "reason") if key in one} for one in logs
    ]


async def test_lines_that_cannot_be_read_offer_the_owner_only_the_reply() -> None:
    """The check would not run, so only what it would not reach is usable; logged by code."""
    lines = FakePermissionLineStore()
    lines.fail_next()
    completer = FakeToolCallingCompleter()
    harness = phases_harness(completer, identities=_linked(), phases={"lines": lines})
    conversation = await open_conversation(harness)

    with capture_logs() as logs:
        await harness.engine.write_message(conversation, message=said("m-1", "hello"))
        await _one_frozen(harness)

    assert [one.name for one in completer.calls[0].tools] == ["send_text"]
    assert {"event": "could_use_unread", "stage": "planning", "reason": "lines_unread"} in [
        {key: one[key] for key in ("event", "stage", "reason") if key in one} for one in logs
    ]


class _Stuck:
    """A store whose write never returns."""

    def __init__(self) -> None:
        self.held = FakeThingRecordStore()

    async def whose(self, key: ThingKey) -> ThingRecord | None:
        return await self.held.whose(key)

    async def record_whose(self, key: ThingKey, *, person: str) -> ThingRecording:
        del key, person
        await asyncio.Event().wait()
        raise AssertionError  # pragma: no cover - the wait above never returns

    async def export(self) -> tuple[ThingRecord, ...]:
        return await self.held.export()


async def test_a_write_that_never_returns_is_cut_short_by_the_events_own_deadline() -> None:
    """The write runs within the event's budget, so ``receive`` returns how the event
    ended, the place left with no record (ADR-0381 §5:1)."""
    things = _Stuck()
    harness = phases_harness(things=things)

    with capture_logs() as logs:
        result = await asyncio.wait_for(
            harness.engine.receive(event_input(), reply=None, timeout=timedelta(milliseconds=50)),
            timeout=5,
        )

    assert result.channel == event_input().target
    assert await things.whose(_EVENT_PLACE) is None
    assert {"event": "thing_record_unwritten", "stage": "receive", "reason": "deadline"} in [
        {key: one[key] for key in ("event", "stage", "reason") if key in one} for one in logs
    ]
