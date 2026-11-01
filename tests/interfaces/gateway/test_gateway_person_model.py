"""The person model's eight members, reached from a browser (ADR-0338 §8:1-§8:3).

Driven through a real socket for ``test_gateway.py``'s reason: what is under test is a
request the browser makes and the body it renders, and the router, the door and the
admission all sit between the two. The engine behind it is the canonical fake with its
person model switched on over the shared suite's stores (``person_seed``), so each
answer here is the one the engine's contract holds the fake to.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

import pytest
from person_seed import ended, fact, field_suggestion, hold, outside, pin_suggestion, switch_on
from test_gateway_streams import _harness

from ai_assistant.core.errors import DeviceRefusal, DeviceRefusedError
from ai_assistant.core.types import (
    OWNER_PERSON_ID,
    PersonActHow,
    PersonModelAct,
    PersonModelEdit,
    PersonModelList,
    ProfileField,
)
from ai_assistant.interfaces.gateway.http import Request
from ai_assistant.interfaces.gateway.records import RequestClass
from ai_assistant.interfaces.gateway.server import _ASSISTANT_PATHS
from ai_assistant.testing import FakeAssistantEngine

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.core.types import NonBlankEncodableText, PersonModelView

pytestmark = pytest.mark.integration

#: Every path this lane adds, with the member of ADR-0338 §8:1 it reaches.
_ADDED: Final[dict[str, str]] = {
    "/person": "person_model",
    "/person/changes": "profile_changes",
    "/person/field/set": "set_profile_field",
    "/person/pin": "pin_memory",
    "/person/unpin": "unpin_memory",
    "/person/style-mark/remove": "remove_style_mark",
    "/person/suggestion/accept": "accept_person_suggestion",
    "/person/suggestion/dismiss": "dismiss_person_suggestion",
}

#: One well-formed body per path, every value the browser's own (ADR-0177 §1).
_WELL_FORMED: Final[dict[str, dict[str, Any]]] = {
    "/person": {"person_id": OWNER_PERSON_ID},
    "/person/changes": {"person_id": OWNER_PERSON_ID},
    "/person/field/set": {"person_id": OWNER_PERSON_ID, "field": "name", "value": "Robin"},
    "/person/pin": {"person_id": OWNER_PERSON_ID, "memory_id": "m:diet"},
    "/person/unpin": {"person_id": OWNER_PERSON_ID, "memory_id": "m:diet"},
    "/person/style-mark/remove": {"person_id": OWNER_PERSON_ID, "mark_id": "mark:1"},
    "/person/suggestion/accept": {"person_id": OWNER_PERSON_ID, "suggestion_id": "s:1"},
    "/person/suggestion/dismiss": {"person_id": OWNER_PERSON_ID, "suggestion_id": "s:1"},
}

_PANEL: Final = PersonModelAct(how=PersonActHow.PANEL, by=OWNER_PERSON_ID)


def _request(path: str) -> Request:
    return Request(method="POST", path=path, headers=(), body=b"{}")


def _named(engine: FakeAssistantEngine) -> list[str]:
    return [name for name, _ in engine.calls]


# --- the enumeration ----------------------------------------------------------


def test_every_path_names_the_member_adr_0338_s8_1_adds() -> None:
    """One path per member, joined against the router rather than a copy of it."""
    for path, operation in _ADDED.items():
        assert _ASSISTANT_PATHS[("POST", path)] == operation, path
    assert {operation for _, operation in _ASSISTANT_PATHS.items()} >= set(_ADDED.values())


@pytest.mark.parametrize("path", sorted(_ADDED))
async def test_each_path_asks_the_assistant_and_is_refused_without_a_session(path: str) -> None:
    """ADR-0177 §2 and ADR-0168 §1: an assistant request, refused before any session."""
    async with _harness() as one:
        assert one.gateway._classify(_request(path)) is RequestClass.ASSISTANT
        status, body = await one.whole("POST", path, _WELL_FORMED[path], admitted=False)

        assert status == 401
        assert body["fault"] == "no-live-session"
        assert one.engine.calls == []


@pytest.mark.parametrize("path", sorted(_ADDED))
async def test_each_path_needs_the_persons_id_and_reaches_nothing_without_it(path: str) -> None:
    """The person is the browser's to name; the gateway supplies none of its own."""
    async with _harness() as one:
        payload = {name: value for name, value in _WELL_FORMED[path].items() if name != "person_id"}
        status, body = await one.whole("POST", path, payload)

        assert status == 400
        assert body["fault"] == "malformed-request"
        assert one.engine.calls == []


