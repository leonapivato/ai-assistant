"""The planning stage: one planning round, recorded with the episode (ADR-0307).

One orchestration-local phase module (ADR-0309 §2:2), of the kind
:class:`~ai_assistant.orchestration.acting.ActingStage` is. It holds an injected
``ToolCallingCompleter``, a seam onto the episode writer, the excerpt bound and a
clock, and it is **not a Protocol**. Each :meth:`PlanningStage.plan` is one controller
step and one round (§2:3): it assembles planning's inputs, asks the model once, records
the round, and judges the round's calls. It runs nothing, writes no message and
decides nothing about whether a call may run (§9:1).

**The briefing** (ADR-0356 §3, §4:1). A work's first round renders the briefing once: the
system's first turn, tagged text in ADR-0353's format, its sections in one fixed order,
the stimulus first, every section on every briefing and an empty one saying why. Every
item is in a tag whose attributes say who or what it is from, and an item planning may
name carries its label. Another episode is shown by its short view (:func:`short_view`,
§9), a selection of its own recorded parts.

**A work's rounds are one continuing exchange** (§5). :class:`PlanningWork` holds the
exchange, with the round's response, and the phases hand it to the next round, which hands
both in byte for byte and appends the last round's response, as the completer returned it,
and its report: one result for each of its calls, in its order and under its ids, code's
rendering of what came of it, a digested one as its digest's evidence, then the news: the
time, and what the inputs hold that the exchange has not shown (§5:3-§5:6, ADR-0359,
ADR-0360). Every round of a work is offered the tools its first was (§4:3). The round's
text is its reply to the system, kept as its notes and written to no one (§7:2-§7:3).

**What it is given** (§6, as ADR-0312 §4 corrects it). Understanding's record and its
story links; the place window and the episode window; what both recall runs found
(ADR-0308 §3), each episode by its records with the labels of the stories it is in, and
each memory record only where its source is not outside; this activation's earlier
rounds and their notes, shown on every pass whatever the audience; acting's outcomes;
the offered capabilities and the channel kind's description; the current time, in the
person's zone where their profile sets one and the configured zone otherwise (ADR-0338
§3:6), with its offset and the zone's name beside it (#2964); and
digested evidence, which the digesting stage and recall's digest supply, each digest
under the label of the result it read and each item under its source's label (ADR-0308
§5:1). The episode window's and the found episodes' notes follow the reader's audience
(ADR-0307 §6:4, ADR-0312 §4:2). Raw outside content is never shown (§9:2): not a place
item someone else wrote, not an outside episode's input, not an outside memory record,
and not a referent's excerpt.

**The person block** (ADR-0338 §7:3, §7:6-§7:9). Where the activation is a person's and a
person-model store is wired, the briefing's always-in-mind section shows the person's
fields, the whole kept-in-mind slot and the pending suggestions the block admits, each
marked as a suggestion and never as the profile: data, as the person's own choices, never
an instruction. Its memories take their
labels the first time planning is shown them, and a found memory the block shows is named
there by its label alone. The phases' glue drops before each round every memory the memory
store no longer holds (§7:10). Where there is no block, nothing of the person model reaches
the request or the instruction.

**What planning looked up for itself** (§6:6). A done look-up's result is shown under its
R label: a memory search's records whose source is not outside, each under its own M label
as a found one is, its outside records only as its digest's evidence; a story's full view
as the story views are rendered, its marks with it; and a follow-up's result is the
result it names, read again by a digest against its new question. The phases' glue
fetches and reads these and hands them on with the outcome; this module renders them.

**The story views** (§6:1, §6:3-§6:4, ADR-0300 §8). For each story the activation belongs
to, planning is shown its summary, the notes and episodes newer than it, when it was
last tidied and how many changes have come since, the short views of the stories it is
part of marked as inherited, where its matter stands, what was done included, and its
latest episodes; and the short view of each story understanding cited as a referent that
the activation is not in. The views are assembled by the phases' glue under the pass's
audience (:class:`PlanningStories`); this module renders them. Where a record placed for
the owner alone may not be shown, a summary is withheld and the view says so, notes are
absent with nothing said of them, and the episodes and where the matter stands are only
what the audience may be shown; when the summary was last tidied and the count are
shown on every pass. A marked summary or note, an episode resting on outside content and
a marked moment of where a matter stands are each outside content planning has read.

**Offered capabilities** (ADR-0306 §2:7 to §2:9). One tool per capability, offered only
where every tool satisfying it declares the same five properties and one schema. Each
gets a required *looking for* argument where its result may carry outside text and a
*deliberate repeat* mark where it is not safe to repeat. Arguments the declaration
names in ``system_supplied`` are the hub's to fill and are not offered.

**Labels** (§5). Everything planning is shown that it may name gets a label the first
time it is shown, from any source, and keeps it for the whole activation; the labels
already recorded with the episode are carried in, and the round's new ones are
recorded with it. Episode notes take no label. A place-window item that links to an
activation is shown with that activation's episode label.

**The same exchange, shown once** (ADR-0276 §3, read with ADR-0307 §5:6 and §6:1; #2951).
An episode whose exchange the place window already shows, by items linked to its
activation, is that exchange shown twice. Its messages stay in the place window, under
its label. Wherever the episode itself is rendered, its entry keeps the label and
everything only the episode carries, its notes, status and evidence among
them, and each text the place window shows whole is replaced by a line saying so: its
input, where the user's linked items are that input; its response, where the
assistant's linked items are the messages it wrote; and a round's message, where one of
the assistant's linked items is that message. A text the window shows only in part, or
not at all, is rendered as before, and an episode no item links to is rendered whole.

**Recorded before anything goes out** (§2:3 to §2:4, §3:1). The round is appended through
:class:`RoundRecorder` before :meth:`PlanningStage.plan` returns, so its calls run only
after the append has returned. An append that fails is a capture failure: it is logged
and holds back none of the calls.

**Judged before authorizing** (§5:3 to §5:4, the hub's half). A call naming a capability
not offered, a label planning was never shown or one of the wrong kind, or lacking its
*looking for*, is refused whole with its reason and runs nothing. A call that passes
carries ids in place of labels, and its *looking for* and *deliberate repeat* are
taken out of its arguments (ADR-0306 §2:10). Whether a note a move names is still held
is the story store's half, in the lane that builds planning's story calls. A call to a
capability whose condition for running does not hold here, which the phases say in
:attr:`PlanningInputs.not_here`, is refused with that reason, and on a waiting round a
stop naming work the round does not wait on is refused (ADR-0356 §4:4-§4:5).

**Asking** (ADR-0321 §2). A call that came back needing the user's yes is shown with a
reference and its exact line, written by :func:`exact_line` for every capability alike.
No part of a response names the calls a message asks about (ADR-0356 §7:5): the round's
asking message is its first ``text`` call carrying ``asks`` (ADR-0357 §8:1, §8:3), which
names them by those references. A name that resolves to no such call is dropped (§8:5).
For each call it asks about, code renders one exact line, and the round records the call
in its ``asked``, its part the line's number (ADR-0321 §2:6, §2:8); the lines go out to
the phases on :attr:`PlannedRound.questions`, which append them after any rewording
(ADR-0357 §8:2). A second ``text`` call carrying ``asks`` is refused (§8:3).

**Approved actions** (§4:2). The actions the activation's yes approved are shown under A
labels and proposed through :data:`APPROVED_ACTION_TOOL` by label alone. The judge fills
in the values recorded with the question and names the part in
:attr:`PlannedCall.approved_part`, so nothing planning sends beside the label changes
them.

**Candidates** (ADR-0329 §6). Where ``remember`` is offered, it records a candidate,
and the instruction says what a candidate is for, how eager to be, when to name a
memory, when to ask, and how to reply (§6:1-§6:5), and how to note reliance where that
capability is offered (§6:8). A candidate's result
says it is recorded and pending, with the memories similar to its fact each under its
own M label, or that they could not be read (§4:1, §4:4, §6:5). An episode of the
episode window the observer has not processed is shown with its pending candidates,
each by its fact (§6:9), which the phases' glue reads and hands over. A memory's label
carries each unresolved open question on it, in words, wherever it is shown (§6:6).

**The instruction is a template** (ADR-0334): the system message is rendered from
:data:`PLANNING_PROMPT`'s template, which the composition root reads at start and hands
the stage, and this module keeps no copy of its text (§3:1). It takes no flag and no value
(ADR-0356 §4:2); the briefing, the reports, the tool declarations, the judge, the exact
lines and every rule above stay here, whatever a template says (§1:3, §7:2).

**It logs stage and code-owned reason only**, never inputs, model output or arguments
(ADR-0275 §8).
"""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Final, Protocol
from uuid import uuid4
from zoneinfo import ZoneInfo

import structlog

