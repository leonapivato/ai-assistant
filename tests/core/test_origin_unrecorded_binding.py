"""ADR-0184's `core` surface: the sibling, the shared base, and what neither does.

§10 states this lane's obligations in terms, and this module is the ones that are
answerable from `core` alone: construction, the two rosters, the derived set's
correspondence with :class:`EgressBinding`'s, the **structural** claim that the
derivation is declared once, the mutual exclusion of §3 at model level, ``authorises``
answering ``False`` with no conjunct added, and §8's wire claim — which is a claim
about the *shape a peer emits* and never about a version number, since ADR-0186 §13
reads §8 as binding ADR-0184's own change rather than every later one.

**The discrimination is also pinned over a real store**, in
``tests/permissions/test_audit.py``, because §10 asks for it there: the rows this
represents exist as *bytes in a `data` column*, and a case that only ever validated a
dict would pass an implementation that never decoded one. The cases here are the
model-level half of the same rule and are not a substitute for it.

**Nothing here treats the sibling as constructible by a producer.** ADR-0184 §4 makes
it read-only — ``ActionRequest`` cannot carry one, ``from_request`` cannot make one,
and ``AuditTrail.record`` refuses one — so every value below is built directly, which
is exactly what a *store decoding a row* does and what no caller may do.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import get_type_hints

import pytest
from pydantic import BaseModel, TypeAdapter, ValidationError

from ai_assistant.core import types as core_types
from ai_assistant.core.protocols import AssistantEngine
from ai_assistant.core.types import (
    ActionRequest,
    BoundAccount,
    CanonicalDestination,
    ConfirmationEgress,
    CostBasis,
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
    ToolCost,
    ToolDefinition,
    _EgressBindingBase,
)

_AT = datetime(2026, 8, 23, 9, 0, tzinfo=UTC)
_ACCOUNT = BoundAccount(identity="work@example.com", reference="conn-0001")
_ENDPOINT = "smtp://mail.example.com:587"

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

#: The three members the two siblings share, as a store would have them off a row.
_SHARED: dict[str, object] = {
    "spans": (),
    "account": _ACCOUNT,
    "transport_endpoint": _ENDPOINT,
}

_UNION = TypeAdapter[EgressBinding | OriginUnrecordedBinding | None](
    EgressBinding | OriginUnrecordedBinding | None
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


def _pair(*spans: EgressSpan) -> tuple[EgressBinding, OriginUnrecordedBinding]:
    """The two siblings over identical shared members, for a correspondence case."""
    shared: dict[str, object] = {**_SHARED, "spans": spans}
    return (
        EgressBinding(**shared, planned_with_external_content=False),  # type: ignore[arg-type]  # heterogeneous test kwargs
        OriginUnrecordedBinding(**shared),  # type: ignore[arg-type]  # heterogeneous test kwargs
    )


# --- §10: construction, and the two rosters -----------------------------------


def test_the_sibling_refuses_the_origin_field_as_an_unknown_member() -> None:
    """§2, §3: it does not carry the member, and ``extra="forbid"`` says so.

    This is the half that makes the union *mutually exclusive* rather than merely
    ordered. Without ``extra="forbid"`` an object carrying the field would validate
    as **both** models, the arm a smart union happened to try first would win, and a
    current row could decode as a legacy one — which is the direction that matters,
    because it silently discards a recorded fact.
    """
    with pytest.raises(ValidationError, match=r"planned_with_external_content"):
        OriginUnrecordedBinding(**_SHARED, planned_with_external_content=False)  # type: ignore[arg-type,call-arg]  # the extra member under test


@pytest.mark.parametrize("omitted", sorted(OriginUnrecordedBinding.model_fields))
def test_every_member_of_the_sibling_is_required(omitted: str) -> None:
    """§2: the same three members, each required with no default.

    ADR-0150 §1's "a binding is either whole or absent" is unchanged by this ADR,
    and an ``OriginUnrecordedBinding`` is not a partially populated
    :class:`EgressBinding`: it is a different model, every one of whose members is
    required, so the fifteen partial states ADR-0150 §1 refuses stay unexpressible.
    A defaulted ``spans`` would be the sharp one — an omitted description would
    silently become an *empty* one, which ADR-0148 §8's third clause makes a floor.
    """
    assert OriginUnrecordedBinding(**_SHARED)  # type: ignore[arg-type]  # heterogeneous test kwargs

    partial: dict[str, object] = {name: value for name, value in _SHARED.items() if name != omitted}
    with pytest.raises(ValidationError) as raised:
        OriginUnrecordedBinding(**partial)  # type: ignore[arg-type]  # heterogeneous test kwargs

    assert omitted in str(raised.value)


def test_the_binding_still_refuses_construction_with_the_origin_omitted() -> None:
    """§2: ``EgressBinding`` is unchanged, and this is the clause moving it would break.

    ADR-0181 §3 makes ``planned_with_external_content`` required with no default so
    that every builder has to answer. Moving three members onto a shared base is the
    kind of edit that could quietly hand the fourth a default, and the sibling now
    sitting next to it is a standing invitation to do so.
    """
    with pytest.raises(ValidationError, match=r"planned_with_external_content"):
        EgressBinding(**_SHARED)  # type: ignore[arg-type]  # the omission under test


def test_the_two_rosters_differ_by_exactly_the_origin_field() -> None:
    """§10's first clause: a member added to either without the other is caught.

    Asserted as an equality over both rosters rather than as a difference, so it
    fails in **both** directions: a member added to ``EgressBinding`` alone leaves a
    legacy row unable to carry a fact its own epoch recorded, and one added to the
    sibling alone invents a fact no row holds. The order is asserted too, because
    the shared members must come off the base rather than be restated after it.
    """
    assert tuple(OriginUnrecordedBinding.model_fields) == (
        "spans",
        "account",
        "transport_endpoint",
    )
    assert tuple(EgressBinding.model_fields) == (
        "spans",
        "account",
        "transport_endpoint",
        "planned_with_external_content",
    )


# --- §2, §10: the shared base, asserted structurally --------------------------


@pytest.mark.parametrize("model", [EgressBinding, OriginUnrecordedBinding])
@pytest.mark.parametrize(
    "declared",
    [
        "canonical_destination_set",
        "_spans_describe_one_decomposition",
        "_one_supplied_form_canonicalises_one_way",
    ],
)
def test_the_shared_derivation_and_validators_are_declared_only_on_the_base(
    model: type[BaseModel], declared: str
) -> None:
    """§10's fourth clause: the *declared-once* claim, which no value test guards.

    Correspondence over any finite set of inputs is satisfied by a correct second
    copy just as well as by one function, so the value cases below cannot see the
    difference and are not asked to. This can: it walks the MRO and asserts the base
    is the class that declares each shared name, which fails outright the moment a
    lane pastes a copy onto either sibling.

    The validators are here for the same reason as the derivation. A second copy of
    :meth:`_spans_describe_one_decomposition` would be the "second shape that must
    agree" ADR-0150 is named after, and the two copies could drift into accepting
    different span tuples on the two sides of a round-trip.
    """
    owners = [klass.__name__ for klass in model.__mro__ if declared in vars(klass)]

    assert owners == [_EgressBindingBase.__name__], (
        f"{model.__name__} resolves {declared} through {owners}, not the shared base alone"
    )


def test_neither_sibling_inherits_from_the_other() -> None:
    """§2: the inheritance runs base-to-siblings, and this is why it matters.

    Making ``EgressBinding`` inherit from ``OriginUnrecordedBinding`` would mint one
    name instead of two and would make ``isinstance(binding, OriginUnrecordedBinding)``
    answer ``True`` for **every live binding** — so the one narrowing every consumer
    performs would silently misfire and every current row would be refused as legacy.
    The private base is what buys the shared declaration without that.
    """
    whole, legacy = _pair()

    assert not isinstance(whole, OriginUnrecordedBinding)
    assert not isinstance(legacy, EgressBinding)
    assert isinstance(whole, _EgressBindingBase)
    assert isinstance(legacy, _EgressBindingBase)


# --- §10: the correspondence of the derived set -------------------------------


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
    """§10's third clause: the clause that would otherwise rot.

    Without it a legacy row could export the wrong recipients, or omit the account
    fallback, while passing every construction, roster and discrimination case. The
    derived set is what a **surface renders**, so a history row whose set was
    computed differently from the one the user was shown when the ruling was made
    would misstate who the call was about.

    The three inputs are the three the ADR names, and each is a distinct way the
    derivation could disagree: the deduplication, the total order, and ADR-0148 §2's
    third clause — where the spans carry no destination at all the set is exactly the
    connected account, so it is **never empty** and no policy refuses on ADR-0148 §8's
    third floor for want of one.
    """
    whole, legacy = _pair(*spans)

    assert whole.canonical_destination_set == legacy.canonical_destination_set
    assert len(legacy.canonical_destination_set) == expected


def test_the_account_fallback_is_the_whole_account_on_both() -> None:
    """ADR-0148 §2's third clause, asserted by value rather than by count.

    The case above pins that a destination-less binding derives *one* member; this
    pins **which** — the connected account whole, not its identity (ADR-0150 §3's
    "no lane reduces an account member to its identity"). A sibling that derived a
    reduced member would satisfy the count and misstate the recipient.
    """
    whole, legacy = _pair()

    assert legacy.canonical_destination_set == (CanonicalDestination(account=_ACCOUNT),)
    assert whole.canonical_destination_set == legacy.canonical_destination_set


def test_the_sibling_refuses_the_span_tuples_a_binding_refuses() -> None:
    """§2: it satisfies every structural invariant ``EgressBinding`` enforces.

    Inherited rather than restated, which is the point of the base — but a lane
    could have declared the members on the sibling and left the validators behind,
    and the roster case above would still pass. Two spans sharing an
    ``(argument, index)`` pair describe one value twice; a legacy row holding one is
    corrupt, not old.
    """
    duplicated = (_span("body", 0), _span("body", 0))

    with pytest.raises(ValidationError, match=r"described twice"):
        OriginUnrecordedBinding(**{**_SHARED, "spans": duplicated})  # type: ignore[arg-type]  # heterogeneous test kwargs
    with pytest.raises(ValidationError, match=r"described twice"):
        EgressBinding(**{**_SHARED, "spans": duplicated}, planned_with_external_content=False)  # type: ignore[arg-type]  # heterogeneous test kwargs


# --- §3: the discrimination is total and mutually exclusive -------------------


def test_a_stored_object_carrying_the_origin_validates_as_the_binding_alone() -> None:
    """§3's first row: the flag present selects the flagged model, and nothing else."""
    stored = {**_SHARED, "planned_with_external_content": True}

    decoded = _UNION.validate_python(stored)

    assert isinstance(decoded, EgressBinding)
    assert decoded.planned_with_external_content is True


