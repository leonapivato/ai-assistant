"""The harness's own composition: the slice of the real pipeline a benchmark drives.

**Why this is not ``build_engine``.** ``ai_assistant.app.build_engine`` wires the
whole product, and the only way to put a conversation into it is
``Engine.converse`` — which asks a model to *plan and answer* every turn. A
benchmark conversation already has both sides: LoCoMo's turns are two named humans,
LongMemEval's are a real user and a real assistant, and the corpus's assistant turns
are frequently where the evidence lives (#1029's P6 is exactly the question of
whether they survive ingestion). Driving them through ``converse`` would discard the
corpus's own assistant side, replace it with this system's, and charge two model
calls per turn against a ~5,900-turn corpus. It would measure a different experiment,
expensively.

So the harness assembles the ingestion path from the same public classes the
composition root uses, minus the turn-answering half it must not use. Everything that
decides what lands in memory is the production object: the same
``SqliteMemoryStore``, the same embedder the settings select, the same
``ConversationLifecycle`` capture, the same ``ModelBackedObserver``, the same
``DefaultMemoryPolicy``, the same ``MemoryIngestor`` holding the same
``ModelBackedReconciler``, the same ``SqliteTraceStore``.

**That list is checked rather than asserted, and #1293 is why.** For two published
pilots the reconciler was on it and not in the code: ``MemoryIngestor`` was
constructed here without one while ``app/composition.py`` wired it, so ADR-0159's
mechanism never ran in a scored run and the manifest — reading a setting rather than
an object — said it had. ``tests/benchmarks/test_harness_contracts.py`` now pins the
ingestor's keyword list against the composition root's, so the next argument to
appear there fails a test instead of a pilot.

**The three cardinality controls are imported, not copied.** ``RETRIEVAL_LIMIT``,
``EPISODIC_SUPPLEMENT_LIMIT`` and ``CONFLICT_LIMIT`` come from
``ai_assistant.app.composition`` itself, so a benchmark cannot silently measure a
retrieval budget the product does not use. That is the one guard against this module
drifting from the composition root it mirrors, and it is worth more than a comment
asking a reader to keep them in step.

**Two deliberate deviations, both recorded because they move a number.**

1. *No routing.* The composition root builds the answering seam as a
   ``RoutingProvider`` over ``default_model`` plus ``fallback_models``, so a failing
   provider is retried elsewhere. A benchmark holds the model fixed and reports it
   (#1029's threats-to-validity section says so in as many words), and a run whose
   answers came from two different models measures neither. The harness therefore
   uses one route with retry — the shape ``_build_observer_provider`` already uses,
   for a related reason.
2. *No hub.* Nothing here starts, contacts or requires the resident process; the
   harness is its own process and opens its own data directory. #1029's "all
   inference in worker processes, never the hub" is satisfied structurally by that,
   and it has to be: there is no worker-process mechanism in the tree to opt into.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from ai_assistant.app.composition import (
    CONFLICT_LIMIT,
    EPISODIC_SUPPLEMENT_LIMIT,
    RETRIEVAL_LIMIT,
)
from ai_assistant.core.config import EmbedderKind
from ai_assistant.core.errors import ConfigurationError
from ai_assistant.evaluation import SqliteTraceStore
from ai_assistant.learning import ModelBackedObserver
from ai_assistant.memory import (
    DefaultMemoryPolicy,
    MemoryIngestor,
    ModelBackedReconciler,
    SqliteDeferralStore,
    SqliteMemoryStore,
)

# Not a package export, so it is imported from its own module — the same line
# `app/composition.py` carries, for the same reason.
from ai_assistant.memory.conversation_store import SqliteConversationStore
from ai_assistant.models import (
    BoundedEmbedder,
    HashingEmbedder,
    PydanticAIProvider,
    ensure_vendor_available,
)
from ai_assistant.models.batch import anthropic_batch_completer
from ai_assistant.models.retry import RetryingProvider, RetryPolicy
from ai_assistant.orchestration import (
    ConversationLifecycle,
    MemoryWriteStage,
    ObservationStage,
)
from benchmarks.memory.clock import BenchmarkClock

if TYPE_CHECKING:
    from contextlib import AbstractAsyncContextManager
    from pathlib import Path

    from ai_assistant.core.config import Settings
    from ai_assistant.core.protocols import BatchCompleter, Embedder, ModelProvider, Observer
    from benchmarks.memory.spend import SpendGuard

__all__ = [
    "BATCH_PROVIDER",
    "DEFAULT_ISSUER",
    "Harness",
    "Reconciliation",
    "build_batch_completer",
    "build_embedder",
    "build_harness",
    "build_model_provider",
    "build_reconciler",
    "reconciler_spec",
    "refuse_unbatchable_route",
]

#: The provider half of a ``"provider:model"`` spec whose batch endpoint the harness
#: can actually reach.
#:
#: A two-word copy of ``ai_assistant.models.batch._PROVIDER_NAME``, under the same
#: discipline :data:`benchmarks.memory.answer.SUPPLEMENT_KINDS` is copied under: the
#: name is private and the harness does not widen a subsystem's surface for its own
#: convenience. ``tests/benchmarks/test_harness_contracts.py`` fails the day the two
#: disagree.
#:
#: **It is copied so the refusal can happen early, and early is the whole point.**
#: ``AnthropicBatchCompleter`` refuses a foreign spec itself — but at ``submit``,
#: which on a batched run is *after* every case has been ingested. On LoCoMo that is
#: ~294 paid observation calls and an hour of wall clock spent before the run
#: discovers it cannot answer.
BATCH_PROVIDER: Final = "anthropic"

#: The account label a run stamps on its batches when the operator names none.
#:
#: ADR-0143 §2 makes ``issuer`` an assertion the seam cannot check: it is what a
#: handle is compared against, so a deployment that labels two accounts alike gets a
#: handle accepted against the wrong one. The default therefore says plainly that
#: nobody named an account, rather than inventing one that looks specific — an
#: operator running against two accounts has to pass ``--issuer`` for the comparison
#: to mean anything, and a default like ``"default"`` would hide that.
DEFAULT_ISSUER: Final = "unnamed-account"


@dataclass(frozen=True, slots=True)
class Reconciliation:
    """ADR-0159's reconciler as this run wired it, beside the manifest's word for it.

    **The object and its description are one value because #1293 was the other
    arrangement.** Every pilot script since pilot-4 exported
    ``ASSISTANT_RECONCILER_MODEL``, and the run notes recorded it as if a reconciler
    were labelling conflicts — while ``build_harness`` constructed ``MemoryIngestor``
    with no ``reconciler`` at all. Two published runs therefore carry a provenance
    claim about a mechanism that never ran, and nothing in the artifacts could
    contradict it: the claim was read off a setting, and a setting is true whether or
    not anything acted on it.

    A field derived from ``Settings`` can always say that. This one cannot: it is
    produced by :func:`build_reconciler` in the same expression that constructs the
    reconciler, it is the value handed to :class:`~ai_assistant.memory.MemoryIngestor`,
    and there is no way to obtain the description without the object. So a manifest
    naming a reconciler is a manifest whose ingestor held one.

    Attributes:
        reconciler: The object the ingestor reconciles through.
        route: The ``"provider:model"`` spec it labels on — the argument it was
            constructed with, ``Settings.reconciler_model`` resolved against
            ``default_model`` exactly as ``app.composition._reconciler_spec`` resolves
            it.
        max_conflicts: ADR-0159 §3's bound it was constructed with — how many members
            of a conflict set, in rank order, one request may ask about.
    """

    reconciler: ModelBackedReconciler
    route: str
    max_conflicts: int

    @property
    def name(self) -> str:
        """The manifest's account of what actually reconciled.

        The class is read off the constructed object rather than named, so a run
        wired to something else says so; the two bounds beside it are the arguments
        that object holds and neither is separately configurable after construction.

        Returns:
            One line, in the shape ``ModelGrader``'s :attr:`name` has: what it is and
            what it was pointed at, fit for a manifest field and for a reader
            comparing two runs' provenance without opening either's code.
        """
        return (
            f"{type(self.reconciler).__name__}(route={self.route}, "
            f"max_conflicts={self.max_conflicts})"
        )


@dataclass(frozen=True, slots=True)
class Harness:
    """One case's worth of wired pipeline, over one data directory.

    Attributes:
        lifecycle: The capture path — a conversation turn becomes an episode.
        observation: The distillation path — episodes become beliefs.
        store: The memory store both of them write to and retrieval reads from.
        traces: The trace store. Held whole here, unlike anywhere in the product:
            ADR-0119 §7 withholds the walk from every component of the *request
            pipeline*, and this is an offline analysis tool in the shape
            ``MeasureReader`` already has. The emitters below still receive it
            narrowed to a ``TraceSink`` by their own constructors' annotations, so
            nothing in the pipeline gains the walk by this object existing.
        model: The answering seam, and the grading seam. One route, fixed.
        clock: The instant every injectable seam here reads. The driver moves it;
            see :mod:`benchmarks.memory.clock` for why a wall clock is wrong.
        embedder_model_id: The embedding space this run's vectors live in — recorded
            in the manifest, because a score computed under one embedder says nothing
            about another.
        reconciliation: ADR-0159's reconciler this case's ingestor actually holds,
            beside the manifest's word for it. Held on the harness rather than left
            inside ``MemoryIngestor`` — which exposes nothing — so a caller can record
            what reconciled without asking a setting what it thinks reconciled (#1293).
        model_route: The ``"provider:model"`` spec answers came from.
        observer_route: The spec episodes were distilled through. Reported separately
            because ``Settings.observer_model`` can differ from ``default_model``, and
            a pilot that changed one without recording it would be uninterpretable.
        retrieval_limit: The budget ``assemble_by_band`` fills, straight from the
            composition root.
        episodic_limit: The budget the answering turn's **episodic supplement** fills
            (ADR-0158 §3), straight from the composition root and never a share of
            ``retrieval_limit`` — the two are two budgets, so a question asks for 15
            beliefs *and* up to 5 episodes. Held beside the belief budget rather than
            derived from it because §3's ceiling clause is what the composition root
            already enforces; the harness reads both numbers and invents neither.
        data_dir: Where this case's databases live.
    """

    lifecycle: ConversationLifecycle
    observation: ObservationStage
    store: SqliteMemoryStore
    traces: SqliteTraceStore
    model: ModelProvider
    clock: BenchmarkClock
    embedder_model_id: str
    reconciliation: Reconciliation
    model_route: str
    observer_route: str
    retrieval_limit: int
    episodic_limit: int
    data_dir: Path
    #: Held so :meth:`close` can reach them — the concrete handle, because closing a
    #: resource is this composition root's business and no Protocol here declares it.
    #: ``conversations`` is also handed to the ingestion driver, which takes it as a
    #: ``ConversationStore`` and reads a turn's store-allocated ordinal through that
    #: contract: the only exact answer to where a captured turn sits in an observation
    #: window (ADR-0162 §7, #1075). Both are injected into the stages above, which is
    #: where the rest of the harness meets them; ``deferrals`` is named nowhere else.
    conversations: SqliteConversationStore
    deferrals: SqliteDeferralStore

    def __post_init__(self) -> None:
        """Hold ADR-0158 §3's ceiling where ``LearningLoop`` holds it: at construction.

        §3's normative clause — the configured episodic bound never exceeds the
        configured belief budget — is where that ADR puts the product thesis in
        checkable form, and the product does not trust the line that sets it: it
        re-checks at ``LearningLoop.__init__``. A harness that only *imported* the
        right numbers would hold the ceiling by provenance rather than by
        construction, and a benchmark measuring a configuration the product refuses to
        run would publish it as this system's behaviour. Checked here rather than in
        :func:`build_harness` so it also covers a harness derived with
        ``dataclasses.replace``, which is how a test varies these bounds.

        **The type check is mirrored too, and ``bool`` is why.** It looks redundant
        against ``mypy --strict`` — a ``float`` or a string cannot reach these fields
        without defeating the checker first — but ``bool`` is an ``int`` subclass, so
        ``True`` type-checks here and would run the whole supplement at a bound of
        one. That is the case ``_check_tuning`` calls out in as many words, "a flag is
        not a count", and it is the one a type annotation cannot hold. The rest of the
        check comes free once that line is written, and a benchmark's numbers are
        worth the four lines.

        Raises:
            TypeError: If either bound is not an integer, ``bool`` included.
            ValueError: If ``retrieval_limit`` is not positive, if ``episodic_limit``
                is negative, or if ``episodic_limit`` exceeds ``retrieval_limit``
                (ADR-0158 §3). Zero is legal for the episodic bound and disables the
                supplement, which is a value ADR-0158 §6's arm may choose.
        """
        for name, value, floor in (
            ("retrieval_limit", self.retrieval_limit, 1),
            ("episodic_limit", self.episodic_limit, 0),
        ):
            if isinstance(value, bool) or not isinstance(value, int):
                msg = f"{name} must be an integer, got {value!r}"
                raise TypeError(msg)
            if value < floor:
                msg = f"{name} must be at least {floor}, got {value}"
                raise ValueError(msg)
        if self.episodic_limit > self.retrieval_limit:
            msg = (
                f"episodic_limit must not exceed retrieval_limit (ADR-0158 §3): "
                f"{self.episodic_limit} > {self.retrieval_limit}"
            )
            raise ValueError(msg)

    def close(self) -> None:
        """Close every connection this harness opened, in the reverse of open order.

        The trace store is closed last because it was opened first: everything above
        it took it as a ``TraceSink``, and a store closed while a holder might still
        emit is the one ordering that can lose a trace at shutdown.
        """
        self.store.close()
        self.conversations.close()
        self.deferrals.close()
        self.traces.close()


def build_embedder(settings: Settings) -> Embedder:
    """Construct the embedder the settings select, bounded as production bounds it.

    Mirrors ``ai_assistant.app.composition._build_configured_embedder``, which is
    private and so cannot be called. The default is the on-device vendored
    ``bge-small-en-v1.5`` (ADR-0006 §2, ADR-0024) — which is what #1029 requires, and
    is why ``ASSISTANT_EMBEDDER`` is left alone for a real run. ``hashing`` selects
    the non-semantic QA embedder, which is useful for exercising plumbing without
    loading ONNX and is **not** a configuration any scored run may use.

    Args:
        settings: Loaded application settings.

    Returns:
        The embedder, wrapped in ``BoundedEmbedder`` exactly as the composition root
        wraps it, so a benchmark cannot accidentally measure an unbounded one.
    """
    inner: Embedder
    if settings.embedder is EmbedderKind.HASHING:
        inner = HashingEmbedder()
    else:
        # Imported here rather than at module scope for the reason the composition
        # root gives: the import pulls in ONNX, and the hashing path must not pay it.
        from ai_assistant.models.fastembed_embedder import (  # noqa: PLC0415 — deferred so the hashing path never imports fastembed/ONNX
            FastEmbedEmbedder,
        )

        inner = FastEmbedEmbedder()
    return BoundedEmbedder.from_settings(inner, settings)


def build_model_provider(
    settings: Settings, spec: str, *, guard: SpendGuard | None = None
) -> ModelProvider:
    """One route, with retry and without routing.

    ``ensure_vendor_available`` is called first, exactly as
    ``_build_observer_provider`` calls it and for the reason ADR-0062 §2 gives: an
    unresolvable spec would otherwise surface at the first completion as a bare
    non-retryable ``ModelError``, which on this seam means at the first question of a
    paid run. It is key-free and offline — it resolves the provider *class* and reads
    no credential — so it costs nothing and blocks nothing.

    Args:
        settings: Loaded application settings — the resilience knobs only.
        spec: The ``"provider:model"`` spec to use.
        guard: The run's spend guard, or ``None`` for an unguarded provider. Applied
            **outside** the retry, so a retried call is charged once — which is what
            ``plan_run`` counts, and therefore what a ceiling read off the plan means.

    Returns:
        The provider.

    Raises:
        ConfigurationError: If ``spec`` names a vendor unknown to pydantic-ai or whose
            optional package is not installed.
    """
    ensure_vendor_available(spec)
    built: ModelProvider = RetryingProvider(
        PydanticAIProvider(spec), policy=RetryPolicy.from_settings(settings)
    )
    return built if guard is None else guard.wrap(built)


def reconciler_spec(settings: Settings) -> str:
    """The one ``"provider:model"`` spec the reconciler labels through (ADR-0159 §3).

    Mirrors ``ai_assistant.app.composition._reconciler_spec``, which is private and so
    cannot be called: ``reconciler_model`` where the operator named one, otherwise
    ``default_model``. Spelled here rather than assumed, for the reason
    :func:`~benchmarks.memory.run.check_credentials_for` spells the judge's fallback —
    a reconciler on a route the answering seam never touches is exactly the
    configuration a startup check exists to refuse, and it cannot refuse a route it
    computed differently from the one that will be built.

    Args:
        settings: Loaded application settings.

    Returns:
        The spec, never empty: ``default_model`` stands behind it.
    """
    return (
        settings.reconciler_model
        if settings.reconciler_model is not None
        else settings.default_model
    )


def build_reconciler(
    settings: Settings, *, model: ModelProvider | None = None, guard: SpendGuard | None = None
) -> Reconciliation:
    """Construct ADR-0159's reconciler as the composition root constructs it.

    ``app/composition.py`` wires ``ModelBackedReconciler`` unconditionally — the route
    falls back to ``default_model``, so there is no configuration under which the
    product ingests without one — and this is the same wiring over the harness's own
    one-route seam. **It is unconditional here for the same reason**: a
    ``reconciler_model`` that is set and a ``reconciler_model`` that is unset are two
    routes, not a switch, and a harness that treated the unset case as "no reconciler"
    would measure a pipeline the product cannot be configured into.

    The provider is built by :func:`build_model_provider` rather than by copying
    ``_build_reconciler_provider``, and the two agree by construction: both are
    ``RetryingProvider`` over one ``PydanticAIProvider``, with no routing, which is
    what ADR-0159 §3 requires of this seam and is already why this module's answering
    and observation seams have that shape.

    **The guard reaches this seam, and it has to.** A reconciler labels at most one
    request per proposal, so a LoCoMo case's ingestion carries thousands of them —
    a paid seam the run's ceiling did not cover would make ``--max-model-calls`` a
    bound on a strict subset of what the run spends. :func:`~benchmarks.memory.run.
    plan_run` counts them for the same reason, so the ceiling stays readable off the
    plan in the currency the plan is written in.

    **What the guard cannot do here is stop the run at this seam**, and that is
    ADR-0159 §3's never-raises clause rather than a gap in the wrap: the reconciler
    catches ``Exception`` around its own request, so a ``RunAbortedError`` raised by
    the guard is converted into an unlabelled conflict set exactly as a model error
    is. The bound still holds — ``charge`` refuses before the call, so nothing is
    spent past it — and the run still stops, at the next answering or observation
    call, which is guarded by something that lets the abort out. What a reader must
    not conclude from a run's ``reconciler_failed`` count alone is that the model
    misbehaved; a run that also aborted may have been reporting its own ceiling.

    Args:
        settings: Loaded application settings — the route, the bound, and the
            resilience knobs :func:`build_model_provider` reads.
        model: Override the labelling seam. Supplied by tests, which must make no live
            model call; ``None`` builds the configured route. An injected reconciler
            reaches ``refuse_ineligible_scored_run`` clause 5 through
            :func:`~benchmarks.memory.run.execute_run`, so a *scored* run cannot carry
            one.
        guard: The run's spend guard, or ``None`` for an unguarded seam. Applied to a
            provider built here **and** to an injected one, for the reason
            :func:`build_harness` applies it to an injected answering seam: an
            injected provider stands in for a call the run would otherwise have made.

    Returns:
        The reconciler and the manifest's account of it, as one value.

    Raises:
        ConfigurationError: If the reconciler's route names a vendor unknown to
            pydantic-ai or whose optional package is not installed — raised at the
            build rather than at the first ingest that would have reconciled, which is
            the reason ``_build_reconciler_provider`` gives for checking it even when
            the route repeats ``default_model``.
    """
    route = reconciler_spec(settings)
    provider = (
        build_model_provider(settings, route, guard=guard)
        if model is None
        else (model if guard is None else guard.wrap(model))
    )
    return Reconciliation(
        reconciler=ModelBackedReconciler(
            model=provider, route=route, max_conflicts=settings.reconciler_max_conflicts
        ),
        route=route,
        max_conflicts=settings.reconciler_max_conflicts,
    )


def refuse_unbatchable_route(spec: str) -> None:
    """Fail now if ``spec``'s vendor has no batch endpoint this harness can reach.

    The sibling of :func:`~benchmarks.memory.run.check_credentials_for`, answering the
    question a batched run adds: not "does this route hold a credential" but "can this
    route be batched at all". Both are asked before a store is opened, and for the
    same reason — the failure they prevent otherwise lands after the expensive part.

    Args:
        spec: The ``"provider:model"`` spec the run will answer and judge on.

    Raises:
        ConfigurationError: If ``spec`` names a provider other than
            :data:`BATCH_PROVIDER`. Its own class rather than ``ValueError`` because
            this is a startup misconfiguration in exactly the sense
            ``ensure_vendor_available`` uses: there is nothing to retry and nothing to
            reroute, the run is simply configured for something it cannot do.
    """
    provider, separator, _ = spec.partition(":")
    if separator and provider != BATCH_PROVIDER:
        msg = (
            f"--phase batch cannot answer on {spec!r}: the only batch endpoint wired "
            f"into this tree is {BATCH_PROVIDER!r} (ADR-0143 §11 defers a second "
            f"vendor). Run --phase sync, or set ASSISTANT_DEFAULT_MODEL to an "
            f"{BATCH_PROVIDER} route."
        )
        raise ConfigurationError(msg)


def build_batch_completer(
    settings: Settings, *, issuer: str, spec: str | None = None
) -> AbstractAsyncContextManager[BatchCompleter]:
    """The harness's own composition root for bulk inference (ADR-0143 §8).

    §8 is normative that a consumer depends on the ``BatchCompleter`` Protocol and
    "never on a concrete class in ``models/`` for its types", and obtains an instance
    "by construction in a composition root it owns ... its own root for a consumer
    outside ``ai_assistant``". This module is that root, and this is the one line in
    it: the return type is the Protocol, and the concrete class is named nowhere the
    harness can see it.

    **It is a context manager because the client it owns is one.** The transport is
    built here and the completer exposes no accessor for it, so the block is what
    releases the connection pool — see ``models/batch.py`` for the argument, including
    why scoping the transport costs ADR-0143 §2's resumption story nothing (the handle
    is a value, and this run persists it to ``batches.jsonl`` inside the block).

    Nothing here checks a credential. That is
    :func:`~benchmarks.memory.run.check_credentials_for`'s job on the answering route,
    which is the same route this batches, and the harness asks it before any store is
    opened.

    Args:
        settings: Loaded application settings, read for the default route only.
        issuer: The non-secret account label stamped on every handle and compared
            against every handle presented. Never a credential — handles are written
            to ``batches.jsonl``.
        spec: The ``"provider:model"`` route to batch on, or ``None`` for
            ``settings.default_model``. The answering route by default, because the
            batch *is* the answering seam here.

    Returns:
        A block yielding the completer, typed as the Protocol.
    """
    return anthropic_batch_completer(
        issuer=issuer,
        default_model=spec if spec is not None else settings.default_model,
    )


def build_harness(  # noqa: PLR0913 — the three seam overrides are three distinct injection points and a bundle would hide which of them a caller left to the settings
    settings: Settings,
    *,
    data_dir: Path,
    model: ModelProvider | None = None,
    observer: Observer | None = None,
    reconciler: Reconciliation | None = None,
    guard: SpendGuard | None = None,
) -> Harness:
    """Wire one case's pipeline over ``data_dir``.

    Args:
        settings: Loaded application settings. Read for the embedder, the model
            specs, the retention horizons and the observation bounds — the same
            fields the composition root reads for the same collaborators.
        data_dir: Where this case's databases are created. One directory per case:
            a benchmark case is a whole memory, and two cases sharing a store would
            let one case's beliefs answer another's questions.
        model: Override the answering and grading seam. Supplied by tests, which must
            make no live model call; ``None`` builds the configured route.
        observer: Override the distillation seam, for the same reason.
        reconciler: The reconciler every case in a run shares, or ``None`` to build
            one from ``settings`` here. A run builds it once and hands it down, so the
            object the manifest describes is the object each ingestor holds — the
            property #1293 is about; a direct caller that passes ``None`` still gets
            the configured wiring rather than none.
        guard: The run's spend guard, shared with every other case and with the judge.
            It is applied to the answering seam whether that seam was built here or
            **injected** — the one place the guard covers a caller's own object, because
            an injected provider stands in for a call the run would otherwise have made
            and a budget nothing can drive is a budget nothing exercises.

            **An injected ``observer`` is not covered, and a caller passing one has moved
            distillation outside the run's budget.** An ``Observer`` is not a
            ``ModelProvider``: it holds its own provider behind a surface with no
            accessor, so there is nothing here to wrap, and reaching for one would be the
            harness widening a subsystem's contract for its own convenience. Built here,
            the observer's provider *is* guarded, which is the case every real run is in —
            and ``refuse_ineligible_scored_run`` clause 5 refuses an injected seam on a
            scored run outright, so the gap is reachable only from a smoke run, whose
            artifacts are already not a measurement.

    Returns:
        The wired harness. The caller owns it and must :meth:`Harness.close` it.
    """
    data_dir.mkdir(parents=True, exist_ok=True)
    embedder = build_embedder(settings)
    clock = BenchmarkClock()

    model_route = settings.default_model
    observer_route = (
        settings.observer_model if settings.observer_model is not None else settings.default_model
    )
    answering = (
        build_model_provider(settings, model_route, guard=guard)
        if model is None
        else (model if guard is None else guard.wrap(model))
    )

    traces = SqliteTraceStore(path=data_dir / "traces.db")
    # `now` is the benchmark clock; `traces_now` is left at its wall-clock default,
    # which is the separation ADR-0119 §5 exists for — a trace stream ordered by a
    # clock that jumps between cases would be unreadable, and the store's contract is
    # that a search judges every candidate against one reading of *its* clock.
    store = SqliteMemoryStore(
        path=data_dir / "memory.db", embedder=embedder, traces_sink=traces, now=clock
    )
    conversations = SqliteConversationStore(
        path=data_dir / "conversations.db",
        retention=settings.episode_retention,
        tombstone_grace=settings.conversation_tombstone_grace,
        now=clock,
    )
    deferrals = SqliteDeferralStore(
        path=data_dir / "deferrals.db",
        retention=settings.deferral_ttl,
        queue_limit=settings.deferral_queue_limit,
    )
    # `conflict_limit` is passed for the reason the composition root passes it: the
    # figure a trace records should be one this layer chose rather than one a default
    # filled in. The value is imported, so it is the product's figure either way.
    #
    # **`reconciler` is passed for a blunter reason: for two published pilots it was
    # not** (#1293). ADR-0159's mechanism defaulted to `None` here while the
    # composition root wired it, so every crossing of every scored run came back
    # `reconciler_absent` — 2,578 of 2,578 on pilot-5 — and the manifest said
    # otherwise. `tests/benchmarks/test_harness_contracts.py` now pins this call's
    # keyword list against the composition root's, so the next argument to appear
    # there cannot go missing here quietly.
    reconciliation = (
        reconciler if reconciler is not None else build_reconciler(settings, guard=guard)
    )
    writes = MemoryWriteStage(
        writer=MemoryIngestor(
            store=store,
            policy=DefaultMemoryPolicy(),
            traces_sink=traces,
            conflict_limit=CONFLICT_LIMIT,
            reconciler=reconciliation.reconciler,
            now=clock,
        ),
        deferrals=deferrals,
    )
    return Harness(
        lifecycle=ConversationLifecycle(
            conversations=conversations,
            memory=store,
            retention=settings.episode_retention,
            now=clock,
        ),
        observation=ObservationStage(
            observer=observer
            if observer is not None
            # `timezone` is passed for the same reason the bounds beside it are, and
            # it is the one argument here whose omission would be silent: ADR-0156 §3's
            # second clause has a producer handed no calendar render no instants and
            # resolve no relative expression — correct, deliberate behaviour, and not
            # the product's. A harness that took the `None` default would ingest with
            # no event times in the observation prompt while reporting a healthy run,
            # so the measurement of ADR-0156 would be void rather than negative (#1171).
            else ModelBackedObserver(
                build_model_provider(settings, observer_route, guard=guard),
                now=clock,
                timezone=settings.timezone,
                max_batch_size=settings.observation_batch_size,
                max_proposals=settings.observation_max_proposals,
            ),
            conversations=conversations,
            memory=store,
            writes=writes,
            batch_size=settings.observation_batch_size,
            route=observer_route,
        ),
        store=store,
        traces=traces,
        model=answering,
        clock=clock,
        embedder_model_id=embedder.model_id,
        reconciliation=reconciliation,
        model_route=model_route,
        observer_route=observer_route,
        retrieval_limit=RETRIEVAL_LIMIT,
        episodic_limit=EPISODIC_SUPPLEMENT_LIMIT,
        data_dir=data_dir,
        conversations=conversations,
        deferrals=deferrals,
    )
