"""ADR-0329 §6:9 and §20's addition to ADR-0284 §8:1: an episode's pending candidates.

The projection carries the facts the caller hands it, cut to the excerpt bound, and
carries none unless handed them; an episode with no processing record records no round,
so it carries none.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from test_episode_projection import _NOW, _episode, _recordless, _trigger

from ai_assistant.core.episode_encoding import project_episode
from ai_assistant.core.types import EpisodeProjection, Modality, ProjectedText
from ai_assistant.testing.parties import OWNERS_WORDS


def test_a_projection_carries_no_candidate_unless_handed_one() -> None:
    projection = project_episode(_episode(_trigger(OWNERS_WORDS)), excerpt_chars=100)

    assert projection.candidates == ()


def test_the_handed_facts_are_carried_in_order_each_cut_to_the_bound() -> None:
    projection = project_episode(
        _episode(_trigger(OWNERS_WORDS)),
        excerpt_chars=10,
        candidates=("prefers window seats", "short"),
    )

    assert projection.candidates == (
        ProjectedText(text="prefers wi", full_chars=20),
        ProjectedText(text="short", full_chars=5),
    )
    assert projection.candidates[0].cut
    assert not projection.candidates[1].cut


def test_an_episode_with_no_processing_record_is_handed_no_candidate() -> None:
    with pytest.raises(ValueError, match="records no candidate"):
        project_episode(_recordless(), excerpt_chars=100, candidates=("a fact",))


def test_a_projection_without_a_processing_record_carries_no_candidate() -> None:
    with pytest.raises(ValidationError, match="carries its content alone"):
        EpisodeProjection(
            occurred_at=_NOW,
            capture_modality=Modality.SPEECH,
            candidates=(ProjectedText(text="a fact", full_chars=6),),
        )
