"""Framing: one model call per finding, and the checks code makes (ADR-0346 §5, §7, §9).

**What the call is given** (§5:1): only the finding's claim; the parts it rests on, each
with the message it answers where it is a reply; the scout's annotations; and the
person's profile fields where the person model is on. No stored memory is shown to it,
so a framing is worded from what the finding rests on alone. Each part names the exchange
it belongs to by a label handed out afresh for the call, and when that exchange occurred,
read from the record; the exchange under review, the leaving episode, is always ``E1``.

**What it proposes** (§5:2): one or more memories, each with its wording, its supports and
each one's direction, backing, how sure, about-when and note; its ``subjects`` and
``involved``; its situation labels (§9:1); its marks; a validity end where its supports
name one (ADR-0345 §6); and, under the person model, the style and pin judgements
ADR-0338 §9:4-§9:5 name. Or that nothing in the finding is worth keeping, with a reason
(§5:6). Framing judges evidence, not importance: the scout already judged the finding
worth keeping.

**What code sets and checks** (§5:4), each memory on its own: a memory that fails a check
is not written, and the others stand. Code sets each support's origin, ``when`` and who
added it from the part it points at (ADR-0329 §9:5), and the holder is the writer's to
set (ADR-0345 §2:2); it checks that:

- every support points at a part the finding rests on, each part once, and at least one
  ``for`` support points at the leaving episode (§3:1);
- some support backs the memory as worded, and the create cites the strongest of them;
- a wording a person approved is the memory's wording exactly, backed by its own
  confirmation (§5:3, ADR-0329 §5:5), and every approved wording the finding rests on is
  framed: where the call frames none of them, code frames it, in exactly the words
  approved, as a memory of its own;
- ``subjects`` and ``involved`` are each given, a person in one of them at most, and every
  name is one a part the memory rests on gives (§5:5, ADR-0345 §9:3);
- a round's message backs only a record of the saying, marked ``assistant_statement`` and
  ``occasion``; a memory marked ``assistant_statement`` cites a round's message; and one
  that takes on what a round's message claims rests on the person's request, agreement or
  confirmation in the leaving episode, which backs it as worded (§7:6-§7:9);
- an ``occasion`` carries no validity end, and an end lies in the future and is the
  about-when of the support the create cites (ADR-0345 §6:1, §8:4);
- no memory stands on inference alone (§7:2).

Its situation labels are kept within the composition root's bounds (ADR-0345 §7:3), each
the framing's suggestion from the scout's (§9:1), recorded as the observer's at the
create, the leaving episode suggesting it. The narrowing the scout proposed is carried
onto each memory at its create, within ADR-0217 §4's bounds (§5:7), by the placement step
that builds the proposal.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Final, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, JsonValue, ValidationError

from ai_assistant.core.types import (
    OWNER_PERSON_ID,
    ConfirmationPart,
    Memory,
    MemoryMark,
    MemoryOperation,
    MemoryOperationKind,
    MemoryStanding,
    MemorySupport,
    MemoryWriterName,
    Message,
    Placement,
    ReadingCertainty,
    Role,
    SituationLabel,
    SupportDirection,
    SupportOrigin,
    Validity,
    origin_standing,
    part_episode,
    standing_rank,
)
from ai_assistant.orchestration.observer.reading import name_shown, name_stored

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence
    from datetime import datetime

    from ai_assistant.core.prompts import RenderedPrompt
    from ai_assistant.core.types import (
        EpisodicMemory,
        FrozenJson,
        LabelBounds,
        ObservationFinding,
        SupportPart,
    )
    from ai_assistant.orchestration.observer.reading import Reading, ReadPart

__all__ = [
    "Framed",
    "Framing",
    "FramingReply",
    "FramingView",
    "framed",
    "framing_messages",
    "framing_view",
]

#: The origins of the assistant's own words (ADR-0345 §2's table).
_ASSISTANT_ORIGINS: Final = frozenset(
    {SupportOrigin.ASSISTANT_MESSAGE, SupportOrigin.ASSISTANT_MESSAGE_OVER_OUTSIDE}
)

#: The origins of a person's own word in an episode, which may take on what a round's
#: message claims (ADR-0346 §7:6, §7:9).
_PERSON_ORIGINS: Final = frozenset({SupportOrigin.USER_MESSAGE, SupportOrigin.CONFIRMATION})

#: §2:4, §8:3: the marks a record of the saying carries.
_RECORD_OF_SAYING: Final = frozenset({MemoryMark.ASSISTANT_STATEMENT, MemoryMark.OCCASION})

#: The note on the create of a memory code frames for an approved wording (§5:3).
_APPROVED_NOTE: Final = "the user approved this wording"

type _Certainty = Literal["sure", "likely", "unsure"]


class _FramedSupport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")
    part: str
    direction: Literal["for", "against"]
    backs_as_worded: bool = False
    how_sure: _Certainty
    about_when: AwareDatetime | None = None
    note: str = ""


class _FramedMemory(BaseModel):
    """One memory as the framing call proposes it (ADR-0346 §5:2).

    ``subjects`` and ``involved`` are each a list, possibly empty, and never left out:
    one left out fails that memory's check, never the reply. ``style`` and ``pin`` are
    read only where the call was given a person's fields, and count only where ``true``.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")
    wording: str
    supports: tuple[_FramedSupport, ...] = ()
    subjects: tuple[str, ...] | None = None
    involved: tuple[str, ...] | None = None
    labels: tuple[str, ...] = ()
    marks: tuple[str, ...] = ()
    valid_until: AwareDatetime | None = None
    note: str = ""
    style: JsonValue = None
    pin: JsonValue = None


