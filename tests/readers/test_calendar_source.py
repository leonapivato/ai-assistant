"""ADR-0093 §7's I/O discipline: the descriptor, the cap, the worker, the deadline.

Each case below is one of the defences §7 argues at length, and the arguments are
worth keeping in view because several of them defeat the *obvious* implementation
rather than an obviously wrong one:

* a path that is absolute and readable may still be a FIFO with no writer, and
  opening a FIFO for reading **blocks until a writer appears** — so a
  regular-file check written after an ordinary open is never reached;
* a source checked for size and then read is a source that can grow or be
  replaced in between, so the cap would describe a file that no longer exists by
  the time the bytes are consumed;
* a stalled NFS or FUSE mount stays a perfectly ordinary regular file while every
  syscall against it hangs, so ``O_NONBLOCK`` closes the FIFO case and closes
  nothing else — a worker plus a deadline is what makes the hang the *reader's*
  problem instead of the process's;
* the reservation is keyed to the **worker**, not to the coroutine, so it
  survives a deadline expiry and an externally delivered cancellation alike.
"""

from __future__ import annotations

import asyncio
import os
import types
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from ics_fixtures import NOW, calendar, frozen, reader, source, utc, vevent

from ai_assistant.core.errors import ReaderError
from ai_assistant.readers import _occurrences, _source
from ai_assistant.readers import calendar as calendar_module
from ai_assistant.readers._source import (
    ReadAlreadyOutstandingError,
    ReadDeadlineExpiredError,
    SourceNotRegularFileError,
    SourceTooLargeError,
)
from ai_assistant.testing.cancellation import ThreadSuspension

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from pathlib import Path

    from ai_assistant.readers import CalendarReader

_ONE_ENTRY = calendar(vevent(f"DTSTART:{utc(NOW)}", "DURATION:PT1H", "SUMMARY:Standup"))

#: One collection as ``vdirsyncer`` 0.20.0's ``singlefile`` storage actually wrote
#: it, captured verbatim from a sync of an ``http`` remote rather than assembled
#: here. Every other fixture in this package is hand-written RFC 5545 on purpose;
#: this one is the exception, because what it pins is not the reader's handling of
#: a construct but the *shape a real co-located fetcher emits* — the arrangement
#: ADR-0095 rates strongest and `readers/calendar.py` names as the supported
#: deployment. Note what vdirsyncer's own framing does: the whole collection lands
#: in one ``VCALENDAR``, ``UID`` is moved after the payload properties, and the
#: ``http`` storage has replaced each source ``UID`` with a content hash
#: (``_ignore_uids``). None of that is ours to control, which is the point of
#: capturing it rather than writing it.
_VDIRSYNCER_SINGLEFILE = (
    b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//live-calendar-lane//EN\r\n"
    b"CALSCALE:GREGORIAN\r\n"
    b"BEGIN:VEVENT\r\nDTSTAMP:20260808T090000Z\r\nDTSTART:20260809T090000Z\r\n"
    b"DTEND:20260809T093000Z\r\nSUMMARY:Morning standup\r\nLOCATION:Room 2\r\n"
    b"UID:09a238f056952a7756f41fc56f1bd2bb78cc42e317e3238b4a9fd1621f8977a8\r\n"
    b"END:VEVENT\r\n"
    b"BEGIN:VEVENT\r\nDTSTAMP:20260808T091500Z\r\nDTSTART:20260809T140000Z\r\n"
    b"DTEND:20260809T150000Z\r\nSUMMARY:Design review\r\nLOCATION:Video call\r\n"
    b"DESCRIPTION:Dial-in 555-0100 passcode 9999\r\n"
    b"UID:198f21b93d797cf1ab2b076b09c008b58e297837f010cdeb3f3a024bf1df9a5f\r\n"
    b"END:VEVENT\r\nEND:VCALENDAR\r\n"
)

#: Noon between the two entries above, so both sit inside a four-hour window and
#: neither is at an edge — the reading below is about the *arrangement*, and an
#: entry that fell out of the window would make it about the window instead.
_VDIRSYNCER_NOW = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)

