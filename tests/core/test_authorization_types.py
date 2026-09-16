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
    BoundedArgument,
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
        # **Seven and not six** (ADR-0268 §2): the ending a closure of the row's goal
        # takes over the rows standing when it is taken. Appended, so the six
        # ratified members keep the values a stored row decodes from, which is §1's
        # own *"added to and never renamed"* rule and the licence for it.
        "goal_closed",
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
        # **Four and not three** (ADR-0266 §4): ADR-0254 §19 books *"A fourth
        # ``ResolutionRule``"* by name and ADR-0266 fires it, appended so the three
        # ratified readings keep the values a stored row decodes from.
        "stated_bound",
    ]


def test_the_field_list_is_closed_and_a_lane_adding_a_member_is_changing_the_decision() -> None:
    """§1: *"The field list is **closed**"*, so a fifteenth field is a red test.

    **Fourteen since ADR-0267 §7**, which partially supersedes §1's field list in that
    limb alone: the row gains ``quoted``, the governing quote for the request's
    intended action in the goal the row was built from. Its producer is ADR-0254 §20's
    Lane 2 (ADR-0267 §11), so every row this tree writes carries ``None``.
    """
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
        "quoted",
    }


# --- §2: a member fixes a value or states a bound, and there is no third kind -


def test_a_member_carrying_both_a_fixed_value_and_a_bound_is_not_constructible() -> None:
    """§2: a model validator admits exactly two shapes."""
    with pytest.raises(ValidationError, match="fixes a value or states a bound"):
        CoverageMember(
            kind=BoundKind.MONEY,
            fixed="60",
            bound=money_bound(),
            basis=authorization_basis(),
        )


def test_a_member_carrying_neither_is_not_constructible() -> None:
    """§2: *"one that does neither records nothing the user said"*."""
    with pytest.raises(ValidationError, match="fixes a value or states a bound"):
        CoverageMember(kind=BoundKind.MONEY, basis=authorization_basis())


def test_a_member_without_a_basis_is_not_constructible() -> None:
    """§9 clause (i): *"a member without one is not constructible"* (arm 21).

    The **type's** half of that clause. Its other two arms — a basis whose ``act``
    names no recorded turn, and one whose ``span`` is not a span of that turn's
    ``TurnResult.utterance`` — compare a basis against a **store** and are
    ``orchestration``'s, which §1's division of refusals states in terms.
    """
    with pytest.raises(ValidationError):
        CoverageMember.model_validate({"kind": "terms", "fixed": "60"})


def test_no_two_members_of_one_row_carry_the_same_kind() -> None:
    """ADR-0266 §3, restating §2's rule over the value that now identifies a member:
    *"A precedence rule between two members about one argument is a rule somebody
    would have to remember at the comparison"* (arm 4(a))."""
    with pytest.raises(ValidationError, match="same kind"):
        authorization(
            coverage=(
                coverage_member(BoundKind.MONEY, bound=money_bound("40")),
                coverage_member(BoundKind.MONEY, bound=money_bound()),
            )
        )


@pytest.mark.parametrize(
    "fixed",
    [
        "2026-02-30",
        "2026-13-01",
        "2026-09-13T25:00:00Z",
        "2026-09-13T10:70:00Z",
        "2026-02-29",
        # **The offset's own ranges**, which the parse *normalises* rather than
        # refusing: ``+00:60`` reads back as ``+01:00``, so the record would say one
        # thing and the reading another — ADR-0150's two-shapes hazard at the one
        # comparison that decides whether a call is authorised. Adversarial review,
        # round 5, ``blocker``.
        "2026-01-01T12:00:00+00:60",
        "2026-01-01T12:00:00+24:00",
        "2026-01-01T12:00:00+99:99",
    ],
)
def test_a_period_member_fixing_a_date_the_reading_refuses_is_not_constructible(
    fixed: str,
) -> None:
    """ADR-0266 §3: a ``PERIOD`` ``fixed`` is *"a value that reading accepts"*.

    **Shape is not enough, and the cost of treating it as enough is a covered
    call.** A fixed value is compared by **byte equality**, so a member holding
    ``"2026-02-30"`` would cover a request carrying that same impossible string —
    a value ADR-0254 §4's reading accepts nowhere, since it denotes no day. The
    construction and the comparison read **one** parser
    (``period_reading_form``), so a string one refuses is a string the other never
    sees. Adversarial review, round 1, ``blocker``.
    """
    with pytest.raises(ValidationError, match="reading accepts"):
        CoverageMember(kind=BoundKind.PERIOD, fixed=fixed, basis=authorization_basis())


