"""ADR-0244's parked read, driven through the **engine** (§19).

The representative-input tests §18's last clause and §19 name, at the seams they are
about. §18 is explicit that four of this decision's rulings are **deliberately not**
suite clauses — "a generic conformance suite cannot see a wiring or the absence of a
call" — and names the three that this module is the site for: that **no model call
precedes a dispatch**, that **the value sent is the park's own ``parameters``**, and the
arms §19 lists. ``tests/permissions/parked_reads_contract.py`` carries Arm 9, the
store's own suite.

**Driven through the engine rather than through the servicing site**, because every arm
here is about something only the pipeline above that site has: the question is assembled
at the capture point, the answer runs through ``resume``, the continuation is a turn, and
``grantable_decisions`` is an engine operation. A loop-level case can reach none of them.

**The pipeline is the real one.** The production ``ThresholdActionPolicy`` over the same
recipient-grant store the engine's own act writes to, the real
:class:`~ai_assistant.orchestration.reads.SearchServicer`, the canonical
``FakeParkedReads`` wired as **one instance** into that servicer and the engine alike
(ADR-0244 §18's Lane 2 obligation, held here by the case), and the capture point that is
"the single place a ``TurnOutcome`` is built".
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import timedelta
from itertools import count
from typing import TYPE_CHECKING, Any, Final

import pytest
from test_engine import AT, PATIENT, Harness
from test_engine_read_envelope import _AskingPlanner, _recorder
from test_loop_search import (
    _ACCOUNT,
    _CONFIGURED_SEARCH,
    _DEADLINE,
    _binder,
    _CostedSearcher,
    _search,
)

from ai_assistant.core.errors import (
    AuditError,
    UngrantableActError,
    UnknownContinuationError,
)
from ai_assistant.core.types import (
    ContinuationToken,
    EgressBinding,
    MemoryKind,
    MemorySource,
    ParkedReadDisposition,
    PermissionDecision,
    PermissionOutcome,
    PermissionRuling,
    Placement,
    PlacementReach,
    PlacementSetter,
    Provenance,
    ReadAnswerOutcome,
    ReadCancellation,
    ReadKind,
    RecipientGrantNotEstablished,
    Role,
    SearchNotServiced,
    SearchRefusal,
    SemanticMemory,
)
from ai_assistant.orchestration.reads import SearchServicer, admitted_fourth_group
from ai_assistant.permissions.policy import ThresholdActionPolicy
from ai_assistant.testing import (
    FAKE_WEB_SEARCH,
    FakeAuditTrail,
    FakeEgressBinder,
    FakeMemoryStore,
    FakeParkedReads,
    FakeQueryComposer,
    FakeRecipientGrantStore,
    FakeWebSearcher,
)

if TYPE_CHECKING:
    from ai_assistant.orchestration.composing import ComposingStage
    from ai_assistant.testing import FakeModelProvider

_ASKED: Final = "what has changed since we last spoke"

#: ADR-0244 §3's lifetime for these cases. Long enough that nothing expires by accident;
#: the expiry arms move the **clock** rather than shortening this, because ADR-0059 §1's
#: comparison is against the clock's reading and a test advances it rather than waits.
_TTL: Final = timedelta(hours=24)

#: A distinctive clause of ADR-0244 §12's fixed fragment, quoted so the arm asserts the
#: **fragment** reached the prompt rather than that two prompts differ.
_AWAITING_FRAGMENT: Final = "waiting on an answer from this person before it can be made"

#: The clause ADR-0242 §7's ``UNAVAILABLE`` fragment carries — the literal #2221 records
#: as false, and the one ADR-0244 §12 exists to stop a parked turn saying.
_PRODUCED_NOTHING: Final = "that lookup produced nothing this turn could use"


@dataclass
class _Wired:
    """The engine and the stores it shares with the servicing site.

    **One trail, one recipient-grant store and one parked-read store**, which is
    ``app/composition.py``'s own discipline and what every arm here is stated over: the
    ruling the search records is the row the park names, and the park the servicing wrote
    is the one ``resume`` settles. A harness holding two of any of them can seed a state
    and never *reach* it.
    """

    engine: Any
    trail: FakeAuditTrail
    parks: FakeParkedReads
    searcher: FakeWebSearcher
    composer: FakeQueryComposer
    memory: FakeMemoryStore
    clock: _Clock
    #: The seam the servicing bound through, kept so a case can perform a **provisioning
    #: act on it** between the park and the answer — which is what ADR-0247 §12's Arms F
    #: and F' are driven by, and the one thing a re-derived binding is compared against.
    binder: FakeEgressBinder


class _Clock:
    """An injected clock a case advances rather than waits on (ADR-0009, ADR-0059 §1)."""

    def __init__(self) -> None:
        self.now = AT

    def __call__(self) -> Any:
        return self.now

    def advance(self, by: timedelta) -> None:
        """Move the reading forward, so a deadline passes without a case sleeping."""
        self.now += by


def _wired(
    *,
    composing: ComposingStage | None = None,
    configured: bool = False,
) -> _Wired:
    """The real pipeline over shared stores, with a parked-read store wired.

    Nothing is seeded: no recipient grant, so the production policy rules ``CONFIRM`` on
    the first search — which is the state #2221 records on the owner's own store and the
    one every arm below starts from.

    ``configured`` is ADR-0247's deployment, and it is a **different ground for the same
    park**: the policy is handed the destination this deployment is configured with, so
    §3's two retired floors no longer draw the ``CONFIRM``, and what draws it instead is
    the per-call cost ADR-0236 §4 leaves ``UNKNOWN`` where the operator declared no
    figure — which is exactly the shape §12's Arm E names. The searcher is then the bare
    fake and the seam holds its **uncosted** declaration, because a binding seam holding
    a different declaration refuses the request before any ruling is sought.
    """
    decisions = count(1)
    clock = _Clock()
    grants = FakeRecipientGrantStore(now=clock)
    trail = FakeAuditTrail(recipient_grants=grants)
    searcher = FakeWebSearcher(results=("a result about the bell tower",))
    composer = FakeQueryComposer()
    store = FakeParkedReads()
    memory = FakeMemoryStore(now=clock)
    binder = _binder(definition=FAKE_WEB_SEARCH) if configured else _binder()
    harness = Harness(
        memory=memory,
        planner=_AskingPlanner(_search()),
        composing=composing,
        now=clock,
        search=SearchServicer(
            composer=composer,
            searcher=searcher if configured else _CostedSearcher(searcher),
            binder=binder,
            policy=ThresholdActionPolicy(
                grants=grants,
                configured_search=_CONFIGURED_SEARCH if configured else None,
            ),
            trail=trail,
            now=clock,
            # **A prefix of its own**, because the harness mints ``d-N`` for the answers
            # its own operations record and the trail is append-only.
            id_factory=lambda: f"search-d-{next(decisions)}",
            deadline=_DEADLINE,
            # ADR-0244 §18's one-instance obligation: the **same** object the engine
            # answers through, so the park this servicing writes is the park that
            # ``resume`` settles.
            parked_reads=store,
            parked_read_ttl=_TTL,
        ),
        parked_reads=store,
        trail=trail,
        recipient_grants=grants,
    )
    return _Wired(
        engine=harness.engine,
        trail=trail,
        parks=store,
        searcher=searcher,
        composer=composer,
        memory=memory,
        clock=clock,
        binder=binder,
    )


def _system_prompt(model: FakeModelProvider, ordinal: int = -1) -> str:
    """The system message the production composing stage assembled, from the fake's record."""
    assert model.calls
    return next(one.content for one in model.calls[ordinal].messages if one.role is Role.SYSTEM)


async def _parked(wired: _Wired) -> Any:
    """The one open park this deployment holds, read through the contract."""
    [held] = await wired.parks.outstanding()
    return held


# --- Arm 1: the question appears and nothing is sent --------------------------


async def test_a_confirmed_search_writes_one_park_and_sends_nothing() -> None:
    """§19's Arm 1 (#2222 scenario 1), and ADR-0244 §1 entire.

    A servicing whose policy rules ``CONFIRM`` writes **one** park, opens no channel,
    admits no record, and returns a turn whose ``read_confirmation`` carries the exact
    query. **The turn does not park**: it composes and answers, so ``reply`` is present
    and ADR-0170 §4's three ``reply``-``None`` shapes are untouched.
    """
    composing, model = _recorder()
    wired = _wired(composing=composing)

    outcome = await wired.engine.converse(_ASKED, timeout=PATIENT)

    assert outcome.search_not_serviced is SearchNotServiced.ANSWER_AWAITED
    assert outcome.read_confirmation is not None
    assert outcome.read_confirmation.read is ReadKind.WEB_SEARCH
    assert outcome.read_answer is None, "a turn that parked a read answered none"
    assert outcome.reply is not None, "the turn composed and answered; what parked is the read"
    assert wired.searcher.searched == [], "nothing was sent"
    assert len(await wired.parks.outstanding()) == 1
    prompt = _system_prompt(model)
    assert _AWAITING_FRAGMENT in prompt
    assert _PRODUCED_NOTHING not in prompt, "#2221's literal, which §12 exists to stop"


async def test_the_question_carries_the_exact_query_and_the_destination() -> None:
    """ADR-0244 §4, §13: the confirmation renders the query byte for byte.

    "A surface that showed the user less than what would leave the device has not put
    ADR-0148 §8's question", and what a surface renders is
    :attr:`Confirmation.parameters` — so the arm is over the **parameters the ruling was
    taken over**, not over a summary this lane could have minted beside them.
    """
    wired = _wired()

    outcome = await wired.engine.converse(_ASKED, timeout=PATIENT)

    confirmation = outcome.read_confirmation
    assert confirmation is not None
    park = await _parked(wired)
    assert confirmation.parameters == park.parameters, "the park's own arguments, unaltered"
    assert confirmation.egress is not None, "ADR-0244 §4: always present on a WEB_SEARCH park"
    assert confirmation.egress.account_identity
    assert confirmation.tool_id, "the searcher's own registered declaration, by value"
    assert confirmation.reason, "the recorded CONFIRM's own reason (ADR-0042 §4)"


async def test_the_park_names_the_recorded_confirm_and_carries_the_parked_turn() -> None:
    """ADR-0244 §2: the park's durable identity is the **recorded decision**.

    And the two members §8's continuation would otherwise fabricate are persisted: the
    goal the turn was planned against, and the plan the planner returned.
    """
    wired = _wired()

    await wired.engine.converse(_ASKED, timeout=PATIENT)

    park = await _parked(wired)
    recorded = await wired.trail.get(park.decision_id)
    assert recorded is not None
    assert recorded.ruling.outcome is PermissionOutcome.CONFIRM
    assert recorded.step_id is None, "ADR-0231 §6: a WEB_SEARCH decision carries no step"
    assert recorded.execution_id is None, "and no execution"
    assert recorded.expires_at == park.expires_at, "ADR-0244 §3's shared deadline"
    assert park.goal is not None, "the goal §8 would otherwise fabricate"
    assert park.plan is not None, "and the plan"
    assert park.disposition is ParkedReadDisposition.OPEN


