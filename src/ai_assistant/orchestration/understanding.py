"""The understanding stage: an activation read before it is associated (ADR-0276).

One orchestration-local stage: it holds an injected ``ModelProvider`` and reads no
store, and it is **not a Protocol** (§1). The episode window's records are handed to it:
ADR-0282's **windows stage**, below, holds the composition root's **episode selector**
and records the window as ids, and the understanding phase fetches them (ADR-0282 §3,
§5). It receives no goal, no candidate goal, no attempt, no plan, no retrieved memory
and no context-provider state, and its prompt renders none of them — it reads the
activation's input and the two windows §3 and §4 define, and nothing else, save what
recall kept for the pass and the short views of the candidate stories (ADR-0300 §6,
superseding ADR-0276 §1:5 for those alone).

**What recall kept** (ADR-0281 §7) renders as a third section, ``recalled``, labelled
``M1``, ``M2``… in recall's order, only where recall made a decision for the pass: its
records as the understanding phase fetched them (ADR-0282 §5). A recalled record either
window already rendered stays there only. A recalled episode
takes the episode window's projection; a recalled memory renders its wording,
cut with the cut disclosed, its last update (ADR-0328 §7:8's transaction time) and an
attribution by band, marked
``not_linkable`` on every pass (ADR-0305 §3), and its label resolves to a ``memory``
referent. Where recall kept nothing, or failed, the section says so.

**The person section** (ADR-0338 §7:2, §7:6-§7:7). Where the activation is a person's and
its person block was assembled, the message begins with it: the person's five fields,
each as their own choice and never as an instruction, and the memories they pinned,
labelled ``M1``, ``M2``… ahead of the recalled section, whose ``M`` labels follow on. A
recalled record the section shows is rendered there only. Nothing else of the person
model reaches this stage: no style memory and no suggestion (superseding ADR-0276 §1:5
and ADR-0281 §7:2 for those additions alone). Where there is no block, no section
renders and the instruction says nothing of one.

**The candidate stories** (ADR-0300 §6) render as a fourth section, ``stories``,
labelled ``S1``, ``S2``… in the candidates' order, only where the understanding phase
assembled candidates for the pass: each story's short view — the first lines of its
summary and its mark, or that the summary was withheld, its newest pending notes, or
nothing about its notes on a pass that may not be shown them (ADR-0305 §4), and its
latest episodes, which take no label — as
:class:`~ai_assistant.orchestration.story_links.StoryCandidates` read it, under ADR-0303
§3's privacy default. The summary and every note are quoted source data attributed by
their records, the summary as the tidy-up's and marked or not, a note by who wrote it and
whether it is marked, and a marked one as outside content, never as the user's words
(ADR-0303 §3:7, §3:8). The reply's ``belongs_to`` names the matters the input belongs to
(ADR-0353 §9:2): an ``S`` label resolves to its story, a ``P`` or ``M`` label naming an
episode to that episode's activation, and an ``R`` label to its running activation
(ADR-0353 §10:3). So does an ``H`` label naming a channel item that links to an
activation (ADR-0303 §7): a supplied item that is one exchange with an episode of the
episode window, to its episode's activation (ADR-0301 §1:1); a transcript message to the
activation the chat reader's bookkeeping records as having taken it in, which the reader
brings with the window. All of it is read off what the pass already holds, and nothing
is fetched. A label in ``belongs_to`` naming an item that links to no activation, or a
remembered fact, which is never a story link, is dropped and counted, with no repair
(ADR-0353 §9:12, ADR-0303 §7:6, ADR-0305 §3:2). One resolving to nothing rendered, or to
an episode recording no activation, is a label defect, repaired once and then dropped
and counted (ADR-0300 §6:8, ADR-0353 §9:10). An ``S`` label is also cited in ``cites``,
and resolves there to a ``story`` referent; cited there it links nothing (ADR-0304 §8,
ADR-0353 §9:4). Where the candidates could not be read, or there are none, the section
says so.

**Taken-in input, and the in-progress section** (ADR-0349 §5, §7, §10:1-§10:2). An input
a merge brought is part of the activation's input: it is rendered with the trigger's,
each kept apart and dated and marked as taken over, and the version that named its
activation covers it (§7:9). Beside the windows, a fifth section, ``in_progress``, shows
each activation running for the same person on any place, the Task Scheduler's included,
that the pass may be shown, newest first and at most ``in_progress_limit`` of them, with
how many more run — each exactly what caused it, its input in brief read through the peer
view, and whether it has acted — labelled ``R1``, ``R2``… An ``R`` label joins the one
table every label resolves through (ADR-0353 §10:2): cited in ``cites`` it resolves to a
``running`` referent, named by that activation's episode id, its channel and its input in
brief as its entry rendered it (§10:1); in ``belongs_to``, to the running activation as
an activation member (§10:3). Only the reply's ``meant_for`` makes the input part of
running work: it names, by ``R`` label, zero or more of them its input is meant for, each
resolving to that activation's id, once, in the reply's order, into ``continues``
(§10:4). A label in ``meant_for`` naming no shown activation, and an ``R`` label in
``cites`` or ``belongs_to`` naming no shown entry, is dropped and counted with no repair
(§9:11): a repair would delay every activation waiting on this one's understanding. The
section and its instruction take no template flag: the instruction says what the section
is wherever it is rendered, and a pass shown nothing renders none.

**Two windows, two label sequences** (§3). The **channel window** is what the channel
supplied — ``ChannelContext.history`` then ``reply_to`` — or, for an input the chat's
reader brought in, the conversation's recent transcript, each message keeping its
author (ADR-0293 §6:4, §6:5). Its items are labelled ``H1``, ``H2``… The **episode
window** is what the selector returns (§4), labelled ``P1``, ``P2``… in the selector's
order. The input carries no label. No label survives the call and none is persisted —
each resolves, here, into an :class:`~ai_assistant.core.types.UnderstandingReferent`
built from the material this module rendered, never from model output (§2).

**The same exchange in both windows is rendered once** (§3): an episode whose stored id
equals a channel item's identifier is the channel item, under its ``H`` label, annotated
as also present in the episode window; it takes no ``P`` label and is not counted
toward the selector's bound. A transcript message that links to an activation is
identified by that activation's episode, so on the chat path too an earlier exchange of
the conversation is shown once, as its messages (#2899); where it is several messages,
the first carries the episode's annotations and each is marked.

**Validation, one repair, then record or refuse** (ADR-0276 §6, ADR-0353 §9:10). The
output must parse as one :class:`~ai_assistant.core.types.ProposedActivationUnderstanding`,
and then every label in ``cites`` and ``belongs_to`` that is not of the ``R`` form must
resolve. A first output failing either earns **exactly one** further completion carrying
it and a code-owned statement of what was wrong. A second output that does not parse
raises :class:`~ai_assistant.core.errors.UnderstandingError`; one that parses but still
carries a label resolving to nothing is **recorded**, the label dropped and counted,
because a label the model misspelled twice is a claim the stage cannot ground, not a
mechanical failure. There is no ground to downgrade (ADR-0353 §12). The drops §9:11 and
§9:12 name are made with no repair at all. A ``ModelError`` propagates unchanged.
Nothing here substitutes an empty, default or invented understanding.

**A key the reply shape does not name is dropped before the parse** (ADR-0339 §2), at
every depth, on every reply: no key exempts a reply from it, ``answers`` included
(ADR-0353 §9:14). Whether the drop applies is decided from the reply's text alone, so
the regression suite's reader, which is :func:`_parsed`, reads a reply as the stage
does. A reply refused only for such keys is a parsed output and costs no repair; the
types keep ``extra="forbid"``, the repair still carries the first output unpruned, and
the diagnostic record keeps the reply as the model wrote it (§3).

**No question is marked, and no answer pointer is read** (ADR-0353 §11). Understanding
is shown no question mark and no ``Q`` label, and the reply carries no pointer, so the
stage records none: authorizing's rules stand and find no pointer (§11:3). The windows
still bring each assistant message's question with them (``TranscriptWindow.asked``,
``WrittenBy.asked``), and this stage no longer reads it.

**The instruction is a template** (ADR-0334): the system message is rendered from
:data:`UNDERSTANDING_PROMPT`'s template, which the composition root reads at start and
hands the stage, and this module keeps no copy of its text (§3:1). The stage computes
the template's flags for each call; the rendered request, the label validation, the
one repair and every rule above stay here, whatever a template says (§1:3, §7:2).

**It logs stage and code-owned reason only** — no input, no window content, no model
output and no exception content (ADR-0275 §8) — save, on an output that parsed after
the drop removed keys, the number removed, computed by code and logged as ``stray``
(ADR-0339 §4): never a key's name, which is model output, and never under a field
named for ``key``, which the hub's log redaction masks.
"""

from __future__ import annotations

import asyncio
import functools
import json
import re

# At runtime, not under TYPE_CHECKING: `EpisodeSelector` is a PEP 695 alias, whose
# value is read lazily and must resolve when it is (#1706).
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final, get_args, get_origin

import structlog
from pydantic import BaseModel, ValidationError

from ai_assistant.core.channel_validation import input_origin
from ai_assistant.core.diagnostics import write_diagnostic, write_failure
from ai_assistant.core.episode_encoding import project_episode
from ai_assistant.core.errors import UnderstandingError
from ai_assistant.core.prompts import PromptDeclaration
from ai_assistant.core.types import (
    DEFAULT_ASSISTANT_NAME,
    UNDERSTANDING_REFERENT_EXCERPT_CHARS,
    ActivationUnderstanding,
    BeliefBand,
    DeletedMessage,
    DiagnosticKind,
    DiagnosticSource,
    EpisodicMemory,
    InputOrigin,
    Memory,
    Message,
    MessageAuthor,
    ProfileField,
    ProposedActivationUnderstanding,
    RecallOutcome,
    Role,
    StoryMember,
    StoryMemberKind,
    StoryNoteAuthor,
    UnderstandingProducer,
    UnderstandingReferent,
)
from ai_assistant.orchestration.disclosure import admitted_to_understanding
from ai_assistant.orchestration.episode_reads import without_open_episodes
from ai_assistant.orchestration.stories import episode_address
from ai_assistant.orchestration.story_privacy import activation_of

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from ai_assistant.core.prompts import PromptTemplate, RenderedPrompt
    from ai_assistant.core.protocols import DiagnosticSink, MemoryStore, ModelProvider
    from ai_assistant.core.types import (
        ActivationRecall,
        ChannelContext,
        ChannelContextItem,
        ChannelIdentity,
        ClaimedAuthor,
        EpisodeProjection,
        JoinedInput,
        RecordedInputMessage,
        StoryNote,
        StorySummaryLine,
        TranscriptMessage,
    )
    from ai_assistant.orchestration.disclosure import TurnSupply
    from ai_assistant.orchestration.matters import InProgressEntry
    from ai_assistant.orchestration.person_block import PersonBlock
    from ai_assistant.orchestration.story_links import Candidates, ShortView

__all__ = [
    "UNDERSTANDING_PROMPT",
    "AskedIn",
    "ChannelWindow",
    "EpisodeSelector",
    "LineMessage",
    "RecentEpisodes",
    "SuppliedWindow",
    "TranscriptWindow",
    "UnderstandingStage",
    "WrittenBy",
    "place_window_links",
]

_log = structlog.get_logger(__name__)

#: The page bound :meth:`~ai_assistant.core.protocols.MemoryStore.episodes` admits.
_MAX_PAGE: Final = 100

#: The time of an item that carries none, in :func:`place_window_links`' order. Only a
#: transcript's items carry none, and they are ordered by position.
_NO_TIME: Final = datetime.min.replace(tzinfo=UTC)

#: How many unresolvable labels the repair statement names, and how much of each. The
#: labels are the model's own strings, so the statement bounds them rather than echoing
#: whatever length a first output chose.
_REPAIR_LABELS_SHOWN: Final = 20
_REPAIR_LABEL_CHARS: Final = 32

#: The code-owned reason the count of dropped unnamed keys is logged under (ADR-0339 §4:1).
_UNNAMED_DROPPED: Final = "unnamed_keys_dropped"

