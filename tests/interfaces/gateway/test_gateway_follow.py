"""The change stream, relayed to a browser (ADR-0296 §4, ADR-0298 §7).

The gateway opens one hub stream per browser stream and relays it change for change:
each chunk becomes one value under its own kind, the hub's ending becomes the terminal
``end``, and a refusal the hub makes becomes the terminal ``fault`` a refused request
would carry. The whole iteration runs inside the browser device's name (§1:5), so a
remote browser's stream — reopened as often as the hub goes quiet — is the device's
own, and a loopback browser's names nothing (§1:2).

Two engines drive it: the canonical fake, whose own change stream is the engine's
(PR #2732), for what a following page really receives; and a scripted one, for the
chunks the fake never writes in-process — a snapshot, roles, a heartbeat, the hub's
ending and a refusal.
"""

from __future__ import annotations

import asyncio
import json
from datetime import timedelta
from typing import TYPE_CHECKING, Any, Final

import pytest
from test_gateway_remote_listener import (
    _GATEWAY_NODE,
    _PHONE,
    Remote,
    _FakeAgent,
    _remote,
    _start_session,
)
from test_gateway_streams import Harness, _harness, _values

from ai_assistant.core.device_context import current_acting_for
from ai_assistant.core.errors import ConversationStoreError, DeviceRefusal, DeviceRefusedError
from ai_assistant.core.streams import closing_stream
from ai_assistant.core.types import (
    ActivationEnding,
    ChatDevice,
    ChatStreamChunk,
    ChatStreamEnd,
    ConversationState,
    CurrentState,
    DeletedMessage,
    DeviceAccess,
    DeviceChange,
    DeviceRole,
    DevicesChangedChange,
    MessageAuthor,
    NewMessage,
)
from ai_assistant.interfaces.gateway.change_stream import paced
from ai_assistant.interfaces.gateway.refusals import refusal_detail
from ai_assistant.interfaces.gateway.server import _ASSISTANT_PATHS, _STREAMED_SHAPES
from ai_assistant.testing import FakeAssistantEngine
from ai_assistant.wire.errors import HubUnavailableError

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

pytestmark = pytest.mark.integration

_FOLLOW: Final = "/chat/follow"

#: The hub's own machine, as the device a loopback browser there is (ADR-0298 §3:1).
_HUB: Final = "hub"


class _Scripted(FakeAssistantEngine):
    """A hub whose change stream yields what the case puts on it, one at a time.

    Records the outbound name each step ran inside, which is the name the wire client
    would write into the frame it reopens the stream with.
    """

    def __init__(self) -> None:
        """Hold an empty script."""
        super().__init__()
        self.script: asyncio.Queue[ChatStreamChunk | ChatStreamEnd | Exception] = asyncio.Queue()
        self.named: list[str | None] = []
        self.closed = asyncio.Event()

    def follow_chat(self, *, after: int) -> AsyncIterator[ChatStreamChunk | ChatStreamEnd]:
        """Follow the script from ``after``."""
        self.calls.append(("follow_chat", {"after": after}))
        self.named.append(current_acting_for())
        return self._following()

    async def _following(self) -> AsyncIterator[ChatStreamChunk | ChatStreamEnd]:
        try:
            while True:
                item = await self.script.get()
                self.named.append(current_acting_for())
                if isinstance(item, Exception):
                    raise item
                yield item
        finally:
            self.closed.set()


async def _follow(one: Harness, after: int = 0) -> asyncio.StreamReader:
    """Open a change stream on the loopback listener, and check its head."""
    reader, headers, status = await one.send("POST", _FOLLOW, {"after": after})
    assert status == 200
    assert headers["content-type"] == ["application/x-ndjson"]
    return reader


async def _follow_remote(one: Remote) -> list[dict[str, Any]]:
    """Open a change stream as the listed phone, and read it to its end."""
    cookie_half, header_half = await _start_session(one)
    reader, writer = await one.connect()
    body = json.dumps({"after": 0}).encode()
    writer.write(
        (
            f"POST {_FOLLOW} HTTP/1.1\r\nHost: {one.authority}\r\nOrigin: {one.origin}\r\n"
            f"Content-Type: application/json\r\nContent-Length: {len(body)}\r\n"
            f"X-Assistant-Session: {header_half}\r\n"
            f"Cookie: assistant_session={cookie_half}\r\n\r\n"
        ).encode()
        + body
    )
    await writer.drain()
    head = await reader.readuntil(b"\r\n\r\n")
    assert head.startswith(b"HTTP/1.1 200 "), head
    async with asyncio.timeout(5):
        return [value async for value in _values(reader)]