from ai_assistant.core.channel_validation import OriginKind, origin_kind
from ai_assistant.core.clock import checked_clock
from ai_assistant.core.diagnostics import returned_written, write_diagnostic, write_failure
from ai_assistant.core.episode_encoding import project_episode
from ai_assistant.core.prompts import PromptDeclaration
from ai_assistant.core.types import (
    DEFAULT_ASSISTANT_NAME,
    OWNER_PERSON_ID,
    PEER_COULDNT_FINISH_LINE,
    AskedCall,
    BeliefBand,
    CallOutcomeKind,
    CallResult,
    CallShowed,
    CapabilityResult,
    ChannelIdentity,
    DiagnosticKind,
    DiagnosticSource,
    EpisodicMemory,
    ExchangeStep,
    HolderKind,
    LabelKind,
    MemoryMark,
    MemoryStanding,
    Message,
    NewConversation,
    OfferedTool,
    PlanningExchange,
    PlanningLabel,
    PlanningRound,
    ProfileField,
    ProjectedCall,
    ProjectedEvidence,
    ProjectedJoin,
    ProjectedProposal,
    ProjectedRecall,
    ProjectedRound,
    ProjectedUnderstanding,
    ProposedCall,
    ReadingCertainty,
    RecordedTextInput,
    Role,
    RoundReport,
    ShownRecord,
    ShownRecordKind,
    ShownText,
    StoryEffectState,
    StoryMemberKind,
    StoryNoteAuthor,
    StoryRelation,
    SupportHolder,
    ToolOutcome,
    label_prefix,
    parties_are_outside,
    parties_are_persons_own,
    relay_mark_counts,
    statement_citations,
)
from ai_assistant.orchestration.channel_kinds import place_channel, place_of
from ai_assistant.orchestration.matters import (
    STOP_ACTIVATION_CAPABILITY,
    EntryInput,
    NotAsAsked,
)
from ai_assistant.orchestration.message_tools import (
    asks_named,
    carries_asks,
    platform_name,
)
from ai_assistant.orchestration.person_block import activation_person, person_zone
from ai_assistant.orchestration.stories import episode_address
from ai_assistant.orchestration.story_calls import (
    STORY_CALL_CAPABILITIES,
    TIDY_STORY_CAPABILITY,
)
from ai_assistant.orchestration.task_scheduler import (
    StartingEntry,
    place_description,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Collection, Iterable, Sequence

    from ai_assistant.core.prompts import PromptTemplate, RenderedPrompt
    from ai_assistant.core.protocols import DiagnosticSink, ToolCallingCompleter
    from ai_assistant.core.types import (
        ActionRequest,
        ActivationUnderstanding,
        ClaimedAuthor,
        EpisodeProjection,
        FrozenJsonValue,
        JoinedInput,
        Memory,
        PeerEffect,
        PeerView,
        Profile,
        ProjectedText,
        QuestionPart,
        RecordedChannelTrigger,
        RecordedDelivery,
        RecordedInputMessage,
        RoundResponse,
        StoryNote,
        StoryStanding,
        StorySummaryLine,
        StorySummaryState,
        ToolDefinition,
        UnderstandingReferent,
    )
    from ai_assistant.orchestration.matters import InProgressEntry
    from ai_assistant.orchestration.person_block import PersonBlock, ShownSuggestion
    from ai_assistant.orchestration.story_links import ShortView
    from ai_assistant.orchestration.task_scheduler import (
        ActivationEntry,
        ListedPlace,
        StillLive,
        TaskEntry,
        TaskListing,
    )

__all__ = [
    "ALREADY_ASKING",
    "APPROVED_ACTION_ARGUMENT",
    "APPROVED_ACTION_TOOL",
    "DELIBERATE_REPEAT",
    "LOOKING_FOR",
    "NOTHING_NEW",
    "OLDER_NOTES_PAGE_ARGUMENT",
    "PAGE_ARGUMENT",
    "PLANNING_PROMPT",
    "WAITING_ROUND",
    "ApprovedAction",
    "CallOutcome",
    "CallOutcomeKind",
    "DigestItem",
    "DigestedEvidence",
    "EpisodeRead",
    "EpisodeShown",
    "EpisodesFound",
    "FullViewPart",
    "MatterShown",
    "NewsShown",
    "OfferShown",
    "OlderHistory",
    "PeerShown",
    "PlaceAuthor",
    "PlaceItem",
    "PlaceWindow",
    "PlannedCall",
    "PlannedRound",
    "PlanningInputs",
    "PlanningStage",
    "PlanningStories",
    "PlanningStory",
    "PlanningWork",
    "RecordedCandidate",
    "RefusedCall",
    "RoundRecorder",
    "RunningShown",
    "ShowingLabels",
    "answer_fact",
    "call_showed",
    "exact_line",
    "full_view_parts",
    "offered_tools",
    "relayed_episodes",
    "shown_within",
]

_log = structlog.get_logger(__name__)

#: ADR-0306 §2:9's *looking for* argument, required where a result may carry outside text.
LOOKING_FOR: Final = "looking_for"

#: A story read's optional argument: which page of the story's older notes it shows, the
#: newest page 1 (#2893). Defined here, where the page saying how to ask for the next is
#: rendered, and declared by :data:`~ai_assistant.orchestration.lookups.READ_STORY`.
OLDER_NOTES_PAGE_ARGUMENT: Final = "older_notes_page"

#: The episode look-ups' optional argument: which page of the result to show, the first 1
#: (ADR-0358 §6:6). Defined here, where the line saying how to ask for the next page is
#: rendered, and declared by :mod:`~ai_assistant.orchestration.lookups`.
PAGE_ARGUMENT: Final = "page"

#: The story read's capability, :mod:`~ai_assistant.orchestration.lookups`'
#: ``READ_STORY_CAPABILITY``, which planning cannot import: the look-ups reach acting,
#: and planning never reaches the held results.
_READ_STORY: Final = "read_story"

#: ADR-0306 §2:9's *deliberate repeat* mark, offered where a capability is not safe to
#: repeat.
DELIBERATE_REPEAT: Final = "deliberate_repeat"

_LOOKING_FOR_SCHEMA: Final[dict[str, Any]] = {
    "type": "string",
    "description": (
        "What you are looking for in this call's result. Its result may carry text "
        "someone else wrote, which is read for you against what you say here."
    ),
}

_DELIBERATE_REPEAT_SCHEMA: Final[dict[str, Any]] = {
    "type": "boolean",
    "description": (
        "Set true only to make this call again on purpose, with the same values as a call "
        "already made in this matter. Otherwise such a call is refused as already done."
    ),
}

#: ADR-0321 §4:2: the tool an approved action is proposed through, by its A label alone.
#: Offered only where the activation has an approved action, and never a capability.
APPROVED_ACTION_TOOL: Final = "run_approved_action"

#: The approved-action tool's one argument of its own: the action's A label.
APPROVED_ACTION_ARGUMENT: Final = "action"

#: The arguments an exact line leaves out wherever a call carries them (ADR-0321 §2:5):
#: the *looking for* and the *deliberate repeat* mark. The declaration's
#: ``system_supplied`` are the third kind, read per capability.
_NEVER_SHOWN: Final = frozenset({LOOKING_FOR, DELIBERATE_REPEAT})

#: The top-level schema keywords the hub keeps true when it adds or removes an argument.
_TRANSFORMABLE: Final = frozenset(
    {
        "type",
        "properties",
        "required",
        "additionalProperties",
        "title",
        "description",
        "$schema",
        "$id",
        "$comment",
        "$defs",
        "definitions",
    }
)

#: The keywords that point elsewhere in a schema, which a removed property could dangle.
_REFERENCE_KEYWORDS: Final = frozenset({"$ref", "$dynamicRef", "$recursiveRef"})

#: How much of a label the model wrote a refusal's reason quotes back.
_QUOTED_LABEL_CHARS: Final = 32

#: Each kind of thing a label names, one and several, for a refusal's reason.
_THINGS: Final = {
    LabelKind.STORY: ("a story", "stories"),
    LabelKind.EPISODE: ("an episode", "episodes"),
    LabelKind.NOTE: ("a note", "notes"),
    LabelKind.MEMORY: ("a memory", "memories"),
    LabelKind.RESULT: ("a result", "results"),
    LabelKind.APPROVED_ACTION: ("an approved action", "approved actions"),
    LabelKind.SCHEDULED_TASK: ("a scheduled task", "scheduled tasks"),
    LabelKind.PLACE: ("a place", "places"),
}


# --- the inputs ------------------------------------------------------------------------


class PlaceAuthor(StrEnum):
    """Who wrote a place-window item, as the place records it."""

    USER = "user"
    ASSISTANT = "assistant"
    OTHER = "other"
    """Someone other than the user or the assistant: raw outside content, which planning
    is never shown (ADR-0307 §9:2)."""

    TASK_SCHEDULER = "task_scheduler"
    """The Task Scheduler, whose place window is a task's lineage, each step stated by the
    hub from the tasks it keeps (ADR-0350 §6:5)."""


@dataclass(frozen=True, slots=True)
class PlaceItem:
    """One item of the place window (ADR-0303 §7), as planning is shown it.

    Attributes:
        author: Who wrote it.
        text: What it says. Never shown where ``author`` is ``other``.
        at: When it was written, where the place records it.
        is_input: Whether it is the input this activation is processing, or part of it.
        episode_id: The id of the episode of the activation it links to, where it links
            to one (ADR-0303 §7:1); it is shown with that episode's label (§5:6).
        referent_id: The id understanding's referent names this item by, where the
            glue that builds the window knows it: a ``channel_item`` referent with this
            id is shown as this item (ADR-0307 §5:6) and never by its words.
        task_id: The scheduled task the item links to, where an activation the Task
            Scheduler started wrote it and the Task Scheduler still holds its task: it is
            shown with that task's ``T`` label beside its episode label (ADR-0350 §9:1-§9:2).
    """

    author: PlaceAuthor
    text: str
    at: datetime | None = None
    is_input: bool = False
    episode_id: str | None = None
    referent_id: str | None = None
    task_id: str | None = None


@dataclass(frozen=True, slots=True)
class PlaceWindow:
    """The place the input came from, and what planning is shown of it.

    Attributes:
        takes_message: Whether a round's text is written into the place. Where it is
            not, the text is kept with the episode and written nowhere (§3:8).
        description: The channel kind's description, with what the user said when
            setting the channel up (ADR-0292 §8:1), where there is one.
        items: The place window's items, oldest first.
    """

    takes_message: bool
    description: str | None = None
    items: tuple[PlaceItem, ...] = ()


@dataclass(frozen=True, slots=True)
class RecordedCandidate:
    """What a ``remember`` that recorded a candidate came back with (ADR-0329 §4, §6:5).

    Planning's own shape, filled by the phases' glue from the call's result and the
    memories it fetched by id (ADR-0282 §2:4).

    Attributes:
        similar: The memories similar to the candidate's fact, as planning fetched them,
            each shown under its own M label; ``None`` where the lookup failed, and the
            candidate is still recorded (§4:4).
    """

    similar: tuple[Memory, ...] | None


@dataclass(frozen=True, slots=True)
class CallOutcome:
    """What came of one call of an earlier round, from acting's record.

    Planning's own shape, because no phase module imports another (ADR-0309 §2:3): the
    lane that wires the phases fills it from acting's and authorizing's decisions.

    Attributes:
        round_id: The round that proposed the call.
        call_id: The provider's id for the call in that round.
        kind: What came of it.
        reason: Why it was not done or was refused, in code-owned words.
        result_id: For a done call that brought a result, the id acting minted for it,
            which its R label names (ADR-0307 §5:1, ADR-0308 §6:1). ``None`` where the
            call brought none, as for a capability whose result is none.
        result: What a done call returned, where its result goes to planning whole
            (ADR-0306 §5:14), JSON ``null`` included.
        digested: Whether the result, or its outside part, went to a digest instead
            (ADR-0306 §5:14). That reaches planning only as the
            :class:`DigestedEvidence` naming its ``result_id``, and ``result`` is then
            ``None``.
        records: For a memory search planning made (§6:6), its records whose source is
            not outside, as planning fetched them by id (ADR-0282 §2:4), each shown under
            its own M label; ``None`` for any other call. Its outside records went to a
            digest, and ``digested`` says so.
        story: For a story read planning made (§6:6), the story's full view as it was
            read; ``None`` for any other call.
        candidate: For a ``remember`` that recorded a candidate (ADR-0329 §4, §6:5),
            what its lookup found; ``None`` for any other call.
        request: For a call that needs the user, the request as authorizing ruled on
            it, with the values the hub filled in and its binding (ADR-0321 §2:8): what
            a question about it shows and records. ``None`` on every other outcome, and
            where none was handed on, in which case the call cannot be asked about.
        deliberate_repeat: Whether planning marked that call a deliberate repeat, as
            the asked call records it.
        already_asked: For a call identical to one still waiting on the user, the part
            of the question that asked about it (ADR-0321 §4:11): it is not asked about
            again.
        replaces: For a remember that needs the user, the assertions its question shows
            the new statement replacing (ADR-0321 §5:5), which the asked call records
            by id.
        worded: For a call that needs the user and names a memory by its id, such as a
            ``pin``, each such argument with the memory's wording as the store held it
            when this round was planned, which its exact line shows in place of the id
            (ADR-0338 §8:6). The asked call records the id.
        tasks: For a call on the Task Scheduler, a spawn, a cancel or a list pull, what
            it came back with, its tasks shown under ``T`` labels, its activations under
            their episodes' ``E`` labels and its places under ``L`` labels (ADR-0350
            §4:6-§4:8); ``None`` for any other call.
        peer: For a stop call, a look-up or an answer, the activation it named and
            what came of it, under that activation's ``E`` label (ADR-0349 §4:9,
            §4:11, §6:5-§6:6); ``None`` for any other call.
        delivered: For a message call that sent something, or tried to, what it sent,
            where it went and how (ADR-0356 §8:4); ``None`` for any other call.
        episodes: For a search of past episodes, what it found (ADR-0358 §7); ``None``
            for any other call.
        history: For a read of the origin's older history, the page it read (§9);
            ``None`` for any other call.
        full: For the episode look-up, the full record it read (§10); ``None`` for any
            other call.

    Raises:
        ValueError: If it carries a result, or says one was digested, without the
            result's id, or carries a raw result beside a digested one or a looked-up
            one; or if anything but a call that needs the user carries what a question
            about it would show, or it names replaced assertions without its request.
    """

    round_id: str
    call_id: str
    kind: CallOutcomeKind
    reason: str | None = None
    result_id: str | None = None
    result: FrozenJsonValue = None
    digested: bool = False
    records: tuple[Memory, ...] | None = None
    story: PlanningStory | None = None
    candidate: RecordedCandidate | None = None
    request: ActionRequest | None = None
    deliberate_repeat: bool = False
    already_asked: QuestionPart | None = None
    replaces: tuple[Memory, ...] = ()
    worded: tuple[tuple[str, str], ...] = ()
    tasks: TaskListing | None = None
    peer: PeerShown | None = None
    delivered: RecordedDelivery | None = None
    episodes: EpisodesFound | None = None
    history: OlderHistory | None = None
    full: EpisodeRead | None = None

    def __post_init__(self) -> None:
        """A result is shown under its label, so it carries the id the label names."""
        asking = (
            self.request is not None
            or self.deliberate_repeat
            or self.already_asked is not None
            or bool(self.replaces)
            or bool(self.worded)
        )
        if asking and self.kind is not CallOutcomeKind.NEEDS_YOU:
            msg = "only a call that needs the user carries what a question about it shows"
            raise ValueError(msg)
        if self.replaces and self.request is None:
            msg = "the assertions a question shows replaced ride the request it shows"
            raise ValueError(msg)
        if self.worded and self.request is None:
            msg = "the wording a question shows a memory by rides the request it shows"
            raise ValueError(msg)
        looked_up = (
            self.records is not None
            or self.story is not None
            or self.candidate is not None
            or self.tasks is not None
            or self.episodes is not None
            or self.history is not None
            or self.full is not None
        )
        if (self.result is not None or self.digested or looked_up) and self.result_id is None:
            msg = "a call's result carries the id acting minted for it (ADR-0308 §6:1)"
            raise ValueError(msg)
        if self.digested and self.result is not None:
            msg = "a digested result reaches planning only as its digest's evidence"
            raise ValueError(msg)
        if looked_up and self.result is not None:
            msg = "a looked-up result reaches planning as what was looked up"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class DigestItem:
    """One item of a digest's evidence (ADR-0308 §5:1).

    Attributes:
        text: What the item says.
        source_kind: What kind of record it rests on: a result, or a memory record.
        source_id: That record's id. The record is shown by its label (ADR-0308 §4:15).
    """

    text: str
    source_kind: LabelKind
    source_id: str


@dataclass(frozen=True, slots=True)
class DigestedEvidence:
    """One digest, as planning is shown it (ADR-0308 §4, §5): the seam B3 fills.

    Evidence rests on outside content, so each item is shown as such, with its source
    by label. An activation shown a digest that answered, with or without items, has
    read outside content (ADR-0308 §5:4). A failed digest shows no content: planning is
    told it could not read the result (§4:13).

    Attributes:
        result_id: The result digested, as a :class:`CallOutcome` names it, or ``None``
            for recall's digest.
        answered: Whether the digest answered; ``False`` where it failed.
        items: The evidence, empty where it failed or nothing answered the question.
        question: What the digest answered, where planning asked it: a call's *looking
            for*, which tells a follow-up's digest apart from the first one of the same
            result (ADR-0308 §6:7); ``None`` for recall's digest, which answers the
            understood meaning.
    """

    result_id: str | None
    answered: bool
    items: tuple[DigestItem, ...] = ()
    question: str | None = None

    def __post_init__(self) -> None:
        """A failed digest records no evidence (ADR-0308 §7's ``ActivationDigest``)."""
        if self.items and not self.answered:
            msg = "a failed digest carries no evidence"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class PlanningStory:
    """One story the activation belongs to, as planning is shown it (ADR-0307 §6:1).

    Assembled by the phases' glue under the pass's audience (§6:4), from the story's
    summary state, the short views of the stories it is part of and where its matter
    stands (§10); planning renders it and decides nothing about what may be shown.

    Attributes:
        story_id: The story.
        tidied_at: When its summary was last tidied, or ``None`` where it never was.
        changes: How many changes have come since: the notes and the episodes pending
            on it, one count (§6:3), counted whatever the audience may be shown.
        written: Whether a summary has been written.
        lines: The summary's lines, where it may be shown; empty otherwise.
        outside: The summary's mark, where it is shown (ADR-0303 §3:4).
        withheld: A summary was written and may not be shown, which the view says
            (ADR-0304 §4:2).
        notes: The notes newer than the summary, in the order written, where notes
            may be shown.
        notes_withheld: No note may be shown, and nothing is said of the notes
            (ADR-0305 §4).
        older: One page of its older notes, those a tidy-up has taken in, newest
            first, where a story read read them and notes may be shown (#2893); ``None``
            on every other view, which says nothing of them.
        older_page: Which page of the older notes ``older`` is, the newest page 1.
        older_more: How many older notes there are beyond ``older``'s page.
        newer: The episodes newer than the summary that the audience admits, newest
            first.
        latest: Its latest episodes that the audience admits, newest first.
        inherited: The short views of the stories it is part of (ADR-0300 §8).
        standing: Where its matter stands, for this pass's reader.
        summary_version: The version that wrote its summary, or ``None`` where none
            has been written, by which a call that showed it keeps it (ADR-0358 §11:2).
    """

    story_id: str
    tidied_at: datetime | None
    changes: int
    written: bool = False
    lines: tuple[StorySummaryLine, ...] = ()
    outside: bool = False
    withheld: bool = False
    notes: tuple[StoryNote, ...] = ()
    notes_withheld: bool = False
    older: tuple[StoryNote, ...] | None = None
    older_page: int = 1
    older_more: int = 0
    newer: tuple[EpisodicMemory, ...] = ()
    latest: tuple[EpisodicMemory, ...] = ()
    inherited: tuple[ShortView, ...] = ()
    standing: StoryStanding | None = None
    summary_version: int | None = None


@dataclass(frozen=True, slots=True)
class PlanningStories:
    """What planning is shown of stories (ADR-0307 §6:1).

    Attributes:
        stories: The stories the activation belongs to, as the story store holds its
            links when the round is planned.
        cited: The short views of the stories understanding cited as referents that
            the activation is not in (ADR-0304 §8), in the order cited.
        unreadable: The story store could not be read, so no story is shown, and
            planning is told so.
    """

    stories: tuple[PlanningStory, ...] = ()
    cited: tuple[ShortView, ...] = ()
    unreadable: bool = False


# --- what the episode look-ups bring (ADR-0358 §6-§10) ------------------------------------


@dataclass(frozen=True, slots=True)
class MatterShown:
    """A matter an episode a look-up showed belongs to, as planning may be shown it.

    ADR-0358 §8:1: read by ``StoryStore.stories_of``, shown by its ``S`` label and, the
    first time it is shown, its summary's first line, under ADR-0307 §6:4's rules for
    what an audience may be shown of a story. A story read again in the full view is
    shown the same way (§10:7).

    Attributes:
        story_id: The story.
        summary_version: The version that wrote its summary, or ``None`` where it has none.
        first_line: Its summary's first line, where the summary may be shown and has one.
        outside: The summary's mark, where the summary is shown (ADR-0303 §3:4).
        withheld: A summary was written and may not be shown (ADR-0304 §4:2).
    """

    story_id: str
    summary_version: int | None = None
    first_line: str | None = None
    outside: bool = False
    withheld: bool = False


@dataclass(frozen=True, slots=True)
class EpisodeShown:
    """One episode a look-up found, with the matters it belongs to (ADR-0358 §7:2, §8:1).

    Attributes:
        record: The episode, admitted by the pass's audience as it is held now.
        matters: The matters it belongs to, in the order the story store returned them.
    """

    record: EpisodicMemory
    matters: tuple[MatterShown, ...] = ()


@dataclass(frozen=True, slots=True)
class EpisodesFound:
    """What one search of past episodes found, one page of it (ADR-0358 §7, §6:6).

    Attributes:
        episodes: The page's episodes, best first.
        page: Which page this is, the first 1.
        more: Whether the search found more past this page.
        unbounded: The pass's audience is unbounded, so the search asked for no episode
            (§7:3).
    """

    episodes: tuple[EpisodeShown, ...] = ()
    page: int = 1
    more: bool = False
    unbounded: bool = False


@dataclass(frozen=True, slots=True)
class OlderHistory:
    """One page of the origin's older history (ADR-0358 §9), newest page first.

    Attributes:
        readable: Whether the place's older history can be read here: ``False`` where
            the place's kind has no window, or no member its store has reads it (§9:4).
        items: Where the window is read from the medium, the page's items, oldest first,
            each as the place window shows an item (§9:3).
        episodes: Where the window is the place's recent episodes, the page's earlier
            episodes, newest first, each admitted by the pass's audience (§9:2).
        page: Which page this is, the newest 1.
        more: Whether there is older history past this page.
        relayed: The episodes, among those its items link to, whose input their latest
            understanding marks relayed, where the mark counts: the user's items of one
            are outside, and withheld as a forward is (ADR-0351 §5:7, ADR-0358 §9:3).
    """

    readable: bool
    items: tuple[PlaceItem, ...] = ()
    episodes: tuple[EpisodicMemory, ...] = ()
    page: int = 1
    more: bool = False
    relayed: frozenset[str] = frozenset()

    def withheld(self, item: PlaceItem) -> bool:
        """Whether ``item`` is shown withheld: someone else's, or of a relayed input."""
        return item.author is PlaceAuthor.OTHER or (
            item.author is PlaceAuthor.USER and item.episode_id in self.relayed
        )


@dataclass(frozen=True, slots=True)
class EpisodeRead:
    """One episode's full record as the episode look-up read it (ADR-0358 §10).

    The projection is :func:`~ai_assistant.core.episode_encoding.project_episode`'s full
    view, under the pass's audience; every record it names by reference is read again
    when the look-up runs, as it is held now (§10:6), and one the store no longer holds,
    or the audience refuses, is absent from ``memories``, ``stories`` and ``episodes``.

    Attributes:
        episode_id: The episode the call named.
        record: The episode as held; ``None`` where the store no longer holds it, or it
            is still open and ``running`` says so.
        running: The episode is still open: its work is still running (§10:2).
        projection: Its full view, where ``record`` is held.
        memories: The memories the full view names, as held now, by id.
        stories: The stories the full view names, as held now, by id.
        matters: The matters the episode belongs to now, read by ``StoryStore.stories_of``
            (ADR-0358 §8:1).
        episodes: The other episodes the full view names that are still held.
        page: Which page of the full view this is, the first 1.
        page_size: How many of the full view's parts one page shows.
    """

    episode_id: str
    record: EpisodicMemory | None = None
    running: bool = False
    projection: EpisodeProjection | None = None
    memories: Mapping[str, Memory] = field(default_factory=dict)
    stories: Mapping[str, MatterShown] = field(default_factory=dict)
    matters: tuple[MatterShown, ...] = ()
    episodes: frozenset[str] = frozenset()
    page: int = 1
    page_size: int = 1

    def __post_init__(self) -> None:
        """A full view is read only of an episode held and frozen."""
        if (self.projection is None) != (self.record is None or self.running):
            msg = "a full view is carried exactly where a frozen episode is held"
            raise ValueError(msg)
        if self.page < 1 or self.page_size < 1:
            msg = "a full view's page and page size are at least 1"
            raise ValueError(msg)

    def parts(self) -> tuple[FullViewPart, ...]:
        """Every part of the full view, in the order they happened (§10:3)."""
        return () if self.projection is None else full_view_parts(self.projection)

    def page_parts(self) -> tuple[FullViewPart, ...]:
        """The parts this page shows."""
        start = (self.page - 1) * self.page_size
        return self.parts()[start : start + self.page_size]

    @property
    def more(self) -> bool:
        """Whether the full view has parts past this page."""
        return len(self.parts()) > self.page * self.page_size


type FullViewPart = (
    ProjectedRecall
    | ProjectedUnderstanding
    | ProjectedEvidence
    | ProjectedJoin
    | ProjectedRound
    | ProjectedCall
    | ProjectedProposal
)
"""One part of an episode's full view (ADR-0358 §10:3)."""


#: Where each kind of part goes among the parts placed before the same round, so the full
#: view shows them in the order they happened (ADR-0358 §10:3, ADR-0309 §3): recall's first
#: run before understanding's first version, its second run after it, then the digests'
#: evidence, an input taken in, a later understanding version, the round's notes, and its
#: calls by their index among the round's.
_AT_FIRST_RECALL: Final = 0
_AT_FIRST_VERSION: Final = 1
_AT_SECOND_RECALL: Final = 2
_AT_EVIDENCE: Final = 3
_AT_JOINED: Final = 4
_AT_LATER_VERSION: Final = 5
_AT_ROUND: Final = 6
_AT_CALL: Final = 7


def full_view_parts(projection: EpisodeProjection) -> tuple[FullViewPart, ...]:
    """An episode's full view's parts, in the order they happened (ADR-0358 §10:3).

    Each part is placed by the round before which it happened, as the projection
    numbers them, then by the phases' order within that place (ADR-0309 §3), and a
    round's calls, recorded or not, by their index among its calls. Empty for a
    projection that is not the full view, or that holds none of its parts, as on a
    pass that may not be shown a record placed for the owner alone (§10:5).

    Args:
        projection: The episode's full view.

    Returns:
        The parts, in order.
    """
    placed: list[tuple[tuple[int, int, int], FullViewPart]] = []
    for recall in projection.recalled:
        placed.append(((0, _AT_SECOND_RECALL if recall.second else _AT_FIRST_RECALL, 0), recall))
    for version in projection.understood:
        rank = _AT_FIRST_VERSION if version.version == 1 else _AT_LATER_VERSION
        placed.append(((version.position, rank, version.version), version))
    for at, item in enumerate(projection.evidence):
        placed.append(((item.position, _AT_EVIDENCE, at), item))
    for at, joined in enumerate(projection.joined):
        placed.append(((joined.position, _AT_JOINED, at), joined))
    for one in projection.rounds:
        placed.append(((one.position, _AT_ROUND, 0), one))
    for call in projection.calls:
        placed.append(((call.position, _AT_CALL, call.index), call))
    for proposal in projection.unrecorded:
        placed.append(((proposal.position, _AT_CALL, proposal.index), proposal))
    # A stable sort, so parts placed alike keep the order the record holds them in.
    placed.sort(key=lambda one: one[0])
    return tuple(part for _, part in placed)


def call_showed(
    outcome: CallOutcome,
    *,
    bound: int,
    owner_records: bool = True,
    labels: ShowingLabels | None = None,
    started: Sequence[PlanningStory] = (),
) -> CallShowed | None:
    """What a done call's result showed planning directly, as its entry keeps it.

    ADR-0358 §11:2-§11:4, read off planning's own rendering of the result
    (:meth:`_Request._result_value`), so it keeps what planning was shown and nothing a
    second walk of the result could miss: the result is rendered once with an empty
    label book, and every memory, episode and story the rendering names under a label
    is kept by its kind and id, in the order first shown, a story also by the summary
    version its view showed (§11:2). A record the rendering withholds takes no label,
    so it leaves nothing: a memory search keeps the records it showed and nothing of
    those its digest read, record by record (§11:3), and an activation's input or a
    task's words, which no record kind names, are never kept (§10:6). A result that goes
    to planning whole keeps its own words, as text; an older message, its words where
    planning was shown them. What is kept is cut to ``bound`` characters, a record
    counting its id's, and the cut is carried (§11:4).

    **The summary versions are read off a second rendering, under the labels planning
    holds** (``labels``): a story keeps the version the rendering first showed its
    summary at, so a matter planning already held a label for, which is shown by that
    label alone (§8:1), keeps none, and a page shows only what is on it. That rendering
    assigns labels as planning's does, so a batch of results rendered in turn over one
    ``labels`` reads each as planning is shown it after the ones before it.

    Args:
        outcome: What came of the call, carrying what its look-up found.
        bound: The composition root's bound on what an entry keeps (§11:4).
        owner_records: Whether the pass may be shown a record placed for the owner
            alone, which decides what a full view's page shows (§10:5).
        labels: The labels planning holds as the result is rendered, which the
            rendering adds to; ``None`` for none.
        started: The stories the call's report shows beside its result, the round's
            first story call done showing the stories it brought the activation into
            (:meth:`_Request._stories_started`); none for every other call.

    Returns:
        What it showed, or ``None`` for a call that was not done (§11:2).

    Raises:
        ValueError: If ``bound`` is below 1.
    """
    if bound < 1:
        msg = "an entry keeps at least one character of what its call showed"
        raise ValueError(msg)
    if outcome.kind is not CallOutcomeKind.DONE:
        return None
    looked = (
        outcome.records,
        outcome.story,
        outcome.candidate,
        outcome.tasks,
        outcome.peer,
        outcome.episodes,
        outcome.history,
        outcome.full,
    )
    parts: list[ShownText | ShownRecord] = []
    if all(one is None for one in looked):
        if not (outcome.digested or outcome.result is None):
            words = json.dumps(_thawed(outcome.result), ensure_ascii=False, sort_keys=True)
            parts.append(ShownText(text=words))
        if not started:
            return shown_within(parts, bound)
    history = outcome.history
    if history is not None:
        # An older message's words, as planning was shown them: a withheld one's never.
        parts.extend(
            ShownText(text=json.dumps({"from": item.author.value, "text": item.text}))
            for item in history.items
            if not history.withheld(item)
        )
    versions = _summary_versions(
        outcome,
        ShowingLabels() if labels is None else labels,
        started,
        owner_records=owner_records,
    )
    parts.extend(
        ShownRecord(
            kind=_SHOWN_KINDS[one.kind],
            id=one.id,
            summary_version=versions.get(one.id) if one.kind is LabelKind.STORY else None,
        )
        for one in _labelled(outcome, started, owner_records=owner_records)
        if one.kind in _SHOWN_KINDS
    )
    return shown_within(parts, bound)


#: The kinds of label whose thing an entry keeps by reference (ADR-0358 §10:6, §11:2).
_SHOWN_KINDS: Final = {
    LabelKind.MEMORY: ShownRecordKind.MEMORY,
    LabelKind.EPISODE: ShownRecordKind.EPISODE,
    LabelKind.STORY: ShownRecordKind.STORY,
}

#: What the rendering :func:`call_showed` reads labels from is given: no window, no
#: capability, and a clock nothing it renders reads.
_SHOWING_PLACE: Final = PlaceWindow(takes_message=False)
_SHOWING_AT: Final = datetime(2000, 1, 1, tzinfo=UTC)


class ShowingLabels:
    """The labels planning holds as results are rendered, for what each showed (§11:2).

    Seeded with the labels the activation holds, and added to as each result is
    rendered over it, as planning's own rendering assigns them.
    """

    def __init__(self, held: Sequence[PlanningLabel] = ()) -> None:
        """Start from the labels planning holds.

        Args:
            held: The labels the activation holds before the results are rendered.
        """
        self._book = _LabelBook(held)


def _rendering(
    outcome: CallOutcome,
    book: _LabelBook,
    started: Sequence[PlanningStory],
    *,
    owner_records: bool,
) -> _Request:
    """``outcome``'s result rendered over ``book``, as planning renders it.

    Then the stories its report shows beside it, ``started``, as
    :meth:`_Request._stories_started` renders them.
    """
    request = _Request(
        PlanningInputs(
            activation_id="showed",
            place=_SHOWING_PLACE,
            capabilities=(),
            owner_records=owner_records,
        ),
        book,
        excerpt_chars=1,
        now=_SHOWING_AT,
        zone=ZoneInfo("UTC"),
    )
    request._result_value(outcome)
    for one in started:
        request._story(one)
    return request


def _labelled(
    outcome: CallOutcome, started: Sequence[PlanningStory], *, owner_records: bool
) -> tuple[PlanningLabel, ...]:
    """Every thing the rendering of ``outcome``'s report names under a label, in order."""
    book = _LabelBook(())
    _rendering(outcome, book, started, owner_records=owner_records)
    return tuple(book.minted)


def _summary_versions(
    outcome: CallOutcome,
    labels: ShowingLabels,
    started: Sequence[PlanningStory],
    *,
    owner_records: bool,
) -> dict[str, int]:
    """The summary version each story's summary was first rendered at (ADR-0358 §11:2).

    Read off the rendering of ``outcome``'s result under the labels planning holds, so a
    story shown twice keeps the version it was first shown at, as it keeps its one
    label; a story whose summary is withheld showed none, and one named by its label
    alone, a matter planning already held a label for among them, showed none either.
    """
    rendered = _rendering(outcome, labels._book, started, owner_records=owner_records)
    return {key: value for key, value in rendered.summaries_shown.items() if value is not None}


def shown_within(parts: Sequence[ShownText | ShownRecord], bound: int) -> CallShowed:
    """What a call showed, ``parts``, cut to ``bound`` characters, the cut carried.

    ADR-0358 §11:4, the one cut every entry's addition takes.

    A text counts its characters and a record its id's, at least one; a text that does
    not fit whole keeps the prefix that does, where any of it does.
    """
    kept: list[ShownText | ShownRecord] = []
    left = bound
    for part in parts:
        cost = len(part.text) if isinstance(part, ShownText) else max(1, len(part.id))
        if cost <= left:
            kept.append(part)
            left -= cost
            continue
        if isinstance(part, ShownText) and part.text[:left].strip():
            kept.append(ShownText(text=part.text[:left]))
        return CallShowed(parts=tuple(kept), cut=True)
    return CallShowed(parts=tuple(kept))


@dataclass(frozen=True, slots=True)
class ApprovedAction:
    """One action the activation's yes approved, as planning is shown it (ADR-0321 §4:2).

    Planning's own shape, filled by the lane that wires the phases from understanding's
    answer pointer and the asking round's asked calls. Planning shows it under an A
    label and proposes it by that label alone.

    Attributes:
        part: The part of the question the yes approved: the asking round and the
            number of the call's exact line.
        call: The call that part asked about, as the asking round recorded it.

    Raises:
        ValueError: If the call is not the one recorded under that part's number.
    """

    part: QuestionPart
    call: AskedCall

    def __post_init__(self) -> None:
        """The call is the one the part names: its exact line carried that number."""
        if self.call.part != self.part.part:
            msg = "an approved action's call is the one recorded under its part"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class RunningShown:
    """A running activation, as an in-progress entry shows it (ADR-0349 §5:6, §7:26).

    Planning's own shape, filled by the phases from what crosses activations, and shown
    under the activation's episode label (§5:7).

    Attributes:
        activation_id: The activation, which its episode's ``E`` label names.
        place: What caused it: its channel and its place.
        input: What it took in, in brief; ``None`` where it is withheld.
        acted: Whether it has acted.
        parties: Whose words its trigger's input carries (ADR-0351 §2:1), which says
            that a withheld input is the assistant's; ``None`` where they are unknown.
        outside: Whether any input it holds is outside, read with its relay mark
            (ADR-0351 §5:7, §8:5), which says that a withheld input is outside.
    """

    activation_id: str
    place: ChannelIdentity
    input: str | None
    acted: bool
    parties: tuple[SupportHolder, ...] | None
    outside: bool = False


@dataclass(frozen=True, slots=True)
class OfferShown:
    """An offer open to this activation, as its planning is shown it (ADR-0349 §7:19).

    Attributes:
        activation_id: The offering activation, whose episode's ``E`` label names it.
        input: The offered input, in brief, as an in-progress entry shows input.
        meaning: The meaning the offering activation's understanding recorded.
    """

    activation_id: str
    input: str | None
    meaning: str


@dataclass(frozen=True, slots=True)
class PeerShown:
    """Another activation's own work, as planning is shown it (ADR-0349 §6:7-§6:10).

    The peer view of an activation this one absorbed, took input from or waited on, read
    fresh at each round (§7:10, §7:27), or what a stop call, a look-up or an answer came
    back with (§4:11, §6:5-§6:6, §7:20).

    Attributes:
        activation_id: The activation, which its episode's ``E`` label names.
        view: Its peer view; ``None`` where its episode could not be read.
        ended: Whether it has ended, a stop included (§4:10, §6:6).
        stopped: For a stop call, whether this call stopped it; ``None`` otherwise.
        absorbed_by: For a refused stop call, the activation that absorbed it (§4:9).
        answered: For an answer call, what it came to: ``taken``, ``declined`` or
            ``withdrawn``.
        not_as_asked: For an answer call, why it did not come to what it asked, where
            it did not (ADR-0352 §4:2); ``None`` otherwise.
        meaning: For an answer call, the meaning the offer carried, as its offering
            activation's understanding recorded it (ADR-0349 §7:19).
        set_up: For a stop call, what the activation set up that is still live below it
            (ADR-0352 §3:1-§3:6); ``None`` where nothing could have been set up, with no
            Task Scheduler wired.
    """

    activation_id: str
    view: PeerView | None = None
    ended: bool = False
    stopped: bool | None = None
    absorbed_by: str | None = None
    answered: str | None = None
    not_as_asked: NotAsAsked | None = None
    meaning: str | None = None
    set_up: StillLive | None = None


#: What an answer that did not come to what it asked came to, as planning is told it
#: beside the answer's result and in each call its round held back (ADR-0349 §7:22-§7:23,
#: ADR-0352 §4:2). ``{offering}`` is the work that offered the input.
_NOT_AS_ASKED: Final[Mapping[NotAsAsked, str]] = {
    NotAsAsked.STOPPED: (
        "{offering} was stopped before the answer, so the input it carried is no longer "
        "asked for, and the work that input asked for is not to be done"
    ),
    NotAsAsked.ENDED: (
        "{offering} ended before the answer, so the input it carried is no longer asked "
        "for, and the work that input asked for is not to be done"
    ),
    NotAsAsked.AT_LIMIT: (
        "the take was refused, since this work already holds as much input as it may, and "
        "counts as a decline: {offering} waits for this work to end, and then does the work "
        "of the input it carried itself"
    ),
    NotAsAsked.NO_OFFER: "the label it named names no offer open to this work",
    NotAsAsked.NOT_ALLOWED: "it was not allowed, so it settled nothing",
    NotAsAsked.NOT_DONE: "it was not done, so it settled nothing",
}
#: Which of them are shown beside an answer's result: what the hub settled, never a
#: decline planning chose, which would only echo its own words back (#3471).
_SHOWN_WITH_RESULT: Final = frozenset({NotAsAsked.STOPPED, NotAsAsked.ENDED, NotAsAsked.AT_LIMIT})


def answer_fact(why: NotAsAsked, *, offering: str) -> str:
    """What an answer that did not come to what it asked came to, in one clause.

    Args:
        why: Why it did not come to what it asked.
        offering: How the work that offered the input is named: its ``E`` label beside
            the answer's result, or in words in a held-back call's reason.

    Returns:
        The code-owned fact, naming the offering work by ``offering``.
    """
    return _NOT_AS_ASKED[why].format(offering=offering)


@dataclass(frozen=True, slots=True)
class PlanningInputs:
    """Everything one round is given (ADR-0307 §6, ADR-0312 §4).

    Attributes:
        activation_id: The activation being planned.
        place: The place the input came from, and its window.
        understanding: Understanding's latest record, where it recorded one.
        outside_trigger: Whether the trigger's input is outside, read with its relay mark
            (ADR-0351 §5:3, §5:7).
        episodes: The episode window's frozen episodes, in its order, as the pass's
            audience predicate already admitted them (ADR-0276 §4:9).
        recalled: What either recall run kept, as planning fetched it: the first run's
            records, then the second's, each in its run's order, as the pass's audience
            predicate admitted them (ADR-0308 §3, ADR-0282 §2:8).
        recalled_stories: The stories each found episode is in, by its id, as its run
            recorded them (``RecalledItem.stories``); shown by label alone (§3:2).
        owner_records: Whether a record placed for the owner alone may be shown on this
            pass. It decides the episode window's notes, never this activation's own.
        rounds: This activation's earlier rounds, as the episode records them.
        labels: The labels already assigned in this activation, as recorded.
        outcomes: What came of the earlier rounds' calls.
        capabilities: The tool declarations the offered capabilities come from.
        label_arguments: For a capability, which of its arguments name things by
            label, and what kind of thing each names.
        evidence: Digested evidence from earlier rounds' results.
        outside_content_read: Whether the activation's record already says it has read
            outside content (ADR-0306 §4:5), before this round's inputs.
        stories: The story views (§6:1), or ``None`` where no story store is wired,
            which shows no stories section.
        approved: The actions this activation's yes approved (ADR-0321 §4:2), each
            shown under an A label and proposed by it; none where its input approved
            nothing.
        pending: For an episode of the episode window the observer has not processed,
            by its id, the facts of the candidates its own rounds recorded, in order
            (ADR-0329 §6:9); none where nothing is pending.
        overtaken: The ids of earlier rounds that new input overtook before they acted
            (ADR-0332 §3:7, §3:12-§3:13): planned from an earlier understanding version,
            so their message was never written and nothing they asked about was shown.
            Each stays in ``rounds``, its text shown as not written, and what it asked
            about is not taken as asked (ADR-0321 §2:2).
        not_taken: The ids of earlier rounds whose acts were held back because an
            answer of theirs to an offer did not come to what it asked (ADR-0352 §4:2).
            Each is also in ``overtaken``, and its text is shown as not written for
            that reason.
        person: The activation's person block, less what the memory store no longer
            holds (ADR-0338 §7:3, §7:10): its five fields, its whole kept-in-mind slot
            and the pending suggestions it admits, shown always in mind. ``None``
            for an activation that is no person's or where no person-model store is
            wired, which shows none and leaves the instruction as it was.
        places: The activation's place list, as built for this round (ADR-0350
            §5:10-§5:12): each place under its channel's heading and its own ``L``
            label. ``None`` for an activation not offered spawn, which is shown none.
        offers: The offers open to this activation, shown at the start of each of its
            rounds (ADR-0349 §7:19).
        waiting: Where this round is a waiting round, each activation it waits on, as an
            in-progress entry shows it (§7:26); empty otherwise.
        declined: Each decline of this activation's offer, by the older that declined
            it, with its reason, shown to its waiting round (§7:23).
        earlier_work: The finished work of each activation this one absorbed or took
            input from, and, after a wait, of each it waited on, read fresh (§7:10,
            §7:27).
        work: The work's exchange as its last round left it (ADR-0356 §5), held by the
            phases for the work's life; ``None`` for a work's first round, which renders
            the briefing.
        not_here: For each capability offered whose condition for running does not
            hold in this activation or on this round, why (ADR-0356 §4:4-§4:6): a call
            to it comes back refused, saying so, and runs nothing.
        person_id: The person the activation is for, where it is a person's, which names
            them where no person block is shown (ADR-0353 §4:1); ``None`` otherwise.
        trigger: The activation's recorded trigger, whose messages and parties the
            stimulus is framed and attributed by (ADR-0353 §7, ADR-0356 §3:2).
        joined: Each input the activation took in after its trigger, in the order joined
            (ADR-0349 §7:7, §7:21), each framed as its own.
        received_at: When the trigger's input arrived, which its framing sentence says.
        running: The in-progress entries, newest first, as ADR-0349 §5 shows them
            (ADR-0353 §2:5-§2:7), each under its episode's ``E`` label.
        running_more: How many more run than ``running`` shows (ADR-0349 §5:10).
        episodes_read: Whether the pass reads an episode window at all (ADR-0276 §4:13),
            which an empty section's note says (ADR-0353 §8:1).
        still_held: Of the memories the work's exchange has shown, those the memory
            store still holds, re-read before a report; ``None`` on a first round, or
            where the store could not be read, which names none as forgotten.
        matters_now: Each matter the work's exchange has shown, by the story's id, as
            the story store holds it now, re-read before a report, or ``None`` where it
            no longer holds it; a matter left out is not compared.
        meanings: For each running activation ``running`` shows, the meaning its latest
            understanding recorded, where it recorded one, which the news names a newly
            started work by (ADR-0360).
        ended: For each activation the exchange showed as running that has ended since,
            its frozen episode as the pass's audience admits it, which the news shows as
            short-term memory would, or ``None`` where it is not yet frozen (ADR-0360).
        person_now: The person's profile and pins as the person-model store holds them
            now, re-read before a report, whose changes the news names (ADR-0360 §4);
            ``None`` on a first round, for no person, or where the store was not read.
    """

    activation_id: str
    place: PlaceWindow
    understanding: ActivationUnderstanding | None = None
    outside_trigger: bool = False
    episodes: tuple[EpisodicMemory, ...] = ()
    recalled: tuple[EpisodicMemory | Memory, ...] = ()
    recalled_stories: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    owner_records: bool = False
    rounds: tuple[PlanningRound, ...] = ()
    labels: tuple[PlanningLabel, ...] = ()
    outcomes: tuple[CallOutcome, ...] = ()
    capabilities: tuple[ToolDefinition, ...] = ()
    label_arguments: Mapping[str, Mapping[str, LabelKind]] = field(default_factory=dict)
    evidence: tuple[DigestedEvidence, ...] = ()
    outside_content_read: bool = False
    stories: PlanningStories | None = None
    approved: tuple[ApprovedAction, ...] = ()
    pending: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    overtaken: frozenset[str] = frozenset()
    not_taken: frozenset[str] = frozenset()
    person: PersonBlock | None = None
    places: tuple[ListedPlace, ...] | None = None
    offers: tuple[OfferShown, ...] = ()
    waiting: tuple[RunningShown, ...] = ()
    declined: tuple[tuple[str, str], ...] = ()
    earlier_work: tuple[PeerShown, ...] = ()
    work: PlanningWork | None = None
    not_here: Mapping[str, str] = field(default_factory=dict)
    person_id: str | None = None
    trigger: RecordedChannelTrigger | None = None
    joined: tuple[JoinedInput, ...] = ()
    received_at: datetime | None = None
    running: tuple[InProgressEntry, ...] = ()
    running_more: int = 0
    episodes_read: bool = True
    still_held: frozenset[str] | None = None
    matters_now: Mapping[str, StorySummaryState | None] = field(default_factory=dict)
    meanings: Mapping[str, str] = field(default_factory=dict)
    ended: Mapping[str, EpisodicMemory | None] = field(default_factory=dict)
    person_now: PersonNow | None = None


@dataclass(frozen=True, slots=True)
class MatterSeen:
    """What a work's exchange last showed of one matter, which the news compares against.

    Attributes:
        summary: The summary's lines as shown, or empty where none was shown.
        written: Whether a summary had been written.
        notes: The ids of its pending notes the exchange showed.
        merged_into: The story it had been merged into, or ``None``.
        written_at: When the summary shown was written, where the view says; ``None`` for
            a view that does not, whose summary is then compared by its words.
    """

    summary: tuple[str, ...] = ()
    written: bool = False
    notes: frozenset[int] = frozenset()
    merged_into: str | None = None
    written_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class PersonNow:
    """The person's profile and pins as the person-model store holds them now (ADR-0360 §4).

    Read before each round after a work's first, with no model call, beside ADR-0338
    §7:10's check, and compared with what the exchange showed; the block is not
    reassembled (§4:4).

    Attributes:
        profile: Their five fields.
        pinned: Each memory a pin now reaches, each once, as the slot resolves pins
            (ADR-0338 §4:8): the current memory its chain reaches, none resting on outside
            content, and the pass's audience applied (§6:4-§6:5).
    """

    profile: Profile
    pinned: tuple[Memory, ...] = ()


@dataclass(frozen=True, slots=True)
class NewsShown:
    """What a work's exchange has shown of the inputs the news reports on (ADR-0356 §5:5).

    Attributes:
        offers: The offering activations whose offers it showed as open.
        earlier_work: Each activation's finished work, by the activation, as last shown.
        understanding: The understanding version it showed, or ``None`` for none.
        items: The place-window items it showed.
        evidence: How many of the inputs' digests it showed, which are held in the order
            recorded.
        stories: The stories the activation belongs to that it showed, by id.
        memories: The memories it showed under an ``M`` label, by id, and not yet said
            to be forgotten: each is re-read before a report, and one the store no
            longer holds is named in the news (the owner's ruling on #3536).
        matters: What it last showed of each matter, by the story's id, which the news
            compares to the matter as it stands now.
        running: The activations it showed as concurrent stimuli, by id, which the news
            names once they end (ADR-0360).
        kept: The memories of the person block's slot it showed as pinned, by id.
        profile: The person's fields as it showed them, each by name, ``None`` not set.
        zone: The zone its briefing's situation named, in which every time of the work is
            written, whatever the person sets meanwhile (ADR-0360 §2:3).
    """

    offers: frozenset[str] = frozenset()
    earlier_work: Mapping[str, str] = field(default_factory=dict)
    understanding: int | None = None
    items: frozenset[PlaceItem] = frozenset()
    evidence: int = 0
    stories: frozenset[str] = frozenset()
    memories: frozenset[str] = frozenset()
    matters: Mapping[str, MatterSeen] = field(default_factory=dict)
    running: frozenset[str] = frozenset()
    kept: frozenset[str] = frozenset()
    profile: tuple[tuple[str, str | None], ...] = ()
    zone: str | None = None


@dataclass(frozen=True, slots=True)
class PlanningWork:
    """A work's exchange, as its last round left it (ADR-0356 §5, §6:4).

    Held only in memory, by the phases, for the work's life: never recorded in the
    episode and never on the wire. The next round appends to it the last round's
    response, as the completer returned it, and its report.

    Attributes:
        exchange: The exchange the last round was asked with.
        tools: The tools its first round was offered, which every round of it is, in
            the same order (ADR-0356 §4:3).
        response: The last round's response, its continuation included.
        round_id: The last round's id, which its calls' outcomes name.
        number: The last round's number in the work, from 1.
        shown: What the exchange has shown of the inputs the news reports on.
        askable: Every call the exchange has shown as needing the user's yes and not yet
            asked about, by the reference it was shown under, as the round and the call
            id its outcome names, which a later round's asking ``text`` call may name
            (ADR-0357 §8:1): the exchange is never re-rendered, so a reference shown
            rounds ago still stands. Its outcome is read afresh on each round.
    """

    exchange: PlanningExchange
    tools: tuple[OfferedTool, ...]
    response: RoundResponse
    round_id: str
    number: int
    shown: NewsShown
    askable: Mapping[str, tuple[str, str]] = field(default_factory=dict)


# --- the round's decision ----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PlannedCall:
    """A call that passed planning's check, as authorizing takes it.

    Attributes:
        call: The call with ids in place of labels, and without its *looking for* or
            *deliberate repeat* (ADR-0306 §2:10).
        looking_for: What planning said it is looking for, where the capability asks.
        deliberate_repeat: Whether planning marked it a deliberate repeat; for an
            approved action, whether the asked call was so marked.
        approved_part: For an approved action planning proposed by its label
            (ADR-0321 §4:2), the part of the question its yes approved; its call then
            carries the values recorded with the question, those the hub fills apart.
            ``None`` for every other call.
    """

    call: ProposedCall
    looking_for: str | None = None
    deliberate_repeat: bool = False
    approved_part: QuestionPart | None = None


@dataclass(frozen=True, slots=True)
class RefusedCall:
    """A call refused whole before authorizing, with its reason (ADR-0307 §5:3).

    Attributes:
        call: The call as proposed.
        reason: Why, in code-owned words, which the next round is shown.
    """

    call: ProposedCall
    reason: str


@dataclass(frozen=True, slots=True)
class PlannedRound:
    """Planning's decision for one round.

    Attributes:
        round: The round, as recorded or as it would have been.
        labels: The labels this round assigned, in order.
        recorded: Whether the episode writer's append of it returned.
        calls: The calls that go on to authorizing, in the round's order.
        refused: The calls refused whole, in the round's order.
        message: Always ``None``: a round's text is its notes and writes no message
            (ADR-0356 §7:3), and what people receive comes only from message calls.
        work: The work's exchange with this round's response, which the phases hold
            and hand the next round (ADR-0356 §5); ``None`` only where none was built.
        read_outside: Whether the work had read outside content when this round was
            asked, which marks each of its calls' entries (ADR-0356 §8:7).
        questions: The exact lines the round's asking ``text`` call carries, by its call
            id: one per call its ``asks`` named that the round records as asked, in their
            parts' order (ADR-0357 §8:2, ADR-0321 §2:5-§2:6); empty where the round asks
            about nothing.
    """

    round: PlanningRound
    labels: tuple[PlanningLabel, ...]
    recorded: bool
    calls: tuple[PlannedCall, ...] = ()
    refused: tuple[RefusedCall, ...] = ()
    message: str | None = None
    work: PlanningWork | None = None
    read_outside: bool = False
    questions: Mapping[str, str] = field(default_factory=dict)


class RoundRecorder(Protocol):
    """The seam onto the episode writer, for a round and the labels it assigned.

    ADR-0307 §2:3 to §2:4: a round is recorded once the episode writer's append of it has
    returned (ADR-0286 §3:1). Orchestration-local: the lane that wires the phases backs
    it with the activation's own writer, which appends both to the open episode.
    """

    async def record(
        self,
        planning_round: PlanningRound,
        labels: tuple[PlanningLabel, ...],
        *,
        questions: Mapping[str, str] | None = None,
    ) -> None:
        """Append ``planning_round`` and ``labels`` to the activation's open episode.

        Args:
            planning_round: The round, following the last one recorded.
            labels: The labels it assigned, after those already recorded.
            questions: The exact lines its asking ``text`` call carries, by call id, as
                :attr:`PlannedRound.questions` holds them, so the recorder can tell
                whether the question would be shown whole (ADR-0321 §4:4).
        """
        ...


# --- offering the capabilities -----------------------------------------------------------


def offered_tools(capabilities: Sequence[ToolDefinition]) -> tuple[OfferedTool, ...]:
    """The capabilities planning is offered, one tool each (ADR-0306 §2:7 to §2:9).

    A capability is offered only where every tool satisfying it declares the same five
    properties and the same schema, and where the schema is an object's that leaves
    room for the added arguments. Its description is its first tool's, by id.

    Args:
        capabilities: The tool declarations, any number per capability.

    Returns:
        One offered tool per capability that may be offered, by name.
    """
    grouped: dict[str, list[ToolDefinition]] = {}
    for tool in capabilities:
        grouped.setdefault(str(tool.capability), []).append(tool)
    offered: list[OfferedTool] = []
    for name in sorted(grouped):
        tools = sorted(grouped[name], key=lambda tool: str(tool.id))
        first = tools[0]
        if any(_declared(tool) != _declared(first) for tool in tools[1:]):
            _log.info("planning_capability_not_offered", stage="planning", reason="disagree")
            continue
        schema = _offered_schema(first)
        if schema is None:
            _log.info("planning_capability_not_offered", stage="planning", reason="schema")
            continue
        offered.append(OfferedTool(name=name, description=first.description, parameters=schema))
    return tuple(offered)


def _declared(tool: ToolDefinition) -> tuple[object, ...]:
    """What every tool of one capability must declare alike (ADR-0306 §2:7)."""
    return (
        tool.effect,
        tool.leaves_hub,
        tool.result,
        tool.outcome_can_be_unknown,
        tool.safe_to_repeat,
        tool.model_dump()["parameters_schema"],
        tuple(tool.system_supplied),
    )


def _offered_schema(tool: ToolDefinition) -> dict[str, Any] | None:
    """The declaration's schema with the added arguments, or ``None`` where it has no room.

    The hub changes a schema only where every rule in it is one it knows how to keep
    true: the properties, the required list and ``additionalProperties``. A schema
    carrying anything else at its top, a combinator, a conditional or a rule on the
    number or names of its properties, may forbid an argument the hub adds or require
    one it removes, so its capability is not offered rather than offered with
    arguments no call could satisfy. So is one carrying a reference anywhere, which a
    removed property could leave pointing at nothing, and one that already names an
    added argument, as a property, as required or as one the hub fills.
    """
    schema: dict[str, Any] = dict(tool.model_dump()["parameters_schema"])
    if schema.get("type", "object") != "object":
        return None
    added: dict[str, dict[str, Any]] = {}
    if tool.result is CapabilityResult.MAY_CARRY_OUTSIDE_TEXT:
        added[LOOKING_FOR] = dict(_LOOKING_FOR_SCHEMA)
    if not tool.safe_to_repeat:
        added[DELIBERATE_REPEAT] = dict(_DELIBERATE_REPEAT_SCHEMA)
    properties: dict[str, Any] = dict(schema.get("properties") or {})
    declared_required: list[str] = list(schema.get("required") or [])
    if set(added) & (set(properties) | set(declared_required) | set(tool.system_supplied)):
        return None
    if (added or tool.system_supplied) and (
        set(schema) - _TRANSFORMABLE or _references_anything(schema)
    ):
        return None
    required = [name for name in declared_required if name not in tool.system_supplied]
    for name in tool.system_supplied:
        properties.pop(name, None)
    properties.update(added)
    if LOOKING_FOR in added:
        required.append(LOOKING_FOR)
    schema.update({"type": "object", "properties": properties})
    if required:
        schema["required"] = required
    else:
        schema.pop("required", None)
    return schema


def _references_anything(value: object) -> bool:
    """Whether a JSON schema carries a reference keyword at any depth."""
    if isinstance(value, dict):
        return any(
            key in _REFERENCE_KEYWORDS or _references_anything(item) for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_references_anything(item) for item in value)
    return False


# --- labels ------------------------------------------------------------------------------


class _LabelBook:
    """The activation's labels: those recorded, and those this round assigns (§5:1)."""

    def __init__(self, recorded: Sequence[PlanningLabel]) -> None:
        self._by_label: dict[str, PlanningLabel] = {one.label: one for one in recorded}
        self._by_thing: dict[tuple[LabelKind, str], str] = {
            (one.kind, one.id): one.label for one in recorded
        }
        self._next: dict[LabelKind, int] = {
            kind: 1 + max((int(one.label[1:]) for one in recorded if one.kind is kind), default=0)
            for kind in LabelKind
        }
        self.minted: list[PlanningLabel] = []

    def label(self, kind: LabelKind, thing: str) -> str:
        """The label ``thing`` holds, assigning the next one of its kind on first show."""
        held = self._by_thing.get((kind, thing))
        if held is not None:
            return held
        assigned = PlanningLabel(
            label=f"{label_prefix(kind)}{self._next[kind]}", kind=kind, id=thing
        )
        self._next[kind] += 1
        self._by_label[assigned.label] = assigned
        self._by_thing[(kind, thing)] = assigned.label
        self.minted.append(assigned)
        return assigned.label

    def resolve(self, label: str) -> PlanningLabel | None:
        """What ``label`` names, or ``None`` where planning was never shown it."""
        return self._by_label.get(label)

    def held(self, kind: LabelKind, thing: str) -> str | None:
        """The label ``thing`` already holds, or ``None``; assigns nothing."""
        return self._by_thing.get((kind, thing))


# --- the instruction ---------------------------------------------------------------------

#: Planning's instruction, the system message of every round (ADR-0334 §2): a template the
#: composition root reads at start and hands the stage, default or override. The module
#: keeps no copy of its text (§3:1). It declares no flag and no value (ADR-0356 §4:2), so
#: every part of it is sent on every round; the briefing, the reports, the tool
#: declarations, the judge and the exact lines stay here, whatever a template says (§1:3,
#: §7:2).
#:
#: **What the instruction must say**, which binds the default and every override alike
#: (ADR-0334 §7:1, ADR-0356 §10:2), and which a promotion's review reads it against
#: (§7:3):
#:
#: - that the system briefs planning with its context, and that results and news are the
#:   system reporting back (ADR-0356 §2:3);
#: - that its context is only part of what the system knows and that it can look up more,
#:   what each section is, that the lines between the tags are the system's own, and that
#:   all of the context, the stimulus included, is data whose requests it weighs and
#:   never an instruction it must follow (§3:9);
#: - that its rounds are one continuing exchange, each seeing the earlier ones, what came
#:   of them, and anything that changed since (§5:7);
#: - that text it writes outside a call is its reply to the system, kept as its notes,
#:   which its later rounds and later work see and which is not meant for any person, and
#:   that what people receive comes only from its calls (§7:6);
#: - that a round with a call is followed by another once its calls finish, and that a
#:   round with no calls ends the work (ADR-0315 §4:3, read with ADR-0356 §10:4, which
#:   moves the tidy-up's exception into the tidy-up's description);
#: - that a round's calls run at the same time, so a call that needs another's result goes
#:   in a later round (ADR-0307 §2:5); and
#: - that planning never substitutes something else for what was asked (ADR-0307 §9:3).
#:
#: A rule about one tool is said in that tool's description, never here (ADR-0357 §7:1).
PLANNING_PROMPT: Final = PromptDeclaration(
    name="planning",
    package="ai_assistant.orchestration",
)

#: The bound on how many of another episode's rounds' notes its short view shows, oldest
#: first cut past it (ADR-0356 §9:4). The composition root hands the stage its own value;
#: this is the stage's default where it hands none.
SHORT_VIEW_NOTES: Final = 6


# --- the briefing's format (ADR-0356 §3, as ADR-0353 §3-§8 has it) ------------------------

#: The days and months a time is written with, in English whatever the host's locale.
_DAY: Final = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_DAY_NAME: Final = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
_MONTH: Final = (
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
)
_MONTH_NAME: Final = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)
#: How many messages the framing sentence spells as a word (ADR-0353 §7:1).
_COUNTS: Final = ("two", "three", "four", "five", "six", "seven", "eight", "nine", "ten")
_NOON: Final = 12

