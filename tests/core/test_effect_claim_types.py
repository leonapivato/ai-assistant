"""ADR-0259's ``core`` surface holds what §§1-2 and §9 say it holds.

Arm 4's first half: ``EffectKey``'s construction and the shapes the claim reaches,
pinned here rather than in the shared conformance suite, because no implementation can
vary what a frozen `core` model refuses to be. The other half — ``claim_effect``'s
contract — is in ``tests/planning/plan_store_contract.py``, and therefore holds against
every implementation.

Most of these pin a **rejection**: an annotation cannot express a cross-field rule and a
comment beside a field does not enforce one, so each combination the annotations alone
would permit gets a case that it does not survive construction.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Final

import pytest
from pydantic import ValidationError

from ai_assistant.core.types import (
    ActionPlan,
    ActionRequest,
    BoundAccount,
    CanonicalDestination,
    CostBasis,
    DataTier,
    DestinationProtocol,
    DiscloserProvenance,
    Disposition,
    EffectClaim,
    EffectKey,
    EffectOutcome,
    EffectRecord,
    EgressBinding,
    EgressDestination,
    EgressSpan,
    EvidenceHistory,
    ExecutionState,
    Goal,
    GoalInterpretation,
    Ground,
    Idempotency,
    MemorySource,
    PermissionDecision,
    PermissionOutcome,
    PermissionRuling,
    PlanExport,
    PlanStep,
    Provenance,
    Reversibility,
    RiskLevel,
    SkipReason,
    SpanCoverage,
    StepExecution,
    StepFailure,
    StepStatus,
    StepTransition,
    ToolCall,
    ToolCost,
    ToolDefinition,
    TurnOutcome,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from ai_assistant.core.types import FrozenJson

_AT: Final = datetime(2026, 7, 20, 12, 0, tzinfo=UTC)
_DIGEST: Final = "a" * 64
_OTHER_DIGEST: Final = "b" * 64
_ACCOUNT: Final = BoundAccount(identity="work@example.com", reference="conn-0001")
_OTHER_ACCOUNT: Final = BoundAccount(identity="home@example.com", reference="conn-0002")
_ENDPOINT: Final = "smtp://mail.example.com:587"
_DESTINATION: Final = CanonicalDestination(
    protocol=DestinationProtocol.SMTP, canonical="a@example.com"
)
_TO: Final = "a@Example.com"
_PROVENANCE: Final = DiscloserProvenance.SYSTEM_SELECTED


def _tool(**overrides: Any) -> ToolDefinition:
    """A side-effecting declaration, with every field an arm may want to vary.

    ``idempotency_window`` follows ``idempotency`` unless an arm states one, because
    ``ToolDefinition`` requires it to be present and positive **iff** the declaration is
    ``KEYED`` — which is exactly the field ADR-0259 §1 says the key does not consult.
    """
    fields: dict[str, object] = {
        "id": "smtp",
        "capability": "send_email",
        "description": "Send an email.",
        "risk_level": RiskLevel.LOW,
        "reversibility": Reversibility.REVERSIBLE,
        "side_effecting": True,
        "reads": (),
        "writes": (),
        "discloses": (DataTier.PERSONAL,),
        "cost": ToolCost(basis=CostBasis.FREE),
        "idempotency": Idempotency.NATURAL,
        "parameters_schema": {"type": "object"},
    }
    fields.update(overrides)
    if fields["idempotency"] is Idempotency.KEYED:
        fields.setdefault("idempotency_window", timedelta(minutes=5))
    return ToolDefinition(**fields)  # type: ignore[arg-type]  # heterogeneous test kwargs


def _binding(**overrides: Any) -> EgressBinding:
    """A whole binding over one described recipient span."""
    fields: dict[str, object] = {
        "spans": (
            EgressSpan(
                argument="to",
                index=None,
                provenance=_PROVENANCE,
                extent=len(_TO),
                destination=EgressDestination(
                    protocol=DestinationProtocol.SMTP, supplied=_TO, canonical="a@example.com"
                ),
            ),
        ),
        "account": _ACCOUNT,
        "transport_endpoint": _ENDPOINT,
        "planned_with_external_content": False,
        "coverage": SpanCoverage.NOT_COVERED,
    }
    fields.update(overrides)
    return EgressBinding(**fields)  # type: ignore[arg-type]  # heterogeneous test kwargs


def _call(
    *,
    definition: ToolDefinition | None = None,
    parameters: Mapping[str, FrozenJson] | None = None,
    binding: EgressBinding | None = None,
) -> ToolCall:
    """An authorised call, built through the sanctioned path (ADR-0029 §2)."""
    request = ActionRequest(
        tool=definition or _tool(),
        parameters=parameters or {"to": _TO},
        step_id="s1",
        execution_id="e1",
        egress_binding=binding,
    )
    return ToolCall(
        request=request,
        decision=PermissionDecision.from_request(
            request,
            PermissionRuling(outcome=PermissionOutcome.ALLOW, reason="allowed"),
            id="d1",
            decided_at=_AT,
        ),
    )


# --- §1: the key admits two shapes and no mixture ----------------------------


@pytest.mark.parametrize(
    "fields",
    [
        pytest.param({}, id="unbound"),
        pytest.param(
            {
                "egress_account": _ACCOUNT,
                "egress_endpoint": _ENDPOINT,
                "egress_destinations": (_DESTINATION,),
            },
            id="bound",
        ),
    ],
)
def test_the_two_admissible_shapes_construct(fields: dict[str, Any]) -> None:
    """§1's validator admits exactly these: the control the refusals rest on."""
    assert EffectKey(tool_id="smtp", parameters_digest=_DIGEST, **fields)


