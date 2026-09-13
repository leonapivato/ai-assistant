"""ADR-0264 through the **engine**: the member the capture point folds into the outcome.

``tests/orchestration/test_outbound_statement.py`` drives the servicing site and the
loop, and ``test_runner_outbound.py`` the drive; this module drives the pipeline
**above** them — ``Engine.converse``, the real ``ComposingStage`` it forwards to, and
the ``TurnOutcome`` it builds — because §7's member and §6's fragment are two consumers
of one assembled value and a lane that dropped either forwarding would leave every
loop-level assertion passing while the user lost the statement.

**The two shapes the decision exists for are pinned here end to end.** #2268's is a turn
that fired a search to the configured provider and whose composed reply told the user
"nothing was searched just now"; #2365's is a turn whose trail recorded
``servicing=not_asked`` and whose reply claimed its figures were "already in front of me
from **this turn's searches**". Neither is *prevented* by this decision — §10 is explicit
that what it supplies is "an authoritative counterstatement and not a prevention" — so
what the arms assert is that the typed value the surface renders from is carried, is
correct, and cannot be made to agree with the denial or the false claim.

The **rendered** statements are lane 2's (§11), landed with the renderer they are about.
"""

from __future__ import annotations

from itertools import count
from typing import TYPE_CHECKING, Any, Final, final

from test_engine import AT, PATIENT, Harness
from test_engine_parked_reads import _ASKED, _Clock, _parked
from test_engine_read_envelope import _AskingPlanner
from test_engine_routing import _UTTERANCE as _ROUTED_PARK_UTTERANCE
from test_engine_routing import _names, _routed_harness, _seed_belief
from test_loop_search import (
    _CONFIGURED_SEARCH,
    _DEADLINE,
    _binder,
    _CostedSearcher,
    _search,
)

