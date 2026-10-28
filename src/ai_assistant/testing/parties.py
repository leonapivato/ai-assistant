"""Canonical parties for a test's recorded input (ADR-0351 §2, §3).

A test that builds a :class:`~ai_assistant.core.types.RecordedChannelTrigger` names
whose words its input carries. These are the parties the kinds declare, as admission
records them (:func:`~ai_assistant.core.channel_validation.declared_input`): the
owner's on the hub chat and the line, the assistant's statement on the Task Scheduler,
and, for a test that only needs an input that is outside, one member nobody
identified.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from ai_assistant.core.channel_validation import declared_input
from ai_assistant.core.types import (
    OWNER_PERSON_ID,
    ChannelIdentity,
    StatementPart,
    SupportHolder,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.core.types import RecordedInputMessage

__all__ = [
    "ASSISTANTS_WORDS",
    "OWNERS_WORDS",
    "UNIDENTIFIED_WORDS",
    "line_input",
]

#: The owner's words: the hub chat's input, or a message the line's account wrote.
OWNERS_WORDS: Final[tuple[SupportHolder, ...]] = (SupportHolder.person(OWNER_PERSON_ID),)

#: The assistant's statement: a scheduled task's instruction (ADR-0351 §3:6).
ASSISTANTS_WORDS: Final[tuple[SupportHolder, ...]] = (
    SupportHolder.statement(StatementPart.SCHEDULED_INSTRUCTION),
)

#: An input carrying words nobody identified, which is outside (ADR-0351 §5:1).
UNIDENTIFIED_WORDS: Final[tuple[SupportHolder, ...]] = (SupportHolder.unknown(),)

#: A line's chat, whose kind declares a party for each message it takes in.
_LINE: Final = ChannelIdentity(channel_type="telegram", instance_id="testing/1")


def line_input(
    messages: Sequence[RecordedInputMessage],
) -> tuple[tuple[SupportHolder, ...], tuple[RecordedInputMessage, ...]]:
    """The parties and the messages of an input the line took in, as admission records them.

    Each message gains the party the line's kind declares for it, the owner's or a
    forward's original sender, claimed, and the input's parties are their distinct
    parties (ADR-0351 §2:6, §2:7, §3:1).

    Args:
        messages: The messages, as a test built them.

    Returns:
        The input's parties, and its messages each carrying its party.
    """
    return declared_input(_LINE, messages)
