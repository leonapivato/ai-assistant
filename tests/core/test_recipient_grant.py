"""``RecipientGrant``: its validators, its digest, and its one construction path.

ADR-0193 §1's record and §2's builder, tested where they live. Everything here is
decidable from ``core`` alone — no store, no seam, no clock — which is the
property §2 gives as its reason for putting the builder on the record rather than
in ``permissions/``: it is a *constructor* of a shared value, and the conditions
it refuses are the ones under which the record would misdescribe itself.

The store-side rules (the duplicate-subject refusal, the count ceiling,
revocation, liveness, precedence) are ``tests/permissions/``'s, and the
enforcement points that consume this record — ``ActionPolicy.decide`` and
``AuditTrail.record`` — are tested there too.
"""

from __future__ import annotations

import inspect
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from pydantic import ValidationError

from ai_assistant.core.types import (
    ActionRequest,
    BoundAccount,
    CanonicalDestination,
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
    RecipientGrant,
    Reversibility,
    RiskLevel,
    SpanCoverage,
    ToolCost,
    ToolDefinition,
)

#: Two fixed instants, so every ordering assertion is about the values under test
#: rather than about how fast the suite runs.
AT = datetime(2026, 7, 20, 12, 0, tzinfo=UTC)
LATER = AT + timedelta(minutes=5)

#: When a grant stops being live, comfortably after both instants above.
EXPIRES = AT + timedelta(days=1)

ACCOUNT = BoundAccount(identity="work@example.com", reference="conn-0001")
OTHER_ACCOUNT = BoundAccount(identity="work@example.com", reference="conn-0002")

ENDPOINT = "test://endpoint/one"


def _tool(**overrides: object) -> ToolDefinition:
    """A transmitting declaration: side-effecting, disclosing, at a known cost."""
    fields: dict[str, object] = {
        "id": "send_email",
        "capability": "send_email",
        "description": "Send an email.",
        "risk_level": RiskLevel.LOW,
        "reversibility": Reversibility.IRREVERSIBLE,
        "side_effecting": True,
        "reads": (),
        "writes": (),
        "discloses": (DataTier.PERSONAL,),
        "cost": ToolCost(basis=CostBasis.FREE),
        "idempotency": Idempotency.NONE,
    }
    fields.update(overrides)
    return ToolDefinition(**fields)  # type: ignore[arg-type]  # heterogeneous test kwargs


def _member(canonical: str) -> CanonicalDestination:
    """One selected-recipient member of a canonical destination set."""
    return CanonicalDestination(protocol=DestinationProtocol.SMTP, canonical=canonical)


def _span(supplied: str, index: int) -> EgressSpan:
    """One span selecting ``supplied``, canonicalised as ADR-0148 §2's SMTP rule does."""
    return EgressSpan(
        argument="to",
        index=index,
        provenance=DiscloserProvenance.SYSTEM_SELECTED,
        extent=len(supplied),
        destination=EgressDestination(
            protocol=DestinationProtocol.SMTP, supplied=supplied, canonical=supplied.lower()
        ),
    )


def _binding(
    *supplied: str,
    account: BoundAccount = ACCOUNT,
    external: bool = False,
) -> EgressBinding:
    """A whole binding selecting ``supplied``, or none at all where it is empty."""
    return EgressBinding(
        spans=tuple(_span(value, index) for index, value in enumerate(supplied)),
        account=account,
        transport_endpoint=ENDPOINT,
        planned_with_external_content=external,
        coverage=SpanCoverage.NOT_COVERED,
    )


def _request(binding: EgressBinding, **overrides: object) -> ActionRequest:
    """A request carrying ``binding``, with parameters its spans describe."""
    to = [span.destination.supplied for span in binding.spans if span.destination is not None]
    fields: dict[str, object] = {
        "tool": _tool(),
        "parameters": {"to": to} if to else {},
        "egress_binding": binding,
    }
    fields.update(overrides)
    return ActionRequest(**fields)  # type: ignore[arg-type]  # heterogeneous test kwargs


