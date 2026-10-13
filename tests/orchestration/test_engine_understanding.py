"""The engine driving ADR-0276's understanding stage: where it runs and what is recorded.

The stage's own behaviour — its windows, its one repair, its resolution — is in
``test_understanding.py``, and the carrier's bound and classification in
``test_activation_state.py``. What is left is only true of a whole pass: that the stage
runs after routing declines and before association on the conversational path and
before the event stage on the event path, that each branch ending a pass without an
understanding records the omission it names, that a spoken turn takes no episode
window, and that the event path maps the stage's failures outward as ADR-0274 §8 maps
the event stage's own.
"""

from __future__ import annotations

import time
from datetime import timedelta
from typing import TYPE_CHECKING, Any, Final

import pytest
from test_engine import AT, Harness, NoStepPlanner
from understanding_support import STATED_PROPOSAL, understanding_stage

from ai_assistant.core.errors import ConfigurationError, ModelTimeoutError
from ai_assistant.core.types import EpisodicMemory, ProcessingReason, UnderstandingOmission
from ai_assistant.orchestration.composing import ComposingStage
from ai_assistant.testing import FakeMemoryStore, FakeModelProvider, FakeStreamingCompleter

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.core.types import EpisodeProcessingRecord, Message

_UTTERANCE: Final = "Is our camping trip still on?"


def _harness(understanding_model: FakeModelProvider, **knobs: Any) -> Harness:
    memory = knobs.pop("memory", None) or FakeMemoryStore(now=lambda: AT)
    knobs.setdefault("planner", NoStepPlanner())
    knobs.setdefault(
        "composing",
        ComposingStage(model=FakeModelProvider("Yes."), streaming=FakeStreamingCompleter()),
    )
    return Harness(
        memory=memory,
        understanding=understanding_stage(model=understanding_model),
        **knobs,
    )


async def _record(harness: Harness) -> EpisodeProcessingRecord:
    """The one captured episode's processing record."""
    (episode,) = [r for r in await harness.memory.export() if isinstance(r, EpisodicMemory)]
    assert episode.processing_record is not None
    return episode.processing_record


# --- the conversational path ---------------------------------------------------------


class _Blocking(FakeModelProvider):
    """A provider that answers without yielding, after the budget is spent.

    The loop never gets control while it runs, so no timer can fire inside the stage:
    only a check of the deadline after the stage returns can see it was crossed.
    """

    async def complete(self, messages: Sequence[Message], *, model: str | None = None) -> Message:
        time.sleep(0.06)  # noqa: ASYNC251 — the point: a completion that never yields
        return await super().complete(messages, model=model)


async def test_a_stage_that_crosses_the_deadline_without_yielding_is_still_timed_out() -> None:
    harness = _harness(_Blocking(STATED_PROPOSAL))
    with pytest.raises(ModelTimeoutError):
        await harness.engine.converse(_UTTERANCE, timeout=timedelta(milliseconds=50))
    assert harness.associator.call_count == 0
    record = await _record(harness)
    assert record.reason is ProcessingReason.TIMEOUT
    assert record.understanding == ()
    assert record.understanding_omitted is UnderstandingOmission.FAILED


# --- wiring ---------------------------------------------------------------------------------


@pytest.mark.parametrize("limit", [None, 1])
def test_a_stage_wired_without_a_version_bound_of_two_is_refused(limit: int | None) -> None:
    with pytest.raises(ConfigurationError, match="version bound"):
        _harness(FakeModelProvider(STATED_PROPOSAL), understanding_version_limit=limit)
