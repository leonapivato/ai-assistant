"""One canonicaliser per protocol, at the seam, refusing what it cannot prove.

ADR-0148 §2 in code, for the one protocol email speaks. Every clause of that
section reads on this module:

- **Per protocol, in one place.** :func:`canonicalise` dispatches on
  :class:`DestinationProtocol` through :data:`_CANONICALISERS`, which is the
  whole of the mapping. "No integration supplies its own canonicaliser for a
  protocol the seam already canonicalises, so that two integrations speaking one
  protocol cannot disagree about whether two destinations are the same
  recipient" — so an integration imports this and passes a protocol, and there is
  nowhere for it to register a second answer.
- **Exact where equivalence is unproven.** "No canonicaliser folds case, strips,
  reorders or rewrites a form on any ground weaker than the protocol saying those
  two forms are one recipient." RFC 5321 §2.4 says exactly one thing this
  module may act on: mailbox domains are case-insensitive and local parts are
  **not**. So the domain is lowered and the local part is copied byte for byte.
  Everything the RFC leaves to the receiving host — a quoted local part, an
  internationalised domain, an address literal — is **refused** rather than
  guessed at, which is §1's third clause and the fail-closed direction §2 argues
  for at length: "lowercasing an address whose local part the protocol treats as
  case-sensitive lets a grant for one address authorise another; provider
  aliasing gives the inverse failure."
- **Both forms survive.** :class:`Destination` carries the supplied form beside
  the canonical one and neither is derivable from the other, which is §2's fourth
  clause and the **alias** case ADR-0148 §14 requires a test for.
- **No I/O of any kind.** A canonicaliser that asked a remote service what a name
  denotes would be performing the resolution §5 governs — the ungated back door
  #93 item 4 describes, "arriving through the one component nobody would think to
  look at". This module imports the standard library's character classes and
  `core`, and nothing else; ``tests/tools/test_destinations.py`` holds it to that
  against its own syntax tree.

**Nothing here transmits and nothing here authorises a byte.** ADR-0017 §2 leaves
the `tools/` boundary approved and *undesignated*, ADR-0148 supplies mechanisms
and designates nothing, and this module is one mechanism: a pure function from a
string to a pair of strings.

**No refusal names the value it refused.** An address is Tier 1 (ADR-0004 §1) and
a refusal message is exactly the string that ends up in a log or in a
``ToolFailure``; ``tools/invocation.py`` declines to interpolate ``str(exc)`` for
the same reason. So a refusal states the rule that was broken and, from
:mod:`ai_assistant.tools.egress_binder`, *where* in the arguments it was broken —
never what was in it.
"""

from __future__ import annotations

import string
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Final

from ai_assistant.core.errors import ToolError

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping


class DestinationProtocol(StrEnum):
    """A protocol whose rules decide when two supplied forms name one recipient.

    The unit ADR-0148 §2 states its canonicalisation rule over: "For every
    destination-bearing argument of an egress call, a **canonical form** is
    computed under the rules of the protocol that names that destination". One
    member per protocol the seam can canonicalise, and a protocol with no member
    has no canonicaliser, so a destination in it cannot be completed and the
    request carrying it is refused before the ruling (§1's third clause).
    """

    SMTP = "smtp"
    """An RFC 5321 mailbox: ``local-part@domain``, the address email speaks."""


class DestinationCanonicalisationError(ToolError):
    """A supplied destination has no canonical form this seam will assert.

    Two distinct causes, deliberately not distinguished by type: the form is not
    a valid destination in its protocol at all, or it is one whose equivalence to
    other forms the protocol does not establish. Both end the same way — ADR-0148
    §1's third clause refuses the request **before the ruling**, so no user is
    asked about a call that cannot be performed (ADR-0145's precedent) — and a
    caller that branched on the difference would be choosing to proceed on one of
    them.

    Carries no destination value, for the reason this module's docstring gives.
    """


@dataclass(frozen=True, slots=True)
class Destination:
    """One selected recipient, in both the form supplied and its canonical form.

    Frozen because ADR-0148 §4's third clause forbids any component adding to,
    removing from, substituting within or reordering the destination set between
    the ruling and transmission, and a mutable member would make the set's
    immutability a convention rather than a property.

    A `tools/`-internal value, not a `core` type: what carries these into an
    ``ActionRequest`` is ADR-0148 §11's surface (a), which is deferred to its own
    contract ADR and is not this lane's to choose (golden rule 5).

    Attributes:
        protocol: The protocol under whose rules ``canonical`` was computed.
        supplied: The form the arguments carried, byte for byte. Never
            reconstructed from ``canonical`` and never dropped — ADR-0148 §14's
            alias case fails an implementation that records only the canonical
            form *and* one that reconstructs the supplied form from it.
        canonical: The form comparison and authorisation are done against.
    """

    protocol: DestinationProtocol
    supplied: str
    canonical: str


