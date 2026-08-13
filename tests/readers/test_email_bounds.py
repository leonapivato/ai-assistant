"""What the reader refuses, what it discards, and what it declines to declare.

Three ADR-0140 sections meet here because they are the same question asked three
ways — *what may leave this read*:

* **§5's body prohibition.** Reading a byte and interpreting it are two acts, and
  only the second is confined: acquisition and framing are unrestricted, because
  an in-band-delimited store cannot be traversed at all without scanning past
  bodies to reach the next delimiter. What is bounded is interpretation and
  materialisation.
* **§12's three caps**, each of which refuses rather than truncates, and one of
  which is about *ordering* rather than about a figure.
* **§7's refusals**, which are the two things this reader declines to say at all.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

import pytest
from mbox_fixtures import NOW, contents, delivered, envelope, facet_of, message, reader, store

from ai_assistant.core.errors import ReaderError
from ai_assistant.core.types import DataTier, MemorySource
from ai_assistant.readers import DELIVERED_AT_HEADER
from ai_assistant.readers import email as email_module
from ai_assistant.readers._source import SourceTooLargeError
from ai_assistant.readers.email import ContentBudgetExhaustedError, TooManyMessagesError

if TYPE_CHECKING:
    from pathlib import Path

INSIDE = NOW - timedelta(hours=1)

#: A string no proposal, facet or rendered value may contain. Distinctive so a
#: substring search over the whole reading is conclusive.
BODY_SENTINEL = "Halvorsen-oncology-referral-9f2c"


def _root(exc: BaseException) -> BaseException:
    """The deepest link of an exception's cause chain."""
    while exc.__cause__ is not None:
        exc = exc.__cause__
    return exc


# --- §5: the body is traversed and discarded --------------------------------


async def test_a_message_with_a_body_proposes_its_envelope_and_nothing_of_the_body(
    tmp_path: Path,
) -> None:
    """Both halves, because either alone is passed by a reader that is wrong.

    A test checking only the sentinel's absence is passed by a reader that drops
    the message **entirely** — so the envelope proposal and the facet count are
    asserted first, and only then is the whole reading searched for a byte of the
    body. The dump is searched rather than the content field, because §5's
    prohibition is over *any* value leaving the reader and a lane that put the
    body somewhere unexpected would satisfy a narrower check.
    """
    path = store(
        tmp_path,
        envelope(
            subject="a real subject",
            delivered_at=INSIDE,
            body=f"Dear Alice,\n\n{BODY_SENTINEL}\n\nRegards",
        ),
    )

    reading = await reader(path).read()

    assert contents(reading.proposals) == [
        'Email from "Alice <alice@example.com>" with subject "a real subject", '
        "delivered 2026-08-03 11:00 (UTC)."
    ]
    assert facet_of(reading).arrived_in_window == 1
    assert BODY_SENTINEL not in reading.model_dump_json()


async def test_a_body_that_looks_like_a_header_is_not_read_as_one(tmp_path: Path) -> None:
    """The header block ends at the first blank line, which is RFC 5322's boundary.

    A body carrying header-shaped lines is the shape that catches a reader
    handing the whole framed region to a parser: ``headersonly=True`` stops at the
    blank line for the *fields*, but a lane that sliced the region differently — or
    that let a continuation run on — would read the body's ``Subject:`` as the
    message's own.
    """
    path = store(
        tmp_path,
        envelope(
            subject="the real subject",
            delivered_at=INSIDE,
            body=f"Subject: {BODY_SENTINEL}\nDate: Mon, 03 Aug 2026 11:00:00 +0000",
        ),
    )

    reading = await reader(path).read()

    (proposal,) = reading.proposals
    assert "the real subject" in proposal.proposed.content
    assert BODY_SENTINEL not in reading.model_dump_json()


async def test_an_unescaped_separator_in_a_body_splits_the_message(tmp_path: Path) -> None:
    """ADR-0140 §4's splitting hazard, asserted as the **residual it is**.

    An mbox delimits messages with an in-band ``From `` line, and a writer that
    fails to escape a body line beginning ``From `` splits one message into two.
    That is a real property of the format and the ADR states it as bounded rather
    than closed, so it is pinned here rather than left to be discovered: the
    fragment is framed, and — because it carries no valid
    ``X-Assistant-Delivered-At`` — it is **skipped**, which is the careless case
    §5's skip rule catches.

    Two deployment requirements have to fail together to get further than this:
    the store must carry bodies at all, which §5's envelopes-only requirement
    removes, *and* the escaping must fail. What §4 bounds is the careful case, and
    it bounds it by making no field of any message an identity rather than by
    preventing the split.
    """
    path = store(
        tmp_path,
        envelope(
            subject="the real message",
            delivered_at=INSIDE,
            body=f"From: mallory@example.com\nSubject: {BODY_SENTINEL}",
        ),
    )
    # The body's own line, at the start of a line, is what the framing splits on.
    path.write_bytes(path.read_bytes().replace(b"From: mallory", b"From mallory"))

    reading = await reader(path).read()

    (proposal,) = reading.proposals
    assert "the real message" in proposal.proposed.content
    assert BODY_SENTINEL not in reading.model_dump_json()


# --- §12: one refusal test per cap ------------------------------------------


