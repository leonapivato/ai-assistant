"""Shared material for the suites that drive ADR-0300 §6's story links."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final, NoReturn

from ai_assistant.core.channel_validation import input_origin
from ai_assistant.core.episode_encoding import episode_content
from ai_assistant.core.errors import StoryStoreError
from ai_assistant.core.types import (
    ChannelContext,
    ChannelIdentity,
    EpisodeProcessingRecord,
    EpisodicMemory,
    MemorySource,
    MemoryWrite,
    MemoryWriteMode,
    Placement,
    PlacementReach,
    PlacementSetter,
    ProcessingReason,
    ProcessingStatus,
    Provenance,
    RecordedChannelTrigger,
    RecordedTextInput,
    StoryMember,
    StoryMemberKind,
    UnderstandingOmission,
    WholeTextReply,
)
from ai_assistant.testing import FakeMemoryStore, FakeStoryStore
from ai_assistant.testing.activation import ended_pass

if TYPE_CHECKING:
    from ai_assistant.core.types import ActivationUnderstanding, MemoryRecord

AT: Final = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
CONVERSATION: Final = ChannelIdentity(channel_type="conversation", instance_id="c-1")
EVENTS: Final = ChannelIdentity(channel_type="informational_event", instance_id="parks")

#: The reach that keeps a record for the owner alone (ADR-0217 §1).
OWNER_ONLY: Final = Placement(reach=PlacementReach.OWNER, set_by=PlacementSetter.DERIVED, set_at=AT)


def activation(activation_id: str) -> StoryMember:
    """An activation as a story member."""
    return StoryMember(kind=StoryMemberKind.ACTIVATION, id=activation_id)


def story(story_id: str) -> StoryMember:
    """A story as a story member."""
    return StoryMember(kind=StoryMemberKind.STORY, id=story_id)


def address(activation_id: str) -> str:
    """The address of an activation's episode (ADR-0283 §2)."""
    return f"activation:{activation_id}"


def episode(  # noqa: PLR0913 — one knob per field a case varies
    activation_id: str,
    *,
    at: datetime = AT,
    text: str = "Plan the camping trip to Riverside.",
    channel: ChannelIdentity = CONVERSATION,
    placement: Placement | None = None,
    understanding: tuple[ActivationUnderstanding, ...] = (),
    open_: bool = False,
) -> EpisodicMemory:
    """One activation's episode at its own address, frozen unless ``open_``.

    An open episode is placed for the owner alone, by derivation, as ADR-0286 places it.
    """
    event = channel.channel_type == "informational_event"
    frozen = not open_
    if placement is None:
        placement = Placement() if frozen else OWNER_ONLY
    record = EpisodicMemory(
        id=address(activation_id),
        content="",
        occurred_at=at,
        outcome="Riverside has space." if frozen else None,
        provenance=Provenance(source=MemorySource.OBSERVED, confidence=0.9, last_updated=at),
        placement=placement,
        processing_record=EpisodeProcessingRecord(
            activation_id=activation_id,
            started_at=at,
            ended_at=at if frozen else None,
            trigger=RecordedChannelTrigger(
                target=channel,
                channel=channel,
                payload=RecordedTextInput(text=text),
                context=ChannelContext(),
                reply=None if event else WholeTextReply(),
                origin=input_origin(channel),
            ),
            status=ProcessingStatus.COMPLETED if frozen else None,
            reason=ProcessingReason.RETURNED if frozen else None,
            understanding=understanding,
            understanding_omitted=(
                None if understanding or not frozen else UnderstandingOmission.NOT_REACHED
            ),
            stages=ended_pass(at) if frozen else (),
        ),
    )
    return record.model_copy(update={"content": episode_content(record)})


def failing(stories: FakeStoryStore, method: str) -> FakeStoryStore:
    """``stories``, its ``method`` raising ``StoryStoreError`` as an unreadable file would.

    The canonical fake arms no failure and is final, so the one method is replaced on
    the instance; every other call answers as the fake does.
    """

    async def fail(*_args: object, **_kwargs: object) -> NoReturn:
        msg = "the story store could not read or write its file"
        raise StoryStoreError(msg)

    setattr(stories, method, fail)
    return stories


async def memory_of(*records: MemoryRecord, now: datetime = AT) -> FakeMemoryStore:
    """A canonical fake memory store holding ``records``, its clock at ``now``."""
    memory = FakeMemoryStore(now=lambda: now)
    await memory.write_atomic(
        [MemoryWrite(record=record, mode=MemoryWriteMode.INSERT_IF_ABSENT) for record in records]
    )
    return memory
