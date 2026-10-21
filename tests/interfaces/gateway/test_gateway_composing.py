"""The composing signal at the gateway: ADR-0332 §5:9 to §5:11's route.

ADR-0332 §5:10: "The gateway serves it at ``POST /chat/composing``, naming the
conversation in its body, as it serves ``write_message`` at ``/chat/message/write``."
Three facts are pinned, each against the router the browser really reaches:

* **the route is one relay**: the conversation the browser named reaches
  ``AssistantEngine.composing`` verbatim, the answer is empty, and nothing else is
  asked of the engine;
* **admission is ADR-0298 §5's Writing row** (ADR-0332 §5:11): the hub decides it for
  the device the gateway names for the request, so a browser device that writes the
  conversation passes and one that only reads it is refused, as its reason's own fault;
* **the signal is never stored** (§5:8): no message, no change and no transcript entry
  follows it.

**The row is the hub's to check** (ADR-0298 §5:6), and the canonical fake checks no
membership row, so :class:`_WritingRow` stands in for the hub's half: it applies the
row the table places ``composing`` in to the device the call ran for. What it observes
of the gateway is the part the gateway owns — which device it named, and how the hub's
refusal reaches the page.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Final

import pytest
from test_gateway_naming import _post
from test_gateway_remote_listener import _PHONE, _remote, _start_session
from test_gateway_streams import Harness, _harness

from ai_assistant.core.device_context import current_acting_for
from ai_assistant.core.errors import DeviceRefusal, DeviceRefusedError
from ai_assistant.core.types import ChatDevice, DeviceAccess
from ai_assistant.interfaces.gateway.refusals import REFUSAL_FAULTS, refusal_detail
from ai_assistant.interfaces.gateway.server import _ASSISTANT_PATHS
from ai_assistant.testing import FakeAssistantEngine
from ai_assistant.wire.routes import Route, route_of

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from ai_assistant.core.types import Identifier

pytestmark = pytest.mark.integration

_PATH: Final = "/chat/composing"

#: This gateway's loopback browser, on a hub of the same machine (ADR-0296 §1:7).
_HUB: Final = "hub"


class _WritingRow(FakeAssistantEngine):
    """A hub that checks ``composing``'s row, as the engine's device checks do.

    ADR-0298 §5 "Writing": "be the named conversation's end for writing". The device is
    the one the call ran for — the outbound name the gateway set around it, which the
    wire client writes into the frame as ``acting_for`` (ADR-0298 §1:5) — and the hub's
    own machine where it named none (§2:1), which passes every row (§3:2).
    """

    def __init__(self) -> None:
        """Record, beside each signal, the device it was made for."""
        super().__init__()
        self.composed_for: list[str | None] = []

    async def composing(self, conversation_id: Identifier) -> None:
        """The Writing row first, then the canonical fake's signal."""
        assert route_of("composing") is Route.WRITING
        device = current_acting_for()
        self.composed_for.append(device)
        if device is not None:
            ends = await self.chat.conversation_devices(conversation_id)
            held = {one.device_id: one.access for one in ends or ()}.get(device)
            if held is None or not held.writes:
                msg = "composing needs a device that is an end for writing of the conversation"
                raise DeviceRefusedError(msg, reason=DeviceRefusal.NOT_ALLOWED)
        await super().composing(conversation_id)


@pytest.fixture
async def harness() -> AsyncIterator[Harness]:
    """A gateway on its own figures, reaching a hub on this machine."""
    async with _harness() as one:
        yield one


async def _started(engine: FakeAssistantEngine, *devices: ChatDevice) -> str:
    """A conversation shown on ``devices``, started at the hub."""
    await engine.set_my_devices(list(devices))
    started = await engine.start_conversation()
    engine.calls.clear()
    return started.id


def _composed(engine: FakeAssistantEngine) -> list[dict[str, Any]]:
    """The arguments of every ``composing`` the engine was asked for."""
    return [arguments for name, arguments in engine.calls if name == "composing"]


# --- the route -------------------------------------------------------------------


def test_the_signal_is_served_at_the_path_the_decision_names() -> None:
    """§5:10's ``POST /chat/composing``, read off the table the router classifies from."""
    assert _ASSISTANT_PATHS[("POST", _PATH)] == "composing"
    assert ("GET", _PATH) not in _ASSISTANT_PATHS


def test_the_signal_is_in_the_writing_row() -> None:
    """§5:11: ADR-0298 §5:1's table puts ``composing`` beside ``write_message``."""
    assert route_of("composing") is Route.WRITING
    assert route_of("composing") is route_of("write_message")


async def test_the_signal_names_the_conversation_and_answers_nothing(harness: Harness) -> None:
    """§5:9: one relay, with the browser's conversation verbatim, and an empty answer.

    A member the surface does not declare is not read, and none is added: the call is
    ``composing`` and nothing else.
    """
    conversation = await _started(
        harness.engine, ChatDevice(device_id=_HUB, access=DeviceAccess.READ_WRITE)
    )

    status, body = await harness.whole(
        "POST", _PATH, {"conversation_id": conversation, "device_id": "nSOMEONEELSE"}
    )

    assert status == 200
    assert body == {}
    assert harness.engine.calls == [("composing", {"conversation_id": conversation})]


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param({}, id="no conversation"),
        pytest.param({"conversation_id": 7}, id="a number"),
        pytest.param({"conversation_id": None}, id="null"),
        pytest.param({"conversation_id": ["c-1"]}, id="a list"),
    ],
)
async def test_a_signal_the_page_could_not_have_meant_is_refused_unrelayed(
    harness: Harness, payload: dict[str, Any]
) -> None:
    """A conversation absent or not a string is malformed, and nothing is relayed."""
    status, body = await harness.whole("POST", _PATH, payload)

    assert status == 400
    assert body == {"fault": "malformed-request"}
    assert harness.engine.calls == []


