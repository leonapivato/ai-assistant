"""ADR-0271 §8's arms 3, 4 and 5 — the charge reading, the comparison, and the finding.

§2's reading is driven **directly**, as a function of one declaration and one stored
output, so an arm about a refused shape is an arm about the reading and not about a
verdict four layers away. §§3-4's comparison is driven through
:func:`~ai_assistant.orchestration.verification.compare`, over the same controlled fakes
:mod:`test_verification_comparison` uses (ADR-0255 §13): **no live integration and no
real charge**, which is §8's own rule for every arm of this decision.

**The two operands an arm varies are the pin and the declaration** — the quote
``ActionPolicy.decide`` proved the dispatch against (§1) and the
``charged_output`` the tool author declared (§2) — and *"the operands are the policy's
pinned quote, the tool author's declaration and the provider's returned output, and
there is no fourth"*. **Nothing here builds a planner value at all.**
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from verification_builders import (
    CHARGED,
    DIGEST,
    EXECUTION,
    OTHER_DIGEST,
    RIVERSIDE,
    UNDER_150,
    Decisions,
    Executions,
    Rows,
    a_charge,
    a_criterion,
    a_decision,
    a_goal,
    a_member,
    a_quote,
    a_row,
    a_ruling,
    a_step,
    a_tool,
    an_attempt,
    an_execution,
    field_equals,
    field_present,
    paired,
)

from ai_assistant.core.types import (
    AttemptOutcome,
    AttemptReport,
    BoundKind,
    ChargedOutput,
    QuotedOutput,
    Reversibility,
    StepStatus,
)
from ai_assistant.orchestration.charges import ChargeTest, charge_read, charge_test
from ai_assistant.orchestration.verification import CriterionResult, Rung, compare

if TYPE_CHECKING:
    from collections.abc import Mapping

    from ai_assistant.core.types import (
        ActionQuote,
        CoverageMember,
        FrozenJson,
        PermissionDecision,
        StepExecution,
        ToolDefinition,
    )
    from ai_assistant.orchestration.verification import Comparison

_BOOKED = (field_equals("status", "confirmed"), field_present("reservation_id"))
"""The two postconditions §2's own satisfying test reads, beside the charge test."""

_HOLDS: Mapping[str, FrozenJson] = {"status": "confirmed", "reservation_id": "r-9"}
_REFUSES: Mapping[str, FrozenJson] = {"status": "rejected", "reservation_id": "r-9"}


def _booked(charge: Mapping[str, FrozenJson] | None = None) -> dict[str, FrozenJson]:
    """A booking step's stored output: its declared postconditions, plus a charge."""
    return {**_HOLDS, **(charge or {})}


def _charging_tool(quoted_output: QuotedOutput | None = None) -> ToolDefinition:
    """The consequential booking declaration, reporting what it charged (§2).

    ``quoted_output`` is the one field an arm varies beside it, because *"a declaration
    may carry both, one or neither"* and no clause compares them.
    """
    return a_tool(
        postconditions=_BOOKED,
        reversibility=Reversibility.IRREVERSIBLE,
        charged_output=CHARGED,
        quoted_output=quoted_output,
    )


async def _money(
    *steps: StepExecution,
    decisions: tuple[PermissionDecision, ...],
    member: CoverageMember | None = None,
    also: tuple[object, ...] = (),
) -> Comparison:
    """Compare a goal whose one criterion is *up to 150 euros*, against ``member``.

    ``also`` prepends further criteria, for arm 5's *"one further criterion met"* pair.
    """
    criteria = (*also, a_criterion(UNDER_150))
    rows = Rows(
        a_row("auth-1", member if member is not None else a_member(UNDER_150, kind=BoundKind.MONEY))
    )
    held, ruled = paired(rows.held, decisions)
    rows.reconcile(held)
    return await compare(
        a_goal(*criteria),  # type: ignore[arg-type]  # `also` is a criterion tuple
        an_attempt(EXECUTION),
        executions=Executions(an_execution(*steps)),
        decisions=Decisions(*ruled),
        rows=rows,
    )


