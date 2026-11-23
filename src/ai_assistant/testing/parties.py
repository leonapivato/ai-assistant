"""Canonical parties, senders and facts for a test's recorded input (ADR-0351 §2, §3).

A test that builds a :class:`~ai_assistant.core.types.RecordedChannelTrigger` names
whose words its input carries. These are the parties the kinds declare, as admission
records them (:func:`~ai_assistant.core.channel_validation.declared_input`): the
owner's for a message the owner's linked account sent on the hub chat or the line, the
assistant's statement on the Task Scheduler, and, for a test that only needs an input
that is outside, one member nobody identified.

Who sent it and the three facts of its work decide whose it is (ADR-0366 §4:1,
ADR-0368 §9): :data:`OWNER_SENDER` is the owner by a link at the hub chat's and the
line's declared most, and :data:`OWNERS_FACTS` a work the owner's own message started.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from ai_assistant.core.channel_validation import declared_input
from ai_assistant.core.types import (
    OWNER_PERSON_ID,
    AuthorityKind,
    ChannelIdentity,
    InputSender,
    StatementPart,
    SupportHolder,
    Sureness,
    WorkAuthority,
    WorkFacts,
    WorkFor,
    parties_are_persons_own,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.core.types import RecordedInputMessage

__all__ = [
    "ASSISTANTS_WORDS",
    "OWNERS_FACTS",
    "OWNERS_WORDS",
    "OWNER_SENDER",
    "UNIDENTIFIED_WORDS",
    "line_input",
    "owners_facts",
]

#: The owner's words: the hub chat's input, or a message the line's account wrote.
OWNERS_WORDS: Final[tuple[SupportHolder, ...]] = (SupportHolder.person(OWNER_PERSON_ID),)

#: The assistant's statement: a scheduled task's instruction (ADR-0351 §3:6).
ASSISTANTS_WORDS: Final[tuple[SupportHolder, ...]] = (
    SupportHolder.statement(StatementPart.SCHEDULED_INSTRUCTION),
)

#: An input carrying words nobody identified, which is outside (ADR-0351 §5:1).
UNIDENTIFIED_WORDS: Final[tuple[SupportHolder, ...]] = (SupportHolder.unknown(),)

#: The owner, as a link of theirs at the hub chat's and the line's declared most names
#: them (ADR-0366 §4:1, §5:3).
OWNER_SENDER: Final = InputSender(person=OWNER_PERSON_ID, level=Sureness.NORMAL)

#: The three facts of a work the owner's own message started: for the owner, carrying
#: their authority, at normal (ADR-0368 §3:1, §3:2).
OWNERS_FACTS: Final = WorkFacts(
    for_whom=WorkFor.for_person(OWNER_PERSON_ID),
    authority=WorkAuthority(kind=AuthorityKind.SENDERS, persons=(OWNER_PERSON_ID,)),
    level=Sureness.NORMAL,
)


def owners_facts(parties: Sequence[SupportHolder] | None) -> WorkFacts:
    """The facts of a work the owner's linked account started, by its input's parties.

    For the owner, at normal, carrying their authority where the words are their own
    (ADR-0368 §3:2), and none otherwise, as for a forward (ADR-0351 §6:2): what a test's
    hand-built episode records, as admission would have.

    Args:
        parties: The input's parties.

    Returns:
        The facts.
    """
    if parties_are_persons_own(parties):
        return OWNERS_FACTS
    return OWNERS_FACTS.model_copy(update={"authority": WorkAuthority.none()})


#: A line's chat, whose kind declares a party for each message it takes in.
_LINE: Final = ChannelIdentity(channel_type="telegram", instance_id="testing/1")


def line_input(
    messages: Sequence[RecordedInputMessage],
) -> tuple[tuple[SupportHolder, ...], tuple[RecordedInputMessage, ...]]:
    """The parties and the messages of an input the line took in, as admission records them.

    Each message the test names no sender for is the owner's (:data:`OWNER_SENDER`), and
    gains the party the line's kind declares for it, its sender's or a forward's original
    sender, claimed, and the input's parties are their distinct parties (ADR-0351 §2:6,
    §2:7, §3:1). A message the test named no sender for comes back naming none, so a
    trigger the test builds from them records no senders, as it built them.

    Args:
        messages: The messages, as a test built them.

    Returns:
        The input's parties, and its messages each carrying its party.
    """
    sent = [
        one if one.sender is not None else one.model_copy(update={"sender": OWNER_SENDER})
        for one in messages
    ]
    parties, stamped = declared_input(_LINE, sent)
    return parties, tuple(
        one if given.sender is not None else one.model_copy(update={"sender": None})
        for one, given in zip(stamped, messages, strict=True)
    )
