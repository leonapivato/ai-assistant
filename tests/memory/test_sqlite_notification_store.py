"""``SqliteNotificationStore`` passes the shared suites, plus its own parts.

ADR-0028 §8's convention applied to a fourth store: the suites are bound to the
**production** store and policy as well as to the canonical fakes, because a
suite bound only to the double certifies the double while the real store drifts.
That is what the duplication in
:mod:`ai_assistant.memory.notification_policy` is safe under — two
implementations of one ruling, held to one set of assertions.

Beside the bindings are the properties that belong to *this* backend and to no
contract: the owner-only file mode ADR-0004 §4 requires of a Tier 1 store, the
durability of a record and of a spent unit of budget across a reopen, the
refusals a corrupt row earns, and the one guarantee this backend buys that the
fake cannot — that ADR-0130 §3's atomic act is a single ``BEGIN IMMEDIATE``
transaction spanning the policy's ruling.
"""

from __future__ import annotations

import asyncio
import sqlite3
import stat
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import pytest
from notification_contract import (
    NOW,
    MutableClock,
    NotificationPolicyContract,
    NotificationStoreContract,
    StoreFactory,
    candidate,
)

from ai_assistant.core.errors import NotificationStoreError
from ai_assistant.core.types import (
    ClassReach,
    NotificationCondition,
    NotificationDispositionKind,
    NotificationPreferences,
    NotificationReach,
    QuietWindow,
)
from ai_assistant.memory.notification_policy import DefaultNotificationPolicy
from ai_assistant.memory.notification_store import SqliteNotificationStore

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from pathlib import Path

    from ai_assistant.core.protocols import NotificationPolicy, NotificationStore
    from ai_assistant.core.types import NotificationCandidate

_RETENTION = timedelta(days=7)
_CAP = 100


def _fixed_now() -> datetime:
    return NOW


def _perishable(key: str = "k1") -> NotificationCandidate:
    """A candidate that would interrupt, so a case can spend a unit of budget."""
    return candidate(key=key, expires_at=NOW + timedelta(days=1))


def _interrupting() -> NotificationPreferences:
    """Settings under which a perishable candidate is ruled ``INTERRUPT``."""
    return NotificationPreferences(
        reaches=(ClassReach(notification_class="calendar", reach=NotificationReach.INTERRUPT),)
    )


class TestSqliteNotificationPolicyContract(NotificationPolicyContract):
    """Runs DefaultNotificationPolicy through the shared NotificationPolicy suite."""

    @pytest.fixture
    def policy(self) -> NotificationPolicy:
        return DefaultNotificationPolicy()

    @pytest.fixture
    def policy_in(self) -> Callable[[str], NotificationPolicy]:
        def build(timezone: str) -> NotificationPolicy:
            return DefaultNotificationPolicy(timezone=timezone)

        return build


class TestSqliteNotificationStoreContract(NotificationStoreContract):
    """Runs SqliteNotificationStore through the shared NotificationStore suite."""

    @pytest.fixture
    def store(self, tmp_path: Path) -> Iterator[NotificationStore]:
        realised = SqliteNotificationStore(path=tmp_path / "notifications.db", now=_fixed_now)
        try:
            yield realised
        finally:
            realised.close()

    @pytest.fixture
    def factory(self, tmp_path: Path) -> Iterator[StoreFactory]:
        """Build subjects over the injected seams, closing each at teardown.

        A function rather than the class itself, deliberately: the class object
        *structurally satisfies* ``NotificationStore``, so handing it over would
        look to the Protocol-triad check like a second subject standing beside
        the fake.
        """
        opened: list[SqliteNotificationStore] = []

        def build(
            *,
            now: Callable[[], datetime],
            retention: timedelta | None = _RETENTION,
            cap: int = _CAP,
        ) -> NotificationStore:
            realised = SqliteNotificationStore(
                path=tmp_path / f"notifications-{len(opened)}.db",
                now=now,
                retention=retention,
                cap=cap,
            )
            opened.append(realised)
            return realised

        try:
            yield build
        finally:
            for realised in opened:
                realised.close()

    @pytest.fixture
    def policy(self) -> NotificationPolicy:
        return DefaultNotificationPolicy()


