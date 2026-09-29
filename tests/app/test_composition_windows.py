"""The composition root wires ADR-0282's windows stage, holding ADR-0276 §4's selector."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ai_assistant.app import build_engine
from ai_assistant.app.composition import UNDERSTANDING_EPISODE_LIMIT
from ai_assistant.core.config import Settings
from ai_assistant.orchestration.understanding import RecentEpisodes, WindowsStage

if TYPE_CHECKING:
    from pathlib import Path


async def test_the_engine_is_built_with_the_windows_stage_over_its_store(tmp_path: Path) -> None:
    engine = build_engine(Settings(), data_dir=tmp_path)
    try:
        windows = engine._windows
        assert isinstance(windows, WindowsStage)
        selector = windows._episodes
        assert isinstance(selector, RecentEpisodes)
        assert selector._memory is engine._loop._memory
        assert selector._limit == UNDERSTANDING_EPISODE_LIMIT
        # ADR-0282 §5: the understanding stage itself holds no selector and reads no store.
        assert not hasattr(engine._understanding, "_episodes")
    finally:
        await engine.aclose()
