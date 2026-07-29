"""Ingesting proposed memories: conflict detection, policy, and application.

``MemoryIngestor`` closes the propose/dispose/persist loop. Given a
:class:`~ai_assistant.core.types.MemoryUpdateProposal` (the "propose" half), it:

1. detects conflicting existing memories (same kind, highly similar content),
2. asks the injected :class:`~ai_assistant.core.protocols.MemoryPolicy` to rule
   on the proposal given those conflicts (the "dispose" half), and
3. applies the ruling to the injected
   :class:`~ai_assistant.core.protocols.MemoryStore` (the "persist" half).

It depends only on the store and policy contracts, so it is agnostic to which
concrete store or policy is wired in.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from math import isfinite
from typing import TYPE_CHECKING

from ai_assistant.core.clock import ClockReadingError, checked_clock
from ai_assistant.core.errors import (
    MemoryStoreConflictError,
    MemoryStoreError,
    UnresolvedEvidenceError,
)
from ai_assistant.core.types import (
    BeliefBand,
    MemoryDecisionKind,
    MemoryIngestResult,
    MemoryKind,
    MemorySource,
    MemoryWrite,
    MemoryWriteMode,
    Provenance,
    Validity,
    band_of,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from ai_assistant.core.clock import Clock
    from ai_assistant.core.protocols import MemoryPolicy, MemoryStore
    from ai_assistant.core.types import MemoryDecision, MemoryRecord, MemoryUpdateProposal

_DEFAULT_CONFLICT_THRESHOLD = 0.75

#: The **ceiling** on the conflicts one ingest resolves, not a truncation budget
#: (ADR-0079 §1). At or below it the whole detected set reaches the policy and a
#: ``SUPERSEDE`` retires all of it; above it the ingest refuses. That re-founding
#: is why the value is 100 rather than ADR-0050's 5: a truncation budget wants to
#: be small, a circuit breaker wants to be an order of magnitude past any ordinary
#: correction — above 100 above-threshold same-kind conflicts the store is holding
#: a runaway, and a correction is the wrong moment to discover that quietly.
_DEFAULT_CONFLICT_LIMIT = 100

#: How many times supersession re-mints a colliding id before giving up. A minted
#: id (``uuid4``) collides with vanishing probability, so a handful of attempts is
#: already far past any real collision; the bound exists to make a *pathological*
#: id factory (one that always collides) fail loudly rather than spin (ADR-0045 §4).
_MAX_SUPERSEDE_ATTEMPTS = 5


def _uuid() -> str:
    return str(uuid.uuid4())


# The only targets a user assertion may be folded onto (ADR-0038 §2a). Held here
# as well as in `policy`, deliberately: the policy chooses, but `MemoryIngestor`
# takes rulings from *any* injected `MemoryPolicy`, so the safety property has to
# hold at the boundary that performs the write rather than at the one that
# recommends it.
_SUPERSEDABLE = frozenset({MemorySource.OBSERVED, MemorySource.INFERRED})


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _check_tuning(*, conflict_threshold: float, conflict_limit: int) -> None:
    """Reject conflict tuning that would disable a stage while looking healthy.

    Relocated from ``LearningLoop`` with the values themselves (ADR-0028 §4a),
    so ADR-0022 §4a's guarantee is moved rather than retired: the same values
    are refused at the same moment, by the object that reads them. Each is a
    *silent* misconfiguration, which is why it is refused at construction rather
    than left to surface as behaviour. ``conflict_limit=0`` hands the policy no
    conflicts, so every proposal is ruled on as though nothing contradicted it,
    and a duplicate is accepted while the caller reports a healthy write. A
    ``NaN`` threshold compares ``False`` against every score and does the same.

    Raises:
        TypeError: If ``conflict_limit`` is not an integer, or
            ``conflict_threshold`` is a ``bool``.
        ValueError: If ``conflict_limit`` is below 1, or ``conflict_threshold``
            is not a finite value in ``[0, 1]`` — the range a
            ``MemoryRecord.score`` occupies.
    """
    # `isinstance` rather than a bare `< 1`, which `1.5` and `inf` both survive
    # — and a non-integral limit reaches `MemoryStore.search`, where a store
    # slicing by it raises `TypeError` far from the mistake. `bool` is excluded
    # because it is an `int` subclass and a flag is not a count.
    if isinstance(conflict_limit, bool) or not isinstance(conflict_limit, int):
        msg = f"conflict_limit must be an integer, got {conflict_limit!r}"
        raise TypeError(msg)
    if conflict_limit < 1:
        msg = f"conflict_limit must be at least 1, got {conflict_limit}"
        raise ValueError(msg)
    # Checked before the range test, which a `bool` silently survives: `bool` is
    # an `int` subclass, so `isfinite(True)` holds and `0.0 <= True <= 1.0` is
    # true — a flag would be read as the threshold 1.0, restricting conflicts to
    # perfect-score matches. Rejected for the same reason the limit rejects one.
    if isinstance(conflict_threshold, bool):
        msg = f"conflict_threshold must be a real number, got {conflict_threshold!r}"
        raise TypeError(msg)
    if not isfinite(conflict_threshold) or not 0.0 <= conflict_threshold <= 1.0:
        msg = f"conflict_threshold must be a finite value in [0, 1], got {conflict_threshold!r}"
        raise ValueError(msg)


def _refuse_unsafe_fold(
    target: MemoryRecord, incoming: MemoryRecord, kind: MemoryDecisionKind
) -> None:
    """Refuse a fold that would destroy data, gated on the ruling where it must be.

    Runs before either a ``REINFORCE`` or a ``SUPERSEDE`` arm is selected. Two
    folds are refused; they differ in whether the ruling matters, because
    ADR-0045 §4 made only ``SUPERSEDE`` mint a new id while ``REINFORCE`` still
    folds at the *target's* id:

    - **Clause 1 — any fold onto a ``USER_ASSERTED`` target.** Kept **record-keyed
      for both rulings** (ADR-0045 §5). A window-closing ``SUPERSEDE`` no longer
      *destroys* the assertion, but the conflict signal is topical similarity, not
      contradiction (ADR-0038 §5), and is too weak to retire a record the user
      gave us — a justification the window does not touch. So nothing, of any
      source, under either ruling, may fold onto an assertion.
    - **Clause 2 — a ``USER_ASSERTED`` proposal onto an ``EXTERNAL`` target,
      ``REINFORCE`` only.** The external id is that system's idempotency key. A
      ``REINFORCE`` still inherits it, so the correction is overwritten by the next
      routine sync (ADR-0038 §2a) — the refusal stays. A ``SUPERSEDE`` now gets a
      *fresh* id (ADR-0045 §4), so that hazard is gone and an ``EXTERNAL``
      supersession is permitted at the writer boundary (ADR-0045 §5b). The arm is
      therefore **narrowed to ``REINFORCE``**, not removed.

    ``DefaultMemoryPolicy`` proposes none of these — rule 2 defers, and rule 3
    supersedes only ``OBSERVED``/``INFERRED`` — but a policy reaches the
    ingestor through an injected seam and any conforming implementation may rule
    differently. The refusal therefore lives here, at the boundary that performs
    the write, rather than in the policy that recommends it.

    Fail-closed rather than silently downgrading, for the reason that already
    makes an absent fold target raise instead of falling back to storing the
    proposal as new: a write that loses data while reporting success is worse
    than one that stops.

    Raises:
        MemoryStoreError: If the fold is one of the two above.
    """
    if target.provenance.source is MemorySource.USER_ASSERTED:
        msg = (
            f"refusing to fold onto {target.id!r}: a {incoming.provenance.source} record may not "
            f"be folded onto a user-asserted one, whose belief it would overwrite "
            f"(ADR-0038 §3, ADR-0045 §5)"
        )
        raise MemoryStoreError(msg)
    if (
        kind is MemoryDecisionKind.REINFORCE
        and incoming.provenance.source is MemorySource.USER_ASSERTED
        and target.provenance.source not in _SUPERSEDABLE
    ):
        msg = (
            f"refusing to reinforce {target.id!r}: a user assertion may not be reinforced onto a "
            f"{target.provenance.source} record, whose id it would inherit and the next sync "
            f"overwrite — only OBSERVED and INFERRED beliefs may be reinforced this way "
            f"(ADR-0038 §2a, narrowed to REINFORCE by ADR-0045 §5b)"
        )
        raise MemoryStoreError(msg)


def _checked_id(id_factory: Callable[[], str], *, owner: str) -> str:
    """Read the injected id factory, guarding its output like the clock (ADR-0045 §4).

    Mirrors :func:`~ai_assistant.core.clock.checked_clock`: the minted id is
    installed with ``model_copy(update=...)``, which skips validators, so a
    ``None``, non-``str`` or empty reading would otherwise reach the store
    unchecked — and the two writers would diverge, the in-memory fake storing
    under a bad key while SQLite rejects it (the exact "consumer test passes on
    state the production writer refuses" trap ADR-0045 §4 names). The factory's
    own raising is caught and re-raised as ``MemoryStoreError`` too, so a
    malformed factory fails the write loudly rather than propagating an arbitrary
    exception across the writer seam (ADR-0028 §5).

    An **exact** ``str`` is required, not merely an ``isinstance`` one: a hostile
    ``str`` *subclass* (say one whose ``__hash__`` raises) passes ``isinstance`` and
    is then hashed as a dict/set key inside ``write_atomic``, leaking an arbitrary
    exception across the seam and defeating this guard. ``type(minted) is str``
    invokes no subclass code, so the check itself cannot be subverted.

    Raises:
        MemoryStoreError: If the factory raises, or returns anything that is not a
            non-empty built-in ``str`` — before any write is attempted.
    """
    try:
        minted = id_factory()
    except Exception as exc:  # any factory failure is the store's error, not the caller's
        msg = f"the id factory injected into {owner} raised while minting a supersession id"
        raise MemoryStoreError(msg) from exc
    if type(minted) is not str or not minted:
        # The message introspects *nothing* about the returned object — not
        # ``repr(minted)``, not ``type(minted).__name__`` — because a hostile object
        # could raise from ``__repr__`` or from a metaclass ``__getattribute__`` on
        # ``__name__``, leaking that exception and defeating the guard. Only ``owner``
        # (a caller-supplied plain str) appears. ``type(minted) is not str`` is itself
        # safe: it reads the type slot and compares identity, invoking no user code.
        msg = f"the id factory injected into {owner} did not return a non-empty built-in str"
        raise MemoryStoreError(msg)
    return minted


def _retirement_set(target: MemoryRecord, conflicts: list[MemoryRecord]) -> list[MemoryRecord]:
    """The full set of conflicting beliefs a ``SUPERSEDE`` retires (ADR-0050 §1, #244).

    A ``SUPERSEDE`` names the *relation* — the proposal overturns the belief the
    conflict set holds — not a single record (ADR-0040 §1). Every entry in
    ``conflicts`` is a same-kind, at-or-above-threshold contradiction the proposal
    just displaced, so retiring only the policy's best-ranked ``target`` would leave
    a second and third stale belief on the same topic live: exactly the honesty gap
    issue #244 reports. The applier therefore closes the window of the target **and**
    of every other conflict it is *warranted* to retire.

    The set is the named ``target`` plus every other conflict whose source is in
    :data:`_SUPERSEDABLE` (``OBSERVED``/``INFERRED``) — the derived beliefs a
    correction may displace. Two sources are held out of the *widening* on purpose:

    - ``USER_ASSERTED`` conflicts are never swept in — clause 1 stands, record-keyed,
      for both rulings (ADR-0045 §5): topical similarity may not retire a record the
      user gave us. ``DefaultMemoryPolicy`` never even reaches ``SUPERSEDE`` with an
      asserted conflict present (it rules ``ASK_USER``, ADR-0050 §2), but the applier
      excludes them regardless, since it takes rulings from any injected policy.
    - ``EXTERNAL`` conflicts are not auto-retired even though ADR-0045 §5b now permits
      an ``EXTERNAL`` supersession at the writer floor. Adopting ``EXTERNAL``
      supersession is a separate, still-deferred policy choice (ADR-0045 §5/§7); the
      widening stays within the ``{OBSERVED, INFERRED}`` class ``DefaultMemoryPolicy``
      already supersedes. An ``EXTERNAL`` target a custom policy *names* is still
      retired — it is the explicit ``target`` — but sibling ``EXTERNAL`` conflicts are
      left live.

    ``target`` leads the list (it is the primary the policy named and
    ``MemoryDecision`` audits); order among the rest follows ``conflicts`` (retrieval
    score), so the batch is deterministic. This needs no ``target_id`` widening in
    ``core`` — closing N windows is N atomic upserts, exactly what issue #244 and
    ADR-0045 §7 said the validity window makes possible without growing the contract.

    Since ADR-0079 §3 this set is a **``MemoryWriter`` contract obligation** rather
    than one implementation's habit, driven by the shared conformance suite and
    matched by ``FakeMemoryWriter``. Nothing here changed with the promotion — and
    nothing is discarded before this function any more either (ADR-0079 §1), so the
    "full set" it retires is now the full set retrieval surfaced.
    """
    others = [
        conflict
        for conflict in conflicts
        if conflict.id != target.id and conflict.provenance.source in _SUPERSEDABLE
    ]
    return [target, *others]


def _close_window(target: MemoryRecord, now: datetime) -> MemoryRecord:
    """Return ``target`` retired at the earlier of ``now`` and its own end (ADR-0080 §1).

    The target stays on disk — retained, off the read path — with
    ``valid_until = end``; ``valid_from`` and every other field are preserved.
    Written with ``model_copy(update=...)``, so ``now`` must already be a guarded,
    aware-UTC reading (the ingestor's :meth:`MemoryIngestor._now_utc`), and it is
    **one instant for the whole retirement set** (ADR-0080 §1), sampled by
    :meth:`MemoryIngestor._apply_supersede` before any close is computed.

    ADR-0080 §1 ratified the clamp these two lines had been carrying as unratified
    "correctness floors", and partially superseded ADR-0045 §4 step 1's unqualified
    ``valid_until = now`` in doing so:

    - **The clamp.** ``end = now`` where the window is unbounded at the end,
      otherwise ``end = min(now, valid_until)``. A retirement never widens a window,
      never moves its start, and never touches its content. Overwriting an earlier
      producer-set end with a later ``now`` would push a self-closed belief back onto
      the read path for ``[valid_until, now)``; retirement takes a belief *off* the
      read path and never puts one back. Where the record has already ended by its
      own terms the write back is a no-op on the window — which still counts as
      resolved and still rides in the batch (ADR-0080 §6), so the applier branches on
      nothing.
    - **The refusal.** If the chosen end is at or before ``valid_from`` (empty or
      inverted), refuse before the batch — including the **tie** ``end ==
      valid_from``, which is the half-open interval ``[F, F)`` and live at no instant
      (ADR-0080 §3). ``model_copy(update=...)`` skips ``Validity``'s validator, and
      ``SqliteMemoryStore``'s decode re-runs it on load, so persisting such a window
      would store a record the store cannot read back. Under a close-coherent
      composition this fires only at that tie; anything else that reaches it is a
      store read *ahead* of the writer's close, which is the clock-coherence gap
      issue #460 carries.

    The refusal is deliberately **not** hoisted into detection: a window that cannot
    be closed is a problem only for a record a ruling actually retires, so refusing
    earlier would fail ``ACCEPT`` and ``REINFORCE`` ingests that touch no window
    (ADR-0080 §6). It raises plain ``MemoryStoreError`` and specifically **not**
    ``UnresolvedEvidenceError``, which names a proposal whose *evidence* does not
    resolve rather than a *target's* window (ADR-0080 §7).

    Raises:
        MemoryStoreError: If the chosen end is at or before ``valid_from`` (empty or
            inverted); nothing is written and every record in the set is unchanged.
    """
    window = target.validity
    end = now if window.valid_until is None else min(now, window.valid_until)
    if window.valid_from is not None and end <= window.valid_from:
        msg = (
            f"cannot retire {target.id!r}: a close at {end.isoformat()} is at or before its "
            f"valid_from {window.valid_from.isoformat()} — an unrepresentable window the store "
            f"would reject (ADR-0080 §3)"
        )
        raise MemoryStoreError(msg)
    return target.model_copy(update={"validity": window.model_copy(update={"valid_until": end})})


def _supersede(incoming: MemoryRecord, new_id: str) -> MemoryRecord:
    """The superseding record: ``incoming`` at a fresh, target-free id (ADR-0045 §4).

    Nothing of the overturned belief is carried onto the record that overturns
    it — least of all its ``evidence``. ADR-0005 §2 defines that field as
    references *supporting* the record, so unioning the contradicted record's
    evidence into a correction would attach the observations that produced the
    wrong belief as justification for the right one: a fabricated warrant in the
    one field callers use to explain why a memory exists (ADR-0038 §1a).

    A user's assertion is its own warrant and needs no borrowed support, so the
    superseding record is simply ``incoming`` — its provenance is already exactly
    right — written at a **freshly-minted** id, not the target's. ADR-0045 §4
    stopped rehoming the correction onto the stale id: the target is retained with
    a closed window (:func:`_close_window`) and the correction becomes a *new*
    record. The id is also not ``incoming.id`` — that is caller-supplied and could
    name an unrelated live record — but the minted id, which is written
    insert-if-absent so a collision is rejected, not clobbered.

    The correction is given a **fresh open window** (ADR-0045 §4), overriding any
    ``validity`` the proposal happened to carry: the whole point of a supersession
    is to install a *live* belief, so a proposal with a producer-set closed or
    future-dated window must not leave the store with the target retired and the
    correction already hidden or not yet live — which would be no live belief at
    all. Every other field of ``incoming`` is kept (§5a: the live record is the
    proposed record but for its id and window).
    """
    return incoming.model_copy(update={"id": new_id, "validity": Validity()})


def _merge(target: MemoryRecord, incoming: MemoryRecord) -> MemoryRecord:
    """Fold ``incoming`` into ``target``, keeping the target's id.

    Newer content wins; evidence is unioned and confidence taken as the maximum,
    so a merge strengthens rather than weakens what is known.

    **Reinforcement only.** Both halves of that — the union and the maximum —
    assume the two records *agree*. Only a ``REINFORCE`` ruling reaches this
    function (ADR-0040 §3): a contradiction is a ``SUPERSEDE``, which
    :meth:`MemoryIngestor._apply` routes to :func:`_supersede` instead.
    """
    provenance = Provenance(
        source=incoming.provenance.source,
        confidence=max(target.provenance.confidence, incoming.provenance.confidence),
        evidence=tuple(dict.fromkeys([*target.provenance.evidence, *incoming.provenance.evidence])),
        last_updated=incoming.provenance.last_updated,
    )
    return incoming.model_copy(update={"id": target.id, "provenance": provenance})


class MemoryIngestor:
    """Runs a proposed memory through conflict detection, policy, and storage.

    Structurally satisfies :class:`~ai_assistant.core.protocols.MemoryWriter`
    (ADR-0028 §2), which is how `orchestration` reaches this write path without
    importing it.
    """

    def __init__(  # noqa: PLR0913 — one parameter per injected collaborator plus two knobs
        self,
        *,
        store: MemoryStore,
        policy: MemoryPolicy,
        conflict_threshold: float = _DEFAULT_CONFLICT_THRESHOLD,
        conflict_limit: int = _DEFAULT_CONFLICT_LIMIT,
        now: Clock = _utcnow,
        id_factory: Callable[[], str] = _uuid,
    ) -> None:
        """Initialise the ingestor.

        Args:
            store: Where accepted memories are persisted and conflicts sought.
            policy: The deterministic policy that rules on each proposal.
            conflict_threshold: Minimum retrieval score for an existing record to
                count as conflicting with the proposal.
            conflict_limit: The **ceiling** on the conflicts one ingest resolves
                (ADR-0079 §1). At or below it the whole detected set reaches the
                policy; above it :meth:`_detect_conflicts` refuses. Its value stays
                tuning — only the behaviour at the boundary is contract.
            now: Clock used to stamp expiry on temporary stores and to close a
                superseded target's window; injectable for deterministic tests.
                Guarded by :func:`~ai_assistant.core.clock.checked_clock`, which is
                what protects :meth:`_expiry`'s and :meth:`_apply_supersede`'s
                ``model_copy(update=...)`` writes — those skip validators, so the
                producer is the only place left to catch a non-conforming reading
                (ADR-0026 §2).
            id_factory: Mints the fresh id a ``SUPERSEDE`` writes its correction at
                (ADR-0045 §4); injectable so tests assert exact ids, mirroring the
                clock and ADR-0022 §5's goal-id factory. Guarded at its output by
                :func:`_checked_id`, for the same reason the clock is: the id is
                installed with ``model_copy(update=...)``, so a non-``str`` or empty
                reading would reach the store unchecked. Defaults to random UUIDs.

        Raises:
            TypeError: If ``conflict_limit`` is not an integer, or
                ``conflict_threshold`` is a ``bool`` (see :func:`_check_tuning`).
            ValueError: If ``conflict_limit`` is below 1, or
                ``conflict_threshold`` is not a finite value in ``[0, 1]`` (see
                :func:`_check_tuning`).
        """
        _check_tuning(conflict_threshold=conflict_threshold, conflict_limit=conflict_limit)
        self._store = store
        self._policy = policy
        self._conflict_threshold = conflict_threshold
        self._conflict_limit = conflict_limit
        self._clock = checked_clock(now, owner="MemoryIngestor")
        self._id_factory = id_factory
        # Guards the read-modify-write in `ingest` (issue #248). Constructed
        # here rather than lazily because since Python 3.10 an `asyncio.Lock`
        # binds no loop until it is first awaited, so an ingestor may be built
        # before the loop exists.
        #
        # One lock for all proposals, deliberately. The finest key that would
        # still be *correct* is the proposal's `MemoryKind`, since
        # `_detect_conflicts` searches within one kind and `_apply` refuses a
        # target outside the conflicts, so two proposals of different kinds can
        # never contend for a record. It is rejected on cost, not correctness:
        # it buys concurrency between kinds that nothing has asked for, on a
        # section whose only awaits are two store calls and a deterministic
        # policy, and it pays by making the safety property depend on conflict
        # detection staying kind-scoped — a coupling a later cross-kind
        # conflict rule would break silently, which is the failure mode this
        # change exists to remove.
        self._lock = asyncio.Lock()

    async def ingest(self, proposal: MemoryUpdateProposal) -> MemoryIngestResult:
        """Detect conflicts, apply the policy, and persist the outcome.

        The three steps are one **read-modify-write**: a fold (``REINFORCE`` or
        ``SUPERSEDE``) folds the proposal into a conflict snapshot taken by the
        search above it, and writes the result back at that record's id.
        Interleaved, two ingests both snapshot the same target before either
        writes, and the second ``add`` silently discards the first — with both
        callers handed a healthy result. Since ADR-0038 the discarded write may
        be a user correction, so the whole sequence is serialised on a lock held
        by this ingestor.

        What that does **not** cover, stated plainly because the guarantee is
        narrower than "ingestion is safe":

        - **Only this ingestor.** Two ``MemoryIngestor`` instances over one
          store hold two different locks and race exactly as before.
        - **Only this process.** An in-process lock says nothing about two
          processes sharing a store file. Closing that needs a compare-and-swap
          on the store itself — a ``MemoryStore`` contract change, tracked as
          issue #104 with issue #248.

        The lock spans the injected policy's ``decide`` as well, because the
        ruling is what the write is derived from; a policy that blocks on I/O
        therefore blocks other ingests. That is the cost of the guarantee, not
        an oversight.

        **Three refusals precede or replace a ruling**, in the order they fire:

        1. **Unresolvable evidence** (ADR-0077 §5): a ``DERIVED`` proposal citing a
           record this store does not hold raises ``UnresolvedEvidenceError``
           naming every such id, before conflict detection and before the policy is
           asked (:meth:`_require_resolvable_evidence`).
        2. **Over the conflict ceiling** (ADR-0079 §1): detection surfacing more
           conflicts than :data:`_DEFAULT_CONFLICT_LIMIT` — whatever this ingestor
           was tuned to — raises ``MemoryStoreError`` with nothing written and no
           ruling sought (:meth:`_detect_conflicts`).
        3. **An unretirable window** (ADR-0080 §3): a ``SUPERSEDE`` whose retirement
           set holds a record whose window cannot be closed representably raises
           ``MemoryStoreError`` before the atomic batch (:func:`_close_window`).

        Args:
            proposal: The memory update to rule on and persist.

        Returns:
            The policy's decision and the id written, if anything was written.

        Raises:
            UnresolvedEvidenceError: If a ``DERIVED`` proposal cites a record the
                store does not hold; nothing is written and the policy is not asked.
            MemoryStoreError: If detection surfaces more conflicts than this
                ingestor will resolve in one ingest, if a retirement's window cannot
                be closed, or on any other store or applier failure.
        """
        # One observation of the caller's proposal, taken on this coroutine's
        # first executed line — before the lock, which is `ingest`'s first await
        # (`core.protocols`' input clause, ADR-0065; issue #366). Everything below
        # reads only this copy. Without it the sequence reads `proposal.proposed`
        # three times across two awaits: once to search for conflicts, once inside
        # the injected policy, and once to build what is written. `MemoryRecord`
        # is mutable and `DefaultMemoryPolicy` is only one of the policies this
        # seam accepts — a model-backed one would widen the window to a network
        # call — so a caller that mutated its own record mid-flight could make
        # `_retirement_set` close the windows of beliefs contradicting the content
        # searched *first* while the record installed came from the read *last*.
        # Not a torn record (the store snapshots its own input, ADR-0056) but a
        # semantic desync one level up: beliefs retired over a statement that was
        # never stored.
        observed = proposal.model_copy(deep=True)
        async with self._lock:
            return await self._ingest(observed)

    async def _ingest(self, observed: MemoryUpdateProposal) -> MemoryIngestResult:
        await self._require_resolvable_evidence(observed.proposed)
        conflicts = await self._detect_conflicts(observed.proposed)
        # Shallow is right here: this copies the ingestor's *own* snapshot, whose
        # `proposed` no caller holds a reference to.
        observed = observed.model_copy(
            update={"conflicts": tuple(record.id for record in conflicts)}
        )
        decision = await self._policy.decide(observed, conflicts=conflicts)
        record_id = await self._apply(decision, observed.proposed, conflicts)
        return MemoryIngestResult(decision=decision, record_id=record_id)

    async def _require_resolvable_evidence(self, record: MemoryRecord) -> None:
        """Refuse a ``DERIVED`` proposal citing a record this store does not hold.

        ADR-0077 §5's write-time resolvability floor, and the first thing an ingest
        does: it runs **before** conflict detection and before the policy is asked,
        because a proposal whose warrant does not exist is inadmissible rather than
        rule-able. The refusal is a raise and not a fabricated ``REJECT`` — a ruling
        is the policy's to make (ADR-0005 §3), and a writer inventing one would put
        a decision nobody made into the ingest result.

        Scoped to the ``DERIVED`` band, because that is the band ADR-0072 §3
        obliges to cite. It is deliberately **not** a floor on citing *nothing*: an
        empty tuple names no record that fails to resolve, so it passes here and is
        the ``MemoryPolicy``'s to judge (``DefaultMemoryPolicy`` rule 2). Putting
        one rule in two places is what ADR-0077 §5 exists to avoid.

        The ids are reported **in citation order** and de-duplicated, so a caller
        comparing them against the batch it selected reads each failure once
        (:class:`~ai_assistant.core.errors.UnresolvedEvidenceError`). *Every*
        unresolved id is named rather than the first: the stage's race-versus-bug
        discrimination is a quantified statement over the whole set, and a partial
        list would let a producer bug hide behind an expiry that accompanied it.

        Raises:
            UnresolvedEvidenceError: If any cited id names no record the store
                returns; nothing is written and no ruling is sought.
        """
        if band_of(record.provenance.source) is not BeliefBand.DERIVED:
            return
        unresolved: list[str] = []
        for cited in dict.fromkeys(record.provenance.evidence):
            if await self._store.get(cited) is None:
                unresolved.append(cited)
        if unresolved:
            msg = (
                f"refusing to ingest {record.id!r}: its {record.provenance.source} provenance "
                f"cites {len(unresolved)} record(s) this store does not hold — "
                f"{', '.join(repr(cited) for cited in unresolved)} (ADR-0077 §5)"
            )
            raise UnresolvedEvidenceError(msg, unresolved)

    async def _detect_conflicts(self, record: MemoryRecord) -> list[MemoryRecord]:
        """Return every conflict retrieval surfaced, or refuse above the ceiling.

        ``conflict_limit`` is a **ceiling, not a truncation budget** (ADR-0079 §1):
        at or below it the whole detected set is handed to the policy — nothing this
        method holds is discarded — and above it the ingest refuses, writing nothing,
        closing no window and asking for no ruling. Truncating instead would defeat
        more than the retirement set: ``DefaultMemoryPolicy``'s two asserted-conflict
        gates are predicates over the set they are *handed*, so an assertion ranked
        past the cut would silently stop reaching them.

        **Two rows of headroom over the ceiling, for two independent reasons.** One
        is the standing over-fetch for the proposal's own record — the store applies
        the limit before this method can drop it, so at ``conflict_limit=1`` a
        re-proposal would otherwise spend its only slot on a record that is then
        discarded, hiding a genuine conflict ranked just below (#110). One extra
        suffices there: ids are unique in a store, so at most one match is the
        proposal itself. The other is ADR-0079 §1's **overflow probe**: without a
        row beyond the ceiling, "retrieval surfaced exactly ``conflict_limit``" and
        "it surfaced more" are indistinguishable.

        This is a bound, not a loop — one ranked read, as today, with a wider limit —
        so it makes no claim that retrieval is exhaustive. ``search`` returns "the
        records most relevant to ``query``, best first", which is what lets a row
        scoring below the threshold prove no later returned row scores at or above
        it; what it never surfaced is invisible here, and closing *that* is a
        ``MemoryStore`` obligation filed as issue #457.

        Raises:
            MemoryStoreError: If retrieval surfaced more conflicts than this
                ingestor will resolve in one ingest.
        """
        matches = await self._store.search(
            record.content,
            limit=self._conflict_limit + 2,
            kinds=[MemoryKind(record.kind)],
        )
        conflicts = [
            match
            for match in matches
            if match.id != record.id and (match.score or 0.0) >= self._conflict_threshold
        ]
        if len(conflicts) > self._conflict_limit:
            msg = (
                f"refusing to ingest {record.id!r}: conflict resolution surfaced more than "
                f"{self._conflict_limit} conflicting records, more than one ingest resolves. "
                f"Nothing was written and no ruling was sought — a correction resolves every "
                f"conflict it is shown, or it does not land (ADR-0079 §1)"
            )
            raise MemoryStoreError(msg)
        return conflicts

    async def _apply(
        self,
        decision: MemoryDecision,
        proposed: MemoryRecord,
        conflicts: list[MemoryRecord],
    ) -> str | None:
        match decision.kind:
            case MemoryDecisionKind.ACCEPT:
                return await self._store.add(proposed)
            case MemoryDecisionKind.STORE_TEMPORARY:
                expires_at = self._expiry(decision.ttl)
                return await self._store.add(proposed.model_copy(update={"expires_at": expires_at}))
            case MemoryDecisionKind.REINFORCE | MemoryDecisionKind.SUPERSEDE:
                target = next((c for c in conflicts if c.id == decision.target_id), None)
                if target is None:
                    # A fold naming an absent target must fail loudly: silently
                    # storing the proposal as new would create the duplicate the
                    # fold was meant to prevent, while reporting success.
                    msg = f"fold target {decision.target_id!r} is not among the conflicts"
                    raise MemoryStoreError(msg)
                _refuse_unsafe_fold(target, proposed, decision.kind)
                # Past the refusal, the ruling names the relation, so the ingestor
                # no longer reads provenance to recover it (ADR-0040 §3): SUPERSEDE
                # retires the contradicted belief (window-close) and writes the
                # correction as a new record, REINFORCE folds the two at the target's
                # id.
                if decision.kind is MemoryDecisionKind.SUPERSEDE:
                    return await self._apply_supersede(_retirement_set(target, conflicts), proposed)
                return await self._store.add(_merge(target, proposed))
            case _:  # REJECT, ASK_USER — nothing is written.
                return None

    async def _apply_supersede(self, targets: list[MemoryRecord], proposed: MemoryRecord) -> str:
        """Close every ``target``'s window and write ``proposed`` as a new record.

        ``targets`` is the full conflicting set a ``SUPERSEDE`` retires
        (:func:`_retirement_set`, ADR-0050 §1 / #244): the policy's best-ranked
        target leads, followed by every other supersedable conflict the correction
        contradicts. All of them plus the correction are one atomic batch —
        ``[UPSERT(T_closed) for each target] + [INSERT_IF_ABSENT(P_new)]`` — via
        :meth:`MemoryStore.write_atomic` (ADR-0046), so a failure part-way cannot
        leave some beliefs retired with no live replacement (the regression ADR-0045
        §8 refused to ship). Retiring N is as atomic and reversible-in-history as
        retiring one, which is why closing N windows needs no ``target_id`` widening
        in ``core`` (issue #244, ADR-0045 §7).

        The correction's id is minted by the guarded id factory and written
        insert-if-absent, so a collision with any stored record — every retained
        target included — is *rejected*, not clobbered; on the resulting
        :class:`~ai_assistant.core.errors.MemoryStoreConflictError` the applier
        re-mints and retries, bounded by :data:`_MAX_SUPERSEDE_ATTEMPTS`. Any other
        ``MemoryStoreError`` aborts with **every** target left **live and unchanged**,
        because the atomic batch rolls all the window-closes back together.

        The close instant is **this ingestor's** clock (ADR-0045 §4, ADR-0026), read
        **once** for the whole retirement set and never re-determined per target
        (ADR-0080 §1): a per-target reading would let one atomic batch record two
        different close times for one ruling, so a reader could not say when the
        correction took effect. Each target's own end is then clamped against it
        (:func:`_close_window`). A retired target leaves the read path once the
        *store's* read clock reaches the close —
        the same read-time semantics ``expires_at`` has. In production the store and
        this ingestor each *independently sample* the real wall clock (neither is
        given a ``now`` in ``build_engine``), and a ``get`` after ``ingest`` returns
        samples at or after the close — provided the wall clock advances forward
        between the two — so the target is hidden. A store read that samples *behind*
        the close (an injected test clock, or the wall clock stepping backward between
        the two samples) keeps it briefly visible, exactly as a backward step
        un-expires an ``expires_at`` record — a read-time-filtering property, not a
        supersession bug (issue #460 tracks an absolute, clock-coherence-independent
        guarantee; ADR-0080 §9 leaves this semantics exactly as ADR-0045 §6 has it).

        Returns:
            The **live** record's id — the correction's freshly-minted id, not any
            retired target's (ADR-0045 §4).

        Raises:
            MemoryStoreError: If the id factory is malformed (:func:`_checked_id`), if
                a target's window cannot be closed (:func:`_close_window`), if the
                bounded re-mint cannot find a free id, or on any other store failure —
                in every case every target is left live and unchanged.
        """
        # One close instant for the whole set (ADR-0080 §1), and every target's end
        # computed from it before any write: a `_close_window` that refuses (a
        # `valid_from` at or after the chosen end, ADR-0080 §3) then aborts the whole
        # supersession with nothing written and every record in the set unchanged.
        # There is deliberately no "skip the awkward one and retire the rest" —
        # that would commit a correction while leaving live a conflict the policy
        # ruled on, ADR-0079 §1's defect one member deep (ADR-0080 §6).
        now = self._now_utc()
        closed = [_close_window(target, now) for target in targets]
        retired_ids = {target.id for target in targets}
        last_conflict: MemoryStoreConflictError | None = None
        for _ in range(_MAX_SUPERSEDE_ATTEMPTS):
            new_id = _checked_id(self._id_factory, owner="MemoryIngestor")
            if new_id in retired_ids:
                # The minted id names one of the retained targets — a *stored* id, so
                # it must be re-minted (ADR-0045 §4: the absent-id obligation covers
                # "the retained target included"). Writing it would make the batch two
                # writes to one id, which `write_atomic` rejects as a hard
                # `MemoryStoreError` (repeated id, ADR-0046 §3) rather than the
                # retryable conflict this is, aborting a re-mint the ADR requires.
                last_conflict = MemoryStoreConflictError(
                    f"minted id {new_id!r} names a superseded target; re-minting"
                )
                continue
            batch = [
                MemoryWrite(record=closed_target, mode=MemoryWriteMode.UPSERT)
                for closed_target in closed
            ]
            batch.append(
                MemoryWrite(
                    record=_supersede(proposed, new_id),
                    mode=MemoryWriteMode.INSERT_IF_ABSENT,
                )
            )
            try:
                await self._store.write_atomic(batch)
            except MemoryStoreConflictError as exc:
                last_conflict = exc
                continue
            return new_id
        msg = (
            f"supersession could not mint a free id for a correction to {retired_ids!r} "
            f"after {_MAX_SUPERSEDE_ATTEMPTS} attempts; the targets are left live and unchanged"
        )
        raise MemoryStoreError(msg) from last_conflict

    def _now_utc(self) -> datetime:
        """The guarded clock's reading, as `memory`'s own error (ADR-0026 §4).

        Load-bearing for :meth:`_expiry`. ``model_copy(update=...)`` does **not**
        re-run validators, so an ``expires_at`` installed that way reaches the
        store exactly as this method left it — and since ADR-0023 makes
        ``MemoryBase.expires_at`` *reject* a naive value rather than assume UTC,
        there is no validator downstream that would have caught it. The guard at
        the producer is therefore the whole protection on this path.

        This replaces the ADR-0023 §6 shim that stood here, and the module-local
        canonicaliser it carried (#169). ADR-0030 §4 permits exactly one
        implementation of that test, in ``core``; routing this write through
        :func:`~ai_assistant.core.clock.checked_clock` is what discharges the
        exception the shim held open.

        Raises:
            MemoryStoreError: If the injected clock's reading is not a conforming
                one — naive, indeterminate, or outside the localizable range.
        """
        try:
            return self._clock()
        except ClockReadingError as exc:
            raise MemoryStoreError(str(exc)) from exc

    def _expiry(self, ttl: timedelta | None) -> datetime | None:
        """Stamp an expiry ``ttl`` from now, failing loudly if it is unrepresentable."""
        if ttl is None:
            return None
        try:
            return self._now_utc() + ttl
        except OverflowError as exc:
            msg = f"temporary-store ttl {ttl!r} overflows the representable date range"
            raise MemoryStoreError(msg) from exc
