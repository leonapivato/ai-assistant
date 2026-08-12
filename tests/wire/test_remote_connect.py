"""The remote listener's credential rule, read off the frame (ADR-0124 §7).

The loopback rule is tested in ``test_envelope.py`` and is unchanged; what is here
is the inversion, and the two properties §9's no-bump rest on: the two readers
share every member but the credential, and the refusal codes are lowercase tokens
that a client tells apart from a class name.
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, Any, Final

import pytest

from ai_assistant.core import errors as core_errors
from ai_assistant.core.errors import MemoryStoreError
from ai_assistant.wire import client as wire_client
from ai_assistant.wire import envelope as env
from ai_assistant.wire.codec import CONNECT_PAYLOAD_BYTES
from ai_assistant.wire.errors import (
    CredentialNotSupportedError,
    CredentialRejectedError,
    CredentialRequiredError,
    ProtocolError,
    UndecodableFrameError,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

#: One well-formed credential, **pinned rather than minted**. It is fed to two
#: ``parametrize`` lists below, so a module-import-time ``mint_credential()`` gave
#: every process a different set of test IDs — which is fine serially and fatal
#: under ``pytest-xdist``, where workers collect independently and a mismatch fails
#: the run before an assertion is reached. Nothing here tests the minting
#: (``test_credential.py`` owns that); these cases need *a* value of the scheme
#: ADR-0124 §6 mints, and a literal is one. What keeps the literal honest is
#: ``test_a_well_formed_credential_is_read_back_whole``: it puts this value through
#: ``read_remote_connect``, which refuses anything not well formed — so a pin that
#: stopped matching the scheme would fail loudly rather than pass vacuously.
_VALID: Final = "X1fH-ZM9TBrKrmGsNmjQ8mT3OA94HhblZa_QFPiyCEs"


@contextlib.contextmanager
def monkeypatched(module: object, name: str, value: object) -> Iterator[None]:
    """Swap one module attribute for the length of the block, then put it back."""
    original = getattr(module, name)
    setattr(module, name, value)
    try:
        yield
    finally:
        setattr(module, name, original)


def _payload(**overrides: Any) -> dict[str, Any]:
    """A connect payload, with whatever a case needs to vary."""
    body: dict[str, Any] = {
        env.CONNECT_VERSION: env.PROTOCOL_VERSION,
        env.CONNECT_CLIENT: "assistant-cli",
    }
    body.update(overrides)
    return body


def test_a_well_formed_credential_is_read_back_whole() -> None:
    """The admitting case, which every refusal below is discriminated against."""
    version, client, credential = env.read_remote_connect(_payload(credential=_VALID))
    assert (version, client, credential) == (env.PROTOCOL_VERSION, "assistant-cli", _VALID)


@pytest.mark.parametrize("payload", [_payload(), _payload(credential="")])
def test_an_absent_or_empty_credential_is_refused_by_its_own_reason(
    payload: dict[str, Any],
) -> None:
    """ADR-0124 §7: absent or empty is "refused, with a distinct error naming the
    reason".

    The two spellings of "nothing" the clause names, and **only** those two: a
    member that is not there, and a member that is there and empty. An explicit
    ``null`` is a third thing and it belongs to the clause below, which is the
    distinction this file previously lost — see
    ``test_a_null_credential_is_present_and_not_a_string``.
    """
    with pytest.raises(CredentialRequiredError):
        env.read_remote_connect(payload)


def test_a_null_credential_is_present_and_not_a_string_so_it_is_rejected() -> None:
    """ADR-0124 §7's two arms, on the one value that satisfies both readings at a
    glance and only one of them on the text (issue #917).

    §7 puts "absent or empty" in one arm and "present and… not a string" in the
    other. A ``null`` member is **present**, and it is **not a string**, so the
    second arm governs — the first is about a member that is not there. The arms are
    asserted against each other rather than alone, because the defect this pins was
    not a missing refusal but the wrong one of two: ``dict.get`` answers ``None``
    both for a member that is absent and for one that is present and ``null``, so a
    reader that tests the decoded value alone cannot tell them apart, and the
    ``is None`` arm ran first and swallowed the case.

    Both codes refuse and close, so this is a distinctness defect rather than an
    admission one — and distinctness is a ruled obligation: §7 requires the reasons
    told apart "in the error it returns **and in what the hub logs**", so an operator
    debugging a non-conforming client is otherwise told it sent *no* credential when
    it sent a malformed one.
    """
    present_and_null = _payload(credential=None)
    assert env.CONNECT_CREDENTIAL in present_and_null  # the premise: the member is there
    with pytest.raises(CredentialRejectedError):
        env.read_remote_connect(present_and_null)

    omitted = _payload()
    assert env.CONNECT_CREDENTIAL not in omitted
    with pytest.raises(CredentialRequiredError):
        env.read_remote_connect(omitted)


def test_a_null_credential_is_still_nothing_on_the_loopback_transport() -> None:
    """The other reader's answer to the same value, pinned as a decision rather than
    left as whatever the shared member-reader happens to do.

    ADR-0124 §7 froze the loopback rule — "ADR-0084 §2's rule is unchanged on the
    loopback transport" — and that rule refuses a **non-empty** credential. A
    ``null`` is not one: it is a client saying it carries none, on a transport where
    nothing is checked and the ``0600`` bit does the work, so admitting it asserts no
    check that did not happen. §7's type rule comes with a code (``credential_rejected``)
    that the same section forbids on this listener, so applying it here would mean
    inventing an answer rather than reading one.

    Asserted beside the remote reader's opposite answer because that is what makes
    the two rules a decision: the same bytes, two listeners, two rulings, each from
    its own clause.
    """
    assert env.read_connect(_payload(credential=None)) == (env.PROTOCOL_VERSION, "assistant-cli")
    with pytest.raises(CredentialRejectedError):
        env.read_remote_connect(_payload(credential=None))


@pytest.mark.parametrize("credential", [1, True, 1.5, {"credential": "x"}, ["x"], None])
def test_a_credential_that_is_not_a_string_is_refused_as_one_that_did_not_verify(
    credential: object,
) -> None:
    """ADR-0124 §7: "present and is not a string… is refused as a credential that did
    not verify, and the value never reaches the verifier or the comparison".

    "On the remote listener the same value would otherwise reach a verifier written
    for text, and three implementations could diverge three ways: an uncaught type
    error that closes the connection with no refusal, a hash over some serialisation
    of the object, or a generic refusal."

    **Every JSON type that is not a string is here, ``null`` included**, so the arm
    is ruled once rather than type by type — a rule that named the types it had
    thought of would leave whichever one it forgot to the arm above.
    """
    with pytest.raises(CredentialRejectedError):
        env.read_remote_connect(_payload(credential=credential))


@pytest.mark.parametrize("credential", ["x", _VALID[:-1], _VALID + "x", _VALID[:-1] + "+"])
def test_a_malformed_credential_is_refused_as_one_that_did_not_verify(credential: str) -> None:
    """The same clause's second limb: "a string that is not a well-formed value of
    the scheme §6 mints".

    It shares its refusal with a wrong credential deliberately, so a peer learns
    nothing from the shape of its own mistake that it could not learn by guessing.
    """
    with pytest.raises(CredentialRejectedError):
        env.read_remote_connect(_payload(credential=credential))


def test_the_two_readers_disagree_about_the_credential_and_about_nothing_else() -> None:
    """ADR-0124 §9's premise, as a property rather than an assertion.

    "The remote listener adds no member to the connect exchange, changes no frame's
    encoding… A peer at version 2 on either listener exchanges exactly the frames it
    exchanges today." So the same payload minus its credential yields the same
    version and client through both readers, and the credential is the one member
    they answer differently about.
    """
    plain = _payload()
    assert env.read_connect(plain) == (env.PROTOCOL_VERSION, "assistant-cli")
    with pytest.raises(CredentialRequiredError):
        env.read_remote_connect(plain)

    carried = _payload(credential=_VALID)
    with pytest.raises(CredentialNotSupportedError):
        env.read_connect(carried)
    assert env.read_remote_connect(carried)[:2] == (env.PROTOCOL_VERSION, "assistant-cli")


def test_an_oversized_handshake_closes_before_the_credential_rule_is_reached() -> None:
    """ADR-0124 §7: "the width is already bounded and nothing new is needed for it".

    "`_refuse_an_oversized_handshake` runs first in `read_connect`, so an oversized
    credential is refused as an oversized handshake and never reaches this section at
    all." The distinction matters because the two refusals have opposite answers: an
    oversized frame closes with no response, and a credential refusal is reported
    first.
    """
    with pytest.raises(UndecodableFrameError, match=str(CONNECT_PAYLOAD_BYTES)):
        env.read_remote_connect(_payload(credential="c" * CONNECT_PAYLOAD_BYTES))


@pytest.mark.parametrize(
    "payload",
    [
        "not an object",
        _payload(version="2", credential=_VALID),
        {env.CONNECT_VERSION: env.PROTOCOL_VERSION, env.CONNECT_CREDENTIAL: _VALID},
    ],
)
def test_a_frame_that_is_not_a_connect_payload_closes_on_both_listeners(payload: object) -> None:
    """The undecodable class is the same on both, which is the other half of §9.

    A payload that is not an object, a version that is not an integer, and a frame
    naming no client are ADR-0084 §3's close with no response, and the remote
    listener inherits them rather than answering them with one of its own codes.
    """
    with pytest.raises(UndecodableFrameError):
        env.read_remote_connect(payload)


def test_every_refusal_code_is_a_lowercase_token_rather_than_a_class_name() -> None:
    """ADR-0124 §7: "a lowercase token, not a class name, so a client can tell a
    transport refusal from a reconstructable ``AssistantError`` by the code alone".

    Pinned as a property of the whole set rather than of the four codes this change
    adds, so a fifth refusal spelled as a class name fails here.
    """
    assert env.HANDSHAKE_REFUSALS
    for code in env.HANDSHAKE_REFUSALS:
        assert code == code.lower()
        assert "_" in code
        assert getattr(core_errors, code, None) is None


def test_the_handshake_set_names_every_refusal_and_the_client_reads_that_set() -> None:
    """The tripwire ADR-0124 §7 asks for, on its own named enforcement point.

    "A new refusal code that is not added to that set would reach an older client's
    reconstruction path as an unknown class." Two things are pinned, and the second
    is the one that makes a future refusal safe without anyone editing this file:
    the set holds the six codes that exist, and the client's call-path guard reads
    **that object** rather than a literal of its own — so a seventh added beside the
    six is covered by construction.
    """
    declared = {
        env.VERSION_MISMATCH,
        env.CREDENTIAL_NOT_SUPPORTED,
        env.CREDENTIAL_REQUIRED,
        env.CREDENTIAL_REJECTED,
        env.DEVICE_NOT_ENROLLED,
        env.DEVICE_REVOKED,
    }
    assert declared == env.HANDSHAKE_REFUSALS
    sentinel = "a_refusal_no_build_declares"
    payload = {"code": sentinel, "message": "refused", "details": None, "reduced": False}
    with (
        monkeypatched(env, "HANDSHAKE_REFUSALS", frozenset({sentinel})),
        pytest.raises(ProtocolError, match="refused"),
    ):
        wire_client._raise_reply_error(payload)  # the enforcement point itself


@pytest.mark.parametrize("code", sorted(env.HANDSHAKE_REFUSALS))
def test_a_handshake_code_on_the_call_path_is_a_protocol_fault(code: str) -> None:
    """ADR-0124 §7's enforcement point, exercised through the function that holds it.

    ``_raise_reply_error`` must not hand a handshake code to ``raise_from_payload``,
    "which expects a class name" — an older client would then report it as an unknown
    error class rather than as the transport refusal it is.
    """
    payload = {"code": code, "message": "refused", "details": None, "reduced": False}
    with pytest.raises(ProtocolError, match="refused"):
        wire_client._raise_reply_error(payload)  # the enforcement point itself


def test_a_declared_failure_on_the_call_path_is_still_reconstructed() -> None:
    """The discriminating half: a client that raised ``ProtocolError`` for everything
    would pass every case above and break ADR-0085 §10a's substitutability.
    """
    payload = {
        "code": "MemoryStoreError",
        "message": "the store is unavailable",
        "details": None,
        "reduced": False,
    }
    with pytest.raises(MemoryStoreError):
        wire_client._raise_reply_error(payload)  # the enforcement point itself
