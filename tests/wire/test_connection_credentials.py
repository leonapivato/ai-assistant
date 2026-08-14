"""What the credential does on the wire, and what it must never leave behind.

ADR-0151 §16 items 6 and 7 name two tests by hand rather than leaving them to the
shared suite, and each is here because **the shared suite cannot reach it**:

* Item 6 asks for "a test that the wire client sends the credential's plaintext and
  not its redaction, written against the encoded frame rather than against the
  client's arguments". A conformance clause runs against three implementations and
  asserts on return values; the failure this one catches is invisible to every one
  of them, because the in-process engine never serialises anything.
* Item 7 asks for "a test that no operation's arguments reach a log, exercised with
  a deliberately failing call". A suite has no view of ``structlog``'s output, and
  the failing call is where a diagnostic is most likely to be written.

Item 6's hazard is worth restating because it is the one that would have shipped.
A ``TypeAdapter`` over :data:`~ai_assistant.core.types.SecretValue` serialises to
``"**********"``. An implementation reaching for pydantic's serialiser rather than
ADR-0087's own projection would send ten asterisks as the credential; the hub would
validate them as a well-formed ``SecretValue``, the provisioner would write them
into the keyring, the record would go active, and **every in-process test would
pass**. The failure would surface only at the first egress call, as an
authentication error against a credential nobody could find a fault in by
inspection. That is ADR-0125 §3's own warning about a helpful store one layer out,
and the reason ADR-0151 §6 refuses to extend ADR-0087's projection to ``SecretStr``:
leaving ``project`` failing closed keeps the general default safe and puts the one
authorised unwrap where a reviewer reads it.

ADR-0151 §16's frame-floor clause is here too, for the same reason it is stated
against the wire implementation: "A reference the caller cannot receive is the
failure §3's mint makes unrecoverable, and it is reachable only over the wire."
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from datetime import timedelta
from typing import TYPE_CHECKING, Any

import pytest
import structlog
from pydantic import SecretStr

from ai_assistant.core.errors import (
    IncompleteProvisioningError,
    OversizedValueError,
    ProvisioningOutcomeUnknownError,
    ResidualCredentialError,
    UnusableIdentityError,
)
from ai_assistant.core.types import (
    ACCOUNT_IDENTITY_MAX_BYTES,
    CONNECTION_REFERENCE_MAX_BYTES,
    ProvisioningState,
    secret_value,
)
from ai_assistant.testing import Disclosure, FakeAssistantEngine, SecretMethod
from ai_assistant.wire import ENVELOPE_RESERVE_BYTES, HubEngineClient, serve_connection
from ai_assistant.wire import envelope as env
from ai_assistant.wire.framing import read_frame, write_frame
from ai_assistant.wire.server import ConnectionLimits

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable, Iterator, MutableMapping
    from pathlib import Path

    from ai_assistant.core.types import ConnectedAccount, SecretValue

pytestmark = pytest.mark.anyio

_PATIENT = timedelta(seconds=5)
_FRAME = 1 << 20

#: ADR-0085 §8d's floor for ``hub_max_frame_bytes``, which is where ADR-0151 §11's
#: arithmetic is close enough to be worth checking. Everywhere above it the
#: question is uninteresting: the default is four orders of magnitude above any
#: credential.
_FLOOR_FRAME = 1024

#: The plaintext under test. Distinctive enough that a substring search over a
#: frame, a log line or a repr is conclusive.
_PLAINTEXT = "corr3ct-h0rse-battery-staple"

_IDENTITY = "  Ada@Example.COM  "


def _unlink(path: Path) -> None:
    """Remove the socket, off the async path so the checkers stay happy."""
    path.unlink(missing_ok=True)


def _credential(plaintext: str = _PLAINTEXT) -> SecretValue:
    """One credential, built the only supported way (ADR-0125 §3)."""
    return secret_value(SecretStr(plaintext))


@contextlib.asynccontextmanager
async def _listening(
    path: Path, handler: Callable[[asyncio.StreamReader, asyncio.StreamWriter], Awaitable[None]]
) -> AsyncIterator[HubEngineClient]:
    """Run an arbitrary handler on a socket, and hand back a client of it."""
    server = await asyncio.start_unix_server(handler, path=str(path))
    try:
        yield HubEngineClient(path, read_timeout=_PATIENT)
    finally:
        server.close()
        with contextlib.suppress(Exception):
            await server.wait_closed()
        _unlink(path)


@contextlib.asynccontextmanager
async def _served(
    backing: FakeAssistantEngine, path: Path, *, max_frame_bytes: int = _FRAME
) -> AsyncIterator[HubEngineClient]:
    """Run a real hub over ``backing``, and hand back a client of it."""
    limits = ConnectionLimits(max_frame_bytes=max_frame_bytes, read_timeout=_PATIENT, build="test")

    async def _hub(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await serve_connection(backing, reader, writer, limits=limits)

    async with _listening(path, _hub) as client:
        yield client


# --- ADR-0151 §16 item 6: what actually goes on the wire ---------------------


async def _capture_request(path: Path, call: Callable[[HubEngineClient], Awaitable[Any]]) -> bytes:
    """Run ``call`` against a hub that records the raw request frame and hangs up.

    Returns:
        The request frame's bytes, exactly as the client wrote them. **The bytes
        and not the decoded envelope**, because the claim under test is about what
        crossed the socket: a decoded payload has already been through the codec,
        and an assertion over it could pass while the encoder wrote something else.
    """
    seen: list[bytes] = []

    async def _hub(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        connect = await read_frame(
            reader, max_frame_bytes=_FRAME, timeout=_PATIENT, idle_timeout=_PATIENT
        )
        await write_frame(
            writer,
            env.encode_envelope(
                env.Envelope(
                    kind=env.FrameKind.CONNECT_ACK,
                    id=env.decode_envelope(connect).id,
                    payload=env.connect_ack_payload(build="test", max_frame_bytes=_FRAME),
                )
            ),
            max_frame_bytes=_FRAME,
        )
        seen.append(
            await read_frame(
                reader, max_frame_bytes=_FRAME, timeout=_PATIENT, idle_timeout=_PATIENT
            )
        )
        writer.close()

    async with _listening(path, _hub) as client:
        # The hub hangs up rather than replying, so the call raises. What is under
        # test is what the client *wrote*, which has already happened by then.
        with contextlib.suppress(Exception):
            await call(client)
    assert len(seen) == 1, "the client did not reach the request frame"
    return seen[0]


async def test_connect_account_puts_the_plaintext_on_the_wire(tmp_path: Path) -> None:
    """ADR-0151 §6, §16 item 6: the secret, not its redaction.

    **Asserted over the frame's bytes**, which is the only place the distinction
    exists. The redaction ``"**********"`` is what pydantic's serialiser emits for a
    ``SecretStr``, and an implementation that reached for it would produce a frame
    the hub accepts, a record that goes active, and a keyring holding ten
    asterisks — with every in-process test still green.

    The absent-redaction half is asserted as well as the present-plaintext half,
    because an encoder could conceivably carry both.
    """
    frame = await _capture_request(
        tmp_path / "hub.sock",
        lambda client: client.connect_account(identity=_IDENTITY, credential=_credential()),
    )

    envelope = env.decode_envelope(frame)
    assert envelope.method == "connect_account"
    assert envelope.payload["credential"] == _PLAINTEXT
    assert _PLAINTEXT.encode() in frame
    assert b"**********" not in frame
    # And the identity crosses byte-for-byte beside it (ADR-0151 §5), which is the
    # other value this frame is the last chance to check.
    assert envelope.payload["identity"] == _IDENTITY


async def test_reprovision_account_puts_the_plaintext_on_the_wire(tmp_path: Path) -> None:
    """The same, on the second and last operation that carries one (ADR-0151 §6).

    Written out rather than parametrised with the case above, because the two
    methods have different signatures and ADR-0151 §6's clause is that the unwrap
    lives at **one site in each** — a shared helper here would test one code path
    twice and leave the other unwatched, which is exactly the asymmetry the clause
    is about.
    """
    frame = await _capture_request(
        tmp_path / "hub.sock",
        lambda client: client.reprovision_account(
            "0f9c2e13-6b4a-4d2f-9f11-5c8a7e3b1d40",
            identity=_IDENTITY,
            credential=_credential(),
        ),
    )

    envelope = env.decode_envelope(frame)
    assert envelope.method == "reprovision_account"
    assert envelope.payload["credential"] == _PLAINTEXT
    assert b"**********" not in frame


async def test_the_hub_reconstitutes_the_plaintext_from_the_declared_annotation(
    tmp_path: Path,
) -> None:
    """ADR-0151 §6: the hub validates the received string against ``SecretValue``.

    The round trip that matters, end to end over a real socket: what the client
    unwrapped is what the provisioner is handed, still wrapped. Asserted against
    the **keyring** rather than against the engine's return value, because no
    response on this surface carries a credential (ADR-0149 §9) — so the keyring is
    the only place the delivered value can be observed at all.
    """
    backing = FakeAssistantEngine()
    async with _served(backing, tmp_path / "hub.sock") as client:
        record = await client.connect_account(identity=_IDENTITY, credential=_credential())

    assert record.state is ProvisioningState.ACTIVE
    slot = backing.connections.entries[-1].slot
    assert slot is not None
    held = await backing.connections.secrets.get(slot)
    assert held is not None
    assert held.get_secret_value() == _PLAINTEXT


async def test_no_credential_reaches_the_socket_when_the_identity_is_refused(
    tmp_path: Path,
) -> None:
    """ADR-0151 §5: refused locally, so **no frame is sent at all**.

    The clause's whole value is this: a client that deferred the identity check to
    the hub would put a secret on a socket for a call that was always going to be
    refused. Asserted by counting frames, because "the credential was not in the
    request" would be satisfied by a request that never carried one for an
    unrelated reason.
    """
    seen: list[bytes] = []

    async def _hub(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        with contextlib.suppress(Exception):
            while True:
                seen.append(
                    await read_frame(
                        reader, max_frame_bytes=_FRAME, timeout=_PATIENT, idle_timeout=_PATIENT
                    )
                )

    async with _listening(tmp_path / "hub.sock", _hub) as client:
        with pytest.raises(UnusableIdentityError):
            # The identity *is* the credential — ADR-0149 §4's paste.
            await client.connect_account(identity=_PLAINTEXT, credential=_credential())

    assert seen == []


# --- ADR-0151 §16 item 7: no argument reaches a log --------------------------


@pytest.fixture
def captured_logs() -> Iterator[list[dict[str, Any]]]:
    """Capture every ``structlog`` event for the body of a test.

    Prepended to the configured processor chain rather than replacing it, so what
    is observed is what the real chain was handed — including
    ``core/logging.py``'s redaction, which runs *after* this and must therefore
    not be what makes the assertions pass on its own.
    """
    records: list[dict[str, Any]] = []

    def _sink(
        _logger: Any, _name: str, event: MutableMapping[str, Any]
    ) -> MutableMapping[str, Any]:
        records.append(dict(event))
        return event

    before = list(structlog.get_config()["processors"])
    structlog.configure(processors=[_sink, *before])
    try:
        yield records
    finally:
        structlog.configure(processors=before)


async def test_a_failing_provisioning_call_writes_neither_value_to_a_log(
    tmp_path: Path, captured_logs: list[dict[str, Any]]
) -> None:
    """ADR-0151 §16 item 7, over a **real hub** and a deliberately failing call.

    Two prohibitions in one case, because they are held by two different mechanisms
    and a test of one would pass while the other was broken:

    * the **credential** must reach no log (ADR-0149 §9). ``core/logging.py``
      redacts by key name and ``_SENSITIVE_KEY_PARTS`` contains ``credential``,
      which is why ADR-0151 §6 requires the argument to be *named* ``credential``
      on both operations — but redaction only fires on a key that is logged at all,
      and ``wire/server.py`` logs no payload, which is the belt this is the braces
      for;
    * the **identity** must reach no log either (ADR-0149 §3 makes it Tier 1), and
      **no key-based redaction covers it** — ``identity`` is not a sensitive key
      part and must not become one, because a reference beside it is loggable on
      purpose. So the identity's absence rests entirely on nothing logging the
      payload, which is the half this case exists to hold.

    The call is made to fail at the keyring so that the hub takes its *error* path,
    which is where a diagnostic is most likely to be written and least likely to
    have been reviewed.
    """
    backing = FakeAssistantEngine()
    backing.connections.secrets.fail(SecretMethod.SET, Disclosure.VERBATIM)

    async with _served(backing, tmp_path / "hub.sock") as client:
        with pytest.raises(IncompleteProvisioningError) as caught:
            await client.connect_account(identity=_IDENTITY, credential=_credential())

    rendered = json.dumps(captured_logs, default=repr)
    assert _PLAINTEXT not in rendered
    assert _IDENTITY not in rendered
    assert _IDENTITY.strip() not in rendered
    # The refusal itself is under the same rule (ADR-0151 §2a): it names the
    # reference, which ADR-0149 §3 licenses to be logged, and neither of the two
    # values beside it.
    assert _PLAINTEXT not in str(caught.value)
    assert _IDENTITY.strip() not in str(caught.value)
    assert caught.value.reference


async def test_a_refused_identity_writes_neither_value_to_a_log(
    tmp_path: Path, captured_logs: list[dict[str, Any]]
) -> None:
    """The local refusal path, which never reaches the hub and so is logged by nobody.

    Worth its own case because it is the one call where the client holds both
    values and produces a message about them: a refusal that quoted what it
    refused would put a pasted token into the operator's own terminal.
    """
    async with _served(FakeAssistantEngine(), tmp_path / "hub.sock") as client:
        with pytest.raises(UnusableIdentityError) as caught:
            await client.connect_account(identity=_PLAINTEXT, credential=_credential())

    rendered = json.dumps(captured_logs, default=repr)
    assert _PLAINTEXT not in rendered
    assert _PLAINTEXT not in str(caught.value)


# --- ADR-0151 §16: the frame floor, against the wire implementation ----------


async def test_a_maximal_identity_and_reference_still_fit_the_floor_frame(
    tmp_path: Path,
) -> None:
    """ADR-0151 §16: a completed ``connect_account`` returns rather than raising.

    Run with ``hub_max_frame_bytes`` at ADR-0085 §8d's 1024-byte floor and a
    **maximal** minted reference throughout, which is where §11's arithmetic is
    tight enough to be worth checking: the payload budget there is 512 bytes, a
    ``ConnectedAccount`` spends roughly 60 on member names and punctuation, and the
    two bounded values are :data:`CONNECTION_REFERENCE_MAX_BYTES` and
    :data:`ACCOUNT_IDENTITY_MAX_BYTES`.

    **The identity is maximal too**, which is the half that makes this a check
    rather than a formality: it is what the lane sized
    :data:`ACCOUNT_IDENTITY_MAX_BYTES` against, and a bound chosen a little too
    generously would fail here and nowhere else.
    """
    reference = "r" * CONNECTION_REFERENCE_MAX_BYTES
    identity = "i" * ACCOUNT_IDENTITY_MAX_BYTES
    backing = FakeAssistantEngine(max_payload_bytes=_FLOOR_FRAME - ENVELOPE_RESERVE_BYTES)
    backing.connections = type(backing.connections)(mint_reference=lambda: reference)

    async with _served(backing, tmp_path / "hub.sock", max_frame_bytes=_FLOOR_FRAME) as client:
        record = await client.connect_account(identity=identity, credential=_credential("s"))

    assert record.reference == reference
    assert record.identity == identity
    assert record.state is ProvisioningState.ACTIVE


@pytest.mark.parametrize(
    ("failing", "expected"),
    [
        (SecretMethod.SET, IncompleteProvisioningError),
        (SecretMethod.DELETE, ResidualCredentialError),
    ],
    ids=["credential-write", "deletion-pass"],
)
async def test_a_reference_carrying_refusal_is_delivered_whole_at_the_floor_frame(
    tmp_path: Path, failing: SecretMethod, expected: type[Exception]
) -> None:
    """ADR-0151 §16: the ``reference`` arrives intact, and ``details_elided`` is false.

    **The failure this guards is unrecoverable and reachable only over the wire.**
    ADR-0085 §10a's reduction nulls ``details`` *before* it truncates a message, so
    an error payload that has to be reduced arrives without its reference — and on
    the classes ``connect_account`` raises, that is the only handle the caller will
    ever have, because §3 minted it inside the act. A caller who loses it has
    durable state they cannot name.

    Run at the floor frame with a maximal minted reference, which is the worst case
    the lane sized the messages against.
    """
    reference = "r" * CONNECTION_REFERENCE_MAX_BYTES
    backing = FakeAssistantEngine(max_payload_bytes=_FLOOR_FRAME - ENVELOPE_RESERVE_BYTES)
    backing.connections = type(backing.connections)(mint_reference=lambda: reference)

    async with _served(backing, tmp_path / "hub.sock", max_frame_bytes=_FLOOR_FRAME) as client:
        if failing is SecretMethod.SET:
            backing.connections.secrets.fail(failing, Disclosure.VERBATIM)
            with pytest.raises(expected) as caught:
                await client.connect_account(identity="ada", credential=_credential("s"))
        else:
            await client.connect_account(identity="ada", credential=_credential("s"))
            backing.connections.secrets.fail(failing, Disclosure.VERBATIM)
            with pytest.raises(expected) as caught:
                await client.disconnect_account(reference)

    assert getattr(caught.value, "reference", None) == reference
    assert caught.value.details_elided is False  # type: ignore[attr-defined] # AssistantError's


async def test_an_activation_failure_delivers_its_reference_over_the_wire(
    tmp_path: Path,
) -> None:
    """The third reference-carrying class, reached through the hub's own engine.

    ``ProvisioningOutcomeUnknownError`` is the widest error code on this surface at
    31 bytes, which is what ADR-0151 §11 sized the one message bound against — so
    it is the class the floor arithmetic is least generous to and the one worth
    exercising by name.

    It is raised through a stubbed provisioner rather than by scripting the fake's
    store, because "the store committed the compare-and-swap and then failed before
    saying so" is a state no lever on the canonical fake produces — and the point
    here is the **delivery** of the class over a frame, which is the client's
    property and not the provisioner's.
    """
    reference = "r" * CONNECTION_REFERENCE_MAX_BYTES

    class _Failing(FakeAssistantEngine):
        async def connect_account(self, **_: object) -> ConnectedAccount:
            msg = (
                f"connection {reference!r} may or may not be connected; read what is "
                f"connected before acting"
            )
            raise ProvisioningOutcomeUnknownError(msg, reference)

    backing = _Failing(max_payload_bytes=_FLOOR_FRAME - ENVELOPE_RESERVE_BYTES)
    async with _served(backing, tmp_path / "hub.sock", max_frame_bytes=_FLOOR_FRAME) as client:
        with pytest.raises(ProvisioningOutcomeUnknownError) as caught:
            await client.connect_account(identity="ada", credential=_credential("s"))

    assert caught.value.reference == reference
    assert caught.value.details_elided is False


async def test_a_maximal_credential_does_not_fit_the_floor_frame(tmp_path: Path) -> None:
    """ADR-0151 §11: fail closed, and never truncate.

    ``SECRET_VALUE_MAX_BYTES`` is 1024 and the payload budget at the 1024-byte frame
    floor is 512, so a maximal credential does not fit the minimum frame. The
    reachable population is an operator who deliberately configured the floor —
    the default is four orders of magnitude above any credential — and the answer
    is a declared ``OversizedValueError`` with nothing written, because a truncated
    credential is one that fails authentication later with no evidence of why.
    """
    backing = FakeAssistantEngine(max_payload_bytes=_FLOOR_FRAME - ENVELOPE_RESERVE_BYTES)
    async with _served(backing, tmp_path / "hub.sock", max_frame_bytes=_FLOOR_FRAME) as client:
        with pytest.raises(OversizedValueError):
            await client.connect_account(identity="ada", credential=_credential("s" * 1000))

    assert backing.connections.entries == []
