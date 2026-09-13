"""``SqliteGoalAuthorizationStore``: the shared suites, and what only a file can say.

The durable store bound to all three of ADR-0254 §16's faces, plus the cases the
shared suites cannot state because they are about **bytes on disk** rather than
about a store's surface: the file mode, the schema marker, the objects the file
must hold, the settle-only trigger, and a row that survives a restart.

ADR-0049 §5's division is what puts them here: a clause a fake can exhibit belongs
in the shared suite, and one that is a property of *persisting a serialised payload
and rebuilding it* belongs in the implementation's own tests, where there are bytes
to seed.
"""

from __future__ import annotations

import sqlite3
import stat
from datetime import timedelta
from typing import TYPE_CHECKING

import pytest
from authorization_builders import AT, EXPIRES, GOAL, NOW, SHARED_CLOCK, TOOL
from goal_authorization_contract import GoalAuthorizationStoreContract, established

from ai_assistant.core.errors import AuthorizationError
from ai_assistant.core.types import AuthorizationDisposition
from ai_assistant.permissions.goal_authorizations import SqliteGoalAuthorizationStore
from ai_assistant.testing.goal_authorizations import authorization, coverage_member, money_bound

if TYPE_CHECKING:
    from pathlib import Path

    from ai_assistant.core.protocols import GoalAuthorizationStore


class TestSqliteGoalAuthorizationStoreContract(GoalAuthorizationStoreContract):
    """Runs the durable store through all three shared suites.

    The two narrow suites bind **this same object**, which is ADR-0254 §16's *"three
    faces, one object"* tested against the durable store rather than only against
    the fake — the half that matters, because the fake and the store could
    otherwise agree with their own suites and disagree with each other.

    **And it is what holds the two statements of ADR-0254 §1's invariants in step.**
    ``testing/`` may not import ``permissions/``, so the fake's log re-implements
    every refusal this store makes; running one suite against both is the only thing
    that stops them drifting.
    """

    @pytest.fixture(autouse=True)
    def _directory(self, tmp_path: Path) -> None:
        """Stash the directory the stores this case builds live in.

        An autouse fixture rather than a constructor argument because pytest
        instantiates the class per test and the store fixture is evaluated inside
        one — so there is no other moment at which a path could reach it.
        """
        self._tmp = tmp_path

    @pytest.fixture
    def store(self) -> GoalAuthorizationStore:
        """The durable store, over the suite's shared clock."""
        return SqliteGoalAuthorizationStore(
            path=self._tmp / "authorizations.sqlite3", now=SHARED_CLOCK.reset()
        )


