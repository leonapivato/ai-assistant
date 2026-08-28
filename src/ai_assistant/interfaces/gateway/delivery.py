"""One delivery slot, fanned out to every open stream (ADR-0175 §4, §5).

**The arithmetic this module exists for.** ADR-0131 §2 gives a device at most one
delivery connection, and a gateway is one device — so however many browsers it
serves, it holds one poll, and what it does with the one answer is the whole of the
fan-out question ADR-0168 §12 deferred to milestone 14.

**Polling only while somebody is listening is the clause the rest falls out of**
(§4). A poll that returns a delivery to a gateway with nowhere to put it has
selected an entry, minted a ``delivery_id`` and started a lease — ADR-0131 §2a makes
those one indivisible step — so the notification is withheld from anything else for
``hub_notification_lease``, for a browser that was never there. Polling on demand
costs nothing, because the outbox is durable: a notification produced while no
browser is watching waits in the place ADR-0131 §3 built for exactly that.

**The gateway retains nothing** (§4). No notification is held, replayed,
de-duplicated, re-ordered or re-judged. A gateway that buffered for browsers that
are not watching would be building ADR-0131 §3's durable outbox one hop further out
and without any of its bounds, which ADR-0094 §9 permits edge state only where it is
"bounded in size and in age and destroyed continuously".

**Writing to every open stream rather than to one is the fan-out, and it is the
only shape that is not a silent fault** (§4). Choosing one stream and starving the
rest means a second tab shows nothing with nothing saying why; evicting an incumbent
when a new stream opens is the silent-eviction lever ADR-0131 §2 and ADR-0168 §4 have
each already refused, one for a poll and one for a session.

**And it is relaying rather than authoring**, which is the golden-rule-3 question
this module has to answer rather than assert. Every clause here is about *when* the
gateway calls and *to how many readers it renders one answer*: it holds nothing,
decides nothing about a notification's content, and adds no state a browser could
observe that the hub did not produce (ADR-0168 §1).
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import TYPE_CHECKING, Any, Final

import structlog

from ai_assistant.core.errors import AssistantError, NotificationBudgetError
from ai_assistant.core.types import SpokenAudioFormat
from ai_assistant.interfaces.gateway import streams
from ai_assistant.wire.errors import TransportError

if TYPE_CHECKING:  # pragma: no cover — imported for typing alone
    from collections.abc import AsyncIterator, Callable, Mapping
    from datetime import timedelta

    from ai_assistant.core.protocols import AssistantEngine
    from ai_assistant.core.types import NotificationDelivery
    from ai_assistant.interfaces.gateway.sessions import Cancellable, Defer

_log = structlog.get_logger(__name__)

#: The fault a stream ends with when the hub could not be reached at all. The same
#: name an ordinary response carries for the same condition, so the page describes
#: it with the words it already has (ADR-0168 §9).
_UNREACHABLE: Final = "hub-unreachable"

#: The fault for a poll the hub received and declined. Its own name rather than
#: :data:`_UNREACHABLE`, because §9 requires the two "distinguishable".
_DECLINED: Final = "assistant-declined"

#: The fault for a poll that failed in neither of the two ways ADR-0168 §9 names.
#: Its own name rather than either of theirs, because §9's distinction is only worth
#: anything if a third condition is not quietly reported as one of the two.
_FAILED: Final = "delivery-failed"

#: What the gateway asks the hub to render a notification in, in preference order
#: (ADR-0206 §2). **The gateway's own value, fixed and identical on every poll**: no
#: browser request carries it, no browser value reaches it, and no browser narrows,
#: widens or reorders it. ADR-0177 §1's second clause and ADR-0175 §6's put
#: ``next_notification`` outside the browser control surface entirely, and §2 records
#: why a browser-supplied list is unavailable twice over — even without that clause,
#: ADR-0175 §4's fan-out gives one answer to every open stream, so a list assembled
#: from two browsers with different decoders has no value it could take.
#:
#: **It names every member of :class:`~ai_assistant.core.types.SpokenAudioFormat`**,
#: so no format the synthesizer can produce is excluded by the caller. What naming
#: the whole enumeration buys is stated exactly in §2 and is worth restating here,
#: because the loose version of it is wrong: it guarantees the *synthesizer's* choice
#: is never narrowed, not that every browser can play the result. The engine picks one
#: member (ADR-0200 §3) and the gateway writes that one rendering to every stream, so a
#: browser whose decoder covers only the other member plays nothing and renders the
#: notification on the page — intentionally silent, because the alternative is a
#: per-stream answer this carrier does not have.
#:
#: **The order is a measurement and not a taste**, and §2 lets a later lane change it
#: on a further measurement without an ADR. Measured 2026-08-28 on the two engines this
#: repository installs, by recording a 3 s 440 Hz tone through ``MediaRecorder`` and
#: then handing every sample to ``decodeAudioData`` in each engine — which is the call
#: the page actually plays a rendering through (``playSpoken``), not a media element:
#:
#: * Chromium 151.0.7922.34 — decodes ``audio/webm;codecs=opus`` (3.00 s) and
#:   ``audio/mp4`` (2.92 s); produces both, at 48 597 and 49 092 bytes for the same
#:   3 s tone, a 1.0% difference.
#: * WebKit 26.5 — decodes both, at 3.00 s and 2.96 s; produces neither, because
#:   Playwright's Linux WebKit ships no ``MediaRecorder`` for either type.
#:
#: So **decodability did not separate the two members on either engine and neither did
#: size**, and the order below is the tie broken on the one figure that did differ:
#: ``audio/webm;codecs=opus`` is what a browser on those engines *produces* first —
#: ``TALK_FORMATS`` in ``assets/app.js`` picks it in the same order, measured the same
#: way — so it is the member most likely to be the one a synthesizer and a page already
#: agree on. The honest caveat, recorded rather than glossed: Playwright's Linux WebKit
#: is not Safari on a phone, and milestone 19's exit test is a phone. A measurement on
#: that device is what would move this constant, and moving it costs no ADR.
GATEWAY_PLAYS: Final[tuple[SpokenAudioFormat, ...]] = (
    SpokenAudioFormat.WEBM_OPUS,
    SpokenAudioFormat.MP4,
)


#: The fault for the one refusal ADR-0175 §8 names by hand: a
#: ``gateway_notification_budget`` above the hub's own ceiling. No load-time check
#: can catch it — ``hub_max_notification_budget`` is another process's setting and
#: may be another machine's — so it arrives here, and §8 requires it reported as a
#: request the hub received and declined rather than as a transport failure.
_BUDGET_DECLINED: Final = "delivery-budget-declined"


class DeliveryStream:
    """One browser's open delivery stream, holding at most one value (ADR-0175 §4).

    **At most one value pending, and nothing queued behind it.** A queue would be
    the buffer §4 refuses, in miniature: it would grow while a browser was not
    reading, and its bound would be a figure no ADR names.

    **A write that has not completed when the next value is due is abandoned and
    the stream is ended** (§4). With several readers of one value, a reader that
    stops reading applies backpressure to the writer, and a writer that waited on it
    would delay every other reader — so the stalled stream goes instead. That costs
    the abandoned browser a reconnect, which is free: a session outlives its
    connections (ADR-0168 §8). :meth:`offer` refusing *is* that condition, because
    the pending slot is cleared by the consumer only once its write has drained.

    The clause reaches a **delivery** stream alone. "An answer stream has one reader
    and nothing to protect from it, and this clause does not reach one."
    """

    def __init__(self) -> None:
        """Open a stream holding nothing."""
        self._pending: Mapping[str, Any] | None = None
        self._ready = asyncio.Event()
        self._ended = False
        #: Set when §4's stalled-write clause fires. The connection handler races
        #: its ``drain`` against this, so a browser that has stopped reading is torn
        #: down rather than waited on — which is what actually reclaims the socket.
        self.abandoned = asyncio.Event()

    def offer(self, value: Mapping[str, Any]) -> bool:
        """Hand this stream one value, or report that it cannot take one.

        Args:
            value: The value to write, already framed as a stream value.

        Returns:
            Whether it was taken. ``False`` where the stream has ended or where the
            previous write has not completed — §4's abandonment condition, which the
            caller answers by ending the stream.
        """
        if self._ended or self._pending is not None:
            return False
        self._pending = value
        self._ready.set()
        return True

    def end(self) -> None:
        """Stop this stream once its pending value, if any, has been written.

        Idempotent, because the two callers overlap: the poll ends every stream when
        it cannot continue, and each connection handler ends its own on the way out.
        """
        self._ended = True
        self._ready.set()

    def abandon(self) -> None:
        """End this stream *now*, without waiting for a write to complete (§4)."""
        self.abandoned.set()
        self.end()

    async def values(self) -> AsyncIterator[Mapping[str, Any]]:
        """Yield each value as it is offered, until the stream ends.

        The pending slot is cleared **after** the consumer's body has run, which is
        what makes :meth:`offer` refuse while a write is outstanding rather than
        overwriting a value the browser has not received.

        Yields:
            Each offered value, in the order it was offered.
        """
        while True:
            if self._pending is None:
                if self._ended:
                    return
                self._ready.clear()
                await self._ready.wait()
            pending = self._pending
            if pending is None:
                return
            yield pending
            self._pending = None


class DeliveryFanOut:
    """The one poll, the set of streams watching it, and the acknowledgement.

    **The acknowledgement never leaves this object** (ADR-0175 §5). A
    ``delivery_id`` is placed in no value written on a stream, in no response body,
    in no document and in no URL, and no browser request carries one — because
    ADR-0131 §4 makes it a capability held by exactly one device, and ADR-0172 §1
    closes the class of values a browser holds at three and forbids widening it "by
    resemblance".
    """

    def __init__(
        self,
        *,
        engine: AssistantEngine,
        budget: timedelta,
        acquire: Callable[[], bool],
        release: Callable[[], None],
        defer: Defer,
    ) -> None:
        """Build a fan-out holding no poll, no stream and no keep-alive.

        Args:
            engine: The hub, as the promoted ``AssistantEngine``. ``next_notification``
                is the **sixth** operation the gateway calls and is not one of
                ADR-0175 §6's five, because no browser request resolves to it: this
                object originates the poll, no browser request names it, and no
                browser argument reaches it.
            budget: ``gateway_notification_budget`` — what the poll asks the hub to
                hold for, and the interval within which §4 obliges a write on every
                open stream. One figure, because the write a browser observes *is*
                the completion of the poll the budget bounds (§8).
            acquire: Take one of ``gateway_max_hub_connections``, or report that the
                ceiling refuses. The delivery connection "counts against
                ``gateway_max_hub_connections`` exactly as any hub connection does"
                (§7), and no lane gives delivery its own budget — ADR-0131 §5's rule
                applied at this door.
            release: Give that slot back.
            defer: How the keep-alive's interval is scheduled (ADR-0206 §8). The
                same seam the session table and the record interval already use,
                injected rather than reached for so a test fires it instead of
                waiting out a budget — and so the interval is observably a thing
                this object holds and drops, which §8's lifetime clause requires.
        """
        self._engine = engine
        self._budget = budget
        self._acquire = acquire
        self._release = release
        self._defer = defer
        self._streams: set[DeliveryStream] = set()
        self._poll: asyncio.Task[None] | None = None
        #: The `next_notification` call currently outstanding, as a task, or ``None``
        #: between two of them. **A task rather than a bare await, so that the
        #: arbitration point can ask whether the poll has returned** (ADR-0206 §8).
        #: Adversarial review, round 1, ``blocker``: a completed call and a resumed
        #: caller are two different instants on one event loop, and an interval
        #: elapsing between them found no way to tell "the poll has outrun its budget"
        #: from "the poll is done and its delivery is this interval's value".
        self._answering: asyncio.Task[NotificationDelivery | None] | None = None
        #: The interval ADR-0206 §8 paces the keep-alive by, armed while and only
        #: while a stream is open. ``None`` where none is armed — which, outside the
        #: instant between a write and its re-arming, means no stream is open.
        self._keep_alive: Cancellable | None = None
        #: Whether a keep-alive has been written since the poll now outstanding was
        #: issued — which is to say whether this stream's "nothing to report" has
        #: already been said for the interval the poll is running in (ADR-0206 §8,
        #: issue #1769). Reset at each poll's issue, because it is a fact about that
        #: poll and not about the fan-out.
        self._kept_alive = False

    def open(self) -> DeliveryStream | None:
        """Register a stream, opening the poll where it is the first (§4).

        Returns:
            The stream, or ``None`` where ``gateway_max_hub_connections`` refuses
            the connection this poll would need. The caller reports that naming the
            limit, as ADR-0168 §8 already requires of every request that meets it.
        """
        if self._poll is not None and self._poll.done():
            # A poll that ended on a fault holds nothing and polls no more. §4:
            # "The gateway polls again only when a browser establishes a delivery
            # stream afresh" — this is that stream, so the spent poll is reaped and
            # a fresh slot is taken for a fresh one.
            self._reap()
        if self._poll is None and not self._acquire():
            return None
        stream = DeliveryStream()
        self._streams.add(stream)
        if self._poll is None:
            self._poll = asyncio.create_task(self._run())
            # **Armed with the poll and not inside it** (ADR-0206 §8). The keep-alive
            # "exists while and only while at least one delivery stream is open", and
            # this is the step in which that becomes true — a task body does not run
            # until the loop next turns, so arming there would leave an interval that
            # is owed and not yet counting.
            self._arm_keep_alive()
        return stream

    def close(self, stream: DeliveryStream) -> None:
        """Unregister a stream, closing the delivery connection with the last (§5).

        "When the last delivery stream ends, the gateway closes its delivery
        connection. Under ADR-0131 §2a that releases the device slot and the hub's
        delivery capacity in one step, and cancels an outstanding poll that has not
        yet selected an entry." Cancelling the call is what closes that connection
        at this layer: the gateway holds no connections of its own (ADR-0168 §1), and
        the wire client "opens a connection of its own for every call and hangs up in
        its ``finally``".

        Args:
            stream: The stream that has ended.
        """
        stream.end()
        self._streams.discard(stream)
        if not self._streams:
            self._reap()

    def shutdown(self) -> None:
        """End every stream and drop the poll, on the way down (ADR-0168 §4)."""
        for stream in tuple(self._streams):
            stream.end()
        self._streams.clear()
        self._reap()

    def _reap(self) -> None:
        """Cancel the poll and the keep-alive, and give the hub slot back.

        **The keep-alive is dropped here rather than beside here** (ADR-0206 §8).
        Its "lifetime is the fan-out's and not the poll's": it is dropped in the
        same step that ends the last stream and in the same step that ends them
        all on the way down, and every one of those steps reaches this method —
        :meth:`close` when the last stream goes, :meth:`shutdown` on the way down,
        and :meth:`open` when a spent poll is replaced. Cancelling it **before**
        the early return is what makes that true rather than nearly true: a
        fan-out whose poll was already reaped still holds an armed interval, and
        a callback firing after the last stream has gone is the orphaned task
        ADR-0060 §1 names.
        """
        self._cancel_keep_alive()
        poll, self._poll = self._poll, None
        if poll is None:
            return
        poll.cancel()
        self._release()

    def _arm_keep_alive(self) -> None:
        """Start the interval afresh, replacing whatever was armed (ADR-0206 §8).

        "A write of either kind restarts the interval, so a gateway whose polls
        complete within their budget writes exactly what it writes today and at
        exactly the cadence it writes it at today; a keep-alive is emitted only
        where a poll has outrun the interval."
        """
        self._cancel_keep_alive()
        self._keep_alive = self._defer(self._budget.total_seconds(), self._keep_alive_due)

    def _cancel_keep_alive(self) -> None:
        """Call the interval off, where one is armed."""
        armed, self._keep_alive = self._keep_alive, None
        if armed is not None:
            armed.cancel()

    def _keep_alive_due(self) -> None:
        """Decide what this elapsing interval writes, and write it (ADR-0206 §8).

        **Reached only where a poll has outrun the interval**, because every write
        re-arms it — so this is the state ADR-0206 §7 creates and §8 exists to keep
        §4's obligation true in: a browser holding a delivery stream cannot tell a
        gateway waiting on a long synthesis from one that has stopped, and tying the
        keep-alive to the poll's return would have made this ADR's one new source of
        delay the one condition the keep-alive could not report.

        **It is the gateway's own write on ADR-0175 §4's terms and nothing more**: it
        carries no part of any notification, is not a delivery, is acknowledged by
        nothing, and leaves §5's acknowledgement rule and ADR-0206 §9 where they
        stand. The gateway already emits this value of its own motion whenever a poll
        returns nothing, so what §8 changes is *when* it is written and not *what*.
        """
        self._keep_alive = None
        if not self._streams:
            # The last stream went in the instant before this callback ran. §8: nothing
            # of the keep-alive survives that step, and "no value written on any stream
            # afterwards" — so this writes nothing and arms nothing.
            return
        answering = self._answering
        if answering is not None and answering.done():
            # **The coincidence, seen from this side** (§8). The poll has returned and
            # the loop has not yet resumed on it — two instants a caller cannot tell
            # apart from inside an ``await``, which is why the poll is a task. §8 fixes
            # which value the interval takes: "where a poll has returned the delivery is
            # that value: a keep-alive due or scheduled but **not yet handed to a
            # stream** is discarded". So this is the discard, and it re-arms nothing —
            # the delivery's own write restarts the interval a beat later, which is what
            # keeps the cadence write-to-write rather than shortening it by this turn.
            #
            # Adversarial review, round 1, ``blocker``. Cancelling the interval from the
            # loop's side alone was arbitration that could not see a poll which had
            # already finished: the keep-alive went out first, filled every stream's one
            # pending slot, and ADR-0175 §4 then abandoned every one of them in the
            # instant after they were given the notification they were waiting for —
            # exactly the outcome §8's ninth round was written to prevent, reached by a
            # scheduling order rather than by a missing clause.
            return
        self._write(streams.alive())
        # This interval's "nothing to report" is now said, so the outstanding poll
        # has nothing left to add by returning nothing — see :attr:`_kept_alive` and
        # the suppression in :meth:`_poll_while_watched`.
        self._kept_alive = True
        self._arm_keep_alive()

    def _write(self, value: Mapping[str, Any]) -> int:
        """Hand one value to every open stream, abandoning those that cannot take it.

        **ADR-0175 §4's per-stream rules bind both kinds unchanged.** The gateway
        holds at most one value pending per stream and queues nothing behind one, and
        a write that has not completed when the next value is due on that stream is
        abandoned and that stream ended. A keep-alive is a value due on that stream,
        so a stream stalled behind a rendering meets that clause exactly as it meets
        it behind any other value — and a delivery arriving behind a keep-alive a
        browser has not drained meets it in the other direction, which ADR-0206 §8
        states in terms: a keep-alive already handed to a stream is **not** retracted,
        because a value a stream has taken is a value a browser may already be
        reading.

        Args:
            value: The value to write, already framed as a stream value.

        Returns:
            How many streams took it.
        """
        written = 0
        for stream in tuple(self._streams):
            if stream.offer(value):
                written += 1
            else:
                stream.abandon()
        return written

    async def _run(self) -> None:
        """Poll while a stream is open, writing each answer to every one (§4, §5).

        **The acknowledgement rides the next poll and no connection is held for
        it** (§5). This loop issues that poll in the same step it fans a delivery
        out — nothing is awaited between them — so §5's write-then-disconnect arm is
        the narrow case where the acknowledgement's own poll does not complete: the
        delivery is then left unacknowledged, its lease expires and the hub offers
        the entry again, which is at-least-once behaving as ADR-0131 §3 built it, and
        the owner may see one notification twice. Either way the token is dropped
        with the loop, so nothing is carried across a period in which no stream was
        open. The alternative is available and is declined: ADR-0131 §4's idempotent
        no-op would make a blind acknowledgement on some later poll safe, but the
        token would then be held for a period bounded by nothing the gateway
        controls, because a browser may never come back.

        **A delivery is acknowledged on the offer rather than on the byte**, and §5
        says why that is where at-least-once stops: "past the gateway the guarantee
        is that the notification was written to at least one stream, not that a
        person read it". A browser whose connection dies between the write and the
        paint loses that notification, which is the shape ADR-0131 §2a already
        accepts one hop in — and closing it would mean handing a browser the
        capability ADR-0172 §1 closes its class against.

        **§4's terminal-value guarantee is unconditional, so the catch is too.** "A
        poll the gateway cannot complete ends every open delivery stream with a
        terminal value reporting it" names no exception classes, and a browser
        holding a response body cannot tell a gateway that stopped polling from one
        with nothing to say — the very condition §4 spends a keep-alive to make
        observable. So anything the three named classes do not cover still ends every
        stream, under a fault name that claims nothing about which side failed:
        ADR-0168 §9 asks for a transport failure and a request the hub received and
        declined to be distinguishable, and a poll that failed in neither of those
        ways is a third condition rather than one of them wearing the wrong label.
        """
        terminal: Mapping[str, Any] | None = None
        try:
            terminal = await self._poll_while_watched()
        except Exception as exc:
            # Logged with its traceback because it is, by construction, a condition
            # nothing here anticipated — and the streams are still ended, because a
            # browser is owed an ending whatever the gateway met.
            _log.exception("gateway.delivery.failed")
            terminal = streams.fault(_FAILED, detail=str(exc))
        # **Before the terminal value and not after it** (ADR-0206 §8, ADR-0175 §4). A
        # loop that has stopped polling writes nothing more of its own motion, and an
        # interval left armed across the ending would fire onto streams that are
        # already ended — where :meth:`DeliveryStream.offer` refuses and this object
        # would abandon a stream whose terminal value the browser had not yet drained,
        # costing it the ending §4 guarantees it.
        self._cancel_keep_alive()
        if terminal is not None:
            self._end_all(terminal)

    async def _poll_while_watched(self) -> Mapping[str, Any] | None:
        """Poll and fan out until no stream is left, or the poll cannot go on.

        Returns:
            The terminal value every open stream is owed, or ``None`` where the loop
            ended because nothing was watching any more — which owes no value,
            because there is nobody to write one to.
        """
        acknowledging: str | None = None
        while self._streams:
            # **Issued as a task so that the keep-alive can see it finish**, which is
            # ADR-0206 §8's arbitration read from the other side — see
            # :attr:`_answering`. Cancelling this loop cancels it: a task awaiting a
            # future has that future cancelled in the same step, so ADR-0175 §5's
            # "cancels an outstanding poll that has not yet selected an entry" is
            # reached exactly as it was when this was a bare ``await``.
            self._kept_alive = False
            self._answering = answering = asyncio.ensure_future(
                self._engine.next_notification(
                    acknowledging=acknowledging, plays=GATEWAY_PLAYS, budget=self._budget
                )
            )
            try:
                delivery = await answering
            except TransportError as exc:
                return streams.fault(_UNREACHABLE, detail=str(exc))
            except NotificationBudgetError as exc:
                return streams.fault(_BUDGET_DECLINED, detail=str(exc))
            except AssistantError as exc:
                return streams.fault(_DECLINED, detail=str(exc))
            finally:
                self._answering = None
            if delivery is None and self._kept_alive:
                # **The keep-alive already was this interval's write** (ADR-0206 §8,
                # issue #1769). §8 promises that "a gateway whose polls complete
                # within their budget writes exactly what it writes today and at
                # exactly the cadence it writes it at today", and today a quiet
                # stream takes one value per ``gateway_notification_budget``. One
                # figure paces both the poll and the interval, and the hub holds the
                # poll for the whole of it — so the interval falls due a round trip
                # *before* every empty poll returns, and writing on that return as
                # well put two values carrying nothing but their own kind on every
                # quiet stream, every interval, for ever. The second says nothing the
                # first did not; §8 changes "**when** it is written and not **what**",
                # so the interval's write is kept and this one is dropped.
                #
                # It is not a write, so it does not restart the interval: re-arming
                # here would push the cadence out by that round trip each time and
                # break §4's "at least once per interval" by the drift.
                if self._keep_alive is None:
                    # Except where the arbitration above discarded an interval on the
                    # promise that this write would restart it. Where the write is the
                    # redundant one the promise is kept here instead, because §8 holds
                    # an interval armed while a stream is open and on a quiet stream
                    # the timer is the only thing that writes at all.
                    self._arm_keep_alive()
                acknowledging = None
                continue
            # A delivery where the poll returned one, and otherwise a value carrying
            # nothing but its own kind (§4) — the first such value of the interval it
            # falls in, the branch above having dropped the second. The keep-alive is
            # not decoration: a stream that writes nothing for an hour is one nothing
            # can distinguish from a stream that has died, at either end, and ADR-0168
            # §9 is explicit that a browser reaching a running gateway must learn that
            # the hub is down rather than that nothing is there.
            value = streams.alive() if delivery is None else streams.notification(delivery)
            # **The one arbitration point, and it is before either value is handed to
            # any stream** (ADR-0206 §8). "The gateway decides there which value it
            # writes for the elapsing interval, and where a poll has returned the
            # delivery is that value: a keep-alive due or scheduled but **not yet
            # handed to a stream** is discarded, and for one interval the two never
            # both reach one stream." Cancelling here is that discard — and it is the
            # only line at which one is possible, because after the hand-off there is
            # a browser that may already be reading and a retraction no implementation
            # can perform (architecture review's ruling, ADR-0206 §8's tenth round).
            self._cancel_keep_alive()
            watching = tuple(self._streams)
            written = self._write(value)
            # The interval restarts from this write, whichever kind it was, so the
            # cadence a browser observes is write-to-write and never poll-to-poll.
            self._arm_keep_alive()
            # §5: acknowledged only where it was written to at least one open stream.
            acknowledging = None if delivery is None or not written else delivery.delivery_id
            if delivery is not None:
                _log.info(
                    "gateway.delivery",
                    streams_written=written,
                    streams_abandoned=len(watching) - written,
                )
        return None

    def _end_all(self, value: Mapping[str, Any]) -> None:
        """End every open stream with one terminal value (§4).

        "A poll the gateway cannot complete ends every open delivery stream with a
        terminal value reporting it… The gateway polls again only when a browser
        establishes a delivery stream afresh, and retries no poll of its own motion."

        **A stream whose previous write has not completed is abandoned instead, and
        that is §4 rather than a shortfall of it.** Three of its clauses meet here and
        the other two decide the case: the gateway "holds at most one value pending
        per stream and queues nothing behind one", and "a write that has not completed
        when the next value is due on that stream is abandoned and the stream is
        ended". A terminal value is the next value due, so a stalled stream meets the
        abandonment clause exactly as it would on an ordinary delivery — and the
        browser is not left guessing, because §2 rules that a body which ended without
        a terminal value **is** a transport failure and the front end reports it as
        one. §4 prices the remedy in the same breath: "a reconnect — which is free,
        because a session outlives its connections".

        The alternative would breach two clauses to satisfy one. Holding the terminal
        value behind the pending one is the queue §4 forbids; replacing the pending
        one is withholding a value from a browser, which §4 forbids in terms — and on
        a *delivery* it would retire a notification nobody ever saw, because §5
        acknowledges on the offer.
        """
        for stream in tuple(self._streams):
            if not stream.offer(value):
                stream.abandon()
            stream.end()


async def write_stream(
    writer: asyncio.StreamWriter,
    stream: DeliveryStream,
    *,
    frame: Callable[[Mapping[str, Any]], bytes],
) -> None:
    """Write one delivery stream's values until it ends or is abandoned (§4).

    The drain is raced against :attr:`DeliveryStream.abandoned` rather than merely
    awaited, because a browser that has stopped reading fills the socket's window
    and a bare ``drain`` on it never returns. Ending such a stream is what actually
    reclaims the connection; without the race the abandonment clause would be a
    decision the gateway made and could not act on.

    Args:
        writer: The connection's writer, already carrying the stream's head.
        stream: The stream to drain.
        frame: How one value becomes bytes on the wire.
    """
    async for value in stream.values():
        writer.write(frame(value))
        drained = asyncio.ensure_future(writer.drain())
        abandoned = asyncio.ensure_future(stream.abandoned.wait())
        try:
            await asyncio.wait({drained, abandoned}, return_when=asyncio.FIRST_COMPLETED)
            if not drained.done():
                return
            await drained
        finally:
            for pending in (drained, abandoned):
                pending.cancel()
                with contextlib.suppress(asyncio.CancelledError, ConnectionError, OSError):
                    await pending
