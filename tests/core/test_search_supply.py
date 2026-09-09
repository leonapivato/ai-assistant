"""``SearchSupply``: what one composition may be composed over (ADR-0238 §2, §3).

ADR-0231 §3 gave ``QueryComposer.compose`` one positional argument and made the
utterance-only property **decidable from the signature**, on ADR-0093 §10's ground
that "a caller able to widen the read is a caller able to defeat the bound".
ADR-0238 §2 keeps the one argument and moves the property onto the value, so the
cases here are where that relocation is actually checked: a caller holding an
excluded record still has nothing to pass, because the type refuses it.

**ADR-0238 §15's Arm 4 is the negative arm this file carries.** "A record whose
``placement.reach`` is ``OWNER`` is refused by ``SearchSupply`` at construction, in a
selection the result influenced and in one it did not" — the whole point of putting
the check on the type is that those two are the same construction, so no selection an
injected result influenced can reach a different outcome. The audit half of that arm
(the withheld count) is the servicing site's and is not here.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Final

import pytest
from pydantic import ValidationError

from ai_assistant.core.types import (
    EpisodicMemory,
    MemorySource,
    Placement,
    PlacementReach,
    PlacementSetter,
    Provenance,
    SearchSupply,
    SemanticMemory,
)

_NOW: Final = datetime(2026, 9, 9, 12, 0, tzinfo=UTC)
UTTERANCE: Final = "find more about that, taking my preferences into account"


def belief(record_id: str = "b-1", *, placement: Placement | None = None) -> SemanticMemory:
    """One belief a turn's retrieval selected."""
    return SemanticMemory(
        id=record_id,
        content="Porto is on the Douro",
        fact="Porto is on the Douro",
        placement=placement if placement is not None else Placement(),
        provenance=Provenance(source=MemorySource.OBSERVED, confidence=0.6, last_updated=_NOW),
    )


def episode(record_id: str = "e-1", *, placement: Placement | None = None) -> EpisodicMemory:
    """One captured turn of this conversation."""
    return EpisodicMemory(
        id=record_id,
        content="we looked that up together",
        occurred_at=_NOW,
        placement=placement if placement is not None else Placement(),
        provenance=Provenance(source=MemorySource.OBSERVED, confidence=0.9, last_updated=_NOW),
    )


#: The narrower reach, with each setter §3's filter must treat identically. ADR-0217
#: §1's table forbids ``reach=OWNER`` with no setter, so a narrowed placement always
#: names who narrowed it — and the filter reads the *reach*, never the setter.
_OWNER_PLACEMENTS: Final = [
    Placement(reach=PlacementReach.OWNER, set_by=PlacementSetter.DERIVED),
    Placement(reach=PlacementReach.OWNER, set_by=PlacementSetter.OWNER_ACT, set_at=_NOW),
    Placement(reach=PlacementReach.OWNER, set_by=PlacementSetter.PROPOSED, set_at=_NOW),
]


# --- §2: exactly two fields --------------------------------------------------


def test_the_supply_carries_two_fields_and_no_third() -> None:
    """§2 states the members exactly, and a lane adding one is changing that decision.

    Frozen and extra-forbidding, so a caller cannot smuggle a third value past the one
    parameter by attaching it to the value that parameter takes — which would be the
    absent-parameter bound defeated one level down.
    """
    assert set(SearchSupply.model_fields) == {"utterance", "records"}
    assert SearchSupply.model_config.get("frozen") is True
    assert SearchSupply.model_config.get("extra") == "forbid"

    with pytest.raises(ValidationError):
        SearchSupply(utterance=UTTERANCE, context="anything")  # type: ignore[call-arg]


def test_records_default_to_empty_which_is_the_ratified_population() -> None:
    """§2: the default is what ADR-0231 §3's ratified population carries.

    Where the destination reads ``UNCHOSEN`` the supply carries the utterance and an
    empty ``records``, "and ADR-0231 §3's utterance-only property therefore holds for
    that destination exactly as ratified". A caller that supplies nothing therefore
    composes exactly as this corpus composes today.
    """
    assert SearchSupply(utterance=UTTERANCE).records == ()


