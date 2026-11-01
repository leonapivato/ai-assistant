"""The yes path's `core` shapes (ADR-0321 §2, §3, §4, §9).

A round's asked calls and its naming of them, the answer pointer in both of
understanding's forms, the approved-action label, the approval with its five slots, the
decision that names it, the effect record's part key, and the confirmation that names
the question it answers. Each test pins a shape a consumer lane builds against, or a
refusal that keeps a record from saying something the yes path could not have meant.
"""

from __future__ import annotations

import inspect
import json
from datetime import UTC, datetime
from typing import Any, Final

import pytest
from pydantic import BaseModel, ValidationError

from ai_assistant.core import types as core_types
from ai_assistant.core.types import (
    ActionRequest,
    ActivationEffect,
    ActivationEffectClaim,
    AnsweredQuestion,
    Approval,
    ApprovalEnd,
    ApprovalGiven,
    ApprovalGiver,
    AskedCall,
    BoundAccount,
    CostBasis,
    DataTier,
    DestinationProtocol,
    DiscloserProvenance,
    EgressBinding,
    EgressDestination,
    EgressSpan,
    EpisodeProcessingRecord,
    EpisodicMemory,
    Idempotency,
    LabelKind,
    MemoryUpdateProposal,
    PermissionDecision,
    PermissionOutcome,
    PermissionRuling,
    PlanningLabel,
    PlanningRound,
    QuestionPart,
    Reversibility,
    RiskLevel,
    RoundResponse,
    SpanCoverage,
    ToolCost,
    ToolDefinition,
    UserConfirmation,
    YesToQuestion,
    label_prefix,
)
from ai_assistant.testing import with_phase_declaration
from ai_assistant.testing.memories import memory, remembered_support

_AT: Final = datetime(2026, 10, 15, 14, 15, tzinfo=UTC)
_RECIPIENT: Final = "sam@example.com"
_PART: Final = QuestionPart(round="q-round", part=1)

#: The models of ``core.types`` that were incomplete on ``main`` before the asked call,
#: each waiting on a declaration further down. The asked call's forward reference may
#: leave none of its own behind.
_INCOMPLETE_BEFORE: Final = frozenset({"BoundAccount", "CanonicalDestination", "PlanExport"})


def _tool(**overrides: object) -> ToolDefinition:
    """A send in the world, not safe to repeat, its outcome possibly unknown."""
    fields: dict[str, object] = {
        "id": "smtp",
        "capability": "send_email",
        "description": "Send an email.",
        "risk_level": RiskLevel.HIGH,
        "reversibility": Reversibility.IRREVERSIBLE,
        "side_effecting": True,
        "reads": (DataTier.PERSONAL,),
        "writes": (),
        "discloses": (DataTier.PERSONAL,),
        "cost": ToolCost(basis=CostBasis.FREE),
        "idempotency": Idempotency.NONE,
        "parameters_schema": {
            "type": "object",
            "properties": {"to": {"type": "string"}, "body": {"type": "string"}},
            "required": ["to", "body"],
        },
    }
    fields.update(overrides)
    return ToolDefinition(**with_phase_declaration(fields))  # type: ignore[arg-type]  # heterogeneous test kwargs


def _binding(*, recipient: str = _RECIPIENT) -> EgressBinding:
    """The binding a send to ``recipient`` is ruled on with."""
    local, _, domain = recipient.rpartition("@")
    return EgressBinding(
        spans=(
            EgressSpan(
                argument="body",
                provenance=DiscloserProvenance.SYSTEM_SELECTED,
                extent=len("running late"),
            ),
            EgressSpan(
                argument="to",
                provenance=DiscloserProvenance.USER_AUTHORED,
                extent=len(recipient),
                destination=EgressDestination(
                    protocol=DestinationProtocol.SMTP,
                    supplied=recipient,
                    canonical=f"{local}@{domain.lower()}",
                ),
            ),
        ),
        account=BoundAccount(identity="my mail", reference="connection-1"),
        transport_endpoint="smtp://mail.example.com:587",
        planned_with_external_content=False,
        coverage=SpanCoverage.NOT_COVERED,
    )


def _values(**overrides: Any) -> dict[str, Any]:
    return {"to": _RECIPIENT, "body": "running late", **overrides}


def _asked(part: int = 1, **overrides: Any) -> AskedCall:
    fields: dict[str, Any] = {
        "part": part,
        "tool": _tool(),
        "values": _values(),
        "binding": _binding(),
    }
    fields.update(overrides)
    return AskedCall(**fields)


