"""ADR-0254's ten `core` types, and every refusal true of a persisted row.

The **model validators** ADR-0254 §1's division of refusals assigns to the type —
rules true of *every state a row is ever persisted in*. The two other kinds are
elsewhere by that same division and are named here so their absence does not read
as a gap:

* a rule about the state a row may be **first written in**, and every rule
  comparing **two rows**, is the store's, at ``record`` and ``settle``
  (``tests/permissions/goal_authorization_contract.py``);
* a rule comparing a basis against a **recorded turn** — §8's *"``span`` is a span
  of that turn's own ``TurnResult.utterance``"* and §9 clause (i)'s *"``act`` names
  a recorded turn"* — is ``orchestration``'s, which is ADR-0254 §20's **Lane 2**
  and not this one. §1 puts it there in terms: *"No `core` type reads a store, a
  trail or a turn"*, which is golden rule 2.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Final

import pytest
from pydantic import ValidationError

from ai_assistant.core.config import Settings
from ai_assistant.core.types import (
    ActionRequest,
    Authorization,
    AuthorizationBasis,
    AuthorizationDisposition,
    AuthorizationOrigin,
    AuthorizationSettlement,
    BoundKind,
    CoverageMember,
    PermissionOutcome,
    PermissionRuling,
    ResolutionRule,
    ToolDefinition,
    ValueBound,
    ValueResolution,
    canonical_json_bytes,
)
from ai_assistant.testing import (
    AUTHORIZATION_PROPOSED_AT,
    AUTHORIZATION_TOOL,
    authorization,
    authorization_basis,
    coverage_member,
    money_bound,
    opening_act,
    period_bound,
    terms_bound,
)

LATER = AUTHORIZATION_PROPOSED_AT + timedelta(hours=1)


# --- the vocabularies are closed (§1, §2, §8, §16) ---------------------------


def test_the_four_vocabularies_are_closed_at_the_membership_the_adr_fixes() -> None:
    """§1, §2, §8 and §16 each close an enumeration at a stated membership.

    Pinned by **value** and not only by count, because the values are what cross a
    wire and what a stored row decodes from: each is *"valued by lower-cased member
    name"* and each *"is added to and never renamed"*.
    """
    assert [member.value for member in AuthorizationDisposition] == [
        "proposed",
        "established",
        "declined",
        "expired",
        "revoked",
        "superseded",
    ]
    assert [member.value for member in AuthorizationOrigin] == ["confirmed", "opening_act"]
    assert [member.value for member in AuthorizationSettlement] == [
        "settled",
        "not_at_source",
        "would_duplicate",
        "no_such_authorization",
    ]
    assert [member.value for member in BoundKind] == ["money", "period", "terms"]
    assert [member.value for member in ResolutionRule] == [
        "as_stated",
        "date_from_context",
        "from_shown_record",
    ]


def test_the_field_list_is_closed_and_a_lane_adding_a_member_is_changing_the_decision() -> None:
    """§1: *"The field list is **closed**"*, so a thirteenth field is a red test."""
    assert set(Authorization.model_fields) == {
        "id",
        "goal",
        "tool",
        "account",
        "destinations",
        "origin",
        "coverage",
        "proposed_at",
        "expires_at",
        "confirmation",
        "supersedes",
        "disposition",
        "settled_at",
    }


# --- §2: a member fixes a value or states a bound, and there is no third kind -


def test_a_member_carrying_both_a_fixed_value_and_a_bound_is_not_constructible() -> None:
    """§2: a model validator admits exactly two shapes."""
    with pytest.raises(ValidationError, match="fixes a value or states a bound"):
        CoverageMember(
            argument="amount",
            fixed="60",
            bound=money_bound(),
            basis=authorization_basis(),
        )


def test_a_member_carrying_neither_is_not_constructible() -> None:
    """§2: *"one that does neither records nothing the user said"*."""
    with pytest.raises(ValidationError, match="fixes a value or states a bound"):
        CoverageMember(argument="amount", basis=authorization_basis())


def test_a_member_without_a_basis_is_not_constructible() -> None:
    """§9 clause (i): *"a member without one is not constructible"* (arm 21).

    The **type's** half of that clause. Its other two arms — a basis whose ``act``
    names no recorded turn, and one whose ``span`` is not a span of that turn's
    ``TurnResult.utterance`` — compare a basis against a **store** and are
    ``orchestration``'s, which §1's division of refusals states in terms.
    """
    with pytest.raises(ValidationError):
        CoverageMember.model_validate({"argument": "amount", "fixed": "60"})


def test_no_two_members_of_one_row_name_the_same_argument() -> None:
    """§2: *"A precedence rule between two members about one argument is a rule
    somebody would have to remember at the comparison"*."""
    with pytest.raises(ValidationError, match="same argument"):
        authorization(
            coverage=(
                coverage_member("amount", fixed="60"),
                coverage_member("amount", bound=money_bound()),
            )
        )


