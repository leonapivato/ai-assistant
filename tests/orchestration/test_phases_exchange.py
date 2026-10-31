"""ADR-0356 §4, §5, §7:7-§7:8, §8 through the phases: the work's exchange, the stable tool
set, the ``text`` call, and each call's entry on the episode.

End to end over the engine and the phases, a scripted planner and the canonical fakes:
what each round was offered and shown, what a ``text`` call wrote and claimed, and what
the frozen episode records of every call.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final

import pytest
from exchange_support import reported
from phases_support import chat_turn, event, phases_harness, processing, written
from task_support import seams

from ai_assistant.core.types import (
    CallOutcomeKind,
    ChannelIdentity,
    DeliveryStatus,
    EpisodicMemory,
    LabelKind,
    MessageAuthor,
    PlanningLabel,
    ProposedCall,
    RecordedCall,
    RoundResponse,
    ToolOutcome,
)
from ai_assistant.orchestration.matters import STOP_ACTIVATION_CAPABILITY
from ai_assistant.orchestration.phase_path import (
    _UNKNOWN_WRITE,
    TEXT_CALL,
    TEXT_CAPABILITY,
    Delivery,
    Fitted,
    PhasePath,
    PhaseWorking,
    PlaceTarget,
    _SendRaisedError,
)
from ai_assistant.orchestration.planning import (
    WAITING_ROUND,
    PlaceWindow,
    PlannedCall,
    PlannedRound,
    RefusedCall,
)
from ai_assistant.orchestration.task_scheduler import SPAWN_CAPABILITY
from ai_assistant.testing import FakeToolCallingCompleter

if TYPE_CHECKING:
    from collections.abc import Sequence

    from test_engine import Harness

    from ai_assistant.core.types import OfferedTool, PlanningExchange

_AT: Final = datetime(2026, 10, 30, 9, 0, tzinfo=UTC)
_LINE: Final = ChannelIdentity(channel_type="telegram", instance_id="ref/42")


def _call(call_id: str, name: str, **arguments: object) -> ProposedCall:
    return ProposedCall(call_id=call_id, name=name, arguments=arguments)  # type: ignore[arg-type]  # JSON values


def _entries(episode: object) -> dict[str, RecordedCall]:
    return {one.call_id: one for one in processing(episode).call_records}  # type: ignore[arg-type]  # an episode


# --- §4:3: one tool set, on every round of every activation --------------------------


async def test_every_round_of_two_activations_is_offered_one_tool_set() -> None:
    """§4:3, §14:9: names, descriptions, schemas and order alike, on every round of a
    person's chat and of an event that is no person's."""
    completer = FakeToolCallingCompleter.scripted(
        RoundResponse(calls=(_call("c1", "nowhere"),)),
        RoundResponse(text="Done."),
        RoundResponse(calls=(_call("c2", "nowhere"),)),
        RoundResponse(),
    )
    harness = phases_harness(completer)

    await chat_turn(harness, "do something")
    await event(harness)

    offered = [call.tools for call in completer.calls]
    assert len(offered) == 4
    assert all(one == offered[0] for one in offered)
    assert offered[0][-1].name == TEXT_CAPABILITY
    await harness.engine.aclose()


async def test_a_spawn_in_an_activation_that_may_set_no_task_comes_back_refused() -> None:
    """§4:4-§4:5: offered, and refused with the reason, running nothing (ADR-0350 §3:4)."""
    completer = FakeToolCallingCompleter.scripted(
        RoundResponse(calls=(_call("c1", SPAWN_CAPABILITY, instruction="water the plants"),)),
        RoundResponse(),
    )
    harness = phases_harness(completer, task_scheduler=seams())
    await harness.engine.start()

    _, episode = await event(harness)

    assert SPAWN_CAPABILITY in {one.name for one in completer.calls[0].tools}
    (spawned,) = reported(completer.calls[1], 0)
    assert spawned["outcome"].startswith("refused")
    assert "may set a task" in spawned["outcome"]
    entry = _entries(episode)["c1"]
    assert (entry.outcome, entry.delivered) == (CallOutcomeKind.REFUSED, None)
    assert entry.reason is not None
    assert "may set a task" in entry.reason
    await harness.engine.aclose()


def test_each_condition_refuses_the_calls_it_once_withheld() -> None:
    """§4:5: the person model's calls, the Task Scheduler's, the calls on running work,
    and on a waiting round every call but a message and the stop."""
    tools = (TEXT_CALL,)
    refused = PhasePath._not_here(
        tools, person=True, scheduling=True, running=frozenset(), standing=True, waiting=True
    )
    assert refused == {}
    from ai_assistant.orchestration.matter_calls import MATTER_CALLS  # noqa: PLC0415
    from ai_assistant.orchestration.person_calls import PERSON_MODEL_CALLS  # noqa: PLC0415
    from ai_assistant.orchestration.task_scheduler import TASK_SCHEDULER_CALLS  # noqa: PLC0415

    every = (*PERSON_MODEL_CALLS, *TASK_SCHEDULER_CALLS, *MATTER_CALLS, TEXT_CALL)
    none_hold = PhasePath._not_here(
        every, person=False, scheduling=False, running=frozenset(), standing=True, waiting=False
    )
    assert "set_profile" in none_hold
    assert SPAWN_CAPABILITY in none_hold
    assert "authority" in none_hold[STOP_ACTIVATION_CAPABILITY]
    assert "no offer is open" in none_hold["answer_offer"]
    assert TEXT_CAPABILITY not in none_hold
    waiting = PhasePath._not_here(
        every,
        person=True,
        scheduling=True,
        running=frozenset({STOP_ACTIVATION_CAPABILITY, "look_up_activation"}),
        standing=True,
        waiting=True,
    )
    assert STOP_ACTIVATION_CAPABILITY not in waiting
    assert TEXT_CAPABILITY not in waiting
    assert waiting["look_up_activation"] == WAITING_ROUND
    assert waiting[SPAWN_CAPABILITY] == WAITING_ROUND


# --- §7:7-§7:8: a text call ------------------------------------------------------------


async def test_a_text_call_is_written_into_its_place_and_its_entry_holds_what_it_sent() -> None:
    """§7:7-§7:8, §8:2-§8:4, §14:9: written into the input's place under an effect record
    naming its round and the position the medium recorded; its entry holds the words,
    where they went and how; a call naming a place it was never shown is refused, with
    no delivery; and every call has an entry, the last round's included."""
    completer = FakeToolCallingCompleter.scripted(
        RoundResponse(
            calls=(
                _call("c1", TEXT_CAPABILITY, words="On it."),
                _call("c2", TEXT_CAPABILITY, words="Over there.", via="L7"),
                _call("c3", "nowhere"),
            )
        ),
        RoundResponse(calls=(_call("c4", TEXT_CAPABILITY, words="Done."),)),
        RoundResponse(),
    )
    harness = phases_harness(completer)

    conversation, episode = await chat_turn(harness, "do it")

    said = [(one.author, one.text) for one in await written(harness, conversation)]
    assert said[1:] == [(MessageAuthor.ASSISTANT, "On it."), (MessageAuthor.ASSISTANT, "Done.")]
    record = processing(episode)
    entries = _entries(episode)
    assert set(entries) == {"c1", "c2", "c3", "c4"}
    sent = entries["c1"]
    assert (sent.round, sent.capability, sent.effect, sent.outcome) == (
        record.rounds[0].id,
        TEXT_CAPABILITY,
        True,
        CallOutcomeKind.DONE,
    )
    assert sent.delivered is not None
    assert sent.delivered.words == "On it."
    assert sent.delivered.went.instance_id == conversation
    assert sent.delivered.status is DeliveryStatus.SENT
    elsewhere = entries["c2"]
    assert (elsewhere.outcome, elsewhere.delivered) == (CallOutcomeKind.REFUSED, None)
    assert elsewhere.reason is not None
    assert "L7" in elsewhere.reason
    assert entries["c3"].outcome is CallOutcomeKind.REFUSED
    assert entries["c4"].round == record.rounds[1].id
    effects = await harness.plans.activation_effects([record.activation_id])
    messages = [one for one in effects if one.capability is None]
    assert [(one.round, one.outcome) for one in messages] == [
        (record.rounds[0].id, ToolOutcome.SUCCEEDED),
        (record.rounds[1].id, ToolOutcome.SUCCEEDED),
    ]
    assert all(one.position is not None for one in messages)
    # The next round was shown what the message call sent.
    first, elsewhere_shown, _ = reported(completer.calls[1], 0)
    assert first["delivered"]["words"] == "On it."
    assert elsewhere_shown["outcome"].startswith("refused")
    # §8:9: the episode's outcome is the words each message call delivered, in order.
    assert episode.outcome == "On it.\n\nDone."
    await harness.engine.aclose()


