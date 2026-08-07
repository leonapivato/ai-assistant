"""The ingestion stage: the read, the gate, and what it reports (ADR-0093 §6).

Every collaborator is a canonical fake from ``ai_assistant.testing`` or a thin
scripted wrapper around one, so nothing here imports a subsystem concrete — nor a
concrete *reader*, which ``lint-imports`` forbids this layer outright (ADR-0093
§2). What is under test is the **stage**: that a reading's proposals reach memory
through the ratified gate, in order, and what its report says. The reader's own
clauses — the band, the episode refusal, the bound, the payload-free failure — are
its conformance suite's and are never re-asserted here.

The one hand-rolled double is :class:`_FailingWriter`, which delegates to the
canonical :class:`FakeMemoryWriter` and fails on a named call. It has to be
scripted: "the earlier proposals are already applied" is a claim about records
that really landed, so replacing the writer rather than wrapping it would make the
assertion vacuous.
"""

from __future__ import annotations

import ast
import asyncio
import inspect
import textwrap
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from ai_assistant.core.errors import (
    GrantError,
    MemoryStoreError,
    ReaderError,
    SourceNotGrantedError,
)
from ai_assistant.core.types import DataTier, GrantScope, MemoryDecisionKind
from ai_assistant.orchestration import IngestionStage, MemoryWriteStage
from ai_assistant.testing import (
    FakeDeferralStore,
    FakeMemoryPolicy,
    FakeMemoryStore,
    FakeMemoryWriter,
    FakeReader,
    FakeSourceGrants,
    attested_proposal,
    source_grant,
)
from ai_assistant.testing.readers import DEFAULT_READER_NAME

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from ai_assistant.core.protocols import MemoryWriter, Reader, SourceGrants
    from ai_assistant.core.types import (
        MemoryIngestResult,
        MemoryUpdateProposal,
        SourceGrant,
        SourceReading,
    )

#: The instant every store fake in this module reads its clock at. Deliberately
#: *after* ``FakeReader``'s own default ``read_at``: the reading's instant is the
#: producer's and the store's is ours, and a test that shared one number could not
#: tell a report echoing the reading from a report echoing the clock.
_AT = datetime(2026, 3, 4, 10, 0, tzinfo=UTC)


class _FailingWriter:
    """A ``MemoryWriter`` that raises ``MemoryStoreError`` on its *n*-th call."""

    def __init__(self, inner: FakeMemoryWriter, *, fail_on: int) -> None:
        self._inner = inner
        self._fail_on = fail_on
        self.calls = 0

    async def ingest(self, proposal: MemoryUpdateProposal) -> MemoryIngestResult:
        """Delegate, except on the call the script names."""
        self.calls += 1
        if self.calls == self._fail_on:
            msg = "the store is broken"
            raise MemoryStoreError(msg)
        return await self._inner.ingest(proposal)

    async def ingest_reading(self, reading: SourceReading) -> Sequence[MemoryIngestResult]:
        """Fail the *n*-th proposal of the reading, delegating the rest.

        The script counts proposals rather than calls, so a reading of three with
        ``fail_on=2`` leaves the first applied and never reaches the third — which is
        ADR-0115 §3's and §4's partial-ingest shape, driven through the seam the
        stage actually uses.
        """
        results: list[MemoryIngestResult] = []
        for proposal in reading.proposals:
            results.append(await self.ingest(proposal))
        return results


def _awaited_names(func: Callable[..., object]) -> list[str]:
    """The attribute names this function awaits, in source order.

    ADR-0097 §5a's first clause — "No ``await`` may occur between the ``live()``
    result a driver gates on and its call to ``Reader.read()``" — is a rule about
    the driver's *body*, stated as a rule rather than bought with a mechanism
    because "it costs a line and a test". This is that test's instrument: reading
    the awaits off the source is what makes the property checkable at all, since
    an interleaving that never happens to be exercised is indistinguishable at run
    time from one that cannot happen.
    """
    tree = ast.parse(textwrap.dedent(inspect.getsource(func)))
    found: list[tuple[int, int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Await):
            continue
        call = node.value
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute):
            found.append((node.lineno, node.col_offset, call.func.attr))
    # Sorted by position, because ``ast.walk`` is breadth-first: reading it in its
    # own order would assert on the tree's shape rather than on the sequence the
    # event loop actually sees, which is the whole subject.
    return [name for _, _, name in sorted(found)]


