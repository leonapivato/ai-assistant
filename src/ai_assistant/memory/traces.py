"""ADR-0119 §8's two `memory` emitters: the relevance read and the write path.

§8 names four seams and two of them are here — "``memory``'s relevance read emits
one ``RETRIEVAL`` trace per ``search``" and "``memory``'s write path emits one
``MEMORY_WRITE`` trace per ``MemoryWriter.ingest``". This module holds what the
two share: the envelope, the subordination, the outcome discriminator and the
literal metric keys. The two emitting methods hold what is theirs — the counts
only they can see.

**The store emits its own retrieval trace and that placement is forced** (§8).
The candidate count and the per-predicate exclusion counts "do not exist outside
the store", so a trace emitted one layer up "would satisfy the letter of 'we have
retrieval telemetry' and be blind to the exact thing #824 watches for". ADR-0128
§1 has since moved every one of those predicates *ahead* of the ranking cut, which
takes all four counts to a structural zero and changes nothing about where the
trace is emitted: what only the store can see is now the candidate set itself.

**Everything here is subordinate to the work it observes** (§5). No trace failure
propagates: not a clock that will not read, not a mapper that raises, not an id
set that will not validate, not a store that will not write. What a lost trace
costs is a Tier 2 log record naming the kind, the seam and the failure's class,
because "a missing trace is indistinguishable from a non-event".

**Nothing here reads a datum.** Every string this module can put in a trace is a
literal constant below, a ``StrEnum`` member from ``core/types.py``, a record id
the store minted, or an exception class name through §3's total conversion. No
query text, no record content, no policy reason, no exception message (§2).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import timedelta
from time import perf_counter
from typing import TYPE_CHECKING, Final

import structlog

from ai_assistant.core.clock import checked_clock
from ai_assistant.core.correlation import current_correlation
from ai_assistant.core.errors import SelfConsumingWriteError, UnresolvedEvidenceError
from ai_assistant.core.types import (
    TRACE_RECORD_SET_CAP,
    EvaluationTrace,
    MemoryDecisionKind,
    RecordIdSet,
    TraceKind,
    TraceOutcome,
    TraceRecordSet,
    TraceRef,
    fault_class_of,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping, Sequence

    from ai_assistant.core.clock import Clock
    from ai_assistant.core.protocols import TraceSink
    from ai_assistant.core.types import UtcInstant

_log = structlog.get_logger(__name__)

#: The event name an emission failure is logged under (ADR-0119 §5). Duplicated
#: from ``ai_assistant.evaluation``'s durable store and from
#: ``orchestration/traces.py`` rather than imported, for the reason the canonical
#: fakes duplicate it too: golden rule 1 forbids `memory` naming another
#: subsystem's concrete module, and a shared constant there would be exactly that
#: import. An operator greps one string and finds every lost trace, whichever side
#: lost it.
TRACE_NOT_RECORDED: Final = "trace_not_recorded"

#: What the log record carries in place of a seam that is not a representable
#: label, so an unvalidated string never reaches a Tier 2 log (ADR-0004 §5).
#: Duplicated from the durable store for :data:`TRACE_NOT_RECORDED`'s reason.
UNREADABLE_TRACE_FIELD: Final = "unreadable"

#: The seam pattern, duplicated from ``core/types.py``'s private ``_TRACE_LABEL``
#: for the one use :func:`_dropped` has for it. Importing the original would be
#: reaching into another module's internals for a two-token regex, and the
#: duplication is checked by a test that builds a trace with a seam this accepts.
_SEAM_LABEL: Final = re.compile(r"[a-z][a-z0-9_]{0,63}")

# --- the seam labels (§2's second clause: a literal constant in this module) ---

#: ``MemoryStore.search`` — one crossing, one ``RETRIEVAL`` trace (§8).
SEAM_SEARCH: Final = "memory_search"

#: ``MemoryWriter.ingest`` — one proposal, one ``MEMORY_WRITE`` trace (§8).
SEAM_INGEST: Final = "memory_ingest"

#: ``MemoryWriter.ingest_reading`` — **one crossing and one trace**, "not one per
#: resulting ``MemoryIngestResult``, following §5's one-crossing rule; the
#: per-reading counts ride as metrics" (§8).
#:
#: **This label is where "the write's mode" §8 requires lands.** The envelope has
#: no enum-valued field to put a mode in — ``metrics`` values are
#: ``int | float | bool`` and ``refs`` values are identifiers — and the seam label
#: is the axis §3 already gives a measure to filter on ("distinguished by the seam
#: label and the outcome"). Two labels for the two ``MemoryWriter`` members is
#: therefore the mode, carried where a measure can group by it.
SEAM_INGEST_READING: Final = "memory_ingest_reading"

# --- the retrieval metric keys ------------------------------------------------

#: The ``limit`` the caller asked for. Observed before any work, so it is on the
#: fault-path trace too — §8 names it there by name.
LIMIT: Final = "limit"

#: The ceiling the KNN was actually asked for, after sqlite-vec's ``k`` clamp. Not
#: derivable from :data:`LIMIT` once the clamp binds, and the clamp is now the only
#: thing between the two: ADR-0128 §1 removed the over-fetch multiplier along with
#: the post-cut pass it padded for, so ``fetch_k`` below ``limit`` says the store's
#: candidate ceiling bound the read — the same fact ``capped`` reports to the
#: caller, from the offline side.
FETCH_K: Final = "fetch_k"

#: The candidate count the store fetched (§8). Since ADR-0128 §1 every one of them
#: is *eligible*: the predicates bind before the cut, so this counts rows the caller
#: could have been served rather than rows the store was about to sift.
CANDIDATES: Final = "candidates"

#: How many records the read returned (§8).
RETURNED: Final = "returned"

# --- the four exclusion counts ------------------------------------------------
# **All four are structural zeros** since ADR-0128 §1 (§3's first clause). Every
# read-time eligibility predicate binds before the ranking cut, so no candidate is
# ever dropped for any of them and the rows that would have been counted are never
# fetched. Each store writes them as **literals** rather than as counters that can
# only stay at zero, so nobody later "fixes" a dead increment back into a post-cut
# eligibility pass and reintroduces the failure ADR-0113 §2 and #457 describe.
#
# **They are kept rather than dropped, and that is a decision** (ADR-0128 §3, on
# #829's window). ADR-0119 §8 requires a count per read-time predicate; ADR-0120
# §7's population is *defined* as the traces carrying these keys. Dropping three of
# them would put every trace before the pre-filter and every trace after it in
# different populations — making the before/after unreadable at exactly the moment
# it matters — and would make "nothing was dropped" and "no candidate set existed"
# the same record. Held at zero, the same population spans the change and the
# counters going to zero on a date **is** the observation.
#
# **The zero is not the placeholder ADR-0119 §3 forbids.** §3's rule is about a
# quantity the event did not reach; these four decompose the candidate set the same
# trace reports, so they stand or fall together — which is why all four are absent
# *together* on the fault and short-circuit paths, where no candidate set exists.

#: Candidates dropped because their ``kind`` was not among those asked for (§8).
#: Structurally zero — see above.
EXCLUDED_KIND: Final = "excluded_kind"

#: Candidates dropped by ADR-0007's ``expires_at`` — §8's "retention" predicate.
#: Structurally zero — see above.
EXCLUDED_RETENTION: Final = "excluded_retention"

#: Candidates dropped by ADR-0045 §6's validity window, either end (§8). The one
#: #824's trigger watched, which is why it is counted apart from the other two —
#: and the reason that watch is retired rather than redefined (ADR-0128 §3): its
#: window share had this count as its numerator, so after §1 it is undefined over
#: an empty set rather than merely uninformative. Structurally zero — see above.
EXCLUDED_WINDOW: Final = "excluded_window"

#: Candidates dropped by the belief-band predicate (§8), and the count that was
#: structurally zero *first* — ADR-0113 §2 bound the band before the ranking cut
#: three ADRs before ADR-0128 §1 joined the other three to it. Structurally zero —
#: see above.
#:
#: **What it does not mean.** It is not a count of records the band kept out of the
#: *store's* answer — that population is filtered inside the KNN, is unbounded, and
#: could only be counted by a second vector search on the interactive read path.
#: :data:`BANDS` is what says a restriction was in force at all. The same now holds
#: of the other three.
EXCLUDED_BAND: Final = "excluded_band"

#: How many bands the caller restricted the read to, absent when it restricted
#: none. Beside :data:`EXCLUDED_BAND`'s structural zero this is the figure that
#: carries the information: a measure reading ``excluded_band = 0`` learns that no
#: *candidate* was dropped for its band, and reads here whether a band predicate was
#: bound before the cut at all.
BANDS: Final = "bands"

# --- the write metric keys ----------------------------------------------------

#: How many proposals the crossing was handed. Observed before any work — one for
#: :data:`SEAM_INGEST`, the reading's own count for :data:`SEAM_INGEST_READING` —
#: so it is on the fault-path trace too, as :data:`LIMIT` is on retrieval's.
PROPOSALS: Final = "proposals"

#: Whether the reading declared a coverage, and so whether ADR-0110's
#: reconciliation was in scope at all. Observed at entry, like :data:`PROPOSALS`.
COVERAGE_DECLARED: Final = "coverage_declared"

#: How many windows the reading's coverage closed (ADR-0110 §3). Observed only
#: where a reconciliation ran, so absent on :data:`SEAM_INGEST` and on an
#: uncovered reading.
CLOSED: Final = "closed"

#: One literal key per ``MemoryDecisionKind``, because §2's second clause makes a
#: metric key "a literal constant written in the emitting module" — an
#: ``f"decisions_{kind.value}"`` would be a key composed at runtime, which is the
#: shape that clause exists to keep out even when the value it is composed from is
#: harmless. Totality over the enum is asserted by test rather than by
#: construction, so a member added later fails loudly here instead of silently
#: dropping a count.
DECISION_METRICS: Final[Mapping[MemoryDecisionKind, str]] = {
    MemoryDecisionKind.ACCEPT: "decisions_accept",
    MemoryDecisionKind.REJECT: "decisions_reject",
    MemoryDecisionKind.REINFORCE: "decisions_reinforce",
    MemoryDecisionKind.SUPERSEDE: "decisions_supersede",
    MemoryDecisionKind.ASK_USER: "decisions_ask_user",
    MemoryDecisionKind.STORE_TEMPORARY: "decisions_store_temporary",
}

#: The exception classes `memory`'s traced seams raise to mean **"no, and that is
#: the right answer"**, as against "something broke" (§3, ADR-0111 §9).
#:
#: **It fails towards ``FAULT``**, exactly as ``orchestration``'s tuple does: an
#: unlisted class is recorded as a fault, so a refusal nobody classified looks
#: noisier than it is and a fault nobody classified never looks quieter than it
#: is. Under-reporting a fault is the direction that costs an operator something.
#:
#: **The membership test is ``isinstance``, so the tuple names only subclasses
#: whose own descendants are refusals too.** ``MemoryStoreError`` is *not* here
#: and cannot be: it is raised both by a broken disk and by four of this
#: subsystem's own refusals — the secret-tier write (ADR-0078 §5b), the conflict
#: ceiling (ADR-0079 §1), the unsafe fold (ADR-0045 §5) and the unretirable window
#: (ADR-0080 §3). §3 binds the discriminator to the exception's **class** and
#: nothing else, so one class gets one reading, and the fail-towards-``FAULT``
#: rule decides which. Those four therefore trace as faults; splitting them out
#: would be a ``core/errors.py`` change, which is not this lane's to make.
#:
#: ``MemoryStoreConflictError`` is left off for the same rule read the same way.
#: From ``_install`` it is a refusal a producer is told to answer by re-minting
#: (ADR-0108 §2), but from ``_apply_supersede`` the same class means a bounded
#: re-mint loop was exhausted, which is a malfunction. One class, one reading,
#: and ``FAULT`` is the direction that does not hide the second case.
_REFUSALS: Final[tuple[type[Exception], ...]] = (
    # ADR-0077 §5: a `DERIVED` proposal whose warrant does not exist is
    # inadmissible rather than rule-able, and the refusal is deliberately a raise
    # "rather than a fabricated `REJECT`". Answered, not broken.
    UnresolvedEvidenceError,
    # ADR-0081 §1 / ADR-0116 §2: a write that would stand as its own warrant is
    # refused, and ADR-0116's title calls it "a refusal a producer can survive".
    # `FoldOntoCitedRecordError` is a subclass and inherits the reading.
    SelfConsumingWriteError,
)


@dataclass(frozen=True, slots=True)
class Reading:
    """What one traced memory crossing observed about itself.

    The emitting method builds this from quantities only it can see, and this
    module turns it into a trace. Splitting it that way is what keeps §5's
    guarded region around *every* step that can fail: a mapper that raises, an id
    set that will not validate and a sink that will not write are all one lost
    trace and never a lost read or a lost write.

    Attributes:
        metrics: Numbers and booleans the crossing observed, under the literal
            keys above. A quantity the crossing did not reach is **absent**,
            never zero (§3's observation rule).
        records: Ids the crossing produced, per disposition, **raw** — repeats and
            all, uncapped. :func:`_capped` is the one place that de-duplicates,
            caps and derives ``total``, so no caller can report a truncation that
            did not happen, miss one that did, or lose a whole trace to a repeat
            §3 forbids the type to carry. An absent key means the set was not
            observed; a key mapped to an empty sequence means it was observed and
            was empty (§3).
    """

    metrics: Mapping[str, int | float | bool] = field(default_factory=dict)
    records: Mapping[TraceRecordSet, Sequence[str]] = field(default_factory=dict)


#: What a crossing with nothing further to say observes.
_NOTHING_FURTHER: Final = Reading()


class MemoryTraces:
    """Emits one trace per crossing of one `memory` seam (ADR-0119 §8).

    One instance per emitting object and per kind: the store holds a
    ``RETRIEVAL`` one, the ingestor a ``MEMORY_WRITE`` one. The kind is fixed at
    construction rather than passed per call because §3 makes it the axis the
    tier discipline is stated along, and a caller that could choose it could put
    a write's ids on a retrieval's kind.
    """

    def __init__(self, *, kind: TraceKind, sink: TraceSink, now: Clock, owner: str) -> None:
        """Wire the emitter to its seam, its kind and its clock.

        Args:
            kind: What every trace from this emitter records.
            sink: The trace store's **append** seam — a
                :class:`~ai_assistant.core.protocols.TraceSink` and never a
                ``TraceStore``, because ADR-0119 §7 gives an emitter the write and
                withholds the walk: "no component of the request pipeline… holds a
                seam carrying the walk, and none reads a trace back". The
                narrowing is this annotation.
            now: The clock the instant is stamped from. §3 puts the stamp on the
                emitter rather than on the store, because a store stamping on
                append "would measure the write rather than the event". Guarded by
                :func:`~ai_assistant.core.clock.checked_clock` (ADR-0026 §7) like
                every other injected clock in this subsystem.
            owner: The label the clock guard's diagnostic names, so a bad reading
                says which seam read it.
        """
        self._kind = kind
        self._sink = sink
        self._now = checked_clock(now, owner=owner)

    async def observing[T](
        self,
        seam: str,
        work: Awaitable[T],
        observe: Callable[[T], Reading],
        *,
        entry: Mapping[str, int | float | bool] | None = None,
        partial: Callable[[], Reading] | None = None,
    ) -> T:
        """Await ``work`` and record exactly one trace for it.

        **No correlation scope is opened here** (§4). An operation is an
        ``AssistantEngine`` call, so the one place a scope legitimately opens is
        that boundary; this reads the ambient identifier and records the answer,
        or omits the reference when there is none — a hub startup, a test driving
        a store directly. "``None`` is the honest answer outside an operation."

        **A cancellation is never classified** (§3, ADR-0060 §1). ``except
        Exception`` does not catch ``CancelledError``, which is a
        ``BaseException``, so an externally delivered cancellation leaves here
        untouched and no trace records it.

        Args:
            seam: Which crossing this is — a literal constant above.
            work: The crossing itself. Passed as an already-constructed coroutine,
                which does not begin running until it is awaited here, so a
                caller's ADR-0065 input observation still happens on the caller's
                own first executed lines.
            observe: How to read what ``work`` returned into the trace.
            entry: Quantities observed *before* the work, so they are carried on
                the fault path too — §8 requires exactly that of a retrieval's
                ``limit``.
            partial: What the crossing had reached when it failed, for a crossing
                that can leave work **applied** behind a raise. ``None`` for one
                that cannot, where the entry quantities are the whole of the fault
                path.

                Not an optimisation: an ``ingest_reading`` whose second proposal
                refuses has already committed its first, and a trace carrying no
                ``WRITTEN`` id would say a record that is live was never written.
                §3's absent key means *not observed*, so omitting an id the
                crossing did observe is the instrument denying the work — the
                fabrication §8's fault-path paragraph refuses in the other
                direction, arriving through a partial commit instead of a zero.

        Returns:
            Whatever ``work`` returned, untouched.
        """
        occurred_at = self._stamped(seam)
        started = perf_counter()
        try:
            result = await work
        except Exception as error:
            await self._record(
                seam,
                occurred_at=occurred_at,
                started=started,
                outcome=TraceOutcome.REFUSED
                if isinstance(error, _REFUSALS)
                else TraceOutcome.FAULT,
                reading=self._merged(seam, entry, partial),
                fault_class=fault_class_of(error),
            )
            raise
        await self._record(
            seam,
            occurred_at=occurred_at,
            started=started,
            outcome=TraceOutcome.OK,
            reading=self._merged(seam, entry, lambda: observe(result)),
        )
        return result

    def _stamped(self, seam: str) -> UtcInstant | None:
        """The instant the crossing began, or ``None`` if the clock would not read.

        Read **before** the work, so ``occurred_at`` plus ``elapsed`` is the
        crossing's interval and the ``OPERATION`` trace above it can bound this
        one. A clock that raises costs the trace and not the read (§5), so the
        failure is logged here and the absence travels to :meth:`_record`.

        Args:
            seam: Which crossing this is, for the log record.

        Returns:
            The reading, or ``None``.
        """
        try:
            return self._now()
        # Broad by design: §5 lets no clock fault reach the work being observed.
        except Exception as error:
            _dropped(self._kind, seam, error)
            return None

    def _merged(
        self,
        seam: str,
        entry: Mapping[str, int | float | bool] | None,
        produce: Callable[[], Reading] | None,
    ) -> Reading:
        """The entry quantities, with whatever the crossing itself observed on top.

        One helper for both paths, so the success reading and the partial one
        cannot drift in how they merge or in how they fail.

        A mapper is first-party code in this package, so a raise here is a bug
        rather than an environmental failure — but §5 admits no exception for
        first-party bugs, and losing a write because its counters would not
        convert is exactly the inversion that clause forbids. The entry
        quantities survive a mapper that raises, because they were observed
        before it ran.

        Args:
            seam: Which crossing this is, for the log record.
            entry: Quantities observed before the work.
            produce: The crossing's own reading, or ``None`` where it has none —
                a fault path with nothing applied behind it.

        Returns:
            The merged reading, or the entry quantities alone.
        """
        if produce is None:
            return Reading(metrics=dict(entry or {}))
        try:
            reading = produce()
        # Broad by design: §5 lets no mapper bug reach the work being observed.
        except Exception as error:
            _dropped(self._kind, seam, error)
            reading = _NOTHING_FURTHER
        return Reading(metrics={**(entry or {}), **reading.metrics}, records=reading.records)

    async def _record(  # noqa: PLR0913 — one parameter per field of the one trace
        self,
        seam: str,
        *,
        occurred_at: UtcInstant | None,
        started: float,
        outcome: TraceOutcome,
        reading: Reading,
        fault_class: str | None = None,
    ) -> None:
        """Build the trace and append it, letting nothing out (ADR-0119 §5).

        Construction is guarded as well as emission, because §2's and §3's
        constraints are enforced *at construction*: a metric key that is not a
        label, a non-finite value, an id set holding a repeat. Each is an emitter
        bug, and each must cost a trace rather than a read or a write.

        ``elapsed`` comes from :func:`time.perf_counter` rather than from the
        clock: it is a duration, and a wall clock stepping backwards mid-crossing
        would produce a negative one the model refuses, losing the trace to a fact
        about the machine's clock rather than about the work.

        Args:
            seam: Which crossing this is.
            occurred_at: When it began, or ``None`` if the clock would not read —
                in which case there is nothing to write and the loss is logged.
            started: The monotonic reading taken at the same moment.
            outcome: What the crossing did.
            reading: What it observed.
            fault_class: The class of the exception that decided a failing
                outcome, through §3's total conversion; ``None`` otherwise.
        """
        if occurred_at is None:
            return
        correlation = current_correlation()
        try:
            trace = EvaluationTrace(
                kind=self._kind,
                seam=seam,
                occurred_at=occurred_at,
                elapsed=timedelta(seconds=max(perf_counter() - started, 0.0)),
                outcome=outcome,
                fault_class=fault_class,
                refs={} if correlation is None else {TraceRef.CORRELATION: correlation},
                records={key: _capped(ids) for key, ids in reading.records.items()},
                metrics=reading.metrics,
            )
        # Broad by design: §5 makes a malformed trace a lost trace, not a failed read.
        except Exception as error:
            _dropped(self._kind, seam, error)
            return
        try:
            await self._sink.emit(trace)
        # Broad by design: §7 says a conforming sink cannot raise here, and §5 says
        # what to do if one does anyway.
        except Exception as error:
            _dropped(self._kind, seam, error)


def _capped(ids: Sequence[str]) -> RecordIdSet:
    """One disposition's ids, de-duplicated and under §3's cap.

    **The de-duplication is the load-bearing half, and it is not defensive.** §3
    rules that "a ``RecordIdSet`` carries each id **at most once**" and the type
    enforces it — so a repeat is not a trace with a redundant entry, it is a trace
    that fails construction and is lost under §5. One ``ingest_reading`` reaches
    that honestly: two proposals of one reading may both ``REINFORCE`` the same
    standing belief, and both results then name the same id. Losing the whole
    crossing's trace because a writer did its job twice is exactly the instrument
    lying that §5 exists to prevent.

    **What is de-duplicated is the id set and never the counts.** The two
    reinforcements are two rulings and stay two in ``decisions_reinforce``; what
    collapses is only the answer to "which records ended up in this state", which
    is a set by §3's own definition.

    **Ordered**, via ``dict.fromkeys``, because §3 wants the ids "in the order the
    observed operation produced them" and a repeat should not move the first
    occurrence.

    ``total`` is the cardinality of that set, so "where that total exceeds the cap
    it holds the first 256, and the set is **truncated** exactly when ``total``
    exceeds the number of ids it carries". Truncation is derived rather than
    flagged, and derived here rather than at each call site, so no emitter can
    report one that did not happen.

    Args:
        ids: Every id the crossing produced under this disposition, in order.

    Returns:
        The capped set.
    """
    distinct = tuple(dict.fromkeys(ids))
    return RecordIdSet(ids=distinct[:TRACE_RECORD_SET_CAP], total=len(distinct))


def _dropped(kind: TraceKind, seam: str, error: Exception) -> None:
    """Log a trace that could not be recorded (ADR-0119 §5).

    "Emission failure is never silent", because "a measure over a stream with
    dropped rows reports a smaller numerator and does not know it". The three keys
    are Tier 2 by construction: the kind is an enum member, the seam is bounded by
    the same pattern the type enforces, and the error's **class** goes through §3's
    total conversion rather than being read raw — ADR-0004 §5 is unconditional that
    logs are Tier 2 only, so the bound §2 puts on a trace's ``fault_class`` has to
    hold on this side of the seam too. The message never appears.

    Args:
        kind: What the lost trace would have recorded.
        seam: Which crossing it was about.
        error: Why it was not recorded.
    """
    _log.warning(
        TRACE_NOT_RECORDED,
        kind=str(kind),
        seam=seam if _SEAM_LABEL.fullmatch(seam) else UNREADABLE_TRACE_FIELD,
        error_class=fault_class_of(error),
    )


__all__ = [
    "BANDS",
    "CANDIDATES",
    "CLOSED",
    "COVERAGE_DECLARED",
    "DECISION_METRICS",
    "EXCLUDED_BAND",
    "EXCLUDED_KIND",
    "EXCLUDED_RETENTION",
    "EXCLUDED_WINDOW",
    "FETCH_K",
    "LIMIT",
    "PROPOSALS",
    "RETURNED",
    "SEAM_INGEST",
    "SEAM_INGEST_READING",
    "SEAM_SEARCH",
    "TRACE_NOT_RECORDED",
    "UNREADABLE_TRACE_FIELD",
    "MemoryTraces",
    "Reading",
]
