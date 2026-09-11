"""``SearchSupply``: what one composition may be composed over (ADR-0238 §2; ADR-0246 §3).

ADR-0231 §3 gave ``QueryComposer.compose`` one positional argument and made the
utterance-only property **decidable from the signature**, on ADR-0093 §10's ground
that "a caller able to widen the read is a caller able to defeat the bound".
ADR-0238 §2 keeps the one argument and widens what it carries, putting two bounds on
the population instead: §2's three populations, and that a non-empty ``records`` is
built only for a destination whose recorded trust is ``USER_CHOSEN``. **Both are the
one construction site's**, and ADR-0245 §3's third clause says in terms that the
trust condition "is not a property this type can hold" — so what is checked here is
what the type *is*, not a population it refuses.

**ADR-0246 §11's Arms D, D' and B' are the arms this file carries, and they invert
ADR-0245 §11's Arm B exclusion limb.** (The ADR writes those names with a prime,
rendered as a plain apostrophe here because ruff refuses the ambiguous character in
Python source.) Reach is audience control — ADR-0217 §1's
denotation of a set of **people** — and a search provider the owner named in a
recorded act is not a person this assistant talks to, so on a destination the user
chose ``Placement.reach`` does not bind at all: no record is withheld on its reach,
on its setter, or on any combination of the two, **whatever the setter** (ADR-0246
§1). ADR-0245 §3's ``AfterValidator`` is deleted with that decision rather than kept
as a predicate that cannot fail (§3), and the cases below are what fails loudly for a
lane that left it in place.

**The deletion hands nothing back to the caller** (ADR-0246 §3). What the validator
ever enforced was the *placement* predicate; the two bounds that remain were never
properties of the type. So no bound moves from the type to the caller — one bound
ceases to exist and the other two stay exactly where ADR-0238 §2 put them.

The audit halves — ``withheld`` at zero and ADR-0245 §7's supplied-narrowed count
over every setter — are the servicing site's and are in
``tests/orchestration/test_closed_loop.py``, with Arm H's reply-side subtraction in
``tests/orchestration/test_spoken_disclosure.py``.
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


#: The narrowing the owner made by their **own act** (ADR-0217 §3), and the one a
#: model **proposed** (§4) — the two ADR-0245 §2 excluded by name and ADR-0246 §1
#: admits. ADR-0217 §1's table forbids ``reach=OWNER`` with no setter, so a narrowed
#: placement always names who narrowed it.
_NARROWED_BY_THE_OWNER: Final = Placement(
    reach=PlacementReach.OWNER, set_by=PlacementSetter.OWNER_ACT, set_at=_NOW
)
_NARROWED_BY_A_MODEL: Final = Placement(
    reach=PlacementReach.OWNER, set_by=PlacementSetter.PROPOSED, set_at=_NOW
)
_ADMITTED_NARROWINGS: Final = [_NARROWED_BY_THE_OWNER, _NARROWED_BY_A_MODEL]

#: The narrowing ADR-0204 §2's evaluation writes through ADR-0217 §3 — the placement a
#: stamped episode of the conversation carries, which is the record #2224 watched
#: ADR-0238 §3's filter drop on every later turn.
_DERIVED: Final = Placement(reach=PlacementReach.OWNER, set_by=PlacementSetter.DERIVED)


# --- §2: exactly two fields --------------------------------------------------


def test_the_supply_carries_two_fields_and_no_third() -> None:
    """§2 states the members exactly, and a lane adding one is changing that decision.

    Frozen and extra-forbidding, so a caller cannot smuggle a third value past the one
    parameter by attaching it to the value that parameter takes — which would be the
    absent-parameter bound defeated one level down. ADR-0246 §3 keeps this entire:
    "**`SearchSupply` keeps everything else ADR-0238 §2 gave it.** Exactly two fields
    and a lane adds no third", and deleting the validator adds nothing back.
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
    composes exactly as this corpus composes today. ADR-0246 §3 keeps the tuple
    immutable and the default empty on that same ground.
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


# --- ADR-0246 §11 Arms D, D', B': the type refuses no placement --------------


@pytest.mark.parametrize("placement", _ADMITTED_NARROWINGS, ids=lambda p: str(p.set_by))
def test_a_narrowing_the_owner_or_a_model_made_is_carried_not_refused(
    placement: Placement,
) -> None:
    """ADR-0246 §11's **Arms D and D'**, on the type, and this inverts ADR-0245 §11 Arm B.

    Arm D: "the supply is constructed rather than refused — asserted on the type
    directly, by constructing a ``SearchSupply`` carrying such a record, **so that a
    lane which left the validator in place fails the arm loudly**". Arm D' is the same
    claim for the placement ``learning/observer.py``'s observation pass writes, which
    is the one a *preference* carries: ground 1 of the owner's ruling is about exactly
    that preference silently dropping out of a follow-up query.

    ADR-0245 §2 refused both by name — the owner's act because "the system records the
    act and not its reason", and the proposal because "the ruling is about the
    *derivation*". The owner has now ruled that the logic reaches both: their explicit
    guard is defined by ADR-0217 §3 as setting reach and nothing else, and a guarded
    record has never meant "local only", it has meant "not for other people".
    """
    held = SearchSupply(utterance=UTTERANCE, records=(belief(placement=placement),))

    assert [record.id for record in held.records] == ["b-1"]
    assert held.records[0].placement is placement


