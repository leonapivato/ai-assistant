"""The phases' thin path: one activation's rounds, wired across the phase modules.

**Glue, and not a phase module** (ADR-0309 §2:3). Each phase takes and returns its own
shapes, because no phase module imports another; this module converts between them,
holds what they decide in the episode's working set, and runs each as a controller
stage. It is outside the ``independence`` contract over the phase modules, so it may
import all of them, and none of them imports it.

**Every activation** (ADR-0309 §2:6). The composition root always builds a
:class:`PhasePath`, and the engine hands the controller its one table,
:data:`~ai_assistant.orchestration.controller.ACTIVATION_RULES`, and these stages for a
conversation turn the chat's reader starts, and for an event ``receive`` admits
(ADR-0313 §4:3).

**An event** (ADR-0313 §4:3-§4:5, ADR-0307 §3:8, ADR-0309 §5:5-§5:6). It runs as one
activation whose place takes no message: :meth:`PhasePath.begin_event` starts its
working set with no conversation, so planning is told up front that its text is kept and
written nowhere, authorizing is handed no message to check and no place, and the event
cannot message the user. Its rounds' text is kept with the episode's rounds, and nothing
is written for it, the *couldn't finish* message included. Having written nothing is not
how an event fails to finish, since it never writes: only the round limit, a stage's
failure or its deadline is, the loop guard counting as a stage's failure (ADR-0317
§3:3), and the engine reads which from the state.

**What one round is** (ADR-0307 §2, ADR-0309 §3). Planning asks the model once and
records the round; authorizing checks every call by rule and the message by its place;
acting runs the allowed calls and writes the message, with digesting beside it reading
each held result as acting holds it (§3:3); and the next round is due where the round
made a call other than a tidy-up, once its calls have finished (ADR-0315 §2:1). Each is
one controller step, and each decision is held here, in :class:`PhaseWorking`, present
once its stage has run whatever came of it (ADR-0280 §3:6).

**The conversions** (the brief's item 3). Planning's recorded round becomes
authorizing's :class:`~ai_assistant.orchestration.authorizer.RoundToAuthorize`, and
authorizing's decision acting's :class:`~ai_assistant.orchestration.acting.
AuthorizedRound`. Acting's outcomes and the digests become planning's
:class:`~ai_assistant.orchestration.planning.CallOutcome` and
:class:`~ai_assistant.orchestration.planning.DigestedEvidence`, each item under its
source's planning label (ADR-0308 §4:15). One
:class:`~ai_assistant.orchestration.digesting.ActivationLabels` holds the activation's
labels, seeded from the episode and given each round's. Whether the activation has read
digested evidence (ADR-0308 §5:4) reaches authorizing as the digests on its
:class:`~ai_assistant.orchestration.authorizer.WorkingRecord`.

**The recorders** (ADR-0307 §2:4, ADR-0308 §5:2). Planning's ``RoundRecorder`` and
digesting's ``DigestRecorder`` are one object here, which adds the round or the digest,
with its labels, to the activation's state and extends the open episode through the
episode writer. A failed append is a capture failure, which the writer handles and
which holds nothing back.

**The wait before an act, and the commitment step** (ADR-0349 §7:12-§7:14). Before
acting dispatches any call of a round that is not a pure read, or the round's message,
it waits for each newer input that could absorb the activation or offer to it, on any
place before it has committed and on its own place after, bounded by the pass's
deadline. Then, in one synchronous step with no await before the dispatch: where the
stop mark is set, nothing of the round runs; where an offer is open that the round's
planning was not shown, the round is held back — none of its calls runs and its message
is not written, by any path, and acting's decision for it says so — and planning runs a
round again, shown the offer; and otherwise the activation is marked committed.
Planning starts over for each understanding version (ADR-0332 §3:12). An input a take
brought on the activation's own place is shown to planning as an input item of the
place (ADR-0349 §7:21).

**The waits on an older activation** (ADR-0349 §7:25-§7:28). Planning holds them: while
its offer is open it plans no round; where it then waits on work still running, its
first round is a waiting round, on which every call but the stop and a message comes back
refused (ADR-0356 §4:5), and its next is planned once
each activation it waits on has ended, the time waited moving its deadline later. Every
round is shown the finished work of what it absorbed, took input from and waited on,
read fresh (§7:10, §7:27), and an older's planning the offers open to it (§7:19).

**The message** (ADR-0307 §3, ADR-0306 §5). The round's text is written into the
input's place through the chat's writer, claimed first under an
:class:`~ai_assistant.core.types.ActivationEffect` and finished with the position the
medium returns, beside the round's calls. An empty text writes nothing; where the place
takes no message the text is kept with the round and written nowhere. **An activation
whose last round made no call but a tidy-up has finished**, whatever its rounds wrote:
one that wrote nothing chose silence, ends done and writes nothing (ADR-0317 §2). The
fixed *couldn't finish* message is written where the round limit, the loop guard, a
stage's failure or a deadline ended the activation, whatever earlier rounds wrote, and
where its last message was refused by authorizing or its write did not come back done,
with none recorded after it (ADR-0317 §3); a stop, a cancellation and a restart write
nothing (§3:6). Wherever it is written the activation did not finish, so its episode
freezes ``failed`` and the conversation's current state reads *couldn't finish* beside
the message (ADR-0293 §8:3): a stage's failure classifies as it is, and an activation
that returned on the round limit, the loop guard or an undelivered last message is
``failed / processing_failed`` (ADR-0317 §3:5). The activation's messages, joined by a
blank line, are the episode's ``outcome`` at the freeze (ADR-0307 §10).

**A work's exchange, and each call's entry** (ADR-0356 §4:3, §5, §8). Every round of
every activation is offered one tool set, in one fixed order (:meth:`PhasePath._offered`):
the registry's capabilities, the person model's, the Task Scheduler's and the calls on
running work where each is attached, and ``text`` last. A call whose condition for
running does not hold comes back refused before authorizing, saying why
(:meth:`PhasePath._not_here`). The working set holds the work's exchange,
:class:`~ai_assistant.orchestration.planning.PlanningWork`, in memory alone, and hands it
to each round. Each call's entry is appended to the episode once what came of it is
known, before the next round's request, and every call still without one gets one at
the freeze, with no outcome (:meth:`PhaseWorking.call_entries`).

**A** ``text`` **call** (ADR-0356 §7:7-§7:8). It is taken out of the round's calls before
authorizing, which checks it by its place alone as the round's message: the place its
``via`` label names, or the input's where it names none. Allowed, it is claimed and
written as the round's message is, under an effect record naming its round and finished
with the position the medium recorded, and its entry holds the words the place took,
where they went and how. ``text``'s other arguments, its wording step and its result's
shape are ADR-0357's lane T1's.

**What wrote each message** (ADR-0303 §7:1, ADR-0306 §5:3). The chat's reader links an
assistant message in the window to the activation that wrote it, by the effect record
its message carries with its position; :meth:`PhasePath.written` is that read, over the
plan store's records of the candidate activations the reader names. A message the old
path wrote has no record, and stays not linkable (§7:5).

**The capabilities planning is offered** (ADR-0306 §2:7, ADR-0309 §4:2). Every one
:class:`PhaseTools` advertises, unless the path is handed a fixed list: each the
deployment's registry holds — the simulated booking act only where a deployment
configured it — and the assistant's own records' declarations, remembering, the story
calls and the look-ups, beside the configured search. The search is registered at the
egress seam and in no ``ToolRegistry`` (ADR-0231 §5), and the own records' calls run
against the assistant's own records (ADR-0306 §3:3), so :class:`PhaseTools` puts their
declarations in front of authorizing's selection beside the deployment's registry, and
routes a search call to the ``WebSearcher`` that proposes and performs it. The search's
``origin`` is the connected account's: planning is offered the search without it, and
the hub fills it from the searcher's own proposal (``WebSearcher.request``). **The
weather pull** (ADR-0324 §5) is offered beside them where a forecaster is configured, as
the search is: the forecast read is in no ``ToolRegistry`` either (§5:5), planning writes
none of its arguments (§3:1), the hub fills them all from the forecaster's own proposal
(``Forecaster.request``), and a forecast read is routed to ``Forecaster.read``. Its
answer reaches planning only as a digest's evidence (§2:3), the digest given its channel
and author as the hub's attribution (§2:4), and a digest that answered marks the
activation as having read outside content (§9:1). **The clock
apart** (#2942): planning's input carries the current time, so it is never offered
``report_current_time``, which would spend a round (ADR-0315 §2:1) reading what it has
(ADR-0211's decline test). The registry keeps the tool (ADR-0048 §1), and a call naming
it is refused as any capability planning was not offered is.

**Recall's second run** (ADR-0308 §2, ADR-0309 §3's row 6). The controller runs one
stage per name, so :meth:`PhasePath.recall_stage` hands it one ``recall`` stage: the
engine's first run where the pass has no recall decision, and the second run, on the
latest understanding's meaning and gaps, where it has one. The rows decide which is
due. The second run's decision is held in :class:`PhaseWorking` and carried on the
activation's state, and understanding never reads it (§2:8).

**What planning is shown of what recall found** (ADR-0308 §3). Before its first round,
planning fetches both runs' kept ids in one read, the audience predicate applied again
(ADR-0282 §2:4-§2:8), and holds what came back. A found episode is shown by its records
under its label with the labels of the stories it is in; a found memory record is shown
only where its source is not outside (ADR-0306 §5:16). Every outside memory record is
withheld: it reaches planning only as recall's digest's evidence.

**Recall's digest** (ADR-0308 §4:4-§4:6, ADR-0309 §3's row 7). Once the second run has
decided, the ids of every memory record either run kept whose source is outside are
held beside its decision, and where there are any, ``recall_undigested`` makes
``digesting`` due before planning's first round. The controller runs one stage per
name, so :meth:`PhasePath.stages` hands it one ``digesting`` stage: recall's digest
while that row's facts hold, and a round's digests beside acting otherwise. Recall's
digest fetches its records by id through the same read planning's fetch uses
(ADR-0282 §2:4-§2:8), holds what it fetched and what came back missing, and answers the
latest understanding's meaning; its evidence reaches planning under each record's own
label, and a failed one tells planning it could not read recall's outside records. It
is failure-tolerant (§4:12), and once decided, whatever came of it, its row does not
answer again; ADR-0280 §4:6's guard ends a pass that would run it twice (ADR-0309
§3:5). Its deadline is the composition root's, cut to what the pass has left.

**The story views** (ADR-0307 §6:1, §6:3-§6:4, ADR-0300 §8). Before each round,
:class:`StoryReads` reads the stories the activation belongs to, as the story store
holds its links then, and gives planning each one's summary state, the episodes newer
than its summary and its latest, the short views of the stories it is part of, and where
its matter stands, what was done included from the plan store's effect records; and the
short view of each story understanding cited as a referent that the activation is not
in. Each is read under the pass's audience: the summary and notes by whether a record
placed for the owner alone may be shown (ADR-0304 §4), the episodes and where the matter
stands by the audience predicate (ADR-0282 §2:8). A story-store or plan-store failure
shows planning that the stories could not be read, and planning goes on. A view resting
on outside content, a marked summary or note, an episode resting on outside content by
its own record, or a marked moment of where a matter stands, sets the working set's
``fetched_outside``, which reaches authorizing's ruling and planning's notes alike
(ADR-0306 §4:5-§4:6), and names what set it, which authorizing gives the diagnostic
record as the ground's record (ADR-0314 §4). Every note shown is held in the working
set with its mark and handed to authorizing, which reads each ``N`` label's mark from
it, so a note the user wrote is not counted as outside content read.

**The story calls** (ADR-0300 §10, ADR-0303 §9). Planning names stories by ``S`` label
and activations by their episodes' ``E`` labels; the composition root hands this path
which of each offered capability's arguments are labels, and planning maps them to ids
or refuses the call whole (ADR-0307 §5:2-§5:3). Each runs through acting's own-records
seam, **the tidy-up apart**: it is started in a task of its own that nothing awaits,
neither the next round nor the activation's end (ADR-0307 §7:2), which the engine
tracks so its shutdown drains it, and whatever came of it, it brings no round (§7:1).

**Planning's look-ups** (ADR-0307 §6:6, ADR-0308 §6). A memory search, a story's full
view and the follow-up run through acting's own-records seam, inside a
:meth:`~ai_assistant.orchestration.lookups.LookUps.scope` this path opens around acting
for the round, so they read under the pass's audience. A memory search's records whose
source is not outside are fetched by id before the next round, the audience predicate
applied again (ADR-0282 §2:4-§2:8), and held under the result's id, every later round
shown the same records; its outside records are held by acting by id, and its digest
fetches them by id the same way. A story's full view, read when its call ran, is held
under the call's result; it shows a page of the story's older notes too, those a tidy-up
has taken in, under the notes' placement, so a move or a split can name them (#2893).
Resting on outside content, older notes included, it sets ``fetched_outside``, as a
story view does, and the notes it shows are held with their marks for authorizing. A
follow-up's result is the result it names, as held, which digesting reads again against
the follow-up's question.

**The episode's placement** (ADR-0309 §5:10, ADR-0204 §2, ADR-0217 §3:12). The working
set holds a :class:`~ai_assistant.orchestration.supplied_records.SuppliedRecords`, handed
every memory record the activation is given or obtains as it arrives: the windows'
records, the episodes of the candidate stories understanding was shown, what either
recall run kept, what a call returned, a web search's records and a digest's included,
and what a story view shows. The value is taken once, at the freeze, over every round,
the windows' records left out on a pass of unbounded audience, and the episode is placed
for the owner alone where it is ``True``.

**Candidates** (ADR-0329 §§3-6). A ``remember`` call records a candidate, and a
candidate's result lists the memories similar to its fact by id, which are fetched by id
before the next round as a memory search's are, the audience predicate applied again,
and handed planning with the outcome (§4:1); one whose lookup failed is handed on saying
so (§4:4). Before the first round, the episode window's episodes the observer has not
processed are read with :func:`~ai_assistant.orchestration.candidates.pending_candidates`,
and each one's pending candidates are handed planning by its fact (§6:9). A call noting
reliance has no effect, so it reaches :class:`PhaseTools`, which answers it done and
reaches nothing (§6:7).

**The person model's calls, where a store is wired** (ADR-0338 §8:4-§8:8, §11:2). The
engine attaches the person block's assembly with :meth:`PhasePath.attach_person_model`
exactly where it is handed one; unattached, as on every hub whose switch is off, nothing
below is reached. Attached, ``set_profile``, ``pin`` and ``unpin`` are advertised beside
the own records' other declarations and offered to every round, refused in an
activation given no person block (ADR-0356 §4:5); a ``pin``'s and an ``unpin``'s memory
is named by ``M`` label; each runs through acting's own-records seam, by
:class:`~ai_assistant.orchestration.person_calls.PersonModelCalls`. Before each round,
the memory each such call that needs the user names is read from the memory store, so
its question shows the memory's wording in place of its label (§8:6); one whose memory
is gone, or rests on outside content, which no question shows (ADR-0307 §9:2), cannot be
asked about.

**Left to later lanes:** the calendar pull (ADR-0324 §4, §6), which needs its grant use,
``PULL``; the weather pull is built (§5).

**It logs stage and code-owned reason only** (ADR-0275 §8), and a defect by its class
and the frames it passed through, never its message (:func:`log_defect`).
"""

from __future__ import annotations

import asyncio
import contextlib
import contextvars
import json
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Final, Protocol
from uuid import uuid4

import structlog

from ai_assistant.core.clock import checked_clock
from ai_assistant.core.episode_encoding import project_episode, question_marks
from ai_assistant.core.errors import (
    ActivationStoppedError,
    ClaimStopped,
    ConversationStoreError,
    MemoryStoreError,
    ModelTimeoutError,
    PlanningError,
    StoryStoreError,
)
from ai_assistant.core.types import (
    MAX_STORY_PAGE,
    RECALLED_ITEMS_MAX,
    TRANSCRIPT_MESSAGE_MAX_CHARS,
    ActivationEffect,
    ActivationRecall,
    ApprovalGiver,
    CallShowed,
    CapabilityEffect,
    CapabilityResult,
    ChannelIdentity,
    ControllerRule,
    ControllerStage,
    DeletedMessage,
    DeliveryStatus,
    DigestOutcome,
    EpisodicMemory,
    ForecastRefusal,
    LabelKind,
    Memory,
    MemoryKind,
    MemoryStatus,
    MessageAuthor,
    Modality,
    NewMessage,
    PlanningLabel,
    ProfileField,
    ProjectedCall,
    ProjectedEvidence,
    ProjectedRecall,
    ProjectedRound,
    ProposedCall,
    QuestionPart,
    RecallOutcome,
    RecordedCall,
    RecordedDelivery,
    SendOutcome,
    ShownRecord,
    ShownRecordKind,
    StageOutcome,
    StoryMember,
    StoryMemberKind,
    StoryRelation,
    ToolDefinition,
    ToolFailure,
    ToolFailureKind,
    ToolOutcome,
    ToolResult,
    parties_are_outside,
    parties_are_persons_own,
)
from ai_assistant.orchestration.acting import (
    ActedCall,
    ActedOutcome,
    ActedRound,
    ActingStage,
    AuthorizedCall,
    AuthorizedRound,
    ResultRoute,
)
from ai_assistant.orchestration.activation_state import CaptureFacts, Commitment, active_state
from ai_assistant.orchestration.authorizer import (
    AllowedCall,
    AuthorizingStage,
    CallToAuthorize,
    MessageVerdict,
    RoundAuthorization,
    RoundMessage,
    RoundToAuthorize,
    Verdict,
    WorkingRecord,
    YesContext,
)
from ai_assistant.orchestration.candidates import pending_candidates
from ai_assistant.orchestration.channel_kinds import place_of
from ai_assistant.orchestration.chat import couldnt_finish
from ai_assistant.orchestration.controller import (
    Stage,
    StageResult,
    TolerantStage,
    recall_digest_due,
)
from ai_assistant.orchestration.conversations import conversation_channel
from ai_assistant.orchestration.defects import ToleratedStageError, is_defect, log_defect
from ai_assistant.orchestration.digesting import ActivationLabels, Digested, DigestingStage
from ai_assistant.orchestration.episode_lookups import OlderSource
from ai_assistant.orchestration.episode_reads import without_open_episodes
from ai_assistant.orchestration.held_results import HeldResult, HeldResults
from ai_assistant.orchestration.lookups import (
    OLDER_NOTES_PAGE,
    READ_STORY_CAPABILITY,
    SEARCH_MEMORY_CAPABILITY,
    searched_ids,
)
from ai_assistant.orchestration.matter_calls import (
    MATTER_CALLS,
    MATTER_CAPABILITIES,
    MATTER_LABEL_ARGUMENTS,
    MatterCaller,
    MatterCalls,
    calling,
)
from ai_assistant.orchestration.matters import (
    ANSWER_OFFER_CAPABILITY,
    LOOK_UP_ACTIVATION_CAPABILITY,
    STOP_ACTIVATION_CAPABILITY,
    NotAsAsked,
    is_pure_read,
)
from ai_assistant.orchestration.message_tools import (
    EMAIL_CAPABILITY,
    EMAIL_CHANNEL_TYPE,
    EXACT_ARGUMENT,
    PLACE_LABEL,
    PLATFORMS,
    TEXT_CALL,
    TEXT_CAPABILITY,
    WORDS_ARGUMENT,
    TextArguments,
    emailed_to,
    platform_name,
    platform_type,
    reworded,
    text_arguments,
    who_it_is_for,
    with_question,
)
from ai_assistant.orchestration.outside_content import rests_on_outside_content
from ai_assistant.orchestration.person_block import still_held
from ai_assistant.orchestration.person_calls import (
    PERSON_MODEL_CALLS,
    PERSON_MODEL_CAPABILITIES,
    PERSON_MODEL_LABEL_ARGUMENTS,
    PersonModelCalls,
    worded_argument,
)
from ai_assistant.orchestration.planning import (
    WAITING_ROUND,
    ApprovedAction,
    CallOutcome,
    CallOutcomeKind,
    DigestedEvidence,
    DigestItem,
    EpisodeRead,
    EpisodesFound,
    OfferShown,
    OlderHistory,
    PeerShown,
    PlaceAuthor,
    PlaceItem,
    PlaceWindow,
    PlannedRound,
    PlanningInputs,
    PlanningStage,
    PlanningStories,
    PlanningStory,
    PlanningWork,
    RecordedCandidate,
    RefusedCall,
    RunningShown,
    ShowingLabels,
    answer_fact,
    call_showed,
    shown_within,
)
from ai_assistant.orchestration.recall import Recalled
from ai_assistant.orchestration.reliance import noted
from ai_assistant.orchestration.remembering import (
    REMEMBER_CAPABILITY,
    candidate_similar,
    is_candidate_result,
)
from ai_assistant.orchestration.stories import episode_address
from ai_assistant.orchestration.story_calls import TIDY_STORY_CAPABILITY
from ai_assistant.orchestration.story_links import admitted_episodes
from ai_assistant.orchestration.story_privacy import SummaryVisibility
from ai_assistant.orchestration.story_standing import story_standing
from ai_assistant.orchestration.supplied_records import SuppliedRecords
from ai_assistant.orchestration.task_scheduler import (
    TASK_SCHEDULER_CALLS,
    TASK_SCHEDULER_CAPABILITIES,
    TASK_SCHEDULER_DESCRIPTION,
    TASK_SCHEDULER_LABEL_ARGUMENTS,
    Spawner,
    decode_listing,
    spawning,
)
from ai_assistant.orchestration.understanding import AskedIn, WrittenBy, fetch_held

if TYPE_CHECKING:
    from collections.abc import (
        Awaitable,
        Callable,
        Collection,
        Coroutine,
        Iterable,
        Iterator,
        Mapping,
        MutableMapping,
        Sequence,
    )

    from ai_assistant.core.prompts import PromptTemplate
    from ai_assistant.core.protocols import (
        DiagnosticSink,
        Forecaster,
        MemoryStore,
        PlanStore,
        StoryStore,
        StructuredCompleter,
        ToolCallingCompleter,
        ToolInvoker,
        ToolRegistry,
        WebSearcher,
    )
    from ai_assistant.core.types import (
        ActivationDigest,
        ActivationUnderstanding,
        AnsweredQuestion,
        ForecastOutcome,
        FrozenJson,
        JoinedInput,
        MemoryRecord,
        MessageReceipt,
        PlanningRound,
        RecordedChannelTrigger,
        ScheduledTask,
        SearchOutcome,
        StoryNote,
        StoryStanding,
        StorySummaryState,
        ToolCall,
        TranscriptMessage,
    )
    from ai_assistant.orchestration.activation_state import ActivationState
    from ai_assistant.orchestration.controller import ControllerStageRun
    from ai_assistant.orchestration.disclosure import TurnSupply
    from ai_assistant.orchestration.lookups import EpisodeLookedUp, LookUps
    from ai_assistant.orchestration.matters import Matters
    from ai_assistant.orchestration.person_block import PersonBlock, PersonBlocks
    from ai_assistant.orchestration.planning import FullViewPart
    from ai_assistant.orchestration.recall import RecallStage
    from ai_assistant.orchestration.story_calls import StoryCalls
    from ai_assistant.orchestration.story_links import Candidates, ShortView, StoryCandidates
    from ai_assistant.orchestration.task_manager import ScheduledTaskCalls
    from ai_assistant.orchestration.task_scheduler import ListedPlace
    from ai_assistant.orchestration.understanding import (
        Fetched,
        LineMessage,
        TranscriptWindow,
        Windows,
    )

__all__ = [
    "CHAT_DESCRIPTION",
    "EVENT_DESCRIPTION",
    "SHOWED_CHARS",
    "Delivery",
    "Fitted",
    "MessageWriter",
    "PhasePass",
    "PhasePath",
    "PhaseTools",
    "PhaseWorking",
    "PlaceTarget",
    "PlaceWriter",
    "Scheduling",
    "StoryReads",
    "authorized_round",
    "call_outcomes",
    "digested_evidence",
    "failing_stage",
    "is_defect",
    "log_defect",
    "place_window",
]

_log = structlog.get_logger(__name__)

#: The conversation channel kind's description, which planning is shown with the place
#: (ADR-0307 §6:1, ADR-0292 §8:1). No store holds a kind's description yet, so the thin
#: path states the chat's here.
CHAT_DESCRIPTION: Final = (
    "The hub's chat: a conversation with the user, on the devices they chose for it. "
    "A message you write is added to this conversation for the user to read."
)

#: The informational-event channel kind's description, shown with its place as the
#: chat's is (ADR-0292 §8:1); stated here for the same reason. The place takes no
#: message (ADR-0307 §3:8), which planning's instruction says up front.
EVENT_DESCRIPTION: Final = (
    "An event a source reported to the hub, such as a device changing state. No one is "
    "waiting on a reply, and nothing you write here reaches the user."
)

#: The bound on what a call's entry keeps of what its result showed, in characters
#: (ADR-0358 §11:4), where the composition root names none, as a test's path does; the
#: composition root sets its own.
SHOWED_CHARS: Final = 4000

_PLANNING_EXPIRED: Final = "the activation's deadline passed before the next round"
_AUTHORIZING_EXPIRED: Final = "the activation's deadline passed before the round was checked"
_ACTING_EXPIRED: Final = "the activation's deadline passed before the round's calls ran"
_RECALL_EXPIRED: Final = "the activation's deadline passed during recall's second run"
_RECALL_DIGEST_EXPIRED: Final = "the activation's deadline passed before recall's digest"
#: The error a failed recall digest's tolerated stage result carries (ADR-0308 §4:12).
_RECALL_DIGEST_FAILED: Final = "recall's digest failed, so planning could not read its records"
#: What a recall decision makes of its stage's entry (ADR-0281 §5), for the second run
#: as for the first (ADR-0308 §2:7).
_RECALL_STAGE_OUTCOMES: Final = {
    RecallOutcome.FOUND: StageOutcome.DONE,
    RecallOutcome.NOTHING_FOUND: StageOutcome.DONE,
    RecallOutcome.FAILED: StageOutcome.FAILED,
    RecallOutcome.TIMED_OUT: StageOutcome.TIMED_OUT,
}
#: What acting decided, as the durable record would have it, for a call that may have
#: happened.
_ACTED_OUTCOMES: Final = {
    ActedOutcome.DONE: ToolOutcome.SUCCEEDED,
    ActedOutcome.UNKNOWN: ToolOutcome.INDETERMINATE,
}
_GONE: Final = "the place took no message: the conversation is gone or refused it"

#: The search refusals that leave a search's outcome unknown: it may have reached the
#: provider, and an unknown outcome is reported as unknown (ADR-0312 §2, ADR-0306 §5:13).
_UNKNOWN_SEARCHES: Final = frozenset({"deadline_expired", "transport_failed"})

#: The capabilities planning is never offered, though a registry holds them: the clock,
#: since planning's input carries ``now`` (#2942). ``tools`` declares it (ADR-0048 §1),
#: and ``orchestration`` names it by its capability.
_NOT_OFFERED: Final = frozenset({"report_current_time"})

#: Why a ``text`` call goes nowhere, by how ADR-0357 §2:4 fails to resolve its place.
_NO_PLACE_HERE: Final = "this activation's input came from no place that takes a message"
_SUGGESTS_SEVERAL: Final = "its task suggests more than one place, so via names one"
_SUGGESTS_NONE: Final = (
    "its task suggests no place and the line's chat is not on its list, so via names one"
)
#: The place check's refusal where it gave no reason of its own.
_NOT_ALLOWED_THERE: Final = "the message may not go there"
#: How much of a ``via`` that names nothing its coming back quotes.
_QUOTED_VIA_CHARS: Final = 40
#: The line's chat's channel type: where a task's message goes that suggests no place
#: (ADR-0357 §2:4).
_LINE_TYPE: Final = PLATFORMS["telegram"]


@dataclass(frozen=True, slots=True)
class _Nowhere:
    """Why a ``text`` call can go nowhere, with the places it may name (ADR-0357 §6:2)."""

    reason: str


#: Why a call whose condition for running does not hold in its activation runs nothing
#: (ADR-0356 §4:4-§4:6), each the condition that decided whether it was offered before.
_NO_PERSON: Final = "this activation is no person's, so it has no profile or pins to change"
_NO_SPAWN: Final = "only an activation that may set a task runs the Task Scheduler's calls"
_NO_RUNNING_VIEW: Final = (
    "running work is shown only to an activation whose author its place establishes, "
    "and this one's it does not"
)
_NO_AUTHORITY: Final = "a stop runs only on an input that carries the user's authority"
_NO_OFFER: Final = "no offer is open to this work, so there is none to answer"

#: Why a ``text`` call came back unknown: whether the place took it is not known.
_UNKNOWN_WRITE: Final = "whether the place took it is not known"

#: What a write's outcome tells of how a message went (ADR-0357 §3:2-§3:3).
_DELIVERY_STATUS: Final = {
    ToolOutcome.SUCCEEDED: DeliveryStatus.SENT,
    ToolOutcome.FAILED: DeliveryStatus.FAILED,
    ToolOutcome.INDETERMINATE: DeliveryStatus.UNKNOWN,
}
#: What a finished effect record's outcome is, as planning is shown a call's (ADR-0306 §6).
_EFFECT_OUTCOMES: Final = {
    ToolOutcome.SUCCEEDED: CallOutcomeKind.DONE,
    ToolOutcome.FAILED: CallOutcomeKind.NOT_DONE,
    ToolOutcome.INDETERMINATE: CallOutcomeKind.UNKNOWN,
}
_WRITE_OUTCOME: Final = {
    ToolOutcome.SUCCEEDED: CallOutcomeKind.DONE,
    ToolOutcome.FAILED: CallOutcomeKind.NOT_DONE,
    ToolOutcome.INDETERMINATE: CallOutcomeKind.UNKNOWN,
}

