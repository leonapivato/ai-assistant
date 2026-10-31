"""The planning stage: one planning round, recorded with the episode (ADR-0307).

One orchestration-local phase module (ADR-0309 §2:2), of the kind
:class:`~ai_assistant.orchestration.acting.ActingStage` is. It holds an injected
``ToolCallingCompleter``, a seam onto the episode writer, the excerpt bound and a
clock, and it is **not a Protocol**. Each :meth:`PlanningStage.plan` is one controller
step and one round (§2:3): it assembles planning's inputs, asks the model once, records
the round, and judges the round's calls. It runs nothing, writes no message and
decides nothing about whether a call may run (§9:1).

**A work's rounds are one continuing exchange** (ADR-0356 §5). A work's first round
renders the instruction and a briefing of one JSON object rendering planning's inputs as
quoted data, once; :class:`PlanningWork` holds that exchange, with the round's response,
and the phases hand it to the next round, which hands both in byte for byte and appends
the last round's response, as the completer returned it, and its report: one result for
each of its calls, in its order and under its ids, code's rendering of what came of it,
a digested one as its digest's evidence, then the news, what the inputs hold that the
exchange has not shown (§5:3-§5:6). Every round of a work is offered the tools its first
was (§4:3). The round's text is kept as its notes (§7:2) and, until a message is a call
(ADR-0357, ADR-0356 §14:3), is still also the round's message. The briefing's JSON and
the instruction's flags are P3's to replace (§14:3).

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
person-model store is wired, every round is shown, first and before everything that
changes from round to round, the person's five fields, the whole kept-in-mind slot and the
pending suggestions the block admits, each marked as a suggestion and never as the
profile: data, as the person's own choices, never an instruction. Its memories take their
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
:class:`RoundRecorder` before :meth:`PlanningStage.plan` returns, so its message is
written and its calls run only after the append has returned. An append that fails is
a capture failure: it is logged and holds back neither the message nor the calls.

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
the stage, and this module keeps no copy of its text (§3:1). The stage computes the
template's flags once, at a work's first round, holding to one value each that may
change between its rounds, since a work's instruction is the same on every round
(ADR-0356 §5:2), and supplies its three values; the rendered request, the tool
declarations, the judge, the exact lines and every rule above stay here, whatever a
template says (§1:3, §7:2).

**It logs stage and code-owned reason only**, never inputs, model output or arguments
(ADR-0275 §8).
"""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Final, Protocol
from uuid import uuid4
from zoneinfo import ZoneInfo

