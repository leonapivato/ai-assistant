"""Per-call channel admission and result projections (ADR-0274 §§3-8)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ai_assistant.core.types import (
    ChannelIdentity,
    ChannelResult,
    NewConversation,
    SpokenChannelResult,
    SpokenTurn,
    TextChannelResult,
    TurnOutcome,
)

if TYPE_CHECKING:
    from ai_assistant.core.types import ChannelContext, Modality


@dataclass(frozen=True)
class ResolvedChannelInput:
    """Validated per-call source data, separate from stored conversation history."""

    channel: ChannelIdentity
    text: str
    modality: Modality
    context: ChannelContext


@dataclass(frozen=True)
class ChannelProjection:
    """The trusted public entry point selects what counts against its limit."""

    method: str

    def text(self, outcome: TurnOutcome) -> TurnOutcome | ChannelResult:
        """Project a textual turn onto this call's declared result."""
        if self.method in {"receive", "receive_streaming"}:
            return text_result(outcome)
        return outcome

    def spoken(self, outcome: SpokenTurn) -> SpokenTurn | ChannelResult:
        """Project speech before measuring the audio degradation ladder."""
        if self.method == "receive":
            return spoken_result(outcome)
        return outcome


def text_result(outcome: TurnOutcome) -> ChannelResult:
    """Wrap a turn with the conversation the store resolved."""
    if outcome.conversation_id is None:
        msg = "a channel turn returned no conversation identifier"
        raise ValueError(msg)
    return ChannelResult(
        channel=ChannelIdentity(channel_type="conversation", instance_id=outcome.conversation_id),
        result=TextChannelResult(outcome=outcome),
    )


def spoken_result(outcome: SpokenTurn) -> ChannelResult:
    """Wrap speech; a recording with no words resolves no channel."""
    channel = None if outcome.outcome is None else text_result(outcome.outcome).channel
    return ChannelResult(channel=channel, result=SpokenChannelResult(outcome=outcome))


def conversation_target(conversation_id: str | None) -> ChannelIdentity | NewConversation:
    """Adapt the legacy optional ID without allocating anything."""
    if conversation_id is None:
        return NewConversation()
    return ChannelIdentity(channel_type="conversation", instance_id=conversation_id)
