"""The upgrade of an episode stored before the three facts into its record (ADR-0368 §2).

Mechanical, with no model and nothing dropped (ADR-0326 §4:1, §4:4). A build before
ADR-0368's facts recorded no sender on an input and no fact on a work: who a work was for
and whether its input carried the user's authority were read from its channel type each
time they were needed, and from nothing stored. Each stored episode with a processing
record is carried with **what that rule said of it**, applied to the record as stored,
so a work from before the upgrade reads whole once the rule is gone (#3642, "nothing
else changes"):

- **Who sent it.** The hub chat and the line establish the user as the author of every
  message they take in, a forward's included, who forwarded it (ADR-0292 §5:4, ADR-0323
  §4:8): an input on either, and each message it or a join of either kind records, was
  sent by the owner, at the most either kind declares, normal (ADR-0366 §5:2), since no
  lowering stood before any could be made (§5:5). An input of any other kind, and each
  message a join of another kind records, was sent by no person.
- **Whom it is for**: the owner, for each kind the rule made the owner's, the hub chat,
  the line, an informational event, a task's occurrence and an approval's outcome
  (ADR-0338 §2:2, ADR-0350 §6:4, ADR-0361 §6:1); no one for any other.
- **Whose authority it carries**: the owner's, as its sender, where its kind
  established the owner and its parties are the owner's own words (ADR-0292 §5:5,
  ADR-0351 §6:1), before any relay mark, which the episode keeps as it was; none
  otherwise, a forward's and a record whose parties are unknown included.
- **Its level**: normal where it was the owner's message, and none otherwise.

**A join records the facts the work started with.** The rule read a work's trigger
alone, and ADR-0349 §7:5 joined only inputs of one author with one authority, so the
facts did not move at a join: each joined input is carried with the record's.

A pure function of the stored record, so the store applies it inside its own
transaction and a test applies it to a dict. It is **idempotent**: a record carried once
comes back the same.
"""

from __future__ import annotations

from typing import Any, Final

#: The owner's identity's id (ADR-0366 §2:5): the one person the rule named.
_OWNER: Final = "person:owner"

#: The kinds whose every message the rule took as the owner's: the hub chat and the line.
_THE_OWNERS_MESSAGES: Final = frozenset({"conversation", "telegram"})

#: The kinds whose work the rule made the owner's (``activation_person``).
_THE_OWNERS_WORK: Final = frozenset(
    {"conversation", "telegram", "informational_event", "task_scheduler", "approvals"}
)

#: The level an owner's message on either kind is carried at: the kinds' declared most.
_THE_OWNERS_LEVEL: Final = "normal"


def _kind(trigger: dict[str, Any]) -> str:
    """The channel type a stored trigger's input came in on, as the rule read it."""
    for held in (trigger.get("channel"), trigger.get("target")):
        if isinstance(held, dict) and isinstance(held.get("channel_type"), str):
            return str(held["channel_type"])
    return "conversation"


def _sender(kind: str) -> dict[str, Any] | None:
    """Who sent an input of ``kind``, as the rule had it: the owner, or no person."""
    if kind in _THE_OWNERS_MESSAGES:
        return {"person": _OWNER, "level": _THE_OWNERS_LEVEL}
    return None


def _owners_own(parties: object) -> bool:
    """Whether stored ``parties`` are a person's own words: set, and every one a person's."""
    return (
        isinstance(parties, list)
        and bool(parties)
        and all(isinstance(one, dict) and one.get("kind") == "person" for one in parties)
    )


def _facts(kind: str, trigger: dict[str, Any]) -> dict[str, Any]:
    """The three facts the rule gave a work of ``kind`` started by ``trigger``."""
    whom: dict[str, Any] = (
        {"kind": "person", "id": _OWNER} if kind in _THE_OWNERS_WORK else {"kind": "no_one"}
    )
    sent = kind in _THE_OWNERS_MESSAGES
    authority: dict[str, Any] = (
        {"kind": "senders", "persons": [_OWNER], "unidentified": False}
        if sent and _owners_own(trigger.get("parties"))
        else {"kind": "none", "persons": [], "unidentified": False}
    )
    return {
        "for_whom": whom,
        "authority": authority,
        "level": _THE_OWNERS_LEVEL if sent else "none",
    }


def _messages(holder: dict[str, Any]) -> list[dict[str, Any]]:
    """The stored messages a trigger or a joined input holds."""
    held = holder.get("messages")
    if not isinstance(held, list):
        return []
    return [one for one in held if isinstance(one, dict)]


def facts_episode(stored: dict[str, Any]) -> bool:
    """Carry the episode ``stored`` holds into the three facts' record, in place.

    Args:
        stored: One stored record, decoded from its JSON. A record with no processing
            record is left alone: there is no work to carry.

    Returns:
        Whether anything changed, so the store rewrites only a record that moved.

    Raises:
        ValueError: If the processing record holds no trigger the rule can read.
    """
    processing = stored.get("processing_record")
    if not isinstance(processing, dict):
        return False
    trigger = processing.get("trigger")
    if not isinstance(trigger, dict):
        msg = "a processing record holds no trigger to read"
        raise ValueError(msg)
    before = repr(processing)
    kind = _kind(trigger)
    sender = _sender(kind)
    trigger["senders"] = [] if sender is None else [sender]
    for message in _messages(trigger):
        message["sender"] = sender
    facts = _facts(kind, trigger)
    processing["facts"] = facts
    joined = processing.get("joined")
    for one in joined if isinstance(joined, list) else []:
        if not isinstance(one, dict):
            continue
        channel = one.get("channel")
        joined_kind = str(channel.get("channel_type")) if isinstance(channel, dict) else ""
        joined_sender = _sender(joined_kind)
        for message in _messages(one):
            message["sender"] = joined_sender
        one["facts"] = facts
    return repr(processing) != before