class _FailsOnTheRecheck:
    """A ``SourceGrants`` that answers once and raises from every later ``live``.

    A thin scripted wrapper around the canonical fake, for :class:`_FailingWriter`'s
    reason: the fake is ``@final`` and its own ``fail_live`` script is armed for
    *every* call, while the case under test needs the failure to arrive **between**
    two of them. Everything the driver actually observes is the canonical fake's;
    what is scripted here is only when the arming happens.
    """

    def __init__(self, inner: FakeSourceGrants) -> None:
        self._inner = inner

    async def live(self, *, source: str, use: GrantScope) -> SourceGrant | None:
        """Delegate, then arm the fake so the next call raises."""
        answer = await self._inner.live(source=source, use=use)
        self._inner.fail_live()
        return answer


class Harness:
    """A wired :class:`IngestionStage` and the fakes behind it, for assertions."""

    def __init__(
        self,
        *,
        reader: Reader | None = None,
        writer: MemoryWriter | None = None,
        policy: FakeMemoryPolicy | None = None,
        grants: SourceGrants | None = None,
    ) -> None:
        self.now: datetime = _AT
        self.memory = FakeMemoryStore(now=lambda: self.now)
        self.policy = policy if policy is not None else FakeMemoryPolicy()
        self.real_writer = FakeMemoryWriter(
            store=self.memory, policy=self.policy, now=lambda: self.now
        )
        self.writer: MemoryWriter = writer if writer is not None else self.real_writer
        # The stage reaches memory through the orchestration **write stage** rather
        # than through a `MemoryWriter` of its own (ADR-0078 §3), so a proposal the
        # policy defers parks a durable question. The queue is held here so a case
        # can read back what was parked.
        self.deferrals = FakeDeferralStore(now=lambda: self.now)
        self.writes = MemoryWriteStage(writer=self.writer, deferrals=self.deferrals)
        self.reader: Reader = reader if reader is not None else FakeReader()
        # Granted throughout unless a case scripts otherwise. Every case in this
        # module other than the gate's own is about what the stage does with a
        # reading it was *permitted* to take, so the default has to be the granted
        # one — an ungranted default would make every other assertion here
        # vacuous, which is the shape ADR-0093 §10 refused for its own fake.
        self.grants: SourceGrants = (
            grants if grants is not None else FakeSourceGrants([source_grant(self.reader.name)])
        )
        self.stage = IngestionStage(reader=self.reader, writes=self.writes, grants=self.grants)


def _proposals(count: int, *, name: str = DEFAULT_READER_NAME) -> list[MemoryUpdateProposal]:
    """``count`` well-formed attested proposals, distinguishable by content."""
    return [
        attested_proposal(
            f"{name} reported thing {index}", reported_by=name, record_id=f"r-{index}"
        )
        for index in range(count)
    ]


# --- every belief reaches memory through the gate (ADR-0093 §1) ---------


async def test_every_proposal_reaches_memory_through_the_ratified_gate() -> None:
    """The reader proposes; a deterministic policy disposes; the stage rules on nothing.

    ADR-0093 §1: "Every belief a reader's reading proposes reaches memory through
    ``MemoryWriter.ingest`` and the ``MemoryPolicy`` behind it. A reader inherits
    no part of ADR-0075's capture exemption." The policy seeing every proposal is
    what that sentence means operationally — a producer that reached the store
    around it would be the arrangement ADR-0028's propose/dispose split exists to
    prevent.
    """
    harness = Harness(reader=FakeReader(_proposals(3)))

    report = await harness.stage.ingest()

    assert len(harness.policy.calls) == 3
    assert report.proposed == 3
    assert report.stored == 3
    assert report.deferred == 0
    assert report.rejected == 0
    stored = await harness.memory.search("reported thing", limit=10)
    assert len(stored) == 3


async def test_the_proposals_are_ingested_in_the_readers_own_order() -> None:
    """In order and independently, exactly as the learn and observation legs do it."""
    harness = Harness(reader=FakeReader(_proposals(3)))

    await harness.stage.ingest()

    assert [call.proposal.proposed.id for call in harness.policy.calls] == ["r-0", "r-1", "r-2"]


