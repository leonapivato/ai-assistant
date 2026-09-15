"""ADR-0254 §11's three projections, as `core` types (§16, §20 arm 35).

**The roster test is ADR-0178 §10's shape, over the three new types.** §20 arm 35
requires that *"no field of any of the three is named or typed for a goal id, an
authorization `confirmation` or `supersedes`, a `BoundAccount`, a subject digest, a
connection reference, a `SecretName` or a transport endpoint — and that
`AuthorizationView` carries the row's `id`, no `destinations`, and
`AuthorizationSettlement` nothing at all beyond its four members"*.

**Asserted over the field list and not over one constructed instance**, which is
ADR-0178 §10's own construction: a value that happens to carry no reference is a fact
about that value, and a *type* that has no field for one is a fact about every value.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Final, get_args, get_origin

import pytest
from pydantic import BaseModel, ValidationError

from ai_assistant.core.types import (
    AuthorizationProjection,
    AuthorizationSettlement,
    AuthorizationView,
    BoundAccount,
    BoundKind,
    Confirmation,
    CoverageView,
    SecretName,
    ToolDefinition,
    TurnOutcome,
)
from ai_assistant.testing import (
    AUTHORIZATION_EXPIRES_AT,
    AUTHORIZATION_TOOL,
    money_bound,
    terms_bound,
)

#: The three types §20 arm 35 states its bar over, together.
VIEWS: Final = (CoverageView, AuthorizationProjection, AuthorizationView)

#: The field **names** no member of the three may carry, in any spelling a lane might
#: reach for. Stated as substrings because the bar is about what the field *is*, and a
#: type that renamed ``goal`` to ``goal_id`` would satisfy an equality check while
#: carrying exactly what §11 forbids.
BARRED_NAMES: Final = (
    "goal_id",
    "confirmation",
    "supersedes",
    "digest",
    "account",
    "reference",
    "secret",
    "endpoint",
    "destinations",
    "resolution",
    "basis",
)


def _annotations(model: type[BaseModel]) -> list[object]:
    """Every type any field of ``model`` names, at any depth of its annotation."""
    found: list[object] = []
    queue: list[object] = [field.annotation for field in model.model_fields.values()]
    while queue:
        annotation = queue.pop()
        found.append(annotation)
        queue.extend(get_args(annotation))
        origin = get_origin(annotation)
        if origin is not None:
            found.append(origin)
    return found


@pytest.mark.parametrize("model", VIEWS, ids=lambda one: one.__name__)
def test_no_projection_names_a_field_the_rendering_bar_forbids(model: type[BaseModel]) -> None:
    """ADR-0254 §20 arm 35's name half, over all three types at once."""
    for name in model.model_fields:
        assert not any(barred in name for barred in BARRED_NAMES), (
            f"{model.__name__}.{name} names a value ADR-0254 §11's rendering bar keeps "
            f"off every surface this decision owes"
        )


@pytest.mark.parametrize("model", VIEWS, ids=lambda one: one.__name__)
def test_no_projection_is_typed_for_an_account_or_a_credential(model: type[BaseModel]) -> None:
    """ADR-0254 §20 arm 35's type half.

    The name check above catches a field called ``account``; this catches one called
    anything else that is nevertheless typed for a :class:`BoundAccount` — which is the
    carrier ``reference`` travels inside, and the reason §11 declines to render a
    destination set at all.
    """
    named = _annotations(model)
    assert BoundAccount not in named
    assert SecretName not in named


@pytest.mark.parametrize("model", VIEWS, ids=lambda one: one.__name__)
def test_every_projection_forbids_an_extra_field(model: type[BaseModel]) -> None:
    """A member ADR-0254 §11 did not name is unconstructible rather than unnoticed."""
    assert model.model_config.get("extra") == "forbid"
    assert model.model_config.get("frozen") is True


