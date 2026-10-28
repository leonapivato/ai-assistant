"""Shared material for the observer's suites (ADR-0329 §§7-17, ADR-0346).

Episodes built as activations record them, a clock a test moves, the canonical fakes
wired as the composition root would wire them, and scripted model routes: no test makes
a live model call or contacts a hub.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Final

from pydantic import BaseModel
from structured_support import structured

from ai_assistant.core.episode_encoding import episode_content
from ai_assistant.core.reply_shapes import read_reply
from ai_assistant.core.types import (
    ActionRequest,
    ActivationDigest,
    ActivationEffect,
    ChannelContext,
    ChannelIdentity,
    ConflictRelation,
    DigestOutcome,
    EpisodeProcessingRecord,
    EpisodicMemory,
    EvidenceItem,
    LabelBounds,
    MemoryDecisionKind,
    MemorySource,
    MemoryWrite,
    MemoryWriteMode,
    Placement,
    PlacementReach,
    PlacementSetter,
    PlanningLabel,
    PlanningRound,
    ProcessingReason,
    ProcessingStatus,
    ProposedCall,
    Provenance,
    QuestionPart,
    RecordedChannelTrigger,
    RecordedInputMessage,
    RecordedTextInput,
    ToolOutcome,
    UnderstandingOmission,
    WholeTextReply,
)
from ai_assistant.orchestration.authorizer import values_digest
from ai_assistant.orchestration.observer import Observer, ObserverLimits
from ai_assistant.orchestration.observer.prompts import (
    OBSERVER_FRAMING_PROMPT,
    OBSERVER_PLACEMENT_PROMPT,
    OBSERVER_SCOUT_PROMPT,
)
from ai_assistant.orchestration.remembering import REMEMBER_CANDIDATE
from ai_assistant.orchestration.understanding import RecentEpisodes
from ai_assistant.orchestration.writes import MemoryWriteStage
from ai_assistant.testing import (
    FakeEmbedder,
    FakeMemoryPolicy,
    FakeMemoryStore,
    FakeMemoryWriter,
    FakeModelProvider,
    FakePlanStore,
    FakeStoryStore,
    default_prompt,
)
from ai_assistant.testing.activation import ended_pass
from ai_assistant.testing.parties import OWNERS_WORDS, line_input

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from ai_assistant.core.protocols import DiagnosticSink, PersonModelStore, StructuredCompleter
    from ai_assistant.core.types import (
        ActivationRecall,
        ActivationUnderstanding,
        MemoryRecord,
        MemoryUpdateProposal,
        SupportHolder,
    )

#: The instant every case starts at: after §7:5's instant.
AT: Final = datetime(2026, 10, 18, 12, 0, tzinfo=UTC)

#: §7:5's instant.
SINCE: Final = datetime(2026, 10, 16, tzinfo=UTC)

CHAT: Final = ChannelIdentity(channel_type="conversation", instance_id="c-1")
EVENTS: Final = ChannelIdentity(channel_type="informational_event", instance_id="parks")

#: The window the cases' selector keeps (``UNDERSTANDING_EPISODE_LIMIT``'s role).
WINDOW: Final = 2

#: The bounds the cases' labels are written under (ADR-0345 §7:3).
LABELS: Final = LabelBounds(max_labels=3, max_chars=40, min_distance=0.05)


def address(activation_id: str) -> str:
    """The address of an activation's episode (ADR-0283 §2)."""
    return f"activation:{activation_id}"


