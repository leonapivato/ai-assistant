"""ADR-0267's quote contract: which values construct and which cannot.

The **type-level** half of §11's arms, and Q1's alone. What a store does with a
minting is ``tests/planning/plan_store_contract.py``'s; what the seam answers is
``tests/planning/goal_quotes_contract.py``'s; what the comparison makes of a quote is
``tests/permissions/test_quote_coverage.py``'s. **Arm 4 is not here and is not this
lane's**: the mint is Q2's, in ``orchestration``, and asserting it here would mean
writing a second statement of the mint in test code and then asserting the test against
it. **Arm 7 is not here either** — the row population and the projection it feeds ride
ADR-0254 §20's Lane 2 (§11) — so what is asserted of ``Authorization.quoted`` and
``AuthorizationProjection.quote`` here is exactly what Q1 lands: their **shape**, and
that every row written today decodes with ``quoted`` ``None``.

What is here is **arm 1** whole, **arm 3** whole, arm **2**'s order limb — the goal's
tuple *is* the total order — and **arm 8**'s writer-clause, stored-shape, wire and
export limbs.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from ai_assistant.core.types import (
    MAX_ACTION_QUOTES,
    ActionPlan,
    ActionQuote,
    ActionQuoteMinting,
    Authorization,
    AuthorizationProjection,
    CostBasis,
    EvidenceHistory,
    Goal,
    GoalInterpretation,
    Ground,
    Idempotency,
    IntendedAction,
    MemorySource,
    PlanExport,
    PlannerOutput,
    PlanStep,
    ProposedAction,
    Provenance,
    QuotedOutput,
    QuoteView,
    Reversibility,
    RiskLevel,
    StepOutputRef,
    ToolCost,
    ToolDefinition,
)
from ai_assistant.testing import authorization
from ai_assistant.wire.envelope import PROTOCOL_VERSION

_WHEN = datetime(2026, 1, 1, tzinfo=UTC)
_DIGEST = "a" * 64
_OTHER_DIGEST = "b" * 64


def _quote(
    *,
    action: str = "ia1",
    amount: str = "120",
    currency: str = "EUR",
    digest: str = _DIGEST,
    read_at: datetime = _WHEN,
) -> ActionQuote:
    """One quote, at the shape §1 declares."""
    return ActionQuote(
        intended_action=action,
        arguments_digest=digest,
        amount=Decimal(amount),
        currency=currency,
        plan="p1",
        read_from=StepOutputRef(step="s1", field="price"),
        read_at=read_at,
    )


def _goal(*, quotes: tuple[ActionQuote, ...] = (), elided: int = 0) -> Goal:
    """A goal at revision 1 holding two intended actions and the given quotes."""
    return Goal(
        id="g1",
        interpretation=(
            GoalInterpretation(
                revision=1,
                outcome="book a room for the trip",
                outcome_ground=Ground.USER_STATED,
                outcome_span="book a room",
                recorded_at=_WHEN,
            ),
        ),
        intended_actions=(
            IntendedAction(id="ia1", intent="book the room"),
            IntendedAction(id="ia2", intent="book the second room"),
        ),
        quotes=quotes,
        quotes_elided=elided,
        provenance=Provenance(
            source=MemorySource.USER_ASSERTED, confidence=1.0, last_updated=_WHEN
        ),
        created_at=_WHEN,
    )


def _tool(**overrides: object) -> ToolDefinition:
    """A declaration, optionally carrying a ``quoted_output``."""
    return ToolDefinition(
        id="book",
        capability="book_room",
        description="book a room",
        risk_level=RiskLevel.MEDIUM,
        reversibility=Reversibility.RECOVERABLE,
        side_effecting=True,
        reads=(),
        writes=(),
        discloses=(),
        cost=ToolCost(basis=CostBasis.FREE),
        idempotency=Idempotency.NONE,
        **overrides,  # type: ignore[arg-type]
    )


# --- arm 1: the record, and the four facts -----------------------------------


def test_a_quote_constructs_at_the_shape_section_one_declares() -> None:
    """§1's seven fields, and it round-trips through its own dump."""
    quote = _quote()
    assert quote.intended_action == "ia1"
    assert quote.arguments_digest == _DIGEST
    assert quote.amount == Decimal("120")
    assert quote.currency == "EUR"
    assert quote.plan == "p1"
    assert quote.read_from == StepOutputRef(step="s1", field="price")
    assert quote.read_at == _WHEN
    assert ActionQuote.model_validate(quote.model_dump()) == quote


