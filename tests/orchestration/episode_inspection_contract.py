"""Shared owner episode inspection obligations from ADR-0275 §§10-11."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from ai_assistant.core.errors import (
    OversizedValueError,
    StaleEpisodeReadError,
    TranscriptArchiveError,
)
from ai_assistant.core.types import (
    ChannelContext,
    ChannelIdentity,
    EpisodeProcessingRecord,
    EpisodeResponseKind,
    EpisodicMemory,
    ExchangeDisposition,
    MemorySource,
    ProcessingReason,
    ProcessingStatus,
    Provenance,
    RecordedChannelTrigger,
    RecordedTextInput,
    TranscriptEntry,
)
from ai_assistant.orchestration.payloads import canonical_payload

if TYPE_CHECKING:
    from ai_assistant.core.protocols import AssistantEngine
    from ai_assistant.testing import FakeMemoryStore, FakeTranscriptArchive

INSPECTION_LIMIT = 1024
INSPECTION_AT = datetime(2026, 9, 20, tzinfo=UTC)
_CHANNEL = ChannelIdentity(channel_type="informational_event", instance_id="source")


@dataclass(frozen=True)
class EpisodeInspectionSubject:
    """An engine and its injected store, for mutations between public reads."""

    engine: AssistantEngine
    memory: FakeMemoryStore
    archive: FakeTranscriptArchive


def _episode(record_id: str, *, activation: bool = False) -> EpisodicMemory:
    return EpisodicMemory(
        id=record_id,
        content='exact café 🍵\\"' * 100,
        occurred_at=INSPECTION_AT,
        provenance=Provenance(
            source=MemorySource.OBSERVED, confidence=0.9, last_updated=INSPECTION_AT
        ),
        processing_record=EpisodeProcessingRecord(
            activation_id="activation",
            started_at=INSPECTION_AT,
            ended_at=INSPECTION_AT,
            trigger=RecordedChannelTrigger(
                target=_CHANNEL,
                channel=_CHANNEL,
                payload=RecordedTextInput(text=" exact input "),
                context=ChannelContext(),
                conversation=None,
                reply=None,
            ),
            status=ProcessingStatus.FAILED,
            reason=ProcessingReason.PROCESSING_FAILED,
            response_kind=EpisodeResponseKind.NONE,
            model_eligible=False,
        )
        if activation
        else None,
    )


class EpisodeInspectionContract:
    """The same live, bounded reads through the engine, fake and wire client."""

    @pytest.fixture
    def episode_inspection(self) -> EpisodeInspectionSubject:
        """Override with an implementation at INSPECTION_LIMIT and a fixed store clock."""
        raise NotImplementedError

    async def test_episode_pages_preserve_exact_ids_and_make_progress(
        self, episode_inspection: EpisodeInspectionSubject
    ) -> None:
        subject = episode_inspection
        ids = ("", " a ", "a", "é", *(f"row-{n:02}" for n in range(20)))
        for record_id in ids:
            await subject.memory.add(_episode(record_id))
        page = await subject.engine.episodes(limit=100)
        assert 0 < len(page.items) < len(ids)
        seen: list[str] = []
        while True:
            assert len(canonical_payload(page)) <= INSPECTION_LIMIT
            assert page.items
            for item in page.items:
                assert not item.has_processing_record
                assert item.activation_id is None
                assert item.status is None
                seen.append(item.position.episode_id)
            if page.next_cursor is None:
                break
            page = await subject.engine.episodes(cursor=page.next_cursor, limit=100)
        assert seen == sorted(ids, reverse=True)

    async def test_episode_filters_include_ineligible_and_bind_size_cut_cursors(
        self, episode_inspection: EpisodeInspectionSubject
    ) -> None:
        subject = episode_inspection
        for n in range(10):
            await subject.memory.add(_episode(f"row-{n}", activation=True))
        await subject.memory.add(_episode("other-producer"))
        page = await subject.engine.episodes(channel=_CHANNEL, status=ProcessingStatus.FAILED)
        assert page.items
        assert page.next_cursor is not None
        assert all(item.status is ProcessingStatus.FAILED for item in page.items)
        with pytest.raises(ValueError, match="cursor"):
            await subject.engine.episodes(cursor=page.next_cursor)
        with pytest.raises(ValueError, match="cursor"):
            await subject.engine.episodes(
                channel=_CHANNEL, status=ProcessingStatus.FAILED, cursor=page.next_cursor + "="
            )
        rest = await subject.engine.episodes(
            channel=_CHANNEL, status=ProcessingStatus.FAILED, cursor=page.next_cursor
        )
        assert rest.items[0].position.episode_id < page.items[-1].position.episode_id

    @pytest.mark.parametrize("record_id", ["", " a ", "é"])
    async def test_episode_detail_fits_escaped_wrapper_and_reassembles_exactly(
        self, episode_inspection: EpisodeInspectionSubject, record_id: str
    ) -> None:
        subject = episode_inspection
        record = _episode(record_id, activation=True)
        await subject.memory.add(record)
        stored = await subject.memory.get(record_id)
        assert stored is not None
        first = await subject.engine.episode_chunk(record_id)
        assert first is not None
        assert first.next_offset is not None
        parts: list[str] = []
        current = first
        while True:
            assert current.episode_id == record_id
            assert current.version == first.version
            assert current.total_bytes == first.total_bytes
            assert current.offset == sum(len(part) for part in parts)
            assert current.text
            assert len(canonical_payload(current)) <= INSPECTION_LIMIT
            parts.append(current.text)
            if current.next_offset is None:
                break
            following = await subject.engine.episode_chunk(
                record_id, version=first.version, offset=current.next_offset
            )
            assert following is not None
            current = following
        encoded = "".join(parts)
        assert encoded.isascii()
        assert hashlib.sha256(encoded.encode()).hexdigest() == first.version
        assert len(encoded) == first.total_bytes
        assert json.loads(encoded) == stored.model_dump(mode="json")
        final = await subject.engine.episode_chunk(
            record_id, version=first.version, offset=first.total_bytes
        )
        assert final is not None
        assert final.text == ""
        assert final.next_offset is None
        assert await subject.memory.get(record_id) == stored

    async def test_episode_detail_rereads_after_annotation_deletion_and_expiry(
        self, episode_inspection: EpisodeInspectionSubject
    ) -> None:
        subject = episode_inspection
        record = _episode("record")
        await subject.memory.add(record)
        first = await subject.engine.episode_chunk(record.id, max_bytes=10)
        assert first is not None
        await subject.memory.add(record.model_copy(update={"topics": ("tea",)}))
        with pytest.raises(
            StaleEpisodeReadError, match=r"^episode changed during detail inspection$"
        ):
            await subject.engine.episode_chunk(record.id, version=first.version, offset=10)
        await subject.memory.delete(record.id)
        assert (
            await subject.engine.episode_chunk(record.id, version=first.version, offset=10) is None
        )
        await subject.memory.add(
            record.model_copy(update={"expires_at": INSPECTION_AT - timedelta(seconds=1)})
        )
        assert await subject.engine.episode_chunk(record.id) is None
        empty = await subject.engine.episodes()
        assert empty.items == ()
        assert empty.next_cursor is None

    async def test_episode_oversized_first_row_is_not_skipped(
        self, episode_inspection: EpisodeInspectionSubject
    ) -> None:
        subject = episode_inspection
        await subject.memory.add(_episode("z" * 900))
        await subject.memory.add(_episode("a"))
        with pytest.raises(OversizedValueError):
            await subject.engine.episodes()

    @pytest.mark.parametrize("limit", [0, 101, True])
    async def test_episode_invalid_page_limits_are_refused(
        self, episode_inspection: EpisodeInspectionSubject, limit: int
    ) -> None:
        before = episode_inspection.memory.resource_log.visits
        with pytest.raises(ValueError, match="episode limit"):
            await episode_inspection.engine.episodes(limit=limit)
        assert episode_inspection.memory.resource_log.visits == before

    @pytest.mark.parametrize("offset", [-1, 1, True, 2**63])
    async def test_episode_invalid_versionless_offsets_are_refused(
        self, episode_inspection: EpisodeInspectionSubject, offset: int
    ) -> None:
        before = episode_inspection.memory.resource_log.visits
        with pytest.raises(ValueError, match="episode"):
            await episode_inspection.engine.episode_chunk("", offset=offset)
        assert episode_inspection.memory.resource_log.visits == before

    async def test_episode_detail_refuses_when_no_positive_progress_fits(
        self, episode_inspection: EpisodeInspectionSubject
    ) -> None:
        record_id = "z" * 900
        await episode_inspection.memory.add(_episode(record_id))
        before = episode_inspection.memory.resource_log.visits
        with pytest.raises(OversizedValueError):
            await episode_inspection.engine.episode_chunk(record_id)
        # Its argument fits: refusal is the result wrapper, after a live read.
        assert episode_inspection.memory.resource_log.visits == before + 1

    @pytest.mark.parametrize("max_bytes", [0, 65537, True])
    async def test_episode_detail_invalid_byte_bounds_precede_store_io(
        self, episode_inspection: EpisodeInspectionSubject, max_bytes: int
    ) -> None:
        before = episode_inspection.memory.resource_log.visits
        with pytest.raises(ValueError, match="episode"):
            await episode_inspection.engine.episode_chunk("", max_bytes=max_bytes)
        assert episode_inspection.memory.resource_log.visits == before

    @pytest.mark.parametrize("version", ["", "abc", "A" * 64])
    async def test_episode_detail_invalid_versions_precede_store_io(
        self, episode_inspection: EpisodeInspectionSubject, version: str
    ) -> None:
        before = episode_inspection.memory.resource_log.visits
        with pytest.raises(ValueError, match="episode"):
            await episode_inspection.engine.episode_chunk("", version=version)
        assert episode_inspection.memory.resource_log.visits == before

    async def test_episode_offset_past_live_encoding_is_a_value_error(
        self, episode_inspection: EpisodeInspectionSubject
    ) -> None:
        subject = episode_inspection
        await subject.memory.add(_episode("record", activation=True))
        first = await subject.engine.episode_chunk("record", max_bytes=1)
        assert first is not None
        with pytest.raises(ValueError, match="offset"):
            await subject.engine.episode_chunk(
                "record", version=first.version, offset=first.total_bytes + 1
            )
        # Missing wins before the length check, as it does for every live read.
        await subject.memory.delete("record")
        assert (
            await subject.engine.episode_chunk(
                "record", version=first.version, offset=first.total_bytes + 1
            )
            is None
        )

    @pytest.mark.parametrize("present", [False, True])
    async def test_engine_forget_destroys_archive_and_removes_live_inspection(
        self, episode_inspection: EpisodeInspectionSubject, present: bool
    ) -> None:
        subject = episode_inspection
        await subject.memory.add(_episode("record", activation=True))
        first = await subject.engine.episode_chunk("record", max_bytes=1)
        assert first is not None
        if not present:
            await subject.memory.delete("record")
        subject.archive.hold(
            TranscriptEntry(
                address="record",
                conversation_id="conversation",
                ordinal=1,
                occurred_at=INSPECTION_AT,
                asked="archived request",
                replied="archived reply",
                disposition=ExchangeDisposition.NO_ACTION_NEEDED,
            )
        )

        assert await subject.engine.forget("record") is present

        assert await subject.archive.entry("record") is None
        assert (await subject.engine.episodes()).items == ()
        assert await subject.engine.episode_chunk("record", version=first.version, offset=1) is None

    async def test_engine_forget_keeps_episode_when_archive_destruction_fails(
        self, episode_inspection: EpisodeInspectionSubject
    ) -> None:
        subject = episode_inspection
        await subject.memory.add(_episode("record", activation=True))
        subject.archive.fail()

        with pytest.raises(TranscriptArchiveError):
            await subject.engine.forget("record")

        assert await subject.engine.episode_chunk("record") is not None
        assert [item.position.episode_id for item in (await subject.engine.episodes()).items] == [
            "record"
        ]

    @pytest.mark.parametrize("present", [False, True])
    async def test_episode_original_argument_bound_precedes_continuation_preflight(
        self, episode_inspection: EpisodeInspectionSubject, present: bool
    ) -> None:
        subject = episode_inspection
        record_id = "z" * 902
        if present:
            await subject.memory.add(_episode(record_id, activation=True))
        arguments = {
            "episode_id": record_id,
            "version": "0" * 64,
            "offset": 1,
            "max_bytes": 65536,
        }
        assert len(canonical_payload(arguments)) == INSPECTION_LIMIT + 1
        assert len(canonical_payload({**arguments, "offset": 0, "max_bytes": 1})) < INSPECTION_LIMIT
        before = subject.memory.resource_log.visits

        with pytest.raises(OversizedValueError):
            await subject.engine.episode_chunk(
                record_id, version="0" * 64, offset=1, max_bytes=65536
            )

        assert subject.memory.resource_log.visits == before