@pytest.mark.parametrize(
    "fields",
    [
        pytest.param({"egress_endpoint": _ENDPOINT}, id="an-endpoint-without-an-account"),
        pytest.param({"egress_destinations": (_DESTINATION,)}, id="destinations-without-either"),
        pytest.param({"egress_account": _ACCOUNT}, id="an-account-alone"),
        pytest.param(
            {"egress_account": _ACCOUNT, "egress_endpoint": _ENDPOINT},
            id="an-account-and-endpoint-with-no-destination",
        ),
        pytest.param(
            {"egress_account": _ACCOUNT, "egress_destinations": (_DESTINATION,)},
            id="an-account-and-destinations-without-an-endpoint",
        ),
        pytest.param(
            {"egress_endpoint": _ENDPOINT, "egress_destinations": (_DESTINATION,)},
            id="an-endpoint-and-destinations-without-an-account",
        ),
    ],
)
def test_every_mixture_between_the_two_shapes_is_unconstructable(fields: dict[str, Any]) -> None:
    """§1: a partial projection cannot split one effect across two unequal rows.

    The non-empty limb is not a new rule — ``canonical_destination_set`` is documented
    as "therefore **never empty**" — so what the validator refuses is the shape that
    declaration already excludes.
    """
    with pytest.raises(ValidationError, match="either unbound"):
        EffectKey(tool_id="smtp", parameters_digest=_DIGEST, **fields)


def test_the_key_carries_no_sixth_field() -> None:
    """§1: no step, execution, plan, decision, goal, instant, attempt or action id.

    The last is the one worth a case of its own: the intended action is the row's
    *other half* and never a field of the key, because a key carrying it would make the
    Saturday and Sunday bookings unequal in the way two unrelated acts are unequal, and
    the revision would dispatch a second booking instead of meeting ``COMPLETED_OTHERWISE``.
    """
    assert set(EffectKey.model_fields) == {
        "tool_id",
        "parameters_digest",
        "egress_account",
        "egress_endpoint",
        "egress_destinations",
    }
    with pytest.raises(ValidationError, match="intended_action_id"):
        EffectKey(  # type: ignore[call-arg]  # the extra member under test
            tool_id="smtp", parameters_digest=_DIGEST, intended_action_id="ia1"
        )