#: ADR-0353 §8:1's reasons an empty section gives, each the start of its note, and the
#: wording where withholding alone may have emptied it (§8:2).
_NOTHING_THERE: Final = "Nothing is there"
_NOTHING_SHOWN: Final = "Nothing is shown"
_NOT_PROVIDED: Final = "The origin does not provide it"
_NOT_HELD: Final = "The system does not have it"
_UNREADABLE: Final = "It could not be read"
#: Every note's opening, by which a reader tells which reason a note gives (ADR-0356 §4:1).
NOTE_REASONS: Final = (_NOTHING_THERE, _NOTHING_SHOWN, _NOT_PROVIDED, _NOT_HELD, _UNREADABLE)

#: What the system is called in every tag, attribute and line (ADR-0353 §4:2).
_SYSTEM: Final = "the system"
#: An unknown party, named as unknown (§4:3, §7:2).
_UNKNOWN: Final = "an unknown sender"
#: The person the system serves, where they have set no name (§4:1).
_UNNAMED: Final = "the owner"
#: Another person, whom no block names (§4:1).
_SOMEONE: Final = "a person the system knows"

#: The section headings, in the order the briefing renders them (ADR-0356 §3:1).
_STIMULUS: Final = "# The stimulus"
_UNDERSTANDING: Final = "# Understanding"
_KNOWLEDGE: Final = "# Knowledge"
_SITUATION: Final = "## The situation"
_ORIGIN_KNOWLEDGE: Final = "## Stimulus origin knowledge"
_CONCURRENT: Final = "## Concurrent stimuli"
_MEMORY: Final = "# Memory"
_ALWAYS: Final = "## Always in mind"
_SHORT_TERM: Final = "## Short-term memory"
_LONG_TERM: Final = "## Long-term memory"
_RECALLED: Final = "### Recalled memories"
_MATTERS: Final = "### Matters"
_ORIGIN_MEMORY: Final = "## Stimulus origin memory"
#: Every heading, in order: the briefing is these sections and nothing else (§3:1).
BRIEFING_HEADINGS: Final = (
    _STIMULUS,
    _UNDERSTANDING,
    _KNOWLEDGE,
    _SITUATION,
    _ORIGIN_KNOWLEDGE,
    _CONCURRENT,
    _MEMORY,
    _ALWAYS,
    _SHORT_TERM,
    _LONG_TERM,
    _RECALLED,
    _MATTERS,
    _ORIGIN_MEMORY,
)

#: Where a part shown in another section is, as an empty tag's ``shown_in`` names it
#: (ADR-0356 §3:2, §9:1): pointed at, never shown again.
_IN_ORIGIN_KNOWLEDGE: Final = "stimulus origin knowledge"
_IN_ORIGIN_MEMORY: Final = "stimulus origin memory"
_IN_THE_STIMULUS: Final = "the stimulus"
_IN_CONCURRENT: Final = "concurrent stimuli"

#: The news's opening line, after the round's results (ADR-0356 §5:5, §17).
NEWS_OPENING: Final = "Since the last round:"
#: The news of a report where nothing changed since the round before (ADR-0356 §5:5).
NOTHING_NEW: Final = "Nothing else has changed since the last round."


def _escaped(value: str) -> str:
    """``value`` escaped as a text tag's content: nothing in it reads as a tag or heading.

    ``&``, ``<`` and ``>`` become character references everywhere, and a ``#`` that
    begins a line, after any indentation, becomes one too (ADR-0353 §3:5).
    """
    escaped = value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return "\n".join(
        f"{line[: len(line) - len(line.lstrip())]}&#35;{line.lstrip()[1:]}"
        if line.lstrip().startswith("#")
        else line
        for line in escaped.split("\n")
    )


def _one_line(value: str) -> str:
    """``value`` on one line: every run of whitespace, line breaks included, one space."""
    return " ".join(value.split())


def _attribute(value: str) -> str:
    """``value`` as an attribute's: on one line, ``"`` escaped as well (§3:5)."""
    return _escaped(_one_line(value)).replace('"', "&quot;")


def _line(value: str) -> str:
    """A record's value placed in a line between the tags: on one line, escaped (§3:5)."""
    return _escaped(_one_line(value))


def _tag(name: str, attributes: Sequence[tuple[str, str]], text: str | None) -> str:
    """One text tag, its attributes escaped, its text escaped, or empty where ``None``."""
    written = "".join(f' {key}="{_attribute(value)}"' for key, value in attributes)
    if text is None:
        return f"<{name}{written}/>"
    return f"<{name}{written}>{_escaped(text)}</{name}>"


def _container(name: str, attributes: Sequence[tuple[str, str]], tags: Sequence[str]) -> list[str]:
    """A container and the tags it holds, which carries no text of its own (§3:3).

    A container holding nothing is written empty, as an empty tag is.
    """
    written = "".join(f' {key}="{_attribute(value)}"' for key, value in attributes)
    if not tags:
        return [f"<{name}{written}/>"]
    held = [f"  {line}" for one in tags for line in one.split("\n")]
    return [f"<{name}{written}>", *held, f"</{name}>"]


def _clock(local: datetime) -> str:
    """A clock time as the briefing writes it: ``3:51 pm``."""
    hour = local.hour % _NOON or _NOON
    return f"{hour}:{local.minute:02d} {'am' if local.hour < _NOON else 'pm'}"


def _long_day(local: datetime) -> str:
    """A day written in full: ``Monday 26 October 2026``."""
    return f"{_DAY_NAME[local.weekday()]} {local.day} {_MONTH_NAME[local.month - 1]} {local.year}"


def _upper(words: str) -> str:
    """``words`` with its first letter capitalised, to begin a line."""
    return words[:1].upper() + words[1:]


def _count(number: int) -> str:
    """How many messages, as the framing sentence says it."""
    return _COUNTS[number - 2] if 2 <= number <= len(_COUNTS) + 1 else str(number)  # noqa: PLR2004 — "two" is the first spelled


def _origin_name(channel: ChannelIdentity | None) -> str:
    """How an origin is named (ADR-0353 §4:4): its kind's name, or its type as recorded."""
    kind = None if channel is None else origin_kind(channel.channel_type)
    if kind is not None:
        return kind.name
    return "an origin the record does not name" if channel is None else channel.channel_type


def _origin_where(channel: ChannelIdentity | None) -> str:
    """An origin's name with the preposition its kind declares, or ``on`` and its type."""
    kind = None if channel is None else origin_kind(channel.channel_type)
    if kind is not None:
        return kind.where
    return (
        "at an origin the record does not name" if channel is None else f"on {channel.channel_type}"
    )


def _words_tag(parties: Sequence[SupportHolder] | None, *, relayed: bool = False) -> str:
    """The text tag words of these parties sit in (ADR-0353 §3:2, ADR-0351 §5).

    ``said`` for the person's own, ``task`` for the assistant's statement, ``received``
    for every other: outside, mixed, or unknown, and words a relay mark that counts makes
    outside (ADR-0351 §5:4, §5:7).
    """
    if relay_mark_counts(parties, relayed=relayed):
        return "received"
    if parties and all(one.kind is HolderKind.PERSON for one in parties):
        return "said"
    if parties and all(one.kind is HolderKind.ASSISTANT_STATEMENT for one in parties):
        return "task"
    return "received"


def _ended(status: object, reason: object) -> str | None:
    """An episode's status and reason, as ``ended=`` writes them (ADR-0284 §8:6)."""
    if status is None or reason is None:
        return None
    said = str(getattr(status, "value", status)).replace("_", " ")
    why = str(getattr(reason, "value", reason)).replace("_", " ")
    return said if why == said else f"{said}, {why}"


@dataclass(frozen=True, slots=True)
class _Naming:
    """Who the stimulus is for, and how each party is named (ADR-0353 §4).

    Attributes:
        person_id: The person the stimulus is for, or ``None`` where it is no person's.
        name: Their name, as the person block holds it, or ``None`` where it is not set
            or no block was assembled.
    """

    person_id: str | None
    name: str | None

    @property
    def who(self) -> str:
        """The person the stimulus is for, named, or in words that stay true (§4:1)."""
        if self.name:
            return self.name
        return _UNNAMED if self.person_id in {None, OWNER_PERSON_ID} else _SOMEONE

    def person(self, identifier: str | None) -> str:
        """A person, by the block's name where the block is theirs (§4:1)."""
        if identifier == self.person_id or (
            identifier == OWNER_PERSON_ID and self.person_id is None
        ):
            return self.who
        return _UNNAMED if identifier == OWNER_PERSON_ID else _SOMEONE

    def party(self, holder: SupportHolder) -> str:
        """One party, named by what its record holds, never by its text (§4:3)."""
        if holder.kind is HolderKind.PERSON:
            return self.person(holder.identifier)
        if holder.kind is HolderKind.ASSISTANT_STATEMENT:
            return _SYSTEM
        if holder.kind is HolderKind.OUTSIDE_SOURCE and holder.identifier:
            return f"{holder.identifier}, as claimed" if holder.claimed else holder.identifier
        return _UNKNOWN

    def parties(self, parties: Sequence[SupportHolder] | None) -> str:
        """Every party of an input, named, or unknown where they are not known (§4:3)."""
        if not parties:
            return _UNKNOWN
        named = list(dict.fromkeys(self.party(one) for one in parties))
        return named[0] if len(named) == 1 else f"{', '.join(named[:-1])} and {named[-1]}"

    def forward(self, sender: ClaimedAuthor) -> str:
        """A forward's original sender, as the medium named them, claimed (§4:3)."""
        return f"{sender.name}, as claimed" if sender.name.strip() else _UNKNOWN

    def author(self, author: PlaceAuthor) -> str:
        """Who wrote a place-window item, by its record (§4:1-§4:3)."""
        if author is PlaceAuthor.USER:
            return self.who
        if author is PlaceAuthor.OTHER:
            return f"someone other than {self.who} or the system"
        return _SYSTEM


@dataclass(frozen=True, slots=True)
class _Words:
    """One text of the stimulus section: its tag, writer, time and text (ADR-0353 §7)."""

    tag: str
    writer: str
    at: datetime | None
    text: str
    forward: bool = False


# --- the rendered request -------------------------------------------------------------------

_NO_UNDERSTANDING: Final = "missing: understanding recorded no reading of this input"
#: A channel item understanding named that the place window cannot be shown pointing at.
_SOME_ITEM: Final = "an item of the place window"

#: ADR-0308 §4:13: a failed digest records no evidence, and planning is told so.
_DIGEST_FAILED: Final = "could not be read: its digest failed, and its content is not shown"
_NOTHING_ANSWERED: Final = "nothing in it answered what was looked for"
_RECALL_DIGEST: Final = "the outside memories recall found"
_DIGESTED_RESULT: Final = "read for you by a digest, under evidence"
_NONE_FOUND: Final = "none"
#: An ended step of the Task Scheduler's that wrote no message anywhere (#3445).
_WROTE_NO_MESSAGE: Final = "wrote no message"
_NO_OLDER: Final = "none on this page"
_NOTHING_DONE: Final = "nothing recorded"

#: A digested result whose digest has not yet been recorded: its evidence comes as news.
_NOT_YET_READ: Final = "not read yet: its digest's evidence comes as news once it is"
#: How one text is made of several messages: the chat's input of the messages it took in
#: (``ChatInput.text``) and an episode's response of the messages it wrote
#: (``PhaseWorking.outcome``) each join them with it. Were either to join otherwise, a
#: text would no longer match its items and would be shown again, never dropped.
_JOINED: Final = "\n\n"
_TIDY_STARTED: Final = (
    "started: it runs on its own, and how it went is recorded on the story, not here"
)

#: What was done, by where it stands (ADR-0300 §8:1).
_EFFECT_TEXT: Final = {
    StoryEffectState.UNKNOWN: "unknown: it may or may not have happened",
    StoryEffectState.NOT_DONE: "not done",
    StoryEffectState.DONE: "done",
}

_RELATION_TEXT: Final = {
    StoryRelation.PART_OF: "part of",
    StoryRelation.CONTAINS: "contains",
}

#: A memory's standing in plain words (ADR-0328 §6:1, §15:5).
_STANDING_TEXT: Final = {
    MemoryStanding.CONFIRMED: "confirmed as worded",
    MemoryStanding.SAID: "as said",
    MemoryStanding.SOURCE: "from a source, not anyone's word",
    MemoryStanding.INFERENCE: "worked out by the system",
}

#: A reading certainty no backing support carries (ADR-0328 §7:5).
_NOT_JUDGED: Final = "not judged"

#: Where a cited message was said, when the window holds no label for its episode.
_SAID_ELSEWHERE: Final = "an earlier exchange"


def _holder_text(holder: SupportHolder, naming: _Naming) -> str:
    """Whose belief a support records, in plain words (ADR-0345 §12:3)."""
    match holder.kind:
        case HolderKind.PERSON:
            return naming.person(holder.identifier)
        case HolderKind.OUTSIDE_SOURCE if holder.claimed:
            return f"a forward claimed to come from {holder.identifier}"
        case HolderKind.OUTSIDE_SOURCE:
            return f"the source {holder.identifier}"
        case HolderKind.ASSISTANT_STATEMENT:
            return "the system's own words"
        case _:
            return "an unknown source"


#: ADR-0329 §6:5, read with ADR-0358 §2:3: what a candidate's result tells planning. Nothing
#: tells it not to say a fact is saved, since the observer reads every episode.
_CANDIDATE_PENDING: Final = (
    "recorded as a candidate for long-term memory: the observer decides whether and how it "
    "is kept once this episode leaves the window"
)

#: ADR-0329 §4:4: a lookup that failed leaves the candidate recorded, and says so.
_SIMILAR_UNREAD: Final = "could not be read; the candidate is still recorded"

#: An instant nothing dates (ADR-0328 §7:3-§7:4): unknown, neither fresh nor stale.
_UNKNOWN_INSTANT: Final = "unknown"


def _ordinal(number: int) -> str:
    """``number`` as an English ordinal: 1st, 2nd, 3rd, 4th, 11th, 21st."""
    suffix = (
        "th" if number % 100 in {11, 12, 13} else {1: "st", 2: "nd", 3: "rd"}.get(number % 10, "th")
    )
    return f"{number}{suffix}"


def _looks(item: PlaceItem) -> tuple[PlaceAuthor, datetime | None, str | None]:
    """What the place window shows of an item that a reference to it can name."""
    return item.author, item.at, item.episode_id


#: The authors whose items show nothing of an episode's own exchange (ADR-0276 §3): one
#: someone else wrote is never shown, and a lineage step is the hub's statement of a
#: step, never its messages (ADR-0350 §6:5).
_NOT_AN_EXCHANGE: Final = frozenset({PlaceAuthor.OTHER, PlaceAuthor.TASK_SCHEDULER})

