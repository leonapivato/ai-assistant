"""What of ADR-0254's `core` vocabulary outlives the goal authorizations.

ADR-0309 §5 deletes the old path, and with it the goal-authorization Protocols, their
contract suites and their canonical fakes. The row family those Protocols stored —
``Authorization``, ``CoverageMember``, ``AuthorizationBasis``, ``ValueResolution`` and
their vocabularies — has no consumer left, so its tests left with the Protocols and the
types follow in their own lane.

What stays is pinned here, each value built locally rather than from a fake that no
longer exists: the bound a user can state (``BoundKind``, ``ValueBound``), the tool
declaration's own refusals (``system_supplied``, ``bounded_arguments``), the fields
``ActionRequest`` and ``PermissionRuling`` still carry, the one canonical encoding, and
``Settings``' absence of any authorization field.
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
    BoundedArgument,
    BoundKind,
    CapabilityEffect,
    CapabilityResult,
    CostBasis,
    DataTier,
    Idempotency,
    PermissionOutcome,
    PermissionRuling,
    Reversibility,
    RiskLevel,
    ToolCost,
    ToolDefinition,
    ValueBound,
    canonical_json_bytes,
)

#: The instant every bound below is stated from.
STARTS_AT: Final = datetime(2026, 9, 13, 9, 0, tzinfo=UTC)
LATER: Final = STARTS_AT + timedelta(hours=1)

#: A declaration that classifies nothing system-supplied and declares no bounded
#: argument, so a case about either field raises it on a copy of this.
TOOL: Final = ToolDefinition(
    id="book_site",
    capability="book_site",
    description="Book a pitch at a campsite through the connected account.",
    risk_level=RiskLevel.LOW,
    reversibility=Reversibility.REVERSIBLE,
    side_effecting=True,
    reads=(),
    writes=(),
    discloses=(DataTier.PERSONAL,),
    cost=ToolCost(basis=CostBasis.FREE),
    idempotency=Idempotency.NONE,
    effect=CapabilityEffect.WORLD,
    leaves_hub=True,
    result=CapabilityResult.NO_OUTSIDE_TEXT,
    outcome_can_be_unknown=True,
    safe_to_repeat=False,
)


def money_bound(
    maximum: str | Decimal = "60",
    *,
    currency: str = "GBP",
    minimum: str | Decimal | None = None,
    maximum_exclusive: bool = False,
) -> ValueBound:
    """A ``MONEY`` bound: at most ``maximum`` of ``currency``, by default inclusive."""
    return ValueBound(
        kind=BoundKind.MONEY,
        currency=currency,
        maximum=Decimal(maximum),
        minimum=None if minimum is None else Decimal(minimum),
        maximum_exclusive=maximum_exclusive,
    )


def period_bound(
    *,
    starts_at: datetime = STARTS_AT,
    ends_at: datetime = STARTS_AT + timedelta(hours=12),
    timezone: str = "Europe/London",
) -> ValueBound:
    """A ``PERIOD`` bound over the half-open interval ``[starts_at, ends_at)``."""
    return ValueBound(
        kind=BoundKind.PERIOD, starts_at=starts_at, ends_at=ends_at, timezone=timezone
    )


def terms_bound(*terms: str) -> ValueBound:
    """A ``TERMS`` bound over the set the user named, in their order."""
    return ValueBound(kind=BoundKind.TERMS, terms=terms)


# --- §2: the vocabulary is closed --------------------------------------------


def test_the_bound_kinds_are_closed_at_the_membership_the_adr_fixes() -> None:
    """§2 closes ``BoundKind`` at three members, pinned by **value** because the
    values are what cross a wire and what a stored row decodes from."""
    assert [member.value for member in BoundKind] == ["money", "period", "terms"]


# --- §2: the three bound kinds, and every other shape refused ----------------


#: The arguments each :class:`BoundKind` takes, keyed by kind — ADR-0254 §2's own
#: enumeration, written once so the two directions of the validator's rule are
#: tested against one statement of it rather than two.
_ARGUMENTS_OF: Final[dict[BoundKind, dict[str, object]]] = {
    BoundKind.MONEY: {"currency": "GBP", "maximum": Decimal("60")},
    BoundKind.PERIOD: {
        "starts_at": STARTS_AT,
        "ends_at": LATER,
        "timezone": "Europe/London",
    },
    BoundKind.TERMS: {"terms": ("flexible",)},
}


@pytest.mark.parametrize(
    ("kind", "kwargs"),
    [
        (BoundKind.MONEY, {"terms": ("flexible",)}),
        (BoundKind.MONEY, {"starts_at": STARTS_AT}),
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


@pytest.mark.parametrize("kind", [BoundKind.PERIOD, BoundKind.TERMS])
def test_a_bound_of_another_kind_carrying_maximum_exclusive_is_refused(kind: BoundKind) -> None:
    """ADR-0266 §3: the flag is ``MONEY``-only, and a ``bool`` is not ``None``.

    Stated as its own refusal because the stray-argument sweep cannot see it: every
    other field of a kind it does not belong to is absent as ``None``, and a flag
    withdrawing a ``maximum`` the bound does not state records nothing (arm 6(b)).
    """
    with pytest.raises(ValidationError, match="no maximum_exclusive"):
        ValueBound.model_validate({"kind": kind, **_ARGUMENTS_OF[kind], "maximum_exclusive": True})


def test_a_money_bound_defaults_to_an_inclusive_ceiling_and_states_a_strict_one() -> None:
    """ADR-0266 §3: *"a ceiling the user stated strictly is representable as one"*.

    **Arm 5 stands verbatim under the new field**, which is the sweep's own finding:
    ``maximum_exclusive`` defaults to ``False``, so every bound written before this
    decision reads exactly as it did.
    """
    assert money_bound("100").maximum_exclusive is False
    assert money_bound("100", maximum_exclusive=True).maximum_exclusive is True


@pytest.mark.parametrize("coercible", ["true", "false", "yes", "no", "on", "off", 0, 1])
def test_a_ceiling_is_not_made_strict_or_inclusive_by_a_value_pydantic_would_coerce(
    coercible: object,
) -> None:
    """ADR-0266 §3 states the flag as *"a ``bool`` defaulting to ``False``"*, and
    lax coercion would make each of these a **different authority** rather than a
    malformed one: ``"false"`` an inclusive ceiling, ``1`` an exclusive one.

    **The one field in this model where that is not harmless**, because ADR-0254 §5
    *orders* it: a correction clearing the flag at an equal ``maximum`` is a
    widening §5 refuses, so a value nobody recorded decides whether the user is
    asked. The browser's ``readBound`` already rejected exactly these shapes on the
    ground that they are states ``ValueBound`` refuses — and it did not, so the
    adapter was holding an invariant the type did not. Adversarial review, round 10,
    ``blocker``.
    """
    with pytest.raises(ValidationError, match="must be a boolean"):
        ValueBound.model_validate(
            {"kind": BoundKind.MONEY, "maximum": "100", "currency": "GBP"}
            | {"maximum_exclusive": coercible}
        )


@pytest.mark.parametrize("stated", [True, False])
def test_a_ceiling_states_either_boolean_and_both_survive_a_round_trip(stated: bool) -> None:
    """The control beside the refusals above: strictness rejects **only** what is
    not a ``bool``, and a bound of either flag decodes from its own JSON unchanged.

    Both directions matter because the flag crosses the wire on every ``MONEY``
    bound, so a refusal reaching a conforming payload would take the whole record
    with it.
    """
    bound = money_bound("100", maximum_exclusive=stated)
    assert ValueBound.model_validate(bound.model_dump(mode="json")).maximum_exclusive is stated


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
    assert period_bound(starts_at=STARTS_AT, ends_at=LATER).ends_at == LATER
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


@pytest.mark.parametrize("zone", ["localtime", "posixrules", "Localtime", "POSIXRULES"])
def test_a_period_bounds_timezone_is_never_the_hosts_own_configuration(zone: str) -> None:
    """§§2 and 4: the zone is **recorded** so that the comparison reads none.

    ``localtime`` and ``posixrules`` resolve through ``ZoneInfo`` on a stock Linux
    install and name the machine rather than a zone — ``localtime`` is a copy of
    whatever the operator configured. A bound recording one would mean a different
    interval on a different host, and a different one on the same host after
    ``timedatectl set-timezone``, while the stored string and the row's
    ``subject_digest`` stayed identical: a calendar date outside the bound could
    start drawing an ``ALLOW`` with no further act of the user's.

    The folded spellings are here because the tz lookup is a **file** lookup: on a
    case-insensitive filesystem they reach the same host-local file, and no IANA
    zone is spelled either way.
    """
    with pytest.raises(ValidationError, match="host's own configuration rather than a zone"):
        period_bound(timezone=zone)


def test_a_period_bounds_timezone_is_still_an_ordinary_iana_name() -> None:
    """The control: the refusal above narrows nothing a user could have meant."""
    for zone in ("UTC", "Europe/London", "Australia/Sydney", "Factory"):
        assert period_bound(timezone=zone).timezone == zone


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


# --- ADR-0266 §7: the declaration's own refusals -----------------------------


def test_a_declaration_declaring_a_system_supplied_key_at_a_kind_is_not_constructible() -> None:
    """ADR-0266 §7, restating §3's protection one field over (arms 68, 6(b)).

    **The rule is preserved and its carrier moved.** §3 made a row whose coverage
    names a system-supplied argument not constructible by reading
    ``CoverageMember.argument``, which no longer exists; a system-supplied key being
    declarable at **no** kind is what keeps *"a user is never asked to approve an
    idempotency key"* true — no member can be met against one, on either route.
    """
    with pytest.raises(ValidationError, match="name no key it fills itself"):
        ToolDefinition.model_validate(
            {
                **TOOL.model_dump(),
                "system_supplied": ("locale",),
                "bounded_arguments": (
                    {"argument": "locale", "kind": "terms", "currency_argument": None},
                ),
            }
        )


@pytest.mark.parametrize(
    ("kind", "currency_argument", "refusal"),
    [
        (BoundKind.MONEY, None, "names the key carrying its currency"),
        (BoundKind.PERIOD, "currency", "carries no currency_argument"),
        (BoundKind.TERMS, "currency", "carries no currency_argument"),
        (BoundKind.MONEY, "amount", "names a second key"),
    ],
    ids=["money-without", "period-with", "terms-with", "one-key-for-both"],
)
def test_a_bounded_argument_of_a_shape_section_seven_does_not_admit_is_refused(
    kind: BoundKind, currency_argument: str | None, refusal: str
) -> None:
    """ADR-0266 §7's two shapes, and arm 6(b)'s enumeration of what neither admits.

    ``MONEY`` **with** a ``currency_argument`` or ``PERIOD``/``TERMS`` **with
    none** — an amount is the only kind §4's readings denominate, and a currency key
    beside a period or a term is a value nothing reads. **And ``argument`` never
    equals ``currency_argument``**: one key cannot carry both the amount and the
    code it is denominated in, and a declaration claiming so would have §4's
    currency conjunct compare an amount against a currency. Adversarial review,
    round 7, ``blocker``.
    """
    with pytest.raises(ValidationError, match=refusal):
        BoundedArgument(argument="amount", kind=kind, currency_argument=currency_argument)


@pytest.mark.parametrize(
    ("kind", "currency_argument"),
    [(BoundKind.MONEY, "currency"), (BoundKind.PERIOD, None), (BoundKind.TERMS, None)],
)
def test_a_bounded_argument_of_a_shape_section_seven_admits_is_constructible(
    kind: BoundKind, currency_argument: str | None
) -> None:
    """The controls beside the refusals above: exactly two shapes, and both work."""
    assert (
        BoundedArgument(argument="amount", kind=kind, currency_argument=currency_argument).kind
        is kind
    )


def test_a_declaration_declaring_one_argument_twice_is_not_constructible() -> None:
    """ADR-0266 §7: ``bounded_arguments`` is **duplicate-free on ``argument``**.

    Two declarations of one key would need a precedence rule at the comparison,
    which is the shape ADR-0254 §2 refuses one type over. **Two declarations of one
    *kind* are admitted** and are not a defect — §7 answers those by meeting no
    member of that kind on the argument route at all, which the policy suite
    exercises. Adversarial review, round 7, ``blocker``.
    """
    with pytest.raises(ValidationError, match="name the same argument"):
        ToolDefinition.model_validate(
            {
                **TOOL.model_dump(),
                "bounded_arguments": (
                    {"argument": "amount", "kind": "money", "currency_argument": "currency"},
                    {"argument": "amount", "kind": "terms", "currency_argument": None},
                ),
            }
        )


def test_a_declaration_declaring_two_arguments_at_one_kind_is_constructible() -> None:
    """The control beside it, and the distinction the rule turns on: the refusal is
    over the **argument**, and two arguments at one kind are a declaration this type
    admits and the comparison answers (ADR-0266 §7)."""
    declared = ToolDefinition.model_validate(
        {
            **TOOL.model_dump(),
            "bounded_arguments": (
                {"argument": "amount", "kind": "money", "currency_argument": "currency"},
                {"argument": "fee", "kind": "money", "currency_argument": "currency"},
            ),
        }
    )
    assert len(declared.bounded_arguments) == 2


def test_a_declaration_filling_the_currency_key_itself_declares_no_money_argument() -> None:
    """ADR-0266 §7's refusal read over **both** keys a ``BoundedArgument`` names.

    §7 states it over the entry *"naming no key of that declaration's own
    ``system_supplied``"*, and a currency key the system fills is as much a value
    the user never stated as the amount's. The restrictive direction ADR-0254 §2
    asks for: it costs a declaration and never authorises a call.
    """
    with pytest.raises(ValidationError, match="name no key it fills itself"):
        ToolDefinition.model_validate(
            {
                **TOOL.model_dump(),
                "system_supplied": ("currency",),
                "bounded_arguments": (
                    {"argument": "amount", "kind": "money", "currency_argument": "currency"},
                ),
            }
        )


# --- §3, §6, §7: what the ruling, the request and the declaration carry -------


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
    assert ActionRequest(tool=TOOL).goal is None
    assert ActionRequest(tool=TOOL, goal="goal-0001").goal == "goal-0001"


def test_a_declaration_classifies_nothing_system_supplied_by_default() -> None:
    """§3: the empty tuple makes the **opposite** claim to the one ADR-0016 §1 refuses.

    An unclassified argument is **user-facing**, so a declaration that says nothing
    needs coverage for every argument and asks where it has none: *"It costs a
    question and can never authorise a call"*.
    """
    assert TOOL.system_supplied == ()
    assert ToolDefinition.model_fields["system_supplied"].default == ()


def test_a_declaration_classifies_each_key_system_supplied_once() -> None:
    """§3: duplicate-free — *"a duplicate is a second spelling of one classification"*."""
    with pytest.raises(ValidationError, match="each key system-supplied once"):
        ToolDefinition.model_validate(
            {**TOOL.model_dump(), "system_supplied": ("locale", "locale")}
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
