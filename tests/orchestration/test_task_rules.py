"""Local times, the person's zone and a rule's arithmetic (ADR-0340 §3, §4, §9:5).

The one function that computes a rule's instants, read in the zone a rule is computed in,
and the local-time reading a spawn's instant and a rule's occurrences share, each
checked against instants worked out by hand.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from typing import Final
from zoneinfo import ZoneInfo

import pytest

from ai_assistant.core.errors import PersonModelStoreError
from ai_assistant.core.types import (
    OWNER_PERSON_ID,
    DueOnRule,
    PersonActHow,
    PersonModelAct,
    ProfileField,
    RuleDay,
    TaskRuleKind,
)
from ai_assistant.orchestration.task_rules import (
    PersonZones,
    computed_elsewhere,
    first_occurrence,
    local_instant,
    next_occurrence,
    rule_push,
    rule_text,
    successor,
)
from ai_assistant.testing.person_model import FakePersonModelStore

NEW_YORK = ZoneInfo("America/New_York")
LOS_ANGELES = ZoneInfo("America/Los_Angeles")
TOKYO = ZoneInfo("Asia/Tokyo")
UTC_ZONE = ZoneInfo("UTC")

#: Friday 23 October 2026, noon in New York.
FRIDAY_NOON = datetime(2026, 10, 23, 16, 0, tzinfo=UTC)


def _rule(repeats: TaskRuleKind, at: time = time(7, 0), **parts: object) -> DueOnRule:
    return DueOnRule(repeats=repeats, time_of_day=at, **parts)  # type: ignore[arg-type]  # each part is the field's own


# --- local times (§3:2-§3:4) -------------------------------------------------------------


def _wall(text: str) -> datetime:
    """A local date and time with no offset, as a spawn states one."""
    return datetime.fromisoformat(text)


def test_a_local_time_that_exists_once_is_that_instant() -> None:
    assert local_instant(_wall("2026-10-25T20:00"), NEW_YORK) == datetime(
        2026, 10, 26, 0, 0, tzinfo=UTC
    )


def test_a_local_time_in_a_daylight_saving_gap_is_the_first_instant_after_it() -> None:
    """§3:4: 02:30 on 8 March 2026 never shows in New York; 03:00 EDT is the first after."""
    assert local_instant(_wall("2026-03-08T02:30"), NEW_YORK) == datetime(
        2026, 3, 8, 7, 0, tzinfo=UTC
    )


@pytest.mark.parametrize(
    "wall", ["2027-03-14T02:00:00.100000", "2027-03-14T02:59:59.999999", "2027-03-14T02:00:01"]
)
def test_a_fraction_of_a_second_inside_a_gap_resolves_to_the_change(wall: str) -> None:
    """§3:4: the search narrows in whole seconds, so it ends wherever the gap is entered."""
    assert local_instant(_wall(wall), NEW_YORK) == datetime(2027, 3, 14, 7, 0, tzinfo=UTC)


def test_a_local_time_a_daylight_saving_change_repeats_is_the_earlier() -> None:
    """§3:4: 01:30 on 1 November 2026 shows twice in New York; fold=0 is EDT's."""
    assert local_instant(_wall("2026-11-01T01:30"), NEW_YORK) == datetime(
        2026, 11, 1, 5, 30, tzinfo=UTC
    )


# --- the rule's arithmetic (§4:5-§4:9) ---------------------------------------------------


def test_a_weekdays_rule_across_a_weekend_falls_next_on_monday() -> None:
    """§10:4: Friday's 07:00 is followed by Monday's, never Saturday's or Sunday's."""
    rule = _rule(TaskRuleKind.WEEKDAYS)
    friday = datetime(2026, 10, 23, 11, 0, tzinfo=UTC)  # 07:00 EDT

    assert successor(rule, friday, NEW_YORK) == datetime(2026, 10, 26, 11, 0, tzinfo=UTC)
    # Set on the Friday after its 07:00, the first is Monday's too.
    assert first_occurrence(rule, NEW_YORK, now=FRIDAY_NOON) == datetime(
        2026, 10, 26, 11, 0, tzinfo=UTC
    )


