"""Shared conformance suites for the two source-read Protocols (ADR-0185 §4, §12).

Every ``SourceReadRecorder`` implementation must pass
:class:`SourceReadRecorderContract`, and every ``SourceReadTrail`` implementation
must pass :class:`SourceReadTrailContract` — which inherits the first, because a
trail *is* the recorder plus the ability to read. A concrete test subclasses one
of them and supplies its subject fixture.

**The narrow suite is bound to three subjects rather than one**, which ADR-0185
§12 requires in as many words: "The lane's conformance suite binds the
``SourceReadRecorder`` contract to **both** fakes and to the concrete store, so
the store's satisfaction of the narrow seam is evidence rather than assertion."
That claim is what lets a composition root pass one object to a driver's
``SourceReadRecorder`` parameter and to the hub's ``SourceReadTrail`` one, and
without those bindings it would be a sentence in an ADR rather than something the
gate checks. It is the arrangement ``source_grant_contract.py`` already uses for
the grant pair.

**Here rather than under ``tests/core/``.** The corpus puts a suite beside the
subsystem that implements it, and ADR-0185 §4 puts both implementations in
``permissions/`` — ``audit_trail_contract.py``, ``action_policy_contract.py`` and
``source_grant_contract.py`` are already here for the same reason.

**A write-only seam still has clauses, and the suite reaches them through a
hook.** ``SourceReadRecorder`` has one member and no way to read anything back, so
:meth:`SourceReadRecorderContract.written` is how a case observes what the subject
holds — a *test author's* lever on the subject it was handed, never a member of
the seam every driver depends on. That is ``SourceGrantsContract.given``'s
arrangement inverted, and for its reason: the suite must not add to the Protocol
the thing the Protocol exists to withhold.

Named ``*_contract`` (not ``test_*``) so pytest collects it only via a
``Test``-prefixed subclass, never the abstract bases directly.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Protocol

import pytest

from ai_assistant.core.errors import ReadTrailError
from ai_assistant.core.protocols import SourceReadRecorder, SourceReadTrail
from ai_assistant.core.types import GrantScope, ReadOutcome, SourceReadRecord
from ai_assistant.testing.cancellation import settle
from ai_assistant.testing.reads import source_read_record

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine
    from contextlib import AbstractAsyncContextManager

    from ai_assistant.testing.cancellation import SuspendedMidWrite

#: The source every case below is about, unless it is about two.
SOURCE = "calendar"

#: A second source, for the cases that need to tell two streams apart.
OTHER = "email"

#: The instant a record's first grant check resolved, unless a case moves it.
CHECKED_AT = datetime(2026, 7, 20, 12, 0, tzinfo=UTC)

_RELEASED_EARLY = "the resource was handed over while the cancelled work was still using it"


def _read(  # noqa: PLR0913 — an id, a source, a use, an instant, an outcome and a count; each is one field a case may need to name
    record_id: str,
    *,
    source: str = SOURCE,
    use: GrantScope = GrantScope.INGEST,
    checked_at: datetime = CHECKED_AT,
    outcome: ReadOutcome = ReadOutcome.COMPLETED,
    produced: int = 0,
) -> SourceReadRecord:
    """One coherent record, named by the caller so a case can assert on order."""
    return source_read_record(
        source,
        record_id=record_id,
        use=use,
        checked_at=checked_at,
        outcome=outcome,
        produced=produced,
    )


async def _refuses(
    recorder: SourceReadRecorder,
    written: Callable[[], Coroutine[Any, Any, list[SourceReadRecord]]],
    rejected: SourceReadRecord,
) -> None:
    """Assert ``record`` refuses ``rejected`` **and writes nothing**.

    The second half is what makes a refusal a refusal: a store that appended and
    *then* raised would be holding exactly the row the clause exists to keep out,
    and every other assertion in the case would still pass.
    """
    before = await written()

    with pytest.raises(ReadTrailError):
        await recorder.record(rejected)

    assert await written() == before, "a refused write must leave no trace"


# --- the ADR-0060 cancellation cases, one per lock site ----------------------


class _CancellationOp(Protocol):
    """One ``SourceReadTrail`` operation the ADR-0060 case drives.

    Each :attr:`name` selects a distinct lock site; the suite runs the same
    cancelled-first / concurrent-second scenario against every one, so a
    regression reintroduced at any single site is caught rather than only at
    ``record``. **Reads are operations too**: ADR-0060 §3 binds any method that
    acquires the resource, not any method that mutates.
    """

    name: str

    async def prepare(self, trail: SourceReadTrail) -> None:
        """Establish anything the operation needs before it can run."""
        ...

    def first(self, trail: SourceReadTrail) -> Coroutine[Any, Any, object]:
        """The call the case suspends inside the resource and then cancels."""
        ...

    def second(self, trail: SourceReadTrail) -> Coroutine[Any, Any, object]:
        """The concurrent call barred from the resource until the first is done."""
        ...

    async def verify(self, trail: SourceReadTrail) -> None:
        """Assert the resource survived: the second call is whole and reads work."""
        ...


class _RecordOp:
    """The append-only ``record`` path."""

    name = "record"

    async def prepare(self, trail: SourceReadTrail) -> None:
        """No preconditions."""

    def first(self, trail: SourceReadTrail) -> Coroutine[Any, Any, object]:
        """Record the row whose write is cancelled."""
        return trail.record(_read("cancel-1"))

    def second(self, trail: SourceReadTrail) -> Coroutine[Any, Any, object]:
        """Record an independent row concurrently."""
        return trail.record(_read("cancel-2", source=OTHER))

    async def verify(self, trail: SourceReadTrail) -> None:
        """The second record is durable; the first is absent-or-whole; reads work."""
        assert {held.id for held in await trail.export()} >= {"cancel-2"}


class _ClearOp:
    """The ``clear`` write, with a recorded row so it does real work."""

    name = "clear"

    async def prepare(self, trail: SourceReadTrail) -> None:
        """A recorded row for ``clear`` to remove."""
        await trail.record(_read("seed-1"))

    def first(self, trail: SourceReadTrail) -> Coroutine[Any, Any, object]:
        """Clear the trail — the call that is cancelled."""
        return trail.clear()

    def second(self, trail: SourceReadTrail) -> Coroutine[Any, Any, object]:
        """Clear again concurrently."""
        return trail.clear()

    async def verify(self, trail: SourceReadTrail) -> None:
        """The trail is empty and still serves reads."""
        assert await trail.export() == []


class _ReadOp:
    """A locked read, driven against a trail seeded the same way.

    Nothing is asserted about the cancelled read's answer — it has none, its task
    was cancelled — so :meth:`verify` pins the state the second call had to see,
    re-read once the scenario is over.
    """

    name = ""

    async def prepare(self, trail: SourceReadTrail) -> None:
        """Seed two rows, in a known recording order."""
        await trail.record(_read("read-1"))
        await trail.record(_read("read-2", source=OTHER, outcome=ReadOutcome.REFUSED))

    def first(self, trail: SourceReadTrail) -> Coroutine[Any, Any, object]:
        """The read the case suspends inside the resource and then cancels."""
        raise NotImplementedError

    def second(self, trail: SourceReadTrail) -> Coroutine[Any, Any, object]:
        """The concurrent read barred from the resource until the first is done."""
        raise NotImplementedError

    async def verify(self, trail: SourceReadTrail) -> None:
        """A read cancelled mid-flight leaves the trail whole and still readable."""
        assert [held.id for held in await trail.export()] == ["read-1", "read-2"]


class _RecentOp(_ReadOp):
    """``recent`` — the bounded page, its own lock site."""

    name = "recent"

    def first(self, trail: SourceReadTrail) -> Coroutine[Any, Any, object]:
        """Read the newest page — the call that is cancelled."""
        return trail.recent(limit=2)

    def second(self, trail: SourceReadTrail) -> Coroutine[Any, Any, object]:
        """Read a narrower page concurrently."""
        return trail.recent(limit=1)


class _ExportOp(_ReadOp):
    """``export`` — the whole-horizon read, its own lock site."""

    name = "export"

    def first(self, trail: SourceReadTrail) -> Coroutine[Any, Any, object]:
        """Export everything — the call that is cancelled."""
        return trail.export()

    def second(self, trail: SourceReadTrail) -> Coroutine[Any, Any, object]:
        """Export again concurrently."""
        return trail.export()


#: Every ``SourceReadTrail`` operation ADR-0060's case is run against — the two
#: writes and both reads, because §3 binds any method that acquires the resource.
_CANCELLATION_OPS: tuple[Callable[[], _CancellationOp], ...] = (
    _RecordOp,
    _ClearOp,
    _RecentOp,
    _ExportOp,
)


class SourceReadRecorderContract:
    """Behaviour every ``SourceReadRecorder`` implementation must exhibit.

    The clauses that bind the **write** seam, and every one of them binds a
    ``SourceReadTrail`` too — which is why :class:`SourceReadTrailContract`
    inherits rather than repeats them.
    """

    @pytest.fixture
    def recorder(self) -> SourceReadRecorder:
        """Override in a subclass to supply the implementation under test.

        The subject must start **empty**: every case below arranges the history it
        is about, and a subject that arrived holding a row would make the ordering
        and prune cases assert against a state the case did not set up.
        """
        raise NotImplementedError

    async def written(self, recorder: SourceReadRecorder) -> list[SourceReadRecord]:
        """Override to return what the subject holds, oldest-recorded first.

        The seam has no read member and must not grow one (ADR-0185 §4), so this
        is how a case observes an append at all. It is a lever on the *subject*,
        never on the Protocol: a fake exposes its own, and a trail answers through
        ``export``.
        """
        raise NotImplementedError

    def test_conforms_to_protocol(self, recorder: SourceReadRecorder) -> None:
        assert isinstance(recorder, SourceReadRecorder)

    async def test_record_returns_the_id_the_caller_minted(
        self, recorder: SourceReadRecorder
    ) -> None:
        """The id is the **caller's**, minted before the call (ADR-0021 §3).

        A store neither mints ids nor reads a clock, which is the division
        ``SourceGrant`` and ``PermissionDecision`` already keep and the reason
        ``id`` is a required field rather than something ``record`` returns from
        nowhere.
        """
        returned = await recorder.record(_read("r-1"))

        assert returned == "r-1"

    async def test_a_recorded_attempt_is_held(self, recorder: SourceReadRecorder) -> None:
        """The row that comes back equals the one that went in."""
        appended = _read("r-1", outcome=ReadOutcome.DISCARDED, produced=14)

        await recorder.record(appended)

        assert await self.written(recorder) == [appended]

    @pytest.mark.parametrize("outcome", list(ReadOutcome), ids=lambda member: member.value)
    async def test_every_outcome_is_recordable(
        self, recorder: SourceReadRecorder, outcome: ReadOutcome
    ) -> None:
        """All six of ADR-0185 §1's members, and no implementation may narrow the set.

        ``UNANSWERED``, ``DISCARDED`` and ``UNCONFIRMED`` are the three no ordinary
        run produces and the three this ADR adds the most value by recording, so a
        store that quietly refused one would leave the trail silent about exactly
        the attempts §7 says it exists for.
        """
        await recorder.record(_read("r-1", outcome=outcome))

        held = await self.written(recorder)
        assert [row.outcome for row in held] == [outcome]

    @pytest.mark.parametrize("use", list(GrantScope), ids=lambda member: member.value)
    async def test_every_use_is_recordable(
        self, recorder: SourceReadRecorder, use: GrantScope
    ) -> None:
        """Three drivers, three uses, one store (ADR-0185 §5, §12).

        The lane wires the recorder into all three, "since a driver wired for one
        use and not another would leave §1's completeness claim false for a use
        nobody noticed"; a store that admitted only some would defeat that from the
        other end.
        """
        await recorder.record(_read("r-1", use=use))

        held = await self.written(recorder)
        assert [row.use for row in held] == [use]

    async def test_recording_a_known_id_is_refused_rather_than_upserted(
        self, recorder: SourceReadRecorder
    ) -> None:
        """Write-once, on ``AuditTrail.record``'s reasoning.

        A trail that upserts is one where history can be rewritten by replaying a
        write, which is the one property this store exists to deny. The refusal
        must also leave the original intact rather than replacing it.
        """
        await recorder.record(_read("r-1", produced=3))

        await _refuses(recorder, lambda: self.written(recorder), _read("r-1", produced=99))

        held = await self.written(recorder)
        assert [(row.id, row.produced) for row in held] == [("r-1", 3)]

    async def test_two_racing_writes_of_one_id_settle_it_once(
        self, recorder: SourceReadRecorder
    ) -> None:
        """The atomicity clause, as a race rather than as a sentence (ADR-0185 §12).

        Without atomicity over the duplicate check and the append, both callers
        observe a free id, both append, and the trail holds one attempt twice —
        which is a *fabricated* record in the store whose premise is that its
        records are not fabricated. Exactly one of the two must raise.
        """
        outcomes = await asyncio.gather(
            recorder.record(_read("r-1", produced=1)),
            recorder.record(_read("r-1", produced=2)),
            return_exceptions=True,
        )

        assert sum(isinstance(outcome, str) for outcome in outcomes) == 1
        assert sum(isinstance(outcome, ReadTrailError) for outcome in outcomes) == 1
        assert len(await self.written(recorder)) == 1

    @pytest.mark.parametrize(
        ("attribute", "value"),
        [
            pytest.param("checked_at", datetime(2026, 7, 20, 12, 0), id="a naive instant"),  # noqa: DTZ001
            pytest.param("produced", -1, id="a negative count"),
            pytest.param("source", "   ", id="a blank source"),
            pytest.param("grant", None, id="a completed row citing no grant"),
        ],
    )
    async def test_a_corrupted_record_is_refused_rather_than_stored(
        self, recorder: SourceReadRecorder, attribute: str, value: object
    ) -> None:
        """ADR-0021 §4 asks for a *validated* snapshot, not merely a detached one.

        Detachment alone copies without checking, so an implementation that only
        deep-copies conforms to every other clause here and still accepts a record
        corrupted past its frozen model's guard. Two of the four are sharp: a naive
        ``checked_at`` makes every later read of the trail incoherent, and a
        ``COMPLETED`` row citing no grant loses the pointer ADR-0185 §2's whole
        correspondence rests on — a reader could no longer partition the two
        outcomes that opened nothing from the four that ran under an authorisation.

        Held here rather than only on one implementation because it is exactly the
        clause two would plausibly disagree on: nothing about a deep-copying store
        *looks* wrong until a corrupted record is in it.
        """
        await recorder.record(_read("r-1"))
        corrupted = _read("r-2")
        object.__setattr__(corrupted, attribute, value)

        await _refuses(recorder, lambda: self.written(recorder), corrupted)

        assert [row.id for row in await self.written(recorder)] == ["r-1"]

    async def test_detachment_survives_a_caller_supplied_subclass(
        self, recorder: SourceReadRecorder
    ) -> None:
        """A caller's subclass may not become the object the trail hands back.

        ``SourceReadRecord`` is a plain model, so a caller can subclass it and
        override ``model_copy`` to return ``self``. A store that snapshotted
        through ``type(read)`` would then hold that instance and return it from
        every read, so the detachment below would stop holding without any of its
        own assertions changing — the caller keeps a live handle on an append-only
        row. The obligation is therefore on the *declared* type.
        """

        class _Sticky(SourceReadRecord):
            def model_copy(self, **kwargs: object) -> _Sticky:
                return self

        original = _read("r-1", produced=7)
        await recorder.record(_Sticky.model_construct(**dict(original)))

        (stored,) = await self.written(recorder)
        object.__setattr__(stored, "produced", 999)

        (reread,) = await self.written(recorder)
        assert reread.produced == original.produced

    async def test_the_stored_snapshot_is_detached_from_the_caller(
        self, recorder: SourceReadRecorder
    ) -> None:
        """The write-path half of ADR-0018 §4's rule.

        A store retaining the caller's object would let
        ``read.__dict__["outcome"] = …`` rewrite an appended row after the fact,
        through a store whose entire premise is that rows are not rewritten.
        Detachment on queries alone closes the door and leaves the window open —
        and ``outcome`` is the field that would be rewritten, since it is the one
        the whole record turns on.
        """
        held = _read("r-1", outcome=ReadOutcome.REFUSED)
        await recorder.record(held)

        object.__setattr__(held, "outcome", ReadOutcome.COMPLETED)
        object.__setattr__(held, "produced", 99)

        (stored,) = await self.written(recorder)
        assert stored.outcome is ReadOutcome.REFUSED
        assert stored.produced == 0

    @pytest.mark.parametrize(
        "declared",
        [
            pytest.param(f" {SOURCE} ", id="surrounding whitespace"),
            pytest.param(SOURCE.upper(), id="another case"),
        ],
    )
    async def test_the_source_is_stored_byte_for_byte(
        self, recorder: SourceReadRecorder, declared: str
    ) -> None:
        """ADR-0185 §2: a faithful copy, and nothing is normalised.

        ``source`` is ``NonBlankEncodableText`` and deliberately not
        ``Identifier``: a stripping type would let the trail name a source the
        reader is not called, which is the one thing an audit record may not do.
        No implementation may strip, case-fold or otherwise normalise it, on the
        write path or at lookup — the rule ``SourceGrants.live`` already carries
        for the grant seam, stated over the record instead.
        """
        await recorder.record(_read("r-1", source=declared))

        (stored,) = await self.written(recorder)
        assert stored.source == declared


class SourceReadTrailContract(SourceReadRecorderContract):
    """Behaviour every ``SourceReadTrail`` implementation must exhibit.

    Inherits the write seam's clauses, because a trail *is* the recorder plus the
    ability to read — ADR-0185 §4's "one ``permissions/`` class implementing all
    four members satisfies both seams", tested rather than asserted.
    """

    @pytest.fixture
    def trail(self) -> SourceReadTrail:
        """Return an empty trail under test."""
        raise NotImplementedError

    @pytest.fixture
    def recorder(self, trail: SourceReadTrail) -> SourceReadRecorder:
        """The same subject, seen through the narrow seam.

        Not a second object: the inherited clauses must bind *this* trail, which
        is ADR-0185 §4's "one implementation satisfies both" being tested rather
        than asserted.
        """
        return trail

    async def written(self, recorder: SourceReadRecorder) -> list[SourceReadRecord]:
        """Answer the inherited clauses through ``export``, since this subject has it."""
        assert isinstance(recorder, SourceReadTrail)
        return await recorder.export()

    def bounded(self, max_rows: int) -> AbstractAsyncContextManager[SourceReadTrail]:
        """Supply an empty trail whose cap is ``max_rows`` (ADR-0185 §6).

        Override in a subclass. The cap is a *construction* input rather than a
        member, so the only way a suite can exercise the prune at a size a test can
        write down is to be handed a differently-configured subject. It is an async
        context manager so a durable implementation can close what it opened.
        """
        raise NotImplementedError

    def test_conforms_to_both_seams(self, trail: SourceReadTrail) -> None:
        """One object, two Protocols, structurally (ADR-0185 §4)."""
        assert isinstance(trail, SourceReadTrail)
        assert isinstance(trail, SourceReadRecorder)

    # --- ordering: recording order, and never ``checked_at`` ----------------

    async def test_export_returns_rows_in_recording_order(self, trail: SourceReadTrail) -> None:
        """ADR-0185 §12: "every record the store holds, in recording order"."""
        for index in range(3):
            await trail.record(_read(f"r-{index}"))

        assert [row.id for row in await trail.export()] == ["r-0", "r-1", "r-2"]

    async def test_recent_returns_rows_newest_recorded_first(self, trail: SourceReadTrail) -> None:
        """ADR-0185 §6: "``recent`` returns records in reverse order of recording"."""
        for index in range(3):
            await trail.record(_read(f"r-{index}"))

        assert [row.id for row in await trail.recent()] == ["r-2", "r-1", "r-0"]

    async def test_the_order_is_recording_order_and_never_checked_at(
        self, trail: SourceReadTrail
    ) -> None:
        """The clause ADR-0185 §6 says the first implementation would get wrong.

        ``checked_at`` is **caller-supplied** and the store reads no clock, which is
        ADR-0097 §4's reason for refusing a timestamp invariant on the grant store:
        "a host clock corrected backwards … makes every truthfully-timestamped
        revocation refusable". Here a decision *does* rest on order — the prune — so
        the same premises reach the opposite conclusion, and a store that sorted on
        the caller's instant would, after a backwards correction, delete the rows it
        had just written and lose precisely the recent history it exists for.

        The rows below are recorded **oldest instant last**, so an implementation
        ordering by ``checked_at`` reverses both answers and fails here rather than
        a year later on a machine whose clock stepped.
        """
        await trail.record(_read("later", checked_at=CHECKED_AT + timedelta(hours=1)))
        await trail.record(_read("earlier", checked_at=CHECKED_AT - timedelta(hours=1)))

        assert [row.id for row in await trail.export()] == ["later", "earlier"]
        assert [row.id for row in await trail.recent()] == ["earlier", "later"]

    # --- the bounded read ---------------------------------------------------

    async def test_recent_returns_the_newest_within_the_limit(self, trail: SourceReadTrail) -> None:
        for index in range(4):
            await trail.record(_read(f"r-{index}"))

        assert [row.id for row in await trail.recent(limit=2)] == ["r-3", "r-2"]

    @pytest.mark.parametrize("limit", [0, -1])
    async def test_a_non_positive_limit_is_refused(
        self, trail: SourceReadTrail, limit: int
    ) -> None:
        """Refused rather than clamped or passed through.

        A store issuing ``LIMIT ?`` against SQLite turns ``limit=-1`` into *no limit
        at all*, so the one call offering a bounded read of a Tier 1 store would
        become the unbounded read it exists to avoid. Clamping silently is the other
        wrong answer — a caller that asked for something meaningless should learn
        that, not be served something it did not ask for.
        """
        await trail.record(_read("r-1"))

        with pytest.raises(ValueError, match="strictly positive"):
            await trail.recent(limit=limit)

    async def test_a_limit_wider_than_a_backing_store_can_bind_still_answers(
        self, trail: SourceReadTrail
    ) -> None:
        """A Python int has no width; a SQLite parameter does.

        Binding one wider than a signed 64-bit integer raises ``OverflowError``,
        which is neither ``ValueError`` nor ``ReadTrailError`` and would leave the
        implementation's error boundary through a hole. A bound above any possible
        row count means "all of them", which is what a conforming answer is.
        """
        await trail.record(_read("r-1"))

        assert [row.id for row in await trail.recent(limit=2**64)] == ["r-1"]

    async def test_an_empty_trail_answers_emptily(self, trail: SourceReadTrail) -> None:
        assert await trail.recent() == []
        assert await trail.export() == []

    async def test_a_returned_list_is_a_detached_snapshot(self, trail: SourceReadTrail) -> None:
        """``recent`` and ``export`` return ``list``, and a list is mutable."""
        await trail.record(_read("r-1"))

        (await trail.export()).clear()
        (await trail.recent()).clear()

        assert len(await trail.export()) == 1

    # --- the bound (ADR-0185 §6) -------------------------------------------

    async def test_the_cap_evicts_the_earliest_recorded(self) -> None:
        """The prune, and its direction (ADR-0185 §6).

        **Oldest-first is the opposite of ``notification_queue_limit``'s choice and
        the two stores are opposite cases.** A notification queue holds candidates
        that have not happened yet, so dropping the newest loses least; an audit
        trail holds acts that already happened, and a store that refused new rows
        when full would make its own fullness gate the system's behaviour — under
        ADR-0185 §5's fail-closed rule the assistant would stop reading sources
        altogether, silently and permanently, because a log filled up.
        """
        async with self.bounded(3) as trail:
            for index in range(5):
                await trail.record(_read(f"r-{index}"))

            assert [row.id for row in await trail.export()] == ["r-2", "r-3", "r-4"]

    async def test_the_row_count_never_exceeds_the_cap(self) -> None:
        """Asserted after **every** append, not only at the end.

        A store that pruned on a schedule rather than inside ``record`` would leave
        a window in which it is over its cap, and an assertion taken once at the end
        could not see it. ADR-0185 §6 refuses the sweep for exactly this: "there is
        no window in which the store is over its cap".
        """
        async with self.bounded(2) as trail:
            for index in range(6):
                await trail.record(_read(f"r-{index}"))
                assert len(await trail.export()) <= 2

    async def test_the_prune_is_blind_to_what_the_row_says(self) -> None:
        """ADR-0185 §6: no prune may be conditioned on any field of a record.

        A uniform, content-blind horizon removes nothing anybody chose, which is
        what keeps it from being the page ADR-0021 §4 forbids tearing out of the
        book. The refused row here is the *most* interesting one the trail holds —
        a read refused across a revocation, which §7 says is the row the security
        question is about — so an implementation that kept "important" rows fails,
        and so does one that dropped them.
        """
        async with self.bounded(2) as trail:
            await trail.record(_read("refused", outcome=ReadOutcome.REFUSED))
            await trail.record(_read("completed-1"))
            await trail.record(_read("completed-2"))

            assert [row.id for row in await trail.export()] == ["completed-1", "completed-2"]

    async def test_a_full_trail_still_accepts_a_new_row(self) -> None:
        """The clause the fail-closed rule depends on (ADR-0185 §6).

        "An audit record must never gate the act it records beyond the recording
        itself." A store that refused at capacity, combined with §5's fail-closed
        driver, would stop the assistant reading sources at all.
        """
        async with self.bounded(1) as trail:
            await trail.record(_read("first"))

            assert await trail.record(_read("second")) == "second"
            assert [row.id for row in await trail.export()] == ["second"]

    @pytest.mark.parametrize("cap", [0, -1])
    async def test_a_cap_that_is_not_strictly_positive_is_refused(self, cap: int) -> None:
        """ADR-0185 §6: no sentinel, no ``none``, no zero, no negative.

        The absence of an unlimited spelling is the *mechanism* that discharges
        ADR-0139 §6's growth-bound clause, and a store that accepted a
        non-positive cap would reintroduce it through the back door — zero is at
        capacity before its first append, and a negative one has no meaning a prune
        could act on.
        """
        with pytest.raises(ValueError, match="strictly positive"):
            async with self.bounded(cap):
                pass  # pragma: no cover — construction is the subject

    # --- erasure -----------------------------------------------------------

    async def test_clear_erases_everything_and_reports_how_much(
        self, trail: SourceReadTrail
    ) -> None:
        """Wholesale erasure only (ADR-0021 §4, ADR-0185 §6).

        The user may burn the book, and nobody may tear out a page — which is why
        there is no ``delete(id)`` on this seam at all, and why the count comes back
        so the act is visible rather than silent.
        """
        for index in range(3):
            await trail.record(_read(f"r-{index}"))

        assert await trail.clear() == 3
        assert await trail.export() == []
        assert await trail.clear() == 0

    async def test_a_cleared_trail_still_records(self, trail: SourceReadTrail) -> None:
        """Burning the book leaves a store, not a corpse.

        A durable implementation empties its rows and keeps whatever describes the
        file's *shape*, so the next read is an empty trail rather than a fault.
        """
        await trail.record(_read("r-1"))
        await trail.clear()

        assert await trail.record(_read("r-2")) == "r-2"
        assert [row.id for row in await trail.export()] == ["r-2"]

    async def test_an_exported_record_survives_a_json_round_trip(
        self, trail: SourceReadTrail
    ) -> None:
        """ADR-0004 §6's export right is a *portable* snapshot.

        A row that could not be rebuilt from its own JSON would satisfy every other
        clause here and still leave the user with a file nothing can read back.
        """
        original = _read("r-1", outcome=ReadOutcome.UNCONFIRMED, produced=4)
        await trail.record(original)

        (exported,) = await trail.export()
        assert SourceReadRecord.model_validate(exported.model_dump(mode="json")) == original

    # --- ADR-0060's cancellation clause, on every lock site ----------------

    #: Set on a subclass whose subject acquires nothing whose safety outlives the
    #: coroutine — no connection, lock, spawned task, file handle or transaction a
    #: ``CancelledError`` could unwind past. Left ``False``, the suite requires the
    #: implementation to prove the invariant by overriding
    #: :meth:`trail_suspended_mid_write`, so a durable backend that reintroduces
    #: ADR-0054's bug fails here rather than passing a suite that never looked.
    acquires_no_shared_resource: bool = False

    #: Operations this implementation acquires no coroutine-outliving resource
    #: for, even though others do. Empty by default.
    operations_without_shared_resource: frozenset[str] = frozenset()

    def trail_suspended_mid_write(
        self,
    ) -> AbstractAsyncContextManager[SuspendedMidWrite[SourceReadTrail]]:
        """Supply a trail whose named operation can be stopped *inside* its resource.

        Override unless :attr:`acquires_no_shared_resource` is set. The suite
        cancels the call while it is suspended and then watches what a second
        caller can reach, which is the only way to tell the fixed code from the
        broken code: pre-ADR-0054 the audit trail raised ``CancelledError``
        correctly and released the connection anyway, so a case that asserts only
        propagation certifies the bug (ADR-0060 §3).
        """
        raise NotImplementedError

    @pytest.mark.optional_obligation
    @pytest.mark.parametrize("make_op", _CANCELLATION_OPS, ids=lambda op: op().name)
    async def test_a_cancelled_operation_holds_its_resource_until_the_work_finishes(
        self, make_op: Callable[[], _CancellationOp]
    ) -> None:
        """``core.protocols``' cancellation clause, on every operation (ADR-0060).

        A cancelled call must not hand the resource to the next caller while the
        work it started is still using it. The second call is what makes this a
        test of the invariant rather than of propagation: a single cancelled call
        in isolation looks identical either way.

        The cancelled write's *effect* is deliberately not asserted, and here that
        is a contract clause rather than a convenience: ADR-0185 §1 rules that
        whether a cancelled attempt left a row is **indeterminate** where the
        cancellation landed inside a recorder call already in flight, and "no
        component may assume either way". An arm that pinned it would pin what the
        contract refuses to promise.
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

            # Decisive where the blocked-caller check above is not: the two calls
            # were never inside the resource at the same time. A delta, because a
            # fake's preconditions pass through the same logged resource.
            assert not harness.log.overlapped, _RELEASED_EARLY
            assert harness.log.visits - visited_before == 2, (
                "both calls should have reached the resource by now"
            )

            await op.verify(trail)
