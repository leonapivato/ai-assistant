"""The canonical fake ``EgressBinder`` (ADR-0152 §13, CONTRIBUTING "Adding a Protocol").

:class:`FakeEgressBinder` is a **second, independent implementation** of
:class:`~ai_assistant.core.protocols.EgressBinder`, not a scripted double. It has
to be: ADR-0152 §10 obliges a conformance suite to exercise every refusal
**directly**, against a subject handed inputs no runner would produce, and "an
implementation that refuses only what the runner would already have refused does
not satisfy this contract". A double that returned canned answers would make the
suite a test of its own script.

It shares no code with :mod:`ai_assistant.tools.egress_binder`, and that is the
whole point of a triad — ``ai_assistant.testing`` imports ``core`` and nothing
else, so the two implementations agree only because the suite holds them both to
one contract. Where they differ is in what they *hold*: this one keeps its
registrations, its connection records and its registry originals in memory and
exposes hooks to arrange them, because a test needs to put a reference into
``PENDING`` or make a read raise without a keyring, a SQLite file or a
provisioning act.

**It transmits nothing and authorises nothing.** Like every fake here it is
test-only; production code importing ``ai_assistant.testing`` fails
``lint-imports``.
"""

from __future__ import annotations

import json
import string
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from pydantic import TypeAdapter, ValidationError

from ai_assistant.core.errors import ConnectionStoreError, EgressBindingError
from ai_assistant.core.types import (
    BoundAccount,
    BoundEgressCall,
    CarriedProvenance,
    DataTier,
    DestinationProtocol,
    DiscloserProvenance,
    EgressBinding,
    EgressDestination,
    EgressSpan,
    EgressSpanLocator,
    FrozenJsonMapping,
    ProvisioningState,
    SpanCoverage,
    ToolDefinition,
)
from ai_assistant.testing.cancellation import LoopSuspension

if TYPE_CHECKING:
    from collections.abc import Callable, Collection

    from ai_assistant.core.types import FrozenJson

#: ADR-0152 §3's two keywords, spelled here rather than imported: this module may
#: not import ``ai_assistant.tools``, and a suite that held both implementations
#: to one *constant* would be checking that they read the same variable rather
#: than that they read the same schema.
DESTINATION_KEYWORD: Final = "x-egress-destination"
TIER_KEYWORD: Final = "x-egress-tier"
_KEYWORDS: Final = (DESTINATION_KEYWORD, TIER_KEYWORD)

#: ADR-0157 §1's third flat form holds exactly two branches, and they are the two
#: forms admitted before it. Spelled here for the same reason the keywords are.
_BRANCHES: Final = 2
_BRANCH_TYPES: Final = ("array", "string")

#: What ADR-0157 §1's second clause refuses beside ``anyOf`` and inside a branch:
#: a ``"type"``, which would leave which branch applies to the dialect, and every
#: applicator it names, which would put the shape somewhere a reader of the
#: subschema does not look.
_APPLICATORS: Final = ("oneOf", "allOf", "not", "if", "then", "else")
_REFUSED_BESIDE_ANYOF: Final = ("type", *_APPLICATORS)

_PARAMETERS: Final = TypeAdapter[Mapping[str, "FrozenJson"]](FrozenJsonMapping)


@dataclass(frozen=True, slots=True)
class _Registration:
    """One tool bound to one connection reference, with its endpoint."""

    reference: str
    transport_endpoint: str


@dataclass(frozen=True, slots=True)
class _Record:
    """A connection record as this fake holds it: an identity and a state."""

    identity: str
    state: ProvisioningState


@dataclass(frozen=True, slots=True)
class _Declared:
    """What one statically named argument declares."""

    protocol: DestinationProtocol | None
    tier: DataTier | None


def _refuse(message: str) -> EgressBindingError:
    """Build a refusal that renders no argument value (ADR-0152 §11)."""
    return EgressBindingError(message)


#: RFC 5322 §3.2.3 ``atext``, which RFC 5321 §4.1.2's ``Atom`` is built from, and
#: RFC 5321 §4.1.2's ``Ldh-str``, the interior of a domain label. Spelled here
#: rather than imported: ``ai_assistant.testing`` may not import ``tools``, which
#: is what makes this a second *implementation* rather than a second copy of one.
_ATEXT: Final = frozenset(string.ascii_letters + string.digits + "!#$%&'*+-/=?^_`{|}~")
_LDH: Final = frozenset(string.ascii_letters + string.digits + "-")

#: RFC 5321 §4.5.3.1.1, §4.5.3.1.2 and RFC 1035 §2.3.4's ceilings, in octets. Here
#: because a form longer than these has no canonical form at the seam either, and a
#: fake that accepted one would certify a seam that does not exist.
_MAX_LOCAL_PART_OCTETS: Final = 64
_MAX_DOMAIN_OCTETS: Final = 255
_MAX_LABEL_OCTETS: Final = 63


