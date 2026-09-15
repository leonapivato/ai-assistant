"""Builders shared by the goal-authorization suites and the two enforcement points.

ADR-0254's record, the store that holds it, the policy that reads it and the trail
that validates it are four contracts stated over the same handful of values: a
transmitting :class:`ToolDefinition`, a :class:`BoundAccount`, an
:class:`EgressBinding`, the :class:`ActionRequest` wrapping it, and the
:class:`PermissionDecision` a ruling becomes. Building those in one place keeps the
four arranging **identical** subjects, which matters most for the fields whose
equality coverage turns on — a row covers nothing if its declaration differs from
the request's by a reworded description (§3's condition 3).

The authorization records themselves come from
:mod:`ai_assistant.testing.goal_authorizations`, which is the canonical builder a
consumer outside these tests reaches for; this module supplies only what is about a
**call**, which the shipping fakes have no business knowing how to build.

Not a conformance suite itself: nothing here asserts anything.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Final

from ai_assistant.core.types import (
    ActionRequest,
    BoundAccount,
    CanonicalDestination,
    DestinationProtocol,
    DiscloserProvenance,
    EgressBinding,
    EgressDestination,
    EgressSpan,
    PermissionDecision,
    PermissionOutcome,
    PermissionRuling,
    SpanCoverage,
    ToolDefinition,
    canonical_json_bytes,
)
from ai_assistant.testing.goal_authorizations import (
    AUTHORIZATION_ACCOUNT,
    AUTHORIZATION_EXPIRES_AT,
    AUTHORIZATION_GOAL,
    AUTHORIZATION_NOW,
    AUTHORIZATION_PROPOSED_AT,
    AUTHORIZATION_TOOL,
)

if TYPE_CHECKING:
    from ai_assistant.core.types import Authorization, FrozenJson

#: The instants every case here is arranged around, re-exported from the shipping
#: fakes so a suite and a consumer's own test cannot drift into two timelines.
AT = AUTHORIZATION_PROPOSED_AT
NOW = AUTHORIZATION_NOW
EXPIRES = AUTHORIZATION_EXPIRES_AT

#: The goal, the declaration and the account a row is established about, likewise.
GOAL = AUTHORIZATION_GOAL
TOOL: ToolDefinition = AUTHORIZATION_TOOL
ACCOUNT = AUTHORIZATION_ACCOUNT

#: A second goal. **The scope is never the conversation** (ADR-0254 §1), so the
#: boundary a case asks about is this value and not a second conversation.
OTHER_GOAL = "goal-0002"

#: A second connected account holding the **same identity**. ADR-0254 §3's
#: condition 4 compares both facts and never one, so this is what a case about it
#: varies (arm 13's second limb).
OTHER_ACCOUNT = BoundAccount(identity=ACCOUNT.identity, reference="conn-0002")

#: The origins a booking request reaches.
SITE = "https://camp.example/book"
OTHER_SITE = "https://other.example/book"

ENDPOINT = "test://endpoint/one"

#: A declaration whose ``parameters_schema`` **names** four of the arguments a
#: booking carries and admits the rest, and which declares ``stay_from`` at
#: ``PERIOD`` beside the canonical fake's own two bounded arguments (ADR-0266 §7).
#: ADR-0254 §4 lets a ruling's reason name a
#: key *"only where the declaration's ``parameters_schema`` itself names that key"*
#: — ADR-0145 §8's rule, on the ground that *"a key can be data"* — so both halves
#: of that rendering need a declaration that declares something and admits
#: something else.
DECLARED_TOOL: ToolDefinition = ToolDefinition.model_validate(
    {
        **AUTHORIZATION_TOOL.model_dump(),
        "parameters_schema": {
            "type": "object",
            "properties": {
                "site": {"type": "string"},
                "amount": {"type": "string"},
                "currency": {"type": "string"},
                "refundable_only": {"type": "boolean"},
                "stay_from": {"type": "string"},
            },
            "additionalProperties": True,
        },
        # **A third bounded argument, at the one kind ``site`` and ``amount`` leave
        # free** (ADR-0266 §7): a declaration declaring two arguments at one kind
        # meets **no** member of that kind, so the rendering arms that need a member
        # the request omits need a kind nothing else occupies.
        "bounded_arguments": (
            *AUTHORIZATION_TOOL.model_dump()["bounded_arguments"],
            {"argument": "stay_from", "kind": "period", "currency_argument": None},
        ),
    }
)

#: The account, origin and canonical form a search *at the configured provider* is
#: arranged around (ADR-0247 §1). The canonical form is what the HTTPS canonicaliser
#: answers for the origin — port made explicit — reproduced rather than imported,
#: because nothing here canonicalises: there is one canonicaliser and it is at the
#: seam.
SEARCH_ACCOUNT = BoundAccount(identity="Example Search", reference="conn-search")
SEARCH_ORIGIN = "https://search.example.com"
SEARCH_CANONICAL = "https://search.example.com:443"

#: The declaration a search is ruled over: :data:`TOOL`'s fields but for the id and
#: the capability, so route (c)'s eligibility is about the **binding** rather than
#: about a second declaration's severity.
SEARCH_TOOL: ToolDefinition = ToolDefinition.model_validate(
    {
        **AUTHORIZATION_TOOL.model_dump(),
        "id": "web_search",
        "capability": "web_search",
        # **``query`` is the one argument a search act bounds, and ``origin`` is the
        # system's** (ADR-0266 §7, ADR-0247 §1). A declaration declaring two
        # arguments at one kind meets **no** member of that kind, and a search
        # carries both keys — so one of them has to be the other thing §3 already
        # provides for. At the configured provider the origin comes from
        # ``Settings`` and ``orchestration`` fills it; the user never states it,
        # which is exactly what ``system_supplied`` names, and it is why *"a user is
        # never asked to approve"* it.
        "system_supplied": ("origin",),
        "bounded_arguments": ({"argument": "query", "kind": "terms", "currency_argument": None},),
    }
)


def search_member(canonical: str = SEARCH_CANONICAL) -> CanonicalDestination:
    """One destination member of the configured provider's own set."""
    return CanonicalDestination(protocol=DestinationProtocol.HTTPS, canonical=canonical)


