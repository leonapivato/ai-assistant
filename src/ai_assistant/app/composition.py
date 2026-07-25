"""Construct the production subsystems and wire them into an engine (ADR-0042 §2).

:func:`build_engine` is the composition root's one function. It names every
concrete implementation, discharges the wiring obligations no type can express,
owns the connection-owning resources it opens, and hands the façade an ordered
shutdown path — everything ADR-0042 §2 requires of this layer.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from ai_assistant.context import AssemblingContextProvider, ClockContextSource
from ai_assistant.core.errors import ConfigurationError
from ai_assistant.learning import RuleBasedFeedbackProcessor
from ai_assistant.memory import DefaultMemoryPolicy, MemoryIngestor, SqliteMemoryStore
from ai_assistant.models import (
    HashingEmbedder,
    PydanticAIProvider,
    RetryingProvider,
    Route,
    RoutingProvider,
)
from ai_assistant.models.retry import RetryPolicy
from ai_assistant.orchestration import Engine, LearningLoop, StepExecutor, StepRunner
from ai_assistant.permissions import SqliteAuditTrail, ThresholdActionPolicy
from ai_assistant.planning import ModelBackedPlanner, SqlitePlanStore
from ai_assistant.tools import build_default_registry

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Sequence

    from ai_assistant.core.config import Settings

#: Where the connection-owning SQLite stores live by default. A per-user directory
#: rather than a value read from the environment (``core.config.Settings`` owns
#: configuration; this is a filesystem default, overridable via ``data_dir``).
_DEFAULT_DATA_DIRNAME = ".ai-assistant"


def build_engine(settings: Settings, *, data_dir: Path | None = None) -> Engine:
    """Wire the production subsystems into a ready :class:`Engine` (ADR-0042 §2).

    The one place concrete subsystems are constructed. It discharges the wiring
    obligations no type can express — **once**, here, rather than copied into
    every front end (ADR-0042 §2):

    * the *same* :class:`SqliteMemoryStore` instance is injected into the loop
      (for retrieval) and into the :class:`MemoryIngestor` writer (for
      persistence), so the closed learning loop is not silently open (ADR-0028 §4);
    * one :class:`InMemoryToolRegistry` object is injected as both the selecting
      ``ToolRegistry`` and the acting ``ToolInvoker`` (ADR-0029 §8);
    * one :class:`SqlitePlanStore` is shared by the runner, the executor, and
      the façade, and one :class:`SqliteAuditTrail` by the runner and the façade
      — the façade reads the trail (query-only) to recover a durably-parked
      confirmation after a restart (ADR-0052 §1);
    * the model seam is composed **retry inside routing**, the order ADR-0013 §3
      recommends and that nothing in `models/` can enforce, since enforcing it
      would mean a wrapper knowing what wraps it (see :func:`_build_model_provider`).

    **It owns the resources it opens.** The three connection-owning stores are
    opened first; if any *later* construction fails, the ones already opened are
    closed before the error propagates, so no half-built engine leaks a connection
    (ADR-0042 §2). On success, their ``close`` methods are handed to the façade as
    its ordered shutdown path — the façade's ``aclose`` drains in-flight work, then
    closes them (ADR-0042 §2); the caller (an adapter) owns calling ``aclose``.

    The tool registry is populated with the first **local, no-egress** tools
    (ADR-0048): ``current_time`` and ``recall_memory``. So a planned step naming
    one of their capabilities selects, gates and executes; a step naming any other
    capability still finds no capable tool and is skipped (``NO_CAPABLE_TOOL``).
    Whether the planner names a tool's exact capability string is not guaranteed
    (ADR-0014 §2 keeps planning blind to the tool set), which is the model↔tool
    alignment follow-up ADR-0048 records rather than solves.

    Args:
        settings: Loaded application settings — the model specs the router routes
            over (``default_model`` then ``fallback_models``, ADR-0062) and their
            resilience knobs, the context localisation window, the parked-confirmation
            lifetime the runner enforces (``confirmation_ttl``, #310), and the four
            permission gate thresholds the policy is constructed with (#239).
        data_dir: Where the SQLite stores live. Defaults to a per-user directory
            (``~/.ai-assistant``), created if absent; a test passes a temporary
            path.

    Returns:
        A ready :class:`Engine`. Drive it with ``converse``/``resume`` and close
        it with ``aclose`` when the session ends.

    Raises:
        ConfigurationError: If the data directory cannot be prepared — blocked by
            permissions, or a file occupies its path. Converted from the raw
            ``OSError`` so an adapter's ``AssistantError`` boundary surfaces it
            rather than letting it escape as a traceback.
    """
    directory = data_dir if data_dir is not None else _default_data_dir()
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        msg = f"could not prepare the data directory {directory}: {exc}"
        raise ConfigurationError(msg) from exc

    opened: list[Callable[[], None]] = []
    try:
        # The connection-owning stores first, tracked for build-failure cleanup.
        memory = SqliteMemoryStore(path=directory / "memory.db", embedder=HashingEmbedder())
        opened.append(memory.close)
        trail = SqliteAuditTrail(path=directory / "audit.db")
        opened.append(trail.close)
        # Durable plan/execution state, so a parked AWAITING_APPROVAL step survives
        # a restart and can be recovered through the façade (ADR-0049, ADR-0052; #318).
        plans = SqlitePlanStore(path=directory / "plans.db")
        opened.append(plans.close)

        model = _build_model_provider(settings, _model_specs(settings))
        # One object as both the selecting registry and the acting invoker
        # (ADR-0029 §8). Populated with the first local tools (ADR-0048); the
        # memory-backed `recall_memory` reads the *same* store the loop retrieves
        # from, so a recall sees what the user's memory holds.
        tools = build_default_registry(memory=memory)

        context = AssemblingContextProvider(
            [
                ClockContextSource(
                    timezone=settings.timezone,
                    working_hours_start=settings.working_hours_start,
                    working_hours_end=settings.working_hours_end,
                )
            ]
        )
        # The writer persists to the *same* store the loop retrieves from (ADR-0028 §4).
        writer = MemoryIngestor(store=memory, policy=DefaultMemoryPolicy())
        loop = LearningLoop(
            context=context,
            memory=memory,
            writer=writer,
            planner=ModelBackedPlanner(model),
            feedback=RuleBasedFeedbackProcessor(),
        )
        runner = StepRunner(
            plans=plans,
            registry=tools,
            # The four gate thresholds are the operator's configuration (ADR-0021 §5,
            # #239); the Settings defaults reproduce the policy's own, so an unset
            # deployment keeps today's gate. The two floors take no setting.
            policy=ThresholdActionPolicy(
                confirm_at_risk=settings.confirm_at_risk,
                confirm_at_reversibility=settings.confirm_at_reversibility,
                deny_at_risk=settings.deny_at_risk,
                deny_at_reversibility=settings.deny_at_reversibility,
            ),
            trail=trail,
            executor=StepExecutor(plans=plans, registry=tools, invoker=tools),
            # A parked confirmation's lifetime is a deployment value (#310); ``None``
            # (the default) keeps the pre-#243 behaviour of no lifetime.
            confirmation_ttl=settings.confirmation_ttl,
        )
        return Engine(
            loop=loop,
            runner=runner,
            plans=plans,
            trail=trail,
            closers=[_as_async(memory.close), _as_async(trail.close), _as_async(plans.close)],
        )
    except BaseException:
        # Close anything already opened before re-raising, so a failed build
        # returns no orphaned connection (ADR-0042 §2). Reverse order: last opened,
        # first closed.
        for close in reversed(opened):
            close()
        raise


def _model_specs(settings: Settings) -> tuple[str, ...]:
    """The ``"provider:model"`` specs to route over, most preferred first (ADR-0062).

    The operator's ``default_model`` always leads, and ``fallback_models`` — empty
    unless configured — supplies the rest, in the order it was written. So an
    unset deployment gets exactly the single route ADR-0061 §2 described, and a
    configured one gets a router that can genuinely fall back, which is what
    retires that caveat.

    This *reads* the preference order rather than deciding it. Which models are
    acceptable, and in what order, is the operator's call;
    ``core.config.Settings`` is where it is named, parsed and validated
    (ADR-0062 §§1, 3). What this layer owns is how those specs are composed —
    :func:`_build_model_provider`.

    Args:
        settings: Loaded application settings.

    Returns:
        The model specs in preference order. Never empty: ``default_model`` leads.
    """
    return (settings.default_model, *settings.fallback_models)


def _build_model_provider(settings: Settings, specs: Sequence[str]) -> RoutingProvider:
    """Build the production model seam: retry *inside* routing (ADR-0013 §3).

    The seam every consumer sees is a ``ModelProvider``; what stands behind it is
    this composition root's decision, and ADR-0013 §3 settled which order to
    compose the two wrappers in. Retrying within a provider is the cheap
    correction — a transient blip resolves without transmitting the prompt to a
    second vendor or paying a second bill — so retry goes innermost and routing
    wraps it. The opposite nesting re-routes on every attempt, spreading one
    logical request across providers on the first blip.

    Every route gets its own :class:`RetryingProvider` with the *same* configured
    policy: the resilience knobs (``model_timeout_seconds`` and friends) are a
    property of how patient this deployment is, not of which vendor answered.

    Args:
        settings: Loaded application settings — the resilience knobs each route's
            retry wrapper is built from.
        specs: The ``"provider:model"`` specs to route over, most preferred first.
            Must be non-empty.

    Returns:
        The routed, retrying provider the planner is given.

    Raises:
        ConfigurationError: If ``specs`` is empty — raised by ``RoutingProvider``,
            which refuses a router with nothing to route to.
    """
    policy = RetryPolicy.from_settings(settings)
    return RoutingProvider(
        [Route(RetryingProvider(PydanticAIProvider(spec), policy=policy)) for spec in specs]
    )


def _as_async(close: Callable[[], None]) -> Callable[[], Awaitable[None]]:
    """Adapt a synchronous ``close()`` to the façade's async shutdown-path shape."""

    async def _aclose() -> None:
        close()

    return _aclose


def _default_data_dir() -> Path:
    """The per-user data directory, resolved without touching the environment."""
    return Path.home() / _DEFAULT_DATA_DIRNAME
