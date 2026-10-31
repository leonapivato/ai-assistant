"""The readers, through the engine: no place holds a message back (ADR-0349 §8).

Each case drives whole passes over the phases, with the hub chat's reader or the line's
over their fakes. Every message starts its own activation once its place's start wait
has passed, whatever runs there (§8:1-§8:2), and the reader marks it taken in by that
activation (§8:3):

- a message on a place while its activation runs is taken in at once, by an activation
  of its own, which the running one never records; on a place where running work has
  acted, one that continues nothing never waits on it (§1:5's case);
- ADR-0332 §1:4's first case on both places: a stop while understanding runs, then a
  message, which is taken in at once, its activation of its own (ADR-0295 §3:6);
- an older activation's first act waits for a correction still held in its place's
  start wait, whose activation absorbs it, so it dispatches nothing (§7:12, §1:5's case);
- the line's ``/stop`` stops every activation running from its chat, each by the one
  stop, and the line answers by rule once (§4:3, ADR-0332 §8:4-§8:5);
- a conversation's state names every activation running from it (§4:4);
- the composing signal reaches the hub chat's reader (ADR-0332 §5:9);
- acting's and the takeover stage's deadlines, read again after their waits (§7:13,
  §7:16).
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import TYPE_CHECKING, Any, Final, cast

import pytest
from exchange_support import says, tags, text_call
from phases_support import (
    SETTLE,
    Gated,
    answered,
    entries,
    frozen,
    input_of,
    open_conversation,
    phases_harness,
    processing,
    said,
    stopped,
    until,
    working,
)
from telegram_support import (
    CASE_START_WAIT,
    CHAT,
    REFERENCE,
    YieldingTelegram,
    stop_command,
    text,
)
from test_phases_matters import (
    _call,
    _Counting,
    _harness,
    _Planner,
    _routed,
    _Understanding,
)
from understanding_support import STATED_PROPOSAL, understanding_stage

from ai_assistant.core.config import Settings
from ai_assistant.core.errors import (
    ConfigurationError,
)
from ai_assistant.core.types import (
    ActivationStop,
    ControllerRule,
    ControllerStage,
    MessageAuthor,
    ProcessingReason,
    ProcessingStatus,
    RoundResponse,
    StageOutcome,
    TelegramIntakeKind,
    TranscriptMessage,
)
from ai_assistant.orchestration.chat import (
    DEFAULT_CHAT_COMPOSING_CAP,
    DEFAULT_CHAT_COMPOSING_LAPSE,
    DEFAULT_CHAT_START_WAIT,
)
from ai_assistant.orchestration.phase_path import PhasePath
from ai_assistant.orchestration.telegram import (
    DEFAULT_TELEGRAM_START_WAIT,
    NOTHING_RUNNING_LINE,
    STOPPED_LINE,
    TelegramLineSeams,
    line_channel,
)
from ai_assistant.testing import (
    FakeModelProvider,
    FakeTelegramBotClient,
    FakeTelegramIntakeRecord,
    FakeToolCallingCompleter,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from test_engine import Harness

    from ai_assistant.core.types import (
        EpisodeProcessingRecord,
        EpisodicMemory,
        Message,
        TelegramIntake,
    )
    from ai_assistant.orchestration.activation_state import ActivationState
    from ai_assistant.orchestration.phase_path import PhasePass

#: The line's channel, keyed by its connection and its chat.
_LINE: Final = line_channel(REFERENCE, CHAT)


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


class _Line:
    """The line's fakes, and the seams the engine is handed."""

    def __init__(self) -> None:
        self.fake = FakeTelegramBotClient(chat_id=CHAT, first_message_id=700)
        self.intake = FakeTelegramIntakeRecord()
        self.seams = TelegramLineSeams(
            client=YieldingTelegram(self.fake),
            intake=self.intake,
            reference=REFERENCE,
            poll_wait=timedelta(seconds=1),
            poll_bound=timedelta(seconds=2),
            send_bound=timedelta(seconds=1),
            start_wait=CASE_START_WAIT,
        )

    def sent(self) -> list[str]:
        return [body for _, body in self.fake.messages]


