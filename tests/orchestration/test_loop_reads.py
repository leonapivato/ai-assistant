"""Servicing the read a planner asked for (ADR-0226 §10's Lane B).

ADR-0226 §11's representative-input tests, at the seam that owes them. The ones
this module discharges are numbered in the case that takes each: **2**'s servicing
half, **3**, **4**'s servicing half, **5**, **6**, **7**, **8**, **9**, **10**'s two
pre-plan arms, **12**, **13** and **14**. Test **1** — the reply-vocabulary question
answering through the hop — and test **10**'s two post-plan arms are engine-level and
live in ``test_engine_read_envelope.py``, because what they assert is what happens
*above* this method.

Every case here is a test over behaviour, as §11 requires: what the supply carried,
what the audit recorded, and what the store was asked. Where a call count appears it
is the assertion §11 names in terms — "no model-supplied string reaches ``get_many``
as an identifier", "the servicer performs no store call" — and never a stand-in for
the behaviour itself.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Final, get_args

import pytest
import structlog

from ai_assistant.core.correlation import correlated_operation
from ai_assistant.core.errors import MemoryStoreError, PlanningError
from ai_assistant.core.types import (
    MAX_HOP_LABELS,
    ActionPlan,
    EpisodicMemory,
    MemoryKind,
    MemorySource,
    Placement,
    PlacementReach,
    PlacementSetter,
    PlanStep,
    Provenance,
    ReadAsk,
    ReadKind,
    ReadRequest,
    SemanticMemory,
    TurnResult,
)
from ai_assistant.orchestration import LearningLoop, MemoryWriteStage
from ai_assistant.orchestration.composing import _split_conversation_tail as compose_split
from ai_assistant.orchestration.disclosure import (
    BoundedAudienceSupply,
    TurnSupply,
    UnboundedAudienceSupply,
)
from ai_assistant.orchestration.reads import (
    READ_AUDIT_EVENT,
    READ_BUDGET,
    Servicing,
    TriggerOutcome,
    TurnReadAudit,
    resolve_label,
    service_read_request,
)
from ai_assistant.planning.planner import _split_conversation_tail as plan_split
from ai_assistant.testing import (
    FakeContextProvider,
    FakeDeferralStore,
    FakeFeedbackProcessor,
    FakeMemoryPolicy,
    FakeMemoryStore,
    FakeMemoryWriter,
    FakePlanner,
    FakeToolRegistry,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, MutableMapping, Sequence

    from ai_assistant.core.clock import Clock
    from ai_assistant.core.protocols import MemoryStore, Planner
    from ai_assistant.core.types import (
        BeliefBand,
        CurrentContext,
        Goal,
        MemoryRecord,
        MemorySearchResult,
    )
    from ai_assistant.testing.cancellation import LoopSuspension

_NOW: Final = datetime(2026, 9, 2, 10, 0, tzinfo=UTC)


def _clock() -> datetime:
    return _NOW


# --------------------------------------------------------------------------- #
# Records                                                                      #
# --------------------------------------------------------------------------- #


def _belief(  # noqa: PLR0913 — one argument per field a case needs to vary
    record_id: str,
    content: str,
    *,
    evidence: tuple[str, ...] = (),
    source: MemorySource = MemorySource.OBSERVED,
    about_person: str | None = None,
    placement: Placement | None = None,
) -> SemanticMemory:
    """A belief, optionally citing evidence and optionally unspeakable."""
    return SemanticMemory(
        id=record_id,
        content=content,
        fact=content,
        about_person=about_person,
        placement=Placement() if placement is None else placement,
        provenance=Provenance(
            source=source,
            confidence=1.0 if source is MemorySource.USER_ASSERTED else 0.6,
            last_updated=_NOW,
            evidence=evidence,
        ),
    )


def _episode(record_id: str, content: str) -> EpisodicMemory:
    """A captured turn, as ``orchestration.conversations`` stamps one."""
    return EpisodicMemory(
        id=record_id,
        content=content,
        occurred_at=_NOW,
        provenance=Provenance(source=MemorySource.OBSERVED, confidence=0.9, last_updated=_NOW),
    )


_OWNER_ONLY: Final = Placement(
    reach=PlacementReach.OWNER, set_by=PlacementSetter.DERIVED, set_at=_NOW
)


# --------------------------------------------------------------------------- #
# Requests                                                                     #
# --------------------------------------------------------------------------- #


def _hop(*labels: str) -> ReadRequest:
    return ReadRequest(asks=(ReadAsk(kind=ReadKind.CITATION_HOP, labels=labels),))


def _query(text: str) -> ReadRequest:
    return ReadRequest(asks=(ReadAsk(kind=ReadKind.SIGHTED_QUERY, query=text),))


def _both(text: str, *labels: str) -> ReadRequest:
    """A request carrying one ask of each kind, query first in ``asks``.

    Deliberately query-first in the tuple: ADR-0226 §6 fixes the *servicing* order
    as the hop then the query "whatever order they arrive in", so a request whose
    members are in the other order is the one that catches an implementation
    following the tuple.
    """
    return ReadRequest(
        asks=(
            ReadAsk(kind=ReadKind.SIGHTED_QUERY, query=text),
            ReadAsk(kind=ReadKind.CITATION_HOP, labels=labels),
        )
    )


# --------------------------------------------------------------------------- #
# Stores and planners                                                          #
# --------------------------------------------------------------------------- #


class _Journal(FakeMemoryStore):
    """The canonical store, recording what it was asked."""

    def __init__(self, *, now: Clock = _clock) -> None:
        super().__init__(now=now)
        self.searches: list[tuple[str, int]] = []
        self.keyed: list[tuple[str, ...]] = []

    async def search(
        self,
        query: str,
        *,
        limit: int = 10,
        kinds: Sequence[MemoryKind] | None = None,
        bands: Sequence[BeliefBand] | None = None,
    ) -> MemorySearchResult:
        self.searches.append((query, limit))
        return await super().search(query, limit=limit, kinds=kinds, bands=bands)

    async def get_many(self, record_ids: Sequence[str]) -> dict[str, MemoryRecord]:
        self.keyed.append(tuple(record_ids))
        return dict(await super().get_many(record_ids))


class _FailingKeyedLoad(FakeMemoryStore):
    """A store whose keyed load fails — §14's first arm."""

    async def get_many(self, record_ids: Sequence[str]) -> dict[str, MemoryRecord]:
        msg = "fake: the keyed load is unavailable"
        raise MemoryStoreError(msg)


class _FailSearchFrom(FakeMemoryStore):
    """A store whose ``search`` fails from the ``nth`` call onward.

    The turn's own belief composition reads three bands before the servicer reads
    anything, so counting calls is how a case arms a failure *inside* the servicing
    while leaving the supply planning saw intact — which is the whole of what §14's
    second and third arms distinguish.
    """

    def __init__(self, *, nth: int, now: Clock = _clock) -> None:
        super().__init__(now=now)
        self.calls = 0
        self._nth = nth

    async def search(
        self,
        query: str,
        *,
        limit: int = 10,
        kinds: Sequence[MemoryKind] | None = None,
        bands: Sequence[BeliefBand] | None = None,
    ) -> MemorySearchResult:
        self.calls += 1
        if self.calls >= self._nth:
            msg = "fake: this band's read is unavailable"
            raise MemoryStoreError(msg)
        return await super().search(query, limit=limit, kinds=kinds, bands=bands)


class _DeletingPlanner:
    """A planner that deletes a record it was shown, then names its label.

    §3's third way of resolving to nothing — "a label whose record is no longer
    live" — needs the record to stop being live *between* the loop rendering it and
    the servicer following it. Nothing else in the turn sits in that window, so the
    planner is where a test opens it, and the record stops being live through the
    store's own ``delete`` rather than through a double that omits an id.
    """

    def __init__(self, store: MemoryStore, record_id: str, request: ReadRequest) -> None:
        self._store = store
        self._record_id = record_id
        self._request = request
        self.calls: list[tuple[MemoryRecord, ...]] = []

    async def plan(
        self,
        goal: Goal,
        *,
        context: CurrentContext,
        memories: Sequence[MemoryRecord] = (),
        capabilities: Sequence[str],
    ) -> ActionPlan:
        del context, capabilities
        self.calls.append(tuple(memories))
        await self._store.delete(self._record_id)
        return ActionPlan(
            id=f"{goal.id}-plan",
            goal_id=goal.id,
            steps=(),
            created_at=_NOW,
            read_request=self._request,
        )


class _SuspendingPlanner:
    """A planner that arms the store's suspension, so the servicing can be cancelled.

    The store's suspension holds whichever call enters it next, and the turn's own
    belief composition has already read three times by the time the planner runs — so
    the planner is the one place a case can arm it *between* the retrieval and the
    servicing, which is the window ADR-0226 §9's completed-servicing clause is about.
    """

    def __init__(self, store: FakeMemoryStore, request: ReadRequest) -> None:
        self._store = store
        self._request = request
        self._armed = asyncio.Event()
        self.held: LoopSuspension | None = None

    async def plan(
        self,
        goal: Goal,
        *,
        context: CurrentContext,
        memories: Sequence[MemoryRecord] = (),
        capabilities: Sequence[str],
    ) -> ActionPlan:
        del context, memories, capabilities
        self.held = self._store.suspend_next_operation()
        self._armed.set()
        return ActionPlan(
            id=f"{goal.id}-plan",
            goal_id=goal.id,
            steps=(),
            created_at=_NOW,
            read_request=self._request,
        )

    async def armed(self) -> LoopSuspension:
        """Wait until the suspension is in place, and hand it to the case."""
        await self._armed.wait()
        assert self.held is not None
        return self.held


class _SuspendAfterKeyedLoad(FakeMemoryStore):
    """Holds the store call that follows a keyed load which *returned* records.

    ADR-0226 §9's second failure field is about a read that had already returned
    when the servicing failed, so the interesting cancellation is not the first
    store call but the one after a hop has come back. Arming from inside
    ``get_many`` — after it has left the modelled resource — is the only place a
    case can open that window, because nothing between the hop and the query is a
    seam a test holds.
    """

    def __init__(self, *, now: Clock = _clock) -> None:
        super().__init__(now=now)
        self.held: LoopSuspension | None = None
        self._armed = asyncio.Event()

    async def get_many(self, record_ids: Sequence[str]) -> Mapping[str, MemoryRecord]:
        resolved = await super().get_many(record_ids)
        self.held = self.suspend_next_operation()
        self._armed.set()
        return resolved

    async def armed(self) -> LoopSuspension:
        """Wait until the suspension is in place, and hand it to the case."""
        await self._armed.wait()
        assert self.held is not None
        return self.held


