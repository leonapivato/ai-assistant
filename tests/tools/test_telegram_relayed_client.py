"""The production Telegram client in relayed mode, against a fake relay (ADR-0330 §12:6).

:class:`TestRelayedHttpsTelegramBotClientContract` binds
:class:`~ai_assistant.tools.egress.HttpsTelegramBotClient`, built with a
:class:`~ai_assistant.tools.egress.TelegramRelay`, to the whole shared suite and to its
relayed obligations, over **real TLS on the loopback**: the far end is
:mod:`telegram_relay_harness`'s relay, and the client reaches it through the production
:class:`~ai_assistant.tools.egress.StreamOutboundTransport` anchored on the relay's CA.
The rest are the arms §12:6 lists that only the production client can show:

- a certificate outside the configured set refused before any byte, **the system's
  authorities included** (§7:1);
- a matching certificate for another host refused (§7:5);
- a credential containing ``:`` refused before any byte (§6:3);
- the relay's refusals and silences classified as §4's table states;
- no call reaching ``https://api.telegram.org`` (§3:2);
- no relay credential in any log line, record or error (§6:6).

And the parts that build relayed mode: :class:`TrustAnchors`' loading and its refusals
(§3:8), :class:`TelegramRelay`'s canonical origin (§3:4), and the client's refusal of
anything but a :class:`TelegramRelay` for its relay.
"""

from __future__ import annotations

import json
import ssl
from typing import TYPE_CHECKING, Any, Final

import pytest
import structlog
from egress_transport_harness import Keyring, Records, entry, keyring
from telegram_bot_client_contract import (
    A_BOUND,
    A_WAIT,
    ATTEMPT,
    SHORT_BOUND,
    Prepared,
    Reached,
    RelayedTelegramBotClientContract,
)
from telegram_relay_harness import (
    RELAY_CREDENTIAL,
    RELAY_HOST,
    RELAY_SECRET_PART,
    FakeRelay,
    Presenting,
    RecordingTransport,
    SilentRelayTransport,
    bot_api,
    closed_port,
    done,
    fake_relay,
    minted,
    refused,
)

