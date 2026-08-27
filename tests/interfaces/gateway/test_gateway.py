"""The gateway end to end, over its own loopback listener (ADR-0168).

**Driven through a real socket rather than through the object's methods**, and
that is deliberate: half of what ADR-0168 §8 rules is about *connections* — which
survive a response and which do not, how many may be held, and what happens to
one that has carried nothing — and none of that is visible from a handler call.
Milestone 13's exit test is a browser round-tripping an `ask` and reading a
legible hub-down fault, so the tests that stand for it speak HTTP.

Marked ``integration`` because a loopback socket is what they open.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import socket
import struct
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import pytest
import structlog
from gateway_mint import bootstrap_value
from gateway_timing import Clock, Timers

from ai_assistant.core.config import Settings
from ai_assistant.core.errors import ConfigurationError, UnknownConversationError
from ai_assistant.core.types import (
    ActionPlan,
    CurrentContext,
    Disposition,
    ExecutionState,
    Goal,
    MemorySource,
    PlanStep,
    Provenance,
    StepOutcome,
    TimeOfDay,
    TurnOutcome,
    TurnResult,
)
from ai_assistant.interfaces.gateway.server import Disclosure, Gateway
from ai_assistant.testing import FakeAssistantEngine
from ai_assistant.wire.errors import HubUnavailableError

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from ai_assistant.core.types import EncodableText, Identifier

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("hermetic_assistant_env")]

#: The instant every scripted turn in this file is stamped with. Fixed rather than
#: read from a clock: nothing here turns on time, and a wall-clock reading would be
#: one more thing a failure could be about.
_AT = datetime(2026, 1, 2, 15, 0, tzinfo=UTC)

_BUNDLE = {
    "/": (b"<!doctype html><p>document", "text/html; charset=utf-8"),
    "/app.css": (b"body{}", "text/css; charset=utf-8"),
    "/app.js": (b"'use strict';", "text/javascript; charset=utf-8"),
}


class _Unreachable(FakeAssistantEngine):
    """An engine whose hub is not there (ADR-0168 §9)."""

    async def converse(
        self,
        utterance: EncodableText,
        *,
        timeout: timedelta,  # noqa: ASYNC109 — the Protocol's own signature
        conversation_id: Identifier | None = None,
    ) -> TurnOutcome:
        """Fail the way a closed door fails: a transport error, not an answer."""
        self.calls.append(("converse", {"utterance": utterance}))
        msg = "no hub is listening on that socket"
        raise HubUnavailableError(msg)


class _Declining(FakeAssistantEngine):
    """An engine that received the request and declined it."""

    async def converse(
        self,
        utterance: EncodableText,
        *,
        timeout: timedelta,  # noqa: ASYNC109 — the Protocol's own signature
        conversation_id: Identifier | None = None,
    ) -> TurnOutcome:
        """Refuse the way the hub refuses: an ``AssistantError`` it authored."""
        self.calls.append(("converse", {"utterance": utterance}))
        msg = "no conversation of that name"
        raise UnknownConversationError(msg)


class _Blocking(FakeAssistantEngine):
    """An engine that holds every turn open until a test releases it."""

    def __init__(self) -> None:
        """Start with nothing released and nothing in flight."""
        super().__init__()
        self.release = asyncio.Event()
        self.occupied = asyncio.Event()

    async def converse(
        self,
        utterance: EncodableText,
        *,
        timeout: timedelta,  # noqa: ASYNC109 — the Protocol's own signature
        conversation_id: Identifier | None = None,
    ) -> TurnOutcome:
        """Occupy a hub connection until released, so the ceiling can be reached."""
        self.occupied.set()
        await self.release.wait()
        return await super().converse(utterance, timeout=timeout, conversation_id=conversation_id)


@dataclass
class Answer:
    """One parsed response."""

    status: int
    headers: dict[str, list[str]]
    body: bytes
    closed: bool

    @property
    def payload(self) -> dict[str, Any]:
        """The body as JSON, or an empty mapping."""
        try:
            parsed = json.loads(self.body)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    def header(self, name: str) -> str | None:
        """The one value of a header, or ``None``."""
        found = self.headers.get(name, [])
        return found[0] if len(found) == 1 else None


@dataclass
class Harness:
    """A bound gateway, its port, and the engine behind it."""

    gateway: Gateway
    server: asyncio.Server
    settings: Settings
    engine: FakeAssistantEngine
    clock: Clock
    timers: Timers

    @property
    def authority(self) -> str:
        """The `Host` this gateway admits."""
        return f"127.0.0.1:{self.settings.gateway_port}"

    async def send(
        self,
        head: str,
        body: bytes = b"",
        *,
        connection: tuple[asyncio.StreamReader, asyncio.StreamWriter] | None = None,
    ) -> Answer:
        """Send one raw request and read the whole answer back.

        Args:
            head: The request line and headers, newline-separated, without the
                trailing blank line. ``{host}`` is filled in.
            body: The request body.
            connection: An open connection to reuse, or ``None`` to open one.

        Returns:
            The parsed response, including whether the gateway then closed.
        """
        opened = connection or await self.connect()
        reader, writer = opened
        framed = head.format(host=self.authority).replace("\n", "\r\n").encode()
        writer.write(framed + b"\r\n\r\n" + body)
        await writer.drain()
        return await _read_answer(reader)

    async def connect(self) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        """Open one connection to the gateway."""
        return await asyncio.open_connection("127.0.0.1", self.settings.gateway_port)


async def _read_answer(reader: asyncio.StreamReader) -> Answer:
    """Parse one HTTP response, then see whether the peer closed."""
    head = await reader.readuntil(b"\r\n\r\n")
    lines = head.decode().split("\r\n")
    status = int(lines[0].split(" ")[1])
    headers: dict[str, list[str]] = {}
    for line in lines[1:]:
        if not line:
            continue
        name, _, value = line.partition(":")
        headers.setdefault(name.lower(), []).append(value.strip())
    length = int(headers.get("content-length", ["0"])[0])
    body = await reader.readexactly(length)
    closed = headers.get("connection", [""])[0] == "close"
    if closed:
        # The header is a claim; the socket is the fact. A refusal that said
        # "close" and left the connection open would be ADR-0168 §8's rule
        # announced rather than obeyed.
        assert await reader.read(1) == b""
    return Answer(status=status, headers=headers, body=body, closed=closed)


def _free_port() -> int:
    """A port nothing is listening on, so two runs do not collide."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


