"""ADR-0254 §§3 and 4's coverage comparison, in one place (ADR-0254 §3, §4, §6).

Whether a live :class:`~ai_assistant.core.types.Authorization` covers a concrete
:class:`~ai_assistant.core.types.ActionRequest`, and whether it covers the
request's **arguments** alone — which is ADR-0254 §6's argument-authority bar,
stated over §3's condition 6 and no other condition.

**Module functions rather than methods**, so nothing here holds a store, a clock
or a seam: everything the comparison needs is in its arguments, which is what
keeps it a comparison of recorded values. The policy calls them; the store does
not, and no `core` type does.

**Every reading is total and every failure of it is a refusal to cover** (§4),
never an exception out of ``decide``, never a ``DENY``, and never a value
substituted, coerced, clamped, defaulted or repaired into range. A request whose
argument a reading refuses is a request the authorization does not cover, and the
ruling is the one the policy's table reached without it.

**No reading consults a schema to decide what an argument means, and there is no
exception** (§4). Every fact a comparison needs is on the row or in the request:
which key holds an amount, which key holds its currency, which zone a date is
read in, which strings a term may take. ADR-0145 §1's schema check decides whether
the call is well-formed and decides nothing about coverage.

**One canonical JSON encoding**, and it is
:func:`~ai_assistant.core.types.canonical_json_bytes` — the encoding
``ActionRequest.parameters_digest`` is taken over. A fixed-value comparison
written by hand would be a second canonicalisation of a payload, and two that
disagree produce a false mismatch at one end and a **false match** at the other.
"""

from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ai_assistant.core.types import BoundKind, canonical_json_bytes

if TYPE_CHECKING:
    from ai_assistant.core.types import (
        ActionRequest,
        Authorization,
        CoverageMember,
        FrozenJson,
        ValueBound,
    )


def user_facing(request: ActionRequest) -> frozenset[str]:
    """The keys of ``request.parameters`` the declaration does **not** fill itself.

    ADR-0254 §3: ``ToolDefinition.system_supplied`` names the keys the **system**
    fills — an idempotency key, a client reference, a locale — and *"every key it
    does not name is user-facing"*. **A declaration that classifies no argument
    system-supplied has every argument user-facing**, and condition 6 then reads
    exactly as it would without the classification.

    Args:
        request: The action being ruled on.

    Returns:
        The user-facing argument keys this call actually carries.
    """
    return frozenset(request.parameters) - frozenset(request.tool.system_supplied)


def covers_arguments(row: Authorization, request: ActionRequest) -> bool:
    """ADR-0254 §3's **condition 6**, and that condition alone (§6's bar).

    *"The request's user-facing arguments and the row's coverage name the same set
    of keys, and every user-facing argument of the request is covered by the
    per-argument rule."*

    **Stated in both directions, because an omission is a change as much as an
    addition is.** A user-facing argument the request carries that the row names in
    no member is not covered — the direction §3 has always had. **And an argument
    the row's coverage names that the request does not carry leaves condition 6
    unsatisfied too**: an act that fixed ``refundable_only`` to ``true``
    authorised a call *carrying* that value, and a call that omits it is a
    different call. ADR-0145 inserts no schema default, so nothing downstream
    restores it, and the omission would silently buy whatever the service does when
    the field is absent. **There is no default, no wildcard, no "not sent therefore
    unconstrained" and no omission that reads as consent.**

    **The empty case holds vacuously** (§1, §3): a row with ``coverage=()`` and a
    request carrying no user-facing argument name the same set — the empty one — so
    condition 6 holds, and that is the one request such a row covers. A request
    carrying system-supplied arguments and no others is such a request.

    **A system-supplied argument is not among them and never fires the bar**, which
    is what keeps an implementation choice out of a question put to the user.

    Args:
        row: The live record the one ``live_for`` read returned.
        request: The action being ruled on.

    Returns:
        Whether condition 6 holds over that pair.
    """
    carried = user_facing(request)
    named = {member.argument for member in row.coverage}
    if carried != named:
        return False
    return all(
        _argument_is_covered(member, request)
        for member in row.coverage
        if member.argument in carried
    )


def covers(row: Authorization, request: ActionRequest) -> bool:
    """ADR-0254 §3's conditions **3, 4, 5 and 6** — the policy's half of coverage.

    Conditions **1 and 2** and the **id half** of condition 3 are
    :meth:`~ai_assistant.core.protocols.GoalAuthorizations.live_for`'s, answered by
    the seam that returned ``row``. **Coverage is still their conjunction and no
    component treats either half as the whole.**

    * **3** — the request's ``tool`` equals the row's **by value**. A record
      established about one declaration authorises nothing about an edited one,
      which is §1's accepted cost in the safe direction.
    * **4** — the binding's ``account`` equals the row's **by value, both facts and
      never one** (ADR-0148 §6).
    * **5** — **every** member of the request's canonical destination set is a
      member of the row's, compared as
      :class:`~ai_assistant.core.types.CanonicalDestination` compares: every field,
      never across protocols. Membership and nothing looser — no case folding, no
      domain matching, no treating an account member as covering a recipient member
      or the reverse, and **no re-canonicalising either side**: the canonicaliser
      is ADR-0148 §2's, at the seam, and there is not a second one here.
    * **6** — :func:`covers_arguments`.

    **A request carrying no ``egress_binding`` is covered by no row**: it names no
    account and no destination set, so conditions 4 and 5 have nothing to compare.

    Args:
        row: The live record the one ``live_for`` read returned.
        request: The action being ruled on.

    Returns:
        Whether the row covers the request **in full**, which is what ADR-0254 §6's
        lineage discharge and route (d)'s ``ALLOW`` both rest on.
    """
    binding = request.egress_binding
    if binding is None:
        return False
    if request.tool != row.tool or binding.account != row.account:
        return False
    if any(member not in row.destinations for member in binding.canonical_destination_set):
        return False
    return covers_arguments(row, request)


