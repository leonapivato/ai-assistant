"""The streamed surface end to end, over the gateway's own listener (ADR-0175).

Driven through a real socket for ``test_gateway.py``'s reason and one more of its
own: ADR-0175 §1 makes a stream "the body of the response to one ordinary HTTP
request", so what is under test here *is* the framing on the wire — a chunked body,
a value per line, and an ending a reader can tell apart from a cut connection. None
of that is visible from a handler call.

Marked ``integration`` because a loopback socket is what they open.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import socket
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import pytest
from gateway_timing import Clock, Timers

from ai_assistant.core.config import Settings
from ai_assistant.core.errors import UnknownConversationError
from ai_assistant.core.types import (
    ActionPlan,
    CurrentContext,
    DataTier,
    Goal,
    MemorySource,
    NotificationCandidate,
    NotificationDelivery,
    Provenance,
    ReplyChunk,
    TimeOfDay,
    TurnOutcome,
    TurnResult,
)
from ai_assistant.interfaces.gateway.http import Request, Response
from ai_assistant.interfaces.gateway.server import _ASSISTANT_PATHS, Gateway
from ai_assistant.testing import FakeAssistantEngine
from ai_assistant.wire.errors import HubUnavailableError

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from ai_assistant.core.types import EncodableText, Identifier

pytestmark = pytest.mark.integration

_AT = datetime(2026, 1, 2, 15, 0, tzinfo=UTC)

_BUNDLE = {
    "/": (b"<!doctype html><p>document", "text/html; charset=utf-8"),
    "/app.css": (b"body{}", "text/css; charset=utf-8"),
    "/app.js": (b"'use strict';", "text/javascript; charset=utf-8"),
}

#: The token ADR-0131 §4 mints, distinctive so a case can search a whole body for it.
_TOKEN = "9." + "c4" * 16


def _turn(utterance: str) -> TurnResult:
    """A turn whose plan has no step — a real ratified shape, not a stub."""
    goal = Goal(
        id="g-1",
        statement=utterance,
        provenance=Provenance(source=MemorySource.USER_ASSERTED, confidence=1.0, last_updated=_AT),
        created_at=_AT,
    )
    return TurnResult(
        goal=goal,
        context=CurrentContext(
            now=_AT,
            time_of_day=TimeOfDay.AFTERNOON,
            is_weekend=False,
            within_working_hours=True,
        ),
        memories=(),
        plan=ActionPlan(id="p-1", goal_id=goal.id, steps=(), created_at=_AT),
    )


def _delivery(number: int = 1) -> NotificationDelivery:
    """One delivery, as ``next_notification`` hands it back."""
    return NotificationDelivery(
        delivery_id=_TOKEN if number == 1 else f"{number}." + f"{number:02x}" * 16,
        notification=NotificationCandidate(
            candidate_key=f"key-{number}",
            producer="calendar-reader",
            notification_class="calendar-upcoming",
            summary=f"notification {number}",
            detail="the detail",
            noticed_at=_AT,
            confidence=0.8,
            sensitivity=DataTier.PERSONAL,
        ),
    )


class _Delivering(FakeAssistantEngine):
    """An engine whose polls are released one at a time (see ``test_delivery.py``)."""

    def __init__(self, answers: list[NotificationDelivery | None | Exception]) -> None:
        """Script one answer per poll."""
        super().__init__()
        self.answers = answers
        self.released = asyncio.Event()
        self.polling = asyncio.Event()

    async def next_notification(
        self, *, acknowledging: Identifier | None = None, budget: timedelta
    ) -> NotificationDelivery | None:
        """Answer the next scripted poll once the test releases it."""
        self.calls.append(("next_notification", {"acknowledging": acknowledging, "budget": budget}))
        self.polling.set()
        try:
            await self.released.wait()
        finally:
            self.released.clear()
            self.polling.clear()
        answer = self.answers.pop(0) if self.answers else None
        if isinstance(answer, Exception):
            raise answer
        return answer

    async def answer_one_poll(self) -> None:
        """Let the outstanding poll return and the fan-out act on it."""
        await self.polling.wait()
        self.released.set()
        for _ in range(4):
            await asyncio.sleep(0)


class _StreamUnreachable(FakeAssistantEngine):
    """An engine whose hub is not there, on the streaming entry (ADR-0168 §9)."""

    def converse_streaming(
        self,
        utterance: EncodableText,
        *,
        timeout: timedelta,
        conversation_id: Identifier | None = None,
    ) -> AsyncIterator[ReplyChunk | TurnOutcome]:
        """Fail the way a closed door fails, from the iteration."""
        self.calls.append(("converse_streaming", {"utterance": utterance}))

        async def failing() -> AsyncIterator[ReplyChunk | TurnOutcome]:
            # The ``yield`` is what makes this an async generator, and it is placed
            # before the raise so it is reachable rather than dead — the guard is
            # what stops it ever running, and the raise is what the caller sees.
            if self.calls:
                msg = "no hub is listening on that socket"
                raise HubUnavailableError(msg)
            yield ReplyChunk(text="unreachable")

        return failing()


class _Abandonable(FakeAssistantEngine):
    """An engine whose stream records whether the consumer closed it (ADR-0175 §3)."""

    def __init__(self) -> None:
        """Start with nothing yielded and nothing closed."""
        super().__init__()
        self.closed = asyncio.Event()
        self.first_chunk = asyncio.Event()

    def converse_streaming(
        self,
        utterance: EncodableText,
        *,
        timeout: timedelta,
        conversation_id: Identifier | None = None,
    ) -> AsyncIterator[ReplyChunk | TurnOutcome]:
        """Yield chunks forever, recording the close the caller owes."""
        self.calls.append(("converse_streaming", {"utterance": utterance}))

        async def endless() -> AsyncIterator[ReplyChunk | TurnOutcome]:
            try:
                while True:
                    yield ReplyChunk(text="tick ")
                    self.first_chunk.set()
                    await asyncio.sleep(0)
            finally:
                self.closed.set()

        return endless()


@dataclass
class Harness:
    """A bound gateway, its port, and the engine behind it."""

    gateway: Gateway
    server: asyncio.Server
    settings: Settings
    engine: FakeAssistantEngine
    clock: Clock
    timers: Timers
    header_half: str = ""
    cookie_half: str = ""
    #: Every connection this harness opened. Held because a ``StreamWriter`` that is
    #: garbage collected closes its transport, which would end a stream under a test
    #: still reading it — a failure that looks exactly like the gateway hanging up.
    opened: list[asyncio.StreamWriter] = field(default_factory=list)

    @property
    def authority(self) -> str:
        """The `Host` this gateway admits."""
        return f"127.0.0.1:{self.settings.gateway_port}"

    async def connect(self) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        """Open one connection to the gateway, and hold it open."""
        reader, writer = await asyncio.open_connection("127.0.0.1", self.settings.gateway_port)
        self.opened.append(writer)
        return reader, writer

    def head(
        self, method: str, path: str, *, admitted: bool = True, length: int | None = None
    ) -> str:
        """One request head, with whichever halves the case presents."""
        lines = [
            f"{method} {path} HTTP/1.1",
            f"Host: {self.authority}",
            f"Origin: http://{self.authority}",
        ]
        if length is not None:
            lines.append("Content-Type: application/json")
            lines.append(f"Content-Length: {length}")
        if admitted:
            lines.append(f"X-Assistant-Session: {self.header_half}")
            lines.append(f"Cookie: assistant_session={self.cookie_half}")
        return "\r\n".join(lines) + "\r\n\r\n"

    async def send(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        admitted: bool = True,
        connection: tuple[asyncio.StreamReader, asyncio.StreamWriter] | None = None,
    ) -> tuple[asyncio.StreamReader, dict[str, list[str]], int]:
        """Send one request and read back its head.

        Returns:
            The reader positioned at the body, the response headers, and the status.
        """
        reader, writer = connection or await self.connect()
        self.opened.append(writer)
        body = b"" if payload is None else json.dumps(payload).encode()
        head = self.head(
            method, path, admitted=admitted, length=None if payload is None else len(body)
        )
        writer.write(head.encode() + body)
        await writer.drain()
        raw = await reader.readuntil(b"\r\n\r\n")
        lines = raw.decode().split("\r\n")
        headers: dict[str, list[str]] = {}
        for line in lines[1:]:
            if not line:
                continue
            name, _, value = line.partition(":")
            headers.setdefault(name.lower(), []).append(value.strip())
        return reader, headers, int(lines[0].split(" ")[1])

    async def whole(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        admitted: bool = True,
    ) -> tuple[int, dict[str, Any]]:
        """Send one request answered whole, and parse its JSON body."""
        reader, headers, status = await self.send(method, path, payload, admitted=admitted)
        body = await reader.readexactly(int(headers.get("content-length", ["0"])[0]))
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError:
            parsed = {}
        return status, parsed if isinstance(parsed, dict) else {}


async def _values(reader: asyncio.StreamReader) -> AsyncIterator[dict[str, Any]]:
    """Read a chunked NDJSON body, one value at a time, until it ends.

    Stops on the zero-length chunk *or* on the connection going away, which is the
    partition ADR-0175 §2 makes a reader act on: a body that ended without a terminal
    value is a transport failure and nothing here manufactures one.
    """
    pending = ""
    while True:
        try:
            size_line = await reader.readuntil(b"\r\n")
        except asyncio.IncompleteReadError, ConnectionError:
            return
        size = int(size_line.strip(), 16)
        if size == 0:
            with contextlib.suppress(asyncio.IncompleteReadError, ConnectionError):
                await reader.readuntil(b"\r\n")
            return
        try:
            payload = await reader.readexactly(size)
            await reader.readexactly(2)
        except asyncio.IncompleteReadError, ConnectionError:
            return
        pending += payload.decode("utf-8")
        while "\n" in pending:
            framed, _, pending = pending.partition("\n")
            if framed:
                yield json.loads(framed)


async def _read_all(reader: asyncio.StreamReader) -> list[dict[str, Any]]:
    """Every value one stream carried."""
    return [value async for value in _values(reader)]


def _free_port() -> int:
    """A port nothing is listening on, so two runs do not collide."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


