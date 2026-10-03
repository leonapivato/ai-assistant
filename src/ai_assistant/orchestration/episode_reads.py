"""Episode reads: inspection fitted to the payload limit, and the open-episode filter.

Inspection is ADR-0275's. ADR-0286 §6:4 adds the one rule a by-id read that feeds a
model applies: an open episode is an id with no record.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ai_assistant.core.episode_encoding import encode_cursor
from ai_assistant.core.types import (
    ChannelIdentity,
    EpisodeChunk,
    EpisodeCursor,
    EpisodePage,
    EpisodicMemory,
    ProcessingStatus,
)
from ai_assistant.orchestration.payloads import canonical_payload, check_payload

if TYPE_CHECKING:
    from collections.abc import Mapping

    from ai_assistant.core.types import MemoryRecord


def is_open_episode(record: object) -> bool:
    """Whether ``record`` is an open episode (ADR-0286 §1), which no model is shown."""
    return (
        isinstance(record, EpisodicMemory)
        and record.processing_record is not None
        and record.processing_record.is_open
    )


def without_open_episodes(found: Mapping[str, MemoryRecord]) -> dict[str, MemoryRecord]:
    """``found`` as a reader that feeds a model takes it (ADR-0286 §6:4).

    A ``get_many`` reaches open episodes as it reaches any other (§6:5); a reader
    whose records reach a model treats each as an id with no record, so it is left
    out of the mapping exactly as a missing id is.
    """
    return {key: record for key, record in found.items() if not is_open_episode(record)}


def fit_page(
    page: EpisodePage,
    *,
    channel: ChannelIdentity | None,
    status: ProcessingStatus | None,
    max_bytes: int,
) -> EpisodePage:
    """Return the largest leading prefix with a cursor that resumes after it."""
    if len(canonical_payload(page)) <= max_bytes:
        return page
    for count in range(len(page.items) - 1, 0, -1):
        items = page.items[:count]
        fitted = EpisodePage(
            items=items,
            next_cursor=encode_cursor(
                EpisodeCursor(after=items[-1].position, channel=channel, status=status)
            ),
        )
        if len(canonical_payload(fitted)) <= max_bytes:
            return fitted
    # The original oversized value gives the ordinary structured size error.
    check_payload(page, max_bytes=max_bytes, subject="the result of episodes()")
    raise AssertionError("an oversized page was unexpectedly admitted")


def fit_chunk(chunk: EpisodeChunk | None, *, max_bytes: int) -> EpisodeChunk | None:
    """Shorten content without changing its version or losing continuation bytes."""
    if len(canonical_payload(chunk)) <= max_bytes:
        return chunk
    if chunk is None or not chunk.text:
        check_payload(chunk, max_bytes=max_bytes, subject="the result of episode_chunk()")
        raise AssertionError("an oversized empty result was unexpectedly admitted")
    best: EpisodeChunk | None = None
    low, high = 1, len(chunk.text) - 1
    while low <= high:
        count = (low + high) // 2
        candidate = chunk.model_copy(
            update={"text": chunk.text[:count], "next_offset": chunk.offset + count}
        )
        if len(canonical_payload(candidate)) <= max_bytes:
            best = candidate
            low = count + 1
        else:
            high = count - 1
    if best is not None:
        return best
    check_payload(chunk, max_bytes=max_bytes, subject="the result of episode_chunk()")
    raise AssertionError("an oversized chunk was unexpectedly admitted")