def _confirmation(
    binding: EgressBinding,
    *,
    decision_id: str = "d-confirm",
    at: datetime = AT,
    **overrides: object,
) -> PermissionDecision:
    """A recorded ``CONFIRM`` about a call carrying ``binding``."""
    return PermissionDecision.from_request(
        _request(binding, **overrides),
        PermissionRuling(outcome=PermissionOutcome.CONFIRM, reason="it discloses off-device"),
        id=decision_id,
        decided_at=at,
    )


def _answer(
    confirmed: PermissionDecision,
    *,
    decision_id: str = "d-answer",
    at: datetime = LATER,
    outcome: PermissionOutcome = PermissionOutcome.ALLOW,
    resolves: str | None = None,
) -> PermissionDecision:
    """The recorded decision that answers ``confirmed``.

    Built by hand rather than through ``from_request`` over the same request,
    because several cases need an answer whose ``resolves`` names something other
    than the confirmation it is handed beside — which is exactly the shape §2's
    refusals are about, and which a faithful factory would refuse to produce.
    """
    named = confirmed.id if resolves is None else resolves
    ruling = PermissionRuling(
        outcome=outcome,
        reason="the user approved the confirmation",
        authorised_by=named if outcome is PermissionOutcome.ALLOW else None,
    )
    return confirmed.model_copy(
        update={"id": decision_id, "ruling": ruling, "decided_at": at, "resolves": named}
    )


def _grant(**overrides: object) -> RecipientGrant:
    """A well-formed granting record, overriding whichever field a case is about."""
    fields: dict[str, object] = {
        "id": "g-1",
        "tool": _tool(),
        "account": ACCOUNT,
        "destinations": (_member("alice@example.com"),),
        "decided_at": AT,
        "expires_at": EXPIRES,
        "established_by": "d-confirm",
    }
    fields.update(overrides)
    return RecipientGrant(**fields)  # type: ignore[arg-type]  # heterogeneous test kwargs


# --- §1: the destination set is non-empty, duplicate-free and canonically ordered ---


def test_a_grant_names_at_least_one_destination() -> None:
    """An empty set authorises nothing and is refused at construction (ADR-0193 §1)."""
    with pytest.raises(ValidationError, match="at least one canonical destination"):
        _grant(destinations=())


def test_a_grant_names_each_destination_once() -> None:
    """A duplicate is a second spelling of one authorisation (ADR-0193 §1)."""
    member = _member("alice@example.com")

    with pytest.raises(ValidationError, match="once"):
        _grant(destinations=(member, member))


def test_a_destination_set_out_of_canonical_order_is_refused() -> None:
    """``(Bob, Alice)`` and ``(Alice, Bob)`` cover the same calls (ADR-0193 §1).

    **The pair is the test**: the same two members in the canonical order
    construct, and reversed they do not. Asserting only the refusal would pass
    against an implementation that refused both spellings, and asserting only the
    acceptance would pass against one that accepted both — which is the state the
    clause exists to prevent, because a duplicate refusal over ordinary tuple
    equality then admits two grants that are the same authorisation, and revoking
    one leaves the other standing.
    """
    alice = _member("alice@example.com")
    bob = _member("bob@example.com")

    assert _grant(destinations=(alice, bob)).destinations == (alice, bob)

    with pytest.raises(ValidationError, match="canonical order"):
        _grant(destinations=(bob, alice))


def test_the_account_member_sorts_before_every_selected_recipient() -> None:
    """The order is ``EgressBinding``'s own, adopted rather than invented (ADR-0193 §1)."""
    account = CanonicalDestination(account=ACCOUNT)
    alice = _member("alice@example.com")

    assert _grant(destinations=(account, alice)).destinations == (account, alice)

    with pytest.raises(ValidationError, match="canonical order"):
        _grant(destinations=(alice, account))


def test_a_grants_destination_order_survives_a_json_round_trip() -> None:
    """A record reconstructed from its dump is the record, order included."""
    alice = _member("alice@example.com")
    bob = _member("bob@example.com")
    grant = _grant(destinations=(alice, bob))

    rebuilt = RecipientGrant.model_validate(grant.model_dump(mode="json"))

    assert rebuilt == grant
    assert rebuilt.destinations == (alice, bob)


# --- §1: established_by pairs with the record kind ---------------------------