_OUTCOME_TEXT: Final = {
    CallOutcomeKind.DONE: "done",
    CallOutcomeKind.NOT_DONE: "not done",
    CallOutcomeKind.UNKNOWN: (
        "unknown: it may or may not have happened, and it is reported as unknown"
    ),
    CallOutcomeKind.REFUSED: (
        "refused before it ran, so nothing in it ran, and no yes lets it run: never ask about it"
    ),
}

#: How a short view's ``did`` says each outcome (ADR-0356 §9:2).
_DID_TEXT: Final = {
    CallOutcomeKind.DONE: "Done",
    CallOutcomeKind.NOT_DONE: "Not done",
    CallOutcomeKind.UNKNOWN: "Its outcome is unknown",
    CallOutcomeKind.REFUSED: "Refused",
    CallOutcomeKind.NEEDS_YOU: "It needed a yes",
}

#: ADR-0321 §2:10, fitted to the asking ``text`` call (ADR-0357 §8:1-§8:2): which case of
#: a call needing the person applies, each said with its outcome.
_NEEDS_YES: Final = (
    "needs a yes, and is not yet asked, even where an earlier message mentioned it: to ask, "
    "make a text call that explains it in your own words and names it in that call's asks "
    "by its ask_as reference, and the system adds its exact details after your words. "
    "Leave it unasked only where it is no longer wanted"
)
#: ADR-0321 §7:3: where nothing can be asked.
_NO_ONE_TO_ASK: Final = (
    "needs a yes, and this activation cannot ask anyone, so it will not run and is not asked about"
)
#: §4:11, and a call an earlier round of this activation already asked about: either
#: way a question that showed its exact line (#3071). #3072: waiting is not approved.
_ALREADY_ASKED: Final = (
    "already asked about, in a question that showed its exact details, and waiting on the "
    "answer, so it is not asked about again. It is not approved: never say it is going "
    "through or being done"
)
#: A call that needs a yes but whose request was not handed on cannot be shown exactly,
#: so it is never asked about (§2:5).
_UNSHOWABLE: Final = "needs a yes, and it cannot be asked about, so it will not run"


def _not_replacing(count: int) -> str:
    """What planning is told of the replaced assertions that rest on outside content."""
    facts = "remembered fact" if count == 1 else "remembered facts"
    return (
        f"{count} {facts} resting on outside content, which this question cannot show "
        "and a yes will not replace"
    )


#: §4:2: how an approved action came to be approved.
_APPROVED_BY: Final = "by a yes in this input, to the question that showed it"

#: What a peer view's reader is told where the episode could not be read (§6:7).
_PEER_UNREAD: Final = "could not be read"
#: ADR-0352 §3:1: a stop call's result where the stopped activation set up nothing live.
_NOTHING_SET_UP: Final = "nothing it set up is still live"
#: Where what it set up could not be read: the stop stands, and nothing is claimed of it.
_SET_UP_UNREAD: Final = "could not be read, so nothing is known of what it set up"
#: ADR-0352 §3:4: an activation pushed from a task and not yet admitted.
_STARTING: Final = "starting"


@dataclass
class _Shown:
    """What one round's rendering showed that bears on its own record."""

    marked: bool = False


@dataclass
class _PlaceTexts:
    """What the place window shows of one episode, by who wrote it (ADR-0276 §3)."""

    user: list[str] = field(default_factory=list)
    assistant: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class _InPlace:
    """Which of an episode's texts the place window shows whole (ADR-0276 §3, #2951).

    Attributes:
        input: Its input.
        messages: The rounds recorded before ADR-0356 whose message it shows whole, by
            their position among the episode's rounds.
        delivered: The message calls whose delivered words it shows whole, by their
            round's position and their place among its calls.
        section: The section the window renders in, which a pointer names.
    """

    input: bool = False
    messages: frozenset[int] = frozenset()
    delivered: frozenset[tuple[int, int]] = frozenset()
    section: str = _IN_ORIGIN_KNOWLEDGE


def _withheld_tag(tag: str, writer: str) -> str:
    """An item whose words are withheld, as ADR-0353 §2:7 renders one (ADR-0356 §3:6)."""
    return _tag(tag, [("from", writer), ("withheld", "yes")], None)


