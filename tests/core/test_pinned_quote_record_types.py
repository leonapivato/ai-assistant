"""ADR-0271's ``core`` record: which values construct, and what a stored dump decodes to.

The **type-level** half of §8's arms, and **P1's alone**. P1 lands the record and the
wire bump; it sets no pin and reads no charge, so what is asserted here is exactly the
construction and decoding limbs of arms 1, 2 and 3.

**What is deliberately not here.** Arm 1's *"the pin is set ... exactly where the
evidence route decided something"* and its audit-trail close-and-reopen limb are
**P2's**: setting a pin is ``permissions`` deciding, and writing one to the trail needs
a policy that decided. Arm 2's one-read limb over a ``GoalQuotes`` fake is P2's for the
same reason. Arm 3's **reading** — the shapes an ``output`` yields a charge at — is
**P3's**, in the subsystem ADR-0262's own lane cut puts the comparison in; what is here
is arm 3's **declaration** limbs, which are the half a ``core`` type decides. Arms 4 and
5 are P3's whole.

``tests/core/test_action_quote_types.py`` is this file's precedent and it is written to
its shape.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError

from ai_assistant.core.types import (
    ActionQuote,
    ActionRequest,
    ChargedOutput,
    CostBasis,
    Idempotency,
    PermissionDecision,
    PermissionOutcome,
    PermissionRuling,
    QuotedOutput,
    Reversibility,
    RiskLevel,
    StepOutputRef,
    ToolCost,
    ToolDefinition,
)

_WHEN = datetime(2026, 1, 1, tzinfo=UTC)
_DIGEST = "a" * 64
_SUBJECT = "b" * 64


def _quote(*, action: str = "ia1", amount: str = "120", currency: str = "EUR") -> ActionQuote:
    """One quote at ADR-0267 §1's shape — the value a pin carries."""
    return ActionQuote(
        intended_action=action,
        arguments_digest=_DIGEST,
        amount=Decimal(amount),
        currency=currency,
        plan="p1",
        read_from=StepOutputRef(step="s1", field="price"),
        read_at=_WHEN,
    )


def _tool(**overrides: Any) -> ToolDefinition:
    """A declaration, optionally carrying a ``charged_output`` or a ``quoted_output``."""
    fields: dict[str, Any] = {
        "id": "book",
        "capability": "book_room",
        "description": "Book a room.",
        "risk_level": RiskLevel.MEDIUM,
        "reversibility": Reversibility.RECOVERABLE,
        "side_effecting": True,
        "reads": (),
        "writes": (),
        "discloses": (),
        "cost": ToolCost(basis=CostBasis.FREE),
        "idempotency": Idempotency.NONE,
    }
    fields.update(overrides)
    return ToolDefinition(**fields)


def _route_d(**overrides: Any) -> dict[str, Any]:
    """The row shape ADR-0254 §7 tells a route-(d) ``ALLOW`` by, as keyword arguments."""
    fields: dict[str, Any] = {
        "outcome": PermissionOutcome.ALLOW,
        "reason": "the authority covers it",
        "authorised_by": "auth-1",
        "authorised_subject": None,
        "authorised_goal": "g1",
    }
    fields.update(overrides)
    return fields


# --- ChargedOutput: §2's declaration ----------------------------------------


def test_a_charged_output_is_exactly_two_keys() -> None:
    """§2: *"a frozen model with ``extra="forbid"`` whose fields are exactly two"*.

    The roster is asserted rather than the two names alone, because the field a later
    lane would reach for — a third key, a unit, a tax component — is precisely what §2
    says the declaration does not carry.
    """
    charged = ChargedOutput(amount="total", currency="total_currency")

    assert set(ChargedOutput.model_fields) == {"amount", "currency"}
    assert ChargedOutput.model_config["extra"] == "forbid"
    assert ChargedOutput.model_config["frozen"] is True
    assert (charged.amount, charged.currency) == ("total", "total_currency")


