"""What a record of whose a thing is, as ``core`` types it (ADR-0381 §3:2, §3:3).

A thing is a connection or a source. A connection is spelled as a line spells one, the
system's own chat as one connection, and the schedule and the approvals as their one
places, which no line names; a source as its reader's declared identity. A record names
the owner's identity alone in this milestone, and when it was recorded.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Final

import pytest
from pydantic import ValidationError

from ai_assistant.core.channel_validation import APPROVALS, TASK_SCHEDULER
from ai_assistant.core.types import (
    ANYONE_GROUP_ID,
    APPROVALS_CONNECTION,
    OWN_CHAT_CONNECTION,
    OWNER_PERSON_ID,
    SCHEDULE_CONNECTION,
    ThingKey,
    ThingKind,
    ThingRecord,
    ThingRecording,
    ThingRecordingKind,
)

_AT: Final = datetime(2026, 11, 24, 9, 0, tzinfo=UTC)
_CALENDAR: Final = ThingKey(kind=ThingKind.SOURCE, identifier="calendar")


@pytest.mark.parametrize(
    "identifier",
    [
        OWN_CHAT_CONNECTION,
        "telegram:conn-bot/424242",
        "account:conn-mail",
        SCHEDULE_CONNECTION,
        APPROVALS_CONNECTION,
    ],
)
def test_a_connection_is_spelled_as_a_line_spells_one_or_as_a_built_in_place(
    identifier: str,
) -> None:
    key = ThingKey(kind=ThingKind.CONNECTION, identifier=identifier)

    assert key.identifier == identifier


def test_the_built_in_places_are_their_channel_types_one_places() -> None:
    """The two spellings name the channel types ``core.channel_validation`` declares."""
    assert SCHEDULE_CONNECTION.partition(":")[0] == TASK_SCHEDULER
    assert APPROVALS_CONNECTION.partition(":")[0] == APPROVALS


@pytest.mark.parametrize(
    "identifier",
    [
        "conversation:chat-1",
        f"{TASK_SCHEDULER}:other",
        f"{APPROVALS}:other",
        TASK_SCHEDULER,
        APPROVALS,
        f" {SCHEDULE_CONNECTION}",
        f"{APPROVALS_CONNECTION} ",
        "no-separator",
        "account:",
        ":conn-mail",
        " account:conn-mail",
        "account: conn-mail",
        "",
        "   ",
    ],
)
def test_a_connection_spelled_otherwise_is_refused(identifier: str) -> None:
    with pytest.raises(ValidationError):
        ThingKey(kind=ThingKind.CONNECTION, identifier=identifier)


@pytest.mark.parametrize("identifier", ["calendar", "calendar:" + "0" * 32, "conversation"])
def test_a_source_is_its_readers_declared_identity_held_verbatim(identifier: str) -> None:
    key = ThingKey(kind=ThingKind.SOURCE, identifier=identifier)

    assert key.identifier == identifier


@pytest.mark.parametrize("identifier", [" calendar", "calendar ", "", "  "])
def test_a_source_with_surrounding_whitespace_or_none_is_refused(identifier: str) -> None:
    with pytest.raises(ValidationError):
        ThingKey(kind=ThingKind.SOURCE, identifier=identifier)


def test_a_key_is_its_kind_and_its_identifier_together() -> None:
    connection = ThingKey(kind=ThingKind.CONNECTION, identifier=OWN_CHAT_CONNECTION)
    source = ThingKey(kind=ThingKind.SOURCE, identifier=OWN_CHAT_CONNECTION)

    assert connection != source
    assert len({connection, source}) == 2


def test_a_record_names_the_owner_and_when_it_was_recorded() -> None:
    record = ThingRecord(key=_CALENDAR, person=OWNER_PERSON_ID, recorded_at=_AT)

    assert (record.key, record.person, record.recorded_at) == (_CALENDAR, OWNER_PERSON_ID, _AT)


@pytest.mark.parametrize("person", [ANYONE_GROUP_ID, "person:someone-else", "", "  "])
def test_a_record_naming_anyone_but_the_owner_is_refused(person: str) -> None:
    """ADR-0381 §3:3: in this milestone, the owner's identity alone, anyone's included."""
    with pytest.raises(ValidationError):
        ThingRecord(key=_CALENDAR, person=person, recorded_at=_AT)


def test_a_record_refuses_a_naive_instant() -> None:
    with pytest.raises(ValidationError):
        ThingRecord(
            key=_CALENDAR,
            person=OWNER_PERSON_ID,
            recorded_at=datetime(2026, 11, 24, 9, 0),  # noqa: DTZ001  # the naive instant under test
        )


def test_the_types_are_frozen_and_refuse_extra_fields() -> None:
    record = ThingRecord(key=_CALENDAR, person=OWNER_PERSON_ID, recorded_at=_AT)

    with pytest.raises(ValidationError):
        record.person = "person:someone-else"
    with pytest.raises(ValidationError):
        ThingKey(kind=ThingKind.SOURCE, identifier="calendar", person=OWNER_PERSON_ID)  # type: ignore[call-arg]  # the extra field under test
    recording = ThingRecording(kind=ThingRecordingKind.ALREADY_RECORDED, record=record)
    assert recording.record == record


def test_the_kinds_are_closed() -> None:
    assert [one.value for one in ThingKind] == ["connection", "source"]
    assert [one.value for one in ThingRecordingKind] == ["recorded", "already_recorded"]
