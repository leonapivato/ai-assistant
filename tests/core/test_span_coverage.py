"""ADR-0233's `core` surface: the three-valued fact, and the refusal it makes possible.

§15's representative inputs that fall to `core` alone. The enum's membership and the
order it is *named* for; the construction refusal §6 gives ADR-0155 §3's absolute
clause; ``authorises`` refusing across ``coverage`` **alone**, which §15 names as the
case that fails an implementation leaving the field out of the whole-binding
comparison; and the transcription onto the shape that crosses the wire.

**Two things this module deliberately does not test.** The *computation* of the value
is ADR-0233 §5's and belongs to the lane that follows the `core` change (#2051): here
every value is stated by the test, which is exactly what a component holding a
recorded answer does. And what a **surface** owes for it is ADR-0233 §8's floor,
which is stated over the two renderers and pinned in their own lanes' tests; nothing
here asserts anything about a rendering.

**The third rung of ADR-0233 §14's ladder is next door**, in
``tests/core/test_coverage_unrecorded_binding.py``, with the discrimination over a
real store in ``tests/permissions/test_audit.py``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Final

import pytest
from pydantic import TypeAdapter, ValidationError

from ai_assistant.core.types import (
    ActionRequest,
    BoundAccount,
    CarriedProvenance,
    Confirmation,
    ConfirmationEgress,
    ContinuationToken,
    CostBasis,
    DataTier,
    DestinationProtocol,
    DiscloserProvenance,
    EgressBinding,
    EgressDestination,
    EgressSpan,
    Idempotency,
    PermissionDecision,
    PermissionOutcome,
    PermissionRuling,
    Reversibility,
    RiskLevel,
    SpanCoverage,
    ToolCost,
    ToolDefinition,
)
from ai_assistant.wire.codec import project

_AT = datetime(2026, 9, 4, 9, 0, tzinfo=UTC)
_ACCOUNT = BoundAccount(identity="work@example.com", reference="conn-0001")
_ENDPOINT = "smtp://mail.example.com:587"

#: ADR-0233 §4's total order, written out rather than read off the members' values.
#: ``StrEnum`` compares as text and ``"model_on_every_path" < "not_covered"``
#: lexically, so the strings state the *opposite* order — which is precisely why the
#: ADR states the order in prose and why no lane derives it from the spellings.
_STRONGEST_LAST: Final = (
    SpanCoverage.NOT_COVERED,
    SpanCoverage.MODEL_ON_EVERY_PATH,
    SpanCoverage.PATH_WITHOUT_MODEL,
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


def _span(argument: str = "body", *, extent: int = 2) -> EgressSpan:
    """One described span of an argument's whole value."""
    return EgressSpan(
        argument=argument,
        provenance=DiscloserProvenance.SYSTEM_SELECTED,
        extent=extent,
    )


def _binding(coverage: SpanCoverage, *spans: EgressSpan) -> EgressBinding:
    """A whole binding at ``coverage``, over ``spans`` or over none."""
    return EgressBinding(
        spans=spans,
        account=_ACCOUNT,
        transport_endpoint=_ENDPOINT,
        planned_with_external_content=False,
        coverage=coverage,
    )


# --- §4: exactly three members, named for the quantifiers -----------------------


def test_the_enum_holds_exactly_the_three_states_the_partition_names() -> None:
    """§4's first clause: one member per state ADR-0155 §3's first clause names.

    **Three rather than a boolean, because the two prohibitions are different
    prohibitions.** A boolean "is this covered" cannot tell the absolutely forbidden
    case from the approvable one, and a boolean "is this approvable" would put the
    partition's reasoning inside a field name where no reviewer can check it against
    ADR-0155 §3. The names carry the quantifier each clause is stated with — *every*
    path versus *some* path — because the quantifiers are what make the partition
    exhaustive, and a name that dropped them would be the first thing to drift.

    Asserted as an equality over the whole membership, so a fourth member, an
    "unknown" member or a rename fails here rather than in a surface's lane.
    """
    assert set(SpanCoverage) == {
        SpanCoverage.NOT_COVERED,
        SpanCoverage.MODEL_ON_EVERY_PATH,
        SpanCoverage.PATH_WITHOUT_MODEL,
    }
    assert [member.value for member in SpanCoverage] == [
        "not_covered",
        "model_on_every_path",
        "path_without_model",
    ]


def test_the_declared_order_is_not_the_order_the_spellings_compare_in() -> None:
    """§4's third clause, pinned as the trap it is rather than as the rule it states.

    The order is ADR-0155 §3's own — "the overlap falls to the absolute clause",
    because one non-model path keeps content under it **forever** — and it is
    ``NOT_COVERED`` < ``MODEL_ON_EVERY_PATH`` < ``PATH_WITHOUT_MODEL``. Since
    ``SpanCoverage`` is a ``StrEnum``, ``<`` on two members compares their *spellings*
    and answers the wrong thing for the very pair that matters most. This asserts the
    disagreement rather than papering over it, so a lane reaching for ``max()`` over
    the members finds out here instead of silently weakening a call's recorded state.
    """
    assert SpanCoverage.MODEL_ON_EVERY_PATH < SpanCoverage.NOT_COVERED, (
        "the lexical order of the spellings, which is not the order §4 states"
    )
    assert _STRONGEST_LAST[-1] is SpanCoverage.PATH_WITHOUT_MODEL