def _money_result(comparison: Comparison) -> CriterionResult:
    """The money criterion's own result — the last of the goal's criteria."""
    return comparison.results[-1]


def _pinned(
    charge: Mapping[str, FrozenJson] | None,
    *,
    quote: ActionQuote | None = None,
    decision_id: str = "d-1",
    digest: str = DIGEST,
    definition: ToolDefinition | None = None,
) -> PermissionDecision:
    """A route-(d) booking decision, with the quote it was proved against pinned."""
    del charge
    return a_decision(
        decision_id,
        definition=definition if definition is not None else _charging_tool(),
        digest=digest,
        ruling=a_ruling(proved_quote=quote if quote is not None else a_quote()),
    )


# --------------------------------------------------------------------------- #
# Arm 3 — the charge reading is total and fail-closed, and nothing in it raises #
# --------------------------------------------------------------------------- #


def test_a_json_string_and_a_json_integer_are_the_two_shapes_that_read() -> None:
    """§2: *"a JSON **string** a ``Decimal`` accepts or a JSON **integer**"*, and no third.

    The two that yield a charge, and the arm every refusal below is stated against.
    """
    string = charge_read(_charging_tool(), a_charge("120.50"))
    integer = charge_read(_charging_tool(), a_charge(120))

    assert string is not None
    assert string.amount == Decimal("120.50")
    assert string.currency == "EUR"
    assert integer is not None
    assert integer.amount == Decimal(120)


@pytest.mark.parametrize(
    ("amount", "why"),
    [
        (120.5, "a JSON float is never a price (ADR-0254 §4, at the charge)"),
        (True, "a JSON boolean is not a JSON integer, though `bool` subclasses `int`"),
        (-1, "an amount is not negative"),
        ("-0.01", "a negative amount as a string is refused on the same ground"),
        ("not-a-number", "a string `Decimal` refuses"),
        ("", "the empty string, which `Decimal` also refuses"),
        ("NaN", "a string `Decimal` **accepts** as a non-finite value"),
        ("Infinity", "likewise accepted and likewise not finite"),
        ("-Infinity", "likewise"),
        ("nan", "the same in the case a careless reading would fold"),
        (None, "a JSON null states no amount"),
        ({"total": "120"}, "a nested object is unreachable — depth is one (§2)"),
    ],
)
def test_every_refused_amount_yields_no_charge_and_raises_nothing(
    amount: FrozenJson, why: str
) -> None:
    """§2: *"every failure of that reading yields no charge … and raises nothing"*.

    **The non-finite trio is the pair a natural implementation reaches by accident**
    (§2): ``Decimal("NaN")`` constructs without complaint and ``Decimal("sNaN") < 0``
    raises rather than answering, so an implementation comparing before it tests
    finiteness lets an ``InvalidOperation`` escape into verification. **And a ``bool``
    is not an ``int`` here**, the arm failing an implementation written as an ``int``
    instance test — ``True`` would read as a one-unit charge agreeing with almost any
    quote.
    """
    assert charge_read(_charging_tool(), a_charge(amount)) is None, why


@pytest.mark.parametrize(
    ("currency", "why"),
    [
        ("usd", "a lowercase code is not upcast — shape and never a register (ADR-0267 §1)"),
        ("EURO", "four letters is not an ISO-4217 alphabetic code"),
        ("EU", "nor is two"),
        ("E1R", "nor is a code carrying a digit"),
        ("€", "nor is a symbol"),
        (978, "a currency that is not a JSON string at all — an integer"),
        (True, "…a boolean, which a string operation applied first would accept"),
        (None, "…or null"),
    ],
)
def test_every_refused_currency_yields_no_charge_and_raises_nothing(
    currency: FrozenJson, why: str
) -> None:
    """§2, arm 3: the non-string currencies and the mis-shaped ones, each yielding none.

    *"The non-string currencies being what an implementation applying a string
    operation before a type test reaches by accident"* — ``978`` and ``True`` each have
    no ``.isupper()``, so the type test runs first here.
    """
    assert charge_read(_charging_tool(), a_charge("120", currency)) is None, why


