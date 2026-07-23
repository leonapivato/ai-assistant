"""Tests for the memory ingestor (conflict detection + policy + application)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta, timezone, tzinfo
from typing import TYPE_CHECKING

import pytest

from ai_assistant.core.errors import MemoryStoreError
from ai_assistant.core.types import (
    DataTier,
    MemoryDecision,
    MemoryDecisionKind,
    MemoryRecord,
    MemorySource,
    MemoryUpdateProposal,
    PreferenceMemory,
    Provenance,
    SemanticMemory,
    Validity,
)
from ai_assistant.memory import (
    DefaultMemoryPolicy,
    InMemoryMemoryStore,
    MemoryIngestor,
    SqliteMemoryStore,
)
from ai_assistant.models import HashingEmbedder

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from ai_assistant.core.protocols import MemoryStore
    from ai_assistant.core.types import MemoryIngestResult, MemoryKind

_WHEN = datetime(2026, 1, 1, tzinfo=UTC)


def _fixed_now() -> datetime:
    return datetime(2026, 6, 1, tzinfo=UTC)


def _prov(
    confidence: float,
    evidence: tuple[str, ...] = (),
    *,
    source: MemorySource = MemorySource.OBSERVED,
) -> Provenance:
    return Provenance(
        source=source,
        confidence=confidence,
        last_updated=_WHEN,
        evidence=list(evidence),
    )


def _semantic(record_id: str, content: str, *, confidence: float = 0.6) -> MemoryRecord:
    return SemanticMemory(id=record_id, content=content, fact=content, provenance=_prov(confidence))


def _preference(
    record_id: str,
    content: str,
    *,
    confidence: float = 0.6,
    evidence: tuple[str, ...] = (),
    source: MemorySource = MemorySource.OBSERVED,
) -> MemoryRecord:
    return PreferenceMemory(
        id=record_id,
        content=content,
        preference=content,
        provenance=_prov(confidence, evidence, source=source),
    )


def _semantic_from(source: MemorySource, record_id: str, content: str) -> MemoryRecord:
    """A semantic record from ``source``, at the confidence that source permits."""
    confidence = 1.0 if source is MemorySource.USER_ASSERTED else 0.6
    return SemanticMemory(
        id=record_id,
        content=content,
        fact=content,
        provenance=_prov(confidence, source=source),
    )


def _asserted(record_id: str, content: str, *, evidence: tuple[str, ...] = ()) -> MemoryRecord:
    """A user-asserted preference — the shape an explicit correction arrives in."""
    return _preference(
        record_id,
        content,
        confidence=1.0,
        evidence=evidence,
        source=MemorySource.USER_ASSERTED,
    )


def _proposal(
    record: MemoryRecord, *, sensitivity: DataTier = DataTier.PERSONAL
) -> MemoryUpdateProposal:
    return MemoryUpdateProposal(proposed=record, rationale="because", sensitivity=sensitivity)


def _ingestor(store: MemoryStore) -> MemoryIngestor:
    return MemoryIngestor(store=store, policy=DefaultMemoryPolicy(), now=_fixed_now)


async def test_accepts_and_stores_a_novel_memory() -> None:
    store = InMemoryMemoryStore()

    result = await _ingestor(store).ingest(
        _proposal(_semantic("1", "unique gardening fact", confidence=0.9))
    )

    assert result.decision.kind is MemoryDecisionKind.ACCEPT
    assert result.record_id == "1"
    assert await store.get("1") is not None


async def test_secret_proposal_is_deferred_and_not_stored() -> None:
    store = InMemoryMemoryStore()

    result = await _ingestor(store).ingest(
        _proposal(_semantic("1", "a secret", confidence=0.9), sensitivity=DataTier.SECRET)
    )

    assert result.decision.kind is MemoryDecisionKind.ASK_USER
    assert result.record_id is None
    assert await store.get("1") is None


async def test_conflicting_proposal_merges_into_existing() -> None:
    store = InMemoryMemoryStore()
    await store.add(_preference("e", "prefers concise emails", confidence=0.5, evidence=("ev1",)))

    result = await _ingestor(store).ingest(
        _proposal(_preference("new", "prefers concise emails", confidence=0.7, evidence=("ev2",)))
    )

    assert result.decision.kind is MemoryDecisionKind.REINFORCE
    assert result.record_id == "e"
    merged = await store.get("e")
    assert merged is not None
    assert merged.provenance.confidence == 0.7  # max of the two
    assert set(merged.provenance.evidence) == {"ev1", "ev2"}
    assert await store.get("new") is None  # merged in place, not duplicated


async def test_user_assertion_supersedes_the_inference_it_contradicts() -> None:
    # The unlearning path (issue #38, ADR-0038), now non-destructive (ADR-0045
    # §4): a correction takes the stale belief off the read path by closing its
    # window and lands as a *new* record at a freshly-minted id — the stale
    # inference is retained on disk, not overwritten. Asserted end to end because
    # "the wrong memory is still retrievable" is a property of the store.
    store = InMemoryMemoryStore()
    await store.add(
        _preference("stale", "user prefers morning meetings", confidence=0.6, evidence=("ev1",))
    )

    result = await _ingestor(store).ingest(
        _proposal(_asserted("correction", "user prefers afternoon meetings", evidence=("ev2",)))
    )

    assert result.decision.kind is MemoryDecisionKind.SUPERSEDE
    # The live belief is a NEW record at a minted id — neither the target's id nor
    # the proposal's own (ADR-0045 §4).
    new_id = result.record_id
    assert new_id is not None
    assert new_id not in {"stale", "correction"}
    # The stale inference is retired: off the read path (get), still on disk.
    assert await store.get("stale") is None
    correction = await store.get(new_id)
    assert correction is not None
    assert correction.content == "user prefers afternoon meetings"
    assert correction.provenance.source is MemorySource.USER_ASSERTED
    assert correction.provenance.confidence == 1.0
    # ADR-0038 §1a: the overturned belief's evidence must NOT follow it across.
    # `ev1` is what made us think "morning"; presenting it as support for
    # "afternoon" would be a fabricated warrant in the field ADR-0005 §2 defines
    # as references *supporting* the record. A user's assertion is its own warrant.
    assert set(correction.provenance.evidence) == {"ev2"}
    # The proposal's own id is discarded, not written at.
    assert await store.get("correction") is None
    # Both records are retained: the retired inference and the live correction.
    exported = {record.id: record for record in await store.export()}
    assert set(exported) == {"stale", new_id}
    # The retired target carries a closed window (present in export, hidden from get).
    assert exported["stale"].validity.valid_until is not None


@pytest.mark.parametrize("backend", ["in-memory", "sqlite"])
async def test_a_superseded_targets_hiding_is_read_time_relative(
    backend: str, tmp_path: Path
) -> None:
    # The retirement guarantee is *read-time-relative*, not absolute — exactly like
    # `expires_at` (ADR-0007) and ADR-0045 §6's own read filter. `_close_window`
    # stamps `valid_until` from the *ingestor's* clock (ADR-0045 §4); `get`/`search`
    # hide the target once the *store's* read clock reaches that instant. In
    # production the store and ingestor each independently sample the real wall clock
    # (neither is given a `now`), so a read after the write samples at/after the close
    # — provided the wall clock advances forward — and it is hidden; a store clock
    # that samples *behind* the close (a test clock, or the wall clock stepping back)
    # transiently still returns it. That transient visibility is a property of
    # read-time filtering, not a bug — documented here, not "fixed". An absolute,
    # clock-coherence-independent guarantee (a store-authoritative retirement instant)
    # is a MemoryStore contract change deferred to issue #306. Run over SQLite too,
    # where the hide rides the `valid_until` pre-filter column the batch UPSERT must
    # write alongside the JSON blob (ADR-0045 §9), not only the in-memory dict.
    read_at = [datetime(2026, 1, 1, tzinfo=UTC)]  # store read clock, mutable; starts BEHIND close
    store: MemoryStore
    if backend == "in-memory":
        store = InMemoryMemoryStore(now=lambda: read_at[0])
    else:
        store = SqliteMemoryStore(
            path=tmp_path / "memory.db",
            embedder=HashingEmbedder(dimensions=32),
            now=lambda: read_at[0],
        )
    try:
        # Open-window target, so it is a live conflict at any read clock. Identical
        # content to the correction so both the lexical and vector detectors find it.
        await store.add(_preference("stale", "user prefers morning meetings", confidence=0.6))

        # The ingestor's clock (`_fixed_now`, 2026-06-01) is the close instant.
        result = await _ingestor(store).ingest(
            _proposal(_asserted("correction", "user prefers morning meetings"))
        )
        assert result.decision.kind is MemoryDecisionKind.SUPERSEDE
        new_id = result.record_id
        assert new_id is not None

        # Read BEHIND the close (store clock 2026-01-01 < valid_until 2026-06-01): the
        # retired target is transiently still visible — the read-time-relative property.
        assert await store.get("stale") is not None
        assert any(r.id == "stale" for r in await store.search("user prefers morning meetings"))

        # Advance the store's read clock to the close instant: now hidden from
        # get/search (the half-open window makes `valid_until` itself exclusive).
        read_at[0] = datetime(2026, 6, 1, tzinfo=UTC)
        assert await store.get("stale") is None
        assert all(r.id != "stale" for r in await store.search("user prefers morning meetings"))

        # `export` keeps the retired target unconditionally, at either read clock.
        assert {r.id for r in await store.export()} == {"stale", new_id}
    finally:
        if isinstance(store, SqliteMemoryStore):
            store.close()


async def test_superseding_a_target_never_extends_its_existing_window() -> None:
    # Retirement takes a belief *off* the read path — it never resurrects one.
    # A target that already self-closes *before* the ingestor's clock keeps that
    # earlier end (`_close_window` takes the min), so a supersession cannot push a
    # self-closed belief back onto the read path for [existing-end, now). No invalid
    # interval or clock skew is needed — just a producer-set `valid_until` earlier
    # than the writer clock, with the store reading before it so it is a live
    # conflict. The full question of producer-settable windows is deferred to #306.
    already_closes = datetime(2026, 3, 1, tzinfo=UTC)  # before the ingestor's 2026-06-01 clock
    store = InMemoryMemoryStore(now=lambda: datetime(2026, 2, 1, tzinfo=UTC))
    await store.add(
        PreferenceMemory(
            id="stale",
            content="user prefers morning meetings",
            preference="morning",
            validity=Validity(valid_until=already_closes),
            provenance=_prov(0.6, source=MemorySource.INFERRED),
        )
    )

    result = await _ingestor(store).ingest(
        _proposal(_asserted("correction", "user prefers morning meetings"))
    )

    assert result.decision.kind is MemoryDecisionKind.SUPERSEDE
    retired = next(record for record in await store.export() if record.id == "stale")
    # Kept at its earlier self-close, not extended out to the writer's 2026-06-01 clock.
    assert retired.validity.valid_until == already_closes


@pytest.mark.parametrize("backend", ["in-memory", "sqlite"])
async def test_superseding_a_future_dated_target_refuses_without_corrupting(
    backend: str, tmp_path: Path
) -> None:
    # The data-integrity floor in `_close_window`: a producer-set `valid_from` at or
    # after the ingestor's clock would, closed at `now`, form an empty/inverted
    # window that `SqliteMemoryStore`'s decode re-validation rejects — corrupting
    # reads. The applier refuses before `write_atomic`, so *neither* backend
    # persists it. Run over both because the corruption is backend-specific; the
    # full retirement semantics for such a target is deferred to issue #306. The
    # target is a live conflict at the store's 2026-10-01 clock but its window would
    # invert against the ingestor's 2026-06-01 clock. Identical content makes it a
    # conflict under both the lexical (in-memory) and vector (SQLite) detectors.
    store: MemoryStore
    if backend == "in-memory":
        store = InMemoryMemoryStore(now=lambda: datetime(2026, 10, 1, tzinfo=UTC))
    else:
        store = SqliteMemoryStore(
            path=tmp_path / "memory.db",
            embedder=HashingEmbedder(dimensions=32),
            now=lambda: datetime(2026, 10, 1, tzinfo=UTC),
        )
    try:
        await store.add(
            PreferenceMemory(
                id="future",
                content="user prefers morning meetings",
                preference="morning",
                validity=Validity(valid_from=datetime(2026, 9, 1, tzinfo=UTC)),
                provenance=_prov(0.6, source=MemorySource.INFERRED),
            )
        )

        with pytest.raises(MemoryStoreError, match="valid_from"):
            await _ingestor(store).ingest(
                _proposal(_asserted("correction", "user prefers morning meetings"))
            )

        # No corrupt state: the store still reads cleanly (a corrupt SQLite row would
        # make `export`/`get` raise a decode error) and the target is intact.
        survivor = await store.get("future")
        assert survivor is not None
        assert survivor.validity.valid_until is None
        assert [record.id for record in await store.export()] == ["future"]
    finally:
        if isinstance(store, SqliteMemoryStore):
            store.close()


async def test_a_correction_survives_the_next_external_re_sync() -> None:
    # The regression ADR-0038 §2a exists to prevent, asserted end to end because
    # the hole is in the interaction, not in either half. ADR-0045 §7 lifts the
    # *writer-floor* refusal of an EXTERNAL supersession, but the shipped
    # `DefaultMemoryPolicy` still does not rule SUPERSEDE over an EXTERNAL conflict
    # (`_SUPERSEDABLE` stays {OBSERVED, INFERRED}, ADR-0040 §6): it ACCEPTs the
    # correction *beside* the imported record, at the correction's own id. The
    # next sync re-adds `calendar:1` (its idempotency key), which cannot touch the
    # correction stored under a different id — so the user's words survive.
    store = InMemoryMemoryStore()
    ingestor = _ingestor(store)
    await store.add(
        _preference(
            "calendar:1",
            "user works from the london office",
            confidence=1.0,
            source=MemorySource.EXTERNAL,
        )
    )

    await ingestor.ingest(_proposal(_asserted("new", "user works from the berlin office")))
    await ingestor.ingest(
        _proposal(
            _preference(
                "calendar:1",
                "user works from the london office",
                confidence=1.0,
                source=MemorySource.EXTERNAL,
            )
        )
    )

    correction = await store.get("new")
    assert correction is not None
    assert correction.content == "user works from the berlin office"
    assert correction.provenance.source is MemorySource.USER_ASSERTED
    # ADR-0038 §2a accepts the correction *beside* the imported record, so the
    # external record must still be intact — an implementation that clobbered
    # `calendar:1` while sparing `new` would otherwise satisfy the assertions
    # above and still be wrong.
    imported = await store.get("calendar:1")
    assert imported is not None
    assert imported.content == "user works from the london office"
    assert imported.provenance.source is MemorySource.EXTERNAL


# --- The default policy supersedes ------------------------------------------
#
# ADR-0040 removed ADR-0038 §1b's precondition: the ruling now names the
# relation, so `MemoryIngestor` no longer infers it from provenance and the
# scan-based guard that enumerated the shipped policies has nothing left to
# guard. What survives is the behavioural pin below — the default policy really
# does rule SUPERSEDE for an assertion over a derived conflict (ADR-0038 §1).


async def test_the_default_policy_actually_supersedes() -> None:
    # ADR-0038 §1 requires the default policy to supersede a conflicting
    # inference under an assertion; ADR-0040 §4 makes it say so with the
    # SUPERSEDE ruling rather than a MERGE the ingestor had to interpret.
    decision = await DefaultMemoryPolicy().decide(
        _proposal(_semantic_from(MemorySource.USER_ASSERTED, "new", "afternoon")),
        conflicts=[_semantic_from(MemorySource.INFERRED, "stale", "morning")],
    )

    assert decision.kind is MemoryDecisionKind.SUPERSEDE
    assert decision.target_id == "stale"


class _MergeEverythingPolicy:
    """A conforming ``MemoryPolicy`` that folds every proposal into the first conflict.

    Returns ``REINFORCE`` regardless of the records' relation — a conforming
    ruling (the ``MemoryPolicy`` contract does not constrain which relation a
    policy picks), and the case ADR-0040 §3 keeps ``_refuse_unsafe_fold`` keyed
    on the records for: the refusal must fire whatever the policy claims.
    """

    async def decide(
        self,
        proposal: MemoryUpdateProposal,
        *,
        conflicts: Sequence[MemoryRecord],
    ) -> MemoryDecision:
        """Fold into the first conflict, or accept when there is none."""
        if not conflicts:
            return MemoryDecision(kind=MemoryDecisionKind.ACCEPT, reason="nothing to fold into")
        return MemoryDecision(
            kind=MemoryDecisionKind.REINFORCE,
            target_id=conflicts[0].id,
            reason="folds everything",
        )


async def test_the_ingestor_refuses_to_fold_an_assertion_onto_an_external_record() -> None:
    # ADR-0038 §2a is a safety property, so it cannot rest on the policy alone:
    # a policy arrives through an injected seam and any conforming one may rule
    # differently. Every fold keeps the target's id, so allowing this would hand
    # the correction the integrating system's idempotency key and let the next
    # sync overwrite it. The ingestor refuses rather than silently downgrading
    # to a reinforcing merge, which would lose the correction just as thoroughly
    # while reporting success.
    store = InMemoryMemoryStore()
    await store.add(
        _preference(
            "calendar:1",
            "user works from the london office",
            confidence=1.0,
            source=MemorySource.EXTERNAL,
        )
    )
    ingestor = MemoryIngestor(store=store, policy=_MergeEverythingPolicy(), now=_fixed_now)

    with pytest.raises(MemoryStoreError, match="refusing to reinforce"):
        await ingestor.ingest(_proposal(_asserted("new", "user works from the berlin office")))

    # Fail-closed: the imported record is untouched and nothing was written.
    imported = await store.get("calendar:1")
    assert imported is not None
    assert imported.content == "user works from the london office"
    assert imported.provenance.source is MemorySource.EXTERNAL
    assert await store.get("new") is None


async def test_the_ingestor_refuses_to_fold_an_assertion_onto_another_assertion() -> None:
    # The other disallowed target, and the one that slips through most easily:
    # this is not a supersession, so a refusal gated on "is this a supersession?"
    # would let it fall into the reinforcing merge — which keeps the target's id
    # and destroys the earlier assertion just as thoroughly. ADR-0038 §3 and §5:
    # no conflict heuristic is confident enough to choose between two things the
    # user said.
    store = InMemoryMemoryStore()
    await store.add(_asserted("said-before", "user prefers morning meetings"))
    ingestor = MemoryIngestor(store=store, policy=_MergeEverythingPolicy(), now=_fixed_now)

    with pytest.raises(MemoryStoreError, match="refusing to fold onto"):
        await ingestor.ingest(_proposal(_asserted("says-now", "user prefers afternoon meetings")))

    earlier = await store.get("said-before")
    assert earlier is not None
    assert earlier.content == "user prefers morning meetings"
    assert await store.get("says-now") is None


@pytest.mark.parametrize(
    "source", [MemorySource.OBSERVED, MemorySource.INFERRED, MemorySource.EXTERNAL]
)
async def test_the_ingestor_refuses_to_fold_a_non_assertion_onto_an_assertion(
    source: MemorySource,
) -> None:
    # ADR-0038 §3 in the direction it is usually read: nothing we were not told
    # may supersede what we were. `DefaultMemoryPolicy` defers here (rule 2), but
    # that is a policy choice and the invariant has to hold for any injected
    # policy — a reinforcing merge would replace the assertion's content *and*
    # downgrade its provenance out of the profile.
    store = InMemoryMemoryStore()
    await store.add(_asserted("their-words", "user prefers morning meetings"))
    ingestor = MemoryIngestor(store=store, policy=_MergeEverythingPolicy(), now=_fixed_now)

    with pytest.raises(MemoryStoreError, match="refusing to fold onto"):
        await ingestor.ingest(
            _proposal(_preference("guess", "user prefers afternoon meetings", source=source))
        )

    theirs = await store.get("their-words")
    assert theirs is not None
    assert theirs.content == "user prefers morning meetings"
    assert theirs.provenance.source is MemorySource.USER_ASSERTED
    assert await store.get("guess") is None


async def test_a_reinforce_of_an_assertion_onto_a_derived_record_keeps_its_evidence() -> None:
    # The recoverable case ADR-0040 exists for. Before it, `MemoryIngestor` read
    # any assertion folded onto a derived record as *supersession* and discarded
    # the target's evidence — a precondition (ADR-0038 §1b) the ingestor could
    # not verify. Now the ruling names the relation: a policy that means
    # reinforcement says REINFORCE, and the target's evidence survives the fold.
    store = InMemoryMemoryStore()
    await store.add(
        _preference(
            "derived",
            "user prefers morning meetings",
            confidence=0.6,
            evidence=("obs1",),
            source=MemorySource.INFERRED,
        )
    )
    # `_MergeEverythingPolicy` rules REINFORCE for the assertion; INFERRED is
    # supersedable, so `_refuse_unsafe_fold` permits the fold.
    ingestor = MemoryIngestor(store=store, policy=_MergeEverythingPolicy(), now=_fixed_now)

    result = await ingestor.ingest(
        _proposal(_asserted("correction", "user prefers afternoon meetings", evidence=("ev2",)))
    )

    assert result.decision.kind is MemoryDecisionKind.REINFORCE
    assert result.record_id == "derived"
    reinforced = await store.get("derived")
    assert reinforced is not None
    # Both records' evidence is retained (ADR-0040 §5a) — the derived record's
    # audit trail is no longer thrown away.
    assert set(reinforced.provenance.evidence) == {"obs1", "ev2"}
    assert await store.get("correction") is None


class _RecordingPolicy:
    """A policy that records the conflicts it was offered and rejects everything."""

    def __init__(self) -> None:
        self.conflicts: list[list[str]] = []

    async def decide(
        self,
        proposal: MemoryUpdateProposal,
        *,
        conflicts: Sequence[MemoryRecord],
    ) -> MemoryDecision:
        self.conflicts.append([record.id for record in conflicts])
        return MemoryDecision(kind=MemoryDecisionKind.REJECT, reason="test recording")


async def test_proposal_itself_does_not_consume_a_conflict_slot() -> None:
    """Excluding the proposal must not cost a slot the limit already spent (#110).

    The store applies ``conflict_limit`` before the ingestor can drop the
    proposal's own record, so at ``conflict_limit=1`` a re-proposal used to leave
    the policy seeing no conflict at all — while a genuine one sat just below it.
    """
    store = InMemoryMemoryStore()
    # Added self-first so the equally-scoring pair ranks it above the rival: the
    # exact order in which the old code discarded the only slot it fetched.
    await store.add(_preference("self", "prefers concise emails"))
    await store.add(_preference("rival", "prefers concise emails"))
    policy = _RecordingPolicy()
    ingestor = MemoryIngestor(store=store, policy=policy, conflict_limit=1, now=_fixed_now)

    await ingestor.ingest(_proposal(_preference("self", "prefers concise emails")))

    assert policy.conflicts == [["rival"]]


async def test_conflicts_offered_never_exceed_the_limit() -> None:
    """Over-fetching to make room for the exclusion must not widen the limit."""
    store = InMemoryMemoryStore()
    for index in range(3):
        await store.add(_preference(f"existing-{index}", "prefers concise emails"))
    policy = _RecordingPolicy()
    ingestor = MemoryIngestor(store=store, policy=policy, conflict_limit=2, now=_fixed_now)

    await ingestor.ingest(_proposal(_preference("new", "prefers concise emails")))

    assert policy.conflicts == [["existing-0", "existing-1"]]


class _MergeToAbsentTargetPolicy:
    """A policy that always asks to fold into a record that isn't a conflict."""

    async def decide(
        self,
        proposal: MemoryUpdateProposal,
        *,
        conflicts: Sequence[MemoryRecord],
    ) -> MemoryDecision:
        return MemoryDecision(
            kind=MemoryDecisionKind.REINFORCE, target_id="ghost", reason="test misdirection"
        )


async def test_merge_into_absent_target_raises_and_stores_nothing() -> None:
    store = InMemoryMemoryStore()
    ingestor = MemoryIngestor(store=store, policy=_MergeToAbsentTargetPolicy(), now=_fixed_now)

    with pytest.raises(MemoryStoreError, match="not among the conflicts"):
        await ingestor.ingest(_proposal(_semantic("1", "some fact", confidence=0.9)))

    assert await store.get("1") is None  # nothing was silently stored as new


class _MaxTtlPolicy:
    """A policy whose STORE_TEMPORARY ttl overflows the representable date range."""

    async def decide(
        self,
        proposal: MemoryUpdateProposal,
        *,
        conflicts: Sequence[MemoryRecord],
    ) -> MemoryDecision:
        return MemoryDecision(
            kind=MemoryDecisionKind.STORE_TEMPORARY, ttl=timedelta.max, reason="test overflow"
        )


async def test_overflowing_temporary_ttl_raises_and_stores_nothing() -> None:
    store = InMemoryMemoryStore()
    ingestor = MemoryIngestor(store=store, policy=_MaxTtlPolicy(), now=_fixed_now)

    with pytest.raises(MemoryStoreError, match="overflows"):
        await ingestor.ingest(_proposal(_semantic("1", "some fact", confidence=0.9)))

    assert await store.get("1") is None


async def test_low_confidence_is_stored_temporarily_with_expiry() -> None:
    # The store shares the ingestor's fixed clock, so the just-stamped expiry
    # (a week out) is still in the future and the record remains retrievable.
    store = InMemoryMemoryStore(now=_fixed_now)

    result = await _ingestor(store).ingest(_proposal(_semantic("1", "weak signal", confidence=0.1)))

    assert result.decision.kind is MemoryDecisionKind.STORE_TEMPORARY
    stored = await store.get("1")
    assert stored is not None
    # _fixed_now (2026-06-01) + the policy's 7-day TTL.
    assert stored.expires_at == datetime(2026, 6, 8, tzinfo=UTC)


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"conflict_limit": 0}, "conflict_limit must be at least 1"),
        ({"conflict_limit": -1}, "conflict_limit must be at least 1"),
        ({"conflict_threshold": float("nan")}, "finite value in"),
        ({"conflict_threshold": 1.5}, "finite value in"),
        ({"conflict_threshold": -0.1}, "finite value in"),
    ],
)
def test_tuning_that_would_silently_disable_a_stage_is_refused(
    kwargs: dict[str, float], match: str
) -> None:
    """Relocated from ``LearningLoop`` with the values it guards (ADR-0028 §4a).

    ADR-0022 §4a's guarantee is moved, not retired: ``conflict_limit=0`` hands
    the policy no conflicts, so a duplicate is accepted while the caller reports
    a healthy write, and a ``NaN`` threshold compares ``False`` against every
    score and does the same. Refused at construction, by the object that now
    reads them.
    """
    with pytest.raises(ValueError, match=match):
        MemoryIngestor(
            store=InMemoryMemoryStore(),
            policy=DefaultMemoryPolicy(),
            now=_fixed_now,
            **kwargs,  # type: ignore[arg-type]  # deliberately invalid tuning
        )


