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

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import TYPE_CHECKING, Final
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ai_assistant.core.types import BoundKind, canonical_json_bytes

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.core.types import (
        ActionRequest,
        Authorization,
        CoverageMember,
        FrozenJson,
        ToolDefinition,
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


class ArgumentFailure(StrEnum):
    """Which of ADR-0254 §4's **three** failures one argument's coverage met.

    *"The three failures are told apart, whichever way the key is rendered,
    because they are different facts about what the user authorised and §3's
    condition 6 keeps them apart."* A ruling that reduced them to one would tell a
    user that their authority did not reach a call without saying in what way.

    Not a ``core`` type: ADR-0254 §16's roster is closed over what ``core`` gains,
    and this is a **rendering** detail of one policy's reason rather than a value
    that crosses a boundary.
    """

    UNNAMED = "unnamed"
    """The row's coverage names this user-facing argument in **no** member."""

    OMITTED = "omitted"
    """A member names this argument and the request does not carry it.

    *"An act that fixed ``refundable_only`` to ``true`` authorised a call carrying
    that value, and a call that omits it is a different call"* — ADR-0145 inserts
    no schema default, so nothing downstream restores it."""

    REFUSED = "refused"
    """A member names it and the comparison over its value was **unproven**."""


@dataclass(frozen=True, slots=True)
class UncoveredArgument:
    """One argument, and which of §4's three failures its coverage met."""

    argument: str
    failure: ArgumentFailure


def uncovered(row: Authorization, request: ActionRequest) -> tuple[UncoveredArgument, ...]:
    """Every way ADR-0254 §3's **condition 6** fails over this pair, told apart.

    Empty exactly where :func:`covers_arguments` answers ``True``, which is what
    keeps the predicate and the account of its failure one computation rather than
    two that can disagree.

    Args:
        row: The live record the one ``live_for`` read returned.
        request: The action being ruled on.

    Returns:
        The failures, ordered by :class:`ArgumentFailure` and then by argument name,
        so a rendering of them is deterministic without the renderer sorting.
    """
    carried = user_facing(request)
    named = {member.argument: member for member in row.coverage}
    defects = [UncoveredArgument(key, ArgumentFailure.UNNAMED) for key in carried - set(named)]
    defects += [UncoveredArgument(key, ArgumentFailure.OMITTED) for key in set(named) - carried]
    defects += [
        UncoveredArgument(key, ArgumentFailure.REFUSED)
        for key in carried & set(named)
        if not _argument_is_covered(named[key], request)
    ]
    return tuple(sorted(defects, key=lambda one: (one.failure.value, one.argument)))


#: What a ruling says about each of §4's three failures, in the order they are
#: rendered. **No value, no bound, no record id and no digest**: a reason is carried
#: on a durable ``PermissionDecision`` that holds ``parameters_digest`` and not
#: ``parameters``, and quoting a value would put into the trail exactly what that
#: omission keeps out (ADR-0254 §4).
_ACCOUNTS: Final[tuple[tuple[ArgumentFailure, str], ...]] = (
    (
        ArgumentFailure.UNNAMED,
        "the user's own recorded act for this goal covers no such argument",
    ),
    (
        ArgumentFailure.OMITTED,
        "this call omits an argument the user's own recorded act covers",
    ),
    (
        ArgumentFailure.REFUSED,
        "this call is outside what the user's own recorded act allows",
    ),
)


def account_of(defects: Sequence[UncoveredArgument], tool: ToolDefinition) -> str:
    """Render ADR-0254 §4's account of why coverage failed, for the user.

    **It never reproduces an argument's value, the bound, the record's id or its
    digest** (§4). **And it names an argument's key only where the declaration's
    ``parameters_schema`` itself names that key**: ADR-0145 §8 rules that a message
    about arguments *"renders any part of the parameters — neither a value nor a
    key"* except what *"the schema itself names"*, on the ground that *"a key can
    be data"* — a mapping the schema does not describe can be keyed by an address
    or an identifier, and ADR-0254 §2's ``argument`` is a key of ``parameters``
    with nothing requiring the schema to declare it.

    So a key the schema declares is named; **a key it does not is counted rather
    than listed**, which is ADR-0145 §8's *"by keyword and location rather than by
    key"* read onto this message. Where several arguments fail, they are named in
    the **declaration's own schema order**.

    Args:
        defects: :func:`uncovered`'s answer, non-empty.
        tool: The declaration being ruled on, whose schema decides what may be
            named.

    Returns:
        One clause per failure that occurred, joined by ``"; "``.
    """
    properties = tool.parameters_schema.get("properties")
    declared = tuple(properties) if isinstance(properties, Mapping) else ()
    order = {name: index for index, name in enumerate(declared)}
    clauses: list[str] = []
    for failure, phrase in _ACCOUNTS:
        met = [one.argument for one in defects if one.failure is failure]
        if not met:
            continue
        named = sorted((key for key in met if key in order), key=lambda key: order[key])
        hidden = len(met) - len(named)
        rendered = phrase
        if named:
            rendered += ": " + ", ".join(repr(key) for key in named)
        if hidden:
            rendered += (
                f", and {hidden} further argument{'s' if hidden > 1 else ''} this "
                f"declaration's schema does not describe"
            )
        clauses.append(rendered)
    return "; ".join(clauses)


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
    return not uncovered(row, request)


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


#: RFC 3339 §5.6's ``full-date``, and nothing wider. ``date.fromisoformat`` admits
#: more than this — the compact ``20260913`` and ISO week dates such as
#: ``2026-W37-7`` — and ADR-0254 §4 admits *"a calendar date"* under the same
#: grammar the date-time arm is stated in, so the wider forms are refused here.
_FULL_DATE = re.compile(r"\A\d{4}-\d{2}-\d{2}\Z")

#: RFC 3339 §5.6's ``date-time``: ``full-date``, the ``T`` separator (that section's
#: own case rule permits ``t``), ``partial-time`` with an optional fraction, and a
#: ``time-offset`` that is ``Z``/``z`` or ``±HH:MM``.
#:
#: **Written out rather than delegated to** ``datetime.fromisoformat``, because that
#: function implements **ISO 8601** and is strictly wider: it accepts *any* single
#: character as the date/time separator — so ``2026-09-13X10:00:00+00:00`` parses —
#: a colon-free offset (``+0000``), a comma as the fractional separator, and the
#: compact and week-date forms. Each of those would be an argument ADR-0254 §4 does
#: not admit **satisfying** a bound, which is the permissive direction and the one
#: direction §4 refuses: *"the answer is not to round, to quantise or to pick a
#: tolerance, it is to refuse and ask."*
_DATE_TIME = re.compile(r"\A\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(\.\d+)?([Zz]|[+-]\d{2}:\d{2})\Z")


def _instant_of(  # noqa: PLR0911 — one return per form the grammar or the zone refuses
    text: str, zone: str | None
) -> datetime | None:
    """The instant ``text`` denotes, or ``None`` where the reading refuses it.

    **The grammar is checked before anything is parsed**, and the two arms are told
    apart by which pattern matched rather than by which parser happened to succeed.
    ``datetime.fromisoformat`` and ``date.fromisoformat`` are then used only to turn
    a string already known to be in the admitted grammar into a value, which is what
    keeps this reading exactly as wide as ADR-0254 §4 states it and no wider.
    """
    if _FULL_DATE.match(text):
        if zone is None:  # pragma: no cover — a PERIOD bound's model requires one
            return None
        try:
            located = ZoneInfo(zone)
        except ZoneInfoNotFoundError, ValueError:  # pragma: no cover — the model validates it
            return None
        try:
            day = date.fromisoformat(text)
        except ValueError:  # pragma: no cover — an impossible date, e.g. 2026-02-31
            return None
        start = datetime.combine(day, time(), tzinfo=located)
        # **A civil date that has no start in that zone denotes no instant, and the
        # reading refuses it** (§4's totality: *"every failure of it is a refusal to
        # cover"*). A zone can skip a whole calendar day — Samoa skipped 30 December
        # 2011 when it crossed the date line — and ``datetime.combine`` answers such a
        # date with an instant all the same, resolving the gap by PEP 495's rule. That
        # instant belongs to a **different** local day, so a bound containing it would
        # cover a request whose date the user could not have meant: the permissive
        # direction, on a value nothing in this system can prove. The round trip is
        # the whole test — where the instant reads back as the day asked for, the day
        # has a start and this is it.
        try:
            round_tripped = start.astimezone(UTC).astimezone(located).date()
        except OverflowError, OSError, ValueError:
            # **A date at the representable boundary is unreadable, not an exception
            # out of ``decide``** (§4). ``0001-01-01`` in a zone ahead of UTC
            # converts to a year-0 instant, which ``datetime`` cannot hold and which
            # surfaces as ``OverflowError`` — neither a ``ValueError`` nor an
            # ``AssistantError``, so it would leave the policy's own error boundary
            # through a hole and take down a ruling that owed a ``CONFIRM``. §4's
            # totality clause is what this is: "every failure of it is a refusal to
            # cover".
            return None
        if round_tripped != day:
            return None
        return start
    if not _DATE_TIME.match(text):
        return None
    # **RFC 3339 §5.6's own case rule permits a lower-case ``t`` and ``z``**, and
    # ``datetime.fromisoformat`` accepts the first and refuses the second. Upper-
    # casing both markers before the parse is what makes the grammar above and the
    # reading below admit exactly the same set: a regex that claimed a form the
    # parse then refused would be a second statement of the rule, free to disagree
    # with the first — and the disagreement would be silent, since a refusal to
    # read is indistinguishable from a refusal to cover.
    normalised = f"{text[:10]}T{text[11:-1]}{text[-1].upper()}"
    try:
        parsed = datetime.fromisoformat(normalised)
    except ValueError:  # pragma: no cover — an impossible date inside the grammar
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


__all__ = [
    "ArgumentFailure",
    "UncoveredArgument",
    "account_of",
    "covers",
    "covers_arguments",
    "uncovered",
    "user_facing",
]
