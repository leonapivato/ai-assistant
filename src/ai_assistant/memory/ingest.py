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
from typing import TYPE_CHECKING, assert_never

from ai_assistant.core.clock import ClockReadingError, checked_clock
from ai_assistant.core.errors import (
    MemoryStoreConflictError,
    MemoryStoreError,
    UnresolvedEvidenceError,
)
from ai_assistant.core.types import (
    MAX_EVIDENCE_CITATIONS,
    BeliefBand,
    DataTier,
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
    from collections.abc import Callable, Sequence

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


# --- two classes, because one constant answered two questions (ADR-0092 §5) ---
# Until ADR-0092 these were a single `_SUPERSEDABLE` frozenset, and they were the
# same set only by coincidence. §4 breaks the coincidence, and the split is the
# whole of ADR-0092 §5: widening one identifier would have made the *reinforce*
# refusal below stop firing for an `EXTERNAL` target — a one-line change that
# passes the gate and reopens the exact data loss ADR-0038 §2a reproduced.
#
# **They must not be tidied back into one.** ADR-0092's Consequences names this as
# the kind of thing a later reader merges; the conformance case pinning the
# `USER_ASSERTED` -> `EXTERNAL` `REINFORCE` refusal is what stops the tidy-up. The
# general shape is worth naming, since it is the second time this file has produced
# it: ADR-0045 §5 had to make the same refusal *relation*-aware after ADR-0040 §3
# had keyed it on the records. A set that answers two questions answers neither once
# the questions come apart.

#: The **retirement class** — beliefs a correction is warranted to retire, used by
#: :func:`_retirement_set`'s widening (ADR-0050 §1, ADR-0079 §3, widened by ADR-0092
#: §4). Held here as well as in `policy`, deliberately: the policy chooses, but
#: `MemoryIngestor` takes rulings from *any* injected `MemoryPolicy`, so the safety
#: property has to hold at the boundary that performs the write rather than at the
#: one that recommends it. Still an allow-list rather than "not USER_ASSERTED", so a
#: `MemorySource` added later is not enrolled in a destructive rule by omission
#: (ADR-0038 §2a's surviving argument).
_RETIREMENT_CLASS = frozenset({MemorySource.OBSERVED, MemorySource.INFERRED, MemorySource.EXTERNAL})

#: The **reinforce-safe class** — targets a user assertion may safely fold onto *at
#: the target's id*, used by :func:`_refuse_unsafe_fold`'s ``REINFORCE`` arm
#: (ADR-0038 §2a, narrowed to ``REINFORCE`` by ADR-0045 §5b). Membership means
#: "does not carry a foreign idempotency key", and **``EXTERNAL`` still does not
#: satisfy it**: a `REINFORCE` inherits the target's id, so a correction folded onto
#: an imported record is overwritten by the next routine sync. ADR-0092 §4 widened
#: what an assertion may *retire* and has no ground to touch what it may fold onto —
#: a `SUPERSEDE` is safe there only because ADR-0045 §4 makes it mint a fresh id.
_REINFORCE_SAFE = frozenset({MemorySource.OBSERVED, MemorySource.INFERRED})

#: The rulings that dispatch a write. Check 0 (:func:`_refuse_secret_write`) gates
#: exactly these and nothing else, because ADR-0004 §3 forbids a secret **in the
#: database** rather than a secret being judged: ``ASK_USER`` and ``REJECT`` write
#: nothing, so refusing them would break the ordinary secret-tier path ADR-0078 §1
#: promises to preserve. Derived as a complement rather than listed, so a sixth
#: write-producing ruling joins the gate rather than slipping past a list nobody
#: updated.
_WRITE_PRODUCING_KINDS = frozenset(MemoryDecisionKind) - {
    MemoryDecisionKind.ASK_USER,
    MemoryDecisionKind.REJECT,
}


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
    target: MemoryRecord,
    proposal: MemoryUpdateProposal,
    kind: MemoryDecisionKind,
    *,
    resolved: tuple[str, ...],
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
      source, under either ruling, may fold onto an assertion — **except** under a
      confirmation that covers this very target (:func:`_confirmation_covers`,
      ADR-0078 §5b). There the signal is not topical similarity: it is the user's
      answer, which ADR-0045 §7 named as one of the two acceptable gates. The
      clause is therefore **narrowed by exception, not lifted**, and it stands
      verbatim in every other case.
    - **Clause 2 — a ``USER_ASSERTED`` proposal onto an ``EXTERNAL`` target,
      ``REINFORCE`` only.** The external id is that system's idempotency key. A
      ``REINFORCE`` still inherits it, so the correction is overwritten by the next
      routine sync (ADR-0038 §2a) — the refusal stays. A ``SUPERSEDE`` now gets a
      *fresh* id (ADR-0045 §4), so that hazard is gone and an ``EXTERNAL``
      supersession is permitted at the writer boundary (ADR-0045 §5b). The arm is
      therefore **narrowed to ``REINFORCE``**, not removed. Untouched by ADR-0078.

      **It is keyed on :data:`_REINFORCE_SAFE` and not on the retirement class, and
      the two are no longer the same set** (ADR-0092 §5). ADR-0092 §4 put
      ``EXTERNAL`` in the class a correction may *retire*; had this arm kept reading
      that class, ``source not in …`` would have gone false for an ``EXTERNAL``
      target and this refusal would have silently stopped firing — reopening the
      loss ADR-0038 §2a reproduced and ADR-0045 §5 kept refused by name. The two
      questions are different: this one asks "may an assertion fold at *this
      record's* id", which turns on whether the id is a foreign system's key.

    ``DefaultMemoryPolicy`` proposes none of these — its rule 4 defers, and rule 6
    names a retirable conflict for ``SUPERSEDE`` rather than ``REINFORCE`` — but a
    policy reaches the ingestor through an injected seam and any conforming
    implementation may rule differently. The refusal therefore lives here, at the
    boundary that performs the write, rather than in the policy that recommends it.
    That is also why the exception is **verified rather than trusted**: a gate that
    opened on an unexamined field would hand that guarantee back to the caller's
    good intentions (ADR-0078 §5b).

    Fail-closed rather than silently downgrading, for the reason that already
    makes an absent fold target raise instead of falling back to storing the
    proposal as new: a write that loses data while reporting success is worse
    than one that stops.

    Args:
        target: The conflict the ruling names.
        proposal: The proposal **as handed to ``ingest``** — whose ``conflicts``
            are the frozen ids the question was asked about, read *before*
            conflict resolution replaced them (ADR-0078 §5b check 4).
        kind: The ruling being applied.
        resolved: The conflict ids *this* ingest resolved — the live set.

    Raises:
        MemoryStoreError: If the fold is one of the two above and no covering
            confirmation permits it.
    """
    incoming = proposal.proposed
    if target.provenance.source is MemorySource.USER_ASSERTED and not _confirmation_covers(
        target, proposal, kind, resolved=resolved
    ):
        msg = (
            f"refusing to fold onto {target.id!r}: a {incoming.provenance.source} record may not "
            f"be folded onto a user-asserted one, whose belief it would overwrite "
            f"(ADR-0038 §3, ADR-0045 §5, narrowed by ADR-0078 §5b)"
        )
        raise MemoryStoreError(msg)
    if (
        kind is MemoryDecisionKind.REINFORCE
        and incoming.provenance.source is MemorySource.USER_ASSERTED
        and target.provenance.source not in _REINFORCE_SAFE
    ):
        msg = (
            f"refusing to reinforce {target.id!r}: a user assertion may not be reinforced onto a "
            f"{target.provenance.source} record, whose id it would inherit and the next sync "
            f"overwrite — only OBSERVED and INFERRED beliefs may be reinforced this way "
            f"(ADR-0038 §2a, narrowed to REINFORCE by ADR-0045 §5b)"
        )
        raise MemoryStoreError(msg)


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
       refused whatever the confirmation says: folding at the target's id would
       rewrite the user's own words, which no answer authorises.
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

    **A refusal at the writer boundary, independent of the model validator**
    ``DeferredProposal`` and ``MemoryUpdateProposal`` carry, because a validator is
    not a boundary: ``model_construct`` and ``model_copy(update=...)`` both skip
    validation, and this repository already treats a definition "tampered past
    ``frozen=True`` with ``object.__setattr__``" as inside its threat model
    (ADR-0018 §3, ADR-0021 §4). Without this, every check in
    :func:`_confirmation_covers` can pass on a validator-bypassing secret proposal
    under an injected ``SUPERSEDE`` policy and the writer persists a secret to the
    ``MemoryStore`` — ADR-0004 §3's "never in the memory database", reached through
    the one seam whose whole job is to refuse writes nobody authorised.

    **It gates the write, not the ruling, and the placement follows from that.** It
    runs *after* the policy has ruled and *before* any write is dispatched, so it
    reaches every write-producing ruling and no ruling that writes nothing. Both
    ends are load-bearing:

    - **Not inside** :func:`_refuse_unsafe_fold`, which ``ingest`` reaches only for
      ``REINFORCE`` and ``SUPERSEDE`` — that would let an injected policy ruling
      ``ACCEPT`` or ``STORE_TEMPORARY`` write the secret straight through
      :meth:`MemoryIngestor._apply`.
    - **Not at the top of ``ingest`` either.** An unconditional refusal *before* the
      policy runs would turn the ordinary secret-tier path into an error: today a
      secret ``learn`` reaches ``DefaultMemoryPolicy``, is ruled ``ASK_USER``,
      writes nothing and raises nothing (ADR-0078 §1), and that behaviour is what
      ADR-0078 preserves. ADR-0004 §3 forbids a secret *in the database*, not a
      secret being *judged*.

    So ``ASK_USER`` and ``REJECT`` return normally, because neither writes anything.

    Raises:
        MemoryStoreError: If the ruling would write and the proposal is Tier 0.
            Nothing is written.
    """
    if decision.kind in _WRITE_PRODUCING_KINDS and proposal.sensitivity is DataTier.SECRET:
        msg = (
            f"refusing to write {proposal.proposed.id!r}: a {decision.kind} ruling on secret-tier "
            f"data would put Tier 0 content in the memory database, which lives in the OS keyring "
            f"and never in a database or a committed file (ADR-0004 §3, ADR-0078 §5b)"
        )
        raise MemoryStoreError(msg)


def _installed_at(
    decision: MemoryDecision, proposed: MemoryRecord, *, resolved: tuple[str, ...]
) -> str | None:
    """The id this ruling would **install** the proposal at, if any (ADR-0081 §1).

    A write *installs* when it stores the proposal's content at an id: whatever
    stood there stops being retrievable and the id now names the belief the
    proposal carries. A write *retires* when it stores an **existing** record back
    with only its validity window narrowed (ADR-0080 §1) — the record is retained,
    ``export`` still carries it, and nothing of the proposal lands at its id.

    ``None`` means "this ruling installs nothing at an id known here":

    - ``REJECT`` and ``ASK_USER`` write nothing at all.
    - ``SUPERSEDE`` installs at a **freshly minted** id that does not exist until
      :meth:`MemoryIngestor._apply_supersede` mints it, so its candidate is tested
      *there*, inside the bounded re-mint loop, and a hit re-mints rather than
      refusing (ADR-0081 §2's "two evaluation points, one rule", §4). Its
      retirement-set writes retire rather than install and are never refused by
      this rule.
    - a ``REINFORCE`` whose ``target_id`` is **not among the conflicts this ingest
      resolved**. ADR-0081 §6 defines the fold's write id as "its fold target,
      which is **drawn from the conflicts** and therefore always stored", so a
      ruling naming anything else has no destination at all: it installs nothing,
      and the standing "not among the conflicts" refusal in
      :meth:`MemoryIngestor._apply` is what applies — which is what §6 means by "a
      ``REINFORCE`` naming a target absent from the conflicts still raises the
      existing not-among-the-conflicts error". Reading the ruling's ``target_id``
      as a destination without that test would let this rule pre-empt a standing
      refusal, and ADR-0081 §4 is explicit that it "adds one refusal to the writer
      and subtracts none".

    ``resolved`` is therefore an input, and it costs nothing: it is the tuple
    :meth:`MemoryIngestor._ingest` already computed from the conflict search
    *before* the policy was asked, fixed inside the ingestor's lock. So the
    predicate still performs **no store read** of its own, adds no I/O, and cannot
    be raced (ADR-0081 §1) — it reads a value the call is already holding.

    The install/retire distinction is a property of the **write**, not of what the
    store happens to hold, which is what keeps the predicate free of any store read.
    """
    match decision.kind:
        case MemoryDecisionKind.ACCEPT | MemoryDecisionKind.STORE_TEMPORARY:
            return proposed.id
        case MemoryDecisionKind.REINFORCE:
            # The fold lands at the *target's* id, which the ruling supplies —
            # never at `proposed.id`. `_merge` writes there and unions both
            # evidence tuples, so a proposal citing its own fold target would end
            # up standing as its own warrant with nothing destroyed at all. A
            # target outside the resolved set is no destination: nothing is folded
            # onto it, and `_apply` refuses it on the standing ground.
            return decision.target_id if decision.target_id in resolved else None
        case MemoryDecisionKind.SUPERSEDE:
            return None
        case MemoryDecisionKind.REJECT | MemoryDecisionKind.ASK_USER:
            return None
    # No `case _`: with every member named, mypy narrows the fall-through to
    # `Never`, so a *new* `MemoryDecisionKind` fails the type check here rather
    # than silently acquiring an unguarded write (the fail-closed shape
    # `_WRITE_PRODUCING_KINDS` gets from being a complement).
    assert_never(decision.kind)


def _refuse_self_consuming_write(
    decision: MemoryDecision, proposal: MemoryUpdateProposal, *, resolved: tuple[str, ...]
) -> None:
    """Refuse a write that would land at an id the proposal cites (ADR-0081 §1).

    The fourth obligation on ``MemoryWriter.ingest``, stacked on ADR-0079 §4's two
    and ADR-0077 §5's one and conflicting with none of them. Those are about the
    *conflict* set and about the evidence set's *existence*; this one is about the
    write set's **disjointness** from the evidence set. ADR-0077 §5's check buys
    "every citation resolved once" — a write that consumes its own citation makes
    that promise true and useless in the same instant, and leaves a belief standing
    as its own warrant.

    **It gates the write, not the ruling**, so it sits between the policy's ruling
    and the write dispatch — the seam :func:`_refuse_secret_write` already occupies,
    reached by every write-producing ruling and by no ruling that writes nothing
    (ADR-0081 §2). Three placements are ruled out there, each for a reason already
    on the record:

    - **Not in** :meth:`MemoryIngestor._require_resolvable_evidence`, which runs
      before the policy — at which point the write set is not yet known, because
      ``REINFORCE``'s destination is ``decision.target_id``.
    - **Not in** :func:`_refuse_unsafe_fold`, which ``ACCEPT`` and
      ``STORE_TEMPORARY`` never reach — the same hole ADR-0078 §10 records when it
      excepts check 0 from that helper, and those two rulings carry most of this
      defect.
    - **Not split in two**, with the ``proposed.id`` half hoisted ahead of the
      ruling where it *is* computable. That would put one rule in two places
      (ADR-0077 §5) and pre-empt a ruling the policy is entitled to make: a
      self-citing proposal the policy declines should be a ``REJECT`` the user can
      read, not an exception (ADR-0080 §3 declined the same hoist).

    **It reads nothing from the store.** Its inputs are the observed proposal, the
    ruling, and the conflict ids this ingest already resolved — all fixed and
    private to this call before it is reached, so it costs no ``get``,
    adds no I/O inside the ingestor's lock, and — unlike ADR-0077 §5's
    resolvability check — cannot itself be raced. It is therefore never a race and
    always a producer fault, which is why the refusal earns **no** new error class
    (§3) and specifically is **not** ``UnresolvedEvidenceError``: the evidence here
    resolves perfectly well, and what is wrong is that the write would consume it.

    The empty-slot case is refused too. For a ``DERIVED`` proposal it cannot arise
    (ADR-0077 §5 already refused a citation resolving to nothing), but for an
    ``ASSERTED`` or ``EXTERNAL`` one the install would store a record whose evidence
    names itself and nothing else that exists — the same defect arriving with no
    destruction at all. Refusing it is what makes the rule statable without a store
    read rather than *in spite* of having none. The degenerate case where the record
    already at that id is itself self-citing is refused as well (ADR-0081 §1):
    distinguishing it would cost a ``get`` on every write-producing ingest to
    protect a state the rule says must not exist.

    Quantified over **the proposal's** evidence and **this write's** destination,
    not over the tuple :func:`_merge` unions (ADR-0081 §1a): a target that already
    cited itself is out of scope, since the fold neither creates that condition nor
    destroys anything, and testing the merged tuple would make such a record
    permanently unfoldable *and* make the refusal depend on state read from the
    store. Scoped to no band, unlike ADR-0077 §5's floor (§1b): a record citing
    nothing satisfies it trivially, while band-scoping would leave ``ASSERTED`` and
    ``EXTERNAL`` free to fabricate their own warrant.

    Args:
        decision: The ruling the policy made.
        proposal: The proposal as this call observed it.
        resolved: The conflict ids this ingest resolved — what makes a
            ``REINFORCE``'s ``target_id`` a destination rather than an invalid
            ruling (ADR-0081 §6).

    Raises:
        MemoryStoreError: If the ruling would install the proposal at an id the
            proposal cites. Nothing is written, no window is closed, and no
            decision is returned.
    """
    proposed = proposal.proposed
    destination = _installed_at(decision, proposed, resolved=resolved)
    if destination is not None and destination in proposed.provenance.evidence:
        msg = (
            f"refusing to write {proposed.id!r}: a {decision.kind} ruling would install it at "
            f"{destination!r}, an id its own provenance cites as evidence — the belief would "
            f"stand as its own warrant, and no citation a write consumes can be presented "
            f"honestly (ADR-0081 §1)"
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


def _retirement_set(
    target: MemoryRecord,
    conflicts: list[MemoryRecord],
    *,
    proposal: MemoryUpdateProposal,
    resolved: tuple[str, ...],
) -> list[MemoryRecord]:
    """The full set of conflicting beliefs a ``SUPERSEDE`` retires (ADR-0050 §1, #244).

    A ``SUPERSEDE`` names the *relation* — the proposal overturns the belief the
    conflict set holds — not a single record (ADR-0040 §1). Every entry in
    ``conflicts`` is a same-kind, at-or-above-threshold contradiction the proposal
    just displaced, so retiring only the policy's best-ranked ``target`` would leave
    a second and third stale belief on the same topic live: exactly the honesty gap
    issue #244 reports. The applier therefore closes the window of the target **and**
    of every other conflict it is *warranted* to retire.

    The set is the named ``target`` plus every other conflict whose source is in
    :data:`_RETIREMENT_CLASS` (``OBSERVED``/``INFERRED``/``EXTERNAL``) — the beliefs
    a correction is warranted to displace. **``EXTERNAL`` joined that class in
    ADR-0092 §4**, which discharges the adoption ADR-0045 §5/§7/§10 deferred and
    partially supersedes ADR-0050 §1's hold-out: the external calendar is an *input*
    and not the truth, so a user's correction retires the import rather than leaving
    it live beside them. The band is retirable on ADR-0038 §2's own error calculus,
    which turns on recoverability — an attested belief is not re-derivable by us and
    is **re-reportable by its source**, on a schedule, a recovery path at least as
    reliable as re-observation.

    One source stays held out of the *widening*, and only one:

    - ``USER_ASSERTED`` conflicts are never swept in **on similarity** — clause 1
      stands, record-keyed, for both rulings (ADR-0045 §5): topical similarity may
      not retire a record the user gave us. ``DefaultMemoryPolicy`` never even
      reaches ``SUPERSEDE`` with an asserted conflict present unless the user
      confirmed it (it rules ``ASK_USER``, ADR-0050 §2), but the applier excludes
      them regardless, since it takes rulings from any injected policy.

      **The one exception is the user's own answer** (ADR-0078 §5b's narrowing of
      ADR-0050 §1's hold-out): an asserted conflict the incoming proposal's
      ``confirmation`` genuinely covers *is* retired, so a confirmation naming two
      prior assertions retires both in the one atomic batch. It is verified per
      record through the same five checks the named target passes
      (:func:`_confirmation_covers`) rather than inferred from the target having
      passed them, because under an injected policy a confirmation can arrive with
      an *inference* named as the target while a live assertion sits in ``retires``
      — and the widening would then act on an authority nothing had checked.
      ``retires`` remains a **ceiling rather than an instruction**: naming an id
      does not retire it, it only bounds what may be. That rule stands untouched by
      ADR-0092 §4; what has gone is its second justification, since an ``EXTERNAL``
      id in ``retires`` no longer needs a confirmation's authority to be swept in —
      the class carries it, and a confirmation exists to authorise retiring an
      **assertion**.

    **This is not :data:`_REINFORCE_SAFE`, and the difference is load-bearing**
    (ADR-0092 §5). That set is still ``{OBSERVED, INFERRED}``, because the question
    it answers — may an assertion fold at *this record's* id — turns on the foreign
    idempotency key an ``EXTERNAL`` record carries, which widening the retirement
    class does not change.

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
        if conflict.id != target.id
        and (
            conflict.provenance.source in _RETIREMENT_CLASS
            or (
                conflict.provenance.source is MemorySource.USER_ASSERTED
                and _confirmation_covers(
                    conflict, proposal, MemoryDecisionKind.SUPERSEDE, resolved=resolved
                )
            )
        )
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


def _bounded_evidence(evidence: Sequence[str], *, elided: int) -> tuple[tuple[str, ...], int]:
    """ADR-0086 §3's retention rule and §4's recurrence, in one place.

    Keeps the **last** :data:`MAX_EVIDENCE_CITATIONS` entries — the tuple is
    ordered oldest-accumulated first, so the oldest are the ones displaced. Recency
    rather than "most reinforcing" because the union deduplicates by id, so every
    citation carries weight exactly one and there is no ranking to select on;
    meanwhile the oldest citations are precisely those likeliest to have expired
    already (ADR-0074 §7), and retaining them would spend a bounded budget on the
    residue and leave "why do you believe that?" unanswerable.

    Args:
        evidence: The citations the install would carry, oldest first.
        elided: The sum of ``evidence_elided`` over every record this install
            draws content from — two for a fold, one for every other ruling.

    Returns:
        The retained citations, and the elision count to store: ``elided`` plus
        the number this install displaced. Never an exact total of what the record
        no longer carries, and deliberately so (ADR-0086 §4).
    """
    displaced = max(len(evidence) - MAX_EVIDENCE_CITATIONS, 0)
    return tuple(evidence[displaced:]), elided + displaced


def _installed(record: MemoryRecord) -> MemoryRecord:
    """``record`` with its evidence brought under the bound (ADR-0086 §2).

    Applied at **every install** and at no retirement, which is the whole of the
    rule's scope. "Install" is ADR-0081 §1's sense, the one :func:`_installed_at`
    already implements: a write installs when it stores the proposal's content at
    an id. A retirement writes an *existing* record back with only its window
    narrowed (:func:`_close_window`), asserts nothing new about the warrant, and
    is therefore exempt — a legacy over-bound target is retired intact rather than
    truncated on its way *off* the read path, which would be the eager rewrite
    ADR-0077 §6 refused and the read-path failure ADR-0086 §2 exists to avoid.

    A no-op — the same object, not a copy — for anything already under the bound,
    which is every record any shipped producer authors and every fold
    :func:`_merge` has already bounded. Where it does bite it rebuilds
    :class:`Provenance` through ``model_validate`` rather than
    ``model_copy(update=...)``, so the type's own validators run on the value that
    is stored (ADR-0026 §2's hazard).
    """
    provenance = record.provenance
    retained, elided = _bounded_evidence(provenance.evidence, elided=provenance.evidence_elided)
    if elided == provenance.evidence_elided:
        return record
    bounded = Provenance.model_validate(
        provenance.model_dump() | {"evidence": retained, "evidence_elided": elided}
    )
    return record.model_copy(update={"provenance": bounded})


def _corroborates(target: MemoryRecord, incoming: MemoryRecord) -> bool:
    """Is this the fold ADR-0103 §6 rules — an ``ATTESTED`` target, a ``DERIVED`` proposal?

    **Keyed on both bands, and on neither record's confidence.** The clause reads
    "where a ``REINFORCE``'s target is in the ``ATTESTED`` band and its incoming
    record is in the ``DERIVED`` band", so it is the pairing that selects the arm,
    not the arithmetic — the same fold at ``0.7`` and at ``1.0`` folds the same
    way. Only the ``1.0`` case is #646's crash (the maximum lands a derived source
    at full confidence and ``Provenance._derived_is_never_certain`` refuses it,
    ADR-0077 §7); the rest is the trade ADR-0103 §6 names in terms — "where the
    derived incoming record's strength happens to exceed the attested target's,
    today's ``max`` would raise the survivor's number and this clause does not".
    A crash-keyed guard would have fixed the exception and left the rule the
    exception was a symptom of.

    **Naming ``ATTESTED`` on the target side keeps the rule inside the reachable
    set** (ADR-0103 §6). The wider "a ``DERIVED`` proposal onto any target" would
    sweep in the ``ASSERTED`` target, and nothing folds onto an assertion at all
    (:func:`_refuse_unsafe_fold` clause 1, ADR-0045 §5) — whatever a confirmation
    says, since :func:`_confirmation_covers` check 1 admits only a ``SUPERSEDE``,
    which retires rather than folds — so it would prescribe how to fold a fold
    that may not happen. The other pairings are left exactly as
    they stand: a ``USER_ASSERTED`` proposal is not in the ``DERIVED`` band, so the
    assertion still wins at 1.0; a ``DERIVED`` target reinforced by an ``EXTERNAL``
    record still folds to ``EXTERNAL`` at the maximum, which the ``ATTESTED`` band
    admits (ADR-0038 §2a) and §6's first clause therefore permits — the
    misattribution that leaves behind is filed as #733 and is deliberately not
    fixed here; and same-band folds are untouched.

    Args:
        target: The stored record the ruling folds into.
        incoming: The proposed record being folded in.

    Returns:
        Whether ADR-0103 §6's second clause governs this fold.
    """
    return (
        band_of(target.provenance.source) is BeliefBand.ATTESTED
        and band_of(incoming.provenance.source) is BeliefBand.DERIVED
    )


def _confirming_instant(
    target: Provenance, incoming: Provenance, *, now: datetime
) -> datetime | None:
    """The survivor's ``last_confirmed_at``: ADR-0103 §6's rule, ADR-0109 §5's shape.

    The later of the two records' **usable** confirming instants; the usable one
    where only one is usable; ``None`` where neither is. An instant is usable when
    it is not ``None`` and not in the writer's future at the moment of the fold —
    ``now`` is the ingestor's own injected, guarded clock, never a module-level
    wall clock, so the selection is deterministic under test (ADR-0109 §5).

    **The clock is what makes this the rule ADR-0103 §6 wrote rather than "the
    later present value".** #741's pair is the proof: an ``ATTESTED`` target whose
    ``reported_at`` is future-dated — stored unchanged, because ADR-0092 §3 does
    not refuse a source's clock skew — folded with a ``DERIVED`` record confirmed
    in January. Selecting the later *present* value takes the future one, and a
    read then reports *unknown* for a belief with a perfectly good January
    confirmation on the other side: the manufactured staleness ADR-0103 §6's
    unknown-does-not-spread paragraph and ADR-0103 §9's third constraint both
    refuse, reached at the fold. Selecting over usable values takes January.

    **Composed rather than inherited on both arms.** The ordinary arm's survivor is
    the incoming record wearing the target's id, so taking the incoming record's
    instant alone would move a belief's currency *backwards* whenever the target
    held the later confirmation — reachable with no producer doing anything
    unusual, a proposal citing a December episode reinforcing a belief confirmed in
    January. "A confirmation we *do* hold is not unmade" is ADR-0103 §6's own
    sentence about the unknown case and reads identically about the merely-older
    one.

    **The selection is made once, and a future instant that later becomes past is
    not promoted retroactively.** Nothing is lost by that: the target's
    ``attestation`` survives the fold under ADR-0103 §6, so the record still says
    what the source reported and when it claimed to be reporting it.

    Args:
        target: The stored record's provenance.
        incoming: The proposed record's provenance.
        now: The ingestor's clock reading, defining "our future" for this fold.

    Returns:
        The instant the survivor carries, or ``None`` for ADR-0103 §9's unknown.
    """
    usable = [
        instant
        for instant in (target.last_confirmed_at, incoming.last_confirmed_at)
        if instant is not None and instant <= now
    ]
    return max(usable, default=None)


def _merge(target: MemoryRecord, incoming: MemoryRecord, *, now: datetime) -> MemoryRecord:
    """Fold ``incoming`` into ``target``, keeping the target's id.

    Newer content wins; evidence is unioned and confidence taken as the maximum,
    so a merge strengthens rather than weakens what is known — **except** for the
    one pairing ADR-0103 §6 rules, where the incoming record corroborates rather
    than accumulates (:func:`_corroborates`, below).

    **Reinforcement only.** Both halves of that — the union and the maximum —
    assume the two records *agree*. Only a ``REINFORCE`` ruling reaches this
    function (ADR-0040 §3): a contradiction is a ``SUPERSEDE``, which
    :meth:`MemoryIngestor._apply` routes to :func:`_supersede` instead.

    **A derived record folded onto an attested one contributes its evidence and
    nothing else** (ADR-0103 §6). The survivor keeps the target's ``source``,
    ``attestation``, content and confidence; the evidence union and the
    transaction stamp move, and the confirming instant is **composed** from both
    sides rather than taken from either (ADR-0109 §5, below). Two rules that are
    each right on their own produced #646 between them — "take the maximum" is
    right about *evidence* and wrong
    about *what a derived source can warrant* — and the survivor was a
    ``Provenance`` ``core`` refuses, so the fold raised a ``ValidationError`` and
    nothing was written at all. Agreement between a derived observation and a
    better-warranted record is real information, but it is information about
    whether the belief still holds, not about how much warrant it has: the
    observation supplies no warrant the target did not already have. So the
    agreement is recorded where ADR-0103 §6 puts it — in the unioned evidence,
    which retains the episode the observation stands on — and not in a number that
    would claim the attested source said something it did not.

    **The whole target record survives, not only its provenance.** ADR-0103 §6
    gives the incoming record exactly two contributions, so its content, its
    ``validity`` window and its ``expires_at`` are all left behind with its
    confidence. Keeping the content is required rather than tidy: an
    ``attestation`` is present exactly when the band is ``ATTESTED`` (ADR-0092 §1),
    so a survivor that kept the target's attestation while carrying the incoming
    record's text would attribute to an external system words it never reported,
    and one that dropped the band to keep the text would drop the record of who
    reported the belief and when — a disclosure obligation (ADR-0073 §4), not a
    nicety.

    **``last_updated`` still comes from the incoming record on both arms, and that
    is not a third contribution.** It is transaction time — "the clock of the store
    changing its mind" (ADR-0045 §3, ADR-0103 §9) — and the store is changing its
    mind here, because the survivor's evidence is not the evidence the target was
    stored with. What ADR-0103 §6 withholds from the incoming record are the
    belief's own properties, which it enumerates; a stamp saying when *we* last
    revised the record is not one of them, and keeping the target's would claim a
    write that just happened never did.

    **Currency is composed here, on both arms, from the two records and the
    ingestor's clock** (ADR-0109 §5, §6). ADR-0103 §6's third contribution — the
    survivor's currency is measured from the later of the two records' *usable*
    confirming instants, from whichever one is usable where only one is, and as
    unknown only where neither is, never from the moment of the fold — is
    implementable now that the instant is stored on the record rather than resolved
    from the episodes (ADR-0109 §1). :func:`_confirming_instant` is that selection,
    and it reads two values this function already holds plus ``now``: no store
    read, so ADR-0081 §1's store-free, cannot-be-raced property is kept whole. It
    governs **every** ``REINFORCE``, in every band pairing — ADR-0103 §9's fourth
    clause says "whatever band that record came from", which is vacuous under
    ADR-0103 §6's pairing alone, and a same-band rule that withheld currency would
    age a belief re-observed every week exactly as fast as one nobody has seen
    since.

    **The citation bound can no longer displace the instant, which is why #744's
    finding has nowhere left to act.** Where the incoming record alone carries more
    than :data:`MAX_EVIDENCE_CITATIONS`, its own oldest-accumulated citations are
    displaced, and accumulation order is not ``occurred_at`` order — so the
    displaced one can be the episode carrying the latest instant, and
    ``evidence_elided`` retains a count and never an id (ADR-0086 §4), so that
    instant is not recoverable from the survivor's tuple. Under a *resolver* the
    survivor's currency would silently fall back to the latest retained citation. It
    does not here: both inputs to the selection were computed by their producers
    when the confirming events were in hand, which is **before** ADR-0086 §3's bound
    ever applied, so the instant stopped depending on the citation list at the
    moment the proposal was authored. The bound bites exactly as it always did —
    ADR-0103 §1's promise not to disturb ADR-0086's citation bound holds — and it
    now displaces citations and nothing else.

    **``derived_from_external`` is the disjunction of both sides, on both arms**
    (ADR-0106 §4). It joins ``confidence`` and ``evidence`` in the combining
    minority rather than the majority that takes ``incoming``'s value, and the
    asymmetry runs the wrong way for the majority style here: a new field written
    as ``incoming.provenance.derived_from_external`` would clear a tainted target
    the first time a clean proposal reinforced it, which is exactly the laundering
    the marker exists to stop. The direction that has to be exercised is therefore
    a **tainted target reinforced by an untainted incoming** — the opposite
    direction passes an implementation that merely copies the incoming field and
    proves nothing.

    The corroboration arm takes the disjunction too, and not the target's value
    alone. ADR-0103 §6 withholds the incoming record's *belief properties* from
    the survivor, and taint is not one of them: it is a fact about what warrant
    was received, and a warrant is never un-received. The survivor there is
    ``ATTESTED``, where ADR-0106 §2 says the field means nothing anyway — but
    writing the disjunction keeps one rule over both arms instead of two that can
    drift, and ADR-0106 §4's clause is stated over the fold rather than over
    either side.

    **The union is bounded here, before the ``Provenance`` is constructed**, so
    the constructor's validators run on the value that is stored — the surrounding
    ``model_copy(update=...)`` skips them (ADR-0026 §2). ADR-0040 §5a's "retains
    **both** records' evidence" holds up to :data:`MAX_EVIDENCE_CITATIONS` and is
    partially superseded beyond it (ADR-0086 §3, §11): the oldest are displaced and
    counted. The fold is the one install drawing from **two** sources, so both
    records' ``evidence_elided`` are summed — including when the union fits and
    nothing is displaced, since an incoming record carrying a count of its own
    would otherwise have that history dropped (ADR-0086 §4). Both arms union and
    bound identically; ADR-0103 §6 changes what the survivor *warrants*, never what
    it cites.

    **On the ordinary arm the ``attestation`` is the incoming one** (ADR-0092 §6),
    and this is required rather than optional: the ``Provenance`` below is built
    field by field, so ``Provenance``'s iff validator would raise on an attested
    fold that carried none. The rule follows that arm's own shape — ``source`` and
    ``last_updated`` already come from the incoming record because newer content
    wins, and the attestation describes the content that survived. It therefore
    never disagrees with the ``source`` beside it, including in the awkward case
    where one source's record is reinforced by another's report: the survivor
    honestly says who reported the text it now holds. **The corroboration arm keeps
    that property by keeping the target's attestation**, which is the same rule
    read against ADR-0103 §6's content ruling rather than a departure from it: the
    attestation still describes the content that survived and still agrees with the
    ``source`` beside it. Taking the incoming attestation there is not merely
    wrong but impossible — a ``DERIVED`` record carries none, and an ``EXTERNAL``
    survivor without one is refused by the same iff validator.

    Args:
        target: The stored record the ruling folds into.
        incoming: The proposed record being folded in.
        now: The writer's clock reading, which defines "our future" for
            :func:`_confirming_instant`'s usability test and for nothing else.
            Passed in rather than read here, so this function stays a pure
            function of its arguments and the caller keeps the clock guard that
            translates a bad reading into `memory`'s own error (ADR-0026 §4).

    Returns:
        The survivor: the target's record on ADR-0103 §6's arm, the incoming
        record wearing the target's id on the ordinary one.
    """
    union = tuple(dict.fromkeys([*target.provenance.evidence, *incoming.provenance.evidence]))
    evidence, elided = _bounded_evidence(
        union,
        elided=target.provenance.evidence_elided + incoming.provenance.evidence_elided,
    )
    # Selected once, before the arms: ADR-0109 §6 makes the rule identical on both,
    # and computing it in one place is what stops the two arms drifting.
    confirmed_at = _confirming_instant(target.provenance, incoming.provenance, now=now)
    # Likewise selected once, before the arms: ADR-0106 §4 states the rule over the
    # fold as a disjunction of both sides, so neither arm may read one side alone.
    tainted = target.provenance.derived_from_external or incoming.provenance.derived_from_external
    if _corroborates(target, incoming):
        corroborated = Provenance(
            source=target.provenance.source,
            confidence=target.provenance.confidence,
            evidence=evidence,
            evidence_elided=elided,
            last_updated=incoming.provenance.last_updated,
            attestation=target.provenance.attestation,
            derived_from_external=tainted,
            last_confirmed_at=confirmed_at,
        )
        return target.model_copy(update={"provenance": corroborated})
    provenance = Provenance(
        source=incoming.provenance.source,
        confidence=max(target.provenance.confidence, incoming.provenance.confidence),
        evidence=evidence,
        evidence_elided=elided,
        last_updated=incoming.provenance.last_updated,
        attestation=incoming.provenance.attestation,
        derived_from_external=tainted,
        last_confirmed_at=confirmed_at,
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

        **Five refusals precede or replace a ruling**, in the order they fire:

        1. **Unresolvable evidence** (ADR-0077 §5): a ``DERIVED`` proposal citing a
           record this store does not hold raises ``UnresolvedEvidenceError``
           naming every such id, before conflict detection and before the policy is
           asked (:meth:`_require_resolvable_evidence`).
        2. **Over the conflict ceiling** (ADR-0079 §1): detection surfacing more
           conflicts than :data:`_DEFAULT_CONFLICT_LIMIT` — whatever this ingestor
           was tuned to — raises ``MemoryStoreError`` with nothing written and no
           ruling sought (:meth:`_detect_conflicts`).
        3. **A secret-tier write** (ADR-0078 §5b check 0): once the policy has ruled
           and before any write is dispatched, a write-producing ruling on a
           ``DataTier.SECRET`` proposal raises ``MemoryStoreError``
           (:func:`_refuse_secret_write`). ``ASK_USER`` and ``REJECT`` return
           normally, which is what preserves the ordinary secret-tier path.
        4. **A write that consumes its own evidence** (ADR-0081 §1): at that same
           seam, a ruling that would *install* the proposal at an id the proposal's
           ``provenance.evidence`` names raises ``MemoryStoreError``
           (:func:`_refuse_self_consuming_write`) — ``ACCEPT`` and
           ``STORE_TEMPORARY`` at ``proposed.id``, ``REINFORCE`` at the ruling's
           ``target_id``, whether or not a record stands there and for every band.
           ``SUPERSEDE`` is decided at its *minted* id instead, inside
           :meth:`_apply_supersede`, where a hit re-mints rather than refusing (§4);
           its retirement-set writes retire rather than install and are never
           refused by this rule.
        5. **An unretirable window** (ADR-0080 §3): a ``SUPERSEDE`` whose retirement
           set holds a record whose window cannot be closed representably raises
           ``MemoryStoreError`` before the atomic batch (:func:`_close_window`).

        And one **refusal at the fold** (ADR-0045 §5, narrowed by ADR-0078 §5b): a
        fold onto a ``USER_ASSERTED`` target raises unless the proposal carries a
        confirmation that genuinely covers that target
        (:func:`_confirmation_covers`).

        Args:
            proposal: The memory update to rule on and persist.

        Returns:
            The policy's decision and the id written, if anything was written.

        Raises:
            UnresolvedEvidenceError: If a ``DERIVED`` proposal cites a record the
                store does not hold; nothing is written and the policy is not asked.
            MemoryStoreError: If detection surfaces more conflicts than this
                ingestor will resolve in one ingest, if a write-producing ruling
                landed on a ``DataTier.SECRET`` proposal, if a ruling would install
                the proposal at an id it cites, if a fold onto a ``USER_ASSERTED``
                target is not covered by a confirmation, if a retirement's window
                cannot be closed, or on any other store or applier failure.
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
        resolved = tuple(record.id for record in conflicts)
        # Shallow is right here: this copies the ingestor's *own* snapshot, whose
        # `proposed` no caller holds a reference to. `observed` is deliberately
        # **kept** rather than rebound: its `conflicts` are the frozen ids the
        # question was asked about, and ADR-0078 §5b check 4 recomputes the
        # `question_key` from exactly those — comparing against the live set below
        # would refuse every honest answer (ADR-0078 §7's "no asserted conflict
        # ever confirmable").
        ruled = observed.model_copy(update={"conflicts": resolved})
        decision = await self._policy.decide(ruled, conflicts=conflicts)
        # Check 0, between the ruling and the write dispatch (ADR-0078 §5b): it
        # gates every write-producing ruling and no ruling that writes nothing, so
        # it belongs neither inside `_refuse_unsafe_fold` (which `ACCEPT` never
        # reaches) nor at the top of `ingest` (which would break the ordinary
        # secret-tier path §1 preserves).
        _refuse_secret_write(decision, observed)
        # ADR-0081 §1, at the same seam and for the same structural reason: it is a
        # property of the *write*, so it belongs after the ruling that determines the
        # write set and before the dispatch that performs it. `SUPERSEDE`'s minted
        # destination does not exist yet and is tested in `_apply_supersede` (§2).
        _refuse_self_consuming_write(decision, observed, resolved=resolved)
        record_id = await self._apply(decision, observed, conflicts, resolved=resolved)
        # The resolved ids come back on **every** ruling (ADR-0078 §4). ADR-0028 §3
        # declined this and named the exact condition for revisiting — a consumer
        # that needs to *show* the user what a proposal contradicted — and a
        # deferred question is that consumer, at a higher stake than presentation:
        # the shown set is the bound on what an answer to the question authorises
        # (ADR-0078 §5). Nothing new is computed; the value the copy above already
        # carries across the policy seam now crosses the writer seam too, so a
        # coordinator can enqueue a question about the conflicts the policy actually
        # saw instead of re-deriving `_detect_conflicts` in `orchestration` (the
        # duplication ADR-0028 §4 deleted) or re-detecting at answer time, by which
        # point the set has moved and the user would have authorised something other
        # than what they were shown.
        return MemoryIngestResult(decision=decision, record_id=record_id, conflicts=resolved)

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
        proposal: MemoryUpdateProposal,
        conflicts: list[MemoryRecord],
        *,
        resolved: tuple[str, ...],
    ) -> str | None:
        proposed = proposal.proposed
        # Every arm below that *installs* passes its record through `_installed`
        # (ADR-0086 §2), which is what makes the bound a property of the seam
        # rather than of one ruling: a later ruling that installs cannot acquire an
        # unbounded write by forgetting to opt in. It is a no-op on a `_merge`
        # result, which has already applied the same rule to the union it formed.
        match decision.kind:
            case MemoryDecisionKind.ACCEPT:
                return await self._install(_installed(proposed))
            case MemoryDecisionKind.STORE_TEMPORARY:
                expires_at = self._expiry(decision.ttl)
                return await self._install(
                    _installed(proposed.model_copy(update={"expires_at": expires_at}))
                )
            case MemoryDecisionKind.REINFORCE | MemoryDecisionKind.SUPERSEDE:
                target = next((c for c in conflicts if c.id == decision.target_id), None)
                if target is None:
                    # A fold naming an absent target must fail loudly: silently
                    # storing the proposal as new would create the duplicate the
                    # fold was meant to prevent, while reporting success.
                    msg = f"fold target {decision.target_id!r} is not among the conflicts"
                    raise MemoryStoreError(msg)
                _refuse_unsafe_fold(target, proposal, decision.kind, resolved=resolved)
                # Past the refusal, the ruling names the relation, so the ingestor
                # no longer reads provenance to recover it (ADR-0040 §3): SUPERSEDE
                # retires the contradicted belief (window-close) and writes the
                # correction as a new record, REINFORCE folds the two at the target's
                # id.
                if decision.kind is MemoryDecisionKind.SUPERSEDE:
                    return await self._apply_supersede(
                        _retirement_set(target, conflicts, proposal=proposal, resolved=resolved),
                        proposed,
                    )
                # The clock reading is the fold's, taken here rather than inside
                # `_merge`: `_now_utc` translates a bad reading into this
                # subsystem's `MemoryStoreError` (ADR-0026 §4), and a module-level
                # helper has no error class to raise. It also keeps `_merge` a pure
                # function of its arguments, which is what makes ADR-0109 §5's
                # selection deterministic under test.
                return await self._fold(_installed(_merge(target, proposed, now=self._now_utc())))
            case _:  # REJECT, ASK_USER — nothing is written.
                return None

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

    async def _fold(self, record: MemoryRecord) -> str:
        """Write ``record`` at the fold target's id, declaring the overwrite.

        ADR-0108 §2's one deliberate upsert. A ``REINFORCE`` folds at the *target
        the ruling named* (:func:`_merge` keeps the target's id), so landing on a
        stored record is the decision rather than a collision — this is exactly the
        case ADR-0022 §4 protected when it defended the upsert, and it survives as
        something this caller **states** rather than something every write silently
        carries.

        It goes through ``write_atomic`` rather than ``add``, though ``add`` *is*
        the upsert verb, because a mode named at the call is a declaration and a
        method name is not: a write that can destroy a standing record then says so
        in a word a reader can grep for.

        Raises:
            MemoryStoreError: The store refused the write — including a cross-kind
                collision, ADR-0108 §4's backstop, which a ``REINFORCE`` cannot
                reach because its target came from a kind-filtered search. Nothing
                is written.
        """
        written = await self._store.write_atomic(
            [MemoryWrite(record=record, mode=MemoryWriteMode.UPSERT)]
        )
        return written[0]

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
        re-mints and retries, bounded by :data:`_MAX_SUPERSEDE_ATTEMPTS`. A minted id
        the **proposal cites** joins that same bounded loop (ADR-0081 §4): installing
        the correction there would leave it standing as its own warrant, reached
        without replacing anything, so the applier re-mints rather than refusing —
        a re-mint is free and always available. Any other
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
        # ADR-0081 §1's second evaluation point (§2, §4). `SUPERSEDE`'s destination
        # does not exist until it is minted, so its candidate is tested here — beside
        # the retained-target test and before the batch is assembled — rather than at
        # the seam the three other installing rulings are decided at. Quantified over
        # *this proposal's* evidence, which `_supersede` carries onto the correction
        # unchanged.
        cited = frozenset(proposed.provenance.evidence)
        last_conflict: MemoryStoreConflictError | None = None
        for _ in range(_MAX_SUPERSEDE_ATTEMPTS):
            new_id = _checked_id(self._id_factory, owner="MemoryIngestor")
            if new_id in cited:
                # A minted id the proposal cites would leave the correction standing
                # as its own warrant — ADR-0081 §1's defect reached without replacing
                # anything, since `INSERT_IF_ABSENT` overwrites nothing. It **re-mints**
                # rather than refusing, because a re-mint is free and always available,
                # which is exactly why the retained-target collision below is handled
                # that way. For a `DERIVED` proposal this is belt to ADR-0077 §5's
                # braces (a cited record that resolves is stored, so the insert would
                # already conflict and re-mint); it does real work for the `ASSERTED`
                # and `EXTERNAL` bands §5 does not check, where the cited id may name
                # nothing and the insert would succeed.
                last_conflict = MemoryStoreConflictError(
                    f"minted id {new_id!r} is cited by the proposal's own evidence; re-minting"
                )
                continue
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
            # The retirements are **not** bounded: `_close_window` writes an
            # existing record back with only its window narrowed, which ADR-0081 §1
            # calls a retirement rather than an install, so a legacy over-bound
            # target goes back with its tuple and its count untouched (ADR-0086 §2).
            # The correction *is* an install, and carries the proposal's own count
            # — never the target's, which ADR-0040 §5a keeps off the record that
            # overturns it (ADR-0086 §4).
            batch = [
                MemoryWrite(record=closed_target, mode=MemoryWriteMode.UPSERT)
                for closed_target in closed
            ]
            batch.append(
                MemoryWrite(
                    record=_installed(_supersede(proposed, new_id)),
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