def _approval(**overrides: Any) -> Approval:
    fields: dict[str, Any] = {
        "who": ApprovalGiver.USER_THROUGH_HUB_CHAT,
        "how": YesToQuestion(activation_id="act-asked", round="q-round"),
        "covers": (_PART,),
        "given": ApprovalGiven(activation_id="act-yes", at=_AT),
        "ends": ApprovalEnd.WHEN_USED,
    }
    fields.update(overrides)
    return Approval(**fields)


def _decision(outcome: PermissionOutcome, **overrides: Any) -> PermissionDecision:
    request = _asked().request
    fields: dict[str, Any] = {"id": "d1", "decided_at": _AT}
    fields.update(overrides)
    return PermissionDecision.from_request(
        request, PermissionRuling(outcome=outcome, reason="ruled"), **fields
    )


# --- the asked call and the round that records it (§2:6, §2:8) -----------------------


def test_an_asked_call_is_the_request_it_records() -> None:
    """§2:8: part, tool, values, binding and mark; ``request`` is the call as ruled on."""
    asked = _asked()

    assert asked.request == ActionRequest(
        tool=_tool(), parameters=_values(), egress_binding=_binding()
    )
    assert asked.deliberate_repeat is False
    assert asked.replaces == ()


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"values": {"to": _RECIPIENT}}, id="values-the-schema-refuses"),
        pytest.param({"values": _values(cc="x")}, id="an-argument-the-binding-does-not-describe"),
        pytest.param({"binding": _binding(recipient="kim@example.com")}, id="another-recipient"),
    ],
)
def test_an_asked_call_that_could_not_be_ruled_on_is_refused(overrides: dict[str, Any]) -> None:
    """§2:8: what the user is shown is a call that could be ruled on and run."""
    with pytest.raises(ValidationError, match="make a request its declaration admits"):
        _asked(**overrides)


def test_an_asked_calls_refusal_renders_none_of_its_values() -> None:
    """ADR-0145 §8: an asked call's values are Tier 1 and stay out of its errors."""
    with pytest.raises(ValidationError) as caught:
        _asked(values={"to": "secret-recipient@example.com"})

    assert "secret-recipient" not in str(caught.value)


def test_a_round_and_what_holds_it_render_none_of_an_asked_calls_values() -> None:
    """ADR-0145 §8: pydantic renders an error by the model validated, so the round, the
    processing record holding it and the episode holding that hide their input too."""
    asked = {"part": 1, "tool": _tool().model_dump(), "values": {"to": "kept@secret.example"}}
    round_ = {"id": "q-round", "recorded_at": _AT.isoformat(), "asked": [asked]}
    record = {
        "activation_id": "act-1",
        "started_at": _AT.isoformat(),
        "trigger": {"never": "read"},
        "rounds": [round_],
    }
    episode = {"id": "ep-1", "occurred_at": _AT.isoformat(), "processing_record": record}

    for model, data in (
        (PlanningRound, round_),
        (EpisodeProcessingRecord, record),
        (EpisodicMemory, episode),
    ):
        with pytest.raises(ValidationError) as caught:
            model.model_validate(data)
        assert "kept@secret.example" not in str(caught.value), model.__name__


def test_only_a_call_not_safe_to_repeat_is_a_deliberate_repeat() -> None:
    """ADR-0306 §2:9: the mark is offered only where a capability is not safe to repeat."""
    assert _asked(deliberate_repeat=True).deliberate_repeat is True
    with pytest.raises(ValidationError, match="deliberate repeat"):
        _asked(tool=_tool(safe_to_repeat=True), deliberate_repeat=True)


def test_an_asked_call_names_each_replaced_assertion_once() -> None:
    """§5:5: the ids a remember's question shows replaced, which a yes retires."""
    assert _asked(replaces=("m-1", "m-2")).replaces == ("m-1", "m-2")
    with pytest.raises(ValidationError, match="once"):
        _asked(replaces=("m-1", "m-1"))


def test_a_rounds_asked_calls_are_its_parts_one_to_n_in_order() -> None:
    """§2:6: each exact line is numbered, and its number is that call's part."""
    round_ = PlanningRound(id="q-round", recorded_at=_AT, text="May I?", asked=(_asked(1),))
    assert round_.asked[0].part == 1
    assert PlanningRound(id="r", recorded_at=_AT).asked == ()

    for parts in ((2,), (1, 1), (2, 1), (1, 3)):
        with pytest.raises(ValidationError, match="parts 1 to n"):
            PlanningRound(
                id="q-round",
                recorded_at=_AT,
                asked=tuple(_asked(part, values=_values()) for part in parts),
            )


def test_a_round_carrying_asked_calls_survives_its_json() -> None:
    """The episode record is stored and crosses the wire as JSON (ADR-0321 §9:2)."""
    round_ = PlanningRound(
        id="q-round",
        recorded_at=_AT,
        text="Shall I send it?",
        asked=(_asked(1), _asked(2, deliberate_repeat=True, replaces=("m-1",))),
    )

    dumped = round_.model_dump_json()

    assert PlanningRound.model_validate_json(dumped) == round_
    assert json.loads(dumped)["asked"][1]["part"] == 2


