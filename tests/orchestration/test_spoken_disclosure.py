"""ADR-0199's placement rules, decided from recorded origin (ADR-0200 §7, ADR-0203).

``orchestration.disclosure`` on its own: which records ADR-0199 §§2-3 place as
speakable on a channel of unbounded audience, decided from recorded origin and never
from content, as the phases apply the predicate through
:func:`~ai_assistant.orchestration.disclosure.admitted_to_understanding`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Final

import pytest

from ai_assistant.core.types import (
    Attestation,
    MemoryRecord,
    MemorySource,
    Placement,
    PlacementReach,
    PlacementSetter,
    Provenance,
    SemanticMemory,
)
from ai_assistant.orchestration.disclosure import (
    UnboundedAudienceSupply,
    admitted_to_understanding,
    speakable_sources,
)

_AT: Final = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)

#: The placement ADR-0217 §3's derivation writes for a record ADR-0204 §2 or §5
#: would have stamped ``True``: reach ``OWNER``, setter ``DERIVED``, at the instant
#: of the narrowing. Every *fixture* below that "carries the stamp" carries this.
_NARROWED: Final = Placement(reach=PlacementReach.OWNER, set_by=PlacementSetter.DERIVED, set_at=_AT)


_CALENDAR: Final = "calendar"

#: What a withheld record says. Recognisable, so an assertion can look for the
#: span itself rather than for "something about somebody else".
_WITHHELD_CONTENT: Final = "Alice is seeing a cardiologist on Friday"

#: What a *placed* record says, beside it. Every ADR-0203 §6 case seeds both, so
#: "nothing was withheld" and "everything was withheld" are told apart by the same
#: assertion rather than by two.
_SPEAKABLE_CONTENT: Final = "the user hikes on Tuesdays"


def _belief(
    record_id: str,
    content: str,
    *,
    source: MemorySource = MemorySource.OBSERVED,
    about_person: str | None = None,
    reported_by: str | None = None,
) -> SemanticMemory:
    """One belief, with exactly the three fields ADR-0199 §2 decides a class from."""
    return SemanticMemory(
        id=record_id,
        content=content,
        fact=content,
        about_person=about_person,
        provenance=Provenance(
            source=source,
            confidence=1.0 if source is MemorySource.USER_ASSERTED else 0.6,
            last_updated=_AT,
            attestation=(
                None
                if reported_by is None
                else Attestation(reported_by=reported_by, reported_at=_AT)
            ),
        ),
    )


def _supply(
    *records: MemoryRecord,
    sources: frozenset[str] = frozenset(),
) -> tuple[tuple[MemoryRecord, ...], bool]:
    """The records a channel of unbounded audience admits, and whether any was held back.

    The predicate is applied through
    :func:`~ai_assistant.orchestration.disclosure.admitted_to_understanding`, the one
    site the phases apply it at, and the boolean is ADR-0204 §2's first term over the
    records given, as the activation's capture takes it (ADR-0309 §5:10).
    """
    admitted = admitted_to_understanding(
        UnboundedAudienceSupply(speakable_attested_sources=sources), records
    )
    return admitted, len(admitted) < len(records)


# --- §3: which classes are placed as speakable -------------------------------


@pytest.mark.parametrize(
    "source", [MemorySource.USER_ASSERTED, MemorySource.OBSERVED, MemorySource.INFERRED]
)
def test_the_owners_own_beliefs_are_speakable(source: MemorySource) -> None:
    """§3's first placement, and the one milestone 19's exit test runs on.

    "That answer is made of the owner's own beliefs and the calendar, and every one
    of those is placed speakable" — a rule that passed the safety test and failed
    the exit test would be a rule nobody could ship.
    """
    record = _belief("rec-1", "the user hikes on Tuesdays", source=source)

    memories, withheld = _supply(record)

    assert withheld is False
    assert memories == (record,)


def test_a_belief_about_somebody_else_is_withheld() -> None:
    """§3: "any record whose ``MemoryBase.about_person`` is stated".

    The household clause, and it decides on its own: the person a belief is about
    is, in a household, exactly the person most likely to be in the room when it
    would be read aloud.
    """
    record = _belief("rec-1", _WITHHELD_CONTENT, about_person="Alice")

    memories, withheld = _supply(record)

    assert withheld is True
    assert memories == ()


def test_an_attested_belief_from_the_configured_calendar_is_speakable() -> None:
    """§3's second placement: ``ATTESTED`` **and** ``reported_by`` names the calendar."""
    record = _belief(
        "rec-1", "standup at 09:00", source=MemorySource.EXTERNAL, reported_by=_CALENDAR
    )

    memories, withheld = _supply(record, sources=frozenset({_CALENDAR}))

    assert withheld is False
    assert memories == (record,)


def test_an_attested_belief_from_any_other_source_is_withheld() -> None:
    """§3's fourth clause: an unplaced class is withheld until an ADR places it.

    The next source to land — a health integration, a message reader — is withheld
    on the day it merges rather than speakable by omission, which is the whole
    safety property of naming the speakable set rather than the withheld one.
    """
    record = _belief(
        "rec-1", "your test results are in", source=MemorySource.EXTERNAL, reported_by="health"
    )

    memories, withheld = _supply(record, sources=frozenset({_CALENDAR}))

    assert withheld is True
    assert memories == ()


