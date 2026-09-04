"""The seam's canonicalisers: one rule applied per protocol, everything else refused.

ADR-0148 §2's exactness default is the security content of the whole section, and
these tests are stated over the two directions it names (#93 item 3): "lowercasing
an address whose local part the protocol treats as case-sensitive lets a grant for
one address authorise another; provider aliasing gives the inverse failure." So
the file asserts *both* that the domain folds and that the local part does not,
and treats every form whose equivalence RFC 5321 does not establish as a refusal
rather than as a case somebody may later make work.

**The HTTPS half is the same discipline under ADR-0231 §8**, which states the
three equivalences that protocol establishes, six it does not, and a refusal for
every form whose equivalence class it cannot state truthfully. §18's test 10 is
what the second half of this file is written against, form by form; what belongs
to the *exchange* rather than to the canonicaliser — that a refused origin opens
no channel — is asserted in ``test_https_exchange.py`` instead.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from ai_assistant.core.errors import ToolError
from ai_assistant.tools.destinations import (
    Destination,
    DestinationCanonicalisationError,
    DestinationProtocol,
    canonical_destination_set,
    canonicalise,
)

_MODULE = Path(__file__).resolve().parents[2] / "src" / "ai_assistant" / "tools" / "destinations.py"

#: What a canonicaliser that performs no I/O is allowed to import. ADR-0148 §2's
#: fifth clause and §14's "a canonicaliser performs no I/O" case: the module reads
#: character classes and `core`'s error hierarchy, and nothing that could reach a
#: socket, a file, a clock or a store.
_PERMITTED_IMPORTS = frozenset(
    {
        "__future__",
        "string",
        "dataclasses",
        "enum",
        "typing",
        "collections.abc",
        "ai_assistant.core.errors",
    }
)


def _smtp(supplied: str) -> Destination:
    return canonicalise(DestinationProtocol.SMTP, supplied)


def _https(supplied: str) -> Destination:
    return canonicalise(DestinationProtocol.HTTPS, supplied)


def test_the_domain_folds_and_the_local_part_does_not() -> None:
    """RFC 5321 §2.4 in one assertion, both halves of it.

    This is ADR-0148 §14's alias case at its sharpest: the two supplied forms
    differ only in the domain's case, which the protocol *does* say makes them one
    recipient, so they share a canonical form — and the local part's case, which
    it does *not*, so they do not.
    """
    upper_domain = _smtp("Alice@Example.COM")
    lower_domain = _smtp("Alice@example.com")
    upper_local = _smtp("alice@example.com")

    assert upper_domain.canonical == "Alice@example.com"
    assert upper_domain.canonical == lower_domain.canonical
    assert upper_local.canonical != upper_domain.canonical


def test_the_supplied_form_survives_canonicalisation_byte_for_byte() -> None:
    """ADR-0148 §2's fourth clause: both forms are carried, and neither is derived.

    §14 fails "an implementation that records only the canonical form, and so does
    one that reconstructs a supplied form from it" — and reconstruction is exactly
    what is impossible here, since the canonical form has lost which case the
    domain was supplied in.
    """
    destination = _smtp("Bob.Smith@Mail.EXAMPLE.com")

    assert destination.supplied == "Bob.Smith@Mail.EXAMPLE.com"
    assert destination.protocol is DestinationProtocol.SMTP


def test_canonicalisation_is_deterministic_over_its_input() -> None:
    """Two derivations of one input agree, which is what ADR-0148 §6 rests on."""
    assert _smtp("a.b+tag@Example.com") == _smtp("a.b+tag@Example.com")


@pytest.mark.parametrize(
    ("supplied", "why"),
    [
        ("", "empty"),
        ("alice", "no @ at all"),
        ("alice@@example.com", "two separators"),
        ("alice@one.com@two.com", "two separators"),
        ("@example.com", "empty local part"),
        ("alice@", "empty domain"),
        (" alice@example.com", "leading whitespace, refused rather than trimmed"),
        ("alice@example.com ", "trailing whitespace, refused rather than trimmed"),
        ("alice smith@example.com", "interior whitespace"),
        ("alice@example.com\n", "a control character"),
        ("alice\t@example.com", "a tab"),
        ("Alice <alice@example.com>", "a display name is not an addr-spec"),
        ("<alice@example.com>", "an angle-addr is not an addr-spec"),
        ("alice(comment)@example.com", "an RFC 5322 comment"),
        ("alice,bob@example.com", "a list is not one destination"),
        ('"alice smith"@example.com', "a quoted local part: the receiving host's to read"),
        ('"alice"@example.com', "a quoted local part, even where it looks like an atom"),
        ("ali\\ce@example.com", "a backslash escape"),
        (".alice@example.com", "a leading dot"),
        ("alice.@example.com", "a trailing dot in the local part"),
        ("ali..ce@example.com", "two dots in a row"),
        ("alice@example..com", "an empty domain label"),
        ("alice@example.com.", "a root-relative domain, refused rather than trimmed"),
        ("alice@-example.com", "a label beginning with a hyphen"),
        ("alice@example-.com", "a label ending with a hyphen"),
        ("alice@exam_ple.com", "an underscore is not let-dig-hyp"),
        ("alice@[192.0.2.1]", "an address literal"),
        ("alice@[IPv6:2001:db8::1]", "an IPv6 literal, whose equivalence is the IP stack's"),
        ("álice@example.com", "a non-ASCII local part"),
        ("alice@exämple.com", "an internationalised domain"),
        ("alice@例え.jp", "a U-label, whose A-label equivalence IDNA does not settle"),
        ("a" * 65 + "@example.com", "a local part over RFC 5321 §4.5.3.1.1's 64 octets"),
        ("alice@" + ".".join(["a" * 63] * 4) + ".a", "a domain over §4.5.3.1.2's 255 octets"),
        ("alice@" + "a" * 64 + ".com", "a label over RFC 1035's 63 octets"),
    ],
)
def test_a_form_whose_equivalence_is_unproven_is_refused(supplied: str, why: str) -> None:
    """ADR-0148 §1's third clause is the fail-closed direction, stated case by case.

    Every entry is either not an RFC 5321 addr-spec or one whose equivalence class
    the protocol assigns to somebody else. §2: "Refusing costs a recoverable error
    the user sees; proceeding costs a disclosure nobody can detect afterwards."
    """
    with pytest.raises(DestinationCanonicalisationError):
        _smtp(supplied)

    assert why  # the reason is documentation for the reader of a failure


@pytest.mark.parametrize(
    "supplied",
    [
        "alice@example.com",
        "a" * 64 + "@example.com",
        "alice@" + "a" * 63 + ".com",
        "alice@" + ".".join(["a" * 63] * 4),
        "a.b.c@sub.domain.example.co.uk",
        "user+tag@example.com",
        "!#$%&'*+-/=?^_`{|}~@example.com",
        "alice@localhost",
        "alice@x1.example.com",
    ],
)
def test_a_conforming_addr_spec_canonicalises(supplied: str) -> None:
    """The bounds are inclusive and the grammar's full atext is accepted.

    A canonicaliser that refused the whole atext set would push integrations
    towards their own, which is the outcome ADR-0148 §2's sixth clause exists to
    prevent.
    """
    assert _smtp(supplied).supplied == supplied


def test_a_refusal_never_quotes_the_address_it_refused() -> None:
    """An address is Tier 1, and a refusal message reaches a log.

    `tools/invocation.py` declines to interpolate ``str(exc)`` for the same
    reason, and `core/logging.py` names that exact shape as the leak its
    key-based redactor cannot see.
    """
    needle = "needle-local-part"

    with pytest.raises(DestinationCanonicalisationError) as raised:
        _smtp(f'"{needle}"@example.com')

    assert needle not in str(raised.value)


def test_a_protocol_with_no_canonicaliser_refuses_without_dereferencing_it() -> None:
    """Adversarial round 7: the missing-canonicaliser branch read `.value`.

    That branch is reached exactly when the protocol is not one this seam knows,
    which includes the case where it is not a member at all — so building the
    refusal out of `protocol.value` raised `AttributeError` instead of the
    documented refusal. The member's own value is named where there is one,
    because an enum member is the tool author's text; anything else is a
    caller-supplied value and is not rendered.
    """
    needle = "the secret is swordfish"

    with pytest.raises(DestinationCanonicalisationError) as raised:
        canonicalise(needle, "alice@example.com")  # type: ignore[arg-type]

    assert needle not in str(raised.value)
    assert "no canonicaliser" in str(raised.value)


def test_an_unhashable_protocol_refuses_before_it_is_used_as_a_key() -> None:
    """Adversarial round 10: `Mapping.get` raises before any branch is reached.

    The round-7 repair guarded the missing-canonicaliser *branch*, which an
    unhashable value never reaches — the lookup itself raises `TypeError` first.
    So the check moved ahead of the lookup, which is the same ordering rule the
    declarations keep: check a value before using it, not after.
    """
    with pytest.raises(DestinationCanonicalisationError, match="no canonicaliser"):
        canonicalise([], "alice@example.com")  # type: ignore[arg-type]


@pytest.mark.parametrize("supplied", [1, b"alice@example.com", None, ["alice@example.com"]])
def test_a_supplied_destination_that_is_not_text_is_refused(supplied: object) -> None:
    """Adversarial round 13: every check below is a string operation.

    `select_destinations` already refuses a non-string entry, so this closes the
    path a direct call takes — with this seam's own refusal rather than an
    `AttributeError` raised from inside a guard.
    """
    with pytest.raises(DestinationCanonicalisationError, match="not text"):
        canonicalise(DestinationProtocol.SMTP, supplied)  # type: ignore[arg-type]


def test_a_destination_set_holding_a_non_destination_is_refused() -> None:
    """The set is what a ruling is taken over (ADR-0148 §4), so nothing is skipped."""
    with pytest.raises(DestinationCanonicalisationError, match="canonicalised destinations"):
        canonical_destination_set(("alice@example.com",))  # type: ignore[arg-type]


def test_the_refusal_is_in_the_assistant_error_hierarchy() -> None:
    """So a request builder can refuse the whole call with one handler."""
    assert issubclass(DestinationCanonicalisationError, ToolError)


def test_the_canonical_set_is_the_distinct_canonical_forms_sorted() -> None:
    """ADR-0148 §2's first clause and §4's single-value clause together.

    Two spellings of one recipient contribute one member — while both
    occurrences, and so both supplied forms, stay outside the set.
    """
    destinations = (
        _smtp("Alice@Example.com"),
        _smtp("alice@example.com"),
        _smtp("Alice@example.com"),
        _smtp("bob@example.com"),
    )

    assert canonical_destination_set(destinations) == (
        "Alice@example.com",
        "alice@example.com",
        "bob@example.com",
    )


def test_the_canonical_set_does_not_depend_on_the_order_it_is_given() -> None:
    """A value authorised "as a single value" (§4) must compare equal to itself."""
    one = _smtp("bob@example.com")
    two = _smtp("alice@example.com")

    assert canonical_destination_set((one, two)) == canonical_destination_set((two, one))


def test_the_canonicaliser_imports_nothing_that_could_perform_io() -> None:
    """ADR-0148 §2's fifth clause and §14's no-I/O case, over the syntax tree.

    Asserted against imports rather than against behaviour because the property is
    "performs no I/O of any kind", which no single call can demonstrate: what a
    test can hold is that the module has nothing to reach a network, a file, a
    clock or a store *with*. The `tools/` transport scan
    (``tests/tools/test_egress_seam.py``) is the neighbouring net and covers a
    different set — transports specifically, across every module here.
    """
    tree = ast.parse(_MODULE.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imported.add(node.module)

    assert imported <= _PERMITTED_IMPORTS, sorted(imported - _PERMITTED_IMPORTS)


# --------------------------------------------------------------------------- #
# ADR-0231 §8 — the HTTPS origin                                                #
# --------------------------------------------------------------------------- #


def test_the_scheme_and_the_host_fold_and_the_default_port_is_written_out() -> None:
    """ADR-0231 §18's test 10, first half: all three equivalences in one assertion.

    "``HTTPS://Example.COM`` and ``https://example.com:443`` canonicalise
    identically" — which is the scheme's ASCII case, the host's ASCII case, and an
    omitted port against a stated ``443``, the whole of what this protocol
    establishes.
    """
    folded = _https("HTTPS://Example.COM")

    assert folded.canonical == "https://example.com:443"
    assert folded.canonical == _https("https://example.com:443").canonical
    assert folded.canonical == _https("https://example.com").canonical


def test_the_supplied_form_survives_beside_the_canonical_one() -> None:
    """ADR-0148 §2's fourth clause, which ADR-0231 §8 does not move.

    An origin written with its default port and one written without are one
    recipient and two *forms*, and the occurrence carries both — reconstructing
    either from the other is what ADR-0148 §14 names as a failure.
    """
    stated = _https("https://Example.com:443")

    assert (stated.supplied, stated.canonical) == (
        "https://Example.com:443",
        "https://example.com:443",
    )


def test_a_stated_non_default_port_survives_into_the_canonical_form() -> None:
    """The port is rendered, never normalised: only ``443``'s omission is an equivalence."""
    assert _https("https://example.com:8443").canonical == "https://example.com:8443"
    assert _https("https://example.com:8443").canonical != _https("https://example.com").canonical


