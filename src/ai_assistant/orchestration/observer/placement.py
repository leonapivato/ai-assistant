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

**What code holds of a reply** (#3398). A placement the writer would refuse is never sent
to it, and a reply is read pair by pair rather than refused whole for one pair, so the same
reply to the same input cannot fail an attempt every time it is retried:

- a pair naming a relation outside the closed set, or leaving out a note its relation
  needs, is read as ``unclear``, with a code-owned note saying the reply placed nothing
  readable there (ADR-0345 §4:3): it writes nothing on the stored memory, and the outcome
  keeps it (ADR-0346 §6:5);
- a memory shown that the reply leaves unplaced, or names more than once, is ``unclear``
  likewise, and a pair naming a memory it was not shown is set aside;
- ``answers`` may be one object, a list or null: the first entry naming an open question
  shown, on a memory shown, is the one answered (§6:2's at most one), and every other entry
  is set aside, never failing the attempt;
- a ``recheck`` on a memory already holding an open ``recheck`` question is placed as
  named, and the writer raises nothing for it (ADR-0348 §4:1), so the relation and its
  note are kept beside what is set aside, where the diagnostic record shows them (§4:2).

What code set aside goes to the diagnostic record. A reply placing no memory shown readably
at all is no placement, and is refused as a reply that does not parse is (ADR-0329
§16:4), to be retried.

**No label of the call reaches stored text** (#3402). A relation's note is carried by
every support and operation its write makes, and a ``recheck`` asks in its words
(ADR-0345 §5:7, §5:9). So the call's labels are chosen to stand nowhere, as a word, in the
data it is shown (:func:`labelled`): where a wording says "an M1 Mac", the memories are
labelled from ``M2``. Every label of the call a note cites is then a reference, never the
data's own text, and is put in words: a memory's label by its wording, a question's by
what it asks.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, replace
from itertools import count
from typing import TYPE_CHECKING, Final, Self

from pydantic import BaseModel, ConfigDict, JsonValue, ValidationError, model_validator

from ai_assistant.core.types import (
    EpisodicMemory,
    Memory,
    MemoryKind,
    MemoryPlacement,
    Message,
    OpenQuestionKind,
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
    requests_to_read,
)

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping, Sequence, Set

    from ai_assistant.core.prompts import RenderedPrompt
    from ai_assistant.core.protocols import MemoryStore, PlanStore
    from ai_assistant.core.types import (
        ActivationEffect,
        FrozenJson,
        MemorySupport,
        SupportPart,
    )

__all__ = [
    "RECHECK_HELD",
    "UNREAD_NOTE",
    "PlacementRead",
    "PlacementReply",
    "PlacementView",
    "Retrieved",
    "compacted",
    "in_words",
    "labelled",
    "narrows",
    "placement_messages",
    "placement_of",
    "retrieved",
]


#: The note code gives a pair the reply placed nothing readable on (ADR-0345 §4:3): its
#: relation is ``unclear``, which writes nothing on the stored memory.
UNREAD_NOTE: Final = "the placement call named no relation of the set, with its note, here"

#: Why a ``recheck`` on a memory already holding an open one is set aside (ADR-0348 §4:2).
RECHECK_HELD: Final = (
    "the memory already holds an open recheck question, so the writer raises no second one"
)

#: A label the placement call is shown, as a note may cite it: a memory's or a question's.
_LABEL: Final = re.compile(r"\b[MQ][0-9]+\b")

#: The keys of a call's payload whose values are its labels, not data it is shown.
_LABEL_KEYS: Final = frozenset({"memory", "question"})


class _Relation(BaseModel):
    """One relation as the placement call names it, read as ``unclear`` where unreadable.

    A relation outside ADR-0345 §4's set, or one left without the note it needs (§4:1),
    is read as ``unclear`` with :data:`UNREAD_NOTE`, so what the stage reads of a reply is
    what any reader of this shape reads of it.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")
    memory: str | None = None
    relation: str | None = None
    note: str | None = None

    @model_validator(mode="after")
    def _of_the_set_with_its_note(self) -> Self:
        named = (self.relation or "").strip()
        note = (self.note or "").strip()
        relation = next((one for one in PlacedRelation if one.value == named), None)
        if relation is None or (relation is not PlacedRelation.INDEPENDENT and not note):
            return self.model_copy(
                update={"relation": PlacedRelation.UNCLEAR.value, "note": UNREAD_NOTE}
            )
        return self


class PlacementReply(BaseModel):
    """The placement call's whole reply: a relation for each memory shown (§6:2).

    ``answers`` is read by :func:`placement_of`, as one object, a list of them or null. A
    reply naming no relation readably is no placement, and does not parse, so any reader
    of this shape refuses it as the stage does (ADR-0329 §16:4).
    """

    model_config = ConfigDict(frozen=True, extra="ignore")
    relations: tuple[_Relation, ...] = ()
    answers: JsonValue = None

    @model_validator(mode="after")
    def _places_something(self) -> Self:
        if not any(
            one.note != UNREAD_NOTE and (one.memory or "").strip() for one in self.relations
        ):
            msg = "a placement names some relation of the set, with its note (ADR-0346 §6:2)"
            raise ValueError(msg)
        return self


@dataclass(frozen=True, slots=True)
class PlacementRead:
    """The placement a reply states, and what code set aside of the reply to state it.

    Attributes:
        placement: The placement, every memory shown named once.
        set_aside: Each piece of the reply code did not take as it stood, with why, for
            the diagnostic record (ADR-0333 §2:5): a pair read as ``unclear``, a pair
            naming a memory not shown, and every answer but the one taken; and each
            ``recheck`` the writer raises nothing for, with its note (ADR-0348 §4:2).
    """

    placement: MemoryPlacement
    set_aside: tuple[dict[str, FrozenJson], ...] = ()


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
    siblings: Set[str] = frozenset(),
) -> tuple[Retrieved, ...]:
    """The stored memories similar enough to ``framed``, in their compact forms (§6:1).

    Those whose relevance to its wording reaches ``threshold``, then every memory naming
    a person it names, in either field, each once, up to ``bound`` in all, as the store
    holds them now. Each person's are read by the store's person filter, bound before the
    ranking cut (ADR-0345 §9:6).

    A memory framed from the same finding is a sibling, not prior knowledge, and is never
    retrieved for it (#3401): siblings usually rest on the same part, so a fold onto one
    adds nothing, and a wrong ``contained`` would lose the claim with no write to show it.

    Args:
        framed: The memory as framed.
        memory: The memory store.
        plans: The plan store a remember call's effect record is read from, for a
            support's content.
        threshold: The least relevance a memory is retrieved at by its wording alone.
        bound: The most memories retrieved.
        recent: The most recent supports each is shown with in full.
        siblings: The ids of the memories framed from the same finding, as installed.

    Returns:
        The memories, labelled ``M1`` onward.

    Raises:
        MemoryStoreError: If the memory store cannot be read.
        PlanningError: If the plan store cannot be read.
    """
    if bound < 1:
        return ()
    left_out = {framed.id, *siblings}
    # Searched past the bound by as many siblings as may be left out, so the bound fills.
    limit = bound + len(siblings)
    found: dict[str, Memory] = {}
    relevant = await memory.search(framed.content, limit=limit, kinds=(MemoryKind.MEMORY,))
    for one in relevant.records:
        if isinstance(one, Memory) and one.id not in left_out and (one.score or 0.0) >= threshold:
            found.setdefault(one.id, one)
    for person in dict.fromkeys((*(framed.subjects or ()), *(framed.involved or ()))):
        if len(found) >= bound:
            break
        named = await memory.search(
            framed.content, limit=limit, kinds=(MemoryKind.MEMORY,), person=person
        )
        for one in named.records:
            if isinstance(one, Memory) and one.id not in left_out:
                found.setdefault(one.id, one)
    memories = list(found.values())[:bound]
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
    # ADR-0361 §5:10: a confirmation of the request form reads its request.
    approving = requests_to_read(shown)
    requests = (
        {str(one.id): one for one in await plans.approval_requests(list(approving))}
        if approving
        else {}
    )
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
                            requests=requests,
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


def placement_of(reply: PlacementReply, view: PlacementView) -> PlacementRead | None:
    """The placement a reply states, or ``None`` where it places nothing shown (§6:2).

    Each memory shown is named once, by the one pair the reply names it in where that pair
    is readable, and as ``unclear`` with :data:`UNREAD_NOTE` where the reply leaves it
    unplaced, names it twice, or names no relation of the set with its note there (ADR-0345
    §4:3). A pair naming a memory not shown is set aside. The answer is the first entry of
    ``answers`` naming a question shown, on a memory shown; every other is set aside. Each
    note's labels are put in words (:func:`in_words`). The revision is the one each was read
    at (§6:6).

    Args:
        reply: The placement call's parsed reply.
        view: What it was shown.

    Returns:
        The placement and what was set aside of the reply, or ``None``, refused as a reply
        that does not parse, where no memory shown is placed readably.
    """
    aside: list[dict[str, FrozenJson]] = []
    named: dict[str, list[_Relation]] = {}
    for one in reply.relations:
        label = (one.memory or "").strip()
        if view.memory(label) is None:
            aside.append({"memory": label, "why": "no memory was shown under this label"})
            continue
        named.setdefault(label, []).append(one)
    pairs: list[PlacedPair] = []
    readable = False
    for shown in view.retrieved:
        given = named.get(shown.handle, [])
        relation, note = PlacedRelation.UNCLEAR, UNREAD_NOTE
        if len(given) == 1 and given[0].note != UNREAD_NOTE:
            relation = PlacedRelation((given[0].relation or "").strip())
            note = in_words((given[0].note or "").strip(), view)
            readable = True
            if relation is PlacedRelation.RECHECK and _held_open(shown.memory):
                # ADR-0348 §4:2: the writer raises no second check, so the relation and its
                # note are kept here, where the diagnostic record shows them.
                aside.append(
                    {
                        "memory": shown.handle,
                        "relation": relation.value,
                        "note": note,
                        "why": RECHECK_HELD,
                    }
                )
        elif given:
            why = "named more than once" if len(given) > 1 else "no relation of the set"
            aside.append({"memory": shown.handle, "why": why})
        else:
            aside.append({"memory": shown.handle, "why": "left unplaced"})
        try:
            pairs.append(
                PlacedPair(
                    memory=shown.memory.id,
                    revision=shown.memory.revision,
                    relation=relation,
                    note=note,
                )
            )
        except ValidationError:
            return None
    if not readable:
        return None
    answers, unanswered = _answered(reply.answers, view)
    aside.extend(unanswered)
    try:
        placement = MemoryPlacement(pairs=tuple(pairs), answers=answers)
    except ValidationError:
        return None
    return PlacementRead(placement=placement, set_aside=tuple(aside))


def _held_open(memory: Memory) -> bool:
    """Whether ``memory`` already holds an open ``recheck`` question (ADR-0348 §4:1)."""
    return any(
        question.kind is OpenQuestionKind.RECHECK and not question.resolved
        for question in memory.open_questions
    )


def _answered(
    answers: JsonValue, view: PlacementView
) -> tuple[PlacedAnswer | None, list[dict[str, FrozenJson]]]:
    """The one question a reply's ``answers`` names, and every other entry, set aside.

    One object, a list of them or null (#3398): the first entry naming an open question
    shown, on a memory shown, is taken, as ADR-0346 §6:2 allows one; the rest are set
    aside with why, never refusing the reply.
    """
    entries = answers if isinstance(answers, list) else [] if answers is None else [answers]
    taken: PlacedAnswer | None = None
    aside: list[dict[str, FrozenJson]] = []
    for entry in entries:
        memory = entry.get("memory") if isinstance(entry, dict) else None
        question = entry.get("question") if isinstance(entry, dict) else None
        shown = view.memory(memory.strip()) if isinstance(memory, str) else None
        asked = (
            shown.questions.get(question.strip())
            if shown is not None and isinstance(question, str)
            else None
        )
        if shown is None or asked is None:
            aside.append({"answer": entry, "why": "no open question shown under these labels"})
        elif taken is not None:
            aside.append({"answer": entry, "why": "a placement answers one question at most"})
        else:
            taken = PlacedAnswer(memory=shown.memory.id, question=asked)
    return taken, aside


def labelled(view: PlacementView) -> PlacementView:
    """``view`` with its labels chosen to stand nowhere, as a word, in its data (#3402).

    The memories are labelled ``M`` and their open questions ``Q``, numbered from 1 in the
    order shown, each skipping any label that stands in a text the call is shown: a
    wording, a support's text, a question, a holder. So a label a note cites is always a
    reference to what the call was shown, never the data's own text, such as "an M1 Mac"
    or "Q1 sales", and :func:`in_words` can put every one in words.

    Args:
        view: What the call is shown, labelled in any way.

    Returns:
        The same view, labelled so.
    """
    taken = {
        match.group(0) for text in _data_texts(view.payload()) for match in _LABEL.finditer(text)
    }
    memories = _free("M", taken)
    questions = _free("Q", taken)
    return replace(
        view,
        retrieved=tuple(
            replace(
                one,
                handle=next(memories),
                questions={next(questions): question for question in one.questions.values()},
            )
            for one in view.retrieved
        ),
    )


def _free(prefix: str, taken: Set[str]) -> Iterator[str]:
    """``prefix`` numbered from 1, each label in ``taken`` skipped."""
    return (label for number in count(1) if (label := f"{prefix}{number}") not in taken)


def _data_texts(value: object, key: str | None = None) -> Iterator[str]:
    """Every text in a call's payload but its labels: the data the call is shown."""
    if isinstance(value, dict):
        for name, inner in value.items():
            yield from _data_texts(inner, str(name))
    elif isinstance(value, list | tuple):
        for inner in value:
            yield from _data_texts(inner, key)
    elif isinstance(value, str) and key not in _LABEL_KEYS:
        yield value


def in_words(note: str, view: PlacementView) -> str:
    """``note`` with every label the call was shown put in words (#3402).

    A memory's label becomes its wording, quoted, and a question's what it asks, quoted:
    the labels are the call's own, and mean nothing, or something else, once the note is
    stored (ADR-0345 §5:7). The call's labels stand nowhere in its data (:func:`labelled`),
    so each is a reference. A label the call was not shown is left as written: it names
    nothing the call was given, and may be the data's own text, as "an M1 Mac" is where the
    memories were labelled from ``M2``.

    Args:
        note: A relation's note as the reply gives it.
        view: What the call was shown.

    Returns:
        The note, citing no label of the call.
    """
    asks: dict[str, str] = {}
    for one in view.retrieved:
        wanted = {question: label for label, question in one.questions.items()}
        for question in one.memory.open_questions:
            if question.id in wanted:
                asks[wanted[question.id]] = question.asks

    def worded(match: re.Match[str]) -> str:
        label = match.group(0)
        shown = view.memory(label)
        if shown is not None:
            return json.dumps(shown.memory.content, ensure_ascii=False)
        if label in asks:
            return json.dumps(asks[label], ensure_ascii=False)
        return label

    return _LABEL.sub(worded, note)
