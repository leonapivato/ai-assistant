"""What a conversation's state shows after a hand-over, over the canonical memory fake.

ADR-0352 §5:1-§5:3: an activation absorbed, or whose input was taken, is never the one whose
ending a conversation shows. Its episode names the activation that took its matter, which
the state follows forward to the one that took it last. Where that one was started from the
same conversation and has ended, its ending is shown; otherwise, while it runs, where it was
started from another place, or where its episode is not found, the taken-over episode is
passed over and the next newest ended one is read the same way. The engine drives the same
reading through whole passes in ``test_phases_matters``.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Final

from channel_episodes import SEEDED_AT, conversation_episode

from ai_assistant.core.types import (
    ActivationEnding,
    ControllerRule,
    EpisodicMemory,
    ProcessingReason,
    ProcessingStatus,
)
from ai_assistant.orchestration.conversations import conversation_state
from ai_assistant.testing import FakeMemoryStore
from ai_assistant.testing.activation import ended_pass

_HERE: Final = "c-here"
_THERE: Final = "c-there"


def _done(conversation: str, activation_id: str, *, minutes: int) -> EpisodicMemory:
    return conversation_episode(
        conversation,
        f"activation:{activation_id}",
        occurred_at=SEEDED_AT + timedelta(minutes=minutes),
    )


def _failed(conversation: str, activation_id: str, *, minutes: int) -> EpisodicMemory:
    return conversation_episode(
        conversation,
        f"activation:{activation_id}",
        occurred_at=SEEDED_AT + timedelta(minutes=minutes),
        completed=False,
    )


def _stopped(
    conversation: str, activation_id: str, *, minutes: int, taken_over_by: str | None = None
) -> EpisodicMemory:
    """An episode frozen *stopped*, naming the activation that took its matter, if one did."""
    at = SEEDED_AT + timedelta(minutes=minutes)
    episode = conversation_episode(conversation, f"activation:{activation_id}", occurred_at=at)
    assert episode.processing_record is not None
    processing = episode.processing_record.model_validate(
        {
            **dict(episode.processing_record),
            "status": ProcessingStatus.INTERRUPTED,
            "reason": ProcessingReason.STOPPED,
            "stages": ended_pass(at, ControllerRule.STOPPED),
            "taken_over_by": taken_over_by,
        }
    )
    return episode.model_copy(update={"processing_record": processing})


def _open(conversation: str, activation_id: str, *, minutes: int) -> EpisodicMemory:
    """An open episode: its activation still runs."""
    episode = _done(conversation, activation_id, minutes=minutes)
    assert episode.processing_record is not None
    processing = episode.processing_record.model_validate(
        {
            **dict(episode.processing_record),
            "status": None,
            "reason": None,
            "ended_at": None,
            "stages": (),
            "understanding_omitted": None,
        }
    )
    return episode.model_copy(update={"processing_record": processing})


async def _ending(*episodes: EpisodicMemory) -> ActivationEnding | None:
    memory = FakeMemoryStore(now=lambda: SEEDED_AT + timedelta(days=1))
    for one in episodes:
        await memory.add(one)
    return (await conversation_state(memory, _HERE)).last_ended


async def test_a_stop_a_person_made_still_reads_stopped() -> None:
    """ADR-0295 §3:4 stands: a stop with no taker is shown as one."""
    assert await _ending(_stopped(_HERE, "a1", minutes=1)) is ActivationEnding.STOPPED


async def test_a_handed_over_activation_shows_its_takers_ending_once_it_has_ended() -> None:
    """§5:3: the taker, started from this conversation and ended, is shown."""
    ending = await _ending(
        _failed(_HERE, "before", minutes=0),
        _done(_HERE, "taker", minutes=1),
        _stopped(_HERE, "handed", minutes=2, taken_over_by="taker"),
    )
    assert ending is ActivationEnding.DONE


async def test_while_the_taker_runs_the_ending_before_the_hand_over_is_kept() -> None:
    """§5:3: a taker still running is passed over to the next newest ended episode."""
    ending = await _ending(
        _failed(_HERE, "before", minutes=0),
        _open(_HERE, "taker", minutes=1),
        _stopped(_HERE, "handed", minutes=2, taken_over_by="taker"),
    )
    assert ending is ActivationEnding.COULDNT_FINISH


async def test_a_taker_started_from_another_place_keeps_the_ending_before() -> None:
    """§5:3, the owner's "go with a": across places the absorbed one's place keeps its own."""
    ending = await _ending(
        _failed(_HERE, "before", minutes=0),
        _stopped(_HERE, "absorbed", minutes=1, taken_over_by="absorber"),
        _done(_THERE, "absorber", minutes=2),
    )
    assert ending is ActivationEnding.COULDNT_FINISH


async def test_a_taker_whose_episode_is_not_found_keeps_the_ending_before() -> None:
    """§5:3: where its episode is not found, the taken-over episode is passed over."""
    ending = await _ending(
        _failed(_HERE, "before", minutes=0),
        _stopped(_HERE, "absorbed", minutes=1, taken_over_by="forgotten"),
    )
    assert ending is ActivationEnding.COULDNT_FINISH


async def test_nothing_shown_before_a_hand_over_reads_as_no_ending() -> None:
    """§5:1: never *stopped*: with nothing else ended, there is no ending to show."""
    ending = await _ending(
        _open(_HERE, "taker", minutes=0),
        _stopped(_HERE, "handed", minutes=1, taken_over_by="taker"),
    )
    assert ending is None


async def test_a_chain_of_hand_overs_is_followed_to_the_one_that_took_the_matter_last() -> None:
    """§5:3: through each episode that records one in turn."""
    ending = await _ending(
        _stopped(_HERE, "first", minutes=0, taken_over_by="second"),
        _stopped(_HERE, "second", minutes=1, taken_over_by="third"),
        _failed(_HERE, "third", minutes=2),
    )
    assert ending is ActivationEnding.COULDNT_FINISH


async def test_a_chain_still_running_at_its_end_passes_over_every_link() -> None:
    """§5:3: the burst's absorbed ones, while the newest runs, are all passed over."""
    ending = await _ending(
        _done(_HERE, "before", minutes=0),
        _stopped(_HERE, "first", minutes=1, taken_over_by="second"),
        _stopped(_HERE, "second", minutes=2, taken_over_by="third"),
        _open(_HERE, "third", minutes=3),
    )
    assert ending is ActivationEnding.DONE


async def test_many_taken_over_episodes_are_read_past_in_wider_pages() -> None:
    """The read widens while every episode it read was taken over, until one is shown."""
    handed = [
        _stopped(_HERE, f"handed-{one}", minutes=10 + one, taken_over_by="taker")
        for one in range(20)
    ]
    ending = await _ending(
        _failed(_HERE, "before", minutes=0),
        _open(_THERE, "taker", minutes=1),
        *handed,
    )
    assert ending is ActivationEnding.COULDNT_FINISH


async def test_an_ending_past_the_newest_reads_bound_is_still_kept() -> None:
    """§5:3: past a thousand hand-overs, the older episodes are read on, newest first."""
    handed = [
        _stopped(_HERE, f"handed-{one}", minutes=10 + one, taken_over_by=f"taker-{one}")
        for one in range(1001)
    ]
    takers = [_done(_THERE, f"taker-{one}", minutes=10 + one) for one in range(1001)]
    ending = await _ending(
        _done(_HERE, "older", minutes=0),
        _failed(_HERE, "before", minutes=1),
        *handed,
        *takers,
    )
    assert ending is ActivationEnding.COULDNT_FINISH