# --- §8:6: when an entry is appended --------------------------------------------------


def _working() -> PhaseWorking:
    return PhaseWorking(
        activation_id="activation",
        place=PlaceWindow(takes_message=True),
        conversation_id=None,
        trigger=None,
        owner_records=True,
        round_limit=3,
    )


def _planned(*calls: ProposedCall, refused: tuple[str, ...] = ()) -> PlannedRound:
    from ai_assistant.core.types import PlanningRound  # noqa: PLC0415

    planning_round = PlanningRound(id="round-1", recorded_at=_AT, calls=calls)
    return PlannedRound(
        round=planning_round,
        labels=(PlanningLabel(label="S1", kind=LabelKind.STORY, id="story"),),
        recorded=True,
        calls=tuple(PlannedCall(one) for one in calls if one.call_id not in refused),
        refused=tuple(
            RefusedCall(one, "names nothing you were shown")
            for one in calls
            if one.call_id in refused
        ),
    )


def test_a_call_with_no_outcome_yet_gets_its_entry_at_the_freeze_with_none() -> None:
    """§8:6, §14:9: a refused call's entry is made at once; a call still running when the
    episode freezes gets one then, with no outcome; each is made once."""
    working = _working()
    working.planned(
        _planned(_call("c1", "book"), _call("c2", "nowhere"), refused=("c2",)),
        effects={"book": True},
    )

    (refused,) = working.call_entries(_AT)
    assert (refused.call_id, refused.outcome) == ("c2", CallOutcomeKind.REFUSED)
    assert working.call_entries(_AT) == ()
    (running,) = working.call_entries(_AT, freezing=True)
    assert (running.call_id, running.outcome, running.reason) == ("c1", None, None)
    assert running.effect is True
    assert working.call_entries(_AT, freezing=True) == ()


