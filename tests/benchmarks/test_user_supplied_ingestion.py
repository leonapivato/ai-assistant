"""#1177: what LoCoMo's re-framing actually puts into the store.

The harness used to map LoCoMo's ``speaker_a`` onto the *user* half of an exchange and
``speaker_b`` onto the *assistant* half. Both claims are false — LoCoMo is two named
third parties chatting, neither of them is this system's user, and the assistant said
none of it — so the observer's first-person contract (ADR-0077 §3) was being scored
against an input that lied to it. The honest frame is that **the user is whoever handed
the assistant the transcript**, which is exactly the person the corpus's own questions
are asked by.

These tests pin the consequences of that frame end to end, through the real loader, the
real capture path and the real store: one exchange per corpus turn, no assistant half,
``assistant_led_turns`` telling the truth, #1074's join at one-turn-to-one-episode, and
the episode carrying what any turn the user typed would carry — ``CAPTURE_CONFIDENCE``,
and no external-content taint.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest
from benchmarks.memory.corpora import locomo
from benchmarks.memory.ingest import IngestionSummary, exchanges_of, ingest_case
from benchmarks.memory.wiring import build_harness

from ai_assistant.core.config import EmbedderKind, Settings
from ai_assistant.core.types import (
    EpisodicMemory,
    rests_on_recorded_external_content,
)
from ai_assistant.orchestration.conversations import CAPTURE_CONFIDENCE
from ai_assistant.testing import FakeObserver

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.integration

#: One exchange per observation pass, so the tiling below is exact rather than
#: approximately right.
BATCH = 1


def _sample() -> list[dict[str, Any]]:
    """A LoCoMo sample whose two sessions have five turns between them.

    Both speakers take a double turn, which is the shape the paired fold would have
    collapsed and the shape this framing must not.

    Returns:
        The sample list, ready to write as JSON.
    """
    return [
        {
            "sample_id": "conv-1",
            "conversation": {
                "speaker_a": "Caroline",
                "speaker_b": "Melanie",
                "session_1_date_time": "1:56 pm on 8 May, 2023",
                "session_1": [
                    {"speaker": "Caroline", "dia_id": "D1:1", "text": "I joined a support group."},
                    {"speaker": "Caroline", "dia_id": "D1:2", "text": "It meets on Tuesdays."},
                    {"speaker": "Melanie", "dia_id": "D1:3", "text": "That is good to hear."},
                ],
                "session_2_date_time": "9:05 am on 12 June, 2023",
                "session_2": [
                    {"speaker": "Melanie", "dia_id": "D2:1", "text": "How is the group?"},
                    {"speaker": "Caroline", "dia_id": "D2:2", "text": "Still going."},
                ],
            },
            "qa": [
                {
                    "category": 1,
                    "question": "What did Caroline join?",
                    "answer": "a support group",
                    "evidence": ["D1:1"],
                }
            ],
        }
    ]


@pytest.fixture
def case_file(tmp_path: Path) -> Path:
    """The sample on disk, where the real loader can read it."""
    path = tmp_path / "locomo10.json"
    path.write_text(json.dumps(_sample()), encoding="utf-8")
    return path


def test_every_corpus_turn_becomes_its_own_exchange(case_file: Path) -> None:
    """N exchanges for N turns, across sessions — the fixture-level claim #1177 makes."""
    case = locomo.load(case_file)[0]

    built = [exchange for session in case.sessions for exchange in exchanges_of(session)]

    assert case.turn_count == 5
    assert len(built) == 5


def test_no_exchange_has_an_assistant_half(case_file: Path) -> None:
    """The assistant said none of it, so there is nothing to put in `outcome`."""
    case = locomo.load(case_file)[0]

    built = [exchange for session in case.sessions for exchange in exchanges_of(session)]

    assert all(exchange.outcome is None for exchange in built)
    assert all(exchange.user_led for exchange in built)


