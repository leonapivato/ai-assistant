"""The coverage comparison, in one place (ADR-0254 §§3, 4, 6; ADR-0266 §7).

Whether a live :class:`~ai_assistant.core.types.Authorization` covers a concrete
:class:`~ai_assistant.core.types.ActionRequest`, and whether it covers the
request's **arguments** alone — which is ADR-0254 §6's argument-authority bar,
stated over §3's condition 6 and no other condition.

**A member records what the user stated and never which slot it fills**
(ADR-0266 §3), so condition 6 is no longer a set equality over argument keys.
ADR-0266 §7 replaces it with **two routes** and three conjuncts:

* the **evidence route**, ``MONEY``-only — the member is proved against the
  **quote taken for the step's intended action**, whose arguments digest equals
  this request's. ADR-0267 supplies the operand: the quotes reach these functions
  as an argument, read once per ruling by the policy through
  :meth:`~ai_assistant.core.protocols.GoalQuotes.for_action` and **keyed on the
  goal and the act**, so the selection of the governing one — the last member of
  what comes back — is taken here and in one place (§5).
* the **argument route**, available only where the declaration itself declares an
  argument at the member's kind (``ToolDefinition.bounded_arguments``). A
  ``MONEY`` member needs the **evidence** route in every case and this one **as
  well** where the declaration declares an amount — *"a filter is not a charge"*.

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
exception** (§4). Every fact a comparison needs is on the row, on the
**declaration** or in the request: which key holds an amount and which key holds
its currency are the declaration's (ADR-0266 §7), which zone a date is read in and
which strings a term may take are the bound's. ADR-0145 §1's schema check decides
whether the call is well-formed and decides nothing about coverage.

**One canonical JSON encoding**, and it is
:func:`~ai_assistant.core.types.canonical_json_bytes` — the encoding
``ActionRequest.parameters_digest`` is taken over. A fixed-value comparison
written by hand would be a second canonicalisation of a payload, and two that
disagree produce a false mismatch at one end and a **false match** at the other.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, time
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import TYPE_CHECKING, Final, NamedTuple
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import TypeAdapter

from ai_assistant.core import types as ai_types
from ai_assistant.core.types import (
    BoundAccount,
    BoundKind,
    CanonicalDestination,
    FrozenJsonMapping,
    ToolDefinition,
    canonical_json_bytes,
)
from ai_assistant.permissions._detachment import field_state

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.core.types import (
        ActionQuote,
        ActionRequest,
        Authorization,
        BoundedArgument,
        CoverageMember,
        FrozenJson,
        SpanCoverage,
        ValueBound,
    )


#: ``ActionRequest.parameters``' own annotated type, so the capture below is
#: **rebuilt through the same validation the field is** rather than copied.
#:
#: A ``dict(request.parameters)`` would detach the top level and leave every nested
#: value shared: :class:`~ai_assistant.core.types.FrozenDict` holds its pairs in one
#: ``__slots__`` attribute and refuses assignment, which
#: ``object.__setattr__(nested, "_items", …)`` goes straight past — so a caller
#: could rewrite ``parameters["prefs"]["x"]`` while the authorization seam was out
#: and the comparison would read the rewritten value. ``_freeze_json`` rebuilds
#: every container beneath the root, which is ``recipient_grants.py``'s *"detached
#: **recursively**, which is what ``field_state`` buys over a copy of ``__dict__``"*
#: reaching the one field on this request that is not a model.
#:
#: **It is not ADR-0145 §1's schema evaluation**, which is what makes this cheaper
#: than rebuilding the whole :class:`~ai_assistant.core.types.ActionRequest`: the
#: walk here is the freeze the field already runs at construction, and no schema is
#: consulted — §4's *"no reading consults a schema to decide what an argument
#: means"* holds of the capture as it does of the comparison.
_PARAMETERS: Final[TypeAdapter[Mapping[str, FrozenJson]]] = TypeAdapter(FrozenJsonMapping)


class CoverageSubject(NamedTuple):
    """What one request asks ADR-0254 §§3 and 4, read in a **single** observation.

    Built by :func:`coverage_subject` **before the ruling's first suspension** and
    consulted afterwards in the request's place, so that one ruling is decided about
    one request (ADR-0065). A sourced ruling suspends — ``live_for`` is a durable
    read — and a frozen model is rewritable through ``__dict__``, so a caller can
    replace ``goal`` and ``parameters`` while that seam is out. A policy that
    selected the row for the goal it read on the way in and compared the arguments
    it read on the way out would ``ALLOW`` a request that is **neither** the one
    presented nor the one substituted.

    ``permissions/recipient_grants.py``'s ``_coverage_subject`` is the model this
    follows one seam over, and the values are **detached as well as captured**:
    capturing the objects alone leaves the same rewrite available one level down.
    Rebuilt through validation and never deep-copied, which is
    ``core.types._detached_tool``'s own discipline continued across a suspension
    rather than a new one.

    **Narrower than a whole validated** :class:`~ai_assistant.core.types.ActionRequest`
    **snapshot, deliberately.** Rebuilding the request would re-run ADR-0145 §1's
    schema evaluation on every ruling, and every value §§3 and 4 are stated over is
    named here — so the cheaper capture is not a weaker one over the comparisons it
    carries.
    """

    goal: str | None
    """``request.goal``: which row ``live_for`` is asked for, and ``None`` where a
    request reaches route (d) in no case."""

    intended_action: str | None
    """``request.intended_action``: the act this request is an attempt at, which is
    what selects the quote ADR-0266 §7's evidence route compares against.

    **Carried across the suspension with the rest of the subject**, because it
    selects the evidence the ``MONEY`` comparison is taken against: a policy that
    read one act on the way in and another on the way out would prove a ceiling
    against a price quoted for a different act. ``None`` is met by that route in no
    case."""

    tool: ToolDefinition
    """The declaration by value — §3's condition 3 — and what :func:`user_facing`
    and :func:`account_of` read."""

    parameters: Mapping[str, FrozenJson]
    """The arguments condition 6 and every §4 reading are taken over.

    **Rebuilt through ``FrozenJsonMapping``'s own validation and therefore detached
    all the way down** (:data:`_PARAMETERS`), because a top-level copy would leave
    every nested value shared with the caller."""

    parameters_digest: str
    """``request.parameters_digest``: the one value ADR-0266 §7's evidence route
    compares an :class:`~ai_assistant.core.types.ActionQuote`'s own against.

    **The request's own property and never a second canonicalisation** (ADR-0267 §1).
    ``ActionRequest`` computes it *"here rather than supplied by a caller"* over
    ADR-0021 §1's encoding, and the quote carries the quoting request's value of that
    same property — so the two sides of the comparison are one encoding computed in
    one place. Recomputing it from :attr:`parameters` here would be the second
    canonicalisation that produces *"a false mismatch at one end and a **false match**
    at the other"*.

    **Read before the suspension with the rest of the subject** (ADR-0065), because the
    seam the quotes come back from is a durable read: a policy that digested the
    arguments it read on the way in and compared them on the way out would be ruling
    about two requests."""

    account: BoundAccount | None
    """The binding's connected account — §3's condition 4 — and ``None`` exactly
    where the request carries no ``egress_binding`` at all."""

    destinations: tuple[CanonicalDestination, ...]
    """The binding's canonical destination set — §3's condition 5 — empty where the
    request carries no binding."""

    coverage: SpanCoverage | None
    """The binding's ``coverage``, which route (d)'s own condition 4 is taken over,
    and ``None`` where the request carries no binding."""


def coverage_subject(request: ActionRequest) -> CoverageSubject:
    """Read off ``request`` everything a ruling compares, once and detached.

    **Called on ``decide``'s first executed line**, before anything is awaited.
    Every line before the first suspension is already one observation — nothing else
    runs on this loop between two statements that do not await — so what this buys
    is not the reading but the **carrying**: the values survive the suspension the
    authorization seam takes, and every comparison after it is decided over them
    rather than over the caller's object.

    **A request this cannot read is an argument fault and not a ruling**, which is
    why nothing here is guarded. ``decide`` reads ``request.tool`` for its own rule
    table on the same unsuspended stretch, so a request whose ``__dict__`` has been
    emptied already fails there; what this closes is the window a **suspension**
    opens, which is the one nothing above it can see.

    Args:
        request: The action being ruled on.

    Returns:
        The values ADR-0254 §§3 and 4's comparisons are decided over.
    """
    binding = request.egress_binding
    return CoverageSubject(
        goal=request.goal,
        intended_action=request.intended_action,
        tool=ToolDefinition.model_validate(field_state(ToolDefinition, request.tool)),
        parameters=_PARAMETERS.validate_python(request.parameters),
        parameters_digest=request.parameters_digest,
        account=(
            None
            if binding is None
            else BoundAccount.model_validate(field_state(BoundAccount, binding.account))
        ),
        destinations=(
            ()
            if binding is None
            else tuple(
                CanonicalDestination.model_validate(field_state(CanonicalDestination, destination))
                for destination in binding.canonical_destination_set
            )
        ),
        coverage=None if binding is None else binding.coverage,
    )


def user_facing(subject: CoverageSubject) -> frozenset[str]:
    """The keys of the request's arguments the declaration does **not** fill itself.

    ADR-0254 §3: ``ToolDefinition.system_supplied`` names the keys the **system**
    fills — an idempotency key, a client reference, a locale — and *"every key it
    does not name is user-facing"*. **A declaration that classifies no argument
    system-supplied has every argument user-facing**, and condition 6 then reads
    exactly as it would without the classification.

    Args:
        subject: The one observation of the request this ruling is decided over.

    Returns:
        The user-facing argument keys this call actually carries.
    """
    return frozenset(subject.parameters) - frozenset(subject.tool.system_supplied)


class CoverageFailure(StrEnum):
    """Which of ADR-0266 §7's failures one defect met, told apart.

    ADR-0254 §4's *"The three failures are told apart, whichever way the key is
    rendered, because they are different facts about what the user authorised"*,
    restated over §7's three conjuncts — **and a fourth is added, because §7
    creates a failure the three cannot express**: a member whose kind nothing in
    this call is proved against. Folding that into :attr:`REFUSED` would tell a
    user that their ceiling was **breached** when in fact it was compared against
    nothing, which is a different fact about what they authorised and the one this
    tree produces most.

    Not a ``core`` type: ADR-0254 §16's roster is closed over what ``core`` gains,
    and this is a **rendering** detail of one policy's reason rather than a value
    that crosses a boundary.
    """

    UNNAMED = "unnamed"
    """The row's coverage covers this user-facing argument through no member.

    Either the declaration declares it at a kind the row carries no member of, or
    it declares it at no kind at all and no member of the row is met through the
    evidence route — §7's second and third conjuncts, which fail the same way from
    the user's side: nothing they recorded reaches this argument."""

    OMITTED = "omitted"
    """A member would be met against this declared argument and the call omits it.

    *"An act that fixed ``refundable_only`` to ``true`` authorised a call carrying
    that value, and a call that omits it is a different call"* — ADR-0145 inserts
    no schema default, so nothing downstream restores it."""

    REFUSED = "refused"
    """A member covers it and the comparison over its value was **unproven**."""

    UNPROVED = "unproved"
    """A member of this **kind** is met by no route at all (§7's first conjunct).

    The subject is the member's :class:`~ai_assistant.core.types.BoundKind` and not
    an argument key, because there is no argument: a ``MONEY`` member with no
    governing quote is proved against nothing, and a ``PERIOD`` or ``TERMS`` member
    at a declaration declaring no argument at its kind has nothing to be compared
    with. **Every ``MONEY`` member fails this way in this tree** (ADR-0266 §11), so
    it is the ordinary reason a stated ceiling asks rather than an exotic one."""