def search_binding(
    *,
    account: BoundAccount = SEARCH_ACCOUNT,
    closed_loop: bool = True,
    external: bool = False,
    coverage: SpanCoverage = SpanCoverage.NOT_COVERED,
) -> EgressBinding:
    """A binding ADR-0247 §2's derived fact holds of, unless a case moves one value.

    Three conjuncts and no more: the binding carries ``closed_loop``, its
    ``account.reference`` equals the configured connection reference, and its
    canonical destination set equals the configured one. A case asking what happens
    *off* the configured provider moves one of them.
    """
    return EgressBinding(
        spans=(span(SEARCH_ORIGIN, argument="origin"),),
        account=account,
        transport_endpoint=ENDPOINT,
        planned_with_external_content=external,
        coverage=coverage,
        closed_loop=closed_loop,
    )


def member(canonical: str = SITE) -> CanonicalDestination:
    """One HTTPS destination member, in the canonical form a seam derives."""
    return CanonicalDestination(protocol=DestinationProtocol.HTTPS, canonical=canonical)


def account_member(account: BoundAccount = ACCOUNT) -> CanonicalDestination:
    """The **account member** a binding with no selected recipient derives.

    ADR-0148 §2's third clause: the canonical destination set is never empty, and a
    call selecting nothing reaches the connected account itself. That is the one
    request an empty ``coverage`` covers (ADR-0254 §1, arm 54).
    """
    return CanonicalDestination(account=account)


def span(supplied: str, index: int | None = None, *, argument: str = "site") -> EgressSpan:
    """One span selecting ``supplied`` under HTTPS's rules.

    ``index`` is ``None`` for the single-destination case, where the argument's own
    value is the string rather than a one-element array — which is the ordinary
    shape of a booking call and the one ADR-0254 §3's per-argument rule is easiest
    to read over.
    """
    return EgressSpan(
        argument=argument,
        index=index,
        provenance=DiscloserProvenance.SYSTEM_SELECTED,
        extent=len(supplied),
        destination=EgressDestination(
            protocol=DestinationProtocol.HTTPS,
            supplied=supplied,
            canonical=SEARCH_CANONICAL if supplied == SEARCH_ORIGIN else supplied,
        ),
    )