async def _frozen(harness: Harness, count: int) -> list[EpisodicMemory]:
    async def done() -> bool:
        return len(await frozen(harness)) >= count

    await until(done, what=f"{count} frozen episode(s)")
    return await frozen(harness)


def _started_by(found: Sequence[EpisodicMemory], text: str) -> EpisodicMemory:
    (episode,) = [one for one in found if input_of(one) == text]
    return episode


async def _taken_by(harness: Harness, conversation: str, position: int) -> str:
    """The activation that took the message at ``position`` in, once one has."""
    found: list[str] = []

    async def marked() -> bool:
        taken = await harness.conversation_store.taken_in(conversation, positions=[position])
        found.extend(taken.values())
        return bool(found)

    await until(marked, what=f"the message at {position} to be taken in")
    return found[0]


def _state_of(harness: Harness, activation_id: str) -> ActivationState:
    (state,) = [
        one.state
        for one in harness.engine._running
        if one.state is not None and one.state.activation_id == activation_id
    ]
    return state


async def _assistant(harness: Harness, conversation: str) -> list[str]:
    return [one.text for one in await written_by_assistant(harness, conversation)]


# --- the hub chat ----------------------------------------------------------------------


async def test_a_message_written_while_one_runs_starts_its_own_activation_at_once() -> None:
    """§8:1, §8:3: taken in while the first runs, marked by an activation of its own.

    The running activation records nothing taken in beside its trigger, and the state
    names both while both run (§4:4).
    """
    completer = Gated()
    harness = phases_harness(completer)
    conversation = await open_conversation(harness)
    await harness.engine.write_message(conversation, message=said("m-1", "book Riverside"))
    await asyncio.wait_for(completer.entered.wait(), SETTLE)
    running = await working(harness, conversation)

    second = await harness.engine.write_message(conversation, message=said("m-2", "for Saturday"))
    assert second.position is not None
    later = await _taken_by(harness, conversation, second.position)
    assert later != running
    digest = await harness.engine.conversation(conversation)
    assert digest is not None
    assert digest.state.working
    assert set(digest.state.activation_ids) == {running, later}, "the state names both"
    assert not completer.release.is_set(), "taken in while the first still runs"

    completer.release.set()
    found = await _frozen(harness, 2)
    await answered(harness, conversation, 2)
    first = _started_by(found, "book Riverside")
    assert processing(first).activation_id == running
    assert processing(first).joined == ()
    assert processing(_started_by(found, "for Saturday")).activation_id == later


async def test_a_message_where_running_work_has_acted_starts_at_once_and_never_waits() -> None:
    """§1:5's case: on its place, work that has acted runs, and a separate question is
    answered while it does: it continues nothing, so it waits on nothing (§7:29)."""
    understanding, planner = _Understanding(), _Planner()
    older_text, newer_text = "search apartments", "what's the weather?"
    planner.script(
        older_text,
        RoundResponse(
            calls=(
                text_call("Searching.", call_id="m1"),
                _call("c1", "remember", fact="Wants a flat.", why="a plan", rests_on_input=True),
            ),
        ),
    )
    planner.hold(older_text, from_round=2)
    harness = _harness(understanding, planner)
    conversation = await open_conversation(harness)
    await harness.engine.write_message(conversation, message=said("a-1", older_text))
    older = await working(harness, conversation)
    await asyncio.wait_for(planner.hold(older_text)[0].wait(), SETTLE)
    assert _state_of(harness, older).committed, "the older has acted"

    receipt = await harness.engine.write_message(conversation, message=said("b-1", newer_text))
    assert receipt.position is not None
    newer = await _taken_by(harness, conversation, receipt.position)
    (answered_first,) = await _frozen(harness, 1)
    assert processing(answered_first).activation_id == newer, (
        "the newer one ended while the older still ran: it never waited on it"
    )
    assert "Searching." in await _assistant(harness, conversation)
    assert f"done: {newer_text}" in await _assistant(harness, conversation)
    assert all(
        tags(one.text, "stimulus", waited_on="yes") == [] for one in planner.requests[newer_text]
    )
    assert _state_of(harness, older).offers == {}, "nothing was offered to the older"

    planner.hold(older_text)[1].set()
    found = await _frozen(harness, 2)
    assert processing(answered_first).joined == ()
    assert _started_by(found, older_text) is not None