@dataclass(frozen=True, slots=True)
class CoverageDefect:
    """One way condition 6 failed, and what it was about.

    **Named for a defect rather than for an argument** because ADR-0266 §7's first
    conjunct is about a **member**, which names no argument: :attr:`subject` is an
    argument key for :attr:`CoverageFailure.UNNAMED`, ``OMITTED`` and ``REFUSED``,
    and a ``BoundKind``'s value for ``UNPROVED``.
    """

    subject: str
    failure: CoverageFailure


def declared_at(tool: ToolDefinition, kind: BoundKind) -> BoundedArgument | None:
    """The one argument this declaration declares at ``kind``, or ``None``.

    ADR-0266 §7: the argument route is available where the declaration carries
    **exactly one** ``BoundedArgument`` at the member's kind. **Where it declares
    none, or declares more than one, no member of that kind is met by that route**
    — no default kind, no inference from a value's JSON type, no schema keyword and
    no fallback to an exact comparison. Two declarations of one kind would need a
    precedence rule at the comparison, which is the rule ADR-0254 §2 refuses to
    have.

    Args:
        tool: The declaration being ruled on.
        kind: The member's kind.

    Returns:
        The sole declared argument at that kind, or ``None`` where there is not
        exactly one.
    """
    declared = [one for one in tool.bounded_arguments if one.kind is kind]
    return declared[0] if len(declared) == 1 else None


