"""ADR-0217's axis at the type: the state table, the meet, and the legacy decode.

§10's representative inputs, the ones that land on ``core``: every refusal of §1's
state table one arm each — at construction **and** on deserialisation, because a
validator that runs only on the first leaves the second as the route in — every row
of the table constructible, the meet and its instant tie-break, and §9's decode of a
record written before the field existed.

The arms that need a producer, a supply site or a store are elsewhere: the fold's
setter propagation is pinned against ``memory/ingest.py`` and its canonical fake,
the derivation over mixed placements against ``orchestration/consolidation.py``, and
the reduction to ADR-0199 §1's two audiences against the spoken supply site.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from ai_assistant.core.types import (
    EpisodicMemory,
    MemorySource,
    Placement,
    PlacementReach,
    PlacementSetter,
    Provenance,
)

_EARLIER = datetime(2026, 8, 29, 9, 0, tzinfo=UTC)
_LATER = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)


def _placement(**fields: object) -> dict[str, object]:
    """One placement as the mapping a store or a wire frame deserialises from."""
    return fields


# --- §1: the table is total, and its five refusals are refused --------------


@pytest.mark.parametrize(
    ("fields", "because"),
    [
        pytest.param(
            _placement(reach=PlacementReach.OWNER),
            "a narrowing no setter is accountable for",
            id="reach OWNER with no setter",
        ),
        pytest.param(
            _placement(set_at=_LATER),
            "an instant for a narrowing nobody made",
            id="an instant with no setter",
        ),
        pytest.param(
            _placement(reach=PlacementReach.ANYONE, set_by=PlacementSetter.DERIVED),
            "the laundering ADR-0204 §5 exists to stop, by construction",
            id="reach ANYONE set by DERIVED",
        ),
        pytest.param(
            _placement(
                reach=PlacementReach.ANYONE,
                set_by=PlacementSetter.PROPOSED,
                set_at=_LATER,
            ),
            "the same laundering, one setter over",
            id="reach ANYONE set by PROPOSED",
        ),
        pytest.param(
            _placement(reach=PlacementReach.OWNER, set_by=PlacementSetter.PROPOSED),
            "§4 owes a model-proposed-and-when stamp",
            id="PROPOSED with no instant",
        ),
        pytest.param(
            _placement(reach=PlacementReach.OWNER, set_by=PlacementSetter.OWNER_ACT),
            "§7's acts each write the instant of the act",
            id="OWNER_ACT with no instant",
        ),
    ],
)
def test_a_state_outside_the_table_is_refused_at_construction(
    fields: dict[str, object], because: str
) -> None:
    """§1's table is total and the states outside it are unrepresentable.

    On the type rather than at the producers, so no producer, decode or later lane
    can represent a combination ADR-0217 does not mean — which is what closes the two
    routes by which a bug elsewhere becomes a disclosure (``reason``, per case).
    """
    with pytest.raises(ValidationError):
        Placement(**fields)  # type: ignore[arg-type]  # the point of the case


@pytest.mark.parametrize(
    "fields",
    [
        pytest.param({"reach": "owner"}, id="reach OWNER with no setter"),
        pytest.param({"set_at": _LATER.isoformat()}, id="an instant with no setter"),
        pytest.param(
            {"reach": "anyone", "set_by": "derived"},
            id="reach ANYONE set by DERIVED",
        ),
        pytest.param(
            {"reach": "anyone", "set_by": "proposed", "set_at": _LATER.isoformat()},
            id="reach ANYONE set by PROPOSED",
        ),
        pytest.param({"reach": "owner", "set_by": "proposed"}, id="PROPOSED with no instant"),
        pytest.param({"reach": "owner", "set_by": "owner_act"}, id="OWNER_ACT with no instant"),
    ],
)
def test_a_state_outside_the_table_is_refused_on_deserialisation(
    fields: dict[str, object],
) -> None:
    """The same refusals on the *read* path, which is the route a validator misses.

    §10 asks for both explicitly: "a validator that runs only on the first leaves the
    second as the route in". A hand-edited store row and a frame from a peer that
    computed one of these both arrive here.
    """
    with pytest.raises(ValidationError):
        Placement.model_validate(fields)


@pytest.mark.parametrize(
    "placement",
    [
        pytest.param(Placement(), id="no setter, reach ANYONE, no instant"),
        pytest.param(
            Placement(reach=PlacementReach.OWNER, set_by=PlacementSetter.DERIVED),
            id="DERIVED without an instant, which §9's decode produces",
        ),
        pytest.param(
            Placement(reach=PlacementReach.OWNER, set_by=PlacementSetter.DERIVED, set_at=_LATER),
            id="DERIVED with an instant, which every derivation writes",
        ),
        pytest.param(
            Placement(reach=PlacementReach.OWNER, set_by=PlacementSetter.PROPOSED, set_at=_LATER),
            id="PROPOSED, whose instant is required",
        ),
        pytest.param(
            Placement(reach=PlacementReach.OWNER, set_by=PlacementSetter.OWNER_ACT, set_at=_LATER),
            id="OWNER_ACT narrowing",
        ),
        pytest.param(
            Placement(reach=PlacementReach.ANYONE, set_by=PlacementSetter.OWNER_ACT, set_at=_LATER),
            id="OWNER_ACT widening — the one act that may write reach ANYONE",
        ),
    ],
)
def test_every_row_of_the_table_is_constructible_and_round_trips(placement: Placement) -> None:
    """Each admitted row survives the encoding, because it is durable state.

    The read rule runs over records read back out of a store, so a placement that did
    not survive the encoding would leave every narrowed record speakable one restart
    later — ADR-0204 §8's argument for the boolean, over the field that replaced it.
    """
    assert Placement.model_validate_json(placement.model_dump_json()) == placement


def test_the_default_is_the_widest_reach_and_no_setter() -> None:
    """§6: the default is ADR-0199 §3's placement and this ADR adds narrowing only."""
    assert Placement() == Placement(reach=PlacementReach.ANYONE, set_by=None, set_at=None)