def episode(  # noqa: PLR0913 — one knob per part of the record a case varies
    activation_id: str,
    *,
    at: datetime = AT,
    text: str = "I prefer window seats when I fly.",
    channel: ChannelIdentity = CHAT,
    messages: Sequence[RecordedInputMessage] = (),
    rounds: Sequence[PlanningRound] = (),
    labels: Sequence[PlanningLabel] = (),
    digests: Sequence[ActivationDigest] = (),
    understanding: tuple[ActivationUnderstanding, ...] = (),
    open_: bool = False,
    external: bool = False,
    recall: ActivationRecall | None = None,
    stories_position: int | None = None,
    parties: tuple[SupportHolder, ...] | None = None,
    ended: datetime | None = None,
) -> EpisodicMemory:
    """One activation's episode at its own address, frozen unless ``open_``.

    A frozen one ends at ``ended``, by default the instant it started.

    Its input's parties are its messages', as the line declares each (ADR-0351 §2:6),
    or, with none, ``parties`` where given and else the owner's.
    """
    frozen = not open_
    owner = Placement(reach=PlacementReach.OWNER, set_by=PlacementSetter.DERIVED)
    record = EpisodicMemory(
        id=address(activation_id),
        content="",
        placement=Placement() if frozen else owner,
        occurred_at=at,
        outcome="Noted." if frozen else None,
        provenance=Provenance(
            source=MemorySource.OBSERVED,
            confidence=0.9,
            last_updated=at,
            derived_from_external=external,
        ),
        processing_record=EpisodeProcessingRecord(
            activation_id=activation_id,
            started_at=at,
            ended_at=(ended or at) if frozen else None,
            trigger=RecordedChannelTrigger(
                target=channel,
                channel=channel,
                payload=RecordedTextInput(text=text),
                context=ChannelContext(),
                reply=WholeTextReply(),
                # ADR-0351 §2:6: an input of messages carries their parties, each as the
                # line declares it; one with none, the owner's unless named.
                parties=line_input(messages)[0]
                if messages
                else (OWNERS_WORDS if parties is None else parties),
                messages=line_input(messages)[1],
            ),
            status=ProcessingStatus.COMPLETED if frozen else None,
            reason=ProcessingReason.RETURNED if frozen else None,
            understanding=understanding,
            understanding_omitted=(
                None if understanding or not frozen else UnderstandingOmission.NOT_REACHED
            ),
            stages=ended_pass(ended or at) if frozen else (),
            rounds=tuple(rounds),
            labels=tuple(labels),
            digests=tuple(digests),
            recall=recall,
            stories_position=stories_position,
        ),
    )
    if not frozen:
        return record
    return record.model_copy(update={"content": episode_content(record)})


async def remembered(  # noqa: PLR0913 — the call, where it was recorded, and its record
    plans: FakePlanStore,
    activation_id: str,
    round_id: str,
    values: dict[str, Any],
    *,
    effect_id: str = "effect-1",
    part: QuestionPart | None = None,
) -> ActivationEffect:
    """Claim and finish the effect record that shows a ``remember`` call done (§3:3)."""
    filled = {**values, "episode": address(activation_id), "rests_on_outside_content": False}
    effect = ActivationEffect(
        id=effect_id,
        activation_id=activation_id,
        round=round_id,
        capability="remember",
        values_digest=values_digest(ActionRequest(tool=REMEMBER_CANDIDATE, parameters=filled)),
        decision_id=f"decision-{effect_id}",
        claimed_at=AT,
        part=part,
    )
    await plans.claim_activation_effect(effect, match=None)
    await plans.finish_activation_effect(effect_id, ToolOutcome.SUCCEEDED)
    return effect


def remember_call(call_id: str = "c1", **values: Any) -> ProposedCall:
    """A ``remember`` call as a round records it, recording a candidate."""
    return ProposedCall(call_id=call_id, name="remember", arguments=values)


def said(
    round_id: str, text: str, *, at: datetime = AT, calls: Sequence[ProposedCall] = ()
) -> PlanningRound:
    """A planning round that wrote ``text``."""
    return PlanningRound(id=round_id, recorded_at=at, text=text, calls=tuple(calls))