def _met_through_evidence(  # noqa: PLR0911 — one return per conjunct ADR-0266 §7 states
    member: CoverageMember, subject: CoverageSubject, quotes: Sequence[ActionQuote]
) -> bool:
    """ADR-0266 §7's evidence route, over the quotes the policy read for this act.

    §7 meets a ``MONEY`` member here where all three hold: the request carries an
    ``intended_action``; **the governing quote** — of the quotes available to the
    policy naming that action, the one latest in ADR-0266 §6's order, and no other
    — has an arguments digest equal to this request's own; and that quote's amount
    satisfies the member, with §4's currency conjunct taken **at the quote's own
    currency** and at no key of the request.

    **The selection is here and in one place, and the seam does none of it**
    (ADR-0267 §5). ``GoalQuotes.for_action`` is *"keyed and never asked"*: it filters
    by the goal and the act and evaluates no predicate, returning that action's quotes
    *"in the order the goal holds them"*, and **``permissions`` takes the last member
    of what comes back**. A store that selected would be a second place the governing
    rule lives, and the first conforming implementation to read it differently would be
    right in one of them.

    **The act is re-read off the governing quote, and that is §7's own selection
    rather than a second keying.** §7 selects *"of the quotes available to the policy
    (§6) that name **that** action, the one **latest** in §6's order"*, so naming the
    act is part of the selection and not merely part of the seam's filter. Taking it
    here as well makes the reading **total over its arguments** — this module's own
    posture, *"everything the comparison needs is in its arguments"* — rather than
    resting the whole proof on a caller having keyed correctly, and it fails in the
    closed direction.

    **An earlier quote is consulted in no case** (§7). A re-quote is a refresh of one
    fact and the current price is the later reading, so a request returning to
    arguments a superseded quote was taken over is **uncovered and the act asks**
    rather than reviving a reading the re-quote displaced. Nothing here scans the
    tuple for a matching digest: the last member is read, and it either matches or the
    member is unmet.

    **The digest is compared and never recomputed** (ADR-0267 §1). Both sides are
    ``ActionRequest.parameters_digest`` — the quote carries the quoting request's
    value, the subject carries this one's — so **every argument of the quoting call is
    inside it, system-supplied keys included**, and a quoting call and an acting call
    differing in **any** key are covered by no quote and ask.

    **A ``MONEY`` member always carries a bound**, so §7's *"ADR-0254 §3's fixed
    comparison or §4's ``MONEY`` reading"* has one live limb here: ADR-0266 §3 refuses
    a ``MONEY`` ``fixed`` outright — *"an amount carries no currency on a fixed member,
    so nothing could denominate it"* — and the type is what makes that true rather than
    a branch below.

    **The amount reading is** :func:`_within` **and is the argument route's own**, so
    the two routes cannot disagree about where an endpoint lies:
    ``maximum_exclusive`` is read strictly, and no reading rounds, quantises, nudges or
    relaxes an endpoint in either direction. **The quote's amount needs no JSON
    typing**: :class:`~ai_assistant.core.types.ActionQuote` admits only a finite,
    non-negative ``Decimal``, so the float, boolean, non-finite and negative refusals
    §4 takes over a request's raw value are taken at the record's own construction.

    **No member of any other kind is met by this route in any case**: a quote states
    a price and carries no other value, so there is nothing for a ``PERIOD`` or a
    ``TERMS`` member to be compared against.

    **A fault is never an absence.** Where the read behind the quotes fails, the
    request is treated as **not covered** and the fault is reported; no implementation
    converts a fault into an absence of quotes, and none falls through to the argument
    route. That happens at the seam rather than here — the policy takes ADR-0254 §6's
    bar and never calls this — which is why an empty ``quotes`` here means exactly
    *the goal holds no quote for this act*.

    Args:
        member: The row's member.
        subject: The one observation of the request this ruling is decided over.
        quotes: That goal's quotes naming the request's intended action, **in the order
            the goal holds them**, as the one seam read returned them. Empty where the
            goal holds none, where the request carries no act, and where this policy
            holds no seam at all — each of which leaves every ``MONEY`` member unmet,
            which is the fail-closed direction.

    Returns:
        Whether the evidence route meets this member.
    """
    if member.kind is not BoundKind.MONEY:
        return False
    if subject.intended_action is None:
        return False
    if not quotes:
        return False
    governing = quotes[-1]
    if governing.intended_action != subject.intended_action:
        return False
    if governing.arguments_digest != subject.parameters_digest:
        return False
    bound = member.bound
    if bound is None:  # pragma: no cover — ADR-0266 §3 refuses a MONEY fixed member
        return False
    if governing.currency != bound.currency:
        return False
    return _within(bound, governing.amount)