#: Short enough that a case does not wait on it, long enough that a loaded
#: machine does not fire it during an ordinary successful read.
_TIGHT_DEADLINE = timedelta(milliseconds=200)


class _Ticker:
    """Counts event-loop turns, so a case can prove the loop stayed responsive.

    The deadline clause exists because a read that ran on the loop would starve
    ADR-0083 §7's deliberately serial scheduler — taking the retention purge and
    the conversation sweep down with it, indefinitely, while every one of them
    looks merely slow. A case that only asserted the deadline fired would pass
    against exactly that implementation, because a blocked loop still eventually
    resumes.
    """

    def __init__(self) -> None:
        self.turns = 0
        self._task: asyncio.Task[None] | None = None

    async def __aenter__(self) -> _Ticker:
        self._task = asyncio.ensure_future(self._tick())
        return self

    async def __aexit__(self, *_: object) -> None:
        assert self._task is not None
        self._task.cancel()

    async def _tick(self) -> None:
        while True:
            await asyncio.sleep(0.005)
            self.turns += 1


async def _eventually_readable(subject: CalendarReader) -> None:
    """Wait until the abandoned worker has released the reservation."""
    async with asyncio.timeout(5):
        while True:
            try:
                await subject.read()
            except ReaderError as exc:
                # Only ever the reservation: any other failure here is a real one
                # and must not be retried into a timeout.
                if not isinstance(exc.__cause__, ReadAlreadyOutstandingError):
                    raise
                await asyncio.sleep(0.01)
            else:
                return


def _patch_os_open(monkeypatch: pytest.MonkeyPatch, after_open: Callable[[Path], None]) -> None:
    """Run ``after_open`` immediately after the source's descriptor is obtained.

    The module's own ``os`` binding is replaced rather than the global one, so
    nothing else in the process — pytest included — reads through the shim.
    """

    def opened(path: Path, flags: int) -> int:
        descriptor = os.open(path, flags)
        after_open(path)
        return descriptor

    monkeypatch.setattr(
        _source,
        "os",
        types.SimpleNamespace(open=opened, fstat=os.fstat, read=os.read, close=os.close),
    )


# --- the descriptor check (ADR-0093 §7) -------------------------------------


async def test_a_directory_source_is_refused_on_the_descriptor(tmp_path: Path) -> None:
    """A directory opens fine on Linux and is not a regular file.

    This is the shape ``vdirsyncer``'s **default** ``filesystem`` storage
    produces — one ``.ics`` per item — and it is refused rather than half-read.
    Widening §7 to accept it is **#649**, which reopens the byte cap's scope,
    §7b's single acquisition instant and mid-read mutation, and so is its own
    decision.
    """
    directory = tmp_path / "vdir"
    directory.mkdir()

    with pytest.raises(ReaderError) as raised:
        await reader(directory).read()

    assert isinstance(raised.value.__cause__, SourceNotRegularFileError)


