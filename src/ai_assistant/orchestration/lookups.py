"""Planning's look-ups: memory and episode searches, a story or an episode whole, and more.

ADR-0307 §6:6: "Planning may look up for itself a memory search, the full view of any
story it has been shown, and pulls. Raw outside content reaches it only through
understanding's or a digest's record." Each look-up is a call planning chooses,
authorizing checks by rule and acting runs (ADR-0306 §3); acting reaches the runner,
:class:`LookUps`, through its own-records seam and never through ``ToolInvoker``
(§3:3), and awaits it to its end.

**Three parts, one module**, as :mod:`~ai_assistant.orchestration.story_calls` is: the
declarations (:data:`LOOK_UPS`), which of their arguments name things by label
(:data:`LOOK_UP_LABEL_ARGUMENTS`), and the runner.

| Call | Takes | Result |
| --- | --- | --- |
| :data:`SEARCH_MEMORY` | a query | may carry outside text |
| :data:`READ_STORY` | a story, by its ``S`` label; a page | no outside text, marks shown |
| :data:`FOLLOW_UP` | a result, by its ``R`` label; a new *looking for* | may carry outside text |
| :data:`SEARCH_EPISODES` | a query; a page | no outside text, marks shown |
| :data:`READ_EPISODE` | an episode, by its ``E`` label; a page | no outside text, marks shown |
| :data:`READ_OLDER_HISTORY` | a page | no outside text, marks shown |

Each declares the assistant's own records as its effect, as reading a story does
(ADR-0306 §3:1, ADR-0308 §6:6), never leaves the hub, never has an unknown outcome, is
safe to repeat, and writes nothing.

**The memory search** (ADR-0306 §3:4, §5:14-§5:16, ADR-0308 §6:2). It searches the
remembered facts, the semantic records, for its query, each band on its own and its
limit filled ``ASSERTED`` first, then ``ATTESTED``, then ``DERIVED`` (ADR-0072 §5), and
keeps what the pass's audience admits (``admitted_to_understanding``, ADR-0282 §2:8), as
recall's band searches do (ADR-0281 §3:2, §4). It routes what it kept record by record
by each record's stored source: the ids of the records whose source is not outside go to
planning, which fetches them by id, the audience predicate applied again, and shows each
under its ``M`` label; the ids of the records whose source is outside are held by acting
under the result's id (:class:`~ai_assistant.orchestration.acting.HeldByIds`), and reach
planning only through a digest answering the call's *looking for*, which fetches them by
id, the predicate applied again (ADR-0282 §2:4-§2:8). No raw outside text reaches
planning.

**The full view of a story** (ADR-0300 §10:5-§10:7, ADR-0307 §5:2). Planning names a
story it has been shown by its ``S`` label, which planning's own check maps to the id.
The view is the one planning is shown of each story the activation belongs to, read by
the phases' glue under the pass's audience and its owner-only placement (ADR-0307 §6:4);
it is read when the call runs and held by the call's decision for the glue, which shows
it under the call's result. A read of a story returns no outside text: its lines are the
user's or the assistant's words, each shown with its mark, and a marked line counts as
outside content for the reader (ADR-0300 §10:6).

**A read also shows the story's older notes** (#2893), those a tidy-up has taken in,
which no view shows otherwise, so a move or a split can name any note the story holds by
the label it is shown under (ADR-0307 §5:1, §5:5). They come newest first,
:data:`OLDER_NOTES_PAGE` at a time: a read naming no page shows the newest, and
:data:`OLDER_NOTES_PAGE_ARGUMENT` asks for a later one. On a pass that may not be shown a
record placed for the owner alone they are absent, as every story note is (ADR-0307
§6:4, ADR-0305 §4).

**The follow-up** (ADR-0308 §6:6-§6:7). Its one planner argument is a result's ``R``
label, which planning's check maps to the result's id, and its *looking for* carries the
new question. The runner answers the result it names
(:class:`~ai_assistant.orchestration.acting.NamedResult`); acting runs it against the
held results, so a digest answers the new question from the result as held, and naming a
result with nothing held comes back not done, with the reason.

**The episode look-ups** (ADR-0358 §6-§10): a search of past episodes, each found
shown as its short view with the matters it belongs to (§7, §8:1); one episode's full
record by its ``E`` label (§10); and the origin's older history (§9). Each is read by
:class:`~ai_assistant.orchestration.episode_lookups.EpisodeLookUpReads` when the call runs, under
the pass's audience, and held by the call's decision in the scope for the glue, which
shows it under the call's result, as a story read's view is. None returns raw outside
content: an outside episode is shown withheld, and a marked note, digested evidence or an
outside episode shown is outside content read (§6:4). A result longer than a page comes in
pages: the call names one by :data:`PAGE_ARGUMENT`, the first where it names none (§6:6).
Each is in the set offered on every round (ADR-0356 §4:3, ADR-0357 §9:1).

**What a look-up reads under.** The memory search and the story's view read under the
pass's audience, which a call does not carry, so the phases' glue opens a
:meth:`LookUps.scope` around acting for the round. A look-up run outside one reads
nothing and is not done.

**A candidate's lookup** (ADR-0329 §4:1-§4:2). Where ``remember`` records a candidate,
its runner asks :meth:`LookUps.similar` for the memories similar to the fact: one search
by relevance alone, no band searched on its own, under the same scope and the same
audience predicate as a memory search, keeping only the memories that do not rest on
outside content, which reach planning only through a digest and this lookup digests
nothing.

**It logs stage and code-owned reason only**, never a query, a record or a story
(ADR-0275 §8).
"""

