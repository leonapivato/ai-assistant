"""The chat space at the gateway: ADR-0293 §11's acts in the medium and their reads.

ADR-0296's record on ADR-0177 §1:1 widens the browser's enumeration with "the acts in
the medium (ADR-0293 §11:2) and the change stream", and its record on §1:5 adds the
name of the browser device to the closed class of what the gateway supplies of its own.
Both halves are asserted: the table names the operations, and the driven requests say
the router reaches the engine for each with the browser's arguments and nothing else —
except the device a message is written from, which is the gateway's naming and which no
body member can supply.

**The change stream is not here.** Until the hub serves one (ADR-0296 §4) a device
catches up with one request for every change after its cursor (ADR-0293 §5:11, §11:1),
and that request is what ``/chat/changes`` relays.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

import pytest
from test_gateway_remote_listener import _GATEWAY_NODE, _PHONE, _FakeAgent, _remote, _start_session
from test_gateway_streams import Harness, _harness

from ai_assistant.core.config import Settings
from ai_assistant.core.types import (
    TRANSCRIPT_MESSAGE_MAX_CHARS,
    ActivationEnding,
    ChatDevice,
    ConversationState,
    DeviceAccess,
    MessageAuthor,
    NewMessage,
    UserMessage,
)
from ai_assistant.interfaces.gateway.server import _ASSISTANT_PATHS, _agent_for
from ai_assistant.testing import FakeAssistantEngine
from ai_assistant.wire.overlay import TailscaleAgent

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

pytestmark = pytest.mark.integration

#: Every path this lane adds, with the operation it resolves to.
_CHAT_PATHS: Final = {
    "/chat/start": "start_conversation",
    "/chat/devices": "my_devices",
    "/chat/devices/set": "set_my_devices",
    "/chat/conversation/devices/set": "set_conversation_devices",
    "/chat/message/write": "write_message",
    "/chat/message/delete": "delete_message",
    "/chat/conversation/delete": "delete_conversation",
    "/chat/transcript": "transcript",
    "/chat/changes": "chat_changes",
}

#: This gateway's loopback browser, on a hub of the same machine (ADR-0296 §1:7).
_HUB: Final = "hub"


@pytest.fixture
async def harness() -> AsyncIterator[Harness]:
    """A gateway on its own figures, reaching a hub on this machine."""
    async with _harness() as one:
        yield one


async def _started(harness: Harness, *, devices: tuple[str, ...] = (_HUB,)) -> str:
    """Put ``devices`` in "my devices" and start a conversation shown on them."""
    await harness.engine.set_my_devices(
        [ChatDevice(device_id=one, access=DeviceAccess.READ_WRITE) for one in devices]
    )
    status, body = await harness.whole("POST", "/chat/start", {})
    assert status == 200
    named: str = body["conversation"]["id"]
    return named


def _written(harness: Harness) -> list[dict[str, Any]]:
    """The arguments of every ``write_message`` the engine was asked to make."""
    return [arguments for name, arguments in harness.engine.calls if name == "write_message"]


def test_the_acts_and_the_changes_read_are_in_the_enumeration() -> None:
    """ADR-0296's record on ADR-0177 §1:1, read off the table the router classifies from."""
    for path, operation in _CHAT_PATHS.items():
        assert _ASSISTANT_PATHS[("POST", path)] == operation, path
        assert ("GET", path) not in _ASSISTANT_PATHS, path


async def test_starting_a_conversation_answers_its_summary(harness: Harness) -> None:
    """ADR-0293 §2:1: an act in the medium that creates an empty conversation."""
    status, body = await harness.whole("POST", "/chat/start", {})

    assert status == 200
    started = body["conversation"]
    assert set(started) == {"id", "started_at", "last_active_at", "last_turn_at"}
    assert started["last_turn_at"] is None
    assert [name for name, _ in harness.engine.calls] == ["start_conversation"]


async def test_my_devices_says_which_device_this_browser_is(harness: Harness) -> None:
    """§3:1's set, and the gateway's naming of the browser's own machine beside it.

    A loopback browser of a gateway whose hub is on this machine is that machine's hub
    device (ADR-0296 §1:7), whose id is ``hub`` (ADR-0298 §3, held).
    """
    status, body = await harness.whole("POST", "/chat/devices", {})
    assert status == 200
    assert body == {"devices": [], "this_device": _HUB}

    await harness.engine.set_my_devices([ChatDevice(device_id="nPHONE", access=DeviceAccess.READ)])
    _, body = await harness.whole("POST", "/chat/devices", {})
    assert body["devices"] == [{"device_id": "nPHONE", "access": "read"}]


