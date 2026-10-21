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

**The commitment step** (ADR-0332 §3:5-§3:7). Before acting dispatches any call of a
round that is not a pure read, or the round's message, it checks, in the same
synchronous step as the stage's first line, for joined input the understanding the
round was planned from does not cover, and where there is none marks the activation
committed: after that no join is taken. Where there is some, the round is set aside —
none of its calls runs and its message is not written, by any path, and acting's
decision for it says so — and the rules start the activation over from understanding.
Planning starts over for each understanding version (§3:12): each round records the
version it was planned from, the rules count the latest version's rounds, and rounds of
an earlier version stay in the record with their results. An input that joined on the
activation's own place is shown to planning as an input item of the place.

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
the hub fills it from the searcher's own proposal (``WebSearcher.request``). **The clock
apart** (#2942): planning's input carries the current time, so it is never offered
``report_current_time``, which would spend a round (ADR-0315 §2:1) reading what it has
(ADR-0211's decline test). The registry keeps the tool (ADR-0048 §1), and a call naming
it is refused as any capability planning was not offered is.

**Recall's second run** (ADR-0308 §2, ADR-0309 §3's row 6). The controller runs one
stage per name, so :meth:`PhasePath.recall_stage` hands it one ``recall`` stage: the
engine's first run where the pass has no recall decision, and the second run, on the
latest understanding's meaning and phrases, where it has one. The rows decide which is
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
for the owner alone where it is ``True``. Before each round is planned the value over
what planning has been given so far is set on the activation's state, so a belief that
round remembers is placed by the supply it was produced over.

**Candidates, behind the composition root's switch** (ADR-0329 §§3-6, §19:3). Where the
path is built to have ``remember`` record candidates, a candidate's result lists the
memories similar to its fact by id, which are fetched by id before the next round as a
memory search's are, the audience predicate applied again, and handed planning with the
outcome (§4:1); one whose lookup failed is handed on saying so (§4:4). Before the first
round, the episode window's episodes the observer has not processed are read with
:func:`~ai_assistant.orchestration.candidates.pending_candidates`, and each one's
pending candidates are handed planning by its fact (§6:9). A call noting reliance has no
effect, so it reaches :class:`PhaseTools`, which answers it done and reaches nothing
(§6:7). With the switch off, none of this is reached.

**Left to later lanes:** pulls (ADR-0292 §13:3), which nothing builds yet.

**It logs stage and code-owned reason only** (ADR-0275 §8), and a defect by its class
and the frames it passed through, never its message (:func:`log_defect`).
"""

from __future__ import annotations

import asyncio
import contextlib
import contextvars
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
    CapabilityEffect,
    CapabilityResult,
    ControllerRule,
    ControllerStage,
    DeletedMessage,
    DigestOutcome,
    EpisodicMemory,
    InputOrigin,
    LabelKind,
    Memory,
    MemoryKind,
    MessageAuthor,
    Modality,
    NewMessage,
    PlanningLabel,
    ProposedCall,
    QuestionPart,
    RecallOutcome,
    SendOutcome,
    StageOutcome,
    StoryMember,
    StoryMemberKind,
    StoryRelation,
    ToolFailure,
    ToolFailureKind,
    ToolOutcome,
    ToolResult,
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
from ai_assistant.orchestration.episode_reads import without_open_episodes
from ai_assistant.orchestration.held_results import HeldResult, HeldResults
from ai_assistant.orchestration.joining import is_pure_read
from ai_assistant.orchestration.lookups import (
    OLDER_NOTES_PAGE,
    READ_STORY_CAPABILITY,
    SEARCH_MEMORY_CAPABILITY,
    searched_ids,
)
from ai_assistant.orchestration.outside_content import rests_on_outside_content
from ai_assistant.orchestration.person_block import still_held
from ai_assistant.orchestration.planning import (
    ApprovedAction,
    CallOutcome,
    CallOutcomeKind,
    DigestedEvidence,
    DigestItem,
    PlaceAuthor,
    PlaceItem,
    PlaceWindow,
    PlannedRound,
    PlanningInputs,
    PlanningStage,
    PlanningStories,
    PlanningStory,
    RecordedCandidate,
    RefusedCall,
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
from ai_assistant.orchestration.understanding import AskedIn, WrittenBy, fetch_held

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Coroutine, Iterator, Mapping, Sequence

    from ai_assistant.core.prompts import PromptTemplate
    from ai_assistant.core.protocols import (
        DiagnosticSink,
        MemoryStore,
        ModelProvider,
        PlanStore,
        StoryStore,
        ToolCallingCompleter,
        ToolInvoker,
        ToolRegistry,
        WebSearcher,
    )
    from ai_assistant.core.types import (
        ActivationDigest,
        ActivationUnderstanding,
        AnsweredQuestion,
        ChannelIdentity,
        FrozenJson,
        JoinedInput,
        MemoryRecord,
        MessageReceipt,
        PlanningRound,
        SearchOutcome,
        StoryNote,
        StoryStanding,
        StorySummaryState,
        ToolCall,
        ToolDefinition,
        TranscriptMessage,
    )
    from ai_assistant.orchestration.activation_state import ActivationState
    from ai_assistant.orchestration.controller import ControllerStageRun
    from ai_assistant.orchestration.disclosure import TurnSupply
    from ai_assistant.orchestration.lookups import LookUps
    from ai_assistant.orchestration.person_block import PersonBlock
    from ai_assistant.orchestration.recall import RecallStage
    from ai_assistant.orchestration.story_calls import StoryCalls
    from ai_assistant.orchestration.story_links import Candidates, ShortView, StoryCandidates
    from ai_assistant.orchestration.understanding import (
        Fetched,
        LineMessage,
        TranscriptWindow,
        Windows,
    )

__all__ = [
    "CHAT_DESCRIPTION",
    "EVENT_DESCRIPTION",
    "Delivery",
    "Fitted",
    "MessageWriter",
    "PhasePass",
    "PhasePath",
    "PhaseTools",
    "PhaseWorking",
    "PlaceTarget",
    "PlaceWriter",
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

#: The activation whose round's calls are running, by what it holds of what it was given:
#: a search's records are handed to it as the search returns them (ADR-0309 §5:10).
_HOLDING: Final[contextvars.ContextVar[SuppliedRecords | None]] = contextvars.ContextVar(
    "phase_tools_holding", default=None
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
        del effect_id
        message = NewMessage(
            author=MessageAuthor.ASSISTANT, text=fitted.text, cut_off=fitted.cut_off
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
    remembering, and the configured search's declaration, so authorizing's selection
    reaches them. The invoker sends a search call to the ``WebSearcher`` and every other
    call to the deployment's invoker. A call to the assistant's own records never
    reaches it: acting runs those directly (ADR-0306 §3:3).

    **The arguments the hub fills.** A connected account's destination is the hub's,
    never a model's: the search's ``origin`` is its searcher's own proposal, and a
    registered tool's, such as the booking act's, is the configured value ``fills``
    names. Planning is offered each capability without them, as it is offered none the
    declaration names in ``system_supplied`` (ADR-0306 §2:10), and they are filled
    before authorizing selects and rules.
    """

    def __init__(  # noqa: PLR0913 — the deployment's pair, the added declarations, the searcher, and the two ways the hub fills an argument
        self,
        *,
        registry: ToolRegistry,
        invoker: ToolInvoker,
        own_records: Sequence[ToolDefinition] = (),
        searcher: WebSearcher | None = None,
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
        self._search_query = search_query
        self._fills = {
            capability: dict(arguments) for capability, arguments in (fills or {}).items()
        }
        self._reliance = reliance
        self._search: ToolDefinition | None = None

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

    async def _extra(self) -> list[ToolDefinition]:
        search = await self.search_declaration()
        reliance = () if self._reliance is None else (self._reliance,)
        return [*self._own_records, *reliance, *(() if search is None else (search,))]

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
        offered: list[ToolDefinition] = []
        for name in capabilities:
            for one in await self.find(name):
                if search is not None and one == search:
                    hidden = _properties(one) - {self._search_query}
                else:
                    hidden = set(self._fills.get(name, {}))
                offered.append(_without(one, hidden))
        return tuple(offered)

    async def filled(self, call: ProposedCall) -> ProposedCall:
        """``call`` with the arguments the hub fills.

        A search's are its searcher's proposal for the query planning wrote, so its
        ``origin`` is the connected account's and never a model's; any other's are the
        configured ``fills``. Whatever else planning wrote is kept, so an argument the
        tool does not take still fails its schema at authorizing. A search whose query
        is missing is handed on as it was, and authorizing finds it fits no tool.
        """
        search = await self.search_declaration()
        filled: Mapping[str, FrozenJson] | None = self._fills.get(call.name)
        if (
            search is not None
            and self._searcher is not None
            and call.name == str(search.capability)
        ):
            query = call.arguments.get(self._search_query)
            proposed = None if not isinstance(query, str) else await self._searcher.request(query)
            filled = None if proposed is None else proposed.parameters
        if not filled:
            return call
        arguments: dict[str, FrozenJson] = {**call.arguments, **filled}
        return ProposedCall(call_id=call.call_id, name=call.name, arguments=arguments)

    @staticmethod
    @contextlib.contextmanager
    def holding(supplied: SuppliedRecords) -> Iterator[None]:
        """Hand every search run inside this scope's records to ``supplied``.

        The glue opens it around acting for a round, so the records a search returns
        are held by the activation that ran it, as the call returns them, before they
        are rendered to text (ADR-0309 §5:10).

        Args:
            supplied: The activation's record of what it was given or obtained.

        Yields:
            Nothing: the scope is the context it runs in.
        """
        token = _HOLDING.set(supplied)
        try:
            yield
        finally:
            _HOLDING.reset(token)

    async def invoke(self, call: ToolCall, *, timeout: timedelta) -> ToolResult:  # noqa: ASYNC109 — the seam owns the deadline (ADR-0029 §4)
        """Invoke ``call``: a search through its searcher, any other through the invoker.

        A search's records are memory records the call returned, so they are handed to
        the activation running it, where a :meth:`holding` scope is open, before they
        become the result's texts. A call noting reliance is answered done and reaches
        nothing: the round records it, and nothing else does (ADR-0329 §6:7).
        """
        if self._reliance is not None and call.request.tool == self._reliance:
            return noted()
        search = await self.search_declaration()
        if search is None or self._searcher is None or call.request.tool != search:
            return await self._invoker.invoke(call, timeout=timeout)
        outcome = await self._searcher.search(call, timeout=timeout)
        if (supplied := _HOLDING.get()) is not None:
            supplied.obtained(outcome.records)
        return _searched(outcome)


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
    referents = [
        *understanding.meaning_referents,
        *(one for reference in understanding.references for one in reference.referents),
        *(one for relationship in understanding.relationships for one in relationship.referents),
    ]
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
    """

    planned: PlannedRound
    authorization: RoundAuthorization | None = None
    acted: ActedRound | None = None
    looking_for: dict[str, str] = field(default_factory=dict)
    written: bool = False
    step: _Step | None = None
    planned_from: int | None = None


class PhaseWorking:
    """The phases' part of one activation's working set (ADR-0280 §3, ADR-0309 §3:2).

    Structurally :class:`~ai_assistant.orchestration.controller.PhaseFacts`, which the
    phase rules read. It holds recall's second decision and what planning fetched of
    both runs' records, each round's decisions, the activation's labels, its digests and
    the evidence they gave, its held results (acting's part of the working episode,
    never saved), and the messages it wrote.
    """

    def __init__(  # noqa: PLR0913 — the activation, its place, its trigger's origin, its audience, its round limit, its recorded labels and its input's authority
        self,
        *,
        activation_id: str,
        place: PlaceWindow,
        conversation_id: str | None,
        trigger_origin: InputOrigin | None,
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
            trigger_origin: Who the trigger's input came from.
            owner_records: Whether a record placed for the owner alone may be shown on
                this pass (ADR-0307 §6:4).
            round_limit: The most rounds the activation runs (ADR-0307 §8:4).
            labels: The labels the episode already records.
            users_authority: Whether the input carries the user's authority (ADR-0321
                §3:3, ADR-0292 §5:5), read as ADR-0323 §4:7 restates it for every
                channel: only an input whose author its channel's kind establishes as
                the user, sent as an instruction, does — the user's message in the hub
                chat, or on the Telegram line from their own account, not forwarding.
                ``False``, the default, wherever it cannot be established.
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
        self.trigger_origin = trigger_origin
        self.owner_records = owner_records
        self.users_authority = users_authority
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
        """The latest round's authorizing decision allows a call or its message."""
        decided = self._rounds[-1].authorization if self._rounds else None
        if decided is None:
            return False
        return bool(decided.allowed) or (decided.message is not None and decided.message.allowed)

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

    def planned(self, planned: PlannedRound) -> None:
        """Hold a round planning decided, and the labels it assigned.

        The round is planned from the latest understanding version (ADR-0332 §3:12).
        """
        self.labels.add(planned.labels)
        self._rounds.append(_Round(planned=planned, planned_from=self.version))

    def overtaken(self) -> frozenset[str]:
        """The rounds new input overtook before they acted (ADR-0332 §3:7, §3:12-§3:13).

        Each planned from an earlier understanding version than the latest: a join came
        before it committed, so its message was never written and nothing it asked about
        was shown, whether its round was set aside or never reached acting. Only a pure
        read of it can have run.
        """
        return frozenset(
            one.planned.round.id for one in self._rounds if one.planned_from != self.version
        )

    def understood(self, version: int) -> None:
        """Hold the latest recorded understanding version, which planning starts over for.

        ADR-0332 §3:12: ``first_round_due`` answers until a round is planned from it,
        and ``round_due`` and ``round_limit_reached`` count that version's rounds.
        """
        self.version = version

    def take_joined(self, joined: Sequence[JoinedInput], place: ChannelIdentity | None) -> None:
        """Take the inputs that joined on the activation's own place into what planning sees.

        ADR-0332 §3:16, ADR-0292 §6:10: an input that joins is part of the activation's
        input, so each of its messages is shown to planning as an input item of the
        place, the user's, as the reader's own are; and a yes it carries is given when
        its latest message was sent (ADR-0321 §4:6). An input a takeover brought came
        from another place: it is not an item of this one, and reaches planning through
        understanding's record alone. Each joined input is taken once.
        """
        fresh = list(joined[self._joined_taken :])
        self._joined_taken = len(joined)
        items: list[PlaceItem] = []
        for one in fresh:
            if one.taken_over_from is not None or one.channel != place:
                continue
            for message in one.messages:
                items.append(
                    PlaceItem(
                        author=PlaceAuthor.USER,
                        text=message.text,
                        at=message.sent_at,
                        is_input=True,
                        referent_id=(
                            None if message.position is None else f"message:{message.position}"
                        ),
                    )
                )
                if self.given_at is not None and message.sent_at > self.given_at:
                    self.given_at = message.sent_at
        if items:
            self.place = replace(self.place, items=(*self.place.items, *items))

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
            # ADR-0332 §3:12-§3:13: a round planned from an earlier version was overtaken
            # by a join before it committed, so it wrote nothing that needed writing.
            if one.planned_from != self.version:
                continue
            if one.planned.message is not None:
                return not one.written
        return False

    def step(self, at: datetime, wait: timedelta) -> _Step:
        """The latest round's step, begun at ``at`` and waited on for ``wait`` at most.

        Begun by whichever of its two stages reaches it first, so each sees one step.
        """
        latest = self.latest
        if latest.step is None:
            latest.step = _Step(deadline=at + wait)
        return latest.step

    def _on_hold(self, held: HeldResult) -> None:
        """Hand a result acting holds to the step digesting it (ADR-0308 §4:2)."""
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
            for outcome in call_outcomes(one.planned, one.authorization, one.acted):
                capability = names.get(outcome.call_id)
                if outcome.result_id is not None:
                    capability = ran.get(outcome.result_id, capability)
                outcomes.append(self._looked_up(outcome, capability))
        return tuple(outcomes)

    def _looked_up(self, outcome: CallOutcome, capability: str | None) -> CallOutcome:
        """``outcome``, carrying what its look-up found where it was one."""
        result_id = outcome.result_id
        if result_id is None:
            return outcome
        page = self.pages.get(result_id)
        if page is not None and capability == READ_STORY_CAPABILITY:
            return replace(outcome, result=None, story=page)
        searched = self.searched.get(result_id)
        if searched is not None and capability == SEARCH_MEMORY_CAPABILITY:
            return replace(outcome, result=None, records=searched)
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
        trigger or a fetched record resting on outside content.
        """
        return (
            self.trigger_origin is InputOrigin.OUTSIDE
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
        answers = () if understanding is None else understanding.answers
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


def call_outcomes(
    planned: PlannedRound,
    authorization: RoundAuthorization | None,
    acted: ActedRound | None,
) -> tuple[CallOutcome, ...]:
    """What came of one round's calls, as planning reads them, in the round's order.

    A call planning's own check refused, or authorizing found not done, is refused;
    one authorizing sent to the user needs you, carrying the request a question about it
    shows and records, or the part of the question it already waits on (ADR-0321 §2:8,
    §4:11); and one it allowed is what acting made of it, its result under the id acting
    minted (ADR-0306 §5:1, §5:14), or needing you where the memory writer asked at write
    time, with the assertions its question shows replaced (ADR-0321 §5:5). A call with no
    decision yet has no outcome.
    """
    refused = {one.call.call_id: one.reason for one in planned.refused}
    verdicts = {} if authorization is None else {one.call_id: one for one in authorization.verdicts}
    ran = {} if acted is None else {one.call.call.decision.id: one for one in acted.calls}
    round_id = planned.round.id
    outcomes: list[CallOutcome] = []
    for call in planned.round.calls:
        call_id = call.call_id
        if call_id in refused:
            outcomes.append(
                CallOutcome(round_id, call_id, CallOutcomeKind.REFUSED, reason=refused[call_id])
            )
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
            )
        )
    return tuple(outcomes)


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
        self, planning_round: PlanningRound, labels: tuple[PlanningLabel, ...]
    ) -> None:
        """Add the round and its labels to the activation's record, and extend it."""
        state = active_state()
        if state is None:
            return
        working = _PLANNING.get()
        if working is not None:
            planning_round = self._path.shown_whole(working, planning_round)
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


#: Why a call a join set aside was not done (ADR-0332 §3:7), as planning reads it.
_SET_ASIDE: Final = "not run: new input joined before this round acted, so it was set aside"


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
    return message or any(not is_pure_read(one.call.request.tool) for one in decided.allowed)


def _commitment(latest: _Round, decided: RoundAuthorization) -> ActedRound | None:
    """Acting's commitment step for the latest round, or ``None`` where it may run.

    ADR-0332 §3:5-§3:7: before acting dispatches any call that is not a pure read, or the
    round's message, it checks for joined input that the understanding the round was
    planned from does not cover, and where there is none marks the activation committed
    (:meth:`ActivationState.commit`), **in one synchronous step**: nothing here awaits,
    and acting dispatches nothing before it returns. A round of pure reads alone commits
    nothing and is not checked; a pass no channel admitted takes no join.

    Returns:
        ``None`` where the round runs. Otherwise acting's decision for it, present and
        dispatching nothing by any path: set aside by a join, each allowed call not done
        with the reason (§3:7), or, where the stop mark is set, nothing at all, and the
        pass ends on the stop (ADR-0297 §4).
    """
    state = active_state()
    if state is None or not _commits(latest, decided):
        return None
    found = state.commit(latest.planned_from)
    if found is Commitment.COMMITTED:
        return None
    if found is Commitment.STOPPED:
        _log.info("phase_round_not_acted", stage="acting", reason="stopped")
        return ActedRound(round_id=decided.round_id)
    _log.info("phase_round_set_aside", stage="acting", reason="joined")
    return ActedRound(
        round_id=decided.round_id,
        calls=tuple(
            ActedCall(call=one, outcome=ActedOutcome.NOT_DONE, reason=_SET_ASIDE)
            for one in authorized_round(decided).calls
        ),
        set_aside=True,
    )


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


def _hold_given(given: PhasePass, working: PhaseWorking) -> None:
    """Hold what the stages before planning gave the activation (ADR-0309 §5:10).

    The windows' records; the first recall run's kept records as the understanding phase
    fetched them; and the episodes of the candidate stories it was shown (ADR-0300
    §6:1). Held again on each call, which holds each record once.
    """
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
        provider: ModelProvider,
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
        now: Callable[[], datetime] = _utcnow,
        timezone: str = "UTC",
        new_effect_id: Callable[[], str] = _new_effect_id,
        diagnostics: DiagnosticSink | None = None,
        candidates: bool = False,
    ) -> None:
        """Wire the path.

        Args:
            completer: The native tool-calling seam planning's rounds go through.
            provider: The model seam a digest's calls go through (ADR-0308 §4:10).
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
            now: The clock a step's start and an effect's claim are read from.
            timezone: The IANA name of the zone planning is shown the current time in
                (#2964), handed on to planning: ``Settings.timezone``.
            new_effect_id: Mints the *couldn't finish* message's effect record id.
            diagnostics: The diagnostic record's write seam, handed on to planning
                and digesting, which this path builds (ADR-0314 §4:4); ``None`` where
                the record is off. The path itself writes no entry (§4:2).
            candidates: Whether ``remember`` records a candidate (ADR-0329 §§3-6), the
                composition root's switch, handed on to planning: the episode window's
                pending candidates are then read and shown (§6:9). Off by default, which
                keeps ADR-0328 §13's interim.

        Raises:
            ValueError: If ``round_limit`` is below 1, ``round_wait`` or
                ``recall_digest_wait`` not positive, or ``recall_cap`` below 1 or above
                ``RECALLED_ITEMS_MAX``.
        """
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
            candidates=candidates,
        )
        self._candidates = candidates
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
        self._story_calls = story_calls
        self._look_ups = look_ups
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

    def _spawn_held(self, work: Coroutine[None, None, None]) -> None:
        """Start ``work`` as a task this path holds until it ends."""
        task = asyncio.get_running_loop().create_task(work, context=contextvars.Context())
        self._held.add(task)
        task.add_done_callback(self._held.discard)

    async def append(self) -> None:
        """Extend the current activation's open episode, where an append is attached."""
        if self._append is not None:
            await self._append()

    def begin(  # noqa: PLR0913 — the activation, its window, its place, its origin, its audience and its recorded labels
        self,
        *,
        activation_id: str,
        window: TranscriptWindow,
        conversation_id: str,
        trigger_origin: InputOrigin | None,
        owner_records: bool,
        labels: Sequence[PlanningLabel] = (),
    ) -> PhaseWorking:
        """Start one conversation turn's working set, before its first stage.

        A turn is the hub chat's: the chat's reader brings its input in. Its input
        carries the user's authority (ADR-0321 §3:3, ADR-0292 §5:5) only where the
        trigger says the user sent it and every message taken in is the user's, the
        author a conversation establishes; anything not established is not the user's.
        A yes it carries is given when its latest message was written (§4:6).

        Args:
            activation_id: The activation.
            window: The conversation's recent transcript, brought in with the input.
            conversation_id: The conversation the input came from, which a message is
                written into (ADR-0307 §3:1).
            trigger_origin: Who the trigger's input came from.
            owner_records: Whether a record placed for the owner alone may be shown.
            labels: The labels the episode already records.

        Returns:
            The working set, which the engine holds on the pass.
        """
        taken = window.input_messages
        return PhaseWorking(
            activation_id=activation_id,
            place=place_window(window),
            conversation_id=conversation_id,
            trigger_origin=trigger_origin,
            owner_records=owner_records,
            round_limit=self._round_limit,
            labels=labels,
            users_authority=(
                trigger_origin is InputOrigin.USER
                and bool(taken)
                and all(one.author is MessageAuthor.USER for one in taken)
            ),
            given_at=max((one.written_at for one in taken), default=None),
        )

    def begin_line(  # noqa: PLR0913 — the activation, its window, its place, its kind's two facts, its origin, its audience and its recorded labels
        self,
        *,
        activation_id: str,
        window: TranscriptWindow,
        target: PlaceTarget,
        description: str,
        giver: ApprovalGiver,
        trigger_origin: InputOrigin | None,
        owner_records: bool,
        labels: Sequence[PlanningLabel] = (),
    ) -> PhaseWorking:
        """Start one activation's working set for a line's chat, before its first stage.

        A line is a place other than the hub chat's conversations whose kind
        establishes the user, as the Telegram line's chat (ADR-0323 §2): its reader
        brings the input in with the window its kind declares (§10), and its messages
        go into the input's place through ``target``'s writer alone (§6:1). Its input
        carries the user's authority (ADR-0321 §3:3 as ADR-0323 §4:7 restates it) only
        where the trigger says the user sent it and **every message taken in is the
        user's, established, and none is a forward** (§4:6): a forward's author is
        claimed (§4:10), and an input taking one in is an outside trigger (§4:11). A
        yes it carries is given by ``giver`` when its latest message was sent (§4:9).

        Args:
            activation_id: The activation.
            window: The line's window, brought in with the input.
            target: The line's chat and its writer.
            description: The line's kind's description, which planning is shown with
                the place (ADR-0292 §8:1).
            giver: Who a yes on the line is: the user, through it (§4:9).
            trigger_origin: Who the trigger's input came from.
            owner_records: Whether a record placed for the owner alone may be shown.
            labels: The labels the episode already records.

        Returns:
            The working set, which the engine holds on the pass.
        """
        taken = window.input_messages
        return PhaseWorking(
            activation_id=activation_id,
            place=place_window(window, description=description),
            conversation_id=None,
            trigger_origin=trigger_origin,
            owner_records=owner_records,
            round_limit=self._round_limit,
            labels=labels,
            users_authority=(
                trigger_origin is InputOrigin.USER
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

    def begin_event(
        self,
        *,
        activation_id: str,
        trigger_origin: InputOrigin | None,
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
            trigger_origin: Who the trigger's input came from.
            owner_records: Whether a record placed for the owner alone may be shown.
            labels: The labels the episode already records.

        Returns:
            The working set, which the engine holds on the pass.
        """
        return PhaseWorking(
            activation_id=activation_id,
            place=PlaceWindow(takes_message=False, description=EVENT_DESCRIPTION),
            conversation_id=None,
            trigger_origin=trigger_origin,
            owner_records=owner_records,
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
                # ADR-0309 §5:10: taken once, here, over every round. The windows are
                # held again in case no round was planned to hold them.
                _hold_given(given, working)
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
            trigger_origin=None,
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
        """One planning round, over everything the thin path gives it (ADR-0307 §6)."""
        working = _working(given)
        fetched = given.understanding_fetch
        if (joining := active_state()) is not None:
            # ADR-0332 §3:16: what joined on this place is input planning is shown.
            working.take_joined(joining.joined, joining.place)
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
        except TimeoutError:
            raise ModelTimeoutError(_PLANNING_EXPIRED) from None
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
        _hold_given(given, working)
        if (state := active_state()) is not None:
            # ADR-0217 §3:12: a belief this round remembers is produced over what
            # planning has been given so far, so it is placed by that supply.
            state.planned_over_withheld = working.supplied.withheld(given.supply)
        inputs = PlanningInputs(
            activation_id=working.activation_id,
            place=working.place,
            understanding=given.understanding,
            trigger_origin=working.trigger_origin,
            episodes=() if fetched is None or fetched.episodes is None else fetched.episodes,
            recalled=found.recalled,
            recalled_stories=_recalled_stories(given.recalled, working.second_recall),
            owner_records=working.owner_records,
            rounds=working.planning_rounds(),
            labels=working.labels.labels,
            outcomes=working.outcomes(),
            capabilities=await self._offered(),
            label_arguments=self._label_arguments,
            evidence=tuple(working.evidence),
            outside_content_read=working.read_outside_content,
            stories=stories,
            approved=approved,
            pending=pending,
            overtaken=working.overtaken(),
            person=person,
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
        whole = self.shown_whole(working, planned.round)
        if whole is not planned.round:
            planned = replace(planned, round=whole)
        working.planned(planned)

    async def _person(self, working: PhaseWorking) -> PersonBlock | None:
        """The activation's person block for this round, less what memory no longer holds.

        ADR-0338 §7:3, §7:10: the block assembled before understanding, from which every
        memory the memory store no longer holds is dropped before each round, the first
        included, and the state keeps what is left, so a memory forgotten while the
        activation runs reaches no later request. ``None`` where the activation has no
        block.

        Every memory the block held before the drop was given to the activation —
        understanding was shown its pins, and an earlier round the rest — so each is
        held among what the activation was given, and the episode inherits its
        placement (ADR-0309 §5:10, ADR-0217 §3) whether or not it is dropped later.
        """
        state = active_state()
        if state is None or state.person_block is None:
            return None
        working.supplied.obtained(state.person_block.memories)
        state.person_block = await still_held(state.person_block, self._memory)
        return state.person_block

    async def _pending(
        self, given: PhasePass, working: PhaseWorking
    ) -> Mapping[str, tuple[str, ...]]:
        """The episode window's pending candidates, read once (ADR-0329 §6:9).

        Only where candidates are recorded: each episode the window shows that the
        observer has not processed, with the facts of the candidates its own rounds
        recorded, read from the plan store as it stands before the first round. A plan
        store that cannot be read shows none, and planning goes on.
        """
        if not self._candidates:
            return {}
        if working.pending is None:
            fetched = given.understanding_fetch
            episodes = () if fetched is None or fetched.episodes is None else fetched.episodes
            try:
                working.pending = await pending_candidates(self._plans, episodes)
            except PlanningError:
                _log.warning("planning_candidates_unread", stage="planning")
                working.pending = {}
        return working.pending

    async def _offered(self) -> tuple[ToolDefinition, ...]:
        """The declarations this round offers planning (ADR-0306 §2:7), the clock apart.

        Planning's input carries ``now``, so the clock's call would only spend a round
        on what it has (#2942): it is left out of the offer, and stays registered.
        """
        names = (
            await self._tools.capabilities() if self._capabilities is None else self._capabilities
        )
        return await self._tools.offered([name for name in names if name not in _NOT_OFFERED])

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

        Its cues are the latest understanding's meaning and the phrase of each of its
        references (§2:2), and it passes over what the windows hold and every record the
        first run kept (§2:3). The decision is held in the working set and carried on
        the activation's state before the stage returns, so the row that made it due
        does not answer again; understanding never reads it (§2:8). A ``failed`` or
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
            tuple(one.phrase for one in understanding.references),
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
        ]
        target = self._target(working)
        place = None if target is None else target.place
        message = (
            None
            if planned.message is None or place is None
            else RoundMessage(planned.message, place)
        )
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
            input_place=place,
            message=message,
            yes=working.yes(given.understanding),
        )
        try:
            async with asyncio.timeout_at(given.deadline):
                decided = await self._authorizing.authorize(given_round)
        except TimeoutError:
            raise ModelTimeoutError(_AUTHORIZING_EXPIRED) from None
        latest.authorization = decided
        looking = {one.call.call_id: one.looking_for for one in planned.calls if one.looking_for}
        latest.looking_for = {
            verdict.decision_id: looking[verdict.call_id]
            for verdict in decided.verdicts
            if verdict.verdict is Verdict.ALLOWED
            and verdict.decision_id is not None
            and verdict.call_id in looking
        }

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
        try:
            # ADR-0332 §3:18: a join taken whose marking has not landed is waited for,
            # so the reader's bookkeeping holds what joined before anything acts on it.
            # The wait is inside the pass's deadline (§3:14: a join does not extend
            # it), and the deadline is read again after it with no await before the
            # commitment step: a wait that crosses it dispatches nothing, and acting
            # fails with its classified expiry (ADR-0280 §5).
            state = active_state()
            if state is not None:
                try:
                    async with asyncio.timeout_at(given.deadline):
                        await state.settled()
                except TimeoutError:
                    raise ModelTimeoutError(_ACTING_EXPIRED) from None
            if given.deadline <= asyncio.get_running_loop().time():
                raise ModelTimeoutError(_ACTING_EXPIRED)
            # ADR-0332 §3:5-§3:7: the commitment step, before anything of the round is
            # dispatched, in one synchronous step with no await before the dispatch.
            withheld = _commitment(latest, decided)
            if withheld is not None:
                latest.acted = withheld
                return
            ran, wrote = await asyncio.gather(
                self._calls(given, working, decided),
                self._message(working, latest),
                return_exceptions=True,
            )
        finally:
            step.held.put_nowait(None)
        if isinstance(ran, ActedRound):
            # Kept even where the message beside it failed: what acting ran happened.
            latest.acted = ran
            # The assertions a remember that needs you would replace were read from the
            # store, and planning is shown them: obtained, so they place what follows
            # (ADR-0309 §5:10, ADR-0321 §5:5).
            working.supplied.obtained(record for one in ran.calls for record in one.replaces)
        for answer in (ran, wrote):
            if isinstance(answer, BaseException):
                raise answer

    async def _calls(
        self, given: PhasePass, working: PhaseWorking, decided: RoundAuthorization
    ) -> ActedRound:
        """Run the round's allowed calls; its tidy-ups run on their own, unawaited.

        **The look-ups** (ADR-0307 §6:6) run inside a scope opened around acting, so
        they read under the pass's audience and its owner-only placement. A story's full
        view a story read read is held under its call's result once acting returns.

        **The tidy-up exception** (ADR-0307 §7:2, §8:1). A new round waits for every
        call of the last one but a tidy-up, and neither it nor the activation's end
        waits for one. So the round's allowed tidy-ups are split off and handed to
        acting in a task of their own, which this does not await: acting runs them
        through its own-records seam and awaits each to its end (ADR-0306 §3:3), after
        the activation has ended if need be. What came of one is written to the story's
        version log, never to the episode (§7:1), so no acting decision of it is held.
        """
        tidies = tuple(
            one
            for one in decided.allowed
            if str(one.call.request.tool.capability) == TIDY_STORY_CAPABILITY
        )
        if tidies:
            self._start_tidies(working, decided, tidies)
        started = {one.call.decision.id for one in tidies}
        rest = tuple(one for one in decided.allowed if one.call.decision.id not in started)
        if not rest:
            return ActedRound(round_id=decided.round_id)
        authorized = authorized_round(replace(decided, allowed=rest))
        with self._tools.holding(working.supplied):
            if self._look_ups is None:
                return await self._acting.act(authorized, held=working.held)
            with self._look_ups.scope(
                audience=given.supply, owner_records=working.owner_records
            ) as scope:
                try:
                    acted = await self._acting.act(authorized, held=working.held)
                finally:
                    # Every view a story read read was obtained, whatever became of
                    # the round's other calls (ADR-0309 §5:10).
                    working.supplied.obtained(
                        _story_records(PlanningStories(stories=tuple(scope.views.values())))
                    )
        self._pages(working, acted, scope.views)
        return acted

    @staticmethod
    def _pages(
        working: PhaseWorking, acted: ActedRound, views: Mapping[str, PlanningStory]
    ) -> None:
        """Hold each story's full view a done story read read, under its call's result.

        A view resting on outside content, a marked summary or note, an episode resting
        on outside content or a marked moment, sets ``fetched_outside``, counted as the
        story views are (ADR-0300 §10:6, ADR-0306 §4:5) and named by what set it; every
        note it shows is held with its mark, which authorizing reads for its ``N`` label.
        """
        for one in acted.calls:
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
        """Write the round's message into the input's place, where it may go (§3:1)."""
        decided = latest.authorization
        text = latest.planned.message
        verdict = None if decided is None else decided.message
        if verdict is None or not verdict.allowed or verdict.effect_id is None or text is None:
            return
        # Whether it was recorded decides whether the activation's last message was
        # delivered (ADR-0317 §3:4).
        latest.written = await self._write(
            working, text, effect_id=verdict.effect_id, round_id=latest.planned.round.id
        )

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
                held, question=question, labels=working.labels, deadline=deadline
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

    def shown_whole(self, working: PhaseWorking, planning_round: PlanningRound) -> PlanningRound:
        """``planning_round``, asking about nothing where its message would not be shown whole.

        The dispatcher's ruling on ADR-0321 §4:4's *shown*: a message cut to fit is not
        shown, since its exact lines come last (§2:5) and any cut takes them. So a round
        whose message the place would cut, by the transcript's bound or the writer's,
        records no asked call: by §2:2 nothing waits on the user that they were not
        clearly asked about, so no yes to that message approves anything, no proposal is
        held back as already asked, and the call may be asked about again whole. Where
        whether it fits cannot be told, it is taken not to, failing closed.

        Returns:
            ``planning_round`` itself where it asks about nothing or its message would be
            shown whole; otherwise a copy that asks about nothing.
        """
        if not planning_round.asked:
            return planning_round
        target = self._target(working)
        whole = False
        if target is not None:
            try:
                whole = not self._fitted(target, planning_round.text).cut_off
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

    def _target(self, working: PhaseWorking) -> PlaceTarget | None:
        """The place the activation's messages go into, and its writer, or ``None``.

        The working set's own target, as the Telegram line's chat; otherwise its
        conversation, through this path's chat writer; and ``None`` where the place
        takes no message, an event's (ADR-0307 §3:8).
        """
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
        pointers = () if given.understanding is None else given.understanding.answers
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
        self, working: PhaseWorking, text: str, *, effect_id: str, round_id: str | None
    ) -> bool:
        """Claim, write and finish one message into the input's place (ADR-0306 §5:3-§5:5).

        The place's writer says what came of it (:class:`Delivery`): done at a position,
        not done with why, or unknown. Whatever of it the place now holds is what the
        episode records the activation sent, a message cut short between parts
        included, whatever becomes of the record's finish (ADR-0284 §4:1).

        Returns:
            Whether the medium recorded it whole.
        """
        target = self._target(working)
        if target is None:
            return False
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
            return False
        try:
            delivered = await target.writer.deliver(fitted, effect_id=effect_id)
        except Exception:
            # Whatever the writer raised, whether it wrote is not known; the record is
            # finished so, and the stage ends on the error.
            await self._plans.finish_activation_effect(effect_id, ToolOutcome.INDETERMINATE)
            raise
        if delivered.written is not None:
            working.messages.append(delivered.written)
        await self._plans.finish_activation_effect(
            effect_id,
            delivered.outcome,
            reason=delivered.reason,
            position=delivered.position,
        )
        return delivered.outcome is ToolOutcome.SUCCEEDED

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
        if self._target(working) is None:
            return
        effects = await self._effects(working)
        text = couldnt_finish(effects).text
        try:
            await self._write(working, text, effect_id=self._new_effect_id(), round_id=None)
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