def test_the_projection_carries_exactly_three_members_and_no_identifier() -> None:
    """ADR-0254 §11 as ADR-0267 §7 leaves it: ``coverage``, ``expires_at`` and ``quote``.

    **A third since ADR-0267 §7**, which partially supersedes §11's field list in that
    limb alone: *"A confirmation that renders a ceiling without the figure the act was
    quoted at is not a confirmation of that charge"*.

    **It still names no identifier**, which is the whole of the difference between this
    type and :class:`AuthorizationView`: a confirmation is about a row the user has not
    established, so there is nothing yet to withdraw and no handle to carry — and
    :class:`~ai_assistant.core.types.QuoteView` carries no digest, no intended action,
    no plan, no step and no goal id, so the new member does not smuggle one in.
    """
    assert set(AuthorizationProjection.model_fields) == {"coverage", "expires_at", "quote"}
    assert "id" not in AuthorizationProjection.model_fields


def test_the_listing_view_carries_the_id_and_no_destinations() -> None:
    """ADR-0254 §20 arm 35's two positive clauses.

    The ``id`` is here **because it is the revocation handle** — ADR-0193 §11's bar read
    as it stands rather than one conjunct wider, and *"a listing that named no id would
    state an act and withhold the means to perform it"*. ``destinations`` is absent
    because :class:`~ai_assistant.core.types.CanonicalDestination`'s account arm carries
    a whole :class:`BoundAccount`, and §11 declines to mint the projection that would
    drop the reference.
    """
    assert set(AuthorizationView.model_fields) == {
        "id",
        "goal_statement",
        "tool",
        "coverage",
        "expires_at",
        "live",
    }


def test_the_settlement_vocabulary_carries_nothing_beyond_its_four_members() -> None:
    """ADR-0254 §16: closed at exactly four, each valued by its lower-cased name."""
    assert [one.value for one in AuthorizationSettlement] == [
        "settled",
        "not_at_source",
        "would_duplicate",
        "no_such_authorization",
    ]


def _view(**overrides: Any) -> dict[str, Any]:
    """The keyword arguments of a well-formed :class:`CoverageView`."""
    return {
        "kind": BoundKind.MONEY,
        "bound": money_bound(),
        "span": "up to sixty pounds",
    } | overrides


def test_a_coverage_view_fixes_a_value_or_states_a_bound_and_never_both() -> None:
    """ADR-0254 §11 puts the two fields *"under ``CoverageMember``'s own two-shape
    validator"*, so the projection is refusable in exactly the cases the record is.
    """
    with pytest.raises(ValidationError, match="never both"):
        CoverageView(**_view(fixed="60"))
    with pytest.raises(ValidationError, match="renders nothing the user said"):
        CoverageView(**_view(bound=None))


@pytest.mark.parametrize(
    ("kind", "extra"),
    [
        (BoundKind.TERMS, {"bound": money_bound("50")}),
        (BoundKind.MONEY, {"bound": terms_bound("flexible")}),
        (BoundKind.PERIOD, {"bound": money_bound("50")}),
        (BoundKind.MONEY, {"fixed": "50", "bound": None}),
        (BoundKind.TERMS, {"fixed": 50, "bound": None}),
        (BoundKind.PERIOD, {"fixed": "2026-02-30", "bound": None}),
    ],
)
def test_a_view_the_record_could_not_have_produced_is_not_constructible(
    kind: BoundKind, extra: dict[str, Any]
) -> None:
    """ADR-0266 §3's kind validation, read through §11's transcription rule.

    **The cost of not stating it is on the screen the user answers from**: a
    ``TERMS`` view carrying a ``MONEY`` bound renders *"the terms: up to 50 GBP"*,
    and a ``MONEY`` view carrying a fixed value renders an amount nothing
    denominates. Both misstate the authority at the one moment §11 exists to make
    checkable, and no ``CoverageMember`` can produce either — so the view is
    *"refusable in exactly the cases the record is"*. Adversarial review, round 1,
    ``major``.
    """
    with pytest.raises(ValidationError):
        CoverageView(**_view(kind=kind, **extra))


