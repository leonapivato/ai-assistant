"""The one table of ADR-0364's renames, and how a stored call under an old name is read.

ADR-0364 §8:1-§8:2 renames the tools and their arguments where planning sees them. No
stored record is rewritten: tickets, requests, effect records, the audit trail, plan
records and episodes keep the names they were written under, and code reads each old name
through this one table, arguments included (§8:5).

- :data:`CAPABILITY_RENAMES` and :data:`ARGUMENT_RENAMES` are the table: each old name
  with its new one, and each renamed tool's old argument names with their new ones.
- :func:`current_name` and :func:`current_arguments` read a recorded call's name and
  arguments as planning sees them now, for a record shown to planning.
- :func:`translated` reads a waiting request's or an unused ticket's call under an old
  name as the new tool's call (§8:6): its arguments translated by the table, where the
  translation sends what the old call would have sent. One the translation cannot carry,
  such as an email to a recipient that is not an address, is void, with why.

It imports no phase module, so planning, authorizing and the approvals may each read it
(ADR-0309 §2:3).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, cast

from pydantic import ValidationError

from ai_assistant.core.types import RequestedCall
from ai_assistant.orchestration.message_tools import FROM_THE_PERSONS_ACCOUNT

if TYPE_CHECKING:
    from collections.abc import Callable

    from ai_assistant.core.types import EgressBinding, FrozenJson, ToolDefinition

__all__ = [
    "ARGUMENT_RENAMES",
    "CAPABILITY_RENAMES",
    "Void",
    "carried",
    "current_arguments",
    "current_name",
    "translated",
]

#: ADR-0364 §8:1: each tool's old name, with its new one.
CAPABILITY_RENAMES: Final[Mapping[str, str]] = {
    "text": "send_text",
    "email": "send_email",
    "spawn": "spawn_task",
    "set_profile": "set_profile_field",
    "pin": "pin_memory",
    "unpin": "unpin_memory",
    "search_memory": "search_memories",
    "web_search": "search_web",
    "forecast_read": "read_forecast",
    "read_story": "read_matter",
    "read_older_history": "read_origin_history",
    "follow_up": "reread_result",
    "stop_activation": "stop_work",
    "remember": "remember_fact",
    "start_story": "start_matter",
    "note_story": "note_matter",
    "link_story": "add_to_matter",
    "unlink_story": "remove_from_matter",
    "move_story": "move_to_matter",
    "merge_stories": "merge_matters",
    "split_story": "split_matter",
    "group_stories": "group_matters",
    "tidy_story": "tidy_matter",
    "look_up_activation": "read_episode",
}

_MATTER: Final[Mapping[str, str]] = {"story": "matter", "stories": "matters"}
_MEMBER: Final[Mapping[str, str]] = {
    **_MATTER,
    "member_story": "member",
    "member_episode": "member",
}

#: The arguments a run reads a member's kind by: shown as ``member``, run as recorded.
_RUN_AS_RECORDED: Final = frozenset({"member_story", "member_episode"})

#: ADR-0364 §8:2: each renamed tool's old argument names, by its new name. The nested
#: call of a ``request_approval`` names its tool ``tool``, once ``capability``.
ARGUMENT_RENAMES: Final[Mapping[str, Mapping[str, str]]] = {
    "send_text": {"via": "connection"},
    "spawn_task": {"places": "connections"},
    "run_approved": {"label": "ticket"},
    "stop_work": {"activation": "work"},
    "read_episode": {"activation": "episode"},
    "read_matter": _MATTER,
    "start_matter": _MATTER,
    "note_matter": _MATTER,
    "add_to_matter": _MEMBER,
    "remove_from_matter": _MEMBER,
    "move_to_matter": _MATTER,
    "merge_matters": _MATTER,
    "split_matter": _MATTER,
    "group_matters": _MATTER,
    "tidy_matter": _MATTER,
    "remember_fact": {
        "rests_on_input": "rests_on_this_stimulus",
        "rests_on_user_messages": "rests_on_stimuli",
        "rests_on_assistant_messages": "rests_on_responses",
    },
}

#: ``request_approval``'s nested call: its key, and its tool's and arguments' keys, the
#: tool's once ``capability`` (ADR-0364 §8:2).
_REQUEST_APPROVAL: Final = "request_approval"
#: The tools whose ``notes`` are one text, which their old names took as a list.
_ONE_TEXT_NOTES: Final = frozenset({"start_matter", "group_matters"})
_NOTES: Final = "notes"
_NESTED_CALL: Final = "call"
_NESTED_TOOL: Final = "tool"
_NESTED_TOOL_BEFORE: Final = "capability"
_NESTED_ARGUMENTS: Final = "arguments"

#: What an email address looks like before its protocol's canonicaliser reads it, as
#: authorizing's gate reads one.
_ADDRESS: Final = re.compile(r"[^@\s]+@[^@\s]+")

#: What an old ``email``'s ``from`` named for the person's own account: the one account
#: this build connects, which ``send_email`` reads as it did (§8:6).
_THE_PERSONS_ACCOUNT: Final = FROM_THE_PERSONS_ACCOUNT


@dataclass(frozen=True, slots=True)
class Void:
    """A stored call the translation cannot carry, and why (ADR-0364 §8:6)."""

    reason: str


def current_name(capability: str) -> str:
    """The name planning sees a call under, read through the table (§8:4-§8:5)."""
    return CAPABILITY_RENAMES.get(capability, capability)


def current_arguments[V](capability: str, arguments: Mapping[str, V]) -> dict[str, V]:
    """A recorded call's arguments under the names planning sees now (§8:4-§8:5).

    ``capability`` is the call's name as recorded, old or new. An argument the table does
    not rename keeps its name.
    """
    current = current_name(capability)
    renamed = ARGUMENT_RENAMES.get(current, {})
    shown = {renamed.get(name, name): value for name, value in arguments.items()}
    nested = shown.get(_NESTED_CALL)
    if current == _REQUEST_APPROVAL and isinstance(nested, Mapping):
        shown[_NESTED_CALL] = cast("V", _nested_shown(nested))
    return shown


def _nested_shown(nested: Mapping[str, object]) -> dict[str, object]:
    """A ``request_approval``'s nested call under the names it goes by now (§8:2)."""
    tool = nested.get(_NESTED_TOOL, nested.get(_NESTED_TOOL_BEFORE))
    arguments = nested.get(_NESTED_ARGUMENTS)
    if not isinstance(tool, str) or not isinstance(arguments, Mapping):
        return dict(nested)
    return {
        _NESTED_TOOL: current_name(tool),
        _NESTED_ARGUMENTS: current_arguments(tool, dict(arguments)),
    }