async def _next(values: AsyncIterator[dict[str, Any]]) -> dict[str, Any]:
    """The next value, within a bound that fails a case rather than hanging it."""
    async with asyncio.timeout(5):
        return await anext(values)


# --- the route ---------------------------------------------------------------------


def test_the_change_stream_is_in_the_enumeration_and_is_a_stream() -> None:
    """ADR-0296's record on ADR-0177 §1:1 gains "the change stream", and it answers on
    a stream (ADR-0175 §1), held against the session that opened it (§7)."""
    assert _ASSISTANT_PATHS[("POST", _FOLLOW)] == "follow_chat"
    assert ("POST", _FOLLOW) in _STREAMED_SHAPES
    assert ("POST", "/chat/changes") not in _STREAMED_SHAPES


@pytest.mark.parametrize("payload", [{}, {"after": -1}, {"after": "3"}, {"after": 2**63}])
async def test_a_cursor_the_surface_refuses_is_refused_before_the_hub(
    payload: dict[str, Any],
) -> None:
    """``after`` is required and in ``[0, 2**63)``, as ``chat_changes``' is."""
    async with _harness() as one:
        status, body = await one.whole("POST", _FOLLOW, payload)

    assert status == 400
    assert body["fault"] == "malformed-request"
    assert all(name != "follow_chat" for name, _ in one.engine.calls)


# --- what the page receives ----------------------------------------------------------


async def test_a_message_written_after_opening_arrives_as_a_change() -> None:
    """The fake's own change stream, relayed: a change carries its sequence number and
    the change as ``chat_changes`` renders it, and a snapshot member that is null where
    the change adds no reader."""
    engine = FakeAssistantEngine()
    await engine.set_my_devices([ChatDevice(device_id=_HUB, access=DeviceAccess.READ_WRITE)])
    started = await engine.start_conversation()
    cursor = (await engine.chat_changes(after=0)).next_after
    async with _harness(engine) as one:
        values = _values(await _follow(one, cursor))
        await engine.chat.append_message(
            started.id, NewMessage(author=MessageAuthor.ASSISTANT, text="Pinecrest, Friday.")
        )
        value = await _next(values)

    assert value["kind"] == "change"
    assert value["snapshot"] is None
    change = value["change"]
    assert change["kind"] == "message_added"
    assert change["seq"] > cursor
    assert change["conversation_id"] == started.id
    assert change["message"]["text"] == "Pinecrest, Friday."
    assert ("follow_chat", {"after": cursor}) in engine.calls


async def test_each_chunk_is_one_value_of_its_own_kind() -> None:
    """ADR-0298 §7:3's four, each under its own kind: a change with its snapshot as a
    transcript renders its entries, a conversation's state, the device's roles, and the
    hub's heartbeat as the gateway's own keep-alive."""
    source = FakeAssistantEngine()
    started = await source.start_conversation()
    await source.chat.append_message(
        started.id, NewMessage(author=MessageAuthor.ASSISTANT, text="Pinecrest, Friday.")
    )
    page = await source.transcript(started.id)
    assert page is not None
    snapshot = (*page.entries, DeletedMessage(conversation_id=started.id, position=2))
    added = DeviceChange(
        change=DevicesChangedChange(
            seq=7,
            conversation_id=started.id,
            devices=(ChatDevice(device_id=_PHONE, access=DeviceAccess.READ),),
        ),
        snapshot=snapshot,
    )
    engine = _Scripted()
    for chunk in (
        ChatStreamChunk(change=added),
        ChatStreamChunk(
            state=CurrentState(
                conversation_id=started.id,
                state=ConversationState(last_ended=ActivationEnding.DONE),
            )
        ),
        ChatStreamChunk(roles=(DeviceRole.COMMANDS,)),
        ChatStreamChunk(heartbeat=True),
    ):
        engine.script.put_nowait(chunk)
    async with _harness(engine) as one:
        values = _values(await _follow(one, 6))
        taken = [await _next(values) for _ in range(4)]

    change, state, roles, alive = taken
    assert change == {
        "kind": "change",
        "change": {
            "kind": "devices_changed",
            "seq": 7,
            "conversation_id": started.id,
            "devices": [{"device_id": _PHONE, "access": "read"}],
        },
        "snapshot": [
            {
                "position": 1,
                "deleted": False,
                "written_at": page.entries[0].written_at.isoformat(),  # type: ignore[union-attr]
                "author": "assistant",
                "text": "Pinecrest, Friday.",
                "replies_to": None,
                "options": [],
                "cut_off": False,
                "device_id": None,
                "message_id": None,
            },
            {"position": 2, "deleted": True},
        ],
    }
    assert state == {
        "kind": "state",
        "conversation_id": started.id,
        "state": {"working": False, "activation_id": None, "last_ended": "done"},
    }
    assert roles == {"kind": "roles", "roles": ["commands"]}
    assert alive == {"kind": "alive"}


