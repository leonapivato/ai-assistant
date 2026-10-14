"""ADR-0199's ruling, applied at supply on the spoken channel (ADR-0200 §7, ADR-0203).

Three parts. The first is ``orchestration.disclosure`` on its own — the placement
rules of ADR-0199 §§2-3, decided from recorded origin and never from content. The
second is the engine driving them: a withheld class never reaching the composing
stage's inputs, the stage being told the audience and the bare fact of a
withholding, and nothing filtering the composed answer afterwards.

The third is **ADR-0203 §6's seven obligations**, which are about the withholding
binding the supply the *whole turn* runs over rather than the composing stage's
alone: #1692's two-turn chain, #1693's return value, the negative arm, the step
consequence §3 admits, the three degradation rules held unmoved on the withholding
route, and the bounded channel left as it was.

The fourth is **ADR-0204 §8's fifteen cases**, about what a record's warrant held.
Two of them — 4 and 9 — are restated under ADR-0210 §10 item 7 with the record
standing where §1 narrows the evaluation to, and the section's banner comment
accounts for the other thirteen one line each.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Final

import pytest

from ai_assistant.core.types import (
    Attestation,
    CalendarFacet,
    ContextFacet,
    CurrentContext,
    EmailFacet,
    MemoryRecord,
    MemorySource,
    Placement,
    PlacementReach,
    PlacementSetter,
    Provenance,
    SemanticMemory,
    TimeOfDay,
)
from ai_assistant.orchestration.disclosure import (
    placed_facet_kinds,
    speakable_sources,
    supply_for_unbounded_audience,
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


#: The situational context a case that does not care about facets is given.
_CONTEXT: Final = CurrentContext(
    now=_AT, time_of_day=TimeOfDay.AFTERNOON, is_weekend=False, within_working_hours=True
)


def _supply(
    *records: MemoryRecord,
    context: CurrentContext = _CONTEXT,
    sources: frozenset[str] = frozenset(),
    retrieved_ids: frozenset[str] | None = None,
) -> tuple[CurrentContext, tuple[MemoryRecord, ...], bool]:
    """ADR-0203 §1's subtraction, over one context and one group of records.

    The narrowing predicate is applied to what the turn assembled and retrieved
    rather than to a ``TurnResult``, because since ADR-0203 §1 there is no turn yet
    when it runs: it sits between retrieval and planning.

    ``retrieved_ids`` defaults to **every** record given, which is the reading the
    placement cases below want: ADR-0210 §1 narrows which members of a supply may
    set the boolean and changes no placement (§3), so a case about a placement puts
    its subject where a relevance read returned it. The cases that turn on the
    narrowing state the set themselves.
    """
    return supply_for_unbounded_audience(
        context,
        records,
        speakable_attested_sources=sources,
        retrieved_ids=(
            frozenset(one.id for one in records) if retrieved_ids is None else retrieved_ids
        ),
    )


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

    _, memories, withheld = _supply(record)

    assert withheld is False
    assert memories == (record,)


def test_a_belief_about_somebody_else_is_withheld() -> None:
    """§3: "any record whose ``MemoryBase.about_person`` is stated".

    The household clause, and it decides on its own: the person a belief is about
    is, in a household, exactly the person most likely to be in the room when it
    would be read aloud.
    """
    record = _belief("rec-1", _WITHHELD_CONTENT, about_person="Alice")

    _, memories, withheld = _supply(record)

    assert withheld is True
    assert memories == ()


def test_an_attested_belief_from_the_configured_calendar_is_speakable() -> None:
    """§3's second placement: ``ATTESTED`` **and** ``reported_by`` names the calendar."""
    record = _belief(
        "rec-1", "standup at 09:00", source=MemorySource.EXTERNAL, reported_by=_CALENDAR
    )

    _, memories, withheld = _supply(record, sources=frozenset({_CALENDAR}))

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

    _, memories, withheld = _supply(record, sources=frozenset({_CALENDAR}))

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

    _, memories, withheld = _supply(unattested, sources=frozenset({_CALENDAR}))

    assert withheld is True
    assert memories == ()


def test_no_configured_calendar_withholds_every_attested_belief() -> None:
    """The composition root's empty set, which withholds rather than guessing a name."""
    record = _belief(
        "rec-1", "standup at 09:00", source=MemorySource.EXTERNAL, reported_by=_CALENDAR
    )

    _, memories, withheld = _supply(record)

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

    _, memories, withheld = _supply(record, sources=frozenset({_CALENDAR}))

    assert withheld is True
    assert memories == ()