async def test_a_parked_decision_is_not_offered_to_the_establishing_act() -> None:
    """§19's Arm 8, last clause, and ADR-0244 §5's **eighth** condition.

    "A decision a park holds is answered through ``resume``, and answering it is what
    dispatches the read; the establishing act resumes nothing and services nothing" — so
    offering both on one row would let a user perform the act that changes nothing about
    this lookup while the lookup's own question stood unanswered beside it.
    """
    wired = _wired()

    await wired.engine.converse(_ASKED, timeout=PATIENT)

    assert await wired.engine.grantable_decisions() == ()


# --- Arm 2: approve dispatches once -------------------------------------------


async def test_an_approval_dispatches_once_and_returns_a_composed_turn() -> None:
    """§19's Arm 2 (#2222 scenario 2), and ADR-0244 §7 and §8.

    One request carrying the park's ``parameters`` **byte for byte**; the park settled
    ``APPROVED`` **before** the resolving ``ALLOW`` is recorded; and a ``TurnOutcome``
    whose ``turn`` is a real ``TurnResult`` carrying the minted records and whose reply
    is composed over them. That last is where ADR-0244 §8 partially supersedes ADR-0052
    §3, which would have returned ``TurnOutcome(turn=None, step=<resolution>)``.
    """
    wired = _wired()
    parked = await wired.engine.converse(_ASKED, timeout=PATIENT)
    park = await _parked(wired)
    assert parked.read_confirmation is not None

    outcome = await wired.engine.resume(
        parked.read_confirmation.token, approved=True, timeout=PATIENT
    )

    assert outcome.read_answer is ReadAnswerOutcome.DISPATCHED
    assert outcome.read_confirmation is None, "ADR-0244 §9's mutual exclusion"
    assert outcome.turn is not None, "a real TurnResult, not a recovered park's None"
    assert outcome.step is None, "a resumed read drives no step"
    assert outcome.routed is None, "and takes no route"
    assert outcome.reply is not None, "composed over the union (§8)"
    assert outcome.conversation_id == park.conversation_id
    [call] = wired.searcher.searched
    assert call.request.parameters == park.parameters, "the park's own arguments, byte for byte"
    assert outcome.turn.goal == park.goal, "the parked turn's goal, read from the park"
    assert outcome.turn.plan == park.plan, "and the parked turn's plan"
    assert [record.content for record in outcome.turn.memories[-1:]] == [
        "a result about the bell tower"
    ], "ADR-0226 §7's fourth group, appended in servicing order"


async def test_the_gate_is_taken_before_the_resolution_is_recorded() -> None:
    """ADR-0244 §6: **clause 5 before clause 6**, and that order is the decision.

    Asserted over the trail's own ordering: the resolving decision names the park's
    decision as what it resolves, and the park is terminal — so a reader finding an
    ``OPEN`` park beside a recorded resolution has met the window settling-second opens,
    which §6 says either strands the park or dispatches zero times.
    """
    wired = _wired()
    parked = await wired.engine.converse(_ASKED, timeout=PATIENT)
    assert parked.read_confirmation is not None
    park = await _parked(wired)

    await wired.engine.resume(parked.read_confirmation.token, approved=True, timeout=PATIENT)

    settled = await wired.parks.get(park.id)
    assert settled is not None
    assert settled.disposition is ParkedReadDisposition.APPROVED
    resolutions = [row for row in await wired.trail.recent() if row.resolves == park.decision_id]
    assert len(resolutions) == 1
    assert resolutions[0].ruling.outcome is PermissionOutcome.ALLOW


async def test_the_settlement_clears_the_content_the_park_held() -> None:
    """ADR-0244 §3: "the content lives exactly as long as the question does".

    The retention rule, checked at the seam rather than in the store's own suite,
    because what it is about here is that the **engine** reads ``goal`` and ``plan`` off
    the park it settled rather than off a row the settlement has since cleared.
    """
    wired = _wired()
    parked = await wired.engine.converse(_ASKED, timeout=PATIENT)
    assert parked.read_confirmation is not None
    park = await _parked(wired)

    outcome = await wired.engine.resume(
        parked.read_confirmation.token, approved=True, timeout=PATIENT
    )

    settled = await wired.parks.get(park.id)
    assert settled is not None
    assert settled.parameters is None, "the query is gone the moment the read is dispatched"
    assert settled.goal is None, "and the goal"
    assert settled.plan is None, "and the plan"
    assert outcome.turn is not None, "and the continuation composed over them anyway"


async def test_a_second_answer_dispatches_nothing_and_says_so() -> None:
    """§19's Arm 2, second half — one of the three arms §19 names as load-bearing.

    "One answer, at most one dispatch, however many times a token is presented." The
    second call consults no policy, opens no channel, records nothing and mints nothing.
    """
    wired = _wired()
    parked = await wired.engine.converse(_ASKED, timeout=PATIENT)
    assert parked.read_confirmation is not None
    token = parked.read_confirmation.token
    await wired.engine.resume(token, approved=True, timeout=PATIENT)
    sent = len(wired.searcher.searched)
    rows = len(await wired.trail.recent())

    again = await wired.engine.resume(token, approved=True, timeout=PATIENT)

    assert again.read_answer is ReadAnswerOutcome.ALREADY_SETTLED
    assert again.turn is None, "nothing was composed"
    assert again.reply is None, "and nothing was answered"
    assert len(wired.searcher.searched) == sent, "nothing further was sent"
    assert len(await wired.trail.recent()) == rows, "and nothing further was recorded"


async def test_no_model_call_precedes_the_dispatch() -> None:
    """ADR-0244 §7, §16, and one of §18's four "deliberately not suite clauses".

    "``QueryComposer`` is not called at resume, no model call precedes the send, and the
    value passed to the searcher is the park's own ``parameters``." A generic suite
    cannot see the *absence* of a call; this is the site where it can.
    """
    wired = _wired()
    parked = await wired.engine.converse(_ASKED, timeout=PATIENT)
    assert parked.read_confirmation is not None
    composed_before = len(wired.composer.utterances)

    await wired.engine.resume(parked.read_confirmation.token, approved=True, timeout=PATIENT)

    assert len(wired.composer.utterances) == composed_before, (
        "no query was composed at resume: what was composed in the parked turn is what is sent"
    )


# --- Arm 3: deny --------------------------------------------------------------


async def test_a_denial_settles_the_park_records_a_deny_and_sends_nothing() -> None:
    """§19's Arm 3 (#2222 scenario 3), and ADR-0244 §10.

    ``turn`` and ``reply`` both ``None`` — ADR-0170 §4's second shape exactly — and the
    parked turn's own reply stands: nothing rewrites it, and this outcome carries no
    turn to replace it with.
    """
    wired = _wired()
    parked = await wired.engine.converse(_ASKED, timeout=PATIENT)
    assert parked.read_confirmation is not None
    park = await _parked(wired)

    outcome = await wired.engine.resume(
        parked.read_confirmation.token, approved=False, timeout=PATIENT
    )

    assert outcome.read_answer is ReadAnswerOutcome.DECLINED
    assert outcome.turn is None, "ADR-0170 §4's second shape"
    assert outcome.reply is None, "and no prose beside it"
    assert outcome.reply_degraded is False, "nothing was owed, so nothing degraded"
    assert wired.searcher.searched == [], "no channel was opened"
    settled = await wired.parks.get(park.id)
    assert settled is not None
    assert settled.disposition is ParkedReadDisposition.DENIED
    resolutions = [row for row in await wired.trail.recent() if row.resolves == park.decision_id]
    assert len(resolutions) == 1
    assert resolutions[0].ruling.outcome is PermissionOutcome.DENY


# --- Arm 5: expiry ------------------------------------------------------------


async def test_an_expired_park_is_not_enumerated_and_answers_expired() -> None:
    """§19's Arm 5 (#2222 scenario 5), in **both** of its halves.

    Where the ``resume`` is the operation that settles it, and where an enumeration
    settled it first — ADR-0244 §9 states ``EXPIRED`` over the **disposition** rather
    than over which call discovered it, so the two read the same to the user.
    """
    wired = _wired()
    parked = await wired.engine.converse(_ASKED, timeout=PATIENT)
    assert parked.read_confirmation is not None
    park = await _parked(wired)
    wired.clock.advance(_TTL + timedelta(minutes=1))

    listed = await wired.engine.pending_confirmations()

    assert [one for one in listed if one.read is not None] == [], "not offered"
    settled = await wired.parks.get(park.id)
    assert settled is not None
    assert settled.disposition is ParkedReadDisposition.EXPIRED
    assert settled.parameters is None, "and its content was cleared"

    answered = await wired.engine.resume(
        parked.read_confirmation.token, approved=True, timeout=PATIENT
    )

    assert answered.read_answer is ReadAnswerOutcome.EXPIRED
    assert wired.searcher.searched == [], "nothing was dispatched"


async def test_an_expiry_this_answer_discovers_reads_the_same_to_the_user() -> None:
    """The other half of Arm 5: no enumeration ran, and the answer settles it itself."""
    wired = _wired()
    parked = await wired.engine.converse(_ASKED, timeout=PATIENT)
    assert parked.read_confirmation is not None
    park = await _parked(wired)
    wired.clock.advance(_TTL + timedelta(minutes=1))

    answered = await wired.engine.resume(
        parked.read_confirmation.token, approved=True, timeout=PATIENT
    )

    assert answered.read_answer is ReadAnswerOutcome.EXPIRED
    settled = await wired.parks.get(park.id)
    assert settled is not None
    assert settled.disposition is ParkedReadDisposition.EXPIRED
    assert wired.searcher.searched == []


async def test_an_expired_parks_decision_does_not_return_to_the_grantable_listing() -> None:
    """ADR-0244 §5, §10: "an expiry makes no decision grantable".

    §5's eighth condition stops excluding an ``EXPIRED`` park's decision, and ADR-0235
    §3's **fifth** then refuses it on its own — the decision carries the same deadline
    the park does — so the row does not return. **The arm fails an implementation that
    stamped the park's deadline and not the decision's.**
    """
    wired = _wired()
    await wired.engine.converse(_ASKED, timeout=PATIENT)
    wired.clock.advance(_TTL + timedelta(minutes=1))
    await wired.engine.pending_confirmations()

    assert await wired.engine.grantable_decisions() == ()


