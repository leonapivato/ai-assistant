"""Shared material for the observer's suites (ADR-0329 §§7-17).

Episodes built as activations record them, a clock a test moves, the canonical fakes
wired as the composition root would wire them, and scripted model routes: no test makes
a live model call or contacts a hub.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Final

from ai_assistant.core.episode_encoding import episode_content
from ai_assistant.core.types import (
    ActionRequest,
    ActivationDigest,
    ActivationEffect,
    ChannelContext,
    ChannelIdentity,
    DigestOutcome,
    EpisodeProcessingRecord,
    EpisodicMemory,
    EvidenceItem,
    InputOrigin,
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
from ai_assistant.orchestration.remembering import REMEMBER_CANDIDATE
from ai_assistant.orchestration.understanding import RecentEpisodes
from ai_assistant.orchestration.writes import MemoryWriteStage
from ai_assistant.testing import (
    FakeMemoryPolicy,
    FakeMemoryStore,
    FakeMemoryWriter,
    FakeModelProvider,
    FakePlanStore,
    FakeStoryStore,
)
from ai_assistant.testing.activation import ended_pass

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.core.types import ActivationUnderstanding, MemoryRecord

#: The instant every case starts at: after §7:5's instant.
AT: Final = datetime(2026, 10, 18, 12, 0, tzinfo=UTC)

#: §7:5's instant.
SINCE: Final = datetime(2026, 10, 16, tzinfo=UTC)

CHAT: Final = ChannelIdentity(channel_type="conversation", instance_id="c-1")
EVENTS: Final = ChannelIdentity(channel_type="informational_event", instance_id="parks")

#: The window the cases' selector keeps (``UNDERSTANDING_EPISODE_LIMIT``'s role).
WINDOW: Final = 2


def address(activation_id: str) -> str:
    """The address of an activation's episode (ADR-0283 §2)."""
    return f"activation:{activation_id}"


def episode(  # noqa: PLR0913 — one knob per part of the record a case varies
    activation_id: str,
    *,
    at: datetime = AT,
    text: str = "I prefer window seats when I fly.",
    origin: InputOrigin = InputOrigin.USER,
    channel: ChannelIdentity = CHAT,
    messages: Sequence[RecordedInputMessage] = (),
    rounds: Sequence[PlanningRound] = (),
    labels: Sequence[PlanningLabel] = (),
    digests: Sequence[ActivationDigest] = (),
    understanding: tuple[ActivationUnderstanding, ...] = (),
    open_: bool = False,
    external: bool = False,
) -> EpisodicMemory:
    """One activation's episode at its own address, frozen unless ``open_``."""
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
            ended_at=at if frozen else None,
            trigger=RecordedChannelTrigger(
                target=channel,
                channel=channel,
                payload=RecordedTextInput(text=text),
                context=ChannelContext(),
                reply=WholeTextReply(),
                origin=origin,
                messages=tuple(messages),
            ),
            status=ProcessingStatus.COMPLETED if frozen else None,
            reason=ProcessingReason.RETURNED if frozen else None,
            understanding=understanding,
            understanding_omitted=(
                None if understanding or not frozen else UnderstandingOmission.NOT_REACHED
            ),
            stages=ended_pass(at) if frozen else (),
            rounds=tuple(rounds),
            labels=tuple(labels),
            digests=tuple(digests),
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
        "story_episodes": 3,
        "related": 5,
        "similar": 5,
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


class Minter:
    """Mints ``1``, ``2``, ... so ids are predictable."""

    def __init__(self) -> None:
        self.minted = 0

    def __call__(self) -> str:
        self.minted += 1
        return str(self.minted)


@dataclass
class Harness:
    """The canonical fakes, wired as the composition root would wire them."""

    clock: Clock = field(default_factory=Clock)
    ruling: MemoryDecisionKind = MemoryDecisionKind.ACCEPT
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
        self.writer = FakeMemoryWriter(store=self.memory, policy=self.policy, now=self.clock)
        self.writes = MemoryWriteStage(writer=self.writer)

    async def hold(self, *records: MemoryRecord) -> None:
        """Store ``records`` as they are."""
        await self.memory.write_atomic(
            [MemoryWrite(record=one, mode=MemoryWriteMode.INSERT_IF_ABSENT) for one in records]
        )

    def observer(
        self,
        *,
        scout: FakeModelProvider | None = None,
        commit: FakeModelProvider | None = None,
        window: int = WINDOW,
        **bounds: Any,
    ) -> Observer:
        """The observer over these fakes, its routes scripted."""
        return Observer(
            scout=scout or FakeModelProvider.scripted(),
            commit=commit or FakeModelProvider.scripted(),
            memory=self.memory,
            writes=self.writes,
            plans=self.plans,
            stories=self.stories,
            episodes=RecentEpisodes(memory=self.memory, limit=window),
            limits=limits(**bounds),
            now=self.clock,
            mint=self.mint,
        )