def test_a_weekly_rule_on_two_days_alternates_between_them() -> None:
    """§10:4: Monday and Thursday at 18:30, in the order of the week."""
    rule = _rule(TaskRuleKind.WEEKLY, time(18, 30), days=(RuleDay.THURSDAY, RuleDay.MONDAY))
    first = first_occurrence(rule, NEW_YORK, now=FRIDAY_NOON)
    assert first == datetime(2026, 10, 26, 22, 30, tzinfo=UTC)  # Monday 18:30 EDT
    second = successor(rule, first, NEW_YORK)
    assert second == datetime(2026, 10, 29, 22, 30, tzinfo=UTC)  # Thursday
    assert successor(rule, second, NEW_YORK) == datetime(2026, 11, 2, 23, 30, tzinfo=UTC)  # EST


def test_an_until_on_which_the_last_occurrence_falls_ends_the_rule_after_it() -> None:
    """§4:7, §10:4: the occurrence on the until falls; none follows it."""
    rule = _rule(TaskRuleKind.DAILY, until_date=date(2026, 10, 25))
    last = datetime(2026, 10, 25, 11, 0, tzinfo=UTC)

    assert successor(rule, datetime(2026, 10, 24, 11, 0, tzinfo=UTC), NEW_YORK) == last
    assert successor(rule, last, NEW_YORK) is None


def test_a_rules_first_occurrence_is_later_than_now_and_on_or_after_its_from() -> None:
    """§4:5: a from that has passed constrains nothing; one ahead holds back the first."""
    passed = _rule(TaskRuleKind.DAILY, time(20, 0), from_date=date(2026, 1, 1))
    ahead = _rule(TaskRuleKind.DAILY, time(20, 0), from_date=date(2026, 10, 27))

    assert first_occurrence(passed, NEW_YORK, now=FRIDAY_NOON) == datetime(
        2026, 10, 24, 0, 0, tzinfo=UTC
    )
    assert first_occurrence(ahead, NEW_YORK, now=FRIDAY_NOON) == datetime(
        2026, 10, 28, 0, 0, tzinfo=UTC
    )


def test_a_rule_whose_until_has_passed_yields_no_first_occurrence() -> None:
    """§4:4: the spawn refuses it, so the arithmetic answers none."""
    rule = _rule(TaskRuleKind.DAILY, until_date=date(2026, 10, 22))

    assert first_occurrence(rule, NEW_YORK, now=FRIDAY_NOON) is None


def test_a_skip_is_a_from_on_the_day_after_the_skipped_occurrence() -> None:
    """§5:1: the replace's rule, from the day after, first falls that day."""
    skipped = datetime(2026, 10, 24, 0, 0, tzinfo=UTC)  # Friday 20:00 EDT
    rule = _rule(TaskRuleKind.DAILY, time(20, 0), from_date=date(2026, 10, 24))

    first = first_occurrence(rule, NEW_YORK, now=FRIDAY_NOON)
    assert first is not None
    assert first > skipped
    assert first == datetime(2026, 10, 25, 0, 0, tzinfo=UTC)


def test_a_rules_occurrence_in_a_daylight_saving_gap_and_a_repeat() -> None:
    """§4:9, §10:4: a rule's local time reads as a one-off's does, in each change."""
    gap = _rule(TaskRuleKind.DAILY, time(2, 30))
    repeat = _rule(TaskRuleKind.DAILY, time(1, 30))

    assert successor(gap, datetime(2026, 3, 7, 7, 30, tzinfo=UTC), NEW_YORK) == datetime(
        2026, 3, 8, 7, 0, tzinfo=UTC
    )
    assert successor(repeat, datetime(2026, 10, 31, 5, 30, tzinfo=UTC), NEW_YORK) == datetime(
        2026, 11, 1, 5, 30, tzinfo=UTC
    )


