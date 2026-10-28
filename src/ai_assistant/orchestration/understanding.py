"""The understanding stage: an activation read before it is associated (ADR-0276).

One orchestration-local stage: it holds an injected
:class:`~ai_assistant.core.protocols.StructuredCompleter` and reads no store, and it is
**not a Protocol** (§1). The episode window's records are handed to it: ADR-0282's
**windows stage**, below, holds the composition root's **episode selector** and records
the window as ids, and the understanding phase fetches them (ADR-0282 §3, §5). It
receives no goal, no candidate goal, no attempt, no plan and no context-provider state,
and its message renders none of them.

**The message is tagged text, knowledge then memory** (ADR-0353 §2). Its sections are
always present, in one order, under fixed headings, and it holds no JSON::

    # The stimulus            each input's framing sentence, then its tagged content (§7)
    # Knowledge
    ## The situation          now and the zone, the person's last stimulus, the origin (§6)
    ## Stimulus origin knowledge   the place window, where the medium supplies it  (H)
    ## Concurrent stimuli     ADR-0349 §5's in-progress entries                   (R)
    # Memory
    ## Always in mind         the person block's fields and pinned memories       (M first)
    ## Short-term memory      the episode window's episodes no other section shows (P)
    ## Long-term memory
    ### Recalled memories     what recall kept that no other section shows        (M)
    ### Matters               the candidate stories' short views                  (S)
    ## Stimulus origin memory the place window built from episodes, and the episode
                              window's episodes recorded at the origin            (H, P)

A section with nothing to render says why, by one of ADR-0353 §8:1's four reasons, and
never that anything was withheld from the pass's audience (§8:2): a record the
disclosure predicate withholds reaches no rendering (ADR-0276 §4:9).

**Every writer is named by code** (§3, §4). Each text a record or a medium carries sits in
a text tag whose ``from`` names who or what it is from: the person by their name in the
person block, the system as "the system", an outside source by its identifier, claimed
where it is claimed, and an unknown party as unknown. The tag follows the parties
(ADR-0351 §5): the person's own words are ``said``, the assistant's statement a ``task``,
and every other ``received``. Every value from a record is escaped wherever it is
rendered, so nothing in it can be read as a tag or a heading (§3:5). Every time is
written in full in the zone of the person the stimulus is for, or the hub's where they
set none, and the situation says which once (§5).

**Labels** are minted in the order the message renders them, each letter its own
sequence, under ADR-0276 §3:3's scheme: ``H`` for the place window, ``P`` for the episode
window, ``M`` for the person block's memories and then recall's, ``S`` for the candidate
stories and ``R`` for the in-progress entries. No label survives the call: each resolves,
here, into an :class:`~ai_assistant.core.types.UnderstandingReferent` built from the
material this module rendered, never from model output (§2). An episode that is one
exchange with an item of the place window is rendered once, as that item under its
``H`` label, with its episode's latest understanding attached (§2:4).

**The reply** is :class:`~ai_assistant.core.types.ProposedActivationUnderstanding`, asked
for as a structured call with that shape (ADR-0354 §8): the first completion and the one
repair are each one ``complete_structured`` call through the application's ordinary
route. A value is a parsed output, and its labels are checked as ADR-0353 §9:10 orders:
every label in ``cites`` and ``belongs_to`` not of the ``R`` form must resolve. A label in
``meant_for`` naming no shown activation, an ``R`` label in ``cites`` or ``belongs_to``
naming no shown entry, and a label in ``belongs_to`` naming a remembered fact or a
place-window item that links to no activation are dropped and counted with no repair
(§9:11, §9:12). A returned ``invalid``, ``empty`` or ``cut`` is an output that fails to
parse and costs the one repair, which carries the first reply's text as the assistant's
turn, or none where it is empty, then the code-owned statement naming the failure's kind
(ADR-0354 §8:3); the same failure on the repair raises
:class:`~ai_assistant.core.errors.UnderstandingError` (ADR-0276 §6:3). A returned
``refused`` costs no repair: its returned entry is written, and
:class:`~ai_assistant.core.errors.ModelContentFilterError` is raised (ADR-0354 §8:4). A
second output that parses but still carries a label resolving to nothing is recorded,
the label dropped and counted. There is no ground to downgrade (ADR-0353 §12). A
``ModelError`` propagates unchanged. Nothing here substitutes an empty, default or
invented understanding.

``meant_for`` alone makes the stimulus part of running work (ADR-0353 §10:4): it resolves,
by each ``R`` label, to the activation the call showed under it, into ``continues``. An
``R`` label in ``cites`` resolves to a ``running`` referent, and one in ``belongs_to`` to
the running activation as an activation member (§10:1-§10:3).

**No question is marked, and no answer pointer is read** (ADR-0353 §11). The windows
still bring each assistant message's question with them (``TranscriptWindow.asked``,
``WrittenBy.asked``), and this stage no longer reads it.

**The instruction is a template that takes no flag** (ADR-0334, ADR-0353 §8:3): the
system message is :data:`UNDERSTANDING_PROMPT`'s template, which the composition root
reads at start and hands the stage, and this module keeps no copy of its text (§3:1).
The rendered request, the label validation, the one repair and every rule above stay
here, whatever a template says (§1:3, §7:2).

**It logs stage and code-owned reason only** — no input, no window content, no model
output and no exception content (ADR-0275 §8, ADR-0354 §7:3).
"""

from __future__ import annotations

import asyncio
import functools
import json
import re

# At runtime, not under TYPE_CHECKING: `EpisodeSelector` is a PEP 695 alias, whose
# value is read lazily and must resolve when it is (#1706).
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final
from zoneinfo import ZoneInfo

import structlog

