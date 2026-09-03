"""ADR-0228 at the loop: a serviced read may revise the plan once.

The turn-shaped half of §13's eighteen. What lives here is everything decided
inside :class:`~ai_assistant.orchestration.loop.LearningLoop` — §2's seven
conditions, §3's bound, §4's budget, §7's monotone supply and single fourth group,
§8's per-call label space, §9's raised audit and §10's carrier. The engine-shaped
half — persistence, driving, capture and the composed reply — is
``test_engine_revision.py``.

**The helpers are ``test_loop_reads``'s**, imported rather than restated: this is
the same loop over the same store shapes, one milestone on, and a second set of
record builders would be a second statement of what a belief with evidence looks
like.
"""

from __future__ import annotations

import inspect
from datetime import timedelta
from typing import TYPE_CHECKING, Any, Final

import pytest
import structlog
from test_loop_reads import (
    _NOW,
    _belief,
    _both,
    _bounded,
    _clock,
    _episode,
    _hop,
    _ids,
    _Journal,
    _loop,
    _prompt_over,
    _query,
    _record,
    _records,
    _unbounded,
)

from ai_assistant.core.errors import MemoryStoreError, PlanningError
from ai_assistant.core.types import (
    ActionPlan,
    MemorySource,
    PlanStep,
    ReadKind,
    ReadRequest,
    Role,
)
from ai_assistant.orchestration.composing import ComposingStage
from ai_assistant.orchestration.loop import ConversationalOperation, LearningLoop
from ai_assistant.orchestration.reads import (
    READ_BUDGET,
    Servicing,
    StopReason,
    TriggerOutcome,
)
from ai_assistant.testing import FakeMemoryStore, FakeModelProvider, FakeStreamingCompleter

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from datetime import datetime

    from ai_assistant.core.clock import Clock
    from ai_assistant.core.types import (
        BeliefBand,
        CurrentContext,
        Goal,
        MemoryKind,
        MemoryRecord,
        MemorySearchResult,
    )
    from ai_assistant.orchestration.loop import RespondedTurn

#: ADR-0228 §4's figure for ``converse`` and ``converse_streaming``, read off the
#: member that declares it rather than restated — so a case that reads as "exactly at
#: the budget" cannot drift from the figure the loop actually enforces.
_BUDGET: Final = ConversationalOperation.CONVERSE.planning_budget
assert _BUDGET is not None


# --------------------------------------------------------------------------- #
# Planners that answer a turn's two calls differently                          #
# --------------------------------------------------------------------------- #


class _Script:
    """A ``Planner`` answering each call of a turn from a script.

    ADR-0228 §3 admits two calls per turn, so a planner a case can steer *per call*
    is what most of §13 needs — the milestone's own shape is a first plan that
    cannot name a value and a second that carries it. It records the supply and the
    vocabulary each call was handed, which is how §7's monotonicity and §8's label
    space are asserted.

    **It mints a fresh id per call**, because ADR-0014 §2's "re-planning produces a
    *new* ``ActionPlan`` with a new ``id``" binds within a turn under §3 and a
    planner reusing one would fail its consumer for its own defect.

    **And it is not told which iteration it is on.** The ordinal it reads is its own
    script pointer, never an input to a decision: ADR-0228 §12 rules that no lane
    adds an iteration index, a "last look" instruction or any other signal to the
    planner's input, and this class takes nothing from the loop it did not take
    before this milestone.
    """

    def __init__(
        self,
        *,
        requests: Sequence[ReadRequest | None] = (),
        steps: Sequence[tuple[PlanStep, ...]] = (),
        supersedes: Sequence[str | None] = (),
        raises: int | None = None,
        on_call: Callable[[], None] | None = None,
    ) -> None:
        """Script one planner.

        Args:
            requests: What each call emits, by 0-based call index. A call past the
                end emits the **last** scripted value, so a one-element script is a
                planner that asks the same thing every time.
            steps: What each call's plan carries, by the same indexing and the same
                run-off rule. Defaults to no steps on every call.
            supersedes: What each call's plan comes back **already carrying** in the
                field the loop owns (ADR-0228 §5) — the spoof §13 item 10 asserts is
                discarded. Defaults to ``None``, which is what a conforming planner
                returns.
            raises: A 0-based call index that raises ``PlanningError`` instead of
                answering, or ``None``. §9's fifth stop reason is about exactly this.
            on_call: Run after answering each call, or ``None``. The hook a case takes
                to move the injected clock **during** a planner call, which is how
                ADR-0228 §4's overrun arm is asserted.
        """
        self._requests = requests
        self._steps = steps
        self._supersedes = supersedes
        self._raises = raises
        self._on_call = on_call
        self.calls: list[tuple[tuple[MemoryRecord, ...], tuple[str, ...]]] = []

    @staticmethod
    def _at[T](script: Sequence[T], ordinal: int, default: T) -> T:
        if not script:
            return default
        return script[ordinal] if ordinal < len(script) else script[-1]

    async def plan(
        self,
        goal: Goal,
        *,
        context: CurrentContext,
        memories: Sequence[MemoryRecord] = (),
        capabilities: Sequence[str],
    ) -> ActionPlan:
        """Answer this call from the script, recording what it was handed."""
        ordinal = len(self.calls)
        self.calls.append((tuple(memories), tuple(capabilities)))
        if self._raises == ordinal:
            msg = "the planner is down"
            raise PlanningError(msg)
        if self._on_call is not None:
            self._on_call()
        return ActionPlan(
            id=f"{goal.id}-plan-{ordinal + 1}",
            goal_id=goal.id,
            steps=self._at(self._steps, ordinal, ()),
            created_at=_NOW,
            rationale=f"call {ordinal + 1}",
            read_request=self._at(self._requests, ordinal, None),
            supersedes=self._at(self._supersedes, ordinal, None),
        )


class _Elapsed:
    """A clock reading ``_NOW`` at the turn's entry and ``_NOW + elapsed`` after it.

    ADR-0228 §4's budget is measured against the loop's **injected** clock, so every
    arm of §13's third test is deterministic rather than timing-sensitive: whatever
    else the turn reads the clock for, the reading the budget check sees is exactly
    ``elapsed`` past the reading taken at entry.

    ``elapsed`` is public and mutable so a case can move the clock **during** a
    planner call — which is how §4's stated cost is asserted: a call already begun
    runs to its own completion, and a turn's total duration may exceed its budget by
    one planner call and one servicing.
    """

    def __init__(self, elapsed: timedelta) -> None:
        self.elapsed = elapsed
        self.readings = 0

    def __call__(self) -> datetime:
        """The next reading."""
        reading = _NOW if self.readings == 0 else _NOW + self.elapsed
        self.readings += 1
        return reading


