"""ADR-0377 §4:1 and §8: an answer records who tapped and how sure; the panel's new outcome.

``ApprovalTap`` gains ``person`` and ``level``, each optional so an answer recorded before
them reads as §4:3 says, and ``level_read``, the level a check reads (§4:2, §4:4).
``ApprovalPanelTapAnswer`` gains ``not_answered`` (§3:4), which shows its request still
pending.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Final

import pytest
from pydantic import ValidationError

from ai_assistant.core.types import (
    OWNER_PERSON_ID,
    ApprovalCardState,
    ApprovalGiver,
    ApprovalPanelEntry,
    ApprovalPanelTap,
    ApprovalPanelTapAnswer,
    ApprovalTap,
    Sureness,
)

_AT: Final = datetime(2026, 11, 24, 12, tzinfo=UTC)
_LINE: Final = ApprovalGiver.USER_TAP_ON_TELEGRAM_CARD


@pytest.mark.parametrize("level", list(Sureness))
def test_a_tap_records_who_tapped_and_the_level_and_round_trips(level: Sureness) -> None:
    """§4:1: the person and the level §2 read, beside the surface's giver and its instant."""
    tap = ApprovalTap(who=_LINE, at=_AT, person=OWNER_PERSON_ID, level=level)

    assert ApprovalTap.model_validate_json(tap.model_dump_json()) == tap
    assert tap.model_dump(mode="json") == {
        "who": "user_tap_on_telegram_card",
        "at": "2026-11-24T12:00:00Z",
        "person": OWNER_PERSON_ID,
        "level": level.value,
    }
    assert tap.level_read is level


def test_a_tap_read_as_no_ones_is_at_none() -> None:
    """§2:1, ADR-0366 §5:6: no link names anyone, so the level is none; above it is refused."""
    assert ApprovalTap(who=_LINE, at=_AT, person=None, level=Sureness.NONE).person is None
    for level in (Sureness.WEAK, Sureness.NORMAL, Sureness.STRONG):
        with pytest.raises(ValidationError, match="no one's is at none"):
            ApprovalTap(who=_LINE, at=_AT, person=None, level=level)


def test_a_link_lowered_to_none_keeps_whom_it_names() -> None:
    """As ``InputSender`` keeps it: the record says what code found (ADR-0366 §5:6)."""
    tap = ApprovalTap(who=_LINE, at=_AT, person=OWNER_PERSON_ID, level=Sureness.NONE)

    assert (tap.person, tap.level_read) == (OWNER_PERSON_ID, Sureness.NONE)


def test_an_unrecorded_level_is_never_a_level_and_reads_as_none() -> None:
    """§4:3, §4:4: an earlier answer reads as the request's person's, its level unrecorded."""
    earlier = ApprovalTap(who=_LINE, at=_AT, person=OWNER_PERSON_ID)

    assert earlier.level is None
    assert earlier.level_read is Sureness.NONE
    assert earlier.model_dump(mode="json")["level"] is None


def test_a_tap_built_the_earlier_way_names_no_one_at_no_recorded_level() -> None:
    """Each optional: a tap built with its giver and instant alone reads as none."""
    tap = ApprovalTap(who=ApprovalGiver.USER_TAP_ON_HUB_PANEL, at=_AT)

    assert (tap.person, tap.level, tap.level_read) == (None, None, Sureness.NONE)


def test_a_tap_carries_nothing_else() -> None:
    """``extra="forbid"`` still holds: a reader at the earlier shape refuses the new fields."""
    with pytest.raises(ValidationError):
        ApprovalTap.model_validate({"who": _LINE, "at": _AT, "links_unread": True})


# --- the panel's outcome (§3:4, §8) ---------------------------------------------------------


def _entry(state: ApprovalCardState) -> ApprovalPanelEntry:
    tapped = state in {ApprovalCardState.APPROVED, ApprovalCardState.DENIED}
    return ApprovalPanelEntry(
        request_id="approval:1",
        text="Book the table.",
        state=state,
        written_at=_AT,
        expires_at=_AT + timedelta(hours=24),
        answered_by=ApprovalGiver.USER_TAP_ON_HUB_PANEL if tapped else None,
        answered_at=_AT if tapped else None,
    )


def test_the_panels_outcome_gains_not_answered_and_renames_none() -> None:
    """Closed, added to and never renamed."""
    assert [one.value for one in ApprovalPanelTapAnswer] == [
        "answered",
        "already_answered",
        "expired",
        "unknown",
        "not_answered",
    ]


def test_a_tap_that_did_not_answer_shows_its_request_still_pending() -> None:
    """§3:3, §3:4: nothing changed, and the request is shown beside the outcome."""
    shown = ApprovalPanelTap(
        answer=ApprovalPanelTapAnswer.NOT_ANSWERED, entry=_entry(ApprovalCardState.PENDING)
    )

    assert ApprovalPanelTap.model_validate_json(shown.model_dump_json()) == shown


@pytest.mark.parametrize(
    "state",
    [ApprovalCardState.APPROVED, ApprovalCardState.DENIED, ApprovalCardState.EXPIRED],
)
def test_a_tap_that_did_not_answer_shows_no_request_but_a_pending_one(
    state: ApprovalCardState,
) -> None:
    with pytest.raises(ValidationError, match="still pending"):
        ApprovalPanelTap(answer=ApprovalPanelTapAnswer.NOT_ANSWERED, entry=_entry(state))


def test_a_tap_that_did_not_answer_shows_its_request() -> None:
    """It was read as the request's person's, so the request is theirs to be shown."""
    with pytest.raises(ValidationError, match="exactly where the request is known"):
        ApprovalPanelTap(answer=ApprovalPanelTapAnswer.NOT_ANSWERED)
