"""ADR-0242's explanation, driven through the **engine** (§15).

``tests/orchestration/test_search_not_serviced.py`` drives the servicing site and the
loop; this module drives the pipeline **above** them — ``Engine.converse``, the real
``ComposingStage`` it forwards to, and the ``TurnOutcome`` it builds — because §7's
carrier and §9's field are two consumers of one computed member and a lane that dropped
either forwarding would leave every loop-level assertion passing while the user lost the
explanation.

The harness is ``test_engine``'s, because what these cases are about is the real
pipeline: the production ``ThresholdActionPolicy``, the real
:class:`~ai_assistant.orchestration.reads.SearchServicer`, the trust store the
composition root wires into the one servicing site, and the capture point that is "the
single place a ``TurnOutcome`` is built".
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from itertools import count
from typing import TYPE_CHECKING, Any, Final

import structlog
from test_engine import AT, PATIENT, SEARCH_DESTINATIONS, Harness
from test_engine_read_envelope import _AskingPlanner, _recorder
from test_loop_search import _DEADLINE, _binder, _CostedSearcher, _search

from ai_assistant.core.types import (
    DestinationTrust,
    DestinationTrustRecord,
    Role,
    SearchNotServiced,
)
from ai_assistant.orchestration.reads import SearchDisposition, SearchServicer
from ai_assistant.permissions.policy import ThresholdActionPolicy
from ai_assistant.testing import (
    FakeAuditTrail,
    FakeDestinationTrustStore,
    FakeMemoryStore,
    FakeQueryComposer,
    FakeRecipientGrantStore,
    FakeWebSearcher,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.orchestration.composing import ComposingStage
    from ai_assistant.testing import FakeModelProvider

_ASKED: Final = "what has changed since we last spoke"

#: A distinctive clause of ADR-0242 §7's ``AUTHORISATION_AWAITED`` fragment, quoted so
#: this module asserts the **fragment** reached the prompt rather than that two prompts
#: differ — which they also do for reasons ADR-0228 §10 owns.
_AWAITED_FRAGMENT: Final = "instead of making that lookup it was put to this person as a question"

#: One distinctive clause per ADR-0242 §7 fragment, for the arm that says a serviced turn
#: is told about no lookup at all. Written out rather than reached for through the
#: composing module's private table, because what is asserted is what the prompt says.
_FRAGMENTS: Final = (
    "this installation does not make them at all",
    "no such lookup was made on this occasion",
    "a limit this installation is run under stood in the way",
    "the rules this installation is run under declined it",
    "is not one this person has chosen to have things composed for",
    _AWAITED_FRAGMENT,
    "it was stopped before it came back",
    "that lookup produced nothing this turn could use",
)


def _system_prompt(model: FakeModelProvider, ordinal: int = -1) -> str:
    """The system message the production stage assembled, from the fake's own record.

    ``ordinal`` picks which turn's prompt, defaulting to the **last** — a journey that
    performs an act between two turns composes twice through one stage, and what the arm
    is about is the turn after the act.
    """
    assert model.calls
    return next(one.content for one in model.calls[ordinal].messages if one.role is Role.SYSTEM)


def _chosen() -> DestinationTrustRecord:
    """A live record over the destination set this deployment's search binds to."""
    return DestinationTrustRecord(
        id="t-1",
        destinations=SEARCH_DESTINATIONS,
        trust=DestinationTrust.USER_CHOSEN,
        established_at=AT - timedelta(days=1),
    )


@dataclass
class _Wired:
    """The engine, the stores it shares with the servicing site, and the searcher.

    **One trail, one recipient-grant store and one trust store**, which is
    ``app/composition.py``'s own discipline and what ADR-0242 §15's journeys are stated
    over: the ruling the search records is the row ``grantable_decisions`` offers, the
    grant the engine establishes is the one the policy consults on the next search, and
    the record the trust act writes is the one the servicing site's ``trust_of`` reads.
    A harness holding two of any of them can seed authority and never *perform* it, which
    is the shape round 2 of this lane's review found.
    """

    engine: Any
    trail: FakeAuditTrail
    grants: FakeRecipientGrantStore
    trust: FakeDestinationTrustStore
    searcher: FakeWebSearcher


