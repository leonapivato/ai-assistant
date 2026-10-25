"""The canonical FakeMemoryWriter passes the shared MemoryWriter suite.

This is what lets other subsystems trust ``ai_assistant.testing.FakeMemoryWriter``
as a stand-in for a real write path: it is held to the same contract as
``MemoryIngestor`` (see ``test_ingest_contract.py``).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

import pytest
from memory_writer_contract import MemoryWriterContract, StubReconciler, WriterFactory
from placed_writer_contract import PlacedWriterContract, PlacedWriterFactory

from ai_assistant.core.errors import MemoryStoreError, MemoryStoreStaleError
from ai_assistant.core.types import (
    Attestation,
    BeliefBand,
    ConflictRelation,
    DataTier,
    EpisodicMemory,
    Memory,
    MemoryDecisionKind,
    MemorySource,
    MemoryStanding,
    MemoryUpdateProposal,
    Provenance,
    Validity,
)
from ai_assistant.testing import FakeMemoryPolicy, FakeMemoryStore, FakeMemoryWriter
from ai_assistant.testing.memories import derived_from, memory, sourced_support

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from ai_assistant.core.protocols import Embedder, MemoryPolicy, MemoryStore, MemoryWriter
    from ai_assistant.core.types import LabelBounds, MemoryRecord

#: The episode every memory below rests on, planted by :func:`_store` (ADR-0328 §4:7).
_EPISODE = "cited-episode"

_CONTENT = "prefers concise emails"


def _fixed_now() -> datetime:
    return datetime(2026, 6, 1, tzinfo=UTC)


async def _store(now: Callable[[], datetime] = _fixed_now) -> FakeMemoryStore:
    """A store holding the episode every memory below rests on."""
    store = FakeMemoryStore(now=now)
    await store.add(
        EpisodicMemory(
            id=_EPISODE,
            content="the exchange the memories rest on",
            occurred_at=_fixed_now(),
            provenance=Provenance(
                source=MemorySource.OBSERVED, confidence=0.6, last_updated=_fixed_now()
            ),
        )
    )
    return store


def _inferred(
    record_id: str, content: str = _CONTENT, *, validity: Validity | None = None
) -> Memory:
    """A memory at inference on the derived stand-in, warranted by its episode, maybe windowed."""
    return memory(
        record_id,
        content,
        *derived_from(_EPISODE, key=record_id),
        validity=validity if validity is not None else Validity(),
    )


def _proposal(record: Memory) -> MemoryUpdateProposal:
    return MemoryUpdateProposal(proposed=record, rationale="because", sensitivity=DataTier.PERSONAL)


class TestFakeMemoryWriterContract(MemoryWriterContract):
    """Runs FakeMemoryWriter through the shared MemoryWriter conformance suite."""

    @pytest.fixture
    def make_writer(self) -> WriterFactory:
        def build(
            store: MemoryStore,
            policy: MemoryPolicy,
            *,
            id_factory: Callable[[], str] | None = None,
            conflict_limit: int | None = None,
            reconciler: StubReconciler | None = None,
        ) -> MemoryWriter:
            # Each `None` leaves the fake's own default, which is what the suite's
            # seams mean by "this obligation does not drive it".
            seams: dict[str, Any] = {}
            if id_factory is not None:
                seams["id_factory"] = id_factory
            if conflict_limit is not None:
                seams["conflict_limit"] = conflict_limit
            if reconciler is not None:
                seams["reconciler"] = reconciler
            return FakeMemoryWriter(store=store, policy=policy, now=_fixed_now, **seams)

        return build

    @pytest.fixture
    def writer(self) -> MemoryWriter:
        return FakeMemoryWriter(
            store=FakeMemoryStore(now=_fixed_now), policy=FakeMemoryPolicy(), now=_fixed_now
        )


class TestFakeMemoryWriterPlaced(PlacedWriterContract):
    """Runs FakeMemoryWriter through ADR-0345's shared placed-write suite (§15:2)."""

    @pytest.fixture
    def make_placed_writer(self) -> PlacedWriterFactory:
        def build(
            store: MemoryStore,
            policy: MemoryPolicy,
            *,
            labels: tuple[LabelBounds, Embedder] | None = None,
        ) -> MemoryWriter:
            bounds, embedder = (None, None) if labels is None else labels
            return FakeMemoryWriter(
                store=store,
                policy=policy,
                now=lambda: datetime(2026, 10, 21, 12, tzinfo=UTC),
                label_bounds=bounds,
                label_embedder=embedder,
            )

        return build


