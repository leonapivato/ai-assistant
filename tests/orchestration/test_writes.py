"""The write stage: an ``ASK_USER`` ruling writes nothing and is logged (ADR-0309 §5).

The deferred-question queue retired with the old path, so the stage parks nothing
and reports what the writer ruled. What it adds is one structured event per
deferral, carrying the ruling's kind and the proposal's memory kind alone, and no
identifier and no content of the proposal (ADR-0319 §5, ADR-0004 §5).
"""

from __future__ import annotations

from datetime import UTC, datetime

import structlog.testing
from orchestration_held_episodes import held_episode

from ai_assistant.core.types import (
    Memory,
    MemoryChange,
    MemoryDecisionKind,
    MemoryOperation,
    MemoryOperationKind,
    MemoryUpdateProposal,
    MemoryWriterName,
    TrackRecordEntry,
)
from ai_assistant.orchestration.writes import DEFERRED_EVENT, MemoryWriteStage
from ai_assistant.testing import FakeMemoryPolicy, FakeMemoryStore, FakeMemoryWriter
from ai_assistant.testing.memories import memory, said_support

_AT = datetime(2026, 3, 4, 10, 0, tzinfo=UTC)

#: Words that must reach no log line: the proposal's content, its rationale, and
#: the record's fact.
_CONTENT = "the user's sister is called Imogen"
_RATIONALE = "the user said so while planning the weekend"


def _now() -> datetime:
    return _AT


def _proposal(record_id: str) -> MemoryUpdateProposal:
    return MemoryUpdateProposal(
        proposed=memory(record_id, _CONTENT, said_support()),
        rationale=_RATIONALE,
    )


def _stage(store: FakeMemoryStore, kind: MemoryDecisionKind) -> MemoryWriteStage:
    return MemoryWriteStage(
        writer=FakeMemoryWriter(store=store, policy=FakeMemoryPolicy(kind), now=_now)
    )


async def test_an_ask_user_ruling_writes_nothing_and_logs_one_event_by_kind() -> None:
    """Nothing is written and nothing is parked; one event names the two kinds alone."""
    store = FakeMemoryStore(now=_now)
    await store.add(held_episode())
    stage = _stage(store, MemoryDecisionKind.ASK_USER)

    with structlog.testing.capture_logs() as logs:
        outcome = await stage.write(_proposal("deferred-1"))

    assert outcome.result.decision.kind is MemoryDecisionKind.ASK_USER
    assert await store.get("deferred-1") is None
    events = [entry for entry in logs if entry["event"] == DEFERRED_EVENT]
    assert events == [
        {
            "event": DEFERRED_EVENT,
            "log_level": "info",
            "ruling": MemoryDecisionKind.ASK_USER.value,
            "memory_kind": "memory",
        }
    ]


async def test_the_deferral_event_carries_no_proposal_id_and_no_content() -> None:
    """ADR-0319 §5: no identifier and no content of the proposal reach the log.

    A memory id is not guaranteed free of personal data, so it is excluded with
    the user's words (ADR-0004 §5). The ruling's ``reason`` is excluded with the
    rest, because a policy may quote the proposal in it.
    """
    record_id = "imogen-sister-deferred-2"
    store = FakeMemoryStore(now=_now)
    await store.add(held_episode())
    stage = _stage(store, MemoryDecisionKind.ASK_USER)

    with structlog.testing.capture_logs() as logs:
        outcome = await stage.write(_proposal(record_id))

    (event,) = [entry for entry in logs if entry["event"] == DEFERRED_EVENT]
    assert set(event) == {"event", "log_level", "ruling", "memory_kind"}
    rendered = repr(logs)
    assert record_id not in rendered
    assert _CONTENT not in rendered
    assert _RATIONALE not in rendered
    assert outcome.result.decision.reason not in rendered


async def test_a_committing_ruling_writes_and_logs_no_deferral() -> None:
    """Only a deferral is logged: a committed proposal is in the store, not the log."""
    store = FakeMemoryStore(now=_now)
    await store.add(held_episode())
    stage = _stage(store, MemoryDecisionKind.ACCEPT)

    with structlog.testing.capture_logs() as logs:
        outcome = await stage.write(_proposal("accepted-1"))

    assert outcome.result.decision.kind is MemoryDecisionKind.ACCEPT
    assert await store.get("accepted-1") is not None
    assert [entry for entry in logs if entry["event"] == DEFERRED_EVENT] == []


async def test_an_operation_and_an_entry_pass_through_to_the_writer() -> None:
    """ADR-0329 §12:3, §14:4: ``apply`` and ``record_use`` take the stage's one route."""
    store = FakeMemoryStore(now=_now)
    await store.add(held_episode())
    stage = _stage(store, MemoryDecisionKind.ACCEPT)
    await stage.write(_proposal("kept-1"))
    stored = await store.get("kept-1")
    assert isinstance(stored, Memory)
    support = said_support(added_at=_AT)
    change = MemoryChange(
        memory=stored,
        operation=MemoryOperation(
            kind=MemoryOperationKind.ADD_SUPPORT,
            cites=support.points_at,
            at=_AT,
            by=MemoryWriterName.OBSERVER,
        ),
        support=support,
    )

    await stage.apply(change)
    added = await store.get("kept-1")
    assert isinstance(added, Memory)
    entry = TrackRecordEntry(
        episode=support.points_at.episode,  # type: ignore[union-attr]  # an input part's episode
        relied_at=_AT,
        held_up=True,
        recorded_at=_AT,
        recorded_by=MemoryWriterName.OBSERVER,
    )
    await stage.record_use(added, entry)

    after = await store.get("kept-1")
    assert isinstance(after, Memory)
    assert after.support_at(support.points_at) is not None
    assert after.track_record == (entry,)