@pytest.mark.parametrize(
    ("output", "why"),
    [
        ({CHARGED.currency: "EUR"}, "the amount key is missing"),
        ({CHARGED.amount: "120"}, "the currency key is missing"),
        ({}, "both are"),
        ({"total": "120", "iso": "EUR"}, "the declaration names neither key present"),
        ("120 EUR", "an output that is not an object at all"),
        (["120", "EUR"], "…nor is a list"),
        (None, "…nor is null"),
        (120, "…nor is a bare number"),
    ],
)
def test_an_output_the_declaration_cannot_be_read_against_yields_no_charge(
    output: FrozenJson, why: str
) -> None:
    """§2: *"an ``output`` that is not an object, a missing key at either name"*."""
    assert charge_read(_charging_tool(), output) is None, why


def test_a_declaration_carrying_no_charged_output_yields_no_charge() -> None:
    """§2: *"a declaration carrying ``None`` reports no charge ever"*.

    The fail-closed default, and ADR-0016 §1's *"Declared, not inferred"* — which is
    why the charge sitting **in the output** changes nothing: the declaration is what
    says where an act reports one.
    """
    assert charge_read(a_tool(postconditions=_BOOKED), a_charge("120")) is None


def test_the_charge_is_never_read_from_a_quoted_output() -> None:
    """§2: *"the two fields are read for their own fact and never for each other's"*.

    A declaration carrying a ``quoted_output`` and **no** ``charged_output``, over an
    output carrying a price at the quoted key: no charge. **The arm that fails an
    implementation reading a charge at ``quoted_output``** — which would make *"the
    acting step's own appended reading"* the operand, the defect #2409 names.
    """
    quoting = a_tool(
        postconditions=_BOOKED,
        quoted_output=QuotedOutput(amount="price", currency="price_currency"),
    )

    assert charge_read(quoting, {"price": "120", "price_currency": "EUR"}) is None


def test_a_declaration_carrying_both_reads_each_at_its_own_key() -> None:
    """§2: *"A declaration may carry both, one or neither"*, and neither defaults.

    The estimate sits at the quoted key and the settled total at the charged one, which
    is §2's own reason for minting a second type: *"selecting the estimate hides the
    very mismatch this decision exists to report"*.
    """
    both = _charging_tool(QuotedOutput(amount="price", currency="price_currency"))
    read = charge_read(both, {"price": "100", "price_currency": "EUR", **a_charge("130")})

    assert read is not None
    assert read.amount == Decimal(130)


def test_charged_output_refuses_construction_with_one_key_for_both() -> None:
    """§2's validator: *"A model validator refuses ``amount`` equal to ``currency``"*.

    **The arm that fails an implementation omitting it**: one key cannot carry both a
    number and an ISO-4217 code, so such a declaration would silently report no charge
    at every act.
    """
    with pytest.raises(ValueError, match="amount"):
        ChargedOutput(amount="total", currency="total")


# --------------------------------------------------------------------------- #
# Arm 4 — the comparison, the finding, and §3's ordering                       #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("amount", "expected", "why"),
    [
        ("120", ChargeTest.HOLDS, "equal to the pin, inside the ceiling"),
        ("100", ChargeTest.HOLDS, "under the pin, inside the ceiling"),
        ("130", ChargeTest.FAILS, "above the pin though under the 150 ceiling — the finding"),
    ],
)
def test_the_amount_conjunct_against_a_pin_at_120_under_a_150_ceiling(
    amount: str, expected: ChargeTest, why: str
) -> None:
    """§3, arm 4: *"``130`` fails it though it is under the ceiling"*.

    **The comparison the corpus could not make before** (§7): the one reading available
    until now — charge against ceiling — passes exactly the case the owner's ruling
    singles out.
    """
    assert (
        charge_test(
            status=StepStatus.SUCCEEDED,
            definition=_charging_tool(),
            output=a_charge(amount),
            pinned=a_quote("120"),
            member=a_member(UNDER_150, kind=BoundKind.MONEY),
        )
        is expected
    ), why