def _met_on_argument_route(
    member: CoverageMember, declared: BoundedArgument, subject: CoverageSubject
) -> bool:
    """ADR-0266 §7's argument route, over one member and one declared argument.

    The request carries a value at ``declared.argument`` and that value satisfies
    the member under ADR-0254 §3's fixed comparison or §4's reading, with a ``MONEY``
    bound's currency conjunct taken at ``declared.currency_argument`` **in the
    concrete request** — which is what makes that currency key *covered* rather than
    unexamined.

    **An argument the request does not carry is not covered**, whichever shape the
    member takes: an act that fixed a value authorised a call *carrying* it.

    **§7's exactly-one rule is taken here and in one place**, so every caller gets
    it: where the declaration declares no argument at the member's kind, or declares
    **more than one**, this route meets the member against nothing — *"no default
    kind, no inference from a value's JSON type, no schema keyword and no fallback
    to an exact comparison"*. Two declarations at one kind would need a precedence
    rule at the comparison, which is the rule ADR-0254 §2 refuses to have.

    Args:
        member: The row's member, of the kind ``declared`` declares.
        declared: The one argument this declaration declares at that kind.
        subject: The one observation of the request this ruling is decided over.

    Returns:
        Whether the argument route meets this member.
    """
    if declared_at(subject.tool, member.kind) != declared:
        return False
    if declared.argument not in subject.parameters:
        return False
    value = subject.parameters[declared.argument]
    if member.bound is None:
        return canonical_json_bytes(value) == canonical_json_bytes(member.fixed)
    return _satisfies(member.bound, value, declared, subject)