@contextlib.asynccontextmanager
async def _harness(
    engine: FakeAssistantEngine | None = None, **overrides: Any
) -> AsyncIterator[Harness]:
    """Bind one gateway with a session already minted, and tear it down after."""
    settings = Settings(gateway_port=_free_port(), **overrides)
    clock, timers = Clock(), Timers()
    behind = engine or FakeAssistantEngine()
    gateway = Gateway(settings=settings, engine=behind, now=clock, defer=timers, bundle=_BUNDLE)
    server = await gateway.start()
    harness = Harness(
        gateway=gateway,
        server=server,
        settings=settings,
        engine=behind,
        clock=clock,
        timers=timers,
    )
    try:
        value = gateway.mint_bootstrap()
        reader, headers, status = await harness.send(
            "POST", "/session", {"bootstrap_value": value}, admitted=False
        )
        assert status == 200
        disclosed = json.loads(await reader.readexactly(int(headers["content-length"][0])))
        harness.header_half = disclosed["header_half"]
        harness.cookie_half = headers["set-cookie"][0].split(";")[0].partition("=")[2]
        yield harness
    finally:
        for writer in harness.opened:
            with contextlib.suppress(Exception):
                writer.close()
        gateway.close()
        server.close()
        with contextlib.suppress(Exception):
            await server.wait_closed()


