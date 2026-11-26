"""The composition root hands the channels' readers its one holder (ADR-0383 §7:9, §9:1)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ai_assistant.app import build_engine
from ai_assistant.core.config import Settings
from ai_assistant.orchestration.bound_stores import BoundStores

if TYPE_CHECKING:
    from pathlib import Path


async def test_the_chats_reader_reads_its_windows_through_the_roots_holder(tmp_path: Path) -> None:
    """The holder recall and the windows stage read through, over the engine's own memory
    store, plan store and chat space: a work's window is read by its sight through it."""
    engine = build_engine(Settings(), data_dir=tmp_path)
    try:
        reader = engine._chat_reader
        assert reader is not None
        stores = reader._stores
        assert isinstance(stores, BoundStores)
        assert engine._windows is not None
        assert stores is engine._windows._stores, "one holder per process"
        assert stores._memory is engine._memory
        assert stores._plans is engine._plans
        assert stores._conversations is engine._conversations.chat_space
        # The reader's intake is the same chat space, held unbound for §7:8's reads.
        assert reader._conversations is stores._conversations
    finally:
        await engine.aclose()
