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
effect record the plan store does not hold, a message call that sent nothing), or the
part's text was never kept (a speech input whose transcript was discarded).
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Final, assert_never

from ai_assistant.core.types import (
    ConfirmationPart,
    EpisodicMemory,
    EvidenceItemPart,
    InputPart,
    LegacyPart,
    Memory,
    MessageCallPart,
    ObserverInferencePart,
    PinPart,
    PlanningRound,
    RecordedSpeechInput,
    RecordedTextInput,
    RememberCallPart,
    RoundMessagePart,
    SupportPart,
    canonical_json_bytes,
    part_episode,
)
from ai_assistant.orchestration.planning import DELIBERATE_REPEAT, LOOKING_FOR
from ai_assistant.orchestration.remembering import (
    FACT_ARGUMENT,
    REMEMBER_CANDIDATE,
    STATEMENT_ARGUMENT,
)
from ai_assistant.orchestration.stories import episode_address

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from ai_assistant.core.types import (
        ActivationEffect,
        ApprovalRequest,
        EpisodeProcessingRecord,
        FrozenJson,
        ProposedCall,
    )

__all__ = [
    "INFERENCE_CONTENT",
    "PIN_CONTENT",
    "episodes_to_read",
    "part_content",
    "remember_activations",
    "requests_to_read",
]


#: What an observer's inference resolves to while its episode is held (ADR-0329 §9:7).
#: The part points at no text of the episode — the inference is the observer's reading
#: of the other supports added with it — so it is said for what it is, never as gone.
INFERENCE_CONTENT: Final = "my reading of the supports beside it, drawn looking back"

#: What a pin resolves to (ADR-0338 §4:4). The part points into no episode and copies
#: nothing of the pin, and the person-model store keeps a pin once it is removed
#: (§4:7), so the part always resolves: it is said for what it is, never as gone.
PIN_CONTENT: Final = "you pinned this wording to keep it in mind"


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


def requests_to_read(memories: Iterable[Memory]) -> tuple[str, ...]:
    """The approval requests resolving ``memories``' confirmations needs, once each.

    A confirmation of the request form names the request a tap approved, whose recorded
    call holds its statement (ADR-0361 §5:10): it is read from the plan store.

    Args:
        memories: The memories whose supports are being resolved.

    Returns:
        The request ids to read in one batch.
    """
    wanted: dict[str, None] = {}
    for memory in memories:
        for support in memory.supports:
            part = support.points_at
            if isinstance(part, ConfirmationPart) and part.request is not None:
                wanted[str(part.request)] = None
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


