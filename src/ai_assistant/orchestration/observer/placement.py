"""Retrieval and placement: what is stored like a framed memory, and how it stands to each.

**Retrieval is code's** (ADR-0346 §6:1). For each memory a framing proposes, code
retrieves the stored memories, as they stand when it retrieves them, similar enough to it:
by relevance to its wording above a composition-root threshold, and every memory naming a
person it names, in either field (ADR-0345 §9:6), up to a composition-root bound. The
past is for reading and the present for writing: what is written is filed against what
is true now.

**Placement is one model call per memory** (§6:2), given the memory as framed and each
retrieved memory in a compact form code builds from the stored record: its wording,
holders and partial supporters, standing, status, the counts of its counted ``for`` and
``against`` supports and the distinct episodes they point at, its open questions, and its
most recent supports in full, up to a composition-root number. It names one of ADR-0345
§4's relations for each retrieved memory, with a note on how the two relate for every
relation but ``independent``, and at most one open question the new memory answers. The
compact form is computed, never written by a model, and the call makes no further read
(§6:3); it changes nothing of the framed memory (§6:4). Where nothing is retrieved there
is nothing to place, and no call is made.

**What code holds of a reply.** A reply that names a memory it was not shown, leaves one
unplaced, names one twice, names a relation outside the closed set, leaves out a note a
relation needs, or answers a question it was not shown, is refused as a reply that does
not parse is (ADR-0329 §16:4): a placement the writer would refuse is never sent to it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, ValidationError

from ai_assistant.core.types import (
    EpisodicMemory,
    Memory,
    MemoryKind,
    MemoryPlacement,
    Message,
    PlacedAnswer,
    PlacedPair,
    PlacedRelation,
    Placement,
    Role,
    origin_is_outside,
)
from ai_assistant.orchestration.episode_reads import without_open_episodes
from ai_assistant.orchestration.observer.reading import (
    ORIGIN_WORDS,
    STANDING_WORDS,
    holder_words,
    name_shown,
)
from ai_assistant.orchestration.support_parts import (
    episodes_to_read,
    part_content,
    remember_activations,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from ai_assistant.core.prompts import RenderedPrompt
    from ai_assistant.core.protocols import MemoryStore, PlanStore
    from ai_assistant.core.types import (
        ActivationEffect,
        FrozenJson,
        MemorySupport,
        SupportPart,
    )

__all__ = [
    "PlacementReply",
    "PlacementView",
    "Retrieved",
    "compacted",
    "narrows",
    "placement_messages",
    "placement_of",
    "retrieved",
]


class _Relation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")
    memory: str
    relation: str
    note: str = ""


class _Answer(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")
    memory: str
    question: str


class PlacementReply(BaseModel):
    """The placement call's whole reply: a relation for each memory shown (§6:2)."""

    model_config = ConfigDict(frozen=True, extra="ignore")
    relations: tuple[_Relation, ...] = ()
    answers: _Answer | None = None


@dataclass(frozen=True, slots=True)
class Retrieved:
    """One stored memory the placement call is shown, in its compact form (§6:2).

    Attributes:
        handle: Its label (``M1``, ``M2``, ...).
        memory: The memory, as read now, revision and all.
        questions: Its open questions' ids, by the labels they are shown under.
        recent: Its most recent supports, newest first, each with its part's content,
            or ``None`` where the part no longer resolves.
        supplied: The placement of every episode read to show those supports, which the
            write placed against it takes the meet of (ADR-0329 §12:6).
    """

    handle: str
    memory: Memory
    questions: dict[str, str] = field(default_factory=dict)
    recent: tuple[tuple[MemorySupport, str | None], ...] = ()
    supplied: tuple[Placement, ...] = ()

    def rendered(self) -> dict[str, FrozenJson]:
        """The compact form, computed from the stored record and never by a model."""
        memory = self.memory
        summary = memory.evidence_summary
        stopped = memory.stopped
        open_ = {question: handle for handle, question in self.questions.items()}
        return {
            "memory": self.handle,
            "wording": memory.content,
            "held_by": [holder_words(one) for one in memory.holders],
            "partly_supported_by": [holder_words(one) for one in memory.partial_supporters],
            "stands": STANDING_WORDS[memory.standing],
            "status": memory.status.value,
            "for": summary.supporting,
            "against": summary.against,
            "episodes": summary.episodes,
            "open_questions": [
                {"question": open_[one.id], "asks": one.asks}
                for one in memory.open_questions
                if one.id in open_
            ],
            "recent_supports": [
                {
                    "from": ORIGIN_WORDS[support.origin],
                    "outside": support.outside,
                    "direction": support.direction.value,
                    "backs_as_worded": support.backs_as_worded,
                    "counted": support.points_at not in stopped,
                    "at": None if support.when is None else support.when.isoformat(),
                    "text": "(gone)" if text is None else text,
                }
                for support, text in self.recent
            ],
        }


