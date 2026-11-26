"""ADR-0383 §2 and §5:4: a record's home, the one function that names what a write may
carry, and the two kinds of record the memory store holds that require one."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Final

import pytest
from pydantic import ValidationError

from ai_assistant.core.types import (
    OWNER_PERSON_ID,
    EpisodicMemory,
    Memory,
    MemorySource,
    Provenance,
    RecordEnvelope,
    RecordHome,
    RecordHomeKind,
    SemanticMemory,
    WorkFor,
    WorkForKind,
    home_may_be_written,
)
from ai_assistant.testing.memories import memory

_AT: Final = datetime(2026, 11, 26, 9, 0, tzinfo=UTC)


def test_the_kinds_are_the_three_the_decision_names() -> None:
    """§2:1: person, group and shared, by these stored values."""
    assert {one.value for one in RecordHomeKind} == {"person", "group", "shared"}


def test_a_home_stores_its_kind_and_its_identifier() -> None:
    """§2:2: both are kept, and the shared things name no one."""
    assert RecordHome.owners().model_dump(mode="json") == {
        "kind": "person",
        "id": OWNER_PERSON_ID,
    }
    assert RecordHome.shared().model_dump(mode="json") == {"kind": "shared", "id": None}
    assert RecordHome.group("group:household").model_dump(mode="json") == {
        "kind": "group",
        "id": "group:household",
    }


@pytest.mark.parametrize(
    "fields",
    [
        {"kind": "shared", "id": OWNER_PERSON_ID},
        {"kind": "person"},
        {"kind": "group"},
        {"kind": "person", "id": " "},
        {"kind": "person", "id": OWNER_PERSON_ID, "for_whom": "x"},
        {"kind": "everyone"},
    ],
    ids=["shared-named", "person-unnamed", "group-unnamed", "blank", "extra", "unknown-kind"],
)
def test_a_home_that_does_not_name_whose_it_is_is_refused(fields: dict[str, object]) -> None:
    """A person's and a group's home name an id, the shared things none, and nothing else
    is let through."""
    with pytest.raises(ValidationError):
        RecordHome.model_validate(fields)


def test_whom_a_work_is_for_gives_its_home() -> None:
    """§4:1: a person's domain, a group's, and the shared things for a work for no one."""
    assert RecordHome.of_work(WorkFor.for_person(OWNER_PERSON_ID)) == RecordHome.owners()
    assert RecordHome.of_work(WorkFor.no_one()) == RecordHome.shared()
    assert RecordHome.of_work(
        WorkFor(kind=WorkForKind.GROUP, id="group:household")
    ) == RecordHome.group("group:household")


@pytest.mark.parametrize(
    ("home", "allowed"),
    [
        (RecordHome.owners(), True),
        (RecordHome.shared(), True),
        (RecordHome.person("person:sam"), False),
        (RecordHome.group("group:household"), False),
        (RecordHome.group(OWNER_PERSON_ID), False),
    ],
    ids=["owner", "shared", "another-person", "group", "group-named-like-the-owner"],
)
def test_a_write_may_carry_only_the_owners_domain_or_the_shared_things(
    home: RecordHome, *, allowed: bool
) -> None:
    """§2:3: in this milestone, the owner's domain and the shared things, a group's
    refused."""
    assert home_may_be_written(home) is allowed


def test_an_episode_and_a_memory_require_a_home() -> None:
    """§5:4: no write can leave it out."""
    provenance = Provenance(source=MemorySource.OBSERVED, confidence=0.9, last_updated=_AT)
    with pytest.raises(ValidationError, match="home"):
        EpisodicMemory.model_validate(
            {"id": "e", "content": "c", "occurred_at": _AT, "provenance": provenance}
        )
    held = memory("m", "the user is vegetarian").model_dump()
    held.pop("home")
    with pytest.raises(ValidationError, match="home"):
        Memory.model_validate(held)


def test_a_minted_record_carries_no_home() -> None:
    """ADR-0383 §3, as its 2026-11-26 note reads it: the home is the two stored kinds',
    not the envelope's, so a record no store holds has none."""
    assert "home" in EpisodicMemory.model_fields
    assert "home" in Memory.model_fields
    assert "home" not in RecordEnvelope.model_fields
    assert "home" not in SemanticMemory.model_fields
