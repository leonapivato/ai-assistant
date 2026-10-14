"""The one shape rule a reader applies to what it composes (#1449).

``readers/_compose.py`` states it: a reader's composed ``content`` is one line,
every line boundary the source supplied is removed, and every other byte survives
verbatim. These cases pin the rule itself, pin it at the calendar reader, and pin
the two things it deliberately does *not* do — the quotation mark and ``NUL`` come
out the other side untouched, because ADR-0183 §8 rules that a reader's
composition is not an escaping and because a span that merely *looks* neutralised
is the worse of the two errors that section names.

What *reaches* the rule is the parser's business, so the reader's cases are stated
over the characters ``icalendar`` actually carries into a ``SUMMARY``, and the rest
are pinned against ``one_line`` directly, which is where the rule lives.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

import pytest
from ics_fixtures import NOW as CALENDAR_NOW
from ics_fixtures import calendar, source, summaries, utc, vevent
from ics_fixtures import reader as calendar_reader

from ai_assistant.readers._compose import one_line

if TYPE_CHECKING:
    from pathlib import Path

#: Every character ``one_line`` removes, spelled out here rather than imported
#: from the module under test: a case that took the set from its own subject would
#: pass against a subject that removed nothing.
BOUNDARIES: Final = ("\n", "\r", "\v", "\f", "\x1c", "\x1d", "\x1e", "\x85", "\u2028", "\u2029")

#: Characters that survive, each a decision rather than an oversight. ``"`` is the
#: delimiter the reader wraps a span in, and ADR-0183 §8 names delimiting
#: untrusted text with a delimiter untrusted text may contain as not a defence —
#: removing it would buy a consumer nothing while teaching it that something had
#: been bought. ``NUL``, ``DEL`` and the rest of the C0 set are here for the same
#: reason: a partial filter reads as a control-character defence and is none.
SURVIVORS: Final = ('"', "\x00", "\x7f", "\x01", "\t", " ")


def _span(*characters: str) -> str:
    """``characters`` between two letters they cannot be confused with."""
    return "a" + "".join(characters) + "b"


async def _calendar_content(directory: Path, summary: str, *, name: str) -> list[str]:
    """Every belief a one-entry calendar carrying ``summary`` composes."""
    raw = calendar(
        vevent(
            f"SUMMARY:{summary}",
            f"DTSTART:{utc(CALENDAR_NOW)}",
            f"DTEND:{utc(CALENDAR_NOW)}",
        )
    )
    reading = await calendar_reader(source(directory, raw, name=name)).read()
    return summaries(reading.proposals)


def test_one_line_removes_every_boundary_and_preserves_everything_else() -> None:
    """The rule, at the one place it is implemented.

    Character by character rather than over one mixed string, so a failure names
    which character the rule stopped covering.
    """
    for boundary in BOUNDARIES:
        assert one_line(_span(boundary)) == "ab", f"{boundary!r} is a line boundary"
    for survivor in SURVIVORS:
        assert one_line(_span(survivor)) == _span(survivor), f"{survivor!r} is not"

    once = one_line(_span(*BOUNDARIES, *SURVIVORS))
    assert once == "a" + "".join(SURVIVORS) + "b"
    assert one_line(once) == once, "the removal is idempotent"
    assert len(once.splitlines()) <= 1, "one line, by Python's own reckoning"


@pytest.mark.parametrize(
    ("case", "summary"),
    [
        ("an RFC 5545 line-feed escape", "a\\nb"),
        ("a raw line separator", _span("\u2028")),
        ("a raw paragraph separator", _span("\u2029")),
        ("a raw next line", _span("\x85")),
        ("a raw form feed", _span("\f")),
        ("the C0 separators", _span("\v", "\x1c", "\x1d", "\x1e")),
    ],
)
async def test_a_calendar_summary_no_longer_carries_a_break_into_a_belief(
    tmp_path: Path, case: str, summary: str
) -> None:
    """The half of #1449 that was a breach rather than a divergence.

    Before this, ``_occurrences._text`` was the whole of the calendar's extraction
    — ``"" if value is None else str(value)`` — so an adversary-chosen ``SUMMARY``
    put its own line structure inside the sentence the reader composed. Each case
    is a spelling a source can actually reach: RFC 5545 decodes ``\\n`` in a TEXT
    property into a real line feed, and the rest ride inside the content line as
    themselves, because none of them is the ``CRLF`` that ends one.
    """
    composed = await _calendar_content(tmp_path, summary, name="break.ics")

    assert composed == ['Calendar entry "ab", at 2026-08-03 12:00 (UTC).'], case


async def test_a_quotation_mark_and_a_nul_survive_the_reader(tmp_path: Path) -> None:
    """The characters this rule deliberately leaves alone (ADR-0183 §8).

    A reader that removed the quotation mark would be delimiting untrusted text
    with a delimiter it had just made unforgeable — a defence only if a consumer
    may parse the composition for its spans, and §8's second clause says no
    consumer may. Asserting the survival is what stops a later lane adding the
    strip as an obvious improvement.
    """
    hostile = 'a" at "b\x00c'

    from_calendar = await _calendar_content(tmp_path, hostile, name="survivors.ics")

    assert from_calendar == [f'Calendar entry "{hostile}", at 2026-08-03 12:00 (UTC).']
