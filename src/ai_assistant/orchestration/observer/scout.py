"""The scout: one model call proposing findings about a leaving episode (ADR-0346 §4).

The scout is one call per due episode, over what §2 reads (§4:1). It proposes findings:
each states one thing worth keeping, which may hold several claims that share its
annotations, and names the parts it rests on by the labels the reading gave them (§4:2).
Beside each it says what it knows of the person: whom the finding is about and whom it
involves, why it matters, the situations in which it matters, and, where it should reach
fewer people than its default, a proposed narrowing with a note on why. Parts that call
for different handling are separate findings (§4:3). It writes nothing: its findings, and
later each one's outcome, are recorded on the leaving episode's observation record, the
annotations beside each claim (§4:5).

**Every candidate is accounted for** (§4:6). The reply names each candidate the leaving
episode records by a finding, or declines it with a reason. A reply that leaves one
unaccounted is refused as a reply that does not parse is, and the attempt is retried
(ADR-0329 §16:4); the record keeps each decline and its reason. Where code drops the only
finding naming a candidate, as it drops one resting on no part of the leaving episode,
the candidate is recorded declined under a code-owned reason, so nothing planning
recorded disappears unexplained.

**What code holds of a proposal**, whatever the model answered. A finding names parts
by label, and code maps each label back to the part it names; a label naming nothing
read drops the finding, since no support may point at a part no stored episode holds
(ADR-0329 §9:5). A finding that rests on no part of the leaving episode is dropped (§3:1).
The annotations are hints (§4:4): they set no origin, holder or standing, and are no
evidence, and the owner, named "the user" in what the scout reads and writes, is recorded
by the owner's identifier (ADR-0345 §9:4). A proposed narrowing is read failing closed: any
narrowing the reply proposes is the one narrower reach the vocabulary holds, so a
malformed one never widens what a memory reaches (ADR-0217 §4).

**A candidate recorded under an approval** (ADR-0329 §5:5): a finding naming one rests on
the user's yes to its wording, whatever else the scout named, so framing sees the words
the user approved.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from pydantic import BaseModel, ConfigDict, JsonValue, ValidationError

from ai_assistant.core.types import (
    CandidateDecline,
    FindingAnnotations,
    Message,
    ObservationFinding,
    PlacementReach,
    ProfileField,
    ProposedNarrowing,
    ProposedSuggestion,
    Role,
    SuggestionKind,
    SupportOrigin,
)
from ai_assistant.orchestration.observer.reading import name_stored

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.core.prompts import RenderedPrompt
    from ai_assistant.core.types import FrozenJson, SupportPart
    from ai_assistant.orchestration.observer.reading import Reading, ReadPart

__all__ = [
    "DROPPED_REASON",
    "PersonProposals",
    "PersonScoutReply",
    "Proposal",
    "ScoutReply",
    "person_proposals",
    "proposed",
    "scout_messages",
]

#: The origins of the assistant's own words, on which no suggestion rests (ADR-0329 §10:1).
_ASSISTANT_ORIGINS: Final = frozenset(
    {SupportOrigin.ASSISTANT_MESSAGE, SupportOrigin.ASSISTANT_MESSAGE_OVER_OUTSIDE}
)

#: Why a candidate is recorded declined where code dropped every finding naming it
#: (ADR-0346 §4:6): code-owned words, never the model's.
DROPPED_REASON: Final = (
    "the scout's finding about it rested on no part of this exchange the record holds"
)

#: A narrowing's note where the scout proposed one without saying why (ADR-0346 §4:2).
_NARROWING_NOTE: Final = "the scout proposed a narrower reach and gave no reason"


class _ProposedFinding(BaseModel):
    """One finding as the scout writes it: labels, never addresses (ADR-0346 §4:2)."""

    model_config = ConfigDict(frozen=True, extra="ignore")
    claim: str
    rests_on: tuple[str, ...] = ()
    candidates: tuple[str, ...] = ()
    subjects: tuple[str, ...] = ()
    involved: tuple[str, ...] = ()
    why: str = ""
    situations: tuple[str, ...] = ()
    narrowing: JsonValue = None


class _ProposedDecline(BaseModel):
    """One candidate the scout declined, by its label, and why (ADR-0346 §4:6)."""

    model_config = ConfigDict(frozen=True, extra="ignore")
    candidate: str
    reason: str


class ScoutReply(BaseModel):
    """The scout's whole reply (its instruction's shape); an unnamed key is dropped."""

    model_config = ConfigDict(frozen=True, extra="ignore")
    findings: tuple[_ProposedFinding, ...] = ()
    declines: tuple[_ProposedDecline, ...] = ()


class _PersonProposedFinding(_ProposedFinding):
    """A finding as the scout writes it under the person flag (ADR-0338 §9:3).

    ``restates`` is any JSON value: one that is not a setting and a value says nothing,
    so a malformed one costs the reply nothing and the finding is committed as any other.
    """

    restates: JsonValue = None


class PersonScoutReply(ScoutReply):
    """The scout's whole reply where it is given a person's fields (ADR-0338 §9:1-§9:3).

    Its two additions are optional, and read as JSON values whatever they hold: a reply
    that leaves them out, as one written under an override that does not carry the
    person sections does, is read exactly as :class:`ScoutReply` reads it, and an entry
    that is not a suggestion is dropped alone, never the reply.
    """

    findings: tuple[_PersonProposedFinding, ...] = ()
    suggestions: JsonValue = None


@dataclass(frozen=True, slots=True)
class Proposal:
    """What code keeps of a scout's reply (ADR-0346 §4:2, §4:6).

    Attributes:
        findings: The findings kept, each with no outcome yet.
        declines: Every candidate no kept finding names, with its reason.
        dropped: How many proposed findings code dropped.
    """

    findings: tuple[ObservationFinding, ...]
    declines: tuple[CandidateDecline, ...]
    dropped: int


@dataclass(frozen=True, slots=True)
class PersonProposals:
    """What the scout proposed of the person model, after code's checks (ADR-0338 §9:2-§9:3).

    Attributes:
        restating: The findings that only restate a field, by id, each with the field
            suggestion it becomes, or ``None`` where no part it rests on can carry one.
            None of them is committed.
        suggestions: The field suggestions the scout proposed beside its findings.
        dropped: How many proposed suggestions code dropped as malformed.
    """

    restating: dict[str, ProposedSuggestion | None]
    suggestions: tuple[ProposedSuggestion, ...]
    dropped: int

    @property
    def to_record(self) -> tuple[ProposedSuggestion, ...]:
        """Every suggestion to record, the scout's and the restating findings', in order."""
        return (
            *self.suggestions,
            *(one for one in self.restating.values() if one is not None),
        )


def scout_messages(
    reading: Reading,
    instruction: RenderedPrompt,
    *,
    person: dict[str, FrozenJson] | None = None,
) -> list[Message]:
    """The scout's one call: its instruction, and the reading as quoted source data.

    Args:
        reading: What the observer read of the leaving episode.
        instruction: ``OBSERVER_SCOUT_PROMPT`` rendered from its template, default or
            override, as the composition root read it at start (ADR-0334 §3:5); the
            call's given entry records its ``prompt`` key (ADR-0335 §9:1).
        person: The leaving episode's person's five fields (ADR-0338 §7:4, §9:1), shown
            first under ``person``; ``None`` where the step is given none.

    Returns:
        The conversation the scout's route completes.
    """
    payload = reading.payload()
    if person is not None:
        payload = {"person": person, **payload}
    return [
        Message(role=Role.SYSTEM, content=instruction.text),
        Message(role=Role.USER, content=json.dumps(payload, ensure_ascii=True)),
    ]


def proposed(reply: ScoutReply, reading: Reading, *, numbered_from: int = 1) -> Proposal | None:
    """The findings and declines code keeps of the scout's reply (ADR-0346 §4).

    Args:
        reply: The scout's parsed reply.
        reading: The reading its labels name things in.
        numbered_from: The number the first finding's id takes (``f1``, ``f2``, ...).

    Returns:
        The proposal, or ``None`` where the reply leaves a candidate of the leaving
        episode neither named by a finding nor declined with a reason (§4:6): the reply
        is refused as one that does not parse is.
    """
    hints = {hint.handle: hint for hint in reading.hints}
    named = {label for one in reply.findings for label in one.candidates if label in hints}
    reasons: dict[str, str] = {}
    for one in reply.declines:
        if one.candidate in hints and one.reason.strip():
            reasons.setdefault(one.candidate, one.reason.strip())
    if set(hints) - named - set(reasons):
        return None
    kept, dropped = _kept(reply, reading, numbered_from=numbered_from)
    covered = {hints[label].effect for _, source in kept for label in source.candidates}
    declines: dict[str, CandidateDecline] = {}
    for handle, hint in hints.items():
        if hint.effect in covered or hint.effect in declines:
            continue
        reason = reasons.get(handle, DROPPED_REASON)
        declines[hint.effect] = CandidateDecline(candidate=hint.effect, reason=reason)
    return Proposal(
        findings=tuple(one for one, _ in kept), declines=tuple(declines.values()), dropped=dropped
    )


def person_proposals(
    reply: PersonScoutReply, reading: Reading, *, numbered_from: int = 1
) -> PersonProposals:
    """What the scout proposed of the person model, checked (ADR-0338 §9:2-§9:3).

    A finding marked as only restating a field, with a field and a non-blank value,
    becomes a field suggestion resting on the first part it rests on that the leaving
    episode carries and that is not the assistant's own words (ADR-0329 §10:1), or on
    none where it rests on no such part; either way it is not committed (§9:3). A
    proposed suggestion is kept only where it names a field, a non-blank value and one
    part, by its label, that the leaving episode carries and that is not the assistant's
    own words. Whether the value is valid, held already, pending or dismissed is the
    store's to answer when it is recorded (§9:2).

    Args:
        reply: The scout's parsed reply, under the person flag.
        reading: The reading its labels name things in.
        numbered_from: The number the first finding's id takes, as :func:`proposed` was
            given it for the same reply, so the two name the findings alike.

    Returns:
        The restating findings, the suggestions, and how many suggestions were dropped.
    """
    kept, _ = _kept(reply, reading, numbered_from=numbered_from)
    episode = reading.record.id
    restating: dict[str, ProposedSuggestion | None] = {}
    for finding, source in kept:
        if not isinstance(source, _PersonProposedFinding):
            continue
        restated = _setting(source.restates)
        if restated is None:
            continue
        part = next(
            (
                read
                for one in finding.rests_on
                if (read := reading.at(one)) is not None and _may_carry(read, reading)
            ),
            None,
        )
        restating[finding.id] = None if part is None else _suggested(restated, part, episode)
    suggestions: list[ProposedSuggestion] = []
    dropped = 0
    entries = reply.suggestions if isinstance(reply.suggestions, list) else []
    for entry in entries:
        suggestion = _scouted_suggestion(entry, reading, episode)
        if suggestion is None:
            dropped += 1
        else:
            suggestions.append(suggestion)
    if reply.suggestions is not None and not isinstance(reply.suggestions, list):
        dropped += 1
    return PersonProposals(restating=restating, suggestions=tuple(suggestions), dropped=dropped)


type _Kept = list[tuple[ObservationFinding, _ProposedFinding]]


def _kept(reply: ScoutReply, reading: Reading, *, numbered_from: int) -> tuple[_Kept, int]:
    """The findings kept, each beside the proposal it came from, and the count dropped.

    A finding naming a label the reading does not hold, a part or a candidate, is
    malformed and dropped, and so is one resting on no part of the leaving episode
    (ADR-0346 §3:1).
    """
    episode = reading.record.id
    leaving = reading.leaving_parts
    hints = {hint.handle: hint for hint in reading.hints}
    kept: _Kept = []
    dropped = 0
    for one in reply.findings:
        parts = _parts(one.rests_on, reading)
        if any(label not in hints for label in one.candidates) or not parts:
            dropped += 1
            continue
        named = [hints[label] for label in dict.fromkeys(one.candidates)]
        for hint in named:
            if hint.confirmation is not None and hint.confirmation.part not in parts:
                # §5:5: a finding about a candidate the user confirmed rests on that yes.
                parts = (*parts, hint.confirmation.part)
        if leaving.isdisjoint(parts):
            dropped += 1
            continue
        # Two labels may name one candidate's effect, which the record names once.
        effects = list(dict.fromkeys(hint.effect for hint in named))
        try:
            finding = ObservationFinding(
                id=f"f{numbered_from + len(kept)}",
                episode=episode,
                claim=one.claim,
                rests_on=parts,
                candidate=effects[0] if effects else None,
                further_candidates=tuple(effects[1:]),
                annotations=_annotations(one),
            )
        except ValidationError:
            dropped += 1
            continue
        kept.append((finding, one))
    return kept, dropped


def _annotations(proposed_: _ProposedFinding) -> FindingAnnotations:
    """The scout's annotations on one finding, as the record keeps them (ADR-0346 §4:2).

    Each name as the scout gave it, the owner by the owner's identifier; a person named
    in both fields is kept in ``subjects`` alone (ADR-0345 §9:2). Blank entries are left
    out. Any narrowing proposed is the narrower reach, failing closed (ADR-0217 §4).
    """
    subjects = _names(proposed_.subjects)
    involved = tuple(one for one in _names(proposed_.involved) if one not in subjects)
    situations = tuple(dict.fromkeys(one.strip() for one in proposed_.situations if one.strip()))
    narrowing = None
    if proposed_.narrowing is not None and proposed_.narrowing is not False:
        held = proposed_.narrowing
        note = held.get("note") if isinstance(held, dict) else None
        narrowing = ProposedNarrowing(
            reach=PlacementReach.OWNER,
            note=note.strip() if isinstance(note, str) and note.strip() else _NARROWING_NOTE,
        )
    return FindingAnnotations(
        subjects=subjects,
        involved=involved,
        why=proposed_.why.strip(),
        situations=situations,
        narrowing=narrowing,
    )


def _names(names: Sequence[str]) -> tuple[str, ...]:
    """Names as the record keeps them, each once, blank ones left out."""
    return tuple(dict.fromkeys(name_stored(one) for one in names if one.strip()))


def _parts(handles: tuple[str, ...], reading: Reading) -> tuple[SupportPart, ...]:
    """The parts the labels name, each once; empty where any label names nothing read."""
    parts: list[SupportPart] = []
    for handle in dict.fromkeys(handles):
        read = reading.part(handle)
        if read is None:
            return ()
        parts.append(read.part)
    return tuple(parts)


def _setting(value: JsonValue) -> tuple[ProfileField, str] | None:
    """A field and its value, from a JSON object naming both; ``None`` from anything else."""
    if not isinstance(value, dict):
        return None
    field, held = value.get("field"), value.get("value")
    if not isinstance(field, str) or not isinstance(held, str) or not held.strip():
        return None
    try:
        return ProfileField(field), held.strip()
    except ValueError:
        return None


def _may_carry(read: ReadPart, reading: Reading) -> bool:
    """Whether a suggestion may rest on ``read``: the leaving episode's, not the assistant's."""
    return read.part in reading.leaving_parts and read.origin not in _ASSISTANT_ORIGINS


def _suggested(
    setting: tuple[ProfileField, str], read: ReadPart, episode: str
) -> ProposedSuggestion | None:
    """A field suggestion resting on ``read``, its origin code's, from the record (§7:9).

    ``None`` where the value is no text a suggestion may carry.
    """
    field, value = setting
    try:
        return ProposedSuggestion(
            kind=SuggestionKind.FIELD,
            field=field,
            value=value,
            episode_id=episode,
            part=read.part,
            origin=read.origin,
        )
    except ValidationError:
        return None


def _scouted_suggestion(
    entry: JsonValue, reading: Reading, episode: str
) -> ProposedSuggestion | None:
    """One suggestion the scout proposed, or ``None`` where it is malformed (§9:2)."""
    setting = _setting(entry)
    if setting is None or not isinstance(entry, dict):
        return None
    label = entry.get("part")
    read = reading.part(label) if isinstance(label, str) else None
    if read is None or not _may_carry(read, reading):
        return None
    return _suggested(setting, read, episode)