#: The activation whose round's calls are running, by what it holds of what it was given:
#: a search's records are handed to it as the search returns them (ADR-0309 §5:10).
_HOLDING: Final[contextvars.ContextVar[SuppliedRecords | None]] = contextvars.ContextVar(
    "phase_tools_holding", default=None
)

#: Where a pull's attribution is noted, by its call's decision id, for the digest that
#: reads its answer (ADR-0324 §2:4).
_ATTRIBUTING: Final[contextvars.ContextVar[MutableMapping[str, str] | None]] = (
    contextvars.ContextVar("phase_tools_attributing", default=None)
)

#: The activation whose round planning is deciding, set around planning's call, which
#: records the round inside it: the recorder reads from it whether the round's message
#: would be shown whole (ADR-0321 §4:4).
_PLANNING: Final[contextvars.ContextVar[PhaseWorking | None]] = contextvars.ContextVar(
    "phase_path_planning", default=None
)


# --- the seams this module is handed ---------------------------------------------------


class MessageWriter(Protocol):
    """The place's writer: *send a message* (ADR-0293 §6:10-§6:13).

    Structurally the chat's :class:`~ai_assistant.orchestration.chat.ChatWriter`.
    """

    def fitted(self, conversation_id: str, message: NewMessage) -> NewMessage:
        """``message`` exactly as :meth:`send` records it, cut to what a read returns."""
        ...

    async def send(self, conversation_id: str, message: NewMessage) -> MessageReceipt | None:
        """Write one assistant message into a conversation, or ``None`` where it is gone."""
        ...


@dataclass(frozen=True, slots=True)
class Delivery:
    """What came of writing one message into a place, as its effect record finishes it.

    ADR-0306 §5:5's three outcomes: done, with the position the medium recorded it at;
    not done, with why; or unknown, where it may have reached the medium.

    Attributes:
        outcome: ``SUCCEEDED``, ``FAILED`` or ``INDETERMINATE``.
        position: Where the medium recorded it; present exactly on a message done.
        reason: Why it was not done; only on ``FAILED``.
        written: The text the place now holds of it, which the episode records as sent
            (ADR-0284 §4:1): the whole message where it was done, what reached the
            place of a message cut short, and ``None`` where nothing did.
    """

    outcome: ToolOutcome
    position: int | None = None
    reason: str | None = None
    written: str | None = None

    def __post_init__(self) -> None:
        """A position is a done message's, and a reason a not-done one's.

        Raises:
            ValueError: If either rides on another outcome.
        """
        if (self.position is not None) != (self.outcome is ToolOutcome.SUCCEEDED):
            msg = "a delivery carries a position exactly where the message is done"
            raise ValueError(msg)
        if self.reason is not None and self.outcome is not ToolOutcome.FAILED:
            msg = "only a message not done carries why"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class Fitted:
    """A round's text as a place would write it: whole, or cut to fit its bounds.

    Attributes:
        text: What the place would write.
        cut_off: Whether anything of the round's text was cut to fit, so its message
            is not shown whole (ADR-0321 §4:4's *shown*).
    """

    text: str
    cut_off: bool = False


class PlaceWriter(Protocol):
    """One place's writer, as the phases write an activation's message into it.

    The hub chat's conversation is one, through its chat writer; the Telegram line's
    chat is another (ADR-0323 §6). The message is claimed under its effect record before
    :meth:`deliver` is called, and finished with what it returns (ADR-0306 §5:3-§5:5);
    the writer holds its channel's rules and its bounds, before anything leaves
    (ADR-0292 §8:3) — a conversation's transcript bound is the conversation's, and a
    line that splits a long message cuts none (ADR-0323 §6:6).
    """

    def fitted(self, text: str) -> Fitted:
        """``text`` exactly as :meth:`deliver` would write it.

        Raises:
            OversizedValueError: If no non-blank prefix fits the place's bounds.
        """
        ...

    async def deliver(self, fitted: Fitted, *, effect_id: str) -> Delivery:
        """Write ``fitted``, claimed under ``effect_id``, and say what came of it.

        Raises:
            Exception: Only for what the writer could not class; the phases then
                finish the record unknown, since it may have been written.
        """
        ...


@dataclass(frozen=True, slots=True)
class PlaceTarget:
    """The place an activation's messages go into, and its writer (ADR-0306 §4:7).

    Attributes:
        channel: The input's channel, whose place this is; its effect records name the
            place by :func:`~ai_assistant.orchestration.channel_kinds.place_of`.
        writer: The place's writer.
    """

    channel: ChannelIdentity
    writer: PlaceWriter

    @property
    def place(self) -> str:
        """The place, as a message's effect record names it."""
        return place_of(self.channel)


@dataclass(frozen=True, slots=True)
class _ConversationWriter:
    """The hub chat's writer, as a :class:`PlaceWriter` for one conversation.

    The conversation store's answers, read as ADR-0306 §5:5's outcomes: a store fault
    is unknown, since whether it recorded is not known; a conversation gone, or one
    that refused the message, is not done; and a message recorded is done, at its
    position.
    """

    writer: MessageWriter
    conversation_id: str

    def fitted(self, text: str) -> Fitted:
        """``text`` cut to the transcript's bound, then to the writer's (ADR-0293 §4:7)."""
        message = self._message(text)
        return Fitted(text=message.text, cut_off=message.cut_off)

    def _message(self, text: str) -> NewMessage:
        cut = len(text) > TRANSCRIPT_MESSAGE_MAX_CHARS
        return self.writer.fitted(
            self.conversation_id,
            NewMessage(
                author=MessageAuthor.ASSISTANT,
                text=text[:TRANSCRIPT_MESSAGE_MAX_CHARS],
                cut_off=cut,
            ),
        )

    async def deliver(self, fitted: Fitted, *, effect_id: str) -> Delivery:
        # ADR-0350 §12:9: the transcript records with the message the effect record it was
        # claimed under, so whether it was sent is read after a restart, never guessed.
        message = NewMessage(
            author=MessageAuthor.ASSISTANT,
            text=fitted.text,
            cut_off=fitted.cut_off,
            effect_id=effect_id,
        )
        try:
            receipt = await self.writer.send(self.conversation_id, message)
        except ConversationStoreError:
            # Whether the store recorded it is not known: unknown, with no position.
            _log.warning("phase_message_unwritten", stage="acting", reason="store_failed")
            return Delivery(ToolOutcome.INDETERMINATE)
        if (
            receipt is None
            or receipt.outcome is not SendOutcome.RECORDED
            or receipt.position is None
        ):
            _log.info("phase_message_unwritten", stage="acting", reason="place_gone")
            return Delivery(ToolOutcome.FAILED, reason=_GONE)
        return Delivery(ToolOutcome.SUCCEEDED, position=receipt.position, written=message.text)


class PhasePass(Protocol):
    """What a phase stage reads of the pass's working set (ADR-0280 §3).

    The engine's working set satisfies it: the pass's deadline and audience posture,
    the windows stage's decision, recall's first decision, the understanding the
    understanding stage recorded, what that phase fetched for the windows, the
    candidate stories it was shown, and the phases' own part, :class:`PhaseWorking`.
    """

    @property
    def deadline(self) -> float:
        """The pass's deadline, on the running loop's clock."""

    @property
    def supply(self) -> TurnSupply:
        """The pass's audience posture, which recall and every fetch filter by."""

    @property
    def windows(self) -> Windows | None:
        """The windows stage's decision, where it made one (ADR-0282 §3)."""

    @property
    def recalled(self) -> Recalled | None:
        """Recall's first decision, where it made one (ADR-0281 §6)."""

    @property
    def understanding(self) -> ActivationUnderstanding | None:
        """The understanding version the stage recorded, where it recorded one."""

    @property
    def understanding_fetch(self) -> Fetched | None:
        """The window's and recall's records the understanding phase fetched by id."""

    @property
    def story_candidates(self) -> Candidates | None:
        """The candidate stories the understanding phase was shown (ADR-0300 §6:1)."""

    @property
    def phases(self) -> PhaseWorking | None:
        """The phases' working set, where the pass runs them."""


# --- the capabilities --------------------------------------------------------------------


class PhaseTools:
    """The thin path's registry and invoker over the deployment's (ADR-0309 §4:2).

    Structurally a :class:`~ai_assistant.core.protocols.ToolRegistry` and a
    :class:`~ai_assistant.core.protocols.ToolInvoker`. The registry answers what the
    deployment's answers, and also each own-records declaration it is handed, such as
    remembering, the configured search's declaration and the configured forecast read's,
    so authorizing's selection reaches them. Neither of the last two is in the
    deployment's registry (ADR-0231 §5, ADR-0260 §1:4, ADR-0324 §5:5): each is offered
    beside the registry's capabilities here, the forecast read as the search is (§5:4).
    The invoker sends a search call to the ``WebSearcher``, a forecast read to the
    ``Forecaster`` (the weather pull, ADR-0324 §5), and every other call to the
    deployment's invoker. A call to the assistant's own records never reaches it: acting
    runs those directly (ADR-0306 §3:3).

    **The arguments the hub fills.** A connected account's destination is the hub's,
    never a model's: the search's ``origin`` is its searcher's own proposal, and a
    registered tool's, such as the booking act's, is the configured value ``fills``
    names. Planning is offered each capability without them, as it is offered none the
    declaration names in ``system_supplied`` (ADR-0306 §2:10), and they are filled
    before authorizing selects and rules. **The forecast read takes no argument planning
    writes** beyond the *looking for* the hub adds (ADR-0324 §3:1): its origin and its
    coordinate are all the forecaster's own proposal (``Forecaster.request``), so no
    place crosses the planning seam (§3:4, ADR-0260 §3:2).

    **A pull's answer is attributed by the hub** (ADR-0324 §2:4, §5:3). A forecast read
    that brought records back notes, under its call's decision, its channel and its
    author — the forecaster's ``name``, and the provider, a service, claimed, as of the
    ``reported_at`` the provider declared — where a :meth:`holding` scope is open, so the
    digest reading it is given them as the hub's attribution, never from its text.
    """

    def __init__(  # noqa: PLR0913 — the deployment's pair, the added declarations, the searcher, the forecaster, and the two ways the hub fills an argument
        self,
        *,
        registry: ToolRegistry,
        invoker: ToolInvoker,
        own_records: Sequence[ToolDefinition] = (),
        searcher: WebSearcher | None = None,
        forecaster: Forecaster | None = None,
        search_query: str = "query",
        fills: Mapping[str, Mapping[str, FrozenJson]] | None = None,
        reliance: ToolDefinition | None = None,
    ) -> None:
        """Wire the pair over the deployment's.

        Args:
            registry: The deployment's registry.
            invoker: The deployment's invoker, the same object in production.
            own_records: The declarations of capabilities on the assistant's own
                records, which no registry holds.
            searcher: The configured search, or ``None`` where no account is connected.
            forecaster: The configured forecast read, the weather pull's sensor
                (ADR-0324 §5:1), or ``None`` where no provider is configured.
            search_query: The one argument of the search planning writes; the hub
                fills every other from the searcher's own proposal.
            fills: For a registered capability, the arguments the hub fills and their
                configured values, such as a connected account's destination.
            reliance: The declaration of noting reliance (ADR-0329 §6:7), advertised
                beside the own records' and answered done here, reaching nothing; or
                ``None`` where it is not declared.
        """
        self._registry = registry
        self._invoker = invoker
        self._own_records = tuple(own_records)
        self._searcher = searcher
        self._forecaster = forecaster
        self._search_query = search_query
        self._fills = {
            capability: dict(arguments) for capability, arguments in (fills or {}).items()
        }
        self._reliance = reliance
        self._search: ToolDefinition | None = None
        self._forecast: ToolDefinition | None = None

    def add_own_records(self, declarations: Sequence[ToolDefinition]) -> None:
        """Advertise further declarations on the assistant's own records.

        For capabilities wired once the store they write is known: the person model's
        calls, attached where the engine is handed a person-model store (ADR-0338 §11:2).

        Args:
            declarations: The further declarations.

        Raises:
            ValueError: If one names a capability already advertised here.
        """
        held = {str(one.capability) for one in self._own_records}
        if any(str(one.capability) in held for one in declarations):
            msg = "a capability on the assistant's own records is declared once"
            raise ValueError(msg)
        self._own_records = (*self._own_records, *declarations)

    async def search_declaration(self) -> ToolDefinition | None:
        """The configured search's declaration, as its searcher proposes it, or ``None``.

        Read from the searcher's own proposal, once: the declaration a deployment
        registered carries its configured cost (ADR-0236 §1), so no copy is made here.
        """
        if self._search is None and self._searcher is not None:
            proposed = await self._searcher.request(self._search_query)
            if proposed is not None:
                self._search = proposed.tool
        return self._search

    async def forecast_declaration(self) -> ToolDefinition | None:
        """The configured forecast read's declaration, as its forecaster proposes it.

        Read from the forecaster's own proposal, once, as the search's is: the
        declaration a deployment registered carries its configured cost (ADR-0236 §1),
        so no copy is made here. ``None`` where no forecaster is configured, or where it
        proposes no read, which is a configuration fact (ADR-0260 §4).
        """
        if self._forecast is None and self._forecaster is not None:
            proposed = await self._forecaster.request()
            if proposed is not None:
                self._forecast = proposed.tool
        return self._forecast

    async def _extra(self) -> list[ToolDefinition]:
        search = await self.search_declaration()
        forecast = await self.forecast_declaration()
        reliance = () if self._reliance is None else (self._reliance,)
        configured = tuple(one for one in (search, forecast) if one is not None)
        return [*self._own_records, *reliance, *configured]

    async def get(self, tool_id: str) -> ToolDefinition | None:
        """The definition registered as ``tool_id``, the added ones included."""
        for one in await self._extra():
            if str(one.id) == tool_id:
                return one
        return await self._registry.get(tool_id)

    async def find(self, capability: str) -> list[ToolDefinition]:
        """Every tool advertising ``capability``, ordered by id, the added ones included."""
        found = [one for one in await self._extra() if str(one.capability) == capability]
        found.extend(await self._registry.find(capability))
        return sorted(found, key=lambda one: str(one.id))

    async def capabilities(self) -> tuple[str, ...]:
        """Every advertised capability, sorted and de-duplicated."""
        names = {str(one.capability) for one in await self._extra()}
        names.update(await self._registry.capabilities())
        return tuple(sorted(names))

    async def all_tools(self) -> list[ToolDefinition]:
        """Every definition, ordered by id, the added ones included."""
        every = [*await self._extra(), *await self._registry.all_tools()]
        return sorted(every, key=lambda one: str(one.id))

    async def offered(self, capabilities: Sequence[str]) -> tuple[ToolDefinition, ...]:
        """The declarations planning is offered, for the named capabilities (§4:2).

        Each is offered without the arguments the hub fills, which planning's offer
        leaves out as it leaves out any argument the declaration names in
        ``system_supplied`` (ADR-0306 §2:10). A capability no tool satisfies is not
        offered.
        """
        search = await self.search_declaration()
        forecast = await self.forecast_declaration()
        offered: list[ToolDefinition] = []
        for name in capabilities:
            for one in await self.find(name):
                if search is not None and one == search:
                    hidden = _properties(one) - {self._search_query}
                elif forecast is not None and one == forecast:
                    # Every argument the forecast read takes is the hub's (ADR-0324
                    # §3:1, §3:4): planning writes only the *looking for*.
                    hidden = _properties(one)
                else:
                    hidden = set(self._fills.get(name, {}))
                offered.append(_without(one, hidden))
        return tuple(offered)

    async def filled(self, call: ProposedCall) -> ProposedCall:
        """``call`` with the arguments the hub fills.

        A search's are its searcher's proposal for the query planning wrote, so its
        ``origin`` is the connected account's and never a model's; a forecast read's are
        its forecaster's proposal whole, the origin and the configured coordinate
        (ADR-0324 §3:4); any other's are the configured ``fills``. Whatever else planning
        wrote is kept, so an argument the tool does not take still fails its schema at
        authorizing, and an argument the hub fills is the hub's value whatever planning
        wrote for it. A search whose query is missing is handed on as it was, and
        authorizing finds it fits no tool.
        """
        search = await self.search_declaration()
        forecast = await self.forecast_declaration()
        filled: Mapping[str, FrozenJson] | None = self._fills.get(call.name)
        if (
            search is not None
            and self._searcher is not None
            and call.name == str(search.capability)
        ):
            query = call.arguments.get(self._search_query)
            proposed = None if not isinstance(query, str) else await self._searcher.request(query)
            filled = None if proposed is None else proposed.parameters
        elif (
            forecast is not None
            and self._forecaster is not None
            and call.name == str(forecast.capability)
        ):
            proposal = await self._forecaster.request()
            filled = None if proposal is None else proposal.parameters
        if not filled:
            return call
        arguments: dict[str, FrozenJson] = {**call.arguments, **filled}
        return ProposedCall(call_id=call.call_id, name=call.name, arguments=arguments)

    @staticmethod
    @contextlib.contextmanager
    def holding(
        supplied: SuppliedRecords, attributions: MutableMapping[str, str] | None = None
    ) -> Iterator[None]:
        """Hand every search and forecast read run inside this scope's records to ``supplied``.

        The glue opens it around acting for a round, so the records a search or a
        forecast read returns are held by the activation that ran it, as the call
        returns them, before they are rendered to text (ADR-0309 §5:10). A forecast
        read's attribution is noted in ``attributions`` under its call's decision id
        (ADR-0324 §2:4).

        Args:
            supplied: The activation's record of what it was given or obtained.
            attributions: Where a pull's attribution is noted, by decision id, or
                ``None`` where nothing reads them.

        Yields:
            Nothing: the scope is the context it runs in.
        """
        token = _HOLDING.set(supplied)
        noted = _ATTRIBUTING.set(attributions)
        try:
            yield
        finally:
            _ATTRIBUTING.reset(noted)
            _HOLDING.reset(token)

    async def invoke(self, call: ToolCall, *, timeout: timedelta) -> ToolResult:  # noqa: ASYNC109 — the seam owns the deadline (ADR-0029 §4)
        """Invoke ``call`` through its searcher, its forecaster or the invoker.

        A search goes to its searcher, a forecast read to its forecaster, and any other
        call to the deployment's invoker. A search's or a forecast read's records are
        memory records the call returned, so they are handed to the activation running
        it, where a :meth:`holding` scope is open, before they become the result's texts.
        A call noting reliance is answered done and reaches nothing: the round records
        it, and nothing else does (ADR-0329 §6:7).
        """
        if self._reliance is not None and call.request.tool == self._reliance:
            return noted()
        forecast = await self.forecast_declaration()
        if forecast is not None and self._forecaster is not None and call.request.tool == forecast:
            return await self._forecast_read(self._forecaster, call, timeout=timeout)
        search = await self.search_declaration()
        if search is None or self._searcher is None or call.request.tool != search:
            return await self._invoker.invoke(call, timeout=timeout)
        outcome = await self._searcher.search(call, timeout=timeout)
        if (supplied := _HOLDING.get()) is not None:
            supplied.obtained(outcome.records)
        return _searched(outcome)

    @staticmethod
    async def _forecast_read(
        forecaster: Forecaster,
        call: ToolCall,
        *,
        timeout: timedelta,  # noqa: ASYNC109 — the seam owns the deadline (ADR-0241 §1, ADR-0324 §8:1)
    ) -> ToolResult:
        """The weather pull: ``call`` sent to ``Forecaster.read`` (ADR-0324 §5:4).

        Under the call's own deadline, which the forecaster enforces: at it the read is
        cut short and its outcome is unknown (§8:1), so nothing it would have answered
        later reaches the activation (§8:2). Its records are handed to the activation,
        and its attribution is noted under the call's decision, where a
        :meth:`holding` scope is open.
        """
        outcome = await forecaster.read(call, timeout=timeout)
        if (supplied := _HOLDING.get()) is not None:
            supplied.obtained(outcome.records)
        if (attributions := _ATTRIBUTING.get()) is not None:
            attributions[call.decision.id] = _forecast_attribution(
                forecaster.name, outcome.reported_at
            )
        return _forecasted(outcome)


def _forecast_attribution(channel: str, reported_at: datetime | None) -> str:
    """The hub's attribution of a forecast read's answer (ADR-0324 §2:4, §5:3).

    Its channel, the weather channel the forecaster's ``name`` identifies (§5's table),
    and its author: a service, the provider, claimed and not established, written when
    the provider reported it. Stated from the hub's own data and never from the
    answer's text (ADR-0292 §5:1, §5:8).
    """
    when = "" if reported_at is None else f", as of {reported_at.astimezone(UTC).isoformat()}"
    return (
        f"outside content: the weather channel {json.dumps(channel)}; its author is a "
        f"service, the forecast provider, claimed and not established, and it is what the "
        f"provider reported{when}"
    )


def _forecasted(outcome: ForecastOutcome) -> ToolResult:
    """A forecast read's outcome as a call's result: its records' texts, or why none.

    **The outcome is the one the forecaster's ledger completion records**, so an effect
    record a call under an approval gets carries the outcome its invocation completed
    with (ADR-0306 §5:8, ADR-0321 §4:10), and the two records never disagree. An answer
    the provider gave completed the call, whether or not it is one this system carries
    — a day described, none described, or no instant declared — so it is done, its
    texts the records it minted, none for a refusal. A read cut short by its deadline
    may have reached the provider, so its outcome is unknown (ADR-0324 §8:1). A call
    that did not complete as a call is not done. The forecaster states the same mapping
    for its ledger completion, and each subsystem's tests pin the same table.
    """
    refusal = outcome.refusal
    if refusal is None or refusal in _COMPLETED_FORECASTS:
        texts: list[FrozenJson] = [record.content for record in outcome.records]
        return ToolResult(outcome=ToolOutcome.SUCCEEDED, output=texts)
    if refusal is ForecastRefusal.DEADLINE_EXPIRED:
        return ToolResult(
            outcome=ToolOutcome.INDETERMINATE,
            failure=ToolFailure(
                kind=ToolFailureKind.TIMED_OUT, message="the forecast read ran out of time"
            ),
        )
    kind = (
        ToolFailureKind.UNAVAILABLE
        if refusal is ForecastRefusal.TRANSPORT_FAILED
        else ToolFailureKind.REFUSED
    )
    failure = ToolFailure(kind=kind, message=f"the forecast read was refused: {refusal.value}")
    return ToolResult(outcome=ToolOutcome.FAILED, failure=failure)


#: The forecast refusals of a call that completed: the provider answered, and what it
#: answered is not something this system carries.
_COMPLETED_FORECASTS: Final = frozenset({ForecastRefusal.NO_RESULT, ForecastRefusal.UNATTESTED})


def _properties(tool: ToolDefinition) -> set[str]:
    """The argument names a declaration's schema lists."""
    properties = tool.model_dump()["parameters_schema"].get("properties") or {}
    return {str(name) for name in properties}


def _without(tool: ToolDefinition, hidden: set[str]) -> ToolDefinition:
    """``tool`` as planning is offered it: the ``hidden`` arguments are the hub's to fill.

    A copy for planning's offer alone, never ruled on: authorizing selects and the
    policy rules on the registered declaration (ADR-0029 §2).
    """
    added = tuple(sorted(hidden - set(tool.system_supplied)))
    if not added:
        return tool
    return tool.model_copy(update={"system_supplied": (*tool.system_supplied, *added)})


def _searched(outcome: SearchOutcome) -> ToolResult:
    """A search's outcome as a call's result: its records' texts, or why there are none.

    A search that came back with no result completed, with nothing in it; one cut
    short, at the deadline or mid-exchange, may have reached the provider, so its
    outcome is unknown; any other refusal is not done.
    """
    if outcome.refusal is None or outcome.refusal.value == "no_result":
        texts: list[FrozenJson] = [record.content for record in outcome.records]
        return ToolResult(outcome=ToolOutcome.SUCCEEDED, output=texts)
    kind = (
        ToolFailureKind.REFUSED
        if outcome.refusal.value == "spend_refused"
        else ToolFailureKind.UNAVAILABLE
    )
    failure = ToolFailure(kind=kind, message=f"the search was refused: {outcome.refusal.value}")
    if outcome.refusal.value in _UNKNOWN_SEARCHES:
        return ToolResult(outcome=ToolOutcome.INDETERMINATE, failure=failure)
    return ToolResult(outcome=ToolOutcome.FAILED, failure=failure)


# --- the story views ---------------------------------------------------------------------


class StoryReads:
    """What planning is shown of stories, read under the pass's audience (ADR-0307 §6:1).

    It holds the story store, the memory store the episodes are read from, the plan
    store the effect records are read from, the short views' reader, and how many of a
    story's episodes are shown. It reads; it writes nothing and calls no model.
    """

    def __init__(
        self,
        *,
        stories: StoryStore,
        memory: MemoryStore,
        plans: PlanStore,
        short_views: StoryCandidates,
        episodes: int,
    ) -> None:
        """Wire the reads to their stores.

        Args:
            stories: The story store.
            memory: The memory store the stories' episodes are fetched from.
            plans: The plan store holding the effect records (ADR-0306 §6).
            short_views: The short views' reader, understanding's (ADR-0300 §6:2).
            episodes: How many of a story's latest episodes are shown, and of the
                episodes newer than its summary (#2589's numbers).

        Raises:
            ValueError: If ``episodes`` is below 1.
        """
        if episodes < 1:
            msg = "a story view shows at least one episode"
            raise ValueError(msg)
        self._stories = stories
        self._memory = memory
        self._plans = plans
        self._short = short_views
        self._episodes = episodes

    async def read(
        self,
        activation_id: str,
        *,
        understanding: ActivationUnderstanding | None,
        audience: TurnSupply,
        owner_records: bool,
    ) -> PlanningStories:
        """The views of the activation's stories, and of the stories understanding cited.

        Args:
            activation_id: The activation.
            understanding: Its latest recorded understanding, whose ``story``
                referents name the stories cited (ADR-0304 §8).
            audience: The pass's audience posture, which admits the episodes.
            owner_records: Whether a record placed for the owner alone may be shown,
                which decides the summaries and the notes (ADR-0304 §4).

        Returns:
            The views, or none with ``unreadable`` set where the story store or the
            plan store could not be read.

        Raises:
            MemoryStoreError: If the episodes cannot be read, as planning's own fetch.
        """
        visibility = SummaryVisibility(owner_records=owner_records)
        member = StoryMember(kind=StoryMemberKind.ACTIVATION, id=activation_id)
        try:
            belongs = [
                header.story_id
                for header in await self._stories.stories_of(member)
                if header.merged_into is None
            ]
            views = [
                view
                for story_id in belongs
                if (view := await self._story(story_id, audience, visibility)) is not None
            ]
            shown = {*belongs, *(one.story_id for view in views for one in view.inherited)}
            cited = await self._short.short_views(
                [story_id for story_id in _cited(understanding) if story_id not in shown],
                audience=audience,
                visibility=visibility,
            )
        except StoryStoreError, PlanningError:
            _log.warning("planning_stories_unreadable", stage="planning")
            return PlanningStories(unreadable=True)
        _log.info("planning_stories", stage="planning", stories=len(views), cited=len(cited))
        return PlanningStories(stories=tuple(views), cited=cited)

    async def view(
        self, story_id: str, *, audience: TurnSupply, owner_records: bool, older_page: int = 1
    ) -> PlanningStory | None:
        """One story's full view, read as the views of the activation's stories are.

        The full view a story read returns (ADR-0307 §6:6, ADR-0300 §10:6), under the
        same placement (§6:4): the summary and notes by whether a record placed for the
        owner alone may be shown, the episodes and where the matter stands by the
        audience predicate. It also shows one page of the story's older notes, those a
        tidy-up has taken in, newest first (#2893), under the notes' placement: where
        no note may be shown, they are not read.

        Args:
            story_id: The story.
            audience: The pass's audience posture, which admits the episodes.
            owner_records: Whether a record placed for the owner alone may be shown.
            older_page: Which page of the older notes to show, the newest page 1.

        Returns:
            The view, or ``None`` where the store does not hold the story.

        Raises:
            StoryStoreError: If the story store cannot be read, or the story was written
                while its notes were read, every time they were read.
            PlanningError: If the plan store cannot be read.
            MemoryStoreError: If the story's episodes cannot be read.
        """
        return await self._story(
            story_id,
            audience,
            SummaryVisibility(owner_records=owner_records),
            older_page=older_page,
        )

    async def _story(
        self,
        story_id: str,
        audience: TurnSupply,
        visibility: SummaryVisibility,
        *,
        older_page: int | None = None,
    ) -> PlanningStory | None:
        """One story's view, or ``None`` where the store no longer holds it.

        With ``older_page``, a full view: it also carries that page of the older notes.

        Raises:
            StoryStoreError: If the story store cannot be read, or, for a full view, the
                story was written while its notes were read, every time they were read.
        """
        state = await self._stories.current_summary(story_id)
        if state is None:
            return None
        taken_in: tuple[StoryNote, ...] | None = None
        if older_page is not None and visibility.owner_records:
            state, taken_in = await self._older(story_id, state, visibility)
            if state is None:
                return None
        standing = await story_standing(
            self._stories, self._memory, story_id, reader=audience, plans=self._plans
        )
        parents: list[str] = (
            []
            if standing is None
            else [
                related.story_id
                for related in standing.related
                if related.relation is StoryRelation.PART_OF
            ]
        )
        inherited = await self._short.short_views(parents, audience=audience, visibility=visibility)
        latest = [] if standing is None else _latest(standing, self._episodes)
        newer = [episode_address(activation) for activation in state.pending_episodes]
        fetched = await admitted_episodes(self._memory, dict.fromkeys([*newer, *latest]), audience)
        pending = sorted(
            (record for address in newer if (record := fetched.get(address)) is not None),
            key=lambda record: (record.occurred_at, record.id),
            reverse=True,
        )
        summary = state.summary
        shown = summary is not None and visibility.summary()
        notes_shown = visibility.owner_records
        older: tuple[StoryNote, ...] | None = None
        more = 0
        if older_page is not None and taken_in is not None:
            start = (older_page - 1) * OLDER_NOTES_PAGE
            older = taken_in[start : start + OLDER_NOTES_PAGE]
            more = max(0, len(taken_in) - start - OLDER_NOTES_PAGE)
        return PlanningStory(
            story_id=story_id,
            tidied_at=None if summary is None else summary.written_at,
            changes=len(state.pending_notes) + len(state.pending_episodes),
            written=summary is not None,
            lines=summary.lines if shown and summary is not None else (),
            outside=shown and summary is not None and summary.outside,
            withheld=summary is not None and not shown,
            notes=tuple(note for note in state.pending_notes if visibility.note(note)),
            notes_withheld=not notes_shown,
            older=older,
            older_page=1 if older_page is None else older_page,
            older_more=more,
            newer=tuple(pending[: self._episodes]),
            latest=tuple(record for address in latest if (record := fetched.get(address))),
            inherited=inherited,
            standing=standing,
            summary_version=None if summary is None else summary.version,
        )

    async def _older(
        self, story_id: str, state: StorySummaryState, visibility: SummaryVisibility
    ) -> tuple[StorySummaryState | None, tuple[StoryNote, ...]]:
        """The notes ``story_id`` holds that are not pending on it, newest first.

        The story store pages a story's notes in the order written; every page is read,
        as the check that a move's notes are held reads them, and the notes pending on
        the story are left out, so a note is never in both lists (#2893). The notes are
        read between two reads of the summary's state, as the owner's summary read reads
        them (:func:`~ai_assistant.orchestration.stories.owner_summary`), and kept only
        where the two are one read, ``as_of`` included: every write that adds, carries
        or takes in a note advances it (ADR-0300 §3:8), so a note written meanwhile is
        never taken for one a tidy-up took in.

        Returns:
            The state the notes were read under, ``None`` where the story is no longer
            held, and the older notes.

        Raises:
            StoryStoreError: If the store cannot be read, or the story was written
                while its notes were read, every one of :data:`_OLDER_READS` times.
        """
        for _ in range(_OLDER_READS):
            held: list[StoryNote] = []
            cursor: int | None = None
            while True:
                page = await self._stories.notes(story_id, cursor=cursor, limit=MAX_STORY_PAGE)
                if page is None:
                    break
                held.extend(page.notes)
                if page.next_cursor is None:
                    break
                cursor = page.next_cursor
            again = await self._stories.current_summary(story_id)
            if again is None:
                return None, ()
            if again == state:
                pending = {note.note_id for note in state.pending_notes}
                return state, tuple(
                    note
                    for note in reversed(held)
                    if note.note_id not in pending and visibility.note(note)
                )
            state = again
        msg = "the story was written while its notes were read, every time they were read"
        raise StoryStoreError(msg)