#: Understanding's prompt (ADR-0334 §2): its system message is the template
#: ``understanding.txt`` shipped beside this module, or the owner's override of it, which
#: the composition root reads and hands the stage (§3:5). It may branch on two flags and
#: prints no value:
#:
#: - ``recalled``: recall made a decision for the pass, so the message carries a recalled
#:   section (ADR-0281 §7); a pass with none keeps the instruction it had.
#: - ``stories``: the understanding phase assembled candidate stories, so the message
#:   carries a stories section and the reply's shape gains ``story_labels`` (ADR-0300 §6);
#:   a pass with none keeps the instruction it had.
#: - ``person``: the activation is a person's and a person block was assembled for it, so
#:   the message carries a person section (ADR-0338 §7:2); a pass with none keeps the
#:   instruction it had.
#:
#: **What the instruction must say**, which binds the default and every override alike
#: (ADR-0334 §7:1), and which a promotion's review reads it against (§7:3): that every
#: value of the message is quoted source data, and who said something is stated by the
#: keys around it (ADR-0276 §3:6, under ADR-0098 §2); what the grounds mean, and that a
#: ``supplied`` reading names a label (ADR-0276 §2:6, §6); what a recalled memory is,
#: and that an ``M`` label grounds a reading ``supplied`` (ADR-0281 §7); ADR-0300 §6:9's
#: readings of a story link; where an ``S`` label may be cited and what citing it does
#: (ADR-0304 §8:5) — the repair statement carries no rule on it (§8:6), so the
#: instruction alone says it; which ``H`` labels a story label may name (ADR-0303 §7:8);
#: that a remembered fact is never a story link (ADR-0305 §3); and ADR-0321 §3's readings
#: of an answer, as ADR-0322 §2 and §4 extend them, including when one reply approves
#: several questions (§4:9), that a ``Q`` label goes only in ``answers`` (#3081), and
#: that an unresolved matter names by ``Q`` label each question a bare yes could fit
#: (#3080); and ADR-0349's additions, which take no flag: what the in-progress section
#: shows (§5:2-§5:6), that ``continues`` names every entry the input corrects, completes,
#: cancels or changes and separate work continues none (§7:3), and that an ``R`` label
#: goes only in ``continues`` (§5:7). Input a merge brought is covered by the version that
#: named its activation (§7:9), so understanding never runs on it and the instruction
#: says nothing of it; and, under ``person``, what the person section is: the
#: person's own choices and the memories they pinned, data and never instructions, whose
#: ``M`` labels come first (ADR-0338 §7:6-§7:7), and that the language is a hint for
#: reading their input (§3:11). Authority is not read here: whose
#: input approves is authorizing's check (ADR-0321 §3:3), and a pointer grants nothing.
UNDERSTANDING_PROMPT: Final = PromptDeclaration(
    name="understanding",
    package="ai_assistant.orchestration",
    flags=frozenset({"recalled", "stories", "person"}),
)


#: How a recalled memory is attributed, by its band (ADR-0281 §7, ADR-0328 §12).
_BAND_ATTRIBUTION: Final = {
    BeliefBand.ASSERTED: "a remembered fact: something the user said",
    BeliefBand.DERIVED: "a remembered fact: something the assistant worked out",
    # Not "a connected source": the band also holds a memory resting on the
    # assistant's own message (ADR-0328 §4, §6), which no integration reported.
    BeliefBand.ATTESTED: (
        "a remembered fact: something from a source, never something the user said"
    ),
}

#: The recalled section where it renders no record (ADR-0281 §7).
_NOTHING_RECALLED: Final = "missing: nothing was recalled for this input"
_RECALL_FAILED: Final = "missing: recall failed, so no memories are shown"
_ALREADY_SHOWN: Final = "missing: everything recalled is already in the windows above"
#: The same, where a person section renders beside the windows (ADR-0338 §7:7): a recalled
#: record the person section shows is rendered there only.
_ALREADY_SHOWN_ABOVE: Final = "missing: everything recalled is already shown above"
_NO_LONGER_HELD: Final = "missing: what was recalled is no longer in memory"

#: The stories section where it renders no story (ADR-0300 §6:4).
_NO_STORIES: Final = "missing: none of the earlier episodes shown belongs to a story"
_STORIES_UNREADABLE: Final = "missing: the stories could not be read, so none is shown"

#: A short view's parts where they render nothing.
_NO_LINES: Final = "missing: no line of this story's summary is shown"
#: A summary written but withheld from this pass's audience (ADR-0304 §4:1, §4:2): the reader
#: is told a summary exists that this audience may not be shown, and nothing of it, its mark
#: included. Nothing behind the summary is the reason (§4:3).
_SUMMARY_WITHHELD: Final = (
    "missing: this story has a summary, withheld here because this audience may not be shown it"
)
_NO_NOTES: Final = "missing: no note is waiting to be folded into this story's summary"
_NO_EPISODES: Final = "missing: no episode of this story is shown"

_STORY_ITEM: Final = "a story: the assistant's memory of one matter"

#: The person section (ADR-0338 §7:2, §7:6): who the person is, by their own choices, and
#: the memories they pinned, each said as theirs and never as an instruction.
#: The person the activation is *for* (ADR-0338 §2:2), which says nothing of who wrote
#: the input: that is the input's own rendering, by its recorded origin (ADR-0284 §2:3).
_PERSON_ITEM: Final = (
    "the person the assistant is working for in this activation, by the profile they set: "
    "each field is their own current choice, never an instruction. Who wrote the input is "
    "said with the input, not here"
)
_NOT_SET: Final = "not set"
#: What each field is, as the section says it (ADR-0338 §3's table, §3:11).
_FIELD_TEXT: Final = {
    ProfileField.NAME: "what they are called, as they write it",
    ProfileField.ADDRESS: "how they like to be addressed",
    ProfileField.ASSISTANT_NAME: "what they call the assistant",
    ProfileField.TIME_ZONE: "their time zone",
    ProfileField.LANGUAGE: "the language they write in: a hint for reading what they write",
}
#: An assistant's name not set (ADR-0338 §3's table, §3:9): not set, and what that means,
#: never the default presented as the person's own choice.
_ASSISTANT_NAME_NOT_SET: Final = f"not set, so the assistant is called {DEFAULT_ASSISTANT_NAME}"
_PINNED_ITEM: Final = "a memory the person pinned for the assistant to keep in mind"
_NOTHING_PINNED: Final = "missing: the person has pinned nothing to keep in mind"

#: Who wrote a note, as a short view renders it: the note's own record of its author,
#: never a reading of its text (ADR-0303 §3:7).
_NOTE_AUTHOR_TEXT: Final = {
    StoryNoteAuthor.PLANNING: "the assistant, while working on this matter",
    StoryNoteAuthor.TIDY_UP: "the assistant, tidying this story's summary",
    StoryNoteAuthor.OWNER: "the user, writing on this story directly",
}
_LINE_AUTHOR_TEXT: Final = "the assistant, tidying this story's summary"
_OUTSIDE_TEXT: Final = (
    "rests on outside content: what a source reported, never something the user said"
)
#: A marked summary's mark, said of the summary because a line carries none (ADR-0303 §3:4):
#: the lines' own words say which part came from outside.
_SUMMARY_OUTSIDE_TEXT: Final = (
    "some of this summary rests on outside content: what a source reported, never something "
    "the user said; its lines' own words say which"
)

#: A label of the ``R`` form (ADR-0353 §9:10, §9:11): ``R`` and a decimal number. One in
#: ``cites`` or ``belongs_to`` naming no shown entry is dropped and counted with no
#: repair; every other unresolved label there earns the one repair.
_R_FORM: Final = re.compile(r"R[0-9]+")

_UNPARSEABLE: Final = (
    "Your reply was not one JSON object of the required shape, so it could not be "
    "read. Reply again with only that JSON object, no prose and no code fence."
)


# --- the windows ---------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SuppliedWindow:
    """A non-conversation channel's window: exactly what it supplied (ADR-0276 §3)."""

    context: ChannelContext


@dataclass(frozen=True, slots=True)
class TranscriptWindow:
    """The chat's window: its recent transcript, brought in with the input (ADR-0293 §6:4).

    What the chat's reader brought in beside the messages it took in as the input,
    replacing the tail read from episodes for that input (ADR-0293's partial
    supersession of ADR-0276 §3:1-§3:2). Each message keeps its author, so the window
    informs and never authorizes (§6:5). A message is not a stored record: it passes as
    the medium holds it, as a supplied item does. Where it links to an activation, its
    identifier is that activation's episode's stored id, which the episode window and
    recall share (ADR-0276 §3, #2899); a message that links to nothing has none.

    Attributes:
        conversation: The conversation channel, rendered as each item's source.
        messages: The conversation's recent messages, ascending, without the input's
            own and without a deleted message's marker.
        input_messages: The messages taken in as the input, ascending. The input is
            rendered with each one's position, instant and the message it replies to,
            so a correction names the message it corrects (§4:5); and an item written
            after the earliest of them is marked as such, since the transcript shows
            what was written and when (§6).
        replied_to: Each earlier message an input message replies to that
            ``messages`` does not already show, ascending — a deleted one as its
            marker (§4:5, §5:8).
        links: The activation each message of ``messages`` and ``replied_to`` links
            to, by its position (ADR-0303 §7:1-§7:3, ADR-0293 §6:6): for a message an
            activation took in, the one the reader's bookkeeping records; and where
            the phases are wired, for an assistant message the phases wrote, the
            activation its effect record names as having written it (ADR-0306 §5:3).
            The reader brings it with the window, so the understanding phase reads no
            further store to resolve a message. A message missing here links to
            nothing: neither the bookkeeping nor an effect record names an activation
            for it, as for an assistant message the old path wrote (ADR-0303 §7:5).
        asked: The question each assistant message ``links`` names its writer for is,
            by its position, where it is one (ADR-0322 §4:2), as the reader brings it
            with the window. Since ADR-0353 §11:1 understanding is shown no question
            mark, and the stage no longer reads it.
        forwarded: The original sender of each message that is a forward, by its
            position, claimed (ADR-0323 §4:10). A forward is rendered as its original
            sender's, never as the user's, and planning is never shown its raw text
            (ADR-0307 §9:2). Empty for a place that takes no forward, as the hub chat's.
        claimed: The positions of the other messages whose author the place's kind
            does not establish: on the line, a message a reply quotes that the
            assistant did not write (ADR-0323 §4:2), which may be the user's or a
            forward Telegram sent without its origin. Rendered as claimed, and, as a
            forward is, never shown to planning as raw text.

    **The Telegram line brings its window in this same shape** (ADR-0323 §10): its
    ``conversation`` is the line's channel, its messages are built from the recent
    episodes on the channel and place, and each links to the activation it records.
    """

    conversation: ChannelIdentity
    messages: tuple[TranscriptMessage | LineMessage, ...]
    input_messages: tuple[TranscriptMessage | LineMessage, ...] = ()
    replied_to: tuple[TranscriptMessage | LineMessage | DeletedMessage, ...] = ()
    links: Mapping[int, str] = field(default_factory=dict)
    asked: Mapping[int, AskedIn] = field(default_factory=dict)
    forwarded: Mapping[int, ClaimedAuthor] = field(default_factory=dict)
    claimed: frozenset[int] = frozenset()


@dataclass(frozen=True, slots=True)
class LineMessage:
    """One message of a line's window, as its kind's window brings it in (ADR-0323 §10).

    The hub chat's window carries the chat's own
    :class:`~ai_assistant.core.types.TranscriptMessage`, which records the device a
    user's message was written from (ADR-0293 §5:2). A line's messages come from no
    device of the hub — the user's Telegram apps are the user's end of the chat, not
    devices (ADR-0323 §2:4) — so they are carried in this shape, which holds what the
    window renders of a message and nothing of a device: where it is in its place,
    when it was sent, who wrote it, what it says, and what it replies to.

    Attributes:
        position: Its id in its place, as the medium gives it.
        written_at: When it was sent.
        author: Who wrote it, as the place records it: the assistant's own messages,
            and every other the user's, a forward among them marked by the window.
        text: What it says.
        replies_to: The position of the earlier message it replies to, or ``None``.
        cut_off: Never set on a line: its writer splits a long message, never cuts it.
    """

    position: int
    written_at: datetime
    author: MessageAuthor
    text: str
    replies_to: int | None = None
    cut_off: bool = False