@pytest.fixture
async def harness() -> AsyncIterator[Harness]:
    """A gateway on ADR-0168 §8's and ADR-0175 §8's own figures."""
    async with _harness() as one:
        yield one


# --- ADR-0175 §1, §3: a turn's answer streams --------------------------------


async def test_a_streamed_turn_is_a_chunked_body_of_ndjson_values(harness: Harness) -> None:
    """§1: every message the gateway sends a browser is "the body of the response to
    one ordinary HTTP request that browser made" — and §2 leaves the framing to this
    lane, which chose one JSON object per line."""
    reader, headers, status = await harness.send(
        "POST", "/ask/stream", {"utterance": "what is on today"}
    )

    values = await _read_all(reader)

    assert status == 200
    assert headers["transfer-encoding"] == ["chunked"]
    assert "content-length" not in headers
    assert headers["content-type"] == ["application/x-ndjson"]
    assert [value["kind"] for value in values][-1] == "outcome"


async def test_a_streamed_turn_yields_chunks_then_exactly_one_terminal_outcome(
    harness: Harness,
) -> None:
    """§3: "one value per ``ReplyChunk``, then one terminal value carrying the
    ``TurnOutcome``"."""
    reader, _, _ = await harness.send("POST", "/ask/stream", {"utterance": "what is on today"})

    values = await _read_all(reader)

    kinds = [value["kind"] for value in values]
    assert set(kinds[:-1]) <= {"chunk"}
    assert kinds[-1] == "outcome"
    assert kinds.count("outcome") == 1


async def test_the_terminal_reply_is_the_answer_and_the_chunks_joined_to_it(
    harness: Harness,
) -> None:
    """ADR-0173 §3 binds at this edge unchanged (§3): "The terminal ``TurnOutcome``'s
    ``reply`` is the answer; where a rendered chunk sequence and it disagree, the
    front end renders the terminal ``reply``".

    The canonical fake derives its chunks from the outcome, so the join holding here
    is the property a client can rely on — and the clause the page obeys is that it
    renders the terminal value rather than what it accumulated.
    """
    reader, _, _ = await harness.send("POST", "/ask/stream", {"utterance": "what is on today"})

    values = await _read_all(reader)

    joined = "".join(value["text"] for value in values if value["kind"] == "chunk")
    assert values[-1]["outcome"]["reply"] == joined


async def test_the_terminal_value_carries_the_turn_whole(harness: Harness) -> None:
    """§3: "The terminal value carries the ``TurnOutcome`` whole, so all four of
    ADR-0173 §6's shapes are readable at the browser from the two members alone."

    Asserted against the non-streaming entry's own view, because ADR-0175 §3 keeps
    both turn entries on this surface and "the gateway never substitutes one for the
    other" — two renderings of one turn that disagreed would be the substitution
    performed by the view rather than by the router.
    """
    reader, _, _ = await harness.send("POST", "/ask/stream", {"utterance": "what is on today"})
    streamed = (await _read_all(reader))[-1]["outcome"]

    _, whole = await harness.whole("POST", "/ask", {"utterance": "what is on today"})

    assert set(streamed) == set(whole["outcome"])
    assert {"reply", "reply_degraded", "step", "steps", "conversation_id"} <= set(streamed)


async def test_a_partly_composed_answer_arrives_with_the_flag_that_says_so(
    harness: Harness,
) -> None:
    """§3's fourth shape — "owed and **partly** produced" — is the one a browser
    surface loses by accident, because showing the chunks and stopping displays it
    identically to a complete answer. Both members cross, so the page can tell.
    """
    harness.engine.turn_outcome = TurnOutcome(
        turn=_turn("what is on today"),
        conversation_id=harness.engine.start_conversation("c-partial"),
        reply="half an answer",
        reply_degraded=True,
    )

    reader, _, _ = await harness.send(
        "POST", "/ask/stream", {"utterance": "what is on today", "conversation_id": "c-partial"}
    )
    values = await _read_all(reader)

    assert values[-1]["outcome"]["reply"] == "half an answer"
    assert values[-1]["outcome"]["reply_degraded"] is True