# --- the switch (§11:2) ---------------------------------------------------------


@pytest.mark.parametrize("path", sorted(_ADDED))
async def test_a_hub_with_no_person_model_answers_off_and_never_a_fault(path: str) -> None:
    """``PersonModelOffError`` is a state, so the page shows "not switched on", never an
    error: every member answers ``{"off": true}``, the request having reached the hub."""
    async with _harness() as one:
        status, body = await one.whole("POST", path, _WELL_FORMED[path])

        assert (status, body) == (200, {"off": True})
        assert _named(one.engine) == [_ADDED[path]]


# --- the read ------------------------------------------------------------------


async def test_the_read_carries_every_list_each_entry_worded_beside_its_controls_id() -> None:
    """§8:1: the fields, the slot with its fill, what it left out and why, the pins no
    longer current, the style marks and the suggestions; each entry with its wording."""
    engine = FakeAssistantEngine()
    people, memory = switch_on(engine, budget_chars=30)
    await hold(
        engine,
        memory,
        fact("m:diet", "Eats no meat."),
        fact("m:brief", "Short answers, please."),
        outside("m:out", "The shop says Robin likes jazz."),
        ended("m:old", "Lives in Porto.", successor=None),
    )
    await engine.set_profile_field(OWNER_PERSON_ID, field=ProfileField.NAME, value="Robin")
    await engine.pin_memory(OWNER_PERSON_ID, memory_id="m:diet")
    await people.add_pin(OWNER_PERSON_ID, "m:out", act=_PANEL)
    await people.add_pin(OWNER_PERSON_ID, "m:old", act=_PANEL)
    mark = await people.add_style_mark(OWNER_PERSON_ID, "m:brief")
    field = await people.record_suggestion(
        OWNER_PERSON_ID, field_suggestion(ProfileField.LANGUAGE, "Português")
    )
    pin = await people.record_suggestion(OWNER_PERSON_ID, pin_suggestion("m:brief"))

    async with _harness(engine) as one:
        status, body = await one.whole("POST", "/person", {"person_id": OWNER_PERSON_ID})

    assert status == 200
    model = body["person_model"]
    assert model["person_id"] == OWNER_PERSON_ID
    assert model["profile"] == {
        "name": "Robin",
        "address": None,
        "assistant_name": None,
        "time_zone": None,
        "language": None,
    }
    assert model["kept"] == [{"memory_id": "m:diet", "content": "Eats no meat.", "pinned": True}]
    assert (model["kept_total"], model["kept_chars"], model["budget_chars"]) == (1, 13, 30)
    assert model["left_out"] == [
        {
            "memory_id": "m:out",
            "content": "The shop says Robin likes jazz.",
            "pinned": True,
            "reason": "outside_content",
        },
        {
            "memory_id": "m:brief",
            "content": "Short answers, please.",
            "pinned": False,
            "reason": "budget",
        },
    ]
    assert [(one["memory_id"], one["content"]) for one in model["no_longer_current"]] == [
        ("m:old", "Lives in Porto.")
    ]
    assert model["no_longer_current_total"] == 1
    assert [(one["mark_id"], one["shows"], one["content"]) for one in model["style_marks"]] == [
        (mark.record_id, "m:brief", "Short answers, please.")
    ]
    suggestions = {one["suggestion_id"]: one for one in model["suggestions"]}
    assert suggestions[field.record_id] | {"recorded_at": None} == {
        "suggestion_id": field.record_id,
        "kind": "field",
        "field": "language",
        "value": "Português",
        "memory_id": None,
        "content": None,
        "rests_on_outside_content": False,
        "recorded_at": None,
    }
    assert suggestions[pin.record_id]["kind"] == "pin"
    assert suggestions[pin.record_id]["content"] == "Short answers, please."
    assert model["suggestions_total"] == 2


