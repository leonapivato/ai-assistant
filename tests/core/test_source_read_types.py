"""``ReadOutcome`` and ``SourceReadRecord``: the two types ADR-0185 §2 decides.

The store's conformance suites exercise these through a subject; this module is
about the *type*, which is where ADR-0185 §2's two construction invariants live —
"checked at construction for :class:`SourceGrant`'s reason: a record corrupted past
its own model would be stored and then make every later read of the trail
incoherent".

Nothing here opens a store. What it pins is that a record which does not say what
happened cannot be built at all, so no implementation has to defend against one.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from ai_assistant.core.types import GrantScope, ReadOutcome, RiskLevel, SourceReadRecord

_CHECKED_AT = datetime(2026, 8, 1, 9, 0, tzinfo=UTC)

#: The two outcomes decided at the first grant check, before anything was opened.
_UNGRANTED = (ReadOutcome.REFUSED, ReadOutcome.UNANSWERED)

#: The three on which no reading exists, so nothing could have been produced.
_READINGLESS = (*_UNGRANTED, ReadOutcome.FAILED)


def _record(**overrides: object) -> SourceReadRecord:
    """One coherent record, with ``overrides`` applied."""
    fields: dict[str, object] = {
        "id": "r-1",
        "source": "calendar",
        "use": GrantScope.INGEST,
        "checked_at": _CHECKED_AT,
        "outcome": ReadOutcome.COMPLETED,
        "grant": "g-1",
        "produced": 0,
    }
    fields.update(overrides)
    return SourceReadRecord(**fields)  # type: ignore[arg-type]  # a heterogeneous field map


# --- the outcome vocabulary --------------------------------------------------


def test_the_outcomes_are_the_six_the_adr_names() -> None:
    """ADR-0185 §1: "exactly one of ``ReadOutcome``'s six members".

    Pinned as a set rather than left to a walk of the enum, because the *number* is
    a ratified figure: §1 rules the six "mutually exclusive and total over the
    outcomes ADR-0097 §5 and ADR-0093 §8 already rule for a gated read; no
    implementation invents a seventh". A seventh member added without its ADR fails
    here rather than in review, and so does a member quietly removed.
    """
    assert {member.value for member in ReadOutcome} == {
        "completed",
        "refused",
        "unanswered",
        "failed",
        "discarded",
        "unconfirmed",
    }


def test_the_outcomes_are_not_ordered() -> None:
    """ADR-0185 §2, on ``GrantScope``'s reason (ADR-0097 §10).

    "Six outcomes of a read are not ranked, and an order would invite a comparison
    that means nothing." ``PermissionOutcome`` is a severity scale because outcomes
    of a permission decision genuinely combine by maximum; nothing about
    ``DISCARDED`` is *more* than ``REFUSED``, so a ``max()`` over these would return
    an answer no clause could act on.

    What is asserted is the **absence of the scale**, not the absence of ``str``'s
    own comparisons: ``StrEnum`` members are strings and always compare, which is why
    ``test_grant_types`` pins ``GrantScope``'s the same way. ``RiskLevel`` is the
    control, so this is a statement about a difference rather than about a class in
    isolation.
    """
    assert isinstance(ReadOutcome.COMPLETED, str)
    assert ReadOutcome.__lt__ is str.__lt__
    assert RiskLevel.__lt__ is not str.__lt__


def test_an_outcome_serialises_as_its_value() -> None:
    """A ``StrEnum`` for ``GrantScope``'s reason: a stable, serialisable vocabulary."""
    assert _record().model_dump(mode="json")["outcome"] == "completed"


# --- §2's first invariant: the grant pointer ---------------------------------