def test_a_quote_carries_exactly_seven_fields_and_no_eighth() -> None:
    """§1: "It carries no eighth field: no id of its own, no attempt, no tool…"."""
    assert set(ActionQuote.model_fields) == {
        "intended_action",
        "arguments_digest",
        "amount",
        "currency",
        "plan",
        "read_from",
        "read_at",
    }


@pytest.mark.parametrize("amount", ["NaN", "Infinity", "-Infinity", "-1", "-0.01"])
def test_a_quote_is_not_constructible_at_an_amount_that_is_not_a_price(amount: str) -> None:
    """§1: the amount is finite and not negative.

    ``Decimal`` **accepts** all three of ``"NaN"``, ``"Infinity"`` and ``"-Infinity"``,
    which is why the refusal is a validator and not the annotation: "neither of which
    has a JSON representation or survives arithmetic in a running total, and comparing
    ``NaN`` with ``<`` raises rather than answering".
    """
    with pytest.raises(ValidationError):
        _quote(amount=amount)


def test_zero_is_a_price_and_is_no_absence() -> None:
    """§11 arm 1: "**Zero is a price**: ``Decimal("0")`` constructs"."""
    assert _quote(amount="0").amount == Decimal("0")


@pytest.mark.parametrize("digest", ["", "A" * 64, "a" * 63, "a" * 65, "g" * 64, " " + "a" * 63])
def test_a_quote_is_not_constructible_at_a_digest_that_is_not_lowercase_hex(digest: str) -> None:
    """§1: ``arguments_digest`` is a ``Sha256Hex``, which is what it is compared as."""
    with pytest.raises(ValidationError):
        _quote(digest=digest)


@pytest.mark.parametrize("currency", ["usd", "EURO", "€", "EU", "E1R", "", "eur"])
def test_neither_record_is_constructible_at_a_currency_of_the_wrong_shape(currency: str) -> None:
    """§1 and §7, and the shape is on **both** records rather than on one.

    "A quote minted at ``"usd"`` matches no bound's ``"USD"`` ever, so it would cover
    nothing while looking like a price that had been read."
    """
    with pytest.raises(ValidationError):
        _quote(currency=currency)
    with pytest.raises(ValidationError):
        QuoteView(amount=Decimal("120"), currency=currency, read_at=_WHEN)


@pytest.mark.parametrize("currency", ["EUR", "GBP", "XTS", "ZZZ"])
def test_the_currency_is_shape_checked_and_never_checked_against_a_register(
    currency: str,
) -> None:
    """§1: "shape and not register, so an unassigned three-letter code constructs"."""
    assert _quote(currency=currency).currency == currency
    assert QuoteView(amount=Decimal("1"), currency=currency, read_at=_WHEN).currency == currency


def test_a_quote_is_not_constructible_carrying_an_eighth_field() -> None:
    """§1: ``extra="forbid"``, so a later lane cannot slip an expiry onto the record."""
    with pytest.raises(ValidationError):
        ActionQuote.model_validate({**_quote().model_dump(), "expires_at": _WHEN.isoformat()})


# --- arm 1: the view renders no internal value --------------------------------


def test_a_quote_view_carries_three_values_and_no_identifier() -> None:
    """§7: "It carries **no** digest, no intended action, no plan, no step, no goal id…"."""
    assert set(QuoteView.model_fields) == {"amount", "currency", "read_at"}


@pytest.mark.parametrize("amount", ["NaN", "Infinity", "-1"])
def test_a_quote_view_is_not_constructible_at_an_amount_that_is_not_a_price(
    amount: str,
) -> None:
    """§7: "the bound is restated from §1 rather than assumed from the record"."""
    with pytest.raises(ValidationError):
        QuoteView(amount=Decimal(amount), currency="EUR", read_at=_WHEN)


# --- arm 1 and arm 2: the goal's order is the total order ---------------------


def test_the_last_quote_naming_an_action_is_the_governing_one() -> None:
    """§2: the tuple is oldest first and "the governing quote … is the last member".

    A goal carrying quotes for two actions returns them oldest first, and appending a
    second for one action leaves the first **in place and unmarked** — §4's *"no lane
    marks, supersedes, invalidates, edits or removes the quote it displaced"* read as a
    property of the record.
    """
    first = _quote(action="ia1", amount="120")
    other = _quote(action="ia2", amount="80")
    later = _quote(action="ia1", amount="135")
    goal = _goal(quotes=(first, other, later))

    assert goal.quotes == (first, other, later)
    for_ia1 = [quote for quote in goal.quotes if quote.intended_action == "ia1"]
    assert for_ia1[-1].amount == Decimal("135")
    assert for_ia1[0] == first, "the displaced quote is left in place and unmarked"