@dataclass(frozen=True, slots=True)
class AskedIn:
    """The question a message is, by its records (ADR-0322 §4:1-§4:3).

    Attributes:
        round: The planning round that wrote the message, as its effect record names
            it, which recorded the calls the message asked about (ADR-0321 §2:8).
        parts: The parts its mark shows, as ``project_episode`` projects that round of
            the writer's episode, ``1`` to *n*; never read from the message's text.
    """

    round: str
    parts: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class WrittenBy:
    """What wrote an assistant message, by its effect record (ADR-0303 §7:1, ADR-0306 §5:3).

    Attributes:
        activation_id: The activation the record names as having written it.
        asked: The question the message is, where its round asked about calls and the
            writer's episode marks it; ``None`` for every other message.
        round: The planning round the record names as having written it; ``None`` for
            the *couldn't finish* message, which names none (ADR-0307 §10).
    """

    activation_id: str
    asked: AskedIn | None = None
    round: str | None = None


type ChannelWindow = SuppliedWindow | TranscriptWindow

#: ADR-0276 §4's **episode selector**: one orchestration-local function the
#: composition root wires into the windows stage (ADR-0282 §3), so its *method* changes by wiring a
#: different one and moves no clause and no engine byte.
#:
#: It is called with the identifiers of the channel window's items — the ids of §3's
#: *same exchange* — and returns the window's episodes in **rendering order**. An
#: episode whose id is among them may be returned and is **not counted** toward the
#: bound; every other episode it returns is. Whatever its method, a selector stays
#: within §4's walls: bounded by ``UNDERSTANDING_EPISODE_LIMIT``, across every
#: channel, requesting no eligibility, reading episodic records and nothing else,
#: invoking no model, and ranking nothing by relevance.
type EpisodeSelector = Callable[[frozenset[str]], Awaitable[tuple[EpisodicMemory, ...]]]


class RecentEpisodes:
    """The initial selector: the most recent episodes by occurrence (ADR-0276 §4).

    The ``limit`` most recent episodes by ``(occurred_at, episode_id)`` descending,
    taken from :meth:`~ai_assistant.core.protocols.MemoryStore.episodes` with no
    channel and no status filter and fetched by
    :meth:`~ai_assistant.core.protocols.MemoryStore.get_many`. That enumeration is the
    owner-inspection read, which requests no eligibility, and ``get_many`` filters
    none — so episodes ADR-0275 §7 marks ineligible are in the window on the same
    terms as any other, which is the one read ADR-0276 §4 supersedes that rule for.
    No horizon on age is applied.

    **Episodes of the channel window are passed over rather than counted** (§3):
    they are returned where the walk reaches them, so the stage can render each once
    under its ``H`` label, and the walk continues until ``limit`` *other* episodes
    are held or the store has no more.
    """

    def __init__(self, *, memory: MemoryStore, limit: int) -> None:
        """Wire the selector to the store it reads and the bound it keeps.

        Args:
            memory: The store whose episodes the window is read from.
            limit: ``UNDERSTANDING_EPISODE_LIMIT``, a composition-root constant
                (ADR-0276 §4, ADR-0158 §5).

        Raises:
            ValueError: If ``limit`` is below 1.
        """
        if limit < 1:
            msg = "the episode window's bound must be at least 1 (ADR-0276 §4)"
            raise ValueError(msg)
        self._memory = memory
        self._limit = limit

    async def __call__(self, shared: frozenset[str]) -> tuple[EpisodicMemory, ...]:
        """The window's episodes, most recent first.

        Args:
            shared: The channel window's item identifiers, whose episodes are
                returned where reached and not counted toward the bound.

        Returns:
            At most ``limit`` episodes outside ``shared``, with every episode of
            ``shared`` the walk reached among them, in ``(occurred_at, episode_id)``
            descending order.
        """
        selected: list[EpisodicMemory] = []
        counted = 0
        cursor: str | None = None
        while counted < self._limit:
            size = min(_MAX_PAGE, self._limit - counted + len(shared))
            page = await self._memory.episodes(cursor=cursor, limit=size)
            addresses = [row.position.episode_id for row in page.items]
            # ADR-0286 §6:4: an open episode — the running activation's own among
            # them — is an id with no record here, so it takes no place in the window.
            found = without_open_episodes(await self._memory.get_many(addresses))
            for address in addresses:
                record = found.get(address)
                if not isinstance(record, EpisodicMemory):
                    # Expired or deleted between the two reads, or open: a gap, never an
                    # error, and never the end of the walk — a page whose every row
                    # vanished still hands on its cursor.
                    continue
                if address in shared:
                    selected.append(record)
                    continue
                if counted == self._limit:
                    break
                selected.append(record)
                counted += 1
            # Progress is the cursor's, not the page's: a store that hands back the
            # cursor it was given would otherwise be walked forever.
            if page.next_cursor is None or page.next_cursor == cursor:
                break
            cursor = page.next_cursor
        return tuple(selected)


@dataclass(frozen=True, slots=True)
class Windows:
    """The windows stage's decision: the two windows, the episodes held as ids (ADR-0282 §3).

    Attributes:
        channel: The channel window exactly as ADR-0276 §3 defines it for the pass. It
            is the channel's own material, held as it is, not a set of ids.
        episode_ids: The ids of the episode window's records, in the selector's order,
            after the audience predicate; ``None`` where the pass takes no episode
            window (ADR-0276 §4:13), and then the selector was not called.
        shared: The identifiers of the channel window's items: §3's *same exchange*
            ids, which the selector passes over rather
            than counts, and which recall searches past.
    """

    channel: ChannelWindow
    episode_ids: tuple[str, ...] | None
    shared: frozenset[str]


class WindowsStage:
    """Assemble the pass's two windows ahead of recall and understanding (ADR-0282 §3).

    It holds ADR-0276 §4's episode selector, which runs here unchanged, and makes only
    the selector's reads: it is a stage whose result is a choice of records (ADR-0282
    §2). What it writes are ids, after the audience predicate; the understanding phase
    fetches the records it renders.
    """

    def __init__(self, *, episodes: EpisodeSelector) -> None:
        """Wire the stage to the composition root's episode selector.

        Args:
            episodes: ADR-0276 §4's episode selector.
        """
        self._episodes = episodes

    async def assemble(
        self, channel: ChannelWindow, *, audience: TurnSupply, episodes: bool
    ) -> Windows:
        """The window decision for one pass.

        Args:
            channel: The pass's channel window.
            audience: The pass's audience posture, which filters both windows (§4:9).
            episodes: Whether the pass takes an episode window at all; with ``False``
                it takes none (ADR-0276 §4:13), and then no store is read.

        Returns:
            The windows, with the episode window as ids.
        """
        shared = frozenset(
            item.identifier for item in _channel_items(channel) if item.identifier is not None
        )
        if not episodes:
            return Windows(channel=channel, episode_ids=None, shared=shared)
        selected = admitted_to_understanding(audience, await self._episodes(shared))
        return Windows(
            channel=channel, episode_ids=tuple(record.id for record in selected), shared=shared
        )


@dataclass(frozen=True, slots=True)
class Fetched:
    """What the understanding phase fetched by id, and what came back (ADR-0282 §2, §5).

    Attributes:
        episodes: The episode window's admitted records, in the window's order;
            ``None`` where the pass takes no episode window.
        recalled: Recall's kept records that came back admitted, in recall's order.
        fetched: Every id the phase asked for, in order, each once.
        missing: The ids that returned no record of the kind held, or whose record
            the audience predicate refused on the second application.
    """

    episodes: tuple[EpisodicMemory, ...] | None
    recalled: tuple[EpisodicMemory | Memory, ...]
    fetched: tuple[str, ...]
    missing: tuple[str, ...]


async def fetch_held(
    memory: MemoryStore,
    *,
    episode_ids: tuple[str, ...] | None,
    recalled_ids: tuple[str, ...],
    audience: TurnSupply,
) -> Fetched:
    """Fetch the window's and recall's ids in one read, re-applying the audience predicate.

    One ``get_many`` returns each record's current version (ADR-0282 §5:1). An id with
    no record, a record no longer of the kind held — an episode for the window, an
    episode or memory for recall — and one the predicate now refuses are not
    errors: each is recorded as missing and left out, and the rest keep their order
    (§2, §5:2).

    Args:
        memory: The store the ids were chosen from.
        episode_ids: The episode window's ids, in its order; ``None`` where the pass
            takes no episode window.
        recalled_ids: Recall's kept ids, in its order.
        audience: The pass's audience posture.

    Returns:
        The records found and admitted, with what was asked for and what was missing.
    """
    ids = tuple(dict.fromkeys((*(episode_ids or ()), *recalled_ids)))
    # ADR-0286 §6:4: an open episode is an id with no record, recorded as missing.
    found = without_open_episodes(await memory.get_many(ids)) if ids else {}
    candidates = [
        record for id_ in ids if isinstance(record := found.get(id_), EpisodicMemory | Memory)
    ]
    admitted = {record.id: record for record in admitted_to_understanding(audience, candidates)}
    episodes = (
        None
        if episode_ids is None
        else tuple(
            record for id_ in episode_ids if isinstance(record := admitted.get(id_), EpisodicMemory)
        )
    )
    recalled = tuple(record for id_ in recalled_ids if (record := admitted.get(id_)) is not None)
    held = {record.id for record in (*(episodes or ()), *recalled)}
    return Fetched(
        episodes=episodes,
        recalled=recalled,
        fetched=ids,
        missing=tuple(id_ for id_ in ids if id_ not in held),
    )


# --- the rendered call -----------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Brief:
    """One call's rendered prompt and the label sequences it rendered.

    ``labels`` holds exactly the labels §3's scheme minted for this call — ``H`` then
    *n*, ``P`` then *n*, ADR-0281 §7's ``M`` then *n*, ADR-0300 §6:5's ``S`` then *n*,
    resolving to a ``story`` referent (ADR-0304 §8:1), and ADR-0349 §5:7's ``R`` then
    *n*, resolving to a ``running`` referent (ADR-0353 §10:1, §10:2), ASCII decimal with
    no padding — so an exact lookup is the whole of resolution: a string of another
    form, an *n* out of range and a label of a sequence this call did not render all
    miss it, and nothing is case-folded, trimmed or repaired.
    """

    messages: tuple[Message, Message]
    #: The system message's instruction and the flags it was rendered under, which each
    #: given entry for the call, and for its repair, records (ADR-0335 §9:1).
    instruction: RenderedPrompt
    labels: dict[str, UnderstandingReferent]
    channel_count: int
    episode_count: int
    #: How many ``M`` labels the recalled section rendered; ``None`` where the call
    #: rendered no recalled section at all (ADR-0281 §7).
    recalled_count: int | None = None
    #: What a story label resolves to (ADR-0300 §6:7): an ``S`` label its story, a
    #: ``P`` or ``M`` label naming an episode that episode's activation, an ``R`` label
    #: its running activation (ADR-0353 §10:3), and an ``H``
    #: label naming a place-window item that links to an activation that activation
    #: (ADR-0303 §7:4). An ``H`` label not here names an item that links to nothing,
    #: and an ``M`` label naming a recalled memory names a fact, which is never
    #: a story link: each is dropped and counted with no repair (§7:6, ADR-0305 §3). Any
    #: other label not here — an episode of no activation, or nothing rendered — is a
    #: story-label defect (ADR-0300 §6:8).
    story_members: dict[str, StoryMember] = field(default_factory=dict)
    #: How many ``S`` labels the stories section rendered; ``None`` where the call
    #: rendered no stories section at all (ADR-0300 §6:5).
    story_count: int | None = None
    #: What each ``R`` label the running section rendered names: the running activation,
    #: by its id (ADR-0349 §10:2). A ``meant_for`` label not here resolves to no shown
    #: activation, and is dropped and counted (ADR-0353 §9:11).
    running: dict[str, str] = field(default_factory=dict)
    #: How many ``M`` labels the person section rendered, which come first (ADR-0338
    #: §7:7); ``None`` where the call rendered no person section.
    person_count: int | None = None


