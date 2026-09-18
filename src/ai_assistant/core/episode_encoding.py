"""Canonical encoding and validation of episode inspection values (ADR-0275)."""

from __future__ import annotations

import base64
import binascii
import json
import re
from hashlib import sha256

from pydantic import BaseModel, TypeAdapter, ValidationError

from ai_assistant.core.errors import MemoryStoreError, StaleEpisodeReadError
from ai_assistant.core.types import (
    ChannelIdentity,
    EncodableText,
    EpisodeChunk,
    EpisodeCursor,
    EpisodePosition,
    EpisodeSummary,
    EpisodicMemory,
    MemoryRecord,
    ProcessingStatus,
)

_MAX_PAGE = 100
_MAX_CHUNK = 65536

_TEXT: TypeAdapter[str] = TypeAdapter(EncodableText)


def canonical_json(value: BaseModel) -> str:
    """Encode JSON-mode fields with the canonical inspection spelling."""
    return json.dumps(
        value.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def encode_cursor(cursor: EpisodeCursor) -> str:
    """Encode a validated position and filters as an unpadded opaque cursor."""
    return base64.urlsafe_b64encode(canonical_json(cursor).encode()).decode().rstrip("=")


def check_list(
    channel: ChannelIdentity | None,
    status: ProcessingStatus | None,
    cursor: str | None,
    limit: int,
) -> tuple[ChannelIdentity | None, ProcessingStatus | None, EpisodeCursor | None]:
    """Snapshot filters and reject invalid or mismatched cursors before store I/O."""
    if type(limit) is not int or not 1 <= limit <= _MAX_PAGE:
        msg = "episode limit must be an integer in [1, 100]"
        raise ValueError(msg)
    checked_channel = (
        None if channel is None else ChannelIdentity.model_validate_json(channel.model_dump_json())
    )
    checked_status = None if status is None else ProcessingStatus(status)
    if cursor is None:
        return checked_channel, checked_status, None
    parsed = None
    try:
        if not isinstance(cursor, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", cursor):
            raise ValueError
        raw = base64.b64decode(cursor + "=" * (-len(cursor) % 4), altchars=b"-_", validate=True)
        candidate = EpisodeCursor.model_validate_json(raw)
        if (
            encode_cursor(candidate) == cursor
            and candidate.channel == checked_channel
            and candidate.status == checked_status
        ):
            parsed = candidate
    except ValueError, ValidationError, binascii.Error:
        pass
    if parsed is None:
        msg = "invalid episode cursor or mismatched filters"
        raise ValueError(msg)
    return checked_channel, checked_status, parsed


def check_detail(episode_id: str, version: str | None, offset: int, max_bytes: int) -> None:
    """Refuse invalid detail arguments before a store lookup."""
    _TEXT.validate_python(episode_id)
    if type(offset) is not int or not 0 <= offset < 2**63:
        msg = "episode offset must be an integer in [0, 2**63)"
        raise ValueError(msg)
    if type(max_bytes) is not int or not 1 <= max_bytes <= _MAX_CHUNK:
        msg = "episode chunk size must be an integer in [1, 65536]"
        raise ValueError(msg)
    if version is None:
        if offset:
            msg = "a continuation offset requires an episode version"
            raise ValueError(msg)
    elif not isinstance(version, str) or not re.fullmatch(r"[0-9a-f]{64}", version):
        msg = "invalid episode version"
        raise ValueError(msg)


def position_of(record: EpisodicMemory) -> EpisodePosition:
    """Return the declared ordering fields without normalizing the address."""
    return EpisodePosition(occurred_at=record.occurred_at, episode_id=record.id)


def summary_of(record: EpisodicMemory) -> EpisodeSummary:
    """Project a record onto its inspection summary, preserving absent facts."""
    processing = record.processing_record
    return EpisodeSummary(
        position=position_of(record),
        activation_id=None if processing is None else processing.activation_id,
        channel=None if processing is None else processing.trigger.channel,
        modality=record.capture.modality,
        status=None if processing is None else processing.status,
        response_kind=None if processing is None else processing.response_kind,
        has_processing_record=processing is not None,
    )


def detail_of(
    record: EpisodicMemory,
    *,
    version: str | None,
    offset: int,
    max_bytes: int,
) -> EpisodeChunk:
    """Slice canonical detail after verifying its digest and current length."""
    try:
        validated = EpisodicMemory.model_validate_json(record.model_dump_json())
    except ValidationError as exc:
        msg = "invalid stored episode detail"
        raise MemoryStoreError(msg) from exc
    encoded = canonical_json(validated)
    digest = sha256(encoded.encode()).hexdigest()
    if version is not None and version != digest:
        raise StaleEpisodeReadError("episode changed during detail inspection")
    if offset > len(encoded):
        msg = "episode offset exceeds its current detail length"
        raise ValueError(msg)
    end = min(offset + max_bytes, len(encoded))
    return EpisodeChunk(
        episode_id=record.id,
        version=digest,
        offset=offset,
        text=encoded[offset:end],
        next_offset=None if end == len(encoded) else end,
        total_bytes=len(encoded),
    )


def admits_model_eligibility(record: MemoryRecord, requested: bool | None) -> bool:
    """Apply the declared eligibility axis, leaving non-episodic values unchanged."""
    if requested is None or not isinstance(record, EpisodicMemory):
        return True
    effective = record.processing_record is None or record.processing_record.model_eligible
    return effective == requested


def check_eligibility(value: object) -> None:
    """Refuse coercible values on the optional boolean query axis."""
    if value is not None and type(value) is not bool:
        msg = "episode_model_eligible must be a boolean or None"
        raise ValueError(msg)
