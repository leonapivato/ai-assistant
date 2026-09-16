"""The charge an act reported, and the test against the quote it was proved against.

ADR-0271 §8's **P3**, the reading half: *"§2's charge reading and §3's limbs inside
ADR-0262's comparison, in the subsystem that decision's own lane cut puts it in"*. The
limbs themselves are
:func:`~ai_assistant.orchestration.verification.classify_bound_step`'s, one module over;
what lives here is the **reading** (§2) and the **three-conjunct test** (§3) it feeds.

**The operands are three and there is no fourth** (§3): the policy's pinned quote
(:attr:`~ai_assistant.core.types.PermissionRuling.proved_quote`, ADR-0271 §1), the tool
author's own declaration, and the provider's returned output. **Nothing here reads a
model, a plan or a prose value** — not a ``verifies``, not an ``intended_action`` a
planner wrote, not a step's position, not a ``GoalElement.text``, not a
``StepFailure.message`` and not a tool description.

**The reading is total, fail-closed and silent** (§2). *"Every failure of that reading
yields no charge, and nothing is repaired, coerced, defaulted or substituted"*, and *"a
yield of no charge raises nothing"* — a declaration carrying no
:attr:`~ai_assistant.core.types.ToolDefinition.charged_output`, an ``output`` that is not
an object, a missing key at either name, a value of any refused shape, an amount
``Decimal`` refuses or accepts as non-finite, a negative amount, a currency that is not a
JSON string or not ISO-4217 shaped: each yields **no charge**, and the charge test is then
**not taken**.

**No substitute is ever read for a charge** (§2). Not :attr:`ToolDefinition.cost`, not
:attr:`~ai_assistant.core.types.ToolInvocation.incurred_cost` — ADR-0192 §5's *"never
money the tool moved"* is why the invocation row is not the operand — not a quote, not a
ceiling and not a zero: *"a charge this system supplied is a charge no provider
reported"*. And **the two declaration fields are read for their own fact and never for
each other's**: nothing here reads ``quoted_output`` as a charge, and nothing mints an
``ActionQuote`` from one.

**This module mints no record, no store, no seam, no Protocol and no write path for a
charge** (§2), and nothing persists one. :class:`Charge` is a value this comparison holds
for the length of one call and nothing writes it anywhere.

**And the comparison is a report and never a prevention** (§3). A failed test makes a
bound step *contradicting*, which ADR-0262 §2's own machinery turns into that criterion's
result. **It changes no ruling, refuses no dispatch, revokes no**
:class:`~ai_assistant.core.types.Authorization`, **retries nothing, reverses nothing and
refunds nothing**, and the act it speaks of has already run.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from ai_assistant.core.types import BoundKind, StepStatus
from ai_assistant.orchestration.quotes import amount_read

if TYPE_CHECKING:
    from decimal import Decimal

    from ai_assistant.core.types import (
        ActionQuote,
        CoverageMember,
        FrozenJson,
        ToolDefinition,
        ValueBound,
    )

__all__ = ["Charge", "ChargeTest", "charge_read", "charge_test"]

#: An ISO-4217 alphabetic code is exactly this long (ADR-0267 §1).
_CURRENCY_CODE_LENGTH = 3


@dataclass(frozen=True, slots=True)
class Charge:
    """What one invocation reported it charged, read under its own declaration (§2).

    **Not a record.** ADR-0271 §2 mints *"no record, no store, no seam, no Protocol and
    no write path for a charge"*, so this is a value one comparison holds and nothing
    persists, transcribes or renders. It is a dataclass rather than a ``core`` model for
    exactly that reason: a model in ``core/types.py`` is a shape that crosses subsystem
    boundaries, and this one crosses none.

    Attributes:
        amount: The whole amount that invocation charged, finite and not negative —
            the value at the key :attr:`~ai_assistant.core.types.ChargedOutput.amount`
            names, read as ADR-0267 §4 reads a quoted one.
        currency: That amount's ISO-4217 code, three uppercase ASCII letters. **Shape
            and never a register** (ADR-0267 §1), and never folded: §3 compares it
            against the pinned quote's **byte for byte**.
    """

    amount: Decimal
    currency: str


class ChargeTest(StrEnum):
    """§3's charge test over one bound step: it holds, it fails, or it is not taken.

    **Three states and not two**, because *not taken* and *fails* reach different limbs
    of §3's classification: a failed test makes a step **contradicting**, while a test
    that was never taken leaves it at limb 3 — **neither** — so the call it belongs to
    is *"never satisfying"* and its criterion `unestablished` where every call is one
    (§4). Folding the two would report a declaration that says nothing about charges as
    a provider that charged the wrong amount.
    """

    HOLDS = "holds"
    """A charge read and all three of §3's conjuncts hold."""

    FAILS = "fails"
    """A charge read and some conjunct does not hold — the finding (§3)."""

    NOT_TAKEN = "not_taken"
    """The step is not ``SUCCEEDED``, there is no pin, or no charge reads (§3)."""