class _SuspendAfterNthSearch(FakeMemoryStore):
    """Holds the search that follows the ``nth`` one, once that one has returned.

    The query's own composition is several reads, so this is how a case reaches
    §9's partial shape without a hop: an earlier band returns, and the next is held.
    """

    def __init__(self, *, nth: int, now: Clock = _clock) -> None:
        super().__init__(now=now)
        self.calls = 0
        self._nth = nth
        self.held: LoopSuspension | None = None
        self._armed = asyncio.Event()

    async def search(
        self,
        query: str,
        *,
        limit: int = 10,
        kinds: Sequence[MemoryKind] | None = None,
        bands: Sequence[BeliefBand] | None = None,
    ) -> MemorySearchResult:
        found = await super().search(query, limit=limit, kinds=kinds, bands=bands)
        self.calls += 1
        if self.calls == self._nth:
            self.held = self.suspend_next_operation()
            self._armed.set()
        return found

    async def armed(self) -> LoopSuspension:
        """Wait until the suspension is in place, and hand it to the case."""
        await self._armed.wait()
        assert self.held is not None
        return self.held


class _RaisingPlanner:
    """A planner that cannot plan — §10's third arm."""

    async def plan(
        self,
        goal: Goal,
        *,
        context: CurrentContext,
        memories: Sequence[MemoryRecord] = (),
        capabilities: Sequence[str],
    ) -> ActionPlan:
        del goal, context, memories, capabilities
        msg = "no plan for that"
        raise PlanningError(msg)


class _RaisingRegistry(FakeToolRegistry):
    """A registry whose vocabulary read fails — §10's fourth arm.

    ``ToolRegistry.capabilities()`` is the injectable failure sitting *above* the
    planner in the turn, so it is how §11 item 10's "the turn fails before the
    planner is called" is reached without reaching into the loop's own stages.
    """

    async def capabilities(self) -> tuple[str, ...]:
        msg = "fake: the registry is unavailable"
        raise PlanningError(msg)


def _loop(
    memory: MemoryStore,
    *,
    planner: Planner | None = None,
    retrieval_limit: int = 30,
    episodic_limit: int = 0,
    registry: FakeToolRegistry | None = None,
) -> LearningLoop:
    """A loop over ``memory``, canonical everything else.

    The episodic supplement is **off** by default so a case's supply is exactly the
    beliefs it seeded: ADR-0158 §3 admits zero as a supported configuration, and a
    third group arriving by relevance would make "what the servicer added" a
    subtraction rather than a reading.
    """
    return LearningLoop(
        context=FakeContextProvider(),
        memory=memory,
        writes=MemoryWriteStage(
            writer=FakeMemoryWriter(store=memory, policy=FakeMemoryPolicy(), now=_clock),
            deferrals=FakeDeferralStore(now=_clock),
        ),
        planner=planner if planner is not None else FakePlanner(now=_clock),
        registry=registry if registry is not None else FakeToolRegistry(),
        feedback=FakeFeedbackProcessor(),
        retrieval_limit=retrieval_limit,
        episodic_limit=episodic_limit,
        now=_clock,
        id_factory=lambda: "goal-1",
    )


def _bounded() -> BoundedAudienceSupply:
    """The filter ``converse`` supplies: evaluates, and subtracts nothing."""
    return BoundedAudienceSupply(speakable_attested_sources=frozenset())


def _unbounded() -> UnboundedAudienceSupply:
    """The filter ``converse_spoken`` supplies: ADR-0199 §3's subtraction."""
    return UnboundedAudienceSupply(speakable_attested_sources=frozenset())


def _records(captured: Sequence[MutableMapping[str, Any]]) -> list[Mapping[str, Any]]:
    """The audit records among captured log events, in order."""
    return [event for event in captured if event["event"] == READ_AUDIT_EVENT]


def _record(captured: Sequence[MutableMapping[str, Any]]) -> Mapping[str, Any]:
    """The one audit record §9 obliges this turn to have written."""
    [only] = _records(captured)
    return only


def _ids(memories: Sequence[MemoryRecord]) -> list[str]:
    return [record.id for record in memories]


# --------------------------------------------------------------------------- #
# §11 item 4 (servicing half): the label is an ordinal into the loop's sequence #
# --------------------------------------------------------------------------- #


def test_a_label_is_an_ordinal_into_the_sequence_the_loop_passed() -> None:
    """§11 item 4: ``M3`` is the third record of *that* turn's ``memories``.

    Resolved against a sequence this test constructs directly, which is how §3's
    "both sides derive the label from ``memories`` and neither consults the other"
    is asserted: there is no table to consult, so a resolver holding only the
    sequence is the whole mechanism.
    """
    supply = (_belief("a", "one"), _belief("b", "two"), _belief("c", "three"))

    assert resolve_label("M1", supply) is supply[0]
    assert resolve_label("M3", supply) is supply[2]
    assert resolve_label("M4", supply) is None


def test_the_same_label_against_a_different_supply_resolves_to_a_different_record() -> None:
    """§11 item 4: the label is meaningful only within the turn that rendered it.

    §3 names the cost in terms — "no label survives to a later turn and none is
    persistable as a reference" — and calls it the correct behaviour rather than a
    limitation, because the resolvable set is exactly what this turn showed.
    """
    first = (_belief("a", "one"), _belief("b", "two"))
    second = (_belief("c", "three"), _belief("d", "four"))

    assert resolve_label("M2", first) is first[1]
    assert resolve_label("M2", second) is second[1]


@pytest.mark.parametrize(
    "label",
    [
        "M0",  # an ordinal below 1
        "M",  # the prefix alone
        "m1",  # the wrong case
        "M01",  # padded, which §3 forbids in terms
        "M+1",
        "M 1",
        " M1",
        "M1 ",
        "M1.0",
        "banana",
        "belief-1",  # a well-formed record identifier
        "M\u0661",  # RUF001: a non-ASCII decimal digit, which `\\d` would admit
        "M" + "9" * 40,  # longer than any sequence, and never handed to int()
    ],
)
def test_a_label_that_is_not_of_the_form_resolves_to_nothing(label: str) -> None:
    """§11 item 3: "a string that does not match the form" resolves to nothing.

    §3 fixes the scheme as "the ASCII string ``M`` followed by *n* in decimal with
    no padding", and every way of not being that lands in one place. The non-ASCII
    digit is the arm a ``\\d`` pattern passes and the renderer could never have
    produced.
    """
    supply = (_belief("belief-1", "one"), _belief("belief-2", "two"))

    assert resolve_label(label, supply) is None


# --------------------------------------------------------------------------- #
# §11 item 2 (servicing half): a sufficed turn pays no read                    #
# --------------------------------------------------------------------------- #


async def test_a_sufficed_turn_pays_no_read_and_is_recorded_as_a_non_firing() -> None:
    """§11 item 2: no request, no store call for one, and the supply is untouched.

    Asserted over the audit and over the supply. The one call count is the one §11
    states in terms — "the servicer performs no store call" — and it is a keyed-load
    count, which the turn has no other reason to make.
    """
    memory = _Journal()
    await memory.add(_belief("belief-1", "dana works on billing"))
    supply = _bounded()

    with structlog.testing.capture_logs() as captured:
        turn = (await _loop(memory).respond("dana works on billing", narrow=supply)).turn

    assert _ids(turn.memories) == ["belief-1"]
    assert memory.keyed == []
    record = _record(captured)
    assert record["trigger"] == TriggerOutcome.NOT_FIRED.value
    assert record["servicing"] == Servicing.NOT_ASKED.value
    assert record["kinds"] == ()
    assert record["returned"] == 0
    assert record["new"] == 0
    assert record["deduplicated"] == 0
    assert record["labels_unresolved"] == 0
    assert record["truncated_kinds"] == ()
    assert record["failed"] is False
    assert record["failed_after_read_returned"] is False


# --------------------------------------------------------------------------- #
# §11 item 3: a label outside the shown set resolves to nothing                #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("label", ["M9", "M99", "banana", "belief-1"])
async def test_an_unresolvable_label_adds_nothing_and_is_recorded_as_dropped(label: str) -> None:
    """§11 item 3: no record added, no turn failed, nothing raised, drop counted.

    The last arm is the one §3 is written for: ``belief-1`` is a *well-formed record
    identifier* of a record this store actually holds, and it still resolves to
    nothing — because it is not a label, and "no record identifier is … accepted
    from" a model.
    """
    memory = _Journal()
    await memory.add(_belief("belief-1", "dana works on billing", evidence=("episode-1",)))
    await memory.add(_episode("episode-1", "the exchange about billing"))
    planner = FakePlanner(now=_clock, read_request=_hop(label))

    with structlog.testing.capture_logs() as captured:
        turn = (
            await _loop(memory, planner=planner).respond("dana works on billing", narrow=_bounded())
        ).turn

    assert _ids(turn.memories) == ["belief-1"]
    record = _record(captured)
    assert record["trigger"] == TriggerOutcome.FIRED.value
    assert record["servicing"] == Servicing.SERVICED.value
    assert record["labels_unresolved"] == 1
    assert record["new"] == 0
    # §3's prohibition, asserted where it would break: no model-supplied string
    # reaches the store as an identifier, so an unresolvable label buys no read.
    assert memory.keyed == []


async def test_a_label_whose_record_is_no_longer_live_resolves_to_nothing() -> None:
    """§11 item 3's last arm: the labelled record has gone since it was rendered.

    §3 names ``get_many``'s own behaviour as what supplies this case — "an id that
    does not resolve is simply missing from the mapping" — so the labelled record's
    id rides in the keyed load beside the evidence it would have opened, and its
    absence there is the label resolving to nothing rather than a hop proceeding
    from a record the store no longer holds.
    """
    memory = _Journal()
    await memory.add(_belief("belief-1", "dana works on billing", evidence=("episode-1",)))
    await memory.add(_episode("episode-1", "the exchange about billing"))
    planner = _DeletingPlanner(memory, "belief-1", _hop("M1"))

    with structlog.testing.capture_logs() as captured:
        turn = (
            await _loop(memory, planner=planner).respond("dana works on billing", narrow=_bounded())
        ).turn

    assert _ids(planner.calls[0]) == ["belief-1"]
    assert _ids(turn.memories) == ["belief-1"], "the supply is what planning saw"
    record = _record(captured)
    assert record["labels_unresolved"] == 1
    assert record["new"] == 0
    assert record["returned"] == 0
    # The cited episode is live and was never followed: the *label* resolved to
    # nothing, so there was nothing to read evidence from.
    assert await memory.get("episode-1") is not None