async def test_the_read_relays_the_lists_and_the_page_it_was_asked_for() -> None:
    """The selector and the page are the browser's own, passed through unchanged."""
    engine = FakeAssistantEngine()
    switch_on(engine)

    async with _harness(engine) as one:
        status, _ = await one.whole(
            "POST",
            "/person",
            {"person_id": OWNER_PERSON_ID, "lists": ["kept"], "limit": 3, "offset": 6},
        )
        _, absent = await one.whole("POST", "/person", {"person_id": OWNER_PERSON_ID})

    assert status == 200
    asked = [arguments for name, arguments in engine.calls if name == "person_model"]
    assert asked[0]["lists"] == (PersonModelList.KEPT,)
    assert (asked[0]["limit"], asked[0]["offset"]) == (3, 6)
    assert asked[1]["lists"] is None
    assert absent["person_model"] is not None


@pytest.mark.parametrize("lists", [["kept", "nonsense"], "kept", [1]])
async def test_a_selector_naming_no_list_is_refused_before_the_hub(lists: object) -> None:
    async with _harness() as one:
        status, body = await one.whole(
            "POST", "/person", {"person_id": OWNER_PERSON_ID, "lists": lists}
        )

        assert (status, body["fault"]) == (400, "malformed-request")
        assert one.engine.calls == []


async def test_a_person_the_hub_does_not_hold_reads_as_null() -> None:
    engine = FakeAssistantEngine()
    switch_on(engine)

    async with _harness(engine) as one:
        status, body = await one.whole("POST", "/person", {"person_id": "person:nobody"})

    assert (status, body) == (200, {"person_model": None})


async def test_the_change_log_is_read_a_page_at_a_time_most_recent_first() -> None:
    """§3:5: the field, the old value, the new, when and how."""
    engine = FakeAssistantEngine()
    switch_on(engine)
    await engine.set_profile_field(OWNER_PERSON_ID, field=ProfileField.NAME, value="Rob")
    await engine.set_profile_field(OWNER_PERSON_ID, field=ProfileField.NAME, value="Robin")

    async with _harness(engine) as one:
        _, first = await one.whole(
            "POST", "/person/changes", {"person_id": OWNER_PERSON_ID, "limit": 1}
        )
        _, second = await one.whole(
            "POST", "/person/changes", {"person_id": OWNER_PERSON_ID, "limit": 1, "offset": 1}
        )

    assert [(one["field"], one["old"], one["new"], one["how"]) for one in first["changes"]] == [
        ("name", "Rob", "Robin", "panel")
    ]
    assert [(one["old"], one["new"]) for one in second["changes"]] == [(None, "Rob")]
    assert [one["request"] for one in first["changes"] + second["changes"]] == [None, None]


async def test_a_change_made_by_a_yes_on_a_card_names_its_request() -> None:
    """ADR-0362 §2:1: the request crosses for the log to name; the episode does not."""
    engine = FakeAssistantEngine()
    people, _ = switch_on(engine)
    card = PersonModelAct(
        how=PersonActHow.APPROVAL,
        by=OWNER_PERSON_ID,
        request="approval:938d954a",
        episode_id="episode:approval",
    )
    await people.set_field(OWNER_PERSON_ID, ProfileField.ADDRESS, "Test19", act=card)

    async with _harness(engine) as one:
        _, body = await one.whole("POST", "/person/changes", {"person_id": OWNER_PERSON_ID})

    assert body["changes"] == [
        {
            "field": "address",
            "old": None,
            "new": "Test19",
            "at": body["changes"][0]["at"],
            "how": "approval",
            "request": "approval:938d954a",
        }
    ]


# --- the writes ----------------------------------------------------------------