class FramingReply(BaseModel):
    """The framing call's whole reply: memories, or nothing with a reason (§5:2, §5:6)."""

    model_config = ConfigDict(frozen=True, extra="ignore")
    memories: tuple[_FramedMemory, ...] = ()
    nothing: str | None = None


@dataclass(frozen=True, slots=True)
class FramingView:
    """Exactly what one framing call is shown, kept so its labels map back (§5:1).

    Attributes:
        finding: The finding.
        leaving: The leaving episode.
        parts: The parts the finding rests on, as read, labelled ``P1`` to ``Pn``.
    """

    finding: ObservationFinding
    leaving: EpisodicMemory
    parts: tuple[ReadPart, ...]

    def part(self, handle: str) -> ReadPart | None:
        """The part a label names, among those shown."""
        return next((one for one in self.parts if one.handle == handle), None)

    def exchanges(self) -> dict[str, str]:
        """Each exchange the call shows, its episode's id to its label, ``E1`` the leaving."""
        episodes = [self.leaving.id, *(one.episode for one in self.parts)]
        return {episode: f"E{index}" for index, episode in enumerate(dict.fromkeys(episodes), 1)}

    def payload(self) -> dict[str, FrozenJson]:
        """What the framing call is shown: one JSON object of quoted source data (§5:1)."""
        exchanges = self.exchanges()
        annotations = self.finding.annotations
        shown: dict[str, FrozenJson] = {
            "claim": self.finding.claim,
            "under_review": exchanges[self.leaving.id],
            "parts": [
                one.rendered(answers=True, exchange=exchanges[one.episode]) for one in self.parts
            ],
        }
        if annotations is not None:
            narrowing = annotations.narrowing
            shown |= {
                "subjects": [name_shown(one) for one in annotations.subjects],
                "involved": [name_shown(one) for one in annotations.involved],
                "why": annotations.why,
                "situations": list(annotations.situations),
                "narrowing": None
                if narrowing is None
                else {"reach": narrowing.reach.value, "note": narrowing.note},
            }
        return shown


