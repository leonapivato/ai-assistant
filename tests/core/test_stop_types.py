"""The vocabulary a stop adds to the contract (ADR-0297 §4, §5, §6:1)."""

from __future__ import annotations

from ai_assistant.core.errors import (
    ActivationStoppedError,
    AssistantError,
    ClaimRefused,
    ClaimStopped,
)
from ai_assistant.core.types import (
    ENDING_CONTROLLER_RULES,
    ActivationEnding,
    ActivationStop,
    ControllerRule,
    ProcessingReason,
)


def test_a_stop_answers_one_of_exactly_three() -> None:
    """§5:2: closed, valued by lower-cased member name, added to and never renamed."""
    assert [member.value for member in ActivationStop] == [
        "stopped",
        "already_ended",
        "no_such_activation",
    ]
    for member in ActivationStop:
        assert member.value == member.name.lower()


def test_a_stops_end_entry_and_reason_are_named_and_end_a_pass() -> None:
    """§4: ``ControllerRule.STOPPED`` ends a pass; ``ProcessingReason.STOPPED`` names it."""
    assert ControllerRule.STOPPED.value == "stopped"
    assert ControllerRule.STOPPED in ENDING_CONTROLLER_RULES
    assert (
        len({ControllerRule.STOPPED, ControllerRule.INTERRUPTED, ControllerRule.HUB_STOPPED}) == 3
    )
    assert ProcessingReason.STOPPED.value == "stopped"
    assert ActivationEnding.STOPPED.value == "stopped"


def test_activation_stopped_error_is_an_assistant_error_carrying_only_a_message() -> None:
    """§4:9: a new ``AssistantError`` subclass with a message and no structured state."""
    error = ActivationStoppedError("stopped")
    assert isinstance(error, AssistantError)
    assert not isinstance(error, ClaimStopped)
    assert error.args == ("stopped",)
    assert not isinstance(ClaimStopped("x"), ClaimRefused)