# --- this backend's own properties ----------------------------------------


@pytest.fixture
def store(tmp_path: Path) -> Iterator[SqliteNotificationStore]:
    """A store on a file, so a case can reopen it or inspect its mode."""
    realised = SqliteNotificationStore(path=tmp_path / "notifications.db", now=_fixed_now)
    try:
        yield realised
    finally:
        realised.close()


@pytest.mark.parametrize(
    "cap",
    [0, -1, 2**63, 1.5, True],
    ids=["zero", "negative", "over-wide", "a-float", "a-bool"],
)
def test_the_store_refuses_a_cap_it_cannot_work_under(tmp_path: Path, cap: object) -> None:
    """ADR-0130 §7, refused at construction on ADR-0022 §4a's arrangement.

    A cap of ``0`` is at capacity before its first admission, so every candidate
    would be dropped while the system reported health — the class of value §4a
    refuses when the store is built rather than per admission.
    """
    with pytest.raises(ValueError, match="cap must be an int"):
        SqliteNotificationStore(path=tmp_path / "n.db", cap=cap)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "retention",
    [timedelta(0), timedelta(seconds=-1), 7],
    ids=["zero", "negative", "not-a-duration"],
)
def test_the_store_refuses_a_retention_it_cannot_work_under(
    tmp_path: Path, retention: object
) -> None:
    """``None`` is the only spelling for "never purged" (ADR-0130 §7)."""
    with pytest.raises(ValueError, match="retention must be"):
        SqliteNotificationStore(path=tmp_path / "n.db", retention=retention)  # type: ignore[arg-type]


def test_the_database_file_is_owner_only(tmp_path: Path) -> None:
    """ADR-0004 §4: a Tier 1 store's file is readable by nobody else.

    A candidate carries free text a producer wrote to be shown to a person, so
    this store inherits every obligation the ``MemoryStore`` carries.
    """
    path = tmp_path / "notifications.db"

    realised = SqliteNotificationStore(path=path, now=_fixed_now)
    realised.close()

    assert stat.S_IMODE(path.stat().st_mode) == 0o600


async def test_a_record_survives_a_reopen(tmp_path: Path) -> None:
    """Durability is the whole point of this backend over the fake."""
    path = tmp_path / "notifications.db"
    first = SqliteNotificationStore(path=path, now=_fixed_now)
    ruling = await first.admit(candidate(key="k1"), policy=DefaultNotificationPolicy())
    first.close()
    assert ruling.notification_id is not None

    second = SqliteNotificationStore(path=path, now=_fixed_now)
    try:
        recovered = await second.get(ruling.notification_id)
    finally:
        second.close()

    assert recovered is not None
    assert recovered.candidate.candidate_key == "k1"
    assert recovered.kind is NotificationDispositionKind.HOLD
    assert recovered.reason is NotificationCondition.PERISHABLE
    assert recovered.retention == _RETENTION


async def test_a_spent_unit_of_budget_survives_a_reopen(tmp_path: Path) -> None:
    """ADR-0130 §5: "no spent unit is refunded except by an act that says so".

    A restart is not such an act. A store keeping its spend ledger only in memory
    would hand a wrong producer a fresh budget on every hub restart, which is
    exactly the bound §5 exists to make computable.
    """
    path = tmp_path / "notifications.db"
    policy = DefaultNotificationPolicy()
    first = SqliteNotificationStore(path=path, now=_fixed_now)
    await first.set_preferences(
        NotificationPreferences(
            reaches=(ClassReach(notification_class="calendar", reach=NotificationReach.INTERRUPT),),
            interruption_budget=1,
        )
    )
    assert (await first.admit(_perishable("k1"), policy=policy)).kind is (
        NotificationDispositionKind.INTERRUPT
    )
    first.close()

    second = SqliteNotificationStore(path=path, now=_fixed_now)
    try:
        second_ruling = await second.admit(_perishable("k2"), policy=policy)
    finally:
        second.close()

    assert second_ruling.kind is NotificationDispositionKind.HOLD
    assert second_ruling.reason is NotificationCondition.BUDGET