@pytest.mark.parametrize(
    "fixed",
    [
        "2026-09-13",
        "2026-02-28",
        "2028-02-29",
        "0099-01-01",
        "2026-09-13T10:00:00+01:00",
        # The widest offsets RFC 3339 §4.2 admits, either side of the line the
        # refusals above are stated over.
        "2026-01-01T12:00:00+23:59",
        "2026-01-01T12:00:00-23:59",
    ],
)
def test_a_period_member_fixing_a_date_the_reading_accepts_is_constructible(fixed: str) -> None:
    """The control beside the refusal above: a real calendar date and a real
    instant carrying an offset are both values §4's reading reads."""
    assert (
        CoverageMember(kind=BoundKind.PERIOD, fixed=fixed, basis=authorization_basis()).fixed
        == fixed
    )


#: One bound of each kind, so the pair matrix below is written over kinds rather
#: than over three hand-built values (ADR-0266 §11's arm 6(b)).
def _bound_of(kind: BoundKind) -> ValueBound:
    """A well-formed :class:`ValueBound` of ``kind``."""
    return {
        BoundKind.MONEY: money_bound(),
        BoundKind.PERIOD: period_bound(),
        BoundKind.TERMS: terms_bound("flexible"),
    }[kind]


@pytest.mark.parametrize(
    ("kind", "fixed"),
    [(BoundKind.MONEY, "60"), (BoundKind.TERMS, 60), (BoundKind.TERMS, True)],
)
def test_a_member_fixing_a_value_its_kind_does_not_state_is_not_constructible(
    kind: BoundKind, fixed: object
) -> None:
    """ADR-0266 §3, arm 6(b): a ``MONEY`` ``fixed`` outright — *"an amount carries
    no currency on a fixed member"* — and a ``TERMS`` ``fixed`` that is not a
    string, ``True`` among them, since ``bool`` is an ``int`` in Python."""
    with pytest.raises(ValidationError):
        CoverageMember(
            kind=kind,
            fixed=fixed,  # type: ignore[arg-type]  # the refusal is what is asserted
            basis=authorization_basis(),
        )


@pytest.mark.parametrize(
    ("kind", "bound"),
    [(one, other) for one in BoundKind for other in BoundKind if one is not other],
)
def test_a_member_whose_bound_is_of_another_kind_is_not_constructible(
    kind: BoundKind, bound: BoundKind
) -> None:
    """ADR-0266 §11's arm 6(b): **every unequal pair of the three kinds**.

    **Generated from the vocabulary rather than listed**, so the matrix is complete
    by construction and a fourth ``BoundKind`` would widen it without anyone
    remembering to. Adversarial review, round 7, ``blocker``: three of the six pairs
    were exercised and the arm asks for all of them.
    """
    with pytest.raises(ValidationError, match="states a bound of that kind"):
        CoverageMember(kind=kind, bound=_bound_of(bound), basis=authorization_basis())


@pytest.mark.parametrize("kind", list(BoundKind))
def test_a_member_whose_bound_is_of_its_own_kind_is_constructible(kind: BoundKind) -> None:
    """Arm 6(b)'s *"beside one equal pair of each that is"* — the three controls,
    without which the matrix above would pass on a validator refusing everything."""
    member = CoverageMember(kind=kind, bound=_bound_of(kind), basis=authorization_basis())
    assert member.bound is not None
    assert member.bound.kind is kind


def test_a_row_carrying_two_members_of_different_kinds_is_constructible() -> None:
    """ADR-0266 §3's rule is one **per kind** and not one per row (arm 4(a)).

    The control beside the refusal above: a ``MONEY`` member beside a ``TERMS`` one
    is two statements about two different things the user said, and nobody has to
    remember a precedence between them.
    """
    row = authorization(
        coverage=(
            coverage_member(BoundKind.MONEY, bound=money_bound()),
            coverage_member(BoundKind.TERMS, bound=terms_bound("refundable")),
        )
    )
    assert {member.kind for member in row.coverage} == {BoundKind.MONEY, BoundKind.TERMS}


# --- §2: the three bound kinds, and every other shape refused ----------------


