"""Tests for the memory ingestor (conflict detection + policy + application)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta, timezone, tzinfo
from typing import TYPE_CHECKING

import pytest

from ai_assistant.core.errors import MemoryStoreError
from ai_assistant.core.types import (
    Attestation,
    BeliefBand,
    DataTier,
    EpisodicMemory,
    MemoryDecision,
    MemoryDecisionKind,
    MemoryRecord,
    MemorySource,
    MemoryUpdateProposal,
    PreferenceMemory,
    Provenance,
    SemanticMemory,
    Validity,
    band_of,
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


#: What the `ATTESTED` band must carry since ADR-0092 §1. Attached by `_prov` from
#: the band rather than passed per case: none of the rules below turns on its
#: *contents*, so spelling it out at every `EXTERNAL` site would put noise in front
#: of the rule each case is about. The fold case that *does* care passes its own.
_ATTESTED_BY = Attestation(reported_by="calendar:work", reported_at=_WHEN)


def _prov(
    confidence: float,
    evidence: tuple[str, ...] = (),
    *,
    source: MemorySource = MemorySource.OBSERVED,
    attestation: Attestation | None = None,
) -> Provenance:
    return Provenance(
        source=source,
        confidence=confidence,
        last_updated=_WHEN,
        evidence=evidence,
        # Keyed on the band, so a `MemorySource` added into `ATTESTED` later needs
        # no edit here, and so a case that supplies its own is not overridden.
        attestation=(
            attestation
            if attestation is not None or band_of(source) is not BeliefBand.ATTESTED
            else _ATTESTED_BY
        ),
    )


#: The episode a well-formed derived proposal cites. Two ratified rules make it
#: necessary rather than decorative, and they are different rules with different
#: owners (ADR-0077 §5): ``DefaultMemoryPolicy`` **rejects** a ``DERIVED`` proposal
#: citing nothing, and ``MemoryIngestor`` **refuses** one citing a record the store
#: does not hold. So a derived proposal that means to exercise anything else has to
#: cite an episode, and the store has to be holding it (:func:`_plant_episodes`).
_EPISODE = "episode-1"


async def _plant_episodes(store: MemoryStore, *episode_ids: str) -> None:
    """Store the episodes the proposals below cite, so their citations resolve.

    ``EPISODIC``, so kind-scoped conflict detection never returns one as a conflict
    for the semantic and preference proposals these tests drive.
    """
    for episode_id in episode_ids:
        await store.add(
            EpisodicMemory(
                id=episode_id,
                content=f"the exchange {episode_id} records",
                occurred_at=_WHEN,
                provenance=_prov(0.6),
            )
        )


def _semantic(
    record_id: str,
    content: str,
    *,
    confidence: float = 0.6,
    evidence: tuple[str, ...] = (),
) -> MemoryRecord:
    return SemanticMemory(
        id=record_id, content=content, fact=content, provenance=_prov(confidence, evidence)
    )


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
    await _plant_episodes(store, _EPISODE)

    result = await _ingestor(store).ingest(
        _proposal(_semantic("1", "unique gardening fact", confidence=0.9, evidence=(_EPISODE,)))
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
    await _plant_episodes(store, "ev1", "ev2")
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


async def test_a_correction_retires_every_conflicting_inference_not_only_the_best_ranked() -> None:
    # ADR-0050 §1 (#244): a correction that contradicts *several* stale inferences
    # must retire the whole set in one supersession, not just the policy's best-ranked
    # target — otherwise the second and third stale belief stay live on the read path,
    # the exact leak issue #244 reports. Asserted end to end: which windows closed is
    # a property of the store.
    store = InMemoryMemoryStore()
    for stale_id in ("morning", "early", "dawn"):
        await store.add(
            _preference(
                stale_id,
                "user prefers morning meetings",
                confidence=0.6,
                source=MemorySource.INFERRED,
            )
        )
    # An EXTERNAL conflict on the same topic. Since ADR-0092 §4 adopted EXTERNAL
    # supersession — partially superseding ADR-0050 §1's hold-out — it is in the
    # retirement class and is swept in with the inferences: the calendar is an
    # *input*, so the user's correction retires it rather than leaving it live
    # beside them.
    await store.add(
        _preference(
            "imported", "user prefers noon meetings", confidence=1.0, source=MemorySource.EXTERNAL
        )
    )
    # A low threshold so all four near-duplicates are detected (they score at the
    # default 0.75 boundary; the headroom keeps the test off the knife-edge).
    ingestor = MemoryIngestor(
        store=store,
        policy=DefaultMemoryPolicy(),
        now=_fixed_now,
        conflict_threshold=0.5,
        id_factory=lambda: "corrected",
    )

    result = await ingestor.ingest(
        _proposal(_asserted("correction", "user prefers afternoon meetings"))
    )

    assert result.decision.kind is MemoryDecisionKind.SUPERSEDE
    assert result.record_id == "corrected"
    retired_ids = ("morning", "early", "dawn", "imported")
    # Every retirable belief on the topic is off the read path — the three
    # inferences and, since ADR-0092 §4, the import.
    for retired_id in retired_ids:
        assert await store.get(retired_id) is None
    # The correction is live; the whole retained set is the four originals plus it.
    assert await store.get("corrected") is not None
    exported = {record.id: record for record in await store.export()}
    assert set(exported) == {*retired_ids, "corrected"}
    for retired_id in retired_ids:
        assert exported[retired_id].validity.valid_until is not None
    # The ones the policy did not name still closed on the same instant as the named
    # target — one atomic close, not a partial one (ADR-0080 §1).
    closes = {exported[i].validity.valid_until for i in retired_ids}
    assert len(closes) == 1


@pytest.mark.parametrize("backend", ["in-memory", "sqlite"])
async def test_a_multi_target_supersede_that_cannot_mint_leaves_every_target_live(
    backend: str, tmp_path: Path
) -> None:
    # ADR-0050 §1 / ADR-0045 §8: the widened supersession closes N windows and inserts
    # the correction as one atomic `write_atomic` batch, so a failure part-way must
    # leave *every* target live and unchanged — not some retired with no replacement.
    # Driven deterministically by an always-colliding id factory: after the bounded
    # re-mints the applier raises, and the atomic batch rolls back all N window-closes.
    # Run over SQLite too, where `write_atomic` *applies* the target UPSERTs before it
    # discovers the correction's INSERT_IF_ABSENT collision — so rollback happens after
    # real writes, the integration path the in-memory store (which validates the
    # collision first) does not exercise.
    store: MemoryStore
    if backend == "in-memory":
        store = InMemoryMemoryStore()
    else:
        store = SqliteMemoryStore(
            path=tmp_path / "memory.db", embedder=HashingEmbedder(dimensions=32)
        )
    try:
        for stale_id in ("morning", "early", "dawn"):
            await store.add(
                _preference(
                    stale_id,
                    "user prefers morning meetings",
                    confidence=0.6,
                    source=MemorySource.INFERRED,
                )
            )
        # An unrelated record occupying the id the factory always mints, so every
        # INSERT_IF_ABSENT collides and the correction can never land.
        await store.add(_semantic("wall", "an unrelated fact", confidence=0.9))
        ingestor = MemoryIngestor(
            store=store,
            policy=DefaultMemoryPolicy(),
            now=_fixed_now,
            conflict_threshold=0.5,
            id_factory=lambda: "wall",
        )

        with pytest.raises(MemoryStoreError):
            await ingestor.ingest(
                _proposal(_asserted("correction", "user prefers afternoon meetings"))
            )

        # Every target is still live with an open window — the multi-close rolled back.
        for stale_id in ("morning", "early", "dawn"):
            record = await store.get(stale_id)
            assert record is not None
            assert record.validity.valid_until is None
        assert await store.get("wall") is not None  # the collided-with record is intact
    finally:
        if isinstance(store, SqliteMemoryStore):
            store.close()


async def test_a_correction_above_the_conflict_ceiling_refuses_and_writes_nothing() -> None:
    # The same boundary this file used to pin, with the opposite ratified outcome.
    # ADR-0050 §1 accepted a bounded surplus above `conflict_limit`: one supersession
    # retired exactly the cap and the rest stayed live. ADR-0079 §1 partially
    # supersedes that clause and re-founds the limit as a *ceiling*: a correction
    # resolves every conflict it is shown, or it does not land. Above it the ingest
    # refuses — nothing written, no window closed, no ruling sought — because the
    # surplus never drained (a re-proposal sees the landed correction as an asserted
    # conflict and defers, ADR-0050 §2) and because the same truncation could hide an
    # asserted conflict from the policy's own gates.
    store = InMemoryMemoryStore()
    stale_ids = ("s1", "s2", "s3")  # three matching inferences, ceiling set to two below
    for stale_id in stale_ids:
        await store.add(
            _preference(
                stale_id,
                "user prefers morning meetings",
                confidence=0.6,
                source=MemorySource.INFERRED,
            )
        )
    ingestor = MemoryIngestor(
        store=store,
        policy=DefaultMemoryPolicy(),
        now=_fixed_now,
        conflict_threshold=0.5,
        conflict_limit=2,
        id_factory=lambda: "corrected",
    )

    with pytest.raises(MemoryStoreError, match="surfaced more than"):
        await ingestor.ingest(_proposal(_asserted("correction", "user prefers afternoon meetings")))

    # Every contradicting inference is still live with an open window, and the
    # correction did not land: the store is exactly as it was.
    for stale_id in stale_ids:
        record = await store.get(stale_id)
        assert record is not None
        assert record.validity.valid_until is None
    assert await store.get("corrected") is None
    assert {record.id for record in await store.export()} == set(stale_ids)


async def test_a_correction_that_contradicts_an_assertion_defers_and_writes_nothing() -> None:
    # ADR-0050 §2 (#245): a user assertion that contradicts a prior *assertion* is
    # deferred to the user (ASK_USER). Neither is destroyed on a topical-similarity
    # signal (ADR-0045 §5 / clause 1), and the new one is not silently committed
    # beside the old — so the profile never holds two live contradictory assertions.
    store = InMemoryMemoryStore()
    await store.add(_asserted("earlier", "user works from the Berlin office"))

    result = await _ingestor(store).ingest(
        _proposal(_asserted("later", "user works from the Munich office"))
    )

    assert result.decision.kind is MemoryDecisionKind.ASK_USER
    assert result.record_id is None
    # Nothing written: the earlier assertion is untouched and still live, the new one
    # is not stored. The contradiction is surfaced for the user to resolve, not
    # resolved by the heuristic.
    earlier = await store.get("earlier")
    assert earlier is not None
    assert earlier.validity.valid_until is None
    assert await store.get("later") is None
    assert {record.id for record in await store.export()} == {"earlier"}


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
    # is a MemoryStore contract change deferred to issue #460, which ADR-0080 §9 split
    # out of #306 and left unclosed. Run over SQLite too,
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

        # `export` keeps the retired target regardless of its validity window (at
        # either read clock); both records here are non-expired, so both appear.
        assert {r.id for r in await store.export()} == {"stale", new_id}
    finally:
        if isinstance(store, SqliteMemoryStore):
            store.close()


async def test_superseding_a_target_never_extends_its_existing_window() -> None:
    # ADR-0080 §1's clamp: retirement takes a belief *off* the read path and never
    # resurrects one. A target that already self-closes *before* the ingestor's
    # clock keeps that earlier end (`_close_window` takes the min), so a
    # supersession cannot push a self-closed belief back onto the read path for
    # [existing-end, now). No invalid interval or clock skew is needed — just a
    # producer-set `valid_until` earlier than the writer clock, with the store
    # reading before it so it is a live conflict. This is the clock-injected form
    # the shared suite cannot express, which states the clamp as an inequality
    # because it pins no writer clock (ADR-0080 §7).
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
    # ADR-0080 §3's refusal, now ratified rather than an applier floor: a
    # producer-set `valid_from` at or after the ingestor's clock would, closed at
    # `now`, form an empty/inverted window that `SqliteMemoryStore`'s decode
    # re-validation rejects — corrupting reads. The applier refuses before
    # `write_atomic`, so *neither* backend persists it. Run over both because the
    # corruption is backend-specific. The
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


@pytest.mark.parametrize("backend", ["in-memory", "sqlite"])
async def test_superseding_a_target_whose_window_opens_at_the_close_refuses(
    backend: str, tmp_path: Path
) -> None:
    # ADR-0080 §3's **tie**, which nothing pinned before it: `end == valid_from`
    # gives the half-open interval [F, F) — empty, live at no instant — so there is
    # no honest end to write and it falls on the refusing side rather than on a
    # "close it at its own start" fallback. The sibling case above plants
    # `valid_from` strictly *after* the writer's clock, so it still holds if the
    # check is weakened from `end <= valid_from` to `end <`; under that weakening
    # this one persists [F, F), which `model_copy(update=...)` constructs without
    # re-running `Validity`'s validator and SQLite then cannot decode. A second,
    # ordinary target is present so the assertion is ADR-0080 §6's: *every* record
    # in the retirement set is byte-identical afterwards, not merely the awkward one
    # — there is no "skip it and retire the rest".
    close = _fixed_now()  # the ingestor's close instant, and the planted valid_from
    store: MemoryStore
    if backend == "in-memory":
        store = InMemoryMemoryStore(now=lambda: datetime(2026, 7, 1, tzinfo=UTC))
    else:
        store = SqliteMemoryStore(
            path=tmp_path / "memory.db",
            embedder=HashingEmbedder(dimensions=32),
            now=lambda: datetime(2026, 7, 1, tzinfo=UTC),
        )
    try:
        await store.add(
            PreferenceMemory(
                id="opens-at-close",
                content="user prefers morning meetings",
                preference="morning",
                validity=Validity(valid_from=close),  # live at the store's clock
                provenance=_prov(0.6, source=MemorySource.INFERRED),
            )
        )
        await store.add(
            _preference(
                "sibling",
                "user prefers morning meetings",
                confidence=0.6,
                source=MemorySource.INFERRED,
            )
        )
        before = {record.id: record for record in await store.export()}

        with pytest.raises(MemoryStoreError, match="valid_from"):
            await _ingestor(store).ingest(
                _proposal(_asserted("correction", "user prefers morning meetings"))
            )

        assert {record.id: record for record in await store.export()} == before
    finally:
        if isinstance(store, SqliteMemoryStore):
            store.close()


class _AdvancingClock:
    """Records every reading and returns a later instant each time.

    ADR-0080 §7's instrument for the one thing the shared suite cannot express:
    that a writer reads its close instant **once** per ingest. Equality across the
    retired records alone is satisfied by a writer that re-samples a *constant*
    clock; equality plus advancing is satisfied by one that ignores its injected
    clock entirely. The call count and the first-value identity together rule out
    both, and they are observable only because the test owns the clock.
    """

    def __init__(self) -> None:
        self.readings: list[datetime] = []

    def __call__(self) -> datetime:
        reading = _fixed_now() + timedelta(hours=len(self.readings))
        self.readings.append(reading)
        return reading


async def test_a_multi_target_supersede_reads_its_close_instant_exactly_once() -> None:
    # ADR-0080 §1: `now` is one instant, determined before any write and shared by
    # every member of the retirement set — never re-determined per target, which
    # would let one atomic batch record two different close times for one ruling,
    # so a reader could not say when the correction took effect.
    store = InMemoryMemoryStore()
    for stale_id in ("morning", "early", "dawn"):
        await store.add(
            _preference(
                stale_id,
                "user prefers morning meetings",
                confidence=0.6,
                source=MemorySource.INFERRED,
            )
        )
    clock = _AdvancingClock()
    ingestor = MemoryIngestor(
        store=store,
        policy=DefaultMemoryPolicy(),
        now=clock,
        conflict_threshold=0.5,
        id_factory=lambda: "corrected",
    )

    result = await ingestor.ingest(
        _proposal(_asserted("correction", "user prefers afternoon meetings"))
    )

    assert result.decision.kind is MemoryDecisionKind.SUPERSEDE
    assert len(clock.readings) == 1
    exported = {record.id: record for record in await store.export()}
    ends = {exported[stale_id].validity.valid_until for stale_id in ("morning", "early", "dawn")}
    assert ends == {clock.readings[0]}


async def test_a_correction_retires_the_import_and_survives_the_next_re_sync() -> None:
    # ADR-0092 §7's trace, end to end, because the property is in the interaction
    # and not in either half. It is the ADR-0038 §2a reproduction replayed on the
    # tree ADR-0092 describes, and both halves of that ADR are load-bearing here:
    #
    #   Monday   the calendar reports London; the import lands as an attested
    #            record at *our* id `m1` (§6: the source's key is not the store's
    #            key, so a producer mints).
    #   ...      the user says Berlin. §4 puts `m1` in the retirement class, the
    #            policy rules SUPERSEDE, and the applier closes `m1`'s window and
    #            writes the correction at a fresh id (ADR-0045 §4). `m1` is off
    #            `get` and retained in `export` (ADR-0045 §6).
    #   Tuesday  the calendar still says London and re-syncs, at a *newly minted*
    #            id. Because it no longer computes `m1`'s id, it cannot land on the
    #            retired record and erase the retirement — which is the narrow,
    #            honest thing §6 buys, and the only thing asserted below.
    store = InMemoryMemoryStore()
    ingestor = MemoryIngestor(
        store=store, policy=DefaultMemoryPolicy(), now=_fixed_now, id_factory=lambda: "m2"
    )
    await store.add(
        _preference(
            "m1",
            "user works from the london office",
            confidence=1.0,
            source=MemorySource.EXTERNAL,
        )
    )

    corrected = await ingestor.ingest(
        _proposal(_asserted("new", "user works from the berlin office"))
    )
    resync = await ingestor.ingest(
        _proposal(
            _preference(
                "m3",  # minted afresh this sync, never `m1` (§6)
                "user works from the london office",
                confidence=1.0,
                source=MemorySource.EXTERNAL,
            )
        )
    )

    # The correction retired the import rather than landing beside it (§4).
    assert corrected.decision.kind is MemoryDecisionKind.SUPERSEDE
    assert corrected.decision.target_id == "m1"
    correction = await store.get("m2")
    assert correction is not None
    assert correction.content == "user works from the berlin office"
    assert correction.provenance.source is MemorySource.USER_ASSERTED

    # The retirement itself survives the re-sync. This is the assertion that
    # matters: under the source's key as the store's id, the re-sync's blind
    # `ACCEPT` upsert would have landed on `m1` and replaced a record whose window
    # was closed with one whose window is open by default — erasing the only
    # on-disk evidence that the user's correction ever took effect, which ADR-0045
    # §6 guaranteed `export` would keep.
    exported = {record.id: record for record in await store.export()}
    assert exported["m1"].validity.valid_until is not None, "the retirement was erased"
    assert exported["m1"].content == "user works from the london office"
    assert await store.get("m1") is None  # retired, retained, off the read path

    # Which branch the re-sync takes is a *similarity* outcome, and ADR-0092 §7
    # names both as ratified: the correction surfaces and rule 4 rules ASK_USER
    # (nothing written), or it does not and the import lands live at its fresh id
    # beside the correction — the two-live-records residual §7 declines to close.
    # Neither may destroy anything, which is what is asserted above.
    assert resync.decision.kind in {MemoryDecisionKind.ASK_USER, MemoryDecisionKind.ACCEPT}
    if resync.decision.kind is MemoryDecisionKind.ACCEPT:
        assert await store.get("m3") is not None


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


async def test_the_whole_detected_conflict_set_reaches_the_policy_at_the_ceiling() -> None:
    """At the ceiling, nothing detected is discarded before the ruling (ADR-0079 §1).

    The over-fetch that makes room for excluding the proposal's own record must not
    leak into what the policy sees either — the limit is a ceiling on the *ruled-on*
    set, not on the rows retrieval was asked for.
    """
    store = InMemoryMemoryStore()
    for index in range(3):
        await store.add(_preference(f"existing-{index}", "prefers concise emails"))
    policy = _RecordingPolicy()
    ingestor = MemoryIngestor(store=store, policy=policy, conflict_limit=3, now=_fixed_now)

    await ingestor.ingest(_proposal(_preference("new", "prefers concise emails")))

    assert policy.conflicts == [["existing-0", "existing-1", "existing-2"]]


async def test_a_conflict_set_above_the_ceiling_is_refused_before_the_policy_is_asked() -> None:
    """One past the ceiling refuses rather than truncating (ADR-0079 §1).

    The counterpart of the case above, and the reason the over-fetch is two rows
    rather than one: without a probe past the ceiling, "retrieval surfaced exactly
    the ceiling" and "it surfaced more" are indistinguishable, and a writer that
    could not tell them apart would have to discard silently — the defect #313
    reports.
    """
    store = InMemoryMemoryStore()
    for index in range(4):
        await store.add(_preference(f"existing-{index}", "prefers concise emails"))
    before = await store.export()
    policy = _RecordingPolicy()
    ingestor = MemoryIngestor(store=store, policy=policy, conflict_limit=3, now=_fixed_now)

    with pytest.raises(MemoryStoreError, match="surfaced more than"):
        await ingestor.ingest(_proposal(_preference("new", "prefers concise emails")))

    assert policy.conflicts == []  # the policy was never asked
    assert await store.export() == before  # and nothing was written


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
    await _plant_episodes(store, _EPISODE)

    result = await _ingestor(store).ingest(
        _proposal(_semantic("1", "weak signal", confidence=0.1, evidence=(_EPISODE,)))
    )

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
    # Kind-scoped detection keeps the cited episode out of a semantic proposal's
    # conflicts, so it cannot consume the ceiling of 1 this case is pinning.
    await _plant_episodes(store, _EPISODE)
    ingestor = MemoryIngestor(
        store=store,
        policy=DefaultMemoryPolicy(),
        conflict_threshold=threshold,
        conflict_limit=limit,
        now=_fixed_now,
    )

    result = await ingestor.ingest(
        _proposal(_semantic("1", "unique fact", confidence=0.9, evidence=(_EPISODE,)))
    )

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
    await _plant_episodes(store, _EPISODE)
    naive_clock = MemoryIngestor(
        store=store,
        policy=DefaultMemoryPolicy(),
        now=lambda: datetime(2026, 6, 1),  # noqa: DTZ001 — the naive clock is the subject
    )

    with pytest.raises(MemoryStoreError, match="MemoryIngestor"):
        await naive_clock.ingest(
            _proposal(_semantic("1", "weak signal", confidence=0.1, evidence=(_EPISODE,)))
        )

    assert await store.get("1") is None


async def test_a_non_utc_clock_is_converted_not_merely_accepted() -> None:
    """The write skips the validator, so §2's UTC storage has to happen here.

    Asserted on ``tzinfo``, not only on the instant: an equality check alone
    passes for a ``+02:00`` value, which is exactly the state ADR-0023 §2's
    "no field opting out" forbids — and which
    ``SqliteMemoryStore._add_sync``'s expiry index would then be computed from.
    """
    store = InMemoryMemoryStore(now=_fixed_now)
    await _plant_episodes(store, _EPISODE)
    berlin_clock = MemoryIngestor(
        store=store,
        policy=DefaultMemoryPolicy(),
        now=lambda: datetime(2026, 6, 1, 2, tzinfo=timezone(timedelta(hours=2))),
    )

    await berlin_clock.ingest(
        _proposal(_semantic("1", "weak signal", confidence=0.1, evidence=(_EPISODE,)))
    )

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
    await _plant_episodes(store, _EPISODE)
    broken = MemoryIngestor(
        store=store,
        policy=DefaultMemoryPolicy(),
        now=lambda: datetime(2026, 6, 1, tzinfo=zone),
    )

    with pytest.raises(MemoryStoreError, match="MemoryIngestor"):
        await broken.ingest(
            _proposal(_semantic("1", "weak signal", confidence=0.1, evidence=(_EPISODE,)))
        )

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
    await _plant_episodes(store, _EPISODE)
    lying = MemoryIngestor(
        store=store,
        policy=DefaultMemoryPolicy(),
        now=lambda: _LyingConversion(2026, 6, 1, tzinfo=UTC),
    )

    with pytest.raises(MemoryStoreError, match="did not convert to UTC"):
        await lying.ingest(
            _proposal(_semantic("1", "weak signal", confidence=0.1, evidence=(_EPISODE,)))
        )

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
    await _plant_episodes(store, _EPISODE)
    _FlipOnConvert.lie = timedelta(0)
    flipping = MemoryIngestor(
        store=store,
        policy=DefaultMemoryPolicy(),
        now=lambda: _FlipOnConvert(2026, 6, 1, tzinfo=UTC),
    )

    try:
        with pytest.raises(MemoryStoreError, match="did not convert to UTC"):
            await flipping.ingest(
                _proposal(_semantic("1", "weak signal", confidence=0.1, evidence=(_EPISODE,)))
            )
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
    # Planted before the harness arms: the evidence resolution both ingests do is a
    # `get`, not a `search`, so it neither trips nor is tripped by the pause.
    await _plant_episodes(store, "ev1", "evA", "evB")
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
