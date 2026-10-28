"""ADR-0283 §14:2 and ADR-0284 §11:2, through production composition, on the phases.

``test_channel_history_composition`` drives these cases through ``converse``'s admission
and today's table, which the cutover retires (ADR-0309 §2:6, §5:1). Each case here is
one of them with the root's phases wired and a conversational activation started by a
message the chat's reader takes in: a channel's history is its episodes, deleting or
forgetting a conversation reaches the episodes on its channel, a running activation's
state is the engine's, and an episode records where its input came from.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Final

import pytest
from phases_composition_support import (
    MEANING,
    SETTLE,
    UNDERSTANDING_INSTRUCTIONS,
    Phased,
    Turn,
    build_phased,
    phased,
)
from structlog.testing import capture_logs
from understanding_support import Rendered

from ai_assistant.core.episode_encoding import episode_content
from ai_assistant.core.types import (
    EpisodicMemory,
    InputOrigin,
    ProcessingStatus,
    RecordedChannelTrigger,
    RoundResponse,
    Validity,
)
from ai_assistant.orchestration.conversations import conversation_channel
from ai_assistant.testing import FakeToolCallingCompleter

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence
    from pathlib import Path

    from ai_assistant.core.types import MemoryWrite, Message, OfferedTool

pytestmark = pytest.mark.integration

#: The text whose planning round fails, so the activation ends failed (ADR-0284 §6:2).
_FAILS: Final = "this pass fails"
#: An event's raw text, which no episode's search text may carry (ADR-0284 §7:1).
_REPORTED: Final = "The thermostat entered eco mode."


class _FailsOn(FakeToolCallingCompleter):
    """Planning's round, failing once :attr:`fail_next` is set, and only that once.

    Set by the case just before it writes :data:`_FAILS`, so a later activation that is
    shown the failed one in its windows still plans.
    """

    def __init__(self) -> None:
        super().__init__(RoundResponse(text="Noted."))
        self.fail_next = False

    async def respond(
        self,
        messages: Sequence[Message],
        tools: Sequence[OfferedTool],
        *,
        model: str | None = None,
    ) -> RoundResponse:
        if self.fail_next:
            self.fail_next = False
            msg = "the planner is down"
            raise RuntimeError(msg)
        return await super().respond(messages, tools, model=model)


async def _started(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, **settings: Any) -> Phased:
    built = build_phased(tmp_path, monkeypatch, completer=_FailsOn(), **settings)
    await built.engine.start()
    return built


@pytest.fixture
async def composed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Phased]:
    """The production root with the phases, over a fresh data directory, started."""
    built = await _started(tmp_path, monkeypatch)
    try:
        yield built
    finally:
        await built.engine.aclose()


async def _episode(composed: Phased, address: str) -> EpisodicMemory:
    episode = phased(await composed.stored(address))
    assert episode.processing_record is not None
    return episode


async def _fail(composed: Phased, conversation_id: str) -> str:
    """One activation whose planning fails; the episode it left on the channel.

    Its failure is logged with its traceback, captured here rather than rendered: the
    console renderer's traceback holds the loop for seconds.
    """
    before = await composed.held(conversation_id)
    assert isinstance(composed.completer, _FailsOn)
    composed.completer.fail_next = True
    with capture_logs() as logs:
        turn = await composed.say(_FAILS, conversation_id)
    assert "chat_activation_failed" in [log["event"] for log in logs]
    after = await composed.held(conversation_id)
    assert after[: len(before)] == before
    assert after[len(before) :] == [turn.address]
    return turn.address


def _origin(episode: EpisodicMemory) -> InputOrigin | None:
    assert episode.processing_record is not None
    trigger = episode.processing_record.trigger
    assert isinstance(trigger, RecordedChannelTrigger)
    return trigger.origin


# --- a channel's history is its episodes (ADR-0283) ----------------------------------


async def test_a_conversational_episode_is_named_for_its_activation_on_its_channel(
    composed: Phased,
) -> None:
    """§2: the id is ``activation:<activation_id>``, and its channel names the conversation."""
    turn = await composed.say("hello")

    episode = await _episode(composed, turn.address)
    assert episode.id == f"activation:{turn.activation_id}"
    assert episode.processing_record is not None
    assert episode.processing_record.trigger.channel == conversation_channel(turn.conversation_id)
    assert await composed.held(turn.conversation_id) == [turn.address]


async def test_a_failed_activation_on_a_conversation_is_recorded_on_its_channel_with_its_status(
    composed: Phased,
) -> None:
    """ADR-0284 §11:2, §6:2: the failed activation is recorded on the channel, with its status."""
    first = await composed.say("hello")

    failed = await _fail(composed, first.conversation_id)

    episode = await _episode(composed, failed)
    assert episode.processing_record is not None
    assert episode.processing_record.status is ProcessingStatus.FAILED
    assert episode.processing_record.trigger.channel == conversation_channel(first.conversation_id)
    assert await composed.held(first.conversation_id) == [first.address, failed]
    assert episode.content == episode_content(episode), "§7:1: the one rule, failed or not"


async def test_the_digest_counts_the_channels_episodes(composed: Phased) -> None:
    """§4:2: every live episode on the channel, failed ones included (ADR-0284 §6:2)."""
    first = await composed.say("hello")
    await composed.say("again", first.conversation_id)
    await _fail(composed, first.conversation_id)

    digest = await composed.engine.conversation(first.conversation_id)

    assert digest is not None
    assert digest.recorded_turns == 3
    assert digest.last_turn_at is not None


# --- deleting and forgetting a conversation (ADR-0283 §8, ADR-0293 §2) ---------------


async def test_deleting_a_conversation_deletes_every_episode_on_its_channel(
    composed: Phased,
) -> None:
    """§8:1: failed or not, expired but unpurged, or not yet valid — all of it goes."""
    first = await composed.say("hello")
    failed = await _fail(composed, first.conversation_id)
    template = await _episode(composed, first.address)
    now = datetime.now(UTC)
    await composed.memory.add(
        template.model_copy(
            update={"id": "activation:expired", "expires_at": now - timedelta(days=1)}
        )
    )
    await composed.memory.add(
        template.model_copy(
            update={
                "id": "activation:not-yet-valid",
                "validity": Validity(valid_from=now + timedelta(days=1)),
            }
        )
    )
    assert len(await composed.held(first.conversation_id)) == 4
    other = await composed.say("another conversation")

    assert await composed.engine.forget_conversation(first.conversation_id) is True

    assert await composed.held(first.conversation_id) == []
    for gone in (first.address, failed):
        assert await composed.memory.get(gone) is None
    assert await composed.held(other.conversation_id) == [other.address]


async def test_an_episode_write_that_commits_then_cancels_on_a_deleted_conversation(
    composed: Phased, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0293 §2:7: a deleted conversation's episode is kept, cancelled or not.

    The conversation is deleted before the delayed admission write commits, and the
    activation is then cancelled: it is frozen ``interrupted``, and its episode stays on
    the place beside the earlier one, until the user forgets them.
    """
    first = await composed.say("hello")
    memory = composed.memory
    original = memory.write_atomic
    landed: list[str] = []

    async def write_atomic(writes: Sequence[MemoryWrite]) -> Sequence[str]:
        episode = [write.record.id for write in writes if write.record.id.startswith("activation:")]
        if not episode or episode[0] == first.address or landed:
            return await original(writes)
        assert await composed.engine.delete_conversation(first.conversation_id) is True
        await original(writes)
        assert await memory.get(episode[0]) is not None, "the episode landed after the delete"
        landed.append(episode[0])
        raise asyncio.CancelledError

    monkeypatch.setattr(memory, "write_atomic", write_atomic)

    await composed.write(first.conversation_id, "and again")

    async def frozen() -> bool:
        if not landed:
            return False
        kept = await memory.get(landed[0])
        return (
            isinstance(kept, EpisodicMemory)
            and kept.processing_record is not None
            and not kept.processing_record.is_open
        )

    deadline = asyncio.get_running_loop().time() + SETTLE
    while not await frozen():
        assert asyncio.get_running_loop().time() < deadline, "the cancelled episode never froze"
        await asyncio.sleep(0.005)
    kept = await memory.get(landed[0])
    assert isinstance(kept, EpisodicMemory)
    assert kept.processing_record is not None
    assert kept.processing_record.status is ProcessingStatus.INTERRUPTED
    assert await composed.held(first.conversation_id) == [first.address, landed[0]]