async def test_a_vdirsyncer_singlefile_collection_is_read(tmp_path: Path) -> None:
    """The positive half of the case above, against bytes a real fetcher wrote.

    ADR-0095 §Context rates the co-located fetcher the stronger of the two source
    patterns, and `readers/calendar.py` names ``vdirsyncer``'s ``singlefile``
    storage as the arrangement that fits §7's regular-file check. Until this case
    existed that was an **assertion in prose on both sides** — #649 recorded it as
    "unverified in-session", and the only executable statement about vdirsyncer in
    this package was the directory *refusal* above. So the shape the deployment
    depends on was pinned nowhere, and a change that broke it would have been
    caught by no test while two docstrings went on recommending it.

    What the assertions are chosen to hold, beyond "it parses":

    * **The whole collection is one regular file**, so §7's descriptor check
      admits it — the property that distinguishes ``singlefile`` from the default
      ``filesystem`` storage and the entire reason #649 stays deferred.
    * **Every entry is proposed**, so the single wrapper is read as a collection
      rather than as one entry with trailing text.
    * **``DESCRIPTION`` reaches no belief.** It is where a calendar's most
      sensitive content lives — here a dial-in and its passcode — and
      :func:`~ai_assistant.readers.calendar._render` deliberately omits it. A
      belief is durable, retrievable and exportable, so this is a privacy property
      of the stored record and not a rendering preference.
    * **vdirsyncer's ``UID`` reaches no id.** ADR-0092 §6 forbids an ``EXTERNAL``
      producer adopting the source's key "whether directly or namespaced", and
      this fetcher's key is doubly unfit: the ``http`` storage rewrites it to a
      *content hash*, so adopting it would give a re-worded entry a new id and an
      unchanged one a stable address into a retired record.
    """
    subject = reader(
        source(tmp_path, _VDIRSYNCER_SINGLEFILE),
        now=frozen(_VDIRSYNCER_NOW),
        window_past=timedelta(hours=4),
        window_future=timedelta(hours=4),
    )

    reading = await subject.read()

    contents = [proposal.proposed.content for proposal in reading.proposals]
    assert [content.split('"')[1] for content in contents] == [
        "Morning standup",
        "Design review",
    ]
    # Every distinctive token of the `DESCRIPTION`, the bare access code included.
    # Asserting only on the formatted number and the word "passcode" would pass
    # against a renderer that reformatted one and dropped the other while still
    # emitting `9999` — which is the half of that line that actually opens a door.
    assert not any(
        token in content
        for content in contents
        for token in ("555-0100", "5550100", "passcode", "9999", "Dial-in")
    )
    assert not any(
        "09a238f056952a77" in proposal.proposed.id or "198f21b93d797cf1" in proposal.proposed.id
        for proposal in reading.proposals
    )


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="POSIX FIFOs only")
async def test_a_writer_less_fifo_fails_rather_than_hanging(tmp_path: Path) -> None:
    """The case ``O_NONBLOCK`` exists for, and the one an ordinary open never survives.

    Opening a FIFO for reading blocks until a writer appears, so a descriptor
    check written after an ordinary open is never reached and the hazard survives
    the clause written to close it. Opening non-blockingly returns immediately,
    which is what lets the regular-file test run at all — and for a regular file
    the flag is a no-op, so nothing is paid for the guard.

    The whole case is inside a five-second budget: a hang here is the failure, so
    it must be reported as one rather than as a suite that never finishes.
    """
    fifo = tmp_path / "calendar.ics"
    os.mkfifo(fifo)

    async with asyncio.timeout(5):
        with pytest.raises(ReaderError) as raised:
            await reader(fifo).read()

    assert isinstance(raised.value.__cause__, SourceNotRegularFileError)


# --- the byte cap, enforced on the read (ADR-0093 §7) -----------------------


async def test_a_source_at_the_cap_is_read_and_one_byte_over_is_refused(
    tmp_path: Path,
) -> None:
    """Refused, never truncated: a truncated reading is not a smaller calendar."""
    exact = reader(source(tmp_path, _ONE_ENTRY), max_bytes=len(_ONE_ENTRY))
    assert (await exact.read()).proposals

    tight = reader(source(tmp_path, _ONE_ENTRY), max_bytes=len(_ONE_ENTRY) - 1)
    with pytest.raises(ReaderError) as raised:
        await tight.read()

    assert isinstance(raised.value.__cause__, SourceTooLargeError)