def charge_read(definition: ToolDefinition, output: FrozenJson) -> Charge | None:
    """The charge this step's output reports, or ``None`` where the reading fails (§2).

    **The reading is ADR-0267 §4's own, by reference rather than re-specified** (§2):
    the ``output`` is a JSON **object**; at the ``amount`` key a JSON **string** a
    ``Decimal`` accepts or a JSON **integer**, whose ``Decimal`` is finite and not
    negative; at the ``currency`` key a JSON **string** of ADR-0267 §1's shape. The
    amount half is literally that function — :func:`~ai_assistant.orchestration.quotes
    .amount_read`, the tree's one statement of it — so a value the mint admits and one
    this reading admits cannot come apart.

    **The two conjuncts the quote path delegates to a validator are stated here**, and
    the reason is that there is no validator to delegate them to: ``quote_read``
    constructs an :class:`~ai_assistant.core.types.ActionQuote` and reads its refusal as
    a reading that failed, while §2 mints **no record** for a charge. So the finiteness
    and sign refusal (ADR-0267 §1 on ADR-0254 §2's own ground — ``Decimal`` admits
    ``Infinity`` and ``NaN``, *"neither of which has a JSON representation"*) and the
    ISO-4217 **shape** refusal are taken here, in that order: ``Decimal("sNaN") < 0``
    **raises** rather than answering, so finiteness is tested before the sign, exactly as
    :class:`~ai_assistant.core.types.ValueBound` orders the same pair.

    **A JSON boolean is not a JSON integer**, stated because the implementation language
    will not state it: ``bool`` is a subclass of ``int`` in Python, so a check written as
    an ``int`` instance test admits ``true`` as ``Decimal(1)`` and reports a one-unit
    charge that agrees with almost any quote. That refusal is ``amount_read``'s, and
    the currency's own type test runs **before** any string operation for the same
    reason — an implementation applying one first would read ``True`` or ``3`` as a code.

    **The operative declaration is the caller's** (§2) — the whole
    :class:`~ai_assistant.core.types.ToolDefinition` embedded by value in the
    :class:`~ai_assistant.core.types.PermissionDecision` the step's ``approval_ref``
    names, **never the registry's** — and this function reads whatever it is handed.

    Args:
        definition: The **pinned** declaration the act ran under.
        output: That step's own stored ``output``.

    Returns:
        The charge, or ``None`` where any part of the reading failed. **It raises
        nothing.**
    """
    charged = definition.charged_output
    if charged is None or not isinstance(output, Mapping):
        return None
    if charged.amount not in output or charged.currency not in output:
        return None
    amount = amount_read(output[charged.amount])
    currency = output[charged.currency]
    if amount is None or not isinstance(currency, str):
        return None
    if not amount.is_finite() or amount < 0:
        # Ordered: `Decimal("sNaN") < 0` raises rather than answering, and `"NaN"`,
        # `"Infinity"` and `"-Infinity"` are strings `Decimal` **accepts** — the pair a
        # natural implementation reaches by accident, which §2 names.
        return None
    if not _iso_4217_shaped(currency):
        return None
    return Charge(amount=amount, currency=currency)


