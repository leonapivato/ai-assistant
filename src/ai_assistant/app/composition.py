"""Construct the production subsystems and wire them into an engine (ADR-0042 §2).

:func:`build_composition` is the composition root's one build. It names every
concrete implementation, discharges the wiring obligations no type can express,
owns the connection-owning resources it opens, and hands the façade an ordered
shutdown path — everything ADR-0042 §2 requires of this layer.

:func:`build_engine` is that build read down to its engine, and it stays the
entry point for every caller that needs nothing else. What the second return
value exists for is ADR-0119 §9's startup stamp: the configuration trace records
the **effective** ``search`` limit of each cardinality control, and §9 is explicit
that "the figure to record is the one the composition root actually produced" —
because neither control is a ``Settings`` field, so "a ``Settings`` dump would
show neither". :class:`Composition` is that figure leaving the one layer that
knows it, beside the ``TraceSink`` the stamp writes through.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final, assert_never

from ai_assistant.context import (
    AssemblingContextProvider,
    CalendarContextSource,
    ClockContextSource,
    EmailContextSource,
)
from ai_assistant.core.config import EmbedderKind
from ai_assistant.core.errors import ConfigurationError, ModelError
from ai_assistant.core.types import DELIVERY_RESERVE_BYTES, SecretScope
from ai_assistant.evaluation import MeasureReader, SqliteTraceStore
from ai_assistant.learning import ModelBackedObserver, RuleBasedFeedbackProcessor
from ai_assistant.memory import (
    DefaultMemoryPolicy,
    DefaultNotificationPolicy,
    MemoryIngestor,
    ModelBackedReconciler,
    SqliteDeferralStore,
    SqliteMemoryStore,
    SqliteNotificationOutbox,
    SqliteNotificationStore,
)
from ai_assistant.memory.conversation_store import SqliteConversationStore
from ai_assistant.memory.health import DEFAULT_K, DEFAULT_SAMPLE, MAX_K, StoreHealthReader
from ai_assistant.memory.notification_store import check_notification_tuning
from ai_assistant.memory.reembed import Reembedder
from ai_assistant.models import (
    BoundedEmbedder,
    BoundedSpeechSynthesizer,
    BoundedSpeechTranscriber,
    HashingEmbedder,
    PydanticAIProvider,
    PydanticAIStreamingCompleter,
    RetryingProvider,
    Route,
    RoutingProvider,
    ensure_credential_available,
    ensure_vendor_available,
)
from ai_assistant.models.retry import RetryPolicy
from ai_assistant.orchestration import (
    ComposingStage,
    ConnectionOperations,
    ConsolidationStage,
    ConversationLifecycle,
    Engine,
    GrantOperations,
    HeldSource,
    IngestionStage,
    LearningLoop,
    MemoryWriteStage,
    NotificationWriteStage,
    ObservationStage,
    QuestionStage,
    RecoveryScan,
    RoutingStage,
    StepExecutor,
    StepRunner,
    UpcomingEventStage,
)
from ai_assistant.orchestration.payloads import ENVELOPE_RESERVE_BYTES
from ai_assistant.permissions import (
    SqliteAuditTrail,
    SqliteRecipientGrantStore,
    SqliteRoutingTrail,
    SqliteSourceGrantStore,
    SqliteSourceReadTrail,
    ThresholdActionPolicy,
)
from ai_assistant.permissions.spend import SpendConfiguration
from ai_assistant.planning import ModelBackedPlanner, SqlitePlanStore
from ai_assistant.readers import CalendarReader, EmailReader
from ai_assistant.secret_store import KeyringSecretStore
from ai_assistant.tools import (
    build_default_registry,
    build_send_email_integration,
    egress_registrations,
)
from ai_assistant.tools.connection_store import SqliteConnectionStore
from ai_assistant.tools.egress import StreamOutboundTransport
from ai_assistant.tools.egress_binder import EgressBindingSeam
from ai_assistant.tools.provisioning import KeyringConnectionProvisioner

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Sequence
    from pathlib import Path

    from ai_assistant.core.config import Settings
    from ai_assistant.core.protocols import (
        ConnectionPurger,
        Embedder,
        OutboundTransport,
        Reader,
        Secrets,
        SpeechSynthesizer,
        SpeechTranscriber,
        TraceSink,
    )


#: What this layer tunes :class:`LearningLoop`'s retrieval to, and **passed
#: explicitly rather than left to the constructor's default** (ADR-0119 §9).
#:
#: The value is the one ``orchestration`` already defaults to, so nothing about a
#: deployment moves. What moves is *where the figure is decided*: §9 has the
#: configuration stamp record "the **effective** ``search`` limit that control
#: produces at the seam", and the honest figure is the one the composition root
#: produced, not one this module re-states from memory beside a default it does
#: not control. Passing it makes the two the same object of knowledge — a stamp
#: reading this constant is reading exactly what the loop was built with, and a
#: later change to ``orchestration``'s own default cannot make the record wrong.
#:
#: **15 rather than 5, on measurement rather than taste** (#1163, #1029's scored
#: pilot re-rank analysis). Over the retrieval misses whose gold record was
#: *present in the store* — so a ranking failure, not an ingestion one — the
#: gold-citing record's median cosine rank was 12, and 114 of 277 sat at ranks
#: 6 to 10. A budget of 5 cut the answer off above almost all of them; 15 covers
#: about 80% of that population, and the deeper page is the cheapest lever there
#: is, because the records are already ranked and already in the store.
#:
#: **And 30 rather than 15, because complete intake removed the ceiling that made
#: depth in beliefs worthless** (ADR-0162 §9). ADR-0160 §1 took the episodic bound
#: to 15 on a correct reading of a store that no longer exists: the belief layer was
#: saturated at 63.1%, "the ceiling of what its distilled records cite at all", so
#: buying depth here bought nothing. Under ADR-0162 §1 the probe's belief-reach
#: curve runs 55.1% at 5 to 81.2% at 50 and is still climbing, where the control's
#: runs 31.2% to 38.8% and is flat by 15. On union all-gold-reached the probe swept
#: 15+15 79.8%, 20+10 80.9%, 20+20 83.3%, **30+10 85.1%**, 30+15 86.5%, 30+30 88.6%,
#: 50+10 88.4% — so 30+10 beats 20+20 at a comparable prompt size (~6.5k against
#: ~5.9k characters) and beats the incumbent 15+15 by 5.3 points at about 1.5 times the
#: context. Spending the marginal slot on the layer still returning new gold is
#: ADR-0160's own reasoning applied to the store its ruling helped create.
#:
#: **It is provisional in a stated way, which is a cost this constant carries**
#: (§9's third clause). Whatever the byte-budgeted single ranked pool ADR-0160 §5
#: leaves open decides replaces it, and pilot 5's post-hoc attribution (ADR-0160 §3)
#: re-tests it. No ratified clause fixed the old value — ADR-0160 §6 lists
#: "``RETRIEVAL_LIMIT`` stays 15" among what that ADR does *not* decide, in unmarked
#: text, which under ADR-0089 §3 supplies no obligation — so this is the same kind of
#: composition-root tuning move on the same kind of evidence.
#:
#: What it costs is answer context: 5 records filled roughly 4KB, so this is
#: about six times that in the prompt, per turn. That is the trade the
#: evidence buys, and it is bounded on both sides — ADR-0119 §3's
#: ``TRACE_RECORD_SET_CAP`` of 256 is still an order of magnitude away, so no
#: traced read moves nearer to truncating and §9's diagnostic keeps saying the
#: same thing about this deployment.
RETRIEVAL_LIMIT: Final = 30

#: How many episodes a turn's **supplementary** read may add to the answering
#: prompt (ADR-0158 §3), beside — never out of — :data:`RETRIEVAL_LIMIT`.
#:
#: A composition-root constant rather than a
#: :class:`~ai_assistant.core.config.Settings` field, and ADR-0158 §5 rules that
#: placement: the belief budget is a composition constant and this is the same kind
#: of thing, a cardinality control whose authority is measurement. The contrast
#: that decides it is ``episode_retention``, which *is* a setting because ADR-0074
#: §7 makes it a privacy choice the user owns. How many episodes help an answer is
#: not a preference; it is a fact nobody has measured, and offering it as a knob
#: would imply a user could know it.
#:
#: **10 against a belief budget of 30, and the two still never share.** ADR-0158 §3
#: gives the supplement a budget of its own precisely so that
#: :data:`RETRIEVAL_LIMIT`'s moves — bought for *beliefs*, on #1029's rank-miss
#: measurement and then on ADR-0162 §9's reach sweep — are not handed back to
#: episodes. What has changed is the evidence, not the separation: the bound began
#: at 5 as a judgement standing in for a measurement, ADR-0160 §1 replaced it with
#: one at 15 on a store where the belief layer was saturated, and ADR-0162 §9
#: replaces that in turn on a store where it is not.
#:
#: **Why 10 rather than 15, when 30+15 measures higher** (§9). The probe puts 30+15
#: at 86.5% against 30+10's 85.1% — 1.4 points for half again as much transcript in
#: every prompt, where an episode is a verbatim turn against a belief's distilled
#: sentence. ADR-0158 §5 left the byte bound open precisely because count is a weak
#: guard on volume and named the next scored run's ``context_chars`` as what decides
#: it, so the smaller number spends less of an unmeasured budget while the layer
#: demonstrably still returning gold gets the depth. It is also the reversible
#: direction: raising a bound on the pilot's evidence is one integer, and unwinding a
#: prompt that grew past a byte bound nobody has set is not.
#:
#: **Both numbers are provisional in a stated way** (§9's third clause) — the
#: byte-budgeted single ranked pool ADR-0160 §5 leaves open replaces them, and pilot
#: 5's post-hoc attribution (ADR-0160 §3) re-tests them. ADR-0160 §1's remaining
#: half stands and is relied on here: no separately registered ablation arm is owed
#: for the bound.
#:
#: **It may never exceed :data:`RETRIEVAL_LIMIT`**, which ``LearningLoop`` enforces
#: at construction rather than trusting this line. That ceiling is where ADR-0158
#: §3 puts the product thesis in checkable form: whatever the numbers become,
#: nobody can configure a system that asks for more transcript than belief. At 10
#: against 30 it is satisfied with slack again, so the coupling ADR-0160 §2 warned
#: about — that dropping belief depth would drag this bound down with it — is simply
#: not exercised. ADR-0160 §2's admission that parity *meets* the ceiling is
#: untouched and unneeded here.
EPISODIC_SUPPLEMENT_LIMIT: Final = 10

#: What this layer tunes :class:`MemoryIngestor`'s conflict ceiling to, passed
#: explicitly for :data:`RETRIEVAL_LIMIT`'s reason.
CONFLICT_LIMIT: Final = 100

#: How far the conflict probe over-asks its ceiling (ADR-0079 §1, ``memory/
#: ingest.py``'s ``limit=self._conflict_limit + 2``).
#:
#: **This is the whole reason ADR-0119 §9 records an effective limit and not a
#: control's own value.** §9: "A ``conflict_limit`` of 255 sits under the cap
#: while the probe it drives asks for 257, so a diagnostic keyed to the control
#: would say 'this deployment cannot truncate' of one that can."
#:
#: The arithmetic is duplicated from `memory` and cannot be imported: golden rule
#: 1 puts a subsystem's internals off limits, and the ingestor exposes no
#: effective-limit seam. ``tests/app`` pins the duplicate against the ingestor's
#: actual behaviour, so a drift fails a test rather than quietly misreporting the
#: figure an operator reads when truncated traces appear.
_CONFLICT_PROBE_OVERSHOOT: Final = 2

#: ADR-0144 §4's **preference sequence**: the ordered tool ids that break a tie
#: ADR-0144's ordering has reached key 6 on — that is, between candidates the
#: severity block and latency already found equal. It can promote nothing over a
#: candidate keys 1 through 5 prefer, and it is **configuration, never consent**
#: (§4): it grants nothing, authorises nothing, and whichever candidate it picks
#: is still ruled on against its own declaration by ``permissions`` before
#: anything runs.
#:
#: Empty by default, in which case key 6 ranks every candidate equally and a
#: genuine tie stays ``AMBIGUOUS_CAPABILITY``. It lives here rather than in
#: ``Settings`` because ADR-0144 §4 puts it at the composition root and §7 scopes
#: a *user-facing* preference out — that needs durable per-user policy state with
#: its own data-rights obligations, filed as #1101. Until then §5 names the
#: recovery in full and it runs through this line: an operator reads the tied ids
#: off the ``step_capability_ambiguous`` log record, names one here, **restarts**
#: — the snapshot is taken at construction and never re-read — and re-runs the
#: still-``PENDING`` step. An id naming no registered tool is permitted and
#: matches nothing; naming one twice is refused at construction.
TOOL_PREFERENCE: Final[tuple[str, ...]] = ()


@dataclass(frozen=True, slots=True)
class Composition:
    """The built engine, plus what only this layer knows (ADR-0119 §9).

    Returned by :func:`build_composition` and consumed by `service`, which stamps
    one ``CONFIGURATION`` trace per hub startup. Everything on it beyond the
    engine is there because the stamp cannot obtain it anywhere else: the sink is
    opened here, and the two cardinality figures are properties of *how this layer
    constructed two collaborators* rather than of any setting.

    **Narrow by construction.** The sink is typed as a
    :class:`~ai_assistant.core.protocols.TraceSink` and never as the concrete
    store or as ``TraceStore``, so a holder can append a trace and cannot walk one
    (ADR-0119 §7) — the same narrowing the ``Engine``'s two trace parameters get,
    reaching one more consumer. `service` may not name
    ``ai_assistant.evaluation`` at all (``lint-imports``), so the annotation and
    the contract agree.

    Attributes:
        engine: The ready façade, exactly as :func:`build_engine` returns it.
        trace_sink: The **append** seam of the trace store opened by this build.
        retrieval_search_limit: The largest ``limit`` a turn's retrieval reaches
            ``MemoryStore.search`` with. Equal to the loop's own
            ``retrieval_limit``, because ``orchestration/retrieval.py`` fills one
            budget of that size band by band and the first band asks for all of it.
        conflict_search_limit: The ``limit`` the ingestor's conflict probe reaches
            ``MemoryStore.search`` with — the ceiling **plus two** (ADR-0079 §1),
            which is the figure §9 requires and the control's own value is not.
    """

    engine: Engine
    trace_sink: TraceSink
    retrieval_search_limit: int
    conflict_search_limit: int


def build_engine(settings: Settings, *, data_dir: Path | None = None) -> Engine:
    """The engine alone, for every caller that needs nothing else (ADR-0042 §2).

    The composition root's entry point, unchanged in behaviour and in signature.
    :func:`build_composition` is the same build with ADR-0119 §9's two extra
    figures still attached; a caller that is not stamping a configuration trace
    wants this one.

    Args:
        settings: Loaded application settings; see :func:`build_composition`.
        data_dir: Where the SQLite stores live, overriding ``settings.data_dir``
            when given; see :func:`build_composition`.

    Returns:
        A ready :class:`Engine`. Drive it with ``converse``/``resume`` and close
        it with ``aclose`` when the session ends.

    Raises:
        ConfigurationError: Whatever :func:`build_composition` raises, unchanged.
    """
    return build_composition(settings, data_dir=data_dir).engine


def build_composition(  # noqa: PLR0915 — one statement per resource this root opens or wires
    settings: Settings,
    *,
    data_dir: Path | None = None,
    transport: OutboundTransport | None = None,
) -> Composition:
    """Wire the production subsystems into a ready :class:`Composition` (ADR-0042 §2).

    The one place concrete subsystems are constructed. It discharges the wiring
    obligations no type can express — **once**, here, rather than copied into
    every front end (ADR-0042 §2):

    * the *same* :class:`SqliteMemoryStore` instance is injected into the loop
      (for retrieval) and into the :class:`MemoryIngestor` writer (for
      persistence), so the closed learning loop is not silently open (ADR-0028 §4);
    * one :class:`InMemoryToolRegistry` object is injected as the selecting
      ``ToolRegistry``, the acting ``ToolInvoker`` (ADR-0029 §8) **and the registry
      the loop reads the planner's capability vocabulary from** (ADR-0211 §3), and
      is handed the ``InvocationLedger`` face of the one :class:`SqliteAuditTrail`
      — never the trail itself (ADR-0192 §9);
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
    * the **notification store and its policy are wired together** (ADR-0130 §3,
      §9), which is the one thing the ``Engine`` refuses to be built without: it
      takes the pair or neither, so a store nothing rules and a ruling nothing
      keeps are both unconstructable. The policy is handed to the engine rather
      than to the store, because §3 puts the ruling *inside* the store's critical
      section by making it an argument to each call — and it reads
      ``settings.timezone``, the same value ADR-0008 §5 gives the temporal
      context, because §6 introduces no second timezone source.

    **Configuration is validated before any resource is opened (#372).** The
    resource-free construction — the model seam (which checks every configured
    spec's vendor, ADR-0062 §2), the context provider (which reads only settings),
    and the embedder (whose on-device default checks the vendored model artifact,
    ADR-0006 §2, ADR-0024) — runs *above* the data directory and the stores, so a
    bad configuration fails without ever touching disk: no directory is created and
    no database file is written for a build that was never going to succeed. Only
    the steps that genuinely need an open store stay below that line.

    **It owns the resources it opens.** The connection-owning stores are
    opened first among the resources; if any *later* construction fails, the ones
    already opened are closed before the error propagates, so no half-built engine
    leaks a connection (ADR-0042 §2). On success, their ``close`` methods are handed
    to the façade as its ordered shutdown path — the façade's ``aclose`` drains
    in-flight work, then closes them (ADR-0042 §2); the caller (an adapter) owns
    calling ``aclose``.

    The tool registry is populated with the one **local, no-egress** tool ADR-0048
    left standing: ``current_time`` (ADR-0208 §1 removed ``recall_memory``). So a
    planned step naming its capability selects, gates and executes; a step naming
    any other capability — a memory lookup included — finds no capable tool and is
    skipped (``NO_CAPABLE_TOOL``), which ADR-0208 §3 rules is the correct outcome
    rather than a gap to close by re-registering a tool.
    Since ADR-0211 the planner is **told** that vocabulary — the loop reads it off
    the very registry built here and passes it — so a goal needing a capability
    nobody advertises is one the prompt asks to be declined rather than planned.
    That is an instruction and not a guarantee (ADR-0211 §6): a model may still emit
    a name outside the vocabulary, and where it does the step is planned, reaches
    selection and skips exactly as before. ADR-0053's alias layer is the bridge for
    a near miss, which is the model↔tool alignment follow-up ADR-0048 records
    rather than solves.

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
        transport: The outbound-transport capability this deployment reaches the
            world with (ADR-0191 §1), or ``None`` for the production one this root
            constructs below. **This is not the fallback ADR-0191 §3 forbids**, and
            the distinction is by which party the clause is about: §3's ban on a
            default is stated over "every constructor and factory that *needs* a
            transport" — ``SmtpEgressTransport`` and
            ``build_send_email_integration``, both of which now take it required —
            while §3's fourth clause makes *this* function the only place in
            ``src/ai_assistant`` that constructs the real implementation and the
            only place that hands it out. Absence here therefore selects
            production rather than letting a consumer past a missing injection.
            The seam exists because ADR-0191 §9 requires milestone 25's exit arm to
            build its composition *through this root* while handing it
            :class:`~ai_assistant.testing.FakeOutboundTransport`, which is the
            "same route" clause of §3 read from the test's side.

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
        A :class:`Composition`: the ready :class:`Engine` — drive it with
        ``converse``/``resume`` and close it with ``aclose`` when the session ends
        — beside the trace sink this build opened and the two effective ``search``
        limits it produced, which ADR-0119 §9's startup stamp records and cannot
        read off ``Settings``.

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
    # The reconciler's route, on the observer's shape and for the observer's reasons
    # (ADR-0159 §3, ADR-0077 §3): one route, named rather than inherited, and no
    # fallback. Built up here so a spec naming an uninstalled vendor fails the build
    # rather than the first ingest that would have used it.
    reconciler_route = _reconciler_spec(settings)
    reconciler_model = _build_reconciler_provider(settings, reconciler_route)
    # The read-only sources, if this deployment configured one (ADR-0093 §7).
    # **Three reader instances rather than one**, and ADR-0096 §5 decides it here
    # rather than
    # leaving the composition lane to pick by accident: ADR-0093 §7 bounds a reader
    # at one outstanding worker *per instance*, so a shared reader would let a
    # scheduled ingestion read suppress the request-path facet for as long as it
    # runs — coupling a request cadence to a periodic job, in the direction that
    # makes an advisory facet wait on it. Three instances cost three workers at
    # most, which is still bounded, and each consumer then owns its own failure.
    #
    # **The third is ADR-0132's producer, and ADR-0132 §3 requires it to be its
    # own.** "The producer performs its own ``Reader.read()`` on its own schedule,
    # and derives nothing from the facet path's reading or from the ingestion
    # job's" — ADR-0093 §3's rule applied rather than stretched, because a producer
    # reading a snapshot ingestion left behind would be reading durable
    # cross-subsystem state §5 of that ADR forbids and would inherit a cadence
    # chosen for a different job. The serial scheduler keeps the two scheduled
    # reads from contending; what a deployment running both pays is duty cycle, and
    # ADR-0132's Consequences name that rather than hide it.
    #
    # All three are built above the data directory, and they belong there for
    # #372's reason rather than by association: constructing a reader opens nothing
    # — it validates §7a's figures and names a daemon thread it has not started —
    # so a calendar window or cap outside its range fails the build before any
    # store is written.
    facet_reader = _build_calendar_reader(settings)
    ingestion_reader = _build_calendar_reader(settings)
    upcoming_reader = _build_calendar_reader(settings)
    # And the same rule applied to the **second source** (ADR-0140, ADR-0142 §3).
    # Two instances rather than three, because email has two consumers and not
    # three: ADR-0140 §9 mints no producer for it, so there is no upcoming-event
    # sibling to build. The count follows the consumers rather than the calendar's
    # shape, which is the half a lane copying the block above gets wrong.
    #
    # **Separate instances is ADR-0140 §13's own deliverable**, stated there rather
    # than left to ADR-0096 §5 by inference: "both consumers above are wired into
    # the engine on **separate** ``EmailReader`` instances, neither sharing the
    # other's". A root injecting one reader into both wires a hub in which a
    # running scheduled ingest makes the request-path facet raise ``ReaderError``
    # and vanish — every presence check passing while a ratified clause is
    # breached.
    #
    # Built above the data directory for the calendar readers' reason exactly
    # (#372): constructing one opens nothing and validates ADR-0140 §12's five
    # figures, so a window or cap outside its range fails the build before any
    # store is written.
    email_facet_reader = _build_email_reader(settings)
    email_ingestion_reader = _build_email_reader(settings)
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
    # And the notification store's tuning is *asked* here, above the data
    # directory, though its store opens below with the rest (ADR-0130 §7,
    # ADR-0022 §4a). It is the first tuning in this tree that ``Settings`` accepts
    # and a store refuses — §7 puts no ceiling on a retention, the deliberate
    # escape being ``None``, while this backend stamps one as microseconds into a
    # signed 64-bit column — so without this call a deployment configuring one
    # past that bound would create the data directory and open the stores that
    # precede the notification store, only then learning its configuration was
    # unusable — the store's own constructor checks before it opens its file, so
    # the stores after it never open either. #372's contract is that
    # "no directory is created and no database file is written for a build that
    # was never going to succeed", and a check that touches no resource belongs
    # above the line whatever opens it below.
    #
    # The store checks again for itself when it is built: it is public, anyone
    # may construct one directly, and a guard that only fires when a caller
    # remembered to ask is not a guard.
    check_notification_tuning(settings.notification_retention, settings.notification_queue_limit)
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
        #
        # **The trace store opens ahead of the rest**, because the stores below
        # take it as a ``TraceSink`` and a required constructor argument cannot be
        # filled by something that does not exist yet (ADR-0119 §7). It is still
        # the **seventh** connection-owning store (ADR-0119 §6) — the ordinal
        # counts them, it does not order them — and the first that is **Tier 2**
        # rather than Tier 1: it holds numbers, opaque ids and durations about
        # events, and never the content those events were about (§2). ADR-0083
        # ruling 4's exclusivity needs nothing new for it, on ADR-0102 §12's
        # reasoning: it lives inside the directory the instance lock already
        # covers, is opened by the same process, is closed in the same ordered
        # shutdown, and is reached only through the API.
        #
        # **A database of its own rather than a table beside an existing one**
        # (§6). Two reasons, and the second decides: a trace about a failed write
        # inside the failed write's own database is lost exactly when it is most
        # wanted, and this is the only store here with a decided deletion horizon,
        # so putting a swept table beside ``memory.db``'s retention axes would be
        # three lifetimes in one file.
        #
        # **One object, handed out narrowed, and never whole** (§7). The
        # ``Engine`` below is given it as a ``TraceRetention`` — the deletion
        # seam — so the maintenance operation can sweep it and the pipeline
        # cannot walk it. The memory store and the writer are given the same
        # object as a ``TraceSink``, narrowed the same way, by the annotation on
        # each one's own constructor. Nothing takes it whole.
        #
        # **``settings.trace_retention`` is enforced from here** (#852): the
        # engine measures the horizon back from its own clock and calls
        # ``purge_before`` as the third call behind ADR-0083 §7's existing
        # retention-purge operation (ADR-0119 §10). No new job, no new interval,
        # and no store surface on the scheduler, which holds an ``Engine`` and
        # nothing else.
        traces = SqliteTraceStore(path=directory / "traces.db")
        opened.append(traces.close)
        # ADR-0119 §8's ``RETRIEVAL`` emitter is *inside* this store, because what
        # the trace reports about a read is observable only here: the ``limit``
        # asked for, the ``fetch_k`` the KNN was actually given after the clamp, the
        # candidate count and the band split. A trace emitted one layer up would
        # satisfy the letter of "we have retrieval telemetry" and see none of them.
        # Which of §8's keys still carry a signal is ``memory/traces.py``'s to say
        # and not this comment's — it documents each key against the decision that
        # set it, several of them structurally zero since ADR-0128 §1 and kept
        # rather than dropped by §3. This is the wiring point that arms the emitter.
        memory = SqliteMemoryStore(
            path=directory / "memory.db", embedder=embedder, traces_sink=traces
        )
        opened.append(memory.close)
        # ADR-0193's standing recipient grants — a Tier 1 store beside the two
        # below, holding what the user made *standing* about sending where the
        # source-grant store holds what they authorised about *reading*. The two
        # may not be joined (ADR-0097 §7, ADR-0193 §13), which is why they are two
        # files and two objects rather than two tables in one.
        #
        # **Built before the trail**, because the trail resolves a route-(b)
        # ``authorised_by`` against it and takes it as a constructor dependency.
        #
        # **One object, passed three times**: as a ``RecipientGrantResolution`` to
        # the trail, as a ``RecipientGrants`` to the policy, and — once a surface
        # offers the establishing act (ADR-0193 §13 defers which) — whole to
        # whatever performs it. Structural typing is what makes that sound, and the
        # narrowing is the *annotation on each consumer* rather than anything done
        # here: what the trail cannot do is name ``covering`` or ``record``, and
        # what the policy cannot do is name ``record``.
        #
        # The ceiling is the operator's configuration and reaches the constructor
        # with no default of its own: ``Settings`` carries ADR-0193 §1's shipped 64,
        # and a second default here would be a figure a deployment could not see it
        # was getting. Zero is admitted and means the deployment declines route (b).
        recipient_grants = SqliteRecipientGrantStore(
            path=directory / "recipient_grants.db",
            max_outstanding=settings.recipient_grant_max_outstanding,
        )
        opened.append(recipient_grants.close)
        # **The sole reader of ADR-0194 §1's four spend settings, and of the fifth
        # this mechanism depends on** (ADR-0194 §5, §11). The store takes explicit
        # values and never a `Settings` read, so this is the one place the two
        # meet — and `timezone` is read *with* them because it is what selects the
        # calendar period every total and every admission is decided over. A reader
        # counting only four cannot implement the period rule.
        #
        # **One object satisfies `SpendGate`, `SpendLedger` and ADR-0192's ledger
        # seam**, because all three read the same rows: two holders keyed by them
        # could disagree about a total, which is the failure ADR-0016 §7 named for
        # two registries one seam over.
        trail = SqliteAuditTrail(
            path=directory / "audit.db",
            recipient_grants=recipient_grants,
            # **The clock is injected here**, which ADR-0194 §5 names alongside the
            # five settings as this root's own obligation. Left to the store's
            # default it would be a clock this layer neither chose nor could
            # substitute — and this is the same `_utcnow` every other seam here is
            # given, so the instant that stamps an invocation row and the instant
            # that selects its calendar period are read through one function.
            now=_utcnow,
            spend=SpendConfiguration(
                currency=settings.world_spend_currency,
                day_ceiling=settings.world_spend_day_ceiling,
                month_ceiling=settings.world_spend_month_ceiling,
                allowance=settings.world_spend_unknown_allowance,
                zone=settings.timezone,
            ),
        )
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
        # data directory and the same owner-only file mode as the other five
        # Tier 1 stores,
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
        # ADR-0185's source-read trail — the **eleventh** connection-owning store
        # and the tenth that is Tier 1, holding what this system *read* where the
        # store above holds what the user *authorised*. ADR-0139 §6 is explicit that
        # the second does not discharge ADR-0004 §7's recording half for the first:
        # "granting is not access". ADR-0083 ruling 4's exclusivity needs nothing new
        # for it, on ADR-0102 §12's reasoning: it is inside the directory the
        # instance lock already covers, opened by the same process, and closed in the
        # same ordered shutdown.
        #
        # **One object, passed four times** (ADR-0185 §4, ADR-0186 §10): as a
        # `SourceReadRecorder` to each of the three drivers, and **whole, as the
        # `SourceReadTrail`, to the engine**. Structural typing is what makes that
        # sound, and the narrowing is the *annotation on the driver's constructor*
        # rather than anything done here — what a driver cannot do is name `recent`,
        # which is what keeps ADR-0093 §5's forbidden cursor out of a sensor's reach.
        #
        # **The engine is the wide seam's only holder**, which is the surface
        # ADR-0185 §12 left to its own lane and ADR-0186 §10 decided. The asymmetry
        # is the design: the drivers write and cannot read, the façade reads and does
        # not write — authoring a row stays on the seam that gated the read (ADR-0185
        # §5), and ADR-0186 §4's refusal of a promoted `record` is one store over the
        # same rule. That all four positions hold the **same instance** is a
        # composition-root obligation no type can state: a façade wired to a second
        # trail would answer a user's history from a store nothing writes to, which
        # is worse than an error, since it is indistinguishable from the truthful
        # answer that nothing has been read.
        #
        # **The cap is the user's configuration and reaches the constructor**, where
        # it is validated once and read once (ADR-0185 §6). It is a row count rather
        # than a duration because this store's inflow is a *timer*, and there is no
        # unlimited spelling for it at either end.
        reads = SqliteSourceReadTrail(
            path=directory / "reads.db", max_rows=settings.source_read_trail_max_rows
        )
        opened.append(reads.close)
        # The routing trail (ADR-0197 §9). A **fourth** row kind, joining neither of
        # ADR-0186 §10's two partitions: a routed operation is never a
        # `PermissionDecision` and never a `SourceReadRecord`. One row per decision,
        # written *before* the act it precedes, so a routed `forget` — the one act that
        # destroys the only other evidence of itself — leaves a record that a **model**
        # chose it.
        #
        # **One object, two seams, and only one position names either today.** The
        # engine is handed it as `RoutingRecorder`, the write-only half the routing
        # stage holds, which is what stops a stage erasing the record of its own
        # decisions with `clear` (§9). Nothing holds the readable `RoutingTrail`:
        # ADR-0197 §9 mints no engine method for it and §11 leaves the read surface to
        # its own decision, so an operator debugging a routed act reads the store
        # directly until then. That is ADR-0185's own position for a day, and it is
        # stated as a cost rather than discovered.
        #
        # **The cap is the user's configuration and reaches the constructor**, where it
        # is validated once and read once — `source_read_trail_max_rows`' shape and its
        # number, because a routing row is smaller than a read row and the two trails
        # are read by the same kind of operator. There is no unlimited spelling.
        routing_trail = SqliteRoutingTrail(
            path=directory / "routing.db", max_rows=settings.routing_trail_max_rows
        )
        opened.append(routing_trail.close)
        # The held notifications (ADR-0130 §7, §9). The **eighth**
        # connection-owning store and the seventh that is Tier 1: a candidate
        # carries free text a producer wrote to be shown to a person, so it lives
        # under the same data directory and the same owner-only file mode as the
        # other Tier 1 stores. ADR-0083 ruling 4's exclusivity needs nothing
        # new for it, on ADR-0102 §12's reasoning: it is inside the directory the
        # instance lock already covers, opened by the same process, and closed in
        # the same ordered shutdown.
        #
        # Both tunings are the *user's* configuration and both reach the
        # constructor, where they are validated once and read once: the retention
        # is stamped onto each record at admission and runs from the instant that
        # record **ceased** to be actionable, so a later change to the setting
        # never reaches back into a record already admitted (§7); and the cap is
        # strictly positive because a cap of zero is at capacity before its first
        # admission (§7, ADR-0022 §4a). The cap counts the **actionable** set, so
        # what it bounds is the list a person reads rather than the storage.
        #
        # **The id source is deliberately not passed**, and for the opposite
        # reason the deferral queue's claim-token source is not: a notification id
        # authorises nothing — every read that names one hands back the record
        # beside it — so it is an identity rather than a capability, and the
        # default is a plain UUID rather than a ``secrets`` draw.
        #
        # **ADR-0141 §3's ruling seam is inside this store, and this is the
        # wiring point that arms it** — the same argument the memory store's
        # ``RETRIEVAL`` emitter is wired on. The conditions §4 records exist only
        # inside ADR-0130 §3's atomic act, and the reconsideration path does not
        # reach the writer stage at all, so an emitter one layer up would miss
        # every ruling that is not a first offer. The sink is the *same* trace
        # store the engine boundary and the memory seams append to, so one stream
        # carries every kind. It is a required argument with no default (§10), so
        # a composition that omitted it would not type-check.
        notifications = SqliteNotificationStore(
            path=directory / "notifications.db",
            traces_sink=traces,
            retention=settings.notification_retention,
            cap=settings.notification_queue_limit,
        )
        opened.append(notifications.close)
        # ADR-0131 §3's delivery outbox: the **ninth** connection-owning store and
        # the eighth that is Tier 1, for the notification store's reason exactly —
        # an entry holds the same candidate, so it holds the same free text a
        # producer wrote to be shown to a person.
        #
        # **It is handed the notification store rather than reaching into one**
        # (ADR-0131 §3b). Every way an entry leaves the outbox dismisses its
        # ADR-0130 record "through the dismissal ``NotificationStore`` carries", and
        # the two commits are ordered rather than atomic — dismiss first, remove
        # after — which is what makes §3b's invariant true: an actionable record
        # with no entry means its enqueue never committed, and nothing else. That
        # ordering is the outbox's to keep, so it needs the seam, and this is where
        # golden rule 1 puts the pairing.
        #
        # **The delivery ceiling is computed here because only here knows it**
        # (ADR-0131 §4): it is ADR-0085 §8's contract limit — the frame ceiling less
        # §8b's 512-byte envelope reserve, which this root already subtracts for the
        # engine — less §4's 256-byte delivery reserve, which covers wrapping a
        # candidate as ``{"delivery_id": …, "notification": …}``. §4 forbids the
        # bound living on ``NotificationCandidate``'s own validation, because a
        # frozen `core` model has no ``Settings`` input and the same candidate would
        # then be valid on one hub and invalid on another.
        outbox = SqliteNotificationOutbox(
            path=directory / "outbox.db",
            records=notifications,
            lease=settings.hub_notification_lease,
            max_entries=settings.hub_notification_outbox_entries,
            max_bytes=settings.hub_notification_outbox_bytes,
            candidate_ceiling=(
                settings.hub_max_frame_bytes - ENVELOPE_RESERVE_BYTES - DELIVERY_RESERVE_BYTES
            ),
        )
        opened.append(outbox.close)
        connections, connection_operations, integration_secrets = _build_connection_operations(
            directory, opened=opened
        )

        # ADR-0130 §4 and §5's deterministic ruling, built once and held twice: the
        # engine hands it to the store on the reconsideration path, and the write
        # stage below hands it to the same store on the live path. One object,
        # because two would be two policies over one store — and `Settings.timezone`
        # is its one construction-time input (§6), so two could not even disagree
        # about the user's night without a second timezone source, which there is
        # not.
        notification_policy = DefaultNotificationPolicy(timezone=settings.timezone)
        # **ADR-0130 §3's producer seam, concrete at last** (#964). Until leg 10's
        # first producer existed there was nothing to hold it and this root said so;
        # ADR-0132's producer is that holder, so the seam is composed here, over the
        # *same* store the engine's surface reads and the *same* outbox the engine
        # serves polls from. A second store would let a ruled notification be
        # unreadable and undismissable through the surfaces the user has (ADR-0028
        # §4), and a second outbox would break ADR-0131 §3b's invariant outright.
        #
        # **The outbox is what makes the live handoff exist** (ADR-0131 §3b): "When
        # a ``NotificationWriter`` call returns an actionable ``INTERRUPT``
        # disposition, the same call path calls ``NotificationOutbox.offer`` with
        # that candidate before it returns to the producer", and §3b's startup
        # reconciliation is a repair for a handoff that did not happen rather than
        # the trigger a notification relies on. It is passed explicitly rather than
        # defaulted, so a root that meant "there is nowhere to deliver" would have
        # to say so.
        notification_writer = NotificationWriteStage(
            store=notifications, policy=notification_policy, outbox=outbox
        )

        # The context provider, assembled now that the grant seam exists. Each
        # source's facet is registered only when **that source** is configured — a
        # source with nothing to read would be I/O on personal data in exchange for
        # nothing (ADR-0093 §7a, ADR-0140 §13) — and the two decisions read
        # different fields and neither reads the other's (ADR-0142 §2). Neither
        # carries a `required` marker, so a reader fault, a store fault or a
        # withdrawn grant each degrade that one facet and leave the rest of the
        # context assembled (ADR-0008 §4, ADR-0026 §4).
        context = AssemblingContextProvider(
            [
                clock_source,
                *(
                    []
                    if facet_reader is None
                    else [
                        CalendarContextSource(
                            reader=facet_reader, grants=grants, reads=reads, now=_utcnow
                        )
                    ]
                ),
                *(
                    []
                    if email_facet_reader is None
                    else [
                        EmailContextSource(
                            reader=email_facet_reader, grants=grants, reads=reads, now=_utcnow
                        )
                    ]
                ),
            ]
        )

        # **The one registered egress integration, where a deployment configured
        # one** (ADR-0148 §6, ADR-0152 §10, ADR-0154 §6). Built before the registry
        # because both the registry's contents and the binding seam's registration
        # table are derived from this single value, which is what stops them from
        # disagreeing: a `send_email` in the registry with no registration behind it
        # is a tool the seam refuses on every call (ADR-0152 §8), and a registration
        # with nothing in the registry names a tool nothing can invoke.
        #
        # **Why the two facts are configuration.** Nothing in the tree records which
        # service a connected account is on: ADR-0151 §18 scopes out "what an
        # integration *is*: an endpoint, a service identity, a scope list, an
        # account chooser" and ADR-0149 §13 states the consequence — "a connection
        # record carries no endpoint and no description". So neither the reference
        # nor the endpoint is derivable from what is connected, and until the ADR
        # §18 says fires with the first integration lands, the operator states both.
        # `Settings` refuses half a pair, so this is whole or absent.
        #
        # **`records` and `secrets` are the objects this root already holds**, not
        # second ones over the same file and namespace. The transport reads the
        # connection record twice around its credential read (ADR-0148 §6) and the
        # binding seam reads it once per call (ADR-0152 §10); a second handle would
        # let a provisioning act commit a revision one of them could not yet see.
        # The keyring face is the single `INTEGRATION`-scoped one (ADR-0149 §1),
        # narrowed here to `Secrets` by the parameter's own annotation — a transport
        # handed the writing face could delete the credential it reads.
        #
        # **The transport capability is constructed here and handed in** (ADR-0191
        # §1, §3). Constructed *inside* the branch, so a deployment that configured
        # no integration builds no transport at all and hands none out: absence of
        # configuration never selects a default implementation, and the property
        # "a subsystem handed no capability has no route to the world" is true of
        # the whole tree rather than of one argument list. Holding it does not make
        # `app` an egress boundary — it opens nothing, and no lane may read this
        # line as designating one under ADR-0017 §1.
        egress = (
            None
            if settings.send_email_connection is None or settings.send_email_endpoint is None
            else build_send_email_integration(
                connection=settings.send_email_connection,
                endpoint=settings.send_email_endpoint,
                records=connections,
                secrets=integration_secrets,
                transport=StreamOutboundTransport() if transport is None else transport,
            )
        )

        # One object as both the selecting registry and the acting invoker
        # (ADR-0029 §8). Populated with `current_time` (ADR-0048) and, where a
        # deployment connected an account, `send_email`. **No memory tool**: the
        # turn's supply is retrieved once, in the retrieval stage, and no store is
        # injected here for a tool to re-read it band-blind (ADR-0208 §1).
        #
        # **The invoker is handed the ledger face of `trail`, and never the trail**
        # (ADR-0192 §9's wiring clause). One object satisfies `AuditTrail`,
        # `InvocationLedger` and `InvocationCompleter` over one store, and each
        # consumer is handed the face its job needs: the seam claims and completes,
        # so it gets the ledger; it can neither record a `PermissionDecision`, nor
        # read one, nor export, nor `clear` through it, so no decision write, no
        # history read and no erasure reaches `tools/` (ADR-0192 §2). The
        # narrowing is the parameter's annotation, which is what makes it a **type**
        # rather than a prohibition an implementation is trusted to keep.
        #
        # **The same object as the trail the runner records decisions into**, not a
        # second one over the same file. The ledger requires the decision it is
        # passed to be equal to the decision the store holds under that id
        # (ADR-0192 §1), so a second handle would refuse every claim under a ruling
        # the runner had just recorded — and two tables keyed by one decision could
        # diverge, which is the split ADR-0029 §8 refuses one seam over.
        #
        # **And the gate face of that same object** (ADR-0194 §3, §5): the invoker
        # is admitted through the holder that reads the rows the ledger writes, and
        # is handed the gate and never the `SpendLedger` — an invoker able to read a
        # totals projection has acquired a permissions-owned history it has no use
        # for, which is ADR-0029 §1's argument one seam over. The engine below gets
        # the ledger face and never the gate, for the mirror reason.
        tools = build_default_registry(egress=egress, ledger=trail, gate=trail)

        # The writer persists to the *same* store the loop retrieves from (ADR-0028 §4),
        # and appends its ``MEMORY_WRITE`` traces to the *same* trace store the read
        # path and the engine boundary use, so §4's correlation join has one stream
        # to join within (ADR-0119 §8).
        #
        # **``conflict_limit`` is passed rather than defaulted** (ADR-0119 §9). It
        # is one of the two cardinality controls whose *effective* ``search`` limit
        # the configuration stamp records, and §9 puts the figure to record here:
        # "the figure to record is the one the composition root actually produced".
        # A default filled in by `memory` would leave this layer stating a number
        # it did not choose. The value is `memory`'s own, so nothing moves.
        writer = MemoryIngestor(
            store=memory,
            policy=DefaultMemoryPolicy(),
            traces_sink=traces,
            conflict_limit=CONFLICT_LIMIT,
            # ADR-0159's reconciler, wired because this deployment has a model seam
            # to give it. Its absence is ruled and safe (§6) — the writer would then
            # hold ADR-0121 §1's certain agreements alone — so this line buys the
            # judgement rather than enabling the write path.
            reconciler=ModelBackedReconciler(
                model=reconciler_model,
                route=reconciler_route,
                max_conflicts=settings.reconciler_max_conflicts,
            ),
        )
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
            # **The same object as the selecting registry and the acting invoker**
            # (ADR-0211 §3), not a second registry and not a snapshot taken from
            # one. The turn reads `capabilities()` off this to tell the planner what
            # can be done, and `StepRunner` below resolves the resulting steps
            # against the very same object — so a step cannot be planned against a
            # capability the selecting registry never advertised, which is #1772's
            # narration reintroduced by wiring rather than by prompting. This root
            # already holds exactly one `InMemoryToolRegistry` for ADR-0029 §8's
            # reason; this line extends that single-object discipline to the
            # planning stage rather than inventing a second one for it.
            registry=tools,
            feedback=RuleBasedFeedbackProcessor(),
            # Passed rather than defaulted, for the reason the ingestor's
            # ``conflict_limit`` is (ADR-0119 §9): this is the second cardinality
            # control, and its effective ``search`` limit is its own value —
            # ``orchestration/retrieval.py`` fills one budget of this size band by
            # band, so the first band asks for all of it and no band asks for more.
            retrieval_limit=RETRIEVAL_LIMIT,
            # The episodic supplement's own budget (ADR-0158 §3), passed for the
            # same reason and never subtracted from the one above: the two are two
            # budgets, not a share of one, so a turn asks for 30 beliefs *and* up
            # to 10 episodes. §5 puts this figure here rather than on ``Settings``.
            episodic_limit=EPISODIC_SUPPLEMENT_LIMIT,
        )
        # ADR-0152 §10's marked clause: "It is implemented in `tools/`, and consumed
        # in `orchestration` by the runner stage … **The composition root wires the
        # one implementation.**" (#1138). PR #1135 landed the seam and gave
        # ``StepRunner`` a ``binder`` defaulting to ``None``; this is the wiring it
        # deferred, because ``records`` needs a connection store the root did not
        # open until the connection surface arrived.
        #
        # **The same store object the provisioner writes**, not a second one over
        # the same file. ADR-0152 §10 makes the seam read one connection record per
        # egress call for its connectability and identity, and a second handle would
        # let a provisioning act commit a revision this seam could not yet see —
        # the split ADR-0102 §7 refuses one store over, arriving here.
        #
        # **`registrations` holds whatever `egress` above does, and nothing else.**
        # How a tool comes to be registered against a connected account is
        # `tools/`-internal and contracted nowhere (ADR-0152 §10), so `tools/` owns
        # both derivations and this root performs neither: `egress_registrations`
        # is the seam's half of the same value `build_default_registry` took the
        # registry's half of. An unconfigured deployment still gets an **empty**
        # table, and that is not an inert value — it is what keeps ADR-0152 §8's
        # mis-registration refusal reachable, so a tool declaring either §3 keyword
        # while bound to no connected account is refused rather than quietly
        # answered ``None``.
        #
        # **`definitions` is the same object injected as ``ToolRegistry`` and
        # ``ToolInvoker``**, so ADR-0152 §1's registry-original comparison and the
        # one ``invoke`` makes read one table rather than two that must agree
        # (ADR-0029 §1). ``canonicalises`` is left to its default, which is every
        # protocol `tools.destinations` holds a canonicaliser for: it can only
        # narrow that set, and narrowing here would manufacture ADR-0152 §3
        # refusals for protocols the seam can in fact canonicalise.
        binder = EgressBindingSeam(
            definitions=tools,
            registrations=egress_registrations(egress),
            records=connections,
        )
        runner = StepRunner(
            plans=plans,
            registry=tools,
            binder=binder,
            # The four gate thresholds are the operator's configuration (ADR-0021 §5,
            # #239); the Settings defaults reproduce the policy's own, so an unset
            # deployment keeps today's gate. The two floors take no setting.
            policy=ThresholdActionPolicy(
                confirm_at_risk=settings.confirm_at_risk,
                confirm_at_reversibility=settings.confirm_at_reversibility,
                deny_at_risk=settings.deny_at_risk,
                deny_at_reversibility=settings.deny_at_reversibility,
                # The **query face** of the store above and never the store
                # (ADR-0193 §7): a policy handed the whole thing is one ``record``
                # call away from authorising the send it is ruling on, and the
                # annotation on its constructor is what removes the capability.
                # Wiring it here is what makes ADR-0148 §3's route (b) reachable at
                # all; until a surface offers the establishing act (§13) the store
                # is empty, so every ruling is the one it was before.
                grants=recipient_grants,
            ),
            trail=trail,
            executor=StepExecutor(plans=plans, registry=tools, invoker=tools),
            # A parked confirmation's lifetime is a deployment value (#310); ``None``
            # (the default) keeps the pre-#243 behaviour of no lifetime.
            confirmation_ttl=settings.confirmation_ttl,
            # ADR-0144 §4's preference sequence, supplied here because that is
            # where the ADR puts it — an operator's surface, not a user's
            # (:data:`TOOL_PREFERENCE`, #1101).
            tool_preference=TOOL_PREFERENCE,
        )
        engine = Engine(
            loop=loop,
            runner=runner,
            plans=plans,
            trail=trail,
            # The **ledger** face of that same object, and never the gate
            # (ADR-0194 §5): one holder over one set of rows, so the totals a user
            # reads and the ceiling the seam enforces cannot disagree — while an
            # adapter reaching this member acquires no route to an admission.
            spend=trail,
            # ADR-0014 §4's startup scan, over the **same two stores** the runner
            # and the executor write through (ADR-0192 §9). The audit store is
            # handed over twice, under two of the three faces one object satisfies:
            # as `AuditTrail`, for the one query ADR-0192 §2 gives this consumer
            # (`open_invocations`), and as `InvocationCompleter`, the narrow face
            # over the invocation rows. It is **not** handed `InvocationLedger` —
            # the wide face the `ToolInvoker` gets — because `claim_invocation` is
            # the seam's act and no lane outside `tools/` calls it: withholding the
            # member is what makes "the scan never claims" a **type** rather than a
            # prohibition this composition is trusted to keep (ADR-0029 §1).
            recovery=RecoveryScan(plans=plans, trail=trail, completer=trail),
            # The very trail the three drivers record into, handed over **whole**
            # here and narrowed to `SourceReadRecorder` at each of them (ADR-0185 §4,
            # ADR-0186 §10). This is the only position that names the wide seam, and
            # it is what makes `recent_reads` and `export_reads` answer about the
            # reads that actually happened rather than about an empty second store.
            reads=reads,
            # ADR-0197's operation-routing stage, over the **same** model seam the
            # planner and the composer reach through — `model`, the
            # routing-over-retrying provider built above. §2 gives the stage no setting
            # and §11 leaves "which model answers" undecided, so it takes the
            # deployment's configured route rather than naming one, and `complete` is
            # called with no `model=` override for ADR-0013 §4's reason.
            #
            # The **write-only** half of §9's trail goes to the *stage*, and the
            # asymmetry is the design: the stage writes and cannot read, exactly as the
            # read trail's drivers do. Structural typing means this one object satisfies
            # `RoutingTrail` too, so the read surface §11 defers takes this same instance
            # rather than a second store — but what the stage can *name* is `record`,
            # which is what makes "a stage cannot erase the record of its own decisions"
            # a `mypy --strict` failure rather than a review note. The façade is handed
            # no trail seam of any width, so this is the one position that names either.
            routing=RoutingStage(model=model, recorder=routing_trail),
            # The two speech seams, each under the deadline decorator ADR-0200 §1
            # puts on the *wrapper* rather than in the seam, "so that it composes
            # over every implementation" (ADR-0118 §2). Wired **together**: half a
            # pipeline can transcribe an utterance and never say the answer, and the
            # engine refuses that shape at construction.
            transcriber=BoundedSpeechTranscriber(_build_transcriber()),
            synthesizer=BoundedSpeechSynthesizer(_build_synthesizer()),
            # What ADR-0199 §3 places as **speakable** on a channel of unbounded
            # audience among attested beliefs: the calendar source ADR-0093 §7
            # configures, and nothing else. The identity comes from the reader that
            # was actually built — ADR-0190 §7's minted discriminator included — and
            # this is the only layer that can read it, since `orchestration` may not
            # import `readers` (golden rule 1). No calendar configured means an empty
            # set, which withholds every attested record rather than guessing.
            speakable_attested_sources=(
                frozenset() if facet_reader is None else frozenset({facet_reader.name})
            ),
            # ADR-0200 §6's fourth byte ceiling, on **decoded** audio, straight off
            # `Settings`. It bounds a recording and a rendering with the same figure
            # for the reason ADR-0085 §8's limit is symmetric.
            max_spoken_audio_bytes=settings.hub_max_spoken_audio_bytes,
            # How long a routed park stays answerable (ADR-0197 §7). Straight off
            # `Settings`, positive and finite with no spelling for "never": a routed
            # park is invisible — `pending_confirmations` does not list it and no
            # durable store recovers it — so without a lifetime a client that
            # disconnected between the park and its token would hold a slot at
            # `max_outstanding_confirmations` that nothing could ever free.
            routed_confirmation_ttl=settings.routed_confirmation_ttl,
            # The same store the loop retrieves from and the writer persists to, so
            # the inspection surface lists the beliefs the assistant actually uses
            # and ``forget`` destroys what the user was shown (ADR-0073 §7).
            memory=memory,
            # The very queue `writes` enqueues into and `questions` below answers
            # from, so the retention sweep (ADR-0083 §7) reclaims the rows the
            # user's own questions live in. A second queue here would report a cap
            # kept over rows nobody can see (ADR-0078 §1, §10 item 8).
            deferrals=deferrals,
            # The seventh database's **deletion seam**, and the third store the one
            # maintenance operation sweeps (ADR-0119 §10). The very object opened
            # above, narrowed by the parameter's own annotation to
            # ``TraceRetention``: the engine may sweep the trace store and may not
            # walk it, because a pipeline that could read its own telemetry would be
            # measuring a system that includes the instrument (§7).
            traces=traces,
            # The **same object again**, narrowed the other way (ADR-0119 §7): a
            # ``TraceSink`` for the engine-boundary emitter §8 puts at
            # ``Engine._tracked``, so one ``OPERATION`` trace lands per public
            # call — a turn, a scheduled job and a client command alike. Two
            # parameters and not one because the capabilities are two: nothing in
            # the pipeline may name the walk, and a single wider parameter would
            # hand it over.
            trace_sink=traces,
            # The horizon that sweep measures back from, straight off ``Settings``
            # (ADR-0119 §10). ``None`` — the disable sentinel — means keep forever
            # and the sweep does not run; the default is 365 days, longer than any
            # measurement window, and there is no count or size cap to configure.
            trace_retention=settings.trace_retention,
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
            # The terminal composing stage (ADR-0170 §1), holding the **same** model
            # seam the planner reaches through — `model`, the routing-over-retrying
            # provider built above. One seam and not a second family of settings:
            # ADR-0170 §9 leaves "which model answers" undecided and §2 gives the
            # stage no setting of its own, so it takes the deployment's configured
            # route rather than naming one. This is the explicit composition-root
            # injection §2 obliges — `Engine` receives no `ModelProvider` of its
            # own, so a stage that reached for one would have to go through a
            # concrete subsystem's internals, which golden rule 1 forbids.
            composing=ComposingStage(
                model=model,
                # The streaming seam, built here and **not** wrapped (ADR-0173 §5).
                # No `RetryingProvider` and no `RoutingProvider`: a stream is not
                # atomic, so past its first non-blank delta a retry answers a
                # question already half-answered and a fallback route answers it
                # differently — which is why streaming is a sibling Protocol neither
                # wrapper implements rather than a member on `ModelProvider`. The
                # route is `default_model`, the same primary the router prefers, so
                # a streamed answer comes from the model the deployment configured
                # for conversation; a route that cannot stream is a `ModelError`
                # from the call and degrades the pass, never a startup refusal
                # (§5) — and its vendor is already checked above, since
                # `_model_specs` puts `default_model` first.
                streaming=PydanticAIStreamingCompleter(settings.default_model),
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
                    # The calendar a belief's event time is stated in (ADR-0156 §2,
                    # §3): ``settings.timezone`` again, the same value ADR-0008 §5
                    # gives the temporal context and ADR-0130 §6 gives the
                    # notification policy, because §6 of ADR-0008 introduces no
                    # second timezone source. Withholding it would be a producer
                    # that resolves no relative expression at all, since UTC is the
                    # one calendar §3 refuses to substitute.
                    timezone=settings.timezone,
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
            # no stage at all and `Engine.ingest_calendar` refuses rather than
            # reporting an
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
            calendar_ingestion=(
                None
                if ingestion_reader is None
                else IngestionStage(
                    reader=ingestion_reader,
                    writes=writes,
                    grants=grants,
                    reads=reads,
                    now=_utcnow,
                )
            ),
            # ADR-0140's ingestion, and the **second source's** stage rather than a
            # second use of the first (ADR-0142 §3). It is a second construction of
            # the same class — no new machinery at all, which is the strongest
            # available evidence that the seam was cut in the right place at leg 6 —
            # over the *same* write stage, so an ingested mail belief the policy
            # defers parks a question the user can answer and one it stores is
            # inspectable and forgettable through the surfaces that already exist.
            #
            # **A multiplexing stage is refused, and the reason is cadence rather
            # than taste** (§3). One stage behind one operation is one scheduler row,
            # and one row has one interval — so a multiplexer would have to grow a
            # schedule of its own, which is ADR-0093 §11's registry arriving at the
            # second source instead of the third. It would also fuse the failure
            # modes: a `ReaderError` from one source would abort the loop and the
            # sibling source would not be read at all that tick.
            #
            # **Wired on its own path and armed on its own interval** (§2), reading
            # no field of the calendar's in either decision. Both clauses of §1 are
            # visible right here: the stage exists whenever `email_source_path` is
            # set, whatever the calendar is doing, and nothing defaults this
            # source's arming from another's.
            #
            # Its **own** reader, never the one the context source holds
            # (ADR-0096 §5, ADR-0140 §13).
            email_ingestion=(
                None
                if email_ingestion_reader is None
                else IngestionStage(
                    reader=email_ingestion_reader,
                    writes=writes,
                    grants=grants,
                    reads=reads,
                    now=_utcnow,
                )
            ),
            # Leg 10's upcoming-event producer (ADR-0132). **The first holder of
            # ADR-0130 §3's seam**, and the reason `notification_writer` above
            # exists at all.
            #
            # **Its own reader, its own grant scope, its own cadence** — three
            # independences ADR-0132 states separately because each is a different
            # ADR's rule. The reader is not shared (§3, ADR-0096 §5); the read is
            # gated on `NOTIFY` and on nothing else, so a live `INGEST` or `FACET`
            # grant on this calendar authorises it not at all (§2, ADR-0133 §2);
            # and its interval is its own field rather than a share of
            # `calendar_reader_interval` (§4).
            #
            # **Built whenever a source is configured, and armed only by its own
            # interval.** The stage's presence answers "is there anything to read";
            # the scheduler's row answers "should it be read on a timer"; and the
            # grant answers "may it be read for this". None of the three stands in
            # for another (ADR-0097 §8), which is why the stage is wired here even
            # when `calendar_upcoming_interval` is `None`.
            upcoming=(
                None
                if upcoming_reader is None
                else UpcomingEventStage(
                    reader=upcoming_reader,
                    grants=grants,
                    writer=notification_writer,
                    reads=reads,
                    # §1 enumerates a clock among the producer's collaborators, so
                    # it is injected here rather than reached for — the same seam
                    # the grant operations above take, and for ADR-0026's reason.
                    # §4 then anchors every instant the producer uses on the
                    # reading's own `read_at`, so nothing in the stage reads it and
                    # a test pins that it never does.
                    now=_utcnow,
                    lead=settings.calendar_upcoming_lead,
                )
            ),
            # Leg 7's consolidation stage (ADR-0106, ADR-0111, ADR-0114), over the
            # *same* write stage the three producers above use and the *same*
            # memory store it walks. Both are composition-root obligations no type
            # expresses (ADR-0028 §4): a second write stage would rule `ASK_USER` on
            # a thousand consolidations and park not one question, and a second
            # store would have it propose beliefs citing records the write path
            # cannot resolve — which ADR-0114's Alternatives give as the decisive
            # reason the walk sits *on* `MemoryStore` rather than beside it.
            #
            # **The observer's provider, deliberately reused.** ADR-0077 §3's
            # no-fallback rule is what this producer needs and it is exactly what
            # `_build_observer_provider` builds — one named route that never falls
            # back — and the reasoning reads here with more force: a consolidation
            # prompt carries a whole chunk of stored records, and the work is
            # deferrable by construction, because a run that fails does not record
            # its chunk as done. A second `consolidation_model` family would be
            # config surface with no decision behind it; ADR-0106 §12 leaves this
            # job's quality parameters to leg 8's measurement.
            #
            # **Always wired, unlike `ingestion` above**, because nothing about it
            # is conditional on a source or a grant: the job is armed by its
            # interval alone, which is `None` until an operator sets it. The two
            # bounds are ADR-0111 §4's `Settings` fields, so the delay this job can
            # impose on a sibling is a figure an operator can read off the
            # configuration.
            consolidation=ConsolidationStage(
                memory=memory,
                writes=writes,
                model=observer_model,
                chunk_size=settings.scheduler_chunk_size,
                run_budget=settings.scheduler_run_budget,
            ),
            # Leg 10's notification chassis (ADR-0130 §3, §9). **The two are wired
            # together or not at all**, which the ``Engine`` refuses to be built
            # without: a store with no policy could hold records nothing rules, and
            # a policy with no store could rule nothing that lasts. Before this
            # wiring existed all five surface methods refused with
            # ``ConfigurationError`` — "no store is composed" and "nothing is held"
            # being different facts — and after it a composed hub has a working
            # seam (#948).
            #
            # **The policy is a collaborator of the engine rather than of the
            # store**, and that is §3's shape: the store takes it as an *argument*
            # to each ruling call, so the ruling happens inside the store's
            # critical section and no window exists between reading the state and
            # writing the record it was ruled against. Nothing here sequences those
            # steps, and a composition that handed the store a policy to keep would
            # be describing a different contract.
            #
            # **`settings.timezone` is the policy's one construction-time input**
            # (§6): quiet windows are read in the same value ADR-0008 §5 gives the
            # temporal context and ADR-0093 §7b binds the calendar reader to, and
            # no second timezone source is introduced. It is passed here rather
            # than per call because a caller free to vary it could move the user's
            # night — and `Settings` has already refused an unknown IANA zone at
            # load, which is what stands behind a figure that now decides when the
            # assistant is allowed to interrupt.
            #
            # **The `NotificationWriter` is composed above rather than here**, and
            # that placement is §1's: the seam belongs to the *producer*, not to
            # this façade — "A producer holds no channel, no delivery seam and no
            # client connection", and the converse is that the engine holds no
            # producer seam. It is built beside the store it writes through and
            # handed to `upcoming` above. The store's `purge` needs no wiring
            # either — the engine calls it behind ADR-0083 §7's existing
            # retention-purge operation, as `PurgeReport.notifications`, exactly as
            # ADR-0130 §7 requires and as the trace store's sweep already does.
            notifications=notifications,
            notification_policy=notification_policy,
            # ADR-0131's delivery seam. The outbox reaches the engine as
            # ``orchestration``'s own ``DeliveryOutbox`` rather than as ``core``'s
            # ``NotificationOutbox``, because §3b gives the latter "exactly one
            # method" and that one is the *producer's*; the engine needs three more
            # to serve a poll, and this root is where one object takes both roles.
            #
            # **Its startup reconciliation is not run here**, and that is ADR-0131
            # §3b's clause rather than an omission: it must run "to completion
            # before it serves any poll", and this function builds an engine for a
            # CLI as well as for a hub. The hub runs it as part of coming up
            # (``service/hub.py``), where "before any poll" is a fact about the
            # listener rather than about a constructor.
            notification_outbox=outbox,
            max_notification_budget=settings.hub_max_notification_budget,
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
            # and a mapping would deduplicate that conflict away unseen. Each
            # source's instances agree by construction — all of one source's come
            # from one path field — which is exactly why the refusal has to be
            # expressed rather than assumed.
            #
            # **Each source's readers carry that source's own location, and the
            # second source is what made that necessary** (ADR-0102 §6). Until email
            # arrived this list read one field for every reader in it, which was
            # correct only while every reader was a calendar's;
            # `_configured_email_location` exists so that the disclosure a client
            # renders before a user grants is *this* source's path and never a
            # sibling's. A grant given against the wrong disclosed location is the
            # uninformed grant ADR-0097 §9a exists to prevent, arriving through a
            # wiring shortcut rather than through an encoding.
            grant_operations=GrantOperations(
                store=grants,
                sources=_held_sources(
                    settings,
                    calendar=(facet_reader, ingestion_reader, upcoming_reader),
                    email=(email_facet_reader, email_ingestion_reader),
                ),
                id_factory=_uuid,
                clock=_utcnow,
            ),
            # The five connection operations (ADR-0151 §1, §10), over the one
            # provisioner seam. **The engine reaches the provisioner through the
            # Protocol and never by an injected concrete**, and `orchestration`
            # imports no module of `tools` (golden rule 1) — the narrowing is the
            # annotation on ``ConnectionOperations.__init__``, and this is the one
            # place that knows which implementation satisfies it.
            connection_operations=connection_operations,
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
                # Tier 1 stores (ADR-0083 ruling 4, ADR-0102 §7).
                _as_async(grants.close),
                # And the read trail immediately after it, which is the one ordering
                # worth naming between the two: a driver holds both, and closing the
                # recorder first would leave a gated read able to open a source it
                # could no longer record (ADR-0185 §5). Nothing else constrains it —
                # no store reads this one and it reads none.
                _as_async(reads.close),
                # And the notification store, on the same ordering and for the
                # same reason (ADR-0130 §9). It is closed **before** the trace
                # store because it emits nothing into one; what it must outlive is
                # the drain of the reconsideration job, which the façade has
                # already waited on by the time any of these run.
                _as_async(notifications.close),
                # The connection store, on the same ordering as the other Tier 1
                # stores (ADR-0149 §3). Nothing constrains its position relative to
                # them: no other store reads it and it reads none, and the keyring
                # face beside it owns no connection to close.
                _as_async(connections.close),
                # And the outbox immediately after it, which is the one ordering
                # constraint between the two: a departure dismisses the record
                # *before* it removes the entry (ADR-0131 §3b), so an outbox still
                # able to run one after the record store had closed would be an
                # outbox able to remove an entry whose dismissal could not commit —
                # the one order §3b rules unsafe.
                _as_async(outbox.close),
                # And the trace store as the seventh (ADR-0119 §6). Closed **last
                # although it is now opened first**, which is the one place this
                # list deliberately departs from open order: the memory store and
                # the writer above emit into it (§8), so a trace written on the way
                # down has to find the connection still open. The façade drains
                # in-flight work before any of these run, so what this protects is
                # the tail of that drain rather than a race with it.
                _as_async(traces.close),
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
        # The **same** trace store again, narrowed a third way (ADR-0119 §7): a
        # ``TraceSink`` for `service`'s startup stamp, which appends one
        # ``CONFIGURATION`` trace and can no more walk the store than an emitter
        # inside the pipeline can. The two figures beside it are §9's effective
        # ``search`` limits, read off the constants this build tuned the two
        # collaborators with rather than off ``Settings``, which holds neither.
        return Composition(
            engine=engine,
            trace_sink=traces,
            retrieval_search_limit=RETRIEVAL_LIMIT,
            conflict_search_limit=CONFLICT_LIMIT + _CONFLICT_PROBE_OVERSHOOT,
        )
    except BaseException:
        # Close anything already opened before re-raising, so a failed build
        # returns no orphaned connection (ADR-0042 §2). Reverse order: last opened,
        # first closed.
        for close in reversed(opened):
            close()
        raise


def _build_connection_operations(
    directory: Path, *, opened: list[Callable[[], None]]
) -> tuple[SqliteConnectionStore, ConnectionOperations, Secrets]:
    """Open the connection store and wire the five operations over it (ADR-0151 §10).

    Extracted from :func:`build_composition` because the wiring is three
    constructions and one boundary that each want their reason written down, not
    because the pieces are reusable — nothing else builds one.

    **This is the wiring ADR-0153 §8's second precondition is about.** Making
    ``connect_account`` and ``reprovision_account`` reachable in an installation is
    what puts an ``INTEGRATION`` credential in a keyring, and §8 forbids that
    "before the routing §3 requires is present in ``ai_assistant/service/purge.py``"
    — otherwise an installation could acquire a credential its shipped delete act
    does not reach, which is the state ADR-0126 §6 forbids. Holding the order is the
    dispatcher's; what this docstring holds is *why*, so a lane reading this file
    later does not have to rediscover it.

    Args:
        directory: The resolved data directory. It is both where the store's file
            goes and the namespace ADR-0125 §2 binds the keyring face to.
        opened: The build's rollback list. The store registers itself here the
            statement after it opens, so a *later* construction failing closes it
            rather than leaking a connection out of a half-built engine (ADR-0042
            §2). Registering inside rather than at the call site is what makes that
            true of the window this function owns.

    Returns:
        The store, so the caller can join it to the engine's **ordered** shutdown —
        a different list from ``opened``, which is the failure path; the operations
        object the engine is wired with; and the one ``INTEGRATION``-scoped keyring
        face, **narrowed to** :class:`~ai_assistant.core.protocols.Secrets` by this
        annotation. The face is returned rather than rebuilt at the one other place
        that needs it, because the comment below is load-bearing: there is exactly
        one of these in the system, and a second construction would be a second
        object claiming the same guarantee. Narrowed on the way out because the
        remaining consumer is a transport, which reads and must not be able to
        delete (ADR-0125 §8).
    """
    # ADR-0149 §3's connection store: another connection-owning Tier 1 store — an
    # entry carries an account identity, which ADR-0149 §3 rules Tier 1 personal
    # data — under the same data directory and the same owner-only file mode as the
    # others. ADR-0083 ruling 4's exclusivity needs nothing new for it, on ADR-0102
    # §12's reasoning: it is inside the directory the instance lock already covers,
    # opened by this process, and closed in the same ordered shutdown.
    store = SqliteConnectionStore(path=directory / "connections.db")
    opened.append(store.close)
    # **The one ``INTEGRATION``-scoped keyring face in the system** (ADR-0149 §1).
    # It is constructed *here* and nowhere else: `tools` may not import
    # :mod:`ai_assistant.secret_store` at all, which ``lint-imports`` holds, and
    # `orchestration` holds no keyring face and acquires none by carrying a
    # credential across its surface (ADR-0125 §8, ADR-0151 §6).
    #
    # **Bound to the resolved data directory rather than to a setting read again**
    # (ADR-0125 §2), so two data directories on one machine share no entry — the
    # keyring is per OS user, not per data directory, and a QA hub overwriting the
    # owner's real credential is the failure that cannot be noticed. Constructing it
    # touches no keyring (ADR-0125 §7), so a deployment with no keyring still starts
    # and only a call that needs one fails.
    secrets = KeyringSecretStore(scope=SecretScope.INTEGRATION, installation=str(directory))
    # The provisioner ADR-0149 §1 puts in `tools`. **One object, two faces** —
    # ``ConnectionProvisioner`` here and ``ConnectionPurger`` for ADR-0126's offline
    # act — which is ADR-0153 §2's decision and the same structural-typing move the
    # grant store already makes: what a consumer may name is decided by the
    # annotation on its constructor rather than by a subset relation between two
    # Protocols.
    provisioner = KeyringConnectionProvisioner(store=store, secrets=secrets)
    # **The engine reaches it through the Protocol and never by an injected
    # concrete**, and `orchestration` imports no module of `tools` (golden rule 1).
    # The narrowing is the annotation on ``ConnectionOperations.__init__``; this is
    # the one place that knows which implementation satisfies it.
    return store, ConnectionOperations(provisioner=provisioner), secrets


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


def _reconciler_spec(settings: Settings) -> str:
    """The one ``"provider:model"`` spec the reconciler labels through (ADR-0159 §3).

    ``reconciler_model`` when the operator named one; otherwise ``default_model``.
    The same shape :func:`_observer_spec` has, and the same argument: the default
    names no provider the operator did not already configure, so ADR-0004 §2's
    property cannot be breached by leaving it unset, while the setting still makes
    the choice *nameable and separable* — an operator who wants two stored beliefs
    weighed by a smaller or locally-hosted model changes one value and does not
    touch the route their answers come from.

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


def _build_reconciler_provider(settings: Settings, spec: str) -> RetryingProvider:
    """Build the reconciler's model seam: **retry, and no routing** (ADR-0159 §3).

    The observer's shape (:func:`_build_observer_provider`), reached by the same
    argument. Fallback's cost is that *more providers may see a given prompt*, and a
    reconciler's prompt is two of the user's own stored beliefs. What it would buy
    is reliability, and reliability buys nothing here: ADR-0159 §3's never-raises
    clause converts a failed request into an unlabelled member, and §6 ratifies the
    ruling that follows — ADR-0121 §1's certain agreements plus ``ACCEPT``, which is
    strictly better than the rule ADR-0159 replaced. So a second recipient is a cost
    with no benefit, which is exactly the trade ADR-0004 §7's minimisation rule
    settles.

    **Retry is not fallback**: it re-sends to the *same* provider, so it widens no
    recipient set, and the route requires its own credential (ADR-0013 §6) — nothing
    stands behind it, so a provider this deployment cannot authenticate to leaves
    the members unlabelled rather than quietly diverting the beliefs somewhere it
    can.

    Args:
        settings: Loaded application settings — the resilience knobs every other
            route gets, because how patient this deployment is is not a property of
            which vendor answered.
        spec: The reconciler's ``"provider:model"`` spec (:func:`_reconciler_spec`).

    Returns:
        The provider the reconciler labels through.

    Raises:
        ConfigurationError: If ``spec`` names a vendor unknown to pydantic-ai or
            whose optional package is not installed — checked here for ADR-0062 §2's
            reason, so an operator learns at startup rather than on the first ingest
            that would have reconciled. Checked even when it repeats
            ``default_model``: the check is cheap, and a helper trusting a caller to
            have checked already would break the day the two stop coinciding.
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


def _build_email_reader(settings: Settings) -> EmailReader | None:
    """Construct the configured email reader, or ``None`` if there is no store.

    :func:`_build_calendar_reader`'s shape for the **second** source (ADR-0140,
    ADR-0142 §2), and every sentence of that function's docstring about why this
    layer may import ``ai_assistant.readers`` at all, and about why ``None`` is a
    consent decision rather than a technical one, holds here unchanged. What is
    worth stating separately is what differs.

    **Keyed on ``email_source_path`` and on nothing else.** ADR-0142 §2 is marked:
    "A source's ingestion stage is constructed by the composition root when **that
    source's** path field is configured … Neither decision reads any other source's
    fields." So this function consults no calendar field and no interval — a store
    configured with no ``email_reader_interval`` is the legal, meaningful state in
    which the reader exists, the facet is available to a turn, and no scheduler row
    is armed.

    **No timezone parameter, unlike the calendar's**, and the absence is
    ``EmailReader``'s own consequence rather than an omission here: every instant it
    reads is already an instant, because ADR-0140 §5's delivery header carries a
    determinate offset and a ``Date`` that resolves to none is skipped. There is no
    floating wall time for a zone to localise, so there is no second timezone source
    for this layer to decline to invent.

    **Five figures rather than the calendar's eight** (ADR-0140 §12), each already
    refused at load by ``Settings`` and stated again at the constructor because it
    is a second seam a test or a second composition root reaches directly. The one
    that differs in *kind* is ``email_window_past``, whose lower bound is open where
    ``calendar_window_past``'s is closed: a window of zero width is a reader that
    reads nothing while reporting health.

    The clock is left at the reader's own default, for the calendar reader's reason:
    nothing at this layer has a second clock to hand it.

    Args:
        settings: Loaded application settings — the store path and ADR-0140 §12's
            five figures.

    Returns:
        The reader, or ``None`` when ``email_source_path`` is unset.

    Raises:
        ValueError: If a figure is outside its range or the path is not absolute.
            Unreachable through ``Settings``, which refuses both at load; it is the
            constructor's own guard on the seam a caller could reach directly.
    """
    if settings.email_source_path is None:
        return None
    return EmailReader(
        settings.email_source_path,
        window_past=settings.email_window_past,
        max_messages=settings.email_max_messages,
        max_bytes=settings.email_max_bytes,
        read_timeout=settings.email_read_timeout,
        max_content_bytes=settings.email_max_content_bytes,
    )


def _build_transcriber() -> SpeechTranscriber:
    """Construct the on-device speech recogniser (ADR-0200 §1, §5).

    ``MoonshineTranscriber`` is imported **here, lazily, not at module scope**, for
    ``FastEmbedEmbedder``'s reason: the module pulls in ``sherpa_onnx`` and a second
    ONNX runtime, and it is deliberately not re-exported from ``ai_assistant.models``
    so that importing that package stays cheap. Only the resident hub builds a
    composition, so only the hub pays it.

    Construction stays **offline and cheap**: nothing is loaded here, and the model
    files are read on the first ``transcribe``, inside the worker that call owns —
    which is what puts the cold load inside the deadline the caller wraps this in
    rather than outside it (ADR-0118 §4).

    **Unbounded, and it never leaves this function that way.** The one caller wraps
    it in :class:`~ai_assistant.models.bounded_speech.BoundedSpeechTranscriber`
    immediately, which is where ADR-0200 §1's deadline lives.

    Returns:
        The transcriber, before it is bounded.
    """
    from ai_assistant.models.moonshine_transcriber import (  # noqa: PLC0415 — lazy: pulls in sherpa_onnx
        MoonshineTranscriber,
    )

    return MoonshineTranscriber()


def _build_synthesizer() -> SpeechSynthesizer:
    """Construct the on-device speech synthesiser (ADR-0200 §1, §5).

    :func:`_build_transcriber`'s sibling, imported lazily and bounded by its caller
    for the same reasons. See that function; every clause of it binds here.

    Returns:
        The synthesizer, before it is bounded.
    """
    from ai_assistant.models.supertonic_synthesizer import (  # noqa: PLC0415 — lazy: pulls in sherpa_onnx
        SupertonicSynthesizer,
    )

    return SupertonicSynthesizer()


def _build_embedder(settings: Settings) -> Embedder:
    """Construct the configured :class:`Embedder`, bounded, before disk is touched.

    **The composition root wires no unbounded ``Embedder`` into anything the hub
    can reach** (ADR-0118 §2). This function returns the wrapped embedder for every
    :class:`EmbedderKind`, and it is the single wiring point every consumer goes
    through — :func:`build_engine`'s memory store and :func:`build_reembedder`'s
    migration alike — so the seam is bounded once rather than at each caller.

    The bound is a property of what is *wired*, not of the ``Embedder`` contract,
    and that is why ADR-0118 §9 writes no text on the Protocol: a Protocol cannot
    compel a composition root to wire the implementation that honours it, so the
    clause is stated over this function instead.

    :class:`~ai_assistant.models.bounded_embedder.BoundedEmbedder` is applied to
    both modes rather than only to the on-device one. ``HashingEmbedder`` is
    bounded by construction under ADR-0118 §1 and the deadline is inert over it —
    wrapping it anyway costs one delegating call and keeps the guarantee true of
    the *seam* rather than of one branch, which is what makes a future ``Embedder``
    bounded on the day it is wired.

    Args:
        settings: Loaded application settings — ``embedder`` selects the mode and
            ``embedding_timeout_seconds`` the deadline.

    Returns:
        The bounded embedder the memory store embeds and retrieves with.

    Raises:
        ConfigurationError: If the configured embedder cannot be prepared; see
            :func:`_build_configured_embedder` for the cases.
    """
    return BoundedEmbedder.from_settings(_build_configured_embedder(settings), settings)


def _build_configured_embedder(settings: Settings) -> Embedder:
    """Construct the configured :class:`Embedder`, before any resource is opened.

    Reached only through :func:`_build_embedder`, which bounds what this returns.
    Nothing else may call it: an unbounded embedder handed to a consumer is exactly
    what ADR-0118 §2's second clause forbids.

    ADR-0006 §2's firm decision is that **on-device embedding is the default**:
    memory content is Tier-1 personal data (ADR-0004) and must not leave the device
    merely to be indexed. So ``settings.embedder`` defaults to the vendored
    on-device model (:class:`FastEmbedEmbedder`, ADR-0024), and this is where that
    ratified default is finally honoured by the running app — the composition root
    had wired the non-semantic :class:`HashingEmbedder` unconditionally, leaving
    production "semantic" recall not actually semantic.

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


def _configured_calendar_location(settings: Settings) -> str | None:
    """Where this deployment configured its **calendar** to read from (ADR-0102 §6).

    A plain ``str`` and not a ``Path``, because §6's hazard is precisely a pathname
    with no UTF-8 encoding: Linux pathnames are bytes and Python surfaces an
    undecodable one through ``surrogateescape``, so ``str(path)`` can hold a lone
    surrogate. The string is what has to be judged, and judging it is the grant
    operations' job rather than this layer's — here it is only read.

    **This function said "one source, and the day there is a second this stops
    being a function of ``Settings`` alone" — that day arrived and this is the
    answer.** The location is now per source rather than per deployment: this reads
    the calendar's field, :func:`_configured_email_location` reads email's, and
    :func:`_held_sources` pairs each reader with its own. What is *not* answered is
    ADR-0093 §11's registry, in which a location becomes a property of a registered
    source rather than of a named field — ADR-0142 §8 declines to fire it at the
    second source and ADR-0102 §10's normative clause still owes that lane a
    re-derivation of the enumeration's worst case.
    """
    if settings.calendar_reader_path is None:
        return None
    return str(settings.calendar_reader_path)


def _configured_email_location(settings: Settings) -> str | None:
    """Where this deployment configured its **mail store** to be (ADR-0102 §6).

    :func:`_configured_calendar_location`'s rule on ADR-0140 §12's field. The plain
    ``str`` is for the same reason and the judging is the same layer's.

    **Read off ``Settings`` rather than off the reader**, which is the one place
    this pair departs from the identity beside it: ``Reader`` declares a ``name``
    and declares no location at all, so the identity comes from the object and the
    location cannot. That asymmetry is ADR-0102 §7's and is why the two are supplied
    together rather than derived from one another.
    """
    if settings.email_source_path is None:
        return None
    return str(settings.email_source_path)


def _held_sources(
    settings: Settings,
    *,
    calendar: Sequence[Reader | None],
    email: Sequence[Reader | None],
) -> list[HeldSource]:
    """Pair every reader this root built with **its own** source's location.

    ADR-0102 §7's input to :class:`~ai_assistant.orchestration.grants.GrantOperations`,
    assembled here because this is the one layer that knows both halves: the
    identity is read off the reader object, and the location off the ``Settings``
    field that configured *that* source.

    **A sequence rather than a mapping, and duplicates are deliberate** (ADR-0102
    §7). Each of a source's consumers holds its own reader instance (ADR-0096 §5),
    so one source contributes as many rows as it has consumers, all declaring one
    identity. §7 rules that two readers declaring one identity at differing
    locations is a configuration error the engine does not build through, and a
    mapping would deduplicate that conflict away unseen — so the repetition is what
    makes the check possible rather than noise the check has to tolerate.

    **Grouped by source rather than flattened**, which is what keeps the pairing
    honest. A single comprehension over every reader would need one location
    expression for all of them, which is exactly the shape that was correct while
    every reader was a calendar's and silently wrong the moment a second source
    arrived.

    Args:
        settings: Where each source's configured location comes from.
        calendar: The calendar readers this root built, ``None`` for each consumer
            of an unconfigured source.
        email: The email readers, on the same terms.

    Returns:
        One :class:`~ai_assistant.orchestration.grants.HeldSource` per reader
        actually built, in source order. Empty when no source is configured, which
        is the shipping default and the state in which ``grantable_sources`` offers
        nothing (ADR-0093 §7, ADR-0140 §13).
    """
    return [
        HeldSource(reader.name, location=location)
        for readers, location in (
            (calendar, _configured_calendar_location(settings)),
            (email, _configured_email_location(settings)),
        )
        for reader in readers
        if reader is not None
    ]


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

#: The census's own defaults and its ``k`` ceiling, re-exported so its entry
#: point can put them in ``--help`` and refuse a bad argument *at the argument*,
#: without importing ``memory`` (ADR-0129 §5, ADR-0083 §8). Restating the numbers
#: there would be a second definition that could drift from the one the mechanism
#: applies; passing them through the layer already allowed to name both sides
#: costs an import edge that exists anyway.
STORE_HEALTH_DEFAULT_SAMPLE: Final = DEFAULT_SAMPLE
STORE_HEALTH_DEFAULT_K: Final = DEFAULT_K
STORE_HEALTH_MAX_K: Final = MAX_K


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


def build_measure_reader(settings: Settings, *, data_dir: Path | None = None) -> MeasureReader:
    """Point leg 8's offline measure report at this deployment's trace store.

    The composition root's third function, and the thinnest of them, because
    ADR-0120 §9 gives the reporting tool nothing to be wired *to*: it opens the
    trace store and no other store (§10), it reads through ``TraceStore.walk``
    alone (§9), and it consults no model, no clock and no policy. What this
    function supplies is the one fact the mechanism may not go and get for
    itself — where the data directory is.

    **It is here rather than in the entry point** for the reason
    :func:`build_reembedder` is: ``lint-imports``' "nothing imports the evaluation
    package" contract forbids ``service`` the direct edge, and the entry point has
    to be in ``service`` because that is where the instance lock lives (ADR-0104
    §5, transferred by ADR-0120 §9). So the tool arrives at its mechanism the same
    indirect way the re-embedder does, through this layer.

    **Nothing is opened here.** A reader that opened the database on construction
    would create an empty one as a side effect of a deployment that has never run
    the hub asking whether it has any traces, and the honest answer to that is
    ADR-0120 §8's empty-stream statement rather than a new file.

    Args:
        settings: Loaded application settings — ``data_dir`` locates the store.
        data_dir: Overrides ``settings.data_dir`` when given, exactly as
            :func:`build_engine`'s keyword does (ADR-0083 §2).

    Returns:
        A reader ready to report over ``<data_dir>/traces.db``.
    """
    directory = data_dir if data_dir is not None else settings.data_dir
    return MeasureReader(store=directory / "traces.db")


def build_store_health_reader(
    settings: Settings, *, data_dir: Path | None = None
) -> StoreHealthReader:
    """Point ADR-0129's store-health census at this deployment's memory store.

    The composition root's fourth function, and thin for the same reason the
    third is: ADR-0129 §5 gives the census nothing to be wired *to*. It opens the
    memory store and no other store (§4), embeds nothing and constructs no
    ``Embedder`` (§2), and consults no model and no policy — so the one fact it
    may not go and get for itself is where the data directory is.

    **It is here rather than in the entry point** for the reason
    :func:`build_reembedder` is, and §5 states it: the mechanism lives in
    ``memory/``, ``lint-imports``' "nothing imports the service" contract means
    the entry point has to *be* in ``service`` because that is where the instance
    lock lives, and ADR-0083 §8 keeps that entry point free of subsystem imports.
    So the census arrives at its mechanism the same indirect way the re-embedder
    and the measure report do.

    **The clock is not a parameter here**, and that is ADR-0129 §1 rather than an
    omission: ``T`` is the instant the tool reads its own clock, "not an operator
    parameter: no option, argument or setting moves it". A test fixes it by
    injecting one into :class:`~ai_assistant.memory.health.StoreHealthReader`
    directly, which is the corpus's standing pattern; there is nothing for this
    layer to choose.

    **Nothing is opened here**, exactly as in :func:`build_measure_reader`: a
    reader that opened the database on construction would create an empty one as
    a side effect of a deployment that has never run the hub asking what is in it.

    Args:
        settings: Loaded application settings — ``data_dir`` locates the store.
        data_dir: Overrides ``settings.data_dir`` when given, exactly as
            :func:`build_engine`'s keyword does (ADR-0083 §2).

    Returns:
        A reader ready to take a census of ``<data_dir>/memory.db``.
    """
    directory = data_dir if data_dir is not None else settings.data_dir
    return StoreHealthReader(store=directory / "memory.db")


@dataclass(frozen=True, slots=True)
class OpenedConnections:
    """A :class:`ConnectionPurger` over an opened store, and the close it owes.

    Returned by :func:`build_connection_purger` and consumed by the offline delete
    act. The pair is one value rather than two returns because ADR-0153 §3 makes
    the close an obligation of the *act* — "whatever the act opens in order to
    reach the purge — the connection store, and the objects the composition root
    builds around it — is **closed before the first destruction begins**" — and a
    builder that handed back only the purger would leave the caller no way to
    discharge it, since :class:`ConnectionPurger` carries two members and neither
    is a close (ADR-0153 §2).

    **The purger is typed as the narrow face and never as the concrete class**,
    the same narrowing :class:`Composition` gives its ``TraceSink``. The holder is
    an offline, irreversible, destructive tool; handing it
    ``ConnectionProvisioner`` would let the one component whose purpose is
    destroying an installation also create a connection in one (ADR-0153 §2).

    Attributes:
        purger: The two-member seam ADR-0153 §2 places, satisfied here by the
            connection provisioner in `tools/` — its primary production
            implementation, and the only one.
        close: Releases the connection store this build opened. Synchronous, and
            idempotent because the store's own close is.
    """

    purger: ConnectionPurger
    close: Callable[[], None]


def build_connection_purger(
    settings: Settings, *, data_dir: Path | None = None
) -> OpenedConnections:
    """Wire the offline delete act to ADR-0149 §8's purge (ADR-0153 §2, §6).

    The composition root's fifth function, and it is here for the reason the
    second, third and fourth are, stated once more because this one has a second
    boundary to cross. ``lint-imports``' "no subsystem imports the secret store"
    contract names ``ai_assistant.service`` in its source list, so the entry point
    **cannot** construct the ``INTEGRATION``-scoped keyring face this provisioner
    needs; and ADR-0153 §6's fourth clause puts the rest of it beyond argument —
    `service` "imports no subsystem directly", reaches
    :class:`~ai_assistant.core.protocols.ConnectionPurger` as a Protocol in
    ``core``, and "receives the implementation by injection from `app`". So the
    delete act arrives at its mechanism the same indirect way the re-embedder, the
    measure report and the store-health census do.

    **The store is opened here, unlike in the three functions above**, and the
    difference is the mechanism rather than a change of posture: a connection
    store that is not open cannot answer :meth:`ConnectionPurger.connected`, and
    ADR-0153 §3 requires that answer *before* the owner's confirmation. The cost
    is that a deployment which never connected an account gets a
    ``connections.db`` created by this call — which is the same file the hub
    creates on its next start (ADR-0149 §3), destroyed by this very act on the
    path that completes, and left behind only where the act refuses after the
    preflights. It is not, in other words, "a file left behind that the
    installation never had" in ADR-0126 §7's sense.

    **Nothing about the keyring is touched here.** ADR-0125 §7: "Constructing an
    implementation touches no keyring. The backend is resolved on the first call."
    An installation whose store names no slot therefore makes no keyring call at
    any point of the act, which is what keeps a headless box's delete right
    intact (ADR-0153 §4).

    Two facts are chosen here and the act can name neither (ADR-0125 §2): the
    scope, so the object handed out reaches only ``INTEGRATION`` entries, and the
    installation namespace — the data directory, injected rather than read by the
    store itself, exactly as ``interfaces/cli.py``'s ``_enrolment_secrets``
    injects it for the device's own scope.

    Args:
        settings: Loaded application settings — ``data_dir`` locates the store and
            names the installation.
        data_dir: Overrides ``settings.data_dir`` when given, exactly as
            :func:`build_engine`'s keyword does (ADR-0083 §2).

    Returns:
        The purger, and the close that releases everything opened to reach it.

    Raises:
        ConnectionStoreError: If ``<data_dir>/connections.db`` cannot be opened or
            initialised. ADR-0153 §4's third clause governs what the act does with
            that: it destroys nothing and reports, because an unreadable index is
            the case in which proceeding guarantees the unrepairable state rather
            than risking it.
    """
    directory = data_dir if data_dir is not None else settings.data_dir
    store = SqliteConnectionStore(path=directory / "connections.db")
    purger = KeyringConnectionProvisioner(
        store=store,
        secrets=KeyringSecretStore(scope=SecretScope.INTEGRATION, installation=str(directory)),
    )
    return OpenedConnections(purger=purger, close=store.close)
