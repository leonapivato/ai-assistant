"""The browser's notification review surface, end to end (ADR-0177 §10).

Five operations reach a browser here that did not before — ``notifications``,
``dismiss_notification``, ``forget_notification``, ``notification_preferences`` and
``set_notification_preferences``. ADR-0177 §1 admits them by name, §2 keeps the four
request classes, and §10 says what the surface owes once they are reachable.

**The one thing this file exists to hold apart is the notification *record* from a
*delivery*.** A browser watching ``/deliveries`` and holding a list it can dismiss
from is the first place both objects are on one screen, and ADR-0175 §10 named that
confusion as the reason the review surface was deferred to this milestone at all.

**Driven through a real socket** for ``test_gateway.py``'s reason, on
``test_gateway_streams``' own harness rather than a third copy of it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from test_gateway_streams import _harness

from ai_assistant.core.types import (
    ClassReach,
    DataTier,
    NotificationCandidate,
    NotificationPreferences,
    NotificationReach,
    QuietWindow,
)
from ai_assistant.interfaces.gateway.http import Request
from ai_assistant.interfaces.gateway.records import RequestClass
from ai_assistant.interfaces.gateway.server import _ASSISTANT_PATHS
from ai_assistant.testing import (
    FakeAssistantEngine,
    FakeNotificationOutbox,
    FakeNotificationStore,
)

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("hermetic_assistant_env")]

#: The instant the store, the gateway and every scripted value here agree on. It is
#: :class:`gateway_timing.Clock`'s own default reading, so a case that does not move
#: the clock has one instant rather than two that happen to be close.
_INSTANT = datetime(2026, 8, 21, 9, 0, tzinfo=UTC)

#: An earlier instant for the store, where a case needs a record admitted before the
#: gateway's own reading. Two clocks rather than one advanced, because the session the
#: harness mints expires on that same clock: a case that moved it far enough for a
#: record to perish would be asserting about a browser that had been logged out.
_EARLIER = _INSTANT - timedelta(hours=2)

#: Every path this lane adds, with the operation ADR-0177 §1 admits it for.
_ADDED: dict[str, str] = {
    "/notifications": "notifications",
    "/notification/dismiss": "dismiss_notification",
    "/notification/forget": "forget_notification",
    "/notification/preferences": "notification_preferences",
    "/notification/preferences/set": "set_notification_preferences",
}

#: The whole standing-settings value, as the shipped defaults hold it. Every member
#: is present because the write replaces rather than merges (ADR-0130 §6), so this is
#: also the smallest well-formed body the write accepts.
_DEFAULTS: dict[str, Any] = {
    "reaches": [],
    "quiet_windows": [],
    "interruption_budget": "3",
    "budget_window_microseconds": "86400000000",
}

#: One well-formed body per path, so a case can drive any of them without inventing
#: arguments at each site.
_WELL_FORMED: dict[str, dict[str, Any]] = {
    "/notifications": {},
    "/notification/dismiss": {"notification_id": "ntf-1"},
    "/notification/forget": {"notification_id": "ntf-1"},
    "/notification/preferences": {},
    "/notification/preferences/set": _DEFAULTS,
}


def _engine(at: datetime = _INSTANT) -> FakeAssistantEngine:
    """One engine whose notification store reads the clock this file fixes.

    The store and its outbox are replaced together: the outbox dismisses *through*
    the store when an entry departs (ADR-0131 §3b), so an outbox left pointing at the
    engine's original store would report a dismissal the review surface could not see.
    """
    engine = FakeAssistantEngine()
    store = FakeNotificationStore(now=lambda: at)
    engine.notification_store = store
    engine.notification_outbox = FakeNotificationOutbox(records=store, now=lambda: at)
    return engine


def _candidate(*, at: datetime = _INSTANT, **overrides: Any) -> NotificationCandidate:
    """One producer's proposal, on this file's instant unless a case moves it."""
    fields: dict[str, Any] = {
        "candidate_key": "key-1",
        "producer": "calendar",
        "notification_class": "upcoming_event",
        "summary": "Standup starts in ten minutes",
        "detail": "In the small room.",
        "noticed_at": at - timedelta(minutes=1),
        "confidence": 0.9,
        "sensitivity": DataTier.PERSONAL,
    }
    return NotificationCandidate(**(fields | overrides))


async def _hold(engine: FakeAssistantEngine, *, at: datetime = _INSTANT, **overrides: Any) -> str:
    """Admit one candidate and return the id of the record it wrote."""
    ruling = await engine.notification_store.admit(
        _candidate(at=at, **overrides), policy=engine.notification_policy
    )
    assert ruling.notification_id is not None
    return ruling.notification_id


def _named(engine: FakeAssistantEngine) -> list[str]:
    """Which operations this engine was asked for, in order."""
    return [name for name, _ in engine.calls]


def _request(path: str) -> Request:
    """One parsed POST at ``path``, for a classification that reads it alone."""
    return Request(method="POST", path=path, headers=(), body=b"{}")


def _clear(engine: FakeAssistantEngine) -> None:
    """Forget the calls seeding made, so a case reads only its own."""
    engine.calls.clear()


# --- ADR-0177 §1 and §2: the enumeration reaches the surface -----------------


def test_every_path_this_lane_adds_names_an_operation_the_adr_admits() -> None:
    """§1 admits the notification review five by name.

    Checked against the router rather than against a list in this file, so a path
    added here without an operation, or an operation without a path, fails at the
    join instead of being asserted true of a copy.
    """
    for path, operation in _ADDED.items():
        assert _ASSISTANT_PATHS[("POST", path)] == operation, path


def test_the_gateways_own_poll_is_not_one_of_the_five() -> None:
    """§1's second clause, bound unchanged by §10's first: ``next_notification`` "is
    the gateway's own poll, no browser request resolves to it, no browser argument
    reaches it, and it is not one of the thirty".

    Asserted here as well as on the router's whole enumeration because this is the
    lane that could most plausibly have added it: five operations named
    ``*_notification*`` arrive together, and the sixth is the one that must not.
    """
    assert "next_notification" not in set(_ASSISTANT_PATHS.values())


@pytest.mark.parametrize("path", sorted(_ADDED))
async def test_an_added_shape_asks_the_assistant_for_something(path: str) -> None:
    """ADR-0177 §2: every request §1 admits "asks the assistant for something" in
    ADR-0168 §6's own words "and is therefore ``assistant-request``".

    The four classes do not become five, and no rule is conditioned on which of the
    thirty an ``assistant-request`` names.
    """
    async with _harness() as one:
        assert one.gateway._classify(_request(path)) is RequestClass.ASSISTANT


@pytest.mark.parametrize("path", sorted(_ADDED))
async def test_an_added_shape_is_refused_without_a_session_and_reaches_nothing(
    path: str,
) -> None:
    """ADR-0168 §1's biconditional, in the direction that matters most.

    Each of these plainly asks the assistant for something and §3 plainly refuses it
    to a browser with no session, so the engine must not be reached.
    """
    async with _harness() as one:
        status, body = await one.whole("POST", path, _WELL_FORMED[path], admitted=False)

        assert status == 401
        assert body["fault"] == "no-live-session"
        assert one.engine.calls == []


# --- ADR-0130 §7: what the listing shows --------------------------------------


async def test_the_listing_carries_what_a_person_needs_in_order_to_act() -> None:
    """ADR-0130 §7 and ADR-0177 §10, with the command line as the precedent.

    The record's own id — which the two verbs take — the summary and detail ADR-0130
    §2 makes "the only free text… what the *user* would be shown", the class §6 tunes
    and the producer that noticed it, when it was noticed and when it perishes, and
    the ruling with the whole set of conditions it is waiting on.
    """
    engine = _engine()
    held = await _hold(engine, expires_at=_INSTANT + timedelta(hours=1))
    async with _harness(engine) as one:
        status, body = await one.whole("POST", "/notifications", {})

        assert status == 200
        assert body["notifications"] == [
            {
                "id": held,
                "notification_class": "upcoming_event",
                "producer": "calendar",
                "summary": "Standup starts in ten minutes",
                "detail": "In the small room.",
                "noticed_at": (_INSTANT - timedelta(minutes=1)).isoformat(),
                "expires_at": (_INSTANT + timedelta(hours=1)).isoformat(),
                "expired": False,
                "kind": "hold",
                "reason": "reach_interrupt",
                "failed": ["reach_interrupt"],
                "ruled_at": _INSTANT.isoformat(),
                "admitted_at": _INSTANT.isoformat(),
                "dismissed_at": None,
                "dropped_at": None,
            }
        ]


async def test_the_listing_carries_no_evidence_beside_the_ruling() -> None:
    """ADR-0130 §4 separates the evidence from the ruling, and ADR-0175 §12 records
    that ADR-0130 is unreached by the browser's arrival — the gateway re-judges no
    disposition.

    A page showing a producer's confidence beside a notification would be presenting
    the first as though it were the second, so the members that would let it do so do
    not cross. ``candidate_key`` is the store's duplicate key and ``reconsider_at``
    and ``retention`` are the reconsideration job's bookkeeping.
    """
    engine = _engine()
    await _hold(engine, goal_id="goal-1", references=("rec-1",))
    async with _harness(engine) as one:
        _, body = await one.whole("POST", "/notifications", {})

        for withheld in (
            "confidence",
            "sensitivity",
            "references",
            "goal_id",
            "candidate_key",
            "reconsider_at",
            "retention",
            "delivery_id",
        ):
            assert withheld not in body["notifications"][0], withheld


async def test_an_expired_record_is_still_enumerated_and_renders_as_expired() -> None:
    """ADR-0130 §7: expiry "ends interruptibility and actionability but deletes
    nothing, so an expired record is still enumerated and renders as expired".

    No field answers it — the record carries the instant and no verdict — so the
    predicate is the core type's own, asked at the reading this adapter supplies.
    """
    engine = _engine(_EARLIER)
    await _hold(engine, at=_EARLIER, expires_at=_EARLIER + timedelta(hours=1))
    async with _harness(engine) as one:
        status, body = await one.whole("POST", "/notifications", {})

        assert status == 200
        assert body["notifications"][0]["expires_at"] == (_EARLIER + timedelta(hours=1)).isoformat()
        assert body["notifications"][0]["expired"] is True


async def test_a_record_declaring_no_expiry_is_not_reported_as_expired() -> None:
    """The other half, and it is not the same claim.

    ADR-0130 §5 makes declaring an expiry "the whole of the escalation test": a
    candidate that commits to no moment is held and never interrupted, and it has not
    perished and never will. A reader folding "no expiry" into "expired" would label
    the ordinary case as the exceptional one.
    """
    engine = _engine(_EARLIER)
    await _hold(engine, at=_EARLIER)
    async with _harness(engine) as one:
        _, body = await one.whole("POST", "/notifications", {})

        assert body["notifications"][0]["expires_at"] is None
        assert body["notifications"][0]["expired"] is False


async def test_the_page_the_browser_asked_for_is_the_page_it_gets() -> None:
    """ADR-0177 §1: "every argument expressing what the user asked for is the
    browser's own — the gateway derives none of them, defaults none of them"."""
    engine = _engine()
    for index in range(3):
        await _hold(engine, candidate_key=f"key-{index}", summary=f"Thing {index}")
    _clear(engine)
    async with _harness(engine) as one:
        _, body = await one.whole("POST", "/notifications", {"limit": 1, "offset": 1})

        assert [one["summary"] for one in body["notifications"]] == ["Thing 1"]
        assert engine.calls == [("notifications", {"limit": 1, "offset": 1})]


