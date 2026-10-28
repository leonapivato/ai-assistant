"""What the observer offers and proposes of an input, by its parties (ADR-0351 §7, §11:1).

Driven over the canonical fakes, from the reading through framing to the stamp both
writers use, so what the observer proposes is what the writer admits: your note beside a
forward is yours, the forward its sender's, claimed, and a scheduled task's input, a
marked task's included, is no part the observer offers.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Final

from observer_support import (
    AT,
    LABELS,
    Harness,
    Minter,
    address,
    episode,
    framed,
    framing,
    read_as,
    said,
)

from ai_assistant.core.types import (
    OWNER_PERSON_ID,
    ChannelIdentity,
    ClaimedAuthor,
    EpisodicMemory,
    InputPart,
    ObservationFinding,
    RecordedInputMessage,
    RoundMessagePart,
    StatementPart,
    SupportHolder,
    SupportOrigin,
    stamped_support,
)
from ai_assistant.orchestration.observer.framing import FramingView
from ai_assistant.orchestration.observer.framing import framed as framed_by_code
from ai_assistant.orchestration.observer.reading import EpisodeReader, Reading
from ai_assistant.orchestration.observer.replies import FramingReplyShape

_OWNER: Final = SupportHolder.person(OWNER_PERSON_ID)
_LINE: Final = ChannelIdentity(channel_type="telegram", instance_id="conn-1/42")
_SCHEDULE: Final = ChannelIdentity(channel_type="task_scheduler", instance_id="schedule")
_STATEMENT: Final = SupportHolder.statement(StatementPart.SCHEDULED_INSTRUCTION)


async def _read(harness: Harness, leaving_id: str) -> tuple[EpisodicMemory, Reading]:
    leaving = await harness.memory.get(address(leaving_id))
    assert isinstance(leaving, EpisodicMemory)
    reader = EpisodeReader(memory=harness.memory, plans=harness.plans, stories=harness.stories)
    return leaving, await reader.read(leaving)


async def test_your_note_beside_a_forward_is_proposed_as_yours_and_the_forward_as_its_senders() -> (
    None
):
    """§7:1, §7:2: ``user_message`` held by you, and ``outside_input`` held by Sam, claimed."""
    harness = Harness()
    sent = AT - timedelta(minutes=10)
    await harness.hold(
        episode(
            "one",
            channel=_LINE,
            messages=(
                RecordedInputMessage(text="I'm moving to Porto in May.", sent_at=sent),
                RecordedInputMessage(
                    text="Ana is moving to Porto too.",
                    sent_at=sent,
                    forwarded_from=ClaimedAuthor(name="Sam", account_id=77),
                ),
            ),
        )
    )
    leaving, reading = await _read(harness, "one")
    own, forward = reading.leaving.parts
    assert (own.origin, forward.origin) == (SupportOrigin.USER_MESSAGE, SupportOrigin.OUTSIDE_INPUT)

    view = FramingView(
        finding=ObservationFinding(
            id="f1",
            episode=leaving.id,
            claim="The user and Ana are both moving to Porto.",
            rests_on=(own.part, forward.part),
        ),
        leaving=leaving,
        parts=(own, forward),
    )
    reply = read_as(
        framing(
            framed("The user is moving to Porto in May.", own.handle),
            framed("Ana is moving to Porto.", forward.handle, subjects=("Ana",)),
        ),
        FramingReplyShape,
    )
    assert reply is not None
    result = framed_by_code(reply, view, now=AT, mint=Minter(), labels=LABELS)

    mine, anas = (one.memory for one in result.memories)
    (on_note,) = (stamped_support(one, leaving) for one in mine.supports)
    (on_forward,) = (stamped_support(one, leaving) for one in anas.supports)
    assert on_note.points_at == InputPart(episode=leaving.id, message=0)
    assert (on_note.origin, on_note.holder) == (SupportOrigin.USER_MESSAGE, _OWNER)
    assert (on_forward.origin, on_forward.holder) == (
        SupportOrigin.OUTSIDE_INPUT,
        SupportHolder.source("77", claimed=True),
    )


async def test_no_part_of_a_marked_tasks_input_is_offered_as_a_support() -> None:
    """§3:6, §7:3: its parties include the assistant's statement; its round's message is."""
    harness = Harness()
    await harness.hold(
        episode(
            "step",
            channel=_SCHEDULE,
            parties=(_STATEMENT, SupportHolder.unknown()),
            text="Check whether the listing I read is still up.",
            rounds=(said("r1", "It is still listed.", at=AT + timedelta(seconds=5)),),
        )
    )

    _, reading = await _read(harness, "step")

    (part,) = reading.leaving.parts
    assert part.part == RoundMessagePart(episode=address("step"), round="r1")
    assert not any(isinstance(one.part, InputPart) for one in reading.leaving.parts)