@pytest.mark.parametrize("outcome", _UNGRANTED, ids=lambda member: member.value)
def test_an_attempt_that_found_no_grant_may_not_cite_one(outcome: ReadOutcome) -> None:
    """ADR-0185 §2: ``grant`` is ``None`` "exactly on ``REFUSED`` and ``UNANSWERED``".

    A ``REFUSED`` row citing a grant claims an authorisation the driver never had,
    in the store whose premise is that its records are not fabricated.
    """
    with pytest.raises(ValidationError, match="found no live grant"):
        _record(outcome=outcome, grant="g-1")


@pytest.mark.parametrize(
    "outcome",
    [
        ReadOutcome.COMPLETED,
        ReadOutcome.FAILED,
        ReadOutcome.DISCARDED,
        ReadOutcome.UNCONFIRMED,
    ],
    ids=lambda member: member.value,
)
def test_an_attempt_that_ran_under_a_grant_must_name_it(outcome: ReadOutcome) -> None:
    """The other direction, which is what makes the correspondence a partition.

    Without it, ``grant is None`` would no longer separate the two outcomes that
    opened nothing from the four that ran under an authorisation, and a reader of
    the trail would have to trust the writer's discipline to place a row —
    which is the thing ADR-0185 §2 says the invariants exist to remove.
    """
    with pytest.raises(ValidationError, match="must name it"):
        _record(outcome=outcome, grant=None, produced=0)


@pytest.mark.parametrize("outcome", list(ReadOutcome), ids=lambda member: member.value)
def test_the_coherent_pairing_is_admitted(outcome: ReadOutcome) -> None:
    """Every outcome has a record that can be built, so no refusal is vacuous."""
    ungranted = outcome in _UNGRANTED
    record = _record(outcome=outcome, grant=None if ungranted else "g-1")

    assert record.outcome is outcome
    assert (record.grant is None) is ungranted


# --- §2's second invariant: the count ----------------------------------------


@pytest.mark.parametrize("outcome", _READINGLESS, ids=lambda member: member.value)
def test_an_attempt_with_no_reading_produced_nothing(outcome: ReadOutcome) -> None:
    """ADR-0185 §2: ``produced`` is zero on ``REFUSED``, ``UNANSWERED`` and ``FAILED``.

    "no reading exists in any of the three" — the first two never called ``read()``,
    and ADR-0093 §8 forbids a failed read returning "what it managed to gather".
    """
    with pytest.raises(ValidationError, match="carries no reading"):
        _record(outcome=outcome, grant=None if outcome in _UNGRANTED else "g-1", produced=1)


@pytest.mark.parametrize(
    "outcome",
    [ReadOutcome.COMPLETED, ReadOutcome.DISCARDED, ReadOutcome.UNCONFIRMED],
    ids=lambda member: member.value,
)
def test_an_attempt_carrying_a_reading_may_state_any_count(outcome: ReadOutcome) -> None:
    """Zero up, on all three — and the non-zero cases are the point.

    ADR-0185 §2: "A non-zero ``produced`` on a ``DISCARDED`` or ``UNCONFIRMED`` row
    is the point, not an oversight. 'This read across your revocation carried
    fourteen proposals that were dropped' is a materially different audit fact from
    'it carried none'." And a ``COMPLETED`` zero is ADR-0093 §8's rule that an empty
    reading "is a **successful** reading", carried onto the record.
    """
    assert _record(outcome=outcome, produced=0).produced == 0
    assert _record(outcome=outcome, produced=14).produced == 14


def test_a_negative_count_is_refused() -> None:
    """``ge=0``: a count is a cardinal quantity and the floor is on the field."""
    with pytest.raises(ValidationError):
        _record(produced=-1)


# --- the fields that carry no default ----------------------------------------