@dataclass(frozen=True, slots=True)
class Framed:
    """One memory a framing proposed, after code's checks (ADR-0346 §5:4).

    Attributes:
        memory: The memory as it would be created, its placement not yet set: the
            proposal sets it from the supply and the narrowing (§5:7, ADR-0329 §12:6).
        texts: The text of each part its supports point at, by part, which the
            placement call is shown it with.
        style: Whether the call said it states how the person wants to be spoken to
            (ADR-0338 §9:4), read only under the person model.
        pin: Whether the call said it matters in every conversation (§9:5).
    """

    memory: Memory
    texts: Mapping[SupportPart, str]
    style: bool = False
    pin: bool = False


@dataclass(frozen=True, slots=True)
class Framing:
    """What one framing call decided, after code's checks (§5).

    Attributes:
        memories: The memories that passed every check, in the order proposed, any code
            framed for an approved wording last.
        failed: How many proposed memories failed a check and are not written.
        nothing: The call's reason where it decided nothing is worth keeping (§5:6).
        notes: For each memory proposed, its wording and, where it failed, why: what the
            diagnostic record shows of the decision (ADR-0333 §2:5).
    """

    memories: tuple[Framed, ...]
    failed: int = 0
    nothing: str | None = None
    notes: tuple[dict[str, FrozenJson], ...] = ()


def framing_view(finding: ObservationFinding, reading: Reading) -> FramingView | None:
    """What one framing call is shown for ``finding`` (§5:1).

    Each part the finding rests on is taken from the reading, which reads the same
    record every attempt, and labelled afresh for the call, ``P1`` to ``Pn``.

    Args:
        finding: The finding.
        reading: This attempt's reading.

    Returns:
        The view, or ``None`` where a part it rests on is no longer read: the episode it
        is a part of has gone since the finding was proposed, and the finding fails its
        check (ADR-0329 §9:5).
    """
    parts: list[ReadPart] = []
    for index, part in enumerate(finding.rests_on, start=1):
        read = reading.at(part)
        if read is None:
            return None
        parts.append(_relabelled(read, f"P{index}"))
    return FramingView(finding=finding, leaving=reading.record, parts=tuple(parts))


def _relabelled(read: ReadPart, handle: str) -> ReadPart:
    return replace(read, handle=handle)


def framing_messages(
    view: FramingView,
    instruction: RenderedPrompt,
    *,
    person: dict[str, FrozenJson] | None = None,
) -> list[Message]:
    """The framing call for a finding: its instruction and what it is shown (§5:1).

    Args:
        view: What the call is shown.
        instruction: ``OBSERVER_FRAMING_PROMPT`` rendered from its template, default or
            override, as the composition root read it at start (ADR-0334 §3:5).
        person: The leaving episode's person's five fields (ADR-0338 §9:1), shown first
            under ``person``; ``None`` where the call is given none.

    Returns:
        The conversation the framing route completes.
    """
    payload = view.payload()
    if person is not None:
        payload = {"person": person, **payload}
    return [
        Message(role=Role.SYSTEM, content=instruction.text),
        Message(role=Role.USER, content=json.dumps(payload, ensure_ascii=True)),
    ]


class _Refused(Exception):  # noqa: N818 — a control-flow signal carrying a code-owned reason
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True, slots=True)
class _Context:
    view: FramingView
    now: datetime
    mint: Callable[[], str]
    labels: LabelBounds
    person: bool