@pytest.mark.parametrize(("threshold", "limit"), [(0.0, 1), (1.0, 1)])
async def test_tuning_accepts_the_boundary_values(threshold: float, limit: int) -> None:
    """0 and 1 bound the score range, and 1 is the smallest useful limit."""
    store = InMemoryMemoryStore()
    ingestor = MemoryIngestor(
        store=store,
        policy=DefaultMemoryPolicy(),
        conflict_threshold=threshold,
        conflict_limit=limit,
        now=_fixed_now,
    )

    result = await ingestor.ingest(_proposal(_semantic("1", "unique fact", confidence=0.9)))

    assert result.record_id == "1"


@pytest.mark.parametrize("limit", [1.5, float("inf"), True, "5"])
def test_tuning_refuses_a_conflict_limit_that_is_not_an_integer(limit: object) -> None:
    """A non-integral limit reaches ``MemoryStore.search``, where slicing raises."""
    with pytest.raises(TypeError, match="must be an integer"):
        MemoryIngestor(
            store=InMemoryMemoryStore(),
            policy=DefaultMemoryPolicy(),
            conflict_limit=limit,  # type: ignore[arg-type]  # deliberately invalid tuning
            now=_fixed_now,
        )


@pytest.mark.parametrize("threshold", [True, False])
def test_tuning_refuses_a_boolean_threshold(threshold: bool) -> None:
    """A flag is not a threshold, just as it is not a count (#111).

    ``bool`` is an ``int`` subclass, so both values clear the finite-and-in-range
    test and are read silently as ``1.0`` and ``0.0``. ``True`` is the one that
    bites — it restricts conflicts to perfect-score matches while looking like
    deliberate tuning.
    """
    with pytest.raises(TypeError, match="must be a real number"):
        MemoryIngestor(
            store=InMemoryMemoryStore(),
            policy=DefaultMemoryPolicy(),
            # No `type: ignore` needed, and that is the point: `bool` is a
            # `float` to the type checker, so nothing but this runtime check
            # stands between a flag and the threshold it would be read as.
            conflict_threshold=threshold,
            now=_fixed_now,
        )