async def test_a_cancelled_parks_decision_does_return_to_the_grantable_listing() -> None:
    """§19's Arm 8, and the discrimination ADR-0244 §5 draws between the two.

    "A cancelled park's decision is therefore the one that returns to the listing", where
    the other six conditions hold — because a cancellation writes no resolution and never
    will, and nothing about the decision's own deadline has passed.
    """
    wired = _wired()
    parked = await wired.engine.converse(_ASKED, timeout=PATIENT)
    assert parked.read_confirmation is not None

    assert (
        await wired.engine.cancel_read(parked.read_confirmation.token) is ReadCancellation.WITHDRAWN
    )

    assert len(await wired.engine.grantable_decisions()) == 1


# --- Arm 6: the changed operation ---------------------------------------------


async def test_unconfiguring_refuses_an_open_parks_answer_as_unavailable() -> None:
    """ADR-0247 §12's **Arm G**, over the production ``parked_reads`` path.

    "With a park open and the deployment holding no search registration, the answer rules
    nothing, dispatches nothing and returns ``UNAVAILABLE_NOW``; the park is still
    ``OPEN``." The arm exists because lane 4 deletes the ``max_calls == 0`` limb beside
    this one and must not disturb it: the no-searcher limb is taken **before** the
    conversation is read, and it is what a deployment that disconnected its search
    account answers.

    The limb this replaces was ADR-0238 §8's bound of ``0``, which ADR-0247 §5 removes —
    so the deployment fact an answer can still meet is this one and the conversation's
    own existence, which ``test_an_answer_for_a_deleted_conversation_is_refused_as_unavailable``
    drives through ``ConversationStore.get`` (ADR-0247 §6).
    """
    wired = _wired()
    parked = await wired.engine.converse(_ASKED, timeout=PATIENT)
    assert parked.read_confirmation is not None
    park = await _parked(wired)
    # The deployment's own configuration, changed under a standing question — which is
    # exactly the state §6's clause 2 is written for.
    wired.engine._parked_reads._search = None

    outcome = await wired.engine.resume(
        parked.read_confirmation.token, approved=True, timeout=PATIENT
    )

    assert outcome.read_answer is ReadAnswerOutcome.UNAVAILABLE_NOW
    assert wired.searcher.searched == []
    assert [row for row in await wired.trail.recent() if row.resolves] == [], "nothing was ruled"
    still_open = await wired.parks.get(park.id)
    assert still_open is not None
    assert still_open.disposition is ParkedReadDisposition.OPEN, "and the park is not spent"


# --- Arm 7: cancellation ------------------------------------------------------


async def test_cancelling_an_open_park_withdraws_it_and_records_no_ruling() -> None:
    """§19's Arm 7, first state, and ADR-0244 §11.

    "The whole difference from a denial": a denial is the user answering *no* and is a
    ruling; a cancellation is the user withdrawing the question and is not one.
    """
    wired = _wired()
    parked = await wired.engine.converse(_ASKED, timeout=PATIENT)
    assert parked.read_confirmation is not None
    park = await _parked(wired)

    assert (
        await wired.engine.cancel_read(parked.read_confirmation.token) is ReadCancellation.WITHDRAWN
    )

    settled = await wired.parks.get(park.id)
    assert settled is not None
    assert settled.disposition is ParkedReadDisposition.CANCELLED
    assert settled.parameters is None, "cleared in the same step"
    assert [row for row in await wired.trail.recent() if row.resolves] == [], "no ruling recorded"
    assert wired.searcher.searched == [], "and nothing was sent"


async def test_cancelling_a_settled_park_answers_that_there_is_nothing_to_cancel() -> None:
    """§19's Arm 7, third state: "on a settled park with nothing running"."""
    wired = _wired()
    parked = await wired.engine.converse(_ASKED, timeout=PATIENT)
    assert parked.read_confirmation is not None
    await wired.engine.resume(parked.read_confirmation.token, approved=False, timeout=PATIENT)

    assert (
        await wired.engine.cancel_read(parked.read_confirmation.token)
        is ReadCancellation.NOTHING_TO_CANCEL
    )


async def test_an_answer_after_a_cancellation_is_already_settled() -> None:
    """ADR-0244 §11: **neither party acts on a park the other took.**

    The cancellation took the gate, so the answer that follows rules nothing, records
    nothing and sends nothing.
    """
    wired = _wired()
    parked = await wired.engine.converse(_ASKED, timeout=PATIENT)
    assert parked.read_confirmation is not None
    await wired.engine.cancel_read(parked.read_confirmation.token)

    outcome = await wired.engine.resume(
        parked.read_confirmation.token, approved=True, timeout=PATIENT
    )

    assert outcome.read_answer is ReadAnswerOutcome.ALREADY_SETTLED
    assert wired.searcher.searched == []


async def test_an_unknown_token_is_refused_and_never_denied() -> None:
    """ADR-0244 §11, ADR-0084 §7: an unknown token raises, exactly as ``resume`` does.

    **Never a ``NOTHING_TO_CANCEL``**, which would tell a caller its question was already
    gone when in fact this engine never held it.
    """
    wired = _wired()

    with pytest.raises(UnknownContinuationError):
        await wired.engine.cancel_read(ContinuationToken(handle="never-minted"))


# --- Arm 4: restart -----------------------------------------------------------


async def test_a_park_survives_a_restart_and_is_offered_with_a_fresh_token() -> None:
    """§19's Arm 4 (#2222 scenario 4), and ADR-0244 §5 and §15.

    "Nothing durable holds a token", so a restart empties the handle table and the next
    ``pending_confirmations`` re-mints from durable state — and the park re-offered is
    the **same** park, named by the same decision.
    """
    wired = _wired()
    parked = await wired.engine.converse(_ASKED, timeout=PATIENT)
    assert parked.read_confirmation is not None
    park = await _parked(wired)
    # A restart, modelled as this engine's own handle table emptying — which is what
    # ADR-0084 §7 says a restart does to it, and what a second engine over the same
    # durable state would meet.
    wired.engine._read_parks.clear()

    offered = [one for one in await wired.engine.pending_confirmations() if one.read is not None]

    assert len(offered) == 1
    assert offered[0].parameters == park.parameters, "the same content"
    assert offered[0].token != parked.read_confirmation.token, "and a freshly minted token"

    outcome = await wired.engine.resume(offered[0].token, approved=True, timeout=PATIENT)

    assert outcome.read_answer is ReadAnswerOutcome.DISPATCHED
    assert len(wired.searcher.searched) == 1, "exactly once, after the restart"


async def test_enumeration_is_idempotent_and_reuses_the_handle_it_minted() -> None:
    """ADR-0244 §5: "a park already named by a handle reuses that handle".

    ADR-0052 §2's reconciliation at a second population, and what keeps a surface's token
    stable across two listings.
    """
    wired = _wired()
    await wired.engine.converse(_ASKED, timeout=PATIENT)

    first = [one for one in await wired.engine.pending_confirmations() if one.read is not None]
    second = [one for one in await wired.engine.pending_confirmations() if one.read is not None]

    assert [one.token for one in first] == [one.token for one in second]


# --- Arm 8: the refusal arms --------------------------------------------------


async def test_a_second_park_for_one_conversation_takes_the_undiscriminated_member() -> None:
    """§19's Arm 8, third clause, and ADR-0244 §1's third clause with §12's table.

    "A second park for one conversation is refused by the store and the servicing takes
    ADR-0242 §8's undiscriminated member." Driven by a second turn of the **same**
    conversation while the first question stands — which is the state ADR-0244 §14 says
    a conversation with an open park is in: it still converses, plans and services every
    other read kind, and what it does not do is write a second park.
    """
    wired = _wired()
    first = await wired.engine.converse(_ASKED, timeout=PATIENT)

    second = await wired.engine.converse(
        _ASKED, timeout=PATIENT, conversation_id=first.conversation_id
    )

    assert second.search_not_serviced is not SearchNotServiced.ANSWER_AWAITED
    assert second.read_confirmation is None, "no park was written, so no question is reported"
    assert len(await wired.parks.outstanding()) == 1, "still one open park"
    assert second.reply is not None, "and the turn answered"


# --- §14: a park blocks nothing ----------------------------------------------


async def test_a_conversation_with_an_open_park_still_converses() -> None:
    """ADR-0244 §14: "no lane blocks, queues, defers or fails a turn on account of an
    open park", and a park holds no execution slot, step or claim.

    Driven over a **second** conversation as well as the first, because §3's rule is
    per conversation and §14's is per turn: what an open park bounds is that
    conversation's next *park*, and nothing else about any turn anywhere.
    """
    wired = _wired()
    first = await wired.engine.converse(_ASKED, timeout=PATIENT)

    # The same utterance, because this harness's planner mints one goal id per
    # deployment and a second statement under it is the audit hazard `save_goal`
    # refuses. What the arm is about is the **conversation**, not the words.
    second = await wired.engine.converse(_ASKED, timeout=PATIENT)

    assert second.reply is not None, "a different conversation converses unaffected"
    assert second.conversation_id != first.conversation_id
    assert len(await wired.parks.outstanding()) == 2, "one open park each, and no more"


# --- Arm 11: two concurrent answers ------------------------------------------


async def test_two_concurrent_answers_produce_one_settlement_and_one_dispatch() -> None:
    """§19's Arm 11 — one of the three arms §19 names as load-bearing.

    "Two ``resume`` calls on one token produce **one** settlement, **one** recorded
    resolution and **one** dispatch; the loser returns ``ALREADY_SETTLED``, consults no
    policy, records nothing and **raises nothing**."

    **Both callers reach clause 5, which is what §19 requires and what neither a bare
    ``asyncio.gather`` nor a pause at the *ruling* produces.** Held at the **store's own
    compare-and-swap**: the first ``settle`` to arrive is suspended inside it, so the
    second caller passes clauses 1 to 4 over a park that is still ``OPEN``, reaches the gate
    and takes it — and the first then loses the write it was holding. Two gate attempts,
    one settlement, and a loser that arrived at clause 5 rather than bouncing off clause
    1, which is the interleaving an implementation whose losing path acts anyway
    survives every weaker construction of.

    **"Consults no policy" is asserted over counts** rather than inferred from the
    member: the gate records every attempt and the paused policy records every
    ``resolve`` it is asked, and one of each is what one settlement buys.
    """
    wired = _wired()
    parked = await wired.engine.converse(_ASKED, timeout=PATIENT)
    assert parked.read_confirmation is not None
    token = parked.read_confirmation.token
    park = await _parked(wired)
    gate = _GatedSettle(wired.parks)
    wired.engine._parked_reads._store = gate
    counted = _SuspendingResolution(wired.engine._loop._search._policy)
    counted.release.set()  # counted, not held: this case pauses at the gate instead
    wired.engine._loop._search._policy = counted
    held = asyncio.create_task(wired.engine.resume(token, approved=True, timeout=PATIENT))
    await gate.reached.wait()

    # The second caller passes clauses 1-4 over a park the first has read but not yet
    # written, so it reaches the gate too — which is the state §19 Arm 11 is about.
    second = await wired.engine.resume(token, approved=True, timeout=PATIENT)

    gate.release.set()
    first = await held

    assert gate.attempts == 2, "both answers reached the compare-and-swap"
    members = sorted(outcome.read_answer for outcome in (first, second) if outcome.read_answer)
    assert members == sorted([ReadAnswerOutcome.ALREADY_SETTLED, ReadAnswerOutcome.DISPATCHED]), (
        "exactly one of them took the park's one answer"
    )
    assert counted.resolutions == 1, "the loser consulted no policy"
    assert len(wired.searcher.searched) == 1, "one dispatch"
    resolutions = [row for row in await wired.trail.recent() if row.resolves == park.decision_id]
    assert len(resolutions) == 1, "one recorded resolution"
    loser = next(
        one for one in (first, second) if one.read_answer is not ReadAnswerOutcome.DISPATCHED
    )
    assert loser.turn is None, "and the loser composed nothing"