def test_the_utterance_is_non_blank_and_encodable() -> None:
    """§2: "the unrewritten user text for the turn being planned, as `orchestration`
    already holds it" — ADR-0231 §3's argument, unchanged in everything but where it
    sits."""
    with pytest.raises(ValidationError):
        SearchSupply(utterance="   ")
    with pytest.raises(ValidationError):
        SearchSupply(utterance="lone surrogate \ud800")


# --- §2, §3, §15's Arm 4: the exclusion, on the type ------------------------


@pytest.mark.parametrize("placement", _OWNER_PLACEMENTS, ids=lambda p: str(p.set_by))
def test_a_record_placed_for_the_owner_is_refused_at_construction(
    placement: Placement,
) -> None:
    """§15's Arm 4, and §2's "the refusal is on the type".

    Evaluated **per record and regardless of why that record was selected**, which is
    what makes ADR-0238 §12's negative arm true: an injected result cannot carry an
    excluded record into a query, because no selection a result influenced can place
    one in a supply. Driven across all three setters, because the filter reads
    ADR-0217 §1's *reach* and a lane reading the setter instead would admit two of
    them.
    """
    with pytest.raises(ValidationError, match="ANYONE"):
        SearchSupply(utterance=UTTERANCE, records=(belief(placement=placement),))


def test_the_refusal_reaches_a_record_of_any_kind() -> None:
    """§3: the fact is ``Placement.reach`` on ``MemoryBase``, so every kind carries it.

    An episode is the record §2's *first* population is made of — "episodes of this
    conversation that `orchestration` selected into the turn's supply" — so a filter
    that only reached beliefs would let the population most likely to be narrowed
    through untouched.
    """
    narrowed = Placement(reach=PlacementReach.OWNER, set_by=PlacementSetter.DERIVED)

    with pytest.raises(ValidationError, match="ANYONE"):
        SearchSupply(utterance=UTTERANCE, records=(episode(placement=narrowed),))


def test_one_excluded_record_refuses_the_whole_supply() -> None:
    """Not filtered out quietly: the *supply* is refused.

    A type that dropped the member would leave the caller believing it had composed
    over a set it did not, which is the silence ADR-0128 §2 is about one seam over —
    and it would put the withheld count §11's audit reads out of the servicing site's
    reach.
    """
    narrowed = Placement(reach=PlacementReach.OWNER, set_by=PlacementSetter.OWNER_ACT, set_at=_NOW)

    with pytest.raises(ValidationError, match="1 of 2"):
        SearchSupply(
            utterance=UTTERANCE,
            records=(belief("b-1"), belief("b-2", placement=narrowed)),
        )


def test_records_placed_for_anyone_are_admitted_in_the_order_given() -> None:
    """The ordinary case, and the order is the caller's.

    §2 closes ``records`` to three populations but says nothing about their order —
    that is the servicing site's, and this type neither sorts nor re-ranks. ADR-0231
    §11's "no component augments, re-ranks or annotates a query" is about the
    composer's *answer*; what this asserts is that the type does not do it on the way
    in either.
    """
    supplied = (episode("e-1"), belief("b-1"), belief("b-2"))

    held = SearchSupply(utterance=UTTERANCE, records=supplied)

    assert [record.id for record in held.records] == ["e-1", "b-1", "b-2"]


def test_the_default_placement_is_the_admitted_one() -> None:
    """ADR-0217 §1's default reach is ``ANYONE``, so an unnarrowed record passes.

    Stated because the refusal above would be indistinguishable from a type that
    refused *everything*: this is the case that says the filter has a true branch.
    """
    assert Placement().reach is PlacementReach.ANYONE
    assert SearchSupply(utterance=UTTERANCE, records=(belief(),)).records[0].id == "b-1"