async def test_a_streamed_turn_the_hub_could_not_answer_ends_in_a_terminal_fault() -> None:
    """§3: "or one terminal value carrying the fault the exchange ended in", and §2
    keeps that distinguishable from a body that simply stopped."""
    async with _harness(_StreamUnreachable()) as one:
        reader, _, status = await one.send("POST", "/ask/stream", {"utterance": "what is on today"})

        values = await _read_all(reader)

        assert status == 200
        assert values == [
            {
                "kind": "fault",
                "fault": "hub-unreachable",
                "detail": "no hub is listening on that socket",
            }
        ]


async def test_a_stream_the_browser_abandoned_closes_the_engines_iterator() -> None:
    """§3: "The gateway closes every engine stream it opened, on every exit and early
    ones included, through the closing seam ``core.streams`` carries."

    "A browser that goes away… is an early exit, and none of them leaves an iteration
    open." This surface is the first consumer that will routinely abandon one, where
    the CLI drives every stream to exhaustion — so a lane consuming this with a bare
    ``async for`` and a ``break`` leaks a turn's resources on the most common path
    this surface has.
    """
    engine = _Abandonable()
    async with _harness(engine) as one:
        reader, writer = await one.connect()
        await one.send(
            "POST", "/ask/stream", {"utterance": "what is on today"}, connection=(reader, writer)
        )
        await asyncio.wait_for(engine.first_chunk.wait(), timeout=5)

        writer.close()
        with contextlib.suppress(Exception):
            await writer.wait_closed()

        await asyncio.wait_for(engine.closed.wait(), timeout=5)


async def test_a_turn_asked_for_whole_is_never_answered_from_a_stream(harness: Harness) -> None:
    """§3: "A streamed turn is not re-asked as ``converse`` by the gateway, whatever
    it produced, and a turn the browser asked for whole is answered by ``converse``
    and never from a stream."

    The fallback is forbidden twice over — ADR-0168 §9 has the gateway not retry
    silently, and ADR-0173 §7 refuses the same fallback one layer in because past the
    first chunk it "produces a complete answer that does not begin with the text the
    user already read".
    """
    reader, headers, _ = await harness.send("POST", "/ask/stream", {"utterance": "one"})
    await _read_all(reader)
    _, whole_headers, _ = await harness.send("POST", "/ask", {"utterance": "two"})

    assert headers["content-type"] == ["application/x-ndjson"]
    assert whole_headers["content-type"] == ["application/json"]
    called = [name for name, _ in harness.engine.calls]
    assert called == ["converse_streaming", "converse"]


@pytest.mark.parametrize(
    ("method", "path"),
    [("POST", "/ask/stream"), ("GET", "/deliveries")],
)
async def test_an_unadmitted_stream_request_is_refused_and_never_reaches_the_engine(
    harness: Harness, method: str, path: str
) -> None:
    """ADR-0168 §1's biconditional, on the two shapes ADR-0175 adds. §3 serves a
    stream only to an admitted browser, and §7 restates it: "No stream is served on
    [an unadmitted connection], because no stream is served without the session that
    admits it"."""
    status, body = await harness.whole(method, path, admitted=False)

    assert status == 401
    assert body == {"fault": "no-live-session"}
    assert harness.engine.calls == []


async def test_a_streamed_turn_with_no_utterance_is_refused_before_the_head_is_written(
    harness: Harness,
) -> None:
    """Everything decidable before the engine is reached keeps its own status — a
    stream's head is written only once the gateway has committed to answering on
    one, and a fault after that has nowhere to put a status code."""
    status, body = await harness.whole("POST", "/ask/stream", {"conversation_id": "c-1"})

    assert status == 400
    assert body == {"fault": "malformed-request"}
    assert harness.engine.calls == []


# --- ADR-0175 §4, §5: the delivery stream ------------------------------------


async def test_a_delivery_reaches_the_browser_without_its_token() -> None:
    """§4 writes the delivery "unchanged", and §5: "A ``delivery_id`` never reaches a
    browser. It is placed in no value the gateway writes on a stream, in no response
    body, in no document and in no URL, and no browser request carries one."

    Searched over the raw body rather than over parsed keys, so a member added later
    that happened to carry the token fails here.
    """
    engine = _Delivering([_delivery(1)])
    async with _harness(engine) as one:
        reader, headers, status = await one.send("GET", "/deliveries")
        assert status == 200
        assert headers["content-type"] == ["application/x-ndjson"]

        await engine.answer_one_poll()
        value = await anext(_values(reader))

        assert value == {
            "kind": "notification",
            "notification_class": "calendar-upcoming",
            "summary": "notification 1",
            "detail": "the detail",
        }
        assert _TOKEN not in json.dumps(value)