def test_a_charge_in_another_currency_fails_the_test() -> None:
    """§3: *"byte for byte, no conversion, no fold and no register consulted"*.

    ``"120"``/``"USD"`` against a pin at ``"120"``/``"EUR"`` **fails** — and §6 books
    what a cross-currency act proves, *"no lane adds a rate, a table, a tolerance or a
    rounding"*.
    """
    assert (
        charge_test(
            status=StepStatus.SUCCEEDED,
            definition=_charging_tool(),
            output=a_charge("120", "USD"),
            pinned=a_quote("120", "EUR"),
            member=a_member(UNDER_150, kind=BoundKind.MONEY),
        )
        is ChargeTest.FAILS
    )


def test_the_member_conjunct_is_driven_on_its_own() -> None:
    """§3's third conjunct, arm 4: *"against a member bounded at ``110``-``150``/EUR…"*.

    A charge of ``"100"`` against a pin at ``"120"`` **fails** the test *"though it
    agrees with the quote and is under the ceiling"* — **the arm failing an
    implementation testing currency and *not greater than the quote* only**. The same
    charge against a member carrying no ``minimum`` holds, which is what makes the arm
    about the conjunct rather than about the figure.
    """
    bounded = a_member(UNDER_150, kind=BoundKind.MONEY, minimum="110")

    assert (
        charge_test(
            status=StepStatus.SUCCEEDED,
            definition=_charging_tool(),
            output=a_charge("100"),
            pinned=a_quote("120"),
            member=bounded,
        )
        is ChargeTest.FAILS
    )
    assert (
        charge_test(
            status=StepStatus.SUCCEEDED,
            definition=_charging_tool(),
            output=a_charge("100"),
            pinned=a_quote("120"),
            member=a_member(UNDER_150, kind=BoundKind.MONEY),
        )
        is ChargeTest.HOLDS
    )


def test_the_members_currency_is_read_at_the_quotes_own_currency() -> None:
    """ADR-0266 §7's comparison shape: the currency conjunct *"at the quote's own"*.

    A member bounded in ``GBP`` is satisfied by no charge proved against a ``EUR``
    quote, however small the amount — *"and at no key of the request"*, there being no
    request here at all.
    """
    assert (
        charge_test(
            status=StepStatus.SUCCEEDED,
            definition=_charging_tool(),
            output=a_charge("10"),
            pinned=a_quote("120", "EUR"),
            member=a_member(UNDER_150, kind=BoundKind.MONEY, currency="GBP"),
        )
        is ChargeTest.FAILS
    )


def test_a_strict_ceiling_is_read_strictly() -> None:
    """ADR-0266 §3: *"under 150 euros"* does not cover a charge at exactly ``150``.

    **No endpoint is ever widened** — the difference is a cent in the direction that
    would report an amount the user's own words refuse.
    """
    exclusive = a_member(UNDER_150, kind=BoundKind.MONEY, maximum_exclusive=True)
    at_the_endpoint = {
        "status": StepStatus.SUCCEEDED,
        "definition": _charging_tool(),
        "output": a_charge("150"),
        "pinned": a_quote("150"),
    }

    assert charge_test(**at_the_endpoint, member=exclusive) is ChargeTest.FAILS  # type: ignore[arg-type]
    assert (
        charge_test(**at_the_endpoint, member=a_member(UNDER_150, kind=BoundKind.MONEY))  # type: ignore[arg-type]
        is ChargeTest.HOLDS
    )