def _step(capability: str = "send_email", **parameters: object) -> PlanStep:
    return PlanStep(
        id="step-1",
        intent="send the note",
        capability=capability,
        parameters=parameters,  # type: ignore[arg-type]  # heterogeneous test arguments
    )


#: What every case here asks. **One distinctive term**, because the fake store scores
#: a record by the fraction of query terms appearing as substrings of its content: a
#: multi-word utterance retrieves anything sharing a common word, and a case's
#: "records the servicing added" would then be records the turn's own belief read had
#: already retrieved. Seeds meant for the fourth group are lexically disjoint from
#: this, and seeds meant for the retrieved group carry it.
_ASKED: Final = "lease"


async def _seeded() -> _Journal:
    """A store whose retrieved belief cites an episode the hop can reach.

    The episode is safe as fourth-group material whatever it says: retrieval selects
    ``BELIEF_KINDS`` and never ``EPISODIC`` (ADR-0074 §6), and :func:`_loop` turns the
    episodic supplement off, so nothing but a servicing can put one in the supply.
    """
    memory = _Journal()
    await memory.add(_belief("belief-1", "the lease question", evidence=("episode-1",)))
    await memory.add(_episode("episode-1", "Ada: the flat was on Rua da Boavista."))
    return memory


async def _system_prompt_over(responded: RespondedTurn) -> str:
    """The **system** prompt the production renderer assembles for one turn.

    ADR-0228 §10's clause is an instruction about how to answer, so it lands in the
    system message where ADR-0199 §5's deflection shape does. Assembled by the
    production :class:`~ai_assistant.orchestration.composing.ComposingStage` under
    ADR-0227 §7's fidelity rule — a fake that cannot fail to carry the clause would
    assert nothing — with a fake ``ModelProvider`` merely recording what it was sent.

    Args:
        responded: What the turn produced, carrying §10's fact.

    Returns:
        The system message's content.
    """
    model = FakeModelProvider("answer")
    stage = ComposingStage(model=model, streaming=FakeStreamingCompleter())
    await stage.compose(
        turn=responded.turn,
        step=None,
        undriven=(),
        hop_reached=responded.hop_reached,
        stopped_while_asking=responded.stopped_while_asking,
    )
    [call] = model.calls
    return next(one.content for one in call.messages if one.role is Role.SYSTEM)


async def _revising(
    memory: FakeMemoryStore,
    planner: _Script,
    *,
    operation: ConversationalOperation | None = ConversationalOperation.CONVERSE,
    now: Clock = _clock,
    narrow: Any = None,
) -> RespondedTurn:
    """Run one turn of a budgeted, bounded-audience operation.

    Args:
        memory: The store the turn reads and the servicer hops through.
        planner: The scripted planner.
        operation: Which operation the turn runs under (ADR-0228 §4). ``None`` names
            no operation, which declares no budget and therefore does not iterate —
            the identity crosses this seam and never a duration, so a case says which
            operation it is rather than choosing a figure no ADR ruled on.
        now: The loop's injected clock.
        narrow: The supply filter, defaulting to the one ``converse`` supplies.

    Returns:
        What the turn produced.
    """
    loop = _loop(memory, planner=planner, now=now)
    return await loop.respond(
        _ASKED,
        narrow=_bounded() if narrow is None else narrow,
        operation=operation,
    )


# --------------------------------------------------------------------------- #
# §13 item 3: the budget is reached, and its four further arms                 #
# --------------------------------------------------------------------------- #


async def test_the_budget_stops_the_turn_and_the_reply_says_so() -> None:
    """§4's guard fires, §9 records it, and §10 reaches the assembled prompt.

    The clock passes the operation's budget between the first planner call and §2's
    check, so the turn makes **one** call, keeps the plan it has, and tells the
    composing stage the bare fact that it stopped looking while it was still asking.
    Asserted through the production renderer under ADR-0227 §7's fidelity rule: what
    §10 guarantees is about the prompt this system actually assembles, and a fake
    that cannot fail to carry the clause would assert nothing.
    """
    memory = await _seeded()
    planner = _Script(requests=[_hop("M1")])

    with structlog.testing.capture_logs() as captured:
        responded = await _revising(memory, planner, now=_Elapsed(timedelta(seconds=25)))

    assert len(planner.calls) == 1, "the budget was spent before the second call"
    record = _record(captured)
    assert record["stop"] == StopReason.BUDGET_REACHED.value
    assert record["planner_calls"] == 1
    assert record["trigger"] == TriggerOutcome.FIRED.value
    assert responded.stopped_while_asking is True
    assert "stopped before you could" in await _system_prompt_over(responded)


@pytest.mark.parametrize(
    ("elapsed", "calls", "stop"),
    [
        (timedelta(seconds=20), 1, StopReason.BUDGET_REACHED),
        (timedelta(seconds=20, microseconds=-1), 2, StopReason.BOUND_REACHED),
    ],
    ids=["exactly-at-the-budget", "one-tick-below-it"],
)
async def test_the_boundary_instant_is_spent_not_available(
    elapsed: timedelta, calls: int, stop: StopReason
) -> None:
    """§4's closed boundary, both sides of it, on an injected clock.

    "An additional call is admitted **only while** the elapsed time is strictly less
    than the budget: at exactly the budget, and beyond it, the turn stops." §4 closes
    it in the implementation rather than leaving it open because "leaving equality to
    the implementation would let two conforming loops differ on identical input — one
    spending a model call the other refuses, with a different reply, a different cost
    and a different audit record", and an injected clock makes equality an ordinary
    case in a test rather than a measure-zero curiosity.
    """
    memory = await _seeded()
    planner = _Script(requests=[_hop("M1")])

    with structlog.testing.capture_logs() as captured:
        await _revising(memory, planner, now=_Elapsed(elapsed))

    assert len(planner.calls) == calls
    assert _record(captured)["stop"] == stop.value


async def test_a_planner_call_that_overruns_the_budget_is_not_abandoned() -> None:
    """§4's stated cost, asserted rather than assumed.

    The budget "is a gate on **starting** an iteration and never a cancellation of
    one in flight: a planner call already begun runs to its own completion, and a
    turn's total duration may therefore exceed its budget by one planner call and
    one servicing". The clock is one tick below the budget when the second call is
    admitted and far past it by the time that call returns; the turn keeps the plan
    the call produced and drives it.
    """
    memory = await _seeded()
    overrun = _Elapsed(timedelta(seconds=19))
    planner = _Script(requests=[_hop("M1"), None], steps=[(), (_step(),)])

    responded = await _revising(memory, planner, now=overrun)

    assert len(planner.calls) == 2
    assert responded.turn.plan.steps == (_step(),), "the overrunning call's plan stands"
    assert len(responded.plans) == 2


