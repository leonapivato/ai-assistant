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

import contextlib
import sqlite3
import stat
import threading
from datetime import timedelta
from typing import TYPE_CHECKING, Final

import pytest
from authorization_builders import AT, EXPIRES, GOAL, NOW, SHARED_CLOCK, TOOL, MovableClock
from goal_authorization_contract import (
    OTHER_TOOL,
    GoalAuthorizationStoreContract,
    established,
)

from ai_assistant.core.errors import AuthorizationError
from ai_assistant.core.types import AuthorizationDisposition, BoundKind
from ai_assistant.permissions.goal_authorizations import SqliteGoalAuthorizationStore
from ai_assistant.testing.cancellation import (
    ResourceLog,
    SuspendedMidWrite,
    ThreadSuspension,
)
from ai_assistant.testing.goal_authorizations import authorization, coverage_member, money_bound

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path

    from ai_assistant.core.protocols import GoalAuthorizationStore
    from ai_assistant.testing.cancellation import SuspendedCall


#: Where each of ADR-0268 §1's two members does its SQL. Named rather than derived,
#: because a lever that guessed the attribute would silently suspend nothing and the
#: cancellation case would certify a store it never held open.
_ENDING_SYNC_METHODS: Final[dict[str, str]] = {
    "end_for_goal": "_end_for_goal_sync",
    "clear_closure": "_clear_closure_sync",
}


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

    @contextlib.asynccontextmanager
    async def store_suspended_mid_write(
        self,
    ) -> AsyncIterator[SuspendedMidWrite[GoalAuthorizationStore]]:
        """Park a named member's worker thread inside the connection's turn.

        ``arm(member)`` wraps the private method that member does its SQL in
        (:data:`_ENDING_SYNC_METHODS`) — inside ``async with self._lock`` and inside
        the worker the event loop cannot interrupt, which is exactly where ADR-0054's
        bug lived — so the first worker to reach it blocks and every later one runs
        free. Blocking there is what makes the case deterministic: left to run, a
        commit finishes in microseconds and whether the second caller arrives while
        the worker still holds the connection would be a race.

        **Its own store on its own connection**, not the ``store`` fixture's: the
        suspended worker is parked for the length of the case, and sharing would make
        an unrelated failure hang instead of fail.
        """
        store = SqliteGoalAuthorizationStore(
            path=self._tmp / "suspended.sqlite3", now=SHARED_CLOCK.reset()
        )
        log = ResourceLog()
        suspension = ThreadSuspension()

        def arm(member: str) -> SuspendedCall:
            attribute = _ENDING_SYNC_METHODS[member]
            original = getattr(store, attribute)
            armed = threading.Event()

            def blocking(*args: object) -> object:
                with log.inside():  # the span the connection is genuinely in use for
                    if not armed.is_set():  # the first worker only; later ones run free
                        armed.set()
                        suspension.hold()
                    return original(*args)

            setattr(store, attribute, blocking)
            return suspension

        try:
            yield SuspendedMidWrite(store=store, log=log, arm=arm)
        finally:
            # An implementation that released the connection early leaves a worker
            # parked here; releasing unconditionally is what turns that into a
            # failure rather than a hang.
            suspension.release()
            store.close()


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

    @staticmethod
    def _made_version_one(path: Path) -> None:
        """Turn a file this code wrote into the one version 1 would have written.

        A version-1 database is not something this code can produce any more, and
        writing one out by hand would be a second statement of the old shape free to
        drift from the real one. So the current store writes the file and the two
        differences ADR-0268 §9's migration is *"the whole of it"* are undone: the
        closure-record storage goes, and the marker goes back to ``1``. Every row is
        left exactly as it was, which is what the arm is about.
        """
        connection = sqlite3.connect(path)
        try:
            connection.execute("DROP TABLE goal_authorization_closures")
            connection.execute("UPDATE meta SET value = '1' WHERE key = 'schema_version'")
            connection.commit()
        finally:
            connection.close()

    @staticmethod
    def _marker_and_tables(path: Path) -> tuple[str, set[str]]:
        """The file's ``schema_version`` and the names of the tables it holds."""
        connection = sqlite3.connect(path)
        try:
            marker = str(
                connection.execute(
                    "SELECT value FROM meta WHERE key = 'schema_version'"
                ).fetchone()[0]
            )
            names = {
                str(row[0])
                for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
            }
        finally:
            connection.close()
        return marker, names

    async def test_a_version_one_database_opens_under_version_two_with_every_row_intact(
        self, path: Path
    ) -> None:
        """ADR-0268 §9's arm 10, the half that is about bytes on disk.

        A store at the previous ``schema_version`` holding an ``ESTABLISHED`` row
        whose goal is **already closed** — the closing act having run before
        ``end_for_goal`` existed. **It opens**, every row it held intact and the
        closure-record storage created under the new marker; **the upgrade ends
        nothing, records no closure and rewrites no row**; and the row still appears
        in ``standing`` and still covers a call.

        *"A lane that moved the marker without creating the storage has shipped a
        store no existing database opens"*, which is what the table assertion
        catches; one that rewrote a row would have retrofitted a decision ADR-0247
        §8(b) makes prospective.
        """
        first = SqliteGoalAuthorizationStore(path=path, now=SHARED_CLOCK.reset())
        try:
            await first.record(established(id="legacy"))
            before = await first.export()
        finally:
            first.close()
        self._made_version_one(path)
        assert self._marker_and_tables(path)[0] == "1"

        second = SqliteGoalAuthorizationStore(path=path, now=SHARED_CLOCK.reset())
        try:
            marker, tables = self._marker_and_tables(path)
            assert marker == "2"
            assert "goal_authorization_closures" in tables
            # **No row rewritten, re-dispositioned or back-filled.**
            assert await second.export() == before
            assert [row.id for row in await second.standing(GOAL)] == ["legacy"]
            assert await second.live_for(GOAL, TOOL.id) is not None
            # **No goal recorded closed by the upgrade**: nothing is fenced, which a
            # ``record`` for that same goal succeeding is the evidence of.
            assert await second.record(established(id="fresh", tool=OTHER_TOOL)) == "fresh"
        finally:
            second.close()

    async def test_the_upgraded_row_lapses_on_its_own_expiry_and_no_ending_reaches_it(
        self, path: Path
    ) -> None:
        """Arm 10: the row *"still covers a call, **until its own ``expires_at``** and
        no longer — asserted by advancing the clock past it"*.

        That is ADR-0268 §9's prospectivity bound exactly, and **it is no worse than
        the pre-decision behaviour**: the defect the decision names, persisting for
        rows written before the fix and bounded by the backstop that was their only
        bound (ADR-0256 §1). **No upgrade ends it and no sweep finds it**, which is
        the point of asserting the expiry rather than an ending.
        """
        clock = MovableClock()
        first = SqliteGoalAuthorizationStore(path=path, now=SHARED_CLOCK.reset())
        try:
            await first.record(established(id="legacy"))
        finally:
            first.close()
        self._made_version_one(path)

        second = SqliteGoalAuthorizationStore(path=path, now=clock)
        try:
            clock.set(EXPIRES - timedelta(microseconds=1))
            assert await second.live_for(GOAL, TOOL.id) is not None
            clock.set(EXPIRES)
            assert await second.live_for(GOAL, TOOL.id) is None
            held = await second.resolve("legacy")
            assert held is not None
            assert held.disposition is AuthorizationDisposition.ESTABLISHED
        finally:
            second.close()

    async def test_a_reopen_of_a_pre_decision_goal_ends_the_row_the_closure_never_reached(
        self, path: Path
    ) -> None:
        """Arm 10: *"the reopen is the one path that is closed"*.

        Reopening that goal ends the legacy row ``GOAL_CLOSED`` **before** clearing
        the fence, so a call of the reopened goal is covered by **no** row written
        before the upgrade. That is the only route by which such a row otherwise
        reaches a call of the reopened goal, and it is why ADR-0268 §2 orders the
        pair ending-then-clear rather than the other way about.

        **The reopen's two calls are driven directly here**, because the act that
        takes them is ``orchestration``'s and this file is about what the durable
        store does with a file it did not write.
        """
        first = SqliteGoalAuthorizationStore(path=path, now=SHARED_CLOCK.reset())
        try:
            await first.record(established(id="legacy"))
        finally:
            first.close()
        self._made_version_one(path)

        second = SqliteGoalAuthorizationStore(path=path, now=SHARED_CLOCK.reset())
        try:
            assert await second.end_for_goal(GOAL, at=NOW, goal_version=7) == 1
            assert await second.clear_closure(GOAL, goal_version=7) is True
            held = await second.resolve("legacy")
            assert held is not None
            assert (held.disposition, held.settled_at) == (
                AuthorizationDisposition.GOAL_CLOSED,
                NOW,
            )
            assert await second.standing(GOAL) == ()
            assert await second.live_for(GOAL, TOOL.id) is None
            # The fence is down, so the reopened request can establish afresh.
            assert await second.record(established(id="afresh")) == "afresh"
        finally:
            second.close()

    async def test_a_faulting_ending_on_a_pre_decision_database_leaves_it_unfenced(
        self, path: Path
    ) -> None:
        """Arm 10's injection, on the database that carries no fence.

        *"``end_for_goal`` faulting after a successful ``ACTIVE`` write leaves the
        goal **active and unfenced**, its legacy row **still ``ESTABLISHED`` and
        still covering a call** until its own ``expires_at``."* That is §9's
        prospectivity bound and the state the reopen exists to improve on rather than
        one this decision creates — **no clause claims every call of such a goal
        asks** — and the repair is the user's own abandon and reopen.

        The fault is injected at the store's own step, which is all-or-nothing, so
        what it leaves is *nothing*: no settlement and no record.
        """
        first = SqliteGoalAuthorizationStore(path=path, now=SHARED_CLOCK.reset())
        try:
            await first.record(established(id="legacy"))
        finally:
            first.close()
        self._made_version_one(path)

        second = SqliteGoalAuthorizationStore(path=path, now=SHARED_CLOCK.reset())
        try:
            second.close()  # the connection the next call would use
            with pytest.raises(AuthorizationError):
                await second.end_for_goal(GOAL, at=NOW, goal_version=7)
        finally:
            second.close()

        third = SqliteGoalAuthorizationStore(path=path, now=SHARED_CLOCK.reset())
        try:
            held = await third.resolve("legacy")
            assert held is not None
            assert held.disposition is AuthorizationDisposition.ESTABLISHED
            assert [row.id for row in await third.standing(GOAL)] == ["legacy"]
            # **Unfenced**: a fresh row records, which on a goal closed *under* this
            # decision it could not.
            assert await third.record(established(id="unfenced", tool=OTHER_TOOL)) == "unfenced"
            # And the repair is the user's own two acts.
            assert await third.end_for_goal(GOAL, at=NOW, goal_version=8) == 2
            assert await third.clear_closure(GOAL, goal_version=9) is True
            assert await third.record(established(id="repaired")) == "repaired"
        finally:
            third.close()

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

    @pytest.mark.parametrize(
        "planted",
        [4.5, "xyz", "x007", " x4", "+x4", "xABC", "0x4", "abc", 9, 10, 16, "x" + "1" * 4301],
        ids=str,
    )
    async def test_a_closure_record_that_cannot_be_read_exactly_is_refused(
        self, path: Path, planted: object
    ) -> None:
        """ADR-0268 §1's watermark is *"never lowered"*, so it is read exactly or not read.

        **A declared column type is an affinity and not a constraint**: SQLite stores
        what it is given, so an `INTEGER` column takes ``4.5`` and ``'abc'`` alike. A
        store reading that back with ``int(…)`` would take a planted ``4.5`` as
        version **4** — and an ``end_for_goal`` at 4 would then proceed and rewrite
        the record **down** to 4, lowering the watermark the record exists to hold;
        ``'abc'`` would instead leak a raw ``ValueError`` past this layer's boundary.
        Adversarial review, round 2, ``major``.

        **Both lines are asserted here.** The table's own ``CHECK`` refuses the write
        — which is what the planting itself shows — and where a file this store did
        not write gets past it, the decode refuses the record as an
        ``AuthorizationError`` **without mutating anything**.

        ``'x007'``, ``' x4'``, ``'+x4'``, ``'xABC'`` and ``'0x4'`` are in the table
        because ``int(…, 16)`` accepts what is inside every one of them while none is
        what was written: two spellings of one number would both decode and only one
        would compare equal to the record.

        **``9``, ``10``, ``16`` and ``'abc'`` are the round-4 finding.** The column's
        ``TEXT`` affinity stores a planted integer as its **decimal** text, so an
        untagged hex encoding would have read a planted ``10`` back as **16** — a
        closure held at the wrong version, and a ``clear_closure`` at 10 then leaving
        a live goal fenced for good. ``9`` is beside them because it is the largest
        integer the two renderings agree on, which is why an earlier revision's note
        claiming a planted integer round-trips looked true. The tag makes the two
        languages disjoint, so every one of them is refused rather than misread.

        ``'x' + '1' * 4301`` is there because it is canonical text of a magnitude a
        *decimal* decoder could not have read at all — the ceiling this encoding
        exists not to have — so it must read back **exactly** rather than raise.
        """
        store = SqliteGoalAuthorizationStore(path=path, now=SHARED_CLOCK.reset())
        try:
            await store.record(established(id="a1"))
            assert await store.end_for_goal(GOAL, at=NOW, goal_version=9) == 1
        finally:
            store.close()

        connection = sqlite3.connect(path)
        try:
            try:
                connection.execute("UPDATE goal_authorization_closures SET version = ?", (planted,))
                connection.commit()
            except sqlite3.IntegrityError:
                # The first line held: the stored form is pinned by the table itself.
                return
        finally:
            connection.close()

        second = SqliteGoalAuthorizationStore(path=path, now=SHARED_CLOCK.reset())
        try:
            before = await second.export()
            if planted == "x" + "1" * 4301:
                # **Not corruption**: canonical base-16 text of a 4301-digit
                # magnitude, which is exactly what the encoding exists to hold and
                # what a decimal one could not have converted in either direction.
                assert await second.end_for_goal(GOAL, at=NOW, goal_version=0) == 0
                assert await second.clear_closure(GOAL, goal_version=int("1" * 4301, 16)) is True
                return
            with pytest.raises(AuthorizationError, match="canonical"):
                await second.end_for_goal(GOAL, at=NOW, goal_version=4)
            with pytest.raises(AuthorizationError, match="canonical"):
                await second.clear_closure(GOAL, goal_version=4)
            assert await second.export() == before, "and nothing is mutated on the way out"
        finally:
            second.close()

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
                id="a1", coverage=(coverage_member(BoundKind.MONEY, bound=money_bound("800")),)
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
