"""The browser's control surface end to end (ADR-0177).

The grant surface and the belief surface reach a browser here. ADR-0177 §1 admits
them by name; §2 keeps the four request classes; §5, §6 and §7 say what the surfaces
owe once they are reachable. ``observe``, which this lane added beside them, left the
surface with ADR-0285 §6, and the deferred-question surface left with its panel
(ADR-0309 §5).

**Driven through a real socket** for ``test_gateway.py``'s reason: what is under
test is a request the browser makes and a body it renders, and the router, the door
and the admission all sit between the two.

The harness is ``test_gateway_streams``' own rather than a third copy of it — the
gateway it binds and the session it mints are the same in either file, and a copy
would be one more place for the two to drift apart.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Final

import pytest
from test_gateway_streams import _harness

from ai_assistant.core.errors import GrantError, UngrantableSourceError
from ai_assistant.core.types import (
    Attestation,
    Belief,
    BeliefBand,
    GrantScope,
    ReportedExtent,
    belief_view,
)
from ai_assistant.interfaces.gateway.http import Request
from ai_assistant.interfaces.gateway.records import RequestClass
from ai_assistant.interfaces.gateway.server import _ASSISTANT_PATHS
from ai_assistant.testing import FakeAssistantEngine
from ai_assistant.testing.memories import memory, remembered_support
from ai_assistant.wire.errors import HubUnavailableError

if TYPE_CHECKING:
    from ai_assistant.core.types import Identifier, NonBlankEncodableText, SourceGrant

pytestmark = pytest.mark.integration

#: The instant every scripted value here is stamped with. Fixed rather than read
#: from a clock: nothing here turns on time, and a wall-clock reading would be one
#: more thing a failure could be about.
_INSTANT = datetime(2026, 1, 2, 15, 0, tzinfo=UTC)

#: Every path this lane adds, with the operation ADR-0177 §1 admits it for. Written
#: down once so the cases below read against the ADR rather than against each other.
_ADDED: dict[str, str] = {
    "/sources": "grantable_sources",
    "/grant": "grant",
    "/revoke": "revoke",
    "/grants/recent": "recent_grants",
    "/grants/standing": "standing_grants",
    "/beliefs": "beliefs",
    "/belief": "belief",
    "/belief/forget": "forget",
}

#: One well-formed body per path, so a case can drive any of them without inventing
#: arguments at each site. Every value here is the **browser's own**: ADR-0177 §1
#: requires that "every argument expressing what the user asked for is the browser's
#: own — the gateway derives none of them, defaults none of them".
_WELL_FORMED: dict[str, dict[str, Any]] = {
    "/sources": {},
    "/grant": {"source": "calendar", "scope": ["notify"]},
    "/revoke": {"source": "calendar"},
    "/grants/recent": {},
    "/grants/standing": {},
    "/beliefs": {},
    "/belief": {"record_id": "rec-1"},
    "/belief/forget": {"record_id": "rec-1"},
}


def _named(engine: FakeAssistantEngine) -> list[str]:
    """Which operations this engine was asked for, in order."""
    return [name for name, _ in engine.calls]


# --- ADR-0177 §1: the enumeration reaches the surface ------------------------


def test_every_path_this_lane_adds_names_an_operation_the_adr_admits() -> None:
    """§1 admits twenty-five further operations "and no others".

    Checked against the router rather than against a list in this file, so a path
    added here without an operation, or an operation without a path, fails at the
    join instead of being asserted true of a copy.
    """
    for path, operation in _ADDED.items():
        assert _ASSISTANT_PATHS[("POST", path)] == operation, path


@pytest.mark.parametrize("path", sorted(_ADDED))
async def test_an_added_shape_asks_the_assistant_for_something(path: str) -> None:
    """ADR-0177 §2: every request §1 admits "asks the assistant for something" in
    ADR-0168 §6's own words "and is therefore ``assistant-request``".

    The four classes do not become five, and no rule is conditioned on which of the
    thirty an ``assistant-request`` names — which is why this is asserted once over
    every added path rather than argued per surface.
    """
    async with _harness() as one:
        assert one.gateway._classify(_request(path)) is RequestClass.ASSISTANT


@pytest.mark.parametrize("path", sorted(_ADDED))
async def test_an_added_shape_is_refused_without_a_session_and_reaches_nothing(
    path: str,
) -> None:
    """ADR-0168 §1's biconditional, in the direction that matters most.

    Each of these plainly asks the assistant for something and §3 plainly refuses it
    to a browser with no session, so the engine must not be reached. ADR-0177 §1's
    fourth clause is that biconditional restated for the twenty-five, and this is
    where it holds or does not.
    """
    async with _harness() as one:
        status, body = await one.whole("POST", path, _WELL_FORMED[path], admitted=False)

        assert status == 401
        assert body["fault"] == "no-live-session"
        assert one.engine.calls == []


# --- ADR-0177 §6: the grant surface ------------------------------------------


async def test_the_sources_answer_carries_the_location_a_grant_must_disclose() -> None:
    """ADR-0102 §6 and ADR-0139 §5: "a client renders each ``location`` and takes an
    explicit act from the user before it sends ``grant``, and a client that cannot
    show the user the location does not send ``grant``".

    So the location has to cross. It comes to rest nowhere — it is on this response
    and on no stored record (ADR-0097 §9a) — and the point of carrying it is that the
    front end can meet the disclosure obligation at all.
    """
    engine = FakeAssistantEngine()
    engine.hold_source("calendar", location="/home/owner/calendar.ics")
    engine.hold_source("notes")
    async with _harness(engine) as one:
        status, body = await one.whole("POST", "/sources", {})

        assert status == 200
        assert body["sources"] == [
            {"source": "calendar", "location": "/home/owner/calendar.ics", "live": None},
            {"source": "notes", "location": None, "live": None},
        ]


async def test_a_sources_entry_renders_exactly_the_uses_its_live_grant_names() -> None:
    """ADR-0139 §3's third clause and ADR-0177 §6's second and third.

    "Where it renders an existing grant, it renders exactly the uses that grant
    names" — nothing added, nothing dropped — and the members the grant leaves out
    are not carried "in any form". A view that padded the tuple to three members
    would have made the front end's only option the failure §6 names.
    """
    engine = FakeAssistantEngine()
    engine.hold_source("calendar", location="/home/owner/calendar.ics")
    engine.hold_grant("calendar", scope=(GrantScope.NOTIFY,))
    async with _harness(engine) as one:
        _, body = await one.whole("POST", "/sources", {})

        assert body["sources"][0]["live"]["scope"] == ["notify"]


async def test_a_grant_relays_the_source_verbatim_and_normalises_nothing() -> None:
    """ADR-0102 §2: "**No implementation may strip, case-fold or otherwise normalise
    ``source`` at any point before it is compared.**"

    A gateway that trimmed would admit a call the in-process engine refuses, which is
    the normalisation-below-the-comparison failure that clause is written against —
    and it would do it one layer further out than the wire annotation §2 is about.
    """
    engine = FakeAssistantEngine()
    engine.hold_source("calendar", location="/somewhere")
    async with _harness(engine) as one:
        status, body = await one.whole(
            "POST", "/grant", {"source": " calendar ", "scope": ["notify"]}
        )

        assert status == 422
        assert body["fault"] == "assistant-declined"
        assert engine.calls == [("grant", {"source": " calendar ", "scope": (GrantScope.NOTIFY,)})]


async def test_a_grant_naming_ingest_is_the_hub_s_refusal_and_records_nothing() -> None:
    """ADR-0294 §4: a new grant may not name ``INGEST``, and the gateway relays the refusal.

    The page offers no box for it, but a request is not a page. The gateway decides
    no scope rule of its own — empty and duplicated are the promoted surface's to
    refuse, and so is this — so the request reaches ``grant``, which refuses it
    locally with a ``ValueError`` and records nothing. That is a malformed request
    rather than a hub decision, so the browser is told it was rejected, with the
    refusal's own sentence.
    """
    engine = FakeAssistantEngine()
    engine.hold_source("calendar", location="/somewhere")
    async with _harness(engine) as one:
        status, body = await one.whole(
            "POST", "/grant", {"source": "calendar", "scope": ["notify", "ingest"]}
        )

        assert status == 400
        assert body["fault"] == "rejected"
        assert "ADR-0294" in body["detail"]
        assert engine.grants_recorded == []


async def test_a_grant_carries_the_whole_scope_the_browser_chose() -> None:
    """ADR-0097 §8: nothing decides what the user permitted on their behalf.

    The gateway neither defaults the scope, nor widens it, nor infers one member from
    another — ADR-0133 §2 forbids ranking them — so what reaches the engine is what
    the browser sent, and what comes back is the record as it was appended.
    """
    engine = FakeAssistantEngine()
    engine.hold_source("calendar", location="/somewhere")
    async with _harness(engine) as one:
        status, body = await one.whole(
            "POST", "/grant", {"source": "calendar", "scope": ["notify"]}
        )

        assert status == 200
        assert body["grant"]["scope"] == ["notify"]
        assert body["grant"]["source"] == "calendar"
        assert body["grant"]["revokes"] is None


async def test_a_grant_naming_a_use_of_no_vocabulary_is_refused_before_the_hub() -> None:
    """A member of no vocabulary is not a scope the promoted surface has an answer
    for, so it is refused here rather than relayed.

    What is **not** decided here is emptiness or repetition: ADR-0097 §2 refuses an
    empty scope at construction and §10 refuses a duplicate, "locally and before any
    I/O" in every implementation (ADR-0085 §9), so a second rule at this layer could
    only differ from the one every other client already gets.
    """
    async with _harness() as one:
        status, body = await one.whole(
            "POST", "/grant", {"source": "calendar", "scope": ["notify", "everything"]}
        )

        assert status == 400
        assert body["fault"] == "malformed-request"
        assert one.engine.calls == []


async def test_an_empty_scope_is_the_hubs_refusal_and_not_the_gateways() -> None:
    """The other half of the case above, and the reason it is a separate one.

    ``grant`` with an empty scope is well-formed on the wire and refused by the
    promoted surface, so it is relayed and comes back as the hub's own refusal. A
    gateway that answered it locally would be a surface disagreeing with the contract
    about which calls are refused.

    The fault name is the evidence and is the only evidence there could be: the
    engine refuses "locally and before any I/O", so the call is not recorded — and
    ``rejected`` is the name :func:`_relay_fault` gives a ``ValueError`` the promoted
    surface raised, where every refusal the *gateway* authors is
    ``malformed-request``.
    """
    async with _harness() as one:
        status, body = await one.whole("POST", "/grant", {"source": "calendar", "scope": []})

        assert status == 400
        assert body["fault"] == "rejected"


async def test_a_revocation_applies_no_admission_check() -> None:
    """ADR-0102 §4: revocation "is refused for no property of the source's name — and
    in particular is *not* refused because no reader currently declares it".

    An operator who unsets a source's path leaves a live grant naming a source nothing
    drives; if this path applied the admission check ``grant`` applies, a configuration
    edit would have made that grant permanently unrevokable from a browser.
    """
    engine = FakeAssistantEngine()
    async with _harness(engine) as one:
        status, body = await one.whole("POST", "/revoke", {"source": "nothing-declares-this"})

        assert status == 200
        assert body["revoked"] is None
        assert _named(engine) == ["revoke"]


async def test_standing_grants_carries_a_grant_on_a_source_no_reader_declares() -> None:
    """ADR-0139 §2, which is the whole reason the operation exists.

    "``grantable_sources`` is keyed on the composition root, so an operator who unsets
    a reader's configured path makes the grant on it invisible while leaving it live
    and read-authorising." A gateway that annotated this set from the other read, or
    dropped an entry absent from it, would hide it again — which ADR-0139 §3's first
    clause forbids in terms.
    """
    engine = FakeAssistantEngine()
    engine.hold_grant("calendar", scope=(GrantScope.INGEST,))
    async with _harness(engine) as one:
        sources_status, sources = await one.whole("POST", "/sources", {})
        standing_status, standing = await one.whole("POST", "/grants/standing", {})

        assert sources_status == 200
        assert sources["sources"] == []
        assert standing_status == 200
        assert [one["source"] for one in standing["standing"]] == ["calendar"]
        assert standing["standing"][0]["scope"] == ["ingest"]


async def test_the_history_carries_what_distinguishes_a_revocation_from_a_grant() -> None:
    """ADR-0097 §4's audit surface, relayed and not interpreted.

    ADR-0102 §3 forbids presenting a record from ``recent_grants`` as live or as
    withdrawn on its own, so the gateway computes no liveness here — it carries
    ``revokes``, which is what tells the two kinds of record apart, and leaves the
    question of what stands to ``standing_grants``.
    """
    engine = FakeAssistantEngine()
    granted = engine.hold_grant("calendar", scope=(GrantScope.NOTIFY,))
    engine.hold_grant("calendar", scope=(GrantScope.NOTIFY,), revokes=granted.id)
    async with _harness(engine) as one:
        status, body = await one.whole("POST", "/grants/recent", {})

        assert status == 200
        assert [one["revokes"] for one in body["grants"]] == [granted.id, None]
        assert all("live" not in one for one in body["grants"])


async def test_the_gateway_serves_no_shape_that_amends_a_grant() -> None:
    """ADR-0177 §7's first clause: "The gateway serves no request shape that performs
    both, composes no amendment, and holds no state between the two."

    A gateway route doing both would put the intermediate state back inside a process
    the user cannot see — "the same defect the refused ``amend(source, scope)`` engine
    method has, rebuilt at a different layer", and forbidden a second time by
    ADR-0168 §1.
    """
    assert "amend" not in set(_ASSISTANT_PATHS.values())
    assert not any("amend" in path for _, path in _ASSISTANT_PATHS)


async def test_an_amendment_reaches_the_hub_as_two_calls_in_order() -> None:
    """§7's first clause from the other side: two browser requests, two engine calls.

    Composed in the front end, which is what puts the intermediate state where a
    surface can report it (ADR-0139 §4). Nothing between the two requests is held by
    the gateway — it does not know they are related.
    """
    engine = FakeAssistantEngine()
    engine.hold_source("calendar", location="/somewhere")
    engine.hold_grant("calendar", scope=(GrantScope.NOTIFY,))
    async with _harness(engine) as one:
        withdrawn_status, _ = await one.whole("POST", "/revoke", {"source": "calendar"})
        granted_status, _ = await one.whole(
            "POST", "/grant", {"source": "calendar", "scope": ["notify"]}
        )

        assert (withdrawn_status, granted_status) == (200, 200)
        assert _named(engine) == ["revoke", "grant"]


async def test_a_lost_hub_and_a_hub_refusal_are_two_conditions_on_a_grant_act() -> None:
    """ADR-0177 §7's third clause: which of ADR-0139 §4's three outcomes an act gets
    "is read from ADR-0168 §9's distinction and from nothing else".

    A request the hub received and declined is **known not to have landed**; a
    transport failure between the gateway and the hub is **not known**. The gateway
    is what makes the two tellable apart, and a front end reading them from one status
    code could not classify either.
    """
    async with _harness(_Unreachable()) as one:
        lost_status, lost = await one.whole("POST", "/revoke", {"source": "calendar"})
    async with _harness(_Declining()) as two:
        refused_status, refused = await two.whole("POST", "/revoke", {"source": "calendar"})

    assert (lost_status, lost["fault"]) == (502, "hub-unreachable")
    assert (refused_status, refused["fault"]) == (422, "assistant-declined")


# --- ADR-0177 §5: the belief surface -----------------------------------------


#: Every member ADR-0328 §15:1 has both memory views carry, and no other: no
#: confidence, no presented confidence and no elision count (§15:3).
_LISTED: Final = {
    "id",
    "band",
    "standing",
    "status",
    "content",
    "valid_until",
    "as_of",
    "learned",
    "evidence",
    "reading_certainty",
    "track_record",
    "legacy",
    "unbacked",
    "rests_on_outside_content",
    "supports_gone",
}


async def test_a_listing_carries_every_field_the_floor_requires_and_no_support() -> None:
    """ADR-0328 §15:1's fields, and ADR-0085 §4a's split.

    A summary carries **no** supports: the type has nowhere to put one, so a conforming
    listing cannot ship an episode's text on every page. The key set is exact, so a
    field one view carries and the other drops (#1517's failure) is caught here.
    """
    engine = FakeAssistantEngine()
    engine.hold("rec-1", content="the owner runs on Tuesdays", band=BeliefBand.DERIVED)
    async with _harness(engine) as one:
        status, body = await one.whole("POST", "/beliefs", {})

        assert status == 200
        held = body["beliefs"][0]
        assert set(held) == _LISTED
        assert (held["band"], held["standing"], held["status"]) == (
            "derived",
            "inference",
            "current",
        )
        assert set(held["evidence"]) == {"supporting", "against", "episodes", "latest"}
        assert set(held["track_record"]) == {"relied_on", "held_up", "let_down", "last_used"}
        assert "supports" not in held


async def test_the_single_view_carries_the_listings_fields_and_every_support() -> None:
    """ADR-0328 §15:2: the same fields under the same names, plus each support."""
    engine = FakeAssistantEngine()
    engine.hold("rec-1", content="the office is in Boston")
    async with _harness(engine) as one:
        _, single = await one.whole("POST", "/belief", {"record_id": "rec-1"})

        belief = single["belief"]
        assert set(belief) == _LISTED | {"supports"}
        assert set(belief["supports"][0]) == {
            "part",
            "content",
            "origin",
            "direction",
            "note",
            "how_sure",
            "when",
            "about_when",
            "source_details",
            "counts",
        }
        assert belief["supports"][0]["origin"] == "user_message"


async def test_a_sourced_supports_details_cross_whole_on_the_single_view() -> None:
    """ADR-0328 §15:2 on the shape ADR-0092 §2 requires: one object, never two members.

    Two independent nullable members admit two half-answers — a source with no instant,
    and an instant with no source — and one optional object with two required members
    makes both unconstructable on this wire exactly as they are on the record.
    """
    engine = FakeAssistantEngine()
    engine.hold(
        "rec-1",
        content="the board dine on Thursday",
        band=BeliefBand.ATTESTED,
        attestation=Attestation(reported_by="work-calendar", reported_at=_INSTANT),
    )
    async with _harness(engine) as one:
        _, listing = await one.whole("POST", "/beliefs", {})
        _, single = await one.whole("POST", "/belief", {"record_id": "rec-1"})

        assert listing["beliefs"][0]["standing"] == "source"
        assert listing["beliefs"][0]["rests_on_outside_content"] is True
        assert single["belief"]["supports"][0]["source_details"] == {
            "reported_by": "work-calendar",
            "reported_at": _INSTANT.isoformat(),
        }


async def test_an_absent_value_crosses_as_null_rather_than_being_omitted() -> None:
    """ADR-0184's ruling: an absence carrying meaning is a value rather than a gap.

    A memory nothing dates has an unknown as of (ADR-0328 §7:3) and a reading nobody
    judged has no certainty (§7:5); both cross as ``null``, because a page cannot tell
    an absent key from a key it forgot to read.
    """
    engine = FakeAssistantEngine()
    engine.hold("rec-1", content="the office is in Boston", band=BeliefBand.ASSERTED)
    async with _harness(engine) as one:
        _, listing = await one.whole("POST", "/beliefs", {})

        held = listing["beliefs"][0]
        assert held["reading_certainty"] is None
        assert held["valid_until"] is None
        assert held["rests_on_outside_content"] is False


async def test_a_derived_memory_carries_the_computed_answer_and_not_a_flag() -> None:
    """ADR-0328 §7:6, read through §12 as ADR-0189 §2's fifth clause.

    Rests-on-outside-content is computed from the supports by ``core`` at projection
    time: no producer supplies it and no surface recomputes it from ``band``. The
    ``DERIVED`` band is the one where the two answers can differ.
    """
    engine = FakeAssistantEngine()
    engine.hold(
        "outside",
        content="they commute on Tuesdays",
        band=BeliefBand.DERIVED,
        rests_on_outside_content=True,
    )
    engine.hold("inside", content="they prefer mornings", band=BeliefBand.DERIVED)
    async with _harness(engine) as one:
        _, listing = await one.whole("POST", "/beliefs", {})

        answers = {row["id"]: row["rests_on_outside_content"] for row in listing["beliefs"]}
        assert answers == {"outside": True, "inside": False}


async def test_the_extent_rides_on_the_record_and_crosses_to_no_browser() -> None:
    """ADR-0189 §10 leaves the extent's rendering to ADR-0117, so it stops here.

    A value on this wire with no consumer is surface (ADR-0045 §1), so the two members
    a surface *is* ruled to render are the two that cross.
    """
    engine = FakeAssistantEngine()
    engine.hold(
        "rec-1",
        content="the board dine on Thursday",
        band=BeliefBand.ATTESTED,
        attestation=Attestation(
            reported_by="work-calendar",
            reported_at=_INSTANT,
            extent=ReportedExtent(extends_until=_INSTANT),
        ),
    )
    async with _harness(engine) as one:
        _, single = await one.whole("POST", "/belief", {"record_id": "rec-1"})

        details = single["belief"]["supports"][0]["source_details"]
        assert set(details) == {"reported_by", "reported_at"}


async def test_an_absent_band_filter_and_an_empty_one_are_different_questions() -> None:
    """The contract's own words: ``bands`` of ``None`` selects every band, and "an
    empty sequence selects nothing, which is a different answer from ``None``".

    A reader that folded the two would answer a question the browser did not ask, and
    would do it silently — the empty case returns an empty page either way, so nothing
    downstream could tell.
    """
    engine = FakeAssistantEngine()
    engine.hold("rec-1", content="held", band=BeliefBand.ASSERTED)
    async with _harness(engine) as one:
        _, every = await one.whole("POST", "/beliefs", {})
        _, none_at_all = await one.whole("POST", "/beliefs", {"bands": []})

        assert len(every["beliefs"]) == 1
        assert none_at_all["beliefs"] == []
        assert [arguments["bands"] for _, arguments in engine.calls] == [None, ()]


async def test_the_listing_relays_no_kind_so_episodes_never_reach_the_panel() -> None:
    """ADR-0328 §11:2, and #3143: the listing holds memories, never episodes.

    The page asks with no filter, and the gateway relays only the bands: there is no
    kind to relay, so the engine's own listing — memories only — is what the panel
    shows.
    """
    engine = FakeAssistantEngine()
    engine.hold("rec-1", content="held")
    async with _harness(engine) as one:
        await one.whole("POST", "/beliefs", {"kinds": ["episodic"]})

        assert engine.calls == [("beliefs", {"bands": None})]


async def test_a_band_of_no_vocabulary_is_refused_rather_than_dropped() -> None:
    """Dropping it would answer a narrower question than the browser asked and say
    nothing about having done so, which is the quiet half of the case above."""
    async with _harness() as one:
        status, body = await one.whole("POST", "/beliefs", {"bands": ["invented"]})

        assert status == 400
        assert body["fault"] == "malformed-request"
        assert one.engine.calls == []


async def test_the_single_read_resolves_its_supports_and_shows_the_gone_one_as_gone() -> None:
    """ADR-0328 §15:7, and ADR-0073 §4's floor.

    A support whose episode no longer resolves still counts, and is shown as gone and
    never as evidence — not as a reassuring id, not silently dropped. It crosses with
    ``content`` ``null``, and a support carries no id at all.
    """
    engine = _WithEvidence()
    async with _harness(engine) as one:
        status, body = await one.whole("POST", "/belief", {"record_id": "rec-1"})

        assert status == 200
        supports = body["belief"]["supports"]
        assert [one["content"] for one in supports] == ["a run on Tuesday", None]
        assert all(one["counts"] for one in supports), "a gone support still counts"
        assert body["belief"]["supports_gone"] is False
        assert all("id" not in one and "episode" not in one for one in supports)


async def test_a_belief_read_that_names_nothing_live_is_its_own_condition() -> None:
    """ADR-0073 §5: "this surface deletes what it can show".

    An id naming a belief the assistant has since revised does not resolve, and the
    ceremony's own requirement is that the surface declines it rather than destroying
    something it cannot display. So the read says so as its own condition, and the
    front end has something to say other than "it failed".
    """
    async with _harness() as one:
        status, body = await one.whole("POST", "/belief", {"record_id": "rec-gone"})

        assert status == 404
        assert body == {"fault": "no-such-belief"}


async def test_forgetting_a_belief_reports_whether_there_was_one_to_forget() -> None:
    """The contract: ``False`` "where the id named nothing live, which is not an
    error: the user's intent — 'let this not be held' — is already satisfied".

    So the gateway relays the boolean rather than turning it into a fault, and the
    ceremony that precedes it is the front end's (ADR-0177 §5) — this handler cannot
    tell a confirmed call from an unconfirmed one and does not pretend to.
    """
    engine = FakeAssistantEngine()
    engine.hold("rec-1", content="held")
    async with _harness(engine) as one:
        _, destroyed = await one.whole("POST", "/belief/forget", {"record_id": "rec-1"})
        _, again = await one.whole("POST", "/belief/forget", {"record_id": "rec-1"})

        assert destroyed == {"destroyed": True}
        assert again == {"destroyed": False}


# --- what the gateway refuses of its own -------------------------------------


@pytest.mark.parametrize(
    "path",
    ["/grant", "/revoke", "/belief", "/belief/forget"],
)
async def test_a_missing_required_argument_is_refused_before_the_hub(path: str) -> None:
    """ADR-0168 §1: the gateway "derives none of them, defaults none of them".

    A request with no argument at all is not a call with a default; it is a request
    the surface cannot make, and it is refused without a hub connection being taken.
    """
    async with _harness() as one:
        status, body = await one.whole("POST", path, {})

        assert status == 400, path
        assert body["fault"] == "malformed-request", path
        assert one.engine.calls == []


async def test_a_refusal_carries_no_fact_about_the_hub() -> None:
    """ADR-0168 §3: a refusal's body carries the condition "and nothing else: no
    assistant content, no fact about the hub's state, and no fact about whether the
    hub is reachable".

    Asserted on the malformed-request path because that is the one this lane adds
    most of, and because a reader that echoed the offending member back would be a
    surface disclosing its own shape to something that got it wrong.
    """
    async with _harness() as one:
        _, body = await one.whole("POST", "/belief", {"record_id": 7})

        assert body == {"fault": "malformed-request"}


@pytest.mark.parametrize("value", [True, -1, 2**63, "40"])
async def test_a_page_argument_is_refused_at_this_adapters_own_parse_boundary(
    value: object,
) -> None:
    """``AssistantEngine.beliefs``' own instruction to a client: "an adapter that lets
    a user supply either **should refuse an out-of-range value at its own parse
    boundary**".

    A browser is such an adapter, so the bound ADR-0085 §9 declares — ``[0, 2**63)``,
    refused rather than clamped (ADR-0073 §2) — is applied here, and no hub connection
    is taken for a page nobody can serve.

    ``True`` is in the list because ``bool`` is an ``int`` by inheritance: without the
    type check it is a page of one that nothing downstream could tell from a request
    for one.
    """
    async with _harness() as one:
        status, body = await one.whole("POST", "/beliefs", {"limit": value})

        assert status == 400
        assert body["fault"] == "malformed-request"
        assert one.engine.calls == []


async def test_an_operations_own_paging_rule_stays_the_operations() -> None:
    """The bound above is the *argument's* and is not narrowed to any operation's.

    ``recent_grants`` requires a strictly positive ``limit`` (ADR-0102 §10), which
    ``beliefs`` does not — so ``limit: 0`` is well-formed at this boundary, is relayed,
    and comes back as the hub's own refusal. A gateway that had folded the tighter rule
    into its parser would refuse a call ``beliefs`` accepts.
    """
    async with _harness() as one:
        paged_status, _ = await one.whole("POST", "/beliefs", {"limit": 0})
        grants_status, grants = await one.whole("POST", "/grants/recent", {"limit": 0})

        assert paged_status == 200
        assert (grants_status, grants["fault"]) == (400, "rejected")


async def test_a_blank_identifier_is_the_promoted_surfaces_refusal_and_not_a_second_one() -> None:
    """Blankness is refused by the promoted surface "locally and before any I/O" in
    every implementation (ADR-0085 §9), so nothing reaches the hub either way — and a
    second predicate here would be a second definition of "blank".

    That is the failure ADR-0102 §2 is written against one field over: a rule applied
    a layer below the comparison makes the gateway admit or refuse calls the
    in-process engine does not. The paging bound above is different in kind and that
    is why it is here — the surface contract asks an adapter for it by name, and no
    clause asks an adapter to decide what a blank string is.
    """
    async with _harness() as one:
        status, body = await one.whole("POST", "/belief", {"record_id": "   "})

        assert status == 400
        assert body["fault"] == "rejected"


@pytest.mark.parametrize(
    ("path", "payload"),
    [
        ("/beliefs", {"bands": [{}]}),
        ("/grant", {"source": "calendar", "scope": [{"facet": True}]}),
    ],
)
async def test_a_vocabulary_member_that_is_not_a_string_is_refused_and_not_a_fault(
    path: str, payload: dict[str, Any]
) -> None:
    """A body can carry an object or an array where a member name belongs, and neither
    is hashable — so a reader that asked the vocabulary about one directly would raise
    a ``TypeError`` this module does not catch.

    ADR-0168 §3's answer to a request the surface has no shape for is a refusal on a
    condition, not a fault of the process, and the type check is what makes the lookup
    total over what a JSON body can contain.
    """
    async with _harness() as one:
        status, body = await one.whole("POST", path, payload)

        assert status == 400, path
        assert body["fault"] == "malformed-request", path
        assert one.engine.calls == []


async def test_a_source_with_no_configured_location_stays_grantable() -> None:
    """ADR-0102 §6, normatively: ``location`` is ``None`` "only where the source has
    **no** configured location at all".

    A configured location that cannot be shown is the hazard the clause fails closed
    on, and it fails closed *hub-side*: ``grantable_sources`` omits such a source and
    ``grant`` refuses it. So a source that reaches a client with ``location`` absent is
    one where "§9a's obligation [is] vacuous — there is nothing to show — and the
    source is grantable with ``location`` absent".

    Written down because the inverse reading is the natural one and would make a
    grantable source ungrantable from a browser while reaching no hazard at all.
    """
    engine = FakeAssistantEngine()
    engine.hold_source("notes")
    async with _harness(engine) as one:
        listed_status, listed = await one.whole("POST", "/sources", {})
        granted_status, granted = await one.whole(
            "POST", "/grant", {"source": "notes", "scope": ["notify"]}
        )

        assert (listed_status, listed["sources"][0]["location"]) == (200, None)
        assert granted_status == 200
        assert granted["grant"]["source"] == "notes"


async def test_a_grant_store_fault_is_the_hubs_condition_and_not_a_gateway_one() -> None:
    """ADR-0168 §9: a request the hub received and declined is answered as such, and
    never as a transport failure or as an answer."""
    async with _harness(_CorruptStore()) as one:
        status, body = await one.whole("POST", "/grants/standing", {})

        assert status == 422
        assert body["fault"] == "assistant-declined"


def _request(path: str) -> Request:
    """One parsed POST at ``path``, for a classification that reads it alone."""
    return Request(method="POST", path=path, headers=(), body=b"{}")


class _Unreachable(FakeAssistantEngine):
    """An engine whose hub is not there (ADR-0168 §9)."""

    async def revoke(self, source: NonBlankEncodableText) -> SourceGrant | None:
        """Fail the way a closed door fails: a transport error, not an answer."""
        self.calls.append(("revoke", {"source": source}))
        msg = "no hub is listening on that socket"
        raise HubUnavailableError(msg)


class _Declining(FakeAssistantEngine):
    """An engine that received the request and declined it."""

    async def revoke(self, source: NonBlankEncodableText) -> SourceGrant | None:
        """Refuse the way the hub refuses: an ``AssistantError`` it authored."""
        self.calls.append(("revoke", {"source": source}))
        msg = "that source cannot be granted"
        raise UngrantableSourceError(msg)


class _CorruptStore(FakeAssistantEngine):
    """An engine whose grant store cannot be read (ADR-0139 §2's own refusal)."""

    async def standing_grants(self) -> tuple[SourceGrant, ...]:
        """Refuse the whole call rather than a source, as the contract requires."""
        self.calls.append(("standing_grants", {}))
        msg = "the grant store could not be read"
        raise GrantError(msg)


class _WithEvidence(FakeAssistantEngine):
    """An engine holding one memory whose supports are half gone.

    Scripted here rather than through :meth:`FakeAssistantEngine.hold`, which holds one
    resolved support: the gone support is the state ADR-0328 §15:7 is about, and a
    state no test can reach is a floor nobody checks.
    """

    async def belief(self, record_id: Identifier) -> Belief:
        """Answer one memory carrying a resolved support and a gone one."""
        self.calls.append(("belief", {"record_id": record_id}))
        held = memory(
            record_id,
            "the owner runs on Tuesdays",
            remembered_support("activation:kept"),
            remembered_support("activation:lost", effect="effect-2"),
        )
        kept, lost = (support.points_at for support in held.supports)
        return belief_view(held, now=_INSTANT, contents={kept: "a run on Tuesday", lost: None})
