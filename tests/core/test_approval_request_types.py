"""ADR-0361 §8:1: the approval request, its card, its ticket, and the forms that name it.

The request holds §2:6's parts, its answer and where its cards went; the closed
enumerations are added to and never renamed; ``Approval`` gains a tap's form beside the
question's, extending ADR-0321 §4:6's shape; an effect record names the request it wrote
or the ticket it spends; and a confirmation names the request it answers. The Approvals
channel's register entry establishes no author as the user and declares its inputs'
parties empty (§3:6).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Final

import pytest
from pydantic import ValidationError

from ai_assistant.core.channel_validation import APPROVALS, declared_input, establishes_the_user
from ai_assistant.core.types import (
    TAP_GIVERS,
    ActivationEffect,
    Approval,
    ApprovalCard,
    ApprovalEnd,
    ApprovalGiven,
    ApprovalGiver,
    ApprovalRequest,
    ApprovalRequestState,
    ApprovalRequestWrite,
    ApprovalTap,
    ApprovalWriteAnswer,
    ChannelIdentity,
    ConfirmationPart,
    CostBasis,
    Idempotency,
    PermissionDecision,
    PermissionOutcome,
    PermissionRuling,
    PlanExport,
    QuestionPart,
    RequestedCall,
    Reversibility,
    RiskLevel,
    TapOnCard,
    TicketState,
    ToolCost,
    ToolDefinition,
    UserConfirmation,
    YesToQuestion,
)
from ai_assistant.testing import with_phase_declaration

_AT: Final = datetime(2026, 11, 1, 9, 0, tzinfo=UTC)
_EXPIRY: Final = _AT + timedelta(hours=24)
_LINE: Final = ChannelIdentity(channel_type="telegram", instance_id="conn-1/42")
_APPROVALS: Final = ChannelIdentity(channel_type=APPROVALS, instance_id="approvals")
_TAP: Final = ApprovalTap(who=ApprovalGiver.USER_TAP_ON_TELEGRAM_CARD, at=_AT)


def _tool(**overrides: object) -> ToolDefinition:
    fields: dict[str, object] = {
        "id": "stays",
        "capability": "book_stay",
        "description": "Book a stay.",
        "risk_level": RiskLevel.HIGH,
        "reversibility": Reversibility.IRREVERSIBLE,
        "side_effecting": True,
        "reads": (),
        "writes": (),
        "discloses": (),
        "cost": ToolCost(basis=CostBasis.FREE),
        "idempotency": Idempotency.NONE,
        "parameters_schema": {
            "type": "object",
            "properties": {"hotel": {"type": "string"}},
            "required": ["hotel"],
        },
    }
    fields.update(overrides)
    return ToolDefinition(**with_phase_declaration(fields))  # type: ignore[arg-type]  # heterogeneous test kwargs


def _card(minted: str | None = None, position: int | None = None) -> ApprovalCard:
    return ApprovalCard(place=_LINE, position=position, token=minted)


def _call(**overrides: Any) -> RequestedCall:
    fields: dict[str, Any] = {"tool": _tool(), "values": {"hotel": "the Ritz"}}
    fields.update(overrides)
    return RequestedCall(**fields)


def _request(**overrides: Any) -> ApprovalRequest:
    fields: dict[str, Any] = {
        "id": "q1",
        "person": "person:owner",
        "activation_id": "act-ask",
        "round": "r1",
        "call": _call(),
        "why": "You asked me to book it.",
        "written_at": _AT,
        "expires_at": _EXPIRY,
    }
    fields.update(overrides)
    return ApprovalRequest(**fields)


def _tap_approval(**overrides: Any) -> Approval:
    fields: dict[str, Any] = {
        "who": ApprovalGiver.USER_TAP_ON_TELEGRAM_CARD,
        "how": TapOnCard(request="q1", activation_id="act-ask", round="r1", expires_at=_EXPIRY),
        "given": ApprovalGiven(activation_id="act-approval", at=_AT),
        "ends": ApprovalEnd.WHEN_USED_OR_EXPIRED,
    }
    fields.update(overrides)
    return Approval(**fields)


# --- the closed enumerations (§8:1) ------------------------------------------------------


def test_the_enumerations_are_the_ones_the_decision_names() -> None:
    """§8:1: pending/approved/denied/expired, held/used/void, and a giver per surface."""
    assert [one.value for one in ApprovalRequestState] == [
        "pending",
        "approved",
        "denied",
        "expired",
    ]
    assert [one.value for one in TicketState] == ["held", "used", "void"]
    assert {one.value for one in TAP_GIVERS} == {
        "user_tap_on_telegram_card",
        "user_tap_on_hub_panel",
    }
    assert ApprovalEnd.WHEN_USED_OR_EXPIRED.value == "when_used_or_expired"


# --- the request (§2:6) ------------------------------------------------------------------


def test_a_request_is_written_pending_and_round_trips() -> None:
    request = _request()

    assert (request.state, request.answer, request.ticket, request.cards) == (
        ApprovalRequestState.PENDING,
        None,
        None,
        (),
    )
    assert not request.ended
    assert not request.outcome_due
    assert ApprovalRequest.model_validate_json(request.model_dump_json()) == request


def test_an_approved_request_holds_its_ticket_and_its_tap() -> None:
    request = _request(
        state=ApprovalRequestState.APPROVED,
        answer=_TAP,
        ticket=TicketState.USED,
        spent_by="e1",
        cards=(_card("t1", 3), ApprovalCard(place=_LINE)),
        pushed_to="act-approval",
    )

    assert request.ended
    assert not request.outcome_due
    assert ApprovalRequest.model_validate_json(request.model_dump_json()) == request


@pytest.mark.parametrize(
    ("overrides", "match"),
    [
        pytest.param({"expires_at": _AT}, "expires after", id="expiring-when-written"),
        pytest.param({"answer": _TAP}, "carries its tap", id="a-tap-while-pending"),
        pytest.param(
            {"state": ApprovalRequestState.DENIED}, "carries its tap", id="denied-by-no-tap"
        ),
        pytest.param(
            {"state": ApprovalRequestState.APPROVED, "answer": _TAP},
            "holds a ticket",
            id="approved-with-no-ticket",
        ),
        pytest.param(
            {"state": ApprovalRequestState.EXPIRED, "ticket": TicketState.VOID},
            "holds a ticket",
            id="a-ticket-without-a-yes",
        ),
        pytest.param(
            {
                "state": ApprovalRequestState.APPROVED,
                "answer": _TAP.model_copy(update={"at": _EXPIRY}),
                "ticket": TicketState.HELD,
            },
            "before it expires",
            id="answered-at-its-expiry",
        ),
        pytest.param(
            {
                "state": ApprovalRequestState.APPROVED,
                "answer": _TAP,
                "ticket": TicketState.USED,
            },
            "spent it",
            id="used-by-nothing",
        ),
        pytest.param({"pushed_to": "act-x"}, "answered or expired", id="pushed-while-pending"),
        pytest.param(
            {"cards": (_card("t"),) * 2},
            "distinct tokens",
            id="one-token-twice",
        ),
    ],
)
def test_a_request_that_could_not_be_held_is_refused(overrides: dict[str, Any], match: str) -> None:
    with pytest.raises(ValidationError, match=match):
        _request(**overrides)


def test_a_tap_is_a_surfaces() -> None:
    """§4:9: who answered is the giver of the surface tapped, never a message's."""
    with pytest.raises(ValidationError, match="surfaces"):
        ApprovalTap(who=ApprovalGiver.USER_THROUGH_HUB_CHAT, at=_AT)


