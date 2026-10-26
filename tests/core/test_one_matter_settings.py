"""ADR-0349 §9's settings: the held-inputs bound and the in-progress section's size.

The per-field guards an ``int`` setting inherits from its type — a flag is not a count,
a foreign scalar is not a number — are ``tests/core/test_config.py``'s, discovered from
the model; what is here is what ADR-0349 decides about these two fields in particular.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from ai_assistant.core.config import Settings


def _settings(**fields: Any) -> Settings:
    """Construct ``Settings`` from the fields a case names."""
    return Settings(**fields)


def test_the_defaults_are_the_decisions_starting_values() -> None:
    """§9:2, §9:3: four inputs held, and five in-progress entries."""
    settings = _settings()

    assert settings.held_input_limit == 4
    assert settings.in_progress_limit == 5


def test_join_limit_stays_until_step_two() -> None:
    """§1:4's step 1: ``join_limit`` stays, at its value, until step 2 removes it."""
    assert _settings().join_limit == 3


@pytest.mark.parametrize("name", ["held_input_limit", "in_progress_limit"])
def test_a_limit_of_one_is_admitted(name: str) -> None:
    """§9:2, §9:3: at least 1, and 1 itself; a held-inputs limit of 1 turns merging off."""
    assert getattr(_settings(**{name: 1}), name) == 1


@pytest.mark.parametrize("name", ["held_input_limit", "in_progress_limit"])
@pytest.mark.parametrize("value", [0, -1])
def test_a_limit_below_one_is_refused(name: str, value: int) -> None:
    """§9:2, §9:3: at least 1, so nothing below it loads."""
    with pytest.raises(ValidationError, match=name):
        _settings(**{name: value})
