"""The person model as the page reads it: JSON views of ADR-0338 §8:1's answers.

**An enumeration, for ADR-0168 §6's reason**: what may appear on the page is decided
here rather than by whatever a future ``PersonModelView`` carries. Each view names the
members the About you panel and the belief panel render, and nothing else crosses.

**Nothing here computes a value.** The slot's order and fill, what it left out and
why, which pins are no longer current, the wording of every memory shown and whether a
suggestion rests on outside content are the engine's (ADR-0338 §6, §4:8, §7:9), so the
page and the command line cannot show two different models of one person.

**The ids that cross are the ones a control names**: a memory's for pin and unpin, a
style mark's for its removal and a suggestion's for accepting or dismissing it, each
verbatim as the person model holds it (§10:4). **One more id crosses, to be read**: the
approval request a change made by a yes on a card names, since the change log says
which request's card it was (ADR-0362 §2:1, ADR-0338 §3:5 as it amends it). A pin's own
id and a person's role, the question part and episode a change names and the instant a
person was created cross nowhere, because neither a control nor a line on either panel
names them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ai_assistant.core.types import (
        KeptMemoryView,
        LeftOutMemory,
        PersonModelEdit,
        PersonModelView,
        Profile,
        ProfileChange,
        StalePinView,
        StyleMarkView,
        SuggestionView,
    )


def profile_view(profile: Profile) -> dict[str, str | None]:
    """The five fields, each set or ``null`` (ADR-0338 §3:1, §3:9).

    Keyed by :class:`~ai_assistant.core.types.ProfileField`'s values, so an empty field
    crosses as not set and never as a default presented as the person's own.
    """
    return {
        "name": profile.name,
        "address": profile.address,
        "assistant_name": profile.assistant_name,
        "time_zone": profile.time_zone,
        "language": profile.language,
    }


def _kept_view(kept: KeptMemoryView) -> dict[str, Any]:
    """One memory the kept-in-mind slot shows (§6:2)."""
    return {"memory_id": kept.memory_id, "content": kept.content, "pinned": kept.pinned}


def _left_out_view(left: LeftOutMemory) -> dict[str, Any]:
    """One memory the slot left out, and why (§6:4)."""
    return {
        "memory_id": left.memory_id,
        "content": left.content,
        "pinned": left.pinned,
        "reason": left.reason.value,
    }


def _stale_pin_view(stale: StalePinView) -> dict[str, Any]:
    """One pin no longer current (§4:8), named by the memory it was made on.

    That memory is what ``unpin_memory`` names a pin no longer current by, so it is
    the id its control carries.
    """
    return {
        "memory_id": stale.pin.memory_id,
        "pinned_at": stale.pin.pinned_at.isoformat(),
        "content": stale.content,
        "rests_on_outside_content": stale.rests_on_outside_content,
    }


def _style_mark_view(mark: StyleMarkView) -> dict[str, Any]:
    """One standing style mark, the memory it shows, and its wording (§5:3)."""
    return {
        "mark_id": mark.mark.id,
        "marked_at": mark.mark.marked_at.isoformat(),
        "shows": mark.shows,
        "content": mark.content,
    }


def _suggestion_view(view: SuggestionView) -> dict[str, Any]:
    """One pending suggestion, marked where it rests on outside content (§7:9, §9:2, §9:5).

    A field suggestion carries its field and value, and a pin suggestion its memory and
    that memory's wording, which is what accepting it pins and so confirms (§4:3).
    """
    proposed = view.suggestion.proposed
    return {
        "suggestion_id": view.suggestion.id,
        "kind": proposed.kind.value,
        "field": None if proposed.field is None else proposed.field.value,
        "value": proposed.value,
        "memory_id": proposed.memory_id,
        "content": view.content,
        "rests_on_outside_content": view.rests_on_outside_content,
        "recorded_at": view.suggestion.recorded_at.isoformat(),
    }


def person_model_view(view: PersonModelView) -> dict[str, Any]:
    """One person's model, each of its five lists a page beside its total (§8:1)."""
    return {
        "person_id": view.person.id,
        "profile": profile_view(view.profile),
        "kept": [_kept_view(one) for one in view.kept],
        "kept_total": view.kept_total,
        "budget_chars": view.budget_chars,
        "kept_chars": view.kept_chars,
        "left_out": [_left_out_view(one) for one in view.left_out],
        "left_out_total": view.left_out_total,
        "no_longer_current": [_stale_pin_view(one) for one in view.no_longer_current],
        "no_longer_current_total": view.no_longer_current_total,
        "style_marks": [_style_mark_view(one) for one in view.style_marks],
        "style_marks_total": view.style_marks_total,
        "suggestions": [_suggestion_view(one) for one in view.suggestions],
        "suggestions_total": view.suggestions_total,
    }


def profile_change_view(change: ProfileChange) -> dict[str, Any]:
    """One change-log entry: the field, its old and new values, when, and how (§3:5).

    ``request`` is the approval request a yes on a card names (ADR-0362 §2:1), and
    ``null`` for every other act, a stored yes to a question included.
    """
    return {
        "field": change.field.value,
        "old": change.old,
        "new": change.new,
        "at": change.at.isoformat(),
        "how": change.act.how.value,
        "request": change.act.request,
    }


def edit_view(edit: PersonModelEdit) -> dict[str, Any]:
    """What a panel's write did: the store's write, or why it was refused before one.

    Exactly one of the two members is set, as on the edit itself, so the page reads
    which happened rather than inferring it from a missing value.
    """
    write = edit.write
    return {
        "write": (
            None
            if write is None
            else {
                "kind": write.kind.value,
                "record_id": write.record_id,
                "refusal": None if write.refusal is None else write.refusal.value,
                "reason": write.reason,
            }
        ),
        "refused": None if edit.refused is None else edit.refused.value,
    }


__all__ = [
    "edit_view",
    "person_model_view",
    "profile_change_view",
    "profile_view",
]
