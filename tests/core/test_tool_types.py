"""The tool-declaration types enforce what ADR-0016 says they enforce.

Most of these pin a *rejection*. A `ToolDefinition` is the input to a permission
decision, so a contradictory or under-specified one must fail at construction
rather than reach a policy that has to guess.
"""

from __future__ import annotations

import operator
from datetime import timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from pydantic import ValidationError

from ai_assistant.core.types import (
    CostBasis,
    DataTier,
    Idempotency,
    Reversibility,
    RiskLevel,
    ToolCost,
    ToolDefinition,
)

if TYPE_CHECKING:
    from collections.abc import Callable

_FREE = ToolCost(basis=CostBasis.FREE)


def _definition(**overrides: object) -> ToolDefinition:
    """Build a valid definition with ``overrides`` applied."""
    fields: dict[str, object] = {
        "id": "smtp",
        "capability": "send_email",
        "description": "Send an email.",
        "risk_level": RiskLevel.HIGH,
        "reversibility": Reversibility.IRREVERSIBLE,
        "side_effecting": True,
        "reads": (DataTier.PERSONAL,),
        "writes": (),
        "discloses": (DataTier.PERSONAL,),
        "cost": _FREE,
        "idempotency": Idempotency.NONE,
    }
    fields.update(overrides)
    return ToolDefinition(**fields)  # type: ignore[arg-type]  # heterogeneous test kwargs


# --- severity ordering --------------------------------------------------


def test_risk_level_orders_by_severity_not_alphabetically() -> None:
    """The whole point: 'critical' < 'low' as strings, CRITICAL > LOW as risk."""
    assert RiskLevel.LOW < RiskLevel.MEDIUM < RiskLevel.HIGH < RiskLevel.CRITICAL
    assert RiskLevel.CRITICAL > RiskLevel.LOW
    assert not RiskLevel.CRITICAL < RiskLevel.LOW


def test_reversibility_orders_by_severity() -> None:
    assert Reversibility.REVERSIBLE < Reversibility.RECOVERABLE < Reversibility.IRREVERSIBLE


#: All four operators, so every ordering test below covers each of them rather
#: than ``__lt__`` alone — ``str`` supplies all four, so any one left underived
#: would silently keep the inherited lexicographic behaviour.
_ORDERINGS = (operator.lt, operator.le, operator.gt, operator.ge)


@pytest.mark.parametrize("level", list(RiskLevel))
def test_a_risk_level_compares_equal_to_its_own_value(level: RiskLevel) -> None:
    same = RiskLevel(level.value)

    assert level <= same
    assert level >= same
    assert not level < same


def test_severity_ordering_is_consistent_in_both_operand_orders() -> None:
    assert (RiskLevel.LOW < RiskLevel.HIGH) is (RiskLevel.HIGH > RiskLevel.LOW)
    assert (RiskLevel.HIGH <= RiskLevel.LOW) is (RiskLevel.LOW >= RiskLevel.HIGH)


@pytest.mark.parametrize("compare", _ORDERINGS)
@pytest.mark.parametrize("operand", ["medium", "critical", 1, None])
def test_comparing_a_risk_level_with_a_non_member_raises(
    compare: Callable[[object, object], bool], operand: object
) -> None:
    """Must raise, not answer.

    Returning ``NotImplemented`` would send Python to the reflected ``str``
    comparison, which answers lexicographically — the trap the overrides exist
    to close, surviving in exactly the mixed-type case a policy reading a
    threshold from configuration produces. ``"critical"`` is among the operands
    because that is the value the lexicographic answer gets most wrong.
    """
    with pytest.raises(TypeError):
        compare(RiskLevel.LOW, operand)

    with pytest.raises(TypeError):
        compare(operand, RiskLevel.LOW)


@pytest.mark.parametrize("compare", _ORDERINGS)
def test_the_two_scales_do_not_compare_with_each_other(
    compare: Callable[[object, object], bool],
) -> None:
    """Both rank from zero, so a cross-scale comparison would silently answer."""
    with pytest.raises(TypeError):
        compare(RiskLevel.LOW, Reversibility.IRREVERSIBLE)


def test_risk_level_still_serialises_as_its_string_value() -> None:
    """Ordering must not cost the readable value an audit record needs."""
    assert _definition().model_dump(mode="json")["risk_level"] == "high"


# --- data reach ---------------------------------------------------------


def test_data_tiers_are_sorted_most_sensitive_first_and_deduplicated() -> None:
    """Declaration order, not alphabetical — which would read as the reverse."""
    definition = _definition(
        reads=(DataTier.OPERATIONAL, DataTier.SECRET, DataTier.PERSONAL, DataTier.SECRET)
    )

    assert definition.reads == (DataTier.SECRET, DataTier.PERSONAL, DataTier.OPERATIONAL)


