"""ADR-0221 §11's tests 8 and 9 for ``Modality``: values pinned, absence decodes.

Test 8 — *every enum value is pinned* — is asserted **over the whole membership**
rather than member by member, and that is the whole point of it. §2 fixes each
member's serialised value because a ``StrEnum`` serialises its value and the record
carrying it is wire-carried as well as persisted, so two conforming implementations
emitting ``speech`` and ``SPEECH`` for one fact would leave every record written
under the loser undecodable. A per-member assertion would pass while a third member
arrived spelled any way at all, which is exactly the drift §2's closing clause
forbids: "a member added later takes a value of the same form — the member name
lower-cased". So both halves are asserted: the exact roster, and the form rule that
outlives it. §5 binds :class:`~ai_assistant.core.types.Modality` to that rule in
terms.

ADR-0287 §2 removed ``ExchangeDisposition``, the other enum §11 test 8 pinned, with
the transcript archive that was its one carrier.

Test 9 — *a record constructed with no capture stated* — is the migration §8 calls
self-clearing, read from the record's side: ``capture`` is additive with a default
on a model that does not set ``extra="forbid"``, so a record already in a store
deserialises unchanged. Nothing else in the tree asserts that: the store suite
proves a record the store was *given* comes back whole
(``tests/memory/memory_store_contract.py``), and this proves a payload written
before the field existed decodes at all.

Scoped to ``core``. What capture writes into ``capture`` is §5's and Lane E's, and
is not asserted here.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import pytest

from ai_assistant.core.types import (
    Capture,
    EpisodicMemory,
    MemorySource,
    Modality,
    Provenance,
)

_WHEN = datetime(2026, 6, 1, tzinfo=UTC)

#: ADR-0221 §5's two, pinned the same way and under §2's rule, which §5 extends to
#: this enum in terms.
_MODALITY_VALUES: dict[str, str] = {"TEXT": "text", "SPEECH": "speech"}


def _provenance() -> Provenance:
    return Provenance(source=MemorySource.OBSERVED, confidence=0.6, last_updated=_WHEN)


def _episode(**overrides: Any) -> EpisodicMemory:
    """An episode with no capture stated unless a case states one."""
    return EpisodicMemory(
        id="e1",
        content="The user asked: where did we land on the flights?",
        provenance=_provenance(),
        occurred_at=_WHEN,
        **overrides,
    )


# --- §11.8: every enum value is pinned, over the whole membership -------------


def test_every_modality_value_is_the_one_the_adr_fixes() -> None:
    """§5's two, under §2's rule, which §5 binds to this enum in terms."""
    assert {member.name: member.value for member in Modality} == _MODALITY_VALUES


def test_every_modality_member_takes_a_value_of_the_stated_form() -> None:
    """§2's closing clause: the value is the member name lower-cased.

    The half of test 8 the roster above cannot carry. A member added later is a
    member the roster does not name, so the roster's failure says only "something
    changed"; this says *what* the new member's value has to be, and fails a member
    given a second spelling, an alias or a numeric encoding.
    """
    assert all(member.value == member.name.lower() for member in Modality)


@pytest.mark.parametrize("member", list(Modality), ids=lambda m: m.value)
def test_a_record_round_trips_carrying_the_same_modality_back(member: Modality) -> None:
    """§11.8's second half, through JSON, nested inside ``capture``."""
    encoded = json.loads(_episode(capture=Capture(modality=member)).model_dump_json())

    assert encoded["capture"] == {"modality": member.value}
    assert EpisodicMemory.model_validate(encoded).capture.modality is member


def test_capture_is_frozen_and_carries_modality_alone() -> None:
    """§12.2: a frozen record carrying ``modality`` alone as ADR-0221 ships it.

    The field count is pinned because §5's two deferred facts — which derivation
    produced the text, and whether the source is retained — are declined *here* and
    land later as additive fields. A lane that shipped either as a ``None``-only slot
    would be choosing its type with no producer in hand, which ADR-0073 §4 refuses;
    this is what makes that a test failure rather than a review note.
    """
    assert Capture.model_config.get("frozen") is True
    assert set(Capture.model_fields) == {"modality"}


# --- §11.9: neither field stated, and a record written before they landed -----


def test_a_record_constructed_with_no_capture_carries_the_default() -> None:
    """§11.9's first half: ``modality`` of ``TEXT``.

    ``TEXT`` is true of what such a record holds rather than a value fallen back on:
    §5 makes it the value for a typed turn and for an episode carrying no user
    material at all.
    """
    record = _episode()

    assert record.capture == Capture()
    assert record.capture.modality is Modality.TEXT


def test_a_record_written_before_the_field_landed_decodes_to_the_same() -> None:
    """§11.9's second half, and the whole of §8's no-migration claim.

    The payload is built by *removing* the key from a current record's encoding,
    which is what a row written before ADR-0221 is: the same document without it.
    Building one by hand would pin this module's idea of the old shape instead of the
    store's.
    """
    written_before = json.loads(_episode().model_dump_json())
    del written_before["capture"]

    decoded = EpisodicMemory.model_validate(written_before)

    assert decoded.capture == Capture()
    assert decoded.capture.modality is Modality.TEXT
    assert decoded == _episode()


def test_a_record_carrying_an_unknown_member_still_decodes() -> None:
    """§8's other direction, and the reliance its no-bump reasoning rests on.

    ADR-0213 §11's case is that an older peer decoding a newer hub's record ignores a
    member it does not know — which holds only because these models do not set
    ``extra="forbid"``. Asserted from this side because the older peer is not
    available to assert it from: a record carrying a field no version of this model
    declares is what a future additive field looks like from here, and §5 promises
    exactly two of them.
    """
    from_a_newer_peer = json.loads(_episode().model_dump_json())
    from_a_newer_peer["capture"] = {"modality": "text", "derived_by": "some-later-field"}
    from_a_newer_peer["a_field_this_version_never_had"] = 1

    decoded = EpisodicMemory.model_validate(from_a_newer_peer)

    assert decoded.capture == Capture()
    assert decoded == _episode()
