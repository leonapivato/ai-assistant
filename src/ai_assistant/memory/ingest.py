"""Ingesting proposed memories: conflict detection, policy, and application.

``MemoryIngestor`` closes the propose/dispose/persist loop (ADR-0028, ADR-0328 §11).
Given a :class:`~ai_assistant.core.types.MemoryUpdateProposal` whose memory its
producer built, it:

1. refuses a proposal whose supports point at an episode the store does not hold
   (ADR-0328 §4:7),
2. detects conflicting memories (highly similar wording),
3. asks the injected :class:`~ai_assistant.core.protocols.MemoryPolicy` to rule, and
4. applies the ruling to the injected :class:`~ai_assistant.core.protocols.MemoryStore`:
   an ``ACCEPT`` installs the memory, a ``REINFORCE`` adds its supports to the target,
   a ``SUPERSEDE`` installs it at a fresh id and ends what it retires (§11:5-§11:8).

It also applies one operation to one stored memory (:meth:`MemoryIngestor.apply`,
§11:3), computing the record the operation yields through ``core``'s
:func:`~ai_assistant.core.types.applied_operation`, which the canonical fake computes
through too.

It depends only on the store and policy contracts, so it is agnostic to which concrete
store or policy is wired in. Every rule of the ratified write path over a field
ADR-0328 keeps stays as it stood, read through §12 (§11:9): where a rule named a
``MemorySource`` it reads the memory's band.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from math import isfinite
from types import MappingProxyType
from typing import TYPE_CHECKING, Final, assert_never

from pydantic import ValidationError

from ai_assistant.core.clock import ClockReadingError, checked_clock
from ai_assistant.core.errors import (
    FoldOntoCitedRecordError,
    MemoryStoreConflictError,
    MemoryStoreError,
    MemoryStoreStaleError,
    SelfConsumingWriteError,
    UnresolvedEvidenceError,
)
from ai_assistant.core.types import (
    MAX_TOPICS_PER_RECORD,
    BeliefBand,
    ConflictRelation,
    DataTier,
    Memory,
    MemoryDecisionKind,
    MemoryIngestResult,
    MemoryKind,
    MemoryOperation,
    MemoryOperationKind,
    MemorySupport,
    MemoryWrite,
    MemoryWriteMode,
    SupportDirection,
    SupportOrigin,
    TraceKind,
    TraceRecordSet,
    Validity,
    applied_operation,
    part_episode,
    record_band,
)
from ai_assistant.memory import traces
from ai_assistant.memory._agreement import agrees
from ai_assistant.memory._reconciler import ReconcilerOutcome

# `memory`'s own policy module, for its floor predicate alone (ADR-0159 §2, §10). The
# dependency is on a *predicate over the proposal*, not on the injected policy: this
# import is what stops the invocation condition becoming a second copy of the floor
# that could drift from the one that rules.
from ai_assistant.memory.policy import clears_admissibility_floor

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from ai_assistant.core.clock import Clock
    from ai_assistant.core.protocols import MemoryPolicy, MemoryStore, TraceSink
    from ai_assistant.core.types import (
        MemoryChange,
        MemoryDecision,
        MemoryRecord,
        MemoryUpdateProposal,
    )
    from ai_assistant.memory._reconciler import ConflictReconciler, ReconcilerReport

_DEFAULT_CONFLICT_THRESHOLD = 0.75

#: The **ceiling** on the conflicts one ingest resolves, not a truncation budget
#: (ADR-0079 §1). At or below it the whole detected set reaches the policy and a
#: ``SUPERSEDE`` retires all of it; above it the ingest refuses.
_DEFAULT_CONFLICT_LIMIT = 100

#: How many times supersession re-mints a colliding id before giving up (ADR-0045 §4).
_MAX_SUPERSEDE_ATTEMPTS = 5


def _uuid() -> str:
    return str(uuid.uuid4())


# --- three classes, because one constant answered two questions (ADR-0092 §5) ---
# Read through ADR-0328 §12: each was a set of sources and is now a set of bands.
# **They must not be tidied back into one**: they answer different questions, and the
# conformance cases pinning each refusal are what stop the tidy-up.

#: The **retirement class** — bands a correction is warranted to retire, used by
#: :func:`_retirement_set`'s widening (ADR-0050 §1, ADR-0079 §3, widened by ADR-0092
#: §4). Held here as well as in `policy`, deliberately: the policy chooses, but this
#: writer takes rulings from *any* injected `MemoryPolicy`, so the safety property has
#: to hold at the boundary that performs the write. An allow-list rather than "not
#: ASSERTED", so a band added later is not enrolled in a destructive rule by omission.
_RETIREMENT_CLASS = frozenset({BeliefBand.DERIVED, BeliefBand.ATTESTED})

#: The **reinforce-safe class** — targets an asserted proposal may fold onto
#: (ADR-0038 §2a, narrowed to ``REINFORCE`` by ADR-0045 §5b, widened with ``ASSERTED``
#: by ADR-0121 §5). ``ATTESTED`` still does not satisfy it: a memory resting on a
#: connected source's report is the source's to re-report, not the user's to fold into.
_REINFORCE_SAFE = frozenset({BeliefBand.DERIVED, BeliefBand.ASSERTED})

#: The **incoming** bands clause 1's agreeing-fold exception admits (ADR-0121 §5 as
#: widened by ADR-0214 §3). ``ATTESTED`` is out for ADR-0121 §3's reason.
_AGREEING_FOLD_INCOMING = frozenset({BeliefBand.ASSERTED, BeliefBand.DERIVED})

#: The rulings that dispatch a write. Check 0 (:func:`_refuse_secret_write`) gates
#: exactly these, derived as a complement so a new write-producing ruling joins the
#: gate rather than slipping past a list nobody updated.
_WRITE_PRODUCING_KINDS = frozenset(MemoryDecisionKind) - {
    MemoryDecisionKind.ASK_USER,
    MemoryDecisionKind.REJECT,
}

#: The relations that put a conflict **beyond retirement**, by any ruling (ADR-0159
#: §5). ``CONTRADICTS`` is deliberately absent, and its presence anywhere in a crossing
#: is what puts that crossing under ADR-0171 §2's narrowing.
_UNRETIRABLE_RELATIONS = frozenset({ConflictRelation.RESTATES, ConflictRelation.ADDS})


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _asserted(record: MemoryRecord) -> bool:
    """Whether ``record`` is in the ``ASSERTED`` band (ADR-0328 §12's first row)."""
    return record_band(record) is BeliefBand.ASSERTED


def _cited_ids(memory: Memory) -> frozenset[str]:
    """The episodes ``memory``'s supports point at: what it cites (ADR-0328 §12).

    §12 reads "the evidence a record cites" as the episodes its supports point at. A
    legacy support carries the record stored before ADR-0328 whole (§16:4), so
    installing at that record's id consumes no warrant, and it is no citation here.
    """
    return frozenset(
        episode
        for support in memory.supports
        if (episode := part_episode(support.points_at)) is not None
    )


def _newly_added(memory: Memory, support: MemorySupport | None) -> tuple[MemorySupport, ...]:
    """The support a change adds, where ``memory`` does not carry its part already.

    §4:7's episode check binds a support actually added: one whose part the memory
    already carries changes nothing and is no error (§4:8), even where its episode has
    since gone.
    """
    if support is None or memory.support_at(support.points_at) is not None:
        return ()
    return (support,)


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
    target: MemoryRecord,
    proposal: MemoryUpdateProposal,
    kind: MemoryDecisionKind,
    *,
    resolved: tuple[str, ...],
) -> None:
    """Refuse a fold that would destroy data, gated on the ruling where it must be.

    Read through ADR-0328 §12:

    - **Clause 1 — any fold onto an ``ASSERTED`` target** is refused (ADR-0038 §3,
      ADR-0045 §5), except where a confirmation covers this very target
      (:func:`_confirmation_covers`, ADR-0078 §5b) or the fold is an agreeing
      ``REINFORCE`` (:func:`_agreeing_restatement`, ADR-0121 §5, ADR-0214 §3), which
      only adds the proposal's supports to the target and changes nothing the user told
      us (ADR-0328 §11:6). Both exceptions are verified here rather than trusted from
      the ruling.
    - **Clause 2 — an asserted proposal onto a target outside the reinforce-safe class,
      ``REINFORCE`` only** (ADR-0038 §2a, ADR-0045 §5b): an ``ATTESTED`` target is
      refused.

    Args:
        target: The conflict the ruling names.
        proposal: The proposal **as handed to ``ingest``**, whose ``conflicts`` are the
            frozen ids the question was asked about (ADR-0078 §5b check 4).
        kind: The ruling being applied.
        resolved: The conflict ids *this* ingest resolved.

    Raises:
        MemoryStoreError: If the fold is one of the two above and no exception admits
            it.
    """
    incoming = proposal.proposed
    if (
        _asserted(target)
        and not _confirmation_covers(target, proposal, kind, resolved=resolved)
        and not _agreeing_restatement(target, incoming, kind)
    ):
        msg = (
            f"refusing to fold onto {target.id!r}: a {incoming.band} memory may not be folded "
            f"onto one the user asserted (ADR-0038 §3, ADR-0045 §5, narrowed by ADR-0078 §5b "
            f"and ADR-0121 §5)"
        )
        raise MemoryStoreError(msg)
    if (
        kind is MemoryDecisionKind.REINFORCE
        and incoming.band is BeliefBand.ASSERTED
        and record_band(target) not in _REINFORCE_SAFE
    ):
        msg = (
            f"refusing to reinforce {target.id!r}: a user assertion may not be reinforced onto "
            f"a {record_band(target)} memory (ADR-0038 §2a, narrowed to REINFORCE by "
            f"ADR-0045 §5b)"
        )
        raise MemoryStoreError(msg)