async def test_my_devices_is_replaced_by_the_set_the_browser_sent(harness: Harness) -> None:
    """§3:1: the whole set travels, and the answer is whether it changed."""
    devices = [
        {"device_id": _HUB, "access": "read_write"},
        {"device_id": "nWATCH", "access": "read"},
    ]
    status, body = await harness.whole("POST", "/chat/devices/set", {"devices": devices})

    assert status == 200
    assert body == {"changed": True}
    assert await harness.engine.my_devices() == (
        ChatDevice(device_id=_HUB, access=DeviceAccess.READ_WRITE),
        ChatDevice(device_id="nWATCH", access=DeviceAccess.READ),
    )
    _, again = await harness.whole("POST", "/chat/devices/set", {"devices": devices})
    assert again == {"changed": False}


@pytest.mark.parametrize(
    "devices",
    [
        None,
        "hub",
        [{"device_id": _HUB}],
        [{"device_id": _HUB, "access": "everything"}],
        [{"device_id": _HUB, "access": "read", "label": "laptop"}],
        [{"device_id": _HUB, "access": []}],
        [{"device_id": _HUB, "access": {}}],
        [{"device_id": [], "access": "read"}],
        [{"device_id": 7, "access": "read"}],
        [{"device_id": "  ", "access": "read"}],
        ["hub"],
    ],
)
async def test_a_device_set_the_page_could_not_have_meant_is_refused_unrelayed(
    harness: Harness, devices: object
) -> None:
    """Each entry is ``{device_id, access}`` and nothing else; anything else is malformed."""
    payload = {} if devices is None else {"devices": devices}
    status, body = await harness.whole("POST", "/chat/devices/set", payload)

    assert status == 400
    assert body == {"fault": "malformed-request"}
    assert harness.engine.calls == []


async def test_a_set_naming_one_device_twice_is_the_surfaces_refusal(harness: Harness) -> None:
    """The surface refuses a duplicate (``checked_chat_devices``); the gateway relays it."""
    twice = [{"device_id": _HUB, "access": "read"}, {"device_id": _HUB, "access": "write"}]
    status, body = await harness.whole("POST", "/chat/devices/set", {"devices": twice})

    assert status == 400
    assert body["fault"] == "rejected"


async def test_a_written_message_is_received_at_its_position(harness: Harness) -> None:
    """§4:1, §4:4: the message carries the device the gateway named, and *received*.

    **A body member naming another device is not read**: the device is the gateway's
    naming (ADR-0296's record on ADR-0177 §1:5), so a page cannot write as a device it
    is not.
    """
    conversation = await _started(harness)
    status, body = await harness.whole(
        "POST",
        "/chat/message/write",
        {
            "conversation_id": conversation,
            "message_id": "m-1",
            "text": "Book the usual campsite.",
            "device_id": "nSOMEONEELSE",
        },
    )

    assert status == 200
    assert body == {
        "receipt": {"conversation_id": conversation, "outcome": "recorded", "position": 1}
    }
    (written,) = _written(harness)
    assert written["message"] == UserMessage(
        device_id=_HUB, message_id="m-1", text="Book the usual campsite."
    )


async def test_sending_again_is_the_same_message(harness: Harness) -> None:
    """§4:2: the same device's same message id is the same message, recorded once."""
    conversation = await _started(harness)
    sent = {"conversation_id": conversation, "message_id": "m-1", "text": "Hello."}
    await harness.whole("POST", "/chat/message/write", sent)

    status, body = await harness.whole("POST", "/chat/message/write", sent)

    assert status == 200
    assert body["receipt"] == {
        "conversation_id": conversation,
        "outcome": "repeated",
        "position": 1,
    }


