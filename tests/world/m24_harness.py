"""Milestone 24's read half: the world ADR-0185 §11's five arms are driven in.

§11 pre-registers the read half of #1427's exit as **five arms and five figures**,
and rules the suite "deterministic, offline and in the ordinary gate, against
``ai_assistant.testing``'s fakes and a seeded reader. No live arm is registered:
nothing in the read half depends on a model's behaviour, so ADR-0181 §8's capped
live run has no counterpart here and no lane invents one." This module is that
suite's world; :mod:`test_m24_read_trail_arms` is the five arms, and each reports
its own figure with its denominator.

**What is real here and what is a double, stated once so nobody has to infer it.**
Everything on the path the arms measure is the shipping class: the real
:class:`~ai_assistant.permissions.reads.SqliteSourceReadTrail`, the real
``CalendarContextSource`` and ``EmailContextSource``, the real ``IngestionStage``,
the real ``UpcomingEventStage``, and — in arm (c), where the subject is a *path* and
a *configured location* — the real ``CalendarReader`` over a planted ``.ics``. The
doubles are:

* **the grant seam**, wrapped so that ``live()`` can be made to answer ``None``, to
  raise, and to **suspend across a clock tick**, which §11 arm (a) requires by name;
* **the reader**, in every arm but (c), which is
  :class:`~ai_assistant.testing.FakeReader` — the "seeded reader" §11 sanctions, and
  the only way to drive ``FAILED`` from a source that failed with the bytes in hand;
* **the collaborators the read half does not rule on** — the memory write path and
  the notification writer — which are ``ai_assistant.testing``'s canonical fakes,
  each conformance-tested against its own Protocol.

``app/composition.py`` is the production wiring this mirrors: one trail object
passed to all three drivers as a ``SourceReadRecorder``. Where this harness diverges
from that root it is stated at the site.

**The clock is controlled and moves only when told**, which is what makes arm (a)'s
``checked_at`` assertion sharp rather than tautological. §11: the arm asserts each
record's instant "against the instant that clock served when the first ``live()``
answered — on a ``live()`` made to suspend across a clock tick, so a lane that read
the clock before the call fails here, and on a read whose bytes are acquired later,
so a lane that reached for ``SourceReading.read_at`` fails here too". Both traps are
armed by construction: :class:`Gate` ticks the clock *inside* its first suspension,
and :data:`READ_AT` is strictly later than any instant the clock ever serves.
"""

from __future__ import annotations

import asyncio
import contextlib
import threading
import warnings
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Final

from ai_assistant.context.sources import CalendarContextSource, EmailContextSource
from ai_assistant.core.errors import (
    GrantError,
    ReaderError,
    ReadTrailError,
    SourceNotGrantedError,
)
from ai_assistant.core.types import (
    GrantScope,
    NotificationCandidate,
    NotificationCondition,
    NotificationDisposition,
    NotificationDispositionKind,
    ReadOutcome,
)
from ai_assistant.orchestration import IngestionStage, MemoryWriteStage
from ai_assistant.orchestration.upcoming import UpcomingEventStage
from ai_assistant.permissions import SqliteSourceReadTrail
from ai_assistant.readers._source import OneWorker, ReadAlreadyOutstandingError
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
from ai_assistant.testing.cancellation import settle

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.core.protocols import Reader, SourceReadRecorder
    from ai_assistant.core.types import SourceGrant, SourceReadRecord

#: The two declared reader identities the tree actually holds (ADR-0185's Context).
#: §11 arm (a) drives "both readers", and these are the two.
CALENDAR: Final = "calendar"
EMAIL: Final = "email"

#: Where the controlled clock starts. Every attempt moves it on by one tick, so no
#: two records in one run share a ``checked_at`` and the arm can key on it.
START: Final = datetime(2026, 8, 1, 9, 0, tzinfo=UTC)

#: How far one tick moves the clock.
TICK: Final = timedelta(seconds=1)

#: The instant every seeded reading claims its bytes were acquired at. **Strictly
#: later than any instant the clock serves** in a run this suite drives, which is
#: what makes ADR-0185 §12's "never derived from ``SourceReading.read_at``" a trap a
#: wrong implementation falls into rather than a sentence nothing checks.
READ_AT: Final = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)