def test_a_granting_record_names_the_act_it_rode() -> None:
    """A granting record without ``established_by`` names no act (ADR-0193 §1)."""
    with pytest.raises(ValidationError, match="established_by"):
        _grant(established_by=None)


def test_a_revoking_record_names_no_establishing_act() -> None:
    """A revoking record with ``established_by`` claims an establishment it is not."""
    with pytest.raises(ValidationError, match="establishes nothing"):
        _grant(revokes="g-1", established_by="d-confirm")


def test_a_revoking_record_is_well_formed_without_one() -> None:
    """The counterpart, so the pair fails against an implementation refusing both."""
    revocation = _grant(id="r-1", revokes="g-1", established_by=None)

    assert revocation.revokes == "g-1"
    assert revocation.established_by is None


# --- §9: a granting record is live for some duration -------------------------


@pytest.mark.parametrize(
    "expires_at",
    [pytest.param(AT, id="equal"), pytest.param(AT - timedelta(seconds=1), id="before")],
)
def test_a_granting_record_expiring_at_or_before_its_decision_is_refused(
    expires_at: datetime,
) -> None:
    """It authorises nothing while still occupying an outstanding slot (ADR-0193 §9)."""
    with pytest.raises(ValidationError, match="strictly after"):
        _grant(decided_at=AT, expires_at=expires_at)


def test_a_granting_record_expiring_an_instant_later_is_accepted() -> None:
    """The boundary from the other side, so the pair is about the comparison."""
    grant = _grant(decided_at=AT, expires_at=AT + timedelta(microseconds=1))

    assert grant.expires_at > grant.decided_at


@pytest.mark.parametrize(
    "expires_at",
    [
        pytest.param(AT, id="equal to decided_at"),
        pytest.param(AT - timedelta(days=7), id="an expiry long past"),
        pytest.param(EXPIRES, id="ordinary"),
    ],
)
def test_a_revoking_record_is_accepted_at_any_ordering(expires_at: datetime) -> None:
    """A revoking record is never live, so ADR-0193 §1 orders its instants by no rule.

    The middle case is the one that matters: a revocation transcribes the expiry
    of the grant it withdraws, and a user revoking a grant that has *already*
    expired — which they must be able to do, because an expired grant still
    occupies an outstanding slot — hands over exactly this shape.
    """
    revocation = _grant(id="r-1", revokes="g-1", established_by=None, expires_at=expires_at)

    assert revocation.expires_at == expires_at


# --- §1: the subject digest --------------------------------------------------


def test_two_grants_differing_only_in_id_share_a_digest() -> None:
    """``id`` is the one removal, because the digest is checked *against* an id."""
    assert _grant(id="g-1").subject_digest == _grant(id="g-2").subject_digest


@pytest.mark.parametrize(
    ("field", "value"),
    [
        pytest.param("tool", _tool(description="Send an email, politely."), id="tool"),
        pytest.param("account", OTHER_ACCOUNT, id="account"),
        pytest.param("destinations", (_member("bob@example.com"),), id="destinations"),
        pytest.param("decided_at", AT + timedelta(seconds=1), id="decided_at"),
        pytest.param("expires_at", EXPIRES + timedelta(days=365), id="expires_at"),
        pytest.param("established_by", "d-other", id="established_by"),
    ],
)
def test_two_grants_differing_in_any_other_single_field_do_not_share_a_digest(
    field: str, value: object
) -> None:
    """Asserted one field at a time, so no exclusion can survive unnoticed.

    Three of these were wrong in an earlier draft of ADR-0193 and both review
    lenses converged on them at round 10. ``expires_at`` aliased "granted until
    March" with "granted until 2040" into one fingerprint; ``account`` aliased a
    grant over the user's work account with one over their personal one, which
    ``BoundAccount``'s own declaration says "a standing grant would cover a record
    the user never granted" about; and ``established_by`` is round 11's blocker —
    without it, two *legitimate* confirmations a coarse clock stamped alike were
    one fingerprint, so the later grant satisfied the earlier row's digest while
    being a different user act.
    """
    assert _grant().subject_digest != _grant(**{field: value}).subject_digest