def framed(  # noqa: PLR0913 — the reply, what it was shown, and code's own values
    reply: FramingReply,
    view: FramingView,
    *,
    now: datetime,
    mint: Callable[[], str],
    labels: LabelBounds,
    person: bool = False,
) -> Framing:
    """A framing call's decision after every check code makes (ADR-0346 §5:4).

    Args:
        reply: The framing call's parsed reply.
        view: What it was shown.
        now: The instant every support, operation and label is stamped with.
        mint: Mints the fresh part of a new memory's id.
        labels: The composition root's bounds on a memory's labels (ADR-0345 §7:3).
        person: Whether the call was given a person's fields, so its style and pin
            judgements are read (ADR-0338 §9:4-§9:5).

    Returns:
        The memories that pass, how many failed, and the call's reason where it kept
        nothing.
    """
    context = _Context(view=view, now=now, mint=mint, labels=labels, person=person)
    memories: list[Framed] = []
    notes: list[dict[str, FrozenJson]] = []
    failed = 0
    for proposed in reply.memories:
        try:
            one = _checked(proposed, context)
        except _Refused as refused:
            failed += 1
            notes.append({"wording": proposed.wording, "refused": refused.reason})
            continue
        memories.append(one)
        notes.append({"wording": one.memory.content, "refused": None})
    for approved in _unframed_approvals(view, memories):
        memories.append(_approved(approved, context))
        notes.append({"wording": approved.text, "refused": None, "framed_by": "code"})
    nothing = None if reply.memories else (reply.nothing or "").strip() or None
    return Framing(memories=tuple(memories), failed=failed, nothing=nothing, notes=tuple(notes))


def _checked(proposed: _FramedMemory, context: _Context) -> Framed:
    """One proposed memory, checked and built, or :class:`_Refused` with why."""
    view = context.view
    supports = _supports(proposed, context)
    leaving = view.leaving.id
    if not any(
        one.direction is SupportDirection.FOR and part_episode(one.points_at) == leaving
        for one in supports.values()
    ):
        msg = "no support for it points at the exchange under review (ADR-0346 §3:1)"
        raise _Refused(msg)
    backing = [one for one in supports.values() if _backs(one)]
    if not backing:
        msg = "no support backs it as worded"
        raise _Refused(msg)
    confirmed = _confirmed_wording(supports, view)
    content = confirmed if confirmed is not None else proposed.wording.strip()
    if not content:
        msg = "it has no wording"
        raise _Refused(msg)
    marks = _marks(proposed.marks)
    _assistant_words(supports, marks, leaving)
    if MemoryMark.OCCASION in marks and proposed.valid_until is not None:
        msg = "an occasion carries no validity end (ADR-0345 §8:4)"
        raise _Refused(msg)
    ordered = _ordered(list(supports.values()), proposed.valid_until, context.now)
    subjects, involved = _people(proposed, supports, view)
    try:
        memory = Memory(
            id=f"observed:{context.mint()}",
            content=content,
            supports=tuple(ordered),
            operations=(
                MemoryOperation(
                    kind=MemoryOperationKind.CREATE,
                    cites=ordered[0].points_at,
                    note=proposed.note.strip(),
                    at=context.now,
                    by=MemoryWriterName.OBSERVER,
                ),
            ),
            labels=_labels(proposed.labels, context),
            marks=tuple(marks),
            subjects=subjects,
            involved=involved,
            validity=Validity(valid_until=proposed.valid_until),
            placement=Placement(),
        )
    except ValidationError as exc:
        msg = f"it is not a memory: {exc.error_count()} errors"
        raise _Refused(msg) from exc
    if memory.standing is MemoryStanding.INFERENCE:
        msg = "it would stand on inference alone (ADR-0346 §7:2)"
        raise _Refused(msg)
    return Framed(
        memory=memory,
        texts=_texts(memory, view),
        style=context.person and proposed.style is True,
        pin=context.person and proposed.pin is True,
    )


def _supports(proposed: _FramedMemory, context: _Context) -> dict[str, MemorySupport]:
    """Each support, by its part's label, its code-owned fields set (ADR-0329 §9:5)."""
    supports: dict[str, MemorySupport] = {}
    for one in proposed.supports:
        read = context.view.part(one.part)
        if read is None:
            msg = f"a support names {one.part!r}, which is no part the finding rests on"
            raise _Refused(msg)
        if one.part in supports:
            msg = f"a support names {one.part!r} twice"
            raise _Refused(msg)
        direction = SupportDirection(one.direction)
        confirmation = read.origin is SupportOrigin.CONFIRMATION
        try:
            supports[one.part] = MemorySupport(
                points_at=read.part,
                origin=read.origin,
                direction=direction,
                note=one.note,
                backs_as_worded=one.backs_as_worded and direction is SupportDirection.FOR,
                how_sure=ReadingCertainty.SURE if confirmation else ReadingCertainty(one.how_sure),
                when=read.when,
                about_when=one.about_when,
                added_at=context.now,
                added_by=MemoryWriterName.OBSERVER,
            )
        except ValidationError as exc:
            msg = f"a support on {one.part!r} is not one"
            raise _Refused(msg) from exc
    return supports


