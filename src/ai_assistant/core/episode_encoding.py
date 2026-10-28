"""Canonical encoding of episode values: inspection, search text and projection.

Inspection is ADR-0275's. ADR-0284 adds the two derivations every reader of an episode
shares: :func:`episode_content`, its search text (§7), and :func:`project_episode`, what
a model is shown of it (§8). ADR-0286 adds :func:`episode_extends`, the one test of
whether a revision of an open episode only extends the stored one (§3). ADR-0322 adds
the question's mark to the projection (§4:3), and :func:`question_marks`, which pairs
each mark with the round it was read from. ADR-0349 §6:7 extends the projection with
the peer view, another activation's own work as every share reads it.
"""

from __future__ import annotations

import base64
import binascii
import json
import re
from hashlib import sha256
from typing import TYPE_CHECKING, Final, overload

from pydantic import BaseModel, TypeAdapter, ValidationError

from ai_assistant.core.errors import MemoryStoreError, StaleEpisodeReadError
from ai_assistant.core.types import (
    ChannelIdentity,
    EncodableText,
    EpisodeChunk,
    EpisodeCursor,
    EpisodePosition,
    EpisodeProjection,
    EpisodeSummary,
    EpisodicMemory,
    InputOrigin,
    PeerEffect,
    PeerNotes,
    PeerView,
    ProcessingStatus,
    ProjectedEvidence,
    ProjectedRound,
    ProjectedText,
    RecordedChannelTrigger,
    RecordedSpeechInput,
    RecordedTextInput,
    ToolOutcome,
    rests_on_recorded_external_content,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from ai_assistant.core.types import (
        ActivationDigest,
        ActivationEffect,
        EpisodeProcessingRecord,
        JoinedInput,
        PlanningRound,
    )

_MAX_PAGE = 100
_MAX_CHUNK = 65536

_TEXT: TypeAdapter[str] = TypeAdapter(EncodableText)

#: What separates the messages of one held input in a peer view's text of it, as the
#: readers separate the messages they take in as one input.
_MESSAGE_SEPARATOR: Final = "\n\n"

#: The effect outcomes a peer view shows: done, and unknown (ADR-0349 §6:9).
_SHOWN_OUTCOMES: Final = frozenset({ToolOutcome.SUCCEEDED, ToolOutcome.INDETERMINATE})


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


# --- an episode's search text (ADR-0284 §7) ------------------------------------


def episode_content(record: EpisodicMemory) -> str:
    """The search text of an episode, derived from its processing record (ADR-0284 §7).

    **A recipe, not a ruling** (§7:4). Today it is the latest understanding's
    ``meaning``, or, where the activation has no understanding, one line of its
    status and reason; followed, on its own line, by the input text or transcript
    where the trigger's ``origin`` is ``user``. So a conversational episode is found
    by its sense and by the exact names and numbers in the user's words, an outside
    report by its sense alone, and an episode no stage understood by how it ended. An
    activation the Task Scheduler started, whose ``origin`` is ``assistant``, is found by
    its sense alone too: its input is the assistant's own instruction, never the user's
    words (ADR-0350 §6:3, §6:12).

    **What it never includes** is §7:2's invariant: the input text of a trigger whose
    ``origin`` is ``outside``.

    **An open episode's** search text is empty (ADR-0286 §1, superseding §7:1 in
    when): the freezing write derives it, and this returns ``""`` until then.

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
    if processing.status is None or processing.reason is None:
        return ""
    if processing.understanding:
        lines = [processing.understanding[-1].meaning]
    else:
        lines = [f"status {processing.status.value}, reason {processing.reason.value}"]
    trigger = processing.trigger
    if trigger.origin is InputOrigin.USER:
        words = _input_text(trigger)
        if words is not None and words.strip():
            lines.append(words)
    return "\n".join(lines)


# --- the episode a model is shown (ADR-0284 §8) --------------------------------


@overload
def project_episode(
    record: EpisodicMemory,
    *,
    excerpt_chars: int,
    admit_outside_input: bool = False,
    owner_records: bool = False,
    candidates: Sequence[str] = (),
) -> EpisodeProjection: ...


@overload
def project_episode(
    record: EpisodicMemory,
    *,
    excerpt_chars: int,
    owner_records: bool = False,
    effects: Sequence[ActivationEffect],
) -> PeerView: ...


def project_episode(  # noqa: PLR0913 — one read function, two views (ADR-0349 §6:7)
    record: EpisodicMemory,
    *,
    excerpt_chars: int,
    admit_outside_input: bool = False,
    owner_records: bool = False,
    candidates: Sequence[str] = (),
    effects: Sequence[ActivationEffect] | None = None,
) -> EpisodeProjection | PeerView:
    """Project an episode onto what a model is shown of it (ADR-0284 §8:1-§8:2).

    Every model-facing rendering of a stored episode reads the episode through this
    and renders no other field of it (§8:3). The input and the response are cut to
    ``excerpt_chars`` characters and the cut is carried; a site with a tighter
    ceiling of its own applies it to what this returns (§8:7).

    **Planning's rounds** (ADR-0307 §10) render under the reader's audience: each
    round's message, with the parts it asked about where it is a question (ADR-0322
    §4:3), and its episode notes with their mark only where
    ``owner_records`` says a record placed for the owner alone may be shown to this
    reader (ADR-0307 §4:4, §6:4). That placement holds for every reader of a stored
    episode (ADR-0312 §4:3), so the default withholds them; the round's message is
    the episode's own response and is shown wherever the episode is. Each is cut to
    ``excerpt_chars`` as the input is.

    **An episode's evidence** (ADR-0308 §5:5 to §5:6) renders each digest's items,
    in the order the digests were recorded, as each item's text and its mark and
    never its source label, which names a thing only in the activation that recorded
    it. Evidence is placed for the owner alone, as episode notes are, so it renders
    only where ``owner_records`` says so; the activation's own planning is shown its
    own evidence by the planning stage, never through this (ADR-0312 §4:1, §4:3).
    Each item is cut to ``excerpt_chars``.

    **An episode's pending candidates** (ADR-0329 §6:9) are the facts the caller
    hands in ``candidates``: which of the episode's ``remember`` calls are candidates
    still pending is read from the plan store, which this module does not reach, so
    the phases' glue selects them for planning's episode window and every other caller
    passes none. Each is cut to ``excerpt_chars``.

    The input is shown where the trigger's ``origin`` is ``user``, or where it is
    ``outside`` and ``admit_outside_input`` is set — which the understanding stage's
    episode window and its recalled episodes alone do (§8:5). It is never shown where the
    origin is ``assistant``: a scheduled task's instruction is not the user's words, and a
    reader that renders the input attributes it as theirs (ADR-0350 §6:12), so a reader
    attributes such an episode from its ``origin`` and its meaning alone. An episode with no
    processing record shows its ``content`` as its input instead (§8:2), the one path on
    which a model is shown ``content``. No stage verdict is shown (ADR-0318 §3:1).

    **The peer view** (ADR-0349 §6:7-§6:10) is the second view, returned where
    ``effects`` is given: another activation's own work, read by every share, and
    computed from two records alone, the activation's episode as stored, open or
    frozen, and its effect records, which orchestration reads from the plan store and
    hands in (§6:8). Of the episode it shows only what its stages appended when they
    ended, which is all a stored record holds, and of the effects only those whose
    outcome is written and is done or unknown. Its input is shown as this projection
    shows it with ``admit_outside_input`` false, cut to ``excerpt_chars``, and so is
    every input the activation holds beside it. Its latest meaning is shown, which a
    reader renders as provisional; its rounds' notes and its evidence under
    ``owner_records``, as here; and each effect shown as :class:`PeerEffect` says. A
    round's message is shown only through a message effect done or unknown, never from
    the round itself, so a message not yet sent is never shown (§6:8). Nothing else of
    the episode is: no recall, story link, failed call, draft, approval, call value or
    result (§6:10).

    Args:
        record: The stored episode, exactly as held.
        excerpt_chars: The bound, in characters, on the input, the response,
            each round's message and notes, and each evidence item.
        admit_outside_input: Whether an ``outside`` input's text is shown. Never set
            for the peer view.
        owner_records: Whether a record placed for the owner alone may be shown to
            this reader, which decides the episode notes and the evidence.
        candidates: The facts of the episode's pending candidates, in the order its
            rounds record them, or none. None for the peer view.
        effects: The activation's effect records, finished or not, in claim order, as
            the plan store returns them: given, the peer view is returned.

    Returns:
        The projection, or the peer view where ``effects`` is given.

    Raises:
        ValueError: If ``excerpt_chars`` is not an integer of at least 1; for the
            projection, if the episode is open: an open episode is never a model
            input there (ADR-0286 §6), so a reader that feeds a model passes over it
            before it projects; or ``candidates`` are given for an episode with no
            processing record, which records no round; for the peer view, if the
            episode has no processing record, ``admit_outside_input`` or
            ``candidates`` are given, or an effect is another activation's.
    """
    if type(excerpt_chars) is not int or excerpt_chars < 1:
        msg = "the episode excerpt bound must be an integer of at least 1"
        raise ValueError(msg)
    if effects is not None:
        if admit_outside_input or candidates:
            msg = "a peer view admits no outside input and carries no candidate (ADR-0349 §6:9)"
            raise ValueError(msg)
        return _peer_view(record, effects, excerpt_chars, owner_records=owner_records)
    if record.processing_record is not None and record.processing_record.is_open:
        msg = "an open episode is never a model input (ADR-0286 §6)"
        raise ValueError(msg)
    response = _projected(record.outcome, excerpt_chars)
    external = rests_on_recorded_external_content(record.provenance)
    processing = record.processing_record
    if processing is None:
        if candidates:
            msg = "an episode with no processing record records no candidate"
            raise ValueError(msg)
        return EpisodeProjection(
            occurred_at=record.occurred_at,
            capture_modality=record.capture.modality,
            input=_projected(record.content, excerpt_chars),
            response=response,
            derived_from_external=external,
        )
    trigger = processing.trigger
    origin = trigger.origin
    shown = origin is InputOrigin.USER or (origin is InputOrigin.OUTSIDE and admit_outside_input)
    latest = processing.understanding[-1] if processing.understanding else None
    return EpisodeProjection(
        occurred_at=record.occurred_at,
        channel=trigger.channel,
        # ADR-0351 §8:4, §10:4: the parties and the latest version's relay mark, in
        # place of the origin, which the projection computes from the parties alone
        # until the lane that moves this reader over (§10:2, §11).
        parties=trigger.parties,
        relayed=latest is not None and latest.relayed,
        input=_projected(_input_text(trigger), excerpt_chars) if shown else None,
        meaning=None if latest is None else latest.meaning,
        meaning_ground=None if latest is None else latest.meaning_ground,
        unresolved=() if latest is None else latest.unresolved,
        response=response,
        status=processing.status,
        reason=processing.reason,
        derived_from_external=external,
        rounds=_projected_rounds(processing.rounds, excerpt_chars, owner_records=owner_records),
        evidence=_projected_evidence(processing.digests, excerpt_chars) if owner_records else (),
        candidates=tuple(
            ProjectedText(text=fact[:excerpt_chars], full_chars=len(fact)) for fact in candidates
        ),
    )


def _peer_view(
    record: EpisodicMemory,
    effects: Sequence[ActivationEffect],
    bound: int,
    *,
    owner_records: bool,
) -> PeerView:
    """Another activation's own work, from its episode as stored and its effects (§6:8)."""
    processing = record.processing_record
    if processing is None:
        msg = "a peer view reads an activation's episode, which has a processing record"
        raise ValueError(msg)
    trigger = processing.trigger
    shown = trigger.origin is InputOrigin.USER
    latest = processing.understanding[-1] if processing.understanding else None
    notes = (
        tuple(
            PeerNotes(notes=projected, marked=one.notes_marked)
            for one in processing.rounds
            if (projected := _projected(one.notes, bound)) is not None
        )
        if owner_records
        else ()
    )
    return PeerView(
        channel=trigger.channel,
        origin=trigger.origin,
        input=_projected(_input_text(trigger), bound) if shown else None,
        joined=tuple(_joined_text(one, bound) for one in processing.joined) if shown else (),
        meaning=None if latest is None else latest.meaning,
        notes=notes,
        evidence=_projected_evidence(processing.digests, bound) if owner_records else (),
        did=_peer_effects(processing, effects, bound),
        status=processing.status,
        reason=processing.reason,
        derived_from_external=rests_on_recorded_external_content(record.provenance),
    )


