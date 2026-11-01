"""Approvals by card on the engine: asking, the ticket, the sensor and the join (ADR-0361).

Each case drives the engine with the phases wired and the Approvals channel beside them,
over the canonical fakes. A tap is simulated with the plan store's own member, as the
card's callback and the panel's command make it (AP3, AP4), and the sensor is woken as
they wake it. Planning is answered by a responder that reads each round's exchange as
planning's model would: by what it was shown.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import timedelta
from typing import TYPE_CHECKING, Any, Final, cast

from exchange_support import tags, text_call
from phases_support import open_conversation, phases_harness, said, until
from task_support import seams as task_seams
from test_engine import AT

from ai_assistant.core.types import (
    OWNER_PERSON_ID,
    ActionRequest,
    ApprovalGiver,
    ApprovalRequest,
    ApprovalRequestState,
    ApprovalTap,
    CapabilityEffect,
    EpisodicMemory,
    PermissionDecision,
    PermissionOutcome,
    PermissionRuling,
    ProcessingStatus,
    ProposedCall,
    RoundResponse,
    TicketState,
)
from ai_assistant.orchestration.approval_calls import ApprovalsSeams
from ai_assistant.orchestration.approvals import THE_APPROVALS
from ai_assistant.orchestration.authorizer import AuthorizingStage
from ai_assistant.orchestration.phase_path import PhasePath
from ai_assistant.testing import FakePlanStore, FakeToolCallingCompleter

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Sequence
    from datetime import datetime

    from test_engine import Harness

    from ai_assistant.core.types import OfferedTool, PlanningExchange

_DAY: Final = timedelta(hours=24)
_DATE: Final = "2026-11-02"


def _seams() -> ApprovalsSeams:
    """The Approvals channel's seams for a case: a short recheck, so nothing waits long."""
    return ApprovalsSeams(expiry=_DAY, recheck=timedelta(milliseconds=20))


class _Policy:
    """A call in the world needs the person; one for the date ``never`` is denied."""

    async def decide(self, request: ActionRequest) -> PermissionRuling:
        if request.parameters.get("date") == "never":
            return PermissionRuling(outcome=PermissionOutcome.DENY, reason="test: never")
        if request.tool.effect is CapabilityEffect.WORLD:
            return PermissionRuling(outcome=PermissionOutcome.CONFIRM, reason="test: the world")
        return PermissionRuling(outcome=PermissionOutcome.ALLOW, reason="test: allowed")

    async def resolve(self, confirmed: PermissionDecision, *, approved: bool) -> PermissionRuling:
        if not approved:
            return PermissionRuling(outcome=PermissionOutcome.DENY, reason="test: refused")
        return PermissionRuling(
            outcome=PermissionOutcome.ALLOW, reason="test: approved", authorised_by=confirmed.id
        )


class _Clock:
    """The engine's wall clock, which a case moves."""

    def __init__(self) -> None:
        self.at: datetime = AT

    def __call__(self) -> datetime:
        return self.at


# --- reading an exchange as planning's model does ----------------------------------------


def _text(exchange: PlanningExchange) -> str:
    """Everything the work was shown: its briefing, then each report and its news."""
    parts = [exchange.briefing]
    for step in exchange.steps:
        parts.extend(one.text for one in step.report.results)
        parts.append(step.report.news)
    return "\n".join(parts)


def _approving(exchange: PlanningExchange) -> bool:
    """Whether the work is an approval's: its origin is the approvals (§3:6)."""
    return "- The origin: the approvals," in exchange.briefing


def _results(exchange: PlanningExchange) -> list[dict[str, Any]]:
    """What came of the last round's calls, each as its result shows it."""
    if not exchange.steps:
        return []
    return [json.loads(one.text) for one in exchange.steps[-1].report.results]


def _ticket(exchange: PlanningExchange) -> str | None:
    """The A label of the ticket the work was shown, where it was shown one."""
    shown = tags(_text(exchange), "ticket")
    return None if not shown else shown[-1].get("label")


def _offer(exchange: PlanningExchange) -> str | None:
    """The label of an offer open to the work, where one is shown."""
    shown = tags(_text(exchange), "stimulus", offered="yes")
    return None if not shown else shown[-1].get("label")


def _ask(date: str = _DATE, *, call_id: str = "ask-1") -> ProposedCall:
    return ProposedCall(
        call_id=call_id,
        name="request_approval",
        arguments={
            "call": {"capability": "book", "arguments": {"date": date}},
            "why": "You asked me to book the table.",
        },
    )


