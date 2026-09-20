"""Fit live episode inspection results to the public payload limit (ADR-0275)."""

from __future__ import annotations

from ai_assistant.core.episode_encoding import encode_cursor
from ai_assistant.core.types import (
    ChannelIdentity,
    EpisodeChunk,
    EpisodeCursor,
    EpisodePage,
    ProcessingStatus,
)
from ai_assistant.orchestration.payloads import canonical_payload, check_payload


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