async def test_a_field_is_set_and_cleared_by_an_absent_or_null_value() -> None:
    engine = FakeAssistantEngine()
    people, _ = switch_on(engine)

    async with _harness(engine) as one:
        _, set_ = await one.whole("POST", "/person/field/set", _WELL_FORMED["/person/field/set"])
        held = await people.read(OWNER_PERSON_ID)
        _, cleared = await one.whole(
            "POST", "/person/field/set", {"person_id": OWNER_PERSON_ID, "field": "name"}
        )
        _, again = await one.whole(
            "POST",
            "/person/field/set",
            {"person_id": OWNER_PERSON_ID, "field": "name", "value": None},
        )

    assert held is not None
    assert held.profile.name == "Robin"
    assert set_["edit"] == {
        "write": {"kind": "written", "record_id": None, "refusal": None, "reason": None},
        "refused": None,
    }
    assert cleared["edit"]["write"]["kind"] == "written"
    assert again["edit"]["write"]["kind"] == "unchanged"
    after = await people.read(OWNER_PERSON_ID)
    assert after is not None
    assert after.profile.name is None


@pytest.mark.parametrize(
    "payload",
    [
        {"person_id": OWNER_PERSON_ID, "field": "name", "value": 7},
        {"person_id": OWNER_PERSON_ID, "field": "name", "value": ["Robin"]},
        {"person_id": OWNER_PERSON_ID, "field": "pronouns", "value": "they"},
        {"person_id": OWNER_PERSON_ID, "value": "Robin"},
    ],
    ids=["number", "list", "no-such-field", "no-field"],
)
async def test_a_value_that_is_not_text_is_refused_and_never_taken_for_a_clear(
    payload: dict[str, Any],
) -> None:
    """A clear is ``None`` alone: a number must not empty a field (§3:2's caller)."""
    engine = FakeAssistantEngine()
    switch_on(engine)
    await engine.set_profile_field(OWNER_PERSON_ID, field=ProfileField.NAME, value="Robin")
    engine.calls.clear()

    async with _harness(engine) as one:
        status, body = await one.whole("POST", "/person/field/set", payload)

    assert (status, body["fault"]) == (400, "malformed-request")
    assert engine.calls == []


async def test_a_zone_zoneinfo_does_not_resolve_is_refused_in_the_edit_with_its_reason() -> None:
    """§3:2: refused, nothing written, and the code-owned reason crosses for the page."""
    engine = FakeAssistantEngine()
    switch_on(engine)

    async with _harness(engine) as one:
        status, body = await one.whole(
            "POST",
            "/person/field/set",
            {"person_id": OWNER_PERSON_ID, "field": "time_zone", "value": "Mars/Olympus"},
        )

    assert status == 200
    write = body["edit"]["write"]
    assert (write["kind"], write["refusal"]) == ("refused", "invalid_value")
    assert isinstance(write["reason"], str)
    assert write["reason"]


async def test_a_pin_is_written_and_its_refusals_cross_before_any_write() -> None:
    """§4:2 and §6:3: a memory not current, and one past the budget, are refused."""
    engine = FakeAssistantEngine()
    people, memory = switch_on(engine, budget_chars=20)
    await hold(
        engine,
        memory,
        fact("m:diet", "Eats no meat."),
        fact("m:long", "A wording longer than the budget."),
        ended("m:old", "Lives in Porto.", successor=None),
    )

    async with _harness(engine) as one:
        _, pinned = await one.whole("POST", "/person/pin", _WELL_FORMED["/person/pin"])
        _, again = await one.whole("POST", "/person/pin", _WELL_FORMED["/person/pin"])
        _, over = await one.whole(
            "POST", "/person/pin", {"person_id": OWNER_PERSON_ID, "memory_id": "m:long"}
        )
        _, stale = await one.whole(
            "POST", "/person/pin", {"person_id": OWNER_PERSON_ID, "memory_id": "m:old"}
        )

    assert pinned["edit"]["write"]["kind"] == "written"
    assert pinned["edit"]["write"]["record_id"]
    assert again["edit"]["write"]["kind"] == "unchanged"
    assert over["edit"] == {"write": None, "refused": "over_budget"}
    assert stale["edit"] == {"write": None, "refused": "not_current"}
    held = await people.read(OWNER_PERSON_ID)
    assert held is not None
    assert [pin.memory_id for pin in held.standing_pins] == ["m:diet"]


