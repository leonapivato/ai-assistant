"""The Telegram line through the production composition root (ADR-0323 §3, §11, §13, §15:5).

One deployment, built by :func:`~ai_assistant.app.composition.build_composition` with the
line's two settings set and the bot connected through the shipped connect act, is
handed one fake transport answering as Telegram does. Its reader then polls through the
production client, over the root-wired connection store and keyring store, and its
writer answers by rule — so the token the connect act stored is read and bound into a
request by the seam alone, on the line's own route.

What is measured is §15:5's last arm on the whole route: **no token in any log line,
record or error**. The token is searched for in every log line the run wrote, in the
line's intake record, in the episodes and effect records, and in every request target
except the one the seam bound it into. And the line's absence is measured too: a
deployment that names no line opens no intake record and holds no reader (§3:3).

The keyring store's backend *selection* is the one thing displaced, by the lever
ADR-0125 §11 put on that class for a test (``m25_harness.point_the_keyring_at``).
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Final, final

import pytest
import structlog
from m25_harness import Backing, point_the_keyring_at
from pydantic import SecretStr

from ai_assistant.app.composition import build_composition, telegram_intake_path
from ai_assistant.core.config import EmbedderKind, Settings
from ai_assistant.core.types import TransportEndpoint
from ai_assistant.memory import SqliteTelegramIntakeRecord
from ai_assistant.orchestration.telegram import NON_TEXT_LINE
from ai_assistant.tools.egress import HttpsTelegramBotClient

if TYPE_CHECKING:
    from pathlib import Path

    from ai_assistant.app.composition import Composition
    from ai_assistant.core.protocols import ByteChannel

pytestmark = pytest.mark.anyio

#: The bot's token, as BotFather mints one; the part after the colon is the secret.
TOKEN: Final = "123456789:AAH-telegram_token_secret_part0"  # noqa: S105 — a test token
SECRET_PART: Final = TOKEN.split(":", 1)[1]

#: The owner's account, and so their chat with the bot.
CHAT: Final = 424242

#: Where the one origin pins to.
TELEGRAM: Final = TransportEndpoint(host="api.telegram.org", port=443, implicit_tls=True)

#: When the owner's messages were sent.
SENT: Final = int(datetime(2026, 10, 17, 9, 0, tzinfo=UTC).timestamp())


def _http(payload: object) -> bytes:
    body = json.dumps(payload).encode("utf-8")
    head = [
        "HTTP/1.1 200 OK",
        "Content-Type: application/json",
        f"Content-Length: {len(body)}",
        "",
        "",
    ]
    return "\r\n".join(head).encode("ascii") + body


def _updates() -> list[dict[str, Any]]:
    """What the owner sent and what a stranger sent: a photo, and a text from elsewhere."""
    return [
        {
            "update_id": 1,
            "message": {
                "message_id": 11,
                "date": SENT,
                "chat": {"id": CHAT, "type": "private"},
                "from": {"id": CHAT, "is_bot": False, "first_name": "O"},
                "photo": [{"file_id": "x", "file_unique_id": "y", "width": 1, "height": 1}],
            },
        },
        {
            "update_id": 2,
            "message": {
                "message_id": 3,
                "date": SENT,
                "chat": {"id": 99, "type": "private"},
                "from": {"id": 99, "is_bot": False, "first_name": "S"},
                "text": "let me in",
            },
        },
    ]


@final
class _Channel:
    """A secure channel whose far end answers as the Bot API does, by method."""

    def __init__(self, telegram: _Telegram) -> None:
        self._telegram = telegram
        self._inbound = bytearray()
        self.written = bytearray()

    @property
    def is_secure(self) -> bool:
        return True

    async def read_line(self) -> bytes:  # pragma: no cover — the exchange reads by `read`
        raise NotImplementedError

    async def read(self, limit: int, /) -> bytes:
        taken = bytes(self._inbound[:limit])
        del self._inbound[:limit]
        return taken

    async def write(self, data: bytes, /) -> None:
        self.written += data
        head, _, body = bytes(self.written).partition(b"\r\n\r\n")
        if b"Content-Length:" not in head or not body:
            return
        target = head.split(b" ", 2)[1].decode("ascii")
        self._inbound += self._telegram.answer(target.rsplit("/", 1)[1], json.loads(body))

    async def start_tls(self) -> None:
        """Nothing to upgrade."""

    async def close(self) -> None:
        """Release it."""


@final
class _Telegram:
    """An outbound transport whose far end is a scripted Telegram, or a relay serving it."""

    def __init__(
        self, *, polls_answered: int | None = None, endpoint: TransportEndpoint = TELEGRAM
    ) -> None:
        """Answer as Telegram does; after ``polls_answered`` polls, answer none of them.

        Args:
            polls_answered: How many polls are answered before none is.
            endpoint: The one endpoint the line may reach: Telegram's, or a relay's.
        """
        self._endpoint = endpoint
        self.channels: list[_Channel] = []
        self.sent: list[str] = []
        self.polls: list[dict[str, Any]] = []
        self._held = _updates()
        self._polls_answered = polls_answered

    async def open_channel(self, endpoint: TransportEndpoint) -> ByteChannel:
        assert endpoint == self._endpoint, "the line reaches its one origin, and no other"
        channel = _Channel(self)
        self.channels.append(channel)
        await asyncio.sleep(0.001)  # a real poll holds the loop's attention elsewhere
        return channel

    def answer(self, method: str, body: dict[str, Any]) -> bytes:
        if method == "getUpdates":
            self.polls.append(body)
            if self._polls_answered is not None and len(self.polls) > self._polls_answered:
                return b""  # written, and never answered: the poll's outcome is unknown
            offset = body.get("offset")
            if isinstance(offset, int):
                self._held = [one for one in self._held if one["update_id"] >= offset]
            return _http({"ok": True, "result": self._held})
        if method == "sendMessage":
            self.sent.append(str(body["text"]))
            return _http({"ok": True, "result": {"message_id": 500 + len(self.sent)}})
        return _http({"ok": True, "result": True})

    def targets(self) -> list[str]:
        return [
            bytes(one.written).split(b" ", 2)[1].decode("ascii")
            for one in self.channels
            if one.written
        ]


def _settings(reference: str | None = None, **relayed: Any) -> Settings:
    lined: dict[str, Any] = (
        {} if reference is None else {"telegram_connection": reference, "telegram_user_id": CHAT}
    )
    return Settings(embedder=EmbedderKind.HASHING, **lined, **relayed)


async def _connected(tmp_path: Path, backing: Backing, credential: str = TOKEN) -> str:
    """The line's credential connected through the shipped act, in the keyring (§3:1-§3:2)."""
    composition = build_composition(_settings(), data_dir=tmp_path, transport=None)
    point_the_keyring_at(composition, backing)
    try:
        account = await composition.engine.connect_account(
            identity="telegram-relay" if credential != TOKEN else "my-assistant-bot",
            credential=SecretStr(credential),
        )
    finally:
        await composition.engine.aclose()
    return account.reference