# Behaviour specific to FakeMemoryWriter, beyond the shared contract: it records
# what it was handed, which is what makes it useful to a consumer's tests.


async def test_every_proposal_is_recorded_as_handed_over() -> None:
    store = await _store()
    writer = FakeMemoryWriter(store=store, policy=FakeMemoryPolicy(), now=_fixed_now)
    proposal = _proposal(_inferred("pref-1"))

    await writer.ingest(proposal)

    assert [call.proposed.id for call in writer.calls] == ["pref-1"]
    # A snapshot, not the caller's object: mutating the proposal afterwards
    # cannot reach what was recorded.
    assert writer.calls[0] is not proposal


async def test_a_stale_retry_records_the_one_call_once() -> None:
    """One public ``ingest`` is one entry, though its first write went stale and it retried."""
    store = await _store()
    writer = FakeMemoryWriter(store=store, policy=FakeMemoryPolicy(), now=_fixed_now)
    attempts: list[int] = []
    real_write = store.write_atomic

    async def stale_once(writes: Any) -> Any:
        attempts.append(1)
        if len(attempts) == 1:
            msg = "another writer moved it"
            raise MemoryStoreStaleError(msg)
        return await real_write(writes)

    store.write_atomic = stale_once  # type: ignore[method-assign]

    result = await writer.ingest(_proposal(_inferred("pref-1")))

    assert len(attempts) == 2
    assert result.record_id == "pref-1"
    assert [call.proposed.id for call in writer.calls] == ["pref-1"]


async def test_a_non_utc_clock_is_converted_not_merely_accepted() -> None:
    """An operation's instant skips validators, so ADR-0023 §2's UTC happens here.

    Asserted on ``tzinfo``, not only on the instant: an equality check alone passes
    for a ``+02:00`` value. ``MemoryIngestor`` converts; a canonical fake that merely
    accepted would certify a consumer against state the production writer refuses.
    """
    store = await _store()
    await store.add(_inferred("existing"))
    berlin = timezone(timedelta(hours=2))
    writer = FakeMemoryWriter(
        store=store,
        policy=FakeMemoryPolicy(MemoryDecisionKind.REINFORCE),
        now=lambda: datetime(2026, 6, 1, 2, tzinfo=berlin),
    )

    await writer.ingest(_proposal(_inferred("new")))

    stored = await store.get("existing")
    assert isinstance(stored, Memory)
    added = stored.operations[-1]
    assert added.at == datetime(2026, 6, 1, tzinfo=UTC)
    assert added.at.tzinfo is UTC
    assert stored.supports[-1].added_at.tzinfo is UTC


_TARGET_WINDOW = Validity(
    valid_from=datetime(2026, 2, 1, tzinfo=UTC), valid_until=datetime(2027, 6, 1, tzinfo=UTC)
)
_TARGET_EXPIRES_AT = datetime(2027, 9, 1, tzinfo=UTC)
_INCOMING_WINDOW = Validity(
    valid_from=datetime(2026, 3, 1, tzinfo=UTC), valid_until=datetime(2027, 3, 1, tzinfo=UTC)
)
_INCOMING_EXPIRES_AT = datetime(2027, 5, 1, tzinfo=UTC)

#: The **open** lifetime, run opposite a bounded one, so a case says the survivor's
#: lifetime is *kept* rather than merely non-empty.
_OPEN_LIFETIME = (Validity(), None)


@pytest.mark.parametrize(
    ("target_window", "target_expiry"),
    [(_TARGET_WINDOW, _TARGET_EXPIRES_AT), _OPEN_LIFETIME],
    ids=["bounded-target", "open-target"],
)
async def test_a_derived_reinforcement_of_an_attested_memory_corroborates_it(
    target_window: Validity, target_expiry: datetime | None
) -> None:
    """The fake adds an inference to a source's memory the way ``MemoryIngestor`` does.

    ADR-0328 §11:6: a reinforcement only adds the proposal's supports. So the
    attested memory keeps its wording, its source standing and its source details,
    and its own lifetime — the incoming memory's window and expiry are left behind.
    """
    store = await _store()
    imported = memory(
        "imported",
        "prefers concise emails, as the mail client has it",
        sourced_support(
            Attestation(reported_by="mail:work", reported_at=_fixed_now()), episode=_EPISODE
        ),
        validity=target_window,
        expires_at=target_expiry,
    )
    await store.add(imported)
    writer = FakeMemoryWriter(
        store=store, policy=FakeMemoryPolicy(MemoryDecisionKind.REINFORCE), now=_fixed_now
    )
    incoming = _inferred("observed", validity=_INCOMING_WINDOW).model_copy(
        update={"expires_at": _INCOMING_EXPIRES_AT}
    )

    result = await writer.ingest(_proposal(incoming))

    assert result.decision.kind is MemoryDecisionKind.REINFORCE
    assert result.record_id == "imported"
    survivor = await store.get("imported")
    assert isinstance(survivor, Memory)
    assert survivor.standing is MemoryStanding.SOURCE
    assert survivor.standing_attestation == imported.supports[0].source_details
    assert survivor.content == imported.content
    assert survivor.validity == target_window
    assert survivor.expires_at == target_expiry
    assert survivor.support_at(incoming.supports[0].points_at) is not None