async def test_an_approval_racing_a_denial_leaves_the_park_and_the_trail_agreeing() -> None:
    """§19's Arm 12: one settlement, one recorded ruling, and the two say the same thing."""
    wired = _wired()
    parked = await wired.engine.converse(_ASKED, timeout=PATIENT)
    assert parked.read_confirmation is not None
    token = parked.read_confirmation.token
    park = await _parked(wired)

    outcomes = await asyncio.gather(
        wired.engine.resume(token, approved=True, timeout=PATIENT),
        wired.engine.resume(token, approved=False, timeout=PATIENT),
    )

    assert sum(1 for one in outcomes if one.read_answer is ReadAnswerOutcome.ALREADY_SETTLED) == 1
    settled = await wired.parks.get(park.id)
    assert settled is not None
    resolutions = [row for row in await wired.trail.recent() if row.resolves == park.decision_id]
    assert len(resolutions) == 1
    expected = (
        PermissionOutcome.ALLOW
        if settled.disposition is ParkedReadDisposition.APPROVED
        else PermissionOutcome.DENY
    )
    assert resolutions[0].ruling.outcome is expected, (
        "the park's disposition and the trail's recorded answer say the same thing"
    )


# --- Arm 6: the changed operation, the two limbs a wrapper reaches ------------


class _RefusingResolution:
    """A policy that rules as the production one does and **refuses the resolution**.

    ADR-0244 §6's clause 6 in the state ``AUTHORITY_CHANGED`` is reserved for: an
    approving answer the policy refused at the instant of the answer. It is reachable in
    a real deployment — a threshold an operator lowered while the question stood — and
    unreachable through this pipeline's own inputs, so the *policy* is what a case
    varies rather than a `Settings` value the servicer does not read.
    """

    def __init__(self, inner: ThresholdActionPolicy) -> None:
        self._inner = inner

    async def decide(self, request: Any) -> Any:
        return await self._inner.decide(request)

    async def resolve(self, confirmed: Any, *, approved: bool) -> Any:
        from ai_assistant.core.types import PermissionRuling  # noqa: PLC0415 — one class's subject

        del confirmed, approved
        return PermissionRuling(
            outcome=PermissionOutcome.DENY,
            reason="the thresholds moved while the question stood",
        )


class _RefusingRebind:
    """A binder that binds as the real one does and **refuses every rebind**.

    ADR-0152 §7's refusal, which ADR-0244 §6's clause 4 reaches: "a destination, an
    account identity or a payload description that moved between the question and the
    answer is a refusal, not a send". Nothing a case can pass through this pipeline moves
    a destination under a standing question, so the seam is what a case varies.
    """

    def __init__(self, inner: Any) -> None:
        self._inner = inner

    async def bind(self, *args: Any, **kwargs: Any) -> Any:
        return await self._inner.bind(*args, **kwargs)

    async def rebind(self, *args: Any, **kwargs: Any) -> Any:
        del args, kwargs
        return None


async def test_a_policy_that_refuses_the_answer_records_it_and_dispatches_nothing() -> None:
    """§19's Arm 6, second limb: ``AUTHORITY_CHANGED``, **with the answer recorded**.

    ADR-0004 §7's reason: "a ruling the trail never sees is a decision nobody can audit".
    The park is spent either way — the gate was taken before the policy was asked — and
    nothing was dispatched.
    """
    wired = _wired()
    parked = await wired.engine.converse(_ASKED, timeout=PATIENT)
    assert parked.read_confirmation is not None
    park = await _parked(wired)
    servicer = wired.engine._loop._search
    servicer._policy = _RefusingResolution(servicer._policy)

    outcome = await wired.engine.resume(
        parked.read_confirmation.token, approved=True, timeout=PATIENT
    )

    assert outcome.read_answer is ReadAnswerOutcome.AUTHORITY_CHANGED
    assert wired.searcher.searched == [], "nothing was dispatched"
    resolutions = [row for row in await wired.trail.recent() if row.resolves == park.decision_id]
    assert len(resolutions) == 1, "the answer **is** recorded whatever it is"
    assert resolutions[0].ruling.outcome is PermissionOutcome.DENY
    settled = await wired.parks.get(park.id)
    assert settled is not None
    assert settled.disposition is ParkedReadDisposition.APPROVED, "the park is spent either way"


async def test_a_binding_that_no_longer_derives_equal_refuses_with_no_ruling_recorded() -> None:
    """§19's Arm 6, first limb: ``OPERATION_CHANGED`` and **no ruling recorded**.

    Clause 4 precedes the gate, so the park is left ``OPEN``: "a park spent on an answer
    the subject check would have refused is an answer the user has to give again for no
    reason" (ADR-0244 §6).
    """
    wired = _wired()
    parked = await wired.engine.converse(_ASKED, timeout=PATIENT)
    assert parked.read_confirmation is not None
    park = await _parked(wired)
    servicer = wired.engine._loop._search
    servicer._binder = _RefusingRebind(servicer._binder)

    outcome = await wired.engine.resume(
        parked.read_confirmation.token, approved=True, timeout=PATIENT
    )

    assert outcome.read_answer is ReadAnswerOutcome.OPERATION_CHANGED
    assert wired.searcher.searched == []
    assert [row for row in await wired.trail.recent() if row.resolves] == [], "no ruling"
    still_open = await wired.parks.get(park.id)
    assert still_open is not None
    assert still_open.disposition is ParkedReadDisposition.OPEN, "the park is not spent"


async def test_a_park_whose_parameters_do_not_hash_to_the_digest_dispatches_nothing() -> None:
    """§19's Arm 8, second clause, and ADR-0244 §2's parameter check.

    "``parameters`` are the ruling's own and are **checked against the recorded
    ``CONFIRM``, not trusted from the store**." Driven by dropping the park this
    servicing wrote and writing one over the same decision whose arguments differ, which
    is the state a tampered or a corrupted row is in.

    **``PermissionDecision.authorises`` is not this check and cannot be**: it is ``True``
    only of an ``ALLOW``, so it is ``False`` of every ``CONFIRM`` by construction — a lane
    collapsing the two would refuse every parked read, which is why the digest comparison
    is written out.
    """
    wired = _wired()
    await wired.engine.converse(_ASKED, timeout=PATIENT)
    park = await _parked(wired)
    assert await wired.parks.drop_for_conversation(park.conversation_id) == 1
    tampered = park.model_copy(
        update={"parameters": {"origin": "search.example", "query": "something else entirely"}}
    )
    assert await wired.parks.park(tampered) is True
    [offered] = [one for one in await wired.engine.pending_confirmations() if one.read]

    outcome = await wired.engine.resume(offered.token, approved=True, timeout=PATIENT)

    assert outcome.read_answer is ReadAnswerOutcome.OPERATION_CHANGED
    assert wired.searcher.searched == [], "nothing was dispatched"
    assert [row for row in await wired.trail.recent() if row.resolves] == [], "and nothing ruled"


# --- Arms 10 and 14: the states a crash and a restart leave behind ------------


async def test_a_park_settled_with_no_ruling_recorded_answers_already_settled() -> None:
    """§19's Arm 10: the crash between the gate and the ruling.

    "With the park settled ``APPROVED`` and no resolution recorded, the next ``resume``
    returns ``ALREADY_SETTLED``, the next ``pending_confirmations`` does not list the
    park, **nothing is dispatched**, and no ruling appears in the trail." Driven by
    settling at the seam and stopping before ``resolve`` — the state ADR-0244 §6 admits
    by name: "a bounded loss of one answer, preferred to the unbounded hazard the other
    order carries".
    """
    wired = _wired()
    parked = await wired.engine.converse(_ASKED, timeout=PATIENT)
    assert parked.read_confirmation is not None
    park = await _parked(wired)
    await wired.parks.settle(
        park.id, disposition=ParkedReadDisposition.APPROVED, at=wired.clock.now
    )

    outcome = await wired.engine.resume(
        parked.read_confirmation.token, approved=True, timeout=PATIENT
    )

    assert outcome.read_answer is ReadAnswerOutcome.ALREADY_SETTLED
    assert wired.searcher.searched == [], "nothing was dispatched"
    assert [row for row in await wired.trail.recent() if row.resolves] == [], "and no ruling"
    assert [one for one in await wired.engine.pending_confirmations() if one.read] == []


async def test_the_grantable_exclusion_survives_a_restart() -> None:
    """§19's Arm 14: the exclusion is held by the **row**, not in memory.

    "With a park settled ``DENIED``, no resolution recorded, its deadline not passed and
    the engine rebuilt over the same durable state, ``park_of_decision`` answers that
    terminal row, ``grantable_decisions`` omits its decision, and
    ``establish_recipient_grant`` on it raises ``UngrantableActError``." **The arm fails
    an implementation holding the exclusion in memory**, which is why the handle table is
    cleared before the listing is asked.
    """
    wired = _wired()
    await wired.engine.converse(_ASKED, timeout=PATIENT)
    park = await _parked(wired)
    await wired.parks.settle(park.id, disposition=ParkedReadDisposition.DENIED, at=wired.clock.now)
    wired.engine._read_parks.clear()

    held = await wired.parks.park_of_decision(park.decision_id)

    assert held is not None
    assert held.disposition is ParkedReadDisposition.DENIED
    assert await wired.engine.grantable_decisions() == ()
    with pytest.raises(UngrantableActError, match="parked read"):
        await wired.engine.establish_recipient_grant(
            park.decision_id, expires_at=wired.clock.now + timedelta(days=30)
        )


