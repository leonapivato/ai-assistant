"""The registry's contents, and the default-registry factory (ADR-0048 §3).

One local read-only tool, the one *configured* egress integration, and the
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

**The local tool transmits nothing.** ``current_time`` is read-only —
non-``side_effecting``, non-disclosing, ``NATURAL`` idempotency, ``FREE`` cost —
which keeps it clear of the idempotency-window machinery ADR-0029 §5 reserves for
``KEYED`` writes and of the spend policy a paid tool would need. It is the whole
of the local set: ADR-0208 §1 removed ``recall_memory``, because the turn's supply
is retrieved at one site and a tool reading the same store band-blind added a
confirmation and a payload nothing renders.

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
    from collections.abc import Collection, Mapping

    from ai_assistant.core.clock import Clock
    from ai_assistant.core.protocols import (
        InvocationLedger,
        OutboundTransport,
        Secrets,
        SpendGate,
    )
    from ai_assistant.core.types import FrozenJson
    from ai_assistant.tools.egress_binder import ConnectionRecords
    from ai_assistant.tools.invocation import BoundImplementation, EgressToolImplementation


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
    transport: OutboundTransport,
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
        transport: The injected capability of reaching the world (ADR-0191 §1),
            **required**. It used to be an optional keyword whose absence left the
            transport's own default — so a deployment that passed nothing reached
            the world through a default argument, which is the state ADR-0191 §3
            calls "an ambient capability wearing an injection's clothes". The one
            place that constructs the real implementation is
            ``app/composition.py`` (§3); a test hands
            :class:`~ai_assistant.testing.FakeOutboundTransport` by that same
            route, and there is no other route.

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
    return EgressIntegration(
        definition=SEND_EMAIL,
        implementation=SendEmail(
            SmtpEgressTransport(
                registration=registration,
                records=records,
                secrets=secrets,
                transport=transport,
            )
        ),
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
    *,
    now: Clock = _utcnow,
    egress: EgressIntegration | None = None,
    ledger: InvocationLedger,
    gate: SpendGate,
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
        now: Clock ``current_time`` reads; defaults to ``datetime.now(UTC)``.
            Injectable so a test is deterministic.
        ledger: The ``InvocationLedger`` the returned invoker claims and
            completes through (ADR-0192 §1, §3), passed straight to
            :class:`~ai_assistant.tools.registry.InMemoryToolRegistry` — required
            there and so required here, because the consume is unconditional. The
            composition root supplies the one object it also wires as
            ``AuditTrail`` and ``InvocationCompleter`` (ADR-0192 §9).
        gate: The ``SpendGate`` the returned invoker admits through, before the
            claim (ADR-0194 §3), passed straight to ``InMemoryToolRegistry`` —
            required there and so required here, because the admission is
            unconditional. The composition root supplies the **same** object it
            wires as ``AuditTrail``, ``InvocationCompleter`` and ``SpendLedger``:
            all four read the same rows, and two holders keyed by them could
            disagree about a total (ADR-0194 §5).
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
        A registry holding ``current_time``, and ``send_email`` where one is
        configured — ready to select from and invoke. **No memory tool is among
        them** (ADR-0208 §1), and no lane re-binds one under any id without an ADR
        deciding the question ADR-0208 leaves to #1732.
    """
    tools: list[tuple[ToolDefinition, BoundImplementation]] = [
        (CURRENT_TIME, CurrentTime(now=now)),
    ]
    if egress is not None:
        tools.append((egress.definition, egress.implementation))
    return InMemoryToolRegistry(tools, ledger=ledger, gate=gate)


__all__ = [
    "CURRENT_TIME",
    "CurrentTime",
    "EgressIntegration",
    "build_default_registry",
    "build_send_email_integration",
    "egress_registrations",
]