def _member_defects(
    member: CoverageMember, subject: CoverageSubject, quotes: Sequence[ActionQuote]
) -> tuple[CoverageDefect, ...]:
    """Every way ``member`` is not met over this request — empty where it is.

    ADR-0266 §7's first conjunct, **and the account of its failure in the same
    computation**, so the predicate and the reason cannot disagree.

    * A ``MONEY`` member needs the **evidence** route in every case, and the
      argument route **as well** where the declaration declares an argument at
      ``MONEY`` — both holding, because *"a ``max_price`` constrains what a search
      returns and a transfer amount is one leg of a call"*.
    * A ``PERIOD`` or a ``TERMS`` member is met by the argument route alone.

    **Both routes are examined, and neither failure hides the other.** An earlier
    shape returned at the first failure, so a call omitting the declared amount
    while carrying its currency was told only that the price was proved by nothing
    — never that it had dropped an argument the user's act covers. Those are
    *"different facts about what the user authorised"* (ADR-0254 §4), and §7 asks
    for **both** routes to hold rather than for one answer about them; a reason that
    folds them tells the user the wrong one. Adversarial review, round 4,
    ``blocker``.

    Args:
        member: The row's member.
        subject: The one observation of the request this ruling is decided over.
        quotes: That goal's quotes naming the request's intended action, oldest first.

    Returns:
        The defects this member met, ordered as the routes are read.
    """
    found: list[CoverageDefect] = []
    declared = declared_at(subject.tool, member.kind)
    if member.kind is BoundKind.MONEY and not _met_through_evidence(member, subject, quotes):
        # **The quote is the primary proof and a declared argument never stands in
        # for it** (ADR-0266 §7). Reported even where a declared amount sits inside
        # the ceiling, because that is what happened: the price the act will make was
        # compared against nothing.
        found.append(CoverageDefect(member.kind.value, CoverageFailure.UNPROVED))
    if declared is None:
        if member.kind is not BoundKind.MONEY:
            # A ``PERIOD`` or ``TERMS`` member is met by the argument route alone,
            # and this declaration declares no argument at its kind, or declares two.
            found.append(CoverageDefect(member.kind.value, CoverageFailure.UNPROVED))
        # **A ``MONEY`` member reaching here is the case §7 admits**: the quote is
        # the primary proof and the argument route an additional safeguard, so a
        # declaration declaring no amount keeps its ceiling proved against the quote.
    elif declared.argument not in subject.parameters:
        found.append(CoverageDefect(declared.argument, CoverageFailure.OMITTED))
    elif not _met_on_argument_route(member, declared, subject):
        found.append(CoverageDefect(declared.argument, CoverageFailure.REFUSED))
    return tuple(found)


def _examined_currency_keys(row: Authorization, subject: CoverageSubject) -> frozenset[str]:
    """The currency keys §7's conditional exemption reaches.

    **A key a ``BoundedArgument`` names as its ``currency_argument`` is not an
    argument the declaration declares at no kind — but only where the comparison
    that consumes it was actually taken.** It is exempt where the request carries a
    value at that ``BoundedArgument``'s own ``argument``, the row carries a ``MONEY``
    member, and that member is met **on the argument route** against it, whose §4
    comparison reads the currency key there.

    **In every other case it is an ordinary user-facing argument the declaration
    declares at no kind**: a request carrying the currency and no amount, or one
    whose row holds no ``MONEY`` member, leaves it compared by nothing — so §7's
    third conjunct reaches it and the request is uncovered without a quote. An
    unconditional exemption would let ``{"currency": "EUR"}`` and
    ``{"currency": "USD"}`` both pass an empty row.
    """
    money = next((member for member in row.coverage if member.kind is BoundKind.MONEY), None)
    if money is None:
        return frozenset()
    return frozenset(
        one.currency_argument
        for one in subject.tool.bounded_arguments
        if one.kind is BoundKind.MONEY
        and one.currency_argument is not None
        and one.argument in subject.parameters
        and _met_on_argument_route(money, one, subject)
    )