async def test_an_unpin_erases_nothing_and_says_when_there_was_no_pin() -> None:
    engine = FakeAssistantEngine()
    people, memory = switch_on(engine)
    await hold(engine, memory, fact("m:diet", "Eats no meat."))
    await engine.pin_memory(OWNER_PERSON_ID, memory_id="m:diet")

    async with _harness(engine) as one:
        _, unpinned = await one.whole("POST", "/person/unpin", _WELL_FORMED["/person/unpin"])
        _, again = await one.whole("POST", "/person/unpin", _WELL_FORMED["/person/unpin"])

    assert unpinned["edit"]["write"]["kind"] == "written"
    assert again["edit"]["write"]["kind"] == "unchanged"
    assert await memory.get("m:diet") is not None
    held = await people.read(OWNER_PERSON_ID)
    assert held is not None
    assert held.standing_pins == ()


async def test_a_style_mark_is_removed_by_the_id_the_read_gave_it() -> None:
    engine = FakeAssistantEngine()
    people, memory = switch_on(engine)
    await hold(engine, memory, fact("m:brief", "Short answers."))
    mark = await people.add_style_mark(OWNER_PERSON_ID, "m:brief")
    assert mark.record_id is not None

    async with _harness(engine) as one:
        _, removed = await one.whole(
            "POST",
            "/person/style-mark/remove",
            {"person_id": OWNER_PERSON_ID, "mark_id": mark.record_id},
        )

    assert removed["edit"]["write"]["kind"] == "written"
    held = await people.read(OWNER_PERSON_ID)
    assert held is not None
    assert held.standing_marks == ()


async def test_a_suggestion_is_accepted_or_dismissed_by_its_id() -> None:
    """§8:8: a field takes its value; §9:2: a dismissed one is decided for good."""
    engine = FakeAssistantEngine()
    people, _ = switch_on(engine)
    taken = await people.record_suggestion(
        OWNER_PERSON_ID, field_suggestion(ProfileField.LANGUAGE, "Português")
    )
    declined = await people.record_suggestion(
        OWNER_PERSON_ID, field_suggestion(ProfileField.ADDRESS, "Rob")
    )

    async with _harness(engine) as one:
        _, accepted = await one.whole(
            "POST",
            "/person/suggestion/accept",
            {"person_id": OWNER_PERSON_ID, "suggestion_id": taken.record_id},
        )
        _, dismissed = await one.whole(
            "POST",
            "/person/suggestion/dismiss",
            {"person_id": OWNER_PERSON_ID, "suggestion_id": declined.record_id},
        )
        _, twice = await one.whole(
            "POST",
            "/person/suggestion/dismiss",
            {"person_id": OWNER_PERSON_ID, "suggestion_id": declined.record_id},
        )

    assert accepted["edit"]["write"]["kind"] == "written"
    assert dismissed["edit"]["write"]["kind"] == "written"
    assert twice["edit"]["write"]["refusal"] == "already_decided"
    held = await people.read(OWNER_PERSON_ID)
    assert held is not None
    assert held.profile.language == "Português"
    assert held.profile.address is None


# --- §8:3: shown only to the person and the owner --------------------------------


class _RefusingDevice(FakeAssistantEngine):
    """A hub that refuses this device the person model, as the route table's command
    row refuses a device without the commands role (ADR-0298 §5:6)."""

    async def person_model(
        self,
        person_id: NonBlankEncodableText,
        *,
        lists: Sequence[PersonModelList] | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> PersonModelView | None:
        msg = "the person model needs the commands role"
        raise DeviceRefusedError(msg, reason=DeviceRefusal.NOT_ALLOWED)

    async def pin_memory(
        self, person_id: NonBlankEncodableText, *, memory_id: NonBlankEncodableText
    ) -> PersonModelEdit:
        msg = "the person model needs the commands role"
        raise DeviceRefusedError(msg, reason=DeviceRefusal.NOT_ALLOWED)


@pytest.mark.parametrize("path", ["/person", "/person/pin"])
async def test_the_hubs_refusal_for_the_device_is_relayed_as_every_other(path: str) -> None:
    """§8:3 is the hub's route table's; the gateway adds no rule and relays its answer."""
    async with _harness(_RefusingDevice()) as one:
        status, body = await one.whole("POST", path, _WELL_FORMED[path])

    assert (status, body["fault"]) == (422, "device-not-allowed")