def test_the_digest_survives_a_json_round_trip() -> None:
    """The property a stored field would not have had (ADR-0193 §1).

    The two sides of the comparison the digest exists for are a decision read back
    out of a trail and a grant read back out of a store, so a projection taken
    over live objects rather than over their JSON form would fingerprint the
    record differently before and after it was persisted — and every route-(b) row
    would fail its own check on the first restart.
    """
    grant = _grant()

    rebuilt = RecipientGrant.model_validate(grant.model_dump(mode="json"))

    assert rebuilt.subject_digest == grant.subject_digest


def test_a_grant_whose_model_dump_lies_is_digested_on_its_real_field_state() -> None:
    """``model_dump`` is an ordinary attribute, and this digest is a check.

    An instance can shadow the method through ``__dict__`` — the same bypass
    ``frozen=True`` leaves open everywhere else in this module — and a projection
    built by calling it would then fingerprint whatever that mapping described.
    ADR-0193 §6 has ``AuditTrail.record`` **recompute** this value on the grant the
    resolution seam returns and compare it with the row's ``authorised_subject``,
    so a record able to nominate its own digest is a record able to satisfy a row
    it does not match, which is the whole of what the comparison is for.
    """
    grant = _grant()
    elsewhere = _grant(id="g-2", destinations=(_member("bob@example.com"),))
    grant.__dict__["model_dump"] = elsewhere.model_dump

    assert grant.subject_digest != elsewhere.subject_digest
    assert grant.subject_digest == _grant().subject_digest


def test_the_digest_is_a_property_and_not_a_field() -> None:
    """A stored digest can be read back disagreeing with what it was computed from."""
    assert "subject_digest" not in _grant().model_dump()
    assert "subject_digest" not in RecipientGrant.model_fields


def test_the_digest_projection_is_every_field_but_the_id() -> None:
    """The roster, read off ``model_fields`` rather than hand-written (ADR-0193 §1).

    In the shape ``tests/readers/test_calendar_duration_settings.py`` already uses
    for a field set that must not drift unnoticed. ADR-0193 §1 states the rule as a
    **removal from the whole dump** rather than as a list of members, precisely
    because a list goes stale silently the first time a field is added and a
    removal cannot — so a field added to :class:`RecipientGrant` by a later ADR
    without deciding its place in the digest fails here rather than being excluded
    in silence.
    """
    grant = _grant()

    projection: dict[str, Any] = grant._digest_projection()

    assert set(projection) == set(RecipientGrant.model_fields) - {"id"}


# --- §6: PermissionRuling's half of the pairing ------------------------------


def test_a_ruling_naming_no_authorisation_fingerprints_none() -> None:
    """A fingerprint of the authorisation is incoherent on a ruling that names none."""
    with pytest.raises(ValidationError, match="fingerprints none"):
        PermissionRuling(
            outcome=PermissionOutcome.ALLOW,
            reason="fine",
            authorised_subject="0" * 64,
        )


def test_a_route_a_allow_carries_a_pointer_and_no_fingerprint() -> None:
    """The converse is **not** required: route (a) rests on a confirmation.

    Which of the two shapes is *owed* is decided at ``AuditTrail.record``, the only
    component that can see ``resolves`` and ``egress_binding`` (ADR-0193 §6); the
    type can only state the half that is incoherent on its own.
    """
    ruling = PermissionRuling(
        outcome=PermissionOutcome.ALLOW, reason="the user approved", authorised_by="d-confirm"
    )

    assert ruling.authorised_by == "d-confirm"
    assert ruling.authorised_subject is None


def test_a_ruling_may_carry_both() -> None:
    """The route-(b) shape, so the refusal above is about the pairing and not the field."""
    ruling = PermissionRuling(
        outcome=PermissionOutcome.ALLOW,
        reason="a standing grant covers these recipients",
        authorised_by="g-1",
        authorised_subject="0" * 64,
    )

    assert ruling.authorised_subject == "0" * 64


# --- §2: established_from, the one construction path -------------------------


