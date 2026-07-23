"""Shared conformance suite for the MemoryStore Protocol.

Every ``MemoryStore`` implementation must pass this suite (CONTRIBUTING,
"Protocol conformance suites"). A concrete test subclasses
:class:`MemoryStoreContract` and overrides the ``store`` fixture; the suite
asserts only behaviour *universal* to the contract — not the retrieval rules of
any one implementation (lexical vs. semantic), which stay in the per-implementation
test modules.

Expiry cases use a deadline far in the past, so they hold under any store clock
(wall-clock or injected) without the suite having to dictate one.

Named ``*_contract`` (not ``test_*``) so pytest collects it only via a
``Test``-prefixed subclass, never the abstract base directly.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from ai_assistant.core.protocols import MemoryStore

if TYPE_CHECKING:
    from collections.abc import Callable

    StoreFactory = Callable[[Callable[[], datetime]], MemoryStore]
from ai_assistant.core.types import (
    MemoryKind,
    MemoryRecord,
    MemorySource,
    PreferenceMemory,
    Provenance,
    SemanticMemory,
    Validity,
)

# Far in the past: expired (or window-closed) under any clock at or after 2000 —
# every real wall-clock and the fixed test clocks the subclasses inject.
_LONG_AGO = datetime(2000, 1, 1, tzinfo=UTC)
# Far in the future: a ``valid_from`` here is not yet open under any such clock.
_FAR_FUTURE = datetime(2999, 1, 1, tzinfo=UTC)
# The instant every shipped store fixture's injected clock returns; the ``now``
# fixture below exposes it so window *boundary* cases can be built relative to it.
_STORE_NOW = datetime(2026, 6, 1, tzinfo=UTC)
_ONE_HOUR = timedelta(hours=1)


def _provenance() -> Provenance:
    return Provenance(
        source=MemorySource.OBSERVED,
        confidence=0.6,
        last_updated=datetime(2026, 1, 1, tzinfo=UTC),
    )


def _semantic(
    record_id: str,
    content: str,
    *,
    expires_at: datetime | None = None,
    validity: Validity | None = None,
) -> MemoryRecord:
    return SemanticMemory(
        id=record_id,
        content=content,
        fact=content,
        provenance=_provenance(),
        expires_at=expires_at,
        validity=validity or Validity(),
    )


def _preference(record_id: str, content: str) -> MemoryRecord:
    return PreferenceMemory(
        id=record_id, content=content, preference=content, provenance=_provenance()
    )


class MemoryStoreContract:
    """The behavioural contract every ``MemoryStore`` implementation must satisfy."""

    @pytest.fixture
    def store(self) -> MemoryStore:
        """Override in a subclass to supply the implementation under test."""
        raise NotImplementedError

    @pytest.fixture
    def now(self) -> datetime:
        """The instant the store-under-test's injected clock returns.

        Every shipped ``MemoryStore`` subclass injects a clock fixed at
        :data:`_STORE_NOW`, so the validity-window boundary cases below (a
        ``valid_from``/``valid_until`` exactly *at* now) can be built relative to
        it. A subclass whose ``store`` fixture uses a different clock overrides
        this fixture to match.
        """
        return _STORE_NOW

    @pytest.fixture
    def store_factory(self) -> StoreFactory:
        """Override in a subclass to build a store under test with a given clock.

        Used by the read-consistency case that needs an *advancing* clock — one
        returning a later instant on each call — which the fixed ``store`` fixture
        cannot express.
        """
        raise NotImplementedError

    def test_conforms_to_protocol(self, store: MemoryStore) -> None:
        assert isinstance(store, MemoryStore)

    async def test_add_returns_id_and_get_round_trips(self, store: MemoryStore) -> None:
        returned = await store.add(_preference("p1", "prefers concise replies"))

        assert returned == "p1"
        got = await store.get("p1")
        assert got is not None
        assert got.id == "p1"
        assert got.kind == "preference"  # the typed record survives the round trip

    async def test_get_missing_returns_none(self, store: MemoryStore) -> None:
        assert await store.get("nope") is None

    async def test_add_overwrites_same_id_with_full_replacement(self, store: MemoryStore) -> None:
        # Upsert is a full replacement, not a merge: re-adding an id with a
        # different kind must leave no trace of the previous record — not its
        # kind, nor its subtype fields. (Overwriting across kinds also proves the
        # backend rewrites every column, not just the payload.)
        await store.add(_semantic("1", "old semantic note"))
        replacement = _preference("1", "new preference note")
        await store.add(replacement)

        got = await store.get("1")
        assert got is not None
        assert got.kind == "preference"  # the old semantic kind is gone
        assert got == replacement  # the whole record equals the second input

    async def test_search_finds_a_matching_record(self, store: MemoryStore) -> None:
        await store.add(_semantic("c", "the user likes coffee"))

        results = await store.search("coffee")

        assert "c" in {r.id for r in results}

    async def test_search_filters_by_kind(self, store: MemoryStore) -> None:
        await store.add(_semantic("s", "coffee fact"))
        await store.add(_preference("p", "coffee preference"))

        results = await store.search("coffee", kinds=[MemoryKind.PREFERENCE])

        assert [r.id for r in results] == ["p"]

    async def test_search_respects_limit(self, store: MemoryStore) -> None:
        for i in range(4):
            await store.add(_semantic(f"k{i}", "shared coffee keyword"))

        results = await store.search("coffee", limit=2)

        assert len(results) <= 2

    async def test_empty_query_matches_nothing(self, store: MemoryStore) -> None:
        await store.add(_semantic("1", "some content"))

        assert await store.search("   ") == []

    async def test_non_positive_limit_matches_nothing(self, store: MemoryStore) -> None:
        await store.add(_semantic("1", "coffee"))

        assert await store.search("coffee", limit=0) == []
        assert await store.search("coffee", limit=-1) == []

    async def test_delete_removes_and_reports_existence(self, store: MemoryStore) -> None:
        await store.add(_semantic("1", "a fact"))

        assert await store.delete("1") is True
        assert await store.get("1") is None
        assert await store.delete("1") is False  # already gone

    async def test_clear_removes_all_and_returns_count(self, store: MemoryStore) -> None:
        await store.add(_semantic("1", "one"))
        await store.add(_semantic("2", "two"))

        assert await store.clear() == 2
        assert await store.get("1") is None
        assert await store.clear() == 0  # empty now

    async def test_export_returns_live_records_only(self, store: MemoryStore) -> None:
        await store.add(_semantic("live", "still valid"))
        await store.add(_semantic("dead", "gone", expires_at=_LONG_AGO))

        exported = await store.export()

        assert [r.id for r in exported] == ["live"]

    async def test_expired_records_are_hidden_from_get_and_search(self, store: MemoryStore) -> None:
        await store.add(_semantic("1", "coffee", expires_at=_LONG_AGO))

        assert await store.get("1") is None
        assert "1" not in {r.id for r in await store.search("coffee")}

    async def test_purge_expired_removes_only_expired(self, store: MemoryStore) -> None:
        await store.add(_semantic("live", "keeps"))
        await store.add(_semantic("dead", "goes", expires_at=_LONG_AGO))

        assert await store.purge_expired() == 1
        assert await store.get("live") is not None
        assert await store.purge_expired() == 0  # nothing left

    # --- Validity window read obligations (ADR-0045 §6) -----------------------

    async def test_fully_open_window_is_live_everywhere(self, store: MemoryStore) -> None:
        # The default window (both ends None) preserves today's behaviour: the
        # record is returned by get, search, and export alike.
        await store.add(_semantic("open", "coffee", validity=Validity()))

        assert await store.get("open") is not None
        assert "open" in {r.id for r in await store.search("coffee")}
        assert "open" in {r.id for r in await store.export()}

    async def test_window_closed_record_is_hidden_from_reads_but_kept_by_export(
        self, store: MemoryStore
    ) -> None:
        # A retired belief (closed valid_until) leaves the read path but is
        # retained: export is a data-rights obligation and must still return it.
        await store.add(_semantic("closed", "coffee", validity=Validity(valid_until=_LONG_AGO)))

        assert await store.get("closed") is None
        assert "closed" not in {r.id for r in await store.search("coffee")}
        assert "closed" in {r.id for r in await store.export()}

    async def test_not_yet_valid_record_is_hidden_from_reads_but_kept_by_export(
        self, store: MemoryStore
    ) -> None:
        # The valid_from end is enforced too, not assumed away: a record that is
        # not yet live is off the read path, yet still retained for export.
        await store.add(_semantic("future", "coffee", validity=Validity(valid_from=_FAR_FUTURE)))

        assert await store.get("future") is None
        assert "future" not in {r.id for r in await store.search("coffee")}
        assert "future" in {r.id for r in await store.export()}

    async def test_expired_wins_over_a_closed_window_in_export(self, store: MemoryStore) -> None:
        # The two axes are orthogonal but retention wins: a record that is both
        # window-closed *and* expired is excluded from export, not kept as history.
        # export keeps closed-window records only while they are still retained.
        await store.add(
            _semantic(
                "gone",
                "coffee",
                expires_at=_LONG_AGO,
                validity=Validity(valid_until=_LONG_AGO),
            )
        )

        assert await store.get("gone") is None
        assert "gone" not in {r.id for r in await store.export()}  # retention beats history

    async def test_valid_until_boundary_is_half_open(
        self, store: MemoryStore, now: datetime
    ) -> None:
        # [from, until): at valid_until the record is already retired; strictly
        # before it, it is still live. Both get and search agree.
        await store.add(_semantic("at_until", "coffee alpha", validity=Validity(valid_until=now)))
        await store.add(
            _semantic("before_until", "coffee beta", validity=Validity(valid_until=now + _ONE_HOUR))
        )

        assert await store.get("at_until") is None
        assert await store.get("before_until") is not None
        found = {r.id for r in await store.search("coffee")}
        assert "at_until" not in found
        assert "before_until" in found

    async def test_valid_from_boundary_is_half_open(
        self, store: MemoryStore, now: datetime
    ) -> None:
        # [from, until), all three cases for the valid_from end: strictly before
        # now is already live, at now is live, strictly after now is not yet live.
        # Both get and search agree on each.
        await store.add(
            _semantic("before_from", "coffee beta", validity=Validity(valid_from=now - _ONE_HOUR))
        )
        await store.add(_semantic("at_from", "coffee gamma", validity=Validity(valid_from=now)))
        await store.add(
            _semantic("after_from", "coffee delta", validity=Validity(valid_from=now + _ONE_HOUR))
        )

        assert await store.get("before_from") is not None
        assert await store.get("at_from") is not None
        assert await store.get("after_from") is None
        found = {r.id for r in await store.search("coffee")}
        assert "before_from" in found
        assert "at_from" in found
        assert "after_from" not in found

    async def test_stored_records_are_isolated_from_caller_mutation(
        self, store: MemoryStore
    ) -> None:
        # The window drives read filtering, so a caller must not be able to retire
        # or revive a stored record by mutating the nested Validity — neither the
        # object it passed to add, nor one a read handed back.
        original = _semantic("iso", "coffee", validity=Validity(valid_until=_FAR_FUTURE))
        await store.add(original)

        original.validity.valid_until = _LONG_AGO  # mutate the caller's own object
        assert await store.get("iso") is not None  # stored copy is still live

        got = await store.get("iso")
        assert got is not None
        got.validity.valid_until = _LONG_AGO  # mutate a returned object
        assert await store.get("iso") is not None  # stored copy is still live

    async def test_search_judges_every_record_against_one_clock_reading(
        self, store_factory: StoreFactory
    ) -> None:
        # A single search must use one "now" for all candidates, not re-read an
        # advancing clock per record — otherwise a boundary record's fate depends
        # on iteration order, and implementations of the Protocol diverge.
        step = timedelta(hours=1)
        state = {"now": _STORE_NOW}

        def advancing() -> datetime:
            reading = state["now"]
            state["now"] = reading + step
            return reading

        store = store_factory(advancing)
        # All fall due after the first reading but before later ones, so a
        # per-record advancing clock would retire the later-iterated ones.
        deadline = _STORE_NOW + step // 2
        for i in range(3):
            await store.add(_semantic(f"c{i}", "coffee", validity=Validity(valid_until=deadline)))

        results = await store.search("coffee")

        assert {r.id for r in results} == {"c0", "c1", "c2"}