def _run(label: str, *, call_id: str = "run-1") -> ProposedCall:
    return ProposedCall(call_id=call_id, name="run_approved", arguments={"label": label})


type Script = Callable[[PlanningExchange], Awaitable[RoundResponse]]


async def _silent(_exchange: PlanningExchange) -> RoundResponse:
    return RoundResponse()


class _Planner(FakeToolCallingCompleter):
    """Planning, answered by one script for the person's work and one for an approval's."""

    def __init__(self, person: Script, approval: Script = _silent) -> None:
        super().__init__(response=lambda _exchange, _tools: RoundResponse())
        self._person = person
        self._approval = approval
        self.person: list[PlanningExchange] = []
        self.approval: list[PlanningExchange] = []

    async def respond(
        self,
        exchange: PlanningExchange,
        tools: Sequence[OfferedTool],
        *,
        model: str | None = None,
    ) -> RoundResponse:
        await super().respond(exchange, tools, model=model)
        if _approving(exchange):
            self.approval.append(exchange)
            return await self._approval(exchange)
        self.person.append(exchange)
        return await self._person(exchange)


def _authorizing(plans: FakePlanStore) -> type[AuthorizingStage]:
    """Authorizing over the harness's plan store, as the composition root wires it."""

    def build(**seams: Any) -> AuthorizingStage:
        return AuthorizingStage(plans=plans, **seams)

    return cast("type[AuthorizingStage]", build)


def _harness(planner: _Planner, *, clock: _Clock | None = None, **stores: Any) -> Harness:
    plans = stores.pop("plans", None) or FakePlanStore(now=lambda: AT)
    knobs: dict[str, Any] = {
        "approvals": _seams(),
        "plans": plans,
        "phases": {"policy": _Policy(), "round_limit": 8, "authorizing": _authorizing(plans)},
        **stores,
    }
    if clock is not None:
        knobs["now"] = clock
    return phases_harness(planner, **knobs)


async def _requests(harness: Harness) -> tuple[ApprovalRequest, ...]:
    return (await harness.plans.export()).approval_requests


async def _until_requests(harness: Harness, count: int) -> tuple[ApprovalRequest, ...]:
    async def written() -> bool:
        return len(await _requests(harness)) >= count

    await until(written, what=f"{count} approval request(s)")
    return await _requests(harness)


async def _tap(
    harness: Harness,
    request: ApprovalRequest,
    state: ApprovalRequestState = ApprovalRequestState.APPROVED,
) -> None:
    """A tap on the request's card, as its surface lands it, and the sensor woken (§4:9)."""
    tap = ApprovalTap(who=ApprovalGiver.USER_TAP_ON_HUB_PANEL, at=request.written_at)
    await harness.plans.answer_approval_request(str(request.id), state, tap)
    harness.engine.approvals_changed()


async def _frozen(harness: Harness, activation_id: str) -> EpisodicMemory:
    found: list[EpisodicMemory] = []

    async def done() -> bool:
        record = await harness.memory.get(f"activation:{activation_id}")
        if (
            isinstance(record, EpisodicMemory)
            and record.processing_record is not None
            and not record.processing_record.is_open
        ):
            found.append(record)
            return True
        return False

    await until(done, what=f"the episode of {activation_id} to freeze")
    return found[-1]


async def _held(harness: Harness, request_id: str) -> ApprovalRequest:
    (held,) = await harness.plans.approval_requests([request_id])
    return held


def _books(harness: Harness) -> list[Any]:
    return [one for one in harness.invoker.invocations if one.request.tool.capability == "book"]


async def _start(harness: Harness, text: str = "book the table") -> str:
    conversation = await open_conversation(harness)
    await harness.engine.write_message(conversation, message=said("m-1", text))
    return conversation


# --- §2:4: a direct call needing the person -------------------------------------------------


async def test_a_direct_call_needing_a_yes_runs_nothing_and_names_request_approval() -> None:
    """§2:4, §9:4: it runs nothing, and comes back saying to ask through request_approval."""
    told: list[dict[str, Any]] = []

    async def person(exchange: PlanningExchange) -> RoundResponse:
        if not exchange.steps:
            call = ProposedCall(call_id="book-1", name="book", arguments={"date": _DATE})
            return RoundResponse(calls=(call,))
        told.extend(_results(exchange))
        return RoundResponse()

    planner = _Planner(person)
    harness = _harness(planner)
    await harness.engine.start()
    try:
        await _start(harness)
        await until(lambda: _settled(told), what="the second round")
        (result,) = told
        assert "request_approval" in result["outcome"]
        assert "same arguments" in result["outcome"]
        assert _books(harness) == []
        assert await _requests(harness) == ()
    finally:
        await harness.engine.aclose()


