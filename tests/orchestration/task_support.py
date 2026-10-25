"""Writing scheduled tasks and their activations' records, for the Task Scheduler's suites.

A case about the sensor, the Task Manager or the restart's settlement needs tasks the
plan store holds, pushed to activations whose effect records and episodes say what they
did. These helpers write them through the plan store's own members, as a spawn and a
push write them (ADR-0350 §3:3, §7:5), so every case holds the store to its contract.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Final

from ai_assistant.core.types import (
    OWNER_PERSON_ID,
    ActivationEffect,
    ChannelIdentity,
    DueNow,
    EpisodicMemory,
    ProcessingReason,
    ProcessingStatus,
    ScheduledTaskAuthor,
    TaskSpawn,
    TaskWriteAnswer,
    ToolOutcome,
)
from ai_assistant.orchestration.task_manager import TaskManagerLimits, TaskSchedulerSeams
from ai_assistant.orchestration.task_scheduler import SCHEDULE, SPAWN_CAPABILITY

if TYPE_CHECKING:
    from ai_assistant.core.protocols import PlanStore
    from ai_assistant.core.types import ScheduledTask, TaskWhen

#: The instant every case runs at unless it moves its clock: the engine harness's own.
AT: Final = datetime(2026, 1, 1, tzinfo=UTC)

#: A conversation of the hub's chat, as a place.
CHAT: Final = ChannelIdentity(channel_type="conversation", instance_id="c-1")

#: The line's chat, as a place.
LINE: Final = ChannelIdentity(channel_type="telegram", instance_id="line-ref/42")

#: Generous bounds, which a case about a limit narrows.
LIMITS: Final = TaskManagerLimits(chain_limit=10, pending_limit=50, listing_bound=20)


def seams(**changes: object) -> TaskSchedulerSeams:
    """The Task Scheduler's settings for a case: a short recheck, so a case never waits."""
    held: dict[str, object] = {
        "limits": LIMITS,
        "recheck": timedelta(milliseconds=20),
        "lateness_grace": timedelta(minutes=2),
        "push_limit": 3,
        "zone": "UTC",
        "persons": (OWNER_PERSON_ID,),
    }
    held.update(changes)
    return TaskSchedulerSeams(**held)  # type: ignore[arg-type]  # each knob is the field's own


def activation() -> str:
    """A fresh activation id, canonical UUID4 text."""
    return str(uuid.uuid4())


def spawn_effect(parent: str, *, at: datetime = AT) -> ActivationEffect:
    """The effect record a spawn made by ``parent`` is claimed under (ADR-0350 §3:3)."""
    return ActivationEffect(
        id=f"effect:{uuid.uuid4().hex}",
        activation_id=parent,
        round="round:1",
        capability=SPAWN_CAPABILITY,
        values_digest=hashlib.sha256(uuid.uuid4().bytes).hexdigest(),
        decision_id=f"decision:{uuid.uuid4().hex}",
        claimed_at=at,
    )


async def write_task(  # noqa: PLR0913 — the store, the parent, and one knob per part a case varies
    plans: PlanStore,
    parent: str,
    *,
    when: TaskWhen | None = None,
    places: tuple[ChannelIdentity, ...] = (),
    instruction: str = "check the listings",
    set_in: ChannelIdentity = CHAT,
    replaces: str | None = None,
    chain_limit: int = 10,
    pending_limit: int = 50,
    at: datetime = AT,
) -> ScheduledTask:
    """Write a task ``parent`` spawned, through the store's own step, and return it."""
    written = await plans.write_scheduled_task(
        TaskSpawn(
            id=f"task:{uuid.uuid4().hex}",
            person=OWNER_PERSON_ID,
            author=ScheduledTaskAuthor.PERSON,
            when=DueNow() if when is None else when,
            places=places,
            instruction=instruction,
            set_in=set_in,
            set_at=at,
            replaces=replaces,
        ),
        spawn_effect(parent, at=at),
        match=None,
        replace_any=True,
        chain_limit=chain_limit,
        pending_limit=pending_limit,
    )
    assert written.answer is TaskWriteAnswer.WRITTEN, written
    assert written.task is not None
    return written.task


async def pushed(plans: PlanStore, task: ScheduledTask) -> str:
    """Push ``task``'s first occurrence to a fresh activation, and return the activation."""
    one = activation()
    await plans.mark_occurrence_pushed(task.id, 1, one)
    return one


async def message(
    plans: PlanStore,
    activation_id: str,
    place: ChannelIdentity,
    *,
    outcome: ToolOutcome | None = None,
    position: int | None = None,
) -> ActivationEffect:
    """A message ``activation_id`` claimed into ``place``, finished with ``outcome``."""
    effect = ActivationEffect(
        id=f"effect:{uuid.uuid4().hex}",
        activation_id=activation_id,
        round="round:1",
        place=f"{place.channel_type}:{place.instance_id}",
        claimed_at=AT,
    )
    await plans.claim_activation_effect(effect, match=None)
    if outcome is not None:
        await plans.finish_activation_effect(effect.id, outcome, position=position)
    (held,) = [
        one for one in await plans.activation_effects([activation_id]) if one.id == effect.id
    ]
    return held


def schedule_episode(
    activation_id: str,
    *,
    status: ProcessingStatus = ProcessingStatus.COMPLETED,
    reason: ProcessingReason = ProcessingReason.RETURNED,
) -> EpisodicMemory:
    """The frozen episode of an activation the Task Scheduler started, as it ended."""
    from channel_episodes import conversation_episode  # noqa: PLC0415 — a sibling helper

    base = conversation_episode("c-1", f"activation:{activation_id}")
    record = base.processing_record
    assert record is not None
    trigger = record.trigger.model_copy(update={"target": SCHEDULE, "channel": SCHEDULE})
    return base.model_copy(
        update={
            "processing_record": record.model_copy(
                update={"trigger": trigger, "status": status, "reason": reason}
            )
        }
    )