# --- §2: the three bound kinds, and every other shape refused ----------------


#: The arguments each :class:`BoundKind` takes, keyed by kind — ADR-0254 §2's own
#: enumeration, written once so the two directions of the validator's rule are
#: tested against one statement of it rather than two.
_ARGUMENTS_OF: Final[dict[BoundKind, dict[str, object]]] = {
    BoundKind.MONEY: {
        "currency": "GBP",
        "currency_argument": "currency",
        "maximum": Decimal("60"),
    },
    BoundKind.PERIOD: {
        "starts_at": AUTHORIZATION_PROPOSED_AT,
        "ends_at": LATER,
        "timezone": "Europe/London",
    },
    BoundKind.TERMS: {"terms": ("flexible",)},
}


@pytest.mark.parametrize(
    ("kind", "kwargs"),
    [
        (BoundKind.MONEY, {"terms": ("flexible",)}),
        (BoundKind.MONEY, {"starts_at": AUTHORIZATION_PROPOSED_AT}),
        (BoundKind.PERIOD, {"maximum": Decimal("60")}),
        (BoundKind.TERMS, {"currency": "GBP"}),
    ],
)
def test_a_bound_carrying_an_argument_its_kind_does_not_take_is_refused(
    kind: BoundKind, kwargs: dict[str, object]
) -> None:
    """§2: the validator is stated in both directions, per kind."""
    with pytest.raises(ValidationError, match="bound"):
        ValueBound.model_validate({"kind": kind, **_ARGUMENTS_OF[kind], **kwargs})


@pytest.mark.parametrize(
    ("kind", "missing"),
    [
        (BoundKind.MONEY, "currency"),
        (BoundKind.MONEY, "currency_argument"),
        (BoundKind.MONEY, "maximum"),
        (BoundKind.PERIOD, "starts_at"),
        (BoundKind.PERIOD, "ends_at"),
        (BoundKind.PERIOD, "timezone"),
        (BoundKind.TERMS, "terms"),
    ],
)
def test_a_bound_missing_an_argument_its_kind_takes_is_refused(
    kind: BoundKind, missing: str
) -> None:
    """§2: every argument that kind takes is present, ``minimum`` alone excepted."""
    stated = dict(_ARGUMENTS_OF[kind])
    del stated[missing]
    with pytest.raises(ValidationError, match="states its"):
        ValueBound.model_validate({"kind": kind, **stated})


def test_a_money_bound_takes_an_optional_minimum_and_refuses_one_above_its_maximum() -> None:
    """§2: ``minimum`` is *"less than or equal to ``maximum``"*."""
    assert money_bound("60", minimum="10").minimum == Decimal("10")
    with pytest.raises(ValidationError, match="minimum is at most its maximum"):
        money_bound("10", minimum="60")


@pytest.mark.parametrize(
    ("amount", "reason"), [("Infinity", "finite"), ("NaN", "finite"), ("-1", "negative")]
)
def test_a_money_bounds_amounts_take_tool_costs_two_refusals(amount: str, reason: str) -> None:
    """§2: ``ToolCost``'s refusals, *"reused rather than restated"*.

    *"``Decimal`` admits ``Infinity`` and ``NaN``, neither of which has a JSON
    representation or survives arithmetic in a running total, and comparing ``NaN``
    with ``<`` raises rather than answering."*

    **The non-finite half is refused by pydantic's own ``Decimal`` handling before
    the model validator runs**, which is ``ToolCost``'s situation unchanged: the
    explicit check is the belt-and-braces that type already carries, and what this
    asserts is the **refusal**, not which layer produced it.
    """
    with pytest.raises(ValidationError, match=reason):
        money_bound(amount)
    with pytest.raises(ValidationError, match=reason):
        money_bound("60", minimum=amount)