async def test_a_naive_clock_cannot_leak_a_naive_expiry() -> None:
    """``_expiry`` installs ``expires_at`` through ``model_copy``, which skips
    validators — so the clock is the only place this can be caught.

    Inverted by ADR-0026: the ADR-0023 §6 shim that stood here attributed UTC to
    a naive reading. ``checked_clock`` refuses it instead, which is the trade
    ADR-0023 §3 takes at the producer — a silent fabrication becomes a loud
    failure naming the seam.
    """
    store = InMemoryMemoryStore(now=_fixed_now)
    naive_clock = MemoryIngestor(
        store=store,
        policy=DefaultMemoryPolicy(),
        now=lambda: datetime(2026, 6, 1),  # noqa: DTZ001 — the naive clock is the subject
    )

    with pytest.raises(MemoryStoreError, match="MemoryIngestor"):
        await naive_clock.ingest(_proposal(_semantic("1", "weak signal", confidence=0.1)))

    assert await store.get("1") is None


async def test_a_non_utc_clock_is_converted_not_merely_accepted() -> None:
    """The write skips the validator, so §2's UTC storage has to happen here.

    Asserted on ``tzinfo``, not only on the instant: an equality check alone
    passes for a ``+02:00`` value, which is exactly the state ADR-0023 §2's
    "no field opting out" forbids — and which
    ``SqliteMemoryStore._add_sync``'s expiry index would then be computed from.
    """
    store = InMemoryMemoryStore(now=_fixed_now)
    berlin_clock = MemoryIngestor(
        store=store,
        policy=DefaultMemoryPolicy(),
        now=lambda: datetime(2026, 6, 1, 2, tzinfo=timezone(timedelta(hours=2))),
    )

    await berlin_clock.ingest(_proposal(_semantic("1", "weak signal", confidence=0.1)))

    stored = await store.get("1")
    assert stored is not None
    assert stored.expires_at == datetime(2026, 6, 8, tzinfo=UTC)
    assert stored.expires_at.tzinfo is UTC