def test_the_setter_enumeration_is_exhaustive() -> None:
    """§1: three members, and no implementation or later ADR adds a fourth.

    Unlike :class:`PlacementReach`, whose members are "the vocabulary as it stands",
    this enumeration **is** exhaustive — it is §3's three setters, and a fourth would
    supersede §3's first clause rather than stack on it. Pinned so that adding one
    fails a test naming the clause instead of quietly widening who may narrow.
    """
    assert set(PlacementSetter) == {
        PlacementSetter.OWNER_ACT,
        PlacementSetter.DERIVED,
        PlacementSetter.PROPOSED,
    }


# --- §3: the meet, over a fold's eligible sides ------------------------------


_ANYONE_ACT = Placement(
    reach=PlacementReach.ANYONE, set_by=PlacementSetter.OWNER_ACT, set_at=_EARLIER
)
_OWNER_PROPOSED = Placement(
    reach=PlacementReach.OWNER, set_by=PlacementSetter.PROPOSED, set_at=_LATER
)
_OWNER_DERIVED = Placement(
    reach=PlacementReach.OWNER, set_by=PlacementSetter.DERIVED, set_at=_LATER
)
_OWNER_ACT = Placement(reach=PlacementReach.OWNER, set_by=PlacementSetter.OWNER_ACT, set_at=_LATER)
_LEGACY = Placement(reach=PlacementReach.OWNER, set_by=PlacementSetter.DERIVED)


@pytest.mark.parametrize(
    ("stored", "incoming", "expected"),
    [
        pytest.param(
            _ANYONE_ACT,
            _OWNER_PROPOSED,
            _ANYONE_ACT,
            id="an unguarded record is not re-narrowed by a proposal",
        ),
        pytest.param(
            _ANYONE_ACT,
            _OWNER_DERIVED,
            _OWNER_DERIVED,
            id="a derivation is eligible against an act, and an act does not lift one",
        ),
        pytest.param(
            Placement(),
            _OWNER_PROPOSED,
            _OWNER_PROPOSED,
            id="a proposal narrows a record nothing had narrowed",
        ),
        pytest.param(
            _OWNER_ACT,
            _OWNER_PROPOSED,
            _OWNER_ACT,
            id="an act outranks a proposal at the same reach",
        ),
        pytest.param(
            _OWNER_DERIVED,
            _OWNER_ACT,
            _OWNER_DERIVED,
            id="a derivation outranks an act at the same reach",
        ),
        pytest.param(
            _OWNER_ACT,
            Placement(),
            _OWNER_ACT,
            id="a duplicate does not dilute a guard",
        ),
        pytest.param(
            _LEGACY,
            Placement(),
            _LEGACY,
            id="a decoded legacy narrowing keeps its unknown instant",
        ),
    ],
)
def test_the_fold_takes_the_meet_over_its_eligible_sides(
    stored: Placement, incoming: Placement, expected: Placement
) -> None:
    """§3's meet, its eligibility filter and its instant rule, in one arm each.

    A ``PROPOSED`` side is discarded against an ``OWNER_ACT`` or ``DERIVED`` one
    rather than weighed, because these are two placements of **one belief** and
    weighing it would let a model undo an owner's act by duplication. Nothing else is
    ever discarded, and the survivor's instant is the winning side's rather than the
    instant of the fold.
    """
    assert stored.folded_with(incoming) == expected
    assert incoming.folded_with(stored) == expected, "the meet does not depend on the side order"


@pytest.mark.parametrize("setter", list(PlacementSetter), ids=str)
def test_two_like_sides_carry_the_earlier_instant(setter: PlacementSetter) -> None:
    """§3's tie-break, taken once for each setter, in both orders.

    The stamp names when the placement was set, so where two eligible sides agree on
    reach and setter the survivor takes the **earlier** instant — never the instant of
    the fold, and never the later one, which would move a stamp forward on the
    accident of a duplicate arriving.
    """
    reach = PlacementReach.ANYONE if setter is PlacementSetter.OWNER_ACT else PlacementReach.OWNER
    early = Placement(reach=reach, set_by=setter, set_at=_EARLIER)
    late = Placement(reach=reach, set_by=setter, set_at=_LATER)

    assert early.folded_with(late) == early
    assert late.folded_with(early) == early


