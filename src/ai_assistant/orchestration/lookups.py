"""Planning's look-ups: a memory search, a story's full view, and the follow-up.

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
| :data:`READ_STORY` | a story, by its ``S`` label | no outside text, marks shown |
| :data:`FOLLOW_UP` | a result, by its ``R`` label; a new *looking for* | may carry outside text |

Each declares the assistant's own records as its effect, as reading a story does
(ADR-0306 §3:1, ADR-0308 §6:6), never leaves the hub, never has an unknown outcome, is
safe to repeat, and writes nothing.

**The memory search** (ADR-0306 §3:4, §5:14-§5:16, ADR-0308 §6:2). It searches the
remembered facts, the semantic records, for its query, and keeps what the pass's
audience admits (``admitted_to_understanding``, ADR-0282 §2:8), as recall's band searches
do (ADR-0281 §4). It routes what it kept record by record by each record's stored
source: the ids of the records whose source is not outside go to planning, which fetches
them by id, the audience predicate applied again, and shows each under its ``M`` label;
the ids of the records whose source is outside are held by acting under the result's id
(:class:`~ai_assistant.orchestration.acting.HeldByIds`), and reach planning only through
a digest answering the call's *looking for*, which fetches them by id, the predicate
applied again (ADR-0282 §2:4-§2:8). No raw outside text reaches planning.

**The full view of a story** (ADR-0300 §10:5-§10:7, ADR-0307 §5:2). Planning names a
story it has been shown by its ``S`` label, which planning's own check maps to the id.
The view is the one planning is shown of each story the activation belongs to, read by
the phases' glue under the pass's audience and its owner-only placement (ADR-0307 §6:4);
it is read when the call runs and held by the call's decision for the glue, which shows
it under the call's result. A read of a story returns no outside text: its lines are the
user's or the assistant's words, each shown with its mark, and a marked line counts as
outside content for the reader (ADR-0300 §10:6).

**The follow-up** (ADR-0308 §6:6-§6:7). Its one planner argument is a result's ``R``
label, which planning's check maps to the result's id, and its *looking for* carries the
new question. The runner answers the result it names
(:class:`~ai_assistant.orchestration.acting.NamedResult`); acting runs it against the
held results, so a digest answers the new question from the result as held, and naming a
result with nothing held comes back not done, with the reason.

**What a look-up reads under.** The memory search and the story's view read under the
pass's audience, which a call does not carry, so the phases' glue opens a
:meth:`LookUps.scope` around acting for the round. A look-up run outside one reads
nothing and is not done.

**It logs stage and code-owned reason only**, never a query, a record or a story
(ADR-0275 §8).
"""

from __future__ import annotations

import contextlib
from collections.abc import Mapping
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final, Protocol

import structlog

from ai_assistant.core.errors import MemoryStoreError, PlanningError, StoryStoreError
from ai_assistant.core.types import (
    CapabilityEffect,
    CapabilityResult,
    CostBasis,
    DataTier,
    Idempotency,
    LabelKind,
    MemoryKind,
    Reversibility,
    RiskLevel,
    SemanticMemory,
    ToolCost,
    ToolDefinition,
    ToolFailure,
    ToolFailureKind,
    ToolOutcome,
    ToolResult,
    rests_on_recorded_external_content,
)
from ai_assistant.orchestration.acting import HeldByIds, NamedResult
from ai_assistant.orchestration.disclosure import admitted_to_understanding
from ai_assistant.orchestration.story_calls import STORY_ARGUMENT

if TYPE_CHECKING:
    from collections.abc import Iterator

    from ai_assistant.core.protocols import MemoryStore
    from ai_assistant.core.types import FrozenJson, ToolCall
    from ai_assistant.orchestration.acting import OwnRecordsAnswer
    from ai_assistant.orchestration.disclosure import TurnSupply
    from ai_assistant.orchestration.planning import PlanningStory