def test_data_reach_must_be_declared() -> None:
    """An omitted tuple would be the claim 'this tool touches no data'."""
    for field in ("reads", "writes", "discloses"):
        fields = {
            "id": "t",
            "capability": "c",
            "description": "d",
            "risk_level": RiskLevel.LOW,
            "reversibility": Reversibility.REVERSIBLE,
            "side_effecting": False,
            "reads": (),
            "writes": (),
            "discloses": (),
            "cost": _FREE,
            "idempotency": Idempotency.NONE,
        }
        del fields[field]
        with pytest.raises(ValidationError):
            ToolDefinition(**fields)  # type: ignore[arg-type]  # deliberately incomplete


# --- effect consistency -------------------------------------------------


def test_a_tool_that_writes_must_be_side_effecting() -> None:
    with pytest.raises(ValidationError, match="side-effecting"):
        _definition(writes=(DataTier.PERSONAL,), side_effecting=False)


def test_a_tool_that_discloses_must_be_side_effecting() -> None:
    """Forbids the inert-email definition: discloses PERSONAL, claims no effect."""
    with pytest.raises(ValidationError, match="side-effecting"):
        _definition(
            discloses=(DataTier.PERSONAL,),
            side_effecting=False,
            reversibility=Reversibility.REVERSIBLE,
        )


def test_a_tool_with_no_side_effect_must_be_reversible() -> None:
    with pytest.raises(ValidationError, match="nothing to reverse"):
        _definition(
            side_effecting=False,
            discloses=(),
            reversibility=Reversibility.IRREVERSIBLE,
        )


def test_a_reversible_tool_may_still_disclose() -> None:
    """Deliberately legal, and a later reader should not 'fix' it.

    Creating a hosted calendar event is REVERSIBLE — the tool deletes it — while
    the provider having seen the contents is permanent. Requiring disclosure to
    imply IRREVERSIBLE would make nearly every hosted integration irreversible
    and leave the scale with one useful value.
    """
    definition = _definition(reversibility=Reversibility.REVERSIBLE, discloses=(DataTier.PERSONAL,))

    assert definition.reversibility is Reversibility.REVERSIBLE


def test_a_read_only_tool_may_still_be_high_risk() -> None:
    """Risk is unconstrained by side_effecting: a mailbox dump is not low risk."""
    definition = _definition(
        side_effecting=False,
        discloses=(),
        writes=(),
        reversibility=Reversibility.REVERSIBLE,
        risk_level=RiskLevel.HIGH,
    )

    assert definition.risk_level is RiskLevel.HIGH


# --- description --------------------------------------------------------


@pytest.mark.parametrize(
    "blank",
    [
        "",
        "   ",
        "\n\t",
        "\xa0",  # non-breaking space: whitespace, so strip() catches it
        "\u200b",  # zero-width space: category Cf, so strip() does not
        "﻿",  # byte-order mark, likewise
        "⁣",  # invisible separator
        "\u200b﻿  ",  # a run of them, which is no more visible
        "\x00",  # a control character renders as nothing too
        "️",  # variation selector: category Mn, which a blocklist misses
        "͏",  # combining grapheme joiner, likewise
        "́̂",  # combining accents with no base character to sit on
        # Inside the visible whitelist, yet still rendering as nothing — the
        # exception list of ADR-0018 §1, which the category test alone lets past.
        "⠀",  # BRAILLE PATTERN BLANK (So, a symbol)
        "ㅤ",  # HANGUL FILLER (Lo, a letter)
        "ᅟ",  # HANGUL CHOSEONG FILLER
        "ᅠ",  # HANGUL JUNGSEONG FILLER
        "ﾠ",  # HALFWIDTH HANGUL FILLER
        "⠀ㅤ",  # a run of them is no more visible than one
    ],
)
def test_a_description_with_nothing_visible_is_refused(blank: str) -> None:
    """It is what the user is shown when approving.

    ``strip()`` alone would pass the zero-width cases: they are *format*
    characters, not whitespace, so a description made of them survives
    stripping while rendering as nothing at all.
    """
    with pytest.raises(ValidationError):
        _definition(description=blank)


def test_a_description_is_stripped() -> None:
    assert _definition(description="  Send an email.  ").description == "Send an email."


def test_an_invisible_character_beside_visible_text_is_fine() -> None:
    """The rule is 'something renders', not 'every character renders'."""
    assert _definition(description="Send\u200b an email.").description == "Send\u200b an email."


def test_a_blank_rendering_codepoint_beside_visible_text_is_fine() -> None:
    """Braille blank is legitimate padding when something else renders."""
    assert _definition(description="A\u2800B").description == "A\u2800B"


# --- cost ---------------------------------------------------------------


def test_a_priced_tool_carries_amount_and_currency() -> None:
    cost = ToolCost(basis=CostBasis.PER_CALL, amount=Decimal("0.002"), currency="USD")

    assert cost.amount == Decimal("0.002")


@pytest.mark.parametrize(
    ("amount", "currency"),
    [(None, "USD"), (Decimal("1"), None), (None, None)],
)
def test_a_per_call_cost_needs_both_amount_and_currency(
    amount: Decimal | None, currency: str | None
) -> None:
    with pytest.raises(ValidationError):
        ToolCost(basis=CostBasis.PER_CALL, amount=amount, currency=currency)


