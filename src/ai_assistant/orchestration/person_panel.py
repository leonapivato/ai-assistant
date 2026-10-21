"""The person model on the panels: the read and the writes behind them (ADR-0338 §8:1-§8:3).

``AssistantEngine``'s eight person-model members, answered here over orchestration's
person-block assembly (:class:`~ai_assistant.orchestration.person_block.PersonBlocks`),
so the engine and the canonical fake answer them alike, as both answer
``pending_candidates`` from one reading. Neither reads a store for them itself.

**The read** (§8:1) is one read of the person-model store and of the memory store:

- the fields, as the store holds them;
- the kept-in-mind slot, assembled as the person block assembles it on a private
  place, which every place on the hub is today (§7's privacy note): the standing pins,
  oldest first, then the standing style marks, the most recently marked first, each
  showing its chain's current end (§4:8) and each memory once, stopping before the
  first wording that would exceed the budget (§6:1-§6:2). The record rule (§6:5)
  withholds nothing on a bounded audience, so it is not applied here; a memory
  resting on outside content is left out, as the block leaves it out (§6:4);
- what the slot left out, and why: the budget, or outside content;
- the standing pins whose memory the store holds and whose chain reaches no current
  memory: no longer current, shown until removed (§4:8), with the wording of the
  memory they were made on, as the history read holds it, since no live read words it;
- the standing style marks whose memory the store holds, each with the current memory
  it shows, or the wording of the one it was made on where it shows none;
- and the pending suggestions, the most recent first, each marked where it rests on
  outside content (§7:9), a pin suggestion's only while its memory is current (§9:5).

A pin or mark whose memory the store no longer holds is shown nowhere (§4:10). The
store holds a memory exactly where the history read returns it (ADR-0342 §5:4).

**The change log** grows with every change and is kept until the person's data is
deleted (§3:5), so it is a read of its own, a page at a time, the most recent first
(:func:`profile_changes`), and never part of the view: a log that outgrew the frame
would otherwise take the profile, the slot and every control down with it.

**The writes** are a ``panel`` act by the owner, the person the command role serves
(§3:4, §8:3). A pin and an unpin go through
:meth:`~ai_assistant.orchestration.person_block.PersonBlocks.pin` and
:meth:`~ai_assistant.orchestration.person_block.PersonBlocks.unpin`, which hold §4:2's
and §6:3's checks under the one lock per person every pin is made under, so this module
writes no second check. Accepting a pin suggestion is such a pin, and the store's pin
accepts the suggestion in the same write (§8:8); accepting a field suggestion is the
store's own accept, which logs the change as the suggestion's (§3:5).

**With no store wired** — ``Settings.person_model`` off (§11:2) — every member raises
:class:`~ai_assistant.core.errors.PersonModelOffError`, after its arguments are checked
and before anything is read: :func:`wired` is that refusal.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from ai_assistant.core.errors import PersonModelOffError, PersonModelStoreError
from ai_assistant.core.types import (
    OWNER_PERSON_ID,
    KeptMemoryView,
    LeftOutMemory,
    LeftOutReason,
    Memory,
    MemoryStatus,
    PersonActHow,
    PersonModelAct,
    PersonModelEdit,
    PersonModelEditRefusal,
    PersonModelRefusal,
    PersonModelView,
    PersonModelWrite,
    PersonModelWriteKind,
    StalePinView,
    StyleMarkView,
    SuggestionKind,
    SuggestionState,
    SuggestionView,
)
from ai_assistant.orchestration.person_block import PinRefusal

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence
    from datetime import datetime

    from ai_assistant.core.types import (
        MemoryRecord,
        PersonModel,
        PersonSuggestion,
        Pin,
        ProfileChange,
        ProfileField,
        StyleMark,
    )
    from ai_assistant.orchestration.person_block import PersonBlocks, Pinned

__all__ = [
    "PANEL_ACT",
    "accept_suggestion",
    "dismiss_suggestion",
    "person_model_view",
    "pin_memory",
    "profile_changes",
    "remove_style_mark",
    "set_profile_field",
    "unpin_memory",
    "wired",
]

#: Every panel write's act: on the panel, by the owner, the person the command role
#: serves (ADR-0338 §3:4, §4:2, §8:3). On today's one-person hub that is the person's
#: own act on their own model (§2:1).
PANEL_ACT: Final = PersonModelAct(how=PersonActHow.PANEL, by=OWNER_PERSON_ID)

_OFF: Final = (
    "the person model is not switched on on this hub: no person-model store is wired "
    "(ADR-0338 §11:2)"
)


def wired(blocks: PersonBlocks | None) -> PersonBlocks:
    """The person-block assembly, or the refusal of a hub that keeps no person model.

    Args:
        blocks: The assembly the implementation was built with, or ``None``.

    Returns:
        The assembly.

    Raises:
        PersonModelOffError: If none is wired (ADR-0338 §11:2).
    """
    if blocks is None:
        raise PersonModelOffError(_OFF)
    return blocks


async def person_model_view(
    blocks: PersonBlocks, person_id: str, *, limit: int, offset: int
) -> PersonModelView | None:
    """Read one person's model as the About you panel shows it (ADR-0338 §8:1-§8:2).

    The chains are walked first, live read first (:meth:`PersonBlocks.current_ends`),
    and the history read is made **after** that walk, over every memory a pin or mark
    was made on and every current end the walk reached: a memory forgotten while the
    walk ran is then not held, and whatever rests on it is shown nowhere (§4:10;
    ADR-0342 §5:4), as :func:`~ai_assistant.orchestration.person_block.still_held`
    drops it before a planning round. A start held whose current end is not is a
    chain that reaches no current memory.

    Each of the five lists — the slot, what it left out, the pins no longer current,
    the style marks and the suggestions — is cut to the page ``offset`` and ``limit``
    name, beside its total, and the slot's fill is the whole slot's. A budget bounds
    characters, not entries (a memory may be worded empty), so the slot is paged too.

    Args:
        blocks: The person-block assembly over the two stores.
        person_id: The person, by id.
        limit: How many entries each list's page holds at most.
        offset: How many of each list's entries to skip.

    Returns:
        The view, or ``None`` where the store holds no such person.

    Raises:
        PersonModelStoreError: If the person-model store cannot be read.
        MemoryStoreError: If the memory store cannot be read.
    """
    model = await blocks.store.read(person_id)
    if model is None:
        return None
    pins = _ordered(model.standing_pins, _pinned)
    marks = _ordered(model.standing_marks, _marked, newest_first=True)
    pending = _ordered(model.suggestions, _recorded, newest_first=True)
    starts = list(dict.fromkeys([*(pin.memory_id for pin in pins), *(m.memory_id for m in marks)]))
    reached = await blocks.current_ends(starts)
    asked = list(dict.fromkeys([*starts, *(end.id for end in reached.values())]))
    history = await blocks.memory.get_history(asked) if asked else {}
    # A chain's current end, only where the start and the end are both still held.
    ends = {start: end for start, end in reached.items() if start in history and end.id in history}
    kept, left_out = _slot(
        [(pin.memory_id, True) for pin in pins] + [(mark.memory_id, False) for mark in marks],
        ends,
        budget=blocks.budget_chars,
    )
    suggested = [
        one.proposed.memory_id
        for one in pending
        if one.proposed.kind is SuggestionKind.PIN and one.proposed.memory_id is not None
    ]
    live = await blocks.memory.get_many(list(dict.fromkeys(suggested))) if suggested else {}
    stale = [
        StalePinView(
            pin=pin,
            content=history[pin.memory_id].content,
            rests_on_outside_content=history[pin.memory_id].rests_on_outside_content,
        )
        for pin in model.standing_pins
        if pin.memory_id in history and pin.memory_id not in ends
    ]
    marked = [
        _mark(mark, ends, history) for mark in model.standing_marks if mark.memory_id in history
    ]
    shown = _suggestions(pending, live)
    window = slice(offset, offset + limit)
    return PersonModelView(
        person=model.person,
        profile=model.profile,
        kept=kept[window],
        budget_chars=blocks.budget_chars,
        kept_chars=sum(len(one.content) for one in kept),
        left_out=tuple(left_out[window]),
        no_longer_current=tuple(stale[window]),
        style_marks=tuple(marked[window]),
        suggestions=tuple(shown[window]),
        kept_total=len(kept),
        left_out_total=len(left_out),
        no_longer_current_total=len(stale),
        style_marks_total=len(marked),
        suggestions_total=len(shown),
    )


def _mark(
    mark: StyleMark, ends: Mapping[str, Memory], history: Mapping[str, Memory]
) -> StyleMarkView:
    """A held mark, with the current memory it shows and its wording, or its own memory's."""
    end = ends.get(mark.memory_id)
    if end is not None:
        return StyleMarkView(mark=mark, shows=end.id, content=end.content)
    return StyleMarkView(mark=mark, content=history[mark.memory_id].content)