# --- Arms 7 and 13: what happens while an answer is in flight ----------------


class _SuspendingResolution:
    """A policy that holds its ``resolve`` open until a case releases it.

    ADR-0244 §19's Arm 13 is stated over exactly this pause — "with a ``resume`` paused
    **after** its settlement and before its recorded ruling" — because that is the window
    §5's eighth condition exists to close: the park is already ``APPROVED`` and the trail
    holds no resolution, so a condition stated over an *open* park alone would offer the
    establishing act a decision the answering call is about to resolve.
    """

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.reached = asyncio.Event()
        self.release = asyncio.Event()
        #: How many callers reached ``resolve``. The loser's "consults no policy" clause
        #: is a statement about this number and not about the member it returned.
        self.resolutions = 0

    async def decide(self, request: Any) -> Any:
        return await self._inner.decide(request)

    async def resolve(self, confirmed: Any, *, approved: bool) -> Any:
        self.resolutions += 1
        self.reached.set()
        await self.release.wait()
        return await self._inner.resolve(confirmed, approved=approved)


class _SuspendingSearcher:
    """A searcher that holds its ``search`` open until a case releases it.

    ADR-0244 §19's Arm 7, second state: a dispatch **in flight**, which is the only state
    ``INTERRUPTED`` names and which no synchronous fake can be in.
    """

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.reached = asyncio.Event()
        self.release = asyncio.Event()

    @property
    def name(self) -> str:
        return str(self._inner.name)

    async def request(self, query: str, /) -> Any:
        return await self._inner.request(query)

    async def search(self, call: Any, /, *, timeout: timedelta) -> Any:  # noqa: ASYNC109 — the seam owns the deadline, as the contract declares it
        self.reached.set()
        await self.release.wait()
        return await self._inner.search(call, timeout=timeout)


async def test_the_establishing_act_is_refused_while_an_answer_is_between_gate_and_ruling() -> None:
    """§19's Arm 13, and the property ADR-0244 §5's eighth condition exists to have.

    **The arm fails an implementation whose eighth condition is stated over an ``OPEN``
    park alone**: at the pause the park is ``APPROVED`` and no resolution is recorded, so
    such an implementation would offer the act on a decision whose answer is mid-flight —
    recording an ``ALLOW`` the user never gave that answer for, and leaving the answering
    call's own append to fail.
    """
    wired = _wired()
    parked = await wired.engine.converse(_ASKED, timeout=PATIENT)
    assert parked.read_confirmation is not None
    park = await _parked(wired)
    servicer = wired.engine._loop._search
    paused = _SuspendingResolution(servicer._policy)
    servicer._policy = paused
    answering = asyncio.create_task(
        wired.engine.resume(parked.read_confirmation.token, approved=True, timeout=PATIENT)
    )
    await paused.reached.wait()

    settled = await wired.parks.get(park.id)
    assert settled is not None
    assert settled.disposition is ParkedReadDisposition.APPROVED, "the gate is already taken"
    assert [row for row in await wired.trail.recent() if row.resolves] == [], "and no ruling yet"
    assert await wired.engine.grantable_decisions() == ()
    with pytest.raises(UngrantableActError, match="parked read"):
        await wired.engine.establish_recipient_grant(
            park.decision_id, expires_at=wired.clock.now + timedelta(days=30)
        )
    assert [one for one in await wired.engine.pending_confirmations() if one.read] == [], (
        "a concurrent enumeration during the pause does not list the park"
    )
    assert wired.searcher.searched == [], "and dispatches nothing"

    paused.release.set()
    outcome = await answering

    assert outcome.read_answer is ReadAnswerOutcome.DISPATCHED
    assert len(wired.searcher.searched) == 1, "the paused answer then records its ruling and sends"


async def test_cancelling_a_dispatch_in_flight_interrupts_it_and_leaves_the_park_approved() -> None:
    """§19's Arm 7, second state, and ADR-0244 §11.

    "What is cancelled is the ``resume`` call running the dispatch, and **no
    ``TurnOutcome`` is produced for it**" — the cancellation is a teardown and is
    converted into neither an outcome nor a refusal. "A cancelled dispatch leaves the
    park ``APPROVED`` and does not re-open it": the question was answered, the call was
    made, and **no caller assumes the query did not leave**.
    """
    wired = _wired()
    parked = await wired.engine.converse(_ASKED, timeout=PATIENT)
    assert parked.read_confirmation is not None
    park = await _parked(wired)
    servicer = wired.engine._loop._search
    held = _SuspendingSearcher(servicer._searcher)
    servicer._searcher = held
    answering = asyncio.create_task(
        wired.engine.resume(parked.read_confirmation.token, approved=True, timeout=PATIENT)
    )
    await held.reached.wait()

    assert (
        await wired.engine.cancel_read(parked.read_confirmation.token)
        is ReadCancellation.INTERRUPTED
    )

    with pytest.raises(asyncio.CancelledError):
        await answering
    settled = await wired.parks.get(park.id)
    assert settled is not None
    assert settled.disposition is ParkedReadDisposition.APPROVED, "not re-opened"
    held.release.set()


# --- what the continuation owes the turn it composes -------------------------


async def test_a_refused_dispatch_carries_its_explanation_into_the_resumed_reply() -> None:
    """ADR-0244 §8: the ordinary carrier on a resumed read that yielded nothing.

    "Where the dispatched read yielded no records — it was refused, expired, interrupted
    or returned nothing — the turn still composes, and **ADR-0242 §6's carrier gives the
    composing stage its member exactly as it does on any other turn**."

    ``DISPATCHED`` says what became of the *answer* and says nothing about what became of
    the read, so a reply composed with no member would leave a user told the lookup ran
    and shown nothing it produced — with no sentence saying why. The member is mapped at
    the site that holds the refusal and carried from there as data.
    """
    composing, model = _recorder()
    wired = _wired(composing=composing)
    parked = await wired.engine.converse(_ASKED, timeout=PATIENT)
    assert parked.read_confirmation is not None
    park = await _parked(wired)
    assert park.parameters is not None
    servicer = wired.engine._loop._search
    servicer._searcher = _CostedSearcher(
        FakeWebSearcher(refusals={str(park.parameters["query"]): SearchRefusal.DEADLINE_EXPIRED})
    )

    outcome = await wired.engine.resume(
        parked.read_confirmation.token, approved=True, timeout=PATIENT
    )

    assert outcome.read_answer is ReadAnswerOutcome.DISPATCHED, "the answer was spent"
    assert outcome.search_not_serviced is SearchNotServiced.INTERRUPTED, (
        "and ADR-0241's DEADLINE_EXPIRED maps to the member whose statement says the "
        "search was begun and stopped (ADR-0242 §10)"
    )
    assert outcome.reply is not None, "the turn still composed"
    assert "begun and stopped" not in _system_prompt(model), "asserted over the fragment below"
    assert "it was stopped before it came back" in _system_prompt(model)


async def test_a_dispatch_that_yielded_carries_no_member_at_all() -> None:
    """The control for the case above: a search that ran says nothing about not running.

    ADR-0242 §6's eligibility is the presence of a disposition, and a yield has none —
    "the assistant looked, and saying it did not would be false".
    """
    wired = _wired()
    parked = await wired.engine.converse(_ASKED, timeout=PATIENT)
    assert parked.read_confirmation is not None

    outcome = await wired.engine.resume(
        parked.read_confirmation.token, approved=True, timeout=PATIENT
    )

    assert outcome.read_answer is ReadAnswerOutcome.DISPATCHED
    assert outcome.search_not_serviced is None


def test_the_resumed_fourth_group_is_bounded_and_deduplicated() -> None:
    """ADR-0244 §7: the minted records are admitted under ADR-0226 §6's budget of ten.

    "They are deduplicated and admitted under ADR-0226 §6's budget of ten", so an
    eleventh admits nothing — and the deduplication is over the **whole union**, which
    is the half a seen-set that never advances would fail: two records of one batch
    sharing an id would otherwise both enter the supply the reply is composed over.

    **Driven at the function that states the two rules rather than through the engine**,
    because a dispatch cannot reach either bound: ADR-0231 §5 caps
    ``Settings.search_max_results`` at three, so one approved read mints at most three
    records and neither an eleventh nor a repeated id is constructible through the seam.
    The rules are stated anyway — ADR-0244 §7 retains them by name — and this is the
    site where a rule stated for a bound no input reaches can still be checked. The
    engine-level case below asserts what the pipeline *can* show: that the union it
    composes over holds each record once.
    """
    held = ("already-held",)

    assert [
        record.id
        for record in admitted_fourth_group(tuple(_minted(f"r-{n}") for n in range(12)), held=held)
    ] == [f"r-{n}" for n in range(10)], "ADR-0226 §6's budget of ten, and no eleventh"
    assert admitted_fourth_group((_minted("already-held"),), held=held) == (), (
        "a record the supply already holds keeps its place there and consumes no slot"
    )
    assert [
        record.id for record in admitted_fourth_group((_minted("r-1"), _minted("r-1")), held=())
    ] == ["r-1"], "and the seen set advances, so one batch's duplicate enters once"


def _minted(record_id: str) -> SemanticMemory:
    """A record shaped as a search mints one, for the admission rules alone."""
    return SemanticMemory(
        id=record_id,
        content=f"a result under {record_id}",
        fact=f"a result under {record_id}",
        placement=Placement(),
        provenance=Provenance(source=MemorySource.OBSERVED, confidence=0.6, last_updated=AT),
    )


async def test_the_resumed_union_holds_each_record_once() -> None:
    """The engine-level half of the case above, over what a dispatch can reach."""
    wired = _wired()
    parked = await wired.engine.converse(_ASKED, timeout=PATIENT)
    assert parked.read_confirmation is not None

    outcome = await wired.engine.resume(
        parked.read_confirmation.token, approved=True, timeout=PATIENT
    )

    assert outcome.turn is not None
    assert len({record.id for record in outcome.turn.memories}) == len(outcome.turn.memories)


