"""The one shape rule both readers apply to what they compose (#1449).

``readers/_compose.py`` states it: a reader's composed ``content`` is one line,
every line boundary the source supplied is removed, and every other byte survives
verbatim. These cases pin the rule itself, pin it at **both** readers, and pin the
two things it deliberately does *not* do — the quotation mark and ``NUL`` come out
the other side untouched, because ADR-0183 §8 rules that a reader's composition is
not an escaping and because a span that merely *looks* neutralised is the worse of
the two errors that section names.

**What "identical from both readers" can and cannot mean, stated here because the
difference is a finding rather than a wrinkle.** The rule is one function and both
readers call it, so the same characters are removed at both. What *reaches* it is
each parser's business, and the two parsers destroy different things first:
``compat32`` substitutes a replacement character per byte of a header value it
cannot decode as ASCII, so ``U+2028`` never arrives at an email header value as
``U+2028`` at all (``test_a_header_carrying_undecodable_bytes_still_encodes`` in
``test_email_headers.py`` pins that coercion), and a bare carriage return costs the
whole message before any field is read (below). So the cross-reader case is stated
over the characters both parsers can actually carry, and the rest are pinned
against ``one_line`` directly, which is where the rule lives.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Final

import pytest
from ics_fixtures import NOW as CALENDAR_NOW
from ics_fixtures import calendar, source, summaries, utc, vevent
from ics_fixtures import reader as calendar_reader
from mbox_fixtures import DATE, NOW, contents, delivered, message, store
from mbox_fixtures import reader as email_reader

from ai_assistant.readers import DELIVERED_AT_HEADER
from ai_assistant.readers._compose import one_line

if TYPE_CHECKING:
    from pathlib import Path

#: Well inside the email reader's default two-hour window, whose upper edge is
#: exclusive at :data:`NOW`.
INSIDE: Final = NOW - timedelta(hours=1)

#: Every character ``one_line`` removes, spelled out here rather than imported
#: from the module under test: a case that took the set from its own subject would
#: pass against a subject that removed nothing.
BOUNDARIES: Final = ("\n", "\r", "\v", "\f", "\x1c", "\x1d", "\x1e", "\x85", "\u2028", "\u2029")

#: Characters that survive, each a decision rather than an oversight. ``"`` is the
#: delimiter both readers wrap a span in, and ADR-0183 §8 names delimiting
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


async def _email_content(directory: Path, *headers: str, name: str) -> list[str]:
    """Every belief a one-message store carrying ``headers`` composes."""
    raw = message(
        *headers,
        f"Date: {DATE}",
        f"{DELIVERED_AT_HEADER}: {delivered(INSIDE)}",
    )
    reading = await email_reader(store(directory, raw, name=name)).read()
    return contents(reading.proposals)


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


async def test_both_readers_remove_the_same_characters_from_the_span_they_compose(
    tmp_path: Path,
) -> None:
    """#1449's divergence, closed: one span, two readers, the same neutralised text.

    The span carries only what **both** parsers deliver intact — RFC 5545's
    ``\\n`` escape decodes to a real line feed, the email side folds to reach one,
    and the C0 members pass through ``compat32`` and ``icalendar`` alike — so a
    difference in the outcome here would be a difference in the rule rather than
    in the two parsers.
    """
    carried = ("\v", "\f", "\x1c", "\x1d", "\x1e")
    survives = _span('"', "\x00")
    header = "Subject: " + _span(*carried, '"', "\x00")

    from_calendar = await _calendar_content(
        tmp_path, _span("\\n", *carried, '"', "\x00"), name="one-rule.ics"
    )
    from_email = await _email_content(
        tmp_path, "From: Alice", header, "\tcontinued", name="one-rule.mbox"
    )

    assert from_calendar == [f'Calendar entry "{survives}", at 2026-08-03 12:00 (UTC).']
    assert from_email == [
        f'Email from "Alice" with subject "{survives}\tcontinued", '
        "delivered 2026-08-03 11:00 (UTC)."
    ]
    for content in (*from_calendar, *from_email):
        assert len(content.splitlines()) <= 1, content


@pytest.mark.parametrize(
    ("case", "summary"),
    [
        ("an RFC 5545 line-feed escape", "a\\nb"),
        ("a raw line separator", _span("\u2028")),
        ("a raw paragraph separator", _span("\u2029")),
        ("a raw next line", _span("\x85")),
        ("a raw form feed", _span("\f")),
    ],
)
async def test_a_calendar_summary_no_longer_carries_a_break_into_a_belief(
    tmp_path: Path, case: str, summary: str
) -> None:
    """The half of #1449 that was a breach rather than a divergence.

    Before this, ``_occurrences._text`` was the whole of the calendar's extraction
    — ``"" if value is None else str(value)`` — so an adversary-chosen ``SUMMARY``
    put its own line structure inside the sentence the reader composed, while the
    email reader removed one from a header value. Each case is a spelling a source
    can actually reach: RFC 5545 decodes ``\\n`` in a TEXT property into a real
    line feed, and the rest ride inside the content line as themselves, because
    none of them is the ``CRLF`` that ends one.
    """
    composed = await _calendar_content(tmp_path, summary, name="break.ics")

    assert composed == ['Calendar entry "ab", at 2026-08-03 12:00 (UTC).'], case


async def test_a_bare_carriage_return_in_a_header_costs_the_message_before_the_rule_runs(
    tmp_path: Path,
) -> None:
    """Not this rule's doing, and pinned so that it is not read as this rule's doing.

    ``_header_block`` deliberately does not treat a lone ``\\r`` as a line
    boundary, because ``mailbox.mbox`` does not — but ``BytesParser`` beneath it
    does, so the header block ends at the carriage return and the two headers
    carrying instants land past it. ``_interpret`` then skips the message under
    ADR-0140 §5, which is fail-closed, which is why it is #1463 rather than a fix
    in this change.
    """
    composed = await _email_content(tmp_path, "From: Alice", "Subject: a\rb", name="bare-cr.mbox")

    assert composed == []


async def test_a_quotation_mark_and_a_nul_survive_both_readers(tmp_path: Path) -> None:
    """The characters this rule deliberately leaves alone (ADR-0183 §8).

    A reader that removed the quotation mark would be delimiting untrusted text
    with a delimiter it had just made unforgeable — a defence only if a consumer
    may parse the composition for its spans, and §8's second clause says no
    consumer may. Asserting the survival is what stops a later lane adding the
    strip as an obvious improvement.
    """
    hostile = 'a" with subject "b\x00c'

    from_calendar = await _calendar_content(tmp_path, hostile, name="survivors.ics")
    from_email = await _email_content(
        tmp_path, "From: Alice", f"Subject: {hostile}", name="survivors.mbox"
    )

    assert from_calendar == [f'Calendar entry "{hostile}", at 2026-08-03 12:00 (UTC).']
    assert from_email == [
        f'Email from "Alice" with subject "{hostile}", delivered 2026-08-03 11:00 (UTC).'
    ]