class _Request:
    """One round's briefing or report, assigning labels as it shows things."""

    def __init__(  # noqa: PLR0913 — the inputs, the labels, the bound, the clock, the zone and whose it is, and the notes' bound
        self,
        inputs: PlanningInputs,
        book: _LabelBook,
        *,
        excerpt_chars: int,
        now: datetime,
        zone: ZoneInfo,
        own_zone: bool = False,
        notes_bound: int = SHORT_VIEW_NOTES,
    ) -> None:
        self._inputs = inputs
        self._book = book
        self._excerpt_chars = excerpt_chars
        self._now = now
        self._zone = zone
        self._own_zone = own_zone
        self._notes_bound = notes_bound
        person = inputs.person
        self._naming = _Naming(
            person_id=inputs.person_id if person is None else person.person_id,
            name=None if person is None else person.profile.value(ProfileField.NAME),
        )
        trigger = inputs.trigger
        self._origin: ChannelIdentity | None = None if trigger is None else trigger.channel
        if (
            trigger is not None
            and self._origin is None
            and isinstance(trigger.target, NewConversation)
        ):
            # A conversation the store allocates on admission: the hub chat, not yet named.
            self._origin = ChannelIdentity(channel_type="conversation", instance_id="new")
        kind = None if self._origin is None else origin_kind(self._origin.channel_type)
        # ADR-0353 §2: a window the origin's kind builds from episodes is the system's
        # memory of the origin, and one read from the medium is knowledge.
        self._remembered = kind is not None and kind.remembered
        self.shown = _Shown()
        # The calls this round may ask about, by the reference each is shown with
        # (ADR-0321 §2:3), filled as results are rendered.
        self.askable: dict[str, CallOutcome] = {}
        # The calls this activation's earlier rounds asked about, by their round's number:
        # a round new input overtook asked nothing (ADR-0332 §3:7, ADR-0321 §2:2), and nor
        # did one whose asking ``text`` call was not sent (ADR-0357 §8).
        self._asked_before: tuple[tuple[int, AskedCall], ...] = tuple(
            (number, asked)
            for number, one in enumerate(inputs.rounds, 1)
            if one.id not in inputs.overtaken and _question_sent(one, inputs.outcomes)
            for asked in one.asked
        )
        self._reads_stories = False
        # Each earlier work's view as rendered, by its activation, which the news compares
        # to what the exchange showed (ADR-0356 §5:5).
        self._peers_rendered: dict[str, str] = {}
        # The episodes rendered so far, so one shown again is pointed at by its label.
        self._rendered: set[str] = set()
        # The summary version each story was first rendered with a summary at, or
        # ``None`` where its summary was withheld, in the order rendered; a story named
        # by its label alone is not here (ADR-0358 §11:2).
        self.summaries_shown: dict[str, int | None] = {}
        # The memories and the matters rendered so far, which the news later re-reads.
        self._memories: set[str] = set()
        self._matters: dict[str, MatterSeen] = {}
        # Each running activation understanding cited, named once the briefing is
        # rendered (ADR-0353 §14:1).
        self._running_cited: list[str] = []
        # What the place window shows of each episode it links to (ADR-0276 §3).
        self._in_place: dict[str, _PlaceTexts] = {}
        self._relayed = relayed_episodes(
            (*inputs.episodes, *inputs.recalled), excerpt_chars=excerpt_chars
        )
        self._by_referent: dict[str, tuple[PlaceItem, int, int]] = {}
        alike = Counter(_looks(item) for item in inputs.place.items)
        seen: Counter[tuple[PlaceAuthor, datetime | None, str | None]] = Counter()
        for item in inputs.place.items:
            seen[_looks(item)] += 1
            if item.referent_id is not None:
                self._by_referent[item.referent_id] = (
                    item,
                    seen[_looks(item)],
                    alike[_looks(item)],
                )
        for item in inputs.place.items:
            if (
                item.episode_id is None
                or item.author in _NOT_AN_EXCHANGE
                or self._relayed_item(item)
            ):
                continue
            texts = self._in_place.setdefault(item.episode_id, _PlaceTexts())
            (texts.user if item.author is PlaceAuthor.USER else texts.assistant).append(item.text)

    # --- times ---

    def _at(self, instant: datetime) -> str:
        """An instant in full, in the work's zone: ``Mon 26 Oct 2026, 9:12 am`` (§5:1)."""
        local = instant.astimezone(self._zone)
        return (
            f"{_DAY[local.weekday()]} {local.day} {_MONTH[local.month - 1]} {local.year}, "
            f"{_clock(local)}"
        )

    def _at_or_unknown(self, instant: datetime | None) -> str:
        return _UNKNOWN_INSTANT if instant is None else self._at(instant)

    # --- the briefing (ADR-0356 §3) ---

    def briefing(self, offered: Sequence[OfferedTool]) -> str:
        """The briefing: every section of §3:1, in order, under its heading, as text."""
        inputs = self._inputs
        self._reads_stories = _offers_story_reads(offered)
        # Rendered in the order labels are minted: what is shown first takes the first
        # label of its kind. The understanding names what it cites by those labels, so it
        # is rendered last and placed second.
        stimulus = self._stimulus()
        situation = self._situation()
        always = self._always_in_mind()
        knowledge, origin_memory = self._origin_sections()
        concurrent = self._concurrent()
        short_term = self._short_term()
        recalled = self._recalled()
        matters = self._matters_section()
        origin_memory = origin_memory + self._origin_episodes()
        understanding = self._understanding()
        sections = [
            _STIMULUS,
            *stimulus,
            "",
            _UNDERSTANDING,
            *understanding,
            "",
            _KNOWLEDGE,
            "",
            _SITUATION,
            *situation,
            "",
            _ORIGIN_KNOWLEDGE,
            *(knowledge or [self._knowledge_note()]),
            "",
            _CONCURRENT,
            *concurrent,
            "",
            _MEMORY,
            "",
            _ALWAYS,
            *always,
            "",
            _SHORT_TERM,
            *(short_term or [self._short_term_note()]),
            "",
            _LONG_TERM,
            _RECALLED,
            *recalled,
            "",
            _MATTERS,
            *matters,
            "",
            _ORIGIN_MEMORY,
            *(origin_memory or [self._origin_memory_note()]),
        ]
        del inputs
        return "\n".join(sections)

    def shown_now(self) -> NewsShown:
        """What the briefing just rendered showed of what the news reports on (§5:5)."""
        inputs = self._inputs
        return NewsShown(
            offers=frozenset(one.activation_id for one in inputs.offers),
            earlier_work=dict(self._peers_rendered),
            understanding=None if inputs.understanding is None else inputs.understanding.version,
            items=frozenset(inputs.place.items),
            evidence=len(inputs.evidence),
            stories=frozenset(one.story_id for one in self._stories_held()),
            memories=frozenset(self._memories),
            matters=dict(self._matters),
            running=self._running_shown(),
            kept=frozenset()
            if inputs.person is None
            else frozenset(one.id for one in inputs.person.pinned),
            profile=_profile_of(None if inputs.person is None else inputs.person.profile),
            zone=self._zone.key,
        )

    def _running_shown(self) -> frozenset[str]:
        """The activations the concurrent stimuli section shows, by id."""
        inputs = self._inputs
        return frozenset(
            {
                *(one.activation_id for one in inputs.running),
                *(one.activation_id for one in inputs.offers),
                *(one.activation_id for one in inputs.waiting),
            }
        )

    def _stories_held(self) -> tuple[PlanningStory, ...]:
        """The stories the activation belongs to, as this round's inputs hold them."""
        given = self._inputs.stories
        return () if given is None or given.unreadable else given.stories

    # --- the stimulus (ADR-0353 §7) ---

    def _stimulus(self) -> list[str]:
        """Every input the activation holds, the trigger's then each joined one, framed.

        The work's own stimulus, where understanding marks it relayed, is shown, carrying
        ``relayed="yes"`` (ADR-0356 §3:7); an input outside by its parties, and a joined
        input that is relayed, is withheld (§3:6).
        """
        inputs = self._inputs
        trigger = inputs.trigger
        parties = None if trigger is None else trigger.parties
        relayed = inputs.understanding is not None and inputs.understanding.relayed
        words = self._trigger_words(trigger, parties)
        # Withheld by its record's parties; with no record there is none to read. Where the
        # record holds each message with its own party, each is judged by its own (a
        # forward's sender, ADR-0351 §2:6-§2:7), and the person's own words are shown.
        by_message = trigger is not None and bool(trigger.messages)
        withheld = trigger is not None and not by_message and parties_are_outside(parties)
        shown_relayed = relayed and not withheld and relay_mark_counts(parties, relayed=True)
        at = inputs.received_at
        if at is None:
            at = next((one.at for one in words if one.at is not None), self._now)
        lines = self._framed(
            self._origin,
            parties,
            words,
            at=at,
            withheld=withheld,
            relayed=shown_relayed,
            withhold_received=by_message,
        )
        if withheld or (by_message and any(one.tag == "received" for one in words)):
            self.shown.marked = True
        for one in inputs.joined:
            joined_parties = _known_parties(one.messages)
            joined_words = [self._recorded_message(message) for message in one.messages]
            hidden = parties_are_outside(joined_parties) or relay_mark_counts(
                joined_parties, relayed=one.relayed
            )
            lines.append("")
            lines.extend(
                self._framed(
                    one.channel,
                    joined_parties,
                    joined_words,
                    at=one.messages[0].sent_at,
                    taken_over=one.taken_over_from is not None,
                    withheld=hidden,
                )
            )
        return lines

    def _trigger_words(
        self,
        trigger: RecordedChannelTrigger | None,
        parties: tuple[SupportHolder, ...] | None,
    ) -> list[_Words]:
        """The trigger's words: its recorded messages, else its input text, else the items."""
        if trigger is not None and trigger.messages:
            return [self._recorded_message(one) for one in trigger.messages]
        # ADR-0349 §6:6: what the pass took in, as the place window holds it, before the
        # text the activation was admitted with, which may hold a message since deleted.
        items = [
            one.text
            for one in self._inputs.place.items
            if one.is_input and one.author is PlaceAuthor.USER
        ]
        if items:
            tag = "said" if trigger is None else _words_tag(parties)
            writer = self._naming.who if trigger is None else self._naming.parties(parties)
            return [_Words(tag=tag, writer=writer, at=None, text=_JOINED.join(items))]
        text: str | None = None
        if trigger is not None:
            payload = trigger.payload
            text = payload.text if isinstance(payload, RecordedTextInput) else payload.transcript
        if not text:
            return []
        return [
            _Words(
                tag=_words_tag(parties), writer=self._naming.parties(parties), at=None, text=text
            )
        ]

    def _recorded_message(self, message: RecordedInputMessage) -> _Words:
        """One recorded message of an input, attributed by its own party (ADR-0351 §2:6)."""
        party = None if message.party is None else (message.party,)
        if message.forwarded_from is not None:
            return _Words(
                tag="received",
                writer=self._naming.forward(message.forwarded_from),
                at=message.sent_at,
                text=message.text,
                forward=True,
            )
        return _Words(
            tag=_words_tag(party),
            writer=self._naming.parties(party),
            at=message.sent_at,
            text=message.text,
        )

    def _framed(  # noqa: PLR0913 — the origin, the parties, the texts, when, and the clauses a sentence may add
        self,
        channel: ChannelIdentity | None,
        parties: Sequence[SupportHolder] | None,
        words: Sequence[_Words],
        *,
        at: datetime,
        taken_over: bool = False,
        withheld: bool = False,
        relayed: bool = False,
        withhold_received: bool = False,
    ) -> list[str]:
        """One input's framing sentence and its tagged content (ADR-0353 §7:1-§7:5).

        ``withhold_received`` withholds each text whose own party is outside, a forward's
        among them (ADR-0356 §3:6), and shows the rest.
        """
        local = at.astimezone(self._zone)
        what, content = self._what(channel, parties, words)
        if taken_over:
            what += ", taken in from other work, which was stopped"
        opening = f"A stimulus reached the system at {_clock(local)} on {_long_day(local)}: {what}"
        if content is None or not words:
            return [f"{opening}."]
        several = len(words) > 1
        verb = "They contain" if several else "It contains"
        lines = [f"{opening}. {verb} {content}:"]
        for one in words:
            attributes = [("from", one.writer)]
            if one.at is not None:
                attributes.append(("at", self._at(one.at)))
            if withheld or (withhold_received and one.tag == "received"):
                lines.append(_tag(one.tag, [*attributes, ("withheld", "yes")], None))
                continue
            if relayed:
                attributes.append(("relayed", "yes"))
            lines.append(_tag(one.tag, attributes, one.text))
        return lines

    def _what(
        self,
        channel: ChannelIdentity | None,
        parties: Sequence[SupportHolder] | None,
        words: Sequence[_Words],
    ) -> tuple[str, str | None]:
        """The framing sentence's ``{what}`` and ``{content}`` (§7:1's table), from records."""
        kind = None if channel is None else origin_kind(channel.channel_type)
        where = _line(_origin_where(channel))
        if parties is not None and not parties:
            return f"an input with no one's words in it arrived {where}", None
        if kind is not None and kind.act:
            return self._sent(kind, where, words)
        content = kind.content if kind is not None else "this text"
        if parties and all(one.kind is HolderKind.ASSISTANT_STATEMENT for one in parties):
            return "a step of scheduled work came due", content
        if parties and all(one.kind is HolderKind.OUTSIDE_SOURCE for one in parties):
            return f"a report from {_line(self._naming.parties(parties))}", content
        if len(words) > 1:
            return f"{_count(len(words))} inputs {where}", "these messages"
        return f"an input {where}", content

    def _sent(self, kind: OriginKind, where: str, words: Sequence[_Words]) -> tuple[str, str]:
        """``{what}`` for a message a person sends: what they did, and how many (§7:1)."""
        forwards = sum(one.forward for one in words)
        if words and forwards == len(words):
            act = "forwarded"
        elif forwards:
            act = f"{kind.act} or forwarded"
        else:
            act = kind.act
        who = _line(self._naming.who)
        if len(words) > 1:
            return f"{_count(len(words))} messages {who} {act} {where}", "these messages"
        return f"a message {who} {act} {where}", kind.content

    # --- the understanding (ADR-0353 §14:1, ADR-0356 §3:2) ---

    def _understanding(self) -> list[str]:
        """The latest understanding: its meaning, citations, unclear points and belonging."""
        understanding = self._inputs.understanding
        lines = (
            [f"{_NOT_HELD}: understanding recorded no reading of this stimulus."]
            if understanding is None
            else self._understood_lines(understanding)
        )
        if self._inputs.approved:
            # ADR-0321 §4:2: what this stimulus's yes approved, each under its A label.
            lines.append("- Approved by a yes in this stimulus:")
            lines.extend(f"  {self._approved(one)}" for one in self._inputs.approved)
        return lines

    def _understood_lines(self, understanding: ActivationUnderstanding) -> list[str]:
        """One understanding's ``understanding`` tag, ``unclear`` containers and belonging line."""
        belongs = [
            self._book.label(LabelKind.STORY, one.id)
            if one.kind is StoryMemberKind.STORY
            else self._book.label(LabelKind.EPISODE, episode_address(one.id))
            for one in understanding.story_links
        ]
        cites = [
            label
            for one in understanding.meaning_referents
            if (label := self._referent(one)) is not None
        ]
        attributes = [("from", _SYSTEM)]
        if cites:
            attributes.append(("cites", " ".join(dict.fromkeys(cites))))
        lines = [_tag("understanding", attributes, understanding.meaning)]
        for point in understanding.unclear:
            lines.extend(
                _container(
                    "unclear",
                    [("from", _SYSTEM), ("gap", point.gap)],
                    [_tag("reading", [("from", _SYSTEM)], one) for one in point.readings],
                )
            )
        if belongs:
            lines.append(f"- Belongs to: {', '.join(belongs)}.")
        else:
            lines.append("- Belongs to: nothing yet; it starts something new.")
        return lines

    def _referent(self, referent: UnderstandingReferent) -> str | None:
        """A cited item by its label, where it names a thing planning may name.

        A channel item is named by the episode label its item carries, where it links to
        one, and otherwise by none: an item of the place window carries no label. Running
        work is named by the label another part of the exchange gave its episode, and by
        none where nothing names it (ADR-0353 §14:1, §10:6).
        """
        kinds = {
            "story": LabelKind.STORY,
            "episode": LabelKind.EPISODE,
            "memory": LabelKind.MEMORY,
        }
        if referent.kind == "running":
            if referent.id is None:
                return None
            return self._book.held(LabelKind.EPISODE, referent.id)
        kind = kinds.get(referent.kind)
        if kind is not None and referent.id is not None:
            return self._book.label(kind, referent.id)
        if referent.kind == "channel_item" and referent.id is not None:
            found = self._by_referent.get(referent.id)
            if found is not None and found[0].episode_id is not None:
                return self._book.label(LabelKind.EPISODE, found[0].episode_id)
        return None

    # --- the situation (ADR-0353 §6, ADR-0356 §3:2, ADR-0357 §2:13) ---

    def _situation(self) -> list[str]:
        """Now with the zone, the person's last stimulus, the origin, and the place list."""
        local = self._now.astimezone(self._zone)
        now = f"{_long_day(local)}, {_clock(local)}"
        naming = self._naming
        who = _line(naming.who)
        zone = _line(self._zone.key)
        if self._own_zone:
            first = (
                f"- Now: {now}, in {who}'s time zone ({zone}). Every time below is in this zone."
            )
        elif naming.person_id is not None and self._inputs.person is not None:
            first = (
                f"- Now: {now}, in the hub's time zone ({zone}). {_upper(who)} has not set a "
                "time zone, so every time below is in the hub's zone."
            )
        elif naming.person_id is not None:
            first = (
                f"- Now: {now}, in the hub's time zone ({zone}). The system holds no time zone "
                f"of {who}'s, so every time below is in the hub's zone."
            )
        else:
            first = (
                f"- Now: {now}, in the hub's time zone ({zone}). This stimulus is no person's, "
                "so every time below is in the hub's zone."
            )
        last = self._last()
        if naming.person_id is None:
            second = "- Last stimulus: this stimulus is no person's, so no earlier one is named."
        elif last is None:
            second = (
                f"- {_upper(who)}'s last stimulus: the system holds none earlier than this one."
            )
        else:
            second = f"- {_upper(who)}'s last stimulus: {self._at(last[0])}, {_line(last[1])}."
        reply = (
            "A reply can be written there."
            if self._inputs.place.takes_message
            else "No reply can be written there."
        )
        kind = None if self._origin is None else origin_kind(self._origin.channel_type)
        name = _origin_name(self._origin)
        if kind is None:
            third = f"- The origin: {_line(name)}; the system has no description of it. {reply}"
        else:
            described = kind.described.replace("{person}", who)
            third = f"- The origin: {name}, {described}. {reply}"
        lines = [first, second, third]
        description = self._inputs.place.description
        if description:
            # ADR-0292 §8:1: how a reply is shown there, which is planning's to know.
            lines.append(f"- What the origin's kind says of it: {_line(description)}")
        return [*lines, *self._place_list()]

    def _last(self) -> tuple[datetime, str] | None:
        """The newest earlier stimulus for the same person among what the pass holds (§6:2)."""
        person = self._naming.person_id
        if person is None:
            return None
        inputs = self._inputs
        before = inputs.received_at or self._now
        found: list[tuple[datetime, str]] = [
            (item.at, _origin_where(self._origin))
            for item in inputs.place.items
            if item.at is not None and item.author is PlaceAuthor.USER and not item.is_input
        ]
        for record in (*inputs.episodes, *inputs.recalled):
            if not isinstance(record, EpisodicMemory) or record.processing_record is None:
                continue
            trigger = record.processing_record.trigger
            if activation_person(trigger) == person and parties_are_persons_own(trigger.parties):
                found.append((record.occurred_at, _origin_where(trigger.channel)))
        found.extend(
            (entry.arrived_at, _origin_where(entry.channel))
            for entry in inputs.running
            if entry.arrived_at is not None
        )
        earlier = [one for one in found if one[0] < before]
        return max(earlier, key=lambda one: one[0]) if earlier else None

    def _place_list(self) -> list[str]:
        """The place list, after the origin's line: each place under its channel's heading.

        ADR-0357 §2:13: each place carries its ``L`` label, so a ``text`` call's ``via`` can
        name one. Where the pass holds no list, the line says so.
        """
        places = self._inputs.places
        if places is None:
            return [
                "- Places a message can be sent by its label: the system holds no place list "
                "for this stimulus, so a text call goes where its tool chooses."
            ]
        if not places:
            return ["- Places a message can be sent by its label: none."]
        lines = ["- Places a message can be sent by its label:"]
        grouped: dict[str, list[ListedPlace]] = {}
        for one in places:
            grouped.setdefault(one.heading, []).append(one)
        for heading, held in grouped.items():
            lines.append(f"  - {_line(heading)}:")
            for one in held:
                attributes = [
                    ("label", self._book.label(LabelKind.PLACE, one.place)),
                    ("from", _SYSTEM),
                ]
                if one.suggested:
                    attributes.append(("suggested", "yes"))
                lines.append(f"    {_tag('place', attributes, one.description)}")
        return lines

    # --- the origin's window (ADR-0353 §2, ADR-0356 §3:2) ---

    def _origin_sections(self) -> tuple[list[str], list[str]]:
        """The place window, as origin knowledge or as origin memory by its kind.

        Read from the medium, it is knowledge, and each item linking to an episode
        carries that episode's ``E`` label. Built from episodes, it is memory, and each
        item that is one exchange with an episode the pass holds is rendered once, as
        that episode's short view.
        """
        items = self._inputs.place.items
        if not self._remembered:
            return [line for item in items for line in self._item(item)], []
        held = {
            record.id: record
            for record in (*self._inputs.episodes, *self._inputs.recalled)
            if isinstance(record, EpisodicMemory)
        }
        lines: list[str] = []
        for item in items:
            record = None if item.episode_id is None else held.get(item.episode_id)
            if record is not None and item.author not in _NOT_AN_EXCHANGE:
                if record.id not in self._rendered:
                    task = (
                        ()
                        if item.task_id is None
                        else (("task", self._book.label(LabelKind.SCHEDULED_TASK, item.task_id)),)
                    )
                    lines.extend(self._episode(record, in_place=None, extra=task))
                continue
            lines.extend(self._item(item))
        return [], lines

    def _item(self, item: PlaceItem) -> list[str]:
        """One item of the place window, as a ``message`` tag by who wrote it."""
        attributes = [("from", self._naming.author(item.author))]
        if item.at is not None:
            attributes.append(("at", self._at(item.at)))
        if item.episode_id is not None:
            attributes.append(("episode", self._book.label(LabelKind.EPISODE, item.episode_id)))
        if item.task_id is not None:
            # ADR-0350 §9:2: the scheduled task it links to, beside its episode label.
            attributes.append(("task", self._book.label(LabelKind.SCHEDULED_TASK, item.task_id)))
        if item.is_input:
            # The stimulus itself, shown in its own section and pointed at here.
            return [_tag("message", [*attributes, ("shown_in", _IN_THE_STIMULUS)], None)]
        if item.author is PlaceAuthor.OTHER or self._relayed_item(item):
            # ADR-0356 §3:6: someone else's words, and a relayed input's, are withheld.
            return [_tag("message", [*attributes, ("withheld", "yes")], None)]
        return [_tag("message", attributes, item.text)]

    def _relayed_item(self, item: PlaceItem) -> bool:
        """Whether ``item`` is the person's message of an input its episode marks relayed.

        ADR-0351 §5:7: such an input is outside, and is withheld as a forward is
        (ADR-0307 §9:2); the work's own stimulus is the one exception (ADR-0356 §3:7),
        which the window points at rather than shows.
        """
        return item.author is PlaceAuthor.USER and item.episode_id in self._relayed

    def _knowledge_note(self) -> str:
        """Origin knowledge's note where it renders nothing (ADR-0353 §8:1)."""
        name = _line(_origin_name(self._origin))
        if self._remembered:
            return (
                f"{_NOT_PROVIDED}: {name} gives the system no history of this chat, so what "
                "the system remembers of it is under stimulus origin memory."
            )
        if self._origin is None or not self._inputs.place.takes_message:
            return f"{_NOTHING_SHOWN}: the origin supplied nothing around this stimulus."
        return f"{_NOTHING_THERE}: the origin holds nothing around this stimulus."

    def _origin_memory_note(self) -> str:
        """Origin memory's note where it renders nothing (ADR-0353 §8:1)."""
        if not self._inputs.episodes_read and not self._remembered:
            return f"{_NOT_HELD}: the system's memory of this origin is not read for this stimulus."
        return f"{_NOTHING_SHOWN}: the system remembers nothing else of this origin to show here."

    def _at_origin(self, record: EpisodicMemory) -> bool:
        processing = record.processing_record
        return (
            self._origin is not None
            and processing is not None
            and processing.trigger.channel == self._origin
        )

    def _window_episodes(self) -> list[EpisodicMemory]:
        """The episode window's frozen episodes, in its order."""
        return [
            record
            for record in self._inputs.episodes
            if record.processing_record is None or not record.processing_record.is_open
        ]

    def _origin_episodes(self) -> list[str]:
        """The episode window's episodes at the origin that origin knowledge does not render.

        An episode the knowledge window shows items of is shown in short-term memory,
        pointing at those items (ADR-0356 §3:2, §9:1); one it shows nothing of, recorded at
        the stimulus's origin, is shown here.
        """
        lines: list[str] = []
        for record in self._window_episodes():
            if record.id in self._rendered or not self._at_origin(record):
                continue
            if not self._remembered and record.id in self._in_place:
                continue
            lines.extend(self._episode(record, in_place=None))
        return lines

    # --- concurrent stimuli (ADR-0349 §5, ADR-0353 §2:5-§2:7, ADR-0356 §3:2) ---

    def _concurrent(self) -> list[str]:
        """Each running activation under its episode's ``E`` label, and how many more.

        An offer open to the work is marked ``offered="yes"`` with what it was understood
        to mean (ADR-0349 §7:19); on a waiting round, each activation the work waits on is
        marked ``waited_on="yes"``, with the decline's reason (§7:26).
        """
        inputs = self._inputs
        offers = {one.activation_id: one for one in inputs.offers}
        waited = {one.activation_id: one for one in inputs.waiting}
        lines: list[str] = []
        done: set[str] = set()
        for entry in inputs.running:
            tags = [self._entry_input(one) for one in _entry_inputs(entry)]
            lines.extend(
                self._running_container(
                    entry.activation_id,
                    entry.channel,
                    entry.arrived_at,
                    acted=entry.acted,
                    outside=entry.outside,
                    tags=tags,
                    offer=offers.get(entry.activation_id),
                    waited=entry.activation_id in waited,
                )
            )
            done.add(entry.activation_id)
        for one in inputs.offers:
            if one.activation_id not in done:
                lines.extend(self._offer_lines(one))
                done.add(one.activation_id)
        for shown in inputs.waiting:
            if shown.activation_id in done:
                continue
            tag = (
                _withheld_tag(_words_tag(shown.parties), self._naming.parties(shown.parties))
                if shown.input is None
                else _tag(
                    _words_tag(shown.parties),
                    [("from", self._naming.parties(shown.parties))],
                    shown.input,
                )
            )
            lines.extend(
                self._running_container(
                    shown.activation_id,
                    shown.place,
                    None,
                    acted=shown.acted,
                    outside=shown.outside,
                    tags=[tag],
                    offer=None,
                    waited=True,
                )
            )
        if inputs.running_more:
            lines.append(
                f"{inputs.running_more} more are running, older than those above, and are not "
                "shown."
            )
        if lines:
            return lines
        if self._naming.person_id is None:
            return [
                f"{_NOT_HELD}: concurrent stimuli are shown only for a stimulus that is a person's."
            ]
        return [f"{_NOTHING_SHOWN}: no other stimulus is running that can be shown here."]

    def _running_container(  # noqa: PLR0913 — the activation, where and when, what it did, what it took in, and how this work is tied to it
        self,
        activation_id: str,
        channel: ChannelIdentity,
        arrived_at: datetime | None,
        *,
        acted: bool,
        outside: bool,
        tags: Sequence[str],
        offer: OfferShown | None,
        waited: bool,
    ) -> list[str]:
        """One concurrent stimulus, as a ``stimulus`` container."""
        attributes = [
            ("label", self._book.label(LabelKind.EPISODE, episode_address(activation_id))),
            ("origin", _origin_name(channel)),
        ]
        if arrived_at is not None:
            attributes.append(("at", self._at(arrived_at)))
        attributes.append(("acted", "yes" if acted else "no"))
        if outside:
            attributes.append(("outside", "yes"))
        held = list(tags)
        if offer is not None:
            attributes.append(("offered", "yes"))
            held.append(_tag("understood", [("from", _SYSTEM)], offer.meaning))
        if waited:
            attributes.append(("waited_on", "yes"))
            reasons = [why for older, why in self._inputs.declined if older == activation_id]
            if reasons:
                attributes.append(("declined", reasons[-1]))
        return _container("stimulus", attributes, held)

    def _offer_lines(self, one: OfferShown) -> list[str]:
        """An offer open to this work, as a concurrent stimulus marked offered (§7:19)."""
        who = self._naming.who
        tag = (
            _withheld_tag("said", who)
            if one.input is None
            else _tag("said", [("from", who)], one.input)
        )
        attributes = [
            ("label", self._book.label(LabelKind.EPISODE, episode_address(one.activation_id))),
            ("offered", "yes"),
        ]
        return _container(
            "stimulus",
            attributes,
            [tag, _tag("understood", [("from", _SYSTEM)], one.meaning)],
        )

    def _entry_input(self, one: EntryInput) -> str:
        """One input of a concurrent stimulus: its brief, or the empty marker (§2:7)."""
        attributes = [("from", self._naming.parties(one.parties))]
        if one.brief is None:
            attributes.append(("withheld", "yes"))
        return _tag(_words_tag(one.parties, relayed=one.relayed), attributes, one.brief)

    # --- always in mind (ADR-0338 §7:2, ADR-0353 §4:5, ADR-0356 §10:5) ---

    def _always_in_mind(self) -> list[str]:
        """Who the person is to the system, their fields, and the slot and suggestions."""
        person = self._inputs.person
        if person is None:
            if self._naming.person_id is None:
                return [f"{_NOT_HELD}: this stimulus is no person's, so none is kept in mind."]
            return [f"{_NOT_HELD}: no profile or kept memory is read for this stimulus."]
        profile = person.profile
        name = profile.value(ProfileField.NAME)
        assistant = profile.value(ProfileField.ASSISTANT_NAME)
        who = _line(self._naming.who)
        if name and assistant:
            serves = f"- {who} is the one the system serves, and calls it {_line(assistant)}."
        elif name:
            serves = (
                f"- {who} is the one the system serves, and has not set a name for it, so it "
                f"is called {DEFAULT_ASSISTANT_NAME}."
            )
        elif assistant:
            serves = f"- {_upper(who)} has not set a name, and calls the system {_line(assistant)}."
        else:
            serves = (
                f"- {_upper(who)} has not set a name, nor one for the system, so it is called "
                f"{DEFAULT_ASSISTANT_NAME}."
            )
        address = profile.value(ProfileField.ADDRESS)
        language = profile.value(ProfileField.LANGUAGE)
        lines = [
            serves,
            f"- How {who} likes to be addressed: {_line(address)}."
            if address
            else f"- {_upper(who)} has not set how they like to be addressed.",
            f"- The language {who} writes in: {_line(language)}."
            if language
            else f"- {_upper(who)} has not set the language they write in.",
            # ADR-0356 §10:5: the block says that its fields outweigh any memory.
            f"- These fields are {who}'s current choice, and outweigh any memory stating "
            "another value for them.",
        ]
        for one in person.kept:
            # ADR-0338 §6:1: the slot's budget bounds its wordings, so each is shown whole.
            kept = ("pinned", "yes") if one.pinned else ("preference", "yes")
            lines.append(f"- {self._memory(one.memory, whole=True, extra=(kept,))}")
        if not person.kept:
            lines.append(f"- {_upper(who)} keeps nothing in mind for the system yet.")
        if person.left_out:
            memories = "memory" if person.left_out == 1 else "memories"
            lines.append(
                f"- {person.left_out} more {memories} {who} keeps in mind, left out to keep "
                "this short."
            )
        for suggestion in person.suggestions:
            lines.append(f"- {self._suggestion(suggestion)}")
        return lines

    def _suggestion(self, one: ShownSuggestion) -> str:
        """A pending suggestion, marked as one and never as the person's profile (§7:3)."""
        noticed = self._at(one.recorded_at)
        if one.field is not None:
            return (
                f"A suggestion the system noticed on {noticed}, which {_line(self._naming.who)} "
                f"has not taken up: their {one.field.value.replace('_', ' ')} set to "
                f"{_line(one.value or '')!s}."
            )
        if one.memory is not None:
            return self._memory(one.memory, extra=(("suggested", "pin"), ("noticed", noticed)))
        return f"A suggestion the system noticed on {noticed}."

    # --- short-term memory (ADR-0356 §3:2, §9) ---

    def _short_term(self) -> list[str]:
        """The episode window's episodes no other section renders, and the earlier work."""
        lines: list[str] = []
        for record in self._window_episodes():
            if record.id in self._rendered:
                continue
            at_origin = self._at_origin(record)
            linked = record.id in self._in_place and not self._remembered
            if at_origin and not linked:
                # Shown under stimulus origin memory.
                continue
            lines.extend(self._episode(record, in_place=self._place_of(record)))
        for one in self._inputs.earlier_work:
            lines.extend(self._peer_shown(one))
        return lines

    def _short_term_note(self) -> str:
        """Short-term memory's note where it renders nothing (ADR-0353 §8:1)."""
        if not self._inputs.episodes_read:
            return f"{_NOT_HELD}: recent stimuli are not read for a stimulus from this origin."
        return f"{_NOTHING_SHOWN}: no other recent stimulus is shown here."

    def _place_of(self, record: EpisodicMemory) -> _InPlace | None:
        """Which of an episode's texts the knowledge window shows whole, if it shows any."""
        texts = self._in_place.get(record.id)
        if texts is None or self._remembered:
            return None
        messages, delivered = _messages_in_place(record, texts.assistant)
        return _InPlace(
            input=bool(texts.user) and _JOINED.join(texts.user) == _input_of(record),
            messages=messages,
            delivered=delivered,
        )

    # --- recalled memories ---

    def _recalled(self) -> list[str]:
        """What both recall runs kept that no other section renders (ADR-0308 §3).

        A found episode is shown as its short view, and a found memory only where its
        source is not outside; the rest reach planning as recall's digest's evidence,
        each marked outside (§3:3, ADR-0306 §5:16).
        """
        inputs = self._inputs
        window = {record.id for record in inputs.episodes}
        person = inputs.person
        kept = frozenset() if person is None else person.memory_ids
        lines: list[str] = []
        for record in inputs.recalled:
            if record.id in window or record.id in kept or record.id in self._rendered:
                continue
            if isinstance(record, EpisodicMemory):
                processing = record.processing_record
                if processing is not None and processing.is_open:
                    continue
                stories = [
                    self._book.label(LabelKind.STORY, story)
                    for story in inputs.recalled_stories.get(record.id, ())
                ]
                extra = (("in_matters", " ".join(stories)),) if stories else ()
                lines.extend(self._episode(record, in_place=None, extra=extra))
            elif not record.rests_on_outside_content:
                lines.append(self._memory(record))
        for one in inputs.evidence:
            if one.result_id is None:
                lines.extend(self._evidence_lines(one))
        if lines:
            return lines
        if inputs.recalled:
            return [f"{_NOTHING_SHOWN}: everything recall found is already shown above."]
        return [
            f"{_NOTHING_SHOWN}: no memory was recalled for this stimulus that can be shown here."
        ]

    # --- matters (ADR-0307 §6:1, ADR-0356 §3:2) ---

    def _matters_section(self) -> list[str]:
        """Each story the activation belongs to, and each one understanding cited."""
        given = self._inputs.stories
        if given is None:
            return [f"{_NOT_HELD}: matters are not read for this stimulus."]
        if given.unreadable:
            return [
                f"{_UNREADABLE}: the matters could not be read, so none is shown, though some "
                "may exist."
            ]
        lines: list[str] = []
        for one in given.stories:
            lines.extend(self._story(one))
        for view in given.cited:
            lines.extend(self._short(view))
        if lines:
            return lines
        return [f"{_NOTHING_SHOWN}: this stimulus belongs to no matter yet, and none was cited."]

    def _seen(self, story_id: str, seen: MatterSeen) -> None:
        """Note what a matter was shown as, which the news later compares against."""
        self._matters[story_id] = seen

    def _story(self, one: PlanningStory) -> list[str]:
        """One matter: its summary, what is newer, the tidy-up facts, and where it stands.

        When the summary was last tidied and the count of changes since are shown on every
        pass (§6:3-§6:4). On a pass that may not be shown a note, nothing about the notes
        renders (ADR-0305 §4).
        """
        label = self._book.label(LabelKind.STORY, one.story_id)
        attributes = [
            ("label", label),
            ("last_tidied", "never" if one.tidied_at is None else self._at(one.tidied_at)),
            ("changes_since", str(one.changes)),
        ]
        tags = [self._summary_tag(one.written, one.withheld, one.lines, one.outside)]
        # ADR-0358 §11:2: the summary version it was first shown at.
        self.summaries_shown.setdefault(one.story_id, None if one.withheld else one.summary_version)
        if not one.notes_withheld:
            tags.extend(self._notes_of(one, attributes))
        for record in one.newer:
            tags.append(self._episode_text(record, ("since_tidied", "yes")))
        newer = {record.id for record in one.newer}
        for record in one.latest:
            if record.id not in newer:
                tags.append(self._episode_text(record))
        for view in one.inherited:
            tags.append("\n".join(self._short(view, inherited=True)))
        lines = _container("matter", attributes, tags)
        if one.standing is not None:
            lines.extend(self._standing(label, one.standing))
        self._seen(
            one.story_id,
            MatterSeen(
                summary=tuple(line.text for line in one.lines),
                written=one.written,
                notes=frozenset(int(note.note_id) for note in one.notes),
                merged_into=None if one.standing is None else one.standing.story.merged_into,
                written_at=one.tidied_at,
            ),
        )
        return lines

    def _notes_of(self, one: PlanningStory, attributes: list[tuple[str, str]]) -> list[str]:
        """A matter's notes, on a pass that may show them, and what its older notes are.

        A tidied story says that a story read lists any older notes its summary came from,
        where a story read is offered, and not on a read's own view, which lists them, a
        page at a time (#2893, #2944).
        """
        tags = [self._note(note) for note in one.notes]
        if one.older is None:
            if one.tidied_at is not None and self._reads_stories:
                attributes.append(("older_notes", "read the story to see them by their labels"))
            return tags
        tags.extend(self._note(note, older=True) for note in one.older)
        if one.older_more:
            attributes.append(("more_older", _more_older(one.older_more, one.older_page + 1)))
        elif not one.older:
            attributes.append(("older_notes", _NO_OLDER))
        return tags

    def _summary_tag(
        self,
        written: bool,
        withheld: bool,
        lines: Sequence[StorySummaryLine],
        outside: bool,
    ) -> str:
        """A summary's lines, or why none is shown; a marked one is read outside content."""
        if withheld:
            return _tag("summary", [("from", _SYSTEM), ("withheld", "yes")], None)
        if not written:
            return _tag("summary", [("from", _SYSTEM), ("written", "not yet")], None)
        attributes = [("from", _SYSTEM)]
        if outside:
            attributes.append(("outside", "yes"))
            # ADR-0303 §3:6: a marked summary planning reads is outside content read.
            self.shown.marked = True
        return _tag("summary", attributes, "\n".join(line.text for line in lines))

    def _note(self, note: StoryNote, *, older: bool = False) -> str:
        """A matter's note under its label, by who wrote it and its mark, never its text."""
        writer = self._naming.who if note.author is StoryNoteAuthor.OWNER else _SYSTEM
        attributes = [
            ("label", self._book.label(LabelKind.NOTE, str(note.note_id))),
            ("from", writer),
            ("at", self._at(note.written_at)),
        ]
        if note.author is StoryNoteAuthor.TIDY_UP:
            attributes.append(("written_by", "a tidy-up"))
        if older:
            attributes.append(("taken_in", "yes"))
        if note.outside:
            attributes.append(("outside", "yes"))
            self.shown.marked = True
        return _tag("note", attributes, note.text)

    def _short(self, view: ShortView, *, inherited: bool = False) -> list[str]:
        """A story's short view (ADR-0300 §6:2), under the same minimum (ADR-0304 §4)."""
        attributes = [("label", self._book.label(LabelKind.STORY, view.story_id))]
        if inherited:
            attributes.append(("inherited", "yes"))
        tags = [self._summary_tag(view.written, view.withheld, view.lines, view.outside)]
        self.summaries_shown.setdefault(
            view.story_id, None if view.withheld else view.summary_version
        )
        if not view.notes_withheld:
            tags.extend(self._note(note) for note in view.notes)
        tags.extend(self._episode_text(record) for record in view.episodes)
        self._matters.setdefault(
            view.story_id,
            MatterSeen(
                summary=tuple(line.text for line in view.lines),
                written=view.written,
                notes=frozenset(int(note.note_id) for note in view.notes),
            ),
        )
        return _container("matter", attributes, tags)

    def _standing(self, label: str, standing: StoryStanding) -> list[str]:
        """Where a matter stands (ADR-0300 §8:1), each episode by its label, as lines."""
        merged = standing.story.merged_into
        if merged is not None:
            return [f"- {label} was merged into {self._book.label(LabelKind.STORY, merged)}."]
        done = [
            f"{self._book.label(LabelKind.EPISODE, episode_address(effect.activation_id))} "
            f"({_EFFECT_TEXT[effect.state]}, {self._at(effect.at)})"
            for effect in standing.done
        ]
        lines = [f"- What was done in {label}: {'; '.join(done) if done else _NOTHING_DONE}."]
        moments: list[str] = []
        for moment in standing.recent:
            attributes = [
                ("from", _SYSTEM),
                (
                    "episode",
                    self._book.label(LabelKind.EPISODE, episode_address(moment.activation_id)),
                ),
                ("at", self._at(moment.occurred_at)),
            ]
            if moment.outside:
                attributes.append(("outside", "yes"))
                self.shown.marked = True
            moments.append(_tag("latest", attributes, moment.meaning))
        if moments:
            lines.append(f"- {label}'s timeline, newest first:")
            lines.extend(f"  {one}" for one in moments)
        earlier = standing.earlier
        if earlier is not None:
            lines.append(
                f"- {label} has {earlier.episodes} earlier episodes, from "
                f"{self._at(earlier.first_at)} to {self._at(earlier.last_at)}."
            )
        for related in standing.related:
            members = "member" if related.member_count == 1 else "members"
            lines.append(
                f"- {label} is {_RELATION_TEXT[related.relation]} "
                f"{self._book.label(LabelKind.STORY, related.story_id)}, with "
                f"{related.member_count} {members}."
            )
        return lines

    # --- an episode's short view (ADR-0356 §9) ---

    def _episode_text(self, record: EpisodicMemory, *extra: tuple[str, str]) -> str:
        """An episode inside a container: its short view, or a pointer where shown already."""
        label = self._book.label(LabelKind.EPISODE, record.id)
        if record.id in self._rendered:
            return _tag("episode", [("label", label), *extra, ("shown", "above")], None)
        return "\n".join(self._episode(record, in_place=None, extra=extra))

    def _episode(
        self,
        record: EpisodicMemory,
        *,
        in_place: _InPlace | None,
        extra: Sequence[tuple[str, str]] = (),
    ) -> list[str]:
        """Another episode, shown through its short view, under its ``E`` label (§9:1).

        Rendered from its projection alone, under the reader's audience (§9:5), with the
        episode window's pending candidates beside it (ADR-0329 §6:9).
        """
        label = self._book.label(LabelKind.EPISODE, record.id)
        self._rendered.add(record.id)
        window = {one.id for one in self._inputs.episodes}
        projection = project_episode(
            record,
            excerpt_chars=self._excerpt_chars,
            owner_records=self._inputs.owner_records,
            # ADR-0329 §6:9: an unprocessed episode's pending candidates, the window's alone.
            candidates=self._inputs.pending.get(record.id, ()) if record.id in window else (),
        )
        lines, marked = short_view(
            projection,
            label,
            naming=self._naming,
            at=self._at,
            place=self._book.held,
            notes_bound=self._notes_bound,
            in_place=in_place,
            extra=extra,
        )
        if marked:
            self.shown.marked = True
        return lines

    # --- earlier work (ADR-0349 §7:10, §7:27) ---

    def _peer_shown(self, one: PeerShown) -> list[str]:
        """One activation's finished work, rendered and noted as shown."""
        lines = self._peer(one)
        self._peers_rendered[one.activation_id] = "\n".join(lines)
        return lines

    def _peer(self, one: PeerShown) -> list[str]:
        """Another activation's own work, read through the peer view (§6:7-§6:10).

        Shown as an ``episode`` container, as a short view is: what it took in, what it
        was understood to mean, read as provisional, its notes, its evidence, what it did
        and how it stands.
        """
        label = self._book.label(LabelKind.EPISODE, episode_address(one.activation_id))
        attributes = [("label", label)]
        if one.stopped is not None:
            attributes.append(("stopped_by_this_call", "yes" if one.stopped else "no"))
        if one.answered is not None:
            attributes.append(("answer", one.answered))
            why = one.not_as_asked
            tags: list[str] = []
            if why is not None and why in _SHOWN_WITH_RESULT:
                attributes.append(("because", answer_fact(why, offering=label)))
                if one.meaning is not None:
                    tags.append(_tag("understood", [("from", _SYSTEM)], one.meaning))
            return _container("episode", attributes, tags)
        attributes.append(("status", "ended" if one.ended else "running"))
        view = one.view
        tags = []
        if view is None:
            attributes.append(("work", _PEER_UNREAD))
        else:
            if view.derived_from_external:
                attributes.append(("outside", "yes"))
                self.shown.marked = True
            tags = self._peer_work(view)
        return _container("episode", attributes, tags)

    def _peer_work(self, view: PeerView) -> list[str]:
        """What a peer view shows of an activation's own work (§6:9), as tags."""
        tags: list[str] = []
        word = _words_tag(view.parties, relayed=view.relayed)
        writer = self._naming.parties(view.parties)
        if view.input is not None:
            tags.append(
                "\n".join(_container("input", [], [_projected_tag(word, writer, view.input)]))
            )
            tags.extend(
                "\n".join(_container("took_in", [], [_projected_tag(word, writer, text)]))
                for text in view.joined
            )
        else:
            tags.append("\n".join(_container("input", [], [_withheld_tag(word, writer)])))
        if view.meaning is not None:
            tags.append(
                _tag("understood", [("from", _SYSTEM), ("provisional", "yes")], view.meaning)
            )
        for notes in view.notes:
            attributes = [("from", _SYSTEM)]
            if notes.marked:
                attributes.append(("outside", "yes"))
                self.shown.marked = True
            tags.append(_projected_tag("notes", _SYSTEM, notes.notes, attributes))
        for evidence in view.evidence:
            tags.append(
                _projected_tag(
                    "evidence", _SYSTEM, evidence.text, [("from", _SYSTEM), ("outside", "yes")]
                )
            )
            self.shown.marked = True
        tags.extend(_tag("did", [("from", _SYSTEM)], _effect_text(effect)) for effect in view.did)
        if not view.did:
            tags.append(_tag("did", [("from", _SYSTEM)], _NOTHING_DONE))
        return tags

    def _set_up(self, left: StillLive) -> object:
        """What a stopped activation set up that is still live (ADR-0352 §3:1-§3:6).

        Each task as the Task Scheduler's calls show one, under its ``T`` label, and each
        activation as the list pull's running part shows one, under its ``E`` label, or,
        pushed and not yet admitted, under its task's label as starting; each part says
        how many more there are past the listing bound.
        """
        if not left.read:
            return _SET_UP_UNREAD
        if left.nothing:
            return _NOTHING_SET_UP
        shown: dict[str, object] = {
            "scheduled": [self._task(one) for one in left.tasks] or _NONE_FOUND
        }
        if left.more_tasks:
            shown["more_scheduled_not_shown"] = left.more_tasks
        shown["running"] = [
            {
                "scheduled_task": self._book.label(LabelKind.SCHEDULED_TASK, one.task_id),
                "status": _STARTING,
            }
            if isinstance(one, StartingEntry)
            else self._running(one)
            for one in left.activations
        ] or _NONE_FOUND
        if left.more_activations:
            shown["more_running_not_shown"] = left.more_activations
        return shown

    # --- a remembered fact ---

    def _memory(
        self, record: Memory, *, whole: bool = False, extra: Sequence[tuple[str, str]] = ()
    ) -> str:
        """A memory not resting on outside content, as a ``memory`` tag under its label.

        ADR-0328 §15:5's label, as attributes: its kind by its band, its standing, its age,
        its evidence where its standing is inference, its reading certainty where that is
        not ``sure``, its track record where it has one, and each unresolved open question
        on it (ADR-0329 §6:6); ADR-0345 §12:3-§12:4's holders, and a memory of what the
        system said, said so.
        """
        who = self._naming.who
        label = self._book.label(LabelKind.MEMORY, record.id)
        self._memories.add(record.id)
        said = MemoryMark.ASSISTANT_STATEMENT in record.marks
        if said:
            kind = f"what the system itself said, never what {who} said or a source reported"
        else:
            kind = {
                BeliefBand.ASSERTED: f"something {who} said",
                BeliefBand.DERIVED: "something the system worked out",
                BeliefBand.ATTESTED: f"something from a source, never something {who} said",
            }[record.band]
        attributes = [("label", label), ("from", _SYSTEM), *extra, ("kind", kind)]
        if not said:
            attributes.append(("standing", _STANDING_TEXT[record.standing]))
        attributes.extend(
            [
                ("learned", self._at_or_unknown(record.learned)),
                ("as_of", self._at_or_unknown(record.as_of(self._now))),
            ]
        )
        attributes.extend(self._memory_judged(record))
        attributes.extend(self._memory_holders(record, said=said))
        fact = record.content
        bound = len(fact) if whole else self._excerpt_chars
        if len(fact) > bound:
            fact = f"{fact[:bound]}…"
            attributes.append(("cut", "yes"))
        return _tag("memory", attributes, fact)

    def _memory_judged(self, record: Memory) -> list[tuple[str, str]]:
        """What a memory's record says of how far it is to be trusted, as attributes.

        ADR-0328 §15:5: its evidence where its standing is inference, its reading certainty
        where that is not ``sure``, its track record where it has one, and each unresolved
        open question on it (ADR-0329 §6:6).
        """
        attributes: list[tuple[str, str]] = []
        if record.standing is MemoryStanding.INFERENCE:
            evidence = record.evidence_summary
            attributes.append(
                (
                    "evidence",
                    f"{evidence.supporting} for, {evidence.against} against, over "
                    f"{evidence.episodes} episodes, latest {self._at_or_unknown(evidence.latest)}",
                )
            )
        certainty = record.reading_certainty
        if certainty is not ReadingCertainty.SURE:
            attributes.append(
                ("reading_certainty", _NOT_JUDGED if certainty is None else str(certainty))
            )
        track = record.track_summary
        if track.relied_on:
            attributes.append(
                (
                    "track_record",
                    f"relied on {track.relied_on}, held up {track.held_up}, let down "
                    f"{track.let_down}",
                )
            )
        questions = [one.asks for one in record.open_questions if not one.resolved]
        if questions:
            attributes.append(("open_questions", "; ".join(questions)))
        return attributes

    def _memory_holders(self, record: Memory, *, said: bool) -> list[tuple[str, str]]:
        """ADR-0345 §12:3-§12:4's part of a memory's label, as attributes.

        Its holders wherever they are not the person alone, the holders of its counted
        ``against`` supports where it has any, and its validity end where it lies in the
        future. A memory of what the system said cites where and when, and who kept it.
        """
        attributes: list[tuple[str, str]] = []
        holders = record.holders
        if said:
            cited = [
                f"{self._book.held(LabelKind.EPISODE, one.episode) or _SAID_ELSEWHERE} at "
                f"{self._at_or_unknown(one.when)}"
                for one in statement_citations(record)
            ]
            if cited:
                attributes.append(("said_in", "; ".join(cited)))
            kept = [one for one in holders if one.kind is HolderKind.PERSON]
            if kept:
                attributes.append(
                    ("kept_by", ", ".join(_holder_text(one, self._naming) for one in kept))
                )
        elif holders and holders != (SupportHolder.person(OWNER_PERSON_ID),):
            attributes.append(
                ("held_by", ", ".join(_holder_text(one, self._naming) for one in holders))
            )
        disputed = record.against_holders
        if disputed:
            attributes.append(
                ("disputed_by", ", ".join(_holder_text(one, self._naming) for one in disputed))
            )
        end = record.validity.valid_until
        if end is not None and end > self._now:
            attributes.append(("holds_until", self._at(end)))
        return attributes

    # --- digested evidence ---

    def _evidence_lines(self, one: DigestedEvidence) -> list[str]:
        """One digest's evidence, each item an ``evidence`` tag marked outside (ADR-0308 §5)."""
        source = (
            _RECALL_DIGEST
            if one.result_id is None
            else self._book.label(LabelKind.RESULT, one.result_id)
        )
        if not one.answered:
            return [f"- A digest of {source} {_DIGEST_FAILED}."]
        # ADR-0308 §5:4: a digest that answered, with or without items, is read.
        self.shown.marked = True
        looking = "" if one.question is None else f", looking for {_line(one.question)}"
        if not one.items:
            return [f"- A digest of {source}{looking}: {_NOTHING_ANSWERED}."]
        lines = [f"- What a digest read of {source}{looking}, resting on outside content:"]
        lines.extend(
            "  "
            + _tag(
                "evidence",
                [
                    ("from", _SYSTEM),
                    ("source", self._book.label(item.source_kind, item.source_id)),
                    ("outside", "yes"),
                ],
                item.text,
            )
            for item in one.items
        )
        return lines

    def _evidence(self, one: DigestedEvidence) -> str:
        """One digest, as text, for a result (ADR-0308 §5)."""
        return "\n".join(self._evidence_lines(one))

    # --- the report (ADR-0356 §5:3-§5:6) ---

    def report(self, work: PlanningWork) -> tuple[RoundReport, NewsShown]:
        """The system's turn after the work's last round: its results, then the news.

        ADR-0356 §5:3-§5:6. One result for each call of that round, in its order and
        under its id: code's rendering of what came of it, a digested result as its
        digest's evidence, marked outside, and a result planning may name under its R
        label. Then what the inputs hold that the exchange has not shown: each offer
        newly open and each that closed, the finished work newly read of an activation
        this work took over or waited on, a stimulus taken in, with its meaning, any
        evidence not yet shown, each matter shown that has changed since, and each
        memory shown that the store no longer holds (the owner's ruling on #3536); or that
        nothing has changed.

        Returns:
            The report, and what the exchange has shown once it is sent.
        """
        inputs = self._inputs
        shown = work.shown
        self._memories.update(shown.memories)
        self._matters.update(shown.matters)
        outcomes = {
            outcome.call_id: outcome
            for outcome in inputs.outcomes
            if outcome.round_id == work.round_id
        }
        fresh = list(enumerate(inputs.evidence))[shown.evidence :]
        digests = _digests_by_call(work.response.calls, outcomes, fresh)
        reported = {at for held in digests.values() for at, _ in held}
        results: list[CallResult] = []
        for index, call in enumerate(work.response.calls, 1):
            outcome = outcomes.get(call.call_id)
            result = self._call(call, outcome, reference=f"{work.number}.{index}")
            if outcome is not None and outcome.digested and outcome.result_id is not None:
                # §5:4: a result resting on outside content is its digest's evidence.
                read = digests.get(call.call_id, [])
                result["evidence"] = [self._evidence(one) for _, one in read] or _NOT_YET_READ
            results.append(
                CallResult(
                    call_id=call.call_id,
                    text=json.dumps(result, ensure_ascii=False, sort_keys=False),
                )
            )
        started = self._stories_started(work, outcomes, results, shown.stories)
        news = self._news(shown, [one for at, one in fresh if at not in reported])
        self._name_running()
        return (
            RoundReport(
                results=tuple(results),
                news="\n".join(
                    [self._now_line(), *([NEWS_OPENING, *news] if news else [NOTHING_NEW])]
                ),
            ),
            NewsShown(
                offers=frozenset(one.activation_id for one in inputs.offers),
                earlier_work={**shown.earlier_work, **self._peers_rendered},
                understanding=(
                    shown.understanding
                    if inputs.understanding is None
                    else inputs.understanding.version
                ),
                items=shown.items | frozenset(inputs.place.items),
                evidence=len(inputs.evidence),
                stories=shown.stories | started,
                memories=frozenset(self._memories),
                matters=dict(self._matters),
                running=(shown.running - frozenset(inputs.ended)) | self._running_shown(),
                kept=self._kept_now(shown),
                profile=(
                    shown.profile
                    if inputs.person_now is None
                    else _profile_of(inputs.person_now.profile)
                ),
                zone=shown.zone,
            ),
        )

    def _now_line(self) -> str:
        """When the report was made, as the situation writes now (ADR-0360)."""
        local = self._now.astimezone(self._zone)
        return f"Now: {_long_day(local)}, {_clock(local)}."

    def _kept_now(self, shown: NewsShown) -> frozenset[str]:
        """The memories the exchange has shown pinned once this report is sent."""
        person = self._inputs.person_now
        return shown.kept if person is None else frozenset(one.id for one in person.pinned)

    def _name_running(self) -> None:
        """Nothing is left to name: running work is cited by a label already held."""

    def _stories_started(
        self,
        work: PlanningWork,
        outcomes: Mapping[str, CallOutcome],
        results: list[CallResult],
        shown: frozenset[str],
    ) -> frozenset[str]:
        """The stories the round's story calls brought the activation into, in their result.

        What came of a story call that started or linked the activation into a story is
        that story, which a later round names by its S label (ADR-0356 §5:4, ADR-0307
        §5:1): each story the inputs now hold that the exchange never showed is rendered,
        as the story views are, in the result of the round's first story call done.

        Returns:
            The stories rendered, by id; none where no story call was done.
        """
        fresh = [one for one in self._stories_held() if one.story_id not in shown]
        if not fresh:
            return frozenset()
        for at, call in enumerate(work.response.calls):
            outcome = outcomes.get(call.call_id)
            if (
                call.name in STORY_CALL_CAPABILITIES
                and outcome is not None
                and outcome.kind is CallOutcomeKind.DONE
            ):
                result = json.loads(results[at].text)
                result["stories"] = ["\n".join(self._story(one)) for one in fresh]
                results[at] = CallResult(
                    call_id=call.call_id, text=json.dumps(result, ensure_ascii=False)
                )
                return frozenset(one.story_id for one in fresh)
        return frozenset()

    def _news(self, shown: NewsShown, evidence: Sequence[DigestedEvidence]) -> list[str]:
        """What the work's inputs hold that the exchange has not yet shown (§5:5-§5:6)."""
        inputs = self._inputs
        news: list[str] = []
        for one in inputs.offers:
            if one.activation_id not in shown.offers:
                news.extend(self._offer_lines(one))
        open_now = {one.activation_id for one in inputs.offers}
        for closed in sorted(shown.offers - open_now):
            label = self._book.label(LabelKind.EPISODE, episode_address(closed))
            news.append(f"- The offer of {label} is no longer open.")
        for peer in inputs.earlier_work:
            lines = self._peer(peer)
            rendered = "\n".join(lines)
            if shown.earlier_work.get(peer.activation_id) != rendered:
                news.append("- Finished work newly read:")
                news.extend(lines)
            self._peers_rendered[peer.activation_id] = rendered
        understanding = inputs.understanding
        if understanding is not None and understanding.version != shown.understanding:
            # A stimulus taken in, with its meaning (ADR-0332 §3:12).
            news.append("- A stimulus was taken in, and understood again:")
            news.extend(self._understood_lines(understanding))
        for item in inputs.place.items:
            if item not in shown.items:
                news.extend(self._item(replace(item, is_input=False)))
        for digest in evidence:
            news.extend(self._evidence_lines(digest))
        news.extend(self._matters_changed())
        news.extend(self._forgotten(shown))
        news.extend(self._works_changed(shown))
        news.extend(self._always_changed(shown))
        return news

    def _works_changed(self, shown: NewsShown) -> list[str]:
        """Other works newly running, and works shown running that have ended (ADR-0360 §3).

        By the concurrent stimuli section's own selection: each it would now enter that the
        exchange has not shown, newest first, as the section renders an entry, with its
        latest meaning as the peer view renders it, and how many more started (§3:1,
        §3:3); and each the exchange showed there that has ended, as short-term memory
        shows an episode, its input pointing at where the exchange showed it (§3:2). One
        another kind of news names in this report, or this work's own stop ended, is not
        named again (§3:4).
        """
        inputs = self._inputs
        named = {one.activation_id for one in inputs.offers} | {
            one.activation_id for one in inputs.earlier_work
        }
        named |= self._stopped_here()
        lines: list[str] = []
        started = [
            entry
            for entry in inputs.running
            if entry.activation_id not in shown.running and entry.activation_id not in named
        ]
        for entry in started:
            tags = [self._entry_input(one) for one in _entry_inputs(entry)]
            meaning = inputs.meanings.get(entry.activation_id)
            if meaning is not None:
                tags.append(
                    _tag("understood", [("from", _SYSTEM), ("provisional", "yes")], meaning)
                )
            lines.append("- Being worked on separately:")
            lines.extend(
                self._running_container(
                    entry.activation_id,
                    entry.channel,
                    entry.arrived_at,
                    acted=entry.acted,
                    outside=entry.outside,
                    tags=tags,
                    offer=None,
                    waited=False,
                )
            )
        if started and inputs.running_more:
            lines.append(
                f"- {inputs.running_more} more are running, older than those, and are not shown."
            )
        for activation_id, record in sorted(inputs.ended.items()):
            if activation_id not in shown.running or activation_id in named:
                continue
            label = self._book.label(LabelKind.EPISODE, episode_address(activation_id))
            if record is None:
                lines.append(f"- {label} has ended.")
                continue
            lines.append(f"- {label} has ended:")
            lines.extend(
                self._episode(record, in_place=_InPlace(input=True, section=_IN_CONCURRENT))
            )
        return lines

    def _stopped_here(self) -> set[str]:
        """The activations this work's own stop calls stopped, whose result reported them."""
        return {
            outcome.peer.activation_id
            for outcome in self._inputs.outcomes
            if outcome.peer is not None and outcome.peer.stopped
        }

    def _always_changed(self, shown: NewsShown) -> list[str]:
        """What the person newly chose to keep in mind (ADR-0360 §4).

        Each memory a pin now reaches that the exchange has not shown pinned, as always in
        mind renders a pinned memory; each one shown pinned that no pin now reaches, as no
        longer pinned; and each field changed, with its new value, or as not set; the time
        zone saying that this work's times stay in the zone its briefing named. A pin or a
        field this work's own call changed comes back in that call's result, and is not
        named again (§4:5).
        """
        person = self._inputs.person_now
        if person is None:
            return []
        who = _line(self._naming.who)
        own_pins, own_fields = self._chosen_here()
        lines: list[str] = []
        before = dict(shown.profile)
        for name, value in _profile_of(person.profile):
            if name not in before or before[name] == value or name in own_fields:
                continue
            said = name.replace("_", " ")
            if name == ProfileField.TIME_ZONE.value:
                zone = _line(shown.zone or self._zone.key)
                set_to = f"is now {_line(value)}" if value else "is no longer set"
                lines.append(
                    f"- {_upper(who)}'s time zone {set_to}; this work's times stay in {zone}."
                )
                continue
            lines.append(
                f"- {_upper(who)}'s {said} is now {_line(value)}."
                if value
                else f"- {_upper(who)}'s {said} is no longer set."
            )
        now = {one.id for one in person.pinned}
        for memory in person.pinned:
            if memory.id in shown.kept or memory.id in own_pins:
                continue
            pinned = self._memory(memory, whole=True, extra=(("pinned", "yes"),))
            lines.append(f"- Now pinned: {pinned}")
        for memory_id in sorted(shown.kept - now - own_pins):
            label = self._book.held(LabelKind.MEMORY, memory_id)
            if label is not None:
                lines.append(f"- {label} is no longer pinned.")
        return lines

    def _chosen_here(self) -> tuple[set[str], set[str]]:
        """The memories and fields this work's own done pin, unpin and profile calls changed."""
        done = {
            (one.round_id, one.call_id)
            for one in self._inputs.outcomes
            if one.kind is CallOutcomeKind.DONE
        }
        memories: set[str] = set()
        fields: set[str] = set()
        for planning_round in self._inputs.rounds:
            for call in planning_round.calls:
                if (planning_round.id, call.call_id) not in done:
                    continue
                if call.name in {"pin", "unpin"}:
                    named = self._book.resolve(str(call.arguments.get("memory", "")))
                    if named is not None:
                        memories.add(named.id)
                elif call.name == "set_profile":
                    fields.add(str(call.arguments.get("field", "")))
        return memories, fields

    def _forgotten(self, shown: NewsShown) -> list[str]:
        """Each memory the exchange showed that the store no longer holds (#3536).

        The briefing stays as rendered (ADR-0356 §5:2); a memory forgotten mid-work is
        named by its label as forgotten and not to be used, once.
        """
        held = self._inputs.still_held
        if held is None:
            return []
        lines: list[str] = []
        gone = shown.memories - held
        for memory_id in sorted(gone):
            label = self._book.held(LabelKind.MEMORY, memory_id)
            if label is not None:
                lines.append(
                    f"- {label} is forgotten: the system no longer holds it, so do not use it."
                )
        self._memories.difference_update(gone)
        return lines

    def _matters_changed(self) -> list[str]:
        """Each matter the exchange showed that has changed since, said once.

        Re-read as the store holds it now; planning reads the whole with a story read.
        Nothing the briefing showed is re-rendered (ADR-0356 §5:2, §5:6).
        """
        now = self._inputs.matters_now
        lines: list[str] = []
        for story_id, seen in sorted(self._matters.items()):
            if story_id not in now:
                continue
            label = self._book.label(LabelKind.STORY, story_id)
            state = now[story_id]
            if state is None:
                lines.append(f"- {label} is gone: the system no longer holds it.")
                del self._matters[story_id]
                continue
            said, self._matters[story_id] = self._matter_change(seen, state)
            if said:
                lines.append(f"- {label} changed: {'; '.join(said)}.")
        return lines

    def _matter_change(
        self, seen: MatterSeen, state: StorySummaryState
    ) -> tuple[list[str], MatterSeen]:
        """What changed of one matter since the exchange showed it, and what it shows now.

        ADR-0359 §2, §5: a summary's words and its notes are compared only on a pass that
        may show them (ADR-0304 §4, ADR-0305 §4), a rewritten summary marked outside is said
        to be rewritten with no line of it, and the matter a merge went into is named only
        where the pass may be shown it; a note this work wrote itself is no news to it.
        """
        visible = self._inputs.owner_records
        said: list[str] = []
        merged = state.story.merged_into
        if merged is not None and seen.merged_into is None:
            # ADR-0359 §2:4, §5:3: named by its label where the pass may be shown it.
            into = (
                self._book.label(LabelKind.STORY, merged)
                if visible
                else self._book.held(LabelKind.STORY, merged)
            )
            said.append(
                "it was merged into another matter"
                if into is None
                else f"it was merged into {into}"
            )
        summary = state.summary
        texts = () if summary is None else tuple(line.text for line in summary.lines)
        if (summary is not None) != seen.written:
            rewritten = True
        elif summary is None:
            rewritten = False
        elif seen.written_at is not None:
            rewritten = summary.written_at != seen.written_at
        else:
            rewritten = visible and texts != seen.summary
        if rewritten and visible and texts and summary is not None and not summary.outside:
            said.append(
                f"its summary was rewritten, and now begins: {_line(texts[0]).rstrip(' .')}"
            )
        elif rewritten:
            said.append("its summary was rewritten")
        pending = frozenset(int(note.note_id) for note in state.pending_notes)
        if visible:
            gained = [
                note
                for note in state.pending_notes
                if int(note.note_id) not in seen.notes
                and note.written_during != self._inputs.activation_id
            ]
            if gained:
                said.append(
                    "it gained a note" if len(gained) == 1 else f"it gained {len(gained)} notes"
                )
            if not rewritten and seen.notes - pending:
                said.append("some of what it held was moved or split off into another matter")
        return said, MatterSeen(
            summary=texts,
            written=summary is not None,
            notes=pending if visible else seen.notes,
            merged_into=merged,
            written_at=None if summary is None else summary.written_at,
        )

    # --- a call's result ---

    def _place_named(self, place: str) -> str:
        """A place by its ``L`` label where it is on the list, and in words otherwise."""
        held = self._book.held(LabelKind.PLACE, place)
        if held is not None:
            return held
        return f"{place_description(place_channel(place))}, not on your place list"

    def _task(self, entry: TaskEntry) -> dict[str, object]:
        """A scheduled task, as the Task Scheduler's calls show it (ADR-0350 §4:6-§4:8)."""
        shown: dict[str, object] = {
            "label": self._book.label(LabelKind.SCHEDULED_TASK, entry.task_id),
            "state": entry.state,
            "falls_due": entry.falls_due,
        }
        if entry.repeats is not None:
            shown["repeats"] = entry.repeats
        if entry.read_back is not None:
            shown["read_back"] = entry.read_back
        if entry.waits_on:
            shown["waits_on"] = [
                self._book.label(LabelKind.SCHEDULED_TASK, one) for one in entry.waits_on
            ]
        shown["carries"] = (
            _withheld_tag("task", _SYSTEM)
            if entry.instruction is None
            else _tag("task", [("from", _SYSTEM)], entry.instruction)
        )
        if entry.instruction is None:
            self.shown.marked = True
        shown["set_by"] = entry.author
        shown["suggests"] = [self._place_named(one) for one in entry.places] or _NONE_FOUND
        shown["parent"] = {
            "episode": self._book.label(LabelKind.EPISODE, f"activation:{entry.parent}"),
            "is": entry.parent_text,
        }
        return shown

    def _activation(self, entry: ActivationEntry) -> dict[str, object]:
        """A running or ended activation, as the list pull shows it (ADR-0350 §4:6-§4:7)."""
        shown: dict[str, object] = {
            "episode": self._book.label(LabelKind.EPISODE, f"activation:{entry.activation_id}"),
            "started": entry.started,
            "place": entry.place,
            "status": entry.status,
            "input": self._entry_words(entry),
        }
        if entry.wrote_into is not None and (entry.wrote_into or not entry.may_have_written_into):
            # A message whose outcome is not known is no answer that none was written.
            shown["wrote_into"] = [
                self._listed_place(one) for one in entry.wrote_into
            ] or _WROTE_NO_MESSAGE
        if entry.may_have_written_into:
            shown["may_have_written_into"] = [
                self._listed_place(one) for one in entry.may_have_written_into
            ]
        return shown

    def _entry_words(self, entry: ActivationEntry) -> str:
        """An activation's input in brief, in a text tag by whose words it carries."""
        if entry.outside:
            self.shown.marked = True
            return _withheld_tag("received", _UNKNOWN)
        if entry.assistants:
            return (
                _withheld_tag("task", _SYSTEM)
                if entry.input is None
                else _tag("task", [("from", _SYSTEM)], entry.input)
            )
        if entry.input is None:
            return _withheld_tag("said", self._naming.who)
        return _tag("said", [("from", self._naming.who)], entry.input)

    def _listed_place(self, place: str) -> dict[str, object]:
        """A place a message went into, as the place list shows it (ADR-0350 §5:10-§5:12)."""
        for one in self._inputs.places or ():
            if one.place == place:
                return {"label": self._book.label(LabelKind.PLACE, place), "is": one.description}
        return {"is": place_description(place_channel(place)), "on_your_place_list": False}

    def _running(self, entry: ActivationEntry) -> dict[str, object]:
        """A running activation, as the list pull's running part shows it (ADR-0349 §6:2)."""
        return {
            "episode": self._book.label(LabelKind.EPISODE, f"activation:{entry.activation_id}"),
            "place": entry.place,
            "input": self._entry_words(entry),
            "has_acted": entry.acted,
        }

    def _listing(self, listing: TaskListing) -> dict[str, object]:
        """What a call on the Task Scheduler came back with, labelled (ADR-0350 §4:6-§4:8)."""
        shown: dict[str, object] = {}
        if listing.spawned is not None:
            shown["spawned"] = self._task(listing.spawned)
        if listing.cancelled is not None:
            shown["cancelled"] = self._task(listing.cancelled)
        if listing.listed:
            shown["running"] = [self._running(one) for one in listing.running] or _NONE_FOUND
            shown["scheduled"] = [self._task(one) for one in listing.scheduled] or _NONE_FOUND
            shown["ended_lately"] = [self._activation(one) for one in listing.recent] or _NONE_FOUND
        return shown

    def _call(
        self, call: ProposedCall, outcome: CallOutcome | None, *, reference: str
    ) -> dict[str, object]:
        """What came of one call, as its result shows it (ADR-0356 §5:4)."""
        shown: dict[str, object] = {}
        if outcome is None:
            # ADR-0307 §7:1: a tidy-up's outcome is the story's version log's, never
            # the episode's, and nothing waits for it.
            shown["outcome"] = (
                _TIDY_STARTED if call.name == TIDY_STORY_CAPABILITY else "no outcome recorded"
            )
            return shown
        if outcome.kind is CallOutcomeKind.NEEDS_YOU:
            return shown | self._needs_you(outcome, reference)
        text = _OUTCOME_TEXT[outcome.kind]
        if outcome.reason is not None:
            text = f"{text}: {outcome.reason}"
        shown["outcome"] = text
        shown |= self._delivered(outcome.delivered)
        shown |= self._absorbed_by(outcome.peer)
        if outcome.kind is not CallOutcomeKind.DONE or outcome.result_id is None:
            return shown
        shown["result"] = self._result(outcome, outcome.result_id)
        return shown

    def _result(self, outcome: CallOutcome, result_id: str) -> dict[str, object]:
        """A done call's result under its R label: what it found, as planning may see it."""
        result: dict[str, object] = {"label": self._book.label(LabelKind.RESULT, result_id)}
        result["value"] = self._result_value(outcome)
        if outcome.peer is not None and outcome.peer.set_up is not None:
            result["set_up_still_live"] = self._set_up(outcome.peer.set_up)
        return result

    def _result_value(self, outcome: CallOutcome) -> object:
        """What a done call's result shows: what it looked up, or what it returned.

        A story read's view, its marks with it, a marked line outside content read,
        which rendering it counts (ADR-0300 §10:6); a memory search's records; a
        candidate's lookup; a call on the Task Scheduler or on running work; an episode
        look-up's (ADR-0358 §7-§10); or the result itself, a digested one as read for
        planning by its digest.
        """
        looked: tuple[tuple[object, Callable[[Any], object]], ...] = (
            (outcome.story, lambda story: "\n".join(self._story(story))),
            (outcome.records, lambda _: self._searched(outcome)),
            (outcome.candidate, self._candidate),
            (outcome.tasks, self._listing),
            (outcome.peer, lambda peer: "\n".join(self._peer(peer))),
            (outcome.episodes, self._found_episodes),
            (outcome.history, self._older_history),
            (outcome.full, self._full_episode),
        )
        for found, rendered in looked:
            if found is not None:
                return rendered(found)
        return _DIGESTED_RESULT if outcome.digested else _thawed(outcome.result)

    # --- the episode look-ups' results (ADR-0358 §7-§10) ---

    def _found_episodes(self, found: EpisodesFound) -> dict[str, object]:
        """A search of past episodes: one page of what it found, each as its short view.

        ADR-0358 §7:2: each episode found is rendered as short-term memory renders an
        episode, through :meth:`_episode` over its projection under the reader's
        audience; §8:1: with the matters it belongs to. §7:3: a pass of unbounded
        audience found none.
        """
        shown: dict[str, object] = {
            "page": found.page,
            "episodes": [self._found_episode(one) for one in found.episodes] or _NONE_FOUND,
        }
        if found.more:
            shown["more"] = _next_page(found.page)
        return shown

    def _found_episode(self, one: EpisodeShown) -> dict[str, object]:
        """One episode a look-up found, as its short view, with the matters it is in."""
        shown: dict[str, object] = {"episode": self._shown_episode(one.record)}
        if one.matters:
            shown["in_matters"] = [self._matter(matter) for matter in one.matters]
        return shown

    def _shown_episode(self, record: EpisodicMemory) -> str:
        """An episode a look-up shows: its short view, as short-term memory shows one.

        ADR-0358 §7:2, §9:2: through the one rendering of another episode, the short view
        (ADR-0356 §9), under the reader's audience; an episode already shown is pointed at
        by its label.
        """
        return self._episode_text(record)

    def _matter(self, matter: MatterShown, *, again: bool = False) -> dict[str, object] | str:
        """A matter by its S label and, the first time it is shown, its summary's first line.

        ADR-0358 §8:1, under ADR-0307 §6:4's rules for what an audience may be shown of a
        story: a summary that may not be shown is withheld, and a marked one shown is
        outside content read (ADR-0303 §3:6). ``again`` is the full view's reading of it
        as it is held now, which always shows the first line (§10:7).
        """
        held = self._book.held(LabelKind.STORY, matter.story_id) is not None
        label = self._book.label(LabelKind.STORY, matter.story_id)
        if held and not again:
            return label
        self.summaries_shown.setdefault(
            matter.story_id, None if matter.withheld else matter.summary_version
        )
        shown: dict[str, object] = {"label": label}
        if matter.withheld:
            shown["summary"] = _SUMMARY_WITHHELD
        elif matter.summary_version is None:
            shown["summary"] = _NO_SUMMARY
        elif matter.first_line is None:
            shown["summary"] = _NO_LINES
        else:
            shown["summary"] = matter.first_line
            if matter.outside:
                shown["summary_outside_content"] = _OUTSIDE
                self.shown.marked = True
        return shown

    def _older_history(self, history: OlderHistory) -> dict[str, object] | str:
        """One page of the origin's older history, or why none is shown (ADR-0358 §9).

        Each item as the place window shows an item (§9:3), and each earlier episode by
        its label and short view (§9:2).
        """
        if not history.readable:
            return _HISTORY_UNREADABLE
        if not history.items and not history.episodes and not history.more:
            return _NOTHING_OLDER if history.page == 1 else _NO_OLDER
        shown: dict[str, object] = {"page": history.page}
        if history.items or not history.episodes:
            # A page whose every message was deleted, or already shown, shows none.
            shown["items"] = [self._older_item(item, history) for item in history.items] or (
                _NO_OLDER
            )
        if history.episodes:
            shown["episodes"] = [self._shown_episode(record) for record in history.episodes]
        if history.more:
            shown["more"] = _next_page(history.page)
        return shown

    def _older_item(self, item: PlaceItem, history: OlderHistory) -> str:
        """An older item as the place window shows one, a relayed input's withheld (§9:3)."""
        if history.withheld(item) and item.author is PlaceAuthor.USER:
            attributes = [("from", self._naming.who)]
            if item.at is not None:
                attributes.append(("at", self._at(item.at)))
            return _tag("message", [*attributes, ("withheld", "yes")], None)
        return "\n".join(self._item(replace(item, is_input=False)))

    def _full_episode(self, read: EpisodeRead) -> dict[str, object]:
        """One page of an episode's full record, its parts in the order they happened.

        ADR-0358 §10:3-§10:11. The input, the meaning, the response and how the work
        ended head every page, as the short view shows them, and the parts follow:
        on a pass that may not be shown a record placed for the owner alone there are
        none, and nothing is said of them (§10:5). A record shown again is read as it
        is held now and says so (§10:6-§10:7). A part the record no longer keeps says
        so (§10:9).
        """
        label = self._book.label(LabelKind.EPISODE, read.episode_id)
        shown: dict[str, object] = {"label": label}
        projection = read.projection
        if read.running:
            shown["full_record"] = _STILL_RUNNING
            return shown
        if read.record is None or projection is None:
            shown["full_record"] = _RECORD_GONE
            return shown
        self._rendered.add(read.episode_id)
        shown |= self._full_head(projection)
        if read.matters:
            # ADR-0358 §8:1: the matters it belongs to, as an episode search names them.
            shown["in_matters"] = [self._matter(matter) for matter in read.matters]
        if not self._inputs.owner_records:
            return shown
        shown["page"] = read.page
        if projection.understood_elided and read.page == 1:
            shown["earlier_understanding"] = _elided(projection.understood_elided)
        shown["parts"] = [self._full_part(part, read) for part in read.page_parts()] or (
            _NONE_FOUND if read.page == 1 else _NO_OLDER
        )
        if read.more:
            shown["more"] = _next_page(read.page)
        return shown

    def _full_head(self, projection: EpisodeProjection) -> dict[str, object]:
        """What heads every page of a full view: what the short view shows of the episode."""
        shown: dict[str, object] = {"at": self._at(projection.occurred_at)}
        given = _view_input(projection, self._naming, None)
        if given:
            shown["input"] = given[0]
            if parties_are_outside(projection.parties, relayed=projection.relayed):
                self.shown.marked = True
        if projection.meaning is not None:
            shown["understood_then"] = projection.meaning
        if projection.response is not None:
            shown["response"] = _text(projection.response)
        if projection.derived_from_external:
            shown["outside_content"] = _OUTSIDE
            self.shown.marked = True
        if projection.status is not None and projection.reason is not None:
            shown["ended"] = f"{projection.status.value}: {projection.reason.value}"
        return shown

    def _full_part(self, part: FullViewPart, read: EpisodeRead) -> dict[str, object]:
        """One part of an episode's full view (ADR-0358 §10:3)."""
        if isinstance(part, ProjectedCall):
            return self._full_call(part, read)
        if isinstance(part, ProjectedRecall):
            return {
                "recall": "second run" if part.second else "first run",
                "outcome": part.outcome.value,
                "found": self._shown_again(part.found, read) or _NONE_FOUND,
            }
        if isinstance(part, ProjectedRound):
            return {"round": part.position + 1} | self._full_round(part)
        return self._full_record_part(part)

    def _full_round(self, one: ProjectedRound) -> dict[str, object]:
        """One round of a full view: an older round's message, and its notes where shown."""
        shown: dict[str, object] = {}
        if one.message is not None:
            shown["message"] = _text(one.message)
        if one.notes is not None:
            shown["notes"] = _text(one.notes)
            if one.notes_marked:
                shown["notes_outside_content"] = _OUTSIDE
                self.shown.marked = True
        return shown

    def _full_record_part(
        self,
        part: ProjectedUnderstanding | ProjectedEvidence | ProjectedJoin | ProjectedProposal,
    ) -> dict[str, object]:
        """A full view's part that names no record: understanding, evidence, an input."""
        if isinstance(part, ProjectedUnderstanding):
            understood: dict[str, object] = {"understood": part.meaning, "version": part.version}
            if part.unclear:
                understood["unclear"] = [
                    {"gap": one.gap, "readings": list(one.readings)} for one in part.unclear
                ]
            return understood
        if isinstance(part, ProjectedEvidence):
            # ADR-0358 §10:8: digested evidence is shown marked, and read outside content.
            self.shown.marked = True
            return {"evidence": _text(part.text), "outside_content": _OUTSIDE}
        if isinstance(part, ProjectedJoin):
            return {
                "took_in": _JOIN_WITHHELD if part.input is None else _text(part.input),
                "from": _place_text(part.channel),
            }
        # §10:9: a call whose entry the record does not hold keeps only its arguments.
        return {
            "round": part.position + 1,
            "capability": part.capability,
            "arguments": _text(part.arguments),
            "outcome": _NOT_KEPT,
        }

    def _full_call(self, call: ProjectedCall, read: EpisodeRead) -> dict[str, object]:
        """One call's entry in the full view: what came of it and what it showed."""
        shown: dict[str, object] = {
            "round": call.position + 1,
            "capability": call.capability,
            "arguments": _text(call.arguments),
        }
        if call.outcome is None:
            shown["outcome"] = (
                _TIDY_STARTED if call.capability == TIDY_STORY_CAPABILITY else _NO_OUTCOME
            )
        else:
            text = _FULL_OUTCOME_TEXT[call.outcome]
            shown["outcome"] = text if call.reason is None else f"{text}: {call.reason}"
        shown |= self._delivered(call.delivered)
        if call.marked:
            # ADR-0356 §8:7, ADR-0358 §10:8: a marked entry is shown marked.
            shown["outside_content"] = _OUTSIDE
            self.shown.marked = True
        if call.outcome is not CallOutcomeKind.DONE:
            return shown
        showed = call.showed
        if showed is None:
            shown["showed"] = _NOT_KEPT
            return shown
        parts: list[object] = []
        for part in showed.parts:
            if isinstance(part, ShownText):
                parts.append({"text": part.text})
            else:
                parts.extend(self._shown_again((part,), read))
        if showed.cut:
            parts.append(_REST_NOT_KEPT)
        shown["showed"] = parts or _SHOWED_NOTHING
        return shown

    def _shown_again(
        self, records: Sequence[ShownRecord], read: EpisodeRead
    ) -> list[dict[str, object]]:
        """Records the full view shows again, each as it is held now (ADR-0358 §10:6-§10:7).

        A memory as planning is shown any memory, one resting on outside content left
        out as a found one is (ADR-0307 §9:2); a story by its label and its summary's
        first line; an episode by its label alone. One no longer held, or that the
        audience refuses, is left out with nothing said (§6:3).
        """
        shown: list[dict[str, object]] = []
        for record in records:
            if record.kind is ShownRecordKind.MEMORY:
                memory = read.memories.get(record.id)
                if memory is None or memory.rests_on_outside_content:
                    continue
                shown.append({"memory": self._memory(memory), "shown": _AS_HELD_NOW})
            elif record.kind is ShownRecordKind.STORY:
                story = read.stories.get(record.id)
                if story is not None:
                    shown.append(self._matter_again(story))
            elif record.id in read.episodes:
                shown.append(
                    {
                        "label": self._book.label(LabelKind.EPISODE, record.id),
                        "shown": _AS_HELD_NOW,
                    }
                )
        return shown

    def _matter_again(self, story: MatterShown) -> dict[str, object]:
        """A story the full view shows again: its label and its summary's first line."""
        matter = self._matter(story, again=True)
        shown: dict[str, object] = {"label": matter} if isinstance(matter, str) else matter
        return shown | {"shown": _AS_HELD_NOW}

    def _delivered(self, delivered: RecordedDelivery | None) -> dict[str, object]:
        """What a message call sent, where it went and how (ADR-0356 §8:4), or nothing."""
        if delivered is None:
            return {}
        place = place_of(delivered.went)
        shown: dict[str, object] = {
            "words": delivered.words,
            "went": self._book.held(LabelKind.PLACE, place) or place,
            "by": platform_name(delivered.went.channel_type),
            "how": delivered.status.value,
        }
        if delivered.reason is not None:
            shown["because"] = delivered.reason
        return {"delivered": shown}

    def _absorbed_by(self, peer: PeerShown | None) -> dict[str, object]:
        """ADR-0349 §4:9: the absorber a refused stop names, by its label, where one did."""
        if peer is None or peer.absorbed_by is None:
            return {}
        return {
            "absorbed_by": self._book.label(LabelKind.EPISODE, episode_address(peer.absorbed_by))
        }

    def _needs_you(self, outcome: CallOutcome, reference: str) -> dict[str, object]:
        """Which case of needing a yes applies to a call (ADR-0321 §2:10).

        A call is offered for asking, under ``reference``, only where the activation can
        ask, its request was handed on, and it is not already asked about: by an earlier
        question still waiting (§4:11) or by an earlier round of this activation.
        """
        shown: dict[str, object] = {}
        request = outcome.request
        earlier = None if request is None else self._asked_earlier(request)
        if not self._can_ask():
            shown["outcome"] = _NO_ONE_TO_ASK
        elif outcome.already_asked is not None:
            shown["outcome"] = _ALREADY_ASKED
        elif earlier is not None:
            shown["outcome"] = _ALREADY_ASKED
            number, asked = earlier
            shown["asked_in"] = f"round {number}'s question, part {asked.part}"
        elif request is None:
            shown["outcome"] = _UNSHOWABLE
        else:
            shown["outcome"] = _NEEDS_YES
            shown["ask_as"] = reference
            self.askable[reference] = outcome
            shown |= self._replacing(outcome.replaces)
        if outcome.reason is not None:
            shown["because"] = outcome.reason
        return shown

    def _can_ask(self) -> bool:
        """Whether a question can reach anyone: the origin takes a message (ADR-0321 §7:3)."""
        return self._inputs.place.takes_message

    def _replacing(self, replaces: Sequence[Memory]) -> dict[str, object]:
        """What a remember's question would show it replacing, as planning may see it."""
        shown: dict[str, object] = {}
        kept = _shown_replaced(replaces)
        if kept:
            shown["replacing"] = [self._memory(record) for record in kept]
        withheld = len({record.id for record in replaces} - {record.id for record in kept})
        if withheld:
            shown["not_replacing"] = _not_replacing(withheld)
        return shown

    def still_askable(self, carried: Mapping[str, tuple[str, str]]) -> dict[str, CallOutcome]:
        """Those of ``carried`` that may still be asked about, each as its outcome is now.

        Each is read afresh from the round's inputs, by its round and call id, so a
        request the inputs no longer hand on, such as a pin whose memory was forgotten
        (ADR-0338 §8:6), names nothing. One still needing a yes may be asked about where
        a question can be asked, no question waits on it (ADR-0321 §4:11), and no round
        of this activation has asked about it since.
        """
        now = {(one.round_id, one.call_id): one for one in self._inputs.outcomes}
        kept: dict[str, CallOutcome] = {}
        for reference, key in carried.items():
            outcome = now.get(key)
            if outcome is None or not self._can_ask():
                continue
            request = outcome.request
            if (
                outcome.kind is CallOutcomeKind.NEEDS_YOU
                and request is not None
                and outcome.already_asked is None
                and self._asked_earlier(request) is None
            ):
                kept[reference] = outcome
        return kept

    def _asked_earlier(self, request: ActionRequest) -> tuple[int, AskedCall] | None:
        """The earlier round of this activation that asked about this call, if one did."""
        for number, asked in self._asked_before:
            if _same_call(asked, request):
                return number, asked
        return None

    def _approved(self, one: ApprovedAction) -> str:
        """An approved action under its A label, with the details its question showed."""
        call = one.call
        return _tag(
            "approved",
            [
                ("label", self._book.label(LabelKind.APPROVED_ACTION, _approved_id(one.part))),
                ("from", _SYSTEM),
                ("approved", _APPROVED_BY),
            ],
            exact_line(call, filled=_filled(self._inputs.capabilities, call)),
        )

    def _searched(self, outcome: CallOutcome) -> dict[str, object]:
        """A memory search's result: its records not outside, and where the rest went."""
        records = [
            self._memory(record)
            for record in outcome.records or ()
            if not record.rests_on_outside_content
        ]
        shown: dict[str, object] = {"remembered": records or _NONE_FOUND}
        if outcome.digested:
            shown["resting_on_outside_content"] = _DIGESTED_RESULT
        return shown

    def _candidate(self, candidate: RecordedCandidate) -> dict[str, object]:
        """A candidate's result: recorded, with the memories like it (ADR-0329 §4, §6:5)."""
        shown: dict[str, object] = {"candidate": _CANDIDATE_PENDING}
        if candidate.similar is None:
            shown["similar_memories"] = _SIMILAR_UNREAD
            return shown
        similar = [
            self._memory(record)
            for record in candidate.similar
            if not record.rests_on_outside_content
        ]
        shown["similar_memories"] = similar or _NONE_FOUND
        return shown