#: How many times a full view reads a story's notes before it gives up on a story being
#: written meanwhile, as the owner's summary read does.
_OLDER_READS: Final = 5


def _latest(standing: StoryStanding, count: int) -> list[str]:
    """The addresses of a story's latest ``count`` episodes the reader is shown.

    Where the matter stands lists them most recent first, by each episode's own
    instant, already under the reader's audience (ADR-0300 §8:1).
    """
    return [episode_address(moment.activation_id) for moment in standing.recent[:count]]


def _cited(understanding: ActivationUnderstanding | None) -> list[str]:
    """The stories understanding cited as referents (ADR-0304 §8:1), in order, once each."""
    if understanding is None:
        return []
    # ADR-0353 §9:8: a version's referents are its `meaning_referents`.
    referents = understanding.meaning_referents
    return list(
        dict.fromkeys(
            referent.id
            for referent in referents
            if referent.kind == "story" and referent.id is not None
        )
    )


def _stories_outside(given: PlanningStories) -> tuple[str, ...]:
    """What of the story views planning is shown rests on outside content (ADR-0303 §3:6).

    A marked summary shown, named by its story's id; a marked note shown, by its id; an
    episode shown resting on outside content by its provenance, its input from outside,
    whose understood meaning is still shown, or its evidence (ADR-0303 §3:2, ADR-0308
    §5:4-§5:5), counted as the episode window's are, by its id; and a marked moment of
    where a matter stands, by its episode's address. Empty where none does.
    """
    shorts: list[ShortView] = [
        *given.cited,
        *(one for story in given.stories for one in story.inherited),
    ]
    summaries = (
        *(story.story_id for story in given.stories if story.outside),
        *(one.story_id for one in shorts if one.outside),
    )
    notes = (
        str(note.note_id)
        for note in (
            *(note for story in given.stories for note in _story_notes(story)),
            *(note for one in shorts for note in one.notes),
        )
        if note.outside
    )
    episodes = (
        *(record for story in given.stories for record in (*story.newer, *story.latest)),
        *(record for one in shorts for record in one.episodes),
    )
    moments = (
        episode_address(moment.activation_id)
        for story in given.stories
        if story.standing is not None
        for moment in story.standing.recent
        if moment.outside
    )
    return (
        *summaries,
        *notes,
        *moments,
        *(record.id for record in episodes if rests_on_outside_content(record)),
    )


def _shown_notes(given: PlanningStories) -> tuple[StoryNote, ...]:
    """Every story note a story view planning is shown carries, with its mark."""
    shorts: list[ShortView] = [
        *given.cited,
        *(one for story in given.stories for one in story.inherited),
    ]
    return (
        *(note for story in given.stories for note in _story_notes(story)),
        *(note for one in shorts for note in one.notes),
    )


def _story_notes(story: PlanningStory) -> tuple[StoryNote, ...]:
    """A story view's notes: those since it was tidied, then a story read's older ones."""
    return (*story.notes, *(story.older or ()))


def _story_records(given: PlanningStories) -> tuple[EpisodicMemory, ...]:
    """Every episode a story view planning is shown carries (ADR-0309 §5:10).

    A story's newer and latest episodes, and those of each short view beside it, each
    already admitted by the audience predicate when it was read.
    """
    shorts: list[ShortView] = [
        *given.cited,
        *(one for story in given.stories for one in story.inherited),
    ]
    return (
        *(record for story in given.stories for record in (*story.newer, *story.latest)),
        *(record for one in shorts for record in one.episodes),
    )


def _read(found: EpisodeLookedUp) -> tuple[MemoryRecord, ...]:
    """Every record an episode look-up read and shows (ADR-0309 §5:10)."""
    if isinstance(found, EpisodesFound):
        return tuple(one.record for one in found.episodes)
    if isinstance(found, OlderHistory):
        return found.episodes
    if found.record is None:
        return ()
    return (
        found.record,
        *(one for one in found.memories.values() if not one.rests_on_outside_content),
    )


def _looked_outside(found: EpisodeLookedUp) -> tuple[str, ...]:
    """What an episode look-up shows that rests on outside content (ADR-0358 §6:4).

    An episode resting on outside content, as the episode window's are counted; a marked
    summary shown, by its story; and, of a full view, its evidence, a marked note or a
    marked entry, by the episode.
    """
    if isinstance(found, EpisodesFound):
        return (
            *(one.record.id for one in found.episodes if rests_on_outside_content(one.record)),
            *(
                matter.story_id
                for one in found.episodes
                for matter in one.matters
                if matter.outside and matter.first_line is not None
            ),
        )
    if isinstance(found, OlderHistory):
        return tuple(one.id for one in found.episodes if rests_on_outside_content(one))
    if found.record is None or found.projection is None:
        return ()
    # What the page shows, as it is rendered: its evidence, a marked note or a marked
    # entry; and a marked summary of a matter the episode is in, which every page names,
    # or of a story the page shows again (ADR-0303 §3:6).
    parts = found.page_parts()
    marked = rests_on_outside_content(found.record) or any(
        isinstance(part, ProjectedEvidence)
        or (isinstance(part, ProjectedRound) and part.notes_marked)
        or (isinstance(part, ProjectedCall) and part.marked)
        for part in parts
    )
    again = {
        one.id for part in parts for one in _named_on(part) if one.kind is ShownRecordKind.STORY
    }
    summaries = (
        one.story_id
        for one in (*found.matters, *(found.stories[key] for key in again if key in found.stories))
        if one.outside and one.first_line is not None
    )
    return (*((found.episode_id,) if marked else ()), *dict.fromkeys(summaries))


def _named_on(part: FullViewPart) -> tuple[ShownRecord, ...]:
    """The records one full view's part names by reference (ADR-0358 §10:3)."""
    if isinstance(part, ProjectedRecall):
        return part.found
    if isinstance(part, ProjectedCall) and part.showed is not None:
        return tuple(one for one in part.showed.parts if isinstance(one, ShownRecord))
    return ()


# --- the working set ---------------------------------------------------------------------


@dataclass
class _Step:
    """The step that runs a round's calls, acting with digesting beside it (§3:3)."""

    deadline: datetime
    held: asyncio.Queue[HeldResult | None] = field(default_factory=asyncio.Queue)


@dataclass
class _Round:
    """One round's decisions, each present once its stage has run (ADR-0309 §3:2).

    Attributes:
        planned: Planning's decision.
        authorization: Authorizing's decision, once it has run.
        acted: Acting's decision, once it has run.
        looking_for: What each allowed call is looking for, by its decision's id.
        step: The step running the round's calls, once it has begun.
        written: Whether its message was recorded in the conversation (ADR-0317 §3:4).
        planned_from: The understanding version it was planned from, the latest when
            planning ran (ADR-0332 §3:12); ``None`` where none was recorded.
        offers_shown: The offering activations whose offers its planning was shown
            (ADR-0349 §7:19), which the commitment step reads (§7:14).
        waiting: Whether it is a waiting round (§7:26).
        not_taken: Whether its acts were held back because an answer of it did not come
            to what it asked (ADR-0352 §4:2): only its answers and pure reads ran, and
            its message was never written.
        sent: What came of each of its ``text`` calls once it was written, or held
            back unwritten, by call id (ADR-0356 §7:8).
        effects: Whether each capability it was offered declared an effect, by name,
            as its calls' entries record it (ADR-0356 §8:3).
        finished: Where acting raised and handed back no call's outcome, the outcome and
            reason each of the round's finished effect records holds, by its id
            (ADR-0306 §6), which its call's entry is made from.
        handed: What came of each call acting finished, by its decision's id, as acting
            handed each back (ADR-0356 §8:6). Where acting raised or was cancelled before
            handing back the round, each finished call's entry is made from it.
    """

    planned: PlannedRound
    authorization: RoundAuthorization | None = None
    acted: ActedRound | None = None
    looking_for: dict[str, str] = field(default_factory=dict)
    written: bool = False
    step: _Step | None = None
    planned_from: int | None = None
    offers_shown: frozenset[str] = frozenset()
    waiting: bool = False
    not_taken: bool = False
    sent: dict[str, _Sent] = field(default_factory=dict)
    effects: Mapping[str, bool] = field(default_factory=dict)
    finished: Mapping[str, tuple[ToolOutcome, str | None]] = field(default_factory=dict)
    handed: dict[str, ActedCall] = field(default_factory=dict)

    def acted_one(self, acted: ActedCall) -> None:
        """Hold what came of one call, as acting hands it back (ADR-0356 §8:6)."""
        self.handed[acted.call.call.decision.id] = acted

    @property
    def has_messages(self) -> bool:
        """Whether it has a message to write: its own, or a ``text`` call."""
        return self.planned.message is not None or any(
            one.call.name == TEXT_CAPABILITY for one in self.planned.calls
        )

    @property
    def delivered(self) -> bool:
        """Whether every message it had to write was recorded in its place."""
        texts = [one.call.call_id for one in self.planned.calls if one.call.name == TEXT_CAPABILITY]
        sent = all(
            (one := self.sent.get(call_id)) is not None and one.kind is CallOutcomeKind.DONE
            for call_id in texts
        )
        return sent and (self.planned.message is None or self.written)


@dataclass(frozen=True, slots=True)
class _Sent:
    """What came of one ``text`` call (ADR-0356 §7:8, §8:4).

    Attributes:
        kind: Done, not done or unknown, as its write came back; not done where it was
            held back unwritten.
        reason: Why it was not done, or why it is unknown.
        delivered: What it sent, where and how, where it was written or its write was
            attempted; ``None`` where it was held back before anything was sent.
    """

    kind: CallOutcomeKind
    reason: str | None = None
    delivered: RecordedDelivery | None = None


@dataclass
class _Attempt:
    """One message's write as tried: its text and place, and what its writer said, if it did."""

    words: str
    went: ChannelIdentity
    delivery: Delivery | None = None


def _sent_of(delivered: Delivery, words: str, went: ChannelIdentity) -> _Sent:
    """What came of a ``text`` call, from what its place's writer said (ADR-0357 §3)."""
    reason = _UNKNOWN_WRITE if delivered.outcome is ToolOutcome.INDETERMINATE else delivered.reason
    return _Sent(
        _WRITE_OUTCOME[delivered.outcome],
        reason=reason,
        delivered=RecordedDelivery(
            words=delivered.written or words,
            went=went,
            status=_DELIVERY_STATUS[delivered.outcome],
            reason=reason,
        ),
    )


def _raised_send(attempted: Sequence[_Attempt]) -> _Sent:
    """What came of a ``text`` call whose write or whose record's finish raised (§8:4).

    Where the writer said how it went before the record's finish raised, that holds;
    where the writer itself raised after it was reached, the words and the place are
    kept, how it went unknown; where it was never reached, nothing was sent.
    """
    if not attempted:
        return _Sent(CallOutcomeKind.UNKNOWN, reason=_UNKNOWN_WRITE)
    attempt = attempted[0]
    if attempt.delivery is not None:
        return _sent_of(attempt.delivery, attempt.words, attempt.went)
    return _Sent(
        CallOutcomeKind.UNKNOWN,
        reason=_UNKNOWN_WRITE,
        delivered=RecordedDelivery(
            words=attempt.words,
            went=attempt.went,
            status=DeliveryStatus.UNKNOWN,
            reason=_UNKNOWN_WRITE,
        ),
    )


class _SendRaisedError(Exception):
    """A ``text`` call's write raised, carrying what is known of it (ADR-0356 §8:4).

    Raised from the writer's own error, which the stage ends on once its call's outcome
    is held.
    """

    def __init__(self, sent: _Sent) -> None:
        super().__init__("a text call's write raised")
        self.sent = sent


@dataclass
class Scheduling:
    """What the phases hold of an activation offered spawn (ADR-0350 §3:4, §5:10-§5:11).

    Attributes:
        person: The person the activation is for, whom a task it spawns is for (§3:5).
        set_in: The place of its input, where a task it spawns is set (§3:6).
        build: Builds its place list when it is shown, at the activation's start and at
            every planning round (§5:8), with each place's writer.
        task: For an activation the Task Scheduler started, its task, whose suggested
            places its place list marks and a spawn stating none carries forward (§5:6);
            ``None`` for every other activation, which still replies where its input came
            from (§6:8).
        places: The place list as last built.
        targets: Each place on that list, by place, with its writer.
    """

    person: str
    set_in: ChannelIdentity
    build: Callable[[], Awaitable[tuple[tuple[ListedPlace, ...], Mapping[str, PlaceTarget]]]]
    task: ScheduledTask | None = None
    places: tuple[ListedPlace, ...] = ()
    targets: Mapping[str, PlaceTarget] = field(default_factory=dict)

    @property
    def speaks_by_label(self) -> bool:
        """Whether its messages name their place by label: a task's activation's (§6:7)."""
        return self.task is not None


