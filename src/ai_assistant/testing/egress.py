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


def _canonical_smtp(supplied: str) -> str:
    """This implementation's SMTP canonicaliser: lower the domain, keep the local part.

    RFC 5321 §2.4 makes mailbox domains case-insensitive and leaves the local
    part's semantics to the receiving host, so one transformation and no other.
    Deliberately narrower than the seam's own canonicaliser rather than a copy of
    it — what the conformance suite pins is that *some* canonical form is computed
    here and accepted from nobody, not that two implementations spell RFC 5321
    identically.

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
    if not local_part or not domain or domain.startswith(("[", ".")) or domain.endswith("."):
        msg = "an email address has a non-empty local part and a bare domain (RFC 5321 §4.1.2)"
        raise ValueError(msg)
    return f"{local_part}@{domain.lower()}"


_CANONICALISERS: Final[Mapping[DestinationProtocol, Callable[[str], str]]] = {
    DestinationProtocol.SMTP: _canonical_smtp,
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
                defines one protocol.
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
        binding = self._derive(checked, declared, arguments, account, registration, carried.spans)
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
        binding = self._derive(checked, declared, arguments, account, registration, carried)
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
        """Rebuild and detach the two arguments both members take (ADR-0152 §1)."""
        try:
            checked = ToolDefinition.model_validate(tool.model_dump())
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
        """Rebuild the approved binding, for the same three reasons."""
        try:
            return EgressBinding.model_validate(binding.model_dump())
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
        """Refuse a destination-bearing argument whose declared shape is not flat."""
        items = subschema.get("items")
        flat = "$ref" not in subschema and (
            subschema.get("type") == "string"
            or (
                subschema.get("type") == "array"
                and isinstance(items, Mapping)
                and "$ref" not in items
                and items.get("type") == "string"
            )
        )
        if not flat:
            msg = (
                f"{tool_id}: argument {name!r} is marked destination-bearing and is neither "
                f"a string nor an array whose items is a string (ADR-0152 §4)"
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
    ) -> EgressBinding:
        """Derive every field of the binding from the declaration and the arguments."""
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
            )
        except ValidationError as exc:
            msg = f"{tool.id}: the spans derived for this call do not form a well-formed binding"
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