async def test_a_source_that_grows_after_it_is_opened_is_still_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The cap is on the **read**, not on a size checked before it (ADR-0093 §7).

    A source checked for size and then read is a source that can grow or be
    replaced in between, so the cap would describe a file that no longer exists by
    the time the bytes are consumed. Growing it *after* the descriptor exists is
    exactly the window a pre-read ``stat`` cannot see — so an implementation that
    stat'd first would accept this file and read every byte of it.
    """
    path = source(tmp_path, _ONE_ENTRY)
    cap = len(_ONE_ENTRY) + 16

    def grow(source_path: Path) -> None:
        source_path.write_bytes(b"x" * (cap * 4))

    _patch_os_open(monkeypatch, grow)

    with pytest.raises(ReaderError) as raised:
        await reader(path, max_bytes=cap).read()

    assert isinstance(raised.value.__cause__, SourceTooLargeError)


# --- one clock reading, at acquisition (ADR-0093 §7b) -----------------------


async def test_the_clock_is_read_exactly_once_and_only_after_the_bytes_arrive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The reading describes the bytes returned, not the file that was there before.

    Two requirements meet here and pull apart until the capture point is named.
    *Determinism* wants a single reading, or two conforming readers given the same
    source propose different sets — and so does one reader run twice. *Truthfulness*
    wants the instant to be the one ``read_at`` claims: "the instant this system
    performed the read". Anchoring before the read satisfies the first and breaks
    the second — a capture at 10:00 that opens a file replaced at 10:05 and reads
    it at 10:10 returns proposals describing the 10:05 file stamped 10:00, with
    membership evaluated against an instant that predates the data, so a just-ended
    event is proposed as current.

    The source here is replaced between the call's start and its acquisition, which
    is the case §7b names.
    """
    path = source(tmp_path, calendar(vevent(f"DTSTART:{utc(NOW)}", "SUMMARY:Stale")))
    replacement = calendar(vevent(f"DTSTART:{utc(NOW)}", "DURATION:PT1H", "SUMMARY:Fresh"))
    real = _source.acquire
    acquired: list[bool] = []
    clock_saw_acquisition: list[bool] = []

    def swapped(source_path: Path, *, max_bytes: int) -> bytes:
        source_path.write_bytes(replacement)
        raw = real(source_path, max_bytes=max_bytes)
        acquired.append(True)
        return raw

    monkeypatch.setattr(calendar_module, "acquire", swapped)

    def clock() -> datetime:
        clock_saw_acquisition.append(bool(acquired))
        return NOW

    reading = await reader(path, now=clock).read()

    assert clock_saw_acquisition == [True], "one reading, taken after the bytes arrived"
    assert reading.read_at == NOW
    assert [proposal.proposed.content for proposal in reading.proposals] == [
        'Calendar entry "Fresh", on 2026-08-03 from 12:00 to 13:00 (UTC).'
    ]


# --- the deadline, the worker and the one-at-a-time reservation (§7) --------


@pytest.fixture
def suspended_acquire(monkeypatch: pytest.MonkeyPatch) -> Iterator[ThreadSuspension]:
    """Hold the read inside its acquisition — a regular file whose read is suspended."""
    suspension = ThreadSuspension()
    real = _source.acquire

    def held(path: Path, *, max_bytes: int) -> bytes:
        suspension.hold()
        return real(path, max_bytes=max_bytes)

    monkeypatch.setattr(calendar_module, "acquire", held)
    try:
        yield suspension
    finally:
        suspension.release()


@pytest.fixture
def suspended_expansion(monkeypatch: pytest.MonkeyPatch) -> Iterator[ThreadSuspension]:
    """Hold the read inside its *expansion* instead — §7's other half.

    An earlier draft of §7 said "filesystem work", which left the loop exposed to
    the other bounded thing this reader does: §7b's budget allows 100,000
    occurrence expansions, and an 8 MiB calendar within every stated cap can
    require them. Run on the loop after the worker returned, that CPU work starves
    the scheduler exactly as a blocked syscall does — and worse for the deadline,
    because the timer callback cannot fire while the loop is occupied, so
    ``read()`` overruns its timeout and then *returns successfully*.
    """
    suspension = ThreadSuspension()
    # Read from the defining module and patched on the *using* one: `calendar.py`
    # imports the name, so its own binding is what a read goes through.
    real = _occurrences.occurrences_in_window

    def held(raw: bytes, **figures: object) -> object:
        suspension.hold()
        return real(raw, **figures)  # type: ignore[arg-type]

    monkeypatch.setattr(calendar_module, "occurrences_in_window", held)
    try:
        yield suspension
    finally:
        suspension.release()