async def test_the_budget_runs_from_the_turns_entry_and_not_from_the_first_plan() -> None:
    """§13 item 3's fifth arm: the budget's **origin** is entry into the loop.

    "A turn whose work *before* the first plan — context assembly, the two relevance
    reads, the first planner call itself — already consumes the budget starts **no**
    second call." This is the assertion an implementation timing from the first
    plan's *return* would fail while satisfying every arm above: such an
    implementation would read its clock afresh after the plan came back and find no
    time spent at all.

    The clock here advances the whole budget on its **first** reading after entry, so
    a loop measuring from entry sees the budget spent and a loop measuring from the
    plan's return sees nothing spent.
    """
    memory = await _seeded()
    planner = _Script(requests=[_hop("M1")])

    with structlog.testing.capture_logs() as captured:
        await _revising(memory, planner, now=_Elapsed(timedelta(seconds=21)))

    assert len(planner.calls) == 1, "the turn's first phase had already spent the budget"
    assert _record(captured)["stop"] == StopReason.BUDGET_REACHED.value


# --------------------------------------------------------------------------- #
# §13 item 4: a servicing that adds nothing does not revise                    #
# --------------------------------------------------------------------------- #


async def test_a_servicing_that_adds_nothing_does_not_revise() -> None:
    """§2(e): a byte-identical supply is not a second question.

    "A servicing whose every record was deduplicated out leaves the supply
    byte-identical, and a planner called twice over one input is being asked the same
    question twice at the price of a model round trip." The hop names a belief whose
    evidence is a record the supply already holds, so every returned record
    deduplicates away.

    **And the condition is not merely thrift** (§2). §9's iteration rate would count
    a turn that learned nothing as a turn that looked again, so making the condition
    the arrival of new material is what keeps the number honest.
    """
    memory = _Journal()
    await memory.add(_belief("belief-1", "the lease question", evidence=("belief-2",)))
    # Carries the asked term, so the turn's own belief read retrieves it and the hop
    # reaches nothing the supply does not already hold.
    await memory.add(_belief("belief-2", "the lease was signed in March"))
    planner = _Script(requests=[_hop("M1")])

    with structlog.testing.capture_logs() as captured:
        responded = await _revising(memory, planner)

    assert len(planner.calls) == 1
    assert len(memory.keyed) == 1, "no second store read"
    supplied = _ids(responded.turn.memories)
    assert supplied == ["belief-1", "belief-2"], "the supply is what one servicing left"
    record = _record(captured)
    assert record["stop"] == StopReason.NOT_ITERATED.value
    assert record["servicings"][0]["new"] == 0
    assert record["servicings"][0]["deduplicated"] == 1


# --------------------------------------------------------------------------- #
# §13 item 5: a failed and a partial servicing do not revise                   #
# --------------------------------------------------------------------------- #


class _FailingKeyed(FakeMemoryStore):
    """ADR-0226 §5's first arm: the servicing's first store call raises."""

    def __init__(self) -> None:
        super().__init__(now=_clock)

    async def get_many(self, record_ids: Sequence[str]) -> dict[str, MemoryRecord]:
        msg = "the keyed load is down"
        raise MemoryStoreError(msg)


class _FailingAfterHop(FakeMemoryStore):
    """§5's second arm: the hop returns and the query then raises."""

    def __init__(self) -> None:
        super().__init__(now=_clock)
        self._searches = 0

    async def search(
        self,
        query: str,
        *,
        limit: int = 10,
        kinds: Sequence[MemoryKind] | None = None,
        bands: Sequence[BeliefBand] | None = None,
    ) -> MemorySearchResult:
        self._searches += 1
        # The turn's own belief composition reads three bands before the servicing
        # reaches its first, so the fourth search is the query's.
        if self._searches > 3:
            msg = "the query is down"
            raise MemoryStoreError(msg)
        return await super().search(query, limit=limit, kinds=kinds, bands=bands)


class _FailingLaterBand(FakeMemoryStore):
    """§5's third arm: a later band raises after an earlier one returned.

    Keyed on the **observation** rather than on a search count, so the arm is the one
    ADR-0226 §9 states — "whether a read it had already performed had returned
    records" — by construction rather than by a case getting the band arithmetic
    right. The turn's own belief composition reads three bands before the servicing
    reaches its first, so only a search past those can be the query's.
    """

    def __init__(self) -> None:
        super().__init__(now=_clock)
        self._searches = 0
        self._returned = False

    async def search(
        self,
        query: str,
        *,
        limit: int = 10,
        kinds: Sequence[MemoryKind] | None = None,
        bands: Sequence[BeliefBand] | None = None,
    ) -> MemorySearchResult:
        self._searches += 1
        if self._searches > 3 and self._returned:
            msg = "a later band is down"
            raise MemoryStoreError(msg)
        found = await super().search(query, limit=limit, kinds=kinds, bands=bands)
        self._returned = self._returned or (self._searches > 3 and bool(found.records))
        return found


@pytest.mark.parametrize(
    ("store", "request_", "partial"),
    [
        (_FailingKeyed, _hop("M1"), False),
        (_FailingAfterHop, _both("Boavista", "M1"), True),
        (_FailingLaterBand, _query("Boavista"), True),
    ],
    ids=["keyed-load-raises", "hop-returned-then-query-raised", "later-band-raised"],
)
async def test_a_failed_or_partial_servicing_does_not_revise(
    store: type[FakeMemoryStore], request_: ReadRequest, partial: bool
) -> None:
    """§2(d), over ADR-0226 §5's three arms.

    "A servicing that failed or was partial leaves the supply as planning saw it
    (ADR-0226 §5), so there is nothing new to plan over and a second call would be
    handed the first call's own input." §2(d) follows that all-or-nothing posture
    rather than softening it: a partial servicing on §5's terms returned *nothing* to
    the turn, so a revision fired on one would be a second plan over a supply the
    corpus says the turn never received.
    """
    memory = store()
    await memory.add(_belief("belief-1", "the lease question", evidence=("episode-1",)))
    await memory.add(_episode("episode-1", "Ada: the flat was on Rua da Boavista."))
    # Two beliefs the *query* reaches and the turn's own read does not, in different
    # confidence bands — so an earlier band of the servicing's own composition has
    # records to return before a later one raises, whichever end the composition
    # starts from.
    await memory.add(_belief("found-1", "Boavista paperwork", source=MemorySource.USER_ASSERTED))
    await memory.add(_belief("found-2", "Boavista inventory"))
    planner = _Script(requests=[request_])

    with structlog.testing.capture_logs() as captured:
        responded = await _revising(memory, planner)

    assert len(planner.calls) == 1
    assert responded.turn.memories == planner.calls[0][0], "the supply planning saw"
    record = _record(captured)
    assert record["stop"] == StopReason.NOT_ITERATED.value
    entry = record["servicings"][0]
    assert entry["failed"] is True
    assert entry["failed_after_read_returned"] is partial


