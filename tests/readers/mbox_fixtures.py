"""Building mbox stores by hand, so each case says what it is testing.

Deliberately not a library, for ``ics_fixtures``'s reason exactly: every helper
here assembles bytes verbatim, because the point of these tests is that *this*
text produces *that* reading. A builder that normalised a header, escaped a
separator or filled in a missing field would be a second implementation of the
thing under test, sitting between the case and its subject — and the fields under
test here are precisely the ones a *fetcher* is required to get right and may not
(ADR-0140 §2, §5).

Named ``mbox_fixtures`` rather than ``test_*`` so pytest does not collect it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Final

from ai_assistant.core.types import EmailFacet
from ai_assistant.readers import DELIVERED_AT_HEADER, EmailReader

if TYPE_CHECKING:
    from pathlib import Path

    from ai_assistant.core.clock import Clock
    from ai_assistant.core.types import MemoryUpdateProposal, SourceReading

#: The instant every case's clock reads unless it says otherwise. Far from any
#: representable bound, so saturation only happens where a case asks for it.
NOW: Final = datetime(2026, 8, 3, 12, 0, tzinfo=UTC)

#: A ``Date`` earlier than :data:`NOW`, in RFC 5322's form with a determinate
#: zone. Used wherever a case is about something other than the report time.
DATE: Final = "Mon, 03 Aug 2026 11:00:00 +0000"


def delivered(moment: datetime) -> str:
    """An instant as ADR-0140 §5's closed-subset delivery header value.

    Upper-case ``T`` and ``Z``, second in ``00``-``59``, no fractional part. The
    honest fetcher's spelling, which is what every case that is *not* about the
    grammar should use.
    """
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def message(*headers: str, body: str | None = None) -> bytes:
    """One framed message: its ``From `` separator line, ``headers``, and a body.

    The separator line's own timestamp is deliberately *wrong* — a syntax no
    parser here reads — because ADR-0140 §5 forbids deriving a delivery instant
    from it, and a fixture that made it agree with the headers would let a reader
    that read the wrong line pass every case.
    """
    lines = ["From nobody@invalid Thu Jan  1 00:00:00 1970", *headers, ""]
    if body is not None:
        lines.append(body)
    return ("\n".join(lines) + "\n").encode()


def envelope(  # noqa: PLR0913 — one keyword per header a case may want to spell wrongly
    *,
    sender: str = "Alice <alice@example.com>",
    subject: str = "Standup notes",
    date: str = DATE,
    delivered_at: datetime | str = NOW,
    body: str | None = None,
    extra: tuple[str, ...] = (),
) -> bytes:
    """One ordinary message the reader proposes from, with one field overridden.

    Every argument is a spelling rather than a value, so a case can put anything
    in a header that a store can — including the values §5 skips.
    """
    stamp = delivered_at if isinstance(delivered_at, str) else delivered(delivered_at)
    return message(
        f"From: {sender}",
        f"Subject: {subject}",
        f"Date: {date}",
        f"{DELIVERED_AT_HEADER}: {stamp}",
        *extra,
        body=body,
    )


def store(directory: Path, *messages: bytes, name: str = "inbox.mbox") -> Path:
    """Write ``messages`` to one mbox file under ``directory`` and return its path."""
    path = directory / name
    path.write_bytes(b"".join(messages))
    return path


def frozen(moment: datetime = NOW) -> Clock:
    """A clock that always reads ``moment``."""
    return lambda: moment


def reader(path: Path, **overrides: object) -> EmailReader:
    """A reader over ``path`` with a frozen clock and a two-hour window.

    The narrow default window is what makes the edge cases legible: with
    :data:`NOW` at 12:00Z the window is ``[10:00, 12:00)``, so an assertion about
    "exactly at the lower edge" names an instant a reader of the test can see.
    """
    settings: dict[str, object] = {"now": frozen(), "window_past": timedelta(hours=2)}
    settings.update(overrides)
    return EmailReader(path, **settings)  # type: ignore[arg-type]


def contents(proposals: tuple[MemoryUpdateProposal, ...]) -> list[str]:
    """Every proposal's rendered content, for an order-sensitive assertion."""
    return [proposal.proposed.content for proposal in proposals]


def facet_of(reading: SourceReading) -> EmailFacet:
    """The reading's facet, asserted to be an :class:`EmailFacet` and narrowed.

    Since ADR-0140 §6 the annotation is a discriminated union, so every case
    reading a payload field has to say which member it expects — and saying it
    once here makes the expectation itself an assertion: this reader produces an
    email facet on **every** read, including the empty one, which is what keeps
    ``arrived_in_window == 0`` distinguishable from "no facet at all".
    """
    assert isinstance(reading.facet, EmailFacet), reading.facet
    return reading.facet