@pytest.mark.parametrize("omitted", ["grant", "produced"])
def test_the_two_stated_fields_have_no_default(omitted: str) -> None:
    """ADR-0185 §12: ``grant`` and ``produced`` are required with no default.

    "so a caller states both rather than inheriting a value it did not mean". A
    defaulted ``grant`` would let a driver record ``None`` on a ``COMPLETED`` row by
    forgetting rather than by deciding, and a defaulted ``produced`` would report a
    read that carried fourteen proposals as one that carried none.
    """
    fields = {
        "id": "r-1",
        "source": "calendar",
        "use": GrantScope.INGEST,
        "checked_at": _CHECKED_AT,
        "outcome": ReadOutcome.COMPLETED,
        "grant": "g-1",
        "produced": 0,
    }
    del fields[omitted]

    with pytest.raises(ValidationError, match=r"[Ff]ield required"):
        SourceReadRecord(**fields)  # type: ignore[arg-type]  # deliberately incomplete


# --- the source: a faithful copy ---------------------------------------------


@pytest.mark.parametrize(
    "declared",
    ["  calendar  ", "CALENDAR", "calendar-work"],
    ids=["surrounding whitespace", "another case", "another source"],
)
def test_the_source_is_kept_byte_for_byte(declared: str) -> None:
    """ADR-0185 §2, and ADR-0096 §2's rule that a faithful copy may only reject.

    ``Reader.name`` returns a bare ``str`` and ``SourceReading.source`` is
    ``EncodableText``, neither of which strips — so ``Identifier`` here would make a
    conforming reader named ``"  calendar  "`` produce a record naming
    ``"calendar"``: a record that does not say what happened, in the store whose
    premise is that its records are not fabricated, and one that could collide with
    a genuinely distinct reader.
    """
    assert _record(source=declared).source == declared


@pytest.mark.parametrize("blank", ["", "   ", "\t\n"])
def test_a_blank_source_is_refused(blank: str) -> None:
    """``NonBlankEncodableText`` refuses a blank identity while normalising nothing."""
    with pytest.raises(ValidationError):
        _record(source=blank)


# --- the record's shape ------------------------------------------------------


def test_the_record_is_frozen_and_forbids_extra_fields() -> None:
    """ADR-0068's posture, and ``extra="forbid"`` so a stored row equals what reloads."""
    record = _record()

    with pytest.raises(ValidationError):
        record.produced = 3
    with pytest.raises(ValidationError):
        _record(opened=True)


def test_the_record_carries_exactly_the_seven_fields_the_adr_enumerates() -> None:
    """ADR-0185 §12 names seven, and the count is a ratified figure.

    An eighth field arriving without its own ADR fails here — and §12 requires any
    later addition to be "optional with a default, on ADR-0008 §1's additive
    pattern", because "a required addition would make every stored row fail
    validation, which is the failure ADR-0184 records and repairs".
    """
    assert set(SourceReadRecord.model_fields) == {
        "id",
        "source",
        "use",
        "checked_at",
        "outcome",
        "grant",
        "produced",
    }


def test_no_field_states_an_externality_claim() -> None:
    """ADR-0185 §3: the origin fact a read record carries is its ``source``.

    A boolean mirroring ``EgressBinding.planned_with_external_content`` would be
    ``True`` on every row ever written, because ADR-0183 rules that "the adversary
    writes the source and a reader derives no standing from what it reads" — which
    is ADR-0106 §2's second-spelling failure and ADR-0045 §1's surface with no
    consumer at once. Pinned as an absence because an absence is what a later lane
    would fill in without noticing.
    """
    dumped = _record().model_dump()

    assert not any("external" in name or "origin" in name for name in dumped)


def test_a_naive_instant_is_refused() -> None:
    """``UtcInstant``: timezone-aware, and naive refused (ADR-0023 §5)."""
    with pytest.raises(ValidationError):
        _record(checked_at=datetime(2026, 8, 1, 9, 0))  # noqa: DTZ001 — the subject


def test_the_record_survives_a_json_round_trip() -> None:
    """A row is stored as its JSON dump and rebuilt on every read."""
    original = _record(outcome=ReadOutcome.DISCARDED, produced=4)

    assert SourceReadRecord.model_validate(original.model_dump(mode="json")) == original