class UnderstandingStage:
    """Produce one activation's understanding from its input and two windows (ADR-0276)."""

    def __init__(
        self,
        *,
        model: ModelProvider,
        excerpt_chars: int,
        prompt: PromptTemplate,
        diagnostics: DiagnosticSink | None = None,
    ) -> None:
        """Wire the stage to the model seam, the excerpt bound and its instruction.

        The stage reads no store: the episode window's records are handed to it, as
        the understanding phase fetched them (ADR-0282 §5).

        Args:
            model: The application's ordinary, already-wrapped route, carrying the
                provider stack's retry policy (ADR-0011). ``complete`` is called with
                no ``model=`` override, since ADR-0013 §4 rules that an explicit
                ``model=`` override disables routing.
            excerpt_chars: ``UNDERSTANDING_EXCERPT_CHARS``: the bound each episode's
                input and response are cut to, the cut disclosed (§4).
            prompt: The template of :data:`UNDERSTANDING_PROMPT`, default or override,
                as the composition root read it at start (ADR-0334 §3:4, §3:5). Every
                call renders its system message from it.
            diagnostics: The diagnostic record's write seam (ADR-0314 §4:4): each
                completion's rendered request before it, and its reply or its failure
                after; ``None`` where the record is off.

        Raises:
            ValueError: If ``excerpt_chars`` is below 1, or ``prompt`` is not a template
                of :data:`UNDERSTANDING_PROMPT`.
        """
        if excerpt_chars < 1:
            msg = "the episode excerpt bound must be at least 1 (ADR-0276 §4)"
            raise ValueError(msg)
        if prompt.declaration != UNDERSTANDING_PROMPT:
            msg = "the understanding stage renders the understanding prompt (ADR-0334 §2)"
            raise ValueError(msg)
        self._model = model
        self._excerpt_chars = excerpt_chars
        self._prompt = prompt
        self._diagnostics = diagnostics

    async def understand(  # noqa: PLR0913 — the input, its channel, its window, the audience, whether it takes episodes, the two facts orchestration mints, and what recall found
        self,
        text: str,
        *,
        channel: ChannelIdentity,
        window: ChannelWindow,
        audience: TurnSupply,
        episodes: tuple[EpisodicMemory, ...] | None,
        version: int,
        now: Callable[[], datetime],
        deadline: float,
        recall: ActivationRecall | None = None,
        recalled: tuple[EpisodicMemory | Memory, ...] = (),
        stories: Candidates | None = None,
        origin: InputOrigin | None = None,
        joined: Sequence[JoinedInput] = (),
        running: Sequence[InProgressEntry] | None = None,
        running_more: int = 0,
        person: PersonBlock | None = None,
    ) -> ActivationUnderstanding:
        """Read one input against its windows, and record what it was understood to mean.

        Args:
            text: The activation's input — the utterance, the transcript or the
                event's text — exactly as the pass holds it.
            channel: The channel it arrived on, from which its attribution is derived
                where ``origin`` is not given.
            window: The channel window (§3).
            audience: The pass's audience posture. Its predicate filters the stored
                records of both windows before anything is rendered (§4).
            episodes: The episode window's records, in the window's order, as the
                understanding phase fetched them (ADR-0282 §5); ``None`` where the
                pass takes no episode window (§4, ADR-0250 §15). The audience
                predicate is applied to them again here.
            version: The version orchestration mints for this record.
            now: The clock ``recorded_at`` is read from.
            deadline: The pass's deadline on the running loop's clock (§5). No
                completion is started once it has passed — the one repair included —
                however the time was spent.
            recall: Recall's decision for the pass (ADR-0281 §7). ``None`` where
                recall made no decision, and then the call renders no recalled
                section and the instruction says nothing of one.
            recalled: The records of recall's kept items the understanding phase
                fetched, in recall's order, rendered as a third section labelled
                ``M`` (ADR-0282 §5). A kept item that came back missing is not here.
            stories: The candidate stories the understanding phase assembled
                (ADR-0300 §6:1-§6:4), rendered as a fourth section labelled ``S``.
                ``None`` where the phase assembled none, and then the call renders no
                stories section and the instruction says nothing of one.
            origin: Who the input came from, as admission recorded it on the trigger
                (ADR-0284 §2:2). A kind that declares its origin per input (ADR-0323
                §4:11) is attributed by it; ``None`` reads the channel type's one
                declaration, which is the same value for every other kind.
            joined: The inputs the activation took in beside its trigger's, in the order
                it took them in (ADR-0349 §7:7, §7:21): read with the trigger's as the
                activation's whole input, each kept apart and dated, and marked as
                taken over from the work that held it.
            running: The in-progress section (ADR-0349 §5:2-§5:10): each activation
                running for the same person on any place, newest first, rendered
                labelled ``R``, which the reply may cite anywhere and whose
                ``meant_for`` names the work it is meant for (ADR-0353 §10). ``None``
                or empty renders no section, and then every ``R`` label resolves to
                nothing.
            running_more: How many more run than the section shows (§5:10).
            person: The activation's person block (ADR-0338 §7:1), of which the call
                renders the five fields and the pinned memories, first in the message
                and labelled ``M`` ahead of the recalled section (§7:2, §7:7). ``None``
                renders no section, and then the instruction says nothing of one.

        Returns:
            The recorded understanding.

        Raises:
            UnderstandingError: If the one repair's output still does not parse.
            ModelError: Propagated unchanged from the provider stack.
            TimeoutError: If ``deadline`` had passed when a completion was due.
        """
        brief = self._brief(
            text,
            channel=channel,
            window=window,
            audience=audience,
            episodes=episodes,
            recall=recall,
            recalled=recalled,
            stories=stories,
            origin=origin,
            joined=joined,
            running=running or (),
            running_more=running_more,
            person=person,
        )
        _within(deadline)
        first = await self._completed(brief.messages, brief.instruction)
        proposal, problem = self._validated(first.content, brief)
        if problem is not None:
            _within(deadline)
            _log.info("understanding_repair", stage="understanding", reason=problem.reason)
            second = await self._completed(
                (
                    *brief.messages,
                    Message(role=Role.ASSISTANT, content=first.content),
                    Message(role=Role.USER, content=problem.statement),
                ),
                brief.instruction,
            )
            proposal, problem = self._validated(second.content, brief)
            if proposal is None:
                _log.warning("understanding_failed", stage="understanding", reason="unparseable")
                msg = "the understanding stage's repaired output did not parse (ADR-0276 §6)"
                raise UnderstandingError(msg)
        assert proposal is not None  # noqa: S101 — a first output with no problem parsed
        return _resolved(
            proposal,
            brief.labels,
            brief.story_members,
            version=version,
            recorded_at=now(),
            running=brief.running,
        )

    async def _completed(self, messages: Sequence[Message], instruction: RenderedPrompt) -> Message:
        """One completion, its rendered request and its reply written to the record.

        The given entry is written before the call and the returned one once it returns
        or fails (ADR-0314 §4:1); the failure is re-raised unchanged. The given entry
        names the template the system message was rendered from and the flags it was
        rendered under (ADR-0334 §8:2, ADR-0335 §9:1), the repair's included, since it
        resends that message.
        """
        await write_diagnostic(
            self._diagnostics,
            DiagnosticSource.UNDERSTANDING,
            DiagnosticKind.GIVEN,
            lambda: {
                "messages": [one.model_dump(mode="json") for one in messages],
                "prompt": instruction.provenance(),
            },
        )
        try:
            reply = await self._model.complete(messages)
        except Exception as exc:
            await write_failure(self._diagnostics, DiagnosticSource.UNDERSTANDING, exc)
            raise
        await write_diagnostic(
            self._diagnostics,
            DiagnosticSource.UNDERSTANDING,
            DiagnosticKind.RETURNED,
            lambda: {"reply": reply.content},
        )
        return reply

    def _brief(  # noqa: PLR0913 — the input, its channel, its window, the audience, the window's episodes, what recall found and the candidate stories
        self,
        text: str,
        *,
        channel: ChannelIdentity,
        window: ChannelWindow,
        audience: TurnSupply,
        episodes: tuple[EpisodicMemory, ...] | None,
        recall: ActivationRecall | None,
        recalled: tuple[EpisodicMemory | Memory, ...],
        stories: Candidates | None,
        origin: InputOrigin | None = None,
        joined: Sequence[JoinedInput] = (),
        running: Sequence[InProgressEntry] = (),
        running_more: int = 0,
        person: PersonBlock | None = None,
    ) -> _Brief:
        """Render the prompt, filtering the episode window's stored records first (§3, §4).

        No question is marked (ADR-0353 §11:1). The inputs a merge brought render with
        the input, and the in-progress section as a section of its own, each entry under
        its ``R`` label (ADR-0349 §5), which resolves in the one label table (ADR-0353
        §10:2) and as an activation member (§10:3). The person
        section comes first, before everything that changes from input to input, and its
        pinned memories take the first ``M`` labels (ADR-0338 §7:7, #3084).
        """
        placed = _Placed.of(window, audience, episodes)
        shared = placed.shared
        window_episodes = placed.episodes
        labels: dict[str, UnderstandingReferent] = {}
        story_members: dict[str, StoryMember] = {}
        rendered_items: list[dict[str, object]] = []
        for index, one in enumerate(placed.items, start=1):
            label = f"H{index}"
            rendered_items.append(
                one.item.rendering(
                    label,
                    one.also,
                    excerpt_chars=self._excerpt_chars,
                    linkable=one.link is not None,
                    annotated=one.annotated,
                )
            )
            labels[label] = one.item.referent
            # ADR-0303 §7:4: an item that links to an activation is a story label for
            # it, as a P label naming that activation's episode is: a one-exchange
            # item by its stored episode (ADR-0301 §1:1), a transcript message by the
            # reader's bookkeeping. Anything withheld has no label.
            if one.link is not None:
                story_members[label] = StoryMember(kind=StoryMemberKind.ACTIVATION, id=one.link)
        rendered_episodes: list[dict[str, object]] = []
        for record in (record for record in window_episodes if record.id not in shared):
            label = f"P{len(rendered_episodes) + 1}"
            # ADR-0284 §8:5: the episode window is one of the two renderings that
            # admit an outside input's text.
            projected = _ProjectedEpisode.of(
                record, excerpt_chars=self._excerpt_chars, admit_outside_input=True
            )
            rendered_episodes.append(projected.rendering(label))
            labels[label] = projected.referent()
            _member_of(record, label, story_members)
        received = _input_rendering(text, channel, origin)
        if isinstance(window, TranscriptWindow) and window.input_messages:
            received["messages"] = [_input_message(one, window) for one in window.input_messages]
        if joined:
            # ADR-0332 §3:10: the activation's whole input, each joined one kept apart.
            received["joined"] = [_joined_rendering(one) for one in joined]
        payload: dict[str, object] = {}
        person_count: int | None = None
        if person is not None:
            payload["person"], person_count = _person_section(person, labels)
        payload |= {
            "input": received,
            "channel_window": rendered_items
            or "missing: no recent context accompanies this input on its channel",
            "episode_window": (
                rendered_episodes or "missing: there are no other recent episodes to show"
            )
            if episodes is not None
            else "not provided for input on this channel",
        }
        recalled_count: int | None = None
        if recall is not None:
            # ADR-0281 §7: a record either window already rendered stays there only.
            # ADR-0338 §7:7: and one the person section shows is there only.
            rendered = shared | {record.id for record in window_episodes} | _pinned_ids(person)
            section, recalled_count = self._recalled_section(
                recall.outcome,
                recalled,
                rendered,
                labels,
                story_members,
                first=1 + (person_count or 0),
                above=_ALREADY_SHOWN if person is None else _ALREADY_SHOWN_ABOVE,
            )
            payload["recalled"] = section
        story_count: int | None = None
        if stories is not None:
            payload["stories"], story_count = self._stories_section(stories, labels, story_members)
        shown_running: dict[str, str] = {}
        # ADR-0349 §5:2, §5:7, §5:10: beside the windows, each under its R label, newest
        # first, and how many more run than it shows; ADR-0353 §10:1-§10:3: each R label
        # in the one table, and as an activation member.
        payload |= _in_progress_section(
            running, running_more, shown_running, labels=labels, story_members=story_members
        )
        instruction = self._prompt.rendered(
            flags={
                "recalled": recall is not None,
                "stories": stories is not None,
                "person": person is not None,
            }
        )
        messages = (
            Message(role=Role.SYSTEM, content=instruction.text),
            Message(role=Role.USER, content=json.dumps(payload, ensure_ascii=True)),
        )
        return _Brief(
            messages,
            instruction,
            labels,
            len(rendered_items),
            len(rendered_episodes),
            recalled_count,
            story_members,
            story_count,
            shown_running,
            person_count=person_count,
        )

    def _stories_section(
        self,
        stories: Candidates,
        labels: dict[str, UnderstandingReferent],
        story_members: dict[str, StoryMember],
    ) -> tuple[list[dict[str, object]] | str, int]:
        """ADR-0300 §6:5's fourth section, labelled ``S`` in the candidates' order.

        Each ``S`` label resolves twice: in ``belongs_to`` to its story member (§6:7),
        and in ``cites`` to a ``story`` referent (ADR-0304 §8:1). The latest episodes
        take no label of their own (§6:5).
        """
        if stories.unreadable:
            return _STORIES_UNREADABLE, 0
        section: list[dict[str, object]] = []
        for view in stories.views:
            label = f"S{len(section) + 1}"
            section.append(self._short_view(label, view))
            labels[label] = _story_referent(view)
            story_members[label] = StoryMember(kind=StoryMemberKind.STORY, id=view.story_id)
        if section:
            return section, len(section)
        return _NO_STORIES, 0

    def _short_view(self, label: str, view: ShortView) -> dict[str, object]:
        """One candidate under its label: summary lines, newest notes, latest episodes (§6:2).

        The summary and each note are attributed by their records — the summary as the
        tidy-up's and marked or not, a note by who wrote it and whether it is marked —
        and never by their text (ADR-0303 §3:7). A withheld summary is said to be withheld,
        and nothing of it is rendered (ADR-0304 §4:2). On a pass that may not be shown a
        note, the notes part is not rendered at all: it says neither that none is waiting
        nor that any was withheld (ADR-0305 §4). The episodes take no label
        (§6:5), and render through the projection with an outside input's text not
        admitted: ADR-0284 §8:5 admits it in the episode window and the recalled
        section alone.
        """
        episodes = [
            _ProjectedEpisode.of(
                record, excerpt_chars=self._excerpt_chars, admit_outside_input=False
            ).described()
            for record in view.episodes
        ]
        rendered: dict[str, object] = {
            "label": label,
            "item": _STORY_ITEM,
            "summary": (
                _SUMMARY_WITHHELD
                if view.withheld
                else [_summary_line(line) for line in _shown_lines(view)] or _NO_LINES
            ),
        }
        if view.outside:
            rendered["summary_outside_content"] = _SUMMARY_OUTSIDE_TEXT
        if not view.notes_withheld:
            rendered["newest_notes"] = [_story_note(note) for note in view.notes] or _NO_NOTES
        rendered["latest_episodes"] = episodes or _NO_EPISODES
        return rendered

    def _recalled_section(  # noqa: PLR0913 — the outcome, its records, what is shown, the two label maps it mints into, where its labels start and what it says when all is shown
        self,
        outcome: RecallOutcome,
        recalled: tuple[EpisodicMemory | Memory, ...],
        rendered: frozenset[str],
        labels: dict[str, UnderstandingReferent],
        story_members: dict[str, StoryMember],
        *,
        first: int = 1,
        above: str = _ALREADY_SHOWN,
    ) -> tuple[list[dict[str, object]] | str, int]:
        """ADR-0281 §7's third section, labelled ``M`` in recall's order, and its count.

        Its labels start at ``first``: after the person section's, where one rendered
        (ADR-0338 §7:7).
        """
        if outcome in {RecallOutcome.FAILED, RecallOutcome.TIMED_OUT}:
            return _RECALL_FAILED, 0
        if outcome is RecallOutcome.NOTHING_FOUND:
            return _NOTHING_RECALLED, 0
        section: list[dict[str, object]] = []
        for record in (record for record in recalled if record.id not in rendered):
            label = f"M{len(section) + first}"
            if isinstance(record, EpisodicMemory):
                # ADR-0284 §8:5: recalled episodes are the other rendering that admits
                # an outside input's text.
                projected = _ProjectedEpisode.of(
                    record, excerpt_chars=self._excerpt_chars, admit_outside_input=True
                )
                section.append(projected.rendering(label))
                labels[label] = projected.referent()
                _member_of(record, label, story_members)
            else:
                memory = _RecalledFact.of(record, excerpt_chars=self._excerpt_chars)
                section.append(memory.rendering(label))
                labels[label] = memory.referent()
        if section:
            return section, len(section)
        # Recall kept records, and none renders: either every one is already shown
        # above, or the fetch found none of them held any more (ADR-0282 §5:2).
        return (above if recalled else _NO_LONGER_HELD), 0

    def _validated(
        self, content: str, brief: _Brief
    ) -> tuple[ProposedActivationUnderstanding | None, _Problem | None]:
        """ADR-0353 §9:10's two checks, in order, and the code-owned statement of what failed.

        The parse, then the labels of ``cites`` and ``belongs_to`` that are not of the
        ``R`` form. A label in ``meant_for`` naming no shown activation, an ``R`` label in
        ``cites`` or ``belongs_to`` naming no shown entry (§9:11), and a label in
        ``belongs_to`` naming a remembered fact or a place-window item that links to no
        activation (§9:12), call for no repair: :func:`_resolved` drops and counts each.
        """
        proposal, dropped = _read(content)
        if proposal is None:
            return None, _Problem("unparseable", _UNPARSEABLE)
        if dropped:
            # ADR-0339 §4: the number of unnamed keys the drop removed, and nothing of them.
            _log.info(
                "understanding_stray_keys",
                stage="understanding",
                reason=_UNNAMED_DROPPED,
                stray=dropped,
            )
        unresolved = [
            label
            for label in proposal.cites
            if label not in brief.labels and not _R_FORM.fullmatch(label)
        ]
        # ADR-0300 §6:8: a label in `belongs_to` naming nothing a link can be made to is a
        # label defect, and takes part in the one repair completion — except an R label
        # (ADR-0353 §9:11), and one naming a place-window item that links to no activation
        # or a remembered fact (§9:12), each dropped and counted with no repair.
        unlinkable = [
            label
            for label in proposal.belongs_to
            if label not in brief.story_members
            and not _R_FORM.fullmatch(label)
            and not _never_linked(label, brief)
        ]
        if not unresolved and not unlinkable:
            return proposal, None
        return proposal, _Problem("labels", _label_statement(unresolved, brief, unlinkable))