def _canonical_smtp(supplied: str) -> str:
    """This implementation's SMTP canonicaliser: lower the domain, keep the local part.

    RFC 5321 §2.4 makes mailbox domains case-insensitive and leaves the local
    part's semantics to the receiving host, so one transformation and no other.

    **Its accept/refuse boundary is the conformance suite's, not this module's.**
    ``EgressBinderContract`` states a corpus of forms every implementation must
    canonicalise identically and a corpus every implementation must refuse, and
    both subjects run it — so a divergence between this and the production
    canonicaliser fails a test rather than a review round. What is *not* done here
    is porting :mod:`ai_assistant.tools.destinations`' rules across: ADR-0148 §2's
    one-canonicaliser clause exists to keep that rule in **one** place, and a copy
    of it here — across an import boundary ``lint-imports`` forbids — would be the
    second copy the clause is against. The suite is where two independent
    implementations are told what to agree on.

    Raises:
        ValueError: If the supplied form is not one this implementation will
            assert a canonical form for. No message names the value (ADR-0004 §1).
    """
    if not supplied or not supplied.isascii():
        msg = "a destination that is empty or not ASCII has no canonical form here"
        raise ValueError(msg)
    if any(character.isspace() or not character.isprintable() for character in supplied):
        msg = "an email address carries no whitespace or control characters (RFC 5321 §4.1.2)"
        raise ValueError(msg)
    if supplied.count("@") != 1:
        msg = "an email address is one local part, one '@' and one domain (RFC 5321 §4.1.2)"
        raise ValueError(msg)
    local_part, domain = supplied.split("@")
    _check_local_part(local_part)
    _check_domain(domain)
    return f"{local_part}@{domain.lower()}"


def _check_local_part(local_part: str) -> None:
    """Require an RFC 5321 ``Dot-string``, refusing every other lawful spelling.

    Raises:
        ValueError: If it is empty, quoted, or not dot-separated atoms.
    """
    if not local_part:
        msg = "an email address has a non-empty local part (RFC 5321 §4.1.2)"
        raise ValueError(msg)
    if len(local_part.encode()) > _MAX_LOCAL_PART_OCTETS:
        msg = f"a local part is at most {_MAX_LOCAL_PART_OCTETS} octets (RFC 5321 §4.5.3.1.1)"
        raise ValueError(msg)
    if '"' in local_part or "\\" in local_part:
        msg = "a quoted local part's equivalence to any other form is not established"
        raise ValueError(msg)
    if local_part.startswith(".") or local_part.endswith(".") or ".." in local_part:
        msg = "a local part is dot-separated atoms (RFC 5321 §4.1.2)"
        raise ValueError(msg)
    if any(character not in _ATEXT for character in local_part.replace(".", "")):
        msg = "a local part outside RFC 5322 §3.2.3's atext is refused"
        raise ValueError(msg)


def _check_domain(domain: str) -> None:
    """Require an RFC 5321 ``Domain``: dot-separated let-dig-hyphen labels.

    Raises:
        ValueError: If it is empty, an address literal, or not conforming labels.
    """
    if not domain:
        msg = "an email address has a non-empty domain (RFC 5321 §4.1.2)"
        raise ValueError(msg)
    if len(domain.encode()) > _MAX_DOMAIN_OCTETS:
        msg = f"a domain is at most {_MAX_DOMAIN_OCTETS} octets (RFC 5321 §4.5.3.1.2)"
        raise ValueError(msg)
    if domain.startswith("["):
        msg = "an address literal's equivalence class belongs to the IP stack"
        raise ValueError(msg)
    for label in domain.split("."):
        if len(label) > _MAX_LABEL_OCTETS:
            msg = f"a domain label is at most {_MAX_LABEL_OCTETS} octets (RFC 1035 §2.3.4)"
            raise ValueError(msg)
        if not label or not (label[0].isalnum() and label[-1].isalnum()):
            msg = "a domain is non-empty labels beginning and ending alphanumeric"
            raise ValueError(msg)
        if any(character not in _LDH for character in label):
            msg = "a domain label holds only letters, digits and hyphens (RFC 5321 §4.1.2)"
            raise ValueError(msg)


#: ADR-0231 §8's host grammar: ASCII letters, digits, ``-`` and ``.``, and the two
#: ceilings it states. Spelled here for :data:`_ATEXT`'s reason — ``testing`` may
#: not import ``tools``, which is what makes this a second *implementation*.
_HOST_CHARACTERS: Final = frozenset(string.ascii_letters + string.digits + "-.")
_MAX_HOST_LENGTH: Final = 253
_MAX_HOST_LABEL: Final = 63

#: The port's domain, as §8 states it: one to five decimal digits without a
#: leading zero, denoting 1-65535.
_MAX_HTTPS_PORT: Final = 65535
_HTTPS_DEFAULT_PORT: Final = 443