async def _paused_on(
    composed: Phased, monkeypatch: pytest.MonkeyPatch
) -> tuple[asyncio.Event, asyncio.Event]:
    """Hold the activation saying "slow" once its conversation stage has run."""
    entered, release = asyncio.Event(), asyncio.Event()
    original = composed.engine._begin_conversation_stage

    async def held(working: Any) -> None:
        await original(working)
        if getattr(working, "utterance", None) == "slow":
            entered.set()
            await release.wait()

    monkeypatch.setattr(composed.engine, "_begin_conversation_stage", held)
    return entered, release


async def _slow(composed: Phased, conversation_id: str, entered: asyncio.Event) -> Turn:
    """Write "slow" and wait until its activation is held; the turn it started."""
    position = await composed.write(conversation_id, "slow")
    await asyncio.wait_for(entered.wait(), SETTLE)
    activation = await composed.taken_by(conversation_id, position)
    return Turn(conversation_id=conversation_id, activation_id=activation)


async def test_a_conversation_deleted_while_an_activation_runs_keeps_its_episode(
    composed: Phased, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0293 §2:7: the activation's episode stays on the place."""
    first = await composed.say("hello")
    entered, release = await _paused_on(composed, monkeypatch)
    turn = await _slow(composed, first.conversation_id, entered)
    try:
        assert await composed.engine.delete_conversation(first.conversation_id) is True
    finally:
        release.set()

    async def frozen() -> bool:
        kept = await composed.memory.get(turn.address)
        return (
            isinstance(kept, EpisodicMemory)
            and kept.processing_record is not None
            and not kept.processing_record.is_open
        )

    deadline = asyncio.get_running_loop().time() + SETTLE
    while not await frozen():
        assert asyncio.get_running_loop().time() < deadline, "the activation never froze"
        await asyncio.sleep(0.005)
    assert await composed.held(first.conversation_id) == [first.address, turn.address]


async def test_a_conversation_forgotten_while_an_activation_runs_leaves_no_episode(
    composed: Phased, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0293 §2:6: the open episode is forgotten as ADR-0286 §8 forgets one, and the
    conversation stays (§2:4)."""
    first = await composed.say("hello")
    entered, release = await _paused_on(composed, monkeypatch)
    turn = await _slow(composed, first.conversation_id, entered)
    try:
        assert await composed.engine.forget_conversation(first.conversation_id) is True
    finally:
        release.set()
    await composed.idle(first.conversation_id)

    assert await composed.memory.get(turn.address) is None
    assert await composed.held(first.conversation_id) == []
    assert await composed.engine.conversation(first.conversation_id) is not None


async def test_a_running_activation_whose_episode_was_forgotten_still_shows_working(
    composed: Phased, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0293 §8:2, ADR-0295 §1:2: "working…" is the engine's, not the episode's."""
    first = await composed.say("hello")
    entered, release = await _paused_on(composed, monkeypatch)
    turn = await _slow(composed, first.conversation_id, entered)
    try:
        before = await composed.engine.conversation(first.conversation_id)
        assert before is not None
        assert (before.state.working, before.state.activation_ids) == (
            True,
            (turn.activation_id,),
        )
        assert await composed.engine.forget(turn.address) is True
        during = await composed.engine.conversation(first.conversation_id)
        assert during is not None
        assert (during.state.working, during.state.activation_ids) == (True, (turn.activation_id,))
    finally:
        release.set()
    await composed.idle(first.conversation_id)
    after = await composed.engine.conversation(first.conversation_id)
    assert after is not None
    assert not after.state.working


async def test_reclaim_keeps_a_conversation_whose_channel_holds_a_live_episode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§8:2: past the horizon, the one holding an episode stays and the empty one goes.

    Under a finite window only: ``None``, the default since ADR-0287 §1, switches
    reclaim off (ADR-0074 §7), so there is no horizon to pass.
    """
    composed = await _started(tmp_path, monkeypatch, episode_retention=timedelta(days=30))
    try:
        kept = (await composed.say("hello")).conversation_id
        empty = await composed.engine._conversations.begin(None)
        lifecycle = composed.engine._conversations
        assert lifecycle._retention is not None
        later = datetime.now(UTC) + lifecycle._retention + timedelta(days=1)
        monkeypatch.setattr(lifecycle, "_now", lambda: later)
        monkeypatch.setattr(composed.conversations, "_now", lambda: later)

        await lifecycle.reclaim()

        assert await composed.conversations.get(kept) is not None
        assert await composed.engine.conversation(kept) is not None
        assert await composed.conversations.get(empty.id) is None
    finally:
        await composed.engine.aclose()


# --- ADR-0284 §11:2: the experience of processing --------------------------------------


async def test_a_conversational_episode_is_the_users_and_its_content_the_meaning_and_words(
    composed: Phased,
) -> None:
    """ADR-0284 §2:2 and §7:1: admission records ``user``; content is meaning, then words."""
    episode = await _episode(composed, (await composed.say("hello there")).address)

    assert _origin(episode) is InputOrigin.USER
    assert episode.content == f"{MEANING}\nhello there"
    assert episode.content == episode_content(episode)


async def test_an_event_episode_is_outside_and_its_content_the_meaning_alone(
    composed: Phased,
) -> None:
    """ADR-0284 §2:2 and §7:1: admission records ``outside``; the words are not content."""
    result = await composed.event(_REPORTED)
    assert result.capture.episode_id is not None
    episode = await _episode(composed, result.capture.episode_id)

    assert _origin(episode) is InputOrigin.OUTSIDE
    assert episode.content == MEANING
    assert _REPORTED not in episode.content


async def test_a_later_activation_renders_the_event_as_a_report_received(
    composed: Phased,
) -> None:
    """ADR-0284 §2:3 and §8: read by ``origin``, never by the channel type.

    The next conversational activation's understanding stage is shown the event in its
    episode window as a report received, never as something the user said, with the
    report's own words (§8:5).
    """
    await composed.event(_REPORTED)
    composed.model.calls.clear()

    await composed.say("is the heating on?")

    understanding = [
        call.messages[1].content
        for call in composed.model.calls
        if call.messages[0].content in UNDERSTANDING_INSTRUCTIONS
    ]
    assert understanding, "the later activation reached the understanding stage"
    sent = Rendered(understanding[0])
    (report,) = [
        one
        for one in sent.containers("Short-term memory")
        if one.get("origin") == "a connected source"
    ]
    # ADR-0353 §3:2, §3:7: the report's own words, in a received tag from its source,
    # marked outside, and never said by the person.
    assert report.get("outside") == "yes"
    words = report.tags[0]
    assert (words.name, words.get("from")) == ("received", "informational_event:sensor")
    assert words.text == _REPORTED
