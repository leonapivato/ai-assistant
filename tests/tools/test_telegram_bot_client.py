"""The production Telegram client, against a fake Telegram (ADR-0323 §11, §13, §15:5).

Two halves. :class:`TestHttpsTelegramBotClientContract` binds
:class:`~ai_assistant.tools.egress.HttpsTelegramBotClient` to the shared suite, its far
end a scripted channel under :class:`~ai_assistant.testing.FakeOutboundTransport`. The
rest are the arms only the production client has, each a row of §11 or of §15:5's list:
the token's read order and its absence from every log, record, error and ``repr``; the
one origin and the refused redirect; the read bound; one channel per call; the record
re-read before any byte; the POST's framing; and how a Bot API answer is read.

**Nothing here opens a socket or reaches Telegram.** The client takes the exchange,
and the exchange takes the transport, as required arguments with no default, so a case
that forgot one would not construct rather than reaching the network.
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, final

import pytest
import structlog
from egress_transport_harness import SLOT, Keyring, Records, entry, keyring
from telegram_bot_client_contract import (
    A_BOUND,
    A_WAIT,
    ATTEMPT,
    SHORT_BOUND,
    Prepared,
    Reached,
    TelegramBotClientContract,
)

from ai_assistant.core.errors import ConnectionStoreError, TransportError
from ai_assistant.core.types import (
    ProvisioningState,
    TelegramCallback,
    TelegramFailure,
    TelegramForwardKind,
    TelegramForwardOrigin,
    TelegramMessage,
    TelegramQuotedMessage,
    TelegramUpdate,
    TransportEndpoint,
)
from ai_assistant.testing import FakeByteChannel, FakeOutboundTransport
from ai_assistant.tools.egress import (
    TELEGRAM_BOT_API_ORIGIN,
    HttpsExchange,
    HttpsTelegramBotClient,
    TransportPinError,
)

if TYPE_CHECKING:
    from ai_assistant.core.protocols import ByteChannel
    from ai_assistant.testing.cancellation import LoopSuspension

pytestmark = pytest.mark.anyio

#: The bot's token, as BotFather mints one. Every leak case searches for it, and for
#: the half after the colon, which is the secret part.
TOKEN: Final = "123456789:AAH-telegram_token_secret_part0"  # noqa: S105 — a test token
SECRET_PART: Final = TOKEN.split(":", 1)[1]

#: The line's connection, the harness's own reference, and the owner's chat.
REFERENCE: Final = "conn-0001"
CHAT: Final = 424242

#: The endpoint the one origin pins to.
TELEGRAM_ENDPOINT: Final = TransportEndpoint(host="api.telegram.org", port=443, implicit_tls=True)

#: A read bound no ordinary answer reaches.
BOUND_BYTES: Final = 64 * 1024


def http(status: int, body: bytes, *, reason: str = "OK", fields: tuple[str, ...] = ()) -> bytes:
    """One HTTP/1.1 response, framed by a content length.

    Args:
        status: The status code.
        body: The payload.
        reason: The reason phrase.
        fields: Further header lines.

    Returns:
        The response's octets.
    """
    head = [f"HTTP/1.1 {status} {reason}", *fields, f"Content-Length: {len(body)}", "", ""]
    return "\r\n".join(head).encode("ascii") + body


def answer(payload: object, *, status: int = 200) -> bytes:
    """A Bot API answer: its JSON, in a response.

    Args:
        payload: The JSON object.
        status: The status Telegram puts it under.

    Returns:
        The response's octets.
    """
    return http(
        status, json.dumps(payload).encode("utf-8"), fields=("Content-Type: application/json",)
    )


def done(result: object) -> bytes:
    """``{"ok": true, "result": ...}``."""
    return answer({"ok": True, "result": result})


def refused(code: int, *, retry_after: int | None = None) -> bytes:
    """``{"ok": false, "error_code": ...}``, with a rate limit's wait where given."""
    payload: dict[str, object] = {"ok": False, "error_code": code, "description": "nope"}
    if retry_after is not None:
        payload["parameters"] = {"retry_after": retry_after}
    return answer(payload, status=code)


def message_json(message: TelegramMessage) -> dict[str, Any]:
    """A message as the Bot API writes one, for :func:`update_json`."""
    raw: dict[str, Any] = {
        "message_id": message.message_id,
        "date": int(message.sent_at.timestamp()),
        "chat": {"id": message.chat_id, "type": "private" if message.private_chat else "group"},
    }
    if message.sender_id is not None:
        raw["from"] = {"id": message.sender_id, "is_bot": message.sender_is_bot, "first_name": "O"}
    if message.text is not None:
        raw["text"] = message.text
    if message.command is not None:
        raw["entities"] = [command_entity(message.command)]
    return raw


