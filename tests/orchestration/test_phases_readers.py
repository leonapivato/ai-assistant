"""The readers, through the engine, once joining by code is gone (ADR-0349 §1:4's step 2).

Each case drives whole passes over the phases, with the hub chat's reader or the line's
over their fakes. Until the readers' own step (§1:4's step 3) the readers still hold a
place's messages behind its running activation (ADR-0332 §2:3-§2:4), but no message
joins one by code:

- a message on a place while its activation runs waits, and is taken in after it as an
  activation of its own, which the running one never records;
- ADR-0332 §1:4's first case on both places: a stop while understanding runs, then a
  message, then the stage's end — the message waits, and is taken in when the stopped
  activation ends (ADR-0295 §3:6);
- the line's ``/stop`` stops its running activation, which writes nothing, and the line
  answers by rule (ADR-0332 §8:4-§8:5);
- the composing signal reaches the hub chat's reader (§5:9);
- the per-place rule as the kinds still declare it (§2:3);
- acting's and the takeover stage's deadlines, read again after their waits (ADR-0349
  §7:13, §7:16).
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import TYPE_CHECKING, Any, Final, cast

import pytest
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
from test_phases_matters import _Counting, _routed
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
from ai_assistant.orchestration.channel_kinds import one_at_a_time
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
    TELEGRAM,
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


# --- the hub chat ----------------------------------------------------------------------


async def test_a_message_written_while_it_runs_waits_and_starts_its_own_activation() -> None:
    """ADR-0349 §1:4's step 2: no message joins by code; until step 3 the reader holds it.

    The running activation records nothing taken in beside its trigger, and the message
    is taken in after it ends, by an activation of its own.
    """
    completer = Gated()
    harness = phases_harness(completer)
    conversation = await open_conversation(harness)
    await harness.engine.write_message(conversation, message=said("m-1", "book Riverside"))
    await asyncio.wait_for(completer.entered.wait(), SETTLE)
    running = await working(harness, conversation)

    await harness.engine.write_message(conversation, message=said("m-2", "for Saturday"))
    for _ in range(20):
        await asyncio.sleep(0.001)
    assert await harness.conversation_store.taken_in(conversation, positions=[2]) == {}
    completer.release.set()
    found = await _frozen(harness, 2)
    await answered(harness, conversation, 2)

    first = _started_by(found, "book Riverside")
    later = _started_by(found, "for Saturday")
    assert processing(first).activation_id == running
    assert processing(first).joined == ()
    taken = await harness.conversation_store.taken_in(conversation, positions=[1, 2])
    assert taken == {1: running, 2: processing(later).activation_id}


async def test_a_stop_while_understanding_runs_then_a_message_waits_and_is_taken_in_after() -> None:
    """§1:4's first case on the hub chat: the stop holds nothing back (ADR-0295 §3:6)."""
    model = _GatedUnderstanding()
    harness = phases_harness(understanding=understanding_stage(model=model))
    conversation = await open_conversation(harness)
    await harness.engine.write_message(conversation, message=said("m-1", "book Riverside"))
    await asyncio.wait_for(model.entered.wait(), SETTLE)
    running = await working(harness, conversation)

    assert await harness.engine.stop_activation(running) is ActivationStop.STOPPED
    await harness.engine.write_message(conversation, message=said("m-2", "make it Saturday"))
    for _ in range(20):
        await asyncio.sleep(0.001)
    assert await harness.conversation_store.taken_in(conversation, positions=[2]) == {}, (
        "it joins nothing, and waits"
    )
    model.release.set()

    found = await _frozen(harness, 2)
    await answered(harness, conversation, 1)
    first = _started_by(found, "book Riverside")
    later = _started_by(found, "make it Saturday")
    stopped(first)
    assert processing(first).joined == ()
    assert processing(later).activation_id != running
    taken = await harness.conversation_store.taken_in(conversation, positions=[1, 2])
    assert taken == {1: running, 2: processing(later).activation_id}


async def test_the_composing_signal_reaches_the_chats_reader(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§5:9: the engine hands the signal to the reader, after the Writing check."""
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
    """§6:1-§6:4: the engine's own defaults are the settings', and a bad set is refused."""
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


async def _line_running(harness: Harness) -> str:
    """The id of the activation the line's reader runs, once it has one."""
    reader = harness.engine._telegram_reader
    assert reader is not None
    found: list[str] = []

    async def shown() -> bool:
        if reader.working is not None:
            found.append(reader.working)
        return bool(found)

    await until(shown, what="the line's activation to run")
    return found[0]


async def test_a_message_on_the_line_while_it_runs_waits_and_starts_its_own() -> None:
    """ADR-0349 §1:4's step 2 on the line: nothing joins, and the update waits in Telegram."""
    line = _Line()
    completer = Gated()
    harness = _line_harness(line, completer=completer)
    line.fake.hold(text(1, "book Riverside", message_id=40))
    await harness.engine.start()
    await asyncio.wait_for(completer.entered.wait(), SETTLE)
    running = await _line_running(harness)

    line.fake.hold(text(2, "for Saturday", message_id=41))
    for _ in range(20):
        await asyncio.sleep(0.001)
    assert 2 not in await line.intake.recorded([2]), "it waits, unmarked"
    completer.release.set()
    found = await _frozen(harness, 2)
    await harness.engine.aclose()

    first = _started_by(found, "book Riverside")
    later = _started_by(found, "for Saturday")
    assert processing(first).activation_id == running
    assert processing(first).joined == ()
    held = (await line.intake.recorded([2]))[2]
    assert (held.kind, held.activation_id) == (
        TelegramIntakeKind.TAKEN_IN,
        processing(later).activation_id,
    )


async def test_a_stop_on_the_line_while_understanding_runs_then_a_message_waits() -> None:
    """§1:4's first case on the line: the ``/stop``, a message, then the stage's end."""
    line = _Line()
    model = _GatedUnderstanding()
    harness = _line_harness(line, understanding=understanding_stage(model=model))
    line.fake.hold(text(1, "book Riverside", message_id=40))
    await harness.engine.start()
    await asyncio.wait_for(model.entered.wait(), SETTLE)
    running = await _line_running(harness)

    line.fake.hold(stop_command(2))
    answered_as: list[TelegramIntake] = []

    async def answered_stop() -> bool:
        answered_as.extend((await line.intake.recorded([2])).values())
        return STOPPED_LINE in line.sent() and bool(answered_as)

    await until(answered_stop, what="the stop to be answered")
    line.fake.hold(text(3, "make it Saturday", message_id=42))
    for _ in range(20):
        await asyncio.sleep(0.001)
    assert 3 not in await line.intake.recorded([3]), "it joins nothing, and waits"
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
    assert processing(later).activation_id != running


async def test_a_stop_on_the_line_with_nothing_running_stops_nothing() -> None:
    """§8:5: answered "Nothing was running.", and no activation starts."""
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


# --- the per-place rule (§2:3) ----------------------------------------------------------


def test_the_conversation_kind_and_the_line_run_one_activation_at_a_time() -> None:
    """§2:3: as the kinds declare it; every other kind runs side by side (§2:2)."""
    assert one_at_a_time("conversation")
    assert TELEGRAM.one_at_a_time
    assert one_at_a_time(TELEGRAM.channel_type)
    assert not one_at_a_time("upcoming_event")


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
        FakeToolCallingCompleter.scripted(RoundResponse(text="Riverside, Friday.")),
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
