"""CalendarReader passes the shared Reader suite, plus the clauses only it can.

The binding is the point of a *shared* suite: a clause either binds every
implementation or binds none, so the concrete reader is held to exactly what the
canonical fake is held to (``tests/core/test_fake_reader.py``).

Below the binding are the obligations ADR-0093 §10 names as **not** suite clauses
and hands to this lane, tracked by **#648**:

* that a *real* missing, unreadable or malformed source is what raises — three
  cases, "so the lane writes all three rather than the one that is easiest to
  provoke";
* that the underlying failure survives as ``__cause__``;
* that the message is **payload-free**.

None is reachable generically, and ``ReaderContract.failing_reader``'s docstring
says why for each: a suite cannot make an arbitrary implementation's source fail,
a reader that detects a malformed document by its own validation has no underlying
exception to preserve, and payload-freeness cannot be decided without knowing what
the payload would have been — which is the source's secret.
"""

from __future__ import annotations

import sys
from pathlib import Path as _Path
from typing import TYPE_CHECKING

import pytest
from ics_fixtures import NOW, STAMP, calendar, frozen, reader, source, utc, vevent

sys.path.insert(0, str(_Path(__file__).resolve().parent.parent / "core"))

from reader_contract import GatedRead, ReaderContract

from ai_assistant.core.errors import ReaderError
from ai_assistant.readers import CALENDAR_READER_NAME, CalendarReader, _source
from ai_assistant.readers import calendar as calendar_module
from ai_assistant.testing.cancellation import ThreadSuspension

if TYPE_CHECKING:
    from pathlib import Path

    from ai_assistant.core.protocols import Reader

#: A distinctive title, used twice: once so a malformed source's parser failure
#: has something quotable to leak, and once so a case can prove it did not.
SENSITIVE_TITLE = "Oncology follow-up with Dr Halvorsen"


def _root(exc: BaseException) -> BaseException:
    """The deepest link of an exception's cause chain."""
    while exc.__cause__ is not None:
        exc = exc.__cause__
    return exc


_ONE_ENTRY = calendar(
    vevent(f"DTSTART:{utc(NOW)}", "DURATION:PT1H", "SUMMARY:Standup"),
)


