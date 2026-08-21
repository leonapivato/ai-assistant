"""One poll, many streams, and the acknowledgement that never leaves (ADR-0175 §4, §5).

Driven against the fan-out directly rather than through a socket, because what these
pin is *when the gateway calls* and *to how many readers it renders one answer* — the
two facts golden rule 3 turns on here, and neither is visible from a response body.
The end-to-end half lives in ``test_gateway_streams.py``.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import pytest

from ai_assistant.core.errors import NotificationBudgetError, NotificationOutboxError
from ai_assistant.core.types import DataTier, NotificationCandidate, NotificationDelivery
from ai_assistant.interfaces.gateway.delivery import DeliveryFanOut, DeliveryStream
from ai_assistant.testing import FakeAssistantEngine
from ai_assistant.wire.errors import HubUnavailableError

if TYPE_CHECKING:
    from collections.abc import Mapping

    from ai_assistant.core.types import Identifier

_AT = datetime(2026, 1, 2, 15, 0, tzinfo=UTC)
_BUDGET = timedelta(seconds=20)


def _delivery(number: int) -> NotificationDelivery:
    """One delivery, numbered so a test can tell two apart."""
    return NotificationDelivery(
        delivery_id=f"{number}." + f"{number:02x}" * 16,
        notification=NotificationCandidate(
            candidate_key=f"key-{number}",
            producer="calendar-reader",
            notification_class="calendar-upcoming",
            summary=f"notification {number}",
            noticed_at=_AT,
            confidence=0.8,
            sensitivity=DataTier.PERSONAL,
        ),
    )


class _Scripted(FakeAssistantEngine):
    """An engine whose polls are released one at a time by the test.

    The canonical fake's own ``next_notification`` deliberately does not sleep, so a
    fan-out driven against it would spin: what a test of ADR-0175 §4 needs held is
    the *cadence*, which means deciding when each poll answers.
    """

    def __init__(self, answers: list[NotificationDelivery | None | Exception]) -> None:
        """Script one answer per poll, in order."""
        super().__init__()
        self.answers = answers
        self.acknowledged: list[Identifier | None] = []
        self.released = asyncio.Event()
        self.polling = asyncio.Event()

    async def next_notification(
        self, *, acknowledging: Identifier | None = None, budget: timedelta
    ) -> NotificationDelivery | None:
        """Answer the next scripted poll once the test releases it."""
        self.acknowledged.append(acknowledging)
        self.calls.append(("next_notification", {"acknowledging": acknowledging, "budget": budget}))
        self.polling.set()
        try:
            await self.released.wait()
        finally:
            # Cleared on a cancelled poll too, so ``polling`` means "a poll is
            # outstanding *now*" rather than "one was, once". A test that waited on a
            # stale flag would see the poll before it, which is exactly the ordering
            # ADR-0175 §5's acknowledgement clauses turn on.
            self.released.clear()
            self.polling.clear()
        answer = self.answers.pop(0) if self.answers else None
        if isinstance(answer, Exception):
            raise answer
        return answer

    async def answer_one_poll(self) -> None:
        """Let the outstanding poll return, and let the loop reach the next."""
        await self.polling.wait()
        self.released.set()
        await asyncio.sleep(0)
        await asyncio.sleep(0)


class _Slots:
    """``gateway_max_hub_connections``, as the fan-out sees it (ADR-0175 §7)."""

    def __init__(self, ceiling: int = 8) -> None:
        """Start with every slot free."""
        self.ceiling = ceiling
        self.held = 0
        self.taken = 0

    def acquire(self) -> bool:
        """Take one, or report the ceiling."""
        if self.held >= self.ceiling:
            return False
        self.held += 1
        self.taken += 1
        return True

    def release(self) -> None:
        """Give one back."""
        self.held -= 1


def _fan_out(
    answers: list[NotificationDelivery | None | Exception], *, slots: _Slots | None = None
) -> tuple[DeliveryFanOut, _Scripted, _Slots]:
    """A fan-out over a scripted engine, with its hub-slot accounting visible."""
    engine = _Scripted(answers)
    held = slots or _Slots()
    return (
        DeliveryFanOut(engine=engine, budget=_BUDGET, acquire=held.acquire, release=held.release),
        engine,
        held,
    )


async def _drain(stream: DeliveryStream, into: list[Mapping[str, Any]]) -> None:
    """Read one stream to its end, as a connection handler would."""
    async for value in stream.values():
        into.append(value)


# --- ADR-0175 §4: the stream itself ------------------------------------------


async def test_a_stream_holds_at_most_one_value_and_queues_nothing_behind_it() -> None:
    """§4: "The gateway holds at most one value pending per stream and queues nothing
    behind one." A queue would be the buffer §4 refuses, in miniature."""
    stream = DeliveryStream()

    assert stream.offer({"kind": "alive"}) is True
    assert stream.offer({"kind": "alive"}) is False


