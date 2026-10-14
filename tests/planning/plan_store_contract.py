"""Shared conformance suite for the PlanStore Protocol (ADR-0014).

Every ``PlanStore`` implementation must pass this suite (CONTRIBUTING, "Protocol
conformance suites"). A concrete test subclasses :class:`PlanStoreContract` and
overrides the ``store`` fixture.

This suite matters more than most: `InMemoryPlanStore`, `SqlitePlanStore` and
`FakePlanStore` re-implement the stop record (ADR-0297 §1) and acting's effect
records (ADR-0306 §6) independently — the fake cannot import the subsystem it stands
in for — so this is what stops them drifting. It asserts only behaviour the
*contract* guarantees, never how a given store keys its ids.

It pins the members the phases use. The members ADR-0309 §5 retires are no longer
pinned here, though every store still carries them until the Protocol narrows.

Named ``*_contract`` (not ``test_*``) so pytest collects it only via a
``Test``-prefixed subclass, never the abstract base directly.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Protocol

import pytest

from ai_assistant.core.errors import ClaimStopped, PlanningError
from ai_assistant.core.types import (
    ActivationEffect,
    ActivationEffectClaim,
    ToolOutcome,
)
from ai_assistant.testing.cancellation import settle

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine
    from contextlib import AbstractAsyncContextManager

    from ai_assistant.core.protocols import PlanStore
    from ai_assistant.testing.cancellation import SuspendedMidWrite

_WHEN = datetime(2026, 1, 1, tzinfo=UTC)


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


def _message(effect_id: str, *, activation: str = "act-1") -> ActivationEffect:
    """A message's effect record as claimed, with no outcome and no position."""
    return ActivationEffect(
        id=effect_id, activation_id=activation, round="r1", place="c-1", claimed_at=_WHEN
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
        assert export.schema_version == 18
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

    async def test_the_export_carries_the_records_and_clear_erases_them(
        self, store: PlanStore
    ) -> None:
        """§6's ``PlanExport.activation_effects``; ``clear`` erases them with the rest."""
        await store.claim_activation_effect(_effect("e1"), match=None)
        await store.claim_activation_effect(_message("m1"), match=None)
        await store.finish_activation_effect("e1", ToolOutcome.SUCCEEDED)

        export = await store.export()
        assert export.schema_version == 18
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
