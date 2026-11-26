"""The sight over a store's two home columns (``memory/_home_columns.py``, ADR-0383 §7:3).

The statement :func:`seen_sql` writes must answer as the predicate does over the home
:func:`stored_home` reads, on every row: a positive match on exactly what the store
writes, and every other pair, a ``NULL``, a value stored as bytes, a kind no build
writes, a blank or padded identifier, the home of no one, seen by no sight (§5:3). Proved
here over a table of odd rows, in a file of each text encoding SQLite keeps.
"""

from __future__ import annotations

import sqlite3
from typing import Final

import pytest
import structlog

from ai_assistant.core.types import OWNER_PERSON_ID, RecordHome, RecordHomeKind
from ai_assistant.memory._home_columns import count_homes, seen_sql, stored_home
from sight_equivalence import SIGHTS

#: Homes a build writes, and homes the reading accepts that no sight here sees: an
#: identifier is never normalised, so a padded or re-cased one names someone else.
_READABLE: Final[list[tuple[object, object]]] = [
    ("person", OWNER_PERSON_ID),
    ("shared", None),
    ("person", "person:someone-else"),
    ("group", "group:one"),
    ("person", f" {OWNER_PERSON_ID}"),
    ("person", f"{OWNER_PERSON_ID} "),
    ("person", OWNER_PERSON_ID.upper()),
]

#: Pairs a file altered outside the store could hold, which the reading accepts as no
#: home: the home of no one (§5:3).
_UNREADABLE: Final[list[tuple[object, object]]] = [
    (None, None),
    ("person", None),
    (None, OWNER_PERSON_ID),
    ("shared", ""),
    ("shared", "shared"),
    ("shared", OWNER_PERSON_ID),
    ("PERSON", OWNER_PERSON_ID),
    ("person ", OWNER_PERSON_ID),
    ("person", "   "),
    ("", None),
    ("domain", None),
    (b"person", OWNER_PERSON_ID.encode()),
    ("person", OWNER_PERSON_ID.encode()),
    (b"shared", None),
    ("person", 5),
    (5, None),
]

#: Every pair the cases store.
_ROWS: Final = [*_READABLE, *_UNREADABLE]


def _table(encoding: str) -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:", isolation_level=None)
    conn.execute(f"PRAGMA encoding = '{encoding}'")
    conn.execute("CREATE TABLE rows(n INTEGER PRIMARY KEY, home_kind TEXT, home_id TEXT)")
    conn.executemany(
        "INSERT INTO rows(n, home_kind, home_id) VALUES(?, ?, ?)",
        [(n, kind, home_id) for n, (kind, home_id) in enumerate(_ROWS)],
    )
    return conn


@pytest.mark.parametrize("encoding", ["UTF-8", "UTF-16le", "UTF-16be"])
@pytest.mark.parametrize("sight_name", list(SIGHTS))
def test_the_statement_answers_as_the_predicate_over_the_one_reading(
    encoding: str, sight_name: str
) -> None:
    """§7:3: selected where, and only where, the sight sees the home the columns hold."""
    sight = SIGHTS[sight_name]
    conn = _table(encoding)
    where, params = seen_sql(sight)
    selected = {n for (n,) in conn.execute(f"SELECT n FROM rows WHERE {where}", params)}  # noqa: S608 — module text; values bound
    unselected = {n for (n,) in conn.execute(f"SELECT n FROM rows WHERE NOT {where}", params)}  # noqa: S608 — module text; values bound
    stored = conn.execute("SELECT n, home_kind, home_id FROM rows").fetchall()
    expected = {n for n, kind, home_id in stored if sight.sees(stored_home(kind, home_id))}
    assert selected == expected
    # Never NULL, so the negation selects exactly the rest (§7:5's refusals read it).
    assert selected | unselected == set(range(len(_ROWS)))
    assert not selected & unselected


def test_the_one_reading_accepts_only_what_a_store_writes() -> None:
    """§2:2, §5:3: exactly the kind's text and the identifier's, nothing coerced."""
    assert stored_home("person", OWNER_PERSON_ID) == RecordHome.owners()
    assert stored_home("shared", None) == RecordHome.shared()
    assert stored_home("group", "group:one") == RecordHome.group("group:one")
    assert stored_home("person", f" {OWNER_PERSON_ID}") == RecordHome.person(f" {OWNER_PERSON_ID}")
    for kind, home_id in _UNREADABLE:
        assert stored_home(kind, home_id) is None, (kind, home_id)


def test_the_homes_the_sights_see_are_matched_exactly() -> None:
    """The owner's work matches the owner's domain and the shared things, and no more."""
    conn = _table("UTF-8")
    where, params = seen_sql(SIGHTS["owners-work"])
    rows = conn.execute(f"SELECT home_kind, home_id FROM rows WHERE {where}", params).fetchall()  # noqa: S608 — module text; values bound
    assert rows == [(RecordHomeKind.PERSON.value, OWNER_PERSON_ID), ("shared", None)]
    assert seen_sql(SIGHTS["producer-with-no-facts"]) == ("0", [])


def test_a_count_carries_numbers_and_codes_alone() -> None:
    """§11:1 to §11:3: the store's code, the member, the numbers by reason, the codes."""
    with structlog.testing.capture_logs() as events:
        count_homes(
            SIGHTS["run-over-the-owners-domain"],
            store="stories",
            member="stories",
            homes=[RecordHome.owners(), RecordHome.shared(), None],
        )
    assert events == [
        {
            "event": "sight_counted",
            "log_level": "info",
            "store": "stories",
            "member": "stories",
            "given": 3,
            "other_home": 1,
            "no_home": 1,
            "sees_nothing": 0,
            "reader": "run",
            "bounds": ["domain", "person_owner"],
        }
    ]