def test_the_placed_sources_are_the_three_the_adr_names() -> None:
    assert speakable_sources() == {
        MemorySource.USER_ASSERTED,
        MemorySource.OBSERVED,
        MemorySource.INFERRED,
    }


# --- §3: the two facets, and the one that has not landed ---------------------


def test_both_placed_facets_reach_the_stage() -> None:
    """§3: neither discloses anything an utterance could leak, by its own construction."""
    context = CurrentContext(
        now=_AT,
        time_of_day=TimeOfDay.AFTERNOON,
        is_weekend=False,
        within_working_hours=True,
        calendar=CalendarFacet(
            source=_CALENDAR, read_at=_AT, entries_in_progress=1, covers_until=_AT
        ),
        email=EmailFacet(source="email", read_at=_AT, arrived_in_window=2, covers_from=_AT),
    )

    narrowed, _, withheld = _supply(context=context)

    assert withheld is False
    assert narrowed is context


def test_a_facet_kind_no_adr_has_placed_is_withheld_by_construction() -> None:
    """§3's fourth clause, made structural rather than remembered.

    A facet added to :class:`~ai_assistant.core.types.CurrentContext` without a
    placement is withheld the day it lands, because the match is by **exact type**
    — a subclass of a placed facet is a different class and no ratified ADR has
    placed it.
    """

    class HealthFacet(CalendarFacet):
        """A facet nobody has placed, standing in for the next source to land."""

    context = CurrentContext(
        now=_AT,
        time_of_day=TimeOfDay.AFTERNOON,
        is_weekend=False,
        within_working_hours=True,
        calendar=HealthFacet(source="health", read_at=_AT, entries_in_progress=1, covers_until=_AT),
    )

    narrowed, _, withheld = _supply(context=context)

    assert withheld is True
    assert narrowed.calendar is None


def test_the_placed_kinds_cover_every_facet_the_context_can_hold() -> None:
    """The tripwire for a *third* facet: it fails here until an ADR places it.

    Read off :class:`~ai_assistant.core.types.CurrentContext`'s own annotations, so
    a member added there is compared against §3's list rather than silently
    withheld and never noticed.
    """
    held = {
        kind
        for name in CurrentContext.model_fields
        for kind in _facet_kinds(CurrentContext.model_fields[name].annotation)
    }
    assert held == placed_facet_kinds(), (
        "CurrentContext holds a facet kind ADR-0199 §3 has not placed; it is "
        "withheld from an unbounded channel until an ADR places it, and this "
        "assertion is where that is noticed"
    )


def _facet_kinds(annotation: object) -> set[type[ContextFacet]]:
    """Every ``ContextFacet`` subclass named inside one field annotation."""
    from typing import get_args  # noqa: PLC0415 — local to this walk

    if isinstance(annotation, type) and issubclass(annotation, ContextFacet):
        return {annotation}
    return {kind for arm in get_args(annotation) for kind in _facet_kinds(arm)}


# --- §2: the subtraction removes members and does nothing else ---------------


def test_a_supply_with_nothing_withheld_is_handed_over_unchanged() -> None:
    """ADR-0199 §5: "The withholding subtracts from what the turn produced and adds nothing".

    Identity rather than equality on the context, because a rebuilt-but-equal value
    would still be a second object the turn runs over and would hide a rebuild that
    dropped a member :class:`~ai_assistant.core.types.CurrentContext` grows later.
    """
    record = _belief("rec-1", "the user hikes")

    narrowed, memories, withheld = _supply(record)

    assert narrowed is _CONTEXT
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

    _, memories, _ = _supply(*supplied)

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
    """ADR-0246 §11's **Arm H**, over ``disclosure.py``'s production subtraction.

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

    Asserted over :func:`~ai_assistant.orchestration.disclosure.supply_for_unbounded_audience`
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

        _, memories, withheld = _supply(_belief("rec-1", _SPEAKABLE_CONTENT), guarded)

        assert withheld is True, f"{placement.set_by} is still a narrowing to the owner"
        assert [one.id for one in memories] == ["rec-1"], (
            "the guarded record is subtracted before the turn plans (ADR-0203 §1)"
        )

    # And the episode is retrieved in this exact shape when it is *not* stamped —
    # `test_milestone_19s_exit_test_is_unaffected` asserts precisely that — so the
    # absence above is the withholding rather than a retrieval that found nothing.