def _joined_text(joined: JoinedInput, bound: int) -> ProjectedText:
    """One held input's text: its messages, apart, as the readers take them in as one."""
    text = _MESSAGE_SEPARATOR.join(one.text for one in joined.messages)
    return ProjectedText(text=text[:bound], full_chars=len(text))


def _peer_effects(
    processing: EpisodeProcessingRecord, effects: Sequence[ActivationEffect], bound: int
) -> tuple[PeerEffect, ...]:
    """Each effect done or unknown, in claim order, as §6:9 shows it.

    Raises:
        ValueError: If an effect is another activation's.
    """
    rounds = {one.id: one for one in processing.rounds}
    shown: list[PeerEffect] = []
    for effect in effects:
        if effect.activation_id != processing.activation_id:
            msg = "a peer view shows the effects of the activation it reads alone"
            raise ValueError(msg)
        outcome = effect.outcome
        if outcome is None or outcome not in _SHOWN_OUTCOMES:
            continue
        if effect.is_call:
            shown.append(PeerEffect(outcome=outcome, capability=effect.capability))
        elif effect.round is None:
            shown.append(PeerEffect(outcome=outcome, couldnt_finish=True))
        else:
            planned = rounds.get(effect.round)
            message = (
                _projected(planned.text, bound) if planned and _shows_message(planned) else None
            )
            shown.append(PeerEffect(outcome=outcome, message=message))
    return tuple(shown)