@dataclass(frozen=True, slots=True)
class _Problem:
    """What was wrong with an output, as a code-owned reason and statement."""

    reason: str
    statement: str


# --- the channel window ------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _PlacedItem:
    """One item of the place window, what it shares with the episode window, its link.

    ``annotated`` is whether this item carries what the episode window would have added
    about ``also`` — its status and understanding. Several transcript messages
    can be one exchange — the user's message an activation took in and the reply it
    wrote — and that exchange is rendered once (ADR-0276 §3): the first of them in
    rendering order carries its annotations, and every one of them is marked as also in
    the episode window.
    """

    item: _ChannelItem
    also: EpisodicMemory | None
    link: str | None
    annotated: bool = True


@dataclass(frozen=True, slots=True)
class _Placed:
    """The place window's items as one pass renders them, each with its link (ADR-0303 §7).

    One reading, shared by the rendering and by the candidates' assembly, so the
    activations the candidates are read for are exactly those the labels resolve to.

    Attributes:
        items: The items in rendering order.
        shared: The identifiers of the items, ADR-0276 §3's *same exchange* ids.
        episodes: The episode window's records the audience admits, in its order.
    """

    items: tuple[_PlacedItem, ...]
    shared: frozenset[str]
    episodes: tuple[EpisodicMemory, ...]

    @classmethod
    def of(
        cls,
        window: ChannelWindow,
        audience: TurnSupply,
        episodes: Sequence[EpisodicMemory] | None,
    ) -> _Placed:
        """Read the window's items and resolve each one's link off the records held."""
        items = _channel_items(window)
        shared = frozenset(item.identifier for item in items if item.identifier is not None)
        admitted: tuple[EpisodicMemory, ...] = ()
        if episodes is not None:
            admitted = admitted_to_understanding(audience, episodes)
        merged = {record.id: record for record in admitted if record.id in shared}
        placed: list[_PlacedItem] = []
        annotated: set[str] = set()
        for item in items:
            also = None if item.identifier is None else merged.get(item.identifier)
            first = also is not None and also.id not in annotated
            if also is not None:
                annotated.add(also.id)
            placed.append(_PlacedItem(item, also, item.linked(also), annotated=first))
        return cls(items=tuple(placed), shared=shared, episodes=admitted)


def place_window_links(
    window: ChannelWindow,
    *,
    audience: TurnSupply,
    episodes: Sequence[EpisodicMemory] | None,
) -> tuple[str, ...]:
    """The activations the place window's items link to, newest item first, each once.

    ADR-0303 §7:9's first source of candidates, read off exactly the items and links
    the stage renders: the window filtered for the pass's audience, so a withheld
    record brings no story, and each item's link as the stage resolves it. A
    transcript's newest message is the one latest in its conversation; a stored
    episode's item is ordered by when its episode occurred, which is the only time a
    supplied item carries. An activation linked by several items takes the place of
    its newest.

    Args:
        window: The pass's place window, as the windows stage holds it.
        audience: The pass's audience posture.
        episodes: The episode window's records as the understanding phase fetched
            them, which a one-exchange supplied item links through; ``None`` where the
            pass takes no episode window.

    Returns:
        The activation ids, newest item first.
    """
    placed = _Placed.of(window, audience, episodes)
    linked = [one for one in placed.items if one.link is not None]
    linked.sort(key=_newness, reverse=True)
    return tuple(dict.fromkeys(one.link for one in linked if one.link is not None))


def _newness(one: _PlacedItem) -> tuple[int, datetime, str]:
    """How new an item is: its position in a transcript, else its stored episode's time.

    One window holds one kind of item, so only one part of the key ever differs.
    """
    stored = one.also
    if stored is None:
        return (one.item.position or 0, _NO_TIME, "")
    return (one.item.position or 0, stored.occurred_at, stored.id)


@dataclass(frozen=True, slots=True)
class _ChannelItem:
    """One item of the channel window, with the referent its label resolves to.

    ``body`` is what the item renders.

    ``link`` is the activation the item links to by its own record (ADR-0303 §7:1): a
    transcript message's, as the reader's bookkeeping records it. A supplied item has
    none of its own, and links only where it is one exchange with an episode of the
    episode window (§1:1).
    ``position`` is a transcript message's place in its conversation, the medium's
    own item id (ADR-0303 §7:2), and what orders the window newest first.
    """

    identifier: str | None
    body: dict[str, object]
    referent: UnderstandingReferent
    link: str | None = None
    position: int | None = None

    def rendering(
        self,
        label: str,
        also: EpisodicMemory | None,
        *,
        excerpt_chars: int,
        linkable: bool,
        annotated: bool = True,
    ) -> dict[str, object]:
        """The item under its label, marked where it is also in the episode window.

        An item that links to no activation is marked not linkable (ADR-0303 §7:5): a
        label in ``belongs_to`` naming it links nothing. No message carries a question
        mark (ADR-0353 §11:1).

        ``also`` is the episode-window record the item names, where it names one: its
        status, reason and understanding ride here, rendered once (§3). A supplied
        item or a transcript message is not a record and keeps its own text, gaining
        only those annotations, and only where ``annotated``: of several items that are
        one exchange, the first carries them and the rest are only marked, so the
        exchange is rendered once.

        **A stored understanding version rides only on an item also in the episode
        window** — what that window would have added about it.
        """
        rendered: dict[str, object] = {"label": label, **self.body}
        if also is not None and annotated:
            projected = _ProjectedEpisode.of(
                also, excerpt_chars=excerpt_chars, admit_outside_input=False
            )
            rendered.update(projected.annotations())
        if also is not None:
            # §3: one exchange, rendered once, here; what the episode window would have
            # added about it — its status and what was understood then — rides here too.
            rendered["also_in_episode_window"] = True
        if not linkable:
            rendered["not_linkable"] = True
        return rendered

    def linked(self, also: EpisodicMemory | None) -> str | None:
        """The activation the item links to, where it links to one (ADR-0303 §7:1, §7:3).

        Its own record's, or, for a supplied item that is one exchange with an episode
        of the episode window, that episode's (ADR-0301 §1:1). Read off the records the
        pass already holds: nothing is fetched (ADR-0301 §1:4).
        """
        if self.link is not None:
            return self.link
        return None if also is None else activation_of(also)


