"""``request_approval``'s runner, and the Approvals channel's declarations (ADR-0361).

The runner writes a request and the call's effect record in one store step, filling
every part of the request from who asks and from the call as authorizing ruled it, and
says how its card went (§2:6-§2:9, §3:3). The declarations are the kind, the two calls
and the approval's input (§3:6, §5:2, §6:1).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Final

import pytest

from ai_assistant.core.channel_validation import APPROVALS, declared_input, origin_kind
from ai_assistant.core.types import (
    OWNER_PERSON_ID,
    ActionRequest,
    ActivationEffect,
    ApprovalGiver,
    ApprovalRequest,
    ApprovalRequestState,
    ApprovalTap,
    CapabilityEffect,
    CapabilityResult,
    ChannelIdentity,
    CostBasis,
    DataTier,
    DeliveryStatus,
    Idempotency,
    PermissionDecision,
    PermissionOutcome,
    PermissionRuling,
    RecordedDelivery,
    RequestedCall,
    Reversibility,
    RiskLevel,
    TicketState,
    ToolCall,
    ToolCost,
    ToolDefinition,
    ToolOutcome,
    ToolResult,
)
from ai_assistant.orchestration.acting import Unwritten
from ai_assistant.orchestration.approval_calls import (
    OUTSIDE_LINE,
    ApprovalAsker,
    ApprovalCalls,
    CardFacts,
    CardOutcome,
    CardPosted,
    asking,
    card_state,
    card_text,
)
from ai_assistant.orchestration.approvals import (
    APPROVALS_KIND,
    REQUEST_APPROVAL,
    THE_APPROVALS,
    approval_input,
    nested_call,
    ticket_of,
)
from ai_assistant.testing import FakePlanStore

if TYPE_CHECKING:
    from ai_assistant.core.types import FrozenJson

_AT: Final = datetime(2026, 10, 31, 12, 0, tzinfo=UTC)
_DAY: Final = timedelta(hours=24)
_TAP: Final = ApprovalTap(
    who=ApprovalGiver.USER_TAP_ON_TELEGRAM_CARD, at=_AT + timedelta(minutes=1)
)

_BOOK: Final = ToolDefinition(
    id="book",
    capability="book",
    description="Book a table for a date.",
    risk_level=RiskLevel.HIGH,
    reversibility=Reversibility.RECOVERABLE,
    side_effecting=True,
    reads=(DataTier.PERSONAL,),
    writes=(DataTier.PERSONAL,),
    discloses=(),
    cost=ToolCost(basis=CostBasis.FREE),
    idempotency=Idempotency.NONE,
    effect=CapabilityEffect.WORLD,
    leaves_hub=False,
    result=CapabilityResult.NO_OUTSIDE_TEXT,
    outcome_can_be_unknown=True,
    safe_to_repeat=False,
    parameters_schema={
        "type": "object",
        "properties": {"date": {"type": "string"}},
        "required": ["date"],
    },
)

_ARGUMENTS: Final[dict[str, FrozenJson]] = {
    "call": {"capability": "book", "arguments": {"date": "2026-11-02"}},
    "why": "You asked me to book the table.",
}


def _call() -> ToolCall:
    request = ActionRequest(tool=REQUEST_APPROVAL, parameters=_ARGUMENTS)
    decision = PermissionDecision.from_request(
        request,
        PermissionRuling(outcome=PermissionOutcome.ALLOW, reason="ruled by its call"),
        id="decision:ask",
        decided_at=_AT,
        effect="effect:ask",
    )
    return ToolCall(request=request, decision=decision)


def _effect() -> ActivationEffect:
    return ActivationEffect(
        id="effect:ask",
        activation_id="act-ask",
        round="round:ask",
        capability="request_approval",
        values_digest="0" * 64,
        decision_id="decision:ask",
        claimed_at=_AT,
    )


def _asker() -> ApprovalAsker:
    return ApprovalAsker(
        person=OWNER_PERSON_ID,
        activation_id="act-ask",
        round_id="round:ask",
        requested={"decision:ask": RequestedCall(tool=_BOOK, values={"date": "2026-11-02"})},
    )


class _Cards:
    def __init__(self, outcome: CardOutcome | None) -> None:
        self.posted: list[ApprovalRequest] = []
        self.facts: list[CardFacts] = []
        self._outcome = outcome

    async def post(self, request: ApprovalRequest, facts: CardFacts) -> CardPosted:
        self.posted.append(request)
        self.facts.append(facts)
        if self._outcome is None:
            msg = "the line is down"
            raise RuntimeError(msg)
        delivered = (
            RecordedDelivery(
                words="Approval needed: book",
                went=ChannelIdentity(channel_type="telegram", instance_id="bot/1"),
                status=DeliveryStatus.SENT,
            )
            if self._outcome is CardOutcome.SENT
            else None
        )
        return CardPosted(self._outcome, delivered)


async def test_a_request_is_written_with_every_part_code_fills_in() -> None:
    """§2:6-§2:7, §3:5: the person, the asking work and round, the call as ruled, ``why``,
    and the expiry 24 hours on; done once written, the card *not posted* with no poster."""
    plans = FakePlanStore()
    woken: list[None] = []
    runner = ApprovalCalls(
        plans=plans, expiry=_DAY, now=lambda: _AT, wake=lambda: woken.append(None)
    )
    with asking(_asker()):
        answer = await runner.run_claiming(_call(), _effect(), match=None, deliberate_repeat=False)

    assert isinstance(answer, ToolResult)
    assert answer.outcome is ToolOutcome.SUCCEEDED
    assert isinstance(answer.output, Mapping)
    assert str(answer.output["card"]).startswith("not posted")
    (request,) = (await plans.export()).approval_requests
    assert (request.person, request.activation_id, request.round) == (
        OWNER_PERSON_ID,
        "act-ask",
        "round:ask",
    )
    assert request.call.tool.capability == "book"
    assert request.why == "You asked me to book the table."
    assert request.expires_at == _AT + _DAY
    (effect,) = await plans.activation_effects(["act-ask"])
    assert effect.request == request.id, "the effect record names its request (§2:9)"
    assert woken, "the sensor is woken by the write (§3:4)"


@pytest.mark.parametrize(
    ("outcome", "said"),
    [(CardOutcome.SENT, "sent"), (CardOutcome.NOT_DONE, "not done"), (None, "unknown")],
    ids=["sent", "not-done", "raised"],
)
async def test_the_result_says_how_the_card_went(outcome: CardOutcome | None, said: str) -> None:
    """§2:7: sent, not done or unknown; a card that failed leaves the request on the panel."""
    cards = _Cards(outcome)
    runner = ApprovalCalls(plans=FakePlanStore(), expiry=_DAY, now=lambda: _AT, cards=cards)
    with asking(_asker()):
        answer = await runner.run_claiming(_call(), _effect(), match=None, deliberate_repeat=False)

    assert isinstance(answer, ToolResult)
    assert isinstance(answer.output, Mapping)
    assert str(answer.output["card"]).startswith(said)
    assert len(cards.posted) == 1


async def test_a_duplicate_of_a_pending_request_writes_nothing_and_says_since_when() -> None:
    """§2:8: the same capability, values and binding for the same person."""
    plans = FakePlanStore()
    runner = ApprovalCalls(plans=plans, expiry=_DAY, now=lambda: _AT)
    with asking(_asker()):
        await runner.run_claiming(_call(), _effect(), match=None, deliberate_repeat=False)
        again = _effect().model_copy(update={"id": "effect:again"})
        answer = await runner.run_claiming(_call(), again, match=None, deliberate_repeat=False)

    assert isinstance(answer, Unwritten)
    assert "already waits" in answer.reason
    assert "2026-10-31 12:00 UTC" in answer.reason
    assert len((await plans.export()).approval_requests) == 1


async def test_no_request_is_written_outside_the_phases_or_for_a_call_not_ruled() -> None:
    """§2:5: who asks is read from the activation, never from what the call carries."""
    plans = FakePlanStore()
    runner = ApprovalCalls(plans=plans, expiry=_DAY, now=lambda: _AT)
    alone = await runner.run_claiming(_call(), _effect(), match=None, deliberate_repeat=False)
    with asking(ApprovalAsker(person=OWNER_PERSON_ID, activation_id="act-ask", round_id="r")):
        unruled = await runner.run_claiming(_call(), _effect(), match=None, deliberate_repeat=False)

    assert isinstance(alone, Unwritten)
    assert isinstance(unruled, Unwritten)
    assert (await plans.export()).approval_requests == ()


def test_the_expiry_is_positive() -> None:
    with pytest.raises(ValueError, match="positive"):
        ApprovalCalls(plans=FakePlanStore(), expiry=timedelta(0), now=lambda: _AT)


# --- the declarations (§3:6, §5:1, §6:1) -------------------------------------------------


def test_the_kind_is_declared_as_the_task_schedulers_is() -> None:
    """§3:6: pushes, no window, no approval giver, private, and no author established."""
    assert APPROVALS_KIND.channel_type == APPROVALS == THE_APPROVALS.channel_type
    assert APPROVALS_KIND.window.value == "none"
    assert APPROVALS_KIND.approval_giver is None
    assert APPROVALS_KIND.audience.value == "private"
    assert not APPROVALS_KIND.establishes_the_user
    assert APPROVALS_KIND.input_parties(THE_APPROVALS) == ((), ())


def test_the_registers_origin_row_and_empty_parties() -> None:
    """§3:6, ADR-0351 §2:4: the Approvals origin, in the Task Scheduler's style."""
    kind = origin_kind(APPROVALS)
    assert kind is not None
    assert kind.name == "the approvals"
    assert kind.act == ""
    assert "no one is there" in kind.described
    assert declared_input(THE_APPROVALS) == ((), ())


