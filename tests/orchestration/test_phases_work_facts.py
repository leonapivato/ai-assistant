"""Who sent a hub chat message, and its work's facts, end to end through the engine.

ADR-0368 §2: the hub chat's reader finds who sent each message from the device it was
written from, through the identity store the engine is handed (ADR-0366 §4:1), and the
episode keeps it on the trigger with the three facts the work started with. Beside them
today's path still decides (§1:3): a message from a device no link ties is answered as
every message is, and its facts say an unidentified sender's, which the log names as a
disagreement. The line's own case is ``test_phases_telegram``'s first.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from phases_support import PHONE, answered, frozen, open_conversation, phases_harness, said, until
from structlog.testing import capture_logs

from ai_assistant.core.types import (
    OWNER_PERSON_ID,
    Account,
    AuthorityKind,
    EpisodicMemory,
    InputSender,
    MessageAuthor,
    Sureness,
    WorkAuthority,
    WorkFacts,
    WorkFor,
)
from ai_assistant.orchestration.work_facts import NO_LINK
from ai_assistant.testing import FakeIdentityStore
from ai_assistant.testing.tool_calling import DEFAULT_ROUND_TEXT

if TYPE_CHECKING:
    from test_engine import Harness

_OWNER = InputSender(person=OWNER_PERSON_ID, level=Sureness.NORMAL)


async def _one_frozen(harness: Harness) -> EpisodicMemory:
    found: list[EpisodicMemory] = []

    async def done() -> bool:
        found[:] = await frozen(harness)
        return len(found) == 1

    await until(done, what="the activation's episode to freeze")
    return found[0]


async def test_a_message_from_a_linked_device_records_the_owner_and_their_facts() -> None:
    """ADR-0368 §2:6, §3:1, §3:2: the owner sent it, at normal; the work is theirs and
    carries their authority; the reply is as it always was."""
    linked = FakeIdentityStore(
        configured=[Account(kind="conversation", identifier=PHONE.device_id)]
    )
    harness = phases_harness(identities=linked)
    conversation = await open_conversation(harness)
    with capture_logs() as logs:
        await harness.engine.write_message(conversation, message=said("m-1", "hi"))
        messages = await answered(harness, conversation, 1)
        episode = await _one_frozen(harness)
    await harness.engine.aclose()

    assert [(one.author, one.text) for one in messages] == [
        (MessageAuthor.USER, "hi"),
        (MessageAuthor.ASSISTANT, DEFAULT_ROUND_TEXT),
    ]
    record = episode.processing_record
    assert record is not None
    assert record.trigger.senders == (_OWNER,)
    assert record.facts == WorkFacts(
        for_whom=WorkFor.for_person(OWNER_PERSON_ID),
        authority=WorkAuthority(kind=AuthorityKind.SENDERS, persons=(OWNER_PERSON_ID,)),
        level=Sureness.NORMAL,
    )
    (entry,) = [one for one in logs if one["event"] == "work_facts_recorded"]
    assert (entry["at"], entry["agrees"]) == ("start", True)


async def test_a_message_from_a_device_no_link_ties_is_still_answered() -> None:
    """ADR-0368 §1:3: today's path still decides, so the message is answered; its facts
    say an unidentified sender's, and the log names the disagreement."""
    harness = phases_harness(identities=FakeIdentityStore())
    conversation = await open_conversation(harness)
    with capture_logs() as logs:
        await harness.engine.write_message(conversation, message=said("m-1", "hi"))
        messages = await answered(harness, conversation, 1)
        episode = await _one_frozen(harness)
    await harness.engine.aclose()

    assert [one.author for one in messages] == [MessageAuthor.USER, MessageAuthor.ASSISTANT]
    record = episode.processing_record
    assert record is not None
    assert record.trigger.senders == (NO_LINK,)
    assert record.facts is not None
    assert record.facts.authority == WorkAuthority(kind=AuthorityKind.SENDERS, unidentified=True)
    (entry,) = [one for one in logs if one["event"] == "work_facts_recorded"]
    assert (entry["agrees"], entry["differs"]) == (False, ("authority", "level"))
