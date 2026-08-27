"""Canonical fakes for the two routing Protocols (ADR-0197 §9, §12).

Both halves of the routing seam, and both are owed a full triad in the change that
adds them: :class:`FakeRoutingRecorder` for the **write** seam ADR-0197 §2's routing
stage holds, and :class:`FakeRoutingTrail` for the durable store a future hub-owned
read surface will hold (§11). Neither is an internal seam of ``permissions/``.

**The two fakes model one store between them**, exactly as the source-read pair and
the grant pair do. A composition root passes one concrete object to the stage's
``RoutingRecorder`` parameter and to a ``RoutingTrail`` one, so
``tests/permissions/test_fake_routing.py`` binds the *trail* fake to the recorder
suite as well — turning ADR-0197 §9's "one concrete store satisfies them" from an
assertion into a test, which is what §12's second Normative asks for in as many
words.

**The narrow fake carries no read member and no** ``clear``, and that is the property
under test rather than an economy. ADR-0185 §4's split removed the ability to *read*
from the driver's type; here it removes the same capability **plus** ``clear``,
because a routing stage handed the whole trail could erase the record of its own
decisions. What the narrow fake offers instead is
:attr:`FakeRoutingRecorder.written`, a *test author's* lever with a name no production
caller would reach for.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final, final
from uuid import uuid4

from pydantic import ValidationError

from ai_assistant.core.errors import RoutingTrailError
from ai_assistant.core.types import (
    RoutableOperation,
    RouteApproval,
    RoutedOperationRecord,
)
from ai_assistant.testing.cancellation import LoopSuspension, ResourceLog, SuspendableResource

if TYPE_CHECKING:
    from collections.abc import Sequence

#: The instant :func:`routed_operation_record` stamps when the caller does not. Fixed
#: rather than "now", so a record built in a test is the same record on every run
#: (ADR-0026 §2's posture applied to a fixture).
DEFAULT_DECIDED_AT: Final = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)

#: The conversation a :func:`routed_operation_record` names when the caller does not.
#: A plain identifier rather than a real conversation's id: ADR-0197 §9 makes the
#: pointer one-way, so a ``conversation_id`` naming a conversation no store holds is
#: legible history rather than corruption.
DEFAULT_CONVERSATION_ID: Final = "conversation-1"

#: The exclusive upper bound ADR-0197 §9 puts on the cap, inherited from ADR-0185 §6:
#: "every strictly positive integer below ``2**63``", which is ``Settings``' own
#: ``lt=2**63``. A list could hold more; the durable store cannot bind more, and a
#: fake that diverged here would admit a configuration no deployment can produce.
MAX_ROWS_EXCLUSIVE: Final = 2**63

#: The cap both fakes hold when a caller states none — ``Settings``' own default
#: (ADR-0197 §9), so an unconfigured fake behaves like an unconfigured deployment and
#: a test that wants the prune has to ask for it.
DEFAULT_MAX_ROWS: Final = 200_000

#: The widest ``limit`` :meth:`FakeRoutingTrail.recent` admits, exclusive. ADR-0186 §3
#: requires every bounded listing to refuse a ``limit`` outside ``[1, 2**63)``
#: **locally and before any I/O**, and the fake refuses it though a list could serve
#: it: a consumer's test must not pass against a bound no durable store can bind.
MAX_LIMIT_EXCLUSIVE: Final = 2**63

#: The answers a route may end on (ADR-0197 §9). Named once so the state machine
#: below reads as the rule rather than as two member comparisons repeated.
_ANSWERS: Final[frozenset[RouteApproval]] = frozenset({RouteApproval.GIVEN, RouteApproval.REFUSED})


def _mint() -> str:
    """A fresh row id, minted by the caller as ADR-0197 §9 requires of every row."""
    return f"routed-{uuid4().hex}"


def routed_operation_record(  # noqa: PLR0913 — an operation, a row id, a route id, an instant, an approval, a subject and a conversation; each is one field of the row a caller may want to name
    operation: RoutableOperation = RoutableOperation.FORGET,
    *,
    record_id: str | None = None,
    route_id: str = "route-1",
    decided_at: datetime = DEFAULT_DECIDED_AT,
    approval: RouteApproval | None = None,
    subject: str | None = "belief-1",
    conversation_id: str | None = DEFAULT_CONVERSATION_ID,
) -> RoutedOperationRecord:
    """Build one :class:`~ai_assistant.core.types.RoutedOperationRecord` for a test.

    Args:
        operation: Which operation the route named.
        record_id: The row's own id; a fresh mint when omitted.
        route_id: The route this row belongs to. A constant by default, so the common
            case — two rows of one confirm-owed route — needs no argument at all.
        decided_at: When this decision was taken.
        approval: What was decided about the user's approval. ``None`` **derives** it
            from ``operation``'s tag rather than meaning "nothing was decided":
            :attr:`~ai_assistant.core.types.RouteApproval.NOT_OWED` on a read-only
            operation and :attr:`~ai_assistant.core.types.RouteApproval.OWED` on a
            confirm-owed one, which are the two a *first* row may carry. A caller
            wanting an incoherent pairing — to assert the model refuses it — builds
            the record directly, because this helper exists to make the coherent case
            cheap.
        subject: The scalar identity the façade was called with. ``None`` where the
            operation takes none, which is every read-only member.
        conversation_id: The conversation the ask ran under, or ``None``.

    Returns:
        The record, validated by its own model.
    """
    return RoutedOperationRecord(
        id=_mint() if record_id is None else record_id,
        route_id=route_id,
        decided_at=decided_at,
        operation=operation,
        approval=_default_approval(operation) if approval is None else approval,
        subject=subject if operation.confirm_owed else None,
        conversation_id=conversation_id,
    )


def _default_approval(operation: RoutableOperation) -> RouteApproval:
    """The approval a *first* row of ``operation``'s route may carry (ADR-0197 §9)."""
    return RouteApproval.OWED if operation.confirm_owed else RouteApproval.NOT_OWED