def _argument_is_covered(member: CoverageMember, request: ActionRequest) -> bool:
    """ADR-0254 §3's per-argument rule, over one member.

    The member is **fixed**, and the canonical JSON encoding of the argument's
    value equals the canonical JSON encoding of ``fixed``, byte for byte; or the
    member is **bounded**, and the argument satisfies the bound under §4's total,
    fail-closed reading.

    **An argument the request does not carry is not covered**, whichever shape the
    member takes — which is condition 6's second direction reaching one member.
    """
    if member.argument not in request.parameters:
        return False
    value = request.parameters[member.argument]
    if member.bound is None:
        return canonical_json_bytes(value) == canonical_json_bytes(member.fixed)
    return _satisfies(member.bound, value, request)


def _satisfies(bound: ValueBound, value: FrozenJson, request: ActionRequest) -> bool:
    """ADR-0254 §4's reading of one argument against one bound.

    Total, and every failure is a refusal to cover rather than an exception.
    """
    if bound.kind is BoundKind.MONEY:
        return _satisfies_money(bound, value, request)
    if bound.kind is BoundKind.PERIOD:
        return _satisfies_period(bound, value)
    return _satisfies_terms(bound, value)


def _satisfies_money(bound: ValueBound, value: FrozenJson, request: ActionRequest) -> bool:
    """ADR-0254 §4's ``MONEY`` reading, with the currency conjunct over the request.

    The argument's value is a JSON **string** ``Decimal`` accepts, or a JSON
    **integer**; the resulting ``Decimal`` is finite and not negative; it is at most
    ``maximum`` and, where a ``minimum`` is carried, at least that; **and the
    request carries, at the bound's ``currency_argument``, a JSON string equal to
    the bound's ``currency`` byte for byte**.

    **The last conjunct is stated over the concrete request rather than over the
    row**, so a row whose currency member says one thing and whose request says
    another covers nothing rather than covering the wrong amount of the wrong
    money; and a request carrying no value at that key is **not covered**.

    **A JSON floating-point value never satisfies a ``MONEY`` bound.** A binary
    float is not a price, and comparing one against a decimal bound is precisely
    the unproven comparison ADR-0148 §2 refuses by default: the answer is not to
    round, to quantise or to pick a tolerance, it is to refuse and ask. A JSON
    **boolean** is refused with it: ``bool`` is an ``int`` in Python and ``True``
    would otherwise read as one.
    """
    if bound.currency_argument is None or bound.maximum is None:  # pragma: no cover — the model
        return False
    stated = request.parameters.get(bound.currency_argument)
    if not isinstance(stated, str) or stated != bound.currency:
        return False
    if isinstance(value, bool) or not isinstance(value, str | int):
        return False
    try:
        amount = Decimal(value)
    except InvalidOperation, ValueError:
        return False
    if not amount.is_finite() or amount < 0 or amount > bound.maximum:
        return False
    return bound.minimum is None or amount >= bound.minimum


def _satisfies_period(bound: ValueBound, value: FrozenJson) -> bool:
    """ADR-0254 §4's ``PERIOD`` reading, over the half-open ``[starts_at, ends_at)``.

    The value is a JSON **string** parsing as **either** an RFC 3339 date-time
    carrying an offset, **or** a calendar date. A calendar date denotes the **start
    of that day in the bound's own ``timezone``**, read off the bound rather than
    off ``Settings``, so the comparison is over two recorded values and reads no
    configuration at the moment it is taken.

    **A date-time carrying no offset never satisfies a ``PERIOD`` bound**: a naive
    instant is an unproven comparison and there is no zone this system is entitled
    to supply for it at ruling time. The calendar-date arm is not that case — the
    zone there is the **user's own recorded value**, not one the system supplied.
    """
    if bound.starts_at is None or bound.ends_at is None:  # pragma: no cover — the model
        return False
    if not isinstance(value, str):
        return False
    instant = _instant_of(value, bound.timezone)
    if instant is None:
        return False
    return bound.starts_at <= instant < bound.ends_at


def _instant_of(text: str, zone: str | None) -> datetime | None:
    """The instant ``text`` denotes, or ``None`` where the reading refuses it.

    ``date.fromisoformat`` succeeds on a bare calendar date and refuses a full
    date-time, which is what tells the two arms apart without inspecting the
    string: a naive date-time reaches the second arm and is refused there.
    """
    try:
        day = date.fromisoformat(text)
    except ValueError:
        day = None
    if day is not None:
        if zone is None:  # pragma: no cover — a PERIOD bound's model requires one
            return None
        try:
            located = ZoneInfo(zone)
        except ZoneInfoNotFoundError, ValueError:  # pragma: no cover — the model validates it
            return None
        return datetime.combine(day, time(), tzinfo=located)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.utcoffset() is not None else None


def _satisfies_terms(bound: ValueBound, value: FrozenJson) -> bool:
    """ADR-0254 §4's ``TERMS`` reading: membership by the stored characters.

    **No fold, no strip, no case-insensitive match, no prefix and no substring** —
    ADR-0237 §3's rule for a ``TopicLabel`` read onto a set the user named.
    """
    if bound.terms is None:  # pragma: no cover — the model requires it of a TERMS bound
        return False
    return isinstance(value, str) and value in bound.terms


__all__ = ["covers", "covers_arguments", "user_facing"]
