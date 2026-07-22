"""Tests for the memory ingestor (conflict detection + policy + application)."""

from __future__ import annotations

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
)
from ai_assistant.memory import DefaultMemoryPolicy, InMemoryMemoryStore, MemoryIngestor

if TYPE_CHECKING:
    from collections.abc import Sequence

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


def _ingestor(store: InMemoryMemoryStore) -> MemoryIngestor:
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

    assert result.decision.kind is MemoryDecisionKind.MERGE
    assert result.record_id == "e"
    merged = await store.get("e")
    assert merged is not None
    assert merged.provenance.confidence == 0.7  # max of the two
    assert set(merged.provenance.evidence) == {"ev1", "ev2"}
    assert await store.get("new") is None  # merged in place, not duplicated


async def test_user_assertion_supersedes_the_inference_it_contradicts() -> None:
    # The unlearning path (issue #38, ADR-0038): a correction must take the
    # stale belief off the read path, not sit beside it. Asserted end to end
    # rather than on the policy alone, because "the wrong memory is still
    # retrievable" is a property of the store after ingestion.
    store = InMemoryMemoryStore()
    await store.add(
        _preference("stale", "user prefers morning meetings", confidence=0.6, evidence=("ev1",))
    )

    result = await _ingestor(store).ingest(
        _proposal(_asserted("correction", "user prefers afternoon meetings", evidence=("ev2",)))
    )

    assert result.decision.kind is MemoryDecisionKind.MERGE
    assert result.record_id == "stale"
    superseded = await store.get("stale")
    assert superseded is not None
    assert superseded.content == "user prefers afternoon meetings"
    assert superseded.provenance.source is MemorySource.USER_ASSERTED
    assert superseded.provenance.confidence == 1.0
    assert set(superseded.provenance.evidence) == {"ev1", "ev2"}  # the trail survives
    assert await store.get("correction") is None  # not stored beside the stale belief
    assert [record.id for record in await store.export()] == ["stale"]


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
    """A policy that always asks to merge into a record that isn't a conflict."""

    async def decide(
        self,
        proposal: MemoryUpdateProposal,
        *,
        conflicts: Sequence[MemoryRecord],
    ) -> MemoryDecision:
        return MemoryDecision(
            kind=MemoryDecisionKind.MERGE, merge_into="ghost", reason="test misdirection"
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