# --------------------------------------------------------------------------- #
# §11 item 5: an unbounded-audience operation services nothing                 #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "request_",
    [_hop("M1"), _query("the exchange about billing")],
    ids=["citation_hop", "sighted_query"],
)
async def test_an_unbounded_audience_operation_services_nothing(request_: ReadRequest) -> None:
    """§11 item 5: no fourth group, no store read for the request, declined.

    ADR-0226 §5's channel scoping, which is the whole of this ADR's answer to
    ADR-0203 §2's backfill clause: a planner on such a turn judges sufficiency over
    a supply the subtraction has already thinned, so a read it emits is shaped by
    what was withheld even though it never saw the withheld records.

    **The emission is still recorded**, because what is scoped is the servicing:
    "the trigger goes on being measured on every channel".
    """
    memory = _Journal()
    await memory.add(_belief("belief-1", "dana works on billing", evidence=("episode-1",)))
    await memory.add(_episode("episode-1", "the exchange about billing"))
    planner = FakePlanner(now=_clock, read_request=request_)
    supply = _unbounded()

    with structlog.testing.capture_logs() as captured:
        turn = (
            await _loop(memory, planner=planner).respond("dana works on billing", narrow=supply)
        ).turn

    assert _ids(turn.memories) == ["belief-1"]
    assert memory.keyed == []
    assert len(memory.searches) == 3, "the three bands of the turn's own belief read"
    record = _record(captured)
    assert record["trigger"] == TriggerOutcome.FIRED.value
    assert record["servicing"] == Servicing.DECLINED.value
    assert record["returned"] == 0
    assert record["new"] == 0
    assert record["failed"] is False


# --------------------------------------------------------------------------- #
# §11 item 6: a serviced record still fires ADR-0204 §2's evaluation           #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "withheld_record",
    [
        _belief("secret-1", "the appointment on thursday", about_person="Sam"),
        _belief("secret-1", "the appointment on thursday", placement=_OWNER_ONLY),
    ],
    ids=["adr_0199_s3_withholds_it", "adr_0217_placement_mark"],
)
async def test_a_serviced_record_sets_the_value_the_capture_records(
    withheld_record: SemanticMemory,
) -> None:
    """§11 item 6: the evaluation runs over the turn's **final** supply.

    ADR-0226 §7 partially supersedes ADR-0204 §2's timing clause and nothing else of
    §2: one evaluation, both terms, one supply — and on a turn that serviced a
    request the supply is the deduplicated union of all four groups.

    **This is the assertion standing between this ADR and #1708's laundering path.**
    A bounded turn composing over a serviced withheld-class record would otherwise
    capture an *unmarked* episode, and a later spoken turn may read it back —
    "#1708's laundering path runs entirely through this channel's captures". It
    fails on any implementation that evaluates before servicing.

    **And nothing is narrowed to buy it** (§7): the record reaches the fourth group
    and the composing stage, exactly as the other three groups carry withheld-class
    records on a bounded channel.
    """
    memory = FakeMemoryStore(now=_clock)
    await memory.add(_belief("belief-1", "billing schedule notes", evidence=("secret-1",)))
    await memory.add(withheld_record)
    planner = FakePlanner(now=_clock, read_request=_hop("M1"))
    supply = _bounded()

    turn = (await _loop(memory, planner=planner).respond("billing schedule", narrow=supply)).turn

    assert _ids(planner.calls[0][2]) == ["belief-1"], "the planner saw three groups"
    assert _ids(turn.memories) == ["belief-1", "secret-1"], "nothing was dropped"
    assert supply.withheld is True


async def test_the_same_supply_without_the_servicing_records_no_withholding() -> None:
    """The control for the case above: the mark comes from the fourth group.

    Without it the assertion would pass on an implementation that set the boolean
    from the three groups planning saw, which is exactly the implementation ADR-0226
    §7 exists to rule out.
    """
    memory = FakeMemoryStore(now=_clock)
    await memory.add(_belief("belief-1", "billing schedule notes", evidence=("secret-1",)))
    await memory.add(_belief("secret-1", "the appointment on thursday", about_person="Sam"))
    supply = _bounded()

    turn = (await _loop(memory).respond("billing schedule", narrow=supply)).turn

    assert _ids(turn.memories) == ["belief-1"]
    assert supply.withheld is False


# --------------------------------------------------------------------------- #
# §11 item 7: the hop is serviced first, and the budget truncates the query    #
# --------------------------------------------------------------------------- #


async def test_the_hop_is_serviced_before_the_query_and_the_budget_truncates_it() -> None:
    """§11 item 7: the hop's records, then exactly the remainder from the query.

    §6 ratifies the cross-kind precedence here rather than leaving it to a lane,
    "because it decides what reaches the prompt": under one shared budget the two
    kinds compete for the same ten slots, and either order satisfies every other
    clause while producing a different fourth group, prompt and audit.

    The request carries the query **first** in ``asks``, so an implementation
    following the tuple rather than §6 fails this.
    """
    memory = FakeMemoryStore(now=_clock)
    cited = tuple(f"cited-{n}" for n in range(1, 5))
    await memory.add(_belief("belief-1", "billing schedule", evidence=cited))
    for record_id in cited:
        await memory.add(_belief(record_id, "an earlier exchange"))
    for n in range(1, 9):
        await memory.add(_belief(f"loose-{n}", "an unfiled billing note"))
    planner = FakePlanner(now=_clock, read_request=_both("unfiled billing note", "M1"))

    with structlog.testing.capture_logs() as captured:
        turn = (
            await _loop(memory, planner=planner, retrieval_limit=1).respond(
                "billing schedule", narrow=_bounded()
            )
        ).turn

    fourth = _ids(turn.memories)[1:]
    assert fourth[:4] == list(cited), "the hop's records, in the order it named them"
    assert len(fourth) == READ_BUDGET, "and exactly the remainder from the query"
    assert all(name.startswith("loose-") for name in fourth[4:])
    record = _record(captured)
    assert record["truncated_kinds"] == (ReadKind.SIGHTED_QUERY.value,)
    assert record["new"] == READ_BUDGET


async def test_a_hop_that_exhausts_the_budget_leaves_the_query_no_slots() -> None:
    """§11 item 7's second half: permitted, asserted, and stated as a cost.

    §6 is explicit that the hop "is **not** guaranteed small" —
    ``MAX_EVIDENCE_CITATIONS`` is 64, so two labels may resolve to ten distinct live
    evidence records and take the whole budget, "leaving the query none. That is
    permitted by the truncation clause above and asserted by §11's seventh test".
    It does not fail the turn.
    """
    memory = _Journal()
    cited = tuple(f"cited-{n}" for n in range(1, 13))
    await memory.add(_belief("belief-1", "billing schedule notes", evidence=cited))
    for record_id in cited:
        await memory.add(_belief(record_id, "an earlier billing exchange"))
    planner = FakePlanner(now=_clock, read_request=_both("billing note", "M1"))

    with structlog.testing.capture_logs() as captured:
        turn = (
            await _loop(memory, planner=planner, retrieval_limit=1).respond(
                "billing schedule", narrow=_bounded()
            )
        ).turn

    assert _ids(turn.memories)[1:] == list(cited[:READ_BUDGET])
    record = _record(captured)
    assert record["truncated_kinds"] == (
        ReadKind.CITATION_HOP.value,
        ReadKind.SIGHTED_QUERY.value,
    )
    # The query got no slots, so no read was issued for it: three band searches for
    # the turn's own belief composition and none after.
    assert len(memory.searches) == 3


# --------------------------------------------------------------------------- #
# §11 item 12: the budget and the bounds hold                                  #
# --------------------------------------------------------------------------- #


async def test_a_servicing_whose_candidates_exceed_ten_returns_ten() -> None:
    """§11 item 12's first arm, over the uncapped kind.

    The hop is where the budget has to bite: a sighted query is asked for the slots
    that are left and cannot overrun them, where one belief's ``Provenance.evidence``
    is contractually uncapped and 64 citations is the shape §6 prices.
    """
    memory = FakeMemoryStore(now=_clock)
    cited = tuple(f"cited-{n:02d}" for n in range(1, 16))
    await memory.add(_belief("belief-1", "billing schedule notes", evidence=cited))
    for record_id in cited:
        await memory.add(_belief(record_id, "an earlier billing exchange"))
    planner = FakePlanner(now=_clock, read_request=_hop("M1"))

    turn = (
        await _loop(memory, planner=planner, retrieval_limit=1).respond(
            "billing schedule", narrow=_bounded()
        )
    ).turn

    assert _ids(turn.memories)[1:] == list(cited[:READ_BUDGET])


async def test_a_record_already_in_the_supply_is_deduplicated_out_of_the_fourth_group() -> None:
    """§11 item 12's second arm: the original keeps its position and costs nothing.

    ADR-0158 §4's rule applied to a fourth group, for its reason. The duplicate is
    *counted* as a deduplication rather than as a yield, which is what keeps §8's
    novelty rate a statement about records the prompt had not already carried.
    """
    memory = FakeMemoryStore(now=_clock)
    await memory.add(
        _belief("belief-1", "billing schedule notes", evidence=("belief-2", "cited-1"))
    )
    await memory.add(_belief("belief-2", "billing schedule owner"))
    await memory.add(_belief("cited-1", "an earlier exchange"))
    planner = FakePlanner(now=_clock, read_request=_hop("M1"))

    with structlog.testing.capture_logs() as captured:
        turn = (
            await _loop(memory, planner=planner).respond("billing schedule", narrow=_bounded())
        ).turn

    assert _ids(turn.memories) == ["belief-1", "belief-2", "cited-1"]
    record = _record(captured)
    assert record["returned"] == 2
    assert record["new"] == 1
    assert record["deduplicated"] == 1


async def test_a_record_both_kinds_return_enters_the_fourth_group_once() -> None:
    """§11 item 12's third arm — "the one a servicer deduplicating only against the
    pre-servicing supply gets wrong".

    §7 states the deduplication over the whole union for exactly this case: the
    record enters once, "at the position §6's precedence gives its first arrival,
    which is the hop's", and "the second arrival is deduplicated out and **consumes
    no slot of the budget**".
    """
    memory = FakeMemoryStore(now=_clock)
    await memory.add(_belief("belief-1", "schedule notes for dana", evidence=("shared-1",)))
    await memory.add(_belief("shared-1", "an unfiled billing item"))
    await memory.add(_belief("loose-1", "an unfiled billing item"))
    planner = FakePlanner(now=_clock, read_request=_both("unfiled billing", "M1"))

    with structlog.testing.capture_logs() as captured:
        turn = (
            await _loop(memory, planner=planner, retrieval_limit=1).respond(
                "schedule notes", narrow=_bounded()
            )
        ).turn

    fourth = _ids(turn.memories)[1:]
    assert fourth.count("shared-1") == 1
    assert fourth[0] == "shared-1", "at the hop's position"
    assert sorted(fourth) == ["loose-1", "shared-1"]
    record = _record(captured)
    assert record["returned"] == 3, "the hop's one and the query's two"
    assert record["new"] == 2
    assert record["deduplicated"] == 1
    assert record["truncated_kinds"] == (), "the duplicate consumed no slot"