async def profile_changes(
    blocks: PersonBlocks, person_id: str, *, limit: int, offset: int
) -> tuple[ProfileChange, ...]:
    """One page of a person's change log, the most recent change first (ADR-0338 §3:5).

    The log is append-only and kept until the person's data is deleted, so it is read a
    page at a time and never whole with the rest of the model.

    Args:
        blocks: The person-block assembly over the person-model store.
        person_id: Whose log.
        limit: How many entries the page holds at most.
        offset: How many of the most recent to skip.

    Returns:
        The page; empty where the store holds no such person, or past the log's end.

    Raises:
        PersonModelStoreError: If the store cannot be read.
    """
    model = await blocks.store.read(person_id)
    if model is None:
        return ()
    newest_first = model.changes[::-1]
    return tuple(newest_first[offset : offset + limit])


def _slot(
    starts: Sequence[tuple[str, bool]], reached: Mapping[str, Memory], *, budget: int
) -> tuple[tuple[KeptMemoryView, ...], list[LeftOutMemory]]:
    """The slot within the budget, and what it left out and why (ADR-0338 §6:1-§6:4).

    Each start in the slot's order, pinned first: a start whose chain reaches no
    current memory is in neither; a memory already shown or left out is not again; one
    resting on outside content is left out for it; and once a wording would exceed the
    budget, it and every later memory are left out for the budget, as the block stops
    there (§6:2).
    """
    kept: list[KeptMemoryView] = []
    left_out: list[LeftOutMemory] = []
    seen: set[str] = set()
    spent = 0
    full = False
    for start, pinned in starts:
        memory = reached.get(start)
        if memory is None or memory.id in seen:
            continue
        seen.add(memory.id)
        if memory.rests_on_outside_content:
            left_out.append(
                LeftOutMemory(
                    memory_id=memory.id,
                    content=memory.content,
                    pinned=pinned,
                    reason=LeftOutReason.OUTSIDE_CONTENT,
                )
            )
            continue
        if not full and spent + len(memory.content) <= budget:
            spent += len(memory.content)
            kept.append(KeptMemoryView(memory_id=memory.id, content=memory.content, pinned=pinned))
            continue
        full = True
        left_out.append(
            LeftOutMemory(
                memory_id=memory.id,
                content=memory.content,
                pinned=pinned,
                reason=LeftOutReason.BUDGET,
            )
        )
    return tuple(kept), left_out


