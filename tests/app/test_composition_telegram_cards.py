"""The composition root wires the line's approval cards (ADR-0361 §4:2, §4:9, §9:3).

Where the line is configured, ``request_approval`` posts its card through the line's
cards, the reader carries a tap out and edits them through the same object, and a tap
that changed a request wakes the Approvals sensor. Where it is not, no card is posted.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

import pytest

from ai_assistant.app.composition import build_composition
from ai_assistant.core.config import EmbedderKind, Settings
from ai_assistant.core.types import OWNER_PERSON_ID
from ai_assistant.orchestration.telegram import TelegramCards

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.anyio

LINE: Final[dict[str, Any]] = {"telegram_connection": "conn-line", "telegram_user_id": 424242}


async def test_a_configured_line_posts_edits_and_takes_taps_through_one_cards(
    tmp_path: Path,
) -> None:
    """One cards object: the poster, the reader's, and woken by the engine's sensor."""
    composition = build_composition(
        Settings(embedder=EmbedderKind.HASHING, **LINE), data_dir=tmp_path
    )
    try:
        engine = composition.engine
        reader = engine._telegram_reader
        phases = engine._phases
        assert reader is not None
        assert phases is not None
        calls = phases._approval_calls
        assert calls is not None
        cards = reader._cards
        assert isinstance(cards, TelegramCards)
        assert calls._cards is cards
        assert cards._wake == engine.approvals_changed
        assert cards._person == OWNER_PERSON_ID
    finally:
        await composition.engine.aclose()


async def test_a_hub_with_no_line_posts_no_card(tmp_path: Path) -> None:
    """§2:7: a request waits on the hub page's panel alone."""
    composition = build_composition(Settings(embedder=EmbedderKind.HASHING), data_dir=tmp_path)
    try:
        phases = composition.engine._phases
        assert phases is not None
        calls = phases._approval_calls
        assert calls is not None
        assert calls._cards is None
    finally:
        await composition.engine.aclose()