@dataclass(frozen=True, slots=True)
class PlacementView:
    """Exactly what one placement call is shown, kept so its labels map back (§6:2).

    Attributes:
        framed: The memory as framed.
        texts: The text of each part its supports point at, by part.
        retrieved: Each stored memory retrieved, in its compact form.
    """

    framed: Memory
    texts: Mapping[SupportPart, str]
    retrieved: tuple[Retrieved, ...]

    def memory(self, handle: str) -> Retrieved | None:
        """The retrieved memory a label names, among those shown."""
        return next((one for one in self.retrieved if one.handle == handle), None)

    def payload(self) -> dict[str, FrozenJson]:
        """What the placement call is shown: one JSON object of quoted source data."""
        framed = self.framed
        end = framed.validity.valid_until
        return {
            "memory": {
                "wording": framed.content,
                "supports": [
                    {
                        "from": ORIGIN_WORDS[one.origin],
                        "outside": origin_is_outside(one.origin),
                        "direction": one.direction.value,
                        "backs_as_worded": one.backs_as_worded,
                        "at": None if one.when is None else one.when.isoformat(),
                        "text": self.texts.get(one.points_at, "(not shown)"),
                    }
                    for one in framed.supports
                ],
                "subjects": [name_shown(one) for one in framed.subjects or ()],
                "involved": [name_shown(one) for one in framed.involved or ()],
                "marks": [one.value for one in framed.marks],
                "valid_until": None if end is None else end.isoformat(),
            },
            "stored": [one.rendered() for one in self.retrieved],
        }


async def retrieved(  # noqa: PLR0913 — the memory, the stores, and the root's three numbers
    framed: Memory,
    *,
    memory: MemoryStore,
    plans: PlanStore,
    threshold: float,
    bound: int,
    recent: int,
) -> tuple[Retrieved, ...]:
    """The stored memories similar enough to ``framed``, in their compact forms (§6:1).

    Those whose relevance to its wording reaches ``threshold``, then every memory naming
    a person it names, in either field, each once, up to ``bound`` in all, as the store
    holds them now. Each person's are read by the store's person filter, bound before the
    ranking cut (ADR-0345 §9:6).

    Args:
        framed: The memory as framed.
        memory: The memory store.
        plans: The plan store a remember call's effect record is read from, for a
            support's content.
        threshold: The least relevance a memory is retrieved at by its wording alone.
        bound: The most memories retrieved.
        recent: The most recent supports each is shown with in full.

    Returns:
        The memories, labelled ``M1`` onward.

    Raises:
        MemoryStoreError: If the memory store cannot be read.
        PlanningError: If the plan store cannot be read.
    """
    if bound < 1:
        return ()
    found: dict[str, Memory] = {}
    relevant = await memory.search(framed.content, limit=bound, kinds=(MemoryKind.MEMORY,))
    for one in relevant.records:
        if isinstance(one, Memory) and (one.score or 0.0) >= threshold:
            found.setdefault(one.id, one)
    for person in dict.fromkeys((*(framed.subjects or ()), *(framed.involved or ()))):
        if len(found) >= bound:
            break
        named = await memory.search(
            framed.content, limit=bound, kinds=(MemoryKind.MEMORY,), person=person
        )
        for one in named.records:
            if isinstance(one, Memory):
                found.setdefault(one.id, one)
    memories = [one for one in found.values() if one.id != framed.id][:bound]
    return await compacted(memories, memory=memory, plans=plans, recent=recent)


