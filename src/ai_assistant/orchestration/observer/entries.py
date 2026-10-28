"""What the observer gives the diagnostic record, and nothing it reads back (ADR-0333 §2-§4).

Where ``Settings.diagnostic_record`` is on, the observer writes, as the source
``observer``, what each of its model calls was given and returned, the scout's findings and
declines as recorded, each finding's outcome with what its framing and placements decided,
every ``unclear`` among them included (ADR-0346 §6:5), and how each attempt ended (§2:1's
table). The composition root hands it its ``DiagnosticSink``, as ``None``
where the setting is false, and then nothing here builds an entry (§2:7).

**Under the leaving episode's activation, never bound** (§2:8, §2:10). The observer is a
background stage and no activation's run (ADR-0329 §7:4), so it binds nothing through
:func:`~ai_assistant.core.diagnostics.diagnosed_activation`: every entry names, as its
activation, the activation of the episode's processing record, and is stamped from the
observer's own clock. An episode with no processing record has no activation, and nothing
is written for it. A call reading several due episodes writes its given and returned
entries under each of their activations (§2:9). The store puts each in the activation's
second file, so the activation's own file still ages from its run (§3:1).

**Every body names the episode and its attempt** (§2:3): ``episode`` is the leaving
episode's id and ``attempt_started_at`` the instant its attempt started, and ``stage``
says which entry it is: ``scout``, ``framing`` or ``placement`` for a call's given and
returned entries,
and ``findings``, ``outcome`` or ``end`` for the three step entries. A call's given entry
also names, as ``prompt``, the template its system message was rendered from (ADR-0334
§8:2).

**Subordinate to the work** (§2:11, §4:2). A failure to build or write an entry is logged
as ADR-0314 §2:4 logs one, naming the activation, the source and the failure's class and
never the content, and it never fails, retries, holds or changes an attempt or an outcome.
A cancellation reaching a write is re-raised (ADR-0314 §2:5). Nothing here reads an entry,
the observer's own included (§4:1).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import structlog

from ai_assistant.core.diagnostics import DIAGNOSTIC_NOT_WRITTEN, failure_body
from ai_assistant.core.types import (
    DiagnosticEntry,
    DiagnosticKind,
    DiagnosticSource,
    fault_class_of,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence
    from datetime import datetime

    from ai_assistant.core.prompts import RenderedPrompt
    from ai_assistant.core.protocols import DiagnosticSink
    from ai_assistant.core.types import (
        CandidateDecline,
        EpisodicMemory,
        FindingOutcome,
        Message,
        ObservationAttemptEnd,
        ObservationFinding,
        ObservationState,
        ObserverStep,
        StructuredReply,
    )

__all__ = ["Diagnosed", "ObserverEntries"]

_log = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class Diagnosed:
    """Where one attempt's entries go, and what every body names (§2:3, §2:8).

    Attributes:
        activation_id: The activation of the episode's processing record.
        episode: The leaving episode's id.
        started_at: When the attempt started.
    """

    activation_id: str
    episode: str
    started_at: datetime

    @classmethod
    def of(cls, episode: EpisodicMemory, started_at: datetime) -> Diagnosed | None:
        """Where an attempt at ``episode`` writes, or ``None`` where it has no activation.

        Args:
            episode: The leaving episode, as read.
            started_at: When the attempt started.

        Returns:
            ``None`` for an episode with no processing record (§2:8).
        """
        processing = episode.processing_record
        if processing is None:
            return None
        return cls(
            activation_id=processing.activation_id, episode=episode.id, started_at=started_at
        )

    def named(self) -> dict[str, object]:
        """The two fields every body carries (§2:3)."""
        return {"episode": self.episode, "attempt_started_at": self.started_at.isoformat()}


class ObserverEntries:
    """The observer's write seam onto the diagnostic record (ADR-0333 §2).

    Holds the sink, or ``None`` where the record is off, and the observer's clock. Every
    method returns once its entries are written or dropped, and raises nothing but a
    cancellation.
    """

    def __init__(self, sink: DiagnosticSink | None, *, now: Callable[[], datetime]) -> None:
        """Hold the sink and the clock.

        Args:
            sink: The record's write seam, or ``None`` where ``diagnostic_record`` is
                false (§2:7).
            now: The observer's own clock, which stamps every entry (§2:10).
        """
        self._sink = sink
        self._now = now

    async def given(  # noqa: PLR0913 — the targets, the step, the request and three keys
        self,
        targets: Sequence[Diagnosed],
        step: ObserverStep,
        messages: Sequence[Message],
        *,
        prompt: RenderedPrompt,
        finding: ObservationFinding | None = None,
        reply_shape: Mapping[str, str] | None = None,
    ) -> None:
        """A call's given entry, under each activation its episodes name (§2:2, §2:9).

        Args:
            targets: The attempts the call reads for, one per episode it reads.
            step: The step making it.
            messages: Its rendered request.
            prompt: Its system message's instruction, whose template and flags the
                entry names (ADR-0334 §8:2, ADR-0335 §9:1).
            finding: The finding a framing or a placement call decides.
            reply_shape: The name and version of the shape a structured call asks for
                (ADR-0354 §7:1).
        """

        def body() -> dict[str, object]:
            built: dict[str, object] = {
                "stage": step.value,
                "messages": [one.model_dump(mode="json") for one in messages],
                "prompt": prompt.provenance(),
            }
            if reply_shape is not None:
                built["reply_shape"] = dict(reply_shape)
            if finding is not None:
                built["finding"] = _finding(finding)
            return built

        await self._each(targets, DiagnosticKind.GIVEN, body)

    async def returned(  # noqa: PLR0913 — the targets, the step and what came back
        self,
        targets: Sequence[Diagnosed],
        step: ObserverStep,
        *,
        reply: str | None = None,
        failure: BaseException | None = None,
        finding: str | None = None,
        structured: StructuredReply[Any] | None = None,
    ) -> None:
        """A call's returned entry: the reply as text, or the failure (§2:2).

        A structured call's entry keeps its reply as the model wrote it and what came back
        with it: the model that answered, the mode, the finish reason, a refusal's
        statement and category, the usage, and the returned failure's kind where there
        is one (ADR-0354 §7:2).

        Args:
            targets: The attempts the call read for.
            step: The step that made it.
            reply: The model's reply, where it returned.
            failure: How it failed, where it did.
            finding: The id of the finding a framing or a placement call decided.
            structured: What a structured call returned, where it returned.
        """

        def body() -> dict[str, object]:
            built: dict[str, object] = {"stage": step.value}
            if finding is not None:
                built["finding"] = finding
            if failure is not None:
                built["failure"] = failure_body(failure)
            elif structured is not None:
                built.update(_exchange_of(structured))
            else:
                built["reply"] = reply
            return built

        await self._each(targets, DiagnosticKind.RETURNED, body)

    async def findings(
        self,
        target: Diagnosed | None,
        findings: Sequence[ObservationFinding],
        dropped: int,
        *,
        declines: Sequence[CandidateDecline] = (),
    ) -> None:
        """The scout's findings and declines as recorded, and how many it dropped (§2:4).

        Args:
            target: The attempt, or ``None`` where it has no activation.
            findings: The findings the scout's reply kept, as recorded.
            dropped: How many of its proposals code dropped.
            declines: The candidates it declined, with their reasons (ADR-0346 §4:6).
        """
        await self._each(
            _one(target),
            DiagnosticKind.STEP,
            lambda: {
                "stage": "findings",
                "findings": [_finding(one) for one in findings],
                "dropped": dropped,
                "declines": [one.model_dump(mode="json") for one in declines],
            },
        )

    async def outcome(
        self,
        target: Diagnosed | None,
        finding: ObservationFinding,
        outcome: FindingOutcome,
        *,
        decided: Mapping[str, object] | None = None,
    ) -> None:
        """A finding's outcome, with what its framing and placements decided (§2:5).

        Args:
            target: The attempt, or ``None`` where it has no activation.
            finding: The finding.
            outcome: Its outcome, as the observation record gives it, every ``unclear``
                its placements named among it (ADR-0346 §6:5).
            decided: What its framing and placements decided, after code's checks,
                where a framing call decided it; ``None`` where a check failed before
                any call.
        """
        await self._each(
            _one(target),
            DiagnosticKind.STEP,
            lambda: {
                "stage": "outcome",
                "finding": finding.id,
                "claim": finding.claim,
                "outcome": outcome.model_dump(mode="json"),
                "decided": None if decided is None else dict(decided),
            },
        )

    async def ended(
        self,
        target: Diagnosed | None,
        end: ObservationAttemptEnd,
        state: ObservationState,
        *,
        failure: Mapping[str, object] | None = None,
        skipped: bool = False,
    ) -> None:
        """How an attempt ended and the state it left the episode in (§2:6).

        Args:
            target: The attempt, or ``None`` where it has no activation.
            end: Finished, failed or held.
            state: The state the episode was left in.
            failure: A failure's class and message.
            skipped: Whether the episode was skipped by rule, the one entry it is given.
        """

        def body() -> dict[str, object]:
            built: dict[str, object] = {"stage": "end", "end": end.value, "state": state.value}
            if failure is not None:
                built["failure"] = dict(failure)
            if skipped:
                built["skipped"] = "nothing_to_read"
            return built

        await self._each(_one(target), DiagnosticKind.STEP, body)

    async def _each(
        self,
        targets: Sequence[Diagnosed],
        kind: DiagnosticKind,
        body: Callable[[], Mapping[str, object]],
    ) -> None:
        """Write one entry under each target, building nothing where there is no sink."""
        sink = self._sink
        if sink is None:
            return
        for target in targets:
            try:
                entry = DiagnosticEntry.model_validate(
                    {
                        "activation_id": target.activation_id,
                        "source": DiagnosticSource.OBSERVER,
                        "kind": kind,
                        "recorded_at": self._now(),
                        "body": {**target.named(), **body()},
                    }
                )
            except Exception as exc:  # the instrument is subordinate to the work (§2:11)
                _dropped(target.activation_id, exc)
                continue
            try:
                await sink.write(entry)
            except Exception as exc:  # a sink breaking its contract costs only the entry
                _dropped(target.activation_id, exc)


def _one(target: Diagnosed | None) -> tuple[Diagnosed, ...]:
    return () if target is None else (target,)


def _dropped(activation_id: str, error: Exception) -> None:
    """ADR-0314 §2:4's line: the activation, the source and the class, never content (§4:2)."""
    _log.warning(
        DIAGNOSTIC_NOT_WRITTEN,
        activation_id=activation_id,
        source=DiagnosticSource.OBSERVER.value,
        error_class=fault_class_of(error),
    )


