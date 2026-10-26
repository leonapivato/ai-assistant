"""The composition root hands the engine and the readers their settings (ADR-0349 §9).

``held_input_limit`` and ``in_progress_limit`` reach the engine's account of what runs,
which the takeover stage, an offer and understanding's in-progress section read (ADR-0349
§9:2-§9:3); the hub chat's start wait, composing lapse and cap reach its reader (ADR-0332
§6:1-§6:3); and the line's start wait reaches its reader through the line's seams
(§6:4). Each is set off its default, so a root that dropped one would hand the default
and fail here. ``join_limit`` reaches nothing: joining by code is gone (ADR-0349 §9:1).
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Any, Final

import pytest

from ai_assistant.app.composition import build_composition
from ai_assistant.core.config import EmbedderKind, Settings

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.anyio

#: The line, configured, so the root builds its reader.
_LINE: Final[dict[str, Any]] = {"telegram_connection": "conn-0001", "telegram_user_id": 424242}


async def test_the_root_hands_the_engine_and_the_readers_the_settings(tmp_path: Path) -> None:
    settings = Settings(
        embedder=EmbedderKind.HASHING,
        held_input_limit=2,
        in_progress_limit=3,
        chat_start_wait=timedelta(seconds=0.25),
        chat_composing_lapse=timedelta(seconds=2),
        chat_composing_cap=timedelta(seconds=7),
        telegram_start_wait=timedelta(seconds=4),
        **_LINE,
    )
    composition = build_composition(settings, data_dir=tmp_path)
    engine = composition.engine
    try:
        assert engine._matters.held_input_limit == 2
        assert engine._matters.in_progress_limit == 3
        chat = engine._chat_reader
        assert chat is not None
        assert chat._start_wait == pytest.approx(0.25)
        assert chat._composing_lapse == pytest.approx(2.0)
        assert chat._composing_cap == pytest.approx(7.0)
        line = engine._telegram_reader
        assert line is not None
        assert line._start_wait == timedelta(seconds=4)
    finally:
        await engine.aclose()
