"""Per-call channel admission and result projections (ADR-0274 §§3-8)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ai_assistant.core.types import (
    ChannelIdentity,
    ChannelResult,
    EpisodeCaptureReport,
    NewConversation,
    SpokenChannelResult,
    SpokenTurn,
    TextChannelResult,
    TurnOutcome,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from ai_assistant.core.types import ChannelContext, Modality


UNCAPTURED = EpisodeCaptureReport(activation_id=None, episode_id=None, state="degraded")


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
    capture_report: Callable[[], EpisodeCaptureReport] | None = None

    def report(self) -> EpisodeCaptureReport:
        """Reserve this call's final receipt without guessing a stored ordinal."""
        return UNCAPTURED if self.capture_report is None else self.capture_report()

    def text(self, outcome: TurnOutcome) -> TurnOutcome | ChannelResult:
        """Project text, reserving the longer successful capture spelling."""
        if self.capture_report is not None:
            outcome = outcome.model_copy(update={"capture_degraded": False})
        if self.method in {"receive", "receive_streaming"}:
            return text_result(outcome, capture=self.report())
        return outcome

    def spoken(self, outcome: SpokenTurn) -> SpokenTurn | ChannelResult:
        """Measure speech with room for the index address its capture may obtain."""
        if self.capture_report is not None and outcome.outcome is not None:
            outcome = outcome.model_copy(
                update={
                    "outcome": outcome.outcome.model_copy(update={"capture_degraded": False}),
                    "episode_id": self.report().episode_id,
                }
            )
        if self.method == "receive":
            return spoken_result(outcome, capture=self.report())
        return outcome

    def terminal(self, result: ChannelResult) -> TurnOutcome | SpokenTurn | ChannelResult:
        """Measure the terminal value in the public entry point's result shape."""
        if isinstance(result.result, TextChannelResult):
            return self.text(result.result.outcome)
        if isinstance(result.result, SpokenChannelResult):
            return self.spoken(result.result.outcome)
        return result.model_copy(update={"capture": self.report()})


def text_result(
    outcome: TurnOutcome, *, capture: EpisodeCaptureReport = UNCAPTURED
) -> ChannelResult:
    """Wrap a turn with the conversation the store resolved."""
    if outcome.conversation_id is None:
        msg = "a channel turn returned no conversation identifier"
        raise ValueError(msg)
    return ChannelResult(
        channel=ChannelIdentity(channel_type="conversation", instance_id=outcome.conversation_id),
        result=TextChannelResult(outcome=outcome),
        capture=capture,
    )


def spoken_result(
    outcome: SpokenTurn, *, capture: EpisodeCaptureReport = UNCAPTURED
) -> ChannelResult:
    """Wrap speech; a recording with no words resolves no channel."""
    channel = None if outcome.outcome is None else text_result(outcome.outcome).channel
    return ChannelResult(
        channel=channel, result=SpokenChannelResult(outcome=outcome), capture=capture
    )


def captured_result(
    result: ChannelResult, report: EpisodeCaptureReport, *, index_episode_id: str | None
) -> ChannelResult:
    """Fold the final receipt into the channel and its existing legacy projection."""
    value = result.result
    if isinstance(value, TextChannelResult):
        value = value.model_copy(update={"outcome": _captured_outcome(value.outcome, report)})
    elif isinstance(value, SpokenChannelResult) and value.outcome.outcome is not None:
        spoken = value.outcome.model_copy(
            update={
                "outcome": _captured_outcome(value.outcome.outcome, report),
                "episode_id": index_episode_id,
            }
        )
        value = value.model_copy(update={"outcome": spoken})
    return result.model_copy(update={"result": value, "capture": report})


def _captured_outcome(outcome: TurnOutcome, report: EpisodeCaptureReport) -> TurnOutcome:
    return outcome.model_copy(
        update={"capture_degraded": outcome.capture_degraded or report.state != "recorded"}
    )


def conversation_target(conversation_id: str | None) -> ChannelIdentity | NewConversation:
    """Adapt the legacy optional ID without allocating anything."""
    if conversation_id is None:
        return NewConversation()
    return ChannelIdentity(channel_type="conversation", instance_id=conversation_id)