def binding(
    *supplied: str,
    account: BoundAccount = ACCOUNT,
    external: bool = False,
    closed_loop: bool = False,
    coverage: SpanCoverage = SpanCoverage.NOT_COVERED,
) -> EgressBinding:
    """A whole binding selecting ``supplied``.

    With **no** supplied recipient the derived canonical destination set is the
    connected account alone (ADR-0148 §2's third clause).

    ``external`` is ADR-0181 §5's fact and ``coverage`` is ADR-0233 §4's: route (d)
    discharges the first exactly where a row covers in full and relaxes the second
    for nothing, so a case varies them separately (ADR-0254 §6, arms 31 and 67).
    """
    spans = (
        (span(supplied[0]),)
        if len(supplied) == 1
        else tuple(span(value, index) for index, value in enumerate(supplied))
    )
    return EgressBinding(
        spans=spans,
        account=account,
        transport_endpoint=ENDPOINT,
        planned_with_external_content=external,
        coverage=coverage,
        closed_loop=closed_loop,
    )


def request(
    bound: EgressBinding,
    *,
    tool: ToolDefinition = TOOL,
    goal: str | None = GOAL,
    act: str | None = None,
    **parameters: FrozenJson,
) -> ActionRequest:
    """A request carrying ``bound``, its spans' arguments and ``parameters``.

    The destination-bearing arguments come from the binding's own spans, because
    ``ActionRequest`` refuses a binding that does not describe its arguments
    (ADR-0150 §4); everything else a case names is an ordinary argument the
    coverage comparison reads.

    ``goal`` defaults to :data:`GOAL` and is set to ``None`` by the case that asks
    what a request carrying none reaches (arm 9).

    ``act`` fills ``intended_action`` — the act this request is an attempt at, which
    is what selects the quote ADR-0266 §7's evidence route is taken against
    (ADR-0265 §1). It defaults to ``None``, which that route meets in no case, so a
    case about a quote has to say which act it is about.
    """
    listed: dict[str, list[str]] = {}
    single: dict[str, str] = {}
    for occurrence in bound.spans:
        if occurrence.destination is None:
            continue
        if occurrence.index is None:
            single[occurrence.argument] = occurrence.destination.supplied
        else:
            listed.setdefault(occurrence.argument, []).append(occurrence.destination.supplied)
    carried: dict[str, FrozenJson] = {**listed, **single, **parameters}
    described = EgressBinding(
        # Ordered by argument and then by index, absent first, which
        # ``EgressBinding`` refuses otherwise (ADR-0150 §4).
        spans=tuple(
            sorted(
                (
                    *bound.spans,
                    *(
                        EgressSpan(
                            argument=key,
                            provenance=DiscloserProvenance.SYSTEM_SELECTED,
                            extent=_extent(value),
                        )
                        for key, value in parameters.items()
                    ),
                ),
                key=lambda one: (one.argument, one.index if one.index is not None else -1),
            )
        ),
        account=bound.account,
        transport_endpoint=bound.transport_endpoint,
        planned_with_external_content=bound.planned_with_external_content,
        coverage=bound.coverage,
        closed_loop=bound.closed_loop,
    )
    return ActionRequest(
        tool=tool,
        parameters=carried,
        egress_binding=described,
        goal=goal,
        intended_action=act,
    )


def _extent(value: FrozenJson) -> int:
    """The code-point count ADR-0150 §4 fixes, for a span carrying no destination.

    A JSON string is counted directly; every other value in the canonical JSON
    encoding, which is the one ``parameters_digest`` is taken over — the same rule
    ``core`` applies, reproduced here because nothing outside ``core`` may import
    its private counter.
    """
    return len(value) if isinstance(value, str) else len(canonical_json_bytes(value).decode())