@contextlib.asynccontextmanager
async def _harness(
    engine: FakeAssistantEngine | None = None, **overrides: Any
) -> AsyncIterator[Harness]:
    """Bind one gateway on a free port and tear it down afterwards."""
    settings = Settings(gateway_port=_free_port(), **overrides)
    clock, timers = Clock(), Timers()
    behind = engine or FakeAssistantEngine()
    gateway = Gateway(
        settings=settings,
        engine=behind,
        now=clock,
        defer=timers,
        bundle=_BUNDLE,
    )
    server = await gateway.start()
    try:
        yield Harness(
            gateway=gateway,
            server=server,
            settings=settings,
            engine=behind,
            clock=clock,
            timers=timers,
        )
    finally:
        gateway.close()
        server.close()
        with contextlib.suppress(Exception):
            await server.wait_closed()


@pytest.fixture
async def harness() -> AsyncIterator[Harness]:
    """A gateway on ADR-0168 §8's own figures."""
    async with _harness() as one:
        yield one


async def _start_session(harness: Harness) -> tuple[str, str]:
    """Run the bootstrap exchange and return the two halves a browser then holds."""
    value = bootstrap_value(harness.gateway)
    body = json.dumps({"bootstrap_value": value}).encode()
    answer = await harness.send(
        f"POST /session HTTP/1.1\nHost: {{host}}\nContent-Length: {len(body)}\n"
        f"Content-Type: application/json",
        body,
    )
    assert answer.status == 200, answer.body
    cookie = answer.header("set-cookie")
    assert cookie is not None
    return cookie.split(";")[0].partition("=")[2], answer.payload["header_half"]


async def _exchange(harness: Harness, value: str) -> Answer:
    """Present one bootstrap value at the exchange and read the answer."""
    body = json.dumps({"bootstrap_value": value}).encode()
    return await harness.send(
        f"POST /session HTTP/1.1\nHost: {{host}}\nContent-Length: {len(body)}", body
    )


def _ask(
    harness: Harness,
    *,
    header_half: str | None,
    cookie_half: str | None,
    conversation: str | None = None,
) -> tuple[str, bytes]:
    """Frame one `/ask`, with whichever halves the case presents."""
    asked: dict[str, str] = {"utterance": "what is on today"}
    if conversation is not None:
        asked["conversation_id"] = conversation
    body = json.dumps(asked).encode()
    lines = [
        "POST /ask HTTP/1.1",
        "Host: {host}",
        f"Origin: http://{harness.authority}",
        "Content-Type: application/json",
        f"Content-Length: {len(body)}",
    ]
    if header_half is not None:
        lines.append(f"X-Assistant-Session: {header_half}")
    if cookie_half is not None:
        lines.append(f"Cookie: assistant_session={cookie_half}")
    return "\n".join(lines), body


# --- ADR-0168 §3: the two things served without a session, and nothing else ---


@pytest.mark.parametrize("path", ["/", "/app.css", "/app.js"])
async def test_the_front_ends_own_assets_are_served_without_a_session(
    harness: Harness, path: str
) -> None:
    """One of §3's two exceptions, "and they are the whole of the exception".

    "A browser with no session cannot fetch the page from which it would exchange
    the bootstrap value", so a rule forbidding both makes §5 unreachable.
    """
    answer = await harness.send(f"GET {path} HTTP/1.1\nHost: {{host}}")

    assert answer.status == 200
    assert answer.body == _BUNDLE[path][0]
    assert harness.engine.calls == []


async def test_an_unadmitted_assistant_request_is_refused_and_never_reaches_the_engine(
    harness: Harness,
) -> None:
    """ADR-0168 §1's biconditional, in the direction that matters most.

    An `ask` "plainly asks the assistant for something and §3 plainly refuses it",
    which is the class an earlier one-directional draft of the routing clause sent
    to the engine anyway.
    """
    head, body = _ask(harness, header_half=None, cookie_half=None)

    answer = await harness.send(head, body)

    assert answer.status == 401
    assert answer.payload == {"fault": "no-live-session"}
    assert harness.engine.calls == []


async def test_a_refusal_carries_no_fact_about_the_hub(harness: Harness) -> None:
    """§3: a refusal carries "no assistant content, no fact about the hub's state,
    and no fact about whether the hub is reachable"."""
    head, body = _ask(harness, header_half="not-a-session", cookie_half=None)

    answer = await harness.send(head, body)

    assert set(answer.payload) == {"fault"}


# --- ADR-0168 §5 and §6: the exchange, and the two values it discloses ---


