"""Canonical test doubles for the goal-authorization seam (ADR-0254 §16).

The shared fakes for :class:`~ai_assistant.core.protocols.GoalAuthorizations`,
:class:`~ai_assistant.core.protocols.AuthorizationResolution` and
:class:`~ai_assistant.core.protocols.GoalAuthorizationStore`, so a component that
consults the seam — an ``ActionPolicy`` for ADR-0254 §6's one ``live_for`` read,
an ``AuditTrail`` for §7's resolution read — can exercise every branch of its own
rule without a store on disk and without importing the permissions subsystem's
internals (``CLAUDE.md`` golden rule 1).

**Three fakes because the seam is three Protocols**, split by capability rather
than by taxonomy (ADR-0254 §16, on ADR-0097 §3's split and for its reason).
:class:`FakeGoalAuthorizations` is the policy's face and can write nothing and
resolve no id; :class:`FakeAuthorizationResolution` is the trail's face and
carries one member; :class:`FakeGoalAuthorizationStore` writes. The store fake
satisfies both narrow seams structurally, which is why the two narrow conformance
suites are bound against **it** as well as against their own fake — that turns
§16's *"three faces, one object"* from an assertion into a test.

**One history, three views.** All three answer from the same
:class:`_AuthorizationLog`, which applies every invariant
:meth:`~ai_assistant.core.protocols.GoalAuthorizationStore.record` and
:meth:`~ai_assistant.core.protocols.GoalAuthorizationStore.settle` apply. Two
hand-written copies of *"is this row live"* would be free to disagree, and the one
that disagreed would still pass its own suite — the failure ADR-0254 §16 guards
when it puts liveness in one member rather than in each caller.

**The invariants are written a second time here rather than imported**, and that
is the boundary's cost rather than an oversight: golden rule 1 forbids
``testing/`` importing ``permissions/``, and ``lint-imports`` fails the gate on
it. The **shared conformance suite** is what holds the two statements in step, and
it is bound against both the fakes and ``SqliteGoalAuthorizationStore`` for
exactly that reason.

**The clock is injected and read once, by the one member that evaluates
liveness** (§16). :meth:`FakeGoalAuthorizationStore.live_for` reads it exactly
once and measures every row it considers against that instant; ``resolve``,
``standing``, ``recent``, ``export``, ``record`` and ``settle`` read it not at
all. A test that drives a clock advancing on every read is what makes the
single-read clause falsifiable, so the constructor takes one.

**Not a fault injector.** Everything here conforms. A consumer that needs a store
which *breaks* the contract on purpose supplies its own stub; these must stay the
things a conforming implementation is compared against.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Final, final
from uuid import uuid4

from ai_assistant.core.clock import checked_clock
from ai_assistant.core.errors import AuthorizationError, InvalidAuthorizationError
from ai_assistant.core.types import (
    Authorization,
    AuthorizationBasis,
    AuthorizationDisposition,
    AuthorizationOrigin,
    AuthorizationSettlement,
    BoundAccount,
    BoundKind,
    CanonicalDestination,
    CostBasis,
    CoverageMember,
    DataTier,
    DestinationProtocol,
    Idempotency,
    ResolutionRule,
    Reversibility,
    RiskLevel,
    ToolCost,
    ToolDefinition,
    ValueBound,
    ValueResolution,
    describe_untrusted,
)
from ai_assistant.testing._detachment import field_state
from ai_assistant.testing.cancellation import SuspendableResource

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from ai_assistant.core.types import FrozenJsonValue
    from ai_assistant.testing.cancellation import LoopSuspension, ResourceLog

#: When a scripted row is proposed. Fixed, so ordering assertions are about the
#: values under test rather than about how fast a suite runs.
#:
#: **Prefixed rather than named ``DEFAULT_…``**, and every constant and builder here
#: is: ``ai_assistant.testing`` already re-exports two grant seams' defaults, and a
#: third claiming the bare names would either shadow one at the package surface or
#: force a consumer to remember which import won.
AUTHORIZATION_PROPOSED_AT: Final = datetime(2026, 9, 13, 9, 0, tzinfo=UTC)

#: When a scripted row stops being live. **Twelve hours** after
#: :data:`AUTHORIZATION_PROPOSED_AT`: far enough that :data:`AUTHORIZATION_NOW` sits
#: comfortably inside the interval and a test about expiry has to say so, and short
#: enough to read as the *"measured in hours"* horizon ADR-0254 §6 contrasts a
#: recipient grant's with.
AUTHORIZATION_EXPIRES_AT: Final = AUTHORIZATION_PROPOSED_AT + timedelta(hours=12)

#: What the fakes' default clock reads: inside every default row's interval, so a
#: test that does not mention liveness gets a live row, and a test that is about
#: liveness moves this rather than the record.
AUTHORIZATION_NOW: Final = AUTHORIZATION_PROPOSED_AT + timedelta(hours=1)

#: The goal a scripted row is about unless a test names another. **The scope is
#: never the conversation** (ADR-0254 §1), so a second goal is the way a test asks
#: about the boundary.
AUTHORIZATION_GOAL: Final = "goal-0001"

#: The declaration a scripted row is about unless a test names another.
#:
#: **It discloses**, because ADR-0148 §8's second clause makes a non-empty
#: ``discloses`` true of every tool registered at the egress seam — so a row over a
#: non-disclosing declaration would authorise calls that never needed one, and a
#: policy test built on it would prove nothing about the floor route (d) exists to
#: relieve.
#:
#: **And it trips nothing else**: ``LOW`` risk, ``REVERSIBLE``, at a known cost.
#: Deliberate, and the opposite of realistic, for :data:`~ai_assistant.testing.
#: recipient_grants.RECIPIENT_GRANT_TOOL`'s stated reason — an authorization
#: discharges the **disclosure** ground and nothing else (ADR-0254 §3), so a base
#: declaration that tripped another floor would leave a policy case unable to tell
#: *"the row was consulted and used"* from *"the row was never reached"*.
#:
#: **It classifies nothing system-supplied**, so ADR-0254 §3's condition 6 reads
#: exactly as it would without the classification and every argument is
#: user-facing. A case about that field raises it on a copy of this.
AUTHORIZATION_TOOL: Final = ToolDefinition(
    id="book_site",
    capability="book_site",
    description="Book a pitch at a campsite through the connected account.",
    risk_level=RiskLevel.LOW,
    reversibility=Reversibility.REVERSIBLE,
    side_effecting=True,
    reads=(),
    writes=(),
    discloses=(DataTier.PERSONAL,),
    cost=ToolCost(basis=CostBasis.FREE),
    idempotency=Idempotency.NONE,
)

#: The connected account a scripted row is established against. Two facts, as
#: :class:`~ai_assistant.core.types.BoundAccount` requires: an identity the user
#: recognises and the connection record's reference, which is what stops a row
#: covering a second connectable record holding the same identity (ADR-0254 §3).
AUTHORIZATION_ACCOUNT: Final = BoundAccount(identity="work@example.com", reference="conn-0001")

#: The canonical destination a scripted row names unless a test names another.
AUTHORIZATION_DESTINATION: Final = CanonicalDestination(
    protocol=DestinationProtocol.HTTPS, canonical="https://camp.example/book"
)

#: The recorded turn a scripted basis rests on unless a test names another.
AUTHORIZATION_ACT: Final = "turn-0001"


def _mint(prefix: str) -> str:
    """A unique id for a scripted record, so two builder calls never collide."""
    return f"{prefix}-{uuid4().hex[:12]}"


def authorization_basis(
    *,
    act: str = AUTHORIZATION_ACT,
    span: str = "up to fifty pounds",
    resolution: ValueResolution | None = None,
) -> AuthorizationBasis:
    """One :class:`~ai_assistant.core.types.AuthorizationBasis` (ADR-0254 §8).

    Args:
        act: The recorded turn this member rests on.
        span: The user's own words inside that turn's stored utterance.
        resolution: How the span became the value; ``AS_STATED`` by default, which
            is the resolution that normalises by nothing.

    Returns:
        The basis.
    """
    return AuthorizationBasis(
        act=act,
        span=span,
        resolution=resolution
        if resolution is not None
        else ValueResolution(rule=ResolutionRule.AS_STATED),
    )


def money_bound(
    maximum: str | Decimal = "60",
    *,
    currency: str = "GBP",
    currency_argument: str = "currency",
    minimum: str | Decimal | None = None,
) -> ValueBound:
    """A ``MONEY`` :class:`~ai_assistant.core.types.ValueBound` (ADR-0254 §2).

    Args:
        maximum: The greatest amount the bound permits.
        currency: The ISO-4217 code the amount is denominated in.
        currency_argument: The key of ``parameters`` carrying that currency —
            **the whole of the association**, which no schema supplies.
        minimum: The least amount, where the act stated one.

    Returns:
        The bound.
    """
    return ValueBound(
        kind=BoundKind.MONEY,
        currency=currency,
        currency_argument=currency_argument,
        maximum=Decimal(maximum),
        minimum=None if minimum is None else Decimal(minimum),
    )


def period_bound(
    *,
    starts_at: datetime = AUTHORIZATION_PROPOSED_AT,
    ends_at: datetime = AUTHORIZATION_EXPIRES_AT,
    timezone: str = "Europe/London",
) -> ValueBound:
    """A ``PERIOD`` bound over the half-open interval ``[starts_at, ends_at)``.

    Args:
        starts_at: The inclusive start.
        ends_at: The exclusive end, strictly after ``starts_at``.
        timezone: The IANA zone a **calendar date** argument is read in.

    Returns:
        The bound.
    """
    return ValueBound(
        kind=BoundKind.PERIOD, starts_at=starts_at, ends_at=ends_at, timezone=timezone
    )


def terms_bound(*terms: str) -> ValueBound:
    """A ``TERMS`` bound over the set the user named, in their order.

    Args:
        terms: The permitted terms, non-empty and duplicate-free.

    Returns:
        The bound.
    """
    return ValueBound(kind=BoundKind.TERMS, terms=terms)


def coverage_member(
    argument: str,
    *,
    fixed: FrozenJsonValue | None = None,
    bound: ValueBound | None = None,
    basis: AuthorizationBasis | None = None,
) -> CoverageMember:
    """One :class:`~ai_assistant.core.types.CoverageMember` (ADR-0254 §2).

    Args:
        argument: The key of ``parameters`` this member is about, at depth one.
        fixed: The value the act fixed, where it fixed one.
        bound: The range the act stated, where it stated one.
        basis: The act, span and resolution behind it; a default basis otherwise.

    Returns:
        The member. Exactly one of ``fixed`` and ``bound`` is given, which the
        model itself refuses otherwise.
    """
    return CoverageMember(
        argument=argument,
        fixed=fixed,
        bound=bound,
        basis=basis if basis is not None else authorization_basis(),
    )


def authorization(  # noqa: PLR0913 — one knob per Authorization field a suite varies
    *,
    id: str | None = None,  # noqa: A002 — names the field it fills
    goal: str = AUTHORIZATION_GOAL,
    tool: ToolDefinition = AUTHORIZATION_TOOL,
    account: BoundAccount = AUTHORIZATION_ACCOUNT,
    destinations: Sequence[CanonicalDestination] = (AUTHORIZATION_DESTINATION,),
    origin: AuthorizationOrigin = AuthorizationOrigin.CONFIRMED,
    coverage: Sequence[CoverageMember] | None = None,
    proposed_at: datetime = AUTHORIZATION_PROPOSED_AT,
    expires_at: datetime = AUTHORIZATION_EXPIRES_AT,
    confirmation: str | None = "confirm-0001",
    supersedes: str | None = None,
    disposition: AuthorizationDisposition = AuthorizationDisposition.PROPOSED,
    settled_at: datetime | None = None,
) -> Authorization:
    """A scripted :class:`~ai_assistant.core.types.Authorization` (ADR-0254 §1).

    The default is a **path-(i) proposal**: a row named by a ``CONFIRM``, written
    ``PROPOSED``, bounding ``amount`` at GBP 60 — the record ADR-0254's own worked
    case is about. A test asking about an opening act passes ``confirmation=None``,
    ``origin=AuthorizationOrigin.OPENING_ACT`` and an ``ESTABLISHED`` disposition;
    one asking about a correction passes ``supersedes`` beside those.

    Args:
        id: The row's own id; a fresh one otherwise, so two builder calls never
            collide on a store's write-once rule.
        goal: The goal whose calls this authority is about.
        tool: The declaration it was established about, by value.
        account: The connected account it was established against.
        destinations: The canonical destination set it names.
        origin: How the authority came into being.
        coverage: What the act fixed or bounded; one ``MONEY`` member over
            ``amount`` otherwise.
        proposed_at: When the row was written.
        expires_at: When the authority ceases to be live.
        confirmation: The recorded ``CONFIRM`` the question rode, on path (i).
        supersedes: The row this one replaces, where it replaces one.
        disposition: Where the row stands.
        settled_at: When it was last settled; supplied automatically for a row
            written already ``ESTABLISHED`` with no confirmation, which is what
            paths (ii) and (iii) require and what a caller most often forgets.

    Returns:
        The row.
    """
    if settled_at is None and disposition is not AuthorizationDisposition.PROPOSED:
        settled_at = proposed_at
    return Authorization(
        id=id if id is not None else _mint("auth"),
        goal=goal,
        tool=tool,
        account=account,
        destinations=tuple(destinations),
        origin=origin,
        coverage=tuple(coverage)
        if coverage is not None
        else (coverage_member("amount", bound=money_bound()),),
        proposed_at=proposed_at,
        expires_at=expires_at,
        confirmation=confirmation,
        supersedes=supersedes,
        disposition=disposition,
        settled_at=settled_at,
    )


def opening_act(  # noqa: PLR0913 — the knobs a path-(iii) case varies, and no fewer
    *,
    id: str | None = None,  # noqa: A002 — names the field it fills
    goal: str = AUTHORIZATION_GOAL,
    tool: ToolDefinition = AUTHORIZATION_TOOL,
    account: BoundAccount = AUTHORIZATION_ACCOUNT,
    destinations: Sequence[CanonicalDestination] = (AUTHORIZATION_DESTINATION,),
    coverage: Sequence[CoverageMember] | None = None,
    proposed_at: datetime = AUTHORIZATION_PROPOSED_AT,
    expires_at: datetime = AUTHORIZATION_EXPIRES_AT,
) -> Authorization:
    """A scripted **path-(iii)** row: an act that opened an authority with no question.

    ``confirmation`` and ``supersedes`` both unset, ``origin`` ``OPENING_ACT``,
    written ``ESTABLISHED`` with ``settled_at`` equal to ``proposed_at`` — and a
    **non-empty** coverage, which the model itself requires of a row carrying
    neither pointer, because *"an opening act that fixed nothing is not an act of
    the user"*.

    Such a row **supplies no recipient authority** (ADR-0254 §1), so route (d) over
    it re-takes the grant seam at every dispatch and withdrawing the grant ends the
    authority at the next one. A test about that is what this builder is for.

    Args:
        id: The row's own id; a fresh one otherwise.
        goal: The goal whose calls this authority is about.
        tool: The declaration it was opened about.
        account: The connected account it names.
        destinations: The canonical destination set it names.
        coverage: What the act bounded; one ``MONEY`` member over ``amount``
            otherwise.
        proposed_at: The recorded turn's instant, which is also ``settled_at``.
        expires_at: When the authority ceases to be live.

    Returns:
        The row.
    """
    return authorization(
        id=id,
        goal=goal,
        tool=tool,
        account=account,
        destinations=destinations,
        origin=AuthorizationOrigin.OPENING_ACT,
        coverage=coverage,
        proposed_at=proposed_at,
        expires_at=expires_at,
        confirmation=None,
        supersedes=None,
        disposition=AuthorizationDisposition.ESTABLISHED,
    )


def _named(given: object) -> str:
    """Name ``given`` for a refusal message, without reading an attribute of it.

    :func:`~ai_assistant.permissions.goal_authorizations._named`'s discipline,
    shared by copy across the boundary golden rule 1 draws: the value reaching the
    log is whatever the caller passed, and a record whose ``__dict__`` is missing a
    field has no ``id`` attribute at all.
    """
    try:
        if isinstance(given, Authorization):
            for key, value in object.__getattribute__(given, "__dict__").items():
                if type(key) is str and key == "id":
                    return describe_untrusted(value)
    except Exception:  # the value cannot even be named; say so and carry on
        return "the given value"
    return "the given value"


#: ADR-0254 §1's transition graph, whole and as data — the same five edges
#: ``SqliteGoalAuthorizationStore`` states, written a second time because
#: ``testing/`` may not import ``permissions/`` (golden rule 1). The conformance
#: suite is what holds the two in step.
_EDGES: Final[dict[AuthorizationDisposition, frozenset[AuthorizationDisposition]]] = {
    AuthorizationDisposition.PROPOSED: frozenset(
        {
            AuthorizationDisposition.ESTABLISHED,
            AuthorizationDisposition.DECLINED,
            AuthorizationDisposition.EXPIRED,
        }
    ),
    AuthorizationDisposition.ESTABLISHED: frozenset(
        {AuthorizationDisposition.REVOKED, AuthorizationDisposition.SUPERSEDED}
    ),
}


def _narrows(  # noqa: PLR0911 — one return per refusal, and each names a different widening
    later: ValueBound, earlier: ValueBound
) -> bool:
    """Whether ``later`` permits no value ``earlier`` does not (ADR-0254 §1, §9).

    The non-widening test, per kind, and it is a **subset** question: equality
    narrows vacuously and is admitted. A change of ``kind``, of ``currency``, of
    ``currency_argument`` or of a ``PERIOD``'s ``timezone`` re-denominates what the
    bound is *about* rather than shrinking what it permits, so each takes path (i).
    """
    if later.kind is not earlier.kind:
        return False
    if later.kind is BoundKind.MONEY:
        if (later.currency, later.currency_argument) != (
            earlier.currency,
            earlier.currency_argument,
        ):
            return False
        if later.maximum is None or earlier.maximum is None or later.maximum > earlier.maximum:
            return False
        if earlier.minimum is None:
            return True
        return later.minimum is not None and later.minimum >= earlier.minimum
    if later.kind is BoundKind.PERIOD:
        if later.timezone != earlier.timezone:
            return False
        interval = (later.starts_at, later.ends_at, earlier.starts_at, earlier.ends_at)
        if any(instant is None for instant in interval):
            return False
        starts, ends, was_starts, was_ends = (
            instant for instant in interval if instant is not None
        )
        return starts >= was_starts and ends <= was_ends
    if later.terms is None or earlier.terms is None:
        return False
    return set(later.terms) <= set(earlier.terms)


def _member_defect(later: CoverageMember, earlier: CoverageMember | None) -> str | None:
    """Why ``later`` is not a permitted correction of ``earlier`` — or ``None``.

    ADR-0254 §1's *"what path (ii) may change, and what it may never touch"*, per
    argument, with §9 clause (ii)'s principle as the whole of the reason. See
    :func:`~ai_assistant.permissions.goal_authorizations._member_defect`, whose
    arms these are.
    """
    key = later.argument
    if earlier is None:
        return (
            f"a correction may not add a coverage member for {key!r}, which the row it "
            f"supersedes names in no member"
        )
    if later == earlier:
        return None
    if (later.bound is None) is not (earlier.bound is None):
        return (
            f"a correction may replace a fixed value the superseded row fixed, or narrow a "
            f"bound it bounded; for {key!r} it does neither"
        )
    if (
        later.bound is not None
        and earlier.bound is not None
        and not _narrows(later.bound, earlier.bound)
    ):
        return f"a correction may only narrow a bound; for {key!r} it widens or re-denominates one"
    return None


@final
class _AuthorizationLog:
    """The history all three fakes answer from (ADR-0254 §1, §16).

    Shared rather than written three times, because the three faces must agree
    about liveness to the letter: the store fake's ``record`` and ``settle`` are
    what a test uses to arrange a state, and each narrow fake has to *be* in that
    same state for a shared suite to mean the same thing against all of them.

    Not a Protocol implementation and not exported: the fakes are.
    """

    def __init__(self) -> None:
        """Create an empty history."""
        self._records: list[Authorization] = []

    # --- writes -----------------------------------------------------------

    def append(self, row: Authorization) -> str:
        """Validate ``row`` against every ADR-0254 §1 invariant and append a snapshot.

        The snapshot is taken by **revalidating** rather than by copying, and from
        the instance's field state rather than from ``model_dump()``, for
        ``SqliteGoalAuthorizationStore._revalidated``'s reason: ``model_dump`` is an
        ordinary overridable method, so a subclass could return a mapping that does
        not describe itself — a row bounding sixty pounds whose dump names eight
        hundred — and the log would then hold an authority the user never gave.

        **Every check and the append are one operation**, with no ``await`` between
        them, which is where the atomicity ADR-0254 §16 requires is obtained.

        Raises:
            InvalidAuthorizationError: On any ground ``record`` names.
        """
        snapshot = self._revalidated(row)
        if any(held.id == snapshot.id for held in self._records):
            msg = (
                f"authorization {snapshot.id!r} is already recorded; the store is "
                f"write-once, so history cannot be rewritten by replaying a write"
            )
            raise InvalidAuthorizationError(msg)
        self._check_write_path(snapshot)
        superseded = self._check_supersedes(snapshot)
        self._check_uniqueness(snapshot, retiring=superseded)
        self._records.append(snapshot)
        if superseded is not None and snapshot.confirmation is None:
            # **Path (ii) alone**: a path-(i) proposal's ``supersedes`` states what
            # *approving* it would replace, and that retirement lands in the same
            # write as the ``ESTABLISHED`` settlement rather than in the proposal.
            self._write_settlement(
                superseded,
                to=AuthorizationDisposition.SUPERSEDED,
                settled_at=snapshot.proposed_at,
            )
        return snapshot.id

    @staticmethod
    def _revalidated(row: Authorization) -> Authorization:
        """A detached, validated snapshot, refusing what the model refuses.

        Raises:
            InvalidAuthorizationError: If the record does not satisfy its own model
                or carries state :class:`Authorization` declares no field for.
        """
        try:
            return Authorization.model_validate(field_state(Authorization, row))
        except ValueError as exc:
            msg = f"authorization {_named(row)} is not a valid record: {describe_untrusted(exc)}"
            raise InvalidAuthorizationError(msg) from exc

    @staticmethod
    def _check_write_path(row: Authorization) -> None:
        """Refuse a row written in a disposition its path does not admit (§1, §16).

        Raises:
            InvalidAuthorizationError: If a row carrying ``confirmation`` is written
                in any disposition but ``PROPOSED``, or one carrying it unset in any
                disposition but ``ESTABLISHED`` or with ``settled_at`` unequal to
                ``proposed_at``.
        """
        if row.confirmation is not None:
            if row.disposition is not AuthorizationDisposition.PROPOSED:
                msg = (
                    f"authorization {row.id!r} names a confirmation, so it is written "
                    f"PROPOSED and reaches every later disposition through settle alone; "
                    f"it was written {row.disposition} (ADR-0254 §1)"
                )
                raise InvalidAuthorizationError(msg)
            return
        if row.disposition is not AuthorizationDisposition.ESTABLISHED:
            msg = (
                f"authorization {row.id!r} names no confirmation, so it records an act "
                f"that needed no question and is written ESTABLISHED; it was written "
                f"{row.disposition} (ADR-0254 §1)"
            )
            raise InvalidAuthorizationError(msg)
        if row.settled_at != row.proposed_at:
            msg = (
                f"authorization {row.id!r} records an act that needed no question, so its "
                f"settled_at is its proposed_at (ADR-0254 §1)"
            )
            raise InvalidAuthorizationError(msg)

    def _check_supersedes(self, row: Authorization) -> Authorization | None:
        """Resolve ``supersedes`` and hold a correction to what it may change.

        Raises:
            InvalidAuthorizationError: If ``supersedes`` resolves to no
                ``ESTABLISHED`` row of that goal and declaration id, or if a
                path-(ii) correction alters a transcribed field, adds, drops or
                widens a member, or moves ``expires_at`` other than by ADR-0256 §5's
                one narrowing.
        """
        named = row.supersedes
        if named is None:
            return None
        earlier = next((held for held in self._records if held.id == named), None)
        if (
            earlier is None
            or earlier.disposition is not AuthorizationDisposition.ESTABLISHED
            or earlier.goal != row.goal
            or earlier.tool.id != row.tool.id
        ):
            msg = (
                f"authorization {row.id!r} supersedes {named!r}, which is not an "
                f"ESTABLISHED row of goal {row.goal!r} through declaration "
                f"{row.tool.id!r} (ADR-0254 §1, §16)"
            )
            raise InvalidAuthorizationError(msg)
        if row.confirmation is None:
            self._check_correction(row, earlier)
        return earlier

    @staticmethod
    def _check_correction(row: Authorization, earlier: Authorization) -> None:
        """Hold a path-(ii) correction to what ADR-0254 §1 lets it change.

        **A path-(i) proposal carrying ``supersedes`` is subject to none of this**
        (ADR-0256 §9): it may set ``expires_at`` to a **later** instant than the row
        it names, which is what renews an authority whose expiry has passed.

        Raises:
            InvalidAuthorizationError: If a transcribed field moved, if the coverage
                added, dropped or widened a member, or if ``expires_at`` moved other
                than by ADR-0256 §5's one narrowing.
        """
        for name in ("goal", "tool", "account", "destinations", "origin"):
            if getattr(row, name) != getattr(earlier, name):
                msg = (
                    f"authorization {row.id!r} corrects {earlier.id!r} and alters its "
                    f"{name}; a correction transcribes goal, tool, account, destinations "
                    f"and origin unchanged (ADR-0254 §1)"
                )
                raise InvalidAuthorizationError(msg)
        if row.expires_at != earlier.expires_at and not (
            row.proposed_at < row.expires_at < earlier.expires_at
        ):
            msg = (
                f"authorization {row.id!r} corrects {earlier.id!r} and moves its "
                f"expires_at; a correction may carry only an instant strictly after its "
                f"own proposed_at and strictly before the superseded row's (ADR-0256 §5)"
            )
            raise InvalidAuthorizationError(msg)
        held = {member.argument: member for member in earlier.coverage}
        for member in row.coverage:
            defect = _member_defect(member, held.get(member.argument))
            if defect is not None:
                msg = (
                    f"authorization {row.id!r} corrects {earlier.id!r}: {defect} (ADR-0254 §1, §9)"
                )
                raise InvalidAuthorizationError(msg)
        dropped = sorted(held.keys() - {member.argument for member in row.coverage})
        if dropped:
            msg = (
                f"authorization {row.id!r} corrects {earlier.id!r} and drops its member "
                f"for {', '.join(repr(key) for key in dropped)}; every member the "
                f"correction does not replace is carried forward byte for byte, with its "
                f"own basis (ADR-0254 §1, §5)"
            )
            raise InvalidAuthorizationError(msg)

    def _check_uniqueness(self, row: Authorization, *, retiring: Authorization | None) -> None:
        """Refuse a write leaving two ``ESTABLISHED`` rows of one pair (ADR-0254 §1).

        Raises:
            InvalidAuthorizationError: If one would survive beside this row.
        """
        if row.disposition is not AuthorizationDisposition.ESTABLISHED:
            return
        surviving = self._established_ids(row.goal, row.tool.id) - {
            retired.id for retired in (retiring,) if retired is not None
        }
        if surviving:
            msg = (
                f"authorization {row.id!r} would be the second ESTABLISHED row of goal "
                f"{row.goal!r} through declaration {row.tool.id!r}, beside "
                f"{', '.join(repr(held) for held in sorted(surviving))}; at most one "
                f"stands per pair (ADR-0254 §1)"
            )
            raise InvalidAuthorizationError(msg)

    def _established_ids(self, goal: str, tool_id: str) -> set[str]:
        """The ids of every ``ESTABLISHED`` row of that goal and declaration id."""
        return {
            held.id
            for held in self._records
            if held.goal == goal
            and held.tool.id == tool_id
            and held.disposition is AuthorizationDisposition.ESTABLISHED
        }

    def settle(
        self, authorization_id: str, to: AuthorizationDisposition, settled_at: datetime
    ) -> AuthorizationSettlement:
        """Move one row along one of ADR-0254 §1's five edges, or say why not.

        The read, the comparisons and the writes happen with no ``await`` between
        them, which is the indivisible step ADR-0254 §16 requires: two racing
        settlements of one row cannot both win, because the second finds a
        disposition the edge does not leave.
        """
        held = next((one for one in self._records if one.id == authorization_id), None)
        if held is None:
            return AuthorizationSettlement.NO_SUCH_AUTHORIZATION
        if to not in _EDGES.get(held.disposition, frozenset()):
            return AuthorizationSettlement.NOT_AT_SOURCE
        if to is not AuthorizationDisposition.ESTABLISHED:
            self._write_settlement(held, to=to, settled_at=settled_at)
            return AuthorizationSettlement.SETTLED
        return self._establish(held, settled_at=settled_at)

    def _establish(self, held: Authorization, *, settled_at: datetime) -> AuthorizationSettlement:
        """Take §1's conditional supersession and its uniqueness check in one step.

        **The supersession is conditional on the named row still standing
        ``ESTABLISHED``, read at the instant of the settlement** (ADR-0254 §1):
        where it has already left, this row is established all the same and the
        named row is **not written to at all**, staying in whatever retired
        disposition it reached. The uniqueness check is then taken over what would
        remain after that supersession, so a *third* established row of the pair
        answers ``WOULD_DUPLICATE`` with nothing written.
        """
        retiring: Authorization | None = None
        if held.supersedes is not None:
            candidate = next((one for one in self._records if one.id == held.supersedes), None)
            if (
                candidate is not None
                and candidate.disposition is AuthorizationDisposition.ESTABLISHED
            ):
                retiring = candidate
        surviving = self._established_ids(held.goal, held.tool.id) - {
            retired.id for retired in (retiring,) if retired is not None
        }
        if surviving:
            return AuthorizationSettlement.WOULD_DUPLICATE
        self._write_settlement(held, to=AuthorizationDisposition.ESTABLISHED, settled_at=settled_at)
        if retiring is not None:
            self._write_settlement(
                retiring, to=AuthorizationDisposition.SUPERSEDED, settled_at=settled_at
            )
        return AuthorizationSettlement.SETTLED

    def _write_settlement(
        self, row: Authorization, *, to: AuthorizationDisposition, settled_at: datetime
    ) -> None:
        """Rewrite one row's disposition and its instant, and nothing else.

        **Through the record's own model**, so a settled row carrying no
        ``settled_at`` is refused here as it would be on the way back out.
        """
        settled = Authorization.model_validate(
            {**row.model_dump(), "disposition": to, "settled_at": settled_at}
        )
        self._records[self._records.index(row)] = settled

    # --- reads ------------------------------------------------------------

    def live_for(self, goal: str, tool_id: str, reading: datetime) -> Authorization | None:
        """The live row of that pair, settling the lapsed proposals it read.

        The integrity check is taken **before** the settlements, so a log holding
        two live rows of one pair is left exactly as it was found.

        Raises:
            AuthorizationError: If more than one live row of that pair would answer.
        """
        rows = [one for one in self._records if one.goal == goal and one.tool.id == tool_id]
        live = [one for one in rows if _is_live(one, reading)]
        if len(live) > 1:
            msg = (
                f"the authorization store holds {len(live)} live rows for goal {goal!r} "
                f"through declaration {tool_id!r} ({', '.join(repr(one.id) for one in live)}); "
                f"at most one stands per pair (ADR-0254 §1, §5)"
            )
            raise AuthorizationError(msg)
        for one in rows:
            if one.disposition is AuthorizationDisposition.PROPOSED and one.expires_at <= reading:
                self._write_settlement(one, to=AuthorizationDisposition.EXPIRED, settled_at=reading)
        return _detached(live[0]) if live else None

    def resolve(self, authorization_id: str) -> Authorization | None:
        """The row with that id, whatever its disposition, or ``None``, detached."""
        found = next((one for one in self._records if one.id == authorization_id), None)
        return None if found is None else _detached(found)

    def standing(self, goal: str) -> tuple[Authorization, ...]:
        """Every ``ESTABLISHED`` row of ``goal``, live and lapsed, newest first."""
        return tuple(
            one
            for one in self.ordered()
            if one.goal == goal and one.disposition is AuthorizationDisposition.ESTABLISHED
        )

    def ordered(self, limit: int | None = None) -> tuple[Authorization, ...]:
        """Every row, newest first by ``proposed_at``, ties broken by ``id`` ascending."""
        ranked = sorted(self._records, key=lambda one: (-_epoch_us(one.proposed_at), one.id))
        return tuple(_detached(one) for one in (ranked if limit is None else ranked[:limit]))

    def clear(self) -> int:
        """Delete every row, returning the number removed."""
        removed = len(self._records)
        self._records.clear()
        return removed


_EPOCH: Final = datetime(1970, 1, 1, tzinfo=UTC)


def _epoch_us(instant: datetime) -> int:
    """``instant`` as whole microseconds since the epoch, exactly.

    An **integer**, computed from a ``timedelta``'s integer components: a float
    epoch second carrying microsecond precision needs sixteen significant digits at
    present-day values, right at the edge of a double, so two rows a microsecond
    apart could compare equal or invert under the ordering ``recent`` contracts.
    """
    elapsed = instant - _EPOCH
    return (elapsed.days * 86_400 + elapsed.seconds) * 1_000_000 + elapsed.microseconds


def _detached(row: Authorization) -> Authorization:
    """A snapshot no caller shares with the log (ADR-0097 §3).

    ``frozen=True`` refuses ``row.expires_at = …`` and does **not** refuse
    ``row.__dict__["expires_at"] = …``, so a caller rewriting the answer would
    otherwise widen what the user authorised — **through the gate's own answer**.
    ``deep=True`` because the members beneath the root carry the bounds the
    comparison reads, and a shallow copy still shares every one of them.
    """
    return row.model_copy(deep=True)


def _is_live(row: Authorization, reading: datetime) -> bool:
    """Whether ``row`` is live at ``reading`` (ADR-0254 §1).

    ``ESTABLISHED``, and the reading **at or after** ``settled_at`` and **strictly
    before** ``expires_at``. The lower end is stated because the clock can move
    backwards, and a row called live whose ``settled_at`` is after a ruling's
    ``decided_at`` is one ADR-0254 §7's trail refuses as backdated.
    """
    if row.disposition is not AuthorizationDisposition.ESTABLISHED:
        return False
    settled_at = row.settled_at
    if settled_at is None:  # pragma: no cover — the model pairs the two
        return False
    return settled_at <= reading < row.expires_at


@final
class FakeGoalAuthorizations:
    """A non-persistent ``GoalAuthorizations`` test double (ADR-0254 §16).

    The **policy's** face: one member, and no way to write a row or to resolve an
    id. A policy handed this cannot name ``record``, which is the static guarantee
    ADR-0097 §3's split buys and which ``mypy --strict`` is what enforces.
    """

    def __init__(
        self,
        records: Sequence[Authorization] = (),
        *,
        now: Callable[[], datetime] = lambda: AUTHORIZATION_NOW,
    ) -> None:
        """Create the seam.

        Args:
            records: The history it starts with, applied in order under the same
                invariants ``record`` applies.
            now: The clock :meth:`live_for` evaluates liveness against, read
                **once** per call.

        Raises:
            InvalidAuthorizationError: If ``records`` is not a history a conforming
                store could hold.
        """
        self._log = _AuthorizationLog()
        self._clock = checked_clock(now, owner="FakeGoalAuthorizations")
        self._resource = SuspendableResource()
        self._failure: Exception | None = None
        self._calls = 0
        for record in records:
            self._log.append(record)

    @property
    def call_count(self) -> int:
        """How many times :meth:`live_for` has been called.

        ADR-0254 §6's *"at most once per ruling"* is a rule about the policy, and a
        seam that cannot be counted cannot falsify it.
        """
        return self._calls

    def hold(self, *records: Authorization) -> None:
        """Add rows to the history after construction, under the same invariants.

        Args:
            records: The rows to append, in order.

        Raises:
            InvalidAuthorizationError: If a row is not one a conforming store would
                admit at that point in the history.
        """
        for record in records:
            self._log.append(record)

    def settle(
        self, authorization_id: str, *, to: AuthorizationDisposition, settled_at: datetime
    ) -> AuthorizationSettlement:
        """Move a row along an edge, so a test can arrange a settled state.

        **Test-only and not on the Protocol**: this face carries ``live_for`` alone,
        and a policy holding it cannot reach this. It exists because a suite
        exercising a *revoked* row has to revoke one, and doing that through a
        second object would be a second history.

        Args:
            authorization_id: The row to settle.
            to: The disposition to move it to.
            settled_at: The instant to record.

        Returns:
            Which of the four outcomes the step answered.
        """
        return self._log.settle(authorization_id, to, settled_at)

    def fail_live_for(self, error: Exception | None = None) -> None:
        """Arm every subsequent :meth:`live_for` to raise a store fault.

        **The branch ADR-0254 §6's fault clause is stated over**, and the one place
        this seam departs from the grant seam's discipline: a fault **takes the
        bar** rather than reading as an absence, so a policy that answered ``None``
        on one would turn a refusal the user's own act earned into an ``ALLOW``.

        Args:
            error: The underlying fault, preserved as ``__cause__``.
        """
        self._failure = (
            error if error is not None else RuntimeError("fake: the store is unreadable")
        )

    async def live_for(self, goal: str, tool_id: str) -> Authorization | None:
        """The live row of ``goal`` through ``tool_id``, or ``None``.

        The clock is read **once**, inside the modelled resource, and every row
        considered is evaluated against that instant.

        Raises:
            AuthorizationError: If a fault is armed (:meth:`fail_live_for`), or if
                more than one live row of that pair would answer.
        """
        self._calls += 1
        if self._failure is not None:
            msg = "fake: the authorization store could not be read"
            raise AuthorizationError(msg) from self._failure
        async with self._resource.held():
            return self._log.live_for(goal, tool_id, self._clock())

    def suspend_next_operation(self) -> LoopSuspension:
        """Hold the next call that enters the modelled resource open inside it."""
        return self._resource.suspend_next()

    @property
    def resource_log(self) -> ResourceLog:
        """When each call was inside the modelled resource (ADR-0060's case reads it)."""
        return self._resource.log


@final
class FakeAuthorizationResolution:
    """A non-persistent ``AuthorizationResolution`` test double (ADR-0254 §7, §16).

    The **trail's** face: one member, answering in every disposition because the
    trail's own first check reads that field. It can write nothing and cannot ask
    ``live_for``'s question.
    """

    def __init__(self, records: Sequence[Authorization] = ()) -> None:
        """Create the seam.

        Args:
            records: The history it starts with, applied in order under the same
                invariants ``record`` applies.

        Raises:
            InvalidAuthorizationError: If ``records`` is not a history a conforming
                store could hold.
        """
        self._log = _AuthorizationLog()
        self._resource = SuspendableResource()
        self._failure: Exception | None = None
        self._calls = 0
        for record in records:
            self._log.append(record)

    @property
    def call_count(self) -> int:
        """How many times :meth:`resolve` has been called."""
        return self._calls

    def hold(self, *records: Authorization) -> None:
        """Add rows to the history after construction, under the same invariants.

        Args:
            records: The rows to append, in order.

        Raises:
            InvalidAuthorizationError: If a row is not one a conforming store would
                admit at that point in the history.
        """
        for record in records:
            self._log.append(record)

    def settle(
        self, authorization_id: str, *, to: AuthorizationDisposition, settled_at: datetime
    ) -> AuthorizationSettlement:
        """Move a row along an edge, so a test can arrange a settled state.

        **Test-only and not on the Protocol.** A trail's route-(d) invariant refuses
        on the resolved row's *disposition*, so a suite exercising that check has to
        reach one — and the shipped revocation-between-``live_for``-and-``record``
        case is exactly a settlement taken between two reads of one history.

        Args:
            authorization_id: The row to settle.
            to: The disposition to move it to.
            settled_at: The instant to record.

        Returns:
            Which of the four outcomes the step answered.
        """
        return self._log.settle(authorization_id, to, settled_at)

    def fail_resolve(self, error: Exception | None = None) -> None:
        """Arm every subsequent :meth:`resolve` to raise a store fault.

        Args:
            error: The underlying fault, preserved as ``__cause__``.
        """
        self._failure = (
            error if error is not None else RuntimeError("fake: the store is unreadable")
        )

    async def resolve(self, authorization_id: str) -> Authorization | None:
        """The row with that id, whatever its disposition, or ``None``.

        Reads no clock and settles nothing.

        Raises:
            AuthorizationError: If a fault is armed (:meth:`fail_resolve`).
        """
        self._calls += 1
        if self._failure is not None:
            msg = "fake: the authorization store could not be read"
            raise AuthorizationError(msg) from self._failure
        async with self._resource.held():
            return self._log.resolve(authorization_id)

    def suspend_next_operation(self) -> LoopSuspension:
        """Hold the next call that enters the modelled resource open inside it."""
        return self._resource.suspend_next()

    @property
    def resource_log(self) -> ResourceLog:
        """When each call was inside the modelled resource (ADR-0060's case reads it)."""
        return self._resource.log


@final
class FakeGoalAuthorizationStore:
    """A non-persistent ``GoalAuthorizationStore`` test double (ADR-0254 §16).

    Structurally implements
    :class:`~ai_assistant.core.protocols.GoalAuthorizationStore` — and therefore
    :class:`~ai_assistant.core.protocols.GoalAuthorizations` and
    :class:`~ai_assistant.core.protocols.AuthorizationResolution` too, which is why
    the two narrow conformance suites are bound against this class as well as
    against their own fakes. That binding is what turns ADR-0254 §16's *"three
    faces, one object"* from an assertion into a test.

    :meth:`record`'s checks and its append are separated by no interleaving point,
    and so are :meth:`settle`'s read, comparisons and writes — which is how the
    indivisibility ADR-0254 §16 requires is obtained on a single event loop. Every
    method runs inside a
    :class:`~ai_assistant.testing.cancellation.SuspendableResource`, so the fake is
    a real subject for ADR-0060's cancellation clause at each of the lock sites a
    durable store would have. That does not weaken the argument: acquiring an
    uncontended :class:`asyncio.Lock` does not suspend, so nothing runs between the
    checks and the write that did not before.
    """

    def __init__(
        self,
        records: Sequence[Authorization] = (),
        *,
        now: Callable[[], datetime] = lambda: AUTHORIZATION_NOW,
    ) -> None:
        """Create the store.

        Args:
            records: The history it starts with, applied in order under the same
                invariants :meth:`record` applies.
            now: The clock :meth:`live_for` evaluates liveness against, read
                **once** per call. No other member reads it.

        Raises:
            InvalidAuthorizationError: If ``records`` is not a history a conforming
                store could hold.
        """
        self._log = _AuthorizationLog()
        self._clock = checked_clock(now, owner="FakeGoalAuthorizationStore")
        self._resource = SuspendableResource()
        self._read_failure: Exception | None = None
        self._write_failure: Exception | None = None
        for record in records:
            self._log.append(record)

    def suspend_next_operation(self) -> LoopSuspension:
        """Hold the next call that enters the modelled resource open inside it.

        There is one modelled resource and every method enters it, so this suspends
        whichever call arrives next rather than a named operation. The hook the
        cancellation case takes (ADR-0060 §3); test-only, and not part of the
        contract.

        Returns:
            The handle to wait on and release.
        """
        return self._resource.suspend_next()

    @property
    def resource_log(self) -> ResourceLog:
        """When each call was inside the modelled resource (ADR-0060's case reads it)."""
        return self._resource.log

    def fail_reads(self, error: Exception | None = None) -> None:
        """Arm every subsequent read to raise a store fault.

        Required of this fake as well as of the two narrow ones: a policy handed
        the store as its ``GoalAuthorizations``, or a trail handed it as its
        ``AuthorizationResolution``, must exhibit the same fail-closed branch, and a
        capability present on only one of the faces would leave that wiring
        untestable.

        Args:
            error: The underlying fault, preserved as ``__cause__``.
        """
        self._read_failure = (
            error if error is not None else RuntimeError("fake: the store is unreadable")
        )

    def fail_writes(self, error: Exception | None = None) -> None:
        """Arm every subsequent :meth:`record`, :meth:`settle` and :meth:`clear` to fault.

        A **store fault**, not a refusal: it raises
        :class:`~ai_assistant.core.errors.AuthorizationError` rather than
        :class:`~ai_assistant.core.errors.InvalidAuthorizationError`, because a
        refusal is what the invariants already produce from a badly-formed record —
        and because ``settle``'s refusals are **results** rather than exceptions
        (ADR-0254 §16), so there is no other way to reach that member's fault
        branch at all.

        Args:
            error: The underlying fault, preserved as ``__cause__``.
        """
        self._write_failure = (
            error if error is not None else RuntimeError("fake: the store is unwritable")
        )

    def _refuse_read(self) -> None:
        """Raise the scripted read fault, if one is armed.

        Raises:
            AuthorizationError: If :meth:`fail_reads` armed one.
        """
        if self._read_failure is not None:
            msg = "fake: the authorization store could not be read"
            raise AuthorizationError(msg) from self._read_failure

    def _refuse_write(self) -> None:
        """Raise the scripted write fault, if one is armed.

        Raises:
            AuthorizationError: If :meth:`fail_writes` armed one.
        """
        if self._write_failure is not None:
            msg = "fake: the authorization store could not be written"
            raise AuthorizationError(msg) from self._write_failure

    async def record(self, authorization: Authorization) -> str:
        """Append ``authorization`` and return its id.

        The invariant checks are *inside* the resource, not before it: a caller that
        validated against a store it no longer holds could pass a uniqueness check
        that the append then contradicts.

        Raises:
            AuthorizationError: If a store fault is scripted (:meth:`fail_writes`).
            InvalidAuthorizationError: On any ground ADR-0254 §16 names.
        """
        self._refuse_write()
        async with self._resource.held():
            return self._log.append(authorization)

    async def settle(
        self,
        authorization_id: str,
        /,
        *,
        to: AuthorizationDisposition,
        settled_at: datetime,
    ) -> AuthorizationSettlement:
        """Move one row along one of ADR-0254 §1's five edges, or say why not.

        **A refusal is a result and never an exception**, so the three non-``SETTLED``
        members are returned rather than raised; the only raise here is the scripted
        store fault.

        Raises:
            AuthorizationError: If a store fault is scripted (:meth:`fail_writes`).
        """
        self._refuse_write()
        async with self._resource.held():
            return self._log.settle(authorization_id, to, settled_at)

    async def live_for(self, goal: str, tool_id: str) -> Authorization | None:
        """The live row of ``goal`` through ``tool_id``, or ``None``.

        The clock is read **once**, inside the modelled resource, and the integrity
        refusal is taken before any lapsed proposal is settled.

        Raises:
            AuthorizationError: If a read fault is scripted (:meth:`fail_reads`), or
                if more than one live row of that pair would answer.
        """
        self._refuse_read()
        async with self._resource.held():
            return self._log.live_for(goal, tool_id, self._clock())

    async def resolve(self, authorization_id: str) -> Authorization | None:
        """The row with that id, whatever its disposition, or ``None``.

        Reads no clock and settles nothing.

        Raises:
            AuthorizationError: If a read fault is scripted (:meth:`fail_reads`).
        """
        self._refuse_read()
        async with self._resource.held():
            return self._log.resolve(authorization_id)

    async def standing(self, goal: str) -> tuple[Authorization, ...]:
        """Every ``ESTABLISHED`` row of ``goal``, live **and** lapsed.

        Evaluates no liveness, reports none and reads no clock: each row carries its
        own ``expires_at`` and the caller compares.

        Raises:
            AuthorizationError: If a read fault is scripted (:meth:`fail_reads`).
        """
        self._refuse_read()
        async with self._resource.held():
            return self._log.standing(goal)

    async def recent(self, *, limit: int = 50) -> tuple[Authorization, ...]:
        """Up to ``limit`` rows, newest first, ties broken by ``id`` ascending.

        The store's guard, in its class and with its allowlist, because ADR-0084 §4's
        substitutability runs in **both** directions: a double admitting
        ``limit=True`` would hand a consumer's tests one row where the store hands
        them one too but under a bound production would have refused.

        Raises:
            ValueError: If ``limit`` is not a strictly positive **exact** ``int``.
            AuthorizationError: If a read fault is scripted (:meth:`fail_reads`).
        """
        if type(limit) is not int or limit <= 0:
            msg = (
                f"limit must be a strictly positive int, got "
                f"{describe_untrusted(limit)}; the type is checked because a bool "
                f"passes the comparison while meaning a bound of one"
            )
            raise ValueError(msg)
        self._refuse_read()
        async with self._resource.held():
            return self._log.ordered(limit)

    async def export(self) -> tuple[Authorization, ...]:
        """**Every** row, in :meth:`recent`'s order.

        Proposed, established, declined, expired, revoked and superseded, with each
        member's basis whole: this is what discharges ADR-0004 §6's portability
        obligation for the store, so it omits nothing.

        Raises:
            AuthorizationError: If a read fault is scripted (:meth:`fail_reads`).
        """
        self._refuse_read()
        async with self._resource.held():
            return self._log.ordered()

    async def clear(self) -> int:
        """Delete every row, returning the number removed.

        The body runs inside the modelled resource for :meth:`record`'s reason and
        for one of its own: the count returned must describe the deletion that
        actually happened.

        Raises:
            AuthorizationError: If a store fault is scripted (:meth:`fail_writes`).
        """
        self._refuse_write()
        async with self._resource.held():
            return self._log.clear()


__all__ = [
    "AUTHORIZATION_ACCOUNT",
    "AUTHORIZATION_ACT",
    "AUTHORIZATION_DESTINATION",
    "AUTHORIZATION_EXPIRES_AT",
    "AUTHORIZATION_GOAL",
    "AUTHORIZATION_NOW",
    "AUTHORIZATION_PROPOSED_AT",
    "AUTHORIZATION_TOOL",
    "FakeAuthorizationResolution",
    "FakeGoalAuthorizationStore",
    "FakeGoalAuthorizations",
    "authorization",
    "authorization_basis",
    "coverage_member",
    "money_bound",
    "opening_act",
    "period_bound",
    "terms_bound",
]