async def test_a_paging_argument_out_of_range_is_refused_before_the_hub() -> None:
    """ADR-0085 §9's bound, refused "at its own parse boundary" by an adapter that
    lets a user supply one — which a browser is."""
    async with _harness(_engine()) as one:
        status, body = await one.whole("POST", "/notifications", {"limit": -1})

        assert status == 400
        assert body["fault"] == "malformed-request"
        assert one.engine.calls == []


# --- ADR-0177 §10: dismissal is not acknowledgement ---------------------------


async def test_a_dismissal_disposes_of_the_record_and_acknowledges_no_delivery() -> None:
    """§10's first clause: "what they operate on is the notification **record**…
    Nothing on this surface acknowledges, retires, withdraws or completes a
    **delivery**."

    The evidence is which operation was called: ``next_notification`` is the only
    method by which an acknowledgement crosses (ADR-0131 §1), it is the gateway's own
    poll, and a dismissal must not reach it.
    """
    engine = _engine()
    held = await _hold(engine)
    _clear(engine)
    async with _harness(engine) as one:
        status, body = await one.whole("POST", "/notification/dismiss", {"notification_id": held})

        assert status == 200
        assert body == {"dismissed": True}
        assert _named(engine) == ["dismiss_notification"]


async def test_a_dismissal_leaves_the_record_readable() -> None:
    """ADR-0130 §9: "A dismissal is not a deletion. The record stays readable and
    stays in the user's export; what ends is its actionability."

    So the listing still carries it, with the stamp that says what happened — which is
    what lets the page end the offer on the *hub's* fact rather than on this device's
    clock.
    """
    engine = _engine()
    held = await _hold(engine)
    async with _harness(engine) as one:
        await one.whole("POST", "/notification/dismiss", {"notification_id": held})
        _, body = await one.whole("POST", "/notifications", {})

        assert body["notifications"][0]["id"] == held
        assert body["notifications"][0]["dismissed_at"] == _INSTANT.isoformat()