def carried(requested: RequestedCall) -> Void | None:
    """Why a stored call under an old name is void, or ``None`` where the table carries it.

    ADR-0364 §8:6: read by its values alone, so a card and the panel can say so without
    the declarations a run reads it with.
    """
    new = CAPABILITY_RENAMES.get(str(requested.tool.capability))
    values = current_arguments(str(requested.tool.capability), dict(requested.values))
    if new in _ONE_TEXT_NOTES and isinstance(values.get(_NOTES), list | tuple):
        # Its notes were a list, which the new tool takes as one text, so the translation
        # cannot send what the old call would have, and a run reads it void too.
        return Void(reason=f"its call no longer fits {new}, so it cannot run as asked")
    if new != "send_email":
        return None
    carried = _email_values(values)
    return carried if isinstance(carried, Void) else None


def translated(
    requested: RequestedCall, declaration: Callable[[str], ToolDefinition | None]
) -> RequestedCall | Void:
    """A stored request's call read as the new tool's call (ADR-0364 §8:6).

    A call under a name the table does not rename is returned as it is. One under an old
    name is read with the new tool's declaration, ``declaration`` answering it by name,
    and its arguments translated by the table where the translation sends what the old
    call would have sent: an ``email`` from ``user`` reads as the person's one email
    account, and ``exact`` as the words wrapped whole, any tag they hold escaped, which
    the wording step sends unchanged with the tags removed, so the words are kept as
    they are (§9:9). Its binding is kept for authorizing to rebind as ADR-0321 §4:2
    rebinds.

    Returns:
        The call as the new tool's, or why it is void.
    """
    old = str(requested.tool.capability)
    new = CAPABILITY_RENAMES.get(old)
    if new is None:
        return requested
    current = declaration(new)
    if current is None:
        return Void(reason=f"{new} is not offered here, so the call cannot run")
    # A member's kind is read by the argument it is recorded under, which planning's own
    # check writes from ``member`` and a run reads (§8:2), so those keep their names.
    recorded = dict(requested.values)
    kept = {name: value for name, value in recorded.items() if name in _RUN_AS_RECORDED}
    values = {
        **current_arguments(
            old, {name: value for name, value in recorded.items() if name not in kept}
        ),
        **kept,
    }
    if new == "send_email":
        carried = _email_values(values)
        if isinstance(carried, Void):
            return carried
        values = carried
    try:
        return RequestedCall(
            tool=current,
            values=values,
            binding=_carried_binding(old, requested.binding, values),
            deliberate_repeat=requested.deliberate_repeat and not current.safe_to_repeat,
            replaces=requested.replaces,
            wording=requested.wording,
            looking_for=requested.looking_for,
        )
    except ValidationError, ValueError:
        return Void(reason=f"its call no longer fits {new}, so it cannot run as asked")


