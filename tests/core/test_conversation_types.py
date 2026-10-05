"""The conversation values ADR-0074 §9 adds to ``core/types.py``, with ADR-0293's chat space.

What is asserted here is what the *types* guarantee on their own — frozen, every
instant timezone-aware, a message shaped as its author's (ADR-0293 §5:2), and an
export that carries the conversations and their transcripts and no episode
(ADR-0283 §4:3, ADR-0293 §5:3). Store behaviour belongs to the conformance suite.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from ai_assistant.core.types import (
    CHAT_SNAPSHOT_ENTRIES,
    MESSAGE_OPTIONS_MAX,
    TRANSCRIPT_MESSAGE_MAX_CHARS,
    ChatChange,
    ChatChanges,
    ChatDevice,
    ChatStreamChunk,
    ChatStreamEnd,
    Conversation,
    ConversationDeletedChange,
    ConversationExport,
    ConversationStartedChange,
    ConversationState,
    CurrentState,
    DeletedMessage,
    DeviceAccess,
    DeviceChange,
    DeviceChanges,
    DeviceRole,
    DevicesChangedChange,
    MessageAddedChange,
    MessageAuthor,
    MessageReceipt,
    NewMessage,
    ParkedBinding,
    SendOutcome,
    TranscriptMessage,
    TranscriptPage,
    checked_chat_devices,
)

_NOW = datetime(2026, 6, 1, tzinfo=UTC)
_LATER = _NOW + timedelta(hours=1)


def _conversation(conversation_id: str = "c-1", **overrides: object) -> Conversation:
    fields: dict[str, object] = {
        "id": conversation_id,
        "started_at": _NOW,
        "last_active_at": _NOW,
    }
    fields.update(overrides)
    return Conversation.model_validate(fields)


def test_a_fresh_conversation_has_no_turn_stamp_and_no_tombstone() -> None:
    """§2: both are unset until something sets them, and both are optional."""
    conversation = _conversation()

    assert conversation.last_turn_at is None
    assert conversation.deleted_at is None
    assert conversation.last_active_at == conversation.started_at


@pytest.mark.parametrize(
    "field", ["id", "started_at", "last_active_at", "last_turn_at", "deleted_at"]
)
def test_a_conversation_is_frozen(field: str) -> None:
    """ADR-0068: the shared record graph does not get mutated out from under a reader."""
    conversation = _conversation(last_turn_at=_NOW, deleted_at=_NOW)

    with pytest.raises(ValidationError):
        setattr(conversation, field, _LATER)


@pytest.mark.parametrize("field", ["started_at", "last_active_at"])
def test_a_naive_instant_is_refused(field: str) -> None:
    """ADR-0023 §3: `core` cannot know a naive value's zone, so it never guesses."""
    naive = datetime(2026, 6, 1)  # noqa: DTZ001 — the point of the case

    fields: dict[str, object] = {"id": "c-1", "started_at": _NOW, "last_active_at": _NOW}
    fields[field] = naive

    with pytest.raises(ValidationError):
        Conversation.model_validate(fields)


def test_a_blank_identifier_is_refused() -> None:
    """An empty id identifies nothing while satisfying "an id is present"."""
    with pytest.raises(ValidationError):
        _conversation("   ")
    with pytest.raises(ValidationError):
        ParkedBinding(execution_id="", step_id="step-1")


def test_an_export_refuses_a_conversation_stamped_deleted() -> None:
    """§9: a stamped conversation is deleted as far as every read is concerned."""
    with pytest.raises(ValidationError, match="stamped deleted"):
        ConversationExport(exported_at=_NOW, conversations=(_conversation(deleted_at=_NOW),))


def test_an_export_refuses_a_conversation_carried_twice() -> None:
    """One conversation addressable twice is an ambiguous snapshot, not a larger one."""
    with pytest.raises(ValidationError, match="duplicate conversation ids"):
        ConversationExport(
            exported_at=_NOW, conversations=(_conversation("c-1"), _conversation("c-1"))
        )


