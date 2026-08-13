"""ADR-0140 §5's header rules: what is read under which rule, and what is skipped.

§5 divides a message's fields into two classes and gives each its own rule, and
almost every way of getting this wrong passes the other file's tests:

* ``X-Assistant-Delivered-At`` and ``Date`` each carry an **instant**, so each
  must be present exactly once and resolve determinately or the message is
  skipped. Nothing is substituted for a fact the source did not make, and a skip
  raises nothing.
* the sender and the subject carry no instant and are **never on their own a
  reason to skip**: absent or duplicated, they are empty, with no selection made
  among the candidates.

The delivery header's grammar is a **closed subset** of RFC 3339 rather than RFC
3339 minus a list, and the accept/reject boundary has to be that subset rather
than whichever library a lane reached for. Both directions are asserted, and the
accepting one is not redundant: every skip clause here is satisfied by a reader
that skips everything, so without it the subset is pinned only from outside and
its inside is a lane's guess.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from mbox_fixtures import DATE, NOW, contents, delivered, envelope, facet_of, message, reader, store

from ai_assistant.readers import DELIVERED_AT_HEADER

if TYPE_CHECKING:
    from pathlib import Path

#: An instant inside the fixtures' ``[10:00, 12:00)`` window, so every case below
#: turns on the header's *spelling* rather than on membership.
INSIDE = NOW - timedelta(hours=1)

#: The same instant as the honest fetcher spells it, for the cases that vary one
#: character of it.
INSIDE_STAMP = delivered(INSIDE)


async def _proposals(tmp_path: Path, *messages: bytes) -> tuple[str, ...]:
    """Read a store of ``messages`` and return each proposal's rendered content."""
    reading = await reader(store(tmp_path, *messages)).read()
    assert facet_of(reading).arrived_in_window == len(reading.proposals)
    return tuple(contents(reading.proposals))


# --- the delivery header: zero, two, or unusable is a skip -------------------


@pytest.mark.parametrize(
    ("case", "headers"),
    [
        ("none at all", ()),
        (
            "two of them",
            (f"{DELIVERED_AT_HEADER}: {INSIDE_STAMP}", f"{DELIVERED_AT_HEADER}: {INSIDE_STAMP}"),
        ),
        (
            "two disagreeing",
            (
                f"{DELIVERED_AT_HEADER}: {INSIDE_STAMP}",
                f"{DELIVERED_AT_HEADER}: 2020-01-01T00:00:00Z",
            ),
        ),
        ("unparseable", (f"{DELIVERED_AT_HEADER}: last tuesday",)),
        ("empty", (f"{DELIVERED_AT_HEADER}:",)),
    ],
)
async def test_an_unusable_delivery_header_is_skipped_never_defaulted(
    tmp_path: Path, case: str, headers: tuple[str, ...]
) -> None:
    """ADR-0140 §5: no fallback dates a message the fetcher did not stamp.

    **The duplicate arm is fail-closed and is the whole point.** The fetcher
    strips every copy the message itself carried before writing its own; where
    that strip has failed, taking the *first* occurrence would make forgery
    **work**, because the attacker writes theirs above the fetcher's and ordering
    decides membership. Skipping costs an attacker their own message — which is
    not an attack — and costs an honest deployment nothing, because an honest
    fetcher writes exactly one.
    """
    proposed = await _proposals(
        tmp_path,
        message("From: Alice <alice@example.com>", "Subject: skipped", f"Date: {DATE}", *headers),
    )

    assert proposed == (), case


# --- the closed subset: rejected from outside, and accepted on its boundaries -