from ai_assistant.core.types import (
    OutboundDestination,
    OutboundReach,
    ReadAnswerOutcome,
    Role,
    RoutableOperation,
    RouteOutcome,
    SearchNotServiced,
)
from ai_assistant.core.types import TurnOutcome as TurnOutcomeType
from ai_assistant.orchestration.composing import ComposingStage
from ai_assistant.orchestration.reads import SearchServicer
from ai_assistant.permissions.policy import ThresholdActionPolicy
from ai_assistant.testing import (
    FakeAuditTrail,
    FakeMemoryStore,
    FakeModelProvider,
    FakeParkedReads,
    FakeQueryComposer,
    FakeRecipientGrantStore,
    FakeStreamingCompleter,
    FakeWebSearcher,
    StreamAttempt,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.core.types import TurnOutcome

#: A distinctive clause of each of ADR-0264 §6's three fragments (see
#: ``test_outbound_statement``'s own copy, which is over the same literals).
_REACHED_FRAGMENT: Final = "this assistant reached outside this system, and it took in"
_NOT_REACHED_FRAGMENT: Final = "this assistant reached nothing outside this system"

#: The sentence #2365 records a reply making on a turn that asked for no search.
_FALSE_CLAIM: Final = "already in front of me from this turn's searches"

#: The sentence #2268 records a reply making on a turn whose search was serviced.
_DENIAL: Final = "nothing was searched just now"


@final
class _Wired:
    """An engine over shared stores, with a search this deployment is configured for."""

    def __init__(
        self,
        *,
        results: Sequence[str] = ("a result about the bell tower",),
        parked: bool = False,
        configured: bool = True,
        model: FakeModelProvider | None = None,
    ) -> None:
        """Wire the real pipeline, optionally over a store that can hold a park.

        ``configured`` is what decides whether the search runs on this turn or parks.
        With it the policy is handed the destination this deployment is configured with
        and rules ``ALLOW`` on ADR-0247 §2's route (c) — the deployment's own
        configuration — so the turn reaches the provider with no grant seeded, which is
        production's own state on the owner's deployment. Without it nothing authorises
        the call, the policy rules ``CONFIRM``, and ADR-0244 §1 has the servicing site
        park the read — which is the ground every resume arm below starts from.
        """
        decisions = count(1)
        clock = _Clock()
        grants = FakeRecipientGrantStore(now=clock)
        self.trail = FakeAuditTrail(recipient_grants=grants)
        self.searcher = FakeWebSearcher(results=tuple(results))
        self.parks = FakeParkedReads() if parked else None
        self.model = model
        harness = Harness(
            memory=FakeMemoryStore(now=clock),
            planner=_AskingPlanner(_search(), rounds=1),
            now=clock,
            search=SearchServicer(
                composer=FakeQueryComposer(),
                searcher=_CostedSearcher(self.searcher),
                binder=_binder(),
                policy=ThresholdActionPolicy(
                    grants=grants,
                    configured_search=_CONFIGURED_SEARCH if configured else None,
                ),
                trail=self.trail,
                now=clock,
                id_factory=lambda: f"search-d-{next(decisions)}",
                deadline=_DEADLINE,
                parked_reads=self.parks,
                parked_read_ttl=_DEADLINE * 2880,
            ),
            parked_reads=self.parks,
            trail=self.trail,
            recipient_grants=grants,
            composing=_composing(model),
        )
        self.engine = harness.engine


def _composing(model: FakeModelProvider | None) -> ComposingStage | None:
    """The **production** composing stage over a fake provider that records its prompt.

    ADR-0227 §7's fidelity rule forbids substituting the renderer whose output the
    assertion is about and permits a fake ``ModelProvider``: the stage assembling the
    prompt is the one the engine ships, and the fake merely records what it was handed
    and answers with the scripted reply.
    """
    if model is None:
        return None
    return ComposingStage(model=model, streaming=FakeStreamingCompleter())


def _system_prompt(model: FakeModelProvider, ordinal: int = -1) -> str:
    """The system message the production composing stage assembled, from the fake's record."""
    assert model.calls
    return next(one.content for one in model.calls[ordinal].messages if one.role is Role.SYSTEM)


def _statement(outcome: TurnOutcome) -> Any:
    """The member, asserted present before it is read."""
    assert outcome.outbound_statement is not None, "ADR-0264 §7 carries it on every such pass"
    return outcome.outbound_statement


# --- #2268's shape: a reply cannot deny a contact the trail records -----------


async def test_a_turn_that_searched_carries_a_statement_the_reply_cannot_talk_out_of() -> None:
    """#2268, pinned end to end: the denial stands beside a value that contradicts it.

    The issue's own words: "Turn 2 fired a search to the configured provider … the
    composed reply told the user 'nothing was searched just now.'" What ADR-0264
    supplies against it is **structural rather than detective** (§10): the model is left
    free to write the denial — no clause of the decision inspects, classifies or
    corrects a composed reply — and what changes is that a typed value saying otherwise
    is carried beside it and rendered by code.

    So the arm scripts exactly that reply and asserts the member is carried, correct,
    and unaffected by what the prose says: §7's "the statement stands where the reply
    contradicts it", and §10's "a user reading both sees the disagreement without
    anything having classified it".
    """
    model = FakeModelProvider(f"I have nothing to add — {_DENIAL}.")
    wired = _Wired(model=model)

    outcome = await wired.engine.converse(_ASKED, timeout=PATIENT)

    assert wired.searcher.searched, "the turn really did reach the provider"
    assert outcome.reply is not None
    assert _DENIAL in outcome.reply, "the model wrote the denial, and nothing stopped it"
    statement = _statement(outcome)
    assert statement.reach is OutboundReach.REACHED
    assert statement.destinations == (OutboundDestination.SEARCH_PROVIDER,)
    assert statement.records >= 1
    assert outcome.search_not_serviced is None, "ADR-0242 §6's eligibility is a disposition"
    assert _REACHED_FRAGMENT in _system_prompt(model), (
        "and the composer was told the fact, so it need not guess (ADR-0264 §6)"
    )


# --- #2365's shape: a reply cannot claim a contact the trail does not ---------


async def test_a_turn_that_asked_for_no_search_carries_not_reached_and_not_none() -> None:
    """#2365, pinned end to end — §13 item 9 at the ``TurnOutcome``.

    The issue's turn recorded ``servicing=not_asked``, ``servicings=()`` and
    ``stop=not_iterated`` and told the user its forecast "is already in front of me from
    **this turn's searches**". #2365 states why the earlier draft of this decision did
    not refuse it — "a turn with no servicing has no statement to render, so there is
    nothing for the surface to contradict" — and why it is the worse half of the pair:
    "it is not a missing acknowledgement but a false provenance claim", on exactly the
    class of fact whose value is its freshness.

    "**An implementation that leaves the member ``None`` on such a turn fails this
    arm**, which is the whole of what #2365 records."
    """
    model = FakeModelProvider(f"It will be mild — that is {_FALSE_CLAIM}.")
    harness = Harness(memory=FakeMemoryStore(now=lambda: AT), composing=_composing(model))

    outcome = await harness.engine.converse("what is the forecast", timeout=PATIENT)

    assert outcome.reply is not None
    assert _FALSE_CLAIM in outcome.reply, "the model wrote the claim, and nothing stopped it"
    statement = _statement(outcome)
    assert statement.reach is OutboundReach.NOT_REACHED, "the value #2365 needed and lacked"
    assert statement.destinations == ()
    assert statement.records == 0
    assert _NOT_REACHED_FRAGMENT in _system_prompt(model)


# --- §13 item 4: the parked read, dispatched on the resume --------------------


async def test_an_approved_park_carries_the_contact_its_dispatch_established() -> None:
    """§13 item 4, first shape: the resume's own call, and the resume's own admission.

    "A parked read the user approved, dispatched on the resume (ADR-0244 §7) … one
    whose call returns records … so ``records`` is what ``admitted_fourth_group``
    admitted at the resume's own site and not what the call returned (§4). **Neither is
    a servicing and neither drives a step, and an implementation that computes the fact
    only in ``reads`` fails this arm** (§2)."

    §2 binds "at every site that performs a ``WEB_SEARCH`` call, and there are two
    today": the servicing, and this dispatch. §6 then says where they are brought
    together — "on ADR-0244 §7's resume the first two are two different sites and the
    engine is where they are brought together; no site recomputes another's fact".
    """
    wired = _Wired(parked=True, configured=False)
    parked = await wired.engine.converse(_ASKED, timeout=PATIENT)
    assert parked.read_confirmation is not None
    assert parked.outbound_statement is not None
    assert parked.outbound_statement.reach is OutboundReach.NOT_REACHED, (
        "the parking turn opened no channel — ADR-0244 §1: nothing is sent, opened, "
        "claimed or spent — so the contact is the *resume*'s and not this pass's"
    )

    outcome = await wired.engine.resume(
        parked.read_confirmation.token, approved=True, timeout=PATIENT
    )

    assert outcome.read_answer is ReadAnswerOutcome.DISPATCHED
    statement = _statement(outcome)
    assert statement.reach is OutboundReach.REACHED
    assert statement.destinations == (OutboundDestination.SEARCH_PROVIDER,)
    assert statement.records == 1, "what the resume's own admission took in"
    assert outcome.turn is not None
    assert len(outcome.turn.memories) >= statement.records


async def test_an_approved_park_whose_call_found_nothing_carries_a_contact_with_zero() -> None:
    """§13 item 4, second shape: "one that reaches the provider and returns nothing".

    "which carries a contact with ``records`` ``0``." ``SearchRefusal.NO_RESULT`` maps
    to no ``SearchDisposition`` (ADR-0231 §13), so this is §2's eighteenth case reached
    at the dispatch site: a call that completed and recorded none.

    ADR-0242 §6's member is ``None`` here for the same reason, which is the pair
    ADR-0264 §8 says answer different questions: the trail records a contact and no act
    that would have changed what it produced.
    """
    wired = _Wired(parked=True, configured=False, results=())
    parked = await wired.engine.converse(_ASKED, timeout=PATIENT)
    assert parked.read_confirmation is not None

    outcome = await wired.engine.resume(
        parked.read_confirmation.token, approved=True, timeout=PATIENT
    )

    assert outcome.read_answer is ReadAnswerOutcome.DISPATCHED
    statement = _statement(outcome)
    assert statement.reach is OutboundReach.REACHED, "the call reached the provider"
    assert statement.records == 0, "and brought nothing into the supply, which §4 states"
    assert outcome.search_not_serviced is None


async def test_a_declined_park_dispatched_nothing_and_carries_no_statement() -> None:
    """§7's ``None`` case on the resume path: no contact, and no reply composed.

    ADR-0244 §10 makes a declining answer ``turn`` and ``reply`` both ``None``, which is
    ADR-0170 §4's second shape — a pass this decision composes nothing for. "Nothing is
    sent, no channel is opened, no claim is appended, and no minted record exists", so
    no contact is established either and §7's one ``None`` case is the honest answer.
    """
    wired = _Wired(parked=True, configured=False)
    parked = await wired.engine.converse(_ASKED, timeout=PATIENT)
    assert parked.read_confirmation is not None
    assert await _parked(wired) is not None  # type: ignore[arg-type]

    outcome = await wired.engine.resume(
        parked.read_confirmation.token, approved=False, timeout=PATIENT
    )

    assert outcome.read_answer is ReadAnswerOutcome.DECLINED
    assert outcome.reply is None, "ADR-0244 §10's shape"
    assert outcome.outbound_statement is None, (
        "neither established a contact nor composed a reply (ADR-0264 §7)"
    )


# --- §13 item 10's carrying half: the statement on a pass that composed none ---


async def test_a_turn_that_parked_a_read_still_carries_what_it_did_about_the_world() -> None:
    """§6: the member is carried on a pass §6 gives no fragment.

    "ADR-0170 §4 requires no composition on a pass whose step parked for confirmation or
    whose ``turn`` is ``None`` … On it the member is carried and §7's statement is
    rendered exactly as that section fixes, and there is no fragment because there is
    nothing to give one to — which is not a degradation, because the reply the fragment
    guards does not exist."

    **This pass does compose**, which is ADR-0244 §1's own clause — "the turn does not
    park, is not suspended and does not fail" — so what the arm pins is that a turn that
    parked its *read* carries the member and says it reached nothing, which is true: the
    park opened no channel.
    """
    wired = _Wired(parked=True, configured=False)

    outcome = await wired.engine.converse(_ASKED, timeout=PATIENT)

    assert outcome.read_confirmation is not None, "the question this turn parked"
    assert outcome.reply is not None, "and it still composed (ADR-0244 §1)"
    statement = _statement(outcome)
    assert statement.reach is OutboundReach.NOT_REACHED
    assert outcome.search_not_serviced is SearchNotServiced.ANSWER_AWAITED, (
        "both members ride together, neither read off the other (ADR-0264 §8)"
    )


# --- §13 item 11: the routed passes -------------------------------------------


async def test_a_routed_pass_that_is_not_a_park_carries_not_reached() -> None:
    """§13 item 11, whole-reply: "Each carries ``NOT_REACHED``".

    ADR-0197 §10 rules that on a routed pass that is not a park "the composing stage
    runs on §6's two inputs and an answer is owed" — so there is prose, and §1's
    condition binds on it like any other. §7 names this pass among the three that carry
    ``NOT_REACHED`` rather than ``None``.

    **And the routed composer is given neither §6's fragment nor**
    ``_PLAN_IS_ABOUT_ACTING``, "which is the assertion that keeps that closure true":
    ADR-0197 §6 closes the routed composer's inputs at "exactly two", and ADR-0264 §14
    records that no supersession is owed against it because a routed pass is given
    nothing new.
    """
    model = FakeModelProvider("I looked at what has been read.")
    harness = _routed_harness(
        router=_names(RoutableOperation.RECENT_READS),
        composing=_composing(model),
        memory=FakeMemoryStore(now=lambda: AT),
    )

    outcome = await harness.engine.converse("what have you read lately", timeout=PATIENT)

    assert outcome.routed is not None, "the router named an operation and the route was taken"
    assert outcome.routed.outcome is RouteOutcome.PERFORMED
    statement = _statement(outcome)
    assert statement.reach is OutboundReach.NOT_REACHED
    assert statement.destinations == ()
    assert statement.records == 0
    prompt = _system_prompt(model)
    assert _NOT_REACHED_FRAGMENT not in prompt, "ADR-0197 §6's two inputs, unnarrowed"
    assert "All of that is about acting" not in prompt, "a routed pass renders no plan block"


async def test_a_routed_park_carries_no_statement_at_all() -> None:
    """§13 item 11: "A **routed park** carries ``None`` and renders nothing".

    §7's one ``None`` case, and the pass it is named over: ADR-0197 §10 rules that on a
    routed park "the composing stage is not reached", and the route opened no channel of
    its own — so the pass neither established a contact nor composed a reply, which is
    exactly what §7 makes the member absent for.

    **The distinction from the pass that *answers* such a park is load-bearing** — that
    one composes, and §7 gives it ``NOT_REACHED``.
    """
    memory = FakeMemoryStore(now=lambda: AT)
    # ADR-0197 §5 resolves the argument "by deterministic local code reading the store
    # the operation itself reads", so a ``forget`` route over an empty store ends
    # ``NOT_FOUND`` rather than parking — the belief is a precondition of the park and
    # not a convenience.
    await _seed_belief(memory)
    harness = _routed_harness(memory=memory)

    outcome = await harness.engine.converse(_ROUTED_PARK_UTTERANCE, timeout=PATIENT)

    assert outcome.routed is not None
    assert outcome.routed.outcome is RouteOutcome.AWAITING_CONFIRMATION
    assert outcome.reply is None, "ADR-0197 §10: a routed park owes no answer"
    assert outcome.outbound_statement is None, (
        "neither established a contact nor composed a reply (ADR-0264 §7)"
    )


async def test_the_streaming_routed_pass_carries_it_on_the_terminal_outcome() -> None:
    """§13 item 11's streaming half: "whole-reply, streaming **and spoken**".

    "which are separate composers from the conversational one and the path an
    implementation updating only the latter would leave behind". The terminal
    ``TurnOutcome`` a streamed routed pass produces carries ``NOT_REACHED`` exactly as
    the whole-reply one does, and the streaming routed composer is given neither of §6's
    two additions — ADR-0197 §6's "exactly two" inputs, unnarrowed.
    """
    harness = _routed_harness(
        router=_names(RoutableOperation.RECENT_READS),
        composing=ComposingStage(
            model=FakeModelProvider(),
            streaming=FakeStreamingCompleter(
                script=(StreamAttempt(deltas=("I looked", " at the trail.")),)
            ),
        ),
        memory=FakeMemoryStore(now=lambda: AT),
    )

    produced = [
        value
        async for value in harness.engine.converse_streaming(
            "what have you read lately", timeout=PATIENT
        )
    ]

    (terminal,) = [value for value in produced if isinstance(value, TurnOutcomeType)]
    assert terminal.routed is not None
    assert terminal.routed.outcome is RouteOutcome.PERFORMED
    statement = _statement(terminal)
    assert statement.reach is OutboundReach.NOT_REACHED
    assert statement.destinations == ()
    assert statement.records == 0
