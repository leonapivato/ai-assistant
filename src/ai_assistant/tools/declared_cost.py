"""What a configured per-call figure builds, for any integration that has one.

ADR-0236 §1's rule, *"stated over building a ``ToolCost``, not over reading a
setting"*, at the one place in production a configured amount and its currency become
one. It was ``tools/web_search.py``'s while the search was the only integration a
deployment could price; ADR-0260 §11 gives the forecast read "the same pair, in the
same domain", so it is stated **here** and read by both builders rather than twice.

**Why it is not simply ``Settings``' validator reused.** ``core`` may import no
subsystem and no subsystem may import another (golden rules 1 and 2), and this is the
one site an integration can be built *without* going through ``Settings`` — a test, or
a composition root that constructed a builder directly. ADR-0236 §2 puts a statement
here for that structural reason and says so in terms: *"The domain is therefore
enforced twice, deliberately, and the two statements are of one rule."* Two, not
three: one in ``core.config`` for the fields, one here for the builders.

**``FREE`` is unreachable through this module and there is no argument that could ask
for one** (ADR-0236 §3). The two states :func:`checked_per_call_cost` returns are the
whole of what a deployment can put a declaration's ``cost`` field in; an operator
asserting that a call costs them nothing passes ``Decimal("0")`` with the currency
their account is denominated in.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Final

from ai_assistant.core.types import CostBasis, ToolCost, describe_untrusted

#: ADR-0194 §1's magnitude bound on any amount that mechanism reads, restated here
#: for :func:`checked_per_call_cost` at the one site an integration is built without
#: going through ``Settings`` (ADR-0236 §2). Strictly above, so ``1E15`` itself is refused.
_COST_AMOUNT_CEILING: Final = Decimal("1E15")

#: ADR-0194 §1's fractional-digit bound, likewise. Nine, which is what a declared
#: figure may carry and what the store's arithmetic is stated over.
_COST_AMOUNT_SCALE: Final = 9

#: ISO-4217's alphabetic form is three letters — ``ToolCost.currency``'s own rule
#: (ADR-0016 §4) and ``world_spend_currency``'s, and not a third one (ADR-0236 §2).
_CURRENCY_CODE_LENGTH: Final = 3


def _is_countable(amount: Decimal) -> bool:
    """Report whether ``amount`` is countable under ADR-0194 §1.

    Finite; absolute value **strictly** below :data:`_COST_AMOUNT_CEILING`; and
    expressible to at most :data:`_COST_AMOUNT_SCALE` fractional digits.
    ``Decimal("1.0000000000")`` is countable, because §1's predicate is a test on
    the *value* and not on the representation.

    **A further implementation of §1's predicate, deliberately, and not a further
    source for it.** ``core.config`` carries one for the ``Settings`` field it
    validates and ``permissions.spend`` carries one for the store that runs the
    arithmetic, each stating the ADR's clause rather than each other, because
    ``core`` may import no subsystem and no subsystem may import another (golden
    rules 1 and 2). ADR-0236 §2 puts a statement here for the same structural
    reason and says so in terms — *"The domain is therefore enforced twice,
    deliberately, and the two statements are of one rule."*

    **Context-independent by construction.** Everything it reads comes from the
    amount's own ``as_tuple()``, and ``copy_abs`` rather than ``abs`` because the
    latter rounds to the ambient precision and traps under a hostile context on
    exactly the values this predicate exists to classify.

    Args:
        amount: The amount to classify.

    Returns:
        Whether ADR-0194's mechanism may read it.
    """
    if not amount.is_finite():
        return False
    _, digits, exponent = amount.as_tuple()
    if not isinstance(exponent, int):  # pragma: no cover — a finite Decimal has an int exponent
        return False
    significant = len(digits)
    while significant and digits[significant - 1] == 0:
        significant -= 1
    scale = 0 if significant == 0 else exponent + (len(digits) - significant)
    if scale < -_COST_AMOUNT_SCALE:
        return False
    return amount.copy_abs() < _COST_AMOUNT_CEILING


def checked_per_call_cost(amount: Decimal | None, currency: str | None) -> ToolCost | None:
    """The declared cost a configured per-call figure builds, or ``None`` for absence.

    ADR-0236 §1's rule, *"stated over building a ``ToolCost``, not over reading a
    setting"*, at the one place in production either value becomes one. ``None``
    means the pair is unset, and the caller keeps its declaration's own ``UNKNOWN``
    cost rather than building an equal copy of it (§4).

    **`FREE` is unreachable through this function and there is no argument that
    could ask for one** (§3): the two states it returns are the whole of what a
    deployment can put the declaration's ``cost`` field in. An operator asserting
    that a call costs them nothing passes ``Decimal("0")`` with the currency
    their account is denominated in, which satisfies the ``UNKNOWN``-cost floor
    exactly as any other ``PER_CALL`` figure does.

    **This restates ADR-0236 §2's domain at the one place an integration can be
    built without going through ``Settings``**, which is that section's marked
    clause: the domain is enforced twice, and the two statements are of one rule.

    Args:
        amount: the deployment's configured per-call figure, or ``None`` —
            ``Settings.web_search_cost_per_call`` or ``Settings.forecast_cost_per_call``.
        currency: the ISO-4217 code it is denominated in, or ``None``.

    Returns:
        The ``PER_CALL`` cost where both are supplied, and ``None`` where neither
        is.

    Raises:
        TypeError: If ``currency`` is supplied and is not a ``str``. The type is part
            of the domain, so a caller that ignored the annotation is refused by name
            rather than by ``len()`` raising one field along, and the canonical fake
            states the same rule (ADR-0236 §7).
        ValueError: If exactly one of the two is supplied; if ``amount`` is not an
            exact ``Decimal``, is non-finite, is negative, or is not countable
            under ADR-0194 §1; or if ``currency`` is not exactly three uppercase
            ASCII letters (ADR-0016 §4's shape, and ``world_spend_currency``'s).
    """
    if (amount is None) != (currency is None):
        supplied = "cost_per_call" if currency is None else "cost_currency"
        missing = "cost_currency" if currency is None else "cost_per_call"
        msg = (
            f"{supplied} is supplied and {missing} is not; a declared per-call cost needs "
            f"both the figure and the ISO-4217 code it is denominated in (ADR-0236 §1)"
        )
        raise ValueError(msg)
    if amount is None or currency is None:
        return None
    if type(amount) is not Decimal:
        # An exact ``Decimal`` and not an ``isinstance`` match, for ``_checked_bound``'s
        # reason: a subclass overriding comparison would satisfy the range below while
        # declaring something else entirely.
        # Rendered through `describe_untrusted`: the type has just been refused, so the
        # value is anything at all and its `__repr__` is the caller's — a message
        # interpolating it directly could raise in place of this `ValueError`.
        msg = f"cost_per_call is an exact Decimal; got {describe_untrusted(amount)}"
        raise ValueError(msg)
    if not amount.is_finite():
        msg = f"cost_per_call must be finite (ADR-0236 §2); got {amount!r}"
        raise ValueError(msg)
    if amount < 0:
        msg = f"cost_per_call must not be negative (ADR-0236 §2); got {amount!r}"
        raise ValueError(msg)
    if not _is_countable(amount):
        msg = (
            f"cost_per_call must be countable — below {_COST_AMOUNT_CEILING} and to at "
            f"most {_COST_AMOUNT_SCALE} fractional digits (ADR-0194 §1); got {amount!r}"
        )
        raise ValueError(msg)
    if type(currency) is not str:
        # Refused by name, and before the shape check below reaches ``len()``. An
        # exact ``str`` and not an ``isinstance`` match, for the amount's reason one
        # field up: a subclass overriding ``__len__`` or ``isupper`` would satisfy the
        # shape check while declaring something else. ``TypeError`` and not the
        # ``ValueError`` a malformed *code* earns, because the class states which
        # mistake was made.
        msg = f"cost_currency is a str; got {type(currency).__name__}"
        raise TypeError(msg)
    if len(currency) != _CURRENCY_CODE_LENGTH or not (
        currency.isascii() and currency.isupper() and currency.isalpha()
    ):
        msg = (
            "cost_currency must be three uppercase ASCII letters (ISO-4217, ADR-0016 §4); "
            f"got {currency!r}"
        )
        raise ValueError(msg)
    return ToolCost(basis=CostBasis.PER_CALL, amount=amount, currency=currency)


__all__ = ["checked_per_call_cost"]