from ai_assistant.core.channel_validation import (
    OriginKind,
    declared_input,
    origin_kind,
)
from ai_assistant.core.diagnostics import write_diagnostic, write_failure
from ai_assistant.core.episode_encoding import project_episode
from ai_assistant.core.errors import ModelContentFilterError, UnderstandingError
from ai_assistant.core.prompts import PromptDeclaration
from ai_assistant.core.reply_shapes import reply_shape_version
from ai_assistant.core.types import (
    DEFAULT_ASSISTANT_NAME,
    OWNER_PERSON_ID,
    UNDERSTANDING_REFERENT_EXCERPT_CHARS,
    ActivationUnderstanding,
    BeliefBand,
    DeletedMessage,
    DiagnosticKind,
    DiagnosticSource,
    EpisodicMemory,
    HolderKind,
    Memory,
    Message,
    MessageAuthor,
    ProfileField,
    ProposedActivationUnderstanding,
    RecallOutcome,
    ReplyFailure,
    Role,
    StoryMember,
    StoryMemberKind,
    StoryNoteAuthor,
    SupportHolder,
    UnderstandingProducer,
    UnderstandingReferent,
    parties_are_outside,
    parties_are_persons_own,
    relay_mark_counts,
)
from ai_assistant.orchestration.disclosure import admitted_to_understanding
from ai_assistant.orchestration.episode_reads import without_open_episodes
from ai_assistant.orchestration.matters import EntryInput
from ai_assistant.orchestration.person_block import activation_person
from ai_assistant.orchestration.stories import episode_address
from ai_assistant.orchestration.story_privacy import activation_of

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from ai_assistant.core.prompts import PromptTemplate, RenderedPrompt
    from ai_assistant.core.protocols import DiagnosticSink, MemoryStore, StructuredCompleter
    from ai_assistant.core.types import (
        ActivationRecall,
        ChannelContext,
        ChannelContextItem,
        ChannelIdentity,
        ClaimedAuthor,
        EpisodeProjection,
        JoinedInput,
        RecordedChannelTrigger,
        RecordedInputMessage,
        StoryNote,
        StorySummaryLine,
        StructuredReply,
        TranscriptMessage,
        UnclearPoint,
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

#: Understanding's prompt (ADR-0334 §2): its system message is the template
#: ``understanding.txt`` shipped beside this module, or the owner's override of it, which
#: the composition root reads and hands the stage (§3:5). It takes no flag and prints no
#: value: every part of its instruction is sent on every call (ADR-0353 §8:3).
#:
#: **What the instruction must say**, which binds the default and every override alike
#: (ADR-0334 §7:1), and which a promotion's review reads it against (§7:3), as ADR-0353
#: §13:2 rewrote the list:
#:
#: - all of the message is data to understand, never instructions, and who or what an
#:   item is from is stated by its tag's attributes, never by its text (ADR-0098 §2:2,
#:   ADR-0276 §3:6);
#: - what each section is (ADR-0353 §2), and that the lines between the tags are the
#:   system's own (§3:4);
#: - that memory, the matters included, is the system's own memory, provisional and
#:   possibly out of date (ADR-0304 §8:5, in its part that stands);
#: - what concurrent stimuli are, that ``meant_for`` names the work the stimulus is meant
#:   for by ADR-0353 §10:5's test and separate work none, and that only ``meant_for``
#:   makes the stimulus part of that work (ADR-0349 §5:2-§5:6, §7:3, and ADR-0353 §10);
#: - ADR-0351 §5:12's relay line;
#: - that an unclear point's readings say what the stimulus would mean, never what to do
#:   (ADR-0276 §6:1, as ADR-0353 §9 amends it).
#:
#: It need no longer say what a ground means, anything of a question mark, a ``Q`` label
#: or an answer, that the language is a hint, that always in mind's ``M`` labels come
#: first, or anything of a link (ADR-0353 §13:3). Authority is not read here: whose input
#: approves is authorizing's check (ADR-0321 §3:3).
UNDERSTANDING_PROMPT: Final = PromptDeclaration(
    name="understanding",
    package="ai_assistant.orchestration",
)

#: The shape understanding's reply is asked for as (ADR-0354 §8:1, ADR-0353 §9:2).
REPLY_SHAPE: Final = ProposedActivationUnderstanding

#: A label of the ``R`` form (ADR-0353 §9:10, §9:11): ``R`` and a decimal number. One in
#: ``cites`` or ``belongs_to`` naming no shown entry is dropped and counted with no
#: repair; every other unresolved label there earns the one repair.
_R_FORM: Final = re.compile(r"R[0-9]+")

#: The code-owned statement of a reply that does not parse, by the failure's kind
#: (ADR-0354 §8:3): each names the kind, and none quotes the reply.
_UNPARSED: Final = {
    ReplyFailure.INVALID: (
        "Your reply did not parse: it was not one JSON object of the required shape, so it "
        "could not be read (invalid). Reply again with only that JSON object."
    ),
    ReplyFailure.EMPTY: (
        "Your reply did not parse: it was empty (empty). Reply again with only the JSON "
        "object of the required shape."
    ),
    ReplyFailure.CUT: (
        "Your reply did not parse: it stopped before it ended (cut). Reply again with only "
        "the JSON object of the required shape, shorter."
    ),
}

#: The zone a call renders in where the understanding phase hands none.
_UTC: Final = ZoneInfo("UTC")

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


# --- the message's words (ADR-0353 §3, §4, §5) ---------------------------------------

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
#: How many messages the framing sentence spells as a word (§7:1).
_COUNTS: Final = ("two", "three", "four", "five", "six", "seven", "eight", "nine", "ten")
_NOON: Final = 12

#: The four reasons an empty section gives (ADR-0353 §8:1), each the start of its note,
#: and the wording where withholding alone may have emptied it (§8:2).
_NOTHING_THERE: Final = "Nothing is there"
_NOTHING_SHOWN: Final = "Nothing is shown"
_NOT_PROVIDED: Final = "The origin does not provide it"
_NOT_HELD: Final = "The system does not have it"
_UNREADABLE: Final = "It could not be read"
#: Every note's opening, by which a reader tells which reason a note gives.
NOTE_REASONS: Final = (_NOTHING_THERE, _NOTHING_SHOWN, _NOT_PROVIDED, _NOT_HELD, _UNREADABLE)

#: What the system is called in every tag, attribute and line (§4:2).
_SYSTEM: Final = "the system"
#: An unknown party, named as unknown (§4:3, §7:2).
_UNKNOWN: Final = "an unknown sender"
#: The person the system serves, where they have set no name (§4:1).
_UNNAMED: Final = "the owner"
#: Another person, whom no block names (§4:1).
_SOMEONE: Final = "a person the system knows"


def _text(value: str) -> str:
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
    return _text(_one_line(value)).replace('"', "&quot;")


def _line(value: str) -> str:
    """A record's value placed in a line between the tags: on one line, escaped (§3:5)."""
    return _text(_one_line(value))


def _tag(name: str, attributes: Sequence[tuple[str, str]], text: str | None) -> str:
    """One text tag, its attributes escaped, its text escaped, or empty where ``None``."""
    written = "".join(f' {key}="{_attribute(value)}"' for key, value in attributes)
    if text is None:
        return f"<{name}{written}/>"
    return f"<{name}{written}>{_text(text)}</{name}>"


def _container(name: str, attributes: Sequence[tuple[str, str]], tags: Sequence[str]) -> list[str]:
    """A container and the tags it holds, which carries no text of its own (§3:3)."""
    written = "".join(f' {key}="{_attribute(value)}"' for key, value in attributes)
    return [f"<{name}{written}>", *(f"  {one}" for one in tags), f"</{name}>"]


def _clock(local: datetime) -> str:
    """A clock time as the message writes it: ``3:51 pm``."""
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


def _ended(projection: EpisodeProjection) -> str | None:
    """A stimulus in memory's status and reason, as ``ended=`` writes them (§3:8)."""
    if projection.status is None or projection.reason is None:
        return None
    status = projection.status.value.replace("_", " ")
    reason = projection.reason.value.replace("_", " ")
    return status if reason == status else f"{status}, {reason}"


def _origin_of(channel: ChannelIdentity | None) -> OriginKind | None:
    """What a channel's kind declares for understanding, where it declares it (§6:3)."""
    return None if channel is None else origin_kind(channel.channel_type)


def _origin_name(channel: ChannelIdentity | None) -> str:
    """How an origin is named (§4:4): its kind's name, or its channel type as recorded."""
    kind = _origin_of(channel)
    if kind is not None:
        return kind.name
    return "an origin the record does not name" if channel is None else channel.channel_type


def _origin_where(channel: ChannelIdentity | None) -> str:
    """An origin's name with the preposition its kind declares, or ``on`` and its type."""
    kind = _origin_of(channel)
    if kind is not None:
        return kind.where
    return (
        "at an origin the record does not name" if channel is None else f"on {channel.channel_type}"
    )


def _words_tag(parties: Sequence[SupportHolder] | None, *, relayed: bool = False) -> str:
    """The text tag words of these parties sit in (ADR-0353 §3:2, ADR-0351 §5).

    ``said`` for the person's own, ``task`` for the assistant's statement, ``received``
    for every other: outside, mixed, or unknown, and words a relay mark that counts
    makes outside (ADR-0351 §5:4, §5:7).
    """
    if relay_mark_counts(parties, relayed=relayed):
        return "received"
    if parties and all(one.kind is HolderKind.PERSON for one in parties):
        return "said"
    if parties and all(one.kind is HolderKind.ASSISTANT_STATEMENT for one in parties):
        return "task"
    return "received"


def _received(words: Sequence[_Words]) -> list[_Words]:
    """``words`` of an input a relay mark counts on, each attributed as received.

    ADR-0351 §5:5, §5:7: only an input whose parties are the person's own or the
    assistant's; on one already outside, each message keeps its own party's tag.
    """
    return [replace(one, tag="received") for one in words]


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


@dataclass(frozen=True, slots=True)
class _Words:
    """One text of the stimulus section: its tag, writer, time, text and what it answers."""

    tag: str
    writer: str
    at: datetime | None
    text: str
    replies_to: str | None = None
    forward: bool = False
    number: int | None = None


# --- the rendered call -----------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Brief:
    """One call's rendered request and the label tables it minted.

    ``labels`` holds exactly the labels §3's scheme minted for this call — ``H`` then
    *n*, ``P`` then *n*, ``M`` then *n*, ``S`` then *n* resolving to a ``story`` referent
    (ADR-0304 §8:1), and ``R`` then *n* resolving to a ``running`` referent (ADR-0353
    §10:1, §10:2), ASCII decimal with no padding — so an exact lookup is the whole of
    resolution: a string of another form, an *n* out of range and a label of a sequence
    this call did not render all miss it, and nothing is case-folded, trimmed or repaired.
    """

    messages: tuple[Message, Message]
    #: The system message's instruction, which each given entry for the call, and for its
    #: repair, records (ADR-0335 §9:1).
    instruction: RenderedPrompt
    labels: dict[str, UnderstandingReferent]
    #: What a ``belongs_to`` label resolves to (ADR-0300 §6:7): an ``S`` label its story, a
    #: ``P`` or ``M`` label naming an episode that episode's activation, an ``R`` label its
    #: running activation (ADR-0353 §10:3), and an ``H`` label naming a place-window item
    #: that links to an activation that activation (ADR-0303 §7:4).
    story_members: dict[str, StoryMember] = field(default_factory=dict)
    #: What each ``R`` label names: the running activation, by its id (ADR-0349 §10:2).
    running: dict[str, str] = field(default_factory=dict)
    #: How many labels of each letter the message rendered.
    counts: dict[str, int] = field(default_factory=dict)


@functools.cache
def _reply_shape() -> dict[str, str]:
    """The given entry's ``reply_shape``: the shape's name and version (ADR-0354 §7:1)."""
    return {"name": REPLY_SHAPE.__name__, "version": reply_shape_version(REPLY_SHAPE)}


def _returned(
    reply: StructuredReply[ProposedActivationUnderstanding],
) -> dict[str, str | dict[str, int] | None]:
    """The returned entry of a structured call (ADR-0354 §7:2).

    The reply as the model wrote it, and what the exchange holds of the model that
    answered, the mode, the finish reason, a refusal and the usage, and the failure's kind;
    and the provider's summary of its thinking under ``thinking`` where the exchange holds
    one, with no such key where it holds none (ADR-0355 §5:1).
    """
    exchange = reply.exchange
    returned: dict[str, str | dict[str, int] | None] = {
        "reply": exchange.reply,
        "model": exchange.model,
        "mode": exchange.mode.value,
        "finish_reason": exchange.finish_reason,
        "refusal": exchange.refusal,
        "refusal_category": exchange.refusal_category,
        "usage": {
            "input_tokens": exchange.usage.input_tokens,
            "output_tokens": exchange.usage.output_tokens,
            "cache_read_tokens": exchange.usage.cache_read_tokens,
            "cache_write_tokens": exchange.usage.cache_write_tokens,
        },
        "failure": None if reply.failure is None else reply.failure.value,
    }
    if exchange.thinking is not None:
        returned["thinking"] = exchange.thinking
    return returned


class UnderstandingStage:
    """Produce one activation's understanding from its input and two windows (ADR-0276)."""

    def __init__(
        self,
        *,
        model: StructuredCompleter,
        excerpt_chars: int,
        prompt: PromptTemplate,
        diagnostics: DiagnosticSink | None = None,
    ) -> None:
        """Wire the stage to the structured-completion seam, the excerpt bound, its prompt.

        The stage reads no store: the episode window's records are handed to it, as
        the understanding phase fetched them (ADR-0282 §5).

        Args:
            model: The application's ordinary, already-wrapped route, as its
                ``StructuredCompleter`` (ADR-0354 §6:2, §8:1), carrying the provider
                stack's retry policy (ADR-0011). ``complete_structured`` is called with no
                ``model=`` override, since ADR-0013 §4 rules that one disables routing.
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

    async def understand(  # noqa: PLR0913 — the input and everything the phase hands the stage to render it
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
        relayed: bool = False,
        joined: Sequence[JoinedInput] = (),
        running: Sequence[InProgressEntry] | None = None,
        running_more: int = 0,
        person: PersonBlock | None = None,
        trigger: RecordedChannelTrigger | None = None,
        zone: ZoneInfo | None = None,
        own_zone: bool = False,
        received_at: datetime | None = None,
    ) -> ActivationUnderstanding:
        """Read one input against its context, and record what it was understood to mean.

        Args:
            text: The activation's input — the utterance, the transcript or the
                event's text — exactly as the pass holds it.
            channel: The channel it arrived on: its origin (ADR-0353 §4:4).
            window: The place window (ADR-0276 §3).
            audience: The pass's audience posture. Its predicate filters the stored
                records of both windows before anything is rendered (§4).
            episodes: The episode window's records, in the window's order, as the
                understanding phase fetched them (ADR-0282 §5); ``None`` where the
                pass takes no episode window (§4:13). The audience predicate is
                applied to them again here.
            version: The version orchestration mints for this record.
            now: The clock ``recorded_at`` and the situation's now are read from.
            deadline: The pass's deadline on the running loop's clock (§5). No
                completion is started once it has passed — the one repair included —
                however the time was spent.
            recall: Recall's decision for the pass (ADR-0281 §7); ``None`` where recall
                made no decision, and then recalled memories say the system does not
                have them.
            recalled: The records of recall's kept items the understanding phase
                fetched, in recall's order (ADR-0282 §5).
            stories: The candidate stories the understanding phase assembled
                (ADR-0300 §6:1-§6:4); ``None`` where it assembled none.
            relayed: Whether an earlier version of the activation's understanding marked
                its trigger's input relayed (ADR-0351 §5:6). The mark holds for the rest
                of the activation, so this version records it whatever the reply says
                (§5:9), and the input is rendered as received (§5:5, §5:7).
            joined: The inputs the activation took in beside its trigger's, in the order
                it took them in (ADR-0349 §7:7, §7:21), each rendered with its own framing
                sentence after the trigger's (ADR-0353 §2:2).
            running: The concurrent stimuli (ADR-0349 §5:2-§5:10), newest first, each
                under its ``R`` label (ADR-0353 §2:5, §10).
            running_more: How many more run than the section shows (§5:10).
            person: The activation's person block (ADR-0338 §7:1): always in mind, and
                the name every person is called by (ADR-0353 §4:1, §4:5).
            trigger: The activation's recorded trigger, whose parties and messages the
                stimulus is attributed and framed by (ADR-0353 §3:1, §7:3).
            zone: The zone every time is rendered in (ADR-0353 §5:2): the person's, or
                the hub's where they set none; UTC where none is handed.
            own_zone: Whether ``zone`` is the person's own rather than the hub's.
            received_at: When the stimulus reached the system, for its framing sentence
                and the person's last stimulus; ``now`` where none is handed.

        Returns:
            The recorded understanding.

        Raises:
            UnderstandingError: If the one repair's output still does not parse.
            ModelContentFilterError: If the provider refused a completion (ADR-0354 §8:4).
            ModelError: Propagated unchanged from the provider stack.
            TimeoutError: If ``deadline`` had passed when a completion was due.
        """
        moment = now()
        # Whose words the input carries: its trigger's parties, or, where none is handed,
        # those its channel's kind declares (ADR-0351 §2:1, §3:1).
        parties = _parties_of(trigger, channel)
        brief = _Renderer(
            excerpt_chars=self._excerpt_chars,
            zone=zone or _UTC,
            own_zone=own_zone,
            naming=_naming(person, trigger, parties),
            channel=channel,
            now=moment,
            received_at=received_at or moment,
            profiled=person is not None,
            relayed=relayed,
        ).brief(
            self._prompt,
            text,
            window=window,
            audience=audience,
            episodes=episodes,
            recall=recall,
            recalled=recalled,
            stories=stories,
            parties=parties,
            trigger=trigger,
            joined=joined,
            running=running or (),
            running_more=running_more,
            person=person,
        )
        _within(deadline)
        first = await self._completed(brief.messages, brief.instruction)
        proposal, problem = self._validated(first, brief)
        if problem is not None:
            _within(deadline)
            _log.info("understanding_repair", stage="understanding", reason=problem.reason)
            written = first.exchange.reply
            second = await self._completed(
                (
                    *brief.messages,
                    # ADR-0354 §8:3: the first reply's text as the assistant's turn, or no
                    # assistant turn where that text is empty.
                    *((Message(role=Role.ASSISTANT, content=written),) if written.strip() else ()),
                    Message(role=Role.USER, content=problem.statement),
                ),
                brief.instruction,
            )
            proposal, problem = self._validated(second, brief)
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
            relayed=relayed,
        )

    async def _completed(
        self, messages: Sequence[Message], instruction: RenderedPrompt
    ) -> StructuredReply[ProposedActivationUnderstanding]:
        """One structured completion, its request and its reply written to the record.

        The given entry is written before the call and the returned one once it returns
        or fails (ADR-0314 §4:1); a failure raised is re-raised unchanged. The given entry
        names the template the system message was rendered from (ADR-0334 §8:2) and the
        reply's shape and version (ADR-0354 §7:1), the repair's included. The returned
        entry keeps the reply as the model wrote it, and what the exchange holds, before
        the stage acts on a returned failure (§7:2).
        """
        await write_diagnostic(
            self._diagnostics,
            DiagnosticSource.UNDERSTANDING,
            DiagnosticKind.GIVEN,
            lambda: {
                "messages": [one.model_dump(mode="json") for one in messages],
                "prompt": instruction.provenance(),
                "reply_shape": _reply_shape(),
            },
        )
        try:
            reply = await self._model.complete_structured(messages, REPLY_SHAPE)
        except Exception as exc:
            await write_failure(self._diagnostics, DiagnosticSource.UNDERSTANDING, exc)
            raise
        await write_diagnostic(
            self._diagnostics,
            DiagnosticSource.UNDERSTANDING,
            DiagnosticKind.RETURNED,
            lambda: _returned(reply),
        )
        return reply

    def _validated(
        self, reply: StructuredReply[ProposedActivationUnderstanding], brief: _Brief
    ) -> tuple[ProposedActivationUnderstanding | None, _Problem | None]:
        """ADR-0353 §9:10's two checks, in order, and the code-owned statement of what failed.

        A returned failure is the parse's: ``refused`` raises, and ``invalid``, ``empty``
        and ``cut`` are a reply that does not parse (ADR-0354 §8:3, §8:4). Then the labels
        of ``cites`` and ``belongs_to`` that are not of the ``R`` form. A label in
        ``meant_for`` naming no shown activation, an ``R`` label in ``cites`` or
        ``belongs_to`` naming no shown entry (§9:11), and a label in ``belongs_to`` naming
        a remembered fact or a place-window item that links to no activation (§9:12), call
        for no repair: :func:`_resolved` drops and counts each.

        Raises:
            ModelContentFilterError: Where the provider refused the call.
        """
        failure = reply.failure
        if failure is ReplyFailure.REFUSED:
            _log.warning("understanding_refused", stage="understanding", reason=failure.value)
            msg = "the provider refused the understanding call (ADR-0354 §8:4)"
            raise ModelContentFilterError(msg)
        if failure is not None:
            return None, _Problem(failure.value, _UNPARSED[failure])
        proposal = reply.value
        assert proposal is not None  # noqa: S101 — a reply holds its value or a failure
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


def _parties_of(
    trigger: RecordedChannelTrigger | None, channel: ChannelIdentity
) -> tuple[SupportHolder, ...] | None:
    """Whose words the stimulus carries: its trigger's parties (ADR-0351 §2:1).

    Where no trigger is handed, the parties its channel's kind declares (§3:1).
    """
    if trigger is not None:
        return trigger.parties
    return declared_input(channel)[0]


def _naming(
    person: PersonBlock | None,
    trigger: RecordedChannelTrigger | None,
    parties: Sequence[SupportHolder] | None,
) -> _Naming:
    """Who the stimulus is for, from its person block, else its trigger (ADR-0338 §2:2).

    With neither, the owner where the words are the person's own (ADR-0351 §3:2).
    """
    if person is not None:
        return _Naming(person_id=person.person_id, name=person.profile.value(ProfileField.NAME))
    if trigger is not None:
        return _Naming(person_id=activation_person(trigger), name=None)
    return _Naming(
        person_id=OWNER_PERSON_ID if parties_are_persons_own(parties) else None, name=None
    )


# --- the renderer (ADR-0353 §2-§8) -------------------------------------------------------


class _Renderer:
    """One call's message: its sections in order, its labels minted as they render."""

    def __init__(  # noqa: PLR0913 — the bound, the zone and whose it is, the naming, the origin, the two instants, whether a profile is held, and the relay mark
        self,
        *,
        excerpt_chars: int,
        zone: ZoneInfo,
        own_zone: bool,
        naming: _Naming,
        channel: ChannelIdentity,
        now: datetime,
        received_at: datetime,
        profiled: bool,
        relayed: bool = False,
    ) -> None:
        self._profiled = profiled
        # ADR-0351 §5:9: an earlier version's relay mark on the trigger's input.
        self._relayed = relayed
        self._excerpt_chars = excerpt_chars
        self._zone = zone
        self._own_zone = own_zone
        self._naming = naming
        self._channel = channel
        self._now = now
        self._received_at = received_at
        self.labels: dict[str, UnderstandingReferent] = {}
        self.story_members: dict[str, StoryMember] = {}
        self.running: dict[str, str] = {}
        self.counts: dict[str, int] = {}

    # --- labels and times ---

    def _mint(self, letter: str) -> str:
        count = self.counts.get(letter, 0) + 1
        self.counts[letter] = count
        return f"{letter}{count}"

    def _local(self, instant: datetime) -> datetime:
        return instant.astimezone(self._zone)

    def _at(self, instant: datetime) -> str:
        """An instant in full, in the call's zone: ``Mon 26 Oct 2026, 9:12 am`` (§5:1)."""
        local = self._local(instant)
        return (
            f"{_DAY[local.weekday()]} {local.day} {_MONTH[local.month - 1]} {local.year}, "
            f"{_clock(local)}"
        )

    # --- the message ---

    def brief(  # noqa: PLR0913 — the template, the input and everything rendered beside it
        self,
        prompt: PromptTemplate,
        text: str,
        *,
        window: ChannelWindow,
        audience: TurnSupply,
        episodes: tuple[EpisodicMemory, ...] | None,
        recall: ActivationRecall | None,
        recalled: tuple[EpisodicMemory | Memory, ...],
        stories: Candidates | None,
        parties: tuple[SupportHolder, ...] | None,
        trigger: RecordedChannelTrigger | None,
        joined: Sequence[JoinedInput],
        running: Sequence[InProgressEntry],
        running_more: int,
        person: PersonBlock | None,
    ) -> _Brief:
        """Render the message, filtering the episode window's stored records first (§3, §4).

        Labels are minted in the order the sections render them, each letter its own
        sequence (ADR-0353 §2:3). No question is marked (§11:1).
        """
        placed = _Placed.of(window, audience, episodes)
        kind = _origin_of(self._channel)
        remembered = kind is not None and kind.remembered
        items = self._window_items(placed)
        window_lines = [line for _, lines in items for line in lines]
        by_position = {
            one.item.position: label
            for (label, _), one in zip(items, placed.items, strict=True)
            if one.item.position is not None
        }
        knowledge_lines = [] if remembered else window_lines
        concurrent = self._concurrent(running, running_more)
        always = self._always_in_mind(person)
        unshared = [record for record in placed.episodes if record.id not in placed.shared]
        here = [record for record in unshared if _at_origin(record, self._channel)]
        elsewhere = [record for record in unshared if not _at_origin(record, self._channel)]
        short_term = [
            line for record in elsewhere for line in self._remembered(record, admit_outside=True)
        ]
        recalled_lines = self._recalled(recall, recalled, placed, person)
        matters = self._matters(stories)
        origin_memory = [
            *(window_lines if remembered else []),
            *(line for record in here for line in self._remembered(record, admit_outside=True)),
        ]
        stimulus = self._stimulus(
            text,
            window=window,
            parties=parties,
            trigger=trigger,
            joined=joined,
            by_position=by_position,
        )
        last = self._last(placed, recalled, running)
        sections = [
            "# The stimulus",
            *stimulus,
            "",
            "# Knowledge",
            "",
            "## The situation",
            *self._situation(kind, last),
            "",
            "## Stimulus origin knowledge",
            *(knowledge_lines or [self._knowledge_note(window, remembered=remembered)]),
            "",
            "## Concurrent stimuli",
            *concurrent,
            "",
            "# Memory",
            "",
            "## Always in mind",
            *always,
            "",
            "## Short-term memory",
            *(short_term or [self._short_term_note(episodes)]),
            "",
            "## Long-term memory",
            "### Recalled memories",
            *recalled_lines,
            "",
            "### Matters",
            *matters,
            "",
            "## Stimulus origin memory",
            *(origin_memory or [self._origin_memory_note(window, episodes, remembered=remembered)]),
        ]
        instruction = prompt.rendered(flags={})
        messages = (
            Message(role=Role.SYSTEM, content=instruction.text),
            Message(role=Role.USER, content="\n".join(sections)),
        )
        return _Brief(
            messages,
            instruction,
            self.labels,
            self.story_members,
            self.running,
            self.counts,
        )

    # --- the stimulus (§7) ---

    def _stimulus(  # noqa: PLR0913 — the input, its window, its parties and record, what joined it, and the window's labels
        self,
        text: str,
        *,
        window: ChannelWindow,
        parties: tuple[SupportHolder, ...] | None,
        trigger: RecordedChannelTrigger | None,
        joined: Sequence[JoinedInput],
        by_position: Mapping[int, str],
    ) -> list[str]:
        """Every input the activation holds, the trigger's then each joined one, framed.

        Each begins with its framing sentence and its tagged content follows it (§7:1). The
        trigger's messages are its window's input messages where the chat's reader brought
        them, else its recorded messages, else its text whole; every text is attributed by
        its parties, never by what it says (§7:3).
        """
        words: list[_Words]
        if isinstance(window, TranscriptWindow) and window.input_messages:
            # ADR-0293 §4:5: a message of the input may reply to another of the input, which
            # carries no label, so each is numbered and a reply names the number.
            numbers = {one.position: n for n, one in enumerate(window.input_messages, 1)}
            replied = {
                **{position: f"message {n}" for position, n in numbers.items()},
                **by_position,
            }
            words = [
                self._input_message(one, window, replied, numbers[one.position])
                for one in window.input_messages
            ]
        elif trigger is not None and trigger.messages:
            words = [self._recorded_message(one, None) for one in trigger.messages]
        else:
            words = [
                _Words(
                    tag=_words_tag(parties),
                    writer=self._naming.parties(parties),
                    at=None,
                    text=text,
                    replies_to=self._supplied_reply(window),
                )
            ]
        new_conversation = (
            self._channel.channel_type == "conversation"
            and isinstance(window, TranscriptWindow)
            and not window.messages
            and not window.replied_to
        )
        if relay_mark_counts(parties, relayed=self._relayed):
            words = _received(words)
        lines = self._framed(
            self._channel, parties, words, at=self._received_at, new_conversation=new_conversation
        )
        for one in joined:
            joined_parties = _known_parties(one.messages)
            joined_words = [self._recorded_message(message, None) for message in one.messages]
            if relay_mark_counts(joined_parties, relayed=one.relayed):
                joined_words = _received(joined_words)
            lines.append("")
            lines.extend(
                self._framed(
                    one.channel,
                    joined_parties,
                    joined_words,
                    at=one.messages[0].sent_at,
                    taken_over=one.taken_over_from is not None,
                )
            )
        return lines

    @staticmethod
    def _supplied_reply(window: ChannelWindow) -> str | None:
        """The ``H`` label of the item a supplied window says this input replies to.

        The item it replies to is the window's last (ADR-0276 §3:1), labelled after the
        history's.
        """
        if isinstance(window, SuppliedWindow) and window.context.reply_to is not None:
            return f"H{len(window.context.history) + 1}"
        return None

    def _framed(  # noqa: PLR0913 — the origin, the parties, the texts, when, and the two clauses a sentence may add
        self,
        channel: ChannelIdentity,
        parties: Sequence[SupportHolder] | None,
        words: Sequence[_Words],
        *,
        at: datetime,
        new_conversation: bool = False,
        taken_over: bool = False,
    ) -> list[str]:
        """One input's framing sentence and its tagged content (ADR-0353 §7:1-§7:5).

        Every slot is filled from records alone, with a fallback that stays true: an
        unknown sender is named as unknown, and an act the record does not establish is
        not said to have happened (§7:2).
        """
        local = self._local(at)
        what, content = self._what(channel, parties, words)
        if new_conversation:
            what += ", starting a new conversation"
        if taken_over:
            what += ", taken in from other work, which was stopped"
        opening = f"A stimulus reached the system at {_clock(local)} on {_long_day(local)}: {what}"
        if content is None:
            # §7:4: an input whose parties are empty has no content clause, and no content.
            return [f"{opening}."]
        several = len(words) > 1
        verb = "They contain" if several else "It contains"
        lines = [f"{opening}. {verb} {content}:"]
        for one in words:
            attributes = [("from", one.writer)]
            if one.number is not None and several:
                attributes.append(("message", str(one.number)))
            if one.at is not None:
                attributes.append(("at", self._at(one.at)))
            if one.replies_to is not None:
                attributes.append(("replies_to", one.replies_to))
            lines.append(_tag(one.tag, attributes, one.text))
        return lines

    def _what(
        self,
        channel: ChannelIdentity,
        parties: Sequence[SupportHolder] | None,
        words: Sequence[_Words],
    ) -> tuple[str, str | None]:
        """The framing sentence's ``{what}`` and ``{content}`` (§7:1's table), from records."""
        kind = _origin_of(channel)
        # §3:5: a value from a record, a fallback's channel type among them, is escaped and
        # kept to one line wherever a line between the tags carries it.
        where = _line(_origin_where(channel))
        if parties is not None and not parties:
            return f"an input with no one's words in it arrived {where}", None
        if kind is not None and kind.act:
            return self._sent(kind, where, words)
        content = kind.content if kind is not None else "this text"
        if parties and all(one.kind is HolderKind.ASSISTANT_STATEMENT for one in parties):
            what = "a step of scheduled work came due"
        elif parties and all(one.kind is HolderKind.OUTSIDE_SOURCE for one in parties):
            what = f"a report from {_line(self._naming.parties(parties))}"
        elif len(words) > 1:
            return f"{_count(len(words))} inputs {where}", "these messages"
        else:
            what = f"an input {where}"
        return what, content

    def _sent(self, kind: OriginKind, where: str, words: Sequence[_Words]) -> tuple[str, str]:
        """``{what}`` for a message a person sends: what they did, and how many (§7:1)."""
        forwards = sum(one.forward for one in words)
        if forwards == len(words):
            act = "forwarded"
        elif forwards:
            act = f"{kind.act} or forwarded"
        else:
            act = kind.act
        who = _line(self._naming.who)
        if len(words) > 1:
            return f"{_count(len(words))} messages {who} {act} {where}", "these messages"
        return f"a message {who} {act} {where}", kind.content

    def _input_message(
        self,
        message: TranscriptMessage | LineMessage,
        window: TranscriptWindow,
        by_position: Mapping[int, str],
        number: int,
    ) -> _Words:
        """One message of the input as the medium holds it: who wrote it, when, what it answers.

        A forward is its original sender's, claimed, and never the person's words
        (ADR-0323 §4:10, ADR-0351 §2:7). What it replies to is named by the window item's
        label, or by the number of the input's own message it replies to.
        """
        forward = window.forwarded.get(message.position)
        replies = None if message.replies_to is None else by_position.get(message.replies_to)
        if forward is not None:
            return _Words(
                tag="received",
                writer=self._naming.forward(forward),
                at=message.written_at,
                text=message.text,
                replies_to=replies,
                forward=True,
                number=number,
            )
        return _Words(
            tag="said",
            writer=self._naming.who,
            at=message.written_at,
            text=message.text,
            replies_to=replies,
            number=number,
        )

    def _recorded_message(self, message: RecordedInputMessage, replies: str | None) -> _Words:
        """One recorded message of an input, attributed by its own party (ADR-0351 §2:6)."""
        party = None if message.party is None else (message.party,)
        if message.forwarded_from is not None:
            writer = self._naming.forward(message.forwarded_from)
        else:
            writer = self._naming.parties(party)
        return _Words(
            tag=_words_tag(party),
            writer=writer,
            at=message.sent_at,
            text=message.text,
            replies_to=replies,
            forward=message.forwarded_from is not None,
        )

    # --- the situation (§6) ---

    def _situation(self, kind: OriginKind | None, last: tuple[datetime, str] | None) -> list[str]:
        """Now with the zone, the person's last stimulus, and the origin (§6:1)."""
        local = self._local(self._now)
        now = f"{_long_day(local)}, {_clock(local)}"
        naming = self._naming
        who = _line(naming.who)
        zone = _line(self._zone.key)
        if self._own_zone:
            first = (
                f"- Now: {now}, in {who}'s time zone ({zone}). Every time below is in this zone."
            )
        elif naming.person_id is not None and self._profiled:
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
        if naming.person_id is None:
            second = "- Last stimulus: this stimulus is no person's, so no earlier one is named."
        elif last is None:
            second = (
                f"- {_upper(who)}'s last stimulus: the system holds none earlier than this one."
            )
        else:
            second = f"- {_upper(who)}'s last stimulus: {self._at(last[0])}, {_line(last[1])}."
        name = _origin_name(self._channel)
        if kind is None:
            third = f"- The origin: {_line(name)}; the system has no description of it."
        else:
            described = kind.described.replace("{person}", who)
            third = f"- The origin: {name}, {described}."
        return [first, second, third]

    def _last(
        self,
        placed: _Placed,
        recalled: Sequence[EpisodicMemory | Memory],
        running: Sequence[InProgressEntry],
    ) -> tuple[datetime, str] | None:
        """The newest earlier stimulus for the same person among what the pass holds (§6:2).

        Running or ended: the episode window's and recall's episodes, the concurrent
        stimuli, which are the same person's (ADR-0349 §5:3), and the messages the person
        wrote in the place window, each a stimulus taken in at this origin. Nothing is
        read for it.
        """
        person = self._naming.person_id
        if person is None:
            return None
        found: list[tuple[datetime, str]] = [
            (one.item.at, _origin_where(self._channel))
            for one in placed.items
            if one.item.at is not None
            and one.item.author is MessageAuthor.USER
            and not one.item.outside
        ]
        for record in (*placed.episodes, *recalled):
            if not isinstance(record, EpisodicMemory) or record.processing_record is None:
                continue
            trigger = record.processing_record.trigger
            if activation_person(trigger) == person:
                found.append((record.occurred_at, _origin_where(trigger.channel)))
        found.extend(
            (entry.arrived_at, _origin_where(entry.channel))
            for entry in running
            if entry.arrived_at is not None
        )
        earlier = [one for one in found if one[0] < self._received_at]
        return max(earlier, key=lambda one: one[0]) if earlier else None

    # --- the place window (ADR-0276 §3) ---

    def _window_items(self, placed: _Placed) -> list[tuple[str, list[str]]]:
        """The place window's items, each under its ``H`` label, minted into the tables."""
        minted: list[tuple[str, _PlacedItem]] = []
        for one in placed.items:
            label = self._mint("H")
            self.labels[label] = one.item.referent
            # ADR-0303 §7:4: an item that links to an activation is a story label for it.
            if one.link is not None:
                self.story_members[label] = StoryMember(
                    kind=StoryMemberKind.ACTIVATION, id=one.link
                )
            minted.append((label, one))
        by_position = {
            one.item.position: label for label, one in minted if one.item.position is not None
        }
        return [(label, self._item(label, one, by_position)) for label, one in minted]

    def _item(self, label: str, one: _PlacedItem, by_position: Mapping[int, str]) -> list[str]:
        """One item under its label, with its episode's understanding where it is one exchange.

        ADR-0353 §2:4: an episode the episode window holds that is one exchange with this
        item is rendered once, here, as this item, with its latest understanding attached:
        of several items that are one exchange, the first carries it.

        It carries ``outside="yes"`` where its words are outside by its record (§3:7): a
        forward's or a claimed author's, by the message's own record, or a message of an
        input that episode's latest understanding marks relayed, where the mark counts
        (ADR-0351 §5:7, §5:11). It keeps its ``message`` tag and its writer, since an item
        is one message as the medium holds it, attributed by its record (§3:2, ADR-0351
        §5:5): the relay mark changes no party (§5:8). An item that is one exchange with
        no episode the pass holds has no relay mark to read, and renders by its record.
        """
        item = one.item
        attributes = [("label", label)]
        if item.deleted:
            return [_tag("message", [*attributes, ("deleted", "yes")], None)]
        attributes.append(("from", self._item_writer(item)))
        if item.at is not None:
            attributes.append(("at", self._at(item.at)))
        projection = (
            None
            if one.also is None
            else _ProjectedEpisode.of(
                one.also, excerpt_chars=self._excerpt_chars, admit_outside_input=False
            ).projection
        )
        if item.outside or (projection is not None and _relayed_message(item, projection)):
            attributes.append(("outside", "yes"))
        if item.replies_to is not None and (answered := by_position.get(item.replies_to)):
            attributes.append(("replies_to", answered))
        if item.cut:
            attributes.append(("cut", "yes"))
        if item.after:
            # ADR-0293 §6: written after the stimulus's first message, by its position.
            attributes.append(("after_stimulus", "yes"))
        lines = [_tag("message", attributes, item.text)]
        if projection is not None and one.annotated and projection.meaning is not None:
            lines.append(_understood(projection.meaning, projection.unclear))
        return lines

    def _item_writer(self, item: _ChannelItem) -> str:
        """Who wrote an item, by its record, never by its text (ADR-0293 §6:5, §4:3)."""
        if item.forward is not None:
            return self._naming.forward(item.forward)
        if item.claimed:
            return _UNKNOWN
        if item.author is MessageAuthor.ASSISTANT:
            return _SYSTEM
        if item.author is MessageAuthor.USER:
            return self._naming.who
        # ADR-0274 §5:4, ADR-0276 §3:6: a source label the channel supplied establishes no
        # writer, so it is named as claimed, however it reads.
        return _UNKNOWN if item.source is None else f"{item.source}, as claimed"

    def _knowledge_note(self, window: ChannelWindow, *, remembered: bool) -> str:
        """Origin knowledge's note where it renders nothing (§8:1)."""
        name = _line(_origin_name(self._channel))
        if remembered:
            return (
                f"{_NOT_PROVIDED}: {name} gives the system no history of this chat, so what "
                "the system remembers of it is under stimulus origin memory."
            )
        if isinstance(window, TranscriptWindow) and self._channel.channel_type == "conversation":
            return f"{_NOTHING_THERE}: this conversation has just started."
        return f"{_NOTHING_SHOWN}: the origin supplied nothing around this stimulus."

    def _origin_memory_note(
        self, window: ChannelWindow, episodes: Sequence[EpisodicMemory] | None, *, remembered: bool
    ) -> str:
        """Origin memory's note where it renders nothing (§8:1)."""
        if episodes is None and not remembered:
            return f"{_NOT_HELD}: the system's memory of this origin is not read for this stimulus."
        if (
            isinstance(window, TranscriptWindow)
            and self._channel.channel_type == "conversation"
            and not window.messages
            and not window.replied_to
        ):
            return f"{_NOTHING_THERE}: this conversation has just started."
        return f"{_NOTHING_SHOWN}: the system remembers nothing else of this origin to show here."

    # --- concurrent stimuli (ADR-0349 §5, ADR-0353 §2:5-§2:7) ---

    def _concurrent(self, running: Sequence[InProgressEntry], more: int) -> list[str]:
        """Each running activation under its ``R`` label, newest first, and how many more."""
        if not running:
            if self._naming.person_id is None:
                return [
                    f"{_NOT_HELD}: concurrent stimuli are shown only for a stimulus that is a "
                    "person's."
                ]
            return [f"{_NOTHING_SHOWN}: no other stimulus is running that can be shown here."]
        lines: list[str] = []
        for entry in running:
            label = self._mint("R")
            tags = [self._entry_input(one) for one in _entry_inputs(entry)]
            attributes = [("label", label), ("origin", _origin_name(entry.channel))]
            if entry.arrived_at is not None:
                attributes.append(("at", self._at(entry.arrived_at)))
            attributes.append(("acted", "yes" if entry.acted else "no"))
            if entry.outside:
                attributes.append(("outside", "yes"))
            lines.extend(_container("stimulus", attributes, tags))
            self.running[label] = entry.activation_id
            shown = " ".join(one.brief for one in _entry_inputs(entry) if one.brief is not None)
            self.labels[label] = UnderstandingReferent(
                kind="running",
                id=episode_address(entry.activation_id),
                source=_channel_text(entry.channel),
                excerpt=_excerpt(shown),
            )
            self.story_members[label] = StoryMember(
                kind=StoryMemberKind.ACTIVATION, id=entry.activation_id
            )
        if more:
            lines.append(f"{more} more are running, older than those above, and are not shown.")
        return lines

    def _entry_input(self, one: EntryInput) -> str:
        """One input of a concurrent stimulus: its brief, or the empty marker (§2:7)."""
        attributes = [("from", self._naming.parties(one.parties))]
        if one.brief is None:
            attributes.append(("withheld", "yes"))
        return _tag(_words_tag(one.parties, relayed=one.relayed), attributes, one.brief)

    # --- always in mind (ADR-0338 §7:2, ADR-0353 §4:5) ---

    def _always_in_mind(self, person: PersonBlock | None) -> list[str]:
        """Who the person is to the system, three of their fields, and what they pinned."""
        if person is None:
            if self._naming.person_id is None:
                return [f"{_NOT_HELD}: this stimulus is no person's, so none is kept in mind."]
            return [f"{_NOT_HELD}: no profile or pinned memory is read for this stimulus."]
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
        ]
        for memory in person.pinned:
            label = self._mint("M")
            lines.append(f"- {self._fact(label, memory, pinned=True)}")
            self.labels[label] = UnderstandingReferent(
                kind="memory", id=memory.id, source="memory", excerpt=_excerpt(memory.content)
            )
        if not person.pinned:
            lines.append(f"- {_upper(who)} has pinned nothing for the system to keep in mind.")
        return lines

    def _fact(self, label: str, memory: Memory, *, pinned: bool = False, cut: bool = False) -> str:
        """A remembered fact under its ``M`` label, attributed by its band (ADR-0281 §7:3)."""
        who = self._naming.who
        kind = {
            BeliefBand.ASSERTED: f"something {who} said",
            BeliefBand.DERIVED: "something the system worked out",
            # Not "a connected source": the band also holds a memory resting on the
            # system's own message (ADR-0328 §4, §6), which no integration reported.
            BeliefBand.ATTESTED: f"something from a source, never something {who} said",
        }[memory.band]
        attributes = [("label", label), ("from", _SYSTEM)]
        if pinned:
            attributes.append(("pinned", "yes"))
        attributes.extend([("kind", kind), ("learned", self._at(memory.transaction_time))])
        if cut:
            attributes.append(("cut", "yes"))
        text, _ = (memory.content, False) if not cut else _cut(memory.content, self._excerpt_chars)
        return _tag("memory", attributes, text)

    # --- short-term memory, and a stimulus in memory ---

    def _remembered(
        self, record: EpisodicMemory, *, admit_outside: bool, letter: str = "P"
    ) -> list[str]:
        """One episode as a stimulus in memory, under its label (ADR-0284 §8, ADR-0353 §3:3)."""
        label = self._mint(letter)
        projected = _ProjectedEpisode.of(
            record, excerpt_chars=self._excerpt_chars, admit_outside_input=admit_outside
        )
        self.labels[label] = projected.referent()
        _member_of(record, label, self.story_members)
        return self._stimulus_in_memory(projected.projection, label)

    def _stimulus_in_memory(self, projection: EpisodeProjection, label: str | None) -> list[str]:
        """A stimulus in memory: what it took in, how it was understood, what was sent."""
        attributes: list[tuple[str, str]] = [] if label is None else [("label", label)]
        if projection.channel is not None:
            attributes.append(("origin", _origin_name(projection.channel)))
        elif projection.capture_modality is not None:
            attributes.append(("origin", f"a {projection.capture_modality.value} capture"))
        attributes.append(("at", self._at(projection.occurred_at)))
        if projection.status is not None and parties_are_outside(
            projection.parties, relayed=projection.relayed
        ):
            attributes.append(("outside", "yes"))
        tags = self._taken_in(projection)
        if projection.meaning is not None:
            tags.append(_understood(projection.meaning, projection.unclear))
        tags.extend(_response(projection))
        return _container("stimulus", attributes, tags)

    def _taken_in(self, projection: EpisodeProjection) -> list[str]:
        """What a stimulus in memory took in, by its parties: its text, or the empty marker."""
        tags: list[str] = []
        parties = projection.parties
        words = [("from", self._naming.parties(parties))]
        shown = projection.input
        if shown is None:
            if projection.status is not None:
                tags.append(
                    _tag(
                        _words_tag(parties, relayed=projection.relayed),
                        [*words, ("withheld", "yes")],
                        None,
                    )
                )
        else:
            if shown.cut:
                words.append(("cut", "yes"))
            tags.append(_tag(_words_tag(parties, relayed=projection.relayed), words, shown.text))
        return tags

    def _short_term_note(self, episodes: Sequence[EpisodicMemory] | None) -> str:
        """Short-term memory's note where it renders nothing (§8:1)."""
        if episodes is None:
            return f"{_NOT_HELD}: recent stimuli are not read for a stimulus from this origin."
        return f"{_NOTHING_SHOWN}: no other recent stimulus is shown here."

    # --- recalled memories (ADR-0281 §7, ADR-0338 §7:7) ---

    def _recalled(
        self,
        recall: ActivationRecall | None,
        recalled: Sequence[EpisodicMemory | Memory],
        placed: _Placed,
        person: PersonBlock | None,
    ) -> list[str]:
        """What recall kept that no other section renders, labelled ``M`` after always in mind."""
        if recall is None:
            return [f"{_NOT_HELD}: memories are not recalled for this stimulus."]
        if recall.outcome in {RecallOutcome.FAILED, RecallOutcome.TIMED_OUT}:
            return [f"{_UNREADABLE}: recall failed, so no memory is shown, though some may exist."]
        if recall.outcome is RecallOutcome.NOTHING_FOUND:
            return [f"{_NOTHING_SHOWN}: recall found no memory for this stimulus."]
        shown = placed.shared | {record.id for record in placed.episodes} | _pinned_ids(person)
        lines: list[str] = []
        for record in (record for record in recalled if record.id not in shown):
            if isinstance(record, EpisodicMemory):
                # ADR-0284 §8:5: recalled episodes are the other rendering that admits an
                # outside input's text.
                lines.extend(self._remembered(record, admit_outside=True, letter="M"))
            else:
                label = self._mint("M")
                cut = len(record.content) > self._excerpt_chars
                lines.append(self._fact(label, record, cut=cut))
                fact, _ = _cut(record.content, self._excerpt_chars)
                self.labels[label] = UnderstandingReferent(
                    kind="memory", id=record.id, source="memory", excerpt=_excerpt(fact or "")
                )
        if lines:
            return lines
        if recalled:
            return [f"{_NOTHING_SHOWN}: everything recall found is already shown above."]
        return [f"{_NOTHING_SHOWN}: what recall found is no longer in memory."]

    # --- matters (ADR-0300 §6, ADR-0303 §3, ADR-0305 §4) ---

    def _matters(self, stories: Candidates | None) -> list[str]:
        """The candidate stories, each as its short view under its ``S`` label (§6:5).

        Each ``S`` label resolves twice: in ``belongs_to`` to its story member (§6:7), and
        in ``cites`` to a ``story`` referent (ADR-0304 §8:1).
        """
        if stories is None:
            return [f"{_NOT_HELD}: matters are not read for this stimulus."]
        if stories.unreadable:
            return [
                f"{_UNREADABLE}: the matters could not be read, so none is shown, though some "
                "may exist."
            ]
        lines: list[str] = []
        for view in stories.views:
            label = self._mint("S")
            lines.extend(self._matter(label, view))
            self.labels[label] = _story_referent(view)
            self.story_members[label] = StoryMember(kind=StoryMemberKind.STORY, id=view.story_id)
        return lines or [f"{_NOTHING_SHOWN}: no matter is found for what is shown here."]

    def _matter(self, label: str, view: ShortView) -> list[str]:
        """One matter: its summary, its pending notes, its latest stimuli as their meaning.

        A summary and a note are attributed by their records, and marked outside by the
        record's mark, never by their text (ADR-0303 §3:4, §3:7). A withheld summary is
        said to be, with nothing of it (ADR-0304 §4:2); on a pass that may not be shown a
        note, nothing about its notes renders (ADR-0305 §4:1).
        """
        tags: list[str] = []
        if view.withheld:
            tags.append(_tag("summary", [("from", _SYSTEM), ("withheld", "yes")], None))
        elif view.lines:
            summary = [("from", _SYSTEM)]
            if view.outside:
                summary.append(("outside", "yes"))
            tags.append(_tag("summary", summary, "\n".join(one.text for one in view.lines)))
        if not view.notes_withheld:
            tags.extend(self._note(note) for note in view.notes)
        for record in view.episodes:
            projection = _ProjectedEpisode.of(
                record, excerpt_chars=self._excerpt_chars, admit_outside_input=False
            ).projection
            if projection.meaning is not None:
                tags.append(
                    _tag(
                        "latest",
                        [("from", _SYSTEM), ("at", self._at(projection.occurred_at))],
                        projection.meaning,
                    )
                )
        return _container("matter", [("label", label)], tags)

    def _note(self, note: StoryNote) -> str:
        """One pending note, by who wrote it and its mark, never by its text (§3:7)."""
        writer = self._naming.who if note.author is StoryNoteAuthor.OWNER else _SYSTEM
        attributes = [("from", writer), ("at", self._at(note.written_at))]
        if note.outside:
            attributes.append(("outside", "yes"))
        return _tag("note", attributes, note.text)