def _finding(finding: ObservationFinding) -> dict[str, object]:
    """A finding as the scout proposed it: its id, claim, parts, annotations and source."""
    return {
        "id": finding.id,
        "claim": finding.claim,
        "rests_on": [one.model_dump(mode="json") for one in finding.rests_on],
        "candidate": finding.candidate,
        "further_candidates": list(finding.further_candidates),
        "annotations": None
        if finding.annotations is None
        else finding.annotations.model_dump(mode="json"),
    }


def _exchange_of(reply: StructuredReply[Any]) -> dict[str, object]:
    """What a structured call's returned entry keeps of it (ADR-0354 §7:2).

    The provider's summary of its thinking is kept under ``thinking`` where the exchange
    holds one, and no such key is written where it holds none (ADR-0355 §5:1).
    """
    exchange = reply.exchange
    held: dict[str, object] = {
        "reply": exchange.reply,
        "model": exchange.model,
        "mode": exchange.mode.value,
        "finish_reason": exchange.finish_reason,
        "refusal": exchange.refusal,
        "refusal_category": exchange.refusal_category,
        "usage": exchange.usage.model_dump(mode="json"),
    }
    if exchange.thinking is not None:
        held["thinking"] = exchange.thinking
    if reply.failure is not None:
        held["failure"] = reply.failure.value
    return held