def test_request_approval_is_declared_not_safe_to_repeat_on_the_assistants_records() -> None:
    """§2:9, §3:3: claimed and recorded under ADR-0306 §5, and it never leaves the hub."""
    assert REQUEST_APPROVAL.effect is CapabilityEffect.OWN_RECORDS
    assert not REQUEST_APPROVAL.safe_to_repeat
    assert not REQUEST_APPROVAL.leaves_hub
    assert nested_call(_ARGUMENTS) == ("book", {"date": "2026-11-02"})
    assert nested_call({"call": {"capability": "book"}, "why": "x"}) is None


def test_the_input_states_the_outcome_and_a_ticket_is_held_only_while_usable() -> None:
    """§5:1, §5:7, §5:9, §6:1-§6:2: the outcome and the request, and no one's words."""
    request = ApprovalRequest(
        id="approval:1",
        person=OWNER_PERSON_ID,
        activation_id="act-ask",
        round="round:ask",
        call=RequestedCall(tool=_BOOK, values={"date": "2026-11-02"}),
        why="You asked me to book the table.",
        written_at=_AT,
        expires_at=_AT + _DAY,
    )
    with pytest.raises(ValueError, match="answered or expired"):
        approval_input(request)
    tap = ApprovalTap(who=ApprovalGiver.USER_TAP_ON_HUB_PANEL, at=_AT)
    approved = request.model_copy(
        update={"state": ApprovalRequestState.APPROVED, "answer": tap, "ticket": TicketState.HELD}
    )
    text = approval_input(approved)
    assert "approved" in text
    assert "approval:1" in text
    assert "You asked me" not in text, "its why is context, never the input"
    assert ticket_of(approved, at=_AT) is not None
    assert ticket_of(approved, at=_AT + _DAY) is None, "it expires with its request"
    denied = request.model_copy(update={"state": ApprovalRequestState.DENIED, "answer": tap})
    assert ticket_of(denied, at=_AT) is None
    assert "denied" in approval_input(denied)


