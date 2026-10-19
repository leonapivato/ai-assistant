"""A support's part, resolved to the readable content it points at (ADR-0328 §15:2).

The single-memory view carries each support with "the part it points at resolved to
readable content or shown as gone". The part is one part of one episode (§4's part
table), so it is resolved against that part's own fields on the episode's record, never
against the episode's search text (ADR-0284 §7), which is an index over the whole
activation rather than the content of any one part of it.

**Pure, and in its own module.** The engine reads what this needs in one batch per page
(the episodes, the asking activations' episodes, and the effect records remember calls
are claimed under) and hands it here; nothing here reads a store or a clock, so the
façade's reads stay batched (ADR-0086 §6) and every rule below is testable on values.

A part that does not resolve is ``None``, which every surface shows as gone and never
as evidence (§15:7, ADR-0073 §4's floor): the episode is gone, or it holds no such part
(a position past its end, a round it never recorded, a digest item it never kept, an
effect record the plan store does not hold), or the part's text was never kept (a
speech input whose transcript was discarded).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, assert_never

from ai_assistant.core.types import (
    ConfirmationPart,
    EpisodicMemory,
    EvidenceItemPart,
    InputPart,
    LegacyPart,
    Memory,
    PlanningRound,
    RecordedSpeechInput,
    RecordedTextInput,
    RememberCallPart,
    RoundMessagePart,
    SupportPart,
    part_episode,
)
from ai_assistant.orchestration.remembering import STATEMENT_ARGUMENT
from ai_assistant.orchestration.stories import episode_address

if TYPE_CHECKING:
    from collections.abc import Collection, Iterable, Mapping

    from ai_assistant.core.types import ActivationEffect, EpisodeProcessingRecord

__all__ = [
    "episodes_to_read",
    "part_content",
    "remember_activations",
]


def episodes_to_read(memories: Iterable[Memory]) -> tuple[str, ...]:
    """Every episode resolving ``memories``' parts needs, in first-seen order, once each.

    The episode each part points into, and, for a confirmation, the asking activation's
    episode, whose round holds the question part the yes approved (§4's part table).

    Args:
        memories: The memories whose supports are being resolved.

    Returns:
        The episode ids to read in one batch.
    """
    wanted: dict[str, None] = {}
    for memory in memories:
        for support in memory.supports:
            part = support.points_at
            if (episode := part_episode(part)) is not None:
                wanted[episode] = None
            if isinstance(part, ConfirmationPart):
                wanted[episode_address(part.asking_activation)] = None
    return tuple(wanted)


def remember_activations(
    memories: Iterable[Memory], episodes: Mapping[str, EpisodicMemory]
) -> tuple[str, ...]:
    """The activations whose effect records resolving ``memories``' remember calls needs.

    A remember call is addressed by its episode and the effect record it was claimed
    under (§4's part table, ADR-0306 §5:3); the record lives in the plan store, keyed by
    the activation, which the episode's processing record names.

    Args:
        memories: The memories whose supports are being resolved.
        episodes: The episodes read for them.

    Returns:
        The activation ids, once each.
    """
    wanted: dict[str, None] = {}
    for memory in memories:
        for support in memory.supports:
            part = support.points_at
            if not isinstance(part, RememberCallPart):
                continue
            record = episodes.get(part.episode)
            if record is not None and record.processing_record is not None:
                wanted[record.processing_record.activation_id] = None
    return tuple(wanted)


def part_content(  # noqa: PLR0911 — one arm per part §4's part table names
    part: SupportPart,
    *,
    episodes: Mapping[str, EpisodicMemory],
    effects: Mapping[str, ActivationEffect],
    carried: Mapping[str, object] | None,
    wordings: Collection[str],
) -> str | None:
    """The readable content ``part`` points at, or ``None`` where it does not resolve.

    Args:
        part: The support's part.
        episodes: The episodes read for the page, by id.
        effects: The effect records read for the page's remember calls, by id.
        carried: A legacy support's carried record, as stored (§16:4).
        wordings: The wordings of the memories carrying this part, which tell apart two
            remember calls one round made under the capability one effect record names.

    Returns:
        The part's content, or ``None`` for gone.
    """
    match part:
        case LegacyPart():
            content = (carried or {}).get("content")
            return content if isinstance(content, str) and content else None
        case InputPart():
            return _input(episodes.get(part.episode), part.message)
        case RoundMessagePart():
            round_ = _round(_processing(episodes.get(part.episode)), part.round)
            return None if round_ is None or not round_.text else round_.text
        case EvidenceItemPart():
            return _evidence(_processing(episodes.get(part.episode)), part.digest, part.item)
        case ConfirmationPart():
            if episodes.get(part.episode) is None:
                return None
            asking = episodes.get(episode_address(part.asking_activation))
            return _approved(_processing(asking), part.question.round, part.question.part)
        case RememberCallPart():
            processing = _processing(episodes.get(part.episode))
            effect = effects.get(part.effect)
            if processing is None or effect is None:
                return None
            if effect.activation_id != processing.activation_id or effect.round is None:
                return None
            return _remembered(_round(processing, effect.round), effect.capability, wordings)
        case _:  # pragma: no cover - exhaustive over the discriminated union
            assert_never(part)


def _processing(episode: EpisodicMemory | None) -> EpisodeProcessingRecord | None:
    return None if episode is None else episode.processing_record


def _input(episode: EpisodicMemory | None, message: int | None) -> str | None:
    """The input as a whole, or one of its trigger's recorded messages."""
    if episode is None:
        return None
    processing = episode.processing_record
    if processing is None:
        # An episode recorded with no processing record carries its exchange only as its
        # content: that is the input as it holds it, and it holds no messages apart.
        return (episode.content or None) if message is None else None
    trigger = processing.trigger
    if message is not None:
        messages = trigger.messages
        return messages[message].text if message < len(messages) else None
    payload = trigger.payload
    match payload:
        case RecordedTextInput():
            return payload.text or None
        case RecordedSpeechInput():
            return payload.transcript or None
        case _:  # pragma: no cover - exhaustive over the discriminated union
            assert_never(payload)


def _round(processing: EpisodeProcessingRecord | None, round_id: str) -> PlanningRound | None:
    if processing is None:
        return None
    return next((one for one in processing.rounds if one.id == round_id), None)


def _evidence(processing: EpisodeProcessingRecord | None, digest: int, item: int) -> str | None:
    if processing is None or digest >= len(processing.digests):
        return None
    evidence = processing.digests[digest].evidence
    return evidence[item].text if item < len(evidence) else None


def _approved(processing: EpisodeProcessingRecord | None, round_id: str, part: int) -> str | None:
    """The statement the approved question part showed, from the asking round's record.

    The round keeps every call its message asked about, with the values it sends
    (ADR-0321 §2:8); the part numbers them from one. A remember's statement is the
    wording the user approved (§4:6); a call carrying none reads as the round's message,
    which asked the question.
    """
    round_ = _round(processing, round_id)
    if round_ is None or not 1 <= part <= len(round_.asked):
        return None
    statement = round_.asked[part - 1].values.get(STATEMENT_ARGUMENT)
    if isinstance(statement, str) and statement:
        return statement
    return round_.text or None


def _remembered(
    round_: PlanningRound | None, capability: str | None, wordings: Collection[str]
) -> str | None:
    """The statement of the remember call one effect record claims, where one is told apart.

    The effect record names its round and its capability, not the call (ADR-0306 §6), so
    the round's calls to that capability are the candidates. One distinct statement among
    them is the call's; among several, the one a memory carrying the part is worded as
    (§13:2 makes the wording the statement). Where neither tells them apart, the part is
    not resolved rather than resolved to another call's statement.
    """
    if round_ is None or capability is None:
        return None
    statements = {
        statement
        for call in round_.calls
        if call.name == capability
        and isinstance(statement := call.arguments.get(STATEMENT_ARGUMENT), str)
        and statement
    }
    if len(statements) == 1:
        return next(iter(statements))
    matching = statements.intersection(wordings)
    return next(iter(matching)) if len(matching) == 1 else None