def _confirmed_wording(supports: Mapping[str, MemorySupport], view: FramingView) -> str | None:
    """The wording a person approved that the memory rests on, or ``None`` (§5:3).

    A confirmation backs the memory as worded or is on no memory but its own (ADR-0328
    §4:6), and a memory carries at most one approved wording.
    """
    approved: set[str] = set()
    for handle, one in supports.items():
        if one.origin is not SupportOrigin.CONFIRMATION:
            continue
        read = view.part(handle)
        if not one.backs_as_worded or read is None:
            msg = "a person's yes to a wording backs that wording, and only it (§5:3)"
            raise _Refused(msg)
        approved.add(read.text)
    if len(approved) > 1:
        msg = "a memory carries one approved wording, framed exactly (§5:3)"
        raise _Refused(msg)
    return next(iter(approved), None)


def _marks(proposed: Sequence[str]) -> set[MemoryMark]:
    try:
        return {MemoryMark(one.strip()) for one in proposed}
    except ValueError as exc:
        msg = "a mark is one of occasion and assistant_statement (ADR-0345 §8:1)"
        raise _Refused(msg) from exc


def _assistant_words(
    supports: Mapping[str, MemorySupport], marks: set[MemoryMark], leaving: str
) -> None:
    """ADR-0346 §7:6-§7:9: what a round's message may back and support."""
    said = [one for one in supports.values() if one.origin in _ASSISTANT_ORIGINS]
    saying = _RECORD_OF_SAYING.issubset(marks)
    if MemoryMark.ASSISTANT_STATEMENT in marks and not said:
        msg = "a memory marked assistant_statement cites a round's message (ADR-0345 §8:3)"
        raise _Refused(msg)
    if any(_backs(one) for one in said) and not saying:
        msg = "a round's message backs only a record of the saying (ADR-0345 §2:4)"
        raise _Refused(msg)
    takes_on = any(one.direction is SupportDirection.FOR for one in said)
    if takes_on and not saying:
        kept = any(
            _backs(one) and one.origin in _PERSON_ORIGINS and part_episode(one.points_at) == leaving
            for one in supports.values()
        )
        if not kept:
            msg = (
                "what a round's message claims is kept only on a person's request, agreement "
                "or confirmation in this exchange, which backs it (ADR-0346 §7:6, §7:9)"
            )
            raise _Refused(msg)


def _backs(support: MemorySupport) -> bool:
    return support.direction is SupportDirection.FOR and support.backs_as_worded


def _ordered(
    supports: list[MemorySupport], valid_until: datetime | None, now: datetime
) -> list[MemorySupport]:
    """Supports with the one the create cites first (ADR-0328 §3:3, ADR-0345 §6:1).

    The strongest backing support leads, the rest keep the call's order. Where the memory
    carries a validity end, the end lies in the future and the create cites a backing
    support whose about-when names it.
    """
    ordered = sorted(
        supports, key=lambda one: (not _backs(one), -standing_rank(origin_standing(one.origin)))
    )
    if valid_until is None:
        return ordered
    if valid_until <= now:
        msg = "a validity end set at a create lies after it (ADR-0345 §6:1)"
        raise _Refused(msg)
    naming = next((one for one in ordered if _backs(one) and one.about_when == valid_until), None)
    if naming is None:
        msg = "a validity end is the about-when of a support backing the memory (§6:1)"
        raise _Refused(msg)
    return [naming, *(one for one in ordered if one is not naming)]


