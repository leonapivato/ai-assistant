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

from typing import TYPE_CHECKING, Any

from exchange_support import text_call
from phases_support import PHONE, open_conversation, phases_harness, said, until, written
from task_support import seams
from test_engine import AT
from test_phases_task_scheduler import (
    _first_place,
    _Request,
    _responder,
    _spawning,
    _until_scheduled,
)
from test_phases_work_facts import _one_frozen

from ai_assistant.core.types import (
    HUB_DEVICE_ID,
    OWN_CHAT_CONNECTION,
    OWNER_PERSON_ID,
    Account,
    CallCheck,
    CallCheckKind,
    CallOutcomeKind,
    ChannelIdentity,
    ChannelInput,
    CheckedFor,
    CheckOutcome,
    CheckOutcomeKind,
    CheckRun,
    DueNow,
    EpisodicMemory,
    GrantHow,
    LineParts,
    MessageAuthor,
    PermissionLineKind,
    PermissionRuling,
    ProposedCall,
    RoundResponse,
    ScheduledOccurrence,
    ScheduledTask,
    ScheduledTaskAuthor,
    Sureness,
    TextChannelPayload,
)
from ai_assistant.orchestration.activation_state import admit_channel
from ai_assistant.orchestration.channel_kinds import ACCOUNT_KINDS, CONNECTION_KINDS
from ai_assistant.orchestration.permission_check import CheckSubject
from ai_assistant.orchestration.phase_path import PhaseWorking, Scheduling, had_connections
from ai_assistant.orchestration.planning import ConnectionShown, PlaceWindow
from ai_assistant.orchestration.task_scheduler import SCHEDULE
from ai_assistant.testing import FakeIdentityStore, FakePermissionLineStore
from ai_assistant.testing.tool_calling import FakeToolCallingCompleter

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.core.types import OfferedTool, PlanningExchange, RecordedCall

_OWNER_AT_NORMAL = CheckedFor.for_person(OWNER_PERSON_ID, Sureness.NORMAL)
_NO_LINE = CheckOutcome(kind=CheckOutcomeKind.ALLOWED_ON_NO_LINE)


def _linked() -> FakeIdentityStore:
    """The owner's phone, linked as the hub's start links it: the owner, at normal.

    Beside it the hub's own machine, which the hub's configuration links: the cases write
    on the local socket, so each message came through ``hub`` and is read from both
    links (ADR-0378 §6:1).
    """
    return FakeIdentityStore(
        configured=[
            Account(kind="conversation", identifier=PHONE.device_id),
            Account(kind="conversation", identifier=HUB_DEVICE_ID),
        ]
    )


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