def test_a_charged_output_refuses_one_key_for_both_facts() -> None:
    """§2: *"A model validator refuses ``amount`` equal to ``currency``"* — arm 3.

    The arm that fails an implementation omitting the validator. One key cannot carry
    both a number and an ISO-4217 code, so such a declaration would report **no charge
    at every act**, silently, and no call under it would ever be satisfying. Refusing
    at construction is where the integration author sees it.
    """
    with pytest.raises(ValidationError, match="named for both the amount and the currency"):
        ChargedOutput(amount="total", currency="total")


def test_a_charged_output_splits_no_key_so_depth_stays_one() -> None:
    """§2, on ADR-0267 §3: *"Depth is one and no lane adds an addressing syntax"*.

    Enforced by carrying **no** validator for it rather than by a blacklist: nothing
    splits the string, so a key is looked up whole and a nested value is unreachable
    however the key is spelled. A provider's flat ``"total.charged"`` is therefore an
    ordinary key and is admitted — the same reading ``QuotedOutput`` is given, and the
    arm that fails a lane adding a ``.``/``[``/``]``/``*`` refusal this record does not
    have.
    """
    charged = ChargedOutput(amount="total.charged", currency="total[0]")

    assert charged.amount == "total.charged"
    assert charged.currency == "total[0]"


def test_a_charged_output_is_not_a_quoted_output_however_alike_they_look() -> None:
    """§2: *"it is its own type and not ``QuotedOutput`` reused"*.

    The two name different facts — a quote is **prospective** and a charge
    **retrospective** — so they are distinct classes even where their two keys agree,
    and neither validates as the other. The arm that fails a lane aliasing one to the
    other to save a class: an alias would make ``isinstance`` true here and would let a
    later reading pick the estimate where the total was meant.
    """
    assert len({ChargedOutput, QuotedOutput}) == 2
    assert not issubclass(ChargedOutput, QuotedOutput)
    assert not issubclass(QuotedOutput, ChargedOutput)
    assert ToolDefinition.model_fields["charged_output"].annotation == ChargedOutput | None
    assert ToolDefinition.model_fields["quoted_output"].annotation == QuotedOutput | None


# --- ToolDefinition.charged_output: §2's declaration on the record ----------


def test_a_declaration_carries_a_charged_output_or_carries_none() -> None:
    """§2 and arm 3: *"a ``ToolDefinition`` with and without ``charged_output``"*.

    ``None`` is the default and *"a declaration carrying ``None`` reports no charge
    ever"* — the fail-closed direction, and ADR-0016 §1's *"Declared, not inferred"*
    read as this decision's fifth exception to the required-field rule.
    """
    assert _tool().charged_output is None
    assert ToolDefinition.model_fields["charged_output"].default is None

    declared = _tool(charged_output=ChargedOutput(amount="charged", currency="charged_ccy"))

    assert declared.charged_output == ChargedOutput(amount="charged", currency="charged_ccy")


def test_a_declaration_may_carry_both_fields_and_nothing_compares_them() -> None:
    """§2: *"A declaration may carry both, one or neither"*, the same keys included.

    *"No clause compares them, requires them to agree, or refuses either on the other's
    account"* — so a declaration whose estimate and settled total sit at **one** key
    constructs, and so does one whose two readings sit at different keys. The arm that
    fails an implementation adding a cross-field validator here, which would refuse the
    very declaration §2 exists to admit: an output carrying an estimate at one key and
    a settled total at another.
    """
    same = _tool(
        quoted_output=QuotedOutput(amount="price", currency="ccy"),
        charged_output=ChargedOutput(amount="price", currency="ccy"),
    )
    different = _tool(
        quoted_output=QuotedOutput(amount="estimate", currency="ccy"),
        charged_output=ChargedOutput(amount="settled", currency="settled_ccy"),
    )

    assert same.quoted_output is not None
    assert same.charged_output is not None
    assert (same.quoted_output.amount, same.charged_output.amount) == ("price", "price")
    assert different.charged_output == ChargedOutput(amount="settled", currency="settled_ccy")