@pytest.mark.parametrize("code", ["gbp", "GB", "GBPP", "G8P", ""])
def test_a_money_bounds_currency_is_iso_4217_shaped_and_is_not_normalised(code: str) -> None:
    """§2: three uppercase ASCII letters, validated for **shape** and not a register."""
    with pytest.raises(ValidationError, match="three uppercase ASCII letters"):
        money_bound(currency=code)


def test_a_period_bound_is_half_open_and_refuses_an_empty_interval() -> None:
    """§2: ``ends_at`` **strictly after** ``starts_at``; ADR-0194 §1's convention."""
    assert period_bound(starts_at=AUTHORIZATION_PROPOSED_AT, ends_at=LATER).ends_at == LATER
    with pytest.raises(ValidationError, match="ends strictly after it starts"):
        period_bound(starts_at=LATER, ends_at=LATER)


@pytest.mark.parametrize("zone", ["Mars/Olympus", "UTC+1", "+01:00", "Europe/Nowhere"])
def test_a_period_bounds_timezone_is_a_name_the_tz_database_knows(zone: str) -> None:
    """§4 reads a calendar date as the start of that day *in the bound's own zone*.

    A name nothing resolves would make that reading unavailable at the one
    comparison that decides whether a call is authorised, and §4's answer to an
    unproven comparison is to refuse rather than to guess.
    """
    with pytest.raises(ValidationError, match="IANA zone name"):
        period_bound(timezone=zone)


def test_a_terms_bound_is_non_empty_duplicate_free_and_keeps_the_users_order() -> None:
    """§2: the set the user named, and membership is equality of stored characters."""
    assert terms_bound("free cancellation", "flexible").terms == (
        "free cancellation",
        "flexible",
    )
    with pytest.raises(ValidationError, match="at least one term"):
        terms_bound()
    with pytest.raises(ValidationError, match="each term once"):
        terms_bound("flexible", "flexible")


# --- §8, §10: the resolution admits exactly three shapes ---------------------


def test_as_stated_carries_neither_argument() -> None:
    """§8, arm 34."""
    assert ValueResolution(rule=ResolutionRule.AS_STATED).now is None
    with pytest.raises(ValidationError, match="carries no"):
        ValueResolution(rule=ResolutionRule.AS_STATED, now=AUTHORIZATION_PROPOSED_AT)
    with pytest.raises(ValidationError, match="carries no"):
        ValueResolution(rule=ResolutionRule.AS_STATED, record="rec-1")


@pytest.mark.parametrize("absent", ["now", "timezone"])
def test_date_from_context_requires_both_its_arguments(absent: str) -> None:
    """§8: *"both required and neither absent"* — the inputs the resolution used."""
    kwargs: dict[str, object] = {
        "now": AUTHORIZATION_PROPOSED_AT,
        "timezone": "Europe/London",
    }
    del kwargs[absent]
    with pytest.raises(ValidationError, match="states its"):
        ValueResolution.model_validate({"rule": ResolutionRule.DATE_FROM_CONTEXT, **kwargs})


def test_from_shown_record_requires_the_record_it_resolved_to() -> None:
    """§8, §10: the id of a record the loop put in front of the user on that turn."""
    assert ValueResolution(rule=ResolutionRule.FROM_SHOWN_RECORD, record="rec-1").record == "rec-1"
    with pytest.raises(ValidationError, match="states its"):
        ValueResolution(rule=ResolutionRule.FROM_SHOWN_RECORD)


def test_a_basis_keeps_both_halves_and_neither_is_derivable_from_the_other() -> None:
    """§8: the words the user said **and** the value the system took them to mean."""
    basis = AuthorizationBasis(
        act="turn-9",
        span="up to fifty pounds",
        resolution=ValueResolution(
            rule=ResolutionRule.DATE_FROM_CONTEXT,
            now=AUTHORIZATION_PROPOSED_AT,
            timezone="Europe/London",
        ),
    )
    assert (basis.act, basis.span) == ("turn-9", "up to fifty pounds")
    assert basis.resolution.now == AUTHORIZATION_PROPOSED_AT


