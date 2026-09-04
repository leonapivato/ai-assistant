"""ADR-0233 §14's third rung: the sibling, the chain, and what the ladder refuses.

``tests/core/test_origin_unrecorded_binding.py``'s obligations one epoch on, over the
shape ADR-0184 §9's deferral is answered with. What is answerable from `core` alone:
the roster, the **structural** claim that each member is declared exactly once on the
chain, the ladder's mutual exclusion at model level, ``authorises`` answering ``False``
with no conjunct added, and the two clauses that make the shape unmintable — a request
cannot carry one and ``from_request`` has no route to one.

**The discrimination is also pinned over a real store**, in
``tests/permissions/test_audit.py``, because ADR-0233 §15 asks for it there: the rows
this represents exist as *bytes in a `data` column*, and a case that only ever
validated a dict would pass an implementation that never decoded one. The cases here
are the model-level half of the same rule and are not a substitute for it.

**Nothing here treats the sibling as constructible by a producer.** ADR-0233 §14 makes
it read-only — ``ActionRequest`` cannot carry one, ``from_request`` cannot make one,
``AuditTrail.record`` refuses one and ``pending_confirmation`` never offers one — so
every value below is built directly, which is exactly what a *store decoding a row*
does and what no caller may do.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import BaseModel, TypeAdapter, ValidationError

from ai_assistant.core.types import (
    ActionRequest,
    BoundAccount,
    CanonicalDestination,
    ConfirmationEgress,
    CostBasis,
    CoverageUnrecordedBinding,
    DataTier,
    DestinationProtocol,
    DiscloserProvenance,
    EgressBinding,
    EgressDestination,
    EgressSpan,
    Idempotency,
    OriginUnrecordedBinding,
    PermissionDecision,
    PermissionOutcome,
    PermissionRuling,
    Reversibility,
    RiskLevel,
    SpanCoverage,
    ToolCost,
    ToolDefinition,
    _EgressBindingBase,
    _OriginRecordedBindingBase,
)

_AT = datetime(2026, 9, 4, 9, 0, tzinfo=UTC)
_ACCOUNT = BoundAccount(identity="work@example.com", reference="conn-0001")
_ENDPOINT = "smtp://mail.example.com:587"

#: The four members the two origin-recorded rungs share, as a store would have them
#: off a row. ``coverage`` is what separates them and is therefore not here.
_SHARED: dict[str, object] = {
    "spans": (),
    "account": _ACCOUNT,
    "transport_endpoint": _ENDPOINT,
    "planned_with_external_content": False,
}

_LADDER = TypeAdapter[EgressBinding | CoverageUnrecordedBinding | OriginUnrecordedBinding | None](
    EgressBinding | CoverageUnrecordedBinding | OriginUnrecordedBinding | None
)

_TOOL = ToolDefinition(
    id="smtp",
    capability="send_email",
    description="Send an email.",
    risk_level=RiskLevel.LOW,
    reversibility=Reversibility.REVERSIBLE,
    side_effecting=True,
    reads=(),
    writes=(),
    discloses=(DataTier.PERSONAL,),
    cost=ToolCost(basis=CostBasis.FREE),
    idempotency=Idempotency.NATURAL,
    parameters_schema={"type": "object"},
)


def _to(supplied: str, canonical: str) -> EgressDestination:
    """One occurrence, in both the form the caller supplied and the canonical one."""
    return EgressDestination(
        protocol=DestinationProtocol.SMTP, supplied=supplied, canonical=canonical
    )


def _span(argument: str, index: int | None = None, **overrides: object) -> EgressSpan:
    """A described span, optionally carrying a destination occurrence."""
    fields: dict[str, object] = {
        "argument": argument,
        "index": index,
        "provenance": DiscloserProvenance.SYSTEM_SELECTED,
        "extent": 1,
    }
    fields.update(overrides)
    return EgressSpan(**fields)  # type: ignore[arg-type]  # heterogeneous test kwargs


def _pair(*spans: EgressSpan) -> tuple[EgressBinding, CoverageUnrecordedBinding]:
    """The whole binding and the middle rung over identical shared members."""
    shared: dict[str, object] = {**_SHARED, "spans": spans}
    return (
        EgressBinding(
            **shared,  # type: ignore[arg-type]  # heterogeneous test kwargs
            coverage=SpanCoverage.NOT_COVERED,
        ),
        CoverageUnrecordedBinding(**shared),  # type: ignore[arg-type]  # heterogeneous test kwargs
    )


# --- §14: construction, and the roster the epoch recorded -----------------------


def test_the_sibling_refuses_the_coverage_field_as_an_unknown_member() -> None:
    """§14's discrimination clause: it does not carry the member, and ``extra="forbid"``
    says so.

    This is the half that makes the ladder *mutually exclusive* rather than merely
    ordered. Without ``extra="forbid"`` an object carrying ``coverage`` would validate
    as **both** this model and :class:`EgressBinding`, the arm a smart union happened
    to try first would win, and a current row could decode as a middle-rung one —
    which is the direction that matters, because it silently discards a recorded fact
    and then refuses the park it was recorded for.
    """
    with pytest.raises(ValidationError, match=r"coverage"):
        CoverageUnrecordedBinding(**_SHARED, coverage=SpanCoverage.NOT_COVERED)  # type: ignore[arg-type,call-arg]  # the extra member under test


@pytest.mark.parametrize("omitted", sorted(CoverageUnrecordedBinding.model_fields))
def test_every_member_of_the_sibling_is_required(omitted: str) -> None:
    """§14's second clause: the same four members, each required with no default.

    ADR-0150 §1's "a binding is either whole or absent" is unchanged, and a
    ``CoverageUnrecordedBinding`` is not a partially populated
    :class:`EgressBinding`: it is a different model, every one of whose members is
    required, so the partial states ADR-0150 §1 refuses stay unexpressible.
    ``planned_with_external_content`` is the sharp one here — a default on it would
    make this rung indistinguishable from the one below and collapse the ladder.
    """
    assert CoverageUnrecordedBinding(**_SHARED)  # type: ignore[arg-type]  # heterogeneous test kwargs

    partial: dict[str, object] = {name: value for name, value in _SHARED.items() if name != omitted}
    with pytest.raises(ValidationError) as raised:
        CoverageUnrecordedBinding(**partial)  # type: ignore[arg-type]  # heterogeneous test kwargs

    assert omitted in str(raised.value)


def test_the_three_rosters_are_the_chain_read_off_in_order() -> None:
    """§14's second clause: each shape is the next one minus a field, in order.

    Asserted as three equalities rather than as differences, so it fails in **every**
    direction: a member added to ``EgressBinding`` alone leaves a recorded row unable
    to carry a fact its own epoch held, one added to a sibling alone invents a fact no
    row holds, and one added out of order breaks the ladder into a matrix. The order
    within each roster is asserted too, because the shared members must come off the
    chain rather than be restated after it.
    """
    assert tuple(OriginUnrecordedBinding.model_fields) == (
        "spans",
        "account",
        "transport_endpoint",
    )
    assert tuple(CoverageUnrecordedBinding.model_fields) == (
        "spans",
        "account",
        "transport_endpoint",
        "planned_with_external_content",
    )
    assert tuple(EgressBinding.model_fields) == (
        "spans",
        "account",
        "transport_endpoint",
        "planned_with_external_content",
        "coverage",
    )


# --- §14: each member declared exactly once, asserted structurally ---------------


@pytest.mark.parametrize(
    "model", [EgressBinding, CoverageUnrecordedBinding, OriginUnrecordedBinding]
)
@pytest.mark.parametrize(
    "declared",
    [
        "canonical_destination_set",
        "_spans_describe_one_decomposition",
        "_one_supplied_form_canonicalises_one_way",
    ],
)
def test_the_shared_derivation_and_validators_are_declared_only_on_the_root(
    model: type[BaseModel], declared: str
) -> None:
    """§14's declare-each-member-once rule, over the names every rung shares.

    ``tests/core/test_origin_unrecorded_binding.py``'s structural case widened to the
    third rung, and it is the case no value test can stand in for: correspondence over
    any finite set of inputs is satisfied by a correct second copy just as well as by
    one function. This walks the MRO and asserts the chain's **root** is the class that
    declares each shared name, so it fails outright the moment a lane pastes a copy
    onto a rung.
    """
    owners = [klass.__name__ for klass in model.__mro__ if declared in vars(klass)]

    assert owners == [_EgressBindingBase.__name__], (
        f"{model.__name__} resolves {declared} through {owners}, not the chain's root alone"
    )


@pytest.mark.parametrize("model", [EgressBinding, CoverageUnrecordedBinding])
def test_the_origin_member_is_declared_only_on_the_rung_the_two_share(
    model: type[BaseModel],
) -> None:
    """§14's second clause on the member the chain's second rung exists for.

    ``planned_with_external_content`` is carried by two of the three shapes, so a lane
    could have declared it twice — once on each — and every roster case above would
    still pass while the two declarations drifted in type, description or default.
    The private rung is what buys the single declaration, and this is what pins it
    there.
    """
    owners = [
        klass.__name__ for klass in model.__mro__ if "planned_with_external_content" in vars(klass)
    ]

    assert owners == [], "declared as a pydantic field on the rung, not in a class body"
    assert "planned_with_external_content" in _OriginRecordedBindingBase.model_fields, (
        "the rung the two origin-recorded shapes share is where the member lives"
    )
    assert "planned_with_external_content" not in OriginUnrecordedBinding.model_fields


def test_no_rung_inherits_from_another() -> None:
    """§14, and ADR-0184 §2's reason read over three shapes rather than two.

    Making ``EgressBinding`` inherit from ``CoverageUnrecordedBinding`` would mint one
    name instead of two and would make ``isinstance(binding, CoverageUnrecordedBinding)``
    answer ``True`` for **every live binding** — so every narrowing written for the
    epoch would misfire and every current row would be refused as legacy. The private
    chain buys the shared declaration without that, and each rung is a leaf.
    """
    whole, middle = _pair()
    legacy = OriginUnrecordedBinding(spans=(), account=_ACCOUNT, transport_endpoint=_ENDPOINT)

    assert not isinstance(whole, CoverageUnrecordedBinding)
    assert not isinstance(whole, OriginUnrecordedBinding)
    assert not isinstance(middle, EgressBinding)
    assert not isinstance(middle, OriginUnrecordedBinding)
    assert not isinstance(legacy, CoverageUnrecordedBinding)
    assert isinstance(middle, _OriginRecordedBindingBase)
    assert not isinstance(legacy, _OriginRecordedBindingBase)
    assert isinstance(whole, _EgressBindingBase)
    assert isinstance(middle, _EgressBindingBase)


# --- §14: the derived set corresponds, so history states the right recipients ----


@pytest.mark.parametrize(
    ("spans", "expected"),
    [
        pytest.param((), 1, id="no-destination-falls-back-to-the-account"),
        pytest.param(
            (
                _span("to", 0, destination=_to("b@example.com", "b@example.com")),
                _span("to", 1, destination=_to("a@example.com", "a@example.com")),
            ),
            2,
            id="several-destinations",
        ),
        pytest.param(
            (
                _span("to", 0, destination=_to("Alice@Example.com", "alice@example.com")),
                _span("to", 1, destination=_to("alice@example.com", "alice@example.com")),
            ),
            1,
            id="an-aliased-pair-deduplicates",
        ),
    ],
)
def test_the_derived_set_corresponds_member_for_member_and_in_order(
    spans: tuple[EgressSpan, ...], expected: int
) -> None:
    """ADR-0184 §10's third clause, over the rung ADR-0233 adds.

    The clause that would otherwise rot: without it a middle-rung row could export the
    wrong recipients, or omit the account fallback, while passing every construction,
    roster and discrimination case. The derived set is what a **surface renders**, so a
    history row whose set was computed differently from the one the user was shown when
    the ruling was made would misstate who the call was about.

    The three inputs are the three the deduplication, the total order and ADR-0148 §2's
    third clause each turn on — the last being that where the spans carry no
    destination the set is exactly the connected account, so it is **never empty**.
    """
    whole, middle = _pair(*spans)

    assert whole.canonical_destination_set == middle.canonical_destination_set
    assert len(middle.canonical_destination_set) == expected


def test_the_account_fallback_is_the_whole_account() -> None:
    """ADR-0148 §2's third clause, asserted by value rather than by count.

    The case above pins that a destination-less binding derives *one* member; this
    pins **which** — the connected account whole, not its identity (ADR-0150 §3's "no
    lane reduces an account member to its identity"). A rung that derived a reduced
    member would satisfy the count and misstate the recipient.
    """
    whole, middle = _pair()

    assert middle.canonical_destination_set == (CanonicalDestination(account=_ACCOUNT),)
    assert whole.canonical_destination_set == middle.canonical_destination_set


def test_the_sibling_refuses_the_span_tuples_a_binding_refuses() -> None:
    """§14: it satisfies every structural invariant ``EgressBinding`` enforces.

    Inherited rather than restated, which is the point of the chain — but a lane could
    have declared the members on the rung and left the validators behind, and the
    roster cases above would still pass. Two spans sharing an ``(argument, index)``
    pair describe one value twice; a row holding one is corrupt, not old.
    """
    duplicated = (_span("body", 0), _span("body", 0))

    with pytest.raises(ValidationError, match=r"described twice"):
        CoverageUnrecordedBinding(**{**_SHARED, "spans": duplicated})  # type: ignore[arg-type]  # heterogeneous test kwargs


# --- §14: the ladder is structural, total and mutually exclusive ----------------


def test_a_stored_object_carrying_both_keys_validates_as_the_binding_alone() -> None:
    """§14's ladder, first rung: both keys select ``EgressBinding`` and nothing else."""
    decoded = _LADDER.validate_python({**_SHARED, "coverage": "not_covered"})

    assert isinstance(decoded, EgressBinding)
    assert decoded.coverage is SpanCoverage.NOT_COVERED


def test_a_stored_object_carrying_the_origin_but_not_the_coverage_is_the_middle_rung() -> None:
    """§14's ladder, second rung: the epoch this ADR mints a shape for.

    The row records its origin and not its coverage, and both facts come back — which
    is the whole reason every refusal for this epoch is *stated* rather than inherited
    from the origin guard: such a row **has** ``planned_with_external_content`` and
    falls straight past any ``isinstance`` written for ``OriginUnrecordedBinding``.
    """
    decoded = _LADDER.validate_python(dict(_SHARED))

    assert isinstance(decoded, CoverageUnrecordedBinding)
    assert not isinstance(decoded, EgressBinding)
    assert not isinstance(decoded, OriginUnrecordedBinding)
    assert decoded.planned_with_external_content is False


def test_a_stored_object_carrying_neither_key_is_the_bottom_rung() -> None:
    """§14's ladder, third rung: ADR-0184 §1's roster with the second name added.

    The epochs are totally ordered, so a row lacking ``planned_with_external_content``
    necessarily lacks ``coverage`` too — which is why the ladder is a chain and no
    fourth combination exists to represent.
    """
    decoded = _LADDER.validate_python(
        {name: value for name, value in _SHARED.items() if name != "planned_with_external_content"}
    )

    assert isinstance(decoded, OriginUnrecordedBinding)
    assert not isinstance(decoded, CoverageUnrecordedBinding)


def test_a_stored_object_carrying_the_coverage_but_not_the_origin_raises() -> None:
    """§14's ladder: the combination a **matrix** would admit and a chain does not.

    ADR-0233 §15 names this as one of the cases that fails an implementation which
    widened the tolerance rather than shaping it. Such a row is nobody's epoch: no
    build ever wrote it, ``OriginUnrecordedBinding`` does not declare ``coverage`` and
    both other rungs require ``planned_with_external_content``, so it satisfies no arm
    of the union at all.
    """
    with pytest.raises(ValidationError):
        _LADDER.validate_python(
            {
                name: value
                for name, value in {**_SHARED, "coverage": "not_covered"}.items()
                if name != "planned_with_external_content"
            }
        )


def test_a_stored_object_missing_the_coverage_and_faulty_elsewhere_still_raises() -> None:
    """§14: the tolerance is exactly as many shapes wide as there are epochs.

    An implementation that recognised "the coverage is missing" and then relaxed would
    accept this row; the ladder does not, because a member of the wrong type satisfies
    no rung. It is the type system holding the tolerance there rather than a predicate
    over ``exc.errors()``.
    """
    with pytest.raises(ValidationError):
        _LADDER.validate_python({**_SHARED, "account": "work@example.com"})


def test_a_stored_object_carrying_an_undeclared_member_still_raises() -> None:
    """§14: no rung admits a member it does not declare.

    A row from a *later* schema than any rung knows is a downgraded database, not a
    legacy one, and it stays the fault it has always been. ``extra="forbid"`` on the
    chain's root is what makes this hold for all three arms at once.
    """
    with pytest.raises(ValidationError):
        _LADDER.validate_python({**_SHARED, "schema_epoch": 3})


def test_a_stored_null_binding_still_means_no_egress_call() -> None:
    """ADR-0150 §1's second clause, standing unchanged through a second epoch.

    ``None`` continues to mean exactly one thing — the request is not an egress call —
    and ADR-0233 does not use it to mean "the binding was unreadable". That is the
    whole reason a second sibling had to exist rather than a cheap projection.
    """
    assert _LADDER.validate_python(None) is None


def test_a_middle_rung_row_fabricates_no_coverage_on_the_way_out() -> None:
    """§14's nothing-is-fabricated clause, at the model.

    ``coverage`` is required with no default and ADR-0233 §5 forbids a seam inventing
    one, so every member of :class:`SpanCoverage` is out; the model does not carry the
    member at all, so ``model_dump`` emits no key for it and an export is a faithful
    copy of what the row says.
    """
    _, middle = _pair()

    assert "coverage" not in middle.model_dump()
    assert middle.model_dump()["planned_with_external_content"] is False


# --- §14: authorises answers False, through the conjunct that was already there --


@pytest.mark.parametrize(
    "offered", [SpanCoverage.NOT_COVERED, SpanCoverage.MODEL_ON_EVERY_PATH], ids=lambda m: m.value
)
def test_a_decision_carrying_the_sibling_authorises_nothing(offered: SpanCoverage) -> None:
    """§14, ADR-0184 §6: ``False`` against a request whose members all agree.

    The request's binding carries the **same** ``spans``, ``account``,
    ``transport_endpoint`` and ``planned_with_external_content``, so nothing but the
    class can make the comparison fail — and it is asserted for **each** coverage a
    request can carry, so no particular value is the reason. That is what fails an
    implementation which compared the shared members separately, or exempted the
    coverage from the comparison to make such a row resumable.

    No conjunct was added for this. ADR-0150 §9 and ADR-0181 §3's fourth clause make
    the binding compared whole and by value, and pydantic's equality is per class, so a
    model of one class never equals a model of another whatever its members hold.
    """
    request = ActionRequest(
        tool=_TOOL,
        parameters={},
        step_id="step-1",
        execution_id="exec-1",
        egress_binding=EgressBinding(
            **_SHARED,  # type: ignore[arg-type]  # heterogeneous test kwargs
            coverage=offered,
        ),
    )
    recorded = PermissionDecision(
        id="d-1",
        ruling=PermissionRuling(outcome=PermissionOutcome.ALLOW, reason="a rule allowed it"),
        tool=_TOOL,
        parameters_digest=request.parameters_digest,
        decided_at=_AT,
        step_id="step-1",
        execution_id="exec-1",
        egress_binding=CoverageUnrecordedBinding(**_SHARED),  # type: ignore[arg-type]  # heterogeneous test kwargs
    )

    assert recorded.authorises(request) is False


def test_a_request_cannot_carry_the_sibling_at_all() -> None:
    """§14's third clause: ``ActionRequest.egress_binding`` stays narrow.

    This is what makes the shape unreachable from every live path *by construction*,
    which is in turn why :meth:`PermissionDecision.from_request` needs no branch and
    gains no route. A widened request field would give every builder a way to not
    answer, which is what "required with no default" exists to deny.
    """
    with pytest.raises(ValidationError):
        ActionRequest(
            tool=_TOOL,
            parameters={},
            step_id="step-1",
            egress_binding=CoverageUnrecordedBinding(**_SHARED),  # type: ignore[arg-type]  # the widening under test
        )


def test_from_request_transcribes_the_narrow_field_and_makes_no_sibling() -> None:
    """§14's third clause: the factory has no route to the shape.

    Nothing to branch on, because the source field cannot hold one. Asserted rather
    than reasoned about, because "unreachable by construction" is a claim about the
    *annotation* that a later widening would falsify silently.
    """
    request = ActionRequest(
        tool=_TOOL,
        parameters={},
        step_id="step-1",
        egress_binding=EgressBinding(
            **_SHARED,  # type: ignore[arg-type]  # heterogeneous test kwargs
            coverage=SpanCoverage.MODEL_ON_EVERY_PATH,
        ),
    )

    recorded = PermissionDecision.from_request(
        request,
        PermissionRuling(outcome=PermissionOutcome.CONFIRM, reason="ask"),
        id="d-1",
        decided_at=_AT,
    )

    assert isinstance(recorded.egress_binding, EgressBinding)
    assert recorded.egress_binding.coverage is SpanCoverage.MODEL_ON_EVERY_PATH


def test_no_confirmation_shape_exists_for_this_epoch() -> None:
    """§14's last clause: no coverage-unrecorded confirmation shape is minted.

    ``ConfirmationEgress.coverage`` is required with no default, so composing one for a
    row that never recorded the fact would demand the fabrication this representation
    exists to avoid — at the surface where a user is being asked to approve something.
    The absence is answered by not asking the question; both assembly sites refuse such
    a row and neither gives the member a default or a nullable variant.
    """
    assert ConfirmationEgress.model_fields["coverage"].is_required()
    assert not any(name.startswith("coverage_") for name in ConfirmationEgress.model_fields)

    with pytest.raises(ValidationError, match="coverage"):
        ConfirmationEgress(  # type: ignore[call-arg]  # the omission under test
            account_identity=_ACCOUNT.identity,
            spans=(),
            planned_with_external_content=False,
        )
