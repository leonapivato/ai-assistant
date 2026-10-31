"""What an activation the phases run captures (ADR-0221, ADR-0223, ADR-0286).

``test_engine_capture`` drove these cases through ``converse``, which retired at the
cutover (ADR-0309 §5:1). The phases' own capture — the outcome kept whole, the rounds,
the placement — is ``test_engine_phases``'s; each case here is one of today's that
reaches the same capture path from a chat activation: a typed message captures
``TEXT``, a supply holding nothing external captures an unstamped episode, and no log
on the capture path carries a word of what was written.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Final

import structlog
from phases_support import answered, chat_turn, open_conversation, phases_harness, replying, say

from ai_assistant.core.errors import ConversationStoreError, MemoryStoreError
from ai_assistant.core.types import Capture, Modality
from ai_assistant.testing import (
    FakeConversationStore,
    FakeMemoryStore,
    FakeToolCallingCompleter,
)

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime

    from ai_assistant.core.types import Conversation, MemoryWrite

#: A span no log line could carry by accident.
_SPAN: Final = "zarquon-seven-marmalade"


async def test_a_typed_message_captures_text() -> None:
    """§5: ``TEXT`` "is the default and says it did not [reach this system as speech]"."""
    _, episode = await chat_turn(phases_harness(), "I went hiking")
    assert episode.capture == Capture(modality=Modality.TEXT)


async def test_a_captured_episode_over_a_clean_supply_is_not_marked_external() -> None:
    """ADR-0223 §7: no record in the supply carried the marker, so ``False``."""
    _, episode = await chat_turn(phases_harness(), "should I book it?")
    assert episode.provenance.derived_from_external is False


class _RefusingStore(FakeMemoryStore):
    """A store whose episode write is refused, so capture degrades with the text in hand."""

    async def write_atomic(self, writes: Sequence[MemoryWrite]) -> Sequence[str]:
        msg = "the store is down"
        raise MemoryStoreError(msg)


class _RefusingIndex(FakeConversationStore):
    """A store whose ``record_turn`` is refused, which is capture's *other* logging branch."""

    async def record_turn(
        self,
        conversation_id: str,
        *,
        episode_id: str,
        occurred_at: datetime,
    ) -> Conversation | None:
        msg = "the conversation store is down"
        raise ConversationStoreError(msg)


def _writing() -> FakeToolCallingCompleter:
    return replying(f"Certainly, {_SPAN}.")


async def test_no_log_on_the_capture_path_carries_what_was_written() -> None:
    """ADR-0221 §11 test 14: rendering a message is not a licence to log it.

    ADR-0004 §5 names "message bodies" a redaction target. The capture path logs only
    where something failed, so the degraded routes are the ones worth driving: a refused
    episode write and a refused ``record_turn``, each with the message in hand, beside
    the happy path, and none of them may carry a word of it.
    """
    with structlog.testing.capture_logs() as captured:
        await chat_turn(phases_harness(_writing()), "go on")

        refusing = phases_harness(_writing(), memory=_RefusingStore())
        conversation = await open_conversation(refusing)
        await say(refusing, conversation, "go on")
        await answered(refusing, conversation, 1)

        unindexed = phases_harness(_writing(), conversation_store=_RefusingIndex())
        conversation = await open_conversation(unindexed)
        await say(unindexed, conversation, "go on")
        await answered(unindexed, conversation, 1)

    stages = {
        event.get("stage") for event in captured if event["event"] == "activation_capture_degraded"
    }
    # ADR-0286 §3: the refusing store fails the admission write, so the first stage's
    # append finds no record and logs its mismatch too.
    assert stages == {"record_turn", "episode", "append"}, (
        "every capture logging branch ran, so the assertion below has each as a subject"
    )
    assert not any(_SPAN in json.dumps(event, default=str) for event in captured), (
        "no log event on the capture path carries the message's text, elided or whole"
    )