from __future__ import annotations

import contextlib
import re
from collections.abc import Mapping
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final, Protocol

import structlog

from ai_assistant.core.errors import (
    ConversationStoreError,
    MemoryStoreError,
    PlanningError,
    StoryStoreError,
)
from ai_assistant.core.types import (
    BeliefBand,
    CapabilityEffect,
    CapabilityResult,
    CostBasis,
    DataTier,
    Idempotency,
    LabelKind,
    Memory,
    MemoryKind,
    Reversibility,
    RiskLevel,
    ToolCost,
    ToolDefinition,
    ToolFailure,
    ToolFailureKind,
    ToolOutcome,
    ToolResult,
    TranscriptMessage,
)
from ai_assistant.orchestration.acting import HeldByIds, NamedResult
from ai_assistant.orchestration.channel_kinds import CONNECTION_KINDS, place_of
from ai_assistant.orchestration.conversations import conversation_channel
from ai_assistant.orchestration.disclosure import admitted_to_understanding
from ai_assistant.orchestration.planning import (
    OLDER_NOTES_PAGE_ARGUMENT,
    PAGE_ARGUMENT,
    ConnectionsFound,
    ConnectionShown,
    EpisodeRead,
    EpisodesFound,
    OlderHistory,
)
from ai_assistant.orchestration.story_calls import STORY_ARGUMENT

if TYPE_CHECKING:
    from collections.abc import Iterator

    from ai_assistant.core.protocols import ConversationStore, MemoryStore
    from ai_assistant.core.types import FrozenJson, ToolCall
    from ai_assistant.orchestration.acting import OwnRecordsAnswer
    from ai_assistant.orchestration.disclosure import TurnSupply
    from ai_assistant.orchestration.episode_lookups import EpisodeLookUpReads, OlderSource
    from ai_assistant.orchestration.planning import PlanningStory

__all__ = [
    "EPISODE_ARGUMENT",
    "FOLLOW_UP",
    "FOLLOW_UP_CAPABILITY",
    "LOOK_UPS",
    "LOOK_UP_CAPABILITIES",
    "LOOK_UP_LABEL_ARGUMENTS",
    "OLDER_NOTES_PAGE",
    "OLDER_NOTES_PAGE_ARGUMENT",
    "PAGE_ARGUMENT",
    "QUERY_ARGUMENT",
    "QUERY_MAX_CHARS",
    "READ_EPISODE",
    "READ_EPISODE_CAPABILITY",
    "READ_OLDER_HISTORY",
    "READ_OLDER_HISTORY_CAPABILITY",
    "READ_STORY",
    "READ_STORY_CAPABILITY",
    "RECORDS_KEY",
    "RESULT_ARGUMENT",
    "SEARCH_CONNECTIONS",
    "SEARCH_CONNECTIONS_CAPABILITY",
    "SEARCH_EPISODES",
    "SEARCH_EPISODES_CAPABILITY",
    "SEARCH_MEMORY",
    "SEARCH_MEMORY_CAPABILITY",
    "ConnectionSearch",
    "EpisodeLookedUp",
    "LookUpScope",
    "LookUps",
    "StoryViews",
    "searched_ids",
]

_log = structlog.get_logger(__name__)

#: The capabilities, renamed by ADR-0364 §8:1. Each declaration keeps its id, the name it
#: was first declared under.
SEARCH_MEMORY_CAPABILITY: Final = "search_memories"
READ_STORY_CAPABILITY: Final = "read_matter"
FOLLOW_UP_CAPABILITY: Final = "reread_result"
SEARCH_EPISODES_CAPABILITY: Final = "search_episodes"
READ_EPISODE_CAPABILITY: Final = "read_episode"
READ_OLDER_HISTORY_CAPABILITY: Final = "read_origin_history"
#: ADR-0364 §3:7: the connections search, new.
SEARCH_CONNECTIONS_CAPABILITY: Final = "search_connections"

#: Each look-up's declaration id: its capability's name before ADR-0364 §8:1 renamed it.
_IDS: Final[Mapping[str, str]] = {
    SEARCH_MEMORY_CAPABILITY: "search_memory",
    READ_STORY_CAPABILITY: "read_story",
    FOLLOW_UP_CAPABILITY: "follow_up",
    READ_OLDER_HISTORY_CAPABILITY: "read_older_history",
}

#: The episode look-up's one planner argument: the episode, by its ``E`` label.
EPISODE_ARGUMENT: Final = "episode"

#: The memory search's one argument: what to search for.
QUERY_ARGUMENT: Final = "query"

#: The follow-up's one planner argument: the result it asks about, by its ``R`` label.
RESULT_ARGUMENT: Final = "result"

#: How many of a story's older notes one page of a story read shows (#2893).
OLDER_NOTES_PAGE: Final = 10