async def test_the_byte_cap_refuses_on_the_read_itself_and_before_any_parsing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0093 §7's ordering, which is why ``email_max_bytes`` must exist at all.

    A message cap can only be applied *after* parsing, so a cap on messages alone
    lets a 2 GiB store be fully parsed before anything refuses it — the bound
    applied one step too late to bound the work. The assertion is not merely that
    an over-cap store raises: the interpreter is replaced with one that fails the
    test if it is reached, so "before any parsing" is pinned rather than inferred
    from the exception's type.
    """

    def refuse(block: bytes) -> None:
        pytest.fail("the byte cap must refuse before any message is interpreted")

    monkeypatch.setattr(email_module, "_interpret", refuse)
    path = store(tmp_path, *[envelope(delivered_at=INSIDE) for _ in range(20)])

    with pytest.raises(ReaderError) as raised:
        await reader(path, max_bytes=64).read()

    assert isinstance(_root(raised.value), SourceTooLargeError)


async def test_the_content_budget_refuses_before_the_over_budget_proposal_is_built(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``email_max_content_bytes`` bounds the **output**, which none of the others do.

    A reader that never charges the accumulator, or that charges it *after*
    materialising, passes every other test in this suite — so the rendering is
    counted rather than the exception alone: the first message is rendered and the
    second is refused before it is, which is what "checked before each proposal is
    materialised" means.

    A folded ``Subject`` is the shape §12 names, because it is how a single
    envelope inside every other cap reaches an unbounded size.
    """
    rendered: list[str] = []
    real = email_module._render

    def counted(envelope_: object) -> str:
        result = real(envelope_)  # type: ignore[arg-type]
        rendered.append(result)
        return result

    monkeypatch.setattr(email_module, "_render", counted)
    folded = ["Subject: a subject", *[f"  folded continuation line {n}" for n in range(200)]]
    path = store(
        tmp_path,
        envelope(subject="small", delivered_at=INSIDE),
        message(
            "From: Alice <alice@example.com>",
            *folded,
            "Date: Mon, 03 Aug 2026 11:00:00 +0000",
            f"{DELIVERED_AT_HEADER}: {delivered(INSIDE)}",
        ),
    )

    with pytest.raises(ReaderError) as raised:
        await reader(path, max_content_bytes=1024).read()

    assert isinstance(_root(raised.value), ContentBudgetExhaustedError)
    assert len(rendered) == 1, "the over-budget proposal was materialised before it was refused"


async def test_the_message_cap_is_applied_at_the_framing(tmp_path: Path) -> None:
    """§12's ordering, and the one property every other test here passes while breached.

    A store of ``email_max_messages + 1`` framed messages **none** of which carries
    a valid ``X-Assistant-Delivered-At`` must **refuse** rather than return a
    successful empty reading. An implementation that skips invalid messages first
    and counts what survives satisfies every other case in this suite and still
    turns a busted cap into a quiet week — which is exactly what ADR-0093 §5's
    refuse-don't-truncate rule exists to prevent, and the ordering ADR-0117 §5
    records the calendar taking.
    """
    unstamped = message("From: Alice <alice@example.com>", "Subject: nothing usable here")
    path = store(tmp_path, *[unstamped for _ in range(4)])

    with pytest.raises(ReaderError) as raised:
        await reader(path, max_messages=3).read()

    assert isinstance(_root(raised.value), TooManyMessagesError)


async def test_the_message_cap_admits_exactly_its_own_figure(tmp_path: Path) -> None:
    """The accepting direction, so the cap is not satisfied by refusing everything.

    Counted at the framing means counted *before* the window is applied too, so a
    store at exactly the cap whose messages are mostly out of window is a
    successful reading rather than a refusal.
    """
    path = store(
        tmp_path,
        envelope(delivered_at=INSIDE),
        envelope(delivered_at=NOW - timedelta(days=30)),
        envelope(delivered_at=NOW - timedelta(days=60)),
    )

    reading = await reader(path, max_messages=3).read()

    assert len(reading.proposals) == 1


# --- §7: what this reader declines to declare, and §5's tier ----------------


async def test_the_reading_declares_no_coverage_and_no_extent(tmp_path: Path) -> None:
    """ADR-0140 §7, over a reading that accounted for every message it held.

    **Not a consequence of something having gone wrong.** ``CalendarReader``
    withholds its coverage when a read skipped an entry, so a test over a reading
    with skips would prove nothing about this clause — this store is entirely
    interpretable, entirely in window, and the reading still declares neither.

    Coverage is what a read *exhausted*, and this read exhausts a file rather than
    a world; and the demotion a coverage would buy is not wanted, because the
    fetcher's retention guarantees every message eventually leaves the store, so
    ADR-0110 §3's conditions would be met for every belief one retention period
    after it was proposed. No belief this reader proposes is absence-demotable, and
    the extent is declined on ADR-0117 §6's precedent: a message's position in the
    source's world is an instant, and a zero-width extent would be contained by
    every coverage.
    """
    path = store(tmp_path, envelope(delivered_at=INSIDE), envelope(delivered_at=INSIDE))

    reading = await reader(path).read()

    assert len(reading.proposals) == 2
    assert reading.coverage is None
    assert reading.as_of is None
    for proposal in reading.proposals:
        attestation = proposal.proposed.provenance.attestation
        assert attestation is not None
        assert attestation.extent is None


async def test_every_proposal_states_its_tier_rather_than_defaulting_to_it(
    tmp_path: Path,
) -> None:
    """ADR-0093 §4's ``sensitivity``, and ADR-0140 §5's reason for the value.

    ``PERSONAL`` is uniform here *because* the store holds envelopes: a mailbox's
    bodies hold everything from a newsletter to a password-reset link, Tier 0 by
    ADR-0004's own classification, and no per-message classifier could tell them
    apart. The value cannot be asserted to have been *chosen* rather than
    defaulted — no check can — so what is pinned is the value and the band it
    travels in.
    """
    path = store(tmp_path, envelope(delivered_at=INSIDE))

    reading = await reader(path).read()

    (proposal,) = reading.proposals
    assert proposal.sensitivity is DataTier.PERSONAL
    assert proposal.proposed.provenance.source is MemorySource.EXTERNAL
    assert proposal.rationale.strip()