async def compacted(
    memories: Sequence[Memory], *, memory: MemoryStore, plans: PlanStore, recent: int
) -> tuple[Retrieved, ...]:
    """Each memory with its open questions labelled and its recent supports resolved.

    Args:
        memories: The stored memories, as read.
        memory: The memory store the episodes their supports point into are read from.
        plans: The plan store a remember call's effect record is read from.
        recent: The most recent supports each is shown with in full.

    Returns:
        The memories, labelled ``M1`` onward, each with the placement of every episode
        read to show it.

    Raises:
        MemoryStoreError: If the memory store cannot be read.
        PlanningError: If the plan store cannot be read.
    """
    if not memories:
        return ()
    newest = {
        one.id: sorted(one.supports, key=lambda support: support.added_at, reverse=True)[
            : max(recent, 0)
        ]
        for one in memories
    }
    shown = [one.model_copy(update={"supports": tuple(newest[one.id])}) for one in memories]
    found = without_open_episodes(await memory.get_many(list(episodes_to_read(shown))))
    episodes = {key: one for key, one in found.items() if isinstance(one, EpisodicMemory)}
    activations = remember_activations(shown, episodes)
    effects: dict[str, ActivationEffect] = {}
    if activations:
        effects = {one.id: one for one in await plans.activation_effects(list(activations))}
    compact: list[Retrieved] = []
    asked = 0
    for index, one in enumerate(memories, start=1):
        questions: dict[str, str] = {}
        for question in one.open_questions:
            if not question.resolved:
                asked += 1
                questions[f"Q{asked}"] = question.id
        # Every episode read to show its supports, a confirmation's asking one included,
        # since its text is what is shown (ADR-0329 §12:6).
        read = episodes_to_read([one.model_copy(update={"supports": tuple(newest[one.id])})])
        compact.append(
            Retrieved(
                handle=f"M{index}",
                memory=one,
                questions=questions,
                supplied=tuple(episodes[key].placement for key in read if key in episodes),
                recent=tuple(
                    (
                        support,
                        part_content(
                            support.points_at,
                            episodes=episodes,
                            effects=effects,
                            carried=support.carries,
                        ),
                    )
                    for support in newest[one.id]
                ),
            )
        )
    return tuple(compact)


def narrows(supply: Placement, target: Memory) -> bool:
    """Whether a write resting on ``supply`` would reach fewer people than ``target`` does.

    The meet over the two is narrower in reach than the target's placement, or decided by
    a stronger setter (ADR-0217 §3:3). An operation on a stored memory writes no placement
    (ADR-0328 §5:2), so a relation's supports, notes and questions written onto such a
    memory would carry what ``supply`` holds to people it may not reach.

    Args:
        supply: The placement the write rests on.
        target: The stored memory.

    Returns:
        Whether writing onto ``target`` would widen what ``supply`` reaches.
    """
    held = target.placement
    meet = Placement.narrowest_of((supply, held))
    return meet.reach is not held.reach or meet.set_by is not held.set_by


def placement_messages(view: PlacementView, instruction: RenderedPrompt) -> list[Message]:
    """The placement call for a framed memory: its instruction and what it is shown.

    Args:
        view: What the call is shown.
        instruction: ``OBSERVER_PLACEMENT_PROMPT`` rendered from its template, default or
            override, as the composition root read it at start (ADR-0334 §3:5).

    Returns:
        The conversation the placement route completes.
    """
    return [
        Message(role=Role.SYSTEM, content=instruction.text),
        Message(role=Role.USER, content=json.dumps(view.payload(), ensure_ascii=True)),
    ]


def placement_of(reply: PlacementReply, view: PlacementView) -> MemoryPlacement | None:
    """The placement a reply states, or ``None`` where it does not state one (§6:2).

    Each memory shown is named once, by a relation of ADR-0345 §4's set, with a note for
    every relation but ``independent``; at most one open question it answers, on a memory
    it names, by a label it was shown. The revision is the one each was read at (§6:6).

    Args:
        reply: The placement call's parsed reply.
        view: What it was shown.

    Returns:
        The placement, or ``None``, refused as a reply that does not parse.
    """
    named: dict[str, _Relation] = {}
    for one in reply.relations:
        if view.memory(one.memory) is None or one.memory in named:
            return None
        named[one.memory] = one
    if set(named) != {one.handle for one in view.retrieved}:
        return None
    try:
        pairs = tuple(
            PlacedPair(
                memory=one.memory.id,
                revision=one.memory.revision,
                relation=PlacedRelation(named[one.handle].relation.strip()),
                note=named[one.handle].note.strip(),
            )
            for one in view.retrieved
        )
        answers = None
        if reply.answers is not None:
            shown = view.memory(reply.answers.memory)
            question = None if shown is None else shown.questions.get(reply.answers.question)
            if shown is None or question is None:
                return None
            answers = PlacedAnswer(memory=shown.memory.id, question=question)
        return MemoryPlacement(pairs=pairs, answers=answers)
    except ValueError, ValidationError:
        return None