def short_view(  # noqa: PLR0913 — the projection, its label, and how its parts are named and bounded
    projection: EpisodeProjection,
    label: str,
    *,
    naming: _Naming,
    at: Callable[[datetime], str],
    place: Callable[[LabelKind, str], str | None],
    notes_bound: int = SHORT_VIEW_NOTES,
    in_place: _InPlace | None = None,
    extra: Sequence[tuple[str, str]] = (),
) -> tuple[list[str], bool]:
    """An episode's short view: the one rendering of another episode (ADR-0356 §9).

    Short-term memory, recall, a matter and origin memory show another episode through
    it, and so does a look-up that shows an episode (ADR-0358 §7:2, §9:2). It is a
    selection of the episode's own recorded parts, made from its projection alone (§9:1):
    an ``episode`` container under its ``E`` label holding its ``input``, its
    ``understood`` meaning, then, in the order recorded, each round's ``notes``, a ``did``
    for each call whose entry records an effect, and a ``took_in`` for each input it took
    in, with its ending as the container's ``ended`` attribute. Look-ups and every call
    with no effect are left out (§9:2); a round recorded before the decision shows its
    message as a ``did`` (§9:3); the oldest notes past ``notes_bound`` are left out, and the
    view says how many (§9:4); and on a pass that may not be shown records placed for the
    owner alone, the projection holds no notes and no call, so none is shown (§9:5). A part
    resting on outside content is marked, and never shown raw (§9:6); no thinking is ever
    shown (§9:7).

    Args:
        projection: The episode's projection, under the reader's audience.
        label: Its ``E`` label.
        naming: How its parties are named.
        at: How an instant is written, in the work's zone.
        place: The label a place holds, where it holds one.
        notes_bound: How many rounds' notes are shown, the newest kept.
        in_place: Which of its texts another section shows whole, which are pointed at.
        extra: Further attributes of the container, each a fact the record holds.

    Returns:
        Its lines, and whether it showed outside content.
    """
    attributes, marked = _view_attributes(projection, label, at=at, extra=extra)
    tags = _view_input(projection, naming, in_place)
    if projection.meaning is not None:
        tags.append(_tag("understood", [("from", _SYSTEM)], projection.meaning))
    parts, cut, parts_marked = _view_parts(
        projection, naming, place=place, notes_bound=notes_bound, in_place=in_place
    )
    tags.extend(parts)
    # ADR-0329 §6:9: an unprocessed episode's candidates, each by its fact, marked pending.
    tags.extend(
        _projected_tag("candidate", _SYSTEM, one, [("from", _SYSTEM), ("pending", "yes")])
        for one in projection.candidates
    )
    if cut:
        notes = "round's notes" if cut == 1 else "rounds' notes"
        attributes.append(
            ("notes_left_out", f"{cut} older {notes}, which an episode look-up reads")
        )
    return _container("episode", attributes, tags), marked or parts_marked