async def test_a_blank_conversation_is_the_hubs_refusal(harness: Harness) -> None:
    """Relayed verbatim, so a blank id is the surface's to refuse (§5:9's ``ValueError``)."""
    status, body = await harness.whole("POST", _PATH, {"conversation_id": "   "})

    assert status == 400
    assert body["fault"] == "rejected"
    assert _composed(harness.engine) == []


async def test_a_signal_on_a_get_is_no_shape_the_gateway_serves(harness: Harness) -> None:
    """ADR-0168 §6 classifies from the method and path alone: a ``GET`` is no shape."""
    status, _ = await harness.whole("GET", _PATH)

    assert status == 404
    assert harness.engine.calls == []


# --- admission: the Writing row, decided by the hub for the named device ------------


@pytest.mark.parametrize("access", [DeviceAccess.WRITE, DeviceAccess.READ_WRITE])
async def test_a_writing_end_on_the_remote_listener_is_admitted(access: DeviceAccess) -> None:
    """ADR-0298 §5 "Writing": the phone writes the conversation, so its signal passes.

    The device the hub checks is the one the gateway named for the request — the
    phone, from the overlay's naming and from nothing the browser asserts — so the
    row is applied to the device the person is typing on.
    """
    engine = _WritingRow()
    conversation = await _started(engine, ChatDevice(device_id=_PHONE, access=access))
    async with _remote(engine=engine) as one:
        halves = await _start_session(one)
        answer = await _post(one, halves, _PATH, {"conversation_id": conversation})

    assert answer.status == 200, answer.body
    assert json.loads(answer.body) == {}
    assert engine.composed_for == [_PHONE]
    assert _composed(engine) == [{"conversation_id": conversation}]


@pytest.mark.parametrize(
    "devices",
    [
        pytest.param((ChatDevice(device_id=_PHONE, access=DeviceAccess.READ),), id="a reader"),
        pytest.param((ChatDevice(device_id="nLAPTOP", access=DeviceAccess.READ_WRITE),), id="none"),
    ],
)
async def test_a_device_that_is_no_writing_end_is_refused_as_its_reasons_fault(
    devices: tuple[ChatDevice, ...],
) -> None:
    """ADR-0298 §5 "Writing", refused: a reader of the conversation, or no end of it.

    The hub received the request and declined it, so the page is answered ``422`` with
    the reason's own fault and this gateway's sentence naming the phone (ADR-0298 §6),
    exactly as any other refusal for the device is — and the signal went nowhere.
    """
    engine = _WritingRow()
    conversation = await _started(engine, *devices)
    async with _remote(engine=engine) as one:
        halves = await _start_session(one)
        answer = await _post(one, halves, _PATH, {"conversation_id": conversation})

    assert answer.status == 422
    assert answer.payload == {
        "fault": REFUSAL_FAULTS[DeviceRefusal.NOT_ALLOWED],
        "detail": refusal_detail(DeviceRefusal.NOT_ALLOWED, device=_PHONE, gateway=_HUB),
    }
    assert engine.composed_for == [_PHONE]
    assert _composed(engine) == []


async def test_a_loopback_browser_names_no_device_and_the_hub_decides_its_own() -> None:
    """ADR-0298 §1:2: a loopback browser's request is the connecting device's own.

    So nothing is named, and the row is decided for the gateway's own machine — here the
    hub's, which passes every row (§3:2).
    """
    engine = _WritingRow()
    conversation = await _started(engine)
    async with _harness(engine) as harness:
        status, body = await harness.whole("POST", _PATH, {"conversation_id": conversation})

    assert (status, body) == (200, {})
    assert engine.composed_for == [None]


# --- never stored (§5:8) -----------------------------------------------------------


async def test_the_signal_writes_nothing_into_the_conversation(harness: Harness) -> None:
    """§5:8: "It is never written into the transcript, any store or any episode."

    Read back through the reads the page itself makes: the transcript holds no message
    and the changes after the cursor read before the signals hold none.
    """
    conversation = await _started(
        harness.engine, ChatDevice(device_id=_HUB, access=DeviceAccess.READ_WRITE)
    )
    _, before = await harness.whole("POST", "/chat/changes", {"after": 0})
    cursor = before["next_after"]

    for _ in range(3):
        status, _ = await harness.whole("POST", _PATH, {"conversation_id": conversation})
        assert status == 200

    _, transcript = await harness.whole(
        "POST", "/chat/transcript", {"conversation_id": conversation}
    )
    _, after = await harness.whole("POST", "/chat/changes", {"after": cursor})
    assert transcript["transcript"]["entries"] == []
    assert after["changes"] == []
    assert after["next_after"] == cursor
    assert [
        name for name, _ in harness.engine.calls if name not in {"transcript", "chat_changes"}
    ] == ["composing"] * 3