@pytest.mark.parametrize(
    ("case", "value"),
    [
        # Five `datetime.fromisoformat` accepts, so a reader delegating acceptance
        # to it passes every unparseable case above and still admits what §5
        # excludes.
        ("a space separator", "2026-08-03 11:00:00Z"),
        ("a comma fractional separator", "2026-08-03T11:00:00,5Z"),
        ("an offset carrying seconds", "2026-08-03T11:00:00+00:00:30"),
        ("an omitted SS", "2026-08-03T11:00Z"),
        ("an offset without its colon", "2026-08-03T11:00:00+0000"),
        # Two a parser conforming to RFC 3339's grammar accepts while
        # `fromisoformat` rejects them — so the skip is owed on §5's terms rather
        # than as a side effect of the stdlib's narrowness.
        ("a lower-case t", "2026-08-03t11:00:00Z"),
        ("a lower-case z", "2026-08-03T11:00:00z"),
        ("a leap second", "2016-12-31T23:59:60Z"),
        # The excluded offset, which RFC 3339 §4.3 makes a determinate UTC instant:
        # it is excluded for *disagreement* rather than ambiguity, because
        # `fromisoformat` reads it as UTC while `parsedate_to_datetime` treats the
        # `-0000` form as carrying no usable zone at all.
        ("the excluded -00:00", "2026-08-03T11:00:00-00:00"),
        # Precision finer than a microsecond, which no `UtcInstant` holds exactly —
        # and is not rounded onto the subset.
        ("seven fractional digits", "2026-08-03T11:00:00.1234567Z"),
        # Values the pattern itself refuses, so the closure is not only about the
        # interesting literals.
        ("a trailing comment", f"{INSIDE_STAMP} (delivered)"),
        ("two timestamps", f"{INSIDE_STAMP} {INSIDE_STAMP}"),
        ("no offset at all", "2026-08-03T11:00:00"),
        ("an impossible hour", "2026-08-03T24:00:00Z"),
        ("an impossible date", "2026-02-30T11:00:00Z"),
    ],
)
async def test_a_value_outside_the_closed_subset_is_skipped(
    tmp_path: Path, case: str, value: str
) -> None:
    """§5's subset is the accept/reject boundary, not a parser's own.

    A value RFC 3339 admits but the subset does not is not an accepted value here
    "whether or not it is well-formed", and the reader **never normalises one onto
    the subset**: it does not roll a leap second to the following instant,
    case-fold a separator, or drop precision to make a value acceptable.
    """
    proposed = await _proposals(tmp_path, envelope(delivered_at=value))

    assert proposed == (), case


@pytest.mark.parametrize(
    ("case", "value", "rendered"),
    [
        ("second 59", "2026-08-03T10:59:59Z", "2026-08-03 10:59 (UTC)"),
        ("second 00", "2026-08-03T11:00:00Z", "2026-08-03 11:00 (UTC)"),
        ("one fractional digit", "2026-08-03T11:00:00.1Z", "2026-08-03 11:00 (UTC)"),
        ("six fractional digits", "2026-08-03T11:00:00.123456Z", "2026-08-03 11:00 (UTC)"),
        # The excluded `-00:00`'s mirror, which *is* admissible.
        ("a +00:00 offset", "2026-08-03T11:00:00+00:00", "2026-08-03 11:00 (UTC)"),
        # #1031: both boundary offsets above are UTC, so a reader whose subset
        # check reduced to `endswith("Z")` would pass every one of them. A nonzero
        # offset in each direction is an interior value of the subset and is what
        # closes that hole.
        ("a negative nonzero offset", "2026-08-03T07:30:00-03:00", "2026-08-03 10:30 (UTC)"),
        ("a positive nonzero offset", "2026-08-03T14:30:00+03:00", "2026-08-03 11:30 (UTC)"),
        ("the largest offset", "2026-08-04T10:30:00+23:59", "2026-08-03 10:31 (UTC)"),
    ],
)
async def test_a_value_on_the_subsets_own_boundaries_is_accepted(
    tmp_path: Path, case: str, value: str, rendered: str
) -> None:
    """The accepting direction, which every skip clause in this file is passed without.

    A reader that skips everything satisfies each rejection above, so the subset
    would be pinned only from outside and its inside would be a lane's guess. Each
    value here sits on one of the subset's own boundaries, and the rendered
    instant is asserted rather than the bare acceptance — because an offset that is
    *parsed* and then not *applied* accepts the value and dates the message wrongly
    (#1031).
    """
    proposed = await _proposals(tmp_path, envelope(subject="accepted", delivered_at=value))

    assert proposed == (
        f'Email from "Alice <alice@example.com>" with subject "accepted", delivered {rendered}.',
    ), case


async def test_surrounding_whitespace_is_not_part_of_the_value(tmp_path: Path) -> None:
    """A field body's surrounding whitespace is not content, and never was.

    Every parser strips the space after the colon already, so stripping the other
    end too is reading the field rather than widening the subset — and the
    alternative is skipping an honest fetcher's message over a trailing space. What
    is *inside* the value must still be a timestamp and nothing else, which the
    two-timestamps and trailing-comment cases above pin.
    """
    proposed = await _proposals(
        tmp_path, envelope(subject="padded", delivered_at=f"  {INSIDE_STAMP}  ")
    )

    assert len(proposed) == 1


