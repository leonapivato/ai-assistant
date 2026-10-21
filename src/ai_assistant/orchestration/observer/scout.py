"""The scout: one model call proposing findings about a leaving episode (ADR-0329 §9:1).

The scout is one call over what §8 names, with the leaving episode's candidates as hints
(§9:1). It proposes findings: each states one claim in words and names the parts of
episodes it rests on, by the labels the reading gave them. It writes nothing (§9:2): its
findings, and later each one's outcome, are recorded on the leaving episode's
observation record (§16:1).

**What code holds of a proposal**, whatever the model answered. A finding names parts
by label, and code maps each label back to the part it names; a label naming nothing
read drops the finding, since no support may point at a part no stored episode holds
(§9:5). A finding that rests on no part of the leaving episode is dropped: the observer
commits only findings that come from the leaving episode (§8:2). A reliance finding is
the one exception, since what it rests on is what later episodes show of a reliance in
the leaving one (§14:1-§14:2): it is kept only where it names a memory a reliance call
in the leaving episode named, and rests on parts of later episodes alone.

**A candidate recorded under an approval is never left out** (§5:5, §11:1). The user's
yes to its wording is the strongest warrant there is: a finding naming such a candidate
rests on that yes, whatever else the scout named, and where the scout proposed no finding
resting on it, code adds one, its claim the fact the user approved.

A reply that does not parse is no proposal, never a partial one: the attempt fails and
is retried (§16:4). A key the reply's shape does not name is dropped rather than refusing
the reply: every field it does name is validated as before, so a reply missing a required
field, or carrying a value of the wrong kind, still fails whole. A model's stray key, such
as a ``"command": null`` beside a finding's own, is no reason to discard its findings.

A reply with prose around its object is read for that object, not refused for the prose:
the whole reply first, then a fenced block, then the last object standing on its own in
the text. Each is validated exactly as a bare reply is. An object found in the text is
taken only where it names a field of the shape, so a stray ``{}`` or an unrelated object
in the prose is never read as an empty answer; and no container, an object or an array, is
ever looked inside, nor a fence opened within one, so a nested piece of a malformed answer
is never read as the answer. A fence only marks a block as a candidate: it never cuts the
search, so a container left open inside a block still holds what follows the block.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from pydantic import BaseModel, ConfigDict, JsonValue, ValidationError

from ai_assistant.core.types import (
    Message,
    ObservationFinding,
    ProfileField,
    ProposedSuggestion,
    Role,
    SuggestionKind,
    SupportOrigin,
)

if TYPE_CHECKING:
    from ai_assistant.core.prompts import RenderedPrompt
    from ai_assistant.core.types import FrozenJson, SupportPart
    from ai_assistant.orchestration.observer.reading import Reading, ReadPart

__all__ = [
    "PersonProposals",
    "PersonScoutReply",
    "ScoutReply",
    "parsed",
    "person_proposals",
    "proposed_findings",
    "scout_messages",
]

#: The origins of the assistant's own words, on which no suggestion rests (ADR-0329 §10:1).
_ASSISTANT_ORIGINS: Final = frozenset(
    {SupportOrigin.ASSISTANT_MESSAGE, SupportOrigin.ASSISTANT_MESSAGE_OVER_OUTSIDE}
)


class _ProposedFinding(BaseModel):
    """One finding as the scout writes it: labels, never addresses."""

    model_config = ConfigDict(frozen=True, extra="ignore")
    claim: str
    rests_on: tuple[str, ...] = ()
    candidate: str | None = None
    relied_on: str | None = None


class ScoutReply(BaseModel):
    """The scout's whole reply (its instruction's shape); an unnamed key is dropped."""

    model_config = ConfigDict(frozen=True, extra="ignore")
    findings: tuple[_ProposedFinding, ...] = ()


class _PersonProposedFinding(_ProposedFinding):
    """A finding as the scout writes it under the person flag (ADR-0338 §9:3).

    ``restates`` is any JSON value: one that is not a setting and a value says nothing,
    so a malformed one costs the reply nothing and the finding is committed as any other.
    """

    restates: JsonValue = None


class PersonScoutReply(BaseModel):
    """The scout's whole reply where it is given a person's fields (ADR-0338 §9:1-§9:3).

    Its two additions are optional, and read as JSON values whatever they hold: a reply
    that leaves them out, as one written under an override that does not carry the
    person sections does, is read exactly as :class:`ScoutReply` reads it, and an entry
    that is not a suggestion is dropped alone, never the reply.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")
    findings: tuple[_PersonProposedFinding, ...] = ()
    suggestions: JsonValue = None


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