def _view_attributes(
    projection: EpisodeProjection,
    label: str,
    *,
    at: Callable[[datetime], str],
    extra: Sequence[tuple[str, str]],
) -> tuple[list[tuple[str, str]], bool]:
    """A short view's container attributes, and whether its episode rests on outside content."""
    attributes: list[tuple[str, str]] = [("label", label)]
    if projection.channel is not None:
        attributes.append(("origin", _origin_name(projection.channel)))
    attributes.append(("at", at(projection.occurred_at)))
    ended = _ended(projection.status, projection.reason)
    if ended is not None:
        attributes.append(("ended", ended))
    recorded = projection.status is not None
    outside = projection.derived_from_external or (
        recorded and parties_are_outside(projection.parties, relayed=projection.relayed)
    )
    if outside:
        attributes.append(("outside", "yes"))
    attributes.extend(extra)
    return attributes, outside


def _view_input(
    projection: EpisodeProjection, naming: _Naming, in_place: _InPlace | None
) -> list[str]:
    """A short view's ``input``: its words, withheld, or pointing at where they are shown."""
    word = _words_tag(projection.parties, relayed=projection.relayed)
    writer = naming.parties(projection.parties) if projection.parties else naming.who
    if in_place is not None and in_place.input:
        return [_tag("input", [("shown_in", in_place.section)], None)]
    if projection.input is None:
        if projection.status is None:
            return []
        held = _withheld_tag(word, writer)
    else:
        held = _projected_tag(word, writer, projection.input)
    return ["\n".join(_container("input", [], [held]))]


def _view_parts(
    projection: EpisodeProjection,
    naming: _Naming,
    *,
    place: Callable[[LabelKind, str], str | None],
    notes_bound: int,
    in_place: _InPlace | None,
) -> tuple[list[str], int, bool]:
    """A short view's notes, ``did`` and ``took_in`` tags, in the order they happened.

    Each round's parts at its position: its notes, then a message an older round wrote,
    then each call with an effect in the round's call order; each input taken in before
    the round it was taken before (ADR-0356 §9:1-§9:4).

    Returns:
        The tags, how many rounds' notes the bound left out, and whether any is marked.
    """
    marked = False
    parts: list[tuple[int, int, int, str]] = []
    with_notes = [one for one in projection.rounds if one.notes is not None]
    cut = max(0, len(with_notes) - notes_bound)
    dropped = {one.position for one in with_notes[:cut]}
    for one in projection.rounds:
        if one.notes is not None and one.position not in dropped:
            attributes = [("from", _SYSTEM)]
            if one.notes_marked:
                attributes.append(("outside", "yes"))
                marked = True
            parts.append(
                (one.position, 0, 0, _projected_tag("notes", _SYSTEM, one.notes, attributes))
            )
        if one.message is not None:
            parts.append((one.position, 1, 0, _old_message_did(one, in_place)))
    for call in projection.calls:
        if not call.effect:
            continue
        attributes = [("from", _SYSTEM)]
        if call.marked:
            attributes.append(("outside", "yes"))
            marked = True
        shown = in_place is not None and (call.position, call.index) in in_place.delivered
        did = _tag("did", attributes, _did_text(call, place, shown=shown))
        parts.append((call.position, 2, call.index, did))
    for join in projection.joined:
        word = _words_tag(join.parties, relayed=join.relayed)
        writer = naming.parties(join.parties)
        held = (
            _withheld_tag(word, writer)
            if join.input is None
            else _projected_tag(word, writer, join.input)
        )
        parts.append((join.position, -1, 0, "\n".join(_container("took_in", [], [held]))))
    parts.sort(key=lambda one: (one[0], one[1], one[2]))
    return [one[3] for one in parts], cut, marked


def _digests_by_call(
    calls: Sequence[ProposedCall],
    outcomes: Mapping[str, CallOutcome],
    fresh: Sequence[tuple[int, DigestedEvidence]],
) -> dict[str, list[tuple[int, DigestedEvidence]]]:
    """Each digested call's digests, each digest given to one call (ADR-0356 §5:4).

    Two calls can read one result, a search and a follow-up of it (ADR-0308 §6:7): a
    digest goes to the call whose *looking for* it answered, and otherwise, in the calls'
    order, one to each, the last call of a result taking what is left.
    """
    digested = [
        (call, outcome.result_id)
        for call in calls
        if (outcome := outcomes.get(call.call_id)) is not None
        and outcome.digested
        and outcome.result_id is not None
    ]
    taken: set[int] = set()
    given: dict[str, list[tuple[int, DigestedEvidence]]] = {}
    for call, result_id in digested:
        wanted = call.arguments.get(LOOKING_FOR)
        matched = [
            (at, one)
            for at, one in fresh
            if one.result_id == result_id and at not in taken and one.question == wanted
        ]
        given[call.call_id] = matched
        taken.update(at for at, _ in matched)
    for number, (call, result_id) in enumerate(digested):
        if given[call.call_id]:
            continue
        left = [(at, one) for at, one in fresh if one.result_id == result_id and at not in taken]
        last = all(other != result_id for _, other in digested[number + 1 :])
        held = left if last else left[:1]
        given[call.call_id] = held
        taken.update(at for at, _ in held)
    return given


def _profile_of(profile: Profile | None) -> tuple[tuple[str, str | None], ...]:
    """A person's fields, each by name; none where there is no profile."""
    if profile is None:
        return ()
    return tuple((one.value, profile.value(one)) for one in ProfileField)


def _projected_tag(
    name: str,
    writer: str,
    text: ProjectedText,
    attributes: Sequence[tuple[str, str]] | None = None,
) -> str:
    """A projected text in a text tag, marked ``cut`` where the excerpt bound cut it."""
    held = list(attributes) if attributes is not None else [("from", writer)]
    if text.cut:
        held.append(("cut", "yes"))
    return _tag(name, held, text.text)


def _old_message_did(one: ProjectedRound, in_place: _InPlace | None) -> str:
    """A message a round recorded before ADR-0356 wrote, as a ``did`` (§9:3)."""
    message = one.message
    assert message is not None  # noqa: S101 — the caller reads a round with a message
    if in_place is not None and one.position in in_place.messages:
        return _tag("did", [("from", _SYSTEM), ("shown_in", in_place.section)], "a message")
    text = f"a message: {message.text}" + ("…" if message.cut else "")
    return _tag("did", [("from", _SYSTEM)], text)


def _messages_in_place(
    record: EpisodicMemory, written: Sequence[str]
) -> tuple[frozenset[int], frozenset[tuple[int, int]]]:
    """Which of an episode's messages one of ``written`` is, whole, the latest first.

    ADR-0276 §3 (#2951): decided over the episode's own whole texts, never the
    projection's cut ones: a round's text, for a round recorded before ADR-0356, and each
    message call's delivered words, from its entry. Each item of the window stands for
    one message, and the window is the conversation's most recent part, so the latest
    messages claim the items first.

    Returns:
        The rounds whose message is shown, by position; and the message calls whose words
        are, by their round's position and their place among its calls.
    """
    processing = record.processing_record
    if processing is None or not written:
        return frozenset(), frozenset()
    order: list[tuple[tuple[int, int, int], str]] = []
    position = {one.id: at for at, one in enumerate(processing.rounds)}
    for at, one in enumerate(processing.rounds):
        if one.text.strip():
            order.append(((at, 1, 0), one.text))
    for entry in processing.call_records:
        round_at = position.get(entry.round)
        if entry.delivered is None or round_at is None:
            continue
        calls = [one.call_id for one in processing.rounds[round_at].calls]
        index = calls.index(entry.call_id) if entry.call_id in calls else 0
        order.append(((round_at, 2, index), entry.delivered.words))
    unclaimed = Counter(written)
    messages: set[int] = set()
    delivered: set[tuple[int, int]] = set()
    for key, text in sorted(order, reverse=True):
        if unclaimed[text]:
            unclaimed[text] -= 1
            if key[1] == 1:
                messages.add(key[0])
            else:
                delivered.add((key[0], key[2]))
    return frozenset(messages), frozenset(delivered)


def _did_text(
    call: ProjectedCall,
    place: Callable[[LabelKind, str], str | None],
    *,
    shown: bool = False,
) -> str:
    """What a call with an effect did, as its round recorded it, with what came of it (§9:2)."""
    outcome = "Its outcome is not recorded" if call.outcome is None else _DID_TEXT[call.outcome]
    if call.reason is not None:
        outcome = f"{outcome}: {call.reason}"
    delivered = call.delivered
    if delivered is not None:
        where = place_of(delivered.went)
        went = place(LabelKind.PLACE, where) or _origin_name(delivered.went)
        how = delivered.status.value
        why = "" if delivered.reason is None else f": {delivered.reason}"
        if shown:
            by = platform_name(delivered.went.channel_type)
            return (
                f"{call.capability} by {by}, into {went}, shown in the window. {_upper(how)}{why}."
            )
        return (
            f"{call.capability} by {platform_name(delivered.went.channel_type)}, into {went}: "
            f"{delivered.words} — {_upper(how)}{why}."
        )
    arguments = call.arguments.text + ("…" if call.arguments.cut else "")
    return f"{call.capability} {arguments}. {outcome}."


def _effect_text(effect: PeerEffect) -> str:
    """One effect another activation made, as its peer view shows it (§6:9)."""
    if effect.couldnt_finish:
        return PEER_COULDNT_FINISH_LINE
    unknown = effect.outcome is ToolOutcome.INDETERMINATE
    if effect.capability is not None:
        if unknown:
            return f"the tool {effect.capability} may have run; whether it did is not known"
        return f"the tool {effect.capability} ran"
    if effect.message is None:
        message = "a message"
    else:
        cut = "…" if effect.message.cut else ""
        message = f"the message: {effect.message.text}{cut}"
    return f"may have sent {message}" if unknown else f"sent {message}"


def _entry_inputs(entry: InProgressEntry) -> tuple[EntryInput, ...]:
    """A concurrent stimulus's inputs, or its one brief where its episode was never written."""
    if entry.inputs:
        return entry.inputs
    return (EntryInput(brief=entry.input, parties=entry.parties),)


def _known_parties(messages: Sequence[RecordedInputMessage]) -> tuple[SupportHolder, ...] | None:
    """An input's parties from its messages: their distinct parties, or ``None`` unknown."""
    if any(one.party is None for one in messages):
        return None
    return tuple(dict.fromkeys(one.party for one in messages if one.party is not None))


def relayed_episodes(
    records: Iterable[EpisodicMemory | Memory], *, excerpt_chars: int
) -> frozenset[str]:
    """The ids of the episodes among ``records`` whose input is relayed (ADR-0351 §5:7).

    Each read through its projection (ADR-0284 §8:3), whose relay mark is its latest
    understanding version's (§5:11, §8:4), and counted only where the mark counts. An
    open episode is never projected (ADR-0286 §6), so its mark is read off its record as
    the projection reads it: the trigger's parties and the latest version's mark.
    """
    return frozenset(
        record.id
        for record in records
        if isinstance(record, EpisodicMemory) and _input_relayed(record, excerpt_chars)
    )


def _input_relayed(record: EpisodicMemory, excerpt_chars: int) -> bool:
    """Whether ``record``'s input is relayed where the mark counts (ADR-0351 §5:7, §5:11)."""
    processing = record.processing_record
    if processing is not None and processing.is_open:
        latest = processing.understanding[-1] if processing.understanding else None
        return relay_mark_counts(
            processing.trigger.parties, relayed=latest is not None and latest.relayed
        )
    projected = project_episode(record, excerpt_chars=excerpt_chars)
    return relay_mark_counts(projected.parties, relayed=projected.relayed)


def _input_of(record: EpisodicMemory) -> str | None:
    """An episode's whole input, as :func:`project_episode` reads it before cutting it."""
    processing = record.processing_record
    if processing is None:
        return record.content
    payload = processing.trigger.payload
    return payload.text if isinstance(payload, RecordedTextInput) else payload.transcript


def _offers_story_reads(offered: Sequence[OfferedTool]) -> bool:
    """Whether a story read is among the round's offered tools (#2893, #2944)."""
    return any(tool.name == _READ_STORY for tool in offered)


#: What an episode look-up's result says of outside content and of a matter's summary.
_OUTSIDE: Final = "rests on outside content: what a source reported, never what anyone said"
_NO_SUMMARY: Final = "none written yet"
_NO_LINES: Final = "the summary has no line"
#: ADR-0304 §4:2: a summary withheld from this pass's audience, and the view says so.
_SUMMARY_WITHHELD: Final = (
    "withheld: this story has a summary, which this audience may not be shown"
)


def _text(projected: ProjectedText) -> str:
    """A projected text, saying where the excerpt bound cut it."""
    if projected.cut:
        return f"{projected.text}… (cut: {len(projected.text)} of {projected.full_chars} chars)"
    return projected.text


def _place_text(channel: ChannelIdentity) -> str:
    """A place, as a full view names where an input came from: channel and place."""
    return f"{channel.channel_type}:{channel.instance_id}"


#: What the episode look-ups' results say (ADR-0358 §6-§10).
_HISTORY_UNREADABLE: Final = "this place's older history cannot be read here"
_NOTHING_OLDER: Final = "nothing older: the place window already showed all this place holds"
_STILL_RUNNING: Final = (
    "the work is still running, so its record is not frozen: look up the running "
    "activation's findings instead"
)
_RECORD_GONE: Final = "its record is no longer kept"
_NOT_KEPT: Final = "no longer kept"
_REST_NOT_KEPT: Final = "the rest of what it showed is no longer kept"
_SHOWED_NOTHING: Final = "nothing"
_NO_OUTCOME: Final = "no outcome recorded"
_AS_HELD_NOW: Final = "as it is held now, not as it was then"
_JOIN_WITHHELD: Final = "an outside report, not shown"

#: What came of another episode's call, in its full view (ADR-0358 §10:3).
_FULL_OUTCOME_TEXT: Final = {
    CallOutcomeKind.DONE: "done",
    CallOutcomeKind.NOT_DONE: "not done",
    CallOutcomeKind.UNKNOWN: "unknown: it may or may not have happened",
    CallOutcomeKind.REFUSED: "refused before it ran",
    CallOutcomeKind.NEEDS_YOU: "needed the user's yes",
}


def _next_page(page: int) -> str:
    """What a look-up's result says where there is more past the page it shows (§6:6)."""
    return f"there is more: call again with {PAGE_ARGUMENT} {page + 1} for the next page"


def _elided(count: int) -> str:
    """What the full view says of the understanding versions the record elided (§10:9)."""
    return f"{count} earlier version{'s' if count != 1 else ''} of understanding no longer kept"


def _more_older(count: int, page: int) -> str:
    """What a story read says of the older notes beyond the page it shows (#2893)."""
    return (
        f"{count} older not shown: read the story again with "
        f"{OLDER_NOTES_PAGE_ARGUMENT} {page} for the next page"
    )