# --- §6: the construction refusal, unconditional --------------------------------


def test_a_binding_carrying_a_covered_path_with_no_model_call_is_unconstructable() -> None:
    """§6's first clause, and ADR-0155 §3's second clause getting its first mechanism.

    §15's fourth representative input: a request whose composed arguments carry a
    covered path with no model call is refused at ``EgressBinding`` construction, so
    **no confirmation is ever built for it** — which is why what is asserted here is
    the refusal at the type rather than a denial anywhere downstream.

    The refusal is at construction rather than at the ruling because ADR-0155 §3's
    fourth clause makes authorisation irrelevant to it: "No authorisation makes a
    transmission either prohibition above forbids lawful." A refusal a policy could be
    replaced out of is not the refusal that clause asks for, which is also why §6 adds
    no ``ActionPolicy`` floor for the case.
    """
    with pytest.raises(ValidationError, match="no model call"):
        _binding(SpanCoverage.PATH_WITHOUT_MODEL, _span())


@pytest.mark.parametrize(
    "coverage",
    [SpanCoverage.NOT_COVERED, SpanCoverage.MODEL_ON_EVERY_PATH],
    ids=lambda member: member.value,
)
def test_the_other_two_states_construct(coverage: SpanCoverage) -> None:
    """§6's boundary: the refusal is one state wide, not a bar on carrying the fact.

    Without this, "refuse ``PATH_WITHOUT_MODEL``" is satisfied by a validator that
    refused every binding, which would make the whole surface unbuildable while
    passing the case above. ``MODEL_ON_EVERY_PATH`` is the state ADR-0233 exists to
    make approvable, so a lane that refused it has implemented arm (a).
    """
    assert _binding(coverage, _span()).coverage is coverage


def test_the_refusal_names_no_value_of_the_payload() -> None:
    """§6, ADR-0150 §8: the state names the defect, and the message names nothing else.

    A binding's spans are locators and extents rather than values, but the *argument
    name* is a caller's string and ADR-0150 §13's residue records that a model
    composing a call can put content of its own choosing into a key. The message names
    the prohibition and the clause; it does not name the argument, the account, the
    endpoint or the recipient.
    """
    with pytest.raises(ValidationError) as raised:
        _binding(SpanCoverage.PATH_WITHOUT_MODEL, _span("a-key-a-model-chose"))

    rendered = str(raised.value)
    assert "a-key-a-model-chose" not in rendered
    assert _ACCOUNT.identity not in rendered
    assert _ENDPOINT not in rendered


def test_no_flag_parameter_or_subclass_admits_the_refused_state() -> None:
    """§6's first clause: "no lane adds a parameter, a flag or a subclass".

    The subclass arm is the one a lane would actually reach for, and pydantic makes it
    look harmless: a model inheriting ``EgressBinding`` inherits its validators, so the
    refusal holds through the inheritance rather than being re-run at the top level
    only. Asserted rather than reasoned about, because "inherited" is a property of
    how the validator was declared and a later lane could redeclare it.
    """

    class _Subclass(EgressBinding):
        """A lane's attempt at an admitting variant."""

    with pytest.raises(ValidationError, match="no model call"):
        _Subclass(
            spans=(),
            account=_ACCOUNT,
            transport_endpoint=_ENDPOINT,
            planned_with_external_content=False,
            coverage=SpanCoverage.PATH_WITHOUT_MODEL,
        )


# --- §4's sixth clause: `authorises` compares it with the rest of the binding ----


def test_authorises_answers_false_across_this_field_alone() -> None:
    """§15's second representative input, and the case that fails a left-out field.

    Two decisions differing in ``coverage`` **alone** — same tool, same parameters,
    same step, same execution, same spans, same destinations, one
    ``MODEL_ON_EVERY_PATH`` and one ``NOT_COVERED`` — do not authorise each other's
    requests. §15 names why this case has to exist: the altered-body and edit cases
    both move ``parameters_digest``, so an implementation that left ``coverage`` out of
    §4's whole-binding comparison would pass them both and only this one fails it.

    **No conjunct was added for it and none may be** (§4's sixth clause). The binding
    is compared whole and by value (ADR-0150 §9), so the field is compared because it
    is a member — which is also why the digests below are asserted equal: nothing but
    the binding can be making the comparison fail.
    """
    approved = ActionRequest(
        tool=_TOOL,
        parameters={"body": "hi"},
        step_id="step-1",
        execution_id="exec-1",
        egress_binding=_binding(SpanCoverage.MODEL_ON_EVERY_PATH, _span()),
    )
    offered = ActionRequest(
        tool=_TOOL,
        parameters={"body": "hi"},
        step_id="step-1",
        execution_id="exec-1",
        egress_binding=_binding(SpanCoverage.NOT_COVERED, _span()),
    )
    recorded = PermissionDecision.from_request(
        approved,
        PermissionRuling(outcome=PermissionOutcome.ALLOW, reason="a rule allowed it"),
        id="d-1",
        decided_at=_AT,
    )

    assert recorded.authorises(approved) is True, "the baseline: the same call is authorised"
    assert recorded.authorises(offered) is False
    assert offered.parameters_digest == approved.parameters_digest, (
        "the digests agree, so the binding is the only thing the comparison can refuse on"
    )