async def test_the_exchange_mints_a_session_and_discloses_both_halves(
    harness: Harness,
) -> None:
    """ "It returns nothing but the two session values §6 requires"."""
    value = bootstrap_value(harness.gateway)
    body = json.dumps({"bootstrap_value": value}).encode()

    answer = await harness.send(
        f"POST /session HTTP/1.1\nHost: {{host}}\nContent-Length: {len(body)}", body
    )

    assert answer.status == 200
    assert set(answer.payload) == {"header_half"}
    cookie = answer.header("set-cookie")
    assert cookie is not None
    assert answer.payload["header_half"] not in cookie


async def test_the_exchange_response_is_the_only_one_that_sets_a_cookie(
    harness: Harness,
) -> None:
    """§6's attributes, read off the one response that carries them.

    `HttpOnly` so no script reads it, `SameSite=Strict` so no other site causes it
    to be sent, `Path=/` and no `Domain` so a second cookie of this name "is
    detectable as the anomaly it is rather than silently preferred", and no
    persistent expiry — none of which the guarantee rests on, because "a session's
    lifetime is decided by the gateway alone".
    """
    value = bootstrap_value(harness.gateway)
    body = json.dumps({"bootstrap_value": value}).encode()

    answer = await harness.send(
        f"POST /session HTTP/1.1\nHost: {{host}}\nContent-Length: {len(body)}", body
    )

    cookie = answer.header("set-cookie")
    assert cookie is not None
    assert "HttpOnly" in cookie
    assert "SameSite=Strict" in cookie
    assert "Path=/" in cookie
    assert "Domain" not in cookie
    assert "Max-Age" not in cookie
    assert "Expires" not in cookie


async def test_a_failed_exchange_discloses_only_that_it_failed(harness: Harness) -> None:
    """§5: "never whether the value was well-formed, whether one is still
    outstanding, or whether a session already exists"."""
    bootstrap_value(harness.gateway)
    body = json.dumps({"bootstrap_value": "wrong"}).encode()

    answer = await harness.send(
        f"POST /session HTTP/1.1\nHost: {{host}}\nContent-Length: {len(body)}", body
    )
    absent = await harness.send("POST /session HTTP/1.1\nHost: {host}\nContent-Length: 0")

    assert answer.status == absent.status == 400
    assert answer.payload == absent.payload == {"fault": "bootstrap-exchange-failed"}


async def test_the_bootstrap_value_is_exchangeable_exactly_once(harness: Harness) -> None:
    """§5's single use, which is ADR-0182 §2's first cessation event.

    ADR-0182 §9 supersedes only §5's *second* sentence — "mints no further session
    until its process is restarted" — and states that "the single-use half is
    untouched and applied", which is what this holds.
    """
    value = bootstrap_value(harness.gateway)
    body = json.dumps({"bootstrap_value": value}).encode()
    head = f"POST /session HTTP/1.1\nHost: {{host}}\nContent-Length: {len(body)}"
    assert (await harness.send(head, body)).status == 200

    second = await harness.send(head, body)

    assert second.status == 400
    assert second.payload == {"fault": "bootstrap-exchange-failed"}


async def test_a_fresh_mint_replaces_the_outstanding_value_rather_than_being_refused(
    harness: Harness,
) -> None:
    """ADR-0182 §2's third cessation event, at the door the browser uses.

    "Replacement rather than refusal, because the owner's mental model is the
    screen in front of them": a gateway that refused while a value stood "would
    make the act fail in the case an owner most often reaches it in — they minted,
    mistyped, and want another", so "the value on the screen is always the value
    that works".
    """
    first = bootstrap_value(harness.gateway)
    second = bootstrap_value(harness.gateway)

    stale = json.dumps({"bootstrap_value": first}).encode()
    fresh = json.dumps({"bootstrap_value": second}).encode()
    refused = await harness.send(
        f"POST /session HTTP/1.1\nHost: {{host}}\nContent-Length: {len(stale)}", stale
    )
    admitted = await harness.send(
        f"POST /session HTTP/1.1\nHost: {{host}}\nContent-Length: {len(fresh)}", fresh
    )

    assert first != second
    assert refused.status == 400
    assert refused.payload == {"fault": "bootstrap-exchange-failed"}
    assert admitted.status == 200


async def test_the_exchange_is_refused_at_the_ceiling_and_consumes_the_value_anyway() -> None:
    """ADR-0182 §4: the one door the ceiling is enforced at, reachable at last.

    "The **bootstrap exchange is the only place the ceiling is enforced**, because
    it is the only act that raises the live session count. An exchange that would
    take the count past ``gateway_max_sessions`` is **refused**, and no session is
    minted." And the value goes with it: "the value the exchange carried is consumed
    exactly as a spent value is, so a refused exchange is not a value the caller may
    present again", because "the alternative leaves a live ticket outstanding after
    a failure the caller can drive, which turns the ceiling into a way to keep a
    value alive".
    """
    async with _harness(gateway_max_sessions=1) as one:
        first = bootstrap_value(one.gateway)
        assert (await _exchange(one, first)).status == 200
        second = bootstrap_value(one.gateway)

        refused = await _exchange(one, second)
        again = await _exchange(one, second)

    assert refused.status == 400
    assert refused.payload == {"fault": "bootstrap-exchange-failed"}
    assert again.status == 400
    assert again.payload == {"fault": "bootstrap-exchange-failed"}