@pytest.mark.parametrize(
    ("moved", "value"),
    [
        ("tool_id", "smtp-2"),
        ("parameters_digest", _OTHER_DIGEST),
        ("egress_account", _OTHER_ACCOUNT),
        ("egress_endpoint", "smtp://other.example.com:587"),
        (
            "egress_destinations",
            (CanonicalDestination(protocol=DestinationProtocol.SMTP, canonical="b@example.com"),),
        ),
    ],
)
def test_equality_moves_with_every_field_the_key_carries(moved: str, value: object) -> None:
    """§1: all five are part of the identity, and none is decorative."""
    bound = EffectKey(
        tool_id="smtp",
        parameters_digest=_DIGEST,
        egress_account=_ACCOUNT,
        egress_endpoint=_ENDPOINT,
        egress_destinations=(_DESTINATION,),
    )

    assert bound != bound.model_copy(update={moved: value})


# --- §1: the derived key, and what it is derived from -------------------------


@pytest.mark.parametrize("idempotency", list(Idempotency))
def test_a_side_effecting_tool_has_a_key_whatever_its_idempotency(
    idempotency: Idempotency,
) -> None:
    """§1: the ``None`` limb is ``side_effecting`` alone.

    Deliberately **not** ``interrupted_outcome``'s two-limb test, which exempts
    ``NATURAL`` because a repeat of one is harmless: this asks whether an effect exists
    to be claimed at all, and ADR-0255 §7's requirement is stated over **dispatch**.
    """
    key = _call(definition=_tool(idempotency=idempotency)).effect_key

    assert key is not None
    assert key.tool_id == "smtp"


def test_a_tool_that_is_not_side_effecting_has_no_key() -> None:
    """§1's if-and-only-if, from the other side: such a call reaches the store never."""
    assert _call(definition=_tool(side_effecting=False, discloses=())).effect_key is None


def test_the_key_is_built_from_the_binding_where_the_decision_carries_one() -> None:
    """§1: the three facts that describe **where the effect goes**, and no more."""
    call = _call(binding=_binding())
    key = call.effect_key

    assert key is not None
    assert key.egress_account == _ACCOUNT
    assert key.egress_endpoint == _ENDPOINT
    assert key.egress_destinations == call.decision.egress_binding.canonical_destination_set  # type: ignore[union-attr]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("planned_with_external_content", True),
        ("coverage", SpanCoverage.MODEL_ON_EVERY_PATH),
        ("closed_loop", True),
    ],
)
def test_the_key_is_unchanged_by_the_bindings_provenance_fields(field: str, value: object) -> None:
    """§1: two replans differing only in how the call was reasoned about are one effect.

    Were these in the key they would mint a second one and **dispatch the same effect
    twice**, which is the failure the section exists to stop.
    """
    first = _call(binding=_binding()).effect_key
    second = _call(binding=_binding(**{field: value})).effect_key

    assert first == second


def test_the_key_is_unchanged_across_two_span_decompositions_that_canonicalise_alike() -> None:
    """§1: ``spans`` is excluded because the destination set is its canonicalisation.

    ADR-0150 §9 names that set as a thing ``authorises`` deliberately does *not*
    compare, "precisely because two different decompositions can canonicalise to one
    destination set" — and for effect identity that is the property wanted.
    """
    supplied = "a@EXAMPLE.com"
    other = _binding(
        spans=(
            EgressSpan(
                argument="to",
                index=None,
                provenance=_PROVENANCE,
                extent=len(supplied),
                destination=EgressDestination(
                    protocol=DestinationProtocol.SMTP, supplied=supplied, canonical="a@example.com"
                ),
            ),
        )
    )

    first = _call(binding=_binding()).effect_key
    second = _call(parameters={"to": supplied}, binding=other).effect_key

    assert first is not None
    assert second is not None
    assert first.egress_destinations == second.egress_destinations
    assert first.parameters_digest != second.parameters_digest, (
        "two spellings of one recipient are two digests, which §1 states as the cost"
    )


