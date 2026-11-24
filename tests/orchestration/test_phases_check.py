"""The check's record of each call, end to end through the engine and the phases.

ADR-0379 §3:2: the episode's entry for each call keeps what the check made of it, beside
what was decided, which is what it was before the check was built (ADR-0367 §4:5). The
owner's message on the hub chat, from a linked device at normal: its reply into the
input's place stays outside the check (§4:7), and a call on the assistant's own records is
*allowed, on no line*, for the owner at normal. A task the owner set: its work's text into
a connection its task suggests is checked for the task's author, at the level the task
records (ADR-0368 §6:1, §7's fifth row), though the work's own facts still carry none.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from exchange_support import text_call
from phases_support import PHONE, open_conversation, phases_harness, said, until, written
from task_support import seams
from test_phases_task_scheduler import (
    _first_place,
    _Request,
    _responder,
    _spawning,
    _until_scheduled,
)
from test_phases_work_facts import _one_frozen

from ai_assistant.core.types import (
    OWNER_PERSON_ID,
    Account,
    CallCheck,
    CallCheckKind,
    CallOutcomeKind,
    CheckedFor,
    CheckOutcome,
    CheckOutcomeKind,
    CheckRun,
    EpisodicMemory,
    MessageAuthor,
    ProposedCall,
    RoundResponse,
    Sureness,
)
from ai_assistant.testing import FakeIdentityStore, FakePermissionLineStore
from ai_assistant.testing.tool_calling import FakeToolCallingCompleter

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.core.types import OfferedTool, PlanningExchange, RecordedCall

_OWNER_AT_NORMAL = CheckedFor.for_person(OWNER_PERSON_ID, Sureness.NORMAL)
_NO_LINE = CheckOutcome(kind=CheckOutcomeKind.ALLOWED_ON_NO_LINE)


def _linked() -> FakeIdentityStore:
    """The owner's phone, linked as the hub's start links it: the owner, at normal."""
    return FakeIdentityStore(configured=[Account(kind="conversation", identifier=PHONE.device_id)])


def _entries(episode: EpisodicMemory) -> dict[str, RecordedCall]:
    assert episode.processing_record is not None
    return {one.call_id: one for one in episode.processing_record.call_records}


def _remembering_then_replying(
    exchange: PlanningExchange, _tools: Sequence[OfferedTool]
) -> RoundResponse:
    """A first round keeping a fact and replying; nothing after."""
    if exchange.steps:
        return RoundResponse()
    return RoundResponse(
        calls=(
            ProposedCall(
                call_id="r1",
                name="remember_fact",
                arguments={
                    "fact": "The owner waters the plants on Sundays.",
                    "why": "worth keeping",
                    "rests_on_this_stimulus": True,
                },
            ),
            text_call("Noted.", call_id="t1"),
        )
    )


async def test_the_owners_calls_record_the_check_beside_what_was_decided() -> None:
    """Outside for the reply into the input's place; allowed, on no line, for the rest."""
    lines = FakePermissionLineStore()
    harness = phases_harness(
        FakeToolCallingCompleter(response=_remembering_then_replying),
        identities=_linked(),
        phases={"lines": lines, "capabilities": ("remember_fact",)},
    )
    conversation = await open_conversation(harness)
    await harness.engine.write_message(conversation, message=said("m-1", "I water on Sundays"))

    episode = await _one_frozen(harness)

    entries = _entries(episode)
    assert entries["t1"].outcome is CallOutcomeKind.DONE
    assert entries["t1"].check == CallCheck(kind=CallCheckKind.OUTSIDE)
    remembered = entries["r1"]
    assert remembered.check == CallCheck(
        kind=CallCheckKind.CHECKED,
        runs=(CheckRun(checked_for=_OWNER_AT_NORMAL, outcome=_NO_LINE),),
    )


def _texting_its_place(request: _Request) -> RoundResponse:
    """The task's activation: one ``send_text`` into the place its task suggests."""
    if request.rounds:
        return RoundResponse()
    return RoundResponse(
        calls=(
            ProposedCall(
                call_id="t1",
                name="send_text",
                arguments={"connection": _first_place(request), "words": "hello"},
            ),
        )
    )


async def test_a_tasks_text_is_checked_for_its_author_at_the_level_it_records() -> None:
    """ADR-0368 §6:1, §7: the task's author at the task's level, not the work's none."""
    completer = _responder(_spawning(connections="first place"), _texting_its_place)
    harness = phases_harness(
        completer,
        task_scheduler=seams(),
        identities=_linked(),
        phases={"lines": FakePermissionLineStore()},
    )
    await harness.engine.start()
    try:
        conversation = await open_conversation(harness)
        await harness.engine.write_message(conversation, message=said("m-1", "say hello soon"))
        (episode,) = await _until_scheduled(harness, 1)

        async def spoken() -> bool:
            return any(
                one.author is MessageAuthor.ASSISTANT and one.text == "hello"
                for one in await written(harness, conversation)
            )

        await until(spoken, what="the task's message")
        entry = _entries(episode)["t1"]
        assert entry.outcome is CallOutcomeKind.DONE
        assert entry.check == CallCheck(
            kind=CallCheckKind.CHECKED,
            runs=(CheckRun(checked_for=_OWNER_AT_NORMAL, outcome=_NO_LINE),),
        )
    finally:
        await harness.engine.aclose()
