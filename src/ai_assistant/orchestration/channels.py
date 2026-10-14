"""Per-call channel admission and result projections (ADR-0274 §§3-8)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ai_assistant.core.types import (
    ChannelIdentity,
    ChannelResult,
    EpisodeCaptureReport,
    NewConversation,
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
        """Reserve this call's final receipt at the address fixed at admission (ADR-0283 §2)."""
        return UNCAPTURED if self.capture_report is None else self.capture_report()

    def text(self, outcome: TurnOutcome) -> TurnOutcome:
        """Project text, reserving the longer successful capture spelling.

        A typed turn's public result is the bare outcome: ``converse`` is the one entry
        that runs one, ``receive`` refusing the text conversational combination
        (ADR-0293 §11).
        """
        if self.capture_report is not None:
            outcome = outcome.model_copy(update={"capture_degraded": False})
        return outcome

    def terminal(self, result: ChannelResult) -> TurnOutcome | ChannelResult:
        """Measure the terminal value in the public entry point's result shape."""
        if isinstance(result.result, TextChannelResult):
            return self.text(result.result.outcome)
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


def captured_result(result: ChannelResult, report: EpisodeCaptureReport) -> ChannelResult:
    """Fold the final receipt into the channel and its existing legacy projection."""
    value = result.result
    if isinstance(value, TextChannelResult):
        value = value.model_copy(update={"outcome": _captured_outcome(value.outcome, report)})
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
