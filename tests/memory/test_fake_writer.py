"""The canonical FakeMemoryWriter passes the shared MemoryWriter suite.

This is what lets other subsystems trust ``ai_assistant.testing.FakeMemoryWriter``
as a stand-in for a real write path: it is held to the same contract as
``MemoryIngestor`` (see ``test_ingest_contract.py``).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

import pytest
from memory_writer_contract import MemoryWriterContract, WriterFactory

from ai_assistant.core.errors import MemoryStoreError
from ai_assistant.core.types import (
    Attestation,
    DataTier,
    EpisodicMemory,
    MemoryDecisionKind,
    MemorySource,
    MemoryUpdateProposal,
    PreferenceMemory,
    Provenance,
    ReadCoverage,
    ReportedExtent,
    SourceReading,
    Validity,
)
from ai_assistant.testing import FakeMemoryPolicy, FakeMemoryStore, FakeMemoryWriter

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from ai_assistant.core.protocols import MemoryPolicy, MemoryStore, MemoryWriter
    from ai_assistant.core.types import BeliefBand, MemoryKind, MemoryRecord


def _fixed_now() -> datetime:
    return datetime(2026, 6, 1, tzinfo=UTC)


def _proposal(
    record_id: str,
    *,
    evidence: tuple[str, ...] = (),
    validity: Validity | None = None,
    expires_at: datetime | None = None,
    last_updated: datetime | None = None,
) -> MemoryUpdateProposal:
    # The three lifecycle fields are optional and default to what every case that
    # does not care about them already had — an open window, no expiry, the fixed
    # clock — so only the fold case that asserts on them spells them out.
    content = "prefers concise emails"
    return MemoryUpdateProposal(
        proposed=PreferenceMemory(
            id=record_id,
            content=content,
            preference=content,
            validity=validity if validity is not None else Validity(),
            expires_at=expires_at,
            provenance=Provenance(
                source=MemorySource.OBSERVED,
                confidence=0.6,
                evidence=evidence,
                last_updated=last_updated if last_updated is not None else _fixed_now(),
            ),
        ),
        rationale="because",
        sensitivity=DataTier.PERSONAL,
    )


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
        ) -> MemoryWriter:
            # Each `None` leaves the fake's own default, which is what the suite's
            # seams mean by "this obligation does not drive it".
            seams: dict[str, Any] = {}
            if id_factory is not None:
                seams["id_factory"] = id_factory
            if conflict_limit is not None:
                seams["conflict_limit"] = conflict_limit
            return FakeMemoryWriter(store=store, policy=policy, now=_fixed_now, **seams)

        return build

    @pytest.fixture
    def writer(self) -> MemoryWriter:
        return FakeMemoryWriter(
            store=FakeMemoryStore(now=_fixed_now), policy=FakeMemoryPolicy(), now=_fixed_now
        )


# Behaviour specific to FakeMemoryWriter, beyond the shared contract: it records
# what it was handed, which is what makes it useful to a consumer's tests.


async def test_every_proposal_is_recorded_as_handed_over() -> None:
    store = FakeMemoryStore(now=_fixed_now)
    writer = FakeMemoryWriter(store=store, policy=FakeMemoryPolicy(), now=_fixed_now)
    proposal = _proposal("pref-1")

    await writer.ingest(proposal)

    assert [call.proposed.id for call in writer.calls] == ["pref-1"]
    # A snapshot, not the caller's object: mutating the proposal afterwards
    # cannot reach what was recorded.
    assert writer.calls[0] is not proposal


async def test_a_non_utc_clock_is_converted_not_merely_accepted() -> None:
    """The expiry write skips validators, so ADR-0023 §2's UTC has to happen here.

    Asserted on ``tzinfo``, not only on the instant: an equality check alone
    passes for a ``+02:00`` value, which is exactly the state §2 forbids — and
    which a store's expiry index would then be computed from. ``MemoryIngestor``
    converts; a canonical fake that merely accepted would certify a consumer
    against state the production writer refuses.
    """
    store = FakeMemoryStore(now=_fixed_now)
    berlin = timezone(timedelta(hours=2))
    writer = FakeMemoryWriter(
        store=store,
        policy=FakeMemoryPolicy(MemoryDecisionKind.STORE_TEMPORARY, ttl=timedelta(days=1)),
        now=lambda: datetime(2026, 6, 1, 2, tzinfo=berlin),
    )

    await writer.ingest(_proposal("pref-1"))

    stored = await store.get("pref-1")
    assert stored is not None
    assert stored.expires_at == datetime(2026, 6, 2, tzinfo=UTC)
    assert stored.expires_at.tzinfo is UTC


async def test_an_unrepresentable_temporary_ttl_is_the_subsystems_error() -> None:
    """A ttl past the representable date range fails the way the real one fails.

    ``MemoryIngestor`` translates the ``OverflowError`` into a
    ``MemoryStoreError`` at this boundary; a fake leaking the arithmetic error
    would have a consumer handling the wrong exception in production.
    """
    store = FakeMemoryStore(now=_fixed_now)
    writer = FakeMemoryWriter(
        store=store,
        policy=FakeMemoryPolicy(MemoryDecisionKind.STORE_TEMPORARY, ttl=timedelta.max),
        now=_fixed_now,
    )

    with pytest.raises(MemoryStoreError, match="overflows"):
        await writer.ingest(_proposal("pref-1"))

    assert await store.export() == []


def _inferred(record_id: str, *, validity: Validity | None = None) -> PreferenceMemory:
    """A supersedable conflict for ``_proposal``'s content, optionally windowed."""
    content = "prefers concise emails"
    return PreferenceMemory(
        id=record_id,
        content=content,
        preference=content,
        validity=validity if validity is not None else Validity(),
        provenance=Provenance(
            source=MemorySource.INFERRED, confidence=0.6, last_updated=_fixed_now()
        ),
    )


