"""The person model on the panels: the read and the writes behind them (ADR-0338 §8:1-§8:3).

``AssistantEngine``'s seven person-model members, answered here over orchestration's
person-block assembly (:class:`~ai_assistant.orchestration.person_block.PersonBlocks`),
so the engine and the canonical fake answer them alike, as both answer
``pending_candidates`` from one reading. Neither reads a store for them itself.

**The read** (§8:1) is one read of the person-model store and of the memory store:

- the fields and the change log, as the store holds them;
- the kept-in-mind slot, assembled as the person block assembles it on a private
  place, which every place on the hub is today (§7's privacy note): the standing pins,
  oldest first, then the standing style marks, the most recently marked first, each
  showing its chain's current end (§4:8) and each memory once, stopping before the
  first wording that would exceed the budget (§6:1-§6:2). The record rule (§6:5)
  withholds nothing on a bounded audience, so it is not applied here; a memory
  resting on outside content is left out, as the block leaves it out (§6:4);
- what the slot left out, and why: the budget, or outside content;
- the standing pins whose memory the store holds and whose chain reaches no current
  memory: no longer current, shown until removed (§4:8);
- the standing style marks whose memory the store holds;
- and the pending suggestions, the most recent first, each marked where it rests on
  outside content (§7:9), a pin suggestion's only while its memory is current (§9:5).

A pin or mark whose memory the store no longer holds is shown nowhere (§4:10). The
store holds a memory exactly where the history read returns it (ADR-0342 §5:4).

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
    SuggestionKind,
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


async def person_model_view(blocks: PersonBlocks, person_id: str) -> PersonModelView | None:
    """Read one person's model as the About you panel shows it (ADR-0338 §8:1-§8:2).

    Args:
        blocks: The person-block assembly over the two stores.
        person_id: The person, by id.

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
    starts = [*(pin.memory_id for pin in pins), *(mark.memory_id for mark in marks)]
    reached = await blocks.current_ends(starts)
    held = set(await blocks.memory.get_history(list(dict.fromkeys(starts)))) if starts else set()
    kept, left_out = _slot(
        [(pin.memory_id, True) for pin in pins] + [(mark.memory_id, False) for mark in marks],
        reached,
        budget=blocks.budget_chars,
    )
    suggested = [
        one.proposed.memory_id
        for one in pending
        if one.proposed.kind is SuggestionKind.PIN and one.proposed.memory_id is not None
    ]
    live = await blocks.memory.get_many(list(dict.fromkeys(suggested))) if suggested else {}
    return PersonModelView(
        person=model.person,
        profile=model.profile,
        changes=model.changes,
        kept=kept,
        budget_chars=blocks.budget_chars,
        left_out=left_out,
        no_longer_current=tuple(
            pin
            for pin in model.standing_pins
            if pin.memory_id in held and pin.memory_id not in reached
        ),
        style_marks=tuple(mark for mark in model.standing_marks if mark.memory_id in held),
        suggestions=_suggestions(pending, live),
    )


def _slot(
    starts: Sequence[tuple[str, bool]], reached: Mapping[str, Memory], *, budget: int
) -> tuple[tuple[KeptMemoryView, ...], tuple[LeftOutMemory, ...]]:
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
                    memory_id=memory.id, pinned=pinned, reason=LeftOutReason.OUTSIDE_CONTENT
                )
            )
            continue
        if not full and spent + len(memory.content) <= budget:
            spent += len(memory.content)
            kept.append(KeptMemoryView(memory_id=memory.id, content=memory.content, pinned=pinned))
            continue
        full = True
        left_out.append(
            LeftOutMemory(memory_id=memory.id, pinned=pinned, reason=LeftOutReason.BUDGET)
        )
    return tuple(kept), tuple(left_out)


def _suggestions(
    pending: Sequence[PersonSuggestion], live: Mapping[str, MemoryRecord]
) -> tuple[SuggestionView, ...]:
    """The pending suggestions the panel shows, the most recent first (§7:9, §9:5)."""
    shown: list[SuggestionView] = []
    for one in pending:
        proposed = one.proposed
        if proposed.kind is SuggestionKind.FIELD:
            outside = proposed.rests_on_outside_content
        else:
            record = live.get(proposed.memory_id or "")
            if not isinstance(record, Memory) or record.status is not MemoryStatus.CURRENT:
                continue
            outside = record.rests_on_outside_content
        shown.append(SuggestionView(suggestion=one, rests_on_outside_content=outside))
    return tuple(shown)


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

    The suggestion is read first, to tell a pin suggestion from a field suggestion. A
    pending pin suggestion is accepted by pinning its memory through the checked pin,
    whose write accepts it (§8:8); were it dismissed between the read and the pin, the
    pin is still the person's act and the suggestion stays dismissed. Every other id —
    a pending field suggestion, or one not pending when read — goes to the store's
    accept, which writes the field as the suggestion's or refuses it ``unknown_record``
    or ``already_decided``. An id not pending when read can name no pin suggestion
    recorded after that read: the store mints each id fresh (``uuid4`` on SQLite), and
    a caller names one it was shown.

    Raises:
        PersonModelStoreError: If the person-model store cannot be read or written.
        MemoryStoreError: If the memory store cannot be read.
    """
    model = await blocks.store.read(person_id)
    if model is None:
        return PersonModelEdit(write=_refused(PersonModelRefusal.UNKNOWN_PERSON))
    found = _pending(model, suggestion_id)
    if found is not None and found.proposed.kind is SuggestionKind.PIN:
        memory_id = found.proposed.memory_id
        assert memory_id is not None  # noqa: S101 — a pin suggestion names its memory
        return _edit(await blocks.pin(person_id, memory_id, act=PANEL_ACT))
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


def _refused(refusal: PersonModelRefusal) -> PersonModelWrite:
    return PersonModelWrite(kind=PersonModelWriteKind.REFUSED, refusal=refusal)


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