async def test_the_hubs_ending_is_relayed_as_the_terminal_end_and_the_body_ends() -> None:
    """``ChatStreamEnd`` is written only as the hub shuts down, with the cursor to
    follow again from; the gateway relays it and ends the body, so the page has a
    terminal value rather than a cut connection."""
    engine = _Scripted()
    engine.script.put_nowait(ChatStreamEnd(next_after=12))
    async with _harness(engine) as one:
        taken = [value async for value in _values(await _follow(one, 3))]
        await asyncio.wait_for(engine.closed.wait(), 5)

    assert taken == [{"kind": "end", "next_after": 12}]


async def test_a_quiet_chat_is_kept_alive_at_the_cadence_the_head_states() -> None:
    """The gateway writes ``alive`` whenever its cadence passes with nothing relayed —
    an engine followed in-process writes no heartbeat — and states that cadence in the
    head, so the page can tell a quiet chat from a dead stream."""
    engine = _Scripted()
    async with _harness(engine, gateway_notification_budget=timedelta(milliseconds=50)) as one:
        reader, headers, status = await one.send("POST", _FOLLOW, {"after": 0})
        values = _values(reader)
        first, second = await _next(values), await _next(values)
        engine.script.put_nowait(ChatStreamChunk(roles=()))
        after = await _next(values)
        while after["kind"] == "alive":
            after = await _next(values)

    assert status == 200
    assert headers["x-assistant-keep-alive-microseconds"] == ["50000"]
    assert first == second == {"kind": "alive"}
    # The step waiting on the hub was not cancelled for the keep-alives: one stream,
    # and the chunk that came after them is the one relayed.
    assert [name for name, _ in engine.calls].count("follow_chat") == 1
    assert after == {"kind": "roles", "roles": []}


# --- whose stream it is --------------------------------------------------------------


async def test_a_remote_browsers_stream_runs_inside_its_name_throughout() -> None:
    """ADR-0298 §1:5: the gateway names the browser device around the whole iteration,
    so every step — the opening and each one after it — writes ``acting_for``."""
    engine = _Scripted()
    engine.script.put_nowait(ChatStreamChunk(roles=(DeviceRole.COMMANDS,)))
    engine.script.put_nowait(ChatStreamEnd(next_after=0))
    async with _remote(engine=engine) as one:
        taken = await _follow_remote(one)

    assert taken == [{"kind": "roles", "roles": ["commands"]}, {"kind": "end", "next_after": 0}]
    assert engine.named == [_PHONE, _PHONE, _PHONE]
    assert current_acting_for() is None


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({}, id="hub on this machine"),
        pytest.param({"remote_hub_address": "100.64.0.1"}, id="hub elsewhere"),
    ],
)
async def test_a_loopback_browsers_stream_names_nothing(overrides: dict[str, Any]) -> None:
    """ADR-0298 §1:2: the loopback browser is the connecting device."""
    engine = _Scripted()
    engine.script.put_nowait(ChatStreamEnd(next_after=0))
    async with _harness(engine, agent=_FakeAgent(), **overrides) as one:
        [value async for value in _values(await _follow(one))]

    assert set(engine.named) == {None}


# --- how it ends ---------------------------------------------------------------------


async def test_a_device_without_a_role_is_refused_as_the_stream_ends() -> None:
    """The role check is the stream's first step (ADR-0298 §5), so its refusal arrives
    after the head as the terminal fault, in the same name and sentence a refused
    request carries — the condition the page drops what it holds on (§7:13)."""
    engine = _Scripted()
    engine.script.put_nowait(
        DeviceRefusedError("reading many needs a role", reason=DeviceRefusal.NO_ROLE)
    )
    async with _remote(engine=engine) as one:
        taken = await _follow_remote(one)

    assert taken == [
        {
            "kind": "fault",
            "fault": "device-without-role",
            "detail": refusal_detail(DeviceRefusal.NO_ROLE, device=_PHONE, gateway=_HUB),
        }
    ]
    assert engine.closed.is_set()