@pytest.mark.parametrize("placement", _ADMITTED_NARROWINGS, ids=lambda p: str(p.set_by))
def test_the_admission_reaches_a_record_of_any_kind(placement: Placement) -> None:
    """§3: the fact is the ``Placement`` on ``MemoryBase``, so every kind carries it.

    An episode is the record ADR-0238 §2's *first* population is made of — "episodes of
    this conversation that `orchestration` selected into the turn's supply" — so a lane
    that deleted the validator for beliefs alone, or kept a kind-specific check
    somewhere, would leave the population most likely to be narrowed refused.
    """
    held = SearchSupply(utterance=UTTERANCE, records=(episode(placement=placement),))

    assert [record.id for record in held.records] == ["e-1"]


def test_a_derived_narrowing_is_admitted_and_that_limb_of_arm_b_stands() -> None:
    """ADR-0246 §11's **Arm B'**: "Arm B's ``DERIVED`` limb stands."

    ADR-0245 §1 admitted this pair and ADR-0246 §1 does not disturb it — what §1 widens
    is the *rest* of the field's range, and a decision that admitted every other setter
    while quietly dropping this one would be a regression nothing else here would
    catch. It is also the producer ADR-0238 §2's cross-turn promise needed: the stamped
    episode a later turn retrieves carries exactly this pair (#2224).
    """
    held = SearchSupply(
        utterance=UTTERANCE,
        records=(episode(placement=_DERIVED), belief("b-1", placement=_DERIVED)),
    )

    assert [record.id for record in held.records] == ["e-1", "b-1"]
    assert all(record.placement.set_by is PlacementSetter.DERIVED for record in held.records)


def test_every_placement_a_record_can_carry_reaches_a_supply() -> None:
    """ADR-0246 §1: "there being no combination it refuses."

    ADR-0245 §11's Arm B asserted an admitted set of exactly two combinations; §1
    supersedes that clause, so the sweep now asserts the **whole** range of pairs
    ``Placement``'s own table can carry (ADR-0217 §1). Driven as a sweep rather than as
    a list of cases so that a reach denotation a later ADR adds is admitted here on the
    day it lands — ADR-0246 §12's last deferral states that answer in terms: "a later
    denotation binds no more at a supply than ``OWNER`` does, because reach does not
    bind there at all."

    A pair ``Placement`` itself refuses is not this type's exclusion, which is why the
    sweep asks what a placement can be built from rather than asserting a hand-written
    list.
    """
    constructible = {
        (reach, setter)
        for reach in PlacementReach
        for setter in (None, *PlacementSetter)
        if _placeable(reach, setter)
    }

    assert {pair for pair in constructible if not _supplies(*pair)} == set(), (
        "no placement a record can carry is refused by the supply (ADR-0246 §1, §3)"
    )
    assert (PlacementReach.OWNER, PlacementSetter.OWNER_ACT) in constructible, "Arm D's pair"
    assert (PlacementReach.OWNER, PlacementSetter.PROPOSED) in constructible, "Arm D''s pair"
    assert (PlacementReach.OWNER, PlacementSetter.DERIVED) in constructible, "Arm B''s pair"


def _placement(reach: PlacementReach, setter: PlacementSetter | None) -> Placement | None:
    """One placement, or ``None`` where ADR-0217 §1's own table refuses the pair."""
    try:
        return Placement(reach=reach, set_by=setter, set_at=_NOW if setter is not None else None)
    except ValidationError:
        return None


def _placeable(reach: PlacementReach, setter: PlacementSetter | None) -> bool:
    """Whether ADR-0217 §1's table admits this pair at all."""
    return _placement(reach, setter) is not None


def _supplies(reach: PlacementReach, setter: PlacementSetter | None) -> bool:
    """Whether a supply holding one record so placed can be constructed."""
    placement = _placement(reach, setter)
    assert placement is not None
    try:
        SearchSupply(utterance=UTTERANCE, records=(belief(placement=placement),))
    except ValidationError:  # pragma: no cover — ADR-0246 §3 leaves nothing to raise it
        return False
    return True


def test_a_mixed_supply_is_carried_whole_and_nothing_is_dropped() -> None:
    """ADR-0246 §3, and it is the shape ADR-0245 §11's Arm B refused.

    ADR-0245's type refused the *whole* supply where one member was excluded, so that a
    caller could not be left believing it had composed over a set it did not. With no
    exclusion left there is nothing to refuse and nothing to drop: the four placements
    a record can carry arrive together, in the order the builder gave them.

    A type that had been "fixed" by pruning rather than by deleting the validator fails
    here — which is the silence ADR-0128 §2 is about one seam over, and it would put
    the supplied count the audit reads out of the servicing site's reach.
    """
    supplied = (
        belief("b-anyone"),
        belief("b-derived", placement=_DERIVED),
        belief("b-guarded", placement=_NARROWED_BY_THE_OWNER),
        episode("e-proposed", placement=_NARROWED_BY_A_MODEL),
    )

    held = SearchSupply(utterance=UTTERANCE, records=supplied)

    assert held.records == supplied


def test_records_are_carried_in_the_order_given() -> None:
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


def test_the_default_placement_reaches_a_supply_unchanged() -> None:
    """ADR-0217 §1's default reach is ``ANYONE``, and the ordinary record is unmoved.

    Stated because every case above is about a *narrowed* record: this is the one that
    says the population ADR-0231 §3 always carried composes exactly as it did, which is
    ADR-0246 §1's honouring limb — "what it does is subtract a filter rather than read
    a new fact".
    """
    assert Placement().reach is PlacementReach.ANYONE
    assert SearchSupply(utterance=UTTERANCE, records=(belief(),)).records[0].id == "b-1"
