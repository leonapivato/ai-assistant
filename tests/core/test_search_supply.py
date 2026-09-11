"""``SearchSupply``: what one composition may be composed over (ADR-0238 §2; ADR-0245 §2).

ADR-0231 §3 gave ``QueryComposer.compose`` one positional argument and made the
utterance-only property **decidable from the signature**, on ADR-0093 §10's ground
that "a caller able to widen the read is a caller able to defeat the bound".
ADR-0238 §2 keeps the one argument and moves the property onto the value, so the
cases here are where that relocation is actually checked: a caller holding an
excluded record still has nothing to pass, because the type refuses it.

**ADR-0245 §11's Arm B is the negative arm this file carries, and it replaces
ADR-0238 §15's Arm 4.** Reach is audience control (ADR-0245 §1), so the set the type
admits is stated positively over two combinations and no more: reach ``ANYONE``, and
reach ``OWNER`` narrowed by ``DERIVED``. A record placed reach ``OWNER`` setter
``OWNER_ACT``, and one placed reach ``OWNER`` setter ``PROPOSED``, are each refused at
construction — "in a selection a search result influenced and in one it did not", which
is the same construction, so no selection an injected result influenced can reach a
different outcome. **The refusal is asserted on the type directly, so that a builder
that filtered correctly could not make the arm pass.** The audit halves — the withheld
count and ADR-0245 §7's supplied-narrowed count — are the servicing site's and are in
``tests/orchestration/test_closed_loop.py``.
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


#: ADR-0245 §2's **excluded** narrowings: the one the owner made by their own act, and
#: the one a model proposed. ADR-0217 §1's table forbids ``reach=OWNER`` with no setter,
#: so a narrowed placement always names who narrowed it — and since ADR-0245 §1 the
#: filter reads **both** fields, which is why these two are here and ``DERIVED`` is not.
_EXCLUDED_PLACEMENTS: Final = [
    Placement(reach=PlacementReach.OWNER, set_by=PlacementSetter.OWNER_ACT, set_at=_NOW),
    Placement(reach=PlacementReach.OWNER, set_by=PlacementSetter.PROPOSED, set_at=_NOW),
]

#: ADR-0245 §2's second admitted combination — the placement a stamped episode of the
#: conversation carries (ADR-0204 §2 on ADR-0217 §3), which is the record #2224 watched
#: ADR-0238 §3's filter drop on every later turn.
_DERIVED: Final = Placement(reach=PlacementReach.OWNER, set_by=PlacementSetter.DERIVED)


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


# --- ADR-0245 §2, §3, §11's Arm B: the exclusion, on the type ---------------


@pytest.mark.parametrize("placement", _EXCLUDED_PLACEMENTS, ids=lambda p: str(p.set_by))
def test_a_narrowing_the_owner_or_a_model_made_is_refused_at_construction(
    placement: Placement,
) -> None:
    """ADR-0245 §11's Arm B, and §3's "the refusal is on the type".

    The two setters §2 excludes by name, on a destination of **any** recorded trust:
    ``OWNER_ACT``, because "the system records the act and not its reason" and admitting
    it would be deciding what the owner meant by it; and ``PROPOSED``, because the
    ruling is about the *derivation* and a setter it did not name is not admitted by it.

    Evaluated **per record and regardless of why that record was selected**, which is
    what keeps ADR-0245 §8's negative arm true over the narrowed excluded set: an
    injected result cannot carry an excluded record into a query, because no selection a
    result influenced can place one in a supply — the two selections are the same
    construction, and this is it.
    """
    with pytest.raises(ValidationError, match="DERIVED"):
        SearchSupply(utterance=UTTERANCE, records=(belief(placement=placement),))


@pytest.mark.parametrize("placement", _EXCLUDED_PLACEMENTS, ids=lambda p: str(p.set_by))
def test_the_refusal_reaches_a_record_of_any_kind(placement: Placement) -> None:
    """§3: the fact is the ``Placement`` on ``MemoryBase``, so every kind carries it.

    An episode is the record ADR-0238 §2's *first* population is made of — "episodes of
    this conversation that `orchestration` selected into the turn's supply" — so a filter
    that only reached beliefs would let the population most likely to be narrowed
    through untouched.
    """
    with pytest.raises(ValidationError, match="DERIVED"):
        SearchSupply(utterance=UTTERANCE, records=(episode(placement=placement),))


def test_a_derived_narrowing_is_admitted_and_that_is_the_decision() -> None:
    """ADR-0245 §1, over both kinds, and it is the producer ADR-0238 §2 lacked.

    "On such a supply a ``MemoryRecord`` whose ``placement.reach`` is
    ``PlacementReach.OWNER`` and whose ``placement.set_by`` is
    ``PlacementSetter.DERIVED`` is **admitted**, whichever of ADR-0238 §2's three
    populations selected it." Stated here as well as at the servicing site because the
    *type* is where ADR-0238 §3's first clause used to refuse it: a lane that fixed the
    builder and left the validator alone would build no supply at all (#2224).
    """
    held = SearchSupply(
        utterance=UTTERANCE,
        records=(episode(placement=_DERIVED), belief("b-1", placement=_DERIVED)),
    )

    assert [record.id for record in held.records] == ["e-1", "b-1"]
    assert all(record.placement.set_by is PlacementSetter.DERIVED for record in held.records)


def test_the_admitted_set_is_two_combinations_and_the_type_admits_no_third() -> None:
    """§2: "It admits no other combination."

    The positive statement of the rule, driven over every pair ADR-0217 §1's two reach
    denotations and three setters can make — so a lane that widened the predicate to any
    ``OWNER`` reach, or that read the setter without the reach, fails here rather than in
    a scenario someone has to think of. ``reach=ANYONE`` with a narrowing setter is not
    reachable through ``Placement``'s own table, which is why the sweep asks the type
    what it admits rather than asserting a hand-written list.
    """
    admitted = {
        (reach, setter)
        for reach in PlacementReach
        for setter in (None, *PlacementSetter)
        if _constructs(reach, setter)
    }

    assert admitted == {
        # §2's first limb is stated over the **reach alone**, so an owner's act that
        # widened a record back to ``ANYONE`` is admitted by it exactly as an unnarrowed
        # record is: what §2 excludes is a *narrowing* the owner made, and this is not
        # one (ADR-0217 §3's act may widen a ``PROPOSED`` or ``OWNER_ACT`` placement).
        (PlacementReach.ANYONE, None),
        (PlacementReach.ANYONE, PlacementSetter.OWNER_ACT),
        # §2's second limb, which is the whole of what ADR-0245 decides.
        (PlacementReach.OWNER, PlacementSetter.DERIVED),
    }


def _constructs(reach: PlacementReach, setter: PlacementSetter | None) -> bool:
    """Whether a supply holding one record so placed can be constructed at all.

    ``Placement`` refuses some pairs itself (ADR-0217 §1's table), and those are not the
    supply's exclusions — so a pair the placement cannot carry counts as not admitted
    here without the sweep having to know which of the two types refused it.
    """
    try:
        placement = Placement(
            reach=reach, set_by=setter, set_at=_NOW if setter is not None else None
        )
    except ValidationError:
        return False
    try:
        SearchSupply(utterance=UTTERANCE, records=(belief(placement=placement),))
    except ValidationError:
        return False
    return True


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
