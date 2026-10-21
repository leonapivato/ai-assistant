"""A keyless callable and a credentialed one, each refusing the other's record (ADR-0325 §2).

ADR-0325 §2:3 restates ADR-0148 §6:5's third condition for every callable: the record
the binding names has the callable's own shape. A callable built with a ``Secrets``
face reads under the slot the record names and refuses a record that names none; a
keyless callable reads no credential and refuses a record that names one. §5:6 asks
the implementing lane for both refusals, and they are here over the one keyless
callable the tree has — :class:`~ai_assistant.tools.egress.HttpsEgressTransport`
built with no face — and over each credentialed one at the seam.

**Nothing here opens a socket.** Every channel is
:class:`~ai_assistant.testing.FakeByteChannel` served by
:class:`~ai_assistant.testing.FakeOutboundTransport`, and the transport's recorded
attempts are what "nothing was transmitted" is asserted against.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

import pytest
from egress_transport_harness import (
    CREDENTIAL,
    IDENTITY,
    REFERENCE,
    Keyring,
    Records,
    arguments,
    binding,
    entry,
    keyring,
    transport,
)

from ai_assistant.core.errors import ConnectionStoreError
from ai_assistant.core.types import (
    BoundAccount,
    EgressBinding,
    ProvisioningState,
    SpanCoverage,
)
from ai_assistant.testing import FakeByteChannel, FakeOutboundTransport
from ai_assistant.tools.egress import (
    BoundCallChangedError,
    HttpsEgressTransport,
    HttpsExchange,
    TransportPinError,
)
from ai_assistant.tools.egress_binder import EgressRegistration

if TYPE_CHECKING:
    from ai_assistant.core.protocols import Secrets
    from ai_assistant.tools.connection_store import StoredEntry

pytestmark = pytest.mark.anyio

#: The keyless integration's registration: its connection and its one origin.
_TOOL_ID: Final = "forecast@keyless"
_ORIGIN: Final = "https://forecast.example.invalid"
_TARGET: Final = "/v1/forecast?latitude=41.15&longitude=-8.61"

#: What the far end answers when a request is allowed through.
_ANSWER: Final = b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\n{}"

#: The record a keyless provisioning act writes: ``ACTIVE`` at revision 1, no slot.
_KEYLESS: Final = entry(slot=None)


def _bound(*, identity: str = IDENTITY, reference: str = REFERENCE) -> EgressBinding:
    """A binding over the keyless integration's connection, as a ruling fixed it."""
    return EgressBinding(
        spans=(),
        account=BoundAccount(identity=identity, reference=reference),
        transport_endpoint=_ORIGIN,
        planned_with_external_content=False,
        coverage=SpanCoverage.NOT_COVERED,
    )


def _https(
    records: Records, *, secrets: Secrets | None
) -> tuple[HttpsEgressTransport, FakeOutboundTransport]:
    """An HTTPS transport over one answering far end, keyless where ``secrets`` is None."""
    capability = FakeOutboundTransport().serve(FakeByteChannel(secure=True).deliver(_ANSWER))
    subject = HttpsEgressTransport(
        registration=EgressRegistration(
            tool_id=_TOOL_ID, reference=REFERENCE, transport_endpoint=_ORIGIN
        ),
        records=records,
        secrets=secrets,
        exchange=HttpsExchange(transport=capability, max_response_bytes=4096),
    )
    return subject, capability


async def _ask_keyless(subject: HttpsEgressTransport, call: EgressBinding | None = None) -> int:
    """One keyless request, returning the response's status."""
    answered = await subject.fetch(
        call if call is not None else _bound(),
        origin=_ORIGIN,
        target=_TARGET,
        credential_field=None,
    )
    return answered.status


# --- the keyless callable --------------------------------------------------


async def test_a_keyless_callable_asks_under_a_keyless_record_after_one_read() -> None:
    """ADR-0325 §2:5: the record is read **once**, and then the request is made.

    No credential field rides in the request, because there is none to place.
    """
    records = Records(_KEYLESS)
    subject, capability = _https(records, secrets=None)

    status = await _ask_keyless(subject)

    assert status == 200
    assert records.reads == [REFERENCE]
    assert len(capability.attempts) == 1
    written = capability.channels[0].written.decode("latin-1")
    assert written.startswith(f"GET {_TARGET} HTTP/1.1\r\n")


async def test_a_keyless_callable_refuses_a_record_naming_a_slot() -> None:
    """ADR-0325 §2:3, §5:6: a slot on the record is refused, not ignored.

    Ignoring it would be harmless to the egress floor — the credential would never be
    read — and would leave a credential in the keyring that no call reads while the
    user believes it is in use. Refused before any channel is opened.
    """
    subject, capability = _https(Records(entry()), secrets=None)

    with pytest.raises(BoundCallChangedError, match="names a credential"):
        await _ask_keyless(subject)

    assert capability.attempts == ()