# --- `Date` is required, singular, and never filled from anything else -------


@pytest.mark.parametrize(
    ("case", "headers"),
    [
        ("no Date at all", ()),
        ("two Dates", (f"Date: {DATE}", "Date: Mon, 03 Aug 2026 10:30:00 +0000")),
        # The two §5 offers to illustrate its predicate: both *parse* and then
        # resolve to nothing usable.
        ("an RFC 5322 -0000", ("Date: Mon, 03 Aug 2026 11:00:00 -0000",)),
        ("an absent zone", ("Date: Mon, 03 Aug 2026 11:00:00",)),
        # And the harder half, which does not parse at all — a lane handling only
        # the illustrations reaches either the fallback or an escaping parser
        # error, and the second breaches §5's rule that a skip raises nothing.
        ("a malformed Date", ("Date: yesterday afternoon",)),
        ("an impossible Date", ("Date: Mon, 32 Aug 2026 11:00:00 +0000",)),
        ("an empty Date", ("Date:",)),
    ],
)
async def test_a_date_that_resolves_to_no_instant_is_skipped(
    tmp_path: Path, case: str, headers: tuple[str, ...]
) -> None:
    """§5: the delivery instant is never substituted for a report time.

    This is the substitution a reader reaches for *precisely because* it has a
    usable instant in hand: the message carries a valid, in-window
    ``X-Assistant-Delivered-At``, so the only thing stopping it being proposed with
    that instant standing in as ``reported_at`` is the rule. ADR-0092 §3 permits no
    substitute for a report time the source did not make.
    """
    proposed = await _proposals(
        tmp_path,
        message(
            "From: Alice <alice@example.com>",
            "Subject: skipped",
            f"{DELIVERED_AT_HEADER}: {INSIDE_STAMP}",
            *headers,
        ),
    )

    assert proposed == (), case


async def test_a_date_the_reader_can_resolve_is_carried_as_reported_at(
    tmp_path: Path,
) -> None:
    """The accepting direction of the rule above, on a zone that is not UTC.

    ``reported_at`` is the sender's clock as an instant, so a ``Date`` carrying a
    real offset is converted rather than read as wall time — the same property
    #1031 raises for the delivery header, on the field beside it.
    """
    path = store(
        tmp_path,
        envelope(date="Mon, 03 Aug 2026 13:00:00 +0200", delivered_at=INSIDE),
    )

    reading = await reader(path).read()

    (proposal,) = reading.proposals
    attestation = proposal.proposed.provenance.attestation
    assert attestation is not None
    assert attestation.reported_at == datetime(2026, 8, 3, 11, 0, tzinfo=UTC)


# --- the sender and the subject are never on their own a reason to skip ------


@pytest.mark.parametrize(
    ("case", "headers", "rendered"),
    [
        ("no Subject", ("From: Alice <alice@example.com>",), 'from "Alice <alice@example.com>"'),
        (
            "two Subjects",
            ("From: Alice <alice@example.com>", "Subject: first", "Subject: second"),
            'from "Alice <alice@example.com>"',
        ),
        ("no From", ("Subject: still proposed",), 'from "an unnamed sender"'),
        (
            "two Froms",
            ("Subject: still proposed", "From: alice@example.com", "From: mallory@example.com"),
            'from "an unnamed sender"',
        ),
        ("neither", (), 'from "an unnamed sender"'),
    ],
)
async def test_an_absent_or_duplicated_text_field_proposes_with_it_empty(
    tmp_path: Path, case: str, headers: tuple[str, ...], rendered: str
) -> None:
    """§5's converse, so the skip rule is not quietly generalised to every field.

    Neither field carries an instant, neither is an identity (§4), and a message
    that legitimately carries no subject is ordinary mail rather than a fault. The
    **duplicate** is the case a lane breaches while passing the absent one, because
    ``email.message.Message``'s own mapping returns the *first* occurrence of a
    repeated header and says nothing — which is exactly the selection §5 forbids,
    reaching the opposite outcome from the duplicate ``Date`` above it.
    """
    proposed = await _proposals(
        tmp_path,
        message(f"Date: {DATE}", f"{DELIVERED_AT_HEADER}: {INSIDE_STAMP}", *headers),
    )

    assert len(proposed) == 1, case
    assert rendered in proposed[0], case
    if case.startswith("two Subjects"):
        assert "first" not in proposed[0], "no selection is made among the candidates"
        assert "second" not in proposed[0], "no selection is made among the candidates"
    if case.startswith("two Froms"):
        assert "alice@example.com" not in proposed[0]
        assert "mallory@example.com" not in proposed[0]