def _intake_files(directory: Path) -> list[Path]:
    """Every file a line's intake record could be opened at, under ``directory``."""
    return list(directory.glob("telegram*"))


def _reader(composition: Composition) -> Any:
    return composition.engine._telegram_reader


async def test_the_line_runs_over_the_production_route_and_no_token_escapes(
    tmp_path: Path,
) -> None:
    backing = Backing()
    reference = await _connected(tmp_path, backing)
    telegram = _Telegram()
    composition = build_composition(_settings(reference), data_dir=tmp_path, transport=telegram)
    point_the_keyring_at(composition, backing)
    reader = _reader(composition)
    assert isinstance(reader._client, HttpsTelegramBotClient)
    assert reader._client.chat_id == CHAT

    with structlog.testing.capture_logs() as logs:
        await composition.engine.start()
        async with asyncio.timeout(10):
            while not (telegram.sent and len(telegram.targets()) >= 4):  # noqa: ASYNC110 — the fake answers at once
                await asyncio.sleep(0.005)
        intake = reader._intake
        exported = await intake.export()
        await composition.engine.aclose()

    assert telegram.sent == [NON_TEXT_LINE], "the owner's photo answered, the stranger not"
    assert exported.intake == () or all(one.update_id == 1 for one in exported.intake)
    # The token is bound into the request target by the seam, and nowhere else.
    assert all(target.startswith(f"/bot{TOKEN}/") for target in telegram.targets())
    rendered = json.dumps(logs, default=str) + exported.model_dump_json()
    assert logs, "the run logged"
    assert SECRET_PART not in rendered
    assert "/bot" not in rendered
    assert isinstance(intake, SqliteTelegramIntakeRecord)
    assert telegram_intake_path(tmp_path, reference=reference, chat_id=CHAT).exists()


async def test_a_deployment_that_names_no_line_holds_none_and_opens_nothing(
    tmp_path: Path,
) -> None:
    """§3:3: with the settings unset, nothing starts and nothing changes."""
    telegram = _Telegram()
    composition = build_composition(_settings(), data_dir=tmp_path, transport=telegram)
    try:
        await composition.engine.start()
        await asyncio.sleep(0.01)
    finally:
        await composition.engine.aclose()

    assert _reader(composition) is None
    assert telegram.channels == []
    assert not _intake_files(tmp_path), "no intake record is opened"