def digest(*items: str, at: datetime = AT, question: str = "What does it say?") -> ActivationDigest:
    """A digest that answered with ``items``, resting on the result ``R1``."""
    return ActivationDigest(
        result="R1",
        question=question,
        outcome=DigestOutcome.ANSWERED,
        evidence=tuple(EvidenceItem(text=one, source="R1") for one in items),
        recorded_at=at,
    )


class Clock:
    """A clock a test moves."""

    def __init__(self, at: datetime = AT) -> None:
        self.at = at

    def __call__(self) -> datetime:
        return self.at

    def advance(self, by: timedelta) -> None:
        self.at += by


def limits(**overrides: Any) -> ObserverLimits:
    """The bounds the cases run under, any of them overridden."""
    fields: dict[str, Any] = {
        "since": SINCE,
        "relevance": 0.8,
        "retrieved": 5,
        "recent_supports": 3,
        "stale_retries": 2,
        "labels": LABELS,
        "retry_base": timedelta(minutes=1),
        "retry_cap": timedelta(hours=1),
        "stuck_after": 3,
        "per_run": 10,
        "daily_calls": 300,
    }
    fields.update(overrides)
    return ObserverLimits(**fields)


def reply(**fields: Any) -> str:
    """A model's reply: one JSON object."""
    return json.dumps(fields)