def _suggestions(
    pending: Sequence[PersonSuggestion], live: Mapping[str, MemoryRecord]
) -> list[SuggestionView]:
    """The pending suggestions the panel shows, the most recent first (§7:9, §9:5)."""
    shown: list[SuggestionView] = []
    for one in pending:
        proposed = one.proposed
        if proposed.kind is SuggestionKind.FIELD:
            shown.append(
                SuggestionView(
                    suggestion=one, rests_on_outside_content=proposed.rests_on_outside_content
                )
            )
            continue
        record = live.get(proposed.memory_id or "")
        if not isinstance(record, Memory) or record.status is not MemoryStatus.CURRENT:
            continue
        shown.append(
            SuggestionView(
                suggestion=one,
                rests_on_outside_content=record.rests_on_outside_content,
                content=record.content,
            )
        )
    return shown


async def set_profile_field(
    blocks: PersonBlocks, person_id: str, field: ProfileField, value: str | None
) -> PersonModelEdit:
    """Set or clear one field on the panel, through the store's one-step write (§3, §8:8).

    Raises:
        PersonModelStoreError: If the store cannot be read or written.
    """
    return PersonModelEdit(
        write=await blocks.store.set_field(person_id, field, value, act=PANEL_ACT)
    )


async def pin_memory(blocks: PersonBlocks, person_id: str, memory_id: str) -> PersonModelEdit:
    """Pin a memory on the panel, through the person block's one checked pin (§4:2, §6:3).

    Raises:
        PersonModelStoreError: If the person-model store cannot be read or written.
        MemoryStoreError: If the memory store cannot be read.
    """
    return _edit(await blocks.pin(person_id, memory_id, act=PANEL_ACT))


def _edit(pinned: Pinned) -> PersonModelEdit:
    """A checked pin's outcome, as the panel's edit carries it."""
    if pinned.write is not None:
        return PersonModelEdit(write=pinned.write)
    match pinned.refused:
        case PinRefusal.NOT_CURRENT:
            return PersonModelEdit(refused=PersonModelEditRefusal.NOT_CURRENT)
        case PinRefusal.OVER_BUDGET:
            return PersonModelEdit(refused=PersonModelEditRefusal.OVER_BUDGET)
        case _:
            # The store holds no such person: the store's own refusal, as its write
            # would have carried it.
            return PersonModelEdit(write=_refused(PersonModelRefusal.UNKNOWN_PERSON))