def test_an_attested_belief_with_no_attestation_is_withheld() -> None:
    """No recorded origin, no class, and §2's third clause withholds it.

    ADR-0092 §1 makes that shape unconstructible — an ``EXTERNAL`` provenance
    without an attestation is refused at validation — so the case is reached the
    only way it can be, through ``model_construct``, which "bypasses every
    validator while still satisfying ``isinstance``" (ADR-0032 §6's own argument
    for revalidating at a seam). The placement fails closed on it rather than
    reaching for an attribute that is not there.
    """
    speakable = _belief(
        "rec-1", "standup at 09:00", source=MemorySource.EXTERNAL, reported_by=_CALENDAR
    )
    unattested = speakable.model_copy(
        update={
            "provenance": Provenance.model_construct(
                source=MemorySource.EXTERNAL, confidence=0.6, last_updated=_AT, attestation=None
            )
        }
    )

    memories, withheld = _supply(unattested, sources=frozenset({_CALENDAR}))

    assert withheld is True
    assert memories == ()


def test_no_configured_calendar_withholds_every_attested_belief() -> None:
    """The composition root's empty set, which withholds rather than guessing a name."""
    record = _belief(
        "rec-1", "standup at 09:00", source=MemorySource.EXTERNAL, reported_by=_CALENDAR
    )

    memories, withheld = _supply(record)

    assert withheld is True
    assert memories == ()


def test_a_calendar_belief_about_somebody_else_is_still_withheld() -> None:
    """§3 places it "again where ``about_person`` is not stated" — the conjunction holds."""
    record = _belief(
        "rec-1",
        _WITHHELD_CONTENT,
        source=MemorySource.EXTERNAL,
        reported_by=_CALENDAR,
        about_person="Alice",
    )

    memories, withheld = _supply(record, sources=frozenset({_CALENDAR}))

    assert withheld is True
    assert memories == ()


def test_the_placed_sources_are_the_three_the_adr_names() -> None:
    assert speakable_sources() == {
        MemorySource.USER_ASSERTED,
        MemorySource.OBSERVED,
        MemorySource.INFERRED,
    }


# --- §2: the subtraction removes members and does nothing else ---------------


def test_a_supply_with_nothing_withheld_is_handed_over_unchanged() -> None:
    """ADR-0199 §5: "The withholding subtracts from what the turn produced and adds nothing"."""
    record = _belief("rec-1", "the user hikes")

    memories, withheld = _supply(record)

    assert memories == (record,)
    assert withheld is False


def test_what_survives_keeps_the_order_it_arrived_in() -> None:
    """ADR-0203 §2: "The subtraction removes members and reorders nothing".

    ADR-0074 §5's three groups — the conversation's recent turns, then the
    relevance-retrieved beliefs, then ADR-0158's episodic supplement — reach the
    planner in that order still, which is how this corpus expresses precedence into
    a prompt. A filter that partitioned rather than filtered would pass every
    membership assertion above and silently reorder the prompt.
    """
    first = _belief("rec-1", "the user hikes")
    dropped = _belief("rec-2", _WITHHELD_CONTENT, about_person="Alice")
    third = _belief("rec-3", "the user cycles")
    supplied = (first, dropped, third)

    memories, _ = _supply(*supplied)

    assert memories == (first, third)
    assert supplied == (first, dropped, third), "the sequence it was handed is not modified"


# --- ADR-0246 §11 Arm H: reach still binds where a person listens -------------

#: The narrowing the **owner** made by their own act (ADR-0217 §3) — the placement
#: ADR-0246 §11's Arms D and H are both stated over, and the one that decision admits
#: to a search supply built for a destination the user chose.
_GUARDED: Final = Placement(
    reach=PlacementReach.OWNER, set_by=PlacementSetter.OWNER_ACT, set_at=_AT
)


def test_a_guarded_record_is_withheld_from_a_channel_wider_than_the_owner() -> None:
    """ADR-0246 §11's **Arm H**, over ``disclosure.py``'s production predicate.

    "With the same guarded record in view, the turn's **reply** on a channel whose
    audience is wider than the owner does not carry it, exactly as it does not today.
    The arm exists because §1's subtraction is the one thing a reader of this ADR might
    believe it removed."

    It did not. ADR-0246 §1's fourth clause: "**Reach keeps its full force everywhere
    this system speaks to a person.** ADR-0217 §1's denotation and §2's placement,
    ADR-0199 §3's classes, ADR-0203 §1's subtraction and ADR-0204 §2's derivation are
    untouched by every clause of this ADR, which supersedes no word of any of them. A
    record narrowed to the owner — by an act, a derivation or a proposal — stays
    withheld from every reply and every delivery whose audience is wider, exactly as it
    is today." What ADR-0246 widens is one supply built for a party that is **not a
    person**; this is the other path, and it is unmoved.

    Asserted over :func:`~ai_assistant.orchestration.disclosure.admitted_to_understanding`
    itself rather than over a restatement of it, and over all three setters, because a
    lane deleting a placement predicate in ``core`` and ``orchestration`` is one
    sed-substitution away from deleting this one too.
    """
    for placement in (
        _GUARDED,
        _NARROWED,
        Placement(reach=PlacementReach.OWNER, set_by=PlacementSetter.PROPOSED, set_at=_AT),
    ):
        guarded = _belief("rec-2", _WITHHELD_CONTENT).model_copy(update={"placement": placement})

        memories, withheld = _supply(_belief("rec-1", _SPEAKABLE_CONTENT), guarded)

        assert withheld is True, f"{placement.set_by} is still a narrowing to the owner"
        assert [one.id for one in memories] == ["rec-1"], (
            "the guarded record is subtracted before the turn plans (ADR-0203 §1)"
        )

    # And the episode is retrieved in this exact shape when it is *not* stamped —
    # `test_milestone_19s_exit_test_is_unaffected` asserts precisely that — so the
    # absence above is the withholding rather than a retrieval that found nothing.
