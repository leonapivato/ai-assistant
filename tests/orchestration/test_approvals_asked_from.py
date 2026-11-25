"""Where an approval's request was asked, as code reads it (ADR-0382 §2:2, §4).

:func:`~ai_assistant.orchestration.approvals.asked_from` reads the places an input of the
asking activation came from, its trigger's and each joined input's, from its running
state or its episode alike, and keeps each whose kind takes a message.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final

import pytest

from ai_assistant.core.types import (
    ChannelIdentity,
    ChannelInput,
    JoinedInput,
    RecordedInputMessage,
    TextChannelPayload,
)
from ai_assistant.orchestration.activation_state import admit_channel
from ai_assistant.orchestration.approvals import THE_APPROVALS, AskedFrom, asked_from
from ai_assistant.orchestration.task_scheduler import SCHEDULE

if TYPE_CHECKING:
    from ai_assistant.core.types import RecordedChannelTrigger

_AT: Final = datetime(2026, 11, 25, 9, 0, tzinfo=UTC)
_CHAT: Final = ChannelIdentity(channel_type="conversation", instance_id="c-1")
_OTHER_CHAT: Final = ChannelIdentity(channel_type="conversation", instance_id="c-2")
_LINE: Final = ChannelIdentity(channel_type="telegram", instance_id="line")
_EVENT: Final = ChannelIdentity(channel_type="informational_event", instance_id="thermostat-1")


def _admitted(target: ChannelIdentity) -> RecordedChannelTrigger:
    return admit_channel(
        ChannelInput(target=target, payload=TextChannelPayload(text="book the table")),
        None,
        clock=lambda: _AT,
        id_factory=lambda: "7d0f3c0e-3c4a-4c39-9a52-6f0a1d2b3c4d",
    ).trigger


def _joined(channel: ChannelIdentity, *, taken_from: str | None = None) -> JoinedInput:
    return JoinedInput(
        joined_at=_AT,
        channel=channel,
        messages=(RecordedInputMessage(text="and for four", sent_at=_AT),),
        taken_over_from=taken_from,
    )


def test_the_triggers_place_and_each_joined_inputs_each_once_in_order() -> None:
    """§2:1, §4:1: its trigger's, then each that joined by an absorption or a take, all
    alike, each once."""
    trigger = _admitted(_CHAT)
    joined = (
        _joined(_LINE, taken_from="act-newer"),
        _joined(_OTHER_CHAT),
        _joined(_CHAT),
    )

    assert asked_from(trigger, joined) == AskedFrom(
        places=("conversation:c-1", "telegram:line", "conversation:c-2")
    )


@pytest.mark.parametrize(
    "where", [SCHEDULE, THE_APPROVALS, _EVENT], ids=["the schedule", "the approvals", "an event"]
)
def test_a_place_whose_kind_takes_no_message_keeps_nothing(where: ChannelIdentity) -> None:
    """§4:2, §4:3: the schedule, the approvals and an event's place take no message, so a
    task's work, among others, holds no place its request was asked from; one that took a
    message's place by a take still holds that."""
    trigger = _admitted(where)

    assert asked_from(trigger, ()) == AskedFrom()
    assert asked_from(trigger, (_joined(_CHAT),)) == AskedFrom(places=("conversation:c-1",))


def test_no_trigger_read_and_nothing_joined_holds_no_place() -> None:
    assert asked_from(None, ()) == AskedFrom()


def test_an_asking_activation_that_could_not_be_read_holds_no_place() -> None:
    """§4:4: read or not, never both a place and unread."""
    assert AskedFrom(read=False).places == ()
    with pytest.raises(ValueError, match="could not be read"):
        AskedFrom(places=("conversation:c-1",), read=False)
