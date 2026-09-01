"""ADR-0221 §11's tests 8 and 9: the values are pinned, and absence still decodes.

Test 8 — *every enum value is pinned* — is asserted **over the whole membership**
rather than member by member, and that is the whole point of it. §2 fixes each
member's serialised value because a ``StrEnum`` serialises its value and
:class:`~ai_assistant.core.types.EpisodicMemory` is wire-carried as well as
persisted, so two conforming implementations emitting ``step_executed`` and
``STEP_EXECUTED`` for one fact would leave every record written under the loser
undecodable — on the field §8 makes the migration's discriminator. A per-member
assertion would pass while a *seventeenth* member arrived spelled any way at all,
which is exactly the drift §2's closing clause forbids: "a member added later takes
a value of the same form — the member name lower-cased". So both halves are
asserted: the exact roster of sixteen, and the form rule that outlives it.

Test 9 — *a record constructed with neither new field* — is the migration §8 calls
self-clearing, read from the record's side. Both fields are additive with defaults
on a model that does not set ``extra="forbid"``, so a record already in a store
deserialises unchanged, and the **absence** of ``disposition`` is the discriminator
between a record written before ADR-0221 and one written after it. Nothing else in
the tree asserts that: the store suite proves a record the store was *given* comes
back whole (``tests/memory/memory_store_contract.py``), and this proves a payload
written before the fields existed decodes at all.

Scoped to ``core``. What each render site does with a disposition is ADR-0221 §3's
and Lane D's; what capture writes into either field is §5's and Lane E's. Neither is
asserted here, and no phrase table appears in this module for the reason §3 keeps
them out of ``core``.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import pytest

from ai_assistant.core.types import (
    Capture,
    Disposition,
    EpisodicMemory,
    ExchangeDisposition,
    MemorySource,
    Modality,
    Provenance,
    RouteOutcome,
)

if TYPE_CHECKING:
    from enum import StrEnum

_WHEN = datetime(2026, 6, 1, tzinfo=UTC)

#: ADR-0221 §2's table, member by member, in its own order: the no-step case, then
#: one per :class:`Disposition` member, then one per :class:`RouteOutcome` member.
#: Spelled out here rather than derived from the source enums — a derivation would
#: reproduce whatever the implementation did, including a mistake, and the point of
#: the pin is that the ADR and the code agree.
_DISPOSITION_VALUES: dict[str, str] = {
    "NO_ACTION_NEEDED": "no_action_needed",
    "STEP_EXECUTED": "step_executed",
    "STEP_DENIED": "step_denied",
    "STEP_AWAITING_CONFIRMATION": "step_awaiting_confirmation",
    "STEP_NO_CAPABLE_TOOL": "step_no_capable_tool",
    "STEP_AMBIGUOUS_CAPABILITY": "step_ambiguous_capability",
    "STEP_INVALID_PARAMETERS": "step_invalid_parameters",
    "STEP_EGRESS_UNBINDABLE": "step_egress_unbindable",
    "ROUTED_PERFORMED": "routed_performed",
    "ROUTED_AWAITING_CONFIRMATION": "routed_awaiting_confirmation",
    "ROUTED_REFUSED": "routed_refused",
    "ROUTED_AMBIGUOUS": "routed_ambiguous",
    "ROUTED_AMBIGUOUS_TRUNCATED": "routed_ambiguous_truncated",
    "ROUTED_NOT_FOUND": "routed_not_found",
    "ROUTED_UNRECORDED": "routed_unrecorded",
    "ROUTED_FAILED": "routed_failed",
}

#: ADR-0221 §5's two, pinned the same way and under §2's rule, which §5 extends to
#: this enum in terms.
_MODALITY_VALUES: dict[str, str] = {"TEXT": "text", "SPEECH": "speech"}


def _provenance() -> Provenance:
    return Provenance(source=MemorySource.OBSERVED, confidence=0.6, last_updated=_WHEN)


def _episode(**overrides: Any) -> EpisodicMemory:
    """An episode with neither new field stated unless a case states one."""
    return EpisodicMemory(
        id="e1",
        content="The user asked: where did we land on the flights?",
        provenance=_provenance(),
        occurred_at=_WHEN,
        **overrides,
    )


# --- §11.8: every enum value is pinned, over the whole membership -------------


def test_exchange_disposition_has_exactly_sixteen_members() -> None:
    """§2's count, asserted as a count so a member cannot be added unnoticed.

    Sixteen is not an arbitrary number: it is one per :class:`Disposition` member,
    one for the no-step case, and one per :class:`RouteOutcome` member. Asserting it
    against the *source* enums' lengths as well as against the literal is what makes
    this fail on the day a member is added to one of them — the cost §2 accepts and
    ``assert_never`` at the render sites collects.
    """
    assert len(ExchangeDisposition) == 16
    assert len(ExchangeDisposition) == len(Disposition) + 1 + len(RouteOutcome)


def test_every_exchange_disposition_value_is_the_one_the_adr_fixes() -> None:
    """§2's table, whole. A seventeenth member fails here rather than shipping."""
    assert {member.name: member.value for member in ExchangeDisposition} == _DISPOSITION_VALUES