async def test_a_ceiling_refusal_is_recorded_as_the_ceiling_and_answered_as_a_failure() -> None:
    """ADR-0182 §4's split: the owner is told everything and the browser nothing.

    "The refusal **is** recorded, and the record names the ceiling as the condition
    it was refused on… That record is the owner's channel for the fact the browser
    is not told." Telling the browser instead "would hand any local process a probe
    for how many browsers the owner has admitted".
    """
    async with _harness(gateway_max_sessions=1) as one:
        assert (await _exchange(one, bootstrap_value(one.gateway))).status == 200
        with structlog.testing.capture_logs() as records:
            refused = await _exchange(one, bootstrap_value(one.gateway))
            one.timers.fire_all()

    assert refused.payload == {"fault": "bootstrap-exchange-failed"}
    conditions = [record.get("condition") for record in records]
    assert "session-ceiling" in conditions


async def test_every_way_a_value_can_have_ceased_is_the_same_refusal(harness: Harness) -> None:
    """ADR-0182 §2: a failed exchange "never [discloses] which of the four events
    above ended the value it carried".

    ADR-0168 §5's rule governs all four, so the four cessation events, an unknown
    value and an absent one are one answer with one body.
    """
    spent = bootstrap_value(harness.gateway)
    assert (await _exchange(harness, spent)).status == 200

    expired = bootstrap_value(harness.gateway)
    harness.timers.fire_all()
    replaced = bootstrap_value(harness.gateway)
    bootstrap_value(harness.gateway)
    ended = bootstrap_value(harness.gateway)
    harness.gateway.close()

    answers = [await _exchange(harness, one) for one in (spent, expired, replaced, ended)]
    answers.append(await _exchange(harness, "never-minted"))
    answers.append(await harness.send("POST /session HTTP/1.1\nHost: {host}\nContent-Length: 0"))

    assert {(one.status, one.body) for one in answers} == {
        (400, answers[0].body),
    }
    assert answers[0].payload == {"fault": "bootstrap-exchange-failed"}


async def test_an_exchange_presenting_a_candidate_no_disclosure_promoted_is_refused(
    harness: Harness,
) -> None:
    """ADR-0182 §1: such a value "is **not minted**", and §2: it "admits nothing".

    The interval in which a candidate sits in memory beside a still-outstanding
    value is pinned where it exists, on ``BootstrapMint`` itself
    (``test_sessions.py``); what is pinned here is the door — a value the gateway
    generated and never disclosed buys no session, and the value that was disclosed
    still does.
    """
    standing = bootstrap_value(harness.gateway)
    captured: list[str] = []

    def capture_then_fail(one: Disclosure) -> None:
        captured.append(one.value)
        msg = "standard output is not writable"
        raise ConfigurationError(msg)

    with pytest.raises(ConfigurationError):
        harness.gateway.mint_bootstrap(capture_then_fail, act=None)

    refused = await _exchange(harness, captured[0])
    admitted = await _exchange(harness, standing)

    assert refused.status == 400
    assert refused.payload == {"fault": "bootstrap-exchange-failed"}
    assert admitted.status == 200


async def test_a_disclosed_value_ceases_when_its_ttl_elapses(harness: Harness) -> None:
    """ADR-0182 §2's second cessation event, at the door.

    Driven by firing what the gateway deferred rather than by moving the clock,
    because §3 puts this bound on a monotonic source and §10 asks it pinned "by
    driving the injected deferral seam rather than by moving a clock".
    """
    value = bootstrap_value(harness.gateway)

    harness.timers.fire_all()

    refused = await _exchange(harness, value)
    assert refused.status == 400
    assert refused.payload == {"fault": "bootstrap-exchange-failed"}


# --- The exit test: an `ask` round-trips from a browser (#1230) ---


async def test_an_admitted_ask_round_trips_and_renders_what_the_hub_returned(
    harness: Harness,
) -> None:
    """Milestone 13's exit test, in the gateway's half of it.

    A browser holding both halves asks, the request reaches the promoted engine
    surface exactly once, and what comes back is the turn — the answer, the plan,
    the step, and the conversation the browser keeps to continue.

    The member set is asserted whole rather than by presence, because this
    enumeration is a decision (``_outcome_view``) and not a projection: a member
    that stops being carried is as much a defect as one that starts being carried
    unreviewed. Issue #1337 is that failure in the first direction — the answer was
    composed, returned over the wire, and dropped here.
    """
    cookie_half, header_half = await _start_session(harness)
    head, body = _ask(harness, header_half=header_half, cookie_half=cookie_half)

    answer = await harness.send(head, body)

    assert answer.status == 200
    outcome = answer.payload["outcome"]
    assert outcome["conversation_id"]
    assert set(outcome) == {
        "conversation_id",
        "capture_degraded",
        "memory_degraded",
        "reply",
        "reply_degraded",
        "rationale",
        "steps",
        "step",
    }
    assert [call[0] for call in harness.engine.calls] == ["converse"]


async def test_a_named_conversation_is_relayed_to_the_engine_unchanged(
    harness: Harness,
) -> None:
    """The gateway relays what the browser named and re-derives nothing.

    A conversation is the hub's (ADR-0074 §2); the id it hands back is "what a
    client keeps and presents to continue", and the gateway is the second adapter
    to carry that — the CLI already does it with ``--conversation``. Passing an id
    the assistant does not know is the engine's refusal to author, not this
    adapter's to invent.
    """
    cookie_half, header_half = await _start_session(harness)
    first = await harness.send(*_ask(harness, header_half=header_half, cookie_half=cookie_half))
    named = first.payload["outcome"]["conversation_id"]

    await harness.send(
        *_ask(harness, header_half=header_half, cookie_half=cookie_half, conversation=named)
    )

    assert harness.engine.calls[-1][1]["conversation_id"] == named


