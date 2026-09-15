"""Shared conformance suite for the PlanStore Protocol (ADR-0014).

Every ``PlanStore`` implementation must pass this suite (CONTRIBUTING, "Protocol
conformance suites"). A concrete test subclasses :class:`PlanStoreContract` and
overrides the ``store`` fixture.

This suite matters more than most: `InMemoryPlanStore` and `FakePlanStore`
re-implement the ADR-0014 §4 transition graph independently — the fake cannot
import the subsystem it stands in for — so this is what stops the two drifting.
It asserts only behaviour the *contract* guarantees, never how a given store
keys its ids.

Named ``*_contract`` (not ``test_*``) so pytest collects it only via a
``Test``-prefixed subclass, never the abstract base directly.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Protocol

import pytest
from pydantic import ValidationError

from ai_assistant.core.errors import (
    ActiveExecutionError,
    IllegalTransitionError,
    PlanningError,
    RetriesExhaustedError,
    StaleExecutionError,
)
from ai_assistant.core.types import (
    MAX_ASSOCIATION_CANDIDATES,
    MAX_GOAL_EVIDENCE,
    MAX_GOAL_INTERPRETATIONS,
    MAX_INTENDED_ACTIONS,
    TERMINAL_ATTEMPT_STATES,
    ActionPlan,
    AttemptEffort,
    AttemptKind,
    AttemptOutcome,
    AttemptPhase,
    AttemptState,
    AttemptTransition,
    EvidenceApplicability,
    EvidenceBasis,
    EvidenceHistory,
    EvidenceStanding,
    Goal,
    GoalAttempt,
    GoalElement,
    GoalEvidence,
    GoalInterpretation,
    GoalQuestion,
    GoalQuestionDisposition,
    GoalRevision,
    GoalStatus,
    Ground,
    IntendedAction,
    IntendedActionMinting,
    InterpretationVerdict,
    InterpretedOutput,
    MemorySource,
    PlanInterpretation,
    PlanStep,
    Provenance,
    ReadAsk,
    ReadKind,
    ReadOutcomeKind,
    ReadRequest,
    ResultReference,
    SkipReason,
    StepCondition,
    StepFailure,
    StepOutputRef,
    StepStatus,
    StepTransition,
    StepVerification,
    ToolFailureKind,
    VerificationKind,
)
from ai_assistant.testing.cancellation import settle

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine
    from contextlib import AbstractAsyncContextManager

    from ai_assistant.core.protocols import PlanStore
    from ai_assistant.core.types import ExecutionState, StepExecution
    from ai_assistant.testing.cancellation import SuspendedMidWrite

_WHEN = datetime(2026, 1, 1, tzinfo=UTC)

#: The two engagement instants ADR-0250's arms order goals by. Distinct and both
#: after ``_WHEN``, so "engaged later" is a fact about the values rather than about
#: whichever call happened to run first.
_ENGAGED_AT = datetime(2026, 2, 1, tzinfo=UTC)
_LATER_ENGAGED = datetime(2026, 3, 1, tzinfo=UTC)


#: What a failure of the cancellation case below means, in one place: every
#: assertion in it is the same invariant seen from a different side.
_RELEASED_EARLY = (
    "the cancelled call released its resource while its own work was still "
    "running, so a second caller reached it concurrently"
)


def _goal(goal_id: str = "g1", *, statement: str = "relocate to Lisbon") -> Goal:
    """A goal opened at revision 1, in the shape ADR-0249 §3 mints."""
    return Goal(
        id=goal_id,
        conversation_id="c1",
        interpretation=(
            GoalInterpretation(
                revision=1,
                outcome=statement,
                outcome_ground=Ground.USER_STATED,
                outcome_span=statement,
                recorded_at=_WHEN,
                raised_by="t-1",
            ),
        ),
        provenance=Provenance(
            source=MemorySource.USER_ASSERTED, confidence=1.0, last_updated=_WHEN
        ),
        created_at=_WHEN,
    )


def _revision(
    revision: int, *, outcome: str = "relocate to Lisbon in September"
) -> GoalInterpretation:
    """One interpretation revision, in the shape ADR-0249 §1 admits.

    Grounded ``INFERRED`` rather than ``USER_STATED`` because nothing here is a span
    of any turn's request — the suite records revisions, it does not resolve grounds,
    and §7's resolution is L3's.
    """
    return GoalInterpretation(
        revision=revision,
        outcome=outcome,
        outcome_ground=Ground.INFERRED,
        recorded_at=_WHEN,
        raised_by=f"t-{revision}",
    )


def _attempt(attempt_id: str = "a1", goal_id: str = "g1") -> GoalAttempt:
    """A freshly opened attempt: ``UNDERSTAND``/``RUNNING``, nothing spent (§5, §6)."""
    return GoalAttempt(id=attempt_id, goal_id=goal_id, opened_at=_WHEN)


def _question(
    question_id: str = "q1",
    *,
    goal_id: str = "g1",
    attempt_id: str = "a1",
    asked_at: datetime = _WHEN,
) -> GoalQuestion:
    """An ``OPEN`` question carrying both content fields (ADR-0250 §8).

    ``expires_at`` is stamped from ``asked_at`` because §8 computes it "**once**, at
    the instant the question is written" — the figure is ``Settings.goal_question_ttl``'s
    default, and no store reads that setting or this deadline.
    """
    return GoalQuestion(
        id=question_id,
        goal_id=goal_id,
        attempt_id=attempt_id,
        text="which campsite?",
        about="the usual campsite",
        asked_at=asked_at,
        expires_at=asked_at + timedelta(hours=72),
    )


async def _goal_with_attempt(
    store: PlanStore, *, goal_id: str = "g1", attempt_id: str = "a1"
) -> None:
    """Write the two records every question resolves against (ADR-0250 §9).

    ``record_question`` refuses a dangling ``goal_id`` or ``attempt_id`` at the write,
    so the arms below need both rows before they can ask about anything else.
    """
    await store.save_goal(_goal(goal_id))
    await store.open_attempt(_attempt(attempt_id, goal_id=goal_id))


#: One region every evidence arm below composes from, applying the one axis whose
#: comparison is byte-exact (ADR-0213 §3) so an arm never turns on a fold.
_REGION = EvidenceApplicability(topics=("weather",))


def _evidence(  # noqa: PLR0913 — the row's own fields, each a distinct thing an arm varies
    evidence_id: str = "ev1",
    *,
    goal_id: str = "g1",
    attempt_id: str = "a1",
    read_at: datetime = _WHEN,
    as_of: datetime | None = None,
    supported: tuple[EvidenceApplicability, ...] = (_REGION,),
    verdict: str = ReadOutcomeKind.RETURNED_RECORDS.value,
    records: tuple[str, ...] = ("m1",),
) -> GoalEvidence:
    """A ``STANDING`` ``READ_OUTCOME`` row, in the shape ADR-0252 §1 admits.

    A ``SIGHTED_QUERY``, because that is one of the three durable kinds whose
    ``len(records)`` must equal ``returned`` — so an arm varying ``records`` varies the
    count with it and never has to remember the invariant.
    """
    return GoalEvidence(
        id=evidence_id,
        goal_id=goal_id,
        attempt_id=attempt_id,
        basis=EvidenceBasis.READ_OUTCOME,
        read_kind=ReadKind.SIGHTED_QUERY,
        supported=supported,
        supported_elided=0,
        read_at=read_at,
        as_of=as_of,
        records=records,
        returned=len(records),
        admitted=len(records),
        verdict=verdict,
        standing=EvidenceStanding.STANDING,
    )


async def _goal_with_evidence(
    store: PlanStore, *, rows: int = 1, goal_id: str = "g1"
) -> tuple[str, ...]:
    """A goal, an attempt and ``rows`` standing evidence rows, oldest first.

    ``read_at`` steps by a minute per row, so ``evidence_of``'s order is a fact about
    the instants rather than about the order the writes happened to land in.
    """
    await _goal_with_attempt(store, goal_id=goal_id)
    written = []
    for index in range(rows):
        row = _evidence(f"ev{index + 1}", goal_id=goal_id, read_at=_WHEN + timedelta(minutes=index))
        written.append(await store.record_evidence(row))
    return tuple(written)


#: One read request of each of ADR-0226 §2's two kinds, for the export arms below.
_READ_REQUEST = ReadRequest(
    asks=(
        ReadAsk(kind=ReadKind.CITATION_HOP, labels=("M1", "M2")),
        ReadAsk(kind=ReadKind.SIGHTED_QUERY, query="which lender did you recommend?"),
    )
)


def _plan(  # noqa: PLR0913 — the plan's own fields, each a distinct thing an arm varies
    plan_id: str = "p1",
    goal_id: str = "g1",
    *,
    steps: int = 1,
    read_request: ReadRequest | None = None,
    supersedes: str | None = None,
    targets_revision: int | None = 1,
) -> ActionPlan:
    """A plan the store accepts: stamped, as ADR-0249 §8 requires every saved plan.

    ``targets_revision`` defaults to the revision every goal this suite builds stands
    at, because a plan whose stamp is still absent is one ``save_plan`` refuses (§8).
    The arm that drives that refusal passes ``None`` explicitly.
    """
    return ActionPlan(
        id=plan_id,
        goal_id=goal_id,
        steps=tuple(
            PlanStep(id=f"s{index}", intent=f"step {index}", capability="send_email")
            for index in range(1, steps + 1)
        ),
        created_at=_WHEN,
        read_request=read_request,
        supersedes=supersedes,
        targets_revision=targets_revision,
    )


def _intended(action_id: str = "ia1", *, serves: tuple[str, ...] = ()) -> IntendedAction:
    """One intended action, minted by ``orchestration`` in the shape ADR-0265 §1 admits."""
    return IntendedAction(id=action_id, intent=f"perform {action_id}", serves=serves)


def _minting(
    *actions: IntendedAction, goal_id: str = "g1", expected_version: int = 0
) -> IntendedActionMinting:
    """The command that appends ``actions`` to ``goal_id`` (ADR-0265 §5)."""
    return IntendedActionMinting(
        goal_id=goal_id, actions=actions, expected_version=expected_version
    )


def _acting_plan(
    plan_id: str = "p1", *, first: str | None = "ia1", second: str | None = None
) -> ActionPlan:
    """A plan whose steps carry one **capability** and byte-identical ``parameters``.

    ADR-0265 §10 arm 1(a)'s shape: what separates the two steps is the intended action
    each names and nothing else, "so the triple §6's first clause requires is **distinct
    for the two steps** while the argument key is equal".
    """
    parameters: Mapping[str, Any] = {"hotel": "the one by the station", "nights": 1}
    named = (first,) if second is None else (first, second)
    return ActionPlan(
        id=plan_id,
        goal_id="g1",
        steps=tuple(
            PlanStep(
                id=f"s{index}",
                intent="book a room",
                capability="book_room",
                parameters=parameters,
                intended_action=action,
            )
            for index, action in enumerate(named, start=1)
        ),
        created_at=_WHEN,
        targets_revision=1,
    )


def _conditioned_goal(goal_id: str = "g1", *, element_id: str = "e1", revision: int = 1) -> Goal:
    """A goal whose current revision carries one **condition** element with an ``id``.

    ADR-0253 §9's ``save_plan`` conjunct is stated over exactly that set — "the ``id``
    of a condition element of the interpretation that plan's ``targets_revision``
    names" — so the arms below need a goal that has one, which :func:`_goal`
    deliberately does not: a goal ADR-0249 §3 opens "carries no elements" at all.
    """
    held = _goal(goal_id)
    conditioned = held.interpretation[0].model_copy(
        update={
            "revision": revision,
            "conditions": (
                GoalElement(
                    id=element_id,
                    text="the weather over the trip permits it",
                    ground=Ground.INFERRED,
                ),
            ),
        }
    )
    return held.model_copy(update={"interpretation": (conditioned,)})


def _conditioned_plan(
    plan_id: str = "p1", *, about: str = "e1", targets_revision: int = 1
) -> ActionPlan:
    """A plan whose one step carries one ``READ_OUTCOME`` condition about ``about``."""
    return ActionPlan(
        id=plan_id,
        goal_id="g1",
        steps=(
            PlanStep(
                id="s1",
                intent="book it",
                capability="send_email",
                when=(StepCondition(about=about, basis=EvidenceBasis.READ_OUTCOME),),
            ),
        ),
        created_at=_WHEN,
        targets_revision=targets_revision,
    )


def _claim(state: ExecutionState, step_id: str = "s1", *, attempt_id: str = "a1") -> StepTransition:
    """The transition that claims a step — bound tool, authorisation, attempt.

    ``attempt_id`` is required on a ``→ RUNNING`` transition (ADR-0255 §3) and names
    the attempt :func:`_owned` opens, which is the one every arm here claims under.
    """
    return StepTransition(
        execution_id=state.id,
        step_id=step_id,
        to_status=StepStatus.RUNNING,
        expected_version=state.version,
        bound_tool="smtp",
        approval_ref="perm-1",
        attempt_id=attempt_id,
    )


async def _owned(
    store: PlanStore, state: ExecutionState, *, attempt_id: str = "a1", goal_id: str = "g1"
) -> ExecutionState:
    """Open the attempt that owns ``state``, as ``orchestration`` does (ADR-0249 §12).

    The execution id is appended at the moment the execution exists and before any step
    of it is dispatched, which is what makes ADR-0255 §3's membership limb resolve. An
    execution whose append has not landed carries no attempt that names it, so a claim
    on it is refused — which is the ordering failing closed.

    By whichever of ADR-0249 §12's two routes the attempt is at: ``open_attempt``
    carrying the reference where the row does not exist yet, and ``commit_attempt``
    appending it where it does — which is how one attempt comes to own the several
    executions its walks open.
    """
    held = await store.get_attempt(attempt_id)
    if held is None:
        await store.open_attempt(
            GoalAttempt(id=attempt_id, goal_id=goal_id, opened_at=_WHEN, execution_ids=(state.id,))
        )
    else:
        await store.commit_attempt(
            AttemptTransition(
                attempt_id=attempt_id,
                expected_version=held.version,
                add_execution_id=state.id,
            )
        )
    return state


class _CancellationOp(Protocol):
    """One locked ``PlanStore`` operation the ADR-0060 case drives (#370, #397).

    Each :attr:`name` selects a distinct ``async with self._lock:
    _run_to_completion(...)`` site; the suite runs the same
    cancelled-first / concurrent-second scenario against every one, so a
    regression reintroduced at any single site is caught rather than only at
    ``save_goal``. :meth:`first` and :meth:`second` act on *independent* subjects,
    so the concurrent second succeeds whatever the cancelled first's
    indeterminate effect turns out to be — which matters most for
    ``commit_transition``, whose compare-and-swap would otherwise couple them.

    **Reads are operations too** (#397). ADR-0060 §3 binds any method that acquires
    the resource, and every locked read here holds the connection lock around its
    own worker-thread SQL — so a regression replacing one read's
    ``_run_to_completion`` with a bare ``to_thread`` would hand the connection to a
    concurrent caller while that read's worker still used it, and every write case
    would still pass.
    """

    name: str

    async def prepare(self, store: PlanStore) -> None:
        """Establish anything the operation needs before it can run."""
        ...

    def first(self, store: PlanStore) -> Coroutine[Any, Any, object]:
        """The call the case suspends inside the resource and then cancels."""
        ...

    def second(self, store: PlanStore) -> Coroutine[Any, Any, object]:
        """The concurrent call barred from the resource until the first is done."""
        ...

    async def verify(self, store: PlanStore) -> None:
        """Assert the resource survived: the second call is whole and reads work."""
        ...


class _SaveGoalOp:
    """The ``save_goal`` upsert — ADR-0060's original subject."""

    name = "save_goal"

    async def prepare(self, store: PlanStore) -> None:
        """No preconditions."""

    def first(self, store: PlanStore) -> Coroutine[Any, Any, object]:
        """Save the goal whose write is cancelled."""
        return store.save_goal(_goal("cancel-1"))

    def second(self, store: PlanStore) -> Coroutine[Any, Any, object]:
        """Save an independent goal concurrently."""
        return store.save_goal(_goal("cancel-2"))

    async def verify(self, store: PlanStore) -> None:
        """The second goal is durable; the first is absent-or-whole; reads work."""
        assert await store.get_goal("cancel-2") == _goal("cancel-2")
        cancelled = await store.get_goal("cancel-1")
        assert cancelled is None or cancelled == _goal("cancel-1")
        assert {goal.id for goal in (await store.export()).goals} >= {"cancel-2"}


class _SavePlanOp:
    """The ``save_plan`` write, on two plans under two pre-saved goals."""

    name = "save_plan"

    async def prepare(self, store: PlanStore) -> None:
        """Save the goals the two plans hang off (``save_plan`` needs them)."""
        await store.save_goal(_goal("gA"))
        await store.save_goal(_goal("gB"))

    def first(self, store: PlanStore) -> Coroutine[Any, Any, object]:
        """Save the plan whose write is cancelled."""
        return store.save_plan(_plan("pA", "gA"))

    def second(self, store: PlanStore) -> Coroutine[Any, Any, object]:
        """Save an independent plan concurrently."""
        return store.save_plan(_plan("pB", "gB"))

    async def verify(self, store: PlanStore) -> None:
        """The second plan is durable; the cancelled one is absent-or-whole."""
        assert await store.get_plan("pB") == _plan("pB", "gB")
        cancelled = await store.get_plan("pA")
        assert cancelled is None or cancelled == _plan("pA", "gA")


class _StartExecutionOp:
    """The ``start_execution`` write, on two independent pre-saved plans."""

    name = "start_execution"

    async def prepare(self, store: PlanStore) -> None:
        """Save two goal+plan pairs so each execution has its own plan."""
        await store.save_goal(_goal("gA"))
        await store.save_plan(_plan("pA", "gA"))
        await store.save_goal(_goal("gB"))
        await store.save_plan(_plan("pB", "gB"))

    def first(self, store: PlanStore) -> Coroutine[Any, Any, object]:
        """Start the execution whose write is cancelled."""
        return store.start_execution("pA")

    def second(self, store: PlanStore) -> Coroutine[Any, Any, object]:
        """Start an independent execution concurrently."""
        return store.start_execution("pB")

    async def verify(self, store: PlanStore) -> None:
        """The second execution is live and readable."""
        assert "pB" in {state.plan_id for state in await store.active_executions()}


class _CommitTransitionOp:
    """The ``commit_transition`` compare-and-swap (#370, priority 2).

    The two calls claim a step on *different* executions, so each swap turns on
    its own execution's version and the concurrent second is decided
    independently of the cancelled first — which, shielded, may itself commit.
    """

    name = "commit_transition"

    def __init__(self) -> None:
        """Hold the two started executions the transitions claim against."""
        self._state_a: ExecutionState
        self._state_b: ExecutionState

    async def prepare(self, store: PlanStore) -> None:
        """Start two independent executions and remember their versions."""
        await store.save_goal(_goal("gA"))
        await store.save_plan(_plan("pA", "gA"))
        self._state_a = await _owned(
            store, await store.start_execution("pA"), attempt_id="aA", goal_id="gA"
        )
        await store.save_goal(_goal("gB"))
        await store.save_plan(_plan("pB", "gB"))
        self._state_b = await _owned(
            store, await store.start_execution("pB"), attempt_id="aB", goal_id="gB"
        )

    def first(self, store: PlanStore) -> Coroutine[Any, Any, object]:
        """Claim a step on execution A — the swap that is cancelled."""
        return store.commit_transition(_claim(self._state_a, attempt_id="aA"))

    def second(self, store: PlanStore) -> Coroutine[Any, Any, object]:
        """Claim a step on execution B concurrently."""
        return store.commit_transition(_claim(self._state_b, attempt_id="aB"))

    async def verify(self, store: PlanStore) -> None:
        """Execution B took its claim; the store still serves reads."""
        state = await store.get_execution(self._state_b.id)
        assert state is not None
        assert state.version > self._state_b.version


class _DeleteGoalOp:
    """The ``delete_goal`` write, on two independent pre-saved goals."""

    name = "delete_goal"

    async def prepare(self, store: PlanStore) -> None:
        """Save the two goals the calls delete."""
        await store.save_goal(_goal("gA"))
        await store.save_goal(_goal("gB"))

    def first(self, store: PlanStore) -> Coroutine[Any, Any, object]:
        """Delete goal A — the call that is cancelled."""
        return store.delete_goal("gA")

    def second(self, store: PlanStore) -> Coroutine[Any, Any, object]:
        """Delete goal B concurrently."""
        return store.delete_goal("gB")

    async def verify(self, store: PlanStore) -> None:
        """Goal B is gone; the store still serves reads."""
        assert await store.get_goal("gB") is None


class _ClearOp:
    """The ``clear`` write. No live step, so it is not refused (ADR-0014)."""

    name = "clear"

    async def prepare(self, store: PlanStore) -> None:
        """A goal to remove, so ``clear`` does real connection work."""
        await store.save_goal(_goal("gA"))

    def first(self, store: PlanStore) -> Coroutine[Any, Any, object]:
        """Clear the store — the call that is cancelled."""
        return store.clear()

    def second(self, store: PlanStore) -> Coroutine[Any, Any, object]:
        """Clear again concurrently."""
        return store.clear()

    async def verify(self, store: PlanStore) -> None:
        """The store is empty and still serves reads."""
        assert not (await store.export()).goals


class _ReadOp:
    """A locked ``PlanStore`` read, driven against a store seeded the same way (#397).

    The two calls are the *same* read against independent subjects, because what
    distinguishes a read op is its lock site and both calls have to enter it.
    Nothing is asserted about the cancelled read's answer — it has none, its task
    was cancelled — so :meth:`verify` pins the state the second call had to see,
    re-read once the scenario is over.
    """

    name = ""

    def __init__(self) -> None:
        """Hold the executions the read ops below address."""
        self._state_a: ExecutionState
        self._state_b: ExecutionState

    async def prepare(self, store: PlanStore) -> None:
        """Seed two independent goal/plan/execution chains for the reads to answer from."""
        await store.save_goal(_goal("gA"))
        await store.save_plan(_plan("pA", "gA"))
        self._state_a = await store.start_execution("pA")
        await store.save_goal(_goal("gB"))
        await store.save_plan(_plan("pB", "gB"))
        self._state_b = await store.start_execution("pB")

    def first(self, store: PlanStore) -> Coroutine[Any, Any, object]:
        """The read the case suspends inside the resource and then cancels."""
        raise NotImplementedError

    def second(self, store: PlanStore) -> Coroutine[Any, Any, object]:
        """The concurrent read barred from the resource until the first is done."""
        raise NotImplementedError

    async def verify(self, store: PlanStore) -> None:
        """A read cancelled mid-flight leaves the store whole and still readable."""
        assert await store.get_goal("gA") == _goal("gA")
        assert await store.get_plan("pB") == _plan("pB", "gB")
        exported = await store.export()
        assert {goal.id for goal in exported.goals} == {"gA", "gB"}


class _GetGoalOp(_ReadOp):
    """``get_goal`` — one row by id, under the connection lock."""

    name = "get_goal"

    def first(self, store: PlanStore) -> Coroutine[Any, Any, object]:
        """Read goal A — the call that is cancelled."""
        return store.get_goal("gA")

    def second(self, store: PlanStore) -> Coroutine[Any, Any, object]:
        """Read goal B concurrently."""
        return store.get_goal("gB")


class _GetPlanOp(_ReadOp):
    """``get_plan`` — its own lock site, though it shares a row reader with the others."""

    name = "get_plan"

    def first(self, store: PlanStore) -> Coroutine[Any, Any, object]:
        """Read plan A — the call that is cancelled."""
        return store.get_plan("pA")

    def second(self, store: PlanStore) -> Coroutine[Any, Any, object]:
        """Read plan B concurrently."""
        return store.get_plan("pB")


class _GetExecutionOp(_ReadOp):
    """``get_execution`` — the third ``async with self._lock`` around a row read."""

    name = "get_execution"

    def first(self, store: PlanStore) -> Coroutine[Any, Any, object]:
        """Read execution A — the call that is cancelled."""
        return store.get_execution(self._state_a.id)

    def second(self, store: PlanStore) -> Coroutine[Any, Any, object]:
        """Read execution B concurrently."""
        return store.get_execution(self._state_b.id)


class _ActiveExecutionsOp(_ReadOp):
    """``active_executions`` — the outstanding-work scan, its own lock site."""

    name = "active_executions"

    def first(self, store: PlanStore) -> Coroutine[Any, Any, object]:
        """Scan for live executions — the call that is cancelled."""
        return store.active_executions()

    def second(self, store: PlanStore) -> Coroutine[Any, Any, object]:
        """Scan again concurrently."""
        return store.active_executions()


class _ExportOp(_ReadOp):
    """``export`` — the whole-store read, its own lock site."""

    name = "export"

    def first(self, store: PlanStore) -> Coroutine[Any, Any, object]:
        """Export everything — the call that is cancelled."""
        return store.export()

    def second(self, store: PlanStore) -> Coroutine[Any, Any, object]:
        """Export again concurrently."""
        return store.export()


class _RecordEvidenceOp:
    """The ``record_evidence`` write, on two independent goals' histories."""

    name = "record_evidence"

    async def prepare(self, store: PlanStore) -> None:
        """Two goals with an attempt each, so both writes have somewhere to land."""
        await _goal_with_attempt(store, goal_id="gA", attempt_id="aA")
        await _goal_with_attempt(store, goal_id="gB", attempt_id="aB")

    def first(self, store: PlanStore) -> Coroutine[Any, Any, object]:
        """Record a row on goal A — the write that is cancelled."""
        return store.record_evidence(_evidence("evA", goal_id="gA", attempt_id="aA"))

    def second(self, store: PlanStore) -> Coroutine[Any, Any, object]:
        """Record a row on goal B concurrently."""
        return store.record_evidence(_evidence("evB", goal_id="gB", attempt_id="aB"))

    async def verify(self, store: PlanStore) -> None:
        """Goal B's row landed whole; the store still serves reads."""
        stored = await store.get_evidence("evB")
        assert stored is not None
        assert stored.goal_id == "gB"


class _RecordIntendedActionsOp:
    """The ``record_intended_actions`` write, on two independent goals (ADR-0265 §5)."""

    name = "record_intended_actions"

    async def prepare(self, store: PlanStore) -> None:
        """Two goals, so both mintings have somewhere to land and neither races."""
        await store.save_goal(_goal("gA"))
        await store.save_goal(_goal("gB"))

    def first(self, store: PlanStore) -> Coroutine[Any, Any, object]:
        """Mint on goal A — the write that is cancelled."""
        return store.record_intended_actions(_minting(_intended("iaA"), goal_id="gA"))

    def second(self, store: PlanStore) -> Coroutine[Any, Any, object]:
        """Mint on goal B concurrently."""
        return store.record_intended_actions(_minting(_intended("iaB"), goal_id="gB"))

    async def verify(self, store: PlanStore) -> None:
        """Goal B's minting landed whole; the store still serves reads."""
        stored = await store.get_goal("gB")
        assert stored is not None
        assert [action.id for action in stored.intended_actions] == ["iaB"]


class _EvidenceReadOp(_ReadOp):
    """A locked evidence **read**, over two independent goals' histories (#397).

    ADR-0060 §3 "binds any method that acquires the resource rather than any method
    that mutates", and both reads below hold the connection lock around their own
    worker-thread SQL — so a regression replacing either one's ``_run_to_completion``
    with a bare ``to_thread`` would hand the connection to a concurrent caller while
    that read's worker still used it, and every write case would still pass.
    """

    async def prepare(self, store: PlanStore) -> None:
        """Seed the read chains, and one evidence row on each goal."""
        await super().prepare(store)
        await store.open_attempt(_attempt("aA", goal_id="gA"))
        await store.open_attempt(_attempt("aB", goal_id="gB"))
        await store.record_evidence(_evidence("evA", goal_id="gA", attempt_id="aA"))
        await store.record_evidence(_evidence("evB", goal_id="gB", attempt_id="aB"))

    async def verify(self, store: PlanStore) -> None:
        """The store is whole, and both histories still read back."""
        await super().verify(store)
        assert [row.id for row in (await store.evidence_of("gA")).rows] == ["evA"]
        assert [row.id for row in (await store.evidence_of("gB")).rows] == ["evB"]


class _GetEvidenceOp(_EvidenceReadOp):
    """``get_evidence`` — one row by id, under the connection lock."""

    name = "get_evidence"

    def first(self, store: PlanStore) -> Coroutine[Any, Any, object]:
        """Read goal A's row — the call that is cancelled."""
        return store.get_evidence("evA")

    def second(self, store: PlanStore) -> Coroutine[Any, Any, object]:
        """Read goal B's row concurrently."""
        return store.get_evidence("evB")


class _EvidenceOfOp(_EvidenceReadOp):
    """``evidence_of`` — a goal's whole history and its count, its own lock site."""

    name = "evidence_of"

    def first(self, store: PlanStore) -> Coroutine[Any, Any, object]:
        """Read goal A's history — the call that is cancelled."""
        return store.evidence_of("gA")

    def second(self, store: PlanStore) -> Coroutine[Any, Any, object]:
        """Read goal B's history concurrently."""
        return store.evidence_of("gB")


#: Every locked ``PlanStore`` operation ADR-0060's case is run against: each is a
#: distinct lock site with its own ``_run_to_completion`` call. The writes came
#: first (#370); the reads are the same invariant on the other half of the surface
#: (#397), since ADR-0060 §3 binds any method that acquires the resource rather
#: than any method that mutates.
_CANCELLATION_OPS: tuple[Callable[[], _CancellationOp], ...] = (
    _SaveGoalOp,
    _SavePlanOp,
    _StartExecutionOp,
    _CommitTransitionOp,
    _DeleteGoalOp,
    _ClearOp,
    _GetGoalOp,
    _GetPlanOp,
    _GetExecutionOp,
    _ActiveExecutionsOp,
    _ExportOp,
    # ADR-0252 §12's three members are three more lock sites, and the reads are
    # operations too: a regression at any one of them would otherwise be invisible.
    _RecordEvidenceOp,
    _GetEvidenceOp,
    _EvidenceOfOp,
    # ADR-0265 §5's member is one more lock site, and a compare-and-swap one: a
    # regression that released the resource before its own work finished would let a
    # second caller decide against a version this one was about to advance.
    _RecordIntendedActionsOp,
)


class PlanStoreContract:
    """Behaviour every ``PlanStore`` implementation must exhibit."""

    @pytest.fixture
    def store(self) -> PlanStore:
        """Return an empty store under test."""
        raise NotImplementedError

    async def _started(self, store: PlanStore, *, steps: int = 1) -> ExecutionState:
        await store.save_goal(_goal())
        await store.save_plan(_plan(steps=steps))
        return await _owned(store, await store.start_execution("p1"))

    async def _step(
        self, store: PlanStore, state: ExecutionState, step_id: str = "s1"
    ) -> StepExecution:
        """Read one step back out of durable state, which is where a refusal is checked."""
        stored = await store.get_execution(state.id)
        assert stored is not None
        step = stored.step(step_id)
        assert step is not None
        return step

    async def seed_a_second_owner(self, store: PlanStore, attempt: GoalAttempt) -> None:
        """Write ``attempt`` **beneath** ADR-0255 §3's refusals, as a legacy store holds it.

        The one state this decision cannot reach through its own contract: an execution
        two attempts of one goal name. Both attempt-writing members refuse it now, so a
        subject implements this against its own storage — which is exactly what makes the
        arm about a store *written before* the decision rather than one this code can
        produce.

        Args:
            store: The subject under test.
            attempt: The row to write as it stands, with no refusal applied.
        """
        raise NotImplementedError

    # --- goals and plans ------------------------------------------------

    async def test_saves_and_reads_back_a_goal(self, store: PlanStore) -> None:
        await store.save_goal(_goal())
        stored = await store.get_goal("g1")
        assert stored is not None
        assert stored.statement == "relocate to Lisbon"

    async def test_missing_goal_reads_as_none(self, store: PlanStore) -> None:
        assert await store.get_goal("nope") is None

    async def test_save_goal_is_the_opening_write_alone(self, store: PlanStore) -> None:
        """ADR-0249 §12: ``save_goal`` refuses a goal whose id the store already holds.

        No longer an upsert, and the reason is stated rather than stylistic: "an upsert
        that replaced a whole goal would defeat §1's append-only interpretation and
        this section's compare-and-swap in one call". The refusal is the same error
        class an unknown goal already raises.
        """
        await store.save_goal(_goal())
        with pytest.raises(PlanningError):
            await store.save_goal(_goal())
        export = await store.export()
        assert len(export.goals) == 1

    async def test_a_plan_needs_its_goal_to_exist(self, store: PlanStore) -> None:
        """Refusing the orphan here is what lets export promise integrity."""
        with pytest.raises(PlanningError):
            await store.save_plan(_plan(goal_id="ghost"))

    # --- ADR-0228 §5: a `supersedes` that does not resolve is refused ---------
    # §12 obliges this suite to carry the three arms and both implementations to
    # satisfy them: the widening is **behavioural**, not merely documented — "a store
    # that accepts a `supersedes` naming a plan it does not hold stops conforming the
    # moment §5 binds" — so a suite left unextended would leave the rejection
    # asserted by nothing.

    async def test_a_plan_may_supersede_a_plan_the_store_holds(self, store: PlanStore) -> None:
        """The positive case, which is what makes the three refusals mean something.

        A revision names the plan it replaced, under the same goal, and the store
        takes it. ``None`` — "this plan replaced nothing" — is what every other plan
        carries and is never an error.
        """
        await store.save_goal(_goal())
        await store.save_plan(_plan("p1"))
        await store.save_plan(_plan("p2", supersedes="p1"))

        stored = await store.get_plan("p2")
        assert stored is not None
        assert stored.supersedes == "p1"
        first = await store.get_plan("p1")
        assert first is not None
        assert first.supersedes is None

    async def test_a_supersedes_naming_no_stored_plan_is_refused(self, store: PlanStore) -> None:
        """§5's first arm: the predecessor is not there.

        This is ADR-0014 §5's export promise kept at write time rather than repaired
        at read time — "every ``goal_id``/``plan_id`` referenced by an included
        record resolves within the same export" — which is the division ADR-0049 §1
        already records for the goal check.
        """
        await store.save_goal(_goal())
        with pytest.raises(PlanningError):
            await store.save_plan(_plan("p2", supersedes="ghost"))
        assert await store.get_plan("p2") is None

    async def test_a_plan_cannot_supersede_itself(self, store: PlanStore) -> None:
        """§5's second arm: a plan naming its own ``id``.

        A self-reference resolves — the plan is being written — so a store checking
        only "does it resolve" would accept a durable record claiming a plan replaced
        the plan it is. It is refused as an unknown goal already is, with the same
        error class.
        """
        await store.save_goal(_goal())
        with pytest.raises(PlanningError):
            await store.save_plan(_plan("p1", supersedes="p1"))
        assert await store.get_plan("p1") is None

    async def test_a_supersedes_naming_a_plan_under_another_goal_is_refused(
        self, store: PlanStore
    ) -> None:
        """§5's third arm: the chain does not span goals.

        ADR-0228 §1 rules that "the revision carries the **same** ``goal_id`` as the
        plan it replaces": the goal is minted once per turn from the user's
        unrewritten words, and "a second goal would make one turn look like two in
        every store that holds goals". A chain that spanned goals is the case a
        durable foreign key would be owed for, and §5 forbids it here instead.
        """
        await store.save_goal(_goal())
        await store.save_goal(_goal("g2"))
        await store.save_plan(_plan("p1", "g1"))

        with pytest.raises(PlanningError):
            await store.save_plan(_plan("p2", "g2", supersedes="p1"))
        assert await store.get_plan("p2") is None

    async def test_execution_needs_its_plan_to_exist(self, store: PlanStore) -> None:
        with pytest.raises(PlanningError):
            await store.start_execution("ghost")

    async def test_a_plan_id_cannot_be_reused_for_a_different_plan(self, store: PlanStore) -> None:
        """Replacing a plan would rewrite the record of what was decided.

        Worse, an execution already under way refers to its plan by id, so the
        swap would pair real step history with steps that were never planned.
        Re-planning takes a new id (ADR-0014 §2).
        """
        await store.save_goal(_goal())
        await store.save_plan(_plan(steps=1))
        await store.start_execution("p1")

        with pytest.raises(PlanningError):
            await store.save_plan(_plan(steps=2))

        stored = await store.get_plan("p1")
        assert stored is not None
        assert [step.id for step in stored.steps] == ["s1"]

    async def test_a_goals_objective_cannot_be_rewritten(self, store: PlanStore) -> None:
        """Otherwise plans already recorded would come to describe a new objective.

        Under ADR-0249 §12 the refusal is ``save_goal``'s own — it is the opening
        write alone — and the objective moves only by appending a revision, which is
        what :meth:`test_record_interpretation_appends_and_advances_the_version`
        drives.
        """
        await store.save_goal(_goal())
        await store.save_plan(_plan())

        rewritten = _goal(statement="delete all mail")
        with pytest.raises(PlanningError):
            await store.save_goal(rewritten)

        stored = await store.get_goal("g1")
        assert stored is not None
        assert stored.statement == "relocate to Lisbon"

    async def test_saving_an_identical_plan_again_is_idempotent(self, store: PlanStore) -> None:
        """A retry must not be punished — only a *differing* plan is a conflict."""
        await store.save_goal(_goal())
        await store.save_plan(_plan())
        await store.save_plan(_plan())

        export = await store.export()
        assert len(export.plans) == 1

    # --- ADR-0249 §12: the interpretation chain and the attempt --------------
    # §12 obliges the existing suite to gain the new obligations "in the same change
    # that adds them", so both conforming stores are held to every clause here rather
    # than to whichever one a lane happened to edit.

    async def test_record_interpretation_appends_and_advances_the_version(
        self, store: PlanStore
    ) -> None:
        """§12: one revision appended, ``version`` advanced, the goal returned.

        ``version`` and ``revision`` are different values and are never read for each
        other (§1): the first orders writes, the second names an understanding.
        """
        await store.save_goal(_goal())

        updated = await store.record_interpretation(
            GoalRevision(goal_id="g1", interpretation=_revision(2), expected_version=0)
        )

        assert [one.revision for one in updated.interpretation] == [1, 2]
        assert updated.version == 1
        assert updated.interpretation_elided == 0
        assert updated.statement == "relocate to Lisbon in September"
        stored = await store.get_goal("g1")
        assert stored is not None
        assert stored == updated

    async def test_record_interpretation_refuses_an_unknown_goal(self, store: PlanStore) -> None:
        with pytest.raises(PlanningError):
            await store.record_interpretation(
                GoalRevision(goal_id="ghost", interpretation=_revision(2), expected_version=0)
            )

    async def test_record_interpretation_refuses_a_revision_out_of_order(
        self, store: PlanStore
    ) -> None:
        """§1: each revision is **one greater** than the element before it."""
        await store.save_goal(_goal())
        with pytest.raises(PlanningError):
            await store.record_interpretation(
                GoalRevision(goal_id="g1", interpretation=_revision(3), expected_version=0)
            )

    async def test_two_interpretations_against_one_version_leave_one_loser(
        self, store: PlanStore
    ) -> None:
        """§16 arm 10, the goal half: compare-and-swap, with nothing lost.

        Two commands computed against the same ``expected_version``: one succeeds and
        one raises, with no interpretation lost and no interleaving. §12 states the
        read, the comparison and the write are **one indivisible step**.
        """
        await store.save_goal(_goal())
        first = GoalRevision(
            goal_id="g1", interpretation=_revision(2, outcome="the first"), expected_version=0
        )
        second = GoalRevision(
            goal_id="g1", interpretation=_revision(2, outcome="the second"), expected_version=0
        )

        await store.record_interpretation(first)
        with pytest.raises(StaleExecutionError):
            await store.record_interpretation(second)

        stored = await store.get_goal("g1")
        assert stored is not None
        assert [one.outcome for one in stored.interpretation] == [
            "relocate to Lisbon",
            "the first",
        ]
        assert stored.version == 1

    async def test_two_interpretations_dispatched_together_leave_one_loser(
        self, store: PlanStore
    ) -> None:
        """§12's indivisibility, over calls that are actually in flight together.

        The arm above awaits the winner before the loser starts, so an implementation
        that read and compared *before* a suspension and wrote after it without
        re-reading would pass it while letting two concurrent callers both succeed.
        This one dispatches both commands before either completes, which is the
        interleaving §12's "the read, the comparison and the write are **one
        indivisible step**" is stated about.

        **Exactly one succeeds**, and what is stored is the winner's own revision —
        asserted rather than assumed, because a store that let both through would
        leave a history the losing write had appended to.
        """
        await store.save_goal(_goal())
        commands = [
            GoalRevision(
                goal_id="g1",
                interpretation=_revision(2, outcome=f"understanding {label}"),
                expected_version=0,
            )
            for label in ("a", "b")
        ]

        settled = await asyncio.gather(
            *(store.record_interpretation(one) for one in commands), return_exceptions=True
        )

        won = [one for one in settled if isinstance(one, Goal)]
        lost = [one for one in settled if isinstance(one, BaseException)]
        assert len(won) == 1, "exactly one write of a version lands"
        assert all(isinstance(one, StaleExecutionError) for one in lost)

        stored = await store.get_goal("g1")
        assert stored is not None
        assert stored.version == 1, "one write, one version"
        assert [one.revision for one in stored.interpretation] == [1, 2]
        assert stored.statement == won[0].statement, "and the stored history is the winner's"

    async def test_two_attempt_transitions_dispatched_together_leave_one_loser(
        self, store: PlanStore
    ) -> None:
        """§12's indivisibility over the second command, on the same construction.

        :meth:`test_two_interpretations_dispatched_together_leave_one_loser`'s
        reasoning applied to ``commit_attempt``, because §12 states the rule of both
        writes and an implementation can get one right and the other wrong.
        """
        await store.save_goal(_goal())
        await store.save_plan(_plan())
        await store.save_plan(_plan(plan_id="p2"))
        await store.open_attempt(_attempt())
        moves = [
            AttemptTransition(attempt_id="a1", expected_version=0, add_plan_id=plan_id)
            for plan_id in ("p1", "p2")
        ]

        settled = await asyncio.gather(
            *(store.commit_attempt(one) for one in moves), return_exceptions=True
        )

        won = [one for one in settled if isinstance(one, GoalAttempt)]
        lost = [one for one in settled if isinstance(one, BaseException)]
        assert len(won) == 1, "exactly one transition of a version lands"
        assert all(isinstance(one, StaleExecutionError) for one in lost)

        stored = await store.get_attempt("a1")
        assert stored is not None
        assert stored.version == 1
        assert stored.plan_ids == won[0].plan_ids, "and the stored record is the winner's"
        assert len(stored.plan_ids) == 1, "the loser appended nothing"

    async def test_the_interpretation_history_is_bounded_and_the_elision_is_disclosed(
        self, store: PlanStore
    ) -> None:
        """§16 arm 9: the bound holds, the **oldest** goes, and the count says so.

        A goal driven past ``MAX_GOAL_INTERPRETATIONS`` keeps its **current**
        revision, drops the oldest, and reports how many have gone — ADR-0086 §4's
        ground applied: "a displaced citation that leaves no trace would make a belief
        report a narrower warrant than it has".
        """
        await store.save_goal(_goal())
        goal = await store.get_goal("g1")
        assert goal is not None
        for revision in range(2, MAX_GOAL_INTERPRETATIONS + 4):
            goal = await store.record_interpretation(
                GoalRevision(
                    goal_id="g1",
                    interpretation=_revision(revision, outcome=f"understanding {revision}"),
                    expected_version=goal.version,
                )
            )

        assert len(goal.interpretation) == MAX_GOAL_INTERPRETATIONS
        assert goal.interpretation_elided == 3
        assert goal.interpretation[-1].revision == MAX_GOAL_INTERPRETATIONS + 3
        assert goal.interpretation[0].revision == 4, "the oldest went, not the current"
        assert goal.statement == f"understanding {MAX_GOAL_INTERPRETATIONS + 3}"

    async def test_an_attempt_opens_reads_back_and_lists_in_opened_order(
        self, store: PlanStore
    ) -> None:
        await store.save_goal(_goal())
        await store.open_attempt(_attempt())
        await store.open_attempt(_attempt("a2"))

        assert await store.get_attempt("a1") == _attempt()
        assert [one.id for one in await store.attempts_of("g1")] == ["a1", "a2"]
        assert await store.get_attempt("nope") is None
        assert await store.attempts_of("ghost") == ()

    async def test_open_attempt_refuses_an_unknown_goal_and_a_reused_id(
        self, store: PlanStore
    ) -> None:
        with pytest.raises(PlanningError):
            await store.open_attempt(_attempt(goal_id="ghost"))
        await store.save_goal(_goal())
        await store.open_attempt(_attempt())
        with pytest.raises(PlanningError):
            await store.open_attempt(_attempt())

    async def test_commit_attempt_moves_the_phase_state_outcome_and_effort(
        self, store: PlanStore
    ) -> None:
        """§12: every absent member leaves its field unchanged."""
        await store.save_goal(_goal())
        await store.open_attempt(_attempt())

        moved = await store.commit_attempt(
            AttemptTransition(
                attempt_id="a1", expected_version=0, to_phase=AttemptPhase.PLAN, planner_calls=2
            )
        )
        assert moved.phase is AttemptPhase.PLAN
        assert moved.state is AttemptState.RUNNING, "an absent member changes nothing"
        assert moved.effort.planner_calls == 2
        assert moved.version == 1

        ended = await store.commit_attempt(
            AttemptTransition(
                attempt_id="a1",
                expected_version=1,
                to_phase=AttemptPhase.VERIFY,
                to_state=AttemptState.ENDED,
                outcome=AttemptOutcome.ANSWERED,
                ended_at=_WHEN,
            )
        )
        assert (ended.phase, ended.state, ended.outcome) == (
            AttemptPhase.VERIFY,
            AttemptState.ENDED,
            AttemptOutcome.ANSWERED,
        )
        assert await store.get_attempt("a1") == ended

    async def test_an_attempts_ledger_round_trips_the_kind_it_was_opened_under(
        self, store: PlanStore
    ) -> None:
        """ADR-0251 §5: the ledger carries which allowance its counters are measured against.

        The kind is stamped by ``orchestration`` at the instant the attempt is opened and
        is **never re-stamped, never derived at read time and never taken from a later
        turn's operation** — so what a store owes is that the value it was handed comes
        back byte for byte, through both of the routes an attempt is read by.

        **And an attempt opened with no kind stays with none**, which is what an
        attempt-opening turn that declared no operation means (§5) and what a row written
        before this decision decodes to. It is never repaired at read time into a default
        somebody guessed.
        """
        await store.save_goal(_goal())
        await store.open_attempt(
            _attempt().model_copy(update={"effort": AttemptEffort(kind=AttemptKind.CONVERSATIONAL)})
        )
        await store.open_attempt(_attempt(attempt_id="a2"))

        stamped = await store.get_attempt("a1")
        unstamped = await store.get_attempt("a2")

        assert stamped is not None
        assert unstamped is not None
        assert stamped.effort.kind is AttemptKind.CONVERSATIONAL
        assert unstamped.effort.kind is None, "no operation declared, and none invented"
        assert [one.effort.kind for one in await store.attempts_of("g1")] == [
            AttemptKind.CONVERSATIONAL,
            None,
        ], "and the same through the enumerating route"

    async def test_a_commit_that_moves_the_counters_leaves_the_kind_where_it_stood(
        self, store: PlanStore
    ) -> None:
        """ADR-0251 §5: "never re-stamped", asserted where a store could overwrite it.

        ``AttemptTransition`` carries no member for the kind and gains none, so a commit
        that advances the counters has nothing to say about it — and a store rebuilding
        the ledger from the transition alone, rather than folding into the stored one,
        would silently clear it.
        """
        await store.save_goal(_goal())
        await store.open_attempt(
            _attempt().model_copy(update={"effort": AttemptEffort(kind=AttemptKind.SPOKEN)})
        )

        moved = await store.commit_attempt(
            AttemptTransition(attempt_id="a1", expected_version=0, planner_calls=3)
        )

        assert moved.effort.planner_calls == 3
        assert moved.effort.kind is AttemptKind.SPOKEN, "the counters moved and the kind did not"
        assert "kind" not in AttemptTransition.model_fields, (
            "no transition names it: the stamp is the opening act's and no later act's"
        )

    async def test_the_attempts_references_grow_by_append_and_ignore_a_repeat(
        self, store: PlanStore
    ) -> None:
        """§16 arm 19: appended in order, and a repeated identifier is ignored.

        The identifiers are **real** rows of this goal, because ADR-0014 §5's closure
        obliges the store to refuse any other — see
        :meth:`test_an_attempt_cannot_take_a_reference_the_export_could_not_close_over`.
        """
        await store.save_goal(_goal())
        await store.save_plan(_plan())
        await store.save_plan(_plan(plan_id="p2"))
        execution = await store.start_execution("p1")
        await store.open_attempt(_attempt())

        moves = (
            AttemptTransition(attempt_id="a1", expected_version=0, add_plan_id="p1"),
            AttemptTransition(attempt_id="a1", expected_version=1, add_execution_id=execution.id),
            AttemptTransition(attempt_id="a1", expected_version=2, add_authorization_id="auth-1"),
            AttemptTransition(attempt_id="a1", expected_version=3, add_plan_id="p2"),
            AttemptTransition(attempt_id="a1", expected_version=4, add_plan_id="p1"),
        )
        for move in moves:
            attempt = await store.commit_attempt(move)

        assert attempt.plan_ids == ("p1", "p2"), "appended in order, the repeat ignored"
        assert attempt.execution_ids == (execution.id,)
        assert attempt.authorization_ids == ("auth-1",)

    async def test_an_attempt_cannot_take_a_reference_the_export_could_not_close_over(
        self, store: PlanStore
    ) -> None:
        """ADR-0014 §5's closure, kept at write time (ADR-0228 §5, ADR-0249 §11).

        An attempt's ``plan_ids`` and ``execution_ids`` are ``plan_id`` values
        referenced by an included record, so "every ``goal_id``/``plan_id`` referenced
        by an included record resolves within the same export" reaches them. A store
        that took one it does not hold would answer ``export`` with a document that
        does not validate — the failure discovered by whoever reads it back, which is
        exactly what ADR-0228 §5 moved the ``supersedes`` check to the write to
        prevent.

        **Under the attempt's own goal**, so the closure survives a deletion:
        ``delete_goal`` cascades a goal's plans, executions and attempts together, and
        a reference confined to one goal cannot outlive its target.
        """
        await store.save_goal(_goal())
        await store.save_goal(_goal("g2"))
        await store.save_plan(_plan(plan_id="p-other", goal_id="g2"))
        await store.open_attempt(_attempt())

        for dangling in (
            AttemptTransition(attempt_id="a1", expected_version=0, add_plan_id="missing"),
            AttemptTransition(attempt_id="a1", expected_version=0, add_execution_id="missing"),
            AttemptTransition(attempt_id="a1", expected_version=0, add_plan_id="p-other"),
        ):
            with pytest.raises(PlanningError):
                await store.commit_attempt(dangling)

        with pytest.raises(PlanningError):
            await store.open_attempt(
                GoalAttempt(id="a2", goal_id="g1", opened_at=_WHEN, plan_ids=("missing",))
            )

        assert (await store.export()).attempts == (_attempt(),), "and nothing was written"

    # --- ADR-0255 §3: the claim's two further conjuncts, and the ownership -----
    # invariant that makes the first of them a binding rather than a coincidence.

    async def test_a_claim_naming_an_attempt_the_store_does_not_hold_is_refused(
        self, store: PlanStore
    ) -> None:
        """§15 arm 7's first limb, and its class (ADR-0255 §3).

        An unknown attempt stays unknown however many times the caller re-reads, so the
        refusal is a ``PlanningError`` that is **not** a ``StaleExecutionError`` — a
        caller obeying the stale class's re-read-and-retry contract would loop against a
        write that cannot land. ``StaleExecutionError`` **subclasses** ``PlanningError``,
        so an arm asserting only the base class would be satisfied by the retryable one.
        """
        state = await self._started(store)

        with pytest.raises(PlanningError) as refusal:
            await store.commit_transition(_claim(state, attempt_id="never-opened"))

        assert not isinstance(refusal.value, StaleExecutionError)
        assert (await self._step(store, state)).status is StepStatus.PENDING

    async def test_a_claim_under_an_attempt_that_did_not_open_the_execution_is_refused(
        self, store: PlanStore
    ) -> None:
        """§15 arm 6's binding arm: ``execution_ids`` is what decides it.

        Execution E is opened under attempt A, A is committed ``ENDED``, and a second
        attempt **B of the same goal** stands neither terminal nor paused. A claim for E
        naming **B** satisfies every goal-level fact about B — same goal, live state,
        current revision — and is refused anyway, because the binding is the execution's
        membership and never the goal's. Without that, the cancellation of A would be
        defeated by naming B (ADR-0255 §3).
        """
        state = await self._started(store)
        await store.commit_attempt(
            AttemptTransition(
                attempt_id="a1",
                expected_version=0,
                to_state=AttemptState.ENDED,
                outcome=AttemptOutcome.ANSWERED,
                ended_at=_WHEN,
            )
        )
        await store.open_attempt(_attempt("a2"))

        with pytest.raises(PlanningError) as refusal:
            await store.commit_transition(_claim(state, attempt_id="a2"))

        assert not isinstance(refusal.value, StaleExecutionError)
        goal = await store.get_goal("g1")
        assert goal is not None
        assert goal.revision == 1, "and the goal's revision did not move"
        assert (await self._step(store, state)).status is StepStatus.PENDING

    @pytest.mark.parametrize(
        "state",
        [
            AttemptState.CANCELLED,
            AttemptState.ENDED,
            AttemptState.AWAITING_CLARIFICATION,
            AttemptState.AWAITING_AUTHORIZATION,
            AttemptState.BLOCKED,
        ],
    )
    async def test_a_claim_under_a_terminal_or_paused_attempt_is_refused(
        self, store: PlanStore, state: AttemptState
    ) -> None:
        """§15 arm 6's state-limb arms: **five** of ``AttemptState``'s seven members.

        The two terminal members and the three ADR-0249 §5 derives *paused* from, because
        *paused* is as disqualifying as *ended*: a store that accepted every non-terminal
        state would let a step reach the tool under an attempt the system is reporting as
        paused, in the one surface a user reads to find out whether anything is happening.
        The paused limb raises the same non-stale class, and its ground is what a caller
        can do rather than permanence — what lifts the pause is a **user act**, never a
        re-read.
        """
        execution = await self._started(store)
        terminal = state in TERMINAL_ATTEMPT_STATES
        await store.commit_attempt(
            AttemptTransition(
                attempt_id="a1",
                expected_version=0,
                to_state=state,
                outcome=AttemptOutcome.ANSWERED if terminal else None,
                ended_at=_WHEN if terminal else None,
            )
        )

        with pytest.raises(PlanningError) as refusal:
            await store.commit_transition(_claim(execution))

        assert not isinstance(refusal.value, StaleExecutionError)
        assert (await self._step(store, execution)).status is StepStatus.PENDING

    async def test_a_claim_under_an_attempt_holding_an_unresolved_effect_is_accepted(
        self, store: PlanStore
    ) -> None:
        """§15 arm 6's paired arm, and it is what stops the limb being a whitelist.

        ``EFFECT_UNRESOLVED`` is neither terminal nor one of the three §5 derives
        *paused* from, so a claim under it lands — which is the member's whole point
        (ADR-0255 §6): an attempt holding an effect it cannot account for is neither
        finished nor waiting on anybody. A ``RUNNING``-only rule would make §6's own
        producer unreachable.
        """
        execution = await self._started(store)
        await store.commit_attempt(
            AttemptTransition(
                attempt_id="a1",
                expected_version=0,
                to_state=AttemptState.EFFECT_UNRESOLVED,
            )
        )

        claimed = await store.commit_transition(_claim(execution))

        step = claimed.step("s1")
        assert step is not None
        assert step.status is StepStatus.RUNNING

    async def test_a_stale_revision_claim_keeps_the_retryable_class(self, store: PlanStore) -> None:
        """§15 arm 6's keep-the-two-questions-apart arm (ADR-0255 §3, ADR-0249 §8).

        Reached through the same member, an attempt that satisfies every limb of the new
        conjunct, and a goal whose revision has moved: the refusal is
        ``StaleExecutionError`` still, because that comparison is against a value that
        genuinely **moves** and re-reading is exactly what a caller should do. An
        implementation cannot satisfy the set by making ``commit_transition`` raise one
        class for everything.
        """
        state = await self._started(store)
        await store.record_interpretation(
            GoalRevision(goal_id="g1", interpretation=_revision(2), expected_version=0)
        )

        with pytest.raises(StaleExecutionError):
            await store.commit_transition(_claim(state))

    async def test_a_claim_on_a_plan_a_stored_plan_supersedes_is_refused(
        self, store: PlanStore
    ) -> None:
        """§15 arm 6's successor arms (ADR-0255 §3), and what makes them independent.

        A plan P2 carrying ``supersedes=P`` is saved while P's execution stands mid-run:
        the next claim on P is refused on the non-stale class, **the goal's revision did
        not move and the attempt is not terminal** — which is what makes this condition
        redundant with neither of the others — and P's already ``SUCCEEDED`` step keeps
        its output. A claim on **P2** is accepted, so the rule is *this plan has a
        successor* and not *this goal has two plans*.
        """
        state = await self._started(store, steps=2)
        state = await store.commit_transition(_claim(state))
        state = await store.commit_transition(
            StepTransition(
                execution_id=state.id,
                step_id="s1",
                to_status=StepStatus.SUCCEEDED,
                expected_version=state.version,
                output={"sent": True},
            )
        )
        await store.save_plan(_plan(plan_id="p2", supersedes="p1"))

        with pytest.raises(PlanningError) as refusal:
            await store.commit_transition(_claim(state, "s2"))

        assert not isinstance(refusal.value, StaleExecutionError)
        goal = await store.get_goal("g1")
        assert goal is not None
        assert goal.revision == 1, "the goal's revision did not move"
        attempt = await store.get_attempt("a1")
        assert attempt is not None
        assert attempt.state is AttemptState.RUNNING, "and the attempt is not terminal"
        held = await store.get_execution(state.id)
        assert held is not None
        first = held.step("s1")
        assert first is not None
        assert first.status is StepStatus.SUCCEEDED
        assert first.output == {"sent": True}, "the superseded plan's record is untouched"
        second = held.step("s2")
        assert second is not None
        assert second.status is StepStatus.PENDING, "at its entry status, nothing invoked"

    async def test_a_claim_on_the_successor_itself_is_accepted(self, store: PlanStore) -> None:
        """The successor conjunct's paired arm: P2 is claimable (ADR-0255 §3)."""
        await self._started(store)
        await store.save_plan(_plan(plan_id="p2", supersedes="p1"))
        successor = await _owned(store, await store.start_execution("p2"), attempt_id="a2")

        claimed = await store.commit_transition(_claim(successor, attempt_id="a2"))

        step = claimed.step("s1")
        assert step is not None
        assert step.status is StepStatus.RUNNING

    async def test_commit_attempt_refuses_an_execution_another_attempt_owns(
        self, store: PlanStore
    ) -> None:
        """§15 arm 6's bypass arm, on ``commit_attempt`` (ADR-0255 §3).

        With E already carried by A, appending it to **B** is refused — so the state in
        which E belongs to two attempts, under which a claim naming B would pass every
        conjunct, **cannot be reached through the store**. ADR-0249 §12's append-only
        rule is a different question and is untouched: a repeat of the same append on the
        attempt that owns E is still ignored rather than duplicated or refused.
        """
        state = await self._started(store)
        await store.open_attempt(_attempt("a2"))

        with pytest.raises(PlanningError) as refusal:
            await store.commit_attempt(
                AttemptTransition(attempt_id="a2", expected_version=0, add_execution_id=state.id)
            )

        assert not isinstance(refusal.value, StaleExecutionError)
        owner = await store.get_attempt("a1")
        assert owner is not None
        assert owner.execution_ids == (state.id,)

        repeated = await store.commit_attempt(
            AttemptTransition(
                attempt_id="a1", expected_version=owner.version, add_execution_id=state.id
            )
        )
        assert repeated.execution_ids == (state.id,), "the append is still idempotent"

    async def test_open_attempt_refuses_an_execution_another_attempt_owns(
        self, store: PlanStore
    ) -> None:
        """§15 arm 6's bypass arm through the other door (ADR-0255 §3).

        ``open_attempt`` takes a whole attempt and the tuple may arrive **non-empty**, so
        a caller could otherwise reach the forbidden state without calling
        ``commit_attempt`` at all — opening a live attempt that carries an ended
        attempt's execution.
        """
        state = await self._started(store)

        with pytest.raises(PlanningError) as refusal:
            await store.open_attempt(
                GoalAttempt(id="a2", goal_id="g1", opened_at=_WHEN, execution_ids=(state.id,))
            )

        assert not isinstance(refusal.value, StaleExecutionError)
        assert await store.get_attempt("a2") is None, "and nothing was written"

    async def test_two_appends_of_one_execution_dispatched_together_leave_one_loser(
        self, store: PlanStore
    ) -> None:
        """§15 arm 6's first indivisibility arm, on ADR-0249 §12's own construction.

        The serial arms above cannot see the interleaving the rule is stated about: an
        implementation that read, compared and then wrote across a suspension passes
        every one of them while letting **both** appends land — reaching, through the
        door this decision closes, exactly the legacy duplicate the arm below is reduced
        to refusing. Both commands are dispatched before either completes, over an
        execution **no attempt yet owns**.
        """
        await store.save_goal(_goal())
        await store.save_plan(_plan())
        state = await store.start_execution("p1")
        await store.open_attempt(_attempt("a1"))
        await store.open_attempt(_attempt("a2"))
        appends = [
            AttemptTransition(attempt_id=attempt_id, expected_version=0, add_execution_id=state.id)
            for attempt_id in ("a1", "a2")
        ]

        settled = await asyncio.gather(
            *(store.commit_attempt(one) for one in appends), return_exceptions=True
        )

        won = [one for one in settled if isinstance(one, GoalAttempt)]
        lost = [one for one in settled if isinstance(one, BaseException)]
        assert len(won) == 1, "exactly one attempt comes to own the execution"
        assert len(lost) == 1, "and the other is refused rather than also landing"
        assert isinstance(lost[0], PlanningError)
        assert not isinstance(lost[0], StaleExecutionError)
        owners = [one for one in await store.attempts_of("g1") if state.id in one.execution_ids]
        assert [one.id for one in owners] == [won[0].id], "one owner, and it is the winner"

    async def test_an_open_and_an_append_dispatched_together_leave_one_loser(
        self, store: PlanStore
    ) -> None:
        """§15 arm 6's second indivisibility arm: the two members raced against each other.

        ADR-0255 §3 states that **each** member decides exclusivity "in the same
        indivisible step as its own write", so an implementation can get one right and
        the other wrong — and a store whose ``open_attempt`` compared before a suspension
        would let the tuple it carries land beside an append that also landed.
        """
        await store.save_goal(_goal())
        await store.save_plan(_plan())
        state = await store.start_execution("p1")
        await store.open_attempt(_attempt("a1"))

        settled = await asyncio.gather(
            store.commit_attempt(
                AttemptTransition(attempt_id="a1", expected_version=0, add_execution_id=state.id)
            ),
            store.open_attempt(
                GoalAttempt(id="a2", goal_id="g1", opened_at=_WHEN, execution_ids=(state.id,))
            ),
            return_exceptions=True,
        )

        lost = [one for one in settled if isinstance(one, BaseException)]
        assert len(lost) == 1, "exactly one write lands"
        assert isinstance(lost[0], PlanningError)
        assert not isinstance(lost[0], StaleExecutionError)
        owners = [one for one in await store.attempts_of("g1") if state.id in one.execution_ids]
        assert len(owners) == 1, "and the execution is named by exactly one attempt"
        assert await store.get_attempt("a2") is None or owners[0].id == "a2", (
            "an attempt opened carrying an execution another attempt owns is not written"
        )

    async def test_a_successor_saved_against_a_claim_leaves_one_of_two_histories(
        self, store: PlanStore
    ) -> None:
        """§15 arm 6's two-writer arm for the successor conjunct (ADR-0255 §3).

        **The assertion is over which write linearized first and not over the final
        state**, because both records standing together is a *legitimate* outcome — the
        claim that won, followed by the save — and §4's committed-claim rule is what makes
        it one. So exactly one of two histories holds: the claim linearized **before** the
        successor's persistence, in which case it lands and the save then lands too; or
        the successor's persistence linearized first, in which case the claim is refused
        on the non-stale class. **What no history may show is a claim that linearized
        after the successor was persisted and nevertheless landed**, which is the only
        state the conjunct forbids.

        The order is read from the store's own completions rather than from the wall
        clock: each of these writes is one indivisible step, so the order they finish in
        is the order they linearized in. The serial arms above cannot see this
        interleaving at all — an implementation that read the plan's successors, compared
        and then wrote across a suspension passes every one of them while letting a claim
        that lost dispatch anyway, which is the race §7's sweep cannot close from another
        turn.
        """
        state = await self._started(store)
        order: list[str] = []
        refusals: list[BaseException] = []

        async def saving() -> None:
            await store.save_plan(_plan(plan_id="p2", supersedes="p1"))
            order.append("save")

        async def claiming() -> None:
            try:
                await store.commit_transition(_claim(state))
            except PlanningError as refusal:
                refusals.append(refusal)
                order.append("refused")
            else:
                order.append("claim")

        await asyncio.gather(saving(), claiming())

        assert all(not isinstance(one, StaleExecutionError) for one in refusals)
        assert len(refusals) == len([one for one in order if one == "refused"])

        assert await store.get_plan("p2") is not None, "the successor is persisted either way"
        assert len(order) == 2, "both writers finished"
        step = (await self._step(store, state)).status
        if order[0] == "save":
            assert order[1] == "refused", "a claim after a persisted successor never lands"
            assert step is StepStatus.PENDING, "so the step stands at its entry status"
        else:
            assert order == ["claim", "save"], "the claim won, and the save then landed"
            assert step is StepStatus.RUNNING, "which is a legitimate history, not a breach"

    async def test_a_legacy_duplicate_owner_refuses_the_claim_whichever_it_names(
        self, store: PlanStore
    ) -> None:
        """§15 arm 6's legacy arm (ADR-0255 §3), seeded beneath the refusals.

        A store written **before** this decision could hold an execution two attempts
        name, and the refusals above change no stored row — so what a reader does with one
        is fixed here, and it is to refuse, **whichever attempt the claim names**. A
        migration would have to choose which attempt owns it and nothing in the record
        says, so it would invent an ownership nobody recorded; accepting either owner
        would hand back the exact bypass the conjunct exists to close. No lane repairs,
        rewrites or deletes such a row.

        The seam is the subject's own (:meth:`seed_a_second_owner`), because reaching this
        state through the contract is precisely what this decision makes impossible.
        """
        state = await self._started(store)
        await store.commit_attempt(
            AttemptTransition(
                attempt_id="a1",
                expected_version=0,
                to_state=AttemptState.CANCELLED,
                outcome=AttemptOutcome.FAILED,
                ended_at=_WHEN,
            )
        )
        await self.seed_a_second_owner(
            store,
            GoalAttempt(id="a2", goal_id="g1", opened_at=_WHEN, execution_ids=(state.id,)),
        )

        for named in ("a1", "a2"):
            with pytest.raises(PlanningError) as refusal:
                await store.commit_transition(_claim(state, attempt_id=named))
            assert not isinstance(refusal.value, StaleExecutionError)

        assert (await self._step(store, state)).status is StepStatus.PENDING

    async def test_the_absent_and_the_misplaced_attempt_are_unconstructible(
        self, store: PlanStore
    ) -> None:
        """§15 arm 7's two constructions, asserted unconstructible rather than refused.

        A ``→ RUNNING`` transition carrying **no** ``attempt_id`` does not validate, and
        neither does an ``attempt_id`` on any other ``to_status`` — which is why neither
        is a store limb: naming the absent case as one would be a rule no conforming
        implementation could be shown to obey, and would put the boundary in two places.
        """
        state = await self._started(store)

        with pytest.raises(ValidationError):
            StepTransition(
                execution_id=state.id,
                step_id="s1",
                to_status=StepStatus.RUNNING,
                expected_version=state.version,
                bound_tool="smtp",
                approval_ref="perm-1",
            )
        with pytest.raises(ValidationError):
            StepTransition(
                execution_id=state.id,
                step_id="s1",
                to_status=StepStatus.AWAITING_APPROVAL,
                expected_version=state.version,
                bound_tool="smtp",
                attempt_id="a1",
            )

    async def test_save_goal_holds_an_oversized_history_to_the_bound(
        self, store: PlanStore
    ) -> None:
        """ADR-0249 §2, over the write it is stated of rather than over one member.

        "A goal whose sequence would exceed it drops its **oldest** element on the
        write that would exceed it, and the **current** interpretation is never
        dropped" — and ``save_goal`` is a write. A store that applied the bound only
        through ``record_interpretation`` would take an oversized history at the door
        and enforce the ceiling on nothing.

        The elision is **disclosed** on this write exactly as it is on the other: a
        history reporting fewer revisions than it held would answer §2's own question
        falsely (ADR-0086 §4).
        """
        oversized = _goal().model_copy(
            update={
                "interpretation": tuple(
                    _revision(number, outcome=f"understanding {number}")
                    for number in range(1, MAX_GOAL_INTERPRETATIONS + 4)
                )
            }
        )

        await store.save_goal(oversized)

        stored = await store.get_goal("g1")
        assert stored is not None
        assert len(stored.interpretation) == MAX_GOAL_INTERPRETATIONS
        assert stored.interpretation_elided == 3
        assert stored.interpretation[0].revision == 4, "the oldest went"
        assert stored.statement == f"understanding {MAX_GOAL_INTERPRETATIONS + 3}", (
            "and the current interpretation is never dropped"
        )

    async def test_commit_attempt_refuses_a_stale_version(self, store: PlanStore) -> None:
        """§16 arm 10, the attempt half."""
        await store.save_goal(_goal())
        await store.save_plan(_plan())
        await store.save_plan(_plan(plan_id="p2"))
        await store.open_attempt(_attempt())
        await store.commit_attempt(
            AttemptTransition(attempt_id="a1", expected_version=0, add_plan_id="p1")
        )
        with pytest.raises(StaleExecutionError):
            await store.commit_attempt(
                AttemptTransition(attempt_id="a1", expected_version=0, add_plan_id="p2")
            )

    async def test_commit_attempt_refuses_a_backwards_phase_and_a_terminal_move(
        self, store: PlanStore
    ) -> None:
        """§5, §6: the phase never moves backwards, and no move leaves a terminal."""
        await store.save_goal(_goal())
        await store.open_attempt(_attempt())
        moved = await store.commit_attempt(
            AttemptTransition(attempt_id="a1", expected_version=0, to_phase=AttemptPhase.EXECUTE)
        )
        with pytest.raises(IllegalTransitionError):
            await store.commit_attempt(
                AttemptTransition(
                    attempt_id="a1",
                    expected_version=moved.version,
                    to_phase=AttemptPhase.INVESTIGATE,
                )
            )

        ended = await store.commit_attempt(
            AttemptTransition(
                attempt_id="a1",
                expected_version=moved.version,
                to_state=AttemptState.ENDED,
                outcome=AttemptOutcome.ANSWERED,
                ended_at=_WHEN,
            )
        )
        with pytest.raises(IllegalTransitionError):
            await store.commit_attempt(
                AttemptTransition(
                    attempt_id="a1",
                    expected_version=ended.version,
                    to_state=AttemptState.RUNNING,
                )
            )

    async def test_commit_attempt_refuses_an_effort_that_would_go_backwards(
        self, store: PlanStore
    ) -> None:
        """§5: both counters are monotonically non-decreasing within an attempt."""
        await store.save_goal(_goal())
        await store.open_attempt(_attempt())
        moved = await store.commit_attempt(
            AttemptTransition(attempt_id="a1", expected_version=0, planner_calls=3)
        )
        with pytest.raises(PlanningError):
            await store.commit_attempt(
                AttemptTransition(attempt_id="a1", expected_version=moved.version, planner_calls=2)
            )

    async def test_commit_attempt_refuses_an_unknown_attempt(self, store: PlanStore) -> None:
        with pytest.raises(PlanningError):
            await store.commit_attempt(AttemptTransition(attempt_id="nope", expected_version=0))

    async def test_save_plan_refuses_a_plan_that_is_still_unstamped(self, store: PlanStore) -> None:
        """§16 arm 18's last clause, and §8's window closed at the store."""
        await store.save_goal(_goal())
        with pytest.raises(PlanningError):
            await store.save_plan(_plan(targets_revision=None))
        assert await store.get_plan("p1") is None

    async def test_a_plan_targeting_a_stale_revision_cannot_be_claimed(
        self, store: PlanStore
    ) -> None:
        """§16 arm 26: the stale-target refusal is the **store's**, not the driver's.

        A plan targeting the goal's current revision claims normally; once a later
        revision is recorded the same plan is refused, with the error class a stale
        ``expected_version`` already raises. Nothing dispatches a step of such a plan
        and nothing claims one.
        """
        await store.save_goal(_goal())
        await store.save_plan(_plan())
        state = await _owned(store, await store.start_execution("p1"))
        current = await store.commit_transition(_claim(state))
        assert current.step("s1") is not None

        await store.save_plan(_plan(plan_id="p2"))
        second = await _owned(store, await store.start_execution("p2"))
        await store.record_interpretation(
            GoalRevision(goal_id="g1", interpretation=_revision(2), expected_version=0)
        )

        with pytest.raises(StaleExecutionError):
            await store.commit_transition(_claim(second))

    async def test_an_unstamped_stored_plan_is_not_driven(self, store: PlanStore) -> None:
        """§8: a plan **already on disk** carrying ``None`` targets no revision.

        The one route to such a row is ADR-0249 §12's migration, so the row is put
        here the only way this contract admits — through ``save_plan`` with the check
        bypassed is not available, so the arm drives the rule the migration leaves
        behind by recording a revision the stored plan cannot target.
        """
        await store.save_goal(_goal())
        await store.save_plan(_plan())
        state = await _owned(store, await store.start_execution("p1"))
        await store.record_interpretation(
            GoalRevision(goal_id="g1", interpretation=_revision(2), expected_version=0)
        )
        with pytest.raises(StaleExecutionError):
            await store.commit_transition(_claim(state))

    async def test_save_plan_refuses_a_plan_that_does_not_revalidate(
        self, store: PlanStore
    ) -> None:
        """ADR-0023 §2 over the record ADR-0253 gives a graph.

        "``model_copy(update=...)`` skips validators — a pydantic property no type can
        close — so the invariant holds *at the validation boundary*, and **a write that
        reaches past it must re-validate**." ADR-0253 §1 makes a forward dependency
        **unconstructible**, so "acyclicity is a property of the type rather than a
        check somebody remembered to write" — and that is only true of what reaches this
        store if the store rebuilds the value. A store that kept this one would put a
        cycle into the record a driver walks, and the type would have stopped saying
        anything about it.

        Driven through ``depends_on`` rather than through a scalar because that is the
        clause whose whole safety argument is construction-time, and the arm is over
        **every** conforming implementation: before it, one store revalidated and two
        did not.
        """
        await store.save_goal(_goal())
        forward = _plan(steps=2).model_copy(
            update={
                "steps": (
                    _plan(steps=2).steps[0].model_copy(update={"depends_on": ("s2",)}),
                    _plan(steps=2).steps[1],
                )
            }
        )
        assert forward.steps[0].depends_on == ("s2",), "the caller reached past the validator"

        with pytest.raises(PlanningError):
            await store.save_plan(forward)
        assert await store.get_plan("p1") is None

    # --- ADR-0253 §9: the condition-label window, closed at the store ------

    async def test_save_plan_admits_a_condition_naming_an_element_of_the_revision(
        self, store: PlanStore
    ) -> None:
        """§9's conjunct in the direction that must keep working.

        A plan whose ``StepCondition.about`` is the ``id`` of a condition element of
        the revision it targets is saved and reads back **with the condition intact** —
        which is what makes the refusals below a window rather than a ban, and what
        ADR-0253 §14 arm 20's paired arm calls "the one that matters" one seam over.
        """
        await store.save_goal(_conditioned_goal())
        await store.save_plan(_conditioned_plan())
        stored = await store.get_plan("p1")
        assert stored is not None
        assert stored.steps[0].when[0].about == "e1"

    async def test_save_plan_refuses_a_plan_still_carrying_a_condition_label(
        self, store: PlanStore
    ) -> None:
        """§14 arm 7's paired store arm, and §14 arm 24 over this conformance suite.

        A plan still carrying an unsubstituted ``about`` of ``"D1"`` is refused **even
        where the goal holds an element whose ``id`` would otherwise have matched it**
        — the collision ADR-0253 §7's grammar rule makes unreachable, because a
        ``GoalElement`` whose ``id`` is ``"D1"`` is not constructible at all. So the
        arm builds the nearest goal that *could* have collided, and the refusal is
        still exact.

        The error class is the one ADR-0249 §8 gives an unstamped ``targets_revision``
        and ADR-0228 §5 an unresolvable ``supersedes``, "and for the same reason: the
        unresolved state exists only between the planner's return and the loop's
        substitution, and a window is closed at the store rather than trusted to close
        itself".
        """
        with pytest.raises(ValidationError):
            GoalElement(id="D1", text="the collision", ground=Ground.INFERRED)

        await store.save_goal(_conditioned_goal(element_id="e1"))
        with pytest.raises(PlanningError):
            await store.save_plan(_conditioned_plan(about="D1"))
        assert await store.get_plan("p1") is None

    async def test_save_plan_refuses_an_about_naming_an_element_of_another_revision(
        self, store: PlanStore
    ) -> None:
        """§9: the element must be one of **the revision the plan targets**.

        The goal's revision 2 carries a differently-identified element, so a plan
        targeting 2 and naming revision 1's element names nothing that revision holds
        — which is the state §5 requires ``about`` to be free of, checked where the
        store is the only place with a total order over writes.
        """
        await store.save_goal(_conditioned_goal(element_id="e1"))
        second = _revision(2).model_copy(
            update={
                "conditions": (
                    GoalElement(id="e2", text="a different condition", ground=Ground.INFERRED),
                )
            }
        )
        await store.record_interpretation(
            GoalRevision(goal_id="g1", interpretation=second, expected_version=0)
        )
        with pytest.raises(PlanningError):
            await store.save_plan(_conditioned_plan(about="e1", targets_revision=2))
        assert await store.get_plan("p1") is None

    async def test_save_plan_refuses_a_settles_the_targeted_revision_does_not_carry(
        self, store: PlanStore
    ) -> None:
        """§9: the conjunct reaches ``PlanInterpretation.settles`` on the same terms.

        "The loop takes each ``StepCondition.about`` **and each
        ``PlanInterpretation.settles``** for its own", so a plan whose interpretation
        still names a label is refused exactly as a step's condition is — and a plan
        whose interpretation names a real element is saved.
        """
        await store.save_goal(_conditioned_goal(element_id="e1"))
        base = _conditioned_plan().model_copy(update={"steps": (_plan().steps[0],)})
        with pytest.raises(PlanningError):
            await store.save_plan(
                base.model_copy(
                    update={
                        "interpretations": (PlanInterpretation(id="i1", settles="D1", record="m1"),)
                    }
                )
            )
        assert await store.get_plan("p1") is None

        saved = base.model_copy(
            update={"interpretations": (PlanInterpretation(id="i1", settles="e1", record="m1"),)}
        )
        await store.save_plan(saved)
        read_back = await store.get_plan("p1")
        assert read_back is not None
        assert read_back.interpretations[0].settles == "e1"

    async def test_a_plan_declaring_no_condition_is_not_checked_at_all(
        self, store: PlanStore
    ) -> None:
        """§9, and ADR-0253 §12's "it changes no behaviour of a plan that declares none
        of the new keys".

        The goal here carries **no** condition element at all, so the resolvable set is
        empty — and an ordinary plan still saves, because a plan naming nothing is not
        checked. Without that clause every plan this system has ever written would
        become unsaveable against a goal at revision 1, which ADR-0249 §9 says "carries
        no elements".
        """
        await store.save_goal(_goal())
        await store.save_plan(_plan())
        stored = await store.get_plan("p1")
        assert stored is not None
        assert (stored.steps[0].when, stored.interpretations) == ((), ())

    async def test_a_plan_carrying_the_whole_of_the_new_shape_round_trips(
        self, store: PlanStore
    ) -> None:
        """§10: what a conforming ``PlanStore`` must **round-trip**.

        Every field ADR-0253 adds, through one store and back: a dependency, a
        reference, a verification, a recency figure, a condition and an
        output-backed interpretation. A store that dropped any of them would leave a
        driver reading a plan the planner did not write, and ADR-0014 §2's "auditable
        record of a decision" would be a record of a different one.
        """
        await store.save_goal(_conditioned_goal())
        plan = ActionPlan(
            id="p1",
            goal_id="g1",
            steps=(
                PlanStep(id="s1", intent="refresh", capability="refresh_forecast"),
                PlanStep(
                    id="s2",
                    intent="book",
                    capability="send_email",
                    depends_on=("s1",),
                    resolves=(
                        ResultReference(
                            parameter="body", source=StepOutputRef(step="s1", field="summary")
                        ),
                    ),
                    when=(
                        StepCondition(
                            about="e1",
                            basis=EvidenceBasis.INTERPRETATION,
                            requires=InterpretationVerdict.QUALIFIES,
                        ),
                    ),
                    verifies=StepVerification(
                        kind=VerificationKind.FIELD_EQUALS, field="status", equals="confirmed"
                    ),
                    evidence_recency=timedelta(minutes=15),
                ),
            ),
            created_at=_WHEN,
            targets_revision=1,
            interpretations=(
                PlanInterpretation(
                    id="i1", settles="e1", reads=StepOutputRef(step="s1", field="summary")
                ),
            ),
        )
        await store.save_plan(plan)
        assert await store.get_plan("p1") == plan

    # --- ADR-0265: the intended action, the minting and save_plan's conjunct ---

    async def test_two_actions_minted_in_one_call_are_two_identities_a_plan_names_apart(
        self, store: PlanStore
    ) -> None:
        """ADR-0265 §10 arm 1(a), and it is the owner's two-rooms case whole.

        "A goal minted two ``IntendedAction``s in one ``IntendedActionMinting`` holds
        two members with **distinct** ids, and a plan whose two steps carry the **same**
        capability and byte-identical ``parameters`` but **different**
        ``intended_action`` values is saved" — so §6's triple is distinct for the two
        steps while the argument key is equal, "which is the fact an at-most-once claim
        scoped to the goal alone cannot see".

        **One compare-and-swap and not two** (§5): the two actions are appended in one
        call, so ``version`` advances by exactly one.
        """
        await store.save_goal(_goal())

        minted = await store.record_intended_actions(_minting(_intended("ia1"), _intended("ia2")))

        assert [action.id for action in minted.intended_actions] == ["ia1", "ia2"]
        assert minted.version == 1, "two actions in one call take one compare-and-swap"

        await store.save_plan(_acting_plan(first="ia1", second="ia2"))
        stored = await store.get_plan("p1")
        assert stored is not None
        first, second = stored.steps
        assert (first.capability, first.parameters) == (second.capability, second.parameters)
        assert (first.intended_action, second.intended_action) == ("ia1", "ia2")

    async def test_save_goal_refuses_a_goal_opened_carrying_an_intended_action(
        self, store: PlanStore
    ) -> None:
        """§1 and §2, and it is what makes §1's bound a bound.

        "The goal's opening write mints none: a goal is opened carrying revision 1
        alone (ADR-0249 §3) … so ``intended_actions`` is empty on every goal at the
        moment it is opened", and "**the only route to a new ``IntendedAction`` is a
        ``ProposedAction`` recorded by the member §5 adds**".

        **Driven with one seeded action and with an over-bound tuple**, because the two
        fail differently if only the second is closed: a store that checked the bound
        alone would admit a seeded action nobody minted, and one that checked neither
        would "take at the door what the ceiling forbids and enforce it on nothing" —
        ``save_goal``'s own sentence for ADR-0249 §2's ceiling. **The remedy is a
        refusal and never an elision** (§1), so nothing is stored trimmed either.
        """
        seeded = _goal().model_copy(update={"intended_actions": (_intended("ia1"),)})
        over = _goal().model_copy(
            update={
                "intended_actions": tuple(
                    _intended(f"ia{index}") for index in range(MAX_INTENDED_ACTIONS + 1)
                )
            }
        )

        for opened in (seeded, over):
            with pytest.raises(PlanningError):
                await store.save_goal(opened)
            assert await store.get_goal("g1") is None, "and nothing is stored trimmed"

    @pytest.mark.parametrize(
        "malformed",
        [None, "ia1", 7, {"ia1": True}, (7,)],
        ids=[
            "a-falsey-none",
            "a-string-whose-tuple-is-its-characters",
            "not-a-container",
            "a-mapping",
            "a-member-that-is-not-an-action",
        ],
    )
    async def test_save_goal_refuses_a_goal_whose_intended_actions_is_not_a_tuple(
        self, store: PlanStore, malformed: object
    ) -> None:
        """The field is **checked and not trusted**, and the store keeps nothing (§12).

        ADR-0023 §2: "``model_copy(update=...)`` skips validators (a pydantic property
        no type can close), so the invariant holds *at the validation boundary*, and **a
        write that reaches past it must re-validate**." A ``save_goal`` that tested the
        field for **truthiness** would wave ``None`` straight through — and then persist
        it, leaving the next ``record_intended_actions`` to raise a bare ``TypeError``
        out of a member this contract says raises ``PlanningError``. ``None`` is
        parametrised first for exactly that reason: it is the one malformed value the
        seeded-action refusal above cannot see.

        Every case is refused with ``PlanningError`` at the write, and nothing is
        stored — which is what makes the three conforming implementations agree rather
        than differ by whichever of them happened to revalidate.
        """
        opened = _goal().model_copy(update={"intended_actions": malformed})

        with pytest.raises(PlanningError):
            await store.save_goal(opened)
        assert await store.get_goal("g1") is None

    async def test_save_goal_refuses_a_goal_that_has_no_fields_at_all(
        self, store: PlanStore
    ) -> None:
        """The refusal reaches the emptiest object ``Goal`` can be made into.

        ``Goal.model_construct()`` is ADR-0023 §2's hazard at its limit: it carries **no
        ``id``**, so a store composing its refusal out of ``goal.id`` raises
        ``AttributeError`` — not the ``PlanningError`` this contract names — at exactly
        the input the revalidation exists for. The subject is read with ``getattr``
        instead, which is ``revalidated_revision``'s own construction for the same
        hazard one command over.
        """
        with pytest.raises(PlanningError):
            await store.save_goal(Goal.model_construct())

    @pytest.mark.parametrize(
        "malformed",
        [
            (),
            "ia1",
            None,
            7,
            {"ia1": True},
            (7,),
            (_intended("ia1"), _intended("ia1")),
        ],
        ids=[
            "an-empty-minting",
            "a-string-whose-tuple-is-its-characters",
            "a-falsey-none",
            "not-a-container",
            "a-mapping",
            "a-member-that-is-not-an-action",
            "two-members-under-one-id",
        ],
    )
    async def test_a_minting_mutated_past_its_validators_is_refused(
        self, store: PlanStore, malformed: object
    ) -> None:
        """The command is **checked and not trusted**, and the goal is left alone (§5).

        ADR-0023 §2: "``model_copy(update=...)`` skips validators (a pydantic property
        no type can close), so the invariant holds *at the validation boundary*, and **a
        write that reaches past it must re-validate**." Every shape here is one
        :class:`IntendedActionMinting` refuses at construction and one a caller can put
        back — and each fails differently if the store trusts it: an **empty** command
        advances ``Goal.version`` while minting nothing, a **string** is ``("i", "a",
        "1")`` and leaks an ``AttributeError`` where this contract names
        ``PlanningError``, and **two members under one id** breach §1's
        one-id-per-member invariant inside a single append — "a case the store's refusal
        of an id the goal **already holds** does not reach".

        This is ``test_a_revision_whose_invalidates_is_not_a_tuple_is_refused``'s case
        one command over, and the assertion that matters is the second one: the goal's
        ``intended_actions`` **and** its ``version`` are byte-for-byte what they were, so
        a refusal is never a write that happened to raise.
        """
        await store.save_goal(_goal())
        await store.record_intended_actions(_minting(_intended("held")))
        before = await store.get_goal("g1")
        assert before is not None

        with pytest.raises(PlanningError):
            await store.record_intended_actions(
                _minting(_intended("ia9"), expected_version=1).model_copy(
                    update={"actions": malformed}
                )
            )

        after = await store.get_goal("g1")
        assert after is not None
        assert after.intended_actions == before.intended_actions
        assert after.version == before.version

    async def test_record_intended_actions_refuses_an_unknown_goal(self, store: PlanStore) -> None:
        """§5: the member refuses a goal the store does not hold, as every other goal
        write does and with the class ADR-0249 §12 gives ``save_goal``."""
        with pytest.raises(PlanningError):
            await store.record_intended_actions(_minting(_intended()))

    async def test_two_mintings_against_one_version_leave_one_loser(self, store: PlanStore) -> None:
        """§5: "a stale write raises the ``PlanningError`` class ``StaleExecutionError``
        occupies for executions", and the read, the comparison and the write are one
        indivisible step.

        The loser writes **nothing**: the goal holds the winner's action alone, which is
        what makes a retry a re-read rather than a second append.
        """
        await store.save_goal(_goal())
        await store.record_intended_actions(_minting(_intended("ia1")))

        with pytest.raises(StaleExecutionError):
            await store.record_intended_actions(_minting(_intended("ia2")))

        held = await store.get_goal("g1")
        assert held is not None
        assert [action.id for action in held.intended_actions] == ["ia1"]
        assert held.version == 1

    async def test_two_mintings_dispatched_together_leave_one_loser(self, store: PlanStore) -> None:
        """§5's compare-and-swap, driven **concurrently** rather than in sequence.

        ``record_interpretation``'s own arm one member over, and for its reason: a
        sequential pair establishes that the second caller reads an advanced version,
        while only a concurrent pair establishes that "the read, the comparison and the
        write are **one indivisible step** with no separate read on which a decision is
        taken". Two mintings dispatched together against one version leave **one**
        winner and one ``StaleExecutionError``, and the goal holds the winner's action
        alone — never both, which is what a store that read, decided and then wrote
        would leave behind.
        """
        await store.save_goal(_goal())

        results = await asyncio.gather(
            store.record_intended_actions(_minting(_intended("ia1"))),
            store.record_intended_actions(_minting(_intended("ia2"))),
            return_exceptions=True,
        )

        winners = [one for one in results if isinstance(one, Goal)]
        losers = [one for one in results if isinstance(one, StaleExecutionError)]
        assert len(winners) == 1, f"expected exactly one winner, got {results}"
        assert len(losers) == 1, f"expected exactly one stale loser, got {results}"

        held = await store.get_goal("g1")
        assert held is not None
        assert len(held.intended_actions) == 1, "the loser appended nothing"
        assert held.version == 1
        assert held.intended_actions == winners[0].intended_actions

    async def test_record_intended_actions_refuses_an_id_the_goal_already_holds(
        self, store: PlanStore
    ) -> None:
        """§10 arm 5, and §5's first refusal.

        "An intended action is minted once", so an ``id`` the goal already carries is an
        **invariant breach at the current version** rather than a lost race — which is
        why it takes ``PlanningError`` and **not** the stale-write class: "a caller that
        re-read and retried would re-raise for ever".
        """
        await store.save_goal(_goal())
        await store.record_intended_actions(_minting(_intended("ia1")))

        with pytest.raises(PlanningError) as refusal:
            await store.record_intended_actions(_minting(_intended("ia1"), expected_version=1))
        assert not isinstance(refusal.value, StaleExecutionError)

        held = await store.get_goal("g1")
        assert held is not None
        assert [action.id for action in held.intended_actions] == ["ia1"]
        assert held.version == 1, "the refusal writes nothing, not even a version"

    async def test_a_minting_past_the_bound_is_refused_whole_and_elides_nothing(
        self, store: PlanStore
    ) -> None:
        """§10 arm 5's bound limb, over a goal at 63 handed **two**.

        "The last over a goal at 63 handed **two** actions, so the all-or-nothing limb
        is exercised and **neither** is recorded." §1 is what forbids the alternative:
        "no lane elides an intended action, for any reason, at any age", because "an
        identity that can vanish is not an identity" and a rollover "would make a
        completed booking's claim fresh again, silently, at the moment capacity ran
        out".
        """
        await store.save_goal(_goal())
        filled = await store.record_intended_actions(
            _minting(*(_intended(f"ia{index}") for index in range(1, MAX_INTENDED_ACTIONS)))
        )
        assert len(filled.intended_actions) == MAX_INTENDED_ACTIONS - 1

        with pytest.raises(PlanningError) as refusal:
            await store.record_intended_actions(
                _minting(_intended("over-1"), _intended("over-2"), expected_version=1)
            )
        assert not isinstance(refusal.value, StaleExecutionError)

        held = await store.get_goal("g1")
        assert held is not None
        assert held.intended_actions == filled.intended_actions, "no member elided"
        assert held.version == 1, "no count advanced"

    async def test_the_last_legal_mint_carries_a_goal_to_exactly_the_bound(
        self, store: PlanStore
    ) -> None:
        """§10 arm 5, over a **separate goal at 63** and never the one the refusal above
        is taken over.

        "One action handed to it **records** and carries it to exactly
        ``MAX_INTENDED_ACTIONS`` — the last legal mint, which a ``>=``-shaped comparison
        refuses while every refusal named here still passes, and which a fixture shared
        with the refusal above could not reach."
        """
        await store.save_goal(_goal("g2"))
        await store.record_intended_actions(
            _minting(
                *(_intended(f"ia{index}") for index in range(1, MAX_INTENDED_ACTIONS)),
                goal_id="g2",
            )
        )

        filled = await store.record_intended_actions(
            _minting(_intended("last"), goal_id="g2", expected_version=1)
        )

        assert len(filled.intended_actions) == MAX_INTENDED_ACTIONS
        assert filled.intended_actions[-1].id == "last"

    async def test_a_minting_whose_second_action_serves_nothing_records_neither(
        self, store: PlanStore
    ) -> None:
        """§10 arm 5's ``serves`` limb, "asserted over a **two-action** command whose
        **second** action carries the bad value, so that the refusal is shown to be
        all-or-nothing rather than a partial append".

        §5 states the check's one instant: "at the append every entry names an element
        of the **current** interpretation, and a value that does not is a caller
        reaching past ``orchestration`` with a dangling or foreign identifier".
        """
        await store.save_goal(_conditioned_goal(element_id="e1"))

        with pytest.raises(PlanningError) as refusal:
            await store.record_intended_actions(
                _minting(_intended("ia1", serves=("e1",)), _intended("ia2", serves=("nowhere",)))
            )
        assert not isinstance(refusal.value, StaleExecutionError)

        held = await store.get_goal("g1")
        assert held is not None
        assert held.intended_actions == (), "byte-for-byte what it was"
        assert held.version == 0

    async def test_a_minting_serving_another_goals_element_records_neither(
        self, store: PlanStore
    ) -> None:
        """§10 arm 5: "one naming an element of a **different** goal", on the same
        two-action shape.

        The element exists — it is simply not this goal's — so the refusal is about the
        **goal's own current interpretation** rather than about resolvability anywhere
        in the store, which is what §5's "an element of the goal's **current**
        interpretation" says and what a store comparing against every element it holds
        would silently widen.
        """
        await store.save_goal(_conditioned_goal(element_id="e1"))
        await store.save_goal(_conditioned_goal("g2", element_id="e2"))

        with pytest.raises(PlanningError) as refusal:
            await store.record_intended_actions(
                _minting(_intended("ia1", serves=("e1",)), _intended("ia2", serves=("e2",)))
            )
        assert not isinstance(refusal.value, StaleExecutionError)

        held = await store.get_goal("g1")
        assert held is not None
        assert (held.intended_actions, held.version) == ((), 0)

    async def test_a_serves_entry_goes_stale_and_is_neither_repaired_nor_re_checked(
        self, store: PlanStore
    ) -> None:
        """§3: "a ``serves`` entry naming an element not in the current revision is
        stale, truthful and harmless … the entry is not rewritten, not recomputed, not
        dropped and not refreshed", and "nothing re-checks it".

        §5 is explicit that the conjunct "is checkable exactly once, and that instant is
        the only one at which it is true by construction", so a later revision that
        drops the element leaves the record exactly as it was — and a later minting
        against that goal is not refused on account of the older action's stale link.
        """
        await store.save_goal(_conditioned_goal(element_id="e1"))
        await store.record_intended_actions(_minting(_intended("ia1", serves=("e1",))))
        await store.record_interpretation(
            GoalRevision(goal_id="g1", interpretation=_revision(2), expected_version=1)
        )

        held = await store.get_goal("g1")
        assert held is not None
        assert held.intended_actions[0].serves == ("e1",), "truthful, and not repaired"

        later = await store.record_intended_actions(
            _minting(_intended("ia2"), expected_version=held.version)
        )
        assert later.intended_actions[0].serves == ("e1",), "and not re-checked"

    async def test_save_plan_refuses_a_plan_naming_an_action_the_goal_does_not_hold(
        self, store: PlanStore
    ) -> None:
        """§4: "``PlanStore.save_plan`` **refuses a plan any of whose
        ``PlanStep.intended_action`` values is not the ``id`` of a member of
        ``Goal.intended_actions`` of the plan's own goal**", with the same error class
        ADR-0253 §9 gives an unresolvable condition label and for the same reason.

        The refusal is also driven with a plan still carrying an unsubstituted ``"A1"``,
        which §1's grammar rule makes exact: an ``IntendedAction`` whose ``id`` is
        ``"A1"`` is **not constructible**, so the label matches no action on any goal
        rather than silently scoping a claim to a different act.
        """
        await store.save_goal(_goal())
        await store.record_intended_actions(_minting(_intended("ia1")))

        with pytest.raises(ValidationError):
            IntendedAction(id="A1", intent="the collision")

        for named in ("ia2", "A1"):
            with pytest.raises(PlanningError):
                await store.save_plan(_acting_plan(first=named))
            assert await store.get_plan("p1") is None

    async def test_save_plan_saves_a_step_that_names_no_intended_action(
        self, store: PlanStore
    ) -> None:
        """§4: "A step naming no intended action is held to nothing by this decision" —
        a read step, a composition step and "every step of every plan written before
        this decision carry ``None``, and that is a conforming plan rather than a
        degraded one".

        The goal here holds an action, so the resolvable set is non-empty and the plan
        is still not checked: what turns the conjunct on is a step **naming** one.
        """
        await store.save_goal(_goal())
        await store.record_intended_actions(_minting(_intended("ia1")))

        await store.save_plan(_acting_plan(first=None))

        stored = await store.get_plan("p1")
        assert stored is not None
        assert stored.steps[0].intended_action is None

    async def test_the_conjunct_reads_the_goals_tuple_and_not_the_targeted_revision(
        self, store: PlanStore
    ) -> None:
        """§4: "``Goal.intended_actions`` is not revised: it is appended to", so the set
        ``save_plan`` reads is the goal's own tuple and ``targets_revision`` does not
        narrow it.

        That is the one place this conjunct differs from ADR-0253 §9's, which is stated
        over "the interpretation the plan's ``targets_revision`` names" — and a store
        that reused that scoping would refuse every plan of a goal whose understanding
        had moved since the act was minted, which is the *"change our booking to
        Sunday"* case §10 arm 2 turns on.
        """
        await store.save_goal(_goal())
        await store.record_intended_actions(_minting(_intended("ia1")))
        await store.record_interpretation(
            GoalRevision(goal_id="g1", interpretation=_revision(2), expected_version=1)
        )

        await store.save_plan(_acting_plan().model_copy(update={"targets_revision": 2}))

        stored = await store.get_plan("p1")
        assert stored is not None
        assert stored.steps[0].intended_action == "ia1"

    async def test_a_goals_intended_actions_round_trip_and_the_export_carries_them(
        self, store: PlanStore
    ) -> None:
        """§10 arm 6: "the record round-trips and the export closes".

        "``PlanExport`` carries them inside ``goals`` with no new member", because an
        ``IntendedAction`` rides inside ``Goal`` and ADR-0014 §5's closure rule is
        satisfied by construction. And **a goal written before this decision decodes
        with ``intended_actions`` empty**, which is the same assertion from the other
        side: the store this suite runs over has never been told about an action for
        ``g2``, and does not invent one.
        """
        await store.save_goal(_goal())
        await store.save_goal(_goal("g2"))
        await store.record_intended_actions(_minting(_intended("ia1", serves=()), _intended("ia2")))

        export = await store.export()

        carried = {goal.id: goal.intended_actions for goal in export.goals}
        assert [action.id for action in carried["g1"]] == ["ia1", "ia2"]
        assert carried["g2"] == ()

    async def test_deleting_a_goal_removes_the_actions_with_it(self, store: PlanStore) -> None:
        """§5: "``delete_goal``'s cascade reaches the actions because they are inside
        the goal", and ADR-0014 §5's "a goal the user deletes must not leave its plan
        history behind" "needs no extension: deleting the goal row deletes them".

        **An intended action is not a reason to refuse a deletion** (§5): the live-step
        refusal is unchanged and nothing here adds a second one.
        """
        await store.save_goal(_goal())
        await store.record_intended_actions(_minting(_intended("ia1"), _intended("ia2")))

        await store.delete_goal("g1")

        assert await store.get_goal("g1") is None
        export = await store.export()
        assert export.goals == ()

    async def test_two_executions_of_one_plan_produce_two_distinguishable_rows(
        self, store: PlanStore
    ) -> None:
        """§14 arm 9, and it is what ``(plan_id, step_id)`` alone could not satisfy.

        ADR-0014 §5's ``start_execution`` mints a **new** ``ExecutionState`` per run, so
        two executions of one plan can carry two different ``StepExecution.output``
        values for one step. §8's reason for naming the execution is exactly that: a
        pair of plan and step "names a *decision* and not a *value*, and a row built on
        it could not say which output it read".

        The arm runs one plan twice, returns a different output each time, and asserts
        that the two rows' ``interpreted_output.execution_id`` differ **and** that each
        resolves through ``get_execution`` to the output its verdict was formed over.
        Composing such a row is ``orchestration``'s (§8) and A7's to perform, so the
        rows here are constructed rather than produced — what is under test is that the
        reference the type carries resolves, which is the property §8 mints it for.
        """
        await store.save_goal(_goal())
        await store.save_plan(_plan())
        outputs = {}
        for run, value in (("first", "cloudy"), ("second", "clear")):
            state = await _owned(store, await store.start_execution("p1"))
            state = await store.commit_transition(_claim(state))
            await store.commit_transition(
                StepTransition(
                    execution_id=state.id,
                    step_id="s1",
                    to_status=StepStatus.SUCCEEDED,
                    expected_version=state.version,
                    output={"summary": value},
                )
            )
            outputs[run] = (state.id, value)

        assert outputs["first"][0] != outputs["second"][0]
        for run, (execution_id, value) in outputs.items():
            row = GoalEvidence(
                id=f"ev-{run}",
                goal_id="g1",
                attempt_id="a1",
                basis=EvidenceBasis.INTERPRETATION,
                declaration="e1",
                supported=(_REGION,),
                supported_elided=0,
                read_at=_WHEN,
                returned=0,
                admitted=0,
                verdict=InterpretationVerdict.QUALIFIES.value,
                standing=EvidenceStanding.STANDING,
                interpreted_output=InterpretedOutput(
                    execution_id=execution_id, step_id="s1", field="summary"
                ),
            )
            await store.record_evidence(row)
            named = row.interpreted_output
            assert named is not None
            execution = await store.get_execution(named.execution_id)
            assert execution is not None
            step = execution.step(named.step_id)
            assert step is not None
            assert isinstance(step.output, Mapping)
            assert step.output[named.field or ""] == value
            # The plan is derived and never copied (§8): `ExecutionState.plan_id`
            # already names it, and a second carrier is ADR-0251 §3's defect.
            assert execution.plan_id == "p1"

    # --- ADR-0250 §§1, 2, 9: engagement, status and the candidate set ------

    async def test_engage_goal_stamps_both_fields_and_advances_the_version(
        self, store: PlanStore
    ) -> None:
        """§1, §9: the one writer of ``last_engaged_at`` and ``last_engaged_in``.

        It writes **nothing else** — not the status, not the interpretation, not the
        attempt — and ``conversation_id`` is **never rewritten**, which is ADR-0249
        §1's provenance clause binding entire: the record still answers *where did this
        objective come from* after the goal has been engaged from a second
        conversation.
        """
        await store.save_goal(_goal())
        stored = await store.get_goal("g1")
        assert stored is not None
        assert (stored.last_engaged_at, stored.last_engaged_in) == (None, None)

        engaged = await store.engage_goal(
            "g1", at=_ENGAGED_AT, conversation_id="c2", expected_version=0
        )

        assert engaged.last_engaged_at == _ENGAGED_AT
        assert engaged.last_engaged_in == "c2"
        assert engaged.conversation_id == "c1", "provenance, and never rewritten"
        assert engaged.version == 1
        assert engaged.status is GoalStatus.ACTIVE
        assert [one.revision for one in engaged.interpretation] == [1]
        assert await store.attempts_of("g1") == ()
        assert await store.get_goal("g1") == engaged

    async def test_engage_goal_refuses_a_stale_version_and_an_unknown_goal(
        self, store: PlanStore
    ) -> None:
        """§9: "It refuses on a stale ``expected_version``".

        ADR-0249 §1 makes ``version`` "the **compare-and-swap** token every mutation of
        the goal advances", and a stamp that skipped it would be the one mutation two
        concurrent turns could interleave.
        """
        await store.save_goal(_goal())
        await store.engage_goal("g1", at=_ENGAGED_AT, conversation_id="c1", expected_version=0)

        with pytest.raises(StaleExecutionError):
            await store.engage_goal("g1", at=_ENGAGED_AT, conversation_id="c1", expected_version=0)
        with pytest.raises(PlanningError):
            await store.engage_goal(
                "missing", at=_ENGAGED_AT, conversation_id="c1", expected_version=0
            )

    async def test_two_engagements_dispatched_together_leave_one_loser(
        self, store: PlanStore
    ) -> None:
        """§20 arm 19's third pair, on the interleaving §12's indivisibility is about.

        "Two ``engage_goal`` calls computed against the same ``expected_version``: one
        succeeds and one raises." Dispatched before either completes, so an
        implementation that read and compared before a suspension and wrote after it
        without re-reading fails here rather than passing a sequential arm.

        **The loser is counted and not merely type-checked**, because the arm is "one
        succeeds and **one raises**" and a conformance suite that let the second call
        answer anything at all would certify a store breaking the signature
        :meth:`PlanStore.engage_goal` states — it returns a :class:`Goal` or raises.
        One winner plus one loser over two dispatched calls admits no third kind of
        result; a membership test over the losers alone passes vacuously when there
        are none.
        """
        await store.save_goal(_goal())

        settled = await asyncio.gather(
            *(
                store.engage_goal("g1", at=_ENGAGED_AT, conversation_id=name, expected_version=0)
                for name in ("c2", "c3")
            ),
            return_exceptions=True,
        )

        won = [one for one in settled if isinstance(one, Goal)]
        lost = [one for one in settled if isinstance(one, BaseException)]
        assert len(won) == 1, "exactly one write of a version lands"
        assert len(lost) == 1, "and the other call raised rather than answering with a value"
        assert isinstance(lost[0], StaleExecutionError), (
            "the loser computed against a version that had moved, which is what "
            f"engage_goal refuses on: {lost[0]!r}"
        )

        stored = await store.get_goal("g1")
        assert stored is not None
        assert stored.version == 1, "one write, one version"
        assert stored.last_engaged_in == won[0].last_engaged_in

    @pytest.mark.parametrize(
        "status",
        [GoalStatus.ACTIVE, GoalStatus.ABANDONED, GoalStatus.ACHIEVED, GoalStatus.BLOCKED],
    )
    async def test_set_goal_status_refuses_no_member_of_the_vocabulary(
        self, store: PlanStore, status: GoalStatus
    ) -> None:
        """§9: the store refuses neither ``ACHIEVED`` nor ``BLOCKED``.

        "A10 and A3 write them through this same route and a store that refused a
        member would be a second place the vocabulary is decided." **Which act may
        write which member is the caller's rule**, and ADR-0250 §20 arm 23 is what
        pins that over the shipped tree — the store's job is to make the route exist
        and to make it the only one.
        """
        await store.save_goal(_goal())

        moved = await store.set_goal_status("g1", status=status, at=_ENGAGED_AT, expected_version=0)

        assert moved.status is status
        assert moved.version == 1
        assert (moved.last_engaged_at, moved.last_engaged_in) == (None, None), (
            "it writes nothing else: not the engagement stamp (ADR-0250 §9)"
        )
        assert [one.revision for one in moved.interpretation] == [1]

    async def test_set_goal_status_refuses_a_stale_version_and_an_unknown_goal(
        self, store: PlanStore
    ) -> None:
        """§20 arm 23's last limb: "on **both** conforming implementations"."""
        await store.save_goal(_goal())
        await store.set_goal_status(
            "g1", status=GoalStatus.ABANDONED, at=_ENGAGED_AT, expected_version=0
        )

        with pytest.raises(StaleExecutionError):
            await store.set_goal_status(
                "g1", status=GoalStatus.ACTIVE, at=_ENGAGED_AT, expected_version=0
            )
        with pytest.raises(PlanningError):
            await store.set_goal_status(
                "missing", status=GoalStatus.ACTIVE, at=_ENGAGED_AT, expected_version=0
            )

    async def test_no_other_write_moves_either_engagement_field(self, store: PlanStore) -> None:
        """§1, §20 arm 18's store half: exactly one writer, and these are not it.

        "``save_goal``, ``record_interpretation``, ``open_attempt`` and
        ``commit_attempt`` each leave both exactly as they found them", and neither a
        candidate-set read nor an export moves either. The four *acts* that engage a
        goal are ADR-0250 §19's M3; what a store can be held to is that nothing else
        does.
        """
        await store.save_goal(_goal())
        await store.engage_goal("g1", at=_ENGAGED_AT, conversation_id="c1", expected_version=0)
        await store.save_plan(_plan())
        await store.open_attempt(_attempt())
        await store.record_interpretation(
            GoalRevision(goal_id="g1", interpretation=_revision(2), expected_version=1)
        )
        await store.commit_attempt(
            AttemptTransition(attempt_id="a1", expected_version=0, add_plan_id="p1")
        )
        await store.candidates_for("c1", limit=MAX_ASSOCIATION_CANDIDATES)
        await store.export()

        stored = await store.get_goal("g1")
        assert stored is not None
        assert (stored.last_engaged_at, stored.last_engaged_in) == (_ENGAGED_AT, "c1")

    @pytest.mark.parametrize(
        "instant",
        [
            pytest.param(datetime(2026, 2, 1), id="naive"),  # noqa: DTZ001 — the subject
            pytest.param(datetime(2026, 2, 1, tzinfo=timezone(timedelta(hours=2))), id="offset"),
        ],
    )
    async def test_an_engagement_instant_is_validated_before_it_is_committed(
        self, store: PlanStore, instant: datetime
    ) -> None:
        """ADR-0023 §2: a write that reaches past ``model_copy`` must re-validate.

        "``model_copy(update=...)`` skips validators (a pydantic property no type can
        close), so the invariant holds *at the validation boundary*, and **a write that
        reaches past it must re-validate**." A store that stamped an unvalidated
        instant would **commit** it and then fail to decode its own row on the next
        read — a record the type is supposed to make impossible, persisted, with the
        fault surfacing at a reader that did nothing wrong.

        The offset case is the other half of §2: an aware instant is **converted** to
        UTC rather than refused, because "Python compares two aware datetimes sharing a
        ``tzinfo`` by their naive wall-clock values", so an unconverted one orders
        wrongly among its peers — which is exactly what ADR-0250 §1's key sorts on.
        """
        await store.save_goal(_goal())

        if instant.tzinfo is None:
            with pytest.raises(PlanningError):
                await store.engage_goal("g1", at=instant, conversation_id="c1", expected_version=0)
            unmoved = await store.get_goal("g1")
            assert unmoved is not None
            assert (unmoved.last_engaged_at, unmoved.version) == (None, 0), "and nothing moved"
            return

        engaged = await store.engage_goal(
            "g1", at=instant, conversation_id="c1", expected_version=0
        )
        assert engaged.last_engaged_at == instant
        assert engaged.last_engaged_at is not None
        assert engaged.last_engaged_at.tzinfo is UTC, "converted rather than stored as given"
        assert await store.get_goal("g1") == engaged, "so the row reads back"

    async def test_a_settlement_instant_is_validated_before_it_is_committed(
        self, store: PlanStore
    ) -> None:
        """ADR-0023 §2, over the other record this decision stamps.

        The same clause reaches ``settle_question``'s ``at``: a naive settlement
        instant committed here would leave a question the store can write and then
        cannot decode, and the question would be **terminal** — its content already
        cleared — so nothing could recover what it had asked.
        """
        await _goal_with_attempt(store)
        await store.record_question(_question())

        with pytest.raises(PlanningError):
            await store.settle_question(
                "q1",
                disposition=GoalQuestionDisposition.ANSWERED,
                at=datetime(2026, 3, 1),  # noqa: DTZ001 — the subject
            )

        held = await store.get_question("q1")
        assert held is not None
        assert held.disposition is GoalQuestionDisposition.OPEN, "and nothing moved"
        assert held.text == "which campsite?", "and the content is still there"

    async def test_the_candidate_set_is_the_two_field_membership_test(
        self, store: PlanStore
    ) -> None:
        """§2: opened **in** this conversation, **or** last engaged in it.

        "A goal that has moved between conversations is a candidate in **two** of
        them — the one that opened it and the one that last engaged it", and in no
        more, because ``last_engaged_in`` holds one value. A closed goal is a
        candidate too: "open or closed alike".
        """
        await store.save_goal(_goal("g1"))
        await store.save_goal(_goal("g2"))
        await store.engage_goal("g2", at=_ENGAGED_AT, conversation_id="c2", expected_version=0)
        await store.set_goal_status(
            "g1", status=GoalStatus.ACHIEVED, at=_ENGAGED_AT, expected_version=0
        )

        first = await store.candidates_for("c1", limit=MAX_ASSOCIATION_CANDIDATES)
        second = await store.candidates_for("c2", limit=MAX_ASSOCIATION_CANDIDATES)
        third = await store.candidates_for("c3", limit=MAX_ASSOCIATION_CANDIDATES)

        assert {one.id for one in first.goals} == {"g1", "g2"}, "both were opened in c1"
        assert [one.id for one in second.goals] == ["g2"], "and one was last engaged in c2"
        assert third.goals == (), "a third conversation reaches neither"
        assert (first.elided, second.elided, third.elided) == (0, 0, 0)
        assert first.goals[0].status is GoalStatus.ACHIEVED or any(
            one.status is GoalStatus.ACHIEVED for one in first.goals
        ), "a closed goal is a candidate while its conversation is retained"

    async def test_the_candidate_set_is_ordered_with_the_absent_instant_last(
        self, store: PlanStore
    ) -> None:
        """§1, §20 arm 26's ordering half: the key, its tie-break, and the absence.

        "``last_engaged_at`` descending with the ``goal_id`` ascending as the
        tie-break, and a goal whose ``last_engaged_at`` is absent sorts **after** every
        goal carrying one." The absent instant sorts last because "sorting it first
        would make the oldest, least-touched objective in the store the focused goal of
        every conversation that holds one", and the tie-break is stated because a
        migrated pair carrying no instant at all is reachable.
        """
        for name in ("g1", "g2", "g3", "g4"):
            await store.save_goal(_goal(name))
        await store.engage_goal("g3", at=_ENGAGED_AT, conversation_id="c1", expected_version=0)
        await store.engage_goal("g1", at=_LATER_ENGAGED, conversation_id="c1", expected_version=0)

        page = await store.candidates_for("c1", limit=MAX_ASSOCIATION_CANDIDATES)

        assert [one.id for one in page.goals] == ["g1", "g3", "g2", "g4"], (
            "engaged later first, then the two carrying no instant by id ascending"
        )

    async def test_the_candidate_set_is_capped_and_counts_what_it_dropped(
        self, store: PlanStore
    ) -> None:
        """§2, §20 arm 21's store half: the cap, and the true remainder.

        "``elided`` carries the true remainder, and no dropped goal is rendered." A
        count and never an identifier, and "a store that cannot count them does not
        answer ``0``".
        """
        for index in range(1, MAX_ASSOCIATION_CANDIDATES + 4):
            await store.save_goal(_goal(f"g{index:02d}"))

        page = await store.candidates_for("c1", limit=MAX_ASSOCIATION_CANDIDATES)

        assert len(page.goals) == MAX_ASSOCIATION_CANDIDATES
        assert page.elided == 3, "the true remainder, not a flag"
        assert [one.id for one in page.goals] == [
            f"g{index:02d}" for index in range(1, MAX_ASSOCIATION_CANDIDATES + 1)
        ]

    async def test_the_tie_break_is_applied_only_to_instants_that_are_equal(
        self, store: PlanStore
    ) -> None:
        """§1: "the ``goal_id`` **ascending** as the tie-break" — for a *tie*.

        Two instants a microsecond apart are not a tie, and ordering them by a float of
        the datetime makes them one: ``datetime.timestamp()`` returns seconds as a
        ``float``, and from about 2262 two instants a microsecond apart compare **equal**
        as floats while comparing correctly as datetimes. A store sorting on the float
        would then fall through to the id, returning the *older* goal first whenever the
        ids happened to run that way — which is §1's key inverted, silently, on a pair it
        does not tie.

        Driven at a far-future instant rather than a 2026 one because that is where the
        collision is reachable at all; the ids are chosen so the wrong answer and the
        right one differ.
        """
        far = datetime(2263, 1, 1, tzinfo=UTC)
        await store.save_goal(_goal("a-earlier"))
        await store.save_goal(_goal("z-later"))
        await store.engage_goal("a-earlier", at=far, conversation_id="c1", expected_version=0)
        await store.engage_goal(
            "z-later",
            at=far + timedelta(microseconds=1),
            conversation_id="c1",
            expected_version=0,
        )

        page = await store.candidates_for("c1", limit=MAX_ASSOCIATION_CANDIDATES)

        assert [one.id for one in page.goals] == ["z-later", "a-earlier"], (
            "the later instant leads; the id decides nothing here because this is no tie"
        )

    async def test_goals_engaged_in_the_same_instant_are_ordered_by_id_ascending(
        self, store: PlanStore
    ) -> None:
        """§1: and where the instants *are* equal, the id is what decides.

        "Two goals engaged in the same instant is reachable — a clock with millisecond
        resolution and a turn that engages two goals is not, but a migrated pair
        carrying no instant at all is — so the order is stated rather than left to a
        store's row order." This is the other half of the case above: the tie-break
        exists and applies exactly here.
        """
        same = datetime(2026, 5, 1, tzinfo=UTC)
        for name in ("g-zulu", "g-alpha"):
            await store.save_goal(_goal(name))
            await store.engage_goal(name, at=same, conversation_id="c1", expected_version=0)

        page = await store.candidates_for("c1", limit=MAX_ASSOCIATION_CANDIDATES)

        assert [one.id for one in page.goals] == ["g-alpha", "g-zulu"]

    async def test_a_limit_above_the_cap_is_held_to_the_cap(self, store: PlanStore) -> None:
        """§2: the ceiling is fixed and a caller asking for more gets it, not a raise.

        "Truncated to ``MAX_ASSOCIATION_CANDIDATES``, and carrying the count of goals
        the truncation dropped" — the cap is the rule and ``limit`` is the caller's
        narrower request, so a larger one is held down rather than refused. What it must
        **not** do is hand the type more than it admits: that surfaces as a raw
        ``ValidationError`` escaping the store, which is neither this subsystem's error
        class nor an answer a caller can act on.

        ``elided`` is counted against what was actually returned, so it stays the true
        remainder whichever of the two bounds applied.
        """
        for index in range(1, MAX_ASSOCIATION_CANDIDATES + 3):
            await store.save_goal(_goal(f"g{index:02d}"))

        page = await store.candidates_for("c1", limit=MAX_ASSOCIATION_CANDIDATES + 5)

        assert len(page.goals) == MAX_ASSOCIATION_CANDIDATES
        assert page.elided == 2, "the true remainder against the bound that applied"

    async def test_a_candidate_set_is_read_with_a_positive_limit(self, store: PlanStore) -> None:
        """§9: ``limit`` is what the caller truncates to, and zero truncates to nothing.

        A store that answered an empty page for ``limit=0`` would report every goal as
        elided, which is a disclosure §2 keys the reply on — so the malformed argument
        is refused rather than answered.
        """
        await store.save_goal(_goal())
        for limit in (0, -1):
            with pytest.raises(PlanningError):
                await store.candidates_for("c1", limit=limit)

    # --- ADR-0250 §§8-12: the goal's one clarification ---------------------

    async def test_a_question_is_written_read_back_and_enumerated(self, store: PlanStore) -> None:
        """§9: ``record_question``, ``get_question``, ``open_question`` and the listing.

        ``outstanding_questions`` "takes no view of the clock": an expired question is
        still ``OPEN`` until something settles it, which is ``ParkedReads.outstanding``'s
        own division — "a store that read one would be deciding a lifetime the engine
        owns".
        """
        await _goal_with_attempt(store)

        assert await store.open_question("g1") is None
        assert await store.outstanding_questions() == ()

        assert await store.record_question(_question()) is True

        held = await store.get_question("q1")
        assert held is not None
        assert held.disposition is GoalQuestionDisposition.OPEN
        assert (held.text, held.about) == ("which campsite?", "the usual campsite")
        assert await store.open_question("g1") == held
        assert await store.outstanding_questions() == (held,)
        assert await store.get_question("missing") is None
        assert await store.open_question("missing") is None

    async def test_a_goal_holds_at_most_one_open_question(self, store: PlanStore) -> None:
        """§8, §20 arm 19's first pair: the gate is the store's, not a caller's.

        "Two ``record_question`` calls on one goal: one succeeds and one answers
        ``False``, with no second row." The restriction is kept for a **correctness**
        reason rather than a storage one: "two outstanding questions about one
        objective have no order and answering either changes what the other means".

        **It is per goal and never per conversation**: a conversation may hold any
        number of paused goals, each with its own question — which the second half of
        this case is what pins.
        """
        await _goal_with_attempt(store)
        await _goal_with_attempt(store, goal_id="g2", attempt_id="a2")

        assert await store.record_question(_question()) is True
        assert await store.record_question(_question(question_id="q2")) is False

        assert await store.get_question("q2") is None, "no second row"
        assert await store.outstanding_questions() == (await store.open_question("g1"),)

        assert (
            await store.record_question(_question(question_id="q3", goal_id="g2", attempt_id="a2"))
            is True
        ), "per goal and never per conversation (ADR-0250 §8)"

    async def test_two_questions_dispatched_together_leave_one_loser(
        self, store: PlanStore
    ) -> None:
        """§9: "the read of the existing question and the write are **one indivisible
        step**", over calls that are actually in flight together.

        The sequential arm above would pass an implementation that read before a
        suspension and wrote after it without re-reading — which is exactly the
        interleaving two engines over one data directory produce.
        """
        await _goal_with_attempt(store)

        settled = await asyncio.gather(
            *(store.record_question(_question(question_id=name)) for name in ("q1", "q2")),
            return_exceptions=True,
        )

        assert sorted(one for one in settled if isinstance(one, bool)) == [False, True]
        rows = [name for name in ("q1", "q2") if await store.get_question(name) is not None]
        assert len(rows) == 1, "one row, whichever caller won"

    async def test_settling_clears_the_content_in_the_same_step(self, store: PlanStore) -> None:
        """§8, §9: the disposition moves and the content goes, indivisibly.

        "A settled question keeps its facts and loses its content", and ``goal_id``
        **survives settlement** so that a late answer still reaches the goal (§11).
        There is no intermediate state in which a terminal question still carries its
        text: the type refuses one.
        """
        await _goal_with_attempt(store)
        await store.record_question(_question())

        assert (
            await store.settle_question(
                "q1", disposition=GoalQuestionDisposition.ANSWERED, at=_LATER_ENGAGED
            )
            is True
        )

        settled = await store.get_question("q1")
        assert settled is not None
        assert settled.disposition is GoalQuestionDisposition.ANSWERED
        assert (settled.text, settled.about) == (None, None)
        assert settled.settled_at == _LATER_ENGAGED
        assert (settled.goal_id, settled.attempt_id) == ("g1", "a1")
        assert await store.open_question("g1") is None, "and the goal's slot is free"
        assert await store.outstanding_questions() == ()

    async def test_a_settle_that_lost_the_race_changes_nothing(self, store: PlanStore) -> None:
        """§9, §20 arm 19's second pair: the resolve-once gate.

        "Two ``settle_question`` calls on one question: one answers ``True`` and one
        ``False``, with the content cleared exactly once." A caller that lost "records
        nothing, revises nothing and reports the settled state", which is ADR-0244 §3's
        gate at the seam a goal has instead of a decision.
        """
        await _goal_with_attempt(store)
        await store.record_question(_question())

        settled = await asyncio.gather(
            *(
                store.settle_question("q1", disposition=disposition, at=_LATER_ENGAGED)
                for disposition in (
                    GoalQuestionDisposition.ANSWERED,
                    GoalQuestionDisposition.WITHDRAWN,
                )
            ),
            return_exceptions=True,
        )

        assert sorted(one for one in settled if isinstance(one, bool)) == [False, True]
        held = await store.get_question("q1")
        assert held is not None
        assert held.disposition is not GoalQuestionDisposition.OPEN
        assert (held.text, held.about) == (None, None)

    async def test_settling_an_already_terminal_or_unknown_question_answers_false(
        self, store: PlanStore
    ) -> None:
        """§9: "``settle_question`` on an already-terminal question answers ``False``
        and changes nothing", and one naming no question does the same.
        """
        await _goal_with_attempt(store)
        await store.record_question(_question())
        await store.settle_question(
            "q1", disposition=GoalQuestionDisposition.WITHDRAWN, at=_LATER_ENGAGED
        )
        before = await store.get_question("q1")

        assert (
            await store.settle_question(
                "q1", disposition=GoalQuestionDisposition.ANSWERED, at=_ENGAGED_AT
            )
            is False
        )
        assert (
            await store.settle_question(
                "missing", disposition=GoalQuestionDisposition.ANSWERED, at=_ENGAGED_AT
            )
            is False
        )
        assert await store.get_question("q1") == before, "and changes nothing"

    async def test_settling_to_open_settles_nothing_and_is_refused(self, store: PlanStore) -> None:
        """§9, §12: "no terminal disposition is inferred from silence", and ``OPEN``
        is not a terminal one.

        A malformed command rather than a lost race, so it is refused rather than
        answered ``False`` — which is what keeps ``False`` meaning "another caller
        moved it".
        """
        await _goal_with_attempt(store)
        await store.record_question(_question())

        with pytest.raises(PlanningError):
            await store.settle_question(
                "q1", disposition=GoalQuestionDisposition.OPEN, at=_LATER_ENGAGED
            )

        held = await store.get_question("q1")
        assert held is not None
        assert held.disposition is GoalQuestionDisposition.OPEN

    @pytest.mark.parametrize(
        "disposition",
        [
            GoalQuestionDisposition.ANSWERED,
            GoalQuestionDisposition.WITHDRAWN,
            GoalQuestionDisposition.EXPIRED,
            GoalQuestionDisposition.SUPERSEDED,
        ],
    )
    async def test_record_question_refuses_a_question_that_is_already_terminal(
        self, store: PlanStore, disposition: GoalQuestionDisposition
    ) -> None:
        """§9: this member "writes an ``OPEN`` question", and that is the whole of it.

        The type admits both shapes and has to — a settled question is read back,
        exported and returned by ``get_question`` — so the state it does not close is a
        **caller** handing a terminal record here. Writing one would answer ``True``
        while ``open_question`` answered ``None`` for the same goal: a record with a
        ``settled_at`` nothing settled, occupying no slot, reported as a question that
        was opened.

        §12 is the same rule read from the other side — "**no terminal disposition is
        inferred from silence**" — because a disposition is written by the act that
        reaches it, and ``settle_question`` is the only act that reaches a terminal one.
        All four are driven, because they are four distinct acts and "no implementation
        treats any as a weaker form of another".
        """
        await _goal_with_attempt(store)
        already = _question().model_copy(
            update={
                "disposition": disposition,
                "settled_at": _LATER_ENGAGED,
                "text": None,
                "about": None,
            }
        )

        with pytest.raises(PlanningError, match="record_question writes an OPEN question"):
            await store.record_question(already)

        assert await store.get_question("q1") is None, "and the refusal left no record"
        assert await store.open_question("g1") is None
        assert await store.outstanding_questions() == ()
        assert await store.record_question(_question()) is True, "the slot is still free"

    async def test_a_question_names_an_attempt_of_its_own_goal(self, store: PlanStore) -> None:
        """§9: the closure kept at write time, over a reference that can outlive it.

        ``goal_id`` and ``attempt_id`` are both references ADR-0014 §5 requires to
        resolve within the same export, which ADR-0250 §9 extends to ``question_id``.
        An attempt belonging to **another** goal resolves at the write and stops
        resolving at the first ``delete_goal``: that call cascades one goal's attempts
        and its questions together, so a question bound across the two survives the
        attempt it names and makes the next ``export`` unvalidatable — the precise
        failure :meth:`commit_attempt` already confines its own references to prevent.

        Asserted **through** the deletion rather than at the refusal alone, because the
        refusal is only worth having for what it stops happening later.
        """
        await _goal_with_attempt(store)
        await _goal_with_attempt(store, goal_id="g2", attempt_id="a2")

        with pytest.raises(PlanningError, match="its own goal holds"):
            await store.record_question(_question(goal_id="g2", attempt_id="a1"))

        assert await store.get_question("q1") is None
        assert await store.record_question(_question(goal_id="g2", attempt_id="a2")) is True
        assert (await store.delete_goal("g1")).deleted
        export = await store.export()
        assert {one.attempt_id for one in export.questions} <= {one.id for one in export.attempts}

    async def test_a_question_needs_its_goal_and_its_attempt_to_exist(
        self, store: PlanStore
    ) -> None:
        """§9: a dangling reference is refused at the write, not repaired at the read.

        ADR-0014 §5's closure promise kept at write time, which is the division
        ``save_plan`` already records for ``supersedes`` — and what makes
        ``PlanExport``'s extension of that rule to ``question_id`` hold across a
        deletion.
        """
        await _goal_with_attempt(store)

        with pytest.raises(PlanningError):
            await store.record_question(_question(question_id="q2", goal_id="missing"))
        with pytest.raises(PlanningError):
            await store.record_question(_question(question_id="q3", attempt_id="missing"))

        await store.record_question(_question())
        with pytest.raises(PlanningError):
            await store.record_question(_question())

    async def test_delete_goal_reaches_its_questions_open_and_terminal_alike(
        self, store: PlanStore
    ) -> None:
        """§9, §20 arm 28: the cascade reaches questions, and an open one does not block.

        "An open question does not block a deletion, on ADR-0073 §5's ruling that *the
        store deletes what it is told to delete*." ``GoalDeletion`` reports them
        exactly as ADR-0249 §12 has it report attempts — which is to say the record
        carries no count for either, so what is asserted is the rows' absence.
        """
        await _goal_with_attempt(store)
        await _goal_with_attempt(store, goal_id="g2", attempt_id="a2")
        await store.record_question(_question())
        await store.settle_question(
            "q1", disposition=GoalQuestionDisposition.EXPIRED, at=_LATER_ENGAGED
        )
        await store.record_question(_question(question_id="q2"))
        await store.record_question(_question(question_id="q3", goal_id="g2", attempt_id="a2"))

        removal = await store.delete_goal("g1")

        assert removal.deleted, "an open question does not block a deletion"
        assert await store.get_question("q1") is None, "the terminal one went too"
        assert await store.get_question("q2") is None
        assert await store.get_question("q3") is not None, "and another goal's did not"

    async def test_clear_removes_questions_too(self, store: PlanStore) -> None:
        """§9: a bulk erase reaches what a goal-scoped one would."""
        await _goal_with_attempt(store)
        await store.record_question(_question())

        assert await store.clear() >= 1
        assert await store.get_question("q1") is None
        assert await store.outstanding_questions() == ()

    async def test_the_export_carries_questions_and_closes_over_them(
        self, store: PlanStore
    ) -> None:
        """§9, §20 arm 27: the document gains ``questions`` and the closure reaches them.

        ADR-0014 §5's closure rule **extends** to ``question_id`` rather than changing:
        a question names a goal and an attempt, and both survive its settlement, so
        both must resolve within the same document. **A settled question exports with
        its content already absent**, which is §8's retention rule and not an omission
        from the export — so the whole document is the proof that the content is gone.
        """
        await _goal_with_attempt(store)
        await store.record_question(_question())
        await store.record_question(_question(question_id="q2"))  # refused: one open per goal
        await store.settle_question(
            "q1", disposition=GoalQuestionDisposition.SUPERSEDED, at=_LATER_ENGAGED
        )
        await store.record_question(_question(question_id="q3"))

        export = await store.export()

        assert {one.id for one in export.questions} == {"q1", "q3"}
        by_id = {one.id: one for one in export.questions}
        assert (by_id["q1"].text, by_id["q1"].about) == (None, None), "content already absent"
        assert by_id["q1"].goal_id == "g1", "and the facts it closes over survive"
        assert by_id["q3"].text == "which campsite?"
        assert {one.goal_id for one in export.questions} <= {one.id for one in export.goals}
        assert {one.attempt_id for one in export.questions} <= {one.id for one in export.attempts}

    async def test_delete_goal_cascades_to_attempts(self, store: PlanStore) -> None:
        """§16 arm 12: the cascade reaches attempts, and a live attempt blocks nothing.

        ADR-0014 §5's live-step refusal is unchanged — it keys on a ``RUNNING`` step,
        not on an attempt's state — so an attempt still ``RUNNING`` does not block a
        deletion no execution blocks.
        """
        await store.save_goal(_goal())
        await store.open_attempt(_attempt())
        await store.save_plan(_plan())

        deletion = await store.delete_goal("g1")

        assert deletion.deleted
        assert await store.attempts_of("g1") == ()
        assert await store.get_attempt("a1") is None

    async def test_clear_removes_attempts_too(self, store: PlanStore) -> None:
        await store.save_goal(_goal())
        await store.open_attempt(_attempt())
        assert await store.clear() >= 2
        assert await store.get_attempt("a1") is None

    async def test_the_export_carries_attempts_and_closes_over_them(self, store: PlanStore) -> None:
        """§16 arm 11: the document carries the attempt and its references resolve."""
        await store.save_goal(_goal())
        await store.save_plan(_plan())
        await store.open_attempt(_attempt())
        await store.commit_attempt(
            AttemptTransition(attempt_id="a1", expected_version=0, add_plan_id="p1")
        )

        export = await store.export()

        assert export.schema_version == 13
        assert [one.id for one in export.attempts] == ["a1"]
        assert export.attempts[0].plan_ids == ("p1",)

    # --- evidence: ADR-0252 §12's three members and §13's bound --------------
    # §12 obliges this suite to carry all four obligations in the change that adds
    # them: "a conformance suite exercising one implementation would be a suite that
    # lets the other disagree". The predicates of §§6-8 are **not** here — §12 puts
    # them in `orchestration` and the store "applies the marks it is given and
    # evaluates neither predicate" — so what these arms pin is the store's half:
    # the refusals, the indivisibility, the order, the bound and the cascade.

    async def test_a_row_is_written_and_read_back_by_id(self, store: PlanStore) -> None:
        """ADR-0252 §18 arm 26: the row names its attempt and reads back whole.

        "The row names the attempt that recorded it on ``attempt_id``, and is read back
        by ``get_evidence`` by ``id``." A row that came back missing a field would be a
        store that had quietly decided which of §1's values it keeps.
        """
        await _goal_with_attempt(store)
        written = _evidence()

        assert await store.record_evidence(written) == "ev1"

        stored = await store.get_evidence("ev1")
        assert stored == written
        assert stored is not None
        assert stored.attempt_id == "a1"
        assert stored.standing is EvidenceStanding.STANDING
        assert await store.get_evidence("nope") is None

    async def test_record_evidence_refuses_an_id_it_already_holds(self, store: PlanStore) -> None:
        """§12: it "refuses a row whose ``id`` the store already holds".

        No member replaces a stored row, so a second write under one id would be the
        upsert §12 declines to offer — and the first row's applicabilities, instants and
        verdict would be gone with no record that they ever stood.
        """
        await _goal_with_evidence(store)

        with pytest.raises(PlanningError):
            await store.record_evidence(_evidence("ev1", supported=()))

        stored = await store.get_evidence("ev1")
        assert stored is not None
        assert stored.supported == (_REGION,), "the held row is untouched"

    async def test_record_evidence_refuses_a_row_that_does_not_revalidate(
        self, store: PlanStore
    ) -> None:
        """A caller can reach past a frozen model's validators, and the store may not.

        ADR-0023 §2: "``model_copy(update=...)`` skips validators (a pydantic property no
        type can close), so the invariant holds *at the validation boundary*, and **a
        write that reaches past it must re-validate**". The row built here is the shape
        ADR-0252 §1's fourth axis says is **not constructible** — ``SUPERSEDED`` with no
        ``superseded_by`` — and the axis exists so that "a row that says it was displaced
        without saying by what" cannot be stored, which is the whole of what makes
        correction 1 auditable.

        In the shared suite because the alternative is two conforming stores that admit
        different rows: §12's own "a conformance suite exercising one implementation
        would be a suite that lets the other disagree".
        """
        await _goal_with_attempt(store)
        reaching_past = _evidence().model_copy(update={"standing": EvidenceStanding.SUPERSEDED})

        with pytest.raises(PlanningError):
            await store.record_evidence(reaching_past)

        assert await store.get_evidence("ev1") is None
        assert await store.evidence_of("g1") == EvidenceHistory(goal_id="g1")

    async def test_record_evidence_refuses_a_goal_the_store_does_not_hold(
        self, store: PlanStore
    ) -> None:
        """§12: it refuses "a row whose ``goal_id`` the store does not hold".

        With the error class an unknown goal already raises, so a caller handling one
        handles both.
        """
        with pytest.raises(PlanningError):
            await store.record_evidence(_evidence(goal_id="ghost"))

    async def test_evidence_of_returns_a_total_order_and_a_count(self, store: PlanStore) -> None:
        """§12: ``read_at`` oldest first, **ties broken by ``id`` ascending** (arm 39).

        "Two rows sharing a ``read_at`` to the microsecond are returned by
        ``evidence_of`` in ``id`` order by both conforming implementations." An order
        stated on the instant alone would leave two stores free to return them either
        way round, which makes ADR-0252 §10's ``E`` label space differ between them and
        makes §13's elision drop different rows — so the tie-break is a contract and not
        a convenience.

        The rows are written **newest first** here, so an implementation that returned
        insertion order fails rather than passing by accident.
        """
        await _goal_with_attempt(store)
        later = _WHEN + timedelta(hours=1)
        for row in (
            _evidence("ev9", read_at=later),
            _evidence("ev3", read_at=_WHEN),
            _evidence("ev1", read_at=_WHEN),
        ):
            await store.record_evidence(row)

        history = await store.evidence_of("g1")

        assert [row.id for row in history.rows] == ["ev1", "ev3", "ev9"]
        assert history.goal_id == "g1"
        assert history.elided == 0

    async def test_evidence_of_an_unheld_goal_is_an_empty_history(self, store: PlanStore) -> None:
        """A lookup, not a fault: an absent goal reads as a history with nothing in it.

        ``open_question``'s own posture — "an absent goal is not a fault to raise on a
        read that is already a lookup" — and the zero count is a true statement about a
        goal that has never dropped a row.
        """
        history = await store.evidence_of("ghost")

        assert history == EvidenceHistory(goal_id="ghost")

    async def test_a_refresh_marks_the_row_it_displaces_in_the_same_write(
        self, store: PlanStore
    ) -> None:
        """§8, §12 and arm 16: the append and the marks land together.

        "A row that refreshes an earlier row supersedes it: the earlier row's
        ``standing`` becomes ``SUPERSEDED`` and its ``superseded_by`` names ``L``, **in
        the same indivisible write that records ``L``**." Which rows a new row refreshes
        is ``orchestration``'s six-limb test (§8) and not the store's — the store applies
        the set it is given (§12) — so this arm hands it one.

        **The mark and its argument travel together or the value does not construct**
        (§1), so a store that moved the standing and left ``superseded_by`` absent could
        not have written the row at all.
        """
        await _goal_with_evidence(store)

        await store.record_evidence(
            _evidence("ev2", read_at=_WHEN + timedelta(hours=1)), supersedes=("ev1",)
        )

        displaced = await store.get_evidence("ev1")
        assert displaced is not None
        assert displaced.standing is EvidenceStanding.SUPERSEDED
        assert displaced.superseded_by == "ev2"
        assert displaced.inapplicable_at_revision is None
        fresh = await store.get_evidence("ev2")
        assert fresh is not None
        assert fresh.standing is EvidenceStanding.STANDING

    async def test_a_supersedes_given_as_a_bare_string_is_refused(self, store: PlanStore) -> None:
        """``str`` satisfies ``Sequence[str]``, and its characters are not the ids (§12).

        ``tuple("ev1")`` is ``("e", "v", "1")``. A store that snapshotted the argument
        without checking its shape would irreversibly supersede the three single-
        character rows this arm stands up — leaving ``ev1``, the row the caller actually
        named, **STANDING** — and would answer with a new row's id as though the refresh
        had landed. §12 obliges a store to mark the rows the caller named, and marking
        three others while reporting success is worse than refusing: the history would
        then hold a retirement nothing explains, which is exactly what ADR-0252 §1's
        fourth axis exists to make impossible.

        This is the same malformed-container failure
        ``test_a_revision_whose_invalidates_is_not_a_tuple_is_refused`` drives one level
        in, on a field rather than a parameter. A parameter carries no validator at all,
        so nothing but the store checks it.
        """
        await _goal_with_attempt(store)
        for index, row_id in enumerate(("e", "v", "1", "ev1")):
            await store.record_evidence(_evidence(row_id, read_at=_WHEN + timedelta(minutes=index)))

        with pytest.raises(PlanningError):
            await store.record_evidence(
                _evidence("ev-new", read_at=_WHEN + timedelta(hours=1)), supersedes="ev1"
            )

        for row_id in ("e", "v", "1", "ev1"):
            untouched = await store.get_evidence(row_id)
            assert untouched is not None
            assert untouched.standing is EvidenceStanding.STANDING, (
                f"{row_id} was never named and must not be marked"
            )
        assert await store.get_evidence("ev-new") is None, "and the append did not land"

    @pytest.mark.parametrize(
        "malformed",
        [7, {"ev1": True}, ("",), (7,)],
        ids=["not-a-container", "a-mapping", "a-blank-id", "an-id-that-is-not-a-string"],
    )
    async def test_a_supersedes_that_is_not_a_container_of_ids_is_refused(
        self, store: PlanStore, malformed: object
    ) -> None:
        """The parameter is checked, not trusted, and the whole call is refused (§12).

        ``Sequence[str]`` is an annotation and nothing enforces it at the call, so what
        arrives can be any object at all. Each of these would fail somewhere deeper —
        a mapping iterates its keys, an ``int`` is not iterable, a blank id names no row
        — and "somewhere deeper" is after the append in an implementation that checked
        late, which is the state §12's indivisibility rules out. The refusal is a
        ``PlanningError``, the class every other refusal on this member raises, rather
        than whatever the container happened to raise on its own.
        """
        await _goal_with_evidence(store)

        with pytest.raises(PlanningError):
            await store.record_evidence(
                _evidence("ev-new", read_at=_WHEN + timedelta(hours=1)),
                supersedes=malformed,  # type: ignore[arg-type]
            )

        assert await store.get_evidence("ev-new") is None, "the append did not land"
        standing = await store.get_evidence("ev1")
        assert standing is not None
        assert standing.standing is EvidenceStanding.STANDING

    async def test_record_evidence_reads_its_supersedes_once(self, store: PlanStore) -> None:
        """The set is observed at one instant, however the caller spelled it (§12).

        The ``supersedes`` counterpart of
        ``test_a_revision_reads_its_invalidation_set_once``: a one-shot iterator is what
        separates a store that traverses the argument once from one that traverses it
        twice. A store that drained it on the refusal pass would find it **empty** on
        the marking pass — the row appended, the call reporting success, and the rows it
        was told to retire still ``STANDING``. That is ``core.protocols``' second
        standing obligation (ADR-0065 §1) read over this parameter.
        """
        await _goal_with_evidence(store, rows=2)
        one_shot = iter(("ev1", "ev2"))

        await store.record_evidence(
            _evidence("ev3", read_at=_WHEN + timedelta(hours=1)),
            supersedes=one_shot,  # type: ignore[arg-type]
        )

        for row_id in ("ev1", "ev2"):
            marked = await store.get_evidence(row_id)
            assert marked is not None
            assert marked.standing is EvidenceStanding.SUPERSEDED, (
                f"{row_id} was named and must be marked, whatever the set's spelling"
            )
            assert marked.superseded_by == "ev3"

    @pytest.mark.parametrize(
        ("named", "arrange"),
        [
            pytest.param("ev-other", "another goal's", id="not-this-goals"),
            pytest.param("nope", "no row at all", id="no-such-row"),
            pytest.param("ev1", "already marked", id="not-standing"),
            pytest.param("ev2", "the row being written", id="the-row-being-written"),
        ],
    )
    async def test_record_evidence_refuses_a_supersedes_it_cannot_apply(
        self, store: PlanStore, named: str, arrange: str
    ) -> None:
        """§12's three refusals, and the whole call is refused rather than half applied.

        "Refusing the whole call where any named row is not this goal's, is not
        ``STANDING``, or is the row being written" — so a caller never has to ask which
        of its marks landed. A row this store does not hold at all is "not this goal's",
        which is why it is one case rather than a fourth.

        The last case is what §12's own sentence rules out: a row is validated against
        the history **as it stood before the call**, so naming the row being written
        names nothing.
        """
        assert arrange  # the parametrisation's own label, carried for the report
        await _goal_with_evidence(store)
        await _goal_with_attempt(store, goal_id="g2", attempt_id="a2")
        await store.record_evidence(_evidence("ev-other", goal_id="g2"))
        if named == "ev1":
            await store.record_evidence(
                _evidence("ev-mark", read_at=_WHEN + timedelta(hours=1)), supersedes=("ev1",)
            )

        with pytest.raises(PlanningError):
            await store.record_evidence(
                _evidence("ev2", read_at=_WHEN + timedelta(hours=2)), supersedes=(named,)
            )

        assert await store.get_evidence("ev2") is None, "the whole call is refused"
        other = await store.get_evidence("ev-other")
        assert other is not None
        assert other.standing is EvidenceStanding.STANDING

    async def test_a_marked_row_is_never_marked_again(self, store: PlanStore) -> None:
        """§8 and §9 and arm 15: the mark is terminal and is never un-marked.

        "A row that is ``SUPERSEDED`` is never returned to ``STANDING``, by a later
        revision, by a later refresh, by the deletion of the row that displaced it, or
        by any other route." The store's half of that is refusing to mark a row that is
        already marked — in **either** direction, so a superseded row cannot be
        invalidated and an invalidated one cannot be superseded.
        """
        await _goal_with_evidence(store, rows=2)
        await store.record_evidence(
            _evidence("ev3", read_at=_WHEN + timedelta(hours=1)), supersedes=("ev1",)
        )
        await store.record_interpretation(
            GoalRevision(
                goal_id="g1", interpretation=_revision(2), expected_version=0, invalidates=("ev2",)
            )
        )

        with pytest.raises(PlanningError):
            await store.record_evidence(
                _evidence("ev4", read_at=_WHEN + timedelta(hours=2)), supersedes=("ev1",)
            )
        with pytest.raises(PlanningError):
            await store.record_interpretation(
                GoalRevision(
                    goal_id="g1",
                    interpretation=_revision(3),
                    expected_version=1,
                    invalidates=("ev2",),
                )
            )

        first = await store.get_evidence("ev1")
        second = await store.get_evidence("ev2")
        assert first is not None
        assert second is not None
        assert (first.standing, first.superseded_by) == (EvidenceStanding.SUPERSEDED, "ev3")
        assert (second.standing, second.inapplicable_at_revision) == (
            EvidenceStanding.INAPPLICABLE,
            2,
        )

    @pytest.mark.parametrize("mark", ["supersede", "invalidate"])
    async def test_a_mark_changes_exactly_one_field_and_its_argument(
        self, store: PlanStore, mark: str
    ) -> None:
        """§9: "invalidation is a marking and never a deletion … exactly one field changes".

        "The row is kept with its applicabilities, its instants, its verdict and its
        references intact; it is still exported, still reachable through
        ``get_evidence`` and ``evidence_of``." §8's supersession is the same move with
        the other argument. A store that rebuilt the row, dropped its regions or
        restamped an instant while marking it would be editing the audit trail, so the
        arm compares every other field against what was written.
        """
        await _goal_with_evidence(store)
        written = await store.get_evidence("ev1")
        assert written is not None

        if mark == "supersede":
            await store.record_evidence(
                _evidence("ev2", read_at=_WHEN + timedelta(hours=1)), supersedes=("ev1",)
            )
        else:
            await store.record_interpretation(
                GoalRevision(
                    goal_id="g1",
                    interpretation=_revision(2),
                    expected_version=0,
                    invalidates=("ev1",),
                )
            )

        marked = await store.get_evidence("ev1")
        assert marked is not None
        moved = {"standing", "superseded_by", "inapplicable_at_revision"}
        assert marked.model_dump(exclude=moved) == written.model_dump(exclude=moved)
        history = await store.evidence_of("g1")
        assert any(row.id == "ev1" for row in history.rows), "a mark is not a deletion"

    async def test_a_revision_applies_its_invalidations_in_the_same_step(
        self, store: PlanStore
    ) -> None:
        """§9, §12 and arm 16: the append, the version advance and the marks are one.

        "``GoalRevision`` carries the set, ``record_interpretation`` applies it, and
        there is **no second call and no window** in which a recorded revision stands
        beside evidence its own change invalidated." ``inapplicable_at_revision``
        carries "the ``revision`` that did it", which is the revision being appended.

        **Which rows a revision invalidates is not the store's to work out** (§9, §12):
        the predicate is keyed on ``supported`` and is ``orchestration``'s, so this arm
        hands the store a set.
        """
        await _goal_with_evidence(store, rows=2)

        goal = await store.record_interpretation(
            GoalRevision(
                goal_id="g1",
                interpretation=_revision(2),
                expected_version=0,
                invalidates=("ev1",),
            )
        )

        assert goal.version == 1
        assert goal.interpretation[-1].revision == 2
        marked = await store.get_evidence("ev1")
        assert marked is not None
        assert marked.standing is EvidenceStanding.INAPPLICABLE
        assert marked.inapplicable_at_revision == 2
        assert marked.superseded_by is None
        untouched = await store.get_evidence("ev2")
        assert untouched is not None
        assert untouched.standing is EvidenceStanding.STANDING, "every other row is untouched"

    async def test_a_revision_reads_its_invalidation_set_once(self, store: PlanStore) -> None:
        """The set is observed at one instant, however the caller spelled it (§12).

        ``invalidates`` is annotated a tuple, but ``model_copy(update=...)`` **skips
        validators** — ADR-0023 §2's premise, "a pydantic property no type can close" —
        so a caller can hand this member a one-shot iterator. A store that traversed it
        twice would drain it on the refusal pass and find it **empty** on the marking
        pass: the revision would be appended, the version would advance, and the rows
        the revision invalidated would still be ``STANDING``. That is precisely the
        window §12's indivisibility exists to close — *"there is no second call and no
        window in which a recorded revision stands beside evidence its own change
        invalidated"* — reopened not by a second call but by reading one argument twice
        (``core.protocols``' second standing obligation, ADR-0065 §1).

        The mark is what is asserted rather than the traversal, because the traversal is
        the implementation's: what a caller is owed is that the marks landed.
        """
        await _goal_with_evidence(store, rows=2)
        one_shot = iter(("ev1", "ev2"))
        revision = GoalRevision(
            goal_id="g1", interpretation=_revision(2), expected_version=0
        ).model_copy(update={"invalidates": one_shot})

        await store.record_interpretation(revision)

        for row_id in ("ev1", "ev2"):
            marked = await store.get_evidence(row_id)
            assert marked is not None
            assert marked.standing is EvidenceStanding.INAPPLICABLE, (
                f"{row_id} was named and must be marked, whatever the set's spelling"
            )
            assert marked.inapplicable_at_revision == 2

    @pytest.mark.parametrize(
        "malformed",
        ["ev1", 7, {"ev1": True}],
        ids=["a-string-whose-tuple-is-its-characters", "not-a-container", "a-mapping"],
    )
    async def test_a_revision_whose_invalidates_is_not_a_tuple_is_refused(
        self, store: PlanStore, malformed: object
    ) -> None:
        """A snapshot is not enough: the command itself has to revalidate (ADR-0023 §2).

        ``invalidates`` is annotated ``tuple[Identifier, ...]``, and
        ``model_copy(update=...)`` **skips validators**, so the field can hold anything.
        ``"ev1"`` is the case that shows why a ``tuple()`` snapshot does not close it:
        ``tuple("ev1")`` is ``("e", "v", "1")`` — three ids the caller never named, which
        a store would mark wherever they happen to exist while leaving ``ev1``
        **standing**. A revision that invalidated the wrong rows and said nothing is
        worse than one that refused.

        The goal is left untouched, because the refusal runs before the append: §12's
        indivisibility is a promise about a call that succeeds *and* about one that does
        not.
        """
        await _goal_with_evidence(store)
        revision = GoalRevision(
            goal_id="g1", interpretation=_revision(2), expected_version=0
        ).model_copy(update={"invalidates": malformed})

        with pytest.raises(PlanningError):
            await store.record_interpretation(revision)

        goal = await store.get_goal("g1")
        assert goal is not None
        assert goal.version == 0, "the append did not land"
        standing = await store.get_evidence("ev1")
        assert standing is not None
        assert standing.standing is EvidenceStanding.STANDING

    async def test_a_revision_naming_an_unmarkable_row_appends_nothing(
        self, store: PlanStore
    ) -> None:
        """§12: ``record_interpretation`` "refuses the whole call" the same way.

        A revision that cannot mark every row it named must not land its append either —
        otherwise the goal moves on while the evidence its own change invalidated stays
        ``STANDING``, which is exactly the window the atomicity exists to close.
        """
        await _goal_with_evidence(store)
        await _goal_with_attempt(store, goal_id="g2", attempt_id="a2")
        await store.record_evidence(_evidence("ev-other", goal_id="g2"))

        with pytest.raises(PlanningError):
            await store.record_interpretation(
                GoalRevision(
                    goal_id="g1",
                    interpretation=_revision(2),
                    expected_version=0,
                    invalidates=("ev-other",),
                )
            )

        goal = await store.get_goal("g1")
        assert goal is not None
        assert goal.version == 0, "the append did not land"
        assert len(goal.interpretation) == 1

    async def test_an_invalidation_does_not_rewrite_the_revision_that_grounds_on_it(
        self, store: PlanStore
    ) -> None:
        """ADR-0252 §10 and arm 17: an element grounded on a row survives the mark.

        "A ``GoalElement`` grounded on a row that is later marked ``INAPPLICABLE`` or
        ``SUPERSEDED`` is **not rewritten, not dropped, not re-grounded and not removed
        from the revision it sits in**, and no lane records a revision on account of a
        mark." The chain is append-only and a revision states what was understood **when
        it was recorded**; editing one to reflect a later mark would destroy exactly the
        audit it exists to be.
        """
        await _goal_with_evidence(store)
        grounded = _revision(2).model_copy(
            update={
                "conditions": (
                    GoalElement(
                        text="the forecast is settled",
                        ground=Ground.FROM_EVIDENCE,
                        evidence_row_id="ev1",
                    ),
                )
            }
        )
        await store.record_interpretation(
            GoalRevision(goal_id="g1", interpretation=grounded, expected_version=0)
        )

        await store.record_interpretation(
            GoalRevision(
                goal_id="g1",
                interpretation=_revision(3),
                expected_version=1,
                invalidates=("ev1",),
            )
        )

        goal = await store.get_goal("g1")
        assert goal is not None
        assert goal.interpretation[1].conditions[0].evidence_row_id == "ev1"
        assert goal.interpretation[1].conditions[0].ground is Ground.FROM_EVIDENCE

    async def test_the_bound_drops_the_oldest_row_and_discloses_it(self, store: PlanStore) -> None:
        """§13 and arm 20: the history is bounded, and the elision is never silent.

        "A goal whose history would exceed it drops its **oldest** row on the write that
        would exceed it", and ``EvidenceHistory.elided`` "carries how many rows this
        goal's history has dropped … it **never decreases**, and a write that drops *k*
        rows advances it by *k*". Silent truncation is not available, on ADR-0086 §4's
        ground.

        **The drop is by age and by nothing else** — the oldest row here is ``STANDING``
        and is dropped all the same, because "a rule that kept ``STANDING`` rows
        preferentially would make the history a curated selection rather than a record".
        """
        await _goal_with_attempt(store)
        for index in range(MAX_GOAL_EVIDENCE):
            await store.record_evidence(
                _evidence(f"ev{index:03d}", read_at=_WHEN + timedelta(minutes=index))
            )
        assert (await store.evidence_of("g1")).elided == 0

        await store.record_evidence(_evidence("ev-new", read_at=_WHEN + timedelta(days=1)))

        history = await store.evidence_of("g1")
        assert len(history.rows) == MAX_GOAL_EVIDENCE
        assert history.elided == 1
        assert await store.get_evidence("ev000") is None, "the oldest went"
        assert await store.get_evidence("ev-new") is not None
        assert history.rows[0].id == "ev001"

    async def test_the_write_never_elides_the_row_it_is_writing(self, store: PlanStore) -> None:
        """§12, §13 and arm 36: "a write never elides the row it is writing".

        "Whatever place §12's order gives it: the oldest **other** row is dropped
        instead", because "a store that discarded the row it had just been told to
        persist would return an id from ``record_evidence`` that resolves in nothing".
        The row written here is the **oldest** of the goal's history by ``read_at``, so
        an implementation that elided by age alone would drop it.
        """
        await _goal_with_attempt(store)
        for index in range(MAX_GOAL_EVIDENCE):
            await store.record_evidence(
                _evidence(f"ev{index:03d}", read_at=_WHEN + timedelta(days=1, minutes=index))
            )

        oldest = await store.record_evidence(_evidence("ev-old", read_at=_WHEN))

        assert await store.get_evidence(oldest) is not None, "the appended row is kept"
        history = await store.evidence_of("g1")
        assert history.elided == 1
        assert history.rows[0].id == "ev-old"
        assert await store.get_evidence("ev000") is None, "the oldest *other* row went"

    async def test_a_full_history_refreshed_whole_still_writes_marks_and_elides(
        self, store: PlanStore
    ) -> None:
        """ADR-0252 §18 arm 40, which is the case that forced §12's two guarantees apart.

        "A goal holding ``MAX_GOAL_EVIDENCE`` standing rows with identical support and
        one shared effective instant, written to with a later answering row covering that
        support and naming all of them in ``supersedes``, **succeeds**." A rule
        protecting every row the call marks would leave the write with no eligible
        candidate — "retaining all of them breaks the bound, dropping any of them breaks
        the protection, and refusing the write breaks ``record_evidence``'s own
        contract" — so the protection is scoped to the **appended** row and the elision
        then runs over the marked history by age alone.
        """
        await _goal_with_attempt(store)
        held = [f"ev{index:03d}" for index in range(MAX_GOAL_EVIDENCE)]
        for row_id in held:
            await store.record_evidence(_evidence(row_id, read_at=_WHEN))

        await store.record_evidence(
            _evidence("ev-new", read_at=_WHEN + timedelta(hours=1)), supersedes=tuple(held)
        )

        history = await store.evidence_of("g1")
        assert len(history.rows) == MAX_GOAL_EVIDENCE
        assert history.elided == 1
        assert history.rows[-1].id == "ev-new"
        assert [row.standing for row in history.rows[:-1]] == [EvidenceStanding.SUPERSEDED] * (
            MAX_GOAL_EVIDENCE - 1
        )
        assert await store.get_evidence("ev000") is None, "a row this call marked was elided"

    async def test_a_superseded_by_may_name_a_row_the_bound_has_dropped(
        self, store: PlanStore
    ) -> None:
        """§12 and arm 36: the reference is "an identifier and not a resolution guarantee".

        §12's order is ``(read_at, id)`` and §8 limb 6 orders by the **effective
        instant**, which is ``as_of`` where a source declares one — so a row that
        superseded another can sort **before** it and be elided first. "The mark still
        states what it states, the loss is carried on ``EvidenceHistory.elided``, and no
        lane repairs it, back-fills it, un-marks the row, reorders retention to prevent
        it, or keeps a row alive because something names it."
        """
        await _goal_with_attempt(store)
        # The two orders come apart exactly here: `ev-fresh` was **read** first and is
        # therefore first in `(read_at, id)` order, but the source it read declares the
        # **later** instant — so it is the later row by §8 limb 6's effective instant
        # and legitimately supersedes `ev-old`.
        await store.record_evidence(
            _evidence("ev-old", read_at=_WHEN + timedelta(minutes=10), as_of=_WHEN)
        )
        await store.record_evidence(
            _evidence("ev-fresh", read_at=_WHEN, as_of=_WHEN + timedelta(minutes=5)),
            supersedes=("ev-old",),
        )
        for index in range(MAX_GOAL_EVIDENCE - 2):
            await store.record_evidence(
                _evidence(f"ev{index:03d}", read_at=_WHEN + timedelta(days=1, minutes=index))
            )
        assert (await store.evidence_of("g1")).elided == 0, "the bound is not yet reached"

        await store.record_evidence(_evidence("ev-last", read_at=_WHEN + timedelta(days=2)))

        assert await store.get_evidence("ev-fresh") is None, "the superseding row went first"
        survivor = await store.get_evidence("ev-old")
        assert survivor is not None
        assert survivor.standing is EvidenceStanding.SUPERSEDED
        assert survivor.superseded_by == "ev-fresh", "the mark is not repaired"
        assert (await store.evidence_of("g1")).elided == 1

    async def test_the_export_carries_one_history_per_goal_with_its_count(
        self, store: PlanStore
    ) -> None:
        """§13 and arm 22: export closure and disclosure.

        "An export carries exactly one ``EvidenceHistory`` per goal, each with its rows
        and its elision count." ADR-0004 §6's export right is what obliges the member —
        a goal's evidence is the user's data — and the count is what stops the document
        saying *this is the evidence* where the truth is *this is the evidence that was
        kept*. A goal that has recorded nothing carries an **empty** history rather than
        none, which is a true answer and not an omission.
        """
        await _goal_with_evidence(store, rows=2)
        await _goal_with_attempt(store, goal_id="g2", attempt_id="a2")

        export = await store.export()

        by_goal = {history.goal_id: history for history in export.evidence}
        assert set(by_goal) == {"g1", "g2"}
        assert [row.id for row in by_goal["g1"].rows] == ["ev1", "ev2"]
        assert by_goal["g1"].elided == 0
        assert by_goal["g2"] == EvidenceHistory(goal_id="g2")

    async def test_deleting_a_goal_removes_its_evidence_and_counts_it(
        self, store: PlanStore
    ) -> None:
        """§12 and arm 23: the cascade reaches evidence and reports what it removed.

        "``delete_goal``'s cascade reaches evidence, and ``GoalDeletion`` gains
        ``evidence_removed``" — ADR-0014 §5's "a goal the user deletes must not leave its
        plan history behind" **extended rather than re-promised**. "No row of any
        standing blocks a deletion", and the elision count goes with the goal, so a goal
        reopened under the same id does not inherit a predecessor's losses.
        """
        await _goal_with_attempt(store)
        for index in range(MAX_GOAL_EVIDENCE + 1):
            await store.record_evidence(
                _evidence(f"ev{index:03d}", read_at=_WHEN + timedelta(minutes=index))
            )
        await store.record_evidence(
            _evidence("ev-mark", read_at=_WHEN + timedelta(days=1)), supersedes=("ev001",)
        )
        assert (await store.evidence_of("g1")).elided == 2

        removal = await store.delete_goal("g1")

        assert removal.deleted
        assert removal.evidence_removed == MAX_GOAL_EVIDENCE
        assert await store.evidence_of("g1") == EvidenceHistory(goal_id="g1")
        assert await store.get_evidence("ev002") is None

    async def test_clearing_the_store_removes_every_row(self, store: PlanStore) -> None:
        """``clear`` is one of only three routes out of the store for a row (§12).

        The others are ``delete_goal`` and §13's elision: "no member deletes one row".
        """
        await _goal_with_evidence(store, rows=2)

        assert await store.clear() >= 2

        assert await store.evidence_of("g1") == EvidenceHistory(goal_id="g1")
        assert await store.get_evidence("ev1") is None

    # --- starting an execution ------------------------------------------

    async def test_execution_starts_derived_from_the_plan(self, store: PlanStore) -> None:
        state = await self._started(store, steps=2)
        assert state.plan_id == "p1"
        assert [step.step_id for step in state.steps] == ["s1", "s2"]
        assert all(step.status is StepStatus.PENDING for step in state.steps)
        assert state.version == 0

    # --- the transition graph -------------------------------------------

    async def test_claiming_a_step_advances_it(self, store: PlanStore) -> None:
        state = await self._started(store)
        updated = await store.commit_transition(_claim(state))
        step = updated.step("s1")
        assert step is not None
        assert step.status is StepStatus.RUNNING
        assert step.attempts == 1
        assert step.started_at is not None

    async def test_a_write_bumps_the_version(self, store: PlanStore) -> None:
        state = await self._started(store)
        updated = await store.commit_transition(_claim(state))
        assert updated.version == state.version + 1

    async def test_illegal_transition_is_rejected(self, store: PlanStore) -> None:
        """PENDING to SUCCEEDED skips the claim, so it must not be persistable."""
        state = await self._started(store)
        with pytest.raises(IllegalTransitionError):
            await store.commit_transition(
                StepTransition(
                    execution_id=state.id,
                    step_id="s1",
                    to_status=StepStatus.SUCCEEDED,
                    expected_version=state.version,
                )
            )

    async def test_running_without_authorisation_is_rejected(self, store: PlanStore) -> None:
        """ADR-0004 §7: nothing executes without a decision to point at."""
        state = await self._started(store)
        with pytest.raises(IllegalTransitionError):
            await store.commit_transition(
                StepTransition(
                    execution_id=state.id,
                    step_id="s1",
                    to_status=StepStatus.RUNNING,
                    expected_version=state.version,
                    bound_tool="smtp",
                    attempt_id="a1",
                )
            )

    async def test_approval_cannot_be_sought_without_a_tool_to_approve(
        self, store: PlanStore
    ) -> None:
        """Consent is to a specific action, not to an unspecified one."""
        state = await self._started(store)
        with pytest.raises(IllegalTransitionError):
            await store.commit_transition(
                StepTransition(
                    execution_id=state.id,
                    step_id="s1",
                    to_status=StepStatus.AWAITING_APPROVAL,
                    expected_version=state.version,
                )
            )

    async def test_a_never_queued_step_can_be_denied_in_one_transition(
        self, store: PlanStore
    ) -> None:
        """A policy refusing outright is a denial, though nobody was asked.

        ADR-0041 §1: the record is truthful because it names the decision that
        refused it, not because a confirmation was put to anyone.

        The version count is asserted, not incidental. A store that satisfied
        this request by durably writing `AWAITING_APPROVAL` and then `SKIPPED`
        would return an indistinguishable final state while reopening the very
        window ADR-0041 closes — a failure between the two writes strands the
        step (#257). One commit is the obligation; the disposition is not.
        """
        state = await self._started(store)
        before = state.version
        state = await store.commit_transition(
            StepTransition(
                execution_id=state.id,
                step_id="s1",
                to_status=StepStatus.SKIPPED,
                expected_version=state.version,
                skip_reason=SkipReason.APPROVAL_DENIED,
                approval_ref="perm-1",
            )
        )

        assert state.version == before + 1

        # Read back rather than trust the return value: a denial that is only
        # in the returned object is exactly the stranding this edge exists to
        # prevent, since a restart would resurrect the step as PENDING.
        stored = await store.get_execution(state.id)
        assert stored is not None
        assert stored.version == before + 1
        step = stored.step("s1")
        assert step is not None
        assert step.status is StepStatus.SKIPPED
        assert step.skip_reason is SkipReason.APPROVAL_DENIED
        assert step.approval_ref == "perm-1"

    async def test_a_queued_step_is_still_denied_by_a_human(self, store: PlanStore) -> None:
        """ADR-0041 widens the denial rule; it does not move it (§3).

        This is the genuine human-denied path — a confirmation was shown and
        answered no — and it stays legal. Without it the suite would admit a
        store that implements only the direct edge, leaving a real user denial
        with nowhere to go and the step awaiting approval forever.
        """
        state = await self._started(store)
        state = await store.commit_transition(
            StepTransition(
                execution_id=state.id,
                step_id="s1",
                to_status=StepStatus.AWAITING_APPROVAL,
                expected_version=state.version,
                bound_tool="smtp",
            )
        )
        state = await store.commit_transition(
            StepTransition(
                execution_id=state.id,
                step_id="s1",
                to_status=StepStatus.SKIPPED,
                expected_version=state.version,
                skip_reason=SkipReason.APPROVAL_DENIED,
                approval_ref="perm-denied",
            )
        )

        step = state.step("s1")
        assert step is not None
        assert step.status is StepStatus.SKIPPED
        assert step.skip_reason is SkipReason.APPROVAL_DENIED
        assert step.approval_ref == "perm-denied"

    async def test_a_pending_denial_must_point_at_its_decision(self, store: PlanStore) -> None:
        """The `approval_ref` is the whole guard on the direct edge (ADR-0041 §2).

        Without it, `APPROVAL_DENIED` would be assertable from the status every
        step starts in, with nothing behind it — the fabricated record the
        narrower rule was protecting against.
        """
        state = await self._started(store)
        with pytest.raises(IllegalTransitionError):
            await store.commit_transition(
                StepTransition(
                    execution_id=state.id,
                    step_id="s1",
                    to_status=StepStatus.SKIPPED,
                    expected_version=state.version,
                    skip_reason=SkipReason.APPROVAL_DENIED,
                )
            )

    async def test_a_denial_must_point_at_its_decision(self, store: PlanStore) -> None:
        state = await self._started(store)
        state = await store.commit_transition(
            StepTransition(
                execution_id=state.id,
                step_id="s1",
                to_status=StepStatus.AWAITING_APPROVAL,
                expected_version=state.version,
                bound_tool="smtp",
            )
        )
        with pytest.raises(IllegalTransitionError):
            await store.commit_transition(
                StepTransition(
                    execution_id=state.id,
                    step_id="s1",
                    to_status=StepStatus.SKIPPED,
                    expected_version=state.version,
                    skip_reason=SkipReason.APPROVAL_DENIED,
                )
            )

    async def test_an_approved_step_cannot_run_a_different_tool(self, store: PlanStore) -> None:
        """Approving "smtp" must not become permission to run something else.

        This is the authorisation-laundering path: without the check, a caller
        approves a benign tool and then claims the step with a destructive one,
        carrying the benign approval along as its justification.
        """
        state = await self._started(store)
        state = await store.commit_transition(
            StepTransition(
                execution_id=state.id,
                step_id="s1",
                to_status=StepStatus.AWAITING_APPROVAL,
                expected_version=state.version,
                bound_tool="smtp",
            )
        )
        with pytest.raises(IllegalTransitionError):
            await store.commit_transition(
                StepTransition(
                    execution_id=state.id,
                    step_id="s1",
                    to_status=StepStatus.RUNNING,
                    expected_version=state.version,
                    bound_tool="payments.delete_account",
                    approval_ref="perm-for-smtp",
                    attempt_id="a1",
                )
            )

    async def test_a_retry_cannot_swap_the_tool(self, store: PlanStore) -> None:
        """The same laundering, taken through the retry path instead."""
        state = await self._started(store)
        state = await store.commit_transition(_claim(state))
        state = await store.commit_transition(
            StepTransition(
                execution_id=state.id,
                step_id="s1",
                to_status=StepStatus.FAILED,
                expected_version=state.version,
                failure=StepFailure(message="boom"),
            )
        )
        with pytest.raises(IllegalTransitionError):
            await store.commit_transition(
                StepTransition(
                    execution_id=state.id,
                    step_id="s1",
                    to_status=StepStatus.RUNNING,
                    expected_version=state.version,
                    bound_tool="payments.delete_account",
                    attempt_id="a1",
                )
            )

    async def test_unknown_step_is_rejected(self, store: PlanStore) -> None:
        state = await self._started(store)
        with pytest.raises(PlanningError):
            await store.commit_transition(
                StepTransition(
                    execution_id=state.id,
                    step_id="ghost",
                    to_status=StepStatus.AWAITING_APPROVAL,
                    expected_version=state.version,
                )
            )

    async def test_a_full_run_reaches_succeeded_with_its_output(self, store: PlanStore) -> None:
        state = await self._started(store)
        state = await store.commit_transition(_claim(state))
        state = await store.commit_transition(
            StepTransition(
                execution_id=state.id,
                step_id="s1",
                to_status=StepStatus.SUCCEEDED,
                expected_version=state.version,
                output={"ref": "ABC"},
            )
        )
        step = state.step("s1")
        assert step is not None
        assert step.status is StepStatus.SUCCEEDED
        assert step.output == {"ref": "ABC"}
        assert step.finished_at is not None
        assert not state.is_active

    # --- compare-and-swap -----------------------------------------------

    async def test_a_stale_write_is_refused(self, store: PlanStore) -> None:
        """The race that would otherwise run a non-idempotent tool twice."""
        state = await self._started(store)
        first = _claim(state)
        second = _claim(state)  # computed against the same version

        await store.commit_transition(first)
        with pytest.raises(StaleExecutionError):
            await store.commit_transition(second)

    async def test_the_loser_of_a_race_did_not_change_anything(self, store: PlanStore) -> None:
        state = await self._started(store)
        await store.commit_transition(_claim(state))
        with pytest.raises(StaleExecutionError):
            await store.commit_transition(_claim(state))

        stored = await store.get_execution(state.id)
        assert stored is not None
        step = stored.step("s1")
        assert step is not None
        assert step.attempts == 1

    # --- retries ---------------------------------------------------------

    async def test_a_failed_step_can_be_retried(self, store: PlanStore) -> None:
        state = await self._started(store)
        state = await store.commit_transition(_claim(state))
        state = await store.commit_transition(
            StepTransition(
                execution_id=state.id,
                step_id="s1",
                to_status=StepStatus.FAILED,
                expected_version=state.version,
                failure=StepFailure(message="boom"),
            )
        )
        state = await store.commit_transition(_claim(state))
        step = state.step("s1")
        assert step is not None
        assert step.status is StepStatus.RUNNING
        assert step.attempts == 2
        assert step.failure is None, "a retry re-opens the step, clearing the last failure"

    async def test_retries_are_bounded(self, store: PlanStore) -> None:
        """The ceiling is deterministic code's to enforce (VISION §7)."""
        state = await self._started(store)
        for _ in range(3):
            state = await store.commit_transition(_claim(state))
            state = await store.commit_transition(
                StepTransition(
                    execution_id=state.id,
                    step_id="s1",
                    to_status=StepStatus.FAILED,
                    expected_version=state.version,
                    failure=StepFailure(message="boom"),
                )
            )
        with pytest.raises(RetriesExhaustedError):
            await store.commit_transition(_claim(state))

    # --- failure records survive the store (ADR-0039) ---------------------

    @pytest.mark.parametrize("to_status", [StepStatus.FAILED, StepStatus.INDETERMINATE])
    async def test_a_failure_status_transition_requires_a_failure(
        self, store: PlanStore, to_status: StepStatus
    ) -> None:
        """Required on both FAILED and INDETERMINATE (ADR-0039 §2), not just FAILED.

        A suite that pinned only ``FAILED`` would certify a store fed by a
        command shape that left ``INDETERMINATE`` — the #208 half — with no
        durable account of itself.
        """
        with pytest.raises(ValidationError, match="requires a failure"):
            StepTransition(
                execution_id="e1",
                step_id="s1",
                to_status=to_status,
                expected_version=0,
            )

    @pytest.mark.parametrize(
        "to_status",
        [StepStatus.RUNNING, StepStatus.AWAITING_APPROVAL, StepStatus.SUCCEEDED],
    )
    async def test_a_non_failure_transition_forbids_a_failure(
        self, store: PlanStore, to_status: StepStatus
    ) -> None:
        with pytest.raises(ValidationError, match="only valid for a transition to FAILED"):
            StepTransition(
                execution_id="e1",
                step_id="s1",
                to_status=to_status,
                expected_version=0,
                failure=StepFailure(message="boom"),
            )

    @pytest.mark.parametrize("to_status", [StepStatus.FAILED, StepStatus.INDETERMINATE])
    async def test_a_tool_failure_round_trips_verbatim(
        self, store: PlanStore, to_status: StepStatus
    ) -> None:
        """Kind and message are unchanged after ``commit_transition`` (ADR-0039 §6).

        On ``FAILED`` *and* ``INDETERMINATE`` — the latter is the regression test
        for #208 and for ADR-0032 §5's by-value rule surviving one frame past the
        seam. Read back from the store, not the return value, so a store that
        only echoed the command would not pass.
        """
        state = await self._started(store)
        state = await store.commit_transition(_claim(state))
        failure = StepFailure(
            kind=ToolFailureKind.RATE_LIMITED, message="the upstream throttled us"
        )
        state = await store.commit_transition(
            StepTransition(
                execution_id=state.id,
                step_id="s1",
                to_status=to_status,
                expected_version=state.version,
                failure=failure,
            )
        )

        stored = await store.get_execution(state.id)
        assert stored is not None
        step = stored.step("s1")
        assert step is not None
        assert step.status is to_status
        assert step.failure == failure
        assert step.failure is not None
        assert step.failure.kind is ToolFailureKind.RATE_LIMITED
        assert step.failure.message == "the upstream throttled us"

    async def test_an_indeterminate_step_with_a_retryable_kind_is_not_run_again(
        self, store: PlanStore
    ) -> None:
        """A durable kind on an INDETERMINATE step is diagnostic, never permission.

        The graph has no ``INDETERMINATE → RUNNING`` edge (ADR-0014 §4), so a
        ``TIMED_OUT`` whose ``retryable`` is ``True`` still cannot be re-claimed
        (ADR-0039 §4). This is the case a reader of the new field is most likely
        to get wrong.
        """
        state = await self._started(store)
        state = await store.commit_transition(_claim(state))
        state = await store.commit_transition(
            StepTransition(
                execution_id=state.id,
                step_id="s1",
                to_status=StepStatus.INDETERMINATE,
                expected_version=state.version,
                failure=StepFailure(kind=ToolFailureKind.TIMED_OUT, message="deadline passed"),
            )
        )
        assert ToolFailureKind.TIMED_OUT.retryable  # the field says "retryable"...
        with pytest.raises(IllegalTransitionError):  # ...and the graph still refuses it
            await store.commit_transition(_claim(state))

    # --- resumption -------------------------------------------------------

    async def test_active_executions_finds_outstanding_work(self, store: PlanStore) -> None:
        state = await self._started(store)
        assert [found.id for found in await store.active_executions()] == [state.id]

    # --- execution-id non-reuse (ADR-0044 §1, #280) -----------------------

    async def test_two_executions_of_one_plan_get_distinct_ids(self, store: PlanStore) -> None:
        """A plan may have several live executions, and each is its own instance.

        ADR-0014 §5's ``active_executions`` exists precisely to resume several,
        and ADR-0044 §1 binds a parked confirmation to ``(execution_id,
        step_id)``. So two executions of one plan must never share an id, or
        one's answer would resolve the other's identical parked step.
        """
        await store.save_goal(_goal())
        await store.save_plan(_plan())
        first = await store.start_execution("p1")
        second = await store.start_execution("p1")
        assert first.id != second.id

    async def test_a_deleted_executions_id_is_never_reused(self, store: PlanStore) -> None:
        """Deleting execution ``E`` must not free its id for a later one (#280).

        This is the exact hazard ADR-0044 §1 makes non-reuse normative against:
        a conforming store that deleted ``E`` and later minted another named
        ``E`` would let ``pending_confirmation(E, step)`` (ADR-0044 §3) return a
        stale ``CONFIRM`` from the prior incarnation for the fresh one. The id is
        asserted *unequal*, never a format — the contract fixes uniqueness, not
        how a store keys its ids.
        """
        first = await self._started(store)
        await store.delete_goal("g1")
        assert await store.get_execution(first.id) is None

        await store.save_goal(_goal())
        await store.save_plan(_plan())
        second = await store.start_execution("p1")
        assert second.id != first.id

    async def test_an_execution_id_is_not_reused_after_clear(self, store: PlanStore) -> None:
        """``clear`` erases the records but must not rewind the id space.

        The same non-reuse guarantee as deletion, taken through the bulk-erase
        path: a store that reset an id counter on ``clear`` would collide a new
        execution with one a still-retained audit trail already names.
        """
        first = await self._started(store)
        await store.clear()

        await store.save_goal(_goal())
        await store.save_plan(_plan())
        second = await store.start_execution("p1")
        assert second.id != first.id

    async def test_a_finished_execution_is_not_active(self, store: PlanStore) -> None:
        state = await self._started(store)
        state = await store.commit_transition(
            StepTransition(
                execution_id=state.id,
                step_id="s1",
                to_status=StepStatus.SKIPPED,
                expected_version=state.version,
                skip_reason=SkipReason.SUPERSEDED,
            )
        )
        assert await store.active_executions() == []

    # --- stored state is the store's own ----------------------------------

    async def test_a_retained_goal_reference_cannot_edit_stored_state(
        self, store: PlanStore
    ) -> None:
        """ADR-0068 freezes ``Goal``, so a retained reference cannot rewrite it."""
        goal = _goal()
        await store.save_goal(goal)
        with pytest.raises(ValidationError):
            goal.interpretation[0].outcome = "tampered"

        stored = await store.get_goal("g1")
        assert stored is not None
        assert stored.statement == "relocate to Lisbon"

    async def test_mutating_a_returned_goal_cannot_edit_stored_state(
        self, store: PlanStore
    ) -> None:
        await store.save_goal(_goal())
        got = await store.get_goal("g1")
        assert got is not None
        with pytest.raises(ValidationError):
            got.interpretation[0].outcome = "tampered"

        fresh = await store.get_goal("g1")
        assert fresh is not None
        assert fresh.statement == "relocate to Lisbon"

    async def test_mutating_a_returned_plan_cannot_edit_stored_state(
        self, store: PlanStore
    ) -> None:
        """``frozen=True`` stops attribute assignment, not ``__dict__`` writes.

        Sharing the stored instance would therefore let a caller rewrite the
        audit record in place — including a nested step's ``capability``, which
        is what the executor later binds a tool to.
        """
        await store.save_goal(_goal())
        await store.save_plan(_plan())

        got = await store.get_plan("p1")
        assert got is not None
        got.__dict__["goal_id"] = "tampered"
        got.steps[0].__dict__["capability"] = "payments.delete_account"

        fresh = await store.get_plan("p1")
        assert fresh is not None
        assert fresh.goal_id == "g1"
        assert fresh.steps[0].capability == "send_email"

    async def test_a_retained_plan_reference_cannot_edit_stored_state(
        self, store: PlanStore
    ) -> None:
        await store.save_goal(_goal())
        plan = _plan()
        await store.save_plan(plan)
        plan.__dict__["goal_id"] = "tampered"

        stored = await store.get_plan("p1")
        assert stored is not None
        assert stored.goal_id == "g1"

    async def test_an_exported_plan_cannot_edit_stored_state(self, store: PlanStore) -> None:
        await store.save_goal(_goal())
        await store.save_plan(_plan())

        export = await store.export()
        export.plans[0].__dict__["goal_id"] = "tampered"

        again = await store.export()
        assert again.plans[0].goal_id == "g1"

    async def test_mutating_a_returned_execution_cannot_edit_stored_state(
        self, store: PlanStore
    ) -> None:
        """Execution state is the audit record; only commit_transition may move it.

        ADR-0068 freezes ``ExecutionState`` and its ``StepExecution`` elements, so
        the audit record cannot be edited in place at all — neither the nested
        step status nor the version.
        """
        state = await self._started(store)
        with pytest.raises(ValidationError):
            state.steps[0].status = StepStatus.SUCCEEDED
        with pytest.raises(ValidationError):
            state.version = 99

        fresh = await store.get_execution(state.id)
        assert fresh is not None
        assert fresh.steps[0].status is StepStatus.PENDING
        assert fresh.version == 0

    async def test_active_executions_come_back_oldest_first(self, store: PlanStore) -> None:
        """Sorting ids would interleave plans and put exec-10 before exec-2."""
        await store.save_goal(_goal())
        expected = []
        for index in range(1, 13):
            await store.save_plan(_plan(plan_id=f"p{index}"))
            expected.append((await store.start_execution(f"p{index}")).id)

        assert [state.id for state in await store.active_executions()] == expected

    # --- data rights (ADR-0004) -------------------------------------------

    async def test_export_carries_the_stored_state(self, store: PlanStore) -> None:
        await self._started(store)
        export = await store.export()
        assert [goal.id for goal in export.goals] == ["g1"]
        assert [plan.id for plan in export.plans] == ["p1"]
        assert len(export.executions) == 1

    async def test_export_round_trips_through_json(self, store: PlanStore) -> None:
        await self._started(store)
        export = await store.export()
        assert type(export).model_validate_json(export.model_dump_json()) == export

    async def test_export_announces_the_shape_its_plans_carry(self, store: PlanStore) -> None:
        """ADR-0226 §11 item 16: "both conforming ``PlanStore`` implementations export
        the new version".

        The version is a fact about the *document*, so it cannot be a producer's
        claim (ADR-0039 §10) — and it is asserted here rather than only over the type
        because a store is the thing that mints an export, and one that assembled a
        document by hand could carry an ``ActionPlan`` with a ``read_request``
        while labelling it as the shape before that field existed.
        """
        await store.save_goal(_goal())
        await store.save_plan(_plan(read_request=_READ_REQUEST))
        export = await store.export()

        assert export.schema_version == 13
        assert export.plans[0].read_request == _READ_REQUEST

    async def test_export_round_trips_a_plans_read_request(self, store: PlanStore) -> None:
        """The other half of item 16: the request survives serialisation intact.

        An export is the artifact a user takes elsewhere, and ADR-0226 §4 makes the
        request part of what the plan records — a document that carried the version
        but dropped the field would announce a shape it does not have.
        """
        await store.save_goal(_goal())
        await store.save_plan(_plan(read_request=_READ_REQUEST))
        export = await store.export()

        restored = type(export).model_validate_json(export.model_dump_json())
        assert restored == export
        request = restored.plans[0].read_request
        assert request is not None
        assert {ask.kind for ask in request.asks} == {
            ReadKind.CITATION_HOP,
            ReadKind.SIGHTED_QUERY,
        }

    async def test_deleting_a_goal_cascades(self, store: PlanStore) -> None:
        state = await self._started(store)
        result = await store.delete_goal("g1")

        assert result.deleted
        assert result.plans_removed == 1
        assert result.executions_removed == 1
        assert await store.get_goal("g1") is None
        assert await store.get_plan("p1") is None
        assert await store.get_execution(state.id) is None

    async def test_deletion_is_refused_while_a_step_is_live(self, store: PlanStore) -> None:
        state = await self._started(store)
        await store.commit_transition(_claim(state))

        result = await store.delete_goal("g1")
        assert not result.deleted
        assert result.blocked_by == (state.id,)
        assert await store.get_goal("g1") is not None

    async def test_deletion_succeeds_once_the_live_step_resolves(self, store: PlanStore) -> None:
        """Cancel-then-delete: the round-trip the refusal above asks for."""
        state = await self._started(store)
        state = await store.commit_transition(_claim(state))
        state = await store.commit_transition(
            StepTransition(
                execution_id=state.id,
                step_id="s1",
                to_status=StepStatus.INDETERMINATE,
                expected_version=state.version,
                failure=StepFailure(message="whether the tool acted is unknown"),
            )
        )
        result = await store.delete_goal("g1")
        assert result.deleted

    async def test_deletion_reports_erased_indeterminate_steps(self, store: PlanStore) -> None:
        """The user must learn an action may have completed before its record went."""
        state = await self._started(store)
        state = await store.commit_transition(_claim(state))
        state = await store.commit_transition(
            StepTransition(
                execution_id=state.id,
                step_id="s1",
                to_status=StepStatus.INDETERMINATE,
                expected_version=state.version,
                failure=StepFailure(message="whether the tool acted is unknown"),
            )
        )
        result = await store.delete_goal("g1")
        assert result.indeterminate_steps == ("s1",)

    async def test_a_permanently_failed_step_does_not_block_deletion(
        self, store: PlanStore
    ) -> None:
        """Otherwise one failure would void the erasure right for good."""
        state = await self._started(store)
        state = await store.commit_transition(_claim(state))
        state = await store.commit_transition(
            StepTransition(
                execution_id=state.id,
                step_id="s1",
                to_status=StepStatus.FAILED,
                expected_version=state.version,
                failure=StepFailure(message="boom"),
            )
        )
        assert state.is_active
        result = await store.delete_goal("g1")
        assert result.deleted

    async def test_deleting_an_unknown_goal_reports_refusal(self, store: PlanStore) -> None:
        result = await store.delete_goal("ghost")
        assert not result.deleted

    async def test_clear_empties_the_store(self, store: PlanStore) -> None:
        await self._started(store)
        assert await store.clear() > 0
        assert await store.get_goal("g1") is None

    async def test_clear_is_refused_while_a_step_is_live(self, store: PlanStore) -> None:
        state = await self._started(store)
        await store.commit_transition(_claim(state))
        with pytest.raises(ActiveExecutionError):
            await store.clear()

    # --- cancellation (ADR-0060) -------------------------------------------

    #: Whether this implementation acquires nothing whose safety outlives the
    #: coroutine — no connection, lock, spawned task, file handle or transaction
    #: that a ``CancelledError`` could unwind past. ``core.protocols``' clause is
    #: then vacuously satisfied and there is nothing for the case below to
    #: observe. Left ``False``, the suite requires the implementation to prove the
    #: invariant by overriding :meth:`store_suspended_mid_write` — so a new
    #: durable backend that reintroduces ADR-0054's bug fails here rather than
    #: passing a suite that never looked. Opting out is a visible declaration in
    #: the subclass, exactly as ``serves_a_fixed_instant`` is for the context
    #: provider.
    acquires_no_shared_resource: bool = False

    def store_suspended_mid_write(
        self,
    ) -> AbstractAsyncContextManager[SuspendedMidWrite[PlanStore]]:
        """Supply a store whose named locked operation can be stopped *inside* its resource.

        Override unless :attr:`acquires_no_shared_resource` is set. The suite
        cancels the call while it is suspended and then watches what a second
        caller can reach, which is the only way to tell the fixed code from the
        broken code: pre-ADR-0054 the store raised ``CancelledError`` correctly
        and released the connection anyway, so a case that asserts only
        propagation certifies the bug (ADR-0060 §3).

        The returned :class:`SuspendedMidWrite` carries the store, its
        :class:`ResourceLog`, and an ``arm(operation)`` lever the case calls —
        *after* its preconditions — to hold the next entry into that operation
        (#370, #397). Every distinct ``async with self._lock`` site is a separate
        place the same regression can reappear — the locked *reads* included, since
        ADR-0060 §3 binds any method that acquires the resource — so the case is run
        against each; ``arm``
        is where the implementation says how it stops a given one — a worker
        thread parked mid-SQL, a fake's single modelled resource. Returned as a
        context manager so the subject is disposed of the way that implementation
        needs.

        The :class:`ResourceLog` records each call's time *inside* the resource,
        and the case reads it once the scenario is over. It is not redundant with
        the blocked-caller check below: that one is decisive only where queueing
        is loop-bound (a fake on an ``asyncio.Lock``), while a store whose work
        runs on an executor can leave a second call pending for reasons that have
        nothing to do with the resource. The log settles that case directly.
        """
        raise NotImplementedError

    @pytest.mark.optional_obligation
    async def test_record_evidence_observes_its_supersedes_before_its_first_await(
        self,
    ) -> None:
        """``core.protocols``' second standing obligation, on the one member that takes
        a caller-owned sequence (ADR-0065 §1).

        "Arguments belong to the caller … a ``Sequence`` argument is a container the
        caller may still be holding. So everything one call derives from one argument —
        what it stores, what it computes, what it returns — comes from **one**
        observation of that argument." ``record_evidence`` marks every row
        ``supersedes`` names, and a mark is terminal (§8), so a set read twice across a
        suspension would let a caller retire a row it never asked to retire — and
        nothing would record that it had not.

        ``evidence`` needs no case of its own on that clause's own terms: it is a frozen
        model whose every member is frozen or a tuple, which is the "immutable all the
        way down" the clause calls silent. The **set** is what is mutable, which is why
        it is the subject here.

        Driven mid-flight rather than after the call, for the reason ADR-0065 §3 gives
        for its own cases: "each case must establish mid-flight observation, not
        post-call isolation", because a post-call check passes on torn code.
        """
        if self.acquires_no_shared_resource:
            pytest.skip("implementation acquires nothing whose safety outlives the coroutine")

        async with self.store_suspended_mid_write() as harness:
            store = harness.store
            await _goal_with_attempt(store)
            await store.record_evidence(_evidence("ev1"))
            await store.record_evidence(_evidence("ev2", read_at=_WHEN + timedelta(minutes=1)))
            suspended = harness.arm("record_evidence")

            named = ["ev1"]
            writing = asyncio.ensure_future(
                store.record_evidence(
                    _evidence("ev3", read_at=_WHEN + timedelta(hours=1)), supersedes=named
                )
            )
            try:
                await suspended.reached()
                named.append("ev2")  # the caller mutates what it passed, mid-flight
                await settle()
            finally:
                suspended.release()
            await writing

            first = await store.get_evidence("ev1")
            second = await store.get_evidence("ev2")
            assert first is not None
            assert second is not None
            assert first.standing is EvidenceStanding.SUPERSEDED
            assert second.standing is EvidenceStanding.STANDING, (
                "the row appended mid-flight was never in the set this call observed"
            )

    @pytest.mark.parametrize("make_op", _CANCELLATION_OPS, ids=lambda op: op().name)
    async def test_a_cancelled_operation_holds_its_resource_until_the_work_finishes(
        self, make_op: Callable[[], _CancellationOp]
    ) -> None:
        """``core.protocols``' cancellation clause, on every locked operation (ADR-0060).

        A cancelled call must not hand the resource to the next caller while the
        work it started is still using it. The second call is what makes this a
        test of the invariant rather than of propagation: a single cancelled call
        in isolation looks identical either way. Run once per locked operation, so
        a regression reintroduced at any one lock site — not just ``save_goal`` —
        is caught.

        **Named for an operation, not a write.** ADR-0060 §3 binds any method that
        acquires the resource; the writes were covered first (#370) and the locked
        reads are the same invariant on the other half of the surface (#397). A read
        that released the connection under cancellation while its worker still held
        it is the identical ADR-0054 hazard, and no write case can see it.

        The first call's *effect* is deliberately not asserted here (the op's
        ``verify`` pins only what a caller may rely on). The clause's third
        paragraph makes it indeterminate to the caller — under ADR-0054's shield a
        cancelled write that reached ``COMMIT`` is durably written — so the two
        calls are independent subjects and what is pinned is that the second is
        whole and the store still serves reads.
        """
        if self.acquires_no_shared_resource:
            pytest.skip("implementation acquires nothing whose safety outlives the coroutine")

        op = make_op()
        async with self.store_suspended_mid_write() as harness:
            store = harness.store
            await op.prepare(store)
            # Arm *after* the preconditions, so a fake arming its one resource
            # suspends the operation under test rather than a setup write.
            suspended = harness.arm(op.name)
            visited_before = harness.log.visits

            first = asyncio.ensure_future(op.first(store))
            second: asyncio.Task[object] | None = None
            try:
                await suspended.reached()
                first.cancel()
                await settle()

                second = asyncio.ensure_future(op.second(store))
                await settle()
                assert not second.done(), _RELEASED_EARLY

                # Again, because deferring one cancellation is not the contract:
                # a second delivered while the deferred wait runs must not escape
                # and unwind out of the resource either (ADR-0054's helper loops
                # on `while not done.is_set()` for exactly this).
                first.cancel()
                await settle()
                assert not second.done(), _RELEASED_EARLY
            finally:
                suspended.release()

            with pytest.raises(asyncio.CancelledError):
                await first
            assert second is not None
            await second

            # Decisive where the blocked-caller check above is not: the two calls
            # were never inside the resource at the same time. A delta, because a
            # fake's preconditions pass through the same logged resource.
            assert not harness.log.overlapped, _RELEASED_EARLY
            assert harness.log.visits - visited_before == 2, (
                "both calls should have reached the resource by now"
            )

            await op.verify(store)