class _NoOffset(tzinfo):
    """A ``tzinfo`` that is set but indeterminate — issue #36's case."""

    def utcoffset(self, dt: datetime | None) -> timedelta | None:
        return None

    def dst(self, dt: datetime | None) -> timedelta | None:
        return None

    def tzname(self, dt: datetime | None) -> str | None:
        return "indeterminate"


class _RaisingOffset(tzinfo):
    """A ``tzinfo`` whose ``utcoffset()`` raises rather than answering."""

    def utcoffset(self, dt: datetime | None) -> timedelta | None:
        msg = "no offset available"
        raise RuntimeError(msg)

    def dst(self, dt: datetime | None) -> timedelta | None:
        return None

    def tzname(self, dt: datetime | None) -> str | None:
        return "raises"


class _UnreprableOffset(tzinfo):
    """Raises from ``utcoffset()`` *and* from ``__repr__``.

    ``datetime.__repr__`` embeds ``repr(tzinfo)``, so building the error message
    for this reading is itself a call into hostile code.
    """

    def utcoffset(self, dt: datetime | None) -> timedelta | None:
        msg = "no offset available"
        raise RuntimeError(msg)

    def dst(self, dt: datetime | None) -> timedelta | None:
        return None

    def tzname(self, dt: datetime | None) -> str | None:
        return "hostile"

    def __repr__(self) -> str:
        msg = "repr is hostile too"
        raise RuntimeError(msg)