def test_the_key_is_unchanged_across_two_definitions_that_share_an_id() -> None:
    """§1's third narrowing, asserted deliberately rather than left to be discovered.

    A definition carries a description, a schema, a risk level and declarations a
    deployment can revise **without changing what the call does**, and a key over the
    whole definition would mint a fresh one on every such revision and dispatch the
    effect twice. A later lane that widened the key fails this row rather than silently
    double-dispatching on a harmless re-registration.
    """
    revised = _tool(
        description="Send an email, revised.",
        risk_level=RiskLevel.CRITICAL,
        reversibility=Reversibility.IRREVERSIBLE,
        discloses=(DataTier.PERSONAL, DataTier.OPERATIONAL),
        idempotency=Idempotency.NONE,
        cost=ToolCost(basis=CostBasis.UNKNOWN),
    )

    assert _call().effect_key == _call(definition=revised).effect_key


def test_the_key_reads_the_decision_and_not_the_mutable_request() -> None:
    """§1: ADR-0018 §3's post-construction mutation is inside the threat model.

    A key derived from the mutable half could be persisted for one effect while another
    was invoked, so the mutation of ``request`` moves nothing and the same mutation of
    the **decision** — the copy the trail holds — moves the key, which is what shows
    the property is the derivation's rather than an accident of equal values.
    """
    call = _call()
    before = call.effect_key

    call.__dict__["request"] = ActionRequest(
        tool=_tool(id="other"), parameters={"to": "z@example.com"}, step_id="s1", execution_id="e1"
    )
    assert call.effect_key == before, "the request is not what the key is read from"

    call.__dict__["decision"] = call.decision.model_copy(
        update={"parameters_digest": _OTHER_DIGEST}
    )
    assert call.effect_key != before, "and the decision is"


def test_the_effect_key_is_a_plain_property_and_not_a_computed_field() -> None:
    """§9: a computed field enters ``model_dump()``, and ADR-0018 §4's rebuild runs
    against ``extra="forbid"`` — ``idempotency_key``'s own recorded reason."""
    # Read through ``getattr`` for the reason ``test_engine_surface_closure`` does: a
    # direct class-level access is typed as the property's *return*, so the narrowing
    # would make everything after it unreachable rather than checked.
    assert isinstance(getattr(ToolCall, "effect_key"), property)  # noqa: B009 — see above
    assert "effect_key" not in ToolCall.model_computed_fields
    assert "effect_key" not in ToolCall.model_fields
    assert "effect_key" not in _call().model_dump()


def test_the_two_keys_are_two_values_and_neither_is_computed_from_the_other() -> None:
    """§1: the tool-facing key is "distinct for a distinct intent"; this one is not.

    ``idempotency_key`` is ``decision.id`` for a ``KEYED`` tool and ``None`` otherwise
    (ADR-0029 §5); ``effect_key`` has the opposite property, **identical across two
    authorisations of the same concrete call**, which is what lets a later plan's step
    be recognised as the earlier plan's effect.
    """
    first = _call(definition=_tool(idempotency=Idempotency.KEYED))
    second = ToolCall(
        request=first.request,
        decision=PermissionDecision.from_request(
            first.request,
            PermissionRuling(outcome=PermissionOutcome.ALLOW, reason="allowed again"),
            id="d2",
            decided_at=_AT,
        ),
    )

    assert first.idempotency_key != second.idempotency_key, "two intents, two tool-facing keys"
    assert first.effect_key == second.effect_key, "one concrete call, one goal-facing key"


# --- §2: the answer carries the holder where the caller must act on it --------


