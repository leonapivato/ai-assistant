"""Shared conformance suites for the two routing Protocols (ADR-0197 §9, §12).

Every ``RoutingRecorder`` implementation must pass :class:`RoutingRecorderContract`,
and every ``RoutingTrail`` implementation must pass :class:`RoutingTrailContract` —
which inherits the first, because a trail *is* the recorder plus the ability to read.
A concrete test subclasses one of them and supplies its subject fixture.

**The narrow suite is bound to both fakes and to the concrete store**, which ADR-0197
§12 requires in as many words: "The shared suite for ``RoutingRecorder`` binds to
**both** fakes, as ADR-0185 §12's pair does, so the narrow seam is evidenced rather
than asserted." That claim is what lets a composition root pass one object to the
routing stage's ``RoutingRecorder`` parameter and to a ``RoutingTrail`` one, and
without those bindings it would be a sentence in an ADR rather than something the gate
checks.

**Here rather than under** ``tests/core/``. The corpus puts a suite beside the
subsystem that implements it, and ADR-0197 §9 puts the implementation in
``permissions/`` — ``audit_trail_contract.py``, ``source_read_contract.py`` and
``source_grant_contract.py`` are already here for the same reason.

**A write-only seam still has clauses, and the suite reaches them through a hook.**
``RoutingRecorder`` has one member and no way to read anything back, so
:meth:`RoutingRecorderContract.written` is how a case observes what the subject holds
— a *test author's* lever on the subject it was handed, never a member of the seam
every stage depends on.

Named ``*_contract`` (not ``test_*``) so pytest collects it only via a
``Test``-prefixed subclass, never the abstract bases directly.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Protocol

import pytest

from ai_assistant.core.errors import RoutingTrailError
from ai_assistant.core.protocols import RoutingRecorder, RoutingTrail
from ai_assistant.core.types import RoutableOperation, RouteApproval, RoutedOperationRecord
from ai_assistant.testing.cancellation import settle
from ai_assistant.testing.routing import routed_operation_record

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine
    from contextlib import AbstractAsyncContextManager

    from ai_assistant.testing.cancellation import SuspendedMidWrite

#: The route every case below is about, unless it is about two.
ROUTE = "route-1"

#: A second route, for the cases that need to tell two apart.
OTHER_ROUTE = "route-2"

#: The belief a confirm-owed row names, unless a case moves it.
SUBJECT = "belief-1"

#: The instant a row's decision was taken, unless a case moves it.
DECIDED_AT = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)

_RELEASED_EARLY = "the resource was handed over while the cancelled work was still using it"


def _owed(  # noqa: PLR0913 — a row id, a route, an operation, an approval, a subject and a conversation; each is one field a case may need to name
    record_id: str,
    *,
    route_id: str = ROUTE,
    operation: RoutableOperation = RoutableOperation.FORGET,
    approval: RouteApproval | None = None,
    subject: str | None = SUBJECT,
    conversation_id: str | None = "conversation-1",
) -> RoutedOperationRecord:
    """One coherent row, named by the caller so a case can assert on order."""
    return routed_operation_record(
        operation,
        record_id=record_id,
        route_id=route_id,
        decided_at=DECIDED_AT,
        approval=approval,
        subject=subject,
        conversation_id=conversation_id,
    )


def _read_only(record_id: str, *, route_id: str = ROUTE) -> RoutedOperationRecord:
    """One coherent read-only row — the ``NOT_OWED`` shape, which takes no subject."""
    return routed_operation_record(
        RoutableOperation.RECENT_READS,
        record_id=record_id,
        route_id=route_id,
        decided_at=DECIDED_AT,
        subject=None,
    )


async def _refuses(
    recorder: RoutingRecorder,
    written: Callable[[], Coroutine[Any, Any, list[RoutedOperationRecord]]],
    rejected: RoutedOperationRecord,
) -> None:
    """Assert ``record`` refuses ``rejected`` **and writes nothing**.

    The second half is what makes a refusal a refusal: a store that appended and *then*
    raised would be holding exactly the row the clause exists to keep out, and every
    other assertion in the case would still pass. It is also what ADR-0197 §9 rests the
    caller's contract on — "appending nothing, and the act that row precedes does not
    proceed" — so a suite that only asserted the raise would leave the half a caller
    depends on untested.
    """
    before = await written()

    with pytest.raises(RoutingTrailError):
        await recorder.record(rejected)

    assert await written() == before, "a refused write must leave no trace"


# --- the ADR-0060 cancellation cases, one per lock site ----------------------


class _CancellationOp(Protocol):
    """One ``RoutingTrail`` operation the ADR-0060 case drives.

    Each :attr:`name` selects a distinct lock site; the suite runs the same
    cancelled-first / concurrent-second scenario against every one, so a regression
    reintroduced at any single site is caught rather than only at ``record``. **Reads
    are operations too**: ADR-0060 §3 binds any method that acquires the resource, not
    any method that mutates.
    """

    name: str

    async def prepare(self, trail: RoutingTrail) -> None:
        """Establish anything the operation needs before it can run."""
        ...

    def first(self, trail: RoutingTrail) -> Coroutine[Any, Any, object]:
        """The call the case suspends inside the resource and then cancels."""
        ...

    def second(self, trail: RoutingTrail) -> Coroutine[Any, Any, object]:
        """The concurrent call barred from the resource until the first is done."""
        ...

    async def verify(self, trail: RoutingTrail) -> None:
        """Assert the resource survived: the second call is whole and reads work."""
        ...


class _RecordOp:
    """The append-only ``record`` path."""

    name = "record"

    async def prepare(self, trail: RoutingTrail) -> None:
        """No preconditions."""

    def first(self, trail: RoutingTrail) -> Coroutine[Any, Any, object]:
        """Record the row whose write is cancelled."""
        return trail.record(_owed("cancel-1"))

    def second(self, trail: RoutingTrail) -> Coroutine[Any, Any, object]:
        """Record an independent row, under a route of its own, concurrently."""
        return trail.record(_owed("cancel-2", route_id=OTHER_ROUTE))

    async def verify(self, trail: RoutingTrail) -> None:
        """The second record is durable; the first is absent-or-whole; reads work."""
        assert {held.id for held in await trail.export()} >= {"cancel-2"}


class _ClearOp:
    """The ``clear`` write, with a recorded row so it does real work."""

    name = "clear"

    async def prepare(self, trail: RoutingTrail) -> None:
        """A recorded row for ``clear`` to remove."""
        await trail.record(_owed("seed-1"))

    def first(self, trail: RoutingTrail) -> Coroutine[Any, Any, object]:
        """Clear the trail — the call that is cancelled."""
        return trail.clear()

    def second(self, trail: RoutingTrail) -> Coroutine[Any, Any, object]:
        """Clear again concurrently."""
        return trail.clear()

    async def verify(self, trail: RoutingTrail) -> None:
        """The trail is empty and still serves reads."""
        assert await trail.export() == ()


class _ReadOp:
    """A locked read, driven against a trail seeded the same way.

    Nothing is asserted about the cancelled read's answer — it has none, its task was
    cancelled — so :meth:`verify` pins the state the second call had to see, re-read
    once the scenario is over.
    """

    name = ""

    async def prepare(self, trail: RoutingTrail) -> None:
        """Seed two rows, in a known recording order."""
        await trail.record(_owed("read-1"))
        await trail.record(_read_only("read-2", route_id=OTHER_ROUTE))

    def first(self, trail: RoutingTrail) -> Coroutine[Any, Any, object]:
        """The read the case suspends inside the resource and then cancels."""
        raise NotImplementedError

    def second(self, trail: RoutingTrail) -> Coroutine[Any, Any, object]:
        """The concurrent read barred from the resource until the first is done."""
        raise NotImplementedError

    async def verify(self, trail: RoutingTrail) -> None:
        """A read cancelled mid-flight leaves the trail whole and still readable."""
        assert [held.id for held in await trail.export()] == ["read-1", "read-2"]


class _RecentOp(_ReadOp):
    """``recent`` — the bounded page, its own lock site."""

    name = "recent"

    def first(self, trail: RoutingTrail) -> Coroutine[Any, Any, object]:
        """Read the newest page — the call that is cancelled."""
        return trail.recent(limit=2)

    def second(self, trail: RoutingTrail) -> Coroutine[Any, Any, object]:
        """Read a narrower page concurrently."""
        return trail.recent(limit=1)


class _ExportOp(_ReadOp):
    """``export`` — the whole-horizon read, its own lock site."""

    name = "export"

    def first(self, trail: RoutingTrail) -> Coroutine[Any, Any, object]:
        """Export everything — the call that is cancelled."""
        return trail.export()

    def second(self, trail: RoutingTrail) -> Coroutine[Any, Any, object]:
        """Export again concurrently."""
        return trail.export()


#: Every ``RoutingTrail`` operation ADR-0060's case is run against — the two writes and
#: both reads, because §3 binds any method that acquires the resource.
_CANCELLATION_OPS: tuple[Callable[[], _CancellationOp], ...] = (
    _RecordOp,
    _ClearOp,
    _RecentOp,
    _ExportOp,
)


class RoutingRecorderContract:
    """Behaviour every ``RoutingRecorder`` implementation must exhibit.

    The clauses that bind the **write** seam, and every one of them binds a
    ``RoutingTrail`` too — which is why :class:`RoutingTrailContract` inherits rather
    than repeats them.
    """

    @pytest.fixture
    def recorder(self) -> RoutingRecorder:
        """Override in a subclass to supply the implementation under test.

        The subject must start **empty**: every case below arranges the history it is
        about, and a subject that arrived holding a row would make the ordering, state
        machine and prune cases assert against a state the case did not set up.
        """
        raise NotImplementedError

    async def written(self, recorder: RoutingRecorder) -> list[RoutedOperationRecord]:
        """Override to return what the subject holds, oldest-recorded first.

        The seam has no read member and must not grow one (ADR-0197 §9), so this is how
        a case observes an append at all. It is a lever on the *subject*, never on the
        Protocol: a fake exposes its own, and a trail answers through ``export``.
        """
        raise NotImplementedError

    def test_conforms_to_protocol(self, recorder: RoutingRecorder) -> None:
        assert isinstance(recorder, RoutingRecorder)

    async def test_record_appends_and_hands_nothing_back(self, recorder: RoutingRecorder) -> None:
        """ADR-0197 §9: ``record`` "appends one row and returns nothing".

        The id is the **caller's**, minted before the call, so there is nothing for the
        store to hand back — "a store that minted the id could not be handed a frozen
        record, and a retry could not name the row it was retrying".
        """
        # Called for its effect and typed as returning ``None``, so the assertion is
        # about the *append* rather than about a value: what §9 fixes is that the store
        # hands nothing back, and the row landing is what proves the call was a write.
        await recorder.record(_owed("r-1"))

        assert [row.id for row in await self.written(recorder)] == ["r-1"]

    async def test_a_recorded_decision_is_held(self, recorder: RoutingRecorder) -> None:
        """The row that comes back equals the one that went in."""
        appended = _owed("r-1")

        await recorder.record(appended)

        assert await self.written(recorder) == [appended]

    @pytest.mark.parametrize("operation", list(RoutableOperation))
    async def test_every_operation_is_recordable(
        self, recorder: RoutingRecorder, operation: RoutableOperation
    ) -> None:
        """All nine of §3's vocabulary, on the approval its own tag admits.

        A store that admitted only the shape its author had in mind would fail the
        first time the vocabulary was widened under §3's rule, at the site furthest
        from the widening.
        """
        row = routed_operation_record(operation, record_id="r-1", route_id=ROUTE)

        await recorder.record(row)

        assert await self.written(recorder) == [row]

    @pytest.mark.parametrize("answer", [RouteApproval.GIVEN, RouteApproval.REFUSED])
    async def test_a_confirm_owed_route_records_both_of_its_rows(
        self, recorder: RoutingRecorder, answer: RouteApproval
    ) -> None:
        """§9's two valid sequences: ``OWED``→``GIVEN`` and ``OWED``→``REFUSED``.

        Asserted beside the refusals below rather than left implied by them: a store
        that refused *every* second row under a ``route_id`` would pass every case in
        the refusal block and make a confirm-owed route unanswerable.
        """
        await recorder.record(_owed("r-1"))

        await recorder.record(_owed("r-2", approval=answer))

        held = await self.written(recorder)
        assert [(row.id, row.approval) for row in held] == [
            ("r-1", RouteApproval.OWED),
            ("r-2", answer),
        ]

    # --- idempotence, and what it is *not* over (ADR-0197 §9) --------------

    async def test_an_identical_record_is_not_appended_twice_and_is_not_an_error(
        self, recorder: RoutingRecorder
    ) -> None:
        """A retried write is idempotent — over the **whole** frozen record.

        ADR-0197 §9: "A row already present under the same ``id`` *whose every field is
        equal to the one supplied* is not appended twice and is not an error." This is
        the half that keeps a caller's retry after an ambiguous failure from filing the
        same decision twice.
        """
        row = _owed("r-1")
        await recorder.record(row)

        await recorder.record(row)

        assert await self.written(recorder) == [row]

    async def test_a_known_id_carrying_a_different_decision_is_refused(
        self, recorder: RoutingRecorder
    ) -> None:
        """Idempotence is over the record and **never over the id alone** (§9).

        The failure this store exists to make impossible: "a repeating id factory would
        otherwise let a routed ``revoke`` be performed while the trail kept only an
        earlier ``forget``'s row". The original must survive intact rather than being
        replaced, and the act the refused row preceded must not proceed — which is what
        :func:`_refuses` asserts on the caller's behalf.
        """
        await recorder.record(_owed("r-1", operation=RoutableOperation.FORGET))

        await _refuses(
            recorder,
            lambda: self.written(recorder),
            _owed("r-1", route_id=OTHER_ROUTE, operation=RoutableOperation.REVOKE, subject="mail"),
        )

        held = await self.written(recorder)
        assert [(row.id, row.operation) for row in held] == [("r-1", RoutableOperation.FORGET)]

    async def test_two_racing_writes_of_one_id_settle_it_once(
        self, recorder: RoutingRecorder
    ) -> None:
        """The atomicity clause as a race rather than as a sentence (ADR-0197 §9).

        Without atomicity over the checks and the append, both callers observe a free
        id, both append, and the trail holds one decision twice. Exactly one of the two
        must raise.
        """
        outcomes = await asyncio.gather(
            recorder.record(_owed("r-1", operation=RoutableOperation.FORGET)),
            recorder.record(_owed("r-1", operation=RoutableOperation.FORGET_QUESTION)),
            return_exceptions=True,
        )

        assert sum(outcome is None for outcome in outcomes) == 1
        assert sum(isinstance(outcome, RoutingTrailError) for outcome in outcomes) == 1
        assert len(await self.written(recorder)) == 1

    async def test_two_racing_writes_of_one_route_settle_it_once(
        self, recorder: RoutingRecorder
    ) -> None:
        """§12's atomicity case, and it is required of **every** implementation.

        "Two ``record`` calls raced with a colliding ``route_id`` and distinct row ids,
        asserting exactly one appended row and one ``RoutingTrailError``. A sequential
        test of the same pair does not satisfy this clause, because the
        check-then-append implementation it is written against passes sequentially."
        """
        outcomes = await asyncio.gather(
            recorder.record(_owed("r-1", operation=RoutableOperation.FORGET, subject="belief-a")),
            recorder.record(_owed("r-2", operation=RoutableOperation.REVOKE, subject="calendar")),
            return_exceptions=True,
        )

        assert sum(outcome is None for outcome in outcomes) == 1
        assert sum(isinstance(outcome, RoutingTrailError) for outcome in outcomes) == 1
        assert len(await self.written(recorder)) == 1

    # --- the route's state machine (ADR-0197 §9) ---------------------------

    async def test_a_route_id_held_by_a_different_route_is_refused(
        self, recorder: RoutingRecorder
    ) -> None:
        """The store's half of §9's two-ended ``route_id`` check.

        "Without the store's half a repeating id factory would file two destructive
        decisions as one route while the row-level ``id`` check passed, since the two
        rows' own ids differ."
        """
        await recorder.record(_owed("r-1", operation=RoutableOperation.FORGET))

        await _refuses(
            recorder,
            lambda: self.written(recorder),
            _owed("r-2", operation=RoutableOperation.REVOKE, subject="calendar"),
        )

    async def test_a_second_row_under_a_read_only_route_is_refused(
        self, recorder: RoutingRecorder
    ) -> None:
        """§9: "A read-only route is exactly one ``NOT_OWED`` row".

        A second row of any kind under a ``route_id`` retaining one is refused — an
        answer included, which is the arm a reader is least likely to think of.
        """
        await recorder.record(_read_only("r-1"))

        await _refuses(recorder, lambda: self.written(recorder), _read_only("r-2"))

    async def test_an_answer_under_a_read_only_route_is_refused(
        self, recorder: RoutingRecorder
    ) -> None:
        """The "an answer included" arm of the clause above, stated on its own.

        A ``GIVEN`` filed against a route the trail knows was read-only would be a
        record of the user approving something nobody asked them about.
        """
        await recorder.record(_read_only("r-1"))

        await _refuses(
            recorder,
            lambda: self.written(recorder),
            _owed("r-2", approval=RouteApproval.GIVEN),
        )

    async def test_a_second_owed_row_is_refused(self, recorder: RoutingRecorder) -> None:
        """§9: a confirm-owed route holds **at most one** ``OWED`` row.

        Two would be two questions filed as one, and a reader joining the route's rows
        could not say which of them the answer belonged to.
        """
        await recorder.record(_owed("r-1"))

        await _refuses(recorder, lambda: self.written(recorder), _owed("r-2"))

    @pytest.mark.parametrize(
        ("first", "second"),
        [
            pytest.param(RouteApproval.GIVEN, RouteApproval.REFUSED, id="refused after given"),
            pytest.param(RouteApproval.REFUSED, RouteApproval.GIVEN, id="given after refused"),
            pytest.param(RouteApproval.GIVEN, RouteApproval.GIVEN, id="a second given"),
            pytest.param(RouteApproval.REFUSED, RouteApproval.REFUSED, id="a second refused"),
        ],
    )
    async def test_a_route_is_answered_once(
        self, recorder: RoutingRecorder, first: RouteApproval, second: RouteApproval
    ) -> None:
        """§9: at most one answer per route, whatever the two answers say.

        "Without these the trail could hold a ``GIVEN`` and a ``REFUSED`` for one route
        — two incompatible claims about what one person decided — or two answers to one
        question."
        """
        await recorder.record(_owed("r-1"))
        await recorder.record(_owed("r-2", approval=first))

        await _refuses(recorder, lambda: self.written(recorder), _owed("r-3", approval=second))

    @pytest.mark.parametrize("answer", [RouteApproval.GIVEN, RouteApproval.REFUSED])
    async def test_an_answer_under_a_route_retaining_no_row_is_admitted(
        self, recorder: RoutingRecorder, answer: RouteApproval
    ) -> None:
        """§9's **admitted** case, and the one the natural wrong implementation fails.

        "A suite that only pins the refusals passes against a ``record`` that requires
        an ``OWED`` row." Requiring it would make a *retention* setting decide whether a
        user's approval of a live confirmation is honoured: pruning is by recording
        order alone, so a live park's ``OWED`` row can be pruned while the park is still
        registered and still claimable, and at a bound of one a single routed read
        between the park and the user's yes is enough. An orphan ``GIVEN`` costs an
        operator one join that finds no ``OWED``; the refusal costs the user the
        operation they had just approved.
        """
        orphan = _owed("r-1", approval=answer)

        await recorder.record(orphan)

        assert await self.written(recorder) == [orphan]

    # --- what a snapshot is (ADR-0021 §4) ----------------------------------

    @pytest.mark.parametrize(
        ("attribute", "value"),
        [
            pytest.param("decided_at", datetime(2026, 8, 27, 12, 0), id="a naive instant"),  # noqa: DTZ001
            pytest.param("route_id", "   ", id="a blank route id"),
            pytest.param("approval", RouteApproval.NOT_OWED, id="a confirm-owed row not owed"),
        ],
    )
    async def test_a_corrupted_record_is_refused_rather_than_stored(
        self, recorder: RoutingRecorder, attribute: str, value: object
    ) -> None:
        """ADR-0021 §4 asks for a *validated* snapshot, not merely a detached one.

        Detachment alone copies without checking, so an implementation that only
        deep-copies conforms to every other clause here and still accepts a record
        corrupted past its frozen model's guard. The third is the sharp one: a
        confirm-owed row carrying ``NOT_OWED`` is a destruction filed as though no
        confirmation had ever been owed for it, which is exactly what an operator would
        read the row to find out.
        """
        await recorder.record(_owed("r-1"))
        corrupted = _owed("r-2", route_id=OTHER_ROUTE)
        object.__setattr__(corrupted, attribute, value)

        await _refuses(recorder, lambda: self.written(recorder), corrupted)

        assert [row.id for row in await self.written(recorder)] == ["r-1"]

    async def test_the_stored_snapshot_is_detached_from_the_caller(
        self, recorder: RoutingRecorder
    ) -> None:
        """A caller mutating its own object past ``frozen=True`` must not move the row.

        ``frozen=True`` refuses ``row.approval = …`` and not
        ``row.__dict__["approval"] = …``, so a store retaining the caller's object would
        let an appended row be rewritten after the fact — which is the whole of what an
        append-only trail is for.
        """
        row = _owed("r-1")
        await recorder.record(row)

        object.__setattr__(row, "subject", "belief-999")

        (held,) = await self.written(recorder)
        assert held.subject == SUBJECT

    async def test_detachment_survives_a_caller_supplied_subclass(
        self, recorder: RoutingRecorder
    ) -> None:
        """A caller's subclass may not become the object the trail hands back.

        ``RoutedOperationRecord`` is a plain model, so a caller can subclass it and
        override ``model_copy`` to return ``self``. A store that snapshotted through
        ``type(record)`` would then hold that instance and hand it back from every read.
        """

        class _Sneaky(RoutedOperationRecord):
            def model_copy(self, **_kwargs: object) -> _Sneaky:
                return self

        row = _Sneaky.model_validate(_owed("r-1").model_dump())
        await recorder.record(row)

        (held,) = await self.written(recorder)
        assert held is not row
        assert type(held) is RoutedOperationRecord

    async def test_the_subject_is_stored_byte_for_byte(self, recorder: RoutingRecorder) -> None:
        """The row's ``subject`` is the identity the façade was called with (§9).

        Not a normalisation of it: a store that reshaped the scalar would make the trail
        name something the operation was never called with, which is the one fact the
        row exists to carry.
        """
        row = _owed("r-1", operation=RoutableOperation.REVOKE, subject="calendar")

        await recorder.record(row)

        (held,) = await self.written(recorder)
        assert held.subject == "calendar"


class RoutingTrailContract(RoutingRecorderContract):
    """Behaviour every ``RoutingTrail`` implementation must exhibit.

    Inherits the write seam's clauses, because a trail *is* the recorder plus the
    ability to read — ADR-0197 §9's "one concrete store satisfies them", tested rather
    than asserted.
    """

    @pytest.fixture
    def trail(self) -> RoutingTrail:
        """Return an empty trail under test."""
        raise NotImplementedError

    @pytest.fixture
    def recorder(self, trail: RoutingTrail) -> RoutingRecorder:
        """The same subject, seen through the narrow seam.

        Not a second object: the inherited clauses must bind *this* trail, which is
        ADR-0197 §9's "one concrete store satisfies them" being tested rather than
        asserted.
        """
        return trail

    async def written(self, recorder: RoutingRecorder) -> list[RoutedOperationRecord]:
        """Answer the inherited clauses through ``export``, since this subject has it."""
        assert isinstance(recorder, RoutingTrail)
        return list(await recorder.export())

    def bounded(self, max_rows: int) -> AbstractAsyncContextManager[RoutingTrail]:
        """Supply an empty trail whose cap is ``max_rows`` (ADR-0197 §9).

        Override in a subclass. The cap is a *construction* input rather than a member,
        so the only way a suite can exercise the prune at a size a test can write down
        is to be handed a differently-configured subject. It is an async context manager
        so a durable implementation can close what it opened.
        """
        raise NotImplementedError

    def test_conforms_to_both_seams(self, trail: RoutingTrail) -> None:
        """One object, two Protocols, structurally (ADR-0197 §9)."""
        assert isinstance(trail, RoutingTrail)
        assert isinstance(trail, RoutingRecorder)

    # --- ordering: recording order, and never ``decided_at`` ---------------

    async def test_export_returns_rows_in_recording_order(self, trail: RoutingTrail) -> None:
        """ADR-0197 §9: ``export`` answers "the whole trail in the same order"."""
        for index in range(3):
            await trail.record(_read_only(f"r-{index}", route_id=f"route-{index}"))

        assert [row.id for row in await trail.export()] == ["r-0", "r-1", "r-2"]

    async def test_recent_returns_rows_newest_recorded_first(self, trail: RoutingTrail) -> None:
        """ADR-0197 §9: ``recent`` answers **newest-recorded first**."""
        for index in range(3):
            await trail.record(_read_only(f"r-{index}", route_id=f"route-{index}"))

        assert [row.id for row in await trail.recent(limit=3)] == ["r-2", "r-1", "r-0"]

    async def test_the_order_is_recording_order_and_never_decided_at(
        self, trail: RoutingTrail
    ) -> None:
        """The order is the sequence of ``record`` calls, not the caller's instants.

        ``decided_at`` is caller-supplied, and a host clock corrected backwards would
        send a prune keyed on it after the rows it just wrote — ADR-0185 §6's reasoning,
        which ADR-0197 §9 inherits along with the bound. A store that sorted on the
        instant would put the second row first here.
        """
        await trail.record(
            routed_operation_record(
                RoutableOperation.RECENT_READS,
                record_id="later-instant",
                route_id="route-0",
                decided_at=datetime(2026, 8, 27, 13, 0, tzinfo=UTC),
                subject=None,
            )
        )
        await trail.record(
            routed_operation_record(
                RoutableOperation.RECENT_READS,
                record_id="earlier-instant",
                route_id="route-1",
                decided_at=datetime(2026, 8, 27, 11, 0, tzinfo=UTC),
                subject=None,
            )
        )

        assert [row.id for row in await trail.export()] == ["later-instant", "earlier-instant"]

    async def test_recent_returns_the_newest_within_the_limit(self, trail: RoutingTrail) -> None:
        """The bound is a page from the newest end, not a slice from the oldest."""
        for index in range(4):
            await trail.record(_read_only(f"r-{index}", route_id=f"route-{index}"))

        assert [row.id for row in await trail.recent(limit=2)] == ["r-3", "r-2"]

    @pytest.mark.parametrize("limit", [0, -1, 2**63])
    async def test_a_limit_outside_the_admissible_range_is_refused(
        self, trail: RoutingTrail, limit: int
    ) -> None:
        """ADR-0186 §3's rule, restated by ADR-0197 §9: ``[1, 2**63)``, locally.

        Refused rather than clamped or passed through: SQLite reads ``LIMIT -1`` as *no
        limit at all*, so the one call offering a bounded read of a Tier 1 store would
        become the unbounded read it exists to avoid — and a Python int wider than a
        signed 64-bit parameter raises ``OverflowError``, which is neither ``ValueError``
        nor ``RoutingTrailError`` and would leave the implementation's error boundary
        through a hole.
        """
        with pytest.raises(ValueError, match="limit"):
            await trail.recent(limit=limit)

    async def test_an_empty_trail_answers_emptily(self, trail: RoutingTrail) -> None:
        """No rows is an answer, not a failure."""
        assert await trail.recent(limit=5) == ()
        assert await trail.export() == ()

    async def test_a_returned_listing_is_a_detached_snapshot(self, trail: RoutingTrail) -> None:
        """ADR-0018 §3: a read hands back a copy, and mutating it moves nothing."""
        await trail.record(_owed("r-1"))

        exported = await trail.export()
        object.__setattr__(exported[0], "subject", "belief-999")

        (held,) = await trail.export()
        assert held.subject == SUBJECT

    # --- the bound (ADR-0197 §9) -------------------------------------------

    async def test_the_cap_evicts_the_earliest_recorded(self) -> None:
        """The prune, and its direction (ADR-0197 §9).

        Oldest-first, as the source-read trail's is and for its reason: a trail holds
        acts that already happened, and a store that refused new rows when full would
        make its own fullness gate the system's behaviour — under §9's refuse-to-act
        rule the assistant would stop routing altogether, reads included, because a log
        filled up.
        """
        async with self.bounded(3) as trail:
            for index in range(5):
                await trail.record(_read_only(f"r-{index}", route_id=f"route-{index}"))

            assert [row.id for row in await trail.export()] == ["r-2", "r-3", "r-4"]

    async def test_the_row_count_never_exceeds_the_cap(self) -> None:
        """Asserted after **every** append, not only at the end.

        A store that pruned on a schedule rather than inside ``record`` would leave a
        window in which it is over its cap, and an assertion taken once at the end could
        not see it.
        """
        async with self.bounded(2) as trail:
            for index in range(6):
                await trail.record(_read_only(f"r-{index}", route_id=f"route-{index}"))
                assert len(await trail.export()) <= 2

    async def test_the_prune_is_blind_to_what_the_row_says(self) -> None:
        """ADR-0197 §9: pruning "takes no account of a route's state".

        The row dropped here is the *most* interesting one the trail holds — an
        unanswered park's ``OWED`` row, the sequence an operator most wants to see — so
        an implementation that exempted it fails, and so does one that singled it out.
        Exempting it is the wrong half to move: "a bound with an exception is a bound an
        adversary chooses the shape of, and a client that opens parks and abandons them
        would pin rows the bound exists to evict".
        """
        async with self.bounded(2) as trail:
            await trail.record(_owed("owed-and-unanswered"))
            await trail.record(_read_only("read-1", route_id="route-a"))
            await trail.record(_read_only("read-2", route_id="route-b"))

            assert [row.id for row in await trail.export()] == ["read-1", "read-2"]

    async def test_a_pruned_owed_row_does_not_stop_its_answer_being_recorded(self) -> None:
        """§9's two clauses read from their two ends, in one case.

        "A pruned row costs history and never costs a resolution — which is true only
        because the state machine above admits an answer under a ``route_id`` retaining
        no row. The two clauses are one decision read from its two ends, and a lane may
        not implement one without the other." This is the case a bound and a state
        machine written in one change can each pass alone and fail together.
        """
        async with self.bounded(1) as trail:
            await trail.record(_owed("owed"))
            await trail.record(_read_only("a-routed-read", route_id="route-a"))

            await trail.record(_owed("given", approval=RouteApproval.GIVEN))

            assert [row.id for row in await trail.export()] == ["given"]

    async def test_a_full_trail_still_accepts_a_new_row(self) -> None:
        """The clause the refuse-to-act rule depends on (ADR-0197 §9).

        A store that refused at capacity, combined with §9's rule that a row which
        cannot be written stops the act it precedes, would stop the assistant routing at
        all — reads included.
        """
        async with self.bounded(1) as trail:
            await trail.record(_read_only("first", route_id="route-a"))

            await trail.record(_read_only("second", route_id="route-b"))

            assert [row.id for row in await trail.export()] == ["second"]

    @pytest.mark.parametrize("cap", [0, -1])
    async def test_a_cap_that_is_not_strictly_positive_is_refused(self, cap: int) -> None:
        """ADR-0197 §9, inheriting ADR-0185 §6: no sentinel, no ``none``, no zero.

        Zero is at capacity before its first append, and a negative cap has no meaning a
        prune could act on. The absence of an unlimited spelling is the mechanism, and a
        store accepting a non-positive cap would reintroduce the growth it removes.
        """
        with pytest.raises(ValueError, match="strictly positive"):
            async with self.bounded(cap):
                pass  # pragma: no cover — construction is the subject

    async def test_a_cap_wider_than_the_admissible_range_is_refused(self) -> None:
        """The other edge: "every strictly positive integer **below** ``2**63``".

        A durable store binds the cap as its prune's ``OFFSET`` on every append, and a
        Python int past that width raises ``OverflowError`` — neither ``ValueError`` nor
        ``RoutingTrailError``, so it leaves the implementation's error boundary through a
        hole, on the **first record** rather than at construction.
        """
        with pytest.raises(ValueError, match=r"2\*\*63"):
            async with self.bounded(2**63):
                pass  # pragma: no cover — construction is the subject

    async def test_a_cap_that_is_not_exactly_an_integer_is_refused(self) -> None:
        """``bool`` is an ``int``, so ``True`` is a cap of one wearing a flag's clothes.

        ``Settings``' own ``_exactly_an_integer`` refuses it at load; this is the same
        rule restated where the invariant is actually used, so a trail built in a test
        or from a future configuration that reads no setting cannot hold it either.
        """
        with pytest.raises(TypeError, match="exactly an int"):
            async with self.bounded(True):
                pass  # pragma: no cover — construction is the subject

    # --- erasure (ADR-0007) ------------------------------------------------

    async def test_clear_erases_everything(self, trail: RoutingTrail) -> None:
        """``clear`` destroys every row and returns nothing (ADR-0197 §9).

        Wholesale by design: the user may burn the book, and nobody may tear out a page.
        Nothing reads this trail yet, so a count would be a value with no consumer.
        """
        await trail.record(_owed("r-1"))
        await trail.record(_read_only("r-2", route_id=OTHER_ROUTE))

        await trail.clear()

        assert await trail.export() == ()

    async def test_a_cleared_trail_still_records(self, trail: RoutingTrail) -> None:
        """Erasure empties the store; it does not break it."""
        await trail.record(_owed("r-1"))
        await trail.clear()

        await trail.record(_owed("r-2"))

        assert [row.id for row in await trail.export()] == ["r-2"]

    async def test_an_exported_record_survives_a_json_round_trip(self, trail: RoutingTrail) -> None:
        """Every field a row carries crosses a serialising boundary unchanged.

        The property a durable store gets for free and an in-memory one has to keep by
        hand, asserted for both so a divergence in either direction fails.
        """
        original = _owed("r-1", operation=RoutableOperation.REVOKE, subject="calendar")
        await trail.record(original)

        (exported,) = await trail.export()
        assert RoutedOperationRecord.model_validate(exported.model_dump(mode="json")) == original

    # --- ADR-0060's cancellation clause, on every lock site ----------------

    #: Set on a subclass whose subject acquires nothing whose safety outlives the
    #: coroutine — no connection, lock, spawned task, file handle or transaction a
    #: ``CancelledError`` could unwind past. Left ``False``, the suite requires the
    #: implementation to prove the invariant by overriding
    #: :meth:`trail_suspended_mid_write`, so a durable backend that reintroduces
    #: ADR-0054's bug fails here rather than passing a suite that never looked.
    acquires_no_shared_resource: bool = False

    #: Operations this implementation acquires no coroutine-outliving resource for, even
    #: though others do. Empty by default.
    operations_without_shared_resource: frozenset[str] = frozenset()

    def trail_suspended_mid_write(
        self,
    ) -> AbstractAsyncContextManager[SuspendedMidWrite[RoutingTrail]]:
        """Supply a trail whose named operation can be stopped *inside* its resource.

        Override unless :attr:`acquires_no_shared_resource` is set. The suite cancels the
        call while it is suspended and then watches what a second caller can reach, which
        is the only way to tell the fixed code from the broken code: pre-ADR-0054 the
        audit trail raised ``CancelledError`` correctly and released the connection
        anyway, so a case that asserts only propagation certifies the bug (ADR-0060 §3).
        """
        raise NotImplementedError

    @pytest.mark.optional_obligation
    @pytest.mark.parametrize("make_op", _CANCELLATION_OPS, ids=lambda op: op().name)
    async def test_a_cancelled_operation_holds_its_resource_until_the_work_finishes(
        self, make_op: Callable[[], _CancellationOp]
    ) -> None:
        """``core.protocols``' cancellation clause, on every operation (ADR-0060).

        A cancelled call must not hand the resource to the next caller while the work it
        started is still using it. The second call is what makes this a test of the
        invariant rather than of propagation: a single cancelled call in isolation looks
        identical either way.

        The cancelled write's *effect* is deliberately not asserted. ADR-0060 makes a
        cancelled write's effect indeterminate, and ADR-0197 §9 relies on that
        indeterminacy falling on the **row** rather than on the act: the row is written
        first, so a cancellation between it and the call leaves a row for an operation
        that did not happen, which an operator can reconcile.
        """
        if self.acquires_no_shared_resource:
            pytest.skip("implementation acquires nothing whose safety outlives the coroutine")

        op = make_op()
        if op.name in self.operations_without_shared_resource:
            pytest.skip(f"{op.name} acquires nothing whose safety outlives the coroutine")

        async with self.trail_suspended_mid_write() as harness:
            trail = harness.store
            await op.prepare(trail)
            suspended = harness.arm(op.name)
            visited_before = harness.log.visits

            first = asyncio.ensure_future(op.first(trail))
            second: asyncio.Task[object] | None = None
            try:
                await suspended.reached()
                first.cancel()
                await settle()

                second = asyncio.ensure_future(op.second(trail))
                await settle()
                assert not second.done(), _RELEASED_EARLY

                # Again, because deferring one cancellation is not the contract: a
                # second delivered while the deferred wait runs must not escape and
                # unwind out of the resource either.
                first.cancel()
                await settle()
                assert not second.done(), _RELEASED_EARLY
            finally:
                suspended.release()

            with pytest.raises(asyncio.CancelledError):
                await first
            assert second is not None
            await second

            # Decisive where the blocked-caller check above is not: the two calls were
            # never inside the resource at the same time. A delta, because a fake's
            # preconditions pass through the same logged resource.
            assert not harness.log.overlapped, _RELEASED_EARLY
            assert harness.log.visits - visited_before == 2, (
                "both calls should have reached the resource by now"
            )

            await op.verify(trail)