def _carried_binding(
    capability: str, binding: EgressBinding | None, values: Mapping[str, FrozenJson]
) -> EgressBinding | None:
    """A recorded call's binding with its spans under the names its arguments go by now.

    Each argument's span is the one recorded, renamed as the table renames it, and an
    argument the translation leaves out, such as an old ``email``'s ``exact``, takes its
    span with it, so the binding still describes the call it covers. Authorizing then
    rebinds it as ADR-0321 §4:2 rebinds, which refuses it where it differs.
    """
    if binding is None:
        return None
    renamed = ARGUMENT_RENAMES.get(current_name(capability), {})
    spans = []
    for span in binding.spans:
        name = (
            span.argument
            if span.argument in _RUN_AS_RECORDED
            else renamed.get(span.argument, span.argument)
        )
        if name in values:
            spans.append(
                span if name == span.argument else span.model_copy(update={"argument": name})
            )
    return binding.model_copy(update={"spans": tuple(spans)})


def _email_values(values: Mapping[str, FrozenJson]) -> dict[str, FrozenJson] | Void:
    """An old ``email``'s values as ``send_email``'s, or why they cannot be carried."""
    carried: dict[str, FrozenJson] = dict(values)
    sender = carried.pop("from", None)
    if sender != _THE_PERSONS_ACCOUNT:
        return Void(reason="it was to be sent from no email account the system holds")
    attachments = carried.pop("attachments", None)
    if attachments not in (None, [], ()):
        return Void(reason="it names an attachment, and nothing can be attached")
    # ADR-0364 §8:6, §9:9: ``exact`` reads as the words wrapped whole, which are sent
    # unchanged with the tags removed: the words themselves.
    carried.pop("exact", None)
    for argument in ("to", "cc", "bcc"):
        value = carried.get(argument)
        recipients = [value] if isinstance(value, str) else value
        if isinstance(recipients, list | tuple) and any(
            not isinstance(one, str) or _ADDRESS.fullmatch(one.strip()) is None
            for one in recipients
        ):
            return Void(reason=f"a recipient in {argument} is not an email address")
    carried["from"] = _THE_PERSONS_ACCOUNT
    return carried
