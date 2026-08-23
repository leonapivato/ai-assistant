"""Canonical fakes for the two source-read Protocols (ADR-0185 §4, §12).

Both halves of the read seam, and both are owed a full triad in the change that
adds them: :class:`FakeSourceReadRecorder` for the **write** seam a driver holds,
and :class:`FakeSourceReadTrail` for the durable store the hub's read-trail
operations hold. Neither is an internal seam of ``permissions/``.

**The two fakes model one store between them**, exactly as the grant pair does. A
composition root is free to pass one concrete object to a driver's
``SourceReadRecorder`` parameter and to a ``SourceReadTrail`` one, so
``tests/permissions/test_fake_source_reads.py`` binds the *trail* fake to the
recorder suite as well — turning ADR-0185 §4's "one implementation satisfies both"
from an assertion into a test.

**The narrow fake carries no read member at all**, and that is deliberate rather
than economical. ADR-0185 §4 removes the ability to *read* the trail from the type
a driver names, because a queryable read trail in a driver's hand is the cursor
ADR-0093 §5 forbids — "It may not be derived from durable state recording what
previous runs read." A canonical fake that carried ``recent`` anyway would let a
driver's own test reach it through a concrete annotation, which is the one place
the type stops arguing. What the narrow fake offers instead is
:attr:`FakeSourceReadRecorder.written`, a *test author's* lever with a name no
production caller would reach for.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final, final
from uuid import uuid4

from pydantic import ValidationError

from ai_assistant.core.errors import ReadTrailError
from ai_assistant.core.types import GrantScope, ReadOutcome, SourceReadRecord
from ai_assistant.testing.cancellation import LoopSuspension, ResourceLog, SuspendableResource
from ai_assistant.testing.readers import DEFAULT_READER_NAME

if TYPE_CHECKING:
    from collections.abc import Sequence

#: The source a :func:`source_read_record` names when the caller does not, and the
#: identity :class:`~ai_assistant.testing.FakeReader` declares by default — so a
#: driver's test that wires a fake reader beside a recorder gets records naming the
#: reader that produced them, with no third constant to keep in step.
DEFAULT_READ_SOURCE: Final = DEFAULT_READER_NAME

#: The instant :func:`source_read_record` stamps when the caller does not. Fixed
#: rather than "now", so a record built in a test is the same record on every run
#: (ADR-0026 §2's posture applied to a fixture).
DEFAULT_CHECKED_AT: Final = datetime(2026, 7, 20, 12, 0, tzinfo=UTC)

#: The grant a :func:`source_read_record` cites on the four outcomes that ran under
#: one. It is a plain identifier rather than a real
#: :class:`~ai_assistant.core.types.SourceGrant`'s id, because ADR-0185 §8 makes
#: the pointer **one-way**: nothing joins back, and a ``grant`` naming a record no
#: store holds is legible history rather than corruption.
DEFAULT_GRANT_ID: Final = "grant-1"

#: The exclusive upper bound ADR-0185 §6 puts on the cap — "every strictly positive
#: integer below ``2**63``", which is ``Settings``' own ``lt=2**63``. A list could
#: hold more; the durable store cannot bind more, and a fake that diverged here would
#: admit a configuration no deployment can produce.
MAX_ROWS_EXCLUSIVE: Final = 2**63

#: The cap both fakes hold when a caller states none — ``Settings``' own default
#: (ADR-0185 §6), so an unconfigured fake behaves like an unconfigured deployment
#: and a test that wants the prune has to ask for it.
DEFAULT_MAX_ROWS: Final = 200_000

#: The outcomes on which no grant was found at the first check, so no record may
#: cite one (ADR-0185 §2). Spelled here so :func:`source_read_record` can derive a
#: coherent default rather than making every caller state the pairing.
_UNGRANTED: Final = frozenset({ReadOutcome.REFUSED, ReadOutcome.UNANSWERED})


def _mint() -> str:
    """A fresh record id, minted by the caller as ADR-0021 §3 requires of every store."""
    return f"read-{uuid4().hex}"


def source_read_record(  # noqa: PLR0913 — a source, an id, a use, an instant, an outcome, a grant and a count; each is one field of the record a caller may want to name
    source: str = DEFAULT_READ_SOURCE,
    *,
    record_id: str | None = None,
    use: GrantScope = GrantScope.INGEST,
    checked_at: datetime = DEFAULT_CHECKED_AT,
    outcome: ReadOutcome = ReadOutcome.COMPLETED,
    grant: str | None = None,
    produced: int = 0,
) -> SourceReadRecord:
    """Build one :class:`~ai_assistant.core.types.SourceReadRecord` for a test.

    Args:
        source: The reader's declared identity the attempt was about.
        record_id: The record's own id; a fresh mint when omitted.
        use: Which of the three uses the attempt was for.
        checked_at: When the first grant check resolved.
        outcome: How the attempt ended.
        grant: The grant the attempt ran under. ``None`` **derives** it from
            ``outcome`` rather than meaning "no grant": :data:`DEFAULT_GRANT_ID` on
            the four outcomes that ran under one, and a genuine ``None`` on
            ``REFUSED`` and ``UNANSWERED``. A caller wanting an *incoherent* pairing
            — to assert the model refuses it — builds the record directly, because
            this helper exists to make the coherent case cheap and a helper that
            could produce the refused shape would let a test assert against a record
            no conforming driver could write.
        produced: How many items the reading carried. Zero by default, which is the
            only admissible count on the three outcomes carrying no reading.

    Returns:
        The record, validated by its own model.
    """
    return SourceReadRecord(
        id=_mint() if record_id is None else record_id,
        source=source,
        use=use,
        checked_at=checked_at,
        outcome=outcome,
        grant=None if outcome in _UNGRANTED else (grant or DEFAULT_GRANT_ID),
        produced=produced,
    )


def _snapshot(read: SourceReadRecord) -> SourceReadRecord:
    """Rebuild ``read`` as a validated, detached :class:`SourceReadRecord`.

    ADR-0021 §4's "detached, validated snapshot" applied to this store, on
    ``FakeAuditTrail.record``'s reasoning: a copy alone detaches without checking,
    so a record corrupted past its frozen model's guard — a ``checked_at`` written
    back as naive is the sharp case — would be stored and then make every later
    read of the trail incoherent.

    Rebuilt as a ``SourceReadRecord`` specifically rather than as ``type(read)``: a
    caller's subclass could override ``model_copy`` to return ``self``, and storing
    that instance would hand every later read this store's own object.

    Raises:
        ReadTrailError: If the record does not satisfy its own model. Raised from
            this seam's own class rather than letting pydantic's
            ``ValidationError`` escape, because a caller handling "the trail would
            not accept this" should not need a second handler for the shape of the
            refusal.
    """
    try:
        return SourceReadRecord.model_validate(read.model_dump())
    except ValidationError as exc:
        msg = f"source read {read.id!r} is not a valid record: {exc}"
        raise ReadTrailError(msg) from exc


class _ReadLog:
    """The append-only list both fakes keep, with ADR-0185 §6's prune.

    Private and shared, for :mod:`ai_assistant.testing.grants`'s reason: the
    invariants are the store's rather than either seam's, and two copies would be
    two places for them to drift.
    """

    def __init__(self, *, max_rows: int) -> None:
        """Create an empty log bounded at ``max_rows`` rows.

        Args:
            max_rows: The cap, strictly positive. Refused here as well as at
                ``Settings`` load for ``UpcomingEventStage``'s reason: a fake built
                in a test that reads no setting must not be able to hold a cap of
                zero, which is at capacity before its first append.

        Raises:
            TypeError: If ``max_rows`` is not exactly an ``int``. ``bool`` is an
                ``int``, so ``True`` would otherwise be a cap of one — a flag loaded
                where a count belongs, which is what ``Settings``' own
                ``_exactly_an_integer`` refuses at load.
            ValueError: If ``max_rows`` is not strictly positive, or is not below
                ``2**63``. The upper bound is ADR-0185 §6's admissible range, and the
                fake refuses it though a list could hold it: a canonical fake that
                admitted a cap the durable store cannot bind would let a consumer's
                test pass against a configuration no deployment can produce, which is
                the trade ``FakeReader`` already names.
        """
        if type(max_rows) is not int:
            msg = (
                f"the read trail's cap must be exactly an int, got {max_rows!r} of type "
                f"{type(max_rows).__name__}; a bool passes every comparison below while "
                f"meaning a cap of one (ADR-0185 §6)"
            )
            raise TypeError(msg)
        if not 0 < max_rows < MAX_ROWS_EXCLUSIVE:
            msg = (
                f"the read trail's cap must be strictly positive and below 2**63, got "
                f"{max_rows}; there is no unlimited spelling and no zero (ADR-0185 §6)"
            )
            raise ValueError(msg)
        self._max_rows = max_rows
        self._rows: list[SourceReadRecord] = []

    def append(self, read: SourceReadRecord) -> str:
        """Append a validated snapshot, prune to the cap, and return the id.

        The duplicate check, the append and the prune are one uninterrupted
        sequence with no ``await`` in it, which is how ADR-0185 §12's atomicity is
        obtained on a single event loop.

        Raises:
            ReadTrailError: If the record is invalid or its id is already recorded.
        """
        snapshot = _snapshot(read)
        if any(row.id == snapshot.id for row in self._rows):
            msg = (
                f"source read {snapshot.id!r} is already recorded; the trail is "
                f"append-only, so history cannot be rewritten by replaying a write"
            )
            raise ReadTrailError(msg)
        self._rows.append(snapshot)
        # Oldest-recorded first, uniformly and blind to every field of the row
        # (ADR-0185 §6). Nothing anybody chose is removed, which is what keeps the
        # horizon from being the page torn out of the book.
        if len(self._rows) > self._max_rows:
            del self._rows[: len(self._rows) - self._max_rows]
        return snapshot.id

    def recording_order(self) -> list[SourceReadRecord]:
        """Every row held, oldest-recorded first, as **detached** copies.

        ADR-0018 §3's read-path rule, which a fake holding objects has to keep by
        hand where a serialising store gets it for free: ``frozen=True`` refuses
        ``row.outcome = …`` and not ``row.__dict__["outcome"] = …``, so handing back
        the stored instances would let a reader rewrite an append-only row through
        the very call that reports it. The list is fresh too, for the same reason at
        one level up.
        """
        return [row.model_copy() for row in self._rows]

    def clear(self) -> int:
        """Drop every row, returning how many there were."""
        removed = len(self._rows)
        self._rows.clear()
        return removed


@final
class FakeSourceReadRecorder:
    """A ``SourceReadRecorder`` test double: it writes, and answers nothing.

    Structurally implements
    :class:`~ai_assistant.core.protocols.SourceReadRecorder`, and structurally
    fails :class:`~ai_assistant.core.protocols.SourceReadTrail` — which is the
    property under test rather than an economy. A driver handed this cannot name
    ``recent``, so ADR-0093 §5's forbidden cursor is unreachable from the site that
    would want it.

    Beyond the contract it exposes :attr:`written` and :meth:`fail_record`; neither
    is contract. The first is what makes a *driver's* ADR-0185 §1 outcomes
    assertable at all, and the second is what makes §5's fail-closed branch
    reachable from a test.
    """

    def __init__(
        self,
        *,
        failure: Exception | None = None,
        max_rows: int = DEFAULT_MAX_ROWS,
    ) -> None:
        """Create an empty recorder.

        Args:
            failure: Arm :meth:`record` to raise from the first call, wrapping this
                as the cause. ``None`` records normally.
            max_rows: ADR-0185 §6's cap. Held here as well as on the trail fake
                because a driver's test may want to see the prune from the seam the
                driver actually holds.

        Raises:
            ValueError: If ``max_rows`` is not strictly positive.
        """
        self._log = _ReadLog(max_rows=max_rows)
        self._failure = failure
        self._resource = SuspendableResource()

    @property
    def written(self) -> tuple[SourceReadRecord, ...]:
        """Every record appended, oldest-recorded first — a **test-only** lever.

        Deliberately not spelled ``export``: ADR-0185 §4 removes the read capability
        from this seam, and a fake carrying the contract's own read name would let a
        driver's test reach it through a concrete annotation. The suite asks the
        subject it was handed; production callers name the Protocol.
        """
        return tuple(self._log.recording_order())

    def fail_record(self, error: Exception | None = None) -> None:
        """Arm :meth:`record` to raise, wrapping ``error`` as the cause.

        ADR-0185 §5's fail-closed clause — "Where the recorder raises, the driver
        discards the reading" — is otherwise unreachable from any test, and §11 arm
        (e) is measured over exactly this path.
        """
        self._failure = (
            error if error is not None else RuntimeError("fake: the read trail is unwritable")
        )

    def suspend_next_operation(self) -> LoopSuspension:
        """Hold the next :meth:`record` open inside the modelled resource.

        The hook ADR-0060's cancellation case takes, and the lever ADR-0185 §11 arm
        (e)'s third attempt needs: a cancellation landing *inside* a recorder call
        already in flight, whose row the contract refuses to promise either way.

        Returns:
            The handle to wait on and release.
        """
        return self._resource.suspend_next()

    @property
    def resource_log(self) -> ResourceLog:
        """When each call was inside the modelled resource (ADR-0060's case reads it)."""
        return self._resource.log

    async def record(self, read: SourceReadRecord) -> str:
        """Append ``read`` and return its id.

        Raises:
            ReadTrailError: If a failure is armed, if the record does not satisfy
                its own model, or if its id is already recorded. One class for all
                three (ADR-0185 §12).
        """
        if self._failure is not None:
            msg = "fake: the read trail could not be written"
            raise ReadTrailError(msg) from self._failure
        async with self._resource.held():
            return self._log.append(read)


@final
class FakeSourceReadTrail:
    """A non-persistent, append-only ``SourceReadTrail`` backed by a list.

    Structurally implements :class:`~ai_assistant.core.protocols.SourceReadTrail`
    **and** :class:`~ai_assistant.core.protocols.SourceReadRecorder`, which is
    ADR-0185 §4's "one ``permissions/`` class implementing all four members
    satisfies both seams" modelled in the double as well as in the store.

    :meth:`record`'s duplicate check, its append and ADR-0185 §6's prune are
    separated by no interleaving point, which is how the atomicity §12 requires is
    obtained on a single event loop. Every method runs inside a
    :class:`~ai_assistant.testing.cancellation.SuspendableResource`, so the fake is
    a subject for ADR-0060's cancellation clause at each of the lock sites the
    ``sqlite3`` trail has.

    **The order is recording order and never** ``checked_at``. A list preserves it
    by construction, which is the point rather than a convenience: ADR-0185 §6 rules
    that a prune keyed on a caller-supplied instant deletes the rows it just wrote
    after a backwards clock correction, so a fake that sorted on ``checked_at``
    would model a store no implementation may be.
    """

    def __init__(
        self,
        records: Sequence[SourceReadRecord] = (),
        *,
        max_rows: int = DEFAULT_MAX_ROWS,
    ) -> None:
        """Create a trail holding ``records``, in the order given.

        Args:
            records: The history to start from, appended in order through the same
                invariants :meth:`record` applies — so a script this fake could only
                honour by breaking its own contract fails where it was written.
            max_rows: ADR-0185 §6's cap.

        Raises:
            ValueError: If ``max_rows`` is not strictly positive.
            ReadTrailError: If ``records`` names one id twice, or holds a record
                that does not satisfy its own model.
        """
        self._log = _ReadLog(max_rows=max_rows)
        self._resource = SuspendableResource()
        self._record_failure: Exception | None = None
        self._read_failure: Exception | None = None
        for read in records:
            self._log.append(read)

    def fail_record(self, error: Exception | None = None) -> None:
        """Arm :meth:`record` to raise, wrapping ``error`` as the cause."""
        self._record_failure = (
            error if error is not None else RuntimeError("fake: the read trail is unwritable")
        )

    def fail_read(self, error: Exception | None = None) -> None:
        """Arm :meth:`recent`, :meth:`export` and :meth:`clear` to raise.

        "The store could not be read" is a state no well-formed input can provoke,
        so a consumer's own error branch is unreachable without a lever for it.
        """
        self._read_failure = (
            error if error is not None else RuntimeError("fake: the read trail is unreadable")
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

    async def record(self, read: SourceReadRecord) -> str:
        """Append ``read`` and return its id.

        Raises:
            ReadTrailError: If a failure is armed, if the record does not satisfy
                its own model, or if its id is already recorded.
        """
        if self._record_failure is not None:
            msg = "fake: the read trail could not be written"
            raise ReadTrailError(msg) from self._record_failure
        # The checks are *inside* the resource rather than in front of it: a caller
        # that validated against a trail it no longer holds could pass a duplicate
        # check that the append then contradicts.
        async with self._resource.held():
            return self._log.append(read)

    async def recent(self, *, limit: int = 50) -> list[SourceReadRecord]:
        """Return up to ``limit`` records, newest-**recorded** first.

        Raises:
            ValueError: If ``limit`` is not strictly positive.
            ReadTrailError: If a read failure is armed.
        """
        if limit <= 0:
            msg = f"limit must be strictly positive, got {limit}"
            raise ValueError(msg)
        self._refuse_read()
        async with self._resource.held():
            rows = self._log.recording_order()
        rows.reverse()
        return rows[:limit]

    async def export(self) -> list[SourceReadRecord]:
        """Return every record held, in recording order (ADR-0004 §6).

        Raises:
            ReadTrailError: If a read failure is armed.
        """
        self._refuse_read()
        async with self._resource.held():
            return self._log.recording_order()

    async def clear(self) -> int:
        """Delete every record, returning the number removed.

        Raises:
            ReadTrailError: If a read failure is armed.
        """
        self._refuse_read()
        async with self._resource.held():
            return self._log.clear()

    def _refuse_read(self) -> None:
        """Raise the armed read failure, if there is one.

        Raises:
            ReadTrailError: If :meth:`fail_read` armed one.
        """
        if self._read_failure is not None:
            msg = "fake: the read trail could not be read"
            raise ReadTrailError(msg) from self._read_failure


__all__ = [
    "DEFAULT_CHECKED_AT",
    "DEFAULT_GRANT_ID",
    "DEFAULT_MAX_ROWS",
    "DEFAULT_READ_SOURCE",
    "MAX_ROWS_EXCLUSIVE",
    "FakeSourceReadRecorder",
    "FakeSourceReadTrail",
    "source_read_record",
]
