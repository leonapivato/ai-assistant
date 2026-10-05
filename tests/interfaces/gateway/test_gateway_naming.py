"""The gateway names the browser device each relayed request is for (ADR-0298 §1, §6).

ADR-0298 §1:5: "A gateway names the browser device of a call it relays by setting an
outbound context value around that ``AssistantEngine`` call", and the wire client
writes it into the frame's ``acting_for``. So what these cases observe is the value
the engine call ran inside — :func:`~ai_assistant.core.device_context.current_acting_for`
read at the moment the fake records the call, which is the moment the wire client
would write the frame.

Three facts are pinned:

* a browser on the **remote** listener is named on every request relayed for it, and
  the device its message names is that same name (§2:7's binding is to it);
* a browser on the **loopback** listener names nothing (§1:2), and neither does the
  gateway's own notification poll (§5), whichever listener opened the stream;
* a refusal for the device reaches the page as its reason's own fault, with a sentence
  naming the device and the act that would change the answer (§6).
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Final

import pytest
from test_gateway_remote_listener import (
    _GATEWAY_NODE,
    _PHONE,
    Answer,
    Remote,
    _FakeAgent,
    _remote,
    _start_session,
)
from test_gateway_streams import _Delivering, _harness, _values

from ai_assistant.core.device_context import current_acting_for
from ai_assistant.core.errors import DeviceRefusal, DeviceRefusedError
from ai_assistant.core.types import ChatDevice, ConversationSummary, DeviceAccess
from ai_assistant.interfaces.gateway.refusals import REFUSAL_FAULTS, refusal_detail
from ai_assistant.testing import FakeAssistantEngine

if TYPE_CHECKING:
    from collections.abc import Iterable

pytestmark = pytest.mark.integration

#: The hub's own machine, as the device a loopback browser there is (ADR-0298 §3:1).
_HUB: Final = "hub"


class _NamedCalls(list[tuple[str, dict[str, object]]]):
    """The fake's call log, recording beside each call the name it ran inside."""

    def __init__(self) -> None:
        """Start empty."""
        super().__init__()
        self.named: list[tuple[str, str | None]] = []

    def append(self, call: tuple[str, dict[str, object]]) -> None:
        """Record the call, and the outbound name held while it was made."""
        self.named.append((call[0], current_acting_for()))
        super().append(call)


def _naming(engine: FakeAssistantEngine) -> _NamedCalls:
    """Swap ``engine``'s call log for one that records the outbound name."""
    log = _NamedCalls()
    engine.calls = log
    return log


class _Refusing(FakeAssistantEngine):
    """A hub that refuses every ``start_conversation`` for the device, with one reason."""

    def __init__(self, reason: DeviceRefusal) -> None:
        """Refuse with ``reason``."""
        super().__init__()
        self.reason = reason

    async def start_conversation(self) -> ConversationSummary:
        """Refuse, as the engine's membership row does (ADR-0298 §5, §6)."""
        self.calls.append(("start_conversation", {}))
        msg = "start_conversation needs a device in my devices"
        raise DeviceRefusedError(msg, reason=self.reason)


async def _post(one: Remote, halves: tuple[str, str], path: str, payload: dict[str, Any]) -> Answer:
    """One admitted JSON request from the listed phone, on the remote listener."""
    cookie_half, header_half = halves
    body = json.dumps(payload).encode()
    return await one.send(
        f"POST {path} HTTP/1.1\nHost: {{host}}\nOrigin: {one.origin}\n"
        f"Content-Type: application/json\nContent-Length: {len(body)}\n"
        f"X-Assistant-Session: {header_half}\nCookie: assistant_session={cookie_half}",
        body,
    )


def _names(log: _NamedCalls, *operations: str) -> set[str | None]:
    """Every name the given operations ran inside."""
    return {name for operation, name in log.named if operation in operations}


def _the_operations(log: _NamedCalls) -> Iterable[str]:
    """Every operation the engine was asked for."""
    return [operation for operation, _ in log.named]


# --- the remote listener names its browser ---------------------------------------