def _understood(meaning: str, unclear: Sequence[UnclearPoint]) -> str:
    """A stored understanding, from the system: its meaning, then what it left unclear.

    The text of a record stays as it was written (ADR-0353 §5:4).
    """
    parts = [meaning]
    for point in unclear:
        readings = "; or ".join(point.readings)
        parts.append(f"Unclear: {point.gap} It could mean: {readings}")
    return _tag("understood", [("from", _SYSTEM)], "\n".join(parts))


def _response(projection: EpisodeProjection) -> list[str]:
    """What the system sent back, with how the stimulus ended (ADR-0284 §8:6, §3:8).

    Where nothing was sent, an empty ``response`` still says how it ended.
    """
    ended = _ended(projection)
    attributes: list[tuple[str, str]] = [("from", _SYSTEM)]
    if ended is not None:
        attributes.append(("ended", ended))
    if projection.response is not None:
        if projection.response.cut:
            attributes.append(("cut", "yes"))
        return [_tag("response", attributes, projection.response.text)]
    return [] if ended is None else [_tag("response", attributes, None)]


def _at_origin(record: EpisodicMemory, channel: ChannelIdentity) -> bool:
    """Whether an episode was recorded at the stimulus's origin, its own channel (§2:2)."""
    processing = record.processing_record
    return processing is not None and processing.trigger.channel == channel