async def test_a_quiet_poll_writes_the_keep_alive_so_the_stream_stays_legible() -> None:
    """§4: the gateway writes on every open stream "at least once per
    ``gateway_notification_budget``… and otherwise a value carrying nothing but its
    own kind".

    "A stream that writes nothing for an hour is a stream nothing can distinguish
    from one that has died, at either end."
    """
    engine = _Delivering([None])
    async with _harness(engine) as one:
        reader, _, _ = await one.send("GET", "/deliveries")

        await engine.answer_one_poll()
        value = await anext(_values(reader))

        assert value == {"kind": "alive"}


async def test_one_delivery_reaches_both_of_one_browsers_streams() -> None:
    """§4's fan-out, on the wire: "written to **every** delivery stream open at the
    moment it returned".

    "There is at most one live session", so what this rules is "one delivery to the
    several *connections* of one browser — its tabs" (§4's own reading of ADR-0168 §5
    and ADR-0174 §9).
    """
    engine = _Delivering([_delivery(1)])
    async with _harness(engine) as one:
        first, _, _ = await one.send("GET", "/deliveries")
        second, _, _ = await one.send("GET", "/deliveries")
        await engine.polling.wait()

        # Two streams, one poll: §12 checks this against ADR-0168 §1's biconditional
        # and finds a second stream "does not *originate* a further call, because
        # ADR-0131 §2 gives the device one slot". A reader taking "resolves to calls"
        # as "originates a call" would build two and be closed on the second.
        assert [name for name, _ in engine.calls] == ["next_notification"]

        await engine.answer_one_poll()

        assert (await anext(_values(first)))["summary"] == "notification 1"
        assert (await anext(_values(second)))["summary"] == "notification 1"


async def test_a_poll_the_gateway_cannot_complete_ends_the_stream_naming_it() -> None:
    """§4: "A poll the gateway cannot complete ends every open delivery stream with a
    terminal value reporting it, distinguishing a transport failure from a request
    the hub received and declined (ADR-0168 §9)"."""
    engine = _Delivering([HubUnavailableError("no hub is listening on that socket")])
    async with _harness(engine) as one:
        reader, _, _ = await one.send("GET", "/deliveries")

        await engine.answer_one_poll()
        values = await _read_all(reader)

        assert values == [
            {
                "kind": "fault",
                "fault": "hub-unreachable",
                "detail": "no hub is listening on that socket",
            }
        ]


async def test_the_hub_ceiling_refuses_a_delivery_stream_naming_the_limit() -> None:
    """§7: "The gateway's delivery connection counts against
    ``gateway_max_hub_connections`` exactly as any hub connection does, and a request
    that would need one beyond that ceiling is refused naming the limit."

    At a ceiling of one, "a gateway can serve a delivery stream or a turn and not
    both, refusing the other with a message naming the limit".
    """
    engine = _Delivering([None])
    async with _harness(engine, gateway_max_hub_connections=1) as one:
        _watching, _, status = await one.send("GET", "/deliveries")
        assert status == 200
        await engine.polling.wait()

        refused_status, body = await one.whole("POST", "/ask", {"utterance": "what is on today"})

        assert refused_status == 503
        assert body == {"fault": "hub-connection-ceiling", "limit": "gateway_max_hub_connections"}


# --- ADR-0175 §7: what a stream does and does not do to its connection -------


async def test_the_read_deadline_does_not_cut_a_stream_it_is_shorter_than() -> None:
    """§7: "A connection on which a response the gateway has not finished writing is
    outstanding is **not idle**… and closes no connection while a stream on it is
    open."

    A reader holding only ADR-0168 §8 would end every stream ADR-0175 §1 defines
    thirty seconds after its request arrived — "which is not a stricter reading of the
    surface — it is a gateway on which the surface cannot exist". The deadline here is
    armed around the *read*, which begins once the previous response completed, so it
    is already the response-keyed rule §7 ratifies.
    """
    engine = _Delivering([None, _delivery(2)])
    async with _harness(engine, gateway_read_timeout=timedelta(milliseconds=20)) as one:
        reader, _, _ = await one.send("GET", "/deliveries")
        await engine.answer_one_poll()
        assert (await anext(_values(reader)))["kind"] == "alive"

        await asyncio.sleep(0.1)  # several deadlines' worth, with the stream open
        await engine.answer_one_poll()

        assert (await anext(_values(reader)))["summary"] == "notification 2"


async def test_an_open_stream_is_not_use_of_the_session_and_dies_with_it() -> None:
    """§7, two clauses at once.

    "An open stream is not use of the session that admitted it.
    ``gateway_session_idle_timeout`` is refreshed by a request the gateway admits and
    by nothing else — not by a stream's continued existence, not by a value the
    gateway writes on one, and not by a delivery poll." That bound exists so an
    unattended session dies, and a page left open is exactly the unattended case, so a
    stream must not be the thing that argues the owner is present (#1320's figure went
    the other way, and §7 keeps this one from following it).

    "A stream ends no later than the session that admitted it, and the gateway ends
    every stream a session held at the moment that session ends." A held-open stream
    sends no further request, so without that the gateway would learn of the session's
    death only from a request that never comes.
    """
    engine = _Delivering([None, None])
    async with _harness(engine, gateway_session_idle_timeout=timedelta(minutes=5)) as one:
        reader, _, _ = await one.send("GET", "/deliveries")
        await engine.answer_one_poll()
        assert (await anext(_values(reader)))["kind"] == "alive"

        one.clock.advance(timedelta(minutes=6))
        one.timers.fire_all()
        await asyncio.sleep(0)

        assert await _read_all(reader) == []
        status, body = await one.whole("POST", "/ask", {"utterance": "what is on today"})
        assert (status, body) == (401, {"fault": "no-live-session"})