def _projected_rounds(
    rounds: tuple[PlanningRound, ...], bound: int, *, owner_records: bool
) -> tuple[ProjectedRound, ...]:
    """Each round's message, its question's mark, and its notes where they may be shown.

    The mark is the part numbers of the round's recorded asked calls (ADR-0321 §2:8),
    carried only with the message (ADR-0322 §4:3).
    """
    projected: list[ProjectedRound] = []
    for one in rounds:
        message = _projected(one.text, bound) if _shows_message(one) else None
        notes = _projected(one.notes, bound) if owner_records else None
        if message is None and notes is None:
            continue
        projected.append(
            ProjectedRound(
                message=message,
                notes=notes,
                notes_marked=notes is not None and one.notes_marked,
                asked=tuple(asked.part for asked in one.asked) if _is_marked(one) else (),
            )
        )
    return tuple(projected)


def question_marks(
    record: EpisodicMemory, projection: EpisodeProjection
) -> tuple[tuple[str, ProjectedRound], ...]:
    """Each question mark ``projection`` carries, with the id of the round it was read from.

    The projection carries no id (ADR-0284 §8:3), so a reader that labels the marks it
    renders, or names a message's question by its round, pairs them by this
    (ADR-0322 §4:3-§4:4). The marked rounds are exactly those :func:`project_episode`
    projects with a non-empty ``asked``, in its order, whatever the reader: a round's
    message, and so its mark, is shown wherever the episode is (ADR-0307 §10).

    Args:
        record: The stored episode, exactly as held.
        projection: Its projection, as :func:`project_episode` returned it.

    Returns:
        Each marked round's id and its projected round, in the projection's order. None
        for an episode with no processing record, and none where the projection's marks
        do not match the record's rounds, which fails closed: no question is marked.
    """
    processing = record.processing_record
    if processing is None:
        return ()
    rounds = [one for one in processing.rounds if _is_marked(one)]
    shown = [one for one in projection.rounds if one.asked]
    if len(rounds) != len(shown) or any(
        one.asked != tuple(asked.part for asked in planned.asked)
        for one, planned in zip(shown, rounds, strict=True)
    ):
        return ()
    return tuple((planned.id, one) for one, planned in zip(shown, rounds, strict=True))