async def test_a_reply_names_the_position_it_replies_to(harness: Harness) -> None:
    """§4:5: a message may name one earlier message; one never held is the hub's answer."""
    conversation = await _started(harness)
    await harness.whole(
        "POST",
        "/chat/message/write",
        {"conversation_id": conversation, "message_id": "m-1", "text": "First."},
    )
    _, body = await harness.whole(
        "POST",
        "/chat/message/write",
        {"conversation_id": conversation, "message_id": "m-2", "text": "No.", "replies_to": 1},
    )
    assert body["receipt"]["position"] == 2
    assert _written(harness)[1]["message"].replies_to == 1

    _, body = await harness.whole(
        "POST",
        "/chat/message/write",
        {"conversation_id": conversation, "message_id": "m-3", "text": "?", "replies_to": 9},
    )
    assert body["receipt"] == {
        "conversation_id": conversation,
        "outcome": "no_such_reply",
        "position": None,
    }


async def test_a_device_that_is_not_an_end_is_answered_with_no_position(
    harness: Harness,
) -> None:
    """§7:2: only a conversation's devices write in it. The answer is an outcome, not a fault."""
    conversation = await _started(harness, devices=())

    status, body = await harness.whole(
        "POST",
        "/chat/message/write",
        {"conversation_id": conversation, "message_id": "m-1", "text": "Hello."},
    )

    assert status == 200
    assert body["receipt"] == {
        "conversation_id": conversation,
        "outcome": "not_an_end",
        "position": None,
    }


async def test_a_message_over_the_bound_is_refused_on_the_send(harness: Harness) -> None:
    """§4:7: "refused, with the error on the send, and is not recorded"."""
    conversation = await _started(harness)

    status, body = await harness.whole(
        "POST",
        "/chat/message/write",
        {
            "conversation_id": conversation,
            "message_id": "m-1",
            "text": "x" * (TRANSCRIPT_MESSAGE_MAX_CHARS + 1),
        },
    )

    assert status == 422
    assert body["fault"] == "message-too-long"
    assert str(TRANSCRIPT_MESSAGE_MAX_CHARS) in body["detail"]
    assert _written(harness) == []


@pytest.mark.parametrize(
    "payload",
    [
        {"message_id": "m-1", "text": "Hello."},
        {"conversation_id": "c", "text": "Hello."},
        {"conversation_id": "c", "message_id": "m-1"},
        {"conversation_id": "c", "message_id": "m-1", "text": "   "},
        {"conversation_id": "c", "message_id": " ", "text": "Hello."},
        {"conversation_id": "c", "message_id": "m-1", "text": "Hi", "replies_to": 0},
        {"conversation_id": "c", "message_id": "m-1", "text": "Hi", "replies_to": True},
        {"conversation_id": "c", "message_id": "m-1", "text": "Hi", "replies_to": "1"},
    ],
)
async def test_a_write_the_page_could_not_have_meant_is_refused_unrelayed(
    harness: Harness, payload: dict[str, Any]
) -> None:
    """A member absent, blank or of the wrong type is malformed, and nothing is relayed."""
    status, body = await harness.whole("POST", "/chat/message/write", payload)

    assert status == 400
    assert body == {"fault": "malformed-request"}
    assert harness.engine.calls == []


async def test_writing_into_a_conversation_that_is_gone_is_its_own_condition(
    harness: Harness,
) -> None:
    """§2:2: a conversation is never created by a message; a gone one is named as gone."""
    conversation = await _started(harness)
    await harness.engine.delete_conversation(conversation)

    status, body = await harness.whole(
        "POST",
        "/chat/message/write",
        {"conversation_id": conversation, "message_id": "m-1", "text": "Hello."},
    )

    assert status == 404
    assert body == {"fault": "no-such-conversation"}


@pytest.mark.parametrize(
    "agent",
    [
        pytest.param(None, id="no agent"),
        pytest.param(_FakeAgent(own=None), id="an agent that will not say"),
    ],
)
async def test_a_gateway_that_cannot_name_the_browsers_device_writes_nothing(
    agent: _FakeAgent | None,
) -> None:
    """A loopback browser whose machine its own agent would not name has no name here.

    That machine's device id is its overlay identity (ADR-0296 §1:7, ADR-0298 §3), and
    the gateway could not read it; recording the message under an id the hub would not
    know the machine by would make §4:2's repeat and §7:2's ends answer for the wrong
    device. So the write is refused as its own condition, and the page is told — and
    the gateway serves regardless (ADR-0168 §9).
    """
    async with _harness(remote_hub_address="100.64.0.1", agent=agent) as harness:
        _, devices = await harness.whole("POST", "/chat/devices", {})
        status, body = await harness.whole(
            "POST",
            "/chat/message/write",
            {"conversation_id": "c-1", "message_id": "m-1", "text": "Hello."},
        )

    assert devices["this_device"] is None
    assert status == 422
    assert body["fault"] == "device-unnamed"
    assert _written(harness) == []