def test_a_stored_object_without_the_origin_validates_as_the_sibling_alone() -> None:
    """§3's second row: the flag absent selects the flagless model, and nothing else."""
    decoded = _UNION.validate_python(dict(_SHARED))

    assert isinstance(decoded, OriginUnrecordedBinding)
    assert not isinstance(decoded, EgressBinding)


def test_a_stored_object_missing_the_origin_and_faulty_elsewhere_still_raises() -> None:
    """§3's third row, and the case that fails a widened tolerance.

    This is the one that separates *shaping* the tolerance from *loosening* it. An
    implementation that recognised "the origin is missing" and then relaxed would
    accept this row; the union does not, because a member of the wrong type
    satisfies neither arm. The tolerance ADR-0184 adds is exactly one shape wide,
    and it is the type system holding it there rather than a predicate over
    ``exc.errors()``.
    """
    with pytest.raises(ValidationError):
        _UNION.validate_python({**_SHARED, "account": "work@example.com"})


def test_a_stored_object_carrying_an_undeclared_member_still_raises() -> None:
    """§3's fourth row: neither model admits a member it does not declare.

    A row from a *later* schema than either model knows is a downgraded database,
    not a legacy one, and it stays the fault it has always been. Without
    ``extra="forbid"`` this would decode as whichever arm ignored the key.
    """
    with pytest.raises(ValidationError):
        _UNION.validate_python({**_SHARED, "schema_epoch": 2})