async def test_the_report_carries_the_readings_identity_and_our_read_instant() -> None:
    """``source`` is the producer's declared identity and ``read_at`` is *our* clock.

    ADR-0093 §10 keeps the two instants apart — a reading-wide ``as_of`` is the
    *source's* claim and is a different fact (ADR-0073 §4) — and §7 makes the
    identity Tier 2 and never a path, which is what lets a report be carried
    around at all.
    """
    acquired = datetime(2026, 3, 4, 9, 30, tzinfo=UTC)
    reader = FakeReader(_proposals(1, name="calendar"), name="calendar", read_at=acquired)

    report = await Harness(reader=reader).stage.ingest()

    assert report.source == "calendar"
    # The reading's own instant, not the store's clock (`_AT`, half an hour later).
    assert report.read_at == acquired


async def test_the_stage_passes_nothing_to_the_read() -> None:
    """``read()`` takes no arguments, so the stage cannot widen the bound (§5, §10).

    A caller able to widen the read is a caller able to defeat the bound, which is
    the property ADR-0077 §1 bought by putting the maximum on the producer. There
    is nothing to assert about arguments that do not exist, so what is asserted is
    the consequence: one pass is exactly one read.
    """
    reader = FakeReader(_proposals(2))
    harness = Harness(reader=reader)

    await harness.stage.ingest()

    assert reader.call_count == 1


# --- an empty reading is a success, and a failed read is not (ADR-0093 §8) ---


async def test_an_empty_reading_is_a_successful_pass_that_wrote_nothing() -> None:
    """The source had nothing to propose within the bound — not a failure signal.

    ADR-0093 §8 is explicit that "no caller may treat it as one", and this is the
    caller. Nothing reaches the policy, because there is nothing to rule on.
    """
    harness = Harness(reader=FakeReader([]))

    report = await harness.stage.ingest()

    assert report.proposed == 0
    assert report.stored == 0
    assert report.deferred == 0
    assert report.rejected == 0
    assert harness.policy.calls == []


async def test_a_source_failure_propagates_rather_than_becoming_an_empty_report() -> None:
    """A read that cannot complete raises, and no report is constructed.

    The two states must stay distinguishable at this seam: an empty reading that
    also meant "unreadable" would make a reader whose file was unreadable for a
    week look healthy for a week (ADR-0093 §8). Nothing is written on the way out.
    """
    harness = Harness(reader=FakeReader(failure=PermissionError("denied")))

    with pytest.raises(ReaderError):
        await harness.stage.ingest()

    assert harness.policy.calls == []
    assert await harness.memory.search("reported", limit=10) == []


async def test_a_cancelled_read_is_never_converted_into_a_source_fault() -> None:
    """``CancelledError`` crosses the stage unchanged (ADR-0093 §8, ADR-0060).

    The carve-out matters *here* as much as in the reader: converting it would
    make the scheduler log a source fault and re-arm on a shutdown that was
    working correctly (ADR-0083 §4).
    """
    reader = FakeReader(_proposals(1))
    harness = Harness(reader=reader)
    gate = reader.suspend_next()

    pass_ = asyncio.ensure_future(harness.stage.ingest())
    await gate.reached()
    pass_.cancel()
    gate.release()

    with pytest.raises(asyncio.CancelledError):
        await pass_
    assert harness.policy.calls == []


# --- what the gate ruled, counted honestly ------------------------------


async def test_a_deferred_ruling_parks_a_durable_question() -> None:
    """The stage writes through the *write stage*, so an ``ASK_USER`` is queued.

    ADR-0078 §3's one obligation, reaching a third producer: "a producer holding
    the writer directly gets the ratified policy and applier and silently loses
    the queue". A reader's proposals reach nobody in the moment, so a lost
    question is a question nobody is ever asked.
    """
    harness = Harness(
        reader=FakeReader(_proposals(1)),
        policy=FakeMemoryPolicy(MemoryDecisionKind.ASK_USER),
    )

    report = await harness.stage.ingest()

    assert report.deferred == 1
    assert report.stored == 0
    assert report.rejected == 0
    assert len(await harness.deferrals.pending(limit=10)) == 1