def test_a_declaration_written_before_this_field_decodes_carrying_none() -> None:
    """§8: *"a stored ``ToolDefinition`` with ``charged_output`` absent"*, arm 3's limb.

    ``ToolDefinition`` sets ``extra="forbid"``, so the claim is the **absence** of the
    key rather than a tolerated unknown one: a dump written before this decision has no
    ``charged_output`` at all and validates to ``None``, which reports no charge. The
    arm that fails a lane making the field required — that would refuse every
    definition already on disk, and §8 forbids *"no decision record is rewritten,
    back-filled or re-decided"*.
    """
    dumped = _tool().model_dump(mode="json")
    del dumped["charged_output"]

    assert ToolDefinition.model_validate(dumped).charged_output is None


def test_a_charged_output_survives_a_json_round_trip_byte_for_byte() -> None:
    """Arm 1's decoding half, taken at the type rather than at the trail.

    The audit trail's close-and-reopen is **P2's** arm — writing a record needs a
    policy that decided — but what makes it possible is that the declaration's new
    member survives ``model_dump(mode="json")`` and revalidates to an equal value.
    Asserted here because a serialisation that dropped it would leave verification with
    no declaration to read a charge under, and the failure would surface three lanes
    later.
    """
    declared = _tool(charged_output=ChargedOutput(amount="charged", currency="charged_ccy"))
    dumped = declared.model_dump(mode="json")

    assert dumped["charged_output"] == {"amount": "charged", "currency": "charged_ccy"}
    assert ToolDefinition.model_validate(dumped) == declared


# --- PermissionRuling.proved_quote: §1's pin --------------------------------


def test_a_route_d_allow_carries_the_quote_it_was_proved_against() -> None:
    """§1: the pin constructs on the one row shape it is set on.

    ``authorised_goal`` set is ADR-0254 §7's route-(d) discriminator, and the quote is
    carried **by value** — the ``ActionQuote`` itself, equal to the value handed in.
    """
    quote = _quote()
    ruling = PermissionRuling(**_route_d(proved_quote=quote))

    assert ruling.proved_quote == quote
    assert ruling.model_dump(mode="json")["proved_quote"] == {
        "intended_action": "ia1",
        "arguments_digest": _DIGEST,
        "amount": "120",
        "currency": "EUR",
        "plan": "p1",
        "read_from": {"step": "s1", "field": "price"},
        "read_at": "2026-01-01T00:00:00Z",
    }, "all seven values inline — by value, and no handle on a row read elsewhere"


def test_a_route_d_allow_that_proved_nothing_carries_no_pin() -> None:
    """§1: *"It does not require the converse"*, and that asymmetry is deliberate.

    A route-(d) ``ALLOW`` whose coverage carried no ``MONEY`` member sets
    ``authorised_goal`` and pins nothing, which is the ordinary shape and must stay
    constructible. The arm that fails a validator written as an equivalence.
    """
    assert PermissionRuling(**_route_d()).proved_quote is None
    assert PermissionRuling.model_fields["proved_quote"].default is None


@pytest.mark.parametrize(
    ("shape", "overrides"),
    [
        ("no authorisation at all", {"authorised_by": None, "authorised_goal": None}),
        (
            "route (b) — a grant digest and no goal",
            {"authorised_subject": _SUBJECT, "authorised_goal": None},
        ),
        ("route (c) — a pointer and neither of the two", {"authorised_goal": None}),
    ],
)
def test_a_pin_is_refused_on_every_row_no_evidence_route_was_taken_over(
    shape: str, overrides: dict[str, Any]
) -> None:
    """§1 and arm 1's validator case: the three row shapes §7 tells the others by.

    *"A model validator refuses it set where ``authorised_goal`` is unset"*. The last
    two shapes are the arm that fails **a validator gating on ``authorised_by``
    alone**: both carry a pointer, so such a validator would admit a quote proved for a
    goal-scoped authority on a row that names no goal — a pin over a comparison nobody
    made. The first is refused too, ``_a_scope_needs_the_authorisation_it_scopes``
    already making a scope without a pointer unconstructible.
    """
    with pytest.raises(ValidationError, match="proved against no quote"):
        PermissionRuling(**_route_d(proved_quote=_quote(), **overrides))
    assert shape