__all__ = [
    "FOLLOW_UP",
    "FOLLOW_UP_CAPABILITY",
    "LOOK_UPS",
    "LOOK_UP_CAPABILITIES",
    "LOOK_UP_LABEL_ARGUMENTS",
    "QUERY_ARGUMENT",
    "QUERY_MAX_CHARS",
    "READ_STORY",
    "READ_STORY_CAPABILITY",
    "RECORDS_KEY",
    "RESULT_ARGUMENT",
    "SEARCH_MEMORY",
    "SEARCH_MEMORY_CAPABILITY",
    "LookUpScope",
    "LookUps",
    "StoryViews",
    "searched_ids",
]

_log = structlog.get_logger(__name__)

#: The capabilities, each the id of its one declaration.
SEARCH_MEMORY_CAPABILITY: Final = "search_memory"
READ_STORY_CAPABILITY: Final = "read_story"
FOLLOW_UP_CAPABILITY: Final = "follow_up"

#: The memory search's one argument: what to search for.
QUERY_ARGUMENT: Final = "query"

#: The follow-up's one planner argument: the result it asks about, by its ``R`` label.
RESULT_ARGUMENT: Final = "result"

#: The longest query a memory search takes.
QUERY_MAX_CHARS: Final = 500

#: The key a memory search's result lists, for planning, the ids of the records whose
#: source is not outside under.
RECORDS_KEY: Final = "records"

#: The key a story read's result names the story read under.
_STORY_KEY: Final = "story"

_NOT_IN_SCOPE: Final = "a look-up reads under the pass's audience, and none was given"


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
        id=capability,
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
        "Search what you remember about the user and their world for a query. What "
        "rests on what a source reported is read for you against what you are looking "
        "for; the rest is shown to you."
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
        "Read the full view of a story you were shown: its summary, its notes and "
        "episodes since, its latest episodes, the larger stories it is part of, and "
        "where its matter stands."
    ),
    properties={
        STORY_ARGUMENT: {
            "type": "string",
            "minLength": 1,
            "description": "The story, by the S label you were shown it under.",
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
        "Ask a new question of a result that was read for you, by its R label: say the "
        "new question in looking_for. The result as it came back is read again for it; "
        "nothing is called again."
    ),
    properties={
        RESULT_ARGUMENT: {
            "type": "string",
            "minLength": 1,
            "description": "The result, by the R label you were shown it under.",
        },
    },
    required=(RESULT_ARGUMENT,),
    result=CapabilityResult.MAY_CARRY_OUTSIDE_TEXT,
)
"""The follow-up (ADR-0308 §6:6): one planner argument, a result's R label, and the
*looking for* the hub adds carries the new question."""

#: Every look-up's declaration.
LOOK_UPS: Final = (SEARCH_MEMORY, READ_STORY, FOLLOW_UP)

#: Every look-up's capability, in :data:`LOOK_UPS`' order.
LOOK_UP_CAPABILITIES: Final = tuple(str(one.capability) for one in LOOK_UPS)

#: Which of the look-ups' arguments name things by label (ADR-0307 §5:2), which
#: planning's check maps to ids or refuses whole (§5:3).
LOOK_UP_LABEL_ARGUMENTS: Final[Mapping[str, Mapping[str, LabelKind]]] = {
    READ_STORY_CAPABILITY: {STORY_ARGUMENT: LabelKind.STORY},
    FOLLOW_UP_CAPABILITY: {RESULT_ARGUMENT: LabelKind.RESULT},
}


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
        self, story_id: str, *, audience: TurnSupply, owner_records: bool
    ) -> PlanningStory | None:
        """One story's full view, under ``audience``, or ``None`` where it is not held.

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
    """

    audience: TurnSupply
    owner_records: bool
    views: dict[str, PlanningStory] = field(default_factory=dict)


#: The scope a round's look-ups run under, opened by :meth:`LookUps.scope` around acting.
_SCOPE: ContextVar[LookUpScope | None] = ContextVar("look_up_scope", default=None)


def _not_done(kind: ToolFailureKind, message: str) -> ToolResult:
    return ToolResult(outcome=ToolOutcome.FAILED, failure=ToolFailure(kind=kind, message=message))