def test_a_requested_call_is_one_that_could_be_ruled_on() -> None:
    """§2:2, §2:6: its values validate against the schema, and its mark fits the capability."""
    assert _call().request.parameters == {"hotel": "the Ritz"}
    with pytest.raises(ValidationError, match="admits"):
        _call(values={"room": "12"})
    with pytest.raises(ValidationError, match="not safe to repeat"):
        _call(tool=_tool(safe_to_repeat=True), deliberate_repeat=True)


def test_two_calls_are_the_same_by_capability_values_and_binding() -> None:
    """§2:8: the duplicate check's sameness, read on no other part of the call."""
    assert _call().same_call(_call(deliberate_repeat=True))
    assert _call().same_call(_call(tool=_tool(id="another-provider")))
    assert not _call().same_call(_call(values={"hotel": "the Savoy"}))


def test_a_write_carries_its_request_except_on_the_backstop() -> None:
    assert ApprovalRequestWrite(answer=ApprovalWriteAnswer.ALREADY_DONE).request is None
    with pytest.raises(ValidationError):
        ApprovalRequestWrite(answer=ApprovalWriteAnswer.WRITTEN)
    with pytest.raises(ValidationError):
        ApprovalRequestWrite(answer=ApprovalWriteAnswer.ALREADY_DONE, request=_request())


