"""The on-device recall threshold sits in the gap it was measured from (ADR-0281 §3).

ADR-0281 §3 has the value for ``FastEmbedEmbedder`` chosen so that "a short input
carrying no content, such as "yes", "ok" or "same as before", normally keeps
nothing, while a paraphrase of a stored fact keeps it". The measurement it was
chosen from is ``scripts/measure_recall_threshold.py`` (#2601); these tests run it
against the real, vendored model and pin both sides against the value the root
wires, so a change of embedder or model that moves either side across it fails
here rather than in what recall keeps.

The model is vendored (ADR-0024), so nothing is downloaded; the measurement is one
small store and a few dozen embeddings, run once for the module.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

from ai_assistant.app.composition import RECALL_THRESHOLDS
from ai_assistant.core.config import EmbedderKind
from ai_assistant.models.fastembed_embedder import FastEmbedEmbedder

sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))
from measure_recall_threshold import CONTENT_FREE, PARAPHRASES, Measurement, measure

_THRESHOLD = RECALL_THRESHOLDS[EmbedderKind.ON_DEVICE]


@pytest.fixture(scope="module")
def measured() -> Measurement:
    return asyncio.run(measure(FastEmbedEmbedder()))


def test_the_measurement_has_enough_of_each_group() -> None:
    """#2601's lists: the content-free replies it names, and at least a dozen pairs."""
    assert {"yes", "ok", "same as before", "sounds good", "thanks"} <= set(CONTENT_FREE)
    assert len(PARAPHRASES) >= 12


def test_no_content_free_reply_keeps_a_memory(measured: Measurement) -> None:
    """§3: "yes", "ok" or "same as before" keeps nothing, so no record scores at the cut."""
    kept = [
        (one.cue, one.record, one.score) for one in measured.content_free if one.score >= _THRESHOLD
    ]
    assert kept == [], f"content-free replies at or above {_THRESHOLD}: {kept}"


def test_every_paraphrase_keeps_its_memory(measured: Measurement) -> None:
    """§3: a paraphrase of a stored fact keeps it, so its record scores at the cut."""
    missed = [
        (one.cue, one.record, one.score) for one in measured.paraphrases if one.score < _THRESHOLD
    ]
    assert missed == [], f"paraphrases below {_THRESHOLD}: {missed}"


def test_the_threshold_sits_in_the_measured_gap(measured: Measurement) -> None:
    """The two distributions separate, and the value is between them."""
    assert measured.gap > 0
    assert measured.content_free_max < _THRESHOLD <= measured.paraphrase_min
