"""ADR-0140 §3's window: which messages a read proposes from, and how far back.

Four properties, and every one of them is a place where a reader can be plausibly
wrong and pass everything else: the window's two edges, the arithmetic that
computes the lower one, and the fact that membership is decided on the **delivery
instant** rather than on the ``Date`` sitting beside it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from mbox_fixtures import NOW, contents, envelope, facet_of, frozen, message, reader, store

from ai_assistant.readers._occurrences import UTC_MIN

if TYPE_CHECKING:
    from pathlib import Path

#: The fixtures' reader looks two hours back from :data:`NOW`, so the window is
#: ``[10:00, 12:00)`` and every edge below is an instant a reader of the test can
#: see without arithmetic.
LOWER_EDGE = NOW - timedelta(hours=2)


async def test_the_windows_edges_are_asserted_rather_than_implied(tmp_path: Path) -> None:
    """ADR-0140 §3's window is closed at the bottom and open at the top.

    **The lower edge is the direction that matters**, and it is why the ADR states
    the membership rule once rather than leaving it to a lane: a reader admitting
    only ``lower < delivered_at`` loses the edge message **permanently** rather
    than late, because by the next run the window has moved past it and §3 leaves
    no cursor to notice. The upper edge is exclusive for §7b's reason unchanged —
    ``read_at`` is the instant the bytes were acquired, and a message delivered
    *at* it is not yet inside the interval the read describes.

    ``arrived_in_window`` is asserted beside the proposals, because a reader can
    decide membership correctly and count it wrongly; and ``covers_from`` is
    asserted equal to the lower edge itself, because a count of zero means nothing
    to a consumer who does not know the interval it counted over.
    """
    path = store(
        tmp_path,
        envelope(subject="exactly at the lower edge", delivered_at=LOWER_EDGE),
        envelope(
            subject="a second before the lower edge", delivered_at=LOWER_EDGE - timedelta(seconds=1)
        ),
        envelope(subject="exactly at read_at", delivered_at=NOW),
        envelope(subject="a second before read_at", delivered_at=NOW - timedelta(seconds=1)),
    )

    reading = await reader(path).read()

    assert contents(reading.proposals) == [
        'Email from "Alice <alice@example.com>" with subject "exactly at the lower edge", '
        "delivered 2026-08-03 10:00 (UTC).",
        'Email from "Alice <alice@example.com>" with subject "a second before read_at", '
        "delivered 2026-08-03 11:59 (UTC).",
    ]
    assert facet_of(reading).arrived_in_window == 2
    assert facet_of(reading).covers_from == LOWER_EDGE


async def test_an_empty_window_still_states_the_interval_it_counted_over(
    tmp_path: Path,
) -> None:
    """The zero case, which is the one ``covers_from`` exists for (ADR-0140 §6).

    A count of zero is uninterpretable on its own — and a consumer of
    ``CurrentContext`` does not read ``Settings``, so the horizon has to travel
    with the value or not exist at all. This is ``covers_until``'s mirror and the
    symmetry ADR-0117 §8 anticipated from the other side.
    """
    path = store(tmp_path, envelope(delivered_at=NOW - timedelta(days=30)))

    reading = await reader(path).read()

    assert reading.proposals == ()
    assert facet_of(reading).arrived_in_window == 0
    assert facet_of(reading).covers_from == LOWER_EDGE


async def test_the_window_arithmetic_saturates_rather_than_raising(tmp_path: Path) -> None:
    """ADR-0140 §3's saturation clause, on the only case that can reach it.

    §12's ten-year ceiling makes the overflow unreachable **from configuration
    alone**, so it is reachable only from configuration *and* a clock — the case a
    lane that builds the window as a bare subtraction never runs and never sees.
    Its failure would be an ``OverflowError`` escaping ADR-0093 §8's two outcomes
    entirely rather than arriving as a ``ReaderError``, on a store that parsed
    perfectly.

    Saturation is chosen rather than a refusal for §7b's reason: it loses nothing,
    because there is no instant before the minimum for a message to have been
    delivered at, so the clamped window and the ideal one select the same
    messages. There is no upward direction to test — email has the one edge, and
    ``read_at`` is representable by construction.
    """
    # Two days clear of `datetime.min`, which is what `checked_clock` will accept:
    # it keeps a one-day margin so a reading survives being localized to any zone.
    near_the_bottom = datetime.min.replace(tzinfo=UTC) + timedelta(days=2)
    path = store(tmp_path, envelope(delivered_at=near_the_bottom - timedelta(hours=1)))

    reading = await reader(
        path, now=frozen(near_the_bottom), window_past=timedelta(days=3650)
    ).read()

    assert reading.read_at == near_the_bottom
    assert facet_of(reading).covers_from == UTC_MIN
    assert facet_of(reading).arrived_in_window == 1, "the clamped window still selects the message"


# --- the two clocks are two facts, and only one decides membership -----------


async def test_a_store_carrying_only_a_date_proposes_nothing(tmp_path: Path) -> None:
    """ADR-0140 §5: ``Date`` is never a delivery instant.

    The reader decides membership on ``X-Assistant-Delivered-At`` and on nothing
    else — never on the mbox ``From `` line, a ``Received`` header, ``Date``, or
    the file's modification time. A store whose messages are perfectly ordinary
    mail delivered inside the window, and which the fetcher never stamped, is
    therefore a store this reader proposes nothing from.
    """
    inside = NOW - timedelta(hours=1)
    path = store(
        tmp_path,
        message(
            "From: Alice <alice@example.com>",
            "Subject: ordinary mail nobody stamped",
            f"Date: {inside:%a, %d %b %Y %H:%M:%S} +0000",
        ),
    )

    reading = await reader(path).read()

    assert reading.proposals == ()
    assert facet_of(reading).arrived_in_window == 0


async def test_membership_is_the_delivery_instant_while_reported_at_is_the_date(
    tmp_path: Path,
) -> None:
    """Both present and disagreeing, in both directions (ADR-0140 §5).

    §5 separates the two clocks as a **security** property before a modelling one:
    ``Date`` is the one clock in the message the *sender* controls, so a sender who
    can move the window by writing a future date holds a message in every window
    there will ever be, and one who writes a past date drops out of all of them.

    Every other test in this file is passed by a reader that reads both fields
    into one variable, because on honest mail they agree. This is the case that is
    not: one message is dated a year away and delivered inside the window, the
    other dated inside the window and delivered a year ago, and only the first is
    proposed — with ``reported_at`` carrying the ``Date`` it was dated with rather
    than the delivery instant it was selected by.
    """
    path = store(
        tmp_path,
        envelope(
            subject="dated far away, delivered inside",
            date="Tue, 03 Aug 2027 09:00:00 +0000",
            delivered_at=NOW - timedelta(hours=1),
        ),
        envelope(
            subject="dated inside, delivered long ago",
            date="Mon, 03 Aug 2026 11:00:00 +0000",
            delivered_at=NOW - timedelta(days=365),
        ),
    )

    reading = await reader(path).read()

    (proposal,) = reading.proposals
    assert "dated far away, delivered inside" in proposal.proposed.content
    attestation = proposal.proposed.provenance.attestation
    assert attestation is not None
    assert attestation.reported_at == datetime(2027, 8, 3, 9, 0, tzinfo=UTC)
    assert proposal.proposed.provenance.last_confirmed_at == attestation.reported_at


async def test_a_nonzero_offset_is_converted_before_membership_is_decided(
    tmp_path: Path,
) -> None:
    """The delivery instant is an instant, not a wall clock (#1031).

    ADR-0140 §5 admits any determinate numeric offset, so a reader that treated the
    written digits as UTC would put a message in the wrong window rather than
    merely rejecting a value — which is the direction that matters, because it
    lands on §3's arrival window rather than on the grammar. Both messages here
    carry local times that are **outside** the window as written and inside it once
    their offsets are applied, one from each side of UTC; and the third is the
    converse, written as a time that looks inside the window and is an hour past
    ``read_at`` once converted.
    """
    path = store(
        tmp_path,
        # 07:30-03:00 is 10:30Z — inside [10:00, 12:00), while "07:30" is not.
        envelope(subject="west of utc", delivered_at="2026-08-03T07:30:00-03:00"),
        # 14:30+03:00 is 11:30Z — inside, while "14:30" is past read_at.
        envelope(subject="east of utc", delivered_at="2026-08-03T14:30:00+03:00"),
        # 11:30-01:30 is 13:00Z — an hour past read_at, while "11:30" looks inside.
        envelope(subject="looks inside and is not", delivered_at="2026-08-03T11:30:00-01:30"),
    )

    reading = await reader(path).read()

    assert contents(reading.proposals) == [
        'Email from "Alice <alice@example.com>" with subject "west of utc", '
        "delivered 2026-08-03 10:30 (UTC).",
        'Email from "Alice <alice@example.com>" with subject "east of utc", '
        "delivered 2026-08-03 11:30 (UTC).",
    ]
    assert facet_of(reading).arrived_in_window == 2


async def test_the_delivery_instant_is_never_taken_from_the_mbox_from_line(
    tmp_path: Path,
) -> None:
    """§5's exclusion, on the field a lane most plausibly reaches for.

    Every fixture in this suite writes a ``From `` line dated 1970 precisely so
    that a reader taking its timestamp proposes nothing — and this case makes that
    load-bearing rather than incidental by dating the separator line *inside* the
    window while the delivery header sits outside it. The separator is also the
    line §4's splitting hazard lets an attacker write, which is one of the three
    reasons §5 excluded it.
    """
    separator = f"From alice@example.com {NOW - timedelta(hours=1):%a %b %d %H:%M:%S %Y}".encode()
    raw = envelope(delivered_at=NOW - timedelta(days=30)).split(b"\n", 1)[1]

    reading = await reader(store(tmp_path, separator + b"\n" + raw)).read()

    assert reading.proposals == ()


async def test_two_reads_of_one_store_at_two_clocks_move_the_window(
    tmp_path: Path,
) -> None:
    """No cursor, and the window moving with the clock is what replaces one.

    ADR-0140 §3 removes the cursor by showing that ADR-0093 §5's argument transfers:
    "the window *moves with the clock*, so every run's window is recomputed from
    scratch and an entry inside it is read whether or not any previous run read
    it. There is no accumulating backlog for a cursor to track." Asserted over one
    unchanged store read twice — the same message is proposed both times while it
    is in the window, and is gone from the second reading once the window has moved
    past it, with no durable state anywhere deciding either outcome.
    """
    delivery = NOW - timedelta(hours=1)
    path = store(tmp_path, envelope(delivered_at=delivery))

    first = await reader(path).read()
    second = await reader(path, now=frozen(NOW + timedelta(hours=2))).read()

    assert len(first.proposals) == 1, "read once, in window"
    assert second.proposals == (), "read again after the window moved past it"
    assert facet_of(second).covers_from == NOW


async def test_a_re_read_mints_a_fresh_id_rather_than_addressing_the_message(
    tmp_path: Path,
) -> None:
    """ADR-0140 §4's fourth clause: a ``Message-ID`` is not, and does not become, an id.

    A derived id is an **address**, aimed at the same record on every re-read —
    and ADR-0092 §6 refuses one because of what that address does on a re-sync
    (ADR-0038 §2a's resurrection). Idempotency does not vanish, it moves: the
    unchanged re-read proposes the same *content*, and the gate folds it by
    similarity at the target's id.
    """
    path = store(
        tmp_path,
        envelope(delivered_at=NOW - timedelta(hours=1), extra=("Message-ID: <abc@example.com>",)),
    )

    first = await reader(path).read()
    second = await reader(path).read()

    (one,) = first.proposals
    (two,) = second.proposals
    assert one.proposed.id != two.proposed.id
    assert "abc@example.com" not in one.proposed.id
    assert one.proposed.content == two.proposed.content
    assert "abc@example.com" not in one.proposed.content
