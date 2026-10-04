"""Every read reads every episode, failed and outside ones included (ADR-0284 §6:2).

These tests once pinned ADR-0283 §4's eligibility filter. ADR-0284 §6 retires the
flag and the axis: history, retrieval, both episodic reads and the citation hop read
every episode their reads return. (The observer was a further reader until ADR-0285
§1 retired it.) Each test seeds failed episodes — the passes the retired flag marked
ineligible — beside completed ones, and asserts they are read.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from channel_episodes import conversation_episode
from test_loop_reads import _belief, _bounded, _loop
from test_loop_structured import _Script, _structured

from ai_assistant.core.types import (
    ChannelContext,
    ChannelIdentity,
    EpisodeProcessingRecord,
    EpisodicMemory,
    InputOrigin,
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
from ai_assistant.orchestration.conversations import HISTORY_REPLAY_BOUND, ConversationLifecycle
from ai_assistant.orchestration.loop import ConversationalOperation
from ai_assistant.orchestration.reads import READ_BUDGET, _hop_records, _Reads
from ai_assistant.orchestration.retrieval import assemble_by_band
from ai_assistant.testing import (
    FakeConversationStore,
    FakeMemoryStore,
)
from ai_assistant.testing.activation import ended_pass

_AT = datetime(2026, 9, 18, tzinfo=UTC)


def _episode(identifier: str, *, completed: bool) -> EpisodicMemory:
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
                reply=None,
                origin=InputOrigin.OUTSIDE,
            ),
            status=ProcessingStatus.COMPLETED if completed else ProcessingStatus.FAILED,
            reason=ProcessingReason.RETURNED if completed else ProcessingReason.PROCESSING_FAILED,
            understanding_omitted=UnderstandingOmission.NOT_REACHED,
            stages=ended_pass(_AT),
        ),
    )


async def test_history_reads_failed_episodes_up_to_the_replay_bound() -> None:
    """ADR-0284 §6:2: history is the channel's latest episodes, whatever their status."""
    conversations = FakeConversationStore(now=lambda: _AT)
    memory = FakeMemoryStore(now=lambda: _AT)
    stage = ConversationLifecycle(
        conversations=conversations,
        memory=memory,
        retention=None,
        now=lambda: _AT,
    )
    conversation = await conversations.start()
    completed = [f"activation:completed-{index}" for index in range(2)]
    for identifier in completed:
        await memory.add(conversation_episode(conversation.id, identifier, occurred_at=_AT))
    for index in range(HISTORY_REPLAY_BOUND + 5):
        await memory.add(
            conversation_episode(
                conversation.id, f"activation:failed-{index}", occurred_at=_AT, completed=False
            )
        )

    failed = [f"activation:failed-{index}" for index in range(HISTORY_REPLAY_BOUND + 5)]
    assert [record.id for record in (await stage.history(conversation.id)).records] == (
        completed + failed
    )[-HISTORY_REPLAY_BOUND:]


async def test_retrieval_reads_failed_episodes() -> None:
    memory = FakeMemoryStore(now=lambda: _AT)
    for index in range(25):
        await memory.add(_episode(f"hidden-{index}", completed=False))
    await memory.add(_episode("visible", completed=True))

    records = await assemble_by_band(memory, "matching", limit=30)

    assert {record.id for record in records} == {
        "visible",
        *(f"hidden-{index}" for index in range(25)),
    }


async def _crowded_memory() -> FakeMemoryStore:
    memory = FakeMemoryStore(now=lambda: _AT)
    await memory.add(_belief("belief", "boiler"))
    for index in range(READ_BUDGET + 1):
        await memory.add(
            _episode(f"hidden-{index}", completed=False).model_copy(
                update={"content": "boiler", "topics": ("boiler",)}
            )
        )
    await memory.add(
        _episode("visible", completed=True).model_copy(
            update={"content": "boiler", "topics": ("boiler",)}
        )
    )
    return memory


async def test_episodic_supplement_reads_failed_episodes() -> None:
    memory = await _crowded_memory()
    planner = _Script(None)
    loop = _loop(memory, planner=planner, episodic_limit=READ_BUDGET + 2, now=lambda: _AT)

    responded = await loop.respond(
        "boiler", narrow=_bounded(), operation=ConversationalOperation.CONVERSE
    )

    assert len(planner.calls) == 1
    supplied = {record.id for record in planner.calls[0][0]}
    assert {"belief", "visible", "hidden-0"} <= supplied
    assert {"belief", "visible", "hidden-0"} <= {record.id for record in responded.turn.memories}


@pytest.mark.parametrize("query", [None, "boiler"])
async def test_structured_read_reads_failed_episodes(
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
    read = [record.id for record in planner.calls[1][0]]
    assert read[0] == "belief"
    assert any(identifier.startswith("hidden-") for identifier in read), (
        "a failed episode is read like any other"
    )
    assert [record.id for record in responded.turn.memories] == read


async def test_citation_hops_reach_failed_evidence_and_named_records() -> None:
    memory = FakeMemoryStore(now=lambda: _AT)
    hidden = _episode("hidden", completed=False)
    visible = _episode("visible", completed=True)
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
    assert [record.id for record in reached.expansion] == ["belief", "hidden", "visible"]
    assert [record.id for record in reached.evidence] == ["hidden", "visible"]
    named = await _hop_records(
        memory,
        ReadAsk(kind=ReadKind.CITATION_HOP, labels=("M1",)),
        supply=(hidden,),
        reads=_Reads(),
    )
    assert [record.id for record in named.expansion] == ["hidden"]
    assert named.unresolved == 0
