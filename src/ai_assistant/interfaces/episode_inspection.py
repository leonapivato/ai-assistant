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
    from ai_assistant.core.types import (
        ActivationUnderstanding,
        EpisodePage,
        EpisodeProcessingRecord,
        EpisodeSummary,
        StoryHeader,
    )

#: The label an open episode carries in place of its absent end fields (ADR-0286 §11).
#: A record is open while its status is ``None`` (§1), so its status, reason and end
#: time are absent because its pass has not ended, not because the record lacks them:
#: ``unavailable`` stays the label of an episode with no processing record (ADR-0275
#: §11:5), and this one says the pass is still running.
IN_PROGRESS = "in progress, not yet ended"


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
    """Render the engine's order, exact addresses, and explicit continuation.

    A row carries no response line: ADR-0284 §4:1 removes ``response_kind``, the
    summary's one fact saying whether its episode sent a response, and §4:3 has the
    CLI read no field that section removes. The detail view carries the label.

    An open episode's row says it is in progress in place of its absent status
    (ADR-0286 §11).
    """
    if not page.items:
        console.print("No live episodes matched.")
    for item in page.items:
        fields = "".join(f"\n  {label}: {value}" for label, value in summary_fields(item))
        console.print(
            f"Episode {json.dumps(item.position.episode_id, ensure_ascii=False)}{fields}",
            markup=False,
            emoji=False,
            highlight=False,
            soft_wrap=True,
        )
    if page.next_cursor is not None:
        console.print(f"Next cursor: {page.next_cursor}", markup=False, emoji=False, soft_wrap=True)
        console.print("Use --cursor with the same channel and status filters.")
    _retention_notice(console)


def summary_fields(item: EpisodeSummary) -> tuple[tuple[str, str], ...]:
    """The labelled facts a listing row states after its episode id, in its order.

    One source for the episode list's row and the story view's one-line activation
    member (ADR-0289 §5:2), so the two cannot state different facts about one
    episode. An open episode's processing reads in progress (ADR-0286 §11).
    """
    channel = (
        "unavailable"
        if item.channel is None
        else f"{item.channel.channel_type}/{item.channel.instance_id}"
    )
    return (
        ("Occurred", item.position.occurred_at.isoformat()),
        ("Activation", item.activation_id or "unavailable"),
        ("Channel", f"{channel}; modality: {item.modality.value}"),
        ("Processing", _summary_status(item)),
    )


def _summary_status(item: EpisodeSummary) -> str:
    """Label a row's processing status, reading openness as the summary carries it.

    A summary with a processing record and no status is an open episode's, since a
    record is open exactly while its status is ``None`` (ADR-0286 §1); one with no
    processing record has no status to state (ADR-0275 §11:5).
    """
    if item.status is not None:
        return item.status.value
    return IN_PROGRESS if item.has_processing_record else "unavailable"


def _response_label(record: EpisodicMemory) -> str:
    """Label an episode by whether it sent a response (ADR-0284 §4:3).

    On a processing-record episode ``outcome`` is the text the activation sent back
    on its channel, or ``None`` where it sent none (§4:1). An episode without a
    processing record is ``unavailable``: its ``outcome`` is not a response sent on a
    channel, so whether it has one is not something the record states.

    An open episode with no response yet is ``none yet``: the stage that produces
    one, or the freezing write, may still append it (ADR-0286 §4).
    """
    if record.processing_record is None:
        return "unavailable"
    if record.outcome is not None:
        return "sent"
    return "none yet" if record.processing_record.is_open else "none"


def _retention_notice(console: Console) -> None:
    console.print(
        "Retention expiry, where a retention window is set, removes an episode from live "
        "memory; explicit forgetting deletes it."
    )


def render_detail(
    console: Console,
    record: EpisodicMemory,
    *,
    stories: tuple[StoryHeader, ...] | None,
) -> None:
    """Distinguish processing status from goal achievement and playback.

    An open episode is labelled in progress in place of its absent status, reason
    and end time (ADR-0286 §11), and each section it may still grow says so.

    Args:
        console: Where to render.
        record: The verified record.
        stories: The stories the episode's activation belongs to directly, as the
            engine answered them, or ``None`` where the episode has no activation to
            ask about. Rendered as one line, saying ``none`` for an activation that
            belongs to no story (ADR-0289 §5:3).
    """
    processing = record.processing_record
    if processing is None:
        activation = status = reason = "unavailable"
    elif processing.status is None or processing.reason is None:
        # ADR-0286 §1: an open record's status, reason and end time are all None.
        activation, status, reason = processing.activation_id, IN_PROGRESS, IN_PROGRESS
    else:
        activation = processing.activation_id
        status, reason = processing.status.value, processing.reason.value
    console.print(
        f"Episode {json.dumps(record.id, ensure_ascii=False)}\n"
        f"Activation: {activation}\n"
        f"Processing: {status}\n"
        f"Reason: {reason}\n"
        f"Response: {_response_label(record)}\n"
        f"Stories: {_stories_label(stories)}",
        markup=False,
        emoji=False,
        highlight=False,
        soft_wrap=True,
    )
    console.print(
        "\n".join(_stage_lines(processing)),
        markup=False,
        emoji=False,
        highlight=False,
        soft_wrap=True,
    )
    console.print("Processing status does not report goal achievement or audio playback.")
    console.print(
        "\n".join(_recall_lines(processing)),
        markup=False,
        emoji=False,
        highlight=False,
        soft_wrap=True,
    )
    console.print(
        "\n".join(_understanding_lines(processing)),
        markup=False,
        emoji=False,
        highlight=False,
        soft_wrap=True,
    )
    _retention_notice(console)
    console.print(
        json.dumps(record.model_dump(mode="json"), ensure_ascii=False, indent=2),
        markup=False,
        emoji=False,
        highlight=False,
        soft_wrap=True,
    )