def test_an_unknown_instant_absorbs_a_known_one() -> None:
    """§3, §1: a tie against a decoded legacy placement stays unknown.

    Adopting the known instant would assert a first narrowing this system cannot
    vouch for — §1's "unknown, never unrecorded-therefore-recent" — so the absence
    absorbs rather than losing to a measurement.
    """
    assert _LEGACY.folded_with(_OWNER_DERIVED) == _LEGACY
    assert _OWNER_DERIVED.folded_with(_LEGACY) == _LEGACY


def test_three_duplicates_meet_the_same_way_in_any_order() -> None:
    """§3: the rule is total, commutative and associative.

    What makes it usable is that the answer does not depend on which side an
    implementation calls the stored one, nor on the order three duplicates are merged
    in — so a fold performed left to right and one performed right to left agree.
    """
    left = _OWNER_ACT.folded_with(_LEGACY).folded_with(Placement())
    right = Placement().folded_with(_LEGACY.folded_with(_OWNER_ACT))

    assert left == right == _LEGACY


# --- §3: the derivation's meet, where no side is discarded -------------------


def test_a_derivation_meets_every_supplied_placement_proposed_included() -> None:
    """§3's clause bounding eligibility to the fold, at the type.

    A derivation's inputs are *different records*: the derived record carries no act
    of the owner's for a proposal to override, so discarding one would protect
    nothing and would launder an ``OWNER`` input — the failure ADR-0204 §5's
    narrowest-over-every-record-supplied rule exists to prevent. The setter follows
    the surviving reach, so a narrowing only a proposal supplied is recorded
    ``PROPOSED`` and the owner still lifts in one act what a model proposed.
    """
    assert Placement.narrowest_of([_ANYONE_ACT, _OWNER_PROPOSED]) == _OWNER_PROPOSED


def test_a_derivation_over_no_placements_is_the_default() -> None:
    """The empty meet is §6's default rather than an invented narrowing."""
    assert Placement.narrowest_of([]) == Placement()


def test_a_derivation_takes_the_strongest_setter_at_the_surviving_reach() -> None:
    """§3: a side whose reach is wider supplies no setter, having supplied none of it."""
    assert Placement.narrowest_of([_ANYONE_ACT, _OWNER_PROPOSED, _OWNER_DERIVED]) == _OWNER_DERIVED


# --- §9: a record already in a store is decoded, never defaulted ------------


def _stored_episode(*, withheld: bool) -> dict[str, object]:
    """One episode as a store written under ADR-0204 deserialises from."""
    return {
        "id": "e1",
        "kind": "episodic",
        "content": "the user asked about a guarded belief",
        "occurred_at": _EARLIER,
        "provenance": {
            "source": MemorySource.OBSERVED.value,
            "confidence": 0.6,
            "last_updated": _EARLIER,
            "supplied_withheld_content": withheld,
        },
    }


def test_a_record_stamped_before_the_field_existed_decodes_narrowed() -> None:
    """§9's decode, on the load-bearing site: the persistent store.

    Without it every record ADR-0204 narrowed would decode as **unnarrowed** on the
    day this field landed — ADR-0204 §1's fourth clause hazard, a decode default read
    as a measurement, with a disclosure consequence. The decoded placement carries no
    instant, because nothing timed an act that predates the field.
    """
    record = EpisodicMemory.model_validate(_stored_episode(withheld=True))

    assert record.placement == Placement(reach=PlacementReach.OWNER, set_by=PlacementSetter.DERIVED)
    assert record.placement.set_at is None


def test_a_record_the_old_field_left_false_decodes_to_the_default() -> None:
    """The mapping is total and one-directional: ``false`` or absent is the default."""
    stamped = EpisodicMemory.model_validate(_stored_episode(withheld=False))
    absent = _stored_episode(withheld=False)
    provenance = absent["provenance"]
    assert isinstance(provenance, dict)
    del provenance["supplied_withheld_content"]

    assert stamped.placement == Placement()
    assert EpisodicMemory.model_validate(absent).placement == Placement()


def test_the_legacy_member_never_widens_a_placement_the_record_carries() -> None:
    """One-directional: a stored placement is what the record carries, whatever else is.

    A row written after the field lands carries its own placement; the legacy member
    beside it — a hand-edited row, or a peer that kept emitting one — decides nothing.
    """
    stored = _stored_episode(withheld=False)
    stored["placement"] = {"reach": "owner", "set_by": "derived"}

    assert EpisodicMemory.model_validate(stored).placement == Placement(
        reach=PlacementReach.OWNER, set_by=PlacementSetter.DERIVED
    )


def test_the_removed_member_is_not_readable_off_a_decoded_provenance() -> None:
    """§1: the field is removed rather than kept beside the placement.

    Two recorded values in front of one read is the shape ADR-0217 §1 refuses, and a
    ``Provenance`` that still answered to the old name would be exactly that.
    """
    record = EpisodicMemory.model_validate(_stored_episode(withheld=True))

    assert not hasattr(record.provenance, "supplied_withheld_content")
    assert "supplied_withheld_content" not in Provenance.model_fields
