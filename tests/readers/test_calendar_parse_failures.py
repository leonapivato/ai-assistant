"""The parse seam's own failure class, and the three states it has to keep apart.

``SourceNotParseableError`` (``readers/_occurrences.py``) was asserted nowhere in
this tree until #1281 — neither for the zero-byte source nor for a malformed
document. ``test_calendar_contract.py`` covers a malformed source's *shape* (it
raises, its cause survives, its message quotes neither the source nor the parser),
but never its class or the message text, so a parser upgrade that reclassified an
unreadable document would leave every existing case green.

What that unpins is a deployment claim, not an implementation detail.
``readers/calendar.py``'s module docstring tells an operator that
``vdirsyncer discover`` alone is not enough (#890): the collection it creates is
**zero bytes**, and zero bytes is not an iCalendar document, so a hub armed
between ``discover`` and the first ``sync`` fails every tick with
``calendar: SourceNotParseableError (ValueError)``. The paragraph's whole point is
that three states an operator can be in are *distinguishable* — path absent,
path present but pre-sync, and a genuinely empty calendar — and only the third is
a success. A parser that accepted ``b""`` as an empty calendar would collapse the
second into the third, make the documented ordering advice wrong, and break
nothing that any test could see.

The **message text** is asserted deliberately rather than incidentally. ADR-0093
§8 makes it a ruled surface: ``CalendarReader._failure`` emits this reader's
identity and the two class names and never ``str(cause)``, because for a missing
``/home/alice/Private/therapy.ics`` the cause's ``str`` *is* that path, and
ADR-0083 §7 writes this message to an operational log that ADR-0004 §5 forbids
Tier 1 data in.

Refs #1281, #890, #1273, PR #1275.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

import pytest
from ics_fixtures import calendar, reader, source

from ai_assistant.core.errors import ReaderError
from ai_assistant.readers import CALENDAR_READER_NAME
from ai_assistant.readers._occurrences import SourceNotParseableError

if TYPE_CHECKING:
    from pathlib import Path

#: The whole of what a failed parse is permitted to say (ADR-0093 §8): this
#: reader's declared identity, the failure's class, and the cause's class.
_PARSE_FAILURE_MESSAGE: Final = f"{CALENDAR_READER_NAME}: SourceNotParseableError (ValueError)"

#: What ``vdirsyncer discover calendar`` leaves behind. ``SingleFileStorage``
#: creates the collection through ``checkfile(path, create=True)``, which opens
#: the path ``"wb"`` and closes it — so the file an operator checks for is there,
#: and holds nothing.
_DISCOVERED_BUT_UNSYNCED: Final = b""

#: A collection truncated mid-write: the ``VCALENDAR`` opens, a ``VEVENT`` opens
#: inside it, and neither closes. This is the *non-empty* malformed case, kept
#: distinct from the zero-byte one because a guard written as ``if not raw`` would
#: pass the first and a guard written as ``if b"END:VCALENDAR" not in raw`` would
#: pass neither — and only one of those two is the parser doing its job.
_TRUNCATED: Final = b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:e1\r\n"

#: Bytes with no iCalendar framing at all — a fetcher that wrote an error page,
#: or a path pointing at the wrong file entirely.
_NOT_ICALENDAR_AT_ALL: Final = b"<html><body>404 Not Found</body></html>\r\n"

#: A calendar that is genuinely empty, once a sync has landed: well-formed, and
#: carrying no ``VEVENT``. The contrast case, and the only one of the four that is
#: a success.
_SYNCED_AND_EMPTY: Final = calendar()


#: The three unparseable shapes, shared by both cases below so neither can drift
#: into covering a subset of the other.
_UNPARSEABLE: Final = [
    pytest.param("discovered.ics", _DISCOVERED_BUT_UNSYNCED, id="zero-byte"),
    pytest.param("truncated.ics", _TRUNCATED, id="truncated"),
    pytest.param("not-icalendar.ics", _NOT_ICALENDAR_AT_ALL, id="not-icalendar"),
]


def _chain(exc: BaseException) -> list[type[BaseException]]:
    """Every class on an exception's ``__cause__`` chain, outermost first."""
    classes: list[type[BaseException]] = []
    current: BaseException | None = exc
    while current is not None:
        classes.append(type(current))
        current = current.__cause__
    return classes