def test_an_export_carries_no_episode() -> None:
    """ADR-0283 §4:3: a conversation's turns are its channel's episodes, exported there.

    The document has no member for them at all, so a producer cannot hand one in. What
    it gains is the transcript (ADR-0293 §5:3), which is the hosted medium's content
    and not an episode.
    """
    exported = ConversationExport(exported_at=_NOW, conversations=(_conversation(),))

    assert set(ConversationExport.model_fields) == {
        "schema_version",
        "exported_at",
        "conversations",
        "messages",
    }
    assert exported.schema_version == 6
    with pytest.raises(ValidationError):
        ConversationExport.model_validate({"exported_at": _NOW, "turns": ()})


def test_a_conversation_carries_no_observation_watermark() -> None:
    """ADR-0285 §4: the member ADR-0212 §1 added is removed, not left unset.

    ``extra="forbid"`` makes the removal a refusal: a producer still handing the
    member in is told so rather than having it dropped silently.
    """
    assert "observed_through" not in Conversation.model_fields
    with pytest.raises(ValidationError):
        _conversation(observed_through=3)


def test_the_export_version_moves_because_the_document_gained_the_transcripts() -> None:
    """ADR-0293 §5:3: the document carries the transcripts it did not.

    That is exactly what the version exists to announce (ADR-0039 §10, ADR-0014 §5),
    so the document reads 6 where it read 5 (and 5 where ADR-0285 §4:4 moved it from 4).
    """
    assert ConversationExport(exported_at=_NOW).schema_version == 6


@pytest.mark.parametrize("version", [1, 2, 3, 4, 5, 7])
def test_the_export_refuses_a_version_that_is_not_the_shape_it_carries(version: int) -> None:
    """The export label describes the transcript-carrying ADR-0293 §5 shape exactly."""
    with pytest.raises(ValidationError):
        ConversationExport.model_validate({"schema_version": version, "exported_at": _NOW})


# --- the chat space (ADR-0293) --------------------------------------------------


def _message(position: int = 1, **overrides: object) -> TranscriptMessage:
    fields: dict[str, object] = {
        "conversation_id": "c-1",
        "position": position,
        "written_at": _NOW,
        "author": MessageAuthor.ASSISTANT,
        "text": "hello",
    }
    fields.update(overrides)
    return TranscriptMessage.model_validate(fields)


@pytest.mark.parametrize(
    "fields",
    [
        {"author": "user", "text": "hi"},
        {"author": "user", "text": "hi", "device_id": "phone"},
        {"author": "user", "text": "hi", "device_id": "phone", "message_id": "m", "cut_off": True},
        {"author": "assistant", "text": "hi", "device_id": "phone"},
        {"author": "assistant", "text": "hi", "message_id": "m"},
        {"author": "assistant", "text": " "},
        {"author": "assistant", "text": "x" * (TRANSCRIPT_MESSAGE_MAX_CHARS + 1)},
        {"author": "assistant", "text": "?", "options": ("yes", "yes")},
        {"author": "assistant", "text": "?", "options": tuple(str(i) for i in range(13))},
        {"author": "assistant", "text": "?", "options": ("x" * 201,)},
        {"author": "assistant", "text": "hi", "replies_to": 0},
        {"author": "assistant", "text": "hi", "cut_off": 1},
    ],
)
def test_a_new_message_is_shaped_as_its_authors(fields: dict[str, object]) -> None:
    """§5:2's table: the device and id are the user's and required; cut off the assistant's.

    And §4:7's bound, on the type: a message over it cannot be constructed.
    """
    with pytest.raises(ValidationError):
        NewMessage.model_validate(fields)