def _stories_label(stories: tuple[StoryHeader, ...] | None) -> str:
    """Name the stories an activation belongs to directly, in the engine's order.

    ``unavailable`` where the episode has no processing record, so no activation a
    story could hold; ``none`` where the activation belongs to no story.
    """
    if stories is None:
        return "unavailable"
    if not stories:
        return "none"
    return ", ".join(_quoted(story.story_id) for story in stories)


def _quoted(text: str) -> str:
    """Show record text exactly, so a line break in it cannot pose as a rendered line."""
    return json.dumps(text, ensure_ascii=False)


def _stage_lines(processing: EpisodeProcessingRecord | None) -> list[str]:
    """Render the stage record the processing record carries (ADR-0280 §7), deriving none.

    Each entry's stage, the rule that made it due (for the end entry, the rule that
    ended the pass), its outcome and its duration, in the record's order. Where
    entries were elided, the count stands at the gap: ADR-0280 §6 keeps the first
    half of the bound and the last, so the gap falls at the middle of what is kept.
    """
    if processing is None:
        return ["Stages: unavailable"]
    if not processing.stages:
        return [f"Stages: {_none_recorded(processing)}"]
    lines = ["Stages:"]
    gap = len(processing.stages) // 2
    for index, entry in enumerate(processing.stages):
        if processing.stages_elided and index == gap:
            lines.append(f"  ... {processing.stages_elided} elided")
        seconds = (entry.ended_at - entry.started_at).total_seconds()
        lines.append(
            f"  {entry.stage.value} (due: {entry.due.value}): {entry.outcome.value}, {seconds:.3f}s"
        )
    return lines


def _recall_lines(processing: EpisodeProcessingRecord | None) -> list[str]:
    """Render the recall result the processing record carries (ADR-0281 §6), deriving none.

    Its outcome, and each kept item's kind, provenance and excerpt in recall's order.
    ``none recorded`` where recall made no decision on the pass — a resume, a pass
    that ended before recall, or one where it was not wired. Item ids and each item's
    structured origin stay in the ``--json`` detail.
    """
    if processing is None:
        return ["Recall: unavailable"]
    if processing.recall is None:
        return [f"Recall: {_none_recorded(processing)}"]
    lines = [f"Recall: {processing.recall.outcome.value}"]
    lines.extend(
        f"  {item.kind.value} ({item.provenance.value}): {_quoted(item.excerpt)}"
        for item in processing.recall.items
    )
    return lines


def _understanding_lines(processing: EpisodeProcessingRecord | None) -> list[str]:
    """Render the retained understanding the record carries (ADR-0276 §7), deriving none.

    Per retained version, in the record's order: its number, producer, meaning and
    ground, each reference's phrase and referent kinds, each relationship's statement
    and ground, and each unresolved matter; and the omission value or elided count
    where the record carries one. Referent ids, sources and excerpts stay in the
    ``--json`` detail.
    """
    if processing is None:
        return ["Understanding: unavailable"]
    if processing.understanding_omitted is not None:
        return [f"Understanding: not recorded ({processing.understanding_omitted.value})"]
    if not processing.understanding and not processing.understanding_elided:
        # Only an open record reaches here: a frozen one carries a non-empty
        # understanding or an omission, and an open one carries no omission (ADR-0286 §1).
        return [f"Understanding: {_none_recorded(processing)}"]
    lines: list[str] = []
    if processing.understanding_elided:
        lines.append(f"Understanding versions elided: {processing.understanding_elided}")
    for version in processing.understanding:
        lines.extend(_version_lines(version))
    return lines


def _none_recorded(processing: EpisodeProcessingRecord) -> str:
    """Say a section is empty, and on an open record that its pass may still fill it."""
    return "none recorded yet" if processing.is_open else "none recorded"


def _version_lines(version: ActivationUnderstanding) -> list[str]:
    lines = [
        f"Understanding v{version.version} ({version.producer.value})",
        f"  Meaning ({version.meaning_ground.value}): {_quoted(version.meaning)}",
    ]
    for reference in version.references:
        kinds = ", ".join(referent.kind for referent in reference.referents) or "none"
        lines.append(f"  Reference {_quoted(reference.phrase)}; referent kinds: {kinds}")
    lines.extend(
        f"  Relationship ({relationship.ground.value}): {_quoted(relationship.statement)}"
        for relationship in version.relationships
    )
    for matter in version.unresolved:
        lines.append(f"  Unresolved: {_quoted(matter.matter)}")
        lines.append(f"    Why it matters: {_quoted(matter.why_it_matters)}")
    return lines