# --------------------------------------------------------------------------- #
# §13 item 6: an operation that declares no budget does not iterate            #
# --------------------------------------------------------------------------- #


async def test_a_bounded_audience_operation_that_declares_no_budget_does_not_iterate() -> None:
    """§2(a), on a turn whose every *other* condition holds.

    §13 item 6 asks for this arm on a **bounded-audience** operation precisely so
    that it is about the declaration and not about the audience: the request is
    serviced, the servicing completes, it returns a record the supply did not hold,
    the turn is under the bound — and the turn still makes one planner call, because
    the operation declared no budget.

    "No implementation reads an absent declaration as a default, as
    unknown-and-therefore-permitted, or as a case to decide at run time from anything
    other than a declaration" (§2(a)). A lane that adds an operation and forgets to
    price it gets the turn the system already has.
    """
    memory = await _seeded()
    planner = _Script(requests=[_hop("M1")])

    with structlog.testing.capture_logs() as captured:
        responded = await _revising(memory, planner, operation=None)

    assert len(planner.calls) == 1
    record = _record(captured)
    assert record["stop"] == StopReason.NOT_ITERATED.value
    assert record["servicings"][0]["new"] == 1, "every other condition held"
    assert _ids(responded.turn.memories) == ["belief-1", "episode-1"], "serviced all the same"


async def test_an_unbounded_audience_turn_fails_the_servicing_condition_too() -> None:
    """§2(c) beside §2(a), which is the ``converse_spoken`` shape.

    ADR-0226 §5 declines to service a read request on an operation whose output
    channel's audience is unbounded, so §2(c) fails and there is nothing to revise
    over; ADR-0228 §4 declares that operation **no** budget, so §2(a) fails as well.
    Two independent reasons, which is why §14 defers a revision there by name and why
    no lane reads a thin spoken reply as firing it.
    """
    memory = await _seeded()
    planner = _Script(requests=[_hop("M1")])

    with structlog.testing.capture_logs() as captured:
        responded = await _revising(memory, planner, operation=None, narrow=_unbounded())

    assert len(planner.calls) == 1
    record = _record(captured)
    assert record["servicing"] == Servicing.DECLINED.value
    assert record["servicings"] == (), "nothing was serviced, so there is no entry"
    assert record["stop"] == StopReason.NOT_ITERATED.value
    assert responded.turn.memories == planner.calls[0][0], "no fourth group"


# --------------------------------------------------------------------------- #
# §13 item 7: the label space is the sequence passed on that call              #
# --------------------------------------------------------------------------- #


async def test_the_label_space_is_the_sequence_passed_on_that_call() -> None:
    """§8: ADR-0226 §3's labelling binds each call separately and as written.

    Three things, over one turn that services twice.

    **The same label string resolves to different records on a turn's two calls** —
    which it does not here, because the three groups keep their positions (§7), so
    the assertion is the sharper one available: a label naming a record the **first
    servicing added** resolves on the second call and named something else on the
    first. ``M2`` is the second record of each call's supply: on call one that is
    the second seeded belief, and on call two it is still that belief — so the case
    reaches for ``M3``, which does not exist on call one and is the first servicing's
    own yield on call two.

    **And no model-supplied string reaches ``get_many`` as an identifier**, on either
    call: every label is resolved in code to a record the loop already selected, and
    what reaches the store is that record's own stored evidence.
    """
    memory = _Journal()
    await memory.add(_belief("belief-1", "the lease question", evidence=("episode-1",)))
    await memory.add(_belief("belief-2", "the lease renewal", evidence=("episode-2",)))
    await memory.add(_episode("episode-1", "Ada: the flat was on Rua da Boavista."))
    await memory.add(_episode("episode-2", "Ada: the renewal is in March."))
    planner = _Script(requests=[_hop("M1"), _hop("M3")])

    responded = await _revising(memory, planner)

    first, second = (supply for supply, _ in planner.calls)
    assert _ids(first) == ["belief-1", "belief-2"], "three groups, and M3 names nothing"
    assert _ids(second) == ["belief-1", "belief-2", "episode-1"], "M3 is the hop's own yield"
    # The second call's `M3` resolved to `episode-1`, whose evidence is empty, so the
    # second servicing reached nothing — which is the point: the label resolved, and
    # it resolved *within this call's* sequence.
    assert _ids(responded.turn.memories) == ["belief-1", "belief-2", "episode-1"]
    for asked in memory.keyed:
        assert "M1" not in asked, "no label reached the store"
        assert "M3" not in asked, "on either call"
    assert memory.keyed == [("belief-1", "episode-1"), ("episode-1",)]


# --------------------------------------------------------------------------- #
# §13 item 8: the second level needs a fresh emission                          #
# --------------------------------------------------------------------------- #


async def test_the_second_level_is_reached_only_through_a_fresh_emission() -> None:
    """§8: one level per servicing, and a second level only because a planner named it.

    "Within one servicing, a citation hop follows exactly one level" — ADR-0226 §3's
    clause binds each servicing entire, and no servicer follows the evidence of a
    record it reached in the same servicing. So a hop whose fetched record itself
    cites further evidence adds only the first level.

    "A second level is reachable across iterations, and **only because the planner
    named it**": the record the first servicing fetched stands in the supply, is
    labelled on the second call, and its own evidence is reachable by a
    ``CITATION_HOP`` the second plan emits. Not by depth, not by a transitive
    resolver, not by following evidence the model did not name.

    **That is what makes the depth safe rather than merely available** (§8). The
    second level is not a deeper traversal the resolver performs; it is a record the
    loop *chose to render*, labelled, that a model then asked for — so every property
    ADR-0226 §3 bought is intact.
    """
    memory = _Journal()
    await memory.add(_belief("belief-1", "the lease question", evidence=("level-1",)))
    await memory.add(_episode("level-1", "Ada: ask the agent."))
    await memory.add(_belief("level-1b", "unused"))
    # The first level's record cites a second, which the first servicing must not
    # follow and the second may — once the second plan names it.
    memory._records["level-1"] = _belief("level-1", "Ada: ask the agent.", evidence=("level-2",))
    await memory.add(_episode("level-2", "Ada: the agent is Marta."))
    planner = _Script(requests=[_hop("M1"), _hop("M2")])

    responded = await _revising(memory, planner)

    first, second = (supply for supply, _ in planner.calls)
    assert _ids(first) == ["belief-1"], "one level: the supply before any servicing"
    assert _ids(second) == ["belief-1", "level-1"], "the first level and no more"
    assert _ids(responded.turn.memories) == ["belief-1", "level-1", "level-2"]
    assert len(planner.calls) == 2, "the second level cost a second emission"