#: A cap far above anything arms (a), (b), (c) and (e) drive, so nothing is pruned
#: under them. §11 is explicit that "arms (a) and (b) drive fewer attempts than
#: ``source_read_trail_max_rows`` so that nothing is pruned under them, and arm (d)
#: deliberately drives more, so a completeness figure taken over arm (d) would count
#: the prune as a loss".
ROOMY: Final = 1_000

#: What the drivers raise when an attempt does not complete. Caught by
#: :meth:`World.drive` because the arms rule on the **trail**, not on the exception:
#: each driver's own module already pins which error each refusal produces.
REFUSALS: Final = (GrantError, ReaderError, SourceNotGrantedError)


class RecordingNotificationWriter:
    """A ``NotificationWriter`` that records what it was offered and rules ``HOLD``.

    ``test_upcoming.py``'s double, here because arm (e) needs to assert that **no
    candidate was concluded** from an unrecorded attempt — a claim about what the
    seam was *handed*, which the shipping ``NotificationWriteStage`` publishes
    nothing about. ``HOLD`` rather than ``INTERRUPT`` for that module's reason: the
    producer must behave identically whatever comes back.
    """

    def __init__(self) -> None:
        """Start with nothing offered."""
        self.offered: list[NotificationCandidate] = []

    async def offer(self, candidate: NotificationCandidate) -> NotificationDisposition:
        """Record the offer and rule the untuned default."""
        self.offered.append(candidate)
        return NotificationDisposition(
            kind=NotificationDispositionKind.HOLD,
            notification_id=f"n-{len(self.offered)}",
            notification_class=candidate.notification_class,
            ruled_at=READ_AT,
            reason=NotificationCondition.REACH_INTERRUPT,
            failed=(NotificationCondition.REACH_INTERRUPT,),
        )


class Clock:
    """A clock that answers a fixed instant and moves only when told.

    Fixed rather than free-running so a record's ``checked_at`` is a value an arm
    can write down, and manual rather than per-call so the *number* of reads is not
    what decides the instant — an implementation that read the clock twice would
    otherwise silently get a different answer and the assertion would be about call
    counts instead of about the clause.
    """

    def __init__(self, start: datetime = START) -> None:
        """Start at ``start``, having served nothing."""
        self.now = start
        self.calls = 0

    def tick(self) -> None:
        """Move the clock on by one :data:`TICK`."""
        self.now += TICK

    def __call__(self) -> datetime:
        """Answer, and count that a driver asked."""
        self.calls += 1
        return self.now


class Gate:
    """The grant seam an attempt is driven through, with §11's three levers.

    Wraps :class:`~ai_assistant.testing.FakeSourceGrants` rather than replacing it,
    so liveness is still decided by that fake's own conformance-tested anti-join and
    the only thing added here is *when* the seam suspends and *which* call raises.

    **The suspension is the point** (ADR-0185 §11 arm (a), §12). ``live()`` is
    ``async`` and may suspend — on the grant store's lock, on the hub's loop — so a
    clock read taken *before* the call can predate the very grant act that decided
    the outcome. :meth:`begin` arms a genuine ``await`` inside the next ``live()``
    and moves the clock across it, so a driver that stamped ``checked_at`` before
    the call records the wrong instant and arm (a) fails.
    """

    def __init__(self, clock: Clock, records: Sequence[SourceGrant] = ()) -> None:
        """Wrap a fake grant seam holding ``records``.

        Args:
            clock: The clock this seam moves across its suspension.
            records: The grant history the fake starts from.
        """
        self._clock = clock
        self.inner = FakeSourceGrants(records)
        self._tick_next = False
        self._raise_on: tuple[int, ...] = ()
        self._calls = 0

    def begin(self, *, raise_on: tuple[int, ...] = ()) -> None:
        """Arm the seam for one attempt.

        Args:
            raise_on: Which of this attempt's ``live()`` calls raise ``GrantError``,
                one-based — ``(1,)`` is ADR-0185 §1's ``UNANSWERED`` and ``(2,)`` is
                its ``UNCONFIRMED``. The two are separate members because "there was
                no live grant" and "we could not find out whether there was one" are
                different facts about the user's authorisation.
        """
        self._tick_next = True
        self._raise_on = raise_on
        self._calls = 0

    async def live(self, *, source: str, use: GrantScope) -> SourceGrant | None:
        """Answer as the fake does, having first suspended and moved the clock."""
        self._calls += 1
        if self._tick_next:
            self._tick_next = False
            # A genuine suspension, not a bare `await` on a coroutine: `sleep(0)`
            # yields to the loop, which is what `live()` really does when it waits
            # on a store's lock. The clock moves *inside* it.
            await asyncio.sleep(0)
            self._clock.tick()
        if self._calls in self._raise_on:
            msg = "harness: the grant store could not be read"
            raise GrantError(msg)
        return await self.inner.live(source=source, use=use)