async def test_a_loopback_refusal_names_the_gateways_own_device() -> None:
    """Where the stream names nothing, the hub decided the connecting device (§2:1)."""
    engine = _Scripted()
    engine.script.put_nowait(
        DeviceRefusedError("reading many needs a role", reason=DeviceRefusal.NO_ROLE)
    )
    async with _harness(engine, agent=_FakeAgent(), remote_hub_address="100.64.0.1") as one:
        taken = [value async for value in _values(await _follow(one))]

    assert taken[-1]["fault"] == "device-without-role"
    assert f"ai-assistant-device assign {_GATEWAY_NODE} commands" in taken[-1]["detail"]


@pytest.mark.parametrize(
    ("failure", "fault"),
    [
        pytest.param(HubUnavailableError("the hub is not running"), "hub-unreachable", id="hub"),
        pytest.param(ConversationStoreError("unreadable"), "assistant-declined", id="declined"),
    ],
)
async def test_a_failure_mid_stream_is_its_own_terminal_fault(
    failure: Exception, fault: str
) -> None:
    """ADR-0168 §9's distinction survives onto the stream: a hub that cannot be reached
    is not a request the hub declined, and neither is a cut connection."""
    engine = _Scripted()
    engine.script.put_nowait(ChatStreamChunk(roles=()))
    engine.script.put_nowait(failure)
    async with _harness(engine) as one:
        taken = [value async for value in _values(await _follow(one))]

    assert taken[0] == {"kind": "roles", "roles": []}
    assert taken[-1]["kind"] == "fault"
    assert taken[-1]["fault"] == fault


async def test_a_session_ending_ends_the_stream_and_closes_the_hubs() -> None:
    """ADR-0175 §7: a stream ends no later than the session that admitted it, named as
    ``no-live-session``; and the hub stream under it is closed, not left running."""
    engine = _Scripted()
    async with _harness(engine) as one:
        values = _values(await _follow(one))
        await asyncio.sleep(0.05)
        one.gateway.close()
        taken = [value async for value in values]
        await asyncio.wait_for(engine.closed.wait(), 5)

    assert taken == [{"kind": "fault", "fault": "no-live-session"}]


async def test_the_stream_holds_a_hub_connection_until_it_ends() -> None:
    """The stream counts against ``gateway_max_hub_connections`` for its life, as a
    delivery poll does (ADR-0175 §7): a second is refused with the ceiling, and the
    slot comes back when the first ends."""
    engine = _Scripted()
    async with _harness(engine, gateway_max_hub_connections=1) as one:
        await _follow(one)
        status, body = await one.whole("POST", _FOLLOW, {"after": 0})
        assert (status, body["fault"]) == (503, "hub-connection-ceiling")
        engine.script.put_nowait(ChatStreamEnd(next_after=0))
        await asyncio.wait_for(engine.closed.wait(), 5)
        await asyncio.sleep(0.05)
        reader = await _follow(one)

    assert reader is not None


# --- the pacing ----------------------------------------------------------------------


async def test_pacing_never_cancels_the_step_it_is_waiting_on() -> None:
    """A keep-alive is yielded while the next step is still out, and that same step's
    item is the next one yielded: cancelling it would close a wire stream mid-read."""
    released = asyncio.Event()
    started = 0

    async def slow() -> AsyncIterator[str]:
        nonlocal started
        started += 1
        await released.wait()
        yield "the change"

    stream = paced(slow(), every=0.01)
    async with closing_stream(stream):
        assert await anext(stream) is None
        assert await anext(stream) is None
        released.set()
        while (item := await anext(stream)) is None:
            pass
        assert item == "the change"
        with pytest.raises(StopAsyncIteration):
            await anext(stream)

    assert started == 1


async def test_closing_the_pacing_closes_what_it_paces() -> None:
    """Closing it cancels the step in flight and closes the stream under it."""
    closed = asyncio.Event()

    async def forever() -> AsyncIterator[str]:
        try:
            await asyncio.Event().wait()
            yield "never"
        finally:
            closed.set()

    async with closing_stream(paced(forever(), every=0.01)) as stream:
        assert await anext(stream) is None

    assert closed.is_set()
