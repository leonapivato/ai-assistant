"""Every database the composition root opens is closed by the façade's shutdown.

A hand-written case per store is the shape this invariant kept failing in. Three of
them exist — the transcript archive's (#1902) and the two #1903 adds beside it — and
each was written *after* a store had already shipped with its ``close`` on the
build-failure cleanup list and absent from ``Engine(closers=…)``, so a build that
**failed** closed it and one that **succeeded** never did. The next store to be
added will not be caught by a case that names the last one, which is what the issue
asks for in as many words: "a sweep over *every* opened store, rather than three
hand-written cases, would keep the fourteenth from repeating it".

**So the roster is discovered rather than declared.** ``sqlite_census`` records
every ``sqlite3.connect`` the build performs, and the assertion is that none of the
connections is still usable once ``Engine.aclose`` has returned. A fifteenth store
wired without a closer fails this test on the day it is added, naming its own
database file, and no list here has to be kept in step for that to happen.

Three anti-vacuity guards sit beside it, because a census that silently stopped seeing
anything would pass every assertion it makes: the census is non-empty, every ``*.db``
file the build leaves in the data directory appears in it, and something in it was
open before the shutdown ran. So a store reaching SQLite by some route other than
``sqlite3.connect`` shows up as a file nobody watched, rather than as a test that
quietly stopped testing.

The subject is the *connection*, which is what ADR-0042 §2 and ADR-0083 §4 are about
at this layer: a closer list is a statement about wiring, and a connection left open
past shutdown leaves a ``-wal`` beside a Tier 1 database holding its pages.

Refs: ADR-0042 §2; ADR-0083 §4; #1903.
"""

from __future__ import annotations

from pathlib import Path

from ai_assistant.app.composition import build_engine
from ai_assistant.core.config import EmbedderKind, Settings
from sqlite_census import connection_census, is_open


async def test_every_database_the_build_opens_is_closed_by_the_engines_shutdown(
    tmp_path: Path,
) -> None:
    """ADR-0042 §2's ordered shutdown, held against the roster the build actually opens.

    "On success, their ``close`` methods are handed to the façade as its ordered
    shutdown path" is what :func:`build_composition`'s own docstring promises, and it
    was untrue of three stores in turn. This is that sentence as an assertion over
    whatever the build opens today.

    Both directions are asserted, because only the pair is evidence: the connections
    are open *before* ``aclose`` — otherwise a build that opened nothing would satisfy
    the second half — and none of them is open after it.
    """
    with connection_census() as recorded:
        engine = build_engine(Settings(embedder=EmbedderKind.HASHING), data_dir=tmp_path)

    assert recorded, "the census saw no connection at all, so nothing below is evidence"
    # The directory listing is a synchronous read of a temporary directory this test
    # owns, not an I/O path the event loop can be starved by.
    on_disk = {path.name for path in tmp_path.glob("*.db")}  # noqa: ASYNC240
    watched = {Path(database).name for database, _ in recorded}
    assert on_disk <= watched, (
        f"the build left {sorted(on_disk - watched)} in the data directory without the "
        f"census seeing it opened; a store reaching SQLite by another route is outside "
        f"what this test can guard"
    )
    open_before = sorted(name for name, connection in recorded if is_open(connection))
    assert open_before, "the build closed everything it opened, so the sweep below is vacuous"

    await engine.aclose()

    open_after = sorted(name for name, connection in recorded if is_open(connection))
    assert open_after == [], (
        f"{[Path(name).name for name in open_after]} survived `Engine.aclose()` "
        f"with a live connection: every store this root opens joins the ordered shutdown "
        f"(ADR-0042 §2, ADR-0083 §4), and one registered only on the build-failure "
        f"cleanup list is closed when the build *fails* and never when it succeeds (#1903)"
    )