def _may_reconcile(proposal: MemoryUpdateProposal, conflicts: Sequence[MemoryRecord]) -> bool:
    """ADR-0159 §2's invocation condition, in full and in one place.

    A reconciler is invoked **exactly when** all three hold: the proposed memory is not
    ``ASSERTED``; no member of the conflict set is; and the proposal clears the
    admissibility floor. On every other ingest none is invoked and ``decide`` is called
    with ``None``. A correctness boundary, not a cost heuristic, and it binds this writer
    whatever ``MemoryPolicy`` it holds.

    Args:
        proposal: The proposal being ingested.
        conflicts: The resolved conflict set.

    Returns:
        Whether relations may be determined for this ingest.
    """
    return (
        proposal.proposed.band is not BeliefBand.ASSERTED
        and not any(_asserted(conflict) for conflict in conflicts)
        and clears_admissibility_floor(proposal)
    )


def _refuse_retiring_a_related_conflict(
    target: MemoryRecord,
    kind: MemoryDecisionKind,
    relations: Mapping[str, ConflictRelation],
) -> None:
    """Refuse a ``SUPERSEDE`` that would retire a ``RESTATES`` or ``ADDS`` conflict.

    ADR-0159 §5's exclusion at the one place it cannot be expressed as an omission.
    A ``SUPERSEDE`` naming another member simply leaves such a conflict out of the
    retirement set (:func:`_retirement_set`); a ``SUPERSEDE`` naming *this* one has
    nowhere to leave it, because retiring the named target is what the ruling means
    — so the write is refused instead.

    **Enforced from the writer's own relations, never trusted from the ruling** —
    ADR-0038 §2a's shape, at the boundary that performs the write. ``MemoryIngestor``
    takes rulings from *any* injected ``MemoryPolicy``, and ``DefaultMemoryPolicy``
    never asks for this fold (ADR-0159 §4(b) names a ``CONTRADICTS`` member), so the
    refusal exists for the policies this seam admits rather than for the one it
    ships with.

    **Nothing here is a ``_refuse_unsafe_fold`` exception, and ADR-0159 opens
    none** (§5). The labels only ever *narrow* what happens: they withhold a fold
    the old rule performed and a retirement ADR-0050 §1 permitted. That asymmetry is
    why ADR-0159 can hold a model call where ADR-0121 §5 could not — a safety
    property that can only be tightened by an untrusted input needs no verification
    of the input, which is #868's objection landing on a different ADR.

    Args:
        target: The conflict the ruling names.
        kind: The ruling being applied.
        relations: The relations **this writer** determined, handed to no policy.

    Raises:
        MemoryStoreError: If the ruling is a ``SUPERSEDE`` naming a conflict this
            writer holds a ``RESTATES`` or ``ADDS`` relation for.
    """
    if kind is not MemoryDecisionKind.SUPERSEDE:
        return
    relation = relations.get(target.id)
    if relation in _UNRETIRABLE_RELATIONS:
        msg = (
            f"refusing to supersede {target.id!r}: this writer determined the proposal "
            f"{relation} that record, and a conflict so related is never retired, by any "
            f"ruling (ADR-0159 §5)"
        )
        raise MemoryStoreError(msg)


def _agreeing_restatement(target: MemoryRecord, incoming: Memory, kind: MemoryDecisionKind) -> bool:
    """Whether clause 1's ADR-0121 §5 exception admits this fold.

    Three conditions: the ruling is ``REINFORCE``; the incoming memory's band is in
    :data:`_AGREEING_FOLD_INCOMING` (ADR-0214 §3); and the two agree under ADR-0121 §1
    (wording and kind, no score). Recomputed here rather than read off the ruling.

    Args:
        target: The stored record the ruling folds into.
        incoming: The proposed memory.
        kind: The ruling being applied.

    Returns:
        Whether the fold is the one ADR-0121 §5 permits.
    """
    return (
        kind is MemoryDecisionKind.REINFORCE
        and incoming.band in _AGREEING_FOLD_INCOMING
        and agrees(target, incoming)
    )


def _confirmation_covers(
    target: MemoryRecord,
    proposal: MemoryUpdateProposal,
    kind: MemoryDecisionKind,
    *,
    resolved: tuple[str, ...],
) -> bool:
    """Whether a confirmation authorises retiring ``target`` (ADR-0078 §5b).

    Clause 1's one exception, and **five checks stand behind it**, all of them
    performable at this boundary with what the writer already holds. (The sixth,
    check 0, gates the *write* rather than the ruling and so cannot live here —
    ``ingest`` reaches this helper only for ``REINFORCE`` and ``SUPERSEDE``, which
    would let an injected policy ruling ``ACCEPT`` write a secret straight through;
    it sits between the ruling and the write dispatch instead,
    :func:`_refuse_secret_write`.)

    1. **The ruling is ``SUPERSEDE``.** A ``REINFORCE`` onto an assertion stays
       refused *by this exception* whatever the confirmation says: folding at the
       target's id would rewrite the user's own words, which no answer authorises.
       That reason is why ADR-0121 §5's exception is a separate gate rather than a
       widening of this one — it admits the single ``REINFORCE`` that writes the
       user's own words back rather than rewriting them
       (:func:`_agreeing_restatement`), and it needs no confirmation at all.
    2. **The target id is in ``confirmation.retires``.**
    3. **The target id is also among the conflicts this very ingest resolved.** A
       confirmation cannot authorise retiring a record the current ruling was not
       even made against.
    4. **``confirmation.question_key`` equals the key recomputed from the proposal
       as handed to ``ingest``.** This is the check that stops the value being a
       bearer token, and it took ADR-0078 two revisions to get right: checks 1-3 all
       pass when a confirmation given for Q1 is presented with a *different*
       proposal that happens to conflict with the same assertion, and binding on the
       proposal alone still left the narrower hole open — two questions can share a
       proposal **exactly** and have been shown different conflict sets, so Q1's
       broader ``retires`` would spend itself inside Q2's apply and retire an
       assertion Q2's user never saw. The key covers *what was proposed* and *what
       it was proposed against* together, so the two questions differ and the
       confirmation does not travel. Recomputed from the **frozen** conflicts the
       proposal arrived carrying — not the live set the ingestor stamped onto its own
       copy, which would compare the wrong set on every input.
    5. **Every id in ``confirmation.retires`` is among those frozen conflicts.**
       Check 3 requires a target to be in the *live* set; this requires it to have
       been among the ones the user was *shown*. Both, because the two sets can
       differ in either direction and the authority is bounded by the smaller one.

    **What none of this claims.** It does not make the confirmation unforgeable —
    any subsystem holding the injected ``MemoryStore`` can call ``write_atomic``
    directly, and a floor on the writer is not a security boundary against
    arbitrary in-process code. What it *is* is a guarantee that no ruling reaches a
    user assertion by inference: not from a policy's judgement, not from topical
    similarity, and not from a confirmation belonging to another question. That a
    confirmation corresponds to a deferral a user actually answered is enforced one
    layer up, by `orchestration`'s claim (ADR-0078 §3, §9).

    Args:
        target: The conflict the ruling names.
        proposal: The proposal as handed to ``ingest``.
        kind: The ruling being applied.
        resolved: The conflict ids this ingest resolved.

    Returns:
        ``True`` iff all five checks hold, and the fold is therefore the user's
        own answer rather than a similarity signal.
    """
    confirmation = proposal.confirmation
    if confirmation is None or kind is not MemoryDecisionKind.SUPERSEDE:
        return False
    frozen = set(proposal.conflicts)
    return (
        target.id in confirmation.retires
        and target.id in resolved
        and confirmation.question_key == proposal.question_key
        and frozen.issuperset(confirmation.retires)
    )