def _thawed(value: object) -> object:
    """A frozen JSON value as plain JSON, for rendering."""
    if isinstance(value, Mapping):
        return {str(key): _thawed(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [_thawed(item) for item in value]
    return value


# --- asking (ADR-0321 §2) ----------------------------------------------------------------------


def exact_line(
    call: AskedCall,
    *,
    filled: Collection[str] = (),
    numbered: bool = False,
    replacing: Sequence[str] = (),
    worded: Mapping[str, str] | None = None,
) -> str:
    """The exact line a question shows for one call (ADR-0321 §2:5-§2:6, §5:5).

    One renderer for every capability. It names the capability and lists every argument
    the call sends, in the order the call carries them, each value as its JSON text, so
    a string is quoted whole and a line break in it stays on the line; a name that is not
    a plain identifier is quoted the same way. It leaves out the
    arguments the hub fills in, ``filled`` (the declaration's ``system_supplied``), and,
    wherever the call carries them, the *looking for* argument and the *deliberate
    repeat* mark. Where the message asks about several calls the line starts with its
    number, which is the call's part.

    Args:
        call: The call asked about, as the round records it.
        filled: The arguments the hub fills in for its capability.
        numbered: Whether the line carries its part's number.
        replacing: For a remember, the statements its question shows it replacing, each
            shown after the arguments as "replacing".
        worded: For an argument naming a memory by its id, as a ``pin``'s does, the
            memory's wording, which the line shows in that argument's place, as the
            argument the call sends (ADR-0338 §8:6).

    Returns:
        The line, with no line break in it.
    """
    left_out = _NEVER_SHOWN | frozenset(filled)
    shown = {} if worded is None else worded
    arguments = [
        f"{_name_text(name)}: {_json_text(shown.get(name, value))}"
        for name, value in call.values.items()
        if name not in left_out
    ]
    if replacing:
        arguments.append("replacing " + ", ".join(_json_text(one) for one in replacing))
    line = _name_text(str(call.tool.capability))
    if arguments:
        line = f"{line} — " + "; ".join(arguments)
    return f"{call.part}. {line}" if numbered else line


#: A name an exact line shows bare: one that can carry no line break, quote or
#: delimiter of the line's own.
_BARE_NAME: Final = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _name_text(name: str) -> str:
    """A capability's or an argument's name as an exact line shows it.

    Bare where it is a plain identifier, and otherwise as its JSON text, so a name can
    never start another line or pass for a delimiter, a value or another argument.
    """
    return name if _BARE_NAME.fullmatch(name) else _json_text(name)


#: Every character :meth:`str.splitlines` breaks a line at, each as its JSON escape. JSON
#: escapes those below U+0020 itself; the rest it would write as they are.
_LINE_BREAKS: Final = str.maketrans(
    {
        chr(code): f"\\u{code:04x}"
        for code in (0x0A, 0x0D, 0x0B, 0x0C, 0x1C, 0x1D, 0x1E, 0x85, 0x2028, 0x2029)
    }
)


def _json_text(value: object) -> str:
    """A value as its JSON text, on one line, with its characters as written.

    A character that would break the line is written as its JSON escape, so the text
    still decodes to the value whole.
    """
    return json.dumps(_thawed(value), ensure_ascii=False).translate(_LINE_BREAKS)


def _canonical(value: object) -> str:
    """A model's or a value's JSON form with its keys sorted, for comparing as JSON."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _filled(capabilities: Sequence[ToolDefinition], call: AskedCall) -> frozenset[str]:
    """The arguments the hub fills in for an asked call's capability (ADR-0306 §2:10).

    Those its offered declaration names, the first by id as :func:`offered_tools`
    describes the capability, and those the selected declaration itself names. Never
    more: an argument left out of an exact line is one the user is not shown.

    **Every argument, where the capability is not offered on this pass** — fail closed.
    Which arguments the hub filled is known only from the offered copy, so where there
    is none the hub cannot say, and a saved call's line shows its capability alone: a
    forecast read approved before its forecaster was unconfigured renders no coordinate
    to the model (ADR-0260 §3:2, ADR-0324 §3), and a search's no origin. Such a call
    runs nowhere either, since authorizing finds no tool for a capability not offered.
    """
    capability = str(call.tool.capability)
    offered = next(
        (
            tool
            for tool in sorted(capabilities, key=lambda one: str(one.id))
            if str(tool.capability) == capability
        ),
        None,
    )
    if offered is None:
        return frozenset(call.values)
    return frozenset({*call.tool.system_supplied, *offered.system_supplied})


def _same_call(asked: AskedCall, request: ActionRequest) -> bool:
    """Whether a request is the call an asked call records: tool, values and binding."""
    return _same_request(asked.request, request)


def _same_request(one: ActionRequest, other: ActionRequest) -> bool:
    """Whether two requests are one call: the same tool, values and binding (§4:4).

    Compared as JSON, never by Python equality, which holds ``true`` equal to ``1``, and
    never by key order, which a rebuilt declaration need not keep: the values by the
    request's own canonical digest, the tool and the binding by their JSON forms with
    their keys sorted.
    """
    return (
        one.parameters_digest == other.parameters_digest
        and _canonical(one.tool.model_dump(mode="json"))
        == _canonical(other.tool.model_dump(mode="json"))
        and _binding_json(one) == _binding_json(other)
    )


def _binding_json(request: ActionRequest) -> str | None:
    """A request's binding as its sorted JSON form, or ``None`` where it has none."""
    binding = request.egress_binding
    return None if binding is None else _canonical(binding.model_dump(mode="json"))


def _shown_replaced(replaces: Sequence[Memory]) -> tuple[Memory, ...]:
    """The replaced assertions a question shows: each once, none resting on outside content.

    A question's text is the round's, replayed to every later round and, once written,
    in the place window, so an assertion resting on outside content is not shown in it
    (ADR-0307 §9:2), and so it is not retired on the yes (ADR-0321 §5:5).
    """
    kept: dict[str, Memory] = {}
    for record in replaces:
        if not record.rests_on_outside_content:
            kept.setdefault(record.id, record)
    return tuple(kept.values())


@dataclass(frozen=True, slots=True)
class _Asked:
    """One call a round's asking message asks about, and what its question shows beside it.

    ``replacing`` is the assertions it replaces; ``worded`` the wording an argument
    naming a memory is shown by (ADR-0338 §8:6).
    """

    call: AskedCall
    replacing: tuple[str, ...] = ()
    worded: tuple[tuple[str, str], ...] = ()


def _asked_calls(names: Sequence[str], askable: Mapping[str, CallOutcome]) -> tuple[_Asked, ...]:
    """The calls the round's asking message asks about, from the references it named.

    ADR-0357 §8:1, §8:5. In the order named, each part its place in that order (ADR-0321
    §2:6). A name that resolves to no call this round may ask about is dropped, and so is
    one naming the same call, by tool, values and binding, as a name before it: the
    question shows a call once. A call whose values and binding make no request its
    declaration admits cannot be recorded as asked about (§2:8), and is dropped as well.
    A remember's replaced assertions are recorded by id and shown by statement, exactly
    the same ones (§5:5), which are those :func:`_shown_replaced` keeps.
    """
    chosen: list[tuple[ActionRequest, CallOutcome]] = []
    for name in names:
        outcome = askable.get(name.strip())
        request = None if outcome is None else outcome.request
        if outcome is None or request is None:
            _log.info("planning_ask_dropped", stage="planning", reason="names_nothing")
            continue
        if any(_same_request(earlier, request) for earlier, _ in chosen):
            _log.info("planning_ask_dropped", stage="planning", reason="named_twice")
            continue
        chosen.append((request, outcome))
    asked: list[_Asked] = []
    for request, outcome in chosen:
        replaced = {record.id: record.content for record in _shown_replaced(outcome.replaces)}
        try:
            call = AskedCall(
                part=len(asked) + 1,
                tool=request.tool,
                values=request.parameters,
                binding=request.egress_binding,
                deliberate_repeat=outcome.deliberate_repeat,
                replaces=tuple(replaced),
            )
        except ValueError:
            _log.info("planning_ask_dropped", stage="planning", reason="unrecordable")
            continue
        asked.append(_Asked(call, tuple(replaced.values()), outcome.worded))
    return tuple(asked)


def _question_lines(asked: Sequence[_Asked], capabilities: Sequence[ToolDefinition]) -> str:
    """The exact lines for the calls an asking message asks about (ADR-0321 §2:5-§2:6).

    One line each, in their parts' order, numbered where there are several. The phases
    put them under the fixed line, after the message's words as reworded (ADR-0357 §8:2).
    """
    return "\n".join(
        exact_line(
            one.call,
            filled=_filled(capabilities, one.call),
            numbered=len(asked) > 1,
            replacing=one.replacing,
            worded=dict(one.worded),
        )
        for one in asked
    )


def _asking(calls: Sequence[ProposedCall]) -> ProposedCall | None:
    """The round's asking message: its first ``text`` call carrying ``asks`` (§8:1, §8:3)."""
    return next((one for one in calls if carries_asks(one.name, one.arguments)), None)


def _question_sent(planning_round: PlanningRound, outcomes: Sequence[CallOutcome]) -> bool:
    """Whether a round that asked about calls sent the question (ADR-0357 §8, §3:3).

    Its asking ``text`` call sent it where that call is done. One failed, unknown, refused
    or with no outcome yet did not show it, so nothing waits on it (ADR-0321 §2:2). A
    round that asks about nothing, or whose question its own message carried, as rounds
    recorded before the asking ``text`` call did, keeps what it recorded.
    """
    if not planning_round.asked:
        return True
    asking = _asking(planning_round.calls)
    if asking is None:
        return True
    return any(
        one.round_id == planning_round.id
        and one.call_id == asking.call_id
        and one.kind is CallOutcomeKind.DONE
        for one in outcomes
    )


def _approved_id(part: QuestionPart) -> str:
    """What an approved action's A label names: the question's part, by round and number."""
    return f"{part.round}#{part.part}"


def _approved_tool(
    approved: Mapping[str, ApprovedAction], offered: Sequence[OfferedTool]
) -> OfferedTool | None:
    """The tool an approved action is proposed through, where one is approved (§4:2).

    Its one argument names the action by its A label; a *looking for* is offered beside
    it where an approved call's result may carry outside text. Not offered where a
    capability already takes its name.
    """
    if not approved:
        return None
    if any(tool.name == APPROVED_ACTION_TOOL for tool in offered):
        _log.info("planning_approved_not_offered", stage="planning", reason="name_taken")
        return None
    properties: dict[str, Any] = {
        APPROVED_ACTION_ARGUMENT: {
            "type": "string",
            "enum": list(approved),
            "description": "The approved action, by the A label you were shown it under.",
        }
    }
    if any(
        one.call.tool.result is CapabilityResult.MAY_CARRY_OUTSIDE_TEXT for one in approved.values()
    ):
        properties[LOOKING_FOR] = dict(_LOOKING_FOR_SCHEMA)
    return OfferedTool(
        name=APPROVED_ACTION_TOOL,
        description=(
            "Carry out an action the user approved with their yes, by its A label alone. "
            "Its values are the ones the user approved, filled in for you."
        ),
        parameters={
            "type": "object",
            "properties": properties,
            "required": [APPROVED_ACTION_ARGUMENT],
            "additionalProperties": False,
        },
    )


# --- judging the round's calls -------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Judge:
    """Planning's check of a round's calls before authorizing (§5:3 to §5:4)."""

    offered: Mapping[str, ToolDefinition]
    label_arguments: Mapping[str, Mapping[str, LabelKind]]
    book: _LabelBook
    approved: Mapping[str, ApprovedAction] = field(default_factory=dict)
    """The approved actions, by the id their A label names, where the tool was offered."""
    capabilities: Sequence[ToolDefinition] = ()
    not_here: Mapping[str, str] = field(default_factory=dict)
    """Why each capability whose condition does not hold here cannot run (ADR-0356 §4:4)."""
    waited: frozenset[str] | None = None
    """On a waiting round, the episodes of the activations it waits on, which a stop may
    name (§4:5, ADR-0349 §7:26); ``None`` on every other round."""
    asking: str | None = None
    """The round's asking message, by its call id: its first ``text`` call carrying
    ``asks`` (ADR-0357 §8:3); ``None`` where no call carries it."""

    def __call__(self, call: ProposedCall) -> PlannedCall | RefusedCall:
        if call.name == APPROVED_ACTION_TOOL and self.approved:
            return self._approved(call)
        if carries_asks(call.name, call.arguments) and call.call_id != self.asking:
            # ADR-0357 §8:3: a round has at most one asking message.
            return RefusedCall(call, ALREADY_ASKING)
        # ADR-0356 §4:4-§4:6: offered on every round, and refused, saying why, where its
        # condition for running does not hold in this activation.
        why = self.not_here.get(call.name) if call.name in self.offered else None
        if why is not None:
            return RefusedCall(call, why)
        judged = self._capability(call)
        if isinstance(judged, PlannedCall) and self._stops_elsewhere(judged.call):
            # §4:5, ADR-0349 §7:26: a waiting round's stop names work it waits on.
            return RefusedCall(call, WAITING_ROUND)
        return judged

    def _stops_elsewhere(self, call: ProposedCall) -> bool:
        """Whether ``call`` is a waiting round's stop naming work it does not wait on."""
        if self.waited is None or call.name != STOP_ACTIVATION_CAPABILITY:
            return False
        named = self.label_arguments.get(call.name, {})
        return any(
            kind is LabelKind.EPISODE and call.arguments.get(argument) not in self.waited
            for argument, kind in named.items()
        )

    def _capability(self, call: ProposedCall) -> PlannedCall | RefusedCall:
        """A call to an offered capability, its labels replaced by ids (§5:3-§5:4)."""
        tool = self.offered.get(call.name)
        if tool is None:
            return RefusedCall(call, "no capability of that name was offered")
        arguments: dict[str, Any] = dict(call.model_dump()["arguments"])
        named = [name for name in tool.system_supplied if name in arguments]
        if named:
            return RefusedCall(call, f"the hub fills {named[0]!r}; leave it out")
        looking_for: str | None = None
        if tool.result is CapabilityResult.MAY_CARRY_OUTSIDE_TEXT:
            looking_for = arguments.pop(LOOKING_FOR, None)
            if not isinstance(looking_for, str) or not looking_for.strip():
                return RefusedCall(call, f"{LOOKING_FOR!r} must say what you are looking for")
        deliberate = False
        if not tool.safe_to_repeat and DELIBERATE_REPEAT in arguments:
            mark = arguments.pop(DELIBERATE_REPEAT)
            if not isinstance(mark, bool):
                return RefusedCall(call, f"{DELIBERATE_REPEAT!r} is true or false")
            deliberate = mark
        for argument, kind in self.label_arguments.get(call.name, {}).items():
            if argument not in arguments:
                continue
            mapped = self._mapped(arguments[argument], kind)
            if isinstance(mapped, str):
                return RefusedCall(call, mapped)
            arguments[argument] = mapped[0]
        planned = ProposedCall(call_id=call.call_id, name=call.name, arguments=arguments)
        return PlannedCall(planned, looking_for=looking_for, deliberate_repeat=deliberate)

    def _approved(self, call: ProposedCall) -> PlannedCall | RefusedCall:
        """An approved action, proposed by its A label, as the call its question showed.

        ADR-0321 §4:2: the call carries the values recorded with the question, those the
        hub fills apart, and names the part the yes approved; its deliberate-repeat mark
        is the one recorded. Nothing planning sends beside the label is taken as a
        value: anything but the label and a *looking for* refuses the call whole.
        """
        arguments: dict[str, Any] = dict(call.model_dump()["arguments"])
        label = arguments.pop(APPROVED_ACTION_ARGUMENT, None)
        if not isinstance(label, str):
            return RefusedCall(
                call, f"{APPROVED_ACTION_ARGUMENT!r} names the action by its A label"
            )
        resolved = self._id(label, LabelKind.APPROVED_ACTION)
        if isinstance(resolved, _Refusal):
            return RefusedCall(call, resolved.reason)
        action = self.approved.get(resolved)
        if action is None:
            return RefusedCall(
                call, f"{label[:_QUOTED_LABEL_CHARS]!r} names no action approved now"
            )
        looking_for = arguments.pop(LOOKING_FOR, None)
        if arguments:
            return RefusedCall(call, _APPROVED_LABEL_ALONE)
        asked = action.call
        if asked.tool.result is CapabilityResult.MAY_CARRY_OUTSIDE_TEXT:
            if not isinstance(looking_for, str) or not looking_for.strip():
                return RefusedCall(call, f"{LOOKING_FOR!r} must say what you are looking for")
        else:
            looking_for = None
        filled = _filled(self.capabilities, asked)
        values = {name: value for name, value in asked.values.items() if name not in filled}
        planned = ProposedCall(
            call_id=call.call_id, name=str(asked.tool.capability), arguments=values
        )
        return PlannedCall(
            planned,
            looking_for=looking_for,
            deliberate_repeat=asked.deliberate_repeat,
            approved_part=action.part,
        )

    def _mapped(self, value: object, kind: LabelKind) -> tuple[object] | str:
        """A label argument with its labels replaced by ids, or why it is refused."""
        if isinstance(value, str):
            return self._wrapped(self._id(value, kind))
        if isinstance(value, list | tuple):
            ids: list[str] = []
            for one in value:
                if not isinstance(one, str):
                    return f"an argument naming {_THINGS[kind][1]} takes their labels"
                resolved = self._id(one, kind)
                if isinstance(resolved, _Refusal):
                    return resolved.reason
                ids.append(resolved)
            return (ids,)
        return f"an argument naming {_THINGS[kind][1]} takes their labels"

    def _wrapped(self, resolved: str | _Refusal) -> tuple[object] | str:
        if isinstance(resolved, _Refusal):
            return resolved.reason
        return (resolved,)

    def _id(self, label: str, kind: LabelKind) -> str | _Refusal:
        """The id ``label`` names, where it names a thing of ``kind`` planning was shown."""
        quoted = label[:_QUOTED_LABEL_CHARS]
        known = self.book.resolve(label)
        if known is None:
            return _Refusal(f"{quoted!r} names nothing you were shown")
        if known.kind is not kind:
            return _Refusal(f"{quoted!r} names {_THINGS[known.kind][0]}, not {_THINGS[kind][0]}")
        return known.id


@dataclass(frozen=True, slots=True)
class _Refusal:
    reason: str


#: ADR-0357 §8:3: why a second ``text`` call carrying ``asks`` in a round runs nothing.
ALREADY_ASKING: Final = (
    "the round's question is already asked, by an earlier text call carrying asks: a round "
    "asks one question, so every call it asks about goes in that one message"
)


#: ADR-0356 §4:5, ADR-0349 §7:26: why a call on a waiting round runs nothing, unless it
#: is a message call or a stop naming the work the round waits on.
WAITING_ROUND: Final = (
    "this round waits on running work: only a message, or a stop naming the work it "
    "waits on, runs now; anything else waits for the next round"
)


#: ADR-0321 §4:2: an approved action is proposed by its label, and its values are the
#: recorded ones.
_APPROVED_LABEL_ALONE: Final = (
    "an approved action is proposed by its label alone: its values are the ones the user approved"
)


# --- the stage -------------------------------------------------------------------------------


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _new_round_id() -> str:
    return f"round:{uuid4().hex}"


class PlanningStage:
    """Run one planning round and record it with the episode (ADR-0307)."""

    def __init__(  # noqa: PLR0913 — the model seam, the writer seam, the bound, the instruction, the model override, the two sources a round's record reads and the diagnostic sink
        self,
        *,
        completer: ToolCallingCompleter,
        recorder: RoundRecorder,
        excerpt_chars: int,
        prompt: PromptTemplate,
        model: str | None = None,
        now: Callable[[], datetime] = _utcnow,
        timezone: str = "UTC",
        new_id: Callable[[], str] = _new_round_id,
        diagnostics: DiagnosticSink | None = None,
        short_view_notes: int = SHORT_VIEW_NOTES,
    ) -> None:
        """Wire the stage to its seams.

        Args:
            completer: The native tool-calling seam a round is asked through.
            recorder: The seam that appends a round to the episode.
            excerpt_chars: The bound :func:`project_episode` cuts an episode's texts to.
            prompt: The template of :data:`PLANNING_PROMPT`, default or override, as the
                composition root read it at start (ADR-0334 §3:4, §3:5). Every round
                renders its system message from it.
            model: Optional ``"provider:model"`` override for planning's rounds.
            now: The clock the current time and ``recorded_at`` are read from.
            timezone: The IANA name of the zone the request shows the current time in,
                with its offset and the name beside it (#2964): ``Settings.timezone``,
                the hub's default, where the activation's person block sets no zone of
                theirs (ADR-0338 §3:6). ``recorded_at`` stays UTC.
            new_id: Mints a round's id.
            diagnostics: The diagnostic record's write seam (ADR-0314 §4:4): the
                rendered request and the offered tools before each round, and the
                returned entry where no response came back (§5:2); ``None`` where the
                record is off.
            short_view_notes: How many rounds' notes an episode's short view shows,
                the oldest left out past it (ADR-0356 §9:4).

        Raises:
            ValueError: If ``excerpt_chars`` or ``short_view_notes`` is below 1, or
                ``prompt`` is not a template of :data:`PLANNING_PROMPT`.
            ZoneInfoNotFoundError: If ``timezone`` names no known zone. ``Settings``
                refuses one at load, so a composition root reaching here has already
                been validated.
        """
        if excerpt_chars < 1:
            msg = "planning's excerpt bound must be at least 1"
            raise ValueError(msg)
        if short_view_notes < 1:
            msg = "a short view shows at least one round's notes"
            raise ValueError(msg)
        self._notes_bound = short_view_notes
        if prompt.declaration != PLANNING_PROMPT:
            msg = "the planning stage renders the planning prompt (ADR-0334 §2)"
            raise ValueError(msg)
        self._prompt = prompt
        self._zone = ZoneInfo(timezone)
        self._completer = completer
        self._recorder = recorder
        self._excerpt_chars = excerpt_chars
        self._model = model
        self._now = checked_clock(now, owner="PlanningStage")
        self._new_id = new_id
        self._diagnostics = diagnostics

    def _zone_for(self, person: PersonBlock | None) -> ZoneInfo:
        """The zone the round tells the current time in (ADR-0338 §3:6, ADR-0307 §6:1).

        The person's zone where their profile sets one, and ``Settings.timezone`` where
        it is empty or the activation is no person's, which is given no block (§2:3). The
        store validates a zone on every write (§3:2), so one that does not resolve is a
        store's defect: it is logged, and the hub's zone is used.
        """
        zone = person_zone(None if person is None else person.profile, stage="planning")
        return self._zone if zone is None else zone

    async def plan(self, inputs: PlanningInputs) -> PlannedRound:
        """Run one round over ``inputs``: ask, record, then judge its calls.

        Args:
            inputs: Everything the round is given.

        Returns:
            The round, the labels it assigned, whether it was recorded, its calls for
            authorizing, the calls it refused, and the message to write.

        Raises:
            ModelError: Whatever the tool-calling seam raised; nothing is recorded.
        """
        book = _LabelBook(inputs.labels)
        offered = offered_tools(inputs.capabilities)
        work = inputs.work
        if work is None:
            # ADR-0321 §4:2: each approved action holds its A label from before the
            # request is rendered, so the tool proposing them can name every one.
            approved = {
                book.label(LabelKind.APPROVED_ACTION, _approved_id(one.part)): one
                for one in inputs.approved
            }
            approved_tool = _approved_tool(approved, offered)
            offered_here = offered if approved_tool is None else (*offered, approved_tool)
        else:
            # ADR-0356 §4:3, §5:2: every round of a work is offered what its first round
            # was, and an approved action is one its briefing showed under an A label.
            approved = {
                label: one
                for one in inputs.approved
                if (label := book.held(LabelKind.APPROVED_ACTION, _approved_id(one.part)))
            }
            offered_here = work.tools
            approved_tool = next(
                (one for one in work.tools if one.name == APPROVED_ACTION_TOOL), None
            )
        own = person_zone(
            None if inputs.person is None else inputs.person.profile, stage="planning"
        )
        request = _Request(
            inputs,
            book,
            excerpt_chars=self._excerpt_chars,
            now=self._now(),
            # ADR-0360 §2:3: every time of a work is in the zone its briefing named.
            zone=(
                ZoneInfo(work.shown.zone)
                if work is not None and work.shown.zone is not None
                else self._zone_for(inputs.person)
            ),
            own_zone=own is not None,
            notes_bound=self._notes_bound,
        )
        instruction: RenderedPrompt | None
        if work is None:
            # ADR-0356 §5:2: a work's first round renders the briefing, once, and the
            # instruction it is asked under, which every later round hands in unchanged.
            rendered = request.briefing(offered_here)
            # ADR-0356 §4:2: the instruction takes no flag and no value.
            instruction = self._prompt.rendered()
            exchange = PlanningExchange(instruction=instruction.text, briefing=rendered)
            shown = request.shown_now()
            number = 1
        else:
            # §5:1-§5:3: every later round appends the last round's response, as the
            # completer returned it, and its report; nothing earlier is re-rendered.
            report, shown = request.report(work)
            # ADR-0357 §8:1: a reference an earlier step showed may still be named, unless
            # a round of this activation has asked about its call since.
            request.askable = {**request.still_askable(work.askable), **request.askable}
            exchange = PlanningExchange(
                instruction=work.exchange.instruction,
                briefing=work.exchange.briefing,
                steps=(
                    *work.exchange.steps,
                    ExchangeStep(response=work.response, report=report),
                ),
            )
            instruction = None
            number = work.number + 1
        response = await self._responded(exchange, offered_here, instruction)
        read_outside = inputs.outside_content_read or inputs.outside_trigger or request.shown.marked
        # ADR-0356 §7:2-§7:3: the round's text is its reply to the system, kept as its
        # notes and written to no one; what people receive comes only from message calls.
        notes = response.text if response.text.strip() else None
        # ADR-0357 §8:1-§8:5: the calls the round's asking ``text`` call names in ``asks``,
        # each with its exact line, which the phases append to its words, and recorded
        # with the round. Where the place takes no message nothing is askable, so every
        # name is dropped (ADR-0321 §7:3).
        asking = _asking(response.calls)
        asked = (
            () if asking is None else _asked_calls(asks_named(asking.arguments), request.askable)
        )
        questions = (
            {}
            if asking is None or not asked
            else {asking.call_id: _question_lines(asked, inputs.capabilities)}
        )
        # §8:1: a round recorded under ADR-0356 carries no ``text``, and so no ``place``.
        planning_round = PlanningRound(
            id=self._new_id(),
            follows=inputs.rounds[-1].id if inputs.rounds else None,
            recorded_at=self._now(),
            calls=response.calls,
            notes=notes,
            notes_marked=notes is not None and read_outside,
            asked=tuple(one.call for one in asked),
        )
        labels = tuple(book.minted)
        recorded = await self._record(planning_round, labels, questions)
        declarations = _offered_declarations(inputs.capabilities, offered_here)
        judge = _Judge(
            offered=declarations,
            label_arguments=inputs.label_arguments,
            book=book,
            approved=(
                {}
                if approved_tool is None
                else {_approved_id(one.part): one for one in approved.values()}
            ),
            capabilities=inputs.capabilities,
            not_here=inputs.not_here,
            waited=(
                frozenset(episode_address(one.activation_id) for one in inputs.waiting)
                if inputs.waiting
                else None
            ),
            asking=None if asking is None else asking.call_id,
        )
        judged = [judge(call) for call in response.calls]
        refused = tuple(one for one in judged if isinstance(one, RefusedCall))
        for _ in refused:
            _log.info("planning_call_refused", stage="planning", reason="before_authorizing")
        return PlannedRound(
            round=planning_round,
            labels=labels,
            recorded=recorded,
            calls=tuple(one for one in judged if isinstance(one, PlannedCall)),
            refused=refused,
            work=PlanningWork(
                exchange=exchange,
                tools=tuple(offered_here),
                response=response,
                round_id=planning_round.id,
                number=number,
                shown=shown,
                askable={
                    reference: (outcome.round_id, outcome.call_id)
                    for reference, outcome in request.askable.items()
                },
            ),
            read_outside=read_outside,
            questions=questions,
        )

    async def _responded(
        self,
        exchange: PlanningExchange,
        offered: Sequence[OfferedTool],
        instruction: RenderedPrompt | None,
    ) -> RoundResponse:
        """Ask the round, its request written to the record first (ADR-0314 §4, §5).

        The completer writes planning's returned entry from the provider's response,
        whether or not it reads as a round (§5:2). Where it wrote none because no
        response came back, this module writes it, with the failure; the failure is
        re-raised unchanged. The given entry records the exchange as handed in
        (ADR-0356 §13:6). While the exchange is its briefing alone, it also records the
        same request as the system and user messages it is sent as, which the owner's
        replay tool and viewer read, and names the template the instruction was rendered
        from and the flags it was rendered under (ADR-0334 §8:2, ADR-0335 §9:1). Once
        the exchange has steps, those two messages are no longer the request, so they
        are left out, and the instruction is the one the first round rendered.
        """

        def given() -> dict[str, object]:
            body: dict[str, object] = {"exchange": exchange.model_dump(mode="json")}
            if not exchange.steps:
                body["messages"] = [
                    Message(role=Role.SYSTEM, content=exchange.instruction).model_dump(mode="json"),
                    Message(role=Role.USER, content=exchange.briefing).model_dump(mode="json"),
                ]
            body["tools"] = [tool.model_dump(mode="json") for tool in offered]
            if instruction is not None:
                body["prompt"] = instruction.provenance()
            return body

        await write_diagnostic(
            self._diagnostics, DiagnosticSource.PLANNING, DiagnosticKind.GIVEN, given
        )
        written = returned_written(DiagnosticSource.PLANNING)
        try:
            return await self._completer.respond(exchange, offered, model=self._model)
        except Exception as exc:
            if returned_written(DiagnosticSource.PLANNING) == written:
                await write_failure(self._diagnostics, DiagnosticSource.PLANNING, exc)
            raise

    async def _record(
        self,
        planning_round: PlanningRound,
        labels: tuple[PlanningLabel, ...],
        questions: Mapping[str, str],
    ) -> bool:
        """Append the round; a failure is a capture failure that holds nothing back (§2:4)."""
        try:
            await self._recorder.record(planning_round, labels, questions=questions)
        except Exception:  # ADR-0286 §3:7: an append never fails processing
            _log.warning("activation_capture_degraded", stage="planning", reason="append_failed")
            return False
        return True


def _offered_declarations(
    capabilities: Sequence[ToolDefinition], offered: Sequence[OfferedTool]
) -> dict[str, ToolDefinition]:
    """Each offered capability's first declaration, by id, which its tools all agree with."""
    names = {tool.name for tool in offered}
    declarations: dict[str, ToolDefinition] = {}
    for tool in sorted(capabilities, key=lambda one: str(one.id)):
        declarations.setdefault(str(tool.capability), tool)
    return {name: declaration for name, declaration in declarations.items() if name in names}
