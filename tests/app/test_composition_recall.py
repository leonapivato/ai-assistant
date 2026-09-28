"""The composition root wires ADR-0281's recall stage, and its values (§3, §5)."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

import pytest

from ai_assistant.app import build_engine
from ai_assistant.app.composition import RECALL_BUDGET, RECALL_ITEM_LIMIT, RECALL_THRESHOLDS
from ai_assistant.core.config import EmbedderKind, Settings
from ai_assistant.orchestration.recall import RecallStage

if TYPE_CHECKING:
    from pathlib import Path


def test_the_roots_recall_values_are_the_ones_the_suites_restate() -> None:
    """``tests/orchestration/understanding_support.py`` restates these for the suites
    that build an engine without the root; this is where the two are held equal."""
    assert RECALL_ITEM_LIMIT == 3
    assert timedelta(seconds=2) == RECALL_BUDGET
    assert RECALL_THRESHOLDS[EmbedderKind.ON_DEVICE] == 0.65


def test_every_embedder_has_a_recall_threshold() -> None:
    """§3: a score's scale belongs to its embedder, so none may be wired without one."""
    assert set(RECALL_THRESHOLDS) == set(EmbedderKind)


@pytest.mark.parametrize("kind", list(EmbedderKind))
async def test_the_engine_is_built_with_recall_over_its_store_at_its_embedders_threshold(
    kind: EmbedderKind, tmp_path: Path
) -> None:
    engine = build_engine(Settings(embedder=kind), data_dir=tmp_path)
    try:
        recall = engine._recall
        assert isinstance(recall, RecallStage)
        assert recall._memory is engine._loop._memory
        assert recall._threshold == RECALL_THRESHOLDS[kind]
        assert recall._limit == RECALL_ITEM_LIMIT
        assert recall._budget == RECALL_BUDGET.total_seconds()
    finally:
        await engine.aclose()
