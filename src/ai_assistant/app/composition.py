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
from ai_assistant.core.config import EmbedderKind
from ai_assistant.core.errors import ConfigurationError, ModelError
from ai_assistant.learning import RuleBasedFeedbackProcessor
from ai_assistant.memory import DefaultMemoryPolicy, MemoryIngestor, SqliteMemoryStore
from ai_assistant.models import (
    HashingEmbedder,
    PydanticAIProvider,
    RetryingProvider,
    Route,
    RoutingProvider,
    ensure_vendor_available,
)
from ai_assistant.models.retry import RetryPolicy
from ai_assistant.orchestration import Engine, LearningLoop, StepExecutor, StepRunner
from ai_assistant.permissions import SqliteAuditTrail, ThresholdActionPolicy
from ai_assistant.planning import ModelBackedPlanner, SqlitePlanStore
from ai_assistant.tools import build_default_registry

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Sequence

    from ai_assistant.core.config import Settings
    from ai_assistant.core.protocols import Embedder

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

    **Configuration is validated before any resource is opened (#372).** The
    resource-free construction — the model seam (which checks every configured
    spec's vendor, ADR-0062 §2), the context provider (which reads only settings),
    and the embedder (whose on-device default checks the vendored model artifact,
    ADR-0006 §2, ADR-0024) — runs *above* the data directory and the stores, so a
    bad configuration fails without ever touching disk: no directory is created and
    no database file is written for a build that was never going to succeed. Only
    the steps that genuinely need an open store stay below that line.

    **It owns the resources it opens.** The three connection-owning stores are
    opened first among the resources; if any *later* construction fails, the ones
    already opened are closed before the error propagates, so no half-built engine
    leaks a connection (ADR-0042 §2). On success, their ``close`` methods are handed
    to the façade as its ordered shutdown path — the façade's ``aclose`` drains
    in-flight work, then closes them (ADR-0042 §2); the caller (an adapter) owns
    calling ``aclose``.

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
            rather than letting it escape as a traceback. Or if a configured model
            spec names a vendor pydantic-ai does not know or whose optional package
            is not installed (ADR-0062 §2, see :func:`_build_model_provider`). Or if
            the on-device embedder cannot be constructed because its vendored model
            artifact is missing or incomplete (ADR-0006 §2, ADR-0024, see
            :func:`_build_embedder`).
    """
    # Validate everything that needs no resource before opening a store, so a bad
    # configuration fails before build_engine touches disk (#372). The model seam
    # checks every spec's vendor (ADR-0062 §2) and the context provider reads only
    # settings; neither opens a connection-owning store, so both are built here,
    # above the data directory. Every step that needs an open store stays below,
    # inside the cleanup block that closes what it opened on a later failure.
    model = _build_model_provider(settings, _model_specs(settings))
    context = AssemblingContextProvider(
        [
            ClockContextSource(
                timezone=settings.timezone,
                working_hours_start=settings.working_hours_start,
                working_hours_end=settings.working_hours_end,
            )
        ]
    )
    # Construct the embedder here too — above the data directory — so a missing or
    # unbuildable model fails as a ConfigurationError before any disk is touched
    # (ADR-0006 §2 default, #372's above-disk contract; see :func:`_build_embedder`).
    embedder = _build_embedder(settings)

    directory = data_dir if data_dir is not None else _default_data_dir()
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        msg = f"could not prepare the data directory {directory}: {exc}"
        raise ConfigurationError(msg) from exc

    opened: list[Callable[[], None]] = []
    try:
        # The connection-owning stores first, tracked for build-failure cleanup.
        memory = SqliteMemoryStore(path=directory / "memory.db", embedder=embedder)
        opened.append(memory.close)
        trail = SqliteAuditTrail(path=directory / "audit.db")
        opened.append(trail.close)
        # Durable plan/execution state, so a parked AWAITING_APPROVAL step survives
        # a restart and can be recovered through the façade (ADR-0049, ADR-0052; #318).
        plans = SqlitePlanStore(path=directory / "plans.db")
        opened.append(plans.close)

        # One object as both the selecting registry and the acting invoker
        # (ADR-0029 §8). Populated with the first local tools (ADR-0048); the
        # memory-backed `recall_memory` reads the *same* store the loop retrieves
        # from, so a recall sees what the user's memory holds.
        tools = build_default_registry(memory=memory)

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

    **Every spec's vendor is checked here, before any route is built** — the half
    of ADR-0062 §2 that was decided in principle and deferred for want of a
    mechanism. ``core.config`` validated each spec's *form* at load but cannot ask
    whether the vendor behind it is installed: answering that means reaching
    pydantic-ai, which the import contract forbids this layer (golden rule 4). So
    ``models`` answers it and this layer asks — reaching the SDK only indirectly,
    through the seam, exactly as the contract permits.

    The check covers ``default_model`` as well as the fallbacks, because ``specs``
    is the whole preference order and an unresolvable *primary* is the worse case:
    it disables the entire fallback order rather than the tail of it (ADR-0062 §2).

    Args:
        settings: Loaded application settings — the resilience knobs each route's
            retry wrapper is built from.
        specs: The ``"provider:model"`` specs to route over, most preferred first.
            Must be non-empty.

    Returns:
        The routed, retrying provider the planner is given.

    Raises:
        ConfigurationError: If any spec names a vendor that is unknown to
            pydantic-ai or whose optional package is not installed — raised by
            ``ensure_vendor_available``, so an operator learns at startup rather
            than on some user's request weeks later. Or if ``specs`` is empty —
            raised by ``RoutingProvider``, which refuses a router with nothing to
            route to.
    """
    for spec in specs:
        ensure_vendor_available(spec)
    policy = RetryPolicy.from_settings(settings)
    return RoutingProvider(
        [Route(RetryingProvider(PydanticAIProvider(spec), policy=policy)) for spec in specs]
    )


def _build_embedder(settings: Settings) -> Embedder:
    """Construct the configured :class:`Embedder`, before any resource is opened.

    ADR-0006 §2's firm decision is that **on-device embedding is the default**:
    memory content is Tier-1 personal data (ADR-0004) and must not leave the device
    merely to be indexed. So ``settings.embedder`` defaults to the vendored
    on-device model (:class:`FastEmbedEmbedder`, ADR-0024), and this is where that
    ratified default is finally honoured by the running app — the composition root
    had wired the non-semantic :class:`HashingEmbedder` unconditionally, leaving
    production "semantic" recall not actually semantic (roadmap leg 2).

    The two realizable modes are the only ones ADR-0024 admits — one vendored model,
    no arbitrary-model path — so this is a mode switch, not a model resolver:

    * :attr:`EmbedderKind.ON_DEVICE` → the vendored :class:`FastEmbedEmbedder`.
    * :attr:`EmbedderKind.HASHING` → the deterministic :class:`HashingEmbedder`,
      for tests, offline use, and CI (its similarity is not semantic).

    ``FastEmbedEmbedder`` is imported **here, lazily, not at module scope**, because
    ``ai_assistant.models.fastembed_embedder`` pulls in ``fastembed`` and the ONNX
    runtime (its own docstring says to import it directly and only when wiring the
    real store). Building against the hashing embedder — the whole test gate and any
    offline run — must not pay that import, and the module is deliberately not
    re-exported from ``ai_assistant.models`` for the same reason.

    Constructing the on-device embedder stays **offline and cheap**: it resolves
    :attr:`~FastEmbedEmbedder.dimensions` and its embedding-space identity from the
    packaged artifact's metadata and digests, and defers loading the ONNX model
    itself to the first ``embed`` — which ``build_engine`` never triggers. It is run
    above the data directory (like :func:`_build_model_provider`) so an incomplete
    install fails before ``build_engine`` touches disk (#372).

    Args:
        settings: Loaded application settings — ``embedder`` selects the mode.

    Returns:
        The embedder the memory store embeds and retrieves with.

    Raises:
        ConfigurationError: If the on-device embedder cannot be prepared — its
            vendored model artifact is missing or incomplete (caught by an explicit
            presence check here, above disk); the ``fastembed``/ONNX runtime cannot
            be imported (a pruned install or an unloadable native library); or the
            artifact is present but its metadata is malformed (``FastEmbedEmbedder``
            signals that with a ``ModelError``, re-raised here). All are
            operator-facing install faults — a build input never downloaded at
            runtime (ADR-0024) — so they surface as the same class the model seam's
            vendor check raises (:func:`_build_model_provider`), letting an adapter's
            error boundary report a configuration problem rather than a raw import
            error or a model-call failure.
    """
    if settings.embedder is EmbedderKind.HASHING:
        return HashingEmbedder()

    # EmbedderKind.ON_DEVICE — the default (ADR-0006 §2). Everything below is
    # imported lazily so the hashing path never pays fastembed's ONNX import.
    from ai_assistant.models.embedding_artifact import (  # noqa: PLC0415 — deferred with the on-device branch; see docstring
        missing_files,
        packaged_artifact_dir,
    )

    # Check the vendored artifact is present *here*, above the data directory, so an
    # incomplete install fails before build_engine touches disk. This check cannot be
    # left to FastEmbedEmbedder's construction: that reads only offline metadata (the
    # manifest-constant digest for its id, fastembed's supported-model table for its
    # dimensions) and defers the artifact to _FastEmbedBackend.load on the first
    # embed. So a genuinely missing model would otherwise not surface until the first
    # memory add/search — below the data directory, as a MemoryStoreError, after the
    # stores were already opened on disk — which is exactly the pre-disk contract
    # #372 established for the other resource-free steps. The presence check mirrors
    # the backend's own (ADR-0024 §5: presence, not integrity; integrity is a
    # build-time concern), so it stays cheap — no file is read or hashed.
    directory = packaged_artifact_dir()
    absent = missing_files(directory)
    if absent:
        msg = (
            f"the on-device embedder's vendored model artifact is missing from {directory} "
            f"({', '.join(absent)}); it is a build input (ADR-0024) and is never downloaded at "
            f"runtime, so this installation is incomplete. Set ASSISTANT_EMBEDDER=hashing to run "
            f"without it (retrieval is then non-semantic)"
        )
        raise ConfigurationError(msg)

    # The import itself can fail — `fastembed` (a required, pinned dependency) absent
    # from a dependency-pruned install, or its ONNX native library unloadable on this
    # platform (an `OSError`). That is still an operator-facing install fault, above
    # disk, so it joins the other on-device failures as a `ConfigurationError` rather
    # than escaping the composition root as a raw `ImportError`/`OSError` outside the
    # `AssistantError` hierarchy an adapter's boundary catches.
    try:
        from ai_assistant.models.fastembed_embedder import (  # noqa: PLC0415 — deferred so the hashing path never imports fastembed/ONNX
            FastEmbedEmbedder,
        )
    except (ImportError, OSError) as exc:
        msg = (
            f"could not load the on-device embedding runtime (fastembed/ONNX): {exc}. It is a "
            f"required dependency of this installation; reinstall it, or set "
            f"ASSISTANT_EMBEDDER=hashing to run without it (retrieval is then non-semantic)"
        )
        raise ConfigurationError(msg) from exc

    try:
        return FastEmbedEmbedder()
    except ModelError as exc:
        # The artifact was present above but its metadata (its embedding-space id or
        # reported dimension) is malformed — still a config-time install fault, so it
        # joins the missing-artifact case as a ConfigurationError rather than escaping
        # as a model-call failure.
        msg = f"could not construct the on-device embedder: {exc}"
        raise ConfigurationError(msg) from exc


def _as_async(close: Callable[[], None]) -> Callable[[], Awaitable[None]]:
    """Adapt a synchronous ``close()`` to the façade's async shutdown-path shape."""

    async def _aclose() -> None:
        close()

    return _aclose


def _default_data_dir() -> Path:
    """The per-user data directory, resolved without touching the environment."""
    return Path.home() / _DEFAULT_DATA_DIRNAME
