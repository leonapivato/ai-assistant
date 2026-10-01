"""The three transcript models, and the refusals they carry (ADR-0225 §1, §7, §10).

What is contract here is the **shape as this ADR ships it**: §10 fixes the fields
each model carries and no other, and a later ADR may widen any of them by an
additive, defaulted field — so what these cases pin is the frozen-ness, the
required-ness, the domains an implementation could otherwise let a forged value
past, and the ordinal ADR-0283 §9 removed.

The reads, the ordering, the predicate and the excerpt bound are the *archive's*
obligations and live in ``tests/archive/transcript_archive_contracts.py``, where
they run against every conforming implementation. What is here is what a model can
be asked on its own.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from ai_assistant.core.types import (
    TRANSCRIPT_EXCERPT_BYTES,
    ExchangeDisposition,
    TranscriptArchiveSize,
    TranscriptEntry,
    TranscriptHit,
)

AT = datetime(2026, 9, 2, 12, 0, tzinfo=UTC)


def _entry(**overrides: object) -> TranscriptEntry:
    fields: dict[str, object] = {
        "address": "c1:1",
        "conversation_id": "c1",
        "occurred_at": AT,
        "asked": "where did I say that",
        "replied": "on Tuesday",
        "disposition": ExchangeDisposition.NO_ACTION_NEEDED,
    }
    return TranscriptEntry.model_validate(fields | overrides)


def _hit(**overrides: object) -> TranscriptHit:
    fields: dict[str, object] = {
        "address": "c1:1",
        "conversation_id": "c1",
        "occurred_at": AT,
        "excerpt": "on Tuesday",
        "elided": False,
    }
    return TranscriptHit.model_validate(fields | overrides)


# --- frozen, all three (§13 item 10) ----------------------------------------


def test_a_transcript_entry_refuses_mutation() -> None:
    """ADR-0225 §10 freezes it, and a transcript is the record of what was said.

    A store that handed out a mutable entry would let a reader rewrite an exchange
    that already happened — in the one store whose whole purpose is to still hold it
    later.
    """
    entry = _entry()

    with pytest.raises(ValidationError):
        entry.asked = "rewritten"


def test_a_transcript_hit_refuses_mutation() -> None:
    """The same, over the value a search hands back."""
    hit = _hit()

    with pytest.raises(ValidationError):
        hit.excerpt = "rewritten"


def test_a_size_report_refuses_mutation() -> None:
    """And over the figure that would fire ADR-0225 §6's deferred cap."""
    size = TranscriptArchiveSize(entries=1, stored_bytes=2)

    with pytest.raises(ValidationError):
        size.entries = 99


# --- an entry carries no ordinal (ADR-0283 §9) -----------------------------


@pytest.mark.parametrize("ordinal", [1, None])
def test_an_entry_carrying_an_ordinal_is_refused(ordinal: object) -> None:
    """ADR-0283 §9: "``TranscriptEntry`` carries no ordinal."

    The field is gone rather than defaulted, so a value naming one — an integer, or
    the ``null`` a peer at an earlier protocol version sent — is an extra field the
    model forbids, not one it quietly drops.
    """
    with pytest.raises(ValidationError):
        _entry(ordinal=ordinal)


# --- the disposition is required (§10, §13 item 15) -------------------------


@pytest.mark.parametrize("supplied", [None, "omitted"])
def test_an_entry_with_no_disposition_is_refused(supplied: object) -> None:
    """ADR-0225 §10: required, and carrying no ``None``.

    An optional field here would be a ``None``-only slot with no producer — which
    ADR-0073 §4's standing test refuses — and it would recreate for a parked turn
    exactly the ambiguity the field is carried to prevent: without it a turn that
    parked reads in the transcript as a question nobody answered.

    Both spellings of "no disposition" are refused, because a model that accepted the
    omission while refusing the explicit ``None`` would let the one caller ADR-0225
    §10 is about — the one recording an exchange this system did not drive — through.
    """
    fields: dict[str, object] = {
        "address": "c1:1",
        "conversation_id": "c1",
        "occurred_at": AT,
        "asked": None,
        "replied": None,
    }
    if supplied is None:
        fields["disposition"] = None

    with pytest.raises(ValidationError):
        TranscriptEntry.model_validate(fields)