# --------------------------------------------------------------------------- #
# §13 item 14: the supply is monotone and the fourth group is one group        #
# --------------------------------------------------------------------------- #


async def test_the_supply_is_monotone_and_the_fourth_group_is_one_group() -> None:
    """§7, over a turn with two servicings.

    The three groups the first call saw are byte-identical in the ``TurnResult``;
    both servicings' records follow them in servicing order as **one** appended run;
    and there is no fifth group. "Monotonicity is the safety property this whole
    design rests on": nothing leaves the supply, so the union the last iteration
    holds is a superset of every earlier one, and a stamp or an evaluation taken over
    the final supply covers everything any iteration saw.

    ADR-0223's own docstring for ``SelectionOrigin.over`` names the failure this
    forecloses — "plan a step over tainted material, re-plan over clean material,
    stamp the binding from the last selection, and watch the fact clear" — written
    before any re-planning existed.
    """
    memory = _Journal()
    await memory.add(_belief("belief-1", "the lease question", evidence=("first-1",)))
    await memory.add(_episode("first-1", "Ada: the flat was on Rua da Boavista."))
    await memory.add(_belief("second-1", "the deposit was four hundred", evidence=()))
    planner = _Script(requests=[_hop("M1"), _query("the deposit")])

    responded = await _revising(memory, planner)

    planning_saw, _ = planner.calls[0]
    supplied = responded.turn.memories
    assert supplied[: len(planning_saw)] == planning_saw, "the earlier groups are untouched"
    assert _ids(supplied) == ["belief-1", "first-1", "second-1"], "one appended run, in order"
    assert len(planner.calls) == 2


async def test_a_record_both_servicings_reach_appears_once_at_its_first_place() -> None:
    """§7's whole-union deduplication, ranging over the earlier servicing's yield.

    "A record the second servicing reaches that the first already added enters the
    group once, at its first arrival's position, and **consumes no slot of the second
    budget**." A servicer deduplicating only against the *pre-servicing* supply would
    satisfy the narrower clause and still render one record twice.
    """
    memory = _Journal()
    await memory.add(_belief("belief-1", "the lease question", evidence=("shared-1",)))
    await memory.add(_belief("shared-1", "the flat was on Rua da Boavista"))
    await memory.add(_belief("fresh-1", "the deposit was four hundred"))
    planner = _Script(requests=[_hop("M1"), _query("flat deposit")])

    with structlog.testing.capture_logs() as captured:
        responded = await _revising(memory, planner)

    assert _ids(responded.turn.memories) == ["belief-1", "shared-1", "fresh-1"]
    second = _record(captured)["servicings"][1]
    assert second["deduplicated"] >= 1, "the shared record arrived again and was dropped"
    assert "shared-1" not in _ids(responded.turn.memories)[2:], "and did not arrive twice"


async def test_each_servicing_draws_its_own_budget_of_ten() -> None:
    """§7: a budget per servicing, so a turn's fourth group holds at most twenty.

    "Under a turn-wide budget the second servicing would ordinarily receive nothing,
    which makes the second emission an instrument reading with no read under it."
    Each servicing's budget is counted after deduplication against the supply **as it
    stands when that servicing runs**, which on the second includes the first's
    yield.
    """
    memory = _Journal()
    await memory.add(_belief("belief-1", "the lease question"))
    # Lexically disjoint from `_ASKED`, so none of the twenty is in the supply the
    # turn's own belief read assembled and every one of them is a candidate the
    # servicings' budgets have to ration.
    # Two disjoint tens, each lexically disjoint from `_ASKED` and from the other, so
    # neither is in the supply the turn's own belief read assembled and each
    # servicing's query reaches exactly its own ten. One budget shared across the turn
    # would give the second servicing nothing, which is the shape §7 refuses.
    for ordinal in range(READ_BUDGET):
        await memory.add(_belief(f"paperwork-{ordinal}", f"paperwork item {ordinal}"))
        await memory.add(_belief(f"inventory-{ordinal}", f"inventory item {ordinal}"))
    planner = _Script(requests=[_query("paperwork"), _query("inventory")])

    with structlog.testing.capture_logs() as captured:
        responded = await _revising(memory, planner)

    record = _record(captured)
    assert record["planner_calls"] == 2
    assert [entry["new"] for entry in record["servicings"]] == [READ_BUDGET, READ_BUDGET]
    fourth = _ids(responded.turn.memories)[len(planner.calls[0][0]) :]
    assert len(fourth) == 2 * READ_BUDGET, "at most twenty, and one appended run"
    assert len(set(fourth)) == len(fourth), "and no record twice"


async def test_the_hop_carrier_accumulates_across_both_servicings() -> None:
    """§13 item 14's last clause: the second servicing does not replace the first's set.

    "ADR-0227 §3's hop-set carrier **accumulates across both servicings** rather than
    the second replacing the first: a record the **first** hop reached still renders
    its reply in the prompt the turn finally assembles." Asserted through the
    production renderer under ADR-0227 §7's fidelity rule, because what §3 guarantees
    is about the prompt this system assembles rather than about a value in flight.
    """
    memory = _Journal()
    await memory.add(_belief("belief-1", "the lease question", evidence=("first-1",)))
    await memory.add(_belief("belief-2", "the lease renewal", evidence=("second-1",)))
    await memory.add(_episode("first-1", "Ada: where was the flat?", outcome="On Rua da Boavista."))
    await memory.add(_episode("second-1", "Ada: when is the renewal?", outcome="In March."))
    planner = _Script(requests=[_hop("M1"), _hop("M2")])

    responded = await _revising(memory, planner)

    # ADR-0229 §3's expansion sequence: each label's own record, then that record's
    # live evidence. Both servicings' sequences stand, in servicing order, with the
    # first occurrence keeping its place (ADR-0227 §4).
    assert responded.hop_reached == ("belief-1", "first-1", "belief-2", "second-1")
    prompt = await _prompt_over(responded)
    assert "On Rua da Boavista." in prompt, "the first hop's reply still renders"
    assert "In March." in prompt, "and so does the second's"