def _known_parties(messages: Sequence[RecordedInputMessage]) -> tuple[SupportHolder, ...] | None:
    """An input's parties from its messages: their distinct parties, or ``None`` unknown."""
    if any(one.party is None for one in messages):
        return None
    return tuple(dict.fromkeys(one.party for one in messages if one.party is not None))


def _entry_inputs(entry: InProgressEntry) -> tuple[EntryInput, ...]:
    """A concurrent stimulus's inputs; one built from its trigger's where none is recorded."""
    if entry.inputs:
        return entry.inputs
    return (EntryInput(brief=entry.input, parties=entry.parties),)


# --- the channel window ------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _PlacedItem:
    """One item of the place window, what it shares with the episode window, its link.

    ``annotated`` is whether this item carries its episode's understanding. Several
    transcript messages can be one exchange — the user's message an activation took in
    and the reply it wrote — and that exchange is rendered once (ADR-0276 §3): the first
    of them in rendering order carries its understanding.
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
    """One item of the place window, with the referent its label resolves to.

    What it renders is held as the record gives it — who wrote it, when, its words, what
    it replies to — and named only when the message is rendered, by the pass's naming.

    ``link`` is the activation the item links to by its own record (ADR-0303 §7:1): a
    transcript message's, as the reader's bookkeeping records it. A supplied item has
    none of its own, and links only where it is one exchange with an episode of the
    episode window (§1:1). ``position`` is a transcript message's place in its
    conversation, the medium's own item id (ADR-0303 §7:2), and what orders the window
    newest first.
    """

    identifier: str | None
    referent: UnderstandingReferent
    link: str | None = None
    position: int | None = None
    text: str | None = None
    at: datetime | None = None
    author: MessageAuthor | None = None
    source: str | None = None
    forward: ClaimedAuthor | None = None
    claimed: bool = False
    replies_to: int | None = None
    cut: bool = False
    deleted: bool = False
    after: bool = False

    @property
    def outside(self) -> bool:
        """Whether its words are outside by its record: a forward's, or a claimed author's."""
        return self.forward is not None or self.claimed

    def linked(self, also: EpisodicMemory | None) -> str | None:
        """The activation the item links to, where it links to one (ADR-0303 §7:1, §7:3).

        Its own record's, or, for a supplied item that is one exchange with an episode
        of the episode window, that episode's (ADR-0301 §1:1). Read off the records the
        pass already holds: nothing is fetched (ADR-0301 §1:4).
        """
        if self.link is not None:
            return self.link
        return None if also is None else activation_of(also)


def _relayed_message(item: _ChannelItem, projection: EpisodeProjection) -> bool:
    """Whether ``item`` is a message of an input its episode marks relayed (ADR-0351 §5:7).

    The relay mark is read off the episode's latest understanding version, as the
    projection carries it (§5:11, §8:4), and counts only where the input's parties are
    the person's own or the assistant's. A message the system wrote is the exchange's
    reply, never its input, and is never relayed.
    """
    return item.author is not MessageAuthor.ASSISTANT and relay_mark_counts(
        projection.parties, relayed=projection.relayed
    )


def _channel_items(window: ChannelWindow) -> list[_ChannelItem]:
    """The channel window's items in supplied order (§3)."""
    if isinstance(window, SuppliedWindow):
        supplied = list(window.context.history)
        if window.context.reply_to is not None:
            supplied.append(window.context.reply_to)
        return [_supplied_item(item) for item in supplied]
    return _transcript_items(window)


