"""The SMTP canonicaliser: one rule applied, everything else refused.

ADR-0148 §2's exactness default is the security content of the whole section, and
these tests are stated over the two directions it names (#93 item 3): "lowercasing
an address whose local part the protocol treats as case-sensitive lets a grant for
one address authorise another; provider aliasing gives the inverse failure." So
the file asserts *both* that the domain folds and that the local part does not,
and treats every form whose equivalence RFC 5321 does not establish as a refusal
rather than as a case somebody may later make work.
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
