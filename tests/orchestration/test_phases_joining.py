"""Joining and taking over, through the engine, over the phases (ADR-0332 §3, §4).

Each case drives whole passes of the hub chat's activations with the phases wired. The
readers' half — which input waits, the start wait, marking a joined message taken in,
and the line's ``/stop`` — is step 3's (§1:3); here an input is handed straight to the
join's entry point, as a reader will hand it.

- A join before the activation commits sets the round planned before it aside, and the
  activation starts over from understanding and planning (§3:5-§3:12).
- A join once it has committed, and one after a stop, joins nothing (§3:6, and the
  activation's half of §1:4's first case: the stop, then the message, then the stage's
  end).
- A takeover stops the same person's uncommitted work on another place and brings its
  input in, naming it (§4:4-§4:7); two in one pass, one per understanding version; and
  one refused at a ``join_limit`` of 0 and at an exhausted one (§1:4's last case).
- A look-up is a pure read (ADR-0341 §2): a round of look-ups alone commits nothing and
  an input after it joins; a round mixing one with a story write runs the commitment
  step before either, and a join sets it aside whole (ADR-0341 §3).
"""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Any, Final

from phases_support import (
    SETTLE,
    Gated,
    episodes,
    frozen,
    open_conversation,
    phases_harness,
    processing,
    said,
    stopped,
    until,
    working,
    written,
)
from test_engine import AT
from test_engine_phases import _BOOK
from understanding_support import STATED_PROPOSAL, understanding_stage

from ai_assistant.core.types import (
    ActivationStop,
    CapabilityEffect,
    ControllerRule,
    ControllerStage,
    EpisodicMemory,
    Idempotency,
    InputOrigin,
    Message,
    MessageAuthor,
    ProposedCall,
    RecordedInputMessage,
    Reversibility,
    RiskLevel,
    RoundResponse,
    StageOutcome,
    ToolDefinition,
    ToolOutcome,
)
from ai_assistant.orchestration.conversations import conversation_channel
from ai_assistant.orchestration.joining import JoiningInput, input_standing
from ai_assistant.orchestration.phase_path import PhasePath
from ai_assistant.testing import FakeModelProvider, FakeStoryStore, FakeToolCallingCompleter

if TYPE_CHECKING:
    from collections.abc import Sequence

    from test_engine import Harness

    from ai_assistant.core.types import EpisodeProcessingRecord
    from ai_assistant.orchestration.phase_path import PhasePass, PhaseWorking

#: The words an input says it finishes the user's other work with: the routed model
#: below reads them as continuing the first running activation it is shown.
_FINISHES: Final = "finish"

_USERS: Final = input_standing(origin=InputOrigin.USER, established=True)


def _continuing(messages: Sequence[Message]) -> str:
    """Understanding's reply: continuing ``R1`` where the input says so and work is shown."""
    payload: dict[str, Any] = json.loads(messages[1].content)
    if _FINISHES in payload["input"]["text"] and payload.get("running"):
        return json.dumps(
            {
                "meaning": "It finishes the other work.",
                "meaning_ground": "stated",
                "continues": "R1",
            }
        )
    return STATED_PROPOSAL


def _routed() -> FakeModelProvider:
    return FakeModelProvider(reply=_continuing)


def _joining(conversation: str, text: str, *, position: int = 2) -> JoiningInput:
    return JoiningInput(
        channel=conversation_channel(conversation),
        messages=(RecordedInputMessage(text=text, sent_at=AT, position=position),),
        standing=_USERS,
    )


def _held_authorizing(entered: asyncio.Event, release: asyncio.Event) -> type[PhasePath]:
    """A path whose authorizing waits for ``release``: a join lands before acting."""

    class _Held(PhasePath):
        async def _authorize(self, given: PhasePass) -> None:
            entered.set()
            await release.wait()
            await super()._authorize(given)

    return _Held


def _held_acting(entered: asyncio.Event, release: asyncio.Event) -> type[PhasePath]:
    """A path whose acting stage yields before its first line, as a step run beside it does.

    The controller hands acting its stage with digesting beside it through two tasks
    (ADR-0309 §3:3), so the loop runs other work between the rule that made acting due
    and acting's first line: a join can land there, and only the commitment step finds it.
    """

    class _Held(PhasePath):
        async def _act(self, given: PhasePass) -> None:
            entered.set()
            await release.wait()
            await super()._act(given)

    return _Held