@pytest.mark.parametrize("gate", ["suspended_acquire", "suspended_expansion"])
async def test_a_suspended_read_expires_while_the_loop_stays_responsive(
    tmp_path: Path, request: pytest.FixtureRequest, gate: str
) -> None:
    """The deadline fires, the loop keeps turning, and a second read starts nothing.

    Both halves of the read are driven, because §7's clause covers "the whole of a
    read" and an implementation that offloaded only the I/O would pass one and fail
    the other.
    """
    suspension: ThreadSuspension = request.getfixturevalue(gate)
    subject = reader(source(tmp_path, _ONE_ENTRY), read_timeout=_TIGHT_DEADLINE)

    async with _Ticker() as ticker:
        call = asyncio.ensure_future(subject.read())
        await suspension.reached()
        with pytest.raises(ReaderError) as expired:
            await call
        assert isinstance(expired.value.__cause__, ReadDeadlineExpiredError)
        assert ticker.turns > 0, "the event loop was starved while the worker ran"

        # The reservation is released when the **worker** completes, never when
        # the coroutine exits — so it survives the deadline, and one abandoned
        # thread is the bound rather than one per tick (ADR-0093 §7, ADR-0060).
        with pytest.raises(ReaderError) as refused:
            await subject.read()
        assert isinstance(refused.value.__cause__, ReadAlreadyOutstandingError)

    suspension.release()
    await _eventually_readable(subject)


async def test_a_cancelled_read_re_raises_and_keeps_the_reservation_until_the_worker_ends(
    tmp_path: Path, suspended_acquire: ThreadSuspension
) -> None:
    """The clause §8 carves out of its own wrapping rule, and the shorter route to a leak.

    A cancelled read has, in plain English, "not completed", and a reader wrapping
    everything it catches converts it — leaving the facet degraded and the
    scheduler logging a source fault and re-arming, on a shutdown that was working
    correctly.

    Keying the reservation on the coroutine rather than the worker is reachable by
    exactly this route: a read cancelled *from outside* before its deadline must
    re-raise promptly under ADR-0060, and the worker is still in the syscall when
    it does. A guard released on "the coroutine exited" therefore clears while the
    thread is alive, and the next tick starts a second one — the unbounded growth
    the clause exists to forbid, arriving through the one exit path ADR-0060 makes
    mandatory.
    """
    subject = reader(source(tmp_path, _ONE_ENTRY), read_timeout=timedelta(seconds=30))

    call = asyncio.ensure_future(subject.read())
    await suspended_acquire.reached()
    call.cancel()

    with pytest.raises(asyncio.CancelledError):
        await call

    with pytest.raises(ReaderError) as refused:
        await subject.read()
    assert isinstance(refused.value.__cause__, ReadAlreadyOutstandingError)

    suspended_acquire.release()
    await _eventually_readable(subject)


async def test_the_reader_carries_no_lifecycle_method(tmp_path: Path) -> None:
    """``Reader`` gains **no** ``close`` and no ``aclose`` (ADR-0093 §7).

    Adding one is the obvious move and it is the wrong one: the only thing a
    ``close`` could do about a thread blocked in an uninterruptible syscall is wait
    for it, which re-creates the hang the abandonment rule removes while making it
    look handled. A seam that cannot honour a lifecycle method should not carry one.
    """
    subject = reader(source(tmp_path, _ONE_ENTRY))

    assert not hasattr(subject, "close")
    assert not hasattr(subject, "aclose")


async def test_a_worker_that_never_starts_does_not_wedge_the_reader(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The reservation is released when there is no worker to release it.

    ``_work``'s ``finally`` is the only other release, and it never runs if the
    thread never started — so a host out of thread resources would leave every
    later ``read()`` refused for an outstanding worker that does not exist, long
    after the resources recovered. ADR-0060 forbids exactly that state: a resource
    "left held with nothing running that will release it". The abandonment rule of
    §7 is only honest while the count is bounded by *running* work.
    """
    subject = reader(source(tmp_path, _ONE_ENTRY))

    class _Refuses:
        def __init__(self, **_: object) -> None:
            pass

        def start(self) -> None:
            msg = "can't start new thread"
            raise RuntimeError(msg)

    monkeypatch.setattr(_source, "threading", types.SimpleNamespace(Thread=_Refuses))
    with pytest.raises(ReaderError) as raised:
        await subject.read()
    assert isinstance(raised.value.__cause__, RuntimeError)

    monkeypatch.undo()
    # Not refused, and not by having waited: the reservation was never left held.
    assert (await subject.read()).proposals