@pytest.mark.parametrize(
    ("incoming_window", "incoming_expiry"),
    [(_INCOMING_WINDOW, _INCOMING_EXPIRES_AT), _OPEN_LIFETIME],
    ids=["bounded-incoming", "open-incoming"],
)
async def test_an_attested_reinforcement_of_a_derived_memory_raises_its_standing(
    incoming_window: Validity, incoming_expiry: datetime | None
) -> None:
    """The reverse pairing: a source's support added to an inference.

    Before ADR-0328 this arm took the incoming record's content and lifetime. A
    reinforcement now changes no wording (§3:2) and no lifetime: the derived memory
    keeps its own, and its standing rises to "from a source" because a source's
    support now backs it (§6:2) — computed, never set.
    """
    store = await _store()
    target = _inferred(
        "observed", "prefers concise emails, as we have inferred it", validity=_TARGET_WINDOW
    ).model_copy(update={"expires_at": _TARGET_EXPIRES_AT})
    await store.add(target)
    source = sourced_support(
        Attestation(reported_by="mail:work", reported_at=_fixed_now()), episode=_EPISODE
    )
    incoming = memory(
        "imported", _CONTENT, source, validity=incoming_window, expires_at=incoming_expiry
    )
    writer = FakeMemoryWriter(
        store=store, policy=FakeMemoryPolicy(MemoryDecisionKind.REINFORCE), now=_fixed_now
    )

    result = await writer.ingest(_proposal(incoming))

    assert result.decision.kind is MemoryDecisionKind.REINFORCE
    assert result.record_id == "observed"
    survivor = await store.get("observed")
    assert isinstance(survivor, Memory)
    assert survivor.content == target.content
    assert survivor.validity == _TARGET_WINDOW
    assert survivor.expires_at == _TARGET_EXPIRES_AT
    assert survivor.band is BeliefBand.ATTESTED


async def test_supersede_refuses_a_future_dated_target_without_writing() -> None:
    """The fake carries the same refusal as ``MemoryIngestor`` (ADR-0080 §3, §5:11).

    A producer-set ``valid_from`` after the writer's clock would close to an inverted
    window, so the fake refuses before the write rather than let a consumer's test
    pass on state the production writer could not persist.
    """
    store = await _store(lambda: datetime(2026, 10, 1, tzinfo=UTC))
    await store.add(
        _inferred("existing", validity=Validity(valid_from=datetime(2026, 9, 1, tzinfo=UTC)))
    )
    before = await store.export()
    writer = FakeMemoryWriter(
        store=store, policy=FakeMemoryPolicy(MemoryDecisionKind.SUPERSEDE), now=_fixed_now
    )

    with pytest.raises(MemoryStoreError, match="valid_from"):
        await writer.ingest(_proposal(_inferred("correction", "prefers concise formal emails")))

    assert await store.export() == before


async def test_supersede_never_extends_a_targets_existing_window() -> None:
    """The fake keeps a target's earlier ``valid_until`` — retirement never resurrects."""
    already_closes = datetime(2026, 3, 1, tzinfo=UTC)  # before the writer's 2026-06-01 clock
    store = await _store(lambda: datetime(2026, 2, 1, tzinfo=UTC))
    await store.add(_inferred("existing", validity=Validity(valid_until=already_closes)))
    writer = FakeMemoryWriter(
        store=store, policy=FakeMemoryPolicy(MemoryDecisionKind.SUPERSEDE), now=_fixed_now
    )

    result = await writer.ingest(
        _proposal(_inferred("correction", "prefers concise formal emails"))
    )

    assert result.decision.kind is MemoryDecisionKind.SUPERSEDE
    retired = next(record for record in await store.export() if record.id == "existing")
    assert retired.validity.valid_until == already_closes


