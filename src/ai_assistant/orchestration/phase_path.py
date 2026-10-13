"""The phases' thin path: one activation's rounds, wired across the phase modules.

**Glue, and not a phase module** (ADR-0309 §2:3). Each phase takes and returns its own
shapes, because no phase module imports another; this module converts between them,
holds what they decide in the episode's working set, and runs each as a controller
stage. It is outside the ``independence`` contract over the phase modules, so it may
import all of them, and none of them imports it.

**Only where the opt-in is set** (ADR-0309 §2:6). The composition root builds a
:class:`PhasePath` only where ``Settings.phases_thin_path`` is set, which it is on a
test hub alone; the engine then hands the controller
:data:`~ai_assistant.orchestration.controller.PHASE_RULES` and these stages for a
conversation turn the chat's reader starts. Everywhere else today's table runs
unchanged.

**What one round is** (ADR-0307 §2, ADR-0309 §3). Planning asks the model once and
records the round; authorizing checks every call by rule and the message by its place;
acting runs the allowed calls and writes the message, with digesting beside it reading
each held result as acting holds it (§3:3); and the next round is due where a call
brought something or the round was marked (ADR-0307 §8:1). Each is one controller step,
and each decision is held here, in :class:`PhaseWorking`, present once its stage has run
whatever came of it (ADR-0280 §3:6).

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

**The message** (ADR-0307 §3, ADR-0306 §5). The round's text is written into the
input's place through the chat's writer, claimed first under an
:class:`~ai_assistant.core.types.ActivationEffect` and finished with the position the
medium returns, beside the round's calls. An empty text writes nothing; where the place
takes no message the text is kept with the round and written nowhere. When the round
limit or a deadline ends the activation, or a stage fails, the fixed *couldn't finish*
message is written, whatever earlier rounds wrote (ADR-0307 §3:7, ADR-0293 §9:1, §10:2);
a stop writes nothing (ADR-0295 §3:3). Wherever it is written the activation did not
finish, so its episode freezes ``failed`` and the conversation's current state reads
*couldn't finish* beside the message (ADR-0293 §8:3): a stage's failure classifies as it
is, and an activation that returned on the round limit or having written nothing is
``failed / processing_failed`` (ADR-0275 §5:3). The activation's messages, joined by a
blank line, are the episode's ``outcome`` at the freeze (ADR-0307 §10).

**What wrote each message** (ADR-0303 §7:1, ADR-0306 §5:3). The chat's reader links an
assistant message in the window to the activation that wrote it, by the effect record
its message carries with its position; :meth:`PhasePath.written` is that read, over the
plan store's records of the candidate activations the reader names. A message the old
path wrote has no record, and stays not linkable (§7:5).

**The thin path's capabilities** (ADR-0309 §4:2). The web search, remembering and the
simulated booking act. The search is registered at the egress seam and in no
``ToolRegistry`` (ADR-0231 §5), and remembering runs against the assistant's own records
(ADR-0306 §3:3), so :class:`PhaseTools` puts both declarations in front of authorizing's
selection beside the deployment's registry, and routes a search call to the
``WebSearcher`` that proposes and performs it. The search's ``origin`` is the connected
account's: planning is offered the search without it, and the hub fills it from the
searcher's own proposal (``WebSearcher.request``).

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
on outside content, a marked summary or note, an episode resting on outside content or
carrying evidence, or a marked moment of where a matter stands, sets the working set's
``fetched_outside``, which reaches authorizing's ruling and planning's notes alike
(ADR-0306 §4:5-§4:6).

**Left to later lanes:** the story calls and the full view of a story by look-up,
planning's other look-ups, the follow-up, an event through the phases, and ADR-0309 §5:10's
evaluation of the episode's placement over what the activation was given, for which the
thin path places the episode for the owner alone.

**It logs stage and code-owned reason only** (ADR-0275 §8).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Final, Protocol
from uuid import uuid4

import structlog

from ai_assistant.core.clock import checked_clock
from ai_assistant.core.errors import (
    ActivationStoppedError,
    ClaimStopped,
    ConversationStoreError,
    ModelTimeoutError,
    PlanningError,
    StoryStoreError,
)
from ai_assistant.core.types import (
    RECALLED_ITEMS_MAX,
    TRANSCRIPT_MESSAGE_MAX_CHARS,
    ActivationEffect,
    ActivationRecall,
    CapabilityEffect,
    CapabilityResult,
    ControllerRule,
    ControllerStage,
    DigestOutcome,
    EpisodicMemory,
    InputOrigin,
    MemoryKind,
    MessageAuthor,
    Modality,
    NewMessage,
    PlanningLabel,
    ProposedCall,
    RecallOutcome,
    SemanticMemory,
    SendOutcome,
    StageOutcome,
    StoryMember,
    StoryMemberKind,
    StoryRelation,
    ToolFailure,
    ToolFailureKind,
    ToolOutcome,
    ToolResult,
    TranscriptMessage,
    rests_on_recorded_external_content,
)
from ai_assistant.orchestration.acting import (
    ActedOutcome,
    ActedRound,
    ActingStage,
    AuthorizedCall,
    AuthorizedRound,
    ResultRoute,
)
from ai_assistant.orchestration.activation_state import CaptureFacts, active_state
from ai_assistant.orchestration.authorizer import (
    AuthorizingStage,
    CallToAuthorize,
    RoundAuthorization,
    RoundMessage,
    RoundToAuthorize,
    Verdict,
    WorkingRecord,
)
from ai_assistant.orchestration.chat import couldnt_finish
from ai_assistant.orchestration.controller import (
    Stage,
    StageResult,
    TolerantStage,
    recall_digest_due,
)
from ai_assistant.orchestration.digesting import ActivationLabels, Digested, DigestingStage
from ai_assistant.orchestration.held_results import HeldResult, HeldResults
from ai_assistant.orchestration.planning import (
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
)
from ai_assistant.orchestration.recall import Recalled
from ai_assistant.orchestration.stories import episode_address
from ai_assistant.orchestration.story_links import admitted_episodes
from ai_assistant.orchestration.story_privacy import SummaryVisibility
from ai_assistant.orchestration.story_standing import story_standing
from ai_assistant.orchestration.understanding import fetch_held

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping, Sequence

    from ai_assistant.core.protocols import (
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
        FrozenJson,
        MessageReceipt,
        PlanningRound,
        SearchOutcome,
        StoryStanding,
        ToolCall,
        ToolDefinition,
    )
    from ai_assistant.orchestration.activation_state import ActivationState
    from ai_assistant.orchestration.controller import ControllerStageRun
    from ai_assistant.orchestration.disclosure import TurnSupply
    from ai_assistant.orchestration.recall import RecallStage
    from ai_assistant.orchestration.story_links import ShortView, StoryCandidates
    from ai_assistant.orchestration.understanding import Fetched, TranscriptWindow, Windows

__all__ = [
    "CHAT_DESCRIPTION",
    "MessageWriter",
    "PhasePass",
    "PhasePath",
    "PhaseTools",
    "PhaseWorking",
    "StoryReads",
    "authorized_round",
    "call_outcomes",
    "digested_evidence",
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


class PhasePass(Protocol):
    """What a phase stage reads of the pass's working set (ADR-0280 §3).

    The engine's working set satisfies it: the pass's deadline and audience posture,
    the windows stage's decision, recall's first decision, the understanding the
    understanding stage recorded, what that phase fetched for the windows, and the
    phases' own part, :class:`PhaseWorking`.
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
        """
        self._registry = registry
        self._invoker = invoker
        self._own_records = tuple(own_records)
        self._searcher = searcher
        self._search_query = search_query
        self._fills = {
            capability: dict(arguments) for capability, arguments in (fills or {}).items()
        }
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
        return [*self._own_records, *(() if search is None else (search,))]

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

    async def invoke(self, call: ToolCall, *, timeout: timedelta) -> ToolResult:  # noqa: ASYNC109 — the seam owns the deadline (ADR-0029 §4)
        """Invoke ``call``: a search through its searcher, any other through the invoker."""
        search = await self.search_declaration()
        if search is None or self._searcher is None or call.request.tool != search:
            return await self._invoker.invoke(call, timeout=timeout)
        return _searched(await self._searcher.search(call, timeout=timeout))


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

    async def _story(
        self, story_id: str, audience: TurnSupply, visibility: SummaryVisibility
    ) -> PlanningStory | None:
        """One story's view, or ``None`` where the store no longer holds it."""
        state = await self._stories.current_summary(story_id)
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
            newer=tuple(pending[: self._episodes]),
            latest=tuple(record for address in latest if (record := fetched.get(address))),
            inherited=inherited,
            standing=standing,
        )


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


