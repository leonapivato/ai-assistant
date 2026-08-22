"""The browser's control surface end to end (ADR-0177).

Thirteen operations reach a browser here that did not before: the grant surface,
the belief surface, the deferred-question surface, and ``observe``. ADR-0177 §1
admits them by name and closes the enumeration at thirty; §2 keeps the four request
classes; §5, §6 and §7 say what the surfaces owe once they are reachable.

**Driven through a real socket** for ``test_gateway.py``'s reason: what is under
test is a request the browser makes and a body it renders, and the router, the door
and the admission all sit between the two.

The harness is ``test_gateway_streams``' own rather than a third copy of it — the
gateway it binds and the session it mints are the same in either file, and a copy
would be one more place for the two to drift apart.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import pytest
from test_gateway_streams import _harness

from ai_assistant.core.errors import GrantError, UngrantableSourceError
from ai_assistant.core.types import (
    AnswerKind,
    AnswerOutcome,
    Belief,
    BeliefBand,
    Evidence,
    GrantScope,
    MemoryKind,
    MemorySource,
    ObservationReport,
    ObservedProposal,
    QuestionState,
    SuccessorLink,
)
from ai_assistant.interfaces.gateway.http import Request
from ai_assistant.interfaces.gateway.records import RequestClass
from ai_assistant.interfaces.gateway.server import _ASSISTANT_PATHS
from ai_assistant.testing import FakeAssistantEngine
from ai_assistant.wire.errors import HubUnavailableError

if TYPE_CHECKING:
    from ai_assistant.core.types import Identifier, NonBlankEncodableText, SourceGrant

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("hermetic_assistant_env")]

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
    "/questions": "questions",
    "/questions/interrupted": "interrupted_questions",
    "/question/answer": "answer",
    "/question/forget": "forget_question",
    "/observe": "observe",
}

#: One well-formed body per path, so a case can drive any of them without inventing
#: arguments at each site. Every value here is the **browser's own**: ADR-0177 §1
#: requires that "every argument expressing what the user asked for is the browser's
#: own — the gateway derives none of them, defaults none of them".
_WELL_FORMED: dict[str, dict[str, Any]] = {
    "/sources": {},
    "/grant": {"source": "calendar", "scope": ["facet"]},
    "/revoke": {"source": "calendar"},
    "/grants/recent": {},
    "/grants/standing": {},
    "/beliefs": {},
    "/belief": {"record_id": "rec-1"},
    "/belief/forget": {"record_id": "rec-1"},
    "/questions": {},
    "/questions/interrupted": {},
    "/question/answer": {"question_id": "q-1", "accept": True},
    "/question/forget": {"question_id": "q-1"},
    "/observe": {},
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
    engine.hold_grant("calendar", scope=(GrantScope.FACET,))
    async with _harness(engine) as one:
        _, body = await one.whole("POST", "/sources", {})

        assert body["sources"][0]["live"]["scope"] == ["facet"]


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
            "POST", "/grant", {"source": " calendar ", "scope": ["facet"]}
        )

        assert status == 422
        assert body["fault"] == "assistant-declined"
        assert engine.calls == [("grant", {"source": " calendar ", "scope": (GrantScope.FACET,)})]


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
            "POST", "/grant", {"source": "calendar", "scope": ["notify", "facet"]}
        )

        assert status == 200
        # Declaration order is the record's own validator's, not this adapter's.
        assert body["grant"]["scope"] == ["facet", "notify"]
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
            "POST", "/grant", {"source": "calendar", "scope": ["facet", "everything"]}
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
    granted = engine.hold_grant("calendar", scope=(GrantScope.FACET,))
    engine.hold_grant("calendar", scope=(GrantScope.FACET,), revokes=granted.id)
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
    engine.hold_grant("calendar", scope=(GrantScope.FACET,))
    async with _harness(engine) as one:
        withdrawn_status, _ = await one.whole("POST", "/revoke", {"source": "calendar"})
        granted_status, _ = await one.whole(
            "POST", "/grant", {"source": "calendar", "scope": ["ingest", "notify"]}
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


async def test_a_listing_carries_every_field_the_floor_requires_and_no_citation() -> None:
    """ADR-0073 §4's per-belief fields, and ADR-0085 §4a's split.

    The band, the confidence, the kind, the content, when it was last revised, the
    validity window's end and the id — plus the three citation counts, because §4's
    floor for a derived belief is that the surface conveys "how many citations stand
    behind it" and ADR-0107 §5 owes the elision ceiling beside any rendered count.

    A summary carries **no** citations: the type has nowhere to put one, so a
    conforming listing cannot ship the corpus on every page.
    """
    engine = FakeAssistantEngine()
    engine.hold("rec-1", content="the owner runs on Tuesdays", band=BeliefBand.DERIVED)
    async with _harness(engine) as one:
        status, body = await one.whole("POST", "/beliefs", {})

        assert status == 200
        held = body["beliefs"][0]
        assert set(held) == {
            "id",
            "band",
            "kind",
            "content",
            "confidence",
            "last_updated",
            "valid_until",
            "evidence_count",
            "lost_evidence",
            "evidence_elided",
            "unsupported",
        }
        assert held["band"] == "derived"
        assert "evidence" not in held


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


async def test_a_band_of_no_vocabulary_is_refused_rather_than_dropped() -> None:
    """Dropping it would answer a narrower question than the browser asked and say
    nothing about having done so, which is the quiet half of the case above."""
    async with _harness() as one:
        status, body = await one.whole("POST", "/beliefs", {"bands": ["invented"]})

        assert status == 400
        assert body["fault"] == "malformed-request"
        assert one.engine.calls == []


async def test_the_single_belief_read_resolves_its_citations_and_tombstones_what_is_gone() -> None:
    """ADR-0077 §6's other half, and ADR-0073 §4's floor.

    "A citation the surface cannot render as evidence is never rendered *as* evidence
    — not as a reassuring id, not silently dropped." An unresolved citation crosses as
    an entry whose content is absent, and :class:`Evidence` carries no id at all, so
    nothing downstream can pass one off as the warrant.
    """
    engine = _WithEvidence()
    async with _harness(engine) as one:
        status, body = await one.whole("POST", "/belief", {"record_id": "rec-1"})

        assert status == 200
        assert body["belief"]["evidence"] == [{"content": "a run on Tuesday"}, {"content": None}]
        assert body["belief"]["lost_evidence"] == 1


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


# --- ADR-0078 §8: the deferred-question surface ------------------------------


async def test_the_two_question_listings_answer_two_different_questions() -> None:
    """ADR-0078 §9: an interrupted question is "not 'failed' and not 'retryable': the
    system does **not** know whether the memory write landed".

    Two reads and two lists all the way to the surface, because offering an
    interrupted question beside the answerable ones would present a claim that cannot
    be taken (ADR-0078 §8).
    """
    engine = FakeAssistantEngine()
    engine.ask("q-1", content="do you run on Tuesdays", state=QuestionState.OPEN)
    engine.ask("q-2", content="did you move house", state=QuestionState.INTERRUPTED)
    async with _harness(engine) as one:
        _, waiting = await one.whole("POST", "/questions", {})
        _, begun = await one.whole("POST", "/questions/interrupted", {})

        assert [one["id"] for one in waiting["questions"]] == ["q-1"]
        assert [one["id"] for one in begun["questions"]] == ["q-2"]
        assert begun["questions"][0]["state"] == "interrupted"


async def test_a_question_carries_what_it_would_have_the_assistant_believe() -> None:
    """ADR-0078 §8's six things, of which the conditional is the one a surface gets
    wrong: a pending question "is not a belief of any band", so the band it *would*
    enter travels as the conditional it is, beside why the user is being asked and
    exactly what accepting would retire."""
    engine = FakeAssistantEngine()
    engine.ask("q-1", content="do you run on Tuesdays", state=QuestionState.OPEN)
    async with _harness(engine) as one:
        _, body = await one.whole("POST", "/questions", {})

        held = body["questions"][0]
        assert set(held) == {
            "id",
            "state",
            "content",
            "kind",
            "band",
            "rationale",
            "reason",
            "retires",
            "asked_at",
            "expires_at",
            "successor",
        }
        assert held["band"] == "asserted"
        assert held["retires"] == []
        assert held["successor"] is None


async def test_an_answer_needs_a_boolean_and_is_never_defaulted() -> None:
    """A default would be this adapter deciding whether the user believes something,
    which is what ADR-0097 §8's reasoning forbids a surface anywhere in this system.

    ``true`` as a string is refused for the same reason ``_integer`` excludes
    ``bool``: a value that is *nearly* the right type is the one that reaches the
    store as the wrong answer.
    """
    async with _harness() as one:
        for payload in ({"question_id": "q-1"}, {"question_id": "q-1", "accept": "yes"}):
            status, body = await one.whole("POST", "/question/answer", payload)

            assert status == 400, payload
            assert body["fault"] == "malformed-request", payload
        assert one.engine.calls == []


async def test_an_answer_renders_the_outcome_beside_what_it_left_behind() -> None:
    """ADR-0078 §5 and §9: five outcomes, and two facts reported *alongside* whichever
    applies rather than in place of it.

    A re-deferral that could queue no follow-on at all says so — calling it
    "re-deferred" would claim a question was asked when none was — and a question
    destroyed while its answer was being applied is a true statement about the
    bookkeeping and never about the answer.
    """
    engine = FakeAssistantEngine()
    engine.ask("q-1", content="do you run on Tuesdays", state=QuestionState.OPEN)
    engine.answered = AnswerOutcome(
        kind=AnswerKind.REDEFERRED,
        question_id="q-1",
        successor=SuccessorLink(id="q-2", state=QuestionState.OPEN),
        disposed=True,
    )
    async with _harness(engine) as one:
        status, body = await one.whole(
            "POST", "/question/answer", {"question_id": "q-1", "accept": True}
        )

        assert status == 200
        assert body["answered"] == {
            "kind": "redeferred",
            "question_id": "q-1",
            "record_id": None,
            "successor": {"id": "q-2", "state": "open"},
            "successor_refused": False,
            "disposed": True,
        }


async def test_forgetting_a_question_reports_whether_there_was_one() -> None:
    """The contract's own boolean, relayed. The ceremony ADR-0177 §5 gives this verb
    is the front end's, and it is met with the two listings rather than with the
    single-question read #495 records as missing."""
    engine = FakeAssistantEngine()
    engine.ask("q-1", content="do you run on Tuesdays", state=QuestionState.OPEN)
    async with _harness(engine) as one:
        _, destroyed = await one.whole("POST", "/question/forget", {"question_id": "q-1"})
        _, again = await one.whole("POST", "/question/forget", {"question_id": "q-1"})

        assert destroyed == {"destroyed": True}
        assert again == {"destroyed": False}