# --- ADR-0175 §6: the conversation surface, and the enumeration --------------


async def test_the_browser_lists_conversations_most_recently_active_first(
    harness: Harness,
) -> None:
    """§6's ``recent_conversations``. ADR-0074 §2's sort key is activity and never
    "has a turn landed", and both instants cross so the page can render the
    difference rather than borrowing one reading for the other."""
    harness.engine.start_conversation("c-old")
    harness.engine.start_conversation("c-new")

    status, body = await harness.whole("POST", "/conversations", {})

    assert status == 200
    assert [one["id"] for one in body["conversations"]] == ["c-new", "c-old"]
    assert set(body["conversations"][0]) == {
        "id",
        "started_at",
        "last_active_at",
        "last_turn_at",
    }


async def test_a_page_of_conversations_can_be_asked_for(harness: Harness) -> None:
    """The two arguments ``recent_conversations`` takes, relayed rather than composed:
    the gateway "composes no behaviour the promoted engine surface does not offer"
    (ADR-0168 §1), so paging is the engine's and this is the request shape for it."""
    for name in ("c-1", "c-2", "c-3"):
        harness.engine.start_conversation(name)

    _, body = await harness.whole("POST", "/conversations", {"limit": 1, "offset": 1})

    assert [one["id"] for one in body["conversations"]] == ["c-2"]


async def test_a_flag_where_a_page_size_belongs_is_refused(harness: Harness) -> None:
    """``bool`` is an ``int`` by inheritance, so ``{"limit": true}`` would otherwise be
    a page of one that nothing downstream could tell from a request for one — the
    same reading ``Settings`` refuses on every count it holds."""
    status, body = await harness.whole("POST", "/conversations", {"limit": True})

    assert status == 400
    assert body == {"fault": "malformed-request"}
    assert harness.engine.calls == []


async def test_the_browser_reads_a_conversations_count_and_span_before_destroying_it(
    harness: Harness,
) -> None:
    """§6's ``conversation``. ADR-0073 §5's show-then-confirm at the unit the user
    thinks in — "the count and the span, rather than a transcript nobody can read"
    (ADR-0074 §8)."""
    harness.engine.start_conversation("c-1")

    status, body = await harness.whole("POST", "/conversation", {"conversation_id": "c-1"})

    assert status == 200
    assert set(body["conversation"]) == {"id", "started_at", "last_turn_at", "recorded_turns"}


async def test_a_conversation_that_is_not_there_is_its_own_condition(harness: Harness) -> None:
    """``conversation`` answers ``None`` where the id names nothing live, which is a
    different fact from a hub that declined the request — and ADR-0168 §9 requires the
    conditions kept apart rather than flattened."""
    status, body = await harness.whole("POST", "/conversation", {"conversation_id": "c-absent"})

    assert status == 404
    assert body == {"fault": "no-such-conversation"}


async def test_the_browser_forgets_one_conversation(harness: Harness) -> None:
    """§6's ``forget_conversation``, which "widens what a script on the gateway's own
    origin can spend, and the honest accounting is that it widens it by less than what
    is already there": ADR-0168 §6's residual has covered ``converse`` since milestone
    13, and a turn can approve a tool, execute it and durably commit a non-idempotent
    effect."""
    harness.engine.start_conversation("c-1")

    status, body = await harness.whole("POST", "/conversation/forget", {"conversation_id": "c-1"})

    assert (status, body) == (200, {"destroyed": True})
    assert ("forget_conversation", {"conversation_id": "c-1"}) in harness.engine.calls
    _, listed = await harness.whole("POST", "/conversations", {})
    assert listed["conversations"] == []


async def test_a_conversation_the_hub_declined_is_reported_as_a_declined_request() -> None:
    """ADR-0168 §9 on the new shapes: a request the hub received and declined is
    distinguishable from a transport failure, and neither is presented as an answer."""

    class _Declining(FakeAssistantEngine):
        async def forget_conversation(self, conversation_id: Identifier) -> bool:
            msg = "no conversation of that name"
            raise UnknownConversationError(msg)

    async with _harness(_Declining()) as one:
        status, body = await one.whole("POST", "/conversation/forget", {"conversation_id": "c-1"})

        assert status == 422
        assert body["fault"] == "assistant-declined"