#: A fence opening a block, its tag group 1. It is matched only where the walk stands in
#: the reply's prose, outside any container, so never within a JSON string. Its tag is one
#: word, so no bracket of the reply is ever taken for part of a tag.
_OPENING: Final = re.compile(r"```[ \t]*([\w.+-]*)[ \t]*\n")

#: The fence closing a block, alone on its line: a JSON string holds no raw newline, so
#: backticks inside a fenced object's string never close its block.
_CLOSING: Final = re.compile(r"^[ \t]*```[ \t]*$", re.MULTILINE)

#: The tags a block offered as the reply carries: none, or ``json``.
_JSON_TAGS: Final = frozenset({"", "json", "JSON"})


def parsed[T: BaseModel](content: str, shape: type[T]) -> T | None:
    """A reply as one object of ``shape``, or ``None``: never a partial one.

    The whole reply is read first, with one enclosing Markdown code fence removed, as the
    understanding stage and the tidy-up remove it: a deterministic normalization of a
    wrapper, not a repair. Where the whole reply is not that object, because the model
    wrote prose around it, the object is looked for in the text: a fenced block, the last
    that validates; else an object standing on its own in the text, the last that
    validates. An object found in the text counts only where it names a field of
    ``shape``, and nothing inside a container, an object or an array, is a candidate.

    Args:
        content: The model's reply.
        shape: The model the reply must validate as.

    Returns:
        The object, or ``None`` where neither the reply nor any object in it validates.
    """
    body = content.strip()
    if body.startswith("```") and body.endswith("```") and len(body) >= 6:  # noqa: PLR2004 — two fences
        body = body[3:-3]
        newline = body.find("\n")
        if newline != -1 and body[:newline].strip() in {"", "json", "JSON"}:
            body = body[newline + 1 :]
    whole = _validated(body, shape)
    if whole is not None:
        return whole
    # A JSON value holds no raw carriage return, so line endings are one kind for the search.
    fenced, objects = _candidates(re.sub(r"\r\n?", "\n", content))
    for candidate in (*reversed(fenced), *reversed(objects)):
        if not _names_a_field(candidate, shape):
            continue
        found = _validated(candidate, shape)
        if found is not None:
            return found
    return None


def _validated[T: BaseModel](text: str, shape: type[T]) -> T | None:
    """``text`` validated as ``shape``, or ``None``: the one validation every reading uses."""
    try:
        return shape.model_validate_json(text)
    except ValidationError, ValueError, RecursionError:
        return None


def _names_a_field(text: str, shape: type[BaseModel]) -> bool:
    """Whether ``text`` is a JSON object carrying a key ``shape`` names."""
    try:
        value = json.loads(text)
    except ValueError, RecursionError:
        return False
    if not isinstance(value, dict):
        return False
    named = set(shape.model_fields)
    named.update(f.alias for f in shape.model_fields.values() if f.alias is not None)
    return not named.isdisjoint(value)


def _candidates(text: str) -> tuple[list[str], list[str]]:
    """The fenced blocks' bodies and the top-level JSON objects in ``text``, each in order.

    One walk finds both, so they share one rule: nothing inside a container, an object or
    an array, is a candidate, and neither is a fence opened inside one. Each ``{`` or
    ``[`` the walk meets starts a container. One that decodes is passed whole, an object
    kept as a candidate and an array's members never; one that does not decode is skipped
    as far as its brackets balance. A container whose brackets never balance ends the
    walk, since everything after it may be inside it.

    A fence the walk meets outside any container opens a block, which runs to its closing
    fence, alone on its line, or where none closes it to the end. A block untagged or
    tagged ``json`` offers its body as a candidate. A fence changes nothing else: the walk
    goes on through the block as through any other text, a container opened in it still
    open past its closing fence, and steps over that closing fence rather than taking it
    for an opening one.
    """
    decoder = json.JSONDecoder()
    fenced: list[str] = []
    objects: list[str] = []
    closings: dict[int, int] = {}
    index = 0
    while index < len(text):
        if index in closings:
            index = closings[index]
            continue
        opening = _OPENING.match(text, index)
        if opening is not None:
            closing = _CLOSING.search(text, opening.end())
            if closing is not None:
                closings[closing.start()] = closing.end()
            if opening.group(1).strip() in _JSON_TAGS:
                fenced.append(
                    text[opening.end() : len(text) if closing is None else closing.start()]
                )
            index = opening.end()
            continue
        if text[index] not in "{[":
            index += 1
            continue
        end = _past_container(decoder, text, index, objects)
        if end is None:
            break
        index = end
    return fenced, objects