@pytest.mark.parametrize(
    "ids",
    [
        pytest.param({"execution_id": "e1"}, id="the-execution-alone"),
        pytest.param({"step_id": "s1"}, id="the-step-alone"),
        pytest.param({}, id="neither"),
    ],
)
def test_a_completed_answer_names_its_whole_holder(ids: dict[str, str]) -> None:
    """§2's if-and-only-if, refusing every partial pair on ``COMPLETED``.

    A satisfaction reads the holder from this value, so an answer carrying one id and
    not the other would be a holder no caller could resolve.
    """
    assert EffectOutcome(claim=EffectClaim.COMPLETED, execution_id="e1", step_id="s1")
    with pytest.raises(ValidationError, match="names its holder"):
        EffectOutcome(claim=EffectClaim.COMPLETED, **ids)


@pytest.mark.parametrize(
    "claim",
    [
        EffectClaim.CLAIMED,
        EffectClaim.COMPLETED_OTHERWISE,
        EffectClaim.UNCERTAIN,
        EffectClaim.HELD,
    ],
)
@pytest.mark.parametrize(
    "ids",
    [
        pytest.param({"execution_id": "e1", "step_id": "s1"}, id="both"),
        pytest.param({"execution_id": "e1"}, id="the-execution-alone"),
        pytest.param({"step_id": "s1"}, id="the-step-alone"),
    ],
)
def test_no_other_answer_carries_a_holder(claim: EffectClaim, ids: dict[str, str]) -> None:
    """§2: a caller that cannot act on the holder is not handed one.

    ``COMPLETED_OTHERWISE`` is deliberately among them: the modify-before-replace
    investigation that consumes it needs the earlier act's *arguments* and not only its
    ids, which is a bounded lookup A8's second decision must add and argue for.
    """
    assert EffectOutcome(claim=claim).execution_id is None
    with pytest.raises(ValidationError, match="carries no holder"):
        EffectOutcome(claim=claim, **ids)


def test_the_claim_vocabulary_is_closed_at_five_members() -> None:
    """§2: five members, valued by the lower-cased member name, added to and never renamed."""
    assert {member.name: member.value for member in EffectClaim} == {
        "CLAIMED": "claimed",
        "COMPLETED": "completed",
        "COMPLETED_OTHERWISE": "completed_otherwise",
        "UNCERTAIN": "uncertain",
        "HELD": "held",
    }


def test_the_disposition_gains_exactly_two_members_with_the_values_the_adr_fixes() -> None:
    """§2, §9: two members and not one, because they are two different facts.

    *This goal has already claimed this act* against *this plan cannot say which act
    this step is* — a client that could not tell them apart could not tell a user which
    of the two it was, and the second is a defect in the plan while the first is not.
    """
    assert Disposition.EFFECT_ALREADY_CLAIMED.value == "effect_already_claimed"
    assert Disposition.EFFECT_UNSCOPED.value == "effect_unscoped"


def test_the_effect_record_carries_exactly_seven_fields() -> None:
    """§9's enumeration, and ``extra="forbid"`` on top of it."""
    assert set(EffectRecord.model_fields) == {
        "goal_id",
        "intended_action_id",
        "key",
        "execution_id",
        "step_id",
        "targets_revision",
        "claimed_at",
    }


def test_the_effect_records_revision_is_constrained_to_a_real_one() -> None:
    """§9: ``targets_revision`` carries ``ActionPlan``'s annotation **less its** ``None``.

    A plan whose stamp is absent is one ``save_plan`` refuses, so a claiming plan always
    carries one and the field needs no absent case — which is what makes the constraint
    a fact about the row rather than a hope about its writer.
    """
    with pytest.raises(ValidationError):
        _record(targets_revision=0)
    assert _record(targets_revision=1).targets_revision == 1


def _record(**overrides: Any) -> EffectRecord:
    """One effect row, with every field an arm may want to vary."""
    fields: dict[str, object] = {
        "goal_id": "g1",
        "intended_action_id": "ia1",
        "key": EffectKey(tool_id="smtp", parameters_digest=_DIGEST),
        "execution_id": "x1",
        "step_id": "s1",
        "targets_revision": 1,
        "claimed_at": _AT,
    }
    fields.update(overrides)
    return EffectRecord(**fields)  # type: ignore[arg-type]  # heterogeneous test kwargs