def _supplied_item(item: ChannelContextItem) -> _ChannelItem:
    """A supplied item is not a record: it passes as supplied, attributed by its source."""
    return _ChannelItem(
        identifier=item.item_id,
        referent=UnderstandingReferent(
            kind="channel_item",
            id=item.item_id,
            source=item.source,
            excerpt=_excerpt(item.text or ""),
        ),
        text=item.text,
        source=item.source,
    )


def _transcript_items(window: TranscriptWindow) -> list[_ChannelItem]:
    """The chat's window, its recent messages then those the input replies to (§6:4).

    An item written after the earliest message of the input says so, so the activation
    can tell that a message was written before the reply it follows (ADR-0293 §6).
    """
    first = min((one.position for one in window.input_messages), default=None)
    items = [_message_item(one, window, first) for one in window.messages]
    items.extend(_message_item(one, window, first) for one in window.replied_to)
    return items


def _message_item(
    message: TranscriptMessage | LineMessage | DeletedMessage,
    window: TranscriptWindow,
    first: int | None,
) -> _ChannelItem:
    """One message of the transcript, as the medium holds it (ADR-0293 §5:2).

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
    link = window.links.get(message.position)
    referent = UnderstandingReferent(
        kind="channel_item",
        id=f"message:{message.position}",
        source=_channel_text(window.conversation),
        excerpt="" if isinstance(message, DeletedMessage) else _excerpt(message.text),
    )
    identifier = None if link is None else episode_address(link)
    if isinstance(message, DeletedMessage):
        return _ChannelItem(
            identifier=identifier,
            referent=referent,
            link=link,
            position=message.position,
            deleted=True,
        )
    return _ChannelItem(
        identifier=identifier,
        referent=referent,
        link=link,
        position=message.position,
        text=message.text,
        at=message.written_at,
        author=message.author,
        forward=window.forwarded.get(message.position),
        claimed=message.position in window.claimed,
        replies_to=message.replies_to,
        cut=message.cut_off,
        after=first is not None and message.position > first,
    )


# --- the episode window ------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _ProjectedEpisode:
    """One episode as ADR-0284 §8's projection shows it — never a serialization of it.

    Every field rendered is a field of the projection, and no other field of the stored
    episode is read (§8:3). Who the input came from is the projection's parties, never
    the episode's channel type (§2:3).
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