def part_content(  # noqa: C901, PLR0911, PLR0912 — one arm per part the part table names
    part: SupportPart,
    *,
    episodes: Mapping[str, EpisodicMemory],
    effects: Mapping[str, ActivationEffect],
    carried: Mapping[str, object] | None,
    requests: Mapping[str, ApprovalRequest] | None = None,
) -> str | None:
    """The readable content ``part`` points at, or ``None`` where it does not resolve.

    Args:
        part: The support's part.
        episodes: The episodes read for the page, by id.
        effects: The effect records read for the page's remember calls, by id.
        carried: A legacy support's carried record, as stored (§16:4).
        requests: The approval requests read for the page's confirmations of the request
            form, by id (:func:`requests_to_read`); one not given is gone.

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
        case MessageCallPart():
            return _sent(_processing(episodes.get(part.episode)), part.round, part.call_id)
        case EvidenceItemPart():
            return _evidence(_processing(episodes.get(part.episode)), part.digest, part.item)
        case ConfirmationPart():
            if episodes.get(part.episode) is None:
                return None
            if part.request is not None:
                # ADR-0361 §5:10: the approval's own episode, and the statement the
                # request's recorded call holds.
                held = None if requests is None else requests.get(str(part.request))
                return None if held is None else _requested(held)
            if part.question is None:  # pragma: no cover - one form is always set
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
            return _remembered(_round(processing, effect.round), effect)
        case ObserverInferencePart():
            return None if episodes.get(part.episode) is None else INFERENCE_CONTENT
        case PinPart():
            return PIN_CONTENT
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


def _sent(processing: EpisodeProcessingRecord | None, round_id: str, call_id: str) -> str | None:
    """The words one message call sent, as its entry holds them (ADR-0356 §13:2).

    ``None`` where the episode holds no entry for the call, or the entry holds no
    delivery: a message call refused, or come back before anything was sent (§8:4).
    """
    if processing is None:
        return None
    for entry in processing.call_records:
        if entry.round == round_id and entry.call_id == call_id:
            return None if entry.delivered is None else entry.delivered.words
    return None


def _evidence(processing: EpisodeProcessingRecord | None, digest: int, item: int) -> str | None:
    if processing is None or digest >= len(processing.digests):
        return None
    evidence = processing.digests[digest].evidence
    return evidence[item].text if item < len(evidence) else None


def _approved(processing: EpisodeProcessingRecord | None, round_id: str, part: int) -> str | None:
    """The statement the approved question part showed, from the asking round's record.

    The round keeps every call its message asked about, with the values it sends
    (ADR-0321 §2:8); the part numbers them from one. A remember's statement is the
    wording the user approved (§4:6), and so is a candidate's fact once ``remember``
    records candidates (ADR-0329 §5:5); a call carrying neither reads as the round's
    message, which asked the question.
    """
    round_ = _round(processing, round_id)
    if round_ is None or not 1 <= part <= len(round_.asked):
        return None
    values = round_.asked[part - 1].values
    for argument in (STATEMENT_ARGUMENT, FACT_ARGUMENT):
        statement = values.get(argument)
        if isinstance(statement, str) and statement:
            return statement
    return round_.text or None


def _requested(request: ApprovalRequest) -> str | None:
    """The statement an approved request's recorded call holds (ADR-0361 §5:10).

    The wording the person approved on the card, as ADR-0328 §4:6 compares it: a
    remember's statement, or a candidate's fact.
    """
    values = request.call.values
    for argument in (STATEMENT_ARGUMENT, FACT_ARGUMENT):
        statement = values.get(argument)
        if isinstance(statement, str) and statement:
            return statement
    return None


#: The arguments a proposed remember call carries that never reach acting's digest: the
#: two the hub fills (``system_supplied``, ADR-0254 §3), and the *looking for* argument
#: and *deliberate repeat* mark, removed before the call reaches acting (ADR-0306 §2:10).
_UNDIGESTED: Final = frozenset(
    {*REMEMBER_CANDIDATE.system_supplied, LOOKING_FOR, DELIBERATE_REPEAT}
)


def _remembered(round_: PlanningRound | None, effect: ActivationEffect) -> str | None:
    """The statement of the remember call one effect record claims.

    The effect record names its round and its capability, and carries the digest of the
    values acting ran the call with (ADR-0306 §5, §6): the round's call to that
    capability whose values give that digest is the call. Where no call's digest
    matches, one distinct statement among the round's calls to the capability is still
    the call's; where neither tells the calls apart, the part is left unresolved rather
    than resolved to another call's statement.
    """
    if round_ is None or effect.capability is None:
        return None
    candidates = [call for call in round_.calls if call.name == effect.capability]
    matched = {
        statement
        for call in candidates
        if _digest(call) == effect.values_digest and (statement := _statement(call)) is not None
    }
    if len(matched) == 1:
        return next(iter(matched))
    statements = {statement for call in candidates if (statement := _statement(call)) is not None}
    return next(iter(statements)) if len(statements) == 1 else None


def _statement(call: ProposedCall) -> str | None:
    statement = call.arguments.get(STATEMENT_ARGUMENT)
    return statement if isinstance(statement, str) and statement else None


def _digest(call: ProposedCall) -> str:
    """Acting's digest of a call's values (``acting.values_digest``), for a call with no binding.

    The canonical JSON of its arguments less those that never reach acting's digest,
    beside a ``null`` binding: a remember call leaves no hub, so carries none.
    """
    arguments = {key: value for key, value in call.arguments.items() if key not in _UNDIGESTED}
    document: FrozenJson = {"arguments": arguments, "binding": None}
    return hashlib.sha256(canonical_json_bytes(document)).hexdigest()