class TestWhatOnlyAFileCanSay:
    """The clauses that are about bytes rather than about a store's surface."""

    @pytest.fixture
    def path(self, tmp_path: Path) -> Path:
        """Where this case's database lives."""
        return tmp_path / "authorizations.sqlite3"

    def test_the_database_is_created_owner_only(self, path: Path) -> None:
        """ADR-0004 §4, ADR-0084 §9: Tier 1 pages, and the mode is set **before** the
        first statement so a rollback journal inherits it rather than the umask."""
        store = SqliteGoalAuthorizationStore(path=path, now=SHARED_CLOCK.reset())
        try:
            assert stat.S_IMODE(path.stat().st_mode) == 0o600
        finally:
            store.close()

    async def test_a_row_survives_a_restart_in_every_disposition(self, path: Path) -> None:
        """ADR-0244's shape, arms 38 and 40: *"a restart between the question and the
        answer changes neither"*.

        **An ``ESTABLISHED`` row still carrying its ``confirmation`` is valid**,
        which is exactly why the write-path rule is the store's and not a model
        validator: a validator stating it would refuse to decode the row it had just
        written.
        """
        first = SqliteGoalAuthorizationStore(path=path, now=SHARED_CLOCK.reset())
        try:
            await first.record(authorization(id="a1"))
            await first.settle("a1", to=AuthorizationDisposition.ESTABLISHED, settled_at=NOW)
            await first.record(authorization(id="a2", confirmation="c-2"))
            await first.settle("a2", to=AuthorizationDisposition.DECLINED, settled_at=NOW)
        finally:
            first.close()
        second = SqliteGoalAuthorizationStore(path=path, now=SHARED_CLOCK.reset())
        try:
            live = await second.live_for(GOAL, TOOL.id)
            assert live is not None
            assert (live.id, live.confirmation) == ("a1", "confirm-0001")
            assert {row.id for row in await second.export()} == {"a1", "a2"}
            assert [row.id for row in await second.standing(GOAL)] == ["a1"]
        finally:
            second.close()

    async def test_the_proposal_and_its_expiry_survive_a_restart(self, path: Path) -> None:
        """Arm 40: *"recover the confirmation → the same coverage and the same
        ``expires_at``, and answering then settles that same row"*.

        Both instants are **durable before the user is shown anything**, so §11's
        prompt reads the row rather than recomputing anything (§12).
        """
        first = SqliteGoalAuthorizationStore(path=path, now=SHARED_CLOCK.reset())
        try:
            await first.record(authorization(id="a1"))
        finally:
            first.close()
        second = SqliteGoalAuthorizationStore(path=path, now=SHARED_CLOCK.reset())
        try:
            held = await second.resolve("a1")
            assert held is not None
            assert (held.proposed_at, held.expires_at) == (AT, EXPIRES)
            assert held.coverage[0].bound is not None
            assert (
                await second.settle("a1", to=AuthorizationDisposition.ESTABLISHED, settled_at=NOW)
            ).value == "settled"
        finally:
            second.close()

    def test_a_database_labelled_with_a_schema_this_code_cannot_read_is_refused(
        self, path: Path
    ) -> None:
        """ADR-0049 §1: refused **before** the table is created or read."""
        connection = sqlite3.connect(path)
        try:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            connection.execute("INSERT INTO meta(key, value) VALUES ('schema_version', '99')")
            connection.commit()
        finally:
            connection.close()
        with pytest.raises(AuthorizationError, match="schema_version=99"):
            SqliteGoalAuthorizationStore(path=path, now=SHARED_CLOCK.reset())

    def test_a_file_holding_an_object_of_that_name_that_is_not_this_stores_is_refused(
        self, path: Path
    ) -> None:
        """``CREATE TABLE IF NOT EXISTS`` is a no-op against a table already there
        under that name **whatever shape it has**.

        All four generated projections would then read as ``NULL`` — the insert
        writes only ``proposed_at_us`` and ``data`` — so every uniqueness check would
        find nothing and every pair would admit a second established row: the exact
        failure the generated columns exist to make impossible, walked around rather
        than through.
        """
        connection = sqlite3.connect(path)
        try:
            connection.execute(
                "CREATE TABLE goal_authorizations(proposed_at_us INTEGER, data TEXT)"
            )
            connection.commit()
        finally:
            connection.close()
        with pytest.raises(AuthorizationError, match="not the one this store defines"):
            SqliteGoalAuthorizationStore(path=path, now=SHARED_CLOCK.reset())

    async def test_a_settlement_moves_a_disposition_and_its_instant_and_nothing_else(
        self, path: Path
    ) -> None:
        """ADR-0254 §1: *"a settlement moves one field and its instant"*, said to
        SQLite rather than only to the reader.

        This store is **not** append-only — ``settle`` is a genuine ``UPDATE``, which
        is what makes the disposition itself the compare-and-swap token. What must
        still be impossible is an edit to the row's *substance*, because that is what
        a ruling was taken over and what
        :attr:`~ai_assistant.core.types.Authorization.subject_digest` fingerprints.
        """
        store = SqliteGoalAuthorizationStore(path=path, now=SHARED_CLOCK.reset())
        try:
            await store.record(established(id="a1"))
        finally:
            store.close()
        connection = sqlite3.connect(path)
        try:
            widened = established(
                id="a1", coverage=(coverage_member("amount", bound=money_bound("800")),)
            ).model_dump_json()
            with pytest.raises(sqlite3.IntegrityError, match="never edited"):
                connection.execute(
                    "UPDATE goal_authorizations SET data = ? WHERE id = 'a1'", (widened,)
                )
            with pytest.raises(sqlite3.IntegrityError, match="never edited"):
                connection.execute("UPDATE goal_authorizations SET proposed_at_us = 0")
        finally:
            connection.close()

    async def test_two_live_rows_planted_behind_the_stores_back_raise_rather_than_answer_none(
        self, path: Path
    ) -> None:
        """ADR-0254 §1, §16, arm 36. **A lane that answered ``None`` fails this arm.**

        *"A query that chose between two would be the composition §5 declines"*, and
        ``None`` is this seam's word for *"the store holds no live record"* — two
        rows are not none of them. §16's fault clause then takes §6's bar, so an
        integrity failure **asks** rather than authorising a request neither row
        covers.

        **Reachable only by raw SQL**, which is what *"put there behind the store's
        back"* means: ``record`` refuses the second write and ``settle`` answers
        ``WOULD_DUPLICATE``, so the state exists only where something other than this
        code wrote the file. The module docstring says why the rule is stated once,
        inside the write, rather than also as a partial unique index — the index
        would make **this** refusal untestable, and this is the refusal that matters.
        """
        store = SqliteGoalAuthorizationStore(path=path, now=SHARED_CLOCK.reset())
        try:
            await store.record(established(id="a1"))
        finally:
            store.close()
        connection = sqlite3.connect(path)
        try:
            connection.execute(
                "INSERT INTO goal_authorizations(proposed_at_us, data) VALUES (?, ?)",
                (0, established(id="a2").model_dump_json()),
            )
            connection.commit()
        finally:
            connection.close()
        reopened = SqliteGoalAuthorizationStore(path=path, now=SHARED_CLOCK.reset())
        try:
            with pytest.raises(AuthorizationError, match="live rows"):
                await reopened.live_for(GOAL, TOOL.id)
        finally:
            reopened.close()

    async def test_a_row_that_no_longer_validates_is_a_fault_and_not_a_refusal(
        self, path: Path
    ) -> None:
        """§16: *"a corrupted or downgraded database, which is a fault to report
        rather than a record to hand on"* — the **base** class, because nothing the
        caller handed in was refused."""
        store = SqliteGoalAuthorizationStore(path=path, now=SHARED_CLOCK.reset())
        try:
            await store.record(established(id="a1"))
        finally:
            store.close()
        connection = sqlite3.connect(path)
        try:
            connection.execute("DELETE FROM goal_authorizations")
            connection.execute(
                "INSERT INTO goal_authorizations(proposed_at_us, data) VALUES (?, ?)",
                (0, '{"id": "a1", "goal": "g"}'),
            )
            connection.commit()
        finally:
            connection.close()
        reopened = SqliteGoalAuthorizationStore(path=path, now=SHARED_CLOCK.reset())
        try:
            with pytest.raises(AuthorizationError, match="no longer validates"):
                await reopened.export()
        finally:
            reopened.close()

    async def test_clear_leaves_a_database_this_code_can_still_open(self, path: Path) -> None:
        """§16: the ``meta`` marker describes the file's shape rather than the user's
        history, so burning the book leaves a store that reopens."""
        store = SqliteGoalAuthorizationStore(path=path, now=SHARED_CLOCK.reset())
        try:
            await store.record(established(id="a1"))
            assert await store.clear() == 1
        finally:
            store.close()
        reopened = SqliteGoalAuthorizationStore(path=path, now=SHARED_CLOCK.reset())
        try:
            assert await reopened.export() == ()
        finally:
            reopened.close()

    async def test_an_unopenable_path_is_this_layers_error_rather_than_a_raw_builtin(
        self, tmp_path: Path
    ) -> None:
        """#238's hole, closed here rather than reproduced: a bad path is reported as
        an :class:`~ai_assistant.core.errors.AuthorizationError`."""
        with pytest.raises(AuthorizationError, match="failed to open"):
            SqliteGoalAuthorizationStore(
                path=tmp_path / "nowhere" / "authorizations.sqlite3",
                now=SHARED_CLOCK.reset(),
            )

    async def test_the_expiry_settlement_survives_the_read_that_took_it(self, path: Path) -> None:
        """§1, arm 37: an expiry is **settled** and is never inferred, so the next
        read of the file sees the settled row rather than re-deciding it."""
        store = SqliteGoalAuthorizationStore(path=path, now=SHARED_CLOCK.reset())
        try:
            await store.record(authorization(id="a1"))
            SHARED_CLOCK.set(EXPIRES + timedelta(hours=1))
            assert await store.live_for(GOAL, TOOL.id) is None
        finally:
            store.close()
        reopened = SqliteGoalAuthorizationStore(path=path, now=SHARED_CLOCK.reset())
        try:
            held = await reopened.resolve("a1")
            assert held is not None
            assert held.disposition is AuthorizationDisposition.EXPIRED
        finally:
            reopened.close()