@pytest.mark.parametrize(
    ("kind", "extra"),
    [
        (BoundKind.MONEY, {"bound": money_bound("50")}),
        (BoundKind.TERMS, {"bound": terms_bound("flexible")}),
        (BoundKind.TERMS, {"fixed": "flexible", "bound": None}),
        (BoundKind.PERIOD, {"fixed": "2026-09-13", "bound": None}),
    ],
)
def test_a_view_transcribed_from_a_constructible_member_is_constructible(
    kind: BoundKind, extra: dict[str, Any]
) -> None:
    """The controls beside the refusals above: the validator forbids no rendering a
    conforming record can produce, which is what keeps it a transcription rule
    rather than a second, narrower one."""
    assert CoverageView(**_view(kind=kind, **extra)).kind is kind


def test_a_coverage_view_requires_the_span() -> None:
    """ADR-0254 §8: *"Both halves survive, and neither is derivable from the other."*

    A member rendered without the words behind it is one whose working cannot be
    checked — which §11 says is as true at the question as it is afterwards.
    """
    with pytest.raises(ValidationError):
        CoverageView(**_view(span=""))
    with pytest.raises(ValidationError):
        CoverageView.model_validate({"kind": "money", "bound": money_bound().model_dump()})


def test_a_coverage_view_requires_its_kind() -> None:
    """ADR-0266 §11's arm 6(b): *"a ``CoverageView`` is constructible at each of the
    three kinds and at **none without one**"*.

    **Stated over an otherwise-valid payload missing only ``kind``**, and the error
    is asserted to be about that field. An earlier version of this arm handed the
    validator a payload that also carried the removed ``argument`` and no ``span``,
    so it failed twice over for reasons that had nothing to do with ``kind`` — and
    would have gone on passing if ``kind`` had quietly gained a default, which is
    the regression it exists to catch. Adversarial review, round 7, ``blocker``.
    """
    payload = {"bound": money_bound().model_dump(), "span": "up to sixty pounds"}

    with pytest.raises(ValidationError) as raised:
        CoverageView.model_validate(payload)

    assert [one["loc"] for one in raised.value.errors()] == [("kind",)]
    assert CoverageView.model_validate({**payload, "kind": "money"}).kind is BoundKind.MONEY


@pytest.mark.parametrize("model", [AuthorizationProjection, AuthorizationView])
def test_no_projection_carries_two_views_of_one_kind(model: type[BaseModel]) -> None:
    """ADR-0254 §2's rule as ADR-0266 §3 restates it, transcribed rather than restated.

    §2 forbids two members of one record being about one thing the user said — the
    **kind**, once a member names no argument — and §11 makes these views a
    *transcription* of that record's coverage, so a projection carrying two views of
    one kind is a mis-transcription and the shape a reading surface would need a
    precedence rule to render.
    """
    twice = (CoverageView(**_view()), CoverageView(**_view(span="and no more than sixty")))
    common: dict[str, Any] = {"coverage": twice, "expires_at": AUTHORIZATION_EXPIRES_AT}
    if model is AuthorizationView:
        common |= {
            "id": "auth-1",
            "goal_statement": "book the trip",
            "tool": AUTHORIZATION_TOOL,
            "live": True,
        }
    with pytest.raises(ValidationError, match="carry the same kind"):
        model(**common)