# --- the approval's tap form (§5, §8:1) --------------------------------------------------


def test_a_taps_approval_covers_its_request_and_ends_used_or_expired() -> None:
    """§8:1: the form names the one request; it may be given in the asking work (§6:4)."""
    approval = _tap_approval()
    joined = _tap_approval(given=ApprovalGiven(activation_id="act-ask", at=_AT))

    assert approval.covers == ()
    assert joined.given.activation_id == joined.how.activation_id
    assert Approval.model_validate_json(approval.model_dump_json()) == approval


@pytest.mark.parametrize(
    ("overrides", "match"),
    [
        pytest.param(
            {"covers": (QuestionPart(round="r1", part=1),)}, "no question part", id="a-part"
        ),
        pytest.param({"who": ApprovalGiver.USER_THROUGH_HUB_CHAT}, "tapping", id="a-message"),
        pytest.param({"ends": ApprovalEnd.WHEN_USED}, "expires", id="ends-only-when-used"),
    ],
)
def test_a_taps_approval_is_held_to_its_form(overrides: dict[str, Any], match: str) -> None:
    with pytest.raises(ValidationError, match=match):
        _tap_approval(**overrides)


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"who": ApprovalGiver.USER_TAP_ON_HUB_PANEL}, id="a-tap"),
        pytest.param({"ends": ApprovalEnd.WHEN_USED_OR_EXPIRED}, id="an-expiry"),
    ],
)
def test_a_yes_to_a_question_keeps_its_own_form(overrides: dict[str, Any]) -> None:
    """ADR-0321 §4:6 stands: a yes is given in a message and ends when used."""
    fields: dict[str, Any] = {
        "who": ApprovalGiver.USER_THROUGH_HUB_CHAT,
        "how": YesToQuestion(activation_id="act-ask", round="r1"),
        "covers": (QuestionPart(round="r1", part=1),),
        "given": ApprovalGiven(activation_id="act-yes", at=_AT),
        "ends": ApprovalEnd.WHEN_USED,
    }
    with pytest.raises(ValidationError, match="in a message"):
        Approval(**(fields | overrides))


def _decision(**overrides: Any) -> PermissionDecision:
    request = _call().request
    fields: dict[str, Any] = {"id": "d1", "decided_at": _AT, "effect": "e1"}
    fields.update(overrides)
    return PermissionDecision.from_request(
        request, PermissionRuling(outcome=PermissionOutcome.ALLOW, reason="ruled"), **fields
    )


def test_a_decision_under_a_ticket_names_the_taps_approval_and_no_part() -> None:
    """§5:4: the ticket's key is its request, which the approval's form names."""
    decision = _decision(approval=_tap_approval())

    assert decision.approved_part is None
    assert PermissionDecision.model_validate_json(decision.model_dump_json()) == decision
    with pytest.raises(ValidationError, match="no question part"):
        _decision(approval=_tap_approval(), approved_part=QuestionPart(round="r1", part=1))


# --- the effect record's keys (§2:9, §5:5) ----------------------------------------------


def _effect(**overrides: Any) -> ActivationEffect:
    fields: dict[str, Any] = {
        "id": "e1",
        "activation_id": "act-1",
        "round": "r1",
        "capability": "book_stay",
        "values_digest": "a" * 64,
        "decision_id": "d1",
        "claimed_at": _AT,
    }
    fields.update(overrides)
    return ActivationEffect(**fields)


