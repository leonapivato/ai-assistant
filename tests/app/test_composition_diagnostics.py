"""The diagnostic record as the composition root wires it (ADR-0314 §3:3, §4:4, §7).

One :class:`~ai_assistant.evaluation.FileDiagnosticRecord`, handed out narrowed and never
whole: to the engine's sweep as a ``DiagnosticRetention`` always, and to each emitter as a
``DiagnosticSink`` only where ``Settings.diagnostic_record`` is on. The cases build real
engines over a hashing embedder and a temporary data directory, and open no socket.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from ai_assistant.app import build_engine, diagnostic_record_directory
from ai_assistant.app import composition as composition_module
from ai_assistant.app.composition import DIAGNOSTIC_FILE_BYTES
from ai_assistant.core.config import EmbedderKind, Settings
from ai_assistant.core.errors import ConfigurationError
from ai_assistant.evaluation import FileDiagnosticRecord
from ai_assistant.models.follow_up import FollowUpAsker
from ai_assistant.orchestration.phase_path import PhasePath

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.integration


def _spy(monkeypatch: pytest.MonkeyPatch) -> list[FileDiagnosticRecord]:
    """Record every diagnostic record the builder constructs, still building real ones."""
    built: list[FileDiagnosticRecord] = []

    class _Recorded(FileDiagnosticRecord):
        def __init__(self, **kwargs: object) -> None:
            super().__init__(**kwargs)  # type: ignore[arg-type]  # the root's own keywords
            built.append(self)

    monkeypatch.setattr(composition_module, "FileDiagnosticRecord", _Recorded)
    return built


def _holders_of(root: object, target: object, *, depth: int = 6) -> list[str]:
    """Every attribute path from ``root`` that reaches ``target``, cycle-guarded."""
    found: list[str] = []
    seen: set[int] = set()

    def visit(subject: object, path: str, remaining: int) -> None:
        if remaining == 0 or id(subject) in seen:
            return
        seen.add(id(subject))
        for name, value in vars(subject).items():
            if value is target:
                found.append(f"{path}.{name}")
            elif hasattr(value, "__dict__"):
                visit(value, f"{path}.{name}", remaining - 1)

    visit(root, "engine", depth)
    return sorted(found)


def test_the_record_is_off_by_default_with_a_thirty_day_window() -> None:
    """§2:1, §7:1: off unless the owner opts in, and finite."""
    settings = Settings()

    assert settings.diagnostic_record is False
    assert settings.diagnostic_retention == timedelta(days=30)


@pytest.mark.parametrize("spelled", ["none", "PT0S", "-P1D"])
def test_the_window_has_no_keep_forever_and_no_zero(spelled: str) -> None:
    """§7:1: strictly positive, with no spelling for keep forever."""
    with pytest.raises(ValueError, match="diagnostic_retention"):
        Settings(diagnostic_retention=spelled)  # type: ignore[arg-type]  # as an operator spells it


async def test_off_the_sweep_alone_holds_the_record_and_nothing_is_created(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§4:4, §7:3: no emitter holds a sink, and the sweep still holds the record."""
    built = _spy(monkeypatch)
    engine = build_engine(Settings(embedder=EmbedderKind.HASHING), data_dir=tmp_path)
    try:
        assert len(built) == 1
        assert built[0].directory == tmp_path / "diagnostics"
        assert built[0]._file_bytes == DIAGNOSTIC_FILE_BYTES
        assert _holders_of(engine, built[0]) == ["engine._diagnostic_retention"]
        assert engine._observer is not None
        assert engine._observer._entries._sink is None  # ADR-0333 §2:7
        assert engine._diagnostic_window == timedelta(days=30)
        assert not (tmp_path / "diagnostics").exists()
    finally:
        await engine.aclose()