#: The longest query a memory search takes.
QUERY_MAX_CHARS: Final = 500

#: The key a memory search's result lists, for planning, the ids of the records whose
#: source is not outside under.
RECORDS_KEY: Final = "records"

#: The key a story read's result names the story read under.
_STORY_KEY: Final = "story"

_NOT_IN_SCOPE: Final = "a look-up reads under the pass's audience, and none was given"

#: ADR-0072 §5's consumer-side precedence, the order the bands are searched in.
_BANDS: Final = (BeliefBand.ASSERTED, BeliefBand.ATTESTED, BeliefBand.DERIVED)

#: The episode look-ups (ADR-0358 §7-§10), which read through the episode reads.
_EPISODE_LOOK_UPS: Final = frozenset(
    {SEARCH_EPISODES_CAPABILITY, READ_EPISODE_CAPABILITY, READ_OLDER_HISTORY_CAPABILITY}
)

#: The argument each episode look-up that names something names it by, and what it says
#: where the call names nothing.
_NAMED: Final = {
    SEARCH_EPISODES_CAPABILITY: QUERY_ARGUMENT,
    READ_EPISODE_CAPABILITY: EPISODE_ARGUMENT,
}
_UNNAMED: Final = {
    SEARCH_EPISODES_CAPABILITY: "the query is blank",
    READ_EPISODE_CAPABILITY: "the call names no episode",
    READ_OLDER_HISTORY_CAPABILITY: "the call names nothing",
}

#: The key an episode look-up's result names what it looked up under; what it read is
#: held in the scope and shown in its place.
_LOOKED_UP_KEY: Final = "looked_up"


def _declared(
    capability: str,
    description: str,
    *,
    properties: Mapping[str, FrozenJson],
    required: tuple[str, ...],
    result: CapabilityResult,
) -> ToolDefinition:
    """One look-up's declaration, the class's five properties as ADR-0306 §3 rules them.

    - ``effect=OWN_RECORDS``, ``leaves_hub=False``, ``outcome_can_be_unknown=False`` and
      ``safe_to_repeat=True``: a read of the assistant's own records, declared with the
      class's effect as reading a story is (ADR-0306 §3:1, ADR-0308 §6:6), so acting
      runs it directly against the store and claims no effect record.
    - ``side_effecting=True`` with ``writes=()``: ADR-0306 §2:5 requires it of an effect
      that is not none; nothing is written.
    - ``reversibility=REVERSIBLE``: a read changes nothing to undo.
    - ``reads=(PERSONAL,)``: the assistant's records of the user.
    - ``risk_level=LOW``, ``discloses=()``, ``cost=FREE``, ``idempotency=NATURAL``:
      nothing leaves the device, nothing is spent, and a read twice is the same read.
    """
    return ToolDefinition(
        id=_IDS.get(capability, capability),
        capability=capability,
        description=description,
        risk_level=RiskLevel.LOW,
        reversibility=Reversibility.REVERSIBLE,
        side_effecting=True,
        reads=(DataTier.PERSONAL,),
        writes=(),
        discloses=(),
        cost=ToolCost(basis=CostBasis.FREE),
        idempotency=Idempotency.NATURAL,
        effect=CapabilityEffect.OWN_RECORDS,
        leaves_hub=False,
        result=result,
        outcome_can_be_unknown=False,
        safe_to_repeat=True,
        parameters_schema={
            "type": "object",
            "properties": dict(properties),
            "required": list(required),
            "additionalProperties": False,
        },
    )


SEARCH_MEMORY: Final = _declared(
    SEARCH_MEMORY_CAPABILITY,
    (
        "Search the system's memories, what it has learned, for a query.\n"
        "\n"
        "Memories that rest on what a source reported are read for you against looking_for; the "
        "rest are shown as they are.\n"
        "\n"
        "outcome: done | not done | unknown | refused\n"
        "because: why, with not done, unknown or refused\n"
        "result: with done, under its R label:\n"
        "  remembered: the memories found, best first, each as long-term memory shows one, or "
        "none\n"
        "  resting_on_outside_content: where some found rest on what a source reported, that they "
        "were read for you\n"
        "evidence: with those, what was read of them for looking_for\n"
        "\n"
        "It changes nothing."
    ),
    properties={
        QUERY_ARGUMENT: {
            "type": "string",
            "minLength": 1,
            "maxLength": QUERY_MAX_CHARS,
            "description": "What to search for, in a few words.",
        },
    },
    required=(QUERY_ARGUMENT,),
    result=CapabilityResult.MAY_CARRY_OUTSIDE_TEXT,
)
"""Search memory (ADR-0306 §3:4, ADR-0307 §6:6): its result may carry outside text, so
it is offered with a required *looking for* (§2:9) and routed record by record (§5:16)."""