def _is_number_label(label: str) -> bool:
    """Whether ``label`` is ADR-0231 §8's *number*, which makes a host an IP literal.

    §8 makes the IP-literal test decidable rather than a judgement: *"a host whose
    rightmost label is a **number** — one or more ASCII decimal digits, or
    ``0x``/``0X`` followed by one or more ASCII hexadecimal digits — is an IP
    literal and is refused"*. Written from that sentence, which is why a bare
    ``0x`` is **not** a number here: the clause says *followed by one or more*, and
    an implementation refusing it would be applying a rule the ratified test does
    not state (issue #2075).

    Args:
        label: The host's rightmost label.

    Returns:
        Whether it is a number in either notation.
    """
    if label[:2].lower() == "0x":
        digits = label[2:]
        return bool(digits) and all(character in string.hexdigits for character in digits)
    return label.isascii() and label.isdigit()


def _check_https_host(host: str) -> None:
    """Require ADR-0231 §8's host: labelled, ASCII, bounded, and not a number.

    Raises:
        ValueError: If the host is empty, carries a character outside the grammar,
            has a leading, trailing or doubled ``.``, has a label over 63
            characters or one beginning or ending with ``-``, exceeds 253
            characters, or is an IP literal in any notation.
    """
    if not host:
        msg = "an https destination names a non-empty host (ADR-0231 §8)"
        raise ValueError(msg)
    if len(host) > _MAX_HOST_LENGTH:
        msg = f"an https host is at most {_MAX_HOST_LENGTH} characters (ADR-0231 §8)"
        raise ValueError(msg)
    if any(character not in _HOST_CHARACTERS for character in host):
        msg = "an https host holds only ASCII letters, digits, '-' and '.' (ADR-0231 §8)"
        raise ValueError(msg)
    labels = host.split(".")
    for label in labels:
        if not label:
            msg = "an https host carries no leading, trailing or doubled '.' (ADR-0231 §8)"
            raise ValueError(msg)
        if len(label) > _MAX_HOST_LABEL:
            msg = f"an https host label is at most {_MAX_HOST_LABEL} characters (ADR-0231 §8)"
            raise ValueError(msg)
        if label.startswith("-") or label.endswith("-"):
            msg = "an https host label neither begins nor ends with '-' (ADR-0231 §8)"
            raise ValueError(msg)
    if _is_number_label(labels[-1]):
        msg = "an https host whose rightmost label is a number is an IP literal (ADR-0231 §8)"
        raise ValueError(msg)


def _https_port(written: str | None) -> int:
    """The port ``written`` states, or 443 where it states none.

    Args:
        written: The text after the port separator, or ``None`` where no separator
            was written. The two are **not** the same: §8 makes a separator with
            nothing after it a refusal rather than an omitted port.

    Returns:
        The port, in 1-65535.

    Raises:
        ValueError: If the text is not one to five decimal digits without a
            leading zero denoting a value in that range.
    """
    if written is None:
        return _HTTPS_DEFAULT_PORT
    if not (1 <= len(written) <= len(str(_MAX_HTTPS_PORT))):
        msg = "an https port is one to five decimal digits (ADR-0231 §8)"
        raise ValueError(msg)
    if not written.isascii() or not written.isdigit() or written.startswith("0"):
        # Checked before the conversion rather than after: ``int`` accepts a sign,
        # surrounding whitespace and ``_`` separators, so a port written in a
        # spelling no other reader agrees on would otherwise convert.
        msg = "an https port is decimal digits with no leading zero (ADR-0231 §8)"
        raise ValueError(msg)
    port = int(written)
    if not 1 <= port <= _MAX_HTTPS_PORT:
        msg = f"an https port denotes a value in 1-{_MAX_HTTPS_PORT} (ADR-0231 §8)"
        raise ValueError(msg)
    return port


def _canonical_https(supplied: str) -> str:
    """This implementation's HTTPS canonicaliser: ADR-0231 §8's origin, and nothing below it.

    §8 fixes the canonical form as ``https://<host>:<port>`` — *"always all three,
    with the port rendered explicitly even where the supplied form omitted it"* —
    carrying no path, query, fragment, userinfo or trailing separator. The
    equivalences it establishes are **exactly three**: the scheme differs only by
    ASCII case, the host differs only by ASCII case, and one form omits the port
    where the other states 443. Every other difference makes two destinations, so
    everything else is a refusal rather than a normalisation.

    **Its accept/refuse boundary is the conformance suite's, not this module's**,
    for :func:`_canonical_smtp`'s reason: ``EgressBinderContract`` states the
    corpora both implementations must agree on, and porting
    :mod:`ai_assistant.tools.destinations`' rules across the import boundary
    ``lint-imports`` forbids would be the second copy ADR-0148 §2's sixth clause
    exists to prevent.

    Raises:
        ValueError: If the supplied form is not one this implementation will
            assert a canonical form for. No message names the value (ADR-0004 §1).
    """
    if not supplied.isascii():
        msg = "a destination that is not ASCII has no canonical form here"
        raise ValueError(msg)
    scheme, separator, authority = supplied.partition("://")
    if not separator or scheme.lower() != "https":
        msg = "an https destination names the https scheme (ADR-0231 §8)"
        raise ValueError(msg)
    if any(character in authority for character in "/?#@"):
        msg = (
            "an https destination is an origin: it carries no path, query, "
            "fragment, userinfo or trailing separator (ADR-0231 §8)"
        )
        raise ValueError(msg)
    host, colon, written_port = authority.rpartition(":")
    if not colon:
        host = authority
    _check_https_host(host)
    return f"https://{host.lower()}:{_https_port(written_port if colon else None)}"