async def test_on_each_emitter_holds_the_one_record_as_its_sink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§4:4: the controller's engine, recall and understanding, and the phases' four."""
    built = _spy(monkeypatch)
    settings = Settings(embedder=EmbedderKind.HASHING, diagnostic_record=True)
    engine = build_engine(settings, data_dir=tmp_path)
    try:
        record = built[0]
        phases = engine._phases
        assert isinstance(phases, PhasePath)
        assert engine._diagnostics is record
        assert engine._recall is not None
        assert engine._recall._diagnostics is record
        assert engine._understanding is not None
        assert engine._understanding._diagnostics is record
        assert phases._planning._diagnostics is record
        assert phases._planning._completer._diagnostics is record  # type: ignore[attr-defined]
        assert phases._authorizing._diagnostics is record
        assert phases._digesting._diagnostics is record
        assert engine._diagnostic_retention is record
        # ADR-0333 §2:7: the observer, a background stage, holds the same sink.
        assert engine._observer is not None
        assert engine._observer._entries._sink is record
    finally:
        await engine.aclose()


async def test_the_engine_sweeps_the_record_by_its_window_with_the_record_off(
    tmp_path: Path,
) -> None:
    """§7:2-§7:3: a file written while it was on is deleted after it is turned off."""
    directory = diagnostic_record_directory(Settings(), data_dir=tmp_path)
    directory.mkdir(parents=True, mode=0o700)
    stale = directory / "3f2b8c4e-1d5a-4e7b-9c0d-2a6f8e1b7c35.jsonl"
    fresh = directory / "9a1c7e52-6b3d-4f80-8e2a-1c5d7b9f0e46.jsonl"
    for path, age in ((stale, timedelta(days=40)), (fresh, timedelta(days=1))):
        path.write_text("{}\n", encoding="utf-8")
        stamp = (datetime.now(UTC) - age).timestamp()
        os.utime(path, (stamp, stamp))
    engine = build_engine(Settings(embedder=EmbedderKind.HASHING), data_dir=tmp_path)
    try:
        report = await engine.purge_expired()
    finally:
        await engine.aclose()

    assert report.diagnostics == 1
    assert [path.name for path in directory.iterdir()] == [fresh.name]


def test_a_hub_without_a_sweep_refuses_to_start_with_the_record_on(tmp_path: Path) -> None:
    """§7:4: the window is the record's forgetting, so no sweep means no start."""
    settings = Settings(
        embedder=EmbedderKind.HASHING, diagnostic_record=True, retention_purge_interval=None
    )

    with pytest.raises(ConfigurationError, match=str(tmp_path / "diagnostics")):
        build_engine(settings, data_dir=tmp_path)


def test_a_hub_without_a_sweep_refuses_to_start_while_the_record_holds_a_file(
    tmp_path: Path,
) -> None:
    """§7:4: off now, but files written while it was on would never be deleted."""
    directory = tmp_path / "diagnostics"
    directory.mkdir(mode=0o700)
    (directory / "3f2b8c4e-1d5a-4e7b-9c0d-2a6f8e1b7c35.jsonl").write_text("{}\n")
    settings = Settings(embedder=EmbedderKind.HASHING, retention_purge_interval=None)

    with pytest.raises(ConfigurationError, match=str(directory)):
        build_engine(settings, data_dir=tmp_path)


def test_the_refusal_comes_before_any_store_opens(tmp_path: Path) -> None:
    """§7:4: before the API accepts a request; here, before the data directory is made."""
    data_dir = tmp_path / "fresh"
    settings = Settings(
        embedder=EmbedderKind.HASHING, diagnostic_record=True, retention_purge_interval=None
    )

    with pytest.raises(ConfigurationError):
        build_engine(settings, data_dir=data_dir)

    assert not data_dir.exists()


async def test_a_hub_without_a_sweep_starts_with_the_record_off_and_empty(
    tmp_path: Path,
) -> None:
    """An empty directory, or none, is nothing the window would have to forget."""
    (tmp_path / "diagnostics").mkdir(mode=0o700)
    settings = Settings(embedder=EmbedderKind.HASHING, retention_purge_interval=None)

    engine = build_engine(settings, data_dir=tmp_path)
    await engine.aclose()


async def test_a_hub_with_a_sweep_starts_with_the_record_on(tmp_path: Path) -> None:
    """The ordinary opt-in: the purge job is enabled by default."""
    engine = build_engine(
        Settings(embedder=EmbedderKind.HASHING, diagnostic_record=True), data_dir=tmp_path
    )
    await engine.aclose()