@pytest.mark.parametrize(("name", "raw"), _UNPARSEABLE)
async def test_an_unparseable_source_raises_the_parse_seams_own_class(
    tmp_path: Path, name: str, raw: bytes
) -> None:
    """Three ways to be unreadable, one class, and the cause preserved beneath it.

    ADR-0093 §7b's distinction is between a read that *completed with gaps* and one
    that *could not complete*: an entry a parseable source contains but this reader
    cannot interpret is skipped, and a source that cannot be parsed at all raises.
    These are the second kind, and the assertion is on the class rather than on the
    mere fact of raising, because every reachable failure of this reader raises —
    the class is what tells an operator which of them happened.

    The chain is asserted at its first three links rather than whole. Those three
    are ours — the wrap, the seam's class, and the ``ValueError`` the message
    promises — while anything below them belongs to ``icalendar``, which nests as
    deeply as its own parse happened to fail and is free to change that between
    versions. Pinning the tail would make a dependency bump a test failure
    describing nothing.
    """
    with pytest.raises(ReaderError) as raised:
        await reader(source(tmp_path, raw, name=name)).read()

    assert _chain(raised.value)[:3] == [ReaderError, SourceNotParseableError, ValueError]


@pytest.mark.parametrize(("name", "raw"), _UNPARSEABLE)
async def test_an_unparseable_sources_message_is_the_documented_text(
    tmp_path: Path, name: str, raw: bytes
) -> None:
    """The exact string ``readers/calendar.py`` quotes to an operator, verbatim.

    An operator reading the deployment note is told to expect
    ``calendar: SourceNotParseableError (ValueError)`` in the log and to conclude
    "no sync has landed yet". That makes the message a documented interface rather
    than incidental output, so it is pinned as equality: a message that gained a
    path, a parser's complaint or an entry's title would still *contain* the class
    names, and containment is exactly the assertion that would not notice.
    """
    with pytest.raises(ReaderError) as raised:
        await reader(source(tmp_path, raw, name=name)).read()

    assert str(raised.value) == _PARSE_FAILURE_MESSAGE
    assert str(tmp_path) not in str(raised.value)
    assert str(raised.value.__cause__) not in str(raised.value)


async def test_a_synced_but_empty_collection_is_a_success_with_no_proposals(
    tmp_path: Path,
) -> None:
    """The third state, and the one the other two must not be confused with.

    ADR-0093 §8: an empty ``proposals`` tuple is a **success** and means the source
    had nothing to propose. ``test_calendar_contract.py``'s ``empty_reader`` runs
    this through the shared suite's own clauses; it is restated here because what
    this module is about is the *boundary* between it and the failure above, and a
    boundary asserted from one side only is half a test.
    """
    reading = await reader(source(tmp_path, _SYNCED_AND_EMPTY, name="empty.ics")).read()

    assert reading.proposals == ()


async def test_the_three_deployment_states_are_told_apart(tmp_path: Path) -> None:
    """Absent, discovered-but-unsynced, and synced-and-empty, in one case.

    The deployment note's claim is comparative — running ``discover`` without
    ``sync`` is "the half of this ordering that surprises", because the path an
    operator checks for is there and the read still fails — and no per-state case
    can go green while that claim is false. A parser that treated ``b""`` as an
    empty calendar would leave all three of the cases above passing except this
    one, which is why it exists as its own case rather than as a comment.
    """
    absent = tmp_path / "absent.ics"
    unsynced = source(tmp_path, _DISCOVERED_BUT_UNSYNCED, name="unsynced.ics")

    with pytest.raises(ReaderError) as missing:
        await reader(absent).read()
    with pytest.raises(ReaderError) as pre_sync:
        await reader(unsynced).read()
    landed = await reader(source(tmp_path, _SYNCED_AND_EMPTY, name="landed.ics")).read()

    assert not absent.exists()
    assert unsynced.exists()
    assert (
        str(missing.value) == f"{CALENDAR_READER_NAME}: SourceUnavailableError (FileNotFoundError)"
    )
    assert str(pre_sync.value) == _PARSE_FAILURE_MESSAGE
    assert str(missing.value) != str(pre_sync.value)
    assert landed.proposals == ()
