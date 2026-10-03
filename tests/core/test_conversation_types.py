"""The conversation values ADR-0074 §9 adds to ``core/types.py``, as ADR-0285 leaves them.

What is asserted here is what the *types* guarantee on their own — frozen, every
instant timezone-aware, and an export that carries the conversations and nothing
else (ADR-0283 §4:3). Store behaviour belongs to the conformance suite, not here.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from ai_assistant.core.types import Conversation, ConversationExport, ParkedBinding

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


def test_an_export_carries_no_history() -> None:
    """ADR-0283 §4:3: a conversation's turns are its channel's episodes, exported there.

    The document has no member for them at all, so a producer cannot hand one in.
    """
    exported = ConversationExport(exported_at=_NOW, conversations=(_conversation(),))

    assert set(ConversationExport.model_fields) == {
        "schema_version",
        "exported_at",
        "conversations",
    }
    assert exported.schema_version == 5
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


def test_the_export_version_moves_because_the_conversation_lost_a_member() -> None:
    """ADR-0285 §4:4: the ``Conversation`` the document carries changed shape.

    That is exactly what the version exists to announce (ADR-0039 §10, ADR-0014 §5),
    so the document reads 5 where it read 4.
    """
    assert ConversationExport(exported_at=_NOW).schema_version == 5


@pytest.mark.parametrize("version", [1, 2, 3, 4, 6])
def test_the_export_refuses_a_version_that_is_not_the_shape_it_carries(version: int) -> None:
    """The export label describes the watermark-free ADR-0285 §4 shape exactly."""
    with pytest.raises(ValidationError):
        ConversationExport.model_validate({"schema_version": version, "exported_at": _NOW})