async def test_a_loopback_browser_of_a_remote_hub_writes_as_this_machines_overlay_node() -> None:
    """ADR-0296 §1:7 where the hub is elsewhere: the machine's device is its overlay id.

    Read once, at start, from the gateway's own agent — the same stable identifier the
    hub's enrolment recorded for this machine — so a browser on the loopback listener
    writes as the machine the hub knows, with no setting naming it.
    """
    agent = _FakeAgent()
    engine = FakeAssistantEngine()
    await engine.set_my_devices(
        [ChatDevice(device_id=_GATEWAY_NODE, access=DeviceAccess.READ_WRITE)]
    )
    started = await engine.start_conversation()
    async with _harness(engine, remote_hub_address="100.64.0.1", agent=agent) as harness:
        _, devices = await harness.whole("POST", "/chat/devices", {})
        status, body = await harness.whole(
            "POST",
            "/chat/message/write",
            {"conversation_id": started.id, "message_id": "m-1", "text": "Hello."},
        )

    assert devices["this_device"] == _GATEWAY_NODE
    assert status == 200, body
    (written,) = _written(harness)
    assert written["message"].device_id == _GATEWAY_NODE
    assert agent.own_asked == 1
    assert agent.asked == []


async def test_a_gateway_on_the_hubs_machine_never_asks_its_agent_which_node_it_is() -> None:
    """Where the hub is on this machine the device is ``hub``, and nothing is read."""
    agent = _FakeAgent()
    async with _harness(agent=agent) as harness:
        _, devices = await harness.whole("POST", "/chat/devices", {})

    assert devices["this_device"] == _HUB
    assert agent.own_asked == 0


@pytest.mark.parametrize(
    ("overrides", "built"),
    [
        pytest.param({}, False, id="hub here, no remote listener: no agent"),
        pytest.param({"remote_hub_address": "100.64.0.1"}, True, id="hub elsewhere"),
    ],
)
def test_the_agent_is_built_where_this_machines_device_needs_it(
    overrides: dict[str, Any], *, built: bool
) -> None:
    """The real composition's half: a gateway of a remote hub has an agent to ask."""
    agent = _agent_for(Settings(**overrides))

    assert isinstance(agent, TailscaleAgent) is built


async def test_a_remote_browser_writes_as_the_device_the_overlay_named() -> None:
    """ADR-0296 §1:1: a browser device is the overlay identity its gateway obtained.

    The identity is ADR-0174 §3's, taken from the gateway's own agent and from nothing
    the peer asserts — so the phone's message is the phone's.
    """
    async with _remote() as one:
        await one.engine.set_my_devices(
            [ChatDevice(device_id=_PHONE, access=DeviceAccess.READ_WRITE)]
        )
        started = await one.engine.start_conversation()
        cookie_half, header_half = await _start_session(one)
        payload = (
            f'{{"conversation_id": "{started.id}", "message_id": "m-1", "text": "Hi."}}'
        ).encode()
        answer = await one.send(
            "POST /chat/message/write HTTP/1.1\nHost: {host}\n"
            f"Origin: {one.origin}\nContent-Type: application/json\n"
            f"Content-Length: {len(payload)}\nX-Assistant-Session: {header_half}\n"
            f"Cookie: assistant_session={cookie_half}",
            payload,
        )

    assert answer.status == 200, answer.body
    assert answer.payload["receipt"]["outcome"] == "recorded"
    (written,) = [arguments for name, arguments in one.engine.calls if name == "write_message"]
    message = written["message"]
    assert isinstance(message, UserMessage)
    assert message.device_id == _PHONE