def _shows_message(one: PlanningRound) -> bool:
    """Whether the projection carries the round's message: it wrote some text."""
    return bool(one.text.strip())


def _is_marked(one: PlanningRound) -> bool:
    """Whether the projection marks the round a question: it asked, and its message shows."""
    return bool(one.asked) and _shows_message(one)


def _projected_evidence(
    digests: tuple[ActivationDigest, ...], bound: int
) -> tuple[ProjectedEvidence, ...]:
    """Each digest's items, in order: the text and the mark, never the source label."""
    return tuple(
        ProjectedEvidence(text=ProjectedText(text=item.text[:bound], full_chars=len(item.text)))
        for digest in digests
        for item in digest.evidence
    )


# --- a revision of an open episode (ADR-0286 §3) -------------------------------


def episode_extends(stored: EpisodicMemory, revision: EpisodicMemory) -> bool:
    """Whether ``revision`` only extends the open episode ``stored`` (ADR-0286 §3).

    Decided from the two records' processing records and ``outcome`` alone; no other
    field of either episode enters it. It holds exactly where both carry a
    processing record with one ``activation_id``, the stored one is open, the two
    differ in their processing record or ``outcome``, and every difference is one
    §3 admits:

    - a field at its unset value taking a value: the trigger's ``channel``, a speech
      trigger's ``transcript``, ``recall``, ``recall_second_run`` (ADR-0308 §7, in the
      addition alone) and ``outcome`` (from ``None``), and ``output_degraded`` (from
      ``False``);
    - entries appended at the end of ``understanding`` and of ``stages``, each under
      its bound, with its elided count grown by exactly what the bound dropped; where a
      stored version records the relay mark, the revision's latest version records it
      too, so a bound that elides the version that marked the input never drops the
      mark (ADR-0351 §5:9);
    - entries appended at the end of ``rounds`` and of ``labels``, every earlier entry
      unchanged; neither is bounded (ADR-0307 §10, superseding §3:3 in the additions
      alone);
    - entries appended at the end of ``digests``, every earlier entry unchanged, and
      unbounded (ADR-0308 §7, in the addition alone);
    - entries appended at the end of ``joined``, every earlier entry unchanged, and
      unbounded: each input that joined, in the order it joined (ADR-0332 §3:16, as its
      §10 adds to ADR-0286 §3:3);
    - in the one revision that freezes it, ``status``, ``reason``, ``ended_at`` and
      ``understanding_omitted``, with the end entry the record's own validators then
      require last, and ``taken_over_by`` (ADR-0352 §6:6, as it adds to ADR-0286 §3:3),
      which takes a value in no other revision.

    A field that carries a value keeps it.

    **The bound is read off the two records**, because its limit is a setting the
    record does not carry (ADR-0276 §7:4, ADR-0280 §6:6). Where a sequence's elided
    count did not grow, the bound dropped nothing: the stored entries stand as the
    revision's prefix, and a stored sequence the bound had already cut takes no
    further entry. Where it grew, the bound bit at the revision's own length, which
    is then the limit: ``understanding`` keeps its first entry and the latest,
    ``stages`` its first half and the rest from the end, and every entry the
    revision keeps from the stored sequence must sit where that bound puts it.

    Args:
        stored: The episode as the store holds it.
        revision: The episode a writer would replace it with.

    Returns:
        Whether ``revision`` extends ``stored``.
    """
    before = stored.processing_record
    after = revision.processing_record
    if (
        before is None
        or after is None
        or before.activation_id != after.activation_id
        or not before.is_open
    ):
        return False
    if before == after and stored.outcome == revision.outcome:
        return False
    if stored.outcome is not None and stored.outcome != revision.outcome:
        return False
    if not _appended(
        before.understanding,
        before.understanding_elided,
        after.understanding,
        after.understanding_elided,
        head=_understanding_head,
    ) or not _appended(
        before.stages, before.stages_elided, after.stages, after.stages_elided, head=_stage_head
    ):
        return False
    if _drops_a_relay_mark(before, after) or (
        after.rounds[: len(before.rounds)] != before.rounds
        or after.labels[: len(before.labels)] != before.labels
        or after.digests[: len(before.digests)] != before.digests
        or after.joined[: len(before.joined)] != before.joined
    ):
        return False
    settled = before.model_copy(
        update={
            "trigger": _settled_trigger(before.trigger, after.trigger),
            "recall": after.recall if before.recall is None else before.recall,
            "recall_second_run": (
                after.recall_second_run
                if before.recall_second_run is None
                else before.recall_second_run
            ),
            "output_degraded": before.output_degraded or after.output_degraded,
            "understanding": after.understanding,
            "understanding_elided": after.understanding_elided,
            "stages": after.stages,
            "stages_elided": after.stages_elided,
            "rounds": after.rounds,
            "labels": after.labels,
            "digests": after.digests,
            "joined": after.joined,
            "status": after.status,
            "reason": after.reason,
            "ended_at": after.ended_at,
            "understanding_omitted": after.understanding_omitted,
            # ADR-0352 §6:6: only the freezing revision names who took the matter. The
            # stored record is open, so it names none (§6:5), and an open revision keeps
            # that none.
            "taken_over_by": before.taken_over_by if after.is_open else after.taken_over_by,
        }
    )
    return settled == after