async def test_a_secret_tier_deferral_is_counted_without_claiming_a_queued_question() -> None:
    """``deferred`` counts **rulings**, and the secret-tier arm queues nothing.

    ADR-0078 §1: nothing is enqueued for a ``DataTier.SECRET`` proposal, because
    ADR-0004 §3 is unconditional that Tier 0 content lives "never in a database"
    and a durable queue is a file. The ruling still happened, so the count is
    right — what would be wrong is a report saying the question waits somewhere,
    and this pins that the count survives the suppression rather than the promise
    doing so.

    Reachable for a reader in principle: ADR-0093 §4 obliges a ``sensitivity``
    "chosen for what the source holds rather than defaulted", so a future source
    holding credentials would land exactly here.
    """
    secret = _proposals(1)[0].model_copy(update={"sensitivity": DataTier.SECRET})
    harness = Harness(
        reader=FakeReader([secret]),
        # The fake policy forces `ASK_USER` on secret-tier data whatever it is
        # configured with, because a policy that could be configured out of that
        # would violate its own conformance suite.
        policy=FakeMemoryPolicy(MemoryDecisionKind.ACCEPT),
    )

    report = await harness.stage.ingest()

    assert report.deferred == 1
    assert report.stored == 0
    assert report.rejected == 0
    # Ruled on, and nothing persisted — which is the whole point of the arm.
    assert await harness.deferrals.pending(limit=10) == []


async def test_a_deferral_the_full_queue_refuses_is_still_counted_as_deferred() -> None:
    """The second path where a ruling defers and no new question exists.

    The queue answers ``REFUSED`` at its cap (ADR-0078 §2, §7) — "nothing was
    admitted and there is no deferral to read" — and the ruling is unchanged. A
    report that equated ``deferred`` with "queued" would be false here too, and
    this is the case a reader reaches on volume rather than on sensitivity: a
    calendar bounded at 500 in-window occurrences (ADR-0093 §7a) against a queue
    whose cap is far lower.
    """
    harness = Harness(
        reader=FakeReader(_proposals(3)),
        policy=FakeMemoryPolicy(MemoryDecisionKind.ASK_USER),
    )
    harness.deferrals = FakeDeferralStore(now=lambda: harness.now, queue_limit=1)
    stage = IngestionStage(
        reader=harness.reader,
        writes=MemoryWriteStage(writer=harness.writer, deferrals=harness.deferrals),
        grants=harness.grants,
    )

    report = await stage.ingest()

    assert report.proposed == 3
    assert report.deferred == 3
    assert report.rejected == 0
    # One question fitted; the other two rulings are counted and unqueued.
    assert len(await harness.deferrals.pending(limit=10)) == 1


async def test_a_refused_ruling_stores_nothing_and_asks_nothing() -> None:
    """``rejected`` is the remainder, and it is what a ``REJECT`` lands in."""
    harness = Harness(
        reader=FakeReader(_proposals(2)),
        policy=FakeMemoryPolicy(MemoryDecisionKind.REJECT),
    )

    report = await harness.stage.ingest()

    assert report.proposed == 2
    assert report.stored == 0
    assert report.deferred == 0
    assert report.rejected == 2
    assert await harness.deferrals.pending(limit=10) == []


async def test_the_three_counts_always_partition_the_proposals() -> None:
    """``rejected`` is derived, so the numbers cannot disagree (ADR-0085 §6b)."""
    harness = Harness(reader=FakeReader(_proposals(4)))

    report = await harness.stage.ingest()

    assert report.stored + report.deferred + report.rejected == report.proposed


# --- the residual ADR-0093 §5 names, and the one it does not ------------


async def test_a_writer_failure_leaves_the_earlier_proposals_applied() -> None:
    """No transaction, and nothing claims success for a partially applied reading.

    ``MemoryStore`` offers none, so the failure propagates with what came before
    it already written — and no report is returned to say otherwise (ADR-0022 §4).
    ``assistant beliefs`` shows exactly what landed.
    """
    harness = Harness()
    failing = _FailingWriter(harness.real_writer, fail_on=2)
    harness.writes = MemoryWriteStage(writer=failing, deferrals=harness.deferrals)
    stage = IngestionStage(
        reader=FakeReader(_proposals(3)), writes=harness.writes, grants=harness.grants
    )

    with pytest.raises(MemoryStoreError):
        await stage.ingest()

    assert failing.calls == 2
    assert len(await harness.memory.search("reported thing 0", limit=10)) == 1


