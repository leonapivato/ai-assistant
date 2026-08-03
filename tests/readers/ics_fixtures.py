"""Building `.ics` sources by hand, so each case says what it is testing.

Deliberately not a library: every helper here is one line of RFC 5545 assembled
verbatim, because the point of these tests is that *this* text produces *that*
reading. A builder that normalised anything would be a second implementation of
the thing under test, sitting between the case and its subject.

Named ``ics_fixtures`` rather than ``test_*`` so pytest does not collect it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Final

from ai_assistant.readers import CalendarReader

if TYPE_CHECKING:
    from pathlib import Path

    from ai_assistant.core.clock import Clock

#: The instant every case's clock reads unless it says otherwise. A Monday, so a
#: weekly rule's phase is easy to reason about, and far from any representable
#: bound so saturation only happens where a case asks for it.
NOW: Final = datetime(2026, 8, 3, 12, 0, tzinfo=UTC)

#: A ``DTSTAMP`` earlier than :data:`NOW`, which is the normal case rather than an
#: anomaly: Monday's report, revised into the store on Tuesday (ADR-0092 §3).
STAMP: Final = "20260101T000000Z"


def calendar(*events: str) -> bytes:
    """Wrap ``events`` in a minimal ``VCALENDAR``."""
    body = "".join(f"{event}\r\n" for event in events)
    return (
        f"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//ai-assistant tests//EN\r\n"
        f"{body}END:VCALENDAR\r\n"
    ).encode()


def vevent(*lines: str, uid: str = "e1", stamp: str = STAMP) -> str:
    """One ``VEVENT`` carrying ``lines``, with a ``UID`` and a ``DTSTAMP``."""
    return "\r\n".join(["BEGIN:VEVENT", f"UID:{uid}", f"DTSTAMP:{stamp}", *lines, "END:VEVENT"])


def utc(moment: datetime) -> str:
    """An instant as an RFC 5545 UTC ``DATE-TIME``."""
    return moment.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def source(directory: Path, raw: bytes, *, name: str = "calendar.ics") -> Path:
    """Write ``raw`` to a file under ``directory`` and return its path."""
    path = directory / name
    path.write_bytes(raw)
    return path


def frozen(moment: datetime = NOW) -> Clock:
    """A clock that always reads ``moment``."""
    return lambda: moment


def reader(path: Path, **overrides: object) -> CalendarReader:
    """A reader over ``path`` with a frozen clock and a two-hour window each way.

    The narrow default window is what makes the edge cases legible: with
    :data:`NOW` at 12:00Z the window is ``[10:00, 14:00)``, so an assertion about
    "exactly at the lower edge" names an instant a reader of the test can see.
    """
    settings: dict[str, object] = {
        "now": frozen(),
        "window_past": timedelta(hours=2),
        "window_future": timedelta(hours=2),
    }
    settings.update(overrides)
    return CalendarReader(path, **settings)  # type: ignore[arg-type]


def summaries(proposals: object) -> list[str]:
    """Every proposal's rendered content, for an order-sensitive assertion."""
    return [proposal.proposed.content for proposal in proposals]  # type: ignore[attr-defined]
