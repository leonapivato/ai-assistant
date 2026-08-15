"""The registry's contents, and the default-registry factory (ADR-0048 §3).

Two local read-only tools, the one *configured* egress integration, and the
factory that binds them into the canonical one-object registry+invoker
(:class:`~ai_assistant.tools.registry.InMemoryToolRegistry`). Registration is
internal to this subsystem (ADR-0016 §5, ADR-0029 §1, ADR-0152 §10); the
composition root calls :func:`build_default_registry` and injects the single
returned object as both the selecting ``ToolRegistry`` and the acting
``ToolInvoker`` (ADR-0029 §8).

**This is the one production module that names a transport**, and that is a
property rather than a coincidence. ADR-0017 §3's condition 5 and issue #83's
third bullet both turn on there being exactly one place a client is constructed —
"if each integration builds its own client, this is unenforceable by
construction" — and :func:`build_send_email_integration` is it. Nothing else
under ``src/ai_assistant`` names
:class:`~ai_assistant.tools.egress.SmtpEgressTransport`, the tool that sends
through it holds a one-method Protocol instead
(:class:`~ai_assistant.tools.send_email.BoundTransport`), and
``tests/tools/test_egress_seam.py`` holds the tree to both.

**The two local tools transmit nothing.** Both are read-only —
non-``side_effecting``, non-disclosing, ``NATURAL`` idempotency, ``FREE`` cost —
which keeps them clear of the idempotency-window machinery ADR-0029 §5 reserves
for ``KEYED`` writes and of the spend policy a paid tool would need.

**The egress tool is present only where a deployment configured one, and both
halves of that come from one value.** ADR-0148 §6 binds a registered tool to at
most one connected account, so ``send_email`` is registerable only *against* an
account: an unconfigured deployment gets no ``send_email`` in the registry **and**
no entry in the binding seam's registration table. Deriving both from one
:class:`EgressIntegration` is what makes the half-state — a tool selection can
reach and the seam then refuses under ADR-0152 §8, on every call, forever —
unreachable rather than merely unlikely.

Each tool's declared ``parameters_schema`` is **carried, not enforced** at
selection (ADR-0016 §7 defers that), so each callable validates its own inputs
and raises on a bad argument — which the seam classifies ``INTERNAL`` (ADR-0029
§3). No message raised here interpolates a parameter value, so nothing untrusted
reaches the Tier 2 failure text or a log.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from ai_assistant.core.clock import checked_clock
from ai_assistant.core.types import (
    CostBasis,
    DataTier,
    Idempotency,
    Reversibility,
    RiskLevel,
    ToolCost,
    ToolDefinition,
)
from ai_assistant.tools.egress import SmtpEgressTransport, parse_smtp_endpoint
from ai_assistant.tools.egress_binder import EgressRegistration, RegistrationTable
from ai_assistant.tools.registry import InMemoryToolRegistry
from ai_assistant.tools.send_email import SEND_EMAIL, SendEmail

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Collection, Mapping

    from ai_assistant.core.clock import Clock
    from ai_assistant.core.protocols import MemoryStore, Secrets
    from ai_assistant.core.types import FrozenJson
    from ai_assistant.tools.egress import ByteChannel, SmtpEndpoint
    from ai_assistant.tools.egress_binder import ConnectionRecords
    from ai_assistant.tools.invocation import BoundImplementation, EgressToolImplementation

#: Default number of memory records ``recall_memory`` returns when the call names
#: no ``limit``. Small, because a recall folds into a turn a person reads.
_DEFAULT_RECALL_LIMIT = 5

#: Upper bound on ``recall_memory``'s ``limit``. Low double digits — a few times
#: the default of 5 — because a recall exists to fold into a turn a person reads,
#: not to page a corpus; a plan naming a larger ``limit`` is refused rather than
#: forwarded. The cap also keeps the argument well inside SQLite's integer range
#: (#298), so a huge ``limit`` cannot reach a backend as an out-of-range bind —
#: which no longer needs headroom for an over-fetch multiplier, since ADR-0128 §1
#: removed it, but is still the cheaper of the two guards to keep.
_MAX_RECALL_LIMIT = 25


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _reject_unknown(
    parameters: Mapping[str, FrozenJson], allowed: Collection[str], tool_id: str
) -> None:
    """Refuse a parameter key the tool's schema does not declare.

    Each tool advertises ``additionalProperties: false``, and ``parameters_schema``
    is carried but not enforced at selection (ADR-0016 §7), so the callable makes
    its own behaviour match its own declaration: an unexpected argument is a bad
    argument, refused loudly (the seam classifies it ``INTERNAL``, ADR-0029 §3)
    rather than silently ignored, which would surface a planner↔tool mismatch
    (#296) instead of hiding it.

    **The message names the offending *keys*, never their values** — a value is
    untrusted input that could carry Tier 1 data, and only the key set (which the
    author declared) is safe to render.

    Raises:
        ValueError: If any key is outside ``allowed``.
    """
    unexpected = sorted(set(parameters) - set(allowed))
    if unexpected:
        msg = f"{tool_id} was given unexpected argument(s): {', '.join(unexpected)}"
        raise ValueError(msg)


# --- current_time: a pure-compute tool, zero injected subsystems --------

CURRENT_TIME = ToolDefinition(
    id="current_time",
    capability="report_current_time",
    description="Report the current date and time in UTC.",
    risk_level=RiskLevel.LOW,
    reversibility=Reversibility.REVERSIBLE,
    side_effecting=False,
    reads=(),
    writes=(),
    discloses=(),
    cost=ToolCost(basis=CostBasis.FREE),
    idempotency=Idempotency.NATURAL,
    parameters_schema={"type": "object", "properties": {}, "additionalProperties": False},
)
"""Declaration for :class:`CurrentTime` (ADR-0048 §2).

``LOW`` risk and read-only: reading a clock touches no stored data and reveals
nothing sensitive, so every floor in ADR-0021 §5 is clear of it and the default
policy allows it outright — the tool that closes the pipeline end-to-end with no
confirmation.
"""


class CurrentTime:
    """Report the current UTC instant (ADR-0048 §1).

    Structurally a :class:`~ai_assistant.tools.invocation.ToolImplementation`.
    The clock is injectable so a test is deterministic; it defaults to
    ``datetime.now(UTC)``, so the tool needs no wiring of its own.
    """

    def __init__(self, *, now: Clock = _utcnow) -> None:
        """Bind the clock this tool reads, guarded like every injected-clock seam.

        Wrapped in :func:`~ai_assistant.core.clock.checked_clock` (ADR-0026 §2),
        so a reading is converted to canonical UTC and a non-conforming one — a
        naive datetime, a non-``datetime`` — raises ``ClockReadingError`` rather
        than letting a tool advertised as returning UTC emit a naive or
        wrong-zone timestamp. The guard is per-reading, so it holds for a clock
        that drifts, not only at construction.
        """
        self._now = checked_clock(now, owner="CurrentTime")

    async def __call__(
        self,
        parameters: Mapping[str, FrozenJson],
        *,
        idempotency_key: str | None,  # noqa: ARG002 — NATURAL, so the key is always None
    ) -> FrozenJson:
        """Return the current UTC time as an ISO-8601 string under ``utc``.

        Raises:
            ValueError: If any argument is given — the tool takes none, and its
                schema declares ``additionalProperties: false`` (ADR-0048 §2).
            ClockReadingError: If the injected clock's reading is not a conforming
                UTC instant; the seam classifies it ``INTERNAL`` (ADR-0029 §3).
        """
        _reject_unknown(parameters, (), CURRENT_TIME.id)
        return {"utc": self._now().isoformat()}


# --- recall_memory: a read backed by an injected MemoryStore ------------

RECALL_MEMORY = ToolDefinition(
    id="recall_memory",
    capability="recall_memory",
    description="Search the user's long-term memory for records relevant to a query.",
    risk_level=RiskLevel.MEDIUM,
    reversibility=Reversibility.REVERSIBLE,
    side_effecting=False,
    reads=(DataTier.PERSONAL,),
    writes=(),
    discloses=(),
    cost=ToolCost(basis=CostBasis.FREE),
    idempotency=Idempotency.NATURAL,
    parameters_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "limit": {"type": "integer", "minimum": 1, "maximum": _MAX_RECALL_LIMIT},
        },
        "required": ["query"],
        "additionalProperties": False,
    },
)
"""Declaration for :class:`RecallMemory` (ADR-0048 §2).

``MEDIUM`` risk because it reads Tier 1 data, and read-only because it changes
nothing and transmits nothing off-device (``discloses`` is empty — records return
*into* the local pipeline). ADR-0016 §3 keeps risk unconstrained by
``side_effecting`` precisely so an honest read can say it is sensitive.
"""


class RecallMemory:
    """Search long-term memory through an injected :class:`MemoryStore` (ADR-0048 §1).

    Structurally a :class:`~ai_assistant.tools.invocation.ToolImplementation`.
    It depends on `memory` only through the ``MemoryStore`` Protocol, wired at the
    composition root — never by importing the concrete store (golden rule 1).
    """

    def __init__(self, memory: MemoryStore) -> None:
        """Bind the store this tool reads from."""
        self._memory = memory

    async def __call__(
        self,
        parameters: Mapping[str, FrozenJson],
        *,
        idempotency_key: str | None,  # noqa: ARG002 — NATURAL, so the key is always None
    ) -> FrozenJson:
        """Return records matching ``query`` (most relevant first) as JSON.

        Validates its own arguments, because ``parameters_schema`` enforcement is
        deferred (ADR-0016 §7). A bad argument raises ``ValueError``, which the
        seam turns into an ``INTERNAL`` result; the messages name no parameter
        value, so nothing untrusted reaches the failure text (ADR-0029 §3).

        Raises:
            ValueError: If an unexpected argument is given, ``query`` is absent
                or not a string, or ``limit`` is present and not an integer in
                ``[1, _MAX_RECALL_LIMIT]``.
        """
        _reject_unknown(parameters, ("query", "limit"), RECALL_MEMORY.id)
        query = parameters.get("query")
        if not isinstance(query, str):
            msg = "recall_memory requires a string 'query' argument"
            raise ValueError(msg)
        limit = parameters.get("limit", _DEFAULT_RECALL_LIMIT)
        # A bool is an int subclass and is not a count; reject it like the rest.
        # The upper bound enforces the schema this tool advertises (ADR-0016 §7):
        # an over-cap limit is refused here, never forwarded to the store (#298).
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or limit < 1
            or limit > _MAX_RECALL_LIMIT
        ):
            msg = f"recall_memory 'limit' must be an integer in [1, {_MAX_RECALL_LIMIT}]"
            raise ValueError(msg)
        # ``capped`` is unwrapped and not acted on (ADR-0128 §6): this lookup wants
        # what there is, and a served prefix is a usable answer to "recall what you
        # know about X". Whether it should degrade on the signal is its own lane.
        found = await self._memory.search(query, limit=limit)
        return [record.model_dump(mode="json") for record in found.records]


# --- the configured egress integration ----------------------------------


@dataclass(frozen=True, slots=True)
class EgressIntegration:
    """One configured egress tool: its declaration, its callable, its registration.

    The three travel together because they are one decision. ADR-0148 §6 binds a
    registered tool to at most one connected account; a declaration in the registry
    with no matching :class:`~ai_assistant.tools.egress_binder.EgressRegistration`
    is a tool the binding seam refuses on every call (ADR-0152 §8), and a
    registration with no declaration in the registry names a tool nothing can
    invoke. Neither half is useful alone and either alone is a bug, so this type
    makes them un-separable by the composition root that wires them.

    **How a tool comes to be registered against a connected account is
    `tools/`-internal and contracted nowhere** (ADR-0152 §10). This value is that
    registration act's whole result, and the two functions below are the whole of
    the act.

    Attributes:
        definition: The tool's declaration, as the registry will hold it.
        implementation: The callable bound to it — an
            :class:`~ai_assistant.tools.invocation.EgressToolImplementation`,
            because a transport may re-derive nothing the ruling fixed (ADR-0148
            §4) and so has to be handed the binding.
        registration: The connected account and the endpoint, as the binding seam
            and the transport both read them. The **same object** the transport
            holds, so the reference the transport compares a binding against and
            the reference the seam reads a record by cannot come apart.
    """

    definition: ToolDefinition
    implementation: EgressToolImplementation
    registration: EgressRegistration


def build_send_email_integration(
    *,
    connection: str,
    endpoint: str,
    records: ConnectionRecords,
    secrets: Secrets,
    connect: Callable[[SmtpEndpoint], Awaitable[ByteChannel]] | None = None,
) -> EgressIntegration:
    """Register ``send_email`` against one connected account (ADR-0148 §6, ADR-0152 §10).

    **The one place in production a transport is constructed.** Issue #83's third
    bullet asks whether "the client is constructed centrally at the seam so the
    policy cannot be bypassed per integration", and this function is the answer for
    the whole tree: the transport is built here, handed to the tool as a
    :class:`~ai_assistant.tools.send_email.BoundTransport`, and reachable from
    nowhere else.

    **The endpoint is parsed here and then never used parsed.** Parsing is a
    fail-fast on the operator's configuration — a deployment naming a scheme this
    seam does not pin should not start and then fail at a send. What the transport
    compares per call is the binding's endpoint against this registration's *as
    text, before parsing* (ADR-0154's condition 5), so two spellings of one host
    stay two endpoints; the parse here changes nothing about that comparison and
    only decides whether the text is one this seam will ever open.

    **The fail-fast is exactly as strong as that grammar, which is weaker than it
    reads.** ``parse_smtp_endpoint`` checks the scheme, refuses a path, query,
    fragment or userinfo, and reads a port — but it does not validate the authority
    at all, so a doubled port or a non-hostname survives it (**#1158**, the second
    of the three defects ADR-0154 §6 records for that function; **#1147** is the
    first). Such an endpoint therefore *does* start a deployment and fails at the
    connection attempt, after a credential read. Neither is a route to an
    unintended host — the endpoint is what the operator configured and the
    transport pins the text against itself — and both are named here rather than
    left for a reader to infer a guarantee this function does not make.

    Args:
        connection: The connection reference this tool is registered against — a
            reference the provisioner already minted (ADR-0151 §3). Selecting among
            existing references is not minting one, proposing one or predicting
            one, which is what that clause governs.
        endpoint: The submission endpoint the tool is configured to use, in one of
            the two schemes :mod:`ai_assistant.tools.egress` pins.
        records: The connection store, read once per call by the seam and twice
            around the credential read by the transport (ADR-0148 §6). The **same**
            store object the provisioner writes, so a provisioning act cannot
            commit a revision this path could not yet see.
        secrets: The ``INTEGRATION``-scoped reading face (ADR-0125 §8). Never a
            ``SecretStore``: a transport handed a writing face could delete the
            credential it reads.
        connect: How a channel is obtained, for a test that substitutes a local
            double. ``None`` leaves the transport's own default, which is the one
            function in the tree that opens a socket.

    Returns:
        The declaration, the callable and the registration as one value.

    Raises:
        TransportPinError: If ``endpoint`` is not a form this seam pins — an
            unknown scheme, a missing host, an unusable port. The same class the
            transport raises for the same fact, so a deployment reads one error
            for one mistake whether it is caught at startup or at a send.
    """
    # Fail-fast only; the parsed value is deliberately discarded. See above.
    parse_smtp_endpoint(endpoint)
    registration = EgressRegistration(
        tool_id=SEND_EMAIL.id, reference=connection, transport_endpoint=endpoint
    )
    transport = (
        SmtpEgressTransport(registration=registration, records=records, secrets=secrets)
        if connect is None
        else SmtpEgressTransport(
            registration=registration, records=records, secrets=secrets, connect=connect
        )
    )
    return EgressIntegration(
        definition=SEND_EMAIL,
        implementation=SendEmail(transport),
        registration=registration,
    )


def egress_registrations(integration: EgressIntegration | None) -> RegistrationTable:
    """Return the binding seam's registration table for ``integration``.

    The seam's half of the same fact :func:`build_default_registry` uses for the
    registry's half, so a composition root cannot wire one without the other. An
    absent integration yields an **empty** table, which is not an inert value: it
    is what makes ADR-0152 §8's mis-registration refusal reachable, so a tool
    declaring either §3 keyword while bound to no connected account is refused
    rather than quietly answered "not an egress call".

    Args:
        integration: The configured integration, or ``None`` where a deployment
            configured none.

    Returns:
        A table holding its registration, or an empty one.
    """
    return RegistrationTable(() if integration is None else (integration.registration,))


# --- the factory --------------------------------------------------------


def build_default_registry(
    *, memory: MemoryStore, now: Clock = _utcnow, egress: EgressIntegration | None = None
) -> InMemoryToolRegistry:
    """Return the populated one-object registry+invoker the composition root wires (ADR-0048 §3).

    One factory returns the canonical
    :class:`~ai_assistant.tools.registry.InMemoryToolRegistry` — both
    ``ToolRegistry`` and ``ToolInvoker`` over one id→``(definition, callable)``
    map (ADR-0029 §1). The composition root injects the single returned object as
    both the selecting ``registry`` and the acting ``invoker`` (ADR-0029 §8), so
    the id selection reports and the id ``invoke`` acts on cannot come apart.

    Which tools exist, and each ``(definition, callable)`` binding, stays inside
    `tools/` (ADR-0016 §5): the caller supplies only the injected dependencies a
    tool needs and takes back a ready registry.

    Args:
        memory: The store ``recall_memory`` reads from — the *same* instance the
            learning loop retrieves from, so a recall sees what the user's memory
            holds (a composition-root obligation, as ADR-0028 §4's writer/store
            rule is). Depended on only through its Protocol.
        now: Clock ``current_time`` reads; defaults to ``datetime.now(UTC)``.
            Injectable so a test is deterministic.
        egress: The one configured egress integration, or ``None`` where a
            deployment configured none. **Conditional contents, and ADR-0048 §3
            permits them**: it fixes that "which tools exist, and the
            ``(definition, callable)`` binding of each, stays inside `tools/`" and
            that "the composition root supplies only the injected dependencies a
            tool needs", which is exactly what this parameter is — the dependency
            ``send_email`` needs is a connected account, and a deployment that has
            not named one has not supplied it. Registering the tool anyway would
            put a declaration in front of the selection stage that the binding seam
            refuses on every call (ADR-0152 §8): a capable-looking tool that can
            never succeed, which ADR-0144 §4's preference sequence would still rank
            and offer.

    Returns:
        A registry holding ``current_time`` and ``recall_memory``, and
        ``send_email`` where one is configured — ready to select from and invoke.
    """
    tools: list[tuple[ToolDefinition, BoundImplementation]] = [
        (CURRENT_TIME, CurrentTime(now=now)),
        (RECALL_MEMORY, RecallMemory(memory)),
    ]
    if egress is not None:
        tools.append((egress.definition, egress.implementation))
    return InMemoryToolRegistry(tools)


__all__ = [
    "CURRENT_TIME",
    "RECALL_MEMORY",
    "CurrentTime",
    "EgressIntegration",
    "RecallMemory",
    "build_default_registry",
    "build_send_email_integration",
    "egress_registrations",
]