def test_a_tidy_up_that_started_gets_its_entry_with_no_outcome() -> None:
    """§8:6: a tidy-up that starts has its entry at its start, with no outcome, and the
    story's version log keeps what came of it (ADR-0307 §7:1)."""
    from ai_assistant.orchestration.authorizer import RoundAuthorization  # noqa: PLC0415
    from ai_assistant.orchestration.story_calls import TIDY_STORY_CAPABILITY  # noqa: PLC0415

    working = _working()
    working.planned(
        _planned(_call("c1", TIDY_STORY_CAPABILITY, story="story")),
        effects={TIDY_STORY_CAPABILITY: True},
    )
    assert working.call_entries(_AT) == ()

    working.latest.authorization = RoundAuthorization(
        activation_id="activation", round_id="round-1"
    )

    (started,) = working.call_entries(_AT)
    assert (started.capability, started.outcome) == (TIDY_STORY_CAPABILITY, None)


# --- review round 1: what an entry keeps when something raises, and when it is stored ---


class _RaisingWriter:
    """A place's writer that takes the message, and then raises."""

    def __init__(self) -> None:
        self.taken: list[str] = []

    def fitted(self, text: str) -> Fitted:
        return Fitted(text=text)

    async def deliver(self, fitted: Fitted, *, effect_id: str) -> Delivery:
        del effect_id
        self.taken.append(fitted.text)
        msg = "the line dropped after sending"
        raise OSError(msg)


async def test_a_write_that_raises_after_sending_keeps_what_it_tried_and_where() -> None:
    """ADR-0356 §8:4: a message whose sending was attempted holds what it sent and where,
    its status unknown, and the writer's own error is what the stage ends on."""
    harness = phases_harness(FakeToolCallingCompleter())
    phases = harness.engine._phases
    assert isinstance(phases, PhasePath)
    writer = _RaisingWriter()
    working = PhaseWorking(
        activation_id="activation",
        place=PlaceWindow(takes_message=True),
        conversation_id=None,
        trigger=None,
        owner_records=True,
        round_limit=3,
        target=PlaceTarget(channel=_LINE, writer=writer),
    )

    with pytest.raises(_SendRaisedError) as raised:
        await phases._sent(working, "Booked.", effect_id="e1", round_id="round-1", place=None)

    assert writer.taken == ["Booked."]
    assert isinstance(raised.value.__context__, OSError)
    sent = raised.value.sent
    assert (sent.kind, sent.reason) == (CallOutcomeKind.UNKNOWN, _UNKNOWN_WRITE)
    assert sent.delivered is not None
    assert (sent.delivered.words, sent.delivered.went) == ("Booked.", _LINE)
    assert sent.delivered.status is DeliveryStatus.UNKNOWN
    (effect,) = await harness.plans.activation_effects(["activation"])
    assert effect.outcome is ToolOutcome.INDETERMINATE
    await harness.engine.aclose()