def test_a_period_bounds_zone_and_a_resolutions_zone_are_two_facts() -> None:
    """§8: *"neither is derived from the other"*, and nothing requires them equal.

    A configuration changed after the act leaves the record saying what it said,
    which is ADR-0193 §9's prospectivity in the one place a zone could otherwise be
    re-read.
    """
    member = coverage_member(
        "stay_from",
        bound=period_bound(timezone="Europe/London"),
        basis=authorization_basis(
            resolution=ValueResolution(
                rule=ResolutionRule.DATE_FROM_CONTEXT,
                now=AUTHORIZATION_PROPOSED_AT,
                timezone="Australia/Sydney",
            )
        ),
    )
    row = authorization(coverage=(member,))
    assert row.coverage[0].bound is not None
    assert row.coverage[0].bound.timezone == "Europe/London"
    assert row.coverage[0].basis.resolution.timezone == "Australia/Sydney"


# --- §1, §12: the row's own invariants ---------------------------------------


def test_a_proposed_row_states_no_settled_at_and_a_settled_one_states_one() -> None:
    """§1: ``settled_at`` is present **exactly** on a row whose disposition is not
    ``PROPOSED``, stated in both directions."""
    with pytest.raises(ValidationError, match="has not been settled"):
        authorization(disposition=AuthorizationDisposition.PROPOSED, settled_at=LATER)
    with pytest.raises(ValidationError, match="states the instant it was settled"):
        Authorization.model_validate(
            {
                **authorization().model_dump(),
                "disposition": AuthorizationDisposition.ESTABLISHED,
                "settled_at": None,
            }
        )


def test_a_row_expiring_at_or_before_it_was_proposed_is_not_constructible() -> None:
    """§12, on ADR-0193 §9: *"a grant in shape and nothing in effect"*.

    **This is also what refuses a path-(ii) correction of a lapsed row** (arm 42): a
    correction transcribes the superseded row's ``expires_at``, so one recorded
    after that instant would be born expired — and the refusal falls out of the type
    without the store reading a clock.
    """
    for expires_at in (AUTHORIZATION_PROPOSED_AT, AUTHORIZATION_PROPOSED_AT - timedelta(hours=1)):
        with pytest.raises(ValidationError, match="expires strictly after it was proposed"):
            authorization(expires_at=expires_at)


def test_an_opening_act_that_fixed_nothing_is_not_constructible() -> None:
    """§1: path (iii)'s invariant — a row carrying **neither** pointer carries a
    **non-empty** coverage (arm 64)."""
    with pytest.raises(ValidationError, match="opening act that fixed nothing"):
        opening_act(coverage=())


def test_an_empty_coverage_is_constructible_on_a_path_one_proposal() -> None:
    """§1: an empty ``coverage`` *"is only ever a path-(i) proposal about an
    argument-free call"* (arm 54)."""
    assert authorization(coverage=()).coverage == ()


def test_a_coverage_member_naming_a_system_supplied_argument_is_not_constructible() -> None:
    """§3: *"A row's coverage names no system-supplied argument"* (arm 68).

    The row embeds the declaration whole, so both facts are on the row — a **model
    validator**, by §1's division of refusals.
    """
    declared = AUTHORIZATION_TOOL.model_copy(update={"system_supplied": ("idempotency_key",)})
    with pytest.raises(ValidationError, match="names no system-supplied argument"):
        authorization(
            tool=declared,
            coverage=(coverage_member("idempotency_key", fixed="abc"),),
        )


def test_a_money_bound_and_a_fixed_currency_member_of_one_row_must_agree() -> None:
    """§2, arm 18: *"a row that bounds sixty pounds and fixes the currency to
    something else is not a record of anything the user said"*."""
    with pytest.raises(ValidationError, match=r"fixes .* to that same currency"):
        authorization(
            coverage=(
                coverage_member("amount", bound=money_bound(currency="GBP")),
                coverage_member("currency", fixed="KWD"),
            )
        )
    agreeing = authorization(
        coverage=(
            coverage_member("amount", bound=money_bound(currency="GBP")),
            coverage_member("currency", fixed="GBP"),
        )
    )
    assert len(agreeing.coverage) == 2


def test_the_destination_set_takes_adr_0193s_canonical_tuple_by_the_same_validator() -> None:
    """§1: non-empty, duplicate-free, in the one canonical order."""
    with pytest.raises(ValidationError, match="at least one canonical destination"):
        authorization(destinations=())


# --- §7: the subject digest --------------------------------------------------


