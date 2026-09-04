"""Canonical test doubles for the permission contracts (ADR-0021).

The shared fakes for :class:`~ai_assistant.core.protocols.ActionPolicy` and
:class:`~ai_assistant.core.protocols.AuditTrail`, so a subsystem that gates or
records actions (`orchestration`, and the invocation path when it lands) can
test against real, contract-correct implementations *without importing the
permissions subsystem's internals* (CLAUDE.md golden rule 1).

Both are held to their Protocol's shared conformance suite, which is what stops
a fake drifting from the contract it stands in for.

``FakeAuditTrail`` writes through a
:class:`~ai_assistant.testing.cancellation.SuspendableResource` so it is a real
subject for the cancellation clause ``core.protocols`` states (ADR-0060), rather
than an implementation the obligation cannot reach. **Every** mutating method
enters it — ``record`` and ``clear`` alike — because the clause is stated per
locked write, so a write that skipped the resource would be one the case could
only opt out of (#396).
"""

from __future__ import annotations

import asyncio
import functools
import itertools
import os
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Final, Protocol, runtime_checkable
from uuid import uuid4

from pydantic import TypeAdapter

from ai_assistant.core.clock import ClockReadingError, checked_clock
from ai_assistant.core.errors import (
    AuditError,
    AuthorisationSpentError,
    DuplicateDecisionError,
    InvalidAuthorisationError,
    InvalidCompletionError,
    InvalidResolutionError,
    RecipientGrantError,
    SpendCeilingError,
    SpendUndeterminedError,
    UnrecordedAuthorisationError,
)
from ai_assistant.core.types import (
    CostBasis,
    CoverageUnrecordedBinding,
    DurableIdentifier,
    EgressBinding,
    Idempotency,
    OriginUnrecordedBinding,
    PermissionDecision,
    PermissionOutcome,
    PermissionRuling,
    RecordedInvocation,
    Reversibility,
    RiskLevel,
    SpendAdmissionHandle,
    SpendPeriod,
    SpendTotal,
    ToolCost,
    ToolFailureKind,
    ToolInvocation,
    ToolOutcome,
    describe_untrusted,
)
from ai_assistant.testing._detachment import field_state
from ai_assistant.testing.cancellation import LoopSuspension, SuspendableResource
from ai_assistant.testing.recipient_grants import FakeRecipientGrantResolution
from ai_assistant.testing.spend import (
    Bounds,
    SpendBooks,
    SpendTrapError,
    Unpriced,
    add_exactly,
    measurable,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
    from decimal import Decimal

    from ai_assistant.core.protocols import RecipientGrantResolution
    from ai_assistant.core.types import ActionRequest, RecipientGrant
    from ai_assistant.testing.cancellation import ResourceLog


def _names_a_standing_authorisation(decision: PermissionDecision) -> bool:
    """Whether ADR-0193 §6's invariant is in scope for ``decision``.

    A **route-(b) egress decision**, and nothing else: a non-resolving ``ALLOW``
    whose ``egress_binding`` is not ``None`` and whose ``authorised_by`` is set.
    ``resolves`` is the discriminator the records already carry — a route-(a)
    ``ALLOW`` sets it and equals it to ``authorised_by``, and a route-(b) one
    leaves it unset — so no field was added to say which basis a row rests on
    (ADR-0193 §6).

    **The scope is deliberately narrow, and no lane widens it into a general rule
    about** ``authorised_by``. A decision with no ``egress_binding`` is not an
    egress call, and ADR-0021 §6's standing grants for *other* actions stay
    deferred and unnarrowed: such a decision falls outside this invariant rather
    than needing an exception inside it, so the ADR that opens one states its own
    scope beside this one instead of finding ``PermissionDecision`` already shaped
    against it.
    """
    ruling = decision.ruling
    return (
        ruling.outcome is PermissionOutcome.ALLOW
        and decision.resolves is None
        and decision.egress_binding is not None
        and ruling.authorised_by is not None
    )


def _check_standing_shape(decision: PermissionDecision) -> None:
    """Refuse the route-(b) defects decidable from the decision alone (ADR-0193 §6).

    Three of ADR-0193 §6's eight checks and its pairing clause need no store, so
    they are made here — **before** the ended-epoch refusals ADR-0184 §4 and
    ADR-0233 §14 state over every decision. The order is what makes an
    origin-unrecorded or coverage-unrecorded case land as an
    :class:`~ai_assistant.core.errors.InvalidAuthorisationError` rather than as a
    bare ``AuditError``, which ADR-0193 §14 requires by type; both clauses are
    satisfied either way, since the row is still refused and this class *is* an
    ``AuditError``. A decision carrying either shape and **not** in route-(b) scope
    is untouched here and still refused there, exactly as before.

    **The origin check is stated over the binding's arm, not over a field's
    value.** Only :class:`~ai_assistant.core.types.EgressBinding` carries
    ``planned_with_external_content`` at all, so a validator reading the check as a
    field test would raise ``AttributeError`` on the other arm — or, worse, accept
    it — and ADR-0193 §4's floor would be bypassed by a *missing* field rather than
    by a false one.

    Raises:
        InvalidAuthorisationError: If a **resolving** ``ALLOW`` carries an
            ``authorised_subject``; or if a route-(b) egress decision's binding
            records no origin, records that the call was planned over external
            content, or carries no ``authorised_subject`` to check.
    """
    ruling = decision.ruling
    if decision.resolves is not None:
        if ruling.authorised_subject is not None:
            msg = (
                f"decision {decision.id!r} resolves a confirmation and fingerprints a "
                f"standing authorisation; route (a) rests on a recorded confirmation, "
                f"which is not a grant and has no subject digest (ADR-0193 §6)"
            )
            raise InvalidAuthorisationError(msg)
        return
    if not _names_a_standing_authorisation(decision):
        return
    binding = decision.egress_binding
    if not isinstance(binding, EgressBinding):
        msg = (
            f"decision {decision.id!r} rests on a standing authorisation but records an "
            f"egress call whose origin was never recorded; no standing authorisation "
            f"covers such a call (ADR-0193 §2, §6)"
        )
        raise InvalidAuthorisationError(msg)
    if binding.planned_with_external_content:
        msg = (
            f"decision {decision.id!r} rests on a standing authorisation but records a "
            f"call planned over external content; route (a) — a decision of the user "
            f"about that call — is the only route to an ALLOW on one (ADR-0193 §4, §6)"
        )
        raise InvalidAuthorisationError(msg)
    if ruling.authorised_subject is None:
        msg = (
            f"decision {decision.id!r} names standing authorisation "
            f"{ruling.authorised_by!r} and fingerprints none; a pointer with nothing on "
            f"the row to contradict a rebinding is the record ADR-0193 §6 refuses"
        )
        raise InvalidAuthorisationError(msg)


def _grant_covers(  # noqa: PLR0911 — one return per ADR-0193 §6 comparison, and no fewer
    decision: PermissionDecision, grant: RecipientGrant, binding: EgressBinding
) -> InvalidAuthorisationError | None:
    """Compare the resolved grant against the decision it is claimed to authorise.

    Six of ADR-0193 §6's eight checks — the two ends of the liveness interval and
    §3's declaration, account and destination comparisons, plus the digest. Taken
    over the record ``outstanding`` returned rather than over the decision's
    account of it, which is the whole of what makes the pointer *verified* rather
    than merely present.

    A **module function** rather than a method, so it holds no store and can reach
    none: everything it needs is in its arguments, which is what keeps it a
    comparison of recorded values and stops it acquiring a second read.

    Args:
        decision: The validated snapshot about to be appended.
        grant: The outstanding granting record its ``authorised_by`` resolved to.
        binding: ``decision``'s own binding, already narrowed to the arm that
            records an origin.

    **It returns the refusal rather than raising it**, so ``record`` can apply it
    inside its transaction and after the duplicate-id checks — see
    :meth:`SqliteAuditTrail._resolve_standing_authorisation` for why that ordering
    is the only one both #526's pin and ADR-0021 §4's error split admit.

    Returns:
        The refusal the comparison earned, or ``None`` where the grant covers the
        decision.
    """
    named = grant.id
    if grant.decided_at > decision.decided_at:
        return InvalidAuthorisationError(
            f"decision {decision.id!r} rests on grant {named!r}, which was established "
            f"after the ruling was made; the policy could not have read a record that "
            f"did not exist when it ruled (ADR-0193 §6)"
        )
    if grant.expires_at <= decision.decided_at:
        return InvalidAuthorisationError(
            f"decision {decision.id!r} rests on grant {named!r}, which was not live when "
            f"the ruling was made; an expired grant never sources a new ALLOW "
            f"(ADR-0193 §6)"
        )
    if grant.tool != decision.tool:
        return InvalidAuthorisationError(
            f"decision {decision.id!r} rests on grant {named!r}, which was established "
            f"about a different declaration; coverage compares the ToolDefinition whole "
            f"and by value, so a declaration edit re-prompts (ADR-0193 §1, §3)"
        )
    if grant.account != binding.account:
        return InvalidAuthorisationError(
            f"decision {decision.id!r} rests on grant {named!r}, which was established "
            f"against a different connected account; an account is two facts, identity "
            f"and connection reference, and never one (ADR-0193 §3)"
        )
    if any(member not in grant.destinations for member in binding.canonical_destination_set):
        return InvalidAuthorisationError(
            f"decision {decision.id!r} rests on grant {named!r}, which does not name "
            f"every recipient of this call; coverage is set membership and nothing "
            f"looser (ADR-0193 §3)"
        )
    if decision.ruling.authorised_subject != grant.subject_digest:
        return InvalidAuthorisationError(
            f"decision {decision.id!r} fingerprints a standing authorisation the store's "
            f"grant {named!r} does not match; the digest is recomputed from the record "
            f"the store returned and never taken on the decision's word (ADR-0193 §6)"
        )
    return None


#: Reported when a policy is asked to resolve something nobody was ever shown.
_NOT_A_CONFIRMATION = "fake: the decision resolved was not a CONFIRM, so it authorises nothing"

#: ADR-0181 §5's ground, worded as the section's second clause allows: a statement
#: about the **selection this system made**, never a detection, a score, or a claim
#: that any argument or destination of the call came from external content.
_PLANNED_OVER_EXTERNAL = (
    "the material selected into the model call that produced this request included "
    "a record resting on recorded external content"
)

#: ADR-0184 §7's floor, worded as a statement about the **record** rather than about
#: the call: what is missing is a fact the trail never wrote down, and no reading of
#: the user's answer supplies it.
_ORIGIN_UNRECORDED = (
    "fake: the user approved, but this decision records an egress call whose origin "
    "was never recorded, and no answer can establish it"
)

#: ADR-0184 §7's floor extended by cause (ADR-0233 §14), worded the same way and for
#: the same reason.
_COVERAGE_UNRECORDED = (
    "fake: the user approved, but this decision records an egress call whose coverage "
    "was never recorded, and no answer can establish it"
)


class FakeActionPolicy:
    """A conservative, monotone ``ActionPolicy`` test double.

    Structurally implements :class:`~ai_assistant.core.protocols.ActionPolicy`.
    Unlike :class:`~ai_assistant.testing.policy.FakeMemoryPolicy` this is not a
    constant-answer fake: a policy that returned a configured outcome regardless
    of the request would satisfy the monotonicity obligation *vacuously* — a
    constant function is monotone — leaving the conformance suite's central
    check with nothing to bite on. So the rules are real, and the two knobs move
    the thresholds rather than replacing the reasoning.

    The rules, combined by taking the **most restrictive** result:

    * ``risk_level`` at or above ``confirm_at`` — ``CONFIRM``.
    * ``IRREVERSIBLE`` — ``CONFIRM``, whatever the risk level says.
    * a non-empty ``discloses`` — ``CONFIRM``. The ADR-0021 §5 floor, over
      *any* tier rather than a list of them.
    * an ``UNKNOWN`` cost — ``CONFIRM``. ADR-0016 §4's fail-closed clause.
    * ``risk_level`` at or above ``deny_at``, when one is configured — ``DENY``.
    * an ``egress_binding`` carrying ``planned_with_external_content`` —
      ``CONFIRM``. ADR-0181 §5's floor, over a fact about the **request** rather
      than about the declaration, and the one clause here that reads anything but
      ``request.tool``.

    Each clause is a monotone step function of one declared field, and the
    maximum of monotone functions is monotone, so no configuration of the knobs
    can produce a non-conforming policy. That is deliberate: a fake configurable
    into violating its own conformance suite is a trap.

    Beyond the contract it records every call to :attr:`requests` and
    :attr:`resolutions`, so a consumer's test can assert *that* the gate was
    consulted and with what.
    """

    def __init__(
        self,
        *,
        confirm_at: RiskLevel | None = RiskLevel.MEDIUM,
        deny_at: RiskLevel | None = None,
    ) -> None:
        """Create the fake policy.

        Args:
            confirm_at: Risk level at or above which an action needs the user's
                confirmation; ``None`` never confirms on risk alone (the floors
                still apply).
            deny_at: Risk level at or above which an action is refused outright;
                ``None`` never denies on risk. Set it to ``RiskLevel.LOW`` for a
                policy that refuses everything.
        """
        self.confirm_at = confirm_at
        self.deny_at = deny_at
        self.requests: list[ActionRequest] = []
        self.resolutions: list[tuple[PermissionDecision, bool]] = []

    async def decide(self, request: ActionRequest) -> PermissionRuling:
        """Rule on ``request`` by the thresholds and floors in the class docstring.

        The last clause is ADR-0181 §5's and is not configurable: a request whose
        binding carries ``planned_with_external_content`` gets no ``ALLOW``, because
        ADR-0148 §3's route (a) — the user's own answer about *this* request — is
        unavailable to a member holding no resolution. It is monotone like the rest
        (a step function of one field of the request, combined by maximum), so the
        knobs still cannot configure this fake out of conformance. A request whose
        binding carries ``False``, or which carries no binding, is judged on the
        ordinary path.
        """
        self.requests.append(request.model_copy(deep=True))
        tool = request.tool

        grounds: list[tuple[PermissionOutcome, str]] = [
            (PermissionOutcome.ALLOW, f"{tool.risk_level} risk, nothing disclosed off-device")
        ]
        if self.confirm_at is not None and tool.risk_level >= self.confirm_at:
            grounds.append((PermissionOutcome.CONFIRM, f"risk is {tool.risk_level}"))
        if tool.reversibility is Reversibility.IRREVERSIBLE:
            grounds.append((PermissionOutcome.CONFIRM, "the effect cannot be undone"))
        if tool.discloses:
            tiers = ", ".join(tier.value for tier in tool.discloses)
            grounds.append((PermissionOutcome.CONFIRM, f"it may disclose {tiers} data off-device"))
        if tool.cost.basis is CostBasis.UNKNOWN:
            grounds.append((PermissionOutcome.CONFIRM, "its cost is undeclared"))
        if self.deny_at is not None and tool.risk_level >= self.deny_at:
            grounds.append((PermissionOutcome.DENY, f"risk is {tool.risk_level}"))
        binding = request.egress_binding
        if binding is not None and binding.planned_with_external_content:
            grounds.append((PermissionOutcome.CONFIRM, _PLANNED_OVER_EXTERNAL))

        outcome = max(outcome for outcome, _ in grounds)
        reasons = [reason for ruled, reason in grounds if ruled is outcome]
        return PermissionRuling(outcome=outcome, reason=f"fake: {'; '.join(reasons)}")

    async def resolve(self, confirmed: PermissionDecision, *, approved: bool) -> PermissionRuling:
        """Turn the user's answer to ``confirmed`` into the ruling that resolves it.

        A refusal is honoured unconditionally, and a ``confirmed`` that was never
        a ``CONFIRM`` cannot mint an authorisation — both obligations of
        ADR-0021 §3 rather than choices this fake makes.

        **ADR-0181 §5's fourth clause is discharged by the first of those**, not by
        a clause of its own: where ``confirmed.egress_binding`` carries
        ``planned_with_external_content``, an ``ALLOW`` requires ``approved`` to be
        true, and ``approved`` being false already yields ``DENY`` for every
        ``confirmed``. Nothing is added for the approving case, because the user's
        answer about that call **is** route (a) — the one route §5's second clause
        leaves open.

        **ADR-0184 §7's floor is the one clause that does need a branch here, and
        ADR-0233 §14 extends it by cause to a second**: these are the only cases
        where an approval is not enough. Where ``confirmed.egress_binding`` records
        no origin — an :class:`~ai_assistant.core.types.OriginUnrecordedBinding`,
        which only a row written before ADR-0181 can carry — or records no coverage —
        a :class:`~ai_assistant.core.types.CoverageUnrecordedBinding`, which only a
        row written before ADR-0233 can carry — no ``ALLOW`` is returned whatever
        ``approved`` says, because the missing fact cannot be established at all and
        ADR-0181 §5's second clause leaves no route by which any authorisation covers
        such a call. The second branch is written rather than inherited: a
        coverage-unrecorded row *has* ``planned_with_external_content`` and falls
        straight past the first ``isinstance``. Nothing in the tree hands either one
        here; both are floors, written because a floor's value is that it holds when
        a route appears.
        """
        self.resolutions.append((confirmed.model_copy(deep=True), approved))

        if not approved:
            return PermissionRuling(
                outcome=PermissionOutcome.DENY, reason="fake: the user declined"
            )
        if confirmed.ruling.outcome is not PermissionOutcome.CONFIRM:
            return PermissionRuling(outcome=PermissionOutcome.DENY, reason=_NOT_A_CONFIRMATION)
        if isinstance(confirmed.egress_binding, OriginUnrecordedBinding):
            return PermissionRuling(outcome=PermissionOutcome.DENY, reason=_ORIGIN_UNRECORDED)
        if isinstance(confirmed.egress_binding, CoverageUnrecordedBinding):
            return PermissionRuling(outcome=PermissionOutcome.DENY, reason=_COVERAGE_UNRECORDED)
        return PermissionRuling(
            outcome=PermissionOutcome.ALLOW,
            reason="fake: the user approved the confirmation",
            authorised_by=confirmed.id,
        )


@runtime_checkable
class MintsIdentifiers(Protocol):
    """What :class:`FakeAuditTrail` mints invocation row ids from (ADR-0192 §2).

    Structural, so a suite can inject a factory that forces a collision, returns
    a value no row can be built from, or raises on its own account — the three
    shapes ADR-0192 §2's clauses are about, and none of which a concrete class
    could be asked to do in production.
    """

    def __call__(self) -> str:
        """Return an identifier this process has neither issued nor reserved."""
        ...

    def reserve(self, ids: Iterable[str]) -> None:
        """Promise that none of ``ids`` will be returned by any later call."""
        ...


class FakeIdentifierSpace:
    """The per-process state :class:`FakeIdentifiers` draws from (ADR-0192 §2).

    A copy of ``permissions.identifiers.IdentifierSpace`` rather than an import of
    it. Nothing in ``ai_assistant.testing`` imports a subsystem, and the boundary
    is the reason: the factory is ``permissions/``-internal, which is what makes
    ADR-0192 §2's reservation store-internal. ``permissions/_transactions.py``
    already states the trade for this exact boundary — "four copies of one function
    is what that boundary costs" — and the copy is what keeps this fake usable by a
    subsystem that must not import the real store (golden rule 1).

    Held apart from the factory so two factories constructed in one process draw
    from **one** sequence and share **one** reservation set: a factory whose issued
    ids are process-global but whose reservations are instance-local still reissues
    an id ``clear()`` erased.
    """

    def __init__(self, *, nonce: str | None = None) -> None:
        """Open a fresh space, optionally with a pinned nonce.

        Args:
            nonce: The per-space component, drawn once. Injectable so a suite can
                pin the sequence rather than race it. It is not what makes the
                space fork-safe — the pid folded in at allocation is.
        """
        self._nonce: Final = nonce if nonce is not None else uuid4().hex
        self._counter: Iterator[int] = itertools.count()
        self._reserved: set[str] = set()

    def mint(self) -> str:
        """Return the next identifier this space has neither issued nor reserved."""
        while True:
            # Read here and not in ``__init__``: a child of a ``fork`` inherits the
            # nonce and the counter, and the pid is the only component that can
            # differ (ADR-0049 §3).
            candidate = f"inv-{os.getpid()}-{self._nonce}-{next(self._counter)}"
            if candidate not in self._reserved:
                return candidate

    def reserve(self, ids: Iterable[str]) -> None:
        """Take ``ids`` out of this space for the life of the process."""
        self._reserved.update(ids)


#: The space every :class:`FakeIdentifiers` shares unless a caller says otherwise.
FAKE_PROCESS_SPACE: Final = FakeIdentifierSpace()


class FakeIdentifiers:
    """The canonical fake's identifier factory: a per-process nonce and a counter.

    With the allocation-time pid folded in, which is what ADR-0192 §2 requires of
    every satisfying construction and what a nonce and counter alone are not: those
    are exactly what a ``fork`` copies.
    """

    def __init__(self, *, space: FakeIdentifierSpace | None = None) -> None:
        """Draw from ``space``, or from the process's own.

        Args:
            space: The state to draw from; a suite pins a sequence by passing one.
        """
        self._space = space if space is not None else FAKE_PROCESS_SPACE

    def __call__(self) -> str:
        """Return a fresh identifier."""
        return self._space.mint()

    def reserve(self, ids: Iterable[str]) -> None:
        """Take ``ids`` out of the space for the life of the process."""
        self._space.reserve(ids)


def _fake_now() -> datetime:
    """The fake trail's default clock: the real one, read in UTC."""
    return datetime.now(UTC)


class FakeAuditTrail:
    """A non-persistent, append-only ``AuditTrail`` test double backed by a dict.

    Structurally implements :class:`~ai_assistant.core.protocols.AuditTrail`,
    including the parts that make the trail an *active* participant: write-once
    ids, the resolution invariant, and detachment on both the write and the read
    path.

    :meth:`record`'s checks and its append are separated by no interleaving
    point, which is how the atomicity ADR-0021 §4 requires is obtained on a
    single event loop: two concurrent resolutions of one ``CONFIRM`` cannot both
    observe an unresolved question. The append — and every other method, the
    reads included since #397 — runs inside a
    :class:`~ai_assistant.testing.cancellation.SuspendableResource` so the fake
    is a subject for ADR-0060's cancellation clause on each of the lock sites the
    ``sqlite3`` trail has, and that does not weaken the argument: acquiring an
    uncontended :class:`asyncio.Lock` does not suspend, so nothing runs between
    the checks and the append that did not before — and under contention the lock
    serialises the pair outright.
    """

    def __init__(  # noqa: PLR0913 — one keyword per ADR-0194 §1 setting, injected explicitly
        self,
        *,
        now: Callable[[], datetime] = _fake_now,
        identifiers: MintsIdentifiers | None = None,
        currency: str | None = None,
        day_ceiling: Decimal | None = None,
        month_ceiling: Decimal | None = None,
        allowance: Decimal | None = None,
        timezone: str = "UTC",
        recipient_grants: RecipientGrantResolution | None = None,
    ) -> None:
        """Create an empty trail.

        Args:
            now: The clock the ledger stamps ``recorded_at`` from, wrapped by
                ``checked_clock`` (ADR-0026). Injected so a suite pins the
                idempotency window's boundary rather than racing it; no caller ever
                supplies an instant (ADR-0192 §1).
            identifiers: The factory each invocation row's ``id`` is minted from.
                Defaults to the process's own, so two fakes in one process never
                mint from independent sequences.
            currency: ADR-0194 §1's reporting currency, or ``None``. Set alone it
                configures a currency totals are computed under and refuses
                nothing.
            day_ceiling: The ``CALENDAR_DAY`` ceiling, or ``None`` for unbounded.
            month_ceiling: The ``CALENDAR_MONTH`` ceiling, or ``None``.
            allowance: What an unpriced call is accounted at, or ``None``.
            timezone: The IANA zone the calendar periods are computed in — what
                ``Settings.timezone`` supplies in the running system.
            recipient_grants: The **resolution face** of the standing-grant store,
                against which :meth:`record` resolves a route-(b)
                ``authorised_by`` (ADR-0193 §6). One member wide, so this fake can
                validate a grant and can never author one — the split modelled in
                the double as well as in the contract.

                ``None`` substitutes an **empty**
                :class:`~ai_assistant.testing.recipient_grants.FakeRecipientGrantResolution`,
                so this fake always *has* a seam — ADR-0193 §6 is unqualified
                about that and gives the trail no counterpart to §7's no-source
                mode for a policy — and the seam it gets holds nothing. Every
                route-(b) pointer then resolves to ``None`` and the row is
                refused, which is the only honest answer a trail with no grant
                store can give. A fresh instance per trail rather than a shared
                default, because this one is scriptable and two trails sharing a
                default could arrange each other's history.

        **Explicit values, never a ``Settings`` read** (ADR-0194 §11): the
        composition root is the sole reader of those five settings, and a fixture
        builds them here directly.
        """
        self._decisions: dict[str, PermissionDecision] = {}
        # Insertion order **is** the durable append order every admission rule in
        # ADR-0192 §1 is decided on — deliberately not an ordering over
        # ``recorded_at``, so a clock that steps backwards cannot make a completed
        # act stop being the most recent one.
        self._invocations: dict[str, ToolInvocation] = {}
        # The claim ids a completion row already names, maintained beside
        # ``_invocations`` on every write to it. It answers ADR-0192 §2's
        # "an outcome cannot be written twice" in constant time, where scanning
        # the rows for it makes appending ``n`` completions cost ``n**2``
        # comparisons -- which ADR-0194 §11's ten-thousand-row fixture pays in
        # full. It is derived state and never a second source of truth: every
        # membership question it answers is the one
        # ``any(row.completes == named for row in self._invocations.values())``
        # answers, and ``clear()`` empties the two together.
        self._completed: set[str] = set()
        self._clock = checked_clock(now, owner="FakeAuditTrail")
        self._identifiers: MintsIdentifiers = (
            identifiers if identifiers is not None else FakeIdentifiers()
        )
        self._resource = SuspendableResource()
        self._books = SpendBooks(
            currency=currency,
            day_ceiling=day_ceiling,
            month_ceiling=month_ceiling,
            allowance=allowance,
            timezone=timezone,
        )
        # Its own lock and its own resource: ADR-0194 §3 serialises admissions
        # against each other and deliberately not against the appends.
        self._spend_lock = asyncio.Lock()
        self._spend_park: LoopSuspension | None = None
        self._recipient_grants: RecipientGrantResolution = (
            recipient_grants if recipient_grants is not None else FakeRecipientGrantResolution()
        )

    def suspend_next_operation(self) -> LoopSuspension:
        """Hold the next call that enters the modelled resource open inside it.

        There is one modelled resource and every method enters it — the two writes
        and, since #397, the five reads — so this suspends whichever call arrives
        next rather than a named operation.

        The hook ``AuditTrailContract``'s cancellation case takes (ADR-0060 §3).
        Test-only, and not part of the ``AuditTrail`` contract: the Protocol
        deliberately grows no affordance for this, so the suite asks the *subject*
        it was handed rather than the seam every consumer depends on.

        Returns:
            The handle to wait on and release.
        """
        return self._resource.suspend_next()

    @property
    def resource_log(self) -> ResourceLog:
        """When each call was inside the modelled resource (ADR-0060's case reads it)."""
        return self._resource.log

    async def record(self, decision: PermissionDecision) -> str:
        """Append ``decision`` and return its id.

        The snapshot is taken by **revalidating** rather than by copying, which
        is ADR-0021 §4's "detached, validated snapshot" — ADR-0018 §4's rule that
        "what a registry stores must be valid and detached", imported. A copy
        alone detaches without checking, so a decision corrupted past its frozen
        model's guard — a ``decided_at`` written back as naive is the sharp
        case — would be stored and then make every later ``recent()`` raise on
        comparing it against the aware values beside it. A store that can be put
        into a state where reads crash has not merely accepted bad input; it has
        stopped being readable.

        Rebuilt as a :class:`~ai_assistant.core.types.PermissionDecision`
        specifically, not as ``type(decision)`` — the same correction
        ``ActionRequest`` makes on the definition it detaches. A caller's
        subclass could override ``model_copy`` to return ``self``, and storing
        that instance would hand every later ``get``/``recent``/``export`` the
        trail's own object, so the read-path detachment below would silently
        stop holding and an appended entry could be rewritten through it.
        Rebuilding into the declared type is also what makes the stored record
        equal to the one that reloads from disk, since ``extra="forbid"`` refuses
        a subclass's extra fields rather than flattening them away at
        serialisation. Rebuilt through :func:`_revalidated_decision`, which is the
        same helper the claim path reads its argument with: a subclass *beneath* the
        decision would otherwise be flattened away silently — nothing on the value
        itself is undeclared — and the trail would record less than it was handed
        (``_detachment._refuse_undeclared``). Reading ``decision.model_dump()`` here would
        also let an overridden method decide what is stored, which is the hazard
        that helper exists for.

        **A decision whose ``egress_binding`` records no origin, or no coverage, is
        refused** (ADR-0184 §4, ADR-0233 §14), and it is the one refusal the model
        cannot make for itself: an
        :class:`~ai_assistant.core.types.OriginUnrecordedBinding` and a
        :class:`~ai_assistant.core.types.CoverageUnrecordedBinding` are each a
        *valid* member of a ``PermissionDecision``, because each has to be for a
        stored row to decode into one. Each represents a row from an epoch that has
        ended, so each is only ever read out of a store and never minted into one — a
        caller bypassing ``from_request`` could otherwise append one and fabricate
        history rather than a value. This fake holds objects rather than bytes and so
        cannot be seeded with such a row at all, which is why the read half of
        ADR-0184 §5 is pinned in ``SqliteAuditTrail``'s own tests while *these*
        clauses are in the shared conformance suite.

        **And it is named from the snapshot**, because a caller can hand over a raw
        mapping: it validates into a decision, and ``decision.id`` on a ``dict`` is an
        ``AttributeError`` raised from inside the refusal that was about to be made.

        **The refusal is judged on the rebuilt snapshot rather than on what the
        caller handed over, and the order is load-bearing.**
        ``model_copy(update=...)`` does not validate, so a caller can put a bare
        mapping into ``egress_binding``; a check in front of the rebuild sees a
        ``dict``, answers ``False``, and the rebuild then turns that mapping into
        exactly the shape the check was meant to stop. Checking what will actually be
        stored closes every route into the shape at once rather than the one a caller
        took.

        Raises:
            AuditError: If the decision does not satisfy its own model, or carries
                an ``OriginUnrecordedBinding`` or a ``CoverageUnrecordedBinding``.
                Raised
                as an ``AuditError`` rather than letting pydantic's
                ``ValidationError`` escape, because CONTRIBUTING has this layer
                raise only from the ``AssistantError`` hierarchy — a caller
                handling "the trail would not accept this" should not need a
                second handler for the shape of the refusal.
            DuplicateDecisionError: If the id is already recorded.
            InvalidResolutionError: If ``resolves`` fails the invariant.
            InvalidAuthorisationError: If a route-(b) egress decision fails any of
                ADR-0193 §6's eight checks, or if a resolving ``ALLOW`` carries an
                ``authorised_subject``.
        """
        snapshot = _revalidated_decision(decision)
        # ADR-0193 §6's store-free refusals run **before** the origin-unrecorded
        # one below, which is what makes a route-(b) row carrying that shape land
        # as an ``InvalidAuthorisationError`` rather than as a bare ``AuditError``
        # — a subclass of it, so ADR-0184 §4 is satisfied either way, and a
        # decision not in route-(b) scope is refused below exactly as before.
        _check_standing_shape(snapshot)
        if isinstance(snapshot.egress_binding, OriginUnrecordedBinding):
            msg = (
                f"decision {snapshot.id!r} is not a valid record: its egress binding "
                f"records no origin, which is a shape only a row written before "
                f"ADR-0181 can have; the trail reads such rows and never writes one"
            )
            raise AuditError(msg)
        if isinstance(snapshot.egress_binding, CoverageUnrecordedBinding):
            msg = (
                f"decision {snapshot.id!r} is not a valid record: its egress binding "
                f"records no coverage, which is a shape only a row written before "
                f"ADR-0233 can have; the trail reads such rows and never writes one"
            )
            raise AuditError(msg)
        # The resolution read is the one ``await`` that is deliberately **not**
        # inside the resource below: it is a read of a *different* store, and
        # ADR-0193 §6 states this contract's guarantee over that read rather than
        # over the append precisely because the two are separate awaits and no
        # linearisation point is built across the two stores. A revocation landing
        # in between leaves the decision recorded, which §9 states as the residual
        # window and §14 pins as a test.
        # Its **verdict is carried into the resource rather than raised here**, so
        # the duplicate-id checks refuse first: a replayed route-(b) decision whose
        # grant has since been revoked is a *replayed write*, and reporting it as
        # an unvalidated authorisation would blur the two classes ADR-0021 §4 split
        # so an operator can tell them apart.
        refusal = await self._resolve_standing_authorisation(snapshot)
        # The checks are *inside* the resource, not before it: a caller that
        # validated against a trail it no longer holds could pass a duplicate or
        # resolution check that the append then contradicts. This is where the
        # class docstring's "no interleaving point between the checks and the
        # append" is actually kept once there is a lock at all.
        async with self._resource.held():
            if snapshot.id in self._decisions:
                msg = (
                    f"decision {snapshot.id!r} is already recorded; the trail is "
                    f"append-only, so history cannot be rewritten by replaying a write"
                )
                raise DuplicateDecisionError(msg)
            if snapshot.id in self._invocations:
                # ADR-0192 §2: one id space, every row in it. Refused inside the
                # same atomic act, and as an ``AuditError`` rather than a
                # ``DuplicateDecisionError`` — what is already present is not a
                # decision, so re-recording one is not what happened.
                msg = (
                    f"decision {snapshot.id!r} names a row the trail already holds as an "
                    f"invocation; one identifier names one record, of either kind"
                )
                raise AuditError(msg)
            if refusal is not None:
                raise refusal
            if snapshot.resolves is not None:
                self._check_resolution(snapshot)
            self._decisions[snapshot.id] = snapshot
        return snapshot.id

    async def _resolve_standing_authorisation(
        self, decision: PermissionDecision
    ) -> InvalidAuthorisationError | None:
        """Resolve a route-(b) pointer against the grant records (ADR-0193 §6).

        The other five of ADR-0193 §6's eight checks — the ones that need the
        store — plus the digest, taken over **the record the store returned**
        rather than over the decision's account of it. ADR-0021 §3 said what the
        standard is and this is it: *nothing is taken on trust*. Before this
        clause a non-resolving ``ALLOW`` carrying an ``authorised_by`` was written
        with no check of any kind, which is exactly the hole ADR-0021 §3 named
        when it called such a field "a pointer this contract does not verify".

        **The resolution read is one ``await`` and the append is another**, and
        this contract builds no linearisation point across the two stores. What is
        guaranteed is stated over the read: *at the instant the pointer was
        resolved, it named an outstanding grant covering this decision.* A
        revocation or a ``clear`` landing before that read refuses the write — the
        fail-closed direction, and what a user who revokes expects. One landing
        between the read and the append does not, and ADR-0193 §9 states that
        window rather than rounding it to zero.

        **Expiry is decided against the decision's own ``decided_at``, never
        against a clock.** ``record`` reads none, exactly as ADR-0021 §4's "a
        resolution may not predate its confirmation" compares two recorded
        instants. The question is whether the grant was live **at the moment the
        ruling was made**, which is the only question about liveness a durable
        record answers identically on every later read: a grant that expires
        between the ruling and the write does not retract an honest ``ALLOW``, and
        an expired grant can never source a new one. The instant compared is one
        the *policy* does not supply — ADR-0021 §3 put ``decided_at`` in the caller
        that records precisely so — and the policy is the component this invariant
        defends against.

        **Revocation, by contrast, is decided at the resolution read**, because
        ``outstanding`` is a fact about two records and needs no clock, and because
        ordering a revocation against the decision's ``decided_at`` would be
        unsound: a revoking record's own instant is caller-supplied and may
        legitimately predate the grant it revokes.

        **The interval is closed below and open above**, and both ends are checked.
        Equality at the lower end is permitted — a coarse clock stamping a grant
        and the decision that spends it alike is an ordinary thing rather than a
        suspicious one. What the lower end refuses is a decision resting on a grant
        established **after** the ruling was made: not a stale authorisation but a
        **backdated** one, because the policy could not have read a record that did
        not exist when it ruled.

        **The digest is never taken on the decision's word.** It is recomputed here
        from the record ``outstanding`` returned and compared; an implementation
        that compared the decision's ``authorised_subject`` against itself, or
        against anything derived from the decision, has not implemented this
        clause.

        Args:
            decision: The validated snapshot about to be appended.

        **It returns the refusal rather than raising it**, so ``record`` applies it
        inside the modelled resource and after the duplicate-id checks — the
        ordering ``SqliteAuditTrail`` takes for the same reason.

        Returns:
            The refusal this decision has earned, or ``None`` where the pointer
            resolved to a grant covering it — and ``None`` too for every decision
            outside ADR-0193 §6's scope.

        Raises:
            InvalidAuthorisationError: If the seam could not be read. **Raised**
                rather than returned: a store fault is not something a later
                duplicate-id refusal should mask, because the two say different
                things to an operator and only one is about this decision. It is
                chained from the
                :class:`~ai_assistant.core.errors.RecipientGrantError` it came
                from, so a caller keeps the one ``AuditError`` handler while an
                operator keeps the two facts apart.
        """
        if not _names_a_standing_authorisation(decision):
            return None
        binding = decision.egress_binding
        # `_check_standing_shape` has already refused every other arm, and ran
        # before this method on both write paths. The narrowing is repeated for
        # `mypy`, which reads the union rather than the ordering.
        assert isinstance(binding, EgressBinding)  # noqa: S101 — narrowing, refused above
        named = str(decision.ruling.authorised_by)
        try:
            grant = await self._recipient_grants.outstanding(named)
        except RecipientGrantError as exc:
            msg = (
                f"decision {decision.id!r} names standing authorisation {named!r} and the "
                f"grant store could not be read, so nothing validated it; a component that "
                f"cannot get an answer from that seam fails closed (ADR-0193 §1, §6)"
            )
            raise InvalidAuthorisationError(msg) from exc
        if grant is None:
            return InvalidAuthorisationError(
                f"decision {decision.id!r} names standing authorisation {named!r}, which is "
                f"not an outstanding grant: it is absent, is a revoking record, or has been "
                f"revoked (ADR-0193 §6)"
            )
        return _grant_covers(decision, grant, binding)

    def _check_resolution(self, decision: PermissionDecision) -> None:
        """Enforce ADR-0021 §1 and ADR-0044 §2's invariant on a resolving decision.

        Raises:
            InvalidResolutionError: If the referenced decision is absent, was not
                a ``CONFIRM``, is already resolved, describes a different subject
                (including a different ``execution_id``, ADR-0044 §2a), postdates
                the answer, resolves a concrete binding a sibling already settled
                (ADR-0044 §2b), or if the authorisation pointer does not match.
        """
        confirmed = self._decisions.get(str(decision.resolves))
        if confirmed is None:
            msg = f"decision {decision.resolves!r} is not recorded, so nothing resolves it"
            raise InvalidResolutionError(msg)
        if confirmed.ruling.outcome is not PermissionOutcome.CONFIRM:
            msg = (
                f"decision {confirmed.id!r} ruled {confirmed.ruling.outcome}, not CONFIRM: "
                f"only a question the user was asked can be answered"
            )
            raise InvalidResolutionError(msg)
        if any(other.resolves == decision.resolves for other in self._decisions.values()):
            msg = (
                f"decision {confirmed.id!r} is already resolved; a confirmation answered "
                f"repeatedly is one where a 'no' can be followed by a 'yes' until one sticks"
            )
            raise InvalidResolutionError(msg)
        if (
            confirmed.tool != decision.tool
            or confirmed.parameters_digest != decision.parameters_digest
            or confirmed.step_id != decision.step_id
            or confirmed.execution_id != decision.execution_id
        ):
            msg = (
                f"decision {decision.id!r} resolves {confirmed.id!r} but rules on a "
                f"different action; a confirmation must answer the question that was asked"
            )
            raise InvalidResolutionError(msg)
        self._check_binding_undecided(decision)
        if decision.decided_at < confirmed.decided_at:
            msg = (
                f"decision {decision.id!r} is timestamped before the confirmation "
                f"{confirmed.id!r} it answers"
            )
            raise InvalidResolutionError(msg)
        self._check_authorisation(decision)

    def _check_binding_undecided(self, decision: PermissionDecision) -> None:
        """Refuse a resolution of a concrete binding a sibling already settled (§2b).

        Fires **only** when the resolving decision's ``execution_id`` and
        ``step_id`` are both present — a concrete ``(execution_id, step_id)``
        binding. ADR-0037 §2 accepts several unresolved ``CONFIRM``s under one
        binding (a compare-and-swap loser's ``CONFIRM`` stays recorded), and they
        are the same action, so they must share one fate: once *any* of them is
        resolved the binding is decided, and no second resolution — of that
        confirmation *or a sibling* — may be recorded. Layered *on top of* the
        per-confirmation ``resolves`` rule above, which alone would let a
        ``DENY``'d step keep an ``ALLOW``'d sibling orphan (the #257 window).

        A resolution's own ``(execution_id, step_id)`` equals its confirmation's
        (§2a and the ``step_id`` check enforce it at record time), so a recorded
        resolution sharing this binding *is* a prior resolution of it.

        Raises:
            InvalidResolutionError: If a resolution for this concrete binding is
                already recorded.
        """
        if decision.execution_id is None or decision.step_id is None:
            return
        prior = next(
            (
                other
                for other in self._decisions.values()
                if other.resolves is not None
                and other.execution_id == decision.execution_id
                and other.step_id == decision.step_id
            ),
            None,
        )
        if prior is not None:
            msg = (
                f"decision {decision.id!r} resolves the binding "
                f"({decision.execution_id!r}, {decision.step_id!r}), which decision "
                f"{prior.id!r} already settled; one step of one execution has one answer"
            )
            raise InvalidResolutionError(msg)

    @staticmethod
    def _check_authorisation(decision: PermissionDecision) -> None:
        """Require a resolving ALLOW to cite its own ``resolves``, and a DENY none.

        Without this the pointer is a string a policy could invent, and ADR-0021
        §5's disclosure floor would be satisfiable by fabrication.

        Raises:
            InvalidResolutionError: If the pointer does not match the outcome.
        """
        authorised_by = decision.ruling.authorised_by
        if decision.ruling.outcome is PermissionOutcome.ALLOW:
            if authorised_by != decision.resolves:
                msg = (
                    f"a resolving ALLOW must rest on the confirmation it answers: "
                    f"authorised_by={authorised_by!r}, resolves={decision.resolves!r}"
                )
                raise InvalidResolutionError(msg)
        elif authorised_by is not None:
            # Not reachable in this implementation: PermissionRuling permits
            # the field only on an ALLOW, and `record` revalidates before
            # getting here, so a corrupted ruling is refused at the model
            # boundary first. Kept
            # because the trail must not depend on another type's invariant to
            # hold a safety rule of its own.
            msg = f"a resolving {decision.ruling.outcome} rests on no authorisation"
            raise InvalidResolutionError(msg)

    async def pending_confirmation(
        self, *, execution_id: str, step_id: str
    ) -> PermissionDecision | None:
        """The confirmation this binding still awaits, or ``None`` (ADR-0044 §3).

        Two steps in order: if any ``CONFIRM`` for the binding is already
        resolved the binding is decided, so return ``None`` (never a still-
        unresolved sibling orphan — the #257 hazard §2b closes); otherwise return
        the newest unresolved ``CONFIRM`` by ``decided_at`` descending, ``id``
        ascending, or ``None`` if the binding carries none.
        """
        async with self._resource.held():
            confirms = [
                held
                for held in self._decisions.values()
                if held.ruling.outcome is PermissionOutcome.CONFIRM
                and held.execution_id == execution_id
                and held.step_id == step_id
            ]
            resolved = {other.resolves for other in self._decisions.values() if other.resolves}
        if any(confirm.id in resolved for confirm in confirms):
            return None
        if not confirms:
            return None
        by_id = sorted(confirms, key=lambda held: held.id)
        newest = sorted(by_id, key=lambda held: held.decided_at, reverse=True)[0]
        return newest.model_copy(deep=True)

    async def resolution_of(self, *, execution_id: str, step_id: str) -> PermissionDecision | None:
        """The recorded resolution of this binding's confirmation, or ``None`` (ADR-0059 §2).

        The complement of :meth:`pending_confirmation`: it returns the resolving
        decision (``resolves`` set) whose ``(execution_id, step_id)`` equals the
        binding — the ALLOW or DENY the binding already received. By ADR-0044 §2a a
        resolution's own binding equals its confirmation's, so a stored resolving
        decision sharing this binding *is* a resolution of one of its CONFIRMs; and
        by §2b the concrete binding carries at most one, so the match is unique. The
        result is always an ALLOW or a DENY — a resolving ``CONFIRM`` is
        unconstructable (``_a_resolution_is_not_itself_a_question``) — never a
        question. ``None`` means the binding carries no resolution; a dict read
        cannot fail, so ``None`` never stands in for an unreadable trail.
        """
        async with self._resource.held():
            resolution = next(
                (
                    held
                    for held in self._decisions.values()
                    if held.resolves is not None
                    and held.execution_id == execution_id
                    and held.step_id == step_id
                ),
                None,
            )
            return None if resolution is None else resolution.model_copy(deep=True)

    async def get(self, decision_id: str) -> PermissionDecision | None:
        """Return the decision with ``decision_id`` as a detached snapshot, or ``None``.

        Read inside the modelled resource, like every other read: the ``sqlite3``
        trail answers this from under its connection lock, so it is one of the lock
        sites ADR-0060's clause binds (#397).
        """
        async with self._resource.held():
            stored = self._decisions.get(decision_id)
            return None if stored is None else stored.model_copy(deep=True)

    async def recent(self, *, limit: int = 50) -> list[PermissionDecision]:
        """Return up to ``limit`` decisions, newest first, ties broken by id.

        Raises:
            ValueError: If ``limit`` is not strictly positive.
        """
        if limit <= 0:
            msg = f"limit must be strictly positive, got {limit}"
            raise ValueError(msg)
        async with self._resource.held():
            return [decision.model_copy(deep=True) for decision in self._ordered()[:limit]]

    async def export(self) -> list[PermissionDecision]:
        """Return every recorded decision, in the same order as :meth:`recent` (#397)."""
        async with self._resource.held():
            return [decision.model_copy(deep=True) for decision in self._ordered()]

    async def clear(self) -> int:
        """Delete every row of either kind, returning the number removed.

        **Both kinds, and the count is over both** (ADR-0192 §6). No operation
        erases one and leaves the other: "the user may burn the book; nobody may
        tear out a page" is a rule about one book. It erases the consume with
        everything else, so a decision re-recorded afterwards admits a claim —
        including a byte-for-byte identical one — and no generation, epoch or
        tombstone is minted to narrow that.

        The body runs inside the modelled resource for the reason :meth:`record`'s
        does — it is the second locked write, and ADR-0060's clause is stated per
        lock site — and for one of its own: the count returned must describe the
        deletion that actually happened. Sizing the dict outside the resource and
        emptying it inside would let a concurrent ``clear`` land between the two
        and let both callers report removing the same entries.

        Matches ``FakePlanStore.clear`` and ``FakeMemoryStore.clear``, which
        already model it this way (#396).
        """
        async with self._resource.held():
            removed = len(self._decisions) + len(self._invocations)
            self._decisions.clear()
            self._invocations.clear()
            self._completed.clear()
        return removed

    # --- the ledger: the consume, and the two appends (ADR-0192 §§1-2) ----

    async def claim_invocation(self, *, decision: PermissionDecision) -> ToolInvocation:
        """Append a claim under ``decision`` and return the stored row.

        The revalidation runs **before** the resource is entered, so the decision
        is observed once, before this call's first suspension point (ADR-0065);
        every refusal is then decided **inside** it, with no interleaving point
        before the append, which is how the atomicity ADR-0192 §1 requires is
        obtained on a single event loop. Two concurrent claims under one spendable
        decision therefore cannot both observe no prior claim.

        §1's equality is against the decision the ledger was **passed**, and that is
        why it is asked in two halves: ``passed == snapshot`` here, before the first
        suspension, and ``snapshot == stored`` inside the resource
        (:func:`_refuse_unless_as_passed`). The durable store composes it the same
        way and for the same reason.

        Raises:
            AuditError: If the decision is not a valid record, the guard rejects
                the clock's reading, or the redraw bound is spent.
            UnrecordedAuthorisationError: If the trail holds no decision under that
                id, holds one that is not equal to it, or holds one whose ruling is
                not ``ALLOW``.
            AuthorisationSpentError: If ADR-0192 §1's consume refuses.
        """
        snapshot = _revalidated_decision(decision)
        _refuse_unless_as_passed(snapshot, decision)
        async with self._resource.held():
            recorded = self._decisions.get(snapshot.id)
            if (
                recorded is None
                or recorded != snapshot
                or snapshot.ruling.outcome is not PermissionOutcome.ALLOW
            ):
                # One class for all three grounds: they are all "the authority this
                # call claims is not one this store recorded", and separating them
                # would tell a caller which half of a forgery was detected.
                msg = (
                    f"the trail records no decision equal to {snapshot.id!r}; an "
                    f"authorisation it did not record authorises nothing"
                )
                raise UnrecordedAuthorisationError(msg)
            # Read on first ask and never again, and deferred past every arm of
            # §1's conjunction that the store's own history settles: a clock the
            # ledger did not have to consult must not turn `AuthorisationSpentError`
            # into some other class (ADR-0192 §1, and the durable store's ordering).
            reading = _once(self._reading)
            self._refuse_if_spent(snapshot, reading)
            claim = ToolInvocation(id=self._mint(), decision_id=snapshot.id, recorded_at=reading())
            self._invocations[claim.id] = claim
            return claim.model_copy(deep=True)

    async def complete_invocation(
        self,
        *,
        claim_id: DurableIdentifier,
        outcome: ToolOutcome,
        incurred_cost: ToolCost,
        failure_kind: ToolFailureKind | None = None,
    ) -> ToolInvocation:
        """Append the completion of ``claim_id`` and return the stored row.

        Every argument is validated and detached **before** the resource is
        entered, for ADR-0065's reason and for ADR-0021 §4's: ``incurred_cost`` is
        the live object at the end of the chain that clause names, so a shallow
        copy would share it and ``cost.__dict__["amount"] = ...`` would rewrite an
        appended row.

        Raises:
            AuditError: If an argument is not valid — a ``failure_kind`` with a
                ``SUCCEEDED`` outcome among them — the guard rejects the clock's
                reading, or the redraw bound is spent.
            InvalidCompletionError: If ``claim_id`` names no recorded claim or
                names one a completion already names.
        """
        named = _checked_argument("claim_id", lambda: _identifier(claim_id))
        settled = _checked_argument("outcome", lambda: ToolOutcome(outcome))
        cost = _checked_argument("incurred_cost", lambda: _detached_cost(incurred_cost))
        kind = (
            None
            if failure_kind is None
            else _checked_argument("failure_kind", lambda: ToolFailureKind(failure_kind))
        )
        if kind is not None and settled is ToolOutcome.SUCCEEDED:
            msg = "a SUCCEEDED completion carries no failure_kind"
            raise AuditError(msg)
        async with self._resource.held():
            claim = self._invocations.get(named)
            if claim is None or claim.completes is not None:
                msg = f"the trail holds no open claim {named!r} to complete"
                raise InvalidCompletionError(msg)
            if named in self._completed:
                msg = (
                    f"claim {named!r} is already completed; the trail is append-only, "
                    f"so an outcome cannot be written twice"
                )
                raise InvalidCompletionError(msg)
            completion = ToolInvocation(
                id=self._mint(),
                # Set from the claim and never accepted from a caller (ADR-0192 §2).
                decision_id=claim.decision_id,
                recorded_at=self._reading(),
                completes=claim.id,
                outcome=settled,
                incurred_cost=cost,
                failure_kind=kind,
            )
            self._invocations[completion.id] = completion
            self._completed.add(claim.id)
            return completion.model_copy(deep=True)

    def _reading(self) -> datetime:
        """Take the append's one guarded clock reading (ADR-0026 §2).

        The guard's **own** rejection is translated, so a caller never meets a
        non-``AssistantError`` this trail produced; an exception the clock
        **callable itself** raises propagates unwrapped, type and cause intact.
        """
        try:
            return self._clock()
        except ClockReadingError as exc:
            msg = f"the audit trail's clock returned a reading it cannot record: {exc}"
            raise AuditError(msg) from exc

    def _mint(self) -> str:
        """Draw an identifier no row currently holds, or refuse (ADR-0192 §2).

        A collision is **drawn away from** rather than refused: after a restart the
        store holds claims a new, conforming, process-scoped factory may legally
        mint over, and an implementation refusing the first collision deadlocks
        there and on every subsequent restart. Only an exhausted bound refuses, and
        it is an ``AuditError`` and never one of §1's three named classes.

        The bound is the count of every row held, of either kind, plus one — over
        **one id space**, since a minted invocation id naming a *decision's* id is
        a collision like any other.
        """
        held = len(self._decisions) + len(self._invocations)
        for _ in range(held + 1):
            # Called outside the guard: an exception the factory callable raises on
            # its own account propagates unwrapped (ADR-0026 §2).
            drawn = self._identifiers()
            candidate = _checked_argument("identifier", functools.partial(_identifier, drawn))
            if candidate not in self._decisions and candidate not in self._invocations:
                return candidate
        msg = (
            f"the audit trail's identifier factory returned an identifier the store "
            f"already holds on every one of {held + 1} draws; no row was appended"
        )
        raise AuditError(msg)

    def _refuse_if_spent(self, decision: PermissionDecision, now: Callable[[], datetime]) -> None:
        """Apply ADR-0192 §1's conjunction to the claims already under ``decision``.

        ``now`` is invoked in the window arm alone, which is the only arm an instant
        decides — the durable store's ordering, and for its reason.

        Raises:
            AuthorisationSpentError: If a further claim is not admitted.
        """
        spendable = decision.tool.side_effecting and decision.tool.idempotency is not (
            Idempotency.NATURAL
        )
        if not spendable:
            # A read gated by ADR-0016 §3 is invoked under one ALLOW as often as
            # the pipeline needs it, and refusing the second would break working
            # behaviour to protect nothing.
            return
        rows = list(self._invocations.values())
        claims = [row for row in rows if row.completes is None and row.decision_id == decision.id]
        if not claims:
            return
        completions = {
            row.completes: row
            for row in rows
            if row.completes is not None and row.decision_id == decision.id
        }
        refuse = _spend_refusal(decision.id)
        if any(claim.id not in completions for claim in claims):
            raise refuse("a claim under it is open")
        settled = {completions[claim.id].outcome for claim in claims}
        if settled & {ToolOutcome.SUCCEEDED, ToolOutcome.INDETERMINATE}:
            raise refuse("an act under it has already succeeded or may have")
        last = completions[claims[-1].id]
        if last.outcome is not ToolOutcome.FAILED:
            raise refuse("its last act did not fail")
        if last.failure_kind is None or not last.failure_kind.retryable:
            raise refuse("its last failure reported no retryable kind")
        if decision.tool.idempotency is not Idempotency.KEYED:
            raise refuse("the tool offers no keyed idempotency")
        window = decision.tool.idempotency_window
        elapsed = now() - claims[0].recorded_at
        if window is None or elapsed <= timedelta(0) or elapsed >= window:
            # From the **first** claim in append order and never from the last:
            # measuring from the most recent one would renew the window
            # indefinitely, one retryable failure at a time.
            raise refuse("its idempotency window has lapsed")

    # --- reading what ran (ADR-0192 §2) -----------------------------------

    async def recent_invocations(self, *, limit: int = 50) -> list[RecordedInvocation]:
        """Return up to ``limit`` invocation rows, newest first, ties broken by id.

        Raises:
            ValueError: If ``limit`` is not strictly positive.
            AuditError: If the trail holds a row it could not pair with a decision.
        """
        if limit <= 0:
            msg = f"limit must be strictly positive, got {limit}"
            raise ValueError(msg)
        async with self._resource.held():
            return [self._join(row) for row in self._ordered_invocations()[:limit]]

    async def export_invocations(self) -> list[RecordedInvocation]:
        """Return every invocation row, in the same order as :meth:`recent_invocations`.

        Raises:
            AuditError: If the trail holds a row it could not pair with a decision.
        """
        async with self._resource.held():
            return [self._join(row) for row in self._ordered_invocations()]

    async def open_invocations(self, *, decision_id: DurableIdentifier) -> list[ToolInvocation]:
        """Every claim under ``decision_id`` that no completion names, in append order.

        The reservation is taken **inside** the resource, on the same boundary
        ``clear`` and every append take, and never after the read: an
        implementation reserving afterwards satisfies the sentence and loses the
        race — an erasure and a fresh claim can land in the gap, and the id it then
        reserves names the **new** claim (ADR-0192 §2).

        ``decision_id`` is read as the type the signature names, before the
        resource, exactly as the durable store reads it: ``Identifier`` strips, so
        looking the raw text up would answer "no open claims" for a decision holding
        one.

        Raises:
            AuditError: If ``decision_id`` is not a usable identifier.
        """
        named = _checked_argument("decision_id", lambda: _identifier(decision_id))
        async with self._resource.held():
            completed = {
                row.completes for row in self._invocations.values() if row.completes is not None
            }
            claims = [
                row
                for row in self._invocations.values()
                if row.completes is None and row.decision_id == named and row.id not in completed
            ]
            self._identifiers.reserve([claim.id for claim in claims])
            return [claim.model_copy(deep=True) for claim in claims]

    # --- the spend ceiling (ADR-0194) --------------------------------------

    def suspend_next_spend_read(self) -> LoopSuspension:
        """Hold the next admission open **after** it has snapshotted the rows.

        A second modelled resource, entered by the admission's read alone. The
        admission deliberately does not enter the one every other method uses
        (ADR-0194 §3): what it serialises is other *admissions*, so a completion
        appended by a call already in flight can land while it is reading — which
        is the interleaving §3's take-effect rule is written about and which one
        shared resource would make unreachable.

        The suspension is taken after the snapshot rather than before it, because
        the rule under test is that a release landing between an admission's row
        snapshot and its comparison must not be applied to that admission. Armed
        before the snapshot the case passes against an implementation that applies
        one.

        Test-only, and not part of either spend Protocol.

        Returns:
            The handle to wait on and release.
        """
        if self._spend_park is not None:
            msg = "a spend read is already armed on this fake"
            raise RuntimeError(msg)
        self._spend_park = LoopSuspension()
        return self._spend_park

    async def admit_invocation(self, *, estimate: ToolCost) -> SpendAdmissionHandle:
        """Admit this invocation and reserve its declared contribution, or refuse.

        Structurally implements
        :meth:`~ai_assistant.core.protocols.SpendGate.admit_invocation`.

        Raises:
            SpendCeilingError: If a configured ceiling would be crossed.
            SpendUndeterminedError: On ADR-0194 §4's six grounds, in that
                section's order.
        """
        if not self._books.bounded:
            # ADR-0194 §3's short-circuit: nothing is read, nothing is reserved,
            # and nothing can refuse.
            return self._books.mint(self._identifiers)
        contribution = self._books.declared(estimate)
        if isinstance(contribution, Unpriced):
            raise SpendUndeterminedError(_unmeasured(contribution.value))
        async with self._spend_lock:
            self._books.settle()
            instant = self._spend_reading()
            periods = self._spend_periods(instant)
            rows = await self._spend_read()
            measured = {bounds.period: measurable(bounds, rows, self._books) for bounds in periods}
            unmeasured = [
                period.value
                for period in SpendPeriod
                if measured[period] is None and self._books.ceiling(period) is not None
            ]
            if unmeasured:
                raise SpendUndeterminedError(
                    _unmeasured(f"these periods cannot be measured: {', '.join(unmeasured)}")
                )
            return self._reserve_or_refuse(periods, measured, contribution)

    def release_admission(self, handle: SpendAdmissionHandle) -> None:
        """Drop the reservation ``handle`` names. Never waits, never raises.

        Structurally implements
        :meth:`~ai_assistant.core.protocols.SpendGate.release_admission`. It takes
        no lock and enters no resource, so an invocation whose callable has
        returned never queues behind another invocation's read.
        """
        named = getattr(handle, "handle", None)
        if isinstance(named, str):
            self._books.retire(named)

    async def spend_totals(self) -> tuple[SpendTotal, ...]:
        """Return one total per period, in ``SpendPeriod``'s fixed order.

        Structurally implements
        :meth:`~ai_assistant.core.protocols.SpendLedger.spend_totals`. One clock
        reading and one row snapshot, so the pair is always one a snapshot could
        have produced; and no **admission** lock, since it reads no
        reservation and a totals read must never queue behind a wedged admission.
        It does enter the modelled resource a durable holder's connection lock
        stands for, for the length of the snapshot alone.

        Raises:
            SpendUndeterminedError: Only where an injected clock raised. A trapped
                sum leaves its own periods indeterminate instead of raising, and a
                dict has no backend read to fail.
        """
        instant = self._spend_reading()
        periods = self._spend_periods(instant)
        rows = await self._spend_read()
        priced = self._books.currency is not None
        return tuple(
            self._spend_total(bounds, measurable(bounds, rows, self._books) if priced else None)
            for bounds in periods
        )

    def _spend_reading(self) -> datetime:
        """Take the one guarded clock reading a spend decision is made on."""
        try:
            return self._clock()
        except Exception as exc:
            raise SpendUndeterminedError(_unmeasured(_CLOCK_RAISED)) from exc

    def _spend_periods(self, instant: datetime) -> tuple[Bounds, ...]:
        """Return both periods containing ``instant``, from that one reading."""
        try:
            return self._books.periods(instant)
        except (SpendTrapError, OverflowError, ValueError, OSError) as exc:
            # Not the clock ground: the clock already answered. ADR-0194 §1's
            # rule is total for every reading ``checked_clock`` accepts, so this is
            # unreachable and keeps §5's set closed against a defect in this
            # implementation's own arithmetic — §4's sixth ground.
            raise SpendUndeterminedError(_unmeasured(_ARITHMETIC_TRAPPED)) from exc

    async def _spend_read(self) -> Sequence[tuple[datetime, ToolCost | None, bool]]:
        """Take the snapshot, translating whatever it failed with.

        ADR-0194 §4's fourth ground and §5's closed ``Exception`` set: a backend
        failure is translated rather than propagated, so a caller never meets a
        store's own error type through this seam. A dict cannot fail on its own,
        but the seam owes the translation whether or not this subject can reach
        it — an implementation that only translated where it expected a failure
        would leak the one it did not.
        """
        try:
            return await self._spend_snapshot()
        except Exception as exc:
            raise SpendUndeterminedError(_unmeasured(_STORE_UNREADABLE)) from exc

    async def _spend_snapshot(self) -> Sequence[tuple[datetime, ToolCost | None, bool]]:
        """Snapshot every row, then model the read a durable store performs.

        The snapshot is taken **before** the resource is entered, so a suspension
        armed on it holds the admission at the one point ADR-0194 §3's take-effect
        rule is about: rows fixed, comparison not yet made.
        """
        async with self._resource.held():
            # Inside the resource a durable holder's connection lock stands for, so
            # this fake queues against an append exactly as that one does — and
            # releases it before the parking point below, because ADR-0194 §3
            # requires a completion to be able to land while an admission sits
            # between its row snapshot and its decision.
            completed = {
                row.completes for row in self._invocations.values() if row.completes is not None
            }
            taken = [
                (row.recorded_at, row.incurred_cost, row.id in completed)
                for row in self._invocations.values()
            ]
        parked, self._spend_park = self._spend_park, None
        if parked is not None:
            # Deliberately **not** a locked resource: a second spend read and an
            # append both have to be able to land while this one is parked, and a
            # parking point that held an exclusion would make the very interleaving
            # ADR-0194 §3 is about unreachable.
            await parked.hold()
        return taken

    def _reserve_or_refuse(
        self,
        periods: Sequence[Bounds],
        measured: Mapping[SpendPeriod, Sequence[Decimal] | None],
        contribution: Decimal,
    ) -> SpendAdmissionHandle:
        """Compare against every configured ceiling, then reserve and mint.

        Strictly above a ceiling refuses; exactly equal is admitted. The mint sits
        on the far side of the comparison, so a refusal consults the injected
        factory not at all — and a factory raising ``CancelledError`` cannot turn a
        refusal into a cancellation.
        """
        outstanding = self._books.standing()
        crossed: list[str] = []
        for bounds in periods:
            ceiling = self._books.ceiling(bounds.period)
            amounts = measured[bounds.period]
            if ceiling is None or amounts is None:
                continue
            try:
                accounted = add_exactly(amounts)
                projected = add_exactly([accounted, *outstanding, contribution])
            except SpendTrapError as exc:
                raise SpendUndeterminedError(_unmeasured(_ARITHMETIC_TRAPPED)) from exc
            if projected > ceiling:
                crossed.append(
                    f"{bounds.period.value}: {projected} projected against a ceiling of "
                    f"{ceiling} {self._books.currency}, with {accounted} accounted"
                )
        if crossed:
            raise SpendCeilingError(
                "the invocation was refused: it would cross a configured spend "
                f"ceiling — {'; '.join(crossed)}"
            )
        key = self._books.hold(contribution)
        try:
            handle = self._books.mint(self._identifiers)
        except BaseException:
            # No reservation nobody can release (ADR-0194 §3): a cancellation from
            # the factory propagates unchanged and does not strand one.
            self._books.drop(key)
            raise
        self._books.name(key, handle.handle)
        return handle

    def _spend_total(self, bounds: Bounds, amounts: Sequence[Decimal] | None) -> SpendTotal:
        """Build one period's ``SpendTotal``, indeterminacy included.

        ``currency`` discriminates the two absences: absent, no currency is
        configured and no sum was attempted; present, the period is indeterminate.
        A trapped sum lands in the second, because the other period's figure is
        still computable.
        """
        accounted: Decimal | None = None
        if self._books.currency is not None and amounts is not None:
            try:
                accounted = add_exactly(amounts)
            except SpendTrapError:
                accounted = None
        return SpendTotal(
            period=bounds.period,
            period_start=bounds.start,
            period_end=bounds.end,
            start_offset=bounds.start_offset,
            end_offset=bounds.end_offset,
            ceiling=self._books.ceiling(bounds.period)
            if self._books.currency is not None
            else None,
            currency=self._books.currency,
            accounted=accounted,
        )

    def _join(self, row: ToolInvocation) -> RecordedInvocation:
        """Pair ``row`` with the decision it names (ADR-0192 §2).

        Raises:
            AuditError: If the decision is absent — a row the store could not pair,
                reported rather than silently dropped.
        """
        named = self._decisions.get(row.decision_id)
        if named is None:
            msg = (
                f"the audit trail holds invocation {row.id!r} naming decision "
                f"{row.decision_id!r}, which it does not hold; the store is corrupt"
            )
            raise AuditError(msg)
        return RecordedInvocation(
            invocation=row.model_copy(deep=True),
            tool=named.tool.id,
            capability=named.tool.capability,
            egress_call=named.egress_binding is not None,
        )

    def _ordered_invocations(self) -> list[ToolInvocation]:
        """Return the stored rows by ``recorded_at`` descending, ``id`` ascending."""
        by_id = sorted(self._invocations.values(), key=lambda row: row.id)
        return sorted(by_id, key=lambda row: row.recorded_at, reverse=True)

    def _ordered(self) -> list[PermissionDecision]:
        """Return the stored decisions by ``decided_at`` descending, ``id`` ascending.

        Two passes over a stable sort rather than one composite key, because the
        two halves run in opposite directions and ``datetime`` has no negation.
        """
        by_id = sorted(self._decisions.values(), key=lambda decision: decision.id)
        return sorted(by_id, key=lambda decision: decision.decided_at, reverse=True)


#: ADR-0194 §4's grounds, as **fixed** text — never the caught exception
#: interpolated. A collaborator this seam distrusts may raise a value whose
#: ``__str__`` raises, and formatting it would leak that exception out of a member
#: §5 closes at two classes. The original is chained as ``__cause__``.
_CLOCK_RAISED: Final = "the injected clock raised"
_STORE_UNREADABLE: Final = "the store could not be read"
_ARITHMETIC_TRAPPED: Final = "the arithmetic trapped"


def _unmeasured(because: str) -> str:
    """Compose ADR-0194 §4's payload-free message for an unmeasurable spend.

    It names which ground applied and nothing about the call: no argument value,
    no recipient, no account, no tool output and no digest of any of them.
    """
    return f"the invocation was refused: the spend could not be reduced to a number — {because}"


def _once[T](read: Callable[[], T]) -> Callable[[], T]:
    """Wrap ``read`` so it runs on the first ask and hands back that value after.

    ADR-0192 §1's "exactly one guarded reading per append" as a property of the
    reading rather than of the call graph, so the reading can be deferred past every
    refusal that does not need it. The durable store carries the same helper.
    """
    taken: list[T] = []

    def _read() -> T:
        if not taken:
            taken.append(read())
        return taken[0]

    return _read


def _named_decision(given: object) -> str:
    """How a refusal names the decision it refuses, and never a way to raise from it.

    The id is the caller's value, on the caller's object, under a key the caller
    chose, and the message reporting the fault has to survive all three.
    ``isinstance`` consults ``__class__``, which can be a property that raises;
    ``__dict__`` can be one too; and ``__dict__.get("id")`` hashes ``"id"`` and then
    compares it against whatever collides with it, which can be a ``str`` subclass
    whose ``__eq__`` raises — reachable exactly where the genuine key has been
    deleted. So the id is found by a scan that hashes nothing and compares only keys
    that are *exactly* ``str`` (``_detachment._refuse_undeclared`` states that discipline in
    full), and the whole of it is guarded: a diagnostic that raises would replace the
    ``AuditError`` it is naming with whatever it threw, from inside the ``except``
    block that exists to report it.
    """
    try:
        if isinstance(given, PermissionDecision):
            for key, value in given.__dict__.items():
                if type(key) is str and key == "id":
                    return describe_untrusted(value)
    except Exception:  # the value cannot even be named; say so and carry on
        return "the given value"
    return "the given value"


def _refuse_unless_as_passed(snapshot: PermissionDecision, given: object) -> None:
    """Refuse unless ``snapshot`` is the decision that was passed (ADR-0192 §1).

    §1 decides the admission on "the decision it was **passed** ... the whole value,
    by the frozen model's own equality", and decides it *inside* the atomic
    operation. Re-reading the caller's object in there is what ADR-0065 forbids — it
    can change across the suspension the lock is — so the equality is composed of two
    halves instead: this call establishes ``passed == snapshot`` before the first
    ``await``, and the operation establishes ``snapshot == stored``. Together they are
    §1's clause, decided inside the operation over a value observed before any
    suspension point.

    This half is the one ``_detachment._refuse_undeclared`` cannot give. That refusal stops
    the rebuild **dropping** state; this one stops it **normalising** the value into a
    different one. A root subclass whose fields are all identical is unequal by the
    frozen model's own equality, and so is a ``list`` where the model declares a
    ``tuple``; either would otherwise be admitted as the decision the store holds.

    Nothing is refused here that the trail would not accept — a value the two clauses
    disagree about does not exist. It is *placed* here rather than in
    :func:`_revalidated` because ``record`` has no equality to keep: its obligation is
    on the declared type, which is why ``AuditTrailContract`` requires it to accept a
    caller's subclass and store a ``PermissionDecision``. §1's equality is an
    admission, and an admission is the ledger's.

    **The type test comes first and is by identity**, because Python gives a
    subclass's ``__eq__`` reflected priority: a caller's subclass would otherwise
    answer the question that decides its own admission. Once ``given`` is exactly a
    ``PermissionDecision`` the comparison is this model's own, over field values whose
    model types ``_detachment._refuse_undeclared`` has already fixed.

    **A comparison that raises is an argument fault rather than an admission.** A
    field can hold a ``str`` subclass whose ``__eq__`` raises, and this refusal must
    not leave as whatever that threw; §2's order is exhaustive over the classes a
    refusal arrives in. Nothing of the caller's is interpolated into the message for
    the same reason.

    Raises:
        AuditError: If the comparison cannot be made at all.
        UnrecordedAuthorisationError: If what was passed is not what the snapshot is,
            so no decision the store holds can be equal to it.
    """
    try:
        as_passed = type(given) is PermissionDecision and snapshot == given
    except Exception as exc:
        msg = (
            f"decision {snapshot.id!r} is not a valid record: it cannot be compared "
            f"with the value it was built from"
        )
        raise AuditError(msg) from exc
    if not as_passed:
        # One class and one message for every ground, as `_claim_sync`'s own two
        # have: they are all "the authority this call claims is not one this store
        # recorded", and separating them would tell a caller which half of a forgery
        # was detected (ADR-0192 §2).
        msg = (
            f"the trail records no decision equal to {snapshot.id!r}; an "
            f"authorisation it did not record authorises nothing"
        )
        raise UnrecordedAuthorisationError(msg)


def _detached_cost(value: ToolCost) -> ToolCost:
    """Rebuild ``value`` as a validated, detached :class:`ToolCost`.

    A raw, non-model value is validated rather than dereferenced, which is
    ``FakeToolInvoker._revalidated``'s ordering (ADR-0152 §1, "before reading any
    field of it"): ``value.model_dump()`` is a field read, so calling it first
    would let such a value escape as an ``AttributeError`` — neither ``AuditError``
    nor any class ADR-0192 §2's refusal order admits. The durable store has the
    identical guard at the identical place.

    Raises:
        ValidationError: If it is not a cost this trail can record.
    """
    return ToolCost.model_validate(field_state(ToolCost, value))


def _revalidated_decision(decision: PermissionDecision) -> PermissionDecision:
    """Rebuild ``decision`` as a validated, detached ``PermissionDecision``.

    A raw, non-model value is validated rather than dereferenced, on
    :func:`_detached_cost`'s ordering and for its reason: ADR-0192 §2's refusal
    order puts ``AuditError`` first "where an argument is not valid" and is
    exhaustive over the classes a refusal arrives in, and ``decision.model_dump()``
    on something that is not a decision raises ``AttributeError`` straight through
    it. The durable store guards the same argument the same way.


    **Every ordinary exception the read raises is caught, not only the ones a
    validator means to raise.** A value that is not a model at all reaches
    ``model_validate`` untouched (that is the ordering above), and validating a
    mapping walks it: a ``__getitem__`` that raises leaves as itself through a check
    that was about to refuse the value anyway. The whole read is a function of the
    caller's argument, so whatever it raises is a fault of that argument, and
    ADR-0192 §2's order is exhaustive over the classes a refusal arrives in.
    ``BaseException`` is deliberately not caught: a cancellation is not a fault of
    the argument and is never absorbed (ADR-0060 §1).

    Raises:
        AuditError: If it is not a valid record, or does not satisfy the model.
    """
    given: object = decision
    try:
        return PermissionDecision.model_validate(field_state(PermissionDecision, given))
    except Exception as exc:
        # `describe_untrusted` and never `repr`: the id is the caller's, and a
        # `__repr__` that raises would replace this `AuditError` with whatever it
        # threw — from inside the `except` block that exists to report it.
        named = _named_decision(given)
        # `describe_untrusted` on the cause as well as on the id. `field_state`
        # re-raises a `ValueError` the caller's own code raised, and a hostile
        # `__str__` on it would replace this `AuditError` with whatever it threw —
        # from inside the `except` block that exists to report it (ADR-0192 §2's
        # order is exhaustive over the classes a refusal arrives in).
        msg = f"decision {named} is not a valid record: {describe_untrusted(exc)}"
        raise AuditError(msg) from exc


#: The one validator for every identifier this fake is handed or is returned —
#: the *type*, not a hand-rolled likeness of it.
#:
#: An earlier version checked "text, and not blank" and returned the value
#: **unchanged**, which is not what :data:`DurableIdentifier` means:
#: :data:`~ai_assistant.core.types.Identifier` strips, so ``" x "`` and ``"x"`` are
#: one identifier to every model that holds one and were two to the check. A
#: factory returning both in turn passed the collision check twice and the second
#: row then overwrote the first under the stripped key — an append-only store
#: losing a row, and one durable id naming two acts, which is exactly what
#: ADR-0192 §2's single id space forbids. It also missed text with no UTF-8
#: encoding, which the type refuses and a ``.strip()`` cannot see. The durable
#: store validates through the same adapter (``permissions/audit.py``); a fake
#: that admits what the store refuses is not a stand-in for it.
_IDENTIFIER: Final[TypeAdapter[str]] = TypeAdapter(DurableIdentifier)


def _identifier(value: object) -> str:
    """Return ``value`` normalised as a ``DurableIdentifier``, else reject it.

    Raises:
        ValidationError: If it is not text, is blank, or has no UTF-8 encoding.
    """
    return _IDENTIFIER.validate_python(value)


def _checked_argument[T](name: str, build: Callable[[], T]) -> T:
    """Run ``build``, reporting a rejected value as this layer's own error.

    The guard-rejection arm of ADR-0026 §2: a non-conforming *output* is
    translated, while an exception a collaborator's callable raises on its own
    account is never routed through here.

    **Every ordinary exception, and not only the ones a validator means to raise.**
    ``build`` never does anything but check a value, and the value is the caller's,
    so whatever it raises is a fault of that value — including where the value is
    what makes the check itself fail: ``ToolOutcome(value)`` looks the member up in a
    mapping, so a ``str`` subclass whose ``__hash__`` raises leaves through a
    validator that never got to say no. ADR-0192 §2's order is exhaustive over the
    classes a refusal arrives in. ``BaseException`` is deliberately not caught: a
    cancellation is not a fault of the value and is never absorbed (ADR-0060 §1).
    The durable store carries the identical guard.

    Raises:
        AuditError: If ``build`` rejects the value.
    """
    try:
        return build()
    except Exception as exc:
        # `describe_untrusted` on the cause, for :func:`_revalidated`'s reason: the
        # value is the caller's, and so is any exception reading it raised.
        msg = f"the audit trail was given a {name} it cannot record: {describe_untrusted(exc)}"
        raise AuditError(msg) from exc


def _spend_refusal(decision_id: str) -> Callable[[str], AuthorisationSpentError]:
    """Build this decision's refusal, so every arm reads the same but for its cause."""

    def _refuse(because: str) -> AuthorisationSpentError:
        return AuthorisationSpentError(
            f"the authorisation recorded as {decision_id!r} is spent: {because}"
        )

    return _refuse


#: :class:`FakeAuditTrail` under the ledger faces' names (ADR-0192 §2). **One
#: object satisfies all three**, over one store, so the canonical fake is one class
#: and the composition a test writes is the composition production writes:
#: ``FakeInvocationLedger`` for the seam, ``FakeInvocationCompleter`` for recovery,
#: and the trail itself for the reads. It is the arrangement
#: :data:`~ai_assistant.testing.secrets.FakeSecrets` already has for
#: ``Secrets``/``SecretStore``, which ADR-0192 §2 names as its precedent.
FakeInvocationLedger = FakeAuditTrail

#: :class:`FakeAuditTrail` under the narrow face's name — the one ``orchestration``'s
#: recovery scan is handed, which cannot express a claim at all.
FakeInvocationCompleter = FakeAuditTrail

#: :class:`FakeAuditTrail` under the spend faces' names (ADR-0194 §5). **One
#: object implements ``SpendGate``, ``SpendLedger`` and ADR-0192's ledger seam**,
#: because all three read the same rows — two stores keyed by the same rows could
#: disagree about a total. So the aliases name the faces the composition root
#: hands out, exactly as the two ledger names above do: ``FakeSpendGate`` for the
#: invoker, ``FakeSpendLedger`` for the engine's read.
FakeSpendGate = FakeAuditTrail

#: :class:`FakeAuditTrail` under the totals face's name — the one an adapter
#: holds, and never the gate (ADR-0194 §5).
FakeSpendLedger = FakeAuditTrail


__all__ = [
    "FakeActionPolicy",
    "FakeAuditTrail",
    "FakeIdentifierSpace",
    "FakeIdentifiers",
    "FakeInvocationCompleter",
    "FakeInvocationLedger",
    "FakeSpendGate",
    "FakeSpendLedger",
    "MintsIdentifiers",
]