async def test_one_request_over_a_fixed_candidate_set_produces_one_order() -> None:
    """§11 item 12's ordering guarantee, over a **fixed** candidate set.

    §6 fixes the order and the precedence: "given one request, one pre-servicing
    supply and one set of candidates, two conforming implementations append the same
    records in the same order". No case here asserts that a *concurrently written*
    store does — ADR-0113 §5's accepted miss is inherited whole, and §6 says so
    rather than pinning a guarantee the store does not offer.
    """
    memory = FakeMemoryStore(now=_clock)
    await memory.add(_belief("belief-1", "billing schedule notes", evidence=("cited-1", "cited-2")))
    await memory.add(_belief("cited-1", "an earlier exchange"))
    await memory.add(_belief("cited-2", "another earlier exchange"))
    await memory.add(_belief("loose-1", "an unfiled billing note"))
    planner = FakePlanner(now=_clock, read_request=_both("unfiled billing note", "M1"))
    loop = _loop(memory, planner=planner, retrieval_limit=1)

    first = (await loop.respond("billing schedule", narrow=_bounded())).turn
    second = (await loop.respond("billing schedule", narrow=_bounded())).turn

    assert _ids(first.memories) == _ids(second.memories)
    assert _ids(first.memories) == ["belief-1", "cited-1", "cited-2", "loose-1"]


# --------------------------------------------------------------------------- #
# §11 item 13: the fourth group is appended, and the planner never saw it      #
# --------------------------------------------------------------------------- #


async def test_the_fourth_group_is_appended_whole_and_the_planner_never_saw_it() -> None:
    """§11 item 13: three groups to the planner, four on the ``TurnResult``.

    ADR-0158 §5's three-group clause binds on ``Planner.plan``'s ``memories`` word
    for word — the planner is called before the servicer and "cannot receive a group
    produced from its own output" — and its sameness clause is superseded in exactly
    one respect: the ``TurnResult`` carries those three, in those positions,
    followed by the serviced records whole.
    """
    memory = FakeMemoryStore(now=_clock)
    await memory.add(_episode("tail-1", "the user asked about billing"))
    await memory.add(_belief("belief-1", "billing schedule notes", evidence=("cited-1",)))
    await memory.add(_episode("supp-1", "an older billing exchange"))
    await memory.add(_episode("cited-1", "the exchange the note came from"))
    planner = FakePlanner(now=_clock, read_request=_hop("M2"))

    turn = (
        await _loop(memory, planner=planner, episodic_limit=5).respond(
            "billing",
            history=(_episode("tail-1", "the user asked about billing"),),
            narrow=_bounded(),
        )
    ).turn

    planned = _ids(planner.calls[0][2])
    assert planned == ["tail-1", "belief-1", "supp-1"], "three groups, in order"
    assert _ids(turn.memories) == [*planned, "cited-1"], "appended whole, never interleaved"


async def test_a_turn_that_serviced_nothing_hands_the_planner_and_the_result_one_sequence() -> None:
    """§11 item 13's last clause: ADR-0158 §5 where it still binds.

    "On a turn that serviced nothing the two sequences are identical", which is the
    clause this ADR leaves standing on every turn but the one it names.
    """
    memory = FakeMemoryStore(now=_clock)
    await memory.add(_belief("belief-1", "billing schedule notes"))
    planner = FakePlanner(now=_clock)

    turn = (
        await _loop(memory, planner=planner).respond("billing schedule", narrow=_bounded())
    ).turn

    assert turn.memories == planner.calls[0][2]


async def test_a_group_of_episodes_at_the_tail_cannot_extend_the_leading_episodic_run() -> None:
    """§11 item 13: the renderers' leading-``EPISODIC``-run split is unaffected.

    ADR-0158 §4's separator rule is evaluated over what *precedes* the supplement, so
    a group appended after it "cannot extend that run and cannot be misread as the
    conversation's own turns". Asserted against both splitters that read a supply —
    `planning`'s, which the ADR names, and the composing stage's, which is the one
    that actually meets a fourth group.
    """
    supply = (
        _episode("tail-1", "the user asked about billing"),
        _belief("belief-1", "billing schedule notes"),
        _episode("supp-1", "an older billing exchange"),
        _episode("cited-1", "the exchange the note came from"),
    )

    for split in (plan_split, compose_split):
        turns, retrieved = split(supply)
        assert _ids(turns) == ["tail-1"]
        assert _ids(retrieved) == ["belief-1", "supp-1", "cited-1"]


# --------------------------------------------------------------------------- #
# §11 item 14: a failed servicing degrades, and a partial one leaves nothing   #
# --------------------------------------------------------------------------- #


async def test_a_failing_first_read_degrades_the_turn_and_records_no_yield() -> None:
    """§11 item 14's first arm: the **first** store call raises.

    §5's posture, and the archive's for the same reason ADR-0225 §2 gives: "a turn
    that answered from the supply it had is a worse turn, not a broken one". Nothing
    parks, nothing raises, and the pair of failure fields says a total failure — no
    read had returned when this one landed.
    """
    memory = _FailingKeyedLoad(now=_clock)
    await memory.add(_belief("belief-1", "billing schedule notes", evidence=("cited-1",)))
    await memory.add(_belief("cited-1", "an earlier exchange"))
    planner = FakePlanner(now=_clock, read_request=_hop("M1"))

    with structlog.testing.capture_logs() as captured:
        turn = (
            await _loop(memory, planner=planner).respond("billing schedule", narrow=_bounded())
        ).turn

    assert turn.memories == planner.calls[0][2], "the supply planning saw, byte for byte"
    record = _record(captured)
    assert record["trigger"] == TriggerOutcome.FIRED.value
    assert record["servicing"] == Servicing.SERVICED.value
    assert record["failed"] is True
    assert record["failed_after_read_returned"] is False
    assert record["returned"] == 0
    assert record["new"] == 0


async def test_a_hop_that_returned_before_the_query_raised_leaves_nothing_behind() -> None:
    """§11 item 14's second arm: a **partial** read leaves the supply as it was.

    This is the arm that distinguishes §5's "failed **or partial** read leaves the
    supply as planning saw it" from a best-effort servicer. The hop's records do not
    reach the fourth group, and the audit records the degradation with no returned or
    new count — "a count of discarded records would report a yield on a turn §5
    defines as having received none".
    """
    memory = _FailSearchFrom(nth=4, now=_clock)
    await memory.add(_belief("belief-1", "billing schedule notes", evidence=("cited-1",)))
    await memory.add(_belief("cited-1", "an earlier exchange"))
    planner = FakePlanner(now=_clock, read_request=_both("earlier exchange", "M1"))

    with structlog.testing.capture_logs() as captured:
        turn = (
            await _loop(memory, planner=planner).respond("billing schedule", narrow=_bounded())
        ).turn

    assert turn.memories == planner.calls[0][2]
    record = _record(captured)
    assert record["failed"] is True
    assert record["failed_after_read_returned"] is True, "the hop had already returned"
    assert record["returned"] == 0
    assert record["new"] == 0


async def test_a_later_band_raising_after_an_earlier_one_returned_is_recorded_as_partial() -> None:
    """§11 item 14's third arm — "the one a failure field keyed on asks would get
    wrong".

    §9 states the field over **reads** and not over asks precisely for this: a
    request carrying only a ``SIGHTED_QUERY`` is several ``MemoryStore.search``
    calls, so a query whose second band raises after its first returned is as partial
    as a hop that returned before a query raised.
    """
    memory = _FailSearchFrom(nth=5, now=_clock)
    await memory.add(
        _belief("belief-1", "billing schedule notes", source=MemorySource.USER_ASSERTED)
    )
    planner = FakePlanner(now=_clock, read_request=_query("billing schedule notes"))

    with structlog.testing.capture_logs() as captured:
        turn = (
            await _loop(memory, planner=planner).respond("billing schedule", narrow=_bounded())
        ).turn

    assert memory.calls >= 5, "the servicing reached a second band"
    assert turn.memories == planner.calls[0][2]
    record = _record(captured)
    assert record["failed"] is True
    assert record["failed_after_read_returned"] is True
    assert record["returned"] == 0


# --------------------------------------------------------------------------- #
# §11 items 8, 9 and 10: the audit record itself                               #
# --------------------------------------------------------------------------- #


async def test_the_audit_copies_no_text_and_carries_only_the_correlation_id() -> None:
    """§11 item 8: counts and kinds, the correlation id, and nothing else.

    Asserted at the emitting seam through a capturing processor, "so the test is
    about the code's obligation and not about a configured level" — §9 binds the
    emitting code and says in terms that a deployment above ``INFO`` loses the
    instrument.

    Neither a distinctive span of a returned record nor the planner's query string
    appears anywhere in the event, and there is **no pointer to the plan**: §9 shows
    that a pointer would have to be ``ActionPlan.id``, whose provenance cannot be
    established from the value.
    """
    memory = FakeMemoryStore(now=_clock)
    await memory.add(_belief("belief-1", "billing schedule notes", evidence=("cited-1",)))
    await memory.add(_belief("cited-1", "quinoa-flavoured stroopwafel"))
    planner = FakePlanner(now=_clock, read_request=_both("marmalade zeppelin", "M1"))

    with structlog.testing.capture_logs() as captured, correlated_operation() as correlation:
        turn = (
            await _loop(memory, planner=planner).respond("billing schedule", narrow=_bounded())
        ).turn

    record = _record(captured)
    assert record["correlation_id"] == correlation
    rendered = repr(record)
    assert "marmalade" not in rendered, "the planner's query is not copied"
    assert "stroopwafel" not in rendered, "no returned record's content is copied"
    assert "M1" not in rendered, "the labels it named are not copied"
    assert turn.plan.id not in rendered, "no pointer to the plan"
    assert set(record) == {
        "event",
        "log_level",
        "correlation_id",
        "trigger",
        "servicing",
        "kinds",
        "returned",
        "new",
        "deduplicated",
        "labels_unresolved",
        "truncated_kinds",
        "failed",
        "failed_after_read_returned",
    }
    assert record["log_level"] == "info"
    assert record["kinds"] == (ReadKind.SIGHTED_QUERY.value, ReadKind.CITATION_HOP.value)