def _wired(*, composing: ComposingStage | None = None) -> _Wired:
    """The real pipeline over shared stores, with nothing seeded.

    That empty state is `origin/main`'s and ADR-0238 §14's own exit note — no grant, no
    trust record — so every journey below **performs** the acts rather than arranging
    their effects.

    **The planner asks for a search on both of a turn's calls**, which is ADR-0231 §12's
    own shape and what lets one ``converse`` reach both a servicing that yields and one
    that is refused: once a minted record is in the turn's supply, the binding of any
    later request in that turn carries ``planned_with_external_content``.
    """
    decisions = count(1)
    # The harness's own instant, so a grant established at AT is live when the next
    # ruling is taken at AT — ADR-0193 §6 refuses an ALLOW sourced from a grant
    # that was not live when the ruling was made, and the trail checks it independently.
    grants = FakeRecipientGrantStore(now=lambda: AT)
    trail = FakeAuditTrail(recipient_grants=grants)
    trust = FakeDestinationTrustStore()
    searcher = FakeWebSearcher(results=("a result",))
    harness = Harness(
        memory=FakeMemoryStore(now=lambda: AT),
        planner=_AskingPlanner(_search()),
        composing=composing,
        search=SearchServicer(
            composer=FakeQueryComposer(),
            searcher=_CostedSearcher(searcher),
            binder=_binder(),
            # The production policy over the **same** store the engine's establishing act
            # writes to, so a grant the user performs is one the next ruling consults —
            # ADR-0193 §1's narrow face, satisfied by the store structurally.
            policy=ThresholdActionPolicy(grants=grants),
            trail=trail,
            # The harness's own instant, so the ruling the search records and the answer
            # the engine writes when the grant act rides it share one timeline —
            # ADR-0235 §4 refuses a resolution decided before the confirmation it answers.
            now=lambda: AT,
            # **A prefix of its own**, because the harness mints ``d-N`` for the answers
            # its own operations record and the trail is append-only: two writers drawing
            # from one shape is a collision rather than a case.
            id_factory=lambda: f"search-d-{next(decisions)}",
            deadline=_DEADLINE,
        ),
        trail=trail,
        destination_trust=trust,
        recipient_grants=grants,
    )
    return _Wired(engine=harness.engine, trail=trail, grants=grants, trust=trust, searcher=searcher)


async def _refused_decision(wired: _Wired) -> str:
    """The id of the ``CONFIRM`` this deployment's first search recorded.

    Read from ``grantable_decisions`` — the engine's own listing — rather than from the
    trail, because that is the surface ADR-0235 §3 offers the grant act on and the one
    ADR-0242 §5's next-step line points at.
    """
    [offerable] = await wired.engine.grantable_decisions()
    return str(offerable.id)


# --- §15's journeys, performed through the engine's own operations ------------


async def test_the_first_refused_search_is_offered_as_a_grantable_decision() -> None:
    """§15 Arm 2(a) through the engine, and the row the journey starts from.

    No grant, a first search, a clean footing: the ruling is a ``CONFIRM``, the member is
    ``AUTHORISATION_AWAITED``, and **the decision it was recorded under is one the
    establishing act may ride** — which §8 says the member asserts and which is checked
    here against ``grantable_decisions`` rather than taken on the ADR's word.
    """
    composing, model = _recorder()
    wired = _wired(composing=composing)

    outcome = await wired.engine.converse(_ASKED, timeout=PATIENT)

    assert outcome.search_not_serviced is SearchNotServiced.AUTHORISATION_AWAITED
    assert _AWAITED_FRAGMENT in _system_prompt(model), (
        "§7's carrier reached the composing stage through the engine's own forwarding"
    )
    assert len(await wired.engine.grantable_decisions()) == 1
    assert wired.searcher.searched == [], "the search was ruled on and never made"