async def test_dismissing_what_is_not_actionable_is_false_and_not_an_error() -> None:
    """The contract's own answer: ``False`` "where the id named nothing, or named one
    already dismissed, expired or dropped"."""
    async with _harness(_engine()) as one:
        status, body = await one.whole(
            "POST", "/notification/dismiss", {"notification_id": "nothing-by-that-name"}
        )

        assert status == 200
        assert body == {"dismissed": False}


async def test_a_forget_destroys_the_record_and_the_listing_stops_carrying_it() -> None:
    """ADR-0130 §9 and ADR-0004 §6's delete right, in the shape ``forget_question``
    takes: this is the surface the delete right reaches and the dismissal is not."""
    engine = _engine()
    held = await _hold(engine)
    _clear(engine)
    async with _harness(engine) as one:
        status, body = await one.whole("POST", "/notification/forget", {"notification_id": held})
        _, listed = await one.whole("POST", "/notifications", {})

        assert status == 200
        assert body == {"destroyed": True}
        assert listed["notifications"] == []
        assert _named(engine) == ["forget_notification", "notifications"]


async def test_an_id_reaches_the_hub_exactly_as_the_browser_sent_it() -> None:
    """ADR-0102 §2's rule generalised by ADR-0177 §1: the gateway strips, case-folds
    and normalises nothing.

    An id with an interior space is a well-formed identifier the store may hold, and
    one with surrounding space is a different string from the one it names — a
    gateway that trimmed would dismiss a record the browser did not point at, or
    refuse one it did.
    """
    engine = _Recording()
    async with _harness(engine) as one:
        await one.whole("POST", "/notification/forget", {"notification_id": " ntf-1 "})

        assert engine.raw == [" ntf-1 "]


