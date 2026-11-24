"""What the owner's four members for lines carry (ADR-0376 §4:10, §5).

``PermissionLineEntry`` is exactly a made line's entry, with its identifier and its maker,
or exactly a default line's, with its tool's id, a grant to anyone with no thing and no
condition (§3:1, §5:1); ``MakeLineResult`` carries its line exactly where it was not
refused, and its reason exactly where it was; ``RemoveLineResult`` carries the removed line
exactly where it removed one; each outcome and reason is a closed set of exactly the members
§4 names; and ``how`` and ``bar`` are refused before any I/O where they name no value.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Final

import pytest
from pydantic import ValidationError

from ai_assistant.core.types import (
    ANYONE_GROUP_ID,
    OWNER_PERSON_ID,
    GrantHow,
    MakeLineOutcome,
    MakeLineRefusal,
    MakeLineResult,
    PermissionLine,
    PermissionLineEntry,
    PermissionLineKind,
    RemoveLineOutcome,
    RemoveLineResult,
    Sureness,
    grant_bar,
    grant_how,
)

_AT: Final = datetime(2026, 11, 24, 12, 0, tzinfo=UTC)

_GRANT: Final[dict[str, Any]] = {
    "kind": PermissionLineKind.GRANT,
    "who": OWNER_PERSON_ID,
    "action": "send_text",
    "how": GrantHow.ALLOWED,
    "bar": Sureness.WEAK,
}

_LINE: Final = PermissionLine(id="line:1", made_by=OWNER_PERSON_ID, made_at=_AT, **_GRANT)


def test_the_outcomes_and_reasons_are_exactly_those_section_4_names() -> None:
    """§4:10: closed sets of exactly the members §4 names."""
    assert {one.value for one in MakeLineOutcome} == {"made", "unchanged", "refused"}
    assert [one.value for one in MakeLineRefusal] == [
        "unknown_who",
        "unknown_action",
        "no_thing",
        "unknown_connection",
    ]
    assert {one.value for one in RemoveLineOutcome} == {"removed", "not_standing"}


def test_a_made_lines_entry_carries_its_identifier_and_its_maker() -> None:
    entry = PermissionLineEntry(line_id="line:1", made_by=OWNER_PERSON_ID, **_GRANT)

    assert entry.made
    assert entry.tool_id is None


def test_a_default_lines_entry_carries_its_tools_id_and_no_identifier() -> None:
    """§3:1, §5:1: a grant to anyone, no thing, no condition, its tool's id."""
    entry = PermissionLineEntry(**{**_GRANT, "who": ANYONE_GROUP_ID}, tool_id="text")

    assert not entry.made
    assert (entry.line_id, entry.made_by) == (None, None)


@pytest.mark.parametrize(
    "fields",
    [
        {"line_id": "line:1"},
        {"made_by": OWNER_PERSON_ID},
        {},
        {"line_id": "line:1", "made_by": OWNER_PERSON_ID, "tool_id": "text"},
        {"made_by": OWNER_PERSON_ID, "tool_id": "text"},
    ],
)
def test_an_entry_is_exactly_a_made_lines_or_a_default_lines(fields: dict[str, str]) -> None:
    with pytest.raises(ValidationError):
        PermissionLineEntry.model_validate({**_GRANT, "who": ANYONE_GROUP_ID, **fields})


@pytest.mark.parametrize(
    "parts",
    [
        {"who": OWNER_PERSON_ID},
        {"thing": "conversation"},
        {"condition": "conversation"},
        {"kind": PermissionLineKind.LIMIT, "how": None, "bar": None},
    ],
)
def test_a_default_line_is_a_grant_to_anyone_with_no_thing_or_condition(
    parts: dict[str, Any],
) -> None:
    """§3:1: no default line names the owner, a thing or a condition, or says no."""
    with pytest.raises(ValidationError):
        PermissionLineEntry(**{**_GRANT, "who": ANYONE_GROUP_ID, **parts}, tool_id="text")