# --------------------------------------------------------------------------- #
# §13 items 15-17: the audit, and a turn that did not revise                   #
# --------------------------------------------------------------------------- #


async def test_the_audit_accounts_per_emission_and_the_fire_rate_keeps_its_meaning() -> None:
    """§9's first arm: one record, two entries, and the turn-level figures.

    §9 extends ADR-0226 §9's record rather than replacing it — "One record, one turn,
    one event key, one ``INFO`` line, emitted once and conditioned on nothing" — with
    the per-servicing counts becoming an ordered sequence and two turn-level fields
    joining them.
    """
    memory = _Journal()
    await memory.add(_belief("belief-1", "the lease question", evidence=("first-1",)))
    await memory.add(_episode("first-1", "Ada: the flat was on Rua da Boavista."))
    await memory.add(_belief("second-1", "the deposit was four hundred"))
    planner = _Script(requests=[_hop("M1"), _query("the deposit")])

    with structlog.testing.capture_logs() as captured:
        await _revising(memory, planner)

    assert len(_records(captured)) == 1, "one record per turn, however many emissions"
    record = _record(captured)
    assert record["trigger"] == TriggerOutcome.FIRED.value
    assert record["planner_calls"] == 2
    assert record["stop"] == StopReason.BOUND_REACHED.value
    assert len(record["servicings"]) == 2
    assert [entry["kinds"] for entry in record["servicings"]] == [
        (ReadKind.CITATION_HOP.value,),
        (ReadKind.SIGHTED_QUERY.value,),
    ]


async def test_a_turn_whose_second_planner_call_raises_still_says_it_fired() -> None:
    """§9's fifth stop reason, and the population §5 leaves persisting nothing.

    "A second planner call that raises still writes a record, and none of the four
    successful outcomes describes it. Labelling such a turn **settled** would say the
    planner stopped asking when it did not; **bound reached** would say a guard fired
    when none did. A vocabulary that forces an implementation to pick a falsehood is
    a vocabulary with a hole."

    **It is a stop reason and never a turn outcome**: the original failure propagates
    unchanged, exactly as ADR-0226 §11 item 10 requires of its own arms. And no plan
    is persisted — the engine's persistence site is above the loop and never runs,
    which is the turn a design carrying a plan out of a failure would have written.
    """
    memory = await _seeded()
    planner = _Script(requests=[_hop("M1")], raises=1)

    with (
        structlog.testing.capture_logs() as captured,
        pytest.raises(PlanningError, match="the planner is down"),
    ):
        await _revising(memory, planner)

    assert len(planner.calls) == 2, "the second call was started"
    record = _record(captured)
    assert record["trigger"] == TriggerOutcome.FIRED.value
    assert record["stop"] == StopReason.PLANNING_FAILED.value
    # §9 asks for how many calls the turn **made**, so a call that raised is one the
    # turn made: a record saying one beside **planning failed** would say planning
    # failed on a call it claims never happened.
    assert record["planner_calls"] == 2
    assert len(record["servicings"]) == 1


async def test_a_turn_that_ended_before_any_plan_says_not_reached_and_not_iterated() -> None:
    """§9's default, and what separates it from a turn that found no revision.

    "'Not iterated' is the record's default, so a turn that ended before it reached a
    first plan carries it and says something true — it did not iterate. What
    separates that turn from one that reached a plan and found no revision admissible
    is §8's ``trigger`` outcome, **not reached** against **fired** or **not fired**."
    No lane reads "not iterated" as a claim that a first plan existed.
    """
    memory = await _seeded()
    planner = _Script(raises=0)

    with (
        structlog.testing.capture_logs() as captured,
        pytest.raises(PlanningError, match="the planner is down"),
    ):
        await _revising(memory, planner)

    record = _record(captured)
    assert record["trigger"] == TriggerOutcome.NOT_REACHED.value
    assert record["stop"] == StopReason.NOT_ITERATED.value
    assert record["planner_calls"] == 1, "the call was made and it raised"
    assert record["servicings"] == ()


async def test_a_turn_whose_revision_carried_no_request_is_fired_and_settled() -> None:
    """§9's per-turn trigger, and the fourth stop reason.

    "A turn's trigger **fired** if **any** plan that turn produced carried a
    ``read_request``", so a turn whose first plan asked and whose revision did not is
    **fired** and not **not fired** — which is what keeps the live fire rate directly
    comparable to the replay's 13.6% and to milestone 27's own. Its stop is
    **settled**: the last plan carried no request, and the planner stopped asking.

    **No lane divides emissions by turns and calls the result a fire rate** (§9). A
    turn that emits twice is one turn.
    """
    memory = await _seeded()
    planner = _Script(requests=[_hop("M1"), None])

    with structlog.testing.capture_logs() as captured:
        responded = await _revising(memory, planner)

    record = _record(captured)
    assert record["trigger"] == TriggerOutcome.FIRED.value
    assert record["stop"] == StopReason.SETTLED.value
    assert record["planner_calls"] == 2
    assert len(record["servicings"]) == 1, "the revision asked for nothing to service"
    assert responded.stopped_while_asking is False, "it was not still asking"


async def test_the_audit_still_copies_nothing_under_iteration() -> None:
    """§13 item 16: §9's counts-and-no-copy rule binds the extension entire.

    Neither a distinctive span of a returned record nor **either** iteration's query
    string appears anywhere in the record; no plan identifier appears, the superseded
    plan's included; and the correlation id is the only identifier on the event.
    """
    memory = _Journal()
    await memory.add(_belief("belief-1", "the lease question", evidence=("first-1",)))
    await memory.add(_episode("first-1", "Ada: quinoa-flavoured stroopwafel."))
    await memory.add(_belief("second-1", "marmalade zeppelin bookkeeping"))
    planner = _Script(requests=[_hop("M1"), _query("marmalade zeppelin")])

    with structlog.testing.capture_logs() as captured:
        responded = await _revising(memory, planner)

    rendered = repr(_record(captured))
    assert "marmalade" not in rendered, "neither iteration's query is copied"
    assert "stroopwafel" not in rendered, "no returned record's content is copied"
    assert "M1" not in rendered, "the labels either call named are not copied"
    assert len(responded.plans) == 2
    for plan in responded.plans:
        assert plan.id not in rendered, "no plan identifier, the superseded plan's included"