async def test_a_spend_outside_the_window_is_swept_from_the_ledger(
    tmp_path: Path,
) -> None:
    """The ledger is bounded by the window, not by uptime (ADR-0130 §6).

    Entries outside the window in force are deleted rather than merely skipped,
    which is what keeps a long-lived hub's rate-limiter state from growing
    without bound.
    """
    clock = MutableClock()
    store = SqliteNotificationStore(path=tmp_path / "n.db", now=clock)
    policy = DefaultNotificationPolicy()
    try:
        await store.set_preferences(_interrupting())
        await store.admit(_perishable("k1"), policy=policy)
        clock.advance(timedelta(days=2))

        # Still perishable at the advanced clock, so this ruling spends a unit
        # while the first one's has fallen out of the rolling window.
        await store.admit(candidate(key="k2", expires_at=NOW + timedelta(days=5)), policy=policy)

        rows = store._conn.execute("SELECT COUNT(*) FROM notification_interruptions").fetchone()
    finally:
        store.close()

    assert rows[0] == 1


async def test_the_preferences_survive_a_clear(tmp_path: Path) -> None:
    """ADR-0130 §9: a sweep of the records leaves the user's settings alone.

    A ``clear`` that silently restored every class to ``hold`` would undo a
    "never tell me this" the user meant to keep.
    """
    store = SqliteNotificationStore(path=tmp_path / "n.db", now=_fixed_now)
    try:
        await store.set_preferences(_interrupting())
        await store.admit(candidate(key="k1"), policy=DefaultNotificationPolicy())

        assert await store.clear() == 1

        assert (await store.preferences()).reach_for("calendar") is NotificationReach.INTERRUPT
    finally:
        store.close()


async def test_a_corrupt_row_is_reported_as_this_stores_error(tmp_path: Path) -> None:
    """Not a raw ``ValidationError`` no ``AssistantError`` boundary catches.

    A corrupt row is a *store* fault rather than a caller's, and an adapter that
    renders an ``AssistantError`` would otherwise print a traceback.
    """
    store = SqliteNotificationStore(path=tmp_path / "n.db", now=_fixed_now)
    try:
        ruling = await store.admit(candidate(key="k1"), policy=DefaultNotificationPolicy())
        assert ruling.notification_id is not None
        store._conn.execute(
            "UPDATE notifications SET kind = 'shouted' WHERE id = ?", (ruling.notification_id,)
        )

        with pytest.raises(NotificationStoreError, match="not a known kind"):
            await store.get(ruling.notification_id)
    finally:
        store.close()


async def test_a_corrupt_failed_set_is_reported_as_this_stores_error(tmp_path: Path) -> None:
    """The one column this backend encodes itself rather than through pydantic."""
    store = SqliteNotificationStore(path=tmp_path / "n.db", now=_fixed_now)
    try:
        ruling = await store.admit(candidate(key="k1"), policy=DefaultNotificationPolicy())
        assert ruling.notification_id is not None
        store._conn.execute(
            "UPDATE notifications SET failed = '{' WHERE id = ?", (ruling.notification_id,)
        )

        with pytest.raises(NotificationStoreError, match="not readable JSON"):
            await store.get(ruling.notification_id)
    finally:
        store.close()


async def test_corrupt_preferences_are_reported_as_this_stores_error(tmp_path: Path) -> None:
    """An empty store defaults; a *corrupt* one is a fault and says so.

    The two are different facts, and answering the defaults over a corrupt row
    would silently drop a "never tell me this" the user had set.
    """
    store = SqliteNotificationStore(path=tmp_path / "n.db", now=_fixed_now)
    try:
        await store.set_preferences(_interrupting())
        store._conn.execute(
            "INSERT OR REPLACE INTO notification_preferences(id, value) VALUES(1, ?)",
            ('{"interruption_budget": -3}',),
        )

        with pytest.raises(NotificationStoreError, match="corrupt"):
            await store.preferences()
    finally:
        store.close()