#: The lifecycle fields the fold case below gives its two records **distinctly**,
#: so which record each one came from is asserted rather than defaulted (#745): with
#: the two agreeing, the case passes whichever record the fold took them from.
#: **Both ends of each window differ**, not only `valid_from`: the assertions compare
#: whole `Validity` values, and with a shared `valid_until` a fold that took the
#: target's start and the incoming record's end would compare equal and pass while
#: moving when the surviving belief stops being live.
#:
#: Chosen against `_fixed_now` (2026-06-01), the store's clock and the writer's —
#: the windows open before it and both close and expire after it, so both records
#: are readable throughout and a missing survivor means the fold got the rule wrong.
_TARGET_WINDOW = Validity(
    valid_from=datetime(2026, 2, 1, tzinfo=UTC), valid_until=datetime(2027, 6, 1, tzinfo=UTC)
)
_TARGET_EXPIRES_AT = datetime(2027, 9, 1, tzinfo=UTC)
_TARGET_WHEN = datetime(2026, 1, 1, tzinfo=UTC)
_INCOMING_WINDOW = Validity(
    valid_from=datetime(2026, 3, 1, tzinfo=UTC), valid_until=datetime(2027, 3, 1, tzinfo=UTC)
)
_INCOMING_EXPIRES_AT = datetime(2027, 5, 1, tzinfo=UTC)
_INCOMING_WHEN = datetime(2026, 5, 1, tzinfo=UTC)

#: The **open** lifetime, run opposite a bounded one on the *surviving* side of each
#: arm, exactly as in `test_ingest.py`. Two bounded lifetimes show the fold picks the
#: right record but not that it picks at all: a fold coalescing the two
#: (`target.expires_at or incoming.expires_at`) is indistinguishable from one
#: selecting while both sides are truthy, and would retire an open-ended belief on a
#: date nothing set for it.
_OPEN_LIFETIME = (Validity(), None)


