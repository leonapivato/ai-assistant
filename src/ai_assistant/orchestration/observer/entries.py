"""What the observer gives the diagnostic record, and nothing it reads back (ADR-0333 §2-§4).

Where ``Settings.diagnostic_record`` is on, the observer writes, as the source
``observer``, what each of its model calls was given and returned, the scout's findings as
recorded, each finding's outcome with the words its commit decided, and how each attempt
ended (§2:1's table). The composition root hands it its ``DiagnosticSink``, as ``None``
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
says which entry it is: ``scout`` or ``commit`` for a call's given and returned entries,
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
from typing import TYPE_CHECKING

import structlog

from ai_assistant.core.diagnostics import DIAGNOSTIC_NOT_WRITTEN, failure_body
from ai_assistant.core.types import (
    DiagnosticEntry,
    DiagnosticKind,
    DiagnosticSource,
    fault_class_of,
)
from ai_assistant.orchestration.observer.commit import (
    AddSupports,
    Blocked,
    Create,
    RaiseQuestion,
    RecordUse,
    Unwritten,
)
from ai_assistant.orchestration.observer.writing import policy_ask_wording

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence
    from datetime import datetime

    from ai_assistant.core.prompts import RenderedPrompt
    from ai_assistant.core.protocols import DiagnosticSink
    from ai_assistant.core.types import (
        EpisodicMemory,
        FindingOutcome,
        MemorySupport,
        Message,
        ObservationAttemptEnd,
        ObservationFinding,
        ObservationState,
        ObserverStep,
    )
    from ai_assistant.orchestration.observer.commit import Checked, Resolve

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

    async def given(
        self,
        targets: Sequence[Diagnosed],
        step: ObserverStep,
        messages: Sequence[Message],
        *,
        prompt: RenderedPrompt,
        finding: ObservationFinding | None = None,
    ) -> None:
        """A call's given entry, under each activation its episodes name (§2:2, §2:9).

        Args:
            targets: The attempts the call reads for, one per episode it reads.
            step: The step making it.
            messages: Its rendered request.
            prompt: Its system message's instruction, whose template and flags the
                entry names (ADR-0334 §8:2, ADR-0335 §9:1).
            finding: The finding a commit call decides.
        """

        def body() -> dict[str, object]:
            built: dict[str, object] = {
                "stage": step.value,
                "messages": [one.model_dump(mode="json") for one in messages],
                "prompt": prompt.provenance(),
            }
            if finding is not None:
                built["finding"] = _finding(finding)
            return built

        await self._each(targets, DiagnosticKind.GIVEN, body)

    async def returned(
        self,
        targets: Sequence[Diagnosed],
        step: ObserverStep,
        *,
        reply: str | None = None,
        failure: BaseException | None = None,
        finding: str | None = None,
    ) -> None:
        """A call's returned entry: the reply as text, or the failure (§2:2).

        Args:
            targets: The attempts the call read for.
            step: The step that made it.
            reply: The model's reply, where it returned.
            failure: How it failed, where it did.
            finding: The id of the finding a commit call decided.
        """

        def body() -> dict[str, object]:
            built: dict[str, object] = {"stage": step.value}
            if finding is not None:
                built["finding"] = finding
            if failure is not None:
                built["failure"] = failure_body(failure)
            else:
                built["reply"] = reply
            return built

        await self._each(targets, DiagnosticKind.RETURNED, body)

    async def findings(
        self, target: Diagnosed | None, findings: Sequence[ObservationFinding], dropped: int
    ) -> None:
        """The scout's findings as recorded, and how many of its proposals were dropped (§2:4).

        Args:
            target: The attempt, or ``None`` where it has no activation.
            findings: The findings the scout's reply kept, as recorded.
            dropped: How many of its proposals code dropped.
        """
        await self._each(
            _one(target),
            DiagnosticKind.STEP,
            lambda: {
                "stage": "findings",
                "findings": [_finding(one) for one in findings],
                "dropped": dropped,
            },
        )

    async def outcome(
        self,
        target: Diagnosed | None,
        finding: ObservationFinding,
        outcome: FindingOutcome,
        *,
        decided: Checked | None = None,
        note: str | None = None,
    ) -> None:
        """A finding's outcome, with the words its commit decided (§2:5).

        Args:
            target: The attempt, or ``None`` where it has no activation.
            finding: The finding.
            outcome: Its outcome, as the observation record gives it.
            decided: The commit's decision after code's checks, where a commit call
                decided it; ``None`` where a check failed before any call.
            note: The commit step's own note on its decision.
        """
        await self._each(
            _one(target),
            DiagnosticKind.STEP,
            lambda: {
                "stage": "outcome",
                "finding": finding.id,
                "claim": finding.claim,
                "outcome": outcome.model_dump(mode="json"),
                "decided": None if decided is None else _decided(decided, note),
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
    """A finding as the scout proposed it: its id, claim, parts and where it came from."""
    return {
        "id": finding.id,
        "claim": finding.claim,
        "rests_on": [one.model_dump(mode="json") for one in finding.rests_on],
        "candidate": finding.candidate,
        "relied_on": finding.relied_on,
    }


def _support(support: MemorySupport) -> dict[str, object]:
    """A support as its commit decided it: its part, direction and note, and the rest."""
    return {
        "part": support.points_at.model_dump(mode="json"),
        "origin": support.origin.value,
        "direction": support.direction.value,
        "backs_as_worded": support.backs_as_worded,
        "how_sure": None if support.how_sure is None else support.how_sure.value,
        "about_when": None if support.about_when is None else support.about_when.isoformat(),
        "note": support.note,
    }


def _decided(checked: Checked, note: str | None) -> dict[str, object]:
    """The words a commit decided for what it would write (§2:5)."""
    decided = _primary(checked.primary)
    if checked.resolve is not None:
        decided["resolves"] = _resolve(checked.resolve)
    if note is not None:
        decided["note"] = note
    return decided


def _primary(
    primary: Create | AddSupports | RaiseQuestion | RecordUse | Unwritten | Blocked,
) -> dict[str, object]:
    match primary:
        case Create(memory=memory, retiring=retiring):
            return {
                "action": "create",
                "memory": memory.id,
                "wording": memory.content,
                "supports": [_support(one) for one in memory.supports],
                "retiring": None
                if retiring is None
                else {
                    "memory": retiring.memory.id,
                    "wording": retiring.memory.content,
                    "kind": retiring.kind.value,
                    "note": retiring.note,
                },
                # The question a ruling of ask_user would raise on each memory it names.
                "asks_if_the_policy_asks": policy_ask_wording(memory.content),
            }
        case AddSupports(target=target, supports=supports):
            return {
                "action": "add_supports",
                "memory": target.id,
                "wording": target.content,
                "supports": [_support(one) for one in supports],
            }
        case RaiseQuestion(target=target, kind=kind, asks=asks, support=support):
            return {
                "action": "raise_question",
                "memory": target.id,
                "wording": target.content,
                "question": kind.value,
                "asks": asks,
                "support": _support(support),
            }
        case RecordUse(memory=memory, entry=entry):
            return {
                "action": "record_use",
                "memory": memory.id,
                "wording": memory.content,
                "held_up": entry.held_up,
                "entry_note": entry.note,
            }
        case Unwritten(reason=reason):
            return {"action": "nothing", "reason": reason.value}
        case Blocked():
            return {"action": "blocked"}


def _resolve(resolve: Resolve) -> dict[str, object]:
    return {
        "memory": resolve.target.id,
        "question": resolve.question,
        "note": resolve.note,
        "support": _support(resolve.support),
    }