async def test_the_grant_act_makes_the_next_search_run_and_the_follow_up_ask_for_trust() -> None:
    """§15 Arm 2(b) through the engine, reached by **performing** ADR-0235's act.

    The grant is established through ``establish_recipient_grant`` over the decision the
    refused search recorded, so the ``ALLOW`` on the next turn is one the deployment's own
    thresholds authored over a grant the user made. The follow-up in that same turn is
    then composed over what the first search returned — ADR-0231 §12's shape — and is
    refused, and ``trust_of`` answering ``UNCHOSEN`` is the whole of what makes the member
    ``TRUST_MISSING`` rather than ``AUTHORISATION_AWAITED``.
    """
    wired = _wired()
    await wired.engine.converse(_ASKED, timeout=PATIENT)

    await wired.engine.establish_recipient_grant(
        await _refused_decision(wired), expires_at=AT + timedelta(days=30)
    )
    outcome = await wired.engine.converse(_ASKED, timeout=PATIENT)

    assert len(wired.searcher.searched) == 1, "the grant made one search reachable"
    assert outcome.search_not_serviced is SearchNotServiced.TRUST_MISSING


async def test_the_recovery_journey_ends_on_the_earlier_resolved_decision() -> None:
    """§15's recovery journey, walked through the engine's own operations.

    Grant, a follow-up refusal, ``grantable_decisions`` observed **empty**, the earlier
    resolved decision found through ``recent_decisions``, and the trust act performed on
    it — which is §9's clause made checkable: the decision recording the *refusal* carries
    ``planned_with_external_content`` so ADR-0235 §3's seventh condition excludes it, and
    the decision the user granted from has been **resolved** so §3's fourth condition has
    taken it out too. "``assistant remember-recipients`` can therefore be empty at exactly
    the moment its guidance is followed", which is why §9 sends the user to ``assistant
    decisions`` instead.
    """
    wired = _wired()
    await wired.engine.converse(_ASKED, timeout=PATIENT)
    granted_from = await _refused_decision(wired)
    await wired.engine.establish_recipient_grant(granted_from, expires_at=AT + timedelta(days=30))
    refused = await wired.engine.converse(_ASKED, timeout=PATIENT)

    assert refused.search_not_serviced is SearchNotServiced.TRUST_MISSING
    assert await wired.engine.grantable_decisions() == (), (
        "§9: the listing its guidance would have named is empty at exactly this moment"
    )
    listed = await wired.engine.recent_decisions()
    assert granted_from in {row.id for row in listed}, (
        "§9: `assistant decisions` carries resolved decisions, which is why it can hold "
        "an eligible id when the other listing cannot"
    )

    record = await wired.engine.establish_destination_trust(granted_from)

    assert await wired.engine.standing_destination_trust() == (record,), (
        "the act reaches the store the servicing site reads, which is the whole point of "
        "ADR-0238 §14's one wiring"
    )


async def test_the_act_reaches_the_search_and_does_not_repair_this_conversation() -> None:
    """§15 Arm 2c's end, and §9's monotonicity clause, over one engine.

    ADR-0238 §5's recorded half is monotone over a conversation: once a record has arrived
    from an ``UNCHOSEN`` destination that conversation "fails the recorded half for every
    later turn", and a trust record established afterwards does not lift it. So the same
    follow-up **retried in the same conversation** is still refused and now carries
    ``UNAVAILABLE`` — the member that names no act — while the same follow-up in a
    **fresh** conversation is serviced, which is the half the statement does promise.
    """
    wired = _wired()
    await wired.engine.converse(_ASKED, timeout=PATIENT)
    granted_from = await _refused_decision(wired)
    await wired.engine.establish_recipient_grant(granted_from, expires_at=AT + timedelta(days=30))
    refused = await wired.engine.converse(_ASKED, timeout=PATIENT)
    await wired.engine.establish_destination_trust(granted_from)

    retried = await wired.engine.converse(
        _ASKED, timeout=PATIENT, conversation_id=refused.conversation_id
    )
    fresh = await wired.engine.converse(_ASKED, timeout=PATIENT)

    assert refused.search_not_serviced is SearchNotServiced.TRUST_MISSING
    assert retried.search_not_serviced is SearchNotServiced.UNAVAILABLE, (
        "the act was performed and this conversation is still closed — naming an act "
        "that cannot help is worse than naming none (§8)"
    )
    assert fresh.search_not_serviced is None, (
        "§15 Arm 1: both servicings of a fresh conversation are serviced, which is what "
        "the trust act does change"
    )