#: RFC 5322 §3.2.3 ``atext``, which RFC 5321 §4.1.2's ``Atom`` is built from. The
#: printable ASCII specials outside it — ``"``, ``(``, ``)``, ``<``, ``>``, ``[``,
#: ``]``, ``:``, ``;``, ``@``, ``\``, ``,`` and space — are what a display name, a
#: comment, a quoted local part and an address literal are written with, and each
#: of those is refused below rather than parsed.
_ATEXT: Final = frozenset(string.ascii_letters + string.digits + "!#$%&'*+-/=?^_`{|}~")

#: RFC 5321 §4.1.2 ``Ldh-str``: the interior of a domain label.
_LDH: Final = frozenset(string.ascii_letters + string.digits + "-")

#: RFC 5321 §4.5.3.1.1: the maximum total length of a local part, in octets.
_MAX_LOCAL_PART_OCTETS: Final = 64

#: RFC 5321 §4.5.3.1.2: the maximum total length of a domain name, in octets.
_MAX_DOMAIN_OCTETS: Final = 255

#: RFC 1035 §2.3.4, carried by RFC 5321 §4.1.2's grammar: one label's maximum.
_MAX_LABEL_OCTETS: Final = 63


def _refuse(reason: str) -> DestinationCanonicalisationError:
    """Build the refusal for ``reason``, which never quotes the offending value."""
    return DestinationCanonicalisationError(reason)


def _split_smtp_mailbox(supplied: str) -> tuple[str, str]:
    """Split an addr-spec into its local part and its domain.

    Everything refused here is refused *before* the two halves exist, so no later
    check has to reason about a form that is not a mailbox at all.

    Args:
        supplied: The argument value, exactly as it was given.

    Returns:
        The local part and the domain, neither altered.

    Raises:
        DestinationCanonicalisationError: If ``supplied`` is not a bare RFC 5321
            addr-spec with exactly one ``@`` separating two non-empty halves.
    """
    if not supplied:
        raise _refuse("an empty string is not an email address")
    if not supplied.isascii():
        # SMTPUTF8 (RFC 6531) and IDNA are both live, and they disagree: whether
        # a U-label and its A-label are one recipient depends on IDNA2003 vs
        # IDNA2008 mapping, which this seam is not entitled to pick. §2's default
        # applies — the protocol does not establish the equivalence, so refuse.
        raise _refuse(
            "a non-ASCII email address is refused: whether an internationalised "
            "domain and its punycode form are one recipient is not established "
            "(RFC 6531, RFC 5890), and ADR-0148 §2 refuses rather than guesses"
        )
    if any(character.isspace() or not character.isprintable() for character in supplied):
        # Not stripped: stripping is a rewrite, and §2 permits none on a ground
        # weaker than the protocol saying two forms are one recipient. RFC 5321's
        # addr-spec contains no whitespace, so a form carrying any is not one.
        raise _refuse(
            "an email address contains no whitespace or control characters "
            "(RFC 5321 §4.1.2); it is refused rather than trimmed"
        )
    if supplied.count("@") != 1:
        # Counted rather than split from the right, because the form that would
        # make the count exceed one is a quoted local part, which is refused.
        raise _refuse(
            "an email address is one local part, one '@' and one domain "
            "(RFC 5321 §4.1.2); a display name, an angle-addr or a group is not "
            "canonicalised here"
        )
    local_part, domain = supplied.split("@")
    if not local_part:
        raise _refuse("an email address has a non-empty local part (RFC 5321 §4.1.2)")
    if not domain:
        raise _refuse("an email address has a non-empty domain (RFC 5321 §4.1.2)")
    return local_part, domain