async def test_another_bot_on_the_same_data_directory_starts_its_own_record(
    tmp_path: Path,
) -> None:
    """§2:3, §5:6: a new line is a new place, and another's owed offset confirms none of it.

    Bot A deals with its updates and owes Telegram their confirmation, its next poll
    never answered, when the hub stops. Bot B, connected and named in its place, polls
    with no offset: what A's record owed is A's, and B's unread messages are not
    confirmed away before B has taken them in.
    """
    backing = Backing()
    first = await _connected(tmp_path, backing)
    second = await _connected(tmp_path, backing)
    owed = _Telegram(polls_answered=1)
    before = build_composition(_settings(first), data_dir=tmp_path, transport=owed)
    point_the_keyring_at(before, backing)
    await before.engine.start()
    async with asyncio.timeout(10):
        while not (owed.sent and len(owed.polls) >= 2):  # noqa: ASYNC110 — the fake answers at once
            await asyncio.sleep(0.005)
    await before.engine.aclose()
    assert owed.polls[-1].get("offset") == 3, "A owes Telegram the confirmation through 2"

    fresh = _Telegram()
    after = build_composition(_settings(second), data_dir=tmp_path, transport=fresh)
    point_the_keyring_at(after, backing)
    await after.engine.start()
    async with asyncio.timeout(10):
        while not fresh.polls:  # noqa: ASYNC110 — the fake answers at once
            await asyncio.sleep(0.005)
    await after.engine.aclose()

    assert "offset" not in fresh.polls[0], "B's first poll confirms nothing of A's"
    assert telegram_intake_path(tmp_path, reference=first, chat_id=CHAT) != telegram_intake_path(
        tmp_path, reference=second, chat_id=CHAT
    )


# --- relayed mode (ADR-0330) -------------------------------------------------------

#: The relay credential the relay minted for this hub, connected as a connection of its
#: own (§6:4, §6:7): ``<16 hex>_<43 base64url>``, with no ``:``.
RELAY_CREDENTIAL: Final = "0123456789abcdef_Zm9vYmFyLXJlbGF5LXNlY3JldC1wYXJ0LW9mLWNyZWQtMA"
RELAY_SECRET_PART: Final = RELAY_CREDENTIAL.split("_", 1)[1]

#: What every hosted hub writes, and where it pins (§3:4).
RELAY_ORIGIN: Final = "https://telegram-relay:8443"
RELAY: Final = TransportEndpoint(host="telegram-relay", port=8443, implicit_tls=True)

#: A relay's CA certificate, as ``relay cert show`` prints it, its line breaks removed.
#: Minted for these cases with its private key discarded, so no relay presents it.
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


async def test_a_relayed_line_runs_through_the_root_to_the_relay_alone(tmp_path: Path) -> None:
    """The whole route in relayed mode: the relay's origin, the relay credential, no leak.

    The connect act stores the relay credential as the line's connection, the root
    builds the relayed client from the four settings, and the reader and the writer run
    unchanged against a relay that serves the Bot API faithfully (§4). Every channel is
    to the relay and none to Telegram (§3:2), the credential is in the token's place
    (§4:1), and no log line or record carries it (§6:6).
    """
    backing = Backing()
    reference = await _connected(tmp_path, backing, RELAY_CREDENTIAL)
    relay = _Telegram(endpoint=RELAY)
    settings = _settings(
        reference,
        telegram_relay_origin=RELAY_ORIGIN,
        telegram_relay_certificates=(RELAY_CA,),
    )
    composition = build_composition(settings, data_dir=tmp_path, transport=relay)
    point_the_keyring_at(composition, backing)
    reader = _reader(composition)
    assert repr(reader._client).endswith("mode='relayed')")

    with structlog.testing.capture_logs() as logs:
        await composition.engine.start()
        async with asyncio.timeout(10):
            while not (relay.sent and len(relay.targets()) >= 4):  # noqa: ASYNC110 — the fake answers at once
                await asyncio.sleep(0.005)
        exported = await reader._intake.export()
        await composition.engine.aclose()

    assert relay.sent == [NON_TEXT_LINE], "the user's photo answered, the stranger not"
    assert all(target.startswith(f"/bot{RELAY_CREDENTIAL}/") for target in relay.targets())
    rendered = json.dumps(logs, default=str) + exported.model_dump_json()
    assert RELAY_SECRET_PART not in rendered
    assert "/bot" not in rendered