class PhaseWorking:
    """The phases' part of one activation's working set (ADR-0280 §3, ADR-0309 §3:2).

    Structurally :class:`~ai_assistant.orchestration.controller.PhaseFacts`, which the
    phase rules read. It holds recall's second decision and what planning fetched of
    both runs' records, each round's decisions, the activation's labels, its digests and
    the evidence they gave, its held results (acting's part of the working episode,
    never saved), and the messages it wrote.
    """

    def __init__(  # noqa: PLR0913, PLR0915 — the activation, its place, its trigger, its audience, its round limit, its recorded labels and its input's authority
        self,
        *,
        activation_id: str,
        place: PlaceWindow,
        conversation_id: str | None,
        trigger: RecordedChannelTrigger | None,
        owner_records: bool,
        round_limit: int,
        labels: Sequence[PlanningLabel] = (),
        users_authority: bool = False,
        given_at: datetime | None = None,
        target: PlaceTarget | None = None,
        giver: ApprovalGiver = ApprovalGiver.USER_THROUGH_HUB_CHAT,
    ) -> None:
        """Start an activation's working set, before its first round.

        Args:
            activation_id: The activation.
            place: The place the input came from, and what planning is shown of it.
            conversation_id: The conversation a message is written into, through the
                path's chat writer, or ``None`` where it is not a conversation.
            trigger: The activation's recorded trigger, whose parties say whose words its
                input carries (ADR-0351 §2:1); ``None`` where no channel admitted it.
            owner_records: Whether a record placed for the owner alone may be shown on
                this pass (ADR-0307 §6:4).
            round_limit: The most rounds the activation runs (ADR-0307 §8:4).
            labels: The labels the episode already records.
            users_authority: Whether the input carries the user's authority (ADR-0321
                §3:3, ADR-0292 §5:5), read as ADR-0323 §4:7 restates it for every
                channel and ADR-0351 §6:1 completes it: only an input whose author its
                channel's kind establishes as the user, sent as an instruction, whose
                parties are the user alone, does — the user's message in the hub chat,
                or on the Telegram line from their own account, not forwarding.
                ``False``, the default, wherever it cannot be established. A relay mark
                takes it away for the rest of the activation (ADR-0351 §6:5).
            given_at: When the input was given, timezone-aware: a yes it carries is
                given then (ADR-0321 §4:6). ``None`` where it is not known, and then
                no yes is read from it.
            target: The place a message is written into and its writer, where it is
                not one of the hub chat's conversations, as the Telegram line's chat
                (ADR-0323 §6:1). Never given beside ``conversation_id``.
            giver: Who a yes the input carries is given by: the user, through the
                channel the input came on (ADR-0323 §4:9).

        Raises:
            ValueError: If ``round_limit`` is below 1, or both a conversation and a
                target are given.
        """
        if round_limit < 1:
            msg = "the round limit is at least one round (ADR-0307 §8:4)"
            raise ValueError(msg)
        if conversation_id is not None and target is not None:
            msg = "a working set's messages go into one place: a conversation or a target"
            raise ValueError(msg)
        self.activation_id = activation_id
        self.place = place
        self.conversation_id = conversation_id
        self.trigger = trigger
        self.owner_records = owner_records
        self._users_authority = users_authority
        # ADR-0351 §5:9, §5:14: whether the latest understanding version marks the
        # trigger's input relayed, and whether an input an absorption or a take appended
        # is; each, once set, holds for the rest of the activation.
        self.trigger_relayed = False
        self.joined_relayed = False
        self.given_at = given_at
        self.target = target
        self.giver = giver
        # The actions the input's yes approved, as the records show them, by the pointers
        # they were read for, read once (ADR-0321 §4:2, ADR-0322 §3:4).
        self.approvable: tuple[tuple[AnsweredQuestion, ...], tuple[ApprovedAction, ...]] | None = (
            None
        )
        self._round_limit = round_limit
        self.labels = ActivationLabels(labels)
        self.held = HeldResults(on_hold=self._on_hold)
        # A pull's attribution, by the decision id of the call that brought it, as the
        # tools note it (ADR-0324 §2:4); and by the result it is held under, once held,
        # so a follow-up offering that result again is digested under it too.
        self.attributions: dict[str, str] = {}
        self._attributed: dict[str, str] = {}
        self.digests: list[ActivationDigest] = []
        self.evidence: list[DigestedEvidence] = []
        self.messages: list[str] = []
        # Set once a record the windows or recall brought is seen resting on outside
        # content, before the first round is planned (ADR-0181 §4, ADR-0223), or a
        # story view planning is shown does; with what set it, each named once, in the
        # order seen, for the diagnostic record (ADR-0314 §4).
        self.fetched_outside = False
        self.fetched_outside_from: dict[str, None] = {}
        # The story notes planning has been shown, by id, whose marks authorizing reads
        # for their labels (ADR-0303 §3:1, ADR-0306 §4:5).
        self.notes: dict[int, StoryNote] = {}
        # Every memory record the activation is given or obtains, as it arrives, which
        # the episode's placement is taken over at the freeze (ADR-0309 §5:10).
        self.supplied = SuppliedRecords()
        # Recall's second decision, once that run ends (ADR-0308 §2), and the records
        # either run kept as planning fetched them before its first round (§3).
        self.second_recall: Recalled | None = None
        self.found: Fetched | None = None
        # The ids of the memory records either run kept whose source is outside, held
        # with the second decision (§4:4-§4:5); what recall's digest fetched of them
        # and what came back missing (ADR-0282 §2:7); and whether recall's digest has
        # been decided, whatever came of it.
        self.recall_outside: tuple[str, ...] = ()
        self.recall_digest_fetch: Fetched | None = None
        self.recall_digest_decided = False
        # What planning looked up for itself (ADR-0307 §6:6), by the result's id: a
        # memory search's records whose source is not outside, as fetched by id before
        # the next round (ADR-0282 §2:4), and a story's full view, as its call read it.
        self.searched: dict[str, tuple[Memory, ...]] = {}
        self.search_fetches: list[Fetched] = []
        # ADR-0329 §6:9: the episode window's pending candidates, by episode id, read
        # once before the first round where candidates are recorded.
        self.pending: dict[str, tuple[str, ...]] | None = None
        self.pages: dict[str, PlanningStory] = {}
        # ADR-0332 §3:12: the latest understanding version the pass recorded, which
        # planning starts over for, and how many of the activation's joined inputs this
        # working set has taken into its place and its yes (§3:16).
        self.version: int | None = None
        self._joined_taken = 0
        self._rounds: list[_Round] = []
        # ADR-0350 §3:4: the Task Scheduler's part, for an activation offered spawn; and,
        # once read, the scheduled task each activation the place window links to ran,
        # by the activation (§9:1).
        self.scheduling: Scheduling | None = None
        self.task_links: dict[str, str] | None = None
        # ADR-0349 §7:28: how the waits on an older activation move the pass's deadline,
        # which the engine hands in with the pass; ``None`` moves nothing.
        self.move_deadline: Callable[[float], None] | None = None
        # §7:26: whether its waiting round has been planned, and each activation it
        # waited on, whose finished work every round after the wait is shown (§7:27).
        self.waiting_round_planned = False
        self.waited: tuple[str, ...] = ()
        # §4:6, §6:1: each activation planning was shown as running, by id: in a list
        # pull's running part, an offer or a wait; and what each call on running work
        # came back with, by its result's id.
        self.shown_running: set[str] = set()
        self.peers: dict[str, PeerShown] = {}
        # ADR-0356 §5: the work's exchange as its last round left it, held in memory for
        # the work's life (§6:4) and handed to the next round; and the calls whose
        # entries the episode already records, by their round and id (§8:6).
        self.work: PlanningWork | None = None
        self._entered: set[tuple[str, str]] = set()
        # ADR-0358 §7-§10: what each done episode look-up read, by its result's id; and
        # where the place window came from, which the older history is read from (§9:2).
        self.looked: dict[str, EpisodeLookedUp] = {}
        self.older: OlderSource | None = None

    # --- what the rules read (PhaseFacts) ---

    @property
    def recalled_again(self) -> bool:
        """Recall's second run made its decision, a failed one included (ADR-0308 §2)."""
        return self.second_recall is not None

    @property
    def recall_kept_outside(self) -> bool:
        """Either recall run kept a memory record whose source is outside (§4:5)."""
        return bool(self.recall_outside)

    @property
    def recall_digested(self) -> bool:
        """Recall's digest has been decided, a failed one included (§4:4)."""
        return self.recall_digest_decided

    @property
    def rounds(self) -> int:
        """How many planning rounds were planned from the latest understanding version.

        ADR-0332 §3:12: planning starts over for each version. Rounds planned from an
        earlier one stay in the record, and their results stay for the new rounds
        (§3:13), but are not counted.
        """
        return sum(one.planned_from == self.version for one in self._rounds)

    @property
    def round_limit(self) -> int:
        """The most rounds the activation runs."""
        return self._round_limit

    @property
    def latest_round(self) -> str | None:
        """The latest round's id, or ``None`` before the first."""
        return None if not self._rounds else self._rounds[-1].planned.round.id

    @property
    def latest_has_calls(self) -> bool:
        """The latest round proposed a call, refused ones included."""
        return bool(self._rounds) and bool(self._rounds[-1].planned.round.calls)

    @property
    def latest_has_text(self) -> bool:
        """The latest round's text is not blank."""
        return bool(self._rounds) and bool(self._rounds[-1].planned.round.text.strip())

    @property
    def latest_authorized(self) -> bool:
        """There is an authorizing decision for the latest round."""
        return bool(self._rounds) and self._rounds[-1].authorization is not None

    @property
    def latest_allows(self) -> bool:
        """The latest round's authorizing decision allows a call or a message."""
        decided = self._rounds[-1].authorization if self._rounds else None
        if decided is None:
            return False
        return (
            bool(decided.allowed)
            or (decided.message is not None and decided.message.allowed)
            or any(one.allowed for one in decided.call_messages)
        )

    @property
    def latest_acted(self) -> bool:
        """There is an acting decision for the latest round."""
        return bool(self._rounds) and self._rounds[-1].acted is not None

    @property
    def latest_digests_due(self) -> bool:
        """A call the latest round allows may bring outside text, which a digest reads."""
        decided = self._rounds[-1].authorization if self._rounds else None
        return decided is not None and any(
            one.call.request.tool.result is CapabilityResult.MAY_CARRY_OUTSIDE_TEXT
            for one in decided.allowed
        )

    @property
    def latest_calls_beyond_tidy_ups(self) -> bool:
        """The latest round proposed a call other than a tidy-up (ADR-0315 §2:1).

        Refused calls count, as every call but a tidy-up brings a round whatever came of
        it; a tidy-up never brings one, even when it fails or is refused (§2:2).
        """
        return bool(self._rounds) and any(
            one.name != TIDY_STORY_CAPABILITY for one in self._rounds[-1].planned.round.calls
        )

    @property
    def latest_brings_another(self) -> bool:
        """The latest round brings another, whatever it called (ADR-0349 §7:14, §7:26).

        A waiting round never ends the activation, and a round whose acts were held back
        for an offer it was not shown is planned again (ADR-0315 §2:1-§2:3, as ADR-0349
        §12 reads them).
        """
        if not self._rounds:
            return False
        latest = self._rounds[-1]
        return latest.waiting or (latest.acted is not None and latest.acted.set_aside)

    # --- what the stages read and write ---

    @property
    def latest(self) -> _Round:
        """The latest round.

        Raises:
            RuntimeError: If no round has run, which the rules make impossible.
        """
        if not self._rounds:
            msg = "a round's stages run after its planning round (ADR-0309 §3)"
            raise RuntimeError(msg)
        return self._rounds[-1]

    def planned(
        self,
        planned: PlannedRound,
        *,
        offers_shown: frozenset[str] = frozenset(),
        waiting: bool = False,
        effects: Mapping[str, bool] | None = None,
    ) -> None:
        """Hold a round planning decided, the labels it assigned, and its work's exchange.

        The round is planned from the latest understanding version (ADR-0332 §3:12),
        shown ``offers_shown`` (ADR-0349 §7:19), and is a waiting round where
        ``waiting`` says so (§7:26). ``effects`` says whether each capability it was
        offered declared an effect (ADR-0356 §8:3).
        """
        self.labels.add(planned.labels)
        if planned.work is not None:
            self.work = planned.work
        self._rounds.append(
            _Round(
                planned=planned,
                planned_from=self.version,
                offers_shown=offers_shown,
                waiting=waiting,
                effects=dict(effects or {}),
            )
        )

    def overtaken(self) -> frozenset[str]:
        """The rounds new input overtook before they acted (ADR-0332 §3:7, §3:12-§3:13).

        Each planned from an earlier understanding version than the latest, each whose
        acts were held back for an offer it was not shown (ADR-0349 §7:14), and each
        whose answer to an offer did not come to what it asked (ADR-0352 §4:2): its
        message was never written and nothing it asked about was shown. Only a pure read
        of it, or its answer, can have run.
        """
        return frozenset(
            one.planned.round.id
            for one in self._rounds
            if one.planned_from != self.version or _held_back(one)
        )

    def not_taken(self) -> frozenset[str]:
        """The rounds held back because an answer of theirs was not taken (ADR-0352 §4:2).

        Each is also among :meth:`overtaken`'s; planning shows its text as not written
        for that reason.
        """
        return frozenset(one.planned.round.id for one in self._rounds if one.not_taken)

    def understood(self, version: int, *, relayed: bool = False) -> None:
        """Hold the latest recorded understanding version, which planning starts over for.

        ADR-0332 §3:12: ``first_round_due`` answers until a round is planned from it,
        and ``round_due`` and ``round_limit_reached`` count that version's rounds.
        ``relayed`` is the version's relay mark on the trigger's input, which holds from
        that version on (ADR-0351 §5:9, §6:5).
        """
        self.version = version
        self.trigger_relayed = self.trigger_relayed or relayed

    @property
    def relayed(self) -> bool:
        """Whether any input the activation holds is relayed (ADR-0351 §5:11, §5:14)."""
        return self.trigger_relayed or self.joined_relayed

    @property
    def users_authority(self) -> bool:
        """Whether the input carries the user's authority (ADR-0351 §6:1, §6:5, §8:5).

        What its author and its parties give it, and only while no input the activation
        holds is relayed: an activation holding a relayed input acts with no authority
        from the version, or the append, that brings the relay mark.
        """
        return self._users_authority and not self.relayed

    @property
    def outside_trigger(self) -> bool:
        """Whether the trigger's input is outside, read with its relay mark (ADR-0351 §5:3).

        A pass no channel admitted has no trigger, and so no outside one.
        """
        return self.trigger is not None and parties_are_outside(
            self.trigger.parties, relayed=self.trigger_relayed
        )

    def take_joined(
        self,
        joined: Sequence[JoinedInput],
        place: ChannelIdentity | None,
        *,
        taken: Collection[str] = (),
    ) -> None:
        """Take the inputs an offer brought on the activation's place into what planning sees.

        ADR-0349 §7:21, ADR-0292 §6:10: an input this activation took from an offer
        (one naming an activation in ``taken``) is part of its input, and arrived after
        its window was read, so each of its messages is shown to planning as an input
        item of the place, the user's, as the reader's own are; and a yes it carries is
        given when its latest message was sent (ADR-0321 §4:6). An input an absorption
        brought reaches planning through understanding's record, and its window already
        holds what its own place showed of it. Each input is taken once.
        """
        fresh = list(joined[self._joined_taken :])
        self._joined_taken = len(joined)
        # ADR-0351 §5:13-§5:14: an input appended relayed brings its relay mark here.
        self.joined_relayed = self.joined_relayed or any(one.relayed for one in fresh)
        sent: list[tuple[datetime, PlaceItem]] = []
        for one in fresh:
            if one.taken_over_from not in taken or one.channel != place:
                continue
            for message in one.messages:
                sent.append(
                    (
                        message.sent_at,
                        PlaceItem(
                            author=PlaceAuthor.USER,
                            text=message.text,
                            at=message.sent_at,
                            is_input=True,
                            referent_id=(
                                None if message.position is None else f"message:{message.position}"
                            ),
                        ),
                    )
                )
                if self.given_at is not None and message.sent_at > self.given_at:
                    self.given_at = message.sent_at
        if sent:
            # The window is oldest first, and a renewed offer brings the absorber's own
            # input before what it absorbed, and a later take an earlier message, so
            # each message goes into the window in the order sent (ADR-0293 §6:4).
            self.place = replace(self.place, items=_in_order(self.place.items, sent))

    @property
    def undelivered(self) -> bool:
        """The activation's last message was refused or lost, none recorded after it.

        ADR-0317 §3:4: the latest round that had a message to write did not have it
        recorded in the conversation, because authorizing refused it or its write did
        not come back done (ADR-0306 §5). A message recorded by a later round excuses an
        earlier one that was not, and an activation that had no message to write has
        none undelivered.
        """
        for one in reversed(self._rounds):
            # ADR-0332 §3:12-§3:13, ADR-0349 §7:14, ADR-0352 §4:2: a round planned from
            # an earlier version, or held back for an offer or for an answer that did not
            # come to what it asked, wrote nothing that needed writing.
            if one.planned_from != self.version or _held_back(one):
                continue
            # ADR-0356 §7:7: a ``text`` call is a message too.
            if one.has_messages:
                return not one.delivered
        return False

    def step(self, at: datetime, wait: timedelta) -> _Step:
        """The latest round's step, begun at ``at`` and waited on for ``wait`` at most.

        Begun by whichever of its two stages reaches it first, so each sees one step.
        """
        latest = self.latest
        if latest.step is None:
            latest.step = _Step(deadline=at + wait)
        return latest.step

    def attribution(self, held: HeldResult) -> str | None:
        """The hub's attribution of ``held``, where a pull brought it (ADR-0324 §2:4)."""
        return self._attributed.get(held.result_id)

    def _on_hold(self, held: HeldResult) -> None:
        """Hand a result acting holds to the step digesting it (ADR-0308 §4:2).

        A pull's attribution is taken, as the result is first held, from its call's
        decision; a follow-up's offer keeps the result's id and names another decision,
        so the result's id is what carries it on (ADR-0308 §6:7).
        """
        noted = self.attributions.get(held.decision_id)
        if noted is not None:
            self._attributed.setdefault(held.result_id, noted)
        for one in reversed(self._rounds):
            if one.planned.round.id == held.round_id and one.step is not None:
                one.step.held.put_nowait(held)
                return

    def outcomes(self) -> tuple[CallOutcome, ...]:
        """What came of every round's calls, as planning reads them.

        A look-up's result is shown as what it looked up (ADR-0307 §6:6): a memory
        search's records as fetched, and a story's full view as read. A follow-up naming
        one shows only that its result was read again by a digest (ADR-0308 §6:7).
        """
        outcomes: list[CallOutcome] = []
        for one in self._rounds:
            names = {call.call_id: call.name for call in one.planned.round.calls}
            # The capability a call ran as: an approved action is proposed under the
            # approved-action tool's name and runs as the capability its question
            # showed (ADR-0321 §4:2), so a remember a yes approved is rendered as one.
            ran = (
                {}
                if one.acted is None
                else {
                    acted.result_id: str(acted.call.call.request.tool.capability)
                    for acted in one.acted.calls
                    if acted.result_id is not None
                }
            )
            decisions = (
                {}
                if one.authorization is None
                else {
                    verdict.call_id: verdict.decision_id
                    for verdict in one.authorization.verdicts
                    if verdict.decision_id is not None
                }
            )
            for outcome in call_outcomes(
                one.planned, one.authorization, one.acted, one.sent, one.finished
            ):
                capability = names.get(outcome.call_id)
                if outcome.result_id is not None:
                    capability = ran.get(outcome.result_id, capability)
                looked = self._looked_up(outcome, capability)
                refused = self.peers.get(decisions.get(outcome.call_id) or "")
                if refused is not None and looked.peer is None:
                    # ADR-0349 §4:9: a stop refused, naming the absorber.
                    looked = replace(looked, peer=refused)
                outcomes.append(looked)
        return tuple(outcomes)

    def _labelled(self, outcome: CallOutcome, result_id: str) -> CallOutcome:
        """What a call on the Task Scheduler or on running work came back with, labelled.

        ADR-0350 §4:6-§4:8: a spawn's, a cancel's or a list pull's tasks, activations
        and places. ADR-0349 §4:11, §6:5-§6:6, §7:20: the peer view of the activation a
        stop or a look-up named, or what an answer came to, held by its result's id.
        """
        listing = decode_listing(outcome.result)
        if listing is not None:
            return replace(outcome, result=None, tasks=listing)
        peer = self.peers.get(result_id)
        return outcome if peer is None else replace(outcome, result=None, peer=peer)

    def running_shown(self) -> frozenset[str]:
        """Each activation planning was shown as running (ADR-0349 §4:6, §6:1).

        In a list pull's running part this activation made, an offer or a wait; and, by
        ADR-0352 §3:7, in what a stop call's result listed of what the stopped activation
        set up.
        """
        shown = set(self.shown_running)
        for outcome in self.outcomes():
            if outcome.tasks is not None and outcome.tasks.listed:
                shown.update(one.activation_id for one in outcome.tasks.running)
            set_up = None if outcome.peer is None else outcome.peer.set_up
            if set_up is not None:
                shown.update(set_up.running)
        return frozenset(shown)

    def _looked_up(self, outcome: CallOutcome, capability: str | None) -> CallOutcome:
        """``outcome``, carrying what its look-up found where it was one."""
        result_id = outcome.result_id
        if result_id is None:
            return outcome
        found = self._found(outcome, result_id, capability)
        if found is not None:
            return found
        if capability in TASK_SCHEDULER_CAPABILITIES or capability in MATTER_CAPABILITIES:
            return self._labelled(outcome, result_id)
        if capability == REMEMBER_CAPABILITY and is_candidate_result(outcome.result):
            # ADR-0329 §4:1, §4:4: a candidate's similar memories as fetched, or that its
            # lookup failed, which leaves it recorded.
            similar = (
                None
                if candidate_similar(outcome.result) is None
                else self.searched.get(result_id, ())
            )
            return replace(outcome, result=None, candidate=RecordedCandidate(similar=similar))
        return outcome

    def _found(
        self, outcome: CallOutcome, result_id: str, capability: str | None
    ) -> CallOutcome | None:
        """``outcome``, carrying what its look-up found, or ``None`` where it found none.

        A story read's view, a memory search's records as fetched, and what an episode
        look-up read (ADR-0358 §7-§10).
        """
        page = self.pages.get(result_id)
        if page is not None and capability == READ_STORY_CAPABILITY:
            return replace(outcome, result=None, story=page)
        searched = self.searched.get(result_id)
        if searched is not None and capability == SEARCH_MEMORY_CAPABILITY:
            return replace(outcome, result=None, records=searched)
        looked = self.looked.get(result_id)
        if isinstance(looked, EpisodesFound):
            return replace(outcome, result=None, episodes=looked)
        if isinstance(looked, OlderHistory):
            return replace(outcome, result=None, history=looked)
        if isinstance(looked, EpisodeRead):
            return replace(outcome, result=None, full=looked)
        return None

    def unfetched_searches(self) -> dict[str, tuple[str, ...]]:
        """Each done look-up's ids for planning, by result id, not yet fetched.

        A memory search's records whose source is not outside (ADR-0307 §6:6), and a
        recorded candidate's similar memories (ADR-0329 §4:1); a candidate whose lookup
        failed lists none to fetch.
        """
        unfetched: dict[str, tuple[str, ...]] = {}
        for acted in self.acted_rounds():
            for one in acted.calls:
                result_id = one.result_id
                if (
                    one.outcome is not ActedOutcome.DONE
                    or result_id is None
                    or result_id in self.searched
                ):
                    continue
                capability = str(one.call.call.request.tool.capability)
                if capability == SEARCH_MEMORY_CAPABILITY:
                    unfetched[result_id] = searched_ids(one.output)
                elif capability == REMEMBER_CAPABILITY:
                    similar = candidate_similar(one.output)
                    if similar is not None:
                        unfetched[result_id] = similar
        return unfetched

    def planning_rounds(self) -> tuple[PlanningRound, ...]:
        """Every round, as planning recorded it or as it would have been."""
        return tuple(one.planned.round for one in self._rounds)

    def call_entries(
        self, at: datetime, *, freezing: bool = False, showed: int = SHOWED_CHARS
    ) -> tuple[RecordedCall, ...]:
        """Each call's entry the episode does not yet record, as of now (ADR-0356 §8).

        One for each call a round proposed, refused calls and look-ups included, once
        what came of it is known, as planning is shown it (§8:2-§8:3). A tidy-up's is
        made once it started, with no outcome, or once it was refused (§8:6). At the
        freeze (``freezing``), every call still without one gets one, with no outcome.
        Each entry is made once: the calls it is made for are held as entered.

        **A done call's entry also holds what its result showed planning** (ADR-0358
        §11:2-§11:4), read off what planning renders of it
        (:func:`~ai_assistant.orchestration.planning.call_showed`): each record by its
        kind and id, never by a copy, nothing of what was held for a digest, cut to
        ``showed`` characters. A memory search's entry waits for the fetch before the
        next round, which decides which of its records planning is shown; one whose
        records were never fetched, because no round followed, keeps at the freeze the
        records it listed for planning, by id. Each result is read under the labels
        planning holds and those each result before it assigns, as planning renders them.

        Args:
            at: When the entries are appended.
            freezing: Whether the episode is freezing.
            showed: The composition root's bound on what an entry keeps of what its
                call showed (§11:4).

        Returns:
            The new entries, in the order the rounds proposed their calls.
        """
        entries: list[RecordedCall] = []
        # ADR-0358 §8:1, §11:2: each result is read as planning is shown it, under the
        # labels planning holds and those each result before it in this batch assigns.
        labels = ShowingLabels(self.labels.labels)
        # A memory search's records are fetched before the next round, and what planning
        # is shown of it is known only then: its entry waits for that fetch, and only at
        # the freeze, with no round to follow, keeps the ids it listed.
        waiting = frozenset() if freezing else frozenset(self.unfetched_searches())
        for one in self._rounds:
            round_id = one.planned.round.id
            outcomes = {
                outcome.call_id: outcome
                for outcome in call_outcomes(
                    one.planned,
                    one.authorization,
                    one.acted,
                    one.sent,
                    one.finished,
                    handed=one.handed,
                )
            }
            # An approved action is proposed under its tool and runs as its capability.
            named = {planned.call.call_id: planned.call.name for planned in one.planned.calls}
            for call in one.planned.round.calls:
                if (round_id, call.call_id) in self._entered:
                    continue
                outcome = outcomes.get(call.call_id)
                started = call.name == TIDY_STORY_CAPABILITY and one.authorization is not None
                if outcome is None and not (started or freezing):
                    continue
                if outcome is not None and outcome.result_id in waiting:
                    continue
                capability = named.get(call.call_id, call.name)
                sent = one.sent.get(call.call_id)
                shown = (
                    None if outcome is None else self._showed(outcome, capability, showed, labels)
                )
                entries.append(
                    RecordedCall(
                        round=round_id,
                        call_id=call.call_id,
                        capability=capability,
                        effect=one.effects.get(capability, False),
                        outcome=None if outcome is None else outcome.kind,
                        reason=None if outcome is None else outcome.reason,
                        delivered=(
                            sent.delivered
                            if sent is not None
                            else None
                            if outcome is None
                            else outcome.delivered
                        ),
                        recorded_at=at,
                        marked=one.planned.read_outside
                        or (outcome is not None and outcome.digested),
                        showed=shown,
                    )
                )
                self._entered.add((round_id, call.call_id))
        return tuple(entries)

    def _showed(
        self, outcome: CallOutcome, capability: str, bound: int, labels: ShowingLabels
    ) -> CallShowed | None:
        """What a call's result showed planning, as its entry keeps it (ADR-0358 §11:2)."""
        looked = self._looked_up(outcome, capability)
        if (
            capability == SEARCH_MEMORY_CAPABILITY
            and looked.records is None
            and outcome.kind is CallOutcomeKind.DONE
        ):
            # No round followed to fetch them: the records it listed, by id (§11:2).
            listed = tuple(
                ShownRecord(kind=ShownRecordKind.MEMORY, id=one)
                for one in searched_ids(outcome.result)
            )
            return shown_within(listed, bound)
        return call_showed(looked, bound=bound, owner_records=self.owner_records, labels=labels)

    def acted_rounds(self) -> tuple[ActedRound, ...]:
        """Every acting decision, in round order."""
        return tuple(one.acted for one in self._rounds if one.acted is not None)

    def fetched_resting_on_outside(self, outside: Sequence[str]) -> None:
        """Note what was fetched resting on outside content, and mark the episode now.

        Sets ``fetched_outside`` with what set it, each named once, in the order seen.
        ADR-0223's value for the episode is a disjunction over what the pass was given,
        and this term already makes it true, so the pass holds it from here: ADR-0286
        §4:3 carries it into every append after this one. A restart's close keeps what
        the episode stored, so without this the mark reached only the freezing write,
        which a pass cut off before it never makes (#3270).

        Args:
            outside: The ids of what was fetched resting on outside content. Nothing is
                noted where it is empty.
        """
        if not outside:
            return
        self.fetched_outside = True
        self.fetched_outside_from.update(dict.fromkeys(outside))
        if (state := active_state()) is not None:
            state.holds_external(value=True)

    @property
    def read_outside_content(self) -> bool:
        """Whether a ruling or a digest says the activation has read outside content.

        Authorizing computes it over the activation's whole record (ADR-0306 §4:5-§4:6);
        a digest that answered says so too (ADR-0308 §5:4), and so does an outside
        trigger, a relayed input, or a fetched record resting on outside content
        (ADR-0351 §5:13).
        """
        return (
            self.outside_trigger
            or self.relayed
            or self.fetched_outside
            or any(
                one.authorization is not None and one.authorization.read_outside_content
                for one in self._rounds
            )
            or any(one.outcome is DigestOutcome.ANSWERED for one in self.digests)
        )

    def yes(self, understanding: ActivationUnderstanding | None) -> YesContext | None:
        """The yes the input carries, as authorizing takes it (ADR-0321 §3:1, §4:4).

        Every pointer understanding recorded (ADR-0322 §3:1), with when the input was
        given and whether it carries the user's authority; ``None`` where understanding
        recorded none, or where when the input was given is not known, and then no call
        runs under an approval (ADR-0321 §4:5). It grants nothing by itself: authorizing
        checks each pointer against the records.
        """
        # ADR-0353 §11:2-§11:3: understanding records no answer pointer until the
        # authority run, so authorizing's rules find none.
        del understanding
        answers: tuple[AnsweredQuestion, ...] = ()
        if not answers or self.given_at is None:
            return None
        return YesContext(
            answers=answers,
            given_at=self.given_at,
            users_authority=self.users_authority,
            who=self.giver,
        )

    def outcome(self) -> str | None:
        """The episode's ``outcome``: the messages written, joined by a blank line (§10)."""
        return "\n\n".join(self.messages) if self.messages else None


# --- the conversions ---------------------------------------------------------------------


def place_window(
    window: TranscriptWindow, *, description: str | None = CHAT_DESCRIPTION
) -> PlaceWindow:
    """The chat's window as planning is shown it: a place that takes a message.

    Each message keeps its author; the input's messages are marked as the input; and a
    message the window links to an activation, the one that took it in or wrote it,
    names that activation's episode (ADR-0303 §7:1, ADR-0307 §5:6). Each carries the id
    understanding's referent names it by, so a reference to it reaches planning as the
    item the window shows. A deleted message is not shown. A forward is someone else's,
    claimed (ADR-0323 §4:10), as is any other message whose author the place's kind
    does not establish (§4:2): each is an item of ``other``'s, whose raw text planning
    is never shown (ADR-0307 §9:2), and reaches planning through understanding's record
    alone.

    Args:
        window: The conversation's recent transcript, brought in with the input.
        description: The channel kind's description.

    Returns:
        The place, oldest item first.
    """
    inputs = {one.position for one in window.input_messages}
    shown: dict[int, TranscriptMessage | LineMessage] = {}
    for one in (*window.replied_to, *window.messages, *window.input_messages):
        if not isinstance(one, DeletedMessage):
            shown[one.position] = one
    items = tuple(
        PlaceItem(
            author=PlaceAuthor.OTHER
            if position in window.forwarded or position in window.claimed
            else PlaceAuthor.USER
            if one.author is MessageAuthor.USER
            else PlaceAuthor.ASSISTANT,
            text=one.text,
            at=one.written_at,
            is_input=position in inputs,
            episode_id=(
                None if (linked := window.links.get(position)) is None else episode_address(linked)
            ),
            # The id understanding's referent names the message by (understanding.py
            # `_message_item`), pinned equal by test_phase_path.py.
            referent_id=f"message:{position}",
        )
        for position, one in sorted(shown.items())
    )
    return PlaceWindow(takes_message=True, description=description, items=items)


def call_outcomes(  # noqa: PLR0913 — each decision a round holds, and what acting handed back
    planned: PlannedRound,
    authorization: RoundAuthorization | None,
    acted: ActedRound | None,
    sent: Mapping[str, _Sent] | None = None,
    finished: Mapping[str, tuple[ToolOutcome, str | None]] | None = None,
    *,
    handed: Mapping[str, ActedCall] | None = None,
) -> tuple[CallOutcome, ...]:
    """What came of one round's calls, as planning reads them, in the round's order.

    A ``text`` call is what its write came to, with what it sent, or refused by the
    message place check, where it was not allowed (ADR-0356 §7:7-§7:8, §8:4). Any
    other call planning's own check refused, or authorizing found not done, is refused;
    one authorizing sent to the user needs you, carrying the request a question about it
    shows and records, or the part of the question it already waits on (ADR-0321 §2:8,
    §4:11); and one it allowed is what acting made of it, its result under the id acting
    minted (ADR-0306 §5:1, §5:14), or needing you where the memory writer asked at write
    time, with the assertions its question shows replaced (ADR-0321 §5:5). A call with no
    decision yet has no outcome.

    Where acting raised or was cancelled and so made nothing of the round (``acted`` is
    ``None``), a call it ``handed`` back as it finished is what acting made of it, and
    one claimed under an effect record it did not hand back is what that record holds
    (ADR-0356 §8:6, ADR-0306 §6).
    """
    refused = {one.call.call_id: one.reason for one in planned.refused}
    verdicts = {} if authorization is None else {one.call_id: one for one in authorization.verdicts}
    messages = (
        {} if authorization is None else {one.call_id: one for one in authorization.call_messages}
    )
    written = {} if sent is None else sent
    ran = (
        dict(handed or {})
        if acted is None
        else {one.call.call.decision.id: one for one in acted.calls}
    )
    round_id = planned.round.id
    outcomes: list[CallOutcome] = []
    for call in planned.round.calls:
        call_id = call.call_id
        if call_id in refused:
            outcomes.append(
                CallOutcome(round_id, call_id, CallOutcomeKind.REFUSED, reason=refused[call_id])
            )
            continue
        text = _text_outcome(round_id, call_id, written.get(call_id), messages.get(call_id))
        if text is not None:
            outcomes.append(text)
            continue
        verdict = verdicts.get(call_id)
        if verdict is None:
            continue
        if verdict.verdict is Verdict.NEEDS_YOU:
            # ADR-0321 §2:8, §4:11: what a question about it shows and records, or the
            # part of the question it is already waiting on.
            outcomes.append(
                CallOutcome(
                    round_id,
                    call_id,
                    CallOutcomeKind.NEEDS_YOU,
                    reason=verdict.reason,
                    request=verdict.request,
                    deliberate_repeat=verdict.deliberate_repeat,
                    already_asked=verdict.already_asked,
                )
            )
            continue
        if verdict.verdict is Verdict.NOT_DONE:
            outcomes.append(
                CallOutcome(round_id, call_id, CallOutcomeKind.REFUSED, reason=verdict.reason)
            )
            continue
        one = None if verdict.decision_id is None else ran.get(verdict.decision_id)
        if one is None:
            held = (finished or {}).get(verdict.effect_id or "")
            if acted is None and held is not None and held[0] in _EFFECT_OUTCOMES:
                # ADR-0356 §8:6: acting raised, and the call's effect record holds what
                # came of it (ADR-0306 §6).
                outcomes.append(
                    CallOutcome(round_id, call_id, _EFFECT_OUTCOMES[held[0]], reason=held[1])
                )
            continue
        if one.outcome is ActedOutcome.NEEDS_YOU:
            # ADR-0321 §5:5: a remember the writer asked about at write time needs you,
            # showing the assertions it would replace (#2845).
            outcomes.append(
                CallOutcome(
                    round_id,
                    call_id,
                    CallOutcomeKind.NEEDS_YOU,
                    reason=one.reason,
                    request=one.call.call.request,
                    deliberate_repeat=one.call.deliberate_repeat,
                    replaces=one.replaces,
                )
            )
            continue
        kind = {
            ActedOutcome.DONE: CallOutcomeKind.DONE,
            ActedOutcome.NOT_DONE: CallOutcomeKind.NOT_DONE,
            ActedOutcome.UNKNOWN: CallOutcomeKind.UNKNOWN,
        }[one.outcome]
        digested = one.route is ResultRoute.DIGEST
        outcomes.append(
            CallOutcome(
                round_id,
                call_id,
                kind,
                reason=one.reason,
                result_id=one.result_id,
                result=one.output if one.route is ResultRoute.PLANNING else None,
                digested=digested,
                delivered=_emailed(one),
            )
        )
    return tuple(outcomes)


#: How an email that acting ran went, by what acting made of it (ADR-0357 §3:1-§3:3).
_EMAIL_STATUS: Final = {
    ActedOutcome.DONE: DeliveryStatus.SENT,
    ActedOutcome.NOT_DONE: DeliveryStatus.FAILED,
    ActedOutcome.UNKNOWN: DeliveryStatus.UNKNOWN,
}


def _emailed(one: ActedCall) -> RecordedDelivery | None:
    """What an email acting ran sent, where and how, or ``None`` (ADR-0357 §3:1).

    For an ``email`` whose submission was attempted, under the effect record it was
    claimed under: its words as the wording step rendered them, the platform and its
    recipients, and sent, failed or unknown, as acting found it, with the reason. *Sent*
    is the medium's last word by the time the call returns (§3:2). ``None`` for every
    other call, and for an email refused before it was claimed, such as an accidental
    repeat, which sent nothing.
    """
    request = one.call.call.request
    if str(request.tool.capability) != EMAIL_CAPABILITY or one.outcome is ActedOutcome.NEEDS_YOU:
        return None
    if one.effect_id is None:
        return None
    words = request.parameters.get(WORDS_ARGUMENT)
    where = emailed_to(request.parameters)
    if not isinstance(words, str) or not words.strip() or where is None:
        return None
    exact = request.parameters.get(EXACT_ARGUMENT) is True
    status = _EMAIL_STATUS[one.outcome]
    reason = None if status is DeliveryStatus.SENT else (one.reason or _UNKNOWN_WRITE)
    return RecordedDelivery(
        words=reworded(words, exact=exact),
        went=ChannelIdentity(channel_type=EMAIL_CHANNEL_TYPE, instance_id=where),
        status=status,
        reason=reason,
    )


def _text_outcome(
    round_id: str, call_id: str, sent: _Sent | None, verdict: MessageVerdict | None
) -> CallOutcome | None:
    """What came of a ``text`` call, or ``None`` where it is no ``text`` call or not yet."""
    if sent is not None:
        return CallOutcome(
            round_id, call_id, sent.kind, reason=sent.reason, delivered=sent.delivered
        )
    if verdict is not None and not verdict.allowed:
        return CallOutcome(round_id, call_id, CallOutcomeKind.REFUSED, reason=verdict.reason)
    return None


def authorized_round(decided: RoundAuthorization) -> AuthorizedRound:
    """Authorizing's decision as acting's input: the allowed calls, in the round's order.

    A call that runs under an approval carries the asked call it was rebuilt from
    (ADR-0321 §4:2), whose ``replaces`` a remember retires on the yes (§5:5).
    """
    return AuthorizedRound(
        activation_id=decided.activation_id,
        round_id=decided.round_id,
        calls=tuple(
            AuthorizedCall(one.call, deliberate_repeat=one.deliberate_repeat, asked=one.asked)
            for one in decided.allowed
        ),
        story_activations=decided.story_activations,
    )


def digested_evidence(digested: Digested, labels: Sequence[PlanningLabel]) -> DigestedEvidence:
    """A recorded digest as planning is shown it, each item under its source's thing.

    The digest records each item's source by label (ADR-0308 §4:15); planning names it
    by the thing that label names, so the labels the digest took resolve it.
    """
    named = {one.label: one for one in labels}
    items: list[DigestItem] = []
    for item in digested.digest.evidence:
        source = named.get(item.source)
        if source is None:  # pragma: no cover — the digest took every label it recorded
            continue
        items.append(DigestItem(text=item.text, source_kind=source.kind, source_id=source.id))
    return DigestedEvidence(
        result_id=digested.result_id,
        answered=digested.digest.outcome is DigestOutcome.ANSWERED,
        items=tuple(items),
        question=None if digested.result_id is None else digested.digest.question,
    )


# --- the recorders -----------------------------------------------------------------------


class _RoundRecorder:
    """Planning's ``RoundRecorder``, over the episode writer (ADR-0307 §2:4).

    It adds the round and its labels to the state of the activation this task runs,
    which the open episode is built from, and extends the episode (ADR-0286 §3). The
    writer never raises but for a cancellation: a failed append ends capture, and holds
    nothing back (§3:7). A pass no channel admitted has no episode, and records nothing.
    """

    def __init__(self, path: PhasePath) -> None:
        self._path = path

    async def record(
        self,
        planning_round: PlanningRound,
        labels: tuple[PlanningLabel, ...],
        *,
        questions: Mapping[str, str] | None = None,
    ) -> None:
        """Add the round and its labels to the activation's record, and extend it.

        A round whose question would not be shown whole is recorded asking about
        nothing (:meth:`PhasePath.shown_whole`).
        """
        state = active_state()
        if state is None:
            return
        working = _PLANNING.get()
        if working is not None:
            planning_round = self._path.shown_whole(working, planning_round, questions, labels)
        state.recorded_round(planning_round, labels)
        await _extended(state, self._path.append)


class _DigestRecorder:
    """Digesting's ``DigestRecorder``, over the episode writer (ADR-0308 §5:2).

    As :class:`_RoundRecorder`, for a digest and the labels it took.
    """

    def __init__(self, path: PhasePath) -> None:
        self._path = path

    async def record(self, digest: ActivationDigest, labels: tuple[PlanningLabel, ...]) -> None:
        """Add the digest and its labels to the activation's record, and extend it."""
        state = active_state()
        if state is None:
            return
        state.recorded_digest(digest, labels)
        await _extended(state, self._path.append)


async def _extended(state: ActivationState, append: Callable[[], Awaitable[None]]) -> None:
    """Extend the episode with what the record now holds, one append at a time.

    Each append writes the whole record as it stands. A recorder that finds another
    extending the episode awaits the owner's next append, which begins after its
    addition and so carries it, and returns once that append has returned: a digest is
    recorded only then (ADR-0308 §5:2, ADR-0286 §3:1). Digests recorded side by side
    would otherwise race the writer's conditioned write and end capture (ADR-0286 §3:4).
    No lock is taken (ADR-0306 §5:17). Where the owner stops before that append, a
    waiting recorder takes the appends over.
    """
    while state.extending:
        if state.extension is None:
            state.extension = asyncio.get_running_loop().create_future()
        # Shielded: a waiting recorder cancelled leaves the owner's append to the rest.
        if await asyncio.shield(state.extension):
            return
    state.extending = True
    owed: asyncio.Future[bool] | None = None
    try:
        await append()
        while state.extension is not None:
            owed, state.extension = state.extension, None
            await append()
            owed.set_result(True)
            owed = None
    finally:
        state.extending = False
        for left in (owed, state.extension):
            if left is not None and not left.done():
                left.set_result(False)
        state.extension = None