def command_entity(command: str) -> dict[str, Any]:
    """The ``bot_command`` entity Telegram marks ``command`` with, at the first character.

    Its length counts UTF-16 code units, as the Bot API counts them (ADR-0332 §7:9).
    """
    return {"type": "bot_command", "offset": 0, "length": len(command.encode("utf-16-le")) // 2}


def update_json(update: TelegramUpdate) -> dict[str, Any]:
    """An update as the Bot API writes one."""
    raw: dict[str, Any] = {"update_id": update.update_id}
    if update.message is not None:
        raw["message"] = message_json(update.message)
    if update.callback is not None:
        raw["callback_query"] = callback_json(update.callback)
    return raw


def callback_json(callback: TelegramCallback) -> dict[str, Any]:
    """A button's callback as the Bot API writes one (ADR-0361 §4:7)."""
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


@final
class SilentChannel:
    """A secure channel that records what is written and never answers.

    The one state :class:`FakeByteChannel` cannot model: it can end a stream and be
    armed to raise, but it cannot hang, and an expiry after the write needs one.
    """

    def __init__(self) -> None:
        """Open it, secure and unwritten."""
        self.written = bytearray()
        self.closed = False

    @property
    def is_secure(self) -> bool:
        """Always under TLS."""
        return True

    async def read_line(self) -> bytes:
        """Never answer."""
        await asyncio.Event().wait()
        return b""  # pragma: no cover — the wait never ends

    async def read(self, limit: int, /) -> bytes:
        """Never answer."""
        await asyncio.Event().wait()
        return b""  # pragma: no cover — the wait never ends

    async def write(self, data: bytes, /) -> None:
        """Record the octets."""
        self.written += data

    async def start_tls(self) -> None:
        """Nothing to upgrade."""

    async def close(self) -> None:
        """Release it."""
        self.closed = True


@final
class SilentTransport:
    """An outbound transport whose every channel is a :class:`SilentChannel`."""

    def __init__(self) -> None:
        """Start with nothing opened."""
        self.channels: list[SilentChannel] = []
        self.endpoints: list[TransportEndpoint] = []

    async def open_channel(self, endpoint: TransportEndpoint) -> ByteChannel:
        """Open a silent channel to ``endpoint``."""
        self.endpoints.append(endpoint)
        channel = SilentChannel()
        self.channels.append(channel)
        return channel


@final
class AnsweringChannel:
    """A secure channel whose far end answers by the method the request named.

    A fake Telegram for the cases that make more than one kind of call on one client:
    the scripted :class:`FakeByteChannel` answers what it was given, whatever was
    asked, and a typing indicator answered with a send's result is not what Telegram
    does.
    """

    def __init__(self, answers: dict[str, bytes], *, stall: float = 0.0) -> None:
        """Open it, secure, answering each method with ``answers[method]``.

        Args:
            answers: The answer per method.
            stall: Seconds the write holds the loop **synchronously**, never yielding:
                work no cancellation can land in, as decoding a large answer is.
        """
        self._answers = answers
        self._stall = stall
        self._inbound = bytearray()
        self.written = bytearray()
        self.closed = False

    @property
    def is_secure(self) -> bool:
        """Always under TLS."""
        return True

    async def read_line(self) -> bytes:  # pragma: no cover — the exchange reads by `read`
        """Not used by the exchange."""
        raise NotImplementedError

    async def read(self, limit: int, /) -> bytes:
        """Serve the answer chosen when the request was written."""
        taken = bytes(self._inbound[:limit])
        del self._inbound[:limit]
        return taken

    async def write(self, data: bytes, /) -> None:
        """Record the request, and choose its answer by its method."""
        self.written += data
        time.sleep(self._stall)  # noqa: ASYNC251 — blocking the loop is the point
        target = bytes(self.written).split(b" ", 2)[1].decode("ascii")
        self._inbound += self._answers[target.rsplit("/", 1)[1]]

    async def start_tls(self) -> None:
        """Nothing to upgrade."""

    async def close(self) -> None:
        """Release it."""
        self.closed = True


@final
class AnsweringTransport:
    """An outbound transport whose every channel is an :class:`AnsweringChannel`."""

    def __init__(self, answers: dict[str, bytes], *, stall: float = 0.0) -> None:
        """Answer every call by its method, after ``stall`` seconds of blocked loop."""
        self._answers = answers
        self._stall = stall
        self.channels: list[AnsweringChannel] = []
        self.endpoints: list[TransportEndpoint] = []

    async def open_channel(self, endpoint: TransportEndpoint) -> ByteChannel:
        """Open an answering channel; the endpoint is the client's one origin."""
        self.endpoints.append(endpoint)
        assert endpoint == TELEGRAM_ENDPOINT
        channel = AnsweringChannel(self._answers, stall=self._stall)
        self.channels.append(channel)
        return channel


@final
class Harness:
    """A production client over a scripted Telegram, and what it was asked."""

    def __init__(
        self,
        *,
        client: HttpsTelegramBotClient,
        transport: FakeOutboundTransport | SilentTransport | AnsweringTransport,
        records: Records,
        ring: Keyring,
    ) -> None:
        """Hold the parts a case reads back."""
        self.client = client
        self.transport = transport
        self.records = records
        self.ring = ring

    def scripted(self) -> FakeOutboundTransport:
        """The canonical fake transport, for the cases that read its attempts."""
        assert isinstance(self.transport, FakeOutboundTransport)
        return self.transport

    def written(self) -> list[bytes]:
        """Every request written, one per channel that carried octets."""
        return [bytes(channel.written) for channel in self.transport.channels if channel.written]

    def reached(self) -> tuple[Reached, ...]:
        """Every request that reached Telegram, as its method and decoded body."""
        reached: list[Reached] = []
        for request in self.written():
            head, _, body = request.partition(b"\r\n\r\n")
            target = head.split(b"\r\n", 1)[0].split(b" ")[1].decode("ascii")
            reached.append(Reached(target.rsplit("/", 1)[1], json.loads(body)))
        return tuple(reached)

    def opened(self) -> tuple[str, ...]:
        """The origin of every channel the client opened or tried to, canonical."""
        if isinstance(self.transport, FakeOutboundTransport):
            endpoints = [attempt.endpoint for attempt in self.transport.attempts]
        else:
            endpoints = list(self.transport.endpoints)
        return tuple(f"https://{one.host}:{one.port}" for one in endpoints)

    def prepared(self) -> Prepared:
        """The harness as the suite takes it."""
        return Prepared(client=self.client, reached=self.reached, opened=self.opened)


async def harness(
    *answers: bytes,
    records: Records | None = None,
    holds: str | None = TOKEN,
    transport: FakeOutboundTransport | SilentTransport | AnsweringTransport | None = None,
    bound: int = BOUND_BYTES,
) -> Harness:
    """A production client whose Telegram answers each call with the next of ``answers``.

    Args:
        answers: One response per call, in order.
        records: The connection store; an active record naming :data:`SLOT` by default.
        holds: What the keyring holds under the slot.
        transport: A transport of the case's own, in place of the scripted one.
        bound: The read bound.

    Returns:
        The harness.
    """
    if transport is None:
        transport = FakeOutboundTransport().serve(
            *(FakeByteChannel(secure=True).deliver(octets) for octets in answers)
        )
    ring = await keyring(holds=holds)
    store = records if records is not None else Records(entry())
    client = HttpsTelegramBotClient(
        reference=REFERENCE,
        chat_id=CHAT,
        records=store,
        secrets=ring,
        exchange=HttpsExchange(transport=transport, max_response_bytes=bound),
    )
    return Harness(client=client, transport=transport, records=store, ring=ring)


class TestHttpsTelegramBotClientContract(TelegramBotClientContract):
    """Binds the production client to the shared suite."""

    @pytest.fixture
    def client(self) -> HttpsTelegramBotClient:
        """A client over a transport that serves nothing."""
        return HttpsTelegramBotClient(
            reference=REFERENCE,
            chat_id=CHAT,
            records=Records(entry()),
            secrets=Keyring(),
            exchange=HttpsExchange(transport=FakeOutboundTransport(), max_response_bytes=1024),
        )

    async def accepting(self, *, message_id: int) -> Prepared:
        """Telegram accepts: a message with ``message_id``, ``true``, or no updates."""
        sent = done({"message_id": message_id, "chat": {"id": CHAT, "type": "private"}})
        telegram = AnsweringTransport(
            {
                "sendMessage": sent,
                "sendChatAction": done(True),
                "getUpdates": done([]),
                "editMessageText": sent,
                "answerCallbackQuery": done(True),
            }
        )
        return (await harness(transport=telegram)).prepared()

    async def holding(self, *updates: TelegramUpdate) -> Prepared:
        """Telegram answers the poll with ``updates``."""
        return (await harness(done([update_json(update) for update in updates]))).prepared()

    async def rate_limiting(self, *, retry_after: int | None) -> Prepared:
        """Telegram answers ``429``."""
        return (await harness(refused(429, retry_after=retry_after))).prepared()

    async def refusing(self) -> Prepared:
        """Telegram answers ``400``."""
        return (await harness(refused(400))).prepared()

    async def failing_inside(self) -> Prepared:
        """Telegram answers ``500`` in the Bot API's own shape."""
        return (await harness(refused(500))).prepared()

    async def unreachable(self) -> Prepared:
        """The channel never opens."""
        transport = FakeOutboundTransport()
        transport.refuse_with(TransportError("connection refused"))
        return (await harness(transport=transport)).prepared()

    async def garbled(self) -> Prepared:
        """A front end's error page, which is no Bot API answer."""
        return (
            await harness(http(502, b"<html>bad gateway</html>", reason="Bad Gateway"))
        ).prepared()

    async def silent(self) -> Prepared:
        """A far end that never answers."""
        return (await harness(transport=SilentTransport())).prepared()

    async def disconnected(self) -> Prepared:
        """A connection whose record is a removal."""
        return (await harness(records=Records(entry(state=None)))).prepared()


# --- §11:4: the token, read after the record and under it ----------------------


async def test_the_token_is_read_once_between_two_record_reads() -> None:
    """Record, token, record again: ADR-0148 §6's order on the line's route (§11:4)."""
    rig = await harness(done(True))

    await rig.client.show_typing(attempt=ATTEMPT, chat_id=CHAT, timeout=A_BOUND)

    assert rig.records.reads == [REFERENCE, REFERENCE]
    assert rig.ring.reads == [SLOT]


async def test_another_chat_reads_no_record_and_no_token() -> None:
    """The chat is refused before the token is read (§11:4, §6:1)."""
    rig = await harness(done(True))

    await rig.client.send(attempt=ATTEMPT, chat_id=CHAT + 1, text="hi", timeout=A_BOUND)

    assert rig.records.reads == []
    assert rig.ring.reads == []
    assert rig.scripted().attempts == ()


@pytest.mark.parametrize(
    ("records", "holds"),
    [
        (Records(None), TOKEN),
        (Records(entry(state=ProvisioningState.PENDING)), TOKEN),
        (Records(entry(slot=None)), TOKEN),
        (Records(entry(), entry(revision=2)), TOKEN),
        (Records(entry(), entry(identity="someone-else")), TOKEN),
        (Records(entry(), entry(state=None)), TOKEN),
        (Records(entry(), ConnectionStoreError("store gone")), TOKEN),
        (Records(ConnectionStoreError("store gone")), TOKEN),
        (Records(entry()), None),
        (Records(entry()), "123:abc/../getMe?x=1"),
        (Records(entry()), "123:abc def"),
    ],
    ids=[
        "no-record",
        "not-active",
        "keyless-record",
        "revision-moved",
        "identity-moved",
        "removed-across-the-read",
        "reread-unanswerable",
        "first-read-fails",
        "keyring-empty",
        "token-would-reshape-the-path",
        "token-with-a-space",
    ],
)
async def test_a_line_that_cannot_be_used_opens_no_channel(
    records: Records, holds: str | None
) -> None:
    """Unavailable is decided before any channel exists (§11:4)."""
    rig = await harness(done(True), records=records, holds=holds)

    outcome = await rig.client.show_typing(attempt=ATTEMPT, chat_id=CHAT, timeout=A_BOUND)

    assert outcome.failure is TelegramFailure.UNAVAILABLE
    assert rig.scripted().attempts == ()


# --- §11:8 to §11:9: the token in the path, and nowhere else -----------------


async def test_the_token_is_bound_into_the_target_and_nowhere_else_on_the_wire() -> None:
    """The target is ``/bot<token>/<method>``, and the body carries no token (§11:8)."""
    rig = await harness(done({"message_id": 9}))

    await rig.client.send(attempt=ATTEMPT, chat_id=CHAT, text="hi", timeout=A_BOUND)

    (request,) = rig.written()
    head, _, body = request.partition(b"\r\n\r\n")
    assert head.split(b"\r\n", 1)[0] == f"POST /bot{TOKEN}/sendMessage HTTP/1.1".encode("ascii")
    assert request.count(SECRET_PART.encode("ascii")) == 1
    assert SECRET_PART.encode("ascii") not in body


async def _every_path(rig_for: Any) -> list[tuple[str, object]]:
    """Drive the client down every outcome, returning what each produced."""
    produced: list[tuple[str, object]] = []
    for name, rig in rig_for.items():
        harnessed = await rig
        outcome = await harnessed.client.send(
            attempt=ATTEMPT, chat_id=CHAT, text="hi", timeout=SHORT_BOUND
        )
        produced.append((name, outcome))
        produced.append((f"{name}-repr", repr(harnessed.client)))
    return produced


async def test_no_log_line_outcome_or_repr_carries_the_token() -> None:
    """§11:9, over every outcome the client can produce, done and failed alike."""
    unreachable = FakeOutboundTransport()
    unreachable.refuse_with(TransportError("connection refused"))
    rigs = {
        "done": harness(done({"message_id": 1})),
        "rate-limited": harness(refused(429, retry_after=3)),
        "refused": harness(refused(401)),
        "server-error": harness(refused(500)),
        "garbled": harness(http(502, b"x")),
        "redirect": harness(
            http(302, b"", reason="Found", fields=("Location: https://x.invalid/",))
        ),
        "too-large": harness(done({"message_id": 1}), bound=16),
        "unreachable": harness(transport=unreachable),
        "silent": harness(transport=SilentTransport()),
        "record-moved": harness(records=Records(entry(), entry(revision=2))),
    }

    with structlog.testing.capture_logs() as logs:
        produced = await _every_path(rigs)

    rendered = json.dumps(logs, default=str) + repr(produced)
    for _, value in produced:
        if hasattr(value, "model_dump_json"):
            rendered += value.model_dump_json()
    assert logs, "the client logs every call"
    assert SECRET_PART not in rendered
    assert "/bot" not in rendered


async def test_a_refused_request_names_no_token_in_its_error() -> None:
    """The exchange's own refusal of a target never renders it (§11:9)."""
    exchange = HttpsExchange(transport=FakeOutboundTransport(), max_response_bytes=1024)

    with pytest.raises(TransportPinError) as refused_error:
        await exchange.post_json(
            origin=TELEGRAM_BOT_API_ORIGIN, target=f"/bot{SECRET_PART} x/getMe", payload={}
        )

    assert SECRET_PART not in str(refused_error.value)


# --- §11:5 and §11:14: one origin, no redirect, a channel per call -----------


async def test_every_call_opens_its_own_channel_to_the_one_origin() -> None:
    """One origin fixed in code, implicit TLS, a channel per call (§11:5, §11:14)."""
    rig = await harness(done(True), done(True))

    await rig.client.show_typing(attempt=ATTEMPT, chat_id=CHAT, timeout=A_BOUND)
    await rig.client.show_typing(attempt=ATTEMPT, chat_id=CHAT, timeout=A_BOUND)

    assert TELEGRAM_BOT_API_ORIGIN == "https://api.telegram.org"
    assert [attempt.endpoint for attempt in rig.scripted().attempts] == [TELEGRAM_ENDPOINT] * 2
    assert all(channel.closed for channel in rig.transport.channels)
    assert rig.scripted().open_sockets == 0


async def test_a_redirect_is_followed_nowhere_and_is_unknown() -> None:
    """A ``3xx`` is a refusal, never a second request (§11:5); the send may have gone."""
    rig = await harness(http(302, b"", reason="Found", fields=("Location: https://x.invalid/",)))

    outcome = await rig.client.send(attempt=ATTEMPT, chat_id=CHAT, text="hi", timeout=A_BOUND)

    assert outcome.failure is TelegramFailure.UNKNOWN
    assert len(rig.scripted().attempts) == 1


async def test_a_response_past_the_read_bound_is_abandoned_as_unknown() -> None:
    """§11:13: refused beyond the bound, never truncated into an answer."""
    rig = await harness(done({"message_id": 1, "text": "x" * 512}), bound=128)

    outcome = await rig.client.send(attempt=ATTEMPT, chat_id=CHAT, text="hi", timeout=A_BOUND)

    assert outcome.failure is TelegramFailure.UNKNOWN
    assert rig.transport.channels[0].closed


async def test_a_write_that_fails_part_way_is_unknown() -> None:
    """The octets may be on the wire, so the send may have gone (§6:4)."""
    channel = FakeByteChannel(secure=True)
    channel.fail_write_after(b"", error=TransportError("reset"))
    rig = await harness(transport=FakeOutboundTransport().serve(channel))

    outcome = await rig.client.send(attempt=ATTEMPT, chat_id=CHAT, text="hi", timeout=A_BOUND)

    assert outcome.failure is TelegramFailure.UNKNOWN
    assert channel.closed


async def _past_the_bound[T](gate: LoopSuspension, call: asyncio.Future[T]) -> T:
    """Hold an open past the call's bound, then let it go, and return the outcome.

    The suspension survives its own cancellation until released, as a socket that is
    still being acquired does, so the bound fires inside it and the release is what
    lets the cancellation land.
    """
    async with asyncio.timeout(5):
        await gate.reached()
        await asyncio.sleep(SHORT_BOUND.total_seconds() * 2)
        gate.release()
        return await call


async def test_a_bound_reached_before_the_write_is_not_written() -> None:
    """A send whose channel never opened in time was never written (§6:3)."""
    transport = FakeOutboundTransport()
    gate = transport.suspend_next_open()
    rig = await harness(transport=transport)

    call = asyncio.ensure_future(
        rig.client.send(attempt=ATTEMPT, chat_id=CHAT, text="hi", timeout=SHORT_BOUND)
    )
    outcome = await _past_the_bound(gate, call)

    assert outcome.failure is TelegramFailure.NOT_WRITTEN
    assert transport.open_sockets == 0


async def test_a_poll_reaching_its_bound_before_the_write_is_still_unknown() -> None:
    """§11:11 makes a poll at its bound unknown, whatever it had written."""
    transport = FakeOutboundTransport()
    gate = transport.suspend_next_open()
    rig = await harness(transport=transport)

    call = asyncio.ensure_future(
        rig.client.poll(attempt=ATTEMPT, offset=None, wait=timedelta(0), timeout=SHORT_BOUND)
    )
    outcome = await _past_the_bound(gate, call)

    assert outcome.failure is TelegramFailure.UNKNOWN


@pytest.mark.parametrize("method", ["poll", "send"])
async def test_work_that_overruns_the_bound_without_yielding_is_past_it(method: str) -> None:
    """The bound covers the whole call (§11:10), work no cancellation can land in too.

    The far end answers at once, and in full, but only after holding the loop past
    the bound: a timer cannot fire inside synchronous work, so ``Timeout.expired()``
    alone would call this call kept within its bound.
    """
    telegram = AnsweringTransport(
        {
            "getUpdates": done([update_json(TelegramUpdate(update_id=1))]),
            "sendMessage": done({"message_id": 4}),
        },
        stall=SHORT_BOUND.total_seconds() * 3,
    )
    rig = await harness(transport=telegram)

    if method == "poll":
        polled = await rig.client.poll(
            attempt=ATTEMPT, offset=None, wait=timedelta(0), timeout=SHORT_BOUND
        )
        assert polled.failure is TelegramFailure.UNKNOWN
        assert polled.updates == ()
    else:
        sent = await rig.client.send(attempt=ATTEMPT, chat_id=CHAT, text="hi", timeout=SHORT_BOUND)
        assert sent.failure is TelegramFailure.UNKNOWN
        assert sent.message_id is None


async def test_a_silent_far_ends_channel_is_closed_at_the_bound() -> None:
    """§11:11: cancelled, and its channel closed."""
    transport = SilentTransport()
    rig = await harness(transport=transport)

    await rig.client.poll(attempt=ATTEMPT, offset=None, wait=timedelta(0), timeout=SHORT_BOUND)

    (channel,) = transport.channels
    assert channel.closed


# --- §11:6 to §11:7: the POST and its JSON body ------------------------------


async def test_the_post_is_framed_by_the_exchange() -> None:
    """``Content-Type`` and an exact ``Content-Length``, the body UTF-8 JSON (§11:6)."""
    rig = await harness(done({"message_id": 3}))

    await rig.client.send(attempt=ATTEMPT, chat_id=CHAT, text="Olá — ☕", timeout=A_BOUND)

    (request,) = rig.written()
    head, _, body = request.partition(b"\r\n\r\n")
    lines = head.decode("ascii").split("\r\n")
    assert "Content-Type: application/json" in lines
    assert f"Content-Length: {len(body)}" in lines
    assert "Connection: close" in lines
    assert "Host: api.telegram.org" in lines
    assert json.loads(body.decode("utf-8")) == {"chat_id": CHAT, "text": "Olá — ☕"}


async def test_a_body_json_cannot_carry_is_refused_before_a_channel() -> None:
    """``NaN`` is not JSON, so nothing is opened for it."""
    transport = FakeOutboundTransport()
    exchange = HttpsExchange(transport=transport, max_response_bytes=1024)

    with pytest.raises(TransportPinError, match="JSON"):
        await exchange.post_json(
            origin=TELEGRAM_BOT_API_ORIGIN, target="/x", payload={"n": float("nan")}
        )

    assert transport.attempts == ()


def test_the_post_has_one_caller_in_the_tree() -> None:
    """ "Used by the line's route alone" (§11:6): no other production code posts."""
    source = Path(__file__).resolve().parents[2] / "src" / "ai_assistant"
    callers = {
        path.relative_to(source).as_posix()
        for path in source.rglob("*.py")
        if ".post_json(" in path.read_text(encoding="utf-8")
    }
    egress = (source / "tools" / "egress.py").read_text(encoding="utf-8")

    assert callers == {"tools/egress.py"}
    assert egress.count(".post_json(") == 1
    assert egress.index(".post_json(") > egress.index("class HttpsTelegramBotClient")


# --- how a Bot API answer is read (§5, §6) -------------------------------------


@pytest.mark.parametrize(
    ("response", "failure"),
    [
        (refused(401), TelegramFailure.REFUSED),
        (refused(403), TelegramFailure.REFUSED),
        (refused(502), TelegramFailure.UNKNOWN),
        (answer({"ok": False, "description": "no code"}, status=400), TelegramFailure.UNKNOWN),
        (answer({"ok": "yes", "result": {"message_id": 1}}), TelegramFailure.UNKNOWN),
        (answer({"ok": True, "result": {"message_id": 1}}, status=201), TelegramFailure.UNKNOWN),
        (done({"message_id": True}), TelegramFailure.UNKNOWN),
        (done({"message_id": -1}), TelegramFailure.UNKNOWN),
        (done({}), TelegramFailure.UNKNOWN),
        (http(200, b"[1, 2]"), TelegramFailure.UNKNOWN),
        (http(200, b'{"ok": true, "result": NaN}'), TelegramFailure.UNKNOWN),
        (refused(429, retry_after=-4), TelegramFailure.RATE_LIMITED),
    ],
    ids=[
        "unauthorized",
        "blocked",
        "bad-gateway-in-api-shape",
        "refusal-with-no-code",
        "ok-not-a-bool",
        "done-under-another-status",
        "message-id-a-flag",
        "message-id-negative",
        "no-message-id",
        "not-an-object",
        "not-json",
        "negative-wait",
    ],
)
async def test_a_send_is_classed_by_what_the_bot_api_said(
    response: bytes, failure: TelegramFailure
) -> None:
    """Only a Bot API refusal says not sent; anything else after the write is unknown."""
    rig = await harness(response)

    outcome = await rig.client.send(attempt=ATTEMPT, chat_id=CHAT, text="hi", timeout=A_BOUND)

    assert outcome.failure is failure
    assert outcome.retry_after_seconds is None


async def test_a_typing_result_other_than_true_is_unknown() -> None:
    """``sendChatAction`` answers ``true``; anything else is no answer this line reads."""
    rig = await harness(done({"ok": "maybe"}))

    outcome = await rig.client.show_typing(attempt=ATTEMPT, chat_id=CHAT, timeout=A_BOUND)

    assert outcome.failure is TelegramFailure.UNKNOWN


_AT: Final = 1_760_000_000


def _raw(**fields: Any) -> dict[str, Any]:
    """A text message from the owner in their private chat, with ``fields`` over it."""
    message: dict[str, Any] = {
        "message_id": 50,
        "date": _AT,
        "chat": {"id": CHAT, "type": "private"},
        "from": {"id": CHAT, "is_bot": False, "first_name": "Owner"},
        "text": "hello",
    }
    message.update(fields)
    return {key: value for key, value in message.items() if value is not None}


async def _polled_one(raw: dict[str, Any]) -> TelegramMessage | None:
    """Poll one update carrying ``raw``, returning what the client read of it."""
    rig = await harness(done([{"update_id": 7, "message": raw}]))
    outcome = await rig.client.poll(attempt=ATTEMPT, offset=None, wait=A_WAIT, timeout=A_BOUND)
    assert outcome.done
    (update,) = outcome.updates
    assert update.update_id == 7
    return update.message


async def test_a_text_message_is_read_whole() -> None:
    """Sender, chat, time and text, as Telegram gave them (§5:4)."""
    message = await _polled_one(_raw())

    assert message == TelegramMessage(
        message_id=50,
        chat_id=CHAT,
        private_chat=True,
        sender_id=CHAT,
        sent_at=datetime.fromtimestamp(_AT, tz=UTC),
        text="hello",
    )


async def test_a_message_with_no_text_is_read_with_none() -> None:
    """A voice note is a message with no text (§5:3), not a message dropped."""
    message = await _polled_one(_raw(text=None, voice={"file_id": "f", "duration": 2}))

    assert message is not None
    assert message.text is None


def _command(length: int, *, offset: int = 0, kind: str = "bot_command") -> dict[str, Any]:
    return {"type": kind, "offset": offset, "length": length}


@pytest.mark.parametrize(
    ("text", "entities", "expected"),
    [
        ("/stop", [_command(5)], "/stop"),
        ("/stop now", [_command(5)], "/stop"),
        ("/stop@line_bot", [_command(14)], "/stop@line_bot"),
        # Bold over the whole text beside the command changes nothing.
        ("/stop", [_command(5, kind="bold"), _command(5)], "/stop"),
        # Nor does a type of the documented shape this line has never heard of.
        ("/stop", [_command(5, kind="someday_new"), _command(5)], "/stop"),
        # UTF-16: the emoji is two code units, and the command spans it whole.
        ("/s\U0001f600p x", [_command(5)], "/s\U0001f600p"),
    ],
    ids=[
        "bare",
        "with-words",
        "addressed",
        "beside-another-entity",
        "beside-a-later-type",
        "utf-16-units",
    ],
)
async def test_a_command_is_the_span_its_entity_covers(
    text: str, entities: list[dict[str, Any]], expected: str
) -> None:
    """ADR-0332 §7:9: the text a ``bot_command`` entity at the first character covers."""
    message = await _polled_one(_raw(text=text, entities=entities))

    assert message is not None
    assert message.text == text
    assert message.command == expected


@pytest.mark.parametrize(
    "entities",
    [
        None,
        [],
        [_command(5, offset=1)],
        [_command(5, kind="mention")],
        "not a list",
        [["bot_command", 0, 5]],
        [{"type": "bot_command", "offset": 0}],
        [{"type": "bot_command", "offset": 0, "length": "5"}],
        [{"type": "bot_command", "offset": True, "length": 5}],
        [{"type": 7, "offset": 0, "length": 5}],
        [_command(5), _command(5, kind="")],
        [_command(5), _command(5, kind=" bot_command")],
        [_command(5), _command(5, kind="Bot_Command")],
        [_command(0)],
        [_command(6)],
        [_command(5, offset=-1)],
        [_command(5), _command(5)],
        [_command(3), _command(5)],
        # A malformed entity elsewhere voids the command too: the safe side (§8:1).
        [_command(5), _command(9, offset=2, kind="bold")],
    ],
    ids=[
        "absent",
        "empty",
        "not-at-the-start",
        "another-kind",
        "not-a-list",
        "not-an-object",
        "no-length",
        "text-length",
        "flag-offset",
        "non-text-type",
        "empty-type-beside",
        "spaced-type-beside",
        "capitalised-type-beside",
        "empty-span",
        "past-the-text",
        "negative-offset",
        "two-at-the-start",
        "two-lengths",
        "a-bad-neighbour",
    ],
)
async def test_a_message_with_no_readable_command_entity_is_read_with_none(
    entities: object,
) -> None:
    """§7:9: no command, and the message is still read whole, never dropped."""
    message = await _polled_one(_raw(text="/stop", entities=entities))

    assert message is not None
    assert message.text == "/stop"
    assert message.command is None


async def test_a_command_span_ending_inside_a_character_is_no_command() -> None:
    """A span that splits a surrogate pair names no text, so the message has no command."""
    message = await _polled_one(_raw(text="/\U0001f600", entities=[_command(2)]))

    assert message is not None
    assert message.command is None


async def test_a_message_with_no_text_carries_no_command() -> None:
    """A caption's entities are not the text's: a photo is never a command (§7:9)."""
    message = await _polled_one(
        _raw(text=None, caption="/stop", caption_entities=[_command(5)], entities=[_command(5)])
    )

    assert message is not None
    assert message.text is None
    assert message.command is None


@pytest.mark.parametrize(
    ("origin", "expected"),
    [
        (
            {
                "type": "user",
                "date": _AT,
                "sender_user": {"id": 9, "is_bot": False, "first_name": "Ana", "last_name": "Lima"},
            },
            TelegramForwardOrigin(kind=TelegramForwardKind.USER, name="Ana Lima", account_id=9),
        ),
        (
            {"type": "hidden_user", "date": _AT, "sender_user_name": "Somebody"},
            TelegramForwardOrigin(kind=TelegramForwardKind.HIDDEN_USER, name="Somebody"),
        ),
        (
            {
                "type": "chat",
                "date": _AT,
                "sender_chat": {"id": -5, "type": "group", "title": "Family"},
            },
            TelegramForwardOrigin(kind=TelegramForwardKind.CHAT, name="Family", account_id=-5),
        ),
        (
            {
                "type": "channel",
                "date": _AT,
                "chat": {"id": -100, "type": "channel", "title": "News"},
                "message_id": 3,
            },
            TelegramForwardOrigin(kind=TelegramForwardKind.CHANNEL, name="News", account_id=-100),
        ),
    ],
    ids=["user", "hidden-user", "chat", "channel"],
)
async def test_a_forward_carries_its_origin(
    origin: dict[str, Any], expected: TelegramForwardOrigin
) -> None:
    """A forward's author is its original sender as Telegram reports it (§4:10)."""
    message = await _polled_one(_raw(forward_origin=origin))

    assert message is not None
    assert message.forward_origin == expected


@pytest.mark.parametrize(
    "fields",
    [
        {"forward_origin": {"type": "someday-new", "date": _AT}},
        {"forward_origin": {"type": "user", "date": _AT}},
        {"forward_date": _AT},
        {"forward_from": {"id": 9, "is_bot": False, "first_name": "Ana"}},
        {"forward_origin": {"type": [], "date": _AT}},
        {"forward_origin": {"type": {}, "date": _AT}},
        {
            "forward_origin": {
                "type": "user",
                "sender_user": {"id": 9, "first_name": "A", "last_name": 5},
            }
        },
    ],
    ids=[
        "unknown-kind",
        "user-with-no-sender",
        "legacy-date-only",
        "legacy-from-only",
        "kind-a-list",
        "kind-an-object",
        "last-name-not-text",
    ],
)
async def test_a_forward_whose_origin_cannot_be_read_is_not_read_as_the_users(
    fields: dict[str, Any],
) -> None:
    """A forward that lost its mark would be established; it is not read at all (§4:1)."""
    assert await _polled_one(_raw(**fields)) is None


async def test_a_reply_carries_the_message_it_replies_to() -> None:
    """The quoted message and who wrote it (§4:12)."""
    quoted = {
        "message_id": 40,
        "date": _AT,
        "chat": {"id": CHAT, "type": "private"},
        "from": {"id": 777, "is_bot": True, "first_name": "Bot"},
        "text": "Shall I book it?",
    }

    message = await _polled_one(_raw(reply_to_message=quoted, text="yes"))

    assert message is not None
    assert message.reply_to == TelegramQuotedMessage(
        message_id=40, sender_id=777, sender_is_bot=True, text="Shall I book it?"
    )


@pytest.mark.parametrize(
    "fields",
    [
        {"chat": "424242"},
        {"date": "yesterday"},
        {"date": True},
        {"text": 5},
        {"from": [1]},
        {"message_id": "50"},
        {"reply_to_message": {"message_id": "x"}},
        {"text": "\ud800"},
    ],
    ids=["chat", "date", "date-a-flag", "text", "sender", "message-id", "reply", "lone-surrogate"],
)
async def test_a_message_not_in_the_documented_shape_is_carried_as_none(
    fields: dict[str, Any],
) -> None:
    """Its update still has an id to confirm (§5:2), so only the message is dropped."""
    assert await _polled_one(_raw(**fields)) is None


@pytest.mark.parametrize(
    "result",
    [
        {"update_id": 1},
        [{"update_id": "1"}],
        [{"message": {}}],
        [{"update_id": 2}, {"update_id": 1}],
        [{"update_id": 1}, {"update_id": 1}],
        [7],
    ],
    ids=["not-a-list", "id-a-string", "no-id", "descending", "repeated", "not-an-object"],
)
async def test_a_poll_whose_updates_cannot_be_placed_is_unknown(result: object) -> None:
    """An update with no usable id would have the reader confirm what it never saw."""
    rig = await harness(done(result))

    outcome = await rig.client.poll(attempt=ATTEMPT, offset=None, wait=A_WAIT, timeout=A_BOUND)

    assert outcome.failure is TelegramFailure.UNKNOWN
    assert outcome.updates == ()


async def test_an_update_with_no_message_is_kept_to_confirm() -> None:
    """An update the line does not read is still an update to confirm (§5:6)."""
    rig = await harness(done([{"update_id": 3, "edited_message": _raw()}]))

    outcome = await rig.client.poll(attempt=ATTEMPT, offset=None, wait=A_WAIT, timeout=A_BOUND)

    assert outcome.updates == (TelegramUpdate(update_id=3),)


# --- construction ------------------------------------------------------------


@pytest.mark.parametrize(
    ("reference", "chat_id"),
    [("", CHAT), ("  ", CHAT), (REFERENCE, 0), (REFERENCE, True), (REFERENCE, -5)],
)
def test_a_client_for_no_line_does_not_construct(reference: str, chat_id: int) -> None:
    """``Settings`` refuses both at load; the client states the same rule."""
    with pytest.raises(ValueError):  # noqa: PT011 — either argument, named in the case
        HttpsTelegramBotClient(
            reference=reference,
            chat_id=chat_id,
            records=Records(entry()),
            secrets=Keyring(),
            exchange=HttpsExchange(transport=FakeOutboundTransport(), max_response_bytes=1024),
        )


# --- ADR-0361 §4:7, §8:3: a button's callback, as a poll reads it -------------------


def _tap_raw(**fields: Any) -> dict[str, Any]:
    """A ``callback_query`` as the Bot API writes one, with ``fields`` replaced."""
    raw: dict[str, Any] = {
        "id": "4417",
        "from": {"id": CHAT, "is_bot": False, "first_name": "O"},
        "chat_instance": "-9",
        "message": {
            "message_id": 77,
            "date": 1_700_000_000,
            "chat": {"id": CHAT, "type": "private"},
        },
        "data": "tok:y",
    }
    raw.update(fields)
    return raw


async def _tapped(raw: object) -> TelegramUpdate:
    """The one update a poll handing back ``raw`` as its callback reads."""
    rig = await harness(done([{"update_id": 9, "callback_query": raw}]))
    outcome = await rig.client.poll(attempt=ATTEMPT, offset=None, wait=A_WAIT, timeout=A_BOUND)
    (update,) = outcome.updates
    return update


async def test_a_callback_is_read_with_who_tapped_where_and_its_data() -> None:
    """The id its answer names, the tapper, the card's chat and id, and the data."""
    update = await _tapped(_tap_raw())

    assert update.message is None
    assert update.callback == TelegramCallback(
        callback_id="4417",
        sender_id=CHAT,
        chat_id=CHAT,
        private_chat=True,
        message_id=77,
        data="tok:y",
    )


async def test_a_callback_on_a_message_telegram_no_longer_gives_whole_keeps_its_place() -> None:
    """An inaccessible message (``date`` 0) still names its chat and its id."""
    update = await _tapped(
        _tap_raw(message={"message_id": 77, "date": 0, "chat": {"id": CHAT, "type": "private"}})
    )

    assert update.callback is not None
    assert update.callback.message_id == 77
    assert update.callback.chat_id == CHAT


@pytest.mark.parametrize(
    "fields",
    [
        {"id": 4417},
        {"id": ""},
        {"from": None},
        {"from": {"id": "x"}},
        {"message": [1]},
        {"message": {"message_id": 77, "chat": "x"}},
        {"data": 5},
    ],
    ids=["id-a-number", "id-blank", "no-sender", "sender-id", "message", "chat", "data"],
)
async def test_a_callback_not_in_the_documented_shape_is_carried_as_none(
    fields: dict[str, Any],
) -> None:
    """Its update still has an id to confirm (§5:2), so only the callback is dropped."""
    update = await _tapped(_tap_raw(**fields))

    assert update == TelegramUpdate(update_id=9)