@pytest.mark.parametrize(
    "supplied",
    [
        pytest.param("http://example.com", id="a-scheme-other-than-https"),
        pytest.param("HTTP://example.com", id="the-same-scheme-in-another-case"),
        pytest.param("ftp://example.com", id="a-scheme-with-no-canonicaliser"),
        pytest.param("example.com", id="no-scheme-at-all"),
        pytest.param("https:/example.com", id="a-scheme-with-one-slash"),
        pytest.param("https://user@example.com", id="userinfo"),
        pytest.param("https://user:pass@example.com", id="userinfo-with-a-password"),
        pytest.param("https://example.com?q=1", id="a-query"),
        pytest.param("https://example.com#fragment", id="a-fragment"),
        pytest.param("https://", id="an-empty-host"),
        pytest.param("https://:443", id="an-empty-host-with-a-port"),
        pytest.param("https://exämple.com", id="an-internationalised-host"),
        pytest.param("https://xn--exmple-cua.com/", id="an-a-label-with-a-path"),
        pytest.param("https://ex%61mple.com", id="a-percent-encoded-octet"),
        pytest.param("https://example.com.", id="a-trailing-dot"),
        pytest.param("https://.example.com", id="a-leading-dot"),
        pytest.param("https://example..com", id="a-doubled-dot"),
        pytest.param("https://exa_mple.com", id="an-underscore"),
        pytest.param("https://example.com\x00.evil.com", id="a-control-character"),
        pytest.param("https:// example.com", id="a-space"),
        pytest.param("https://-example.com", id="a-label-beginning-with-a-hyphen"),
        pytest.param("https://example-.com", id="a-label-ending-with-a-hyphen"),
        pytest.param("https://[::1]", id="an-ipv6-literal"),
        pytest.param("https://[::1]:443", id="an-ipv6-literal-with-a-port"),
        pytest.param("https://example.com:", id="a-port-separator-with-no-port"),
        pytest.param("https://example.com:/", id="the-same-with-a-trailing-slash"),
        pytest.param("https://example.com:0443", id="a-port-with-a-leading-zero"),
        pytest.param("https://example.com:https", id="a-port-that-is-not-a-number"),
        pytest.param("https://example.com:٤٤٣", id="a-port-in-another-script"),
        pytest.param("https://example.com:0", id="a-port-below-the-range"),
        pytest.param("https://example.com:65536", id="a-port-above-the-range"),
        pytest.param("https://example.com:443:8443", id="two-ports"),
    ],
)
def test_an_https_form_whose_equivalence_is_unproven_has_no_canonical_form(supplied: str) -> None:
    """ADR-0231 §18's test 10, one assertion per form the ADR names.

    Every one of these is a form whose equivalence class §8 declines to state: an
    internationalised host has an IDNA answer that ADR has not evaluated, a
    trailing dot is a resolver question, a percent-encoded octet has a decoded form
    nothing here establishes an equivalence with, and ``http`` is a different
    protocol. Refusing is the direction ADR-0148 §2 argues for at length, and the
    failure that matters is two forms denoting different recipients being read as
    one.
    """
    with pytest.raises(DestinationCanonicalisationError):
        _https(supplied)