# --- the path ------------------------------------------------------------------------------


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _never() -> bool:
    return False


def _new_effect_id() -> str:
    return f"effect:{uuid4().hex}"


def _place_id(conversation_id: str) -> str:
    """The place a message goes into: the conversation, by its id (ADR-0306 §6)."""
    return place_of(conversation_channel(conversation_id))


def _delivered_round(effects: Sequence[ActivationEffect], pointer: AnsweredQuestion) -> str | None:
    """The round whose message the pointer names, where its delivery is done.

    As authorizing reads ADR-0321 §4:4's *shown*: the asking activation's message
    record for the pointer's round, at its place and position where the pointer names
    them, its outcome done and its position written (ADR-0306 §5:5). The *couldn't
    finish* message names no round and is never a question.
    """
    for one in effects:
        if (
            not one.is_call
            and one.activation_id == pointer.activation_id
            and one.outcome is ToolOutcome.SUCCEEDED
            and one.position is not None
            and one.round is not None
            and (pointer.round is None or one.round == pointer.round)
            and (
                pointer.place is None
                or (one.place == pointer.place and one.position == pointer.position)
            )
        ):
            return one.round
    return None


#: Why a call of a round held back for an offer was not done (ADR-0349 §7:14), as
#: planning reads it.
_HELD_BACK: Final = (
    "not run: newer input was offered to this work before this round acted, so the round "
    "is planned again with the offer shown"
)
#: Why a call of a round whose answer to an offer did not come to what it asked was not
#: done (ADR-0352 §4:2), as planning reads it: ``{facts}`` is what each such answer came
#: to, by :func:`~ai_assistant.orchestration.planning.answer_fact`.
_NOT_TAKEN: Final = (
    "not run: this round's answer to an offer did not come to what it asked, so the round "
    "is planned again with what the answer came to: {facts}"
)
#: How a held-back call's reason names the work that offered the input, which carries no
#: label: the answer's result beside it names that work by its ``E`` label.
_OFFERING_WORK: Final = "the work that offered the input"


def _not_taken(answering: _Answering, caller: MatterCaller | None) -> str:
    """Why each held-back call of a round was not done: what its answers came to (§4:2).

    One fact for each distinct way an answer of the round did not come to what it asked:
    one refused before acting was not allowed, then each that ran says what it came to,
    in the round's order, and one whose arguments or records failed was not done.
    """
    facts: list[NotAsAsked] = []
    if answering.refused:
        facts.append(NotAsAsked.NOT_ALLOWED)
    for one in answering.first.allowed:
        decision = one.call.decision.id
        if caller is not None and decision in caller.as_asked:
            continue
        why = NotAsAsked.NOT_DONE if caller is None else caller.not_as_asked.get(decision)
        facts.append(NotAsAsked.NOT_DONE if why is None else why)
    shown = dict.fromkeys(facts or [NotAsAsked.NOT_DONE])
    return _NOT_TAKEN.format(
        facts="; ".join(answer_fact(why, offering=_OFFERING_WORK) for why in shown)
    )


def _position(item: PlaceItem) -> int | None:
    """A place-window item's position in its medium, where its referent names one."""
    referent = item.referent_id
    if referent is None or not referent.startswith("message:"):
        return None
    held = referent.removeprefix("message:")
    return int(held) if held.isdigit() else None


def _in_order(
    items: Sequence[PlaceItem], sent: Sequence[tuple[datetime, PlaceItem]]
) -> tuple[PlaceItem, ...]:
    """``items`` with each of ``sent`` placed where the medium's order puts it.

    The window keeps its own order, oldest first. Each new item goes after every item
    the medium holds before it: by position where both carry one, the medium's own
    order, which a clock set back never reverses, and by the time each was sent where
    either carries none. So a take brought in a later round still lands among the
    messages it came between.
    """
    merged = list(items)
    for at, item in sorted(sent, key=lambda pair: _order_key(pair[1], pair[0])):
        index = len(merged)
        while index > 0 and _comes_after(merged[index - 1], item, at):
            index -= 1
        merged.insert(index, item)
    return tuple(merged)


def _order_key(item: PlaceItem, at: datetime) -> tuple[int, datetime]:
    """The order new items are placed in: by position, and by time without one."""
    position = _position(item)
    return (-1 if position is None else position, at)


def _comes_after(before: PlaceItem, item: PlaceItem, at: datetime) -> bool:
    """Whether ``before``, already in the window, belongs after ``item`` (sent ``at``)."""
    mine, theirs = _position(item), _position(before)
    if mine is not None and theirs is not None:
        return theirs > mine
    return before.at is not None and before.at > at


def _held_back(one: _Round) -> bool:
    """Whether ``one``'s acts were held back, so its message was never written.

    For an offer it was not shown (ADR-0349 §7:14), or because an answer of it did not
    come to what it asked (ADR-0352 §4:2).
    """
    return one.not_taken or (one.acted is not None and one.acted.set_aside)


@dataclass(frozen=True, slots=True)
class _Answering:
    """A round that answers an offer, split as acting dispatches it (ADR-0352 §4:1).

    Attributes:
        decided: Authorizing's decision for the whole round.
        first: The same decision, its allowed answer calls alone and no message: what
            is dispatched first, and alone.
        rest: Every other allowed call, in the round's order.
        refused: Whether an answer call of the round was not allowed, refused by
            planning's own check or by authorizing, so it cannot come to what it asked
            (§4:2).
    """

    decided: RoundAuthorization
    first: RoundAuthorization
    rest: tuple[AllowedCall, ...]
    refused: bool


def _answering(latest: _Round, decided: RoundAuthorization) -> _Answering | None:
    """The round split for answering first, or ``None`` where it makes no answer call."""
    asked = [
        call.call_id for call in latest.planned.round.calls if call.name == ANSWER_OFFER_CAPABILITY
    ]
    if not asked:
        return None
    allowed = {one.call_id for one in decided.verdicts if one.verdict is Verdict.ALLOWED}

    def answers(one: AllowedCall) -> bool:
        return str(one.call.request.tool.capability) == ANSWER_OFFER_CAPABILITY

    return _Answering(
        decided=decided,
        first=replace(
            decided,
            allowed=tuple(one for one in decided.allowed if answers(one)),
            message=None,
            call_messages=(),
        ),
        rest=tuple(one for one in decided.allowed if not answers(one)),
        refused=any(call_id not in allowed for call_id in asked),
    )


def _in_round_order(decided: RoundAuthorization, *parts: ActedRound) -> ActedRound:
    """``parts``' calls as one acting decision, in the round's order (ADR-0306 §5)."""
    order = {one.call.decision.id: index for index, one in enumerate(decided.allowed)}
    calls = sorted(
        (one for part in parts for one in part.calls),
        key=lambda one: order.get(one.call.call.decision.id, len(order)),
    )
    return ActedRound(round_id=decided.round_id, calls=tuple(calls))


def _commits(latest: _Round, decided: RoundAuthorization) -> bool:
    """Whether acting would dispatch something of the round that commits (ADR-0332 §3:2).

    A call that is not a pure read as ADR-0341 §2:1 defines it (:func:`is_pure_read`),
    or the round's message where it would be written. A call whose capability declares
    a write is not a pure read, a story call, ``remember`` and a tidy-up's write to the
    hub's own records among them, and neither is one that leaves the hub or one in the
    world. A look-up in memory or of a story writes nothing and stays in the hub, so it
    does not commit.
    """
    verdict = decided.message
    message = (
        verdict is not None
        and verdict.allowed
        and verdict.effect_id is not None
        and latest.planned.message is not None
    )
    # ADR-0356 §7:7: a ``text`` call is the round's message in the form of a call.
    texts = any(one.allowed and one.effect_id is not None for one in decided.call_messages)
    return (
        message or texts or any(not is_pure_read(one.call.request.tool) for one in decided.allowed)
    )


def _commitment(
    state: ActivationState, latest: _Round, decided: RoundAuthorization
) -> ActedRound | None:
    """Acting's commitment step for the latest round, or ``None`` where it may run.

    ADR-0349 §7:14, after the wait before an act and **in one synchronous step** with no
    await between: where the stop mark is set, nothing of the round is dispatched and the
    pass ends on the stop (ADR-0297 §4); where an offer is open to this activation that
    this round's planning was not shown, made before the wait or during it, none of its
    calls and not its message is dispatched, each allowed call is not done with the
    reason, and planning runs a round again, shown the offer; and otherwise the
    activation is marked committed, if it was not already
    (:meth:`ActivationState.commit`).

    Returns:
        ``None`` where the round runs. Otherwise acting's decision for it, present and
        dispatching nothing by any path.
    """
    if state.stopped:
        _log.info("phase_round_not_acted", stage="acting", reason="stopped")
        return ActedRound(round_id=decided.round_id)
    if any(offering not in latest.offers_shown for offering in state.offers):
        _log.info("phase_round_held_back", stage="acting", reason="offer")
        return ActedRound(
            round_id=decided.round_id,
            calls=tuple(
                ActedCall(call=one, outcome=ActedOutcome.NOT_DONE, reason=_HELD_BACK)
                for one in authorized_round(decided).calls
            ),
            set_aside=True,
        )
    if state.commit() is Commitment.STOPPED:  # pragma: no cover — read just above
        return ActedRound(round_id=decided.round_id)
    return None


#: Why a ``text`` call of a round the stop ended before it was dispatched was not sent.
_STOPPED_UNSENT: Final = "the work was stopped before it was sent"


def _unsent(latest: _Round, reason: str) -> None:
    """Hold each ``text`` call the latest round may send as not done, unwritten, for ``reason``.

    ADR-0349 §7:14, ADR-0352 §4:2: a round whose acts were held back writes no message,
    a ``text`` call included (ADR-0356 §7:7), and sent nothing.
    """
    decided = latest.authorization
    if decided is None:
        return
    for one in decided.call_messages:
        if one.allowed and one.call_id is not None:
            latest.sent.setdefault(one.call_id, _Sent(CallOutcomeKind.NOT_DONE, reason=reason))


def _working(given: PhasePass) -> PhaseWorking:
    """The pass's phase working set, which a phase stage runs only where it is held.

    Raises:
        RuntimeError: If the pass runs no phases, which the rules make impossible.
    """
    working = given.phases
    if working is None:
        msg = "a phase stage runs only on a pass the phases plan (ADR-0309 §2:6)"
        raise RuntimeError(msg)
    return working


def _expired(message: str) -> Callable[[PhasePass], Exception | None]:
    """A phase stage is not entered once the pass's deadline has passed (ADR-0280 §5)."""

    def expired(given: PhasePass) -> Exception | None:
        if given.deadline <= asyncio.get_running_loop().time():
            return ModelTimeoutError(message)
        return None

    return expired


def _ended_by(state: ActivationState, rule: ControllerRule) -> bool:
    """Whether the pass's end entry is due ``rule``."""
    entries = state.stages.entries
    return bool(entries) and entries[-1].stage is ControllerStage.END and entries[-1].due is rule


def _listed(capability: str, outcome: ToolOutcome) -> str:
    """One effect, as *couldn't finish* lists it: done, or not known to be."""
    if outcome is ToolOutcome.INDETERMINATE:
        return f"the tool {capability} may have run; whether it did is not known"
    return f"the tool {capability} ran"


def _stopped(state: ActivationState | None) -> bool:
    """Whether the pass ended on a stop, which writes nothing (ADR-0295 §3:3)."""
    return state is not None and _ended_by(state, ControllerRule.STOPPED)


def _unfinished(working: PhaseWorking, state: ActivationState | None) -> bool:
    """Whether a pass that returned did not finish, so *couldn't finish* is owed.

    ADR-0317 §3:2-§3:4: the round limit or the loop guard ended it, whatever earlier
    rounds wrote, or its last message was refused or lost with none recorded after it.
    Any other pass that returned has finished, a silent one included (§2), and a stop
    owes nothing (§3:6). A place that takes no message is never written to, so there
    only the round limit and the loop guard, which counts as a stage's failure (§3:3),
    leave the activation unfinished (ADR-0313 §4:5).
    """
    if _stopped(state):
        return False
    ended = state is not None and (
        _ended_by(state, ControllerRule.ROUND_LIMIT_REACHED)
        or _ended_by(state, ControllerRule.STAGE_REPEATED)
    )
    return ended or (working.place.takes_message and working.undelivered)


def failing_stage(state: ActivationState | None) -> ControllerStage | None:
    """The stage whose failure ended the pass, read off its record, or ``None``.

    Read as the controller chose it (ADR-0280 §5, ADR-0309 §3:3-§3:4): the step just
    before an end entry due ``stage_failed`` is its last entry, with the one run
    beside it where there was one, the two sharing their rule and their start, the
    first's entry ahead of the second's. Its first entry not ``done`` ended the pass: a
    stage that failed beside another is recorded ``failed`` too, once cancelled, but it
    is never what ended it. ``None`` where the pass did not end on a stage's failure,
    such as one that failed before its first stage ran.
    """
    if state is None or not _ended_by(state, ControllerRule.STAGE_FAILED):
        return None
    ran = state.stages.entries[:-1]
    if not ran:
        return None
    last = ran[-1]
    step = [
        one
        for one in ran[-2:]
        if one is last
        or (
            one.stage is not last.stage and (one.due, one.started_at) == (last.due, last.started_at)
        )
    ]
    return next((one.stage for one in step if one.outcome is not StageOutcome.DONE), None)


def _fetched_external(fetched: Fetched | None) -> bool:
    """Whether a record the windows or recall brought rests on outside content (ADR-0223)."""
    return bool(_fetched_outside(fetched))


def _fetched_outside(fetched: Fetched | None) -> tuple[str, ...]:
    """The ids of the records the windows or recall brought resting on outside content.

    An episode counts by its provenance, its input from outside, whose understood
    meaning planning is still shown (ADR-0303 §3:2), or its evidence (ADR-0308
    §5:4-§5:5), whether or not the round that reads it keeps notes; a marked note of its
    rounds is counted where planning is shown it, and by authorizing from its label. A
    memory record counts by its provenance (ADR-0223).
    """
    if fetched is None:
        return ()
    records = (*(fetched.episodes or ()), *fetched.recalled)
    return tuple(
        one.id
        for one in records
        if (
            rests_on_outside_content(one)
            if isinstance(one, EpisodicMemory)
            else one.rests_on_outside_content
        )
    )


def _window_records(given: PhasePass) -> tuple[MemoryRecord, ...]:
    """The stored records the pass's windows gave the activation (ADR-0276 §3-§4).

    The episode window's records as the understanding phase fetched them. The channel
    window gives none: a supplied item and a transcript message are not stored records.
    """
    fetched = given.understanding_fetch
    return () if fetched is None or fetched.episodes is None else fetched.episodes


def _hold_given(given: PhasePass, working: PhaseWorking, state: ActivationState | None) -> None:
    """Hold what the stages before planning gave the activation (ADR-0309 §5:10).

    The windows' records; the first recall run's kept records as the understanding phase
    fetched them; the episodes of the candidate stories it was shown (ADR-0300 §6:1);
    and every memory of the person block a stage was shown (ADR-0338 §7:1), as the
    activation's state holds them. Held again on each call, which holds each record once.
    """
    if state is not None:
        working.supplied.obtained(state.person_given)
    working.supplied.windows(_window_records(given))
    fetched = given.understanding_fetch
    if fetched is not None:
        working.supplied.obtained(fetched.recalled)
    candidates = given.story_candidates
    if candidates is not None:
        working.supplied.obtained(record for view in candidates.views for record in view.episodes)


def _found_outside(found: Fetched) -> tuple[str, ...]:
    """The ids of the found episodes planning is shown resting on outside content (ADR-0223).

    Counted as the episode window's are. A found memory record whose source is outside
    is never shown to planning (ADR-0308 §3:3), and one whose source is not outside rests
    on none, so only an episode can count.
    """
    return tuple(
        one.id
        for one in found.recalled
        if isinstance(one, EpisodicMemory) and rests_on_outside_content(one)
    )


def _recalled_stories(*decisions: Recalled | None) -> dict[str, tuple[str, ...]]:
    """The stories each found episode is in, as its run recorded them (ADR-0300 §7:2)."""
    return {
        item.id: tuple(item.stories)
        for decision in decisions
        if decision is not None
        for item in decision.result.items
        if item.stories
    }


def _kept_outside(*decisions: Recalled | None) -> tuple[str, ...]:
    """The memory records the runs kept whose source is outside, once each, in order.

    Read off each kept item's recorded origin (ADR-0306 §5:16, ADR-0281 §6): a memory
    resting on recorded outside content (ADR-0328 §2:5-§2:6). A found episode is never digested,
    and is shown by its records instead (ADR-0308 §3:1).
    """
    return tuple(
        dict.fromkeys(
            item.id
            for decision in decisions
            if decision is not None
            for item in decision.result.items
            if item.kind is MemoryKind.MEMORY and item.rests_on_recorded_external_content
        )
    )


@dataclass(frozen=True)
class _DigestRuns:
    """One ``digesting`` stage for recall's digest and a round's (ADR-0308 §4, ADR-0309 §3).

    ``recall_undigested`` makes digesting due for recall's digest before the first
    round, and ``round_authorized`` runs it beside acting for a round's results. The
    controller runs one stage per name, so this one runs recall's digest while that
    row's facts hold, and the round's otherwise. Recall's digest is decided before
    either returns, so the row does not answer again.
    """

    recall: ControllerStageRun[PhasePass]
    rounds: ControllerStageRun[PhasePass]

    @property
    def name(self) -> ControllerStage:
        """Digesting, under either row."""
        return ControllerStage.DIGESTING

    async def run(self, state: PhasePass) -> StageResult:
        """Run recall's digest where it is due, else the latest round's digests."""
        if recall_digest_due(_working(state)):
            return await self.recall.run(state)
        return await self.rounds.run(state)


@dataclass(frozen=True)
class _RecallRuns[P: PhasePass]:
    """One ``recall`` stage over both runs, the rows deciding which is due (ADR-0308 §2).

    ``not_recalled`` makes recall due while the pass has no first decision, and
    ``understood_not_recalled`` once it has one, so the first run runs where there is
    none and the second otherwise. Each run records its own decision before it returns.
    """

    first: ControllerStageRun[P]
    again: ControllerStageRun[PhasePass]

    @property
    def name(self) -> ControllerStage:
        """Recall, under either row."""
        return ControllerStage.RECALL

    async def run(self, state: P) -> StageResult:
        """Run the first run where the pass has no recall decision, else the second."""
        if state.recalled is None:
            return await self.first.run(state)
        return await self.again.run(state)