# --- §9: the satisfaction trio, and what it may ride on ----------------------


def _transition(**overrides: Any) -> StepTransition:
    """A ``→ SUCCEEDED`` move carrying the trio, with the fields an arm varies."""
    fields: dict[str, object] = {
        "execution_id": "x2",
        "step_id": "s1",
        "to_status": StepStatus.SUCCEEDED,
        "expected_version": 0,
        "satisfied_by_execution": "x1",
        "satisfied_by_step": "s1",
        "satisfied_by_key": EffectKey(tool_id="smtp", parameters_digest=_DIGEST),
    }
    fields.update(overrides)
    return StepTransition(**fields)  # type: ignore[arg-type]  # heterogeneous test kwargs


@pytest.mark.parametrize(
    "dropped",
    ["satisfied_by_execution", "satisfied_by_step", "satisfied_by_key"],
)
def test_a_partial_satisfaction_trio_is_unconstructable(dropped: str) -> None:
    """§9: ADR-0255 §11's constructor limb for ``attempt_id``, applied to a trio."""
    with pytest.raises(ValidationError, match="together or none of them"):
        _transition(**{dropped: None})


@pytest.mark.parametrize(
    "to_status",
    [
        StepStatus.RUNNING,
        StepStatus.AWAITING_APPROVAL,
        StepStatus.FAILED,
        StepStatus.SKIPPED,
        StepStatus.INDETERMINATE,
    ],
)
def test_the_trio_rides_no_transition_but_a_success(to_status: StepStatus) -> None:
    """§9: a mark on any other target status claims a completion the move does not make."""
    extra: dict[str, object] = {"to_status": to_status}
    if to_status is StepStatus.RUNNING:
        extra |= {"attempt_id": "a1"}
    if to_status is StepStatus.SKIPPED:
        extra |= {"skip_reason": SkipReason.SUPERSEDED}
    if to_status in {StepStatus.FAILED, StepStatus.INDETERMINATE}:
        extra |= {"failure": StepFailure(message="boom")}

    with pytest.raises(ValidationError, match="satisfied by an earlier effect"):
        _transition(**extra)


def test_a_satisfaction_carries_no_output_because_the_store_writes_it() -> None:
    """§9: "a value the caller never supplies cannot be mis-stated".

    The store copies ``output`` from the holder row it has just verified and stamps
    ``finished_at`` from its own clock, so a transition asserting what the borrowed act
    returned is refused at construction rather than trusted at the write.
    """
    with pytest.raises(ValidationError, match="carries no output"):
        _transition(output={"reference": "BK-1"})


def test_a_plain_success_still_carries_its_own_output() -> None:
    """The control: the refusal above is about the trio and reaches nothing else."""
    assert StepTransition(
        execution_id="x2",
        step_id="s1",
        to_status=StepStatus.SUCCEEDED,
        expected_version=0,
        output={"reference": "BK-1"},
    ).output == {"reference": "BK-1"}


# --- §2: what a satisfied step's record looks like ----------------------------


def test_a_satisfied_step_records_no_execution_mark() -> None:
    """§2: nothing ran under it, so the four claim marks are not required.

    ``approval_ref`` and ``started_at`` stay ``None`` and ``attempts`` stays 0, and
    ``bound_tool`` is neither required nor cleared — ADR-0014 §3 makes it "which tool
    the **selection stage** chose" and not a claim mark.
    """
    step = StepExecution(
        step_id="s1",
        status=StepStatus.SUCCEEDED,
        output={"reference": "BK-1"},
        finished_at=_AT,
        satisfied_by_execution="x1",
        satisfied_by_step="s0",
    )

    assert (step.attempts, step.started_at, step.approval_ref, step.bound_tool) == (
        0,
        None,
        None,
        None,
    )


