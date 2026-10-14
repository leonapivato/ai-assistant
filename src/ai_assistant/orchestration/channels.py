"""Per-call channel admission and result projections (ADR-0274 §§3-8)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ai_assistant.core.types import (
    ChannelIdentity,
    ChannelResult,
    EpisodeCaptureReport,
    NewConversation,
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

    def terminal(self, result: ChannelResult) -> ChannelResult:
        """Measure the terminal value with this call's receipt reserved.

        The typed turn's bare-outcome projection left with ``converse`` (ADR-0313
        §4:6), so the one shape is the channel result itself.
        """
        return result.model_copy(update={"capture": self.report()})


def captured_result(result: ChannelResult, report: EpisodeCaptureReport) -> ChannelResult:
    """Fold the final receipt into the channel result."""
    return result.model_copy(update={"capture": report})


def conversation_target(conversation_id: str | None) -> ChannelIdentity | NewConversation:
    """Adapt the legacy optional ID without allocating anything."""
    if conversation_id is None:
        return NewConversation()
    return ChannelIdentity(channel_type="conversation", instance_id=conversation_id)