def test_the_persons_zone_changed_while_pending_keeps_it_and_computes_the_next_anew() -> None:
    """§4:3, §10:4: Monday's 08:00 in New York, then Tuesday's 08:00 in Los Angeles."""
    rule = _rule(TaskRuleKind.DAILY, time(8, 0))
    monday_in_new_york = datetime(2026, 10, 26, 12, 0, tzinfo=UTC)

    pushed = rule_push(rule, monday_in_new_york, LOS_ANGELES, now=monday_in_new_york)

    assert pushed.latest is None
    assert pushed.successor == datetime(2026, 10, 27, 15, 0, tzinfo=UTC)


def test_a_rule_missed_for_three_days_pushes_its_latest_and_skips_two() -> None:
    """§4:8, §10:4: the pending one and the next are skipped; the third is pushed."""
    rule = _rule(TaskRuleKind.DAILY, time(8, 0))
    pending = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)
    now = datetime(2026, 10, 26, 13, 0, tzinfo=UTC)

    pushed = rule_push(rule, pending, NEW_YORK, now=now)

    assert pushed.skipped == (datetime(2026, 10, 25, 12, 0, tzinfo=UTC),)
    assert pushed.latest == datetime(2026, 10, 26, 12, 0, tzinfo=UTC)
    assert pushed.successor == datetime(2026, 10, 27, 12, 0, tzinfo=UTC)


def test_a_pending_occurrence_due_under_the_old_zone_is_still_pushed() -> None:
    """§4:8, §10:4: found after the person moved, its stored instant is pushed itself."""
    rule = _rule(TaskRuleKind.DAILY, time(8, 0))
    in_new_york = datetime(2026, 10, 26, 12, 0, tzinfo=UTC)

    pushed = rule_push(rule, in_new_york, TOKYO, now=in_new_york)

    assert pushed.latest is None
    assert pushed.skipped == ()
    assert pushed.successor is not None
    assert pushed.successor > in_new_york


def test_a_missed_rules_latest_on_its_until_writes_no_successor() -> None:
    rule = _rule(TaskRuleKind.DAILY, time(8, 0), until_date=date(2026, 10, 25))

    pushed = rule_push(
        rule,
        datetime(2026, 10, 24, 12, 0, tzinfo=UTC),
        NEW_YORK,
        now=datetime(2026, 10, 26, 0, 0, tzinfo=UTC),
    )

    assert pushed.latest == datetime(2026, 10, 25, 12, 0, tzinfo=UTC)
    assert pushed.successor is None


def test_next_occurrence_is_the_one_computation_from_a_local_date() -> None:
    rule = _rule(TaskRuleKind.WEEKLY, days=(RuleDay.SUNDAY,))

    assert next_occurrence(rule, UTC_ZONE, on_or_after=date(2026, 10, 19)) == datetime(
        2026, 10, 25, 7, 0, tzinfo=UTC
    )


# --- the rule in words (§6:2, §8:2) ------------------------------------------------------

#: How a rule naming no zone is said: with the person's zone it follows (§4:3, #3451).
_FOLLOWS: Final = " in the person's zone, which it follows (now Europe/Lisbon)"


@pytest.mark.parametrize(
    ("rule", "said"),
    [
        (
            _rule(TaskRuleKind.DAILY, time(20, 0)),
            f"every day at 8:00 PM{_FOLLOWS}",
        ),
        (
            _rule(TaskRuleKind.WEEKDAYS),
            f"every weekday at 7:00 AM{_FOLLOWS}",
        ),
        (
            _rule(TaskRuleKind.WEEKLY, time(12, 5), days=(RuleDay.MONDAY, RuleDay.THURSDAY)),
            f"every Monday and Thursday at 12:05 PM{_FOLLOWS}",
        ),
        (
            _rule(TaskRuleKind.WEEKDAYS, time(9, 30), zone="America/New_York"),
            "every weekday at 9:30 AM America/New_York time",
        ),
        (
            _rule(
                TaskRuleKind.DAILY,
                time(20, 0),
                from_date=date(2026, 10, 29),
                until_date=date(2027, 1, 2),
            ),
            (
                f"every day at 8:00 PM{_FOLLOWS}, from Thursday 29 October, "
                "until Saturday 2 January 2027"
            ),
        ),
        (
            _rule(TaskRuleKind.DAILY, time(0, 0), from_date=date(2026, 1, 1)),
            f"every day at 12:00 AM{_FOLLOWS}",
        ),
    ],
)
def test_a_rule_in_words_with_its_zone_from_and_until(rule: DueOnRule, said: str) -> None:
    assert rule_text(rule, today=date(2026, 10, 25), zone=ZoneInfo("Europe/Lisbon")) == said


