r"""``TransportEndpoint``'s own construction-time refusals (ADR-0191 §1, §4).

**These cannot live in either transport conformance suite, and the reason is the
one ADR-0097 §10 gives for `SourceGrant`'s.** Every case in
``tests/core/transport_contract.py`` starts from a *valid* endpoint — the module's
``ENDPOINT`` and ``UPGRADE_ENDPOINT`` constants — so an implementation that
shipped this type with none of its validators would pass both suites end to end
while admitting an endpoint no implementation can honour.

**What is *not* here, and deliberately.** ADR-0191 §4's destination pin — a host
carrying a ``NUL``, which ``getaddrinfo`` truncates at the first one, so
``"127.0.0.1\x00mail.example.invalid"`` resolves to ``127.0.0.1`` — is refused at
ADR-0154 §1's designated seam rather than on this type, and its cases live with
it in ``tests/tools/``. §1 settles this type's construction rules and marks
exhaustiveness where it means it, so a refusal it did not write is contract
surface no ADR decided (golden rule 5); architecture review found the rule
sitting here on round 12. Adversarial review found the ``NUL`` reaching the opener
on round 4, and that property is unchanged — ``parse_smtp_endpoint`` and
``StreamOutboundTransport.open_channel`` are the only constructor and the only
route to a resolver under ``src/``, and both refuse it.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from ai_assistant.core.types import TransportEndpoint

#: The valid endpoint every case below varies one field of.
VALID: dict[str, object] = {"host": "mail.example.invalid", "port": 465, "implicit_tls": True}


def endpoint(**overrides: object) -> TransportEndpoint:
    """Build a valid endpoint, overriding whichever field a case is about.

    Args:
        **overrides: What this case varies.

    Returns:
        The endpoint, where the fields are ones the type accepts.
    """
    fields = VALID | overrides
    return TransportEndpoint(**fields)  # type: ignore[arg-type]  # heterogeneous test kwargs


# --- §1: exactly three fields, frozen, and nothing else ----------------------


def test_the_endpoint_carries_exactly_three_fields() -> None:
    """§1: ``host``, ``port``, ``implicit_tls`` — "and no others".

    A roster rather than three presence assertions, because what §1 forbids is the
    *fourth* field: a scheme, a path, a credential or a recipient on this type
    would be a second place a connection's destination could be decided (#83), and
    a per-field pin cannot fail on a field nobody thought to pin.
    """
    assert set(TransportEndpoint.model_fields) == {"host", "port", "implicit_tls"}


def test_a_field_the_endpoint_does_not_declare_is_refused() -> None:
    """``extra="forbid"``: the fourth field cannot arrive as data either.

    A roster over the declared fields says nothing about a model that quietly
    carried whatever it was handed, and an endpoint holding an unread ``scheme``
    is exactly the shape §1 wrote "no others" against.
    """
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        endpoint(scheme="smtps")


def test_the_endpoint_is_frozen() -> None:
    """§1: the value a pin is compared against cannot move after the comparison.

    A holder that could reassign ``host`` between the check and the open would be
    holding a different endpoint from the one that was checked, which is the
    time-of-check failure the pin exists to prevent.
    """
    pinned = endpoint()

    with pytest.raises(ValidationError, match="frozen"):
        pinned.host = "elsewhere.invalid"


# --- §1: the host and port domains -------------------------------------------


@pytest.mark.parametrize("host", ["", " ", "\t\n "], ids=["empty", "space", "whitespace"])
def test_a_blank_host_is_refused(host: str) -> None:
    """§1: "a host that is empty or only whitespace" is refused at construction.

    An endpoint naming no host is one an implementation would hand to a resolver
    to decide, and what a resolver decides for the empty string is a localhost
    connection nobody wrote down.

    Args:
        host: A spelling of "no host".
    """
    with pytest.raises(ValidationError, match="must not be blank"):
        endpoint(host=host)


@pytest.mark.parametrize("port", [0, -1, 65536], ids=["zero", "negative", "past-the-top"])
def test_a_port_outside_its_domain_is_refused(port: int) -> None:
    """§1: ``1..65535`` inclusive, and no spelling outside it constructs.

    Args:
        port: A port no TCP connection has.
    """
    with pytest.raises(ValidationError):
        endpoint(port=port)


@pytest.mark.parametrize("port", [1, 65535], ids=["bottom", "top"])
def test_both_ends_of_the_port_domain_are_accepted(port: int) -> None:
    """The control: the bound is inclusive, so neither end is refused for free.

    Args:
        port: An end of the domain.
    """
    assert endpoint(port=port).port == port


@pytest.mark.parametrize(
    "host",
    ["mail.example.invalid", "MAIL.example.invalid", "127.0.0.1", "::1", "xn--bcher-kva.invalid"],
    ids=["name", "mixed-case", "ipv4", "ipv6", "punycode"],
)
def test_every_host_a_deployment_could_legitimately_name_is_accepted(host: str) -> None:
    """The accepted domain is wide, because §1 fixes only two refusals over it.

    The blank refusal above is worth stating only if it costs nothing an operator
    would write down, and none of these is blank. The host is also kept verbatim —
    two spellings of one host stay two endpoints (ADR-0148 §2's exactness
    default), which the seam's grammar pins from its own side.

    Args:
        host: A host a deployment could name.
    """
    assert endpoint(host=host).host == host
