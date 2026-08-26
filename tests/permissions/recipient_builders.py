"""Builders shared by the recipient-grant suites and the two enforcement points.

ADR-0193's record, the store that holds it, the policy that reads it and the
trail that validates it are four contracts stated over the same handful of
values: a transmitting :class:`ToolDefinition`, a :class:`BoundAccount`, an
:class:`EgressBinding` selecting some recipients, the :class:`ActionRequest`
wrapping it, and the :class:`PermissionDecision` a ruling becomes. Building those
in one place keeps the four arranging **identical** subjects, which matters most
for the fields whose equality coverage turns on — a grant covers nothing if its
declaration differs from the request's by a reworded description.

The grant records themselves come from :mod:`ai_assistant.testing.recipient_grants`,
which is the canonical builder a consumer outside these tests reaches for; this
module supplies only what is about a *call*, which the shipping fakes have no
business knowing how to build.

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
    OriginUnrecordedBinding,
    PermissionDecision,
    PermissionOutcome,
    PermissionRuling,
)
from ai_assistant.testing.recipient_grants import (
    RECIPIENT_GRANT_ACCOUNT,
    RECIPIENT_GRANT_DECIDED_AT,
    RECIPIENT_GRANT_EXPIRES_AT,
    RECIPIENT_GRANT_NOW,
    RECIPIENT_GRANT_TOOL,
)

if TYPE_CHECKING:
    from ai_assistant.core.types import ToolDefinition

#: The instants every case here is arranged around, re-exported from the shipping
#: fakes so a suite and a consumer's own test cannot drift into two timelines.
AT = RECIPIENT_GRANT_DECIDED_AT
NOW = RECIPIENT_GRANT_NOW
EXPIRES = RECIPIENT_GRANT_EXPIRES_AT

#: The declaration and the account a grant is established about, likewise.
TOOL: ToolDefinition = RECIPIENT_GRANT_TOOL
ACCOUNT = RECIPIENT_GRANT_ACCOUNT

#: A second connectable record holding the **same identity**. ``BoundAccount``'s
#: own declaration is why this exists: "two connectable records can hold one
#: identity, so an identity-only account compares equal across them and a standing
#: grant would cover a record the user never granted". Every account case below is
#: taken over this pair, so a store comparing identity alone fails rather than
#: passing on a fixture where the two differ in both fields.
OTHER_ACCOUNT = BoundAccount(identity=ACCOUNT.identity, reference="conn-0002")

ALICE = "alice@example.com"
BOB = "bob@example.com"

ENDPOINT = "test://endpoint/one"


def member(canonical: str) -> CanonicalDestination:
    """One selected-recipient member of a canonical destination set."""
    return CanonicalDestination(protocol=DestinationProtocol.SMTP, canonical=canonical)


def account_member(account: BoundAccount = ACCOUNT) -> CanonicalDestination:
    """The connected-account member — ADR-0148 §2's third clause."""
    return CanonicalDestination(account=account)


def span(supplied: str, index: int) -> EgressSpan:
    """One span selecting ``supplied``, canonicalised as ADR-0148 §2's SMTP rule does."""
    return EgressSpan(
        argument="to",
        index=index,
        provenance=DiscloserProvenance.SYSTEM_SELECTED,
        extent=len(supplied),
        destination=EgressDestination(
            protocol=DestinationProtocol.SMTP, supplied=supplied, canonical=supplied.lower()
        ),
    )


def binding(
    *supplied: str,
    account: BoundAccount = ACCOUNT,
    external: bool = False,
) -> EgressBinding:
    """A whole binding selecting ``supplied``.

    With **no** supplied recipient the derived canonical destination set is the
    connected account alone (ADR-0148 §2's third clause), which is the shape the
    account-member cases are about — never an empty set, because the derived set
    is never empty.
    """
    return EgressBinding(
        spans=tuple(span(value, index) for index, value in enumerate(supplied)),
        account=account,
        transport_endpoint=ENDPOINT,
        planned_with_external_content=external,
    )


def origin_unrecorded(*supplied: str, account: BoundAccount = ACCOUNT) -> OriginUnrecordedBinding:
    """The pre-ADR-0181 binding, over the members its twin above carries.

    Built directly, because ADR-0184 §4 leaves no producer that can make one: a
    request cannot carry the shape and ``from_request`` has no route to it. What a
    suite may do is what a **store decoding a row** does, which is this.
    """
    return OriginUnrecordedBinding(
        spans=tuple(span(value, index) for index, value in enumerate(supplied)),
        account=account,
        transport_endpoint=ENDPOINT,
    )


def request(
    bound: EgressBinding, *, tool: ToolDefinition = TOOL, **overrides: object
) -> ActionRequest:
    """A request carrying ``bound``, with parameters its spans describe."""
    to = [
        occurrence.destination.supplied
        for occurrence in bound.spans
        if occurrence.destination is not None
    ]
    fields: dict[str, object] = {
        "tool": tool,
        "parameters": {"to": to} if to else {},
        "egress_binding": bound,
    }
    fields.update(overrides)
    return ActionRequest(**fields)  # type: ignore[arg-type]  # heterogeneous test kwargs