def _snapshot(record: RoutedOperationRecord) -> RoutedOperationRecord:
    """Rebuild ``record`` as a validated, detached :class:`RoutedOperationRecord`.

    ADR-0021 §4's "detached, validated snapshot" applied to this store, on
    ``FakeSourceReadTrail``'s reasoning: a copy alone detaches without checking, so a
    record corrupted past its frozen model's guard — a ``decided_at`` written back as
    naive, or a read-only operation given a ``GIVEN`` approval — would be stored and
    then make every later read of the trail incoherent.

    Rebuilt as a ``RoutedOperationRecord`` specifically rather than as
    ``type(record)``: a caller's subclass could override ``model_copy`` to return
    ``self``, and storing that instance would hand every later read this store's own
    object.

    Raises:
        RoutingTrailError: If the record does not satisfy its own model. Raised from
            this seam's own class rather than letting pydantic's ``ValidationError``
            escape, because a caller handling "the trail would not accept this" should
            not need a second handler for the shape of the refusal.
    """
    try:
        return RoutedOperationRecord.model_validate(record.model_dump())
    except ValidationError as exc:
        msg = f"routed operation {record.id!r} is not a valid record: {exc}"
        raise RoutingTrailError(msg) from exc


class _RoutingLog:
    """The append-only list both fakes keep, with ADR-0197 §9's checks and prune.

    Private and shared, for :mod:`ai_assistant.testing.reads`' reason: the invariants
    are the *store's* rather than either seam's, and two copies would be two places
    for them to drift.
    """

    def __init__(self, *, max_rows: int) -> None:
        """Create an empty log bounded at ``max_rows`` rows.

        Args:
            max_rows: The cap, strictly positive and below ``2**63``.

        Raises:
            TypeError: If ``max_rows`` is not exactly an ``int``. ``bool`` is an
                ``int``, so ``True`` would otherwise be a cap of one — a flag loaded
                where a count belongs, which is what ``Settings``' own
                ``_exactly_an_integer`` refuses at load.
            ValueError: If ``max_rows`` is not strictly positive, or is not below
                ``2**63``.
        """
        if type(max_rows) is not int:
            msg = (
                f"the routing trail's cap must be exactly an int, got {max_rows!r} of type "
                f"{type(max_rows).__name__}; a bool passes every comparison below while "
                f"meaning a cap of one (ADR-0197 §9)"
            )
            raise TypeError(msg)
        if not 0 < max_rows < MAX_ROWS_EXCLUSIVE:
            msg = (
                f"the routing trail's cap must be strictly positive and below 2**63, got "
                f"{max_rows}; there is no unlimited spelling and no zero (ADR-0197 §9)"
            )
            raise ValueError(msg)
        self._max_rows = max_rows
        self._rows: list[RoutedOperationRecord] = []

    def append(self, record: RoutedOperationRecord) -> None:
        """Check, append and prune, as one uninterrupted sequence (ADR-0197 §9).

        The id check, the ``route_id`` check, the state machine, the append and the
        prune are separated by no ``await``, which is how the atomicity §9 requires is
        obtained on a single event loop.

        Raises:
            RoutingTrailError: If the record is invalid, if its id is held under a
                differing record, if its ``route_id`` is held by a retained row of
                another route, or if the sequence is one the state machine does not
                admit.
        """
        snapshot = _snapshot(record)
        held = next((row for row in self._rows if row.id == snapshot.id), None)
        if held is not None:
            if held == snapshot:
                # Idempotent over the **whole** record, never over the id alone: a
                # retried write appends nothing and is not an error, while a repeating
                # id factory carrying a different decision is refused (ADR-0197 §9).
                return
            msg = (
                f"routed operation row {snapshot.id!r} is already recorded with different "
                f"content; the trail is append-only, so history cannot be rewritten by "
                f"replaying a write, and the act this row precedes does not proceed"
            )
            raise RoutingTrailError(msg)
        self._check_route(snapshot)
        self._rows.append(snapshot)
        # Oldest-recorded first, uniformly and blind to every field of the row
        # (ADR-0197 §9). An unanswered park's OWED row is pruned at the bound like any
        # other, and pruning it neither evicts the park nor releases its slot nor
        # makes its token unresolvable: the park is the state and this is the record.
        if len(self._rows) > self._max_rows:
            del self._rows[: len(self._rows) - self._max_rows]

    def _check_route(self, snapshot: RoutedOperationRecord) -> None:
        """Enforce ADR-0197 §9's ``route_id`` rule over the rows this log **retains**.

        Never a fact about a park this store is not the authority for: an answer
        arriving under a ``route_id`` retaining **no** row is accepted, and no ``OWED``
        row is required to admit one. That is forced by the bound — pruning is by
        recording order alone, so a live park's ``OWED`` row can be pruned while the
        park is still registered and still claimable, and requiring the row would make
        a *retention* setting decide whether a user's approval of a live confirmation
        is honoured.

        Raises:
            RoutingTrailError: If a retained row of this route disagrees about what the
                route is, or if the sequence is one a route cannot take.
        """
        siblings = [row for row in self._rows if row.route_id == snapshot.route_id]
        if not siblings:
            return
        for row in siblings:
            if (row.operation, row.subject, row.conversation_id) != (
                snapshot.operation,
                snapshot.subject,
                snapshot.conversation_id,
            ):
                msg = (
                    f"route {snapshot.route_id!r} is already held by a retained row about "
                    f"{row.operation.value} on {row.subject!r}; filing two decisions as one "
                    f"route would join a destructive act to an authorisation nobody gave it"
                )
                raise RoutingTrailError(msg)
        held = {row.approval for row in siblings}
        if RouteApproval.NOT_OWED in held or snapshot.approval is RouteApproval.NOT_OWED:
            msg = (
                f"route {snapshot.route_id!r} is a read-only route and is exactly one "
                f"NOT_OWED row; a second row of any kind under it — an answer included — "
                f"is refused (ADR-0197 §9)"
            )
            raise RoutingTrailError(msg)
        if snapshot.approval is RouteApproval.OWED and RouteApproval.OWED in held:
            msg = (
                f"route {snapshot.route_id!r} already retains an OWED row; one question was "
                f"put to the user, so a second would be two questions filed as one"
            )
            raise RoutingTrailError(msg)
        if snapshot.approval in _ANSWERS and held & _ANSWERS:
            answered = next(iter(held & _ANSWERS))
            msg = (
                f"route {snapshot.route_id!r} was already answered {answered.value}; a trail "
                f"holding two answers to one question states two incompatible claims about "
                f"what one person decided (ADR-0197 §9)"
            )
            raise RoutingTrailError(msg)

    def recording_order(self) -> list[RoutedOperationRecord]:
        """Every row held, oldest-recorded first, as **detached** copies.

        ADR-0018 §3's read-path rule, which a fake holding objects has to keep by hand
        where a serialising store gets it for free: ``frozen=True`` refuses
        ``row.approval = …`` and not ``row.__dict__["approval"] = …``, so handing back
        the stored instances would let a reader rewrite an append-only row through the
        very call that reports it.
        """
        return [row.model_copy() for row in self._rows]

    def clear(self) -> None:
        """Drop every row."""
        self._rows.clear()