async def test_a_folded_subject_arrives_as_one_line(tmp_path: Path) -> None:
    """Unfolding removes the break and keeps the whitespace, which is RFC 5322's rule.

    A header value carrying a bare line break is a fetcher fault ADR-0140 §4 names,
    and one reaching a rendered belief would put a newline inside a quoted span —
    so the removal is a property worth asserting rather than an incidental effect
    of however the parser happened to return the value.
    """
    proposed = await _proposals(
        tmp_path,
        message(
            "From: Alice <alice@example.com>",
            "Subject: a subject that runs on",
            "  and is folded across two lines",
            f"Date: {DATE}",
            f"{DELIVERED_AT_HEADER}: {INSIDE_STAMP}",
        ),
    )

    assert proposed == (
        'Email from "Alice <alice@example.com>" with subject "a subject that runs on  '
        'and is folded across two lines", delivered 2026-08-03 11:00 (UTC).',
    )


async def test_a_header_carrying_undecodable_bytes_still_encodes(tmp_path: Path) -> None:
    """A value the store wrote as raw bytes must not become an unencodable ``str``.

    ``compat32`` returns an :class:`email.header.Header` rather than a ``str`` for
    a value it could not decode as ASCII, so a value's *type* here depends on the
    store's content — and a lane assuming ``str`` would carry an object into a
    proposal. Coercing through ``str`` also substitutes the replacement character
    for what could not be decoded, which is what keeps a lone surrogate out of a
    belief that has to survive UTF-8 encoding on its way to a store.
    """
    raw = message(
        "From: Alice <alice@example.com>",
        f"Date: {DATE}",
        f"{DELIVERED_AT_HEADER}: {INSIDE_STAMP}",
    ).replace(b"From: Alice", b"Subject: \xff\xfe caf\xc3\xa9\nFrom: Alice")

    proposed = await _proposals(tmp_path, raw)

    assert len(proposed) == 1
    proposed[0].encode()  # the assertion: it encodes at all


async def test_the_sender_is_carried_as_the_store_gives_it(tmp_path: Path) -> None:
    """§5: "the sender as the store gives it", which is not what a policy would give.

    ``email.policy.default`` *rewrites* what it parses — ``From: <<<<>>>>`` becomes
    ``<>``, and an unterminated quoted display name becomes its contents — so a
    reader built on it would put its own interpretation on a value whose whole
    standing is that the store said it. Nothing about the field is authenticated
    anyway (§4), so there is nothing a normalising pass could make more true.
    """
    proposed = await _proposals(
        tmp_path,
        envelope(sender="<<<<>>>>", subject="malformed sender", delivered_at=INSIDE),
    )

    assert proposed == (
        'Email from "<<<<>>>>" with subject "malformed sender", delivered 2026-08-03 11:00 (UTC).',
    )


async def test_no_recipient_or_threading_header_reaches_a_proposal(tmp_path: Path) -> None:
    """§5's deliberate omissions, asserted rather than left to the field set's shape.

    ``To:`` and ``Cc:`` multiply Tier-1 addresses by every recipient of every
    mailing list, and the useful question they would answer — *was this addressed
    to me* — needs the user's own addresses, which this reader does not have and
    must not guess. ``References`` is not carried because reconstructing a
    conversation from it is an inference, and ADR-0093 §2 rules that a reader
    infers nothing.
    """
    proposed = await _proposals(
        tmp_path,
        envelope(
            delivered_at=INSIDE,
            extra=(
                "To: bob@example.com, carol@example.com",
                "Cc: dave@example.com",
                "References: <thread-root@example.com>",
                "Received: from mx.example.com by hub.example.com; Mon, 3 Aug 2026 11:00:00 +0000",
            ),
        ),
    )

    assert len(proposed) == 1
    for absent in ("bob@", "carol@", "dave@", "thread-root", "mx.example.com"):
        assert absent not in proposed[0], absent
