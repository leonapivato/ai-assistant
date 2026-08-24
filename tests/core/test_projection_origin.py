"""A projection carries the origin of what it shows (ADR-0189 §1, §2, §3).

ADR-0189 §1 rules over the *class* rather than over four fields, because the corpus
had paid four times for answering this one field at a time: a user-facing projection
carries, as **structured fields**, the standing the record is held with, whether its
warrant rests on recorded external content, and — where the record is attested — what
reported it and when that source said so. §2 says what each of the four projections
gains and §3 says what shape it gains it in.

**This module pins the contract and nothing downstream.** ADR-0189 §9 fences the
contract lane to ``core/types.py``'s surface with "no producer and no surface change
in it", so nothing here asserts what ``orchestration`` populates or what a renderer
shows; those are the projection lane's and the surface lane's obligations, enumerated
in §9 and extended by #1517. What *is* checkable here is the shape: that the two
treatments §3 rules are the two the models carry, that the validator §3 puts on
``Warrant`` refuses every combination the band forecloses and nothing else, that the
absences §2 decides are really absent, and that every field is additive — which is
the property that lets this PR land ahead of every consumer.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final

import pytest
from pydantic import BaseModel, ValidationError

if TYPE_CHECKING:
    from collections.abc import Callable

from ai_assistant.core.types import (
    Attestation,
    Belief,
    BeliefBand,
    BeliefSummary,
    MemoryKind,
    Question,
    QuestionState,
    ReportedExtent,
    Retirement,
    Warrant,
)

AT: Final = datetime(2026, 8, 1, 12, 0, 0, tzinfo=UTC)
REPORTED_AT: Final = datetime(2026, 7, 30, 9, 0, 0, tzinfo=UTC)

#: The two fields ADR-0189 §2 puts on each of the three band-carrying projections,
#: under one name on all three. ADR-0107 §3 is the precedent for that mattering: it
#: refused both "put the field on ``BeliefSummary`` only" and "put it on ``Belief``
#: only" one field over, because a listing row that answers less than the row it
#: links to is the same projection defective in one place.
PAIR: Final = ("attestation", "rests_on_recorded_external_content")

#: The three projections that already carry ``band`` at top level, and therefore take
#: §2's two fields beside it rather than a nested :class:`Warrant` (§3).
Projection = Belief | BeliefSummary | Question


def _attestation(*, extent: ReportedExtent | None = None) -> Attestation:
    """One attestation: a source, the instant it spoke, and an optional extent."""
    return Attestation(reported_by="calendar", reported_at=REPORTED_AT, extent=extent)


def _belief(
    *, band: BeliefBand = BeliefBand.ATTESTED, attestation: Attestation | None = None
) -> Belief:
    """One live belief on the single-belief view."""
    return Belief(
        id="b-1",
        band=band,
        kind=MemoryKind.SEMANTIC,
        content="the standup is at 09:30",
        confidence=1.0,
        last_updated=AT,
        attestation=attestation,
    )


def _summary(
    *, band: BeliefBand = BeliefBand.ATTESTED, attestation: Attestation | None = None
) -> BeliefSummary:
    """The same belief on the listing."""
    return BeliefSummary(
        id="b-1",
        band=band,
        kind=MemoryKind.SEMANTIC,
        content="the standup is at 09:30",
        confidence=1.0,
        last_updated=AT,
        attestation=attestation,
    )


def _question(
    *, band: BeliefBand = BeliefBand.ATTESTED, attestation: Attestation | None = None
) -> Question:
    """One deferred memory decision, as the user is shown it."""
    return Question(
        id="q-1",
        state=QuestionState.OPEN,
        content="the standup is at 09:30",
        kind=MemoryKind.SEMANTIC,
        band=band,
        rationale="the calendar says so",
        reason="it contradicts what you told me",
        retires=(),
        asked_at=AT,
        expires_at=None,
        attestation=attestation,
    )


#: Each band-carrying projection beside the builder that constructs one, so every
#: assertion below is made over all three rather than over ``Belief`` alone. #1517's
#: second finding is what that is for: ``BeliefSummary`` is the model a listing row
#: comes from, and a check written over ``Belief`` alone passes while the listing
#: answers less than the row it links to.
PROJECTIONS: Final[tuple[tuple[type[Projection], Callable[..., Projection]], ...]] = (
    (Belief, _belief),
    (BeliefSummary, _summary),
    (Question, _question),
)


# --- §3's validator: everything the band determines, and only that ------------


#: Every combination of the three members, with whether :class:`Warrant` admits it.
#:
#: ADR-0189 §3 rules the whole of it: ``ATTESTED`` requires ``attestation`` set and
#: the predicate ``True``; ``ASSERTED`` requires ``attestation`` unset and the
#: predicate ``False``; ``DERIVED`` requires ``attestation`` unset and admits either
#: value of the predicate. Twelve rows rather than the four admissible ones, because
#: a validator tested only where it fires is half a rule — and because the row this
#: table exists for is ``ASSERTED``/``True``/unset, which an earlier draft of §3
#: admitted: a user's own assertion reporting that its warrant rests on recorded
#: external content, which ADR-0106 §2's predicate makes ``False`` for that band and
#: ADR-0098 §1 forbids in principle.
COMBINATIONS: Final[tuple[tuple[BeliefBand, bool, bool, bool], ...]] = (
    # band, rests_on_recorded_external_content, attestation set, admitted
    (BeliefBand.ATTESTED, True, True, True),
    (BeliefBand.ATTESTED, True, False, False),
    (BeliefBand.ATTESTED, False, True, False),
    (BeliefBand.ATTESTED, False, False, False),
    (BeliefBand.ASSERTED, False, False, True),
    (BeliefBand.ASSERTED, False, True, False),
    (BeliefBand.ASSERTED, True, False, False),
    (BeliefBand.ASSERTED, True, True, False),
    (BeliefBand.DERIVED, True, False, True),
    (BeliefBand.DERIVED, False, False, True),
    (BeliefBand.DERIVED, True, True, False),
    (BeliefBand.DERIVED, False, True, False),
)


@pytest.mark.parametrize(("band", "rests", "attested", "admitted"), COMBINATIONS)
def test_the_band_determines_the_whole_warrant(
    band: BeliefBand, rests: bool, attested: bool, admitted: bool
) -> None:
    """§3's validator reaches all three members, and refuses everything else.

    The discriminating half is as load-bearing as the refusing half: a validator
    that refused the eight would be worthless if it also refused one of the four,
    since ``DERIVED`` admitting **either** value of the predicate is the whole
    reason the field exists (#746).
    """

    def build() -> Warrant:
        return Warrant(
            band=band,
            rests_on_recorded_external_content=rests,
            attestation=_attestation() if attested else None,
        )

    if admitted:
        warrant = build()
        assert (warrant.band, warrant.rests_on_recorded_external_content) == (band, rests)
        assert (warrant.attestation is not None) is attested
        return
    with pytest.raises(ValidationError):
        build()


def test_the_four_admissible_shapes_are_the_four_the_adr_names() -> None:
    """The table above is §3's rule and not a transcription of the code.

    Read the other way round: whatever the validator does, exactly four of the
    twelve combinations may stand, and they are the ones §3 enumerates in prose.
    A validator relaxed to admit a fifth would pass every row above if the table
    were regenerated from it, and fails here.
    """
    admitted = {(band, rests, attested) for band, rests, attested, ok in COMBINATIONS if ok}
    assert admitted == {
        (BeliefBand.ATTESTED, True, True),
        (BeliefBand.ASSERTED, False, False),
        (BeliefBand.DERIVED, True, False),
        (BeliefBand.DERIVED, False, False),
    }


def test_a_warrant_is_frozen_and_forbids_extras() -> None:
    """The shape every promoted model on this surface has (ADR-0068, ADR-0085 §4).

    ``extra="forbid"`` is also what makes ADR-0124 §9's second limb bite for this
    change rather than merely apply, so it is pinned here beside the type rather
    than left to the version note in ``wire/envelope.py`` to assert.
    """
    assert Warrant.model_config.get("frozen") is True
    assert Warrant.model_config.get("extra") == "forbid"
    warrant = Warrant(band=BeliefBand.DERIVED, rests_on_recorded_external_content=True)
    with pytest.raises(ValidationError):
        warrant.band = BeliefBand.ASSERTED
    with pytest.raises(ValidationError):
        Warrant(  # type: ignore[call-arg]
            band=BeliefBand.DERIVED, rests_on_recorded_external_content=True, source="calendar"
        )


def test_a_warrant_states_the_two_facts_it_holds_only_once_each() -> None:
    """§3's third clause, from the other side: no second spelling of one fact.

    A ``Warrant`` carrying a second band-like member, or a projection that carries
    ``band`` gaining a nested one, is the failure §3 rules out — two paths to one
    fact that a careless construction can make disagree.
    """
    assert set(Warrant.model_fields) == {"band", *PAIR}
    for model, _ in PROJECTIONS:
        assert "warrant" not in model.model_fields, (
            f"{model.__name__} carries ``band`` at top level and must not also nest one"
        )
        assert "band" in model.model_fields


# --- §2's fields, on the models that gain them --------------------------------

#: ``(model, builder)`` pairs rendered under the model's own name in test ids, and
#: the models alone for the assertions that need no instance.
CASES: Final = [pytest.param(model, build, id=model.__name__) for model, build in PROJECTIONS]
MODELS: Final = [pytest.param(model, id=model.__name__) for model, _ in PROJECTIONS]


@pytest.mark.parametrize("model", MODELS)
@pytest.mark.parametrize("field", PAIR)
def test_each_band_carrying_projection_gained_the_pair_under_one_name(
    model: type[Projection], field: str
) -> None:
    """§2 puts both fields on all three, spelled the same way on each.

    The long name is the point on ``rests_on_recorded_external_content``: ADR-0106
    §2 keeps the predicate's own name so that a client cannot write half of it, and
    a shorter one would invite exactly the question the long one forecloses —
    *which* externality is this?
    """
    assert field in model.model_fields


@pytest.mark.parametrize(("model", "build"), CASES)
def test_the_pair_defaults_so_every_construction_site_still_compiles(
    model: type[Projection], build: Callable[..., Projection]
) -> None:
    """ADR-0189 §9: additive with a default, which is what lets this land first.

    The contract PR carries no producer, so every site in the tree and in every
    fixture builds these models without naming the new fields. A required field
    would make this change and its producer one change, which golden rule 5 and
    ADR-0015 forbid.
    """
    for field in PAIR:
        assert not model.model_fields[field].is_required()
    built = build()
    assert built.attestation is None
    assert built.rests_on_recorded_external_content is False


@pytest.mark.parametrize(("model", "build"), CASES)
def test_no_cross_field_validator_ties_the_attestation_to_the_band(
    model: type[Projection], build: Callable[..., Projection]
) -> None:
    """§2's stated absence, in both directions, and it is a decision not a gap.

    ``attestation`` is present exactly when the projected record's band is
    ``ATTESTED`` — which ``Provenance``'s own validator already guarantees
    upstream — and §2 declines to assert it a second time here on ADR-0086 §3's
    admissibility test: these are ratified types with construction sites in the
    tree, and a validator tying a new field to an existing one refuses
    constructions that work today. ADR-0107 §4 is the precedent for the shape of
    the answer, "No cross-field invariant is added, and the absence is the
    decision".

    ``Warrant`` gets the validator instead precisely because it is new and refuses
    nothing (ADR-0106 §7's test answered ``no``), which is the asymmetry this pins
    from the other side.
    """
    assert model.model_fields["attestation"].annotation == Attestation | None
    assert build(band=BeliefBand.ATTESTED).attestation is None
    asserted = build(band=BeliefBand.ASSERTED, attestation=_attestation())
    assert asserted.attestation is not None


@pytest.mark.parametrize(("model", "build"), CASES)
def test_the_attestation_is_projected_whole_and_carries_its_extent(
    model: type[Projection], build: Callable[..., Projection]
) -> None:
    """§2 projects the object, not two scalars beside it.

    ADR-0092 §2's half-state argument is what forces it: a source with no instant
    renders "your calendar had this as of …" with a blank, and an instant with no
    source attributes it to nobody. ``Attestation.extent`` rides along and nothing
    renders it, deliberately — splitting the object to leave one bounded optional
    value behind would mint a second, near-identical spelling of ``Attestation``.
    """
    assert model.model_fields["attestation"].annotation == Attestation | None
    extent = ReportedExtent(extends_from=REPORTED_AT, extends_until=AT)
    carried = build(attestation=_attestation(extent=extent)).attestation
    assert carried is not None
    assert (carried.reported_by, carried.reported_at) == ("calendar", REPORTED_AT)
    assert carried.extent == extent


# --- §2's ``Retirement.warrant`` ----------------------------------------------


def test_a_retirement_gained_a_warrant_that_defaults_to_absent() -> None:
    """The one projection that had no standing at all now has somewhere to put it.

    ``Retirement`` carried ``record_id`` and ``content`` and nothing else, so a
    question rendered attacker-authorable calendar text under *"Accepting would
    retire:"* with no marker at all (#673). The field is additive for §9's reason,
    like the six above it.
    """
    assert not Retirement.model_fields["warrant"].is_required()
    assert Retirement(record_id="r-1", content="the standup is at 09:00").warrant is None


def test_nothing_on_a_retirement_ties_the_warrant_to_the_content() -> None:
    """§2 makes the tie a **producer** obligation, and the absence is the decision.

    A validator asserting ``content is None ⟺ warrant is None`` would refuse, at the
    moment it landed, the ``Retirement(record_id=…, content=held.content)`` that
    ``orchestration/questions.py`` constructs today — so the contract PR §9 requires
    to carry no producer could not carry it, and a later PR adding it would be a
    second contract change for an invariant one producer already guarantees.
    ADR-0189 §2 states it, adversarial review found the ordering on that ADR's round
    1, and ADR-0107 §4 is the precedent.

    Both asymmetric shapes therefore construct. That is not an endorsement of either
    — the producer sets ``warrant`` exactly when it sets ``content`` — it is the pin
    that says this type does not enforce it, so a later reader does not mistake the
    silence for an oversight.
    """
    warrant = Warrant(band=BeliefBand.ASSERTED, rests_on_recorded_external_content=False)
    assert Retirement(record_id="r-1", content=None, warrant=warrant).content is None
    assert Retirement(record_id="r-1", content="held").warrant is None


def test_the_tombstone_shape_is_the_one_adr_0045_6_produces() -> None:
    """Both ``None`` together: the retired record no longer resolves.

    ``MemoryStore.get`` hides a closed window, so a conflict retired since the
    question was asked resolves to nothing and both facts are absent at once. §4
    rules what a surface does with it — render *no longer held*, assert nothing
    about band, origin or source, and render **no third state as ``False``** — and
    that obligation is the surface lane's. What is this lane's is that the state
    exists and is constructible.
    """
    tombstone = Retirement(record_id="r-1", content=None)
    assert (tombstone.content, tombstone.warrant) == (None, None)


# --- what makes ADR-0124 §9's second limb bite --------------------------------


@pytest.mark.parametrize(
    ("built", "members"),
    [
        pytest.param(_belief(), PAIR, id="Belief"),
        pytest.param(_summary(), PAIR, id="BeliefSummary"),
        pytest.param(_question(), PAIR, id="Question"),
        pytest.param(Retirement(record_id="r-1", content="held"), ("warrant",), id="Retirement"),
    ],
)
def test_an_absent_member_is_still_emitted_which_is_why_the_version_moves(
    built: BaseModel, members: tuple[str, ...]
) -> None:
    """ADR-0124 §9's second limb, checked rather than asserted (ADR-0189 §9).

    The bump does not rest on the fields being *populated*: ``wire.codec``'s
    ``project`` renders a model by ``model_dump()``, which **includes** a ``None``
    member rather than omitting it, and all four models set ``extra="forbid"``. So a
    version 13 hub emits these members on **every** belief, question and retirement
    — populated or not — and a version 12 client fails ``extra_forbidden`` on them.
    That is the "frame a conforming peer at the new version may send would be refused
    by a conforming peer at the old version" test, and it is ADR-0178 §6's route
    exactly.

    Checked through the real projection rather than through ``model_dump()`` alone,
    because it is the codec's rendering that reaches a peer.
    """
    from ai_assistant.wire.codec import project  # noqa: PLC0415 — asserted about, not used

    rendered = project(built)
    assert isinstance(rendered, dict)
    for member in members:
        assert member in rendered, f"{type(built).__name__} must emit {member} even when absent"
        assert rendered[member] in (None, False)


def test_the_closure_reaches_the_warrant_only_through_two_hops() -> None:
    """``Warrant`` is on the promoted surface, and reached rather than named.

    No method returns one: it arrives at a client through
    ``Question.retires -> Retirement.warrant``, which is why ADR-0085 §5's walk —
    rather than a list — is what promotes it. ``test_engine_surface_closure.py``
    asserts the walk reaches every promoted name; this states the path, so a later
    change that flattened ``Warrant`` onto ``Retirement`` would fail here naming the
    hop it removed rather than merely shrinking a set.
    """
    assert Retirement.model_fields["warrant"].annotation == Warrant | None
    assert Question.model_fields["retires"].annotation == tuple[Retirement, ...]