async def test_an_admitted_request_that_asks_the_assistant_for_nothing_never_reaches_it(
    harness: Harness,
) -> None:
    """The other half of the biconditional: admitted is necessary, not sufficient."""
    cookie_half, header_half = await _start_session(harness)

    answer = await harness.send(
        f"GET /somewhere-else HTTP/1.1\nHost: {{host}}\n"
        f"X-Assistant-Session: {header_half}\nCookie: assistant_session={cookie_half}"
    )

    assert answer.status == 404
    assert harness.engine.calls == []


async def test_a_replaced_cookie_is_reported_as_its_own_condition(harness: Harness) -> None:
    """ADR-0168 §6's distinct fault, over the wire.

    "What the owner reads is that something replaced their cookie rather than that
    their session mysteriously ended" — so the status is not 401's.
    """
    _, header_half = await _start_session(harness)
    head, body = _ask(harness, header_half=header_half, cookie_half="a-replacement")

    answer = await harness.send(head, body)

    assert answer.status == 409
    assert answer.payload == {"fault": "cookie-half-mismatch"}


# --- ADR-0170 §6: the answer is carried beside the step account (#1337) ---


_RATIONALE = "one step, and the account of what became of it is the guarantee"


def _turn_that_ran() -> TurnResult:
    """One turn whose plan has a step, so there is an account to survive beside.

    The fake's own turn plans nothing, and a case about the answer arriving *in
    addition to* the account needs an account with something in it — a rationale
    and a named step, which are what the page lists.
    """
    goal = Goal(
        id="g-1",
        statement="send the note",
        provenance=Provenance(source=MemorySource.USER_ASSERTED, confidence=1.0, last_updated=_AT),
        created_at=_AT,
    )
    return TurnResult(
        goal=goal,
        context=CurrentContext(
            now=_AT, time_of_day=TimeOfDay.AFTERNOON, is_weekend=False, within_working_hours=True
        ),
        memories=(),
        plan=ActionPlan(
            id="p-1",
            goal_id=goal.id,
            steps=(PlanStep(id="s-1", intent="send the note", capability="send_email"),),
            created_at=_AT,
            rationale=_RATIONALE,
        ),
    )


async def test_the_composed_answer_reaches_the_browser_beside_the_step_account(
    harness: Harness,
) -> None:
    """ADR-0170 §6: an adapter renders the answer "**in addition to** the step
    account it renders today, never instead of it".

    Issue #1337 is the first half failing: ``_outcome_view`` enumerated the
    pre-ADR-0170 members, so `/ask` answered 200 with the whole account and no
    answer anywhere in it. The hub had composed one — the same ask through the CLI
    rendered it from the same store — and the browser was shown the plan and the
    disposition and never what the assistant said.

    Both halves are asserted, because a fix that carried the answer *instead of*
    the account would satisfy the issue and violate the clause: the deterministic
    account is what this system guarantees about what it did, and the answer is
    not.
    """
    harness.engine.turn_outcome = TurnOutcome(
        turn=_turn_that_ran(),
        conversation_id="c-1",
        reply="I have sent the note.",
    )
    cookie_half, header_half = await _start_session(harness)

    answer = await harness.send(*_ask(harness, header_half=header_half, cookie_half=cookie_half))

    outcome = answer.payload["outcome"]
    assert outcome["reply"] == "I have sent the note."
    assert outcome["reply_degraded"] is False
    assert outcome["rationale"] == _RATIONALE
    assert outcome["steps"] == [{"intent": "send the note", "capability": "send_email"}]
    assert outcome["conversation_id"] == "c-1"


async def test_a_turn_whose_answer_could_not_be_composed_says_so_and_keeps_its_account(
    harness: Harness,
) -> None:
    """ADR-0170 §6: "The step account is rendered on a degraded turn too".

    A `reply_degraded` outcome is "the account it carries plus a statement that no
    answer could be composed — never as a silent turn". The flag is carried rather
    than left to be inferred from the ``None``, because §4 gives ``reply`` three
    ``None`` shapes and this is the only one where an answer was owed: without it
    the page cannot tell "no answer was owed" from "an answer was owed and could
    not be composed", which is the whole reason the member exists.
    """
    harness.engine.turn_outcome = TurnOutcome(
        turn=_turn_that_ran(), conversation_id="c-1", reply_degraded=True
    )
    cookie_half, header_half = await _start_session(harness)

    answer = await harness.send(*_ask(harness, header_half=header_half, cookie_half=cookie_half))

    outcome = answer.payload["outcome"]
    assert outcome["reply"] is None
    assert outcome["reply_degraded"] is True
    assert outcome["rationale"] == _RATIONALE
    assert outcome["steps"] == [{"intent": "send the note", "capability": "send_email"}]


