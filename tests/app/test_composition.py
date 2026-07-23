"""The composition root wires the production subsystems (ADR-0042 §2).

These are real integration tests: they open the actual connection-owning SQLite
stores (in a temp directory) and assemble the real subsystems. They do not call
the model — construction wires the provider but never invokes it — so no network
or API key is needed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from ai_assistant.app import build_engine
from ai_assistant.app import composition as composition_module
from ai_assistant.core.config import Settings
from ai_assistant.core.errors import AssistantError
from ai_assistant.orchestration import Engine

if TYPE_CHECKING:
    from pathlib import Path


async def test_build_engine_returns_a_ready_engine(tmp_path: Path) -> None:
    """The builder assembles a real ``Engine`` and opens its stores."""
    engine = build_engine(Settings(), data_dir=tmp_path)
    try:
        assert isinstance(engine, Engine)
        # The connection-owning stores were opened on disk.
        assert (tmp_path / "memory.db").exists()
        assert (tmp_path / "audit.db").exists()
    finally:
        await engine.aclose()


async def test_the_engine_closes_its_owned_resources(tmp_path: Path) -> None:
    """``aclose`` releases the connections the builder handed the façade (§2)."""
    engine = build_engine(Settings(), data_dir=tmp_path)
    await engine.aclose()
    # Idempotent: a second close does nothing and does not raise.
    await engine.aclose()


async def test_build_engine_creates_a_missing_data_dir(tmp_path: Path) -> None:
    """A data directory that does not exist yet is created (§2 owns its resources)."""
    nested = tmp_path / "state" / "assistant"
    assert not nested.exists()
    engine = build_engine(Settings(), data_dir=nested)
    try:
        assert nested.is_dir()
    finally:
        await engine.aclose()


class _SpyStore:
    """A stand-in for a connection-owning store that records its close call."""

    instances: list[_SpyStore] = []  # noqa: RUF012 — a test-local registry, not a model field

    def __init__(self, **_kwargs: object) -> None:
        self.closed = False
        _SpyStore.instances.append(self)

    def close(self) -> None:
        self.closed = True


async def test_build_engine_closes_opened_stores_when_a_later_step_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If construction fails after a store is opened, that store is closed (§2).

    The builder must return no half-built façade with an orphaned connection.
    """
    _SpyStore.instances.clear()
    monkeypatch.setattr(composition_module, "SqliteMemoryStore", _SpyStore)
    monkeypatch.setattr(composition_module, "SqliteAuditTrail", _SpyStore)

    def _boom(*_args: object, **_kwargs: object) -> object:
        msg = "planner construction failed"
        raise RuntimeError(msg)

    # ModelBackedPlanner is built *after* both stores are opened.
    monkeypatch.setattr(composition_module, "ModelBackedPlanner", _boom)

    with pytest.raises(RuntimeError, match="planner construction failed"):
        build_engine(Settings(), data_dir=tmp_path)

    assert _SpyStore.instances, "both stores should have been opened before the failure"
    assert all(store.closed for store in _SpyStore.instances)  # every opened store was closed


async def test_build_engine_converts_a_data_dir_failure_to_an_assistant_error(
    tmp_path: Path,
) -> None:
    """A directory that cannot be created is an AssistantError, not a raw OSError."""
    # A file occupies the path where a directory is needed, so mkdir fails.
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory")
    with pytest.raises(AssistantError, match="data directory"):
        build_engine(Settings(), data_dir=blocker / "sub")