@final
class FakeRoutingRecorder:
    """A ``RoutingRecorder`` test double: it writes, and answers nothing.

    Structurally implements
    :class:`~ai_assistant.core.protocols.RoutingRecorder`, and structurally **fails**
    :class:`~ai_assistant.core.protocols.RoutingTrail` — which is the property under
    test rather than an economy. A routing stage handed this cannot name ``recent``,
    ``export`` or ``clear``, so it cannot read the trail and cannot erase the record of
    its own decisions.

    Beyond the contract it exposes :attr:`written` and :meth:`fail_record`; neither is
    contract. The first is what makes a *stage's* ADR-0197 §9 rows assertable at all,
    and the second is what makes §9's refuse-to-act branch reachable from a test.
    """

    def __init__(
        self,
        *,
        failure: Exception | None = None,
        max_rows: int = DEFAULT_MAX_ROWS,
    ) -> None:
        """Create an empty recorder.

        Args:
            failure: Arm :meth:`record` to raise from the first call, wrapping this as
                the cause. ``None`` records normally.
            max_rows: ADR-0197 §9's cap. Held here as well as on the trail fake because
                a stage's test may want to see the prune from the seam the stage
                actually holds — which is exactly what §12's bounded park→prune→resume
                case needs.

        Raises:
            TypeError: If ``max_rows`` is not exactly an ``int``.
            ValueError: If ``max_rows`` is not strictly positive, or is not below
                ``2**63``.
        """
        self._log = _RoutingLog(max_rows=max_rows)
        self._failure = failure
        self._resource = SuspendableResource()

    @property
    def written(self) -> tuple[RoutedOperationRecord, ...]:
        """Every row appended, oldest-recorded first — a **test-only** lever.

        Deliberately not spelled ``export``: ADR-0197 §9 removes the read capability
        from this seam, and a fake carrying the contract's own read name would let a
        stage's test reach it through a concrete annotation. The suite asks the subject
        it was handed; production callers name the Protocol.
        """
        return tuple(self._log.recording_order())

    def fail_record(self, error: Exception | None = None) -> None:
        """Arm :meth:`record` to raise, wrapping ``error`` as the cause.

        ADR-0197 §9's "a row that cannot be written stops the act it precedes" is
        otherwise unreachable from any test, and §12 requires it asserted over a
        confirm-owed route the user approved, over the routing pass of a confirm-owed
        route, and over a read-only route.
        """
        self._failure = (
            error if error is not None else RuntimeError("fake: the routing trail is unwritable")
        )

    def suspend_next_operation(self) -> LoopSuspension:
        """Hold the next :meth:`record` open inside the modelled resource.

        The hook ADR-0060's cancellation case takes, and the lever ADR-0197 §7's
        reservation-release cases need: a pass cancelled at the await between reserving
        a slot and registering a park.

        Returns:
            The handle to wait on and release.
        """
        return self._resource.suspend_next()

    @property
    def resource_log(self) -> ResourceLog:
        """When each call was inside the modelled resource (ADR-0060's case reads it)."""
        return self._resource.log

    async def record(self, record: RoutedOperationRecord) -> None:
        """Append ``record`` (ADR-0197 §9).

        Raises:
            RoutingTrailError: If a failure is armed, if the record does not satisfy its
                own model, if its id is held under a differing record, or if its
                ``route_id`` or its place in the route's state machine is refused.
        """
        if self._failure is not None:
            msg = "fake: the routing trail could not be written"
            raise RoutingTrailError(msg) from self._failure
        async with self._resource.held():
            self._log.append(record)