async def test_a_second_pass_re_reads_and_destroys_nothing_the_first_stored() -> None:
    """The guarantee ADR-0093 §5 actually relies on, and the residual it accepts.

    A reader mints its own id per record (ADR-0092 §6), so a re-read aims at
    nothing: "what a reader may rely on is that a re-read destroys nothing; what
    it may not assume is that a re-proposed entry always folds." The default
    script re-synthesises with a fresh id each pass, which is the conformant
    behaviour, and the fake policy accepts rather than folding — so this asserts
    the half that is promised, and #631 carries the half that is not.
    """
    harness = Harness()

    first = await harness.stage.ingest()
    second = await harness.stage.ingest()

    assert first.stored == 1
    assert second.stored == 1
    assert len(await harness.memory.search("reported one thing", limit=10)) == 2


# --- the gate: all five cases ADR-0097 §5 and §5a distinguish ---------------
#
# ADR-0097 §10 marks the enumeration normative and says why it is not a store
# conformance clause: all five are obligations on *this* stage, and no store
# implementation exhibits any of them. They are written against the driver, using
# the canonical fake's scripted revocation and its scripted failure.


async def test_an_ungranted_source_is_not_read_at_all() -> None:
    """Case one: no live grant at the check, so nothing is opened.

    **Refuse to read, not read-and-discard, and the difference is the whole
    point.** Opening the user's calendar is the act the grant is about; a design
    that read the file and then declined to propose from it would already have
    done the thing it was not permitted to do — and it would do it on the
    schedule. The assertion that carries this is ``call_count == 0``, not the
    empty store.
    """
    reader = FakeReader(_proposals(2))
    harness = Harness(reader=reader, grants=FakeSourceGrants())

    with pytest.raises(SourceNotGrantedError):
        await harness.stage.ingest()

    assert reader.call_count == 0
    assert harness.policy.calls == []


async def test_a_grant_for_another_use_does_not_authorise_ingestion() -> None:
    """A use a grant does not name is not authorised by it (ADR-0097 §2).

    ``FACET`` and ``INGEST`` differ in the one way a user would care about: the
    facet is transient and advisory, while ingestion writes durable beliefs that
    outlive the turn and reach ``export``. "You may look at my calendar to answer
    what I am asking now, but do not remember it" is a coherent sentence, and this
    is the stage that has to honour it.
    """
    reader = FakeReader(_proposals(1))
    grants = FakeSourceGrants([source_grant(reader.name, scope=[GrantScope.FACET])])
    harness = Harness(reader=reader, grants=grants)

    with pytest.raises(SourceNotGrantedError):
        await harness.stage.ingest()

    assert reader.call_count == 0


async def test_an_unanswerable_check_before_the_read_opens_nothing() -> None:
    """Case two: a ``live()`` that raises, so nothing is opened (ADR-0097 §5a).

    **Failing closed is stated rather than assumed, because the tempting reading
    is the other one.** "The check failed, so carry on with what we already knew"
    is what an implementer writes when the alternative looks like losing a
    scheduled run; a missed tick costs one interval, and a read on a revocation
    nobody could see costs the property the grant exists to hold.
    """
    reader = FakeReader(_proposals(2))
    grants = FakeSourceGrants([source_grant(reader.name)])
    grants.fail_live()
    harness = Harness(reader=reader, grants=grants)

    with pytest.raises(GrantError):
        await harness.stage.ingest()

    assert reader.call_count == 0