READ_STORY: Final = _declared(
    READ_STORY_CAPABILITY,
    (
        "Read the full view of a matter you were shown.\n"
        "\n"
        "outcome: done | not done | unknown | refused\n"
        "because: why, with not done, unknown or refused\n"
        "result: with done, under its R label, the matter as matters are shown, in full: its "
        "summary, its notes, its episodes since it was last tidied and its latest ones, the "
        "larger matters it is part of, and where it stands; its older notes a page at a time, "
        "newest first\n"
        "\n"
        "It changes nothing."
    ),
    properties={
        STORY_ARGUMENT: {
            "type": "string",
            "minLength": 1,
            "description": "The matter, by its S label.",
        },
        OLDER_NOTES_PAGE_ARGUMENT: {
            "type": "integer",
            "minimum": 1,
            "description": "Which page of its older notes to show. Left out: 1, the newest.",
        },
    },
    required=(STORY_ARGUMENT,),
    result=CapabilityResult.NO_OUTSIDE_TEXT,
)
"""Read a story's page (ADR-0300 §10's table, §10:6): it returns no outside text and
shows its marks (ADR-0306 §3:1)."""

FOLLOW_UP: Final = _declared(
    FOLLOW_UP_CAPABILITY,
    (
        "Ask a new question of a result that was read for you.\n"
        "\n"
        "The result as it came back is read again for it; nothing is called again.\n"
        "\n"
        "outcome: done | not done | unknown | refused\n"
        "because: why, with not done, unknown or refused\n"
        "evidence: with done, what was read of it for the new looking_for\n"
        "\n"
        "It changes nothing."
    ),
    properties={
        RESULT_ARGUMENT: {
            "type": "string",
            "minLength": 1,
            "description": "The result, by its R label.",
        },
    },
    required=(RESULT_ARGUMENT,),
    result=CapabilityResult.MAY_CARRY_OUTSIDE_TEXT,
)
"""The follow-up (ADR-0308 §6:6): one planner argument, a result's R label, and the
*looking for* the hub adds carries the new question."""


def _page(description: str) -> dict[str, FrozenJson]:
    """A look-up's page argument, its description its own (ADR-0364 §5:2)."""
    return {"type": "integer", "minimum": 1, "description": description}


SEARCH_EPISODES: Final = _declared(
    SEARCH_EPISODES_CAPABILITY,
    (
        "Search past episodes, each the record of the work on an earlier stimulus, for a query.\n"
        "\n"
        "outcome: done | not done | unknown | refused\n"
        "because: why, with not done, unknown or refused\n"
        "result: with done, under its R label:\n"
        "  page: the page shown\n"
        "  episodes: those found, best first, each as short-term memory shows one, with "
        "in_matters, the matters it belongs to by S label; or none\n"
        "  more: the next page, where there is one\n"
        "\n"
        "It changes nothing."
    ),
    properties={
        QUERY_ARGUMENT: {
            "type": "string",
            "minLength": 1,
            "maxLength": QUERY_MAX_CHARS,
            "description": "What to search for, in a few words.",
        },
        PAGE_ARGUMENT: _page("Which page to show. Left out: 1, the first."),
    },
    required=(QUERY_ARGUMENT,),
    result=CapabilityResult.NO_OUTSIDE_TEXT,
)
"""Search past episodes (ADR-0358 §7): each episode found as its short view, outside
content withheld, so its result carries no outside text and shows its marks."""

READ_EPISODE: Final = _declared(
    READ_EPISODE_CAPABILITY,
    (
        "Read one episode: a past one's full record, or what one still running has found and done "
        "so far.\n"
        "\n"
        "Records it shows again are shown as they are held now.\n"
        "\n"
        "outcome: done | not done | unknown | refused\n"
        "because: why, with not done, unknown or refused\n"
        "result: with done, under its R label:\n"
        "  for a past one, a page of its full record:\n"
        "    label, at, input, understood_then, response and how it ended, on every page\n"
        "    in_matters: the matters it belongs to, by S label\n"
        "    page, and parts: in the order they happened: each understanding, what recall found, "
        "each round's notes, each call with its arguments, what came of it and what it showed, "
        "the evidence, and what it took in\n"
        "    more: the next page, where there is one\n"
        "  for one still running: what it has found and done so far, as an episode, with status: "
        "running, or ended\n"
        "\n"
        "It changes nothing."
    ),
    properties={
        EPISODE_ARGUMENT: {
            "type": "string",
            "minLength": 1,
            "description": "The episode, by its E label.",
        },
        PAGE_ARGUMENT: _page("Which page of a past one's record to show. Left out: 1, the first."),
    },
    required=(EPISODE_ARGUMENT,),
    result=CapabilityResult.NO_OUTSIDE_TEXT,
)
"""Read an episode's full record (ADR-0358 §10): outside content shown only through its
digests or withheld, and marked parts shown marked, so its result carries no outside
text and shows its marks."""

READ_OLDER_HISTORY: Final = _declared(
    READ_OLDER_HISTORY_CAPABILITY,
    (
        "Read the stimulus origin's history older than you were shown.\n"
        "\n"
        "outcome: done | not done | unknown | refused\n"
        "because: why, with not done, unknown or refused\n"
        "result: with done, under its R label:\n"
        "  page: the page shown, newest first\n"
        "  items: its older items, as stimulus origin knowledge shows them; or episodes: its "
        "earlier episodes, each as short-term memory shows one\n"
        "  more: the next page, where there is one\n"
        "\n"
        "It changes nothing."
    ),
    properties={PAGE_ARGUMENT: _page("Which page to show. Left out: 1, the newest.")},
    required=(),
    result=CapabilityResult.NO_OUTSIDE_TEXT,
)
"""Read the origin's older history (ADR-0358 §9): each item as the place window shows
one, someone else's withheld, so its result carries no outside text."""

