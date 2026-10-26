"""Shared conformance suite for the PlanStore Protocol (ADR-0014).

Every ``PlanStore`` implementation must pass this suite (CONTRIBUTING, "Protocol
conformance suites"). A concrete test subclasses :class:`PlanStoreContract` and
overrides the ``store`` fixture.

This suite matters more than most: `InMemoryPlanStore`, `SqlitePlanStore` and
`FakePlanStore` re-implement the stop record (ADR-0297 §1) and acting's effect
records (ADR-0306 §6) independently — the fake cannot import the subsystem it stands
in for — so this is what stops them drifting. It asserts only behaviour the
*contract* guarantees, never how a given store keys its ids.

It pins the members the phases use, and the observer's three over its observation
records (ADR-0329 §16:9). The members ADR-0309 §5 retired have left the Protocol and
every store, so nothing here pins them.

Named ``*_contract`` (not ``test_*``) so pytest collects it only via a
``Test``-prefixed subclass, never the abstract base directly.
"""

from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, date, datetime, time, timedelta
from typing import TYPE_CHECKING, Any, Protocol

import pytest

from ai_assistant.core.errors import ClaimStopped, PlanningError
from ai_assistant.core.types import (
    ActivationEffect,
    ActivationEffectClaim,
    ChannelIdentity,
    DueAfterTasks,
    DueAt,
    DueNow,
    DueOnRule,
    EvidenceItemPart,
    FindingOutcome,
    FindingUnwritten,
    InputPart,
    MemoryDecisionKind,
    MemoryOperationKind,
    ObservationAttempt,
    ObservationAttemptEnd,
    ObservationFinding,
    ObservationRecord,
    ObservationState,
    ObservationWrite,
    ObserverCall,
    ObserverStep,
    OccurrencePush,
    OccurrenceState,
    Placement,
    PlacementReach,
    PlacementSetter,
    QuestionPart,
    RuleDay,
    RulePush,
    ScheduledTask,
    ScheduledTaskAuthor,
    ScheduledTaskWrite,
    TaskRefusal,
    TaskRuleKind,
    TaskSpawn,
    TaskWriteAnswer,
    ToolOutcome,
)
from ai_assistant.testing.cancellation import settle

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine
    from contextlib import AbstractAsyncContextManager

    from ai_assistant.core.protocols import PlanStore
    from ai_assistant.testing.cancellation import SuspendedMidWrite

_WHEN = datetime(2026, 1, 1, tzinfo=UTC)

#: More ids than one SQLite statement can bind (``SQLITE_MAX_VARIABLE_NUMBER`` is 32766
#: on every SQLite since 3.32), so a read naming this many must be read in parts
#: (issue #3296).
_PAST_SQLITES_BOUND = 33_000


#: What a failure of the cancellation case below means, in one place: every
#: assertion in it is the same invariant seen from a different side.
_RELEASED_EARLY = (
    "the cancelled call released its resource while its own work was still "
    "running, so a second caller reached it concurrently"
)


def _effect(
    effect_id: str,
    *,
    activation: str = "act-1",
    capability: str = "book_stay",
    values: str = "a" * 64,
) -> ActivationEffect:
    """A call's effect record as acting claims it (ADR-0306 §6), with no outcome."""
    return ActivationEffect(
        id=effect_id,
        activation_id=activation,
        round="r1",
        capability=capability,
        values_digest=values,
        decision_id=f"d-{effect_id}",
        claimed_at=_WHEN,
    )


def _spending(
    effect_id: str,
    *,
    activation: str = "act-2",
    part: QuestionPart | None = None,
    capability: str = "book_stay",
    values: str = "a" * 64,
) -> ActivationEffect:
    """A call that runs under an approval, claimed with its part key (ADR-0321 §4:9).

    It is made in the yes's activation, ``act-2`` by default, and spends part 1 of the
    question round ``q-round`` asked unless another part is named.
    """
    return _effect(
        effect_id, activation=activation, capability=capability, values=values
    ).model_copy(update={"part": part or QuestionPart(round="q-round", part=1)})


def _message(effect_id: str, *, activation: str = "act-1") -> ActivationEffect:
    """A message's effect record as claimed, with no outcome and no position."""
    return ActivationEffect(
        id=effect_id, activation_id=activation, round="r1", place="c-1", claimed_at=_WHEN
    )


def _observation(
    episode: str = "activation:act-1",
    *,
    calls: tuple[datetime, ...] = (_WHEN,),
    state: ObservationState = ObservationState.PROCESSED,
) -> ObservationRecord:
    """An observation record as the observer writes one (ADR-0329 §16:1).

    One attempt, which made a scout call and a commit call per later instant in
    ``calls``, and two findings: one written, creating a memory and adding a support,
    and one that wrote nothing. A waiting record's second finding has no outcome yet.
    """
    first, *rest = calls or (_WHEN,)
    made = tuple(
        ObserverCall(step=ObserverStep.SCOUT if index == 0 else ObserverStep.COMMIT, at=at)
        for index, at in enumerate(calls)
    )
    done = state is not ObservationState.WAITING
    return ObservationRecord(
        episode=episode,
        state=state,
        attempts=(
            ObservationAttempt(
                started_at=min((first, *rest)),
                calls=made,
                end=ObservationAttemptEnd.FINISHED if done else ObservationAttemptEnd.FAILED,
            ),
        ),
        next_attempt_at=None if done else _WHEN + timedelta(minutes=5),
        findings=(
            ObservationFinding(
                id="f1",
                episode=episode,
                claim="The user's sister is called Ada.",
                rests_on=(InputPart(episode=episode, message=0),),
                candidate="effect-remember",
                outcome=FindingOutcome(
                    at=_WHEN,
                    ruling=MemoryDecisionKind.ACCEPT,
                    writes=(
                        ObservationWrite(
                            memory="memory-ada",
                            operations=(
                                MemoryOperationKind.CREATE,
                                MemoryOperationKind.ADD_SUPPORT,
                            ),
                        ),
                    ),
                ),
            ),
            ObservationFinding(
                id="f2",
                episode=episode,
                claim="The report said the flight is delayed.",
                rests_on=(EvidenceItemPart(episode=episode, digest=0, item=1),),
                outcome=(
                    FindingOutcome(at=_WHEN, unwritten=FindingUnwritten.NOT_KEPT) if done else None
                ),
            ),
        ),
    )


