"""Canonical encoding of episode values: inspection, search text and projection.

Inspection is ADR-0275's. ADR-0284 adds the two derivations every reader of an
episode shares: :func:`episode_content`, its search text (§7), and
:func:`project_episode`, what a model is shown of it (§8), with the one table of
verdict phrases beside it.
"""

from __future__ import annotations

import base64
import binascii
import json
import re
from hashlib import sha256
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

from pydantic import BaseModel, TypeAdapter, ValidationError

from ai_assistant.core.errors import MemoryStoreError, StaleEpisodeReadError
from ai_assistant.core.types import (
    ChannelIdentity,
    ControllerStage,
    Disposition,
    EncodableText,
    EpisodeChunk,
    EpisodeCursor,
    EpisodePosition,
    EpisodeProjection,
    EpisodeSummary,
    EpisodicMemory,
    InputOrigin,
    MemoryRecord,
    ProcessingStatus,
    ProjectedText,
    RecordedActivationTrigger,
    RecordedChannelTrigger,
    RecordedTextInput,
    RouteOutcome,
    rests_on_recorded_external_content,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

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


# --- an episode's search text (ADR-0284 §7) ------------------------------------


def episode_content(record: EpisodicMemory) -> str:
    """The search text of an episode, derived from its processing record (ADR-0284 §7).

    **A recipe, not a ruling** (§7:4). Today it is the latest understanding's
    ``meaning``, or, where the activation has no understanding, one line of its
    status and reason; followed, on its own line, by the input text or transcript
    where the trigger's ``origin`` is ``user``. So a conversational episode is found
    by its sense and by the exact names and numbers in the user's words, an outside
    report by its sense alone, and an episode no stage understood by how it ended.

    **What it never includes** is §7:2's invariant: the input text of a trigger whose
    ``origin`` is ``outside``. An ``origin`` of ``None`` — a trigger recorded without
    one, or a resume, which has no input — contributes no words either: who sent
    them is unknown, so they are not taken for the user's.

    **An episode without a processing record** keeps the ``content`` its producer
    gave it, and this returns it unchanged: §7:1 makes the rule a function of the
    processing record and sets it on processing-record episodes alone, and ADR-0275
    §4:2's other producers compose their own. Returning it rather than refusing lets
    a re-derivation pass (§7:5) call this over every stored episode and rewrite
    nothing it does not own.

    Args:
        record: The episode. Its own ``content`` is read only where it has no
            processing record.

    Returns:
        The text to store as the episode's ``content``.
    """
    processing = record.processing_record
    if processing is None:
        return record.content
    if processing.understanding:
        lines = [processing.understanding[-1].meaning]
    else:
        lines = [f"status {processing.status.value}, reason {processing.reason.value}"]
    trigger = processing.trigger
    if isinstance(trigger, RecordedChannelTrigger) and trigger.origin is InputOrigin.USER:
        words = _input_text(trigger)
        if words is not None and words.strip():
            lines.append(words)
    return "\n".join(lines)


# --- the episode a model is shown (ADR-0284 §8) --------------------------------


#: ADR-0284 §8:6's phrase for each :class:`~ai_assistant.core.types.Disposition`:
#: the wording ADR-0221 §2's table gave the matching ``step_*`` member, byte for byte.
STEP_DISPOSITION_PHRASES: Final[Mapping[Disposition, str]] = MappingProxyType(
    {
        Disposition.EXECUTED: "the selected tool ran",
        Disposition.DENIED: "the action was refused by the permission policy",
        Disposition.AWAITING_CONFIRMATION: "the action was parked for the user to confirm",
        Disposition.NO_CAPABLE_TOOL: "no tool advertised the capability the step needed",
        Disposition.AMBIGUOUS_CAPABILITY: (
            "several tools advertised the capability, so none was chosen"
        ),
        Disposition.INVALID_PARAMETERS: (
            "the step's arguments did not fit the declared schema of any capable tool"
        ),
        Disposition.EGRESS_UNBINDABLE: (
            "the outbound call could not be described, so nothing was asked or sent"
        ),
        Disposition.EFFECT_ALREADY_CLAIMED: (
            "this goal had already claimed the act, so nothing was dispatched"
        ),
        Disposition.EFFECT_UNSCOPED: (
            "the plan did not say which act the step was, so nothing was dispatched"
        ),
    }
)

#: ADR-0284 §8:6's phrase for each :class:`~ai_assistant.core.types.RouteOutcome`:
#: the wording ADR-0221 §2's table gave the matching ``routed_*`` member, byte for byte.
#:
#: **Two mappings, never one keyed by both enums.** They are ``StrEnum`` s sharing
#: values — ``awaiting_confirmation`` and ``failed`` are members of each — and a
#: ``StrEnum`` member hashes and compares as its value, so one mapping would hold a
#: single phrase for both and render a parked route as a parked step, or the reverse.
ROUTE_OUTCOME_PHRASES: Final[Mapping[RouteOutcome, str]] = MappingProxyType(
    {
        RouteOutcome.PERFORMED: "the assistant performed the operation the user asked for",
        RouteOutcome.AWAITING_CONFIRMATION: "the operation was parked for the user to confirm",
        RouteOutcome.REFUSED: "the user declined, so the operation was not performed",
        RouteOutcome.AMBIGUOUS: "more than one record matched, so nothing was performed",
        RouteOutcome.AMBIGUOUS_TRUNCATED: (
            "more records matched than could be shown, so nothing was performed"
        ),
        RouteOutcome.NOT_FOUND: "nothing matched, so nothing was performed",
        RouteOutcome.UNRECORDED: "the decision could not be recorded, so nothing was performed",
        RouteOutcome.FAILED: "the operation was attempted and failed",
    }
)


def project_episode(
    record: EpisodicMemory, *, excerpt_chars: int, admit_outside_input: bool = False
) -> EpisodeProjection:
    """Project an episode onto what a model is shown of it (ADR-0284 §8:1-§8:2).

    Every model-facing rendering of a stored episode reads the episode through this
    and renders no other field of it (§8:3). The input and the response are cut to
    ``excerpt_chars`` characters and the cut is carried; a site with a tighter
    ceiling of its own applies it to what this returns (§8:7).

    The input is shown where the trigger's ``origin`` is ``user``, or where it is
    ``outside`` and ``admit_outside_input`` is set — which the understanding stage's
    episode window and its recalled episodes alone do (§8:5). An ``origin`` of
    ``None`` shows none. An episode with no processing record shows its ``content``
    as its input instead (§8:2), the one path on which a model is shown ``content``.

    Args:
        record: The stored episode, exactly as held.
        excerpt_chars: The bound, in characters, on the input and the response.
        admit_outside_input: Whether an ``outside`` input's text is shown.

    Returns:
        The projection.

    Raises:
        ValueError: If ``excerpt_chars`` is not an integer of at least 1.
    """
    if type(excerpt_chars) is not int or excerpt_chars < 1:
        msg = "the episode excerpt bound must be an integer of at least 1"
        raise ValueError(msg)
    response = _projected(record.outcome, excerpt_chars)
    external = rests_on_recorded_external_content(record.provenance)
    processing = record.processing_record
    if processing is None:
        return EpisodeProjection(
            occurred_at=record.occurred_at,
            capture_modality=record.capture.modality,
            input=_projected(record.content, excerpt_chars),
            response=response,
            derived_from_external=external,
        )
    trigger = processing.trigger
    origin = trigger.origin if isinstance(trigger, RecordedChannelTrigger) else None
    shown = origin is InputOrigin.USER or (origin is InputOrigin.OUTSIDE and admit_outside_input)
    latest = processing.understanding[-1] if processing.understanding else None
    return EpisodeProjection(
        occurred_at=record.occurred_at,
        channel=trigger.channel,
        origin=origin,
        input=_projected(_input_text(trigger), excerpt_chars) if shown else None,
        meaning=None if latest is None else latest.meaning,
        meaning_ground=None if latest is None else latest.meaning_ground,
        unresolved=() if latest is None else latest.unresolved,
        step_dispositions=tuple(
            entry.step_disposition
            for entry in processing.stages
            if entry.stage is ControllerStage.DRIVE and entry.step_disposition is not None
        ),
        route_outcomes=tuple(
            entry.route_outcome
            for entry in processing.stages
            if entry.stage is ControllerStage.ROUTING and entry.route_outcome is not None
        ),
        response=response,
        status=processing.status,
        reason=processing.reason,
        derived_from_external=external,
    )


def _input_text(trigger: RecordedActivationTrigger) -> str | None:
    """The trigger's exact payload text or transcript; a resume carries none."""
    if not isinstance(trigger, RecordedChannelTrigger):
        return None
    payload = trigger.payload
    if isinstance(payload, RecordedTextInput):
        return payload.text
    return payload.transcript


def _projected(text: str | None, bound: int) -> ProjectedText | None:
    """A bounded prefix of ``text`` and the length it was cut from."""
    if text is None:
        return None
    return ProjectedText(text=text[:bound], full_chars=len(text))