def route_d_decision(  # noqa: PLR0913 — one knob per field ADR-0254 §7's ten checks read
    row: Authorization,
    bound: EgressBinding,
    *,
    decision_id: str = "d-route-d",
    at: datetime = NOW,
    tool: ToolDefinition | None = None,
    authorised_by: str | None = None,
    authorised_subject: str | None = None,
    authorised_goal: str | None = None,
) -> PermissionDecision:
    """The decision a route-(d) ``ALLOW`` becomes, as a faulty policy could author it.

    Every field ADR-0254 §7's ten checks read is a knob, because each check is
    asserted **independently** (arm 29): the arm submits a row with every other
    check passing and the one under test failing, which is the only shape that
    proves the trail refuses on *that* check rather than on a neighbour.
    """
    return PermissionDecision(
        id=decision_id,
        ruling=PermissionRuling(
            outcome=PermissionOutcome.ALLOW,
            reason="the user's own recorded act for this goal covers this call",
            authorised_by=authorised_by if authorised_by is not None else row.id,
            authorised_subject=(
                authorised_subject if authorised_subject is not None else row.subject_digest
            ),
            authorised_goal=authorised_goal if authorised_goal is not None else row.goal,
        ),
        tool=tool if tool is not None else row.tool,
        parameters_digest="0" * 64,
        decided_at=at,
        egress_binding=bound,
    )


class MovableClock:
    """A clock a case sets, counting its readings.

    Two properties in one object because ADR-0254 §16 states two rules over the
    same seam and a suite needs both: liveness is evaluated against **the instant
    the query read**, and the one query that evaluates it reads the clock **exactly
    once**. A clock that only moved would leave the second untested, and one that
    only counted would leave every interval boundary racing the suite's own
    runtime.

    It **advances on every reading** once a case asks it to, which is what makes
    the single-read clause falsifiable rather than merely stated.
    """

    def __init__(self, at: datetime = NOW, *, step: timedelta = timedelta(0)) -> None:
        """Create a clock reading ``at``, advancing by ``step`` each reading."""
        self._at = at
        self._step = step
        self.readings = 0

    def __call__(self) -> datetime:
        """Return the current reading and count it."""
        reading = self._at
        self._at += self._step
        self.readings += 1
        return reading

    def set(self, at: datetime) -> None:
        """Move the clock to ``at``, leaving the reading count alone."""
        self._at = at

    def advance_by(self, step: timedelta = timedelta(days=1)) -> None:
        """Make every further reading move the clock on by ``step``.

        A **day** by default rather than a microsecond, so a per-row reading cannot
        be mistaken for a coarse clock: any row a second reading measured is far
        outside every interval this module's instants describe.
        """
        self._step = step

    def reset(self) -> MovableClock:
        """Return this clock to its starting reading, step and count.

        Returns:
            This clock, so a fixture can reset and hand it over in one expression.
        """
        self._at = NOW
        self._step = timedelta(0)
        self.readings = 0
        return self


#: The one clock every goal-authorization subject in these suites is built over.
#:
#: **A module-level object rather than a per-test one**, and the reason is
#: ``tests/core/test_protocol_triad.py``: that check proves a binding by
#: *evaluating* the subject fixture, and it can only evaluate one whose signature
#: is exactly ``self``. A subject fixture taking a ``clock`` fixture is a deliberate
#: false negative there, so the canonical fakes would go unbound and the triad rule
#: would report a gap that is not one. :meth:`MovableClock.reset` is what makes it
#: per-test — the suites reset it before every case, tests within a worker run one
#: at a time, and xdist workers are separate processes.
SHARED_CLOCK: Final = MovableClock()


__all__ = [
    "ACCOUNT",
    "AT",
    "DECLARED_TOOL",
    "ENDPOINT",
    "EXPIRES",
    "GOAL",
    "NOW",
    "OTHER_ACCOUNT",
    "OTHER_GOAL",
    "OTHER_SITE",
    "SEARCH_ACCOUNT",
    "SEARCH_CANONICAL",
    "SEARCH_ORIGIN",
    "SEARCH_TOOL",
    "SHARED_CLOCK",
    "SITE",
    "TOOL",
    "MovableClock",
    "account_member",
    "binding",
    "member",
    "request",
    "route_d_decision",
    "search_binding",
    "search_member",
    "span",
]
