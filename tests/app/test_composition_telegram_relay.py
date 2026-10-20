"""The composition root's relayed Telegram line (ADR-0330 §3:4, §3:8, §7:3, §12's table).

The root canonicalises the relay origin through the seam and loads the certificates,
refusing the hub's start on either failure, and above the data directory (#372); then
it builds the relayed client over a transport of the line's own, **anchored on the
relay's certificates alone** — never the one every integration is handed. A direct
line keeps the system-trust transport and Telegram's origin (§3:1).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

import pytest

from ai_assistant.app.composition import build_composition
from ai_assistant.core.config import EmbedderKind, Settings
from ai_assistant.core.errors import ConfigurationError
from ai_assistant.tools.egress import (
    TELEGRAM_BOT_API_ORIGIN,
    HttpsTelegramBotClient,
    StreamOutboundTransport,
)

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.anyio

#: The line, as relayed mode needs one first (§3:6).
LINE: Final[dict[str, Any]] = {"telegram_connection": "conn-relay", "telegram_user_id": 424242}

RELAY_CA: Final = (
    "-----BEGIN CERTIFICATE-----"
    "MIIBfTCCASOgAwIBAgIUVBNdEQURzbiRkUNtd9FKXpiqROkwCgYIKoZIzj0EAwIw"
    "GzEZMBcGA1UEAwwQRXhhbXBsZSBSZWxheSBDQTAeFw0yNjEwMTkwMDAwMDBaFw0z"
    "NjEwMTYwMDAwMDBaMBsxGTAXBgNVBAMMEEV4YW1wbGUgUmVsYXkgQ0EwWTATBgcq"
    "hkjOPQIBBggqhkjOPQMBBwNCAATLIYTcOBiLZXvnSdy9Ce/9GnVvplpNdlezdpAM"
    "bcben+U/yVbz+KAWeaeHaVN3AI6iseuT/BwUAeh710TXUWnWo0UwQzASBgNVHRMB"
    "Af8ECDAGAQH/AgEAMA4GA1UdDwEB/wQEAwIBBjAdBgNVHQ4EFgQUrhyCO524DfbQ"
    "rJ+pjaVMzcCtBpcwCgYIKoZIzj0EAwIDSAAwRQIgIHw06X8kxeupJqfPwjMzL7l0"
    "qogQOM3T9lHgnxRu7mQCIQCY4s5g3sYKk3LN4ToEodOoIUGyONE0iAJYZVNdlhG6"
    "JA=="
    "-----END CERTIFICATE-----"
)


def _settings(**fields: Any) -> Settings:
    return Settings(embedder=EmbedderKind.HASHING, **LINE, **fields)


def _client(settings: Settings, directory: Path) -> tuple[HttpsTelegramBotClient, Any]:
    composition = build_composition(settings, data_dir=directory)
    reader = composition.engine._telegram_reader
    assert reader is not None
    client = reader._client
    assert isinstance(client, HttpsTelegramBotClient)
    return client, composition


async def test_a_relayed_line_reaches_the_canonical_relay_over_an_anchored_transport(
    tmp_path: Path,
) -> None:
    """The client's origin is the canonical relay's, its transport trusts the CA alone."""
    settings = _settings(
        telegram_relay_origin="HTTPS://Telegram-Relay:8443", telegram_relay_certificates=(RELAY_CA,)
    )
    client, composition = _client(settings, tmp_path)
    try:
        transport = client._exchange._transport
        assert client._origin == "https://telegram-relay:8443"
        assert isinstance(transport, StreamOutboundTransport)
        assert transport._anchors is not None
        assert transport._anchors.context().cert_store_stats()["x509_ca"] == 1
    finally:
        await composition.engine.aclose()


async def test_a_direct_line_keeps_telegrams_origin_and_the_systems_trust(tmp_path: Path) -> None:
    """Direct mode is ADR-0323's line, unchanged (§3:1)."""
    client, composition = _client(_settings(), tmp_path)
    try:
        transport = client._exchange._transport
        assert client._origin == TELEGRAM_BOT_API_ORIGIN
        assert isinstance(transport, StreamOutboundTransport)
        assert transport._anchors is None
    finally:
        await composition.engine.aclose()


@pytest.mark.parametrize(
    ("fields", "named"),
    [
        (
            {
                "telegram_relay_origin": "https://10.254.0.1:8443",
                "telegram_relay_certificates": (RELAY_CA,),
            },
            "telegram_relay_origin",
        ),
        (
            {
                "telegram_relay_origin": "https://telegram-relay:8443/",
                "telegram_relay_certificates": (RELAY_CA,),
            },
            "telegram_relay_origin",
        ),
        (
            {
                "telegram_relay_origin": "https://telegram-relay:8443",
                "telegram_relay_certificates": (
                    "-----BEGIN CERTIFICATE-----AAAA-----END CERTIFICATE-----",
                ),
            },
            "telegram_relay_certificates",
        ),
    ],
    ids=["ip-literal", "trailing-path", "not-a-certificate"],
)
def test_a_relay_the_seam_will_not_reach_refuses_the_start_before_disk(
    tmp_path: Path, fields: dict[str, Any], named: str
) -> None:
    """§3:4 and §3:8: a configuration error, raised before the data directory exists."""
    directory = tmp_path / "data"

    with pytest.raises(ConfigurationError, match=named):
        build_composition(_settings(**fields), data_dir=directory)

    assert not directory.exists()