def _stories_external(given: PlanningStories) -> bool:
    """Whether a story view planning is shown rests on outside content (ADR-0303 §3:6).

    A marked summary or note shown, an episode shown resting on outside content or
    carrying evidence, as the episode window's count (ADR-0308 §5:4-§5:5), or a marked
    moment of where a matter stands.
    """
    shorts: list[ShortView] = [
        *given.cited,
        *(one for story in given.stories for one in story.inherited),
    ]
    summaries = any(story.outside for story in given.stories) or any(one.outside for one in shorts)
    notes = any(
        note.outside
        for note in (
            *(note for story in given.stories for note in story.notes),
            *(note for one in shorts for note in one.notes),
        )
    )
    episodes = (
        *(record for story in given.stories for record in (*story.newer, *story.latest)),
        *(record for one in shorts for record in one.episodes),
    )
    moments = any(
        moment.outside
        for story in given.stories
        if story.standing is not None
        for moment in story.standing.recent
    )
    return (
        summaries
        or notes
        or moments
        or any(
            rests_on_recorded_external_content(record.provenance) or _carries_evidence(record)
            for record in episodes
        )
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
    """

    planned: PlannedRound
    authorization: RoundAuthorization | None = None
    acted: ActedRound | None = None
    looking_for: dict[str, str] = field(default_factory=dict)
    step: _Step | None = None


class PhaseWorking:
    """The phases' part of one activation's working set (ADR-0280 §3, ADR-0309 §3:2).

    Structurally :class:`~ai_assistant.orchestration.controller.PhaseFacts`, which the
    phase rules read. It holds recall's second decision and what planning fetched of
    both runs' records, each round's decisions, the activation's labels, its digests and
    the evidence they gave, its held results (acting's part of the working episode,
    never saved), and the messages it wrote.
    """

    def __init__(  # noqa: PLR0913 — the activation, its place, its trigger's origin, its audience, its round limit and its recorded labels
        self,
        *,
        activation_id: str,
        place: PlaceWindow,
        conversation_id: str | None,
        trigger_origin: InputOrigin | None,
        owner_records: bool,
        round_limit: int,
        labels: Sequence[PlanningLabel] = (),
    ) -> None:
        """Start an activation's working set, before its first round.

        Args:
            activation_id: The activation.
            place: The place the input came from, and what planning is shown of it.
            conversation_id: The conversation a message is written into, or ``None``
                where the place takes none.
            trigger_origin: Who the trigger's input came from.
            owner_records: Whether a record placed for the owner alone may be shown on
                this pass (ADR-0307 §6:4).
            round_limit: The most rounds the activation runs (ADR-0307 §8:4).
            labels: The labels the episode already records.

        Raises:
            ValueError: If ``round_limit`` is below 1.
        """
        if round_limit < 1:
            msg = "the round limit is at least one round (ADR-0307 §8:4)"
            raise ValueError(msg)
        self.activation_id = activation_id
        self.place = place
        self.conversation_id = conversation_id
        self.trigger_origin = trigger_origin
        self.owner_records = owner_records
        self._round_limit = round_limit
        self.labels = ActivationLabels(labels)
        self.held = HeldResults(on_hold=self._on_hold)
        self.digests: list[ActivationDigest] = []
        self.evidence: list[DigestedEvidence] = []
        self.messages: list[str] = []
        # Set once a record the windows or recall brought is seen resting on outside
        # content, before the first round is planned (ADR-0181 §4, ADR-0223).
        self.fetched_outside = False
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
        """How many planning rounds the pass has run."""
        return len(self._rounds)

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
    def latest_marked(self) -> bool:
        """The latest round asked for another round."""
        return bool(self._rounds) and self._rounds[-1].planned.round.another_round

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
    def latest_brought_something(self) -> bool:
        """A call of the latest round brought a result or was not done (ADR-0307 §8:1)."""
        if not self._rounds:
            return False
        latest = self._rounds[-1]
        return any(
            one.kind is not CallOutcomeKind.DONE or one.result_id is not None
            for one in call_outcomes(latest.planned, latest.authorization, latest.acted)
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
        """Hold a round planning decided, and the labels it assigned."""
        self.labels.add(planned.labels)
        self._rounds.append(_Round(planned=planned))

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
        """What came of every round's calls, as planning reads them."""
        return tuple(
            outcome
            for one in self._rounds
            for outcome in call_outcomes(one.planned, one.authorization, one.acted)
        )

    def planning_rounds(self) -> tuple[PlanningRound, ...]:
        """Every round, as planning recorded it or as it would have been."""
        return tuple(one.planned.round for one in self._rounds)

    def acted_rounds(self) -> tuple[ActedRound, ...]:
        """Every acting decision, in round order."""
        return tuple(one.acted for one in self._rounds if one.acted is not None)

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
    names that activation's episode (ADR-0303 §7:1, ADR-0307 §5:6). A deleted message
    is not shown.

    Args:
        window: The conversation's recent transcript, brought in with the input.
        description: The channel kind's description.

    Returns:
        The place, oldest item first.
    """
    inputs = {one.position for one in window.input_messages}
    shown: dict[int, TranscriptMessage] = {}
    for one in (*window.replied_to, *window.messages, *window.input_messages):
        if isinstance(one, TranscriptMessage):
            shown[one.position] = one
    items = tuple(
        PlaceItem(
            author=PlaceAuthor.USER if one.author is MessageAuthor.USER else PlaceAuthor.ASSISTANT,
            text=one.text,
            at=one.written_at,
            is_input=position in inputs,
            episode_id=(
                None if (linked := window.links.get(position)) is None else episode_address(linked)
            ),
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
    one authorizing sent to the user needs you; and one it allowed is what acting made
    of it, its result under the id acting minted (ADR-0306 §5:1, §5:14). A call with no
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
            outcomes.append(
                CallOutcome(round_id, call_id, CallOutcomeKind.NEEDS_YOU, reason=verdict.reason)
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
    """Authorizing's decision as acting's input: the allowed calls, in the round's order."""
    return AuthorizedRound(
        activation_id=decided.activation_id,
        round_id=decided.round_id,
        calls=tuple(
            AuthorizedCall(one.call, deliberate_repeat=one.deliberate_repeat)
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


def _new_effect_id() -> str:
    return f"effect:{uuid4().hex}"


def _place_id(conversation_id: str) -> str:
    """The place a message goes into: the conversation, by its id (ADR-0306 §6)."""
    return f"conversation:{conversation_id}"


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


def _fetched_external(fetched: Fetched | None) -> bool:
    """Whether a record the windows or recall brought rests on outside content (ADR-0223).

    An episode carrying evidence counts too: planning is shown an earlier episode's
    evidence, which is outside content (ADR-0308 §5:4-§5:5), whether or not the episode's
    own provenance says so and whether or not the round that reads it keeps notes.
    """
    if fetched is None:
        return False
    records = (*(fetched.episodes or ()), *fetched.recalled)
    return any(
        rests_on_recorded_external_content(one.provenance) or _carries_evidence(one)
        for one in records
    )


def _found_external(found: Fetched) -> bool:
    """Whether a found episode planning is shown rests on outside content (ADR-0223).

    Counted as the episode window's are, its evidence included. A found memory record
    whose source is outside is never shown to planning (ADR-0308 §3:3), and one whose
    source is not outside rests on none, so only an episode can count.
    """
    return any(
        isinstance(one, EpisodicMemory)
        and (rests_on_recorded_external_content(one.provenance) or _carries_evidence(one))
        for one in found.recalled
    )


def _carries_evidence(record: EpisodicMemory | SemanticMemory) -> bool:
    """Whether an episode records a digest that answered with evidence (ADR-0308 §5:5).

    Counted whatever the reader's audience, the conservative direction: where the
    evidence is withheld it was not read, and counting it only marks more.
    """
    processing = record.processing_record if isinstance(record, EpisodicMemory) else None
    return processing is not None and any(
        one.outcome is DigestOutcome.ANSWERED and one.evidence for one in processing.digests
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

    Read off each kept item's recorded origin (ADR-0306 §5:16, ADR-0281 §6): a semantic
    record resting on recorded external content. A found episode is never digested,
    and is shown by its records instead (ADR-0308 §3:1).
    """
    return tuple(
        dict.fromkeys(
            item.id
            for decision in decisions
            if decision is not None
            for item in decision.result.items
            if item.kind is MemoryKind.SEMANTIC and item.rests_on_recorded_external_content
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
    """The thin path's stages, and what one activation's rounds need around them.

    Built by the composition root only where the opt-in is set (ADR-0309 §2:6). The
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
        capabilities: Sequence[str],
        round_limit: int,
        round_wait: timedelta,
        excerpt_chars: int,
        part_chars: int,
        memory: MemoryStore,
        recall_cap: int,
        recall_digest_wait: timedelta,
        planning_model: str | None = None,
        story_reads: StoryReads | None = None,
        now: Callable[[], datetime] = _utcnow,
        new_effect_id: Callable[[], str] = _new_effect_id,
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
            capabilities: The capabilities planning is offered, by name (§4:2).
            round_limit: The most rounds an activation runs (ADR-0307 §8:4).
            round_wait: How long the step running a round's calls waits on its
                digests at most: the call's deadline that bounds the wait (§8:2).
            excerpt_chars: The bound planning cuts another episode's texts to.
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
            now: The clock a step's start and an effect's claim are read from.
            new_effect_id: Mints the *couldn't finish* message's effect record id.

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
            model=planning_model,
            now=now,
        )
        self._digesting = DigestingStage(
            provider=provider, recorder=_DigestRecorder(self), part_chars=part_chars, now=now
        )
        self._authorizing = authorizing
        self._acting = acting
        self._tools = tools
        self._plans = plans
        self._writer = writer
        self._capabilities = tuple(capabilities)
        self._round_limit = round_limit
        self._round_wait = round_wait
        self._new_effect_id = new_effect_id
        self._memory = memory
        self._recall_cap = recall_cap
        self._recall_digest_wait = recall_digest_wait
        self._story_reads = story_reads
        self._append: Callable[[], Awaitable[None]] | None = None

    def attach(self, append: Callable[[], Awaitable[None]]) -> None:
        """Attach the engine's episode append, which extends the current activation's."""
        self._append = append

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
        return PhaseWorking(
            activation_id=activation_id,
            place=place_window(window),
            conversation_id=conversation_id,
            trigger_origin=trigger_origin,
            owner_records=owner_records,
            round_limit=self._round_limit,
            labels=labels,
        )

    async def written(
        self, conversation_id: str, activation_ids: Sequence[str], positions: Sequence[int]
    ) -> dict[int, str]:
        """Which of ``activation_ids`` wrote each message at ``positions`` (ADR-0303 §7:1).

        Read from their effect records (ADR-0306 §5:3): a message done in this
        conversation, at a named position, links to the activation that wrote it. A
        position no record names is simply missing, as is every one where the records
        cannot be read: the message is then not linkable, the conservative direction
        (§7:5), and the window is still brought in.

        Args:
            conversation_id: The conversation the messages are in.
            activation_ids: The candidate activations.
            positions: The assistant messages' positions.

        Returns:
            The activation that wrote each message, by its position.
        """
        wanted = frozenset(positions)
        if not activation_ids or not wanted:
            return {}
        try:
            recorded = await self._plans.activation_effects(activation_ids)
        except Exception:  # the store is down: nothing is linked by what wrote it
            _log.warning("phase_writers_unread", stage="reader", reason="store_failed")
            return {}
        place = _place_id(conversation_id)
        return {
            one.position: one.activation_id
            for one in recorded
            if not one.is_call
            and one.place == place
            and one.outcome is ToolOutcome.SUCCEEDED
            and one.position is not None
            and one.position in wanted
        }

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

        Where the round limit ends the activation, or a stage fails or times out, the
        fixed *couldn't finish* message is written into the input's place, whatever
        earlier rounds wrote (ADR-0307 §3:7, ADR-0293 §9:1, §10:2), and so it is where
        the activation ends having written nothing; a stop and a cancellation write
        nothing (ADR-0295 §3:3, ADR-0293 §9:2). Where a pass that returned owes it, the
        state is marked unfinished, so the episode freezes ``failed`` and the current
        state reads *couldn't finish*, not done (ADR-0293 §8:3). However it ended,
        the activation's messages become the episode's ``outcome``, and the facts the
        freeze derives are set (ADR-0286 §4:2).

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
            # Ending on the round limit, or ending with nothing written (an empty round,
            # or every message refused or gone), owes the fixed message (ADR-0293 §9:1).
            limited = state is not None and _ended_by(state, ControllerRule.ROUND_LIMIT_REACHED)
            if (limited or not working.messages) and not _stopped(state):
                if state is not None:
                    # Unfinished, so the episode and the state say *couldn't finish*
                    # beside the message, not done (ADR-0293 §8:3).
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
                # The thin path places its episode for the owner alone, the safe
                # direction, until ADR-0309 §5:10's evaluation is built.
                state.facts = CaptureFacts(
                    modality=Modality.TEXT,
                    supplied_withheld=True,
                    derived_from_external=external,
                    parked=None,
                    delivery=None,
                )
                state.holds_external(value=external)

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
        try:
            async with asyncio.timeout_at(given.deadline):
                found = await self._found(given, working)
                stories = await self._stories(given, working)
        except TimeoutError:
            raise ModelTimeoutError(_PLANNING_EXPIRED) from None
        if (
            _fetched_external(fetched)
            or _found_external(found)
            or (stories is not None and _stories_external(stories))
        ):
            # Carried into planning's notes and authorizing's rulings from the first
            # round, not only into the frozen episode (ADR-0181 §4, ADR-0306 §4:6).
            working.fetched_outside = True
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
            capabilities=await self._tools.offered(self._capabilities),
            evidence=tuple(working.evidence),
            outside_content_read=working.read_outside_content,
            stories=stories,
        )
        try:
            async with asyncio.timeout_at(given.deadline):
                planned = await self._planning.plan(inputs)
        except TimeoutError:
            raise ModelTimeoutError(_PLANNING_EXPIRED) from None
        working.planned(planned)

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
            _log.info(
                "stage_fetch",
                stage="planning",
                fetched=len(working.found.fetched),
                missing=len(working.found.missing),
            )
        return working.found

    async def _stories(self, given: PhasePass, working: PhaseWorking) -> PlanningStories | None:
        """What planning is shown of stories this round, read as the stores stand now.

        Read before every round, so a later round is shown the stories as they stand
        then, under the pass's audience (ADR-0307 §6:1, §6:4).
        """
        if self._story_reads is None:
            return None
        return await self._story_reads.read(
            working.activation_id,
            understanding=given.understanding,
            audience=given.supply,
            owner_records=working.owner_records,
        )

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

        async def fetch() -> tuple[SemanticMemory, ...]:
            fetched = await fetch_held(
                self._memory, episode_ids=None, recalled_ids=ids, audience=given.supply
            )
            working.recall_digest_fetch = fetched
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
                if isinstance(one, SemanticMemory)
                and rests_on_recorded_external_content(one.provenance)
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
                call=await self._tools.filled(one.call), deliberate_repeat=one.deliberate_repeat
            )
            for one in planned.calls
        ]
        place = None if working.conversation_id is None else _place_id(working.conversation_id)
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
            ),
            calls=tuple(calls),
            input_place=place,
            message=message,
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
            ran, wrote = await asyncio.gather(
                self._calls(working, decided),
                self._message(working, latest),
                return_exceptions=True,
            )
        finally:
            step.held.put_nowait(None)
        if isinstance(ran, ActedRound):
            # Kept even where the message beside it failed: what acting ran happened.
            latest.acted = ran
        for answer in (ran, wrote):
            if isinstance(answer, BaseException):
                raise answer

    async def _calls(self, working: PhaseWorking, decided: RoundAuthorization) -> ActedRound:
        if not decided.allowed:
            return ActedRound(round_id=decided.round_id)
        return await self._acting.act(authorized_round(decided), held=working.held)

    async def _message(self, working: PhaseWorking, latest: _Round) -> None:
        """Write the round's message into the input's place, where it may go (§3:1)."""
        decided = latest.authorization
        text = latest.planned.message
        verdict = None if decided is None else decided.message
        if verdict is None or not verdict.allowed or verdict.effect_id is None or text is None:
            return
        await self._write(
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
                group.create_task(self._digested(working, held, question, step.deadline))

    async def _digested(
        self, working: PhaseWorking, held: HeldResult, question: str, deadline: datetime
    ) -> None:
        digested = await self._digesting.digest_result(
            held, question=question, labels=working.labels, deadline=deadline
        )
        working.digests.append(digested.digest)
        working.evidence.append(digested_evidence(digested, working.labels.labels))

    # --- the place ---

    async def _write(
        self, working: PhaseWorking, text: str, *, effect_id: str, round_id: str | None
    ) -> bool:
        """Claim, write and finish one message into the input's place (ADR-0306 §5:3-§5:5).

        Returns:
            Whether the medium recorded it.
        """
        conversation_id = working.conversation_id
        if conversation_id is None:
            return False
        cut = len(text) > TRANSCRIPT_MESSAGE_MAX_CHARS
        fitted = self._writer.fitted(
            conversation_id,
            NewMessage(
                author=MessageAuthor.ASSISTANT,
                text=text[:TRANSCRIPT_MESSAGE_MAX_CHARS],
                cut_off=cut,
            ),
        )
        effect = ActivationEffect(
            id=effect_id,
            activation_id=working.activation_id,
            round=round_id,
            place=_place_id(conversation_id),
            claimed_at=self._now(),
        )
        try:
            await self._plans.claim_activation_effect(effect, match=None)
        except ClaimStopped:
            _log.info("phase_message_unwritten", stage="acting", reason="stopped")
            return False
        try:
            receipt = await self._writer.send(conversation_id, fitted)
        except ConversationStoreError:
            # Whether the store recorded it is not known: unknown, with no position.
            _log.warning("phase_message_unwritten", stage="acting", reason="store_failed")
            await self._plans.finish_activation_effect(effect_id, ToolOutcome.INDETERMINATE)
            return False
        except Exception:
            # Whatever else the writer raised, whether it wrote is not known either; the
            # record is finished so, and the stage ends on the error.
            await self._plans.finish_activation_effect(effect_id, ToolOutcome.INDETERMINATE)
            raise
        if (
            receipt is None
            or receipt.outcome is not SendOutcome.RECORDED
            or receipt.position is None
        ):
            _log.info("phase_message_unwritten", stage="acting", reason="place_gone")
            await self._plans.finish_activation_effect(effect_id, ToolOutcome.FAILED, reason=_GONE)
            return False
        # Written, as the conversation holds it, whatever becomes of the record's finish.
        working.messages.append(fitted.text)
        await self._plans.finish_activation_effect(
            effect_id, ToolOutcome.SUCCEEDED, position=receipt.position
        )
        return True

    async def _couldnt_finish(self, working: PhaseWorking) -> None:
        """Write the fixed *couldn't finish* message, listing the effects that happened.

        The effects are read from the activation's durable effect records, each call
        done whose record says so, so a call that finished is listed whatever became of
        the step it ran in (ADR-0293 §9:1). Claimed under a record naming no round
        (ADR-0307 §10). It never raises but for a cancellation: a pass that failed is
        already ending on its own error.
        """
        effects = await self._effects(working)
        text = couldnt_finish(effects).text
        try:
            await self._write(working, text, effect_id=self._new_effect_id(), round_id=None)
        except Exception:  # the pass is ending on its own error, or on the round limit
            _log.warning("phase_message_unwritten", stage="end", reason="couldnt_finish_failed")

    async def _effects(self, working: PhaseWorking) -> tuple[str, ...]:
        """The calls that happened, and those whose outcome is unknown, as listed.

        Read from the durable effect records; where they cannot be read, from what
        acting decided on this pass, which is what is known (ADR-0293 §9:1). An unknown
        outcome is listed as unknown, never as done (ADR-0307 §3:4-§3:5, ADR-0306 §5).
        """
        try:
            recorded = await self._plans.activation_effects([working.activation_id])
        except Exception:  # the store is down: list what this pass's working set knows
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


class _RecallDigestFailedError(Exception):
    """Recall's digest failed: carried on its stage's tolerated ``failed`` result.

    Never re-raised while the pass's deadline holds; the digest is recorded with no
    evidence and planning is told it could not read recall's outside records
    (ADR-0308 §4:12-§4:13).
    """
