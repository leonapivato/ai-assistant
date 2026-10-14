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
in §9 and extended by #1517. What *is* checkable here is the shape: that the
band-carrying projections carry §3's top-level pair, that the absences §2 decides are
really absent, and that every field is additive — which is the property that lets this
PR land ahead of every consumer.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final

import pytest

if TYPE_CHECKING:
    from collections.abc import Callable

    from pydantic import BaseModel

from ai_assistant.core.types import (
    Attestation,
    Belief,
    BeliefBand,
    BeliefSummary,
    MemoryKind,
    ReportedExtent,
)

AT: Final = datetime(2026, 8, 1, 12, 0, 0, tzinfo=UTC)
REPORTED_AT: Final = datetime(2026, 7, 30, 9, 0, 0, tzinfo=UTC)

#: The two fields ADR-0189 §2 puts on each of the three band-carrying projections,
#: under one name on all three. ADR-0107 §3 is the precedent for that mattering: it
#: refused both "put the field on ``BeliefSummary`` only" and "put it on ``Belief``
#: only" one field over, because a listing row that answers less than the row it
#: links to is the same projection defective in one place.
PAIR: Final = ("attestation", "rests_on_recorded_external_content")

#: The projections that already carry ``band`` at top level, and therefore take §2's
#: two fields beside it (§3).
Projection = Belief | BeliefSummary


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


#: Each band-carrying projection beside the builder that constructs one, so every
#: assertion below is made over each rather than over ``Belief`` alone. #1517's
#: second finding is what that is for: ``BeliefSummary`` is the model a listing row
#: comes from, and a check written over ``Belief`` alone passes while the listing
#: answers less than the row it links to.
PROJECTIONS: Final[tuple[tuple[type[Projection], Callable[..., Projection]], ...]] = (
    (Belief, _belief),
    (BeliefSummary, _summary),
)


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
    """§2 puts both fields on each, spelled the same way on each.

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


# --- what makes ADR-0124 §9's second limb bite --------------------------------


@pytest.mark.parametrize(
    ("built", "members"),
    [
        pytest.param(_belief(), PAIR, id="Belief"),
        pytest.param(_summary(), PAIR, id="BeliefSummary"),
    ],
)
def test_an_absent_member_is_still_emitted_which_is_why_the_version_moves(
    built: BaseModel, members: tuple[str, ...]
) -> None:
    """ADR-0124 §9's second limb, checked rather than asserted (ADR-0189 §9).

    The bump does not rest on the fields being *populated*: ``wire.codec``'s
    ``project`` renders a model by ``model_dump()``, which **includes** a ``None``
    member rather than omitting it, and both models set ``extra="forbid"``. So a
    version 13 hub emits these members on **every** belief — populated or not — and a
    version 12 client fails ``extra_forbidden`` on them.
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