SEARCH_CONNECTIONS: Final = _declared(
    SEARCH_CONNECTIONS_CAPABILITY,
    (
        "Search the system's connections for a query, beyond those Connections shows.\n"
        "\n"
        "outcome: done | not done | unknown | refused\n"
        "because: why, with not done, unknown or refused\n"
        "result: with done, under its R label:\n"
        "  page: the page shown\n"
        "  connections: those found, best first, each as Connections shows one, or none\n"
        "  more: the next page, where there is one\n"
        "\n"
        "It changes nothing."
    ),
    properties={
        QUERY_ARGUMENT: {
            "type": "string",
            "minLength": 1,
            "maxLength": QUERY_MAX_CHARS,
            "description": "What to search for, such as a name, a platform or what was said there.",
        },
        PAGE_ARGUMENT: _page("Which page to show. Left out: 1, the first."),
    },
    required=(QUERY_ARGUMENT,),
    result=CapabilityResult.NO_OUTSIDE_TEXT,
)
"""Search the connections (ADR-0364 §3:7-§3:8): a read of the system's own records, each
connection found shown as Connections shows one, so its result carries no outside
text."""

#: Every look-up's declaration.
LOOK_UPS: Final = (
    SEARCH_MEMORY,
    READ_STORY,
    FOLLOW_UP,
    SEARCH_EPISODES,
    READ_EPISODE,
    READ_OLDER_HISTORY,
    SEARCH_CONNECTIONS,
)

#: Every look-up's capability, in :data:`LOOK_UPS`' order.
LOOK_UP_CAPABILITIES: Final = tuple(str(one.capability) for one in LOOK_UPS)

#: Which of the look-ups' arguments name things by label (ADR-0307 §5:2), which
#: planning's check maps to ids or refuses whole (§5:3).
LOOK_UP_LABEL_ARGUMENTS: Final[Mapping[str, Mapping[str, LabelKind]]] = {
    READ_STORY_CAPABILITY: {STORY_ARGUMENT: LabelKind.STORY},
    FOLLOW_UP_CAPABILITY: {RESULT_ARGUMENT: LabelKind.RESULT},
    READ_EPISODE_CAPABILITY: {EPISODE_ARGUMENT: LabelKind.EPISODE},
}

type EpisodeLookedUp = EpisodesFound | EpisodeRead | OlderHistory | ConnectionsFound
"""What an episode look-up, or a connections search, read, held in the scope by its call's
decision (ADR-0358 §7-§10, ADR-0364 §3:7)."""


class ConnectionSearch:
    """``search_connections``' read of the hub's own records (ADR-0364 §3:7-§3:8).

    It finds the hub chat's conversations the Connections section does not show: every
    single-place connection is always shown (§3:5), so a many-place connection's places
    are what a search finds. A conversation matches a query by what its entry would
    show and by the text of its transcript, which the hub hosts, read through the
    conversation store's existing reads alone: its recent conversations, then each one's
    recent transcript. Best first, by how many of the query's words it holds, the more
    recent first among equals, a page at a time. It shows no text it matched against.
    """

    def __init__(self, *, conversations: ConversationStore, scan: int, page_size: int) -> None:
        """Wire the search to the conversation store.

        Args:
            conversations: The chat space, whose conversations are places.
            scan: How many of the most recent conversations one search reads.
            page_size: How many connections one page shows.

        Raises:
            ValueError: If either bound is below 1.
        """
        if scan < 1 or page_size < 1:
            msg = "a connections search reads one conversation and shows one at least"
            raise ValueError(msg)
        self._conversations = conversations
        self._scan = scan
        self._page_size = page_size

    async def search(self, query: str, page: int) -> ConnectionsFound:
        """One page of the conversations ``query`` matches, best first.

        Raises:
            ConversationStoreError: If the store cannot be read.
        """
        words = {one for one in re.findall(r"\w+", query.casefold()) if len(one) > 1}
        kind = CONNECTION_KINDS["conversation"]
        scored: list[tuple[int, int, ConnectionShown]] = []
        for order, one in enumerate(await self._conversations.recent(limit=self._scan)):
            transcript = await self._conversations.transcript(one.id)
            texts = [kind.is_a, kind.group or ""]
            if transcript is not None:
                texts.extend(
                    entry.text
                    for entry in transcript.entries
                    if isinstance(entry, TranscriptMessage)
                )
            held = " ".join(texts).casefold()
            score = sum(1 for word in words if word in held)
            if score:
                place = place_of(conversation_channel(one.id))
                scored.append((-score, order, ConnectionShown(place=place, kind=kind)))
        scored.sort(key=lambda one: (one[0], one[1]))
        start = (page - 1) * self._page_size
        shown = tuple(one for _, _, one in scored[start : start + self._page_size])
        return ConnectionsFound(
            page=page, connections=shown, more=len(scored) > start + self._page_size
        )