class OutstandingReader:
    """A reader that refuses **before starting work** (ADR-0093 §7).

    ``OneWorker.run`` raises ``ReadAlreadyOutstandingError`` when the previous read's
    worker is still alive, and its own contract says so in three words: "**Nothing is
    started.**" That is one of the two shapes ADR-0185 §1 rules indistinguishable on
    a ``FAILED`` record, and it is driven through the *real* ``OneWorker`` rather
    than modelled, because the indeterminacy the record inherits is a property of
    that class and of ADR-0093 §8's wrapping rule rather than of this harness.
    """

    def __init__(self, name: str = CALENDAR) -> None:
        """Occupy nothing yet; :meth:`occupy` is what makes the next read refuse."""
        self._name = name
        self._worker = OneWorker(thread_name=name)
        self._release = threading.Event()
        self._outstanding: asyncio.Task[None] | None = None

    @property
    def name(self) -> str:
        """This reader's declared identity."""
        return self._name

    async def occupy(self) -> None:
        """Start a worker that stays alive until :meth:`release`.

        Deterministic rather than racy: the returned task is driven until it has
        taken ``OneWorker``'s lock and set its reservation, which happens before the
        first ``await`` inside ``run``.
        """
        self._outstanding = asyncio.ensure_future(self._worker.run(self._block, seconds=30.0))
        # `OneWorker.run` takes its lock and sets the reservation before its first
        # `await`, so letting the loop run its ready callbacks is enough — no
        # polling, and no sleep whose duration the case would depend on.
        await settle()
        assert self._worker.outstanding, "the occupying read did not take the reservation"

    def _block(self) -> None:
        """The blocking work the occupying read is parked in."""
        self._release.wait(timeout=30.0)

    async def release(self) -> None:
        """Let the occupying worker finish, and wait for it."""
        self._release.set()
        if self._outstanding is not None:
            await self._outstanding
            self._outstanding = None

    async def read(self) -> object:
        """Refuse, because a worker from an earlier read is still running.

        Wrapped as ``ReaderError`` because ADR-0093 §8 requires it — "A sensor may
        not let a source-level exception … cross the seam unwrapped" — which is
        precisely why a driver cannot tell this shape from a read that failed with
        the bytes in hand, and why ADR-0185 §1 refuses to claim either way.
        """
        try:
            return await self._worker.run(lambda: None, seconds=1.0)
        except ReadAlreadyOutstandingError as exc:
            msg = f"{self._name}: {type(exc).__name__}"
            raise ReaderError(msg) from exc


def seeded_reader(name: str = CALENDAR, *, proposals: int = 2) -> FakeReader:
    """A reader whose reading carries ``proposals`` attested beliefs, stamped later.

    :data:`READ_AT` is strictly later than any instant the controlled clock serves,
    so a driver that derived ``checked_at`` from ``SourceReading.read_at`` — which
    ADR-0185 §12 forbids — records an instant no arm expects.
    """
    return FakeReader(
        [
            attested_proposal(f"{name} reported thing {index}", reported_by=name)
            for index in range(proposals)
        ],
        name=name,
        read_at=READ_AT,
    )


def failing_reader(name: str = CALENDAR) -> FakeReader:
    """A reader that fails **with the bytes in hand** — the other ``FAILED`` shape."""
    return FakeReader(name=name, read_at=READ_AT, failure=ValueError("malformed source"))


