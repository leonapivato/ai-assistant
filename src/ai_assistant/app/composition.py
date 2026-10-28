"""Construct the production subsystems and wire them into an engine (ADR-0042 §2).

:func:`build_composition` is the composition root's one build. It names every
concrete implementation, discharges the wiring obligations no type can express,
owns the connection-owning resources it opens, and hands the façade an ordered
shutdown path — everything ADR-0042 §2 requires of this layer.

:func:`build_engine` is that build read down to its engine, and it stays the
entry point for every caller that needs nothing else. What the second return
value exists for is ADR-0119 §9's startup stamp: the configuration trace records
the **effective** ``search`` limit of each cardinality control a startup figure can
describe, and §9 is explicit that "the figure to record is the one the composition
root actually produced", because the control is not a ``Settings`` field.
:class:`Composition` is that figure leaving the one layer that knows it, beside the
``TraceSink`` the stamp writes through. Recall's limit depends on each activation's
data and is not stamped (ADR-0319 §4).
"""

from __future__ import annotations

import errno
import hashlib
import os
import stat
import uuid
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from importlib.resources import files
from typing import TYPE_CHECKING, Final, assert_never

import structlog

from ai_assistant.core.config import EmbedderKind
from ai_assistant.core.errors import ConfigurationError, ModelError
from ai_assistant.core.prompts import PROMPT_OVERRIDE_DIRECTORY, PromptOrigin, PromptTemplate
from ai_assistant.core.types import (
    DELIVERY_RESERVE_BYTES,
    OWNER_PERSON_ID,
    CanonicalDestination,
    DestinationProtocol,
    LabelBounds,
    SecretScope,
)
from ai_assistant.evaluation import FileDiagnosticRecord, MeasureReader, SqliteTraceStore
from ai_assistant.memory import (
    DefaultMemoryPolicy,
    DefaultNotificationPolicy,
    MemoryIngestor,
    ModelBackedReconciler,
    SqliteMemoryStore,
    SqliteNotificationOutbox,
    SqliteNotificationStore,
    SqliteStoryStore,
    SqliteTelegramIntakeRecord,
)
from ai_assistant.memory._reconciler import MEMORY_RECONCILER_PROMPT
from ai_assistant.memory.conversation_store import SqliteConversationStore
from ai_assistant.memory.health import DEFAULT_K, DEFAULT_SAMPLE, MAX_K, StoreHealthReader
from ai_assistant.memory.notification_store import check_notification_tuning
from ai_assistant.memory.person_model_store import SqlitePersonModelStore
from ai_assistant.memory.reembed import Reembedder
from ai_assistant.models import (
    BoundedEmbedder,
    BoundedSpeechSynthesizer,
    BoundedSpeechTranscriber,
    HashingEmbedder,
    PydanticAIProvider,
    PydanticAIToolCallingCompleter,
    RetryingProvider,
    Route,
    RoutingProvider,
    ensure_credential_available,
    ensure_vendor_available,
)
from ai_assistant.models.follow_up import FOLLOW_UP_PROMPT, FollowUpAsker
from ai_assistant.models.retry import RetryPolicy
from ai_assistant.orchestration import (
    ConnectionOperations,
    ConversationLifecycle,
    Engine,
    GrantOperations,
    HeldSource,
    MemoryWriteStage,
    NotificationWriteStage,
    UpcomingEventStage,
)
from ai_assistant.orchestration.acting import ActingStage, OwnRecordsByCapability
from ai_assistant.orchestration.authorizer import AuthorizingStage
from ai_assistant.orchestration.chat import ChatWriter
from ai_assistant.orchestration.digesting import DIGESTING_PROMPT
from ai_assistant.orchestration.lookups import (
    LOOK_UP_CAPABILITIES,
    LOOK_UP_LABEL_ARGUMENTS,
    LOOK_UPS,
    LookUps,
)
from ai_assistant.orchestration.matters_pass import MATTERS_PASS_PROMPT, MattersPass
from ai_assistant.orchestration.observer import Observer, ObserverLimits
from ai_assistant.orchestration.observer.prompts import (
    OBSERVER_FRAMING_PROMPT,
    OBSERVER_PLACEMENT_PROMPT,
    OBSERVER_SCOUT_PROMPT,
)
from ai_assistant.orchestration.payloads import ENVELOPE_RESERVE_BYTES
from ai_assistant.orchestration.person_block import (
    KEPT_IN_MIND_CHARS,
    PLANNING_SUGGESTIONS,
    PersonBlocks,
)
from ai_assistant.orchestration.phase_path import PhasePath, PhaseTools, StoryReads
from ai_assistant.orchestration.planning import PLANNING_PROMPT
from ai_assistant.orchestration.recall import RecallStage
from ai_assistant.orchestration.reliance import NOTE_RELIANCE, RELIANCE_LABEL_ARGUMENTS
from ai_assistant.orchestration.remembering import (
    CANDIDATE_LABEL_ARGUMENTS,
    REMEMBER_CANDIDATE,
    REMEMBER_CAPABILITY,
    CandidateCalls,
)
from ai_assistant.orchestration.selection import Preference
from ai_assistant.orchestration.story_calls import (
    STORY_CALL_CAPABILITIES,
    STORY_CALLS,
    STORY_LABEL_ARGUMENTS,
    StoryCalls,
)
from ai_assistant.orchestration.story_links import StoryCandidates, StoryLinksStage
from ai_assistant.orchestration.story_tidy_up import STORY_TIDY_UP_PROMPT, StoryTidyUp
from ai_assistant.orchestration.task_manager import TaskManagerLimits, TaskSchedulerSeams
from ai_assistant.orchestration.telegram import TelegramLineSeams
from ai_assistant.orchestration.understanding import (
    UNDERSTANDING_PROMPT,
    RecentEpisodes,
    UnderstandingStage,
    WindowsStage,
)
from ai_assistant.permissions import (
    ConfiguredForecastDestination,
    ConfiguredSearchDestination,
    SqliteAuditTrail,
    SqliteSourceGrantStore,
    SqliteSourceReadTrail,
    ThresholdActionPolicy,
)
from ai_assistant.permissions.spend import SpendConfiguration
from ai_assistant.planning import SqlitePlanStore
from ai_assistant.readers import CalendarReader
from ai_assistant.secret_store import KeyringSecretStore
from ai_assistant.tools import (
    build_default_registry,
    build_forecast_integration,
    build_send_email_integration,
    build_simulated_booking_integration,
    build_web_search_integration,
    egress_registrations,
)
from ai_assistant.tools.booking import BOOKING_ACT, BOOKING_AVAILABILITY
from ai_assistant.tools.booking import ORIGIN_ARGUMENT as BOOKING_ORIGIN_ARGUMENT
from ai_assistant.tools.connection_store import SqliteConnectionStore
from ai_assistant.tools.destinations import DestinationCanonicalisationError
from ai_assistant.tools.egress import (
    HttpsExchange,
    HttpsTelegramBotClient,
    StreamOutboundTransport,
    TelegramRelay,
    TelegramRelayError,
)
from ai_assistant.tools.egress_binder import EgressBindingSeam, canonical_destination
from ai_assistant.tools.forecast import FORECAST_READ_ID
from ai_assistant.tools.provisioning import KeyringConnectionProvisioner
from ai_assistant.tools.web_search import QUERY_ARGUMENT as SEARCH_QUERY_ARGUMENT
from ai_assistant.tools.web_search import WEB_SEARCH_ID

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping, Sequence
    from pathlib import Path
    from zoneinfo import ZoneInfo

    from ai_assistant.core.config import Settings
    from ai_assistant.core.prompts import PromptDeclaration
    from ai_assistant.core.protocols import (
        AuditTrail,
        ConnectionPurger,
        ConversationStore,
        DiagnosticSink,
        EgressBinder,
        Embedder,
        Forecaster,
        MemoryStore,
        ModelProvider,
        NotificationPolicy,
        OutboundTransport,
        PlanStore,
        Reader,
        Secrets,
        SpeechSynthesizer,
        SpeechTranscriber,
        StoryStore,
        TraceSink,
        WebSearcher,
    )
    from ai_assistant.tools.registry import InMemoryToolRegistry


_log = structlog.get_logger(__name__)

#: The prompts whose instruction is a template (ADR-0334 §2), each declared in the
#: module that sends it. A lane that moves a prompt into its template adds its
#: declaration here and hands the module ``prompts[<declaration>.name]``; nothing else
#: in this layer changes. An override is read only for a prompt listed here, so a file
#: naming a prompt not yet moved names no prompt and refuses the start (§5:1). The
#: follow-up's (ADR-0337 §6:1) is listed so its override is read as any prompt's, and the
#: hub-side asker is handed it where ``follow_up_question`` is on (§8:5).
PROMPTS: Final[tuple[PromptDeclaration, ...]] = (
    UNDERSTANDING_PROMPT,
    PLANNING_PROMPT,
    DIGESTING_PROMPT,
    STORY_TIDY_UP_PROMPT,
    MATTERS_PASS_PROMPT,
    OBSERVER_SCOUT_PROMPT,
    OBSERVER_FRAMING_PROMPT,
    OBSERVER_PLACEMENT_PROMPT,
    MEMORY_RECONCILER_PROMPT,
    FOLLOW_UP_PROMPT,
)

#: What a template file read from the override directory may not be: writable by
#: anyone but its owner (ADR-0334 §5:1).
_WRITABLE_BY_OTHERS: Final = stat.S_IWGRP | stat.S_IWOTH

#: How much of an override one read takes.
_READ_CHUNK: Final = 64 * 1024

#: What this layer tunes :class:`MemoryIngestor`'s conflict ceiling to, **passed
#: explicitly rather than left to the constructor's default** (ADR-0119 §9): the
#: configuration stamp records the effective ``search`` limit it produces, and the
#: honest figure is the one this build used, not one restated beside a default this
#: module does not control.
CONFLICT_LIMIT: Final = 100

#: The composition root's numbers for a memory's situation labels (ADR-0345 §7:3,
#: §7:5): at most eight labels on one memory, each at most eighty characters, and a new
#: label within a cosine distance of 0.1 of one the memory already carries is a
#: near-duplicate and not added. **Provisional**: no producer writes a label until the
#: observer's framing does (ADR-0346 §9), and the distance is to be measured on the
#: labels it writes, against the embedder wired, as recall's threshold was.
LABEL_BOUNDS: Final = LabelBounds(max_labels=8, max_chars=80, min_distance=0.1)

#: How many episodes the understanding stage's **episode window** holds (ADR-0276 §4),
#: on ADR-0158 §5's rule: a cardinality control whose
#: authority is measurement, so a composition-root constant and never a
#: :class:`~ai_assistant.core.config.Settings` field. Ten by recency is the owner's
#: first guess with no measurement behind it (#2544, 2026-09-22), and the exit run is
#: the first evidence. It bounds the selector wired below; episodes of the channel
#: window are rendered there once and are not counted toward it (§3).
#:
#: **The method is the selector's, not this number's.** A different bound, a
#: per-channel mix, a size budget or a different order is a different selector wired
#: in :func:`build_composition`, which amends no clause of ADR-0276 so long as it
#: keeps §4's walls — bounded, cross-channel, eligibility-blind, disclosure-filtered,
#: model-free and relevance-free.
UNDERSTANDING_EPISODE_LIMIT: Final = 10

#: How many characters of each episode's input and response the episode window renders
#: (ADR-0276 §4). The cut is disclosed in the rendering; the channel window has no
#: ceiling of that decision's own (§3) and is not cut by it.
UNDERSTANDING_EXCERPT_CHARS: Final = 2000

#: How many understanding versions one processing record retains (ADR-0276 §7):
#: version 1 and the latest ``UNDERSTANDING_VERSION_LIMIT - 1``, with the rest counted
#: in ``understanding_elided``. One producer ships, so no record reaches it yet; the
#: bound is what keeps a record's size a function of the activation rather than of how
#: many stages a later redesign runs.
UNDERSTANDING_VERSION_LIMIT: Final = 8

#: How many candidate stories understanding is shown at most (ADR-0300 §6:1): first the
#: stories the episode window's episodes belong to, then recall's. The decision's
#: initial value, unmeasured; a story already a candidate is not repeated.
UNDERSTANDING_STORY_CANDIDATES: Final = 5

#: How many of a story's notes its summary view lists, newest first, before it counts the
#: rest (ADR-0303 §10:2). The view lists them so the owner can name them in a command,
#: so it is sized to hold every note of an ordinary matter: twenty at their bound of
#: 2,000 characters is about 40,000 characters, beside a summary capped at 8,000, well
#: inside a frame's payload limit.
STORY_SUMMARY_VIEW_NOTES: Final = 20

#: How much of each candidate a short view shows (ADR-0300 §6:2), chosen here as §6:2
#: and §3:17 have the building lane choose them. A short view is for recognising the
#: matter, not for its account, which planning is given whole (§8). **Lines: 3** — the
#: summary's first line says what the matter is (§3:6), and two more carry where it is
#: going; with five candidates that keeps the section at fifteen lines, each within
#: ``STORY_NOTE_MAX_CHARS``. **Notes: 2** and **episodes: 2**, §6:2's ceilings taken
#: whole: a pending note is what the summary has not folded in yet, so on a summary not
#: tidied lately it is the freshest thing said about the matter; and the two latest
#: meanings show what the matter was doing last, which is what an input continuing it
#: would follow on from.
STORY_SHORT_VIEW_LINES: Final = 3
STORY_SHORT_VIEW_NOTES: Final = 2
STORY_SHORT_VIEW_EPISODES: Final = 2

#: How many characters of each episode's input and reply a tidy-up renders (ADR-0300
#: §5:3): the episode excerpt every other model-facing rendering of an episode is
#: bounded by, ``UNDERSTANDING_EXCERPT_CHARS``, which is also what a note's own bound,
#: ``STORY_NOTE_MAX_CHARS``, was chosen from.
STORY_TIDY_UP_EXCERPT_CHARS: Final = UNDERSTANDING_EXCERPT_CHARS

#: How many other stories a tidy-up shows for its *like another story* flag
#: (ADR-0303 §5:7), counted together: the stories the episodes it reads also belong
#: to, then the stories of the episodes its search of the memory store finds, each by
#: its summary's first line. Understanding's candidate count, so a tidy-up can name any
#: story that understanding could have linked the same episode into beside this one.
STORY_TIDY_UP_OTHER_STORIES: Final = UNDERSTANDING_STORY_CANDIDATES