@pytest.mark.parametrize("outcome", [PermissionOutcome.CONFIRM, PermissionOutcome.DENY])
def test_a_question_and_a_refusal_carry_no_pin(outcome: PermissionOutcome) -> None:
    """Arm 1: *"a ``CONFIRM``, a ``DENY`` ... each record **none**"*, at construction.

    Neither is reachable **with** a pin at all, and the reason is that the refusals
    compose: a non-``ALLOW`` cites no authorisation, so it scopes none, so it was
    proved against nothing. Asserted because the composition is what lets this decision
    add **one** validator rather than four.
    """
    with pytest.raises(ValidationError):
        PermissionRuling(outcome=outcome, reason="no", authorised_goal="g1", proved_quote=_quote())


def test_the_pin_is_a_value_and_the_record_holds_no_handle_on_one() -> None:
    """§1: *"carried by value and named by nothing, and no identifier is minted"*.

    The annotation is the model and not an identifier, and ``ActionQuote`` still
    carries no id — *"No lane mints a quote id, adds a field to ``ActionQuote``, keys a
    record on one"*. The arm that fails a lane replacing the value with a key on the
    act and the digest, which names **the governing** quote at the instant of the read
    and so drifts off the reading the pin exists to fix.
    """
    assert PermissionRuling.model_fields["proved_quote"].annotation == ActionQuote | None
    assert "id" not in ActionQuote.model_fields
    assert set(ActionQuote.model_fields) == {
        "intended_action",
        "arguments_digest",
        "amount",
        "currency",
        "plan",
        "read_from",
        "read_at",
    }


def test_the_ruling_takes_its_own_copy_of_the_quote_it_pins() -> None:
    """§1's *"carried by value"*, made true against a holder that still has the object.

    Pydantic passes an already-valid model instance through without copying, so without
    :func:`~ai_assistant.core.types._detached_quote` a ruling would share whatever
    instance ``GoalQuotes.for_action`` returned — and ``object.__setattr__`` on that
    original would change which price the row says condition 6 was proved against,
    **after** the comparison was made. ``from_request`` deep-copies the ruling on the
    way to the record, so the window is narrow; it is nonetheless the window ADR-0018
    §3 drew the boundary at, and the two detachments beside this one
    (``ActionRequest.tool``, ``ActionRequest.egress_binding``) close the same shape.
    The arm that fails an implementation taking the caller's instance.
    """
    quote = _quote(amount="120")
    ruling = PermissionRuling(**_route_d(proved_quote=quote))

    object.__setattr__(quote, "amount", Decimal("999"))

    assert ruling.proved_quote is not None
    assert ruling.proved_quote.amount == Decimal("120")
    assert ruling.proved_quote is not quote


def test_a_quote_corrupted_past_its_own_guard_is_refused_at_the_ruling() -> None:
    """§1's detachment rebuilds through validation rather than merely deep-copying.

    ``_detached_tool``'s reason, one record over: a value assembled by
    ``model_construct``, or written back past its frozen model's guard, has passed no
    validator, and the pin reaches a durable record ADR-0021 §4 requires to survive a
    ``model_dump(mode="json")`` round trip. Revalidating at the ruling is what puts the
    refusal where it can be read instead of at the trail, a restart later.
    """
    quote = _quote()
    object.__setattr__(quote, "currency", "eur")

    with pytest.raises(ValidationError, match="three uppercase"):
        PermissionRuling(**_route_d(proved_quote=quote))