@pytest.mark.parametrize(
    "path",
    [
        "/learn",
        "/notifications",
        "/dismiss_notification",
        "/resume",
        "/pending_confirmations",
        "/connected_accounts",
        "/nonsense",
    ],
)
async def test_an_operation_this_gateway_does_not_serve_reaches_nothing(
    harness: Harness, path: str
) -> None:
    """ADR-0175 §6's third clause, which ADR-0177 §1 leaves standing and acts under.

    A request for one "is not an admitted assistant request the gateway declines to
    forward — it is a request the surface has no shape for, which is the same thing a
    request for ``/nonsense`` is" (ADR-0175 §12), so it lands in ADR-0168 §6's residual
    fourth class and the engine is not reached.

    **Two different reasons are asserted by one test and they are worth telling
    apart.** ``learn`` is admitted by *nothing*: ADR-0177 §1 leaves it out by name and
    §11 gives it a trigger, so a shape for it here would be the lane inventing an
    operation. The other five are in §1's enumeration of thirty and are **not served
    by this gateway yet** — the notification review five, ``resume`` and
    ``pending_confirmations`` (whose act §8 blocks until #1366 lands) and the
    connection five are later lanes'. Either way the answer is §6's fourth class,
    which is the property that makes an enumeration checkable: a path nothing serves
    behaves identically to a path nothing has heard of.
    """
    status, body = await harness.whole("POST", path, {})

    assert status == 404
    assert body == {"fault": "no-such-path"}
    assert harness.engine.calls == []


def test_the_surface_resolves_onto_what_it_serves_and_the_gateways_own_poll() -> None:
    """ADR-0177 §1's enumeration, read off the router.

    Eighteen of the thirty operations §1 admits are served here, and
    ``next_notification`` — the gateway's **own** poll — is none of them "because no
    browser request resolves to it: the gateway's own poll originates it under
    ADR-0175 §4, no browser request names it, and no browser argument reaches it"
    (§1's second clause, bound unchanged).

    Asserted as a set equality rather than a subset, which is the whole point of an
    enumeration: a lane that adds a route without a ratified decision fails here, and
    so does a lane that adds one this ADR admits *and* forgets it exists.
    """
    assert set(_ASSISTANT_PATHS.values()) == {
        "converse",
        "converse_streaming",
        "recent_conversations",
        "conversation",
        "forget_conversation",
        "grantable_sources",
        "grant",
        "revoke",
        "recent_grants",
        "standing_grants",
        "beliefs",
        "belief",
        "forget",
        "questions",
        "interrupted_questions",
        "answer",
        "forget_question",
        "observe",
        "delivery-stream",
    }


# --- what a peer that goes away at the wrong moment must not cost ------------


class _Stalling(FakeAssistantEngine):
    """An engine that never reaches its first chunk until a test lets it."""

    def __init__(self) -> None:
        """Start with nothing composed and nothing closed."""
        super().__init__()
        self.composing = asyncio.Event()
        self.closed = asyncio.Event()

    def converse_streaming(
        self,
        utterance: EncodableText,
        *,
        timeout: timedelta,
        conversation_id: Identifier | None = None,
    ) -> AsyncIterator[ReplyChunk | TurnOutcome]:
        """Compose forever, recording the close the caller owes."""
        self.calls.append(("converse_streaming", {"utterance": utterance}))

        async def stalled() -> AsyncIterator[ReplyChunk | TurnOutcome]:
            try:
                self.composing.set()
                await asyncio.Event().wait()
                yield ReplyChunk(text="never")  # pragma: no cover — the wait never ends
            finally:
                self.closed.set()

        return stalled()


class _GoneWriter:
    """A connection the peer closed before the stream's head could be written.

    The narrowest possible subject: ``_write_stream`` is the only place that decides
    what a failed *head* costs, and the failure it turns on is a ``drain`` that
    raises — which no real socket can be made to do on cue.
    """

    def __init__(self) -> None:
        """Start open, and record whether the gateway closed it."""
        self.closed = False
        self.written = b""

    def write(self, payload: bytes) -> None:
        """Take the bytes; the peer is gone but the transport does not say so yet."""
        self.written += payload

    async def drain(self) -> None:
        """Fail the way a reset connection fails."""
        msg = "peer went away"
        raise ConnectionResetError(msg)

    def close(self) -> None:
        """Record the close."""
        self.closed = True


class _ExpiringWriter:
    """A connection whose head write outlives the session that admitted the request.

    The window round 2 of this PR's review found: a ``drain`` may yield — a paused
    transport is enough — and a session's death is a scheduled callback, so between
    the head and the body the session can end. Firing the timers from inside the
    drain is that ordering made deterministic.
    """

    def __init__(self, one: Harness) -> None:
        """Start open, over a harness whose clock and timers a test drives."""
        self.one = one
        self.written = b""
        self.closed = False
        self.drains = 0

    def write(self, payload: bytes) -> None:
        """Take the bytes."""
        self.written += payload

    async def drain(self) -> None:
        """Let the admitting session die while the head is still going out.

        The death is scheduled on the loop rather than run inline, because that is
        where it comes from in a running gateway: ``gateway_session_idle_timeout``
        arrives as a ``call_later`` callback, outside any task. Running it inline
        would be a task ending its own stream, which is a shape the gateway does not
        produce and whose guard would make this case pass for the wrong reason.
        """
        self.drains += 1
        if self.drains == 1:
            self.one.clock.advance(timedelta(minutes=6))
            asyncio.get_running_loop().call_soon(self.one.timers.fire_all)
            await asyncio.sleep(0)
            await asyncio.sleep(0)

    def close(self) -> None:
        """Record the close."""
        self.closed = True