def searched_ids(output: object) -> tuple[str, ...]:
    """The ids a memory search's result lists for planning, or none where it lists none.

    Args:
        output: What the search's call returned for planning.

    Returns:
        The ids of the records whose source is not outside, in the order searched.
    """
    if not isinstance(output, Mapping):
        return ()
    ids = output.get(RECORDS_KEY)
    if not isinstance(ids, list | tuple):
        return ()
    return tuple(one for one in ids if isinstance(one, str))


class StoryViews(Protocol):
    """The full view of one story, as planning is shown it (ADR-0307 §6:1, §6:4).

    Structurally the phases' glue's ``StoryReads``, which reads the views of the stories
    the activation belongs to; a story read reads one by its id the same way.
    """

    async def view(
        self, story_id: str, *, audience: TurnSupply, owner_records: bool, older_page: int = 1
    ) -> PlanningStory | None:
        """One story's full view, under ``audience``, or ``None`` where it is not held.

        It shows the ``older_page``-th page of the story's older notes, newest first,
        where notes may be shown (#2893).

        Raises:
            StoryStoreError: If the story store cannot be read.
            PlanningError: If the plan store cannot be read.
            MemoryStoreError: If the story's episodes cannot be read.
        """
        ...


@dataclass
class LookUpScope:
    """What a round's look-ups read under, and the story views they read.

    Attributes:
        audience: The pass's audience posture, which the memory search and the story
            views are read under (ADR-0282 §2:8).
        owner_records: Whether a record placed for the owner alone may be shown on this
            pass, which decides a story view's summary and notes (ADR-0307 §6:4).
        views: The story views the round's story reads read, by the deciding decision's
            id, which names the call within the activation.
        older: Where the activation's place window came from, which its older history
            is read from (ADR-0358 §9:2); ``None`` for a place with no window.
        found: What the round's episode look-ups read, by the deciding decision's id.
    """

    audience: TurnSupply
    owner_records: bool
    views: dict[str, PlanningStory] = field(default_factory=dict)
    older: OlderSource | None = None
    found: dict[str, EpisodeLookedUp] = field(default_factory=dict)


#: The scope a round's look-ups run under, opened by :meth:`LookUps.scope` around acting.
_SCOPE: ContextVar[LookUpScope | None] = ContextVar("look_up_scope", default=None)


def _not_done(kind: ToolFailureKind, message: str) -> ToolResult:
    return ToolResult(outcome=ToolOutcome.FAILED, failure=ToolFailure(kind=kind, message=message))