@pytest.mark.parametrize(
    ("status", "pinned", "definition", "why"),
    [
        (StepStatus.FAILED, True, True, "the step is not SUCCEEDED"),
        (StepStatus.INDETERMINATE, True, True, "…in any other status either"),
        (StepStatus.SUCCEEDED, False, True, "the decision carries no proved_quote"),
        (StepStatus.SUCCEEDED, True, False, "the declaration carries no charged_output"),
    ],
)
def test_the_four_ways_the_test_is_not_taken_at_all(
    status: StepStatus, pinned: bool, definition: bool, why: str
) -> None:
    """§3: *"It is **not taken at all** where…"*, and the fourth is *"no charge reads"*.

    The fourth is every case of arm 3 above, which is why it is not repeated here.
    """
    assert (
        charge_test(
            status=status,
            definition=_charging_tool() if definition else a_tool(postconditions=_BOOKED),
            output=a_charge("120"),
            pinned=a_quote() if pinned else None,
            member=a_member(UNDER_150, kind=BoundKind.MONEY),
        )
        is ChargeTest.NOT_TAKEN
    ), why


async def test_an_agreeing_charge_makes_the_money_criterion_met() -> None:
    """§4: ADR-0262 §2's blanket **reversed** — such a criterion is now ``met``.

    A booking whose declarations hold and whose charge agrees with the quote its
    dispatch was proved against, inside the user's own ceiling. **The attempt is
    ``VERIFIED``**, which is §7's *"A goal that spends money can reach ``ACHIEVED``"*.
    """
    comparison = await _money(
        a_step("s-1", output=_booked(a_charge("120"))),
        decisions=(_pinned(a_charge("120")),),
    )

    assert _money_result(comparison) is CriterionResult.MET
    assert comparison.rung is Rung.CONSEQUENTIAL
    assert comparison.outcome is AttemptOutcome.VERIFIED


async def test_a_disagreeing_charge_makes_the_money_criterion_unmet() -> None:
    """§3: *"a charge that disagrees is the finding"*, reported as the criterion's result.

    ``130`` charged against a ``120`` pin under a ``150`` ceiling. The criterion is
    **unmet** — §2's own result over the call the disagreeing step belongs to, *"and
    never a result of this decision's own"*.
    """
    comparison = await _money(
        a_step("s-1", output=_booked(a_charge("130"))),
        decisions=(_pinned(a_charge("130")),),
    )

    assert _money_result(comparison) is CriterionResult.UNMET


@pytest.mark.parametrize(
    ("decision", "why"),
    [
        (
            a_decision("d-1", definition=_charging_tool(), ruling=a_ruling()),
            "no pin: the dispatch was not proved against a quote, and none is back-filled",
        ),
        (
            a_decision(
                "d-1",
                definition=a_tool(postconditions=_BOOKED, reversibility=Reversibility.IRREVERSIBLE),
                ruling=a_ruling(proved_quote=a_quote()),
            ),
            "no charged_output: such a declaration reports no charge ever",
        ),
    ],
)
async def test_a_test_not_taken_leaves_the_criterion_unestablished(
    decision: PermissionDecision, why: str
) -> None:
    """§4: *"what an unreadable charge blocks is **satisfaction by that call**"*.

    Limb 2 requires the charge test to **hold**, so such a step reaches limb 3 and the
    call establishes nothing — the criterion ``unestablished`` where its every call is
    one, *"never ``met``"*. **This is the pre-P3 shape kept as the no-charge-reported
    control**, and it is what ADR-0262 §12's own ``MONEY`` arm still asserts.
    """
    comparison = await _money(a_step("s-1", output=_booked(a_charge("120"))), decisions=(decision,))

    assert _money_result(comparison) is CriterionResult.UNESTABLISHED, why
    assert comparison.outcome is AttemptOutcome.UNCERTAIN