def uncovered(
    row: Authorization, subject: CoverageSubject, quotes: Sequence[ActionQuote]
) -> tuple[CoverageDefect, ...]:
    """Every way ADR-0266 §7's **condition 6** fails over this pair, told apart.

    Empty exactly where :func:`covers_arguments` answers ``True``, which is what
    keeps the predicate and the account of its failure one computation rather than
    two that can disagree.

    The three conjuncts, each in one direction and neither dropped:

    1. **Every member of the row is met**, by the two routes (:func:`_member_defect`).
       A member met by no route leaves the request uncovered, which is ADR-0254 §3's
       second direction — *"an act that fixed ``refundable_only`` to ``true``
       authorised a call **carrying** that value"*.
    2. **Every user-facing argument the declaration declares in a ``BoundedArgument``
       is covered by the member of that argument's kind**, a request carrying no
       member of that kind being uncovered — §3's first direction.
    3. **Where the request carries any user-facing argument the declaration declares
       at no kind, at least one member of the row is met through the evidence
       route**, whose digest pins every argument the request carries. Without it a
       row fixing ``subject`` to *"urgent"* would cover a later ``send_message``
       carrying a different ``body``; with it the owner's booking case, whose
       ``site``, ``dates`` and ``party`` are declared nowhere, is covered through its
       quote while a tool with no quote and undeclared arguments asks.

    **There is no default, no wildcard and no omission that reads as consent.**

    Args:
        row: The live record the one ``live_for`` read returned.
        subject: The one observation of the request this ruling is decided over.
        quotes: That goal's quotes naming the request's intended action, **in the order
            the goal holds them**, as the one ``for_action`` read returned them.

    Returns:
        The failures, ordered by :class:`CoverageFailure` and then by subject, so a
        rendering of them is deterministic without the renderer sorting.
    """
    found: set[CoverageDefect] = set()
    kinds = {member.kind: member for member in row.coverage}
    # **The first conjunct** — every member of the row is met, by the two routes,
    # and a member met by neither reports both failures rather than the first.
    for member in row.coverage:
        found.update(_member_defects(member, subject, quotes))
    carried = user_facing(subject)
    declared = {one.argument: one for one in subject.tool.bounded_arguments}
    # **The second** — every user-facing argument the declaration declares is covered
    # by the member of that argument's kind, a row carrying none being uncovered.
    for key in carried & set(declared):
        at_kind = kinds.get(declared[key].kind)
        if at_kind is None:
            found.add(CoverageDefect(key, CoverageFailure.UNNAMED))
        elif not _met_on_argument_route(at_kind, declared[key], subject):
            found.add(CoverageDefect(key, CoverageFailure.REFUSED))
    # **The third** — an argument the declaration declares at no kind needs a member
    # met through the evidence route, whose digest pins every argument the request
    # carries.
    undeclared = carried - set(declared) - _examined_currency_keys(row, subject)
    if undeclared and not any(
        _met_through_evidence(member, subject, quotes) for member in row.coverage
    ):
        found.update(CoverageDefect(key, CoverageFailure.UNNAMED) for key in undeclared)
    return tuple(sorted(found, key=lambda defect: (defect.failure.value, defect.subject)))


#: What a ruling says about each of §7's failures, in the order they are rendered.
#: **No value, no bound, no record id and no digest**: a reason is carried on a
#: durable ``PermissionDecision`` that holds ``parameters_digest`` and not
#: ``parameters``, and quoting a value would put into the trail exactly what that
#: omission keeps out (ADR-0254 §4).
_ACCOUNTS: Final[tuple[tuple[CoverageFailure, str], ...]] = (
    (
        CoverageFailure.UNNAMED,
        "the user's own recorded act for this goal covers no such argument",
    ),
    (
        CoverageFailure.OMITTED,
        "this call omits an argument the user's own recorded act covers",
    ),
    (
        CoverageFailure.REFUSED,
        "this call is outside what the user's own recorded act allows",
    ),
    (
        CoverageFailure.UNPROVED,
        "the user's own recorded act states a limit nothing about this call proves",
    ),
)