async def test_revoking_the_trust_record_returns_the_next_follow_up_to_trust_missing() -> None:
    """§15 Arm 3(b) through the engine, by **performing** the revocation.

    Prospective: it takes effect for every later request and rewrites no recorded
    decision, so the ``ALLOW`` rulings recorded before it stay exactly as they were.
    """
    wired = _wired()
    await wired.engine.converse(_ASKED, timeout=PATIENT)
    granted_from = await _refused_decision(wired)
    await wired.engine.establish_recipient_grant(granted_from, expires_at=AT + timedelta(days=30))
    await wired.engine.converse(_ASKED, timeout=PATIENT)
    record = await wired.engine.establish_destination_trust(granted_from)
    before = {row.id: row.ruling.outcome for row in await wired.engine.recent_decisions()}

    assert await wired.engine.revoke_destination_trust(record.id) is True
    after_revocation = await wired.engine.converse(_ASKED, timeout=PATIENT)

    assert await wired.engine.standing_destination_trust() == ()
    assert after_revocation.search_not_serviced is SearchNotServiced.TRUST_MISSING
    rulings = {row.id: row.ruling.outcome for row in await wired.engine.recent_decisions()}
    assert {row: rulings[row] for row in before} == before, (
        "§4: a ruling recorded before the revocation is not rewritten"
    )


async def test_the_positive_path_services_both_its_searches_and_parks_nothing() -> None:
    """§15 Arm 1's assertion set, over the two servicings one ``converse`` performs.

    "A connection reference and origin configured; a first search recorded
    ``RULING_CONFIRM``; the recipient grant established through
    ``establish_recipient_grant``; trust established through
    ``establish_destination_trust`` over the same decision" — all four performed above —
    "then … each service a search, the second composed over records rather than the
    utterance alone. Asserts: the audit's ``servicings[].disposition`` is ``None`` on
    both, no confirmation is parked, and ``TurnOutcome.search_not_serviced`` is ``None``
    on both."

    Every one of those assertions is made here. What carries them is the **turn's two
    servicings** rather than two turns of the conversation, and the next case records
    why — with an issue against the ADR rather than a silent substitution.
    """
    wired = _wired()
    await _wired_through_to_trust(wired)

    with structlog.testing.capture_logs() as captured:
        outcome = await wired.engine.converse(_ASKED, timeout=PATIENT)

    servicings = [row for event in _audits(captured) for row in event["servicings"]]
    assert [row["disposition"] for row in servicings] == [None, None]
    assert [row["supplied"] for row in servicings] == [0, 1], (
        "§15 Arm 1: the second is composed over **records** rather than the utterance "
        "alone, which is ADR-0238 §2's supply widening on a `USER_CHOSEN` destination"
    )
    assert outcome.search_not_serviced is None
    assert outcome.step is None, "no confirmation is parked: this plan drove no step"
    assert await wired.engine.pending_confirmations() == ()