async def test_a_failed_step_is_decisive_in_no_case() -> None:
    """§3: *"a ``FAILED`` step reaches limb 3 in every case"*.

    Under a pin and a charging declaration, and still **unestablished** rather than
    ``unmet``: *"a failure returns no answer to hold a declaration against"* (ADR-0029
    §3), and the charge test is taken over a ``SUCCEEDED`` step alone.

    **Such a step carries no output at all** — ``StepExecution`` refuses one on any
    status but ``SUCCEEDED`` — so the record could not report a charge here even if the
    reading were attempted, which is the model making §3's guard true one layer down.
    The guard itself is driven over every non-``SUCCEEDED`` status in
    :func:`test_the_four_ways_the_test_is_not_taken_at_all`.
    """
    comparison = await _money(
        a_step("s-1", status=StepStatus.FAILED),
        decisions=(_pinned(None),),
    )

    assert _money_result(comparison) is CriterionResult.UNESTABLISHED


async def test_the_ordering_of_the_limbs_is_driven_not_assumed() -> None:
    """§3, arm 4: a step §2 contradicts, under **no** pin and **no** ``charged_output``.

    Its output refuses its operative declaration's postcondition, so §2's own
    contradicting test holds while the charge test is **not taken**. §3 takes
    contradiction **first**, so the step is contradicting and, as the criterion's only
    call, the criterion is **``unmet``** — *"a step whose own tool's declaration refuses
    its output is contradicting on the record's own evidence, which the absence of a
    readable charge neither supplies nor erases"*.

    **The arm failing an implementation taking the *charge test not taken* case first**,
    which would answer ``neither`` and leave the criterion ``unestablished``.
    """
    comparison = await _money(
        a_step("s-1", output=_REFUSES),
        decisions=(
            a_decision(
                "d-1",
                definition=a_tool(postconditions=_BOOKED, reversibility=Reversibility.IRREVERSIBLE),
                ruling=a_ruling(),
            ),
        ),
    )

    assert _money_result(comparison) is CriterionResult.UNMET


async def test_two_steps_of_one_call_charging_differently_are_ambiguous() -> None:
    """§3, arm 4: §2's grouping is driven, not assumed — *"that **call** ambiguous"*.

    Two ``SUCCEEDED`` steps sharing one ``parameters_digest``, charging ``"120"`` and
    ``"130"`` against the same pin: one satisfying, one contradicting, so the call is
    ambiguous and the criterion **``unestablished``**. *"A mismatch inside an ambiguous
    call is reported as that call's ambiguity, the record declining to say what happened
    rather than a finding suppressed."*
    """
    comparison = await _money(
        a_step("s-1", output=_booked(a_charge("120")), approval_ref="d-1"),
        a_step("s-2", output=_booked(a_charge("130")), approval_ref="d-2"),
        decisions=(
            _pinned(None, decision_id="d-1", digest=DIGEST),
            _pinned(None, decision_id="d-2", digest=DIGEST),
        ),
    )

    assert _money_result(comparison) is CriterionResult.UNESTABLISHED


async def test_the_same_pair_under_different_digests_leaves_the_criterion_unmet() -> None:
    """§3, arm 4: the same two charges as **two calls** — one contradicting → ``unmet``.

    **The arm that fails an implementation promoting a failed charge test straight to a
    criterion-level ``unmet`` without §2's calls**: it is the grouping that decides
    which of the two results the pair reaches, and the pair above proves the grouping is
    consulted.
    """
    comparison = await _money(
        a_step("s-1", output=_booked(a_charge("120")), approval_ref="d-1"),
        a_step("s-2", output=_booked(a_charge("130")), approval_ref="d-2"),
        decisions=(
            _pinned(None, decision_id="d-1", digest=DIGEST),
            _pinned(None, decision_id="d-2", digest=OTHER_DIGEST),
        ),
    )

    assert _money_result(comparison) is CriterionResult.UNMET