async def test_an_unusable_clock_is_reported_as_this_stores_error(tmp_path: Path) -> None:
    """ADR-0026 §4, §7: this seam never reaches a `core` field validator.

    Every reading becomes an integer microsecond epoch, so the producer is the
    only place a naive reading can be caught.
    """
    naive = NOW.replace(tzinfo=None)
    store = SqliteNotificationStore(path=tmp_path / "n.db", now=lambda: naive)
    try:
        with pytest.raises(NotificationStoreError):
            await store.due()
    finally:
        store.close()


async def test_an_id_source_returning_a_present_id_raises_and_commits_nothing(
    tmp_path: Path,
) -> None:
    """A collision is a fault, never an overwrite (``DeferralStore.defer``'s rule).

    Absorbing it would lose a record silently and leave two dispositions naming
    one id. **Nothing is committed by a failed admission** — no record, and no
    unit of budget.
    """
    store = SqliteNotificationStore(
        path=tmp_path / "n.db", now=_fixed_now, new_id=lambda: "always-the-same"
    )
    policy = DefaultNotificationPolicy()
    try:
        await store.set_preferences(_interrupting())
        await store.admit(_perishable("k1"), policy=policy)

        with pytest.raises(NotificationStoreError, match="already holds"):
            await store.admit(_perishable("k2"), policy=policy)

        assert len(await store.export()) == 1
        # The failed admission left no unit behind it either: the ledger still
        # holds only the one the first, successful, admission spent.
        spent = store._conn.execute("SELECT COUNT(*) FROM notification_interruptions").fetchone()
        assert spent[0] == 1
    finally:
        store.close()


async def test_a_blank_id_source_raises_before_anything_is_written(tmp_path: Path) -> None:
    """A caller supplies no id here, so there is no argument for a ``ValueError``."""
    store = SqliteNotificationStore(
        path=tmp_path / "n.db",
        now=_fixed_now,
        new_id=lambda: "   ",
    )
    try:
        with pytest.raises(NotificationStoreError, match="not an identifier"):
            await store.admit(candidate(key="k1"), policy=DefaultNotificationPolicy())

        assert await store.export() == []
    finally:
        store.close()


async def test_the_ruling_runs_inside_one_write_transaction(tmp_path: Path) -> None:
    """ADR-0130 §3: the read, the ruling and the write are **one atomic act**.

    This is the guarantee the fake cannot buy — its exclusion is an
    ``asyncio.Lock``, which holds across coroutines on one loop and not across
    processes. Here the policy is asked with ``BEGIN IMMEDIATE`` already taken,
    so a second *process* cannot interleave between the facts and the record they
    were ruled against. Asserted by having the policy observe the connection's
    transaction state at the moment it is asked, which is the only place the
    property is visible.
    """
    store = SqliteNotificationStore(path=tmp_path / "n.db", now=_fixed_now)
    inner = DefaultNotificationPolicy()
    seen: list[bool] = []

    class Observing:
        async def rule(self, subject, **facts):  # type: ignore[no-untyped-def]
            seen.append(store._conn.in_transaction)
            return await inner.rule(subject, **facts)

    try:
        await store.admit(candidate(key="k1"), policy=Observing())  # type: ignore[arg-type]
    finally:
        store.close()

    assert seen == [True]


async def test_a_policy_that_raises_leaves_the_store_untouched(tmp_path: Path) -> None:
    """The ruling transaction rolls back, and the connection stays usable.

    A transaction left open on a shared connection is a resource held with
    nothing running that will release it: the next ``BEGIN`` fails with "cannot
    start a transaction within a transaction" and the store is poisoned for every
    later caller (``memory/_transactions.py``). The second admission is what
    proves the rollback happened.
    """
    store = SqliteNotificationStore(path=tmp_path / "n.db", now=_fixed_now)

    class Exploding:
        async def rule(self, subject, **facts):  # type: ignore[no-untyped-def]
            msg = "no"
            raise RuntimeError(msg)

    try:
        with pytest.raises(RuntimeError, match="no"):
            await store.admit(candidate(key="k1"), policy=Exploding())  # type: ignore[arg-type]

        assert await store.export() == []
        assert (
            await store.admit(candidate(key="k1"), policy=DefaultNotificationPolicy())
        ).notification_id is not None
    finally:
        store.close()