def test_established_from_transcribes_the_subject_from_the_confirmation() -> None:
    """Every field the record describes is copied by ``core`` (ADR-0193 §2).

    Asserted by **equality and not by presence**, and against a fixture in which
    the confirmation's and the answer's ids and instants differ — so an
    implementation reading either value off the wrong decision fails rather than
    passing on a fixture where the two agree. ``decided_at`` is the *answer*'s,
    because it is the instant the user decided; ``established_by`` is the
    *confirmation*'s id, because that is the act the grant rode.
    """
    binding = _binding("Alice@Example.com", "bob@example.com")
    confirmed = _confirmation(binding, decision_id="d-confirm", at=AT)
    answer = _answer(confirmed, decision_id="d-answer", at=LATER)

    grant = RecipientGrant.established_from(confirmed, answer, id="g-1", expires_at=EXPIRES)

    assert grant.id == "g-1"
    assert grant.tool == confirmed.tool
    assert grant.account == binding.account
    assert grant.destinations == binding.canonical_destination_set
    assert grant.established_by == "d-confirm"
    assert grant.decided_at == LATER
    assert grant.expires_at == EXPIRES
    assert grant.revokes is None


def test_established_from_takes_the_subject_by_value() -> None:
    """Mutating either supplied decision afterwards changes nothing (ADR-0193 §2).

    What "by value" means here as it does at ``from_request``: the record is the
    grant's, not the caller's, from the moment it is returned. ``frozen=True``
    refuses the attribute write and does **not** refuse the ``__dict__`` one,
    which is why this is a test rather than a reliance on the config.
    """
    binding = _binding("alice@example.com")
    confirmed = _confirmation(binding)
    answer = _answer(confirmed)

    grant = RecipientGrant.established_from(confirmed, answer, id="g-1", expires_at=EXPIRES)
    before = grant.model_dump(mode="json")
    confirmed.tool.__dict__["description"] = "Send an email, and also everything else."
    confirmed.egress_binding.account.__dict__["reference"] = "conn-9999"  # type: ignore[union-attr]  # a whole binding

    assert grant.model_dump(mode="json") == before


def test_established_from_returns_a_canonically_ordered_set_without_sorting_it() -> None:
    """The value arrives ordered, and nothing here re-sorts or re-canonicalises it.

    ADR-0193 §2's first clause forbids a surface reordering the tuple, and §1's
    validator refuses one that is out of order — so the two meet here: the value
    is ``EgressBinding.canonical_destination_set``, which ``core`` already returns
    sorted, and the builder passes it through untouched. The counterpart below is
    what makes this mechanical rather than a claim: a caller that rebuilt the
    tuple in the order it happened to render it in and constructed the record
    directly is refused by the same validator.
    """
    binding = _binding("bob@example.com", "alice@example.com")
    confirmed = _confirmation(binding)

    grant = RecipientGrant.established_from(
        confirmed, _answer(confirmed), id="g-1", expires_at=EXPIRES
    )

    assert grant.destinations == binding.canonical_destination_set
    assert grant.destinations == tuple(
        sorted(grant.destinations, key=lambda member: str(member.canonical))
    )

    with pytest.raises(ValidationError, match="canonical order"):
        _grant(destinations=tuple(reversed(grant.destinations)))


def test_established_from_accepts_no_parameter_naming_a_subject() -> None:
    """The signature test that makes the transcription unwritable-around (ADR-0193 §2).

    A builder that copied the three subject values correctly **and also accepted
    an override** would pass every other assertion in this file, and §2's whole
    reason for naming a function is that the capability is absent rather than
    forbidden: "that removes the capability rather than forbidding it, which is the
    move ADR-0021 §3 made when it split ``PermissionRuling`` off
    ``PermissionDecision``". Read off ``inspect.signature`` rather than asserted in
    prose, so a subject parameter added later is a **red test** rather than a
    silent widening.
    """
    parameters = set(inspect.signature(RecipientGrant.established_from).parameters)

    assert parameters == {"confirmed", "answer", "id", "expires_at"}