@pytest.mark.parametrize(
    "zone",
    [_NoOffset(), _RaisingOffset(), _UnreprableOffset()],
    ids=["indeterminate", "raising", "unreprable"],
)
async def test_an_unusable_clock_reading_is_the_subsystems_error(zone: tzinfo) -> None:
    """Translated at this boundary, as ``_expiry`` already does for overflow.

    Unguarded, such a reading reaches ``.timestamp()`` inside the SQLite store
    and surfaces as a raw ``TypeError`` from several layers down, naming neither
    the clock nor the record. The ``unreprable`` case additionally checks that
    *describing* the reading cannot itself escape the translation.
    """
    store = InMemoryMemoryStore(now=_fixed_now)
    broken = MemoryIngestor(
        store=store,
        policy=DefaultMemoryPolicy(),
        now=lambda: datetime(2026, 6, 1, tzinfo=zone),
    )

    with pytest.raises(MemoryStoreError, match="MemoryIngestor"):
        await broken.ingest(_proposal(_semantic("1", "weak signal", confidence=0.1)))

    assert await store.get("1") is None


class _LyingConversion(datetime):
    """Aware and well-behaved, until it is asked to convert itself."""

    def astimezone(self, tz: tzinfo | None = None) -> datetime:  # type: ignore[override]
        return datetime(2026, 6, 1)  # noqa: DTZ001 — returning a naive value is the subject