async def test_ingestion_counts_no_assistant_led_turn(case_file: Path, tmp_path: Path) -> None:
    """The bookkeeping claim: `user_led` throughout, so `assistant_led_turns` is 0 —
    where the old mapping made the summary say the assistant led half the corpus."""
    summary = await _ingest(case_file, tmp_path)

    assert summary.turns_captured == 5
    assert summary.turns_degraded == 0
    assert summary.assistant_led_turns == 0


async def test_each_pointer_maps_to_exactly_one_episode(case_file: Path, tmp_path: Path) -> None:
    """#1074's join at its finest resolution: no fold, so no pointer shares an episode."""
    summary = await _ingest(case_file, tmp_path)

    assert sorted(summary.evidence_episodes) == ["D1:1", "D1:2", "D1:3", "D2:1", "D2:2"]
    assert all(len(episodes) == 1 for episodes in summary.evidence_episodes.values())
    assert len({episodes[0] for episodes in summary.evidence_episodes.values()}) == 5


async def test_every_episode_is_stored_as_the_users_own_turn(
    case_file: Path, tmp_path: Path
) -> None:
    """The framing decision, checked where it lands: the user told the assistant this,
    so the episode carries `CAPTURE_CONFIDENCE` and is not recorded external content
    (ADR-0106 §1) — which would otherwise make every belief resting on it an `ASK_USER`
    by ADR-0106 §6, and a headless run would measure its own headlessness."""
    episodes = await _episodes(case_file, tmp_path)

    assert len(episodes) == 5
    assert all(episode.outcome is None for episode in episodes)
    assert all(episode.provenance.confidence == CAPTURE_CONFIDENCE for episode in episodes)
    assert not any(rests_on_recorded_external_content(episode.provenance) for episode in episodes)


async def test_the_frame_reaches_the_episode_text(case_file: Path, tmp_path: Path) -> None:
    """Stated once per session, in the data — never in a prompt under `src/`."""
    episodes = await _episodes(case_file, tmp_path)

    framed = [episode for episode in episodes if "[Transcript the user shared]" in episode.content]

    assert len(framed) == 2
    assert all(episode.content.startswith("[Transcript the user shared]\n") for episode in framed)


def _settings(tmp_path: Path) -> Settings:
    """Settings a plumbing check may use, and a scored run may not.

    Args:
        tmp_path: The test's directory.

    Returns:
        The settings.
    """
    return Settings(
        data_dir=tmp_path / "data",
        embedder=EmbedderKind.HASHING,
        episode_retention=None,
        observation_batch_size=BATCH,
    )


async def _ingest(case_file: Path, tmp_path: Path) -> IngestionSummary:
    """Ingest the fixture case through a real harness.

    Args:
        case_file: The corpus file.
        tmp_path: The test's directory.

    Returns:
        The ingestion summary.
    """
    case = locomo.load(case_file)[0]
    harness = build_harness(
        _settings(tmp_path),
        data_dir=tmp_path / "case",
        observer=FakeObserver(max_batch_size=BATCH),
    )
    try:
        return await ingest_case(harness, case, batch_size=BATCH)
    finally:
        harness.close()


async def _episodes(case_file: Path, tmp_path: Path) -> tuple[EpisodicMemory, ...]:
    """Ingest, then read every episode back out of the store it landed in.

    Args:
        case_file: The corpus file.
        tmp_path: The test's directory.

    Returns:
        The episodes, in capture order.
    """
    case = locomo.load(case_file)[0]
    harness = build_harness(
        _settings(tmp_path),
        data_dir=tmp_path / "case",
        observer=FakeObserver(max_batch_size=BATCH),
    )
    try:
        summary = await ingest_case(harness, case, batch_size=BATCH)
        ordered = [episodes[0] for _, episodes in sorted(summary.evidence_episodes.items())]
        found = await harness.store.get_many(ordered)
    finally:
        harness.close()
    return tuple(
        record for record in (found[key] for key in ordered) if isinstance(record, EpisodicMemory)
    )
