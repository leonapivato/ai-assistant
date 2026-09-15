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

from test_converse_spoken import _MP4, _recording
from test_engine import (
    AT,
    EGRESS_SCHEMA,
    PATIENT,
    Harness,
    NoStepPlanner,
    OneStepPlanner,
    bound_binder,
)
from test_engine import (
    egress_confirmable as _egress_confirmable,
)
from test_engine import (
    tool as _tool,
)
from test_engine_goal_association import _associating, _goal, _seed
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
    AssociationVerdict,
    Disposition,
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
    FakeSpeechTranscriber,
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
_INDETERMINATE_FRAGMENT: Final = "this system cannot say whether it reached outside itself"

#: The opening clause of ``composing._PLAN_IS_ABOUT_ACTING``, whose **absence** is what
#: keeps ADR-0197 §6's "exactly two" closure true on every routed composer (ADR-0264 §14).
_PLAN_SCOPE_LEAD: Final = "All of that is about acting"

#: The sentence #2365 records a reply making on a turn that asked for no search.
_FALSE_CLAIM: Final = "already in front of me from this turn's searches"

#: The sentence #2268 records a reply making on a turn whose search was serviced.
_DENIAL: Final = "nothing was searched just now"


@final
class _Wired:
    """An engine over shared stores, with a search this deployment is configured for."""

    def __init__(  # noqa: PLR0913 — one knob per thing a case varies about the deployment: what the provider answers, whether a park can be written, whether the search is configured, the composing model, the planner, the tools and the streaming completer; each is one fact and none is derivable from another
        self,
        *,
        results: Sequence[str] = ("a result about the bell tower",),
        parked: bool = False,
        configured: bool = True,
        model: FakeModelProvider | None = None,
        planner: Any = None,
        tools: tuple[Any, ...] = (),
        one_id: bool = False,
        streaming: FakeStreamingCompleter | None = None,
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
        # ``one_id`` mints every record of a response under **one** identifier, which is
        # the shape §13 item 4 asks for: "two of them under one id, so ``records`` is
        # what ``admitted_fourth_group`` admitted at the resume's own site and not what
        # the call returned". ``SearchOutcome`` constrains neither identifier uniqueness
        # nor record count (§4), so this is the seam's own latitude and not a state
        # argued unreachable from the shipped searcher.
        self.searcher = FakeWebSearcher(
            results=tuple(results), id_factory=(lambda: "minted-1") if one_id else None
        )
        self.parks = FakeParkedReads() if parked else None
        self.model = model
        self.streaming = streaming
        # Scripted rather than left to the fake's exhausted-script fallback, so a spoken
        # case drives the same question every other case here drives and the planner is
        # asked for the same read.
        self.transcriber = FakeSpeechTranscriber(transcripts=[_ASKED])
        harness = Harness(
            memory=FakeMemoryStore(now=clock),
            planner=_AskingPlanner(_search(), rounds=1) if planner is None else planner,
            tools=tools,
            binder=bound_binder(tools[0]) if tools else None,
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
            composing=_composing(model, streaming),
            transcriber=self.transcriber,
        )
        self.engine = harness.engine


def _composing(
    model: FakeModelProvider | None, streaming: FakeStreamingCompleter | None = None
) -> ComposingStage | None:
    """The **production** composing stage over a fake provider that records its prompt.

    ADR-0227 §7's fidelity rule forbids substituting the renderer whose output the
    assertion is about and permits a fake ``ModelProvider``: the stage assembling the
    prompt is the one the engine ships, and the fake merely records what it was handed
    and answers with the scripted reply.

    ``streaming`` is handed in where a case asserts over the **streaming** composer's
    prompt rather than the whole one's: the two are assembled by different methods of
    the same stage, and the fake completer records what it was given exactly as the fake
    provider does.
    """
    if model is None:
        return None
    return ComposingStage(model=model, streaming=streaming or FakeStreamingCompleter())


def _system_prompt(model: FakeModelProvider, ordinal: int = -1) -> str:
    """The system message the production composing stage assembled, from the fake's record."""
    assert model.calls
    return next(one.content for one in model.calls[ordinal].messages if one.role is Role.SYSTEM)


def _streamed_prompt(streaming: FakeStreamingCompleter) -> str:
    """The system message the **streaming** composer assembled, from the fake's record.

    :func:`_system_prompt`'s twin over the other seam. ``compose_streaming`` reaches the
    ``StreamingCompleter`` and never the ``ModelProvider``, so a streamed pass records
    nothing on the provider and an assertion about its instruction has to be read here.
    """
    assert streaming.calls, "the streaming composer was reached"
    return next(one.content for one in streaming.last_messages if one.role is Role.SYSTEM)


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
    wired = _Wired(
        parked=True,
        configured=False,
        # **Two records under one id**, so the count discriminates: a lane reporting
        # ``len(AnsweredRead.records)`` — what the *call* returned — reads ``2`` here,
        # and only the resume's own admission reads ``1``. ADR-0226 §7's deduplication
        # is over the whole union, which ``admitted_fourth_group`` states in terms.
        results=("the bell tower is the Clérigos", "and it was finished in 1763"),
        one_id=True,
    )
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
    assert len(wired.searcher.searched) == 1, "the resume's one call (ADR-0244 §7)"
    statement = _statement(outcome)
    assert statement.reach is OutboundReach.REACHED
    assert statement.destinations == (OutboundDestination.SEARCH_PROVIDER,)
    assert statement.records == 1, (
        "the call returned two records under one id and the supply admitted one — a "
        "lane reporting what the call returned reads 2 and fails here (ADR-0264 §4)"
    )
    assert outcome.turn is not None


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
    assert _PLAN_SCOPE_LEAD not in prompt, "a routed pass renders no plan block"


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
    streaming = FakeStreamingCompleter(
        script=(StreamAttempt(deltas=("I looked", " at the trail.")),)
    )
    harness = _routed_harness(
        router=_names(RoutableOperation.RECENT_READS),
        composing=ComposingStage(model=FakeModelProvider(), streaming=streaming),
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
    prompt = _streamed_prompt(streaming)
    assert _NOT_REACHED_FRAGMENT not in prompt, "ADR-0197 §6's two inputs, unnarrowed"
    assert _PLAN_SCOPE_LEAD not in prompt, "a routed pass renders no plan block"


# --- §13 item 8 through the engine: the drive's fact, forwarded ---------------


@final
class _SearchingOneStepPlanner(OneStepPlanner):
    """``OneStepPlanner`` that asks for a search on its **first** call of a turn.

    §13 item 8's fold needs one turn that both reached the provider and drove a send,
    and no planner in this tree produces that shape: ``OneStepPlanner`` drives a step
    and asks for nothing, ``_AskingPlanner`` asks and drives nothing. Subclassed rather
    than written out, so the plan is the one every other engine case is built on and the
    two differ by ADR-0226 §4's one additive field.
    """

    def __init__(self, request: Any, **knobs: Any) -> None:
        """Plan one step, and ask for ``request`` on the turn's opening call."""
        super().__init__(**knobs)
        self._request = request

    async def plan(self, goal: Any, **knobs: Any) -> Any:
        """Plan as the base does, with the read request on the first call of the turn."""
        produced = await super().plan(goal, **knobs)
        if knobs.get("read_outcomes"):
            return produced
        return produced.model_copy(
            update={"plan": produced.plan.model_copy(update={"read_request": self._request})}
        )


def _egress_tool() -> Any:
    """An egress declaration ``FakeActionPolicy`` allows outright.

    ``discloses`` is empty, so the fake policy reaches ``ALLOW`` rather than the
    ``CONFIRM`` ADR-0148 §8's second clause draws for a disclosing tool — which is what
    makes the step *driven* rather than parked, and a parked step drives nothing.
    """
    return _tool("smtp", parameters_schema=EGRESS_SCHEMA)


async def test_a_driven_egress_step_makes_the_turn_indeterminate_through_the_engine() -> None:
    """§13 item 8's fold, at the engine — "the arm asserts each of those three turns".

    A turn whose only outbound act was a send the executor reached the callable for
    carries ``INDETERMINATE`` with ``destinations`` empty: §3 refuses the **contact**
    and §2 equally refuses the **denial**, "because a turn that emailed somebody and was
    told it reached nothing would be misled as badly as #2365's was".

    **Asserted here and not only over the assembly**, because
    :func:`~ai_assistant.orchestration.reads.outbound_statement` called with constructed
    inputs cannot detect the engine dropping ``StepDisposition.outbound`` on the way to
    it — which is the one wire between the stage that computes the fact and the value a
    surface renders.
    """
    definition = _egress_tool()
    harness = Harness(
        memory=FakeMemoryStore(now=lambda: AT),
        tools=(definition,),
        binder=bound_binder(definition),
    )

    outcome = await harness.engine.converse("send it", timeout=PATIENT)

    assert outcome.step is not None
    assert outcome.step.disposition is Disposition.EXECUTED
    statement = _statement(outcome)
    assert statement.reach is OutboundReach.INDETERMINATE
    assert statement.destinations == (), "no class is named on a send's account (ADR-0264 §3)"
    assert statement.records == 0


async def test_a_turn_whose_step_was_not_an_outbound_act_reaches_nothing() -> None:
    """§3: "A driven step establishes none, whatever its binding".

    A non-egress call is not an outbound act at all, so it contributes nothing however
    it ran and the turn answers ``NOT_REACHED`` on its own account — which is the
    ``None`` branch of the same wire the arm above exercises, and the one a lane that
    minted ``INDETERMINATE`` from ``Disposition.EXECUTED`` alone would get wrong.
    """
    harness = Harness(memory=FakeMemoryStore(now=lambda: AT), tools=(_tool(),))

    outcome = await harness.engine.converse("send it", timeout=PATIENT)

    assert outcome.step is not None
    assert outcome.step.disposition is Disposition.EXECUTED
    statement = _statement(outcome)
    assert statement.reach is OutboundReach.NOT_REACHED


async def test_a_turn_that_searched_and_planned_a_send_parks_it_and_stays_reached() -> None:
    """§2's fold at the engine, in the shape the pipeline actually reaches.

    **A turn cannot both reach the provider and drive a send, and that is the
    pipeline's own floor rather than a fixture's limit.** The search's minted record is
    in the turn's supply when the step is bound, so the request carries
    ``planned_with_external_content`` — and ADR-0181 §5's disclosure floor makes every
    policy in this tree rule ``CONFIRM`` on it. So the step parks, contributes nothing,
    and what the turn carries is its search's own contact.

    That is the ``search=`` wire and the fold's identity element asserted together;
    the ``egress=`` wire is asserted by the send-only turn above, which carries
    ``INDETERMINATE`` to the outcome, and the **combination** — ``REACHED`` outranking a
    reached callable's ``INDETERMINATE``, with the class still the search's — is
    asserted over §6's own assembly in ``test_runner_outbound.py``, because no pass of
    this pipeline produces it.
    """
    definition = _egress_tool()
    wired = _Wired(planner=_SearchingOneStepPlanner(_search()), tools=(definition,))

    outcome = await wired.engine.converse(_ASKED, timeout=PATIENT)

    assert wired.searcher.searched, "the turn reached the provider"
    assert outcome.step is not None
    assert outcome.step.disposition is Disposition.AWAITING_CONFIRMATION, (
        "ADR-0181 §5's floor: a send planned over searched content is confirmed"
    )
    statement = _statement(outcome)
    assert statement.reach is OutboundReach.REACHED
    assert statement.destinations == (OutboundDestination.SEARCH_PROVIDER,)
    assert statement.records >= 1


# --- §13 item 10's carrying half: a pass that composed no reply ---------------


async def test_a_turn_that_reached_and_then_parked_its_step_carries_the_statement() -> None:
    """§13 item 10's carrying half, and §6's no-fragment case, on one turn.

    §6: "ADR-0170 §4 requires no composition on a pass whose step parked for
    confirmation … On it the member is carried and §7's statement is rendered exactly as
    that section fixes, and there is no fragment because there is nothing to give one
    to — which is not a degradation, because the reply the fragment guards does not
    exist."

    §7 then fixes the asymmetry this arm is about: ``REACHED`` "reports an **act this
    system performed**, which the user is owed whether or not prose was written". So the
    member is carried here with no reply beside it, which is the shape §13 item 10 says
    a **surface** must render — and the shape it could never be handed if this lane
    nulled the member wherever composition produced nothing.
    """
    definition = _egress_confirmable()
    wired = _Wired(planner=_SearchingOneStepPlanner(_search()), tools=(definition,))

    outcome = await wired.engine.converse(_ASKED, timeout=PATIENT)

    assert outcome.step is not None
    assert outcome.step.confirmation is not None, "the step parked for confirmation"
    assert outcome.reply is None, "ADR-0170 §4's first shape: no answer is owed"
    assert outcome.reply_degraded is False, "and composing one did not fail — none was tried"
    statement = _statement(outcome)
    assert statement.reach is OutboundReach.REACHED, "the search still reached the provider"
    assert statement.destinations == (OutboundDestination.SEARCH_PROVIDER,)


async def test_a_pass_whose_composition_degraded_still_carries_what_the_turn_did() -> None:
    """§7's ``None`` rule does **not** reach a pass whose composition failed.

    §7 makes the member ``None`` on "a **routed park** … and every other pass ADR-0170
    §4 **composes nothing for** that established none", and §6 says which passes those
    are in terms: "ADR-0170 §4 requires no composition on a pass whose step parked for
    confirmation or whose ``turn`` is ``None``". A pass whose composition *failed*
    reached the stage and is neither.

    **Two further clauses settle it the same way.** §7 makes the outcome carry "the
    value §6 computed, **by value, and never a second computation**", so deriving a
    different value at the capture point from what the reply turned out to be is the one
    thing that clause forbids — and the composing stage was handed the fragment for the
    value this outcome carries, so a second derivation would leave the prompt and the
    member disagreeing. And §13 item 10 states a failure mode for a **surface** — "one
    that renders ``NOT_REACHED`` with no reply beside it fails it too" — which is only a
    reachable failure if a pass with no reply can carry that member at all.

    So the value is carried and the **rendering** asymmetry is the surface's rule, which
    is where §11 puts it: every arm's assertions about a rendered statement are lane
    2's.
    """
    wired = _Wired(results=(), model=FakeModelProvider(""))

    outcome = await wired.engine.converse(_ASKED, timeout=PATIENT)

    assert outcome.reply is None
    assert outcome.reply_degraded is True, "ADR-0170 §4's third shape, ADR-0173 §6's member"
    statement = _statement(outcome)
    assert statement.reach is OutboundReach.REACHED, (
        "the call reached the provider, and a model outage afterwards unmakes nothing"
    )
    assert statement.records == 0


# --- §13 item 11's spoken half ------------------------------------------------


async def test_the_routed_spoken_pass_carries_the_member_and_renders_none() -> None:
    """§13 item 11's spoken half: a carried member with no rendering there.

    "The **spoken** one renders none, because ADR-0200 §4 makes ``spoken`` the rendering
    of ``outcome.reply`` and of nothing else and §7 adds nothing to ``SpokenTurn`` — so
    the arm asserts a carried member with no rendering there, which is this decision's
    stated spoken cost and not a lane's omission."

    §7 books that cost in terms: "**What is therefore not available on the spoken
    surface is this decision's guarantee**, and that is a stated cost rather than a gap
    (§12) … **This decision's title is bounded by that**: a reply cannot deny a contact
    **on a surface that renders the statement**, and the spoken one does not."
    """
    model = FakeModelProvider("I looked at what has been read.")
    harness = _routed_harness(
        router=_names(RoutableOperation.RECENT_READS),
        composing=_composing(model),
        memory=FakeMemoryStore(now=lambda: AT),
        transcriber=FakeSpeechTranscriber(transcripts=["what have you read lately"]),
    )

    spoken = await harness.engine.converse_spoken(_recording(), plays=(_MP4,), timeout=PATIENT)

    assert spoken.outcome is not None, "a spoken pass that routed still returns an outcome"
    assert spoken.outcome.routed is not None, "the route was taken on the spoken pass too"
    statement = _statement(spoken.outcome)
    assert statement.reach is OutboundReach.NOT_REACHED
    assert not any(field.startswith("outbound") for field in type(spoken).model_fields), (
        "ADR-0200 §4: SpokenTurn gains nothing, so the guarantee does not reach the ear"
    )
    prompt = _system_prompt(model)
    assert _NOT_REACHED_FRAGMENT not in prompt, "ADR-0197 §6's two inputs, unnarrowed"
    assert _PLAN_SCOPE_LEAD not in prompt, "a routed pass renders no plan block"


# --- §13 item 11's unrouted halves: the two composers the routed arms leave behind ---


async def test_the_unrouted_streaming_pass_is_told_what_it_reached_and_carries_it() -> None:
    """§13 item 11's streaming half on the pass that actually composes.

    Item 11 names three composers — "whole-reply, streaming **and spoken**" — "which are
    separate composers from the conversational one and the path an implementation
    updating only the latter would leave behind". The **routed** arms above assert the
    carried member, but ADR-0197 §6 gives the routed composers "exactly two" inputs and
    no fragment, so neither of them exercises §6's forwarding at all: the argument that
    carries it exists only on the unrouted path.

    So this is the arm that discriminates. A lane that dropped ``outbound`` from
    :meth:`Engine._compose_streaming`'s call leaves a streamed answer to a turn that
    searched composed under no instruction — #2268's shape, on the streaming surface —
    while every routed arm and every whole-reply arm above still passes.
    """
    streaming = FakeStreamingCompleter(script=(StreamAttempt(deltas=("I looked", " it up.")),))
    wired = _Wired(model=FakeModelProvider("unreached on this path"), streaming=streaming)

    produced = [value async for value in wired.engine.converse_streaming(_ASKED, timeout=PATIENT)]

    (terminal,) = [value for value in produced if isinstance(value, TurnOutcomeType)]
    assert wired.searcher.searched, "the streamed turn really did reach the provider"
    assert terminal.routed is None, "an ordinary turn, so §6's fragment is owed"
    statement = _statement(terminal)
    assert statement.reach is OutboundReach.REACHED
    assert statement.destinations == (OutboundDestination.SEARCH_PROVIDER,)
    assert statement.records >= 1
    assert _REACHED_FRAGMENT in _streamed_prompt(streaming), (
        "the streaming composer was told the fact too (ADR-0264 §6)"
    )


async def test_the_unrouted_spoken_pass_is_told_what_it_did_and_carries_it() -> None:
    """§13 item 11's spoken half on the pass that actually composes.

    The spoken twin of the arm above, and it is owed for the reason §6 gives in terms:
    "a spoken turn still carries the statement and an **unrouted** one still gets the
    fragment", because "the reply composed for the ear is the only thing that user
    hears, so it is the one place the instruction can still do any work at all".

    **The fact asserted here is the drive's and not a search's**, because ADR-0226 §5
    scopes a read request by channel — it "is not serviced on an operation whose output
    channel's audience is unbounded" — so a spoken turn records ``servicing=declined``
    and reaches no provider at all. The egress classification is therefore the only
    non-``NOT_REACHED`` value this surface can carry, which makes it the arm that
    discriminates: a lane that dropped ``outbound`` from
    :meth:`Engine._composed_spoken`'s call composes the one reply a user only ever hears
    under no instruction, while the routed spoken arm below — given no fragment by
    ADR-0197 §6 in the first place — stays green.
    """
    model = FakeModelProvider("It has gone out.")
    definition = _egress_tool()
    wired = _Wired(model=model, planner=OneStepPlanner(), tools=(definition,))

    spoken = await wired.engine.converse_spoken(_recording(), plays=(_MP4,), timeout=PATIENT)

    assert spoken.outcome is not None
    assert spoken.outcome.routed is None, "an ordinary spoken turn, so §6's fragment is owed"
    assert spoken.outcome.step is not None
    assert spoken.outcome.step.disposition is Disposition.EXECUTED, "the callable was reached"
    statement = _statement(spoken.outcome)
    assert statement.reach is OutboundReach.INDETERMINATE
    assert statement.destinations == (), "no class is named on a send's account (ADR-0264 §3)"
    assert _INDETERMINATE_FRAGMENT in _system_prompt(model), (
        "the spoken composer was told the fact, which §12 books as the whole of what it gets"
    )
    assert not any(field.startswith("outbound") for field in type(spoken).model_fields), (
        "ADR-0200 §4 still adds nothing to SpokenTurn — the fragment is all this surface gets"
    )


# --- §13 item 8 on the resume: the drive's fact across the confirmation seam ---


async def test_an_approved_confirmation_resumed_carries_the_drive_it_performed() -> None:
    """§13 item 8's fold on ADR-0198's resume, the second place a step is driven.

    §2 carries the egress classification "out of the drive" on
    ``StepDisposition.outbound``, and a step driven **inside** a turn and one driven by
    a resolving ``resume`` are two independently fallible wires to the same value:
    :meth:`Engine._resolve_park` reads it off the disposition and
    :meth:`Engine._capture_resumption` is handed the assembly built from it.

    The driven-step arm above covers neither. A lane that dropped either of those two
    forwardings answers a user who has just approved a send with ``NOT_REACHED`` or with
    no statement at all — the denial shape of #2268 on the one pass where the user has
    most reason to want the truth — while that arm, and every runner-level arm, passes.
    """
    model = FakeModelProvider("It has gone out.")
    definition = _egress_confirmable()
    harness = Harness(
        memory=FakeMemoryStore(now=lambda: AT),
        tools=(definition,),
        binder=bound_binder(definition),
        composing=_composing(model),
    )
    parked = await harness.engine.converse("send it", timeout=PATIENT)
    assert parked.step is not None
    assert parked.step.confirmation is not None, "the step parked for confirmation"

    outcome = await harness.engine.resume(
        parked.step.confirmation.token, approved=True, timeout=PATIENT
    )

    assert outcome.step is not None
    assert outcome.step.disposition is Disposition.EXECUTED, "the callable was reached"
    statement = _statement(outcome)
    assert statement.reach is OutboundReach.INDETERMINATE, (
        "§3: the drive establishes no contact, and §2 refuses the denial just as firmly"
    )
    assert statement.destinations == (), "no class is named on a send's account (ADR-0264 §3)"
    assert statement.records == 0, "this pass serviced no read"
    assert _INDETERMINATE_FRAGMENT in _system_prompt(model), (
        "and the resume composes, so §6 gives its stage the fragment for the value it carries"
    )


# --- §7's two further NOT_REACHED shapes, each its own assignment --------------


async def test_an_undecided_turn_reaches_nothing_and_says_so() -> None:
    """§7's ``UNDECIDED`` shape — ``NOT_REACHED``, and never ``None``.

    ADR-0250 §3 makes such a turn take "**no relevance read, no episodic supplement and
    no ``Planner.plan`` call**", so it reached nothing; and it *composes* — §5 has
    ``orchestration`` build the question deterministically from the typed value — so §7's
    ``None`` rule, which is for a pass that "composes nothing", does not reach it.

    **A distinct assignment from the ordinary no-search turn's**, made before
    ``LearningLoop.respond`` is entered and on a path no arm above traverses: the
    #2365 arm's turn runs the whole loop. A lane that left this one ``None`` ships
    exactly what #2365 records — "not a missing acknowledgement but a false provenance
    claim" with nothing typed beside it to contradict — on the one turn shape whose reply
    this system wrote itself.
    """
    harness = Harness(
        planner=NoStepPlanner(),
        associator=_associating(AssociationVerdict.UNDECIDED, "G1", "G2"),
    )
    conversation = (await harness.conversations.begin(None)).id
    for goal_id, outcome_text in (("goal-one", "book a campsite"), ("goal-two", "book a flight")):
        await _seed(
            harness.plans,
            _goal(goal_id, outcome_text, conversation=conversation),
            engaged_in=conversation,
        )

    outcome = await harness.engine.converse(
        "make it Sunday", timeout=PATIENT, conversation_id=conversation
    )

    assert outcome.turn is None
    assert outcome.disambiguation is not None, "the turn asked which goal it is about"
    assert outcome.reply is not None, "and composed the question itself (ADR-0250 §5)"
    statement = _statement(outcome)
    assert statement.reach is OutboundReach.NOT_REACHED
    assert statement.destinations == ()
    assert statement.records == 0


async def test_a_settled_token_restated_reaches_nothing_and_says_so() -> None:
    """§7's restatement shape — ``NOT_REACHED``, and never ``None``.

    ADR-0198 §§1-3's restatement "drives nothing and searches nothing", and §14 records
    that giving it this value "adds a value to ADR-0198 §2's enumeration without changing
    any value it fixes". It composes no prose of its own — the answer was composed once,
    for the request that performed the act — but §7's rendering asymmetry is the
    *surface's* rule, and §7 names this turn among the three carrying ``NOT_REACHED``
    rather than ``None``.

    **Its own assignment, on the branch that returns before the resume proper**, and the
    arm above it cannot reach: the resume arm settles the park, and this one presents the
    same token a second time. A lane that left it ``None`` hands the surface nothing to
    render on a pass that is, by construction, the user asking a second time what
    happened.
    """
    definition = _egress_confirmable()
    harness = Harness(
        memory=FakeMemoryStore(now=lambda: AT),
        tools=(definition,),
        binder=bound_binder(definition),
    )
    parked = await harness.engine.converse("send it", timeout=PATIENT)
    assert parked.step is not None
    assert parked.step.confirmation is not None
    token = parked.step.confirmation.token
    settled = await harness.engine.resume(token, approved=True, timeout=PATIENT)
    assert settled.step is not None
    assert settled.step.disposition is Disposition.EXECUTED

    restated = await harness.engine.resume(token, approved=True, timeout=PATIENT)

    assert restated.turn is None, "ADR-0170 §4's second shape: it is not an exchange"
    assert restated.reply is None
    assert restated.step is not None, "and it restates the step the first answer settled"
    statement = _statement(restated)
    assert statement.reach is OutboundReach.NOT_REACHED
    assert statement.destinations == ()
    assert statement.records == 0


# --- §7's "composed once per turn": one value per pass, not one shared value ---


async def test_mutating_one_turns_statement_cannot_reach_another_turns() -> None:
    """§7's carrier is minted per pass, so no outcome can be rewritten through another.

    ``frozen=True`` stops ``statement.reach = ...`` but not
    ``statement.__dict__["reach"] = ...`` — the bypass ADR-0018 §3 and §4 name, and the
    one the plan store details at its own detachment ("sharing the instance would let a
    caller rewrite the store's own audit record"). A single module-level
    ``NOT_REACHED`` handed out on every routed, restatement and ``UNDECIDED`` outcome
    would put every one of them behind that bypass at once: a caller holding any single
    outcome could make every **other** outcome, including every later one, say this
    system reached outside itself when it did not.

    That is #2365's shape arrived at from the other side, and it is what §7's "composed
    once **per turn**" and "by value" forbid. **Two different producers are crossed
    here** — a routed pass and an ``UNDECIDED`` turn — because a per-site literal that
    was still one shared object would pass an arm that stayed inside one of them.
    """
    routed = _routed_harness(
        router=_names(RoutableOperation.RECENT_READS),
        composing=_composing(FakeModelProvider("I looked at what has been read.")),
        memory=FakeMemoryStore(now=lambda: AT),
    )

    first = await routed.engine.converse("what have you read lately", timeout=PATIENT)
    _statement(first).__dict__["reach"] = OutboundReach.INDETERMINATE

    second = await routed.engine.converse("what have you read lately", timeout=PATIENT)
    undecided = Harness(
        planner=NoStepPlanner(),
        associator=_associating(AssociationVerdict.UNDECIDED, "G1", "G2"),
    )
    conversation = (await undecided.conversations.begin(None)).id
    for goal_id, outcome_text in (("goal-one", "book a campsite"), ("goal-two", "book a flight")):
        await _seed(
            undecided.plans,
            _goal(goal_id, outcome_text, conversation=conversation),
            engaged_in=conversation,
        )
    asked = await undecided.engine.converse(
        "make it Sunday", timeout=PATIENT, conversation_id=conversation
    )

    assert _statement(second).reach is OutboundReach.NOT_REACHED, (
        "a later pass of the same producer says what its own turn did"
    )
    assert _statement(asked).reach is OutboundReach.NOT_REACHED, (
        "and so does a different producer's, which one shared object would not"
    )
    assert _statement(second) is not _statement(first)
    assert _statement(asked) is not _statement(first)