def _people(
    proposed: _FramedMemory, supports: Mapping[str, MemorySupport], view: FramingView
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """``subjects`` and ``involved``, each given, each name one a part gives (§5:5)."""
    if proposed.subjects is None or proposed.involved is None:
        msg = "subjects and involved are each given, possibly empty (ADR-0346 §5:2)"
        raise _Refused(msg)
    subjects = tuple(dict.fromkeys(name_stored(one) for one in proposed.subjects if one.strip()))
    involved = tuple(
        name
        for name in dict.fromkeys(name_stored(one) for one in proposed.involved if one.strip())
        if name not in subjects
    )
    texts = [read.text for handle in supports if (read := view.part(handle)) is not None]
    ungiven = [
        name
        for name in (*subjects, *involved)
        if name != OWNER_PERSON_ID and not any(name in text for text in texts)
    ]
    if ungiven:
        msg = "a name is carried only as a part the memory rests on gives it (ADR-0345 §9:3)"
        raise _Refused(msg)
    return subjects, involved


def _labels(proposed: Sequence[str], context: _Context) -> tuple[SituationLabel, ...]:
    """The memory's labels, within the bounds (ADR-0345 §7:3), suggested by its episode.

    A label is a suggestion: one longer than the bound, or past the most a memory
    carries, is left out rather than failing the memory.
    """
    bounds = context.labels
    texts = [
        one.strip()
        for one in dict.fromkeys(proposed)
        if one.strip() and len(one.strip()) <= bounds.max_chars
    ]
    return tuple(
        SituationLabel(
            text=text,
            added_at=context.now,
            added_by=MemoryWriterName.OBSERVER,
            episode=context.view.leaving.id,
        )
        for text in list(dict.fromkeys(texts))[: bounds.max_labels]
    )


def _texts(memory: Memory, view: FramingView) -> dict[SupportPart, str]:
    """The text of each part the memory's supports point at, by part."""
    by_part = {read.part: read.text for read in view.parts}
    return {
        one.points_at: by_part[one.points_at] for one in memory.supports if one.points_at in by_part
    }


def _unframed_approvals(view: FramingView, memories: Sequence[Framed]) -> list[ReadPart]:
    """Each approved wording the finding rests on that no framed memory carries (§5:3)."""
    carried = {
        one.points_at
        for framed_ in memories
        for one in framed_.memory.supports
        if isinstance(one.points_at, ConfirmationPart) and _backs(one)
    }
    return [
        read
        for read in view.parts
        if isinstance(read.part, ConfirmationPart) and read.part not in carried
    ]


def _approved(read: ReadPart, context: _Context) -> Framed:
    """An approved wording framed by code, exactly as approved, on its own yes (§5:3).

    Its people are the scout's, each name kept only where the approved wording gives it
    (§5:5), the owner always.
    """
    support = MemorySupport(
        points_at=read.part,
        origin=SupportOrigin.CONFIRMATION,
        direction=SupportDirection.FOR,
        note=_APPROVED_NOTE,
        backs_as_worded=True,
        how_sure=ReadingCertainty.SURE,
        when=read.when,
        added_at=context.now,
        added_by=MemoryWriterName.OBSERVER,
    )
    annotations = context.view.finding.annotations

    def given(names: Sequence[str]) -> tuple[str, ...]:
        return tuple(one for one in names if one == OWNER_PERSON_ID or one in read.text)

    memory = Memory(
        id=f"observed:{context.mint()}",
        content=read.text,
        supports=(support,),
        operations=(
            MemoryOperation(
                kind=MemoryOperationKind.CREATE,
                cites=read.part,
                note=_APPROVED_NOTE,
                at=context.now,
                by=MemoryWriterName.OBSERVER,
            ),
        ),
        subjects=() if annotations is None else given(annotations.subjects),
        involved=() if annotations is None else given(annotations.involved),
        placement=Placement(),
    )
    return Framed(memory=memory, texts={read.part: read.text})