def _check_smtp_local_part(local_part: str) -> None:
    """Require an RFC 5321 ``Dot-string``, refusing every other lawful spelling.

    A quoted local part is *lawful* and is refused anyway, which is the section's
    point: RFC 5321 §2.4 assigns the local part's semantics to the receiving host
    alone, so whether ``"john smith"@example.com`` and ``john.smith@example.com``
    denote one mailbox is a question only that host can answer. Refusing costs a
    recoverable error the user sees; guessing costs a disclosure nobody can detect
    afterwards.

    Args:
        local_part: The half before the ``@``, unaltered.

    Raises:
        DestinationCanonicalisationError: If it is not a dot-atom, or exceeds
            RFC 5321 §4.5.3.1.1's length.
    """
    if len(local_part.encode()) > _MAX_LOCAL_PART_OCTETS:
        raise _refuse(
            f"a local part is at most {_MAX_LOCAL_PART_OCTETS} octets (RFC 5321 §4.5.3.1.1)"
        )
    if local_part.startswith('"') or '"' in local_part or "\\" in local_part:
        raise _refuse(
            "a quoted local part is refused: RFC 5321 §2.4 leaves its "
            "interpretation to the receiving host, so its equivalence to any "
            "other form is not established"
        )
    if local_part.startswith(".") or local_part.endswith(".") or ".." in local_part:
        raise _refuse(
            "a local part is dot-separated atoms, so it neither begins nor ends "
            "with a dot nor holds two in a row (RFC 5321 §4.1.2)"
        )
    if any(character not in _ATEXT for character in local_part.replace(".", "")):
        raise _refuse(
            "a local part outside RFC 5322 §3.2.3's atext is refused; a comment, "
            "an address literal and a routed path are not canonicalised here"
        )


def _check_smtp_domain(domain: str) -> None:
    """Require an RFC 5321 ``Domain``: dot-separated let-dig-hyphen labels.

    Refusing an address literal is the same judgement as refusing a quoted local
    part. ``[192.0.2.1]`` and ``[IPv6:2001:db8::1]`` are lawful destinations whose
    equivalence classes are the IP stack's — ``2001:db8::1`` and
    ``2001:0db8:0:0:0:0:0:1`` are one host and are not one string — and folding
    them is arithmetic this seam has no mandate to do.

    Args:
        domain: The half after the ``@``, unaltered.

    Raises:
        DestinationCanonicalisationError: If it is not a dot-separated sequence of
            conforming labels, or exceeds RFC 5321 §4.5.3.1.2's length.
    """
    if len(domain.encode()) > _MAX_DOMAIN_OCTETS:
        raise _refuse(f"a domain is at most {_MAX_DOMAIN_OCTETS} octets (RFC 5321 §4.5.3.1.2)")
    if domain.startswith("["):
        raise _refuse(
            "an address literal is refused: its equivalence class belongs to the "
            "IP stack (RFC 5321 §4.1.3), not to this seam"
        )
    for label in domain.split("."):
        # A trailing dot lands here as an empty final label and is refused with
        # every other empty one. It is *not* stripped: the root-relative form is
        # outside RFC 5321 §4.1.2's grammar, and trimming it would be the rewrite
        # ADR-0148 §2's second clause forbids.
        if not label:
            raise _refuse(
                "a domain is non-empty labels separated by single dots, with no "
                "trailing dot (RFC 5321 §4.1.2); it is refused rather than trimmed"
            )
        if len(label) > _MAX_LABEL_OCTETS:
            raise _refuse(f"a domain label is at most {_MAX_LABEL_OCTETS} octets (RFC 1035 §2.3.4)")
        if not (label[0].isalnum() and label[-1].isalnum()):
            raise _refuse("a domain label begins and ends with a letter or digit (RFC 5321 §4.1.2)")
        if any(character not in _LDH for character in label):
            raise _refuse("a domain label holds only letters, digits and hyphens (RFC 5321 §4.1.2)")


def _canonical_smtp_address(supplied: str) -> str:
    """Return the canonical form of an RFC 5321 mailbox.

    One transformation and one only: the domain is lowered, because RFC 5321 §2.4
    says mailbox domains "are not case sensitive" and RFC 4343 restates it for
    DNS. The local part is returned exactly as supplied, because the same section
    says it "MUST BE interpreted and assigned semantics only by the host specified
    in the domain part" — the case-sensitive local part ADR-0017 §3 names as the
    motivating hazard and #93 item 3 spells out.

    ``str.lower`` rather than ``str.casefold``: the address is ASCII by the time
    this runs, where the two agree, and ``lower`` is the ASCII case mapping RFC
    4343 actually specifies. ``casefold`` folds ``ß`` to ``ss`` and would be a
    rewrite on a ground the protocol does not supply.

    Args:
        supplied: The argument value, exactly as it was given.

    Returns:
        ``local-part@lowered-domain``.

    Raises:
        DestinationCanonicalisationError: If ``supplied`` is not a form this seam
            will canonicalise; see the checks above for each ground.
    """
    local_part, domain = _split_smtp_mailbox(supplied)
    _check_smtp_local_part(local_part)
    _check_smtp_domain(domain)
    return f"{local_part}@{domain.lower()}"


