"""ADR-0332 §6's settings: the start waits, the composing signal and the join limit.

The per-field guards a duration or an ``int`` setting inherits from its type — a flag is
not a count, a foreign scalar is not a duration — are ``tests/core/test_config.py``'s,
discovered from the model; what is here is what ADR-0332 decides about these fields in
particular.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from pydantic import ValidationError

from ai_assistant.core.config import Settings


def _settings(**fields: Any) -> Settings:
    """Construct ``Settings`` from the fields a case names."""
    return Settings(**fields)


def test_the_defaults_are_the_decisions_starting_values() -> None:
    """§6:1 to §6:5: 1.5 s, 3 s, 10 s, 2 s and three joins."""
    settings = _settings()

    assert settings.chat_start_wait == timedelta(seconds=1.5)
    assert settings.chat_composing_lapse == timedelta(seconds=3)
    assert settings.chat_composing_cap == timedelta(seconds=10)
    assert settings.telegram_start_wait == timedelta(seconds=2)
    assert settings.join_limit == 3


@pytest.mark.parametrize(
    "name", ["chat_start_wait", "chat_composing_lapse", "chat_composing_cap", "telegram_start_wait"]
)
@pytest.mark.parametrize("value", [timedelta(0), timedelta(seconds=-1)])
def test_every_wait_is_strictly_positive(name: str, value: timedelta) -> None:
    """§6:1 to §6:4: a wait of nothing, or less, is refused at load."""
    with pytest.raises(ValidationError, match=name):
        _settings(**{name: value})


def test_a_join_limit_of_zero_turns_joining_off() -> None:
    """§6:5: 0 is admitted, and means no join and no takeover."""
    assert _settings(join_limit=0).join_limit == 0


def test_a_negative_join_limit_is_refused() -> None:
    """§6:5: at least 0."""
    with pytest.raises(ValidationError, match="join_limit"):
        _settings(join_limit=-1)


@pytest.mark.parametrize(
    "fields",
    [
        {"chat_start_wait": timedelta(seconds=11)},
        {"chat_composing_lapse": timedelta(seconds=11)},
        {"chat_composing_cap": timedelta(seconds=1)},
    ],
    ids=["below-the-wait", "below-the-lapse", "below-both"],
)
def test_a_cap_shorter_than_what_it_caps_is_refused(fields: dict[str, Any]) -> None:
    """§6:3: no shorter than ``chat_start_wait`` or ``chat_composing_lapse``."""
    with pytest.raises(ValidationError, match="chat_composing_cap"):
        _settings(**fields)


def test_a_cap_equal_to_what_it_caps_is_admitted() -> None:
    """§6:3's bound is inclusive: a cap as long as the wait and the lapse is no shorter."""
    settings = _settings(
        chat_start_wait=timedelta(seconds=4),
        chat_composing_lapse=timedelta(seconds=4),
        chat_composing_cap=timedelta(seconds=4),
    )

    assert settings.chat_composing_cap == timedelta(seconds=4)