def test_the_subject_digest_is_taken_over_exactly_the_five_fields_section_7_names() -> None:
    """§7: *"the canonical form of the ``Authorization``'s ``goal``, ``tool``,
    ``account``, ``destinations`` and ``coverage``"*.

    A **selection** rather than a removal, which is where it departs from
    ``RecipientGrant.subject_digest``. Pinned off ``model_fields`` so a field added
    later without deciding its place is a red test rather than a silent inclusion or
    exclusion.
    """
    subject = {"goal", "tool", "account", "destinations", "coverage"}
    outside = set(Authorization.model_fields) - subject
    assert outside == {
        "id",
        "origin",
        "proposed_at",
        "expires_at",
        "confirmation",
        "supersedes",
        "disposition",
        "settled_at",
    }
    row = authorization(id="a1")
    for name, value in (
        ("id", "a2"),
        ("origin", AuthorizationOrigin.OPENING_ACT),
        ("expires_at", LATER + timedelta(days=9)),
        ("confirmation", "confirm-9"),
        ("supersedes", "a0"),
    ):
        moved = Authorization.model_validate({**row.model_dump(), name: value})
        assert moved.subject_digest == row.subject_digest, name


def test_settling_a_proposal_leaves_its_subject_digest_where_it_was() -> None:
    """§7: the settled row fingerprints exactly as the proposal did.

    That is what lets the policy compute the digest from the record ``live_for``
    returned and the trail **recompute** it from the record ``resolve`` returns.
    """
    proposal = authorization()
    settled = Authorization.model_validate(
        {
            **proposal.model_dump(),
            "disposition": AuthorizationDisposition.ESTABLISHED,
            "settled_at": LATER,
        }
    )
    assert settled.subject_digest == proposal.subject_digest


@pytest.mark.parametrize("name", ["goal", "coverage"])
def test_moving_a_subject_field_moves_the_digest(name: str) -> None:
    """§7: a mismatch is conclusive — *"this record is not the one the row rested on"*."""
    row = authorization()
    moved = {
        "goal": "goal-0002",
        "coverage": (coverage_member("amount", fixed="60"),),
    }[name]
    other = Authorization.model_validate({**row.model_dump(), name: moved})
    assert other.subject_digest != row.subject_digest


def test_the_digest_survives_a_serialisation_round_trip() -> None:
    """§7: the two sides of the comparison are a decision read back out of a trail
    and a row read back out of a store."""
    row = authorization()
    assert Authorization.model_validate_json(row.model_dump_json()).subject_digest == (
        row.subject_digest
    )


# --- §6, §7: the three new fields --------------------------------------------


def test_a_ruling_scoping_a_goal_it_names_no_authorisation_for_is_refused() -> None:
    """§7: *"a scope for an authorisation the row names none of is incoherent"*.

    The same shape and the same reason as ``authorised_subject``'s refusal.
    """
    with pytest.raises(ValidationError, match="scopes none"):
        PermissionRuling(
            outcome=PermissionOutcome.ALLOW,
            reason="because",
            authorised_goal="goal-0001",
        )


def test_the_converse_is_not_required_because_three_routes_carry_no_goal_scope() -> None:
    """§7: a route-(a), route-(b) or route-(c) ``ALLOW`` sets a pointer and no scope."""
    ruling = PermissionRuling(
        outcome=PermissionOutcome.ALLOW, reason="because", authorised_by="dec-1"
    )
    assert ruling.authorised_goal is None


def test_an_action_request_carries_no_goal_unless_orchestration_sets_one() -> None:
    """§6: ``goal`` defaults to ``None``, and such a request reaches route (d) in no
    case — the fail-closed direction."""
    assert ActionRequest(tool=AUTHORIZATION_TOOL).goal is None
    assert ActionRequest(tool=AUTHORIZATION_TOOL, goal="goal-0001").goal == "goal-0001"


def test_a_declaration_classifies_nothing_system_supplied_by_default() -> None:
    """§3: the empty tuple makes the **opposite** claim to the one ADR-0016 §1 refuses.

    An unclassified argument is **user-facing**, so a declaration that says nothing
    needs coverage for every argument and asks where it has none: *"It costs a
    question and can never authorise a call"*.
    """
    assert AUTHORIZATION_TOOL.system_supplied == ()
    assert ToolDefinition.model_fields["system_supplied"].default == ()