def _channel_items(window: ChannelWindow) -> list[_ChannelItem]:
    """The channel window's items in supplied order (§3)."""
    if isinstance(window, SuppliedWindow):
        supplied = [(item, "a recent item the channel supplied") for item in window.context.history]
        if window.context.reply_to is not None:
            supplied.append((window.context.reply_to, "the item this input replies to"))
        return [_supplied_item(item, role) for item, role in supplied]
    return _transcript_items(window)


def _supplied_item(item: ChannelContextItem, role: str) -> _ChannelItem:
    """A supplied item is not a record: it passes as supplied, quoted (§4)."""
    body: dict[str, object] = {"item": role, "source_label": item.source, "text": item.text}
    return _ChannelItem(
        identifier=item.item_id,
        body=body,
        referent=UnderstandingReferent(
            kind="channel_item",
            id=item.item_id,
            source=item.source,
            excerpt=_excerpt(item.text or ""),
        ),
    )


_TRANSCRIPT_ITEM: Final = "a recent message of this conversation"
_REPLIED_TO_ITEM: Final = "an earlier message the input replies to"

#: Who wrote a message, as the window renders it: the medium's own record of its
#: author, never a reading of its text (ADR-0293 §6:5, ADR-0276 §3:6).
_AUTHOR_TEXT: Final = {
    MessageAuthor.USER: "the user",
    MessageAuthor.ASSISTANT: "the assistant",
}

#: Who wrote a forward, as the window renders it: its original sender, never the user
#: who forwarded it (ADR-0323 §4:10).
_FORWARDED_TEXT: Final = "a forward from someone else, its sender claimed"

#: Who wrote a message the place's kind does not establish an author for, as the window
#: renders it: claimed, and never the user (ADR-0323 §4:2).
_CLAIMED_TEXT: Final = "an author this place does not establish, claimed"


def _transcript_items(window: TranscriptWindow) -> list[_ChannelItem]:
    """The chat's window, its recent messages then those the input replies to (§6:4).

    Each item keeps its author and its position, and an item written after the
    earliest message of the input says so, so the activation can tell that a message
    was written before the reply it follows (ADR-0293 §6).
    """
    first = min((one.position for one in window.input_messages), default=None)
    items = [_message_item(one, window, _TRANSCRIPT_ITEM, first) for one in window.messages]
    items.extend(_message_item(one, window, _REPLIED_TO_ITEM, first) for one in window.replied_to)
    return items


def _forward_of(author: ClaimedAuthor) -> dict[str, object]:
    """A forward's original sender, as the window renders it: claimed (ADR-0323 §4:10)."""
    rendered: dict[str, object] = {"name": author.name, "author": "claimed"}
    if author.account_id is not None:
        rendered["account_id"] = author.account_id
    return rendered


def _input_message(
    message: TranscriptMessage | LineMessage, window: TranscriptWindow
) -> dict[str, object]:
    """One message of the input as the medium holds it: where it is, what it answers.

    Its ``replies_to`` is the position of the window item, or of another message of
    the input, it replies to (ADR-0293 §4:5), so a correction is tied to the message
    it corrects rather than left to its words. A forward names its original sender,
    claimed, and is not the user's words (ADR-0323 §4:10).
    """
    rendered: dict[str, object] = {
        "position": message.position,
        "written_at": message.written_at.isoformat(),
        "text": message.text,
    }
    if message.replies_to is not None:
        rendered["replies_to"] = message.replies_to
    if (forward := window.forwarded.get(message.position)) is not None:
        rendered["forwarded_from"] = _forward_of(forward)
    return rendered


def _message_item(
    message: TranscriptMessage | LineMessage | DeletedMessage,
    window: TranscriptWindow,
    role: str,
    first: int | None,
) -> _ChannelItem:
    """One message of the transcript, quoted as the medium holds it (ADR-0293 §5:2).

    It links to the activation the reader's bookkeeping records as having taken it in,
    or the phases' effect record as having written it, where one is recorded (ADR-0303
    §7:1, §7:3). Where it links, its identifier is that activation's episode's stored
    id, ``activation:<activation_id>`` (ADR-0283 §2), so ADR-0276 §3's *same exchange*
    matches it as written: the episode window's record of the exchange the message
    belongs to is rendered with it, under its ``H`` label, and takes no ``P`` label
    (#2899). A message that links to nothing has no identifier, and §3 does not apply
    to it (ADR-0303 §7:5's conservative direction). Its referent stays the message,
    by its position: a label citing it names the message, not the episode.
    """
    conversation = window.conversation
    body: dict[str, object] = {"item": role, "position": message.position}
    excerpt = ""
    link = window.links.get(message.position)
    if isinstance(message, DeletedMessage):
        body["deleted"] = True
    else:
        forward = window.forwarded.get(message.position)
        if forward is not None:
            body["author"] = _FORWARDED_TEXT
            body["forwarded_from"] = _forward_of(forward)
        elif message.position in window.claimed:
            body["author"] = _CLAIMED_TEXT
        else:
            body["author"] = _AUTHOR_TEXT[message.author]
        body["written_at"] = message.written_at.isoformat()
        body["text"] = message.text
        excerpt = _excerpt(message.text)
        if message.replies_to is not None:
            body["replies_to"] = message.replies_to
        if message.cut_off:
            body["cut_off"] = True
    if first is not None and message.position > first:
        body["written_after_the_input_began"] = True
    return _ChannelItem(
        identifier=None if link is None else episode_address(link),
        body=body,
        referent=UnderstandingReferent(
            kind="channel_item",
            id=f"message:{message.position}",
            source=_channel_text(conversation),
            excerpt=excerpt,
        ),
        link=link,
        position=message.position,
    )


# --- the episode window ------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _ProjectedEpisode:
    """One episode as ADR-0284 §8's projection shows it — never a serialization of it.

    Every field rendered is a field of the projection, and no other field of the
    stored episode is read (§8:3). Who the input came from is the projection's
    ``origin``, never the episode's channel type (§2:3, superseding ADR-0276 §4:8's
    test): an episode whose input came from outside is rendered as a report received.
    """

    episode_id: str
    projection: EpisodeProjection

    @classmethod
    def of(
        cls, record: EpisodicMemory, *, excerpt_chars: int, admit_outside_input: bool
    ) -> _ProjectedEpisode:
        """Project the episode through ``core``'s one projection (§8:1)."""
        projection = project_episode(
            record, excerpt_chars=excerpt_chars, admit_outside_input=admit_outside_input
        )
        return cls(episode_id=record.id, projection=projection)

    @property
    def source(self) -> str:
        """Where the episode arrived: its channel, or its capture modality (§8:1)."""
        projection = self.projection
        if projection.channel is not None:
            return _channel_text(projection.channel)
        if projection.capture_modality is not None:
            return f"capture modality {projection.capture_modality.value}"
        return "a channel the record does not name"

    def rendering(self, label: str) -> dict[str, object]:
        """The episode under its label, attributed from its origin (§4, ADR-0284 §2:3)."""
        return {"label": label, **self.described()}

    def described(self) -> dict[str, object]:
        """The episode with no label, attributed from its origin, as a short view shows it."""
        origin = self.projection.origin
        return {
            "item": (
                f"a report received on {self.source}, never something the user said"
                if origin is InputOrigin.OUTSIDE
                else f"earlier work the assistant scheduled, run on {self.source}; its "
                "input was the assistant's own instruction, never something the user said"
                if origin is InputOrigin.ASSISTANT
                else f"an earlier exchange on {self.source}"
            ),
            **self.parts(),
        }

    def parts(self) -> dict[str, object]:
        """Its time, input, response, status and reason, and understanding.

        ADR-0284 §8:6 as ADR-0318 §3:1 leaves it: a rendering states the episode's
        status and reason, and no verdict. The latest understanding version is shown:
        the episode window and the recalled section show it (ADR-0276 §4, ADR-0281 §7),
        and a channel-window item shows it only where it is also in the episode window,
        through :meth:`annotations`. No question it asked is marked (ADR-0353 §11:1).
        """
        projection = self.projection
        rendered: dict[str, object] = {
            "occurred_at": projection.occurred_at.isoformat(),
            "input": None if projection.input is None else projection.input.text,
            "input_cut_to_first_chars": projection.input is not None and projection.input.cut,
            "response": None if projection.response is None else projection.response.text,
            "response_cut_to_first_chars": (
                projection.response is not None and projection.response.cut
            ),
        }
        return rendered | self.annotations()

    def annotations(self) -> dict[str, object]:
        """Its status and reason and, where it has one, its understanding.

        What a channel-window item gains where it names an episode the episode window
        holds (§3), and the part of :meth:`parts` that is about processing.
        """
        projection = self.projection
        rendered: dict[str, object] = {}
        if projection.status is not None and projection.reason is not None:
            rendered["status"] = projection.status.value
            rendered["reason"] = projection.reason.value
        if projection.meaning is not None:
            # ADR-0353 §12: no ground is recorded, and its unclear points are U2's to
            # render (§16:2), so what was understood then is its meaning alone.
            rendered["understood_then"] = {
                "provisional": "what the assistant understood then, not an established fact",
                "meaning": projection.meaning,
            }
        return rendered

    def excerpt(self) -> str:
        """ADR-0276 §2's referent excerpt: the input shown, else what was understood."""
        projection = self.projection
        if projection.input is not None:
            return _excerpt(projection.input.text)
        return _excerpt(projection.meaning or "")

    def referent(self) -> UnderstandingReferent:
        """The episode's stored id **exactly as stored**, and the rendering of its channel."""
        return UnderstandingReferent(
            kind="episode", id=self.episode_id, source=self.source, excerpt=self.excerpt()
        )


# --- the recalled section ------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _RecalledFact:
    """ADR-0281 §7's projection of one recalled memory."""

    record: Memory
    fact: str
    cut: bool

    @classmethod
    def of(cls, record: Memory, *, excerpt_chars: int) -> _RecalledFact:
        """Its wording, cut to the episode excerpt bound with the cut disclosed."""
        fact, cut = _cut(record.content, excerpt_chars)
        return cls(record=record, fact=fact or "", cut=cut)

    def rendering(self, label: str) -> dict[str, object]:
        """The fact under its ``M`` label, attributed by its band and never by its text.

        It is marked not linkable on every pass, on the place window's key, whether or
        not a stories section renders beside it: a remembered fact is never a story
        link (ADR-0305 §3).
        """
        return {
            "label": label,
            "item": _BAND_ATTRIBUTION[self.record.band],
            "last_updated": self.record.transaction_time.isoformat(),
            "fact": self.fact,
            "fact_cut_to_first_chars": self.cut,
            "not_linkable": True,
        }

    def referent(self) -> UnderstandingReferent:
        """The record's stored id **exactly as stored**, as a ``memory`` referent."""
        return UnderstandingReferent(
            kind="memory", id=self.record.id, source="memory", excerpt=_excerpt(self.fact)
        )


# --- the person section (ADR-0338 §7:2, §7:6-§7:7) --------------------------------


def _pinned_ids(person: PersonBlock | None) -> frozenset[str]:
    """The ids of the memories the person section shows, none where it renders none."""
    return frozenset() if person is None else frozenset(one.id for one in person.pinned)


def _person_section(
    person: PersonBlock, labels: dict[str, UnderstandingReferent]
) -> tuple[dict[str, object], int]:
    """The person's five fields and pinned memories, the memories under the first ``M`` labels.

    Data, rendered as the person's own choices and never as an instruction (§7:6): each
    field with what it is, a field not set said to be not set (§3:9), and each pinned
    memory by its wording whole, which the slot's budget already bounds, attributed by
    its band and marked not linkable as every remembered fact is (ADR-0305 §3). Nothing
    else of the block: understanding is not shown the style memories or the suggestions
    (§7:2).
    """
    profile: dict[str, object] = {}
    for field_ in ProfileField:
        value = person.profile.value(field_)
        if value is None:
            value = _ASSISTANT_NAME_NOT_SET if field_ is ProfileField.ASSISTANT_NAME else _NOT_SET
        profile[field_.value] = {"is": _FIELD_TEXT[field_], "value": value}
    kept: list[dict[str, object]] = []
    for memory in person.pinned:
        label = f"M{len(kept) + 1}"
        kept.append(
            {
                "label": label,
                "item": _PINNED_ITEM,
                "remembered_as": _BAND_ATTRIBUTION[memory.band],
                "last_updated": memory.transaction_time.isoformat(),
                "fact": memory.content,
                "not_linkable": True,
            }
        )
        labels[label] = UnderstandingReferent(
            kind="memory", id=memory.id, source="memory", excerpt=_excerpt(memory.content)
        )
    section: dict[str, object] = {
        "item": _PERSON_ITEM,
        "profile": profile,
        "kept_in_mind": kept or _NOTHING_PINNED,
    }
    return section, len(kept)


