"""The upgrade of an episode stored before ADR-0351 into its record (ADR-0351 §9).

Mechanical, with no model and nothing dropped (ADR-0326 §4:1, §4:4): each stored
trigger loses ``origin``, which ADR-0351 §10:2 computes from the parties and stores
nowhere, and gains ``parties``; each message it or a join on it records gains its
``party``. The parties are what the kind that wrote the record declares (ADR-0351 §3),
applied to the record as stored (§9:1, §9:2):

- an input of the hub chat with the origin ``user``, and each message it records, is
  the owner's;
- a message of the line is the owner's, or, carrying ``forwarded_from``, its sender's,
  claimed (§2:7), and a line input's parties are its messages' distinct parties, or
  the owner's where it records none and its origin is ``user``;
- an input of the informational event channel is the outside source, established,
  that its channel's identity names (§3:5);
- an input of the Task Scheduler is the assistant's statement naming the task's
  instruction, by its stored origin: ``assistant`` for that alone, ``outside`` for that
  and unknown (§3:6).

A join's messages are read by the join's own channel, hub chat or line, as the
trigger's are (§9:2). **Every record the rule does not cover gets ``None`` parties**,
and every message it or a join on it records ``None`` as its party, a forward included
(§9:3); so does a join's message on a kind the rule does not cover. No support is
rewritten (§9:4), and no understanding version or joined input gains a relay mark
(§9:6): one stored before ADR-0351 validates unchanged and marks nothing.

A pure function of the stored record, so the store applies it inside its own
transaction and a test applies it to a dict. It is **idempotent**: a record already in
ADR-0351's shape, its trigger carrying ``parties``, comes back unchanged and reports no
change.
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from ai_assistant.core.types import (
    OWNER_PERSON_ID,
    ClaimedAuthor,
    StatementPart,
    SupportHolder,
    canonical_parties,
    forward_party,
)

#: The kinds whose messages the rule covers: the hub chat's and the line's (§9:2).
_MESSAGE_KINDS = frozenset({"conversation", "telegram"})

#: §9:2 on §3:6: a Task Scheduler input's parties, by its stored origin.
_SCHEDULED: dict[str, tuple[SupportHolder, ...]] = {
    "assistant": (SupportHolder.statement(StatementPart.SCHEDULED_INSTRUCTION),),
    "outside": canonical_parties(
        (SupportHolder.statement(StatementPart.SCHEDULED_INSTRUCTION), SupportHolder.unknown())
    ),
}


def _owner() -> SupportHolder:
    return SupportHolder.person(OWNER_PERSON_ID)


def _message_party(kind: str | None, message: dict[str, Any]) -> SupportHolder | None:
    """One stored message's party on a ``kind`` the rule covers, else ``None`` (§9:2)."""
    if kind not in _MESSAGE_KINDS:
        return None
    sender = message.get("forwarded_from")
    if sender is None:
        return _owner()
    if kind != "telegram":
        return None
    try:
        author = ClaimedAuthor.model_validate(sender)
    except ValidationError:
        # Not a sender any build wrote: the rule does not cover it, and the store's
        # decode, which follows, refuses the record (ADR-0326 §4:3).
        return None
    return forward_party(author)


def _kind(place: object) -> str | None:
    """The channel type a stored target or channel names, the hub chat for a new one."""
    if not isinstance(place, dict):
        return None
    if place.get("kind") == "new_conversation":
        return "conversation"
    found = place.get("channel_type")
    return found if isinstance(found, str) else None


def _event_party(place: object) -> SupportHolder | None:
    """The connected source an informational event's channel names, established (§3:5)."""
    if not isinstance(place, dict):
        return None
    instance = place.get("instance_id")
    if not isinstance(instance, str):
        return None
    return SupportHolder.source(f"{place.get('channel_type')}:{instance}", claimed=False)


def _trigger_parties(
    kind: str | None, origin: object, trigger: dict[str, Any], held: list[SupportHolder | None]
) -> tuple[SupportHolder, ...] | None:
    """The parties §9:2 gives a stored trigger, from its kind, origin and messages."""
    found: tuple[SupportHolder, ...] | None = None
    if None in held:
        found = None
    elif kind == "telegram" and held:
        found = canonical_parties(one for one in held if one)
    elif kind in _MESSAGE_KINDS and origin == "user":
        found = (_owner(),)
    elif kind == "informational_event" and not held:
        party = _event_party(trigger.get("target"))
        found = None if party is None else (party,)
    elif kind == "task_scheduler" and not held and isinstance(origin, str):
        found = _SCHEDULED.get(origin)
    return found


def _set_parties(messages: list[Any], parties: list[SupportHolder | None]) -> None:
    for message, party in zip(messages, parties, strict=True):
        message["party"] = None if party is None else party.model_dump(mode="json")


def parties_episode(stored: dict[str, Any]) -> bool:
    """Give ``stored``'s trigger its parties and each recorded message its party, in place.

    Args:
        stored: One stored record, decoded from its JSON. A record with no processing
            record, or whose trigger or messages are not the shapes a build before
            ADR-0351 wrote, is left alone: the store's decode, which follows, judges a
            shape this does not know.

    Returns:
        Whether anything changed, so the store rewrites only a record that moved.

    It raises nothing for a malformed record: a part it cannot read is one the rule
    does not cover, and the decode that follows judges the record.
    """
    processing = stored.get("processing_record")
    trigger = processing.get("trigger") if isinstance(processing, dict) else None
    if not isinstance(trigger, dict) or "parties" in trigger or "origin" not in trigger:
        return False
    messages = trigger.get("messages", [])
    joined = processing.get("joined", []) if isinstance(processing, dict) else []
    if not isinstance(messages, list) or not isinstance(joined, list):
        return False
    if not all(isinstance(one, dict) for one in messages):
        return False
    origin = trigger.pop("origin")
    kind = _kind(trigger.get("target"))
    held = [_message_party(kind, one) for one in messages]
    parties = _trigger_parties(kind, origin, trigger, held)
    trigger["parties"] = (
        None if parties is None else [one.model_dump(mode="json") for one in parties]
    )
    _set_parties(messages, held if parties is not None else [None] * len(messages))
    for join in joined:
        carried = join.get("messages") if isinstance(join, dict) else None
        if not isinstance(carried, list) or not all(isinstance(one, dict) for one in carried):
            continue
        join_kind = _kind(join.get("channel")) if parties is not None else None
        join_held = [_message_party(join_kind, one) for one in carried]
        if None in join_held:
            join_held = [None] * len(carried)
        _set_parties(carried, join_held)
    return True