class _CancellationOp(Protocol):
    """One locked ``PlanStore`` operation the ADR-0060 case drives (#370, #397).

    Each :attr:`name` selects a distinct ``async with self._lock:
    _run_to_completion(...)`` site; the suite runs the same
    cancelled-first / concurrent-second scenario against every one, so a
    regression reintroduced at any single site is caught rather than only at
    one. :meth:`first` and :meth:`second` act on *independent* subjects, so the
    concurrent second succeeds whatever the cancelled first's indeterminate effect
    turns out to be — which matters most for ``claim_activation_effect``, whose
    one indivisible step would otherwise couple them.

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


class _ClearOp:
    """The ``clear`` write."""

    name = "clear"

    async def prepare(self, store: PlanStore) -> None:
        """A stop record and an effect record to remove, so ``clear`` does real work."""
        await store.record_stop("act-A")
        await store.claim_activation_effect(_effect("eB", activation="act-B"), match=None)

    def first(self, store: PlanStore) -> Coroutine[Any, Any, object]:
        """Clear the store — the call that is cancelled."""
        return store.clear()

    def second(self, store: PlanStore) -> Coroutine[Any, Any, object]:
        """Clear again concurrently."""
        return store.clear()

    async def verify(self, store: PlanStore) -> None:
        """The store is empty and still serves reads."""
        exported = await store.export()
        assert exported.stopped_activations == ()
        assert exported.activation_effects == ()


class _ReadOp:
    """A locked ``PlanStore`` read, driven against a store seeded the same way (#397).

    The two calls are the *same* read against independent subjects, because what
    distinguishes a read op is its lock site and both calls have to enter it.
    Nothing is asserted about the cancelled read's answer — it has none, its task
    was cancelled — so :meth:`verify` pins the state the second call had to see,
    re-read once the scenario is over.
    """

    name = ""

    async def prepare(self, store: PlanStore) -> None:
        """Seed two activations' effect records and a stop for the reads to answer from."""
        await store.claim_activation_effect(_effect("eA", activation="act-1"), match=None)
        await store.claim_activation_effect(_effect("eB", activation="act-2"), match=None)
        await store.record_stop("act-3")

    def first(self, store: PlanStore) -> Coroutine[Any, Any, object]:
        """The read the case suspends inside the resource and then cancels."""
        raise NotImplementedError

    def second(self, store: PlanStore) -> Coroutine[Any, Any, object]:
        """The concurrent read barred from the resource until the first is done."""
        raise NotImplementedError

    async def verify(self, store: PlanStore) -> None:
        """A read cancelled mid-flight leaves the store whole and still readable."""
        read = await store.activation_effects(["act-1", "act-2"])
        assert [one.id for one in read] == ["eA", "eB"]
        assert (await store.export()).stopped_activations == ("act-3",)


class _PartEffectsOp(_ReadOp):
    """``part_effects`` — the read by question part, its own lock site (ADR-0321 §4:9)."""

    name = "part_effects"

    def first(self, store: PlanStore) -> Coroutine[Any, Any, object]:
        """Read by part — the call that is cancelled."""
        return store.part_effects([QuestionPart(round="q-round", part=1)])

    def second(self, store: PlanStore) -> Coroutine[Any, Any, object]:
        """Read by part again concurrently."""
        return store.part_effects([QuestionPart(round="q-round", part=1)])


class _ExportOp(_ReadOp):
    """``export`` — the whole-store read, its own lock site."""

    name = "export"

    def first(self, store: PlanStore) -> Coroutine[Any, Any, object]:
        """Export everything — the call that is cancelled."""
        return store.export()

    def second(self, store: PlanStore) -> Coroutine[Any, Any, object]:
        """Export again concurrently."""
        return store.export()


class _RecordStopOp:
    """The ``record_stop`` write (ADR-0297 §1), naming two independent activations."""

    name = "record_stop"

    async def prepare(self, store: PlanStore) -> None:
        """Nothing: a stop record names no row the store must already hold."""

    def first(self, store: PlanStore) -> Coroutine[Any, Any, object]:
        """Stop activation A — the call that is cancelled."""
        return store.record_stop("act-A")

    def second(self, store: PlanStore) -> Coroutine[Any, Any, object]:
        """Stop activation B concurrently."""
        return store.record_stop("act-B")

    async def verify(self, store: PlanStore) -> None:
        """Activation B's record is held; the store still serves reads."""
        assert "act-B" in (await store.export()).stopped_activations


class _ClaimActivationEffectOp:
    """The ``claim_activation_effect`` write (ADR-0306 §6:2), on two activations.

    Its stop, backstop and write are one indivisible step, so a release before its own
    work finished would let a second claim decide against a record not yet written.
    """

    name = "claim_activation_effect"

    async def prepare(self, store: PlanStore) -> None:
        """Nothing: a claim names no row the store must already hold."""

    def first(self, store: PlanStore) -> Coroutine[Any, Any, object]:
        """Claim activation A's effect — the call that is cancelled."""
        return store.claim_activation_effect(_effect("eA", activation="act-A"), match=None)

    def second(self, store: PlanStore) -> Coroutine[Any, Any, object]:
        """Claim activation B's effect concurrently."""
        return store.claim_activation_effect(_effect("eB", activation="act-B"), match=None)

    async def verify(self, store: PlanStore) -> None:
        """Activation B's record landed whole; the store still serves reads."""
        assert [one.id for one in await store.activation_effects(["act-B"])] == ["eB"]


class _FinishActivationEffectOp:
    """The ``finish_activation_effect`` write (ADR-0306 §6:4), on two records."""

    name = "finish_activation_effect"

    async def prepare(self, store: PlanStore) -> None:
        """Two claimed records to finish."""
        await store.claim_activation_effect(_effect("eA", activation="act-A"), match=None)
        await store.claim_activation_effect(_effect("eB", activation="act-B"), match=None)

    def first(self, store: PlanStore) -> Coroutine[Any, Any, object]:
        """Finish record A — the call that is cancelled."""
        return store.finish_activation_effect("eA", ToolOutcome.SUCCEEDED)

    def second(self, store: PlanStore) -> Coroutine[Any, Any, object]:
        """Finish record B concurrently."""
        return store.finish_activation_effect("eB", ToolOutcome.FAILED)

    async def verify(self, store: PlanStore) -> None:
        """Record B carries its outcome; the store still serves reads."""
        (held,) = await store.activation_effects(["act-B"])
        assert held.outcome is ToolOutcome.FAILED


class _WriteObservationOp:
    """The ``write_observation`` write (ADR-0329 §16:9), on two episodes."""

    name = "write_observation"

    async def prepare(self, store: PlanStore) -> None:
        """Nothing: a first write names no record the store must already hold."""

    def first(self, store: PlanStore) -> Coroutine[Any, Any, object]:
        """Write episode A's record — the call that is cancelled."""
        return store.write_observation(_observation("episode-A"), expected_revision=0)

    def second(self, store: PlanStore) -> Coroutine[Any, Any, object]:
        """Write episode B's record concurrently."""
        return store.write_observation(_observation("episode-B"), expected_revision=0)

    async def verify(self, store: PlanStore) -> None:
        """Episode B's record landed whole; the store still serves reads."""
        (held,) = await store.observations(["episode-B"])
        assert held.findings == _observation("episode-B").findings


class _ObservationReadOp(_ReadOp):
    """A read of the observation records, seeded with one beside the effect records."""

    async def prepare(self, store: PlanStore) -> None:
        """The effect records and stop the other reads see, and one observation record."""
        await super().prepare(store)
        await store.write_observation(_observation("episode-A"), expected_revision=0)

    async def verify(self, store: PlanStore) -> None:
        """The observation record is still whole, and so is the rest."""
        await super().verify(store)
        assert [one.episode for one in await store.observations(["episode-A"])] == ["episode-A"]


class _ObservationsOp(_ObservationReadOp):
    """``observations`` — the read by episode id, its own lock site (ADR-0329 §16:9)."""

    name = "observations"

    def first(self, store: PlanStore) -> Coroutine[Any, Any, object]:
        """Read the record — the call that is cancelled."""
        return store.observations(["episode-A"])

    def second(self, store: PlanStore) -> Coroutine[Any, Any, object]:
        """Read it again concurrently."""
        return store.observations(["episode-A"])


class _ObserverCallsSinceOp(_ObservationReadOp):
    """``observer_calls_since`` — the budget's count, its own lock site (ADR-0329 §16:9)."""

    name = "observer_calls_since"

    def first(self, store: PlanStore) -> Coroutine[Any, Any, object]:
        """Count the calls — the call that is cancelled."""
        return store.observer_calls_since(_WHEN)

    def second(self, store: PlanStore) -> Coroutine[Any, Any, object]:
        """Count them again concurrently."""
        return store.observer_calls_since(_WHEN)


class _ActivationEffectsOp(_ReadOp):
    """``activation_effects`` — a read of acting's records, its own lock site."""

    name = "activation_effects"

    def first(self, store: PlanStore) -> Coroutine[Any, Any, object]:
        """Read the records — the call that is cancelled."""
        return store.activation_effects(["act-1"])

    def second(self, store: PlanStore) -> Coroutine[Any, Any, object]:
        """Read them again concurrently."""
        return store.activation_effects(["act-1"])


# --- the Task Scheduler's scheduled tasks (ADR-0350 §12:3) ---------------------------

#: The person the scheduled tasks below are for, and another.
_PERSON = "person:owner"
_OTHER = "person:guest"

#: Where the tasks below were set: a conversation, and the line's chat.
_HUB_CHAT = ChannelIdentity(channel_type="conversation", instance_id="c-1")
_LINE = ChannelIdentity(channel_type="telegram", instance_id="line")

#: The limits the cases below write under, §12:5's defaults.
_CHAIN_LIMIT = 10
_PENDING_LIMIT = 50


def _spawn(  # noqa: PLR0913 — every part a case below varies
    task_id: str,
    *,
    person: str = _PERSON,
    when: DueNow | DueAt | DueAfterTasks | DueOnRule | None = None,
    places: tuple[ChannelIdentity, ...] = (),
    replaces: str | None = None,
    outside: bool = False,
    author: ScheduledTaskAuthor = ScheduledTaskAuthor.ASSISTANT,
    first_due_at: datetime | None = None,
) -> TaskSpawn:
    """A spawn as the actuator states it (ADR-0350 §3:6), due now unless told otherwise.

    A rule's spawn carries the instant of its first occurrence, as its caller computed
    it (ADR-0340 §9:1).
    """
    return TaskSpawn(
        id=task_id,
        person=person,
        author=author,
        when=when or DueNow(),
        places=places,
        instruction=f"do the step {task_id}",
        set_in=_HUB_CHAT,
        set_at=_WHEN,
        outside_content=outside,
        replaces=replaces,
        first_due_at=first_due_at,
    )


#: A daily rule at 07:00 in the person's zone, and the instants a caller computed for
#: its occurrences: the store computes none (ADR-0340 §9:5), so a case hands them in.
_DAILY = DueOnRule(repeats=TaskRuleKind.DAILY, time_of_day=time(7, 0))
_DAY = timedelta(days=1)
_FIRST = _WHEN + timedelta(hours=7)


def _due(day: int) -> datetime:
    """The instant a daily rule's occurrence falls due on day ``day``, from the first."""
    return _FIRST + day * _DAY


async def _rule_written(store: PlanStore, task_id: str, **write: Any) -> ScheduledTask:
    """Write a task the person set on a daily rule, first due at :data:`_FIRST`."""
    return await _written(
        store,
        task_id,
        when=write.pop("when", _DAILY),
        author=ScheduledTaskAuthor.PERSON,
        first_due_at=write.pop("first_due_at", _FIRST),
        **write,
    )


def _spawn_effect(effect_id: str, *, activation: str = "act-1") -> ActivationEffect:
    """A spawn's effect record, a call to the spawn capability claimed with no outcome."""
    return _effect(
        effect_id,
        activation=activation,
        capability="spawn",
        values=hashlib.sha256(effect_id.encode()).hexdigest(),
    )


async def _write(  # noqa: PLR0913 — every part a case below varies
    store: PlanStore,
    task_id: str,
    *,
    spawner: str = "act-1",
    chain_limit: int = _CHAIN_LIMIT,
    pending_limit: int = _PENDING_LIMIT,
    replace_any: bool = False,
    **spawn: Any,
) -> ScheduledTaskWrite:
    """Write one task spawned by ``spawner``, its effect record named after the task."""
    return await store.write_scheduled_task(
        _spawn(task_id, **spawn),
        _spawn_effect(f"spawn-{task_id}", activation=spawner),
        match=None,
        replace_any=replace_any,
        chain_limit=chain_limit,
        pending_limit=pending_limit,
    )


async def _written(store: PlanStore, task_id: str, **write: Any) -> ScheduledTask:
    """Write one task and return it as written, failing on any other answer."""
    answer = await _write(store, task_id, **write)
    assert answer.answer is TaskWriteAnswer.WRITTEN, answer
    assert answer.task is not None
    return answer.task


async def _held(store: PlanStore, task_id: str) -> ScheduledTask:
    """The task the store holds under ``task_id``."""
    (task,) = await store.scheduled_tasks([task_id])
    return task


async def _state(store: PlanStore, task_id: str) -> OccurrenceState:
    """The state of the one occurrence of the task held under ``task_id``."""
    (occurrence,) = (await _held(store, task_id)).occurrences
    return occurrence.state


async def _step(store: PlanStore, task_id: str, activation: str) -> ScheduledTask:
    """Push a task's occurrence to ``activation``, failing unless it is pushed."""
    assert await store.mark_occurrence_pushed(task_id, 1, activation) is OccurrencePush.PUSHED
    return await _held(store, task_id)


class _ScheduleOp:
    """A locked Task Scheduler operation (ADR-0350 §12:3), driven as every other is.

    Seeded with two tasks due now, ``tA`` and ``tB``, each spawned by its own
    activation, and ``tB``'s occurrence pushed to ``act-B``, so the cancelled call and
    the concurrent one act on independent subjects whatever the first's effect.
    """

    name = ""

    async def prepare(self, store: PlanStore) -> None:
        """Two tasks, one pushed, for the operation to act on."""
        await _written(store, "tA", spawner="act-spawner-A")
        await _written(store, "tB", spawner="act-spawner-B")
        await _step(store, "tB", "act-B")

    def first(self, store: PlanStore) -> Coroutine[Any, Any, object]:
        """The call the case suspends inside the resource and then cancels."""
        raise NotImplementedError

    def second(self, store: PlanStore) -> Coroutine[Any, Any, object]:
        """The concurrent call barred from the resource until the first is done."""
        raise NotImplementedError

    async def verify(self, store: PlanStore) -> None:
        """Both tasks are still held whole, and the store still serves reads."""
        assert [one.id for one in await store.scheduled_tasks(["tA", "tB"])] == ["tA", "tB"]


class _WriteScheduledTaskOp(_ScheduleOp):
    """``write_scheduled_task``: the spawn's one step (§3:3)."""

    name = "write_scheduled_task"

    def first(self, store: PlanStore) -> Coroutine[Any, Any, object]:
        """Write task C — the call that is cancelled."""
        return _write(store, "tC", spawner="act-spawner-C")

    def second(self, store: PlanStore) -> Coroutine[Any, Any, object]:
        """Write task D concurrently."""
        return _write(store, "tD", spawner="act-spawner-D")

    async def verify(self, store: PlanStore) -> None:
        """Task D landed whole with its effect record."""
        await super().verify(store)
        assert [one.id for one in await store.scheduled_tasks(["tD"])] == ["tD"]
        assert [one.id for one in await store.activation_effects(["act-spawner-D"])] == ["spawn-tD"]


class _CancelScheduledTaskOp(_ScheduleOp):
    """``cancel_scheduled_task`` (§9:5)."""

    name = "cancel_scheduled_task"

    async def prepare(self, store: PlanStore) -> None:
        """A third pending task beside the two."""
        await super().prepare(store)
        await _written(store, "tC", spawner="act-spawner-C")

    def first(self, store: PlanStore) -> Coroutine[Any, Any, object]:
        """Cancel task A — the call that is cancelled."""
        return store.cancel_scheduled_task("tA")

    def second(self, store: PlanStore) -> Coroutine[Any, Any, object]:
        """Cancel task C concurrently."""
        return store.cancel_scheduled_task("tC")

    async def verify(self, store: PlanStore) -> None:
        """Task C is cancelled."""
        await super().verify(store)
        assert await _state(store, "tC") is OccurrenceState.CANCELLED


class _MarkOccurrencePushedOp(_ScheduleOp):
    """``mark_occurrence_pushed`` (§7:5)."""

    name = "mark_occurrence_pushed"

    async def prepare(self, store: PlanStore) -> None:
        """A third pending task beside the two."""
        await super().prepare(store)
        await _written(store, "tC", spawner="act-spawner-C")

    def first(self, store: PlanStore) -> Coroutine[Any, Any, object]:
        """Push task A — the call that is cancelled."""
        return store.mark_occurrence_pushed("tA", 1, "act-A")

    def second(self, store: PlanStore) -> Coroutine[Any, Any, object]:
        """Push task C concurrently."""
        return store.mark_occurrence_pushed("tC", 1, "act-C")

    async def verify(self, store: PlanStore) -> None:
        """Task C is pushed."""
        await super().verify(store)
        assert await _state(store, "tC") is OccurrenceState.PUSHED


class _SettleOccurrenceOp(_ScheduleOp):
    """``settle_occurrence`` (§7:6, §8)."""

    name = "settle_occurrence"

    async def prepare(self, store: PlanStore) -> None:
        """Task A pushed too, so both have an occurrence to settle."""
        await super().prepare(store)
        await _step(store, "tA", "act-A")

    def first(self, store: PlanStore) -> Coroutine[Any, Any, object]:
        """Settle task A's occurrence — the call that is cancelled."""
        return store.settle_occurrence("act-A", OccurrenceState.DONE)

    def second(self, store: PlanStore) -> Coroutine[Any, Any, object]:
        """Settle task B's concurrently."""
        return store.settle_occurrence("act-B", OccurrenceState.COULDNT_FINISH)

    async def verify(self, store: PlanStore) -> None:
        """Task B's occurrence ended as it was settled."""
        await super().verify(store)
        assert await _state(store, "tB") is OccurrenceState.COULDNT_FINISH


class _StopPushedActivationOp(_ScheduleOp):
    """``stop_pushed_activation`` (§9:10)."""

    name = "stop_pushed_activation"

    async def prepare(self, store: PlanStore) -> None:
        """Task A pushed too, so both name a pushed activation."""
        await super().prepare(store)
        await _step(store, "tA", "act-A")

    def first(self, store: PlanStore) -> Coroutine[Any, Any, object]:
        """Stop act-A — the call that is cancelled."""
        return store.stop_pushed_activation("act-A")

    def second(self, store: PlanStore) -> Coroutine[Any, Any, object]:
        """Stop act-B concurrently."""
        return store.stop_pushed_activation("act-B")

    async def verify(self, store: PlanStore) -> None:
        """act-B carries its stop record."""
        await super().verify(store)
        assert await store.stopped_activations(["act-B"]) == ("act-B",)


class _ConfirmMessageEffectOp(_ScheduleOp):
    """``confirm_message_effect`` (§8:11)."""

    name = "confirm_message_effect"

    async def prepare(self, store: PlanStore) -> None:
        """Two messages claimed with no outcome, beside the tasks."""
        await super().prepare(store)
        await store.claim_activation_effect(_message("mA", activation="act-A"), match=None)
        await store.claim_activation_effect(_message("mB", activation="act-B"), match=None)

    def first(self, store: PlanStore) -> Coroutine[Any, Any, object]:
        """Confirm message A — the call that is cancelled."""
        return store.confirm_message_effect("mA", delivered=True, position=3)

    def second(self, store: PlanStore) -> Coroutine[Any, Any, object]:
        """Confirm message B absent concurrently."""
        return store.confirm_message_effect("mB", delivered=False)

    async def verify(self, store: PlanStore) -> None:
        """Message B is settled not done."""
        await super().verify(store)
        (held,) = await store.activation_effects(["act-B"])
        assert held.outcome is ToolOutcome.FAILED


class _RemoveScheduledTaskOp(_ScheduleOp):
    """``remove_scheduled_task`` (§7:8)."""

    name = "remove_scheduled_task"

    async def prepare(self, store: PlanStore) -> None:
        """Two ended tasks to remove, beside the two."""
        await super().prepare(store)
        for one in ("tC", "tD"):
            await _written(store, one, spawner=f"act-spawner-{one}")
            await store.cancel_scheduled_task(one)

    def first(self, store: PlanStore) -> Coroutine[Any, Any, object]:
        """Remove task C — the call that is cancelled."""
        return store.remove_scheduled_task("tC")

    def second(self, store: PlanStore) -> Coroutine[Any, Any, object]:
        """Remove task D concurrently."""
        return store.remove_scheduled_task("tD")

    async def verify(self, store: PlanStore) -> None:
        """Task D is gone, and the two are held."""
        await super().verify(store)
        assert await store.scheduled_tasks(["tD"]) == ()


class _ScheduleReadOp(_ScheduleOp):
    """A read of the schedule: the same read against the seeded store, twice."""

    def read(self, store: PlanStore) -> Coroutine[Any, Any, object]:
        """The read."""
        raise NotImplementedError

    def first(self, store: PlanStore) -> Coroutine[Any, Any, object]:
        """The read — the call that is cancelled."""
        return self.read(store)

    def second(self, store: PlanStore) -> Coroutine[Any, Any, object]:
        """The read again, concurrently."""
        return self.read(store)


class _ScheduledTasksOp(_ScheduleReadOp):
    """``scheduled_tasks``."""

    name = "scheduled_tasks"

    def read(self, store: PlanStore) -> Coroutine[Any, Any, object]:
        """Read the two by id."""
        return store.scheduled_tasks(["tA", "tB"])


class _PersonScheduledTasksOp(_ScheduleReadOp):
    """``person_scheduled_tasks``."""

    name = "person_scheduled_tasks"

    def read(self, store: PlanStore) -> Coroutine[Any, Any, object]:
        """Read the person's pending tasks."""
        return store.person_scheduled_tasks(_PERSON, [OccurrenceState.PENDING])


class _SpawnedTasksOp(_ScheduleReadOp):
    """``spawned_tasks``."""

    name = "spawned_tasks"

    def read(self, store: PlanStore) -> Coroutine[Any, Any, object]:
        """Read what act-spawner-A spawned."""
        return store.spawned_tasks(["act-spawner-A"])


class _ScheduledLineageOp(_ScheduleReadOp):
    """``scheduled_lineage``."""

    name = "scheduled_lineage"

    def read(self, store: PlanStore) -> Coroutine[Any, Any, object]:
        """Read act-B's lineage."""
        return store.scheduled_lineage("act-B")


class _LiveBelowOp(_ScheduleReadOp):
    """``live_below``."""

    name = "live_below"

    def read(self, store: PlanStore) -> Coroutine[Any, Any, object]:
        """Read whether anything below task B is live."""
        return store.live_below("tB")


class _DueOccurrencesOp(_ScheduleReadOp):
    """``due_occurrences``."""

    name = "due_occurrences"

    def read(self, store: PlanStore) -> Coroutine[Any, Any, object]:
        """Read what is due."""
        return store.due_occurrences(_WHEN)


class _StoppedActivationsOp(_ScheduleReadOp):
    """``stopped_activations``."""

    name = "stopped_activations"

    def read(self, store: PlanStore) -> Coroutine[Any, Any, object]:
        """Read the stop records of two activations."""
        return store.stopped_activations(["act-A", "act-B"])


#: Every locked ``PlanStore`` operation ADR-0060's case is run against: each is a
#: distinct lock site with its own ``_run_to_completion`` call. The writes came
#: first (#370); the reads are the same invariant on the other half of the surface
#: (#397), since ADR-0060 §3 binds any method that acquires the resource rather
#: than any method that mutates.
_CANCELLATION_OPS: tuple[Callable[[], _CancellationOp], ...] = (
    _ClearOp,
    _ExportOp,
    # ADR-0297 §1's member is one more lock site: the write a claim is decided against.
    _RecordStopOp,
    # ADR-0306 §6's three members: two writes, one of them the indivisible claim, and a
    # read that acquires the resource like every other.
    _ClaimActivationEffectOp,
    _FinishActivationEffectOp,
    _ActivationEffectsOp,
    # ADR-0321 §4:9's read by question part: one more read that acquires the resource.
    _PartEffectsOp,
    # ADR-0329 §16:9's three members: the conditional write, and two reads.
    _WriteObservationOp,
    _ObservationsOp,
    _ObserverCallsSinceOp,
    # ADR-0350 §12:3's fourteen members, each its own lock site: seven writes and
    # seven reads (ADR-0352 §6:1 removed the eighth write, ``record_cascade``).
    _WriteScheduledTaskOp,
    _CancelScheduledTaskOp,
    _MarkOccurrencePushedOp,
    _SettleOccurrenceOp,
    _StopPushedActivationOp,
    _ConfirmMessageEffectOp,
    _RemoveScheduledTaskOp,
    _ScheduledTasksOp,
    _PersonScheduledTasksOp,
    _SpawnedTasksOp,
    _ScheduledLineageOp,
    _LiveBelowOp,
    _DueOccurrencesOp,
    _StoppedActivationsOp,
)


class PlanStoreContract:
    """Behaviour every ``PlanStore`` implementation must exhibit."""

    @pytest.fixture
    def store(self) -> PlanStore:
        """Return an empty store under test."""
        raise NotImplementedError

    # --- ADR-0297: the stop record and the claim it refuses ---------------

    async def test_a_claim_committed_before_the_stop_record_stands(self, store: PlanStore) -> None:
        """§1: the stop writes its record and nothing else, so a claim it follows stands.

        The stop is decided at the claim (ADR-0306 §6:2), so a record claimed before it
        keeps its place, and that record's own finish after the stop writes the outcome.
        """
        await store.claim_activation_effect(_effect("e1"), match=None)

        await store.record_stop("act-1")

        await store.finish_activation_effect("e1", ToolOutcome.SUCCEEDED)
        (held,) = await store.activation_effects(["act-1"])
        assert held.outcome is ToolOutcome.SUCCEEDED

    @pytest.mark.parametrize("stop_first", [True, False])
    async def test_exactly_one_of_landed_and_refused_holds_for_one_claim_and_one_stop(
        self, store: PlanStore, stop_first: bool
    ) -> None:
        """§2: "there is no third case", over both orderings of the pair.

        For one claim and one stop of its activation, exactly one of {the claim landed,
        the claim was refused} holds, and which is decided by which the store took first.
        The claim is ADR-0306 §6:2's, whose one indivisible step decides the stop first.
        """
        landed = refused = False
        if stop_first:
            await store.record_stop("act-1")
        try:
            await store.claim_activation_effect(_effect("e1"), match=None)
            landed = True
        except ClaimStopped:
            refused = True
        if not stop_first:
            await store.record_stop("act-1")

        assert landed is not refused
        assert refused is stop_first
        held = [one.id for one in await store.activation_effects(["act-1"])]
        assert held == ([] if stop_first else ["e1"])

    async def test_record_stop_is_idempotent(self, store: PlanStore) -> None:
        """§1: a second record of one activation writes nothing and raises nothing."""
        await store.record_stop("act-1")
        await store.record_stop("act-1")  # raises nothing

        assert (await store.export()).stopped_activations == ("act-1",)
        with pytest.raises(ClaimStopped):
            await store.claim_activation_effect(_effect("e1"), match=None)

    async def test_record_stop_refuses_no_activation_it_does_not_know(
        self, store: PlanStore
    ) -> None:
        """§1: "it refuses no activation id, since the store knows nothing of which
        activations ran" — so an id no claim has named is recorded like any other.
        """
        await store.record_stop("never-ran")

        assert (await store.export()).stopped_activations == ("never-ran",)

    async def test_the_export_carries_the_stop_records_and_clear_erases_them(
        self, store: PlanStore
    ) -> None:
        """§1: ``stopped_activations`` carries every record once; ``clear`` erases them.

        Erased with the store's other rows and counted among them, so a claim naming
        a formerly stopped activation lands after the ``clear``: the record is gone,
        not merely hidden from the document.
        """
        await store.record_stop("act-2")
        await store.record_stop("act-1")

        export = await store.export()
        assert export.schema_version == 26
        # ADR-0309 §5: the old path's sections left the document.
        assert set(export.model_dump()) == {
            "schema_version",
            "exported_at",
            "stopped_activations",
            "activation_effects",
            "observations",
            # ADR-0350 §12:3: the Task Scheduler's tasks; ADR-0352 §6:3 removed
            # ``cascades``.
            "scheduled_tasks",
        }
        assert sorted(export.stopped_activations) == ["act-1", "act-2"]
        assert type(export).model_validate_json(export.model_dump_json()) == export

        assert await store.clear() == 2
        assert (await store.export()).stopped_activations == ()

        assert await store.claim_activation_effect(_effect("e1"), match=None) is (
            ActivationEffectClaim.CLAIMED
        )

    async def test_record_stop_refuses_a_value_that_is_no_identifier(
        self, store: PlanStore
    ) -> None:
        """A blank id names no activation a claim could carry, and is refused as input.

        The refusal is ``planning``'s own error, and it writes nothing.
        """
        with pytest.raises(PlanningError):
            await store.record_stop("   ")

        assert (await store.export()).stopped_activations == ()

    # --- ADR-0306 §6: acting's effect records ---------------------------------

    async def test_a_claim_writes_the_record_with_no_outcome(self, store: PlanStore) -> None:
        """§6:2: an unmatched claim writes the record and answers ``claimed``."""
        record = _effect("e1")

        assert await store.claim_activation_effect(record, match=None) is (
            ActivationEffectClaim.CLAIMED
        )

        assert await store.activation_effects(["act-1"]) == (record,)
        assert (await store.export()).activation_effects == (record,)

    async def test_a_claim_carrying_an_outcome_is_refused(self, store: PlanStore) -> None:
        """§5:4: a record is claimed before it runs, so it carries no outcome yet."""
        finished = _effect("e1").model_copy(update={"outcome": ToolOutcome.SUCCEEDED})

        with pytest.raises(PlanningError):
            await store.claim_activation_effect(finished, match=None)

        assert await store.activation_effects(["act-1"]) == ()

    async def test_a_stopped_activation_claims_nothing(self, store: PlanStore) -> None:
        """§6:2: a stop record refuses the claim with ``ClaimStopped``, writing nothing."""
        await store.record_stop("act-1")

        with pytest.raises(ClaimStopped):
            await store.claim_activation_effect(_effect("e1"), match=("act-1",))

        assert await store.activation_effects(["act-1"]) == ()

    @pytest.mark.parametrize(
        "match",
        [("\ud800",), ("act-1", "act-\udfff")],
        ids=["lone-surrogate", "after-a-valid-id"],
    )
    async def test_a_match_naming_an_id_with_no_utf8_encoding_is_refused(
        self, store: PlanStore, match: tuple[str, ...]
    ) -> None:
        """An id no store could hold is refused as a ``PlanningError``, writing nothing.

        A record's activation is an identifier, so the id names nothing; but a SQLite
        store cannot bind it, and its driver's ``UnicodeEncodeError`` would otherwise
        escape as something other than the error the Protocol raises (issue #3288).
        Every store refuses it alike, before the claim's write.
        """
        with pytest.raises(PlanningError, match="index"):
            await store.claim_activation_effect(_effect("e1"), match=match)

        assert await store.activation_effects(["act-1"]) == ()

    async def test_a_stop_of_another_activation_refuses_nothing(self, store: PlanStore) -> None:
        """The stop is decided for the record's own activation alone."""
        await store.record_stop("act-2")

        assert await store.claim_activation_effect(_effect("e1"), match=None) is (
            ActivationEffectClaim.CLAIMED
        )

    async def test_a_claim_of_a_held_id_is_refused(self, store: PlanStore) -> None:
        """§6:2: an id the store already holds is refused with ``PlanningError``."""
        await store.claim_activation_effect(_effect("e1"), match=None)

        with pytest.raises(PlanningError):
            await store.claim_activation_effect(_effect("e1", values="b" * 64), match=None)

        assert [one.values_digest for one in await store.activation_effects(["act-1"])] == [
            "a" * 64
        ]

    async def test_no_match_claims_an_equal_call_again(self, store: PlanStore) -> None:
        """§6:3: a claim with ``match`` of ``None`` is never refused as already done."""
        await store.claim_activation_effect(_effect("e1"), match=None)

        assert await store.claim_activation_effect(_effect("e2"), match=None) is (
            ActivationEffectClaim.CLAIMED
        )

    @pytest.mark.parametrize(
        ("outcome", "deliberate", "expected"),
        [
            (None, False, ActivationEffectClaim.ALREADY_DONE),
            (None, True, ActivationEffectClaim.ALREADY_DONE),
            (ToolOutcome.INDETERMINATE, False, ActivationEffectClaim.ALREADY_DONE),
            (ToolOutcome.INDETERMINATE, True, ActivationEffectClaim.ALREADY_DONE),
            (ToolOutcome.SUCCEEDED, False, ActivationEffectClaim.ALREADY_DONE),
            (ToolOutcome.SUCCEEDED, True, ActivationEffectClaim.CLAIMED),
            (ToolOutcome.FAILED, False, ActivationEffectClaim.CLAIMED),
            (ToolOutcome.FAILED, True, ActivationEffectClaim.CLAIMED),
        ],
        ids=[
            "unwritten",
            "unwritten-deliberate",
            "unknown",
            "unknown-deliberate",
            "done",
            "done-deliberate",
            "not-done",
            "not-done-deliberate",
        ],
    )
    async def test_the_backstop_reads_the_matching_effects_outcome(
        self,
        store: PlanStore,
        outcome: ToolOutcome | None,
        deliberate: bool,
        expected: ActivationEffectClaim,
    ) -> None:
        """§5:9, §5:11, §6:2: unknown and unwritten count as done; not done does not.

        A deliberate repeat passes a matching effect only where it is done.
        """
        await store.claim_activation_effect(_effect("e1"), match=None)
        if outcome is not None:
            await store.finish_activation_effect("e1", outcome)

        answer = await store.claim_activation_effect(
            _effect("e2", activation="act-2"),
            match=("act-2", "act-1"),
            deliberate_repeat=deliberate,
        )

        assert answer is expected
        written = [one.id for one in await store.activation_effects(["act-2"])]
        assert written == (["e2"] if expected is ActivationEffectClaim.CLAIMED else [])

    async def test_already_done_writes_nothing(self, store: PlanStore) -> None:
        """§6:2: ``already_done`` writes nothing, so the export holds the first alone."""
        await store.claim_activation_effect(_effect("e1"), match=None)

        await store.claim_activation_effect(_effect("e2"), match=("act-1",))

        assert [one.id for one in (await store.export()).activation_effects] == ["e1"]

    async def test_the_backstop_matches_however_many_activations_it_names(
        self, store: PlanStore
    ) -> None:
        """§5:9: a match naming more activations than SQLite binds is read whole (#3296).

        The matching record names the match's last activation, so a store that read only
        a part of the match would claim the call again.
        """
        match = tuple(f"act-{index}" for index in range(_PAST_SQLITES_BOUND))
        await store.claim_activation_effect(_effect("e1", activation=match[-1]), match=None)

        answer = await store.claim_activation_effect(
            _effect("e2", activation=match[0]), match=match
        )

        assert answer is ActivationEffectClaim.ALREADY_DONE
        assert await store.activation_effects([match[0]]) == ()

    async def test_the_backstop_matches_only_the_named_activations(self, store: PlanStore) -> None:
        """§5:9: an activation outside ``match`` is not matched against."""
        await store.claim_activation_effect(_effect("e1", activation="act-9"), match=None)

        assert await store.claim_activation_effect(_effect("e2"), match=("act-1",)) is (
            ActivationEffectClaim.CLAIMED
        )

    @pytest.mark.parametrize(
        "other",
        [
            {"capability": "send_email"},
            {"values": "c" * 64},
        ],
        ids=["another-capability", "other-values"],
    )
    async def test_the_backstop_matches_capability_and_values_together(
        self, store: PlanStore, other: dict[str, str]
    ) -> None:
        """§6:2: a match carries the same capability *and* the same values digest."""
        await store.claim_activation_effect(_effect("e1"), match=None)

        answer = await store.claim_activation_effect(_effect("e2", **other), match=("act-1",))

        assert answer is ActivationEffectClaim.CLAIMED

    async def test_a_message_is_never_matched(self, store: PlanStore) -> None:
        """Only a call matches a call: a message carries no capability or values."""
        await store.claim_activation_effect(_message("m1"), match=None)

        assert await store.claim_activation_effect(_message("m2"), match=("act-1",)) is (
            ActivationEffectClaim.CLAIMED
        )

    async def test_two_equal_claims_at_once_admit_one(self, store: PlanStore) -> None:
        """§5 and §6:2: the claim is one indivisible step, so concurrent equal calls
        in one round are one claimed and one already done."""
        answers = await asyncio.gather(
            store.claim_activation_effect(_effect("e1"), match=("act-1",)),
            store.claim_activation_effect(_effect("e2"), match=("act-1",)),
        )

        assert sorted(answers) == sorted(
            [ActivationEffectClaim.CLAIMED, ActivationEffectClaim.ALREADY_DONE]
        )
        assert len(await store.activation_effects(["act-1"])) == 1

    # --- ADR-0321 §4:9, §6:2: the spend, its read and the retry's admission ---------

    @pytest.mark.parametrize(
        "outcome",
        [None, ToolOutcome.SUCCEEDED, ToolOutcome.FAILED, ToolOutcome.INDETERMINATE],
        ids=["unwritten", "done", "not-done", "unknown"],
    )
    async def test_a_part_already_carried_is_already_used_whatever_its_outcome(
        self, store: PlanStore, outcome: ToolOutcome | None
    ) -> None:
        """§4:9: where a record carries the part key, the claim answers and writes nothing.

        Two yeses to one part cannot both run, so the key is spent by the first claim
        whatever came of it: a part is answered once.
        """
        await store.claim_activation_effect(_spending("e1"), match=None)
        if outcome is not None:
            await store.finish_activation_effect("e1", outcome)

        answer = await store.claim_activation_effect(
            _spending("e2", activation="act-3", values="b" * 64), match=None
        )

        assert answer is ActivationEffectClaim.ALREADY_USED
        assert await store.activation_effects(["act-3"]) == ()
        assert [one.id for one in (await store.export()).activation_effects] == ["e1"]

    async def test_the_spend_reads_every_activation_and_ignores_match(
        self, store: PlanStore
    ) -> None:
        """§4:9: the key is spent across activations; ``match`` narrows only the backstop."""
        await store.claim_activation_effect(_spending("e1", activation="act-9"), match=None)

        answer = await store.claim_activation_effect(
            _spending("e2", activation="act-2"), match=("act-2",)
        )

        assert answer is ActivationEffectClaim.ALREADY_USED

    async def test_another_part_of_the_same_question_is_not_spent(self, store: PlanStore) -> None:
        """§4:9: the key is the round *and* the part; each part is spent on its own."""
        await store.claim_activation_effect(_spending("e1"), match=None)

        for effect in (
            _spending("e2", part=QuestionPart(round="q-round", part=2), values="b" * 64),
            _spending("e3", part=QuestionPart(round="q-other", part=1), values="c" * 64),
        ):
            assert await store.claim_activation_effect(effect, match=None) is (
                ActivationEffectClaim.CLAIMED
            )

    async def test_a_call_with_no_part_spends_nothing(self, store: PlanStore) -> None:
        """§4:9: only a call under an approval carries a key, so no other claim spends one."""
        await store.claim_activation_effect(_effect("e1"), match=None)

        assert await store.claim_activation_effect(_spending("e2"), match=None) is (
            ActivationEffectClaim.CLAIMED
        )

    async def test_two_yeses_to_one_part_at_once_admit_one(self, store: PlanStore) -> None:
        """§4:9: the spend is decided in the claim's one indivisible step."""
        answers = await asyncio.gather(
            store.claim_activation_effect(_spending("e1", activation="act-2"), match=None),
            store.claim_activation_effect(_spending("e2", activation="act-3"), match=None),
        )

        assert sorted(answers) == sorted(
            [ActivationEffectClaim.CLAIMED, ActivationEffectClaim.ALREADY_USED]
        )
        assert len(await store.part_effects([QuestionPart(round="q-round", part=1)])) == 1

    @pytest.mark.parametrize(
        ("outcome", "deliberate", "under_approval", "expected"),
        [
            (None, True, True, ActivationEffectClaim.CLAIMED),
            (ToolOutcome.INDETERMINATE, True, True, ActivationEffectClaim.CLAIMED),
            (ToolOutcome.SUCCEEDED, True, True, ActivationEffectClaim.CLAIMED),
            (None, False, True, ActivationEffectClaim.ALREADY_DONE),
            (ToolOutcome.INDETERMINATE, False, True, ActivationEffectClaim.ALREADY_DONE),
            (ToolOutcome.SUCCEEDED, False, True, ActivationEffectClaim.ALREADY_DONE),
            (None, True, False, ActivationEffectClaim.ALREADY_DONE),
            (ToolOutcome.INDETERMINATE, True, False, ActivationEffectClaim.ALREADY_DONE),
        ],
        ids=[
            "unwritten-deliberate-approved",
            "unknown-deliberate-approved",
            "done-deliberate-approved",
            "unwritten-approved-not-deliberate",
            "unknown-approved-not-deliberate",
            "done-approved-not-deliberate",
            "unwritten-deliberate-not-approved",
            "unknown-deliberate-not-approved",
        ],
    )
    async def test_a_deliberate_repeat_under_an_approval_passes_an_unknown_outcome(
        self,
        store: PlanStore,
        outcome: ToolOutcome | None,
        deliberate: bool,
        under_approval: bool,
        expected: ActivationEffectClaim,
    ) -> None:
        """§6:2: the claim of a deliberate repeat that runs under an approval passes a
        matching effect whose outcome is unknown or not yet written; every other claim
        matches as ADR-0306 §5:9-§5:11 decide."""
        await store.claim_activation_effect(_effect("e1"), match=None)
        if outcome is not None:
            await store.finish_activation_effect("e1", outcome)
        retry = _spending("e2") if under_approval else _effect("e2", activation="act-2")

        answer = await store.claim_activation_effect(
            retry, match=("act-2", "act-1"), deliberate_repeat=deliberate
        )

        assert answer is expected

    async def test_the_records_are_read_by_part_across_activations_in_claim_order(
        self, store: PlanStore
    ) -> None:
        """§4:4, §4:11: whether a part's key is carried, read across every activation."""
        first = QuestionPart(round="q-round", part=1)
        second = QuestionPart(round="q-round", part=2)
        other = QuestionPart(round="q-other", part=1)
        await store.claim_activation_effect(
            _spending("e2", activation="act-7", part=second), match=None
        )
        await store.claim_activation_effect(_effect("e0"), match=None)
        await store.claim_activation_effect(_message("m0"), match=None)
        await store.claim_activation_effect(
            _spending("e1", activation="act-8", part=first, values="b" * 64), match=None
        )
        await store.claim_activation_effect(
            _spending("e3", part=other, values="c" * 64), match=None
        )
        await store.finish_activation_effect("e1", ToolOutcome.INDETERMINATE)

        read = await store.part_effects([first, second])

        assert [one.id for one in read] == ["e2", "e1"]
        assert read[1].outcome is ToolOutcome.INDETERMINATE
        assert read[1].part == first
        assert await store.part_effects([]) == ()
        assert await store.part_effects([QuestionPart(round="q-none", part=1)]) == ()
        assert [one.id for one in await store.part_effects((first, first))] == ["e1"]

    async def test_the_read_by_part_answers_however_many_parts_it_names(
        self, store: PlanStore
    ) -> None:
        """§4:9: a read naming more parts than SQLite binds is answered whole (#3301).

        In claim order across the whole read, whatever the parts' places in it: the
        first record claimed spends the last part named, the second the first, and the
        fourth one from the middle, while the third spends a part the read does not name.
        """
        named = [QuestionPart(round="q-round", part=one) for one in range(1, _PAST_SQLITES_BOUND)]
        await store.claim_activation_effect(
            _spending("e1", activation="act-1", part=named[-1]), match=None
        )
        await store.claim_activation_effect(
            _spending("e2", activation="act-2", part=named[0]), match=None
        )
        await store.claim_activation_effect(
            _spending("e3", activation="act-3", part=QuestionPart(round="q-other", part=1)),
            match=None,
        )
        await store.claim_activation_effect(
            _spending("e4", activation="act-4", part=named[len(named) // 2]), match=None
        )

        read = await store.part_effects(named)

        assert [one.id for one in read] == ["e1", "e2", "e4"]

    @pytest.mark.parametrize(
        "given",
        [
            pytest.param("q-round", id="a-bare-string"),
            pytest.param([("q-round", 1)], id="a-tuple-not-a-part"),
            pytest.param([{"round": "q-round", "part": 1}], id="a-mapping-not-a-part"),
        ],
    )
    async def test_the_read_by_part_takes_question_parts_alone(
        self, store: PlanStore, given: object
    ) -> None:
        """A read handed anything but ``QuestionPart`` values is refused, not guessed at."""
        with pytest.raises(PlanningError):
            await store.part_effects(given)  # type: ignore[arg-type]  # refused input

    async def test_the_export_carries_the_part_a_record_spent(self, store: PlanStore) -> None:
        """§4:9: the part key is a field of the record, so the export carries it."""
        await store.claim_activation_effect(_spending("e1"), match=None)

        (exported,) = (await store.export()).activation_effects

        assert exported.part == QuestionPart(round="q-round", part=1)

    async def test_a_finish_writes_the_outcome_once(self, store: PlanStore) -> None:
        """§6:4: the outcome and the reason where not done are written once."""
        await store.claim_activation_effect(_effect("e1"), match=None)

        await store.finish_activation_effect("e1", ToolOutcome.FAILED, reason="refused")

        (held,) = await store.activation_effects(["act-1"])
        assert (held.outcome, held.reason) == (ToolOutcome.FAILED, "refused")
        with pytest.raises(PlanningError):
            await store.finish_activation_effect("e1", ToolOutcome.SUCCEEDED)
        assert (await store.activation_effects(["act-1"])) == (held,)

    async def test_a_finish_of_an_unheld_record_is_refused(self, store: PlanStore) -> None:
        """§6:4: a record the store does not hold is refused, writing nothing."""
        with pytest.raises(PlanningError):
            await store.finish_activation_effect("e1", ToolOutcome.SUCCEEDED)

        assert (await store.export()).activation_effects == ()

    @pytest.mark.parametrize(
        "effect_id", ["", "   ", "\ud800"], ids=["empty", "whitespace", "lone-surrogate"]
    )
    async def test_a_finish_refuses_an_effect_id_that_is_no_identifier(
        self, store: PlanStore, effect_id: str
    ) -> None:
        """§6:4: a value that is not an identifier names no record, and is refused as input.

        The Protocol's ``Raises:`` names this refusal (issue #3373). The refusal is
        ``planning``'s own error, and it writes nothing: the record already claimed
        stays claimed and unfinished.
        """
        record = _effect("e1")
        await store.claim_activation_effect(record, match=None)

        with pytest.raises(PlanningError):
            await store.finish_activation_effect(effect_id, ToolOutcome.SUCCEEDED)

        assert (await store.export()).activation_effects == (record,)

    @pytest.mark.parametrize(
        "outcome", [ToolOutcome.SUCCEEDED, ToolOutcome.INDETERMINATE], ids=["done", "unknown"]
    )
    async def test_a_reason_rides_only_on_not_done(
        self, store: PlanStore, outcome: ToolOutcome
    ) -> None:
        """§6:4: a reason on an outcome other than not done is refused, writing nothing."""
        await store.claim_activation_effect(_effect("e1"), match=None)

        with pytest.raises(PlanningError):
            await store.finish_activation_effect("e1", outcome, reason="because")

        (held,) = await store.activation_effects(["act-1"])
        assert held.outcome is None

    @pytest.mark.parametrize(
        "reason", ["", "   ", "\ud800"], ids=["empty", "whitespace", "lone-surrogate"]
    )
    async def test_a_reason_that_is_blank_or_unencodable_is_refused(
        self, store: PlanStore, reason: str
    ) -> None:
        """§6:4: a blank reason, or one with no UTF-8 encoding, is refused, writing nothing.

        The Protocol's ``Raises:`` names this refusal, and a record's reason is
        ``NonBlankEncodableText``, so no store may write such a reason through
        (issue #3326). The record stays claimed and unfinished, so a finish with a
        reason it can hold still lands afterwards.
        """
        record = _effect("e1")
        await store.claim_activation_effect(record, match=None)

        with pytest.raises(PlanningError):
            await store.finish_activation_effect("e1", ToolOutcome.FAILED, reason=reason)

        assert await store.activation_effects(["act-1"]) == (record,)
        await store.finish_activation_effect("e1", ToolOutcome.FAILED, reason="refused")
        (held,) = await store.activation_effects(["act-1"])
        assert (held.outcome, held.reason) == (ToolOutcome.FAILED, "refused")

    async def test_a_position_rides_only_on_a_message_done(self, store: PlanStore) -> None:
        """§6:4: a position on a call, or on a message not done, is refused."""
        await store.claim_activation_effect(_effect("e1"), match=None)
        await store.claim_activation_effect(_message("m1"), match=None)

        with pytest.raises(PlanningError):
            await store.finish_activation_effect("e1", ToolOutcome.SUCCEEDED, position=3)
        with pytest.raises(PlanningError):
            await store.finish_activation_effect("m1", ToolOutcome.FAILED, position=3)
        assert all(one.outcome is None for one in await store.activation_effects(["act-1"]))

        await store.finish_activation_effect("m1", ToolOutcome.SUCCEEDED, position=3)

        message = (await store.activation_effects(["act-1"]))[1]
        assert (message.outcome, message.position) == (ToolOutcome.SUCCEEDED, 3)

    async def test_the_records_are_read_by_activation_in_claim_order(
        self, store: PlanStore
    ) -> None:
        """§6:5: the named activations' records, finished or not, in claim order."""
        await store.claim_activation_effect(_effect("e3", activation="act-2"), match=None)
        await store.claim_activation_effect(_effect("e1"), match=None)
        await store.claim_activation_effect(_effect("e2", activation="act-3"), match=None)
        await store.finish_activation_effect("e1", ToolOutcome.SUCCEEDED)

        read = await store.activation_effects(["act-1", "act-2"])

        assert [one.id for one in read] == ["e3", "e1"]
        assert read[1].outcome is ToolOutcome.SUCCEEDED
        assert await store.activation_effects([]) == ()
        assert await store.activation_effects(["act-unknown"]) == ()

    async def test_a_bare_string_is_not_a_sequence_of_activations(self, store: PlanStore) -> None:
        """A single id passed unwrapped would read each of its characters; refused."""
        with pytest.raises(PlanningError):
            await store.activation_effects("act-1")

    async def test_the_read_by_activation_takes_strings_alone(self, store: PlanStore) -> None:
        """A read naming anything but a string is refused, not matched against nothing."""
        await store.claim_activation_effect(_effect("e1"), match=None)

        with pytest.raises(PlanningError):
            await store.activation_effects(["act-1", 1])  # type: ignore[list-item]  # the refusal under test

    @pytest.mark.parametrize(
        "activations",
        [
            lambda: 5,
            lambda: (one for one in ["act-1"]),
            lambda: iter(["act-1"]),
            lambda: {"act-1"},
            lambda: {"act-1": None},
            lambda: b"act-1",
        ],
        ids=["not-iterable", "generator", "iterator", "set", "mapping", "bytes"],
    )
    async def test_the_read_by_activation_takes_a_sequence_of_activations(
        self, store: PlanStore, activations: Callable[[], object]
    ) -> None:
        """Anything but a sequence of ids is refused as a ``PlanningError`` (issue #3295).

        A value that is not iterable would otherwise escape as ``TypeError``, and a
        one-shot iterable would be exhausted by the check and then read nothing, so the
        store would answer ``()`` whatever it holds. A record is held here so that an
        empty answer could not pass for a refusal.
        """
        await store.claim_activation_effect(_effect("e1"), match=None)

        with pytest.raises(PlanningError):
            await store.activation_effects(activations())  # type: ignore[arg-type]  # the refusal under test

    async def test_the_read_by_activation_answers_however_many_it_names(
        self, store: PlanStore
    ) -> None:
        """A read naming more activations than SQLite binds is answered whole (#3296).

        In claim order across the whole read, whatever the ids' places in it: the
        first record claimed names the last activation, and the second the first.
        """
        named = [f"act-{index}" for index in range(_PAST_SQLITES_BOUND)]
        await store.claim_activation_effect(_effect("e1", activation=named[-1]), match=None)
        await store.claim_activation_effect(_effect("e2", activation=named[0]), match=None)
        await store.claim_activation_effect(_effect("e3", activation="act-unnamed"), match=None)
        await store.claim_activation_effect(
            _effect("e4", activation=named[len(named) // 2]), match=None
        )

        read = await store.activation_effects(named)

        assert [one.id for one in read] == ["e1", "e2", "e4"]

    @pytest.mark.parametrize(
        "activations",
        [["\ud800"], ["act-1", "act-\udfff"]],
        ids=["lone-surrogate", "after-a-valid-id"],
    )
    async def test_the_read_by_activation_refuses_an_id_with_no_utf8_encoding(
        self, store: PlanStore, activations: list[str]
    ) -> None:
        """An id no store could hold is refused as a ``PlanningError`` (issue #3291).

        A record's activation is an identifier, so the id names nothing; but a SQLite
        store cannot bind it, and its driver's ``UnicodeEncodeError`` would otherwise
        escape as something other than the error the Protocol raises. Every store
        refuses it alike, whatever it holds.
        """
        await store.claim_activation_effect(_effect("e1"), match=None)

        with pytest.raises(PlanningError, match="index"):
            await store.activation_effects(activations)

    async def test_the_export_carries_the_records_and_clear_erases_them(
        self, store: PlanStore
    ) -> None:
        """§6's ``PlanExport.activation_effects``; ``clear`` erases them with the rest."""
        await store.claim_activation_effect(_effect("e1"), match=None)
        await store.claim_activation_effect(_message("m1"), match=None)
        await store.finish_activation_effect("e1", ToolOutcome.SUCCEEDED)

        export = await store.export()
        assert export.schema_version == 26
        assert [one.id for one in export.activation_effects] == ["e1", "m1"]
        assert type(export).model_validate_json(export.model_dump_json()) == export

        assert await store.clear() == 2
        assert (await store.export()).activation_effects == ()

    async def test_an_exported_record_cannot_edit_stored_state(self, store: PlanStore) -> None:
        """An export is a snapshot: a record edited in it reaches nothing stored."""
        await store.claim_activation_effect(_effect("e1"), match=None)

        export = await store.export()
        export.activation_effects[0].__dict__["capability"] = "tampered"

        assert (await store.activation_effects(["act-1"]))[0].capability == "book_stay"
        assert (await store.export()).activation_effects[0].capability == "book_stay"

    # --- ADR-0329 §16: the observation record ------------------------------

    async def test_a_first_write_stores_the_record_whole_at_a_fresh_revision(
        self, store: PlanStore
    ) -> None:
        """§16:9: the record is written whole, and the store stamps its revision."""
        record = _observation().model_copy(update={"revision": 999})

        stored = await store.write_observation(record, expected_revision=0)

        assert stored.revision > 0
        assert stored.revision != 999, "a submitted revision is discarded"
        assert stored == record.model_copy(update={"revision": stored.revision})
        assert await store.observations([record.episode]) == (stored,)

    async def test_a_store_holding_none_reads_no_record(self, store: PlanStore) -> None:
        """An episode never attempted has no record, and the read says so by omission."""
        assert await store.observations(["activation:never"]) == ()
        assert await store.observations([]) == ()

    async def test_a_write_under_the_held_revision_replaces_the_record(
        self, store: PlanStore
    ) -> None:
        """The writer's expectation met: the new record lands at a new revision."""
        waiting = await store.write_observation(
            _observation(state=ObservationState.WAITING), expected_revision=0
        )

        processed = await store.write_observation(
            _observation(), expected_revision=waiting.revision
        )

        assert processed.revision not in {0, waiting.revision}
        assert processed.state is ObservationState.PROCESSED
        assert await store.observations([processed.episode]) == (processed,)

    @pytest.mark.parametrize(
        "expectation",
        ["none-where-one-is-held", "a-stale-revision", "one-where-none-is-held"],
    )
    async def test_a_write_whose_expectation_does_not_hold_writes_nothing(
        self, store: PlanStore, expectation: str
    ) -> None:
        """§16:6's backstop: a writer that read another state lands nothing."""
        held = await store.write_observation(
            _observation(state=ObservationState.WAITING), expected_revision=0
        )
        episode, expected = {
            "none-where-one-is-held": (held.episode, 0),
            "a-stale-revision": (held.episode, held.revision + 1),
            "one-where-none-is-held": ("activation:other", held.revision),
        }[expectation]

        with pytest.raises(PlanningError):
            await store.write_observation(_observation(episode), expected_revision=expected)

        assert await store.observations([held.episode, "activation:other"]) == (held,)

    async def test_two_writes_on_one_expectation_admit_one(self, store: PlanStore) -> None:
        """Two writers that read one state: exactly one lands, the other is refused."""
        held = await store.write_observation(
            _observation(state=ObservationState.WAITING), expected_revision=0
        )

        results = await asyncio.gather(
            store.write_observation(_observation(), expected_revision=held.revision),
            store.write_observation(
                _observation(state=ObservationState.STUCK), expected_revision=held.revision
            ),
            return_exceptions=True,
        )

        landed = [one for one in results if isinstance(one, ObservationRecord)]
        refused = [one for one in results if isinstance(one, PlanningError)]
        assert len(landed) == 1
        assert len(refused) == 1
        assert await store.observations([held.episode]) == (landed[0],)

    async def test_no_revision_is_issued_twice_across_a_clear(self, store: PlanStore) -> None:
        """A clear erases the records and keeps the issuer, so a stale read stays stale."""
        before = await store.write_observation(_observation(), expected_revision=0)
        await store.clear()

        after = await store.write_observation(_observation(), expected_revision=0)

        assert after.revision != before.revision
        with pytest.raises(PlanningError):
            await store.write_observation(_observation(), expected_revision=before.revision)

    async def test_revisions_differ_across_episodes(self, store: PlanStore) -> None:
        """The issuer is the store's, not a per-episode count."""
        one = await store.write_observation(_observation("activation:a"), expected_revision=0)
        two = await store.write_observation(_observation("activation:b"), expected_revision=0)

        assert one.revision != two.revision

    async def test_the_read_answers_in_the_order_named_each_once(self, store: PlanStore) -> None:
        """Records come back in the order their episodes are named, and a repeat once."""
        a = await store.write_observation(_observation("activation:a"), expected_revision=0)
        b = await store.write_observation(_observation("activation:b"), expected_revision=0)

        read = await store.observations(
            ["activation:b", "activation:none", "activation:a", "activation:b"]
        )

        assert read == (b, a)

    async def test_the_read_answers_however_many_episodes_it_names(self, store: PlanStore) -> None:
        """The observer may ask after every due episode at once: no count is refused."""
        held = await store.write_observation(_observation("activation:2999"), expected_revision=0)
        named = [f"activation:{index}" for index in range(3000)]

        assert await store.observations(named) == (held,)

    @pytest.mark.parametrize(
        "episodes", ["activation:a", [1], b"activation:a"], ids=["str", "not-str", "bytes"]
    )
    async def test_the_read_takes_a_sequence_of_episode_ids(
        self, store: PlanStore, episodes: object
    ) -> None:
        """A bare string is not a sequence of episode ids, and nor is anything else."""
        with pytest.raises(PlanningError):
            await store.observations(episodes)  # type: ignore[arg-type]  # the refusal under test

    @pytest.mark.parametrize(
        "episodes",
        [["\ud800"], ["activation:a", "activation:\udfff"]],
        ids=["lone-surrogate", "after-a-valid-id"],
    )
    async def test_the_read_refuses_an_episode_id_with_no_utf8_encoding(
        self, store: PlanStore, episodes: list[str]
    ) -> None:
        """An id no store could hold is refused as a ``PlanningError`` (issue #3191).

        A record's episode is encodable text, so the id names nothing; but a SQLite
        store cannot bind it, and its driver's ``UnicodeEncodeError`` would otherwise
        escape as something other than the error the Protocol raises. Every store
        refuses it alike, whatever it holds.
        """
        await store.write_observation(_observation("activation:a"), expected_revision=0)

        with pytest.raises(PlanningError, match="index"):
            await store.observations(episodes)

    @pytest.mark.parametrize(
        "record",
        [
            "not a record",
            ObservationRecord.model_construct(episode="", state=ObservationState.PROCESSED),
        ],
        ids=["not-a-record", "unvalidated"],
    )
    async def test_a_write_of_no_valid_record_is_refused(
        self, store: PlanStore, record: object
    ) -> None:
        """The record is validated, not trusted, and nothing is written."""
        with pytest.raises(PlanningError):
            await store.write_observation(record, expected_revision=0)  # type: ignore[arg-type]  # the refusal under test

        assert (await store.export()).observations == ()

    @pytest.mark.parametrize("expected", [-1, True, "0", None])
    async def test_a_write_takes_a_revision_as_its_expectation(
        self, store: PlanStore, expected: object
    ) -> None:
        """``expected_revision`` is 0 or an issued revision, and nothing else."""
        with pytest.raises(PlanningError):
            await store.write_observation(_observation(), expected_revision=expected)  # type: ignore[arg-type]  # the refusal under test

        assert (await store.export()).observations == ()

    async def test_the_budget_counts_every_call_at_or_after_the_instant(
        self, store: PlanStore
    ) -> None:
        """§16:9: the calls each attempt made, across records, from ``since`` inclusive."""
        later = _WHEN + timedelta(hours=1)
        await store.write_observation(
            _observation("activation:a", calls=(_WHEN, later)), expected_revision=0
        )
        await store.write_observation(
            _observation(
                "activation:b",
                calls=(later, later + timedelta(seconds=1)),
                state=ObservationState.WAITING,
            ),
            expected_revision=0,
        )
        await store.write_observation(
            ObservationRecord(episode="activation:c", state=ObservationState.SKIPPED),
            expected_revision=0,
        )

        assert await store.observer_calls_since(_WHEN) == 4
        assert await store.observer_calls_since(later) == 3
        assert await store.observer_calls_since(later + timedelta(microseconds=1)) == 1
        assert await store.observer_calls_since(later + timedelta(days=1)) == 0

    async def test_a_rewritten_record_counts_only_the_calls_it_now_holds(
        self, store: PlanStore
    ) -> None:
        """The count reads the records as they stand, not every write ever made."""
        held = await store.write_observation(
            _observation(calls=(_WHEN, _WHEN + timedelta(hours=2))), expected_revision=0
        )
        await store.write_observation(_observation(calls=(_WHEN,)), expected_revision=held.revision)

        assert await store.observer_calls_since(_WHEN + timedelta(hours=1)) == 0
        assert await store.observer_calls_since(_WHEN) == 1

    @pytest.mark.parametrize(
        "since",
        [_WHEN.replace(tzinfo=None), "2026-01-01T00:00:00Z", None],
        ids=["naive", "text", "none"],
    )
    async def test_the_budget_counts_from_an_aware_instant(
        self, store: PlanStore, since: object
    ) -> None:
        """A naive instant names no moment, so the count refuses it."""
        with pytest.raises(PlanningError):
            await store.observer_calls_since(since)  # type: ignore[arg-type]  # the refusal under test

    async def test_the_export_carries_the_observations_and_clear_erases_them(
        self, store: PlanStore
    ) -> None:
        """§16:9: the export carries every record by episode id; clear erases and counts them."""
        b = await store.write_observation(_observation("activation:b"), expected_revision=0)
        a = await store.write_observation(_observation("activation:a"), expected_revision=0)
        await store.record_stop("act-stopped")

        export = await store.export()
        assert export.schema_version == 26
        assert export.observations == (a, b)
        assert type(export).model_validate_json(export.model_dump_json()) == export

        assert await store.clear() == 3
        assert (await store.export()).observations == ()
        assert await store.observations(["activation:a", "activation:b"]) == ()
        assert await store.observer_calls_since(_WHEN) == 0

    async def test_a_findings_carry_between_attempts_is_stored_and_read_back_whole(
        self, store: PlanStore
    ) -> None:
        """§12:6, §16:4: a pending finding's supply and partial writes survive the store.

        What the observer needs to commit a finding in a later attempt — the placement
        meet of what it was supplied and what a failed commit wrote — is on the record,
        so a store that kept the record whole keeps them for a process that never saw
        the earlier attempt, and the export carries them (ADR-0004 §6).
        """
        narrowed = Placement(
            reach=PlacementReach.OWNER, set_by=PlacementSetter.DERIVED, set_at=_WHEN
        )
        base = _observation(state=ObservationState.WAITING)
        first, pending = base.findings
        carried = pending.model_copy(
            update={
                "supply": narrowed,
                "written": (
                    ObservationWrite(
                        memory="memory-partial",
                        operations=(
                            MemoryOperationKind.CREATE,
                            MemoryOperationKind.RAISE_QUESTION,
                        ),
                    ),
                ),
            }
        )
        record = ObservationRecord.model_validate(
            {
                **base.model_dump(),
                "findings": (first.model_copy(update={"supply": narrowed}), carried),
            }
        )

        stored = await store.write_observation(record, expected_revision=0)

        (read,) = await store.observations([record.episode])
        assert read == stored == record.model_copy(update={"revision": stored.revision})
        assert read.findings[1].supply == narrowed
        assert read.findings[1].written == carried.written
        export = await store.export()
        assert export.observations == (stored,)
        assert type(export).model_validate_json(export.model_dump_json()) == export

    async def test_a_finding_with_no_carry_reads_back_with_none(self, store: PlanStore) -> None:
        """A finding written with no supply reads back with none: never the empty meet."""
        stored = await store.write_observation(
            _observation(state=ObservationState.WAITING), expected_revision=0
        )

        (read,) = await store.observations([stored.episode])
        assert [one.supply for one in read.findings] == [None, None]
        assert [one.written for one in read.findings] == [(), ()]

    async def test_a_record_read_or_returned_cannot_edit_stored_state(
        self, store: PlanStore
    ) -> None:
        """Every record handed out is a snapshot, the write's own answer included."""
        stored = await store.write_observation(_observation(), expected_revision=0)
        stored.__dict__["state"] = ObservationState.STUCK
        (read,) = await store.observations([stored.episode])
        read.__dict__["state"] = ObservationState.STUCK
        (await store.export()).observations[0].__dict__["state"] = ObservationState.STUCK

        (again,) = await store.observations([stored.episode])
        assert again.state is ObservationState.PROCESSED

    async def test_a_record_handed_in_cannot_edit_what_was_written(self, store: PlanStore) -> None:
        """The store writes its own copy of the record it was handed."""
        record = _observation()
        stored = await store.write_observation(record, expected_revision=0)
        record.__dict__["state"] = ObservationState.STUCK

        assert (await store.observations([stored.episode]))[0].state is ObservationState.PROCESSED

    # --- ADR-0350: the Task Scheduler's scheduled tasks --------------------

    async def test_a_spawn_writes_its_task_and_claims_its_effect_in_one_step(
        self, store: PlanStore
    ) -> None:
        """§3:3: the task and the spawn's effect record, written together.

        The store authors the parent, the chain length and the one pending occurrence,
        due at the instant it was set for a task due now (§5:1, §9:7).
        """
        task = await _written(store, "t1", spawner="act-1", places=(_LINE,))

        assert task.parent == "act-1"
        assert task.chain_length == 1
        assert task.places == (_LINE,)
        (occurrence,) = task.occurrences
        assert occurrence.state is OccurrenceState.PENDING
        assert occurrence.due_at == _WHEN
        assert occurrence.pushes == 0
        assert await _held(store, "t1") == task
        (effect,) = await store.activation_effects(["act-1"])
        assert effect.id == "spawn-t1"
        assert effect.outcome is None

    async def test_a_task_due_at_an_instant_falls_due_at_it(self, store: PlanStore) -> None:
        """§5:1-§5:2: the instant is stored as given, in UTC."""
        at = _WHEN + timedelta(hours=8)

        task = await _written(store, "t1", when=DueAt(at=at))

        assert task.occurrences[0].due_at == at

    async def test_a_stopped_spawner_writes_neither_the_task_nor_its_effect(
        self, store: PlanStore
    ) -> None:
        """§3:3: the store refuses a stopped activation's spawn, writing nothing."""
        await store.record_stop("act-1")

        with pytest.raises(ClaimStopped):
            await _write(store, "t1", spawner="act-1")

        assert await store.scheduled_tasks(["t1"]) == ()
        assert await store.activation_effects(["act-1"]) == ()

    async def test_the_backstop_refuses_the_same_spawn_twice_and_writes_nothing(
        self, store: PlanStore
    ) -> None:
        """§4:3, ADR-0306 §5:9: a spawn is not safe to repeat, so the backstop matches it."""
        effect = _spawn_effect("spawn-first")
        await store.write_scheduled_task(
            _spawn("t1"), effect, match=None, chain_limit=_CHAIN_LIMIT, pending_limit=_PENDING_LIMIT
        )
        repeat = effect.model_copy(update={"id": "spawn-again"})

        answer = await store.write_scheduled_task(
            _spawn("t2"),
            repeat,
            match=("act-1",),
            chain_limit=_CHAIN_LIMIT,
            pending_limit=_PENDING_LIMIT,
        )

        assert answer.answer is TaskWriteAnswer.ALREADY_DONE
        assert answer.task is None
        assert await store.scheduled_tasks(["t2"]) == ()
        assert [one.id for one in await store.activation_effects(["act-1"])] == ["spawn-first"]

    async def test_a_held_task_id_is_refused(self, store: PlanStore) -> None:
        """A task id names one task, so a second write under it is refused whole.

        The second write carries an effect id of its own and other content, so it is the
        task id that refuses it, and the task held is the first one, unchanged.
        """
        first = await _written(store, "t1")
        again = _spawn("t1", places=(_LINE,)).model_copy(update={"instruction": "another step"})

        with pytest.raises(PlanningError):
            await store.write_scheduled_task(
                again,
                _spawn_effect("spawn-other", activation="act-2"),
                match=None,
                chain_limit=_CHAIN_LIMIT,
                pending_limit=_PENDING_LIMIT,
            )

        assert await _held(store, "t1") == first
        assert await store.activation_effects(["act-2"]) == ()

    async def test_a_spawns_effect_is_a_call(self, store: PlanStore) -> None:
        """§4:1: a spawn is a call to a capability, so a message's record is refused."""
        with pytest.raises(PlanningError):
            await store.write_scheduled_task(
                _spawn("t1"),
                _message("m1"),
                match=None,
                chain_limit=_CHAIN_LIMIT,
                pending_limit=_PENDING_LIMIT,
            )

        assert await store.scheduled_tasks(["t1"]) == ()

    @pytest.mark.parametrize("limit", [0, -1, True, 1.5])
    async def test_a_limit_is_a_positive_integer(self, store: PlanStore, limit: Any) -> None:
        """§12:5's limits are at least one, so a write naming another is refused whole."""
        with pytest.raises(PlanningError):
            await _write(store, "t1", chain_limit=limit)
        with pytest.raises(PlanningError):
            await _write(store, "t1", pending_limit=limit)

        assert await store.scheduled_tasks(["t1"]) == ()

    async def test_the_chain_length_counts_the_steps_and_the_limit_refuses_writing_nothing(
        self, store: PlanStore
    ) -> None:
        """§9:7, §9:9: one where the parent is no task's, one more than its task's otherwise."""
        await _written(store, "t1", spawner="act-0")
        await _step(store, "t1", "act-1")
        second = await _written(store, "t2", spawner="act-1", chain_limit=2)
        await _step(store, "t2", "act-2")

        refused = await _write(store, "t3", spawner="act-2", chain_limit=2)

        assert second.chain_length == 2
        assert refused.answer is TaskWriteAnswer.REFUSED
        assert refused.reason is TaskRefusal.CHAIN_LIMIT
        assert await store.scheduled_tasks(["t3"]) == ()
        assert await store.activation_effects(["act-2"]) == ()

    async def test_the_pending_limit_counts_the_persons_pending_occurrences(
        self, store: PlanStore
    ) -> None:
        """§9:8: a spawn past the person's pending limit is refused; another person's is not."""
        await _written(store, "t1", pending_limit=2)
        await _written(store, "t2", pending_limit=2, spawner="act-2")

        refused = await _write(store, "t3", pending_limit=2, spawner="act-3")
        other = await _write(store, "t4", pending_limit=2, spawner="act-4", person=_OTHER)

        assert refused.reason is TaskRefusal.PENDING_LIMIT
        assert await store.activation_effects(["act-3"]) == ()
        assert other.answer is TaskWriteAnswer.WRITTEN

    async def test_two_spawns_of_one_round_cannot_pass_the_pending_limit_together(
        self, store: PlanStore
    ) -> None:
        """§9:9: the limits are checked in the step that writes, so one of two at once lands."""
        answers = await asyncio.gather(
            _write(store, "t1", pending_limit=1, spawner="act-1"),
            _write(store, "t2", pending_limit=1, spawner="act-2"),
        )

        assert sorted(one.answer for one in answers) == [
            TaskWriteAnswer.REFUSED,
            TaskWriteAnswer.WRITTEN,
        ]
        exported = await store.export()
        assert len(exported.scheduled_tasks) == 1
        assert len(exported.activation_effects) == 1

    async def test_a_replace_cancels_the_replaced_and_takes_its_parent_places_and_chain(
        self, store: PlanStore
    ) -> None:
        """§9:4: one step cancels the replaced task's pending occurrences and writes the new.

        The new task takes the replaced one's parent and suggested places in place of
        its own, and so its chain length, whoever replaces it.
        """
        await _written(store, "t0", spawner="act-0")
        await _step(store, "t0", "act-1")
        await _written(store, "t1", spawner="act-1", places=(_LINE,))

        replacement = await _written(
            store,
            "t2",
            spawner="act-9",
            replace_any=True,
            replaces="t1",
            places=(_HUB_CHAT,),
            when=DueAt(at=_WHEN + timedelta(hours=1)),
        )

        assert await _state(store, "t1") is OccurrenceState.CANCELLED
        assert replacement.parent == "act-1"
        assert replacement.places == (_LINE,)
        assert replacement.chain_length == 2
        assert [one.id for one in await store.activation_effects(["act-9"])] == ["spawn-t2"]

    async def test_a_replace_counts_the_pending_limit_after_its_cancel(
        self, store: PlanStore
    ) -> None:
        """§9:4: the pending count is taken after the cancel, so a replace at the limit lands."""
        await _written(store, "t1", pending_limit=1)

        answer = await _write(store, "t2", pending_limit=1, replaces="t1")

        assert answer.answer is TaskWriteAnswer.WRITTEN

    @pytest.mark.parametrize(
        ("setup", "replaces", "reason"),
        [
            ("none", "t-unknown", TaskRefusal.UNKNOWN_TASK),
            ("other", "t1", TaskRefusal.ANOTHER_PERSONS),
            ("not-its", "t1", TaskRefusal.NOT_ITS_SPAWN),
            ("ended", "t1", TaskRefusal.NOTHING_PENDING),
        ],
    )
    async def test_a_replace_the_rules_do_not_allow_is_refused_writing_nothing(
        self, store: PlanStore, setup: str, replaces: str, reason: TaskRefusal
    ) -> None:
        """§4:4, §9:4: an unknown task, another person's, one not its own, or one ended."""
        if setup == "other":
            await _written(store, "t1", person=_OTHER)
        elif setup == "not-its":
            await _written(store, "t1", spawner="act-0")
        elif setup == "ended":
            await _written(store, "t1")
            await store.cancel_scheduled_task("t1")

        answer = await _write(store, "t2", replaces=replaces)

        assert answer.answer is TaskWriteAnswer.REFUSED
        assert answer.reason is reason
        assert await store.scheduled_tasks(["t2"]) == ()
        assert "spawn-t2" not in [one.id for one in await store.activation_effects(["act-1"])]

    async def test_a_replace_never_moves_a_task_past_its_wait(self, store: PlanStore) -> None:
        """§9:4, §5:4: a task waiting on tasks not all ended is replaced only with a wait on them.

        A replace due now, or waiting on fewer of them, is refused and writes nothing: the
        waiting task is still pending, and neither the replacement nor its claim is held.
        """
        await _written(store, "tA")
        await _written(store, "tB")
        await _written(store, "tW", when=DueAfterTasks(tasks=("tA", "tB")))
        before = await _held(store, "tW")

        sooner = await _write(store, "t1", replaces="tW")
        fewer = await _write(store, "t2", replaces="tW", when=DueAfterTasks(tasks=("tA",)))

        for refused in (sooner, fewer):
            assert refused.answer is TaskWriteAnswer.REFUSED
            assert refused.reason is TaskRefusal.INVALID_WAIT
        assert await _held(store, "tW") == before
        assert await store.scheduled_tasks(["t1", "t2"]) == ()
        effects = [one.id for one in await store.activation_effects(["act-1"])]
        assert "spawn-t1" not in effects
        assert "spawn-t2" not in effects

    async def test_a_replace_keeps_or_widens_the_wait_and_is_free_once_it_has_ended(
        self, store: PlanStore
    ) -> None:
        """§9:4: a wait on each unended task passes; once they have all ended, any when does."""
        await _written(store, "tA")
        await _written(store, "tB")
        await _written(store, "tW", when=DueAfterTasks(tasks=("tA", "tB")))
        await store.cancel_scheduled_task("tB")

        kept = await _write(store, "t1", replaces="tW", when=DueAfterTasks(tasks=("tA", "tB")))
        await store.cancel_scheduled_task("tA")
        later = await _write(store, "t2", replaces="t1", when=DueAt(at=_WHEN + timedelta(hours=9)))

        assert kept.answer is TaskWriteAnswer.WRITTEN
        assert later.answer is TaskWriteAnswer.WRITTEN

    async def test_a_wait_names_tasks_held_for_the_same_person(self, store: PlanStore) -> None:
        """§5:4: a wait on a task not held, or on another person's, is refused."""
        await _written(store, "t1", person=_OTHER)

        unknown = await _write(store, "t2", when=DueAfterTasks(tasks=("t-unknown",)))
        others = await _write(store, "t3", when=DueAfterTasks(tasks=("t1",)))

        assert unknown.reason is TaskRefusal.INVALID_WAIT
        assert others.reason is TaskRefusal.INVALID_WAIT

    async def test_a_task_waiting_on_named_tasks_falls_due_when_the_last_of_them_ends(
        self, store: PlanStore
    ) -> None:
        """§5:4: due at the instant the last ends, however each ends; until then, not due."""
        await _written(store, "t1")
        await _written(store, "t2")
        waiting = await _written(store, "t3", when=DueAfterTasks(tasks=("t1", "t2")))
        await _step(store, "t1", "act-a")
        await store.settle_occurrence("act-a", OccurrenceState.DONE)
        half = await _held(store, "t3")

        await store.cancel_scheduled_task("t2")

        assert waiting.occurrences[0].due_at is None
        assert half.occurrences[0].due_at is None
        ended = (await _held(store, "t2")).ended_at
        assert ended is not None
        assert (await _held(store, "t3")).occurrences[0].due_at == ended
        due = await store.due_occurrences(ended)
        assert "t3" in [one.task.id for one in due.due]

    async def test_a_wait_on_tasks_already_ended_is_due_at_once(self, store: PlanStore) -> None:
        """§5:4: at once where every task it names has ended when it is written."""
        await _written(store, "t1")
        await store.cancel_scheduled_task("t1")

        waiting = await _written(store, "t2", when=DueAfterTasks(tasks=("t1",)))

        assert waiting.occurrences[0].due_at == (await _held(store, "t1")).ended_at

    async def test_a_cancel_ends_every_pending_occurrence_and_stops_nothing(
        self, store: PlanStore
    ) -> None:
        """§9:5: pending occurrences end cancelled; a pushed one is left to run."""
        await _written(store, "t1")
        await _written(store, "t2")
        await _step(store, "t2", "act-2")

        cancelled = await store.cancel_scheduled_task("t1")
        running = await store.cancel_scheduled_task("t2")

        assert cancelled.task is not None
        assert cancelled.task.occurrences[0].state is OccurrenceState.CANCELLED
        assert cancelled.task.ended_at is not None
        assert running.reason is TaskRefusal.NOTHING_PENDING
        assert await _state(store, "t2") is OccurrenceState.PUSHED

    async def test_a_cancel_the_rules_do_not_allow_is_refused_writing_nothing(
        self, store: PlanStore
    ) -> None:
        """§4:4: another person's task, one the asker did not spawn, and an unknown one."""
        await _written(store, "t1", spawner="act-0")

        others = await store.cancel_scheduled_task("t1", person=_OTHER)
        not_its = await store.cancel_scheduled_task("t1", spawned_by="act-1")
        unknown = await store.cancel_scheduled_task("t-unknown")
        its_own = await store.cancel_scheduled_task("t1", person=_PERSON, spawned_by="act-0")

        assert others.reason is TaskRefusal.ANOTHER_PERSONS
        assert not_its.reason is TaskRefusal.NOT_ITS_SPAWN
        assert unknown.reason is TaskRefusal.UNKNOWN_TASK
        assert its_own.task is not None

    async def test_the_tasks_are_read_by_id_by_person_and_state_and_by_parent(
        self, store: PlanStore
    ) -> None:
        """§12:3's three reads, each in its order."""
        await _written(store, "t1", spawner="act-1")
        await _written(store, "t2", spawner="act-2")
        await _written(store, "t3", spawner="act-1", person=_OTHER)
        await store.cancel_scheduled_task("t2")

        by_id = await store.scheduled_tasks(["t3", "t-unknown", "t1", "t3"])
        pending = await store.person_scheduled_tasks(_PERSON, [OccurrenceState.PENDING])
        ended = await store.person_scheduled_tasks(
            _PERSON, [OccurrenceState.CANCELLED, OccurrenceState.DONE]
        )
        spawned = await store.spawned_tasks(["act-1", "act-unknown"])

        assert [one.id for one in by_id] == ["t3", "t1"]
        assert [one.id for one in pending] == ["t1"]
        assert [one.id for one in ended] == ["t2"]
        assert [one.id for one in spawned] == ["t1", "t3"]

    @pytest.mark.parametrize("ids", ["t1", ("t1",), [b"t1"], ["\ud800"]])
    async def test_a_read_by_ids_takes_a_sequence_of_encodable_strings(
        self, store: PlanStore, ids: Any
    ) -> None:
        """A bare string, a tuple of bytes and an id with no UTF-8 encoding are refused."""
        if ids == ("t1",):
            assert await store.scheduled_tasks(ids) == ()
            return
        with pytest.raises(PlanningError):
            await store.scheduled_tasks(ids)
        with pytest.raises(PlanningError):
            await store.spawned_tasks(ids)
        with pytest.raises(PlanningError):
            await store.stopped_activations(ids)

    async def test_the_lineage_runs_from_the_start_to_the_task_pushed_to_an_activation(
        self, store: PlanStore
    ) -> None:
        """§6:5: each ancestor step in order, then the current; none where none was pushed."""
        await _written(store, "t1", spawner="act-0")
        await _step(store, "t1", "act-1")
        await _written(store, "t2", spawner="act-1")
        await _step(store, "t2", "act-2")
        await store.settle_occurrence("act-1", OccurrenceState.DONE)
        await _written(store, "t3", spawner="act-2")
        await _step(store, "t3", "act-3")

        assert [one.id for one in await store.scheduled_lineage("act-3")] == ["t1", "t2", "t3"]
        assert [one.id for one in await store.scheduled_lineage("act-1")] == ["t1"]
        assert await store.scheduled_lineage("act-0") == ()

    async def test_live_below_reads_the_tasks_spawned_below_and_theirs(
        self, store: PlanStore
    ) -> None:
        """§7:8, §9:6: a grandchild pending is live below, through a child that has ended."""
        await _written(store, "t1", spawner="act-0")
        await _step(store, "t1", "act-1")
        await _written(store, "t2", spawner="act-1")
        await _step(store, "t2", "act-2")
        await _written(store, "t3", spawner="act-2")
        await store.settle_occurrence("act-2", OccurrenceState.DONE)

        assert await store.live_below("t1")
        assert not await store.live_below("t3")
        await store.cancel_scheduled_task("t3")
        assert not await store.live_below("t1")
        assert not await store.live_below("t-unknown")

    async def test_the_occurrences_due_are_each_their_own_and_the_next_is_named(
        self, store: PlanStore
    ) -> None:
        """§7:2-§7:4: every pending occurrence due at or before the instant, and the next."""
        later = _WHEN + timedelta(hours=1)
        await _written(store, "t1", when=DueAt(at=_WHEN))
        await _written(store, "t2", when=DueAt(at=_WHEN))
        await _written(store, "t3", when=DueAt(at=later))
        await _written(store, "t4", when=DueAt(at=_WHEN - timedelta(minutes=1)))
        await _step(store, "t4", "act-4")

        due = await store.due_occurrences(_WHEN)

        assert [(one.task.id, one.number) for one in due.due] == [("t1", 1), ("t2", 1)]
        assert due.next_due_at == later
        assert (await store.due_occurrences(later)).next_due_at is None

    async def test_the_due_read_compares_aware_instants(self, store: PlanStore) -> None:
        """§7:3: a naive instant is refused, never read as some zone's wall clock."""
        with pytest.raises(PlanningError):
            await store.due_occurrences(datetime(2026, 1, 1))  # noqa: DTZ001 — the naive instant refused

    async def test_a_push_marks_its_activation_once_and_whichever_lands_first_wins(
        self, store: PlanStore
    ) -> None:
        """§7:5: refused where no longer pending, so a cancel and a push never both land."""
        await _written(store, "t1")
        await _written(store, "t2")

        pushed = await store.mark_occurrence_pushed("t1", 1, "act-1")
        again = await store.mark_occurrence_pushed("t1", 1, "act-1b")
        late_cancel = await store.cancel_scheduled_task("t1")
        await store.cancel_scheduled_task("t2")
        late_push = await store.mark_occurrence_pushed("t2", 1, "act-2")
        unknown = await store.mark_occurrence_pushed("t-unknown", 1, "act-3")

        assert pushed is OccurrencePush.PUSHED
        (occurrence,) = (await _held(store, "t1")).occurrences
        assert occurrence.pushed_to == "act-1"
        assert occurrence.pushes == 1
        assert again is OccurrencePush.NOT_PENDING
        assert late_cancel.reason is TaskRefusal.NOTHING_PENDING
        assert late_push is OccurrencePush.NOT_PENDING
        assert unknown is OccurrencePush.NOT_PENDING

    async def test_a_cancel_and_a_push_at_once_admit_one(self, store: PlanStore) -> None:
        """§7:5: between a cancel and a push, whichever lands first in the store wins."""
        await _written(store, "t1")

        pushed, cancelled = await asyncio.gather(
            store.mark_occurrence_pushed("t1", 1, "act-1"), store.cancel_scheduled_task("t1")
        )

        assert (pushed is OccurrencePush.PUSHED) != (cancelled.task is not None)

    async def test_a_push_refuses_an_activation_already_pushed_and_an_unheld_occurrence(
        self, store: PlanStore
    ) -> None:
        """§7:5: an activation is pushed to once, and a task holds the occurrences it holds."""
        await _written(store, "t1")
        await _written(store, "t2")
        await _step(store, "t1", "act-1")

        with pytest.raises(PlanningError):
            await store.mark_occurrence_pushed("t2", 1, "act-1")
        with pytest.raises(PlanningError):
            await store.mark_occurrence_pushed("t2", 2, "act-2")
        with pytest.raises(PlanningError):
            await store.mark_occurrence_pushed("t2", 0, "act-2")

    async def test_a_push_below_a_stopped_activation_is_pushed(self, store: PlanStore) -> None:
        """ADR-0352 §2:3, §7:9: nothing in a task's lineage refuses its push.

        A stop record on the task's parent, and on the parent of the task above it,
        leaves the push as it is: what a stopped activation set up falls due as its when
        gives (§2:4).
        """
        await _written(store, "t1", spawner="act-0")
        await _step(store, "t1", "act-1")
        await _written(store, "t2", spawner="act-1")
        await store.settle_occurrence("act-1", OccurrenceState.STOPPED)
        await store.record_stop("act-0")
        await store.record_stop("act-1")

        assert await store.mark_occurrence_pushed("t2", 1, "act-2") is OccurrencePush.PUSHED
        assert await _state(store, "t2") is OccurrenceState.PUSHED
        assert await store.stopped_activations(["act-2"]) == ()

    @pytest.mark.parametrize(
        "outcome",
        [
            OccurrenceState.DONE,
            OccurrenceState.COULDNT_FINISH,
            OccurrenceState.STOPPED,
            OccurrenceState.INTERRUPTED,
        ],
    )
    async def test_a_settle_writes_the_outcome_with_when_it_ended(
        self, store: PlanStore, outcome: OccurrenceState
    ) -> None:
        """§7:6: the occurrence takes its outcome from how its activation ended."""
        await _written(store, "t1")
        await _step(store, "t1", "act-1")

        task = await store.settle_occurrence("act-1", outcome)

        (occurrence,) = task.occurrences
        assert occurrence.state is outcome
        assert occurrence.ended_at is not None
        assert occurrence.activations == ("act-1",)
        with pytest.raises(PlanningError):
            await store.settle_occurrence("act-1", OccurrenceState.DONE)

    async def test_a_push_again_counts_its_pushes_and_a_second_try_is_never_tried_again(
        self, store: PlanStore
    ) -> None:
        """§8:5-§8:6: pushed again it is pending; a second try is pushed once more at most."""
        await _written(store, "t1")
        await _step(store, "t1", "act-1")

        again = await store.settle_occurrence("act-1", OccurrenceState.PENDING)
        await _step(store, "t1", "act-2")
        second = await store.settle_occurrence("act-2", OccurrenceState.PENDING, second_try=True)
        retried = await _step(store, "t1", "act-3")

        assert again.occurrences[0].state is OccurrenceState.PENDING
        assert not again.occurrences[0].second_try
        assert second.occurrences[0].second_try
        assert retried.occurrences[0].activations == ("act-1", "act-2", "act-3")
        assert retried.occurrences[0].pushes == 3
        with pytest.raises(PlanningError):
            await store.settle_occurrence("act-3", OccurrenceState.PENDING)
        assert await _state(store, "t1") is OccurrenceState.PUSHED

    async def test_a_stopped_activations_occurrence_is_never_pushed_again(
        self, store: PlanStore
    ) -> None:
        """§8:1: where the store holds a stop record for it, nothing pushes it again."""
        await _written(store, "t1")
        await _step(store, "t1", "act-1")
        await store.record_stop("act-1")

        with pytest.raises(PlanningError):
            await store.settle_occurrence("act-1", OccurrenceState.PENDING)

        stopped = await store.settle_occurrence("act-1", OccurrenceState.STOPPED)
        assert stopped.occurrences[0].state is OccurrenceState.STOPPED

    async def test_a_settle_refuses_what_no_occurrence_pushed_and_no_outcome_names(
        self, store: PlanStore
    ) -> None:
        """§7:6: only a pushed occurrence settles, to an outcome or to pending alone."""
        await _written(store, "t1")
        await _step(store, "t1", "act-1")

        with pytest.raises(PlanningError):
            await store.settle_occurrence("act-unknown", OccurrenceState.DONE)
        with pytest.raises(PlanningError):
            await store.settle_occurrence("act-1", OccurrenceState.CANCELLED)
        with pytest.raises(PlanningError):
            await store.settle_occurrence("act-1", OccurrenceState.DONE, second_try=True)
        assert await _state(store, "t1") is OccurrenceState.PUSHED

    async def test_a_stop_of_a_pushed_id_writes_its_stop_record_and_no_other(
        self, store: PlanStore
    ) -> None:
        """§9:10: a pushed id's stop record is written, and an id never pushed gets none."""
        await _written(store, "t1")
        await _step(store, "t1", "act-1")

        assert await store.stop_pushed_activation("act-1")
        assert not await store.stop_pushed_activation("act-never")
        assert await store.stopped_activations(["act-never", "act-1", "act-1"]) == ("act-1",)
        with pytest.raises(ClaimStopped):
            await store.claim_activation_effect(_message("m1", activation="act-1"), match=None)

    async def test_a_confirmation_settles_a_messages_unknown_outcome_once(
        self, store: PlanStore
    ) -> None:
        """§8:11: done with its position, or not done, and nothing written is changed."""
        for one in ("m1", "m2", "m3"):
            await store.claim_activation_effect(_message(one), match=None)
        await store.finish_activation_effect("m2", ToolOutcome.INDETERMINATE)
        await store.finish_activation_effect("m3", ToolOutcome.SUCCEEDED, position=4)

        await store.confirm_message_effect("m1", delivered=True, position=7)
        await store.confirm_message_effect("m2", delivered=False)

        held = {one.id: one for one in await store.activation_effects(["act-1"])}
        assert (held["m1"].outcome, held["m1"].position) == (ToolOutcome.SUCCEEDED, 7)
        assert (held["m2"].outcome, held["m2"].position) == (ToolOutcome.FAILED, None)
        for settled in ("m1", "m2", "m3"):
            with pytest.raises(PlanningError):
                await store.confirm_message_effect(settled, delivered=True, position=1)

    async def test_a_confirmation_is_a_messages_and_carries_its_position_when_delivered(
        self, store: PlanStore
    ) -> None:
        """§8:11: a call is refused, and a position rides on a message delivered alone."""
        await store.claim_activation_effect(_effect("e1"), match=None)
        await store.claim_activation_effect(_message("m1"), match=None)

        with pytest.raises(PlanningError):
            await store.confirm_message_effect("e1", delivered=False)
        with pytest.raises(PlanningError):
            await store.confirm_message_effect("m1", delivered=True)
        with pytest.raises(PlanningError):
            await store.confirm_message_effect("m1", delivered=False, position=2)
        with pytest.raises(PlanningError):
            await store.confirm_message_effect("m-unknown", delivered=False)
        (held,) = [one for one in await store.activation_effects(["act-1"]) if one.id == "m1"]
        assert held.outcome is None

    async def test_a_task_is_removed_once_nothing_of_it_or_below_it_is_live(
        self, store: PlanStore
    ) -> None:
        """§7:8: kept while pending, pushed, live below, or waited on; removed after."""
        await _written(store, "t1", spawner="act-0")
        assert not await store.remove_scheduled_task("t1")
        await _step(store, "t1", "act-1")
        assert not await store.remove_scheduled_task("t1")
        await _written(store, "t2", spawner="act-1")
        await store.settle_occurrence("act-1", OccurrenceState.DONE)
        assert not await store.remove_scheduled_task("t1")
        await _written(store, "t3", spawner="act-x", when=DueAfterTasks(tasks=("t2",)))
        await store.cancel_scheduled_task("t2")
        assert not await store.remove_scheduled_task("t2")

        await store.cancel_scheduled_task("t3")

        assert await store.remove_scheduled_task("t1")
        assert await store.remove_scheduled_task("t3")
        assert await store.remove_scheduled_task("t2")
        assert not await store.remove_scheduled_task("t2")
        assert (await store.export()).scheduled_tasks == ()

    async def test_the_export_carries_the_schedule_and_clear_erases_it(
        self, store: PlanStore
    ) -> None:
        """§12:3: every task in the order written, and clear erases them, each counted.

        Two tasks and their two spawns' effect records are four; no cascade record is
        held to count (ADR-0352 §6:3).
        """
        await _written(store, "t2")
        await _written(store, "t1", spawner="act-2")

        exported = await store.export()
        removed = await store.clear()

        assert exported.schema_version == 26
        assert [one.id for one in exported.scheduled_tasks] == ["t2", "t1"]
        assert removed == 4
        cleared = await store.export()
        assert cleared.scheduled_tasks == ()

    async def test_a_task_read_or_returned_cannot_edit_stored_state(self, store: PlanStore) -> None:
        """A returned task is a detached snapshot, as every record here is."""
        task = await _written(store, "t1")
        task.__dict__["instruction"] = "something else"
        (read,) = await store.scheduled_tasks(["t1"])
        read.__dict__["person"] = _OTHER

        assert (await _held(store, "t1")).instruction == "do the step t1"
        assert (await _held(store, "t1")).person == _PERSON

    # --- ADR-0340: a rule ---------------------------------------------------

    async def test_a_rules_first_occurrence_is_written_with_the_task_and_its_effect(
        self, store: PlanStore
    ) -> None:
        """ADR-0340 §4:5, §9:3: at the instant its spawn carries, in the write's one step.

        The store computes no instant (§9:5): the occurrence falls due where the caller
        said, and the rule is stored whole.
        """
        rule = DueOnRule(
            repeats=TaskRuleKind.WEEKLY,
            days=(RuleDay.TUESDAY, RuleDay.THURSDAY),
            time_of_day=time(9, 30),
            zone="America/New_York",
            from_date=date(2026, 1, 5),
            until_date=date(2026, 3, 31),
        )
        task = await _rule_written(store, "t1", when=rule, first_due_at=_due(5), places=(_LINE,))

        assert task.when == rule
        assert task.author is ScheduledTaskAuthor.PERSON
        (occurrence,) = task.occurrences
        assert (occurrence.number, occurrence.state) == (1, OccurrenceState.PENDING)
        assert occurrence.due_at == _due(5)
        assert await _held(store, "t1") == task
        (effect,) = await store.activation_effects(["act-1"])
        assert (effect.id, effect.outcome) == ("spawn-t1", None)
        assert (await store.due_occurrences(_WHEN)).next_due_at == _due(5)

    async def test_a_stopped_spawner_writes_no_rule_and_no_first_occurrence(
        self, store: PlanStore
    ) -> None:
        """ADR-0340 §9:3, ADR-0350 §3:3: the first occurrence is the write's, so a refusal is."""
        await store.record_stop("act-1")

        with pytest.raises(ClaimStopped):
            await _rule_written(store, "t1")

        assert await store.scheduled_tasks(["t1"]) == ()
        assert await store.activation_effects(["act-1"]) == ()

    @pytest.mark.parametrize(
        ("when", "first"),
        [(_DAILY, None), (DueNow(), _FIRST), (DueAt(at=_FIRST), _FIRST)],
        ids=["a-rule-with-no-first-instant", "now-with-one", "an-instant-with-one"],
    )
    async def test_a_spawn_whose_first_instant_does_not_fit_its_when_is_the_callers_error(
        self, store: PlanStore, when: Any, first: datetime | None
    ) -> None:
        """ADR-0340 §9:3: refused as a ``PlanningError``, no ``TaskRefusal``, writing nothing.

        The spawn's own validation refuses it, so a caller can build one only past it.
        """
        spawn = TaskSpawn.model_construct(
            **{
                **_spawn("t1", author=ScheduledTaskAuthor.PERSON).__dict__,
                "when": when,
                "first_due_at": first,
            }
        )

        with pytest.raises(PlanningError):
            await store.write_scheduled_task(
                spawn,
                _spawn_effect("spawn-t1"),
                match=None,
                chain_limit=_CHAIN_LIMIT,
                pending_limit=_PENDING_LIMIT,
            )

        assert await store.scheduled_tasks(["t1"]) == ()
        assert await store.activation_effects(["act-1"]) == ()

    async def test_a_rule_on_a_task_the_assistant_sets_is_refused_as_not_done(
        self, store: PlanStore
    ) -> None:
        """ADR-0340 §4:1, §9:2: only a task the person set holds a rule; nothing is written.

        The spawning activation's input did not carry the person's authority, so the
        task's author would be the assistant.
        """
        answer = await _write(store, "t1", when=_DAILY, first_due_at=_FIRST)

        assert answer.answer is TaskWriteAnswer.REFUSED
        assert answer.reason is TaskRefusal.ASSISTANTS_RULE
        assert await store.scheduled_tasks(["t1"]) == ()
        assert await store.activation_effects(["act-1"]) == ()

    async def test_a_wait_never_names_a_task_with_a_rule(self, store: PlanStore) -> None:
        """ADR-0350 §5:4: a wait names one-off tasks alone, and a rule's is not one."""
        await _rule_written(store, "t-rule")
        await _written(store, "t-once")

        refused = await _write(store, "t1", when=DueAfterTasks(tasks=("t-once", "t-rule")))

        assert refused.reason is TaskRefusal.INVALID_WAIT
        assert await store.scheduled_tasks(["t1"]) == ()

    async def test_a_rules_first_push_writes_its_successor_in_the_same_step(
        self, store: PlanStore
    ) -> None:
        """ADR-0340 §4:6: no instant before the rule ends at which it has nothing pending.

        Each first push writes the next occurrence pending, at the instant the caller
        gave; an outcome writes none; and the push of the occurrence that falls on the
        until writes none, so the rule ends and the task is then removed (§4:7, ADR-0350
        §7:8).
        """
        task = await _rule_written(store, "t1", spawner="act-0")
        assert task.pending

        answer = await store.mark_occurrence_pushed(
            "t1", 1, "act-1", rule=RulePush(successor=_due(1))
        )

        assert answer is OccurrencePush.PUSHED
        held = await _held(store, "t1")
        assert [(one.number, one.state, one.due_at) for one in held.occurrences] == [
            (1, OccurrenceState.PUSHED, _FIRST),
            (2, OccurrenceState.PENDING, _due(1)),
        ]
        assert held.occurrences[0].pushed_to == "act-1"
        assert (await store.due_occurrences(_FIRST)).next_due_at == _due(1)
        settled = await store.settle_occurrence("act-1", OccurrenceState.DONE)
        assert len(settled.occurrences) == 2
        assert settled.pending

        await store.mark_occurrence_pushed("t1", 2, "act-2", rule=RulePush(successor=_due(2)))
        assert (await _held(store, "t1")).pending
        await store.mark_occurrence_pushed("t1", 3, "act-3", rule=RulePush(successor=None))
        last = await _held(store, "t1")
        assert [one.number for one in last.occurrences] == [1, 2, 3]
        assert not last.pending
        assert not await store.remove_scheduled_task("t1")
        await store.settle_occurrence("act-2", OccurrenceState.DONE)
        await store.settle_occurrence("act-3", OccurrenceState.COULDNT_FINISH)

        ended = await _held(store, "t1")
        assert len(ended.occurrences) == 3
        assert ended.ended
        assert await store.remove_scheduled_task("t1")

    async def test_a_missed_rule_records_what_it_skipped_and_pushes_the_latest(
        self, store: PlanStore
    ) -> None:
        """ADR-0340 §4:8: missed for three days, one late occurrence is pushed, two skipped.

        The pending occurrence keeps its instant and ends skipped; the one between ends
        skipped at the instant the sensor gave; the latest is pushed; and its successor
        is written pending, all in the one step. Numbers run on and are never reused
        (§4:10).
        """
        await _rule_written(store, "t1")

        answer = await store.mark_occurrence_pushed(
            "t1",
            1,
            "act-late",
            rule=RulePush(skipped=(_due(1),), latest=_due(2), successor=_due(3)),
        )

        assert answer is OccurrencePush.PUSHED
        held = await _held(store, "t1")
        assert [(one.number, one.state, one.due_at) for one in held.occurrences] == [
            (1, OccurrenceState.SKIPPED, _FIRST),
            (2, OccurrenceState.SKIPPED, _due(1)),
            (3, OccurrenceState.PUSHED, _due(2)),
            (4, OccurrenceState.PENDING, _due(3)),
        ]
        assert held.occurrences[2].activations == ("act-late",)
        assert all(one.ended_at is not None for one in held.occurrences[:2])
        assert all(not one.activations for one in held.occurrences[:2])
        assert (await store.scheduled_lineage("act-late"))[-1] == held

    async def test_a_missed_rule_whose_latest_is_its_last_writes_no_successor(
        self, store: PlanStore
    ) -> None:
        """ADR-0340 §4:7-§4:8: where the successor would fall after its until, none is written."""
        await _rule_written(store, "t1")

        await store.mark_occurrence_pushed(
            "t1", 1, "act-late", rule=RulePush(latest=_due(1), successor=None)
        )

        held = await _held(store, "t1")
        assert [one.state for one in held.occurrences] == [
            OccurrenceState.SKIPPED,
            OccurrenceState.PUSHED,
        ]
        assert not held.pending

    async def test_a_push_again_writes_no_next_occurrence_and_the_successor_is_pushed_beside(
        self, store: PlanStore
    ) -> None:
        """ADR-0340 §4:6, §4:8, §9:3: pushed again after a restart, an occurrence is itself.

        Its pushes and its second try are kept, it takes no rule's instants, and the
        successor its first push wrote stays pending, whose own first push writes the
        next. While it waits to be pushed again the rule counts two pending (§4:4's
        note on ADR-0350 §9:8).
        """
        await _rule_written(store, "t1")
        await store.mark_occurrence_pushed("t1", 1, "act-1", rule=RulePush(successor=_due(1)))
        again = await store.settle_occurrence("act-1", OccurrenceState.PENDING, second_try=True)

        assert [one.state for one in again.occurrences] == [OccurrenceState.PENDING] * 2
        assert len(again.occurrences) == 2
        with pytest.raises(PlanningError):
            await store.mark_occurrence_pushed("t1", 1, "act-1b", rule=RulePush(successor=_due(2)))
        assert await store.mark_occurrence_pushed("t1", 1, "act-1b") is OccurrencePush.PUSHED
        await store.mark_occurrence_pushed("t1", 2, "act-2", rule=RulePush(successor=_due(2)))

        held = await _held(store, "t1")
        assert [(one.number, one.state) for one in held.occurrences] == [
            (1, OccurrenceState.PUSHED),
            (2, OccurrenceState.PUSHED),
            (3, OccurrenceState.PENDING),
        ]
        assert held.occurrences[0].activations == ("act-1", "act-1b")
        assert held.occurrences[0].second_try

    async def test_a_rules_first_push_states_its_instants_and_no_other_push_does(
        self, store: PlanStore
    ) -> None:
        """ADR-0340 §9:3: each mismatch is the caller's error, and nothing is written.

        A rule's occurrence never pushed takes its successor's instant, or none where
        the rule has ended; a task with no rule takes none; and the instants given fall
        after the pending one's.
        """
        await _rule_written(store, "t-rule")
        await _written(store, "t-once")
        before = await store.export()

        with pytest.raises(PlanningError):
            await store.mark_occurrence_pushed("t-rule", 1, "act-1")
        with pytest.raises(PlanningError):
            await store.mark_occurrence_pushed(
                "t-once", 1, "act-2", rule=RulePush(successor=_due(1))
            )
        with pytest.raises(PlanningError):
            await store.mark_occurrence_pushed(
                "t-rule", 1, "act-3", rule=RulePush(successor=_FIRST)
            )
        with pytest.raises(PlanningError):
            await store.mark_occurrence_pushed(
                "t-rule", 1, "act-4", rule=RulePush(latest=_FIRST, successor=_due(1))
            )
        with pytest.raises(PlanningError):
            await store.mark_occurrence_pushed(
                "t-rule",
                1,
                "act-5",
                rule={"successor": _due(1)},  # type: ignore[arg-type]  # the store's own check
            )

        after = await store.export()
        assert after.scheduled_tasks == before.scheduled_tasks

    async def test_a_cancel_while_a_rules_occurrence_runs_cancels_the_next_and_ends_it(
        self, store: PlanStore
    ) -> None:
        """ADR-0340 §4:7, §9:3: the pending one ends cancelled and nothing is computed after.

        The running occurrence runs on, and its outcome writes no next one.
        """
        await _rule_written(store, "t1")
        await store.mark_occurrence_pushed("t1", 1, "act-1", rule=RulePush(successor=_due(1)))

        cancelled = await store.cancel_scheduled_task("t1", person=_PERSON)

        assert cancelled.task is not None
        assert [one.state for one in cancelled.task.occurrences] == [
            OccurrenceState.PUSHED,
            OccurrenceState.CANCELLED,
        ]
        assert await store.mark_occurrence_pushed("t1", 2, "act-2") is OccurrencePush.NOT_PENDING
        settled = await store.settle_occurrence("act-1", OccurrenceState.DONE)
        assert len(settled.occurrences) == 2
        assert settled.ended
        assert (await store.cancel_scheduled_task("t1")).reason is TaskRefusal.NOTHING_PENDING

    async def test_a_stop_above_a_rule_leaves_its_first_push_and_successor(
        self, store: PlanStore
    ) -> None:
        """ADR-0352 §2:5: no stop ends a rule; its first push writes what it always writes."""
        await _rule_written(store, "t1", spawner="act-0")
        await store.record_stop("act-0")

        answer = await store.mark_occurrence_pushed(
            "t1", 1, "act-1", rule=RulePush(skipped=(_due(1),), latest=_due(2), successor=_due(3))
        )

        assert answer is OccurrencePush.PUSHED
        assert [one.state for one in (await _held(store, "t1")).occurrences] == [
            OccurrenceState.SKIPPED,
            OccurrenceState.SKIPPED,
            OccurrenceState.PUSHED,
            OccurrenceState.PENDING,
        ]

    async def test_a_stop_above_a_rule_leaves_its_push_again_and_successor(
        self, store: PlanStore
    ) -> None:
        """ADR-0352 §2:4-§2:5: after a restart, what is below a stop is pushed again as any is.

        An occurrence pushed again after a restart is pending beside its successor; a
        stop record on the rule's parent refuses neither, so the push again lands and
        the successor stays pending.
        """
        await _rule_written(store, "t1", spawner="act-0")
        await store.mark_occurrence_pushed("t1", 1, "act-1", rule=RulePush(successor=_due(1)))
        await store.settle_occurrence("act-1", OccurrenceState.PENDING)
        await store.record_stop("act-0")

        answer = await store.mark_occurrence_pushed("t1", 1, "act-1b")

        assert answer is OccurrencePush.PUSHED
        held = await _held(store, "t1")
        assert [one.state for one in held.occurrences] == [
            OccurrenceState.PUSHED,
            OccurrenceState.PENDING,
        ]
        assert held.pending

    async def test_a_skip_while_a_rules_occurrence_runs_replaces_it(self, store: PlanStore) -> None:
        """ADR-0340 §5:1, §4:6: the pending next is there for a replace to reach.

        The replace, the same rule from the day after the skipped occurrence's, cancels
        the old task's pending one and writes the new one with its first occurrence, in
        one step, taking the old task's parent and places (ADR-0350 §9:4). The from is
        the caller's to compute, as the first instant is.
        """
        await _rule_written(store, "t1", spawner="act-0", places=(_LINE,))
        await store.mark_occurrence_pushed("t1", 1, "act-1", rule=RulePush(successor=_due(1)))
        skip = _DAILY.model_copy(update={"from_date": date(2026, 1, 3)})

        replaced = await _rule_written(
            store,
            "t2",
            spawner="act-chat",
            when=skip,
            first_due_at=_due(2),
            replaces="t1",
            replace_any=True,
        )

        old = await _held(store, "t1")
        assert [one.state for one in old.occurrences] == [
            OccurrenceState.PUSHED,
            OccurrenceState.CANCELLED,
        ]
        assert replaced.when == skip
        assert (replaced.parent, replaced.places) == ("act-0", (_LINE,))
        (first,) = replaced.occurrences
        assert (first.state, first.due_at) == (OccurrenceState.PENDING, _due(2))

    async def test_a_rule_counts_its_pending_occurrences_toward_the_limit(
        self, store: PlanStore
    ) -> None:
        """ADR-0340 §4's note on ADR-0350 §9:8: one pending, or two while one is pushed again."""
        await _rule_written(store, "t1")
        await store.mark_occurrence_pushed("t1", 1, "act-1", rule=RulePush(successor=_due(1)))
        assert (await _write(store, "t2", pending_limit=2)).answer is TaskWriteAnswer.WRITTEN
        await store.settle_occurrence("act-1", OccurrenceState.PENDING)

        refused = await _write(store, "t3", pending_limit=3)

        assert refused.reason is TaskRefusal.PENDING_LIMIT

    async def test_the_export_carries_a_rule_whole_and_clear_erases_it(
        self, store: PlanStore
    ) -> None:
        """ADR-0340 §9:3: every occurrence, in order, at ``schema_version`` 26 (ADR-0352 §6:3)."""
        await _rule_written(store, "t1")
        await store.mark_occurrence_pushed(
            "t1", 1, "act-1", rule=RulePush(skipped=(_due(1),), latest=_due(2), successor=_due(3))
        )
        held = await _held(store, "t1")

        exported = await store.export()
        await store.clear()

        assert exported.schema_version == 26
        assert exported.scheduled_tasks == (held,)
        assert len(exported.scheduled_tasks[0].occurrences) == 4
        assert (await store.export()).scheduled_tasks == ()

    # --- cancellation (ADR-0060) -------------------------------------------

    #: Whether this implementation acquires nothing whose safety outlives the
    #: coroutine — no connection, lock, spawned task, file handle or transaction
    #: that a ``CancelledError`` could unwind past. ``core.protocols``' clause is
    #: then vacuously satisfied and there is nothing for the case below to
    #: observe. Left ``False``, the suite requires the implementation to prove the
    #: invariant by overriding :meth:`store_suspended_mid_write` — so a new
    #: durable backend that reintroduces ADR-0054's bug fails here rather than
    #: passing a suite that never looked. Opting out is a visible declaration in
    #: the subclass.
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

    @pytest.mark.parametrize("make_op", _CANCELLATION_OPS, ids=lambda op: op().name)
    async def test_a_cancelled_operation_holds_its_resource_until_the_work_finishes(
        self, make_op: Callable[[], _CancellationOp]
    ) -> None:
        """``core.protocols``' cancellation clause, on every locked operation (ADR-0060).

        A cancelled call must not hand the resource to the next caller while the
        work it started is still using it. The second call is what makes this a
        test of the invariant rather than of propagation: a single cancelled call
        in isolation looks identical either way. Run once per locked operation, so
        a regression reintroduced at any one lock site — not just the first —
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