@pytest.mark.parametrize(
    "mark",
    [
        pytest.param({"approval_ref": "d1"}, id="an-approval-ref"),
        pytest.param({"started_at": _AT}, id="a-started-at"),
        pytest.param({"attempts": 1}, id="an-attempt"),
    ],
)
def test_a_satisfied_step_refuses_the_marks_of_a_run(mark: dict[str, Any]) -> None:
    """§2: a claim mark beside a satisfaction would say the step both ran and did not."""
    with pytest.raises(ValidationError, match="did not run"):
        StepExecution(
            step_id="s1",
            status=StepStatus.SUCCEEDED,
            output={"reference": "BK-1"},
            finished_at=_AT,
            satisfied_by_execution="x1",
            satisfied_by_step="s0",
            **mark,
        )


def test_a_succeeded_step_carrying_neither_mark_still_requires_all_four() -> None:
    """§2: "a ``SUCCEEDED`` step carrying neither new field is unchanged"."""
    with pytest.raises(ValidationError, match="requires approval_ref"):
        StepExecution(step_id="s1", status=StepStatus.SUCCEEDED, finished_at=_AT)


@pytest.mark.parametrize("dropped", ["satisfied_by_execution", "satisfied_by_step"])
def test_a_satisfied_step_names_both_halves_of_its_holder(dropped: str) -> None:
    """§2: a step naming one half names a holder nothing can resolve."""
    marks: dict[str, Any] = {"satisfied_by_execution": "x1", "satisfied_by_step": "s0"}
    marks[dropped] = None

    with pytest.raises(ValidationError, match="names both"):
        StepExecution(
            step_id="s1",
            status=StepStatus.SUCCEEDED,
            output={"reference": "BK-1"},
            finished_at=_AT,
            **marks,
        )


@pytest.mark.parametrize(
    "status", [StepStatus.PENDING, StepStatus.SKIPPED, StepStatus.FAILED, StepStatus.RUNNING]
)
def test_only_a_succeeded_step_can_have_been_satisfied(status: StepStatus) -> None:
    """§2: the marks are reachable by one route, and it ends at ``SUCCEEDED``."""
    with pytest.raises(ValidationError):
        StepExecution(
            step_id="s1",
            status=status,
            satisfied_by_execution="x1",
            satisfied_by_step="s0",
        )


# --- §2: the turn says so, once per satisfied step ---------------------------


def test_the_turn_reports_nothing_as_none_and_never_as_an_empty_tuple() -> None:
    """§2: two spellings of one fact let an implementation and a client disagree."""
    assert TurnOutcome(turn=None).satisfied_from_earlier is None
    assert TurnOutcome(turn=None, satisfied_from_earlier=("s1", "s2")).satisfied_from_earlier == (
        "s1",
        "s2",
    )
    with pytest.raises(ValidationError, match="never empty"):
        TurnOutcome(turn=None, satisfied_from_earlier=())


# --- §9: the export closure, stated over one holder ---------------------------


def _goal(goal_id: str = "g1") -> Goal:
    """A goal at revision 1, the shape every plan below targets."""
    return Goal(
        id=goal_id,
        conversation_id="c1",
        interpretation=(
            GoalInterpretation(
                revision=1,
                outcome="book a room",
                outcome_ground=Ground.USER_STATED,
                recorded_at=_AT,
            ),
        ),
        provenance=Provenance(source=MemorySource.USER_ASSERTED, confidence=1.0, last_updated=_AT),
        created_at=_AT,
    )


def _plan(plan_id: str, goal_id: str = "g1") -> ActionPlan:
    """A one-step plan of ``goal_id``."""
    return ActionPlan(
        id=plan_id,
        goal_id=goal_id,
        steps=(PlanStep(id="s1", intent="book a room", capability="book_room"),),
        created_at=_AT,
        targets_revision=1,
    )