async def test_a_turn_that_owed_no_answer_carries_none_and_the_account_alone(
    harness: Harness,
) -> None:
    """ADR-0170 §4's first ``None`` shape, reaching the page as a ``None``.

    A parked step owes no answer: what the user must answer is the confirmation,
    and prose beside it competes with the question. So the view carries ``null``
    and an unset flag, and neither this adapter nor the page it feeds invents text
    to fill the gap — a "no answer was available" line here would be exactly the
    silent-``None``-versus-degraded confusion the flag exists to prevent, written
    the other way round.
    """
    harness.engine.turn_outcome = TurnOutcome(
        turn=_turn_that_ran(),
        conversation_id="c-1",
        step=StepOutcome(
            disposition=Disposition.AWAITING_CONFIRMATION,
            state=ExecutionState(id="e-1", plan_id="p-1", steps=(), updated_at=_AT),
            step_id="s-1",
            confirmation=harness.engine.park("h-1"),
        ),
    )
    cookie_half, header_half = await _start_session(harness)

    answer = await harness.send(*_ask(harness, header_half=header_half, cookie_half=cookie_half))

    outcome = answer.payload["outcome"]
    assert outcome["reply"] is None
    assert outcome["reply_degraded"] is False
    # The park crosses as the confirmation itself rather than as a flag (#1404), and
    # `test_gateway_confirmations.py` is where its content is checked. What this case
    # is about is the *answer*: a parked turn owes none, and the confirmation being
    # present is what makes the `None` above the right shape rather than a gap.
    assert outcome["step"]["confirmation"]["tool_id"] == "t-1"
    assert outcome["steps"] == [{"intent": "send the note", "capability": "send_email"}]


# The one case in this file that does not speak HTTP, because what it guards is not
# a response: it is the enumeration behind every response above.
def test_a_new_member_of_a_turn_outcome_cannot_reach_the_page_unnoticed() -> None:
    """The guard #1337 did not have.

    ``_outcome_view`` enumerates by design — the page renders what it returns, so
    what may appear there is decided in this repository rather than by whatever a
    future ``TurnOutcome`` happens to carry. The cost of that design is precisely
    what happened: ADR-0170 added two members and gave the CLI a renderer for them,
    this adapter's enumeration went on being correct by its own tests, and the
    answer was dropped one layer short of the person who asked for it. Both of the
    reviewing lenses on the PR that missed it approved.

    So the roster is pinned here instead of the enumeration being replaced by a
    dump. A member added to ``TurnOutcome`` fails this test, and whoever adds it
    decides — in this file, beside the cases above — whether the page sees it.
    Deciding "no" is a passing answer; not deciding at all is what this catches.

    **``routed`` is ADR-0197 §8's member, and the decision taken here is "not in this
    change".** The lane that added it landed the routing stage, its two contracts, the
    store and the engine wiring; ADR-0197 §12's last Normative makes §10's CLI and
    gateway renderings a **consumer group** and a separate lane, "not a second
    decision". So this adapter's ``_outcome_view`` is deliberately unchanged and the
    page does not see the routed account yet.

    That is a decision with a cost, and ADR-0197's own Consequences state it: "a client
    that ignores ``routed`` renders a turn that did something as a turn that did
    nothing". It is bounded rather than open — the consumer lane is briefed against
    §10, which is normative that an adapter renders the routed account **in addition
    to** any composed reply and never instead of it — and it is recorded here rather
    than left to be discovered, which is the whole of what this guard asks for.
    """
    assert set(TurnOutcome.model_fields) == {
        "turn",
        "step",
        "conversation_id",
        "capture_degraded",
        "reply",
        "reply_degraded",
        "routed",
    }


# --- ADR-0168 §7: the two checks that run before the session is read ---


async def test_a_host_the_gateway_did_not_bind_is_refused(harness: Harness) -> None:
    """The `Host` check "is what closes DNS rebinding, which is the specific attack
    a loopback listener attracts"."""
    answer = await harness.send("GET / HTTP/1.1\nHost: rebound.example")

    assert answer.status == 421
    assert answer.payload == {"fault": "host-not-bound"}


async def test_a_foreign_origin_is_refused_even_on_an_asset(harness: Harness) -> None:
    """§7 refuses "any request or connection upgrade carrying an `Origin` that is
    not its own", and it runs before §3's exceptions are served."""
    answer = await harness.send("GET / HTTP/1.1\nHost: {host}\nOrigin: http://127.0.0.1:9000")

    assert answer.status == 403
    assert answer.payload == {"fault": "origin-not-own"}


async def test_the_door_checks_run_before_the_session_is_consulted(
    harness: Harness,
) -> None:
    """ "A refusal that depends on whether a session exists is a refusal that
    discloses whether one exists" — so a bad `Host` beside a good session is
    refused on the `Host`."""
    cookie_half, header_half = await _start_session(harness)
    head, body = _ask(harness, header_half=header_half, cookie_half=cookie_half)

    answer = await harness.send(head.replace("Host: {host}", "Host: rebound.example"), body)

    assert answer.payload == {"fault": "host-not-bound"}


async def test_no_cross_origin_headers_are_sent_and_no_preflight_is_honoured(
    harness: Harness,
) -> None:
    """§7's second clause, in both halves."""
    answer = await harness.send("GET / HTTP/1.1\nHost: {host}")
    preflight = await harness.send("OPTIONS /ask HTTP/1.1\nHost: {host}")

    assert not [name for name in answer.headers if name.startswith("access-control")]
    assert preflight.status == 400
    assert not [name for name in preflight.headers if name.startswith("access-control")]


async def test_every_response_carries_the_content_security_policy(harness: Harness) -> None:
    """§6: "**every** response", refusals included."""
    served = await harness.send("GET / HTTP/1.1\nHost: {host}")
    refused = await harness.send("GET / HTTP/1.1\nHost: elsewhere")

    for answer in (served, refused):
        policy = answer.header("content-security-policy")
        assert policy is not None
        assert "default-src 'none'" in policy
        assert "'unsafe-inline'" not in policy
        assert "script-src 'self'" in policy


