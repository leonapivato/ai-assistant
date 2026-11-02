"""Planning's side of the observer, as the composition root wires it (ADR-0329 §§3-6).

``remember`` records a candidate, its lookup is the look-ups', and reliance is offered.
ADR-0328 §13's interim, under which ``remember`` wrote through ``MemoryPolicy``, is
retired with the composition root's switch that kept it (ADR-0329 §2:3, §19:3), so no
constant and no setting can bring it back.

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
    REMEMBER_CANDIDATE,
    REMEMBER_CAPABILITY,
    CandidateCalls,
)

if TYPE_CHECKING:
    from pathlib import Path

    from ai_assistant.orchestration.engine import Engine


def _phases(tmp_path: Path) -> tuple[Engine, PhasePath]:
    engine = build_engine(Settings(embedder=EmbedderKind.HASHING), data_dir=tmp_path)
    phases = engine._phases
    assert isinstance(phases, PhasePath)
    return engine, phases


def test_no_switch_and_no_setting_brings_the_interim_back() -> None:
    """ADR-0329 §2:3: ``remember`` writes nothing, and nothing a hub reads changes that."""
    assert not hasattr(composition, "REMEMBER_RECORDS_CANDIDATES")
    assert not any("candidate" in name for name in Settings.model_fields)


def test_the_lookups_count_is_a_composition_root_constant() -> None:
    """§4:1."""
    assert composition.CANDIDATE_LOOKUP_LIMIT >= 1


async def test_remember_records_candidates_and_reliance_is_offered(tmp_path: Path) -> None:
    """§§3-6: what every deployment gets."""
    engine, phases = _phases(tmp_path)
    try:
        offered = {str(one.capability): one for one in await phases._offered()}
        assert offered[REMEMBER_CAPABILITY] == REMEMBER_CANDIDATE
        assert offered[NOTE_RELIANCE_CAPABILITY] == NOTE_RELIANCE
        runners = phases._acting._own_records
        # The Task Scheduler's runners sit beside the composition root's seam (ADR-0350 §4:3).
        while not isinstance(runners, OwnRecordsByCapability):
            runners = runners._beside  # type: ignore[attr-defined]  # the seam beside them
        assert isinstance(runners, OwnRecordsByCapability)
        runner = runners._runners[REMEMBER_CAPABILITY]
        assert isinstance(runner, CandidateCalls)
        assert runner._similar is phases._look_ups
        assert runner._limit == composition.CANDIDATE_LOOKUP_LIMIT
        assert set(phases._label_arguments[REMEMBER_CAPABILITY]) == {
            "rests_on_stimuli",
            "rests_on_responses",
            "rests_on_results",
            "memory",
        }
        assert set(phases._label_arguments[NOTE_RELIANCE_CAPABILITY]) == {"memories"}
    finally:
        await engine.aclose()