# --- both halves may be absent, and neither may be blank-by-default ---------


def test_both_halves_may_be_absent_and_are_stated_rather_than_defaulted() -> None:
    """§1's three capture cases put ``None`` on ``asked``, and five paths on ``replied``.

    Required *keywords* carrying ``None``, not defaulted ones: the value is handed to
    capture per call site rather than falling back, so a site that has not thought
    about it fails to construct rather than silently recording that the user said
    nothing.
    """
    entry = _entry(asked=None, replied=None)
    assert entry.asked is None
    assert entry.replied is None

    with pytest.raises(ValidationError):
        TranscriptEntry.model_validate(
            {
                "address": "c1:1",
                "conversation_id": "c1",
                "occurred_at": AT,
                "disposition": ExchangeDisposition.NO_ACTION_NEEDED,
            }
        )


# --- the size report's bounds (§10, §13 item 17) ----------------------------


@pytest.mark.parametrize(("entries", "stored_bytes"), [(-1, 0), (0, -1)])
def test_a_negative_figure_is_refused_at_validation(entries: int, stored_bytes: int) -> None:
    """ADR-0225 §10: neither is a quantity any implementation can be in a state to report.

    A store holds no negative number of entries and occupies no negative number of
    bytes, and an impossible figure crossing the local API to a surface that renders
    it is worse than an error.
    """
    with pytest.raises(ValidationError):
        TranscriptArchiveSize(entries=entries, stored_bytes=stored_bytes)


def test_neither_figure_carries_an_upper_bound() -> None:
    """Decided rather than overlooked (§10).

    There is no store-side refusal to anchor a ceiling on a count or a byte total,
    and inventing a number would be exactly what §6 declines to do for the cap
    itself.
    """
    huge = TranscriptArchiveSize(entries=2**70, stored_bytes=2**70)

    assert huge.entries == 2**70


# --- the fields are exactly the ratified set (§10) --------------------------


def test_each_model_carries_exactly_the_ratified_fields() -> None:
    """ADR-0225 §10: "carrying exactly the fields ratified below and no other".

    A roster rather than a spot check, so a field added without an ADR fails here
    rather than reaching a store nothing but the user reads. Widening is additive and
    defaulted when an ADR decides it, and this is the line that makes the decision
    visible.
    """
    assert set(TranscriptEntry.model_fields) == {
        "address",
        "conversation_id",
        "occurred_at",
        "asked",
        "replied",
        "disposition",
    }
    assert set(TranscriptHit.model_fields) == {
        "address",
        "conversation_id",
        "occurred_at",
        "excerpt",
        "elided",
    }
    assert set(TranscriptArchiveSize.model_fields) == {"entries", "stored_bytes"}


def test_no_transcript_model_carries_a_modality_a_capture_or_a_provenance() -> None:
    """§1's never-list, at the level of the type rather than of an implementation.

    An entry carries "no embedding, no score, no band, no confidence, no provenance
    and no belief", and modality is deliberately absent with §15 deferring it — so a
    lane that wanted one would have to add a field here, which is the moment the ADR
    is owed. Pinned because a `Capture` on this model would also make the archive a
    carrier for the two fields ADR-0221 §5 reserves.
    """
    forbidden = {"modality", "capture", "provenance", "confidence", "band", "score", "embedding"}

    assert forbidden.isdisjoint(TranscriptEntry.model_fields)
    assert forbidden.isdisjoint(TranscriptHit.model_fields)


# --- the excerpt bound is a shared figure (§7) ------------------------------


def test_the_excerpt_bound_is_named_and_is_in_bytes() -> None:
    """ADR-0094 §8: a bound with no figure is two conforming implementations diverging.

    Public because every implementation and the shared conformance suite need the
    same one, and in *bytes* because what it bounds is a response that crosses the
    local API.
    """
    assert TRANSCRIPT_EXCERPT_BYTES == 512