#: How long one tidy-up may take, its one completion included (ADR-0300 §5). Nobody
#: waits for a run, so the bound is not latency: it is what frees the story for a
#: later run when a completion hangs, since at most one runs on a story at a time.
#: The scheduler's per-run budget is five minutes for a whole background run; a
#: tidy-up is one summary, so two.
STORY_TIDY_UP_BUDGET: Final = timedelta(minutes=2)

#: How many decisions recorded for its story a tidy-up shows, newest first (ADR-0302
#: §6:1). Its other-story count, so a decision on a pair with each story it can name
#: fits, and a story with fewer decisions than that shows them all.
STORY_TIDY_UP_DECISIONS: Final = STORY_TIDY_UP_OTHER_STORIES

#: The matters pass's bounds (ADR-0300 §9:3, ADR-0302 §5), chosen here as §5:4 has the
#: building lane choose them; none is measured yet, and the test hub is where to.
#:
#: **Decisions shown: 5** (§5:4), the tidy-up's figure: those on the same stories come
#: first, and a pair of stories decided on more than a few times is the case the bound
#: is there to cut. **Completions per run: 10**, so a backlog after a quiet spell
#: drains over a few runs rather than in one long one; a flag decided by rule needs no
#: completion and is not counted. **Episodes per story: 6**, its latest links, so a
#: split or a move can name what came to the story most recently, which is where a
#: summary starts to look like two matters. **Notes per story: 5**, its newest, pending or
#: not, each under a label a split or a move may name so that it goes too (ADR-0303
#: §8:7), on the episodes' reasoning: the notes about the matter that moves are mostly
#: the recent ones. **Excerpt: 1,000 characters**, half the
#: tidy-up's, because a completion here is shown two or more stories' episodes and
#: decides what they are about rather than folding in what was settled. A run's time
#: is bounded by ``scheduler_run_budget``, and it runs at ``consolidation_interval``.
MATTERS_PASS_DECISIONS: Final = 5
MATTERS_PASS_FLAGS_PER_RUN: Final = 10
MATTERS_PASS_EPISODES: Final = 6
MATTERS_PASS_NOTES: Final = 5
MATTERS_PASS_EXCERPT_CHARS: Final = 1000

#: How many long-term memories recall keeps for one activation at most (ADR-0281 §3).
#: Thin on purpose: recall leaves the story-following and the understanding-cued
#: search to later sources, which add to the same record under the type's ceiling.
RECALL_ITEM_LIMIT: Final = 3

#: Recall's own budget, before the pass's deadline caps it (ADR-0281 §5). A recall
#: that outruns it is ``timed_out`` and understanding runs without it.
RECALL_BUDGET: Final = timedelta(seconds=2)

#: The recall threshold for each embedder (ADR-0281 §3): a score's scale belongs to
#: its embedder, so the value is chosen beside the one wired, never shared.
#:
#: **The on-device value is measured** (#2601), as ADR-0281 §3 asks:
#: ``scripts/measure_recall_threshold.py`` scores content-free replies ("yes", "ok",
#: "same as before" and their kind) and paraphrases of stored facts and episodes
#: against a store over the vendored ``bge-small-en-v1.5``. The best score any
#: content-free reply gave any record was 0.566, and the lowest a paraphrase gave its
#: own record was 0.613, so 0.58 sits in that gap, below its middle, leaning towards
#: keeping a borderline memory rather than missing a real one. The PR that set it
#: records the whole table, and ``tests/app/test_recall_threshold_measured.py`` pins
#: both sides, so a change of model that closes the gap fails there.
#:
#: The hashing embedder's value is reasoned, not measured into a gap, because there
#: is none: its similarity is word overlap, not meaning, so a reply sharing a common
#: word with a record can outscore a paraphrase sharing none. It asks for a
#: substantial share of shared words.
RECALL_THRESHOLDS: Final[Mapping[EmbedderKind, float]] = {
    EmbedderKind.ON_DEVICE: 0.58,
    EmbedderKind.HASHING: 0.3,
}

#: How many entries one activation's stage record retains (ADR-0280 §6): the first
#: ``STAGE_RECORD_LIMIT // 2`` and the last ``STAGE_RECORD_LIMIT - STAGE_RECORD_LIMIT //
#: 2``, with the rest counted in ``stages_elided``; the end entry is last and never
#: elided. A stage runs at most once per pass under M38's loop guard, so no record
#: reaches it yet; the bound is what keeps a record's size a function of the
#: activation once later decisions let a stage run again.
STAGE_RECORD_LIMIT: Final = 64

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
#: genuine tie stays a tie, on which authorizing does not do the call. It lives
#: here rather than in ``Settings`` because ADR-0144 §4 puts it at the composition
#: root and §7 scopes a *user-facing* preference out — that needs durable per-user
#: policy state with its own data-rights obligations, filed as #1101. Until then
#: the recovery runs through this line: an operator names one of the tied tools
#: here and **restarts** — the snapshot is taken at construction and never re-read.
#: An id naming no registered tool is permitted and matches nothing; naming one
#: twice is refused at construction.
TOOL_PREFERENCE: Final[tuple[str, ...]] = ()

# --- The phases (ADR-0309 §2:6, §4) ---------------------------------------------
#
# Every number below is **provisional**: the round limit, the deadlines and the digest
# part size belong to #2589, which has not set them. Each is chosen for a test hub to
# run the thin path's five acceptance cases without being the reason one ends.

#: The most planning rounds one activation runs (ADR-0307 §8:4). **Provisional
#: (#2589).** Enough for a search, its digest, an answer and a correction, and few
#: enough that a loop of refused calls ends quickly.
PHASES_ROUND_LIMIT: Final = 6

#: Each invoked call's deadline, which also bounds a round's wait for its digests
#: (ADR-0307 §8:2, ADR-0029 §4). **Provisional (#2589).**
PHASES_CALL_DEADLINE: Final = timedelta(seconds=30)

#: ``DIGEST_PART_CHARS``: the most characters of outside records one digest call
#: reads (ADR-0308 §4:9). **Provisional (#2589).** A search's three bounded results
#: fit in one part.
PHASES_DIGEST_PART_CHARS: Final = 12_000

#: ``DIAGNOSTIC_FILE_BYTES``: the most one activation's diagnostic file holds (ADR-0314
#: §6:3). A busy activation is far below it; the cap stops one runaway activation from
#: filling the disk, and the window bounds the rest.
DIAGNOSTIC_FILE_BYTES: Final = 8 * 1024 * 1024

#: The diagnostic record's directory under the data directory (ADR-0314 §6:1).
DIAGNOSTIC_DIRECTORY: Final = "diagnostics"

#: ``RECALL_SECOND_RUN_CAP``: how many records recall's second run keeps in all, across
#: understanding's meaning and phrases, each of which keeps up to ``RECALL_ITEM_LIMIT``
#: (ADR-0308 §2:4-§2:5). Not above ``RECALLED_ITEMS_MAX``, which the recall stage and
#: the phase path check. **Provisional (#2589).** Two cues' worth at the per-cue limit:
#: the meaning and one named thing found whole, and a longer reading cut in band order.
RECALL_SECOND_RUN_CAP: Final = 2 * RECALL_ITEM_LIMIT

#: The deadline bounding recall's digest, its fetch of recall's outside memory records
#: included, cut to what the activation has left (ADR-0308 §4:4; §4:11 names only a
#: result's digest's deadline). **Provisional (#2589).** A call's deadline, as a
#: result's digest is bounded by: a few remembered facts are one part, one call.
PHASES_RECALL_DIGEST_DEADLINE: Final = PHASES_CALL_DEADLINE

#: The budget one activation the chat's reader starts is given, in place of
#: ``CHAT_TURN_BUDGET``: several rounds, each a model call, a search and a digest, do
#: not fit the one-reply minute. **Provisional (#2589).**
PHASES_TURN_BUDGET: Final = timedelta(minutes=3)

#: The bound planning cuts another episode's texts to, as understanding's is
#: (ADR-0307 §6:1). **Provisional (#2589).**
PHASES_EXCERPT_CHARS: Final = UNDERSTANDING_EXCERPT_CHARS

#: How many of a story's latest episodes planning is shown whole, and how many of the
#: episodes newer than its summary (ADR-0307 §6:1). **Provisional (#2589).** Where the
#: matter stands already lists its newest moments one by one, so this is what planning
#: reads in full: one more than a short view's, and how many changes have come since
#: says what is not shown.
PHASES_STORY_EPISODES: Final = STORY_SHORT_VIEW_EPISODES + 1

#: The most remembered facts one memory search planning makes keeps, before they are
#: routed by source (ADR-0307 §6:6, ADR-0306 §5:16). **Provisional (#2589).** As many as
#: recall's second run keeps in all, so an asked-for search reaches no fewer than recall.
PHASES_MEMORY_SEARCH_LIMIT: Final = RECALL_SECOND_RUN_CAP

#: How many similar memories a candidate's lookup returns at most (ADR-0329 §4:1).
#: **Provisional (#2589).** A handful: enough to show planning a conflict that matters,
#: few enough that a result stays short.
CANDIDATE_LOOKUP_LIMIT: Final = 5

# --- The observer's bounds (ADR-0329 §7:5, §8:1, §9:3, §16) ------------------------
#
# Every bound the observer works within but its daily budget, which is the setting
# ``observer_daily_calls`` (§16:9). None is measured yet; each is chosen for a hub
# learning from a person's ordinary use, and the catch-up (§17) is the first evidence.

#: §7:5's instant: an episode that occurred before it is never due. The decision's own
#: value, the day the memory record of ADR-0328 went live.
OBSERVER_SINCE: Final = datetime(2026, 10, 16, tzinfo=UTC)

#: The most stored memories retrieved for one framed memory (ADR-0346 §6:1): those
#: relevant enough to its wording, then those naming a person it names. **Provisional.**
#: Twice the lookup's count, since the owner ruled retrieval need not be capped at
#: planning's five, and every retrieved memory costs only its compact form in the one
#: placement call.
OBSERVER_RETRIEVED: Final = 2 * CANDIDATE_LOOKUP_LIMIT

#: The most recent supports a retrieved memory is shown with in full (ADR-0346 §6:2).
#: **Provisional.** Enough to show how a memory came to stand as it does and who said it
#: last, few enough that ten memories keep the placement call a page.
OBSERVER_RECENT_SUPPORTS: Final = 3

#: How many times a placement the writer refuses as stale is retrieved and placed again
#: within one attempt (ADR-0346 §6:7). The observer is the one writer and runs one run at
#: a time (ADR-0345 §11:1), so a stale placement means only a pin confirmed between its
#: retrieval and its write; twice is ample, and past it the attempt fails and is retried
#: with its backoff.
OBSERVER_STALE_RETRIES: Final = 2

#: The first backoff after a failed attempt, doubled each further failure (§16:4).
#: Long enough that a passing outage of a provider is over before the retry, short
#: enough that an episode a reply failed to parse is tried again within the hour.
OBSERVER_RETRY_BASE: Final = timedelta(minutes=15)

#: The longest backoff (§16:4). Half a day, so an episode failing through a long outage
#: is still tried twice a day.
OBSERVER_RETRY_CAP: Final = timedelta(hours=12)

#: The failed attempts after which an episode is stuck and set aside (§16:5). A stuck
#: episode is processed again only by an explicit re-run, and no surface makes one yet,
#: so the count must outlast an outage: with the backoff above the tenth failure comes
#: about 52 hours after the first, which rides out a weekend's outage of a provider
#: while still setting aside, within days, an episode no attempt can finish. A held
#: attempt — the budget, or the run's bound — is not a failure and does not count.
OBSERVER_STUCK_AFTER: Final = 10

#: The most episodes one run takes (§16:8), so a run stays bounded on the scheduler's
#: serial loop (ADR-0083 §7). Each episode costs a scout call, a framing call per finding
#: and a placement call per memory framed (ADR-0346 §10:2), so five is about twenty-five
#: calls: a few minutes at most behind the loop's other jobs. With a run on every freeze
#: and the timer every fifteen minutes, that drains a catch-up faster than the daily
#: budget lets it spend.
OBSERVER_PER_RUN: Final = 5

#: The person-model store's file under the data directory (ADR-0338 §10:1), opened only
#: where ``Settings.person_model`` is on (§11:2).
PERSON_MODEL_FILENAME: Final = "person_model.db"

#: ADR-0338 §3:2's bound on a profile field's length, in characters: a name, an address,
#: an assistant's name, a zone or a language. A composition-root constant, handed to the
#: person-model store, which validates every write against it.
PROFILE_FIELD_CHARS: Final = 200


@dataclass(frozen=True, slots=True)
class Composition:
    """The built engine, plus what only this layer knows (ADR-0119 §9).

    Returned by :func:`build_composition` and consumed by `service`, which stamps
    one ``CONFIGURATION`` trace per hub startup. Everything on it beyond the
    engine is there because the stamp cannot obtain it anywhere else: the sink is
    opened here, and the cardinality figure is a property of *how this layer
    constructed a collaborator* rather than of any setting.

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
        conflict_search_limit: The ``limit`` the ingestor's conflict probe reaches
            ``MemoryStore.search`` with — the ceiling **plus two** (ADR-0079 §1),
            which is the figure §9 requires and the control's own value is not.
    """

    engine: Engine
    trace_sink: TraceSink
    conflict_search_limit: int


def telegram_intake_path(directory: Path, *, reference: str, chat_id: int) -> Path:
    """The Telegram line's intake record's file, one per line (ADR-0323 §2:3, §5:8).

    Keyed by the line's identity — its connection's reference with its chat — as a
    digest, so the file name carries neither and two lines never share a record. A
    line set up again under the same pair finds its own record where it left it.

    Args:
        directory: The data directory.
        reference: ``Settings.telegram_connection``.
        chat_id: ``Settings.telegram_user_id``.

    Returns:
        The record's path under ``directory``.
    """
    key = hashlib.sha256(f"{reference}\x00{chat_id}".encode()).hexdigest()[:24]
    return directory / f"telegram-{key}.db"