async def test_an_unreadable_call_beside_a_satisfying_one_leaves_the_criterion_met() -> None:
    """§4: *"A **different** call that is satisfying … establishes the criterion"*.

    A satisfying call beside a second ``SUCCEEDED`` call whose charge **cannot be
    read** — its output reports none at the keys the declaration names: the unreadable
    one *"neither blocks it nor counts for it"*, so the criterion is **``met``**. Its
    pair below fixes what the unreadable call does block.

    **§8's arm 4 spells the second call's unreadability as a declaration carrying no
    ``charged_output``, and that pair is not constructible here**: two bound steps of one
    criterion contributed the **same** authorising row, and ADR-0254 §7 makes
    ``AuditTrail.record`` refuse a route-(d) decision whose declaration differs from that
    row's **by value** — so no trail could hold two calls of one criterion under two
    declarations. The unreadability is therefore realised at §2's *"a missing key at
    either name"*, which reaches the identical limb: the charge test is **not taken**,
    limb 2 fails for want of a holding test, and the call reaches limb 3. What the arm
    fixes — that an unreadable call neither blocks nor counts — is asserted whole.
    """
    comparison = await _money(
        a_step("s-1", output=_booked(a_charge("120")), approval_ref="d-1"),
        a_step("s-2", output=_HOLDS, approval_ref="d-2"),
        decisions=(
            _pinned(None, decision_id="d-1", digest=DIGEST),
            _pinned(None, decision_id="d-2", digest=OTHER_DIGEST),
        ),
    )

    assert _money_result(comparison) is CriterionResult.MET


async def test_that_unreadable_call_alone_leaves_the_criterion_unestablished() -> None:
    """§4's pair: the same second call **alone** establishes nothing.

    *"Whose whole content is that such a declaration can never **establish**"* — the
    half that shows the fail-closed claim is not a hole, beside the half that shows it
    is not a blanket either.
    """
    comparison = await _money(
        a_step("s-2", output=_HOLDS, approval_ref="d-2"),
        decisions=(_pinned(None, decision_id="d-2", digest=OTHER_DIGEST),),
    )

    assert _money_result(comparison) is CriterionResult.UNESTABLISHED


async def test_a_non_money_criterion_reads_no_charge_at_all() -> None:
    """§3: the charge test is taken *"over no other step of any criterion"*.

    A ``TERMS`` criterion over a booking step whose declaration carries a
    ``charged_output`` it does not report, and whose decision carries no pin: still
    **met**, on §2's two tests alone. **The arm that fails an implementation applying
    limb 2's charge conjunct to every kind**, which would make every ``PERIOD`` and
    ``TERMS`` criterion of a charging tool unestablished.
    """
    rows = Rows(a_row("auth-1", a_member(RIVERSIDE, kind=BoundKind.TERMS)))
    decisions = (a_decision("d-1", definition=_charging_tool(), ruling=a_ruling()),)
    held, ruled = paired(rows.held, decisions)
    rows.reconcile(held)
    comparison = await compare(
        a_goal(a_criterion(RIVERSIDE)),
        an_attempt(EXECUTION),
        executions=Executions(an_execution(a_step("s-1", output=_HOLDS))),
        decisions=Decisions(*ruled),
        rows=rows,
    )

    assert comparison.results == (CriterionResult.MET,)


# --------------------------------------------------------------------------- #
# Arm 5 — the finding is reported, and it prevents nothing                     #
# --------------------------------------------------------------------------- #


async def test_a_single_contradicting_call_with_a_further_met_criterion_is_partial() -> None:
    """Arm 5: ADR-0262 §4's **limb 4**, over a criterion set carrying no unestablished one.

    One call, its charge disagreeing, so §2's ambiguity rule does not fire: the money
    criterion is ``unmet`` and the further criterion ``met``, so the attempt is
    **``PARTIAL``** — ``VERIFIED`` sitting below it *"so that no combination of met
    criteria outvotes an unmet one"*.
    """
    rows = Rows(
        a_row(
            "auth-1",
            a_member(RIVERSIDE, kind=BoundKind.TERMS),
            a_member(UNDER_150, kind=BoundKind.MONEY),
        )
    )
    decisions = (_pinned(None),)
    held, ruled = paired(rows.held, decisions)
    rows.reconcile(held)
    comparison = await compare(
        a_goal(a_criterion(RIVERSIDE), a_criterion(UNDER_150)),
        an_attempt(EXECUTION),
        executions=Executions(an_execution(a_step("s-1", output=_booked(a_charge("130"))))),
        decisions=Decisions(*ruled),
        rows=rows,
    )

    assert comparison.results == (CriterionResult.MET, CriterionResult.UNMET)
    assert comparison.outcome is AttemptOutcome.PARTIAL