# --- validation and resolution ---------------------------------------------------


def _parsed(content: str) -> ProposedActivationUnderstanding | None:
    """One ``ProposedActivationUnderstanding``, or ``None`` — never a partial one.

    The stage's reader, which ADR-0337's regression suite reads understanding replies
    with, so the suite reads a reply as the stage does: :func:`_read`'s proposal,
    without its count, which reaches the stage by :func:`_read` alone.
    """
    return _read(content)[0]


def _read(content: str) -> tuple[ProposedActivationUnderstanding | None, int]:
    """The reply's proposal, or ``None``, and how many unnamed keys were dropped from it.

    One enclosing Markdown code fence is removed first: a deterministic, code-owned
    normalization of a wrapper, not a repair of the object inside it. Then every key the
    reply shape does not name is removed from the text, with its value, at every
    position the shape expects one of its models, the top level and each element of
    ``unclear`` (ADR-0339 §2, ADR-0353 §9:14), and what remains is parsed. The types
    keep their own ``extra="forbid"`` (§3:1), so what remains is parsed exactly as
    before, and a reply the walk cannot read is parsed as it stands.

    The count is ``0`` where nothing was dropped or nothing parsed.
    """
    body = content.strip()
    if body.startswith("```") and body.endswith("```") and len(body) >= 6:  # noqa: PLR2004 — two fences
        body = body[3:-3]
        newline = body.find("\n")
        if newline != -1 and body[:newline].strip() in {"", "json", "JSON"}:
            body = body[newline + 1 :]
    pruned = _pruned_reply(body)
    text, dropped = (body, 0) if pruned is None else pruned
    try:
        # ADR-0353 §9:2: the reply's six keys, ``meant_for`` a list of R labels.
        reply = ProposedActivationUnderstanding.model_validate_json(text)
    except ValidationError, ValueError, RecursionError:
        return None, 0
    return reply, dropped


# --- the drop (ADR-0339 §2) ------------------------------------------------------------
#
# The walk reads the reply's text lexically, never decoding a value it does not keep: a
# dropped key's value is skipped by its string quotes and its matched brackets alone, so
# no content, size or depth of it can refuse the reply (§2:4, §2:5). Its own recursion
# follows the shape, never the reply. Where the text is not one object whose members it
# can delimit, it returns ``None``, nothing is dropped, and the parse judges the reply
# as it stands.

_STRING: Final = re.compile(r'"[^"\\]*(?:\\.[^"\\]*)*"', re.DOTALL)
_SCALAR: Final = re.compile(r"[^,\]} \t\n\r\[{\"]+")
_SPACE: Final = re.compile(r"[ \t\n\r]*")
_STRUCTURAL: Final = re.compile(r'["\[\]{}]')
_CLOSING: Final = {"[": "]", "{": "}"}


@dataclass(frozen=True, slots=True)
class _Sequence:
    """A field the shape holds a sequence of one model in."""

    model: type[BaseModel]


#: What a field expects: one of the shape's models, a sequence of one, or neither.
type _Expected = type[BaseModel] | _Sequence | None


@dataclass(frozen=True, slots=True)
class _Member:
    """One member of an object, as the text writes it: its key and where its value is."""

    written: str
    key: str
    start: int
    end: int


def _pruned_reply(body: str) -> tuple[str, int] | None:
    """``body`` with every unnamed key removed, and how many, or ``None`` to drop nothing.

    The drop applies to every reply: no key exempts one, ``answers`` included (ADR-0353
    §9:14, superseding ADR-0339 §2:2). ``None`` only where the text is not one object
    whose members the walk can delimit.
    """
    at = _skip_space(body, 0)
    read = _members(body, at)
    if read is None:
        return None
    members, end = read
    if _skip_space(body, end) != len(body):
        return None
    return _kept(body, members, ProposedActivationUnderstanding)


def _kept(text: str, members: Sequence[_Member], shape: type[BaseModel]) -> tuple[str, int] | None:
    """The object ``members`` make, read as ``shape``: its named members, and the count dropped."""
    expected = _expected_fields(shape)
    kept: list[str] = []
    dropped = 0
    for one in members:
        if one.key not in expected:
            dropped += 1
            continue
        value = _kept_value(text, one.start, one.end, expected[one.key])
        if value is None:
            return None
        kept.append(f"{one.written}:{value[0]}")
        dropped += value[1]
    return "{" + ",".join(kept) + "}", dropped


def _kept_value(text: str, start: int, end: int, expected: _Expected) -> tuple[str, int] | None:
    """The value at ``start:end`` with the drop applied where ``expected`` names a model.

    A value that is not the object or the array the field expects is kept as written,
    for the parse to judge (§2:4).
    """
    if isinstance(expected, type) and text.startswith("{", start):
        read = _members(text, start)
        return None if read is None else _kept(text, read[0], expected)
    if isinstance(expected, _Sequence) and text.startswith("[", start):
        return _kept_elements(text, start, expected.model)
    return text[start:end], 0


def _kept_elements(text: str, at: int, model: type[BaseModel]) -> tuple[str, int] | None:
    """The array at ``at``, each object element read as ``model``, any other kept as written."""
    elements: list[str] = []
    dropped = 0
    position = _skip_space(text, at + 1)
    if text.startswith("]", position):
        return "[]", 0
    while True:
        end = _value_end(text, position)
        if end is None:
            return None
        if text.startswith("{", position):
            read = _members(text, position)
            if read is None:
                return None
            element = _kept(text, read[0], model)
            if element is None:
                return None
            elements.append(element[0])
            dropped += element[1]
        else:
            elements.append(text[position:end])
        position = _skip_space(text, end)
        if text.startswith(",", position):
            position = _skip_space(text, position + 1)
            continue
        if text.startswith("]", position):
            return "[" + ",".join(elements) + "]", dropped
        return None


def _members(text: str, at: int) -> tuple[list[_Member], int] | None:
    """The members of the object opening at ``at``, in order, and where it ends.

    ``None`` where no object opens at ``at``, or its members cannot be delimited.
    """
    if not text.startswith("{", at):
        return None
    members: list[_Member] = []
    position = _skip_space(text, at + 1)
    if text.startswith("}", position):
        return members, position + 1
    while (member := _member(text, position)) is not None:
        members.append(member)
        position = _skip_space(text, member.end)
        if text.startswith(",", position):
            position = _skip_space(text, position + 1)
        elif text.startswith("}", position):
            return members, position + 1
        else:
            return None
    return None


def _member(text: str, at: int) -> _Member | None:
    """The member whose key opens at ``at``: its key decoded, its value delimited.

    The key is decoded, so a key is named by what it says, escapes included; the value
    is never decoded.
    """
    found = _STRING.match(text, at)
    if found is None:
        return None
    try:
        key = json.loads(found.group())
    except ValueError:
        return None
    colon = _skip_space(text, found.end())
    if not text.startswith(":", colon):
        return None
    start = _skip_space(text, colon + 1)
    end = _value_end(text, start)
    return None if end is None else _Member(found.group(), key, start, end)


def _value_end(text: str, at: int) -> int | None:
    """Where the value starting at ``at`` ends, by its quotes and matched brackets alone."""
    if text.startswith('"', at):
        found = _STRING.match(text, at)
        return None if found is None else found.end()
    if at >= len(text) or text[at] not in _CLOSING:
        scalar = _SCALAR.match(text, at)
        return None if scalar is None else scalar.end()
    pending: list[str] = []
    position = at
    while (found := _STRUCTURAL.search(text, position)) is not None:
        char = found.group()
        if char == '"':
            string = _STRING.match(text, found.start())
            if string is None:
                return None
            position = string.end()
            continue
        position = found.end()
        if char in _CLOSING:
            pending.append(_CLOSING[char])
        elif not pending or pending.pop() != char:
            return None
        if not pending:
            return position
    return None


def _skip_space(text: str, at: int) -> int:
    """The first position at or after ``at`` that is not JSON whitespace."""
    found = _SPACE.match(text, at)
    return at if found is None else found.end()


@functools.cache
def _expected_fields(shape: type[BaseModel]) -> dict[str, _Expected]:
    """Each field ``shape`` names, and what it expects (§2:1, §2:3).

    A key is named only where it equals a field's name exactly.

    Raises:
        TypeError: If a field is read under an alias, or expects a model in a form this
            walk does not follow, so a later shape cannot silently escape the drop.
    """
    if shape.model_config.get("alias_generator") is not None:
        msg = f"{shape.__name__} reads its fields under generated aliases"
        raise TypeError(msg)
    expected: dict[str, _Expected] = {}
    for name, info in shape.model_fields.items():
        if info.alias is not None or info.validation_alias is not None:
            msg = f"{shape.__name__}.{name} is read under an alias"
            raise TypeError(msg)
        expected[name] = _expected_of(shape, name, info.annotation)
    return expected


def _expected_of(shape: type[BaseModel], name: str, annotation: object) -> _Expected:
    """What one field's annotation expects: a model, a sequence of one, or neither."""
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return annotation
    args = get_args(annotation)
    if get_origin(annotation) is tuple and len(args) == 2 and args[1] is Ellipsis:  # noqa: PLR2004 — ``tuple[X, ...]``
        element = args[0]
        if isinstance(element, type) and issubclass(element, BaseModel):
            return _Sequence(element)
    if _mentions_a_model(annotation):
        msg = f"{shape.__name__}.{name} expects a model in a form the drop does not follow"
        raise TypeError(msg)
    return None


def _mentions_a_model(annotation: object) -> bool:
    """Whether a model appears anywhere in ``annotation``."""
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return True
    return any(_mentions_a_model(one) for one in get_args(annotation))


def _label_statement(
    unresolved: Sequence[str], brief: _Brief, unlinkable: Sequence[str] = ()
) -> str:
    """The code-owned statement of which labels resolved to nothing and what was rendered."""
    parts: list[str] = []
    if unresolved:
        parts.append(
            f"These labels in `cites` resolve to nothing in the message: {_shown(unresolved)}."
        )
    # ADR-0300 §6:8: a label in `belongs_to` resolves to a matter, or to an earlier
    # stimulus's activation. An R label (ADR-0353 §9:11), and an H label naming an item
    # that links to nothing or an M label naming a remembered fact (§9:12), are dropped
    # with no repair, so none is among these.
    if unlinkable:
        parts.append(
            "These labels in `belongs_to` name no matter and no earlier stimulus: "
            f"{_shown(unlinkable)}."
        )
    rendered = [
        _sequence("H", brief.channel_count, "channel window"),
        _sequence("P", brief.episode_count, "episode window"),
    ]
    if brief.person_count is not None and brief.recalled_count is not None:
        # ADR-0338 §7:7: one M sequence, the person section's first.
        rendered.append(
            _sequence(
                "M", brief.person_count + brief.recalled_count, "person and recalled sections"
            )
        )
    elif brief.person_count is not None:
        rendered.append(_sequence("M", brief.person_count, "person section"))
    elif brief.recalled_count is not None:
        rendered.append(_sequence("M", brief.recalled_count, "recalled section"))
    if brief.story_count is not None:
        rendered.append(_sequence("S", brief.story_count, "stories section"))
    if brief.running:
        # ADR-0353 §10:2: an R label names running work, and may be cited anywhere.
        rendered.append(_sequence("R", len(brief.running), "in_progress section"))
    # ADR-0304 §8:6: an S label the stories section rendered resolves wherever it is
    # cited, so the statement carries no rule on where one may be cited.
    parts.append(f"The message rendered {', '.join(rendered[:-1])} and {rendered[-1]}.")
    parts.append(
        "Reply again with only the corrected JSON object. Name only labels that were rendered."
    )
    return " ".join(parts)


def _never_linked(label: str, brief: _Brief) -> bool:
    """Whether ``label`` names something rendered that never makes a story link (§9:12).

    An exact lookup: an ``H`` label this call rendered, or an ``M`` label naming a
    remembered fact (ADR-0303 §7:6, ADR-0305 §3:2). Read beside ``story_members``, which
    holds every ``H`` label that does link; a fact never does.
    """
    referent = brief.labels.get(label)
    return referent is not None and referent.kind in {"channel_item", "memory"}


