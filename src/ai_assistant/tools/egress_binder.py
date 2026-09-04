"""The binding seam: derive an egress call's binding whole, or refuse it.

:class:`EgressBindingSeam` is ADR-0152's surface (b) in code — the primary
production implementation of
:class:`~ai_assistant.core.protocols.EgressBinder`, riding with the contract as
one lane and one PR (ADR-0137 §2, ADR-0152 §13).

Five properties shape the module and are worth stating before the code:

- **Nothing is accepted that can be derived** (ADR-0152 §5). Neither member takes
  a destination, a canonical form, a span, an extent, a tier or a binding, and
  there is no argument through which one could be supplied. That is PR #1120's
  round-1 repair applied one boundary out: "a recipient set handed in beside the
  arguments is bound by nothing and re-derivable by nobody". The one thing that
  cannot be derived — a span's recorded origin — is **carried** (ADR-0146 §2),
  never invented, and is the one thing :meth:`EgressBindingSeam.rebind`
  transcribes.
- **Every argument is revalidated and detached first, and every later read is of
  the detached copy** (ADR-0152 §1, ADR-0029 §2). Both members are ``async`` and
  suspend exactly once, on the connection-record read, and that suspension is a
  window: without detachment a caller could hand in a registry-equal definition,
  let it compare, suspend the seam, then replace the declaration with
  ``object.__setattr__`` — which ``frozen=True`` does not stop (ADR-0018 §3) — and
  have the binding derived under a declaration no longer equal to the registered
  original.
- **The binding and the call it describes are returned together** (ADR-0152 §1).
  Detaching inside the seam would otherwise make the seam derive from its own
  copies while the caller built its ``ActionRequest`` from its own objects, so a
  mutation across the await produces exactly the mismatched pair the decision
  forbids. The seam's copies are created *before* the await and are unreachable
  from outside until they are returned, so a mutation bypass has no reference to
  work with.
- **Exactly one store read, and only where there is a registration to name one**
  (ADR-0152 §8, §10). The connection record the registration's reference names,
  read for its connectability and its account identity and for nothing else,
  **at the moment the call is bound** and never carried over from registration or
  from an earlier call (ADR-0148 §6). No network, no clock, no configuration, no
  resolution, no keyring, no second record, and no write of any kind anywhere.
- **It assumes nothing about what its caller checked** (ADR-0152 §4, §10). On the
  ordinary path it is reached after ADR-0145's schema check, but that is an
  ordering of the runner stage rather than a precondition: every shape a clause
  depends on is re-established here, because a request built by a bypass reaches
  the seam (ADR-0029 §2, ADR-0145 §3).

**No credential value and no credential slot crosses this seam.** This object
holds no ``Secrets`` and no ``SecretStore`` face, names no
:class:`~ai_assistant.core.types.SecretName`, and reads none from the connection
record it consults — it takes the connectability and the identity, and nothing
else (ADR-0125 §8, ADR-0149 §8, ADR-0152 §10).

**Nothing here transmits and nothing here authorises a byte.**
``ai_assistant.tools.egress`` stays approved and undesignated (ADR-0017 §2), no
tool is registered at it, and this module supplies a way to obtain a binding for
a call that still cannot be made.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Protocol

from pydantic import TypeAdapter, ValidationError

from ai_assistant.core.errors import EgressBindingError
from ai_assistant.core.types import (
    BoundAccount,
    BoundEgressCall,
    CarriedProvenance,
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
from ai_assistant.tools.destinations import (
    DestinationCanonicalisationError,
)
from ai_assistant.tools.destinations import (
    DestinationProtocol as SeamProtocol,
)
from ai_assistant.tools.destinations import (
    canonicalise as canonicalise_destination,
)
from ai_assistant.tools.egress_declaration import (
    EgressDeclaration,
    mentions_a_keyword,
    read_declaration,
)

if TYPE_CHECKING:
    from collections.abc import Collection, Iterable

    from ai_assistant.core.types import FrozenJson
    from ai_assistant.tools.connection_store import StoredEntry

#: The one canonicaliser per protocol this seam reaches, as a mapping from the
#: `core` enum a declaration names to the seam-internal enum
#: :func:`~ai_assistant.tools.destinations.canonicalise` dispatches on. **This is
#: not a second canonicaliser** (ADR-0148 §2's sixth clause): the rule relating a
#: supplied form to a canonical one lives in exactly one module, and this maps a
#: name onto it. The two enums carry the same member values by construction, and
#: :func:`ai_assistant.tools.egress_declaration.read_declaration` refuses a
#: protocol absent from the set below rather than passing it through.
_CANONICALISERS: Final[Mapping[DestinationProtocol, SeamProtocol]] = {
    DestinationProtocol.SMTP: SeamProtocol.SMTP,
}

_PARAMETERS: Final = TypeAdapter[Mapping[str, "FrozenJson"]](FrozenJsonMapping)


@dataclass(frozen=True, slots=True)
class EgressRegistration:
    """One tool bound to one connected account (ADR-0148 §6's one-account clause).

    **How a tool comes to be registered against a connected account is
    `tools/`-internal and is not contracted anywhere** (ADR-0152 §10). This value
    is that registration as this seam holds it, and it is why the seam reads
    exactly one connection record per egress call: one reference per registered
    tool, so no lookup, no search and no enumeration.

    Attributes:
        tool_id: The registered tool's id.
        reference: The connection record's reference (ADR-0149 §3). The
            registration's, not read per call — what is read per call is the
            record it names.
        transport_endpoint: Where the call is transmitted, as ADR-0148 §6 makes it
            the endpoint the tool "is configured to use". The registration's too:
            only the identity moves, which is why only the identity is re-read.
            What an endpoint must be, and what a redirect may do, is issue #83's
            and is constrained neither here nor by ADR-0150 §7.
    """

    tool_id: str
    reference: str
    transport_endpoint: str


class EgressRegistrations(Protocol):
    """Which tools are bound to which connected account (ADR-0148 §6, ADR-0152 §10).

    Structural and `tools/`-internal, like :class:`RegisteredDefinitions`: **how a
    tool comes to be registered against a connected account is not contracted
    anywhere**, and ADR-0152 §10 leaves it inside this subsystem in terms. A lookup
    rather than a snapshot taken at construction, so the table this seam reads and
    the table a provisioning act updates are one object rather than two that must
    agree.
    """

    def registration(self, tool_id: str, /) -> EgressRegistration | None:
        """The egress registration for ``tool_id``, or ``None`` where there is none."""
        ...


class RegistrationTable:
    """The in-memory :class:`EgressRegistrations` this subsystem wires by default.

    One entry per tool, and it refuses a second for one id at the moment it is
    added: two would make "the connected account this tool is bound to" ambiguous
    and defeat ADR-0148 §6's one-account clause at the seam that relies on it —
    the clause that is also why the seam reads exactly one connection record per
    egress call.
    """

    __slots__ = ("_bound",)

    def __init__(self, registrations: Iterable[EgressRegistration] = ()) -> None:
        """Build the table, refusing a duplicate id.

        Args:
            registrations: The registrations to hold.

        Raises:
            ValueError: If two of them name one tool id.
        """
        self._bound: dict[str, EgressRegistration] = {}
        for registration in registrations:
            self.register(registration)

    def register(self, registration: EgressRegistration, /) -> None:
        """Bind one tool to one connected account.

        Args:
            registration: The tool, its connection reference and its endpoint.

        Raises:
            ValueError: If the tool is already bound to an account.
        """
        if registration.tool_id in self._bound:
            msg = (
                f"tool {registration.tool_id!r} is registered against two connected "
                f"accounts; ADR-0148 §6 binds a registered tool to at most one"
            )
            raise ValueError(msg)
        self._bound[registration.tool_id] = registration

    def registration(self, tool_id: str, /) -> EgressRegistration | None:
        """The registration for ``tool_id``, or ``None``.

        Args:
            tool_id: The tool to look up.

        Returns:
            Its registration, or ``None`` where it is bound to no account.
        """
        return self._bound.get(tool_id)


class RegisteredDefinitions(Protocol):
    """A synchronous view of the definitions a registry holds (ADR-0152 §1).

    ADR-0152 §1 puts the registry-original comparison **before** the seam's one
    await, so it cannot be :meth:`~ai_assistant.core.protocols.ToolRegistry.get`,
    which is ``async``. Structural and `tools/`-internal: it is not a `core`
    Protocol, because both sides of it live in this subsystem and ADR-0149 §3's
    rule applies — a ``core`` seam between two modules of one subsystem is surface
    with no boundary to hold.
    """

    def original(self, tool_id: str, /) -> ToolDefinition | None:
        """The untampered definition registered under ``tool_id``, or ``None``."""
        ...


class ConnectionRecords(Protocol):
    """The read this seam performs, and the whole of what it needs (ADR-0152 §10).

    Satisfied by
    :class:`~ai_assistant.tools.connection_store.SqliteConnectionStore`. Named as
    a structural Protocol rather than taking the store concretely so that the
    read budget is visible in the type: one method, one reference, one record.
    """

    async def latest(self, reference: str, /) -> StoredEntry | None:
        """The reference's latest connection-store entry, or ``None``."""
        ...


def _refuse(message: str) -> EgressBindingError:
    """Build a refusal, which renders no argument value (ADR-0152 §11)."""
    return EgressBindingError(message)


def _plain(value: FrozenJson) -> object:
    """Undo the frozen representation, for the canonical JSON encoding below."""
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, Sequence):
        return [_plain(item) for item in value]
    return value