class LookUps:
    """Run planning's look-ups against the assistant's own records (ADR-0306 §3:3).

    Structurally acting's ``OwnRecordsCalls``. It answers ``failed`` with a code-owned
    kind where a call cannot run, never ``indeterminate``.
    """

    def __init__(
        self,
        *,
        memory: MemoryStore,
        views: StoryViews | None,
        search_limit: int,
        episodes: EpisodeLookUpReads | None = None,
        connections: ConnectionSearch | None = None,
    ) -> None:
        """Wire the runner to the stores it reads.

        Args:
            memory: The memory store a memory search searches.
            views: The story views a story read reads, or ``None`` where no story store
                is wired, which makes every story read not done.
            search_limit: The most records one memory search keeps (#2589's number).
            episodes: The episode look-ups' reads (ADR-0358 §7-§10), or ``None`` where
                none are wired, which makes every episode look-up not done.
            connections: The connections search's read (ADR-0364 §3:7), or ``None``
                where none is wired, which makes every connections search not done.

        Raises:
            ValueError: If ``search_limit`` is below 1.
        """
        if search_limit < 1:
            msg = "a memory search keeps at least one record"
            raise ValueError(msg)
        self._memory = memory
        self._views = views
        self._search_limit = search_limit
        self._episodes = episodes
        self._connections = connections

    @staticmethod
    @contextlib.contextmanager
    def scope(
        *, audience: TurnSupply, owner_records: bool, older: OlderSource | None = None
    ) -> Iterator[LookUpScope]:
        """Open the scope a round's look-ups run under, around acting.

        Args:
            audience: The pass's audience posture.
            owner_records: Whether a record placed for the owner alone may be shown.
            older: Where the place window came from, which the older history reads.

        Yields:
            The scope, whose ``views`` hold the story views read inside it, and whose
            ``found`` holds what the episode look-ups read.
        """
        opened = LookUpScope(audience=audience, owner_records=owner_records, older=older)
        token = _SCOPE.set(opened)
        try:
            yield opened
        finally:
            _SCOPE.reset(token)

    async def run(self, call: ToolCall) -> OwnRecordsAnswer:  # noqa: PLR0911 — one return per look-up
        """Run one look-up and say what the records answered.

        Args:
            call: The authorized look-up, its labels already mapped to ids.

        Returns:
            For a memory search, what goes to planning and the outside ids acting holds;
            for a story read, the story read, its view held in the scope; for a
            follow-up, the result it names; for an episode look-up, what it read, held
            in the scope; ``failed`` where the call cannot run.
        """
        capability = str(call.request.tool.capability)
        parameters = call.request.parameters
        if capability in _EPISODE_LOOK_UPS:
            return await self._episode_look_up(capability, parameters, call.decision.id)
        if capability == SEARCH_CONNECTIONS_CAPABILITY:
            return await self._connections_search(parameters, call.decision.id)
        if capability == SEARCH_MEMORY_CAPABILITY:
            return await self._search(parameters.get(QUERY_ARGUMENT))
        if capability == READ_STORY_CAPABILITY:
            return await self._read(
                parameters.get(STORY_ARGUMENT),
                parameters.get(OLDER_NOTES_PAGE_ARGUMENT, 1),
                call.decision.id,
            )
        if capability == FOLLOW_UP_CAPABILITY:
            result = parameters.get(RESULT_ARGUMENT)
            if not isinstance(result, str) or not result:
                _log.info("look_up_not_done", stage="acting", reason="malformed")
                return _not_done(ToolFailureKind.INVALID_REQUEST, "the call names no result")
            return NamedResult(result_id=result)
        _log.info("look_up_not_done", stage="acting", reason="not_a_look_up")
        return _not_done(ToolFailureKind.INVALID_REQUEST, "not a look-up")

    async def _search(self, query: object) -> OwnRecordsAnswer:
        """Search the remembered facts, and route what the audience admits by source."""
        if not isinstance(query, str) or not query.strip():
            _log.info("look_up_not_done", stage="acting", reason="malformed")
            return _not_done(ToolFailureKind.INVALID_REQUEST, "the query is blank")
        scope = _SCOPE.get()
        if scope is None:
            _log.warning("look_up_not_done", stage="acting", reason="no_scope")
            return _not_done(ToolFailureKind.INTERNAL, _NOT_IN_SCOPE)
        try:
            admitted = await self._banded(query, scope.audience)
        except MemoryStoreError:
            _log.warning("look_up_not_done", stage="acting", reason="search_failed")
            return _not_done(ToolFailureKind.UNAVAILABLE, "memory could not be searched")
        shown = [record.id for record in admitted if not record.rests_on_outside_content]
        outside = tuple(record.id for record in admitted if record.rests_on_outside_content)
        _log.info("look_up_searched", stage="acting", shown=len(shown), held=len(outside))
        output: dict[str, FrozenJson] = {RECORDS_KEY: list(shown)}
        return HeldByIds(output=output, outside=outside)

    async def _banded(self, query: str, audience: TurnSupply) -> list[Memory]:
        """The facts kept: each band searched on its own, kept in precedence order.

        ADR-0072 §5: a band-neutral top-k lets a flood of derived beliefs displace an
        assertion below the cut, so each band is searched on its own, ``ASSERTED``,
        then ``ATTESTED``, then ``DERIVED``, and the limit is filled in that order, as
        recall's band searches fill theirs (ADR-0281 §3:2). ADR-0282 §2:8: a record is
        kept only once the audience predicate has admitted it; each fetch applies it
        again.

        Raises:
            MemoryStoreError: If the store cannot be searched.
        """
        kept: dict[str, Memory] = {}
        for band in _BANDS:
            if len(kept) >= self._search_limit:
                break
            found = await self._memory.search(
                query, limit=self._search_limit, kinds=(MemoryKind.MEMORY,), bands=(band,)
            )
            for record in admitted_to_understanding(audience, found.records):
                if len(kept) >= self._search_limit:
                    break
                # A record rewritten into a later band between the searches is kept
                # once, where it was first admitted.
                if isinstance(record, Memory) and record.id not in kept:
                    kept[record.id] = record
        return list(kept.values())

    async def similar(self, fact: str, *, limit: int) -> tuple[Memory, ...] | None:
        """The memories most similar to ``fact``, for a candidate's lookup (ADR-0329 §4).

        One search by relevance alone (ADR-0328 §7:12), with no band searched on its own,
        under the round's scope: of what it returns, the memories the audience admits
        (ADR-0282 §2:8) that do not rest on outside content (ADR-0329 §4:2), best first.
        They are at most ``limit``, and fewer where the search's best include records it
        does not keep.

        Args:
            fact: The candidate's fact.
            limit: How many the search returns at most.

        Returns:
            The memories kept, or ``None`` where they could not be read: no scope is
            open, or the store could not be searched.
        """
        scope = _SCOPE.get()
        if scope is None:
            _log.warning("look_up_not_done", stage="acting", reason="no_scope")
            return None
        try:
            found = await self._memory.search(fact, limit=limit, kinds=(MemoryKind.MEMORY,))
        except MemoryStoreError:
            _log.warning("look_up_not_done", stage="acting", reason="search_failed")
            return None
        return tuple(
            record
            for record in admitted_to_understanding(scope.audience, found.records)
            if isinstance(record, Memory) and not record.rests_on_outside_content
        )[:limit]

    async def _episode_look_up(
        self, capability: str, parameters: Mapping[str, object], decision_id: str
    ) -> ToolResult:
        """Run one episode look-up under the scope, and hold what it read for the glue.

        ADR-0358 §6:2: run outside a scope, or with no reads wired, it reads nothing and
        is not done.
        """
        page = parameters.get(PAGE_ARGUMENT, 1)
        if isinstance(page, bool) or not isinstance(page, int) or page < 1:
            _log.info("look_up_not_done", stage="acting", reason="malformed")
            return _not_done(ToolFailureKind.INVALID_REQUEST, "the page is not 1 or more")
        named = parameters.get(_NAMED[capability]) if capability in _NAMED else ""
        if not isinstance(named, str) or (capability in _NAMED and not named.strip()):
            _log.info("look_up_not_done", stage="acting", reason="malformed")
            return _not_done(ToolFailureKind.INVALID_REQUEST, _UNNAMED[capability])
        scope = _SCOPE.get()
        if scope is None or self._episodes is None:
            _log.warning("look_up_not_done", stage="acting", reason="no_scope")
            return _not_done(ToolFailureKind.INTERNAL, _NOT_IN_SCOPE)
        reads = self._episodes
        try:
            if capability == SEARCH_EPISODES_CAPABILITY:
                found: EpisodeLookedUp = await reads.search(
                    named, page, audience=scope.audience, owner_records=scope.owner_records
                )
            elif capability == READ_EPISODE_CAPABILITY:
                found = await reads.full(
                    named, page, audience=scope.audience, owner_records=scope.owner_records
                )
            else:
                found = await reads.older(scope.older, page, audience=scope.audience)
        except MemoryStoreError, StoryStoreError, ConversationStoreError:
            _log.warning("look_up_not_done", stage="acting", reason="unreadable")
            return _not_done(ToolFailureKind.UNAVAILABLE, "the records could not be read")
        scope.found[decision_id] = found
        _log.info("look_up_read", stage="acting", look_up=capability)
        return ToolResult(outcome=ToolOutcome.SUCCEEDED, output={_LOOKED_UP_KEY: capability})

    async def _connections_search(
        self, parameters: Mapping[str, object], decision_id: str
    ) -> ToolResult:
        """Search the connections under the scope, and hold what it found (§3:7-§3:8).

        A read of the system's own records under ADR-0358 §6's rules: run outside a
        scope, or with no search wired, it reads nothing and is not done; on a pass that
        may not be shown a record placed for the owner alone, whose conversations every
        place of the hub chat is, it finds none.
        """
        query = parameters.get(QUERY_ARGUMENT)
        page = parameters.get(PAGE_ARGUMENT, 1)
        if not isinstance(query, str) or not query.strip():
            _log.info("look_up_not_done", stage="acting", reason="malformed")
            return _not_done(ToolFailureKind.INVALID_REQUEST, "the query is blank")
        if isinstance(page, bool) or not isinstance(page, int) or page < 1:
            _log.info("look_up_not_done", stage="acting", reason="malformed")
            return _not_done(ToolFailureKind.INVALID_REQUEST, "the page is not 1 or more")
        scope = _SCOPE.get()
        if scope is None or self._connections is None:
            _log.warning("look_up_not_done", stage="acting", reason="no_scope")
            return _not_done(ToolFailureKind.INTERNAL, _NOT_IN_SCOPE)
        if not scope.owner_records:
            found = ConnectionsFound(page=page)
        else:
            try:
                found = await self._connections.search(query, page)
            except ConversationStoreError:
                _log.warning("look_up_not_done", stage="acting", reason="unreadable")
                return _not_done(ToolFailureKind.UNAVAILABLE, "the records could not be read")
        scope.found[decision_id] = found
        _log.info("look_up_read", stage="acting", look_up=SEARCH_CONNECTIONS_CAPABILITY)
        return ToolResult(
            outcome=ToolOutcome.SUCCEEDED, output={_LOOKED_UP_KEY: SEARCH_CONNECTIONS_CAPABILITY}
        )

    async def _read(self, story_id: object, older_page: object, decision_id: str) -> ToolResult:
        """Read one story's full view under the scope, and hold it for the glue."""
        if not isinstance(story_id, str) or not story_id:
            _log.info("look_up_not_done", stage="acting", reason="malformed")
            return _not_done(ToolFailureKind.INVALID_REQUEST, "the call names no story")
        if isinstance(older_page, bool) or not isinstance(older_page, int) or older_page < 1:
            _log.info("look_up_not_done", stage="acting", reason="malformed")
            return _not_done(
                ToolFailureKind.INVALID_REQUEST, "the page of older notes is not 1 or more"
            )
        scope = _SCOPE.get()
        if scope is None or self._views is None:
            _log.warning("look_up_not_done", stage="acting", reason="no_scope")
            return _not_done(ToolFailureKind.INTERNAL, _NOT_IN_SCOPE)
        try:
            view = await self._views.view(
                story_id,
                audience=scope.audience,
                owner_records=scope.owner_records,
                older_page=older_page,
            )
        except StoryStoreError, PlanningError, MemoryStoreError:
            _log.warning("look_up_not_done", stage="acting", reason="story_unreadable")
            return _not_done(ToolFailureKind.UNAVAILABLE, "the story could not be read")
        if view is None:
            _log.info("look_up_not_done", stage="acting", reason="no_story")
            return _not_done(ToolFailureKind.INVALID_REQUEST, "no such story is held")
        scope.views[decision_id] = view
        return ToolResult(outcome=ToolOutcome.SUCCEEDED, output={_STORY_KEY: story_id})
