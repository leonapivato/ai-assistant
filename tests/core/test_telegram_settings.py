"""ADR-0323 §3:2 and §11's settings: the pair that names the line, and its bounds.

The per-field guards an ``int`` or a duration setting inherits from its type — a flag
is not a count, a foreign scalar is not a duration — are ``tests/core/test_config.py``'s,
discovered from the model; what is here is what ADR-0323 decides about these fields in
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


def test_the_line_is_off_by_default() -> None:
    """Neither setting is set, so there is no line (§3:3)."""
    settings = _settings()

    assert settings.telegram_connection is None
    assert settings.telegram_user_id is None


def test_both_settings_name_the_line() -> None:
    """The connection and the owner's account, together (§3:2)."""
    settings = _settings(telegram_connection="conn-0001", telegram_user_id=424242)

    assert settings.telegram_connection == "conn-0001"
    assert settings.telegram_user_id == 424242


@pytest.mark.parametrize(
    ("fields", "missing"),
    [
        ({"telegram_connection": "conn-0001"}, "telegram_user_id"),
        ({"telegram_user_id": 424242}, "telegram_connection"),
    ],
)
def test_one_setting_without_the_other_is_refused_at_load(
    fields: dict[str, Any], missing: str
) -> None:
    """Setting one without the other is refused at settings load (§3:2)."""
    with pytest.raises(ValidationError, match=missing):
        _settings(**fields)


@pytest.mark.parametrize("user", [0, -1, True])
def test_the_owners_account_is_a_positive_id(user: object) -> None:
    """A Telegram account id is positive, and a flag is not one."""
    with pytest.raises(ValidationError):
        _settings(telegram_connection="conn-0001", telegram_user_id=user)


@pytest.mark.parametrize("reference", ["", "   "])
def test_a_blank_connection_is_refused(reference: str) -> None:
    """A cleared variable is not a connection."""
    with pytest.raises(ValidationError, match="must hold text"):
        _settings(telegram_connection=reference, telegram_user_id=424242)


@pytest.mark.parametrize(
    ("wait", "bound"),
    [
        (timedelta(seconds=30), timedelta(seconds=30)),
        (timedelta(seconds=30), timedelta(seconds=10)),
    ],
    ids=["equal", "below"],
)
def test_a_poll_bound_not_above_its_wait_is_refused(wait: timedelta, bound: timedelta) -> None:
    """The bound exceeds the wait (§11:10)."""
    with pytest.raises(ValidationError, match="telegram_poll_bound"):
        _settings(telegram_poll_wait=wait, telegram_poll_bound=bound)


def test_the_defaults_bound_the_poll_above_its_wait() -> None:
    """A deployment that sets nothing still has a poll it can finish."""
    settings = _settings()

    assert settings.telegram_poll_bound > settings.telegram_poll_wait
    assert settings.telegram_send_bound > timedelta(0)
    assert settings.telegram_max_response_bytes > 0