import structlog

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
    DiagnosticKind,
    DiagnosticSource,
    EpisodicMemory,
    ExchangeStep,
    HolderKind,
    LabelKind,
    MemoryMark,
    MemoryStanding,
    Message,
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
    parties_are_assistants,
    parties_are_outside,
    relay_mark_counts,
    statement_citations,
)
from ai_assistant.orchestration.channel_kinds import place_channel, place_of
from ai_assistant.orchestration.matters import (
    LOOK_UP_ACTIVATION_CAPABILITY,
    STOP_ACTIVATION_CAPABILITY,
    NotAsAsked,
)
from ai_assistant.orchestration.message_tools import (
    NEEDS_YOUR_YES,
    asks_named,
    carries_asks,
    platform_name,
)
from ai_assistant.orchestration.person_block import person_zone
from ai_assistant.orchestration.reliance import NOTE_RELIANCE_CAPABILITY
from ai_assistant.orchestration.remembering import REMEMBER_CAPABILITY
from ai_assistant.orchestration.stories import episode_address
from ai_assistant.orchestration.story_calls import (
    STORY_CALL_CAPABILITIES,
    TIDY_STORY_CAPABILITY,
)
from ai_assistant.orchestration.task_scheduler import (
    SPAWN_CAPABILITY,
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
        ChannelIdentity,
        EpisodeProjection,
        FrozenJsonValue,
        Memory,
        PeerEffect,
        PeerView,
        ProjectedText,
        QuestionPart,
        RecordedDelivery,
        RoundResponse,
        StoryNote,
        StoryStanding,
        StoryStandingEpisode,
        StorySummaryLine,
        ToolDefinition,
        UnderstandingReferent,
    )
    from ai_assistant.orchestration.person_block import KeptInMind, PersonBlock, ShownSuggestion
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
    if all(one is None for one in looked):
        if outcome.digested or outcome.result is None:
            return CallShowed()
        words = json.dumps(_thawed(outcome.result), ensure_ascii=False, sort_keys=True)
        return shown_within((ShownText(text=words),), bound)
    parts: list[ShownText | ShownRecord] = []
    history = outcome.history
    if history is not None:
        # An older message's words, as planning was shown them: a withheld one's never.
        parts.extend(
            ShownText(text=json.dumps({"from": item.author.value, "text": item.text}))
            for item in history.items
            if not history.withheld(item)
        )
    versions = _summary_versions(
        outcome, ShowingLabels() if labels is None else labels, owner_records=owner_records
    )
    parts.extend(
        ShownRecord(
            kind=_SHOWN_KINDS[one.kind],
            id=one.id,
            summary_version=versions.get(one.id) if one.kind is LabelKind.STORY else None,
        )
        for one in _labelled(outcome, owner_records=owner_records)
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


def _rendering(outcome: CallOutcome, book: _LabelBook, *, owner_records: bool) -> _Request:
    """``outcome``'s result rendered over ``book``, as planning renders it."""
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
    return request


def _labelled(outcome: CallOutcome, *, owner_records: bool) -> tuple[PlanningLabel, ...]:
    """Every thing the rendering of ``outcome``'s result names under a label, in order."""
    book = _LabelBook(())
    _rendering(outcome, book, owner_records=owner_records)
    return tuple(book.minted)


def _summary_versions(
    outcome: CallOutcome, labels: ShowingLabels, *, owner_records: bool
) -> dict[str, int]:
    """The summary version each story's summary was first rendered at (ADR-0358 §11:2).

    Read off the rendering of ``outcome``'s result under the labels planning holds, so a
    story shown twice keeps the version it was first shown at, as it keeps its one
    label; a story whose summary is withheld showed none, and one named by its label
    alone, a matter planning already held a label for among them, showed none either.
    """
    rendered = _rendering(outcome, labels._book, owner_records=owner_records)
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
            and the pending suggestions it admits, shown first in the request. ``None``
            for an activation that is no person's or where no person-model store is
            wired, which shows none and leaves the instruction as it was.
        places: The activation's place list, as built for this round (ADR-0350
            §5:10-§5:12): each place under its channel's heading and its own ``L``
            label. ``None`` for an activation not offered spawn, which is shown none.
        speaks_by_label: Whether the activation was started by the Task Scheduler, so
            its message names, by its place label, the one place on its list it goes
            into (§6:7).
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
    speaks_by_label: bool = False
    offers: tuple[OfferShown, ...] = ()
    waiting: tuple[RunningShown, ...] = ()
    declined: tuple[tuple[str, str], ...] = ()
    earlier_work: tuple[PeerShown, ...] = ()
    work: PlanningWork | None = None
    not_here: Mapping[str, str] = field(default_factory=dict)


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
    """

    offers: frozenset[str] = frozenset()
    earlier_work: Mapping[str, str] = field(default_factory=dict)
    understanding: int | None = None
    items: frozenset[PlaceItem] = frozenset()
    evidence: int = 0
    stories: frozenset[str] = frozenset()


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
        message: The text to write into the input's place, or ``None`` where the text
            is empty or the place takes no message (§3:2, §3:8).
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

#: The owner's ruling on #3094 (2026-10-16): the one fixed line code puts above the exact
#: lines it appends to a round's message, so a question never goes out as a bare line. The
#: template names it, as the line planning never writes itself.
_NEEDS_YOUR_YES: Final = NEEDS_YOUR_YES

#: Planning's instruction, the system message of every round (ADR-0334 §2): a template the
#: composition root reads at start and hands the stage, default or override. The module
#: keeps no copy of its text (§3:1). The stage computes its flags for each round and
#: supplies its values; the rendered request, the tool declarations, the judge, the
#: appended exact lines and the backstop dropping planning's own copy of the fixed line
#: stay here, whatever a template says (§1:3, §7:2).
#:
#: **Flags**, each computed from what the round offers:
#:
#: - ``takes_message``: the input's place takes a message (ADR-0307 §3:8).
#: - ``story_calls``: a story call is offered (ADR-0300 §10, ADR-0303 §9).
#: - ``story_reads``: a story read is offered, so its older notes can be read (#2893, #2944).
#: - ``approved``: the approved-action tool is offered (ADR-0321 §4:2).
#: - ``candidates``: ``remember`` is offered recording candidates (ADR-0329 §6:1-§6:5).
#: - ``reliance``: noting reliance is offered (ADR-0329 §6:8).
#: - ``person``: the activation is a person's and its person block is shown (ADR-0338
#:   §7:3); a round with none keeps the instruction it had.
#: - ``suggestions``: the person block shows a pending suggestion (§7:3, §7:8).
#: - ``spawn``: spawn is offered, with the place list it suggests from (ADR-0350 §3:4,
#:   §5:10).
#: - ``scheduled``: the activation was started by the Task Scheduler, so its message
#:   names the place it goes into by its place label (ADR-0350 §6:7).
#: - ``running_work``: the stop call or the findings look-up is offered (ADR-0349 §4:6,
#:   §6:1).
#: - ``offers``: an offer is open to this activation and shown (§7:19).
#: - ``waiting``: the round is a waiting round (§7:26).
#: - ``earlier_work``: the finished work of what this activation took over or waited on
#:   is shown (§7:10, §7:27).
#:
#: **Values**, which code owns: ``approved_action_tool``, the approved-action tool's name;
#: ``note_reliance_capability``, the reliance capability's name; and ``needs_your_yes``,
#: the fixed line code puts above the exact lines.
#:
#: **What the instruction must say**, which binds the default and every override alike
#: (ADR-0334 §7:1), and which a promotion's review reads it against (§7:3), as the
#: constants it replaced cited them: ADR-0307 §3:8's paragraph where the place takes no
#: message; that the text is the assistant's own words to the user, since there is no
#: compose step (ADR-0307 §3:3; #2852); that acting on a request is always said (ADR-0317
#: §2, §5; #2864, #3094), and empty text writes no message (ADR-0307 §3:2); how approval
#: works and the line of care (ADR-0321 §2:9-§2:11, §8:7; #2862); proposing rather than
#: asking first in words (ADR-0321 §2:11, §2:5, §2:9, §7:3; #3088); how a round asks, and
#: that the fixed line is the system's (ADR-0321 §2:1-§2:6, §2:12, §3:5, §3:8-§3:9,
#: §4:11; #3071, #3072, #3094); that an activation that cannot message asks nothing
#: (ADR-0321 §7:3); how an approved action is proposed (ADR-0321 §4:2); the story calls
#: (ADR-0300 §10, ADR-0303 §9, ADR-0307 §5:3-§5:5, §7); what a candidate is for, how eager
#: to be, when to name a memory, when to ask and how to reply (ADR-0329 §6:1-§6:5, §5:1);
#: when to note reliance (ADR-0329 §6:8); how rounds follow calls (ADR-0315 §2, §4); and,
#: under ``person``, that a field outweighs any memory stating another value for it
#: (ADR-0338 §3:10), that what the block holds is used as someone who knows the person
#: would, never recited, and the person addressed by name as a person would (§7:8), that
#: no preference, pin or field changes what is true, what is judged best or any rule, and
#: that Aether never claims to be human (§5:6), with, under ``suggestions``, that a
#: suggestion is raised only where it bears on what is being done, and only by asking
#: with a ``set_profile`` or ``pin`` call (§7:8); under ``spawn``, ADR-0350 §9:3's four
#: points and that a spawn is for work that runs later or separately; and, under
#: ``scheduled``, that the message names its one place by its place label (§6:7).
#: For the rest — the role and the quoted data, the labels, the calls, the message written
#: whole before any call (#2851) and a story read's older notes (#2893, #2944) — the
#: constants cited no clause.
PLANNING_PROMPT: Final = PromptDeclaration(
    name="planning",
    package="ai_assistant.orchestration",
    flags=frozenset(
        {
            "takes_message",
            "story_calls",
            "story_reads",
            "approved",
            "candidates",
            "reliance",
            "person",
            "suggestions",
            "spawn",
            "scheduled",
            "running_work",
            "offers",
            "waiting",
            "earlier_work",
        }
    ),
    values=frozenset({"approved_action_tool", "note_reliance_capability", "needs_your_yes"}),
)

#: The calls on running work whose instruction the ``running_work`` flag carries.
_RUNNING_WORK_CALLS: Final = frozenset({STOP_ACTIVATION_CAPABILITY, LOOK_UP_ACTIVATION_CAPABILITY})

#: The values the stage hands planning's template, every one it declares (ADR-0334 §4:2).
_PLANNING_VALUES: Final = {
    "approved_action_tool": APPROVED_ACTION_TOOL,
    "note_reliance_capability": NOTE_RELIANCE_CAPABILITY,
    "needs_your_yes": _NEEDS_YOUR_YES,
}


# --- the rendered request -------------------------------------------------------------------

_OUTSIDE: Final = "rests on outside content: what a source reported, never what the user said"
_WITHHELD_ITEM: Final = (
    "not shown: someone other than the user or the assistant wrote it, and what they wrote "
    "reaches you only through understanding's record"
)
#: A user's item of an input understanding marked relayed: outside, so never shown (§9:2).
_RELAYED_ITEM: Final = (
    "not shown: the user passed on words someone else wrote, and what they wrote reaches "
    "you only through understanding's record"
)
_NO_UNDERSTANDING: Final = "missing: understanding recorded no reading of this input"
#: A channel item understanding named that the place window cannot be shown pointing at.
_SOME_ITEM: Final = "an item of the place window"

#: A running activation understanding cited that planning is shown under no label: its
#: work, never its excerpt (ADR-0353 §10:6).
_RUNNING_UNNAMED: Final = "running work this input draws on, not shown here"
#: ADR-0308 §4:13: a failed digest records no evidence, and planning is told so.
_DIGEST_FAILED: Final = "could not be read: its digest failed, and its content is not shown"
_NOTHING_ANSWERED: Final = "nothing in it answered what was looked for"
_RECALL_DIGEST: Final = "the outside memories recall found"
_DIGESTED_RESULT: Final = "read for you by a digest, under evidence"
_NONE_FOUND: Final = "none"
#: An ended step of the Task Scheduler's that wrote no message anywhere (#3445).
_WROTE_NO_MESSAGE: Final = "wrote no message"
_STORIES_UNREADABLE: Final = "missing: the stories could not be read"
_NO_STORIES: Final = "none: this activation belongs to no story yet"
_NO_SUMMARY: Final = "none written yet"
_NO_LINES: Final = "the summary has no line"
#: ADR-0304 §4:2: a summary withheld from this pass's audience, and the view says so.
_SUMMARY_WITHHELD: Final = (
    "withheld: this story has a summary, which this audience may not be shown"
)
_NEVER_TIDIED: Final = "never"
_NONE_NEWER: Final = "none"
_NO_OLDER: Final = "none on this page"
#: #2944: beside a tidied story's summary, where a story read is offered and notes may be
#: shown, that its lines may have come from notes a story read lists by label. A summary
#: can be built from episodes alone, and planning is not told which, so the cue says
#: "may". It adds nothing to the view: it points at the full view ADR-0307 §6:5 already
#: lets planning look up.
_FROM_OLDER_NOTES: Final = (
    "what tidy-ups took in, which may include older notes: read the story to see any by "
    "their labels"
)
_NO_EPISODES: Final = "none shown"
_SHOWN_ABOVE: Final = "shown above under this label"
_NOTHING_DONE: Final = "nothing recorded"

#: The news of a report where nothing changed since the round before (ADR-0356 §5:5).
NOTHING_NEW: Final = "nothing has changed since your last round"

#: A digested result whose digest has not yet been recorded: its evidence comes as news.
_NOT_YET_READ: Final = "not read yet: its digest's evidence comes as news once it is"
_NO_MEANING: Final = "no meaning understood"
#: ADR-0276 §3 (#2951): a text of an episode the place window already shows under its label.
_IN_PLACE_WINDOW: Final = "shown in the place window under this label, not repeated here"
#: How one text is made of several messages: the chat's input of the messages it took in
#: (``ChatInput.text``) and an episode's response of the messages it wrote
#: (``PhaseWorking.outcome``) each join them with it. Were either to join otherwise, a
#: text would no longer match its items and would be shown again, never dropped.
_JOINED: Final = "\n\n"
_INHERITED: Final = "a larger matter this story is part of"
_TIDY_STARTED: Final = (
    "started: it runs on its own, and how it went is recorded on the story, not here"
)

#: Who wrote a story's note: the note's own record of its author, never its text.
_NOTE_AUTHOR_TEXT: Final = {
    StoryNoteAuthor.PLANNING: "the assistant, while working on this matter",
    StoryNoteAuthor.TIDY_UP: "the assistant, tidying this story's summary",
    StoryNoteAuthor.OWNER: "the user, writing on this story directly",
}

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

#: A found memory record, attributed by its band and never by its text (ADR-0072 §5).
_BAND_TEXT: Final = {
    BeliefBand.ASSERTED: "a remembered fact: something the user said",
    # Not "a connected source": the band also holds a memory resting on the
    # assistant's own message (ADR-0328 §4, §6), which no integration reported.
    BeliefBand.ATTESTED: "a remembered fact: something from a source, never what the user said",
    BeliefBand.DERIVED: "a remembered fact: something the assistant worked out",
}

#: A memory's standing in plain words (ADR-0328 §6:1, §15:5).
_STANDING_TEXT: Final = {
    MemoryStanding.CONFIRMED: "the user confirmed this wording",
    MemoryStanding.SAID: "the user said it",
    MemoryStanding.SOURCE: "from a source, not the user's word",
    MemoryStanding.INFERENCE: "the assistant inferred it",
}

#: A reading certainty no backing support carries (ADR-0328 §7:5).
_NOT_JUDGED: Final = "not judged"

#: ADR-0345 §12:4: a memory marked ``assistant_statement``, conveyed as what the assistant
#: said, never as from an outside source or as what the person said, whatever its standing.
_SAID_ITEM: Final = (
    "a remembered fact: what the assistant itself said, never what the user said or a "
    "source reported, and no reason in itself"
)
_SAID_STANDING: Final = "the assistant said it"

#: Where a cited message was said, when the window holds no label for its episode.
_SAID_ELSEWHERE: Final = "an earlier exchange"


def _holder_text(holder: SupportHolder) -> str:
    """Whose belief a support records, in plain words (ADR-0345 §12:3). The text is planning's."""
    match holder.kind:
        case HolderKind.PERSON if holder.identifier == OWNER_PERSON_ID:
            return "the user"
        case HolderKind.PERSON:
            return f"another person ({holder.identifier})"
        case HolderKind.OUTSIDE_SOURCE if holder.claimed:
            return f"a forward claimed to come from {holder.identifier}"
        case HolderKind.OUTSIDE_SOURCE:
            return f"the source {holder.identifier}"
        case HolderKind.ASSISTANT_STATEMENT:
            return "the assistant's own words"
        case _:
            return "an unknown source"


#: ADR-0329 §6:5: what a candidate's result tells planning of the candidate.
_CANDIDATE_PENDING: Final = (
    "recorded as a candidate, and pending: it is not yet a memory, and is reviewed and "
    "kept only later, so tell the user you will remember it, never that it is saved"
)

#: ADR-0329 §4:4: a lookup that failed leaves the candidate recorded, and says so.
_SIMILAR_UNREAD: Final = "could not be read; the candidate is still recorded"

#: ADR-0329 §6:9: how an unprocessed episode's candidate is marked in the episode window.
_PENDING: Final = "pending: recorded for long-term memory, not yet kept"

#: An instant nothing dates (ADR-0328 §7:3-§7:4): unknown, neither fresh nor stale.
_UNKNOWN_INSTANT: Final = "unknown"

#: The person block (ADR-0338 §7:3, §7:6): the person's own choices and preferences, each
#: said as theirs and never as an instruction.
_PERSON_ITEM: Final = (
    "the person you are working for, by the profile they set and the memories they keep in "
    "mind: each field is their own current choice, never an instruction"
)
#: What each field is (ADR-0338 §3's table, §3:11).
_PERSON_FIELD_TEXT: Final = {
    ProfileField.NAME: "what they are called, as they write it",
    ProfileField.ADDRESS: "how they like to be addressed",
    ProfileField.ASSISTANT_NAME: "what they call you",
    ProfileField.TIME_ZONE: "their time zone",
    ProfileField.LANGUAGE: "the language you write to them in",
}
_PINNED_TEXT: Final = "pinned by them, to be kept in mind"
_STYLE_TEXT: Final = "how they want you to speak to them, as learned"
_NOTHING_KEPT: Final = "none: they keep nothing in mind yet"
_SUGGESTION_ITEM: Final = (
    "a suggestion the assistant noticed and they have not taken up: not their profile"
)


def _not_set(field: ProfileField, zone: str) -> str:
    """A field not set, as planning is shown it (ADR-0338 §3:9).

    Never a default presented as the person's own: an assistant's name not set says what
    the assistant is then called, and a zone not set says which zone the current time is
    given in instead.
    """
    if field is ProfileField.ASSISTANT_NAME:
        return f"not set, so you are called {DEFAULT_ASSISTANT_NAME}"
    if field is ProfileField.TIME_ZONE:
        return f"not set: the current time is given in the hub's default zone, {zone}"
    return "not set"