def test_a_call_whose_sibling_raised_is_recorded_from_its_effect_record() -> None:
    """ADR-0356 §8:6, ADR-0306 §6: where acting raised and handed back nothing, a call its
    effect record says finished is recorded so; one with no record stays without one."""
    from ai_assistant.orchestration.authorizer import (  # noqa: PLC0415
        CallVerdict,
        RoundAuthorization,
        Verdict,
    )

    working = _working()
    working.planned(_planned(_call("c1", "book"), _call("c2", "web_search")))
    working.latest.authorization = RoundAuthorization(
        activation_id="activation",
        round_id="round-1",
        verdicts=(
            CallVerdict("c1", Verdict.ALLOWED, decision_id="d1", effect_id="e1"),
            CallVerdict("c2", Verdict.ALLOWED, decision_id="d2"),
        ),
    )
    working.latest.finished = {"e1": (ToolOutcome.SUCCEEDED, None)}

    (booked,) = working.call_entries(_AT)
    assert (booked.call_id, booked.outcome) == ("c1", CallOutcomeKind.DONE)
    (searched,) = working.call_entries(_AT, freezing=True)
    assert (searched.call_id, searched.outcome) == ("c2", None)


async def test_a_text_call_naming_its_place_by_anything_but_one_label_sends_nothing() -> None:
    """ADR-0356 §7:7: ``via`` names one place by its L label; a list of none is no place,
    and never the input's by default."""
    completer = FakeToolCallingCompleter.scripted(
        RoundResponse(calls=(_call("c1", TEXT_CAPABILITY, words="Hello.", via=[]),)),
        RoundResponse(),
    )
    harness = phases_harness(completer)

    conversation, episode = await chat_turn(harness, "say hello")

    said = [one.text for one in await written(harness, conversation)]
    assert "Hello." not in said
    entry = _entries(episode)["c1"]
    assert (entry.outcome, entry.delivered) == (CallOutcomeKind.REFUSED, None)
    assert entry.reason is not None
    assert "one place" in entry.reason
    await harness.engine.aclose()


class _Watching(FakeToolCallingCompleter):
    """Planning's model, reading the stored open episode as its second round is asked."""

    def __init__(self, harness_of: list[Harness], *responses: RoundResponse) -> None:
        super().__init__()
        self._responses = list(responses)
        self._harness_of = harness_of
        self.stored: tuple[RecordedCall, ...] | None = None

    async def respond(
        self,
        exchange: PlanningExchange,
        tools: Sequence[OfferedTool],
        *,
        model: str | None = None,
    ) -> RoundResponse:
        if exchange.steps and self.stored is None:
            (harness,) = self._harness_of
            (opened,) = [
                one
                for one in await harness.memory.export()
                if isinstance(one, EpisodicMemory)
                and one.processing_record is not None
                and one.processing_record.is_open
            ]
            assert opened.processing_record is not None
            self.stored = opened.processing_record.call_records
        await super().respond(exchange, tools, model=model)
        return self._responses.pop(0)


async def test_each_calls_entry_is_stored_before_the_next_rounds_request() -> None:
    """ADR-0356 §8:6, §14:9: the open episode holds the last round's entries when the next
    round is asked, not only at the freeze."""
    holder: list[Harness] = []
    completer = _Watching(
        holder,
        RoundResponse(calls=(_call("c1", TEXT_CAPABILITY, words="On it."), _call("c2", "nowhere"))),
        RoundResponse(),
    )
    harness = phases_harness(completer)
    holder.append(harness)

    await chat_turn(harness, "do it")

    assert completer.stored is not None
    assert {one.call_id: one.outcome for one in completer.stored} == {
        "c1": CallOutcomeKind.DONE,
        "c2": CallOutcomeKind.REFUSED,
    }
    await harness.engine.aclose()