#: The whole of the seam's canonicalisation surface: one entry per protocol, and
#: no registration function beside it. ADR-0148 §2's sixth clause is a property of
#: this mapping being the only one — "#83's reason applied on the destination
#: axis", where a per-integration canonicaliser makes a standing authorisation
#: mean different things in different tools with no test detecting it.
_CANONICALISERS: Final[Mapping[DestinationProtocol, Callable[[str], str]]] = {
    DestinationProtocol.SMTP: _canonical_smtp_address,
}


def canonicalise(protocol: DestinationProtocol, supplied: str) -> Destination:
    """Return ``supplied`` beside its canonical form under ``protocol``'s rules.

    Pure and total in the sense ADR-0148 §2's fifth clause requires: it reads no
    clock, no store, no configuration and no network, so two derivations of the
    same input agree and nothing here can become the resolution path §5 governs.

    Args:
        protocol: The protocol under whose rules equivalence is decided.
        supplied: The destination as the call's arguments carry it.

    Returns:
        Both forms, with ``supplied`` unaltered.

    Raises:
        DestinationCanonicalisationError: If the protocol has no canonicaliser at
            this seam, the supplied form is not text, or it is one this seam will
            not assert a canonical form for. ADR-0148 §1's third clause refuses
            the whole request rather than sending it for a ruling in an
            incomplete form.
    """
    # Checked **before** it is used as a key: an unhashable value raises from
    # `Mapping.get` itself, ahead of any branch this function could refuse in
    # (adversarial round 10), and the round-7 repair below could not reach that.
    # The member's own value is named where there is one, because an enum member
    # is the tool author's text; anything else is caller-supplied and could carry
    # content, so it is described rather than rendered.
    given: object = protocol
    if not isinstance(given, DestinationProtocol):
        raise _refuse("no canonicaliser at this seam for the protocol given")
    form: object = supplied
    if not isinstance(form, str):
        # A destination that is not text has no canonical form and no supplied
        # form to preserve, and every check below is a string operation — so it
        # is refused here rather than raising an `AttributeError` from inside a
        # guard (adversarial round 13). `select_destinations` already refuses a
        # non-string entry, so this closes the direct-call path.
        raise _refuse("a destination that is not text has no canonical form")
    canonicaliser = _CANONICALISERS.get(given)
    if canonicaliser is None:
        raise _refuse(f"no canonicaliser at this seam for protocol {given.value!r}")
    return Destination(protocol=given, supplied=form, canonical=canonicaliser(form))


def canonical_destination_set(destinations: tuple[Destination, ...]) -> tuple[str, ...]:
    """The call's canonical destination set: the distinct canonical forms it selects.

    ADR-0148 §2's first clause defines the set as "the set of canonical forms of
    every semantic recipient its arguments select", so two arguments supplying
    two spellings of one recipient contribute **one** member — while both supplied
    forms stay on the occurrences the description and the audit record carry
    (§2's fourth clause). Sorted, because §4 authorises the set "as a single
    value" and a value whose order depended on which argument happened to name a
    recipient first would compare unequal to itself.

    Args:
        destinations: The occurrences the arguments selected, in any order.

    Returns:
        The distinct canonical forms, sorted.

    Raises:
        DestinationCanonicalisationError: If a member is not a
            :class:`Destination` — the set is what a ruling is taken over
            (ADR-0148 §4), so a member with no canonical form is refused rather
            than skipped.
    """
    canonical: set[str] = set()
    for entry in destinations:
        member: object = entry
        if not isinstance(member, Destination):
            raise _refuse("a destination set holds canonicalised destinations")
        canonical.add(member.canonical)
    return tuple(sorted(canonical))


__all__ = [
    "Destination",
    "DestinationCanonicalisationError",
    "DestinationProtocol",
    "canonical_destination_set",
    "canonicalise",
]
