"""The composition root's switch for planning's side of the observer (ADR-0329 §19:3).

On — turned on in the change that wires the observer (§19:3) — ``remember`` records a
candidate, its lookup is the look-ups', and reliance is offered. Off, as it stood until
then, ``remember`` is the interim's (ADR-0328 §13): it writes through ``MemoryPolicy``,
nothing records a candidate, reliance is not offered, and the panel's read of the
pending candidates answers none (ADR-0329 §18:2). No setting reads it, so no person's
hub can turn it by itself.

**Nothing here opens a socket.** Every case builds the engine over a hashing embedder and
closes it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ai_assistant.app import build_engine, composition
from ai_assistant.core.config import EmbedderKind, Settings
from ai_assistant.orchestration.acting import OwnRecordsByCapability
from ai_assistant.orchestration.phase_path import PhasePath
from ai_assistant.orchestration.reliance import NOTE_RELIANCE, NOTE_RELIANCE_CAPABILITY
from ai_assistant.orchestration.remembering import (
    REMEMBER,
    REMEMBER_CANDIDATE,
    REMEMBER_CAPABILITY,
    CandidateCalls,
    RememberCalls,
)

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

    from ai_assistant.orchestration.engine import Engine


def _phases(tmp_path: Path) -> tuple[Engine, PhasePath]:
    engine = build_engine(Settings(embedder=EmbedderKind.HASHING), data_dir=tmp_path)
    phases = engine._phases
    assert isinstance(phases, PhasePath)
    return engine, phases


def test_the_switch_is_on_and_is_no_setting() -> None:
    """§19:3: on with the observer wired, and nothing a hub reads turns it."""
    assert composition.REMEMBER_RECORDS_CANDIDATES is True
    assert not any("candidate" in name for name in Settings.model_fields)


def test_the_lookups_count_is_a_composition_root_constant() -> None:
    """§4:1."""
    assert composition.CANDIDATE_LOOKUP_LIMIT >= 1


async def test_off_remember_is_the_interims_and_reliance_is_not_offered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0328 §13: the declaration, the runner, the policy and the interim's instruction."""
    monkeypatch.setattr(composition, "REMEMBER_RECORDS_CANDIDATES", False)
    engine, phases = _phases(tmp_path)
    try:
        offered = {str(one.capability): one for one in await phases._offered()}
        assert offered[REMEMBER_CAPABILITY] == REMEMBER
        assert NOTE_RELIANCE_CAPABILITY not in offered
        runners = phases._acting._own_records
        assert isinstance(runners, OwnRecordsByCapability)
        assert isinstance(runners._runners[REMEMBER_CAPABILITY], RememberCalls)
        assert phases._authorizing._candidates is False
        assert phases._planning._candidates is False
        assert phases._candidates is False
        # ADR-0329 §18:2: the panel's read honours the same switch, so it answers none.
        assert engine._candidates is False
        assert await engine.pending_candidates() == ()
        assert REMEMBER_CAPABILITY not in phases._label_arguments
    finally:
        await engine.aclose()


async def test_on_remember_records_candidates_and_reliance_is_offered(tmp_path: Path) -> None:
    """§§3-6: what every deployment gets, now the one constant is on."""
    engine, phases = _phases(tmp_path)
    try:
        offered = {str(one.capability): one for one in await phases._offered()}
        assert offered[REMEMBER_CAPABILITY] == REMEMBER_CANDIDATE
        assert offered[NOTE_RELIANCE_CAPABILITY] == NOTE_RELIANCE
        runners = phases._acting._own_records
        assert isinstance(runners, OwnRecordsByCapability)
        runner = runners._runners[REMEMBER_CAPABILITY]
        assert isinstance(runner, CandidateCalls)
        assert runner._similar is phases._look_ups
        assert runner._limit == composition.CANDIDATE_LOOKUP_LIMIT
        assert phases._authorizing._candidates is True
        assert phases._planning._candidates is True
        assert phases._candidates is True
        assert engine._candidates is True
        assert set(phases._label_arguments[REMEMBER_CAPABILITY]) == {
            "rests_on_user_messages",
            "rests_on_assistant_messages",
            "rests_on_results",
            "memory",
        }
        assert set(phases._label_arguments[NOTE_RELIANCE_CAPABILITY]) == {"memories"}
    finally:
        await engine.aclose()
