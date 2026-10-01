"""M36 automatic reads keep inspection-only episodes outside model evidence."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from channel_episodes import channel_numbers, conversation_episode
from test_loop_reads import _belief, _bounded, _loop
from test_loop_structured import _Script, _structured

from ai_assistant.core.types import (
    ChannelContext,
    ChannelIdentity,
    EpisodeProcessingRecord,
    EpisodeResponseKind,
    EpisodicMemory,
    MemorySource,
    ProcessingReason,
    ProcessingStatus,
    Provenance,
    ReadAsk,
    ReadKind,
    RecordedChannelTrigger,
    RecordedTextInput,
    SemanticMemory,
    UnderstandingOmission,
)
from ai_assistant.orchestration import MemoryWriteStage, ObservationStage
from ai_assistant.orchestration.conversations import HISTORY_REPLAY_BOUND, ConversationLifecycle
from ai_assistant.orchestration.loop import ConversationalOperation
from ai_assistant.orchestration.reads import READ_BUDGET, _hop_records, _Reads
from ai_assistant.orchestration.retrieval import assemble_by_band
from ai_assistant.testing import (
    FakeConversationStore,
    FakeDeferralStore,
    FakeMemoryPolicy,
    FakeMemoryStore,
    FakeMemoryWriter,
    FakeObserver,
    FakeTranscriptArchiveWriter,
)
from ai_assistant.testing.activation import ended_pass

_AT = datetime(2026, 9, 18, tzinfo=UTC)


def _episode(identifier: str, *, eligible: bool) -> EpisodicMemory:
    channel = ChannelIdentity(channel_type="informational_event", instance_id="source")
    return EpisodicMemory(
        id=identifier,
        content="matching episode",
        occurred_at=_AT,
        provenance=Provenance(source=MemorySource.OBSERVED, confidence=0.9, last_updated=_AT),
        processing_record=EpisodeProcessingRecord(
            activation_id=identifier,
            started_at=_AT,
            ended_at=_AT,
            trigger=RecordedChannelTrigger(
                channel=channel,
                target=channel,
                payload=RecordedTextInput(text="raw event"),
                context=ChannelContext(),
                conversation=None,
                reply=None,
            ),
            status=ProcessingStatus.COMPLETED,
            reason=ProcessingReason.RETURNED,
            response_kind=EpisodeResponseKind.NONE,
            model_eligible=eligible,
            understanding_omitted=UnderstandingOmission.NOT_REACHED,
            stages=ended_pass(_AT),
        ),
    )


async def test_history_filters_eligibility_before_the_replay_bound() -> None:
    """ADR-0283 §4:1: the eligibility axis applies before the bound, so a run of
    inspection-only episodes never consumes the page that eligible ones need."""
    conversations = FakeConversationStore(now=lambda: _AT)
    memory = FakeMemoryStore(now=lambda: _AT)
    stage = ConversationLifecycle(
        conversations=conversations,
        memory=memory,
        archive=FakeTranscriptArchiveWriter(),
        archive_enabled=False,
        retention=None,
        now=lambda: _AT,
    )
    conversation = await conversations.start()
    eligible = [f"activation:eligible-{index}" for index in range(2)]
    for identifier in eligible:
        await memory.add(conversation_episode(conversation.id, identifier, occurred_at=_AT))
    for index in range(HISTORY_REPLAY_BOUND + 5):
        await memory.add(
            conversation_episode(
                conversation.id, f"activation:hidden-{index}", occurred_at=_AT, eligible=False
            )
        )

    assert [record.id for record in (await stage.history(conversation.id)).records] == eligible


async def test_ineligible_episodes_do_not_displace_retrieval_results() -> None:
    memory = FakeMemoryStore(now=lambda: _AT)
    for index in range(25):
        await memory.add(_episode(f"hidden-{index}", eligible=False))
    await memory.add(_episode("visible", eligible=True))

    records = await assemble_by_band(memory, "matching", limit=1)

    assert [record.id for record in records] == ["visible"]


async def _crowded_memory() -> FakeMemoryStore:
    memory = FakeMemoryStore(now=lambda: _AT)
    await memory.add(_belief("belief", "boiler"))
    for index in range(READ_BUDGET + 1):
        await memory.add(
            _episode(f"hidden-{index}", eligible=False).model_copy(
                update={"content": "boiler", "topics": ("boiler",)}
            )
        )
    await memory.add(
        _episode("visible", eligible=True).model_copy(
            update={"content": "boiler", "topics": ("boiler",)}
        )
    )
    return memory


async def test_episodic_supplement_filters_before_its_limit_and_model_supply() -> None:
    memory = await _crowded_memory()
    planner = _Script(None)
    loop = _loop(memory, planner=planner, episodic_limit=1, now=lambda: _AT)

    responded = await loop.respond(
        "boiler", narrow=_bounded(), operation=ConversationalOperation.CONVERSE
    )

    assert len(planner.calls) == 1
    assert [record.id for record in planner.calls[0][0]] == ["belief", "visible"]
    assert [record.id for record in responded.turn.memories] == ["belief", "visible"]


@pytest.mark.parametrize("query", [None, "boiler"])
async def test_structured_read_filters_before_its_limit_and_model_supply(
    query: str | None,
) -> None:
    memory = await _crowded_memory()
    planner = _Script(_structured(topics=("boiler",), query=query), None)
    loop = _loop(memory, planner=planner, now=lambda: _AT)

    responded = await loop.respond(
        "boiler", narrow=_bounded(), operation=ConversationalOperation.CONVERSE
    )

    assert len(planner.calls) == 2
    assert [record.id for record in planner.calls[0][0]] == ["belief"]
    assert [record.id for record in planner.calls[1][0]] == ["belief", "visible"]
    assert [record.id for record in responded.turn.memories] == ["belief", "visible"]


async def test_citation_hops_exclude_ineligible_evidence_and_named_records() -> None:
    memory = FakeMemoryStore(now=lambda: _AT)
    hidden = _episode("hidden", eligible=False)
    visible = _episode("visible", eligible=True)
    belief = SemanticMemory(
        id="belief",
        content="a supported fact",
        fact="a supported fact",
        provenance=Provenance(
            source=MemorySource.OBSERVED,
            confidence=0.9,
            last_updated=_AT,
            evidence=("hidden", "visible"),
        ),
    )
    for record in (hidden, visible, belief):
        await memory.add(record)

    reached = await _hop_records(
        memory,
        ReadAsk(kind=ReadKind.CITATION_HOP, labels=("M1",)),
        supply=(belief,),
        reads=_Reads(),
    )
    assert [record.id for record in reached.expansion] == ["belief", "visible"]
    assert [record.id for record in reached.evidence] == ["visible"]
    refused = await _hop_records(
        memory,
        ReadAsk(kind=ReadKind.CITATION_HOP, labels=("M1",)),
        supply=(hidden,),
        reads=_Reads(),
    )
    assert refused.expansion == ()
    assert refused.unresolved == 1


@pytest.mark.parametrize(
    "flags",
    [
        (False, False),
        (True, False, False),
        (False, True),
        (True,),
        (False,),
    ],
)
async def test_observation_skips_ineligible_episodes_without_stalling_the_watermark(
    flags: tuple[bool, ...],
) -> None:
    """ADR-0283 §11:1: ineligible episodes are skipped, and the pass advances to the
    page's highest number whatever it skipped, so nothing is read twice."""
    memory = FakeMemoryStore(now=lambda: _AT)
    conversations = FakeConversationStore(now=lambda: _AT)
    observer = FakeObserver()
    stage = ObservationStage(
        observer=observer,
        conversations=conversations,
        memory=memory,
        writes=MemoryWriteStage(
            writer=FakeMemoryWriter(store=memory, policy=FakeMemoryPolicy(), now=lambda: _AT),
            deferrals=FakeDeferralStore(now=lambda: _AT),
        ),
        batch_size=10,
        route="observer",
        now=lambda: _AT,
    )
    conversation = await conversations.start()
    identifiers = [f"activation:{index}" for index in range(len(flags))]
    for identifier, eligible in zip(identifiers, flags, strict=True):
        await memory.add(
            conversation_episode(conversation.id, identifier, occurred_at=_AT, eligible=eligible)
        )
    numbers = await channel_numbers(memory, conversation.id)

    await stage.observe(conversation.id)

    expected = [
        identifier for identifier, eligible in zip(identifiers, flags, strict=True) if eligible
    ]
    assert [record.id for batch in observer.batches for record in batch] == expected
    assert observer.call_count == int(bool(expected))
    stored = await conversations.get(conversation.id)
    assert stored is not None
    assert stored.observed_through == numbers[identifiers[-1]]
    await stage.observe(conversation.id)
    assert observer.call_count == int(bool(expected)), "nothing above the watermark is re-read"