async def unpin_memory(blocks: PersonBlocks, person_id: str, memory_id: str) -> PersonModelEdit:
    """Unpin a memory on the panel, through the person block's one unpin (§4:7).

    Raises:
        PersonModelStoreError: If the person-model store cannot be read or written,
            including after a first pin was removed.
        MemoryStoreError: If the memory store cannot be read.
    """
    unpinned = await blocks.unpin(person_id, memory_id)
    if unpinned.unknown_person:
        return PersonModelEdit(write=_refused(PersonModelRefusal.UNKNOWN_PERSON))
    if unpinned.faulted:
        msg = (
            f"the person-model store failed after {unpinned.removed} of {unpinned.showing} "
            "pins showing the memory were removed"
        )
        raise PersonModelStoreError(msg)
    if unpinned.refused is not None:
        return PersonModelEdit(write=unpinned.refused)
    kind = PersonModelWriteKind.WRITTEN if unpinned.removed else PersonModelWriteKind.UNCHANGED
    return PersonModelEdit(write=PersonModelWrite(kind=kind))


async def remove_style_mark(blocks: PersonBlocks, person_id: str, mark_id: str) -> PersonModelEdit:
    """Remove a style mark on the panel (§5:3).

    Raises:
        PersonModelStoreError: If the store cannot be read or written.
    """
    return PersonModelEdit(write=await blocks.store.remove_style_mark(person_id, mark_id))


async def accept_suggestion(
    blocks: PersonBlocks, person_id: str, suggestion_id: str
) -> PersonModelEdit:
    """Accept a pending suggestion on the panel (ADR-0338 §8:8, §9:2, §9:5).

    The suggestion is read first, to tell a pin suggestion from a field suggestion, and
    **every pin goes through the checked pin**: a pending pin suggestion is accepted
    by pinning its memory through :meth:`PersonBlocks.pin`, whose write accepts it
    (§8:8); were it dismissed between the read and the pin, the pin is still the
    person's act and the suggestion stays dismissed. Only a field suggestion reaches
    the store's own accept, which writes the field as the suggestion's. An id not
    pending when the model is read is looked up in the store's export, which writes
    nothing: unknown, it is refused ``unknown_record``; decided, ``already_decided``;
    recorded since the read, it is accepted by its kind as above.

    Raises:
        PersonModelStoreError: If the person-model store cannot be read or written.
        MemoryStoreError: If the memory store cannot be read.
    """
    model = await blocks.store.read(person_id)
    if model is None:
        return PersonModelEdit(write=_refused(PersonModelRefusal.UNKNOWN_PERSON))
    found = _pending(model, suggestion_id)
    if found is None:
        # Not pending when read: looked up in the export, which writes nothing, so no
        # write is made for an id this read did not see as a field suggestion.
        exported = await blocks.store.export()
        held = next(
            (
                one
                for one in exported.suggestions
                if one.id == suggestion_id and one.person_id == person_id
            ),
            None,
        )
        if held is None:
            return PersonModelEdit(write=_refused(PersonModelRefusal.UNKNOWN_RECORD))
        if held.state is not SuggestionState.PENDING:
            return PersonModelEdit(
                write=_refused(PersonModelRefusal.ALREADY_DECIDED, record_id=held.id)
            )
        found = held  # recorded since the read
    if found.proposed.kind is SuggestionKind.PIN:
        memory_id = found.proposed.memory_id
        assert memory_id is not None  # noqa: S101 — a pin suggestion names its memory
        return _edit(await blocks.pin(person_id, memory_id, act=PANEL_ACT))
    # A field suggestion, by its id; a suggestion's kind never changes, so the store's
    # accept writes a field and never a pin.
    return PersonModelEdit(
        write=await blocks.store.accept_suggestion(person_id, suggestion_id, by=OWNER_PERSON_ID)
    )


async def dismiss_suggestion(
    blocks: PersonBlocks, person_id: str, suggestion_id: str
) -> PersonModelEdit:
    """Dismiss a pending suggestion on the panel (§9:2, §12).

    Raises:
        PersonModelStoreError: If the store cannot be read or written.
    """
    return PersonModelEdit(write=await blocks.store.dismiss_suggestion(person_id, suggestion_id))


def _pending(model: PersonModel, suggestion_id: str) -> PersonSuggestion | None:
    return next((one for one in model.suggestions if one.id == suggestion_id), None)


def _refused(refusal: PersonModelRefusal, *, record_id: str | None = None) -> PersonModelWrite:
    return PersonModelWrite(kind=PersonModelWriteKind.REFUSED, refusal=refusal, record_id=record_id)


def _ordered[R](
    records: Sequence[R], when: Callable[[R], datetime], *, newest_first: bool = False
) -> list[R]:
    """Records by their instant, the store's order breaking a tie, as the block orders them."""
    ranked = sorted(enumerate(records), key=lambda pair: (when(pair[1]), pair[0]))
    if newest_first:
        ranked.reverse()
    return [record for _, record in ranked]


def _pinned(pin: Pin) -> datetime:
    return pin.pinned_at


def _marked(mark: StyleMark) -> datetime:
    return mark.marked_at


def _recorded(suggestion: PersonSuggestion) -> datetime:
    return suggestion.recorded_at