def _refuse_secret_write(decision: MemoryDecision, proposal: MemoryUpdateProposal) -> None:
    """Refuse any *write* of a ``DataTier.SECRET`` proposal (ADR-0078 §5b check 0).

    A refusal at the writer boundary, independent of the proposal's own validator,
    which ``model_construct`` skips. It gates the write and not the ruling: it runs
    after the policy has ruled and before any write is dispatched, so ``ASK_USER`` and
    ``REJECT`` return normally (ADR-0004 §3 forbids a secret in the database, not a
    secret being judged).

    Raises:
        MemoryStoreError: If the ruling would write and the proposal is Tier 0.
    """
    if decision.kind in _WRITE_PRODUCING_KINDS and proposal.sensitivity is DataTier.SECRET:
        msg = (
            f"refusing to write {proposal.proposed.id!r}: a {decision.kind} ruling on secret-tier "
            f"data would put Tier 0 content in the memory database, which lives in the OS keyring "
            f"and never in a database or a committed file (ADR-0004 §3, ADR-0078 §5b)"
        )
        raise MemoryStoreError(msg)


def _refuse_tentative_store(decision: MemoryDecision) -> None:
    """Refuse a ``STORE_TEMPORARY`` ruling (ADR-0328 §10:3).

    No ``MemoryPolicy`` stores a proposal tentatively, so a ruling that would is one
    this writer refuses, with nothing written, from whatever policy it holds.

    Raises:
        MemoryStoreError: If the ruling is ``STORE_TEMPORARY``.
    """
    if decision.kind is MemoryDecisionKind.STORE_TEMPORARY:
        msg = (
            "refusing a STORE_TEMPORARY ruling: no proposal is stored tentatively, and one "
            "that does not meet an evidence bar is not committed (ADR-0328 §10:3)"
        )
        raise MemoryStoreError(msg)


def _installed_at(
    decision: MemoryDecision, proposed: Memory, *, resolved: tuple[str, ...]
) -> str | None:
    """The id this ruling would **install** the proposal at, if any (ADR-0081 §1).

    ``ACCEPT`` installs at the proposed id; a ``REINFORCE`` writes the proposal's supports
    at its target, where that target is among the conflicts this ingest resolved;
    ``SUPERSEDE`` installs at a freshly minted id tested inside
    :meth:`MemoryIngestor._apply_supersede`; and the rest install nothing.
    """
    match decision.kind:
        case MemoryDecisionKind.ACCEPT:
            return proposed.id
        case MemoryDecisionKind.REINFORCE:
            return decision.target_id if decision.target_id in resolved else None
        case (
            MemoryDecisionKind.SUPERSEDE
            | MemoryDecisionKind.REJECT
            | MemoryDecisionKind.ASK_USER
            | MemoryDecisionKind.STORE_TEMPORARY
        ):
            return None
    assert_never(decision.kind)


def _refuse_self_consuming_write(
    decision: MemoryDecision, proposal: MemoryUpdateProposal, *, resolved: tuple[str, ...]
) -> None:
    """Refuse a write that would land at an id the proposal's supports point at (ADR-0081 §1).

    Read through ADR-0328 §12: what a proposal cites is the episodes (and legacy records)
    its supports point at. It gates the write, between the ruling and the dispatch, and
    reads nothing from the store.

    Raises:
        FoldOntoCitedRecordError: If a ``REINFORCE`` would write onto a record the
            proposal's supports point at — the destination the *policy* chose
            (ADR-0116 §2).
        SelfConsumingWriteError: If an ``ACCEPT`` would install at ``proposed.id`` and the
            proposal's supports point at it — the destination the *producer* chose.
    """
    proposed = proposal.proposed
    destination = _installed_at(decision, proposed, resolved=resolved)
    if destination is not None and destination in _cited_ids(proposed):
        refusal = (
            FoldOntoCitedRecordError
            if decision.kind is MemoryDecisionKind.REINFORCE
            else SelfConsumingWriteError
        )
        msg = (
            f"refusing to write {proposed.id!r}: a {decision.kind} ruling would install it at "
            f"{destination!r}, an id its own supports point at — the memory would stand as its "
            f"own warrant (ADR-0081 §1)"
        )
        raise refusal(msg)


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


def _retirement_set(
    target: MemoryRecord,
    conflicts: list[MemoryRecord],
    *,
    proposal: MemoryUpdateProposal,
    resolved: tuple[str, ...],
    relations: Mapping[str, ConflictRelation],
) -> list[MemoryRecord]:
    """The full set of conflicting memories a ``SUPERSEDE`` retires (ADR-0050 §1, #244).

    The named ``target`` plus every other conflict in the retirement class
    (``DERIVED`` or ``ATTESTED``, ADR-0079 §3, ADR-0092 §4), less every member this
    writer holds a ``RESTATES`` or ``ADDS`` relation for (ADR-0159 §5) and, where this
    crossing produced a labelled contradiction at all, less every member not labelled
    ``CONTRADICTS`` (ADR-0171 §2). An ``ASSERTED`` member is swept in only where the
    proposal's confirmation genuinely covers it (ADR-0078 §5b), on its own footing.
    ``target`` leads the list and the rest follow ``conflicts``' order.

    Args:
        target: The conflict the ruling names.
        conflicts: The full resolved set, best-ranked first.
        proposal: The proposal as handed to ``ingest``, for the confirmation checks.
        resolved: The conflict ids this ingest resolved.
        relations: The relations this writer determined, keyed by record id.

    Returns:
        The named target followed by every other conflict warranted for retirement.
    """
    labelled_contradiction = any(
        relations.get(conflict.id) is ConflictRelation.CONTRADICTS for conflict in conflicts
    )
    others = [
        conflict
        for conflict in conflicts
        if conflict.id != target.id
        and relations.get(conflict.id) not in _UNRETIRABLE_RELATIONS
        and (
            (
                record_band(conflict) in _RETIREMENT_CLASS
                and (
                    not labelled_contradiction
                    or relations.get(conflict.id) is ConflictRelation.CONTRADICTS
                )
            )
            or (
                _asserted(conflict)
                and _confirmation_covers(
                    conflict, proposal, MemoryDecisionKind.SUPERSEDE, resolved=resolved
                )
            )
        )
    ]
    return [target, *others]


def _supersede(incoming: Memory, new_id: str, retired: Sequence[str]) -> Memory:
    """The superseding memory: ``incoming`` at a fresh id, naming what it replaces.

    Nothing of the overturned memory is carried onto the one that overturns it (ADR-0040
    §5a). It is written at a freshly minted id (ADR-0045 §4), given a fresh open window
    (the point of a supersession is a *live* memory), and its create names every memory
    it retires among those it replaces (ADR-0328 §5:6, §11:7).

    Raises:
        MemoryStoreError: If ``incoming`` cannot stand live at the fresh id.
    """
    first, *rest = incoming.operations
    create = first.model_copy(
        update={"replaces": tuple(dict.fromkeys([*first.replaces, *retired]))}
    )
    try:
        return Memory.model_validate(
            incoming.model_dump()
            | {"id": new_id, "validity": Validity(), "operations": (create, *rest)}
        )
    except ValidationError as exc:
        # A proposal that cannot stand live — one already ended or marked wrong keeps
        # its status, which an open window contradicts (ADR-0328 §3:4) — is refused as
        # this writer's error, never as a raw validation failure.
        msg = f"cannot supersede with {incoming.id!r}: it cannot stand live"
        raise MemoryStoreError(msg) from exc


def _ended(target: MemoryRecord, successor: Memory, now: datetime) -> Memory:
    """``target`` ended by a supersession (ADR-0328 §11:7).

    An end citing the successor's first support, added to ``target`` as an ``against``
    support that does not back it as worded, and naming the successor. The close is
    §5:10's — that support's about-when where it carries one, else ``now`` — clamped and
    never resurrecting (§5:11, ADR-0080 §1).

    Raises:
        MemoryStoreError: If ``target`` is not a memory, already carries the part that
            support points at, or the end is refused by §5:10, §5:11 or §6:5. The whole
            ingest is refused with nothing written.
    """
    if not isinstance(target, Memory):
        msg = f"cannot retire {target.id!r}: a supersession retires memories only"
        raise MemoryStoreError(msg)
    first = successor.supports[0]
    if target.support_at(first.points_at) is not None:
        msg = (
            f"cannot retire {target.id!r}: it already carries the part the superseding "
            f"memory's first support points at (ADR-0328 §11:7)"
        )
        raise MemoryStoreError(msg)
    against = MemorySupport.model_validate(
        first.model_dump()
        | {"direction": SupportDirection.AGAINST, "backs_as_worded": False, "added_at": now}
    )
    end = MemoryOperation(
        kind=MemoryOperationKind.END,
        cites=first.points_at,
        note="superseded by a memory that overturns it",
        at=now,
        by=successor.operations[0].by,
        successor=successor.id,
    )
    try:
        return applied_operation(target, end, support=against)
    except ValueError as exc:
        msg = f"cannot retire {target.id!r}: {exc}"
        raise MemoryStoreError(msg) from exc