def _decide(one: Harness, method: str, path: str, payload: dict[str, Any]) -> Any:
    """Decide one streamed request, as the router would, and hand back the stream."""
    request = Request(
        method=method,
        path=path,
        headers=(("x-assistant-session", one.header_half),),
        body=json.dumps(payload).encode(),
    )
    handle = one.gateway._sessions.handle(one.header_half)
    assert handle is not None
    decided = (
        one.gateway._ask_streaming(request, handle)
        if path == "/ask/stream"
        else one.gateway._delivery_stream(handle)
    )
    assert not isinstance(decided, Response)
    return decided


async def _fail_the_head(one: Harness, method: str, path: str, payload: dict[str, Any]) -> bool:
    """Decide one streamed request, then lose the peer before its head lands."""
    return await one.gateway._write_stream(
        _GoneWriter(),  # type: ignore[arg-type] # a writer is what it writes
        _decide(one, method, path, payload),
        closing=False,
    )


async def test_a_turn_stream_whose_head_never_landed_gives_its_hub_slot_back() -> None:
    """§7 counts a stream's hub connection against ``gateway_max_hub_connections``,
    and a browser that hangs up between its request and the head is the one path on
    which the body that releases that slot never runs at all.

    At a ceiling of one the leak is immediate and total: the next turn is refused for
    a connection nobody holds. Asserted through the ceiling rather than through a
    counter, because the ceiling is what the owner would actually meet.
    """
    async with _harness(gateway_max_hub_connections=1) as one:
        assert (
            await _fail_the_head(one, "POST", "/ask/stream", {"utterance": "what is on"}) is False
        )

        status, _ = await one.whole("POST", "/ask", {"utterance": "what is on today"})

        assert status == 200


async def test_a_delivery_stream_whose_head_never_landed_leaves_no_poll_running() -> None:
    """§4: the gateway holds a poll "while and only while at least one delivery stream
    is open" — a rule an error path must not be able to break.

    A stream registered and then never written to is a reader that never existed, and
    a poll held for it would take an entry, mint a ``delivery_id`` and start a lease
    (ADR-0131 §2a) on nobody's behalf. The ceiling is again the observable: at one, a
    poll still running is a turn refused.
    """
    engine = _Delivering([None])
    async with _harness(engine, gateway_max_hub_connections=1) as one:
        assert await _fail_the_head(one, "GET", "/deliveries", {}) is False

        status, _ = await one.whole("POST", "/ask", {"utterance": "what is on today"})

        assert status == 200


async def test_a_session_ending_closes_an_answer_stream_still_waiting_to_compose() -> None:
    """§7: "A stream ends no later than the session that admitted it, and the gateway
    ends every stream a session held at the moment that session ends."

    Closing the socket does not reach an ``async for`` that is waiting on the engine,
    so a turn still composing when its session expired would hold both the iterator
    and the hub connection §7 counts — for however long the turn took. Ending the
    stream cancels the task driving it, which unwinds through ``closing_stream``
    (ADR-0173's own obligation, §3) and through the release the body owes.
    """
    engine = _Stalling()
    async with _harness(engine, gateway_session_idle_timeout=timedelta(minutes=5)) as one:
        reader, _, status = await one.send("POST", "/ask/stream", {"utterance": "what is on"})
        assert status == 200
        await asyncio.wait_for(engine.composing.wait(), timeout=5)

        one.clock.advance(timedelta(minutes=6))
        one.timers.fire_all()

        await asyncio.wait_for(engine.closed.wait(), timeout=5)
        assert await _read_all(reader) == []


async def test_a_session_that_dies_while_the_head_is_written_still_ends_the_stream() -> None:
    """§7: "A stream ends no later than the session that admitted it."

    The ordering that makes the clause reachable: the stream is registered before the
    first awaited write, so it cannot miss its own session's death. Registered one
    line later — after the head has drained — a drain that yields lets the session's
    scheduled death run first, find no stream against that handle, and leave the one
    that follows with nothing that will ever end it.

    Driven in its own task because ending a stream cancels the task driving it. The
    engine is never reached at all here — the death lands during the *head*, before
    the body starts — which is what makes the claim about registration rather than
    about the turn: the stream was found and ended on a handle it had already been
    associated with.
    """
    engine = _Stalling()
    async with _harness(engine, gateway_session_idle_timeout=timedelta(minutes=5)) as one:
        decided = _decide(one, "POST", "/ask/stream", {"utterance": "what is on"})
        writer = _ExpiringWriter(one)

        driving = asyncio.ensure_future(
            one.gateway._write_stream(
                writer,  # type: ignore[arg-type] # a writer is what it writes
                decided,
                closing=False,
            )
        )
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.wait_for(driving, timeout=5)

        assert driving.cancelled()
        assert writer.closed
        assert engine.calls == []