async def test_a_revocation_between_the_check_and_the_return_discards_the_reading() -> None:
    """Case three: the revocation wins, and nothing is proposed from the reading.

    A read legitimately begun while granted takes real time, and a revocation may
    land inside it. What the re-check buys is that the revocation *wins* rather
    than merely arrives: the reading's bytes are discarded rather than used —
    nothing is proposed, nothing reaches memory, and nothing durable records that
    the read happened.
    """
    reader = FakeReader(_proposals(3))
    grants = FakeSourceGrants([source_grant(reader.name)])
    grants.revoke_after(1)  # the gate's check passes; the re-check does not
    harness = Harness(reader=reader, grants=grants)

    with pytest.raises(SourceNotGrantedError):
        await harness.stage.ingest()

    assert reader.call_count == 1  # the read really did happen
    assert harness.policy.calls == []  # and nothing was proposed from it
    assert await harness.memory.search("reported thing", limit=10) == []


async def test_an_unanswerable_re_check_discards_the_reading_too() -> None:
    """Case four: a ``GrantError`` after the read is treated as a withdrawn grant.

    "No driver may proceed on a stale answer, on the earlier of two lookups, or on
    an absent one" (ADR-0097 §5a). An implementation that caught the error and
    carried on with the *first* lookup would pass every other test in this module
    while writing beliefs after its authorisation stopped being checkable.
    """

    reader = FakeReader(_proposals(3))
    grants = _FailsOnTheRecheck(FakeSourceGrants([source_grant(reader.name)]))
    harness = Harness(reader=reader, grants=grants)

    with pytest.raises(GrantError):
        await harness.stage.ingest()

    assert reader.call_count == 1
    assert harness.policy.calls == []


async def test_a_grant_live_throughout_lets_the_reading_be_used() -> None:
    """Case five: the accepting case, without which the four refusals prove nothing.

    A gate that refused everything would pass all four tests above.
    """
    reader = FakeReader(_proposals(2))
    grants = FakeSourceGrants([source_grant(reader.name)])
    harness = Harness(reader=reader, grants=grants)

    report = await harness.stage.ingest()

    assert report.stored == 2
    assert grants.call_count == 2  # checked before the read and again after it


async def test_the_refusal_names_the_identity_and_the_use_and_nothing_else() -> None:
    """ADR-0097 §8's legibility clause, which the scheduler's log line rests on.

    The scheduler logs a failed job's ``str(exc)`` verbatim (ADR-0083 §7), so this
    message *is* the log line: a path or an entry's text here would be Tier 1 data
    in an operational log, which ADR-0004 §5 forbids outright.
    """
    reader = FakeReader(_proposals(1, name="calendar"), name="calendar")
    harness = Harness(reader=reader, grants=FakeSourceGrants())

    with pytest.raises(SourceNotGrantedError) as caught:
        await harness.stage.ingest()

    message = str(caught.value)
    assert "calendar" in message
    assert GrantScope.INGEST.value in message


async def test_the_stage_cannot_record_a_grant() -> None:
    """§3's capability split, asserted where a widening would actually happen.

    A stage handed the whole store is a scheduler job that can mint its own
    authorisation, and nothing about the record would look wrong afterwards. The
    static half is ``mypy --strict`` refusing to let this stage *name* ``record``;
    what is checkable at run time is that the object it was given has no such
    member to reach, which is what the narrow canonical fake models.
    """
    harness = Harness()

    assert not hasattr(harness.grants, "record")


def test_no_await_stands_between_the_check_and_the_read() -> None:
    """ADR-0097 §5a's first clause, read off the stage's own body.

    Awaiting a coroutine does not yield to the event loop, so with nothing between
    the ``live()`` answer and ``read()`` this stage cannot sit on a stale answer at
    all. The awaits are asserted **exhaustively and in order** — gate, read,
    re-check, then the reading's write — because an extra await anywhere in this body
    is the defect whatever it happens to sit next to.

    **The per-proposal ``write`` loop became one ``write_reading``** (ADR-0115 §2),
    and this sentence records it rather than a list quietly changing. The count went
    *down*: the whole reading, including the absence reconciliation its coverage may
    warrant, is one call, because ADR-0110 §5a refuses that read-modify-write over
    anything less than a single hold of the writer's own serialisation. The span this
    test exists to protect — the ``live()`` answer through ``read()`` — is untouched,
    and the grant window is not widened: the re-check has already run and the reading
    has already been accepted, so the writes happen on the strength of a read this
    stage was permitted to take.
    """
    assert _awaited_names(IngestionStage.ingest) == ["live", "read", "live", "write_reading"]
