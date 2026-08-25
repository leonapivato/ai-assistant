r"""``TransportEndpoint``'s own construction-time refusals (ADR-0191 §1, §4).

**These cannot live in either transport conformance suite, and the reason is the
one ADR-0097 §10 gives for `SourceGrant`'s.** Every case in
``tests/core/transport_contract.py`` starts from a *valid* endpoint — the module's
``ENDPOINT`` and ``UPGRADE_ENDPOINT`` constants — so an implementation that
shipped this type with none of its validators would pass both suites end to end
while admitting an endpoint no implementation can honour.

**And the endpoint is where ADR-0191 §4's pin is decided.** §4 obliges an
implementation to open "a connection to the host and port of the
``TransportEndpoint`` it was handed" and to verify a certificate "against the
endpoint's host". A host carrying a ``NUL`` makes both unsatisfiable rather than
merely awkward: ``getaddrinfo`` hands the string to a C library that stops at the
first ``NUL``, so ``"127.0.0.1\x00mail.example.invalid"`` resolves to
``127.0.0.1`` — a connection to a host the value does not name. Adversarial
review found that on round 4 of this lane's review, reaching the opener.

The refusal is on the type rather than in each implementation on §1's own
reasoning about ``read``'s domain: making the spelling unrepresentable closes it,
where asking every implementation to remember does not.
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


# --- §4: the host a resolver would truncate ----------------------------------


def test_a_host_carrying_an_embedded_nul_is_refused() -> None:
    """§4: the destination pin, closed where a C library would truncate it.

    ``"127.0.0.1\\x00mail.example.invalid"`` is one string to Python and two to
    ``getaddrinfo``, which stops at the ``NUL`` and resolves ``127.0.0.1``. Under
    the upgrade TLS mode that is a cleartext channel to a host the endpoint does
    not name; under implicit TLS the name a certificate is verified against is
    truncated the same way. Neither is reachable if the value cannot be built.

    The message names the offending code point rather than the host — pydantic
    renders the input it refused, which is its own behaviour and is why
    ``parse_smtp_endpoint`` converts this into a ``TransportPinError`` whose text
    is written fresh.
    """
    with pytest.raises(ValidationError, match=r"U\+0000"):
        endpoint(host="127.0.0.1\x00mail.example.invalid")


@pytest.mark.parametrize(
    "host",
    ["mail.example.invalid\r", "mail\nexample.invalid", "mail.example.invalid\x1b"],
    ids=["carriage-return", "newline", "escape"],
)
def test_a_host_carrying_any_other_control_character_is_refused(host: str) -> None:
    """The rule is over control characters, not over the one that was found.

    ``NUL`` is the one adversarial review reached the opener with, and a rule
    written for it alone would be a pin against one code point: a bare ``\\r`` or
    ``\\n`` in a host is a header-injection shape wherever such a value is later
    written into a protocol line, and none of these is a host anything legitimate
    configures.

    Args:
        host: A host carrying one control character.
    """
    with pytest.raises(ValidationError, match="control character"):
        endpoint(host=host)


@pytest.mark.parametrize(
    "host",
    ["mail.example.invalid", "MAIL.example.invalid", "127.0.0.1", "::1", "xn--bcher-kva.invalid"],
    ids=["name", "mixed-case", "ipv4", "ipv6", "punycode"],
)
def test_every_host_a_deployment_could_legitimately_name_is_accepted(host: str) -> None:
    """The control, so the refusals above are not passing by refusing everything.

    A rule this narrow is worth stating only if it costs nothing an operator would
    write down, and none of these carries a control character. The host is also
    kept verbatim — two spellings of one host stay two endpoints (ADR-0148 §2's
    exactness default), which the seam's grammar pins from its own side.

    Args:
        host: A host a deployment could name.
    """
    assert endpoint(host=host).host == host