def test_a_message_within_every_bound_is_constructed() -> None:
    """The bounds admit what they name, so a refusal above is the bound and not the shape."""
    question = NewMessage(
        author=MessageAuthor.ASSISTANT,
        text="x" * TRANSCRIPT_MESSAGE_MAX_CHARS,
        options=tuple(str(index) for index in range(MESSAGE_OPTIONS_MAX)),
    )
    said = NewMessage(author=MessageAuthor.USER, text="hi", device_id="phone", message_id="m")

    assert len(question.options) == MESSAGE_OPTIONS_MAX
    assert said.cut_off is False


def test_a_recorded_message_replies_only_to_an_earlier_one() -> None:
    """§4:5: a reply names an *earlier* message."""
    assert _message(position=3, replies_to=2).replies_to == 2
    with pytest.raises(ValidationError):
        _message(position=3, replies_to=3)


def test_a_receipt_carries_a_position_exactly_where_the_message_is_recorded() -> None:
    """§4:4: *received* is the position; its absence says the message is not there."""
    assert MessageReceipt(conversation_id="c", outcome=SendOutcome.RECORDED, position=1)
    assert MessageReceipt(conversation_id="c", outcome=SendOutcome.NOT_AN_END)
    with pytest.raises(ValidationError):
        MessageReceipt(conversation_id="c", outcome=SendOutcome.REPEATED)
    with pytest.raises(ValidationError):
        MessageReceipt(conversation_id="c", outcome=SendOutcome.NO_SUCH_REPLY, position=1)


def test_a_transcript_page_is_one_conversation_in_ascending_order() -> None:
    """A page and its markers are one conversation's, by position."""
    marker = DeletedMessage(conversation_id="c-1", position=2)
    assert TranscriptPage(conversation_id="c-1", entries=(_message(1), marker), as_of=0)
    with pytest.raises(ValidationError):
        TranscriptPage(conversation_id="c-1", entries=(marker, _message(1)), as_of=0)
    with pytest.raises(ValidationError):
        TranscriptPage(conversation_id="c-2", entries=(_message(1),), as_of=0)


def test_changes_are_in_sequence_and_round_trip_by_kind() -> None:
    """§5:10: a page is ascending; each change decodes back to its own kind."""
    page = ChatChanges(
        changes=(
            MessageAddedChange(seq=1, message=_message(1)),
            DevicesChangedChange(
                seq=2, devices=(ChatDevice(device_id="p", access=DeviceAccess.READ),)
            ),
            ConversationDeletedChange(seq=4, conversation_id="c-1"),
        ),
        next_after=9,
    )

    assert ChatChanges.model_validate_json(page.model_dump_json()) == page
    assert [one.conversation_id for one in page.changes] == ["c-1", None, "c-1"]
    with pytest.raises(ValidationError):
        ChatChanges(changes=page.changes[::-1], next_after=9)
    with pytest.raises(ValidationError):
        ChatChanges(changes=page.changes, next_after=3)


_READER = ChatDevice(device_id="phone", access=DeviceAccess.READ)


def _snapshot(seq: int, conversation_id: str = "c-1", count: int = 1) -> TranscriptPage:
    return TranscriptPage(
        conversation_id=conversation_id,
        entries=tuple(
            _message(index + 1, conversation_id=conversation_id) for index in range(count)
        ),
        as_of=seq,
    )


def test_a_snapshot_travels_only_with_the_change_setting_its_conversation() -> None:
    """ADR-0298 §7:6-§7:7: with a set change of that conversation, as of that change."""
    added = DevicesChangedChange(seq=5, conversation_id="c-1", devices=(_READER,))
    started = ConversationStartedChange(seq=2, conversation_id="c-1", devices=(_READER,))

    assert DeviceChange(change=added, snapshot=_snapshot(5)).seq == 5
    assert DeviceChange(change=started, snapshot=_snapshot(2, count=0)).conversation_id == "c-1"
    refused: list[tuple[ChatChange, TranscriptPage]] = [
        (MessageAddedChange(seq=5, message=_message(1)), _snapshot(5)),
        (DevicesChangedChange(seq=5, devices=(_READER,)), _snapshot(5)),
        (added, _snapshot(4)),
        (added, _snapshot(5, conversation_id="c-2")),
        (added, _snapshot(5, count=CHAT_SNAPSHOT_ENTRIES + 1)),
    ]
    for change, snapshot in refused:
        with pytest.raises(ValidationError):
            DeviceChange(change=change, snapshot=snapshot)