def test_an_observer_file_alone_still_refuses_a_start_without_a_sweep(tmp_path: Path) -> None:
    """ADR-0333 §3:2: the observer's file is counted by the startup refusal like any other."""
    directory = tmp_path / "diagnostics"
    directory.mkdir(mode=0o700)
    (directory / "3f2b8c4e-1d5a-4e7b-9c0d-2a6f8e1b7c35.observer.jsonl").write_text("{}\n")
    settings = Settings(embedder=EmbedderKind.HASHING, retention_purge_interval=None)

    with pytest.raises(ConfigurationError, match=str(directory)):
        build_engine(settings, data_dir=tmp_path)


def test_a_follow_up_file_alone_still_refuses_a_start_without_a_sweep(tmp_path: Path) -> None:
    """ADR-0337 §8:13: the follow-up file is counted by the startup refusal like any other."""
    directory = tmp_path / "diagnostics"
    directory.mkdir(mode=0o700)
    (directory / "3f2b8c4e-1d5a-4e7b-9c0d-2a6f8e1b7c35.followup.jsonl").write_text("{}\n")
    settings = Settings(embedder=EmbedderKind.HASHING, retention_purge_interval=None)

    with pytest.raises(ConfigurationError, match=str(directory)):
        build_engine(settings, data_dir=tmp_path)


# --- ADR-0337 §8: the follow-up asker around the record ----------------------------------


def test_the_follow_up_without_the_record_refuses_the_start_naming_both(tmp_path: Path) -> None:
    """§8:2: refused before the API accepts a request; here, before the data directory."""
    data_dir = tmp_path / "fresh"
    settings = Settings(embedder=EmbedderKind.HASHING, follow_up_question=True)

    with pytest.raises(ConfigurationError, match="follow_up_question") as refused:
        build_engine(settings, data_dir=data_dir)

    assert "diagnostic_record" in str(refused.value)
    assert not data_dir.exists()


async def test_with_the_record_on_and_no_follow_up_no_emitter_holds_an_asker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§8:1: off by default, so a hub hosted for another person never asks."""
    built = _spy(monkeypatch)
    settings = Settings(embedder=EmbedderKind.HASHING, diagnostic_record=True)
    engine = build_engine(settings, data_dir=tmp_path)
    try:
        assert engine._diagnostics is built[0]
        assert not any(isinstance(one, FollowUpAsker) for one in vars(engine).values())
    finally:
        await engine.aclose()


async def test_with_the_follow_up_on_every_emitter_holds_the_asker_around_the_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§8:5: the sink every emitter is handed is the asker, wrapping the one record."""
    built = _spy(monkeypatch)
    settings = Settings(
        embedder=EmbedderKind.HASHING,
        diagnostic_record=True,
        follow_up_question=True,
        follow_up_daily_calls=7,
        default_model="anthropic:claude-default",
        observer_scout_model="anthropic:claude-scout",
        model_timeout_seconds=12.5,
    )
    engine = build_engine(settings, data_dir=tmp_path)
    try:
        record = built[0]
        held = engine._diagnostics
        assert isinstance(held, FollowUpAsker)
        asker: FollowUpAsker = held
        assert asker._sink is record
        phases = engine._phases
        assert isinstance(phases, PhasePath)
        assert engine._recall is not None
        assert engine._recall._diagnostics is asker
        assert engine._understanding is not None
        assert engine._understanding._diagnostics is asker
        assert phases._planning._diagnostics is asker
        assert phases._planning._completer._diagnostics is asker  # type: ignore[attr-defined]
        assert phases._authorizing._diagnostics is asker
        assert phases._digesting._diagnostics is asker
        assert engine._observer is not None
        assert engine._observer._entries._sink is asker
        # The sweep still holds the record itself, never the asker (ADR-0314 §3:3).
        assert engine._diagnostic_retention is record
        # §8:8: each route's first model; §8:3 the budget; the routes' own deadline.
        assert asker._routes == {
            "understanding": "anthropic:claude-default",
            "planning": "anthropic:claude-default",
            "digesting": "anthropic:claude-default",
            "observer.scout": "anthropic:claude-scout",
            "observer.framing": "anthropic:claude-default",
            "observer.placement": "anthropic:claude-default",
        }
        assert asker._budget.limit == 7
        assert asker._timeout == 12.5
        # §8:16: the asker is stopped first among what the façade closes.
        assert engine._closers[0] == asker.aclose
    finally:
        await engine.aclose()
    assert asker._closed
