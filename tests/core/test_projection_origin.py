"""A projection carries the origin of what it shows (ADR-0189 §1, ADR-0328 §15:1-§15:3).

ADR-0189 §1 rules over the *class*: a user-facing projection carries, as **structured
fields**, the standing the record is held with, whether its warrant rests on recorded
outside content, and what reported it and when. ADR-0328 §15 says what that means of a
memory: both projections carry the standing, its band and rests-on-outside-content
(§15:1), and the single view carries each support's source details whole (§15:2); no
projection carries a confidence or an elision count (§15:3).

The projections are built through ``core``'s own :func:`belief_summary` and
:func:`belief_view`, from a memory, so what is pinned is what every caller ships.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final

import pytest

from ai_assistant.core.types import (
    Attestation,
    Belief,
    BeliefBand,
    BeliefSummary,
    MemoryStanding,
    ReportedExtent,
    belief_summary,
    belief_view,
)
from ai_assistant.testing.memories import memory, memory_in_band, sourced_support

if TYPE_CHECKING:
    from pydantic import BaseModel

AT: Final = datetime(2026, 8, 1, 12, 0, 0, tzinfo=UTC)
REPORTED_AT: Final = datetime(2026, 7, 30, 9, 0, 0, tzinfo=UTC)

#: The origin fields ADR-0328 §15:1 puts on both projections, under one name on both.
ORIGIN: Final = ("standing", "band", "rests_on_outside_content")

#: What ADR-0328 §15:3 keeps off every projection of a memory, and what ADR-0189 §2's
#: pair became: the attestation moved onto each support (§15:2), and the predicate's
#: name to §7:6's.
ABSENT: Final = (
    "confidence",
    "presented_confidence",
    "evidence_elided",
    "attestation",
    "rests_on_recorded_external_content",
)


def _attestation(*, extent: ReportedExtent | None = None) -> Attestation:
    """One attestation: a source, the instant it spoke, and an optional extent."""
    return Attestation(reported_by="calendar", reported_at=REPORTED_AT, extent=extent)


@pytest.mark.parametrize("model", [Belief, BeliefSummary], ids=lambda m: m.__name__)
@pytest.mark.parametrize("field", ORIGIN)
def test_each_projection_carries_the_origin_under_one_name(
    model: type[BeliefSummary], field: str
) -> None:
    """§15:1 puts the standing, its band and rests-on-outside-content on both.

    ADR-0107 §3's precedent: a listing row that answers less than the row it links to is
    the same projection defective in one place.
    """
    assert field in model.model_fields


@pytest.mark.parametrize("model", [Belief, BeliefSummary], ids=lambda m: m.__name__)
@pytest.mark.parametrize("field", ABSENT)
def test_no_projection_carries_a_confidence_or_an_elision_count(
    model: type[BeliefSummary], field: str
) -> None:
    """§15:3: a memory carries none, and no projection invents one."""
    assert field not in model.model_fields


@pytest.mark.parametrize(
    ("band", "standing"),
    [
        (BeliefBand.ASSERTED, MemoryStanding.SAID),
        (BeliefBand.ATTESTED, MemoryStanding.SOURCE),
        (BeliefBand.DERIVED, MemoryStanding.INFERENCE),
    ],
)
def test_both_projections_carry_the_computed_standing(
    band: BeliefBand, standing: MemoryStanding
) -> None:
    """The standing is computed from the supports, once, in ``core`` (ADR-0328 §6:3)."""
    held = memory_in_band("m-1", "the standup is at 09:30", band, attestation=_attestation())
    summary = belief_summary(held, now=AT, supports_gone=False)
    view = belief_view(held, now=AT, contents={})
    assert (summary.standing, summary.band) == (standing, band)
    assert (view.standing, view.band) == (standing, band)


def test_rests_on_outside_content_is_the_computed_value_on_both() -> None:
    """§7:6 computed, never set, and the same on the listing and the single view."""
    held = memory_in_band("m-1", "the user likes jazz", BeliefBand.DERIVED, outside=True)
    assert belief_summary(held, now=AT, supports_gone=False).rests_on_outside_content
    assert belief_view(held, now=AT, contents={}).rests_on_outside_content


def test_the_single_view_projects_a_supports_source_details_whole() -> None:
    """§15:2 projects the attestation object, never two scalars beside it.

    ADR-0092 §2's half-state argument: a source with no instant renders "as of …" with a
    blank. ``Attestation.extent`` rides along and nothing renders it, deliberately.
    """
    extent = ReportedExtent(extends_from=REPORTED_AT, extends_until=AT)
    held = memory("m-1", "the standup is at 09:30", sourced_support(_attestation(extent=extent)))
    carried = belief_view(held, now=AT, contents={}).supports[0].source_details
    assert carried is not None
    assert (carried.reported_by, carried.reported_at) == ("calendar", REPORTED_AT)
    assert carried.extent == extent


def test_a_support_whose_part_is_not_resolved_is_shown_as_gone() -> None:
    """§15:7: a part absent from the resolution is gone, never shown as evidence."""
    held = memory_in_band("m-1", "the user lives in Lisbon")
    view = belief_view(held, now=AT, contents={})
    assert view.supports[0].gone
    assert view.supports_gone


# --- what makes ADR-0124 §9's second limb bite --------------------------------


@pytest.mark.parametrize(
    "built",
    [
        pytest.param(belief_view(memory_in_band("m-1", "x"), now=AT, contents={}), id="Belief"),
        pytest.param(
            belief_summary(memory_in_band("m-1", "x"), now=AT, supports_gone=False),
            id="BeliefSummary",
        ),
    ],
)
def test_an_absent_member_is_still_emitted_which_is_why_the_version_moves(
    built: BaseModel,
) -> None:
    """ADR-0124 §9's second limb, checked rather than asserted (ADR-0328 §15:8).

    ``wire.codec``'s ``project`` renders a model by ``model_dump()``, which **includes** a
    ``None`` member rather than omitting it, and both models set ``extra="forbid"``. So a
    hub emits the memory's members on every projection, populated or not, and a peer at
    the previous version fails ``extra_forbidden`` on them.
    """
    from ai_assistant.wire.codec import project  # noqa: PLC0415 — asserted about, not used

    rendered = project(built)
    assert isinstance(rendered, dict)
    for member in ("as_of", "learned", "reading_certainty", "valid_until"):
        assert member in rendered, f"{type(built).__name__} must emit {member} even when absent"