def confirmation(
    bound: EgressBinding,
    *,
    decision_id: str = "d-confirm",
    at: datetime = AT,
    tool: ToolDefinition = TOOL,
) -> PermissionDecision:
    """A recorded ``CONFIRM`` about a call carrying ``bound``."""
    return PermissionDecision.from_request(
        request(bound, tool=tool),
        PermissionRuling(outcome=PermissionOutcome.CONFIRM, reason="it discloses off-device"),
        id=decision_id,
        decided_at=at,
    )


def answer(
    confirmed: PermissionDecision,
    *,
    decision_id: str = "d-answer",
    at: datetime | None = None,
) -> PermissionDecision:
    """The recorded resolving ``ALLOW`` that answers ``confirmed``."""
    return confirmed.model_copy(
        update={
            "id": decision_id,
            "ruling": PermissionRuling(
                outcome=PermissionOutcome.ALLOW,
                reason="the user approved the confirmation",
                authorised_by=confirmed.id,
            ),
            "decided_at": at if at is not None else confirmed.decided_at + timedelta(minutes=1),
            "resolves": confirmed.id,
        }
    )


def route_b_decision(  # noqa: PLR0913 — one knob per field a route-(b) case varies
    *,
    grant_id: str,
    subject: str | None,
    bound: EgressBinding | OriginUnrecordedBinding | None = None,
    decision_id: str = "d-route-b",
    at: datetime | None = None,
    tool: ToolDefinition = TOOL,
) -> PermissionDecision:
    """A **non-resolving** ``ALLOW`` resting on a standing authorisation.

    The shape ADR-0193 §6's invariant is scoped to: ``resolves`` unset,
    ``egress_binding`` present, ``authorised_by`` naming a grant, and
    ``authorised_subject`` carrying its digest. Built by substituting the binding
    afterwards where the case needs an arm no request can carry, which is the only
    route to an :class:`OriginUnrecordedBinding` at all.
    """
    carried = binding(ALICE) if bound is None else bound
    base = request(carried) if isinstance(carried, EgressBinding) else request(binding(ALICE))
    decision = PermissionDecision.from_request(
        base,
        PermissionRuling(
            outcome=PermissionOutcome.ALLOW,
            reason="a standing grant covers these recipients",
            authorised_by=grant_id,
            authorised_subject=subject,
        ),
        id=decision_id,
        decided_at=at if at is not None else NOW,
    )
    if isinstance(carried, EgressBinding):
        return decision
    return decision.model_copy(update={"egress_binding": carried})


class MovableClock:
    """A clock a case sets, counting its readings.

    Two properties in one object because the contract states two rules over the
    same seam and a suite needs both: liveness is evaluated against **the instant
    the query read**, and a query that evaluates it reads the clock **exactly
    once** (ADR-0193 §9). A clock that only moved would leave the second untested,
    and one that only counted would leave every interval boundary racing the
    suite's own runtime.

    It **advances on every reading** by default, which is what makes the
    single-read clause falsifiable rather than merely stated: a query reading per
    row would measure two records against two different instants, and the count
    below says so before any answer has to.
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

        A **day** by default rather than a microsecond, so a per-row reading
        cannot be mistaken for a coarse clock: any record a second reading
        measured is far outside every interval this module's instants describe,
        and the failure is unambiguous rather than a boundary argument.
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


#: The one clock every recipient-grant subject in these suites is built over.
#:
#: **A module-level object rather than a per-test one**, and the reason is
#: ``tests/core/test_protocol_triad.py``. That check proves a binding by
#: *evaluating* the subject fixture — "only running the fixture shows what the
#: conformance suite is actually handed" — and it can only evaluate one whose
#: signature is exactly ``self``. A subject fixture taking a ``clock`` fixture is a
#: deliberate false negative there, so the canonical fakes would go unbound and the
#: triad rule would report a gap that is not one.
#:
#: The alternative was to stop injecting a clock at all, which would have cost the
#: liveness interval and the single-read clause every case that pins them. So the
#: clock is shared and :meth:`MovableClock.reset` is what makes it per-test:
#: ``RecipientGrantsContract.clock`` resets it before every case, tests within a
#: worker run one at a time, and xdist workers are separate processes.
SHARED_CLOCK: Final = MovableClock()


__all__ = [
    "ACCOUNT",
    "ALICE",
    "AT",
    "BOB",
    "ENDPOINT",
    "EXPIRES",
    "NOW",
    "OTHER_ACCOUNT",
    "SHARED_CLOCK",
    "TOOL",
    "MovableClock",
    "account_member",
    "answer",
    "binding",
    "confirmation",
    "member",
    "origin_unrecorded",
    "request",
    "route_b_decision",
    "span",
]