async def test_a_clock_whose_conversion_lies_cannot_install_a_naive_expiry() -> None:
    """`_expiry` writes through ``model_copy``, so `UtcInstant` never sees this.

    A clock returning a ``datetime`` subclass with a valid ``utcoffset()`` but an
    overridden ``astimezone`` would otherwise put a naive ``expires_at`` straight
    into the store — raising ``TypeError`` at the first expiry comparison, or
    persisting JSON that no longer decodes.
    """
    store = InMemoryMemoryStore(now=_fixed_now)
    lying = MemoryIngestor(
        store=store,
        policy=DefaultMemoryPolicy(),
        now=lambda: _LyingConversion(2026, 6, 1, tzinfo=UTC),
    )

    with pytest.raises(MemoryStoreError, match="did not convert to UTC"):
        await lying.ingest(_proposal(_semantic("1", "weak signal", confidence=0.1)))

    assert await store.get("1") is None


class _FlipOnConvert(datetime):
    """Flips its overridden offset *during* ``astimezone``, then returns itself."""

    lie = timedelta(0)

    def utcoffset(self) -> timedelta | None:
        return _FlipOnConvert.lie

    def astimezone(self, tz: tzinfo | None = None) -> datetime:  # type: ignore[override]
        _FlipOnConvert.lie = timedelta(hours=2)
        return self