async def test_the_audit_records_a_turn_that_ran_outside_a_correlated_operation() -> None:
    """§9: "where it is ``None`` the field says the turn ran outside a correlated
    operation and the record is emitted regardless"."""
    with structlog.testing.capture_logs() as captured:
        await _loop(FakeMemoryStore(now=_clock)).respond("billing schedule", narrow=_bounded())

    assert _record(captured)["correlation_id"] is None


async def test_the_audit_carries_no_identifier_a_caller_supplied() -> None:
    """§11 item 9: an address-shaped plan id appears nowhere in the event.

    ``Identifier`` admits any non-blank encodable string, so a ``Planner`` — or
    ``ModelBackedPlanner``'s own injectable id factory — may return one carrying
    content, which in a Tier 2 event is a Tier 1 leak. Asserted over the emitted
    event's own fields, not over the redaction net.
    """
    address = "12 Rowan Street, Ipswich"
    plan = ActionPlan(
        id=address,
        goal_id="goal-1",
        steps=(),
        created_at=_NOW,
        read_request=_query("an earlier exchange"),
    )
    planner = FakePlanner(plan, now=_clock)

    with structlog.testing.capture_logs() as captured:
        await _loop(FakeMemoryStore(now=_clock), planner=planner).respond(
            "billing schedule", narrow=_bounded()
        )

    record = _record(captured)
    assert address not in repr(record)
    assert "goal-1" not in repr(record)


async def test_a_planner_that_raises_records_a_turn_the_trigger_never_reached() -> None:
    """§11 item 10's third arm, and the failure still propagates.

    §8's third outcome: such a turn "reached no judgement about its supply at all",
    so it is in neither the fire rate's numerator nor its denominator.
    """
    with structlog.testing.capture_logs() as captured, pytest.raises(PlanningError):
        await _loop(FakeMemoryStore(now=_clock), planner=_RaisingPlanner()).respond(
            "billing schedule", narrow=_bounded()
        )

    record = _record(captured)
    assert record["trigger"] == TriggerOutcome.NOT_REACHED.value
    assert record["servicing"] == Servicing.NOT_ASKED.value


async def test_a_turn_that_fails_before_the_planner_is_called_records_not_reached() -> None:
    """§11 item 10's fourth arm — "two arms and not one".

    §8's not-reached case is stated over turns that ended without a plan rather than
    over the planner raising, so "an implementation that emitted the record only from
    a handler around ``Planner.plan`` would pass the first and silently drop the
    second, undercounting exactly the population the outcome exists to make visible".
    ``ToolRegistry.capabilities()`` is the injectable case, read immediately above
    the ``plan`` call.
    """
    with structlog.testing.capture_logs() as captured, pytest.raises(PlanningError):
        await _loop(FakeMemoryStore(now=_clock), registry=_RaisingRegistry()).respond(
            "billing schedule", narrow=_bounded()
        )

    assert _record(captured)["trigger"] == TriggerOutcome.NOT_REACHED.value


async def test_every_turn_writes_exactly_one_record() -> None:
    """§8: "Every turn writes §9's audit record, whether or not the trigger fired."

    Three turns of different shapes, three records — because "an instrument that only
    records its positives cannot measure a fire rate", and a denominator is what the
    non-fired turns are.
    """
    memory = FakeMemoryStore(now=_clock)
    await memory.add(_belief("belief-1", "billing schedule notes", evidence=("cited-1",)))
    await memory.add(_belief("cited-1", "an earlier exchange"))

    with structlog.testing.capture_logs() as captured:
        await _loop(memory).respond("billing schedule", narrow=_bounded())
        await _loop(memory, planner=FakePlanner(now=_clock, read_request=_hop("M1"))).respond(
            "billing schedule", narrow=_bounded()
        )
        await _loop(memory, planner=FakePlanner(now=_clock, read_request=_hop("M1"))).respond(
            "billing schedule", narrow=_unbounded()
        )

    assert [event["trigger"] for event in _records(captured)] == [
        TriggerOutcome.NOT_FIRED.value,
        TriggerOutcome.FIRED.value,
        TriggerOutcome.FIRED.value,
    ]
    assert [event["servicing"] for event in _records(captured)] == [
        Servicing.NOT_ASKED.value,
        Servicing.SERVICED.value,
        Servicing.DECLINED.value,
    ]


async def test_a_request_is_serviced_once_and_the_turn_result_is_built_once() -> None:
    """§6: "One emission is serviced **once** per turn", and §5's one construction.

    The servicer performs no second pass. Asserted over the store: one keyed load for
    the hop, and the three band reads of the turn's own belief composition with none
    after — a second pass would show as a second keyed load.
    """
    memory = _Journal()
    await memory.add(_belief("belief-1", "billing schedule notes", evidence=("cited-1",)))
    await memory.add(_belief("cited-1", "an earlier exchange"))
    planner = FakePlanner(now=_clock, read_request=_hop("M1"))

    await _loop(memory, planner=planner).respond("billing schedule", narrow=_bounded())

    assert len(memory.keyed) == 1
    assert len(memory.searches) == 3


async def test_a_turn_with_no_supply_filter_services_nothing() -> None:
    """§5, fail-closed: a filter that declares no audience gets no servicing.

    ``narrow=None`` "remains valid and plans over everything", and it declares no
    posture at all — so ADR-0226 §5's refusal is the answer rather than a guess. The
    emission is still recorded, exactly as it is on the channel §5 names.

    This is the property that makes the scoping unfalsifiable by a caller: the
    posture is read off the supply object rather than taken as a boolean beside it,
    so there is no pair to contradict and no way to declare an unbounded turn
    bounded.
    """
    memory = _Journal()
    await memory.add(_belief("belief-1", "billing schedule notes", evidence=("cited-1",)))
    await memory.add(_belief("cited-1", "an earlier exchange"))
    planner = FakePlanner(now=_clock, read_request=_hop("M1"))

    with structlog.testing.capture_logs() as captured:
        turn = (await _loop(memory, planner=planner).respond("billing schedule")).turn

    assert _ids(turn.memories) == ["belief-1"]
    assert memory.keyed == []
    assert _record(captured)["servicing"] == Servicing.DECLINED.value


async def test_the_servicing_reads_the_belief_kinds_the_retrieval_stage_reads() -> None:
    """§2: the sighted query keeps "the … kind selection of the retrieval stage's
    own read unchanged".

    An episode matching the planner's query is not admitted by it: the sighted query
    is the retrieval stage's read with a different query, not a wider one. ADR-0225
    §12's gate is a separate matter and is not approached — nothing here admits an
    archive entry anywhere.
    """
    memory = FakeMemoryStore(now=_clock)
    await memory.add(_belief("belief-1", "billing schedule notes"))
    await memory.add(_episode("episode-1", "an unfiled billing note"))
    await memory.add(_belief("loose-1", "an unfiled billing note"))
    planner = FakePlanner(now=_clock, read_request=_query("unfiled billing note"))

    turn = (
        await _loop(memory, planner=planner, retrieval_limit=1).respond(
            "billing schedule", narrow=_bounded()
        )
    ).turn

    assert _ids(turn.memories) == ["belief-1", "loose-1"]


async def test_the_hop_follows_only_the_labelled_records_own_evidence() -> None:
    """§3: no second level, "that is iteration, and it is §12's".

    A record reached *through* the hop carries evidence of its own, and none of it is
    followed. Asserted over the supply rather than over a call count, because the
    property is what reached the turn.
    """
    memory = FakeMemoryStore(now=_clock)
    await memory.add(_belief("belief-1", "billing schedule notes", evidence=("cited-1",)))
    await memory.add(_belief("cited-1", "an earlier exchange", evidence=("deeper-1",)))
    await memory.add(_belief("deeper-1", "an exchange behind that one"))
    planner = FakePlanner(now=_clock, read_request=_hop("M1"))

    turn = (
        await _loop(memory, planner=planner).respond("billing schedule", narrow=_bounded())
    ).turn

    assert _ids(turn.memories) == ["belief-1", "cited-1"]


async def test_a_second_labels_evidence_is_followed_in_the_order_the_ask_names_them() -> None:
    """§6: "labels are followed in the order the ask names them and each record's
    evidence in the order that record stores it"."""
    memory = FakeMemoryStore(now=_clock)
    await memory.add(_belief("belief-1", "billing schedule notes", evidence=("a-1", "a-2")))
    await memory.add(_belief("belief-2", "billing schedule owner", evidence=("b-1",)))
    for record_id in ("a-1", "a-2", "b-1"):
        await memory.add(_belief(record_id, "an earlier exchange"))
    planner = FakePlanner(now=_clock, read_request=_hop("M2", "M1"))

    turn = (
        await _loop(memory, planner=planner).respond("billing schedule", narrow=_bounded())
    ).turn

    assert _ids(turn.memories)[2:] == ["b-1", "a-1", "a-2"]


async def test_the_turn_is_not_failed_by_a_request_naming_a_record_with_no_evidence() -> None:
    """A hop onto a belief citing nothing adds nothing and is not a drop.

    The label resolved — §9's ``labels_unresolved`` counts labels that resolved to
    nothing, not reads that found nothing — so the record is a fired, serviced turn
    with a zero yield, which is precisely the population §8 warns is *not* evidence
    the trigger was wrong.
    """
    memory = FakeMemoryStore(now=_clock)
    await memory.add(_belief("belief-1", "billing schedule notes"))
    planner = FakePlanner(now=_clock, read_request=_hop("M1"))

    with structlog.testing.capture_logs() as captured:
        turn = (
            await _loop(memory, planner=planner).respond("billing schedule", narrow=_bounded())
        ).turn

    assert _ids(turn.memories) == ["belief-1"]
    record = _record(captured)
    assert record["labels_unresolved"] == 0
    assert record["returned"] == 0
    assert record["new"] == 0
    assert record["failed"] is False


async def test_an_unbounded_audience_turn_still_narrows_before_planning() -> None:
    """ADR-0203 §1 is untouched where the envelope does not reach.

    The one thing ADR-0226 §7 moves is *when* the evaluation is taken on a turn that
    serviced a request. On an unbounded-audience turn nothing is serviced, so the
    subtraction stays exactly where ADR-0203 §1 puts it — before the planner, which
    is what the planner's own recorded call proves.
    """
    memory = FakeMemoryStore(now=_clock)
    await memory.add(_belief("belief-1", "billing schedule notes"))
    await memory.add(_belief("secret-1", "billing schedule for sam", about_person="Sam"))
    planner = FakePlanner(now=_clock)
    supply = _unbounded()

    turn = (await _loop(memory, planner=planner).respond("billing schedule", narrow=supply)).turn

    assert _ids(planner.calls[0][2]) == ["belief-1"], "withheld before planning"
    assert _ids(turn.memories) == ["belief-1"]
    assert supply.withheld is True