@pytest.mark.parametrize("basis", [CostBasis.FREE, CostBasis.UNKNOWN])
def test_an_unpriced_cost_carries_no_amount(basis: CostBasis) -> None:
    """FREE and UNKNOWN are declarations, not places to stash a number."""
    with pytest.raises(ValidationError):
        ToolCost(basis=basis, amount=Decimal("1"), currency="USD")


@pytest.mark.parametrize("amount", ["NaN", "Infinity", "-Infinity"])
def test_a_non_finite_cost_is_refused(amount: str) -> None:
    """Both satisfy ge=0 — NaN by making every comparison false — and neither
    has a JSON representation nor survives a running total."""
    with pytest.raises(ValidationError):
        ToolCost(basis=CostBasis.PER_CALL, amount=Decimal(amount), currency="USD")


def test_a_negative_cost_is_refused() -> None:
    with pytest.raises(ValidationError):
        ToolCost(basis=CostBasis.PER_CALL, amount=Decimal("-1"), currency="USD")


@pytest.mark.parametrize("currency", ["usd", "US", "USDD", "US1", "", "€€€"])
def test_a_malformed_currency_is_refused(currency: str) -> None:
    """Shape-checked, and deliberately not normalised: 'usd' is rejected, not upcast."""
    with pytest.raises(ValidationError):
        ToolCost(basis=CostBasis.PER_CALL, amount=Decimal("1"), currency=currency)


def test_cost_is_frozen() -> None:
    """Freezing the definition does not freeze what its cost field holds."""
    cost = ToolCost(basis=CostBasis.PER_CALL, amount=Decimal("1"), currency="USD")

    with pytest.raises(ValidationError):
        cost.amount = Decimal("1000")


# --- idempotency --------------------------------------------------------


def test_a_keyed_tool_requires_a_window() -> None:
    with pytest.raises(ValidationError, match="idempotency_window"):
        _definition(idempotency=Idempotency.KEYED)


@pytest.mark.parametrize("window", [timedelta(0), timedelta(seconds=-1)])
def test_a_keyed_window_must_be_strictly_positive(window: timedelta) -> None:
    """No retry can fall inside such a window, so the guarantee is unsatisfiable."""
    with pytest.raises(ValidationError, match="positive"):
        _definition(idempotency=Idempotency.KEYED, idempotency_window=window)


@pytest.mark.parametrize("guarantee", [Idempotency.NONE, Idempotency.NATURAL])
def test_an_unkeyed_tool_carries_no_window(guarantee: Idempotency) -> None:
    with pytest.raises(ValidationError, match="only valid for a KEYED"):
        _definition(idempotency=guarantee, idempotency_window=timedelta(hours=1))


# --- latency ------------------------------------------------------------


def test_a_negative_latency_is_refused() -> None:
    """Not a wrong guess but a nonsense one; it would invert a sort."""
    with pytest.raises(ValidationError, match="latency"):
        _definition(latency=timedelta(seconds=-1))


def test_zero_latency_is_allowed() -> None:
    """A purely local computation is legitimately instantaneous."""
    assert _definition(latency=timedelta(0)).latency == timedelta(0)


# --- immutability -------------------------------------------------------


def test_a_definition_is_frozen() -> None:
    definition = _definition()

    with pytest.raises(ValidationError):
        definition.risk_level = RiskLevel.LOW


def test_the_default_parameters_schema_is_immutable() -> None:
    """Pydantic does not validate defaults, so a `{}` literal would leak a dict."""
    definition = _definition()

    with pytest.raises(TypeError):
        definition.parameters_schema["type"] = "object"  # type: ignore[index]  # the point


def test_a_supplied_parameters_schema_is_frozen_all_the_way_down() -> None:
    definition = _definition(
        parameters_schema={"properties": {"to": {"type": "string"}}, "required": ["to"]}
    )

    nested = definition.parameters_schema["properties"]
    assert isinstance(nested, dict) is False
    assert definition.parameters_schema["required"] == ("to",)


def test_extra_fields_are_refused() -> None:
    """A misspelled safety field must not land silently as an extra."""
    with pytest.raises(ValidationError):
        _definition(risk_levl=RiskLevel.LOW)


# --- identifiers --------------------------------------------------------


@pytest.mark.parametrize("field", ["id", "capability"])
@pytest.mark.parametrize(
    "invisible",
    ["\u200b", "\ufeff", "\ufe0f", "\u200b\ufeff", " \u200b ", "\u2800", "\u3164", "\uffa0"],
)
def test_an_identifier_with_nothing_visible_is_refused(field: str, invisible: str) -> None:
    """A tool's id and capability appear in the same prompt as its description.

    ``Identifier`` alone only refuses a blank, so a zero-width id would render
    as nothing beside a description the type insists must render — and two such
    ids would be indistinguishable to the user approving them.
    """
    with pytest.raises(ValidationError):
        _definition(**{field: invisible})


@pytest.mark.parametrize("field", ["id", "capability"])
def test_an_identifier_is_stripped(field: str) -> None:
    assert getattr(_definition(**{field: "  smtp  "}), field) == "smtp"