@pytest.mark.parametrize(
    "supplied",
    [
        pytest.param("https://127.0.0.1", id="the-dotted-quad-nobody-writes"),
        pytest.param("https://127.1", id="the-abbreviated-form"),
        pytest.param("https://2130706433", id="the-whole-address-as-one-decimal"),
        pytest.param("https://0x7f000001", id="the-whole-address-as-one-hexadecimal"),
        pytest.param("https://0X7F000001", id="the-same-in-upper-case"),
        pytest.param("https://192.168.0.1", id="a-private-address"),
        pytest.param("https://example.com.1", id="a-name-ending-in-a-number"),
    ],
)
def test_a_host_ending_in_a_number_is_an_ip_literal_and_is_refused(supplied: str) -> None:
    """ADR-0231 §8's decidable test, over the four spellings it names by hand.

    The label grammar admits the whole abbreviated family while catching none of
    it, and "each is resolved to ``127.0.0.1`` by the same stack
    ``asyncio.open_connection`` sits on, so a canonicaliser tested only against
    ``127.0.0.1`` refuses the one spelling nobody writes and admits the three an
    attacker would". An implementation testing for four dotted decimal octets
    passes the first arm and fails the next three.
    """
    with pytest.raises(DestinationCanonicalisationError):
        _https(supplied)