def _bounded_topics(admitted: Sequence[str]) -> tuple[str, ...]:
    """ADR-0213 §8's retained subset, stored in §1's canonical order.

    ``admitted`` is the install's **admission order** — which labels survive — and
    the two orders are deliberately different things. §8 fixes admission per arm
    (:func:`_topics_of_fold` for a fold, the record's own canonical order for every
    other install), takes the first :data:`MAX_TOPICS_PER_RECORD` of it, and then §1
    fixes how the survivors are **stored**: strictly increasing by code point,
    whatever order they were admitted in. Sorting after the cut rather than before
    is the whole of the distinction — sorting first would let a code-point-lesser
    incoming label displace a target's label, which is exactly the ratchet §8 exists
    to hold.

    Deduplicating in admission order rather than through ``sorted(set(...))``,
    because the cut happens on that order and a duplicate must not spend a slot.
    """
    admitted_once = tuple(dict.fromkeys(admitted))
    return tuple(sorted(admitted_once[:MAX_TOPICS_PER_RECORD]))


def _topics_of_fold(target: MemoryRecord, incoming: MemoryRecord) -> tuple[str, ...]:
    """The survivor's topics: ADR-0213 §8's bounded union, on both arms.

    **The union is ADR-0204 §5's disjunction with a wider carrier**, taken on
    ADR-0106 §4's ratchet: a record the owner filed under ``"health"`` must not
    quietly stop being reachable by a health-scoped act the first time an unlabelled
    proposal reinforces it, and nothing about the survivor would look wrong
    afterwards. So no fold drops a label the target carried and no arm writes one
    side's tuple over the other's — which is why this is computed **once, before the
    arms**, exactly as ``derived_from_external`` and ``placement`` are and for the
    same reason: the rule is stated over the fold, so neither arm may read one side
    alone.

    **The admission order keeps that ratchet whole under §1's bound**: the target's
    own labels first, then the labels of the incoming record the target does not
    already carry. A target conforming to the bound — every record this deployment
    installs — therefore has all of its labels fit ahead of any incoming one, so the
    failure the union exists to stop is unreachable by construction. What the bound
    declines is always a label of the *incoming* record, a suggestion of the same
    standing as any other topics entry, which §4 already rules may be ignored in
    whole without anything being counted. A target that itself exceeds the bound —
    reachable only by import, or under a constant a later ADR raised — converges
    downward on this same install rather than raising, keeping the first
    :data:`MAX_TOPICS_PER_RECORD` of its own labels ahead of any incoming one.

    **Code-point order among the incoming labels is the only order available**: §1
    fixes this tuple's order by code point precisely so that order carries *no*
    meaning. Deterministic, implementation-independent and identical on every store.

    **Nothing is counted** (§1): a topic set is never a claim to completeness (§7).
    """
    carried = set(target.topics)
    return _bounded_topics(
        [
            *sorted(target.topics),
            *sorted(label for label in incoming.topics if label not in carried),
        ]
    )


def _installed(memory: Memory) -> Memory:
    """``memory`` with its topics brought under :data:`MAX_TOPICS_PER_RECORD` (ADR-0213 §1).

    Applied at every install and at no retirement. A no-op — the same object — for a
    memory already under the bound. A memory carries no citation bound (ADR-0328
    §10:4): every support is kept (§4:9).
    """
    topics = _bounded_topics(sorted(memory.topics))
    if topics == memory.topics:
        return memory
    return memory.model_copy(update={"topics": topics})


def _reinforced(target: MemoryRecord, incoming: Memory, *, now: datetime) -> Memory:
    """``target`` with ``incoming``'s supports added, one add support each (ADR-0328 §11:6).

    The target's wording is left as it is (§3:2); a support whose part the target
    already carries changes nothing and keeps its fields (§4:8). Placement's ratchet
    (ADR-0217 §3, :meth:`~ai_assistant.core.types.Placement.folded_with`) and the union of
    topics (ADR-0213 §8) apply as on any fold (§11:9); neither is an operation (§5:2).
    Each add support is written at ``now`` by the writer that wrote the incoming
    memory's create, and each added support is stamped as added at ``now``.

    Raises:
        MemoryStoreError: If ``target`` is not a memory, or an add support is refused.
    """
    if not isinstance(target, Memory):
        msg = f"cannot reinforce {target.id!r}: a reinforcement adds supports to a memory only"
        raise MemoryStoreError(msg)
    writer = incoming.operations[0].by
    folded = target
    for support in incoming.supports:
        if folded.support_at(support.points_at) is not None:
            continue
        if support.origin is SupportOrigin.CONFIRMATION and not agrees(target, incoming):
            # §4:6: a confirmation is `for` a memory whose wording agrees with the
            # statement the approved part showed, and added to no other. Recomputed
            # here whatever the ruling, since a policy is injected (ADR-0038 §2a).
            msg = (
                f"cannot reinforce {target.id!r}: a confirmation backs only a wording that "
                f"agrees with the statement the user approved (ADR-0328 §4:6)"
            )
            raise MemoryStoreError(msg)
        added = support.model_copy(update={"added_at": now})
        operation = MemoryOperation(
            kind=MemoryOperationKind.ADD_SUPPORT,
            cites=support.points_at,
            note="added by a proposal that agrees with this memory",
            at=now,
            by=writer,
        )
        try:
            folded = applied_operation(folded, operation, support=added)
        except ValueError as exc:
            msg = f"cannot reinforce {target.id!r}: {exc}"
            raise MemoryStoreError(msg) from exc
    return folded.model_copy(
        update={
            "placement": target.placement.folded_with(incoming.placement),
            "topics": _topics_of_fold(target, incoming),
        }
    )


@dataclass(frozen=True, slots=True)
class _Applied:
    """What applying one ruling actually wrote.

    ``MemoryIngestResult`` carries the id left *live* and nothing about what a
    ``SUPERSEDE`` retired to leave it there, because ADR-0078 §4 gave it the
    conflicts the policy ruled against rather than the subset the applier closed.
    ADR-0119 §8 wants that subset "so a correction measure can tell a retired id
    from a reinforced one without re-deriving it", so it travels here — inside the
    subsystem, on no contract.

    Attributes:
        record_id: The id the ruling left live, or ``None`` if nothing was stored.
        superseded: Every id a ``SUPERSEDE`` closed the window of — the whole
            retirement set (ADR-0050 §1), not just the ruling's ``target_id``.
    """

    record_id: str | None
    superseded: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class _Reconciliation:
    """One proposal's relations beside what ADR-0164 §3 observed determining them.

    The relations are what the ruling reads; everything else here is read by the
    trace and by nothing at all besides. That separation is ADR-0164 §3's rule that
    the reconciler's report "reaches a ruling only the way any other determination
    of the relation set does — through the relations the writer therefore holds".

    **Two units live here and they are different populations** (§3). This object is
    one *proposal*; :attr:`offered`, :attr:`certain_restates` and
    :attr:`model_labels` count *pairs*. A proposal clearing ADR-0159 §2's condition
    with an empty conflict set is reconciled and offers no pair at all, which is the
    common case and the reason ``reconciled`` is the wrong denominator for any
    relation figure.

    Attributes:
        relations: The relations this writer holds for the proposal, or ``None``
            where ADR-0159 §2's invocation condition excluded it — the value §8
            distinguishes from an empty mapping, and the flag that decides whether
            this proposal was ``reconciled`` at all.
        qualifier: The metric key this proposal counts under beside ``reconciled``,
            or ``None`` where its model rung answered. The three qualifier keys are
            mutually exclusive by construction: one field can hold one of them.
        offered: Every pair the determination ranged over — this proposal against
            each member of its resolved conflict set.
        certain_restates: Those the certain predicate labelled, whatever a
            reconciler returned for the same pair.
        model_labels: The labels a reconciler supplied **that stand**, one entry per
            pair. Empty wherever nothing installed, which is every path but an
            answered one.
    """

    relations: dict[str, ConflictRelation] | None
    qualifier: str | None = None
    offered: int = 0
    certain_restates: int = 0
    model_labels: tuple[ConflictRelation, ...] = ()

    def observe(self, counts: dict[str, int]) -> None:
        """Add this proposal's ten quantities into a crossing's counts.

        Called once per proposal of the crossing, so the keys accumulate across a
        reading exactly as the ``decisions_*`` keys beside them do. A proposal
        ADR-0159 §2 excluded contributes **zero to each of the ten** and is counted
        by ``proposals`` alone — it is not skipped because it went unobserved, but
        because what it observed was nothing.

        Args:
            counts: The crossing's ten counts, already seeded with a zero apiece;
                mutated in place.
        """
        if self.relations is None:
            return
        counts[traces.RECONCILED] += 1
        if self.qualifier is not None:
            counts[self.qualifier] += 1
        counts[traces.RELATIONS_OFFERED] += self.offered
        counts[traces.RELATIONS_CERTAIN_RESTATES] += self.certain_restates
        for relation in self.model_labels:
            counts[traces.RELATION_METRICS[relation]] += 1
        # The five label keys partition ``relations_offered`` by construction: what
        # neither rung labelled is the remainder, and deriving it rather than
        # counting it separately is what makes the sum an identity instead of a
        # coincidence two counters have to keep.
        counts[traces.RELATIONS_UNLABELLED] += (
            self.offered - self.certain_restates - len(self.model_labels)
        )