async def test_the_transcript_carries_messages_and_markers(harness: Harness) -> None:
    """§5:2's properties for a message, and §5:12's marker — position, deleted, no text."""
    conversation = await _started(harness)
    for index, text in enumerate(("Book it.", "Which one?"), start=1):
        await harness.whole(
            "POST",
            "/chat/message/write",
            {"conversation_id": conversation, "message_id": f"m-{index}", "text": text},
        )
    await harness.engine.chat.append_message(
        conversation,
        NewMessage(author=MessageAuthor.ASSISTANT, text="Pinecrest, Friday.", replies_to=1),
    )
    await harness.engine.delete_message(conversation, position=2)

    status, body = await harness.whole(
        "POST", "/chat/transcript", {"conversation_id": conversation}
    )

    assert status == 200
    page = body["transcript"]
    assert page["conversation_id"] == conversation
    first, deleted, reply = page["entries"]
    assert set(first) == {
        "position",
        "deleted",
        "written_at",
        "author",
        "text",
        "replies_to",
        "options",
        "cut_off",
        "device_id",
        "message_id",
    }
    assert first["author"] == "user"
    assert first["device_id"] == _HUB
    assert deleted == {"position": 2, "deleted": True}
    assert reply["author"] == "assistant"
    assert reply["replies_to"] == 1
    assert reply["device_id"] is None
    assert page["as_of"] >= 1

    _, older = await harness.whole(
        "POST", "/chat/transcript", {"conversation_id": conversation, "before": 3, "limit": 1}
    )
    assert [one["position"] for one in older["transcript"]["entries"]] == [2]


async def test_the_transcript_of_a_conversation_that_is_gone_is_its_own_condition(
    harness: Harness,
) -> None:
    """``None`` from the surface is a different fact from a hub that declined."""
    status, body = await harness.whole("POST", "/chat/transcript", {"conversation_id": "c-none"})

    assert status == 404
    assert body == {"fault": "no-such-conversation"}


async def test_the_changes_after_a_cursor_are_every_kind_in_order(harness: Harness) -> None:
    """§5:10, §5:11: every change gets a sequence number, and one request catches up."""
    await harness.whole(
        "POST", "/chat/devices/set", {"devices": [{"device_id": _HUB, "access": "read_write"}]}
    )
    _, started = await harness.whole("POST", "/chat/start", {})
    conversation = started["conversation"]["id"]
    await harness.whole(
        "POST",
        "/chat/message/write",
        {"conversation_id": conversation, "message_id": "m-1", "text": "Hello."},
    )

    status, body = await harness.whole("POST", "/chat/changes", {"after": 0})

    assert status == 200
    kinds = [one["kind"] for one in body["changes"]]
    assert kinds == ["devices_changed", "conversation_started", "message_added"]
    seqs = [one["seq"] for one in body["changes"]]
    assert seqs == sorted(seqs)
    assert body["next_after"] == seqs[-1]
    devices, started_change, added = body["changes"]
    assert devices["conversation_id"] is None
    assert devices["devices"] == [{"device_id": _HUB, "access": "read_write"}]
    assert started_change["conversation_id"] == conversation
    assert added["message"]["text"] == "Hello."

    # A deletion reaches a device that already applied the message as its marker
    # (§5:12); the message's own change then carries nothing a later device could show.
    await harness.whole(
        "POST", "/chat/message/delete", {"conversation_id": conversation, "position": 1}
    )
    _, body = await harness.whole("POST", "/chat/changes", {"after": body["next_after"]})
    (deleted,) = body["changes"]
    assert deleted == {
        "kind": "message_deleted",
        "seq": deleted["seq"],
        "conversation_id": conversation,
        "position": 1,
    }

    await harness.whole("POST", "/chat/conversation/delete", {"conversation_id": conversation})
    _, later = await harness.whole("POST", "/chat/changes", {"after": body["next_after"]})
    (gone,) = later["changes"]
    assert gone == {
        "kind": "conversation_deleted",
        "seq": later["next_after"],
        "conversation_id": conversation,
    }
    _, caught_up = await harness.whole("POST", "/chat/changes", {"after": later["next_after"]})
    assert caught_up == {"changes": [], "next_after": later["next_after"]}