def test_an_effect_carries_one_key_at_most() -> None:
    """§2:9, §5:5: a question part, a ticket or a request, and a message none."""
    assert _effect(ticket="q1").under_approval
    assert not _effect(request="q1").under_approval
    with pytest.raises(ValidationError, match="one key at most"):
        _effect(ticket="q1", request="q1")
    with pytest.raises(ValidationError, match="one key at most"):
        _effect(ticket="q1", part=QuestionPart(round="r1", part=1))
    with pytest.raises(ValidationError, match="message"):
        ActivationEffect(id="m1", activation_id="a", place="c-1", claimed_at=_AT, ticket="q1")


def test_an_effect_with_no_ticket_or_request_dumps_as_it_did() -> None:
    """A record of every other kind is stored exactly as it was before ADR-0361."""
    dumped = _effect().model_dump(mode="json")

    assert "ticket" not in dumped
    assert "request" not in dumped
    assert _effect(ticket="q1").model_dump(mode="json")["ticket"] == "q1"


# --- the confirmation's request form (§5:10) ---------------------------------------------


def test_a_confirmation_support_names_a_question_part_or_a_request() -> None:
    """§5:10: the request form names the work that ran the ticket beside it."""
    asked = ConfirmationPart(
        episode="activation:act-yes",
        asking_activation="act-ask",
        question=QuestionPart(round="r1", part=1),
    )
    tapped = ConfirmationPart(
        episode="activation:act-approval",
        asking_activation="act-ask",
        request="q1",
        ran_in="act-ask",
    )

    # The question form serialises exactly as it did, so every digest over it holds.
    assert set(asked.model_dump(mode="json")) == {
        "part",
        "episode",
        "asking_activation",
        "question",
    }
    assert ConfirmationPart.model_validate_json(tapped.model_dump_json()) == tapped
    for fields in (
        {"question": QuestionPart(round="r1", part=1), "request": "q1", "ran_in": "a"},
        {},
        {"request": "q1"},
        {"question": QuestionPart(round="r1", part=1), "ran_in": "a"},
    ):
        with pytest.raises(ValidationError):
            ConfirmationPart(episode="e", asking_activation="act-ask", **fields)


def test_a_user_confirmation_answers_one_question_part_or_one_request() -> None:
    """§5:10, §8:1: the authority a card-approved remember carries names its request."""
    common: dict[str, Any] = {"question_key": "b" * 64, "confirmed_at": _AT}

    assert UserConfirmation(request="q1", **common).question is None
    with pytest.raises(ValidationError, match="one question part or one approval request"):
        UserConfirmation(**common)
    with pytest.raises(ValidationError, match="one question part or one approval request"):
        UserConfirmation(request="q1", question=QuestionPart(round="r1", part=1), **common)


# --- the export (§8:2) -------------------------------------------------------------------


def test_an_export_holds_each_request_and_each_token_once() -> None:
    carded = _request(cards=(_card("t1"),))

    assert PlanExport(exported_at=_AT, approval_requests=(carded,)).approval_requests == (carded,)
    with pytest.raises(ValidationError, match="duplicate approval request"):
        PlanExport(exported_at=_AT, approval_requests=(_request(), _request()))
    with pytest.raises(ValidationError, match="one card token"):
        PlanExport(
            exported_at=_AT, approval_requests=(carded, carded.model_copy(update={"id": "q2"}))
        )


# --- the register entry (§3:6) -----------------------------------------------------------


def test_the_approvals_input_carries_no_ones_words_and_establishes_no_one() -> None:
    """§3:6, ADR-0351 §2:4: its parties are empty, and no author is the user there."""
    parties, messages = declared_input(_APPROVALS)

    assert (parties, messages) == ((), ())
    assert not establishes_the_user(APPROVALS)
    with pytest.raises(ValueError, match="mark"):
        declared_input(_APPROVALS, carries_outside_mark=True)