def _left_out(count: int) -> str:
    """How many memories the slot's budget left out (ADR-0338 §6:2)."""
    memories = "memory" if count == 1 else "memories"
    return f"{count} more {memories} they keep in mind, left out to keep this short"


def _looks(item: PlaceItem) -> tuple[PlaceAuthor, datetime | None, str | None]:
    """What the place window shows of an item that a reference to it can name."""
    return item.author, item.at, item.episode_id


def _ordinal(number: int) -> str:
    """``number`` as an English ordinal: 1st, 2nd, 3rd, 4th, 11th, 21st."""
    suffix = (
        "th" if number % 100 in {11, 12, 13} else {1: "st", 2: "nd", 3: "rd"}.get(number % 10, "th")
    )
    return f"{number}{suffix}"


def _instant_or_unknown(instant: datetime | None) -> str:
    """An instant as planning reads instants, or that it is unknown."""
    return _UNKNOWN_INSTANT if instant is None else instant.isoformat()


#: The authors whose items show nothing of an episode's own exchange (ADR-0276 §3): one
#: someone else wrote is never shown, and a lineage step is the hub's statement of a
#: step, never its messages (ADR-0350 §6:5).
_NOT_AN_EXCHANGE: Final = frozenset({PlaceAuthor.OTHER, PlaceAuthor.TASK_SCHEDULER})

_AUTHOR_TEXT: Final = {
    PlaceAuthor.USER: "the user",
    PlaceAuthor.ASSISTANT: "the assistant",
    PlaceAuthor.OTHER: "someone else",
    PlaceAuthor.TASK_SCHEDULER: "the Task Scheduler",
}

_OUTCOME_TEXT: Final = {
    CallOutcomeKind.DONE: "done",
    CallOutcomeKind.NOT_DONE: "not done",
    CallOutcomeKind.UNKNOWN: (
        "unknown: it may or may not have happened, and it is reported as unknown"
    ),
    CallOutcomeKind.REFUSED: (
        "refused before it ran, so nothing in it ran, and no yes lets it run: never ask the "
        "user about it"
    ),
}

#: ADR-0321 §2:10: which case of a call needing the user applies, each said with its
#: outcome. These replace the needs-you outcome text.
_NEEDS_YES: Final = (
    "needs the user's yes, and is not yet asked, even where an earlier message mentioned "
    "it: ask them about it in this round's message, explaining it in your own words, and "
    "name it in asks by its ask_as reference, so the exact details are filled in below "
    "your message. Leave it unasked only where the user no longer wants it"
)
#: §7:3: where the place takes no message.
_NO_ONE_TO_ASK: Final = (
    "needs the user, and this activation cannot message them, so it will not run and is "
    "not asked about"
)
#: §4:11, and a call an earlier round of this activation already asked about: either
#: way a question that showed its exact line (#3071). #3072: waiting is not approved.
_ALREADY_ASKED: Final = (
    "already asked about, in a question that showed its exact details, and waiting on the "
    "user's answer, so it is not asked about again. It is not approved: never say it is "
    "going through or being done"
)
#: ADR-0332 §3:7, §3:12: an earlier round's text, where new input overtook the round
#: before it acted, so it was never written and asked the user nothing.
_OVERTAKEN: Final = (
    "not written: new input joined before this round acted, so the user never saw it"
)
#: A round held back because its answer to an offer did not come to what it asked
#: (ADR-0352 §4:2): its message was never written.
_NOT_TAKEN: Final = (
    "not written: this round's answer to an offer did not come to what it asked, so the "
    "user never saw it"
)
#: A call that needs the user but whose request was not handed on cannot be shown exactly,
#: so it is never asked about (§2:5).
_UNSHOWABLE: Final = "needs the user, and it cannot be asked about, so it will not run"


def _not_replacing(count: int) -> str:
    """What planning is told of the replaced assertions that rest on outside content."""
    facts = "remembered fact" if count == 1 else "remembered facts"
    return (
        f"{count} {facts} resting on outside content, which this question cannot show "
        "and a yes will not replace"
    )


#: §4:2: how an approved action came to be approved.
_APPROVED_BY: Final = "by the user's yes in this input, to the question that showed it"


@dataclass
class _Shown:
    """What one round's rendering showed that bears on its own record."""

    marked: bool = False


@dataclass
class _PlaceTexts:
    """What the place window shows of one episode, by who wrote it (ADR-0276 §3)."""

    user: list[str] = field(default_factory=list)
    assistant: list[str] = field(default_factory=list)