@pytest.mark.parametrize(
    ("target_window", "target_expiry"),
    [(_TARGET_WINDOW, _TARGET_EXPIRES_AT), _OPEN_LIFETIME],
    ids=["bounded-target", "open-target"],
)
async def test_a_derived_reinforcement_of_an_attested_record_corroborates_it(
    target_window: Validity, target_expiry: datetime | None
) -> None:
    """The fake folds ADR-0103 §6's pairing the way ``MemoryIngestor`` does (#646).

    Not contract — ADR-0103 §7 declines to promote §6 to the conformance suite, and
    ADR-0040 §5a keeps how confidence combines unasserted — so the suite cannot
    hold the two copies together and this case does it instead. A fake that kept
    the old ``max`` would let an `orchestration` test see an ``OBSERVED`` survivor
    at 1.0, which production cannot write at all: ``Provenance`` refuses it
    (ADR-0077 §7) and the ingest writes nothing.

    **The lifecycle fields are part of what the two copies have to agree about**
    (#745), so the records carry distinct ones: the target's ``validity`` and
    ``expires_at`` survive, because they are the belief's own properties and §6
    gives the incoming record exactly two contributions, while ``last_updated``
    comes from the incoming record because it is transaction time (ADR-0045 §3)
    rather than a belief property. A fake that diverged here would hand a consumer
    a survivor with a lifetime production would not have written.

    Run at a bounded target lifetime and at an open one (:data:`_OPEN_LIFETIME`),
    so the case says the survivor's lifetime is *selected* rather than non-empty.
    """
    store = FakeMemoryStore(now=_fixed_now)
    await store.add(
        EpisodicMemory(
            id="cited-episode",
            content="the exchange the derived proposal rests on",
            occurred_at=_fixed_now(),
            provenance=Provenance(
                source=MemorySource.OBSERVED, confidence=0.6, last_updated=_fixed_now()
            ),
        )
    )
    imported = PreferenceMemory(
        id="imported",
        content="prefers concise emails, as the mail client has it",
        preference="prefers concise emails",
        validity=target_window,
        expires_at=target_expiry,
        provenance=Provenance(
            source=MemorySource.EXTERNAL,
            confidence=1.0,
            evidence=("t-ev",),
            last_updated=_TARGET_WHEN,
            attestation=Attestation(reported_by="mail:work", reported_at=_fixed_now()),
        ),
    )
    await store.add(imported)
    writer = FakeMemoryWriter(
        store=store, policy=FakeMemoryPolicy(MemoryDecisionKind.REINFORCE), now=_fixed_now
    )

    result = await writer.ingest(
        _proposal(
            "observed",
            evidence=("cited-episode",),
            validity=_INCOMING_WINDOW,
            expires_at=_INCOMING_EXPIRES_AT,
            last_updated=_INCOMING_WHEN,
        )
    )

    assert result.decision.kind is MemoryDecisionKind.REINFORCE
    assert result.record_id == "imported"
    survivor = await store.get("imported")
    assert survivor is not None
    assert survivor.provenance.source is MemorySource.EXTERNAL
    assert survivor.provenance.confidence == 1.0
    assert survivor.provenance.attestation == imported.provenance.attestation
    assert survivor.content == imported.content
    # The belief's own lifetime is the target's; the incoming record's is left
    # behind with its confidence and its text. At the open parameter this is the
    # stronger claim that nothing was filled in from the other side.
    assert survivor.validity == target_window
    assert survivor.expires_at == target_expiry
    assert set(survivor.provenance.evidence) == {"t-ev", "cited-episode"}
    # Transaction time is the incoming record's: the store has just changed its
    # mind about this belief, and keeping `_TARGET_WHEN` would deny that.
    assert survivor.provenance.last_updated == _INCOMING_WHEN