def account_of(defects: Sequence[CoverageDefect], tool: ToolDefinition) -> str:
    """Render ADR-0254 §4's account of why coverage failed, for the user.

    **It never reproduces an argument's value, the bound, the record's id or its
    digest** (§4). **And it names an argument's key only where the declaration's
    ``parameters_schema`` itself names that key**: ADR-0145 §8 rules that a message
    about arguments *"renders any part of the parameters — neither a value nor a
    key"* except what *"the schema itself names"*, on the ground that *"a key can
    be data"* — a mapping the schema does not describe can be keyed by an address
    or an identifier, and an argument key is a key of ``parameters`` with nothing
    requiring the schema to declare it.

    So a key the schema declares is named; **a key it does not is counted rather
    than listed**, which is ADR-0145 §8's *"by keyword and location rather than by
    key"* read onto this message. Where several arguments fail, they are named in
    the **declaration's own schema order**.

    **A ``CoverageFailure.UNPROVED`` defect's subject is a ``BoundKind`` and is
    always named.** It is a member of a closed vocabulary this system minted, not a
    key a caller influenced, so ADR-0145 §8's reason for withholding does not reach
    it — and withholding it would leave the one failure this tree produces most
    saying only that something was unproven, without saying what.

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
        met = [one.subject for one in defects if one.failure is failure]
        if not met:
            continue
        if failure is CoverageFailure.UNPROVED:
            clauses.append(phrase + ": " + ", ".join(sorted(met)))
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


def covers_arguments(
    row: Authorization, subject: CoverageSubject, quotes: Sequence[ActionQuote]
) -> bool:
    """ADR-0254 §3's **condition 6** as ADR-0266 §7 restates it, alone (§6's bar).

    **Stated in both of §3's directions, because an omission is a change as much as
    an addition is.** An argument the row cannot cover leaves it uncovered — §3's
    first direction — and a member met by no route leaves it uncovered too, which is
    §3's second: an act that fixed ``refundable_only`` to ``true`` authorised a call
    *carrying* that value, and a call that omits it is a different call. ADR-0145
    inserts no schema default, so nothing downstream restores it, and the omission
    would silently buy whatever the service does when the field is absent. **There
    is no default, no wildcard, no "not sent therefore unconstrained" and no
    omission that reads as consent.**

    **The empty case holds vacuously** (§1, §3): a row with ``coverage=()`` has no
    member to meet, and a request carrying no user-facing argument declares nothing
    and leaves the third conjunct's set empty — so condition 6 holds, and that is
    the one request such a row covers. A request carrying system-supplied arguments
    and no others is such a request.

    **A system-supplied argument is not among them and never fires the bar**, which
    is what keeps an implementation choice out of a question put to the user — and
    ``ToolDefinition.bounded_arguments`` names no such key, so none can be met by a
    member either.

    Args:
        row: The live record the one ``live_for`` read returned.
        subject: The one observation of the request this ruling is decided over.
        quotes: That goal's quotes naming the request's intended action, oldest first.

    Returns:
        Whether condition 6 holds over that pair.
    """
    return not uncovered(row, subject, quotes)


def covers_on_argument_route(row: Authorization, subject: CoverageSubject) -> bool:
    """Whether every argument of this request is covered on the **argument** route.

    **ADR-0266 §7's narrowing of ADR-0254 §6's lineage discharge, in the narrowing
    direction alone.** §6 discharges ADR-0181 §5's floor for a request a live row
    covers *"in full"*, on the ground that where every user-facing argument is
    covered by *"the user's own fixed values and permitted ranges"*, outside content
    *"cannot have steered anything the user did not bound"*. **The digest does not
    supply that ground**: condition 6's third conjunct proves the call is the one
    that was **quoted**, and both the quoted arguments and the quoting output passed
    through a plan and a tool. A digest proves the call is the one quoted, not one
    the user bounded.

    So a request whose ``egress_binding`` carries ``planned_with_external_content``
    is discharged **only** where this answers ``True``. **Where it is not, the floor
    binds unrelaxed and the ruling is the ``CONFIRM`` the table reached** — §6's own
    *"Partial coverage still asks"*, reached by one further case. Every other limb
    of §6 binds entire.

    **A currency key the argument route's own §4 comparison read is covered by it**,
    which is §7's *"what makes that currency key **covered** rather than
    unexamined"* — the same conditional exemption condition 6 takes, and not a
    second rule.

    **The empty case is discharged vacuously**: a request carrying no user-facing
    argument has nothing outside content could have steered.

    Args:
        row: The live record the one ``live_for`` read returned.
        subject: The one observation of the request this ruling is decided over.

    Returns:
        Whether every user-facing argument the request carries is covered by a
        member on the argument route.
    """
    kinds = {member.kind: member for member in row.coverage}
    declared = {one.argument: one for one in subject.tool.bounded_arguments}
    exempt = _examined_currency_keys(row, subject)
    for key in user_facing(subject):
        if key in exempt:
            continue
        one = declared.get(key)
        if one is None:
            return False
        member = kinds.get(one.kind)
        if member is None or not _met_on_argument_route(member, one, subject):
            return False
    return True


def covers(row: Authorization, subject: CoverageSubject, quotes: Sequence[ActionQuote]) -> bool:
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
        subject: The one observation of the request this ruling is decided over.
        quotes: That goal's quotes naming the request's intended action, oldest first.

    Returns:
        Whether the row covers the request **in full**, which is what ADR-0254 §6's
        lineage discharge and route (d)'s ``ALLOW`` both rest on.
    """
    if subject.account is None:
        return False
    if subject.tool != row.tool or subject.account != row.account:
        return False
    if any(member not in row.destinations for member in subject.destinations):
        return False
    return covers_arguments(row, subject, quotes)


def _satisfies(
    bound: ValueBound, value: FrozenJson, declared: BoundedArgument, subject: CoverageSubject
) -> bool:
    """ADR-0254 §4's reading of one argument against one bound.

    Total, and every failure is a refusal to cover rather than an exception.
    """
    if bound.kind is BoundKind.MONEY:
        return _satisfies_money(bound, value, declared, subject)
    if bound.kind is BoundKind.PERIOD:
        return _satisfies_period(bound, value)
    return _satisfies_terms(bound, value)


def _satisfies_money(
    bound: ValueBound, value: FrozenJson, declared: BoundedArgument, subject: CoverageSubject
) -> bool:
    """ADR-0254 §4's ``MONEY`` reading, with the currency conjunct over the request.

    The argument's value is a JSON **string** ``Decimal`` accepts, or a JSON
    **integer**; the resulting ``Decimal`` is finite and not negative; it is **less
    than** ``maximum`` where ``maximum_exclusive`` is set and **at most** it
    otherwise; where a ``minimum`` is carried, at least that; **and the request
    carries, at the declaration's ``currency_argument``, a JSON string equal to the
    bound's ``currency`` byte for byte**.

    **The currency key is the declaration's and no longer the bound's** (ADR-0266
    §3, §7): the key carrying an amount's currency is a fact about a *declaration*,
    not about an act, so it is read off the :class:`BoundedArgument` that declared
    this argument. §4's conjunct is otherwise unmoved — **stated over the concrete
    request rather than over the row**, so a row whose bound says one currency and
    whose request says another covers nothing rather than covering the wrong amount
    of the wrong money; and a request carrying no value at that key is **not
    covered**.

    **``maximum_exclusive`` is read strictly and no endpoint is ever widened**
    (ADR-0266 §3): *"under 100 euros"* does not cover a call at exactly ``100``,
    *"at most 100 euros"* does, and no reading rounds, quantises, nudges or relaxes
    an endpoint in either direction — the difference is a cent in the direction that
    authorises a call the user did not authorise.

    **A JSON floating-point value never satisfies a ``MONEY`` bound.** A binary
    float is not a price, and comparing one against a decimal bound is precisely
    the unproven comparison ADR-0148 §2 refuses by default: the answer is not to
    round, to quantise or to pick a tolerance, it is to refuse and ask. A JSON
    **boolean** is refused with it: ``bool`` is an ``int`` in Python and ``True``
    would otherwise read as one.
    """
    if declared.currency_argument is None:  # pragma: no cover — the model
        return False
    stated = subject.parameters.get(declared.currency_argument)
    if not isinstance(stated, str) or stated != bound.currency:
        return False
    if isinstance(value, bool) or not isinstance(value, str | int):
        return False
    try:
        amount = Decimal(value)
    except InvalidOperation, ValueError:
        return False
    if not amount.is_finite() or amount < 0:
        return False
    return _within(bound, amount)