class PhasePath:
    """The phases' stages, and what one activation's rounds need around them.

    Built by the composition root on every deployment (ADR-0309 §2:6). The
    engine attaches its episode append, starts each activation's working set with
    :meth:`begin`, hands the controller :meth:`stages` beside its own, and runs the
    pass through :meth:`run`, which writes the *couldn't finish* message where it is
    owed and carries what the episode freezes with.
    """

    def __init__(  # noqa: PLR0913 — the four phases' seams, the tools, the writer, the store, and the provisional numbers
        self,
        *,
        completer: ToolCallingCompleter,
        provider: StructuredCompleter,
        authorizing: AuthorizingStage,
        acting: ActingStage,
        tools: PhaseTools,
        plans: PlanStore,
        writer: MessageWriter,
        round_limit: int,
        round_wait: timedelta,
        excerpt_chars: int,
        planning_prompt: PromptTemplate,
        digesting_prompt: PromptTemplate,
        part_chars: int,
        memory: MemoryStore,
        recall_cap: int,
        recall_digest_wait: timedelta,
        capabilities: Sequence[str] | None = None,
        planning_model: str | None = None,
        story_reads: StoryReads | None = None,
        label_arguments: Mapping[str, Mapping[str, LabelKind]] | None = None,
        story_calls: StoryCalls | None = None,
        look_ups: LookUps | None = None,
        showed_chars: int = SHOWED_CHARS,
        now: Callable[[], datetime] = _utcnow,
        timezone: str = "UTC",
        new_effect_id: Callable[[], str] = _new_effect_id,
        diagnostics: DiagnosticSink | None = None,
    ) -> None:
        """Wire the path.

        Args:
            completer: The native tool-calling seam planning's rounds go through.
            provider: The structured seam a digest's calls go through (ADR-0308 §4:10,
                ADR-0354 §9:1).
            authorizing: The authorizing stage, built over :class:`PhaseTools`.
            acting: The acting stage, its invoker :class:`PhaseTools`.
            tools: The thin path's registry and invoker.
            plans: The plan store a message's effect record is claimed in.
            writer: The place's writer.
            capabilities: The capabilities planning is offered, by name (§4:2), or
                ``None``, the default, for every one ``tools`` advertises, read as each
                round is planned. Either way the clock is left out (#2942).
            round_limit: The most rounds an activation runs (ADR-0307 §8:4).
            round_wait: How long the step running a round's calls waits on its
                digests at most: the call's deadline that bounds the wait (§8:2).
            excerpt_chars: The bound planning cuts another episode's texts to.
            planning_prompt: Planning's instruction template, as the composition root
                read it at start (ADR-0334 §3:5), handed on to planning.
            digesting_prompt: Digesting's instruction template, as the composition
                root read it at start (ADR-0334 §3:5), handed on to digesting.
            part_chars: ``DIGEST_PART_CHARS`` (ADR-0308 §4:9).
            memory: The memory store planning fetches recall's kept records from
                (ADR-0282 §2:4).
            recall_cap: ``RECALL_SECOND_RUN_CAP``: how many records recall's second
                run keeps in all (ADR-0308 §2:4-§2:5).
            recall_digest_wait: The deadline bounding recall's digest, its fetch
                included, cut to what the pass has left (ADR-0308 §4:11 names only a
                result's; this one is the composition root's).
            planning_model: Optional ``"provider:model"`` override for planning.
            story_reads: What planning is shown of stories (ADR-0307 §6:1), or
                ``None`` where no story store is wired, which shows it none.
            label_arguments: For an offered capability, which of its arguments name
                things by label and what kind of thing each names, such as the story
                calls' (ADR-0307 §5:2); planning maps them to ids, and refuses whole a
                call naming a label it was never shown (§5:3).
            story_calls: The story calls' runner, whose check refuses whole, before
                authorizing, a move or a split naming a note the story it moves from does
                not hold as the stories stand then, or naming any note on a pass that may
                not show the owner's records (ADR-0307 §5:3-§5:4, §6:5); ``None`` where no
                story call is offered.
            look_ups: The look-ups' runner, the same object acting reaches through its
                own-records seam, whose scope this path opens around acting so a
                look-up reads under the pass's audience (ADR-0307 §6:6); ``None``
                where no look-up is offered.
            showed_chars: The bound, in characters, on what a call's entry keeps of what
                its result showed (ADR-0358 §11:4).
            now: The clock a step's start and an effect's claim are read from.
            timezone: The IANA name of the zone planning is shown the current time in
                (#2964), handed on to planning: ``Settings.timezone``.
            new_effect_id: Mints the *couldn't finish* message's effect record id.
            diagnostics: The diagnostic record's write seam, handed on to planning
                and digesting, which this path builds (ADR-0314 §4:4); ``None`` where
                the record is off. The path itself writes no entry (§4:2).

        Raises:
            ValueError: If ``round_limit`` is below 1, ``round_wait`` or
                ``recall_digest_wait`` not positive, ``recall_cap`` below 1 or above
                ``RECALLED_ITEMS_MAX``, or ``showed_chars`` below 1.
        """
        if showed_chars < 1:
            msg = "an entry keeps at least one character of what its call showed"
            raise ValueError(msg)
        if round_limit < 1:
            msg = "the round limit is at least one round (ADR-0307 §8:4)"
            raise ValueError(msg)
        if round_wait <= timedelta(0):
            msg = "a round's wait is positive (ADR-0307 §8:2)"
            raise ValueError(msg)
        if recall_digest_wait <= timedelta(0):
            msg = "recall's digest's deadline is positive (ADR-0308 §4:11)"
            raise ValueError(msg)
        if not 1 <= recall_cap <= RECALLED_ITEMS_MAX:
            msg = "the second run's cap is between 1 and RECALLED_ITEMS_MAX (ADR-0308 §2:5)"
            raise ValueError(msg)
        self._now = checked_clock(now, owner="PhasePath")
        self._planning = PlanningStage(
            completer=completer,
            recorder=_RoundRecorder(self),
            excerpt_chars=excerpt_chars,
            prompt=planning_prompt,
            model=planning_model,
            now=now,
            timezone=timezone,
            diagnostics=diagnostics,
        )
        self._digesting = DigestingStage(
            provider=provider,
            recorder=_DigestRecorder(self),
            part_chars=part_chars,
            prompt=digesting_prompt,
            now=now,
            diagnostics=diagnostics,
        )
        self._authorizing = authorizing
        self._acting = acting
        self._tools = tools
        self._plans = plans
        self._writer = writer
        self._capabilities = None if capabilities is None else tuple(capabilities)
        self._round_limit = round_limit
        self._round_wait = round_wait
        self._new_effect_id = new_effect_id
        self._memory = memory
        self._recall_cap = recall_cap
        self._recall_digest_wait = recall_digest_wait
        self._story_reads = story_reads
        self._label_arguments: dict[str, Mapping[str, LabelKind]] = {
            name: dict(arguments) for name, arguments in (label_arguments or {}).items()
        }
        # ADR-0357 §2:4: a ``text`` call's ``via`` names a place by its L label or a
        # platform by name, so it is resolved by the phases (`_text_place`), never by the
        # judge's label check, which would refuse a platform.
        self._story_calls = story_calls
        self._look_ups = look_ups
        self._showed_chars = showed_chars
        # ADR-0338 §11:2: the person model's calls, attached only where a store is wired.
        self._person_calls: PersonModelCalls | None = None
        # ADR-0350 §4: the Task Scheduler's calls, attached only where it is wired.
        self._task_calls: ScheduledTaskCalls | None = None
        # ADR-0349 §4-§7: what crosses the engine's activations, attached by the engine.
        self._matters: Matters | None = None
        self._append: Callable[[], Awaitable[None]] | None = None
        self._spawn: Callable[[Coroutine[None, None, None]], None] = self._spawn_held
        self._closing: Callable[[], bool] = _never
        # The tidy-ups this path started itself, held so none is collected mid-run,
        # where no engine is attached to track them.
        self._held: set[asyncio.Task[None]] = set()

    def attach(
        self,
        append: Callable[[], Awaitable[None]],
        *,
        spawn: Callable[[Coroutine[None, None, None]], None] | None = None,
        closing: Callable[[], bool] | None = None,
    ) -> None:
        """Attach the engine's episode append, and its seams for work nobody waits on.

        Args:
            append: Extends the current activation's open episode.
            spawn: Starts a coroutine as work the engine tracks and drains at shutdown,
                in a context of its own; a tidy-up call runs under it (ADR-0307 §7:2).
                Unattached, this path holds the task itself.
            closing: Whether the engine's shutdown has begun, after which no tidy-up
                starts: what it would take in stays pending (ADR-0300 §5).
        """
        self._append = append
        if spawn is not None:
            self._spawn = spawn
        if closing is not None:
            self._closing = closing

    def attach_person_model(self, blocks: PersonBlocks) -> None:
        """Offer planning the person model's three calls, over the stores ``blocks`` reads.

        ADR-0338 §8:4-§8:8. The engine attaches the person block's assembly here exactly
        where it is handed one, so the calls are offered where a person-model store is
        wired and nowhere else (§11:2): ``set_profile``, ``pin`` and ``unpin`` are
        advertised among the own records' declarations, so authorizing's selection
        reaches them; acting runs each by one
        :class:`~ai_assistant.orchestration.person_calls.PersonModelCalls`; and a
        ``pin``'s and an ``unpin``'s memory is named by its ``M`` label.

        Args:
            blocks: The person block's assembly, over the person-model store, the memory
                store and the slot's budget.

        Raises:
            ValueError: If the person model is attached already, or a capability it
                declares is advertised already.
        """
        if self._person_calls is not None:
            msg = "the person model's calls are attached once"
            raise ValueError(msg)
        calls = PersonModelCalls(blocks=blocks)
        self._tools.add_own_records(PERSON_MODEL_CALLS)
        self._acting.add_own_records(dict.fromkeys(PERSON_MODEL_CAPABILITIES, calls))
        self._label_arguments.update(PERSON_MODEL_LABEL_ARGUMENTS)
        self._person_calls = calls

    def attach_task_scheduler(self, calls: ScheduledTaskCalls) -> None:
        """Offer planning the Task Scheduler's three calls, run by ``calls`` (ADR-0350 §4).

        ``spawn``, ``cancel_task`` and ``list_tasks`` are advertised among the own records'
        declarations; acting runs each by ``calls``, directly against the plan store
        (§4:3); and their task, place and earlier-task arguments are named by label
        (ADR-0307 §5:2). They are offered on every round, and run only in an activation
        offered spawn (§3:4), whose working set holds :class:`Scheduling`: in any other a
        call to one comes back refused (ADR-0356 §4:5).

        Raises:
            ValueError: If it is attached already, or a capability it declares is
                advertised already.
        """
        if self._task_calls is not None:
            msg = "the Task Scheduler's calls are attached once"
            raise ValueError(msg)
        self._tools.add_own_records(TASK_SCHEDULER_CALLS)
        self._acting.add_own_records(dict.fromkeys(TASK_SCHEDULER_CAPABILITIES, calls))
        self._label_arguments.update(TASK_SCHEDULER_LABEL_ARGUMENTS)
        self._task_calls = calls

    def attach_matters(self, matters: Matters) -> None:
        """Offer planning its calls on running work, and hold the waits (ADR-0349 §4-§7).

        The stop call, the findings look-up and the answer call are advertised among the
        own records' declarations; acting runs each by one
        :class:`~ai_assistant.orchestration.matter_calls.MatterCalls` over ``matters``; and
        each names a running activation by its episode's ``E`` label (ADR-0307 §5:2).
        Acting's wait before an act (§7:12) and planning's waits on an older activation
        (§7:25-§7:26) read ``matters`` too.

        Raises:
            ValueError: If it is attached already, or a capability it declares is
                advertised already.
        """
        if self._matters is not None:
            msg = "the calls on running work are attached once"
            raise ValueError(msg)
        self._tools.add_own_records(MATTER_CALLS)
        calls = MatterCalls(matters=matters)
        self._acting.add_own_records(dict.fromkeys(MATTER_CAPABILITIES, calls))
        self._label_arguments.update(MATTER_LABEL_ARGUMENTS)
        self._matters = matters

    def conversation_target(self, conversation_id: str) -> PlaceTarget:
        """A conversation of the hub's chat as a place a message goes into, with its writer."""
        return PlaceTarget(
            channel=conversation_channel(conversation_id),
            writer=_ConversationWriter(self._writer, conversation_id),
        )

    def _spawn_held(self, work: Coroutine[None, None, None]) -> None:
        """Start ``work`` as a task this path holds until it ends."""
        task = asyncio.get_running_loop().create_task(work, context=contextvars.Context())
        self._held.add(task)
        task.add_done_callback(self._held.discard)

    async def append(self) -> None:
        """Extend the current activation's open episode, where an append is attached."""
        if self._append is not None:
            await self._append()

    def begin(  # noqa: PLR0913 — the activation, its window, its place, its trigger, its audience and its recorded labels
        self,
        *,
        activation_id: str,
        window: TranscriptWindow,
        conversation_id: str,
        trigger: RecordedChannelTrigger | None,
        owner_records: bool,
        labels: Sequence[PlanningLabel] = (),
    ) -> PhaseWorking:
        """Start one conversation turn's working set, before its first stage.

        A turn is the hub chat's: the chat's reader brings its input in. Its input
        carries the user's authority (ADR-0321 §3:3, ADR-0292 §5:5) only where the
        trigger's parties are the user alone (ADR-0351 §6:1) and every message taken in
        is the user's, the author a conversation establishes; anything not established
        is not the user's.
        A yes it carries is given when its latest message was written (§4:6).

        Args:
            activation_id: The activation.
            window: The conversation's recent transcript, brought in with the input.
            conversation_id: The conversation the input came from, which a message is
                written into (ADR-0307 §3:1).
            trigger: The activation's recorded trigger, whose parties say whose words its
                input carries.
            owner_records: Whether a record placed for the owner alone may be shown.
            labels: The labels the episode already records.

        Returns:
            The working set, which the engine holds on the pass.
        """
        taken = window.input_messages
        working = PhaseWorking(
            activation_id=activation_id,
            place=place_window(window),
            conversation_id=conversation_id,
            trigger=trigger,
            owner_records=owner_records,
            round_limit=self._round_limit,
            labels=labels,
            users_authority=(
                trigger is not None
                and parties_are_persons_own(trigger.parties)
                and bool(taken)
                and all(one.author is MessageAuthor.USER for one in taken)
            ),
            given_at=max((one.written_at for one in taken), default=None),
        )
        # ADR-0358 §9:2: the chat's window is read from its transcript, so its older
        # history is the transcript before the oldest recent message the window showed.
        working.older = OlderSource(
            conversation_id=conversation_id,
            before=min((one.position for one in (*window.messages, *taken)), default=None),
            shown=frozenset(one.position for one in (*window.messages, *taken, *window.replied_to)),
        )
        return working

    def begin_line(  # noqa: PLR0913 — the activation, its window, its place, its kind's two facts, its trigger, its audience and its recorded labels
        self,
        *,
        activation_id: str,
        window: TranscriptWindow,
        target: PlaceTarget,
        description: str,
        giver: ApprovalGiver,
        trigger: RecordedChannelTrigger | None,
        owner_records: bool,
        labels: Sequence[PlanningLabel] = (),
    ) -> PhaseWorking:
        """Start one activation's working set for a line's chat, before its first stage.

        A line is a place other than the hub chat's conversations whose kind
        establishes the user, as the Telegram line's chat (ADR-0323 §2): its reader
        brings the input in with the window its kind declares (§10), and its messages
        go into the input's place through ``target``'s writer alone (§6:1). Its input
        carries the user's authority (ADR-0321 §3:3 as ADR-0323 §4:7 restates it) only
        where the trigger's parties are the user alone (ADR-0351 §6:1, §6:3) and **every
        message taken in is the user's, established, and none is a forward** (§4:6): a
        forward's party is its original sender, claimed (ADR-0351 §2:7), and an input
        taking one in is an outside trigger (§5:3). A yes it carries is given by
        ``giver`` when its latest message was sent (§4:9).

        Args:
            activation_id: The activation.
            window: The line's window, brought in with the input.
            target: The line's chat and its writer.
            description: The line's kind's description, which planning is shown with
                the place (ADR-0292 §8:1).
            giver: Who a yes on the line is: the user, through it (§4:9).
            trigger: The activation's recorded trigger, whose parties say whose words its
                input carries.
            owner_records: Whether a record placed for the owner alone may be shown.
            labels: The labels the episode already records.

        Returns:
            The working set, which the engine holds on the pass.
        """
        taken = window.input_messages
        working = PhaseWorking(
            activation_id=activation_id,
            place=place_window(window, description=description),
            conversation_id=None,
            trigger=trigger,
            owner_records=owner_records,
            round_limit=self._round_limit,
            labels=labels,
            users_authority=(
                trigger is not None
                and parties_are_persons_own(trigger.parties)
                and bool(taken)
                and all(
                    one.author is MessageAuthor.USER and one.position not in window.forwarded
                    for one in taken
                )
            ),
            given_at=max((one.written_at for one in taken), default=None),
            target=target,
            giver=giver,
        )
        # ADR-0358 §9:2, ADR-0323 §10:1: a line's window is its recent episodes on the
        # channel and place, so its older history is the earlier episodes there, bounded
        # by this activation's start where the window showed none.
        state = active_state()
        working.older = OlderSource(
            channel=window.conversation,
            episodes=frozenset(
                item.episode_id for item in working.place.items if item.episode_id is not None
            ),
            started=None if state is None else state.started_at,
        )
        return working

    def begin_event(
        self,
        *,
        activation_id: str,
        trigger: RecordedChannelTrigger | None,
        owner_records: bool,
        labels: Sequence[PlanningLabel] = (),
    ) -> PhaseWorking:
        """Start one event's working set: a place that takes no message (ADR-0313 §4:3).

        There is no conversation, so no message is written for the event, the *couldn't
        finish* message included, and authorizing is handed no place (ADR-0307 §3:8,
        ADR-0309 §5:6). The event's own words reach planning through understanding's
        record alone, as an outside report (ADR-0307 §9:2), so its place window is empty.

        Its input never carries the user's authority: an email, a timer or any other
        event saying yes approves nothing (ADR-0321 §3:3), and a call that needs the
        user is neither asked about nor run (§7:3). It is taken to be given when it
        begins, which only the record of a refused yes reads.

        Args:
            activation_id: The activation.
            trigger: The activation's recorded trigger.
            owner_records: Whether a record placed for the owner alone may be shown.
            labels: The labels the episode already records.

        Returns:
            The working set, which the engine holds on the pass.
        """
        return PhaseWorking(
            activation_id=activation_id,
            place=PlaceWindow(takes_message=False, description=EVENT_DESCRIPTION),
            conversation_id=None,
            trigger=trigger,
            owner_records=owner_records,
            round_limit=self._round_limit,
            labels=labels,
            users_authority=False,
            given_at=self._now(),
        )

    def begin_task(
        self,
        *,
        activation_id: str,
        trigger: RecordedChannelTrigger | None,
        lineage: Sequence[PlaceItem],
        labels: Sequence[PlanningLabel] = (),
    ) -> PhaseWorking:
        """Start the working set of an activation a scheduled task started (ADR-0350 §6).

        Its place is the schedule, whose window is its task's lineage (§6:5), and its
        messages go into the places on its place list it names, each by its label
        (§6:7): the engine attaches :class:`Scheduling` before the first round, and each
        round's list says whether it may write a message at all (§5:7). Its input never
        carries the person's authority: a scheduled task authorizes nothing (§3:9), so
        no yes is read from it and no call needing the person runs.

        Args:
            activation_id: The activation.
            trigger: The activation's recorded trigger, whose parties are the assistant's
                statement, with unknown where its task carries the outside-content mark
                (ADR-0351 §3:6).
            lineage: The schedule's place window, the lineage as steps (§6:5).
            labels: The labels the episode already records.

        Returns:
            The working set, which the engine holds on the pass.
        """
        return PhaseWorking(
            activation_id=activation_id,
            place=PlaceWindow(
                takes_message=False, description=TASK_SCHEDULER_DESCRIPTION, items=tuple(lineage)
            ),
            conversation_id=None,
            trigger=trigger,
            owner_records=True,
            round_limit=self._round_limit,
            labels=labels,
            users_authority=False,
            given_at=self._now(),
        )

    async def written(
        self, conversation_id: str, activation_ids: Sequence[str], positions: Sequence[int]
    ) -> dict[int, WrittenBy]:
        """Which of ``activation_ids`` wrote each message at ``positions`` in a conversation.

        :meth:`written_in`, for the hub chat's reader, which names the conversation.
        """
        return await self.written_in(_place_id(conversation_id), activation_ids, positions)

    async def written_in(
        self, place: str, activation_ids: Sequence[str], positions: Sequence[int] | None
    ) -> dict[int, WrittenBy]:
        """Which of ``activation_ids`` wrote each message at ``positions`` (ADR-0303 §7:1).

        Read from their effect records (ADR-0306 §5:3): a message done in this
        conversation, at a named position, links to the activation that wrote it. A
        position no record names is simply missing, as is every one where the records
        cannot be read: the message is then not linkable, the conservative direction
        (§7:5), and the window is still brought in.

        Each such message is also the question its round asked, where it is one
        (ADR-0322 §4:1-§4:3): its record names the round, and the writer's stored
        episode, projected, marks that round with the parts it asked about, read from
        the round's recorded asked calls and never from the message's text. Where the
        episodes cannot be read, no message is a question, failing closed.

        Args:
            place: The place the messages are in, as their effect records name it
                (:func:`~ai_assistant.orchestration.channel_kinds.place_of`).
            activation_ids: The candidate activations.
            positions: The assistant messages' positions, or ``None`` for every
                message the candidates wrote into the place: the Telegram line's
                window, built from its episodes, reads them so (ADR-0323 §10).

        Returns:
            What wrote each message, by its position.
        """
        wanted = None if positions is None else frozenset(positions)
        if not activation_ids or (wanted is not None and not wanted):
            return {}
        try:
            recorded = await self._plans.activation_effects(activation_ids)
        except Exception:  # the store is down: nothing is linked by what wrote it
            _log.warning("phase_writers_unread", stage="reader", reason="store_failed")
            return {}
        done = [
            one
            for one in recorded
            if not one.is_call
            and one.place == place
            and one.outcome is ToolOutcome.SUCCEEDED
            and one.position is not None
            and (wanted is None or one.position in wanted)
        ]
        marks = await self._question_marks(
            [one.activation_id for one in done if one.round is not None]
        )
        return {
            one.position: WrittenBy(
                activation_id=one.activation_id,
                asked=None
                if one.round is None or (parts := marks.get((one.activation_id, one.round))) is None
                else AskedIn(round=one.round, parts=parts),
                round=one.round,
            )
            for one in done
            if one.position is not None
        }

    async def _question_marks(
        self, activation_ids: Sequence[str]
    ) -> dict[tuple[str, str], tuple[int, ...]]:
        """The parts each marked round of these activations' episodes asked about (§4:3).

        Read through ``project_episode``, by the activation and the round, since a round's
        id names it only within its activation: a message is marked from its own round's
        record and never another's. An episode still open, or one the store no longer
        holds, marks nothing, and a store that cannot be read marks nothing, so its
        messages carry no mark.
        """
        if not activation_ids:
            return {}
        addresses = list(dict.fromkeys(episode_address(one) for one in activation_ids))
        try:
            found = without_open_episodes(await self._memory.get_many(addresses))
        except Exception:  # the store is down: no message is marked a question
            _log.warning("phase_questions_unread", stage="reader", reason="store_failed")
            return {}
        marks: dict[tuple[str, str], tuple[int, ...]] = {}
        for record in found.values():
            processing = record.processing_record if isinstance(record, EpisodicMemory) else None
            if isinstance(record, EpisodicMemory) and processing is not None:
                projection = project_episode(record, excerpt_chars=1)
                marks.update(
                    ((processing.activation_id, round_id), one.asked)
                    for round_id, one in question_marks(record, projection)
                )
        return marks

    def stages(self) -> tuple[ControllerStageRun[PhasePass], ...]:
        """The four phase stages, as the controller runs them (ADR-0309 §3)."""
        return (
            Stage(ControllerStage.PLANNING, self._plan, expired=_expired(_PLANNING_EXPIRED)),
            Stage(
                ControllerStage.AUTHORIZING,
                self._authorize,
                expired=_expired(_AUTHORIZING_EXPIRED),
            ),
            Stage(ControllerStage.ACTING, self._act, expired=_expired(_ACTING_EXPIRED)),
            _DigestRuns(
                recall=TolerantStage(
                    ControllerStage.DIGESTING,
                    self._digest_recall,
                    expired=_expired(_RECALL_DIGEST_EXPIRED),
                ),
                rounds=Stage(ControllerStage.DIGESTING, self._digest),
            ),
        )

    def recall_stage[P: PhasePass](
        self, first: ControllerStageRun[P], recall: RecallStage | None
    ) -> ControllerStageRun[P]:
        """The one ``recall`` stage the controller runs on a phases pass (ADR-0308 §2).

        The controller runs one stage per name, and recall runs twice on a pass: the
        first run, before understanding, is the engine's own ``first``; the second, once
        understanding has recorded, is run here over the same ``recall`` stage (§2:1).
        Which is due is the rules': ``not_recalled`` answers only while the pass has no
        first decision and ``understood_not_recalled`` only once it has one, so the
        stage runs the first where there is none and the second otherwise.

        Args:
            first: The engine's first run, exactly as it runs on today's path.
            recall: The recall stage the engine holds, or ``None`` where none is wired;
                the second run's row then never answers.

        Returns:
            The stage the controller runs under both rows.
        """

        async def again(given: PhasePass) -> StageResult:
            return await self._recall_again(given, recall)

        return _RecallRuns(
            first=first,
            again=TolerantStage(ControllerStage.RECALL, again, expired=_expired(_RECALL_EXPIRED)),
        )

    async def run(
        self,
        given: PhasePass,
        controlled: Callable[[], Awaitable[None]],
        *,
        state: ActivationState | None,
    ) -> None:
        """Run the pass, then write what its end owes and carry what the episode keeps.

        A pass that returned having finished ends done, and one whose rounds all wrote
        nothing writes nothing: planning chose silence (ADR-0317 §2). The fixed
        *couldn't finish* message is written into the input's place, whatever earlier
        rounds wrote, where a stage fails or times out, which this re-raises, and where a
        pass that returned was ended by the round limit or the loop guard, or its last
        message was refused or lost with none recorded after it (ADR-0317 §3:2-§3:4); a
        stop and a cancellation write nothing (§3:6). Where a pass that returned owes it,
        the state is marked unfinished, so the episode freezes ``failed`` and the
        current state reads *couldn't finish*, not done (ADR-0317 §3:5). Where the place
        takes no message, an event's, nothing is written, and only the round limit and
        the loop guard mark a pass that returned unfinished: having written nothing is
        how such a pass always ends (ADR-0307 §3:8, ADR-0313 §4:5). However it ended,
        the activation's messages become the episode's ``outcome``, and the facts the
        freeze derives are set (ADR-0286 §4:2): among them ADR-0204 §2's value, taken
        here once over everything the activation was given or obtained in every round
        (ADR-0309 §5:10). A defect it re-raises is not logged here: the engine, which
        answers every failure, logs it once (:func:`log_defect`, #2904).

        Raises:
            Exception: Whatever ``controlled`` raised, once the message is written.
        """
        working = _working(given)
        try:
            await controlled()
        except ActivationStoppedError:
            raise
        except Exception:
            if not _stopped(state):
                await self._couldnt_finish(working)
            raise
        else:
            if _unfinished(working, state):
                if state is not None:
                    # Unfinished, so the episode and the state say *couldn't finish*
                    # beside the message, not done (ADR-0317 §3:5).
                    state.unfinished = True
                await self._couldnt_finish(working)
        finally:
            if state is not None:
                # The state's digests are counted too: one recorded there whose append
                # was cancelled never reached the working set (ADR-0308 §5:4).
                external = (
                    working.read_outside_content
                    or _fetched_external(given.understanding_fetch)
                    or any(one.outcome is DigestOutcome.ANSWERED for one in state.digests)
                )
                state.response = working.outcome()
                # ADR-0356 §8:6: every call's entry not yet appended, its outcome where it
                # is now known and none where it is not, carried by the freezing revision.
                state.recorded_calls(
                    working.call_entries(self._now(), freezing=True, showed=self._showed_chars)
                )
                # ADR-0309 §5:10: taken once, here, over every round. The windows are
                # held again in case no round was planned to hold them.
                _hold_given(given, working, state)
                state.facts = CaptureFacts(
                    modality=Modality.TEXT,
                    supplied_withheld=working.supplied.withheld(given.supply),
                    derived_from_external=external,
                )
                state.holds_external(value=external)

    async def unbegun(
        self,
        *,
        activation_id: str,
        conversation_id: str | None = None,
        state: ActivationState | None,
        target: PlaceTarget | None = None,
        description: str = CHAT_DESCRIPTION,
    ) -> None:
        """Write *couldn't finish* for a conversation's activation that failed before :meth:`run`.

        What the reader marked is consumed, so an activation that failed after taking in
        any of the conversation's waiting messages and before its first stage ran writes
        the fixed message (ADR-0317 §3:3, ADR-0293 §10:2) — one that failed before its
        run began, such as a marking that failed part way, where :meth:`run` never wrote
        it. It is written as :meth:`run` writes it, claimed under the activation
        and listing the effects its records hold, and it becomes the episode's
        ``outcome``. A stop writes nothing (ADR-0295 §3:3), and a cancellation is not a
        failure and never reaches here (ADR-0293 §9:2). It never raises but for a
        cancellation: the activation is already ending on its own error.

        Args:
            activation_id: The activation that marked the messages.
            conversation_id: The conversation it marked them in, for the hub chat.
            state: The activation's state, read for its stop mark.
            target: The line's chat and its writer, for a line's activation, which
                marks what it took in on the line's own intake record (ADR-0323 §5:8).
            description: The place's kind's description.
        """
        if state is not None and state.stopped:
            return
        working = PhaseWorking(
            activation_id=activation_id,
            place=PlaceWindow(takes_message=True, description=description),
            conversation_id=conversation_id,
            trigger=None,
            owner_records=False,
            round_limit=self._round_limit,
            target=target,
        )
        try:
            await self._couldnt_finish(working)
        finally:
            # Whatever cancels the write, a message the place took is what the episode
            # records it sent (ADR-0284 §4:1), as :meth:`run` keeps it.
            if state is not None:
                state.response = working.outcome()

    # --- the stages ---

    def _wait(self, given: PhasePass) -> timedelta:
        """A round's wait: its call deadline, cut to what the pass has left (§8:2)."""
        return self._left(given, self._round_wait)

    @staticmethod
    def _left(given: PhasePass, bound: timedelta) -> timedelta:
        """``bound``, cut to what the pass has left."""
        left = max(given.deadline - asyncio.get_running_loop().time(), 0.0)
        return min(bound, timedelta(seconds=left))

    async def _plan(self, given: PhasePass) -> None:
        """One planning round, over everything the thin path gives it (ADR-0307 §6).

        **The waits on an older activation come first** (ADR-0349 §7:25-§7:28): while
        this activation's own offer is open, no round is planned; where, once it is not,
        it waits on work still running, its first round is a waiting round, and its
        next round is planned only once each activation it waits on has ended. The time
        waited moves its deadline later. Where a take stopped it meanwhile, no round is
        planned, and the pass ends on the stop.
        """
        working = _working(given)
        fetched = given.understanding_fetch
        state = active_state()
        if state is not None:
            await self._wait_on_older(state, working)
            if state.stopped:
                return
            # ADR-0349 §7:21: what an offer it took brought is input planning is shown.
            working.take_joined(
                state.joined, state.place, taken={one.activation_id for one in state.took}
            )
        waiting = self._waiting(state, working)
        offers = self._offers_open(state)
        working.shown_running.update(one.activation_id for one in waiting)
        working.shown_running.update(one.activation_id for one in offers)
        try:
            async with asyncio.timeout_at(given.deadline):
                found = await self._found(given, working)
                stories = await self._stories(given, working)
                await self._searched(given, working)
                # The yes's records are read inside the activation's deadline, as
                # every read before the round is (ADR-0280 §5).
                approved = await self._approved(given, working)
                pending = await self._pending(given, working)
                person = await self._person(working)
                # ADR-0338 §8:6: a pin's or an unpin's memory, worded for its question.
                outcomes = await self._worded(working)
                # ADR-0350 §5:8, §9:1: the place list built as it is shown, and the
                # scheduled task each linked activation ran.
                await self._scheduled(working)
                # ADR-0349 §7:10, §7:27: what this one took over or waited on, read now.
                earlier = await self._earlier_work(state, working)
        except TimeoutError:
            raise ModelTimeoutError(_PLANNING_EXPIRED) from None
        # ADR-0356 §8:6: each call's entry is appended once its outcome is known, before
        # the next round's request; after the reads, so a memory search's entry keeps the
        # records the round is shown, as fetched (ADR-0358 §11:2).
        await self._entries(working)
        outside = (
            *_fetched_outside(fetched),
            *_found_outside(found),
            *(() if stories is None else _stories_outside(stories)),
        )
        # Carried into planning's notes and authorizing's rulings from the first round,
        # not only into the frozen episode (ADR-0181 §4, ADR-0306 §4:6).
        working.fetched_resting_on_outside(outside)
        if stories is not None:
            working.notes.update((one.note_id, one) for one in _shown_notes(stories))
        _hold_given(given, working, active_state())
        # ADR-0356 §4:3: every capability on every round, in one fixed order; §4:4-§4:6:
        # each whose condition does not hold here comes back refused, saying why.
        offered = await self._offered()
        not_here = self._not_here(
            offered,
            person=person is not None,
            scheduling=working.scheduling is not None,
            running=self._running_calls(state, working, offers=bool(offers)),
            standing=state is not None
            and state.standing is not None
            and state.standing.author is not None,
            waiting=bool(waiting),
        )
        inputs = PlanningInputs(
            activation_id=working.activation_id,
            place=working.place,
            understanding=given.understanding,
            outside_trigger=working.outside_trigger,
            episodes=() if fetched is None or fetched.episodes is None else fetched.episodes,
            recalled=found.recalled,
            recalled_stories=_recalled_stories(given.recalled, working.second_recall),
            owner_records=working.owner_records,
            rounds=working.planning_rounds(),
            labels=working.labels.labels,
            outcomes=outcomes,
            capabilities=offered,
            label_arguments=self._label_arguments,
            evidence=tuple(working.evidence),
            outside_content_read=working.read_outside_content,
            stories=stories,
            # ADR-0349 §7:26: a waiting round is offered the stop call alone, so the
            # actions the input's yes approved wait, with the rest of its work, for the
            # rounds after the wait.
            approved=() if waiting else approved,
            pending=pending,
            overtaken=working.overtaken(),
            not_taken=working.not_taken(),
            person=person,
            places=None if working.scheduling is None else working.scheduling.places,
            speaks_by_label=working.scheduling is not None and working.scheduling.speaks_by_label,
            offers=offers,
            waiting=waiting,
            declined=() if state is None else state.declined,
            earlier_work=earlier,
            work=working.work,
            not_here=not_here,
        )
        # The round is recorded inside planning's call, so the recorder reads what it
        # needs of this activation from here (ADR-0321 §4:4: a question cut to fit).
        planning = _PLANNING.set(working)
        try:
            async with asyncio.timeout_at(given.deadline):
                planned = await self._planning.plan(inputs)
                planned = await self._notes_checked(planned, working)
        except TimeoutError:
            raise ModelTimeoutError(_PLANNING_EXPIRED) from None
        finally:
            _PLANNING.reset(planning)
        whole = self.shown_whole(working, planned.round, planned.questions, planned.labels)
        if whole is not planned.round:
            planned = replace(planned, round=whole)
        working.planned(
            planned,
            offers_shown=frozenset(one.activation_id for one in offers),
            waiting=bool(waiting),
            effects={
                str(one.capability): one.effect is not CapabilityEffect.NONE for one in offered
            },
        )
        if waiting:
            working.waiting_round_planned = True

    async def _wait_on_older(self, state: ActivationState, working: PhaseWorking) -> None:
        """ADR-0349 §7:25-§7:28: wait on an older activation before a round.

        While this activation's offer is open; and, after its waiting round, until each
        activation it waits on has ended.

        The time waited does not count against the pass's deadline: it is moved later by
        it (§7:28). Each older activation's own deadline and round limit bound the wait.
        """
        matters = self._matters
        if matters is None:
            return
        loop = asyncio.get_running_loop()
        began = loop.time()
        if state.offered_to is not None:
            await matters.offer_answered(state)
        if working.waiting_round_planned and matters.waiting_on(state):
            await matters.waited_ended(state)
        if not matters.waiting_on(state):
            # §7:27: from here on, every round is shown what it waited on.
            working.waited = state.waits_on
        waited = loop.time() - began
        if waited > 0 and working.move_deadline is not None:
            working.move_deadline(waited)

    def _waiting(
        self, state: ActivationState | None, working: PhaseWorking
    ) -> tuple[RunningShown, ...]:
        """Where this round is a waiting round, each activation it waits on (§7:26).

        The first round of an activation that waits on work still running once its offer
        is no longer open, each shown as an in-progress entry shows one.
        """
        matters = self._matters
        if matters is None or state is None or working.waiting_round_planned:
            return ()
        shown: list[RunningShown] = []
        for activation_id in matters.waiting_on(state):
            entry = matters.entry(activation_id)
            if entry is not None:
                shown.append(
                    RunningShown(
                        activation_id=entry.activation_id,
                        place=entry.channel,
                        input=entry.input,
                        acted=entry.acted,
                        parties=entry.parties,
                        outside=entry.outside,
                    )
                )
        return tuple(shown)

    def _offers_open(self, state: ActivationState | None) -> tuple[OfferShown, ...]:
        """Each offer open to this activation, as its planning is shown it (§7:19)."""
        if self._matters is None or state is None:
            return ()
        shown: list[OfferShown] = []
        for offer in state.offers.values():
            entry = self._matters.entry(offer.offering)
            given = None if entry is None else entry.input
            shown.append(
                OfferShown(activation_id=offer.offering, input=given, meaning=offer.meaning)
            )
        return tuple(shown)

    async def _earlier_work(
        self, state: ActivationState | None, working: PhaseWorking
    ) -> tuple[PeerShown, ...]:
        """The finished work of what this activation took over or waited on (§7:10, §7:27).

        Each read fresh through the peer view from that activation's own episode, so
        what an absorbed activation had taken in reaches the reader from its source.
        """
        matters = self._matters
        if matters is None or state is None:
            return ()
        shown: list[PeerShown] = []
        for activation_id in dict.fromkeys((*state.merged, *working.waited)):
            view = await matters.peer(activation_id, owner_records=working.owner_records)
            running = matters.state_of(activation_id)
            shown.append(
                PeerShown(
                    activation_id=activation_id,
                    view=view,
                    ended=running is None or running.stopped,
                )
            )
        return tuple(shown)

    def _running_calls(
        self, state: ActivationState | None, working: PhaseWorking, *, offers: bool
    ) -> frozenset[str]:
        """Which calls on running work this round is offered (§4:6, §6:1, §7:20).

        The stop call where the input carries the user's authority, and the look-up,
        each to an activation whose author its place establishes, the one viewer running
        work is shown to; the answer call where an offer is open to it.
        """
        standing = None if state is None else state.standing
        if standing is None or standing.author is None:
            return frozenset()
        names = {LOOK_UP_ACTIVATION_CAPABILITY}
        if working.users_authority:
            names.add(STOP_ACTIVATION_CAPABILITY)
        if offers:
            names.add(ANSWER_OFFER_CAPABILITY)
        return frozenset(names)

    async def _person(self, working: PhaseWorking) -> PersonBlock | None:
        """The activation's person block for this round, less what memory no longer holds.

        ADR-0338 §7:3, §7:10: the block assembled before understanding, from which every
        memory the memory store no longer holds is dropped before each round, the first
        included, and the state keeps what is left, so a memory forgotten while the
        activation runs reaches no later request. ``None`` where the activation has no
        block.

        What this round is shown of the block is held on the state beside what
        understanding was shown, and both among what the activation was given, so the
        episode inherits their placement (ADR-0309 §5:10, ADR-0217 §3) whatever is
        dropped later.
        """
        state = active_state()
        if state is None or state.person_block is None:
            return None
        state.person_block = await still_held(state.person_block, self._memory)
        state.gave_person_memories(state.person_block.memories)
        working.supplied.obtained(state.person_given)
        return state.person_block

    async def _pending(
        self, given: PhasePass, working: PhaseWorking
    ) -> Mapping[str, tuple[str, ...]]:
        """The episode window's pending candidates, read once (ADR-0329 §6:9).

        Each episode the window shows that the observer has not processed, with the facts
        of the candidates its own rounds recorded, read from the plan store as it stands
        before the first round. A plan store that cannot be read shows none, and planning
        goes on.
        """
        if working.pending is None:
            fetched = given.understanding_fetch
            episodes = () if fetched is None or fetched.episodes is None else fetched.episodes
            try:
                working.pending = await pending_candidates(self._plans, episodes)
            except PlanningError:
                _log.warning("planning_candidates_unread", stage="planning")
                working.pending = {}
        return working.pending

    async def _scheduled(self, working: PhaseWorking) -> None:
        """Build the place list for this round, and read the window's task links once.

        ADR-0350 §5:8: the list is built when it is shown, at every round. A task's
        activation writes a message only where its list holds a place (§5:7, §6:7).
        §9:1-§9:2: a place-window item an activation the Task Scheduler started wrote
        links to its task while the Task Scheduler holds it, read through the
        occurrence's pushed mark, and is shown with that task's label.
        """
        scheduling = working.scheduling
        if scheduling is not None:
            scheduling.places, scheduling.targets = await scheduling.build()
            if scheduling.speaks_by_label:
                working.place = replace(working.place, takes_message=bool(scheduling.targets))
        if self._task_calls is None or working.task_links is not None:
            return
        linked = {
            item.episode_id.removeprefix("activation:")
            for item in working.place.items
            if item.episode_id is not None and item.author is PlaceAuthor.ASSISTANT
        }
        links: dict[str, str] = {}
        for activation_id in sorted(linked):
            try:
                lineage = await self._plans.scheduled_lineage(activation_id)
            except PlanningError:
                _log.warning("phase_task_links_unread", stage="planning", reason="store_failed")
                break
            if lineage and activation_id in lineage[-1].activations:
                links[activation_id] = lineage[-1].id
        working.task_links = links
        if links:
            working.place = replace(
                working.place,
                items=tuple(
                    item
                    if item.episode_id is None
                    else replace(
                        item, task_id=links.get(item.episode_id.removeprefix("activation:"))
                    )
                    for item in working.place.items
                ),
            )

    async def _offered(self) -> tuple[ToolDefinition, ...]:
        """The declarations every round offers planning (ADR-0306 §2:7), the clock apart.

        ADR-0356 §4:3: every capability planning may call, on every round of every
        activation, in one fixed order, from the hub's start until it stops: the
        registry's, the person model's calls where they are attached, the Task
        Scheduler's and the calls on running work where each is wired, and ``text``
        last. No round, activation, person or condition adds one or removes one; a call
        whose condition does not hold comes back refused (:meth:`_not_here`).

        Planning's input carries ``now``, so the clock's call would only spend a round
        on what it has (#2942): it is left out of the offer, and stays registered.
        """
        names = (
            await self._tools.capabilities() if self._capabilities is None else self._capabilities
        )
        if self._person_calls is not None:
            names = (*names, *sorted(PERSON_MODEL_CAPABILITIES - set(names)))
        if self._task_calls is not None:
            names = (*names, *sorted(TASK_SCHEDULER_CAPABILITIES - set(names)))
        if self._matters is not None:
            names = (*names, *sorted(MATTER_CAPABILITIES - set(names)))
        declared = await self._tools.offered(
            [name for name in names if name not in _NOT_OFFERED and name != TEXT_CAPABILITY]
        )
        return (*declared, TEXT_CALL)

    @staticmethod
    def _not_here(  # noqa: PLR0913 — each condition ADR-0356 §4:5 names
        offered: Sequence[ToolDefinition],
        *,
        person: bool,
        scheduling: bool,
        running: frozenset[str],
        standing: bool,
        waiting: bool,
    ) -> dict[str, str]:
        """Why each capability offered cannot run in this activation, on this round.

        ADR-0356 §4:4-§4:6, each the condition that decided before whether it was
        offered: the person model's calls in an activation that is no person's (ADR-0338
        §2:3); the Task Scheduler's in one ADR-0350 §3:4 does not admit; the calls on
        running work where its author is not established, the stop where its input
        carries no user's authority (ADR-0349 §4:6), and the answer where no offer is
        open (§4:6); and, on a waiting round, every call but a message and the stop
        (§7:26), whose activation the judge checks.
        """
        names = {str(one.capability) for one in offered}
        why: dict[str, str] = {}
        if not person:
            why |= dict.fromkeys(sorted(PERSON_MODEL_CAPABILITIES & names), _NO_PERSON)
        if not scheduling:
            why |= dict.fromkeys(sorted(TASK_SCHEDULER_CAPABILITIES & names), _NO_SPAWN)
        for name in sorted((MATTER_CAPABILITIES & names) - running):
            if not standing:
                why[name] = _NO_RUNNING_VIEW
            elif name == STOP_ACTIVATION_CAPABILITY:
                why[name] = _NO_AUTHORITY
            else:
                why[name] = _NO_OFFER
        if waiting:
            for name in sorted(names - {STOP_ACTIVATION_CAPABILITY, TEXT_CAPABILITY}):
                why.setdefault(name, WAITING_ROUND)
        return why

    async def _entries(self, working: PhaseWorking) -> None:
        """Append each call's entry whose outcome is now known (ADR-0356 §8:6).

        Recorded as a round is (ADR-0307 §2:4): added to the activation's record and the
        episode extended, a failure a capture failure that holds nothing back. A pass no
        channel admitted has no episode, and records none.
        """
        state = active_state()
        if state is None:
            return
        entries = working.call_entries(self._now(), showed=self._showed_chars)
        if entries:
            state.recorded_calls(entries)
            await _extended(state, self.append)

    async def _worded(self, working: PhaseWorking) -> tuple[CallOutcome, ...]:
        """What came of every round's calls, a pin's or an unpin's memory worded.

        ADR-0338 §8:6: the question about a ``pin`` or an ``unpin`` call that needs the
        user shows the memory's wording as the memory store holds it, read live here for
        the round that may ask, in place of its label. Only a memory the live read
        returns current is shown so (ADR-0342 §5:1): one that is gone, retired since it
        was shown, or rests on outside content, which no question shows (ADR-0307 §9:2),
        or one that cannot be read, leaves the call handed on with no request, so it
        cannot be asked about. A wording read for a question is among what the
        activation obtained (ADR-0309 §5:10).
        """
        outcomes = working.outcomes()
        if self._person_calls is None:
            return outcomes
        named: dict[int, tuple[str, str]] = {}
        for index, one in enumerate(outcomes):
            request = one.request
            if one.kind is not CallOutcomeKind.NEEDS_YOU or request is None:
                continue
            argument = worded_argument(str(request.tool.capability))
            memory_id = None if argument is None else request.parameters.get(argument)
            if argument is not None and isinstance(memory_id, str):
                named[index] = (argument, memory_id)
        if not named:
            return outcomes
        held: Mapping[str, MemoryRecord]
        try:
            held = await self._memory.get_many(sorted({one for _, one in named.values()}))
        except MemoryStoreError:
            _log.warning("planning_wording_unread", stage="planning", reason="memory_fault")
            held = {}
        worded = list(outcomes)
        for index, (argument, memory_id) in named.items():
            record = held.get(memory_id)
            if (
                not isinstance(record, Memory)
                or record.status is not MemoryStatus.CURRENT
                or record.rests_on_outside_content
            ):
                worded[index] = replace(outcomes[index], request=None, deliberate_repeat=False)
                continue
            working.supplied.obtained((record,))
            worded[index] = replace(outcomes[index], worded=((argument, record.content),))
        return tuple(worded)

    async def _notes_checked(self, planned: PlannedRound, working: PhaseWorking) -> PlannedRound:
        """Refuse whole, before authorizing, a move or a split naming a note not held.

        ADR-0307 §5:3-§5:4, §6:5: checked against the stories as they stand now, after
        planning's own check mapped the call's labels to ids. A refused call runs
        nothing, and brings a round as every refused call does; the reason names the
        note by the label planning was shown it under. The store checks again inside
        its transaction, so a note moved away after this still refuses the call.
        """
        if self._story_calls is None or not planned.calls:
            return planned
        notes = {
            one.id: one.label
            for one in (*working.labels.labels, *planned.labels)
            if one.kind is LabelKind.NOTE
        }
        kept = []
        refused = []
        for one in planned.calls:
            reason = await self._story_calls.refusal(
                one.call, owner_records=working.owner_records, labels=notes
            )
            if reason is None:
                kept.append(one)
            else:
                _log.info("planning_call_refused", stage="planning", reason="not_held")
                refused.append(RefusedCall(one.call, reason))
        if not refused:
            return planned
        order = {call.call_id: index for index, call in enumerate(planned.round.calls)}
        return replace(
            planned,
            calls=tuple(kept),
            refused=tuple(
                sorted(
                    (*planned.refused, *refused),
                    key=lambda one: order.get(one.call.call_id, len(order)),
                )
            ),
        )

    async def _found(self, given: PhasePass, working: PhaseWorking) -> Fetched:
        """Both recall runs' kept records, fetched once, before the first round (§3).

        Planning needs the records recall chose, so it fetches their ids itself in one
        read: each record's current version, the audience predicate applied again, and
        an open episode, an id with no record and one the predicate now refuses left
        out (ADR-0282 §2:4-§2:8). What was fetched and what came back missing is held
        in the working set, and every later round is shown the same records.
        """
        if working.found is None:
            ids = tuple(
                dict.fromkeys(
                    item.id
                    for decision in (given.recalled, working.second_recall)
                    if decision is not None
                    for item in decision.result.items
                )
            )
            working.found = await fetch_held(
                self._memory, episode_ids=None, recalled_ids=ids, audience=given.supply
            )
            working.supplied.obtained(working.found.recalled)
            _log.info(
                "stage_fetch",
                stage="planning",
                fetched=len(working.found.fetched),
                missing=len(working.found.missing),
            )
        return working.found

    async def _searched(self, given: PhasePass, working: PhaseWorking) -> None:
        """Each memory search's records for planning, fetched by id once (ADR-0307 §6:6).

        The ids a search kept whose source is not outside are fetched in one read before
        the next round: each record's current version, the audience predicate applied
        again, and an id with no record or one the predicate now refuses left out
        (ADR-0282 §2:4-§2:8). What came back is held under the search's result, and
        every later round is shown the same records; what was fetched and what came
        back missing is held beside it.
        """
        unfetched = working.unfetched_searches()
        if not unfetched:
            return
        ids = tuple(dict.fromkeys(one for kept in unfetched.values() for one in kept))
        fetched = await fetch_held(
            self._memory, episode_ids=None, recalled_ids=ids, audience=given.supply
        )
        working.search_fetches.append(fetched)
        working.supplied.obtained(fetched.recalled)
        _log.info(
            "stage_fetch",
            stage="planning",
            fetched=len(fetched.fetched),
            missing=len(fetched.missing),
        )
        by_id = {one.id: one for one in fetched.recalled if isinstance(one, Memory)}
        for result_id, kept in unfetched.items():
            working.searched[result_id] = tuple(by_id[one] for one in kept if one in by_id)

    async def _stories(self, given: PhasePass, working: PhaseWorking) -> PlanningStories | None:
        """What planning is shown of stories this round, read as the stores stand now.

        Read before every round, so a later round is shown the stories as they stand
        then, under the pass's audience (ADR-0307 §6:1, §6:4).
        """
        if self._story_reads is None:
            return None
        read = await self._story_reads.read(
            working.activation_id,
            understanding=given.understanding,
            audience=given.supply,
            owner_records=working.owner_records,
        )
        # Held as they are read, whatever becomes of the round (ADR-0309 §5:10).
        working.supplied.obtained(_story_records(read))
        return read

    async def _recall_again(self, given: PhasePass, recall: RecallStage | None) -> StageResult:
        """Recall's second run, on what understanding found (ADR-0308 §2).

        Its cues are the latest understanding's meaning and the gap of each of its unclear
        points (§2:2, ADR-0353 §14:3), and it passes over what the windows hold and every
        record the first run kept (§2:3). The decision is held in the working set and
        carried on the activation's state before the stage returns, so the row that made
        it due does not answer again; understanding never reads it (§2:8). A ``failed`` or
        ``timed_out`` decision is returned ``tolerated`` with its error, and planning
        goes on without it while the pass's deadline holds (§2:7). Past the deadline,
        whatever the run returned is the expiry, as for the first run.

        Raises:
            RuntimeError: If no recall stage is wired, or there is no recorded
                understanding or no window decision, which the rows make impossible.
        """
        working = _working(given)
        understanding = given.understanding
        windows = given.windows
        if recall is None or understanding is None or windows is None:
            msg = "recall's second run follows a recorded understanding (ADR-0308 §2:1)"
            raise RuntimeError(msg)
        first = given.recalled
        kept = () if first is None else tuple(item.id for item in first.result.items)
        recalled = await recall.recall_again(
            understanding.meaning,
            tuple(one.gap for one in understanding.unclear),
            audience=given.supply,
            deadline=given.deadline,
            passed_over=windows.shared | frozenset(windows.episode_ids or ()) | frozenset(kept),
            cap=self._recall_cap,
        )
        late = _expired(_RECALL_EXPIRED)(given)
        if late is not None:
            recalled = Recalled(
                ActivationRecall(outcome=RecallOutcome.TIMED_OUT, cues=recalled.result.cues),
                error=late,
            )
        # ADR-0308 §4:4: the outside memory records either run kept, which recall's
        # digest reads, are held with the second decision.
        working.recall_outside = _kept_outside(first, recalled)
        working.second_recall = recalled
        if (state := active_state()) is not None:
            state.recall_second_run = recalled.result
        outcome = _RECALL_STAGE_OUTCOMES[recalled.result.outcome]
        if outcome is StageOutcome.DONE:
            return StageResult(StageOutcome.DONE)
        return StageResult(outcome, recalled.error, tolerated=True)

    async def _digest_recall(self, given: PhasePass) -> StageResult:
        """Recall's digest: its outside memory records, read against the meaning (§4:4).

        The digest fetches the held ids with planning's read (ADR-0282 §2:4-§2:8), holds
        what it fetched and what came back missing, and reads every record still resting
        on outside content, both runs' together, against the latest understanding's
        meaning. The decision is held before the stage returns, whatever came of it, so
        ``recall_undigested`` does not answer again. A failed digest is recorded with no
        evidence, planning is told it could not read recall's outside records (§4:13),
        and the stage returns ``failed``, or ``timed_out`` where its deadline passed,
        ``tolerated`` (§4:12). Where no record came back to read, nothing is recorded
        and planning is shown nothing of them, as for any id with no record (§2:6).

        Raises:
            RuntimeError: If there is no recorded understanding, which the rows make
                impossible.
        """
        working = _working(given)
        understanding = given.understanding
        if understanding is None:
            msg = "recall's digest answers a recorded understanding's meaning (ADR-0308 §4:4)"
            raise RuntimeError(msg)
        ids = working.recall_outside

        async def fetch() -> tuple[Memory, ...]:
            fetched = await fetch_held(
                self._memory, episode_ids=None, recalled_ids=ids, audience=given.supply
            )
            working.recall_digest_fetch = fetched
            working.supplied.obtained(fetched.recalled)
            _log.info(
                "stage_fetch",
                stage="digesting",
                fetched=len(fetched.fetched),
                missing=len(fetched.missing),
            )
            # A record whose current version no longer rests on outside content is
            # shown to planning by its fact (§3:3), so it is not read here as well.
            return tuple(
                one
                for one in fetched.recalled
                if isinstance(one, Memory) and one.rests_on_outside_content
            )

        try:
            digested = await self._digesting.digest_recall(
                fetch,
                question=understanding.meaning,
                labels=working.labels,
                deadline=self._now() + self._left(given, self._recall_digest_wait),
            )
        finally:
            working.recall_digest_decided = True
        if digested is None:
            return StageResult(StageOutcome.DONE)
        working.digests.append(digested.digest)
        working.evidence.append(digested_evidence(digested, working.labels.labels))
        if digested.failure is None:
            return StageResult(StageOutcome.DONE)
        if digested.failure == "deadline":
            return StageResult(
                StageOutcome.TIMED_OUT, ModelTimeoutError(_RECALL_DIGEST_FAILED), tolerated=True
            )
        return StageResult(
            StageOutcome.FAILED, _RecallDigestFailedError(_RECALL_DIGEST_FAILED), tolerated=True
        )

    async def _authorize(self, given: PhasePass) -> None:
        """Check the latest round's calls by rule, and its message by its place."""
        working = _working(given)
        latest = working.latest
        planned = latest.planned
        calls = [
            CallToAuthorize(
                call=await self._tools.filled(one.call),
                deliberate_repeat=one.deliberate_repeat,
                approved_part=one.approved_part,
            )
            for one in planned.calls
            if one.call.name != TEXT_CAPABILITY
        ]
        texts = [one.call for one in planned.calls if one.call.name == TEXT_CAPABILITY]
        scheduling = working.scheduling
        places: tuple[str, ...] | None = None
        gone: tuple[str, ...] = ()
        if scheduling is not None and scheduling.speaks_by_label:
            # ADR-0350 §6:7: the place its label resolved to, checked against the list.
            places = tuple(scheduling.targets)
            named = planned.round.place
            place = None if named is None else place_of(named)
            message = None if planned.message is None else RoundMessage(planned.message, place)
            # ADR-0357 §2:4: a ``text`` call goes into the place on the list it names or
            # the tool resolves.
            call_messages = self._text_messages(working, latest, texts)
            if any(
                one.place in scheduling.targets
                for one in (*call_messages, *([] if message is None else [message]))
            ):
                # §5:8-§5:9: a place gone since the list was built is refused by rule,
                # so the list is read again as it stands now (#3448), inside the
                # phase's deadline as the check itself is.
                try:
                    async with asyncio.timeout_at(given.deadline):
                        gone = await self._gone_since(scheduling)
                except TimeoutError:
                    raise ModelTimeoutError(_AUTHORIZING_EXPIRED) from None
        else:
            target = self._target(working)
            place = None if target is None else target.place
            message = (
                None
                if planned.message is None or place is None
                else RoundMessage(planned.message, place)
            )
            # ADR-0357 §2:4: into the place it names, or the input's where it names none.
            call_messages = self._text_messages(working, latest, texts)
        rounds = working.planning_rounds()
        given_round = RoundToAuthorize(
            activation_id=working.activation_id,
            round=planned.round,
            working=WorkingRecord(
                rounds=rounds[:-1],
                labels=working.labels.labels,
                digests=tuple(working.digests),
                fetched_outside=working.fetched_outside,
                fetched_outside_from=tuple(working.fetched_outside_from),
                notes=tuple(working.notes.values()),
            ),
            calls=tuple(calls),
            input_place=None if places is not None else place,
            message=message,
            call_messages=call_messages,
            yes=working.yes(given.understanding),
            places=places,
            gone=gone,
        )
        try:
            async with asyncio.timeout_at(given.deadline):
                decided = await self._authorizing.authorize(given_round)
        except TimeoutError:
            raise ModelTimeoutError(_AUTHORIZING_EXPIRED) from None
        latest.authorization = decided
        held = working.labels.labels
        for one in decided.call_messages:
            if not one.allowed and one.call_id is not None:
                # ADR-0357 §2:5: a place the message place check does not allow comes back
                # with the places it may use.
                latest.sent[one.call_id] = _Sent(
                    CallOutcomeKind.REFUSED,
                    reason=f"{one.reason or _NOT_ALLOWED_THERE}; {self._may_use(working, held)}",
                )
        looking = {one.call.call_id: one.looking_for for one in planned.calls if one.looking_for}
        latest.looking_for = {
            verdict.decision_id: looking[verdict.call_id]
            for verdict in decided.verdicts
            if verdict.verdict is Verdict.ALLOWED
            and verdict.decision_id is not None
            and verdict.call_id in looking
        }

    def _text_messages(
        self, working: PhaseWorking, latest: _Round, texts: Sequence[ProposedCall]
    ) -> tuple[RoundMessage, ...]:
        """Each ``text`` call as the message it is, with the place it names or resolves.

        ADR-0357 §2:2-§2:4, §6:1: its arguments checked, who it is for found, and where it
        goes resolved from its ``via`` or, where it names none, chosen as §2:4 says
        (:meth:`_text_place`). One that cannot be carried out runs nothing: it comes back
        with why and what it may name instead, and is never checked or written.
        """
        messages: list[RoundMessage] = []
        named = self._named()
        labels = working.labels.labels
        for call in texts:
            checked = text_arguments(call.arguments)
            if isinstance(checked, str):
                latest.sent[call.call_id] = _Sent(CallOutcomeKind.REFUSED, reason=checked)
                continue
            nobody = who_it_is_for(checked.to, named=named)
            if nobody is not None:
                latest.sent[call.call_id] = _Sent(CallOutcomeKind.REFUSED, reason=nobody)
                continue
            place = self._text_place(working, checked, labels)
            if isinstance(place, _Nowhere):
                latest.sent[call.call_id] = _Sent(CallOutcomeKind.REFUSED, reason=place.reason)
                continue
            messages.append(RoundMessage(checked.words, place, call.call_id))
        return tuple(messages)

    @staticmethod
    def _named() -> tuple[str, ...]:
        """The names the user's profile gives them, as planning is shown them (§2:3)."""
        state = active_state()
        block = None if state is None else state.person_block
        if block is None:
            return ()
        values = (block.profile.value(one) for one in (ProfileField.NAME, ProfileField.ADDRESS))
        return tuple(one for one in values if isinstance(one, str) and one.strip())

    def _text_place(
        self, working: PhaseWorking, checked: TextArguments, labels: Sequence[PlanningLabel]
    ) -> str | _Nowhere:
        """Where a ``text`` call goes, or why it can go nowhere (ADR-0357 §2:4, §6:2).

        ``via`` names a place by its ``L`` label, which names what it named when planning
        was shown it, or a platform by name (:meth:`_platform_place`); left out, the tool
        chooses (:meth:`_chosen_place`). Whether the place may take the message is the
        message place check's, after this (ADR-0306 §4:1).
        """
        scheduling = working.scheduling
        listed = (
            scheduling.places if scheduling is not None and scheduling.speaks_by_label else None
        )
        via = checked.via
        if via is None:
            return self._chosen_place(working, listed, labels)
        if PLACE_LABEL.fullmatch(via):
            place = next(
                (one.id for one in labels if one.label == via and one.kind is LabelKind.PLACE),
                None,
            )
            if place is None:
                return self._nowhere(working, labels, f"{via!r} names no place you were shown")
            return place
        return self._platform_place(working, via, listed, labels)

    def _chosen_place(
        self,
        working: PhaseWorking,
        listed: Sequence[ListedPlace] | None,
        labels: Sequence[PlanningLabel],
    ) -> str | _Nowhere:
        """Where a ``text`` call naming no place goes (ADR-0357 §2:4).

        The place the input came from; or, for an activation the Task Scheduler started,
        the one place its task suggests, or the line's chat where it suggests none. Where
        no such place is on the list, or the task suggests more than one, it goes nowhere.
        """
        if listed is None:
            target = self._target(working)
            if target is None:
                return self._nowhere(working, labels, _NO_PLACE_HERE)
            return target.place
        suggested = [one for one in listed if one.suggested]
        if len(suggested) > 1:
            return self._nowhere(working, labels, _SUGGESTS_SEVERAL)
        if suggested:
            return suggested[0].place
        lines = [one for one in listed if one.channel.channel_type == _LINE_TYPE]
        if len(lines) == 1:
            return lines[0].place
        return self._nowhere(working, labels, _SUGGESTS_NONE)

    def _platform_place(
        self,
        working: PhaseWorking,
        via: str,
        listed: Sequence[ListedPlace] | None,
        labels: Sequence[PlanningLabel],
    ) -> str | _Nowhere:
        """Where a ``text`` call naming a platform goes (ADR-0357 §2:4).

        The place the input came from, where it is on that platform; or, for an
        activation the Task Scheduler started, the one place on its list on that platform,
        or its task's one suggestion among several there.
        """
        channel_type = platform_type(via)
        if channel_type is None:
            quoted = repr(via[:_QUOTED_VIA_CHARS])
            return self._nowhere(
                working, labels, f"{quoted} names no place by its L label and no platform"
            )
        platform = platform_name(channel_type)
        if listed is None:
            target = self._target(working)
            if target is not None and target.channel.channel_type == channel_type:
                return target.place
            return self._nowhere(
                working, labels, f"no place this message may go into is on {platform}"
            )
        on = [one for one in listed if one.channel.channel_type == channel_type]
        if not on:
            return self._nowhere(working, labels, f"no place on your list is on {platform}")
        suggested = [one for one in on if one.suggested]
        if len(on) == 1 or len(suggested) == 1:
            return (on if len(on) == 1 else suggested)[0].place
        return self._nowhere(working, labels, f"more than one place on your list is on {platform}")

    def _nowhere(
        self, working: PhaseWorking, labels: Sequence[PlanningLabel], why: str
    ) -> _Nowhere:
        """A ``text`` call that can go nowhere: why, and the places it may name (§6:2)."""
        return _Nowhere(f"{why}; {self._may_use(working, labels)}")

    def _may_use(self, working: PhaseWorking, labels: Sequence[PlanningLabel]) -> str:
        """The places a ``text`` call may name, as its coming back says them (§2:4-§2:5).

        For an activation the Task Scheduler started, each place on its list, by its ``L``
        label and its platform; for every other, the place its input came from alone,
        with its platform and its label where it has one, since a message goes into no
        other (ADR-0306 §4:1, ADR-0356 §7:10).
        """
        held = {one.id: one.label for one in labels if one.kind is LabelKind.PLACE}
        scheduling = working.scheduling
        if scheduling is not None and scheduling.speaks_by_label:
            named = [
                f"{held.get(one.place, one.place)} ({platform_name(one.channel.channel_type)})"
                for one in scheduling.places
            ]
            if not named:
                return "your place list is empty, so a message goes nowhere"
            return "the places it may name: " + ", ".join(named)
        target = self._target(working)
        if target is None:
            return "this activation can message no one: its input came from no place that takes one"
        label = held.get(target.place)
        where = platform_name(target.channel.channel_type) + ("" if label is None else f", {label}")
        return f"it may go only into the place your input came from ({where}): leave via out"

    @staticmethod
    async def _gone_since(scheduling: Scheduling) -> tuple[str, ...]:
        """The places on the round's list that are gone as the list stands now (§5:8).

        The list is built again, as it is at every round, and left as the round showed it:
        only the check reads the new one.
        """
        now_listed, _ = await scheduling.build()
        held = {one.place for one in now_listed}
        return tuple(one for one in scheduling.targets if one not in held)

    async def _act(self, given: PhasePass) -> None:
        """Run the latest round's allowed calls, and write its message beside them.

        The step is begun here or by digesting, whichever is first, and is told once
        acting has ended, however it ended, so digesting stops waiting for results.
        """
        working = _working(given)
        latest = working.latest
        decided = latest.authorization
        if decided is None:  # pragma: no cover — `round_authorized` answers only once it is
            msg = "acting runs a round authorizing has decided (ADR-0309 §3)"
            raise RuntimeError(msg)
        step = working.step(self._now(), self._wait(given))
        # ADR-0352 §4:1: a round that answers an offer dispatches its answers first and
        # alone, so the wait and the commitment step below are made for them.
        answering = _answering(latest, decided)
        first = decided if answering is None else answering.first
        try:
            state = active_state()
            if state is not None and _commits(latest, first):
                # ADR-0349 §7:12-§7:13: before anything of the round that is not a pure
                # read is dispatched, wait for each newer input that could absorb this
                # activation or offer to it, inside the pass's deadline; a wait that
                # reaches it dispatches nothing, and acting fails with its classified
                # expiry (ADR-0280 §5:1).
                if self._matters is not None and not await self._matters.before_act(
                    state, given.deadline
                ):
                    raise ModelTimeoutError(_ACTING_EXPIRED)
                if given.deadline <= asyncio.get_running_loop().time():
                    raise ModelTimeoutError(_ACTING_EXPIRED)
                # §7:14: the commitment step, with no await before the dispatch.
                withheld = _commitment(state, latest, decided)
                if withheld is not None:
                    latest.acted = withheld
                    _unsent(latest, _HELD_BACK if withheld.set_aside else _STOPPED_UNSENT)
                    return
            if answering is None:
                ran, wrote = await asyncio.gather(
                    self._calls(given, working, decided),
                    self._message(working, latest),
                    return_exceptions=True,
                )
            else:
                ran, wrote = await self._answered_first(given, working, latest, answering)
        finally:
            step.held.put_nowait(None)
        await self._held_acted(working, latest, ran)
        # ADR-0356 §8:6: what came of each call is known now, before any next round.
        await self._entries(working)
        for answer in (ran, wrote):
            if isinstance(answer, BaseException):
                raise answer

    async def _held_acted(
        self, working: PhaseWorking, latest: _Round, ran: ActedRound | BaseException
    ) -> None:
        """Hold what acting made of the round, or, where it raised, what its records hold."""
        if isinstance(ran, ActedRound):
            # Kept even where the message beside it failed: what acting ran happened.
            latest.acted = ran
            # The assertions a remember that needs you would replace were read from the
            # store, and planning is shown them: obtained, so they place what follows
            # (ADR-0309 §5:10, ADR-0321 §5:5).
            working.supplied.obtained(record for one in ran.calls for record in one.replaces)
        elif isinstance(ran, Exception):
            # ADR-0356 §8:6: acting raised, so it handed back no round; each call it
            # finished was handed back as it finished (`_Round.handed`), and one claimed
            # under an effect record still has its outcome there (ADR-0306 §6).
            await self._finished_effects(working, latest)

    async def _finished_effects(self, working: PhaseWorking, latest: _Round) -> None:
        """Hold the outcome each of the round's effect records holds, where acting raised.

        ADR-0356 §8:6, ADR-0306 §6: a call acting finished before a sibling raised has its
        outcome on its effect record, which planning's entry for it is then made from. A
        plan store that cannot be read leaves them unknown, as they are.
        """
        try:
            recorded = await self._plans.activation_effects([working.activation_id])
        except Exception as exc:  # the round's own error is the one the stage ends on
            if is_defect(exc):
                log_defect(
                    "phase_effects_unread", exc, stage="acting", activation_id=working.activation_id
                )
            else:
                _log.warning("phase_effects_unread", stage="acting", reason="store_failed")
            return
        round_id = latest.planned.round.id
        latest.finished = {
            one.id: (one.outcome, one.reason)
            for one in recorded
            if one.round == round_id and one.is_call and one.outcome is not None
        }

    async def _answered_first(
        self,
        given: PhasePass,
        working: PhaseWorking,
        latest: _Round,
        answering: _Answering,
    ) -> tuple[ActedRound | BaseException, BaseException | None]:
        """Run a round's answers first and alone, then the rest only where they settled.

        ADR-0352 §4:1-§4:3: each answer call is awaited to its end before any other call
        of the round that is not a pure read, or its message, is dispatched. Where every
        answer came to what it asked, a take to a take or a decline to the decline, the
        rest of the round is dispatched as any round's is. Otherwise, a take refused at
        ``held_input_limit``, an offer withdrawn, an answer refused whole or one
        authorizing did not allow, only the round's pure reads run: every other call is
        not done with the reason, the message is not written, and planning runs a round
        again shown what each answer came to (ADR-0315 §2:1), which counts toward the
        round limit. Where the activation was stopped while its answers ran, nothing more
        of the round is dispatched, as the commitment step dispatches nothing of a
        stopped one's round (ADR-0349 §7:14).

        Returns:
            What acting made of the round, and what the message's write raised, each an
            exception where it raised, as the gather of an ordinary round returns them.
        """
        caller = self._caller(given, working)
        answered = await self._calls(given, working, answering.first, caller=caller)
        state = active_state()
        if state is not None and state.stopped:
            # ADR-0295 §2:1, ADR-0349 §7:14: a stop that landed while the answers ran
            # starts nothing new, so nothing more of the round is dispatched, and the pass
            # ends on the stop; what the answers did happened.
            _log.info("phase_round_not_acted", stage="acting", reason="stopped")
            _unsent(latest, _STOPPED_UNSENT)
            return answered, None
        settled = not answering.refused and all(
            one.call.decision.id in (() if caller is None else caller.as_asked)
            for one in answering.first.allowed
        )
        decided = answering.decided
        if settled:
            ran, wrote = await asyncio.gather(
                self._calls(given, working, replace(decided, allowed=answering.rest)),
                self._message(working, latest),
                return_exceptions=True,
            )
            if isinstance(ran, ActedRound):
                ran = _in_round_order(decided, answered, ran)
            return ran, wrote
        _log.info("phase_round_held_back", stage="acting", reason="offer_not_taken")
        latest.not_taken = True
        because = _not_taken(answering, caller)
        _unsent(latest, because)
        reads = tuple(one for one in answering.rest if is_pure_read(one.call.request.tool))
        read = (
            await self._calls(
                given, working, replace(decided, allowed=reads, message=None, call_messages=())
            )
            if reads
            else ActedRound(round_id=decided.round_id)
        )
        ran_ids = {one.call.decision.id for one in reads}
        held = ActedRound(
            round_id=decided.round_id,
            calls=tuple(
                ActedCall(call=one, outcome=ActedOutcome.NOT_DONE, reason=because)
                for one in authorized_round(
                    replace(
                        decided,
                        allowed=tuple(
                            one for one in answering.rest if one.call.decision.id not in ran_ids
                        ),
                    )
                ).calls
            ),
        )
        return _in_round_order(decided, answered, read, held), None

    async def _calls(
        self,
        given: PhasePass,
        working: PhaseWorking,
        decided: RoundAuthorization,
        *,
        caller: MatterCaller | None = None,
    ) -> ActedRound:
        """Run the round's allowed calls; its tidy-ups run on their own, unawaited.

        **The look-ups** (ADR-0307 §6:6) run inside a scope opened around acting, so
        they read under the pass's audience and its owner-only placement. A story's full
        view a story read read, and what an episode look-up read, is held under its call's
        result as the scope closes, from what acting handed back where it raised.

        **The tidy-up exception** (ADR-0307 §7:2, §8:1). A new round waits for every
        call of the last one but a tidy-up, and neither it nor the activation's end
        waits for one. So the round's allowed tidy-ups are split off and handed to
        acting in a task of their own, which this does not await: acting runs them
        through its own-records seam and awaits each to its end (ADR-0306 §3:3), after
        the activation has ended if need be. What came of one is written to the story's
        version log, never to the episode (§7:1), so no acting decision of it is held.

        **Each other call's outcome is held on the round as acting hands it back**, so
        a call that finished keeps what came of it on its entry where a sibling raised
        or the round was cancelled (ADR-0356 §8:6).
        """
        tidies = tuple(
            one
            for one in decided.allowed
            if str(one.call.request.tool.capability) == TIDY_STORY_CAPABILITY
        )
        if tidies:
            self._start_tidies(working, decided, tidies)
            # ADR-0356 §8:6: a tidy-up that starts has its entry appended when it starts.
            await self._entries(working)
        started = {one.call.decision.id for one in tidies}
        rest = tuple(one for one in decided.allowed if one.call.decision.id not in started)
        if not rest:
            return ActedRound(round_id=decided.round_id)
        authorized = authorized_round(replace(decided, allowed=rest))
        latest = working.latest
        acted_one = latest.acted_one
        if caller is None:
            caller = self._caller(given, working)
        with (
            spawning(self._spawner(given, working)),
            calling(caller),
            self._tools.holding(working.supplied, working.attributions),
        ):
            if self._look_ups is None:
                acted = await self._acting.act(authorized, held=working.held, on_acted=acted_one)
                self._peers(working, acted, caller)
                return acted
            with self._look_ups.scope(
                audience=given.supply, owner_records=working.owner_records, older=working.older
            ) as scope:
                ran: ActedRound | None = None
                try:
                    ran = await self._acting.act(authorized, held=working.held, on_acted=acted_one)
                finally:
                    # Every view a story read read, and every record an episode look-up
                    # read, was obtained, whatever became of the round's other calls
                    # (ADR-0309 §5:10).
                    working.supplied.obtained(
                        _story_records(PlanningStories(stories=tuple(scope.views.values())))
                    )
                    working.supplied.obtained(
                        tuple(record for found in scope.found.values() for record in _read(found))
                    )
                    # ADR-0356 §8:6, ADR-0358 §11:2: where acting raised or was cancelled
                    # before handing back the round, each read a call it handed back as
                    # done read is held under its result all the same, so its entry keeps
                    # what it showed.
                    calls = tuple(latest.handed.values()) if ran is None else ran.calls
                    self._pages(working, calls, scope.views)
                    self._looked(working, calls, scope.found)
        self._peers(working, ran, caller)
        return ran

    def _caller(self, given: PhasePass, working: PhaseWorking) -> MatterCaller | None:
        """Who calls on running work in this round, read from the working set (§4:6)."""
        state = active_state()
        if self._matters is None or state is None:
            return None
        latest = working.latest
        return MatterCaller(
            state=state,
            users_authority=working.users_authority,
            owner_records=working.owner_records,
            running=working.running_shown(),
            waiting=frozenset(state.waits_on) if latest.waiting else None,
            supply=given.supply,
        )

    @staticmethod
    def _peers(working: PhaseWorking, acted: ActedRound, caller: MatterCaller | None) -> None:
        """Hold what each call on running work came back with, by its outcome (§4:11).

        A done call's under its result's id, and a refused stop's naming its absorber
        under its decision's id (§4:9).
        """
        if caller is None or not caller.shown:
            return
        for one in acted.calls:
            shown = caller.shown.get(one.call.call.decision.id)
            if shown is None:
                continue
            key = one.result_id if one.result_id is not None else one.call.call.decision.id
            working.peers[key] = shown

    @staticmethod
    def _spawner(given: PhasePass, working: PhaseWorking) -> Spawner | None:
        """Who calls the Task Scheduler in this round, read from the working set (§3:4)."""
        scheduling = working.scheduling
        if scheduling is None:
            return None
        state = active_state()
        standing = None if state is None else state.standing
        task = scheduling.task
        return Spawner(
            activation_id=working.activation_id,
            person=scheduling.person,
            users_authority=working.users_authority,
            set_in=scheduling.set_in,
            places=tuple(one.place for one in scheduling.places),
            carried=() if task is None else tuple(place_of(one) for one in task.places),
            read_outside_content=working.read_outside_content,
            supply=given.supply,
            sees_running=standing is not None and standing.author is not None,
        )

    @staticmethod
    def _pages(
        working: PhaseWorking, calls: Iterable[ActedCall], views: Mapping[str, PlanningStory]
    ) -> None:
        """Hold each story's full view a done story read read, under its call's result.

        A view resting on outside content, a marked summary or note, an episode resting
        on outside content or a marked moment, sets ``fetched_outside``, counted as the
        story views are (ADR-0300 §10:6, ADR-0306 §4:5) and named by what set it; every
        note it shows is held with its mark, which authorizing reads for its ``N`` label.
        """
        for one in calls:
            view = views.get(one.call.call.decision.id)
            if (
                view is None
                or one.outcome is not ActedOutcome.DONE
                or one.result_id is None
                or str(one.call.call.request.tool.capability) != READ_STORY_CAPABILITY
            ):
                continue
            working.pages[one.result_id] = view
            shown = PlanningStories(stories=(view,))
            working.notes.update((note.note_id, note) for note in _shown_notes(shown))
            working.fetched_resting_on_outside(_stories_outside(shown))

    @staticmethod
    def _looked(
        working: PhaseWorking, calls: Iterable[ActedCall], found: Mapping[str, EpisodeLookedUp]
    ) -> None:
        """Hold what each done episode look-up read, under its call's result (ADR-0358 §6).

        An outside episode, an episode with evidence or a marked note, and a marked
        summary shown set ``fetched_outside``, named by what set it, as the story views'
        do (§6:4, ADR-0306 §4:5).
        """
        for one in calls:
            looked = found.get(one.call.call.decision.id)
            if looked is None or one.outcome is not ActedOutcome.DONE or one.result_id is None:
                continue
            working.looked[one.result_id] = looked
            working.fetched_resting_on_outside(_looked_outside(looked))

    def _start_tidies(
        self,
        working: PhaseWorking,
        decided: RoundAuthorization,
        tidies: tuple[AllowedCall, ...],
    ) -> None:
        """Start the round's tidy-ups as work nobody waits on, unless shutdown has begun.

        A tidy-up not started loses nothing: what it would have taken in stays pending
        on the story for a later run (ADR-0300 §5).
        """
        if self._closing():
            _log.info("phase_tidy_up_not_started", stage="acting", reason="closing")
            return
        self._spawn(self._tidy(working, authorized_round(replace(decided, allowed=tidies))))

    async def _tidy(self, working: PhaseWorking, tidies: AuthorizedRound) -> None:
        """Run the tidy-ups through acting, logging rather than raising what escapes.

        Nobody awaits this coroutine, so an unexpected error is logged here by its class
        alone, never its message, which could carry a story's words (ADR-0275 §8).
        """
        try:
            await self._acting.act(tidies, held=working.held)
        except Exception as exc:
            _log.error("phase_tidy_up_crashed", stage="acting", error=type(exc).__name__)

    async def _message(self, working: PhaseWorking, latest: _Round) -> None:
        """Write the round's messages into their places, where each may go (§3:1).

        The round's own message, then each ``text`` call allowed, in the round's order
        (ADR-0356 §7:7-§7:8), each claimed and written as a message is: its words as the
        wording step renders them, and an asking call's exact lines after them (ADR-0357
        §4, §8:2).
        """
        decided = latest.authorization
        if decided is None:
            return
        text = latest.planned.message
        verdict = decided.message
        if (
            verdict is not None
            and verdict.allowed
            and verdict.effect_id is not None
            and text is not None
        ):
            # Whether it was recorded decides whether the activation's last message was
            # delivered (ADR-0317 §3:4).
            latest.written = await self._write(
                working,
                text,
                effect_id=verdict.effect_id,
                round_id=latest.planned.round.id,
                place=verdict.place,
            )
        texts = {one.call.call_id: one.call for one in latest.planned.calls}
        questions = latest.planned.questions
        for one in decided.call_messages:
            call = texts.get(one.call_id or "")
            if not one.allowed or one.effect_id is None or call is None:
                continue
            checked = text_arguments(call.arguments)
            if isinstance(checked, str):  # pragma: no cover — checked before authorizing
                continue
            # ADR-0357 §4, §8:2: the words as the wording step renders them, and after
            # them the exact lines of the question it asks, which are never reworded.
            words = with_question(
                reworded(checked.words, exact=checked.exact), questions.get(call.call_id)
            )
            try:
                latest.sent[call.call_id] = await self._sent(
                    working,
                    words,
                    effect_id=one.effect_id,
                    round_id=latest.planned.round.id,
                    place=one.place,
                )
            except _SendRaisedError as raised:
                # The writer raised: whether it wrote is not known, and the stage ends
                # on the writer's own error, as on the round's own message.
                latest.sent[call.call_id] = raised.sent
                cause = raised.__context__
                raise cause if cause is not None else raised from None

    async def _digest(self, given: PhasePass) -> None:
        """Digest each result acting holds as it is held, until acting has ended (§3:3)."""
        working = _working(given)
        latest = working.latest
        step = working.step(self._now(), self._wait(given))
        async with asyncio.TaskGroup() as group:
            while (held := await step.held.get()) is not None:
                question = latest.looking_for.get(held.decision_id)
                if question is None:
                    # No question to answer, so nothing can be read for planning: it
                    # is told it could not read the result (ADR-0308 §4:13).
                    _log.info("digest_failed", stage="digesting", reason="no_question")
                    working.evidence.append(
                        DigestedEvidence(result_id=held.result_id, answered=False)
                    )
                    continue
                group.create_task(
                    self._digested(working, held, question, step.deadline, given.supply)
                )

    async def _digested(
        self,
        working: PhaseWorking,
        held: HeldResult,
        question: str,
        deadline: datetime,
        audience: TurnSupply,
    ) -> None:
        """Digest one held result against ``question``, as it was held (ADR-0308 §6:1-§6:3).

        A result held as it arrived is read as it arrived. One held by the ids of its
        outside records, a memory search's, is fetched by id inside the digest's
        deadline, the audience predicate applied again (ADR-0282 §2:4-§2:8); where none
        comes back to read, nothing is recorded and planning is told it could not read
        the result.
        """
        records = held.records
        if records is None:
            digested: Digested | None = await self._digesting.digest_result(
                held,
                question=question,
                labels=working.labels,
                deadline=deadline,
                attribution=working.attribution(held),
            )
        else:

            async def fetch() -> tuple[Memory, ...]:
                fetched = await fetch_held(
                    self._memory, episode_ids=None, recalled_ids=records, audience=audience
                )
                working.search_fetches.append(fetched)
                working.supplied.obtained(fetched.recalled)
                _log.info(
                    "stage_fetch",
                    stage="digesting",
                    fetched=len(fetched.fetched),
                    missing=len(fetched.missing),
                )
                return tuple(one for one in fetched.recalled if isinstance(one, Memory))

            digested = await self._digesting.digest_records(
                fetch,
                result_id=held.result_id,
                question=question,
                labels=working.labels,
                deadline=deadline,
            )
        if digested is None:
            working.evidence.append(
                DigestedEvidence(result_id=held.result_id, answered=False, question=question)
            )
            return
        working.digests.append(digested.digest)
        working.evidence.append(digested_evidence(digested, working.labels.labels))

    # --- the yes path (ADR-0321) ---

    def shown_whole(
        self,
        working: PhaseWorking,
        planning_round: PlanningRound,
        questions: Mapping[str, str] | None = None,
        labels: Sequence[PlanningLabel] = (),
    ) -> PlanningRound:
        """``planning_round``, asking about nothing where its question would not be shown whole.

        The dispatcher's ruling on ADR-0321 §4:4's *shown*: a message cut to fit is not
        shown, since its exact lines come last (§2:5) and any cut takes them. The question
        is the round's asking ``text`` call, the one ``questions`` holds lines for
        (ADR-0357 §8:2), as it would be written: its words as reworded and the lines after
        them, into the place it names or resolves. So a round whose asking call would be
        cut, by the transcript's bound or the writer's, or could go nowhere, its person or
        place not found, records no asked call: by §2:2 nothing waits on the user that
        they were not clearly asked about, so no yes to that message approves anything,
        no proposal is held back as already asked, and the call may be asked about again
        whole. Where whether it fits cannot be told, it is taken not to, failing closed.
        ``labels`` are the round's own, which the working set does not hold yet.

        Returns:
            ``planning_round`` itself where it asks about nothing or its question would be
            shown whole; otherwise a copy that asks about nothing.
        """
        if not planning_round.asked:
            return planning_round
        lines = questions or {}
        asking = next((one for one in planning_round.calls if one.call_id in lines), None)
        target, text = None, ""
        if asking is not None:
            checked = text_arguments(asking.arguments)
            if (
                not isinstance(checked, str)
                and who_it_is_for(checked.to, named=self._named()) is None
            ):
                place = self._text_place(working, checked, (*working.labels.labels, *labels))
                if isinstance(place, str):
                    target = self._target(working, place)
                    if target is not None and target.place != place:
                        target = None  # it would not go where the place check allows
                    text = with_question(
                        reworded(checked.words, exact=checked.exact), lines[asking.call_id]
                    )
        whole = False
        if target is not None:
            try:
                whole = not self._fitted(target, text).cut_off
            except Exception as exc:  # whether it fits is not known: not shown whole
                if is_defect(exc):
                    log_defect(
                        "phase_question_unmeasured",
                        exc,
                        stage="planning",
                        activation_id=working.activation_id,
                    )
        if whole:
            return planning_round
        _log.info("phase_question_cut", stage="planning", asked=len(planning_round.asked))
        return planning_round.model_copy(update={"asked": ()})

    @staticmethod
    def _fitted(target: PlaceTarget, text: str) -> Fitted:
        """``text`` as the place would write it: within its bounds, its writer's to say.

        Raises:
            OversizedValueError: If the writer finds no non-blank prefix that fits.
        """
        return target.writer.fitted(text)

    def _target(self, working: PhaseWorking, place: str | None = None) -> PlaceTarget | None:
        """The place the activation's messages go into, and its writer, or ``None``.

        For an activation the Task Scheduler started, the place on its list ``place``
        names, or ``None`` where it names none on the list (ADR-0350 §6:7). Otherwise the
        working set's own target, as the Telegram line's chat; its conversation, through
        this path's chat writer; and ``None`` where the place takes no message, an
        event's (ADR-0307 §3:8).
        """
        scheduling = working.scheduling
        if scheduling is not None and scheduling.speaks_by_label:
            return None if place is None else scheduling.targets.get(place)
        if working.target is not None:
            return working.target
        if working.conversation_id is None:
            return None
        return PlaceTarget(
            channel=conversation_channel(working.conversation_id),
            writer=_ConversationWriter(self._writer, working.conversation_id),
        )

    async def _approved(
        self, given: PhasePass, working: PhaseWorking
    ) -> tuple[ApprovedAction, ...]:
        """The actions the input's yes approved, as planning is shown them (ADR-0321 §4:2).

        Gathered from every pointer understanding recorded, in its order (ADR-0322
        §3:4), each read from the records it leads to: the asking activation's message
        delivery record names the question's round, by the pointer's round or by its
        place and position, and the asking episode's round records the calls it asked
        about (§2:8). The parts approved are those the pointer names, or every part
        shown where it names none (§3:6), less those an effect record has already used
        (§4:9), so a second yes shows nothing to run.

        None where the input does not carry the user's authority (§3:3) or the place
        takes no message (§7:3); none from a pointer naming this activation's own
        question (§4:1) or resolving to nothing; and none from one whose records cannot
        be read. This shows and grants nothing that authorizing does not check again
        (§4:4).
        """
        # ADR-0353 §11:2-§11:3: understanding records no answer pointer until the
        # authority run, so none shows an approved action.
        del given
        pointers: tuple[AnsweredQuestion, ...] = ()
        if not pointers or not working.users_authority or self._target(working) is None:
            return ()
        if working.approvable is None or working.approvable[0] != pointers:
            # Each part once: no two pointers name one question (ADR-0322 §2:7), so none
            # is repeated. A part reached from two asking activations cannot be told
            # apart by its label, so neither is shown, failing closed (§3:3).
            gathered: dict[QuestionPart, ApprovedAction] = {}
            askers: dict[QuestionPart, set[str]] = {}
            for pointer in pointers:
                if pointer.activation_id == working.activation_id:
                    continue
                for action in await self._approvable(pointer, working):
                    gathered.setdefault(action.part, action)
                    askers.setdefault(action.part, set()).add(pointer.activation_id)
            working.approvable = (
                pointers,
                tuple(one for part, one in gathered.items() if len(askers[part]) == 1),
            )
        actions = working.approvable[1]
        if not actions:
            return ()
        try:
            spent = await self._plans.part_effects([one.part for one in actions])
        except Exception as exc:  # the store is down: nothing is shown as approved
            self._unread(exc, working)
            return ()
        used = {one.part for one in spent}
        return tuple(one for one in actions if one.part not in used)

    async def _approvable(
        self, pointer: AnsweredQuestion, working: PhaseWorking
    ) -> tuple[ApprovedAction, ...]:
        """The calls the pointer's question asked about and approves, as recorded."""
        try:
            effects = await self._plans.activation_effects([pointer.activation_id])
            round_id = _delivered_round(effects, pointer)
            if round_id is None:
                return ()
            record = await self._memory.get(episode_address(pointer.activation_id))
        except Exception as exc:  # a store is down: nothing is shown as approved
            self._unread(exc, working)
            return ()
        if not isinstance(record, EpisodicMemory) or record.processing_record is None:
            return ()
        asked = next(
            (one.asked for one in record.processing_record.rounds if one.id == round_id), ()
        )
        recorded = {one.part: one for one in asked}
        actions = tuple(
            ApprovedAction(part=QuestionPart(round=round_id, part=number), call=recorded[number])
            for number in (pointer.parts or sorted(recorded))
            if number in recorded
        )
        if actions:
            # What planning may be shown of it was obtained from the asking episode, so
            # the episode and what this activation remembers are placed by it too
            # (ADR-0309 §5:10, ADR-0217 §3:12).
            working.supplied.obtained((record,))
        return actions

    @staticmethod
    def _unread(exc: Exception, working: PhaseWorking) -> None:
        """Log a failed read of the yes's records, a defect as one (#2904)."""
        if is_defect(exc):
            log_defect(
                "phase_approved_unread", exc, stage="planning", activation_id=working.activation_id
            )
        else:
            _log.warning("phase_approved_unread", stage="planning", reason="store_failed")

    # --- the place ---

    async def _write(
        self,
        working: PhaseWorking,
        text: str,
        *,
        effect_id: str,
        round_id: str | None,
        place: str | None = None,
    ) -> bool:
        """Claim, write and finish one message into the input's place (ADR-0306 §5:3-§5:5).

        The place's writer says what came of it (:class:`Delivery`): done at a position,
        not done with why, or unknown. Whatever of it the place now holds is what the
        episode records the activation sent, a message cut short between parts
        included, whatever becomes of the record's finish (ADR-0284 §4:1).

        Returns:
            Whether the medium recorded it whole.
        """
        wrote = await self._written(
            working, text, effect_id=effect_id, round_id=round_id, place=place
        )
        return wrote is not None and wrote[0].outcome is ToolOutcome.SUCCEEDED

    async def _sent(
        self,
        working: PhaseWorking,
        words: str,
        *,
        effect_id: str,
        round_id: str,
        place: str | None,
    ) -> _Sent:
        """Write one ``text`` call's words, and say what came of it (ADR-0356 §7:8, §8:4).

        Claimed, written and finished as any message is (:meth:`_written`): its entry
        holds the words the place took, or tried to, where they went and how. A call
        whose write never reached the place sent nothing, and holds no delivery.
        """
        attempted: list[_Attempt] = []
        try:
            wrote = await self._written(
                working,
                words,
                effect_id=effect_id,
                round_id=round_id,
                place=place,
                attempted=attempted,
            )
        except Exception:
            # ADR-0356 §8:4: where the send was attempted, what it tried to send and where
            # are kept, its status unknown; the stage ends on the error, as on the round's
            # own message.
            raise _SendRaisedError(_raised_send(attempted)) from None
        if wrote is None:
            return _Sent(CallOutcomeKind.NOT_DONE, reason=_GONE)
        delivered, fitted, channel = wrote
        return _sent_of(delivered, fitted, channel)

    async def _written(  # noqa: PLR0913 — the message, its record, its place, and who is told it was tried
        self,
        working: PhaseWorking,
        text: str,
        *,
        effect_id: str,
        round_id: str | None,
        place: str | None = None,
        attempted: list[_Attempt] | None = None,
    ) -> tuple[Delivery, str, ChannelIdentity] | None:
        """Claim, write and finish one message, and say what came of it and where.

        ``attempted``, where given, is told the text and the place's channel just before
        the place's writer is reached, and what the writer said once it returns, so a
        caller whose write or whose record's finish raised knows what was tried and how
        it went.

        Returns:
            What the place's writer said, the text it was handed, and the place's
            channel; ``None`` where it went nowhere: no place, or a claim the stop
            refused.
        """
        target = self._target(working, place)
        if target is None:
            return None
        fitted = self._fitted(target, text)
        effect = ActivationEffect(
            id=effect_id,
            activation_id=working.activation_id,
            round=round_id,
            place=target.place,
            claimed_at=self._now(),
        )
        try:
            await self._plans.claim_activation_effect(effect, match=None)
        except ClaimStopped:
            _log.info("phase_message_unwritten", stage="acting", reason="stopped")
            return None
        attempt = _Attempt(words=fitted.text, went=target.channel)
        if attempted is not None:
            attempted.append(attempt)
        try:
            delivered = await target.writer.deliver(fitted, effect_id=effect_id)
        except Exception:
            # Whatever the writer raised, whether it wrote is not known; the record is
            # finished so, and the stage ends on the error.
            await self._plans.finish_activation_effect(effect_id, ToolOutcome.INDETERMINATE)
            raise
        attempt.delivery = delivered
        if delivered.written is not None:
            working.messages.append(delivered.written)
        await self._plans.finish_activation_effect(
            effect_id,
            delivered.outcome,
            reason=delivered.reason,
            position=delivered.position,
        )
        return delivered, fitted.text, target.channel

    async def _couldnt_finish(self, working: PhaseWorking) -> None:
        """Write the fixed *couldn't finish* message, listing the effects that happened.

        Written only where ADR-0317 §3:2-§3:4 name a case, which :meth:`run` and
        :meth:`unbegun` decide. The effects are read from the activation's durable
        effect records, each call done whose record says so, so a call that finished is
        listed whatever became of the step it ran in (ADR-0317 §3:1). Claimed under a
        record naming no round (ADR-0307 §10). It never raises but for a cancellation:
        a pass that failed is already ending on its own error. Where the place takes no
        message, an event's, nothing is written and nothing read (ADR-0307 §3:8,
        ADR-0309 §5:6).
        """
        scheduling = working.scheduling
        places: tuple[str | None, ...]
        if scheduling is not None and scheduling.speaks_by_label:
            # ADR-0350 §6:7: into each suggested place on the list, or nowhere.
            places = tuple(one.place for one in scheduling.places if one.suggested)
        else:
            places = (None,) if self._target(working) is not None else ()
        if not places:
            return
        effects = await self._effects(working)
        text = couldnt_finish(effects).text
        for place in places:
            await self._couldnt_finish_into(working, text, place)

    async def _couldnt_finish_into(
        self, working: PhaseWorking, text: str, place: str | None
    ) -> None:
        """Write the fixed *couldn't finish* message into one place, never raising."""
        try:
            await self._write(
                working, text, effect_id=self._new_effect_id(), round_id=None, place=place
            )
        except Exception as exc:  # the pass is ending on its own error, or on the round limit
            if is_defect(exc):
                log_defect(
                    "phase_message_unwritten",
                    exc,
                    stage="end",
                    activation_id=working.activation_id,
                )
            else:
                _log.warning("phase_message_unwritten", stage="end", reason="couldnt_finish_failed")

    async def _effects(self, working: PhaseWorking) -> tuple[str, ...]:
        """The calls that happened, and those whose outcome is unknown, as listed.

        Read from the durable effect records; where they cannot be read, from what
        acting decided on this pass, which is what is known (ADR-0317 §3:1). An unknown
        outcome is listed as unknown, never as done (ADR-0307 §3:4-§3:5, ADR-0306 §5).
        """
        try:
            recorded = await self._plans.activation_effects([working.activation_id])
        except Exception as exc:  # the store is down: list what this pass's working set knows
            if is_defect(exc):
                log_defect(
                    "phase_effects_unread", exc, stage="end", activation_id=working.activation_id
                )
            else:
                _log.warning("phase_effects_unread", stage="end", reason="store_failed")
            return tuple(
                _listed(one.call.call.request.tool.capability, _ACTED_OUTCOMES[one.outcome])
                for each in working.acted_rounds()
                for one in each.calls
                if one.outcome in _ACTED_OUTCOMES
                and one.call.call.request.tool.effect is not CapabilityEffect.NONE
            )
        return tuple(
            _listed(one.capability, one.outcome)
            for one in recorded
            if one.capability is not None
            and one.outcome in {ToolOutcome.SUCCEEDED, ToolOutcome.INDETERMINATE}
        )


class _RecallDigestFailedError(ToleratedStageError):
    """Recall's digest failed: carried on its stage's tolerated ``failed`` result.

    Never re-raised while the pass's deadline holds; the digest is recorded with no
    evidence and planning is told it could not read recall's outside records
    (ADR-0308 §4:12-§4:13).
    """