@pytest.mark.parametrize(
    ("incoming_window", "incoming_expiry"),
    [(_INCOMING_WINDOW, _INCOMING_EXPIRES_AT), _OPEN_LIFETIME],
    ids=["bounded-incoming", "open-incoming"],
)
async def test_an_attested_reinforcement_of_a_derived_record_folds_as_it_always_did(
    incoming_window: Validity, incoming_expiry: datetime | None
) -> None:
    """The fake leaves the reverse pairing alone too (ADR-0103 §6, #733, #745).

    The mirror of ``test_ingest.py``'s case of the same name, and it is what makes
    the corroboration case above discriminating rather than merely green: **both**
    arms keep somebody's window and expiry, so "the target's survive" is a claim
    about the arm ADR-0103 §6 rules and says nothing on its own. Pinned on this copy
    of the fold and not only on ``MemoryIngestor``'s because the conformance suite
    holds neither — it pins ``REINFORCE``'s id and its evidence union, and ADR-0040
    §5a leaves the rest of the fold to `memory` — so a fake that regressed here
    would hand an `orchestration` test a survivor with a lifetime production would
    not have written, and nothing else would notice.

    ``last_updated`` is the one field the two arms agree on: transaction time on
    both (ADR-0045 §3).

    Parametrized on the same axis as the corroboration case, moved to the side that
    survives *here*: an open incoming record must leave the survivor open rather
    than let the target's bounded lifetime stand in.
    """
    store = FakeMemoryStore(now=_fixed_now)
    target = PreferenceMemory(
        id="observed",
        content="prefers concise emails, as we have inferred it",
        preference="prefers concise emails",
        validity=_TARGET_WINDOW,
        expires_at=_TARGET_EXPIRES_AT,
        provenance=Provenance(
            source=MemorySource.OBSERVED,
            confidence=0.9,
            evidence=("t-ev",),
            last_updated=_TARGET_WHEN,
        ),
    )
    await store.add(target)
    # An `EXTERNAL` proposal, so `_corroborates` is false in the other direction:
    # the target is the `DERIVED` one here. It carries its own `Attestation`
    # because the `ATTESTED` band must (ADR-0092 §1) — which is also why the fold
    # takes the incoming attestation on this arm and could not on the other.
    incoming = MemoryUpdateProposal(
        proposed=PreferenceMemory(
            id="imported",
            content="prefers concise emails",
            preference="prefers concise emails",
            validity=incoming_window,
            expires_at=incoming_expiry,
            provenance=Provenance(
                source=MemorySource.EXTERNAL,
                confidence=0.5,
                last_updated=_INCOMING_WHEN,
                attestation=Attestation(reported_by="mail:work", reported_at=_fixed_now()),
            ),
        ),
        rationale="because",
        sensitivity=DataTier.PERSONAL,
    )
    writer = FakeMemoryWriter(
        store=store, policy=FakeMemoryPolicy(MemoryDecisionKind.REINFORCE), now=_fixed_now
    )

    result = await writer.ingest(incoming)

    assert result.decision.kind is MemoryDecisionKind.REINFORCE
    assert result.record_id == "observed"
    survivor = await store.get("observed")
    assert survivor is not None
    # Newer content wins on this arm, and the confidence is still the maximum...
    assert survivor.provenance.source is MemorySource.EXTERNAL
    assert survivor.provenance.confidence == 0.9
    assert survivor.content == incoming.proposed.content
    # ...and the lifetime that comes with it is the incoming record's, both ends of
    # the window and the expiry.
    assert survivor.validity == incoming_window
    assert survivor.expires_at == incoming_expiry
    assert survivor.provenance.last_updated == _INCOMING_WHEN  # as on the other arm


async def test_supersede_refuses_a_future_dated_target_without_writing() -> None:
    """The fake carries the same refusal as ``MemoryIngestor`` (ADR-0080 §3).

    A producer-set ``valid_from`` at or after the writer's clock would close to an
    empty/inverted window the durable store rejects on decode, so the fake refuses
    before the write rather than let a consumer's test pass on state the production
    writer could not persist.
    """
    store = FakeMemoryStore(now=lambda: datetime(2026, 10, 1, tzinfo=UTC))
    await store.add(
        PreferenceMemory(
            id="existing",
            content="prefers concise emails",  # matches `_proposal`, so it is a conflict
            preference="prefers concise emails",
            validity=Validity(valid_from=datetime(2026, 9, 1, tzinfo=UTC)),  # after _fixed_now
            provenance=Provenance(
                source=MemorySource.INFERRED, confidence=0.6, last_updated=_fixed_now()
            ),
        )
    )
    before = await store.export()
    writer = FakeMemoryWriter(
        store=store, policy=FakeMemoryPolicy(MemoryDecisionKind.SUPERSEDE), now=_fixed_now
    )

    with pytest.raises(MemoryStoreError, match="valid_from"):
        await writer.ingest(_proposal("correction"))

    assert await store.export() == before  # fail-closed: nothing written, target untouched