async def test_a_tasks_call_meets_the_condition_its_task_records() -> None:
    """ADR-0368 §6:4: a grant whose condition names the connection the task was set by
    applies in its work, which meets it though it holds no activation state of its own."""
    lines = FakePermissionLineStore()
    made = await lines.record_making(
        LineParts(
            kind=PermissionLineKind.GRANT,
            who=OWNER_PERSON_ID,
            action="send_text",
            how=GrantHow.ALLOWED,
            bar=Sureness.WEAK,
            condition=OWN_CHAT_CONNECTION,
        ),
        by=OWNER_PERSON_ID,
    )
    completer = _responder(_spawning(connections="first place"), _texting_its_place)
    harness = phases_harness(
        completer, task_scheduler=seams(), identities=_linked(), phases={"lines": lines}
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
        resting = CheckOutcome(kind=CheckOutcomeKind.ALLOWED_ON_MADE_GRANT, line=made.line.id)
        assert entry.check == CallCheck(
            kind=CallCheckKind.CHECKED,
            runs=(CheckRun(checked_for=_OWNER_AT_NORMAL, outcome=resting),),
        )
    finally:
        await harness.engine.aclose()


class _Raising:
    """A policy that raises once asked: a fault after the check has run."""

    async def decide(self, request: object) -> PermissionRuling:
        del request
        msg = "the policy failed"
        raise RuntimeError(msg)

    async def resolve(self, confirmed: object, *, approved: bool) -> PermissionRuling:
        del confirmed, approved
        raise AssertionError


async def test_a_check_made_before_authorizing_fails_is_kept_on_the_entry() -> None:
    """ADR-0379 §3:2: the frozen episode keeps what the check made of a call it reached,
    though authorizing then raised and nothing ran."""
    harness = phases_harness(
        FakeToolCallingCompleter(response=_remembering_then_replying),
        identities=_linked(),
        phases={"lines": FakePermissionLineStore(), "policy": _Raising()},
    )
    conversation = await open_conversation(harness)
    await harness.engine.write_message(conversation, message=said("m-1", "I water on Sundays"))

    episode = await _one_frozen(harness)

    remembered = _entries(episode)["r1"]
    assert remembered.outcome is None
    assert remembered.check == CallCheck(
        kind=CallCheckKind.CHECKED,
        runs=(CheckRun(checked_for=_OWNER_AT_NORMAL, outcome=_NO_LINE),),
    )


def test_a_condition_naming_a_connection_the_hub_no_longer_has_is_met_for_no_work() -> None:
    """ADR-0376 §2:8: a task records where it was set; once the hub no longer has that
    connection, a condition naming it is met for none of its work's calls. The check runs
    for the task's author at the level it records, as its work's facts record it in
    advance (ADR-0368 §6:1, §6:3)."""
    task = ScheduledTask(
        id="t-1",
        person=OWNER_PERSON_ID,
        author=ScheduledTaskAuthor.PERSON,
        author_person=OWNER_PERSON_ID,
        setting_level=Sureness.WEAK,
        setting_connection="telegram:line",
        when=DueNow(),
        instruction="water the plants",
        parent="act-0",
        set_in=ChannelIdentity(channel_type="telegram", instance_id="line"),
        set_at=AT,
        chain_length=1,
        occurrences=(ScheduledOccurrence(number=1, due_at=AT),),
    )

    async def nothing_listed() -> Any:
        return (), {}

    # ADR-0368 §6:1: the occurrence's admission records the task's author in advance.
    occurrence = admit_channel(
        ChannelInput(target=SCHEDULE, payload=TextChannelPayload(text="it is time")),
        None,
        clock=lambda: AT,
        id_factory=lambda: "7d0f3c0e-3c4a-4c39-9a52-6f0a1d2b3c4d",
        task=task,
    )
    working = PhaseWorking(
        activation_id="activation",
        place=PlaceWindow(takes_message=True),
        conversation_id=None,
        trigger=occurrence.trigger,
        owner_records=True,
        round_limit=3,
        activation=occurrence,
    )
    working.scheduling = Scheduling(
        person=OWNER_PERSON_ID, set_in=task.set_in, build=nothing_listed, task=task
    )

    author = (CheckedFor.for_person(OWNER_PERSON_ID, Sureness.WEAK),)
    assert working.check_subject() == CheckSubject(runs=author, met="telegram:line")
    assert working.check_subject({"telegram:line"}).met == "telegram:line"
    assert working.check_subject({OWN_CHAT_CONNECTION}) == CheckSubject(runs=author, met=None)


def test_the_hub_has_its_own_chat_though_no_conversation_is_listed() -> None:
    """ADR-0376 §2:4, ADR-0381 §2:1: the system's own chat is one connection whatever
    conversations it holds, so a task set there meets its condition after the last
    conversation is deleted; every other listed connection is had as listed."""
    assert had_connections(()) == {OWN_CHAT_CONNECTION}
    listed = (
        ConnectionShown(place="conversation:c-1", kind=CONNECTION_KINDS["conversation"]),
        ConnectionShown(
            place="telegram:line", kind=CONNECTION_KINDS["telegram"], state="disconnected"
        ),
        ConnectionShown(place="task_scheduler:schedule", kind=CONNECTION_KINDS["task_scheduler"]),
        ConnectionShown(place="account:conn-a", kind=ACCOUNT_KINDS["email"], account="email"),
    )
    assert had_connections(listed) == {OWN_CHAT_CONNECTION, "telegram:line", "account:conn-a"}
