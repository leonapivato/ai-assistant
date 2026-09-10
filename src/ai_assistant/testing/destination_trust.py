"""The canonical ``DestinationTrustStore`` fake (ADR-0238 §1, §14).

The triad's third artifact. A non-persistent store over a list, holding the same
clauses the durable one holds and refusing everything it refuses, so a consumer
verified against this one is verified against the contract rather than against a
convenience.

**It is deliberately not a filing cabinet.** ADR-0238 §1 makes ``record`` an active
participant — write-once over the id, a refusal of an empty destination set, a
refusal of a record duplicating a **live** record's destination set, and all of it
indivisible with the append — and every one of those is here. A fake looser than the
contract would certify consumers the real implementation rejects (ADR-0026 §7).

**The exclusion is real, not asserted.** Every method runs inside a
:class:`~ai_assistant.testing.cancellation.SuspendableResource`, so this fake is a
subject for ADR-0060's cancellation clause at the lock sites a durable store has —
and the checks sit *inside* it, which is what makes the shared suite's concurrent
``record`` case a real test rather than a vacuous one.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, final

from pydantic import ValidationError

from ai_assistant.core.errors import (
    DuplicateDestinationTrustError,
    InvalidDestinationTrustError,
)
from ai_assistant.core.types import (
    DestinationTrust,
    DestinationTrustRecord,
    describe_untrusted,
)
from ai_assistant.testing._detachment import field_state
from ai_assistant.testing.cancellation import LoopSuspension, ResourceLog, SuspendableResource

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime

    from ai_assistant.core.types import CanonicalDestination

__all__ = ["FakeDestinationTrustStore"]


@final
class FakeDestinationTrustStore:
    """A non-persistent, conforming ``DestinationTrustStore`` test double.

    Structurally implements
    :class:`~ai_assistant.core.protocols.DestinationTrustStore`.

    **What it keeps and what it hands back are different objects.** Every record is
    revalidated on the way in — through the class's own serializer, recursively — and
    every read rebuilds, so nothing a caller mutates reaches the store and nothing of
    the store's is reachable from what a caller receives. That is ADR-0238 §1's
    detachment obligation, held here for the same reason the durable store holds it
    rather than because a test needed it.
    """

    def __init__(self, records: Sequence[DestinationTrustRecord] = ()) -> None:
        """Create the store.

        Args:
            records: The history it starts with, applied in order under the same
                invariants :meth:`record` applies — so a history a conforming store
                could not hold is refused here rather than at the first read.

        Raises:
            InvalidDestinationTrustError: If ``records`` is not a history a conforming
                store could hold.
        """
        self._records: list[DestinationTrustRecord] = []
        self._resource = SuspendableResource()
        self._read_failure: Exception | None = None
        self._write_failure: Exception | None = None
        #: Whether :meth:`trust_of` can read at all. Its own flag rather than
        #: ``_read_failure``'s, because ADR-0238 §1 makes an unreadable store an
        #: *answer* on that member (``UNCHOSEN``) and an error on every other.
        self._trust_readable = True
        for held in records:
            self._append(held)

    # --- test-only hooks, deliberately off the seam ------------------------

    def suspend_next_operation(self) -> LoopSuspension:
        """Hold the next call that enters the modelled resource open inside it.

        There is one modelled resource and every method enters it, so this suspends
        whichever call arrives next rather than a named operation. The hook the
        cancellation case takes (ADR-0060 §3); test-only, and not part of the
        contract — the Protocol grows no affordance for it.

        Returns:
            The handle to wait on and release.
        """
        return self._resource.suspend_next()

    @property
    def resource_log(self) -> ResourceLog:
        """When each call was inside the modelled resource (ADR-0060's case reads it)."""
        return self._resource.log

    def fail_reads(self, error: Exception | None = None) -> None:
        """Arm every subsequent :meth:`live` and :meth:`export` to raise a store fault.

        **It does not arm** :meth:`trust_of`, and that asymmetry is ADR-0238 §1's
        clause rather than a gap: the trust of a destination is ``UNCHOSEN`` "where a
        record cannot be read", so an unreadable store is an *answer* on that member
        and not an error. :meth:`break_trust_reads` is the hook for that case.

        Args:
            error: The underlying fault, preserved as ``__cause__``.
        """
        self._read_failure = (
            error if error is not None else RuntimeError("fake: the store is unreadable")
        )

    def break_trust_reads(self) -> None:
        """Make :meth:`trust_of` unable to read, so the suite can drive §1's fail-closed arm.

        Distinct from :meth:`fail_reads` because the two clauses differ: this one has
        no error to observe, only an answer — ``UNCHOSEN`` — and a suite that scripted
        it through an exception would be asserting the opposite of what §1 says.
        """
        self._trust_readable = False

    def fail_writes(self, error: Exception | None = None) -> None:
        """Arm every subsequent :meth:`record` and :meth:`revoke` to raise a store fault.

        A **store fault** rather than a refusal: a refusal is what the invariants
        already produce from a badly-formed record, and a caller arranging one of
        those builds the record instead. What this scripts is the other failure — "the
        store could not be written" — which no well-formed input can provoke. Both
        arrive as :class:`~ai_assistant.core.errors.InvalidDestinationTrustError`,
        because ADR-0238 §13 closes this decision's error surface at that one name.

        Args:
            error: The underlying fault, preserved as ``__cause__``.
        """
        self._write_failure = (
            error if error is not None else RuntimeError("fake: the store is unwritable")
        )

    # --- internals ---------------------------------------------------------

    def _refuse_read(self) -> None:
        """Raise the scripted read fault, if one is armed.

        Raises:
            InvalidDestinationTrustError: If :meth:`fail_reads` armed one.
        """
        if self._read_failure is not None:
            msg = "fake: the destination-trust store could not be read"
            raise InvalidDestinationTrustError(msg) from self._read_failure

    def _refuse_write(self) -> None:
        """Raise the scripted write fault, if one is armed.

        Raises:
            InvalidDestinationTrustError: If :meth:`fail_writes` armed one.
        """
        if self._write_failure is not None:
            msg = "fake: the destination-trust store could not be written"
            raise InvalidDestinationTrustError(msg) from self._write_failure

    def _append(self, record: DestinationTrustRecord) -> str:
        """Apply ADR-0238 §1's write invariants and append, as one act.

        The checks are here rather than in :meth:`record` so that they and the append
        share one body: there is no ``await`` between them, which is how the atomicity
        §1 requires is obtained on a single event loop.

        Raises:
            DuplicateDestinationTrustError: If it duplicates a **live** record's
                destination set (ADR-0242 §2). The one ground on which the user's
                recourse is no act at all, told apart by its **type** so that no
                surface has to parse a message or read the store back.
            InvalidDestinationTrustError: If the record does not validate or if its id
                is already recorded. The base class still catches the duplicate-set
                ground too, so a caller wanting one handler keeps one.
        """
        snapshot = _revalidated(record)
        if any(held.id == snapshot.id for held in self._records):
            msg = (
                f"destination trust record {snapshot.id!r} is already recorded; the store is "
                f"write-once, so history cannot be rewritten by replaying a write"
            )
            raise InvalidDestinationTrustError(msg)
        for held in self._records:
            if held.revoked_at is None and held.destinations == snapshot.destinations:
                msg = (
                    f"destination trust record {snapshot.id!r} names the destination set live "
                    f"record {held.id!r} already names; revoking one would leave the other "
                    f"standing and the user would have revoked nothing (ADR-0238 §1)"
                )
                raise DuplicateDestinationTrustError(msg)
        self._records.append(snapshot)
        return snapshot.id

    def _ordered(self, *, live_only: bool) -> list[DestinationTrustRecord]:
        """The stored records, newest act first with ``id`` ascending as the tie-break.

        Rebuilt on the way out, so a caller holds no object this store keeps.
        """
        chosen = [held for held in self._records if not live_only or held.revoked_at is None]
        chosen.sort(key=lambda held: (-held.established_at.timestamp(), held.id))
        return [_revalidated(held) for held in chosen]

    # --- the contract ------------------------------------------------------

    async def record(self, record: DestinationTrustRecord) -> str:
        """Append ``record`` and return its id (ADR-0238 §1).

        The invariant checks are *inside* the resource, not before it: a caller that
        validated against a store it no longer holds could pass a duplicate id or an
        absent destination set that the append then contradicts. This is where "no
        interleaving point between the checks and the append" is actually kept once
        there is a lock at all.

        Raises:
            DuplicateDestinationTrustError: If it duplicates a **live** record's
                destination set (ADR-0242 §2) — the one ground on which the user's
                recourse is no act at all, told apart by its type.
            InvalidDestinationTrustError: If a store fault is scripted
                (:meth:`fail_writes`), if the record does not satisfy its own model,
                or if its id is already recorded.
        """
        self._refuse_write()
        async with self._resource.held():
            return self._append(record)

    async def trust_of(self, destinations: Sequence[CanonicalDestination]) -> DestinationTrust:
        """The recorded trust of ``destinations`` (ADR-0238 §1).

        ``USER_CHOSEN`` only where **every** member is a member of **some one** live
        record's set; ``UNCHOSEN`` otherwise, including for an empty sequence, a
        partial match, a match spanning two records, and a store that cannot be read.

        **It raises for nothing**, which is §1's clause: the trust of a destination is
        ``UNCHOSEN`` "in every other case, including … where a record cannot be read".
        A fake that raised here would certify a consumer against a branch the
        contract says does not exist.
        """
        # Snapshotted **before** the resource is entered, for the durable store's own
        # reason: a ``Sequence`` is the one caller-owned argument on this seam that is
        # not immutable, and a caller that emptied its list while the call was
        # suspended would otherwise make the coverage check's ``all(...)`` vacuously
        # true — answering ``USER_CHOSEN`` for the empty sequence ADR-0238 §1 refuses.
        # The fake must not be the looser of the two (ADR-0026 §7).
        wanted = tuple(destinations)
        async with self._resource.held():
            if not wanted or not self._trust_readable:
                return DestinationTrust.UNCHOSEN
            for held in self._records:
                if held.revoked_at is not None:
                    continue
                covered = set(held.destinations)
                if all(destination in covered for destination in wanted):
                    return DestinationTrust.USER_CHOSEN
            return DestinationTrust.UNCHOSEN

    async def revoke(self, record_id: str, revoked_at: datetime) -> None:
        """Withdraw ``record_id``, prospectively and idempotently (ADR-0238 §1).

        A second revocation leaves the first instant standing rather than restamping
        it, and no other field of the record is touched — §1's "rewrites no recorded
        decision", which the durable store enforces with a trigger and this one holds
        by construction.

        Raises:
            InvalidDestinationTrustError: If a store fault is scripted
                (:meth:`fail_writes`), if ``record_id`` names no record this store
                holds, or if ``revoked_at`` is not a usable instant.
        """
        self._refuse_write()
        async with self._resource.held():
            for position, held in enumerate(self._records):
                if held.id != record_id:
                    continue
                if held.revoked_at is not None:
                    return
                self._records[position] = _revalidated(
                    held.model_copy(update={"revoked_at": revoked_at})
                )
                return
            msg = (
                f"destination trust record {describe_untrusted(record_id)} is not recorded, so "
                f"there is nothing to revoke (ADR-0238 §1)"
            )
            raise InvalidDestinationTrustError(msg)

    async def live(self) -> list[DestinationTrustRecord]:
        """Every unrevoked record, newest act first (ADR-0238 §1).

        Raises:
            InvalidDestinationTrustError: If a read fault is scripted
                (:meth:`fail_reads`).
        """
        self._refuse_read()
        async with self._resource.held():
            return self._ordered(live_only=True)

    async def export(self) -> list[DestinationTrustRecord]:
        """**Every** record, revoked ones included, in :meth:`live`'s order (§1).

        The user's export right (ADR-0004 §6). It omits nothing, and delegating it to
        :meth:`live` would drop exactly the records the right is for.

        Raises:
            InvalidDestinationTrustError: If a read fault is scripted
                (:meth:`fail_reads`).
        """
        self._refuse_read()
        async with self._resource.held():
            return self._ordered(live_only=False)


def _revalidated(record: DestinationTrustRecord) -> DestinationTrustRecord:
    """Rebuild ``record`` as a validated, recursively detached record (ADR-0238 §1).

    The fake owes this in the same words the durable store does. ``model_dump`` is an
    ordinary overridable method, so a subclass can return a mapping that does not
    describe itself — a one-destination instance whose dump names two — and the store
    would then hold a record over a destination the user never named.
    :func:`~ai_assistant.testing._detachment.field_state` is the class's own
    serializer, and it detaches recursively: ``frozen=True`` refuses
    ``destination.canonical = …`` and does not refuse
    ``destination.__dict__["canonical"] = …``.

    Raises:
        InvalidDestinationTrustError: If the record does not satisfy its own model or
            carries state ``DestinationTrustRecord`` declares no field for.
    """
    try:
        return DestinationTrustRecord.model_validate(field_state(DestinationTrustRecord, record))
    except (ValidationError, ValueError) as exc:
        msg = f"destination trust record is not a valid record: {describe_untrusted(exc)}"
        raise InvalidDestinationTrustError(msg) from exc