async def test_supersede_never_extends_a_targets_existing_window() -> None:
    """The fake keeps a target's earlier ``valid_until`` — retirement never resurrects.

    Mirrors ``MemoryIngestor``: a target self-closing before the writer clock keeps
    that earlier end (``min``), so a fake regressing to a bare ``valid_until = now``
    that pushed the end out is caught.
    """
    already_closes = datetime(2026, 3, 1, tzinfo=UTC)  # before the writer's 2026-06-01 clock
    store = FakeMemoryStore(now=lambda: datetime(2026, 2, 1, tzinfo=UTC))
    await store.add(
        PreferenceMemory(
            id="existing",
            content="prefers concise emails",
            preference="prefers concise emails",
            validity=Validity(valid_until=already_closes),
            provenance=Provenance(
                source=MemorySource.INFERRED, confidence=0.6, last_updated=_fixed_now()
            ),
        )
    )
    writer = FakeMemoryWriter(
        store=store, policy=FakeMemoryPolicy(MemoryDecisionKind.SUPERSEDE), now=_fixed_now
    )

    result = await writer.ingest(_proposal("correction"))

    assert result.decision.kind is MemoryDecisionKind.SUPERSEDE
    retired = next(record for record in await store.export() if record.id == "existing")
    assert retired.validity.valid_until == already_closes  # not extended to the writer clock


async def test_supersede_refuses_a_target_whose_window_opens_at_the_close() -> None:
    """ADR-0080 §3's tie, on the fake: ``[F, F)`` is empty, so it refuses.

    The future-dated case above plants ``valid_from`` strictly *after* the writer's
    clock, so it still holds if the check is weakened from ``end <= valid_from`` to
    ``end <``; under that weakening this one is *retained* carrying the empty window
    — ``model_copy(update=...)`` builds it without re-running ``Validity``'s
    validator — and a consumer's test would pass on a record SQLite could not decode.
    A second, ordinary conflict is planted so the assertion is ADR-0080 §6's: every
    record in the retirement set is byte-identical afterwards.
    """
    store = FakeMemoryStore(now=lambda: datetime(2026, 7, 1, tzinfo=UTC))
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
        await writer.ingest(_proposal("correction"))

    assert await store.export() == before
    assert await store.get("corrected") is None


class _AdvancingClock:
    """Records every reading and returns a later instant each time.

    ADR-0080 §7's instrument for what the shared suite cannot express, since it
    fixes no writer clock: that the close instant is read **once** per ingest.
    Equality across the retired records alone is satisfied by a writer re-sampling a
    *constant* clock; equality plus advancing is satisfied by one ignoring its
    injected clock. The call count and the first-value identity rule out both.
    """

    def __init__(self) -> None:
        self.readings: list[datetime] = []

    def __call__(self) -> datetime:
        reading = _fixed_now() + timedelta(hours=len(self.readings))
        self.readings.append(reading)
        return reading


async def test_a_multi_target_supersede_reads_its_close_instant_exactly_once() -> None:
    """One close instant for the whole retirement set (ADR-0080 §1), on the fake.

    A per-target reading would let one atomic batch record two different close
    times for one ruling, and a fake that did it would diverge from
    ``MemoryIngestor`` on exactly the axis ADR-0080 §7 promoted to the suite.
    """
    store = FakeMemoryStore(now=lambda: datetime(2026, 1, 1, tzinfo=UTC))
    for stale_id in ("first", "second", "third"):
        await store.add(_inferred(stale_id))
    clock = _AdvancingClock()
    writer = FakeMemoryWriter(
        store=store,
        policy=FakeMemoryPolicy(MemoryDecisionKind.SUPERSEDE),
        now=clock,
        id_factory=lambda: "corrected",
    )

    result = await writer.ingest(_proposal("correction"))

    assert result.decision.kind is MemoryDecisionKind.SUPERSEDE
    assert len(clock.readings) == 1
    exported = {record.id: record for record in await store.export()}
    ends = {exported[stale_id].validity.valid_until for stale_id in ("first", "second", "third")}
    assert ends == {clock.readings[0]}