def test_an_entrys_parts_fit_its_kind() -> None:
    """A limit has no how, no bar and no condition (ADR-0367 §3:2)."""
    with pytest.raises(ValidationError):
        PermissionLineEntry(
            **{**_GRANT, "kind": PermissionLineKind.LIMIT},
            line_id="line:1",
            made_by=OWNER_PERSON_ID,
        )


def test_an_entry_names_no_one_but_the_owner_or_anyone() -> None:
    with pytest.raises(ValidationError):
        PermissionLineEntry(
            **{**_GRANT, "who": "person:guest"}, line_id="line:1", made_by=OWNER_PERSON_ID
        )


def test_a_making_carries_its_line_exactly_where_it_was_not_refused() -> None:
    assert MakeLineResult(outcome=MakeLineOutcome.MADE, line=_LINE).line == _LINE
    assert MakeLineResult(outcome=MakeLineOutcome.UNCHANGED, line=_LINE).line == _LINE
    refused = MakeLineResult(
        outcome=MakeLineOutcome.REFUSED, refusal=MakeLineRefusal.UNKNOWN_ACTION
    )
    assert refused.line is None
    for bad in (
        {"outcome": MakeLineOutcome.MADE},
        {"outcome": MakeLineOutcome.MADE, "line": _LINE, "refusal": MakeLineRefusal.NO_THING},
        {"outcome": MakeLineOutcome.REFUSED},
        {"outcome": MakeLineOutcome.REFUSED, "line": _LINE, "refusal": MakeLineRefusal.NO_THING},
    ):
        with pytest.raises(ValidationError):
            MakeLineResult(**bad)


def test_a_making_names_a_line_that_stands() -> None:
    removed = _LINE.model_copy(update={"removed_by": OWNER_PERSON_ID, "removed_at": _AT})

    with pytest.raises(ValidationError):
        MakeLineResult(outcome=MakeLineOutcome.MADE, line=removed)


def test_a_removal_carries_the_line_as_it_stood_exactly_where_it_removed_one() -> None:
    """§4:6: the line as it stood, standing; the store keeps its removal (§4:8)."""
    removed = PermissionLine.model_validate(
        {**_LINE.model_dump(), "removed_by": OWNER_PERSON_ID, "removed_at": _AT}
    )

    assert RemoveLineResult(outcome=RemoveLineOutcome.REMOVED, line=_LINE).line == _LINE
    assert RemoveLineResult(outcome=RemoveLineOutcome.NOT_STANDING).line is None
    for bad in (
        {"outcome": RemoveLineOutcome.REMOVED},
        {"outcome": RemoveLineOutcome.REMOVED, "line": removed},
        {"outcome": RemoveLineOutcome.NOT_STANDING, "line": _LINE},
    ):
        with pytest.raises(ValidationError):
            RemoveLineResult(**bad)


@pytest.mark.parametrize(
    ("given", "how"),
    [("allowed", GrantHow.ALLOWED), (GrantHow.WITH_APPROVAL, GrantHow.WITH_APPROVAL)],
)
def test_how_is_one_of_its_values(given: object, how: GrantHow) -> None:
    assert grant_how(given) is how


@pytest.mark.parametrize("given", ["Allowed", "", 1, None, Sureness.WEAK.value])
def test_a_how_naming_no_value_is_refused(given: object) -> None:
    with pytest.raises(ValueError, match="how"):
        grant_how(given)


@pytest.mark.parametrize(
    ("given", "bar"), [("weak", Sureness.WEAK), (Sureness.STRONG, Sureness.STRONG)]
)
def test_a_bar_is_one_of_the_four(given: object, bar: Sureness) -> None:
    assert grant_bar(given) is bar


@pytest.mark.parametrize("given", ["medium", "", 2, None, "allowed"])
def test_a_bar_naming_none_of_the_four_is_refused_by_its_own_name(given: object) -> None:
    with pytest.raises(ValueError, match="bar"):
        grant_bar(given)