_CANONICALISERS: Final[Mapping[DestinationProtocol, Callable[[str], str]]] = {
    DestinationProtocol.SMTP: _canonical_smtp,
    DestinationProtocol.HTTPS: _canonical_https,
}


def _plain(value: FrozenJson) -> object:
    """Undo the frozen representation for the canonical JSON encoding."""
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, Sequence):
        return [_plain(item) for item in value]
    return value


def _extent(value: FrozenJson) -> int:
    """A span's extent in Unicode code points, as ADR-0150 §4 fixes it."""
    if isinstance(value, str):
        return len(value)
    return len(json.dumps(_plain(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False))


def _mappings(node: FrozenJson) -> list[Mapping[str, FrozenJson]]:
    """Every mapping reachable from ``node``, itself included."""
    if isinstance(node, str):
        return []
    if isinstance(node, Mapping):
        found = [node]
        for value in node.values():
            found.extend(_mappings(value))
        return found
    if isinstance(node, Sequence):
        return [found for value in node for found in _mappings(value)]
    return []


def _is_typed_flat(subschema: Mapping[str, FrozenJson]) -> bool:
    """Whether ``subschema`` is one of the two forms that declare a ``type``."""
    items = subschema.get("items")
    return subschema.get("type") == "string" or (
        subschema.get("type") == "array"
        and isinstance(items, Mapping)
        and "$ref" not in items
        and items.get("type") == "string"
    )


def _branch_type(branch: FrozenJson) -> str | None:
    """The flat form one ``anyOf`` branch declares, or ``None`` where it is none.

    A branch that is itself an applicator or a ``$ref`` declares none: ADR-0157
    §1's third form is admitted because each branch is self-contained and checkable
    by the check the two existing forms already get.
    """
    if not isinstance(branch, Mapping) or "$ref" in branch:
        return None
    if any(name in branch for name in ("anyOf", *_APPLICATORS)):
        return None
    declared = branch.get("type")
    return declared if _is_typed_flat(branch) and isinstance(declared, str) else None


def _is_flat_anyof(subschema: Mapping[str, FrozenJson]) -> bool:
    """Whether ``subschema`` is ADR-0157 §1's third form, and no other spelling.

    A sibling keyword is tolerated (§1's fifth clause) — keywords on one subschema
    are conjunctive, so it can only narrow — except the ones spelled in
    :data:`_REFUSED_BESIDE_ANYOF` and ``$ref``, which :func:`_is_flat` reads first.
    """
    branches = subschema["anyOf"]
    if any(name in subschema for name in _REFUSED_BESIDE_ANYOF):
        return False
    if not isinstance(branches, tuple | list) or len(branches) != _BRANCHES:
        return False
    return tuple(sorted(_branch_type(branch) or "" for branch in branches)) == _BRANCH_TYPES


def _is_flat(subschema: Mapping[str, FrozenJson]) -> bool:
    """Whether ``subschema`` is one of ADR-0157 §1's three flat forms."""
    if "$ref" in subschema:
        return False
    if "anyOf" in subschema:
        return _is_flat_anyof(subschema)
    return _is_typed_flat(subschema)


class FakeEgressBinder:
    """An in-memory ``EgressBinder`` that honours ADR-0152 whole.

    Arrange it with :meth:`register`, :meth:`register_egress` and
    :meth:`set_connection`; then call :meth:`bind` and :meth:`rebind` as the
    runner does.
    """

    __slots__ = (
        "_canonicalises",
        "_definitions",
        "_fail_next_read",
        "_reads",
        "_records",
        "_registrations",
        "_suspension",
    )

    def __init__(self, *, canonicalises: Collection[DestinationProtocol] | None = None) -> None:
        """Build an empty binder holding no tool, no registration and no record.

        Args:
            canonicalises: Which protocols this implementation canonicalises. It
                can only **narrow** the default set, never widen it or replace an
                entry, so ADR-0148 §2's one-canonicaliser-per-protocol clause holds
                — and narrowing is what makes ADR-0152 §3's "a protocol this seam
                holds no canonicaliser for" refusal reachable in a tree that
                canonicalises every protocol it defines.
        """
        self._definitions: dict[str, ToolDefinition] = {}
        self._registrations: dict[str, _Registration] = {}
        self._records: dict[str, _Record] = {}
        self._reads: list[str] = []
        self._fail_next_read = False
        self._suspension: LoopSuspension | None = None
        self._canonicalises: frozenset[DestinationProtocol] = frozenset(
            _CANONICALISERS if canonicalises is None else canonicalises
        )

    # --- arrangement ---------------------------------------------------------

    def register(self, tool: ToolDefinition) -> None:
        """Hold ``tool`` as the registry's untampered original for its id.

        A tool registered here and nowhere else is a **non-egress** tool: it is
        bound to no connected account, so :meth:`bind` answers ``None`` for it —
        unless its schema declares either keyword, which is mis-registration and
        is refused (ADR-0152 §8).
        """
        self._definitions[tool.id] = tool.model_copy(deep=True)

    def register_egress(
        self,
        tool: ToolDefinition,
        *,
        reference: str,
        identity: str,
        transport_endpoint: str = "test://endpoint",
        state: ProvisioningState = ProvisioningState.ACTIVE,
    ) -> None:
        """Register ``tool`` against a connected account, and record that account.

        Args:
            tool: The tool's untampered definition.
            reference: The connection record's reference.
            identity: The account identity the record holds.
            transport_endpoint: Where the call would be transmitted.
            state: How far the provisioning act got. ``PENDING`` makes the
                reference **not connectable**, which ADR-0152 §6 refuses.
        """
        self.register(tool)
        self._registrations[tool.id] = _Registration(
            reference=reference, transport_endpoint=transport_endpoint
        )
        self._records[reference] = _Record(identity=identity, state=state)

    def set_connection(
        self, reference: str, *, identity: str, state: ProvisioningState = ProvisioningState.ACTIVE
    ) -> None:
        """Rewrite the record ``reference`` names, as a provisioning act would."""
        self._records[reference] = _Record(identity=identity, state=state)

    def remove_connection(self, reference: str) -> None:
        """Drop the record, as a disconnection's removal entry does (ADR-0149 §5)."""
        self._records.pop(reference, None)

    def fail_next_read(self) -> None:
        """Make the next connection-record read raise ``ConnectionStoreError``."""
        self._fail_next_read = True

    def suspend_next_read(self) -> LoopSuspension:
        """Hold the next connection-record read open, so a suite can mutate inside it.

        ADR-0152 §13's detachment and pairing pins are stated over a mutation
        landed **while the member is suspended on the awaited read** — the one
        suspension point ADR-0152 §10 permits. A fake owns no store to park, so it
        models the window the way :mod:`ai_assistant.testing.cancellation` models
        every other one.

        Returns:
            The handle the suite waits on and releases.
        """
        self._suspension = LoopSuspension()
        return self._suspension

    def reads(self) -> tuple[str, ...]:
        """Every connection reference read so far, in order (ADR-0152 §10's budget)."""
        return tuple(self._reads)

    # --- the contract --------------------------------------------------------

    async def bind(
        self,
        tool: ToolDefinition,
        *,
        parameters: FrozenJsonMapping,
        provenance: CarriedProvenance,
    ) -> BoundEgressCall | None:
        """Derive this call's binding, or answer that it is not an egress call.

        See :meth:`~ai_assistant.core.protocols.EgressBinder.bind`.

        Returns:
            The derived binding beside the detached call, or ``None``.

        Raises:
            EgressBindingError: On every refusal ADR-0152 §6 states.
            ConnectionStoreError: If the record could not be read.
        """
        checked, arguments = self._revalidated(tool, parameters)
        carried = self._revalidated_provenance(provenance)
        registration = self._registered(checked)
        if registration is None:
            return None
        declared, named = self._declaration(checked)
        self._refuse_undescribed(checked, named, arguments)
        account = await self._account(checked, registration)
        binding = self._derive(
            checked,
            declared,
            arguments,
            account,
            registration,
            carried.spans,
            carried.planned_with_external_content,
            carried.coverage,
        )
        self._refuse_unlocated(binding, carried.spans)
        return self._pair(binding, checked, arguments)

    async def rebind(
        self,
        tool: ToolDefinition,
        *,
        parameters: FrozenJsonMapping,
        approved: EgressBinding | None,
    ) -> BoundEgressCall | None:
        """Re-derive this resuming call's binding and compare it with what was approved.

        See :meth:`~ai_assistant.core.protocols.EgressBinder.rebind`.

        Returns:
            The **derived** binding beside the detached call, or ``None``.

        Raises:
            EgressBindingError: On every refusal ``bind`` states, plus ADR-0152
                §7's three.
            ConnectionStoreError: If the record could not be read.
        """
        checked, arguments = self._revalidated(tool, parameters)
        was = None if approved is None else self._revalidated_binding(approved)
        registration = self._registered(checked, resuming=was is not None)
        if registration is None:
            return None
        if was is None:
            msg = (
                f"{checked.id}: this resumed call carries no approved binding while the "
                f"tool is registered against a connected account (ADR-0152 §7)"
            )
            raise _refuse(msg)
        declared, named = self._declaration(checked)
        self._refuse_undescribed(checked, named, arguments)
        account = await self._account(checked, registration)
        carried = {
            EgressSpanLocator(argument=span.argument, index=span.index): span.provenance
            for span in was.spans
        }
        # ADR-0181 §3's fifth clause: the second thing ``rebind`` takes from
        # ``approved``, transcribed rather than re-derived for the reason it takes
        # each span's provenance — this member holds no selection set, and a
        # re-derived False would compare unequal to every approved binding carrying
        # True and refuse the very call the user approved.
        binding = self._derive(
            checked,
            declared,
            arguments,
            account,
            registration,
            carried,
            was.planned_with_external_content,
            # ADR-0233 §4's sixth clause, one field over from the clause above and
            # for its reason: transcribed from ``approved``, never re-derived.
            was.coverage,
        )
        if binding != was:
            msg = (
                f"{checked.id}: the binding derived for this resumed call is not the one "
                f"that was approved (ADR-0150 §9, ADR-0152 §7)"
            )
            raise _refuse(msg)
        return self._pair(binding, checked, arguments)

    # --- the steps -----------------------------------------------------------

    def _revalidated(
        self, tool: ToolDefinition, parameters: FrozenJsonMapping
    ) -> tuple[ToolDefinition, Mapping[str, FrozenJson]]:
        """Rebuild and detach the two arguments both members take (ADR-0152 §1).

        A raw, non-model ``tool`` is handed to ``model_validate`` rather than
        dereferenced: ADR-0152 §1 revalidates "before reading any field of it", and
        ``model_dump()`` is a field read, so calling it first would let such a value
        escape as an ``AttributeError`` instead of the chained refusal §1 promises.
        """
        given: object = tool
        try:
            raw = given.model_dump() if isinstance(given, ToolDefinition) else given
            checked = ToolDefinition.model_validate(raw)
        except ValidationError as exc:
            msg = "the tool definition handed to this seam does not survive its own validation"
            raise _refuse(msg) from exc
        try:
            arguments = _PARAMETERS.validate_python(parameters)
        except ValidationError as exc:
            msg = "the parameters handed to this seam are not a frozen JSON mapping"
            raise _refuse(msg) from exc
        return checked, arguments

    def _revalidated_provenance(self, provenance: CarriedProvenance) -> CarriedProvenance:
        """Rebuild the carrier, catching ``model_construct`` and ``__setattr__`` bypasses."""
        try:
            return CarriedProvenance.model_validate(provenance)
        except ValidationError as exc:
            msg = "the carried provenance handed to this seam does not survive its own validation"
            raise _refuse(msg) from exc

    def _revalidated_binding(self, binding: EgressBinding) -> EgressBinding:
        """Rebuild the approved binding, with :meth:`_revalidated`'s ordering."""
        given: object = binding
        try:
            raw = given.model_dump() if isinstance(given, EgressBinding) else given
            return EgressBinding.model_validate(raw)
        except ValidationError as exc:
            msg = "the approved binding handed to this seam does not survive its own validation"
            raise _refuse(msg) from exc

    def _registered(self, tool: ToolDefinition, *, resuming: bool = False) -> _Registration | None:
        """Compare against the registry original, then decide ADR-0152 §8's partition."""
        original = self._definitions.get(tool.id)
        if original is not None and original != tool:
            msg = (
                f"{tool.id}: the definition handed to this seam is not the one held under "
                f"that id (ADR-0029 §1, ADR-0152 §1)"
            )
            raise _refuse(msg)
        registration = self._registrations.get(tool.id)
        if registration is not None:
            return registration
        if resuming:
            msg = (
                f"{tool.id}: a recorded decision states an egress call and this seam holds "
                f"no connected account for the tool (ADR-0152 §7)"
            )
            raise _refuse(msg)
        mentions = any(
            keyword in mapping
            for mapping in _mappings(tool.parameters_schema)
            for keyword in _KEYWORDS
        )
        if mentions:
            msg = (
                f"{tool.id}: the schema declares egress while the tool is registered "
                f"against no connected account, so it is mis-registered (ADR-0152 §8)"
            )
            raise _refuse(msg)
        return None

    def _declaration(self, tool: ToolDefinition) -> tuple[Mapping[str, _Declared], tuple[str, ...]]:
        """Read ADR-0152 §3's two keywords, refusing every breach of §3 and §4."""
        schema = tool.parameters_schema
        properties = schema.get("properties")
        top = properties if isinstance(properties, Mapping) else {}
        permitted = {id(value) for value in top.values() if isinstance(value, Mapping)}
        for mapping in _mappings(schema):
            if id(mapping) in permitted:
                continue
            for keyword in _KEYWORDS:
                if keyword in mapping:
                    msg = (
                        f"{tool.id}: {keyword} appears outside a top-level property's own "
                        f"subschema, so it is refused rather than ignored (ADR-0152 §3)"
                    )
                    raise _refuse(msg)
        declared: dict[str, _Declared] = {}
        for name, subschema in top.items():
            declared[name] = (
                self._declared_argument(tool.id, name, subschema)
                if isinstance(subschema, Mapping)
                else _Declared(protocol=None, tier=None)
            )
        return declared, tuple(top)

    def _declared_argument(
        self, tool_id: str, name: str, subschema: Mapping[str, FrozenJson]
    ) -> _Declared:
        """One argument's declaration, refused where it cannot describe a call."""
        protocol: DestinationProtocol | None = None
        tier: DataTier | None = None
        if DESTINATION_KEYWORD in subschema:
            value = subschema[DESTINATION_KEYWORD]
            members = {member.value: member for member in DestinationProtocol}
            protocol = members.get(value) if isinstance(value, str) else None
            if protocol is None:
                msg = f"{tool_id}: argument {name!r} names no destination protocol"
                raise _refuse(msg)
            if protocol not in self._canonicalises:
                msg = (
                    f"{tool_id}: argument {name!r} declares destinations in protocol "
                    f"{protocol.value!r}, which this seam holds no canonicaliser for"
                )
                raise _refuse(msg)
        if TIER_KEYWORD in subschema:
            stated = subschema[TIER_KEYWORD]
            tiers = {member.value: member for member in DataTier}
            tier = tiers.get(stated) if isinstance(stated, str) else None
            if tier is None:
                msg = f"{tool_id}: argument {name!r} names no data tier"
                raise _refuse(msg)
        if protocol is not None:
            if tier is None:
                msg = f"{tool_id}: argument {name!r} is destination-bearing and states no tier"
                raise _refuse(msg)
            self._refuse_unflat(tool_id, name, subschema)
        return _Declared(protocol=protocol, tier=tier)

    def _refuse_unflat(self, tool_id: str, name: str, subschema: Mapping[str, FrozenJson]) -> None:
        """Refuse a destination-bearing argument whose declared shape is not flat.

        ADR-0157 §1's three forms, written out here rather than borrowed from the
        seam: this module imports ``core`` and nothing else, and two
        implementations that shared the check would agree by construction instead
        of by conforming to one suite.
        """
        if not _is_flat(subschema):
            msg = (
                f"{tool_id}: argument {name!r} is marked destination-bearing and is none of "
                f"a string, an array whose items is a string, or an anyOf of exactly "
                f"those two (ADR-0152 §4, ADR-0157 §1)"
            )
            raise _refuse(msg)

    def _refuse_undescribed(
        self, tool: ToolDefinition, named: tuple[str, ...], parameters: Mapping[str, FrozenJson]
    ) -> None:
        """Refuse a top-level key the schema never statically named (ADR-0152 §6)."""
        undescribed = [key for key in parameters if key not in named]
        if not undescribed:
            return
        declared = ", ".join(repr(name) for name in named) or "no arguments at all"
        msg = (
            f"{tool.id}: this call carries {len(undescribed)} top-level argument(s) the "
            f"schema never statically named. It declares {declared}; the offending keys "
            f"are not rendered (ADR-0152 §11)"
        )
        raise _refuse(msg)

    async def _account(self, tool: ToolDefinition, registration: _Registration) -> BoundAccount:
        """The one read: the connection record, for its connectability and identity."""
        suspension, self._suspension = self._suspension, None
        if suspension is not None:
            await suspension.hold()
        if self._fail_next_read:
            self._fail_next_read = False
            msg = f"failed to read connection {registration.reference!r}"
            raise ConnectionStoreError(msg)
        self._reads.append(registration.reference)
        record = self._records.get(registration.reference)
        if record is None or record.state is not ProvisioningState.ACTIVE:
            state = "absent" if record is None else record.state.value
            msg = (
                f"{tool.id}: connection {registration.reference!r} is not connectable — its "
                f"record is {state} (ADR-0148 §6)"
            )
            raise _refuse(msg)
        try:
            return BoundAccount(identity=record.identity, reference=registration.reference)
        except ValidationError as exc:
            msg = (
                f"{tool.id}: the record for {registration.reference!r} yields no well-formed "
                f"bound account"
            )
            raise _refuse(msg) from exc

    def _derive(  # noqa: PLR0913 — one parameter per input the derivation reads; ADR-0148 §6 fixes the set
        self,
        tool: ToolDefinition,
        declared: Mapping[str, _Declared],
        parameters: Mapping[str, FrozenJson],
        account: BoundAccount,
        registration: _Registration,
        provenance: Mapping[EgressSpanLocator, DiscloserProvenance],
        planned_with_external_content: bool,
        coverage: SpanCoverage,
    ) -> EgressBinding:
        """Derive every field of the binding from the declaration and the arguments.

        Three members are **carried** rather than derived and each arrives resolved:
        each span's ``provenance`` (ADR-0146 §2), the call's
        ``planned_with_external_content`` (ADR-0181 §3, §4) and its ``coverage``
        (ADR-0233 §4, §5). Nothing here computes, infers or defaults any of them,
        and a ``PATH_WITHOUT_MODEL`` coverage is refused by the construction below
        rather than by a check of this fake's own (ADR-0233 §6).
        """
        spans: list[EgressSpan] = []
        for argument in sorted(parameters):
            value = parameters[argument]
            entry = declared.get(argument, _Declared(protocol=None, tier=None))
            if entry.protocol is not None:
                self._refuse_unshaped(tool, argument, value)
            elements: tuple[tuple[int | None, FrozenJson], ...] = (
                tuple((index, item) for index, item in enumerate(value))
                if isinstance(value, tuple)
                else ((None, value),)
            )
            for index, item in elements:
                spans.append(
                    EgressSpan(
                        argument=argument,
                        index=index,
                        provenance=provenance.get(
                            EgressSpanLocator(argument=argument, index=index),
                            DiscloserProvenance.SYSTEM_SELECTED,
                        ),
                        extent=_extent(item),
                        tier=entry.tier,
                        destination=(
                            None
                            if entry.protocol is None
                            else self._occurrence(tool, argument, index, entry.protocol, item)
                        ),
                    )
                )
        try:
            return EgressBinding(
                spans=tuple(spans),
                account=account,
                transport_endpoint=registration.transport_endpoint,
                planned_with_external_content=planned_with_external_content,
                coverage=coverage,
            )
        except ValidationError as exc:
            msg = (
                f"{tool.id}: this call does not form a well-formed binding — either its "
                f"spans do not describe one decomposition, or it carries covered content "
                f"some covered path of which contains no model call (ADR-0233 §6)"
            )
            raise _refuse(msg) from exc

    def _refuse_unshaped(self, tool: ToolDefinition, argument: str, value: FrozenJson) -> None:
        """Refuse a destination-bearing argument carrying a structured value (ADR-0152 §4)."""
        if isinstance(value, str):
            return
        if isinstance(value, tuple) and all(isinstance(item, str) for item in value):
            return
        msg = (
            f"{tool.id}: argument {argument!r} is destination-bearing and carries a value "
            f"that is neither a string nor an array of strings (ADR-0152 §4)"
        )
        raise _refuse(msg)

    def _occurrence(
        self,
        tool: ToolDefinition,
        argument: str,
        index: int | None,
        protocol: DestinationProtocol,
        value: FrozenJson,
    ) -> EgressDestination:
        """The occurrence for one destination-bearing span, computed here (ADR-0152 §5)."""
        where = f"argument {argument!r}" + ("" if index is None else f" entry {index}")
        if not isinstance(value, str):  # pragma: no cover — the per-call clause ran first
            msg = f"{tool.id}: {where} is not a supplied destination form"
            raise _refuse(msg)
        try:
            canonical = _CANONICALISERS[protocol](value)
        except ValueError as exc:
            msg = f"{tool.id}: {where} has no canonical form — {exc}"
            raise _refuse(msg) from exc
        try:
            return EgressDestination(protocol=protocol, supplied=value, canonical=canonical)
        except ValidationError as exc:
            msg = f"{tool.id}: {where} yields no well-formed occurrence"
            raise _refuse(msg) from exc

    def _refuse_unlocated(
        self, binding: EgressBinding, provenance: Mapping[EgressSpanLocator, DiscloserProvenance]
    ) -> None:
        """Refuse a provenance entry naming a span this call does not carry (ADR-0152 §5)."""
        derived = {
            EgressSpanLocator(argument=span.argument, index=span.index) for span in binding.spans
        }
        stranded = [locator for locator in provenance if locator not in derived]
        if stranded:
            msg = (
                f"the carried provenance names {len(stranded)} span(s) this call does not "
                f"carry; it is refused rather than dropped (ADR-0152 §5)"
            )
            raise _refuse(msg)

    def _pair(
        self, binding: EgressBinding, tool: ToolDefinition, parameters: Mapping[str, FrozenJson]
    ) -> BoundEgressCall:
        """Pair the derived binding with the detached call it was derived under."""
        try:
            return BoundEgressCall(binding=binding, tool=tool, parameters=parameters)
        except ValidationError as exc:
            msg = f"{tool.id}: the derived binding and the call it describes do not pair"
            raise _refuse(msg) from exc


__all__ = ["DESTINATION_KEYWORD", "TIER_KEYWORD", "FakeEgressBinder"]
