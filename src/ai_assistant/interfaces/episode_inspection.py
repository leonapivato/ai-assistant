"""Presentation and verified reassembly for owner episode inspection (ADR-0275)."""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING

from pydantic import ValidationError

from ai_assistant.core.types import EpisodicMemory
from ai_assistant.wire.errors import ProtocolError

if TYPE_CHECKING:
    from rich.console import Console

    from ai_assistant.core.protocols import AssistantEngine
    from ai_assistant.core.types import EpisodePage


async def read_detail(
    engine: AssistantEngine, episode_id: str
) -> tuple[str, EpisodicMemory] | None:
    """Collect one current version completely before exposing any of its content."""
    chunk = await engine.episode_chunk(episode_id)
    if chunk is None:
        return None
    version, total = chunk.version, chunk.total_bytes
    parts: list[str] = []
    offset = 0
    while True:
        if (
            chunk.episode_id != episode_id
            or chunk.version != version
            or chunk.total_bytes != total
            or chunk.offset != offset
            or not chunk.text.isascii()
        ):
            raise ProtocolError("inconsistent episode detail; incomplete content discarded")
        parts.append(chunk.text)
        offset += len(chunk.text)
        if chunk.next_offset is None:
            break
        if not chunk.text or chunk.next_offset != offset or offset >= total:
            raise ProtocolError("invalid episode continuation; incomplete content discarded")
        following = await engine.episode_chunk(episode_id, version=version, offset=offset)
        if following is None:
            return None
        chunk = following
    encoded = "".join(parts)
    if offset != total or hashlib.sha256(encoded.encode()).hexdigest() != version:
        raise ProtocolError("episode detail verification failed; incomplete content discarded")
    try:
        record = EpisodicMemory.model_validate_json(encoded)
    except ValidationError as exc:
        raise ProtocolError("invalid episode record; incomplete content discarded") from exc
    if record.id != episode_id:
        raise ProtocolError("episode detail address mismatch; incomplete content discarded")
    return encoded, record


def render_page(console: Console, page: EpisodePage) -> None:
    """Render the engine's order, exact addresses, and explicit continuation."""
    if not page.items:
        console.print("No live episodes matched.")
    for item in page.items:
        channel = (
            "unavailable"
            if item.channel is None
            else f"{item.channel.channel_type}/{item.channel.instance_id}"
        )
        console.print(
            f"Episode {json.dumps(item.position.episode_id, ensure_ascii=False)}\n"
            f"  Occurred: {item.position.occurred_at.isoformat()}\n"
            f"  Activation: {item.activation_id or 'unavailable'}\n"
            f"  Channel: {channel}; modality: {item.modality.value}\n"
            f"  Processing: {item.status.value if item.status else 'unavailable'}\n"
            f"  Response: {_response_label(item.response_kind)}",
            markup=False,
            highlight=False,
            soft_wrap=True,
        )
    if page.next_cursor is not None:
        console.print(f"Next cursor: {page.next_cursor}", markup=False, soft_wrap=True)
        console.print("Use --cursor with the same channel and status filters.")
    _retention_notice(console)


def _response_label(kind: str | None) -> str:
    return {
        None: "unavailable",
        "none": "no response",
        "conversation_reply": "conversational reply",
        "informational_summary": "informational summary",
    }[kind]


def _retention_notice(console: Console) -> None:
    console.print(
        "Retention expiry removes an episode from live memory; explicit forgetting also "
        "destroys its archived transcript. An archive may outlive an expired episode."
    )


def render_detail(console: Console, record: EpisodicMemory) -> None:
    """Distinguish processing status from goal achievement and playback."""
    processing = record.processing_record
    console.print(
        f"Episode {json.dumps(record.id, ensure_ascii=False)}\n"
        f"Activation: {processing.activation_id if processing else 'unavailable'}\n"
        f"Processing: {processing.status.value if processing else 'unavailable'}\n"
        f"Reason: {processing.reason.value if processing else 'unavailable'}\n"
        f"Response: {_response_label(processing.response_kind if processing else None)}",
        markup=False,
        highlight=False,
        soft_wrap=True,
    )
    console.print("Processing status does not report goal achievement or audio playback.")
    _retention_notice(console)
    console.print(
        json.dumps(record.model_dump(mode="json"), ensure_ascii=False, indent=2),
        markup=False,
        highlight=False,
        soft_wrap=True,
    )