def _extent(value: FrozenJson) -> int:
    """A span's extent in Unicode code points, as ADR-0150 §4 fixes it.

    A JSON string is counted directly — Python's ``len`` over a ``str`` *is* a
    code-point count — and every other value in the canonical JSON encoding
    ADR-0021 §1 pins, which is the encoding ``parameters_digest`` is taken over.

    This is the same measure ``core`` recomputes when an
    :class:`~ai_assistant.core.types.ActionRequest` is constructed, so a seam that
    measured differently would build a binding that model refuses. That is what
    pins it: ``tests/tools/test_egress_binder.py`` asserts the request constructs
    over strings, arrays, objects, numbers, booleans and ``null``, so agreement is
    demonstrated against the real validator rather than by copying a constant.
    """
    if isinstance(value, str):
        return len(value)
    return len(json.dumps(_plain(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False))


def _revalidated_tool(tool: ToolDefinition) -> ToolDefinition:
    """Rebuild ``tool`` through validation, refusing what it will not survive.

    ADR-0029 §2's step 1 at a second seam: ``model_construct`` builds an instance
    without running validators and is public, and ``object.__setattr__`` defeats
    ``frozen=True`` (ADR-0018 §3) — neither is detectable from the annotation, so
    the annotation is not the enforcement.


    **A raw, non-model argument is validated rather than dereferenced**, and that
    ordering is §1's own: "revalidate every argument … **before reading any field
    of it**". ``model_dump()`` *is* a field read, so calling it first would let a
    value that is not a model at all escape as an ``AttributeError`` — never the
    chained refusal §1 promises. §13's bypass list enumerates model instances
    only; it illustrates §1's clause rather than closing it, so the guard is
    stated over what the argument **is** rather than over the shapes that list
    happens to name.

    Raises:
        EgressBindingError: Chained from the ``ValidationError``, and from that
            alone. An exception of any other type raised inside a validator is not
            converted here (ADR-0152 §1, §12).
    """
    given: object = tool
    try:
        # A genuine instance is dumped and rebuilt, which is what forces a
        # `model_construct`ed or `object.__setattr__`-corrupted one back through
        # every validator; anything else goes straight to `model_validate`, which
        # refuses it as a `ValidationError` rather than raising on a missing method.
        raw = given.model_dump() if isinstance(given, ToolDefinition) else given
        return ToolDefinition.model_validate(raw)
    except ValidationError as exc:
        msg = "the tool definition handed to this seam does not survive its own validation"
        raise _refuse(msg) from exc


def _revalidated_parameters(parameters: FrozenJsonMapping) -> Mapping[str, FrozenJson]:
    """Rebuild ``parameters`` through :data:`FrozenJsonMapping`'s own validation.

    ``FrozenJsonMapping`` is an ``Annotated`` alias and Python enforces no
    annotation at runtime, so a caller may hand over a raw ``dict``, a mapping
    carrying a value the alias would refuse, or a mutable one it keeps a reference
    to. Rebuilding answers all three at once: what comes back is frozen all the
    way down and detached from whatever the caller kept.

    A ``RecursionError`` from freezing a deep mapping is **not** converted
    (ADR-0152 §12): it is ADR-0145 §14's unbounded ``_deep_freeze`` at the shared
    frozen-JSON ingress, tracked as issue #1107, and a call that exhausts the
    stack here exhausts it at ``ActionRequest`` construction instead.

    Raises:
        EgressBindingError: Chained from the ``ValidationError``.
    """
    try:
        return _PARAMETERS.validate_python(parameters)
    except ValidationError as exc:
        msg = "the parameters handed to this seam are not a frozen JSON mapping"
        raise _refuse(msg) from exc


def _revalidated_provenance(provenance: CarriedProvenance) -> CarriedProvenance:
    """Rebuild the carrier, so its keys and values are what its type says.

    ``CarriedProvenance`` sets ``revalidate_instances="always"``, so validating an
    instance re-runs every field validator over it — which is what catches a
    carrier built by ``model_construct`` and one whose ``spans`` was replaced by
    ``object.__setattr__`` afterwards.

    Raises:
        EgressBindingError: Chained from the ``ValidationError``.
    """
    try:
        return CarriedProvenance.model_validate(provenance)
    except ValidationError as exc:
        msg = "the carried provenance handed to this seam does not survive its own validation"
        raise _refuse(msg) from exc


def _revalidated_binding(binding: EgressBinding) -> EgressBinding:
    """Rebuild an approved binding through validation, for the same three reasons.

    The validate-before-dump ordering is :func:`_revalidated_tool`'s and is there
    for the same clause: ``approved`` is the other argument this seam reads a
    method off, so a raw non-model would escape as an ``AttributeError`` rather
    than the chained refusal ADR-0152 §1 promises.

    Raises:
        EgressBindingError: Chained from the ``ValidationError``.
    """
    given: object = binding
    try:
        raw = given.model_dump() if isinstance(given, EgressBinding) else given
        return EgressBinding.model_validate(raw)
    except ValidationError as exc:
        msg = "the approved binding handed to this seam does not survive its own validation"
        raise _refuse(msg) from exc


class EgressBindingSeam:
    """Derives an egress binding before the ruling, or refuses the call.

    Structurally an :class:`~ai_assistant.core.protocols.EgressBinder`. Whether
    one object in `tools/` presents this face alongside ``ToolRegistry`` and
    ``ToolInvoker``, or a second object presents it, is `tools/`-internal and not
    contracted (ADR-0152 §10); this is the second object, because the three
    capabilities have three consumer sets and the composition root wires whichever
    it likes.
    """

    __slots__ = ("_canonicalises", "_definitions", "_records", "_registrations")

    def __init__(
        self,
        *,
        definitions: RegisteredDefinitions,
        registrations: EgressRegistrations,
        records: ConnectionRecords,
        canonicalises: Collection[DestinationProtocol] | None = None,
    ) -> None:
        """Wire the seam from the two things it reads and the tools it binds.

        Args:
            definitions: The registry's own untampered definitions, read
                synchronously because ADR-0152 §1's registry-original comparison
                runs before the seam's one await. The composition root injects the
                same object it injects as ``ToolRegistry``, so the original this
                compares against and the original ``invoke`` compares against are
                one table rather than two that must agree (ADR-0029 §1).
            registrations: Which tools are bound to which connected account,
                consulted per call rather than snapshotted here. A tool absent from
                it is not an egress tool (ADR-0152 §8), whatever its schema
                declares — except that a tool declaring either keyword while absent
                is **refused** rather than answered ``None``.
            records: Where the connection record is read. One read per egress
                call, for the connectability and the identity and nothing else.
            canonicalises: Which protocols this seam canonicalises. Defaults to
                every protocol :mod:`ai_assistant.tools.destinations` holds a
                canonicaliser for. It can only **narrow** that set and can never
                widen it or replace an entry, so ADR-0148 §2's sixth clause holds
                unchanged — nothing supplies a second canonicaliser for a protocol
                the seam already canonicalises. Narrowing is what makes ADR-0152
                §3's "a protocol this seam holds no canonicaliser for" refusal
                reachable in a tree that defines one protocol, which ADR-0152 §13
                obliges this lane to ship a case for.

        """
        self._definitions = definitions
        self._registrations = registrations
        self._records = records
        self._canonicalises: frozenset[DestinationProtocol] = frozenset(
            _CANONICALISERS if canonicalises is None else canonicalises
        )

    # --- the two members ------------------------------------------------------

    async def bind(
        self,
        tool: ToolDefinition,
        *,
        parameters: FrozenJsonMapping,
        provenance: CarriedProvenance,
    ) -> BoundEgressCall | None:
        """Derive the binding for a call reaching the permission stage first time.

        See :meth:`~ai_assistant.core.protocols.EgressBinder.bind`, which carries
        the contract; this docstring records only what is this implementation's.

        The order is ADR-0152 §1's and each step can only use what the one before
        it produced: revalidate and detach every argument, compare the definition
        against the registry's original, decide ADR-0152 §8's partition, read the
        declaration, refuse an undescribed key, then — after the one await —
        derive.

        Returns:
            The derived binding beside the detached call, or ``None`` where this
            is not an egress call.

        Raises:
            EgressBindingError: On every refusal ADR-0152 §6 states.
            ConnectionStoreError: If the connection record could not be read.
        """
        checked = _revalidated_tool(tool)
        arguments = _revalidated_parameters(parameters)
        carried = _revalidated_provenance(provenance)
        registration = self._registered(checked)
        if registration is None:
            return None
        declaration = self._declaration(checked)
        self._refuse_undescribed_keys(declaration, arguments)
        account = await self._connectable_account(registration)
        binding = self._derived(
            declaration,
            arguments,
            account,
            registration,
            carried.spans,
            carried.planned_with_external_content,
            carried.coverage,
        )
        self._refuse_unlocated_provenance(binding, carried.spans)
        return self._returned(binding, checked, arguments)

    async def rebind(
        self,
        tool: ToolDefinition,
        *,
        parameters: FrozenJsonMapping,
        approved: EgressBinding | None,
    ) -> BoundEgressCall | None:
        """Re-derive a resuming call's binding and check it against what was approved.

        See :meth:`~ai_assistant.core.protocols.EgressBinder.rebind`.

        Returns:
            The **derived** binding — never the one it was given — beside the
            detached call, or ``None`` on exactly ``bind``'s condition.

        Raises:
            EgressBindingError: On every refusal ``bind`` states, plus the three
                ADR-0152 §7 adds.
            ConnectionStoreError: If the connection record could not be read.
        """
        checked = _revalidated_tool(tool)
        arguments = _revalidated_parameters(parameters)
        was = None if approved is None else _revalidated_binding(approved)
        registration = self._registered(checked, resuming=was is not None)
        if registration is None:
            return None
        if was is None:
            msg = (
                f"{checked.id}: this call resumes a confirmation carrying no egress "
                f"binding, but the tool is registered against a connected account, so "
                f"the binding derived here can equal nothing that was approved"
            )
            raise _refuse(msg)
        declaration = self._declaration(checked)
        self._refuse_undescribed_keys(declaration, arguments)
        account = await self._connectable_account(registration)
        binding = self._derived(
            declaration,
            arguments,
            account,
            registration,
            self._approved_provenance(was),
            # ADR-0181 §3's fifth clause: **transcribed** from ``approved``, never
            # re-derived. This member receives no selection set, so a re-derivation
            # would answer False, compare unequal to every approved binding carrying
            # True, and refuse every resumed egress call planned over external
            # material — the call the user was asked about and approved. That is
            # ADR-0152 §7's own argument for transcribing the provenance, arriving
            # at the second field and narrowing its count to exactly two.
            was.planned_with_external_content,
            # ADR-0233 §4's sixth clause: **transcribed** from ``approved`` too, for
            # the identical reason one field over. The fact is about a composition
            # made before the confirmation was parked, plausibly before a restart,
            # and ``rebind`` receives nothing to recompute it from — so a member
            # that re-derived it would compare unequal to the approved binding and
            # refuse the very call the user was shown and approved. This is the
            # third of the three things ADR-0152 §7's count now admits.
            was.coverage,
        )
        if binding != was:
            msg = (
                f"{checked.id}: the binding derived for this resumed call is not the one "
                f"that was approved, so the answer released a call the user was not shown "
                f"(ADR-0150 §9)"
            )
            raise _refuse(msg)
        return self._returned(binding, checked, arguments)

    # --- the steps ------------------------------------------------------------

    def _registered(
        self, tool: ToolDefinition, *, resuming: bool = False
    ) -> EgressRegistration | None:
        """The tool's egress registration, or ``None`` where ADR-0152 §8 says so.

        Performs the registry-original comparison first: ADR-0029 §1's check one
        stage earlier and for its stated reason, the seam being the only place the
        caller's definition and an untampered original meet. Where the registry
        holds no definition for the id the comparison is not reached, exactly as
        ADR-0152 §1 states.

        Raises:
            EgressBindingError: If the definition is unequal to the registry's
                original; or if the tool has no egress registration and declares
                either keyword; or, on the resuming path, if it has no egress
                registration at all while a binding was approved for it.
        """
        original = self._definitions.original(tool.id)
        if original is not None and original != tool:
            msg = (
                f"{tool.id}: the definition handed to this seam is not the one the "
                f"registry holds under that id, so a binding derived from it would "
                f"describe a call nobody registered (ADR-0029 §1)"
            )
            raise _refuse(msg)
        registration = self._registrations.registration(tool.id)
        if registration is not None:
            return registration
        if resuming:
            msg = (
                f"{tool.id}: a recorded decision states an egress call and this seam holds "
                f"no connected account for the tool, so the two disagree about what was "
                f"authorised (ADR-0152 §7)"
            )
            raise _refuse(msg)
        if mentions_a_keyword(tool.parameters_schema):
            msg = (
                f"{tool.id}: the schema declares egress to this seam while the tool is "
                f"registered against no connected account, so it is mis-registered. "
                f"Answering that it is not an egress call would silently discard a "
                f"declaration its author wrote (ADR-0152 §8)"
            )
            raise _refuse(msg)
        return None

    def _declaration(self, tool: ToolDefinition) -> EgressDeclaration:
        """Read the tool's declaration out of its detached schema (ADR-0152 §3, §4)."""
        return read_declaration(
            tool.parameters_schema, tool_id=tool.id, canonicalises=self._canonicalises
        )

    def _refuse_undescribed_keys(
        self, declaration: EgressDeclaration, parameters: Mapping[str, FrozenJson]
    ) -> None:
        """Refuse a top-level key the schema does not **statically name** (ADR-0152 §6).

        The test is **authorship, not validity**: a locator is persisted into the
        recorded decision, so it must be text the tool's author wrote and not text
        a caller chose. A key admitted only by ``additionalProperties``,
        ``patternProperties``, ``propertyNames`` or any other open-ended form is
        not statically named however validly the call type-checks against it, and
        ADR-0145 §9 and §11 are relied on as true: schema validation passes such a
        call by design, and the key would travel in an authorised payload.

        **The message names the count and the declared names and nothing of the
        key itself** (ADR-0152 §11). A declaration is the author's text and may be
        named; a caller's key is a string a model can write as freely as a value,
        and this seam runs before the request exists.

        Raises:
            EgressBindingError: If any top-level key is not statically named.
        """
        undescribed = [key for key in parameters if declaration.declaration_for(key) is None]
        if not undescribed:
            return
        declared = ", ".join(repr(name) for name in declaration.named) or "no arguments at all"
        msg = (
            f"{declaration.tool_id}: this call carries {len(undescribed)} top-level "
            f"argument(s) the tool's schema never statically named. It declares "
            f"{declared}; the offending keys are not rendered, because a key a caller "
            f"chose is content (ADR-0152 §11)"
        )
        raise _refuse(msg)

    async def _connectable_account(self, registration: EgressRegistration) -> BoundAccount:
        """Read the one connection record, refusing a reference that is not connectable.

        The seam's whole read budget, and the one ``await`` either member performs
        (ADR-0152 §10). Two things are taken from the record and no third: the
        connectability, and the account **identity** that goes into the binding's
        :class:`~ai_assistant.core.types.BoundAccount`. No credential slot, no
        revision and no state enters the binding — ``revision`` and ``state`` move
        while a parked ruling stands, which is the failure ADR-0150 §7 states its
        separate type against.

        Connectability is read **at this moment** and never carried over from
        registration or from an earlier call, which is ADR-0148 §6's clause in its
        own words. A registration snapshot would let a ruling be taken — and a
        confirmation shown — against a reference that had since gone pending.

        **The message names the reference and never the identity**, which is
        ADR-0149 §3's split between a loggable handle and a Tier 1 value and
        ADR-0151 §2a's rule for the neighbouring surface.

        Raises:
            EgressBindingError: If the record is absent, is a removal, or is
                ``PENDING`` rather than ``ACTIVE``.
            ConnectionStoreError: If the store could not be read. Never converted
                (ADR-0152 §9): a store outage asserts nothing about the call.
        """
        stored = await self._records.latest(registration.reference)
        entry = None if stored is None else stored.entry
        if entry is None or entry.state is not ProvisioningState.ACTIVE or entry.identity is None:
            state = "absent" if entry is None or entry.state is None else entry.state.value
            msg = (
                f"{registration.tool_id}: connection {registration.reference!r} is not "
                f"connectable — its record is {state}. Nothing is built against it, no "
                f"ruling is sought for it, and re-running the provisioning act is the "
                f"remedy (ADR-0148 §6, ADR-0151 §4)"
            )
            raise _refuse(msg)
        try:
            return BoundAccount(identity=entry.identity, reference=entry.reference)
        except ValidationError as exc:
            msg = (
                f"{registration.tool_id}: the connection record for "
                f"{registration.reference!r} does not yield a well-formed bound account"
            )
            raise _refuse(msg) from exc

    def _derived(  # noqa: PLR0913 — one parameter per input the derivation reads; ADR-0148 §6 fixes the set
        self,
        declaration: EgressDeclaration,
        parameters: Mapping[str, FrozenJson],
        account: BoundAccount,
        registration: EgressRegistration,
        provenance: Mapping[EgressSpanLocator, DiscloserProvenance],
        planned_with_external_content: bool,
        coverage: SpanCoverage,
        /,
    ) -> EgressBinding:
        """Derive the whole binding from the declaration and the arguments.

        Runs **after** the awaited read, so it is the step the suspension window
        would otherwise reach — and every value it reads is a detached copy
        (ADR-0152 §1, §5).

        **Three of the binding's members are carried rather than derived**, and each
        arrives here already resolved by the member that called this: each span's
        ``provenance`` (ADR-0146 §2, ADR-0152 §7), the call's
        ``planned_with_external_content`` (ADR-0181 §3, §4) and its ``coverage``
        (ADR-0233 §4, §5). Nothing here computes, infers, defaults or amends any of
        them — in particular, no origin is recovered by reading an argument's value,
        its field or its shape, which is ADR-0146 §2's forbidden inference on the
        first axis, ADR-0181 §4's second clause on the second and ADR-0233 §5's
        second clause on the third.

        **A ``PATH_WITHOUT_MODEL`` coverage is refused by the construction below**,
        which is ADR-0233 §6's refusal reaching this seam without a check of its
        own: the model refuses unconditionally, so a call carrying that value is
        unconstructable rather than merely forbidden, and this member converts the
        refusal into the seam's own ``EgressBindingError`` exactly as it converts
        every other one ADR-0150 states.

        Raises:
            EgressBindingError: If a destination-bearing argument's value is not a
                JSON string or a JSON array of JSON strings; if a supplied form has
                no canonical form; if a span of a destination-bearing argument
                would carry no destination; if the call's coverage is
                ``PATH_WITHOUT_MODEL`` (ADR-0233 §6); or if the binding does not
                survive its own construction under ADR-0150 §3, §4 or §8.
        """
        spans: list[EgressSpan] = []
        for argument in sorted(parameters):
            spans.extend(
                self._spans_of(declaration, argument, parameters[argument], provenance=provenance)
            )
        try:
            binding = EgressBinding(
                spans=tuple(spans),
                account=account,
                transport_endpoint=registration.transport_endpoint,
                planned_with_external_content=planned_with_external_content,
                coverage=coverage,
            )
        except ValidationError as exc:
            msg = (
                f"{declaration.tool_id}: this call does not form a well-formed binding, so "
                f"no partial one is produced — either its spans do not describe one "
                f"decomposition (ADR-0150 §3, §4) or it carries covered content some "
                f"covered path of which contains no model call, which is forbidden "
                f"absolutely (ADR-0155 §3, ADR-0233 §6)"
            )
            raise _refuse(msg) from exc
        self._refuse_omitted_destination(declaration, binding)
        return binding

    def _refuse_omitted_destination(
        self, declaration: EgressDeclaration, binding: EgressBinding
    ) -> None:
        """Refuse a binding whose destination-bearing span carries no destination.

        ADR-0150 §11's second routed refusal, stated over the produced binding
        rather than over the derivation, and **stated even though the derivation
        above cannot produce one**. That is deliberate rather than defensive
        clutter: what it guards is ADR-0150 §3's account substitution, whose
        antecedent is a call whose *arguments* select no recipient. "The spans
        carry none" stands for that faithfully only where every destination-bearing
        argument has already yielded its occurrences, `core` cannot check which
        arguments those are, and a later change to the derivation that stopped
        yielding one would otherwise put an account-only canonical destination set
        in front of a policy for a call that named a recipient — silently, with
        every model here still valid.

        The reachable instance is on the resuming path: an ``approved`` binding
        read back out of the trail with a destination omitted compares unequal to
        the binding derived here and is refused by :meth:`rebind`'s equality clause
        (ADR-0152 §7), which is the same refusal by the other route.

        Raises:
            EgressBindingError: If a span of a destination-bearing argument carries
                no occurrence.
        """
        omitted = [
            span
            for span in binding.spans
            if span.destination is None
            and (declared := declaration.declaration_for(span.argument)) is not None
            and declared.protocol is not None
        ]
        if omitted:  # pragma: no cover — unreachable by construction; see the docstring
            msg = (
                f"{declaration.tool_id}: {len(omitted)} span(s) of a destination-bearing "
                f"argument carry no destination. No lane reads such a span as the call "
                f"having selected no recipient (ADR-0150 §3, ADR-0152 §6)"
            )
            raise _refuse(msg)

    def _spans_of(
        self,
        declaration: EgressDeclaration,
        argument: str,
        value: FrozenJson,
        *,
        provenance: Mapping[EgressSpanLocator, DiscloserProvenance],
    ) -> list[EgressSpan]:
        """One argument's spans, by ADR-0150 §4's decomposition and no other.

        Where the value is a JSON array its elements are its spans; where it is any
        other JSON value it is one span, whatever that value is. Nothing in the
        declaration vocabulary says whether an argument decomposes, and no keyword
        for it exists: the decomposition is the value's, so a ``multiple`` flag
        would be a second statement of one fact (ADR-0152 §3).

        Raises:
            EgressBindingError: On ADR-0152 §4's per-call clause, and on a supplied
                form with no canonical form.
        """
        declared = declaration.declaration_for(argument)
        protocol = None if declared is None else declared.protocol
        tier = None if declared is None else declared.tier
        if protocol is not None:
            self._refuse_unshaped_destination(declaration, argument, value)
        elements: tuple[tuple[int | None, FrozenJson], ...]
        if isinstance(value, tuple):
            elements = tuple((index, item) for index, item in enumerate(value))
        else:
            elements = ((None, value),)
        return [
            EgressSpan(
                argument=argument,
                index=index,
                provenance=provenance.get(
                    EgressSpanLocator(argument=argument, index=index),
                    DiscloserProvenance.SYSTEM_SELECTED,
                ),
                extent=_extent(item),
                tier=tier,
                destination=(
                    None
                    if protocol is None
                    else self._occurrence(declaration, argument, index, protocol, item)
                ),
            )
            for index, item in elements
        ]

    def _refuse_unshaped_destination(
        self, declaration: EgressDeclaration, argument: str, value: FrozenJson
    ) -> None:
        """Refuse a declared destination-bearing argument carrying a structured value.

        ADR-0152 §4's per-call clause, and it is **not** redundant beside the
        declaration clause: this seam does not assume its caller validated
        anything. It is a Protocol, its conformance suite calls it directly, and
        ADR-0029 §2 already puts a revalidation at a second seam because "a request
        built by a bypass reaches the seam".

        This is where ADR-0150 §12's multi-recipient structured-span case is
        refused — for carrying a value of the wrong shape rather than for carrying
        two recipients in one span, which is how §12 states it: over the outcome,
        not over which clause produced it.

        Raises:
            EgressBindingError: If the value is not a JSON string and not a JSON
                array of JSON strings.
        """
        if isinstance(value, str):
            return
        if isinstance(value, tuple) and all(isinstance(item, str) for item in value):
            return
        msg = (
            f"{declaration.tool_id}: argument {argument!r} is destination-bearing and "
            f"carries a value that is neither a string nor an array of strings, so a "
            f"recipient could sit inside a span unable to carry it (ADR-0152 §4)"
        )
        raise _refuse(msg)

    def _occurrence(
        self,
        declaration: EgressDeclaration,
        argument: str,
        index: int | None,
        protocol: DestinationProtocol,
        value: FrozenJson,
    ) -> EgressDestination:
        """The occurrence for one destination-bearing span, computed here.

        **Every occurrence carries the form this seam's own canonicaliser computed
        from its supplied form** (ADR-0152 §5). That discharges ADR-0150 §11's
        correspondence check by construction rather than by comparison: an
        occurrence the seam computed cannot disagree with the computation that
        produced it, and a caller has no route by which to present one that does.
        The comparison lives on the resuming path, where an occurrence really does
        arrive from outside (:meth:`rebind`).

        **The message names the argument and the position, never the value**: an
        address is Tier 1 (ADR-0004 §1) and a refusal message reaches a log
        (ADR-0152 §11). The argument name is the tool author's text and is
        statically named by the time this runs.

        Raises:
            EgressBindingError: If this seam's canonicaliser asserts no canonical
                form for the supplied one. The supplied form is never passed
                through as its own canonical form (ADR-0148 §1).
        """
        seam_protocol = _CANONICALISERS[protocol]
        where = f"argument {argument!r}" + ("" if index is None else f" entry {index}")
        if not isinstance(value, str):  # pragma: no cover — the per-call clause ran first
            # `_refuse_unshaped_destination` has already established that a
            # destination-bearing argument holds a string or an array of strings, so
            # this element is one. Stated rather than asserted because the property
            # is a guarantee of the caller above and a type checker cannot see it,
            # and because a guard whose own failure mode is an `AttributeError` from
            # inside a canonicaliser is enforcing nothing (ADR-0026 §2's rule).
            msg = f"{declaration.tool_id}: {where} is not a supplied destination form"
            raise _refuse(msg)
        try:
            destination = canonicalise_destination(seam_protocol, value)
        except DestinationCanonicalisationError as exc:
            msg = f"{declaration.tool_id}: {where} has no canonical form — {exc}"
            raise _refuse(msg) from exc
        try:
            return EgressDestination(
                protocol=protocol, supplied=destination.supplied, canonical=destination.canonical
            )
        except ValidationError as exc:
            msg = f"{declaration.tool_id}: {where} does not yield a well-formed occurrence"
            raise _refuse(msg) from exc

    def _refuse_unlocated_provenance(
        self, binding: EgressBinding, provenance: Mapping[EgressSpanLocator, DiscloserProvenance]
    ) -> None:
        """Refuse a carried provenance entry naming a span this call does not carry.

        ADR-0152 §5: refused rather than dropped. A caller and this derivation
        disagreeing about what the payload is, is exactly what a silent drop would
        hide.

        **The message names a count and nothing else.** An
        :class:`~ai_assistant.core.types.EgressSpanLocator`'s ``argument`` reaching
        this seam from a caller is caller-supplied text, so it is reported without
        interpolation (ADR-0152 §11).

        Raises:
            EgressBindingError: If any locator names no derived span.
        """
        derived = {
            EgressSpanLocator(argument=span.argument, index=span.index) for span in binding.spans
        }
        stranded = [locator for locator in provenance if locator not in derived]
        if stranded:
            msg = (
                f"the carried provenance names {len(stranded)} span(s) this call does not "
                f"carry, so the caller and this derivation disagree about what the payload "
                f"is; it is refused rather than dropped (ADR-0152 §5)"
            )
            raise _refuse(msg)

    def _approved_provenance(
        self, approved: EgressBinding
    ) -> Mapping[EgressSpanLocator, DiscloserProvenance]:
        """The approved binding's provenance, keyed by locator (ADR-0152 §7).

        The **first of the three** things ``rebind`` takes from ``approved``, the
        other two being ``planned_with_external_content`` (ADR-0181 §3's fifth
        clause) and ``coverage`` (ADR-0233 §4's sixth clause) — which between them
        narrow ADR-0152 §7's count from exactly one to exactly three and narrow
        nothing else in it: everything else is still re-derived and the equality
        refusal is unchanged. Transcribing it is forced: a recorded origin is a fact
        about an act that happened before the confirmation was parked, plausibly
        before a restart, and a member that re-derived it would describe every span
        as ``SYSTEM_SELECTED`` and refuse every resumed call whose user typed
        anything. The other two are transcribed for the same reason one field over,
        and neither has an accessor of its own because each is a single scalar read
        straight off the approved binding rather than a mapping to rebuild.
        """
        return {
            EgressSpanLocator(argument=span.argument, index=span.index): span.provenance
            for span in approved.spans
        }

    def _returned(
        self, binding: EgressBinding, tool: ToolDefinition, parameters: Mapping[str, FrozenJson]
    ) -> BoundEgressCall:
        """Pair the derived binding with the detached call it was derived under.

        The copies are the seam's own, made before the await and unreachable from
        outside until this returns — which is what makes the caller's obligation
        one clause on one construction site rather than a rule about an object's
        whole lifetime (ADR-0152 §1).

        Raises:
            EgressBindingError: If the pair does not survive its own validation,
                which is the residual limb of ADR-0152 §6's uncompletable call.
        """
        try:
            return BoundEgressCall(binding=binding, tool=tool, parameters=parameters)
        except ValidationError as exc:
            msg = f"{tool.id}: the derived binding and the call it describes do not pair"
            raise _refuse(msg) from exc


__all__ = [
    "ConnectionRecords",
    "EgressBindingSeam",
    "EgressRegistration",
    "EgressRegistrations",
    "RegisteredDefinitions",
    "RegistrationTable",
]