async def test_a_stream_takes_the_next_value_once_the_previous_write_completed() -> None:
    """The pending slot is cleared by the *consumer*, after its body has run — which
    is what makes the refusal above mean "the previous write has not completed"
    rather than "a value is queued"."""
    stream = DeliveryStream()
    read: list[Mapping[str, Any]] = []
    reading = asyncio.ensure_future(_drain(stream, read))

    stream.offer({"kind": "alive"})
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert stream.offer({"kind": "notification"}) is True
    stream.end()
    await reading
    assert [value["kind"] for value in read] == ["alive", "notification"]


async def test_a_stream_that_ended_takes_nothing_further() -> None:
    """An ended stream is not a slow one, and offering to it is not a stall."""
    stream = DeliveryStream()
    stream.end()

    assert stream.offer({"kind": "alive"}) is False


async def test_an_abandoned_stream_says_so_to_whoever_is_writing_on_it() -> None:
    """§4: a stalled write is "abandoned and the stream is ended", and the writer has
    to be able to act on that — a bare ``drain`` on a browser that stopped reading
    never returns, so without the signal the abandonment would be a decision the
    gateway made and could not carry out."""
    stream = DeliveryStream()

    stream.abandon()

    assert stream.abandoned.is_set()
    assert stream.offer({"kind": "alive"}) is False


# --- §4: one delivery, every open stream -------------------------------------


async def test_one_delivery_is_written_to_every_open_stream() -> None:
    """§4: "A delivery a poll returned is written to **every** delivery stream open
    at the moment it returned, unchanged".

    The alternatives are both refused there: choosing one stream and starving the
    rest is a second tab showing nothing with nothing saying why, and evicting an
    incumbent is the silent lever ADR-0131 §2 and ADR-0168 §4 have each refused.
    """
    fan_out, engine, _ = _fan_out([_delivery(1)])
    first, second = fan_out.open(), fan_out.open()
    assert first is not None
    assert second is not None
    read_first: list[Mapping[str, Any]] = []
    read_second: list[Mapping[str, Any]] = []
    reading = [
        asyncio.ensure_future(_drain(first, read_first)),
        asyncio.ensure_future(_drain(second, read_second)),
    ]

    await engine.answer_one_poll()

    assert read_first[0]["summary"] == "notification 1"
    assert read_second[0]["summary"] == "notification 1"
    fan_out.shutdown()
    for one in reading:
        await one


async def test_an_empty_poll_writes_the_keep_alive_to_every_open_stream() -> None:
    """§4: the gateway writes "at least once per ``gateway_notification_budget``: a
    delivery where the poll returned one, and otherwise a value carrying nothing but
    its own kind".

    Not decoration: a stream that writes nothing for an hour is one nothing can
    distinguish from a stream that has died, at either end, and ADR-0168 §9 requires
    a browser reaching a running gateway to learn that the hub is down rather than
    that nothing is there.
    """
    fan_out, engine, _ = _fan_out([None])
    stream = fan_out.open()
    assert stream is not None
    read: list[Mapping[str, Any]] = []
    reading = asyncio.ensure_future(_drain(stream, read))

    await engine.answer_one_poll()

    assert read == [{"kind": "alive"}]
    fan_out.shutdown()
    await reading


async def test_the_poll_asks_for_the_configured_budget() -> None:
    """§8: the figure "is the value the gateway supplies as ``next_notification``'s
    ``budget`` argument", and it is the same figure that paces the write above —
    "one figure paces both, because the write a browser observes is the completion of
    the poll the budget bounds"."""
    fan_out, engine, _ = _fan_out([None])
    stream = fan_out.open()
    assert stream is not None
    await engine.polling.wait()

    assert engine.calls[0][1]["budget"] == _BUDGET

    fan_out.close(stream)