def seeded_time_zone(settings: Settings) -> str | None:
    """The owner's zone for the person model's seed, where one was given (ADR-0338 §3:7).

    ``ASSISTANT_TIMEZONE``'s value where that variable is set — in the environment, the
    environment file or the settings' own construction — and ``None`` where it is not.
    ``Settings.timezone`` falls back to UTC when nothing set it, and that default is
    the hub's, which no one chose, so it is never seeded as the owner's own: the zone is
    left empty, and an empty zone reads as ``Settings.timezone`` anyway (§3:6).

    Args:
        settings: The loaded settings.

    Returns:
        The zone to seed, or ``None``.
    """
    return settings.timezone if "timezone" in settings.model_fields_set else None


def _policy_for_zone(zone: ZoneInfo) -> NotificationPolicy:
    """The policy whose quiet windows are read in a person's zone (ADR-0338 §3:6).

    The factory both notification ruling paths hold, so each ruling is handed a policy
    built over the zone it is for, which stays that instance's construction-time input
    (ADR-0130 §6).

    Args:
        zone: The person's zone, as their profile sets it.

    Returns:
        The concrete policy over that zone.
    """
    return DefaultNotificationPolicy(timezone=zone)


def _configured_telegram_relay(settings: Settings) -> TelegramRelay | None:
    """The relay a relayed Telegram line reaches, or ``None`` in direct mode (ADR-0330 §3).

    ``Settings`` checked the two fields as text and refused every combination no
    reading makes true (§3:5 to §3:7). What it cannot decide is here: the origin goes
    through the seam's canonicaliser (§3:4), and each certificate is loaded as a trust
    anchor (§3:8). Either failing refuses the hub's start, before any call and before
    anything is opened.

    Args:
        settings: The loaded settings.

    Returns:
        The relay, or ``None`` where ``telegram_relay_origin`` is unset.

    Raises:
        ConfigurationError: If the origin has no canonical form at the seam, or a
            certificate cannot be loaded as a trust anchor.
    """
    if settings.telegram_relay_origin is None:
        return None
    try:
        return TelegramRelay(
            origin=settings.telegram_relay_origin,
            certificates=settings.telegram_relay_certificates,
        )
    except TelegramRelayError as exc:
        msg = f"the Telegram line's relay cannot be reached as configured: {exc}"
        raise ConfigurationError(msg) from exc


def _search_destinations(origin: str | None) -> tuple[CanonicalDestination, ...]:
    """The canonical destination set a search of this deployment would bind to.

    ADR-0238 §2 obliges the search servicing site to read a destination's recorded
    trust **before** the supply is built, and at that instant no request and so no
    binding exists — ``WebSearcher`` has no destination member and ADR-0238 §13 gives
    it none. So the set is derived here, from the one value the searcher's own
    transport is built from, through
    :func:`~ai_assistant.tools.egress_binder.canonical_destination`: **the same
    canonicaliser and the same protocol mapping** ``EgressBindingSeam`` derives a span's
    occurrence with, so the two cannot state one rule twice.

    ``tools/web_search.py`` declares the ``origin`` argument
    ``x-egress-destination: "https"``, so a search binding's spans carry exactly this
    one destination and
    :attr:`~ai_assistant.core.types.EgressBinding.canonical_destination_set` answers
    exactly this tuple — asserted against a binding the real seam derived, in
    ``tests/app/test_search_destinations.py``, rather than left as a claim.

    Args:
        origin: ``Settings.web_search_origin``, or ``None`` where this deployment
            connected no search account.

    Returns:
        The one-member set, or an empty one. **Empty is not a special case**: a
        deployment with no account composes over the utterance alone and closes no
        loop — which is also what an
        origin this seam asserts no canonical form for gets, because the searcher's own
        ``bind`` would refuse that call anyway and a composition root that raised here
        would take the whole process down for a search it was never going to make.
    """
    if origin is None:
        return ()
    try:
        return (canonical_destination(DestinationProtocol.HTTPS, origin),)
    except DestinationCanonicalisationError:
        return ()


def _configured_search(
    connection: str | None, destinations: tuple[CanonicalDestination, ...]
) -> ConfiguredSearchDestination | None:
    """What ADR-0247 §2's route (c) rests on, or ``None`` where nothing does.

    The two configured values as the one argument the policy takes: the connection
    reference the search is registered against and the canonical destination set its
    origin canonicalises to (§1). **Both are passed through rather than derived** —
    the set is :func:`_search_destinations`' own answer, from the canonicaliser
    ``EgressBindingSeam`` derives a span's occurrence with — because §1 compares
    recorded values and forbids either side being re-canonicalised.

    Args:
        connection: ``Settings.web_search_connection``, or ``None`` where this
            deployment connected no search account.
        destinations: :func:`_search_destinations`' answer for
            ``Settings.web_search_origin``.

    Returns:
        The pair, or ``None`` where this deployment has no search destination to
        compare against — no connection, or an origin this seam asserts no canonical
        form for. A policy given ``None`` takes the *at the configured provider* fact
        as false for every request, which is §2's fail-closed direction; **an empty
        set is not passed as a pair**, because a binding's own canonical destination
        set is never empty and a pair that can never compare equal would read as a
        configuration while authorising nothing.
    """
    if connection is None or not destinations:
        return None
    return ConfiguredSearchDestination(reference=connection, destinations=frozenset(destinations))


def _forecast_destinations(origin: str | None) -> tuple[CanonicalDestination, ...]:
    """The canonical destination set a forecast read of this deployment would bind to.

    :func:`_search_destinations` one kind along (ADR-0260 §6, §11), through the
    **same** :func:`~ai_assistant.tools.egress_binder.canonical_destination` and the
    same protocol mapping, because ``tools/forecast.py`` declares its ``origin``
    argument ``x-egress-destination: "https"`` exactly as ``tools/web_search.py``
    does — so a forecast binding's spans carry the one destination this tuple holds.

    **Stated beside its twin rather than shared with it**, which is §11's own
    posture: the forecast settings are ``web_search_*``'s *"own shape field for
    field"*, and the two reads are of two independent configuration facts. The rule
    itself is stated once, in the canonicaliser both call.

    Args:
        origin: ``Settings.forecast_origin``, or ``None`` where this deployment
            configured no forecast provider.

    Returns:
        The one-member set, or an empty one — :func:`_search_destinations`' own
        answer in both cases and for its own reasons.
    """
    if origin is None:
        return ()
    try:
        return (canonical_destination(DestinationProtocol.HTTPS, origin),)
    except DestinationCanonicalisationError:
        return ()


def _configured_forecast(
    connection: str | None, destinations: tuple[CanonicalDestination, ...]
) -> ConfiguredForecastDestination | None:
    """What ADR-0260 §6's widened route (c) rests on for a forecast read, or ``None``.

    :func:`_configured_search` one kind along, word for word in what it does and in
    why: the connection reference the forecast integration is registered against and
    the canonical destination set its origin canonicalises to, **both passed through
    rather than derived**, because §6 compares recorded values and forbids either
    side being re-canonicalised.

    **The result is its own type** (:class:`ConfiguredForecastDestination`), so this
    root cannot hand the policy the search pair for the forecast kind or the reverse
    — the crosswise wiring §6 gives **no** route at all, caught here by the type
    checker rather than by a ruling that quietly matched the wrong configuration.

    Args:
        connection: ``Settings.forecast_connection``, or ``None`` where this
            deployment configured no forecast provider.
        destinations: :func:`_forecast_destinations`' answer for
            ``Settings.forecast_origin``.

    Returns:
        The pair, or ``None`` where this deployment has no forecast destination to
        compare against — no connection, or an origin this seam asserts no canonical
        form for. A policy given ``None`` takes the *at the configured provider* fact
        as false for every forecast read, which is §6's fail-closed direction; **an
        empty set is not passed as a pair**, for :func:`_configured_search`' reason.
    """
    if connection is None or not destinations:
        return None
    return ConfiguredForecastDestination(reference=connection, destinations=frozenset(destinations))