def test_a_declaration_classifies_each_key_system_supplied_once() -> None:
    """§3: duplicate-free — *"a duplicate is a second spelling of one classification"*."""
    with pytest.raises(ValidationError, match="each key system-supplied once"):
        ToolDefinition.model_validate(
            {**AUTHORIZATION_TOOL.model_dump(), "system_supplied": ("locale", "locale")}
        )


# --- §3: one canonical encoding, and it is the digest's ----------------------


def test_the_fixed_value_comparison_reads_the_encoding_the_digest_is_taken_over() -> None:
    """§3: *"there is one canonical form in this system and not a second"* (arm 7).

    ``==`` on the values will not do, and this is why: Python compares ``1`` equal
    to ``1.0`` and ``True`` equal to ``1``, while their canonical encodings differ —
    so a comparison over ``==`` would cover a call the user's act did not.
    """
    one: object = 1
    assert one == 1.0
    assert canonical_json_bytes(1) != canonical_json_bytes(1.0)
    assert one == True  # noqa: E712 — the loose comparison is the point
    assert canonical_json_bytes(True) != canonical_json_bytes(1)
    assert canonical_json_bytes("60") != canonical_json_bytes(60)


# --- §12, ADR-0256 §2: Settings gains nothing --------------------------------


def test_settings_carries_no_authorization_field_at_all() -> None:
    """§12 and ADR-0256 §2, arm 69's ``Settings`` limb, in ADR-0178 §10's shape.

    *"No field is added, no default about an authorization is minted, no ceiling is
    placed on rung 1 or rung 2, and there is **no sentinel, no 'forever' spelling
    and no disable spelling**."* ADR-0254 §20's *"no ``Settings`` field at all"*
    binds every implementing lane unchanged.

    The one deployment value ADR-0256 §1's rung 3 reads is ``episode_retention``,
    which ADR-0074 §7 already owns — it is read by ``orchestration`` at the write
    and by no store, no policy and no trail.
    """
    named = {
        name
        for name in Settings.model_fields
        if any(word in name for word in ("authoriz", "authoris"))
    }
    assert named == set(), named
    assert "episode_retention" in Settings.model_fields


# --- the cost this shape carries, said rather than discovered ----------------


def test_a_fixed_value_of_json_null_is_not_representable_and_leaves_the_argument_uncovered() -> (
    None
):
    """§2 closes the field list at ``fixed: FrozenJsonValue | None``.

    ``None`` is that field's spelling of *"states a bound instead"*, so an act that
    fixed JSON ``null`` mints **no member** — and §3's per-argument rule then leaves
    that argument **uncovered**, which is the fail-closed direction: the user is
    asked about the concrete call.

    Recorded as a test rather than left to be discovered, because the alternative
    reading — that such a member is constructible — is the one a lane would reach
    for and it is not available.
    """
    with pytest.raises(ValidationError, match="fixes a value or states a bound"):
        coverage_member("note", fixed=None)


def test_an_authorization_round_trips_through_json_in_every_disposition() -> None:
    """Every persisted state decodes (arm 38's type half).

    The store's own round-trip arms are
    ``tests/permissions/goal_authorization_contract.py``'s; this is the type's, and
    it is what makes *"``resolve``, ``recent`` and ``export`` must return every row
    whatever its disposition"* a property of the model rather than of one store.
    """
    for disposition in AuthorizationDisposition:
        settled = None if disposition is AuthorizationDisposition.PROPOSED else LATER
        row = authorization(disposition=disposition, settled_at=settled)
        assert Authorization.model_validate_json(row.model_dump_json()) == row


def test_an_utc_instant_is_required_and_a_naive_one_is_refused() -> None:
    """The store is durable *and* ordered, so a naive instant is refused at the type."""
    with pytest.raises(ValidationError):
        authorization(proposed_at=datetime(2026, 9, 13, 9, 0))  # noqa: DTZ001 — the point


def test_the_default_builder_reads_as_the_worked_case_the_adr_is_about() -> None:
    """A sanity pin on the fixture every other case varies from."""
    row = authorization()
    assert row.disposition is AuthorizationDisposition.PROPOSED
    assert row.origin is AuthorizationOrigin.CONFIRMED
    assert row.proposed_at.tzinfo is UTC
    assert row.coverage[0].bound is not None
    assert row.coverage[0].bound.maximum == Decimal("60")