async def test_the_card_is_handed_what_its_request_does_not_record_and_its_delivery_kept() -> None:
    """ADR-0361 §2:11, §4:3: the outside-content fact from the round's ruling, and what
    the card sent kept by the call's decision until the phases record its entry, once."""
    cards = _Cards(CardOutcome.SENT)
    runner = ApprovalCalls(plans=FakePlanStore(), expiry=_DAY, now=lambda: _AT, cards=cards)
    asker = replace(_asker(), read_outside=True)
    with asking(asker):
        await runner.run_claiming(_call(), _effect(), match=None, deliberate_repeat=False)

    (facts,) = cards.facts
    assert facts.read_outside
    delivered = runner.card_delivery(str(_call().decision.id))
    assert delivered is not None
    assert delivered.status is DeliveryStatus.SENT
    assert runner.card_delivery(str(_call().decision.id)) is None, "taken once"


def _request(**fields: object) -> ApprovalRequest:
    base = ApprovalRequest(
        id="approval:1",
        person=OWNER_PERSON_ID,
        activation_id="act-ask",
        round="round:ask",
        call=RequestedCall(tool=_BOOK, values={"date": "2026-11-02"}),
        why="You asked me to book the table.",
        written_at=_AT,
        expires_at=_AT + _DAY,
    )
    return base.model_copy(update=fields)


