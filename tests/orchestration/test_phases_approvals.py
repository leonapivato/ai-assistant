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
import re
from dataclasses import dataclass, field
from datetime import timedelta
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, Final, cast

import pytest
from exchange_support import tags, text_call
from phases_support import open_conversation, phases_harness, said, until
from task_support import activation, write_task
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
    DueAt,
    EpisodicMemory,
    OccurrenceState,
    PermissionDecision,
    PermissionOutcome,
    PermissionRuling,
    PersonActHow,
    PersonModelAct,
    ProcessingStatus,
    ProfileField,
    ProposedCall,
    ProposedSuggestion,
    RoundResponse,
    ScheduledTaskAuthor,
    SuggestionKind,
    TicketState,
    ToolOutcome,
)
from ai_assistant.orchestration.approval_calls import ApprovalsSeams, CardFacts, card_text
from ai_assistant.orchestration.approvals import THE_APPROVALS
from ai_assistant.orchestration.authorizer import AuthorizingStage
from ai_assistant.orchestration.person_block import PersonBlocks
from ai_assistant.orchestration.phase_path import PhasePath
from ai_assistant.orchestration.stories import episode_address
from ai_assistant.testing import (
    FakeMemoryStore,
    FakePersonModelStore,
    FakePlanStore,
    FakeToolCallingCompleter,
)
from ai_assistant.testing.memories import memory, remembered_support, said_support

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Sequence
    from datetime import datetime

    from test_engine import Harness

    from ai_assistant.core.types import (
        FrozenJson,
        OfferedTool,
        PersonModel,
        PlanningExchange,
        ScheduledTask,
    )

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
    asks: ProposedCall = field(default_factory=_ask)
    waited: bool = False
    took: bool = False
    ran: int = 0
    results: list[list[dict[str, Any]]] = field(default_factory=list)

    async def __call__(self, exchange: PlanningExchange) -> RoundResponse:
        self.results.append(_results(exchange))
        if not exchange.steps:
            return RoundResponse(calls=(self.asks,))
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