@final
class FakeRoutingTrail:
    """A non-persistent, append-only ``RoutingTrail`` backed by a list.

    Structurally implements :class:`~ai_assistant.core.protocols.RoutingTrail` **and**
    :class:`~ai_assistant.core.protocols.RoutingRecorder`, which is ADR-0197 §9's "one
    concrete store satisfies them" modelled in the double as well as in the store.

    :meth:`record`'s checks, its append and §9's prune are separated by no interleaving
    point, which is how the atomicity §9 requires is obtained on a single event loop.
    Every method runs inside a
    :class:`~ai_assistant.testing.cancellation.SuspendableResource`, so the fake is a
    subject for ADR-0060's cancellation clause at each of the lock sites the ``sqlite3``
    trail has.

    **The order is recording order and never** ``decided_at``. A list preserves it by
    construction, which is the point rather than a convenience: a prune keyed on a
    caller-supplied instant after a backwards clock correction deletes the rows it just
    wrote, so a fake that sorted on ``decided_at`` would model a store no implementation
    may be.
    """

    def __init__(
        self,
        records: Sequence[RoutedOperationRecord] = (),
        *,
        max_rows: int = DEFAULT_MAX_ROWS,
    ) -> None:
        """Create a trail holding ``records``, in the order given.

        Args:
            records: The history to start from, appended in order through the same
                invariants :meth:`record` applies — so a script this fake could only
                honour by breaking its own contract fails where it was written.
            max_rows: ADR-0197 §9's cap.

        Raises:
            TypeError: If ``max_rows`` is not exactly an ``int``.
            ValueError: If ``max_rows`` is not strictly positive, or is not below
                ``2**63``.
            RoutingTrailError: If ``records`` holds a record this store could not have
                written — a repeated id, a route that answers twice, a row that does
                not satisfy its own model.
        """
        self._log = _RoutingLog(max_rows=max_rows)
        self._resource = SuspendableResource()
        self._record_failure: Exception | None = None
        self._read_failure: Exception | None = None
        for record in records:
            self._log.append(record)

    def fail_record(self, error: Exception | None = None) -> None:
        """Arm :meth:`record` to raise, wrapping ``error`` as the cause."""
        self._record_failure = (
            error if error is not None else RuntimeError("fake: the routing trail is unwritable")
        )

    def fail_read(self, error: Exception | None = None) -> None:
        """Arm :meth:`recent`, :meth:`export` and :meth:`clear` to raise.

        "The store could not be read" is a state no well-formed input can provoke, so a
        consumer's own error branch is unreachable without a lever for it.
        """
        self._read_failure = (
            error if error is not None else RuntimeError("fake: the routing trail is unreadable")
        )

    def suspend_next_operation(self) -> LoopSuspension:
        """Hold the next call that enters the modelled resource open inside it.

        There is one modelled resource and every method enters it, so this suspends
        whichever call arrives next rather than a named operation.

        Returns:
            The handle to wait on and release.
        """
        return self._resource.suspend_next()

    @property
    def resource_log(self) -> ResourceLog:
        """When each call was inside the modelled resource (ADR-0060's case reads it)."""
        return self._resource.log

    @property
    def written(self) -> tuple[RoutedOperationRecord, ...]:
        """Every row appended, oldest-recorded first — the narrow fake's own lever.

        Carried here as well so one conformance suite can be bound to **both** fakes
        (ADR-0197 §12): the narrow suite asks the subject it was handed, and a subject
        that could not answer it would need a second suite rather than the same one.
        """
        return tuple(self._log.recording_order())

    async def record(self, record: RoutedOperationRecord) -> None:
        """Append ``record``.

        Raises:
            RoutingTrailError: If a failure is armed, if the record does not satisfy its
                own model, if its id is held under a differing record, or if its
                ``route_id`` or its place in the route's state machine is refused.
        """
        if self._record_failure is not None:
            msg = "fake: the routing trail could not be written"
            raise RoutingTrailError(msg) from self._record_failure
        # The checks are *inside* the resource rather than in front of it: a caller that
        # validated against a trail it no longer holds could pass a check that the
        # append then contradicts.
        async with self._resource.held():
            self._log.append(record)

    async def recent(self, *, limit: int) -> tuple[RoutedOperationRecord, ...]:
        """Return up to ``limit`` rows, newest-**recorded** first.

        Raises:
            ValueError: If ``limit`` is outside ``[1, 2**63)``. Refused locally and
                before any I/O, as ADR-0186 §3 requires of every bounded listing.
            RoutingTrailError: If a read failure is armed.
        """
        if not 0 < limit < MAX_LIMIT_EXCLUSIVE:
            msg = f"limit must be strictly positive and below 2**63, got {limit}"
            raise ValueError(msg)
        self._refuse_read()
        async with self._resource.held():
            rows = self._log.recording_order()
        rows.reverse()
        return tuple(rows[:limit])

    async def export(self) -> tuple[RoutedOperationRecord, ...]:
        """Return every row held, in recording order (ADR-0004 §6).

        Raises:
            RoutingTrailError: If a read failure is armed.
        """
        self._refuse_read()
        async with self._resource.held():
            return tuple(self._log.recording_order())

    async def clear(self) -> None:
        """Destroy every row, for ADR-0007's deletion right.

        Raises:
            RoutingTrailError: If a read failure is armed.
        """
        self._refuse_read()
        async with self._resource.held():
            self._log.clear()

    def _refuse_read(self) -> None:
        """Raise the armed read failure, if there is one.

        Raises:
            RoutingTrailError: If :meth:`fail_read` armed one.
        """
        if self._read_failure is not None:
            msg = "fake: the routing trail could not be read"
            raise RoutingTrailError(msg) from self._read_failure


__all__ = [
    "DEFAULT_CONVERSATION_ID",
    "DEFAULT_DECIDED_AT",
    "DEFAULT_MAX_ROWS",
    "MAX_LIMIT_EXCLUSIVE",
    "MAX_ROWS_EXCLUSIVE",
    "FakeRoutingRecorder",
    "FakeRoutingTrail",
    "routed_operation_record",
]