async def test_the_resumed_capture_records_this_passs_own_disclosure_evaluation() -> None:
    """ADR-0204 §2 over the resumed turn's own supply, and ADR-0244 §8's ordinary capture.

    **This pass's own value and not the parked turn's**, which is where a read resume
    differs from a step's: a step's resolution renders the parked turn's goal and plan
    from a pass that retrieves nothing, so §2's fourth clause has it carry the parked
    turn's boolean; this pass retrieves a supply of its own and composes over it.

    A hardcoded ``False`` here is #1708's laundering path arrived at through a park: the
    episode would be captured unmarked, and a later spoken turn may read it back.
    """
    wired = _wired()
    await wired.memory.add(
        SemanticMemory(
            id="secret-1",
            # Shares the goal statement's own words, because the resumed turn's
            # retrieval is the ordinary one and searches on that statement — which is
            # itself ADR-0244 §8's "assembled at the instant of the resume by the
            # ordinary pipeline" made visible.
            content=f"{_ASKED}: the appointment on thursday",
            fact="the appointment on thursday",
            about_person="Sam",
            placement=Placement(),
            provenance=Provenance(source=MemorySource.OBSERVED, confidence=0.9, last_updated=AT),
        )
    )
    parked = await wired.engine.converse(_ASKED, timeout=PATIENT)
    assert parked.read_confirmation is not None
    park = await _parked(wired)
    assert park.parameters is not None
    servicer = wired.engine._loop._search
    # A refused dispatch, so the **retrieval** is the only thing that can have caused
    # the narrowing — the sibling case below drives the other half over a yield.
    servicer._searcher = _CostedSearcher(
        FakeWebSearcher(refusals={str(park.parameters["query"]): SearchRefusal.DEADLINE_EXPIRED})
    )
    before = await _episode_ids(wired)

    outcome = await wired.engine.resume(
        parked.read_confirmation.token, approved=True, timeout=PATIENT
    )

    assert outcome.turn is not None
    assert any(record.id == "secret-1" for record in outcome.turn.memories), (
        "the record reached the supply the reply was composed over (ADR-0204 §4)"
    )
    episode = await _resumed_episode(wired, before)
    assert episode.placement.reach is PlacementReach.OWNER, (
        "and the capture derived the owner-only placement ADR-0217 §3 carries the "
        "evaluation on, so a later spoken turn cannot read this episode back"
    )
    assert episode.placement.set_by is PlacementSetter.DERIVED


async def test_the_approved_reads_own_records_are_what_narrow_the_resumed_capture() -> None:
    """ADR-0226 §7's timing, on the supply half only the **fourth group** supplies.

    "One evaluation, over the turn's **final** supply — and on a turn that serviced a
    request the supply is the deduplicated union of all four groups." Here the retrieval
    carries nothing ADR-0199 §3 withholds, so the narrowing is caused **solely by the
    records the approved read minted** — the half an implementation evaluating before it
    appended them would miss, and the half that matters most: an unmarked episode over a
    supply an approved read put external records into is #1708's laundering path reached
    through a park.
    """
    wired = _wired()
    parked = await wired.engine.converse(_ASKED, timeout=PATIENT)
    assert parked.read_confirmation is not None
    before = await _episode_ids(wired)

    outcome = await wired.engine.resume(
        parked.read_confirmation.token, approved=True, timeout=PATIENT
    )

    assert outcome.turn is not None
    assert any(record.content.startswith("a result") for record in outcome.turn.memories), (
        "the read's records reached the supply the reply was composed over"
    )
    episode = await _resumed_episode(wired, before)
    assert episode.placement.reach is PlacementReach.OWNER
    assert episode.placement.set_by is PlacementSetter.DERIVED


async def test_a_resumed_capture_over_a_supply_nothing_withholds_is_not_narrowed() -> None:
    """The control for both cases above: the mark comes from the supply, not the path.

    Without it each would pass on an implementation that hardcoded ``True``, which is
    the same class of error as hardcoding ``False`` and is caught the same way. Driven
    over a dispatch the searcher **refused**, because that is the one approved answer
    whose final supply carries no minted record at all — and on which ADR-0244 §8 still
    has the turn compose.
    """
    wired = _wired()
    parked = await wired.engine.converse(_ASKED, timeout=PATIENT)
    assert parked.read_confirmation is not None
    park = await _parked(wired)
    assert park.parameters is not None
    servicer = wired.engine._loop._search
    servicer._searcher = _CostedSearcher(
        FakeWebSearcher(refusals={str(park.parameters["query"]): SearchRefusal.DEADLINE_EXPIRED})
    )
    before = await _episode_ids(wired)

    outcome = await wired.engine.resume(
        parked.read_confirmation.token, approved=True, timeout=PATIENT
    )

    assert outcome.turn is not None
    assert not any(record.content.startswith("a result") for record in outcome.turn.memories), (
        "the refusal minted nothing, so the fourth group is empty — what the supply "
        "still holds is the conversation's own replay tail, which withholds nothing"
    )
    episode = await _resumed_episode(wired, before)
    assert episode.placement == Placement(), "nothing was withheld, so nothing is narrowed"


async def _episode_ids(wired: _Wired) -> frozenset[str]:
    """Every episode this deployment holds right now, by id."""
    return frozenset(
        record.id
        for record in await wired.memory.export()
        if MemoryKind(record.kind) is MemoryKind.EPISODIC
    )


async def _resumed_episode(wired: _Wired, before: frozenset[str]) -> Any:
    """The episode the resumption captured — the one that was not there before it.

    Identified by difference rather than by position, because ``export`` fixes no order
    and both episodes of this journey carry the same instant: a case reading the "last"
    one would be asserting about whichever the store happened to yield second.
    """
    added = [
        record
        for record in await wired.memory.export()
        if MemoryKind(record.kind) is MemoryKind.EPISODIC and record.id not in before
    ]
    assert len(added) == 1, "the resumption was captured, once"
    return added[0]


# --- ADR-0244 §5: the establishing act still rides this answer ---------------


async def test_an_approval_over_a_clean_binding_establishes_the_grant_it_was_asked_for() -> None:
    """ADR-0244 §5: "the act still rides an answer where a park holds the confirmation".

    ``resume``'s ``remember_recipients_until`` reaches a read park's answer **exactly as
    ADR-0235 §2 rules it, unchanged**, and this decision adds no clause to either. An
    implementation that reported every such request as declined would tell a user who
    made one that it did not land, while the lookup it rode went out.
    """
    wired = _wired()
    parked = await wired.engine.converse(_ASKED, timeout=PATIENT)
    assert parked.read_confirmation is not None
    park = await _parked(wired)
    recorded = await wired.trail.get(park.decision_id)
    assert recorded is not None
    binding = recorded.egress_binding
    assert isinstance(binding, EgressBinding)
    assert binding.planned_with_external_content is False, (
        "a first search over a supply nothing external reached, which is the row "
        "ADR-0193 §4 leaves grantable"
    )

    outcome = await wired.engine.resume(
        parked.read_confirmation.token,
        approved=True,
        timeout=PATIENT,
        remember_recipients_until=wired.clock.now + timedelta(days=30),
    )

    assert outcome.read_answer is ReadAnswerOutcome.DISPATCHED
    assert outcome.recipient_grant is not None
    assert outcome.recipient_grant.not_established is None, "the act landed"
    assert outcome.recipient_grant.established is not None
    assert len(await wired.engine.standing_recipient_grants()) == 1


async def test_a_declining_answer_reports_the_collected_act_as_declined() -> None:
    """ADR-0235 §4's second state, unchanged at this population.

    An act collected beside a declining answer carries ``DECLINED``: the ``DENY`` is
    recorded exactly as it is today and the recipient-grant store is never reached.

    **The recorded ``DENY`` is asserted here rather than assumed**, because it is what
    makes this arm the discriminator for the four below. §4 defines ``DECLINED`` over a
    *recorded* non-``ALLOW`` answer, so an arm that only read the member would pass
    equally against an implementation reporting it on a call that ruled nothing at all.
    """
    wired = _wired()
    parked = await wired.engine.converse(_ASKED, timeout=PATIENT)
    assert parked.read_confirmation is not None

    outcome = await wired.engine.resume(
        parked.read_confirmation.token,
        approved=False,
        timeout=PATIENT,
        remember_recipients_until=wired.clock.now + timedelta(days=30),
    )

    assert outcome.read_answer is ReadAnswerOutcome.DECLINED
    assert outcome.recipient_grant is not None
    assert outcome.recipient_grant.not_established is RecipientGrantNotEstablished.DECLINED
    assert outcome.recipient_grant.established is None
    assert await wired.engine.standing_recipient_grants() == ()
    [resolution] = [row for row in await wired.trail.recent() if row.resolves]
    assert resolution.ruling.outcome is PermissionOutcome.DENY, (
        "the answer this member asserts was recorded"
    )


# --- ADR-0235 §4: the carrier is absent where nothing was ruled ----------------
#
# "``recipient_grant`` is ``None`` on **every** outcome of a call that performed no
# establishing act", and ADR-0244 §9 gives four of its seven members no recorded
# resolution at all. The arm above is the discriminator: a declining answer *did* rule,
# so it keeps ``DECLINED``, and these four must not borrow it. Found by the round-8
# adversarial review, which is the round that recorded the blocker these pin.


async def test_a_second_answer_carrying_an_act_reports_no_carrier_at_all() -> None:
    """``ALREADY_SETTLED`` beside an act: nothing was ruled, so nothing is asserted.

    The user approved this lookup and made its recipients standing; a second press of
    the same control, this time declining and asking again, consults no policy and
    records nothing (ADR-0244 §6). Reporting ``DECLINED`` there would tell the user the
    standing request they already hold had just been considered and refused — and the
    grant from the first answer is still standing while they read it.
    """
    wired = _wired()
    parked = await wired.engine.converse(_ASKED, timeout=PATIENT)
    assert parked.read_confirmation is not None
    token = parked.read_confirmation.token
    first = await wired.engine.resume(
        token,
        approved=True,
        timeout=PATIENT,
        remember_recipients_until=wired.clock.now + timedelta(days=30),
    )
    assert first.read_answer is ReadAnswerOutcome.DISPATCHED
    assert len(await wired.engine.standing_recipient_grants()) == 1
    rows = len(await wired.trail.recent())

    again = await wired.engine.resume(
        token,
        approved=False,
        timeout=PATIENT,
        remember_recipients_until=wired.clock.now + timedelta(days=30),
    )

    assert again.read_answer is ReadAnswerOutcome.ALREADY_SETTLED
    assert again.recipient_grant is None, "no act was performed, so none is reported"
    assert len(await wired.trail.recent()) == rows, "and nothing further was recorded"
    assert len(await wired.engine.standing_recipient_grants()) == 1, "the first act stands"