async def test_on_a_turn_that_did_not_revise_nothing_moved() -> None:
    """§13 item 17: the whole of what a non-revising turn looks like.

    The prompt the composing stage assembles is byte-identical to today's, the
    audit's per-servicing sequence has at most one entry, ``ActionPlan.supersedes``
    is ``None``, and the ``TurnResult`` is constructed once. This is the clause that
    keeps a new prompt input from silently moving every reply the system composes.

    The byte-identity is asserted against a prompt assembled with §10's fact
    explicitly absent, which is the comparison that would fail on an implementation
    rendering the clause unconditionally.
    """
    memory = _Journal()
    await memory.add(_belief("belief-1", "the lease question"))
    planner = _Script()

    with structlog.testing.capture_logs() as captured:
        responded = await _revising(memory, planner)

    assert len(planner.calls) == 1
    assert responded.turn.plan.supersedes is None
    assert responded.plans == (responded.turn.plan,)
    assert responded.stopped_while_asking is False
    record = _record(captured)
    assert len(record["servicings"]) <= 1
    assert record["planner_calls"] == 1

    model = FakeModelProvider("answer")
    stage = ComposingStage(model=model, streaming=FakeStreamingCompleter())
    await stage.compose(turn=responded.turn, step=None, undriven=())
    [call] = model.calls
    assert await _system_prompt_over(responded) == next(
        one.content for one in call.messages if one.role is Role.SYSTEM
    ), "the assembled system prompt is byte-identical to what it is without the fact"


# --------------------------------------------------------------------------- #
# §13 item 10: the loop sets `supersedes` and the planner sets nothing         #
# --------------------------------------------------------------------------- #


async def test_the_revision_differs_from_what_the_planner_returned_in_one_field() -> None:
    """§13 item 10's first arm, field by field against the planner's own return.

    §5 narrows the prohibition to exactly one field: "``id``, ``goal_id``, ``steps``,
    ``rationale`` and ``read_request`` are the planner's, ``supersedes`` is the
    loop's, and there is no third case". So the plan the turn carries out differs
    from the plan the planner returned in ``supersedes`` and in nothing else.
    """
    memory = await _seeded()
    planner = _Script(requests=[_hop("M1"), None], steps=[(), (_step(),)])

    responded = await _revising(memory, planner)

    first, revision = responded.plans
    assert revision.supersedes == first.id
    assert first.supersedes is None, "the first plan replaced nothing"
    for field in ActionPlan.model_fields:
        if field == "supersedes":
            continue
        assert getattr(revision, field) == getattr(
            ActionPlan(
                id=revision.id,
                goal_id=revision.goal_id,
                steps=revision.steps,
                created_at=revision.created_at,
                rationale=revision.rationale,
                read_request=revision.read_request,
            ),
            field,
        ), f"{field} is exactly as the planner returned it"


async def test_a_revision_carrying_another_plans_id_persists_the_loops_value() -> None:
    """§13 item 10's second arm: the planner's value is discarded, not honoured."""
    memory = await _seeded()
    planner = _Script(requests=[_hop("M1"), None], supersedes=[None, "some-other-plan"])

    responded = await _revising(memory, planner)

    first, revision = responded.plans
    assert revision.supersedes == first.id, "the loop's value, not the planner's"


async def test_a_first_plan_carrying_a_resolvable_id_persists_none() -> None:
    """§13 item 10's third arm: the spoof a rule stated only over revisions lets through.

    "A planner conforming by signature could return its **first** plan already
    carrying a same-goal predecessor's id. Nothing would revise, so nothing would
    overwrite it; ``save_plan`` would accept it, because the reference resolves; and
    the store would hold a durable record claiming a supersession that never
    happened."

    Taking the field on **every** plan is what closes it. And the discard is silent:
    "not an error, not a park, not a degradation of the turn, and not a count in §9's
    record" — the turn is not the place to punish a planner's non-conformance, and
    the widest possible effect is that a field the planner does not own is ignored.
    """
    memory = _Journal()
    await memory.add(_belief("belief-1", "the lease question"))
    planner = _Script(supersedes=["a-plan-that-resolves"])

    with structlog.testing.capture_logs() as captured:
        responded = await _revising(memory, planner)

    assert responded.turn.plan.supersedes is None
    assert responded.plans == (responded.turn.plan,)
    record = _record(captured)
    assert record["stop"] == StopReason.NOT_ITERATED.value
    assert set(record) == {
        "event",
        "log_level",
        "correlation_id",
        "trigger",
        "servicing",
        "planner_calls",
        "stop",
        "servicings",
    }, "no count of the discard"


async def test_no_plan_identifier_appears_in_any_prompt_the_turn_assembles() -> None:
    """§13 item 10's fourth arm, through the production renderer.

    "**No plan identifier is rendered to a model and none is accepted from one.**" No
    lane puts a predecessor's id in a prompt, adds a parameter to ``Planner.plan`` to
    carry one, or reads one out of model output — which is the ground ADR-0226 §9
    refused to *log* ``ActionPlan.id`` on, applied to a field that is written.
    """
    memory = await _seeded()
    planner = _Script(requests=[_hop("M1"), None])

    responded = await _revising(memory, planner)

    assert len(responded.plans) == 2
    prompt = await _prompt_over(responded) + await _system_prompt_over(responded)
    for plan in responded.plans:
        assert plan.id not in prompt
    for supply, _ in planner.calls:
        assert all(plan.id not in _ids(supply) for plan in responded.plans)


# --------------------------------------------------------------------------- #
# §13 item 2's loop half: the bound, and §10's fact                            #
# --------------------------------------------------------------------------- #


async def test_the_bound_stops_a_planner_that_asks_on_every_call() -> None:
    """§3: exactly two calls, both emissions serviced, and §10's fact.

    "The second plan's request, where it carries one, **is serviced** under ADR-0226
    §5, §6 and §7 exactly as the first plan's is — and no third planner call follows
    it. Its yield reaches the reply and no plan, which is precisely milestone 27's
    own shape." Servicing it rather than suppressing it "costs no model call — the
    emission already exists — and discarding it would throw away a read the planner
    asked for on a turn where the system had already decided to spend".
    """
    memory = _Journal()
    await memory.add(_belief("belief-1", "the lease question", evidence=("first-1",)))
    await memory.add(_episode("first-1", "Ada: the flat was on Rua da Boavista."))
    await memory.add(_belief("second-1", "the deposit was four hundred"))
    planner = _Script(requests=[_hop("M1"), _query("the deposit")])

    with structlog.testing.capture_logs() as captured:
        responded = await _revising(memory, planner)

    assert len(planner.calls) == 2, "and no third"
    record = _record(captured)
    assert len(record["servicings"]) == 2, "both emissions serviced"
    assert record["stop"] == StopReason.BOUND_REACHED.value
    assert responded.stopped_while_asking is True
    assert "stopped before you could" in await _system_prompt_over(responded)
    assert _ids(responded.turn.memories) == ["belief-1", "first-1", "second-1"], (
        "the second servicing's yield reaches the reply and no plan"
    )