def _execution(
    execution_id: str, plan_id: str, step: StepExecution | None = None
) -> ExecutionState:
    """An execution of ``plan_id`` carrying ``step``, or a bare ``PENDING`` one."""
    return ExecutionState(
        id=execution_id,
        plan_id=plan_id,
        steps=(step or StepExecution(step_id="s1"),),
        updated_at=_AT,
    )


def _export(**overrides: Any) -> PlanExport:
    """A closed document: one goal, two plans, two executions.

    ADR-0252 §13 requires exactly one evidence history per goal the document carries, so
    an empty one is supplied for each goal rather than left out — a true answer and not
    an omission, and the arms below are about a different closure entirely.
    """
    fields: dict[str, object] = {
        "exported_at": _AT,
        "goals": (_goal(),),
        "plans": (_plan("p1"), _plan("p2")),
        "executions": (_execution("x1", "p1"), _execution("x2", "p2")),
    }
    fields.update(overrides)
    goals: tuple[Goal, ...] = fields["goals"]  # type: ignore[assignment]  # this helper's own value
    fields.setdefault("evidence", tuple(EvidenceHistory(goal_id=goal.id) for goal in goals))
    return PlanExport(**fields)  # type: ignore[arg-type]  # heterogeneous test kwargs


def test_an_effect_row_whose_holder_resolves_exports() -> None:
    """The control: §9's closure is satisfied by a row naming a step of a stored execution."""
    assert _export(effects=(_record(execution_id="x1", step_id="s1"),)).effects


@pytest.mark.parametrize(
    ("overrides", "match"),
    [
        pytest.param({"execution_id": "gone"}, "holder is missing", id="a-dangling-execution"),
        pytest.param({"step_id": "s9"}, "holder is missing", id="a-step-of-no-execution"),
        pytest.param({"goal_id": "g2"}, "another goal", id="an-execution-of-another-goal"),
    ],
)
def test_an_effect_row_whose_holder_does_not_line_up_is_refused(
    overrides: dict[str, Any], match: str
) -> None:
    """§9: the closure is stated over **one holder** rather than over three ids.

    Three independent lookups would admit a row naming a step that exists only in some
    other execution while every id still resolves, which is the shape this refuses.
    """
    with pytest.raises(ValidationError, match=match):
        _export(goals=(_goal(), _goal("g2")), effects=(_record(**overrides),))


def _satisfied(execution_id: str, step_id: str) -> StepExecution:
    """A ``SUCCEEDED`` step satisfied from ``execution_id``/``step_id``."""
    return StepExecution(
        step_id="s1",
        status=StepStatus.SUCCEEDED,
        output={"reference": "BK-1"},
        finished_at=_AT,
        satisfied_by_execution=execution_id,
        satisfied_by_step=step_id,
    )


def test_a_satisfied_steps_pair_resolves_within_the_document() -> None:
    """§9: "the same closure is owed of a satisfied step's pair"."""
    assert _export(
        executions=(_execution("x1", "p1"), _execution("x2", "p2", _satisfied("x1", "s1")))
    ).executions


@pytest.mark.parametrize(
    ("named", "step_id", "match"),
    [
        pytest.param("gone", "s1", "holder is missing", id="a-dangling-execution"),
        pytest.param("x1", "s9", "holder is missing", id="a-step-of-another-execution"),
        pytest.param("x3", "s1", "another goal", id="an-execution-of-another-goal"),
    ],
)
def test_a_satisfied_step_naming_an_act_the_document_cannot_look_up_is_refused(
    named: str, step_id: str, match: str
) -> None:
    """§9: an export naming an act the reader cannot resolve has lost the step's provenance."""
    with pytest.raises(ValidationError, match=match):
        _export(
            goals=(_goal(), _goal("g2")),
            plans=(_plan("p1"), _plan("p2"), _plan("p3", "g2")),
            executions=(
                _execution("x1", "p1"),
                _execution("x2", "p2", _satisfied(named, step_id)),
                _execution("x3", "p3"),
            ),
        )