# --- ADR-0077 §8: observing ---------------------------------------------------


async def test_the_conversation_is_a_selector_and_an_absent_one_is_not_an_error() -> None:
    """ADR-0085 §2: ``conversation_id`` is "a **selector rather than a subject**" —
    "this conversation, or the most recently active" — so an absent one selects and
    does not refuse."""
    engine = FakeAssistantEngine()
    engine.start_conversation("c-1")
    async with _harness(engine) as one:
        status, _ = await one.whole("POST", "/observe", {})
        named_status, _ = await one.whole("POST", "/observe", {"conversation_id": "c-1"})

        assert (status, named_status) == (200, 200)
        assert engine.calls == [
            ("observe", {"conversation_id": None}),
            ("observe", {"conversation_id": "c-1"}),
        ]


@pytest.mark.parametrize("path", ["/observe", "/ask", "/ask/stream"])
async def test_a_selector_of_the_wrong_type_is_refused_rather_than_read_as_absent(
    path: str,
) -> None:
    """ADR-0177 §1: "the gateway derives none of them, **defaults none of them**".

    An absent ``conversation_id`` is a selector — "this conversation, or the most
    recently active" (ADR-0085 §2) — so reading a number as an absence answers a
    *different* well-formed question instead of refusing a malformed one.

    It matters most where the operation writes: ``observe`` proposes beliefs from the
    batch it reads, so a mistyped selector silently accepted would put proposals on a
    conversation nobody named. The two turn entries are here too because the reader is
    shared and the refusal has to reach the streamed shape as well as the unary ones.
    """
    body: dict[str, Any] = {"conversation_id": 7}
    if path != "/observe":
        body["utterance"] = "what is on today"
    async with _harness() as one:
        status, answered = await one.whole("POST", path, body)

        assert status == 400, path
        assert answered["fault"] == "malformed-request", path
        assert one.engine.calls == [], path


