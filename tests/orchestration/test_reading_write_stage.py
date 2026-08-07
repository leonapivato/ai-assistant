"""The consumer half of ADR-0115: one call, one snapshot, and what a raise leaves.

§7 assigns three obligations to the consumer rather than to the shared writer suite,
because none of them is observable through the `MemoryWriter` seam: whether the
*whole* reading was forwarded and forwarded once (§2), whether the stage enqueued
from its own entry snapshot (§5), and what a mid-reading raise leaves behind (§5's
residue, issue #814).

The middle one is the sharp one. `MemoryIngestResult` carries no proposal, so the
obvious stage implementation zips results against `reading.proposals` — and if that
is the *caller's* reading rather than a snapshot, a `DataTier.SECRET` proposal
flipped to `PERSONAL` mid-call is ruled correctly and then queued, which is
ADR-0004 §3's "never in a database" reached through the one filter written to
prevent it.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from ai_assistant.core.errors import MemoryStoreError
from ai_assistant.core.types import (
    Attestation,
    DataTier,
    MemoryDecision,
    MemoryDecisionKind,
    MemoryIngestResult,
    MemorySource,
    MemoryUpdateProposal,
    PreferenceMemory,
    Provenance,
    ReadCoverage,
    SourceReading,
)
from ai_assistant.orchestration.ingestion import IngestionStage
from ai_assistant.orchestration.writes import MemoryWriteStage
from ai_assistant.testing import (
    FakeDeferralStore,
    FakeReader,
    FakeSourceGrants,
    source_grant,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

_AT = datetime(2026, 6, 1, tzinfo=UTC)
_SOURCE = "calendar:work"
_COVERAGE = ReadCoverage(covers_until=_AT + timedelta(days=30))


def _proposal(record_id: str, *, tier: DataTier = DataTier.PERSONAL) -> MemoryUpdateProposal:
    return MemoryUpdateProposal(
        proposed=PreferenceMemory(
            id=record_id,
            content=f"what {record_id} says",
            preference=f"what {record_id} says",
            provenance=Provenance(
                source=MemorySource.EXTERNAL,
                confidence=0.6,
                last_updated=_AT,
                attestation=Attestation(reported_by=_SOURCE, reported_at=_AT),
            ),
        ),
        rationale="because",
        sensitivity=tier,
    )


def _reading(*proposals: MemoryUpdateProposal, coverage: ReadCoverage | None) -> SourceReading:
    return SourceReading(source=_SOURCE, read_at=_AT, proposals=proposals, coverage=coverage)


class _RecordingWriter:
    """A ``MemoryWriter`` recording what it was handed, and optionally suspending."""

    def __init__(self, *, defer: bool = False, raise_on: int | None = None) -> None:
        self.readings: list[SourceReading] = []
        self.entered = asyncio.Event()
        self.proceed = asyncio.Event()
        self.proceed.set()
        self._defer = defer
        self._raise_on = raise_on

    async def ingest(self, proposal: MemoryUpdateProposal) -> MemoryIngestResult:
        """Not exercised here; these cases are all about the reading-level seam."""
        raise NotImplementedError

    async def ingest_reading(self, reading: SourceReading) -> Sequence[MemoryIngestResult]:
        self.readings.append(reading)
        self.entered.set()
        await self.proceed.wait()
        results: list[MemoryIngestResult] = []
        for index, proposal in enumerate(reading.proposals):
            if self._raise_on is not None and index == self._raise_on:
                msg = "the store is broken"
                raise MemoryStoreError(msg)
            results.append(
                MemoryIngestResult(
                    record_id=None if self._defer else proposal.proposed.id,
                    decision=MemoryDecision(
                        kind=(
                            MemoryDecisionKind.ASK_USER
                            if self._defer
                            else MemoryDecisionKind.ACCEPT
                        ),
                        reason="scripted",
                    ),
                )
            )
        return results


def _stage(writer: _RecordingWriter) -> tuple[MemoryWriteStage, FakeDeferralStore]:
    deferrals = FakeDeferralStore(now=lambda: _AT)
    return (
        MemoryWriteStage(writer=writer, deferrals=deferrals),
        deferrals,
    )


# --- §2: the whole reading, forwarded once ----------------------------------


@pytest.mark.parametrize("coverage", [_COVERAGE, None], ids=["covered", "uncovered"])
async def test_the_reading_is_forwarded_whole_and_exactly_once(
    coverage: ReadCoverage | None,
) -> None:
    """§2, on both arms — a stage may not assemble a reading it did not receive.

    §1's signature already stops a caller pairing two readings' halves, because
    there is only one argument. What it cannot stop is a stage *synthesising* one:
    a covered reading carrying an empty proposal tuple is well-formed, and a writer
    handed it does exactly what ADR-0110 §3 requires — finds nothing present, and
    closes every covered record the source reported.
    """
    writer = _RecordingWriter()
    stage, _ = _stage(writer)
    reading = _reading(_proposal("a"), _proposal("b"), coverage=coverage)

    outcomes = await stage.write_reading(reading)

    assert len(writer.readings) == 1, "the reading must not be split across calls"
    forwarded = writer.readings[0]
    assert forwarded == reading, "a synthesised or re-assembled reading is refused"
    assert len(outcomes) == 2


# --- §5: the consumer's own snapshot ----------------------------------------


async def test_a_secret_flipped_mid_call_is_still_not_enqueued() -> None:
    """§5's snapshot, and the reason it is not belt-and-braces.

    The tier check runs *after* the writer returns. Without the stage's own entry
    snapshot it reads the caller's live proposal, so flipping ``sensitivity`` from
    ``SECRET`` to ``PERSONAL`` while the call is in flight has the ruling made on
    the secret (correctly, ``ASK_USER``) and the credential queued — ADR-0004 §3's
    "never in a database", through the one filter written to prevent it.
    """
    writer = _RecordingWriter(defer=True)
    stage, deferrals = _stage(writer)
    secret = _proposal("credential", tier=DataTier.SECRET)
    reading = _reading(secret, coverage=None)

    writer.proceed.clear()
    task = asyncio.create_task(stage.write_reading(reading))
    await writer.entered.wait()
    object.__setattr__(secret, "sensitivity", DataTier.PERSONAL)
    writer.proceed.set()
    outcomes = await task

    assert outcomes[0].admission is None, "a secret ruling is reported, never queued"
    assert await deferrals.pending() == []


async def test_a_payload_mutated_mid_call_is_enqueued_as_it_stood_at_entry() -> None:
    """§5's other half: the snapshot is used, and the question is **not** dropped.

    Dropping it is not an accepted outcome — a stage that skipped every mutated
    proposal would satisfy the secret case above while silently losing ordinary
    deferrals, which is the loss ADR-0078 §3 exists to prevent.
    """
    writer = _RecordingWriter(defer=True)
    stage, deferrals = _stage(writer)
    proposal = _proposal("ordinary")
    reading = _reading(proposal, coverage=None)

    writer.proceed.clear()
    task = asyncio.create_task(stage.write_reading(reading))
    await writer.entered.wait()
    object.__setattr__(proposal, "rationale", "tampered after the call began")
    writer.proceed.set()
    await task

    parked = await deferrals.pending()
    assert len(parked) == 1, "an ordinary deferral is queued, not dropped"
    assert parked[0].proposal.rationale == "because", "the entry snapshot is what is queued"


# --- §5's residue: what a mid-reading raise leaves (issue #814) --------------


async def test_a_raise_after_an_earlier_deferral_parks_nothing() -> None:
    """ADR-0115 §5's ruled residue, pinned as ruled rather than accidentally repaired.

    For a reading ``[A, B]`` where ``A`` defers and ``B`` raises, ``A``'s question is
    **not** parked. ADR-0078 §3's obligation is keyed on the stage *observing* a
    result and a raise produces none, so nothing is breached; the question is
    recovered by re-proposal at the next reading of the same source.

    It is pinned because an implementation that quietly kept the old per-proposal
    behaviour would queue ``A`` and pass every other case here (#814).
    """
    writer = _RecordingWriter(defer=True, raise_on=1)
    stage, deferrals = _stage(writer)
    reading = _reading(_proposal("a"), _proposal("b"), coverage=_COVERAGE)

    with pytest.raises(MemoryStoreError, match="the store is broken"):
        await stage.write_reading(reading)

    assert await deferrals.pending() == [], "no result was observed, so nothing is parked"


class _RecordingWriteStage:
    """A write stage that records the readings the ingestion stage forwards."""

    def __init__(self) -> None:
        self.readings: list[SourceReading] = []

    async def write_reading(self, reading: SourceReading) -> Sequence[object]:
        self.readings.append(reading)
        return []


@pytest.mark.parametrize("coverage", [_COVERAGE, None], ids=["covered", "uncovered"])
async def test_the_ingestion_stage_forwards_the_readers_own_reading(
    coverage: ReadCoverage | None,
) -> None:
    """§7 assigns §2's test to the **ingestion stage**, and this is it.

    The AST guard over ``IngestionStage.ingest`` proves only that ``write_reading``
    is awaited, and the write-stage cases above start one layer below — so a stage
    that later rebuilt a covered reading with an empty or mismatched proposal tuple
    would pass both while the writer closed every eligible belief for a coverage the
    reader never reported. That is the fabrication §2 exists to forbid, and the seam
    between the reader and the stage is the only place it is visible.
    """
    reader = FakeReader([_proposal("a"), _proposal("b")], name=_SOURCE)
    reading = await reader.read()
    scripted = _ScriptedReader(reading.model_copy(update={"coverage": coverage}))
    writes = _RecordingWriteStage()
    stage = IngestionStage(
        reader=scripted,
        # A recording stand-in for the write stage: `IngestionStage` names the
        # concrete class, so this is the one place a structural double needs saying.
        writes=writes,  # type: ignore[arg-type]  # structural write stage
        grants=FakeSourceGrants([source_grant(scripted.name)]),
    )

    await stage.ingest()

    assert len(writes.readings) == 1, "the reading must reach the writer exactly once"
    assert writes.readings[0] == scripted.returned, "not a reading the stage assembled"


class _ScriptedReader:
    """Returns one fixed reading, so a test can compare what the stage forwarded."""

    def __init__(self, reading: SourceReading) -> None:
        self.returned = reading

    @property
    def name(self) -> str:
        return self.returned.source

    async def read(self) -> SourceReading:
        return self.returned