@dataclass(frozen=True, slots=True)
class _Ingested:
    """One proposal's public result beside what the trace needs and it lacks."""

    result: MemoryIngestResult
    superseded: tuple[str, ...]
    reconciliation: _Reconciliation


@dataclass(frozen=True, slots=True)
class _Reconciled:
    """One crossing of the write seam.

    Attributes:
        ingested: One entry per proposal, in the order they were ingested.
    """

    ingested: tuple[_Ingested, ...]


#: Which ``TraceRecordSet`` a ruling's live id belongs under (ADR-0119 §8), or
#: ``None`` for a ruling that stores nothing. A ``SUPERSEDE``'s live id is a
#: **written** record — the correction is installed fresh at a minted id
#: (ADR-0045 §4) — and what it displaced travels separately as
#: :attr:`_Applied.superseded`. Totality over ``MemoryDecisionKind`` is asserted by
#: test, so a ruling added later fails loudly rather than losing its ids.
_WRITE_DISPOSITIONS: Final[Mapping[MemoryDecisionKind, TraceRecordSet | None]] = {
    MemoryDecisionKind.ACCEPT: TraceRecordSet.WRITTEN,
    MemoryDecisionKind.STORE_TEMPORARY: TraceRecordSet.WRITTEN,
    MemoryDecisionKind.SUPERSEDE: TraceRecordSet.WRITTEN,
    MemoryDecisionKind.REINFORCE: TraceRecordSet.REINFORCED,
    MemoryDecisionKind.REJECT: None,
    MemoryDecisionKind.ASK_USER: None,
}


def _sole_outcome(report: ReconcilerReport) -> ReconcilerOutcome | None:
    """The one outcome a report names, or ``None`` where it names anything else.

    ADR-0164 §3: a report from a reconciler that **ran** names exactly one of
    :class:`~ai_assistant.memory._reconciler.ReconcilerOutcome`'s three members. One
    that is missing where it was due, names none of them, or names more than one is
    non-conforming *in whole* — the mapping it accompanies installs nothing and the
    proposal counts under ``reconciler_failed``. A report naming more than one is no
    more usable for carrying a valid outcome among them, because nothing says which
    of them to read, and that is what stops two implementations reporting the same
    unusable report differently.

    **Membership is tested with ``is``**, the same test ADR-0164 §3 puts on the
    relation values, so a value merely *equal* to a member can never read as
    conforming.

    Args:
        report: What the reconciler returned. Read defensively: this runs inside the
            caller's guard, and a non-conforming reconciler can put anything here.

    Returns:
        The sole outcome named, or ``None``.
    """
    reported = report.outcomes
    named = [member for member in ReconcilerOutcome if any(value is member for value in reported)]
    if len(named) != 1 or len(reported) != 1:
        return None
    return named[0]


def _installable(
    supplied: Mapping[str, ConflictRelation],
) -> dict[str, ConflictRelation] | None:
    """The mapping's labels, or ``None`` where **any** value is not a member.

    ADR-0164 §3's whole-mapping clause. It is the whole mapping and not the offending
    entry because partial trust is what would make the arithmetic lie: a mapping
    carrying one valid ``ADDS`` beside one bare ``"contradicts"`` could install the
    valid label and count its proposal ``reconciler_failed``, and then one trace
    would say a model label stood *and* that no model rung answered on that
    proposal. It is also the shape ``_relations_for``'s existing guard already has —
    ``except Exception: return own`` discards the entire determination, not the
    member that failed.

    Args:
        supplied: The values read for the members this crossing reads a mapping for.

    Returns:
        The labels to install, or ``None`` where the mapping is non-conforming.
    """
    installed: dict[str, ConflictRelation] = {}
    for record_id, value in supplied.items():
        member = next((member for member in ConflictRelation if value is member), None)
        if member is None:
            return None
        installed[record_id] = member
    return installed


def _reconciliation_reading(reconciled: _Reconciled) -> traces.Reading:
    """Read one completed crossing of the write seam into its trace (ADR-0119 §8).

    **Every decision kind gets a key, including the ones that did not occur.**
    §3's observation rule says an absent key means *not observed*, and a completed
    ingest observed every kind: five zeros and a one is what "this proposal was
    accepted" looks like when the alternative reading of a missing key is
    "unobserved". The fault path omits them all, which is the same rule from the
    other side.

    **ADR-0164 §3's ten reconciliation keys ride the same statement**, and that is
    the whole of what binds them: they are present on exactly the crossings the six
    ``decisions_*`` keys are present on, absent on exactly the ones they are absent
    on, and no crossing can carry one set without the other. So a crossing whose
    proposals ADR-0159 §2 all excluded emits ten zeros — the invocation condition
    *was* evaluated, on every proposal — where a crossing that faulted before any
    reading was taken emits none of them, and a reader can tell "the reconciler was
    never reached" from "the trace never got that far".

    Args:
        reconciled: What the crossing produced.

    Returns:
        The reading the emitter turns into a trace.
    """
    counts: dict[str, int] = dict.fromkeys(traces.DECISION_METRICS.values(), 0)
    counts.update(dict.fromkeys(traces.RECONCILIATION_METRICS, 0))
    records: dict[TraceRecordSet, list[str]] = {
        TraceRecordSet.WRITTEN: [],
        TraceRecordSet.REINFORCED: [],
        TraceRecordSet.SUPERSEDED: [],
    }
    for one in reconciled.ingested:
        kind = one.result.decision.kind
        counts[traces.DECISION_METRICS[kind]] += 1
        one.reconciliation.observe(counts)
        disposition = _WRITE_DISPOSITIONS[kind]
        if disposition is not None and one.result.record_id is not None:
            records[disposition].append(one.result.record_id)
        records[TraceRecordSet.SUPERSEDED].extend(one.superseded)
    metrics: dict[str, int | float | bool] = dict(counts)
    return traces.Reading(metrics=metrics, records=records)


def _proposal_reading(ingested: _Ingested) -> traces.Reading:
    """One bare :meth:`MemoryIngestor.ingest` read as a one-proposal crossing.

    No reconciliation runs, so no retired set is observed and none is keyed: an
    absent key means *unobserved* rather than empty, and ADR-0119 §3 forbids
    substituting one for the other.

    Args:
        ingested: What the one proposal produced.

    Returns:
        The reading the emitter turns into a trace.
    """
    return _reconciliation_reading(_Reconciled(ingested=(ingested,)))