def found(  # noqa: PLR0913 — one keyword per annotation the scout gives (ADR-0346 §4:2)
    claim: str,
    *parts: str,
    candidates: Sequence[str] = (),
    subjects: Sequence[str] = ("the user",),
    involved: Sequence[str] = (),
    why: str = "It matters to the user.",
    situations: Sequence[str] = (),
    narrowing: dict[str, Any] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """One finding as the scout writes it, with its annotations (ADR-0346 §4:2)."""
    return {
        "claim": claim,
        "rests_on": list(parts),
        "candidates": list(candidates),
        "subjects": list(subjects),
        "involved": list(involved),
        "why": why,
        "situations": list(situations),
        "narrowing": narrowing,
        **extra,
    }


def scouted(*findings: dict[str, Any], declines: Sequence[dict[str, str]] = ()) -> str:
    """The scout's reply: its findings and declines (ADR-0346 §4:2, §4:6)."""
    return reply(findings=list(findings), declines=list(declines))


def framed(  # noqa: PLR0913 — one keyword per field framing gives a memory (ADR-0346 §5:2)
    wording: str,
    *parts: str,
    backs: bool = True,
    subjects: Sequence[str] | None = (),
    involved: Sequence[str] | None = (),
    labels: Sequence[str] = (),
    marks: Sequence[str] = (),
    valid_until: str | None = None,
    how_sure: str = "sure",
    **extra: Any,
) -> dict[str, Any]:
    """One memory as framing writes it, each part a ``for`` support (ADR-0346 §5:2)."""
    return {
        "wording": wording,
        "supports": [
            {"part": one, "direction": "for", "backs_as_worded": backs, "how_sure": how_sure}
            for one in parts
        ],
        "subjects": None if subjects is None else list(subjects),
        "involved": None if involved is None else list(involved),
        "labels": list(labels),
        "marks": list(marks),
        "valid_until": valid_until,
        **extra,
    }


def framing(*memories: dict[str, Any], nothing: str | None = None) -> str:
    """Framing's reply: its memories, or nothing with a reason (ADR-0346 §5:2, §5:6)."""
    return reply(memories=list(memories), nothing=nothing)


def placing(*relations: tuple[str, str, str], answers: dict[str, str] | None = None) -> str:
    """Placement's reply: one relation per memory shown, as ``(M, relation, note)``."""
    return reply(
        relations=[
            {"memory": memory, "relation": relation, "note": note}
            for memory, relation, note in relations
        ],
        answers=answers,
    )


class Minter:
    """Mints ``1``, ``2``, ... so ids are predictable."""

    def __init__(self) -> None:
        self.minted = 0

    def __call__(self) -> str:
        self.minted += 1
        return str(self.minted)


class Labelling:
    """A stub reconciler answering fixed ADR-0159 §1 relations, keyed by record id.

    What the writer holds about a stored memory decides what a deferral names
    (ADR-0336 §7), so an observer case about a question supplies the label a model
    would have.
    """

    def __init__(self, labels: Mapping[str, ConflictRelation]) -> None:
        self._labels = dict(labels)

    async def reconcile(
        self, proposal: MemoryUpdateProposal, conflicts: Sequence[MemoryRecord]
    ) -> Mapping[str, ConflictRelation]:
        """Answer with this stub's fixed labels."""
        return dict(self._labels)


@dataclass
class Harness:
    """The canonical fakes, wired as the composition root would wire them.

    ``labels`` are what the writer's reconciler answers, keyed by stored memory id;
    none by default, which is ADR-0336 §6's floor.
    """

    clock: Clock = field(default_factory=Clock)
    ruling: MemoryDecisionKind = MemoryDecisionKind.ACCEPT
    labels: Mapping[str, ConflictRelation] | None = None
    memory: FakeMemoryStore = field(init=False)
    plans: FakePlanStore = field(init=False)
    stories: FakeStoryStore = field(init=False)
    policy: FakeMemoryPolicy = field(init=False)
    writer: FakeMemoryWriter = field(init=False)
    writes: MemoryWriteStage = field(init=False)
    mint: Minter = field(default_factory=Minter)

    def __post_init__(self) -> None:
        self.memory = FakeMemoryStore(now=self.clock)
        self.plans = FakePlanStore(now=self.clock)
        self.stories = FakeStoryStore(now=self.clock)
        self.policy = FakeMemoryPolicy(self.ruling)
        self.writer = FakeMemoryWriter(
            store=self.memory,
            policy=self.policy,
            now=self.clock,
            reconciler=None if self.labels is None else Labelling(self.labels),
            label_bounds=LABELS,
            label_embedder=FakeEmbedder(),
        )
        self.writes = MemoryWriteStage(writer=self.writer)

    async def hold(self, *records: MemoryRecord) -> None:
        """Store ``records`` as they are."""
        await self.memory.write_atomic(
            [MemoryWrite(record=one, mode=MemoryWriteMode.INSERT_IF_ABSENT) for one in records]
        )

    def observer(
        self,
        *,
        scout: FakeModelProvider | StructuredCompleter | None = None,
        commit: FakeModelProvider | StructuredCompleter | None = None,
        window: int = WINDOW,
        diagnostics: DiagnosticSink | None = None,
        person_model: PersonModelStore | None = None,
        **bounds: Any,
    ) -> Observer:
        """The observer over these fakes, its routes scripted, writing to ``diagnostics``.

        ``person_model`` is the person-model store the root wires where the switch is on
        (ADR-0338 §9:8); none by default, as on every hub where it is off.
        """
        return Observer(
            scout=structured(scout or FakeModelProvider.scripted()),
            commit=structured(commit or FakeModelProvider.scripted()),
            memory=self.memory,
            writes=self.writes,
            plans=self.plans,
            stories=self.stories,
            episodes=RecentEpisodes(memory=self.memory, limit=window),
            limits=limits(**bounds),
            scout_prompt=default_prompt(OBSERVER_SCOUT_PROMPT),
            framing_prompt=default_prompt(OBSERVER_FRAMING_PROMPT),
            placement_prompt=default_prompt(OBSERVER_PLACEMENT_PROMPT),
            now=self.clock,
            mint=self.mint,
            diagnostics=diagnostics,
            person_model=person_model,
        )


def read_as[T: BaseModel](reply: str, shape: type[T]) -> T | None:
    """``reply`` read as ``shape`` by ``core``'s one rule, as the stage reads it (§3:4).

    ``None`` where the rule returns a failure: the reply is no proposal.
    """
    read = read_reply(shape, reply)
    return read if isinstance(read, shape) else None