def test_no_model_is_left_incomplete_by_the_asked_calls_forward_reference() -> None:
    """The round names ``AskedCall`` forward; every model holding one is rebuilt whole."""
    incomplete = {
        name
        for name, value in vars(core_types).items()
        if inspect.isclass(value)
        and issubclass(value, BaseModel)
        and value.__module__ == core_types.__name__
        and not value.__pydantic_complete__
    }

    assert incomplete <= _INCOMPLETE_BEFORE
    for holder in (PlanningRound, EpisodeProcessingRecord, EpisodicMemory, MemoryUpdateProposal):
        assert holder.__pydantic_complete__, holder.__name__


# --- the naming (§2:3) ------------------------------------------------------------------


def test_a_response_no_longer_names_the_calls_its_message_asks_about() -> None:
    """ADR-0356 §7:5 replaces §2:3's naming: no part of a response carries it."""
    with pytest.raises(ValidationError, match="extra_forbidden"):
        RoundResponse.model_validate({"text": "May I?", "asks": ["R2"]})


# --- the answer pointer (§3:1) ----------------------------------------------------------


@pytest.mark.parametrize(
    "named",
    [
        pytest.param({"round": "q-round"}, id="by-round"),
        pytest.param({"place": "conv-1", "position": 7}, id="by-place-and-position"),
        pytest.param({"round": "q-round", "place": "conv-1", "position": 7}, id="by-both"),
    ],
)
def test_a_recorded_answer_names_its_message_by_ids(named: dict[str, Any]) -> None:
    """§3:1, ADR-0276 §2:4: the question's message by the records that keep it, no label."""
    pointer = AnsweredQuestion(activation_id="act-asked", parts=(1, 2), **named)

    assert AnsweredQuestion.model_validate_json(pointer.model_dump_json()) == pointer


@pytest.mark.parametrize(
    ("named", "match"),
    [
        pytest.param({}, "round, its place and position", id="names-no-message"),
        pytest.param({"place": "conv-1"}, "together", id="a-place-without-a-position"),
        pytest.param({"round": "r", "position": 7}, "together", id="a-position-without-a-place"),
        pytest.param({"round": "r", "parts": (2, 1)}, "ascending", id="parts-out-of-order"),
        pytest.param({"round": "r", "parts": (1, 1)}, "once", id="a-part-twice"),
    ],
)
def test_a_recorded_answer_that_names_no_one_message_is_refused(
    named: dict[str, Any], match: str
) -> None:
    """§3:1: the pointer names exactly one message and each part once."""
    with pytest.raises(ValidationError, match=match):
        AnsweredQuestion(activation_id="act-asked", **named)


# --- the approved-action label (§4:2) ---------------------------------------------------


def test_the_approved_action_label_is_its_own_kind_with_its_own_prefix() -> None:
    """§4:2: planning is shown each approved action under a label of a new kind."""
    assert label_prefix(LabelKind.APPROVED_ACTION) == "A"
    assert PlanningLabel(label="A1", kind=LabelKind.APPROVED_ACTION, id="q-round:1").label == "A1"
    with pytest.raises(ValidationError):
        PlanningLabel(label="R1", kind=LabelKind.APPROVED_ACTION, id="q-round:1")
    with pytest.raises(ValidationError):
        PlanningLabel(label="A1", kind=LabelKind.RESULT, id="result:1")
    assert len({label_prefix(kind) for kind in LabelKind}) == len(LabelKind)


# --- the approval (§4:6) ----------------------------------------------------------------


def test_an_approval_has_the_five_slots() -> None:
    """§4:6: who, how, covers, given and ends, and nothing else."""
    approval = _approval()

    assert set(Approval.model_fields) == {"who", "how", "covers", "given", "ends"}
    assert approval.how.kind == "yes_to_a_question"
    assert Approval.model_validate_json(approval.model_dump_json()) == approval


@pytest.mark.parametrize(
    ("overrides", "match"),
    [
        pytest.param({"covers": ()}, "at least one part", id="covers-nothing"),
        pytest.param({"covers": (_PART, _PART)}, "once", id="a-part-twice"),
        pytest.param(
            {"covers": (QuestionPart(round="q-other", part=1),)},
            "the question its yes answered",
            id="another-questions-part",
        ),
        pytest.param(
            {"given": ApprovalGiven(activation_id="act-asked", at=_AT)},
            "never the one that asked",
            id="given-where-it-was-asked",
        ),
    ],
)
def test_an_approval_covers_parts_of_its_own_question_alone(
    overrides: dict[str, Any], match: str
) -> None:
    """§4:6: *covers* is exactly the calls of the approved parts of the one question."""
    with pytest.raises(ValidationError, match=match):
        _approval(**overrides)