async def test_a_stream_that_stopped_reading_is_abandoned_and_the_rest_are_not() -> None:
    """§4: "a write that has not completed when the next value is due on that stream
    is abandoned and the stream is ended, so a browser that stops reading cannot delay
    another browser's delivery".

    The reader that never starts is the stalled browser; the one that drains keeps
    receiving. That is ADR-0094 §9's bound taken at the only place fan-out creates
    one, and it costs the abandoned browser a reconnect, which is free because a
    session outlives its connections (ADR-0168 §8).
    """
    fan_out, engine, _ = _fan_out([_delivery(1), _delivery(2)])
    stalled, reading_one = fan_out.open(), fan_out.open()
    assert stalled is not None
    assert reading_one is not None
    read: list[Mapping[str, Any]] = []
    reading = asyncio.ensure_future(_drain(reading_one, read))

    await engine.answer_one_poll()
    await engine.answer_one_poll()

    assert stalled.abandoned.is_set()
    assert [value["summary"] for value in read] == ["notification 1", "notification 2"]
    fan_out.shutdown()
    await reading


# --- §5: the acknowledgement -------------------------------------------------


async def test_a_delivery_written_to_a_stream_is_acknowledged_on_the_next_poll() -> None:
    """§5: "The gateway acknowledges, on its next poll, a delivery it wrote to at
    least one open delivery stream"."""
    fan_out, engine, _ = _fan_out([_delivery(1), None])
    stream = fan_out.open()
    assert stream is not None
    read: list[Mapping[str, Any]] = []
    reading = asyncio.ensure_future(_drain(stream, read))

    await engine.answer_one_poll()
    await engine.polling.wait()

    assert engine.acknowledged == [None, _delivery(1).delivery_id]
    fan_out.shutdown()
    await reading


async def test_a_delivery_no_stream_could_take_is_not_acknowledged() -> None:
    """§5 acknowledges "a delivery it wrote to at least one open delivery stream, and
    it acknowledges no other". A stream that could not take it was abandoned, so the
    delivery reached nobody — and an acknowledgement would retire an entry the hub
    should offer again."""
    fan_out, engine, _ = _fan_out([_delivery(1), None])
    stalled = fan_out.open()
    assert stalled is not None
    stalled.offer({"kind": "alive"})  # occupies the pending slot, so the next offer fails

    await engine.answer_one_poll()
    await engine.polling.wait()

    assert engine.acknowledged == [None, None]
    fan_out.shutdown()


async def test_no_delivery_id_is_carried_across_a_period_with_no_stream_open() -> None:
    """§5's write-then-disconnect arm: "it carries no ``delivery_id`` across a period
    in which no delivery stream was open. So the gateway holds nothing at all whenever
    no stream is open, and every acknowledgement it owes rides a poll §4 already
    obliges."

    Where the acknowledgement's own poll does not complete, the delivery is left
    unacknowledged, its lease expires and the hub offers the entry again — so what
    the owner may see is one notification **twice**, which is ADR-0131 §3's
    at-least-once behaving exactly as built. The alternative is declined rather than
    overlooked: ADR-0131 §4's idempotent no-op would make a blind acknowledgement on
    some later poll safe, but the token would then be held for a period bounded by
    nothing the gateway controls, because a browser may never come back.
    """
    fan_out, engine, slots = _fan_out([_delivery(1), None])
    stream = fan_out.open()
    assert stream is not None
    read: list[Mapping[str, Any]] = []
    reading = asyncio.ensure_future(_drain(stream, read))
    await engine.answer_one_poll()
    assert read[0]["summary"] == "notification 1"
    fan_out.close(stream)
    await asyncio.sleep(0)
    await reading
    assert slots.held == 0
    acknowledged_while_watched = list(engine.acknowledged)

    fresh = fan_out.open()
    assert fresh is not None
    await engine.polling.wait()

    assert engine.acknowledged == [*acknowledged_while_watched, None]
    fan_out.shutdown()


async def test_the_poll_ends_and_the_hub_slot_is_given_back_with_the_last_stream() -> None:
    """§5: "When the last delivery stream ends, the gateway closes its delivery
    connection", which under ADR-0131 §2a releases the device slot and the hub's
    delivery capacity in one step and cancels a poll that has not yet selected."""
    fan_out, engine, slots = _fan_out([None])
    first, second = fan_out.open(), fan_out.open()
    assert first is not None
    assert second is not None
    await engine.polling.wait()
    assert slots.held == 1

    fan_out.close(first)
    assert slots.held == 1

    fan_out.close(second)
    assert slots.held == 0