@pytest.mark.parametrize("path", ["/observe", "/ask"])
async def test_a_null_selector_is_the_absence_it_says_it_is(path: str) -> None:
    """JSON has a way of saying "no selector", and a client using it is not getting
    the type wrong — so ``null`` reads as the absence the omitted member is."""
    body: dict[str, Any] = {"conversation_id": None}
    if path != "/observe":
        body["utterance"] = "what is on today"
    async with _harness() as one:
        status, _ = await one.whole("POST", path, body)

        assert status == 200, path
        assert one.engine.calls[0][1]["conversation_id"] is None, path


async def test_an_observation_keeps_its_three_discard_counts_apart() -> None:
    """They are three different facts — what the producer could not use, what it
    dropped over its own limit, and what the write path refused for want of support —
    and a single "not stored" figure would be this adapter deciding they are one.

    ``decision`` absent means **no ruling was ever made**, which is not the same as a
    ruling that rejected the proposal, so the two are not flattened either.
    """
    engine = FakeAssistantEngine()
    engine.observation = ObservationReport(
        proposals=(
            ObservedProposal(
                content="the owner runs on Tuesdays",
                kind=MemoryKind.SEMANTIC,
                step=MemorySource.INFERRED,
                confidence=0.6,
                rationale="three Tuesdays in the batch",
                decision=None,
                record_id=None,
                reason="the batch ended before it was ruled on",
                evidence=(Evidence(content="a run on Tuesday"),),
            ),
        ),
        discarded_unusable=1,
        discarded_over_limit=2,
        dropped_unsupported=3,
        route="a-model",
        episodes_read=9,
    )
    async with _harness(engine) as one:
        status, body = await one.whole("POST", "/observe", {})

        assert status == 200
        report = body["observation"]
        assert (
            report["discarded_unusable"],
            report["discarded_over_limit"],
            report["dropped_unsupported"],
        ) == (1, 2, 3)
        assert report["route"] == "a-model"
        assert report["episodes_read"] == 9
        assert report["proposals"][0]["decision"] is None
        assert report["proposals"][0]["evidence"] == [{"content": "a run on Tuesday"}]


# --- what the gateway refuses of its own -------------------------------------


@pytest.mark.parametrize(
    "path",
    ["/grant", "/revoke", "/belief", "/belief/forget", "/question/forget"],
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
        ("/beliefs", {"kinds": [[]]}),
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
            "POST", "/grant", {"source": "notes", "scope": ["facet"]}
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
    """An engine holding one belief whose citations are half gone.

    Scripted here rather than through :meth:`FakeAssistantEngine.hold`, which fixes
    the confidence and holds no citations — the tombstone is the state ADR-0073 §4's
    floor is about, and a state no test can reach is a floor nobody checks.
    """

    async def belief(self, record_id: Identifier) -> Belief:
        """Answer one belief carrying a resolved citation and a tombstone."""
        self.calls.append(("belief", {"record_id": record_id}))
        return Belief(
            id=record_id,
            band=BeliefBand.DERIVED,
            kind=MemoryKind.SEMANTIC,
            content="the owner runs on Tuesdays",
            confidence=0.4,
            last_updated=_INSTANT,
            evidence=(Evidence(content="a run on Tuesday"), Evidence()),
        )