async def test_a_clock_that_flips_its_offset_during_conversion_is_refused() -> None:
    """The ingest guard is a separate implementation, so it needs its own proof.

    Same shape ``UtcInstant`` refuses: the reading reports UTC when checked,
    changes offset inside ``astimezone``, and returns itself still carrying
    ``tzinfo is UTC``. Copying its components then would stamp an expiry two
    hours late, past a validator this write never reaches.
    """
    store = InMemoryMemoryStore(now=_fixed_now)
    _FlipOnConvert.lie = timedelta(0)
    flipping = MemoryIngestor(
        store=store,
        policy=DefaultMemoryPolicy(),
        now=lambda: _FlipOnConvert(2026, 6, 1, tzinfo=UTC),
    )

    try:
        with pytest.raises(MemoryStoreError, match="did not convert to UTC"):
            await flipping.ingest(_proposal(_semantic("1", "weak signal", confidence=0.1)))
    finally:
        _FlipOnConvert.lie = timedelta(0)

    assert await store.get("1") is None


class _PauseOnFirstSearch(InMemoryMemoryStore):
    """A store whose *first* ``search`` waits for ``resume`` before reading.

    This is the interleaving harness for issue #248. The hazard is a
    read-modify-write: `ingest` searches, the policy rules, and only then does
    the write land — so a second ingest that searches inside that window folds
    into the same pre-write snapshot. Holding the first search open until the
    second ingest has been *scheduled* reproduces exactly that window, with no
    sleeps and no wall-clock dependence.

    The event is set by the second task *before* it calls ``ingest``, which is
    what keeps the harness honest under a fix: whatever serialises `ingest`
    cannot delay the release, so a serialised run drains rather than deadlocks.
    """

    def __init__(self, *, resume: asyncio.Event) -> None:
        super().__init__(now=_fixed_now)
        self._resume = resume
        self._pending = True

    async def search(
        self,
        query: str,
        *,
        limit: int = 10,
        kinds: Sequence[MemoryKind] | None = None,
    ) -> list[MemoryRecord]:
        """Delegate, then hold the first search's result until ``resume``."""
        matches = await super().search(query, limit=limit, kinds=kinds)
        if self._pending:
            self._pending = False
            # After the read, so the caller is left holding a snapshot the
            # other ingest is about to invalidate — the window issue #248 is
            # about. Pausing before the read would only re-order the two, which
            # loses nothing.
            await self._resume.wait()
        return matches


