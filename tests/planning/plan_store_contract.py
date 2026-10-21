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
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Protocol

import pytest

from ai_assistant.core.errors import ClaimStopped, PlanningError
from ai_assistant.core.types import (
    ActivationEffect,
    ActivationEffectClaim,
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
    Placement,
    PlacementReach,
    PlacementSetter,
    QuestionPart,
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
        assert export.schema_version == 22
        # ADR-0309 §5: the old path's sections left the document.
        assert set(export.model_dump()) == {
            "schema_version",
            "exported_at",
            "stopped_activations",
            "activation_effects",
            "observations",
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
        assert export.schema_version == 22
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
        assert export.schema_version == 22
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