async def test_every_call_relayed_for_a_remote_browser_names_it() -> None:
    """ADR-0296 §1:5: "The gateway names the browser device on every request it relays
    for it", and ADR-0298 §1:5 says how — inside the outbound context value.

    Driven over one shape of each kind the router dispatches: a plain relay
    (``/chat/start``), the two that also carry the device to the handler
    (``/chat/devices``, ``/chat/message/write``) and a turn (``/ask``).
    """
    engine = FakeAssistantEngine()
    await engine.set_my_devices([ChatDevice(device_id=_PHONE, access=DeviceAccess.READ_WRITE)])
    log = _naming(engine)
    async with _remote(engine=engine) as one:
        halves = await _start_session(one)
        started = await _post(one, halves, "/chat/start", {})
        devices = await _post(one, halves, "/chat/devices", {})
        conversation = started.payload["conversation"]["id"]
        written = await _post(
            one,
            halves,
            "/chat/message/write",
            {"conversation_id": conversation, "message_id": "m-1", "text": "Hi."},
        )
        asked = await _post(
            one,
            halves,
            "/ask",
            {"utterance": "what is on today", "reference": {"goal_id": "goal-1"}},
        )

    assert (started.status, devices.status, written.status) == (200,) * 3
    assert asked.status == 200, asked.body
    assert set(_the_operations(log)) >= {"start_conversation", "my_devices", "write_message"}
    assert _names(log, *_the_operations(log)) == {_PHONE}
    # §2:7 binds the message's device to the requesting device, which is the name: so
    # the device the page writes is the device the call acted for, from one source.
    assert devices.payload["this_device"] == _PHONE
    (message,) = [arguments["message"] for name, arguments in log if name == "write_message"]
    assert getattr(message, "device_id", None) == _PHONE


async def test_a_remote_browser_on_the_gateways_own_machine_names_nothing() -> None:
    """ADR-0298 §1:2: ``acting_for`` "is absent where the request is the connecting
    device's own".

    A browser reaching this gateway over the overlay from the machine the gateway runs
    on is that machine, whose device is the connecting one — so it is named exactly
    as a loopback browser there is: not at all.
    """
    engine = FakeAssistantEngine()
    log = _naming(engine)
    agent = _FakeAgent(default_peer=_GATEWAY_NODE)
    async with _remote(
        engine=engine, agent=agent, devices=(_GATEWAY_NODE,), remote_hub_address="100.64.0.1"
    ) as one:
        halves = await _start_session(one)
        devices = await _post(one, halves, "/chat/devices", {})

    assert devices.status == 200, devices.body
    assert devices.payload["this_device"] == _GATEWAY_NODE
    assert _names(log, "my_devices") == {None}


async def test_the_name_does_not_outlive_the_call_it_was_set_around() -> None:
    """The value is set around one call and reset after it (ADR-0298 §1:5), so a
    loopback request after a remote one names nothing — the two listeners share one
    gateway and one engine."""
    engine = FakeAssistantEngine()
    log = _naming(engine)
    async with _remote(engine=engine) as one:
        halves = await _start_session(one)
        await _post(one, halves, "/chat/devices", {})

    assert current_acting_for() is None
    assert _names(log, "my_devices") == {_PHONE}


# --- the loopback listener names nothing -------------------------------------------


@pytest.mark.parametrize(
    ("overrides", "device"),
    [
        pytest.param({}, _HUB, id="hub on this machine"),
        pytest.param({"remote_hub_address": "100.64.0.1"}, _GATEWAY_NODE, id="hub elsewhere"),
    ],
)
async def test_a_loopback_browser_names_nothing(overrides: dict[str, Any], device: str) -> None:
    """ADR-0296 §1:7 and ADR-0298 §1:2: a loopback browser is the gateway's own
    machine, the connecting device, so its requests carry no ``acting_for`` — and the
    device its message names is that machine, the device the hub decides (§2:1)."""
    engine = FakeAssistantEngine()
    await engine.set_my_devices([ChatDevice(device_id=device, access=DeviceAccess.READ_WRITE)])
    log = _naming(engine)
    async with _harness(engine, agent=_FakeAgent(), **overrides) as one:
        _, started = await one.whole("POST", "/chat/start", {})
        _, devices = await one.whole("POST", "/chat/devices", {})
        status, body = await one.whole(
            "POST",
            "/chat/message/write",
            {"conversation_id": started["conversation"]["id"], "message_id": "m-1", "text": "Hi."},
        )

    assert status == 200, body
    assert devices["this_device"] == device
    assert _names(log, *_the_operations(log)) == {None}
    (message,) = [arguments["message"] for name, arguments in log if name == "write_message"]
    assert getattr(message, "device_id", None) == device


