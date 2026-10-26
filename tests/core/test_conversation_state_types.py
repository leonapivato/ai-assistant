"""ADR-0349 §10:3: a conversation's current state names every running activation.

``ConversationState.activation_id`` becomes ``activation_ids``: every running activation
started from the conversation whose id is known, each once, and empty unless the state
is working.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from ai_assistant.core.types import ActivationEnding, ConversationState


def test_the_idle_state_names_no_activation() -> None:
    assert ConversationState().activation_ids == ()
    assert "activation_id" not in ConversationState.model_fields


def test_a_working_state_names_every_running_activation_in_order() -> None:
    state = ConversationState(working=True, activation_ids=("a-1", "a-2"))
    assert state.activation_ids == ("a-1", "a-2")
    assert ConversationState.model_validate_json(state.model_dump_json()) == state


def test_working_with_no_known_id_names_none() -> None:
    """ADR-0297 §5: an activation whose id the factory failed to mint shows "working…"."""
    assert ConversationState(working=True).activation_ids == ()


def test_only_a_working_state_names_activations() -> None:
    with pytest.raises(ValidationError, match="only while working"):
        ConversationState(activation_ids=("a-1",), last_ended=ActivationEnding.DONE)


def test_each_activation_is_named_once() -> None:
    with pytest.raises(ValidationError, match="each running activation once"):
        ConversationState(working=True, activation_ids=("a-1", "a-1"))


@pytest.mark.parametrize("held", [None, "a-1"])
def test_the_old_single_id_is_not_read(held: object) -> None:
    """ADR-0349 §10:5: the shape the wire carries moved, so ``PROTOCOL_VERSION`` did."""
    with pytest.raises(ValidationError):
        ConversationState.model_validate({"working": True, "activation_id": held})
    with pytest.raises(ValidationError):
        ConversationState.model_validate({"working": True, "activation_ids": held})


def test_a_blank_id_is_refused() -> None:
    with pytest.raises(ValidationError):
        ConversationState(working=True, activation_ids=("   ",))
