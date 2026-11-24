"""What a permission line is, as ``core`` types it (ADR-0367 §3:1, §3:2; ADR-0376 §2).

A line names the owner's identity or anyone, exactly one capability, at most one
connection as its thing and, on a grant alone, at most one connection as its condition;
a grant has a how and a bar, a limit has neither. A connection is spelled as what an ``L``
label names, the system's own chat as one connection, and the schedule and the approvals
by none (§2:4).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Final

import pytest
from pydantic import TypeAdapter, ValidationError

from ai_assistant.core.channel_validation import APPROVALS, TASK_SCHEDULER
from ai_assistant.core.types import (
    ANYONE_GROUP_ID,
    LINE_WHO,
    OWN_CHAT_CONNECTION,
    OWNER_PERSON_ID,
    GrantHow,
    LineConnection,
    LineMaking,
    LineMakingKind,
    LineParts,
    LineRemoval,
    LineRemovalKind,
    PermissionLine,
    PermissionLineKind,
    Sureness,
)

_AT: Final = datetime(2026, 11, 24, 9, 0, tzinfo=UTC)
_CONNECTION: Final = TypeAdapter[str](LineConnection)

_GRANT: Final = LineParts(
    kind=PermissionLineKind.GRANT,
    who=ANYONE_GROUP_ID,
    action="search_memories",
    how=GrantHow.ALLOWED,
    bar=Sureness.WEAK,
)
_LIMIT: Final = LineParts(
    kind=PermissionLineKind.LIMIT,
    who=OWNER_PERSON_ID,
    action="send_email",
    thing="account:conn-mail",
)


def _line(parts: LineParts = _GRANT, /, **extra: object) -> PermissionLine:
    return PermissionLine.model_validate(
        {
            "id": "line:1",
            **parts.model_dump(),
            "made_by": OWNER_PERSON_ID,
            "made_at": _AT,
            **extra,
        }
    )


# --- anyone and who (ADR-0367 §2:3, ADR-0376 §2:1) ---------------------------------------


def test_anyone_is_a_group_spelled_apart_from_any_person() -> None:
    assert ANYONE_GROUP_ID == "group:anyone"
    assert {OWNER_PERSON_ID, ANYONE_GROUP_ID} == LINE_WHO


@pytest.mark.parametrize("who", ["person:sam", "group:flat", "anyone", " person:owner"])
def test_a_who_other_than_the_owner_or_anyone_is_refused(who: str) -> None:
    with pytest.raises(ValidationError, match="owner's identity or anyone"):
        LineParts.model_validate(_GRANT.model_dump() | {"who": who})


# --- a connection (ADR-0376 §2:4) -------------------------------------------------------


@pytest.mark.parametrize(
    "spelling",
    [
        OWN_CHAT_CONNECTION,
        "telegram:line",
        "telegram:conn-1/42",
        "account:conn-mail",
        "account:conn:with:colons",
        "informational_event:calendar",
    ],
)
def test_a_connection_is_held_as_given(spelling: str) -> None:
    assert _CONNECTION.validate_python(spelling) == spelling


@pytest.mark.parametrize(
    ("spelling", "why"),
    [
        ("", "blank"),
        ("   ", "blank"),
        ("telegram", "<kind>:<name>"),
        ("telegram:", "<kind>:<name>"),
        (":line", "<kind>:<name>"),
        ("account:", "<kind>:<name>"),
        ("telegram: line", "whitespace"),
        (" telegram:line", "whitespace"),
        ("account:conn-mail ", "whitespace"),
        ("conversation:chat-1", "never by a conversation"),
        ("task_scheduler:schedule", "schedule or the approvals"),
        ("approvals:approvals", "schedule or the approvals"),
        ("approvals", "<kind>:<name>"),
    ],
)
def test_what_a_line_may_not_name_is_refused(spelling: str, why: str) -> None:
    with pytest.raises(ValidationError, match=why):
        _CONNECTION.validate_python(spelling)


@pytest.mark.parametrize("channel_type", [TASK_SCHEDULER, APPROVALS])
def test_the_schedule_and_the_approvals_are_named_by_no_line(channel_type: str) -> None:
    """Spelled again in ``core.types``, which ``channel_validation`` imports: held equal."""
    with pytest.raises(ValidationError, match="schedule or the approvals"):
        _CONNECTION.validate_python(f"{channel_type}:{channel_type}")


# --- a grant and a limit (ADR-0367 §3:1, §3:2; ADR-0376 §2:6) ---------------------------


def test_a_grant_carries_its_how_and_its_bar() -> None:
    full = LineParts.model_validate(
        _GRANT.model_dump() | {"thing": "telegram:line", "condition": OWN_CHAT_CONNECTION}
    )

    assert (full.how, full.bar) == (GrantHow.ALLOWED, Sureness.WEAK)
    assert (full.thing, full.condition) == ("telegram:line", OWN_CHAT_CONNECTION)


@pytest.mark.parametrize("missing", ["how", "bar"])
def test_a_grant_without_its_how_or_its_bar_is_refused(missing: str) -> None:
    with pytest.raises(ValidationError, match="how it allows and its bar"):
        LineParts.model_validate(_GRANT.model_dump() | {missing: None})


@pytest.mark.parametrize(
    "extra",
    [{"how": "allowed"}, {"bar": "normal"}, {"condition": "telegram:line"}],
)
def test_a_limit_has_no_how_no_bar_and_no_condition(extra: dict[str, str]) -> None:
    with pytest.raises(ValidationError, match="no how, no bar and no condition"):
        LineParts.model_validate(_LIMIT.model_dump() | extra)


@pytest.mark.parametrize("action", ["", "   ", "\u200b"])
def test_an_action_is_a_visible_capability(action: str) -> None:
    with pytest.raises(ValidationError):
        LineParts.model_validate(_GRANT.model_dump() | {"action": action})


def test_the_kinds_and_hows_are_closed() -> None:
    assert [one.value for one in PermissionLineKind] == ["grant", "limit"]
    assert [one.value for one in GrantHow] == ["allowed", "with_approval"]
    assert [one.value for one in LineMakingKind] == ["made", "unchanged"]
    assert [one.value for one in LineRemovalKind] == ["removed", "not_standing"]


def test_the_parts_are_frozen() -> None:
    with pytest.raises(ValidationError):
        setattr(_GRANT, "bar", Sureness.NONE)  # noqa: B010  # the write under test, past the frozen type


# --- a made line (ADR-0376 §4:8) --------------------------------------------------------


def test_a_made_line_stands_and_says_its_parts() -> None:
    line = _line(_LIMIT)

    assert line.standing
    assert line.parts == _LIMIT
    assert PermissionLine.model_validate_json(line.model_dump_json()) == line


def test_a_removed_line_records_who_and_when() -> None:
    line = _line(removed_by=OWNER_PERSON_ID, removed_at=_AT + timedelta(hours=1))

    assert not line.standing
    assert line.parts == _GRANT


@pytest.mark.parametrize(
    "extra", [{"removed_by": OWNER_PERSON_ID}, {"removed_at": _AT + timedelta(hours=1)}]
)
def test_a_removal_is_recorded_whole_or_not_at_all(extra: dict[str, object]) -> None:
    with pytest.raises(ValidationError, match="both who removed it and when"):
        _line(**extra)


def test_a_made_line_is_shaped_as_its_kind() -> None:
    with pytest.raises(ValidationError, match="no how, no bar and no condition"):
        _line(_LIMIT, bar=Sureness.NORMAL)


def test_a_made_line_takes_an_aware_instant() -> None:
    with pytest.raises(ValidationError):
        _line(made_at=datetime(2026, 11, 24, 9, 0))  # noqa: DTZ001  # the naive instant under test


# --- what a making and a removal answer ---------------------------------------------------


def test_a_making_names_a_standing_line() -> None:
    removed = _line(removed_by=OWNER_PERSON_ID, removed_at=_AT)

    assert LineMaking(kind=LineMakingKind.MADE, line=_line()).line.standing
    with pytest.raises(ValidationError, match="names a line that stands"):
        LineMaking(kind=LineMakingKind.UNCHANGED, line=removed)


def test_a_removal_names_its_removed_line_exactly_when_it_removed_one() -> None:
    removed = _line(removed_by=OWNER_PERSON_ID, removed_at=_AT)

    assert LineRemoval(kind=LineRemovalKind.REMOVED, line=removed).line == removed
    assert LineRemoval(kind=LineRemovalKind.NOT_STANDING).line is None
    with pytest.raises(ValidationError, match="exactly when"):
        LineRemoval(kind=LineRemovalKind.REMOVED)
    with pytest.raises(ValidationError, match="exactly when"):
        LineRemoval(kind=LineRemovalKind.NOT_STANDING, line=removed)
    with pytest.raises(ValidationError, match="removal recorded"):
        LineRemoval(kind=LineRemovalKind.REMOVED, line=_line())