def test_a_later_quote_leaves_a_pinned_one_untouched() -> None:
    """Arm 2's by-value limb, at the type: *"a value and not a pointer"*.

    ``PermissionRuling`` is frozen and the quote is embedded, so a goal that appends a
    further reading afterwards changes nothing about what this row says condition 6 was
    evaluated against. Which quote a **policy** selects is P2's arm; that the record
    cannot be moved by a later append is this one's.
    """
    ruling = PermissionRuling(**_route_d(proved_quote=_quote(amount="120")))
    later = _quote(amount="130")

    assert later != ruling.proved_quote
    assert ruling.proved_quote is not None
    assert ruling.proved_quote.amount == Decimal("120")
    with pytest.raises(ValidationError):
        ruling.proved_quote = later  # frozen, and the refusal is what is asserted


# --- The durable record: §1's "PermissionDecision gains no field" -----------


def test_the_decision_gains_no_field_and_transcribes_the_ruling_whole() -> None:
    """§1: *"``PermissionDecision`` gains no field"*, ``from_request`` gaining none either.

    The pin reaches the durable record by the path that exists today — ADR-0254 §16's
    own construction for ``authorised_goal``, one field over. The roster is asserted
    because a second copy of the quote on the decision is exactly the shape a later
    lane would reach for, and two assertions of one fact are what ADR-0254 §16 declined
    for the goal.
    """
    quote = _quote()
    request = ActionRequest(tool=_tool(), parameters={"room": "12"}, intended_action="ia1")
    ruling = PermissionRuling(**_route_d(proved_quote=quote))

    decision = PermissionDecision.from_request(request, ruling, id="d-1", decided_at=_WHEN)

    assert decision.ruling.proved_quote == quote
    assert "proved_quote" not in PermissionDecision.model_fields
    assert "quote" not in PermissionDecision.model_fields


def test_a_decision_carrying_both_new_members_round_trips_byte_for_byte() -> None:
    """Arm 1's decoding half over the whole record, and the reason it is one arm.

    A decision embeds the ruling **and** the declaration by value, so one dump carries
    both members; the arm fails a serialisation that drops **either**, which would
    leave verification with no pin to compare against and no declaration to read a
    charge under. The trail's own close-and-reopen is P2's — it needs a policy that
    decided — and this is the property that one rests on.
    """
    declared = _tool(charged_output=ChargedOutput(amount="charged", currency="charged_ccy"))
    request = ActionRequest(tool=declared, parameters={"room": "12"}, intended_action="ia1")
    decision = PermissionDecision.from_request(
        request,
        PermissionRuling(**_route_d(proved_quote=_quote())),
        id="d-1",
        decided_at=_WHEN,
    )

    dumped = decision.model_dump(mode="json")

    assert dumped["ruling"]["proved_quote"]["amount"] == "120"
    assert dumped["tool"]["charged_output"] == {"amount": "charged", "currency": "charged_ccy"}
    assert PermissionDecision.model_validate(dumped) == decision


def test_a_decision_written_before_this_field_decodes_carrying_none() -> None:
    """§8: *"a stored ``PermissionDecision`` decodes with ``proved_quote`` absent"*.

    Both models set ``extra="forbid"``, so the claim is about a key that is not there
    rather than one that is ignored. *"No decision record is rewritten, back-filled or
    re-decided"* — and §1 adds that it is **never** back-filled, a decision recorded
    without a pin being a decision whose dispatch was not proved against a quote.
    """
    request = ActionRequest(tool=_tool(), parameters={"room": "12"}, intended_action="ia1")
    decision = PermissionDecision.from_request(
        request,
        PermissionRuling(**_route_d()),
        id="d-1",
        decided_at=_WHEN,
    )
    dumped = decision.model_dump(mode="json")
    del dumped["ruling"]["proved_quote"]
    del dumped["tool"]["charged_output"]

    decoded = PermissionDecision.model_validate(dumped)

    assert decoded.ruling.proved_quote is None
    assert decoded.tool.charged_output is None
