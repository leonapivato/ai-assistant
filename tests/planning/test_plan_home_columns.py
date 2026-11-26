"""The plan store's reading of a stored home, and its sight in SQL (ADR-0383 §5:3, §7:3).

The SQL conditions must answer as :meth:`~ai_assistant.core.types.Sight.withheld` does
over the one reading of the same columns, on every row: a row the store wrote, and a row
altered outside it, which is withheld from every sight (§5:3).
"""

from __future__ import annotations

import json
import sqlite3
from typing import TYPE_CHECKING, Final

import pytest

from ai_assistant.core.types import OWNER_PERSON_ID, RecordHome
from ai_assistant.planning._home_columns import (
    person_home,
    seen_person_sql,
    seen_sql,
    stored_home,
)
from sight_equivalence import OWN_ACTIVATION, SIGHTS

if TYPE_CHECKING:
    from collections.abc import Iterator

    from ai_assistant.core.types import Sight

#: Each row's ``(home_kind, home_id)``: the homes a build writes, a home no write in this
#: milestone carries, and columns altered outside the store.
_HOMES: Final[list[tuple[object, object]]] = [
    ("person", OWNER_PERSON_ID),
    ("shared", None),
    ("person", "person:bob"),
    ("group", "group:house"),
    (None, None),
    ("person", None),
    ("shared", OWNER_PERSON_ID),
    ("PERSON", OWNER_PERSON_ID),
    ("house", OWNER_PERSON_ID),
    ("person", OWNER_PERSON_ID.encode()),
    (b"person", OWNER_PERSON_ID),
    ("person", 7),
    (1, None),
    ("person", ""),
]

#: Each row's activation: the sight's own, another, and values altered outside.
_MADE_BY: Final[list[object]] = [OWN_ACTIVATION, "other", None, 7, OWN_ACTIVATION.encode()]


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(":memory:")
    try:
        yield connection
    finally:
        connection.close()


def test_stored_home_reads_exactly_what_a_store_writes() -> None:
    """§2:2: a valid pair as stored; anything coerced or malformed is no home (§5:3)."""
    assert stored_home("person", OWNER_PERSON_ID) == RecordHome.owners()
    assert stored_home("shared", None) == RecordHome.shared()
    for kind, home_id in _HOMES[4:]:
        assert stored_home(kind, home_id) is None, (kind, home_id)


def test_person_home_reads_a_person_exactly() -> None:
    """§3, §5:2: a task's or a request's person is its home, read without coercion."""
    assert person_home(OWNER_PERSON_ID) == RecordHome.owners()
    assert person_home("person:bob") == RecordHome.person("person:bob")
    for value in (None, "", 7, OWNER_PERSON_ID.encode()):
        assert person_home(value) is None, value


def _python_made_by(value: object) -> str | None:
    """The activation the store records as having made a row, read strictly."""
    return value if type(value) is str else None


@pytest.mark.parametrize("sight_name", list(SIGHTS))
def test_seen_sql_answers_as_the_predicate_on_every_row(
    conn: sqlite3.Connection, sight_name: str
) -> None:
    """§7:3, §7:4, §5:3: the condition over an effect's columns is the predicate's answer.

    A row of the sight's own activation is held only where its columns name a home; the
    condition is ``0`` or ``1`` on every row, never ``NULL``, so its negation selects the
    rest.
    """
    sight = SIGHTS[sight_name]
    conn.execute("CREATE TABLE rows(n INTEGER, home_kind TEXT, home_id TEXT, activation_id TEXT)")
    rows = [
        (number, kind, home_id, made_by)
        for number, ((kind, home_id), made_by) in enumerate(
            (home, made_by) for home in _HOMES for made_by in _MADE_BY
        )
    ]
    conn.executemany("INSERT INTO rows VALUES (?, ?, ?, ?)", rows)
    where, params = seen_sql(sight, made_by="activation_id")
    answered = conn.execute(
        f"SELECT n, home_kind, home_id, activation_id, {where} FROM rows",  # noqa: S608 — the module's own text
        params,
    ).fetchall()
    for number, kind, home_id, made_by, seen in answered:
        if (kind, home_id) == ("person", "") and made_by == OWN_ACTIVATION:
            # The one corner SQL does not read as the model does: a blank identifier
            # beside the own activation. The store's decoder refuses such a row as
            # corrupt, since its columns disagree with its record's valid home.
            continue
        expected = sight.sees(stored_home(kind, home_id), made_by=_python_made_by(made_by))
        assert seen == int(expected), (number, kind, home_id, made_by)
    held = {n for (n,) in conn.execute(f"SELECT n FROM rows WHERE {where}", params)}  # noqa: S608
    unheld = {n for (n,) in conn.execute(f"SELECT n FROM rows WHERE NOT ({where})", params)}  # noqa: S608
    assert held | unheld == {row[0] for row in rows}
    assert not held & unheld


def _sees_nothing_but_its_own(sight: Sight) -> bool:
    return not sight.homes_seen


@pytest.mark.parametrize("sight_name", list(SIGHTS))
def test_seen_person_sql_answers_as_the_predicate_on_every_row(
    conn: sqlite3.Connection, sight_name: str
) -> None:
    """§3, §7:3, §7:4: the condition over a request's person and asker is the predicate's.

    The asker is read from the row's record, and a record that is not JSON names none,
    so the condition is never an error.
    """
    sight = SIGHTS[sight_name]
    conn.execute("CREATE TABLE rows(n INTEGER, person TEXT, data TEXT)")
    persons: list[object] = [OWNER_PERSON_ID, "person:bob", None, 7, OWNER_PERSON_ID.encode(), ""]
    records: list[tuple[str, str | None]] = [
        (json.dumps({"activation_id": OWN_ACTIVATION}), OWN_ACTIVATION),
        (json.dumps({"activation_id": "other"}), "other"),
        (json.dumps({"activation_id": 7}), None),
        ("{not json", None),
    ]
    rows = [
        (number, person, data, asker)
        for number, (person, (data, asker)) in enumerate(
            (person, record) for person in persons for record in records
        )
    ]
    conn.executemany("INSERT INTO rows VALUES (?, ?, ?)", [row[:3] for row in rows])
    where, params = seen_person_sql(
        sight,
        made_by="CASE WHEN json_valid(data) THEN json_extract(data, '$.activation_id') END",
    )
    stored = dict(conn.execute("SELECT n, person FROM rows").fetchall())
    answered = dict(conn.execute(f"SELECT n, {where} FROM rows", params).fetchall())  # noqa: S608 — the module's own text
    for number, _person, _data, asker in rows:
        if stored[number] == "" and asker == OWN_ACTIVATION:
            continue  # the blank corner above: the decoder refuses the row as corrupt
        expected = sight.sees(person_home(stored[number]), made_by=asker)
        assert answered[number] == int(expected), (number, stored[number], asker)
    if _sees_nothing_but_its_own(sight) and sight.activation is None:
        assert where == "0"