async def _settled(told: list[Any]) -> bool:
    return bool(told)


# --- §2:2-§2:3, §2:8: what writes no request ------------------------------------------------


async def test_a_nested_call_failing_its_schema_or_denied_writes_no_request() -> None:
    """§2:2-§2:3, §9:4: each comes back refused, and no request is written."""
    told: list[dict[str, Any]] = []

    async def person(exchange: PlanningExchange) -> RoundResponse:
        if not exchange.steps:
            unfit = ProposedCall(
                call_id="ask-1",
                name="request_approval",
                arguments={
                    "call": {"capability": "book", "arguments": {}},
                    "why": "You asked me to book the table.",
                },
            )
            return RoundResponse(calls=(unfit, _ask("never", call_id="ask-2")))
        told.extend(_results(exchange))
        return RoundResponse()

    planner = _Planner(person)
    harness = _harness(planner)
    await harness.engine.start()
    try:
        await _start(harness)
        await until(lambda: _settled(told), what="the second round")
        unfit, denied = told
        assert "do not fit" in unfit["outcome"]
        assert "do not ask" in denied["outcome"]
        assert await _requests(harness) == ()
    finally:
        await harness.engine.aclose()


async def test_no_request_asks_for_a_call_no_ticket_can_run_yet() -> None:
    """#3568: a spawn's write claims itself, so no request asks for it, writing nothing."""
    told: list[dict[str, Any]] = []

    async def person(exchange: PlanningExchange) -> RoundResponse:
        if not exchange.steps:
            spawn = ProposedCall(
                call_id="ask-1",
                name="request_approval",
                arguments={
                    "call": {"capability": "spawn", "arguments": {"instruction": "say hello"}},
                    "why": "You asked me to remind you.",
                },
            )
            return RoundResponse(calls=(spawn,))
        told.extend(_results(exchange))
        return RoundResponse()

    planner = _Planner(person)
    harness = _harness(planner, task_scheduler=task_seams())
    await harness.engine.start()
    try:
        await _start(harness)
        await until(lambda: _settled(told), what="the second round")
        (refused,) = told
        assert "cannot be approved on a card yet" in refused["outcome"]
        assert await _requests(harness) == ()
    finally:
        await harness.engine.aclose()


async def test_a_second_identical_pending_request_is_refused_as_waiting() -> None:
    """§2:7-§2:8, §9:4: done once written; the same call again says it already waits."""
    told: list[list[dict[str, Any]]] = []

    async def person(exchange: PlanningExchange) -> RoundResponse:
        told.append(_results(exchange))
        if len(exchange.steps) == 0:
            return RoundResponse(calls=(_ask(),))
        if len(exchange.steps) == 1:
            return RoundResponse(calls=(_ask(call_id="ask-2"),))
        return RoundResponse()

    planner = _Planner(person)
    harness = _harness(planner)
    await harness.engine.start()
    try:
        await _start(harness)
        await until(lambda: _settled(told[2:]), what="the third round")
        (written,) = told[1]
        assert written["result"]["value"]["request"].startswith("written")
        assert written["result"]["value"]["card"].startswith("not posted")
        (again,) = told[2]
        assert "already waits" in again["outcome"]
        (request,) = await _requests(harness)
        assert request.state is ApprovalRequestState.PENDING
        assert request.person == OWNER_PERSON_ID
        assert dict(request.call.values) == {"date": _DATE}
        assert request.expires_at - request.written_at == _DAY
    finally:
        await harness.engine.aclose()


# --- §6:4, §7: a yes to running work, offered and taken across places -------------------------


