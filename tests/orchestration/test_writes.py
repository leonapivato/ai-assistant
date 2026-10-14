"""The write stage: an ``ASK_USER`` ruling writes nothing and is logged (ADR-0309 §5).

The deferred-question queue retired with the old path, so the stage parks nothing
and reports what the writer ruled. What it adds is one structured event per
deferral, carrying the proposal's id and the ruling and never the proposal's
content (ADR-0004 §5).
"""

from __future__ import annotations

from datetime import UTC, datetime

import structlog.testing

from ai_assistant.core.types import (
    MemoryDecisionKind,
    MemorySource,
    MemoryUpdateProposal,
    Provenance,
    SemanticMemory,
)
from ai_assistant.orchestration.writes import DEFERRED_EVENT, MemoryWriteStage
from ai_assistant.testing import FakeMemoryPolicy, FakeMemoryStore, FakeMemoryWriter

_AT = datetime(2026, 3, 4, 10, 0, tzinfo=UTC)

#: Words that must reach no log line: the proposal's content, its rationale, and
#: the record's fact.
_CONTENT = "the user's sister is called Imogen"
_RATIONALE = "the user said so while planning the weekend"


def _now() -> datetime:
    return _AT


def _proposal(record_id: str) -> MemoryUpdateProposal:
    return MemoryUpdateProposal(
        proposed=SemanticMemory(
            id=record_id,
            content=_CONTENT,
            fact=_CONTENT,
            provenance=Provenance(source=MemorySource.OBSERVED, confidence=0.6, last_updated=_AT),
        ),
        rationale=_RATIONALE,
    )


def _stage(store: FakeMemoryStore, kind: MemoryDecisionKind) -> MemoryWriteStage:
    return MemoryWriteStage(
        writer=FakeMemoryWriter(store=store, policy=FakeMemoryPolicy(kind), now=_now)
    )


async def test_an_ask_user_ruling_writes_nothing_and_logs_one_event_by_id() -> None:
    """Nothing is written and nothing is parked; one event names the id and the ruling."""
    store = FakeMemoryStore(now=_now)
    stage = _stage(store, MemoryDecisionKind.ASK_USER)

    with structlog.testing.capture_logs() as logs:
        outcome = await stage.write(_proposal("deferred-1"))

    assert outcome.result.decision.kind is MemoryDecisionKind.ASK_USER
    assert outcome.admission is None
    assert await store.get("deferred-1") is None
    events = [entry for entry in logs if entry["event"] == DEFERRED_EVENT]
    assert events == [
        {
            "event": DEFERRED_EVENT,
            "log_level": "info",
            "proposal_id": "deferred-1",
            "ruling": MemoryDecisionKind.ASK_USER.value,
        }
    ]


async def test_the_deferral_event_carries_no_proposal_content() -> None:
    """ADR-0004 §5: identifiers and classes reach a log, never the user's words.

    The ruling's ``reason`` is excluded with the rest, because a policy may quote
    the proposal in it.
    """
    store = FakeMemoryStore(now=_now)
    stage = _stage(store, MemoryDecisionKind.ASK_USER)

    with structlog.testing.capture_logs() as logs:
        outcome = await stage.write(_proposal("deferred-2"))

    rendered = repr(logs)
    assert _CONTENT not in rendered
    assert _RATIONALE not in rendered
    assert outcome.result.decision.reason not in rendered


async def test_a_committing_ruling_writes_and_logs_no_deferral() -> None:
    """Only a deferral is logged: a committed proposal is in the store, not the log."""
    store = FakeMemoryStore(now=_now)
    stage = _stage(store, MemoryDecisionKind.ACCEPT)

    with structlog.testing.capture_logs() as logs:
        outcome = await stage.write(_proposal("accepted-1"))

    assert outcome.result.decision.kind is MemoryDecisionKind.ACCEPT
    assert await store.get("accepted-1") is not None
    assert [entry for entry in logs if entry["event"] == DEFERRED_EVENT] == []