async def test_the_changes_read_narrows_to_the_conversations_named(harness: Harness) -> None:
    """``conversation_ids`` restricts the page, "my devices" beside it; ``[]`` names none."""
    conversation = await _started(harness)
    await harness.whole(
        "POST",
        "/chat/message/write",
        {"conversation_id": conversation, "message_id": "m-1", "text": "Hello."},
    )

    _, none = await harness.whole("POST", "/chat/changes", {"after": 0, "conversation_ids": []})

    assert [one["kind"] for one in none["changes"]] == ["devices_changed"]
    _, latest = await harness.whole("POST", "/chat/changes", {"after": 0})
    assert none["next_after"] == latest["next_after"]


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"after": -1},
        {"after": True},
        {"after": "3"},
        {"after": 0, "conversation_ids": "c-1"},
        {"after": 0, "conversation_ids": [1]},
        {"after": 0, "limit": -1},
    ],
)
async def test_a_changes_read_the_page_could_not_have_meant_is_refused_unrelayed(
    harness: Harness, payload: dict[str, Any]
) -> None:
    """The cursor is the browser's and has no default; nothing malformed is relayed."""
    status, body = await harness.whole("POST", "/chat/changes", payload)

    assert status == 400
    assert body == {"fault": "malformed-request"}
    assert harness.engine.calls == []


async def test_deleting_a_message_leaves_its_marker(harness: Harness) -> None:
    """§5:8, §5:9: deleting deletes that message alone; a second delete answers false."""
    conversation = await _started(harness)
    await harness.whole(
        "POST",
        "/chat/message/write",
        {"conversation_id": conversation, "message_id": "m-1", "text": "Hello."},
    )

    status, body = await harness.whole(
        "POST", "/chat/message/delete", {"conversation_id": conversation, "position": 1}
    )
    assert status == 200
    assert body == {"deleted": True}
    _, again = await harness.whole(
        "POST", "/chat/message/delete", {"conversation_id": conversation, "position": 1}
    )
    assert again == {"deleted": False}

    for position in (0, True, None, "1"):
        status, body = await harness.whole(
            "POST",
            "/chat/message/delete",
            {"conversation_id": conversation, "position": position},
        )
        assert status == 400, position


async def test_deleting_a_conversation_forgets_nothing(harness: Harness) -> None:
    """§2:3: the conversation and its transcript go; forgetting is a different act."""
    conversation = await _started(harness)

    status, body = await harness.whole(
        "POST", "/chat/conversation/delete", {"conversation_id": conversation}
    )

    assert status == 200
    assert body == {"deleted": True}
    assert "forget_conversation" not in [name for name, _ in harness.engine.calls]
    status, _ = await harness.whole("POST", "/chat/transcript", {"conversation_id": conversation})
    assert status == 404


async def test_a_conversations_devices_are_chosen_away_from_my_devices(
    harness: Harness,
) -> None:
    """§3:3: one conversation's set changes and "my devices" does not."""
    conversation = await _started(harness)

    status, body = await harness.whole(
        "POST",
        "/chat/conversation/devices/set",
        {"conversation_id": conversation, "devices": [{"device_id": "nTV", "access": "read"}]},
    )

    assert status == 200
    assert body == {"changed": True}
    _, digest = await harness.whole("POST", "/conversation", {"conversation_id": conversation})
    assert digest["conversation"]["devices"] == [{"device_id": "nTV", "access": "read"}]
    _, mine = await harness.whole("POST", "/chat/devices", {})
    assert mine["devices"] == [{"device_id": _HUB, "access": "read_write"}]

    status, body = await harness.whole(
        "POST",
        "/chat/conversation/devices/set",
        {"conversation_id": "c-none", "devices": []},
    )
    assert status == 404
    assert body == {"fault": "no-such-conversation"}


async def test_the_digest_carries_the_current_state(harness: Harness) -> None:
    """§8: "working…" and how the last activation ended, relayed and never derived."""
    conversation = await _started(harness)
    _, idle = await harness.whole("POST", "/conversation", {"conversation_id": conversation})
    assert idle["conversation"]["state"] == {
        "working": False,
        "activation_id": None,
        "last_ended": None,
    }

    held = harness.engine.conversation

    async def stated(conversation_id: str) -> Any:
        digest = await held(conversation_id)
        assert digest is not None
        return digest.model_copy(
            update={
                "state": ConversationState(
                    working=True,
                    activation_id="a-7",
                    last_ended=ActivationEnding.INTERRUPTED,
                )
            }
        )

    harness.engine.conversation = stated  # type: ignore[method-assign]
    _, working = await harness.whole("POST", "/conversation", {"conversation_id": conversation})

    assert working["conversation"]["state"] == {
        "working": True,
        "activation_id": "a-7",
        "last_ended": "interrupted",
    }