@pytest.mark.parametrize("path", ["/notification/dismiss", "/notification/forget"])
async def test_an_act_without_an_id_is_refused_before_the_hub(path: str) -> None:
    """A missing member is refused rather than defaulted: there is no notification the
    gateway could pick on the user's behalf."""
    async with _harness(_engine()) as one:
        status, body = await one.whole("POST", path, {})

        assert status == 400
        assert body["fault"] == "malformed-request"
        assert one.engine.calls == []


# --- ADR-0130 §6 and ADR-0177 §10: the standing settings ----------------------


async def test_the_settings_answer_from_an_empty_store_on_the_first_day() -> None:
    """ADR-0130 §6: "An empty store is a working policy" — reach ``hold`` for every
    class including one no preference names, no quiet windows, and three
    interruptions per rolling twenty-four hours.

    So the tuning surface is reachable before there is any usage to learn from, which
    is what makes the arming chain completable at all.
    """
    async with _harness(_engine()) as one:
        status, body = await one.whole("POST", "/notification/preferences", {})

        assert status == 200
        assert body["preferences"] == _DEFAULTS


async def test_the_whole_value_crosses_so_a_browser_can_write_it_back() -> None:
    """ADR-0177 §10's fourth clause: ``set_notification_preferences`` "is a
    read-modify-write and the surface treats it as one: it sends the whole
    ``NotificationPreferences`` value it read".

    A member the read dropped would be a member the write cleared, silently — so
    every one the type carries is on this body, ``budget_window`` included, which is
    on no form the page offers.
    """
    engine = _engine()
    await engine.notification_store.set_preferences(
        NotificationPreferences(
            reaches=(
                ClassReach(notification_class="upcoming_event", reach=NotificationReach.INTERRUPT),
            ),
            quiet_windows=(QuietWindow(start=22 * 60, end=7 * 60),),
            interruption_budget=5,
            budget_window=timedelta(hours=12),
        )
    )
    async with _harness(engine) as one:
        _, body = await one.whole("POST", "/notification/preferences", {})

        assert body["preferences"] == {
            "reaches": [{"notification_class": "upcoming_event", "reach": "interrupt"}],
            "quiet_windows": [{"start": 1320, "end": 420}],
            "interruption_budget": "5",
            "budget_window_microseconds": "43200000000",
        }


