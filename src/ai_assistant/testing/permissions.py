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

import functools
import itertools
import os
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Final, Protocol, get_args, runtime_checkable
from uuid import uuid4

from pydantic import BaseModel, TypeAdapter, ValidationError

from ai_assistant.core.clock import ClockReadingError, checked_clock
from ai_assistant.core.errors import (
    AuditError,
    AuthorisationSpentError,
    DuplicateDecisionError,
    InvalidCompletionError,
    InvalidResolutionError,
    UnrecordedAuthorisationError,
)
from ai_assistant.core.types import (
    CostBasis,
    DurableIdentifier,
    Idempotency,
    OriginUnrecordedBinding,
    PermissionDecision,
    PermissionOutcome,
    PermissionRuling,
    RecordedInvocation,
    Reversibility,
    RiskLevel,
    ToolCost,
    ToolFailureKind,
    ToolInvocation,
    ToolOutcome,
    describe_untrusted,
)
from ai_assistant.testing.cancellation import SuspendableResource

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator

    from ai_assistant.core.types import ActionRequest
    from ai_assistant.testing.cancellation import LoopSuspension, ResourceLog

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

        **ADR-0184 §7's floor is the one clause that does need a branch here**, and
        it is the only case where an approval is not enough: where
        ``confirmed.egress_binding`` records no origin — an
        :class:`~ai_assistant.core.types.OriginUnrecordedBinding`, which only a row
        written before ADR-0181 can carry — no ``ALLOW`` is returned whatever
        ``approved`` says, because the origin of such a call cannot be established
        at all and ADR-0181 §5's second clause leaves no route by which any
        authorisation covers it. Nothing in the tree hands one here; it is a floor,
        written because a floor's value is that it holds when a route appears.
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

    def __init__(
        self,
        *,
        now: Callable[[], datetime] = _fake_now,
        identifiers: MintsIdentifiers | None = None,
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
        """
        self._decisions: dict[str, PermissionDecision] = {}
        # Insertion order **is** the durable append order every admission rule in
        # ADR-0192 §1 is decided on — deliberately not an ordering over
        # ``recorded_at``, so a clock that steps backwards cannot make a completed
        # act stop being the most recent one.
        self._invocations: dict[str, ToolInvocation] = {}
        self._clock = checked_clock(now, owner="FakeAuditTrail")
        self._identifiers: MintsIdentifiers = (
            identifiers if identifiers is not None else FakeIdentifiers()
        )
        self._resource = SuspendableResource()

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
        (:func:`_refuse_undeclared`). Reading ``decision.model_dump()`` here would
        also let an overridden method decide what is stored, which is the hazard
        that helper exists for.

        **A decision whose ``egress_binding`` records no origin is refused**
        (ADR-0184 §4), and it is the one refusal the model cannot make for itself:
        an :class:`~ai_assistant.core.types.OriginUnrecordedBinding` is a *valid*
        member of a ``PermissionDecision``, because it has to be for a stored row to
        decode into one. It represents a row from an epoch that has ended, so it is
        only ever read out of a store and never minted into one — a caller bypassing
        ``from_request`` could otherwise append one and fabricate history rather
        than a value. This fake holds objects rather than bytes and so cannot be
        seeded with such a row at all, which is why the read half of ADR-0184 §5 is
        pinned in ``SqliteAuditTrail``'s own tests while *this* clause is in the
        shared conformance suite.

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
                an ``OriginUnrecordedBinding``. Raised
                as an ``AuditError`` rather than letting pydantic's
                ``ValidationError`` escape, because CONTRIBUTING has this layer
                raise only from the ``AssistantError`` hierarchy — a caller
                handling "the trail would not accept this" should not need a
                second handler for the shape of the refusal.
            DuplicateDecisionError: If the id is already recorded.
            InvalidResolutionError: If ``resolves`` fails the invariant.
        """
        snapshot = _revalidated_decision(decision)
        if isinstance(snapshot.egress_binding, OriginUnrecordedBinding):
            msg = (
                f"decision {decision.id!r} is not a valid record: its egress binding "
                f"records no origin, which is a shape only a row written before "
                f"ADR-0181 can have; the trail reads such rows and never writes one"
            )
            raise AuditError(msg)
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
            if snapshot.resolves is not None:
                self._check_resolution(snapshot)
            self._decisions[snapshot.id] = snapshot
        return snapshot.id

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

        Raises:
            AuditError: If the decision is not a valid record, the guard rejects
                the clock's reading, or the redraw bound is spent.
            UnrecordedAuthorisationError: If the trail holds no decision under that
                id, holds one that is not equal to it, or holds one whose ruling is
                not ``ALLOW``.
            AuthorisationSpentError: If ADR-0192 §1's consume refuses.
        """
        snapshot = _revalidated_decision(decision)
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
            if any(row.completes == named for row in self._invocations.values()):
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


def _field_state(kind: type[BaseModel], given: object) -> Any:
    """The declared field values of ``given``, read by ``kind``'s **own** serializer.

    ``given.model_dump()`` is an ordinary attribute: a subclass can override the
    method and an instance can shadow it through ``__dict__``, and either can return
    a valid-but-false mapping. Everything downstream then rebuilds *that* — so the
    equality check ``claim_invocation`` runs would compare the store's row against a
    decision the caller never held, and a completion would record a cost nobody
    submitted. ``orchestration/executor.py`` states the same reasoning for
    ``ToolResult`` and is the precedent this follows: the class serializer is
    resolved on the class, reads the instance's field values, and consults no
    instance attribute.

    A value that is not a ``kind`` at all is handed back untouched, for
    ``model_validate`` to refuse — nothing is read off it here (ADR-0152 §1's
    ordering).

    **Anything the serializer would silently drop is refused instead**, which is
    :func:`_refuse_undeclared`'s whole subject and is what makes the value this
    returns rebuild into a model equal to the one that was passed.

    ``warnings=False`` because a ``__dict__``-tampered enum serialises with a
    ``PydanticSerializationUnexpectedValue`` warning that is noise here; the
    ``model_validate`` downstream is what rejects it.

    Raises:
        ValueError: If ``given`` carries state ``kind`` declares no field for, or a
            model-valued field anywhere beneath it holds something other than
            exactly its declared type.
    """
    if not isinstance(given, kind):
        return given
    _refuse_undeclared(kind, given)
    return kind.__pydantic_serializer__.to_python(given, warnings=False)


def _refuse_undeclared(kind: type[BaseModel], given: BaseModel) -> None:
    """Refuse state ``kind`` does not declare, on ``given`` and beneath it.

    Two refusals serving one rule — **what is stored is what was handed over, or
    nothing is** — because either kind of state would otherwise be dropped in
    silence by the class serializer :func:`_field_state` reads the value with.

    *State the class declares no field for* sits on the value itself: a subclass's
    extra field, or anything written straight into ``__dict__``. Refusing it keeps
    the guarantee the declared type already carries.

    *A model-valued field holding something other than exactly its declared type* is
    the same loss one level down, and it arrives through a **normally constructed**
    value rather than a tampered one. ``PermissionDecision.tool`` is declared a
    ``ToolDefinition``, and pydantic's default ``revalidate_instances="never"`` keeps
    whatever instance the caller passed — so a ``ToolDefinition`` subclass carrying a
    field of its own survives validation. ``PermissionDecision``'s serializer then
    emits the *declared* fields of it and drops that one, and the snapshot rebuilt
    from the mapping compares **equal** to a decision the caller never held. That is
    ADR-0192 §1's own attack shape: an ``ALLOW`` the trail recorded would admit a
    claim under a tool carrying state it never approved, where §1 requires the
    decision the ledger was *passed* to equal the one the store holds under that id —
    "the whole value, by the frozen model's own equality". Refusing here makes
    ``snapshot == passed`` true *by construction*, so the equality
    ``claim_invocation`` runs over the snapshot **is** the equality §1 asks for.

    Both alternatives are worse. Comparing the caller's live object inside the lock
    satisfies §1 literally and re-reads the decision after a suspension point, which
    ADR-0065 forbids and
    ``test_the_submitted_decision_is_observed_before_the_first_await`` exists to
    catch. Carrying the nested subclass's own state through the snapshot would store
    what ``ToolDefinition``'s ``extra="forbid"`` refuses — a record the type says
    cannot exist. ``record`` reaches this helper too and is tightened in the same
    direction by the same clause: what the trail stores is what it was given.

    The refusal is on the *type* and not on whether this particular subclass happens
    to declare a field of its own, because the second is a property of the class a
    caller supplies and the first is the contract.

    **Nothing here hashes or compares a key or a class the caller controls.** A
    model's ``__dict__`` is annotated ``dict[str, Any]`` and nothing enforces it at
    runtime, so a key can be any hashable object at all — including one whose
    ``__hash__`` collides with a field name and whose ``__eq__`` raises on the
    comparison that collision provokes. Building a ``set`` of the keys, or asking
    ``key in declared`` of a non-``str``, walks straight into it and this refusal
    leaves as whatever that ``__eq__`` threw. A caller's *class* is the same hazard
    through its metaclass, so the type test below is by identity rather than by
    membership. So: iterate (which hashes nothing), classify anything that is not
    *exactly* ``str`` as undeclared without touching it, and only then ask a real
    ``str`` — whose hash and equality are the interpreter's — whether it names a
    field.

    The one recursion descends the **declared** model graph, because a value of any
    other type is refused rather than followed; it is therefore bounded exactly as
    the serializer over the same value is. Containers are walked with an explicit
    stack instead (:func:`_models_within`), their depth being the caller's to choose.

    Raises:
        ValueError: If ``given`` carries state ``kind`` declares no field for, or a
            model-valued field beneath it holds something other than exactly its
            declared type.
    """
    declared = set(kind.model_fields)
    undeclared = [key for key in given.__dict__ if type(key) is not str or key not in declared]
    if undeclared:
        # Described *before* sorting, and described by
        # :func:`~ai_assistant.core.types.describe_untrusted`. Sorting the keys
        # directly raises ``TypeError`` the moment two of them are of different
        # types, and ``repr`` on one can raise anything at all — either way the
        # diagnostic would destroy the diagnosis and this refusal would leave as a
        # class ADR-0192 §2's order does not admit. Sorting the *descriptions*
        # keeps the message deterministic and cannot raise.
        named = sorted(describe_untrusted(key) for key in undeclared)
        msg = f"the value carries state {kind.__name__} has no field for: {named}"
        raise ValueError(msg)
    for name, value in given.__dict__.items():
        admits = _declared_models(kind.model_fields[name].annotation)
        for nested in _models_within(value):
            held = type(nested)
            if not any(held is each for each in admits):
                shown = ", ".join(sorted(each.__name__ for each in admits))
                msg = (
                    f"the value's {name!r} field declares {shown or 'no model'} and "
                    f"holds {describe_untrusted(held)}: a value of another type "
                    f"would be recorded as less than it is"
                )
                raise ValueError(msg)
            _refuse_undeclared(held, nested)


def _declared_models(annotation: object) -> tuple[type[BaseModel], ...]:
    """Every model class ``annotation`` admits, flattened out of unions and containers.

    ``get_args`` unwraps ``X | None``, ``tuple[X, ...]`` and ``Annotated[X, ...]``
    alike, so one walk covers every shape a field of these models is declared with.
    Anything that is not a model class contributes nothing, which is the right
    answer: a field declaring no model admits none.

    Flattened rather than positional. Whether a model sits in the arm of the
    annotation it was put in is ``model_validate``'s question and it refuses one that
    does not; the only question here is whether a value would be recorded as less
    than it is, and every class named anywhere in the annotation serialises whole.
    """
    found: list[type[BaseModel]] = []
    pending: list[object] = [annotation]
    while pending:
        item = pending.pop()
        if isinstance(item, type) and issubclass(item, BaseModel):
            found.append(item)
            continue
        pending.extend(get_args(item))
    return tuple(found)


def _models_within(value: object) -> Iterator[BaseModel]:
    """Every model instance ``value`` is or holds inside a plain container.

    Iterative rather than recursive: a container's nesting depth is the caller's to
    choose, and a ``RecursionError`` is neither ``ValueError`` nor any class
    ADR-0192 §2's refusal order admits. A container that refuses to be iterated
    raises here exactly as it would inside the serializer one call later, so this
    walk widens nothing that can leave.
    """
    pending: list[object] = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, BaseModel):
            yield item
        elif isinstance(item, list | tuple | set | frozenset):
            pending.extend(item)
        elif isinstance(item, dict):
            pending.extend(item.values())


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
    return ToolCost.model_validate(_field_state(ToolCost, value))


def _revalidated_decision(decision: PermissionDecision) -> PermissionDecision:
    """Rebuild ``decision`` as a validated, detached ``PermissionDecision``.

    A raw, non-model value is validated rather than dereferenced, on
    :func:`_detached_cost`'s ordering and for its reason: ADR-0192 §2's refusal
    order puts ``AuditError`` first "where an argument is not valid" and is
    exhaustive over the classes a refusal arrives in, and ``decision.model_dump()``
    on something that is not a decision raises ``AttributeError`` straight through
    it. The durable store guards the same argument the same way.

    Raises:
        AuditError: If it is not a valid record, or does not satisfy the model.
    """
    given: object = decision
    try:
        return PermissionDecision.model_validate(_field_state(PermissionDecision, given))
    except (ValidationError, ValueError) as exc:
        # `describe_untrusted` and never `repr`: the id is the caller's, and a
        # `__repr__` that raises would replace this `AuditError` with whatever it
        # threw — from inside the `except` block that exists to report it.
        named = (
            describe_untrusted(given.__dict__.get("id"))
            if isinstance(given, PermissionDecision)
            else "the given value"
        )
        msg = f"decision {named} is not a valid record: {exc}"
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

    Raises:
        AuditError: If ``build`` rejects the value.
    """
    try:
        return build()
    except (ValidationError, ValueError) as exc:
        msg = f"the audit trail was given a {name} it cannot record: {exc}"
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


__all__ = [
    "FakeActionPolicy",
    "FakeAuditTrail",
    "FakeIdentifierSpace",
    "FakeIdentifiers",
    "FakeInvocationCompleter",
    "FakeInvocationLedger",
    "MintsIdentifiers",
]