def test_a_stored_null_binding_still_means_no_egress_call() -> None:
    """§3's fifth row, and ADR-0150 §1's second clause standing unchanged.

    ``None`` continues to mean exactly one thing — the request is not an egress call
    — and this ADR does not use it to mean "the binding was unreadable". That is the
    whole reason the sibling had to exist: the cheap projection was forbidden.
    """
    assert _UNION.validate_python(None) is None


# --- §6: `authorises` answers False, through the conjunct that was already there


@pytest.mark.parametrize("offered_origin", [True, False])
def test_a_decision_carrying_the_sibling_authorises_nothing(offered_origin: bool) -> None:
    """§6, §10's eighth clause: ``False`` against a request whose members all agree.

    The request's binding carries the **same** ``spans``, ``account`` and
    ``transport_endpoint``, so nothing but the class can make the comparison fail —
    and it is asserted for a request carrying ``True`` **and** one carrying
    ``False``, so neither value is the reason. That is what fails an implementation
    that compared the shared members separately, or exempted the origin from the
    comparison to make a legacy row resumable.

    No conjunct was added for this. ADR-0150 §9 and ADR-0181 §3's fourth clause make
    the binding compared whole and by value, and pydantic's equality is per class, so
    a model of one class never equals a model of another whatever its members hold.

    The call carries no arguments, so the binding's description is empty on both
    sides and every other conjunct — tool, digest, step, execution — agrees by
    construction. That is not a weaker subject: ADR-0148 §2's third clause makes an
    empty description still name a destination (the connected account), so this is a
    binding with a real recipient and the comparison has everything it needs.
    """
    request = ActionRequest(
        tool=_TOOL,
        parameters={},
        step_id="step-1",
        execution_id="exec-1",
        egress_binding=EgressBinding(**_SHARED, planned_with_external_content=offered_origin),  # type: ignore[arg-type]  # heterogeneous test kwargs
    )
    recorded = PermissionDecision(
        id="d-1",
        ruling=PermissionRuling(outcome=PermissionOutcome.ALLOW, reason="a rule allowed it"),
        tool=_TOOL,
        parameters_digest=request.parameters_digest,
        decided_at=_AT,
        step_id="step-1",
        execution_id="exec-1",
        egress_binding=OriginUnrecordedBinding(**_SHARED),  # type: ignore[arg-type]  # heterogeneous test kwargs
    )

    assert recorded.authorises(request) is False