@pytest.mark.parametrize(
    ("record", "call"),
    [
        pytest.param(None, _bound(), id="no-record"),
        pytest.param(entry(state=None), _bound(), id="removed"),
        pytest.param(_KEYLESS, _bound(identity="someone-else"), id="other-identity"),
    ],
)
async def test_the_other_conditions_bind_a_keyless_callable_unchanged(
    record: StoredEntry | None, call: EgressBinding
) -> None:
    """ADR-0325 §2:4: connectability and the recorded identity, refused before a byte.

    A removal is "not connectable", and a record whose identity is not the bound one
    is a reference re-pointed to another use under another name — which the identity
    comparison catches whether or not a key is involved.
    """
    subject, capability = _https(Records(record), secrets=None)

    with pytest.raises(BoundCallChangedError):
        await _ask_keyless(subject, call)

    assert capability.attempts == ()


@pytest.mark.parametrize(
    "call",
    [
        pytest.param(_bound(reference="conn-elsewhere"), id="another-connection"),
        pytest.param(
            _bound().model_copy(update={"transport_endpoint": "https://other.example.invalid"}),
            id="another-endpoint",
        ),
    ],
)
async def test_a_keyless_call_bound_elsewhere_reads_no_record(call: EgressBinding) -> None:
    """ADR-0325 §2:4: the reference and the endpoint are pinned before the one read."""
    records = Records(_KEYLESS)
    subject, capability = _https(records, secrets=None)

    with pytest.raises(TransportPinError):
        await _ask_keyless(subject, call)

    assert records.reads == []
    assert capability.attempts == ()


async def test_a_keyless_callable_propagates_a_store_outage_on_its_one_read() -> None:
    """The one read is a first read: an outage asserts nothing and is not converted."""
    subject, capability = _https(Records(ConnectionStoreError("store gone")), secrets=None)

    with pytest.raises(ConnectionStoreError):
        await _ask_keyless(subject)

    assert capability.attempts == ()


async def test_a_call_disagreeing_with_the_construction_site_is_refused_before_a_read() -> None:
    """ADR-0325 §2:2: which shape an integration is comes from its construction.

    A keyless transport handed a credential field, or a credentialed one handed none,
    is the integration's own code disagreeing with itself; nothing is read from the
    store or the keyring to settle it.
    """
    records = Records(_KEYLESS)
    ring = await keyring()
    keyless, _ = _https(records, secrets=None)
    credentialed, _ = _https(records, secrets=ring)

    with pytest.raises(ValueError, match="ADR-0325"):
        await keyless.fetch(_bound(), origin=_ORIGIN, target=_TARGET, credential_field="X-Api-Key")
    with pytest.raises(ValueError, match="ADR-0325"):
        await credentialed.fetch(_bound(), origin=_ORIGIN, target=_TARGET, credential_field=None)

    assert records.reads == []
    assert ring.reads == []


# --- the credentialed callables --------------------------------------------


async def test_a_credentialed_https_callable_refuses_a_keyless_record() -> None:
    """ADR-0325 §2:3, §5:6: a record naming no slot is refused, and no credential is read.

    Reading nothing and transmitting with no credential is exactly what #2396's
    "where it names one" wording would have allowed, and what §2:3 closes.
    """
    ring = await keyring()
    subject, capability = _https(Records(_KEYLESS), secrets=ring)

    with pytest.raises(BoundCallChangedError, match="not connectable"):
        await subject.fetch(_bound(), origin=_ORIGIN, target=_TARGET, credential_field="X-Api-Key")

    assert ring.reads == []
    assert capability.attempts == ()


async def test_a_credentialed_smtp_callable_refuses_a_keyless_record() -> None:
    """ADR-0325 §2:3, §5:6, over the mail seam: no credential read, nothing sent."""
    ring: Keyring = await keyring(holds=CREDENTIAL)
    subject = transport(None, records=Records(_KEYLESS), secrets=ring)

    with pytest.raises(BoundCallChangedError, match="not connectable"):
        await subject.transmit(binding(), arguments())

    assert ring.reads == []


def test_the_keyless_record_is_the_one_a_keyless_act_writes() -> None:
    """The arrangement this module rests on: ``ACTIVE``, revision 1, and no slot."""
    assert _KEYLESS.entry.state is ProvisioningState.ACTIVE
    assert _KEYLESS.entry.revision == 1
    assert _KEYLESS.entry.slot is None
