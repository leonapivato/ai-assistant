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

The fifth is **ADR-0210 §9's nine obligations**, about *which members* of a spoken
turn's supply may set the boolean ADR-0204 §2 carries to capture and ADR-0199 §5's
third clause carries to the composing stage: the retrieved groups and the context
facets, and never the conversation's own recent turns. The cases that turn on which
relevance read returned a record are driven through
:class:`~ai_assistant.orchestration.loop.LearningLoop`, where both reads and
ADR-0158 §4's deduplication happen; the cases about what the stage is told and what
capture writes are driven through the engine.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final

import pytest

from ai_assistant.core.types import (
    Attestation,
    CalendarFacet,
    ContextFacet,
    CurrentContext,
    EmailFacet,
    EpisodicMemory,
    MemoryRecord,
    MemorySource,
    Placement,
    PlacementReach,
    PlacementSetter,
    Provenance,
    SemanticMemory,
    TimeOfDay,
)
from ai_assistant.orchestration import (
    MemoryWriteStage,
)
from ai_assistant.orchestration.disclosure import (
    UnboundedAudienceSupply,
    placed_facet_kinds,
    speakable_sources,
    supply_for_unbounded_audience,
)
from ai_assistant.orchestration.loop import LearningLoop
from ai_assistant.testing import (
    FakeContextProvider,
    FakeDeferralStore,
    FakeFeedbackProcessor,
    FakeMemoryPolicy,
    FakeMemoryStore,
    FakeMemoryWriter,
    FakePlanner,
    FakeToolRegistry,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from ai_assistant.core.types import TurnResult


def _goal_ids(prefix: str) -> Callable[[], str]:
    """Distinct identifiers, ``<prefix>-1`` first (ADR-0249 §12).

    ``save_goal`` is the opening write alone since ADR-0249 §12, so a loop wired with a
    *constant* factory would refuse its second turn: a goal per turn needs an id per
    turn, which is what production's ``uuid4`` already gives it. The first value is
    unchanged, so a single-turn case reads exactly what it read before.
    """
    count = 0

    def factory() -> str:
        nonlocal count
        count += 1
        return f"{prefix}-{count}"

    return factory


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


# --- ADR-0210 §9: what the evaluation is taken over --------------------------
# ADR-0210 §1 narrows one boolean on one channel: on a channel of unbounded
# audience ADR-0204 §2's disjunction and the fact ADR-0199 §5's third clause
# carries to the composing stage are evaluated over the members of the supply a
# relevance read taken with this turn's own goal statement returned — ADR-0074
# §5's second and third groups, named by the read and not by the group — together
# with the turn's context facets, and never over a member the supply holds only
# because it stands in the conversation's own recent turns.
#
# The **subtraction is untouched** and runs over the whole supply, first group
# included (§1's fourth clause), which is why every case below that asserts a
# boolean also asserts what the turn was supplied. What a member of the first
# group loses is the power to set a boolean.


def _ids(records: Sequence[MemoryRecord]) -> tuple[str, ...]:
    """The ids of ``records`` in order.

    Compared instead of the records themselves because the belief composition
    hands the loop ``model_copy`` results carrying a ``score`` — the same records
    at the same ids, and not the objects a test seeded.
    """
    return tuple(one.id for one in records)


def _stamped_belief(record_id: str, content: str) -> SemanticMemory:
    """§9's inherited-term fixture: a belief ADR-0199 §3 would place **speakable**.

    ``about_person`` unset and a placed ``Provenance.source``, so §3's third clause
    places it and the *first* term of ADR-0204 §2's disjunction is false of it. What
    withholds it is its own **placement** alone (ADR-0217 §2) — §5's inherited route,
    which is the term §9's third clause requires pinned separately. A fixture §3
    withholds on its own account would fire the first term and prove nothing about
    the second.
    """
    return SemanticMemory(
        id=record_id,
        content=content,
        fact=content,
        provenance=Provenance(
            source=MemorySource.OBSERVED,
            confidence=0.6,
            last_updated=_AT,
        ),
        placement=_NARROWED,
    )


def _episode(
    episode_id: str,
    content: str,
    *,
    stamped: bool = False,
    about_person: str | None = None,
) -> EpisodicMemory:
    """A captured turn, as ``orchestration.conversations`` writes one.

    ``OBSERVED``, which ``band_of`` maps to ``DERIVED`` — the band ADR-0158 §3 pins
    the episodic supplement to, and the band every episode this system writes lands
    in. ``about_person`` is the knob that makes §3 withhold it on its own account;
    ``stamped`` is the knob that narrows its **placement**, which ADR-0217 §2
    withholds while §3's third
    clause still places it speakable.
    """
    return EpisodicMemory(
        id=episode_id,
        content=content,
        occurred_at=_AT,
        about_person=about_person,
        provenance=Provenance(
            source=MemorySource.OBSERVED,
            confidence=0.6,
            last_updated=_AT,
        ),
        placement=_NARROWED if stamped else Placement(),
    )


def _spoken_loop(memory: FakeMemoryStore) -> LearningLoop:
    """A :class:`LearningLoop` over ``memory``, canonical fakes everywhere else.

    The seam ADR-0210 §10 item 1 puts the read set on is
    :data:`~ai_assistant.orchestration.loop.SupplyFilter`, between retrieval and
    planning, and the loop is where both relevance reads happen — so the cases that
    turn on *which* read returned a record are driven here rather than through the
    engine, where the store, the query and the deduplication would all be several
    stages away. The engine cases below drive the consequences: what the composing
    stage is told, and what capture writes down.
    """
    return LearningLoop(
        context=FakeContextProvider(),
        memory=memory,
        writes=MemoryWriteStage(
            writer=FakeMemoryWriter(store=memory, policy=FakeMemoryPolicy(), now=lambda: _AT),
            deferrals=FakeDeferralStore(now=lambda: _AT),
        ),
        planner=FakePlanner(now=lambda: _AT),
        feedback=FakeFeedbackProcessor(),
        now=lambda: _AT,
        id_factory=_goal_ids("goal"),
        registry=FakeToolRegistry(),
    )


async def _spoken_supply(
    memory: FakeMemoryStore, utterance: str, *, history: Sequence[MemoryRecord] = ()
) -> tuple[TurnResult, UnboundedAudienceSupply]:
    """One turn through the loop under the unbounded channel's filter.

    Returns the turn and the filter, so a case can assert both halves of §1 — what
    the turn was supplied (the subtraction, unnarrowed) and what the filter
    recorded (the evaluation, narrowed).
    """
    supply = UnboundedAudienceSupply(speakable_attested_sources=frozenset())
    turn = (await _spoken_loop(memory).respond(utterance, history=history, narrow=supply)).turn
    return turn, supply


async def _store(*records: MemoryRecord) -> FakeMemoryStore:
    memory = FakeMemoryStore(now=lambda: _AT)
    for record in records:
        await memory.add(record)
    return memory


async def test_the_inherited_term_fires_from_the_relevance_retrieved_group() -> None:
    """§9's third clause, first placement: the second term, over ADR-0074 §5's second group.

    ADR-0210 §1's third clause keeps **both** terms of ADR-0204 §2's disjunction and
    changes only the set they range over. This fixture is placed speakable by
    ADR-0199 §3's third clause on its own account, so the only thing that withholds
    it is the stamp — which is what makes this case able to fail an implementation
    that narrowed §1 by dropping the inherited route instead.
    """
    stamped = _stamped_belief("b-1", "the user hikes on Tuesdays")

    turn, supply = await _spoken_supply(await _store(stamped), "hikes")

    assert supply.withheld is True
    assert _ids(turn.memories) == (), "and it is subtracted, exactly as before"
    unstamped = _belief("b-1", "the user hikes on Tuesdays")
    _, kept, would_withhold = _supply(unstamped)
    assert (would_withhold, _ids(kept)) == (False, ("b-1",)), (
        "ADR-0199 §3 places this class speakable, so the stamp is the whole of the finding"
    )


async def test_a_record_written_before_the_field_existed_is_withheld_on_its_first_read() -> None:
    """ADR-0217 §10's decode arm, taken to the end the clause states.

    The arm is "a stored record carrying ``supplied_withheld_content: true`` and no
    placement decodes to reach ``OWNER``, setter ``DERIVED``, **and is withheld from
    an unbounded channel on the first read after the upgrade**". The type-level half
    is in ``tests/core/test_placement.py`` and the persistent-store half in
    ``tests/memory/test_sqlite_store.py``; this is the consuming half, and without it
    a build whose supply site stopped consulting the placement would satisfy both of
    those and speak aloud every record ADR-0204 had narrowed.

    The record is **decoded** from the mapping a store written under ADR-0204 holds,
    not constructed with a placement, so the decode is what puts it beyond reach.
    Its class is one ADR-0199 §3 places speakable on its own account — the same
    fixture shape as the inherited-term cases above — so the decode is the whole of
    the finding rather than §3 withholding it for a second reason.
    """
    legacy = SemanticMemory.model_validate(
        {
            "id": "b-1",
            "kind": "semantic",
            "content": "the user hikes on Tuesdays",
            "fact": "the user hikes on Tuesdays",
            "provenance": {
                "source": MemorySource.OBSERVED.value,
                "confidence": 0.6,
                "last_updated": _AT,
                "supplied_withheld_content": True,
            },
        }
    )
    assert legacy.placement == Placement(
        reach=PlacementReach.OWNER, set_by=PlacementSetter.DERIVED
    ), "the decode is the precondition; the subtraction below is the claim"

    turn, supply = await _spoken_supply(await _store(legacy), "hikes")

    assert _ids(turn.memories) == (), "withheld on the first read after the upgrade"
    assert supply.withheld is True, "and the composing stage is told (ADR-0210 §1)"
    _, kept, would_withhold = _supply(
        legacy.model_copy(update={"placement": Placement()}),
        retrieved_ids=frozenset({"b-1"}),
    )
    assert (would_withhold, _ids(kept)) == (False, ("b-1",)), (
        "ADR-0199 §3 places this class speakable, so the decoded placement is the "
        "whole of the finding"
    )


async def test_the_inherited_term_fires_from_the_episodic_supplement() -> None:
    """§9's third clause, second placement — and §9's fourth clause's second arm.

    The same fixture in ADR-0158's supplement rather than in the belief
    composition. §9 requires **both** placements because an implementation reaching
    the supplement only through the deduplication collision below would carry the
    belief composition's records and the colliding ids and nothing of an ordinary
    supplemented turn — passing every other case here and under-firing on the
    commonest supplement there is.
    """
    separator = _belief("b-1", "the user hikes on Tuesdays")
    stamped = _episode("e-1", "the user asked what they do on hikes", stamped=True)

    turn, supply = await _spoken_supply(await _store(separator, stamped), "hikes")

    assert supply.withheld is True
    assert _ids(turn.memories) == ("b-1",), "the episode was subtracted; the belief was not"
    unstamped = _episode("e-1", "the user asked what they do on hikes")
    _, kept, would_withhold = _supply(separator, unstamped)
    assert (would_withhold, _ids(kept)) == (False, ("b-1", "e-1")), (
        "an unstamped episode of this class is speakable, so the stamp is the finding"
    )


async def test_a_withheld_class_in_the_episodic_supplement_fires_the_direct_term() -> None:
    """§9's fourth clause, first arm: the supplement standing on its own, first term.

    A record ADR-0199 §3 withholds on its own account, returned by
    ``_supplement``'s own read and kept by ADR-0158 §4's deduplication because
    neither the conversation tail nor the belief composition holds it. The pair with
    the case above is what §9's fourth clause asks for: both terms, on the third
    group, separately from the collision.
    """
    separator = _belief("b-1", "the user hikes on Tuesdays")
    withheld = _episode("e-1", "the user asked about hikes with Alice", about_person="Alice")

    turn, supply = await _spoken_supply(await _store(separator, withheld), "hikes")

    assert supply.withheld is True
    assert _ids(turn.memories) == ("b-1",)


async def test_a_supplement_read_that_collides_with_the_tail_still_fires() -> None:
    """§9's eighth clause, and the reason ADR-0210 §1's second clause is stated over the reads.

    ``LearningLoop._supplement`` computes ``held = {record.id for record in
    preceding}`` and returns only what is not in it, so an episode of this
    conversation that the supplement's read **does** return is deduplicated away and
    survives at the tail's position alone. §1's second clause rules that such a
    record fires — "the supplement's read selected it for this goal, and the
    deduplication decides where one copy sits rather than why it was chosen" — so an
    implementation evaluating over the composed groups answers ``False`` here.

    The second drive is the same collision with the stamp removed, and it is what
    shows the collision is real rather than assumed: one copy of the episode, at
    index 0, the tail's position, and none in the supplement.
    """
    separator = _belief("b-1", "the user hikes on Tuesdays")
    stamped = _episode("e-1", "the user asked what they do on hikes", stamped=True)

    turn, supply = await _spoken_supply(
        await _store(separator, stamped), "hikes", history=(stamped,)
    )

    assert supply.withheld is True
    assert _ids(turn.memories) == ("b-1",)

    unstamped = _episode("e-1", "the user asked what they do on hikes")
    plain, plain_supply = await _spoken_supply(
        await _store(separator, unstamped), "hikes", history=(unstamped,)
    )
    assert _ids(plain.memories) == ("e-1", "b-1"), (
        "one copy, at the tail's position: ADR-0158 §4 deduplicated the supplement's"
    )
    assert plain_supply.withheld is False


async def test_a_tail_no_relevance_read_returned_fires_nothing() -> None:
    """§9's eighth clause's negative twin, and #1775's mechanism at the loop.

    The same stamped episode in the tail, and a supplement read that does **not**
    return it. Nothing a relevance read of this turn returned was withheld, so §1's
    evaluation is ``False`` — while the episode is still subtracted from everything
    the turn runs over. Without this twin the case above passes on an implementation
    that simply evaluated the whole supply.
    """
    separator = _belief("b-1", "the user hikes on Tuesdays")
    stamped = _episode("e-1", "the user asked about a cardiology appointment", stamped=True)

    turn, supply = await _spoken_supply(
        await _store(separator, stamped), "hikes", history=(stamped,)
    )

    assert supply.withheld is False, (
        "no relevance read of this turn returned it: ADR-0210 §1's first clause"
    )
    assert _ids(turn.memories) == ("b-1",), (
        "and it is still removed — §1's fourth clause leaves the subtraction whole"
    )