# --- ADR-0168 §9: hub-down is a legible fault, and never an answer ---


async def test_the_hub_being_unreachable_is_a_transport_fault_and_closes_nothing() -> None:
    """§9: "reports that to the browser as a transport failure, distinguishable
    from a request the hub received and declined… and never presents a transport
    failure as an answer", and §8: it "is not a refusal and closes nothing"."""
    async with _harness(_Unreachable()) as harness:
        cookie_half, header_half = await _start_session(harness)
        head, body = _ask(harness, header_half=header_half, cookie_half=cookie_half)

        answer = await harness.send(head, body)

        assert answer.status == 502
        assert answer.payload["fault"] == "hub-unreachable"
        assert "outcome" not in answer.payload
        assert not answer.closed


async def test_a_request_the_hub_declined_is_a_different_fault() -> None:
    """The distinction §9 requires survives to the browser rather than being
    flattened into one message."""
    async with _harness(_Declining()) as harness:
        cookie_half, header_half = await _start_session(harness)
        head, body = _ask(harness, header_half=header_half, cookie_half=cookie_half)

        answer = await harness.send(head, body)

        assert answer.status == 422
        assert answer.payload["fault"] == "assistant-declined"


async def test_the_gateway_serves_its_listener_with_no_hub_at_all() -> None:
    """§9's second clause: "so that a browser reaching a running gateway learns
    that the hub is down rather than that nothing is there". Nothing was probed,
    so the page and the exchange are both available."""
    async with _harness(_Unreachable()) as harness:
        assert (await harness.send("GET / HTTP/1.1\nHost: {host}")).status == 200
        assert await _start_session(harness)


# --- ADR-0168 §8: the connections, the deadline and the ceilings ---


async def test_a_refusal_closes_the_connection(harness: Harness) -> None:
    """§8: "The gateway **closes** a connection once it has sent a refusal on it".

    "Closing has neither problem — the ceiling stays an invariant instead of a
    check performed at one moment", and a peer that spends a slot on a refusal
    "has bought one request rather than a foothold".
    """
    answer = await harness.send("GET /nothing HTTP/1.1\nHost: {host}")

    assert answer.status == 401
    assert answer.closed


async def test_an_unadmitted_connection_carries_at_most_one_request(
    harness: Harness,
) -> None:
    """§8: "the gateway closes it once that request's response is complete".

    Serving one of §3's two pre-session exceptions "does not admit it".
    """
    answer = await harness.send("GET / HTTP/1.1\nHost: {host}")

    assert answer.status == 200
    assert answer.closed


async def test_an_admitted_connection_may_carry_further_requests(harness: Harness) -> None:
    """§8: "An admitted connection may carry further requests"."""
    cookie_half, header_half = await _start_session(harness)
    head, body = _ask(harness, header_half=header_half, cookie_half=cookie_half)
    opened = await harness.connect()

    first = await harness.send(head, body, connection=opened)
    second = await harness.send(head, body, connection=opened)

    assert first.status == second.status == 200
    assert not first.closed
    opened[1].close()


async def test_a_request_past_the_size_bound_is_refused_naming_the_limit() -> None:
    """§8: "The refusal names the limit and is applied before any part of the
    request is forwarded"."""
    async with _harness(gateway_max_request_bytes=200) as harness:
        body = b"x" * 500

        answer = await harness.send(
            f"POST /ask HTTP/1.1\nHost: {{host}}\nContent-Length: {len(body)}", body
        )

        assert answer.status == 413
        assert answer.payload == {
            "fault": "request-too-large",
            "limit": "gateway_max_request_bytes",
        }
        assert harness.engine.calls == []


async def test_a_hub_connection_beyond_the_ceiling_is_refused_and_never_queued() -> None:
    """§8: "A browser request that would need one beyond that is **refused**, and
    the refusal names the limit. The gateway does not queue such a request and
    does not open a further connection."

    "It refuses rather than queues, and an earlier draft's 'queues or refuses' was
    wrong twice over" — underdetermined, and unbounded in the direction that
    matters.
    """
    engine = _Blocking()
    async with _harness(engine, gateway_max_hub_connections=1) as harness:
        cookie_half, header_half = await _start_session(harness)
        head, body = _ask(harness, header_half=header_half, cookie_half=cookie_half)
        held = asyncio.create_task(harness.send(head, body))
        await asyncio.wait_for(engine.occupied.wait(), timeout=5)

        refused = await harness.send(head, body)
        engine.release.set()
        assert (await held).status == 200

        assert refused.status == 503
        assert refused.payload == {
            "fault": "hub-connection-ceiling",
            "limit": "gateway_max_hub_connections",
        }


async def test_the_pending_ceiling_refuses_a_further_connection_rather_than_queueing() -> None:
    """§8: "while that many exist it refuses to accept a further connection rather
    than queueing it".

    The tighter budget "keys on admission rather than on activity", because
    admission is the property a peer cannot fake.
    """
    async with _harness(gateway_max_pending_connections=1) as harness:
        first_reader, first_writer = await harness.connect()
        # The handler registers the connection on the loop's next turn, and the
        # ceiling is about connections the gateway is *holding* — so the second
        # dial has to come after that, not merely after the TCP handshake.
        await asyncio.sleep(0.05)

        second_reader, second_writer = await harness.connect()

        assert await second_reader.read(1) == b""
        first_writer.close()
        second_writer.close()
        assert first_reader is not None