# --------------------------------------------------------------------------- #
# §10: what the fact adds to the prompt, and what it must not                 #
# --------------------------------------------------------------------------- #


async def test_the_stop_fact_adds_no_count_no_duration_and_no_guard_name() -> None:
    """§10's negative half, over the text the fact actually added.

    "The fact carries **no count, no duration, no guard name, no query and no
    label**. It does not say which guard fired, how many times the turn looked, or
    how long it spent." Asserted over the **difference** between the prompt this turn
    assembles and the prompt the same turn assembles without the fact — which is the
    only way to say "the fact added nothing but this" rather than "these words are
    absent from a prompt that is mostly about something else".

    The reasons §10 gives: nothing bounds what a planner puts in a query, and the
    turn's timing is a fact about the system rather than about the user's question.
    "A reply that named the deadline would invite a retry, and a retry hits the same
    bound over the same supply; a reply that named the count would be telling the
    user about the system's budget." Which guard fired is an operator's question, and
    ADR-0228 §9 answers it.
    """
    memory = _Journal()
    await memory.add(_belief("belief-1", "the lease question", evidence=("first-1",)))
    await memory.add(_episode("first-1", "Ada: marmalade zeppelin."))
    await memory.add(_belief("second-1", "quinoa stroopwafel bookkeeping"))
    planner = _Script(requests=[_hop("M1"), _query("quinoa stroopwafel")])

    responded = await _revising(memory, planner)
    assert responded.stopped_while_asking is True

    with_fact = await _system_prompt_over(responded)
    model = FakeModelProvider("answer")
    stage = ComposingStage(model=model, streaming=FakeStreamingCompleter())
    await stage.compose(turn=responded.turn, step=None, undriven=())
    [call] = model.calls
    without = next(one.content for one in call.messages if one.role is Role.SYSTEM)

    added = with_fact.replace(without, "").strip()
    assert added, "the fact added something"
    assert not any(character.isdigit() for character in added), "no count and no duration"
    for forbidden in ("bound", "budget", "deadline", "second", "twice", "planner"):
        assert forbidden not in added.lower(), f"no guard name: {forbidden}"
    assert "marmalade" not in added, "no query and nothing a record said"
    assert "quinoa" not in added
    assert "M1" not in added, "no label"


async def test_the_clock_is_read_only_where_the_budget_check_is_reached() -> None:
    """§4: "checked immediately before each additional planner call and at no other point".

    A turn on an operation that declares **no** budget takes no reading for the
    budget at all — its §2(a) condition fails first — and a turn that stops at the
    bound takes none for a call it will not make. The count is over readings of the
    injected clock: entry, the goal's timestamp, and one per admitted budget check.

    It matters beyond tidiness. The loop's clock is guarded
    (:func:`~ai_assistant.core.clock.checked_clock`), so a non-conforming reading is
    a ``PlanningError`` from the stage that read it — and a reading taken eagerly
    would fail a turn on an operation that declares no budget over a clock that turn
    never needed.
    """
    memory = await _seeded()
    unbudgeted = _Elapsed(timedelta(seconds=1))
    await _revising(memory, _Script(requests=[_hop("M1")]), operation=None, now=unbudgeted)

    budgeted = _Elapsed(timedelta(seconds=1))
    await _revising(await _seeded(), _Script(requests=[_hop("M1"), None]), now=budgeted)

    assert budgeted.readings == unbudgeted.readings + 1, (
        "exactly one more reading: the one budget check the budgeted turn reached"
    )


async def test_a_turn_that_never_reached_the_planner_reports_no_calls() -> None:
    """The other side of §9's ``planner_calls``, and what separates zero from one.

    A turn that ended **before the planner was reached at all** made no calls and says
    so; a turn whose first call raised made one. Both are §8's **not reached** on the
    trigger — neither produced a plan, so neither reached a judgement about its supply
    — and ``planner_calls`` is what tells an operator which happened.

    A blank utterance is the shape that reaches neither: it is refused at the top of
    the turn, before any context is assembled and before the planner exists to the
    turn at all.
    """
    memory = await _seeded()
    planner = _Script()
    loop = _loop(memory, planner=planner)

    with (
        structlog.testing.capture_logs() as captured,
        pytest.raises(PlanningError),
    ):
        await loop.respond("   ", narrow=_bounded(), operation=ConversationalOperation.CONVERSE)

    assert planner.calls == []
    record = _record(captured)
    assert record["trigger"] == TriggerOutcome.NOT_REACHED.value
    assert record["planner_calls"] == 0, "no call was made at all"
    assert record["stop"] == StopReason.NOT_ITERATED.value


# --------------------------------------------------------------------------- #
# §4: the budget is the operation's, and no caller supplies a figure          #
# --------------------------------------------------------------------------- #


def test_the_budget_is_read_off_the_operation_and_never_supplied_by_a_caller() -> None:
    """§4: "not a ``Settings`` value, not a deployment flag and not a per-request parameter".

    What crosses :meth:`~ai_assistant.orchestration.loop.LearningLoop.respond`'s seam
    is a member of a **closed** set whose budget this module fixes, so no caller — in
    this package, in a test, or in a later lane — can name a figure no ADR ruled on.
    That is the construction :data:`~ai_assistant.orchestration.reads.READ_BUDGET`
    uses for ADR-0226 §6's ten and for the same stated reason, and the same fail-closed
    shape ADR-0226 §5's channel scoping already has here: the loop reads a closed
    property off what it is handed rather than taking a value a caller could
    contradict.

    **Keyed on the operation and never on the audience** (§4). ``converse`` and
    ``converse_streaming`` are both bounded-audience and declare the same figure;
    ``converse_spoken`` declares none. Audience decides what may be *said* (ADR-0199
    §1, ADR-0226 §5) and never how long a user waits.
    """
    assert {member.value for member in ConversationalOperation} == {
        "converse",
        "converse_streaming",
        "converse_spoken",
    }
    assert ConversationalOperation.CONVERSE.planning_budget == timedelta(seconds=20)
    assert ConversationalOperation.CONVERSE_STREAMING.planning_budget == timedelta(seconds=20)
    assert ConversationalOperation.CONVERSE_SPOKEN.planning_budget is None

    signature = inspect.signature(LearningLoop.respond)
    assert "planning_budget" not in signature.parameters, "no caller supplies a duration"
    annotation = signature.parameters["operation"].annotation
    assert "ConversationalOperation" in str(annotation)
    assert signature.parameters["operation"].default is None, (
        "a caller that names no operation declares no budget and does not iterate"
    )