async def test_two_streams_share_one_poll_and_do_not_originate_a_second() -> None:
    """§12 examines this against ADR-0168 §1's biconditional: a second delivery stream
    "does not *originate* a further call, because ADR-0131 §2 gives the device one
    slot", and §1 "makes no cardinality claim". A reader taking "resolves to calls" as
    "originates a call" would build one poll per stream and be closed on the second."""
    fan_out, engine, slots = _fan_out([None, None])
    first, second = fan_out.open(), fan_out.open()
    assert first is not None
    assert second is not None
    await engine.polling.wait()

    assert slots.taken == 1
    assert len(engine.calls) == 1
    fan_out.shutdown()


async def test_no_poll_is_held_while_no_stream_is_open() -> None:
    """§4: the gateway holds the poll "while and only while at least one delivery
    stream is open", and holds none at any other time.

    A poll that returned to a gateway with nowhere to put the answer would have
    selected an entry, minted a ``delivery_id`` and started a lease in one indivisible
    step (ADR-0131 §2a) — withholding it for ``hub_notification_lease`` on behalf of a
    browser that was never there.
    """
    fan_out, engine, slots = _fan_out([None])

    assert engine.calls == []
    assert slots.taken == 0

    stream = fan_out.open()
    assert stream is not None
    await engine.polling.wait()
    fan_out.close(stream)
    await asyncio.sleep(0)

    assert len(engine.calls) == 1


async def test_no_delivery_is_retained_for_a_stream_that_opens_later() -> None:
    """§4: "A delivery stream opened after a delivery was written carries no replay
    of it… the hub's durable outbox (ADR-0131 §3) is the only place an undelivered
    notification is held."

    A gateway-side buffer would be that outbox rebuilt one hop out with none of its
    bounds, which ADR-0094 §9 permits edge state only where it is bounded in size and
    in age and destroyed continuously.
    """
    fan_out, engine, _ = _fan_out([_delivery(1), None])
    first = fan_out.open()
    assert first is not None
    read_first: list[Mapping[str, Any]] = []
    reading = asyncio.ensure_future(_drain(first, read_first))
    await engine.answer_one_poll()

    second = fan_out.open()
    assert second is not None
    read_second: list[Mapping[str, Any]] = []
    reading_second = asyncio.ensure_future(_drain(second, read_second))
    await asyncio.sleep(0)

    assert read_second == []
    fan_out.shutdown()
    await reading
    await reading_second


# --- §4: a poll the gateway cannot complete ----------------------------------


@pytest.mark.parametrize(
    ("raised", "named"),
    [
        pytest.param(HubUnavailableError("no hub there"), "hub-unreachable", id="transport"),
        pytest.param(
            NotificationOutboxError("the outbox would not commit"),
            "assistant-declined",
            id="received and declined",
        ),
        pytest.param(
            NotificationBudgetError("budget above hub_max_notification_budget"),
            "delivery-budget-declined",
            id="the budget the hub refused",
        ),
    ],
)
async def test_a_poll_that_cannot_complete_ends_every_stream_naming_the_condition(
    raised: Exception, named: str
) -> None:
    """§4: "A poll the gateway cannot complete ends every open delivery stream with a
    terminal value reporting it, distinguishing a transport failure from a request the
    hub received and declined (ADR-0168 §9)."

    The budget case is §8's own: no load-time check can relate
    ``gateway_notification_budget`` to ``hub_max_notification_budget`` — one is
    another process's setting and may be another machine's — so the refusal arrives
    here and is reported as a request the hub received and declined.
    """
    fan_out, engine, _ = _fan_out([raised])
    first, second = fan_out.open(), fan_out.open()
    assert first is not None
    assert second is not None
    read_first: list[Mapping[str, Any]] = []
    read_second: list[Mapping[str, Any]] = []
    reading = [
        asyncio.ensure_future(_drain(first, read_first)),
        asyncio.ensure_future(_drain(second, read_second)),
    ]

    await engine.answer_one_poll()
    for one in reading:
        await one

    assert read_first == [{"kind": "fault", "fault": named, "detail": str(raised)}]
    assert read_second == read_first