async def test_an_expired_park_answered_with_an_act_reports_no_carrier_at_all() -> None:
    """``EXPIRED`` beside an act: the question lapsed, so no answer was ever given.

    Clause 1 settles the park as stale and returns before the policy is asked
    (ADR-0244 §6), so there is no resolution for ADR-0235 §4's ``DECLINED`` to be an
    assertion about.
    """
    wired = _wired()
    parked = await wired.engine.converse(_ASKED, timeout=PATIENT)
    assert parked.read_confirmation is not None
    wired.clock.advance(_TTL + timedelta(minutes=1))

    outcome = await wired.engine.resume(
        parked.read_confirmation.token,
        approved=False,
        timeout=PATIENT,
        remember_recipients_until=wired.clock.now + timedelta(days=30),
    )

    assert outcome.read_answer is ReadAnswerOutcome.EXPIRED
    assert outcome.recipient_grant is None
    assert [row for row in await wired.trail.recent() if row.resolves] == [], "nothing ruled"
    assert await wired.engine.standing_recipient_grants() == ()


async def test_an_unavailable_deployment_answered_with_an_act_reports_no_carrier() -> None:
    """``UNAVAILABLE_NOW`` beside an act: this deployment can rule on nothing.

    A deployment that disconnected its search account, read under a standing question
    (ADR-0247 §12's Arm G). Clause 2 precedes the gate and the policy alike, so the park
    is not spent and no answer is recorded.
    """
    wired = _wired()
    parked = await wired.engine.converse(_ASKED, timeout=PATIENT)
    assert parked.read_confirmation is not None
    wired.engine._parked_reads._search = None

    outcome = await wired.engine.resume(
        parked.read_confirmation.token,
        approved=False,
        timeout=PATIENT,
        remember_recipients_until=wired.clock.now + timedelta(days=30),
    )

    assert outcome.read_answer is ReadAnswerOutcome.UNAVAILABLE_NOW
    assert outcome.recipient_grant is None
    assert [row for row in await wired.trail.recent() if row.resolves] == [], "nothing ruled"
    assert await wired.engine.standing_recipient_grants() == ()


async def test_a_changed_operation_answered_with_an_act_reports_no_carrier() -> None:
    """``OPERATION_CHANGED`` beside an act: the subject moved, so nothing was ruled on.

    The fourth of the four, and the one that leaves the park ``OPEN`` — so a user told
    their standing request had been declined would be reading that about a question
    they can still answer.
    """
    wired = _wired()
    parked = await wired.engine.converse(_ASKED, timeout=PATIENT)
    assert parked.read_confirmation is not None
    park = await _parked(wired)
    servicer = wired.engine._loop._search
    servicer._binder = _RefusingRebind(servicer._binder)

    outcome = await wired.engine.resume(
        parked.read_confirmation.token,
        approved=False,
        timeout=PATIENT,
        remember_recipients_until=wired.clock.now + timedelta(days=30),
    )

    assert outcome.read_answer is ReadAnswerOutcome.OPERATION_CHANGED
    assert outcome.recipient_grant is None
    assert [row for row in await wired.trail.recent() if row.resolves] == [], "nothing ruled"
    still_open = await wired.parks.get(park.id)
    assert still_open is not None
    assert still_open.disposition is ParkedReadDisposition.OPEN, "the park is not spent"


async def test_an_act_on_an_external_content_binding_is_refused_before_the_gate() -> None:
    """ADR-0235 §2's binding refusal, which ADR-0244 §5 preserves entire.

    "A user answering such a confirmation may approve the call, and may not in that act
    make its recipients standing" (ADR-0193 §2, §4). **Refused before the gate**, so
    nothing is ruled, nothing is dispatched, and **the park stays open and answerable
    without the standing request** — a park spent on a refused act is a question the user
    has to answer again for no reason.
    """
    wired = _wired()
    # A second turn of the same conversation, after the first has minted a record at a
    # destination nobody chose: ADR-0181 §5's lineage floor then makes the next
    # request's binding carry `planned_with_external_content`, which is #2221's own
    # shape and the row ADR-0193 §4 covers with no grant.
    first = await wired.engine.converse(_ASKED, timeout=PATIENT)
    assert first.read_confirmation is not None
    await wired.engine.resume(first.read_confirmation.token, approved=True, timeout=PATIENT)
    second = await wired.engine.converse(
        _ASKED, timeout=PATIENT, conversation_id=first.conversation_id
    )
    assert second.read_confirmation is not None
    park = await _parked(wired)

    with pytest.raises(UngrantableActError, match="external content"):
        await wired.engine.resume(
            second.read_confirmation.token,
            approved=True,
            timeout=PATIENT,
            remember_recipients_until=wired.clock.now + timedelta(days=30),
        )

    still_open = await wired.parks.get(park.id)
    assert still_open is not None
    assert still_open.disposition is ParkedReadDisposition.OPEN, "the park is not spent"
    assert len(wired.searcher.searched) == 1, "and the second read was not dispatched"


async def test_an_expiry_at_or_before_the_answers_instant_is_refused_before_the_gate() -> None:
    """ADR-0235 §1's expiry refusal, compared against **the instant the answer carries**.

    One clock reading is used for both the comparison and the record, which is §1's own
    clause: two readings admit an expiry that passes the check and fails
    ``RecipientGrant.established_from``'s constructor.
    """
    wired = _wired()
    parked = await wired.engine.converse(_ASKED, timeout=PATIENT)
    assert parked.read_confirmation is not None
    park = await _parked(wired)

    with pytest.raises(UngrantableActError, match="strictly after"):
        await wired.engine.resume(
            parked.read_confirmation.token,
            approved=True,
            timeout=PATIENT,
            remember_recipients_until=wired.clock.now,
        )

    still_open = await wired.parks.get(park.id)
    assert still_open is not None
    assert still_open.disposition is ParkedReadDisposition.OPEN
    assert wired.searcher.searched == []


# --- ADR-0244 §10: the conversation's own next servicing settles an expiry ----


async def test_the_next_servicing_settles_an_expired_park_and_writes_its_own() -> None:
    """ADR-0244 §10's **third** reader, which no other case reaches.

    "A park whose ``expires_at`` is at or before the clock's reading is settled
    ``EXPIRED`` at the first operation that reads it — an answer, an enumeration, **or
    the conversation's own next servicing**." Without it a park nobody enumerated and
    nobody answered holds that conversation's one open slot past its own deadline,
    spending an ``admit_search`` call per turn and offering no question for any of them.
    """
    wired = _wired()
    first = await wired.engine.converse(_ASKED, timeout=PATIENT)
    assert first.read_confirmation is not None
    stale = await _parked(wired)
    wired.clock.advance(_TTL + timedelta(minutes=1))

    second = await wired.engine.converse(
        _ASKED, timeout=PATIENT, conversation_id=first.conversation_id
    )

    settled = await wired.parks.get(stale.id)
    assert settled is not None
    assert settled.disposition is ParkedReadDisposition.EXPIRED
    assert settled.parameters is None, "and its content was cleared"
    assert second.read_confirmation is not None, "the slot was free, so this turn parked"
    assert second.search_not_serviced is SearchNotServiced.ANSWER_AWAITED
    [standing] = await wired.parks.outstanding()
    assert standing.id != stale.id


class _GatedSettle:
    """A ``ParkedReads`` whose **first** ``settle`` is held open inside the store.

    ADR-0244 §19's Arm 11 is stated over two answers "both past clause 4", and the only
    place that state is reachable is the compare-and-swap itself: pause anywhere later
    and the first answer has already written, so the second bounces off clause 1's
    terminal-state check and never reaches the gate at all. Holding the *write* is what
    puts both callers inside it.

    Every other member delegates, so what is under test is the engine's use of the gate
    and not a second store's behaviour.
    """

    def __init__(self, inner: FakeParkedReads) -> None:
        self._inner = inner
        self.reached = asyncio.Event()
        self.release = asyncio.Event()
        #: How many callers reached the compare-and-swap. Two is the arm's whole point.
        self.attempts = 0

    async def park(self, record: Any, /) -> bool:
        return await self._inner.park(record)

    async def get(self, park_id: str, /) -> Any:
        return await self._inner.get(park_id)

    async def open_park(self, conversation_id: str, /) -> Any:
        return await self._inner.open_park(conversation_id)

    async def park_of_decision(self, decision_id: str, /) -> Any:
        return await self._inner.park_of_decision(decision_id)

    async def outstanding(self) -> Any:
        return await self._inner.outstanding()

    async def settle(self, park_id: str, /, *, disposition: ParkedReadDisposition, at: Any) -> bool:
        self.attempts += 1
        if self.attempts == 1:
            self.reached.set()
            await self.release.wait()
        return await self._inner.settle(park_id, disposition=disposition, at=at)

    async def drop_for_conversation(self, conversation_id: str, /) -> int:
        return await self._inner.drop_for_conversation(conversation_id)


async def test_a_cancellation_that_lost_the_gate_interrupts_nothing() -> None:
    """ADR-0244 §11: **neither party acts on a park the other took**, in the direction
    a fall-through would break.

    "A cancellation that lost it answers ``NOTHING_TO_CANCEL`` where the answer is
    already running or done." A cancellation that read the park **open** asked to
    withdraw the *question*; losing the write means somebody else answered it, and
    tearing down the dispatch that answer authorised would let a lost race stop a send
    a won one had already made. The discriminator is this call's own read, which is what
    "decided by that write and by nothing else" means.
    """
    wired = _wired()
    parked = await wired.engine.converse(_ASKED, timeout=PATIENT)
    assert parked.read_confirmation is not None
    token = parked.read_confirmation.token
    park = await _parked(wired)
    gate = _GatedSettle(wired.parks)
    wired.engine._parked_reads._store = gate
    # The winning answer's **dispatch is held in flight**, which is what makes this case
    # able to fail: released against a finished answer there is no task left to cancel,
    # so a fall-through to the interrupt would find nothing and answer
    # `NOTHING_TO_CANCEL` for the wrong reason.
    held = _SuspendingSearcher(wired.engine._loop._search._searcher)
    wired.engine._loop._search._searcher = held
    # The cancellation reads the park open and is then held at the write.
    cancelling = asyncio.create_task(wired.engine.cancel_read(token))
    await gate.reached.wait()
    answering = asyncio.create_task(wired.engine.resume(token, approved=True, timeout=PATIENT))
    await held.reached.wait()

    gate.release.set()
    cancelled = await cancelling

    assert cancelled is ReadCancellation.NOTHING_TO_CANCEL, "the cancellation took nothing"
    held.release.set()
    answered = await answering

    assert answered.read_answer is ReadAnswerOutcome.DISPATCHED, (
        "and the answer it lost to ran to completion rather than being torn down"
    )
    assert len(wired.searcher.searched) == 1, "the dispatch the answer authorised stands"
    settled = await wired.parks.get(park.id)
    assert settled is not None
    assert settled.disposition is ParkedReadDisposition.APPROVED, "not CANCELLED"