@pytest.mark.parametrize(
    ("case", "make"),
    [
        pytest.param(
            "external content",
            lambda: (_confirmation(_binding("alice@example.com", external=True)), None),
            id="planned over external content",
        ),
        pytest.param(
            "origin never recorded",
            lambda: (
                _confirmation(_binding("alice@example.com")).model_copy(
                    update={
                        "egress_binding": OriginUnrecordedBinding(
                            spans=_binding("alice@example.com").spans,
                            account=ACCOUNT,
                            transport_endpoint=ENDPOINT,
                        )
                    }
                ),
                None,
            ),
            id="origin unrecorded",
        ),
        pytest.param(
            "no egress call",
            lambda: (
                _confirmation(_binding("alice@example.com")).model_copy(
                    update={"egress_binding": None}
                ),
                None,
            ),
            id="no binding",
        ),
    ],
)
def test_established_from_refuses_a_confirmation_it_may_not_establish_from(
    case: str, make: Any
) -> None:
    """§2's content floor, as the function's own preconditions.

    The first two are the pair §2's third clause is about, and they are needed
    beside §4's bar rather than implied by it: §4 stops a grant *covering* a call
    planned over external content, and this stops one being *established* from
    such a call — where the recipients an attacker's content chose become
    standing, and every later call carrying ``False`` then spends the grant with
    §4 satisfied on each of them, because the origin fact is about *that* call and
    is true. The third is structural: a decision with no binding has no account and
    no destination set to transcribe.
    """
    confirmed, _ = make()
    answer = _answer(confirmed)

    with pytest.raises(ValueError, match=r"ADR-0193"):
        RecipientGrant.established_from(confirmed, answer, id="g-1", expires_at=EXPIRES)


def test_established_from_refuses_a_decision_that_was_never_a_confirmation() -> None:
    """A grant rides an answer to a recorded ``CONFIRM`` and to nothing else."""
    binding = _binding("alice@example.com")
    allowed = _confirmation(binding).model_copy(
        update={
            "ruling": PermissionRuling(outcome=PermissionOutcome.ALLOW, reason="no rule applies")
        }
    )

    with pytest.raises(ValueError, match="answer to a recorded CONFIRM"):
        RecipientGrant.established_from(allowed, _answer(allowed), id="g-1", expires_at=EXPIRES)


@pytest.mark.parametrize(
    ("outcome", "resolves", "expected"),
    [
        pytest.param(PermissionOutcome.DENY, None, "approving answer", id="the user declined"),
        pytest.param(PermissionOutcome.ALLOW, "", "resolves", id="resolves unset"),
        pytest.param(PermissionOutcome.ALLOW, "d-other", "resolves", id="resolves another"),
    ],
)
def test_established_from_refuses_an_answer_that_does_not_answer_this_confirmation(
    outcome: PermissionOutcome, resolves: str | None, expected: str
) -> None:
    """The three that separate an *asked* confirmation from an *answered* one.

    No other test in this file reaches it, and without them a pending ``CONFIRM``
    could be handed to the constructor twice over and become a live grant the user
    never assented to — which is round 19's finding, and the reason ADR-0193 §2's
    builder takes **two** decisions rather than one.
    """
    binding = _binding("alice@example.com")
    confirmed = _confirmation(binding)
    answer = (
        _answer(confirmed, outcome=outcome)
        if resolves is None
        else _answer(confirmed, outcome=outcome).model_copy(update={"resolves": resolves or None})
    )

    with pytest.raises(ValueError, match=expected):
        RecipientGrant.established_from(confirmed, answer, id="g-1", expires_at=EXPIRES)


def test_established_from_refuses_rather_than_returning_a_narrowed_grant() -> None:
    """A refusal mints **nothing looser** in its place (ADR-0193 §2).

    Not a grant over the account, not one over a subset, not one over the supplied
    form — the discipline #1548 records OpenClaw stating for a different binding:
    refuse to mint an approval-backed run rather than pretend full coverage. The
    assertion is that the call raises rather than returning anything at all, which
    is the only shape in which "nothing looser" is checkable from outside.
    """
    binding = _binding("alice@example.com", external=True)
    confirmed = _confirmation(binding)

    with pytest.raises(ValueError, match="external content"):
        RecipientGrant.established_from(confirmed, _answer(confirmed), id="g-1", expires_at=EXPIRES)


def test_established_from_applies_the_records_own_validators() -> None:
    """The construction refusals still bind, so the builder cannot route around them."""
    binding = _binding("alice@example.com")
    confirmed = _confirmation(binding)
    answer = _answer(confirmed, at=LATER)

    with pytest.raises(ValidationError, match="strictly after"):
        RecipientGrant.established_from(confirmed, answer, id="g-1", expires_at=LATER)