async def test_supersede_hiding_is_read_time_relative() -> None:
    """The fake's retirement is hidden read-time-relatively, as ``MemoryIngestor``'s is.

    Mirrors ``test_ingest.py``: ``valid_until`` is the writer's close instant, so the
    retired target is hidden from ``get``/``search`` only once the store's read clock
    reaches it. A store clock behind the close transiently still returns it
    (documented, not a bug); ``export`` keeps it at either clock. Pins the property on
    the canonical fake so a duplicate stamping the wrong close instant is caught.
    """
    read_at = [datetime(2026, 1, 1, tzinfo=UTC)]  # store read clock, mutable; starts BEHIND close
    store = FakeMemoryStore(now=lambda: read_at[0])
    await store.add(
        PreferenceMemory(
            id="existing",
            content="prefers concise emails",  # matches `_proposal`, so it is a conflict
            preference="prefers concise emails",
            provenance=Provenance(
                source=MemorySource.INFERRED, confidence=0.6, last_updated=_fixed_now()
            ),
        )
    )
    writer = FakeMemoryWriter(
        store=store, policy=FakeMemoryPolicy(MemoryDecisionKind.SUPERSEDE), now=_fixed_now
    )

    result = await writer.ingest(_proposal("correction"))
    assert result.decision.kind is MemoryDecisionKind.SUPERSEDE
    new_id = result.record_id
    assert new_id is not None

    # Read behind the close (2026-01-01 < the writer's 2026-06-01 close): still visible.
    assert await store.get("existing") is not None
    assert any(r.id == "existing" for r in await store.search("prefers concise emails"))

    # Advance the store's read clock to the close instant: now hidden.
    read_at[0] = datetime(2026, 6, 1, tzinfo=UTC)
    assert await store.get("existing") is None
    assert all(r.id != "existing" for r in await store.search("prefers concise emails"))

    # export keeps the retired target regardless of its validity window (both
    # records here are non-expired, so both appear).
    assert {r.id for r in await store.export()} == {"existing", new_id}


