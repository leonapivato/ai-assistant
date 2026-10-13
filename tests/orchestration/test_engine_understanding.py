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

from typing import Any

import pytest
from test_engine import AT, Harness, NoStepPlanner
from understanding_support import STATED_PROPOSAL, understanding_stage

from ai_assistant.core.errors import ConfigurationError
from ai_assistant.orchestration.composing import ComposingStage
from ai_assistant.testing import FakeMemoryStore, FakeModelProvider, FakeStreamingCompleter


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


# --- wiring ---------------------------------------------------------------------------------


@pytest.mark.parametrize("limit", [None, 1])
def test_a_stage_wired_without_a_version_bound_of_two_is_refused(limit: int | None) -> None:
    with pytest.raises(ConfigurationError, match="version bound"):
        _harness(FakeModelProvider(STATED_PROPOSAL), understanding_version_limit=limit)