async def test_the_poll_a_remote_browser_watches_names_nothing() -> None:
    """ADR-0298 §5: ``next_notification`` "is the connecting device's own: a poll
    carrying ``acting_for`` is refused".

    The poll runs in a task started while the remote browser's request is served, and
    a task copies the context it is started in. So the stream is opened outside the
    name, and this is the case that would catch it inside.
    """
    engine = _Delivering([None])
    log = _naming(engine)
    async with _remote(engine=engine) as one:
        cookie_half, header_half = await _start_session(one)
        _, writer = await one.connect()
        writer.write(
            (
                f"GET /deliveries HTTP/1.1\r\nHost: {one.authority}\r\nOrigin: {one.origin}\r\n"
                f"X-Assistant-Session: {header_half}\r\n"
                f"Cookie: assistant_session={cookie_half}\r\n\r\n"
            ).encode()
        )
        await writer.drain()
        await engine.polling.wait()
        writer.close()

    assert _names(log, "next_notification") == {None}


# --- a refusal for the device is said as its reason --------------------------------


@pytest.mark.parametrize("reason", list(DeviceRefusal))
async def test_a_refusal_for_a_remote_browser_is_its_reasons_own_fault(
    reason: DeviceRefusal,
) -> None:
    """ADR-0298 §6:2's three reasons are three conditions to the owner, so each is its
    own fault, at `422` — the hub received the request and declined it (ADR-0168 §9) —
    with this gateway's sentence naming the device the request acted for."""
    async with _remote(engine=_Refusing(reason)) as one:
        halves = await _start_session(one)
        answer = await _post(one, halves, "/chat/start", {})

    assert answer.status == 422
    assert answer.payload == {
        "fault": REFUSAL_FAULTS[reason],
        "detail": refusal_detail(reason, device=_PHONE, gateway=_HUB),
    }
    assert _PHONE in answer.payload["detail"]
    # The hub's own message is not relayed: the sentence is this gateway's (refusals).
    assert "needs a device in my devices" not in answer.payload["detail"]


async def test_a_refusal_for_a_loopback_browser_names_the_gateways_own_device() -> None:
    """Where the request names nothing, the hub decided the connecting device (§2:1):
    the gateway's own machine, which is the device the sentence must name."""
    engine = _Refusing(DeviceRefusal.NO_ROLE)
    async with _harness(engine, agent=_FakeAgent(), remote_hub_address="100.64.0.1") as one:
        status, body = await one.whole("POST", "/chat/start", {})

    assert status == 422
    assert body["fault"] == "device-without-role"
    assert f"ai-assistant-device assign {_GATEWAY_NODE} commands" in body["detail"]


async def test_a_refused_poll_ends_the_stream_with_its_reasons_own_fault() -> None:
    """The poll is the gateway's own (§5), so a refusal of it is a refusal of the
    gateway's own device — "be in my devices for reading, as the connecting device"
    — and the page is told which device, in the same words as any other refusal."""
    refused = DeviceRefusedError(
        "next_notification needs a device in my devices for reading",
        reason=DeviceRefusal.NOT_ALLOWED,
    )
    engine = _Delivering([refused])
    async with _harness(engine, agent=_FakeAgent(), remote_hub_address="100.64.0.1") as one:
        reader, _, status = await one.send("GET", "/deliveries")
        assert status == 200
        await engine.answer_one_poll()
        values = [value async for value in _values(reader)]

    assert values[-1] == {
        "kind": "fault",
        "fault": "device-not-allowed",
        "detail": refusal_detail(
            DeviceRefusal.NOT_ALLOWED, device=_GATEWAY_NODE, gateway=_GATEWAY_NODE
        ),
    }


@pytest.mark.parametrize("reason", list(DeviceRefusal))
def test_each_sentence_names_the_device_and_the_act_that_changes_the_answer(
    reason: DeviceRefusal,
) -> None:
    """The owner reads the remedy, not a reason code: each sentence names the device
    and an ``ai-assistant-device`` act run on the hub's machine."""
    said = refusal_detail(reason, device=_PHONE, gateway=_GATEWAY_NODE)

    assert _PHONE in said
    assert "ai-assistant-device" in said
    assert "hub's machine" in said


def test_a_sentence_for_a_device_the_gateway_could_not_name_says_so() -> None:
    """A loopback browser whose machine the agent would not name (ADR-0296 §1:7) has
    no id to put in the command, and the sentence says what goes there instead."""
    said = refusal_detail(DeviceRefusal.NOT_ACCEPTED, device=None, gateway=None)

    assert "<this machine's overlay identity>" in said
    assert "<the gateway machine's overlay identity>" in said
    assert "None" not in said


def test_the_three_reasons_are_three_conditions() -> None:
    """One fault name per reason, and no two reasons share one (ADR-0298 §6:2)."""
    assert set(REFUSAL_FAULTS) == set(DeviceRefusal)
    assert len(set(REFUSAL_FAULTS.values())) == len(DeviceRefusal)