class _GatedStore(FakeMemoryStore):
    """A store that holds the absence selection open, so a test can interleave."""

    def __init__(self) -> None:
        super().__init__(now=_gated_now)
        self.selecting = asyncio.Event()
        self.may_select = asyncio.Event()
        self.may_select.set()

    async def list_beliefs(
        self,
        *,
        bands: Sequence[BeliefBand] | None = None,
        kinds: Sequence[MemoryKind] | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[MemoryRecord]:
        self.selecting.set()
        await self.may_select.wait()
        return await super().list_beliefs(bands=bands, kinds=kinds, limit=limit, offset=offset)


def _gated_now() -> datetime:
    return datetime(2026, 6, 1, tzinfo=UTC)


def _intruder() -> MemoryUpdateProposal:
    """An ordinary write that must not slip inside the reading's hold."""
    return MemoryUpdateProposal(
        proposed=PreferenceMemory(
            id="intruder",
            content="an unrelated preference",
            preference="an unrelated preference",
            provenance=Provenance(
                source=MemorySource.OBSERVED, confidence=0.6, last_updated=_gated_now()
            ),
        ),
        rationale="because",
        sensitivity=DataTier.PERSONAL,
    )


async def test_the_fake_serialises_a_covered_reading_against_other_writes() -> None:
    """ADR-0115 §3, proved against **this** implementation's own mechanism (§7).

    §7 keeps the serialisation off the shared suite because it is not observable
    through the Protocol — which is exactly why each implementation owes its own
    proof, the fake included. Without one, deleting this fake's lock would leave the
    shared contract and the production test green while every consumer that reaches
    for the canonical double got a subject whose isolation is imaginary: a
    concurrent ``ingest`` could land between a covered reading's selection and its
    closes, and the stale reconciliation would retire a record just updated.
    """
    store = _GatedStore()
    writer = FakeMemoryWriter(store=store, policy=FakeMemoryPolicy(), now=_gated_now)
    reading = SourceReading(
        source="calendar:work",
        read_at=_gated_now(),
        coverage=ReadCoverage(covers_until=_gated_now() + timedelta(days=30)),
    )

    store.may_select.clear()
    covered = asyncio.create_task(writer.ingest_reading(reading))
    await store.selecting.wait()

    competing = asyncio.create_task(writer.ingest(_intruder()))
    for _ in range(10):
        await asyncio.sleep(0)
    assert not competing.done(), "an ingest interleaved with the reading's read-modify-write"

    store.may_select.set()
    assert list(await covered) == []
    await competing


# --- ADR-0110 §3 condition 3, over this implementation's own selection --------

#: The reader identity the condition-3 cases below attest their records to.
_READER = "calendar:work"

#: What the covered reading in those cases declares it exhausted. Open at the
#: start for the reason a forward-looking read is: it has nothing to say about
#: where an entry *began*, and closing that end would exclude everything already
#: in progress.
_COVERAGE = ReadCoverage(covers_until=_fixed_now() + timedelta(days=30))


def _reported(record_id: str, *, extent: ReportedExtent | None = None) -> MemoryRecord:
    """A live attested belief with a **fully open** envelope window.

    Which is the shape ADR-0117 §4 wants a conforming producer's proposals in:
    the belief is on the read path, visible to conflict detection and enumerable,
    and where its entry lies is stated by the extent or by nothing at all.
    """
    text = f"the entry {record_id} names"
    return PreferenceMemory(
        id=record_id,
        content=text,
        preference=text,
        validity=Validity(),
        provenance=Provenance(
            source=MemorySource.EXTERNAL,
            confidence=0.6,
            last_updated=_fixed_now(),
            attestation=Attestation(reported_by=_READER, reported_at=_fixed_now(), extent=extent),
        ),
    )


async def _read_over(store: FakeMemoryStore) -> None:
    """One covered reading that reports nothing, through the public member."""
    writer = FakeMemoryWriter(store=store, policy=FakeMemoryPolicy(), now=_fixed_now)
    await writer.ingest_reading(
        SourceReading(source=_READER, read_at=_fixed_now(), coverage=_COVERAGE)
    )


@pytest.mark.parametrize(
    ("extent", "closes", "why"),
    [
        (
            ReportedExtent(extends_until=_fixed_now() + timedelta(days=1)),
            True,
            "the source said where it lies and the read exhausted that region",
        ),
        (
            ReportedExtent(extends_until=_fixed_now() + timedelta(days=90)),
            False,
            "an entry reaching past the horizon was not wholly looked at",
        ),
        (
            ReportedExtent(),
            False,
            "an unbounded extent end needs an unbounded coverage end",
        ),
        (None, False, "no extent states no position, so no reading exhausted it"),
    ],
    ids=["inside", "overhangs", "unbounded", "none"],
)
async def test_condition_three_is_decided_by_the_extent(
    extent: ReportedExtent | None, closes: bool, why: str
) -> None:
    """ADR-0117 §9's second clause, for **this** implementation (ADR-0115 §7).

    §7 leaves "each of ADR-0110 §3's other conditions independently prevents a
    close" to each writer's own tests, and ADR-0117 §9 corrects the carrier without
    moving the allocation. The fake duplicates the rule rather than importing it
    (golden rule 1), so a divergence here would be silent: the fake would keep
    demoting on one carrier while ``MemoryIngestor`` demoted on another, and the
    shared suite would drive two different rules while reporting one.

    The ``None`` row is §3's own second sentence, which §9 obliges each
    implementation to state: a record whose attestation declares no extent is
    demotable by no reading, whatever its envelope validity window.
    """
    store = FakeMemoryStore(now=_fixed_now)
    await store.add(_reported("subject", extent=extent))

    await _read_over(store)

    assert (await store.get("subject") is None) is closes, why


async def test_a_bounded_envelope_window_does_not_substitute_for_an_extent() -> None:
    """The carrier moved rather than widened (ADR-0117 §3).

    A record bounded exactly as ADR-0110 §3 originally asked — ``valid_until``
    inside the coverage — is demotable by nothing, because the window is no longer
    consulted. Pinned separately from the ``None`` row above because a fake that
    accepted *either* carrier would pass that row and this is what catches it.
    """
    store = FakeMemoryStore(now=_fixed_now)
    bounded = _reported("bounded-but-silent").model_copy(
        update={"validity": Validity(valid_until=_fixed_now() + timedelta(days=1))}
    )
    await store.add(bounded)

    await _read_over(store)

    assert await store.get(bounded.id) is not None