def test_a_request_cannot_carry_the_sibling_at_all() -> None:
    """§2's fourth clause: ``ActionRequest.egress_binding`` stays narrow.

    This is the clause that makes the origin-unrecorded shape unreachable from every
    live path *by construction*, which is in turn why
    :meth:`PermissionDecision.from_request` needs no branch and gains no route.
    A widened request field would give every builder a way to not answer, which is
    exactly what ADR-0181 §3's "required with no default" exists to deny.
    """
    with pytest.raises(ValidationError):
        ActionRequest(
            tool=_TOOL,
            parameters={},
            step_id="step-1",
            egress_binding=OriginUnrecordedBinding(**_SHARED),  # type: ignore[arg-type]  # the widening under test
        )


def test_from_request_transcribes_the_narrow_field_and_makes_no_sibling() -> None:
    """§4's third clause: the factory has no route to the shape.

    Nothing to branch on, because the source field cannot hold one. Asserted rather
    than reasoned about, because "unreachable by construction" is a claim about the
    *annotation* that a later widening would falsify silently.
    """
    request = ActionRequest(
        tool=_TOOL,
        parameters={},
        step_id="step-1",
        egress_binding=EgressBinding(**_SHARED, planned_with_external_content=True),  # type: ignore[arg-type]  # heterogeneous test kwargs
    )

    recorded = PermissionDecision.from_request(
        request,
        PermissionRuling(outcome=PermissionOutcome.CONFIRM, reason="ask"),
        id="d-1",
        decided_at=_AT,
    )

    assert isinstance(recorded.egress_binding, EgressBinding)
    assert recorded.egress_binding.planned_with_external_content is True