def build_engine(settings: Settings, *, data_dir: Path | None = None) -> Engine:
    """The engine alone, for every caller that needs nothing else (ADR-0042 §2).

    The composition root's entry point, unchanged in behaviour and in signature.
    :func:`build_composition` is the same build with ADR-0119 §9's extra figure
    still attached; a caller that is not stamping a configuration trace
    wants this one.

    Args:
        settings: Loaded application settings; see :func:`build_composition`.
        data_dir: Where the SQLite stores live, overriding ``settings.data_dir``
            when given; see :func:`build_composition`.

    Returns:
        A ready :class:`Engine`. Drive it through its operations and close it
        with ``aclose`` when the session ends.

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

    * the *same* :class:`SqliteMemoryStore` instance is injected into the phases
      (for recall) and into the :class:`MemoryIngestor` writer (for persistence),
      so what is written is what is recalled (ADR-0028 §4);
    * one :class:`InMemoryToolRegistry` object is injected as the selecting
      ``ToolRegistry`` and the acting ``ToolInvoker`` (ADR-0029 §8), and is handed
      the ``InvocationLedger`` face of the one :class:`SqliteAuditTrail` — never
      the trail itself (ADR-0192 §9);
    * one :class:`SqlitePlanStore` and one :class:`SqliteAuditTrail` are shared by
      the phases and the façade — the façade reads the trail (query-only) for the
      decision and invocation listings (ADR-0052 §1);
    * the :class:`ConversationLifecycle` capture stage is given that *same*
      memory store and the one retention horizon settings names, so a captured
      episode and the conversation index that names it expire against one clock
      rather than two (ADR-0074 §7, §9);
    * the model seam is composed **retry inside routing**, the order ADR-0013 §3
      recommends and that nothing in `models/` can enforce, since enforcing it
      would mean a wrapper knowing what wraps it (see :func:`_build_model_provider`);
    * **consolidation's** seam, the background route ``consolidation_model`` names, is
      composed differently on purpose — retry and *no routing*, one named route that
      never falls back (ADR-0285 §5, see :func:`_build_consolidation_provider`);
    * the **grant store is opened here**, as the **sixth** connection-owning Tier 1
      store, and the *same object* is passed twice — as a
      :class:`~ai_assistant.core.protocols.SourceGrantStore` to the grant operations
      and as a :class:`~ai_assistant.core.protocols.SourceGrants` to every driver
      (ADR-0102 §7). Structural typing is what makes one object serve both; what a
      driver cannot do is *name* ``record``, because ``mypy --strict`` runs over
      ``src`` and ``tests`` and the attribute is not on the annotated type
      (ADR-0097 §3);
    * the **upcoming-event producer** is wired whenever a calendar source is
      configured (ADR-0093 §7's disabled default), over its **own** reader instance
      (ADR-0096 §5), and no stage ingests what a reader reads (ADR-0294 §1) — and
      this is the one place a
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
    spec's vendor, ADR-0062 §2), the readers (which validate their figures), and
    the embedder (whose on-device default checks the vendored model artifact,
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
    left standing, ``current_time``, and with the configured integrations' tools;
    the phases offer planning every capability it holds (ADR-0306 §2:7, see
    :func:`_build_phase_path`).

    Args:
        settings: Loaded application settings — the model specs the router routes
            over (``default_model`` then ``fallback_models``, ADR-0062) and their
            resilience knobs, the four permission gate thresholds the phases'
            policy is constructed with (#239),
            consolidation's route (``consolidation_model``; ADR-0285 §5),
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
        A :class:`Composition`: the ready :class:`Engine` — drive it through its
        operations and close it with ``aclose`` when the session ends
        — beside the trace sink this build opened and the conflict probe's effective
        ``search`` limit it produced, which ADR-0119 §9's startup stamp records and
        cannot read off ``Settings``.

    Raises:
        ConfigurationError: If the data directory cannot be prepared — blocked by
            permissions, or a file occupies its path. Converted from the raw
            ``OSError`` so an adapter's ``AssistantError`` boundary surfaces it
            rather than letting it escape as a traceback. Or if a configured model
            spec names a vendor pydantic-ai does not know or whose optional package
            is not installed — the router's specs (ADR-0062 §2, see
            :func:`_build_model_provider`) and consolidation's own route alike
            (ADR-0285 §5, see :func:`_build_consolidation_provider`). Or if
            the on-device embedder cannot be constructed because its vendored model
            artifact is missing or incomplete (ADR-0006 §2, ADR-0024, see
            :func:`_build_embedder`).
    """
    # Validate everything that needs no resource before opening a store, so a bad
    # configuration fails before build_engine touches disk (#372). The model seam
    # checks every spec's vendor (ADR-0062 §2) and opens no connection-owning store,
    # so it is built here, above the data directory. Every step that needs an open
    # store stays below, inside the cleanup block that closes what it opened on a
    # later failure.
    model = _build_model_provider(settings, _model_specs(settings))
    # Consolidation's route, built here and separately: it is one route and it never
    # falls back (ADR-0285 §5). The consolidation stage retired, and the route stays
    # for the background work that rides it, the story tidy-up and the matters pass
    # (ADR-0328 §14:4). Above the data directory with the rest, so a spec naming an
    # uninstalled vendor fails the build rather than the first background run.
    consolidation_model = _build_consolidation_provider(settings, _consolidation_spec(settings))
    # The reconciler's route, on consolidation's shape and for its reasons
    # (ADR-0159 §3, ADR-0285 §5): one route, named rather than inherited, and no
    # fallback. Built up here so a spec naming an uninstalled vendor fails the build
    # rather than the first ingest that would have used it.
    reconciler_route = _reconciler_spec(settings)
    reconciler_model = _build_reconciler_provider(settings, reconciler_route)
    # The observer's two routes, on consolidation's shape and for its reasons (ADR-0329
    # §9:9, ADR-0285 §5:3): each named by its own setting or else ``default_model``, and
    # neither falls back. Up here so a spec naming an uninstalled vendor fails the build
    # rather than the first run.
    observer_scout = _build_observer_provider(settings, _observer_scout_spec(settings))
    observer_commit = _build_observer_provider(settings, _observer_commit_spec(settings))
    # The read-only sources, if this deployment configured one (ADR-0093 §7).
    # **One reader instance per consumer**, and ADR-0096 §5 decides it here rather
    # than leaving the composition lane to pick by accident: ADR-0093 §7 bounds a
    # reader at one outstanding worker *per instance*, so a shared reader would let
    # one consumer's read suppress another's for as long as it runs. Each instance
    # costs one worker at most, which is still bounded, and each consumer then owns
    # its own failure.
    #
    # **The calendar had two consumers: the request-path facet, retired with the
    # old path's context provider (ADR-0309 §5), and ADR-0132's producer**, and
    # ADR-0132 §3 requires the producer's read to be its own — "The
    # producer performs its own ``Reader.read()`` on its own schedule, and derives
    # nothing from the facet path's reading". It has no ingestion consumer, because
    # scheduled ingestion into memory is retired (ADR-0294 §1); the count follows
    # the consumers. **Email has no reader at all**: it is not a grantable source
    # (ADR-0320 §3), and returns only through the channel model's design of an
    # email capability.
    #
    # **Nothing reads through the facet reader since the old path's context provider
    # was retired** (ADR-0309 §5). It is still built for its identity and location:
    # the grant operations list it as a grantable source, and ADR-0199 §3 reads the
    # calendar's name below. Whether the facet goes too is its own decision.
    #
    # Both are built above the data directory, and they belong there for
    # #372's reason rather than by association: constructing a reader opens nothing
    # — it validates its figures (ADR-0093 §7a) and names a daemon
    # thread it has not started — so a window or cap outside its range fails the
    # build before any store is written.
    facet_reader = _build_calendar_reader(settings)
    upcoming_reader = _build_calendar_reader(settings)
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
    # The Telegram line's relay, where its line is relayed (ADR-0330 §3:4, §3:8): the
    # origin canonicalised through the seam and the certificates loaded as trust
    # anchors, each refusing the hub's start on a failure — and above the data
    # directory, because neither opens anything (#372).
    telegram_relay = _configured_telegram_relay(settings)
    # The keyword still wins over the setting when it is given (ADR-0083 §2), so
    # every existing caller — and the hub, handing over the directory it resolved
    # and locked before any store was opened — keeps its injection seam. What
    # changed is only where the *default* comes from: ``Settings.data_dir``,
    # whose factory produces the very ``~/.ai-assistant`` this module resolved
    # privately before, so nothing moves for a deployment that configures nothing.
    directory = data_dir if data_dir is not None else settings.data_dir
    # ADR-0314 §7:4: the record's window is its forgetting, so a hub with no sweep
    # refuses to start while it would write one or holds one, before any store opens.
    record_directory = diagnostic_record_directory(settings, data_dir=directory)
    refuse_an_unswept_diagnostic_record(settings, record_directory)
    # ADR-0337 §8:2: the follow-up is kept in the record, so it is not asked without one.
    refuse_a_follow_up_without_the_record(settings)
    # ADR-0334 §3:4: every prompt's template, default or override, read and checked
    # once, before the API accepts a request and before any store opens; a malformed
    # override refuses the start here (§5:1). It creates nothing (§5:3).
    prompts = read_prompts(settings, data_dir=directory)
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
        # ADR-0314's diagnostic record: one object, handed out narrowed and never
        # whole (§3:3). The engine's sweep takes it as a ``DiagnosticRetention``
        # whatever ``diagnostic_record`` says (§7:3); each emitter takes it as a
        # ``DiagnosticSink`` only where the record is on, and ``None`` otherwise
        # (§4:4). It opens nothing until its first write, so a deployment with the
        # record off never gains its directory.
        diagnostic_record = FileDiagnosticRecord(
            directory=record_directory, file_bytes=DIAGNOSTIC_FILE_BYTES
        )
        diagnostics: DiagnosticSink | None = (
            diagnostic_record if settings.diagnostic_record else None
        )
        # ADR-0337 §8:5: where the follow-up is asked, the asker wraps the sink every
        # emitter is handed, passing each entry on unchanged; the record is on here,
        # since the start is refused above where it is not (§8:2).
        follow_ups = _follow_up_asker(settings, diagnostics, prompts[FOLLOW_UP_PROMPT.name])
        if follow_ups is not None:
            diagnostics = follow_ups
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
        # **ADR-0289 §1's story store, on its own file.** It reads no other store and
        # no store reads it. The engine surface writes it as the owner (§4), and since
        # ADR-0300 §6 understanding's candidates read it and the story-links stage
        # writes it, and since §7 recall reads it, each handed this same object below. Its records
        # are identities and instants only (§2), but which activations belong
        # together is a fact about the owner's life, so it is owner-only like every
        # other file here. Deploying it adds the file and changes no existing record
        # (§6), and it joins the ordered shutdown below.
        stories = SqliteStoryStore(path=directory / "stories.db", now=_utcnow)
        opened.append(stories.close)
        # **ADR-0338 §10's person-model store, on its own file, behind the switch.**
        # Where ``person_model`` is off, the default, no store is built or opened and
        # the engine is handed no person block, so nothing of the person model reaches
        # a model and every deploy stays inert until its last lane has merged (§11:2,
        # ADR-0342 §6:3). Where it is on, the store is created holding the owner, and
        # seeded with their zone from ``ASSISTANT_TIMEZONE`` where that is set (§2:1,
        # §3:7). It reads no other store and no store reads it; the person block reads it
        # beside ``memory`` (§7:1).
        person_model = (
            SqlitePersonModelStore(
                path=directory / PERSON_MODEL_FILENAME,
                field_chars=PROFILE_FIELD_CHARS,
                seed_time_zone=seeded_time_zone(settings),
                now=_utcnow,
            )
            if settings.person_model
            else None
        )
        if person_model is not None:
            opened.append(person_model.close)
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
        # The durable plan store: an activation's stop record and acting's effect
        # records (ADR-0297 §1, ADR-0306 §6), which survive a restart.
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
        # **One object, passed twice** (ADR-0185 §4, ADR-0186 §10): as a
        # `SourceReadRecorder` to the one driver left, the upcoming-event stage, and
        # **whole, as the `SourceReadTrail`, to the engine**. Structural typing is what makes that
        # sound, and the narrowing is the *annotation on the driver's constructor*
        # rather than anything done here — what a driver cannot do is name `recent`,
        # which is what keeps ADR-0093 §5's forbidden cursor out of a sensor's reach.
        #
        # **The engine is the wide seam's only holder**, which is the surface
        # ADR-0185 §12 left to its own lane and ADR-0186 §10 decided. The asymmetry
        # is the design: the drivers write and cannot read, the façade reads and does
        # not write — authoring a row stays on the seam that gated the read (ADR-0185
        # §5), and ADR-0186 §4's refusal of a promoted `record` is one store over the
        # same rule. That both positions hold the **same instance** is a
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
        # **The id source is deliberately not passed**: a notification id
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
        # stage below hands it to the same store on the live path. One object over
        # `Settings.timezone`, the hub's default, and beside it one factory for a
        # person's zone (ADR-0338 §3:6): both paths read the owner's zone from the
        # one person-model store just before each ruling and hand the store the
        # policy for it, so the two cannot disagree about the person's night. Each
        # policy's zone stays its construction-time input (§6). Where the person
        # model is off, both hand every ruling this one policy, as before.
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
            store=notifications,
            policy=notification_policy,
            outbox=outbox,
            policy_for=_policy_for_zone,
            people=person_model,
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
        # **The same object as the trail the phases record decisions into**, not a
        # second one over the same file. The ledger requires the decision it is
        # passed to be equal to the decision the store holds under that id
        # (ADR-0192 §1), so a second handle would refuse every claim under a ruling
        # authorizing had just recorded — and two tables keyed by one decision could
        # diverge, which is the split ADR-0029 §8 refuses one seam over.
        #
        # **And the gate face of that same object** (ADR-0194 §3, §5): the invoker
        # is admitted through the holder that reads the rows the ledger writes, and
        # is handed the gate and never the `SpendLedger` — an invoker able to read a
        # totals projection has acquired a permissions-owned history it has no use
        # for, which is ADR-0029 §1's argument one seam over. The engine below gets
        # the ledger face and never the gate, for the mirror reason.
        # --- the configured simulated booking provider (ADR-0273 §1, §10) ---
        #
        # **The one place in production this provider is wired**, which is §1's
        # *"wired from ``app/composition.py`` alone"* and ADR-0260 §12's L1 shape one
        # integration along.
        #
        # **Built only where a deployment configured it whole**, so a deployment that
        # named none of the nine ``booking_*`` settings holds no provider at all,
        # registers neither declaration in any registry and adds no entry to the seam's
        # table — and ``Settings`` refuses every half-set combination of them, so this
        # is whole or absent rather than merely usually whole. The condition below tests
        # every one of the nine rather than a representative: a reader checking this
        # line should not have to hold a validator in mind to see that the branch and
        # the refusal agree.
        #
        # **No transport is constructed for it and none is passed** (§3). The provider
        # opens no socket, resolves no name and performs no HTTP exchange;
        # `build_simulated_booking_integration` takes no ``OutboundTransport``
        # parameter, so the injection route by which the real and the fake transport
        # both reach production code does not reach it at all — and
        # ``pyproject.toml``'s transport-confinement contract names its module, so an
        # edit giving it one fails `lint-imports` rather than passing review.
        #
        # **`records` and `secrets` are the objects this root already holds**, not
        # second ones over the same file and namespace, for the mail integration's
        # reasons: ADR-0148 §6's conditions read the connection record twice around the
        # credential read, and a second handle would let a provisioning act commit a
        # revision one of them could not yet see.
        #
        # **Its store is an ordinary store of this deployment** (§2): it sits under the
        # same data directory as every other, so `ai-assistant-purge` (ADR-0126,
        # ADR-0153) destroys it with them, and its `close` is registered in the ordered
        # shutdown path below like every other store's (ADR-0042 §2).
        #
        # **This root configures nothing.** ADR-0273 §10: *"no lane of this decision
        # configures the provider in any deployment"* — that is the operator act §1
        # reserves, performed by editing the deployment's configuration and restarting,
        # and no model, plan, planner, tool, surface or API is given a route to it.
        booking = (
            None
            if settings.booking_connection is None
            or settings.booking_endpoint is None
            or settings.booking_available_from is None
            or settings.booking_available_to is None
            or settings.booking_price_amount is None
            or settings.booking_price_currency is None
            or settings.booking_billed_amount is None
            or settings.booking_billed_currency is None
            or settings.booking_retained_records is None
            else build_simulated_booking_integration(
                connection=settings.booking_connection,
                endpoint=settings.booking_endpoint,
                records=connections,
                secrets=integration_secrets,
                store_path=directory / "bookings.db",
                # **Read and passed through unchanged, which is the whole of what this
                # root does with them.** Passing a value is not interpreting it: no
                # default is applied, no arithmetic is performed, and whether each is in
                # ADR-0273 §5's domain was decided at `Settings` load and is decided
                # again by the factory, which is the one place a provider can be built
                # without going through `Settings`.
                available_from=settings.booking_available_from,
                available_to=settings.booking_available_to,
                price_amount=settings.booking_price_amount,
                price_currency=settings.booking_price_currency,
                charge_amount=settings.booking_billed_amount,
                charge_currency=settings.booking_billed_currency,
                retained_records=settings.booking_retained_records,
                indeterminate_date=settings.booking_indeterminate_date,
            )
        )
        if booking is not None:
            # **The build-failure list, and the ordered shutdown below.** This one is
            # the failure path only: a build that raises after this point closes what it
            # opened. Registering it *here alone* would close the store when the build
            # **failed** and never when it succeeded, which is #1903 exactly — so its
            # `close` is in `closers` too (ADR-0042 §2, ADR-0083 ruling 4).
            opened.append(booking.store.close)

        tools = build_default_registry(egress=egress, booking=booking, ledger=trail, gate=trail)

        # ADR-0152 §10's marked clause: "It is implemented in `tools/`, and consumed
        # in `orchestration` … **The composition root wires the one
        # implementation.**" (#1138). Its consumer is the phases' authorizing stage
        # (:func:`_build_phase_path`), because ``records`` needs the connection store
        # this root opened above.
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
        # **The one configured search integration, where a deployment configured
        # one** (ADR-0231 §5, §17). Built *after* the registry above and handed to
        # it never: the search declaration is registered "at the egress seam
        # against a connected account, and in no ``ToolRegistry``", which is the
        # hinge ADR-0231 §5 rests on — a registry entry would put its capability in
        # front of the planner, and the planner naming it is the outcome the whole
        # design exists to make unreachable. `build_default_registry` takes no
        # search argument, so that absence is a property of the signature rather
        # than of a line somebody remembered not to write.
        #
        # **Constructed only where an account is connected** (§17), so a deployment
        # that named neither `web_search_connection` nor `web_search_origin` holds
        # no searcher at all — and `Settings` refuses half a pair, so this is whole
        # or absent. `records`, `secrets` and the transport are the objects this
        # root already holds, for the mail integration's reasons: a second store
        # handle would let a provisioning act commit a revision one of them could
        # not yet see, and constructing the transport inside the branch is what
        # keeps "a subsystem handed no capability has no route to the world" true
        # of the whole tree rather than of one argument list (ADR-0191 §1, §3).
        #
        # **The ledger and the gate are the same object the invoker is handed**
        # (ADR-0192 §9, ADR-0194 §5): one object satisfies `AuditTrail`,
        # `InvocationLedger`, `InvocationCompleter` and `SpendLedger` over one
        # store, each consumer gets the face its job needs, and two holders keyed by
        # those rows could otherwise disagree about a total.
        #
        # **No ``close`` is registered for it, and that is ADR-0042 §2 read rather
        # than skipped.** That section's obligation is over "the resources it has
        # opened"; a searcher opens none that outlives a call. ADR-0191 §3 makes the
        # exchange open a channel per call and close it in a ``finally``, "retaining
        # no pool, cache or keep-alive", and the connection store and the keyring it
        # reads through are objects this root already closes. A no-op ``close``
        # registered here would be a lifecycle nobody has, which is the shape
        # ADR-0231 §6 refuses one clause over.
        #
        # **The one caller is the phases' tools** (ADR-0309 §4). This root wires
        # the searcher into :func:`_build_phase_path` and into nothing else, and no
        # other subsystem holds the reference. A deployment with no account
        # connected holds no searcher, which is never an error.
        search = (
            None
            if settings.web_search_connection is None or settings.web_search_origin is None
            else build_web_search_integration(
                connection=settings.web_search_connection,
                origin=settings.web_search_origin,
                records=connections,
                secrets=integration_secrets,
                transport=StreamOutboundTransport() if transport is None else transport,
                ledger=trail,
                gate=trail,
                max_results=settings.search_max_results,
                max_result_chars=settings.search_max_result_chars,
                max_response_bytes=settings.search_max_response_bytes,
                # **Read and passed through unchanged, which is the whole of what
                # this root does with them** (ADR-0236 §1, §7). Passing a value is
                # not interpreting it: no default is applied, no arithmetic is
                # performed, no `ToolCost` is constructed here, and whether the pair
                # is whole was decided at `Settings` load. Forwarding is an
                # obligation rather than a convenience — a lane that landed the
                # fields, the builder and every test while this root passed neither
                # would leave every configured deployment at `UNKNOWN` with a green
                # gate, which is the failure the decision exists to remove.
                cost_per_call=settings.web_search_cost_per_call,
                cost_currency=settings.web_search_cost_currency,
            )
        )

        # --- the configured forecast integration (ADR-0260 §6, §12) ------
        #
        # **Registered at the egress seam against the configured connection, and in
        # no ``ToolRegistry``** (ADR-0260 §1), which is the hinge that design rests
        # on: a registry entry would put its capability in front of the planner, and
        # the planner naming it is the outcome the whole design exists to make
        # unreachable. `build_default_registry` takes no forecast argument, so that
        # absence is a property of the signature rather than of a line somebody
        # remembered not to write.
        #
        # **Constructed only where a provider is configured** (§12), so a deployment
        # that named none of `forecast_connection`, `forecast_origin`,
        # `forecast_latitude` and `forecast_longitude` holds no forecaster at all —
        # and `Settings` refuses every half-set combination of the four, so this is
        # whole or absent. `records` and the transport are the objects this root
        # already holds, for the search integration's reasons: a second store handle
        # would let a provisioning act commit a revision one of them could not yet
        # see, and constructing the transport inside the branch is what keeps "a
        # subsystem handed no capability has no route to the world" true of the whole
        # tree rather than of one argument list (ADR-0191 §1, §3).
        #
        # **No `Secrets` face is handed over, and that is the integration's shape**
        # (ADR-0344 §2:3): the provider is Open-Meteo and the connection is keyless
        # (ADR-0325 §2:1), so the forecaster reads no credential and the builder takes
        # no face to read one with. Which shape it is lives in the builder's code, not
        # here and not in `Settings` (ADR-0325 §2:2, ADR-0344 §2:4).
        #
        # **The ledger is passed and no gate is** (ADR-0324 §5:8): the weather pull's
        # attempt and outcomes are its `InvocationLedger` claim and completion, as the
        # searcher's are, through the **same** object the invoker and the searcher are
        # handed (ADR-0192 §9). ADR-0260 §6 names no admission, so no gate: the
        # configured cost pair reaches the **declaration**, which is what ADR-0236 §4's
        # unknown-cost floor reads at the ruling (§11).
        #
        # **No ``close`` is registered for it, and that is ADR-0042 §2 read rather
        # than skipped** — the searcher's reasoning one integration along. That
        # section's obligation is over "the resources it has opened"; a forecaster
        # opens none that outlives a call, ADR-0191 §3 makes the exchange open a
        # channel per call and close it in a `finally`, and the connection store it
        # reads is an object this root already closes.
        # ADR-0260 §4's `close` clause is conditional on "a concrete forecaster
        # **holding an opened resource**", and this one holds none; a no-op `close`
        # registered here would be a lifecycle nobody has.
        #
        # **The one caller is the phases' tools, as the weather pull** (ADR-0324 §5:4):
        # this root wires the forecaster into :func:`_build_phase_path` and into nothing
        # else, and puts its registration in the seam's table. The forecast read stays
        # out of every registry (ADR-0260 §1, ADR-0324 §5:5); the phases' tools offer it
        # beside the registry's capabilities, as they offer the search.
        forecast = (
            None
            if settings.forecast_connection is None
            or settings.forecast_origin is None
            or settings.forecast_latitude is None
            or settings.forecast_longitude is None
            else build_forecast_integration(
                connection=settings.forecast_connection,
                origin=settings.forecast_origin,
                latitude=settings.forecast_latitude,
                longitude=settings.forecast_longitude,
                records=connections,
                transport=StreamOutboundTransport() if transport is None else transport,
                ledger=trail,
                max_days=settings.forecast_max_days,
                max_day_chars=settings.forecast_max_day_chars,
                max_response_bytes=settings.forecast_max_response_bytes,
                # **Read and passed through unchanged, which is the whole of what this
                # root does with them** (ADR-0236 §1, §7; ADR-0260 §11). Passing a
                # value is not interpreting it: no default is applied, no arithmetic is
                # performed, no `ToolCost` is constructed here, and whether the pair is
                # whole was decided at `Settings` load.
                cost_per_call=settings.forecast_cost_per_call,
                cost_currency=settings.forecast_cost_currency,
            )
        )

        binder = EgressBindingSeam(
            definitions=tools,
            registrations=egress_registrations(egress, search, forecast, booking),
            records=connections,
        )
        # The writer persists to the *same* store the phases recall from (ADR-0028 §4),
        # and appends its ``MEMORY_WRITE`` traces to the *same* trace store the read
        # path and the engine boundary use, so §4's correlation join has one stream
        # to join within (ADR-0119 §8).
        #
        # **``conflict_limit`` is passed rather than defaulted** (ADR-0119 §9). It
        # is the cardinality control whose *effective* ``search`` limit the
        # configuration stamp records, and §9 puts the figure to record here:
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
                # ADR-0354 §6:2: its `StructuredCompleter` is the object it was handed
                # as its `ModelProvider` before, with its route and retry unchanged.
                completer=reconciler_model,
                route=reconciler_route,
                # ADR-0334 §3:5: its instruction, as read at start, default or override.
                prompt=prompts[MEMORY_RECONCILER_PROMPT.name],
                max_conflicts=settings.reconciler_max_conflicts,
            ),
            # ADR-0345 §7: the root's label bounds, and the store's own embedder, so a
            # near-duplicate is judged in the space the store embeds every label in.
            label_bounds=LABEL_BOUNDS,
            label_embedder=embedder,
        )
        # ADR-0300 §5's tidy-up, **one operation** for planning's tidy-up call (ADR-0300 §10:4), so
        # at most one run is on a story at a time (§5:10). Its lookalike search keeps what recall
        # would, at recall's threshold for the embedder wired (ADR-0303 §5:7). It runs on
        # **consolidation's route**, the one this deployment names for background work over the
        # assistant's own records (ADR-0285 §5): a tidy-up is that kind of work, nobody waits on it,
        # and one skipped or failed loses nothing (§5), so it needs no fallback route and takes no
        # share of the conversational route's limits.
        tidy_up = StoryTidyUp(
            model=consolidation_model,
            stories=stories,
            memory=memory,
            excerpt_chars=STORY_TIDY_UP_EXCERPT_CHARS,
            other_stories=STORY_TIDY_UP_OTHER_STORIES,
            decisions=STORY_TIDY_UP_DECISIONS,
            budget=STORY_TIDY_UP_BUDGET,
            threshold=RECALL_THRESHOLDS[settings.embedder],
            # ADR-0334 §3:5: its instruction, as read at start, default or override.
            prompt=prompts[STORY_TIDY_UP_PROMPT.name],
        )
        # ADR-0276 §4's episode selector, **one object** handed to the windows stage that
        # shows understanding the episode window and to the observer that tests which
        # episodes have left it (ADR-0329 §15:3), so the window the observer tests is the
        # window understanding is shown. Swapping the method is a change on this line.
        episode_selector = RecentEpisodes(memory=memory, limit=UNDERSTANDING_EPISODE_LIMIT)
        # ADR-0329's observer, memory's one writer (§2:1): a background stage over its two
        # routes, the commit step's carrying framing and placement (ADR-0346 §10:2), the
        # one memory store, the write stage over the writer persisting to that store
        # (§12:1, ADR-0028 §4), the one plan store its observation records live in
        # (§16:1), the story store and the selector above (§15:1, §15:3). The engine
        # starts a run on every frozen episode and the scheduler's row runs it on a timer
        # (§7:6).
        observer = Observer(
            scout=observer_scout,
            commit=observer_commit,
            memory=memory,
            writes=MemoryWriteStage(writer=writer),
            plans=plans,
            stories=stories,
            episodes=episode_selector,
            limits=ObserverLimits(
                since=OBSERVER_SINCE,
                # ADR-0346 §6:1: recall's threshold for the embedder wired, the
                # measured line between a memory relevant to a wording and one not.
                relevance=RECALL_THRESHOLDS[settings.embedder],
                retrieved=OBSERVER_RETRIEVED,
                recent_supports=OBSERVER_RECENT_SUPPORTS,
                stale_retries=OBSERVER_STALE_RETRIES,
                labels=LABEL_BOUNDS,
                retry_base=OBSERVER_RETRY_BASE,
                retry_cap=OBSERVER_RETRY_CAP,
                stuck_after=OBSERVER_STUCK_AFTER,
                per_run=OBSERVER_PER_RUN,
                daily_calls=settings.observer_daily_calls,
            ),
            # ADR-0334 §3:5: the three steps' instructions, as read at start.
            scout_prompt=prompts[OBSERVER_SCOUT_PROMPT.name],
            framing_prompt=prompts[OBSERVER_FRAMING_PROMPT.name],
            placement_prompt=prompts[OBSERVER_PLACEMENT_PROMPT.name],
            now=_utcnow,
            # ADR-0333 §2:7: the record's write seam where it is on, ``None`` where off.
            diagnostics=diagnostics,
            # ADR-0338 §9:8: the same person-model store the person block reads, where
            # the switch is on; ``None`` where it is off, and then the observer reads and
            # writes nothing of the person model and runs no pin pass (§11:2).
            person_model=person_model,
        )
        # ADR-0309 §2:6: the phases, which plan every activation, over the objects this
        # root already built (:class:`_PhaseSeams`).
        phases = _build_phase_path(
            settings,
            _PhaseSeams(
                model=model,
                registry=tools,
                plans=plans,
                trail=trail,
                stories=stories,
                memory=memory,
                binder=binder,
                chat=conversations,
                searcher=None if search is None else search.searcher,
                forecaster=None if forecast is None else forecast.forecaster,
                booking_configured=booking is not None,
                max_payload_bytes=settings.hub_max_frame_bytes - ENVELOPE_RESERVE_BYTES,
                diagnostics=diagnostics,
                tidy_up=tidy_up,
            ),
            planning_prompt=prompts[PLANNING_PROMPT.name],
            digesting_prompt=prompts[DIGESTING_PROMPT.name],
        )
        # --- the Telegram line (ADR-0323 §3, §11, §15) --------------------------
        #
        # **Built only while both of the line's settings are set** (§3:3), and
        # `Settings` refuses one without the other (§3:2), so this is whole or
        # absent: a deployment that names no line holds no client, opens no intake
        # record and starts nothing. The client is the seam's one production
        # implementation (§11:1), over the records and the keyring face this root
        # already holds, for the search integration's reasons, and an exchange of its
        # own holding the line's read bound (§11:13); the transport is the one this
        # root hands every integration (ADR-0191 §3). While the connection the
        # settings name is not active, every call is refused before a byte is
        # written (§3:3, §12:3), and the reader rests until it is.
        #
        # **Relayed mode is configuration of that one client** (ADR-0330 §3, §12:2).
        # With `telegram_relay_origin` set, the client reaches the relay's canonical
        # origin and no other, and its exchange's transport is a capability of its own,
        # **anchored on the relay's certificates alone** (§7:3): never the one every
        # integration is handed, which trusts the system's authorities. An injected
        # transport stands for the network whole, as it does for every integration,
        # so a case that hands one in is its relay; the anchors are loaded above even
        # then, so a certificate that does not load refuses the build either way.
        #
        # **The intake record is a Tier 1 store on its own file** (ADR-0155 §1:2),
        # opened here, closed in the ordered shutdown below and on a failed build,
        # for the other stores' reasons. **One file per line** (§2:3): the record keys
        # its updates and the confirmation it owes by Telegram's update ids alone, which
        # are a bot's own, so a line named by another connection or another account is
        # a new place whose record starts empty — another bot's owed offset never
        # confirms this one's unread messages (§5:6).
        telegram_line: TelegramLineSeams | None = None
        telegram_intake: SqliteTelegramIntakeRecord | None = None
        if settings.telegram_connection is not None and settings.telegram_user_id is not None:
            telegram_intake = SqliteTelegramIntakeRecord(
                path=telegram_intake_path(
                    directory,
                    reference=settings.telegram_connection,
                    chat_id=settings.telegram_user_id,
                )
            )
            opened.append(telegram_intake.close)
            line_transport: OutboundTransport
            if transport is not None:
                line_transport = transport
            elif telegram_relay is None:
                line_transport = StreamOutboundTransport()
            else:
                line_transport = StreamOutboundTransport(anchors=telegram_relay.anchors)
            telegram_line = TelegramLineSeams(
                client=HttpsTelegramBotClient(
                    reference=settings.telegram_connection,
                    chat_id=settings.telegram_user_id,
                    records=connections,
                    secrets=integration_secrets,
                    exchange=HttpsExchange(
                        transport=line_transport,
                        max_response_bytes=settings.telegram_max_response_bytes,
                    ),
                    relay=telegram_relay,
                ),
                intake=telegram_intake,
                reference=settings.telegram_connection,
                poll_wait=settings.telegram_poll_wait,
                poll_bound=settings.telegram_poll_bound,
                send_bound=settings.telegram_send_bound,
                start_wait=settings.telegram_start_wait,
            )
        engine = Engine(
            plans=plans,
            trail=trail,
            # The **ledger** face of that same object, and never the gate
            # (ADR-0194 §5): one holder over one set of rows, so the totals a user
            # reads and the ceiling the seam enforces cannot disagree — while an
            # adapter reaching this member acquires no route to an admission.
            spend=trail,
            # The very trail the upcoming-event driver records into, handed over
            # **whole** here and narrowed to `SourceReadRecorder` there (ADR-0185 §4,
            # ADR-0186 §10). This is the only position that names the wide seam, and
            # it is what makes `recent_reads` and `export_reads` answer about the
            # reads that actually happened rather than about an empty second store.
            reads=reads,
            # ADR-0276's understanding stage, over the **same** model seam the phases
            # reach through — the routing-over-retrying provider built
            # above, which carries ADR-0011's retry policy. The stage reads no store
            # and receives no goal, plan, memory retrieval or context state.
            understanding=UnderstandingStage(
                model=model,
                excerpt_chars=UNDERSTANDING_EXCERPT_CHARS,
                prompt=prompts[UNDERSTANDING_PROMPT.name],
                diagnostics=diagnostics,
            ),
            understanding_version_limit=UNDERSTANDING_VERSION_LIMIT,
            # ADR-0282's windows stage, holding the initial episode selector over the
            # one memory store. The selector is the method ADR-0276 §4 makes a wiring
            # choice: swapping it is a change on this line and nowhere else.
            windows=WindowsStage(episodes=episode_selector),
            # ADR-0281's recall stage, over the same memory store, with the threshold
            # chosen for the embedder that store was built with, and the one story
            # store, where it looks up the stories of the episodes it keeps (ADR-0300
            # §7).
            recall=RecallStage(
                memory=memory,
                stories=stories,
                threshold=RECALL_THRESHOLDS[settings.embedder],
                limit=RECALL_ITEM_LIMIT,
                budget=RECALL_BUDGET,
                diagnostics=diagnostics,
            ),
            stage_record_limit=STAGE_RECORD_LIMIT,
            # ADR-0349 §9:2-§9:3: the most inputs one activation holds, its own with
            # every one it absorbed or took, and the most entries understanding's
            # in-progress section shows.
            held_input_limit=settings.held_input_limit,
            in_progress_limit=settings.in_progress_limit,
            # ADR-0289 §4's nine story methods read and write this store, and the
            # story summary view lists this many notes (ADR-0303 §10:2).
            stories=stories,
            story_summary_notes=STORY_SUMMARY_VIEW_NOTES,
            # ADR-0300 §6: the candidate stories understanding is shown, read from the
            # same story store and the one memory store, and the stage that records
            # its links there with the actor `understanding`. Wired together, as the
            # engine requires.
            story_candidates=StoryCandidates(
                stories=stories,
                memory=memory,
                limit=UNDERSTANDING_STORY_CANDIDATES,
                lines=STORY_SHORT_VIEW_LINES,
                notes=STORY_SHORT_VIEW_NOTES,
                episodes=STORY_SHORT_VIEW_EPISODES,
            ),
            story_links=StoryLinksStage(stories=stories),
            # ADR-0300 §9:3's matters pass, as ADR-0302 §5 builds it, which the
            # scheduler's `matters_pass` row runs on consolidation's interval. On
            # **consolidation's route**, for the tidy-up's reason: background work over
            # the assistant's own records that nobody waits on, and a flag whose
            # completion fails is decided on a later run, so it needs no fallback. Over
            # the same story store and memory store as every other story reader.
            matters_pass=MattersPass(
                model=consolidation_model,
                stories=stories,
                memory=memory,
                excerpt_chars=MATTERS_PASS_EXCERPT_CHARS,
                flags_per_run=MATTERS_PASS_FLAGS_PER_RUN,
                decisions=MATTERS_PASS_DECISIONS,
                episodes=MATTERS_PASS_EPISODES,
                notes=MATTERS_PASS_NOTES,
                budget=settings.scheduler_run_budget,
                # ADR-0334 §3:5: its instruction, as read at start, default or override.
                prompt=prompts[MATTERS_PASS_PROMPT.name],
            ),
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
            # The same store the phases recall from and the writer persists to, so
            # the inspection surface lists the beliefs the assistant actually uses
            # and ``forget`` destroys what the user was shown (ADR-0073 §7).
            memory=memory,
            # The seventh database's **deletion seam**, and a store the one
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
            # ADR-0314 §4:4, §7:2: the controller's step entries go through the sink,
            # where the record is on; the sweep takes the record and its window always.
            diagnostics=diagnostics,
            diagnostic_retention=diagnostic_record,
            diagnostic_window=settings.diagnostic_retention,
            # ADR-0323 §2:2: the line's spoke, where it is configured; the engine starts
            # its reader with the hub and stops it with it.
            telegram=telegram_line,
            # ADR-0350 §7:1, §12:5: the Task Scheduler, on every deployment: its sensor
            # starts with the hub and stops with it, and its six settings bound it. A
            # restart settles the pushed occurrences of the hub's one person, the owner
            # (ADR-0338 §2:2). Its times are read and rendered in the person's zone: the
            # engine reads their profile's from the person block's store wired below, and
            # `zone` is `Settings.timezone`, where it sets none or the person model is
            # off (ADR-0340 §3:3, §6:1).
            task_scheduler=TaskSchedulerSeams(
                limits=TaskManagerLimits(
                    chain_limit=settings.task_scheduler_chain_limit,
                    pending_limit=settings.task_scheduler_pending_limit,
                    listing_bound=settings.task_scheduler_listing_bound,
                ),
                recheck=settings.task_scheduler_recheck_interval,
                lateness_grace=settings.task_scheduler_lateness_grace,
                push_limit=settings.task_scheduler_push_limit,
                zone=settings.timezone,
                persons=(OWNER_PERSON_ID,),
            ),
            # ADR-0329 §7:6, §15:1: the observer, run on each frozen episode and by the
            # scheduler's `observer` row.
            observer=observer,
            # ADR-0338 §7:1: the person block's assembly over the person-model store and
            # the same `memory`, with lane 1's two bounds, where the switch is on; none
            # where it is off, so no activation is given a block (§11:2).
            person_blocks=(
                None
                if person_model is None
                else PersonBlocks(
                    store=person_model,
                    memory=memory,
                    budget_chars=KEPT_IN_MIND_CHARS,
                    suggestions=PLANNING_SUGGESTIONS,
                )
            ),
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
                # ADR-0347 §4:1: the story store each episode's admission write reads
                # its position from, the one every story stage writes.
                stories=stories,
            ),
            # Leg 10's upcoming-event producer (ADR-0132). **The first holder of
            # ADR-0130 §3's seam**, and the reason `notification_writer` above
            # exists at all.
            #
            # **Its own reader, its own grant scope, its own cadence** — three
            # independences ADR-0132 states separately because each is a different
            # ADR's rule. The reader is not shared (§3, ADR-0096 §5); the read is
            # gated on `NOTIFY` and on nothing else, so a live `INGEST`
            # grant on this calendar authorises it not at all (§2, ADR-0133 §2);
            # and its interval is its own field (§4).
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
            # (§6), as the hub's default: quiet windows are read in the zone of the
            # person a notification is for, and in this value where theirs is empty
            # (ADR-0338 §3:6, superseding §6:4's single source). A zone is never an
            # argument to a ruling, because a caller free to vary it could move the
            # user's night: the engine picks, per ruling, which policy to hand over,
            # this one or one `_policy_for_zone` built for the person's zone. And
            # `Settings` has already refused an unknown IANA zone at load, as the
            # person-model store refuses one on every write (§3:2).
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
            # ADR-0338 §3:6: the same factory the write stage holds; the engine reads
            # the owner's zone from the store its person block reads, where it is on.
            notification_policy_for=_policy_for_zone,
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
            # **Each source's readers carry that source's own location** (ADR-0102
            # §6), so the disclosure a client renders before a user grants is *this*
            # source's path and never a sibling's. A grant given against the wrong
            # disclosed location is the uninformed grant ADR-0097 §9a exists to
            # prevent, arriving through a wiring shortcut rather than through an
            # encoding.
            grant_operations=GrantOperations(
                store=grants,
                sources=_held_sources(
                    settings,
                    calendar=(facet_reader, upcoming_reader),
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
                # The follow-up asker first (ADR-0337 §8:16): once the façade has drained
                # every activation, a follow-up not yet sent is not sent, and nothing
                # keeps the queue. It writes into the record, which owns nothing to close.
                *([follow_ups.aclose] if follow_ups is not None else []),
                _as_async(memory.close),
                _as_async(trail.close),
                # And the story store: no store reads it and it reads none (ADR-0289
                # §1), so nothing constrains its position, and the façade drains any
                # story call in flight before this list is walked.
                _as_async(stories.close),
                # And the person-model store where it is open (ADR-0338 §10:1): it reads no
                # other store and none reads it, and the façade has drained every
                # activation that reads it through the person block before this runs.
                *([_as_async(person_model.close)] if person_model is not None else []),
                _as_async(plans.close),
                _as_async(conversations.close),
                # The grant store joins the same ordered shutdown as the other
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
                # And the simulated booking provider's store, where a deployment
                # configured one (ADR-0273 §2). It is an *"ordinary store of this
                # deployment"* and owes the same ordered shutdown as the rest, and it
                # has to be **here** as well as on the build-failure list above:
                # registered there alone, it would be closed when the build failed and
                # never when it succeeded, which is #1903 exactly — and here it would
                # leave a `-wal` holding booking records behind, which carry what the
                # user asked (§2's Tier 1 half).
                #
                # **Nothing constrains its position** among the stores: no store reads
                # it and it reads none — it is reached only by this provider's own act,
                # which the façade has drained before any of these run.
                *([_as_async(booking.store.close)] if booking is not None else []),
                # And the simulated booking provider's store, where a deployment
                # configured one (ADR-0273 §2). It is an *"ordinary store of this
                # deployment"* and owes the same ordered shutdown as the rest, and it
                # has to be **here** as well as on the build-failure list above:
                # registered there alone, it would be closed when the build failed and
                # never when it succeeded, which is #1903 exactly — and here it would
                # leave a `-wal` holding booking records behind, which carry what the
                # user asked (§2's Tier 1 half).
                #
                # **Nothing constrains its position** among the stores: no store reads
                # it and it reads none — it is reached only by this provider's own act,
                # which the façade has drained before any of these run. Beside the
                # connection store, because the same provider reads that one per call.
                # And the trace store as the seventh (ADR-0119 §6). Closed **last
                # although it is now opened first**, which is the one place this
                # list deliberately departs from open order: the memory store and
                # the writer above emit into it (§8), so a trace written on the way
                # down has to find the connection still open. The façade drains
                # in-flight work before any of these run, so what this protects is
                # the tail of that drain rather than a race with it.
                #
                # And the Telegram line's intake record before it, where the line is
                # configured (ADR-0323 §5:8, §13:2). No store reads it and it reads
                # none; the façade has stopped the line's reader and drained its
                # activation, so no claim is in flight when it closes.
                *([_as_async(telegram_intake.close)] if telegram_intake is not None else []),
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
            # ADR-0309 §2:6: the phases, built above, which plan every activation, and
            # the longer budget their rounds need.
            phases=phases,
            chat_turn_budget=PHASES_TURN_BUDGET,
            # ADR-0332 §5:1-§5:2, §5:6: the hub chat's start wait, and the composing
            # signal that extends it.
            chat_start_wait=settings.chat_start_wait,
            chat_composing_lapse=settings.chat_composing_lapse,
            chat_composing_cap=settings.chat_composing_cap,
        )
        # The **same** trace store again, narrowed a third way (ADR-0119 §7): a
        # ``TraceSink`` for `service`'s startup stamp, which appends one
        # ``CONFIGURATION`` trace and can no more walk the store than an emitter
        # inside the pipeline can. The figure beside it is §9's effective ``search``
        # limit, read off the constant this build tuned the ingestor with rather than
        # off ``Settings``, which does not hold it. Recall has none (ADR-0319 §4).
        return Composition(
            engine=engine,
            trace_sink=traces,
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
    credential, and the commands that did not — ``beliefs`` and ``forget`` among
    them, neither of which touches a model — are not
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

    Every route is checked — the router's whole preference order, consolidation's
    own and the observer's two — because ADR-0285 §5 gives each of those one spec that
    never falls back (ADR-0329 §9:9), so a credential it lacks disables the background
    work riding it silently rather than being covered by a sibling. Duplicates are checked once;
    consolidation's spec defaults to ``default_model``, and repeating the probe
    would only repeat the message.

    Args:
        settings: Loaded application settings — the router's preference order and
            consolidation's route.

    Raises:
        ConfigurationError: If a spec names a vendor whose package is missing or
            unknown, or one for which this deployment holds no credential. One
            class for both, which is what lets the hub map every startup
            misconfiguration to a single exit code through one type check
            (ADR-0083 §5).
    """
    for spec in dict.fromkeys(
        (
            *_model_specs(settings),
            _consolidation_spec(settings),
            _observer_scout_spec(settings),
            _observer_commit_spec(settings),
        )
    ):
        # In this order: the vendor check owns the "package not installed" message
        # and names the extra to install, and the credential probe presumes the
        # vendor resolved. Repeating a check `build_engine` also runs is cheap and
        # deliberate — the same reasoning `_build_consolidation_provider` records for
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


@dataclass(frozen=True, slots=True)
class _PhaseSeams:
    """The objects the composition root already built that the phases reuse.

    Each is the **same** instance the rest of the composition holds, for that
    object's own reason:
    one trail every ruling is recorded in, one plan store every effect is claimed in,
    one story store the backstop's match is read from, one memory store, one egress
    binder, one registry that is also the invoker, and one tidy-up, so at
    most one run is on a story at a time (ADR-0300 §5:10).
    """

    model: ModelProvider
    registry: InMemoryToolRegistry
    plans: PlanStore
    trail: AuditTrail
    stories: StoryStore
    memory: MemoryStore
    binder: EgressBinder
    chat: ConversationStore
    searcher: WebSearcher | None
    max_payload_bytes: int
    forecaster: Forecaster | None
    booking_configured: bool
    tidy_up: StoryTidyUp
    diagnostics: DiagnosticSink | None = None


def _build_phase_path(
    settings: Settings,
    seams: _PhaseSeams,
    *,
    planning_prompt: PromptTemplate,
    digesting_prompt: PromptTemplate,
) -> PhasePath:
    """The phases, which plan every activation (ADR-0309 §2:6, §4).

    **The capabilities planning is offered** are every one the phases' tools advertise
    (ADR-0306 §2:7): each the registry holds — the current time, ``send_email`` where an
    account is connected, and the simulated booking provider's availability read and
    booking act, which are in the registry only where a deployment configured the
    provider whole (ADR-0273 §1, ADR-0309 §4:2) — and, beside them, the configured web
    search and the assistant's own records' declarations. The search is in no registry
    (ADR-0231 §5), so :class:`PhaseTools` adds its declaration beside the registry's for
    authorizing's selection, as it adds remembering's. **And planning's story calls that
    write** (ADR-0300 §10, ADR-0303 §9): start, note, link, unlink, tidy-up, move, merge,
    split and group, in no registry either, each run through acting's own-records seam
    by one :class:`StoryCalls` over the one story store, memory store and tidy-up, with
    the arguments that name things by label handed to planning (ADR-0307 §5:2), and the
    same runner checking a move or a split before it is authorized (§5:3-§5:4). **And
    planning's look-ups** (§6:6): a memory search, a story's full view and the
    follow-up, in no registry either, each run through the own-records seam by one
    :class:`LookUps` over the one memory store and the story views' reads. **And the
    weather pull** (ADR-0324 §5:4), where a forecaster is configured: the forecast read
    is in no registry (ADR-0260 §1, ADR-0324 §5:5), so :class:`PhaseTools` offers it
    beside the registry's capabilities as it offers the search, fills every argument it
    takes from the forecaster's own proposal and sends its call to ``Forecaster.read``.

    **Candidates** (ADR-0329 §§3-6): ``remember`` is offered recording a candidate, run
    by a :class:`CandidateCalls` whose lookup is the look-ups' (§4:1), and noting
    reliance is offered beside it (§6:7). ADR-0328 §13's interim, under which
    ``remember`` wrote a memory, is retired with the switch that kept it.

    **The policy is the deployment's thresholds and configured providers, with no
    goal authorizations, no goal quotes and no grant seam** (ADR-0306 §4:11, §6;
    ADR-0321 §7:1): a ``ThresholdActionPolicy`` built from the settings, so no ruling
    a phase asks for reads the goal model or a standing grant. A candidate passes no
    ``MemoryPolicy`` (ADR-0329 §5:6).

    **Planning** asks through pydantic-ai's native tool calling, on the deployment's
    default model (ADR-0307 §10); **a digest** is a plain completion on the routed
    ``ModelProvider`` the other stages reach through, with no ``model=`` override
    (ADR-0308 §4:10). The numbers are the provisional ones above (#2589).

    **The configured providers' route** (ADR-0247 §2-§4, ADR-0260 §6). Authorizing is
    told which tools are this deployment's own registered search and its configured
    forecast read, so their calls carry ``closed_loop`` and ``forecast_reach``
    (ADR-0247 §4, ADR-0260 §6), and the policy reaches its configured-provider
    route, which the stand-in keeps (ADR-0306 §4:4).

    **A connected account's destination is the hub's** (ADR-0306 §2:10): the search's
    is its searcher's proposal, and the booking provider's two capabilities take the
    configured endpoint as their ``origin``, so planning is offered none of them.
    """
    policy = ThresholdActionPolicy(
        confirm_at_risk=settings.confirm_at_risk,
        confirm_at_reversibility=settings.confirm_at_reversibility,
        deny_at_risk=settings.deny_at_risk,
        deny_at_reversibility=settings.deny_at_reversibility,
        configured_search=_configured_search(
            settings.web_search_connection, _search_destinations(settings.web_search_origin)
        ),
        configured_forecast=_configured_forecast(
            settings.forecast_connection, _forecast_destinations(settings.forecast_origin)
        ),
    )
    story_calls = StoryCalls(stories=seams.stories, memory=seams.memory, tidy_up=seams.tidy_up)
    # ADR-0307 §6:1: the story views, over the one story store, memory store and plan
    # store; a short view is read as understanding's are, at its bounds. The same reads
    # give a story read its full view (§6:6).
    story_reads = StoryReads(
        stories=seams.stories,
        memory=seams.memory,
        plans=seams.plans,
        short_views=StoryCandidates(
            stories=seams.stories,
            memory=seams.memory,
            limit=UNDERSTANDING_STORY_CANDIDATES,
            lines=STORY_SHORT_VIEW_LINES,
            notes=STORY_SHORT_VIEW_NOTES,
            episodes=STORY_SHORT_VIEW_EPISODES,
        ),
        episodes=PHASES_STORY_EPISODES,
    )
    # ADR-0307 §6:6: planning's look-ups, a memory search over the one memory store and
    # a story's full view through the same story reads, and the follow-up, which acting
    # runs against the activation's held results (ADR-0308 §6:6).
    look_ups = LookUps(
        memory=seams.memory, views=story_reads, search_limit=PHASES_MEMORY_SEARCH_LIMIT
    )
    tools = PhaseTools(
        registry=seams.registry,
        invoker=seams.registry,
        own_records=(REMEMBER_CANDIDATE, *STORY_CALLS, *LOOK_UPS),
        # ADR-0329 §6:7: noting reliance, beside the candidate.
        reliance=NOTE_RELIANCE,
        searcher=seams.searcher,
        # ADR-0324 §5:4: the weather pull, where a forecaster is configured.
        forecaster=seams.forecaster,
        search_query=SEARCH_QUERY_ARGUMENT,
        # Both of the simulated provider's capabilities are offered (ADR-0309 §4:2), and
        # both name the configured endpoint as their ``origin``: the hub's to fill and
        # never planning's to write (ADR-0306 §2:10).
        fills=(
            {
                str(capability): {BOOKING_ORIGIN_ARGUMENT: settings.booking_endpoint}
                for capability in (BOOKING_AVAILABILITY.capability, BOOKING_ACT.capability)
            }
            if seams.booking_configured and settings.booking_endpoint is not None
            else None
        ),
    )
    return PhasePath(
        completer=PydanticAIToolCallingCompleter(
            settings.default_model, diagnostics=seams.diagnostics
        ),
        provider=seams.model,
        authorizing=AuthorizingStage(
            registry=tools,
            policy=policy,
            trail=seams.trail,
            stories=seams.stories,
            memory=seams.memory,
            binder=seams.binder,
            # ADR-0321 §4:4, §4:11, §6:1: the yes path's facts are read from the one
            # plan store acting claims in.
            plans=seams.plans,
            preference=Preference(TOOL_PREFERENCE),
            registered_search=(
                frozenset() if seams.searcher is None else frozenset({WEB_SEARCH_ID})
            ),
            registered_forecast=(
                frozenset({FORECAST_READ_ID}) if seams.forecaster is not None else frozenset()
            ),
            now=_utcnow,
            diagnostics=seams.diagnostics,
        ),
        acting=ActingStage(
            plans=seams.plans,
            invoker=tools,
            own_records=OwnRecordsByCapability(
                {
                    # ADR-0329 §4:1: a candidate's lookup, under the look-ups' scope.
                    REMEMBER_CAPABILITY: CandidateCalls(
                        similar=look_ups, limit=CANDIDATE_LOOKUP_LIMIT
                    ),
                    **dict.fromkeys(STORY_CALL_CAPABILITIES, story_calls),
                    **dict.fromkeys(LOOK_UP_CAPABILITIES, look_ups),
                }
            ),
            timeout=PHASES_CALL_DEADLINE,
            now=_utcnow,
        ),
        tools=tools,
        plans=seams.plans,
        writer=ChatWriter(conversations=seams.chat, max_payload_bytes=seams.max_payload_bytes),
        label_arguments={
            **STORY_LABEL_ARGUMENTS,
            **LOOK_UP_LABEL_ARGUMENTS,
            **CANDIDATE_LABEL_ARGUMENTS,
            **RELIANCE_LABEL_ARGUMENTS,
        },
        # ADR-0307 §5:3-§5:4: the hub's check of a move or a split before authorizing,
        # against the stories as they stand then, by the same runner acting reaches.
        story_calls=story_calls,
        # The look-ups' runner, whose scope the path opens around acting (§6:6).
        look_ups=look_ups,
        round_limit=PHASES_ROUND_LIMIT,
        round_wait=PHASES_CALL_DEADLINE,
        excerpt_chars=PHASES_EXCERPT_CHARS,
        # ADR-0334 §3:5: planning's instruction, as read at start, default or override.
        planning_prompt=planning_prompt,
        digesting_prompt=digesting_prompt,
        part_chars=PHASES_DIGEST_PART_CHARS,
        # ADR-0308 §3, §4:4: planning and recall's digest fetch recall's kept records
        # from the one memory store recall searched; the second run itself is the
        # engine's recall stage, handed over with its first run (§2:1).
        memory=seams.memory,
        recall_cap=RECALL_SECOND_RUN_CAP,
        recall_digest_wait=PHASES_RECALL_DIGEST_DEADLINE,
        story_reads=story_reads,
        now=_utcnow,
        # #2964: planning tells the time in the user's zone, the one `Settings.timezone`
        # the spend and notification policies read, validated at load.
        timezone=settings.timezone,
        diagnostics=seams.diagnostics,
    )


def diagnostic_record_directory(settings: Settings, *, data_dir: Path | None = None) -> Path:
    """Where this deployment's diagnostic record is (ADR-0314 §6:1).

    The composition root's statement of the path, because it is where the record is
    created: the backup reads its exclusion from here (§7:5, ADR-0123 §3:3), as it
    reads the trace store's from :func:`build_measure_reader`.

    Args:
        settings: Loaded application settings — ``data_dir`` locates the record.
        data_dir: Overrides ``settings.data_dir`` when given, as :func:`build_engine`'s
            keyword does.

    Returns:
        ``<data_dir>/diagnostics``.
    """
    directory = data_dir if data_dir is not None else settings.data_dir
    return directory / DIAGNOSTIC_DIRECTORY


def refuse_a_follow_up_without_the_record(settings: Settings) -> None:
    """Refuse a start that would ask the follow-up with no record to keep it in (ADR-0337 §8:2).

    The follow-up is asked of a recorded call and its answer kept in the diagnostic
    record (§8:4, §8:9), so ``follow_up_question`` true with ``diagnostic_record`` false
    is a configuration that could do neither. It is refused before the API accepts a
    request, naming both settings.

    Args:
        settings: Loaded application settings.

    Raises:
        ConfigurationError: Naming both settings, where the start is refused.
    """
    if settings.follow_up_question and not settings.diagnostic_record:
        msg = (
            "follow_up_question is on and diagnostic_record is off: the follow-up is "
            "asked of recorded calls and kept in the diagnostic record; turn "
            "diagnostic_record on or follow_up_question off"
        )
        raise ConfigurationError(msg)


def _follow_up_asker(
    settings: Settings, diagnostics: DiagnosticSink | None, prompt: PromptTemplate
) -> FollowUpAsker | None:
    """The follow-up asker around the record's sink, where it asks (ADR-0337 §8:5, §8:8).

    Each route's follow-up goes to the first model of the stage's own route, or, where a
    planning response names the model that answered, to that model of the same provider:
    planning, understanding and a digest's parts to ``default_model``, which leads the
    routed order and is the one planning's completer asks (:func:`_model_specs`); the
    observer's two steps each to its own step's model. Its deadline is the one every
    route's attempt is held to, ``model_timeout_seconds``, and it asks with the
    planning completer's own thinking, the default.

    Args:
        settings: Loaded application settings.
        diagnostics: The record's sink, or ``None`` where the record is off.
        prompt: The ``follow_up`` template, as read at start (ADR-0337 §6:1).

    Returns:
        ``None`` where ``follow_up_question`` is false or there is no sink to wrap.
    """
    if not settings.follow_up_question or diagnostics is None:
        return None
    first = _model_specs(settings)[0]
    return FollowUpAsker(
        diagnostics,
        prompt=prompt,
        routes={
            "understanding": first,
            "planning": first,
            "digesting": first,
            "observer.scout": _observer_scout_spec(settings),
            # ADR-0346 §10:2: framing and placement ride the commit step's route.
            "observer.framing": _observer_commit_spec(settings),
            "observer.placement": _observer_commit_spec(settings),
        },
        daily_calls=settings.follow_up_daily_calls,
        timeout=settings.model_timeout_seconds,
    )


def refuse_an_unswept_diagnostic_record(settings: Settings, record_directory: Path) -> None:
    """Refuse a start whose diagnostic record nothing would sweep (ADR-0314 §7:4).

    Where ``retention_purge_interval`` is disabled, nothing deletes the record's
    files, so the window that is the record's forgetting would not run. The hub then
    refuses to start while ``diagnostic_record`` is true or the directory holds a
    file. It reads the directory's listing and no entry.

    Args:
        settings: Loaded application settings.
        record_directory: The record's directory, from
            :func:`diagnostic_record_directory`.

    Raises:
        ConfigurationError: Naming the directory, where the start is refused.
    """
    if settings.retention_purge_interval is not None:
        return
    if settings.diagnostic_record:
        msg = (
            f"the diagnostic record is on, and the retention purge job that deletes its "
            f"files under {record_directory} after diagnostic_retention is disabled; "
            f"enable retention_purge_interval or turn diagnostic_record off"
        )
        raise ConfigurationError(msg)
    if _holds_a_file(record_directory):
        msg = (
            f"the diagnostic record's directory {record_directory} holds files, and the "
            f"retention purge job that deletes them is disabled; enable "
            f"retention_purge_interval, or remove them"
        )
        raise ConfigurationError(msg)


def _holds_a_file(directory: Path) -> bool:
    """Whether ``directory``'s listing names anything that is not a directory.

    Raises:
        ConfigurationError: If the directory exists and cannot be listed.
    """
    try:
        with os.scandir(directory) as listing:
            return any(not entry.is_dir(follow_symlinks=False) for entry in listing)
    except FileNotFoundError:
        return False
    except NotADirectoryError:
        return True
    except OSError as exc:
        msg = f"could not list the diagnostic record's directory {directory}: {exc}"
        raise ConfigurationError(msg) from exc


def read_prompts(settings: Settings, *, data_dir: Path | None = None) -> dict[str, PromptTemplate]:
    """Every prompt's template, default or override, read and checked once (ADR-0334 §3).

    Each of :data:`PROMPTS` takes its default from beside the module that sends it
    (§3:1); where ``prompt_overrides`` is true, a file ``<name>.txt`` in
    ``<data_dir>/prompts`` replaces it whole (§3:3). Where it is false no file there is
    read, and the start is refused while the directory holds anything. Each template's
    name, version and origin is logged, and nothing of its text (§8:3). Nothing is
    created, written or deleted (§5:3).

    Args:
        settings: Loaded application settings: ``prompt_overrides``, and ``data_dir``
            unless ``data_dir`` is given.
        data_dir: Overrides ``settings.data_dir`` when given, as :func:`build_engine`'s
            keyword does.

    Returns:
        Each prompt's template, by its name.

    Raises:
        ConfigurationError: Naming the file and its defect, and never its content,
            where the start is refused (§5:1): ``prompt_overrides`` is false and the
            directory holds anything; ``prompts`` is not a directory; an entry in it
            is not a regular file or names no prompt; a file is not UTF-8, holds only
            whitespace, or is not a well-formed template of its prompt; or the
            directory or a file in it is owned by another user, or writable by its
            group or by others.
    """
    templates = {declaration.name: _default_prompt(declaration) for declaration in PROMPTS}
    directory = (data_dir if data_dir is not None else settings.data_dir) / (
        PROMPT_OVERRIDE_DIRECTORY
    )
    for template in _prompt_overrides(directory, enabled=settings.prompt_overrides):
        templates[template.name] = template
    for template in templates.values():
        _log.info(
            "prompt_template",
            prompt=template.name,
            version=template.version,
            origin=template.origin.value,
        )
    return templates


def _default_prompt(declaration: PromptDeclaration) -> PromptTemplate:
    """The prompt's shipped default, from the package that sends it (§3:1).

    Raises:
        ConfigurationError: If the build ships no such file, or a malformed one.
    """
    resource = files(declaration.package).joinpath(declaration.filename)
    try:
        data = resource.read_bytes()
    except OSError as exc:
        msg = f"the default prompt template {declaration.filename} could not be read: {exc}"
        raise ConfigurationError(msg) from exc
    try:
        return PromptTemplate.parse(declaration, data, origin=PromptOrigin.DEFAULT)
    except ConfigurationError as exc:
        msg = f"the default prompt template {declaration.filename}: {exc}"
        raise ConfigurationError(msg) from None


def _prompt_overrides(directory: Path, *, enabled: bool) -> list[PromptTemplate]:
    """The overrides ``directory`` holds, each checked before it is read (§5:1).

    The directory is opened once, without following a link, and each file is opened
    from that descriptor, so every check is made on the object that is read. The
    directory's owner and mode are checked whether or not overrides are on (§5:1 makes
    neither refusal depend on the setting); where they are off, nothing in it is read.

    Raises:
        ConfigurationError: Where the start is refused; see :func:`read_prompts`.
    """
    descriptor = _open_override_directory(directory)
    if descriptor is None:
        return []
    try:
        _refuse_unsafe(os.fstat(descriptor), f"the prompt override directory {directory}")
        names = _listed(descriptor, directory)
        if not enabled:
            if names:
                msg = (
                    f"prompt_overrides is false and the prompt override directory {directory} "
                    f"holds {len(names)} entries; remove them, or set prompt_overrides on the "
                    f"owner's hub (ADR-0334 §5:1)"
                )
                raise ConfigurationError(msg)
            return []
        return [_override(descriptor, directory, name) for name in names]
    finally:
        os.close(descriptor)


def _listed(descriptor: int, directory: Path) -> list[str]:
    """The names the open directory holds, sorted, so a refusal names the same one each time.

    Raises:
        ConfigurationError: If the directory cannot be listed.
    """
    try:
        with os.scandir(descriptor) as listing:
            return sorted(entry.name for entry in listing)
    except OSError as exc:
        msg = f"the prompt override directory {directory} could not be listed: {exc.strerror}"
        raise ConfigurationError(msg) from None


def _override(descriptor: int, directory: Path, name: str) -> PromptTemplate:
    """The override ``name`` in the open directory, read and parsed against its prompt.

    Raises:
        ConfigurationError: If it names no prompt, or is refused as it is read or parsed.
    """
    shown = directory / name
    declaration = next((one for one in PROMPTS if one.filename == name), None)
    if declaration is None:
        msg = f"the prompt override {shown} names no prompt"
        raise ConfigurationError(msg)
    data = _read_override(descriptor, name, shown=shown)
    try:
        return PromptTemplate.parse(declaration, data, origin=PromptOrigin.OVERRIDE)
    except ConfigurationError as exc:
        msg = f"the prompt override {shown}: {exc}"
        raise ConfigurationError(msg) from None


def _open_override_directory(directory: Path) -> int | None:
    """``directory`` opened without following a link, or ``None`` where there is none.

    Raises:
        ConfigurationError: If it is there and is not a directory, or cannot be opened.
    """
    try:
        found = os.lstat(directory)
    except FileNotFoundError, NotADirectoryError:
        # No directory, or no data directory for it to be in: the data directory's own
        # preparation reports the second (#372).
        return None
    except OSError as exc:
        msg = f"the prompt override directory {directory} could not be read: {exc.strerror}"
        raise ConfigurationError(msg) from None
    if not stat.S_ISDIR(found.st_mode):
        msg = f"the prompt override path {directory} is not a directory"
        raise ConfigurationError(msg)
    try:
        return os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except OSError as exc:
        if exc.errno in {errno.ENOTDIR, errno.ELOOP}:
            msg = f"the prompt override path {directory} is not a directory"
        else:
            msg = f"the prompt override directory {directory} could not be opened: {exc.strerror}"
        raise ConfigurationError(msg) from None


def _read_override(directory: int, name: str, *, shown: Path) -> bytes:
    """One override's bytes, read only once it is known to be a safe regular file.

    Opened without following a link and without blocking, so a link, a pipe or a
    device is refused rather than read or waited on.

    Raises:
        ConfigurationError: If it is not a regular file, or is unsafe (§5:1).
    """
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
    try:
        descriptor = os.open(name, flags, dir_fd=directory)
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            msg = f"the prompt override {shown} is not a regular file"
        else:
            msg = f"the prompt override {shown} could not be opened: {exc.strerror}"
        raise ConfigurationError(msg) from None
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            msg = f"the prompt override {shown} is not a regular file"
            raise ConfigurationError(msg)
        _refuse_unsafe(info, f"the prompt override {shown}")
        chunks: list[bytes] = []
        try:
            while chunk := os.read(descriptor, _READ_CHUNK):
                chunks.append(chunk)
        except OSError as exc:
            msg = f"the prompt override {shown} could not be read: {exc.strerror}"
            raise ConfigurationError(msg) from None
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _refuse_unsafe(info: os.stat_result, shown: str) -> None:
    """Refuse what another user owns, or what its group or others may write (§5:1).

    Raises:
        ConfigurationError: Naming ``shown`` and which of the two it is.
    """
    if info.st_uid != os.geteuid():
        msg = f"{shown} is owned by uid {info.st_uid}, not by the hub's uid {os.geteuid()}"
        raise ConfigurationError(msg)
    if info.st_mode & _WRITABLE_BY_OTHERS:
        msg = f"{shown} is writable by its group or by others; chmod go-w it"
        raise ConfigurationError(msg)


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


def _consolidation_spec(settings: Settings) -> str:
    """The one ``"provider:model"`` spec of consolidation's route (ADR-0285 §5).

    The consolidation stage retired; the route stays, and the story tidy-up and the
    matters pass ride it (ADR-0328 §14:4).

    ``consolidation_model`` when the operator named one; otherwise ``default_model``
    — **the route already configured for conversation**, and deliberately not the
    whole ``fallback_models`` preference order, because this route never falls back
    (:func:`_build_consolidation_provider`).

    That default is what makes the setting cost nothing to have: it names no
    provider the operator did not already configure, so ADR-0004 §2's property —
    user data reaches only providers the user explicitly configured — cannot be
    breached by leaving it unset. What the setting buys is that the choice is
    *nameable and separable*: an operator who wants stored records read by a
    smaller, cheaper or locally-hosted model changes one value and does not touch
    the route their answers come from.

    Args:
        settings: Loaded application settings.

    Returns:
        The spec, never empty: ``default_model`` stands behind it.
    """
    return (
        settings.consolidation_model
        if settings.consolidation_model is not None
        else settings.default_model
    )


def _build_consolidation_provider(settings: Settings, spec: str) -> RetryingProvider:
    """Build consolidation's model seam: **retry, and no routing at all** (ADR-0285 §5).

    The deliberate difference from :func:`_build_model_provider`: **a call on this
    route is never re-sent to a second provider.** The route outlived the stage it is
    named for (ADR-0328 §14:4); the story tidy-up and the matters pass ride it, and
    what follows was argued for consolidation and holds for both: each is
    background work over the assistant's own records that nobody waits on.
    ADR-0013 §4 already rules the mechanism — "a caller who names a model has
    already chosen" — and its own Consequences decide the case:

    * fallback's cost is that *more providers may see a given prompt*, which for a
      turn buys an answer the user is waiting for. A background run buys nothing
      with it, because the work is **deferrable**: nothing is waiting, and the free
      remedy is the next run.
    * it is the one payload where the trade inverts. A turn's prompt is one
      utterance; a background prompt carries the assistant's stored records, so
      widening the set of recipients for reliability is exactly what ADR-0004 §7's
      minimisation rule argues against when the reliability buys nothing.

    So the route is a :class:`RetryingProvider` and not a
    :class:`RoutingProvider` — there is no second candidate for a routable failure
    to advance to, rather than a router that happens to hold one route. **Retry is
    not fallback**: it re-sends to the *same* provider, so it widens no recipient
    set, and dropping it would make this route less resilient than every other
    call for no privacy gain.

    The route **requires its own credential** (ADR-0013 §6), which follows from the
    same shape: nothing stands behind it, so a provider the deployment cannot
    authenticate to fails the run rather than quietly diverting the records
    somewhere it can.

    Args:
        settings: Loaded application settings — the resilience knobs the retry
            wrapper is built from, the same ones every other route gets, because how
            patient this deployment is is not a property of which vendor answered.
        spec: Consolidation's ``"provider:model"`` spec (:func:`_consolidation_spec`).

    Returns:
        The provider the background work reads stored records through.

    Raises:
        ConfigurationError: If ``spec`` names a vendor unknown to pydantic-ai or
            whose optional package is not installed — checked here for the reason
            ADR-0062 §2 gives, so an operator learns at startup rather than on the
            first background run. It is checked even when it repeats
            ``default_model``: the check is cheap, and a helper that trusted a caller
            to have checked already would break the day the two stop coinciding.
    """
    ensure_vendor_available(spec)
    return RetryingProvider(PydanticAIProvider(spec), policy=RetryPolicy.from_settings(settings))


def _observer_scout_spec(settings: Settings) -> str:
    """The ``"provider:model"`` spec the observer's scout reads through (ADR-0329 §9:9).

    ``observer_scout_model`` when the operator named one; otherwise ``default_model``,
    on :func:`_consolidation_spec`'s argument: the default names no provider the operator
    did not already configure (ADR-0004 §2).

    Args:
        settings: Loaded application settings.

    Returns:
        The spec, never empty: ``default_model`` stands behind it.
    """
    named = settings.observer_scout_model
    return named if named is not None else settings.default_model


def _observer_commit_spec(settings: Settings) -> str:
    """The ``"provider:model"`` spec the observer's commit step decides through (§9:9).

    Framing and placement both ride it (ADR-0346 §10:2), the commit step cut in two.
    ``observer_commit_model`` when the operator named one; otherwise ``default_model``,
    for :func:`_observer_scout_spec`'s reason.

    Args:
        settings: Loaded application settings.

    Returns:
        The spec, never empty: ``default_model`` stands behind it.
    """
    named = settings.observer_commit_model
    return named if named is not None else settings.default_model


def _build_observer_provider(settings: Settings, spec: str) -> RetryingProvider:
    """Build one of the observer's model seams: **one attempt, and no routing** (§9:9).

    No routing, by ADR-0285 §5:3's rule, which ADR-0329 §9:9 applies: the observer's work
    is deferrable — an episode that fails waits and is retried (§16:4) — so fallback
    would buy nothing and widen the set of providers shown the user's episodes and
    memories.

    **And no retry inside the call**, which is where it parts from consolidation's
    shape. The observer counts every model call against its daily budget, recording it
    before it is made (§16:9); a retrying wrapper would send several requests under
    that one record, so the budget would bound records rather than calls. The
    observer's own retry is the recorded backoff of a failed attempt (§16:4), each of
    whose calls is counted. The wrapper stays for its per-attempt deadline
    (``model_timeout_seconds``), so a hung call ends and frees the one run (§16:6).

    Args:
        settings: Loaded application settings — the deadline every route gets.
        spec: The route's ``"provider:model"`` spec.

    Returns:
        The provider the step reads through.

    Raises:
        ConfigurationError: If ``spec`` names a vendor unknown to pydantic-ai or whose
            optional package is not installed, so the build fails rather than the first
            run (ADR-0062 §2).
    """
    ensure_vendor_available(spec)
    policy = replace(RetryPolicy.from_settings(settings), max_attempts=1)
    return RetryingProvider(PydanticAIProvider(spec), policy=policy)


def _reconciler_spec(settings: Settings) -> str:
    """The one ``"provider:model"`` spec the reconciler labels through (ADR-0159 §3).

    ``reconciler_model`` when the operator named one; otherwise ``default_model``.
    The same shape :func:`_consolidation_spec` has, and the same argument: the default
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

    Consolidation's shape (:func:`_build_consolidation_provider`), reached by the same
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
        The provider the reconciler labels through, as its ``StructuredCompleter``
        (ADR-0354 §6:2): ``RetryingProvider`` implements it beside ``complete``.

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

    **The location is per source rather than per deployment**: this reads the
    calendar's field, and :func:`_held_sources` pairs each reader with its own
    source's. What is *not* answered is ADR-0093 §11's registry, in which a location
    becomes a property of a registered source rather than of a named field —
    ADR-0102 §10's normative clause still owes that lane a re-derivation of the
    enumeration's worst case.
    """
    if settings.calendar_reader_path is None:
        return None
    return str(settings.calendar_reader_path)


def _held_sources(
    settings: Settings,
    *,
    calendar: Sequence[Reader | None],
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

    **Keyed by source**, which is what keeps the pairing honest: a source added
    beside the calendar arrives as its own keyword with its own location, never
    under the calendar's. Email is not one (ADR-0320 §3).

    Args:
        settings: Where each source's configured location comes from.
        calendar: The calendar readers this root built, ``None`` for each consumer
            of an unconfigured source.

    Returns:
        One :class:`~ai_assistant.orchestration.grants.HeldSource` per reader
        actually built. Empty when no source is configured, which is the shipping
        default and the state in which ``grantable_sources`` offers nothing
        (ADR-0093 §7).
    """
    location = _configured_calendar_location(settings)
    return [HeldSource(reader.name, location=location) for reader in calendar if reader is not None]


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