@dataclass
class _Running:
    """The person's work: it asks, waits in its second round, takes the offer, runs."""

    gate: asyncio.Event = field(default_factory=asyncio.Event)
    waited: bool = False
    took: bool = False
    ran: int = 0
    results: list[list[dict[str, Any]]] = field(default_factory=list)

    async def __call__(self, exchange: PlanningExchange) -> RoundResponse:
        self.results.append(_results(exchange))
        if not exchange.steps:
            return RoundResponse(calls=(_ask(),))
        if not self.waited:
            self.waited = True
            await self.gate.wait()
            return RoundResponse(calls=(text_call("I asked for your yes.", call_id="m-2"),))
        offer = _offer(exchange)
        if offer is not None and not self.took:
            self.took = True
            take = ProposedCall(
                call_id="take-1", name="answer_offer", arguments={"offer": offer, "take": True}
            )
            return RoundResponse(calls=(take,))
        ticket = _ticket(exchange)
        if ticket is not None and self.ran < 2:
            self.ran += 1
            return RoundResponse(calls=(_run(ticket, call_id=f"run-{self.ran}"),))
        return RoundResponse()


async def test_a_yes_to_running_work_is_offered_across_places_taken_and_run_once() -> None:
    """§6:3-§6:4, §7:1, §5:6, §9:4: offered to the asking work from the approvals, taken,
    and its ticket runs once; a second run_approved is refused."""
    running = _Running()
    planner = _Planner(running)
    harness = _harness(planner)
    await harness.engine.start()
    try:
        await _start(harness)
        (request,) = await _until_requests(harness, 1)
        asking = str(request.activation_id)
        await _tap(harness, request)

        async def offered() -> bool:
            state = harness.engine._running_state(asking)
            return state is not None and bool(state.offers)

        await until(offered, what="the approval's input to be offered to the asking work")
        running.gate.set()
        episode = await _frozen(harness, asking)
        held = await _held(harness, str(request.id))
        approval = held.pushed_to
        assert approval is not None
        own = await _frozen(harness, approval)

        assert running.took
        assert running.ran == 2
        assert planner.approval == [], "while its offer was open it planned no round"
        assert len(_books(harness)) == 1, "the ticket ran its call once"
        assert held.ticket is TicketState.USED
        processing = episode.processing_record
        assert processing is not None
        (joined,) = processing.joined
        assert joined.channel == THE_APPROVALS, "taken from another place"
        assert joined.taken_over_from == approval
        own_record = own.processing_record
        assert own_record is not None
        assert own_record.understanding[-1].continues == (asking,), "code's link (§6:3)"
        second = running.results[-1]
        assert any("names no ticket" in str(one.get("outcome")) for one in second), (
            "a second run_approved of one ticket is refused"
        )
    finally:
        await harness.engine.aclose()


# --- §6:5: a yes after the work ended -------------------------------------------------------


async def test_a_yes_after_the_work_ended_starts_its_own_activation_naming_the_asking_episode() -> (
    None
):
    """§6:2, §6:5, §9:4: its own activation sees which episode asked, and runs the ticket."""

    async def person(exchange: PlanningExchange) -> RoundResponse:
        return RoundResponse(calls=(_ask(),)) if not exchange.steps else RoundResponse()

    ran: list[str] = []

    async def approval(exchange: PlanningExchange) -> RoundResponse:
        ticket = _ticket(exchange)
        if ticket is not None and not ran:
            ran.append(ticket)
            return RoundResponse(calls=(_run(ticket),))
        return RoundResponse()

    planner = _Planner(person, approval)
    harness = _harness(planner)
    await harness.engine.start()
    try:
        await _start(harness)
        (request,) = await _until_requests(harness, 1)
        asking = str(request.activation_id)
        await _frozen(harness, asking)
        await _tap(harness, request)

        async def pushed() -> bool:
            return (await _held(harness, str(request.id))).pushed_to is not None

        await until(pushed, what="the outcome to be pushed")
        approval_id = (await _held(harness, str(request.id))).pushed_to
        assert approval_id is not None
        own = await _frozen(harness, approval_id)

        first = planner.approval[0]
        (context,) = [one for one in tags(first.briefing, "message") if one.get("episode")]
        label = context.get("episode")
        assert context.text is not None
        assert "book" in context.text
        assert "You asked me to book the table." in context.text
        episodes = [one for one in tags(first.briefing, "episode") if one.get("label") == label]
        assert episodes, "the asking episode, by its label and its short view (§6:2)"
        assert ran
        assert len(_books(harness)) == 1
        assert (await _held(harness, str(request.id))).ticket is TicketState.USED
        record = own.processing_record
        assert record is not None
        assert record.status is ProcessingStatus.COMPLETED
    finally:
        await harness.engine.aclose()


# --- §5:7, §5:9: a ticket void once its holder ends; a deny and an expiry grant none --------