def _past_container(
    decoder: json.JSONDecoder, text: str, start: int, objects: list[str]
) -> int | None:
    """The index past the container at ``start``, keeping it in ``objects`` if an object.

    One that decodes is passed whole, an array's members never kept; one that does not is
    skipped as far as its brackets balance. ``None`` where they never balance.
    """
    try:
        value, end = decoder.raw_decode(text, start)
    except ValueError, RecursionError:
        return _balanced_end(text, start)
    if isinstance(value, dict):
        objects.append(text[start:end])
    return end


#: Each closing bracket, and the opening one it closes.
_OPENS: Final = {"}": "{", "]": "["}


def _balanced_end(text: str, start: int) -> int | None:
    """The index just past the bracket closing the one at ``start``, or ``None``.

    Brackets inside a JSON string, with its backslash escapes, are not counted. A closing
    bracket of the wrong kind is no balance: ``None``, as for one never closed.
    """
    stack: list[str] = []
    index = start
    while index < len(text):
        char = text[index]
        if char == '"':
            index = _past_string(text, index)
            continue
        if char in "{[":
            stack.append(char)
        elif char in _OPENS:
            if not stack or stack.pop() != _OPENS[char]:
                return None
            if not stack:
                return index + 1
        index += 1
    return None


def _past_string(text: str, start: int) -> int:
    """The index just past the JSON string opening at ``start``; the end where none closes."""
    index = start + 1
    while index < len(text):
        if text[index] == "\\":
            index += 2
        elif text[index] == '"':
            return index + 1
        else:
            index += 1
    return len(text)