def test_an_occurrence_computed_under_an_earlier_zone_is_found_and_one_computed_now_is_not() -> (
    None
):
    """§4:3, #3451: Lisbon's 4:34 AM, read after a move to Los Angeles, is not LA's."""
    rule = _rule(TaskRuleKind.DAILY, time(4, 34))
    lisbon = ZoneInfo("Europe/Lisbon")
    in_lisbon = next_occurrence(rule, lisbon, on_or_after=date(2026, 10, 27))
    in_los_angeles = next_occurrence(rule, LOS_ANGELES, on_or_after=date(2026, 10, 27))
    assert in_lisbon is not None
    assert in_los_angeles is not None

    assert computed_elsewhere(rule, in_lisbon, LOS_ANGELES)
    assert not computed_elsewhere(rule, in_los_angeles, LOS_ANGELES)
    assert not computed_elsewhere(rule, in_lisbon, lisbon)
    # A rule naming its zone is computed in it, whatever the person's zone.
    named = _rule(TaskRuleKind.DAILY, time(4, 34), zone="Europe/Lisbon")
    assert not computed_elsewhere(named, in_lisbon, LOS_ANGELES)


def test_an_occurrence_a_daylight_saving_gap_moved_is_not_taken_for_another_zones() -> None:
    """§3:4, §4:9: 2:30 AM on the night the clocks skip resolves to the change itself."""
    rule = _rule(TaskRuleKind.DAILY, time(2, 30))
    moved = next_occurrence(rule, NEW_YORK, on_or_after=date(2026, 3, 8))
    assert moved is not None
    assert moved.astimezone(NEW_YORK).time() == time(3, 0)

    assert not computed_elsewhere(rule, moved, NEW_YORK)


def test_a_weekly_occurrence_landing_on_another_day_in_the_new_zone_is_found() -> None:
    """§4:3: Tuesday's 1:00 AM in Lisbon is Monday evening in Los Angeles."""
    rule = _rule(TaskRuleKind.WEEKLY, time(1, 0), days=(RuleDay.TUESDAY,))
    due = next_occurrence(rule, ZoneInfo("Europe/Lisbon"), on_or_after=date(2026, 10, 26))
    assert due is not None

    assert computed_elsewhere(rule, due, LOS_ANGELES)


# --- the person's zone (§3:3, ADR-0338 §3:6) ---------------------------------------------


async def _people(zone: str | None) -> FakePersonModelStore:
    people = FakePersonModelStore(now=lambda: FRIDAY_NOON)
    if zone is not None:
        await people.set_field(
            OWNER_PERSON_ID,
            ProfileField.TIME_ZONE,
            zone,
            act=PersonModelAct(how=PersonActHow.PANEL, by=OWNER_PERSON_ID),
        )
    return people


async def test_the_persons_zone_is_their_profiles_and_the_hubs_where_it_sets_none() -> None:
    assert (
        await PersonZones(default=UTC_ZONE, people=await _people("Asia/Tokyo")).of(OWNER_PERSON_ID)
        == TOKYO
    )
    assert (
        await PersonZones(default=UTC_ZONE, people=await _people(None)).of(OWNER_PERSON_ID)
        == UTC_ZONE
    )
    assert await PersonZones(default=UTC_ZONE).of(OWNER_PERSON_ID) == UTC_ZONE


async def test_a_person_model_that_cannot_be_read_guesses_no_zone() -> None:
    """§3:3: a fault is no answer that the profile sets none, so the read raises."""
    people = await _people("Asia/Tokyo")
    people.fail_next()
    zones = PersonZones(default=UTC_ZONE, people=people)

    with pytest.raises(PersonModelStoreError):
        await zones.of(OWNER_PERSON_ID)
    # The next read, the store back, is the profile's.
    assert await zones.of(OWNER_PERSON_ID) == TOKYO