async def test_two_concurrent_offers_serialise_on_this_backend(tmp_path: Path) -> None:
    """§3 over a real connection: two coroutines never share one transaction.

    The shared suite asserts the *outcome*; this asserts that the mechanism
    reaching it is a serialised connection rather than two overlapping
    transactions, which is the failure ``sqlite3`` reports rather than absorbs.
    """
    store = SqliteNotificationStore(path=tmp_path / "n.db", now=_fixed_now, cap=1)
    policy = DefaultNotificationPolicy()
    try:
        rulings = await asyncio.gather(
            store.admit(candidate(key="k1"), policy=policy),
            store.admit(candidate(key="k2"), policy=policy),
        )

        kinds = [ruling.kind for ruling in rulings]
        assert kinds.count(NotificationDispositionKind.DROP) == 1
        assert len(await store.held()) == 1
    finally:
        store.close()


async def test_a_quiet_window_is_read_in_the_configured_zone(tmp_path: Path) -> None:
    """ADR-0130 §6: quiet windows are read in ``Settings.timezone``.

    Midday UTC is the middle of the night in ``Pacific/Kiritimati`` (UTC+14), so
    a window a UTC-reading policy would call clear is one this policy is inside —
    which is the whole of why the zone is the policy's one construction-time
    property.
    """
    store = SqliteNotificationStore(path=tmp_path / "n.db", now=_fixed_now)
    try:
        await store.set_preferences(
            NotificationPreferences(
                reaches=(
                    ClassReach(notification_class="calendar", reach=NotificationReach.INTERRUPT),
                ),
                quiet_windows=(QuietWindow(start=0, end=7 * 60),),
            )
        )

        ruling = await store.admit(
            _perishable("k1"), policy=DefaultNotificationPolicy(timezone="Pacific/Kiritimati")
        )

        assert ruling.kind is NotificationDispositionKind.HOLD
        assert ruling.reason is NotificationCondition.QUIET_WINDOW

        assert ruling.reconsider_at == datetime(2026, 8, 11, 17, 0, tzinfo=UTC)
    finally:
        store.close()


def test_opening_over_an_unusable_path_is_reported_as_this_stores_error(
    tmp_path: Path,
) -> None:
    """A directory is not a database, and the failure carries the seam's error."""
    with pytest.raises(NotificationStoreError, match="failed to open notification store"):
        SqliteNotificationStore(path=tmp_path)


def test_a_reopen_over_a_foreign_schema_is_reported_as_this_stores_error(
    tmp_path: Path,
) -> None:
    """A file that is not a SQLite database fails at open, not at first read."""
    path = tmp_path / "notifications.db"
    path.write_bytes(b"not a database at all, not even slightly")

    with pytest.raises(NotificationStoreError, match="failed to open notification store"):
        SqliteNotificationStore(path=path)


def test_a_failed_open_leaks_no_connection(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The connection is closed when preparing the schema fails.

    Not cosmetic: a leaked handle on a Tier 1 file outlives the failure that
    produced it, and on a hub that retries the open it accumulates.
    """
    opened: list[sqlite3.Connection] = []
    real_connect = sqlite3.connect

    def connect(database: str, **kwargs: Any) -> sqlite3.Connection:
        conn: sqlite3.Connection = real_connect(database, **kwargs)
        opened.append(conn)
        return conn

    def refuse(_store: SqliteNotificationStore) -> None:
        msg = "no"
        raise OSError(msg)

    monkeypatch.setattr(sqlite3, "connect", connect)
    monkeypatch.setattr(SqliteNotificationStore, "_restrict_permissions", refuse)

    with pytest.raises(NotificationStoreError):
        SqliteNotificationStore(path=tmp_path / "n.db")

    assert len(opened) == 1
    with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
        opened[0].execute("SELECT 1")