class LookUps:
    """Run planning's look-ups against the assistant's own records (ADR-0306 §3:3).

    Structurally acting's ``OwnRecordsCalls``. It answers ``failed`` with a code-owned
    kind where a call cannot run, never ``indeterminate``.
    """

    def __init__(self, *, memory: MemoryStore, views: StoryViews | None, search_limit: int) -> None:
        """Wire the runner to the stores it reads.

        Args:
            memory: The memory store a memory search searches.
            views: The story views a story read reads, or ``None`` where no story store
                is wired, which makes every story read not done.
            search_limit: The most records one memory search keeps (#2589's number).

        Raises:
            ValueError: If ``search_limit`` is below 1.
        """
        if search_limit < 1:
            msg = "a memory search keeps at least one record"
            raise ValueError(msg)
        self._memory = memory
        self._views = views
        self._search_limit = search_limit

    @staticmethod
    @contextlib.contextmanager
    def scope(*, audience: TurnSupply, owner_records: bool) -> Iterator[LookUpScope]:
        """Open the scope a round's look-ups run under, around acting.

        Args:
            audience: The pass's audience posture.
            owner_records: Whether a record placed for the owner alone may be shown.

        Yields:
            The scope, whose ``views`` hold the story views read inside it.
        """
        opened = LookUpScope(audience=audience, owner_records=owner_records)
        token = _SCOPE.set(opened)
        try:
            yield opened
        finally:
            _SCOPE.reset(token)

    async def run(self, call: ToolCall) -> OwnRecordsAnswer:
        """Run one look-up and say what the records answered.

        Args:
            call: The authorized look-up, its labels already mapped to ids.

        Returns:
            For a memory search, what goes to planning and the outside ids acting holds;
            for a story read, the story read, its view held in the scope; for a
            follow-up, the result it names; ``failed`` where the call cannot run.
        """
        capability = str(call.request.tool.capability)
        parameters = call.request.parameters
        if capability == SEARCH_MEMORY_CAPABILITY:
            return await self._search(parameters.get(QUERY_ARGUMENT))
        if capability == READ_STORY_CAPABILITY:
            return await self._read(parameters.get(STORY_ARGUMENT), call.decision.id)
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
            found = await self._memory.search(
                query, limit=self._search_limit, kinds=(MemoryKind.SEMANTIC,)
            )
        except MemoryStoreError:
            _log.warning("look_up_not_done", stage="acting", reason="search_failed")
            return _not_done(ToolFailureKind.UNAVAILABLE, "memory could not be searched")
        # ADR-0282 §2:8: an id enters the working episode only once the audience
        # predicate has admitted its record; each fetch applies it again.
        admitted = [
            record
            for record in admitted_to_understanding(scope.audience, found.records)
            if isinstance(record, SemanticMemory)
        ]
        shown = [
            record.id
            for record in admitted
            if not rests_on_recorded_external_content(record.provenance)
        ]
        outside = tuple(
            record.id
            for record in admitted
            if rests_on_recorded_external_content(record.provenance)
        )
        _log.info("look_up_searched", stage="acting", shown=len(shown), held=len(outside))
        output: dict[str, FrozenJson] = {RECORDS_KEY: list(shown)}
        return HeldByIds(output=output, outside=outside)

    async def _read(self, story_id: object, decision_id: str) -> ToolResult:
        """Read one story's full view under the scope, and hold it for the glue."""
        if not isinstance(story_id, str) or not story_id:
            _log.info("look_up_not_done", stage="acting", reason="malformed")
            return _not_done(ToolFailureKind.INVALID_REQUEST, "the call names no story")
        scope = _SCOPE.get()
        if scope is None or self._views is None:
            _log.warning("look_up_not_done", stage="acting", reason="no_scope")
            return _not_done(ToolFailureKind.INTERNAL, _NOT_IN_SCOPE)
        try:
            view = await self._views.view(
                story_id, audience=scope.audience, owner_records=scope.owner_records
            )
        except StoryStoreError, PlanningError, MemoryStoreError:
            _log.warning("look_up_not_done", stage="acting", reason="story_unreadable")
            return _not_done(ToolFailureKind.UNAVAILABLE, "the story could not be read")
        if view is None:
            _log.info("look_up_not_done", stage="acting", reason="no_story")
            return _not_done(ToolFailureKind.INVALID_REQUEST, "no such story is held")
        scope.views[decision_id] = view
        return ToolResult(outcome=ToolOutcome.SUCCEEDED, output={_STORY_KEY: story_id})