async def test_supersede_refuses_a_target_whose_window_opens_at_the_close() -> None:
    """ADR-0080 §3's tie, on the fake: ``[F, F)`` is empty, so it refuses whole."""
    store = await _store(lambda: datetime(2026, 7, 1, tzinfo=UTC))
    await store.add(_inferred("opens-at-close", validity=Validity(valid_from=_fixed_now())))
    await store.add(_inferred("sibling"))
    before = await store.export()
    writer = FakeMemoryWriter(
        store=store,
        policy=FakeMemoryPolicy(MemoryDecisionKind.SUPERSEDE),
        now=_fixed_now,
        id_factory=lambda: "corrected",
    )

    with pytest.raises(MemoryStoreError, match="valid_from"):
        await writer.ingest(_proposal(_inferred("correction", "prefers concise formal emails")))

    assert await store.export() == before
    assert await store.get("corrected") is None


class _AdvancingClock:
    """Records every reading and returns a later instant each time (ADR-0080 §7)."""

    def __init__(self) -> None:
        self.readings: list[datetime] = []

    def __call__(self) -> datetime:
        reading = _fixed_now() + timedelta(hours=len(self.readings))
        self.readings.append(reading)
        return reading


class _AllContradicted:
    """A stub labelling every member it is shown ``CONTRADICTS`` (ADR-0336 §5:1)."""

    async def reconcile(
        self, proposal: MemoryUpdateProposal, conflicts: Sequence[MemoryRecord]
    ) -> Mapping[str, ConflictRelation]:
        return dict.fromkeys((c.id for c in conflicts), ConflictRelation.CONTRADICTS)


async def test_a_multi_target_supersede_reads_its_close_instant_exactly_once() -> None:
    """One instant for the whole retirement set (ADR-0080 §1), on the fake.

    The set is several members only where each is a labelled contradiction
    (ADR-0336 §5:1), so the stub labels all three.
    """
    store = await _store(lambda: datetime(2026, 1, 1, tzinfo=UTC))
    for stale_id in ("first", "second", "third"):
        await store.add(_inferred(stale_id))
    clock = _AdvancingClock()
    writer = FakeMemoryWriter(
        store=store,
        policy=FakeMemoryPolicy(MemoryDecisionKind.SUPERSEDE),
        now=clock,
        id_factory=lambda: "corrected",
        reconciler=_AllContradicted(),
    )

    result = await writer.ingest(
        _proposal(_inferred("correction", "prefers concise formal emails"))
    )

    assert result.decision.kind is MemoryDecisionKind.SUPERSEDE
    assert len(clock.readings) == 1
    exported = {record.id: record for record in await store.export()}
    ends = {exported[stale_id].validity.valid_until for stale_id in ("first", "second", "third")}
    assert ends == {clock.readings[0]}


async def test_supersede_hiding_is_read_time_relative() -> None:
    """The fake's retirement is hidden read-time-relatively, as ``MemoryIngestor``'s is."""
    read_at = [datetime(2026, 1, 1, tzinfo=UTC)]  # store read clock; starts BEHIND close
    store = await _store(lambda: read_at[0])
    await store.add(_inferred("existing"))
    writer = FakeMemoryWriter(
        store=store, policy=FakeMemoryPolicy(MemoryDecisionKind.SUPERSEDE), now=_fixed_now
    )

    result = await writer.ingest(
        _proposal(_inferred("correction", "prefers concise formal emails"))
    )
    assert result.decision.kind is MemoryDecisionKind.SUPERSEDE
    new_id = result.record_id
    assert new_id is not None

    assert await store.get("existing") is not None
    read_at[0] = datetime(2026, 6, 1, tzinfo=UTC)
    assert await store.get("existing") is None
    assert {r.id for r in await store.export() if isinstance(r, Memory)} == {"existing", new_id}


@pytest.mark.parametrize("answer", [None, "not a mapping", 42], ids=["none", "a-string", "an-int"])
async def test_a_reconciler_returning_something_unusable_refuses_no_ingest(
    answer: object,
) -> None:
    """ADR-0159 §6 over the *return*, mirroring ``MemoryIngestor``."""

    class _Unusable:
        async def reconcile(
            self, proposal: MemoryUpdateProposal, conflicts: Sequence[MemoryRecord]
        ) -> Mapping[str, ConflictRelation]:
            return answer  # type: ignore[return-value]  # deliberately non-conforming

    store = await _store()
    writer = FakeMemoryWriter(
        store=store,
        policy=FakeMemoryPolicy(),
        now=_fixed_now,
        reconciler=_Unusable(),
    )

    result = await writer.ingest(_proposal(_inferred("pref-1")))

    assert result.record_id == "pref-1"
    assert await store.get("pref-1") is not None