def _held_after_acting(entered: asyncio.Event, release: asyncio.Event) -> type[PhasePath]:
    """A path that waits for ``release`` once the first round's acting has ended."""

    class _Held(PhasePath):
        async def _act(self, given: PhasePass) -> None:
            await super()._act(given)
            if not entered.is_set():
                entered.set()
                await release.wait()

    return _Held


#: A pure read run through ``ToolInvoker`` (ADR-0341 §2:1): its capability changes
#: nothing and it does not leave the hub. The look-ups are pure reads too, but run
#: against the store under their class's ``own_records`` effect (ADR-0306 §3:1), so a
#: case that reads the invoker's own record of the call declares its own.
_HOURS: Final = ToolDefinition.model_validate(
    {
        **_BOOK.model_dump(),
        "id": "hours",
        "capability": "hours",
        "description": "Read the restaurant's opening hours.",
        "risk_level": RiskLevel.LOW,
        "reversibility": Reversibility.REVERSIBLE,
        "side_effecting": False,
        "writes": (),
        "idempotency": Idempotency.NATURAL,
        "effect": CapabilityEffect.NONE,
        "leaves_hub": False,
        "outcome_can_be_unknown": False,
        "safe_to_repeat": True,
        "parameters_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    }
)


def _call(call_id: str, name: str, **arguments: object) -> ProposedCall:
    return ProposedCall(call_id=call_id, name=name, arguments=arguments)  # type: ignore[arg-type]  # JSON values


def _shown(completer: FakeToolCallingCompleter, index: int) -> str:
    """What planning's round ``index``, counted across the case, was shown."""
    return completer.calls[index].messages[-1].content


async def _remembered(harness: Harness, episode: EpisodicMemory) -> list[str]:
    """The candidates ``episode``'s activation recorded: its done remember calls.

    A candidate is the call joined to the effect record that shows it done (ADR-0329
    §3:3), and it writes no memory.
    """
    activation = episode.id.removeprefix("activation:")
    return [
        one.id
        for one in await harness.plans.activation_effects([activation])
        if one.capability == "remember" and one.outcome is ToolOutcome.SUCCEEDED
    ]


def _held_message(entered: asyncio.Event, release: asyncio.Event) -> type[PhasePath]:
    """A path whose message waits for ``release``, once acting's commitment step marked it."""

    class _Held(PhasePath):
        async def _message(self, working: PhaseWorking, latest: Any) -> None:
            entered.set()
            await release.wait()
            await super()._message(working, latest)

    return _Held


class _GatedUnderstanding(FakeModelProvider):
    """Understanding's model, answering only once :attr:`release` is set."""

    def __init__(self) -> None:
        super().__init__(reply=STATED_PROPOSAL)
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def complete(self, messages: Sequence[Message], *, model: str | None = None) -> Message:
        self.entered.set()
        await self.release.wait()
        return await super().complete(messages, model=model)


def _record_of(found: Sequence[EpisodicMemory], activation_id: str) -> EpisodeProcessingRecord:
    (record,) = [
        one.processing_record
        for one in found
        if one.processing_record is not None
        and one.processing_record.activation_id == activation_id
    ]
    return record


def _ran(record: EpisodeProcessingRecord, stage: ControllerStage) -> list[ControllerRule]:
    return [one.due for one in record.stages if one.stage is stage]


async def _all_frozen(harness: Harness, count: int) -> list[EpisodicMemory]:
    async def done() -> bool:
        return len(await frozen(harness)) >= count

    await until(done, what=f"{count} frozen episode(s)")
    return await frozen(harness)


async def _assistant(harness: Harness, conversation: str) -> list[str]:
    return [
        one.text
        for one in await written(harness, conversation)
        if one.author is MessageAuthor.ASSISTANT
    ]


# --- §3: a join on the activation's own place ---------------------------------------


async def test_a_join_before_the_first_act_sets_the_round_aside_and_starts_over() -> None:
    """§3:5-§3:12: the commitment step finds the join, so the round runs nothing.

    Understanding and planning run again, and the round planned after the join is the
    one whose message is written.
    """
    entered, release = asyncio.Event(), asyncio.Event()
    model = FakeModelProvider(reply=STATED_PROPOSAL)
    completer = FakeToolCallingCompleter.scripted(
        RoundResponse(text="Riverside, Friday."), RoundResponse(text="Riverside, Saturday.")
    )
    harness = phases_harness(
        completer,
        phases={"path": _held_acting(entered, release)},
        understanding=understanding_stage(model=model),
    )
    conversation = await open_conversation(harness)
    await harness.engine.write_message(conversation, message=said("m-1", "book Riverside"))
    await asyncio.wait_for(entered.wait(), SETTLE)
    running = await working(harness, conversation)

    joined = harness.engine._join_running(_joining(conversation, "make it Saturday"))
    release.set()
    (episode,) = await _all_frozen(harness, 1)

    assert joined == running
    assert await _assistant(harness, conversation) == ["Riverside, Saturday."]
    record = processing(episode)
    assert record.activation_id == running
    (taken,) = record.joined
    assert [one.text for one in taken.messages] == ["make it Saturday"]
    assert taken.channel == conversation_channel(conversation)
    assert taken.taken_over_from is None
    assert [one.version for one in record.understanding] == [1, 2]
    # The round set aside stays in the record, beside the one after it.
    assert [one.text for one in record.rounds] == ["Riverside, Friday.", "Riverside, Saturday."]
    assert _ran(record, ControllerStage.UNDERSTANDING) == [ControllerRule.NOT_UNDERSTOOD] * 2
    assert _ran(record, ControllerStage.PLANNING) == [ControllerRule.FIRST_ROUND_DUE] * 2
    assert _ran(record, ControllerStage.ACTING) == [ControllerRule.ROUND_AUTHORIZED] * 2
    assert record.stages[-1].due is ControllerRule.NOTHING_DUE
    # Understanding, run again, read the trigger's input and the joined one apart.
    again = json.loads(model.calls[-1].messages[1].content)
    assert again["input"]["text"] == "book Riverside"
    assert again["input"]["joined"][0]["messages"][0]["text"] == "make it Saturday"
    # One message was written, claimed under one effect record: the set-aside round's
    # was never claimed, by any path (§3:7).
    effects = await harness.plans.activation_effects([running])
    assert [one.is_call for one in effects] == [False]


async def test_a_join_before_the_round_is_authorized_leaves_that_round_unacted() -> None:
    """§3:9, §3:12-§3:13: understanding is due again ahead of the earlier round's acting.

    The earlier round stays in the record unauthorized-to-act, and planning starts over
    for the new version.
    """
    entered, release = asyncio.Event(), asyncio.Event()
    completer = FakeToolCallingCompleter.scripted(
        RoundResponse(text="Riverside, Friday."), RoundResponse(text="Riverside, Saturday.")
    )
    harness = phases_harness(completer, phases={"path": _held_authorizing(entered, release)})
    conversation = await open_conversation(harness)
    await harness.engine.write_message(conversation, message=said("m-1", "book Riverside"))
    await asyncio.wait_for(entered.wait(), SETTLE)

    assert harness.engine._join_running(_joining(conversation, "make it Saturday"))
    release.set()
    (episode,) = await _all_frozen(harness, 1)

    assert await _assistant(harness, conversation) == ["Riverside, Saturday."]
    record = processing(episode)
    assert [one.text for one in record.rounds] == ["Riverside, Friday.", "Riverside, Saturday."]
    assert _ran(record, ControllerStage.AUTHORIZING) == [ControllerRule.ROUND_UNAUTHORIZED] * 2
    assert _ran(record, ControllerStage.ACTING) == [ControllerRule.ROUND_AUTHORIZED]


async def test_a_join_once_the_activation_has_committed_joins_nothing() -> None:
    """§3:6: the commitment step marked it before its message, so the input waits."""
    entered, release = asyncio.Event(), asyncio.Event()
    harness = phases_harness(phases={"path": _held_message(entered, release)})
    conversation = await open_conversation(harness)
    await harness.engine.write_message(conversation, message=said("m-1", "book Riverside"))
    await asyncio.wait_for(entered.wait(), SETTLE)

    joined = harness.engine._join_running(_joining(conversation, "make it Saturday"))
    release.set()
    (episode,) = await _all_frozen(harness, 1)

    assert joined is None
    assert processing(episode).joined == ()
    assert len(await _assistant(harness, conversation)) == 1


async def test_a_message_after_a_stop_joins_nothing_and_the_stopped_activation_ends() -> None:
    """§1:4's first case, the activation's half: a stop while understanding runs, then a
    message, then the stage's end. The message joins nothing; that it waits and is taken
    in once the stopped activation ends is the reader's, step 3's.
    """
    model = _GatedUnderstanding()
    harness = phases_harness(understanding=understanding_stage(model=model))
    conversation = await open_conversation(harness)
    await harness.engine.write_message(conversation, message=said("m-1", "book Riverside"))
    await asyncio.wait_for(model.entered.wait(), SETTLE)
    running = await working(harness, conversation)

    assert await harness.engine.stop_activation(running) is ActivationStop.STOPPED
    joined = harness.engine._join_running(_joining(conversation, "make it Saturday"))
    model.release.set()
    (episode,) = await _all_frozen(harness, 1)

    assert joined is None
    stopped(episode)
    assert processing(episode).joined == ()
    assert await _assistant(harness, conversation) == []


# --- §4: a takeover from another of the same person's places -------------------------


async def _two_running(harness: Harness, completer: _Counting) -> tuple[str, str]:
    """Start an activation in a conversation and hold it in planning; its conversation and id."""
    conversation = await open_conversation(harness)
    await harness.engine.write_message(conversation, message=said("a-1", "book Riverside"))
    await asyncio.wait_for(completer.entered.wait(), SETTLE)
    return conversation, await working(harness, conversation)


async def _also_running(
    harness: Harness, completer: _Counting, text: str, count: int
) -> tuple[str, str]:
    """One more conversation's activation, held in planning beside the others."""
    conversation = (await harness.engine.start_conversation()).id
    await harness.engine.write_message(conversation, message=said(f"m-{count}", text))
    running = await working(harness, conversation)

    async def planning() -> bool:
        return completer.calls_waiting >= count

    await until(planning, what=f"{count} activation(s) in planning")
    return conversation, running


class _Counting(Gated):
    """:class:`Gated`, counting the planning calls waiting on :attr:`release`."""

    def __init__(self, *responses: RoundResponse) -> None:
        super().__init__(*responses)
        self.calls_waiting = 0

    async def respond(
        self, messages: Any, tools: Any, *, model: str | None = None
    ) -> RoundResponse:
        self.calls_waiting += 1
        return await super().respond(messages, tools, model=model)


async def test_a_takeover_stops_the_uncommitted_work_and_brings_its_input_in() -> None:
    """§4:4-§4:7: the older is stopped as a stop is, and its input joins the newer."""
    completer = _Counting()
    harness = phases_harness(completer, understanding=understanding_stage(model=_routed()))
    first, older = await _two_running(harness, completer)

    second, newer = await _also_running(harness, completer, "finish it: for two", 2)
    completer.release.set()
    found = await _all_frozen(harness, 2)

    (taken_over,) = [
        one
        for one in found
        if one.processing_record is not None and one.processing_record.activation_id == older
    ]
    stopped(taken_over)
    taken = _record_of(found, newer)
    (joined,) = taken.joined
    assert joined.taken_over_from == older
    assert joined.channel == conversation_channel(first)
    assert [one.text for one in joined.messages] == ["book Riverside"]
    assert [(one.version, one.continues) for one in taken.understanding] == [(1, older), (2, None)]
    assert (ControllerStage.TAKEOVER, ControllerRule.TAKEOVER_UNDECIDED, StageOutcome.DONE) in [
        (one.stage, one.due, one.outcome) for one in taken.stages
    ]
    # Stopped as a stop is: its record written, and nothing written into its place.
    assert older in (await harness.plans.export()).stopped_activations
    assert await _assistant(harness, first) == []
    assert len(await _assistant(harness, second)) == 1


async def test_two_takeovers_in_one_pass_one_per_understanding_version() -> None:
    """§1:4's last case: each version names one running activation, and each is taken."""
    completer = _Counting()
    harness = phases_harness(completer, understanding=understanding_stage(model=_routed()))
    first, a = await _two_running(harness, completer)
    second, b = await _also_running(harness, completer, "for two", 2)

    third, c = await _also_running(harness, completer, "finish both", 3)
    completer.release.set()
    found = await _all_frozen(harness, 3)

    for older in (a, b):
        record = _record_of(found, older)
        assert record.stages[-1].due is ControllerRule.STOPPED
    taker = _record_of(found, c)
    assert [(one.taken_over_from, one.channel) for one in taker.joined] == [
        (a, conversation_channel(first)),
        (b, conversation_channel(second)),
    ]
    assert [(one.version, one.continues) for one in taker.understanding] == [
        (1, a),
        (2, b),
        (3, None),
    ]
    assert _ran(taker, ControllerStage.TAKEOVER) == [ControllerRule.TAKEOVER_UNDECIDED] * 2
    assert await _assistant(harness, first) == []
    assert await _assistant(harness, second) == []
    assert len(await _assistant(harness, third)) == 1


async def test_a_takeover_is_refused_at_a_join_limit_of_zero() -> None:
    """§6:5: 0 turns joining off, and takeover with it; nothing is stopped."""
    completer = _Counting()
    harness = phases_harness(
        completer, understanding=understanding_stage(model=_routed()), join_limit=0
    )
    first, older = await _two_running(harness, completer)

    _, newer = await _also_running(harness, completer, "finish it: for two", 2)
    completer.release.set()
    found = await _all_frozen(harness, 2)

    kept = _record_of(found, older)
    assert kept.stages[-1].due is ControllerRule.NOTHING_DUE
    assert len(await _assistant(harness, first)) == 1
    refused = _record_of(found, newer)
    assert refused.joined == ()
    # The version that named it is the only one: nothing joined, nothing to read again.
    assert [(one.version, one.continues) for one in refused.understanding] == [(1, older)]
    assert _ran(refused, ControllerStage.TAKEOVER) == [ControllerRule.TAKEOVER_UNDECIDED]
    assert older not in (await harness.plans.export()).stopped_activations


async def test_a_takeover_is_refused_once_the_join_limit_is_exhausted() -> None:
    """§1:4's last case: the second version's takeover finds the limit reached."""
    completer = _Counting()
    harness = phases_harness(
        completer, understanding=understanding_stage(model=_routed()), join_limit=1
    )
    first, a = await _two_running(harness, completer)
    second, b = await _also_running(harness, completer, "for two", 2)

    _, c = await _also_running(harness, completer, "finish both", 3)
    completer.release.set()
    found = await _all_frozen(harness, 3)

    assert _record_of(found, a).stages[-1].due is ControllerRule.STOPPED
    assert _record_of(found, b).stages[-1].due is ControllerRule.NOTHING_DUE
    assert len(await _assistant(harness, second)) == 1
    assert await _assistant(harness, first) == []
    taker = _record_of(found, c)
    assert [one.taken_over_from for one in taker.joined] == [a]
    assert [(one.version, one.continues) for one in taker.understanding] == [(1, a), (2, b)]
    assert _ran(taker, ControllerStage.TAKEOVER) == [ControllerRule.TAKEOVER_UNDECIDED] * 2
    assert b not in (await harness.plans.export()).stopped_activations


async def test_episodes_record_nothing_joined_where_nothing_joins() -> None:
    """A pass no input joins records ``joined`` empty, and no takeover runs."""
    harness = phases_harness()
    conversation = await open_conversation(harness)
    await harness.engine.write_message(conversation, message=said("m-1", "hi"))
    (episode,) = await _all_frozen(harness, 1)
    record = processing(episode)
    assert record.joined == ()
    assert _ran(record, ControllerStage.TAKEOVER) == []
    assert [one.continues for one in record.understanding] == [None]
    assert len(await episodes(harness.memory)) == 1


# --- §3:2, §3:5-§3:7: what commits, and what a set-aside round runs --------------------


async def test_a_set_aside_round_runs_none_of_its_calls_a_look_up_and_a_write_alike() -> None:
    """§3:7: nothing of the round is dispatched by any path, and planning is told why."""
    entered, release = asyncio.Event(), asyncio.Event()
    completer = FakeToolCallingCompleter.scripted(
        RoundResponse(
            calls=(
                _call("c1", "search_memory", query="dentist", looking_for="when it is"),
                _call(
                    "c2",
                    "remember",
                    fact="The user likes green tea.",
                    why="a taste",
                    rests_on_input=True,
                ),
            )
        ),
        RoundResponse(text="Noted."),
    )
    harness = phases_harness(
        completer, phases={"path": _held_acting(entered, release), "look_ups": True}
    )
    conversation = await open_conversation(harness)
    await harness.engine.write_message(conversation, message=said("m-1", "remember tea"))
    await asyncio.wait_for(entered.wait(), SETTLE)
    running = await working(harness, conversation)

    assert harness.engine._join_running(_joining(conversation, "and coffee")) == running
    release.set()
    (episode,) = await _all_frozen(harness, 1)

    assert await _remembered(harness, episode) == []
    assert [one.is_call for one in await harness.plans.activation_effects([running])] == [False]
    assert _shown(completer, 1).count("new input joined before this round acted") == 2
    record = processing(episode)
    assert _ran(record, ControllerStage.PLANNING) == [ControllerRule.FIRST_ROUND_DUE] * 2
    assert await _assistant(harness, conversation) == ["Noted."]


async def test_a_round_of_writes_commits_so_an_input_after_it_waits() -> None:
    """§3:2: a write to the hub's own records commits, with no message beside it."""
    entered, release = asyncio.Event(), asyncio.Event()
    completer = FakeToolCallingCompleter.scripted(
        RoundResponse(
            calls=(
                _call(
                    "c1",
                    "remember",
                    fact="The user likes green tea.",
                    why="a taste",
                    rests_on_input=True,
                ),
            )
        ),
        RoundResponse(text="Noted."),
    )
    harness = phases_harness(completer, phases={"path": _held_after_acting(entered, release)})
    conversation = await open_conversation(harness)
    await harness.engine.write_message(conversation, message=said("m-1", "remember tea"))
    await asyncio.wait_for(entered.wait(), SETTLE)

    joined = harness.engine._join_running(_joining(conversation, "and coffee"))
    release.set()
    (episode,) = await _all_frozen(harness, 1)

    assert joined is None
    assert processing(episode).joined == ()
    assert len(await _remembered(harness, episode)) == 1
    assert await _assistant(harness, conversation) == ["Noted."]


async def test_a_round_of_pure_reads_commits_nothing_so_an_input_still_joins() -> None:
    """§3:1-§3:2: looking something up is not acting, so the activation folds the input in."""
    entered, release = asyncio.Event(), asyncio.Event()
    completer = FakeToolCallingCompleter.scripted(
        RoundResponse(calls=(_call("c1", "hours"),)),
        RoundResponse(text="Open until ten."),
    )
    harness = phases_harness(
        completer,
        phases={
            "path": _held_after_acting(entered, release),
            "capabilities": ("hours", "book"),
        },
        tools=(_BOOK, _HOURS),
    )
    conversation = await open_conversation(harness)
    await harness.engine.write_message(conversation, message=said("m-1", "is it open late?"))
    await asyncio.wait_for(entered.wait(), SETTLE)
    running = await working(harness, conversation)

    joined = harness.engine._join_running(_joining(conversation, "on Saturday?"))
    release.set()
    (episode,) = await _all_frozen(harness, 1)

    assert joined == running
    record = processing(episode)
    assert [one.messages[0].text for one in record.joined] == ["on Saturday?"]
    assert [one.version for one in record.understanding] == [1, 2]
    # The read ran and its result stays for the new version's first round (§3:13).
    assert _ran(record, ControllerStage.PLANNING) == [ControllerRule.FIRST_ROUND_DUE] * 2
    assert [str(one.request.tool.capability) for one in harness.invoker.invocations] == ["hours"]
    assert "new input joined" not in _shown(completer, 1)
    assert await _assistant(harness, conversation) == ["Open until ten."]


async def test_a_question_a_join_set_aside_is_asked_again_with_its_exact_line() -> None:
    """ADR-0321 §2:2 beside §3:7: the user never saw it, so nothing waits on it.

    The booking needs a yes; the round asking about it is set aside by a join; the next
    version's round is told that message was never written, is offered the booking to ask
    about again, and its question records the asked call.
    """
    entered, release = asyncio.Event(), asyncio.Event()
    asking = "Shall I book Friday?"
    completer = FakeToolCallingCompleter.scripted(
        RoundResponse(calls=(_call("c1", "book", date="Friday"),)),
        RoundResponse(text=asking, asks=("1.1",)),
        RoundResponse(text=asking, asks=("1.1",)),
    )
    harness = phases_harness(completer, phases={"path": _held_acting(entered, release)})
    conversation = await open_conversation(harness)
    await harness.engine.write_message(conversation, message=said("m-1", "book Friday"))
    await asyncio.wait_for(entered.wait(), SETTLE)

    assert harness.engine._join_running(_joining(conversation, "for two"))
    release.set()
    (episode,) = await _all_frozen(harness, 1)

    shown = _shown(completer, 2)
    assert "the user never saw it" in shown
    assert "needs the user's yes, and is not yet asked" in shown
    assert "already asked about" not in shown
    record = processing(episode)
    assert [len(one.asked) for one in record.rounds] == [0, 1, 1]
    (question,) = await _assistant(harness, conversation)
    assert question.startswith(asking)
    assert question != asking, "the question carries its exact line below the prose"


# --- ADR-0341 §2-§3: a look-up is a pure read --------------------------------------------


async def test_a_round_of_look_ups_alone_commits_nothing_so_an_input_after_it_joins() -> None:
    """ADR-0341 §2:1, §3: a look-up writes nothing and stays in the hub, so no step runs.

    The round searching memory runs, the activation stays uncommitted, and an input
    sent once it has run joins; the look-up's result stays on the episode for the round
    planned from the new understanding version (ADR-0332 §3:13).
    """
    entered, release = asyncio.Event(), asyncio.Event()
    completer = FakeToolCallingCompleter.scripted(
        RoundResponse(
            calls=(_call("c1", "search_memory", query="dentist", looking_for="when it is"),)
        ),
        RoundResponse(text="Tuesday at ten."),
    )
    harness = phases_harness(
        completer, phases={"path": _held_after_acting(entered, release), "look_ups": True}
    )
    conversation = await open_conversation(harness)
    await harness.engine.write_message(conversation, message=said("m-1", "when's the dentist?"))
    await asyncio.wait_for(entered.wait(), SETTLE)
    running = await working(harness, conversation)

    joined = harness.engine._join_running(_joining(conversation, "the kids' one"))
    release.set()
    (episode,) = await _all_frozen(harness, 1)

    assert joined == running
    record = processing(episode)
    assert [one.messages[0].text for one in record.joined] == ["the kids' one"]
    assert [one.version for one in record.understanding] == [1, 2]
    assert _ran(record, ControllerStage.PLANNING) == [ControllerRule.FIRST_ROUND_DUE] * 2
    # The look-up ran and nothing set it aside: the new version's round is shown its
    # result (§3:13), and the one effect claimed is the message's.
    shown = _shown(completer, 1)
    assert "new input joined" not in shown
    (looked,) = json.loads(shown)["rounds"][0]["calls"]
    assert (looked["capability"], looked["outcome"]) == ("search_memory", "done")
    assert [one.is_call for one in await harness.plans.activation_effects([running])] == [False]
    assert await _assistant(harness, conversation) == ["Tuesday at ten."]


async def test_a_round_mixing_a_look_up_and_a_story_write_runs_the_step_and_is_set_aside() -> None:
    """ADR-0341 §3: the story write commits, so the step runs before either call.

    A join that lands before acting is found by that step, which sets the whole round
    aside, the look-up planned ahead of the write included (ADR-0332 §3:7): no story is
    started, nothing is claimed, and planning is told why for both calls.
    """
    entered, release = asyncio.Event(), asyncio.Event()
    completer = FakeToolCallingCompleter.scripted(
        RoundResponse(
            calls=(
                _call("c1", "search_memory", query="Riverside", looking_for="past trips"),
                _call("c2", "start_story", notes=["A camping trip to Riverside."]),
            )
        ),
        RoundResponse(text="Noted."),
    )
    stories = FakeStoryStore(now=lambda: AT)
    harness = phases_harness(
        completer,
        phases={
            "path": _held_acting(entered, release),
            "look_ups": True,
            "stories": stories,
            "story_calls": True,
        },
    )
    conversation = await open_conversation(harness)
    await harness.engine.write_message(conversation, message=said("m-1", "plan Riverside"))
    await asyncio.wait_for(entered.wait(), SETTLE)
    running = await working(harness, conversation)

    assert harness.engine._join_running(_joining(conversation, "in August")) == running
    release.set()
    (episode,) = await _all_frozen(harness, 1)

    assert (await stories.stories()).stories == ()
    assert [one.is_call for one in await harness.plans.activation_effects([running])] == [False]
    assert _shown(completer, 1).count("new input joined before this round acted") == 2
    record = processing(episode)
    assert [one.messages[0].text for one in record.joined] == ["in August"]
    assert _ran(record, ControllerStage.PLANNING) == [ControllerRule.FIRST_ROUND_DUE] * 2
    assert await _assistant(harness, conversation) == ["Noted."]