def test_a_goal_holds_no_quote_and_no_elision_by_default() -> None:
    """§2, and §11's "a ``Goal`` written before Q1 decodes with ``quotes`` empty"."""
    goal = _goal()
    assert goal.quotes == ()
    assert goal.quotes_elided == 0
    assert MAX_ACTION_QUOTES == 64


def test_a_goal_is_not_constructible_at_a_negative_elision_count() -> None:
    """§2: ``quotes_elided`` is an ``int`` ``ge=0`` and "never decreases"."""
    with pytest.raises(ValidationError):
        _goal(elided=-1)


# --- arm 2: the command ------------------------------------------------------


def test_the_minting_carries_exactly_three_fields() -> None:
    """§2: ``goal_id``, ``quote`` and the ``expected_version`` it was computed against."""
    assert set(ActionQuoteMinting.model_fields) == {"goal_id", "quote", "expected_version"}
    minting = ActionQuoteMinting(goal_id="g1", quote=_quote(), expected_version=3)
    assert ActionQuoteMinting.model_validate(minting.model_dump()) == minting


def test_the_minting_is_not_constructible_at_a_negative_expected_version() -> None:
    """``ge=0``, which is ``IntendedActionMinting``'s own bound one record over."""
    with pytest.raises(ValidationError):
        ActionQuoteMinting(goal_id="g1", quote=_quote(), expected_version=-1)


# --- arm 3: the declaration ---------------------------------------------------


def test_a_quoted_output_names_two_different_keys() -> None:
    """§3: "A model validator refuses ``amount`` equal to ``currency``"."""
    declared = QuotedOutput(amount="price", currency="currency")
    assert declared.amount == "price"
    with pytest.raises(ValidationError, match="two different keys"):
        QuotedOutput(amount="price", currency="price")


@pytest.mark.parametrize(
    "key", ["price", "total_price", "amount-due", "price/total", "price.total", "価格"]
)
def test_any_key_a_provider_actually_uses_is_a_key_this_declaration_can_name(
    key: str,
) -> None:
    """§3: each field is an ``EncodableText``, and one model validator guards the record.

    **Depth is one because nothing interprets the key**, not because the key's
    characters are policed — *"``StepOutputRef.field``'s rule, stated once more where
    it governs"*, and that record carries no validator at all. So a provider's flat
    ``"price.total"`` is an ordinary key: the mint looks it up whole, and a nested
    value stays unreachable however it is spelled.

    **The alternative was tried and removed.** A blacklist of ``.``, ``[``, ``]`` and
    ``*`` narrows what a boundary-crossing ``core`` type admits — golden rule 5 makes
    that a contract decision of its own — and would leave this record refusing what
    :class:`~ai_assistant.core.types.StepOutputRef` admits under the rule §3 says the
    two share. §11 arm 3's second limb is booked as an adjudication (#2439).
    """
    assert QuotedOutput(amount=key, currency="currency").amount == key


def test_a_declaration_is_constructible_with_a_quoted_output_and_with_none() -> None:
    """§3 and §9's ADR-0016 scope: the default is ``None`` and it costs a question."""
    assert _tool().quoted_output is None
    declared = _tool(quoted_output=QuotedOutput(amount="price", currency="currency"))
    assert declared.quoted_output == QuotedOutput(amount="price", currency="currency")


def test_a_declaration_dumped_before_this_decision_decodes_with_no_quoted_output() -> None:
    """§11: "a ``ToolDefinition`` [decodes] with ``quoted_output`` ``None``"."""
    stored = _tool().model_dump()
    del stored["quoted_output"]
    assert ToolDefinition.model_validate(stored).quoted_output is None


# --- arm 8: no model contributes a value this decision mints ------------------


def test_no_planner_envelope_carries_a_value_this_decision_mints() -> None:
    """§8's writer clauses, read as a property of the types.

    "A planner envelope carrying an **``ActionQuote``**, a **``QuotedOutput``**, a
    **``QuoteView``**, an amount, a currency, an output key or an arguments digest has
    those values **discarded silently**." Asserted as the stronger fact the tree
    actually gives: the envelope has **no field any of them could arrive on**, so the
    discard is structural rather than a rule a loop is trusted to keep.

    **That is what §3's whole argument rests on.** Against
    ``{"price": "200", "stars": 4, "currency": "EUR"}`` a plan-carried selector naming
    ``stars`` quotes ``4``, satisfies a ``150`` ceiling and authorises the ``200``
    purchase — "a number of the right **shape** in the wrong **slot**, which no
    validation of shape catches".
    """
    minted = {
        "quote",
        "quotes",
        "quotes_elided",
        "quoted",
        "quoted_output",
        "amount",
        "currency",
        "arguments_digest",
        "read_from",
        "read_at",
        "price",
    }
    for model in (PlannerOutput, ActionPlan, PlanStep, ProposedAction):
        assert not minted & set(model.model_fields), model.__name__


