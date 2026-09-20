"""M36 automatic reads keep inspection-only episodes outside model evidence."""

from datetime import UTC, datetime

import pytest

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
)
from ai_assistant.orchestration import MemoryWriteStage, ObservationStage
from ai_assistant.orchestration.conversations import ConversationLifecycle
from ai_assistant.orchestration.reads import _hop_records, _Reads
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
        ),
    )


async def test_history_filters_index_before_the_tail_limit_and_checks_the_envelope() -> None:
    conversations = FakeConversationStore(now=lambda: _AT, tail_limit=2)
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
    rows = []
    for eligible in (True, True, False, False, False):
        row = await conversations.append(conversation.id, occurred_at=_AT, model_eligible=eligible)
        rows.append(row)
        await memory.add(_episode(row.episode_id, eligible=eligible))

    assert [record.id for record in (await stage.history(conversation.id)).records] == [
        row.episode_id for row in rows[:2]
    ]
    # A mismatched eligible index must not resurrect an ineligible envelope.
    mismatch = await conversations.append(conversation.id, occurred_at=_AT)
    await memory.add(_episode(mismatch.episode_id, eligible=False))
    assert [record.id for record in (await stage.history(conversation.id)).records] == [
        rows[1].episode_id
    ]


async def test_ineligible_episodes_do_not_displace_retrieval_results() -> None:
    memory = FakeMemoryStore(now=lambda: _AT)
    for index in range(25):
        await memory.add(_episode(f"hidden-{index}", eligible=False))
    await memory.add(_episode("visible", eligible=True))

    records = await assemble_by_band(memory, "matching", limit=1)

    assert [record.id for record in records] == ["visible"]


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
        ((False, False), (False, False)),
        ((True, True), (False, False), (False, False)),
        ((False, False), (True, True)),
        ((False, True),),
        ((True, False),),
    ],
)
async def test_observation_skips_ineligible_rows_without_stalling_the_watermark(
    flags: tuple[tuple[bool, bool], ...],
) -> None:
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
    rows = []
    for index_flag, envelope_flag in flags:
        row = await conversations.append(
            conversation.id, occurred_at=_AT, model_eligible=index_flag
        )
        rows.append(row)
        await memory.add(_episode(row.episode_id, eligible=envelope_flag))

    await stage.observe(conversation.id)

    expected_rows = [row for row, pair in zip(rows, flags, strict=True) if all(pair)]
    expected = [row.episode_id for row in expected_rows]
    assert [record.id for batch in observer.batches for record in batch] == expected
    assert observer.call_count == int(bool(expected))
    stored = await conversations.get(conversation.id)
    assert stored is not None
    last_eligible = max((row.ordinal for row in expected_rows), default=len(rows))
    assert stored.observed_through == last_eligible
    if last_eligible < len(rows):
        await stage.observe(conversation.id)
        stored = await conversations.get(conversation.id)
        assert stored is not None
        assert stored.observed_through == len(rows)
        assert observer.call_count == 1