@pytest.mark.parametrize(
    ("supplied", "why"),
    [
        pytest.param(f"https://{'a' * 63}.example.com", "a label of exactly 63", id="label-63"),
        pytest.param(
            f"https://{'a' * 61}.{'b' * 61}.{'c' * 61}.{'d' * 61}.com",
            "a host of exactly 251",
            id="host-under-253",
        ),
        pytest.param("https://example.com:1", "the lowest port", id="port-1"),
        pytest.param("https://example.com:65535", "the highest port", id="port-65535"),
        pytest.param("https://0x", "0x with no hexadecimal digit after it", id="a-bare-0x"),
    ],
)
def test_the_boundary_forms_adr_0231_admits_are_admitted(supplied: str, why: str) -> None:
    """The other side of every bound, so no refusal is one form too wide.

    ``https://0x`` is here because it is the boundary §8 states in its own words —
    "``0x``/``0X`` followed by **one or more** ASCII hexadecimal digits" — and a
    canonicaliser refusing it would be refusing a form the ratified test admits,
    which is a rule this seam did not write (issue filed alongside this change).
    """
    assert _https(supplied).canonical.startswith("https://"), why


@pytest.mark.parametrize(
    "supplied",
    [
        pytest.param(f"https://{'a' * 64}.example.com", id="a-label-of-64"),
        pytest.param(
            f"https://{'a' * 61}.{'b' * 61}.{'c' * 61}.{'d' * 61}.{'e' * 61}.com",
            id="a-host-over-253",
        ),
        pytest.param("https://example.com:655360", id="a-port-of-six-digits"),
    ],
)
def test_the_boundary_forms_adr_0231_refuses_are_refused(supplied: str) -> None:
    """The pairs above, one over each bound, which fail a comparison the wrong way round."""
    with pytest.raises(DestinationCanonicalisationError):
        _https(supplied)