def _shown(labels: Sequence[str]) -> str:
    """The model's own label strings, bounded in number and length rather than echoed."""
    return ", ".join(
        json.dumps(label[:_REPAIR_LABEL_CHARS], ensure_ascii=True)
        for label in labels[:_REPAIR_LABELS_SHOWN]
    )


def _sequence(prefix: str, count: int, name: str) -> str:
    if count == 0:
        return f"no {prefix} labels (the {name} is empty)"
    if count == 1:
        return f"{prefix}1 (the {name})"
    return f"{prefix}1 to {prefix}{count} (the {name})"


class _Resolution:
    """Label resolution for one recorded output, counting what it drops (§6)."""

    def __init__(self, labels: dict[str, UnderstandingReferent]) -> None:
        self._labels = labels
        self.dropped = 0

    def referents(self, labels: Sequence[str]) -> tuple[UnderstandingReferent, ...]:
        """The referents of the labels that resolve, each once, in order."""
        seen: set[str] = set()
        referents: list[UnderstandingReferent] = []
        for label in labels:
            referent = self._labels.get(label)
            if referent is None:
                self.dropped += 1
                continue
            if label not in seen:
                seen.add(label)
                referents.append(referent)
        return tuple(referents)


def _resolved(  # noqa: PLR0913 — the reply, what each label kind resolves to, and the two facts orchestration mints
    proposal: ProposedActivationUnderstanding,
    labels: dict[str, UnderstandingReferent],
    story_members: dict[str, StoryMember],
    *,
    version: int,
    recorded_at: datetime,
    running: Mapping[str, str] | None = None,
) -> ActivationUnderstanding:
    """Record the reply by ADR-0353 §9's table, dropping and counting what resolves to nothing.

    ``understanding`` becomes ``meaning``; ``cites`` resolves, through the one table that
    holds every label the call rendered, ``R`` labels included (§10:2), into
    ``meaning_referents``, each once in order; ``unclear`` is copied unchanged;
    ``belongs_to`` resolves into ``story_links`` (ADR-0300 §6:7), proposal order with no
    member twice; and ``meant_for`` resolves, by each ``R`` label, to the running
    activation the call showed under it, in the reply's order and each once, into
    ``continues`` (§10:4, ADR-0349 §10:2). Only ``belongs_to`` makes story links: a
    matter's label in ``cites`` resolves to its referent and links nothing (§9:4).

    Every label that resolves to nothing is dropped and counted in
    ``grounding_dropped``: in ``meant_for`` and an ``R`` label anywhere with no repair
    (§9:11), in ``belongs_to`` a remembered fact or an unlinked place-window item with no
    repair (§9:12), and anything else after the one repair (§9:10). No dropped or absent
    label becomes a referent. The reply carries no answer pointer, and none is recorded
    (§11:2).
    """
    resolution = _Resolution(labels)
    meaning_referents = resolution.referents(proposal.cites)
    links: dict[StoryMember, None] = {}
    for label in proposal.belongs_to:
        member = story_members.get(label)
        if member is None:
            resolution.dropped += 1
            continue
        links.setdefault(member)
    continues: dict[str, None] = {}
    for label in proposal.meant_for:
        named = (running or {}).get(label)
        if named is None:
            resolution.dropped += 1
            continue
        continues.setdefault(named)
    return ActivationUnderstanding(
        version=version,
        recorded_at=recorded_at,
        producer=UnderstandingProducer.INTERPRETATION,
        meaning=proposal.understanding,
        meaning_referents=meaning_referents,
        unclear=proposal.unclear,
        grounding_dropped=resolution.dropped,
        story_links=tuple(links),
        continues=tuple(continues),
    )


# --- rendering helpers -------------------------------------------------------------


def _member_of(record: EpisodicMemory, label: str, story_members: dict[str, StoryMember]) -> None:
    """Record what a ``P`` or ``M`` label naming an episode names as a story label.

    Its activation (ADR-0300 §6:7), as an ``H`` label naming a place-window item that
    links to one resolves to that activation (ADR-0303 §7:4).

    An episode that records no activation is the episode of nothing a story can hold, so
    its label is not a story label at all, and naming it as one is a defect (ADR-0300
    §6:8).
    """
    if (activation := activation_of(record)) is not None:
        story_members[label] = StoryMember(kind=StoryMemberKind.ACTIVATION, id=activation)


def _shown_lines(view: ShortView) -> tuple[StorySummaryLine, ...]:
    """The summary lines a short view renders: none where the summary is withheld."""
    return () if view.withheld else view.lines


def _story_referent(view: ShortView) -> UnderstandingReferent:
    """What an ``S`` label cited in ``cites`` resolves to (ADR-0304 §8:1, ADR-0353 §9:4).

    The story's id as the story store gave it, and as excerpt the first line of its
    summary as the short view rendered it, cut on ADR-0276 §2:5's rule — empty where
    the view rendered no line, a withheld summary included. Nothing resolves the id on
    read: a story since merged is a dangling id, an ordinary state.
    """
    shown = _shown_lines(view)
    return UnderstandingReferent(
        kind="story",
        id=view.story_id,
        source="story",
        excerpt=_excerpt(shown[0].text) if shown else "",
    )


def _summary_line(line: StorySummaryLine) -> dict[str, object]:
    """One line of a story's summary, attributed by its record and never by its text.

    A line carries no mark of its own: the summary's mark is rendered beside the summary.
    """
    return {"written_by": _LINE_AUTHOR_TEXT, "text": line.text}


def _story_note(note: StoryNote) -> dict[str, object]:
    """One pending note, attributed by who wrote it and its mark, never by its text."""
    rendered: dict[str, object] = {
        "written_by": _NOTE_AUTHOR_TEXT[note.author],
        "written_at": note.written_at.isoformat(),
        "text": note.text,
    }
    if note.outside:
        rendered["outside_content"] = _OUTSIDE_TEXT
    return rendered


def _within(deadline: float) -> None:
    """Refuse to start a completion once the pass's deadline has passed (ADR-0276 §5).

    The engine's timer bounds every await, but fires only when the loop gets control;
    this is the check at the two points a completion is about to be spent, so time
    crossed without yielding — rendering, validation — cannot buy one.
    """
    if deadline <= asyncio.get_running_loop().time():
        msg = "the pass's deadline passed before the understanding completion"
        raise TimeoutError(msg)


def _input_rendering(
    text: str, channel: ChannelIdentity, origin: InputOrigin | None = None
) -> dict[str, object]:
    """The input, attributed from where it came from and never from its text (ADR-0098 §2).

    Who it came from is the origin its channel declares (ADR-0284 §2:2) — the very
    declaration admission recorded on the trigger, ``origin`` where the pass hands it
    — and never a test of the channel type, so a second outside channel is attributed
    as a report too (§2:3), and a Telegram input that takes in a forward is a report
    (ADR-0323 §4:11). A scheduled task's input is the assistant's own instruction, written
    when the task was set, and never something the user said (ADR-0350 §6:3, §6:12).
    """
    declared = input_origin(channel) if origin is None else origin
    if declared is InputOrigin.OUTSIDE:
        received = f"a report received on {_channel_text(channel)}, never something the user said"
    elif declared is InputOrigin.ASSISTANT:
        received = (
            f"an instruction the assistant wrote for itself when it scheduled this work, "
            f"pushed on {_channel_text(channel)}; never something the user said"
        )
    else:
        received = f"the message the user just sent on {_channel_text(channel)}"
    return {"received_as": received, "text": text}


#: What an input a merge brought is (ADR-0349 §7:7, §7:21).
_TAKEN_OVER_TEXT: Final = (
    "the input of other work for the same person that this work took over: that work "
    "was stopped, and its input is read here"
)
#: What an in-progress entry shows where its input is withheld, by its origin (§5:6).
_WITHHELD_INPUT: Final = {
    InputOrigin.OUTSIDE: "an outside report, not shown",
    InputOrigin.ASSISTANT: "the assistant's own instruction for work it scheduled, not shown",
    InputOrigin.USER: "not shown",
}


def _recorded_message(message: RecordedInputMessage) -> dict[str, object]:
    """One message of a joined or running input, kept apart and dated (ADR-0323 §5:4)."""
    rendered: dict[str, object] = {"sent_at": message.sent_at.isoformat(), "text": message.text}
    if message.position is not None:
        rendered["position"] = message.position
    if message.forwarded_from is not None:
        rendered["forwarded_from"] = _forward_of(message.forwarded_from)
    return rendered


def _joined_rendering(joined: JoinedInput) -> dict[str, object]:
    """One input a merge brought, as the input renders it (ADR-0332 §3:10, ADR-0349 §7).

    Where it came from and when it was taken in, and each of its messages apart and
    dated; one taken over says so, and never names the activation it stopped, which is
    no label.
    """
    rendered: dict[str, object] = {
        "joined_at": joined.joined_at.isoformat(),
        "place": _channel_text(joined.channel),
        "messages": [_recorded_message(one) for one in joined.messages],
    }
    if joined.taken_over_from is not None:
        rendered["taken_over"] = _TAKEN_OVER_TEXT
    return rendered


def _in_progress_section(
    running: Sequence[InProgressEntry],
    more: int,
    shown: dict[str, str],
    *,
    labels: dict[str, UnderstandingReferent],
    story_members: dict[str, StoryMember],
) -> dict[str, object]:
    """The in-progress section and how many more run, or nothing where none is shown."""
    if not running:
        return {}
    section: dict[str, object] = {
        "in_progress": _running_section(running, shown, labels, story_members)
    }
    if more:
        section["in_progress_more"] = f"{more} more running, not shown, older than those above"
    return section


def _running_section(
    running: Sequence[InProgressEntry],
    shown: dict[str, str],
    labels: dict[str, UnderstandingReferent],
    story_members: dict[str, StoryMember],
) -> list[dict[str, object]]:
    """The in-progress section, each entry under its ``R`` label, minted into the tables.

    Each label names its activation in ``shown``, which ``meant_for`` resolves through
    (ADR-0349 §10:2); its ``running`` referent in ``labels``, the one table ``cites``
    resolves through (ADR-0353 §10:1, §10:2); and its activation as a member in
    ``story_members``, which ``belongs_to`` resolves through (§10:3).
    """
    section: list[dict[str, object]] = []
    for entry in running:
        label = f"R{len(section) + 1}"
        rendered = _running_rendering(label, entry)
        section.append(rendered)
        shown[label] = entry.activation_id
        labels[label] = _running_referent(entry, str(rendered["input"]))
        story_members[label] = StoryMember(kind=StoryMemberKind.ACTIVATION, id=entry.activation_id)
    return section


def _running_referent(entry: InProgressEntry, brief: str) -> UnderstandingReferent:
    """What an ``R`` label cited in ``cites`` resolves to (ADR-0353 §10:1).

    The activation's episode id, stable once the episode freezes; its channel, as an
    episode referent's source is (ADR-0276 §2:5); and its input in brief exactly as its
    entry rendered it, so an input the peer view withholds stays withheld.
    """
    return UnderstandingReferent(
        kind="running",
        id=episode_address(entry.activation_id),
        source=_channel_text(entry.channel),
        excerpt=_excerpt(brief),
    )


def _running_rendering(label: str, entry: InProgressEntry) -> dict[str, object]:
    """One entry under its ``R`` label, exactly as ADR-0349 §5:6 has it.

    What caused it, its channel and its place; what it took in, in brief, read through
    the peer view, so that outside input never appears raw; and whether it has acted.
    """
    return {
        "label": label,
        "place": _channel_text(entry.channel),
        "input": _WITHHELD_INPUT[entry.origin] if entry.input is None else entry.input,
        "has_acted": entry.acted,
    }


def _channel_text(channel: ChannelIdentity) -> str:
    """A channel's type and instance, as the referent's ``source`` records it."""
    return f"{channel.channel_type}:{channel.instance_id}"


def _cut(text: str | None, bound: int) -> tuple[str | None, bool]:
    """A bounded prefix, and whether anything was cut (§4 discloses the cut)."""
    if text is None or len(text) <= bound:
        return text, False
    return text[:bound], True


def _excerpt(text: str) -> str:
    """ADR-0276 §2's bounded prefix of a referent's rendered text."""
    return text[:UNDERSTANDING_REFERENT_EXCERPT_CHARS]