class MemoryIngestor:
    """Runs a proposed memory through conflict detection, policy, and storage.

    Structurally satisfies :class:`~ai_assistant.core.protocols.MemoryWriter`
    (ADR-0028 §2, ADR-0328 §11), which is how `orchestration` reaches this write path
    without importing it.
    """

    def __init__(  # noqa: PLR0913 — one parameter per injected collaborator plus two knobs
        self,
        *,
        store: MemoryStore,
        policy: MemoryPolicy,
        traces_sink: TraceSink,
        traces_now: Clock = _utcnow,
        conflict_threshold: float = _DEFAULT_CONFLICT_THRESHOLD,
        conflict_limit: int = _DEFAULT_CONFLICT_LIMIT,
        now: Clock = _utcnow,
        id_factory: Callable[[], str] = _uuid,
        reconciler: ConflictReconciler | None = None,
    ) -> None:
        """Initialise the ingestor.

        Args:
            store: Where memories are persisted and conflicts sought.
            policy: The deterministic policy that rules on each proposal.
            traces_sink: Where this writer's ``MEMORY_WRITE`` traces are appended
                (ADR-0119 §8). Required with no default (§7).
            traces_now: Clock the ``MEMORY_WRITE`` trace's ``occurred_at`` is stamped
                from — a seam of its own, so the instrument does not move the close
                instant a supersession reads (ADR-0119 §5, ADR-0080 §1).
            conflict_threshold: Minimum retrieval score for an existing memory to count
                as conflicting with the proposal.
            conflict_limit: The **ceiling** on the conflicts one ingest resolves
                (ADR-0079 §1).
            now: Clock an operation's instant is read from — a supersession's end and a
                reinforcement's add support — and a retirement's close; guarded by
                :func:`~ai_assistant.core.clock.checked_clock` (ADR-0026 §2).
            id_factory: Mints the fresh id a ``SUPERSEDE`` writes its memory at
                (ADR-0045 §4), guarded at its output by :func:`_checked_id`.
            reconciler: Determines ADR-0159 §1 relations between the probe and the
                ruling (:func:`_may_reconcile`). Optional, with a ruled, safe absence
                (ADR-0159 §6).

        Raises:
            TypeError: If ``conflict_limit`` is not an integer, or
                ``conflict_threshold`` is a ``bool`` (see :func:`_check_tuning`).
            ValueError: If ``conflict_limit`` is below 1, or ``conflict_threshold`` is
                not a finite value in ``[0, 1]`` (see :func:`_check_tuning`).
        """
        _check_tuning(conflict_threshold=conflict_threshold, conflict_limit=conflict_limit)
        self._store = store
        self._policy = policy
        self._conflict_threshold = conflict_threshold
        self._conflict_limit = conflict_limit
        self._clock = checked_clock(now, owner="MemoryIngestor")
        self._traces = traces.MemoryTraces(
            kind=TraceKind.MEMORY_WRITE,
            sink=traces_sink,
            now=traces_now,
            owner="MemoryIngestor write traces",
        )
        self._id_factory = id_factory
        self._reconciler = reconciler
        # Guards the read-modify-write in `ingest` and `apply` (issue #248), kept by
        # ADR-0219 §5 beside the conditional write: it serialises the injected policy's
        # `decide` within one ingestor and keeps the common case off the retry path.
        self._lock = asyncio.Lock()

    async def ingest(self, proposal: MemoryUpdateProposal) -> MemoryIngestResult:
        """Detect conflicts, apply the policy, and persist the outcome (ADR-0328 §11:4).

        One **read-modify-write**, closed by two mechanisms (#248, ADR-0219 §5): the
        lock keeps two ingests through this object from interleaving, and every write
        derived from a read is conditional on that read's revision, so a record another
        writer moved in between is refused and :meth:`_ingest` re-runs the whole cycle
        once against the store as it now stands.

        **The refusals**, in the order they fire: a support pointing at an episode the
        store does not hold (ADR-0328 §4:7, ``UnresolvedEvidenceError``); more conflicts
        than one ingest resolves (ADR-0079 §1); after the ruling, a write-producing
        ruling on secret-tier data (ADR-0078 §5b), a ``STORE_TEMPORARY`` ruling
        (ADR-0328 §10:3), and a write landing at an id the proposal's supports point at
        (ADR-0081 §1); at the fold, a fold onto an ``ASSERTED`` target no exception admits
        (ADR-0045 §5, ADR-0078 §5b, ADR-0121 §5) and a ``SUPERSEDE`` naming a conflict
        this writer holds a ``RESTATES`` or ``ADDS`` relation for (ADR-0159 §5); and an
        end §5:10, §5:11 or §6:5 refuses, or a retired memory already carrying the part
        the new memory's first support points at (§11:7).

        Args:
            proposal: The memory to rule on and persist.

        Returns:
            The policy's decision and the id left live, if anything was written.

        Raises:
            UnresolvedEvidenceError: If a support points at an episode the store does
                not hold; nothing is written and the policy is not asked.
            MemoryStoreError: On every other refusal above, or any store failure,
                including the ``MemoryStoreStaleError`` a write raises where both of its
                two attempts met a record another writer had moved (ADR-0219 §5).
        """
        # One observation of the caller's proposal, on this coroutine's first executed
        # line — before the lock, which is `ingest`'s first await (ADR-0065, #366).
        observed = proposal.model_copy(deep=True)
        ingested = await self._traces.observing(
            traces.SEAM_INGEST,
            self._locked_ingest(observed),
            _proposal_reading,
            entry={traces.PROPOSALS: 1},
        )
        return ingested.result

    async def apply(self, change: MemoryChange) -> None:
        """Apply one operation to one stored memory (ADR-0328 §11:3).

        The record the operation yields is computed by
        :func:`~ai_assistant.core.types.applied_operation` from the memory the caller
        read, and written ``IF_UNCHANGED`` at that memory's revision (§5:4), with the
        successor an end, a mark wrong or a replace names written ``INSERT_IF_ABSENT`` in
        the same atomic batch (§5:6). An add support whose part the memory already
        carries changes nothing, and nothing is written (§4:8).

        Args:
            change: The memory as read, the operation, and what it brings.

        Raises:
            UnresolvedEvidenceError: If the support it adds, or a support of the
                successor, points at an episode the store does not hold (§4:7).
            MemoryStoreStaleError: If the stored memory is not the one read.
            MemoryStoreConflictError: If the successor's id names a stored record.
            MemoryStoreError: If §4, §5 or §6:5 refuses the operation, or a store
                failure. Nothing is written.
        """
        observed = change.model_copy(deep=True)
        async with self._lock:
            await self._apply_change(observed)

    async def _apply_change(self, change: MemoryChange) -> None:
        memory = change.memory
        added = _newly_added(memory, change.support)
        successor = () if change.successor is None else change.successor.supports
        await self._require_held_episodes(memory.id, (*added, *successor))
        try:
            after = applied_operation(
                memory, change.operation, support=change.support, question=change.question
            )
        except ValueError as exc:
            msg = f"refusing to apply a {change.operation.kind} to {memory.id!r}: {exc}"
            raise MemoryStoreError(msg) from exc
        if after is memory:
            return
        batch = [
            MemoryWrite(
                record=after,
                mode=MemoryWriteMode.IF_UNCHANGED,
                expected_revision=memory.revision,
            )
        ]
        if change.successor is not None:
            batch.append(
                MemoryWrite(
                    record=_installed(change.successor), mode=MemoryWriteMode.INSERT_IF_ABSENT
                )
            )
        await self._store.write_atomic(batch)

    async def _locked_ingest(self, proposal: MemoryUpdateProposal) -> _Ingested:
        """One proposal under the ordinary per-proposal hold."""
        async with self._lock:
            return await self._ingest(proposal)

    async def _ingest(self, observed: MemoryUpdateProposal) -> _Ingested:
        """One proposal's read-modify-write, re-run once if the store moved under it.

        ADR-0219 §5's bound: two attempts in all, the re-run the whole cycle and never a
        re-submission of the payload computed over the rejected snapshot.

        Raises:
            MemoryStoreStaleError: If a second attempt is also refused as stale.
        """
        try:
            return await self._ingest_once(observed)
        except MemoryStoreStaleError:
            return await self._ingest_once(observed)

    async def _ingest_once(self, observed: MemoryUpdateProposal) -> _Ingested:
        await self._require_held_episodes(observed.proposed.id, observed.proposed.supports)
        conflicts = await self._detect_conflicts(observed.proposed)
        resolved = tuple(record.id for record in conflicts)
        # `observed` is kept rather than rebound: its `conflicts` are the frozen ids the
        # question was asked about, and ADR-0078 §5b check 4 recomputes the
        # `question_key` from exactly those.
        ruled = observed.model_copy(update={"conflicts": resolved})
        determined = await self._relations_for(ruled, conflicts)
        relations = determined.relations
        decision = await self._policy.decide(
            ruled,
            conflicts=conflicts,
            relations=None
            if relations is None or self._reconciler is None
            else MappingProxyType(dict(relations)),
        )
        _refuse_secret_write(decision, observed)
        _refuse_tentative_store(decision)
        _refuse_self_consuming_write(decision, observed, resolved=resolved)
        applied = await self._apply(
            decision, observed, conflicts, resolved=resolved, relations=relations or {}
        )
        return _Ingested(
            result=MemoryIngestResult(
                decision=decision, record_id=applied.record_id, conflicts=resolved
            ),
            superseded=applied.superseded,
            reconciliation=determined,
        )

    async def _relations_for(
        self, proposal: MemoryUpdateProposal, conflicts: Sequence[MemoryRecord]
    ) -> _Reconciliation:
        """The relations **this writer** holds for one ingest, and what it observed.

        A ``relations`` of ``None`` means no relation was determined at all —
        ADR-0159 §2's condition excluded this ingest — and it is the value ADR-0159
        §8 distinguishes from an empty mapping, which says something ran and
        labelled nothing. Both rule identically under §4; only one of them is a fact
        a ``reason`` or a later trace can report, and erasing the distinction at the
        seam would make it unrecoverable.

        Two sources, in one order:

        1. **ADR-0121 §1's certain predicate**, computed here whether or not a
           reconciler is injected. It is ADR-0159 §3's first rung, and computing it
           at the writer is what ADR-0159 §5 means by "the ``agrees`` half, which
           every writer can compute with no model": the retirement exclusion holds
           against a restatement in a deployment with no provider at all. It also
           wins over anything a reconciler says about the same pair, which is
           ADR-0038 §2a's recompute-at-the-boundary shape rather than a distrust of
           the injected component — §3 already rules that a reconciler answering
           differently on a pair ``agrees`` admits is not conforming.
        2. **The reconciler's determination**, restricted to members of this
           conflict set. An id it invented names nothing, and is dropped here rather
           than left for the policy's own ignore rule to absorb (ADR-0159 §8).

        **It never fails the ingest** (ADR-0159 §3, §6). A reconciler owes a
        never-raises contract, and this guard is the boundary honouring §6's
        stronger promise — "no ingest is refused or ruled differently because a
        reconciler was unavailable, other than by the relations it therefore does
        not hold" — against a non-conforming one as well as an absent one.

        **Two clauses of ADR-0164 §3 extend that absorption from shapes to values
        and to combinations, and neither moves a ruling.** A returned mapping
        supplying, for a member this writer reads it for, a value that **is** not a
        ``ConflictRelation`` member is non-conforming *in whole*: nothing from it
        installs. That is not defensive typing — ``DefaultMemoryPolicy`` selects on
        ``is``, so a value merely *equal* to a member (``ConflictRelation`` is a
        ``StrEnum``, so the bare string ``"contradicts"`` compares equal to
        ``CONTRADICTS`` and hashes with it) is unlabelled to the arm today while a
        mapping keyed by the enum would find it and count it, and the trace would
        report a model contradiction the arm never saw. And a report claiming *less*
        than the labels beside it — ``unconsulted`` or ``failed`` arriving with model
        labels — is incoherent, so those labels are discarded too. Both discard the
        mapping **whole**, which is the shape the guard below already has: partial
        trust would let one trace say a model label stood *and*, through the answered
        arithmetic, that no model rung answered on that proposal.

        **The members a returned mapping is read for are this crossing's resolved
        conflict set less those the certain rung labelled, and nothing wider.** An id
        the mapping invented is dropped unread (ADR-0159 §8) and a value for a member
        the certain rung labelled is discarded unread (§3), so neither can make a
        mapping non-conforming. A **beyond-bound** entry is read like any other: this
        writer holds no consulted set to except it with, and a mapping still carrying
        one is already the output of a reconciler ADR-0159 §3 obliged to discard it.
        Whether a *well-formed* beyond-bound label should also be refused is
        ADR-0159's enforcement question, which ADR-0164 §9 declines and #1225 records.

        Args:
            proposal: The proposal, carrying this ingest's resolved conflict ids.
            conflicts: The resolved conflict set, best-ranked first.

        Returns:
            The relations determined — ``None`` where none may be — beside the
            quantities ADR-0164 §3 counts. Nothing here reads the observation back:
            it travels to the trace and to nowhere else.

        Raises:
            asyncio.CancelledError: Where one was delivered from **outside** this
                ingest. It is delivered onward under ADR-0060 §1's second clause,
                never converted into an unlabelled member and never allowed to stand
                as a completed write; the lock releases as it unwinds. The guard
                below is stated over ``Exception``, and ``CancelledError`` is a
                ``BaseException``, so this holds by construction. A deadline
                ``models/`` issues against its **own** request is not such a
                cancellation — it is the self-issued kind ADR-0060 §1 distinguishes
                — and is classified into unlabelled like any other timeout.
        """
        if not _may_reconcile(proposal, conflicts):
            return _Reconciliation(relations=None)
        record = proposal.proposed
        own = {
            conflict.id: ConflictRelation.RESTATES
            for conflict in conflicts
            if agrees(conflict, record)
        }
        offered = len(conflicts)
        certain = len(own)

        def reading(
            relations: dict[str, ConflictRelation],
            *,
            qualifier: str | None = None,
            model_labels: tuple[ConflictRelation, ...] = (),
        ) -> _Reconciliation:
            """This ingest's pair counts, whichever arm below produced the labels.

            Args:
                relations: What this writer ends up holding.
                qualifier: The metric key the proposal counts under, if any.
                model_labels: The reconciler's labels that stand.

            Returns:
                The determination and its reading.
            """
            return _Reconciliation(
                relations=relations,
                qualifier=qualifier,
                offered=offered,
                certain_restates=certain,
                model_labels=model_labels,
            )

        if self._reconciler is None:
            # ADR-0159 §6's ratified floor, and the one qualifier this writer
            # observes about *itself*. It counts under ``reconciler_absent`` alone
            # and never under ``reconciler_unconsulted``, which is a statement about
            # a reconciler that ran.
            return reading(own, qualifier=traces.RECONCILER_ABSENT)
        failed = reading(own, qualifier=traces.RECONCILER_FAILED)
        outcome: ReconcilerOutcome | None = None
        labelled: dict[str, ConflictRelation] | None = None
        try:
            report = await self._reconciler.reconcile(proposal, conflicts)
            # **Read inside the guard, not after it.** A reconciler that *returns*
            # something unusable — ``None``, a non-mapping, a mapping whose lookup
            # raises, a report naming no outcome — is as non-conforming as one that
            # raises, and reading it outside would let it refuse the ingest through
            # a ``TypeError`` instead of degrading. ADR-0159 §6 admits no such
            # route: "no ingest is refused or ruled differently because a
            # reconciler was unavailable, other than by the relations it therefore
            # does not hold."
            outcome = _sole_outcome(report)
            determined = report.relations
            labelled = _installable(
                {
                    conflict.id: determined[conflict.id]
                    for conflict in conflicts
                    if conflict.id not in own and conflict.id in determined
                }
            )
        # A raise leaves both readings at ``None``, which is the same answer the
        # non-conforming *returns* below reach — ADR-0159 §3 rules the two
        # identically, and one arm here is what keeps them from drifting.
        except Exception:
            labelled = None
        if labelled is None:
            return failed
        if outcome is ReconcilerOutcome.ANSWERED:
            return reading(labelled | own, model_labels=tuple(labelled.values()))
        if outcome is ReconcilerOutcome.UNCONSULTED and not labelled:
            return reading(own, qualifier=traces.RECONCILER_UNCONSULTED)
        # What is left is every incoherence ADR-0164 §3 rules on at once: a report
        # of ``unconsulted`` or ``failed`` arriving **with** labels, a report of
        # ``failed`` arriving without them, and a report naming none of the three or
        # more than one of them. All discard the mapping whole and count here,
        # because a reader who could not tell them apart from a broken determination
        # would have no conclusion to draw from either.
        return failed

    async def _require_held_episodes(
        self, memory_id: str, supports: Sequence[MemorySupport]
    ) -> None:
        """Refuse supports pointing at an episode the store does not hold (ADR-0328 §4:7).

        Every support but a legacy one, whatever the memory's band — ADR-0077 §5's
        resolvability floor, which ADR-0328 widens from a derived record's citations to
        every support. Read through one ``get_many``, so the episodes are judged against
        one state of the store. The ids are reported in support order, once each.

        Raises:
            UnresolvedEvidenceError: If any support's episode does not resolve; nothing
                is written and no ruling is sought.
        """
        episodes = list(
            dict.fromkeys(
                episode
                for episode in (part_episode(support.points_at) for support in supports)
                if episode is not None
            )
        )
        if not episodes:
            return
        held = await self._store.get_many(episodes)
        unresolved = [
            episode
            for episode in episodes
            if (found := held.get(episode)) is None or found.kind != MemoryKind.EPISODIC.value
        ]
        if unresolved:
            msg = (
                f"refusing to write {memory_id!r}: {len(unresolved)} of its supports point at "
                f"an episode this store does not hold — "
                f"{', '.join(repr(one) for one in unresolved)} (ADR-0328 §4:7)"
            )
            raise UnresolvedEvidenceError(msg, unresolved)

    async def _detect_conflicts(self, memory: Memory) -> list[MemoryRecord]:
        """Return every conflict retrieval surfaced, or refuse above the ceiling.

        ``conflict_limit`` is a **ceiling, not a truncation budget** (ADR-0079 §1). Two
        rows of headroom over it: one for the proposal's own memory (#110), one for the
        overflow probe. Conflicts are memories alone: an episode is never one.

        Raises:
            MemoryStoreError: If retrieval surfaced more conflicts than this ingestor
                will resolve in one ingest.
        """
        found = await self._store.search(
            memory.content,
            limit=self._conflict_limit + 2,
            kinds=[MemoryKind.MEMORY],
        )
        conflicts = [
            match
            for match in found.records
            if match.id != memory.id and (match.score or 0.0) >= self._conflict_threshold
        ]
        if len(conflicts) > self._conflict_limit:
            msg = (
                f"refusing to ingest {memory.id!r}: conflict resolution surfaced more than "
                f"{self._conflict_limit} conflicting records, more than one ingest resolves. "
                f"Nothing was written and no ruling was sought — a correction resolves every "
                f"conflict it is shown, or it does not land (ADR-0079 §1)"
            )
            raise MemoryStoreError(msg)
        return conflicts

    async def _apply(
        self,
        decision: MemoryDecision,
        proposal: MemoryUpdateProposal,
        conflicts: list[MemoryRecord],
        *,
        resolved: tuple[str, ...],
        relations: Mapping[str, ConflictRelation],
    ) -> _Applied:
        proposed = proposal.proposed
        match decision.kind:
            case MemoryDecisionKind.ACCEPT:
                return _Applied(await self._install(_installed(proposed)))
            case MemoryDecisionKind.REINFORCE | MemoryDecisionKind.SUPERSEDE:
                target = next((c for c in conflicts if c.id == decision.target_id), None)
                if target is None:
                    msg = f"fold target {decision.target_id!r} is not among the conflicts"
                    raise MemoryStoreError(msg)
                _refuse_unsafe_fold(target, proposal, decision.kind, resolved=resolved)
                _refuse_retiring_a_related_conflict(target, decision.kind, relations)
                if decision.kind is MemoryDecisionKind.SUPERSEDE:
                    retiring = _retirement_set(
                        target,
                        conflicts,
                        proposal=proposal,
                        resolved=resolved,
                        relations=relations,
                    )
                    return _Applied(
                        await self._apply_supersede(retiring, proposed),
                        tuple(record.id for record in retiring),
                    )
                return _Applied(
                    await self._fold(
                        _installed(_reinforced(target, proposed, now=self._now_utc())),
                        # ADR-0219 §5: conditional on the revision of the record the fold
                        # was derived from, read off `target` and never off a record this
                        # ingestor built (§2).
                        expected_revision=target.revision,
                    )
                )
            case _:  # REJECT, ASK_USER — nothing is written.
                return _Applied(None)

    async def _install(self, record: MemoryRecord) -> str:
        """Write ``record`` as a **new** record, refusing a colliding id.

        ADR-0108 §2's routing for the installing rulings. The ruling that reached
        here is that the proposal contradicts nothing retrieval surfaced, so an id
        already naming a stored record is an accident in every case — a minting
        producer whose factory collided — and the honest response is a refusal
        rather than a silent replacement of a record no ruling was made about
        (#630, and #110 for why conflict detection cannot see it).

        **The absence check costs no read and cannot be raced** (ADR-0108 §1):
        ``INSERT_IF_ABSENT`` is enforced by the store inside the transaction that
        writes, not by a ``get`` this method would have to pay for and could be
        raced against. A one-element batch is otherwise exactly ``add`` — ADR-0046
        §2 rules the degenerate batch legal and equivalent, and
        ``SqliteMemoryStore`` shares ``_persist_record`` and ``_embed_one``
        between the two.

        **Nothing is re-minted.** ``_apply_supersede`` re-mints its correction's id
        on collision, and that is not a precedent here: that id is the *ingestor's*
        own, while this one is the producer's. Re-minting it would edit a record
        the producer made (ADR-0081 §9) and return an id nobody proposed. The
        conflict propagates, and its documented remedy — re-mint and re-propose —
        is the producer's to take.

        Raises:
            MemoryStoreConflictError: ``record.id`` already names a stored record.
                Nothing is written.
            MemoryStoreError: Any other store failure. Nothing is written.
        """
        written = await self._store.write_atomic(
            [MemoryWrite(record=record, mode=MemoryWriteMode.INSERT_IF_ABSENT)]
        )
        return written[0]

    async def _fold(self, record: MemoryRecord, *, expected_revision: int) -> str:
        """Write ``record`` at the fold target's id, conditional on that target.

        ADR-0108 §2's one deliberate upsert, made **conditional** by ADR-0219 §5.
        A ``REINFORCE`` folds at the *target the ruling named* (:func:`_merge` keeps
        the target's id), so landing on a stored record is the decision rather than
        a collision — this is exactly the case ADR-0022 §4 protected when it
        defended the upsert. What ADR-0219 adds is that the record standing there
        must still be the one the fold was computed over: an ``UPSERT`` would
        overwrite a target another writer moved between this ingest's search and
        this write, discarding that writer's content and its evidence while handing
        both callers a healthy ``MemoryIngestResult`` (issue #248, ADR-0046 §5).

        The declaration survives the change rather than being replaced by it.
        ``IF_UNCHANGED`` is still a mode named at the call and still greppable, and
        it says strictly more than ``UPSERT`` did: this write may destroy a standing
        record, and only the one it read.

        It goes through ``write_atomic`` rather than ``add`` — and now could not go
        through ``add`` at all, since ADR-0219 §2 leaves ``add`` unconditional and
        makes ``write_atomic`` the only conditional door.

        Args:
            record: The merged record, already at the target's id.
            expected_revision: The ``revision`` of the record this fold was derived
                from — the target as conflict detection read it, never the merged
                record's own (ADR-0219 §2).

        Raises:
            MemoryStoreStaleError: The target moved, or was deleted, between the
                read this fold was computed over and this write. Nothing is
                written; :meth:`_ingest` re-runs the whole cycle once.
            MemoryStoreError: The store refused the write — including a cross-kind
                collision, ADR-0108 §4's backstop, which a ``REINFORCE`` cannot
                reach because its target came from a kind-filtered search. Nothing
                is written.
        """
        written = await self._store.write_atomic(
            [
                MemoryWrite(
                    record=record,
                    mode=MemoryWriteMode.IF_UNCHANGED,
                    expected_revision=expected_revision,
                )
            ]
        )
        return written[0]

    async def _apply_supersede(self, targets: list[MemoryRecord], proposed: Memory) -> str:
        """End every ``target`` and install ``proposed`` at a fresh id, atomically.

        ``targets`` is the full retirement set (:func:`_retirement_set`). The batch is
        ``[IF_UNCHANGED(ended target) for each target] + [INSERT_IF_ABSENT(new)]``
        (ADR-0046, ADR-0219 §5), so a failure part-way cannot leave memories retired with
        no live replacement (ADR-0045 §8). Each target is ended by an end citing the new
        memory's first support, added to it as an ``against`` support, and naming the new
        memory as its successor; the new memory's create names every one of them among
        those it replaces (ADR-0328 §11:7, §5:6). One clock reading serves every end
        (ADR-0080 §1).

        The new id is minted by the guarded id factory and re-minted, within
        :data:`_MAX_SUPERSEDE_ATTEMPTS`, past an id that collides with a stored record, an
        id a target holds, or an id the proposal's supports point at (ADR-0081 §4).

        Returns:
            The **live** memory's id — the fresh one (ADR-0045 §4).

        Raises:
            MemoryStoreStaleError: If any target moved between this ingest's read and the
                batch; nothing is written and :meth:`_ingest` re-runs the cycle.
            MemoryStoreError: If the id factory is malformed, an end is refused, the
                bounded re-mint finds no free id, or any other store failure — every target
                left live and unchanged.
        """
        now = self._now_utc()
        retired_ids = [target.id for target in targets]
        cited = _cited_ids(proposed)
        last_conflict: MemoryStoreConflictError | None = None
        for _ in range(_MAX_SUPERSEDE_ATTEMPTS):
            new_id = _checked_id(self._id_factory, owner="MemoryIngestor")
            if new_id in cited or new_id in retired_ids:
                last_conflict = MemoryStoreConflictError(
                    f"minted id {new_id!r} is cited by the proposal or names a retired memory; "
                    f"re-minting"
                )
                continue
            successor = _installed(_supersede(proposed, new_id, retired_ids))
            batch = [
                MemoryWrite(
                    record=_ended(target, successor, now),
                    mode=MemoryWriteMode.IF_UNCHANGED,
                    expected_revision=target.revision,
                )
                for target in targets
            ]
            batch.append(MemoryWrite(record=successor, mode=MemoryWriteMode.INSERT_IF_ABSENT))
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

        Load-bearing for every instant this writer stamps through
        ``model_copy(update=...)``, which does **not** re-run validators: an added
        support's ``added_at`` reaches the store exactly as this method left it, so the
        guard at the producer is the whole protection on that path.

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
