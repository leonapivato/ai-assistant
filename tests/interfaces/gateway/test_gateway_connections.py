"""The browser's connection surface, end to end (ADR-0177 §3, §4; ADR-0151).

Five operations reach a browser here that did not before — ``connect_account``,
``reprovision_account``, ``disconnect_account``, ``connected_accounts`` and
``recent_connection_acts``. ADR-0177 §1 admits them by name, §3 rules which of them
each listener carries, and §4 says what a browser owes the one Tier 0 value on the
whole control surface.

**What this file exists to hold apart is the *listener* from everything a peer can
say.** ADR-0177 §3 decides the refusal "from the listener the request arrived on and
from nothing the browser asserts — not from a header, an origin value, a body field,
or a device identity", and it is not lifted by ADR-0174 §4's admission or by a device
appearing in ``gateway_remote_browser_devices``. A handler call cannot see any of
that, so every case here is **driven through a real socket**, on
``test_gateway_streams``' and ``test_gateway_remote_listener``'s own harnesses rather
than a third copy of either.

**The other half is ADR-0151 §7's and §8's classification.** Seven outcome classes
carry facts a client may not derive from anything else — whether the act landed,
whether the reference exists, whether the state is readable — and a surface that
answered all seven with one name would oblige the page to infer them from a message.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest
import structlog
from gateway_mint import bootstrap_value
from test_gateway_remote_listener import Answer, Remote, _read_answer, _remote, _start_session
from test_gateway_streams import Harness, _harness

from ai_assistant.core.errors import (
    ConnectionStoreError,
    DisplacedProvisioningError,
    IncompleteProvisioningError,
    OversizedValueError,
    ProvisioningOutcomeUnknownError,
    ResidualCredentialError,
    UnknownConnectionError,
    UnusableIdentityError,
)
from ai_assistant.core.types import SECRET_VALUE_MAX_BYTES, ConnectedAccount
from ai_assistant.interfaces.gateway.server import _ASSISTANT_PATHS
from ai_assistant.testing import FakeAssistantEngine

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from ai_assistant.core.types import Identifier, NonBlankEncodableText, SecretValue

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("hermetic_assistant_env")]

#: Every path this lane adds, with the operation ADR-0177 §1 admits it for.
_ADDED: dict[str, str] = {
    "/connection/connect": "connect_account",
    "/connection/reprovision": "reprovision_account",
    "/connection/disconnect": "disconnect_account",
    "/connections": "connected_accounts",
    "/connections/recent": "recent_connection_acts",
}

#: The two ADR-0177 §3 admits on the loopback listener alone — ADR-0151 §6's "no
#: other operation on any surface accepts one", read as a set of request shapes.
_CREDENTIAL_PATHS = ("/connection/connect", "/connection/reprovision")

#: The three §3 admits on both listeners. Each carries a *reference*, which ADR-0151
#: §3 designed so that it is not a credential.
_REFERENCE_PATHS = ("/connection/disconnect", "/connections", "/connections/recent")

#: One well-formed body per path, so a case can drive any of them without inventing
#: arguments at each site.
_WELL_FORMED: dict[str, dict[str, Any]] = {
    "/connection/connect": {"identity": "me@example.com", "credential": "sekrit"},
    "/connection/reprovision": {
        "reference": "conn-1",
        "identity": "me@example.com",
        "credential": "sekrit",
    },
    "/connection/disconnect": {"reference": "conn-1"},
    "/connections": {},
    "/connections/recent": {},
}


@pytest.fixture
async def harness() -> AsyncIterator[Harness]:
    """A gateway on ADR-0168 §8's and ADR-0175 §8's own figures."""
    async with _harness() as one:
        yield one


class _Failing(FakeAssistantEngine):
    """An engine whose connection acts raise one scripted failure.

    The seven classes ADR-0151 §7 and §8 classify are raised **by contract** rather
    than driven out of the provisioner one state at a time: what is under test here is
    the gateway's naming of a class it was handed, and the classes are the contract's
    own. Reaching each of them through the store would test the fake's route to it.
    """

    def __init__(self, failure: Exception) -> None:
        """Script one failure for every connection act."""
        super().__init__()
        self.failure = failure

    async def connect_account(
        self, *, identity: NonBlankEncodableText, credential: SecretValue
    ) -> ConnectedAccount:
        """Raise the scripted failure instead of connecting."""
        self.calls.append(("connect_account", {"identity": identity}))
        raise self.failure

    async def disconnect_account(self, reference: Identifier) -> ConnectedAccount | None:
        """Raise the scripted failure instead of disconnecting."""
        self.calls.append(("disconnect_account", {"reference": reference}))
        raise self.failure


async def _connected(one: Harness, identity: str = "me@example.com") -> dict[str, Any]:
    """Connect one account through the surface and return the rendered record."""
    status, body = await one.whole(
        "POST", "/connection/connect", {"identity": identity, "credential": "sekrit"}
    )
    assert status == 200, body
    account: dict[str, Any] = body["account"]
    return account


# --- ADR-0177 §1: five more operations, and the enumeration stays closed ------


def test_the_five_connection_operations_are_in_the_enumeration() -> None:
    """§1: a browser request resolves to calls on exactly thirty operations, of which
    these five are ADR-0151 §1's whole connection surface.

    Read off the one table the gateway classifies from, so the ADR and the code are
    one thing to compare rather than two.
    """
    admitted = {path: operation for (method, path), operation in _ASSISTANT_PATHS.items()}

    assert all(admitted.get(path) == operation for path, operation in _ADDED.items())
    assert all(("POST", path) in _ASSISTANT_PATHS for path in _ADDED)


def test_no_lane_of_this_surface_reaches_learn() -> None:
    """§1 and §11: ``learn`` is admitted by nothing — it is "the one operation of the
    promoted surface that is neither in the enumeration above nor the gateway's own",
    and no lane adds it without its own ratified decision.

    The CONFIRM pair used to be asserted absent beside it and no longer is: ADR-0178's
    merge discharged ADR-0177 §8's precondition, so ``pending_confirmations`` and
    ``resume`` are served (#1404). ``learn`` is what is left, and it is left out for a
    different reason — a missing *surface* decision rather than a missing content one.
    """
    reached = set(_ASSISTANT_PATHS.values())

    assert "learn" not in reached


@pytest.mark.parametrize("path", list(_ADDED))
async def test_each_operation_is_reached_with_the_arguments_the_browser_supplied(
    harness: Harness, path: str
) -> None:
    """§1: "Every operation admitted above is reached with the arguments the promoted
    surface declares and with no others… the gateway derives none of them, defaults
    none of them, composes no operation out of two, and synthesises no result from a
    call it did not make"."""
    status, body = await harness.whole("POST", path, _WELL_FORMED[path])

    assert status in {200, 422}, body
    assert [name for name, _ in harness.engine.calls] == [_ADDED[path]]


async def test_the_gateway_composes_no_operation_out_of_two(harness: Harness) -> None:
    """§1: an act is one call. The read ADR-0151 §7 prescribes after an unread outcome
    is the **browser's** own request, so a failed act leaves exactly one call behind."""
    async with _harness(_Failing(ConnectionStoreError("the store did not answer"))) as one:
        status, body = await one.whole(
            "POST", "/connection/connect", _WELL_FORMED[_CREDENTIAL_PATHS[0]]
        )

        assert status == 422, body
        assert [name for name, _ in one.engine.calls] == ["connect_account"]


async def test_what_is_connected_takes_no_argument_and_is_not_paged(
    harness: Harness,
) -> None:
    """ADR-0151 §9: ``connected_accounts`` "takes no argument, is not paged, and
    admits no ``limit`` and no ``offset``" — so a member a browser sends reaches
    nothing, and the gateway invents no paging of its own."""
    status, body = await harness.whole("POST", "/connections", {"limit": 3, "offset": 9})

    assert status == 200, body
    assert harness.engine.calls == [("connected_accounts", {})]


async def test_the_log_carries_a_limit_and_deliberately_no_offset(harness: Harness) -> None:
    """ADR-0151 §9: one argument, and "there is deliberately no ``offset``" — an
    offset over a store that has none "is a paging surface that lies about its cost"
    (ADR-0102 §10)."""
    status, body = await harness.whole("POST", "/connections/recent", {"limit": 4, "offset": 2})

    assert status == 200, body
    assert harness.engine.calls == [("recent_connection_acts", {"limit": 4})]


async def test_a_non_positive_limit_is_refused_by_the_operations_own_rule(
    harness: Harness,
) -> None:
    """ADR-0151 §2a makes ``limit`` strictly positive — "stricter than ADR-0085 §9's
    ``[0, 2**63)``" — and that rule is the *operation's* rather than the argument's,
    so it is left where the contract puts it rather than re-derived in this adapter."""
    status, body = await harness.whole("POST", "/connections/recent", {"limit": 0})

    assert status == 400
    assert body["fault"] == "rejected"


# --- ADR-0151 §4, §9: what a record and an act look like on the wire ----------


async def test_a_live_record_carries_four_members_and_no_credential(
    harness: Harness,
) -> None:
    """ADR-0177 §4's sixth clause: "No response to any of the five connection
    operations carries the credential or any value derived from it, and no lane adds a
    read-back" — restated because "a browser form's natural behaviour is to redisplay
    what was submitted".

    Four members, which is ADR-0151 §4's whole type: no credential slot, no
    ``SecretName``, no endpoint and no timestamp.
    """
    account = await _connected(harness)

    assert set(account) == {"reference", "identity", "revision", "state"}
    assert "sekrit" not in str(account)


async def test_the_identity_crosses_byte_for_byte(harness: Harness) -> None:
    """ADR-0151 §5: nothing "strips, case-folds, case-normalises or Unicode-normalises
    it, at the surface or below, and what is returned is byte-for-byte what was
    supplied"."""
    identity = "  Adá Lovelace  "

    account = await _connected(harness, identity)

    assert account["identity"] == identity


async def test_the_revision_crosses_losslessly(harness: Harness) -> None:
    """ADR-0151 §4: the revision is "reported as the store holds it: nothing
    renumbers, compacts, offsets or resets it".

    A JSON number is an IEEE-754 double in the one reader that matters, and
    ``revision`` has no upper bound in the type — so it is spelled the way
    ``interruption_budget`` already is.
    """
    account = await _connected(harness)

    assert account["revision"] == "1"


async def test_a_pending_record_is_carried_with_its_state(harness: Harness) -> None:
    """ADR-0151 §4: a pending reference "is neither omitted nor substituted for by the
    previous act's record", so the state crosses and the page is what says what it
    means."""
    account = await _connected(harness)

    status, body = await harness.whole("POST", "/connections", {})

    assert status == 200, body
    assert [one["state"] for one in body["accounts"]] == ["active"]
    assert body["accounts"][0]["reference"] == account["reference"]


async def test_a_disconnection_that_removed_nothing_is_not_a_disconnection(
    harness: Harness,
) -> None:
    """ADR-0151 §8: a ``None`` "is **not** a report of a disconnection… It says one
    thing — no live record was removed by this call"."""
    status, body = await harness.whole("POST", "/connection/disconnect", {"reference": "nope"})

    assert status == 200, body
    assert body == {"removed": None}


async def test_the_log_reads_a_removal_as_the_absence_of_the_record(
    harness: Harness,
) -> None:
    """ADR-0149 §5 forbids a third provisioning state, so a removal is the absence of
    ``account`` (ADR-0151 §4) — and the row carries no instant, because a connection
    record has none (ADR-0149 §3)."""
    account = await _connected(harness)
    await harness.whole("POST", "/connection/disconnect", {"reference": account["reference"]})

    status, body = await harness.whole("POST", "/connections/recent", {})

    assert status == 200, body
    assert [one["account"] is None for one in body["acts"]] == [True, False]
    assert all(set(one) == {"reference", "revision", "account"} for one in body["acts"])


# --- ADR-0177 §4: what a browser owes the credential it carries ---------------


async def test_the_credential_is_relayed_and_nothing_else_is_done_with_it(
    harness: Harness,
) -> None:
    """§4: "The gateway relays the credential to the promoted operation's
    ``credential`` argument and does nothing else with it: it does not log it, retain
    it beyond the call, copy it into any other value, retry a call with it, or place
    it in an admission record"."""
    with structlog.testing.capture_logs() as records:
        await _connected(harness)
        harness.timers.fire_all()

    assert "sekrit" not in str(records)
    assert [name for name, _ in harness.engine.calls] == ["connect_account"]


async def test_a_credential_that_is_not_an_admissible_secret_is_the_gateways_own_refusal(
    harness: Harness,
) -> None:
    """ADR-0125 §3 makes ``secret_value`` the only supported way to build one, and
    ADR-0125 §6 guarantees the refusal "names neither the value nor its length".

    Its own condition rather than ``rejected``: that name is what
    :func:`_relay_fault` gives a refusal the *hub* authored, and no hub was asked.
    """
    status, body = await harness.whole(
        "POST", "/connection/connect", {"identity": "me", "credential": " " * 3}
    )

    assert status == 400
    assert body["fault"] == "credential-unusable"
    assert harness.engine.calls == []


async def test_an_oversized_credential_is_refused_before_anything_is_opened(
    harness: Harness,
) -> None:
    """The same door, at ADR-0125 §3's bound. Refused locally, so nothing is sent."""
    status, body = await harness.whole(
        "POST",
        "/connection/connect",
        {"identity": "me", "credential": "x" * (SECRET_VALUE_MAX_BYTES + 1)},
    )

    assert status == 400
    assert body["fault"] == "credential-unusable"
    assert str(SECRET_VALUE_MAX_BYTES + 1) not in body.get("detail", "")
    assert harness.engine.calls == []


async def test_a_missing_credential_member_is_malformed_and_reaches_no_call(
    harness: Harness,
) -> None:
    """The member is required and is named ``credential`` — §4's second clause, so
    ``core/logging.py``'s key-name redaction reaches it wherever a payload mapping is
    logged."""
    status, body = await harness.whole("POST", "/connection/connect", {"identity": "me"})

    assert status == 400
    assert body["fault"] == "malformed-request"
    assert harness.engine.calls == []


# --- ADR-0177 §3: the listener decides, and nothing the browser says does -----


@pytest.mark.parametrize("path", _CREDENTIAL_PATHS)
async def test_the_two_credential_operations_are_refused_on_the_remote_listener(
    path: str,
) -> None:
    """§3: on the remote browser listener ``connect_account`` and
    ``reprovision_account`` are **not** admitted, and a request for one is "refused on
    a condition of its own — reported as its own condition, naming that credential
    entry is available on a loopback origin only, and never flattened into an absent
    path"."""
    async with _remote() as one:
        cookie_half, header_half = await _start_session(one)

        answer = await _framed(one, path, _WELL_FORMED[path], header_half, cookie_half)

        assert answer.status == 403
        assert answer.payload["fault"] == "credential-entry-loopback-only"
        assert "loopback" in answer.payload["detail"]
        assert one.engine.calls == []


@pytest.mark.parametrize("path", _REFERENCE_PATHS)
async def test_the_three_reference_operations_are_admitted_on_the_remote_listener(
    path: str,
) -> None:
    """§3: "On ADR-0174's remote browser listener, ``disconnect_account``,
    ``connected_accounts`` and ``recent_connection_acts`` are admitted".

    Refusing all five "would be conservatism applied to the wrong noun — it would deny
    the owner a connection *listing* on their phone for a reason that is about a
    password field".
    """
    async with _remote() as one:
        cookie_half, header_half = await _start_session(one)

        answer = await _framed(one, path, _WELL_FORMED[path], header_half, cookie_half)

        assert answer.status == 200, answer.body
        assert [name for name, _ in one.engine.calls] == [_ADDED[path]]


async def test_the_refusal_precedes_the_body_being_read() -> None:
    """§3 is decided "from the listener the request arrived on and from nothing the
    browser asserts", so a body this surface would otherwise call malformed is refused
    on §3's condition instead — which is the observable form of a credential that is
    never parsed on the way to being refused."""
    async with _remote() as one:
        cookie_half, header_half = await _start_session(one)

        answer = await _framed(one, "/connection/connect", {}, header_half, cookie_half)

        assert answer.status == 403
        assert answer.payload["fault"] == "credential-entry-loopback-only"


async def test_the_refusal_is_not_lifted_by_the_device_being_listed() -> None:
    """§3: it "is not lifted by ADR-0174 §4's admission, by a device appearing in
    ``gateway_remote_browser_devices``, or by any configuration this ADR does not
    name" — and the device here is listed, which is the only way the session exists."""
    async with _remote() as one:
        cookie_half, header_half = await _start_session(one)

        answer = await _framed(
            one,
            "/connection/connect",
            _WELL_FORMED["/connection/connect"],
            header_half,
            cookie_half,
        )

        assert answer.status == 403
        assert answer.payload["fault"] == "credential-entry-loopback-only"


async def test_the_same_gateways_loopback_listener_still_admits_the_credential_pair() -> None:
    """§3: "On the gateway's loopback listener (ADR-0168 §2), all five connection
    operations are admitted, ``connect_account`` and ``reprovision_account``
    included" — on the very gateway whose remote listener refuses them, so the split
    is the listener and not the process."""
    async with _remote() as one:
        value = bootstrap_value(one.gateway)
        answer = await _send_loopback(one, "/session", {"bootstrap_value": value}, None, None)
        assert answer.status == 200, answer.body
        cookie = answer.header("set-cookie")
        assert cookie is not None
        cookie_half = cookie.split(";")[0].partition("=")[2]
        header_half = answer.payload["header_half"]

        answer = await _send_loopback(
            one,
            "/connection/connect",
            _WELL_FORMED["/connection/connect"],
            header_half,
            cookie_half,
        )

        assert answer.status == 200, answer.body
        assert [name for name, _ in one.engine.calls] == ["connect_account"]


async def test_the_refusal_is_recorded_nowhere() -> None:
    """ADR-0168 §6: the gateway records "a request refused on a condition of §3, §4,
    §5, §6 or §7" and "nothing for a refusal on any other ground".

    ADR-0177 §3's condition is none of those and §11 adds no clause to ADR-0168, so
    :class:`.records.RefusalCondition` does not grow and no record is written. The
    refusal is still its own condition — it is carried in the body, where the page
    reads it.
    """
    async with _remote() as one:
        cookie_half, header_half = await _start_session(one)

        with structlog.testing.capture_logs() as records:
            answer = await _framed(
                one,
                "/connection/connect",
                _WELL_FORMED["/connection/connect"],
                header_half,
                cookie_half,
            )
            one.timers.fire_all()

        assert answer.status == 403
        emitted = [record for record in records if record["event"] == "gateway.admission"]
        assert [record["outcome"] for record in emitted] == []


async def test_a_refused_connection_request_leaves_the_connection_open() -> None:
    """It is an answer to an admitted request rather than one of ADR-0168 §3 to §7's
    refusals, so the connection survives it exactly as the residual `404` does."""
    async with _remote() as one:
        cookie_half, header_half = await _start_session(one)

        answer = await _framed(
            one,
            "/connection/connect",
            _WELL_FORMED["/connection/connect"],
            header_half,
            cookie_half,
        )

        assert answer.status == 403
        assert not answer.closed


# --- ADR-0177 §3: a gateway whose own hub is remote serves none of the five ---


@pytest.mark.parametrize("path", list(_ADDED))
async def test_a_gateway_dialling_a_remote_hub_serves_none_of_the_five(path: str) -> None:
    """§3: "A gateway that reaches its hub over ADR-0124's remote listener serves
    **none** of the five connection operations to any browser, on either listener. It
    refuses such a request on a condition of its own… never flattened into an absent
    path, an expiry, a ceiling refusal or a fault attributed to the hub."

    ADR-0151 §13's first clause is what is being kept whole: the credential's hop from
    an enrolled device to the hub is untouched and stays refused, and a refusal
    surfacing as ``hub-unreachable`` would attribute to the hub a call nobody made.
    """
    async with _harness(remote_hub_address="100.64.0.9") as one:
        status, body = await one.whole("POST", path, _WELL_FORMED[path])

        assert status == 403
        assert body["fault"] == "connections-need-a-local-hub"
        assert one.engine.calls == []


async def test_a_gateway_dialling_a_remote_hub_still_serves_the_rest() -> None:
    """§3's second clause reaches the five and nothing else: the rest of ADR-0177 §1's
    enumeration is untouched by which transport this gateway's hub is on."""
    async with _harness(remote_hub_address="100.64.0.9") as one:
        status, body = await one.whole("POST", "/beliefs", {})

        assert status == 200, body


# --- ADR-0151 §7, §8: the class of a failure is the answer --------------------


@pytest.mark.parametrize(
    ("failure", "named"),
    [
        (UnusableIdentityError("that name cannot be used"), "identity-unusable"),
        (UnknownConnectionError("no such reference"), "no-such-connection"),
        (DisplacedProvisioningError("another act took it"), "provisioning-displaced"),
        (
            IncompleteProvisioningError("the act did not complete", "conn-9"),
            "provisioning-incomplete",
        ),
        (
            ProvisioningOutcomeUnknownError(
                "the activation failed rather than returning", "conn-9"
            ),
            "provisioning-outcome-unknown",
        ),
        (ConnectionStoreError("the store did not answer"), "connection-store-unread"),
        (ResidualCredentialError("a deletion did not go", "conn-9"), "residual-credential"),
    ],
)
async def test_each_outcome_class_keeps_its_own_condition(failure: Exception, named: str) -> None:
    """ADR-0151 §7 classifies by "two facts the act knows", both of which reach a
    caller only as the exception's class — so a surface answering all seven with
    ``assistant-declined`` would oblige the page to infer them from a message.

    The order matters as much as the set: ``UnknownConnectionError`` and
    ``DisplacedProvisioningError`` are subclasses of ``ConnectionStoreError``, and the
    three say opposite things about whether anything was written.
    """
    async with _harness(_Failing(failure)) as one:
        status, body = await one.whole(
            "POST", "/connection/connect", _WELL_FORMED["/connection/connect"]
        )

        assert status == 422, body
        assert body["fault"] == named


async def test_a_class_carrying_a_reference_carries_it_to_the_browser() -> None:
    """ADR-0151 §7: after ``connect_account`` the minted reference "is the only handle
    the caller will ever have, because the mint made it" — so a class that carries one
    hands it on, and the reference is the non-secret half of ADR-0149 §3's split."""
    async with _harness(_Failing(IncompleteProvisioningError("did not complete", "conn-9"))) as one:
        status, body = await one.whole(
            "POST", "/connection/connect", _WELL_FORMED["/connection/connect"]
        )

        assert status == 422, body
        assert body["reference"] == "conn-9"


async def test_a_reduced_delivery_reports_the_reference_as_lost_rather_than_empty() -> None:
    """ADR-0085 §10a nulls ``details`` before it truncates a message, so a reduced
    delivery reconstructs the class with the default — and "an **empty** member is not
    an absent one"."""
    async with _harness(_Failing(IncompleteProvisioningError("did not complete"))) as one:
        status, body = await one.whole(
            "POST", "/connection/connect", _WELL_FORMED["/connection/connect"]
        )

        assert status == 422, body
        assert "reference" not in body


async def test_a_failure_adr_0151_does_not_classify_falls_through_to_the_three() -> None:
    """ADR-0168 §9's three conditions are total over "did the hub receive this", which
    is the question everywhere else — so anything ADR-0151 has no class for is named
    exactly as it was before this lane."""
    async with _harness(
        _Failing(OversizedValueError("the record does not fit the frame", limit=1024, size=2048))
    ) as one:
        status, body = await one.whole(
            "POST", "/connection/connect", _WELL_FORMED["/connection/connect"]
        )

        assert status == 422, body
        assert body["fault"] == "assistant-declined"


async def test_a_residual_credential_is_reported_on_a_disconnection_too() -> None:
    """ADR-0151 §8: after ``disconnect_account`` a residual "means the removal entry
    **landed** and at least one credential deletion did not… A client reports the
    reference as disconnected **and** the deletion as incomplete, and never as a
    failed disconnection"."""
    async with _harness(
        _Failing(ResidualCredentialError("a deletion did not go", "conn-9"))
    ) as one:
        status, body = await one.whole("POST", "/connection/disconnect", {"reference": "conn-9"})

        assert status == 422, body
        assert body["fault"] == "residual-credential"
        assert body["reference"] == "conn-9"


async def _framed(
    one: Remote, path: str, payload: dict[str, Any], header_half: str, cookie_half: str
) -> Answer:
    """Send one admitted request to the **remote** listener and read the answer."""
    body = json.dumps(payload).encode()
    head = "\n".join(
        [
            f"POST {path} HTTP/1.1",
            "Host: {host}",
            f"Origin: http://{one.authority}",
            "Content-Type: application/json",
            f"Content-Length: {len(body)}",
            f"X-Assistant-Session: {header_half}",
            f"Cookie: assistant_session={cookie_half}",
        ]
    )
    return await one.send(head, body)


async def _send_loopback(
    one: Remote,
    path: str,
    payload: dict[str, Any],
    header_half: str | None,
    cookie_half: str | None,
) -> Answer:
    """Send one request to the **loopback** listener of a two-listener gateway."""
    body = json.dumps(payload).encode()
    lines = [
        f"POST {path} HTTP/1.1",
        f"Host: {one.loopback_authority}",
        f"Origin: http://{one.loopback_authority}",
        "Content-Type: application/json",
        f"Content-Length: {len(body)}",
    ]
    if header_half is not None:
        lines.append(f"X-Assistant-Session: {header_half}")
    if cookie_half is not None:
        lines.append(f"Cookie: assistant_session={cookie_half}")
    reader, writer = await one.connect_loopback()
    writer.write("\r\n".join(lines).encode() + b"\r\n\r\n" + body)
    await writer.drain()
    answer = await _read_answer(reader)
    writer.close()
    return answer


async def test_an_identity_the_contract_refuses_is_refused_by_the_real_implementation(
    harness: Harness,
) -> None:
    """ADR-0151 §5's four refusals, through the shipped fake rather than a scripted
    exception: an identity carrying a line break is one of them, and it is raised
    "locally, before any I/O", so nothing is written and the hub is never asked.

    What the *page* may say about it is pinned in ``test_bundle.py``: the credential
    reached this gateway, which is the hop a browser has already spent by then.
    """
    status, body = await harness.whole(
        "POST", "/connection/connect", {"identity": "ada\nlovelace", "credential": "sekrit"}
    )

    assert status == 422, body
    assert body["fault"] == "identity-unusable"
    assert "ada" not in body["detail"]
    assert "sekrit" not in body["detail"]


async def test_an_identity_equal_to_the_credential_is_refused_and_names_neither(
    harness: Harness,
) -> None:
    """ADR-0149 §4's third answer to a credential pasted into the identity field, and
    ADR-0151 §5's message rule: it "names neither value, no part of either, and no
    length of either"."""
    with structlog.testing.capture_logs() as records:
        status, body = await harness.whole(
            "POST", "/connection/connect", {"identity": "sekrit", "credential": "sekrit"}
        )

    assert status == 422, body
    assert body["fault"] == "identity-unusable"
    assert "sekrit" not in body["detail"]
    assert "sekrit" not in str(records)