def test_a_card_shows_the_line_why_where_outside_content_expiry_and_state() -> None:
    """§2:11: the one renderer, in its order; a record's identifier is never shown."""
    origin = ChannelIdentity(channel_type="conversation", instance_id="conversation:secret")
    text = card_text(_request(), CardFacts(origin=origin, read_outside=True), now=_AT)

    lines = text.split("\n")
    assert lines[0] == "Approval needed:"
    assert lines[1].startswith("book")
    assert '"2026-11-02"' in lines[1]
    assert "Why: You asked me to book the table." in lines
    assert "Asked in the hub chat." in lines
    assert OUTSIDE_LINE in lines
    assert any(line.startswith("Expires ") for line in lines)
    assert lines[-1] == "Waiting for your answer."
    assert "conversation:secret" not in text


@pytest.mark.parametrize(
    ("fields", "state"),
    [
        ({}, "pending"),
        ({"state": ApprovalRequestState.EXPIRED}, "expired"),
        ({"state": ApprovalRequestState.DENIED, "answer": _TAP}, "denied"),
        (
            {"state": ApprovalRequestState.APPROVED, "answer": _TAP, "ticket": TicketState.HELD},
            "approved",
        ),
        (
            {
                "state": ApprovalRequestState.APPROVED,
                "answer": _TAP,
                "ticket": TicketState.USED,
                "spent_by": "effect:used",
            },
            "used",
        ),
        (
            {"state": ApprovalRequestState.APPROVED, "answer": _TAP, "ticket": TicketState.VOID},
            "not_used",
        ),
    ],
    ids=["pending", "expired", "denied", "approved", "used", "not-used"],
)
def test_a_cards_state_is_where_its_request_stands(fields: dict[str, object], state: str) -> None:
    """§4:5: approved, denied, expired, and after a yes, used or not used."""
    request = ApprovalRequest.model_validate({**_request().model_dump(), **fields})

    assert card_state(request, now=_AT) == state


def test_a_pending_request_past_its_expiry_shows_expired() -> None:
    """§3:5: no tap can approve it now, whether or not the sensor has ended it."""
    assert card_state(_request(), now=_AT + _DAY) == "expired"


def test_a_card_whose_origin_is_not_recorded_says_so() -> None:
    """Where the asking work came from is not known: the card says so, and no outside line."""
    text = card_text(_request(), CardFacts(origin=None, read_outside=False), now=_AT)

    assert "Where it was asked is not recorded." in text
    assert OUTSIDE_LINE not in text