def test_a_devices_changes_are_in_sequence_and_drop_their_snapshots_as_chat_changes() -> None:
    """``DeviceChanges`` is ``ChatChanges`` for one device, snapshots beside."""
    added = DevicesChangedChange(seq=5, conversation_id="c-1", devices=(_READER,))
    later = MessageAddedChange(seq=7, message=_message(2))
    page = DeviceChanges(
        changes=(DeviceChange(change=added, snapshot=_snapshot(5)), DeviceChange(change=later)),
        next_after=9,
    )

    assert DeviceChanges.model_validate_json(page.model_dump_json()) == page
    assert page.without_snapshots() == ChatChanges(changes=(added, later), next_after=9)
    with pytest.raises(ValidationError):
        DeviceChanges(changes=page.changes[::-1], next_after=9)
    with pytest.raises(ValidationError):
        DeviceChanges(changes=page.changes, next_after=6)


def test_a_change_stream_chunk_holds_exactly_one_thing() -> None:
    """ADR-0298 §7:3: a change, a current state, roles or a heartbeat, one of them."""
    change = DeviceChange(change=ConversationDeletedChange(seq=3, conversation_id="c-1"))
    state = CurrentState(conversation_id="c-1", state=ConversationState(working=True))
    chunks = [
        ChatStreamChunk(change=change),
        ChatStreamChunk(state=state),
        ChatStreamChunk(roles=(DeviceRole.COMMANDS, DeviceRole.SPOKES)),
        ChatStreamChunk(roles=()),
        ChatStreamChunk(heartbeat=True),
    ]
    for chunk in chunks:
        assert ChatStreamChunk.model_validate_json(chunk.model_dump_json()) == chunk
    for fields in (
        {},
        {"heartbeat": False},
        {"change": change, "heartbeat": True},
        {"state": state, "roles": ()},
        {"roles": (DeviceRole.SPOKES, DeviceRole.COMMANDS)},
        {"roles": (DeviceRole.COMMANDS, DeviceRole.COMMANDS)},
    ):
        with pytest.raises(ValidationError):
            ChatStreamChunk.model_validate(fields)
    assert ChatStreamEnd(next_after=0).next_after == 0
    with pytest.raises(ValidationError):
        ChatStreamEnd(next_after=-1)


def test_a_device_access_says_what_it_lets_a_device_do() -> None:
    """§3:5: writing, reading, or both."""
    assert [(one.writes, one.reads) for one in DeviceAccess] == [
        (False, True),
        (True, False),
        (True, True),
    ]


def test_a_set_of_devices_is_checked_and_put_in_one_order() -> None:
    """One order, no device twice, nothing that is not a device, a bounded size."""
    phone = ChatDevice(device_id="phone", access=DeviceAccess.READ_WRITE)
    watch = ChatDevice(device_id="watch", access=DeviceAccess.READ)

    assert checked_chat_devices([watch, phone]) == (phone, watch)
    for bad in (
        [phone, phone.model_copy(update={"access": DeviceAccess.READ})],
        "phone",
        ["phone"],
        [ChatDevice(device_id=f"d-{index}", access=DeviceAccess.READ) for index in range(65)],
    ):
        with pytest.raises(ValueError, match="devices"):
            checked_chat_devices(bad)


def test_an_export_carries_only_its_own_conversations_messages_once_each() -> None:
    """§5:3: a message's conversation is in the document, and no message is there twice."""
    with pytest.raises(ValidationError):
        ConversationExport(exported_at=_NOW, conversations=(), messages=(_message(1),))
    with pytest.raises(ValidationError):
        ConversationExport(
            exported_at=_NOW,
            conversations=(_conversation(),),
            messages=(_message(1), _message(1, text="again")),
        )