def _pinned_ids(person: PersonBlock | None) -> frozenset[str]:
    """The ids of the memories always in mind shows, none where it renders none."""
    return frozenset() if person is None else frozenset(one.id for one in person.pinned)


# --- validation and resolution ---------------------------------------------------

#: What each label sequence names, as the repair statement says it.
_SEQUENCES: Final = (
    ("H", "the origin's messages"),
    ("R", "the concurrent stimuli"),
    ("M", "always in mind and the recalled memories"),
    ("P", "the stimuli in memory"),
    ("S", "the matters"),
)


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
    rendered = [_sequence(letter, brief.counts.get(letter, 0), name) for letter, name in _SEQUENCES]
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
        return f"no {prefix} labels ({name})"
    if count == 1:
        return f"{prefix}1 ({name})"
    return f"{prefix}1 to {prefix}{count} ({name})"


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
    relayed: bool = False,
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

    ``relayed`` is copied from the reply as the version's relay mark on the trigger's
    input (ADR-0351 §5:6, §5:10), and recorded wherever ``relayed`` says an earlier
    version of the activation marked it, whatever the reply says: the mark holds for the
    rest of the activation, and only lowers (§5:8, §5:9).
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
        relayed=proposal.relayed or relayed,
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


def _story_referent(view: ShortView) -> UnderstandingReferent:
    """What an ``S`` label cited in ``cites`` resolves to (ADR-0304 §8:1, ADR-0353 §9:4).

    The story's id as the story store gave it, and as excerpt the first line of its
    summary as the short view rendered it, cut on ADR-0276 §2:5's rule — empty where
    the view rendered no line, a withheld summary included. Nothing resolves the id on
    read: a story since merged is a dangling id, an ordinary state.
    """
    shown: tuple[StorySummaryLine, ...] = () if view.withheld else view.lines
    return UnderstandingReferent(
        kind="story",
        id=view.story_id,
        source="story",
        excerpt=_excerpt(shown[0].text) if shown else "",
    )


def _within(deadline: float) -> None:
    """Refuse to start a completion once the pass's deadline has passed (ADR-0276 §5).

    The engine's timer bounds every await, but fires only when the loop gets control;
    this is the check at the two points a completion is about to be spent, so time
    crossed without yielding — rendering, validation — cannot buy one.
    """
    if deadline <= asyncio.get_running_loop().time():
        msg = "the pass's deadline passed before the understanding completion"
        raise TimeoutError(msg)


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
