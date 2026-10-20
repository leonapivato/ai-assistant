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


# --- relayed mode (ADR-0330 §3) -------------------------------------------------

#: A line, as relayed mode needs one first (§3:6).
_LINE: dict[str, Any] = {"telegram_connection": "conn-relay", "telegram_user_id": 424242}

#: A certificate's body, as a PEM file carries it across lines.
_BODY = "MIIBszCCAVmgAwIBAgIUQ0FfYm9keV9mb3JfdGVzdHMwCgYIKoZIzj0EAwIw"
_PEM = f"-----BEGIN CERTIFICATE-----\n{_BODY[:32]}\n{_BODY[32:]}\n-----END CERTIFICATE-----\n"


def test_a_line_is_direct_by_default() -> None:
    """No relay origin is direct mode, ADR-0323's line (§3:1)."""
    settings = _settings(**_LINE)

    assert settings.telegram_relay_origin is None
    assert settings.telegram_relay_certificates == ()


@pytest.mark.parametrize(
    "written",
    [
        _PEM,
        _PEM.replace("\n", ""),
        "  " + _PEM.replace("\n", " ") + "  ",
    ],
    ids=["as-printed", "line-breaks-removed", "spaced"],
)
def test_a_relayed_line_takes_the_relays_certificate_in_pem(written: str) -> None:
    """Each element is one PEM certificate, line breaks or none, held as its body."""
    settings = _settings(
        **_LINE,
        telegram_relay_origin="https://telegram-relay:8443",
        telegram_relay_certificates=(written,),
    )

    assert settings.telegram_relay_origin == "https://telegram-relay:8443"
    assert settings.telegram_relay_certificates == (_BODY,)


def test_the_certificates_are_one_variable_comma_separated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The form an env file can carry: one line, two certificates for a rotation (§3:9)."""
    one_line = _PEM.replace("\n", "")
    monkeypatch.setenv("ASSISTANT_TELEGRAM_CONNECTION", "conn-relay")
    monkeypatch.setenv("ASSISTANT_TELEGRAM_USER_ID", "424242")
    monkeypatch.setenv("ASSISTANT_TELEGRAM_RELAY_ORIGIN", "https://telegram-relay:8443")
    monkeypatch.setenv("ASSISTANT_TELEGRAM_RELAY_CERTIFICATES", f"{one_line},{one_line}")

    settings = Settings()

    assert settings.telegram_relay_certificates == (_BODY, _BODY)


@pytest.mark.parametrize(
    "written",
    [
        _BODY,
        "-----BEGIN CERTIFICATE-----not base64!-----END CERTIFICATE-----",
        "-----BEGIN CERTIFICATE----------END CERTIFICATE-----",
        # Assembled, so the repository's private-key hook does not read a key here.
        "-----BEGIN " + "PRIVATE KEY-----" + _BODY + "-----END " + "PRIVATE KEY-----",
        _PEM + _PEM,
        "/etc/relay/ca/cert.pem",
    ],
    ids=["no-armour", "not-base64", "empty-body", "a-private-key", "two-in-one", "a-path"],
)
def test_an_element_that_is_not_one_pem_certificate_is_refused(written: str) -> None:
    """Decidable from the text alone, so refused at load (§3:7)."""
    with pytest.raises(ValidationError, match=r"telegram_relay_certificates\[0\]"):
        _settings(
            **_LINE,
            telegram_relay_origin="https://telegram-relay:8443",
            telegram_relay_certificates=(written,),
        )


def test_a_relay_origin_with_no_line_is_refused() -> None:
    """A relayed line is a line first (§3:6)."""
    with pytest.raises(ValidationError, match="ADR-0330 §3:6"):
        _settings(
            telegram_relay_origin="https://telegram-relay:8443",
            telegram_relay_certificates=(_PEM,),
        )


def test_a_relay_origin_with_no_certificate_is_refused() -> None:
    """Trusted by the configured certificates and no others, so it needs one (§3:7)."""
    with pytest.raises(ValidationError, match="telegram_relay_certificates is empty"):
        _settings(**_LINE, telegram_relay_origin="https://telegram-relay:8443")


def test_certificates_with_no_relay_are_refused() -> None:
    """Certificates for no relay trust nothing, and are refused rather than ignored."""
    with pytest.raises(ValidationError, match="telegram_relay_origin is not"):
        _settings(**_LINE, telegram_relay_certificates=(_PEM,))


@pytest.mark.parametrize("origin", ["", "   "])
def test_a_blank_relay_origin_is_refused(origin: str) -> None:
    """A cleared variable is not an origin."""
    with pytest.raises(ValidationError, match="must hold text"):
        _settings(**_LINE, telegram_relay_origin=origin, telegram_relay_certificates=(_PEM,))


@pytest.mark.parametrize(
    "origin", ["https://10.254.0.1:8443", "http://telegram-relay:8443", "https://relay/path"]
)
def test_the_origin_is_checked_as_text_alone_at_load(origin: str) -> None:
    """The canonicaliser's rules stay at the seam (§3:5): the composition root refuses."""
    settings = _settings(**_LINE, telegram_relay_origin=origin, telegram_relay_certificates=(_PEM,))

    assert settings.telegram_relay_origin == origin