@pytest.mark.parametrize("supplied", ["https://example.com/", "https://example.com/a"])
def test_a_path_bearing_form_is_refused_and_yields_no_destination(supplied: str) -> None:
    """ADR-0231 §18's test 10, last paragraph, and the reason it is stated that way.

    "``https://example.com/a`` and ``https://example.com/b`` are each refused
    independently, and no test asserts that they canonicalise to anything — an
    assertion that they were 'one destination' would drive an implementation to
    strip the path, which §8 forbids in terms."

    The bare trailing slash is refused with them, and that is §8's own arithmetic
    rather than an extra rule: the equivalences this protocol establishes are
    **exactly three**, and reading ``https://example.com/`` as the same recipient
    as ``https://example.com`` would be a fourth.
    """
    with pytest.raises(DestinationCanonicalisationError):
        _https(supplied)


def test_two_paths_under_one_origin_are_not_one_destination() -> None:
    """The pair, asserted as two refusals rather than as one canonical form."""
    for supplied in ("https://example.com/a", "https://example.com/b"):
        with pytest.raises(DestinationCanonicalisationError):
            _https(supplied)


def test_no_https_refusal_renders_the_form_it_refused() -> None:
    """This module's own discipline, which an origin does not escape.

    An origin is operator configuration rather than a mailbox, but a refusal
    message still reaches a log and the value still arrived from somewhere: the
    rule this module states for an address is stated over every value it refuses.
    """
    marker = "distinctive-host-name"

    with pytest.raises(DestinationCanonicalisationError) as raised:
        _https(f"https://{marker}_x.example.com")

    assert marker not in str(raised.value)