async def test_a_write_relays_the_whole_value_and_renders_what_came_back() -> None:
    """§10's fourth clause again, in the direction that is easy to get wrong: the
    surface "renders what the call **returned** rather than what it sent, and states
    no preference state it has not read back".

    An act's outcome is a fact about that act; what stands is a fact only the hub can
    state — the same discipline §7 applies to a grant.
    """
    engine = _engine()
    asked = {
        "reaches": [{"notification_class": "upcoming_event", "reach": "interrupt"}],
        "quiet_windows": [{"start": 0, "end": 360}],
        "interruption_budget": "0",
        "budget_window_microseconds": "3600000000",
    }
    async with _harness(engine) as one:
        status, body = await one.whole("POST", "/notification/preferences/set", asked)

        assert status == 200
        assert body["preferences"] == asked
        assert _named(engine) == ["set_notification_preferences"]
        written = engine.calls[0][1]["preferences"]
        assert isinstance(written, NotificationPreferences)
        assert written.reaches[0].reach is NotificationReach.INTERRUPT
        assert written.quiet_windows[0].end == 360
        assert written.interruption_budget == 0
        assert written.budget_window == timedelta(hours=1)


async def test_a_budget_of_zero_is_written_rather_than_read_as_absent() -> None:
    """ADR-0130 §6: zero is "a legible 'never interrupt' rather than a defect".

    A reader that treated it as a missing member would refuse the one setting a user
    who wants no interruptions at all would reach for first.
    """
    engine = _engine()
    async with _harness(engine) as one:
        _, body = await one.whole(
            "POST", "/notification/preferences/set", _DEFAULTS | {"interruption_budget": "0"}
        )

        assert body["preferences"]["interruption_budget"] == "0"