# --- the decision that names it (§4:8) --------------------------------------------------


@pytest.mark.parametrize("outcome", [PermissionOutcome.ALLOW, PermissionOutcome.CONFIRM])
def test_a_decision_names_its_approval_and_the_part_it_runs_under(
    outcome: PermissionOutcome,
) -> None:
    """§4:8: recorder-supplied through ``from_request``, as ``effect`` is."""
    decision = _decision(outcome, effect="e1", approval=_approval(), approved_part=_PART)

    assert decision.approval == _approval()
    assert decision.approved_part == _PART
    assert PermissionDecision.model_validate_json(decision.model_dump_json()) == decision
    assert _decision(outcome).approval is None


def test_a_decision_about_a_call_under_no_approval_names_none() -> None:
    """§9: ``None`` on a decision about a call that does not run under one."""
    decision = _decision(PermissionOutcome.ALLOW)
    assert (decision.approval, decision.approved_part) == (None, None)


@pytest.mark.parametrize(
    ("outcome", "fields", "match"),
    [
        pytest.param(
            PermissionOutcome.ALLOW,
            {"effect": "e1", "approval": _approval()},
            "together",
            id="an-approval-without-its-part",
        ),
        pytest.param(
            PermissionOutcome.ALLOW,
            {"effect": "e1", "approved_part": _PART},
            "together",
            id="a-part-without-its-approval",
        ),
        pytest.param(
            PermissionOutcome.ALLOW,
            {
                "effect": "e1",
                "approval": _approval(),
                "approved_part": QuestionPart(round="q-round", part=2),
            },
            "covers",
            id="a-part-the-approval-does-not-cover",
        ),
        pytest.param(
            PermissionOutcome.DENY,
            {"effect": "e1", "approval": _approval(), "approved_part": _PART},
            "never overrides a deny",
            id="a-deny",
        ),
        pytest.param(
            PermissionOutcome.ALLOW,
            {"approval": _approval(), "approved_part": _PART},
            "effect record",
            id="an-allow-naming-no-effect-record",
        ),
    ],
)
def test_a_decision_naming_an_approval_it_could_not_run_under_is_refused(
    outcome: PermissionOutcome, fields: dict[str, Any], match: str
) -> None:
    """§4:3, §4:9, §4:10, §4:12: the approval rides only where the call can run under it."""
    with pytest.raises(ValidationError, match=match):
        _decision(outcome, **fields)


def test_the_approval_does_not_change_what_a_decision_authorises() -> None:
    """``authorises`` compares the subject alone; the approval names why it may run."""
    request = _asked().request
    decision = _decision(
        PermissionOutcome.ALLOW, effect="e1", approval=_approval(), approved_part=_PART
    )
    assert decision.authorises(request)


# --- the spend's key on the effect record (§4:9) ----------------------------------------


def test_a_call_effect_carries_the_part_it_spends_and_a_message_none() -> None:
    """§4:9: the part key rides on a call's record; a message spends no part."""
    call = ActivationEffect(
        id="e1",
        activation_id="act-yes",
        round="r1",
        capability="send_email",
        values_digest="a" * 64,
        decision_id="d1",
        claimed_at=_AT,
        part=_PART,
    )
    assert call.part == _PART
    assert ActivationEffect.model_validate_json(call.model_dump_json()) == call
    with pytest.raises(ValidationError, match="spends no question part"):
        ActivationEffect(id="m1", activation_id="a", place="conv-1", claimed_at=_AT, part=_PART)


def test_the_claim_answers_already_used_as_its_own_member() -> None:
    """§4:9: a spent part is told apart from the duplicate backstop's answer."""
    assert ActivationEffectClaim.ALREADY_USED.value == "already_used"
    assert len({member.value for member in ActivationEffectClaim}) == len(ActivationEffectClaim)


# --- the confirmation a remember's yes makes (§5:2, §9) ---------------------------------


def test_a_confirmation_names_the_question_part_it_answers() -> None:
    """§9: ``deferral_id`` gives way to the question it answers, its message and part."""
    proposal = MemoryUpdateProposal(
        proposed=memory("m-new", "Sam prefers email", remembered_support()),
        rationale="the user said so",
    )
    confirmation = UserConfirmation(
        question=_PART, question_key=proposal.question_key, confirmed_at=_AT, retires=("m-1",)
    )

    assert confirmation.question == _PART
    assert "deferral_id" not in UserConfirmation.model_fields
    with pytest.raises(ValidationError):
        UserConfirmation.model_validate(
            {"deferral_id": "d1", "question_key": proposal.question_key, "confirmed_at": _AT}
        )
