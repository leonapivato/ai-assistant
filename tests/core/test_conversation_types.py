"""The four conversation values ADR-0074 §9 adds to ``core/types.py``.

What is asserted here is what the *types* guarantee on their own — frozen, every
instant timezone-aware, and an export that cannot describe an index it does not
carry. Store behaviour belongs to the conformance suite, not here.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from ai_assistant.core.types import (
    FIRST_TURN_ORDINAL,
    Conversation,
    ConversationExport,
    ConversationTurn,
    ParkedBinding,
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


def _turn(
    conversation_id: str = "c-1",
    ordinal: int = FIRST_TURN_ORDINAL,
    *,
    episode_id: str | None = None,
    parked: ParkedBinding | None = None,
) -> ConversationTurn:
    return ConversationTurn(
        conversation_id=conversation_id,
        ordinal=ordinal,
        episode_id=episode_id or f"conv:{conversation_id}:{ordinal}",
        occurred_at=_NOW,
        parked=parked,
    )


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


def test_a_turn_is_frozen_and_its_binding_is_one_value() -> None:
    """§9: the parked pair travels as a value, not as two swappable strings."""
    binding = ParkedBinding(execution_id="exec-1", step_id="step-1")
    turn = _turn(parked=binding)

    with pytest.raises(ValidationError):
        turn.ordinal = 5
    with pytest.raises(ValidationError):
        binding.step_id = "step-2"
    assert turn.parked == binding


@pytest.mark.parametrize("bad", [0, -1])
def test_a_turn_ordinal_below_the_first_is_refused(bad: int) -> None:
    """§9.2: ordinals are dense from ``FIRST_TURN_ORDINAL``, so nothing sits below it."""
    with pytest.raises(ValidationError):
        _turn(ordinal=bad)


@pytest.mark.parametrize(
    ("model", "field"),
    [
        (Conversation, "started_at"),
        (Conversation, "last_active_at"),
        (ConversationTurn, "occurred_at"),
    ],
)
def test_a_naive_instant_is_refused(model: type, field: str) -> None:
    """ADR-0023 §3: `core` cannot know a naive value's zone, so it never guesses."""
    naive = datetime(2026, 6, 1)  # noqa: DTZ001 — the point of the case
    fields: dict[str, object] = (
        {"id": "c-1", "started_at": _NOW, "last_active_at": _NOW}
        if model is Conversation
        else {
            "conversation_id": "c-1",
            "ordinal": 1,
            "episode_id": "conv:c-1:1",
            "occurred_at": _NOW,
        }
    )
    fields[field] = naive

    with pytest.raises(ValidationError):
        model.model_validate(fields)  # type: ignore[attr-defined]  # both are BaseModels


def test_a_blank_identifier_is_refused() -> None:
    """An empty id identifies nothing while satisfying "an id is present"."""
    with pytest.raises(ValidationError):
        _conversation("   ")
    with pytest.raises(ValidationError):
        ParkedBinding(execution_id="", step_id="step-1")


def test_an_export_resolves_every_turn_it_carries() -> None:
    """A turn whose conversation is missing is a fragment with nothing to place it in."""
    with pytest.raises(ValidationError, match="conversation is missing"):
        ConversationExport(
            exported_at=_NOW,
            conversations=(_conversation("c-1"),),
            turns=(_turn("c-2"),),
        )


def test_an_export_refuses_a_conversation_stamped_deleted() -> None:
    """§9: a stamped conversation is deleted as far as every read is concerned."""
    with pytest.raises(ValidationError, match="stamped deleted"):
        ConversationExport(
            exported_at=_NOW, conversations=(_conversation(deleted_at=_NOW),), turns=()
        )


@pytest.mark.parametrize(
    ("turns", "message"),
    [
        ((_turn(ordinal=1), _turn(ordinal=1)), "two turns at one position"),
        (
            (_turn(ordinal=1), _turn(ordinal=2, episode_id="conv:c-1:1")),
            "duplicate episode ids",
        ),
        (
            (
                _turn(ordinal=1, parked=ParkedBinding(execution_id="e", step_id="s")),
                _turn(ordinal=2, parked=ParkedBinding(execution_id="e", step_id="s")),
            ),
            "one parked binding",
        ),
    ],
    ids=["position", "episode", "binding"],
)
def test_an_export_refuses_an_ambiguous_index(
    turns: tuple[ConversationTurn, ...], message: str
) -> None:
    """The store's own uniqueness invariants, seen from outside the store."""
    with pytest.raises(ValidationError, match=message):
        ConversationExport(exported_at=_NOW, conversations=(_conversation(),), turns=turns)


def test_an_export_of_an_empty_conversation_is_well_formed() -> None:
    """A conversation with no turns is state the user holds, not a broken export."""
    exported = ConversationExport(exported_at=_NOW, conversations=(_conversation(),))

    assert exported.turns == ()
    assert exported.schema_version == 2


def test_a_fresh_conversation_has_no_observation_watermark() -> None:
    """ADR-0212 §4: ``None`` is the only spelling of "no pass has recorded one".

    Additive, so every ``Conversation`` a build before ADR-0212 could construct is
    still constructible and reads as a walk that has not started (§7).
    """
    assert _conversation().observed_through is None


@pytest.mark.parametrize("bad", [0, -1])
def test_a_watermark_below_the_first_turn_names_no_position(bad: int) -> None:
    """§8: bounded ``ge=FIRST_TURN_ORDINAL``, so 0 is not a sentinel for "none".

    A zero-valued watermark would be a second spelling of the absence §4 rules is
    spelled ``None`` — and one that reads as a *recorded* position, so a pass would
    walk forward from turn 1 where §4 says it reads the tail.
    """
    with pytest.raises(ValidationError):
        _conversation(observed_through=bad)


def test_the_watermark_is_carried_through_the_export() -> None:
    """§7: the member is on ``Conversation``, so the document ``export`` builds has it.

    Which is why ``schema_version`` moves: the shape of the portable document
    changed, and that is exactly what the version exists to announce (ADR-0039 §10,
    ADR-0014 §5).
    """
    exported = ConversationExport(
        exported_at=_NOW, conversations=(_conversation(observed_through=3),)
    )

    assert exported.conversations[0].observed_through == 3
    assert exported.schema_version == 2


def test_the_export_refuses_a_version_that_is_not_the_shape_it_carries() -> None:
    """Pinned rather than defaulted, so the label is a fact about the document.

    "An export outlives the code that wrote it … a reader must be able to tell which
    shape it is holding" (ADR-0014 §5), and a producer's unchecked claim is not that.
    A document labelled **1** separates itself from a 2 and does *not* separate the
    pre-``delivery`` shape from the post-``delivery`` one, which is issue #1793 and
    is why no reader may take a 1 as evidence of either.
    """
    with pytest.raises(ValidationError):
        ConversationExport.model_validate({"schema_version": 1, "exported_at": _NOW})