def scout_messages(
    reading: Reading,
    instruction: RenderedPrompt,
    *,
    person: dict[str, FrozenJson] | None = None,
) -> list[Message]:
    """The scout's one call: its instruction, and the reading as quoted source data.

    Args:
        reading: What the observer read around the leaving episode.
        instruction: ``OBSERVER_SCOUT_PROMPT`` rendered from its template, default or
            override, as the composition root read it at start (ADR-0334 §3:5); the
            call's given entry records its ``prompt`` key (ADR-0335 §9:1).
        person: The leaving episode's person's five fields (ADR-0338 §7:4, §9:1), shown
            first under ``person``, ahead of what changes from call to call; ``None``
            where the step is given none, and the payload is then as it was.

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


def proposed_findings(
    reply: ScoutReply | PersonScoutReply, reading: Reading, *, numbered_from: int = 1
) -> tuple[tuple[ObservationFinding, ...], int]:
    """The findings code keeps of the scout's reply, and how many it dropped.

    Args:
        reply: The scout's parsed reply.
        reading: The reading its labels name things in.
        numbered_from: The number the first finding's id takes (``f1``, ``f2``, ...).

    Returns:
        The kept findings, each with no outcome yet, and the count of those dropped.
    """
    kept, dropped = _kept(reply, reading, numbered_from=numbered_from)
    return tuple(one for one, _ in kept), dropped


def person_proposals(
    reply: PersonScoutReply, reading: Reading, *, numbered_from: int = 1
) -> PersonProposals:
    """What the scout proposed of the person model, checked (ADR-0338 §9:2-§9:3).

    A finding marked as only restating a field, with a field and a non-blank value,
    becomes a field suggestion resting on the first part it rests on that the leaving
    episode carries and that is not the assistant's own words (ADR-0329 §8:2, §10:1), or
    on none where it rests on no such part; either way it is not committed (§9:3). A
    reliance finding restates nothing. A proposed suggestion is kept only where it names
    a field, a non-blank value and one part, by its label, that the leaving episode
    carries and that is not the assistant's own words. Whether the value is valid, held
    already, pending or dismissed is the store's to answer when it is recorded (§9:2).

    Args:
        reply: The scout's parsed reply, under the person flag.
        reading: The reading its labels name things in.
        numbered_from: The number the first finding's id takes, as
            :func:`proposed_findings` was given it for the same reply, so the two name
            the findings alike.

    Returns:
        The restating findings, the suggestions, and how many suggestions were dropped.
    """
    kept, _ = _kept(reply, reading, numbered_from=numbered_from)
    episode = reading.leaving.record.id
    restating: dict[str, ProposedSuggestion | None] = {}
    for finding, proposed in kept:
        if not isinstance(proposed, _PersonProposedFinding) or finding.relied_on is not None:
            continue
        restated = _setting(proposed.restates)
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


def _kept(
    reply: ScoutReply | PersonScoutReply, reading: Reading, *, numbered_from: int
) -> tuple[list[tuple[ObservationFinding, _ProposedFinding | None]], int]:
    """The findings kept, each beside the proposal it came from, and the count dropped.

    A finding code adds for a candidate recorded under an approval came from no proposal.
    """
    episode = reading.leaving.record.id
    leaving = reading.leaving_parts
    hints = {hint.handle: hint.effect for hint in reading.hints}
    reliances = {one.handle: one.memory.id for one in reading.reliances}
    kept: list[tuple[ObservationFinding, _ProposedFinding | None]] = []
    dropped = 0
    after = reading.leaving.record.occurred_at
    for proposed in reply.findings:
        parts = _parts(proposed.rests_on, reading)
        relied_on = None if proposed.relied_on is None else reliances.get(proposed.relied_on)
        candidate = None if proposed.candidate is None else hints.get(proposed.candidate)
        if (proposed.relied_on is not None and relied_on is None) or (
            proposed.candidate is not None and candidate is None
        ):
            # A label naming nothing shown is a malformed finding, never an ordinary one:
            # a reliance that resolves to none would otherwise be committed as a claim.
            dropped += 1
            continue
        if relied_on is None:
            kept_parts = bool(parts) and not leaving.isdisjoint(parts)
        else:
            # §14:2: what later episodes show of the reliance, and nothing else.
            kept_parts = bool(parts) and all(
                (read := reading.at(part)) is not None and read.occurred_at > after
                for part in parts
            )
        if not kept_parts:
            dropped += 1
            continue
        try:
            finding = ObservationFinding(
                id=f"f{numbered_from + len(kept)}",
                episode=episode,
                claim=proposed.claim,
                rests_on=parts,
                candidate=candidate,
                relied_on=relied_on,
            )
        except ValidationError:
            dropped += 1
            continue
        kept.append((finding, proposed))
    for hint in reading.hints:
        confirmation = hint.confirmation
        if confirmation is None:
            continue
        # A finding about a candidate the user confirmed rests on that yes, whatever
        # else the scout named: the commit step sees the words the user approved.
        kept = [
            (_resting_on_too(one, confirmation.part), source)
            if one.candidate == hint.effect and one.relied_on is None
            else (one, source)
            for one, source in kept
        ]
        if any(confirmation.part in one.rests_on and one.relied_on is None for one, _ in kept):
            continue
        added = ObservationFinding(
            id=f"f{numbered_from + len(kept)}",
            episode=episode,
            claim=confirmation.text,
            rests_on=(confirmation.part,),
            candidate=hint.effect,
        )
        kept.append((added, None))
    return kept, dropped


def _parts(handles: tuple[str, ...], reading: Reading) -> tuple[SupportPart, ...]:
    """The parts the labels name, each once; empty where any label names nothing read."""
    parts: list[SupportPart] = []
    for handle in dict.fromkeys(handles):
        read = reading.part(handle)
        if read is None:
            return ()
        parts.append(read.part)
    return tuple(parts)


def _resting_on_too(finding: ObservationFinding, part: SupportPart) -> ObservationFinding:
    """``finding``, resting on ``part`` as well where it does not already."""
    if part in finding.rests_on:
        return finding
    return finding.model_copy(update={"rests_on": (*finding.rests_on, part)})