@dataclass(frozen=True, slots=True)
class Driven:
    """One attempt the harness drove, and what it meant to drive.

    The arms compare this against the trail rather than against the driver's return
    value, which is the whole subject: ADR-0185 §10 rules that a read is
    "reconstructible from the trail alone", so an arm that read anything else would
    be measuring something the milestone does not claim.
    """

    #: Which of the three uses the attempt was for.
    use: GrantScope
    #: The reader's declared identity.
    source: str
    #: The outcome the arrangement was built to produce.
    outcome: ReadOutcome
    #: The instant the controlled clock served when the first ``live()`` resolved.
    checked_at: datetime
    #: How many items the reading carried, or zero where there was no reading.
    produced: int


class World:
    """The three real drivers over one real trail, as the composition root wires them.

    One trail object is passed to every driver as a ``SourceReadRecorder``, which is
    exactly what ``app/composition.py`` does and what ADR-0185 §4 makes sound: "a
    composition root passes one object to a driver and to the hub's operations
    alike; what the driver cannot do is *name* ``recent``."
    """

    def __init__(self, *, max_rows: int = ROOMY, clock: Clock | None = None) -> None:
        """Open an in-memory trail and the collaborators the drivers need.

        Args:
            max_rows: ADR-0185 §6's cap. Arms (a), (b), (c) and (e) run far below
                it; arm (d) sets it deliberately low.
            clock: The controlled clock; a fresh one at :data:`START` by default.
        """
        self.clock = clock if clock is not None else Clock()
        self.trail = SqliteSourceReadTrail(path=":memory:", max_rows=max_rows)
        self.memory = FakeMemoryStore(now=lambda: START)
        self.writes = MemoryWriteStage(
            writer=FakeMemoryWriter(
                store=self.memory, policy=FakeMemoryPolicy(), now=lambda: START
            ),
            deferrals=FakeDeferralStore(now=lambda: START),
        )
        self.notifications = RecordingNotificationWriter()

    def close(self) -> None:
        """Close the trail's connection."""
        self.trail.close()

    def granted(self, source: str = CALENDAR) -> Gate:
        """A gate holding a live grant covering every use of ``source``.

        ``source_grant`` names all three scopes by default, which is what lets one
        arrangement drive the same source for ``FACET``, ``INGEST`` and ``NOTIFY`` —
        ADR-0133 §2 keeps the three independent, and a grant naming one would refuse
        the other two.
        """
        return Gate(self.clock, [source_grant(source, scope=tuple(GrantScope))])

    def ungranted(self) -> Gate:
        """A gate holding no grant at all — ADR-0185 §1's ``REFUSED``."""
        return Gate(self.clock)

    def driver(
        self, use: GrantScope, *, reader: Reader, gate: Gate, recorder: SourceReadRecorder
    ) -> object:
        """The shipping driver for ``use``, wired over ``reader`` and ``gate``.

        Args:
            use: Which driver to build — ADR-0185 §5 names one per use.
            reader: The producer.
            gate: The grant seam, seen through its ``SourceGrants`` shape.
            recorder: The write seam, normally this world's own trail.

        Returns:
            The driver, whose single operation :meth:`drive` calls.
        """
        if use is GrantScope.FACET:
            builder = CalendarContextSource if reader.name == CALENDAR else EmailContextSource
            return builder(reader=reader, grants=gate, reads=recorder, now=self.clock)
        if use is GrantScope.INGEST:
            return IngestionStage(
                reader=reader,
                writes=self.writes,
                grants=gate,
                reads=recorder,
                now=self.clock,
            )
        return UpcomingEventStage(
            reader=reader,
            grants=gate,
            writer=self.notifications,
            reads=recorder,
            now=self.clock,
            lead=timedelta(minutes=30),
        )

    async def drive(  # noqa: PLR0913 — a use, a reader, a gate, the outcome driven, the calls that raise, the count expected and an optional recorder
        self,
        use: GrantScope,
        *,
        reader: Reader,
        gate: Gate,
        outcome: ReadOutcome,
        raise_on: tuple[int, ...] = (),
        produced: int = 0,
        recorder: SourceReadRecorder | None = None,
    ) -> Driven:
        """Drive one attempt to an outcome and say what was driven.

        The driver's refusal is swallowed: each driver's own module pins which error
        each refusal produces, and what these arms rule on is the **trail**.

        Args:
            use: Which of the three uses to drive.
            reader: The producer.
            gate: The grant seam, already arranged for the outcome wanted.
            outcome: What the arrangement was built to produce.
            raise_on: Which ``live()`` calls raise, one-based.
            produced: How many items the reading is expected to carry.
            recorder: The write seam; this world's trail unless a case overrides it.

        Returns:
            What was driven, for the arm to compare against the trail.
        """
        gate.begin(raise_on=raise_on)
        driver = self.driver(use, reader=reader, gate=gate, recorder=recorder or self.trail)
        with contextlib.suppress(*REFUSALS):
            await _run(driver, use)
        return Driven(
            use=use,
            source=reader.name,
            outcome=outcome,
            checked_at=self.clock.now,
            produced=produced,
        )