# --- §8: no wire move, and the shape that now crosses -------------------------


def test_this_decision_still_changes_no_shape_a_peer_emits() -> None:
    """§8's first clause, pinned as the property it is rather than as a number.

    **The absolute pin this used to be is gone, and its removal is the clause read
    correctly rather than a relaxation.** §8 says ``PROTOCOL_VERSION`` "does not move
    **for this decision**"; ADR-0186 §13 reads that as being about ADR-0184's own
    change and "not a bar on any later one", and ADR-0186 §5 then moves the version
    to 12 under ADR-0124 §9's **first** limb — two methods added to the promoted set.
    A test asserting ``== 11`` here would have made a later, unrelated and correctly
    reasoned bump look like a violation of this ADR, which is the failure
    ``CONTRIBUTING.md`` -> "No state claims in living documents" is about. The one
    place that number is pinned is
    ``tests/core/test_engine_surface_closure.py``, where a lane moving it is made to
    name the limb it is under.

    What survives here is the half §8 actually decides and this module can check:
    ADR-0124 §9's **second** limb did not fire for ADR-0184, because the shape a peer
    emits is unchanged. ``ConfirmationEgress`` — the type that crosses, on
    ``TurnOutcome.step.confirmation`` and as the element type of
    ``pending_confirmations`` — gains no member and no origin-unrecorded variant, so a
    peer at either version emits and accepts exactly what it did.
    """
    members = set(ConfirmationEgress.model_fields)

    assert "planned_with_external_content" in members
    # The widening §8's second clause forbids: a nullable member, or a second
    # binding-shaped one, would be how an origin-unrecorded confirmation arrived.
    assert ConfirmationEgress.model_fields["planned_with_external_content"].is_required()
    assert not any(name.startswith("origin") for name in members)


def test_the_sibling_survives_the_promoted_surfaces_own_return_adapter() -> None:
    """ADR-0186 §5, verified in this tree rather than reasoned about.

    ADR-0186 puts ``PermissionDecision`` on the promoted surface, so §8's premise that
    it "is named nowhere under ``wire/`` and is returned by no promoted method" no
    longer holds — and the question §8 answered for ``Confirmation`` has to be
    answered again for this type. ADR-0186 §5 answers it: the decision round-trips
    **equal** through a ``TypeAdapter`` of ``export_decisions``' own declared return
    annotation, which is the shape ADR-0085 §10 builds a result payload from, and the
    decoded value carries no ``planned_with_external_content`` key anywhere under
    ``egress_binding``.

    **So ADR-0184 §3's discrimination is total on the client side too**, with no
    discriminator member and nothing transcribed into a wire-side schema: the union
    re-discriminates *structurally* at the far end, because ``EgressBinding`` sets
    ``extra="forbid"`` and therefore refuses the member's absence exactly as
    ``OriginUnrecordedBinding`` refuses its presence. A lane that "helpfully" gave the
    sibling a default would break this and nothing else would notice.
    """
    recorded = PermissionDecision(
        id="d-1",
        ruling=PermissionRuling(outcome=PermissionOutcome.ALLOW, reason="a rule allowed it"),
        tool=_TOOL,
        parameters_digest="0" * 64,
        decided_at=_AT,
        step_id="step-1",
        execution_id="exec-1",
        egress_binding=OriginUnrecordedBinding(**_SHARED),  # type: ignore[arg-type]  # heterogeneous test kwargs
    )
    adapter: TypeAdapter[tuple[PermissionDecision, ...]] = TypeAdapter(
        get_type_hints(AssistantEngine.export_decisions, globalns=vars(core_types))["return"]
    )

    projected = adapter.dump_python((recorded,), mode="json")
    decoded = adapter.validate_python(projected)

    assert decoded == (recorded,)
    assert isinstance(decoded[0].egress_binding, OriginUnrecordedBinding)
    assert "planned_with_external_content" not in projected[0]["egress_binding"]