@pytest.mark.parametrize("model", [AuthorizationProjection, AuthorizationView])
def test_an_empty_coverage_is_constructible(model: type[BaseModel]) -> None:
    """ADR-0254 §11: the projection is *"possibly-empty"* because §1 permits it.

    The row a ``CONFIRM`` about an argument-free egress request proposes carries
    ``coverage=()``, and a non-empty projection could not be constructed for it at all —
    so omitting the projection would say falsely that answering establishes no
    authority, and minting a member would be an invention where §11 requires a
    transcription.
    """
    common: dict[str, Any] = {"coverage": (), "expires_at": AUTHORIZATION_EXPIRES_AT}
    if model is AuthorizationProjection:
        # ADR-0267 §7 makes ``quote`` required with no default, so absence is a fact
        # about the row rather than a caller's omission. Every row this tree writes
        # carries ``quoted`` ``None``, its producer being ADR-0254 §20's Lane 2.
        common |= {"quote": None}
    if model is AuthorizationView:
        common |= {
            "id": "auth-1",
            "goal_statement": "book the trip",
            "tool": AUTHORIZATION_TOOL,
            "live": False,
        }
    assert model.model_validate(common).model_dump()["coverage"] == ()


def test_the_view_carries_the_declaration_by_value() -> None:
    """ADR-0254 §11: a :class:`ToolDefinition` *"by value"*.

    Which is what makes two announcements of one act legible — the user tells them apart
    by the declaration each is about — and it is
    :class:`~ai_assistant.core.types.RecipientGrant`'s own shape one store over.
    """
    assert AuthorizationView.model_fields["tool"].annotation is ToolDefinition


def test_the_confirmation_member_is_required_with_no_default() -> None:
    """ADR-0254 §11: ``authorization`` is *"required with no default"*.

    A member that could be left off is one an assembly site can forget, which is
    ``egress``' and ``read``' own reason on this same type.
    """
    assert Confirmation.model_fields["authorization"].is_required()


def test_the_announcement_member_defaults_to_empty() -> None:
    """ADR-0254 §11: ``authorizations`` is *"possibly empty and defaulting to empty"*.

    It is **empty** on every turn that opened none, so the default is the honest value
    rather than a stand-in — the opposite direction from ``Confirmation``'s member
    above, and for the opposite reason: this one states what the turn *did*, and a turn
    that opened nothing did nothing to state.
    """
    assert TurnOutcome(turn=None).authorizations == ()
    assert TurnOutcome.model_fields["authorizations"].default == ()


def test_the_announcement_is_a_tuple_so_one_act_can_open_two_authorities() -> None:
    """ADR-0254 §11: *"one act can open two authorities that are not the same authority"*.

    Two declarations may each name their price argument ``amount``, so merging the two
    would authorise an eighty-pound train booking or refuse an eighty-pound hotel one.
    """
    train = AuthorizationView(
        id="auth-train",
        goal_statement="get to the conference",
        tool=AUTHORIZATION_TOOL,
        coverage=(CoverageView(**_view(bound=money_bound("50"))),),
        expires_at=AUTHORIZATION_EXPIRES_AT,
        live=True,
    )
    hotel = train.model_copy(
        update={"id": "auth-hotel", "coverage": (CoverageView(**_view(bound=money_bound("100"))),)}
    )
    outcome = TurnOutcome(turn=None, authorizations=(train, hotel))
    assert [one.id for one in outcome.authorizations] == ["auth-train", "auth-hotel"]
    bounds = [one.coverage[0].bound for one in outcome.authorizations]
    assert [one.maximum for one in bounds if one is not None] == [Decimal(50), Decimal(100)]


def test_an_expiry_without_a_zone_is_refused() -> None:
    """ADR-0254 §12's instant is a :data:`~ai_assistant.core.types.UtcInstant`.

    A naive one would be an instant nobody can compare, and the horizon ADR-0256 makes
    this surface show is exactly a value two peers must agree about.
    """
    with pytest.raises(ValidationError):
        AuthorizationProjection(coverage=(), expires_at=datetime(2026, 9, 13, 21, 0), quote=None)  # noqa: DTZ001
    assert (
        AuthorizationProjection(
            coverage=(), expires_at=datetime(2026, 9, 13, 21, 0, tzinfo=UTC), quote=None
        ).expires_at.tzinfo
        is not None
    )
