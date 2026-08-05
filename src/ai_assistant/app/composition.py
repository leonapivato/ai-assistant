"""Construct the production subsystems and wire them into an engine (ADR-0042 §2).

:func:`build_engine` is the composition root's one function. It names every
concrete implementation, discharges the wiring obligations no type can express,
owns the connection-owning resources it opens, and hands the façade an ordered
shutdown path — everything ADR-0042 §2 requires of this layer.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final, assert_never

from ai_assistant.context import (
    AssemblingContextProvider,
    CalendarContextSource,
    ClockContextSource,
)
from ai_assistant.core.config import EmbedderKind
from ai_assistant.core.errors import ConfigurationError, ModelError
from ai_assistant.learning import ModelBackedObserver, RuleBasedFeedbackProcessor
from ai_assistant.memory import (
    DefaultMemoryPolicy,
    MemoryIngestor,
    SqliteDeferralStore,
    SqliteMemoryStore,
)
from ai_assistant.memory.conversation_store import SqliteConversationStore
from ai_assistant.memory.reembed import Reembedder
from ai_assistant.models import (
    HashingEmbedder,
    PydanticAIProvider,
    RetryingProvider,
    Route,
    RoutingProvider,
    ensure_credential_available,
    ensure_vendor_available,
)
from ai_assistant.models.retry import RetryPolicy
from ai_assistant.orchestration import (
    ConversationLifecycle,
    Engine,
    GrantOperations,
    HeldSource,
    IngestionStage,
    LearningLoop,
    MemoryWriteStage,
    ObservationStage,
    QuestionStage,
    StepExecutor,
    StepRunner,
)
from ai_assistant.orchestration.payloads import ENVELOPE_RESERVE_BYTES
from ai_assistant.permissions import (
    SqliteAuditTrail,
    SqliteSourceGrantStore,
    ThresholdActionPolicy,
)
from ai_assistant.planning import ModelBackedPlanner, SqlitePlanStore
from ai_assistant.readers import CalendarReader
from ai_assistant.tools import build_default_registry

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Sequence
    from pathlib import Path

    from ai_assistant.core.config import Settings
    from ai_assistant.core.protocols import Embedder


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
    * the deferred-question queue (ADR-0078) is opened here, under the same data
      directory and owner-only file mode as the other Tier 1 stores, and joined to
      the façade's ordered shutdown — with its claim-token source left at its
      ``secrets``-backed **default**, which is the guarantee rather than a detail;
    * **one** :class:`MemoryWriteStage` over that writer and that queue is shared by
      the learn leg and the observation stage, and the :class:`QuestionStage` that
      answers a question is given the very same queue, writer and store — which is
      how two of ADR-0078 §3's three composition-root obligations are discharged
      here rather than hoped for (the third is structural);
    * one :class:`SqlitePlanStore` is shared by the runner, the executor, and
      the façade, and one :class:`SqliteAuditTrail` by the runner and the façade
      — the façade reads the trail (query-only) to recover a durably-parked
      confirmation after a restart (ADR-0052 §1);
    * the :class:`ConversationLifecycle` capture stage is given that *same*
      memory store and the one retention horizon settings names, so a captured
      episode and the conversation index that names it expire against one clock
      rather than two (ADR-0074 §7, §9);
    * the model seam is composed **retry inside routing**, the order ADR-0013 §3
      recommends and that nothing in `models/` can enforce, since enforcing it
      would mean a wrapper knowing what wraps it (see :func:`_build_model_provider`);
    * the **observer's** seam is composed differently on purpose — retry and *no
      routing*, one named route that never falls back (ADR-0077 §3, see
      :func:`_build_observer_provider`) — and the stage is told which route that is,
      because reporting which model read the episodes is what ADR-0013 §6 records as
      owed and no seam exposes it;
    * the **grant store is opened here**, as the **sixth** connection-owning Tier 1
      store, and the *same object* is passed twice — as a
      :class:`~ai_assistant.core.protocols.SourceGrantStore` to the grant operations
      and as a :class:`~ai_assistant.core.protocols.SourceGrants` to every driver
      (ADR-0102 §7). Structural typing is what makes one object serve both; what a
      driver cannot do is *name* ``record``, because ``mypy --strict`` runs over
      ``src`` and ``tests`` and the attribute is not on the annotated type
      (ADR-0097 §3);
    * the **read-only ingestion stage and the calendar context source** are wired
      whenever a source is configured (ADR-0093 §7's disabled default), each over
      its **own** reader instance (ADR-0096 §5) — and this is the one place a
      concrete :class:`~ai_assistant.core.protocols.Reader` may be
      constructed at all, because ``lint-imports`` forbids ``ai_assistant.readers``
      to every subsystem and exempts only this layer (see
      :func:`_build_calendar_reader`).

    **Configuration is validated before any resource is opened (#372).** The
    resource-free construction — the model seam (which checks every configured
    spec's vendor, ADR-0062 §2), the context provider (which reads only settings),
    and the embedder (whose on-device default checks the vendored model artifact,
    ADR-0006 §2, ADR-0024) — runs *above* the data directory and the stores, so a
    bad configuration fails without ever touching disk: no directory is created and
    no database file is written for a build that was never going to succeed. Only
    the steps that genuinely need an open store stay below that line.

    **It owns the resources it opens.** The four connection-owning stores are
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
            lifetime the runner enforces (``confirmation_ttl``, #310), the four
            permission gate thresholds the policy is constructed with (#239), and
            the observer's route and its two per-call bounds (``observer_model``,
            ``observation_batch_size``, ``observation_max_proposals``; ADR-0077),
            the calendar source and ADR-0093 §7a's eight figures bounding a read of
            it (``calendar_reader_path`` and friends; unset by default, in which
            case no reader is built), the data directory (``data_dir``) and the
            shutdown drain budget the façade is handed
            (``shutdown_drain_seconds``; ADR-0083 §2, §4).
        data_dir: Where the SQLite stores live, **overriding**
            ``settings.data_dir`` when given. It keeps its keyword rather than
            being folded into the setting (ADR-0083 §2): it is the injection seam
            every existing test uses, and the hub passes the directory it already
            resolved and locked in §3's step 2 so that one resolution is shared
            rather than performed twice. Created if absent.

    **The ``grants`` parameter is gone** (ADR-0102 §7), and removing it rather than
    defaulting it is the point. It was a ``SourceGrants | None = None`` whose one
    production caller — the hub — never filled it, so no deployment could record a
    grant, no deployment read its configured calendar, and leg 6's exit test was
    reachable by a test with an injected fake and not by a user. That is exactly
    the state #684 exists to record, and a default that silently wires nothing is
    how a configured reader came to be unreachable without anything failing. After
    this an engine either has a grant store or does not build.

    **#684's third checkbox reads otherwise and is superseded**, for two reasons
    the issue predates. It assigns the wiring to "``build_engine``'s caller — the
    hub, and the CLI through it"; the CLI is no longer a caller at all, since
    ``_open_engine`` returns a ``HubEngineClient`` and ADR-0084 §6's
    ``interfaces -> app`` contract makes building an engine there a build failure.
    And every other Tier 1 store in this system is opened here, so putting the
    sixth somewhere else would be a second wiring convention bought for nothing.

    Returns:
        A ready :class:`Engine`. Drive it with ``converse``/``resume`` and close
        it with ``aclose`` when the session ends.

    Raises:
        ConfigurationError: If the data directory cannot be prepared — blocked by
            permissions, or a file occupies its path. Converted from the raw
            ``OSError`` so an adapter's ``AssistantError`` boundary surfaces it
            rather than letting it escape as a traceback. Or if a configured model
            spec names a vendor pydantic-ai does not know or whose optional package
            is not installed — the router's specs (ADR-0062 §2, see
            :func:`_build_model_provider`) and the observer's own route alike
            (ADR-0077 §3, see :func:`_build_observer_provider`). Or if
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
    # The observer's route, built here and separately: it is one route and it never
    # falls back (ADR-0077 §3). Above the data directory with the rest, so an
    # observer spec naming an uninstalled vendor fails the build rather than the
    # first observation.
    observer_route = _observer_spec(settings)
    observer_model = _build_observer_provider(settings, observer_route)
    # The read-only sources, if this deployment configured one (ADR-0093 §7).
    # **Two reader instances rather than one**, and ADR-0096 §5 decides it here
    # rather than
    # leaving the composition lane to pick by accident: ADR-0093 §7 bounds a reader
    # at one outstanding worker *per instance*, so a shared reader would let a
    # scheduled ingestion read suppress the request-path facet for as long as it
    # runs — coupling a request cadence to a periodic job, in the direction that
    # makes an advisory facet wait on it. Two instances cost two workers at most,
    # which is still bounded, and each consumer then owns its own failure.
    #
    # Both are built above the data directory, and they belong there for #372's
    # reason rather than by association: constructing a reader opens nothing — it
    # validates §7a's figures and names a daemon thread it has not started — so a
    # calendar window or cap outside its range fails the build before any store is
    # written.
    facet_reader = _build_calendar_reader(settings)
    ingestion_reader = _build_calendar_reader(settings)
    # The temporal core is built here, above the data directory, because it is what
    # *validates*: a non-conforming zone or a working-hours pair fails the build
    # before disk is touched (#372). The ``AssemblingContextProvider`` around it is
    # assembled below instead, and that is a change ADR-0102 §7 forces rather than a
    # preference — the calendar facet is gated on a ``SourceGrants`` (ADR-0097 §5)
    # and the object answering that seam is the grant store, which is a resource and
    # therefore opens below. The provider's own constructor validates nothing, so
    # nothing #372 protects moves with it.
    clock_source = ClockContextSource(
        timezone=settings.timezone,
        working_hours_start=settings.working_hours_start,
        working_hours_end=settings.working_hours_end,
    )
    # Construct the embedder here too — above the data directory — so a missing or
    # unbuildable model fails as a ConfigurationError before any disk is touched
    # (ADR-0006 §2 default, #372's above-disk contract; see :func:`_build_embedder`).
    embedder = _build_embedder(settings)
    # The keyword still wins over the setting when it is given (ADR-0083 §2), so
    # every existing caller — and the hub, handing over the directory it resolved
    # and locked before any store was opened — keeps its injection seam. What
    # changed is only where the *default* comes from: ``Settings.data_dir``,
    # whose factory produces the very ``~/.ai-assistant`` this module resolved
    # privately before, so nothing moves for a deployment that configures nothing.
    directory = data_dir if data_dir is not None else settings.data_dir
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
        # The conversation index (ADR-0074 §9). Both durations come from settings and
        # are the *user's* configuration, not the contract's: ``episode_retention``
        # defaults to a finite horizon (§7 is emphatic that an unbounded default would
        # ship an ever-growing Tier 1 log of everything the user has ever typed), and
        # ``conversation_tombstone_grace`` is positive and finite with no ``None``
        # spelling (§8), both refused at load rather than per sweep.
        conversations = SqliteConversationStore(
            path=directory / "conversations.db",
            retention=settings.episode_retention,
            tombstone_grace=settings.conversation_tombstone_grace,
        )
        opened.append(conversations.close)
        # The deferred-question queue (ADR-0078 §2). A **fourth** connection-owning
        # Tier 1 store, under the same data directory and the same owner-only file
        # mode, because what it holds is the user's own words waiting on an answer.
        #
        # Both tunings are the *user's* configuration and both reach the
        # constructor, where they are validated once and read once: the lifetime is
        # stamped onto each question at admission, so a later change to the setting
        # cannot reach back and shorten a question already asked (§2), and the cap is
        # strictly positive because a cap of zero would refuse every question while
        # the system reported health (§7, ADR-0022 §4a).
        #
        # **The claim-token source is deliberately not passed.** Its default is a
        # ``secrets``-backed draw, and that default is the guarantee: ``interrupted``
        # publishes every claimed question's id to any caller, so a predictable token
        # is one a reader can guess and spend. Wiring anything here — even something
        # that looks random — is how "unpredictable" becomes a word in an ADR
        # (§2, §10 item 4), which is why a test asserts the built store carries the
        # default rather than trusting this comment.
        deferrals = SqliteDeferralStore(
            path=directory / "deferrals.db",
            retention=settings.deferral_ttl,
            queue_limit=settings.deferral_queue_limit,
        )
        opened.append(deferrals.close)
        # The **sixth** connection-owning Tier 1 store (ADR-0102 §7), under the same
        # data directory and the same owner-only file mode as the other five,
        # because what it holds is the record of what the user permitted. ADR-0083
        # ruling 4's exclusivity needs nothing new for it: it lives inside the
        # directory the instance lock already covers, is opened by the same process,
        # and is closed in the same ordered shutdown.
        #
        # **One object, passed twice** (ADR-0097 §3, ADR-0102 §7): as a
        # ``SourceGrantStore`` to the grant operations, and as a ``SourceGrants`` to
        # every driver. Structural typing is what makes that sound, and the
        # narrowing is the *annotation on the driver's constructor* rather than
        # anything done here — "what the driver cannot do is *name* ``record``".
        grants = SqliteSourceGrantStore(path=directory / "grants.db")
        opened.append(grants.close)

        # The context provider, assembled now that the grant seam exists. Its
        # calendar facet is registered only when a source is configured — a source
        # with nothing to read would be I/O on personal data in exchange for nothing
        # (ADR-0093 §7a). It carries no `required` marker, so a reader fault, a
        # store fault or a withdrawn grant each degrade the facet and leave the rest
        # of the context assembled (ADR-0008 §4, ADR-0026 §4).
        context = AssemblingContextProvider(
            [
                clock_source,
                *(
                    []
                    if facet_reader is None
                    else [CalendarContextSource(reader=facet_reader, grants=grants)]
                ),
            ]
        )

        # One object as both the selecting registry and the acting invoker
        # (ADR-0029 §8). Populated with the first local tools (ADR-0048); the
        # memory-backed `recall_memory` reads the *same* store the loop retrieves
        # from, so a recall sees what the user's memory holds.
        tools = build_default_registry(memory=memory)

        # The writer persists to the *same* store the loop retrieves from (ADR-0028 §4).
        writer = MemoryIngestor(store=memory, policy=DefaultMemoryPolicy())
        # **One** write stage, over that writer and that deferral queue, shared by
        # every producer's stage (ADR-0078 §3). Two of the three composition-root
        # obligations are discharged by this single object existing: the queue the
        # write stage enqueues into is the same instance the question surface
        # enumerates from — a second one would queue questions nobody can answer —
        # and the writer an answer applies through writes to the same `MemoryStore`
        # whose records a question's frozen conflict set names, which is ADR-0028
        # §4's same-store rule reaching a second place. The third (that the answer
        # path is the only producer of a `UserConfirmation`) is structural rather
        # than wiring, and a structural test holds it.
        writes = MemoryWriteStage(writer=writer, deferrals=deferrals)
        loop = LearningLoop(
            context=context,
            memory=memory,
            # The write stage, not a `MemoryWriter` of the loop's own: a producer's
            # stage holding the writer directly gets the ratified policy and applier
            # and silently loses the queue, which is the drop ADR-0078 ends.
            writes=writes,
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
            # The same store the loop retrieves from and the writer persists to, so
            # the inspection surface lists the beliefs the assistant actually uses
            # and ``forget`` destroys what the user was shown (ADR-0073 §7).
            memory=memory,
            # The very queue `writes` enqueues into and `questions` below answers
            # from, so the retention sweep (ADR-0083 §7) reclaims the rows the
            # user's own questions live in. A second queue here would report a cap
            # kept over rows nobody can see (ADR-0078 §1, §10 item 8).
            deferrals=deferrals,
            # The capture/lifecycle stage, holding *both* durable stores — the same
            # `memory` again, so a captured turn is retrievable and destroyable
            # through the surfaces the user already has (ADR-0074 §9). Its
            # ``retention`` is the very value the conversation store was built with,
            # so an episode's stamped `expires_at` and the reclaim of the index that
            # names it are judged against one horizon and not two (§7).
            conversations=ConversationLifecycle(
                conversations=conversations,
                memory=memory,
                retention=settings.episode_retention,
            ),
            # The observation stage (ADR-0077 §8), over the *same* memory store and
            # the *same* writer the learn leg uses, so an observed belief is
            # retrievable, inspectable and forgettable through the surfaces the user
            # already has — and so a proposal's citations resolve against the store
            # its episodes were selected from (ADR-0028 §4's obligation, applied to a
            # second producer). One ``Settings`` value bounds both the selection and
            # the producer, which is what keeps the stage's batch inside the bound
            # the producer refuses beyond (ADR-0077 §1, §9.7).
            observation=ObservationStage(
                observer=ModelBackedObserver(
                    observer_model,
                    max_batch_size=settings.observation_batch_size,
                    max_proposals=settings.observation_max_proposals,
                ),
                conversations=conversations,
                memory=memory,
                # The same write stage the learn leg uses, so an observed proposal
                # the policy defers parks a question the user can answer rather than
                # being reported to a stage nobody is watching and dropped.
                writes=writes,
                batch_size=settings.observation_batch_size,
                route=observer_route,
            ),
            # The answer path (ADR-0078 §8, §9), over the *same* deferral queue the
            # write stage above enqueues into, the *same* writer an ordinary `learn`
            # applies through, and the *same* memory store — so a question the user
            # is shown resolves its conflicts against the records an answer to it
            # would actually retire.
            questions=QuestionStage(writer=writer, deferrals=deferrals, memory=memory),
            # Leg 6's ingestion stage (ADR-0093 §6), over the *same* write stage
            # the learn leg and the observation stage use — ADR-0078 §3's one
            # obligation reaching a third producer, so an attested proposal the
            # policy defers parks a question the user can answer and one it stores
            # is inspectable and forgettable through the surfaces that already
            # exist (ADR-0028 §4).
            #
            # **`None` when no source is configured, which is the default** (§7).
            # A reader ships disabled because "nothing may read a user's personal
            # files because a default said so", so the ordinary deployment builds
            # no stage at all and `Engine.ingest` refuses rather than reporting an
            # empty success. Nothing calls it in that state anyway: the scheduler
            # arms the job only on a configured interval, and `Settings` refuses an
            # interval whose path is unset (§7a).
            #
            # **Wired on the path, never on the interval.** The path configures
            # the source and the interval arms the cadence, so ADR-0093 §7a's
            # facet-only state is one where the stage exists and no job is armed.
            # It is no longer *also* conditional on a grant seam: ADR-0097 §5 makes
            # a `SourceGrants` a required constructor argument and §9 puts the only
            # holder of a store in the hub's grant operations, which had not been
            # built — so `grants` was `None` in every deployment and no source was
            # read at all (#684). ADR-0102 §7 opens the store here, so the seam is
            # always present and only the *grant* decides whether anything is read.
            # §8's consequence stands unchanged and is now the user's to answer:
            # "An installation that has been reading a source stops reading it
            # until the user grants."
            #
            # Its **own** reader, never the one the context source holds
            # (ADR-0096 §5).
            ingestion=(
                None
                if ingestion_reader is None
                else IngestionStage(reader=ingestion_reader, writes=writes, grants=grants)
            ),
            # The four grant operations (ADR-0102 §1, §7), over the *same* store
            # passed to the drivers above — a second store would let a user grant a
            # source the gate then read a different answer about.
            #
            # **The identities and locations come from the reader objects this
            # function built**, each read off the object rather than re-derived from
            # a setting, which is §7's clause and is what keeps `orchestration` from
            # having to know what a calendar is. A *sequence* rather than a mapping:
            # §7 rules that two readers declaring one identity at differing
            # locations is a configuration error the engine does not build through,
            # and a mapping would deduplicate that conflict away unseen. The two
            # instances this function builds agree by construction — both come from
            # `calendar_reader_path` — which is exactly why the refusal has to be
            # expressed rather than assumed.
            grant_operations=GrantOperations(
                store=grants,
                sources=[
                    HeldSource(reader.name, location=_configured_location(settings))
                    for reader in (facet_reader, ingestion_reader)
                    if reader is not None
                ],
                id_factory=_uuid,
                clock=_utcnow,
            ),
            closers=[
                _as_async(memory.close),
                _as_async(trail.close),
                _as_async(plans.close),
                _as_async(conversations.close),
                # The deferral queue joins the façade's ordered shutdown (ADR-0042
                # §2, ADR-0078 §10 item 5).
                #
                # **Its `purge` is wired exactly where `purge_expired` is, and at
                # the same time** (ADR-0078 §10 item 8): "it does not get a new
                # one… this store's purge is wired wherever `purge_expired` is
                # wired and inherits the same fate. Inventing a second sweeping
                # mechanism for one store would be the thing that has to be undone
                # at leg 5." Leg 5 is here: both are called by `Engine.purge_expired`
                # as **one** operation, run by the hub's scheduler on one interval
                # (ADR-0083 §7, §8). Nothing in this file schedules anything —
                # cadence is a property of a deployment, not of the wiring, which is
                # why the scheduler is a peer above this layer and not inside it.
                #
                # Correctness never depended on either sweep running; ADR-0078 §1's
                # exposure cap did, and that is what has now been bought.
                _as_async(deferrals.close),
                # The grant store joins the same ordered shutdown as the other five
                # (ADR-0083 ruling 4, ADR-0102 §7).
                _as_async(grants.close),
            ],
            # The shutdown budget every production engine gets, hub and CLI alike
            # (ADR-0083 §4). It belongs here rather than on the ``Engine`` default
            # because it is a *deployment* value, and this is the layer that reads
            # deployment values: an ``Engine`` a test builds directly keeps the
            # unbounded drain it always had.
            drain_timeout=settings.shutdown_drain_seconds,
            # The contract limit ADR-0085 §8c declares — ``hub_max_frame_bytes``
            # less §8b's 512-byte envelope reserve — passed from the deployment's
            # own setting rather than left to the constructor's default (#572).
            #
            # **The setting is what makes the two implementations agree**, which is
            # the whole of ADR-0084 §4: the limit is a clause of the contract that
            # every implementation enforces, and the client is told the hub's
            # effective frame size in the handshake and "enforces the number it was
            # told". If this layer did not subtract the reserve from the *same*
            # field the listener publishes, a deployment that raised
            # ``hub_max_frame_bytes`` would move the client's limit and not the
            # engine's — and the engine would accept a value the client provably
            # cannot send, which is the divergence §4 moved the limit into the
            # contract to prevent.
            #
            # The reserve is taken from ``orchestration.payloads`` rather than from
            # ``wire``: it is the same 512 bytes either way (ADR-0087 §7 — the two
            # encoders are byte-identical or the vectors fail), and reading it
            # beside the engine that will measure with it adds no package edge here.
            max_payload_bytes=settings.hub_max_frame_bytes - ENVELOPE_RESERVE_BYTES,
        )
    except BaseException:
        # Close anything already opened before re-raising, so a failed build
        # returns no orphaned connection (ADR-0042 §2). Reverse order: last opened,
        # first closed.
        for close in reversed(opened):
            close()
        raise


def ensure_model_credentials(settings: Settings) -> None:
    """Fail now if any configured route holds no credential (issue #530).

    **Deliberately not part of :func:`build_engine`, and that is the decision
    rather than a detail.** For a one-shot CLI the present behaviour is right and
    #530 says so in as many words: the failure lands on the command that needed a
    credential, and the commands that did not — ``beliefs``, ``learn``,
    ``questions``, ``answer``, ``forget``, none of which touch a model — are not
    blocked by its absence. Folding this into ``build_engine`` would make every
    one of them start failing without a key: a regression introduced by a fix, for
    a defect the CLI does not have.

    What changed is the **process model**. ADR-0083 §3 signals readiness last and
    §5/§6 make a fault nothing can clear a stay-down exit, on the ruling that "if
    the hub is not running, there is a reason, and the reason is legible". A
    resident hub with no credential starts, signals ready, looks healthy to every
    supervisor and monitor, and then fails on a user's first real request hours
    later on a box nobody is watching — the exact inverse of the legibility §6
    establishes. So the *hub* asks this question at startup, and nothing else
    does.

    It lives here because the answer is only reachable from ``models`` (golden
    rule 4 confines the provider SDK there) and ADR-0083 §8 lets ``service``
    import ``app`` and ``core`` but no subsystem. This is the composition root
    doing what it already does for the vendor check: asking ``models`` the one
    question only ``models`` can answer.

    **Presence, never validity.** It performs no completion and no round trip, so
    ADR-0083 §3's "nothing in startup may block indefinitely on a network" holds
    and a supervisor's start timeout keeps its meaning. A key that is present but
    revoked or throttled still fails at request time, classified there as the
    model error it is.

    Every route is checked — the router's whole preference order *and* the
    observer's own — because ADR-0077 §3 gives the observer a route that never
    falls back, so a credential it lacks disables observation silently rather
    than being covered by a sibling. Duplicates are checked once; the observer's
    spec defaults to ``default_model``, and repeating the probe would only repeat
    the message.

    Args:
        settings: Loaded application settings — the router's preference order and
            the observer's route.

    Raises:
        ConfigurationError: If a spec names a vendor whose package is missing or
            unknown, or one for which this deployment holds no credential. One
            class for both, which is what lets the hub map every startup
            misconfiguration to a single exit code through one type check
            (ADR-0083 §5).
    """
    for spec in dict.fromkeys((*_model_specs(settings), _observer_spec(settings))):
        # In this order: the vendor check owns the "package not installed" message
        # and names the extra to install, and the credential probe presumes the
        # vendor resolved. Repeating a check `build_engine` also runs is cheap and
        # deliberate — the same reasoning `_build_observer_provider` records for
        # re-checking a spec that may equal `default_model`.
        ensure_vendor_available(spec)
        ensure_credential_available(spec)


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


def _observer_spec(settings: Settings) -> str:
    """The one ``"provider:model"`` spec the observer reads episodes through (ADR-0077 §3).

    ``observer_model`` when the operator named one; otherwise ``default_model`` —
    **the route already configured for conversation**, and deliberately not the
    whole ``fallback_models`` preference order, because this route never falls back
    (:func:`_build_observer_provider`).

    That default is what makes the setting cost nothing to have: it names no
    provider the operator did not already configure, so ADR-0004 §2's property —
    user data reaches only providers the user explicitly configured — cannot be
    breached by leaving it unset. What the setting buys is that the choice is
    *nameable and separable*: an operator who wants the episodic stream read by a
    smaller, cheaper or locally-hosted model changes one value and does not touch
    the route their answers come from.

    Args:
        settings: Loaded application settings.

    Returns:
        The spec, never empty: ``default_model`` stands behind it.
    """
    return (
        settings.observer_model if settings.observer_model is not None else settings.default_model
    )


def _build_observer_provider(settings: Settings, spec: str) -> RetryingProvider:
    """Build the observer's model seam: **retry, and no routing at all** (ADR-0077 §3).

    The deliberate difference from :func:`_build_model_provider`, and the whole of
    ADR-0077 §3's second part: **an observation's failure is never re-sent to a
    second provider.** ADR-0013 §4 already rules the mechanism — "a caller who names
    a model has already chosen" — and here its own Consequences decide the case:

    * fallback's cost is that *more providers may see a given prompt*, which for a
      turn buys an answer the user is waiting for. An observation buys nothing with
      it, because observation is **deferrable**: the episodes are durable, nothing
      is waiting, and the free remedy is to run again.
    * it is the one payload where the trade inverts. A turn's prompt is one
      utterance; an observation's prompt is accumulated history, so widening the set
      of recipients for reliability is exactly what ADR-0004 §7's minimisation rule
      argues against when the reliability buys nothing.

    So the observer is handed a :class:`RetryingProvider` and not a
    :class:`RoutingProvider` — there is no second candidate for a routable failure
    to advance to, rather than a router that happens to hold one route. **Retry is
    not fallback**: it re-sends to the *same* provider, so it widens no recipient
    set, and dropping it would make the observer less resilient than every other
    call for no privacy gain.

    The route **requires its own credential** (ADR-0013 §6), which follows from the
    same shape: nothing stands behind it, so a provider the deployment cannot
    authenticate to fails the observation rather than quietly diverting the
    transcript somewhere it can.

    Args:
        settings: Loaded application settings — the resilience knobs the retry
            wrapper is built from, the same ones every other route gets, because how
            patient this deployment is is not a property of which vendor answered.
        spec: The observer's ``"provider:model"`` spec (:func:`_observer_spec`).

    Returns:
        The provider the observer reads episodes through.

    Raises:
        ConfigurationError: If ``spec`` names a vendor unknown to pydantic-ai or
            whose optional package is not installed — checked here for the reason
            ADR-0062 §2 gives, so an operator learns at startup rather than on the
            first observation. It is checked even when it repeats ``default_model``:
            the check is cheap, and a helper that trusted a caller to have checked
            already would break the day the two stop coinciding.
    """
    ensure_vendor_available(spec)
    return RetryingProvider(PydanticAIProvider(spec), policy=RetryPolicy.from_settings(settings))


def _build_calendar_reader(settings: Settings) -> CalendarReader | None:
    """Construct the configured calendar reader, or ``None`` if there is no source.

    **This function is why the composition root may import
    ``ai_assistant.readers`` at all.** ``lint-imports`` forbids that package to
    every subsystem — ADR-0093 §2's "no subsystem may import it", which ADR-0095
    §3 leans on to keep the ``Reader`` Protocol in ``core`` — and deliberately
    omits ``app``, on the ground the contract states in its own comment: listing
    the composition root "would make ``readers`` unreachable in production for
    good: no other package may import it, so nothing could ever construct a
    ``CalendarReader`` to inject". It is the same carve-out the provider-SDK
    contract states for ``models``, and this is the injection golden rule 1 puts
    here — ``orchestration`` receives a ``Reader`` it may not name.

    **``None`` is the shipping default and it is a consent decision, not a
    technical one** (ADR-0093 §7): "Every reader ships **disabled by default**,
    and the reason is that nothing may read a user's personal files because a
    default said so — not that anything technical is missing." Naming the reason
    is what stops the default flipping the day the technical obstacle clears, and
    it places the default correctly relative to the grant question §11 defers — a
    fresh install that read a calendar unasked would be making that grant decision
    by omission, which is the one way it must not be made. A ``Settings`` field is
    **not** a grant either (§7's last clause), which is why leg 6's exit test
    stays open and #629 tracks it.

    Every figure comes from ``Settings``, where ADR-0093 §7a's ranges are already
    refused at load; the constructor states them again because it is a second seam
    a test or a second composition root reaches directly, and §5 puts the refusal
    at construction rather than at the first run.

    The **timezone is the one ``Settings.timezone``** ADR-0008 §5 gives the
    temporal context, passed rather than re-derived: "A reader may not invent a
    second timezone source", because two components resolving "today" against
    different zones is the class of defect ADR-0026 exists to prevent, arriving
    through data rather than through a clock.

    The clock is left at the reader's own default. ADR-0026 governs *reading* it,
    and the reader guards what it was given (``checked_clock``); nothing here has
    a second clock to hand it, and inventing one would be the second source this
    layer just refused for the zone.

    Args:
        settings: Loaded application settings — the source path and ADR-0093 §7a's
            eight figures.

    Returns:
        The reader, or ``None`` when ``calendar_reader_path`` is unset.

    Raises:
        ValueError: If a figure is outside its range or the path is not absolute.
            Unreachable through ``Settings``, which refuses both at load; it is
            the constructor's own guard on the seam a caller could reach directly.
    """
    if settings.calendar_reader_path is None:
        return None
    return CalendarReader(
        settings.calendar_reader_path,
        timezone=settings.timezone,
        window_past=settings.calendar_window_past,
        window_future=settings.calendar_window_future,
        max_entries=settings.calendar_max_entries,
        max_bytes=settings.calendar_max_bytes,
        max_expansion=settings.calendar_max_expansion,
        read_timeout=settings.calendar_read_timeout,
        max_content_bytes=settings.calendar_max_content_bytes,
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
    no arbitrary-model path — so this is a mode switch, not a model resolver, and
    the switch is **exhaustive**: a member with no branch is refused rather than
    quietly built as the default (#737).

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
    if settings.embedder is not EmbedderKind.ON_DEVICE:
        # **Exhaustive, with no fall-through to the default, and the check is
        # static.** A member with no branch used to land here and be built as the
        # on-device model — silent, and wrong in the one direction that matters:
        # `settings.embedder` is privacy-relevant surface now that ADR-0104 §4
        # refuses an off-device target unless the operator authorises the
        # whole-store egress, so an authorised selection quietly substituted for a
        # different embedder would report one recipient and use another. With both
        # members branched above, `mypy` narrows this to `Never`, so **adding a
        # member without a branch is a gate failure rather than a runtime
        # surprise** (#737). The call is the runtime backstop for a `Settings`
        # built past pydantic's own validation, which is a programming error and
        # is signalled as one.
        assert_never(settings.embedder)

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


def _uuid() -> str:
    """Mint one opaque, random id for a grant record (ADR-0021 §3, ADR-0102 §5).

    A store neither mints ids nor reads a clock, so the factory arrives by
    injection — and it is the *composition root* that supplies it rather than a
    client, because a client minting into a write-once store is one of the three
    grounds ADR-0102 §5 rejects "the client constructs and sends a whole
    ``SourceGrant``" on.
    """
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    """Read the instant a grant record is stamped with (ADR-0102 §5).

    Injected for the same reason and one sharper: a client's clock would backdate a
    user act in a store whose entire value (ADR-0097 §4) is that it says what
    actually happened. ``SourceGrant.decided_at`` is a ``UtcInstant``, so the
    reading is validated timezone-aware UTC at construction.
    """
    return datetime.now(UTC)


def _configured_location(settings: Settings) -> str | None:
    """Where this deployment configured its one source to read from (ADR-0102 §6).

    A plain ``str`` and not a ``Path``, because §6's hazard is precisely a pathname
    with no UTF-8 encoding: Linux pathnames are bytes and Python surfaces an
    undecodable one through ``surrogateescape``, so ``str(path)`` can hold a lone
    surrogate. The string is what has to be judged, and judging it is the grant
    operations' job rather than this layer's — here it is only read.

    **One source, and the day there is a second this stops being a function of
    ``Settings`` alone.** ADR-0093 §11's registry lane is where a location becomes a
    property of a registered source rather than of a named field, and ADR-0102 §10's
    normative clause already owes that lane a re-derivation of the enumeration's
    worst case.
    """
    if settings.calendar_reader_path is None:
        return None
    return str(settings.calendar_reader_path)


def _as_async(close: Callable[[], None]) -> Callable[[], Awaitable[None]]:
    """Adapt a synchronous ``close()`` to the façade's async shutdown-path shape."""

    async def _aclose() -> None:
        close()

    return _aclose


#: The :class:`EmbedderKind` members that embed on the user's own machine
#: (ADR-0104 §4). **Enumerated by name, and fail-closed**: a member absent from
#: this set is refused by :func:`build_reembedder` unless the operator explicitly
#: authorises the egress, so a cloud embedder added later is refused until
#: somebody puts it here deliberately. That is the point of a list rather than a
#: predicate — a predicate on the ``Embedder`` would need new contract surface
#: (golden rule 5) and would put the answer in the implementer's hands rather than
#: the decision's, and `memory/` receives an ``Embedder`` and cannot tell where it
#: runs. Both members are on-device today: ADR-0024's vendored ONNX model, and the
#: dependency-free ``HashingEmbedder``.
_ON_DEVICE_EMBEDDERS: Final = frozenset({EmbedderKind.ON_DEVICE, EmbedderKind.HASHING})


def build_reembedder(
    settings: Settings,
    *,
    data_dir: Path | None = None,
    upload_entire_memory_store: bool = False,
) -> Reembedder:
    """Wire the configured embedder to the memory store's re-embedding migration.

    The composition root's second function, and it is here for the reason the
    first one is: it names two concretes — the ``Embedder`` from ``models/`` and
    the ``Reembedder`` from ``memory/`` — and nothing else in the tree may name
    both. The offline tool that calls it lives in ``ai_assistant/service/`` and
    imports no subsystem, which ADR-0083 §8 requires and ADR-0104 §5 records.

    **This is where the cloud refusal lives** (ADR-0104 §4). The decision is about
    *which embedder the operator chose*, which is a configuration fact this layer
    holds and the store does not: ``memory/`` receives an ``Embedder`` and cannot
    tell whether it reaches the network. So the check is on
    :attr:`Settings.embedder` against :data:`_ON_DEVICE_EMBEDDERS`, and it is
    fail-closed — an unrecognised member is refused, not waved through.

    The embedder is constructed **before** the store path is touched, matching
    :func:`build_engine`'s above-disk contract (#372): an unbuildable on-device
    model is a ``ConfigurationError`` before anything on disk is inspected.

    Args:
        settings: Loaded application settings — ``embedder`` selects the target
            embedding space and ``data_dir`` locates the store.
        data_dir: Overrides ``settings.data_dir`` when given, exactly as
            :func:`build_engine`'s keyword does (ADR-0083 §2).
        upload_entire_memory_store: The operator's explicit authorisation for a
            target that is not on-device. Named for the act rather than the
            mechanism, because what is being consented to is the size of the
            egress and not the topology.

    Returns:
        A migration ready to :meth:`~ai_assistant.memory.reembed.Reembedder.plan`
        or run against ``<data_dir>/memory.db``.

    Raises:
        ConfigurationError: If the configured embedder is not on-device and
            ``upload_entire_memory_store`` is false, or if the embedder itself
            cannot be constructed.
    """
    if settings.embedder not in _ON_DEVICE_EMBEDDERS and not upload_entire_memory_store:
        msg = (
            f"the configured embedder {settings.embedder.value!r} does not run on this "
            f"machine, so re-embedding would upload every record in the memory store to "
            f"its operator. Configuring it is not by itself consent to send the "
            f"accumulated store: pass --upload-entire-memory-store to authorise that, or "
            f"set ASSISTANT_EMBEDDER to an on-device option"
        )
        raise ConfigurationError(msg)
    embedder = _build_embedder(settings)
    directory = data_dir if data_dir is not None else settings.data_dir
    return Reembedder(store=directory / "memory.db", embedder=embedder)