def test_the_key_a_price_is_read_at_lives_on_the_declaration_and_nowhere_else() -> None:
    """§3: "**No plan, no plan step, no planner envelope, no ``ActionRequest``…**"."""
    assert "quoted_output" in ToolDefinition.model_fields
    for model in (PlannerOutput, ActionPlan, PlanStep, ProposedAction, Authorization):
        assert "quoted_output" not in model.model_fields, model.__name__


# --- arm 8: the stored shapes -------------------------------------------------


def test_a_row_dumped_before_this_decision_decodes_with_quoted_none() -> None:
    """§11 arm 8, and §7 makes such a row "conforming rather than one to repair"."""
    stored = authorization().model_dump()
    del stored["quoted"]
    assert Authorization.model_validate(stored).quoted is None


def test_a_goal_dumped_before_this_decision_decodes_with_no_quotes() -> None:
    """§11: "A ``Goal`` written before Q1 decodes with ``quotes`` empty"."""
    stored = _goal().model_dump()
    del stored["quotes"]
    del stored["quotes_elided"]
    decoded = Goal.model_validate(stored)
    assert decoded.quotes == ()
    assert decoded.quotes_elided == 0


def test_the_subject_digest_is_unchanged_across_two_rows_differing_only_in_quoted() -> None:
    """§7: ``quoted`` sits **outside** ``_AUTHORIZATION_SUBJECT``.

    So ADR-0254 §7's recompute-on-the-row parity is untouched: the policy computes the
    digest from the record ``live_for`` returned and the trail **recomputes** it from
    the record ``resolve`` returns, and a field neither comparison reads cannot make
    the two disagree. **Q1 can drive this though the population is Lane 2's**, because
    Q1 lands the field as ``core`` shape (§11).
    """
    without = authorization()
    with_quote = authorization(quoted=_quote())
    assert with_quote.quoted is not None
    assert with_quote.subject_digest == without.subject_digest


def test_the_projection_carries_a_quote_member_that_is_required_with_no_default() -> None:
    """§7: "required with no default", so absence is a fact about the row.

    **Its producer is Lane 2's** (§11), so every projection this tree renders carries
    ``None`` — but the member is not defaulted, and a caller omitting it is refused
    rather than quietly asserting that the act was quoted at nothing.
    """
    assert AuthorizationProjection.model_fields["quote"].is_required()
    with pytest.raises(ValidationError):
        AuthorizationProjection.model_validate({"coverage": [], "expires_at": _WHEN.isoformat()})
    rendered = AuthorizationProjection(coverage=(), expires_at=_WHEN, quote=None)
    assert rendered.quote is None


# --- arm 8: the wire and the export -------------------------------------------


def test_the_protocol_version_has_advanced_by_exactly_one() -> None:
    """§11: "``PROTOCOL_VERSION`` moves by exactly one, in Q1" — 47 → 48.

    Two grounds and no third: ``ToolDefinition`` gains ``quoted_output`` and crosses a
    frame inside a ``PermissionDecision``; ``AuthorizationProjection`` gains ``quote``
    and crosses one inside a ``Confirmation``. **``Goal`` is not one of them.**
    """
    assert PROTOCOL_VERSION == 48


def test_the_export_carries_the_quotes_inside_its_goals_and_gains_no_member() -> None:
    """§11: ``PlanExport.schema_version`` advances and the document gains no member.

    An :class:`ActionQuote` rides **inside** ``Goal``, which ``goals`` already carries,
    so ADR-0014 §5's closure rule is satisfied by construction.
    """
    quote = _quote()
    export = PlanExport(
        exported_at=_WHEN,
        goals=(_goal(quotes=(quote,)),),
        evidence=(EvidenceHistory(goal_id="g1"),),
    )
    assert export.schema_version == 14
    assert "quotes" not in PlanExport.model_fields
    assert export.goals[0].quotes == (quote,)
    restored = PlanExport.model_validate_json(export.model_dump_json())
    assert restored.goals[0].quotes == (quote,)
    assert restored.schema_version == 14