async def _run(driver: object, use: GrantScope) -> object:
    """Call the one operation the driver for ``use`` exposes."""
    if use is GrantScope.FACET:
        return await driver.contribute()  # type: ignore[attr-defined]  # the driver is the one this use names
    if use is GrantScope.INGEST:
        return await driver.ingest()  # type: ignore[attr-defined]
    return await driver.notice()  # type: ignore[attr-defined]


def reconstruct(records: Sequence[SourceReadRecord]) -> dict[datetime, SourceReadRecord]:
    """Index the exported rows by ``checked_at``, refusing a collision.

    One tick per attempt makes the instant unique within a run, so this is the key
    an arm reconstructs by — and a collision would silently make a completeness
    figure look green while two attempts shared one row, which is why it raises.
    """
    indexed: dict[datetime, SourceReadRecord] = {}
    for row in records:
        if row.checked_at in indexed:
            msg = f"two rows share checked_at={row.checked_at!r}; the run is not reconstructible"
            raise AssertionError(msg)
        indexed[row.checked_at] = row
    return indexed


# --- reporting --------------------------------------------------------------


#: Prefixes every reported row, so the figures are self-describing in a warnings
#: summary and greppable in a CI log.
FIGURE_BANNER: Final = "ADR-0185 §11 — milestone 24 read-half exit figures"


def report(lines: Sequence[str]) -> None:
    """Emit an arm's figure so that the run the gate actually performs shows it.

    ADR-0185 §11 requires all five figures with their denominators and forbids
    reporting the read half met "on a run that did not produce all five figures", so
    *which channel* is a correctness question rather than a presentation one — and
    the gate decides it: ``.github/workflows/gate.yml`` runs ``uv run pytest -n
    auto`` and ``just test-fast`` is xdist too, so the ordinary gate is a parallel
    run.

    **A warning rather than a write to the terminal reporter**, for the reason
    ``m23_harness.report`` records at length: an xdist *worker* has no terminal
    reporter, so every row would be dropped under the gate and each arm would pass
    reporting nothing at all. Warnings travel back to the controller in the test
    report and are rendered in the warnings summary under xdist and serial alike.

    **The category is the stdlib ``UserWarning`` and may not be a class defined
    here**, for the same module's reason: xdist serialises a warning by module and
    class name and the *controller* re-imports it, and this module reaches
    ``sys.path`` only through pytest's prepend import mode in a worker.

    Args:
        lines: The rows to report, in order.
    """
    warnings.warn("\n".join([FIGURE_BANNER, *lines]), UserWarning, stacklevel=2)


def count(hits: int, total: int) -> str:
    """One figure rendered with its denominator, which ADR-0185 §11 requires.

    A **count** rather than a share, because that is the unit §11 states all five
    figures in: "attempts driven minus records exported", "rows held beyond the
    cap", and so on.

    Args:
        hits: The numerator.
        total: The denominator.

    Returns:
        The rendered figure.
    """
    return f"{hits} of {total}"


__all__ = [
    "CALENDAR",
    "EMAIL",
    "FIGURE_BANNER",
    "READ_AT",
    "REFUSALS",
    "ROOMY",
    "START",
    "TICK",
    "Clock",
    "Driven",
    "Gate",
    "OutstandingReader",
    "ReadTrailError",
    "RecordingNotificationWriter",
    "World",
    "count",
    "failing_reader",
    "reconstruct",
    "report",
    "seeded_reader",
]
