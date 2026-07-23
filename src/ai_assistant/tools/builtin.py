"""The first local, no-egress tools, and the default-registry factory (ADR-0048).

Two read-only tools and a factory that binds them into the canonical one-object
registry+invoker (:class:`~ai_assistant.tools.registry.InMemoryToolRegistry`).
Registration is internal to this subsystem (ADR-0016 §5, ADR-0029 §1); the
composition root calls :func:`build_default_registry` and injects the single
returned object as both the selecting ``ToolRegistry`` and the acting
``ToolInvoker`` (ADR-0029 §8).

**Nothing here transmits off-device.** Both tools are read-only —
non-``side_effecting``, non-disclosing, ``NATURAL`` idempotency, ``FREE`` cost —
which keeps this slice clear of the egress seam ADR-0017 §2 leaves undesignated,
the idempotency-window machinery ADR-0029 §5 reserves for ``KEYED`` writes, and
the spend policy a paid tool would need. A tool needing an external service, a
credential, or a write is a later lane.

Each tool's declared ``parameters_schema`` is **carried, not enforced** at
selection (ADR-0016 §7 defers that), so each callable validates its own inputs
and raises on a bad argument — which the seam classifies ``INTERNAL`` (ADR-0029
§3). No message raised here interpolates a parameter value, so nothing untrusted
reaches the Tier 2 failure text or a log.
"""

from __future__ import annotations

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
from ai_assistant.tools.registry import InMemoryToolRegistry

if TYPE_CHECKING:
    from collections.abc import Collection, Mapping

    from ai_assistant.core.clock import Clock
    from ai_assistant.core.protocols import MemoryStore
    from ai_assistant.core.types import FrozenJson

#: Default number of memory records ``recall_memory`` returns when the call names
#: no ``limit``. Small, because a recall folds into a turn a person reads.
_DEFAULT_RECALL_LIMIT = 5


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
            "limit": {"type": "integer", "minimum": 1},
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
                or not a string, or ``limit`` is present and not a positive
                integer.
        """
        _reject_unknown(parameters, ("query", "limit"), RECALL_MEMORY.id)
        query = parameters.get("query")
        if not isinstance(query, str):
            msg = "recall_memory requires a string 'query' argument"
            raise ValueError(msg)
        limit = parameters.get("limit", _DEFAULT_RECALL_LIMIT)
        # A bool is an int subclass and is not a count; reject it like the rest.
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            msg = "recall_memory 'limit' must be a positive integer"
            raise ValueError(msg)
        records = await self._memory.search(query, limit=limit)
        return [record.model_dump(mode="json") for record in records]


# --- the factory --------------------------------------------------------


def build_default_registry(*, memory: MemoryStore, now: Clock = _utcnow) -> InMemoryToolRegistry:
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

    Returns:
        A registry holding ``current_time`` and ``recall_memory``, ready to select
        from and invoke.
    """
    return InMemoryToolRegistry(
        [
            (CURRENT_TIME, CurrentTime(now=now)),
            (RECALL_MEMORY, RecallMemory(memory)),
        ]
    )


__all__ = [
    "CURRENT_TIME",
    "RECALL_MEMORY",
    "CurrentTime",
    "RecallMemory",
    "build_default_registry",
]