@pytest.mark.parametrize("dropped", sorted(_DEFAULTS))
async def test_a_member_left_out_of_a_write_is_refused_rather_than_defaulted(
    dropped: str,
) -> None:
    """ADR-0130 §6: the write **replaces** what is held rather than merging into it.

    So a gateway that defaulted an absent member would clear a setting the browser
    never mentioned — every quiet window, or every reach the user has set — and would
    do it on a request that looked well-formed. ADR-0177 §1's "the gateway derives
    none of them, defaults none of them" is the same rule from the other side.
    """
    body = {name: value for name, value in _DEFAULTS.items() if name != dropped}
    async with _harness(_engine()) as one:
        status, answered = await one.whole("POST", "/notification/preferences/set", body)

        assert status == 400
        assert answered["fault"] == "malformed-request"
        assert one.engine.calls == []


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({"reaches": [{"notification_class": "x", "reach": "sometimes"}]}, id="reach"),
        pytest.param({"reaches": [{"reach": "hold"}]}, id="classless"),
        pytest.param({"reaches": ["upcoming_event"]}, id="not-a-row"),
        pytest.param({"reaches": {}}, id="not-a-list"),
        pytest.param(
            {
                "reaches": [
                    {"notification_class": "x", "reach": "off"},
                    {"notification_class": "x", "reach": "interrupt"},
                ]
            },
            id="twice-named",
        ),
        pytest.param({"quiet_windows": [{"start": 60, "end": 60}]}, id="no-extent"),
        pytest.param({"quiet_windows": [{"start": 60, "end": 1440}]}, id="past-midnight"),
        pytest.param({"quiet_windows": [{"start": 60}]}, id="half-a-window"),
        pytest.param({"interruption_budget": "-1"}, id="negative-budget"),
        pytest.param({"interruption_budget": 3}, id="numeric-budget"),
        pytest.param({"interruption_budget": str(2**63)}, id="budget-past-the-bound"),
        pytest.param({"interruption_budget": " 3"}, id="padded-budget"),
        pytest.param({"budget_window_microseconds": "0"}, id="empty-window"),
        pytest.param({"budget_window_microseconds": "-60"}, id="negative-window"),
        pytest.param({"budget_window_microseconds": "PT1H"}, id="spelled-window"),
        pytest.param({"budget_window_microseconds": 86400.0}, id="numeric-window"),
        pytest.param({"budget_window_microseconds": "9" * 20}, id="unholdable-window"),
        pytest.param({"budget_window_microseconds": "9" * 21}, id="past-the-digit-bound"),
    ],
)
async def test_a_value_that_will_not_construct_is_the_gateways_own_refusal(
    body: dict[str, Any],
) -> None:
    """A body that cannot become a ``NotificationPreferences`` leaves **no call to
    relay**, so it is refused here and named as this adapter's own.

    ``rejected`` is the name :func:`_relay_fault` gives a refusal the *hub* authored;
    answering with it would attribute this refusal to a hub that was never asked,
    which is the fact about the hub ADR-0168 §3 keeps out of a refusal body.

    Two of these are not type errors and are the reason the whole value is
    constructed rather than merely type-checked: two rows naming one class makes a
    class's ``off`` silently ambiguous, and a window whose endpoints are the same
    minute is unreadable as either "nothing" or "everything". Both are refused by the
    core type in every client (ADR-0085 §9), so the gateway could not relay one.
    The two members spelled as decimal strings refuse a **number** rather than
    coercing one, which is the losslessness rule holding at the door: accepting
    ``3`` for ``"3"`` would accept exactly the rounded value the spelling exists to
    prevent. The twenty-one-digit case is the length bound, which stops a request
    body asking for quadratic work, and the twenty-nine of nines is a duration
    ``timedelta`` cannot hold — an ``OverflowError`` that has to arrive as this
    refusal rather than as a fault of the process.
    """
    async with _harness(_engine()) as one:
        status, answered = await one.whole(
            "POST", "/notification/preferences/set", _DEFAULTS | body
        )

        assert status == 400
        assert answered["fault"] == "malformed-request"
        assert one.engine.calls == []


@pytest.mark.parametrize(
    ("budget", "window"),
    [
        pytest.param(2**53 + 1, timedelta(days=1), id="past-the-double"),
        pytest.param(2**63 - 1, timedelta(days=1), id="the-largest-budget"),
        pytest.param(3, timedelta(days=999_999_999, microseconds=1), id="the-longest-window"),
        pytest.param(3, timedelta(microseconds=1), id="the-shortest-window"),
    ],
)
async def test_a_value_no_double_holds_survives_being_read_and_written_back(
    budget: int, window: timedelta
) -> None:
    """ADR-0177 §10's fourth clause, at the values where a JSON number stops being
    exact.

    A browser reads a JSON number into an IEEE-754 double, so ``2**53 + 1`` comes back
    as ``2**53`` and a ``timedelta`` of a billion days loses its microsecond. Both are
    inside what ``NotificationPreferences`` admits, and both are members the page only
    holds so that it can hand them back — so a rounding here is a browser changing a
    setting on an edit that never named it. Spelled as decimal strings, they cross
    exactly, which is what this asserts in both directions.
    """
    engine = _engine()
    await engine.notification_store.set_preferences(
        NotificationPreferences(interruption_budget=budget, budget_window=window)
    )
    async with _harness(engine) as one:
        _, read = await one.whole("POST", "/notification/preferences", {})
        _, written = await one.whole("POST", "/notification/preferences/set", read["preferences"])

        assert read["preferences"]["interruption_budget"] == str(budget)
        assert written["preferences"] == read["preferences"]
        sent = engine.calls[-1][1]["preferences"]
        assert isinstance(sent, NotificationPreferences)
        assert sent.interruption_budget == budget
        assert sent.budget_window == window