def test_a_message_into_a_taken_place_gone_since_goes_nowhere(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADR-0361 §7:3, ADR-0357 §2:4: never redirected into the activation's own place."""
    from ai_assistant.core.types import (  # noqa: PLC0415
        ChannelIdentity,
        JoinedInput,
        RecordedInputMessage,
    )
    from ai_assistant.orchestration import phase_path  # noqa: PLC0415
    from ai_assistant.orchestration.matters import Became, Named  # noqa: PLC0415

    taken = ChannelIdentity(channel_type="conversation", instance_id="c-2")
    state = SimpleNamespace(
        took=[Named("act-newer", None, Became.TAKEN)],
        joined=[
            JoinedInput(
                joined_at=AT,
                channel=taken,
                messages=(RecordedInputMessage(text="only two bedrooms", sent_at=AT),),
                taken_over_from="act-newer",
            )
        ],
    )
    monkeypatch.setattr(phase_path, "active_state", lambda: state)
    working = SimpleNamespace(
        scheduling=SimpleNamespace(speaks_by_label=False, targets={}),
        target=None,
        conversation_id="c-1",
    )
    path = cast("PhasePath", SimpleNamespace(_writer=None))
    target = PhasePath._target(path, cast("Any", working), "conversation:c-2")
    assert target is None, "gone since the list was built: nowhere"
    own = PhasePath._target(path, cast("Any", working), "conversation:c-1")
    assert own is not None
    assert own.place == "conversation:c-1"


# --- ADR-0362: the person model's calls and the Task Scheduler's under a ticket ------------

_DIET: Final = memory("m:diet", "Eats no meat.", said_support(when=AT, added_at=AT))
#: The same memory, still current, once it also rests on a remember call made over
#: outside content (ADR-0328 §7:6).
_REMEMBERED_DIET: Final = memory(
    "m:remembered-diet", "Eats no meat.", remembered_support(when=AT, added_at=AT)
)
_OUTSIDE_DIET: Final = memory(
    _REMEMBERED_DIET.id,
    _REMEMBERED_DIET.content,
    *_REMEMBERED_DIET.supports,
    remembered_support(effect="effect-2", outside=True, when=AT, added_at=AT),
)
#: A delay that keeps a spawned task pending while a case reads it.
_LATER: Final = 600


def _asking(capability: str, call_id: str, **arguments: FrozenJson) -> ProposedCall:
    """A request for the person's yes to one call, its arguments as planning sends them."""
    return ProposedCall(
        call_id=call_id,
        name="request_approval",
        arguments={
            "call": {"capability": capability, "arguments": arguments},
            "why": f"You asked me to {capability}.",
        },
    )


def _memory_label(exchange: PlanningExchange) -> str:
    """The M label the work was shown its one memory under."""
    (shown,) = {one.get("label") for one in tags(_text(exchange), "memory")}
    assert shown is not None
    return shown


def _task_labels(exchange: PlanningExchange) -> list[str]:
    """The T labels the last round's results named, in the order they first appear."""
    held = " ".join(one.text for one in exchange.steps[-1].report.results)
    return list(dict.fromkeys(re.findall(r'"(T[1-9][0-9]*)"', held)))


async def _run_each_ticket(exchange: PlanningExchange) -> RoundResponse:
    """An approval's activation: it runs the ticket it holds in its first round, once."""
    ticket = _ticket(exchange)
    if exchange.steps or ticket is None:
        return RoundResponse()
    return RoundResponse(calls=(_run(ticket),))


@dataclass
class _People:
    """A person-model store beside the hub's memory store, holding the diet memory."""

    memory: FakeMemoryStore = field(default_factory=lambda: FakeMemoryStore(now=lambda: AT))
    store: FakePersonModelStore = field(
        default_factory=lambda: FakePersonModelStore(now=lambda: AT)
    )

    @property
    def stores(self) -> dict[str, Any]:
        """The harness's knobs: the memory store, and the person block over both."""
        return {
            "memory": self.memory,
            "person_blocks": PersonBlocks(store=self.store, memory=self.memory),
        }

    async def model(self) -> PersonModel:
        model = await self.store.read(OWNER_PERSON_ID)
        assert model is not None
        return model


async def _asked_and_tapped(harness: Harness, count: int) -> tuple[ApprovalRequest, ...]:
    """Wait for ``count`` requests and the asking work to end, then approve each by a tap."""
    requests = await _until_requests(harness, count)
    await _frozen(harness, str(requests[0].activation_id))
    for one in requests:
        await _tap(harness, one)
    return requests


async def _until_used(
    harness: Harness, requests: Sequence[ApprovalRequest]
) -> list[ApprovalRequest]:
    """Wait until every ticket is used and the work that ran it has ended, then read each.

    A ticket is spent when its call is claimed, before the call runs, so each approval's
    own activation, which ran it or whose input a take carried to the work that did, is
    waited on to freeze before anything the call wrote is read.
    """

    async def used() -> bool:
        held = [await _held(harness, str(one.id)) for one in requests]
        return all(one.ticket is TicketState.USED for one in held)

    await until(used, what="every ticket to be used")
    held = [await _held(harness, str(one.id)) for one in requests]
    for one in held:
        assert one.pushed_to is not None
        await _frozen(harness, str(one.pushed_to))
    return held


def _by_capability(requests: Sequence[ApprovalRequest]) -> dict[str, ApprovalRequest]:
    return {str(one.call.tool.capability): one for one in requests}


async def _tasks(harness: Harness) -> tuple[ScheduledTask, ...]:
    return (await harness.plans.export()).scheduled_tasks


async def test_a_set_profile_and_a_pin_each_run_under_a_ticket_naming_the_request() -> None:
    """ADR-0362 §2:1, §2:4, §6:3: asked by request_approval, tapped, and run by run_approved,
    each recorded with the request form's act: the request, and the approval's own episode."""
    people = _People()
    await people.memory.add(_DIET)
    # The observer's pin suggestion shows the memory to planning under an M label.
    await people.store.record_suggestion(
        OWNER_PERSON_ID,
        ProposedSuggestion(kind=SuggestionKind.PIN, memory_id=_DIET.id, episode_id="activation:a0"),
    )

    async def person(exchange: PlanningExchange) -> RoundResponse:
        if exchange.steps:
            return RoundResponse()
        return RoundResponse(
            calls=(
                _asking("set_profile", "ask-1", field="address", value="Leo"),
                _asking("pin", "ask-2", memory=_memory_label(exchange)),
            )
        )

    planner = _Planner(person, _run_each_ticket)
    harness = _harness(planner, **people.stores)
    await harness.engine.start()
    try:
        await _start(harness, "call me Leo, and keep in mind that I eat no meat")
        requests = await _asked_and_tapped(harness, 2)
        held = _by_capability(await _until_used(harness, requests))
        model = await people.model()
    finally:
        await harness.engine.aclose()

    # ADR-0338 §8:6, ADR-0361 §2:11: the pin's card and its ticket show the memory's
    # wording as the asking round read it, never its id.
    pinning = held["pin"]
    assert pinning.call.wording == _DIET.content
    card = card_text(pinning, CardFacts(origin=None, read_outside=False), now=AT)
    assert f'pin — memory: "{_DIET.content}"' in card
    assert _DIET.id not in card
    tickets = [
        one.text or ""
        for exchange in planner.approval
        for one in tags(_text(exchange), "ticket")
        if "pin" in (one.text or "")
    ]
    assert tickets
    assert all(_DIET.content in one and _DIET.id not in one for one in tickets)
    assert held["set_profile"].call.wording is None
    assert model.profile.address == "Leo"
    (change,) = [one for one in model.changes if one.field is ProfileField.ADDRESS]
    (pin,) = model.standing_pins
    assert pin.memory_id == _DIET.id
    for act, capability in ((change.act, "set_profile"), (pin.act, "pin")):
        request = held[capability]
        assert request.pushed_to is not None
        assert act == PersonModelAct(
            how=PersonActHow.APPROVAL,
            by=OWNER_PERSON_ID,
            request=request.id,
            episode_id=episode_address(str(request.pushed_to)),
        ), "the request, and the approval's own episode, where the yes was given"
        assert request.pushed_to != request.activation_id


async def test_an_unpin_under_a_ticket_removes_the_pin_and_leaves_the_act_that_made_it() -> None:
    """ADR-0362 §2:5, §6:3: an unpin records no act; its ticket is on its effect record."""
    people = _People()
    await people.memory.add(_DIET)
    made = PersonModelAct(how=PersonActHow.PANEL, by=OWNER_PERSON_ID)
    await people.store.add_pin(OWNER_PERSON_ID, _DIET.id, act=made)

    async def person(exchange: PlanningExchange) -> RoundResponse:
        if exchange.steps:
            return RoundResponse()
        return RoundResponse(calls=(_asking("unpin", "ask-1", memory=_memory_label(exchange)),))

    planner = _Planner(person, _run_each_ticket)
    harness = _harness(planner, **people.stores)
    await harness.engine.start()
    try:
        await _start(harness, "you can stop keeping my diet in mind")
        (request,) = await _until_used(harness, await _asked_and_tapped(harness, 1))
        model = await people.model()
        effects = await harness.plans.activation_effects([str(request.pushed_to)])
    finally:
        await harness.engine.aclose()

    assert request.call.wording == _DIET.content, "its card showed the memory's wording"
    (pin,) = model.pins
    assert pin.removed_at is not None
    assert pin.act == made, "the act that made the pin is left as it was"
    assert model.standing_pins == ()
    (spent,) = [one for one in effects if one.id == request.spent_by]
    assert spent.ticket == request.id
    assert spent.capability == "unpin"


async def test_a_ticketed_spawn_runs_in_the_approvals_own_activation_as_the_persons() -> None:
    """ADR-0362 §3:3-§3:5, §6:3: the approval's own activation, which ADR-0350 §3:4 does not
    admit, runs the spawn its ticket holds; its input carries no authority, and the task's
    author is the person. The write spends the ticket in its own step."""

    async def person(exchange: PlanningExchange) -> RoundResponse:
        if exchange.steps:
            return RoundResponse()
        ask = _asking("spawn", "ask-1", instruction="say hello", delay_minutes=_LATER)
        return RoundResponse(calls=(ask,))

    planner = _Planner(person, _run_each_ticket)
    harness = _harness(planner, task_scheduler=task_seams())
    await harness.engine.start()
    try:
        await _start(harness, "remind me to say hello in ten hours")
        (request,) = await _until_used(harness, await _asked_and_tapped(harness, 1))
        (task,) = await _tasks(harness)
        effects = await harness.plans.activation_effects([str(request.pushed_to)])
    finally:
        await harness.engine.aclose()

    assert task.author is ScheduledTaskAuthor.PERSON
    assert task.instruction == "say hello"
    assert task.parent == request.pushed_to, "spawned by the approval's own activation"
    assert task.set_in == THE_APPROVALS
    (spent,) = [one for one in effects if one.id == request.spent_by]
    assert spent.ticket == request.id
    assert spent.capability == "spawn"
    shown = " ".join(one.text for one in planner.approval[-1].steps[-1].report.results)
    assert "the person's tap on a card in the approvals" in shown, "said as the person's"


async def test_a_ticketed_spawn_taken_by_the_running_work_is_the_persons() -> None:
    """ADR-0362 §3:4-§3:5, §6:3: after a take, the work holding the input runs the spawn."""
    running = _Running(
        asks=_asking("spawn", "ask-1", instruction="say hello", delay_minutes=_LATER)
    )
    planner = _Planner(running)
    harness = _harness(planner, task_scheduler=task_seams())
    await harness.engine.start()
    try:
        await _start(harness, "remind me to say hello in ten hours")
        (request,) = await _until_requests(harness, 1)
        asking = str(request.activation_id)
        await _tap(harness, request)

        async def offered() -> bool:
            state = harness.engine._running_state(asking)
            return state is not None and bool(state.offers)

        await until(offered, what="the approval's input to be offered to the asking work")
        running.gate.set()
        await _frozen(harness, asking)
        (held,) = await _until_used(harness, [request])
        tasks = await _tasks(harness)
    finally:
        await harness.engine.aclose()

    assert running.took
    assert planner.approval == []
    (task,) = tasks
    assert task.author is ScheduledTaskAuthor.PERSON
    assert task.parent == asking, "spawned by the work the input joined"
    assert held.spent_by is not None


async def test_a_ticketed_cancel_and_replace_reach_tasks_the_running_work_did_not_spawn() -> None:
    """ADR-0362 §3:5, §6:3: under a ticket, the call may cancel or replace any of the
    person's tasks, though the approval's activation spawned neither and its input carries
    no authority."""
    plans = FakePlanStore(now=lambda: AT)
    elsewhere = activation()
    later = DueAt(at=AT + timedelta(days=2))
    kept = await write_task(plans, elsewhere, when=later, instruction="water the plants")
    moved = await write_task(plans, elsewhere, when=later, instruction="call the vet")

    async def person(exchange: PlanningExchange) -> RoundResponse:
        if not exchange.steps:
            listing = ProposedCall(call_id="list-1", name="list_tasks", arguments={})
            return RoundResponse(calls=(listing,))
        if len(exchange.steps) > 1:
            return RoundResponse()
        first, second = _task_labels(exchange)
        cancel = _asking("cancel_task", "ask-1", task=first)
        replace = _asking(
            "spawn", "ask-2", instruction="call the vet", delay_minutes=_LATER, replaces=second
        )
        return RoundResponse(calls=(cancel, replace))

    planner = _Planner(person, _run_each_ticket)
    harness = _harness(planner, plans=plans, task_scheduler=task_seams())
    await harness.engine.start()
    try:
        await _start(harness, "drop the plants reminder and move the vet call")
        requests = await _asked_and_tapped(harness, 2)
        held = _by_capability(await _until_used(harness, requests))
        tasks = {one.id: one for one in await _tasks(harness)}
        cancelling = held["cancel_task"]
        effects = await harness.plans.activation_effects([str(cancelling.pushed_to)])
    finally:
        await harness.engine.aclose()

    assert dict(cancelling.call.values) == {"task": kept.id}
    (spent,) = [one for one in effects if one.id == cancelling.spent_by]
    assert spent.outcome is ToolOutcome.SUCCEEDED, "the cancel ran, under its ticket"
    for gone in (kept.id, moved.id):
        # Cancelled, and tidied away once nothing of it is live (ADR-0350 §7:8).
        assert gone not in tasks or tasks[gone].occurrences[0].state is OccurrenceState.CANCELLED
    (replacing,) = [one for one in tasks.values() if one.id not in {kept.id, moved.id}]
    assert replacing.author is ScheduledTaskAuthor.PERSON
    assert replacing.parent == elsewhere, "a replace takes the replaced task's parent"
    assert replacing.instruction == "call the vet"


async def test_a_request_for_a_call_the_asking_activation_cannot_run_writes_nothing() -> None:
    """ADR-0362 §3:6, §6:3: the approval's own activation, which ADR-0350 §3:4 does not
    admit, may ask, but a spawn would come back not here, so no request is written."""
    told: list[dict[str, Any]] = []

    async def person(exchange: PlanningExchange) -> RoundResponse:
        return RoundResponse(calls=(_ask(),)) if not exchange.steps else RoundResponse()

    async def approval(exchange: PlanningExchange) -> RoundResponse:
        if not exchange.steps:
            ask = _asking("spawn", "ask-9", instruction="say hello", delay_minutes=_LATER)
            return RoundResponse(calls=(ask,))
        told.extend(_results(exchange))
        return RoundResponse()

    planner = _Planner(person, approval)
    harness = _harness(planner, task_scheduler=task_seams())
    await harness.engine.start()
    try:
        await _start(harness)
        await _asked_and_tapped(harness, 1)
        await until(lambda: _settled(told), what="the approval's second round")
        requests = await _requests(harness)
        tasks = await _tasks(harness)
    finally:
        await harness.engine.aclose()

    (refused,) = told
    assert "cannot run here" in refused["outcome"]
    assert len(requests) == 1, "only the person's work's request"
    assert tasks == ()


@pytest.mark.parametrize("capability", ["pin", "unpin"])
@pytest.mark.parametrize("change", ["gone", "outside"])
async def test_a_worded_request_whose_memory_cannot_be_shown_is_not_written(
    capability: str, change: str
) -> None:
    """ADR-0338 §8:6, ADR-0361 §2:11, ADR-0307 §9:2: a memory gone, or resting on outside
    content, since the round saw it leaves its card no wording to show, so no request."""
    people = _People()
    await people.memory.add(_REMEMBERED_DIET)
    if capability == "pin":
        await people.store.record_suggestion(
            OWNER_PERSON_ID,
            ProposedSuggestion(
                kind=SuggestionKind.PIN, memory_id=_REMEMBERED_DIET.id, episode_id="activation:a0"
            ),
        )
    else:
        made = PersonModelAct(how=PersonActHow.PANEL, by=OWNER_PERSON_ID)
        await people.store.add_pin(OWNER_PERSON_ID, _REMEMBERED_DIET.id, act=made)
    told: list[dict[str, Any]] = []

    async def person(exchange: PlanningExchange) -> RoundResponse:
        if not exchange.steps:
            label = _memory_label(exchange)
            # Changed between the round that saw it and that round's acting.
            if change == "gone":
                await people.memory.delete(_REMEMBERED_DIET.id)
            else:
                await people.memory.add(_OUTSIDE_DIET)
            return RoundResponse(calls=(_asking(capability, "ask-1", memory=label),))
        told.extend(_results(exchange))
        return RoundResponse()

    planner = _Planner(person)
    harness = _harness(planner, **people.stores)
    await harness.engine.start()
    try:
        await _start(harness, "about my diet")
        await until(lambda: _settled(told), what="the second round")
        requests = await _requests(harness)
    finally:
        await harness.engine.aclose()

    assert _OUTSIDE_DIET.rests_on_outside_content
    (refused,) = told
    assert "could not show its wording" in str(refused)
    assert requests == ()