async def test_a_ticket_is_void_once_the_work_holding_it_ends_without_running_it() -> None:
    """§5:7, §5:8, §9:4: declining is no call, and the ticket is void when the work ends."""

    async def person(exchange: PlanningExchange) -> RoundResponse:
        return RoundResponse(calls=(_ask(),)) if not exchange.steps else RoundResponse()

    planner = _Planner(person)
    harness = _harness(planner)
    await harness.engine.start()
    try:
        await _start(harness)
        (request,) = await _until_requests(harness, 1)
        await _frozen(harness, str(request.activation_id))
        await _tap(harness, request)

        async def void() -> bool:
            return (await _held(harness, str(request.id))).ticket is TicketState.VOID

        await until(void, what="the ticket to be void")
        assert planner.approval, "its activation planned, and declined"
        assert _ticket(planner.approval[0]) is not None, "it was shown the ticket"
        assert _books(harness) == []
    finally:
        await harness.engine.aclose()


async def test_a_deny_and_an_expiry_each_grant_no_ticket() -> None:
    """§3:5, §3:7, §5:9, §9:4: each starts an activation, which holds no ticket."""

    async def person(exchange: PlanningExchange) -> RoundResponse:
        if exchange.steps:
            return RoundResponse()
        return RoundResponse(calls=(_ask(), _ask("2026-11-03", call_id="ask-2")))

    clock = _Clock()
    planner = _Planner(person)
    harness = _harness(planner, clock=clock)
    await harness.engine.start()
    try:
        await _start(harness)
        denied, lapsing = await _until_requests(harness, 2)
        await _frozen(harness, str(denied.activation_id))
        await _tap(harness, denied, ApprovalRequestState.DENIED)
        clock.at = AT + _DAY + timedelta(minutes=1)
        harness.engine.approvals_changed()

        async def both() -> bool:
            return len(planner.approval) >= 2

        await until(both, what="an activation for each outcome")
        assert all(_ticket(one) is None for one in planner.approval)
        stimuli = [one.briefing for one in planner.approval]
        assert any("denied" in one for one in stimuli)
        assert any("expired" in one for one in stimuli)
        assert (await _held(harness, str(denied.id))).ticket is None
        expired = await _held(harness, str(lapsing.id))
        assert expired.state is ApprovalRequestState.EXPIRED
        assert expired.ticket is None
        assert _books(harness) == []
    finally:
        await harness.engine.aclose()


# --- §3:7: a restart between the pushed mark and admission ----------------------------------


async def test_an_outcome_marked_pushed_and_never_admitted_is_pushed_again_at_start() -> None:
    """§3:7, §9:4: the restart pushes it under the activation its mark names."""

    async def person(exchange: PlanningExchange) -> RoundResponse:
        return RoundResponse(calls=(_ask(),)) if not exchange.steps else RoundResponse()

    planner = _Planner(person)
    harness = _harness(planner)
    await harness.engine.start()
    try:
        await _start(harness)
        (request,) = await _until_requests(harness, 1)
        await _frozen(harness, str(request.activation_id))
    finally:
        await harness.engine.aclose()

    # A dead process left the mark written and nothing admitted under it.
    await harness.plans.answer_approval_request(
        str(request.id),
        ApprovalRequestState.APPROVED,
        ApprovalTap(who=ApprovalGiver.USER_TAP_ON_HUB_PANEL, at=request.written_at),
    )
    left = "6f1c5e2a-7c4b-4d8e-9a3f-2b1d0c9e8f7a"
    await harness.plans.mark_approval_outcome_pushed(str(request.id), left)
    restarted = _harness(
        planner,
        plans=harness.plans,
        memory=harness.memory,
        conversation_store=harness.conversation_store,
    )
    await restarted.engine.start()
    try:
        own = await _frozen(restarted, left)
        record = own.processing_record
        assert record is not None
        assert record.trigger.channel == THE_APPROVALS
        assert (await _held(restarted, str(request.id))).pushed_to == left
    finally:
        await restarted.engine.aclose()


def test_work_no_author_established_for_answers_an_offer_code_linked_to_it() -> None:
    """§6:4: a scheduled task's work, which sees no running work, still answers the offer."""
    offered = PhasePath._running_calls(
        cast("PhasePath", None), None, cast("Any", None), offers=True
    )
    assert offered == frozenset({"answer_offer"})
    assert (
        PhasePath._running_calls(cast("PhasePath", None), None, cast("Any", None), offers=False)
        == frozenset()
    )