async def test_a_stop_while_understanding_runs_then_a_message_starts_its_own_at_once() -> None:
    """ADR-0332 §1:4's first case on the hub chat: the stop holds nothing back
    (ADR-0295 §3:6), and neither does the place (§8:1)."""
    model = _GatedUnderstanding()
    harness = phases_harness(understanding=understanding_stage(model=model))
    conversation = await open_conversation(harness)
    await harness.engine.write_message(conversation, message=said("m-1", "book Riverside"))
    await asyncio.wait_for(model.entered.wait(), SETTLE)
    running = await working(harness, conversation)

    assert await harness.engine.stop_activation(running) is ActivationStop.STOPPED
    second = await harness.engine.write_message(
        conversation, message=said("m-2", "make it Saturday")
    )
    assert second.position is not None
    later = await _taken_by(harness, conversation, second.position)
    assert later != running
    assert not model.release.is_set(), "taken in while the stopped one's stage still runs"
    model.release.set()

    found = await _frozen(harness, 2)
    await answered(harness, conversation, 1)
    first = _started_by(found, "book Riverside")
    stopped(first)
    assert processing(first).joined == ()
    assert processing(_started_by(found, "make it Saturday")).activation_id == later


async def test_an_act_waits_for_a_correction_still_held_in_its_places_start_wait(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§7:12, §1:5's case: the correction's activation absorbs the older, which then
    dispatches nothing: Saturday is never booked."""
    understanding, planner = _Understanding(), _Planner()
    older_text, newer_text = "book Saturday", "actually Sunday, continues: Saturday"
    planner.script(
        older_text,
        RoundResponse(
            calls=(
                text_call("Booked for Saturday.", call_id="m2"),
                _call(
                    "c1",
                    "remember",
                    fact="Booked Saturday.",
                    why="the booking",
                    rests_on_input=True,
                ),
            ),
        ),
    )
    planner.hold(older_text)
    harness = _harness(understanding, planner, chat_start_wait=timedelta(milliseconds=200))
    conversation = await open_conversation(harness)
    await harness.engine.write_message(conversation, message=said("a-1", older_text))
    await asyncio.wait_for(planner.hold(older_text)[0].wait(), SETTLE)
    older = await working(harness, conversation)

    # The correction's start wait holds until the case lets it end.
    reader = harness.engine._chat_reader
    assert reader is not None
    over = asyncio.Event()

    async def held(seconds: float) -> None:
        del seconds
        await over.wait()

    monkeypatch.setattr(reader, "_sleep", held)
    matters = harness.engine._matters
    acting = matters.before_act
    waits: list[str | None] = []

    async def before_act(state: ActivationState, deadline: float) -> bool:
        waits.append(state.activation_id)
        return await acting(state, deadline)

    monkeypatch.setattr(matters, "before_act", before_act)
    receipt = await harness.engine.write_message(conversation, message=said("b-1", newer_text))
    assert receipt.position is not None
    planner.hold(older_text)[1].set()

    async def waiting() -> bool:
        return older in waits

    await until(waiting, what="the older one's act to wait")
    for _ in range(20):
        await asyncio.sleep(0.001)
    assert (
        await harness.conversation_store.taken_in(conversation, positions=[receipt.position]) == {}
    )
    assert not _state_of(harness, older).committed, "it waits, and commits nothing"

    over.set()
    found = await _frozen(harness, 2)
    newer = next(
        processing(one).activation_id for one in found if processing(one).activation_id != older
    )
    stopped(_started_by(found, older_text))
    record = processing(_started_by(found, newer_text))
    assert record.activation_id == newer
    assert [one.taken_over_from for one in record.joined] == [older]
    assert "Booked for Saturday." not in await _assistant(harness, conversation)
    effects = await harness.plans.activation_effects([older])
    assert [one for one in effects if one.capability == "remember"] == [], (
        "the older dispatched nothing"
    )


async def test_the_composing_signal_reaches_the_chats_reader(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADR-0332 §5:9: the engine hands the signal to the reader, after the Writing check."""
    harness = phases_harness()
    conversation = await open_conversation(harness)
    reader = harness.engine._chat_reader
    assert reader is not None
    signalled: list[str] = []
    monkeypatch.setattr(reader, "composing", signalled.append)

    await harness.engine.composing(conversation)

    assert signalled == [conversation]
    assert await harness.conversation_store.untaken_messages(conversation) == ()


def test_the_engines_waits_are_the_settings_defaults_and_held_to_their_bounds() -> None:
    """ADR-0332 §6:1-§6:4: the engine's own defaults are the settings', and a bad set is
    refused."""
    fields = Settings.model_fields
    assert fields["chat_start_wait"].default == DEFAULT_CHAT_START_WAIT
    assert fields["chat_composing_lapse"].default == DEFAULT_CHAT_COMPOSING_LAPSE
    assert fields["chat_composing_cap"].default == DEFAULT_CHAT_COMPOSING_CAP
    assert fields["telegram_start_wait"].default == DEFAULT_TELEGRAM_START_WAIT
    with pytest.raises(ConfigurationError, match="ADR-0332"):
        phases_harness(chat_start_wait=timedelta(seconds=11))
    with pytest.raises(ValueError, match="ADR-0332"):
        TelegramLineSeams(
            client=YieldingTelegram(FakeTelegramBotClient(chat_id=CHAT)),
            intake=FakeTelegramIntakeRecord(),
            reference=REFERENCE,
            poll_wait=timedelta(seconds=1),
            poll_bound=timedelta(seconds=2),
            send_bound=timedelta(seconds=1),
            start_wait=timedelta(0),
        )


# --- the line ---------------------------------------------------------------------------


def _line_harness(line: _Line, **knobs: Any) -> Harness:
    return phases_harness(telegram=line.seams, **knobs)


async def _line_running(harness: Harness, count: int = 1) -> tuple[str, ...]:
    """The activations the line's reader runs, once it runs ``count`` of them."""
    reader = harness.engine._telegram_reader
    assert reader is not None

    async def shown() -> bool:
        return len(reader.working) >= count

    await until(shown, what=f"{count} line activation(s) to run")
    return reader.working


async def _taken_on_the_line(line: _Line, update_id: int) -> TelegramIntake:
    """The intake record's entry for ``update_id``, once it is taken in."""
    found: list[TelegramIntake] = []

    async def taken() -> bool:
        found.extend((await line.intake.recorded([update_id])).values())
        return bool(found)

    await until(taken, what=f"update {update_id} to be taken in")
    return found[0]


async def test_a_message_on_the_line_while_one_runs_starts_its_own_at_once() -> None:
    """§8:1, §8:3 on the line: nothing joins and nothing waits in Telegram."""
    line = _Line()
    completer = Gated()
    harness = _line_harness(line, completer=completer)
    line.fake.hold(text(1, "book Riverside", message_id=40))
    await harness.engine.start()
    await asyncio.wait_for(completer.entered.wait(), SETTLE)
    (running,) = await _line_running(harness)

    line.fake.hold(text(2, "for Saturday", message_id=41))
    held = await _taken_on_the_line(line, 2)
    assert held.kind is TelegramIntakeKind.TAKEN_IN
    assert held.activation_id != running
    assert not completer.release.is_set(), "taken in while the first still runs"
    completer.release.set()
    found = await _frozen(harness, 2)
    await harness.engine.aclose()

    first = _started_by(found, "book Riverside")
    later = _started_by(found, "for Saturday")
    assert processing(first).activation_id == running
    assert processing(first).joined == ()
    assert processing(later).activation_id == held.activation_id


async def test_a_stop_on_the_line_while_understanding_runs_then_a_message_starts_its_own() -> None:
    """ADR-0332 §1:4's first case on the line: the ``/stop``, then a message, taken in at
    once while the stopped one's stage still runs."""
    line = _Line()
    model = _GatedUnderstanding()
    harness = _line_harness(line, understanding=understanding_stage(model=model))
    line.fake.hold(text(1, "book Riverside", message_id=40))
    await harness.engine.start()
    await asyncio.wait_for(model.entered.wait(), SETTLE)
    (running,) = await _line_running(harness)

    line.fake.hold(stop_command(2))
    answered_as: list[TelegramIntake] = []

    async def answered_stop() -> bool:
        answered_as.extend((await line.intake.recorded([2])).values())
        return STOPPED_LINE in line.sent() and bool(answered_as)

    await until(answered_stop, what="the stop to be answered")
    line.fake.hold(text(3, "make it Saturday", message_id=42))
    held = await _taken_on_the_line(line, 3)
    assert held.activation_id != running
    assert not model.release.is_set()
    model.release.set()

    found = await _frozen(harness, 2)
    await harness.engine.aclose()

    first = _started_by(found, "book Riverside")
    later = _started_by(found, "make it Saturday")
    stopped(first)
    assert processing(first).activation_id == running
    assert processing(first).joined == ()
    assert line.sent()[0] == STOPPED_LINE, "the stopped activation wrote nothing"
    assert answered_as[0].kind is TelegramIntakeKind.ANSWERED
    assert processing(later).activation_id == held.activation_id


async def test_a_stop_on_the_line_stops_every_activation_running_from_its_chat() -> None:
    """§4:3, §1:5: with two running, each is stopped by the one stop, answered once."""
    line = _Line()
    completer = Gated()
    harness = _line_harness(line, completer=completer)
    line.fake.hold(text(1, "book Riverside", message_id=40))
    await harness.engine.start()
    await _line_running(harness)
    line.fake.hold(text(2, "and what's the weather?", message_id=41))
    both = await _line_running(harness, 2)

    line.fake.hold(stop_command(3))

    async def answered_stop() -> bool:
        return bool(line.sent())

    await until(answered_stop, what="the stop to be answered")
    held = await harness.plans.export()
    assert set(both) <= set(held.stopped_activations), "each was stopped, its record written"
    completer.release.set()
    found = await _frozen(harness, 2)
    await harness.engine.aclose()

    assert {processing(one).activation_id for one in found} == set(both)
    for one in found:
        stopped(one)
    assert line.sent() == [STOPPED_LINE], "answered once, and neither wrote anything"


async def test_a_stop_on_the_line_with_nothing_running_stops_nothing() -> None:
    """ADR-0332 §8:5: answered "Nothing was running.", and no activation starts."""
    line = _Line()
    harness = _line_harness(line)
    line.fake.hold(stop_command(1))
    await harness.engine.start()

    async def confirmed() -> bool:
        return line.fake.held == () and bool(line.sent())

    await until(confirmed, what="the stop to be answered and confirmed")
    await harness.engine.aclose()

    assert line.sent() == [NOTHING_RUNNING_LINE]
    assert await frozen(harness) == []


#: How far ahead of acting's first line a case moves the pass's deadline.
_MOMENT: Final = 0.02


def _episode_of(found: Sequence[EpisodicMemory], activation_id: str) -> EpisodicMemory:
    (episode,) = [one for one in found if processing(one).activation_id == activation_id]
    return episode


def _of(found: Sequence[EpisodicMemory], activation_id: str) -> EpisodeProcessingRecord:
    return processing(_episode_of(found, activation_id))


async def test_acting_reads_the_deadline_again_before_its_commitment_step() -> None:
    """ADR-0349 §7:13: a pass past its deadline once acting's wait returns dispatches nothing."""

    class _Expired(PhasePath):
        async def _act(self, given: PhasePass) -> None:
            # After acting's entry checked the deadline; with nothing newer running, its
            # wait returns without yielding, so only the check after it finds it.
            cast("Any", given).deadline = asyncio.get_running_loop().time()
            await super()._act(given)

    harness = phases_harness(
        FakeToolCallingCompleter.scripted(says("Riverside, Friday.", call_id="m3")),
        phases={"path": _Expired},
    )
    conversation = await open_conversation(harness)
    await harness.engine.write_message(conversation, message=said("m-1", "book Riverside"))
    (episode,) = await _frozen(harness, 1)
    await harness.engine.aclose()

    record = processing(episode)
    assert (record.status, record.reason) == (ProcessingStatus.FAILED, ProcessingReason.TIMEOUT)
    assert entries(record)[-2:] == [
        (ControllerStage.ACTING, ControllerRule.ROUND_AUTHORIZED, StageOutcome.TIMED_OUT),
        (ControllerStage.END, ControllerRule.STAGE_TIMED_OUT, StageOutcome.DONE),
    ]
    assert "Riverside, Friday." not in [
        one.text for one in await written_by_assistant(harness, conversation)
    ]


async def test_a_takeover_reads_the_deadline_again_before_its_step(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADR-0349 §7:16: a takeover whose wait ends past the deadline absorbs nothing."""
    completer = _Counting()
    harness = phases_harness(completer, understanding=understanding_stage(model=_routed()))
    engine = harness.engine
    waiting = engine._matters.before_takeover

    async def expiring(state: Any, deadline: float) -> bool:
        # After the stage's entry checked the deadline; with every older one settled,
        # the wait returns at once, so only the check after it finds the deadline.
        assert state.working is not None
        state.working.deadline = asyncio.get_running_loop().time()
        return await waiting(state, deadline)

    monkeypatch.setattr(engine._matters, "before_takeover", expiring)
    first = await open_conversation(harness)
    await engine.write_message(first, message=said("a-1", "book Riverside"))
    await asyncio.wait_for(completer.entered.wait(), SETTLE)
    older = await working(harness, first)
    second = (await engine.start_conversation()).id
    await engine.write_message(second, message=said("b-1", "for two, continues: Riverside"))
    (taker,) = await _frozen(harness, 1)
    completer.release.set()
    found = await _frozen(harness, 2)
    await engine.aclose()

    record = processing(taker)
    assert (record.status, record.reason) == (ProcessingStatus.FAILED, ProcessingReason.TIMEOUT)
    assert entries(record)[-2:] == [
        (ControllerStage.TAKEOVER, ControllerRule.TAKEOVER_UNDECIDED, StageOutcome.TIMED_OUT),
        (ControllerStage.END, ControllerRule.STAGE_TIMED_OUT, StageOutcome.DONE),
    ]
    assert record.joined == ()
    assert _of(found, older).status is ProcessingStatus.COMPLETED, "it was not taken over"
    assert older not in (await harness.plans.export()).stopped_activations


async def written_by_assistant(harness: Harness, conversation: str) -> list[TranscriptMessage]:
    page = await harness.conversation_store.transcript(conversation, limit=100)
    assert page is not None
    return [
        one
        for one in page.entries
        if isinstance(one, TranscriptMessage) and one.author is MessageAuthor.ASSISTANT
    ]