async def test_an_answer_whose_decision_was_already_resolved_dispatches_nothing() -> None:
    """ADR-0244 §6's clause 3, third conjunct: "no decision resolving it is recorded".

    The window it covers is real and narrow: between the trail recording the ``CONFIRM``
    and the servicing writing its park, no park names that decision and §5's eighth
    condition does not yet exclude it — so the establishing act may ride it. Without this
    read the answer would spend the park and consult the policy before the trail refused
    the second resolution: a question the user has to ask again, for a refusal that was
    already knowable.

    **The park is left ``OPEN``**, which is what §9 fixes for a clause that precedes the
    gate — though a decision with a resolution is one no later answer can dispatch
    either, so what the park keeps is its deadline rather than a second chance.
    """
    wired = _wired()
    parked = await wired.engine.converse(_ASKED, timeout=PATIENT)
    assert parked.read_confirmation is not None
    park = await _parked(wired)
    confirmed = await wired.trail.get(park.decision_id)
    assert confirmed is not None
    # The act riding that decision, performed through the engine's own operation while
    # no park named it — which is the window this conjunct is stated over. Recorded
    # directly here because §5's eighth condition now closes the door the window opens.
    await wired.trail.record(
        PermissionDecision.from_confirmation(
            confirmed,
            # A ``DENY``, because a resolving ``ALLOW`` must cite the confirmation it
            # rests on (ADR-0021 §5) and what this case is about is the *existence* of a
            # resolution rather than which way it went.
            PermissionRuling(outcome=PermissionOutcome.DENY, reason="answered elsewhere"),
            id="answered-elsewhere",
            decided_at=wired.clock.now,
        )
    )

    outcome = await wired.engine.resume(
        parked.read_confirmation.token, approved=True, timeout=PATIENT
    )

    assert outcome.read_answer is ReadAnswerOutcome.OPERATION_CHANGED
    assert wired.searcher.searched == [], "nothing was dispatched"
    still_open = await wired.parks.get(park.id)
    assert still_open is not None
    assert still_open.disposition is ParkedReadDisposition.OPEN, "and the park is not spent"


async def test_an_answer_for_a_deleted_conversation_is_refused_as_unavailable() -> None:
    """§19's Arm 6, third limb's other half, and ADR-0244 §6's clause 2 as ADR-0247 §6
    repoints it.

    Clause 2 used to establish that ``search_draw`` answered a draw and that
    ``Settings.search_calls_per_conversation`` was not ``0``; with both removed, the fact
    it was establishing is that **the conversation exists and is not stamped deleted**,
    and ``ConversationStore.get`` answers it by the same rule — "``None`` when the id
    names nothing **or** names a conversation stamped deleted". Nothing is ruled and
    nothing is dispatched, which is what ``UNAVAILABLE_NOW`` says; and the park is left
    where it is, because clause 2 precedes the gate.

    **The park's own rows are not what makes this refuse.** ADR-0244 §3 has the
    conversation's deletion sequence drop its parks through ``drop_for_conversation`` —
    Lane 2's wiring — so a deployment where that has not run yet still holds the
    question, and clause 2 is what keeps it unanswerable. That is the state this case
    drives: the conversation is stamped deleted and the park is still there.
    """
    wired = _wired()
    parked = await wired.engine.converse(_ASKED, timeout=PATIENT)
    assert parked.read_confirmation is not None
    park = await _parked(wired)
    assert await wired.engine._conversations._conversations.stamp_deleted(park.conversation_id)

    outcome = await wired.engine.resume(
        parked.read_confirmation.token, approved=True, timeout=PATIENT
    )

    assert outcome.read_answer is ReadAnswerOutcome.UNAVAILABLE_NOW
    assert wired.searcher.searched == [], "nothing was dispatched"
    assert [row for row in await wired.trail.recent() if row.resolves] == [], "nothing was ruled"
    still_open = await wired.parks.get(park.id)
    assert still_open is not None
    assert still_open.disposition is ParkedReadDisposition.OPEN, "clause 2 precedes the gate"


# --- what a resumed turn owes the conversation it ran under -------------------


class _UnreadableTrail:
    """A trail whose ``get`` raises, for the one clause ADR-0244 §1 states in terms.

    Every other member delegates, so what is under test is whether the **parking turn**
    survives a store fault on the path that assembles its question — not a second
    trail's behaviour.
    """

    def __init__(self, inner: FakeAuditTrail) -> None:
        self._inner = inner
        self.gets = 0

    async def get(self, decision_id: str) -> Any:
        self.gets += 1
        msg = "fake: the trail could not be read"
        raise AuditError(msg)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


async def test_parking_a_read_survives_a_trail_that_cannot_be_read() -> None:
    """ADR-0244 §1: "**the turn does not park, is not suspended and does not fail**".

    The question is assembled from the decision the servicing site already holds, so the
    parking turn takes **no** trail read of its own. A read taken there could raise
    between the park and the reply and take down a turn that had already composed its
    answer — which is the one thing §1 says parking must not do, and the failure this
    case exists to make unreachable.

    The enumeration path is a different seam and still reads: it is not inside a turn
    and already declares ``AuditError`` (ADR-0052 §1).
    """
    wired = _wired()
    unreadable = _UnreadableTrail(wired.trail)
    wired.engine._trail = unreadable

    outcome = await wired.engine.converse(_ASKED, timeout=PATIENT)

    assert outcome.reply is not None, "the turn composed and answered"
    assert outcome.search_not_serviced is SearchNotServiced.ANSWER_AWAITED
    assert outcome.read_confirmation is not None, "and the question was assembled"
    assert unreadable.gets == 0, "with no trail read on the parking turn's path at all"
    assert len(await wired.parks.outstanding()) == 1


# --- ADR-0247 §12's Arms F and F': what moves a park's binding and what does not


async def test_a_park_at_the_configured_provider_answers_and_dispatches() -> None:
    """ADR-0247 §12's **Arm E**, over the ground that still parks a configured search.

    "A ``WEB_SEARCH`` at the configured provider that draws ``CONFIRM`` on an independent
    ground — an ``UNKNOWN`` per-call cost — parks; the answer rebuilds the request,
    ``rebind`` derives a binding equal to the recorded one, and the read **dispatches**."
    Lane 2 landed the transcription this rests on, and what is asserted here is the
    engine's end of it: the park carries ``closed_loop`` ``True`` — ADR-0247 §4 writes it
    from the kind and the configuration, so *every* search of such a deployment does —
    and the answer runs it.

    It is the premise Arms F and F' below vary, so it is asserted first: without it a
    refusal there could be the park having been unanswerable all along.
    """
    wired = _wired(configured=True)
    parked = await wired.engine.converse(_ASKED, timeout=PATIENT)
    assert parked.read_confirmation is not None
    park = await _parked(wired)
    held = await wired.trail.get(park.decision_id)
    assert held is not None
    assert isinstance(held.egress_binding, EgressBinding)
    assert held.egress_binding.closed_loop is True, "ADR-0247 §4's two conditions both hold"

    outcome = await wired.engine.resume(
        parked.read_confirmation.token, approved=True, timeout=PATIENT
    )

    assert outcome.read_answer is ReadAnswerOutcome.DISPATCHED
    assert len(wired.searcher.searched) == 1, "the read ran once"


async def test_a_changed_search_origin_refuses_an_open_park() -> None:
    """ADR-0247 §12's **Arm F**, engine half (lane 2 holds the seam's).

    "With a park open and the deployment's ``web_search_origin`` then changed, the answer
    derives an unequal binding, dispatches nothing, leaves the park ``OPEN`` and returns
    ``OPERATION_CHANGED``."

    **The origin reaches the binding as the registration's ``transport_endpoint``**, which
    ``EgressBindingSeam`` stamps onto every binding it derives (ADR-0148 §6), so changing
    what the deployment configured is a provisioning act on the seam and not an edit of
    the park: the park's own parameters are replayed byte for byte, and the binding
    derived over them no longer equals the recorded one. That is the whole of the
    refusal, and it is why the answer needs no ``Settings`` read of its own.

    **Clause 4 precedes the gate**, so the park is left ``OPEN`` and nothing is ruled:
    "a park spent on an answer the subject check would have refused is an answer the user
    has to give again for no reason" (ADR-0244 §6).
    """
    wired = _wired(configured=True)
    parked = await wired.engine.converse(_ASKED, timeout=PATIENT)
    assert parked.read_confirmation is not None
    park = await _parked(wired)
    wired.binder.register_egress(
        FAKE_WEB_SEARCH,
        reference=_ACCOUNT.reference,
        identity=_ACCOUNT.identity,
        transport_endpoint="https://elsewhere.example",
    )

    outcome = await wired.engine.resume(
        parked.read_confirmation.token, approved=True, timeout=PATIENT
    )

    assert outcome.read_answer is ReadAnswerOutcome.OPERATION_CHANGED
    assert wired.searcher.searched == [], "nothing was dispatched"
    assert [row for row in await wired.trail.recent() if row.resolves] == [], "and nothing ruled"
    still_open = await wired.parks.get(park.id)
    assert still_open is not None
    assert still_open.disposition is ParkedReadDisposition.OPEN, "the park is not spent"


async def test_a_reprovisioned_account_leaves_an_open_park_answerable() -> None:
    """ADR-0247 §12's **Arm F'**, engine half.

    "With the connection reference and origin unchanged and the stored secret replaced,
    the same park answers and the read dispatches." A rotation is a provisioning act on
    the **record** the reference names, and ADR-0148 §6 keeps the two facts a binding
    carries — the account identity and the transport endpoint — apart from the credential
    slot and the revision it moves. So the re-derived binding equals the recorded one and
    the ``closed_loop`` ADR-0247 §7 transcribes rides through with it.

    **The rotation's own moving parts are asserted at the seam, not here**
    (``tests/tools/test_egress_binder.py``): the canonical fake's record holds an identity
    and a state and nothing else, so what this arm can state is that a provisioning act
    over the same reference leaves the park answerable — the half the engine owns — while
    Arm F one case above shows the refusal is reachable at all, so this is not passing on
    a check that never runs.
    """
    wired = _wired(configured=True)
    parked = await wired.engine.converse(_ASKED, timeout=PATIENT)
    assert parked.read_confirmation is not None
    park = await _parked(wired)
    wired.binder.set_connection(_ACCOUNT.reference, identity=_ACCOUNT.identity)

    outcome = await wired.engine.resume(
        parked.read_confirmation.token, approved=True, timeout=PATIENT
    )

    assert outcome.read_answer is ReadAnswerOutcome.DISPATCHED
    assert len(wired.searcher.searched) == 1, "the read ran"
    settled = await wired.parks.get(park.id)
    assert settled is not None
    assert settled.disposition is ParkedReadDisposition.APPROVED
