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
from ai_assistant.models import HashingEmbedder, PydanticAIProvider, RetryingProvider
from ai_assistant.models.retry import RetryPolicy
from ai_assistant.orchestration import Engine, LearningLoop, StepExecutor, StepRunner
from ai_assistant.permissions import SqliteAuditTrail, ThresholdActionPolicy
from ai_assistant.planning import InMemoryPlanStore, ModelBackedPlanner
from ai_assistant.tools import build_default_registry

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

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
    * one :class:`InMemoryPlanStore` is shared by the runner, the executor, and
      the façade, and one :class:`SqliteAuditTrail` by the runner.

    **It owns the resources it opens.** The two connection-owning stores are
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
        settings: Loaded application settings — the model spec and its resilience
            knobs, and the context localisation window.
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

        model = RetryingProvider(
            PydanticAIProvider(settings.default_model),
            policy=RetryPolicy.from_settings(settings),
        )
        plans = InMemoryPlanStore()
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
            policy=ThresholdActionPolicy(),
            trail=trail,
            executor=StepExecutor(plans=plans, registry=tools, invoker=tools),
        )
        return Engine(
            loop=loop,
            runner=runner,
            plans=plans,
            closers=[_as_async(memory.close), _as_async(trail.close)],
        )
    except BaseException:
        # Close anything already opened before re-raising, so a failed build
        # returns no orphaned connection (ADR-0042 §2). Reverse order: last opened,
        # first closed.
        for close in reversed(opened):
            close()
        raise


def _as_async(close: Callable[[], None]) -> Callable[[], Awaitable[None]]:
    """Adapt a synchronous ``close()`` to the façade's async shutdown-path shape."""

    async def _aclose() -> None:
        close()

    return _aclose


def _default_data_dir() -> Path:
    """The per-user data directory, resolved without touching the environment."""
    return Path.home() / _DEFAULT_DATA_DIRNAME
