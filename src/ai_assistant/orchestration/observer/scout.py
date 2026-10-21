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
in the prose is never read as an empty answer; and an object is never looked inside, so a
nested piece of a malformed answer is never read as the answer.
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Final

from pydantic import BaseModel, ConfigDict, ValidationError

from ai_assistant.core.types import Message, ObservationFinding, Role

if TYPE_CHECKING:
    from ai_assistant.core.prompts import RenderedPrompt
    from ai_assistant.core.types import SupportPart
    from ai_assistant.orchestration.observer.reading import Reading

__all__ = ["ScoutReply", "parsed", "proposed_findings", "scout_messages"]


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


#: A fenced block anywhere in a reply: its tag is group 1, its body group 2. Every fence is
#: paired, whatever its tag, so one block's closing fence never opens the next.
_FENCED: Final = re.compile(r"```([^\n`]*)\n(.*?)```", re.DOTALL)


def parsed[T: BaseModel](content: str, shape: type[T]) -> T | None:
    """A reply as one object of ``shape``, or ``None``: never a partial one.

    The whole reply is read first, with one enclosing Markdown code fence removed, as the
    understanding stage and the tidy-up remove it: a deterministic normalization of a
    wrapper, not a repair. Where the whole reply is not that object, because the model
    wrote prose around it, the object is looked for in the text: a fenced block, the last
    that validates; else an object standing on its own in the text, the last that
    validates. An object found in the text counts only where it names a field of
    ``shape``, and a nested object is never a candidate, only one standing at the top.

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
    fenced = [
        match.group(2)
        for match in _FENCED.finditer(content)
        if match.group(1).strip() in {"", "json", "JSON"}
    ]
    for candidate in (*reversed(fenced), *reversed(_top_level_objects(content))):
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


def _top_level_objects(text: str) -> list[str]:
    """The JSON objects standing on their own in ``text``, in order; none nested.

    Each ``{`` outside an object found so far starts a candidate. One that decodes is
    taken whole and the scan resumes after it; one that does not is skipped as far as its
    braces balance, so nothing inside a malformed object is ever a candidate. A ``{``
    whose braces never balance ends the scan, since what follows may be inside it.
    """
    decoder = json.JSONDecoder()
    found: list[str] = []
    start = text.find("{")
    while start != -1:
        try:
            value, end = decoder.raw_decode(text, start)
        except ValueError, RecursionError:
            balanced = _balanced_end(text, start)
            if balanced is None:
                break
            end = balanced
        else:
            if isinstance(value, dict):
                found.append(text[start:end])
        start = text.find("{", end)
    return found


def _balanced_end(text: str, start: int) -> int | None:
    """The index just past the ``}`` closing the ``{`` at ``start``, or ``None``.

    Braces inside a JSON string, with its backslash escapes, are not counted.
    """
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index + 1
    return None


def scout_messages(reading: Reading, instruction: RenderedPrompt) -> list[Message]:
    """The scout's one call: its instruction, and the reading as quoted source data.

    Args:
        reading: What the observer read around the leaving episode.
        instruction: ``OBSERVER_SCOUT_PROMPT`` rendered from its template, default or
            override, as the composition root read it at start (ADR-0334 §3:5); the
            call's given entry records its ``prompt`` key (ADR-0335 §9:1).

    Returns:
        The conversation the scout's route completes.
    """
    return [
        Message(role=Role.SYSTEM, content=instruction.text),
        Message(role=Role.USER, content=json.dumps(reading.payload(), ensure_ascii=True)),
    ]


def proposed_findings(
    reply: ScoutReply, reading: Reading, *, numbered_from: int = 1
) -> tuple[tuple[ObservationFinding, ...], int]:
    """The findings code keeps of the scout's reply, and how many it dropped.

    Args:
        reply: The scout's parsed reply.
        reading: The reading its labels name things in.
        numbered_from: The number the first finding's id takes (``f1``, ``f2``, ...).

    Returns:
        The kept findings, each with no outcome yet, and the count of those dropped.
    """
    episode = reading.leaving.record.id
    leaving = reading.leaving_parts
    hints = {hint.handle: hint.effect for hint in reading.hints}
    reliances = {one.handle: one.memory.id for one in reading.reliances}
    kept: list[ObservationFinding] = []
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
            kept.append(
                ObservationFinding(
                    id=f"f{numbered_from + len(kept)}",
                    episode=episode,
                    claim=proposed.claim,
                    rests_on=parts,
                    candidate=candidate,
                    relied_on=relied_on,
                )
            )
        except ValidationError:
            dropped += 1
    for hint in reading.hints:
        confirmation = hint.confirmation
        if confirmation is None:
            continue
        # A finding about a candidate the user confirmed rests on that yes, whatever
        # else the scout named: the commit step sees the words the user approved.
        kept = [
            _resting_on_too(one, confirmation.part)
            if one.candidate == hint.effect and one.relied_on is None
            else one
            for one in kept
        ]
        if any(confirmation.part in one.rests_on and one.relied_on is None for one in kept):
            continue
        kept.append(
            ObservationFinding(
                id=f"f{numbered_from + len(kept)}",
                episode=episode,
                claim=confirmation.text,
                rests_on=(confirmation.part,),
                candidate=hint.effect,
            )
        )
    return tuple(kept), dropped


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