def charge_test(
    *,
    status: StepStatus,
    definition: ToolDefinition,
    output: FrozenJson,
    pinned: ActionQuote | None,
    member: CoverageMember,
) -> ChargeTest:
    """§3's charge test over one bound step of a ``MONEY`` criterion.

    It **holds** where the step stands ``SUCCEEDED``, its pinned decision carries a
    ``proved_quote``, a charge reads under :func:`charge_read`, and **all three**
    conjuncts hold:

    1. the charge's **currency equals the pinned quote's byte for byte** — *"no
       conversion, no fold and no register consulted"*, exactly as ADR-0254 §4's
       ``MONEY`` reading compares one;
    2. the charge's **amount is not greater than the pinned quote's**; and
    3. that amount **satisfies the confirmed member** under ADR-0254 §4's ``MONEY``
       reading, *"taken at the quote's own currency"* (ADR-0266 §7's comparison shape).

    It **fails** where a charge reads and some conjunct does not hold — *"a charge that
    disagrees is the finding"* — and it is **not taken at all** where the step is not
    ``SUCCEEDED``, where there is no ``proved_quote``, where the declaration carries no
    ``charged_output``, or where no charge reads.

    **Conjunct 3 is not conjunct 2 twice.** A charge under the quote can still fall
    outside the member — a ``minimum`` the user stated, or a ceiling below the quote —
    so an implementation testing currency and *not greater than the quote* alone admits
    an amount the user's own words do not permit. And it is not the ceiling comparison
    ADR-0262 §2 forbids either: the charge meets the **pin** first, and the member only
    then.

    **This is ADR-0254 §4's reading restated in ``orchestration`` and not shared with
    the policy's**, which is golden rule 1 rather than a preference: the one other
    statement of it lives in ``permissions``, and a subsystem may not import another
    subsystem's concrete module. What is shared is what ``core`` and this package can
    carry — the record's own refusals and ``amount_read``.

    Args:
        status: The bound step's own stored status.
        definition: The **pinned** declaration the act ran under.
        output: The step's own stored ``output``.
        pinned: The quote the dispatch was proved against (ADR-0271 §1), or ``None``
            where the decision carries none.
        member: The criterion's **confirmed** member, whose ``kind`` is ``MONEY``.

    Returns:
        Which of the three states the test is in.
    """
    if status is not StepStatus.SUCCEEDED or pinned is None:
        return ChargeTest.NOT_TAKEN
    charge = charge_read(definition, output)
    if charge is None:
        return ChargeTest.NOT_TAKEN
    if charge.currency != pinned.currency or charge.amount > pinned.amount:
        return ChargeTest.FAILS
    if not _satisfies_member(member, charge.amount, currency=pinned.currency):
        return ChargeTest.FAILS
    return ChargeTest.HOLDS


def _satisfies_member(member: CoverageMember, amount: Decimal, *, currency: str) -> bool:
    """ADR-0254 §4's ``MONEY`` reading, at the quote's own currency (ADR-0266 §7).

    The amount is already finite and not negative (:func:`charge_read`), so what is
    left is the bound's own endpoints and the currency conjunct — taken against
    ``currency``, *"the quote's own"*, and at no key of any request. **No endpoint is
    ever widened**: ``maximum_exclusive`` is read strictly, because *"under 100 euros"*
    does not cover a call at exactly ``100`` and *"at most 100 euros"* does (ADR-0266
    §3).

    **A ``MONEY`` member carries a bound and never a fixed value**, which ADR-0266 §3
    refuses outright — *"an amount carries no currency on a fixed member, so nothing
    could denominate it"* — so ADR-0271 §3's *"ADR-0254 §3's fixed comparison or §4's
    ``MONEY`` reading"* reduces to the second here, and the first is unreachable rather
    than unimplemented.

    Args:
        member: The criterion's confirmed member.
        amount: The charge's amount.
        currency: The pinned quote's currency.

    Returns:
        Whether the amount satisfies the member.
    """
    bound: ValueBound | None = member.bound
    if bound is None or bound.kind is not BoundKind.MONEY:  # pragma: no cover — the model
        return False
    if bound.currency != currency or bound.maximum is None:  # pragma: no cover — partly the model
        return False
    if amount > bound.maximum or (bound.maximum_exclusive and amount == bound.maximum):
        return False
    return bound.minimum is None or amount >= bound.minimum


def _iso_4217_shaped(value: str) -> bool:
    """Whether ``value`` is three uppercase ASCII letters (ADR-0267 §1).

    **Shape and never a register**: validating against the live ISO-4217 table *"would
    make a record's decoding depend on a list that changes when currencies are
    withdrawn"*, and silently upcasing ``"usd"`` *"would treat a lowercase code and a
    typo'd one differently for no reason a caller can see"*. So ``"usd"`` and ``"EURO"``
    each yield **no charge** rather than a repaired one.

    **It is a predicate here and a validator in ``core``**, and the difference is ADR-0271
    §2's *"this decision mints no record"*: the quote path reads ``ActionQuote``'s own
    refusal because it constructs one, and a charge constructs nothing to refuse it.
    """
    return (
        len(value) == _CURRENCY_CODE_LENGTH
        and value.isascii()
        and value.isupper()
        and value.isalpha()
    )