from ai_assistant.core.types import TelegramCallback, TelegramFailure, TelegramUpdate
from ai_assistant.testing import FakeOutboundTransport
from ai_assistant.testing.telegram import TELEGRAM_DIRECT_ORIGIN
from ai_assistant.tools.egress import (
    HttpsExchange,
    HttpsTelegramBotClient,
    StreamOutboundTransport,
    TelegramRelay,
    TelegramRelayError,
    TrustAnchorError,
    TrustAnchors,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = pytest.mark.anyio

#: The line's connection and the user's chat.
REFERENCE: Final = "conn-relay"
CHAT: Final = 424242

#: A bot token, which a relayed line must never hand a relay.
BOT_TOKEN: Final = "123456789:AAH-telegram_token_secret_part0"  # noqa: S105 — a test token

#: A read bound no ordinary answer reaches.
BOUND_BYTES: Final = 64 * 1024


def update_json(update: TelegramUpdate) -> dict[str, Any]:
    """An update carrying one text message, as the Bot API writes one."""
    raw: dict[str, Any] = {"update_id": update.update_id}
    if update.message is not None:
        message = update.message
        raw["message"] = {
            "message_id": message.message_id,
            "date": int(message.sent_at.timestamp()),
            "chat": {"id": message.chat_id, "type": "private"},
            "from": {"id": message.sender_id, "is_bot": False, "first_name": "O"},
            "text": message.text,
        }
        if message.command is not None:
            # The relay hands a message's entities unaltered (ADR-0332 §7:10).
            raw["message"]["entities"] = [
                {
                    "type": "bot_command",
                    "offset": 0,
                    "length": len(message.command.encode("utf-16-le")) // 2,
                }
            ]
    if update.callback is not None:
        raw["callback_query"] = callback_json(update.callback)
    return raw


def callback_json(callback: TelegramCallback) -> dict[str, Any]:
    """A button's callback as the Bot API writes one, which a relay hands on unaltered."""
    raw: dict[str, Any] = {
        "id": callback.callback_id,
        "from": {"id": callback.sender_id, "is_bot": callback.sender_is_bot, "first_name": "O"},
        "chat_instance": "-1",
    }
    if callback.message_id is not None:
        raw["message"] = {"message_id": callback.message_id, "date": 1_700_000_000}
        if callback.chat_id is not None:
            raw["message"]["chat"] = {
                "id": callback.chat_id,
                "type": "private" if callback.private_chat else "group",
            }
    if callback.data is not None:
        raw["data"] = callback.data
    return raw


def relay_of(origin: str, *certificates: str) -> TelegramRelay:
    """The relay a hub configured: ``origin``, trusted by ``certificates``."""
    configured = certificates or (minted().configured(),)
    return TelegramRelay(origin=origin, certificates=configured)


async def relayed(
    relay: FakeRelay | None,
    *,
    holds: str | None = RELAY_CREDENTIAL,
    records: Records | None = None,
    origin: str | None = None,
    certificates: tuple[str, ...] = (),
) -> tuple[HttpsTelegramBotClient, RecordingTransport]:
    """A relayed client reaching ``relay`` (or ``origin``) through the anchored transport.

    Args:
        relay: The fake relay, or ``None`` where ``origin`` names one nothing serves.
        holds: What the keyring holds in the connection's slot.
        records: The connection store; an active record by default.
        origin: The relay origin, where it is not ``relay``'s.
        certificates: The configured certificates; the relay's CA by default.

    Returns:
        The client and the transport recording what it reached for.
    """
    target = origin if origin is not None else (relay.origin if relay is not None else "")
    configuration = relay_of(target, *certificates)
    transport = RecordingTransport(StreamOutboundTransport(anchors=configuration.anchors))
    client = HttpsTelegramBotClient(
        reference=REFERENCE,
        chat_id=CHAT,
        records=records if records is not None else Records(entry()),
        secrets=await keyring(holds=holds),
        exchange=HttpsExchange(transport=transport, max_response_bytes=BOUND_BYTES),
        relay=configuration,
    )
    return client, transport


def prepared_over(
    client: HttpsTelegramBotClient, transport: RecordingTransport, relay: FakeRelay
) -> Prepared:
    """The suite's view: what reached the relay, and every origin reached for."""

    def reached() -> tuple[Reached, ...]:
        return tuple(Reached(one.method, dict(one.body)) for one in relay.requests)

    return Prepared(client=client, reached=reached, opened=transport.origins)


class TestRelayedHttpsTelegramBotClientContract(RelayedTelegramBotClientContract):
    """The production client in relayed mode, over real TLS to a fake relay."""

    relay: FakeRelay

    @pytest.fixture(autouse=True)
    def _relay(self) -> Iterator[None]:
        """One fake relay per case, presenting its own leaf until a hook says otherwise."""
        with fake_relay() as relay:
            self.relay = relay
            yield

    @pytest.fixture
    def client(self) -> HttpsTelegramBotClient:
        """A relayed client, constructed and never called."""
        return HttpsTelegramBotClient(
            reference=REFERENCE,
            chat_id=CHAT,
            records=Records(entry()),
            secrets=Keyring(),
            exchange=HttpsExchange(transport=FakeOutboundTransport(), max_response_bytes=1024),
            relay=relay_of("https://localhost:8443"),
        )

    def line_origin(self) -> str:
        """The fake relay's origin."""
        return self.relay.origin

    async def _prepared(self, **kwargs: Any) -> Prepared:
        client, transport = await relayed(self.relay, **kwargs)
        return prepared_over(client, transport, self.relay)

    async def accepting(self, *, message_id: int) -> Prepared:
        """The relay passes on Telegram's acceptance."""
        self.relay.answers["sendMessage"] = done(
            {"message_id": message_id, "chat": {"id": CHAT, "type": "private"}}
        )
        return await self._prepared()

    async def holding(self, *updates: TelegramUpdate) -> Prepared:
        """The relay hands back ``updates``."""
        self.relay.answers["getUpdates"] = done([update_json(update) for update in updates])
        return await self._prepared()

    async def rate_limiting(self, *, retry_after: int | None) -> Prepared:
        """The relay's own rate limit, before passing anything on."""
        self.relay.script.append(refused(429, retry_after=retry_after))
        return await self._prepared()

    async def refusing(self) -> Prepared:
        """Telegram's refusal, passed on unaltered."""
        self.relay.script.append(refused(400))
        return await self._prepared()

    async def failing_inside(self) -> Prepared:
        """Passed on, and no answer from Telegram: a server error (§4:12)."""
        self.relay.script.append(refused(500))
        return await self._prepared()

    async def unreachable(self) -> Prepared:
        """No relay listening where the origin points."""
        client, transport = await relayed(None, origin=f"https://{RELAY_HOST}:{closed_port()}")
        return prepared_over(client, transport, self.relay)

    async def garbled(self) -> Prepared:
        """An answer that is no Bot API answer at all."""
        self.relay.script.append(bot_api("not an object", status=502))
        return await self._prepared()

    async def silent(self) -> Prepared:
        """The relay takes the request and never answers.

        Over :class:`SilentRelayTransport` rather than real TLS, so the request is
        written before any bound can fall: whether a cut-off send is *unknown* turns on
        that order, and a handshake's duration is the machine's. The real relay's own
        stall is driven in the leak case below.
        """
        configuration = relay_of(self.relay.origin)
        transport = SilentRelayTransport()
        client = HttpsTelegramBotClient(
            reference=REFERENCE,
            chat_id=CHAT,
            records=Records(entry()),
            secrets=await keyring(holds=RELAY_CREDENTIAL),
            exchange=HttpsExchange(transport=transport, max_response_bytes=BOUND_BYTES),
            relay=configuration,
        )

        def reached() -> tuple[Reached, ...]:
            return tuple(Reached(one.method, dict(one.body)) for one in transport.requests())

        return Prepared(client=client, reached=reached, opened=transport.origins)

    async def disconnected(self) -> Prepared:
        """A connection whose record is a removal."""
        return await self._prepared(records=Records(entry(state=None)))

    async def holding_a_bot_token(self) -> Prepared:
        """The slot holds a bot token, not a relay credential."""
        return await self._prepared(holds=BOT_TOKEN)

    async def unanchored(self) -> Prepared:
        """The relay presents a stranger CA's leaf for its own name."""
        self.relay.present("stranger")
        return await self._prepared()

    async def misnamed(self) -> Prepared:
        """The relay presents its own CA's leaf, issued for another host."""
        self.relay.present("other-host")
        return await self._prepared()

    async def refusing_the_credential(self) -> Prepared:
        """The relay knows no such credential: ``401``."""
        self.relay.script.append(refused(401))
        return await self._prepared()


# --- §6: the relay credential in the token's place, and nowhere else ----------


async def test_the_relay_credential_is_the_target_and_reaches_only_the_relay() -> None:
    """``/bot<credential>/<method>`` at the relay, and in no body (§4:1, §6:6)."""
    with fake_relay() as relay:
        client, transport = await relayed(relay)

        outcome = await client.send(attempt=ATTEMPT, chat_id=CHAT, text="hi", timeout=A_BOUND)

    assert outcome.done
    (request,) = relay.requests
    assert request.method == "sendMessage"
    assert request.credential == RELAY_CREDENTIAL
    assert RELAY_SECRET_PART not in json.dumps(request.body)
    assert transport.origins() == (relay.origin,)


@pytest.mark.parametrize(
    "holds",
    [BOT_TOKEN, "abc:def", ":", "0123456789abcdef_with/slash", "spaced credential"],
    ids=["bot-token", "any-colon", "only-a-colon", "slash", "space"],
)
async def test_a_credential_a_relay_is_never_handed_opens_nothing(holds: str) -> None:
    """Refused before the channel exists, so not a byte — and not the TCP open (§6:3)."""
    with fake_relay() as relay:
        client, transport = await relayed(relay, holds=holds)

        with structlog.testing.capture_logs() as logs:
            outcome = await client.send(attempt=ATTEMPT, chat_id=CHAT, text="hi", timeout=A_BOUND)

    assert outcome.failure is TelegramFailure.UNAVAILABLE
    assert transport.endpoints == []
    assert relay.requests == []
    reasons = [line.get("reason") for line in logs if line["event"] == "telegram_line_unavailable"]
    expected = "bot_token_on_a_relayed_line" if ":" in holds else "token_unwritable"
    assert reasons == [expected]


async def test_a_direct_line_still_takes_a_bot_token() -> None:
    """The colon rule is relayed mode's alone: direct mode is ADR-0323's line (§3:1)."""
    transport = FakeOutboundTransport().serve()
    client = HttpsTelegramBotClient(
        reference=REFERENCE,
        chat_id=CHAT,
        records=Records(entry()),
        secrets=await keyring(holds=BOT_TOKEN),
        exchange=HttpsExchange(transport=transport, max_response_bytes=1024),
    )

    await client.show_typing(attempt=ATTEMPT, chat_id=CHAT, timeout=A_BOUND)

    assert [attempt.endpoint.host for attempt in transport.attempts] == ["api.telegram.org"]


async def test_no_log_line_outcome_error_or_repr_carries_the_relay_credential() -> None:
    """§6:6 over every outcome a relayed call can have, done and failed alike."""
    rendered = ""
    with structlog.testing.capture_logs() as logs:
        for script in (
            None,
            refused(429, retry_after=2),
            refused(401),
            refused(400),
            refused(500),
            "close",
            "stall",
            bot_api([1], status=200),
        ):
            with fake_relay() as relay:
                if script is not None:
                    relay.script.append(script)
                client, _ = await relayed(relay)
                outcome = await client.send(
                    attempt=ATTEMPT, chat_id=CHAT, text="hi", timeout=SHORT_BOUND * 10
                )
                rendered += outcome.model_dump_json() + repr(client)
        presentings: tuple[Presenting, ...] = ("stranger", "other-host")
        for presenting in presentings:
            with fake_relay(presenting=presenting) as relay:
                client, _ = await relayed(relay)
                polled = await client.poll(
                    attempt=ATTEMPT, offset=None, wait=A_WAIT, timeout=A_BOUND
                )
                rendered += polled.model_dump_json()

    rendered += json.dumps(logs, default=str)
    assert logs, "the client logs every call"
    assert RELAY_SECRET_PART not in rendered
    assert "/bot" not in rendered


# --- §4's table: the relay's refusals and silences ---------------------------


@pytest.mark.parametrize(
    ("answer", "failure", "retryable"),
    [
        (refused(429, retry_after=4), TelegramFailure.RATE_LIMITED, True),
        (refused(400), TelegramFailure.REFUSED, False),
        (refused(403), TelegramFailure.REFUSED, False),
        (refused(401), TelegramFailure.REFUSED, False),
        (refused(500), TelegramFailure.UNKNOWN, False),
        (refused(502), TelegramFailure.UNKNOWN, False),
        ("close", TelegramFailure.UNKNOWN, False),
    ],
    ids=[
        "own-rate-limit",
        "telegram-refused",
        "telegram-blocked",
        "unknown-credential",
        "passed-on-no-answer",
        "bad-gateway",
        "closed-unanswered",
    ],
)
async def test_the_relays_answers_are_classed_as_its_table_says(
    answer: bytes | str, failure: TelegramFailure, retryable: bool
) -> None:
    """ADR-0330 §4's table, row by row, through real TLS."""
    with fake_relay() as relay:
        relay.script.append(answer)  # type: ignore[arg-type]
        client, _ = await relayed(relay)

        outcome = await client.send(attempt=ATTEMPT, chat_id=CHAT, text="hi", timeout=A_BOUND)

    assert outcome.failure is failure
    assert outcome.failure.retryable is retryable
    assert len(relay.requests) == 1, "sent once, never repeated by the client"


async def test_another_chat_is_refused_by_the_hub_before_the_relay_hears_of_it() -> None:
    """The hub's own other-chat check comes first (§5:3, §4's table)."""
    with fake_relay() as relay:
        client, transport = await relayed(relay)

        outcome = await client.send(attempt=ATTEMPT, chat_id=CHAT + 1, text="hi", timeout=A_BOUND)

    assert outcome.failure is TelegramFailure.OTHER_CHAT
    assert transport.endpoints == []


# --- §7: the hub authenticates the relay, by the configured set alone ----------


async def test_the_systems_authorities_are_not_trusted_for_the_relay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Even a relay whose CA is in the system store does not verify (§7:1).

    ``SSL_CERT_FILE`` makes the relay's own CA the process's system trust store, as the
    answering-origin harness does for a direct integration. A line anchored on another
    certificate is refused all the same: the system store is not consulted.
    """
    material = minted()
    ca_file = material.directory / "system-store.pem"
    ca_file.write_text(material.ca_pem, encoding="ascii")
    monkeypatch.setenv("SSL_CERT_FILE", str(ca_file))
    with fake_relay() as relay:
        client, _ = await relayed(
            relay, certificates=(material.configured(material.stranger_ca_pem),)
        )

        outcome = await client.send(attempt=ATTEMPT, chat_id=CHAT, text="hi", timeout=A_BOUND)

    assert outcome.failure is TelegramFailure.NOT_WRITTEN
    assert relay.requests == []


async def test_any_configured_certificate_verifies_the_relay() -> None:
    """A set, so rotation can add the new CA beside the old one (§3:9)."""
    material = minted()
    with fake_relay() as relay:
        client, _ = await relayed(
            relay,
            certificates=(material.configured(material.stranger_ca_pem), material.configured()),
        )

        outcome = await client.show_typing(attempt=ATTEMPT, chat_id=CHAT, timeout=A_BOUND)

    assert outcome.done


async def test_a_relay_below_tls_1_3_is_refused() -> None:
    """The relayed channel is TLS 1.3, which the relay speaks: nothing older is admitted."""
    with fake_relay(tls_ceiling=ssl.TLSVersion.TLSv1_2) as relay:
        client, _ = await relayed(relay)

        outcome = await client.send(attempt=ATTEMPT, chat_id=CHAT, text="hi", timeout=A_BOUND)

    assert outcome.failure is TelegramFailure.NOT_WRITTEN
    assert relay.requests == []


def test_an_anchored_context_holds_the_configured_certificates_and_no_others() -> None:
    """No default verify paths: the store is exactly the set (§7:1, §7:3)."""
    material = minted()
    anchors = TrustAnchors((material.configured(), material.configured(material.stranger_ca_pem)))

    context = anchors.context()

    assert context.cert_store_stats()["x509_ca"] == 2
    assert len(context.get_ca_certs()) == 2
    assert context.check_hostname is True
    assert context.verify_mode is ssl.CERT_REQUIRED
    assert context.minimum_version is ssl.TLSVersion.TLSv1_3
    assert anchors.context() is not context, "a fresh context per channel"


@pytest.mark.parametrize(
    "certificates",
    [(), ("not base64!",), ("AAAA",), ("",)],
    ids=["none", "not-base64", "not-a-certificate", "empty"],
)
def test_a_certificate_that_will_not_load_is_refused_at_construction(
    certificates: tuple[str, ...],
) -> None:
    """§3:8: refused before any call, naming the position and never the text."""
    with pytest.raises(TrustAnchorError) as refusal:
        TrustAnchors(certificates)

    for text in certificates:
        if text:
            assert text not in str(refusal.value)


def test_the_anchors_cannot_be_changed_through_the_transport() -> None:
    """No member supplies or changes them (§7:3): the transport's one slot is private."""
    transport = StreamOutboundTransport(anchors=TrustAnchors((minted().configured(),)))

    with pytest.raises(AttributeError):
        transport.anchors = None  # type: ignore[attr-defined]  # the point of the case
    assert not hasattr(transport, "open")


# --- §3:4: the origin, canonical and only the configured one --------------------


@pytest.mark.parametrize(
    ("origin", "canonical"),
    [
        ("https://telegram-relay:8443", "https://telegram-relay:8443"),
        ("HTTPS://Telegram-Relay:8443", "https://telegram-relay:8443"),
        ("https://telegram-relay", "https://telegram-relay:443"),
    ],
    ids=["the-box", "case-folded", "default-port"],
)
def test_the_relay_origin_is_canonicalised_by_the_seam(origin: str, canonical: str) -> None:
    """A single-label host with a port canonicalises; its canonical form is the origin."""
    assert relay_of(origin).origin == canonical


@pytest.mark.parametrize(
    "origin",
    [
        "https://10.254.0.1:8443",
        "https://[::1]:8443",
        "https://telegram-relay:8443/",
        "https://telegram-relay:8443/bot",
        "http://telegram-relay:8443",
        "https://user@telegram-relay:8443",
        "telegram-relay:8443",
    ],
    ids=["ipv4-literal", "ipv6-literal", "trailing-slash", "path", "cleartext", "userinfo", "bare"],
)
def test_an_origin_the_seam_will_not_pin_is_refused(origin: str) -> None:
    """IP literals, paths and cleartext stay refused (§3:4, §8:3)."""
    with pytest.raises(TelegramRelayError, match="telegram_relay_origin"):
        relay_of(origin)


def test_a_relay_whose_certificates_will_not_load_is_refused() -> None:
    """Named by the setting, so the start diagnostic says which to fix (§3:8)."""
    with pytest.raises(TelegramRelayError, match="telegram_relay_certificates"):
        TelegramRelay(origin="https://telegram-relay:8443", certificates=("AAAA",))


def test_a_client_takes_a_relay_or_nothing() -> None:
    """The mode is the client's construction, and nothing else selects it (§3:3)."""
    with pytest.raises(ValueError, match="relay"):
        HttpsTelegramBotClient(
            reference=REFERENCE,
            chat_id=CHAT,
            records=Records(entry()),
            secrets=Keyring(),
            exchange=HttpsExchange(transport=FakeOutboundTransport(), max_response_bytes=1024),
            relay="https://telegram-relay:8443",  # type: ignore[arg-type]  # the point of the case
        )


def test_the_clients_repr_names_its_mode_and_no_credential() -> None:
    """Mode and connection, never a target."""
    client = HttpsTelegramBotClient(
        reference=REFERENCE,
        chat_id=CHAT,
        records=Records(entry()),
        secrets=Keyring(),
        exchange=HttpsExchange(transport=FakeOutboundTransport(), max_response_bytes=1024),
        relay=relay_of("https://telegram-relay:8443"),
    )

    assert repr(client) == f"HttpsTelegramBotClient(reference={REFERENCE!r}, mode='relayed')"


def test_telegrams_own_origin_is_still_fixed_in_code() -> None:
    """Direct mode's origin is unchanged, and differs from every relay's (§3:1)."""
    assert TELEGRAM_DIRECT_ORIGIN == "https://api.telegram.org:443"
    assert TELEGRAM_DIRECT_ORIGIN not in {
        relay_of(origin).origin for origin in ("https://telegram-relay:8443", "https://localhost")
    }