async def test_an_unadmitted_connection_that_sends_nothing_is_closed_on_the_deadline() -> None:
    """§8: closed "``gateway_read_timeout`` after it was accepted, whether or not a
    complete request has arrived by then".

    That is the state ADR-0084 §3 calls "the cheapest state for a misbehaving peer
    to accumulate", and the deadline is what stops it being free.
    """
    async with _harness(gateway_read_timeout=timedelta(milliseconds=50)) as harness:
        reader, writer = await harness.connect()
        writer.write(b"GET / HTTP/1.1\r\n")
        await writer.drain()

        assert await asyncio.wait_for(reader.read(1), timeout=5) == b""
        writer.close()


# --- The remote door under a peer that is not speaking HTTP (#1369, #1370) ---

#: The opening of a TLS ClientHello — the ~1.5 KB the milestone-14 phone QA saw
#: arrive and sit (#1373). A browser sends it when the address it was given says
#: ``https://``, and nothing in it is ever going to be a blank line.
_CLIENT_HELLO = b"\x16\x03\x01\x02\x00\x01" + b"\x00" * 1400


async def test_bytes_that_cannot_begin_a_request_are_refused_far_inside_the_deadline(
    harness: Harness,
) -> None:
    """§8 closes an unadmitted connection "in any case ``gateway_read_timeout``
    after it was accepted" — a maximum, and this door was treating it as the only
    moment it had. So a browser given ``https://`` by hand got a white screen for
    thirty seconds, no response and no fault, and retried (#1369).

    The deadline here is the shipped figure and the bound asserted is a second, so
    what the test pins is promptness rather than merely eventual closure.
    """
    assert harness.settings.gateway_read_timeout >= timedelta(seconds=5)
    reader, writer = await harness.connect()
    writer.write(_CLIENT_HELLO)
    await writer.drain()

    answer = await asyncio.wait_for(_read_answer(reader), timeout=1)

    assert answer.status == 400
    assert answer.payload == {"fault": "malformed-request"}
    assert answer.closed
    writer.close()


async def test_a_legitimate_request_is_not_hurried_by_that_refusal(harness: Harness) -> None:
    """The refusal reads the byte it already has and waits for nothing.

    A peer that opens a connection and sends its request a moment later is the
    ordinary case, not the refused one — the first byte is judged when it arrives,
    on the deadline the connection already had.
    """
    reader, writer = await harness.connect()
    await asyncio.sleep(0.05)
    writer.write(b"GET /app.js HTTP/1.1\r\nHost: " + harness.authority.encode() + b"\r\n\r\n")
    await writer.drain()

    answer = await asyncio.wait_for(_read_answer(reader), timeout=1)

    assert answer.status == 200
    assert answer.body == _BUNDLE["/app.js"][0]
    writer.close()


async def test_a_peer_that_resets_mid_request_raises_nothing_out_of_the_handler() -> None:
    """Issue #1370: once per connection the phone reset, the gateway's stderr
    carried ``Unhandled exception in client_connected_cb`` and a traceback an
    operator reads as a fault.

    **The traceback named ``_close``, and ``_close`` was never the escape.**
    `connection_lost` hands the *same* exception object to the reader and to the
    close waiter, so a reset noticed by the read raises out of `_next`, and raises
    again inside `_close` — where it is suppressed, but only after that frame has
    been prepended to the traceback the first raise still carries. What answers it
    is the read treating a peer that went away as the ordinary end of a connection,
    which is the reading `_write_stream` already takes one response shape over.

    Driven on a raw socket with a zero linger, because a reset is what has to
    arrive: an orderly close is an end of stream, which this door already handled.
    """
    loop = asyncio.get_running_loop()
    unhandled: list[dict[str, Any]] = []
    loop.set_exception_handler(lambda _loop, context: unhandled.append(context))
    try:
        async with _harness() as harness:
            peer = socket.create_connection(("127.0.0.1", harness.settings.gateway_port))
            peer.sendall(b"GET / HTTP/1.1\r\n")
            await asyncio.sleep(0.05)
            peer.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
            peer.close()
            await asyncio.sleep(0.2)
            # A round trip after the reset, so the loop has certainly run the
            # handler task to completion and its done callback with it.
            assert (await harness.send("GET /app.js HTTP/1.1\nHost: {host}")).status == 200
    finally:
        loop.set_exception_handler(None)

    assert unhandled == [], unhandled


# --- What the browser is handed, and what it is not ---


async def test_the_view_keeps_the_gates_verdict_apart_from_the_steps_outcome(
    harness: Harness,
) -> None:
    """Issue #531's rule, at the second adapter.

    "The disposition is the gate's verdict; the named step's ``status`` and
    ``failure`` are the outcome", and a renderer written as "not failed means
    done" reproduces #531 one status over. A turn with no step says so with
    ``None`` rather than with a success.
    """
    cookie_half, header_half = await _start_session(harness)
    head, body = _ask(harness, header_half=header_half, cookie_half=cookie_half)

    answer = await harness.send(head, body)

    assert answer.payload["outcome"]["step"] is None


async def test_no_session_value_appears_in_any_response_but_the_exchanges_own(
    harness: Harness,
) -> None:
    """§6: "Neither half is placed in any response body except the bootstrap
    exchange's own reply"."""
    cookie_half, header_half = await _start_session(harness)
    head, body = _ask(harness, header_half=header_half, cookie_half=cookie_half)

    answer = await harness.send(head, body)

    assert header_half.encode() not in answer.body
    assert cookie_half.encode() not in answer.body
    assert "set-cookie" not in answer.headers
