"""Recall wired into the engine: its stage, its record and what it shows (ADR-0281).

Each case builds the engine as the composition root does, with recall and understanding
both wired, and asserts what the one captured episode's processing record carries — the
stage entries, the recall result — and what the understanding stage was shown. The
stage alone is in ``test_recall.py``, and the rules and the controller in
``test_controller.py``.
"""

from __future__ import annotations

import time
from datetime import timedelta
from typing import TYPE_CHECKING, Any, Final

import pytest
from test_engine import AT, Harness, NoStepPlanner
from understanding_support import STATED_PROPOSAL, recall_stage, understanding_stage

from ai_assistant.core.errors import MemoryStoreError, ModelTimeoutError
from ai_assistant.core.types import (
    ControllerRule,
    ControllerStage,
    EpisodicMemory,
    RecallOutcome,
    StageOutcome,
)
from ai_assistant.orchestration.composing import ComposingStage
from ai_assistant.orchestration.informational_events import InformationalEventStage
from ai_assistant.testing import FakeMemoryStore, FakeModelProvider, FakeStreamingCompleter

if TYPE_CHECKING:
    from ai_assistant.core.types import EpisodeProcessingRecord, MemoryRecord
    from ai_assistant.orchestration.recall import RecallStage

_S = ControllerStage
_R = ControllerRule
_DONE = StageOutcome.DONE

_TURN: Final = "book the campsite at Pine Flat"


def _harness(
    memory: FakeMemoryStore | None = None,
    *,
    recall: RecallStage | None = None,
    understanding_model: FakeModelProvider | None = None,
    **knobs: Any,
) -> Harness:
    memory = memory or FakeMemoryStore(now=lambda: AT)
    knobs.setdefault("planner", NoStepPlanner())
    knobs.setdefault(
        "composing",
        ComposingStage(model=FakeModelProvider("Yes."), streaming=FakeStreamingCompleter()),
    )
    knobs.setdefault(
        "informational_events", InformationalEventStage(FakeModelProvider("Summarized."))
    )
    return Harness(
        memory=memory,
        understanding=understanding_stage(
            model=understanding_model or FakeModelProvider(STATED_PROPOSAL)
        ),
        recall=recall or recall_stage(memory),
        **knobs,
    )


async def _record(harness: Harness) -> EpisodeProcessingRecord:
    """The one captured activation's processing record."""
    (record,) = [
        r.processing_record
        for r in await harness.memory.export()
        if isinstance(r, EpisodicMemory) and r.processing_record is not None
    ]
    return record


def _entries(record: EpisodeProcessingRecord) -> list[tuple[ControllerStage, ControllerRule, Any]]:
    assert all(entry.due is not ControllerRule.STAGE_REPEATED for entry in record.stages)
    return [(entry.stage, entry.due, entry.outcome) for entry in record.stages]


class _Unyielding(FakeMemoryStore):
    """A store whose search holds the loop past a short deadline, then answers or fails."""

    def __init__(self, *records: MemoryRecord, fails: bool = False) -> None:
        super().__init__(now=lambda: AT)
        self._fails = fails

    async def search(self, query: str, **kwargs: Any) -> Any:
        time.sleep(0.05)  # noqa: ASYNC251 — the point: no timer can fire while it runs
        if self._fails:
            msg = "down"
            raise MemoryStoreError(msg)
        return await super().search(query, **kwargs)


@pytest.mark.parametrize("fails", [False, True], ids=["returns", "fails"])
async def test_recall_that_crosses_the_deadline_without_yielding_is_the_expiry(
    fails: bool,
) -> None:
    """§5: whatever recall returned past the deadline, the pass ends timed out, and what
    it produced is not recorded."""
    harness = _harness(recall=recall_stage(_Unyielding(fails=fails)))
    with pytest.raises(ModelTimeoutError, match="during recall"):
        await harness.engine.converse(_TURN, timeout=timedelta(milliseconds=20))
    record = await _record(harness)
    assert _entries(record) == [
        (_S.BEGIN_CONVERSATION, _R.CONVERSATION_UNRESOLVED, _DONE),
        (_S.WINDOWS, _R.WINDOWS_UNASSEMBLED, _DONE),
        (_S.RECALL, _R.NOT_RECALLED, StageOutcome.TIMED_OUT),
        (_S.END, _R.STAGE_TIMED_OUT, _DONE),
    ]
    assert record.recall is not None
    assert (record.recall.outcome, record.recall.items) == (RecallOutcome.TIMED_OUT, ())