async def test_the_evaluation_is_taken_once_on_a_turn_that_serviced_a_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§7: "§2's *"once"* is kept in letter, so no implementation evaluates twice".

    A recording filter counts its applications. Two would disjoin two evaluations'
    results, which §7 forbids in terms, and would also hand the planner one supply
    and the ``TurnResult`` another for a reason nothing states.
    """
    applications: list[int] = []
    applied = BoundedAudienceSupply.__call__

    def counting(
        supply: BoundedAudienceSupply,
        context: CurrentContext,
        memories: tuple[MemoryRecord, ...],
        retrieved_ids: frozenset[str],
    ) -> tuple[CurrentContext, tuple[MemoryRecord, ...]]:
        applications.append(len(memories))
        return applied(supply, context, memories, retrieved_ids)

    # Patched on the class rather than subclassed: ADR-0226 §5's posture is read off
    # the filter's exact type, and ``TurnSupply``'s members are ``@final`` precisely
    # so that a subclass cannot claim a posture it does not keep. The subject is
    # therefore the real object, instrumented.
    monkeypatch.setattr(BoundedAudienceSupply, "__call__", counting)
    memory = FakeMemoryStore(now=_clock)
    await memory.add(_belief("belief-1", "billing schedule notes", evidence=("cited-1",)))
    await memory.add(_belief("cited-1", "an earlier exchange"))
    planner = FakePlanner(now=_clock, read_request=_hop("M1"))

    await _loop(memory, planner=planner).respond("billing schedule", narrow=_bounded())

    assert applications == [2], "once, over the final supply of four groups"


def test_the_budget_is_the_figure_adr_0226_fixes() -> None:
    """§6: ten, and a second budget rather than a share of the first.

    Pinned as a value rather than left implicit because §6 forbids funding this
    envelope out of ``RETRIEVAL_LIMIT`` or ``EPISODIC_SUPPLEMENT_LIMIT``: a lane
    lowering either to pay for it would leave this constant untouched, so the
    constant is where the figure is asserted and the loop's own budgets are where
    the funding rule is.
    """
    assert READ_BUDGET == 10


def test_a_turn_result_carries_no_marker_of_where_the_fourth_group_begins() -> None:
    """§7's caution, carried word for word to the fourth group.

    A consumer of ``TurnResult.memories`` "may rely on the grouping and may not rely
    on a global relevance order" — and, as ADR-0210 §1 already found for the
    supplement, no boundary index is offered either. The type is unchanged, which is
    the assertion: this lane adds no field to it and none is owed.
    """
    assert set(TurnResult.model_fields) == {
        "goal",
        "context",
        "memories",
        "plan",
        "memory_degraded",
    }


async def test_the_servicer_is_reachable_through_no_registry() -> None:
    """§5: not a tool, not registered, advertising no capability.

    ADR-0208 §1's second clause — that no lane registers a tool whose implementation
    reads a ``MemoryStore`` into any registry the turn path selects from — "binds
    unchanged and is not approached". A turn that serviced a request consults the
    registry exactly once, for the vocabulary the planner is told about (ADR-0211
    §3), and the servicing adds no lookup of its own.
    """
    memory = FakeMemoryStore(now=_clock)
    await memory.add(_belief("belief-1", "billing schedule notes", evidence=("cited-1",)))
    await memory.add(_belief("cited-1", "an earlier exchange"))
    registry = FakeToolRegistry()
    planner = FakePlanner(now=_clock, read_request=_hop("M1"))

    turn = (
        await _loop(memory, planner=planner, registry=registry).respond(
            "billing schedule", narrow=_bounded()
        )
    ).turn

    assert _ids(turn.memories) == ["belief-1", "cited-1"]
    assert registry.lookups == [], "no tool was looked up for the read"
    assert await registry.capabilities() == ()


async def test_a_request_naming_a_query_that_reads_like_a_tool_call_reaches_no_registry() -> None:
    """§4: "A ``ReadAsk`` is **not** a ``PlanStep``, and nothing drives it."

    §11 item 15's servicing-side shape: the query is a relevance query and nothing
    more, so a query spelled like a capability is read by the store and never
    selected, ruled on or driven. The plan's ``steps`` stay empty, which is what the
    selection stage reads.
    """
    memory = FakeMemoryStore(now=_clock)
    await memory.add(_belief("belief-1", "billing schedule notes"))
    await memory.add(_belief("loose-1", "send_email to dana"))
    planner = FakePlanner(now=_clock, read_request=_query("send_email to dana"))
    registry = FakeToolRegistry()

    turn = (
        await _loop(memory, planner=planner, registry=registry, retrieval_limit=1).respond(
            "billing schedule", narrow=_bounded()
        )
    ).turn

    assert turn.plan.steps == ()
    assert _ids(turn.memories) == ["belief-1", "loose-1"]
    assert registry.lookups == []


async def test_a_servicing_that_returns_nothing_leaves_the_supply_identical() -> None:
    """A fired turn with an empty yield is still a fired turn (§8).

    "Novelty … does **not** say the supply was insufficient", and the converse holds
    too: a read that returns only what the supply already carried is a true fire
    scoring as zero. The audit says so rather than the servicing pretending it did
    not run.
    """
    memory = FakeMemoryStore(now=_clock)
    await memory.add(_belief("belief-1", "billing schedule notes"))
    planner = FakePlanner(now=_clock, read_request=_query("billing schedule notes"))

    with structlog.testing.capture_logs() as captured:
        turn = (
            await _loop(memory, planner=planner).respond("billing schedule", narrow=_bounded())
        ).turn

    assert turn.memories == planner.calls[0][2]
    record = _record(captured)
    assert record["trigger"] == TriggerOutcome.FIRED.value
    assert record["returned"] == 1
    assert record["deduplicated"] == 1
    assert record["new"] == 0


async def test_a_degraded_retrieval_does_not_change_what_the_servicing_owes() -> None:
    """``memory_degraded`` is upstream of the envelope and stays so (ADR-0203 §3).

    The servicing runs over whatever the supply turned out to be — which on a
    degraded turn is less — and the flag reports the turn's own I/O rather than what
    the fourth group added. A servicer that cleared it would be claiming the answer
    was as personal as it should have been.
    """
    memory = FakeMemoryStore(now=_clock)
    await memory.add(_belief("belief-1", "billing schedule notes", evidence=("cited-1",)))
    await memory.add(_belief("cited-1", "an earlier exchange"))
    planner = FakePlanner(now=_clock, read_request=_hop("M1"))

    turn = (
        await _loop(memory, planner=planner).respond(
            "billing schedule",
            history_degraded=True,
            narrow=_bounded(),
        )
    ).turn

    assert turn.memory_degraded is True
    assert _ids(turn.memories) == ["belief-1", "cited-1"]


async def test_an_expired_cited_record_is_simply_absent_from_the_fourth_group() -> None:
    """``get_many``'s omission, at the evidence end rather than the label end.

    "An id that does not resolve is **simply missing from the mapping**; it is never
    an error" — so a citation whose record has gone costs the hop that record and
    nothing else, and it is not a dropped *label*.
    """
    memory = FakeMemoryStore(now=_clock)
    await memory.add(_belief("belief-1", "billing schedule notes", evidence=("gone-1", "cited-1")))
    await memory.add(_belief("cited-1", "an earlier exchange"))
    planner = FakePlanner(now=_clock, read_request=_hop("M1"))

    with structlog.testing.capture_logs() as captured:
        turn = (
            await _loop(memory, planner=planner).respond("billing schedule", narrow=_bounded())
        ).turn

    assert _ids(turn.memories) == ["belief-1", "cited-1"]
    record = _record(captured)
    assert record["labels_unresolved"] == 0
    assert record["returned"] == 1
    assert record["new"] == 1


async def test_each_turn_resolves_labels_against_its_own_supply() -> None:
    """The label space is this call's ``memories`` and nothing durable.

    Two turns of one loop resolve ``M1`` against their own sequences, so a request
    that made sense on the first turn reaches a different record on the second where
    the supply differs — §3's "no label survives to a later turn", seen from the
    loop rather than from the resolver.
    """
    memory = FakeMemoryStore(now=_clock)
    await memory.add(_belief("belief-1", "billing schedule notes", evidence=("cited-1",)))
    await memory.add(_belief("cited-1", "an earlier exchange"))
    await memory.add(_belief("belief-2", "roster notes", evidence=("cited-2",)))
    await memory.add(_belief("cited-2", "a roster exchange"))
    planner = FakePlanner(now=_clock, read_request=_hop("M1"))
    loop = _loop(memory, planner=planner, retrieval_limit=1)

    billing = (await loop.respond("billing schedule", narrow=_bounded())).turn
    roster = (await loop.respond("roster notes", narrow=_bounded())).turn

    assert _ids(billing.memories) == ["belief-1", "cited-1"]
    assert _ids(roster.memories) == ["belief-2", "cited-2"]


def test_the_audit_event_key_is_one_fixed_name() -> None:
    """§9: "a structured log event, emitted … under one fixed event key".

    Pinned as a constant so a later lane extending the record for milestone 2 —
    which §9 says "raises rather than replaces" these fields — cannot start a second
    audit beside this one by renaming the key.
    """
    assert READ_AUDIT_EVENT == "turn_read_request"


def test_the_hop_label_bound_is_the_one_the_replay_measured() -> None:
    """§6: "A ``CITATION_HOP`` ask names **at most two labels**".

    Enforced by ``ReadAsk`` (Lane A) and asserted here from the servicing side,
    because §6 says the conversion the replay measured — 47.6% — "is the conversion
    of the bound this section sets rather than of a looser one".
    """
    assert MAX_HOP_LABELS == 2
    with pytest.raises(ValueError, match="at most 2 labels"):
        _hop("M1", "M2", "M3")


def test_a_turn_of_the_far_future_resolves_labels_the_same_way() -> None:
    """The scheme carries no clock and no state; only the sequence decides.

    A guard against a later lane making the label configurable or deriving it from
    anything but position — §3 forbids both, and there is nothing here for a
    deployment to tune.
    """
    supply = tuple(_belief(f"b-{n}", "one") for n in range(1, 13))

    assert resolve_label("M12", supply) is supply[11]
    assert resolve_label("M13", supply) is None
    assert resolve_label("M1", ()) is None


async def test_a_turn_refused_before_context_assembly_records_not_reached() -> None:
    """§8's third outcome reaches every exit that ends without a plan.

    A blank utterance never reaches context assembly, let alone the planner, and it
    is still a turn the instrument took no reading from — which is what "the point
    that turn ends" means in §9.
    """
    with structlog.testing.capture_logs() as captured, pytest.raises(PlanningError):
        await _loop(FakeMemoryStore(now=_clock)).respond("   ", narrow=_bounded())

    assert _record(captured)["trigger"] == TriggerOutcome.NOT_REACHED.value


async def test_two_turns_of_one_loop_write_two_records() -> None:
    """One record per turn, and no state carried between them.

    A ``TurnReadAudit`` is minted per call, so a fired turn cannot leave its counts
    on the next turn's record — the failure that would make a fire rate read high
    for as long as a process lived.
    """
    memory = FakeMemoryStore(now=_clock)
    await memory.add(_belief("belief-1", "billing schedule notes", evidence=("cited-1",)))
    await memory.add(_belief("cited-1", "an earlier exchange"))
    loop = _loop(memory, planner=FakePlanner(now=_clock, read_request=_hop("M1")))
    quiet = _loop(memory)

    with structlog.testing.capture_logs() as captured:
        await loop.respond("billing schedule", narrow=_bounded())
        await quiet.respond("billing schedule", narrow=_bounded())

    first, second = _records(captured)
    assert first["new"] == 1
    assert second["new"] == 0
    assert second["trigger"] == TriggerOutcome.NOT_FIRED.value


def test_a_read_ask_is_never_a_plan_step() -> None:
    """§4, from the consuming side: nothing here turns an ask into a step.

    ``ActionPlan.steps`` is what the selection stage, the permission gate and the
    executor read, and a ``ReadAsk`` is not one of them — asserted structurally,
    because "reading the owner's own store is not an act in the world".
    """
    assert not issubclass(ReadAsk, PlanStep)
    plan = ActionPlan(
        id="plan-1",
        goal_id="goal-1",
        steps=(),
        created_at=_NOW,
        read_request=_query("an earlier exchange"),
    )
    assert plan.steps == ()


def test_the_ordinal_bound_keeps_a_long_label_off_int() -> None:
    """A model-supplied string of arbitrary length is not converted.

    Python refuses ``int()`` above 4,300 digits outright, so a label longer than any
    sequence could index must resolve to nothing *before* the conversion rather than
    by raising inside it — a turn is never failed by a label (§3).
    """
    assert resolve_label("M" + "1" * 5000, (_belief("a", "one"),)) is None


def test_an_ask_of_each_kind_is_the_most_one_request_carries() -> None:
    """§2: "One emission may carry **at most one ask of each kind**".

    Enforced by ``ReadRequest`` (Lane A). Asserted from the servicing side because
    §6's budget, precedence and audit are all stated over one ask per kind, so a
    second would have nowhere defined to go.
    """
    with pytest.raises(ValueError, match="at most one ask of each kind"):
        ReadRequest(
            asks=(
                ReadAsk(kind=ReadKind.SIGHTED_QUERY, query="one"),
                ReadAsk(kind=ReadKind.SIGHTED_QUERY, query="two"),
            )
        )


async def test_a_hop_and_a_query_reaching_nothing_is_not_a_failure() -> None:
    """Zero yield and zero failure are different facts, and the record says both."""
    memory = FakeMemoryStore(now=_clock)
    await memory.add(_belief("belief-1", "billing schedule notes"))
    planner = FakePlanner(now=_clock, read_request=_both("nothing matches this", "M4"))

    with structlog.testing.capture_logs() as captured:
        turn = (
            await _loop(memory, planner=planner).respond("billing schedule", narrow=_bounded())
        ).turn

    assert turn.memories == planner.calls[0][2]
    record = _record(captured)
    assert record["failed"] is False
    assert record["labels_unresolved"] == 1
    assert record["returned"] == 0


async def test_no_caller_can_raise_the_budget() -> None:
    """§6: "no configuration, setting or later lane makes the count configurable".

    An earlier draft of this lane took the budget as a keyword defaulted to
    :data:`READ_BUDGET`, which is exactly such a setting: reachable by any caller in
    this package and by any later lane, with the ratified ten as a mere default.
    There is no knob now, and this is what says so — the figure is read from the
    constant at one site, and §12 is where a decision to move it goes.
    """
    memory = FakeMemoryStore(now=_clock)
    await memory.add(_belief("belief-1", "billing schedule notes"))

    with pytest.raises(TypeError, match="budget"):
        await service_read_request(
            memory,
            _query("billing schedule notes"),
            supply=(),
            audit=TurnReadAudit(),
            budget=100,  # type: ignore[call-arg]  # the point of the case
        )


async def test_no_caller_can_declare_an_unbounded_turn_bounded() -> None:
    """§5 is fail-closed, so the posture is not a second fact beside the filter.

    An earlier draft took the audience as a boolean argument beside ``narrow``. The
    two are then independently caller-controlled, and the contradictory pair — an
    ``UnboundedAudienceSupply`` declared bounded — would service a request on the
    one channel §5 refuses **and** apply the subtraction after planning rather than
    before it, so the planner's own prompt would carry what ADR-0203 §1 withholds.
    The pair does not exist: the posture is read off the supply object, which is the
    only thing that carries it.
    """
    memory = FakeMemoryStore(now=_clock)
    await memory.add(_belief("belief-1", "billing schedule notes", evidence=("cited-1",)))
    await memory.add(_belief("cited-1", "an earlier exchange"))
    planner = FakePlanner(now=_clock, read_request=_hop("M1"))
    loop = _loop(memory, planner=planner)

    with pytest.raises(TypeError, match="bounded_audience"):
        await loop.respond(
            "billing schedule",
            narrow=_unbounded(),
            bounded_audience=True,  # type: ignore[call-arg]  # the point of the case
        )


async def test_a_cancellation_inside_the_servicing_is_not_audited_as_a_completed_read() -> None:
    """§9's counts are "taken over a servicing that completed", and this one did not.

    A cancellation is not a ``MemoryStoreError``, so it passes through the servicer's
    degradation and out of the turn — and §9's record is emitted from a ``finally``,
    which is the whole point of it. Without the failure being recorded *before* the
    await, that record would say a fired, serviced turn that returned nothing: a true
    fire with no read under it, sitting in §8's novelty denominator and
    indistinguishable from a hop whose citations had all expired.

    The cancellation itself still propagates, unabsorbed: nothing here makes a
    cancelled turn look like a turn.
    """
    memory = FakeMemoryStore(now=_clock)
    await memory.add(_belief("belief-1", "billing schedule notes", evidence=("cited-1",)))
    await memory.add(_belief("cited-1", "an earlier exchange"))
    planner = _SuspendingPlanner(memory, _hop("M1"))
    loop = _loop(memory, planner=planner)

    with structlog.testing.capture_logs() as captured:
        turn = asyncio.ensure_future(loop.respond("billing schedule", narrow=_bounded()))
        held = await planner.armed()
        await held.reached()
        turn.cancel()
        held.release()
        with pytest.raises(asyncio.CancelledError):
            await turn

    record = _record(captured)
    assert record["trigger"] == TriggerOutcome.FIRED.value
    assert record["servicing"] == Servicing.SERVICED.value
    assert record["failed"] is True
    assert record["new"] == 0
    assert record["returned"] == 0


async def test_an_unexpected_failure_inside_the_servicing_is_recorded_as_a_failure() -> None:
    """The same rule over the paths a store contract does not name.

    ``MemoryStoreError`` is what the contract states and what §5 degrades; anything
    else is a fault rather than a degradation and takes the turn down. What it must
    not do is take it down while the audit says the read completed.
    """

    class _Faulty(FakeMemoryStore):
        async def get_many(self, record_ids: Sequence[str]) -> Mapping[str, MemoryRecord]:
            del record_ids
            msg = "fake: something no contract describes"
            raise RuntimeError(msg)

    memory = _Faulty(now=_clock)
    await memory.add(_belief("belief-1", "billing schedule notes", evidence=("cited-1",)))
    planner = FakePlanner(now=_clock, read_request=_hop("M1"))

    with (
        structlog.testing.capture_logs() as captured,
        pytest.raises(RuntimeError, match="no contract describes"),
    ):
        await _loop(memory, planner=planner).respond("billing schedule", narrow=_bounded())

    record = _record(captured)
    assert record["failed"] is True
    assert record["returned"] == 0


def test_the_two_postures_are_the_only_two_and_cannot_be_subclassed() -> None:
    """ADR-0199 §1's closed question, closed mechanically (ADR-0226 §5).

    The loop reads the channel's audience off the filter's **exact** type in order to
    decide whether a request is serviced, so a subtype is not a third answer: a class
    inheriting :class:`BoundedAudienceSupply` and overriding ``__call__`` to subtract
    would be classified bounded and would put withheld records in the planner's own
    prompt. ``@final`` is what stops one being written — `mypy` refuses the subclass
    where it is declared, over ``src/`` and ``tests/`` alike — and the runtime test
    declines it besides, which is the fail-closed direction.

    A genuine third posture is a new *audience*, and ADR-0199 §1 puts that behind its
    own decision rather than behind a subclass.
    """
    assert getattr(BoundedAudienceSupply, "__final__", False) is True
    assert getattr(UnboundedAudienceSupply, "__final__", False) is True
    assert set(get_args(TurnSupply.__value__)) == {
        BoundedAudienceSupply,
        UnboundedAudienceSupply,
    }


async def test_a_cancellation_after_the_hop_returned_records_the_partial_fact() -> None:
    """§9's pair, on the path §5 does not degrade.

    The hop's keyed load returns; the sighted query's first band is then cancelled.
    Nothing reached the turn — §5 discards a partial read with the rest — but the
    record must still say *that a read had already returned when the failure landed*,
    which is the only thing distinguishing a partial servicing from a total one.
    Reporting by return value cannot carry that fact off a path that does not return,
    which is why the servicer writes its record instead.
    """
    memory = _SuspendAfterKeyedLoad()
    await memory.add(_belief("belief-1", "billing schedule notes", evidence=("cited-1",)))
    await memory.add(_belief("cited-1", "an earlier exchange"))
    planner = FakePlanner(now=_clock, read_request=_both("earlier exchange", "M1"))
    loop = _loop(memory, planner=planner)

    with structlog.testing.capture_logs() as captured:
        turn = asyncio.ensure_future(loop.respond("billing schedule", narrow=_bounded()))
        held = await memory.armed()
        await held.reached()
        turn.cancel()
        held.release()
        with pytest.raises(asyncio.CancelledError):
            await turn

    record = _record(captured)
    assert record["failed"] is True
    assert record["failed_after_read_returned"] is True
    assert record["returned"] == 0
    assert record["new"] == 0


async def test_a_cancellation_after_a_query_band_returned_records_the_partial_fact() -> None:
    """The same, over a request carrying only a ``SIGHTED_QUERY``.

    §9 states the field over **reads** and not over asks precisely because this shape
    exists: one ask, several ``MemoryStore.search`` calls, and a failure between two
    of them that a field keyed on asks would call total. The fourth search is the
    servicing's own first band — the turn's belief composition has already read three.
    """
    memory = _SuspendAfterNthSearch(nth=4)
    await memory.add(
        _belief("belief-1", "billing schedule notes", source=MemorySource.USER_ASSERTED)
    )
    planner = FakePlanner(now=_clock, read_request=_query("billing schedule notes"))
    loop = _loop(memory, planner=planner)

    with structlog.testing.capture_logs() as captured:
        turn = asyncio.ensure_future(loop.respond("billing schedule", narrow=_bounded()))
        held = await memory.armed()
        await held.reached()
        turn.cancel()
        held.release()
        with pytest.raises(asyncio.CancelledError):
            await turn

    record = _record(captured)
    assert record["failed"] is True
    assert record["failed_after_read_returned"] is True
    assert record["returned"] == 0


# --------------------------------------------------------------------------- #
# ADR-0227 §3: the carrier this servicer states, and what it holds             #
# --------------------------------------------------------------------------- #
#
# The render rule ADR-0227 §1 adds turns on *which records this turn's citation hop
# reached*, and §3 rules that fact "recorded where the kind is known — at the
# servicer, which is the one place ``CITATION_HOP`` and ``SIGHTED_QUERY`` are
# distinguishable". These are that half of the rule; ``test_composing.py`` holds the
# render site's, and ``test_engine_read_envelope.py`` drives both end to end.


async def test_the_carrier_names_what_the_hop_reached_in_the_asks_own_order() -> None:
    """ADR-0227 §3: labels in the ask's order, each record's evidence in stored order.

    "It is an **ordered** carrier, because §4's cap is taken over it in that order" —
    and the order §4 takes it in is ADR-0226 §6's own, which that section rules is
    what makes two conforming implementations append the same records in the same
    order. The sighted query's records are **not** in it (ADR-0227 §2): they were
    selected by relevance against a key their replies are not in, so ADR-0222 §2's
    first reason reaches them in its own words.
    """
    memory = FakeMemoryStore(now=_clock)
    await memory.add(_belief("belief-1", "billing schedule notes", evidence=("cited-2", "cited-1")))
    await memory.add(_belief("belief-2", "billing notes", evidence=("cited-3",)))
    for cited in ("cited-1", "cited-2", "cited-3"):
        await memory.add(_episode(cited, "an earlier exchange"))
    await memory.add(_belief("found-1", "the kestrel report"))
    planner = FakePlanner(now=_clock, read_request=_both("the kestrel report", "M1", "M2"))

    responded = await _loop(memory, planner=planner).respond(
        "billing schedule notes", narrow=_bounded()
    )

    assert _ids(responded.turn.memories) == [
        "belief-1",
        "belief-2",
        "cited-2",
        "cited-1",
        "cited-3",
        "found-1",
    ]
    assert responded.hop_reached == ("cited-2", "cited-1", "cited-3")


async def test_a_deduplicated_out_record_is_carried_and_a_budget_cut_one_is_not() -> None:
    """ADR-0227 §1's third clause and §4's silence, at the seam that decides both.

    §3 carries "the **distinct** records the hop resolved that the turn's supply holds
    after servicing, the deduplicated-out ones included". A record the supply already
    held keeps its position (ADR-0226 §7) and still renders its reply — "the exact
    record a belief cites would render phrase-only whenever the episodic supplement
    happened to have picked it up already, and the turn would fail for the same reason
    #1944 records, by a narrower route that no probe would distinguish from success".

    A record ADR-0226 §6's budget **cut**, by contrast, is not in the supply at all,
    so it is not carried: §4 rules that such records "render nothing at all — no
    bullet, no phrase line and no reply line".
    """
    memory = FakeMemoryStore(now=_clock)
    cited = tuple(f"cited-{n}" for n in range(READ_BUDGET + 2))
    await memory.add(_belief("belief-1", "billing schedule notes", evidence=cited))
    for record_id in cited:
        await memory.add(_episode(record_id, "an earlier exchange about billing"))
    planner = FakePlanner(now=_clock, read_request=_hop("M1"))

    responded = await _loop(memory, planner=planner).respond("billing schedule", narrow=_bounded())

    assert responded.hop_reached == cited[:READ_BUDGET], "the budget cut the last two"
    assert set(responded.hop_reached) <= {record.id for record in responded.turn.memories}


async def test_a_record_the_supply_already_held_stays_in_the_carrier() -> None:
    """The pair to the case above: deduplication removes a record from the *group*, not
    from the carrier.

    The cited episode is in the conversation tail this turn was handed, so ADR-0226
    §7's deduplication keeps "the copy the supply already held … its position" and the
    fourth group is empty. ADR-0227 §1 renders it all the same, because the test is
    "reached by the citation hop" and not which group a record ended up in.
    """
    memory = FakeMemoryStore(now=_clock)
    await memory.add(_belief("belief-1", "billing schedule notes", evidence=("cited-1",)))
    await memory.add(_episode("cited-1", "an earlier exchange about billing"))
    tail = _episode("cited-1", "an earlier exchange about billing")
    planner = FakePlanner(now=_clock, read_request=_hop("M2"))

    responded = await _loop(memory, planner=planner).respond(
        "billing schedule", history=(tail,), narrow=_bounded()
    )

    assert _ids(responded.turn.memories) == ["cited-1", "belief-1"], "no fourth group"
    assert responded.hop_reached == ("cited-1",)


async def test_a_repeated_citation_is_one_entry_of_the_carrier() -> None:
    """ADR-0227 §8's assertion 14 at the servicer: ``(A, A, …, B)`` is two records.

    ``Provenance.evidence`` is a ``tuple`` with no uniqueness constraint, and
    ``_hop_records`` rebuilds its answer by walking each record's evidence in stored
    order — so a repeated citation yields the same record twice, and ADR-0226 §7's
    deduplication removes it only later, at the union. §3 makes the carrier
    **distinct** here, and §4 restates the deduplication ahead of the cap, so a
    list-first cap cannot spend ten positions on one record.

    The evidence is deliberately :data:`READ_BUDGET` repeats of ``A`` before ``B``,
    which is exactly the length §8 asks for: an implementation carrying the repeats
    would render one line where the decision requires two.
    """
    memory = FakeMemoryStore(now=_clock)
    await memory.add(
        _belief("belief-1", "billing schedule notes", evidence=("cited-1",) * READ_BUDGET)
    )
    await memory.add(_belief("belief-2", "billing notes", evidence=("cited-1", "cited-2")))
    await memory.add(_episode("cited-1", "an earlier exchange"))
    await memory.add(_episode("cited-2", "a later exchange"))
    planner = FakePlanner(now=_clock, read_request=_hop("M1", "M2"))

    responded = await _loop(memory, planner=planner).respond(
        "billing schedule notes", narrow=_bounded()
    )

    assert responded.hop_reached == ("cited-1", "cited-2")
    assert _ids(responded.turn.memories) == ["belief-1", "belief-2", "cited-1", "cited-2"]


async def test_the_carrier_is_empty_on_every_turn_that_serviced_no_hop() -> None:
    """ADR-0227 §3's last clause, over the four shapes it names.

    "The set is **empty** on every turn that did not fire, on a turn whose servicing
    ADR-0226 §5 declined, on a turn whose servicing failed or was partial … and on a
    turn whose hop resolved no live record." Each is asserted here, and what follows
    from all four is §8's assertion 8: an empty carrier "renders no reply line
    anywhere, and the assembled prompt is then byte-identical to what it is today".
    """
    seeded = _belief("belief-1", "billing schedule notes", evidence=("cited-1",))
    cited = _episode("cited-1", "an earlier exchange about billing")

    quiet = FakeMemoryStore(now=_clock)
    await quiet.add(seeded)
    await quiet.add(cited)
    not_fired = await _loop(quiet).respond("billing schedule", narrow=_bounded())

    planner = FakePlanner(now=_clock, read_request=_hop("M1"))
    declined = await _loop(quiet, planner=planner).respond("billing schedule", narrow=_unbounded())

    failing = _FailingKeyedLoad(now=_clock)
    await failing.add(seeded)
    await failing.add(cited)
    failed = await _loop(failing, planner=planner).respond("billing schedule", narrow=_bounded())

    barren = FakeMemoryStore(now=_clock)
    await barren.add(_belief("belief-1", "billing schedule notes", evidence=("gone-1",)))
    nothing = await _loop(barren, planner=planner).respond("billing schedule", narrow=_bounded())

    assert not_fired.hop_reached == ()
    assert declined.hop_reached == ()
    assert failed.hop_reached == ()
    assert nothing.hop_reached == ()
    assert _ids(failed.turn.memories) == ["belief-1"], "the supply is as planning saw it"


async def test_no_identifier_the_carrier_holds_reaches_the_audit() -> None:
    """ADR-0227 §8's assertion 16 at the servicer, and §3's namer rule entire.

    "No record identifier reaches a model and none is accepted from one … the
    identifiers in it are held data, used to decide which line the assembler writes,
    and they are rendered into no prompt, no log, no trace and no audit record."
    ADR-0226 §9's record carries counts, kinds and the correlation id, and threading a
    render decision through it "would put record identifiers on a surface whose whole
    discipline is that they are not there" — which is why the carrier is returned
    rather than written onto it.
    """
    memory = FakeMemoryStore(now=_clock)
    await memory.add(_belief("belief-1", "billing schedule notes", evidence=("cited-1",)))
    await memory.add(_episode("cited-1", "an earlier exchange about billing"))
    planner = FakePlanner(now=_clock, read_request=_hop("M1"))

    with structlog.testing.capture_logs() as captured:
        responded = await _loop(memory, planner=planner).respond(
            "billing schedule", narrow=_bounded()
        )

    assert responded.hop_reached == ("cited-1",)
    record = _record(captured)
    assert record["new"] == 1
    assert "cited-1" not in str(record), "the audit names no record"
    assert not any("cited-1" in str(event) for event in captured), "and neither does any log event"