async def test_a_window_that_crosses_midnight_is_expressed_directly() -> None:
    """ADR-0130 §6 and the type's own note: ``22:00`` to ``07:00`` "is the ordinary
    overnight case and is expressed directly rather than as two rows".

    The endpoints carry no zone and cannot: they are minutes since local midnight,
    read in ``Settings.timezone``, and an integer cannot smuggle a second zone in.
    """
    engine = _engine()
    async with _harness(engine) as one:
        _, body = await one.whole(
            "POST",
            "/notification/preferences/set",
            _DEFAULTS | {"quiet_windows": [{"start": 1320, "end": 420}]},
        )

        assert body["preferences"]["quiet_windows"] == [{"start": 1320, "end": 420}]
        written = engine.calls[0][1]["preferences"]
        assert isinstance(written, NotificationPreferences)
        assert written.quiet_windows[0].start == 1320


async def test_every_reach_the_vocabulary_carries_is_writable() -> None:
    """The three members of ``NotificationReach``, each written and read back.

    ``off`` is the one worth naming: ADR-0130 §6 has it reach "every actionable held
    record of that class", so a surface that could not send it would leave "never
    tell me this" unreachable from a browser.
    """
    engine = _engine()
    async with _harness(engine) as one:
        for reach in NotificationReach:
            _, body = await one.whole(
                "POST",
                "/notification/preferences/set",
                _DEFAULTS
                | {"reaches": [{"notification_class": "upcoming_event", "reach": reach.value}]},
            )

            assert body["preferences"]["reaches"] == [
                {"notification_class": "upcoming_event", "reach": reach.value}
            ]


@pytest.mark.parametrize("path", sorted(_ADDED))
async def test_no_review_operation_reaches_the_gateways_own_poll(path: str) -> None:
    """ADR-0177 §10's first clause, asserted over the whole surface at once.

    ``next_notification`` is "the one method by which a notification crosses the
    wire" as a *delivery* (ADR-0131 §1), and its ``acknowledging`` argument is the
    only acknowledgement there is. So "nothing on this surface acknowledges, retires,
    withdraws or completes a delivery" is checkable exactly here: no review operation
    may reach that method, whatever it does to the record.

    The gateway's own poll is unaffected and is not what this asserts about — it runs
    on the delivery stream ADR-0175 §4 establishes, and this lane touches neither.
    """
    engine = _engine()
    held = await _hold(engine)
    _clear(engine)
    body = _WELL_FORMED[path]
    if "notification_id" in body:
        body = body | {"notification_id": held}
    async with _harness(engine) as one:
        status, _ = await one.whole("POST", path, body)

        assert status == 200
        assert "next_notification" not in _named(engine)


def test_the_review_surface_and_the_delivery_stream_are_different_shapes() -> None:
    """ADR-0177 §10 restated as a property of the router.

    The stream is a ``GET`` carrying no argument, because "the poll is the gateway's
    own and takes none from a browser"; the five are ``POST``s carrying the record's
    id. A lane that had served a review operation on the stream's shape would have
    put the two objects on one door, which is the confusion ADR-0175 §10 deferred this
    surface in order to avoid.
    """
    assert _ASSISTANT_PATHS[("GET", "/deliveries")] == "delivery-stream"
    for path, operation in _ADDED.items():
        assert ("GET", path) not in _ASSISTANT_PATHS, path
        assert _ASSISTANT_PATHS[("POST", path)] == operation


class _Recording(FakeAssistantEngine):
    """An engine that records the id it was handed **before** anything validates it.

    ``FakeAssistantEngine.calls`` holds the checked value, because every conforming
    implementation runs ``identifier()`` first (ADR-0085 §9) — so a gateway that
    trimmed and one that did not would leave the same trail there. This subclass is
    the only place the raw argument is observable.
    """

    def __init__(self) -> None:
        """Start with nothing recorded."""
        super().__init__()
        self.raw: list[str] = []

    async def forget_notification(self, notification_id: str) -> bool:
        """Record what arrived, then answer as the contract does."""
        self.raw.append(notification_id)
        return False