def test_the_carrier_writes_the_bindings_value_unchanged() -> None:
    """§4's fourth clause: the seam writes the binding's value from the carrier's.

    ``CarriedProvenance`` holds the fact the seam cannot compute, exactly as it holds
    the discloser mapping and ``planned_with_external_content``; the seam transcribes
    it rather than deriving anything. What `core` can pin is that the carrier accepts
    each state the binding can carry and holds it unchanged — the transcription itself
    is ``tools/egress_binder``'s and is pinned in its own contract suite.

    ``PATH_WITHOUT_MODEL`` is included deliberately: the **carrier** must be able to
    hold it, because a component holding no recorded origin states it (§4) and the
    refusal is the *binding*'s, one step later. A carrier that refused it would move
    §6's refusal to the wrong seam and hide it from the ``EgressBindingError`` the
    caller is given.
    """
    for coverage in _STRONGEST_LAST:
        carrier = CarriedProvenance(
            spans={}, planned_with_external_content=False, coverage=coverage
        )
        assert carrier.coverage is coverage


# --- §4's seventh clause, ADR-0178 §6: the shape that crosses the wire -----------


def test_the_confirmation_shape_carries_the_transcribed_state_across_the_wire() -> None:
    """§4's seventh clause and ADR-0178 §6's rule, over the projection a peer receives.

    ``ConfirmationEgress`` is what crosses — on ``TurnOutcome.step.confirmation`` and
    as the element type of ``pending_confirmations`` — and ``wire/codec``'s ``project``
    renders a model by ``model_dump()``, every field included. So the member is on the
    wire on every egress confirmation, which is the arithmetic behind
    ``PROTOCOL_VERSION`` moving (pinned beside the constant in
    ``tests/core/test_engine_surface_closure.py``).

    The value crosses as the enum's **spelling**, because ``project`` renders every
    ``Enum`` as its ``value`` — the same route ``DiscloserProvenance`` takes on the
    spans this model already carries, so no row is added to ADR-0087 §2c's scalar
    table.

    And it round-trips **equal** through an adapter of the type a client decodes into,
    which is what makes the member a transcription rather than a second carriage: the
    far end reconstructs the state the recorded decision held and nothing derives it
    there.
    """
    egress = ConfirmationEgress(
        account_identity=_ACCOUNT.identity,
        spans=(
            EgressSpan(
                argument="to",
                provenance=DiscloserProvenance.SYSTEM_SELECTED,
                extent=len("a@example.com"),
                destination=EgressDestination(
                    protocol=DestinationProtocol.SMTP,
                    supplied="a@example.com",
                    canonical="a@example.com",
                ),
            ),
        ),
        planned_with_external_content=False,
        coverage=SpanCoverage.MODEL_ON_EVERY_PATH,
    )
    confirmation = Confirmation(
        tool_id="smtp",
        tool_description="Send an email.",
        parameters={"to": "a@example.com"},
        reason="the policy wants a human answer",
        token=ContinuationToken(handle="h-1"),
        egress=egress,
    )

    projected = project(confirmation)
    decoded = TypeAdapter(Confirmation).validate_python(projected)

    assert projected["egress"]["coverage"] == "model_on_every_path"
    assert decoded == confirmation
    assert decoded.egress is not None
    assert decoded.egress.coverage is SpanCoverage.MODEL_ON_EVERY_PATH


def test_a_peer_that_omits_the_member_is_refused_rather_than_defaulted() -> None:
    """ADR-0178 §6's rule seen from the decoding side: this is why the version moved.

    The member is required with no default and ``ConfirmationEgress`` sets
    ``extra="forbid"``, so the bump bites in **both** directions — a new client
    decoding an old hub's confirmation fails with ``missing``, and an old client
    decoding a new hub's fails with ``extra_forbidden``. Half of that pair is what a
    default would silently convert into a fabricated ``NOT_COVERED`` on the surface
    where a user is being asked to approve something.
    """
    whole = {
        "account_identity": _ACCOUNT.identity,
        "spans": [],
        "planned_with_external_content": False,
        "coverage": "not_covered",
    }
    adapter = TypeAdapter(ConfirmationEgress)

    assert adapter.validate_python(whole).coverage is SpanCoverage.NOT_COVERED

    with pytest.raises(ValidationError, match="coverage"):
        adapter.validate_python(
            {name: value for name, value in whole.items() if name != "coverage"}
        )