def test_every_modality_value_is_the_one_the_adr_fixes() -> None:
    """§5's two, under §2's rule, which §5 binds to this enum in terms."""
    assert {member.name: member.value for member in Modality} == _MODALITY_VALUES


@pytest.mark.parametrize("enum", [ExchangeDisposition, Modality], ids=["disposition", "modality"])
def test_every_member_takes_a_value_of_the_stated_form(enum: type[StrEnum]) -> None:
    """§2's closing clause: the value is the member name lower-cased.

    The half of test 8 the roster above cannot carry. A member added later is a
    member the roster does not name, so the roster's failure says only "something
    changed"; this says *what* the new member's value has to be, and fails a member
    given a second spelling, an alias or a numeric encoding.
    """
    assert all(member.value == member.name.lower() for member in enum)


@pytest.mark.parametrize("member", list(ExchangeDisposition), ids=lambda m: m.value)
def test_a_record_round_trips_carrying_the_same_disposition_back(
    member: ExchangeDisposition,
) -> None:
    """§11.8's second half, over the whole membership rather than one member.

    Through JSON rather than through ``model_dump()`` alone, because the claim §2
    rests on is about what a *peer* decodes: the value that leaves this system as
    text is the value that comes back as this member.
    """
    encoded = json.loads(_episode(disposition=member).model_dump_json())

    assert encoded["disposition"] == member.value
    assert EpisodicMemory.model_validate(encoded).disposition is member


@pytest.mark.parametrize("member", list(Modality), ids=lambda m: m.value)
def test_a_record_round_trips_carrying_the_same_modality_back(member: Modality) -> None:
    """§11.8's second half for §5's enum, nested inside ``capture``."""
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


def test_a_record_constructed_with_neither_field_carries_the_defaults() -> None:
    """§11.9's first half: ``disposition`` of ``None`` and ``modality`` of ``TEXT``.

    ``None`` is the discriminator §8 makes it — a record this system captured after
    ADR-0221 carries a member — and ``TEXT`` is true of what such a record holds
    rather than a value fallen back on: §5 makes it the value for a typed turn and
    for an episode carrying no user material at all.
    """
    record = _episode()

    assert record.disposition is None
    assert record.capture == Capture()
    assert record.capture.modality is Modality.TEXT


def test_a_record_written_before_the_fields_landed_decodes_to_the_same() -> None:
    """§11.9's second half, and the whole of §8's no-migration claim.

    The payload is built by *removing* both keys from a current record's encoding,
    which is what a row written before ADR-0221 is: the same document without them.
    Building one by hand would pin this module's idea of the old shape instead of the
    store's.
    """
    written_before = json.loads(_episode().model_dump_json())
    del written_before["disposition"]
    del written_before["capture"]

    decoded = EpisodicMemory.model_validate(written_before)

    assert decoded.disposition is None
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
