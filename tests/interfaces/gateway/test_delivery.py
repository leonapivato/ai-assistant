"""One poll, many streams, and the acknowledgement that never leaves (ADR-0175 §4, §5).

Driven against the fan-out directly rather than through a socket, because what these
pin is *when the gateway calls* and *to how many readers it renders one answer* — the
two facts golden rule 3 turns on here, and neither is visible from a response body.
The end-to-end half lives in ``test_gateway_streams.py``.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from gateway_timing import Timers

from ai_assistant.core.errors import NotificationBudgetError, NotificationOutboxError
from ai_assistant.core.types import (
    DataTier,
    NotificationCandidate,
    NotificationDelivery,
    SpokenAudioFormat,
)
from ai_assistant.interfaces.gateway import delivery
from ai_assistant.interfaces.gateway.delivery import (
    GATEWAY_PLAYS,
    DeliveryFanOut,
    DeliveryStream,
)
from ai_assistant.testing import (
    FakeAssistantEngine,
    FakeNotificationOutbox,
    FakeNotificationStore,
)
from ai_assistant.wire.errors import HubUnavailableError

if TYPE_CHECKING:
    from collections.abc import Mapping

    from ai_assistant.core.types import Identifier

_AT = datetime(2026, 1, 2, 15, 0, tzinfo=UTC)
_BUDGET = timedelta(seconds=20)

#: How many event-loop turns a helper will yield waiting for a condition. Large
#: enough for every step the fan-out takes between one poll's answer and the next
#: poll's request, small enough that a loop which has stopped polling costs nothing
#: worth noticing.
_TURNS = 20


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
        self,
        *,
        acknowledging: Identifier | None = None,
        plays: tuple[SpokenAudioFormat, ...] = (),
        budget: timedelta,
    ) -> NotificationDelivery | None:
        """Answer the next scripted poll once the test releases it."""
        self.acknowledged.append(acknowledging)
        self.calls.append(
            (
                "next_notification",
                {"acknowledging": acknowledging, "plays": plays, "budget": budget},
            )
        )
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
        """Let the outstanding poll return, and let the loop reach the next.

        Yielded to until the fan-out has actually written, rather than a fixed number
        of turns: since ADR-0206 §8 the call is issued as its own task — so that the
        keep-alive's arbitration can see it finish — and a task costs one more turn
        between the answer and the write than an inline ``await`` did. Waiting on the
        condition instead of counting turns is what keeps this helper right the next
        time that changes.
        """
        await self.polling.wait()
        self.released.set()
        # Until this poll has finished, and then until the fan-out has reached the
        # next one or has stopped polling. Bounded so a loop that ends — a fault, the
        # last stream going — costs a few idle turns rather than hanging.
        for _ in range(_TURNS):
            await asyncio.sleep(0)
            if not self.polling.is_set():
                break
        for _ in range(_TURNS):
            if self.polling.is_set():
                break
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
    answers: list[NotificationDelivery | None | Exception],
    *,
    slots: _Slots | None = None,
    timers: Timers | None = None,
) -> tuple[DeliveryFanOut, _Scripted, _Slots]:
    """A fan-out over a scripted engine, with its hub-slot accounting visible.

    ``timers`` is the keep-alive's interval, driven by hand (ADR-0206 §8): the
    figure it is armed at is ``gateway_notification_budget``, so a test that waited
    it out would wait twenty seconds for one write.
    """
    engine = _Scripted(answers)
    held = slots or _Slots()
    return (
        DeliveryFanOut(
            engine=engine,
            budget=_BUDGET,
            acquire=held.acquire,
            release=held.release,
            defer=timers or Timers(),
        ),
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


# --- ADR-0206 §2: the gateway's own `plays`, and no browser's -----------------


def test_the_gateways_plays_names_every_spoken_audio_format_member() -> None:
    """§2: the gateway's ``plays`` names **every** member of ``SpokenAudioFormat``,
    "so no format the synthesizer can produce is excluded by the caller".

    Compared against the enumeration itself rather than against a literal list, which
    is the whole of what makes it hold: a third member added to ``SpokenAudioFormat``
    on ADR-0200 §9's measurement clause fails this until the gateway names it, which
    is the state §2 forbids.
    """
    assert set(GATEWAY_PLAYS) == set(SpokenAudioFormat)
    assert len(GATEWAY_PLAYS) == len(SpokenAudioFormat)


def test_the_order_is_a_constant_this_module_holds_with_its_measurement() -> None:
    """§2: "Their order is a constant the gateway holds, set by the implementing lane
    from a recorded measurement of what browsers decode and changeable on a further
    measurement without an ADR."

    The measurement is in the constant's own docstring, beside the value it decided —
    which is what "recorded" has to mean for a later lane to be able to check it
    against a fresh one. Pinned here so that a lane reordering the tuple and leaving
    the figures behind fails rather than passes: the two engines, their versions and
    the call the page actually decodes through are what a re-measurement replaces.
    """
    recorded = delivery.__doc__ or ""
    source = Path(delivery.__file__ or "").read_text(encoding="utf-8")
    measured = source[source.index("#: What the gateway asks") : source.index("GATEWAY_PLAYS:")]
    assert "decodeAudioData" in measured
    assert "Chromium 151.0.7922.34" in measured
    assert "WebKit 26.5" in measured
    assert "2026-08-28" in measured
    assert recorded != ""


async def test_every_poll_carries_that_value_and_nothing_derived_from_a_browser() -> None:
    """§2: ``plays`` is "a value the gateway supplies of its own, fixed and identical
    on every poll", and no browser "narrows, widens or reorders it".

    Two streams, two polls: the argument is the module constant on each, so it is
    neither assembled from how many streams are open nor recomputed per poll. §2
    records why a browser-supplied list is unavailable twice over — ADR-0177 §1's
    second clause forbids a browser argument reaching this poll at all, and even
    without it ADR-0175 §4's fan-out gives the gateway one answer for every open
    stream, so a list assembled from two browsers with different capabilities has no
    value it could take.
    """
    fan_out, engine, _ = _fan_out([None, None])
    first, second = fan_out.open(), fan_out.open()
    assert first is not None
    assert second is not None

    await engine.answer_one_poll()
    await engine.polling.wait()

    assert [call[1]["plays"] for call in engine.calls] == [GATEWAY_PLAYS, GATEWAY_PLAYS]
    fan_out.shutdown()


# --- §8: the keep-alive is paced by the interval, not by the poll -------------


async def test_a_poll_that_outruns_the_interval_still_writes_on_every_stream() -> None:
    """§8: "The gateway writes on every open delivery stream at least once per
    ``gateway_notification_budget`` **whether or not a poll has returned**."

    The state ADR-0206 §7 creates and this clause exists to keep ADR-0175 §4's
    obligation true in: a browser holding a delivery stream cannot tell a gateway
    waiting on a long synthesis from a gateway that has stopped, and tying the
    keep-alive to the poll's return would have made this ADR's one new source of
    delay the one condition the keep-alive could not report.
    """
    timers = Timers()
    fan_out, engine, _ = _fan_out([None], timers=timers)
    one, two = fan_out.open(), fan_out.open()
    assert one is not None
    assert two is not None
    here: list[Mapping[str, Any]] = []
    there: list[Mapping[str, Any]] = []
    reading = asyncio.gather(_drain(one, here), _drain(two, there))
    await engine.polling.wait()

    assert [timer.delay for timer in timers.armed] == [_BUDGET.total_seconds()]
    timers.fire_all()
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert here == [{"kind": "alive"}]
    assert there == [{"kind": "alive"}]
    fan_out.shutdown()
    await reading


async def test_the_keep_alive_is_the_value_carrying_nothing_but_its_own_kind() -> None:
    """§8: "the gateway writes 'a value carrying nothing but its own kind'… That write
    is the gateway's own, on ADR-0175 §4's terms and nothing more: it carries no part
    of any notification, is not a delivery, is acknowledged by nothing".

    So the value is ``alive`` and the *next* poll acknowledges nothing on its account:
    §5 acknowledges a delivery written to at least one open stream, and a keep-alive
    is not one.
    """
    timers = Timers()
    fan_out, engine, _ = _fan_out([None], timers=timers)
    stream = fan_out.open()
    assert stream is not None
    read: list[Mapping[str, Any]] = []
    reading = asyncio.ensure_future(_drain(stream, read))
    await engine.polling.wait()

    timers.fire_all()
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    await engine.answer_one_poll()

    assert read == [{"kind": "alive"}, {"kind": "alive"}]
    assert engine.acknowledged == [None, None]
    fan_out.shutdown()
    await reading


async def test_a_gateway_whose_polls_complete_within_budget_writes_no_extra_value() -> None:
    """§8: "A write of either kind restarts the interval, so a gateway whose polls
    complete within their budget writes exactly what it writes today and at exactly
    the cadence it writes it at today; a keep-alive is emitted only where a poll has
    outrun the interval, which before this ADR could not happen."

    Driven by counting what is *armed*: each write re-arms one interval and cancels
    the one it replaces, so a fan-out that has answered two polls holds exactly one —
    and the two values the browser saw are the two deliveries, with no keep-alive
    between them.
    """
    timers = Timers()
    fan_out, engine, _ = _fan_out([_delivery(1), _delivery(2)], timers=timers)
    stream = fan_out.open()
    assert stream is not None
    read: list[Mapping[str, Any]] = []
    reading = asyncio.ensure_future(_drain(stream, read))

    await engine.answer_one_poll()
    await engine.answer_one_poll()

    assert [value["summary"] for value in read] == ["notification 1", "notification 2"]
    assert len(timers.armed) == 1
    fan_out.shutdown()
    await reading


async def test_a_stream_stalled_behind_a_value_is_abandoned_when_the_keep_alive_falls_due() -> None:
    """§8: "ADR-0175 §4's per-stream rules bind the keep-alive unchanged… A keep-alive
    is a value due on that stream, so a stream stalled behind a rendering meets that
    clause exactly as it meets it behind any other value, and this ADR does not soften
    it."

    Nothing is queued behind the pending value — the stalled reader is holding one and
    is offered nothing more — and no other stream's cadence is delayed by it, which is
    §4's own reason for abandoning rather than waiting.
    """
    timers = Timers()
    fan_out, engine, _ = _fan_out([_delivery(1)], timers=timers)
    stalled, draining = fan_out.open(), fan_out.open()
    assert stalled is not None
    assert draining is not None
    read: list[Mapping[str, Any]] = []
    reading = asyncio.ensure_future(_drain(draining, read))

    await engine.answer_one_poll()
    timers.fire_all()
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert stalled.abandoned.is_set()
    assert [value["kind"] for value in read] == ["notification", "alive"]
    fan_out.shutdown()
    await reading


async def test_a_due_keep_alive_is_arbitrated_away_before_either_is_handed_over() -> None:
    """§8: "A delivery and a keep-alive are arbitrated at one point, and that point is
    before either is handed to any stream. The gateway decides there which value it
    writes for the elapsing interval, and where a poll has returned the delivery is
    that value: a keep-alive due or scheduled but **not yet handed to a stream** is
    discarded, and for one interval the two never both reach one stream."

    The coincidence is exact here rather than raced: the interval is armed and due —
    ``Timers`` holds the callback and fires only when a test says so — and the poll
    returns first. Adversarial review found on ADR-0206's ninth round that without
    this the pair would fill one stream's single pending slot and §4 would end a
    healthy stream in the instant after it was given the notification it was waiting
    for.
    """
    timers = Timers()
    fan_out, engine, _ = _fan_out([_delivery(1)], timers=timers)
    one, two = fan_out.open(), fan_out.open()
    assert one is not None
    assert two is not None
    here: list[Mapping[str, Any]] = []
    there: list[Mapping[str, Any]] = []
    reading = asyncio.gather(_drain(one, here), _drain(two, there))
    await engine.polling.wait()
    due = timers.armed[0]

    await engine.answer_one_poll()

    # The keep-alive that was due is discarded rather than written: it never fires,
    # so "no keep-alive follows it" is a fact about the schedule and not about the
    # order two writes happened to land in.
    assert due.cancelled is True
    assert [value["kind"] for value in here] == ["notification"]
    assert [value["kind"] for value in there] == ["notification"]
    assert not one.abandoned.is_set()
    assert not two.abandoned.is_set()
    # And the cadence continues: the delivery's own write re-armed the interval, so
    # exactly one is standing and it is not the one that was arbitrated away.
    assert [timer.delay for timer in timers.armed] == [_BUDGET.total_seconds()]
    assert due not in timers.armed
    fan_out.shutdown()
    await reading


async def test_a_keep_alive_a_stream_has_taken_is_not_retracted_by_the_delivery() -> None:
    """§8: "A keep-alive already handed to a stream is not retracted, because a value a
    stream has taken is a value a browser may already be reading. Where a delivery
    arrives behind one a browser has not yet drained, ADR-0175 §4's pending-value
    clause governs unchanged and its outcome is unchanged: the delivery is the next
    value due on that stream, the stream is abandoned and ended, and the browser
    reconnects."

    Architecture review blocked the alternative on ADR-0206's tenth round: a stream's
    slot is filled by a hand-off the gateway cannot undo, so a clause obliging a
    retraction would have been unsatisfiable. And no other open stream is affected —
    the one that drained its keep-alive takes the delivery normally.
    """
    timers = Timers()
    fan_out, engine, _ = _fan_out([_delivery(1)], timers=timers)
    stalled, draining = fan_out.open(), fan_out.open()
    assert stalled is not None
    assert draining is not None
    read: list[Mapping[str, Any]] = []
    reading = asyncio.ensure_future(_drain(draining, read))
    await engine.polling.wait()

    timers.fire_all()
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert stalled.offer({"kind": "alive"}) is False
    await engine.answer_one_poll()

    assert stalled.abandoned.is_set()
    assert [value["kind"] for value in read] == ["alive", "notification"]
    fan_out.shutdown()
    await reading


class _Gated(FakeAssistantEngine):
    """The canonical fake, answering its poll only when a test lets it.

    The fake deliberately does not sleep (its own docstring says why), so a fan-out
    driven against it answers the instant it asks — which is the one thing a test of
    ADR-0206 §8's *ordering* cannot have. Everything else is the fake's: the outbox,
    the lease and ADR-0206's rendering are unchanged, which is what makes the lease
    expiry below a real re-offer rather than a scripted one.
    """

    def __init__(self) -> None:
        """Build one whose first poll parks."""
        super().__init__()
        self.polling = asyncio.Event()
        self.released = asyncio.Event()

    async def next_notification(
        self,
        *,
        acknowledging: Identifier | None = None,
        plays: tuple[SpokenAudioFormat, ...] = (),
        budget: timedelta,
    ) -> NotificationDelivery | None:
        """Park until the test releases this poll, then answer it as the fake does."""
        self.polling.set()
        try:
            await self.released.wait()
        finally:
            self.released.clear()
            self.polling.clear()
        return await super().next_notification(
            acknowledging=acknowledging, plays=plays, budget=budget
        )


async def test_a_delivery_no_stream_took_is_re_offered_after_its_lease_expires() -> None:
    """§8: "the entry is re-offered after its lease expires where no stream took the
    delivery".

    The one stream is stalled behind a keep-alive it has not drained, so the delivery
    is written to nothing, §5 acknowledges nothing, and ADR-0131 §3's outbox holds the
    unacknowledged entry until its lease expires and offers it again — at-least-once
    behaving as built, which is what §8 means by the browser's reconnect costing the
    owner nothing but a duplicate.
    """
    at = _AT
    engine = _Gated()
    store = FakeNotificationStore(now=lambda: at)
    engine.notification_store = store
    lease = timedelta(seconds=120)
    engine.notification_outbox = FakeNotificationOutbox(records=store, now=lambda: at, lease=lease)
    await engine.notification_outbox.offer(
        NotificationCandidate(
            candidate_key="key-1",
            producer="calendar-upcoming",
            notification_class="upcoming_event",
            summary="Standup starts in ten minutes",
            noticed_at=at,
            confidence=0.9,
            sensitivity=DataTier.PERSONAL,
        )
    )
    timers = Timers()
    slots = _Slots()
    fan_out = DeliveryFanOut(
        engine=engine, budget=_BUDGET, acquire=slots.acquire, release=slots.release, defer=timers
    )
    stalled = fan_out.open()
    assert stalled is not None
    await engine.polling.wait()

    # The keep-alive lands in the stream's one pending slot and nobody drains it.
    timers.fire_all()
    await asyncio.sleep(0)
    # Now the poll returns with the delivery, which is the next value due on a stream
    # whose write has not completed — §4 abandons it rather than queueing behind.
    engine.released.set()
    for _ in range(4):
        await asyncio.sleep(0)
    fan_out.shutdown()

    assert stalled.abandoned.is_set()
    polls = [call[1] for call in engine.calls if call[0] == "next_notification"]
    assert [poll["acknowledging"] for poll in polls] == [None] * len(polls)
    assert await engine.notification_outbox.claim() is None
    at += lease + timedelta(seconds=1)
    reoffered = await engine.notification_outbox.claim()
    assert reoffered is not None
    assert reoffered.notification.summary == "Standup starts in ten minutes"


# --- §8: the keep-alive's lifetime is the fan-out's, not the poll's -----------


@pytest.mark.parametrize("ending", ["close", "shutdown"])
async def test_the_keep_alive_is_dropped_with_the_last_stream_beside_the_poll(
    ending: str,
) -> None:
    """§8: "It exists while and only while at least one delivery stream is open; it is
    dropped in the same step that ends the last stream and in the same step that ends
    them all on the way down; and nothing of it survives that step — no timer, no
    task, no pending write, and no value written on any stream afterwards."

    Both endings, because both reach the fan-out's end and ADR-0206 §8 names them
    both. The poll is outstanding when the last stream goes — the case the clause is
    written about, a synthesis still running — and it is cancelled, the interval is
    cancelled with it, and firing whatever a scheduler might still hold writes
    nothing: adversarial review found on the eighth round that an implementation
    hanging the keep-alive off a second task and leaving ``_reap`` as it stood would
    leave that task alive with no stream to write to, which is the shape ADR-0060 §1
    names when it lists "a spawned task" among what a cancellation must not orphan.
    """
    timers = Timers()
    fan_out, engine, slots = _fan_out([_delivery(1)], timers=timers)
    stream = fan_out.open()
    assert stream is not None
    read: list[Mapping[str, Any]] = []
    reading = asyncio.ensure_future(_drain(stream, read))
    await engine.polling.wait()
    assert len(timers.armed) == 1

    if ending == "close":
        fan_out.close(stream)
    else:
        fan_out.shutdown()
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert timers.armed == []
    assert slots.held == 0
    assert not engine.polling.is_set()
    timers.fire_all()
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert read == []
    await reading


async def test_nothing_is_written_on_a_stream_after_the_terminal_value() -> None:
    """§8's lifetime clause at the other ending: a poll the gateway cannot complete
    ends every stream with ADR-0175 §4's terminal value, and no keep-alive follows it.

    An interval left armed across that ending would fire onto streams that are already
    ended, where ``offer`` refuses and the fan-out would abandon a stream whose
    terminal value the browser had not yet drained — costing it the ending §4
    guarantees it.
    """
    timers = Timers()
    fan_out, engine, _ = _fan_out([HubUnavailableError("hub is down")], timers=timers)
    stream = fan_out.open()
    assert stream is not None
    read: list[Mapping[str, Any]] = []
    reading = asyncio.ensure_future(_drain(stream, read))

    await engine.answer_one_poll()
    await reading

    assert [value["kind"] for value in read] == ["fault"]
    assert timers.armed == []
    assert not stream.abandoned.is_set()


# --- ADR-0206 §9: the acknowledgement does not move ---------------------------


async def test_the_acknowledgement_rides_the_next_poll_across_a_keep_alive() -> None:
    """§9: "ADR-0175 §5 binds unchanged. The gateway acknowledges, on its next poll, a
    delivery it wrote to at least one open delivery stream and acknowledges no other."

    Whatever the page did with the rendering — and a keep-alive written between the
    delivery and the next poll is the strongest form of "whatever", because it is the
    gateway's own write arriving in between. Playback is not an acknowledgement, and
    an interrupted, dropped, unplayed or undecodable rendering changes nothing about
    what is acknowledged or when.
    """
    timers = Timers()
    delivered = _delivery(1)
    fan_out, engine, _ = _fan_out([delivered, None], timers=timers)
    stream = fan_out.open()
    assert stream is not None
    read: list[Mapping[str, Any]] = []
    reading = asyncio.ensure_future(_drain(stream, read))

    await engine.answer_one_poll()
    timers.fire_all()
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    await engine.answer_one_poll()

    assert engine.acknowledged[:2] == [None, delivered.delivery_id]
    assert [value["kind"] for value in read[:3]] == ["notification", "alive", "alive"]
    fan_out.shutdown()
    await reading


async def test_a_poll_that_returned_in_the_same_turn_wins_the_interval() -> None:
    """§8's coincidence at the instant a caller cannot see from inside an ``await``:
    the poll has **returned** and the loop has not yet resumed on it.

    "A delivery and a keep-alive are arbitrated at one point, and that point is before
    either is handed to any stream… where a poll has returned the delivery is that
    value: a keep-alive due or scheduled but **not yet handed to a stream** is
    discarded, and for one interval the two never both reach one stream."

    Adversarial review, round 1, ``blocker``. Arbitrating only from the loop's side
    left this order unhandled — the interval callback ran first, wrote ``alive`` into
    every stream's one pending slot, and the delivery that had *already been produced*
    then met ADR-0175 §4's abandonment clause on every one of them. A reconnect on
    every open stream, and the notification lost to all of them, for a liveness signal
    the delivery was about to supply.

    Driven deterministically rather than raced: the engine's answer is released and the
    loop is yielded to only until the poll's own coroutine has run past its wait —
    ``polling`` is cleared in its ``finally``, so a cleared flag means the call has
    finished and nothing has yet written its result. The interval is then fired into
    exactly that window.
    """
    timers = Timers()
    fan_out, engine, _ = _fan_out([_delivery(1)], timers=timers)
    one, two = fan_out.open(), fan_out.open()
    assert one is not None
    assert two is not None
    here: list[Mapping[str, Any]] = []
    there: list[Mapping[str, Any]] = []
    reading = asyncio.gather(_drain(one, here), _drain(two, there))
    await engine.polling.wait()
    due = timers.armed[0]

    engine.released.set()
    # Yielded turn by turn rather than awaited on an event, because what is wanted is
    # the *narrowest* window in which the call has finished and its caller has not
    # resumed — an event would be one more scheduling step wide, which is the whole of
    # what this case is about.
    for _ in range(_TURNS):
        await asyncio.sleep(0)
        if not engine.polling.is_set():
            break
    # The window: the call has returned and no value has reached any stream.
    assert here == []
    assert there == []
    timers.fire_all()
    for _ in range(4):
        await asyncio.sleep(0)

    assert due.cancelled is True
    assert [value["kind"] for value in here] == ["notification"]
    assert [value["kind"] for value in there] == ["notification"]
    assert not one.abandoned.is_set()
    assert not two.abandoned.is_set()
    fan_out.shutdown()
    await reading