async def test_concurrent_merges_into_one_target_do_not_lose_a_write() -> None:
    """Two ingests folding into the same record must both survive (issue #248).

    Unsynchronised, both search before either writes, each folds into the same
    stale snapshot, and the second ``add`` overwrites the first — while both
    callers are handed a healthy ``MemoryIngestResult`` naming the same id. The
    dropped write may be a user correction (ADR-0038), so the assertion is that
    *nothing* is lost: the surviving record must carry both proposals' evidence
    and the higher of the two confidences.
    """
    resume = asyncio.Event()
    store = _PauseOnFirstSearch(resume=resume)
    await store.add(_preference("e", "prefers concise emails", confidence=0.5, evidence=("ev1",)))
    ingestor = _ingestor(store)

    async def first() -> MemoryIngestResult:
        return await ingestor.ingest(
            _proposal(_preference("a", "prefers concise emails", confidence=0.7, evidence=("evA",)))
        )

    async def second() -> MemoryIngestResult:
        # Released outside `ingest`, so serialising `ingest` cannot withhold it.
        resume.set()
        return await ingestor.ingest(
            _proposal(_preference("b", "prefers concise emails", confidence=0.8, evidence=("evB",)))
        )

    result_a, result_b = await asyncio.gather(first(), second())

    assert result_a.decision.kind is MemoryDecisionKind.REINFORCE
    assert result_b.decision.kind is MemoryDecisionKind.REINFORCE
    assert result_a.record_id == result_b.record_id == "e"
    merged = await store.get("e")
    assert merged is not None
    assert set(merged.provenance.evidence) == {"ev1", "evA", "evB"}
    assert merged.provenance.confidence == 0.8
