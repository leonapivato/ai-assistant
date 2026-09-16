"""Minting a `STATED_BOUND` coverage member from the goal's own words (ADR-0266).

ADR-0266 §11's **L2**: *"the mint in `orchestration`"*. §8's writer clause puts it
here and nowhere else — *"`orchestration` mints every coverage member … No
`ActionPolicy`, no `ToolRegistry`, no store, no reader, no interface adapter, no
tool and no model **constructs, writes or repairs** one"* — and this module is that
one place. :func:`~ai_assistant.orchestration.authorizing.proposed_authorization`
takes what it returns as condition 6's fourth operand and writes it onto the row.

**The whole input is the goal** (§5): *"the mint reads the goal's own current
interpretation and its retained history, and nothing else. **No request, no plan, no
step, no declaration, no registry, no quote, no utterance beyond the element's own
`span` and no clock.**"* So :func:`stated_bound_coverage` takes one argument, is
synchronous, is total and is a pure function of the value handed to it — which is
what makes *"the authorization records the constraint as the user stated it"* true
of the record rather than of the call that happened to be in flight.

**What it mints is a ceiling or nothing**, and that has a mechanical ground rather
than a judgement about polarity (§4): §7's evidence route is `MONEY`-only because a
quote states a price and nothing else, so a member of another kind could be proposed
and never *met*, and §1's completeness condition would refuse the proposal carrying
it.

**What it mints is `PROPOSED` and is never established from a span** (§4). A member
this module mints reaches a durable row only through ADR-0254 §1's **path (i)**: the
row is written `PROPOSED` before the question is put, ADR-0254 §11's projection
renders the ceiling **beside the user's own words**, and the user's answer settles
it. That is what closes the class of mis-chosen spans no reading rule could — *"avoid
booking hotels under 100 euros"* proposes a ceiling of `100`, the user reads *"up to
100 euros"* beside their own words, answers no, and **no authority exists**. This
module reaches a path-(iii) opening act in no case, that path writing `ESTABLISHED`
directly with no question put.

**Nothing here re-resolves, re-normalises or re-checks a span against a model** (§2).
ADR-0249 §7 already checked the span against that turn's own `TurnResult.utterance`
when the revision was recorded, and ADR-0254 §1 re-takes it against the store before
the row is built. A model contributes exactly one thing to this decision and it is
the span (§8); no value a model produced reaches any input here as a selector or as
a written value.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Final

from ai_assistant.core.types import (
    AuthorizationBasis,
    BoundKind,
    CoverageMember,
    Ground,
    ResolutionRule,
    ValueBound,
    ValueResolution,
)

if TYPE_CHECKING:
    from ai_assistant.core.types import Goal, GoalElement

#: Runs of these are collapsed to one space (ADR-0266 §4). **ASCII whitespace and
#: no other**, written out rather than spelled `\s`: the pattern class Python gives
#: a `str` matches the non-breaking space and every other Unicode space, so `\s`
#: would silently fold a span this reading does not fold and mint a member from
#: words the table does not carry.
_ASCII_WHITESPACE: Final = re.compile(r"[ \t\n\r\f\v]+")

#: The one trailing character the normalisation trims, and it trims **one**
#: (ADR-0266 §4): `"under 100 euros."` reads, `"under 100 euros.."` mints nothing.
_ONE_TRAILING: Final = (".", "!")

#: ADR-0266 §4's currency table, whole. `"no lane adds a form, a currency or a
#: language without its own ratified decision"`, so this mapping is the table and
#: not a sample of it.
_CURRENCIES: Final[dict[str, str]] = {
    "euro": "EUR",
    "euros": "EUR",
    "eur": "EUR",
    "€": "EUR",
    "dollar": "USD",
    "dollars": "USD",
    "usd": "USD",
    "$": "USD",
    "pound": "GBP",
    "pounds": "GBP",
    "gbp": "GBP",
    "£": "GBP",
}

#: ADR-0266 §4's reading table, whole: the leading words of each form, mapped to
#: whether the ceiling they state **excludes** its endpoint. **Four forms and no
#: fifth**, and every form mints a `maximum` — the table states no other direction,
#: so `"at least"`, `"more than"` and `"over"` are forms of nothing here.
_FORMS: Final[dict[tuple[str, ...], bool]] = {
    ("under",): True,
    ("below",): True,
    ("at", "most"): False,
    ("up", "to"): False,
}

#: How many tokens a matched form leaves: the figure and the currency word, in
#: either order (ADR-0266 §4).
_AMOUNT_AND_CURRENCY: Final = 2


def stated_bound_coverage(goal: Goal | None, /) -> tuple[CoverageMember, ...]:
    """The coverage this goal's own recorded words mint (ADR-0266 §§1-5).

    **§1's candidate selection.** A member is minted from a `GoalElement` of the
    goal's **current** interpretation's ``constraints`` whose ``ground`` is
    ``USER_STATED``, *"and from nothing else — not a `criteria` or a `conditions`
    element, not the interpretation's `outcome`, not a plan step, not an evidence
    row, not a quote and not a memory"*. The *current* interpretation alone: an
    element a later revision neither retained nor replaced is not in it (*"omission
    is removal"*), and minting from an earlier revision would restore a constraint
    the user's own later words removed. The history is walked **only** to find the
    act (:func:`_act_of`).

    **§5's one-per-kind refusal.** Where two candidate elements would mint members
    of one ``kind``, **neither** is minted — no precedence, no ordering, no
    most-recent rule and no narrowest-wins rule. *"choosing between two constraints
    the user stated is an interpretation of which one they meant"*, and §9 clause
    (iii)'s answer to an ambiguity is that the user is asked. A later constraint
    that **replaces** an earlier one is ADR-0254 §1's path (ii); two standing at
    once is the ambiguity this refuses.

    **A goal in hand and no goal are one case.** ``None`` mints nothing, which is
    the same disposition as a goal whose constraints read as nothing: the coverage
    is empty, ADR-0254 §1's completeness condition holds only vacuously, and a
    request carrying a user-facing argument proposes no row.

    Args:
        goal: The goal the request's plan was written against, as the store holds
            it, or ``None`` where the caller could not read one.

    Returns:
        The members this goal mints, in the order its constraints carry them.
        Empty where it mints none.
    """
    if goal is None:
        return ()
    minted: list[CoverageMember] = []
    for element in goal.interpretation[-1].constraints:
        if element.ground is not Ground.USER_STATED:
            continue
        member = _minted(goal, element)
        if member is not None:
            minted.append(member)
    # **§5, and it is stated over the whole candidate set rather than pairwise**: a
    # kind two elements reach is minted by neither of them, so a third element of a
    # third kind is unaffected and a kind exactly one element reaches survives.
    ambiguous = {
        member.kind for member in minted if sum(other.kind is member.kind for other in minted) > 1
    }
    return tuple(member for member in minted if member.kind not in ambiguous)


def _minted(goal: Goal, element: GoalElement, /) -> CoverageMember | None:
    """The member this one candidate element mints, or ``None`` (ADR-0266 §2, §4).

    **§2's refusals, and every one of them is fail-closed.** No member is minted
    where the element carries **no `id`** (a row written before ADR-0253 §7, which
    no history can locate), where the element's **`span` is absent** (ADR-0254
    §10's *"A resolution the loop cannot take is not taken, and no member is
    minted"*), where the earliest carrying revision's **`raised_by` is `None`** (a
    row written before ADR-0249, whose act this system never recorded), or where an
    **elided history** makes that revision's primacy unprovable (:func:`_act_of`).

    A ``USER_STATED`` element carrying no span is admitted by ADR-0249 §1's
    validator only in the ``FROM_EVIDENCE`` and ``INFERRED`` shapes, which §1
    excludes; the span check is stated here because this function is handed an
    element rather than a proof about one.

    Args:
        goal: The goal the element belongs to, for its retained history.
        element: The ``USER_STATED`` constraint being read.

    Returns:
        The member, or ``None`` where any refusal above fires or where §4's table
        matches the span in no form.
    """
    if element.id is None or element.span is None:
        return None
    act = _act_of(goal, element.id)
    if act is None:
        return None
    bound = _read_stated_bound(element.span)
    if bound is None:
        return None
    return CoverageMember(
        kind=bound.kind,
        bound=bound,
        basis=AuthorizationBasis(
            act=act,
            span=element.span,
            # **`STATED_BOUND` takes neither argument** (ADR-0266 §4): its one input
            # is the span the basis already names, so there is nothing further to
            # record and a resolution carrying one is refused at construction.
            resolution=ValueResolution(rule=ResolutionRule.STATED_BOUND),
        ),
    )


def _act_of(goal: Goal, element_id: str, /) -> str | None:
    """The act a member resting on this element names, or ``None`` (ADR-0266 §2).

    *"the `raised_by` of the earliest revision of the goal's retained
    `interpretation` that carries an element with that element's `id`"*. Every
    element of a revision is searched, not its constraints alone: the id names one
    element of the interpretation and a revision that carried it as a criterion
    still carries it.

    **An elided history refuses too, and the test is exact rather than
    approximate.** Where the earliest retained revision carrying the id is the
    **oldest retained revision** and ``interpretation_elided`` is not 0, no member
    is minted: ADR-0249 §2 drops the **oldest** revisions, so a dropped one may have
    carried the element first and the act would name the wrong turn. Where the
    carrying revision has a retained predecessor not carrying the id it **is** the
    first, and where nothing was elided the oldest retained revision is. Both are
    decided from values on the goal, with **no store read**.

    Args:
        goal: The goal whose retained revisions are walked.
        element_id: The id of the element the member rests on.

    Returns:
        The act, or ``None`` where the element is carried by no retained revision,
        where an elision leaves its primacy unprovable, or where the carrying
        revision records no ``raised_by``.
    """
    for position, revision in enumerate(goal.interpretation):
        carried = (*revision.constraints, *revision.criteria, *revision.conditions)
        if not any(element.id == element_id for element in carried):
            continue
        if position == 0 and goal.interpretation_elided != 0:
            return None
        return revision.raised_by
    return None  # pragma: no cover — the current revision carries every candidate


def _read_stated_bound(span: str, /) -> ValueBound | None:
    """Read a span as a stated ceiling, or as nothing (ADR-0266 §4).

    **The table is closed and this is the entire reading.** The normalised span is
    matched **in full** against exactly four forms — ``under``/``below`` for a
    strict ceiling, ``at most``/``up to`` for an inclusive one — each taking a
    decimal figure ADR-0254 §4's ``MONEY`` reading accepts together with **one
    word** of §4's currency table, in either order. *"A span matching no form mints
    no member, and no lane adds a form, a currency or a language without its own
    ratified decision."*

    **A question mints nothing, before any other step**: *"under 100 euros?"* asks
    whether a price is below a figure and grants nothing, and ADR-0254 §9 clause
    (iii)'s posture on an ambiguous act is to ask rather than to guess. The test is
    over the span **as given**, a ``?`` anywhere in it being enough.

    **Nothing outside the span is read**: there is no negation vocabulary, no
    adjacency test, no requirement that the span be a clause or be the act's whole
    utterance, and **no lane adds one**. What the text around the span meant is
    settled by the user's answer to the rendered proposal and never by a rule (§4),
    so *"avoid booking hotels under 100 euros"* and *"spend under 100 euros"* read
    the same span identically.

    **A strict word mints a strict bound and the endpoint is never widened.** *"under
    100 euros"* mints ``maximum`` ``100`` with ``maximum_exclusive``, so a call at
    exactly ``100`` is **not** covered; *"at most 100 euros"* mints the same
    ``maximum`` without it. **No reading rounds, quantises, nudges or relaxes an
    endpoint in either direction** — the difference of a cent is a cent in the
    direction that authorises a call the user did not authorise (ADR-0254 §2).

    Args:
        span: The element's span, byte for byte as the revision recorded it.

    Returns:
        The ``MONEY`` ceiling the span states, or ``None`` where it states none.
    """
    if "?" in span:
        return None
    # §4's normalisation, in the order it states and in no other: fold to lower
    # case, collapse runs of ASCII whitespace to one space, trim **one** trailing
    # `.` or `!`. It is *"part of the resolution … recorded with it"* (ADR-0254
    # §10) and is never applied at the comparison. **Nothing strips a leading or a
    # trailing space**: the three steps are the whole of it, a leading run collapses
    # to one leading space, and a span carrying one matches the table in no form —
    # the refusing direction, which is the one §4 takes everywhere else.
    normalised = _ASCII_WHITESPACE.sub(" ", span.lower())
    if normalised.endswith(_ONE_TRAILING):
        normalised = normalised[:-1]
    tokens = normalised.split(" ")
    for words, exclusive in _FORMS.items():
        if tuple(tokens[: len(words)]) != words:
            continue
        return _ceiling(tokens[len(words) :], exclusive=exclusive)
    return None


def _ceiling(rest: list[str], /, *, exclusive: bool) -> ValueBound | None:
    """The bound a matched form's remaining two words state, or ``None`` (§4).

    The figure and the currency word are **two words in either order**, so exactly
    two remain and exactly one of them is a currency word — no member of §4's
    currency table is a figure ``Decimal`` accepts, so the split is unambiguous
    without a precedence rule.

    Args:
        rest: What the form's leading words left, as collapsed-space tokens.
        exclusive: Whether the matched form withdraws the endpoint.

    Returns:
        The ``MONEY`` ceiling, or ``None`` where the two words are not a figure and
        a currency word.
    """
    if len(rest) != _AMOUNT_AND_CURRENCY:
        return None
    first, second = rest
    if first in _CURRENCIES:
        currency, figure = _CURRENCIES[first], second
    elif second in _CURRENCIES:
        currency, figure = _CURRENCIES[second], first
    else:
        return None
    amount = _amount(figure)
    if amount is None:
        return None
    return ValueBound(
        kind=BoundKind.MONEY, currency=currency, maximum=amount, maximum_exclusive=exclusive
    )


def _amount(figure: str, /) -> Decimal | None:
    """The figure as ADR-0254 §4's ``MONEY`` reading accepts it, or ``None``.

    That reading takes *"a JSON **string** that `Decimal` accepts"* whose *"resulting
    `Decimal` is finite and not negative"*, and this is that rule over a word of the
    span rather than over an argument's value. So a figure written in words mints
    nothing — ``"fifty"`` is no decimal figure — and neither does ``"infinity"``,
    ``"nan"`` or a negative, each of which ``Decimal`` accepts and §4 then refuses.

    Args:
        figure: The word the form left in the amount's position.

    Returns:
        The amount, or ``None`` where §4's reading refuses the word.
    """
    try:
        amount = Decimal(figure)
    except InvalidOperation, ValueError:
        return None
    if not amount.is_finite() or amount < 0:
        return None
    return amount
