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
yes to its wording is the strongest warrant there is, so where the scout proposed no
finding about such a candidate, code adds one: its claim the fact the user approved,
resting on that yes.

A reply that does not parse is no proposal, never a partial one: the attempt fails and
is retried (§16:4).
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, ValidationError

from ai_assistant.core.types import Message, ObservationFinding, Role
from ai_assistant.orchestration.observer.prompts import SCOUT_INSTRUCTION

if TYPE_CHECKING:
    from ai_assistant.core.types import SupportPart
    from ai_assistant.orchestration.observer.reading import Reading

__all__ = ["ScoutReply", "parsed", "proposed_findings", "scout_messages"]


class _ProposedFinding(BaseModel):
    """One finding as the scout writes it: labels, never addresses."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    claim: str
    rests_on: tuple[str, ...] = ()
    candidate: str | None = None
    relied_on: str | None = None


class ScoutReply(BaseModel):
    """The scout's whole reply (``SCOUT_INSTRUCTION``'s shape)."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    findings: tuple[_ProposedFinding, ...] = ()


def parsed[T: BaseModel](content: str, shape: type[T]) -> T | None:
    """A reply as one object of ``shape``, or ``None``: never a partial one.

    One enclosing Markdown code fence is removed first, as the understanding stage and
    the tidy-up remove it: a deterministic normalization of a wrapper, not a repair.

    Args:
        content: The model's reply.
        shape: The model the reply must validate as.

    Returns:
        The object, or ``None`` where the reply does not validate.
    """
    body = content.strip()
    if body.startswith("```") and body.endswith("```") and len(body) >= 6:  # noqa: PLR2004 — two fences
        body = body[3:-3]
        newline = body.find("\n")
        if newline != -1 and body[:newline].strip() in {"", "json", "JSON"}:
            body = body[newline + 1 :]
    try:
        return shape.model_validate_json(body)
    except ValidationError, ValueError, RecursionError:
        return None


def scout_messages(reading: Reading) -> list[Message]:
    """The scout's one call: its instruction, and the reading as quoted source data.

    Args:
        reading: What the observer read around the leaving episode.

    Returns:
        The conversation the scout's route completes.
    """
    return [
        Message(role=Role.SYSTEM, content=SCOUT_INSTRUCTION),
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
                    candidate=None if proposed.candidate is None else hints.get(proposed.candidate),
                    relied_on=relied_on,
                )
            )
        except ValidationError:
            dropped += 1
    for hint in reading.hints:
        confirmation = hint.confirmation
        if confirmation is None or any(
            one.candidate == hint.effect or confirmation.part in one.rests_on for one in kept
        ):
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