def _drops_a_relay_mark(before: EpisodeProcessingRecord, after: EpisodeProcessingRecord) -> bool:
    """Whether ``after``'s latest version drops a relay mark ``before`` records (ADR-0351 §5:9).

    The mark holds for the rest of the activation. The record's own validator holds it
    across the versions a record keeps; this holds it across the versions the bound
    elides, which the revision no longer carries.
    """
    marked = any(one.relayed for one in before.understanding)
    return marked and not (after.understanding and after.understanding[-1].relayed)


def _understanding_head(limit: int) -> int:
    """ADR-0276 §7:4: the history keeps version 1 and the latest ``limit - 1``."""
    del limit
    return 1


def _stage_head(limit: int) -> int:
    """ADR-0280 §6:6: the record keeps its first ``limit // 2`` entries and the rest last."""
    return limit // 2


def _appended(
    before: tuple[object, ...],
    before_elided: int,
    after: tuple[object, ...],
    after_elided: int,
    *,
    head: Callable[[int], int],
) -> bool:
    """Whether ``after`` is ``before`` with entries appended under a head-and-tail bound.

    ``head`` gives how many entries the bound keeps from the front at a limit; it
    keeps the rest from the end.
    """
    added = len(after) + after_elided - len(before) - before_elided
    if added < 0 or after_elided < before_elided:
        return False
    if after_elided == before_elided:
        return (before_elided == 0 or added == 0) and after[: len(before)] == before
    # The bound bit, at the revision's length. The stored sequence passed the same
    # bound, so it is no longer than that limit, and exactly as long where the bound
    # had already dropped entries: a shorter revision would lose recorded entries.
    limit = len(after)
    kept_head = head(limit)
    kept_tail = limit - kept_head
    if (
        kept_head < 1
        or kept_tail < 1
        or len(before) > limit
        or (before_elided and len(before) != limit)
    ):
        return False
    # The bound over the stored entries followed by the appended ones (ADR-0286 §3):
    # the revision's index ``i`` holds that sequence's entry ``source``, which is a
    # stored entry where it falls inside the stored prefix.
    combined = len(before) + added
    for index, entry in enumerate(after):
        source = index if index < kept_head else combined - kept_tail + (index - kept_head)
        if source < len(before) and entry != before[source]:
            return False
    return True


def _settled_trigger(
    before: RecordedChannelTrigger, after: RecordedChannelTrigger
) -> RecordedChannelTrigger:
    """``before``, with its channel and its transcript taken from ``after`` where unset."""
    settled = before
    if before.channel is None:
        settled = settled.model_copy(update={"channel": after.channel})
    if (
        isinstance(settled.payload, RecordedSpeechInput)
        and settled.payload.transcript is None
        and isinstance(after.payload, RecordedSpeechInput)
    ):
        payload = settled.payload.model_copy(update={"transcript": after.payload.transcript})
        settled = settled.model_copy(update={"payload": payload})
    return settled


def _input_text(trigger: RecordedChannelTrigger) -> str | None:
    """The trigger's exact payload text or transcript."""
    payload = trigger.payload
    if isinstance(payload, RecordedTextInput):
        return payload.text
    return payload.transcript


def _projected(text: str | None, bound: int) -> ProjectedText | None:
    """A bounded prefix of ``text`` and the length it was cut from."""
    if text is None:
        return None
    return ProjectedText(text=text[:bound], full_chars=len(text))
