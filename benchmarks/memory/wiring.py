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
``DefaultMemoryPolicy``, the same ``MemoryIngestor``, the same
``SqliteTraceStore``.

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
from typing import TYPE_CHECKING

from ai_assistant.app.composition import (
    CONFLICT_LIMIT,
    EPISODIC_SUPPLEMENT_LIMIT,
    RETRIEVAL_LIMIT,
)
from ai_assistant.core.config import EmbedderKind
from ai_assistant.evaluation import SqliteTraceStore
from ai_assistant.learning import ModelBackedObserver
from ai_assistant.memory import (
    DefaultMemoryPolicy,
    MemoryIngestor,
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
from ai_assistant.models.retry import RetryingProvider, RetryPolicy
from ai_assistant.orchestration import (
    ConversationLifecycle,
    MemoryWriteStage,
    ObservationStage,
)
from benchmarks.memory.clock import BenchmarkClock

if TYPE_CHECKING:
    from pathlib import Path

    from ai_assistant.core.config import Settings
    from ai_assistant.core.protocols import Embedder, ModelProvider, Observer

__all__ = ["Harness", "build_embedder", "build_harness", "build_model_provider"]


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
    model_route: str
    observer_route: str
    retrieval_limit: int
    episodic_limit: int
    data_dir: Path
    #: Held only so :meth:`close` can reach them; nothing else names either. They are
    #: injected into the stages above, which is where the rest of the harness meets
    #: them.
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


def build_model_provider(settings: Settings, spec: str) -> ModelProvider:
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

    Returns:
        The provider.

    Raises:
        ConfigurationError: If ``spec`` names a vendor unknown to pydantic-ai or whose
            optional package is not installed.
    """
    ensure_vendor_available(spec)
    return RetryingProvider(PydanticAIProvider(spec), policy=RetryPolicy.from_settings(settings))


def build_harness(
    settings: Settings,
    *,
    data_dir: Path,
    model: ModelProvider | None = None,
    observer: Observer | None = None,
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
    writes = MemoryWriteStage(
        writer=MemoryIngestor(
            store=store,
            policy=DefaultMemoryPolicy(),
            traces_sink=traces,
            conflict_limit=CONFLICT_LIMIT,
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
                build_model_provider(settings, observer_route),
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
        model=model if model is not None else build_model_provider(settings, model_route),
        clock=clock,
        embedder_model_id=embedder.model_id,
        model_route=model_route,
        observer_route=observer_route,
        retrieval_limit=RETRIEVAL_LIMIT,
        episodic_limit=EPISODIC_SUPPLEMENT_LIMIT,
        data_dir=data_dir,
        conversations=conversations,
        deferrals=deferrals,
    )