async def test_that_criterion_alone_makes_the_attempt_failed() -> None:
    """Arm 5: ADR-0262 §4's **limb 1**, with the money criterion the only one.

    No criterion is met and one is unmet, so the attempt is **``FAILED``** — at rung 2,
    where limb 1's rung refusal is lifted *"unless a criterion is actually ``unmet``"*,
    which this one is.
    """
    comparison = await _money(
        a_step("s-1", output=_booked(a_charge("130"))),
        decisions=(_pinned(None),),
    )

    assert comparison.results == (CriterionResult.UNMET,)
    assert comparison.rung is Rung.CONSEQUENTIAL
    assert comparison.outcome is AttemptOutcome.FAILED


async def test_the_report_carries_exactly_two_fields_and_names_no_figure() -> None:
    """§3: *"``AttemptReport`` keeps **exactly two fields** and ``TurnOutcome`` gains nothing"*.

    **So a user is told that what they asked for was not established and is shown
    neither number.** The arm reads the model's own field set rather than an instance's,
    and then asserts that neither figure, the currency, the tool nor the criterion
    reaches the rendered pair — ADR-0262 §6's *"none names … a figure"* and ADR-0249
    §9's containment binding unrelaxed.
    """
    comparison = await _money(
        a_step("s-1", output=_booked(a_charge("130"))),
        decisions=(_pinned(None),),
    )

    assert set(AttemptReport.model_fields) == {"outcome", "continues"}
    assert comparison.report == AttemptReport(outcome=AttemptOutcome.FAILED, continues=True)
    rendered = comparison.report.model_dump_json()
    for figure in ("130", "120", "EUR", "bookings", UNDER_150):
        assert figure not in rendered


async def test_the_comparison_writes_nothing_of_its_own() -> None:
    """Arm 5: *"the comparison writes nothing of its own"*, and it prevents nothing.

    The three doubles the comparison is given carry **reads only** — the two
    module-private Protocols name neither ``record`` nor ``commit_transition``, and
    ``AuthorizationResolution`` is ``resolve(id)`` and nothing else — so *"no
    ``Authorization`` is written, settled or revoked, no decision is recorded, no
    dispatch is refused"* is a property of the seams rather than of an assertion. What
    this arm adds is that a **disagreeing** charge takes none of those routes either:
    the rows double is read and never mutated, the same row comes back in the same
    disposition, and the only thing the turn carries is §6's two-field report.

    ADR-0262 §4's ``commit_attempt`` is the arm's expected write, and it is the
    engine's — ``test_engine_verify_phase.py``'s arms pin it.
    """
    rows = Rows(a_row("auth-1", a_member(UNDER_150, kind=BoundKind.MONEY)))
    decisions = (_pinned(None),)
    held, ruled = paired(rows.held, decisions)
    rows.reconcile(held)
    before = rows.held
    trail = Decisions(*ruled)
    comparison = await compare(
        a_goal(a_criterion(UNDER_150)),
        an_attempt(EXECUTION),
        executions=Executions(an_execution(a_step("s-1", output=_booked(a_charge("130"))))),
        decisions=trail,
        rows=rows,
    )

    assert _money_result(comparison) is CriterionResult.UNMET
    assert rows.held == before
    assert [one.disposition for one in rows.held] == [one.disposition for one in before]
    assert trail.calls == ["d-1"]
    assert not hasattr(rows, "record")
