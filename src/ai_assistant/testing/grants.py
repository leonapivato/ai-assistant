"""Canonical test doubles for the source-grant seam (ADR-0097 §10).

The shared fakes for :class:`~ai_assistant.core.protocols.SourceGrants` and
:class:`~ai_assistant.core.protocols.SourceGrantStore`, so a subsystem that
drives a reader — `orchestration`'s ingestion stage, `context`'s facet adapter —
can exercise every branch of its own gate without a store on disk and without
importing the permissions subsystem's internals (``CLAUDE.md`` golden rule 1).

**Two fakes because the seam is two Protocols**, split by capability rather than
by taxonomy (ADR-0097 §3). :class:`FakeSourceGrants` is the narrow one and can
create nothing; :class:`FakeSourceGrantStore` records. The store fake satisfies
the narrow seam structurally, which is why the shared ``SourceGrants``
conformance suite is bound against **both** — that turns §3's "one
implementation satisfies both" from an assertion into a test.

Between them they are scriptable to the states ADR-0097 §5 and §5a's gate must
be tested against, and each capability exists because a driver's branch is
otherwise unreachable from any test:

* a **live** grant, and a grant **revoked** by a second record;
* a ``live()`` that **raises** :class:`~ai_assistant.core.errors.GrantError`, on
  *both* fakes — without it a driver's fail-closed branch is unreachable, and an
  implementation that caught the error and carried on with the earlier lookup
  would pass everything while writing beliefs after its authorisation stopped
  being checkable (ADR-0097 §5a, §10);
* a **revocation between two ``live()`` calls** on :class:`FakeSourceGrants` —
  the first answers with a grant and a later one with ``None`` — which is what
  makes §5a's discard clause testable at all, since the query seam has no method
  a test could record with; and
* a ``record`` that raises, on the store fake.

**Not a fault injector.** Everything here conforms. A consumer that needs a store
which *breaks* the contract on purpose supplies its own stub; these must stay the
things a conforming implementation is compared against, so a script they could
only honour by violating their own contract is refused where it is written
(``FakeReader`` and ``FakeObserver`` make the same trade).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final, final
from uuid import uuid4

from pydantic import ValidationError

from ai_assistant.core.errors import GrantError, InvalidGrantError
from ai_assistant.core.types import GrantScope, SourceGrant
from ai_assistant.testing.cancellation import SuspendableResource
from ai_assistant.testing.readers import DEFAULT_READER_NAME

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.testing.cancellation import LoopSuspension, ResourceLog

#: The source a scripted grant is about unless a test names another. It is
#: :data:`~ai_assistant.testing.readers.DEFAULT_READER_NAME` rather than a
#: constant of its own, so a consumer wiring a :class:`~ai_assistant.testing.\
#: readers.FakeReader` beside one of these fakes gets a grant that actually
#: covers that reader: ADR-0097 §1 keys a grant on the reader's declared
#: identity, and two defaults that did not match would make the natural wiring
#: read as ungranted.
DEFAULT_GRANTED_SOURCE: Final = DEFAULT_READER_NAME

#: When a scripted record pretends the user decided. Fixed, so ordering
#: assertions are about the values under test rather than about how fast a suite
#: runs — ``permission_builders.AT``'s reason.
DEFAULT_DECIDED_AT: Final = datetime(2026, 7, 20, 12, 0, tzinfo=UTC)

#: Every use, which is what a test that is not about scope wants. Declaration
#: order, so it is already canonical.
_ALL_USES: Final = (GrantScope.FACET, GrantScope.INGEST)


def _mint(prefix: str) -> str:
    """Mint one opaque record id.

    Opaque and minted rather than derived, for the reason ADR-0092 §6 gives about
    a producer's ids: a derived id is an *address*, aimed at the same record every
    time. A test that needs a stable id supplies one.
    """
    return f"{prefix}-{uuid4().hex}"


def source_grant(
    source: str = DEFAULT_GRANTED_SOURCE,
    *,
    scope: Sequence[GrantScope] = _ALL_USES,
    grant_id: str | None = None,
    decided_at: datetime = DEFAULT_DECIDED_AT,
) -> SourceGrant:
    """One well-formed granting record.

    Exported for :func:`~ai_assistant.testing.readers.attested_proposal`'s
    reason: a consumer scripting either fake, and a driver's own tests, must not
    have to re-derive what a grant looks like. There is nothing subtle in the
    shape, but there are four fields to line up and one of them
    (:attr:`~ai_assistant.core.types.SourceGrant.source`) has to match a reader's
    declared name or the grant covers nothing.

    Args:
        source: The reader's declared identity this grant is about. Tier 2 — name
            the producer (``"calendar"``), never its source's location (ADR-0093
            §7). Nothing production reads it (``lint-imports`` keeps
            ``ai_assistant.testing`` out of every shipping package), so the blast
            radius is one test's output.
        scope: The uses authorised. Defaults to every use; pass a single-member
            sequence for a test about a use *outside* the grant.
        grant_id: A stable id, for a test that wants to name the record it is
            asserting on. ``None`` mints an opaque one.
        decided_at: When the user decided; timezone-aware.

    Returns:
        The grant, ready to hold or to record.
    """
    return SourceGrant(
        id=grant_id if grant_id is not None else _mint("grant"),
        source=source,
        scope=tuple(scope),
        decided_at=decided_at,
    )


def revocation_of(
    grant: SourceGrant,
    *,
    grant_id: str | None = None,
    decided_at: datetime | None = None,
) -> SourceGrant:
    """The record that revokes ``grant``, transcribing what it withdraws.

    The transcription is not a convenience: ADR-0097 §4 has the store verify that
    a revoking record carries the ``source`` and ``scope`` of the grant it
    revokes, so a hand-built revocation that got either wrong is refused. Building
    it from the grant makes that correct by construction, and a test that wants
    the *refusal* overrides one field deliberately rather than by accident.

    Args:
        grant: The granting record being withdrawn.
        grant_id: A stable id for the revoking record; ``None`` mints one.
        decided_at: When the user revoked. ``None`` reuses the grant's own
            instant, which is deliberate rather than lazy: ADR-0097 §4 never
            refuses a revocation for its timestamp, so the default must not
            quietly depend on being later.

    Returns:
        The revoking record.
    """
    return SourceGrant(
        id=grant_id if grant_id is not None else _mint("revoke"),
        source=grant.source,
        scope=grant.scope,
        decided_at=decided_at if decided_at is not None else grant.decided_at,
        revokes=grant.id,
    )


class _GrantLog:
    """The append-only history both fakes answer from (ADR-0097 §4).

    Shared rather than written twice, because the two fakes must agree about
    liveness to the letter: the store's ``record`` is what a test uses to arrange
    a state, and the narrow fake has to *be* in that same state for the shared
    ``SourceGrants`` suite to mean the same thing against both. Two hand-written
    copies of "is this grant live" would be free to disagree, and the one that
    disagreed would still pass its own suite.

    Not a Protocol implementation and not exported: the fakes are.
    """

    def __init__(self) -> None:
        """Create an empty history."""
        self._records: list[SourceGrant] = []

    def append(self, grant: SourceGrant) -> str:
        """Validate ``grant`` against every §4 invariant and append a snapshot.

        The snapshot is taken by **revalidating** rather than by copying, which is
        ADR-0097 §4's "detached, validated snapshot". A copy alone detaches
        without checking, so a record corrupted past its frozen model's guard — an
        emptied ``scope`` is the sharp case, since it would occupy the source's
        one live-grant slot while authorising nothing — would be stored and make
        every later read incoherent.

        Rebuilt as a :class:`~ai_assistant.core.types.SourceGrant` specifically,
        not as ``type(grant)``: a caller's subclass could override ``model_copy``
        to return ``self``, and storing that instance would hand every later read
        the log's own object, so the read-path detachment would silently stop
        holding.

        Raises:
            InvalidGrantError: If the record does not satisfy its own model, if
                its id is already recorded, if it grants a source that already has
                a live grant, or if it revokes and fails any of §4's invariants.
        """
        try:
            snapshot = SourceGrant.model_validate(grant.model_dump())
        except ValidationError as exc:
            msg = f"grant {grant.id!r} is not a valid record: {exc}"
            raise InvalidGrantError(msg) from exc
        if any(held.id == snapshot.id for held in self._records):
            msg = (
                f"grant {snapshot.id!r} is already recorded; the store is "
                f"append-only, so history cannot be rewritten by replaying a write"
            )
            raise InvalidGrantError(msg)
        if snapshot.revokes is None:
            self._check_no_live_grant(snapshot)
        else:
            self._check_revocation(snapshot)
        self._records.append(snapshot)
        return snapshot.id

    def _check_no_live_grant(self, grant: SourceGrant) -> None:
        """Refuse a second live grant for one source (ADR-0097 §4).

        Raises:
            InvalidGrantError: If ``grant``'s source already has a live grant.
        """
        standing = next((held for held in self._live_grants() if held.source == grant.source), None)
        if standing is not None:
            msg = (
                f"source {grant.source!r} already has live grant {standing.id!r}; "
                f"at most one grant per source is live at any instant, and "
                f"narrowing or widening is a revocation followed by a new grant "
                f"(ADR-0097 §2, §4)"
            )
            raise InvalidGrantError(msg)

    def _check_revocation(self, revocation: SourceGrant) -> None:
        """Enforce ADR-0097 §4's invariant on a revoking record.

        Five refusals, and **no sixth on the timestamp**: ``decided_at`` is
        caller-supplied and this log reads no clock, so refusing a revocation that
        predates its grant would make a grant permanently unrevokable across a
        backwards clock correction — the one property the contract exists to
        deliver, defeated by an invariant that was protecting nothing.

        Raises:
            InvalidGrantError: If the named grant is absent, is itself a
                revocation, is already revoked, names a different ``source``, or
                transcribes a different ``scope``.
        """
        target = next((held for held in self._records if held.id == revocation.revokes), None)
        if target is None:
            msg = (
                f"grant {revocation.revokes!r} is not recorded, so nothing revokes it (ADR-0097 §4)"
            )
            raise InvalidGrantError(msg)
        if target.revokes is not None:
            msg = (
                f"record {target.id!r} is itself a revocation; only a granting "
                f"record can be revoked (ADR-0097 §4)"
            )
            raise InvalidGrantError(msg)
        if any(held.revokes == target.id for held in self._records):
            msg = (
                f"grant {target.id!r} is already revoked; a grant revoked twice "
                f"is a history that says the user withdrew one thing twice "
                f"(ADR-0097 §4)"
            )
            raise InvalidGrantError(msg)
        if target.source != revocation.source:
            msg = (
                f"revocation {revocation.id!r} names source {revocation.source!r} but "
                f"grant {target.id!r} is about {target.source!r}; a revoking record "
                f"transcribes what it withdraws (ADR-0097 §4)"
            )
            raise InvalidGrantError(msg)
        if target.scope != revocation.scope:
            msg = (
                f"revocation {revocation.id!r} transcribes scope {revocation.scope!r} but "
                f"grant {target.id!r} authorised {target.scope!r}; there is no partial "
                f"revocation (ADR-0097 §2, §4)"
            )
            raise InvalidGrantError(msg)

    def _live_grants(self) -> list[SourceGrant]:
        """Return the granting records no recorded revocation names.

        Liveness is derived from the ``revokes`` relation **alone**: nothing here
        compares two ``decided_at`` values, which is what keeps a clock correction
        from changing who is granted (ADR-0097 §4).
        """
        revoked = {held.revokes for held in self._records if held.revokes is not None}
        return [held for held in self._records if held.revokes is None and held.id not in revoked]

    def live(self, source: str, use: GrantScope) -> SourceGrant | None:
        """The live grant covering ``source`` for ``use``, detached, or ``None``.

        ``source`` is compared with ``==`` and nothing else — no strip, no
        case-fold. A store that normalised here would change what a grant covers,
        which is the one place a store could be "helpful" and be wrong
        (ADR-0097 §9).
        """
        for held in self._live_grants():
            if held.source == source and use in held.scope:
                return held.model_copy(deep=True)
        return None

    def ordered(self) -> list[SourceGrant]:
        """Every record by ``decided_at`` descending, ``id`` ascending.

        Two passes over a stable sort rather than one composite key, because the
        two halves run in opposite directions and ``datetime`` has no negation —
        ``FakeAuditTrail._ordered``'s shape.
        """
        by_id = sorted(self._records, key=lambda held: held.id)
        return sorted(by_id, key=lambda held: held.decided_at, reverse=True)

    def snapshots(self, limit: int | None = None) -> list[SourceGrant]:
        """Detached copies of the newest ``limit`` records, or of all of them."""
        ordered = self.ordered()
        return [
            held.model_copy(deep=True) for held in (ordered if limit is None else ordered[:limit])
        ]

    def revoke_everything(self) -> int:
        """Append a revocation for every live grant, and report how many.

        What :meth:`FakeSourceGrants.revoke_after` fires. The revocations are
        *real* records appended through :meth:`append`, so the fake ends up in a
        state a conforming store could genuinely be in rather than in a private
        "pretend it is gone" mode that nothing else in the history explains. Each
        reuses its grant's own ``decided_at``, which the invariant permits.
        """
        live = self._live_grants()
        for held in live:
            self.append(revocation_of(held))
        return len(live)

    def clear(self) -> int:
        """Drop every record, returning the number removed."""
        removed = len(self._records)
        self._records.clear()
        return removed


@final
class FakeSourceGrants:
    """A query-only ``SourceGrants`` test double (ADR-0097 §3, §10).

    Structurally implements :class:`~ai_assistant.core.protocols.SourceGrants` and
    **nothing wider**: it has no ``record``, no ``recent``, no ``export`` and no
    ``clear``, so a driver's test cannot accidentally arrange state through the
    subject the driver is supposed to hold. That is the point of the split being
    a type rather than a promise, modelled in the fake as well as in the contract.

    A test arranges history through :meth:`hold` or through the constructor, both
    of which apply the same invariants a real store's ``record`` does — so a
    script this fake could only honour by breaking its own contract fails where it
    was written.

    Beyond the contract it counts its calls and takes three scripts —
    :meth:`fail_live`, :meth:`revoke_after`, and its initial records. None of them
    is contract; only the behaviour pinned by the shared ``SourceGrants``
    conformance suite is.
    """

    def __init__(
        self,
        records: Sequence[SourceGrant] = (),
        *,
        failure: Exception | None = None,
    ) -> None:
        """Create the fake.

        Args:
            records: The history this fake starts with, applied in order under a
                real store's invariants. Grants, revocations, or both.
            failure: Scripted at construction, for a test that wants every
                ``live`` to raise from the start; :meth:`fail_live` is the same
                script applied later. The raised error is always a
                :class:`~ai_assistant.core.errors.GrantError` wrapping this as
                ``__cause__``, because that is what the seam is allowed to raise.

        Raises:
            InvalidGrantError: If ``records`` is not a history a conforming store
                could hold — a duplicate id, two live grants for one source, or a
                revocation failing ADR-0097 §4's invariants.
        """
        self._log = _GrantLog()
        self._failure = failure
        self._revoke_after: int | None = None
        self._calls = 0
        for record in records:
            self._log.append(record)

    @property
    def call_count(self) -> int:
        """How many times :meth:`live` has been called."""
        return self._calls

    def hold(self, *records: SourceGrant) -> None:
        """Add ``records`` to this fake's history.

        **Test-only, and deliberately not named ``record``.** ADR-0097 §3 removes
        the recording capability from the type a *driver* names; this is a lever
        on the fake itself, reached by the test that built it and never by the
        code under test, which only ever sees the ``SourceGrants`` annotation.
        Nothing production can reach it either — ``lint-imports`` keeps
        ``ai_assistant.testing`` out of every shipping package.

        Args:
            records: Grants and revocations, applied in order.

        Raises:
            InvalidGrantError: If the resulting history is one no conforming store
                could hold.
        """
        for record in records:
            self._log.append(record)

    def fail_live(self, error: Exception | None = None) -> None:
        """Arm every subsequent :meth:`live` to raise.

        Required of this fake by ADR-0097 §10 and not decoration: §5a's
        fail-closed clause is otherwise untestable, because a driver's
        ``GrantError`` branch is unreachable from any test — and an implementation
        that caught the error and carried on with the earlier lookup would pass
        everything while writing beliefs after its authorisation stopped being
        checkable.

        Args:
            error: The underlying fault to model, preserved as ``__cause__``.
                ``None`` models a bare store fault with no interesting cause.
        """
        self._failure = (
            error if error is not None else RuntimeError("fake: the store is unreadable")
        )

    def revoke_after(self, calls: int = 1) -> None:
        """Arm a revocation to land after the next ``calls`` answers.

        The capability that makes ADR-0097 §5a's *second* clause testable at all:
        a driver must discard a reading whose grant went away between the check
        and the return of ``read()``, and the query seam has no method a test
        could record a revocation with. Without this the discard path is
        unreachable from a test and the clause would report as held while nothing
        exercised it — the same reasoning ADR-0093 §10 used to require its own
        fake's suspension gate.

        The revocation is a **real appended record** (see
        :meth:`_GrantLog.revoke_everything`), not a private "pretend it is gone"
        mode, so the fake lands in a state a conforming store could be in.

        Args:
            calls: How many further :meth:`live` calls answer normally before the
                revocation lands. ``1`` — the default — is §5a's case: the gate's
                check passes, and the driver's re-check after ``read()`` does not.

        Raises:
            ValueError: If ``calls`` is negative. Zero is meaningful (revoke
                before the next call); a negative count names no moment.
        """
        if calls < 0:
            msg = f"calls must not be negative, got {calls}"
            raise ValueError(msg)
        self._revoke_after = self._calls + calls

    async def live(self, *, source: str, use: GrantScope) -> SourceGrant | None:
        """Return the live grant covering ``source`` for ``use``, or ``None``.

        Returns:
            A detached snapshot of the covering grant, or ``None`` when none
            covers it. Detached because this is the one answer the gate rests on:
            ``frozen=True`` would not stop a caller widening ``scope`` through
            ``__dict__`` on a shared object, which is the gate defeated through
            its own answer (ADR-0097 §4, §10).

        Raises:
            GrantError: If a failure is scripted (:meth:`fail_live`), wrapping it
                as ``__cause__``.
        """
        self._calls += 1
        if self._failure is not None:
            msg = "fake: the grant store could not be read"
            raise GrantError(msg) from self._failure
        if self._revoke_after is not None and self._calls > self._revoke_after:
            self._revoke_after = None
            self._log.revoke_everything()
        return self._log.live(source, use)


@final
class FakeSourceGrantStore:
    """A non-persistent, append-only ``SourceGrantStore`` test double.

    Structurally implements :class:`~ai_assistant.core.protocols.SourceGrantStore`
    — and therefore :class:`~ai_assistant.core.protocols.SourceGrants` too, which
    is why the narrow conformance suite is bound against this class as well as
    against :class:`FakeSourceGrants`. That binding is what turns ADR-0097 §3's
    "one implementation satisfies both" from an assertion into a test.

    :meth:`record`'s checks and its append are separated by no interleaving point,
    which is how the atomicity ADR-0097 §4 requires is obtained on a single event
    loop: two concurrent grants for one source cannot both observe no live grant.
    Every method — the two writes and the three reads — runs inside a
    :class:`~ai_assistant.testing.cancellation.SuspendableResource`, so the fake
    is a real subject for ADR-0060's cancellation clause at each of the lock sites
    a durable store would have, rather than an implementation the obligation
    cannot reach. That does not weaken the atomicity argument: acquiring an
    uncontended :class:`asyncio.Lock` does not suspend, so nothing runs between
    the checks and the append that did not before, and under contention the lock
    serialises the pair outright.
    """

    def __init__(self, records: Sequence[SourceGrant] = ()) -> None:
        """Create the store.

        Args:
            records: The history it starts with, applied in order under the same
                invariants :meth:`record` applies.

        Raises:
            InvalidGrantError: If ``records`` is not a history a conforming store
                could hold.
        """
        self._log = _GrantLog()
        self._resource = SuspendableResource()
        self._live_failure: Exception | None = None
        self._record_failure: Exception | None = None
        for record in records:
            self._log.append(record)

    def suspend_next_operation(self) -> LoopSuspension:
        """Hold the next call that enters the modelled resource open inside it.

        There is one modelled resource and every method enters it, so this
        suspends whichever call arrives next rather than a named operation. The
        hook the cancellation case takes (ADR-0060 §3); test-only, and not part of
        the contract — the Protocol deliberately grows no affordance for this, so
        the suite asks the *subject* it was handed rather than the seam every
        consumer depends on.

        Returns:
            The handle to wait on and release.
        """
        return self._resource.suspend_next()

    @property
    def resource_log(self) -> ResourceLog:
        """When each call was inside the modelled resource (ADR-0060's case reads it)."""
        return self._resource.log

    def fail_live(self, error: Exception | None = None) -> None:
        """Arm every subsequent :meth:`live` to raise (ADR-0097 §10).

        Required of this fake as well as of :class:`FakeSourceGrants`: a driver
        handed the store as its ``SourceGrants`` must exhibit the same fail-closed
        branch, and a capability present on only one of the two would leave that
        wiring untestable.

        Args:
            error: The underlying fault, preserved as ``__cause__``. ``None``
                models a bare store fault.
        """
        self._live_failure = (
            error if error is not None else RuntimeError("fake: the store is unreadable")
        )

    def fail_record(self, error: Exception | None = None) -> None:
        """Arm every subsequent :meth:`record` to raise a store fault.

        A **store fault**, not a refusal: it raises
        :class:`~ai_assistant.core.errors.GrantError` rather than
        :class:`~ai_assistant.core.errors.InvalidGrantError`, because a refusal is
        what the invariants already produce from a badly-formed record and a
        caller arranging one of those builds the record instead. What this scripts
        is the other failure — "the store could not be written" — which no
        well-formed input can provoke.

        Args:
            error: The underlying fault, preserved as ``__cause__``. ``None``
                models a bare store fault.
        """
        self._record_failure = (
            error if error is not None else RuntimeError("fake: the store is unwritable")
        )

    async def record(self, grant: SourceGrant) -> str:
        """Append ``grant`` and return its id.

        The invariant checks are *inside* the resource, not before it: a caller
        that validated against a store it no longer holds could pass a duplicate
        or live-grant check that the append then contradicts. This is where the
        class docstring's "no interleaving point between the checks and the
        append" is actually kept once there is a lock at all.

        Raises:
            GrantError: If a store fault is scripted (:meth:`fail_record`).
            InvalidGrantError: If the record does not satisfy its own model, if
                its id is already recorded, if its source already has a live
                grant, or if it revokes and fails any of ADR-0097 §4's invariants.
        """
        if self._record_failure is not None:
            msg = "fake: the grant store could not be written"
            raise GrantError(msg) from self._record_failure
        async with self._resource.held():
            return self._log.append(grant)

    async def live(self, *, source: str, use: GrantScope) -> SourceGrant | None:
        """Return the live grant covering ``source`` for ``use``, or ``None``.

        Read inside the modelled resource, like every other method: a durable
        store would answer this from under its connection lock, so it is one of
        the lock sites ADR-0060's clause binds.

        Raises:
            GrantError: If a failure is scripted (:meth:`fail_live`).
        """
        if self._live_failure is not None:
            msg = "fake: the grant store could not be read"
            raise GrantError(msg) from self._live_failure
        async with self._resource.held():
            return self._log.live(source, use)

    async def recent(self, *, limit: int = 50) -> list[SourceGrant]:
        """Return up to ``limit`` records, newest first, ties broken by id.

        Raises:
            ValueError: If ``limit`` is not strictly positive.
        """
        if limit <= 0:
            msg = f"limit must be strictly positive, got {limit}"
            raise ValueError(msg)
        async with self._resource.held():
            return self._log.snapshots(limit)

    async def export(self) -> list[SourceGrant]:
        """Return every record, in :meth:`recent`'s order."""
        async with self._resource.held():
            return self._log.snapshots()

    async def clear(self) -> int:
        """Delete every record, returning the number removed.

        The body runs inside the modelled resource for :meth:`record`'s reason and
        for one of its own: the count returned must describe the deletion that
        actually happened, and sizing the log outside the resource would let a
        concurrent ``clear`` land between the two and let both callers report
        removing the same records.
        """
        async with self._resource.held():
            return self._log.clear()


__all__ = [
    "DEFAULT_DECIDED_AT",
    "DEFAULT_GRANTED_SOURCE",
    "FakeSourceGrantStore",
    "FakeSourceGrants",
    "revocation_of",
    "source_grant",
]