class _Request:
    """One round's rendered request, assigning labels as it shows things."""

    def __init__(
        self,
        inputs: PlanningInputs,
        book: _LabelBook,
        *,
        excerpt_chars: int,
        now: datetime,
        zone: ZoneInfo,
    ) -> None:
        self._inputs = inputs
        self._book = book
        self._excerpt_chars = excerpt_chars
        self._now = now
        self._zone = zone
        self.shown = _Shown()
        # The calls this round may ask about, by the reference each is shown with
        # (ADR-0321 §2:3), filled as the earlier rounds are rendered.
        self.askable: dict[str, CallOutcome] = {}
        # The calls this activation's earlier rounds asked about, by their round's number:
        # a round new input overtook asked nothing, since its message was never written
        # (ADR-0332 §3:7, ADR-0321 §2:2), and nor did one whose asking ``text`` call was
        # not sent, since nothing waits on a question the user did not see (ADR-0357 §8).
        self._asked_before: tuple[tuple[int, AskedCall], ...] = tuple(
            (number, asked)
            for number, one in enumerate(inputs.rounds, 1)
            if one.id not in inputs.overtaken and _question_sent(one, inputs.outcomes)
            for asked in one.asked
        )
        # Whether a story read is offered this round, set as the request is rendered.
        self._reads_stories = False
        # Each earlier work's peer view as rendered, by its activation, which the news
        # compares to what the exchange showed (ADR-0356 §5:5).
        self._peers_rendered: dict[str, str] = {}
        # The episodes rendered whole so far, so one shown again is named by its label.
        self._rendered: set[str] = set()
        # The summary version each story was first rendered with a summary at, or
        # ``None`` where its summary was withheld, in the order rendered; a story named
        # by its label alone is not here (ADR-0358 §11:2).
        self.summaries_shown: dict[str, int | None] = {}
        # Each running activation understanding cited: the list it is cited in, its
        # place there and its episode, named once the request is rendered (ADR-0353 §14:1).
        self._running_cited: list[tuple[list[object], int, str]] = []
        # What the place window shows of each episode it links to: the user's texts and
        # the assistant's, each in the window's order (ADR-0276 §3, ADR-0307 §5:6). An
        # item someone else wrote is never shown, so it shows nothing of an episode.
        self._in_place: dict[str, _PlaceTexts] = {}
        # The episodes the pass holds whose input their latest understanding marks
        # relayed, where the mark counts (ADR-0351 §5:7, §5:11): the user's items of
        # one are outside, so each is withheld as a forward is (ADR-0307 §9:2).
        self._relayed = relayed_episodes(
            (*inputs.episodes, *inputs.recalled), excerpt_chars=excerpt_chars
        )
        # The place window's items by the id understanding's referents name them by, each
        # with its place among the items the window shows alike and how many those are, so
        # a reference to one is shown as that item and no other (ADR-0307 §5:6).
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

    def rendered(self, offered: Sequence[OfferedTool]) -> str:
        """The request's JSON object, as one string."""
        inputs = self._inputs
        self._reads_stories = _offers_story_reads(offered)
        document: dict[str, object] = {}
        if inputs.person is not None:
            # ADR-0338 §7:3: first, before everything that changes from round to round,
            # so it caches across them (#3084).
            document["person"] = self._person(inputs.person)
        document |= {
            # The current instant in the person's zone, or the configured one where theirs
            # is not set (ADR-0338 §3:6), with its offset, and the zone's IANA name, so a
            # time told is told in local time (#2964).
            "now": self._now.astimezone(self._zone).isoformat(),
            "time_zone": self._zone.key,
            "place": self._place(),
            "understanding": self._understanding(),
        }
        if inputs.places is not None:
            # ADR-0350 §5:10: the place list, places grouped under channel headings.
            document["places"] = self._places(inputs.places)
        if inputs.approved:
            document["approved_actions"] = [self._approved(one) for one in inputs.approved]
        if inputs.offers:
            # ADR-0349 §7:19: each offer open to this work, at the start of every round.
            document["offers"] = [self._offer(one) for one in inputs.offers]
        if inputs.waiting:
            # §7:26: the work this round waits on, and why an offer was declined.
            document["waiting_on"] = [self._waited_on(one) for one in inputs.waiting]
        if inputs.earlier_work:
            # §7:10, §7:27: the finished work this one took over or waited on.
            document["earlier_work"] = [self._peer_shown(one) for one in inputs.earlier_work]
        document |= {
            "place_window": [self._item(item) for item in inputs.place.items],
            "episode_window": self._episodes(),
            "recalled": self._recalled(),
        }
        stories = inputs.stories
        if stories is not None:
            document["stories"] = self._stories(stories)
            if stories.cited and not stories.unreadable:
                document["cited_stories"] = [self._short(one) for one in stories.cited]
        document |= {
            "capabilities": [tool.name for tool in offered],
            "rounds": [self._round(number, one) for number, one in enumerate(inputs.rounds, 1)],
            "evidence": [self._evidence(one) for one in inputs.evidence],
        }
        self._name_running()
        return json.dumps(document, ensure_ascii=False, sort_keys=False)

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
        )

    def _stories_held(self) -> tuple[PlanningStory, ...]:
        """The stories the activation belongs to, as this round's inputs hold them."""
        given = self._inputs.stories
        return () if given is None or given.unreadable else given.stories

    def report(self, work: PlanningWork) -> tuple[RoundReport, NewsShown]:
        """The system's turn after the work's last round: its results, then the news.

        ADR-0356 §5:3-§5:6. One result for each call of that round, in its order and
        under its id: code's rendering of what came of it, a digested result as its
        digest's evidence, marked outside, and a result planning may name under its R
        label. Then what the inputs hold that the exchange has not shown: each offer
        newly open and each that closed, the finished work newly read of an activation
        this work took over or waited on, and a stimulus taken in, with its meaning,
        and any evidence not yet shown; or that nothing has changed.

        Returns:
            The report, and what the exchange has shown once it is sent.
        """
        inputs = self._inputs
        shown = work.shown
        outcomes = {
            outcome.call_id: outcome
            for outcome in inputs.outcomes
            if outcome.round_id == work.round_id
        }
        fresh = list(enumerate(inputs.evidence))[shown.evidence :]
        reported: set[int] = set()
        results: list[CallResult] = []
        for index, call in enumerate(work.response.calls, 1):
            outcome = outcomes.get(call.call_id)
            result = self._call(call, outcome, reference=f"{work.number}.{index}")
            result.pop("capability", None)
            result.pop("arguments", None)
            if outcome is not None and outcome.digested and outcome.result_id is not None:
                # §5:4: a result resting on outside content is its digest's evidence.
                read = [(at, one) for at, one in fresh if one.result_id == outcome.result_id]
                reported.update(at for at, _ in read)
                result["evidence"] = [self._evidence(one) for _, one in read] or _NOT_YET_READ
            results.append(
                CallResult(
                    call_id=call.call_id,
                    text=json.dumps(result, ensure_ascii=False, sort_keys=False),
                )
            )
        started = self._stories_started(work, outcomes, results, shown.stories)
        news = self._news(shown, [one for at, one in fresh if at not in reported])
        news |= self._text_unwritten(work)
        self._name_running()
        return (
            RoundReport(
                results=tuple(results),
                news=NOTHING_NEW if not news else json.dumps(news, ensure_ascii=False),
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
            ),
        )

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
                result["stories"] = [self._story(one) for one in fresh]
                results[at] = CallResult(
                    call_id=call.call_id, text=json.dumps(result, ensure_ascii=False)
                )
                return frozenset(one.story_id for one in fresh)
        return frozenset()

    def _news(self, shown: NewsShown, evidence: Sequence[DigestedEvidence]) -> dict[str, object]:
        """What the work's inputs hold that the exchange has not yet shown (§5:5-§5:6)."""
        inputs = self._inputs
        news: dict[str, object] = {}
        opened = [
            self._offer(one) for one in inputs.offers if one.activation_id not in shown.offers
        ]
        if opened:
            news["offers_open"] = opened
        open_now = {one.activation_id for one in inputs.offers}
        closed = [
            self._book.label(LabelKind.EPISODE, episode_address(one))
            for one in sorted(shown.offers - open_now)
        ]
        if closed:
            news["offers_closed"] = closed
        read: list[dict[str, object]] = []
        for one in inputs.earlier_work:
            rendered = self._peer_shown(one)
            if shown.earlier_work.get(one.activation_id) != self._peers_rendered[one.activation_id]:
                read.append(rendered)
        if read:
            news["earlier_work"] = read
        understanding = inputs.understanding
        if understanding is not None and understanding.version != shown.understanding:
            # A stimulus taken in, with its meaning (ADR-0332 §3:12).
            news["understanding"] = self._understanding()
        items = [self._item(item) for item in inputs.place.items if item not in shown.items]
        if items:
            news["place_window"] = items
        if evidence:
            news["evidence"] = [self._evidence(one) for one in evidence]
        return news

    def _text_unwritten(self, work: PlanningWork) -> dict[str, object]:
        """Where the last round's text, still its message, was never written, and why.

        Until a message is a call (ADR-0356 §14:1, P3), a round's text is also its message.
        One new input overtook, or held back for an answer that did not come to what it
        asked, was never written (ADR-0332 §3:7, ADR-0352 §4:2), and the report says so,
        as the round's rendering once did.
        """
        if not work.response.text.strip():
            return {}
        if work.round_id in self._inputs.not_taken:
            return {"text_was": _NOT_TAKEN}
        if work.round_id in self._inputs.overtaken:
            return {"text_was": _OVERTAKEN}
        return {}

    def _peer_shown(self, one: PeerShown) -> dict[str, object]:
        """One activation's finished work, rendered and noted as shown."""
        rendered = self._peer(one)
        self._peers_rendered[one.activation_id] = json.dumps(
            rendered, ensure_ascii=False, sort_keys=True
        )
        return rendered

    def _place(self) -> dict[str, object]:
        place = self._inputs.place
        shown: dict[str, object] = {"takes_message": place.takes_message}
        if place.description is not None:
            shown["description"] = place.description
        if self._inputs.outside_trigger:
            shown["input"] = "an outside report: " + _OUTSIDE
        return shown

    def _understanding(self) -> dict[str, object] | str:
        understanding = self._inputs.understanding
        if understanding is None:
            return _NO_UNDERSTANDING
        # ADR-0353 §14:1: the understanding, each cited item by its label, each unclear
        # point with its readings, and the matters it belongs to; no ground (§12).
        shown: dict[str, object] = {"meaning": understanding.meaning}
        if understanding.meaning_referents:
            cited: list[object] = [self._referent(one) for one in understanding.meaning_referents]
            self._running_cited = [
                (cited, at, one.id)
                for at, one in enumerate(understanding.meaning_referents)
                if one.kind == "running" and one.id is not None
            ]
            shown["rests_on"] = cited
        if understanding.unclear:
            shown["unclear"] = [
                {"gap": one.gap, "readings": list(one.readings)} for one in understanding.unclear
            ]
        if understanding.story_links:
            shown["belongs_to"] = [
                self._book.label(LabelKind.STORY, one.id)
                if one.kind is StoryMemberKind.STORY
                else self._book.label(LabelKind.EPISODE, f"activation:{one.id}")
                for one in understanding.story_links
            ]
        return shown

    def _referent(self, referent: UnderstandingReferent) -> str:
        """A referent by its label where it names a thing planning may name.

        Never its excerpt: a channel item's excerpt is the item's own words, which may
        be what someone other than the user wrote, and planning never reads raw outside
        content (ADR-0307 §9:2). The place window shows the items it may, and a channel
        item is named as the window shows it (:meth:`_channel_item`).
        """
        kinds = {
            "story": LabelKind.STORY,
            "episode": LabelKind.EPISODE,
            "memory": LabelKind.MEMORY,
        }
        if referent.kind == "running":
            # Named once the request is rendered (:meth:`_name_running`).
            return _RUNNING_UNNAMED
        kind = kinds.get(referent.kind)
        if kind is not None and referent.id is not None:
            return self._book.label(kind, referent.id)
        if referent.kind == "input":
            return "the input"
        if referent.kind == "channel_item":
            return self._channel_item(referent)
        return f"a {referent.kind} no longer named"

    def _name_running(self) -> None:
        """Name each running activation understanding cited, once the request is rendered.

        By the label planning knows it by (ADR-0353 §14:1), never by its excerpt
        (§10:6): the label another section of this request, or an earlier round, gave its
        episode, wherever that section falls in the request. A label minted for the
        citation alone would be a pointer the activation's record keeps (ADR-0307 §5:1),
        which the observer reads (ADR-0346 §2:1), so a read would chain through the
        referent; work no section names keeps the words it was rendered with.
        """
        for cited, at, episode in self._running_cited:
            held = self._book.held(LabelKind.EPISODE, episode)
            if held is not None:
                cited[at] = held

    def _channel_item(self, referent: UnderstandingReferent) -> str:
        """A channel item understanding named, as the place window shows that item.

        By what the window shows of it: who wrote it, when, and the episode label of
        the activation it links to, which the window shows it under (ADR-0307 §5:6);
        where other items show alike, by its place among them in the window's order, so
        it names that item and no other. Never by its words, which may be what someone
        other than the user wrote (§9:2): an item the window does not hold is named
        only as an item of the window.
        """
        found = None if referent.id is None else self._by_referent.get(referent.id)
        if found is None:
            return _SOME_ITEM
        item, place, alike = found
        shown = f"the item of the place window {_AUTHOR_TEXT[item.author]} wrote"
        if item.at is not None:
            shown += f" at {item.at.isoformat()}"
        if item.episode_id is not None:
            shown += f", under {self._book.label(LabelKind.EPISODE, item.episode_id)}"
        if alike > 1:
            shown += f" ({_ordinal(place)} of {alike} such, in the window's order)"
        return shown

    def _item(self, item: PlaceItem) -> dict[str, object]:
        shown: dict[str, object] = {"from": _AUTHOR_TEXT[item.author]}
        if item.at is not None:
            shown["at"] = item.at.isoformat()
        if item.is_input:
            shown["is_the_input"] = True
        if item.author is PlaceAuthor.OTHER:
            shown["text"] = _WITHHELD_ITEM
        elif self._relayed_item(item):
            shown["text"] = _RELAYED_ITEM
        else:
            shown["text"] = item.text
        if item.episode_id is not None:
            shown["episode"] = self._book.label(LabelKind.EPISODE, item.episode_id)
        if item.task_id is not None:
            # ADR-0350 §9:2: the scheduled task it links to, beside its episode label.
            shown["scheduled_task"] = self._book.label(LabelKind.SCHEDULED_TASK, item.task_id)
        return shown

    def _relayed_item(self, item: PlaceItem) -> bool:
        """Whether ``item`` is the user's message of an input its episode marks relayed.

        ADR-0351 §5:7: such an input is outside, and every reader that reads outside
        content reads it so; the place window shows a forward's item withheld (ADR-0307
        §9:2), and this one is withheld the same way, still the user's, since the relay
        mark changes no party (§5:8). Read off the episodes the pass already holds; an
        item whose episode it does not hold is shown as its record gives it.
        """
        return item.author is PlaceAuthor.USER and item.episode_id in self._relayed

    def _places(self, places: Sequence[ListedPlace]) -> list[dict[str, object]]:
        """The place list: each channel's heading, never named, with its places (§5:10)."""
        grouped: dict[str, list[dict[str, object]]] = {}
        for one in places:
            shown: dict[str, object] = {
                "label": self._book.label(LabelKind.PLACE, one.place),
                "is": one.description,
            }
            if one.suggested:
                shown["suggested"] = True
            grouped.setdefault(one.heading, []).append(shown)
        return [{"channel": heading, "places": held} for heading, held in grouped.items()]

    def _place_named(self, place: str) -> str:
        """A place by its ``L`` label where it is on the list, and in words otherwise."""
        held = self._book.held(LabelKind.PLACE, place)
        if held is not None:
            return held
        channel = place_channel(place)
        kind = "a place" if channel is None else f"a place of the {channel.channel_type} channel"
        return f"{kind} not on your place list"

    def _task(self, entry: TaskEntry) -> dict[str, object]:
        """A scheduled task, as the Task Scheduler's calls show it (ADR-0350 §4:6-§4:8)."""
        shown: dict[str, object] = {
            "label": self._book.label(LabelKind.SCHEDULED_TASK, entry.task_id),
            "state": entry.state,
            "falls_due": entry.falls_due,
        }
        if entry.repeats is not None:
            # ADR-0340 §8:2: a task with a rule shows its rule in words.
            shown["repeats"] = entry.repeats
        if entry.read_back is not None:
            # ADR-0340 §6:2-§6:3: the task a spawn wrote, said back from the record.
            shown["read_back"] = entry.read_back
        if entry.waits_on:
            shown["waits_on"] = [
                self._book.label(LabelKind.SCHEDULED_TASK, one) for one in entry.waits_on
            ]
        shown["carries"] = _OUTSIDE if entry.instruction is None else entry.instruction
        shown["set_by"] = entry.author
        shown["suggests"] = [self._place_named(one) for one in entry.places] or _NONE_FOUND
        shown["parent"] = {
            "episode": self._book.label(LabelKind.EPISODE, f"activation:{entry.parent}"),
            "is": entry.parent_text,
        }
        return shown

    def _activation(self, entry: ActivationEntry) -> dict[str, object]:
        """A running or ended activation, as the list pull shows it (ADR-0350 §4:6-§4:7).

        An ended one says where its messages went, each place as the place list shows
        it, and where one may have gone whose outcome is not known; that it wrote none
        only where neither holds a place (#3445), and nothing where its effect records
        were not read.
        """
        shown: dict[str, object] = {
            "episode": self._book.label(LabelKind.EPISODE, f"activation:{entry.activation_id}"),
            "started": entry.started,
            "place": entry.place,
            "status": entry.status,
            "input": _OUTSIDE if entry.outside or entry.input is None else entry.input,
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

    def _listed_place(self, place: str) -> dict[str, object]:
        """A place a message went into, as the place list shows it (ADR-0350 §5:10-§5:12).

        By its ``L`` label and the list's description where it is on this round's place
        list, and otherwise by what it is, saying it is not on the list.
        """
        for one in self._inputs.places or ():
            if one.place == place:
                return {"label": self._book.label(LabelKind.PLACE, place), "is": one.description}
        return {"is": place_description(place_channel(place)), "on_your_place_list": False}

    def _running(self, entry: ActivationEntry) -> dict[str, object]:
        """A running activation, as the list pull's running part shows it (ADR-0349 §6:2).

        As an in-progress entry shows it (§5:6), under its episode label (§5:7): what
        caused it, what it took in, in brief, and whether it has acted.
        """
        return {
            "episode": self._book.label(LabelKind.EPISODE, f"activation:{entry.activation_id}"),
            "place": entry.place,
            "input": (
                _withheld(outside=entry.outside, assistants=entry.assistants)
                if entry.input is None
                else entry.input
            ),
            "has_acted": entry.acted,
        }

    def _offer(self, one: OfferShown) -> dict[str, object]:
        """An offer open to this work, under the offering activation's label (§7:19)."""
        return {
            "offer": self._book.label(LabelKind.EPISODE, episode_address(one.activation_id)),
            "input": (
                _withheld(outside=False, assistants=False) if one.input is None else one.input
            ),
            "understood_as": one.meaning,
        }

    def _waited_on(self, one: RunningShown) -> dict[str, object]:
        """Work this round waits on, as an in-progress entry shows it (§7:26)."""
        shown: dict[str, object] = {
            "episode": self._book.label(LabelKind.EPISODE, episode_address(one.activation_id)),
            "place": _place_text(one.place),
            "input": (
                _withheld(outside=one.outside, assistants=parties_are_assistants(one.parties))
                if one.input is None
                else one.input
            ),
            "has_acted": one.acted,
        }
        reasons = [why for older, why in self._inputs.declined if older == one.activation_id]
        if reasons:
            shown["declined_this_input"] = reasons[-1]
        return shown

    def _peer(self, one: PeerShown) -> dict[str, object]:
        """Another activation's own work, read through the peer view (§6:7-§6:10).

        What it took in, what it is doing, read as provisional, what it found, each with
        its mark, and what it did. An outside episode shown here counts as any episode
        shown under its label does (§6:13), and marked notes or evidence it shows mark
        this round's notes, as any outside content read does.
        """
        label = self._book.label(LabelKind.EPISODE, episode_address(one.activation_id))
        shown: dict[str, object] = {"episode": label}
        if one.stopped is not None:
            shown["stopped_by_this_call"] = one.stopped
        if one.answered is not None:
            shown["answer"] = one.answered
            why = one.not_as_asked
            if why is not None and why in _SHOWN_WITH_RESULT:
                # ADR-0349 §7:23, ADR-0352 §4:2: why the hub settled it so, naming the
                # offering work by its label, and the input it carried by its meaning.
                shown["because"] = answer_fact(why, offering=label)
                if one.meaning is not None:
                    shown["understood_as"] = one.meaning
            return shown
        shown["status"] = "ended" if one.ended else "running"
        view = one.view
        if view is None:
            shown["work"] = _PEER_UNREAD
        else:
            shown |= self._peer_work(view)
        if one.set_up is not None:
            shown["set_up_still_live"] = self._set_up(one.set_up)
        return shown

    def _set_up(self, left: StillLive) -> object:
        """What a stopped activation set up that is still live (ADR-0352 §3:1-§3:6).

        Each task as the Task Scheduler's calls show one, under its ``T`` label, and each
        activation as the list pull's running part shows one, under its ``E`` label, or,
        pushed and not yet admitted, under its task's label as starting; each part says
        how many more there are past the listing bound. Every label shown here counts as
        shown (§3:7, ADR-0307 §5:3).
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

    def _peer_work(self, view: PeerView) -> dict[str, object]:
        """What a peer view shows of an activation's own work (§6:9)."""
        shown: dict[str, object] = {}
        if view.input is not None:
            shown["input"] = _text(view.input)
            if view.joined:
                shown["also_took_in"] = [_text(text) for text in view.joined]
        else:
            shown["input"] = _withheld(
                outside=parties_are_outside(view.parties, relayed=view.relayed),
                assistants=parties_are_assistants(view.parties, relayed=view.relayed),
            )
        if view.meaning is not None:
            shown["doing"] = f"{_PROVISIONAL}{view.meaning}"
        found: list[object] = []
        for notes in view.notes:
            item: dict[str, object] = {"notes": _text(notes.notes)}
            if notes.marked:
                item["outside_content"] = _OUTSIDE
                self.shown.marked = True
            found.append(item)
        for evidence in view.evidence:
            found.append({"evidence": _text(evidence.text), "outside_content": _OUTSIDE})
            self.shown.marked = True
        if found:
            shown["found"] = found
        shown["did"] = [_effect_text(effect) for effect in view.did] or _NOTHING_DONE
        if view.derived_from_external:
            shown["outside_content"] = _OUTSIDE
            self.shown.marked = True
        return shown

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

    def _episodes(self) -> list[dict[str, object]]:
        shown: list[dict[str, object]] = []
        for record in self._inputs.episodes:
            processing = record.processing_record
            if processing is not None and processing.is_open:
                continue
            projection = project_episode(
                record,
                excerpt_chars=self._excerpt_chars,
                owner_records=self._inputs.owner_records,
                # ADR-0329 §6:9: an unprocessed episode's pending candidates, here alone.
                candidates=self._inputs.pending.get(record.id, ()),
            )
            label = self._book.label(LabelKind.EPISODE, record.id)
            shown.append(self._episode(label, projection, record))
            self._rendered.add(record.id)
        return shown

    def _recalled(self) -> list[dict[str, object]]:
        """What either recall run found, each by its records (ADR-0308 §3).

        A found episode is shown as the episode window's are, through
        :func:`~ai_assistant.core.episode_encoding.project_episode` with no outside
        input admitted and its notes under the reader's audience, and with the labels
        of the stories it is in and nothing else of them (§3:1-§3:2). A found memory
        record is shown only where its source is not outside (§3:3, ADR-0306 §5:16):
        every other one is withheld, and reaches planning only as recall's digest's
        evidence. An episode the episode window already shows is not shown again.
        """
        window = {record.id for record in self._inputs.episodes}
        person = self._inputs.person
        kept = frozenset() if person is None else person.memory_ids
        shown: list[dict[str, object]] = []
        for record in self._inputs.recalled:
            if record.id in window:
                continue
            if record.id in kept:
                # ADR-0338 §7:7: a memory the person block shows keeps the label it took
                # there, and is not shown again.
                shown.append(
                    {"label": self._book.label(LabelKind.MEMORY, record.id), "shown": _SHOWN_ABOVE}
                )
                continue
            if isinstance(record, EpisodicMemory):
                processing = record.processing_record
                if processing is not None and processing.is_open:
                    continue
                projection = project_episode(
                    record,
                    excerpt_chars=self._excerpt_chars,
                    owner_records=self._inputs.owner_records,
                )
                label = self._book.label(LabelKind.EPISODE, record.id)
                episode = self._episode(label, projection, record)
                self._rendered.add(record.id)
                stories = self._inputs.recalled_stories.get(record.id, ())
                if stories:
                    episode["in_stories"] = [
                        self._book.label(LabelKind.STORY, story) for story in stories
                    ]
                shown.append(episode)
            elif not record.rests_on_outside_content:
                shown.append(self._memory(record))
        return shown

    # --- the person block (ADR-0338 §7:3, §7:6-§7:9) ---

    def _person(self, person: PersonBlock) -> dict[str, object]:
        """The person block as data: the five fields, the slot and the suggestions.

        Rendered as the person's own choices and preferences, never as an instruction
        (§7:6). A field not set is said to be not set, and a zone not set is shown
        beside the hub's default zone the current time is given in (§3:9). Each memory
        takes its label the first time planning is shown it, here as anywhere (§7:7),
        and a pin suggestion's memory is labelled as planning labels a memory (§7:9).
        """
        shown: dict[str, object] = {"item": _PERSON_ITEM, "profile": self._profile(person)}
        shown["kept_in_mind"] = [self._kept(one) for one in person.kept] or _NOTHING_KEPT
        if person.left_out:
            shown["left_out"] = _left_out(person.left_out)
        if person.suggestions:
            shown["suggestions"] = [self._suggestion(one) for one in person.suggestions]
        return shown

    def _profile(self, person: PersonBlock) -> dict[str, object]:
        profile: dict[str, object] = {}
        for field_ in ProfileField:
            value = person.profile.value(field_)
            if value is None:
                value = _not_set(field_, self._zone.key)
            profile[field_.value] = {"is": _PERSON_FIELD_TEXT[field_], "value": value}
        return profile

    def _kept(self, one: KeptInMind) -> dict[str, object]:
        """One memory of the slot, as a found memory is shown, with why it is kept."""
        return {
            "kept_as": _PINNED_TEXT if one.pinned else _STYLE_TEXT,
            # §6:1: the slot's budget bounds its wordings, so each is shown whole.
            **self._memory(one.memory, whole=True),
        }

    def _suggestion(self, one: ShownSuggestion) -> dict[str, object]:
        """A pending suggestion, marked as one and never as the person's profile (§7:3)."""
        shown: dict[str, object] = {"item": _SUGGESTION_ITEM}
        if one.field is not None:
            shown["field"] = one.field.value
            shown["value"] = one.value
        elif one.memory is not None:
            shown["pin"] = self._memory(one.memory)
        shown["noticed_at"] = one.recorded_at.isoformat()
        return shown

    # --- the story views (ADR-0307 §6:1, §6:3-§6:4) ---

    def _stories(self, given: PlanningStories) -> list[dict[str, object]] | str:
        """The stories the activation belongs to, each as planning's view of it."""
        if given.unreadable:
            return _STORIES_UNREADABLE
        return [self._story(one) for one in given.stories] or _NO_STORIES

    def _story(self, one: PlanningStory) -> dict[str, object]:
        """One story: its summary, what is newer, the tidy-up facts, and where it stands.

        When the summary was last tidied and the count of changes since are shown on
        every pass (§6:3-§6:4). On a pass that may not be shown a note, the notes part
        is absent, saying nothing of them (ADR-0305 §4).

        A tidied story says beside its summary that a story read lists any older notes
        its lines came from, where a story read is offered and notes may be shown, and
        not on a read's own view, which lists them (#2944).
        """
        shown: dict[str, object] = {
            "label": self._book.label(LabelKind.STORY, one.story_id),
            "summary": self._summary(
                written=one.written, withheld=one.withheld, lines=one.lines, outside=one.outside
            ),
        }
        self.summaries_shown.setdefault(one.story_id, None if one.withheld else one.summary_version)
        if one.outside and one.written and not one.withheld:
            shown["summary_outside_content"] = _OUTSIDE
        if (
            one.tidied_at is not None
            and not one.notes_withheld
            and one.older is None
            and self._reads_stories
        ):
            shown["summary_built_from"] = _FROM_OLDER_NOTES
        shown["last_tidied"] = _NEVER_TIDIED if one.tidied_at is None else one.tidied_at.isoformat()
        shown["changes_since_tidied"] = one.changes
        if not one.notes_withheld:
            shown["notes_since_tidied"] = [self._note(note) for note in one.notes] or _NONE_NEWER
            if one.older is not None:
                shown["older_notes"] = [self._note(note) for note in one.older] or _NO_OLDER
                if one.older_more:
                    shown["more_older_notes"] = _more_older(one.older_more, one.older_page + 1)
        shown["episodes_since_tidied"] = [
            self._story_episode(record) for record in one.newer
        ] or _NONE_NEWER
        shown["latest_episodes"] = [
            self._story_episode(record) for record in one.latest
        ] or _NO_EPISODES
        if one.inherited:
            shown["part_of"] = [self._short(view, inherited=True) for view in one.inherited]
        if one.standing is not None:
            shown["where_it_stands"] = self._standing(one.standing)
        return shown

    def _summary(
        self,
        *,
        written: bool,
        withheld: bool,
        lines: Sequence[StorySummaryLine],
        outside: bool,
    ) -> list[str] | str:
        """A summary's lines, or why none is shown; a marked one is read outside content."""
        if withheld:
            return _SUMMARY_WITHHELD
        if not written:
            return _NO_SUMMARY
        if outside:
            # ADR-0303 §3:6: a marked summary planning reads is outside content read.
            self.shown.marked = True
        return [line.text for line in lines] or _NO_LINES

    def _note(self, note: StoryNote) -> dict[str, object]:
        """A story's note under its label, by who wrote it and its mark, never its text."""
        shown: dict[str, object] = {
            "label": self._book.label(LabelKind.NOTE, str(note.note_id)),
            "written_by": _NOTE_AUTHOR_TEXT[note.author],
            "written_at": note.written_at.isoformat(),
            "text": note.text,
        }
        if note.outside:
            # ADR-0303 §3:6: a marked note planning reads is outside content read.
            shown["outside_content"] = _OUTSIDE
            self.shown.marked = True
        return shown

    def _story_episode(self, record: EpisodicMemory) -> dict[str, object]:
        """An episode of a story, rendered whole once and named by its label after.

        One resting on outside content is outside content planning has read, as
        :meth:`_episode` counts it.
        """
        label = self._book.label(LabelKind.EPISODE, record.id)
        if record.id in self._rendered:
            return {"label": label, "shown": _SHOWN_ABOVE}
        projection = project_episode(
            record, excerpt_chars=self._excerpt_chars, owner_records=self._inputs.owner_records
        )
        self._rendered.add(record.id)
        return self._episode(label, projection, record)

    def _short(self, view: ShortView, *, inherited: bool = False) -> dict[str, object]:
        """A story's short view (ADR-0300 §6:2), under the same minimum (ADR-0304 §4)."""
        shown: dict[str, object] = {"label": self._book.label(LabelKind.STORY, view.story_id)}
        if inherited:
            shown["inherited"] = _INHERITED
        shown["summary"] = self._summary(
            written=view.written,
            withheld=view.withheld,
            lines=view.lines,
            outside=view.outside,
        )
        self.summaries_shown.setdefault(
            view.story_id, None if view.withheld else view.summary_version
        )
        if view.outside and not view.withheld:
            shown["summary_outside_content"] = _OUTSIDE
        if not view.notes_withheld:
            shown["newest_notes"] = [self._note(note) for note in view.notes] or _NONE_NEWER
        shown["latest_episodes"] = [
            self._story_episode(record) for record in view.episodes
        ] or _NO_EPISODES
        return shown

    def _standing(self, standing: StoryStanding) -> dict[str, object]:
        """Where a matter stands (ADR-0300 §8:1), each episode by its label."""
        merged = standing.story.merged_into
        if merged is not None:
            return {"merged_into": self._book.label(LabelKind.STORY, merged)}
        shown: dict[str, object] = {
            "done": [
                {
                    "episode": self._book.label(
                        LabelKind.EPISODE, episode_address(effect.activation_id)
                    ),
                    "state": _EFFECT_TEXT[effect.state],
                    "at": effect.at.isoformat(),
                }
                for effect in standing.done
            ]
            or _NOTHING_DONE,
            "timeline": [self._moment(moment) for moment in standing.recent] or _NO_EPISODES,
        }
        earlier = standing.earlier
        if earlier is not None:
            shown["earlier"] = {
                "episodes": earlier.episodes,
                "from": earlier.first_at.isoformat(),
                "to": earlier.last_at.isoformat(),
            }
        if standing.related:
            shown["related"] = [
                {
                    "story": self._book.label(LabelKind.STORY, related.story_id),
                    "relation": _RELATION_TEXT[related.relation],
                    "members": related.member_count,
                }
                for related in standing.related
            ]
        return shown

    def _moment(self, moment: StoryStandingEpisode) -> dict[str, object]:
        """One episode on a matter's timeline: its label, instant, meaning and mark."""
        shown: dict[str, object] = {
            "episode": self._book.label(LabelKind.EPISODE, episode_address(moment.activation_id)),
            "at": moment.occurred_at.isoformat(),
            "understood": _NO_MEANING if moment.meaning is None else moment.meaning,
        }
        if moment.outside:
            # An episode resting on outside content, shown by its meaning, is read.
            shown["outside_content"] = _OUTSIDE
            self.shown.marked = True
        return shown

    def _memory(self, record: Memory, *, whole: bool = False) -> dict[str, object]:
        """A found memory not resting on outside content: its wording, by its standing.

        ADR-0328 §15:5's label: its standing in plain words, its age (as of and learned,
        each unknown where nothing dates it), its evidence summary where its standing is
        inference, its reading certainty where that is not ``sure``, and its track record
        where it has one; and, beside it, each unresolved open question on it in words
        (ADR-0329 §6:6), which nothing raises before the observer runs. ``whole`` shows the
        wording uncut, as the kept-in-mind slot does, whose budget already bounds it
        (ADR-0338 §6:1).
        """
        fact = record.content
        bound = len(fact) if whole else self._excerpt_chars
        shown: dict[str, object] = {
            "label": self._book.label(LabelKind.MEMORY, record.id),
            "item": _BAND_TEXT[record.band],
            "standing": _STANDING_TEXT[record.standing],
            "last_updated": record.transaction_time.isoformat(),
            "as_of": _instant_or_unknown(record.as_of(self._now)),
            "learned": _instant_or_unknown(record.learned),
            "fact": fact
            if len(fact) <= bound
            else f"{fact[:bound]}… (cut: {bound} of {len(fact)} chars)",
        }
        if record.standing is MemoryStanding.INFERENCE:
            evidence = record.evidence_summary
            shown["evidence"] = {
                "supporting": evidence.supporting,
                "against": evidence.against,
                "episodes": evidence.episodes,
                # §7:2's latest `when` among the counted supports, against included,
                # which as of (the latest confirming instant) does not carry.
                "latest": _instant_or_unknown(evidence.latest),
            }
        certainty = record.reading_certainty
        if certainty is not ReadingCertainty.SURE:
            shown["reading_certainty"] = _NOT_JUDGED if certainty is None else str(certainty)
        track = record.track_summary
        if track.relied_on:
            shown["track_record"] = {
                "relied_on": track.relied_on,
                "held_up": track.held_up,
                "let_down": track.let_down,
            }
        # ADR-0329 §6:6: each unresolved open question on it, in words, beside it.
        questions = [one.asks for one in record.open_questions if not one.resolved]
        if questions:
            shown["open_questions"] = questions
        self._held(record, shown)
        return shown

    def _held(self, record: Memory, shown: dict[str, object]) -> None:
        """ADR-0345 §12:3 and §12:4's part of a memory's label, added to ``shown``.

        Its holders wherever they are not the user alone, the holders of its counted
        ``against`` supports where it has any, and its validity end where it lies in
        the future. A memory marked ``assistant_statement`` is said to be what the
        assistant said, citing where and when, and who kept it, never by its standing.
        """
        holders = record.holders
        if holders and holders != (SupportHolder.person(OWNER_PERSON_ID),):
            shown["held_by"] = [_holder_text(one) for one in holders]
        disputed = record.against_holders
        if disputed:
            shown["disputed_by"] = [_holder_text(one) for one in disputed]
        end = record.validity.valid_until
        if end is not None and end > self._now:
            shown["holds_until"] = end.isoformat()
        if MemoryMark.ASSISTANT_STATEMENT not in record.marks:
            return
        shown["item"] = _SAID_ITEM
        shown["standing"] = _SAID_STANDING
        shown["said"] = [
            {
                "in": self._book.held(LabelKind.EPISODE, one.episode) or _SAID_ELSEWHERE,
                "at": _instant_or_unknown(one.when),
            }
            for one in statement_citations(record)
        ]
        kept = [one for one in holders if one.kind is HolderKind.PERSON]
        if kept:
            shown["kept_by"] = [_holder_text(one) for one in kept]
        shown.pop("held_by", None)

    def _episode(
        self, label: str, projection: EpisodeProjection, record: EpisodicMemory
    ) -> dict[str, object]:
        """Another episode, shown whole: the episode window's, recall's or a story's.

        An outside episode (ADR-0303 §3:2) is outside content planning has read (§3:1),
        so the round's notes are marked (ADR-0307 §4:3) wherever it is shown, as
        authorizing counts its label (ADR-0306 §4:5): where its provenance rests on
        outside content, its input came from outside, whose understood meaning it is
        still shown, or it shows evidence or a marked note. What the reader's audience
        withholds of it is not read.

        Where the place window links items to it, each of its texts the window shows
        whole says so in its place, and the rest is rendered as before (ADR-0276 §3,
        #2951). Which those are is decided by :func:`_in_place` over the episode's own
        texts; what is rendered is still only the projection (ADR-0284 §8:3).
        """
        place = _in_place(record, projection, self._in_place.get(record.id))
        shown: dict[str, object] = {"label": label, "at": projection.occurred_at.isoformat()}
        given = self._episode_input(projection, in_place=place.input)
        if given is not None:
            shown["input"] = given
        if projection.meaning is not None:
            shown["understood_then"] = projection.meaning
        if projection.response is not None:
            shown["response"] = _IN_PLACE_WINDOW if place.response else _text(projection.response)
        if projection.status is not None and projection.reason is not None:
            shown["ended"] = f"{projection.status.value}: {projection.reason.value}"
        if projection.derived_from_external:
            shown["outside_content"] = _OUTSIDE
            self.shown.marked = True
        if projection.rounds:
            shown["rounds"] = [
                self._episode_round(one, in_place=index in place.messages)
                for index, one in enumerate(projection.rounds)
            ]
        if projection.candidates:
            # ADR-0329 §6:9: an unprocessed episode's candidates, each by its fact and
            # marked pending.
            shown["candidates"] = [
                {"fact": _text(one), "status": _PENDING} for one in projection.candidates
            ]
        if projection.evidence:
            # ADR-0308 §3:1, §5:5: the episode's evidence, each item's text and its mark
            # and never its source label, under the reader's audience as the projection
            # decides it. It is outside content, so planning has read it (§5:4).
            shown["evidence"] = [
                {"text": _text(one.text), "outside_content": _OUTSIDE}
                for one in projection.evidence
            ]
            self.shown.marked = True
        return shown

    def _episode_input(self, projection: EpisodeProjection, *, in_place: bool) -> object:
        """Another episode's input as shown, attributed from its parties, or ``None``.

        An outside report's, a relayed input's included, is withheld and marks the
        round's notes (ADR-0303 §3:2, ADR-0351 §5:4, §5:7). A scheduled task's
        instruction, whose parties are the assistant's statement, is the assistant's own
        words, which the projection never shows and nothing reads as the user's
        (ADR-0350 §6:12). An episode with no processing record has no parties, and is
        attributed by neither.
        """
        recorded = projection.has_processing_record
        if recorded and parties_are_outside(projection.parties, relayed=projection.relayed):
            self.shown.marked = True
            return "an outside report, not shown"
        if recorded and parties_are_assistants(projection.parties, relayed=projection.relayed):
            return "the assistant's own instruction for work it scheduled, not shown"
        if projection.input is None:
            return None
        return _IN_PLACE_WINDOW if in_place else _text(projection.input)

    def _episode_round(self, one: ProjectedRound, *, in_place: bool) -> dict[str, object]:
        """One of another episode's rounds: its message, and its notes where shown.

        Its message says it is in the place window where ``in_place`` says the window
        shows it whole (ADR-0276 §3).
        """
        shown: dict[str, object] = {}
        if one.message is not None:
            shown["message"] = _IN_PLACE_WINDOW if in_place else _text(one.message)
        if one.notes is not None:
            shown["notes"] = _text(one.notes)
            if one.notes_marked:
                # ADR-0303 §3:6: a marked note planning reads is outside content read.
                shown["notes_outside_content"] = _OUTSIDE
                self.shown.marked = True
        return shown

    def _round(self, number: int, one: PlanningRound) -> dict[str, object]:
        outcomes = {
            outcome.call_id: outcome
            for outcome in self._inputs.outcomes
            if outcome.round_id == one.id
        }
        shown: dict[str, object] = {"round": number}
        if one.text.strip():
            where = "written into the place" if self._inputs.place.takes_message else "kept"
            if one.id in self._inputs.not_taken:
                where = _NOT_TAKEN
            elif one.id in self._inputs.overtaken:
                where = _OVERTAKEN
            shown["text"] = one.text
            shown["text_was"] = where
            if one.place is not None:
                # ADR-0350 §12:8: the place its message went into, by its place label.
                shown["into"] = self._place_named(
                    f"{one.place.channel_type}:{one.place.instance_id}"
                )
        shown["calls"] = [
            self._call(call, outcomes.get(call.call_id), reference=f"{number}.{index}")
            for index, call in enumerate(one.calls, 1)
        ]
        if one.notes is not None:
            shown["notes"] = one.notes
            if one.notes_marked:
                shown["notes_outside_content"] = _OUTSIDE
                self.shown.marked = True
        return shown

    def _call(
        self, call: ProposedCall, outcome: CallOutcome | None, *, reference: str
    ) -> dict[str, object]:
        shown: dict[str, object] = {
            "capability": call.name,
            "arguments": call.model_dump()["arguments"],
        }
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
        result: dict[str, object] = {"label": self._book.label(LabelKind.RESULT, outcome.result_id)}
        result["value"] = self._result_value(outcome)
        shown["result"] = result
        return shown

    def _result_value(self, outcome: CallOutcome) -> object:
        """What a done call's result shows: what it looked up, or what it returned.

        A story read's view, its marks with it, a marked line outside content read,
        which rendering it counts (ADR-0300 §10:6); a memory search's records; a
        candidate's lookup; a call on the Task Scheduler or on running work; an episode
        look-up's (ADR-0358 §7-§10); or the result itself, a digested one as read for
        planning by its digest.
        """
        looked: tuple[tuple[object, Callable[[Any], object]], ...] = (
            (outcome.story, self._story),
            (outcome.records, lambda _: self._searched(outcome)),
            (outcome.candidate, self._candidate),
            (outcome.tasks, self._listing),
            (outcome.peer, self._peer),
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
        shown = self._shown_episode(one.record)
        if one.matters:
            shown["in_matters"] = [self._matter(matter) for matter in one.matters]
        return shown

    def _shown_episode(self, record: EpisodicMemory) -> dict[str, object]:
        """An episode a look-up shows, as the episode window shows one (ADR-0358 §7:2, §9:2)."""
        projection = project_episode(
            record, excerpt_chars=self._excerpt_chars, owner_records=self._inputs.owner_records
        )
        label = self._book.label(LabelKind.EPISODE, record.id)
        self._rendered.add(record.id)
        return self._episode(label, projection, record)

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

    def _older_item(self, item: PlaceItem, history: OlderHistory) -> dict[str, object]:
        """An older item as the place window shows one, a relayed input's withheld (§9:3)."""
        shown = self._item(item)
        if history.withheld(item) and item.author is PlaceAuthor.USER:
            shown["text"] = _RELAYED_ITEM
        return shown

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
        shown: dict[str, object] = {"at": projection.occurred_at.isoformat()}
        given = self._episode_input(projection, in_place=False)
        if given is not None:
            shown["input"] = given
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
            return {"round": part.position + 1} | self._episode_round(part, in_place=False)
        return self._full_record_part(part)

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
        shown["showed"] = parts or _NOTHING_SHOWN
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
                shown.append(self._memory(memory) | {"shown": _AS_HELD_NOW})
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
        """What a message call sent, where it went and how (ADR-0356 §8:4), or nothing.

        ADR-0357 §3:1: the text delivered, after any rewording and with any exact lines;
        where it went, the place by its place label where planning holds one, and the
        platform beside it; and how it went, with the reason for a failure or an unknown.
        """
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
        """Which case of needing the user applies to a call (ADR-0321 §2:10).

        A call is offered for asking, under ``reference``, only where the place takes a
        message, its request was handed on, and it is not already asked about: by an
        earlier question still waiting on the user (§4:11) or by an earlier round of
        this activation.
        """
        shown: dict[str, object] = {}
        request = outcome.request
        earlier = None if request is None else self._asked_earlier(request)
        if not self._inputs.place.takes_message:
            shown["outcome"] = _NO_ONE_TO_ASK
        elif outcome.already_asked is not None:
            shown["outcome"] = _ALREADY_ASKED
        elif earlier is not None:
            shown["outcome"] = _ALREADY_ASKED
            number, asked = earlier
            shown["asked_in"] = f"round {number}'s message, part {asked.part}"
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

    def _replacing(self, replaces: Sequence[Memory]) -> dict[str, object]:
        """What a remember's question would show it replacing, as planning may see it.

        Each assertion whose source is not outside is shown by its fact under its M
        label, as a found record is. One resting on outside content is not shown here
        and is not shown in the question either (ADR-0307 §9:2): the question's text is
        the round's, which every later round and the place window replay. So it is not
        retired on a yes (ADR-0321 §5:5), and planning is told so by count.
        """
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
        (ADR-0338 §8:6), names nothing. One still needing the user may be asked about
        where the place takes a message, no question waits on it (ADR-0321 §4:11), and
        no round of this activation has asked about it since.
        """
        now = {(one.round_id, one.call_id): one for one in self._inputs.outcomes}
        kept: dict[str, CallOutcome] = {}
        for reference, key in carried.items():
            outcome = now.get(key)
            if outcome is None or not self._inputs.place.takes_message:
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

    def _approved(self, one: ApprovedAction) -> dict[str, object]:
        """An approved action under its A label, with the details its question showed."""
        call = one.call
        return {
            "label": self._book.label(LabelKind.APPROVED_ACTION, _approved_id(one.part)),
            "capability": str(call.tool.capability),
            "details": exact_line(call, filled=_filled(self._inputs.capabilities, call)),
            "approved": _APPROVED_BY,
        }

    def _searched(self, outcome: CallOutcome) -> dict[str, object]:
        """A memory search's result: its records not outside, and where the rest went.

        Each record whose source is not outside is shown by its fact under its own M
        label, as a found one is (ADR-0308 §3:3); one whose current version rests on
        outside content is withheld. The outside records reach planning only as the
        digest's evidence (ADR-0306 §5:16).
        """
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
        """A candidate's result: recorded and pending, with the memories like it.

        ADR-0329 §6:5: it tells planning the candidate is recorded and pending. §4:1:
        each similar memory not resting on outside content by its fact under its own M
        label, as a found one is; one whose current version rests on outside content is
        withheld, as a search's is (§4:2). §4:4: a lookup that failed says so.
        """
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

    def _evidence(self, one: DigestedEvidence) -> dict[str, object]:
        """One digest, under the label of the result it read (ADR-0308 §5)."""
        digest_of = (
            _RECALL_DIGEST
            if one.result_id is None
            else self._book.label(LabelKind.RESULT, one.result_id)
        )
        shown: dict[str, object] = {"digest_of": digest_of}
        if one.question is not None:
            shown["looking_for"] = one.question
        shown["digest"] = self._digest(one)
        return shown

    def _digest(self, one: DigestedEvidence) -> dict[str, object] | str:
        """One digest's evidence, each item with its source's label (ADR-0308 §5:1)."""
        if not one.answered:
            return _DIGEST_FAILED
        # ADR-0308 §5:4: a digest that answered, with or without items, is read.
        self.shown.marked = True
        return {
            "evidence": [
                {
                    "text": item.text,
                    "source": self._book.label(item.source_kind, item.source_id),
                    "outside_content": _OUTSIDE,
                }
                for item in one.items
            ]
            or _NOTHING_ANSWERED
        }


def _text(projected: ProjectedText) -> str:
    """A projected text, saying where the excerpt bound cut it."""
    if projected.cut:
        return f"{projected.text}… (cut: {len(projected.text)} of {projected.full_chars} chars)"
    return projected.text


#: What a peer view's reader is told where the episode could not be read (§6:7).
_PEER_UNREAD: Final = "could not be read"
#: ADR-0352 §3:1: a stop call's result where the stopped activation set up nothing live.
_NOTHING_SET_UP: Final = "nothing it set up is still live"
#: Where what it set up could not be read: the stop stands, and nothing is claimed of it.
_SET_UP_UNREAD: Final = "could not be read, so nothing is known of what it set up"
#: ADR-0352 §3:4: an activation pushed from a task and not yet admitted.
_STARTING: Final = "starting"
#: What a peer's meaning is, read as provisional (ADR-0276 §4:6, ADR-0349 §6:9).
_PROVISIONAL: Final = "provisional, as understood so far: "


def _withheld(*, outside: bool, assistants: bool) -> str:
    """Why an activation's input is not shown, by whose words it carries (ADR-0284 §8:1).

    Outside, read with its relay mark (ADR-0351 §5:1, §5:7), or the assistant's
    (§5:2); otherwise only not shown.
    """
    if outside:
        return "an outside report, not shown: " + _OUTSIDE
    if assistants:
        return "the assistant's own instruction for work it scheduled, not shown"
    return "not shown"


def _effect_text(effect: PeerEffect) -> str:
    """One effect another activation made, as its peer view shows it (§6:9)."""
    if effect.couldnt_finish:
        return PEER_COULDNT_FINISH_LINE
    unknown = effect.outcome is ToolOutcome.INDETERMINATE
    if effect.capability is not None:
        if unknown:
            return f"the tool {effect.capability} may have run; whether it did is not known"
        return f"the tool {effect.capability} ran"
    message = "a message" if effect.message is None else f"the message: {_text(effect.message)}"
    return f"may have sent {message}" if unknown else f"sent {message}"


def _place_text(channel: ChannelIdentity) -> str:
    """A place, as planning is shown what caused an activation: channel and place."""
    return f"{channel.channel_type}:{channel.instance_id}"


@dataclass(frozen=True, slots=True)
class _InPlace:
    """Which of an episode's texts the place window shows whole (ADR-0276 §3, #2951).

    Attributes:
        input: Its input.
        response: Its response.
        messages: Its rounds whose message it shows, by their place in the
            projection's rounds.
    """

    input: bool = False
    response: bool = False
    messages: frozenset[int] = frozenset()


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


def _in_place(
    record: EpisodicMemory, projection: EpisodeProjection, place: _PlaceTexts | None
) -> _InPlace:
    """Which of ``record``'s texts the items ``place`` holds show whole.

    Decided over the episode's own whole texts, never the projection's cut ones, so a
    text is said to be in the window only where it is there character for character:
    its input where the user's items, joined, are that input; its response where the
    assistant's, joined, are that response; and a round's message where an assistant's
    item is that message, each item standing for one round, the latest rounds first,
    since the window is the conversation's most recent part.
    """
    if place is None:
        return _InPlace()
    user, assistant = place.user, place.assistant
    return _InPlace(
        input=bool(user) and _JOINED.join(user) == _input_of(record),
        response=bool(assistant) and _JOINED.join(assistant) == record.outcome,
        messages=_messages_in_place(record, projection, assistant),
    )


def _input_of(record: EpisodicMemory) -> str | None:
    """An episode's whole input, as :func:`project_episode` reads it before cutting it."""
    processing = record.processing_record
    if processing is None:
        return record.content
    payload = processing.trigger.payload
    return payload.text if isinstance(payload, RecordedTextInput) else payload.transcript


def _messages_in_place(
    record: EpisodicMemory, projection: EpisodeProjection, written: Sequence[str]
) -> frozenset[int]:
    """The projection's rounds whose message one of ``written`` is, whole.

    The projection shows a round's message where its text is not blank, in the order
    recorded, so its rounds carrying a message are the record's rounds with text, one
    for one. That is checked, each projected message a cut of its round's text, and
    where it does not hold no message is said to be in the window.
    """
    processing = record.processing_record
    if processing is None or not written:
        return frozenset()
    texts = [one.text for one in processing.rounds if one.text.strip()]
    projected = [
        (index, one.message)
        for index, one in enumerate(projection.rounds)
        if one.message is not None
    ]
    if len(texts) != len(projected) or not all(
        message.full_chars == len(text) and text.startswith(message.text)
        for (_, message), text in zip(projected, texts, strict=True)
    ):
        return frozenset()
    unclaimed = Counter(written)
    shown: set[int] = set()
    for (index, _), text in reversed(list(zip(projected, texts, strict=True))):
        if unclaimed[text]:
            unclaimed[text] -= 1
            shown.add(index)
    return frozenset(shown)


def _offers_story_reads(offered: Sequence[OfferedTool]) -> bool:
    """Whether a story read is among the round's offered tools (#2893, #2944)."""
    return any(tool.name == _READ_STORY for tool in offered)


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
_NOTHING_SHOWN: Final = "nothing"
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

        Raises:
            ValueError: If ``excerpt_chars`` is below 1, or ``prompt`` is not a template
                of :data:`PLANNING_PROMPT`.
            ZoneInfoNotFoundError: If ``timezone`` names no known zone. ``Settings``
                refuses one at load, so a composition root reaching here has already
                been validated.
        """
        if excerpt_chars < 1:
            msg = "planning's excerpt bound must be at least 1"
            raise ValueError(msg)
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
        request = _Request(
            inputs,
            book,
            excerpt_chars=self._excerpt_chars,
            now=self._now(),
            zone=self._zone_for(inputs.person),
        )
        instruction: RenderedPrompt | None
        if work is None:
            # ADR-0356 §5:2: a work's first round renders the briefing, once, and the
            # instruction it is asked under, which every later round hands in unchanged.
            rendered = request.rendered(offered_here)
            instruction = self._prompt.rendered(
                flags=self._flags(inputs, offered, approved_tool=approved_tool is not None),
                values=_PLANNING_VALUES,
            )
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
        # ADR-0356 §7:2, §14:1: the round's text is kept as its notes. Until P3 makes the
        # text notes alone, it is also still the round's message, as the least that keeps
        # every reader of a reply working, and it asks about nothing (§7:5).
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
        # ADR-0350 §6:7, §12:8: a message of an activation the Task Scheduler started
        # names, by its place label, the one place on its list it goes into.
        text, place = (
            _named_place(response.text, book) if inputs.speaks_by_label else (response.text, None)
        )
        planning_round = PlanningRound(
            id=self._new_id(),
            follows=inputs.rounds[-1].id if inputs.rounds else None,
            recorded_at=self._now(),
            text=text,
            place=place if text.strip() else None,
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
            message=(
                planning_round.text
                if inputs.place.takes_message and planning_round.text.strip()
                else None
            ),
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

    @staticmethod
    def _flags(
        inputs: PlanningInputs, offered: Sequence[OfferedTool], *, approved_tool: bool
    ) -> dict[str, bool]:
        """The template's flags, computed once, at the work's first round (ADR-0334 §2:1).

        The instruction is the same on every round of a work (ADR-0356 §5:2), so it is
        rendered under what the first round holds, and a condition that may change between
        rounds is held to one value. ADR-0356 §4:2 takes every flag away in the lane that
        rewrites the instruction (§14:3).
        """
        return {
            "takes_message": inputs.place.takes_message,
            "story_calls": any(tool.name in STORY_CALL_CAPABILITIES for tool in offered),
            "story_reads": _offers_story_reads(offered),
            "approved": approved_tool,
            "candidates": any(tool.name == REMEMBER_CAPABILITY for tool in offered),
            "reliance": any(tool.name == NOTE_RELIANCE_CAPABILITY for tool in offered),
            "person": inputs.person is not None,
            "suggestions": inputs.person is not None and bool(inputs.person.suggestions),
            "spawn": inputs.places is not None
            and any(tool.name == SPAWN_CAPABILITY for tool in offered),
            "scheduled": inputs.speaks_by_label,
            "running_work": any(tool.name in _RUNNING_WORK_CALLS for tool in offered),
            # What may change between a work's rounds is held to one value, since the
            # instruction does not change with it: the offers' and the earlier work's
            # lines are sent on every round, and the waiting round's line in place of the
            # rest never is; a call a waiting round may not make is refused (§4:5).
            "offers": True,
            "waiting": False,
            "earlier_work": True,
        }

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


#: A message's leading place label, as planning is told to write it: ``L1: …``.
_PLACE_LABEL: Final = re.compile(r"\A\s*\[?(L[1-9][0-9]{0,8})\]?\s*[:\u2014\u2013-]\s*")


def _named_place(text: str, book: _LabelBook) -> tuple[str, ChannelIdentity | None]:
    """The message without its leading place label, and the place the label names.

    ADR-0350 §6:7: each message of an activation the Task Scheduler started names, by its
    place label, the one place on its list it goes into. A label naming no place
    planning was shown, or none at all, names no place, and authorizing refuses the
    message; the text is then kept as written.
    """
    found = _PLACE_LABEL.match(text)
    if found is None:
        return text, None
    named = book.resolve(found.group(1))
    if named is None or named.kind is not LabelKind.PLACE:
        return text, None
    channel = place_channel(named.id)
    if channel is None:
        return text, None
    return text[found.end() :], channel


def _offered_declarations(
    capabilities: Sequence[ToolDefinition], offered: Sequence[OfferedTool]
) -> dict[str, ToolDefinition]:
    """Each offered capability's first declaration, by id, which its tools all agree with."""
    names = {tool.name for tool in offered}
    declarations: dict[str, ToolDefinition] = {}
    for tool in sorted(capabilities, key=lambda one: str(one.id)):
        declarations.setdefault(str(tool.capability), tool)
    return {name: declaration for name, declaration in declarations.items() if name in names}