async def test_a_failed_poll_is_not_retried_and_a_fresh_stream_polls_again() -> None:
    """§4: "The gateway polls again only when a browser establishes a delivery stream
    afresh, and retries no poll of its own motion."

    The slot accounting is the other half: a spent poll holds nothing, so the fresh
    one takes its own rather than the gateway holding two.
    """
    fan_out, engine, slots = _fan_out([HubUnavailableError("no hub there"), None])
    first = fan_out.open()
    assert first is not None
    read: list[Mapping[str, Any]] = []
    reading = asyncio.ensure_future(_drain(first, read))
    await engine.answer_one_poll()
    await reading
    fan_out.close(first)
    calls_after_failure = len(engine.calls)

    second = fan_out.open()
    assert second is not None
    await engine.polling.wait()

    assert calls_after_failure == 1
    assert len(engine.calls) == 2
    assert slots.held == 1
    fan_out.shutdown()


# --- §7: the delivery connection counts against the hub ceiling --------------


async def test_the_ceiling_refuses_a_delivery_stream_rather_than_opening_a_connection() -> None:
    """§7: "The gateway's delivery connection counts against
    ``gateway_max_hub_connections`` exactly as any hub connection does, and a request
    that would need one beyond that ceiling is refused naming the limit."

    "No lane gives delivery its own connection budget at the gateway, which is
    ADR-0131 §5's rule applied at this door."
    """
    slots = _Slots(ceiling=1)
    slots.acquire()  # a turn already holds the only one
    fan_out, engine, _ = _fan_out([None], slots=slots)

    assert fan_out.open() is None
    assert engine.calls == []


async def test_a_poll_that_fails_in_no_named_way_still_ends_every_stream() -> None:
    """§4's terminal-value guarantee names no exception class: "A poll the gateway
    cannot complete ends every open delivery stream with a terminal value reporting
    it."

    A browser holding a response body cannot tell a gateway that stopped polling from
    one with nothing to say — which is the very condition §4 spends a keep-alive to
    make observable — so a poll that fails outside the three conditions above still
    owes an ending. The fault is its own name rather than either of ADR-0168 §9's
    two, because §9's distinction between a transport failure and a request the hub
    received and declined is only worth anything if a third condition is not quietly
    reported as one of them.

    The slot comes back with it: ending every stream is what lets each handler close
    its own, and the last close reaps the poll.
    """
    fan_out, engine, slots = _fan_out([RuntimeError("the engine is shutting down")])
    stream = fan_out.open()
    assert stream is not None
    read: list[Mapping[str, Any]] = []
    reading = asyncio.ensure_future(_drain(stream, read))

    await engine.answer_one_poll()
    await reading

    assert read == [
        {"kind": "fault", "fault": "delivery-failed", "detail": "the engine is shutting down"}
    ]
    fan_out.close(stream)
    assert slots.held == 0


async def test_a_stalled_stream_is_abandoned_rather_than_queued_behind_a_terminal_value() -> None:
    """Where §4's clauses meet: a stalled stream and a poll that cannot go on.

    "A poll the gateway cannot complete ends every open delivery stream with a
    terminal value reporting it" is the clause the case looks like it fails. Two
    others decide it: the gateway "holds at most one value pending per stream and
    queues nothing behind one", and "a write that has not completed when the next
    value is due on that stream is abandoned and the stream is ended". A terminal
    value is the next value due, so the stalled stream meets the abandonment clause
    exactly as it would on an ordinary delivery.

    The browser is not left guessing, because §2 rules that ending: a body that ended
    without a terminal value **is** a transport failure and the front end reports it
    as one. And §4 prices the remedy in the same breath — "a reconnect, which is
    free, because a session outlives its connections".

    The stream that *is* reading gets the terminal fault, which is the contrast that
    makes the rule a rule rather than a hole: what decides the two outcomes is whether
    the browser kept up, not whether the gateway bothered.
    """
    fan_out, engine, _ = _fan_out([None, HubUnavailableError("no hub there")])
    stalled, reading_one = fan_out.open(), fan_out.open()
    assert stalled is not None
    assert reading_one is not None
    read: list[Mapping[str, Any]] = []
    reading = asyncio.ensure_future(_drain(reading_one, read))

    await engine.answer_one_poll()  # the keep-alive; the stalled stream never takes it
    await engine.answer_one_poll()  # the poll that cannot go on

    await reading
    assert stalled.abandoned.is_set()
    assert read == [
        {"kind": "alive"},
        {"kind": "fault", "fault": "hub-unreachable", "detail": "no hub there"},
    ]