class TestCalendarReaderContract(ReaderContract):
    """Runs CalendarReader through the shared Reader conformance suite."""

    @pytest.fixture(autouse=True)
    def _levers(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # `gated_read` is a plain method rather than a fixture, so the two levers
        # it needs are parked here where pytest can still undo the patch.
        self._tmp = tmp_path
        self._monkeypatch = monkeypatch

    @pytest.fixture
    def reader(self, tmp_path: Path) -> Reader:
        return reader(source(tmp_path, _ONE_ENTRY))

    @pytest.fixture
    def empty_reader(self, tmp_path: Path) -> Reader:
        return reader(source(tmp_path, calendar(), name="empty.ics"))

    @pytest.fixture
    def failing_reader(self, tmp_path: Path) -> Reader:
        return reader(tmp_path / "absent.ics")

    def gated_read(self) -> GatedRead:
        """A read held inside the acquisition it is performing.

        Suspending :func:`~ai_assistant.readers._source.acquire` rather than
        contriving a slow file is what makes the case deterministic — and it holds
        the read at exactly the place a real one blocks, on the worker thread,
        which is the code the cancellation clause is about.
        """
        suspension = ThreadSuspension()
        real = _source.acquire

        def held(path: Path, *, max_bytes: int) -> bytes:
            suspension.hold()
            return real(path, max_bytes=max_bytes)

        self._monkeypatch.setattr(calendar_module, "acquire", held)
        return GatedRead(
            reader=reader(source(self._tmp, _ONE_ENTRY, name="gated.ics")), gate=suspension
        )


# --- the three failure cases ADR-0093 §10 names by name (#648) --------------


async def test_a_missing_source_raises(tmp_path: Path) -> None:
    """A file that is not there is an ordinary state of the world, not a defect.

    A reader's source is a file the system does not own, so unreadability is
    expected — which is why ADR-0083 §7 logs and retries rather than exiting, and
    why ADR-0093 §7 checks existence at run time rather than refusing to start.
    """
    with pytest.raises(ReaderError) as raised:
        await reader(tmp_path / "absent.ics").read()

    assert isinstance(_root(raised.value), FileNotFoundError)


async def test_an_unreadable_source_raises(tmp_path: Path) -> None:
    """A permission denial is a different operator action from a missing file.

    Preserving ``__cause__`` is what keeps the wrapping from destroying the
    diagnosis: ADR-0083 §7 logs a failed job "with its class", and a missing file,
    a permission denial and a malformed document are three different things to do
    about it.
    """
    path = source(tmp_path, _ONE_ENTRY)
    path.chmod(0o000)
    try:
        with pytest.raises(ReaderError) as raised:
            await reader(path).read()
    finally:
        path.chmod(0o600)

    assert isinstance(_root(raised.value), PermissionError)


async def test_a_malformed_source_raises(tmp_path: Path) -> None:
    """A source that cannot be parsed **at all** raises; a gap inside one does not.

    The distinction is between a read that *completed with gaps* and one that
    *could not complete* (ADR-0093 §7b), and it is ADR-0074 §5's rule carried
    unchanged.
    """
    raw = f"BEGIN:VCALENDAR\r\nSUMMARY:{SENSITIVE_TITLE}\r\nthis is not iCalendar\r\n".encode()

    with pytest.raises(ReaderError) as raised:
        await reader(source(tmp_path, raw, name="broken.ics")).read()

    assert raised.value.__cause__ is not None


# --- §8's two neighbouring obligations on that raise (#648) -----------------


async def test_the_underlying_failure_survives_as_the_cause(tmp_path: Path) -> None:
    """``__cause__`` is the whole diagnosis, and wrapping must not destroy it."""
    with pytest.raises(ReaderError) as raised:
        await reader(tmp_path / "absent.ics").read()

    chain: list[BaseException] = []
    current: BaseException | None = raised.value
    while current is not None:
        chain.append(current)
        current = current.__cause__

    assert any(isinstance(link, FileNotFoundError) for link in chain), chain


async def test_a_missing_paths_failure_does_not_put_that_path_in_the_message(
    tmp_path: Path,
) -> None:
    """The message an operator's log receives names no file (ADR-0093 §8, ADR-0004 §5).

    ``raise ReaderError(str(exc)) from exc`` satisfies every word of §8's wrapping
    rule and, for a missing ``/home/alice/Private/therapy.ics``, produces a message
    that **is** that path — which ADR-0083 §7 then writes to a log. A filename is
    chosen by the user and a directory names them, so the path gets the same
    treatment as the identity rather than a weaker one for having arrived inside
    an exception.
    """
    path = tmp_path / "Private" / "therapy.ics"
    path.parent.mkdir()

    with pytest.raises(ReaderError) as raised:
        await reader(path).read()

    message = str(raised.value)
    assert str(path) not in message
    assert path.name not in message
    assert str(tmp_path) not in message
    # Identity and classes, which is the whole of what §8 permits — and the
    # cause's class is the useful half, because it tells an operator which action
    # to take and they already know the path, having configured it.
    assert message.startswith(f"{CALENDAR_READER_NAME}: ")
    assert "FileNotFoundError" in message


async def test_a_malformed_sources_message_quotes_neither_the_source_nor_the_cause(
    tmp_path: Path,
) -> None:
    """Neither the entry's title nor the parser's own message reaches the message.

    The title is the source's *contents*, which §8 forbids as squarely as it
    forbids the location — and the parser's message is where a title would arrive
    from, since a parse error quotes the line it choked on.
    """
    raw = (
        f"BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nSUMMARY:{SENSITIVE_TITLE}\r\n"
        f"DTSTART:not-a-date\r\nEND:VEVENT\r\n"
    ).encode()
    path = source(tmp_path, raw, name="broken.ics")

    with pytest.raises(ReaderError) as raised:
        await reader(path).read()

    message = str(raised.value)
    assert SENSITIVE_TITLE not in message
    assert "Halvorsen" not in message
    assert str(raised.value.__cause__) not in message
    assert str(path) not in message


def test_the_declared_identity_is_a_constant_and_not_the_source(tmp_path: Path) -> None:
    """A reader that wraps personal data names *itself*, never the data it holds.

    The identity lands on the reading, on ``Attestation.reported_by`` of every
    belief the gate then stores, in every export and in every log line — in a
    system whose ADR-0004 §5 rule is that logs never contain Tier 1 data. So it is
    a **declared constant**, which cannot carry personal data at all: a property
    rather than a rule (ADR-0093 §7).
    """
    path = source(tmp_path, _ONE_ENTRY, name="alice-work-calendar.ics")

    subject = CalendarReader(path, now=frozen())

    assert subject.name == "calendar"
    assert path.name not in subject.name
    assert str(tmp_path) not in subject.name


async def test_every_proposal_is_attested_to_the_entrys_own_dtstamp(tmp_path: Path) -> None:
    """``reported_at`` is the source's clock, and never a local proxy.

    ADR-0093 §10 is normative that "for the calendar sensor that value is the
    occurrence's ``DTSTAMP``", and ADR-0092 §3 permits no substitute — "not our
    clock, not the ingest instant, and in particular **not the file's mtime**,
    which is a property of the last local write and is changed by a copy, a
    restore or a ``touch``".
    """
    reading = await reader(source(tmp_path, _ONE_ENTRY)).read()

    (proposal,) = reading.proposals
    attestation = proposal.proposed.provenance.attestation
    assert attestation is not None
    assert utc(attestation.reported_at) == STAMP
    assert attestation.reported_at < reading.read_at
    assert proposal.proposed.provenance.last_updated == reading.read_at


async def test_the_confirming_instant_is_the_sources_report_and_never_our_read(
    tmp_path: Path,
) -> None:
    """ADR-0109 §4's ``ATTESTED`` arm, at the producer that owns the band.

    The ``ATTESTED`` band's confirming event is the reporting source's report,
    "whose instant is ``Attestation.reported_at`` (ADR-0092 §3) and never our
    ingestion of it" (ADR-0103 §9). So ``last_confirmed_at`` is the ``DTSTAMP``,
    the same value the attestation carries.

    This reader is where the suite proves the field is **not** transaction time
    (ADR-0109 §10's third clause), because it is the producer whose two instants a
    fixture can hold apart: ``last_updated`` is ``read_at`` and the confirming
    instant is the source's, and :data:`STAMP` is months earlier. A currency read
    off ``last_updated`` would call a months-old report imported this morning
    perfectly fresh, which is the case ADR-0103 §9 gives in terms.

    The coincidence with ``attestation.reported_at`` is exempt from ADR-0109 §10's
    distinctness rule and has to be: §4 has this producer set the field *to* that
    value, so a rule requiring the two to differ would forbid the behaviour this
    test exists to pin. ``read_at`` is the instant the code could have reached for
    instead, and the fixture holds *that* apart.
    """
    reading = await reader(source(tmp_path, _ONE_ENTRY)).read()

    (proposal,) = reading.proposals
    provenance = proposal.proposed.provenance
    assert provenance.last_confirmed_at is not None
    assert utc(provenance.last_confirmed_at) == STAMP
    assert provenance.last_confirmed_at != reading.read_at
    assert provenance.last_confirmed_at != provenance.last_updated


async def test_a_dtstamp_in_our_future_is_stored_unchanged_and_not_clamped(
    tmp_path: Path,
) -> None:
    """ADR-0109 §4's fourth clause, at the producer ADR-0092 §3 wrote it for.

    A producer "writes its band's instant as it stands and applies no usability
    test to it": source clocks skew, a ``reported_at`` in our future "is not
    refused" (ADR-0092 §3), and dropping or clamping one here would destroy the
    very value the fold needs to compare. The usability test belongs to the fold
    alone, where two candidates exist; at the producer there is one.

    Three separate outcomes are refused, because each is a way a careful
    implementer might have "helped": ``None``, ``read_at``, and a clamp to
    ``read_at``. Asserting the exact stamp rules out all three at once.
    """
    ahead = "20270101T000000Z"
    entry = calendar(vevent(f"DTSTART:{utc(NOW)}", "DURATION:PT1H", "SUMMARY:Standup", stamp=ahead))

    reading = await reader(source(tmp_path, entry)).read()

    (proposal,) = reading.proposals
    provenance = proposal.proposed.provenance
    assert provenance.last_confirmed_at is not None
    assert utc(provenance.last_confirmed_at) == ahead
    assert provenance.last_confirmed_at > reading.read_at


async def test_an_entry_with_no_dtstamp_is_skipped_rather_than_given_a_local_time(
    tmp_path: Path,
) -> None:
    """No report time means no attestation, so the entry is not proposed at all.

    ADR-0092 §3: "Where the source genuinely says nothing about when it spoke, the
    producer has no attestation to make, and §1's validator then settles the
    outcome structurally rather than by discretion." Skipping is §7b's rule for an
    entry a parseable source contains but the reader cannot interpret.
    """
    stamped = vevent(f"DTSTART:{utc(NOW)}", "DURATION:PT1H", "SUMMARY:Kept", uid="a")
    unstamped = "\r\n".join(
        [
            "BEGIN:VEVENT",
            "UID:b",
            f"DTSTART:{utc(NOW)}",
            "DURATION:PT1H",
            "SUMMARY:Dropped",
            "END:VEVENT",
        ]
    )

    reading = await reader(source(tmp_path, calendar(stamped, unstamped))).read()

    assert [proposal.proposed.content for proposal in reading.proposals] == [
        'Calendar entry "Kept", on 2026-08-03 from 12:00 to 13:00 (UTC).'
    ]


async def test_each_read_mints_a_fresh_opaque_id_and_never_the_vevent_uid(
    tmp_path: Path,
) -> None:
    """An ``EXTERNAL`` producer mints its own id, opaque to the source (ADR-0092 §6).

    The source's key may never be the store's key, "whether directly or
    namespaced", and nor may an id *derived* from content (ADR-0081 §8). A derived
    id is an **address**, aimed at the same record on every re-read — which is the
    ADR-0038 §2a resurrection where a re-sync recomputes a retired record's id and
    erases its closed validity window through ``ACCEPT``'s blind upsert. "Minting
    removes the aim."
    """
    subject = reader(source(tmp_path, calendar(vevent(f"DTSTART:{utc(NOW)}", uid="vevent-uid-1"))))

    first = await subject.read()
    second = await subject.read()

    (one,) = first.proposals
    (two,) = second.proposals
    assert one.proposed.id != two.proposed.id
    assert "vevent-uid-1" not in one.proposed.id
    assert one.proposed.content == two.proposed.content


async def test_a_malformed_mint_fails_rather_than_becoming_a_key(tmp_path: Path) -> None:
    """The id factory is guarded at its **output** (ADR-0092 §6, ADR-0045 §4)."""
    subject = reader(source(tmp_path, _ONE_ENTRY), id_factory=lambda: "   ")

    with pytest.raises(ReaderError) as raised:
        await subject.read()

    assert isinstance(raised.value.__cause__, ValueError)