async def test_the_next_turn_of_a_conversation_that_searched_is_not_laundered_clean() -> None:
    """ADR-0238 §2's own clause, which is why §15 Arm 1's *second turn* is unreachable.

    **This arm records a conflict between two ratified ADRs rather than papering over
    one** (issue #2205). ADR-0242 §15 Arm 1 asks for "two turns of one conversation each
    service a search". ADR-0238 §2 rules the opposite in terms, and lanes B1 and B2
    implemented it: a turn's ``minted_user_chosen`` set is per-turn "because ADR-0231 §16
    makes a minted id resolve in no store and no later turn reach it — what a later turn
    has instead is the captured episode, which is **not** in this set and is exactly why
    **a conversation that searched yesterday is not laundered clean today**". That
    episode carries a recorded external span this decision did not mint, so ADR-0238 §8's
    early fold lowers the conversation's flag the moment it is admitted, §5's recorded
    half is monotone, and the next request is ruled ``CONFIRM``.

    **ADR-0242's own text settles which one governs.** §12: "It decides **no fact about
    any destination** … ADR-0238 §1 binds entire", and "§15's arms over them assert the
    *rendering* of an outcome those sections decide and never the outcome itself". So the
    outcome asserted here is the one ADR-0238 decides, and what this lane owes over it is
    the rendering: ``UNAVAILABLE``, the member that names no act — because the
    destination *is* chosen, so the trust act is not the answer, and nothing established
    now repairs the recorded half.
    """
    wired = _wired()
    await _wired_through_to_trust(wired)
    first = await wired.engine.converse(_ASKED, timeout=PATIENT)

    with structlog.testing.capture_logs() as captured:
        second = await wired.engine.converse(
            _ASKED, timeout=PATIENT, conversation_id=first.conversation_id
        )

    assert first.search_not_serviced is None
    assert [row["disposition"] for event in _audits(captured) for row in event["servicings"]] == [
        SearchDisposition.RULING_CONFIRM.value
    ]
    assert second.search_not_serviced is SearchNotServiced.UNAVAILABLE, (
        "§8: a `CONFIRM` on external footing at a destination the user **has** chosen "
        "names no act, because naming one that cannot help is worse than naming none"
    )
    fresh = await wired.engine.converse(_ASKED, timeout=PATIENT)
    assert fresh.search_not_serviced is None, (
        "and a fresh conversation searches exactly as the first did, which is the "
        "property §15 Arm 1 is really about"
    )


def _audits(captured: Sequence[Any]) -> list[Any]:
    """Every ``turn_read_request`` event in ``captured``, in the order it was written."""
    return [event for event in captured if event["event"] == "turn_read_request"]


async def test_a_turn_that_serviced_every_search_is_told_about_no_lookup_at_all() -> None:
    """§6, §15 Arm 1: the prompt on a turn carrying no member says nothing about one.

    Asserted over the whole vocabulary rather than over one member, so a lane that made
    the carrier unconditional would fail here whichever member it reached for. The
    byte-identity half of §6 is asserted at the loop, where two composes over *one* turn
    can be compared.
    """
    composing, model = _recorder()
    wired = _wired(composing=composing)
    await _wired_through_to_trust(wired)

    outcome = await wired.engine.converse(_ASKED, timeout=PATIENT)

    assert outcome.search_not_serviced is None
    prompt = _system_prompt(model)
    for fragment in _FRAGMENTS:
        assert fragment not in prompt


async def _wired_through_to_trust(wired: _Wired) -> None:
    """Perform both acts, in the order §5's next-step line names them."""
    await wired.engine.converse(_ASKED, timeout=PATIENT)
    granted_from = await _refused_decision(wired)
    await wired.engine.establish_recipient_grant(granted_from, expires_at=AT + timedelta(days=30))
    await wired.engine.establish_destination_trust(granted_from)


def test_the_quoted_fragments_are_the_eight_the_composing_stage_holds() -> None:
    """The clauses above are quotations, and this is what keeps them quotations.

    ADR-0242 §13 fixes the fragments as **eight literals, one per member**, so a lane
    editing one must edit the arm that reads it too — and a lane adding a ninth member
    finds this arm rather than a prompt with nothing in it.
    """
    from ai_assistant.orchestration import composing  # noqa: PLC0415 — one arm's subject

    written = composing._SEARCH_NOT_SERVICED_PROMPTS

    assert len(written) == len(SearchNotServiced) == len(_FRAGMENTS)
    for quoted in _FRAGMENTS:
        assert sum(quoted in text for text in written.values()) == 1, quoted