#: The arguments each :class:`BoundKind` takes, keyed by kind — ADR-0254 §2's own
#: enumeration, written once so the two directions of the validator's rule are
#: tested against one statement of it rather than two.
_ARGUMENTS_OF: Final[dict[BoundKind, dict[str, object]]] = {
    BoundKind.MONEY: {"currency": "GBP", "maximum": Decimal("60")},
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


# --- §8, §10: the resolution admits exactly the shapes the rule names --------

#: A well-formed value for each argument a :class:`ValueResolution` can carry.
_RESOLUTION_ARGUMENTS: dict[str, object] = {
    "now": AUTHORIZATION_PROPOSED_AT,
    "timezone": "Europe/London",
    "record": "rec-1",
}

#: What each :class:`ResolutionRule` takes, in both directions (§8).
#:
#: **``STATED_BOUND`` takes neither** (ADR-0266 §4): its one input is the span the
#: basis already names, so there is nothing further to record.
_RESOLUTION_SHAPES: dict[ResolutionRule, frozenset[str]] = {
    ResolutionRule.AS_STATED: frozenset(),
    ResolutionRule.DATE_FROM_CONTEXT: frozenset({"now", "timezone"}),
    ResolutionRule.FROM_SHOWN_RECORD: frozenset({"record"}),
    ResolutionRule.STATED_BOUND: frozenset(),
}


def test_every_resolution_rule_has_a_stated_shape() -> None:
    """The matrix below is over the **enum**, so a fifth rule is a red test.

    Written as a set comparison rather than as four keys anyone could forget to
    extend: ADR-0266 §4 added the fourth rule and nothing obliged the suite to
    exercise it, which left ``STATED_BOUND``'s validator branch pinned by its
    spelling alone. Adversarial review, round 8, ``major``.
    """
    assert set(_RESOLUTION_SHAPES) == set(ResolutionRule)


@pytest.mark.parametrize("rule", list(ResolutionRule))
def test_a_resolution_carries_its_own_rules_arguments_and_no_others(rule: ResolutionRule) -> None:
    """§8, §10, arm 34: *"both required and neither absent"*, per rule and in both
    directions — the shape constructs, every argument the rule does not take is
    refused where present, and every argument it does take is refused where absent.

    A zero-argument rule exercises the first two limbs and has no third, which is
    what a driven case for it looks like: ``STATED_BOUND`` and ``AS_STATED`` are
    **constructible bare** and refuse each of ``now``, ``timezone`` and ``record``.
    """
    taken = _RESOLUTION_SHAPES[rule]
    payload = {name: _RESOLUTION_ARGUMENTS[name] for name in sorted(taken)}
    resolution = ValueResolution.model_validate({"rule": rule, **payload})
    assert resolution.rule is rule
    carried = {name for name in _RESOLUTION_ARGUMENTS if getattr(resolution, name) is not None}
    assert carried == taken
    for stray in sorted(set(_RESOLUTION_ARGUMENTS) - taken):
        with pytest.raises(ValidationError, match="carries no"):
            ValueResolution.model_validate(
                {"rule": rule, **payload, stray: _RESOLUTION_ARGUMENTS[stray]}
            )
    for absent in sorted(taken):
        without = {name: value for name, value in payload.items() if name != absent}
        with pytest.raises(ValidationError, match="states its"):
            ValueResolution.model_validate({"rule": rule, **without})


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
        BoundKind.PERIOD,
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


def test_a_declaration_declaring_a_system_supplied_key_at_a_kind_is_not_constructible() -> None:
    """ADR-0266 §7, restating §3's protection one field over (arms 68, 6(b)).

    **The rule is preserved and its carrier moved.** §3 made a row whose coverage
    names a system-supplied argument not constructible by reading
    ``CoverageMember.argument``, which no longer exists; a system-supplied key being
    declarable at **no** kind is what keeps *"a user is never asked to approve an
    idempotency key"* true — no member can be met against one, on either route.
    """
    with pytest.raises(ValidationError, match="name no key it fills itself"):
        AUTHORIZATION_TOOL.model_copy(update={"system_supplied": ()}).model_validate(
            {
                **AUTHORIZATION_TOOL.model_dump(),
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
                **AUTHORIZATION_TOOL.model_dump(),
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
            **AUTHORIZATION_TOOL.model_dump(),
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
                **AUTHORIZATION_TOOL.model_dump(),
                "system_supplied": ("currency",),
                "bounded_arguments": (
                    {"argument": "amount", "kind": "money", "currency_argument": "currency"},
                ),
            }
        )


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
        # ADR-0267 §7 puts ``quoted`` **outside** the subject deliberately: it is
        # provenance, *"no comparison of any decision reads it"*, and leaving it in
        # would move the digest of a row whose subject had not changed.
        "quoted",
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
        "coverage": (coverage_member(BoundKind.TERMS, fixed="refundable"),),
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
    fixed JSON ``null`` mints **no member** — and the argument it would have covered
    is then left **uncovered**, which is the fail-closed direction: the user is
    asked about the concrete call.

    Recorded as a test rather than left to be discovered, because the alternative
    reading — that such a member is constructible — is the one a lane would reach
    for and it is not available.
    """
    with pytest.raises(ValidationError, match="fixes a value or states a bound"):
        CoverageMember(kind=BoundKind.TERMS, fixed=None, basis=authorization_basis())


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