def _within(bound: ValueBound, amount: Decimal) -> bool:
    """Whether ``amount`` lies inside a ``MONEY`` bound's endpoints (ADR-0254 §4).

    **One statement, read by both of ADR-0266 §7's routes**, so a figure the evidence
    route admits and one the argument route admits cannot come apart at an endpoint.

    **``maximum_exclusive`` is read strictly and no endpoint is ever widened**
    (ADR-0266 §3): *"under 100 euros"* does not cover a call at exactly ``100``, *"at
    most 100 euros"* does, and no reading rounds, quantises, nudges or relaxes an
    endpoint in either direction — the difference is a cent in the direction that
    authorises a call the user did not authorise.

    Args:
        bound: The member's ``MONEY`` bound.
        amount: The amount to read, already finite and not negative.

    Returns:
        Whether the amount is within the bound.
    """
    if bound.maximum is None:  # pragma: no cover — the model
        return False
    if amount > bound.maximum or (bound.maximum_exclusive and amount == bound.maximum):
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

    **The reading itself is** :func:`~ai_assistant.core.types.period_reading_form`,
    which the `core` type validates a fixed ``PERIOD`` value against — one parser,
    so a string this refuses can never be a value a member holds, and a string it
    admits is read the same way at both ends (ADR-0266 §3).

    What is left here is the half that needs the **bound's own zone**: which instant
    a calendar date denotes, and whether that civil day exists in that zone at all.
    """
    read = ai_types.period_reading_form(text)
    if read is None:
        return None
    if isinstance(read, datetime):
        return read
    if zone is None:  # pragma: no cover — a PERIOD bound's model requires one
        return None
    try:
        located = ZoneInfo(zone)
    except ZoneInfoNotFoundError, ValueError:  # pragma: no cover — the model validates it
        return None
    start = datetime.combine(read, time(), tzinfo=located)
    # **A civil date that has no start in that zone denotes no instant, and the
    # reading refuses it** (§4's totality: *"every failure of it is a refusal to
    # cover"*). A zone can skip a whole calendar day — Samoa skipped 30 December 2011
    # when it crossed the date line — and ``datetime.combine`` answers such a date
    # with an instant all the same, resolving the gap by PEP 495's rule. That instant
    # belongs to a **different** local day, so a bound containing it would cover a
    # request whose date the user could not have meant: the permissive direction, on
    # a value nothing in this system can prove. The round trip is the whole test —
    # where the instant reads back as the day asked for, the day has a start and this
    # is it.
    try:
        round_tripped = start.astimezone(UTC).astimezone(located).date()
    except OverflowError, OSError, ValueError:
        # **A date at the representable boundary is unreadable, not an exception out
        # of ``decide``** (§4). ``0001-01-01`` in a zone ahead of UTC converts to a
        # year-0 instant, which ``datetime`` cannot hold and which surfaces as
        # ``OverflowError`` — neither a ``ValueError`` nor an ``AssistantError``, so
        # it would leave the policy's own error boundary through a hole and take down
        # a ruling that owed a ``CONFIRM``.
        return None
    return start if round_tripped == read else None


def _satisfies_terms(bound: ValueBound, value: FrozenJson) -> bool:
    """ADR-0254 §4's ``TERMS`` reading: membership by the stored characters.

    **No fold, no strip, no case-insensitive match, no prefix and no substring** —
    ADR-0237 §3's rule for a ``TopicLabel`` read onto a set the user named.
    """
    if bound.terms is None:  # pragma: no cover — the model requires it of a TERMS bound
        return False
    return isinstance(value, str) and value in bound.terms


__all__ = [
    "CoverageDefect",
    "CoverageFailure",
    "CoverageSubject",
    "account_of",
    "coverage_subject",
    "covers",
    "covers_arguments",
    "covers_on_argument_route",
    "declared_at",
    "uncovered",
    "user_facing",
]
