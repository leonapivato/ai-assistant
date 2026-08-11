"""Shared conformance suites for the two grant Protocols (ADR-0097 §10).

Every ``SourceGrants`` implementation must pass :class:`SourceGrantsContract`,
and every ``SourceGrantStore`` implementation must pass
:class:`SourceGrantStoreContract` — which inherits the first, because ADR-0097
§10 says so in as many words: "``SourceGrants`` owes the **first three** clauses
below; ``SourceGrantStore`` owes all of them." A concrete test subclasses one of
them and supplies its subject fixture.

**Here rather than under ``tests/core/``.** The corpus puts a suite beside the
subsystem that implements it, and ADR-0097 §3 puts both implementations in
``permissions/`` — ``audit_trail_contract.py`` and ``action_policy_contract.py``
are already here for the same reason. The Protocols themselves stay in ``core``
(§3: "the contract's weight stays in ``core``"), which is what lets
``orchestration`` and ``context`` hold the narrow seam by injection without
either importing ``permissions``.

**Two suites, and the cost is named rather than discovered** (ADR-0097 §3). One
Protocol would have cost one suite and one fake; the split costs two of each, and
it buys the property that a driver *cannot name* ``record`` — which is §1's
central clause held by ``mypy --strict`` instead of by review. Part of the cost
comes back as evidence: §10 binds the narrow suite against **both** canonical
fakes, so "one implementation satisfies both seams" is a test rather than an
assertion.

**What is deliberately not in here**, restated so its absence does not read as
absence from the contract (ADR-0097 §10). The test is whether a clause is
decidable from the store's own surface:

* **§5's caller-side gate and §5a's three clauses.** Obligations on
  ``orchestration`` and ``context``, not on a store; no store implementation
  exhibits any of them. They belong to the ingestion stage's and the adapter's
  own tests, alongside the required ``SourceGrants`` constructor argument that
  makes omitting the gate a type error. All five driver cases §5 and §5a
  distinguish are that lane's, and the canonical fakes carry the scripted
  revocation and scripted failure those cases need.
* **§7's prohibition on citing a grant as ``authorised_by``.** A statement about
  what a *different* subsystem may not do; nothing in a return value exhibits it.
* **§9's rule that a ``source`` must name a reader the hub holds.** A store
  cannot check it — ``permissions/`` may not import ``ai_assistant.readers``
  (ADR-0093 §2) — and ``Identifier`` refuses only a blank string, so nothing in
  ``core`` can either. It is the grant operation's own test.
* **§9a's configured-location disclosure**, the permitted half of the same rule,
  which needs its own tests for the opposite reason and against whichever carrier
  the surface ADR chooses.

Named ``*_contract`` (not ``test_*``) so pytest collects it only via a
``Test``-prefixed subclass, never the abstract bases directly.
"""

from __future__ import annotations

import asyncio
import inspect
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Protocol

import pytest

from ai_assistant.core.errors import GrantError, InvalidGrantError
from ai_assistant.core.protocols import SourceGrants, SourceGrantStore
from ai_assistant.core.types import GrantScope, SourceGrant
from ai_assistant.testing.cancellation import settle
from ai_assistant.testing.grants import DEFAULT_DECIDED_AT, revocation_of, source_grant

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine
    from contextlib import AbstractAsyncContextManager

    from ai_assistant.testing.cancellation import SuspendedMidWrite

#: The source every case below is about unless it is a case about *another*
#: source. A declared-constant-shaped name, as ADR-0093 §7 requires of the real
#: thing: it names the producer, never what the producer reads.
SOURCE = "calendar"

#: What a failure of the cancellation case means, in one place: every assertion
#: in it is the same invariant seen from a different side.
_RELEASED_EARLY = (
    "the cancelled call released its resource while its own work was still "
    "running, so a second caller reached it concurrently"
)


async def _refuses(
    store: SourceGrantStore,
    rejected: SourceGrant,
    error: type[GrantError] = InvalidGrantError,
) -> None:
    """Assert ``record`` refuses ``rejected`` **and writes nothing**.

    ADR-0097 §4 makes ``record`` atomic — the duplicate check, the live-grant
    check, the revocation invariants and the append are one operation — so a
    refusal is not a partial write with an exception on top. Asserting only that
    it raised would accept a store that appended a bad record and *then* rejected
    it, leaving a history the contract says is unrecordable and, for a revocation,
    a grant spent.

    The whole store is compared rather than just the rejected id, because a write
    that landed under a different id, or that mutated the record it named on its
    way through, is the same failure wearing a disguise.
    """
    before = await store.export()

    with pytest.raises(error):
        await store.record(rejected)

    assert await store.export() == before, "a refused write must leave no trace"


class _CancellationOp(Protocol):
    """One ``SourceGrantStore`` operation the ADR-0060 case drives.

    Each :attr:`name` selects a distinct lock site; the suite runs the same
    cancelled-first / concurrent-second scenario against every one, so a
    regression reintroduced at any single site is caught rather than only at
    ``record``. :meth:`first` and :meth:`second` act on **independent** subjects
    — different sources, which ADR-0097 §4's one-live-grant rule makes necessary
    rather than merely tidy — so the concurrent second succeeds whatever the
    cancelled first's indeterminate effect turns out to be.

    **Reads are operations too.** ADR-0060 §3 binds any method that acquires the
    resource, not any method that mutates, so a durable store's locked reads are
    lock sites like its writes: a read that released the connection under
    cancellation while its worker still held it is the identical hazard, and no
    write case can see it.
    """

    name: str

    async def prepare(self, store: SourceGrantStore) -> None:
        """Establish anything the operation needs before it can run."""
        ...

    def first(self, store: SourceGrantStore) -> Coroutine[Any, Any, object]:
        """The call the case suspends inside the resource and then cancels."""
        ...

    def second(self, store: SourceGrantStore) -> Coroutine[Any, Any, object]:
        """The concurrent call barred from the resource until the first is done."""
        ...

    async def verify(self, store: SourceGrantStore) -> None:
        """Assert the resource survived: the second call is whole and reads work."""
        ...


class _RecordOp:
    """The append-only ``record`` path."""

    name = "record"

    async def prepare(self, store: SourceGrantStore) -> None:
        """No preconditions."""

    def first(self, store: SourceGrantStore) -> Coroutine[Any, Any, object]:
        """Record the grant whose write is cancelled."""
        return store.record(source_grant("cancel-a", grant_id="cancel-1"))

    def second(self, store: SourceGrantStore) -> Coroutine[Any, Any, object]:
        """Record an independent grant concurrently — a different source."""
        return store.record(source_grant("cancel-b", grant_id="cancel-2"))

    async def verify(self, store: SourceGrantStore) -> None:
        """The second record is durable; the first is absent-or-whole; reads work."""
        assert await store.live(source="cancel-b", use=GrantScope.FACET) is not None
        assert {held.id for held in await store.export()} >= {"cancel-2"}


class _ClearOp:
    """The ``clear`` write, with a recorded grant so it does real work."""

    name = "clear"

    async def prepare(self, store: SourceGrantStore) -> None:
        """A recorded grant for ``clear`` to remove."""
        await store.record(source_grant("seed", grant_id="seed-1"))

    def first(self, store: SourceGrantStore) -> Coroutine[Any, Any, object]:
        """Clear the store — the call that is cancelled."""
        return store.clear()

    def second(self, store: SourceGrantStore) -> Coroutine[Any, Any, object]:
        """Clear again concurrently."""
        return store.clear()

    async def verify(self, store: SourceGrantStore) -> None:
        """The store is empty and still serves reads."""
        assert await store.export() == []


class _ReadOp:
    """A locked read, driven against a store seeded the same way.

    The two calls are the *same* read against independent subjects, because what
    distinguishes a read op is its lock site and both calls have to enter it.
    Nothing is asserted about the cancelled read's answer — it has none, its task
    was cancelled — so :meth:`verify` pins the state the second call had to see,
    re-read once the scenario is over.
    """

    name = ""

    async def prepare(self, store: SourceGrantStore) -> None:
        """Seed a live grant on one source and a revoked one on another."""
        await store.record(source_grant("read-a", grant_id="read-a-1"))
        granted = source_grant("read-b", grant_id="read-b-1")
        await store.record(granted)
        await store.record(revocation_of(granted, grant_id="read-b-2"))

    def first(self, store: SourceGrantStore) -> Coroutine[Any, Any, object]:
        """The read the case suspends inside the resource and then cancels."""
        raise NotImplementedError

    def second(self, store: SourceGrantStore) -> Coroutine[Any, Any, object]:
        """The concurrent read barred from the resource until the first is done."""
        raise NotImplementedError

    async def verify(self, store: SourceGrantStore) -> None:
        """A read cancelled mid-flight leaves the store whole and still readable."""
        assert await store.live(source="read-a", use=GrantScope.FACET) is not None
        assert await store.live(source="read-b", use=GrantScope.FACET) is None
        assert {held.id for held in await store.export()} == {
            "read-a-1",
            "read-b-1",
            "read-b-2",
        }


class _LiveOp(_ReadOp):
    """``live`` — the one answer the gate rests on, under the lock."""

    name = "live"

    def first(self, store: SourceGrantStore) -> Coroutine[Any, Any, object]:
        """Look up the live source — the call that is cancelled."""
        return store.live(source="read-a", use=GrantScope.FACET)

    def second(self, store: SourceGrantStore) -> Coroutine[Any, Any, object]:
        """Look up the revoked one concurrently."""
        return store.live(source="read-b", use=GrantScope.FACET)


class _RecentOp(_ReadOp):
    """``recent`` — the bounded page, its own lock site."""

    name = "recent"

    def first(self, store: SourceGrantStore) -> Coroutine[Any, Any, object]:
        """Read the newest page — the call that is cancelled."""
        return store.recent(limit=2)

    def second(self, store: SourceGrantStore) -> Coroutine[Any, Any, object]:
        """Read a narrower page concurrently."""
        return store.recent(limit=1)


class _ExportOp(_ReadOp):
    """``export`` — the whole-history read, its own lock site."""

    name = "export"

    def first(self, store: SourceGrantStore) -> Coroutine[Any, Any, object]:
        """Export everything — the call that is cancelled."""
        return store.export()

    def second(self, store: SourceGrantStore) -> Coroutine[Any, Any, object]:
        """Export again concurrently."""
        return store.export()


#: Every ``SourceGrantStore`` operation ADR-0060's case is run against. Both
#: writes and all three reads, because ADR-0060 §3 binds any method that acquires
#: the resource rather than any method that mutates.
_CANCELLATION_OPS: tuple[Callable[[], _CancellationOp], ...] = (
    _RecordOp,
    _ClearOp,
    _LiveOp,
    _RecentOp,
    _ExportOp,
)


class SourceGrantsContract:
    """Behaviour every ``SourceGrants`` implementation must exhibit (ADR-0097 §10).

    The three clauses that bind the *narrow* seam, plus the two vacuity
    statements ``core/protocols.py`` makes about it. Every one of them binds a
    ``SourceGrantStore`` too, which is why :class:`SourceGrantStoreContract`
    inherits rather than repeats them.
    """

    @pytest.fixture
    def grants(self) -> SourceGrants:
        """Override in a subclass to supply the implementation under test.

        The subject must start **empty**: every case below arranges the history it
        is about through :meth:`given`, and a subject that arrived holding a grant
        would make the exact-match and scope cases assert against a state the case
        did not set up.
        """
        raise NotImplementedError

    async def given(self, grants: SourceGrants, *records: SourceGrant) -> None:
        """Override to make ``records`` part of the subject's history.

        The one thing a generic case cannot do for itself. ``SourceGrants`` has a
        single member and it is a query, so a suite for the narrow seam has no
        contract-level way to arrange the state it asserts about — which is
        exactly the property being tested and therefore not one to weaken by
        adding a write to the Protocol. A store implements this with ``record``; a
        query-only implementation implements it however it holds its answers.

        Records are applied **in order**, and an implementation must apply the
        same invariants a store's ``record`` does: a suite that could arrange two
        live grants for one source would be asserting about a state ADR-0097 §4
        says cannot exist.
        """
        raise NotImplementedError

    def test_conforms_to_protocol(self, grants: SourceGrants) -> None:
        assert isinstance(grants, SourceGrants)

    # --- the source is matched exactly (ADR-0097 §9) ------------------------

    @pytest.mark.parametrize(
        "queried",
        [
            pytest.param(f" {SOURCE} ", id="surrounding whitespace"),
            pytest.param(SOURCE.upper(), id="another case"),
            pytest.param(f"{SOURCE}-work", id="another source entirely"),
        ],
    )
    async def test_live_matches_the_source_exactly(
        self, grants: SourceGrants, queried: str
    ) -> None:
        """No strip, no case-fold, no normalising of any kind (ADR-0097 §9).

        Written as a suite clause because it is the one place a store could be
        "helpful" and change what a grant covers. The two directions are both
        wrong and both silent: a normalising store invents an identity rule
        nothing ratified, and the value it invents is the one thing standing
        between a configured reader and the user's personal files.

        The whitespace case is not hypothetical. ``SourceGrant.source`` is an
        ``Identifier``, which *strips*, while ``ReaderContract`` requires only
        that ``reader.name.strip()`` be non-empty — so ``" calendar "`` is a
        conforming declared name whose grant would be stored as ``"calendar"``.
        ADR-0097 §9 closes that at admission, by refusing to grant a
        non-canonically-named reader at all; this clause is what keeps the store
        from papering over it instead.
        """
        await self.given(grants, source_grant(SOURCE))

        assert await grants.live(source=queried, use=GrantScope.FACET) is None

    # --- a grant covers the uses it names, and no others (ADR-0097 §2) ------

    async def test_a_grant_covers_each_use_in_its_scope(self, grants: SourceGrants) -> None:
        """Every named use, not merely the first one a lookup happens to try.

        **The scope is built from the enum rather than enumerated**, so the case
        keeps asking about *every* use as ``GrantScope`` grows. Spelled as a pair
        it went stale the moment ADR-0133 added ``NOTIFY``: the loop below still
        walked all three members while the grant named two, so the case failed for
        naming the wrong scope rather than for anything an implementation did.
        """
        await self.given(grants, source_grant(SOURCE, scope=tuple(GrantScope)))

        for use in GrantScope:
            found = await grants.live(source=SOURCE, use=use)
            assert found is not None, use
            assert found.source == SOURCE
            assert use in found.scope

    async def test_a_grant_does_not_cover_a_use_outside_its_scope(
        self, grants: SourceGrants
    ) -> None:
        """ "A use a grant does not name is not authorised by it" (ADR-0097 §2).

        The whole content of scoping, and the half a store gets wrong by answering
        "is this source granted at all". "You may look at my calendar to answer
        what I am asking now, but do not remember it" is the sentence this clause
        makes true.
        """
        await self.given(grants, source_grant(SOURCE, scope=(GrantScope.FACET,)))

        assert await grants.live(source=SOURCE, use=GrantScope.FACET) is not None
        assert await grants.live(source=SOURCE, use=GrantScope.INGEST) is None

    async def test_notify_implies_no_other_use_and_no_other_use_implies_it(
        self, grants: SourceGrants
    ) -> None:
        """The third use is independent in **both** directions (ADR-0133 §2, §6).

        "``NOTIFY`` implies neither ``FACET`` nor ``INGEST``, and neither of them
        implies ``NOTIFY``… No implementation may infer one member from another,
        **rank** them, or treat any of them as a superset of another."

        The sibling case above already holds "a use a grant does not name is not
        authorised by it" over the original pair, and this one is asked for by
        ADR-0133 §6 by name because the tempting wrong implementations are on this
        member specifically. Reading ``NOTIFY`` as implied by ``INGEST`` is option
        B re-entering through the implementation door after being refused at the
        decision door (§3), and it would silently hand every existing grant a use
        its user was never asked about. The opposite error is subtler and worse for
        being generous-looking: treating ``NOTIFY`` as the widest member and so as
        covering the reads beneath it would let a grant that authorises no
        assembly-time read serve a ``ContextFacet``.

        Both are checked on a *live* grant rather than through construction,
        because it is ``live`` that every driver actually asks (ADR-0097 §5).
        """
        await self.given(grants, source_grant(SOURCE, scope=(GrantScope.NOTIFY,)))

        assert await grants.live(source=SOURCE, use=GrantScope.NOTIFY) is not None
        assert await grants.live(source=SOURCE, use=GrantScope.FACET) is None
        assert await grants.live(source=SOURCE, use=GrantScope.INGEST) is None

    async def test_neither_original_use_carries_notify_with_it(self, grants: SourceGrants) -> None:
        """The other half of ADR-0133 §2's independence, and §3's inertness.

        A store full of ``(FACET, INGEST)`` grants predates the member entirely,
        and ADR-0133 §3 rules that arrival changes none of them: "A grant recorded
        before ``NOTIFY`` existed names the uses it names, so it does not authorise
        ``NOTIFY``". That is the property that makes an append-only consent store
        worth having, and it is the one an implementation breaks by being helpful.

        Separated from the case above so a failure says *which* direction broke:
        one implementation infers upward from a narrow grant, another back-fills a
        wide one, and a single case asserting both would report either as the same
        defect.
        """
        await self.given(grants, source_grant(SOURCE, scope=(GrantScope.FACET, GrantScope.INGEST)))

        assert await grants.live(source=SOURCE, use=GrantScope.FACET) is not None
        assert await grants.live(source=SOURCE, use=GrantScope.INGEST) is not None
        assert await grants.live(source=SOURCE, use=GrantScope.NOTIFY) is None

    async def test_an_ungranted_source_reads_as_none(self, grants: SourceGrants) -> None:
        """``None`` is a clean answer about an empty history, not a failure.

        The state every deployment starts in under ADR-0097 §8, which mints no
        grant from configuration — so this is the answer a freshly-upgraded
        installation gets, and it must not look like a broken store.
        """
        assert await grants.live(source=SOURCE, use=GrantScope.INGEST) is None

    # --- the answer is detached (ADR-0097 §4) -------------------------------

    async def test_live_returns_a_detached_snapshot(self, grants: SourceGrants) -> None:
        """The gate must not be defeatable through its own answer (ADR-0097 §10).

        Bound on the **narrow** seam and not only on the store, which is where it
        would have been missed: ``live`` is the only member of ``SourceGrants``, so
        a query-only implementation handing back its own object would satisfy a
        detachment rule written over "queries on the store" while leaking the one
        value in the system that decides whether a source may be read.

        The concrete bypass is worth naming because ``frozen=True`` does not close
        it — it refuses ``grant.scope = …`` and not
        ``grant.__dict__["scope"] = …``. A caller granted ``FACET`` alone widens
        ``scope`` on the object ``live`` returned to include ``INGEST``, and the
        driver's next check authorises ingestion the user never granted.
        """
        await self.given(grants, source_grant(SOURCE, scope=(GrantScope.FACET,)))
        leaked = await grants.live(source=SOURCE, use=GrantScope.FACET)
        assert leaked is not None

        object.__setattr__(leaked, "scope", (GrantScope.FACET, GrantScope.INGEST))
        object.__setattr__(leaked, "source", "somewhere-else")

        assert await grants.live(source=SOURCE, use=GrantScope.INGEST) is None
        refetched = await grants.live(source=SOURCE, use=GrantScope.FACET)
        assert refetched is not None
        assert refetched.source == SOURCE
        assert refetched.scope == (GrantScope.FACET,)

    # --- input observation (ADR-0065) ---------------------------------------

    def test_live_takes_no_caller_owned_container(self, grants: SourceGrants) -> None:
        """The seam has no mutable input, and that is what discharges ADR-0065.

        ``core/protocols.py``'s input clause is about an argument the caller may
        still be holding and mutate mid-flight. ``live`` takes a ``str`` and an
        enum member — both immutable, neither a container — so the clause is
        **vacuous here and must stay that way**, which is a property of the
        signature and is therefore assertable. It is the same discharge
        ``ReaderContract`` makes when it asserts that ``read()`` takes no
        arguments at all: an obligation reported as held by a suite that could not
        see it is worse than no obligation.
        """
        assert set(inspect.signature(grants.live).parameters) == {"source", "use"}


class SourceGrantStoreContract(SourceGrantsContract):
    """Behaviour every ``SourceGrantStore`` implementation must exhibit (ADR-0097 §4).

    Inherits the narrow seam's clauses, because a store *is* the narrow seam plus
    the ability to write. The store is an **active participant** rather than a
    filing cabinet: it is append-only, it validates the revocation pointer it is
    handed, it refuses a second live grant for one source, and it detaches what it
    stores as well as what it returns. Each of those is a property two
    implementations could plausibly disagree on while both looking correct, which
    is what a shared suite is for.
    """

    @pytest.fixture
    def store(self) -> SourceGrantStore:
        """Return an empty store under test."""
        raise NotImplementedError

    @pytest.fixture
    def grants(self, store: SourceGrantStore) -> SourceGrants:
        """The same subject, seen through the narrow seam.

        Not a second object: the inherited clauses must bind *this* store, which
        is ADR-0097 §3's "one implementation satisfies both" being tested rather
        than asserted. A store that answered the narrow suite through a different
        instance would prove nothing about the one under test here.
        """
        return store

    async def given(self, grants: SourceGrants, *records: SourceGrant) -> None:
        """Arrange the inherited clauses' history through ``record`` itself.

        A store has a contract-level way to do this, so it uses it — which means
        the narrow clauses run against state the store's own write path produced,
        not against state a test reached in behind it.
        """
        assert isinstance(grants, SourceGrantStore)
        for record in records:
            await grants.record(record)

    # --- append-only, write-once (ADR-0097 §4) ------------------------------

    async def test_a_recorded_grant_is_returned_by_live_under_its_own_id(
        self, store: SourceGrantStore
    ) -> None:
        """``record`` returns the id, and the record is the one that comes back.

        The id is the **caller's**, minted before the call, as
        ``PermissionDecision.id`` is: a store neither mints ids nor reads a clock
        (ADR-0021 §3, kept by ADR-0097 §10).
        """
        granted = source_grant(SOURCE, grant_id="g-1")

        returned = await store.record(granted)

        assert returned == "g-1"
        found = await store.live(source=SOURCE, use=GrantScope.FACET)
        assert found == granted

    async def test_recording_a_known_id_is_refused_rather_than_upserted(
        self, store: SourceGrantStore
    ) -> None:
        """Write-once, deliberately unlike ``MemoryStore.add``.

        There the id is the caller's idempotency key and an upsert is right. A
        grant store that upserts is one where the record of what the user decided
        can be rewritten by replaying a write, which is the one property it exists
        to deny (ADR-0097 §4).
        """
        await store.record(source_grant(SOURCE, grant_id="g-1", scope=(GrantScope.FACET,)))

        await _refuses(store, source_grant("elsewhere", grant_id="g-1"))

        held = await store.live(source=SOURCE, use=GrantScope.FACET)
        assert held is not None
        assert held.scope == (GrantScope.FACET,)

    # --- at most one live grant per source (ADR-0097 §4) --------------------

    async def test_a_second_grant_for_a_source_with_a_live_one_is_refused(
        self, store: SourceGrantStore
    ) -> None:
        """One live grant per source at any instant.

        Without it a source accumulates overlapping authorisations and "what am I
        granting?" stops having one answer — and widening becomes a silent append
        rather than the revoke-then-grant pair ADR-0097 §2 requires, which is the
        pair that leaves both records on file.
        """
        await store.record(source_grant(SOURCE, grant_id="g-1", scope=(GrantScope.FACET,)))

        await _refuses(store, source_grant(SOURCE, grant_id="g-2"))

    async def test_after_a_revocation_a_new_grant_for_that_source_is_accepted(
        self, store: SourceGrantStore
    ) -> None:
        """Revoke-then-grant is how a scope changes, and it has to work.

        The other half of the clause above: if a revoked source stayed
        un-grantable the store would have converted "the user changed their mind"
        into a permanent refusal, which is the same lockout ADR-0097 §4 refuses on
        the timestamp.
        """
        granted = source_grant(SOURCE, grant_id="g-1", scope=(GrantScope.FACET,))
        await store.record(granted)
        await store.record(revocation_of(granted, grant_id="r-1"))

        assert await store.record(source_grant(SOURCE, grant_id="g-2")) == "g-2"
        assert await store.live(source=SOURCE, use=GrantScope.INGEST) is not None

    # --- revoking (ADR-0097 §4, §6) -----------------------------------------

    async def test_a_revoked_grant_stops_covering_every_use_and_is_still_on_file(
        self, store: SourceGrantStore
    ) -> None:
        """Revocation is prospective: it stops the reading and unwrites nothing.

        Both halves are the clause. ``live`` must go quiet for *every* use, not
        only the one a caller happens to ask about — a store that dropped one
        member of the scope would leave the source readable for the other. And the
        revoked grant must **stay**: were the record removed, ``reported_by`` on
        every belief from that source would point at a source with no
        authorisation on file at all, and every belief from it would read as
        unauthorised (ADR-0097 §6).
        """
        granted = source_grant(SOURCE, grant_id="g-1")
        await store.record(granted)
        await store.record(revocation_of(granted, grant_id="r-1"))

        for use in GrantScope:
            assert await store.live(source=SOURCE, use=use) is None, use
        assert {held.id for held in await store.recent()} == {"g-1", "r-1"}
        assert {held.id for held in await store.export()} == {"g-1", "r-1"}

    async def test_a_revocation_naming_nothing_recorded_is_refused(
        self, store: SourceGrantStore
    ) -> None:
        """A pointer at nothing withdraws nothing, and must not read as if it did."""
        orphan = revocation_of(source_grant(SOURCE, grant_id="g-nobody"), grant_id="r-1")

        await _refuses(store, orphan)

    async def test_a_revocation_of_an_already_revoked_grant_is_refused(
        self, store: SourceGrantStore
    ) -> None:
        """A grant is withdrawn once; a history saying otherwise says it twice."""
        granted = source_grant(SOURCE, grant_id="g-1")
        await store.record(granted)
        await store.record(revocation_of(granted, grant_id="r-1"))

        await _refuses(store, revocation_of(granted, grant_id="r-2"))

    async def test_a_revocation_of_a_revocation_is_refused(self, store: SourceGrantStore) -> None:
        """Only a granting record can be revoked, so the chain stays one link long.

        Otherwise "un-revoking" arrives through a back door: a revocation of a
        revocation would be a second act nobody designed, restoring an
        authorisation the user withdrew without the user granting anything.
        """
        granted = source_grant(SOURCE, grant_id="g-1")
        await store.record(granted)
        revocation = revocation_of(granted, grant_id="r-1")
        await store.record(revocation)

        await _refuses(store, revocation_of(revocation, grant_id="r-2"))

    async def test_a_revocation_naming_a_different_source_is_refused(
        self, store: SourceGrantStore
    ) -> None:
        """The transcription is verified, not trusted (ADR-0097 §4).

        A revoking record carries the ``source`` and ``scope`` of the grant it
        revokes so it says what was withdrawn without a join — ADR-0021 §1's
        reason for embedding a whole declaration rather than a name. A
        transcription nobody checks is a record that can lie about what it
        withdrew, in the one store whose value is that it says what happened.
        """
        granted = source_grant(SOURCE, grant_id="g-1")
        await store.record(granted)
        mistranscribed = SourceGrant(
            id="r-1",
            source="another-source",
            scope=granted.scope,
            decided_at=granted.decided_at,
            revokes="g-1",
        )

        await _refuses(store, mistranscribed)

    async def test_a_revocation_transcribing_a_different_scope_is_refused(
        self, store: SourceGrantStore
    ) -> None:
        """There is no partial revocation, and this is what makes that true.

        Accepting a narrower transcription would *be* partial revocation, arriving
        as a mistake rather than as a feature: the record would say the user
        withdrew ``INGEST`` while the store went on treating the whole grant as
        gone, or worse, kept it live (ADR-0097 §2).
        """
        granted = source_grant(SOURCE, grant_id="g-1", scope=(GrantScope.FACET, GrantScope.INGEST))
        await store.record(granted)
        narrowed = SourceGrant(
            id="r-1",
            source=granted.source,
            scope=(GrantScope.INGEST,),
            decided_at=granted.decided_at,
            revokes="g-1",
        )

        await _refuses(store, narrowed)

    async def test_a_revocation_timestamped_before_its_grant_is_accepted(
        self, store: SourceGrantStore
    ) -> None:
        """The inverse of the audit trail's ordering rule, and its own case.

        ``SqliteAuditTrail`` refuses a resolution "timestamped before the
        confirmation it answers", and a lane copying that shape gets this
        backwards. It is wrong here and the failure is the worst one available:
        ``decided_at`` is caller-supplied and the store reads no clock, so a host
        clock corrected backwards makes every truthfully-timestamped revocation
        refusable until wall-clock time catches up — and a large enough correction
        makes a grant **permanently unrevokable**, which is the one property this
        contract exists to deliver (ADR-0097 §4).

        Liveness is derived from ``revokes`` alone, so dropping the check removes a
        lockout and costs no property.
        """
        granted = source_grant(SOURCE, grant_id="g-1", decided_at=DEFAULT_DECIDED_AT)
        await store.record(granted)
        backdated = revocation_of(
            granted, grant_id="r-1", decided_at=DEFAULT_DECIDED_AT - timedelta(days=1)
        )

        assert await store.record(backdated) == "r-1"

        for use in GrantScope:
            assert await store.live(source=SOURCE, use=use) is None, use

    # --- atomicity (ADR-0097 §4) --------------------------------------------

    async def test_two_racing_grants_for_one_source_settle_it_once(
        self, store: SourceGrantStore
    ) -> None:
        """The one-live-grant guarantee must survive an interleaving.

        ``record`` is contracted as *atomic*: the duplicate check, the live-grant
        check, the revocation invariants and the append are one operation. Without
        that, two concurrent grants each observe none live, each append, and the
        source has two authorisations where the contract says one — the failure
        ADR-0014 §5 answered with compare-and-swap on ``PlanStore``. "The system
        composes on one event loop" is precisely the setting in which an ``await``
        between a check and a write is an interleaving point.
        """
        results = await asyncio.gather(
            store.record(source_grant(SOURCE, grant_id="g-1", scope=(GrantScope.FACET,))),
            store.record(source_grant(SOURCE, grant_id="g-2", scope=(GrantScope.INGEST,))),
            return_exceptions=True,
        )

        succeeded = [result for result in results if not isinstance(result, BaseException)]
        refused = [result for result in results if isinstance(result, InvalidGrantError)]
        assert len(succeeded) == 1, f"expected exactly one winner, got {results}"
        assert len(refused) == 1, f"the loser must be refused, got {results}"
        assert len(await store.export()) == 1

    async def test_two_racing_revocations_of_one_grant_settle_it_once(
        self, store: SourceGrantStore
    ) -> None:
        """The same atomicity on the other check, so neither half is untested."""
        granted = source_grant(SOURCE, grant_id="g-1")
        await store.record(granted)

        results = await asyncio.gather(
            store.record(revocation_of(granted, grant_id="r-1")),
            store.record(revocation_of(granted, grant_id="r-2")),
            return_exceptions=True,
        )

        succeeded = [result for result in results if not isinstance(result, BaseException)]
        refused = [result for result in results if isinstance(result, InvalidGrantError)]
        assert len(succeeded) == 1, f"expected exactly one winner, got {results}"
        assert len(refused) == 1, f"the loser must be refused, got {results}"

    # --- ordering and bounds -------------------------------------------------

    async def test_recent_is_newest_first_with_an_id_tie_break(
        self, store: SourceGrantStore
    ) -> None:
        """Both halves are needed for two stores to answer the same query alike.

        "Newest first" is ambiguous between insertion order and decision time,
        which disagree whenever records are appended out of order — so these are
        recorded in a deliberately different order than they were decided. The
        ``id`` tie-break makes the order *total*, since two records can share a
        timestamp at any clock resolution.

        Each is a grant for a *different* source, because one source may hold only
        one live grant at a time (ADR-0097 §4).
        """
        await store.record(
            source_grant(
                "s-old", grant_id="g-old", decided_at=DEFAULT_DECIDED_AT - timedelta(hours=1)
            )
        )
        await store.record(
            source_grant(
                "s-new", grant_id="g-new", decided_at=DEFAULT_DECIDED_AT + timedelta(hours=1)
            )
        )
        await store.record(source_grant("s-tie-b", grant_id="g-tie-b"))
        await store.record(source_grant("s-tie-a", grant_id="g-tie-a"))

        found = await store.recent()

        assert [each.id for each in found] == ["g-new", "g-tie-a", "g-tie-b", "g-old"]

    async def test_recent_returns_the_newest_within_the_limit(
        self, store: SourceGrantStore
    ) -> None:
        for index in range(5):
            await store.record(
                source_grant(
                    f"s-{index}",
                    grant_id=f"g-{index}",
                    decided_at=DEFAULT_DECIDED_AT + timedelta(minutes=index),
                )
            )

        found = await store.recent(limit=2)

        assert [each.id for each in found] == ["g-4", "g-3"]

    @pytest.mark.parametrize("limit", [0, -1])
    async def test_a_non_positive_limit_is_refused(
        self, store: SourceGrantStore, limit: int
    ) -> None:
        """Refused rather than clamped or passed through, because the leak is silent.

        A store issuing ``LIMIT ?`` against SQLite turns ``limit=-1`` into *no
        limit at all*, so the one call offering a bounded read of a Tier 1 store
        becomes the unbounded read it exists to avoid. Clamping is the other wrong
        answer: a caller that asked for something meaningless should learn that,
        not be served something it did not ask for.
        """
        await store.record(source_grant(SOURCE))

        with pytest.raises(ValueError, match="limit"):
            await store.recent(limit=limit)

    async def test_a_limit_wider_than_a_backing_store_can_bind_still_answers(
        self, store: SourceGrantStore
    ) -> None:
        """A bound above any possible row count means "all of them", not an error.

        ``limit`` is a Python ``int`` and has no width, so ``2**63`` is a
        perfectly valid strictly-positive request. Binding one that wide into
        SQLite raises ``OverflowError`` — neither ``ValueError`` nor
        ``GrantError``, so it leaves the seam's error boundary through a hole
        while every other clause here still passes.

        **A convention carried across rather than a decision made here.**
        ``SqliteAuditTrail.recent`` already clamps this exact boundary, and its
        own comment gives the reason it is not the ``limit=-1`` case: "a bound
        above any possible row count means 'all of them', which is what the query
        then returns", where clamping a negative limit "would have served
        something the caller did not ask for". The clause is written into *this*
        suite because ADR-0097 §10 puts the concrete store in a later lane, so
        this is the one member of the family where the behaviour can be pinned
        before an implementation exists rather than after. **#679** tracks its
        absence from the sibling suites, where the behaviour is implemented and
        nothing pins it.
        """
        await store.record(source_grant(SOURCE, grant_id="g-1"))

        assert [each.id for each in await store.recent(limit=2**63)] == ["g-1"]

    async def test_an_empty_store_answers_emptily(self, store: SourceGrantStore) -> None:
        assert await store.recent() == []
        assert await store.export() == []
        assert await store.live(source=SOURCE, use=GrantScope.FACET) is None

    # --- export and erasure --------------------------------------------------

    async def test_export_returns_every_record(self, store: SourceGrantStore) -> None:
        granted = source_grant(SOURCE, grant_id="g-1")
        await store.record(granted)
        await store.record(revocation_of(granted, grant_id="r-1"))
        await store.record(source_grant("other", grant_id="g-2"))

        exported = await store.export()

        assert {each.id for each in exported} == {"g-1", "r-1", "g-2"}

    async def test_an_exported_record_survives_a_json_round_trip(
        self, store: SourceGrantStore
    ) -> None:
        """Durability is what forces these records to be serialisable.

        And it is where ADR-0097 §10's choice of a ``tuple`` over a ``frozenset``
        earns itself: ADR-0087 fixes a canonical wire encoding and a set has no
        canonical order, so the scope's order has to survive the round trip or two
        implementations serialise one grant differently.
        """
        original = source_grant(SOURCE, grant_id="g-1", scope=(GrantScope.FACET, GrantScope.INGEST))
        await store.record(original)

        exported = (await store.export())[0]
        reloaded = SourceGrant.model_validate(exported.model_dump(mode="json"))

        assert reloaded == original
        assert reloaded.scope == (GrantScope.FACET, GrantScope.INGEST)

    async def test_clear_erases_everything_and_reports_how_much(
        self, store: SourceGrantStore
    ) -> None:
        """The user may burn the book; there is deliberately no way to tear out a page."""
        granted = source_grant(SOURCE, grant_id="g-1")
        await store.record(granted)
        await store.record(revocation_of(granted, grant_id="r-1"))

        removed = await store.clear()

        assert removed == 2
        assert await store.recent() == []
        assert await store.live(source=SOURCE, use=GrantScope.FACET) is None

    # --- the store owns what it holds (ADR-0097 §4) --------------------------

    @pytest.mark.parametrize(
        ("attribute", "value"),
        [
            pytest.param("decided_at", datetime(2026, 7, 20, 12, 0), id="naive-timestamp"),  # noqa: DTZ001
            pytest.param("scope", (), id="emptied-scope"),
            pytest.param("scope", (GrantScope.FACET, GrantScope.FACET), id="duplicated-scope"),
            pytest.param("id", "", id="blank-identifier"),
        ],
    )
    async def test_a_corrupted_grant_is_refused_rather_than_stored(
        self, store: SourceGrantStore, attribute: str, value: object
    ) -> None:
        """ADR-0097 §4 asks for a *validated* snapshot, not merely a detached one.

        Detachment alone copies without checking, so an implementation that only
        deep-copies conforms to every other clause here and still accepts a record
        corrupted past its frozen model's guard. Two cases are sharp for different
        reasons. A naive ``decided_at`` makes ``recent`` raise on comparing it
        against the aware values beside it — a store that can be put into a state
        where reads crash has stopped being readable, which is worse than refusing
        the write. And an **emptied scope** authorises nothing while still
        occupying the source's one live-grant slot, so the real grant could not be
        recorded until this one was revoked.

        **The refusal is an ``InvalidGrantError`` specifically**, not the
        ``GrantError`` base. This is where the grant errors part company with
        ``AuditError``'s family, whose contract suite asserts the base: there the
        base *is* the refusal ("a write to the trail was refused"), while here the
        base is the **store fault** and only the subclass says "your record was
        refused" (ADR-0097 §10). Asserting the base would let an implementation
        collapse the two, and a caller would then be unable to tell a bad record
        from a broken store — which is the very distinction §5a keeps alive when it
        has a driver fail closed on one and refuse on the other.
        """
        await store.record(source_grant("other", grant_id="g-1"))
        corrupted = source_grant(SOURCE, grant_id="g-2")
        object.__setattr__(corrupted, attribute, value)

        with pytest.raises(InvalidGrantError):
            await store.record(corrupted)

        assert [held.id for held in await store.export()] == ["g-1"]

    async def test_the_stored_snapshot_is_detached_from_the_caller(
        self, store: SourceGrantStore
    ) -> None:
        """The write-path half of the rule, and the half that is easy to drop.

        "Detachment on queries alone closes the door and leaves the window open"
        (ADR-0021 §4). A store retaining the caller's object would let
        ``grant.__dict__["scope"] = …`` rewrite an appended record after the fact,
        through a store whose entire premise is that its records are not
        rewritten — and ``frozen=True`` does not stop that.

        All three fields a caller could move are rewritten here. ``scope`` is the
        one that matters most: widening it after the fact would authorise a use
        the user never granted, with the store's own history saying they did.
        """
        held = source_grant(SOURCE, grant_id="g-1", scope=(GrantScope.FACET,))
        await store.record(held)

        object.__setattr__(held, "scope", (GrantScope.FACET, GrantScope.INGEST))
        object.__setattr__(held, "source", "somewhere-else")
        object.__setattr__(held, "revokes", "g-nobody")

        assert await store.live(source=SOURCE, use=GrantScope.INGEST) is None
        stored = await store.live(source=SOURCE, use=GrantScope.FACET)
        assert stored is not None
        assert stored.scope == (GrantScope.FACET,)
        assert stored.source == SOURCE
        assert stored.revokes is None
        assert [each.id for each in await store.export()] == ["g-1"]

    async def test_detachment_survives_a_caller_supplied_subclass(
        self, store: SourceGrantStore
    ) -> None:
        """A caller's subclass may not become the object the store hands back.

        ``SourceGrant`` is a plain model, so a caller can subclass it and override
        ``model_copy`` to return ``self``. A store that snapshotted through
        ``type(grant)`` would then hold that instance and return it from every
        read, so the detachment above would stop holding without any of its own
        assertions changing — the caller keeps a live handle on an append-only
        record.

        The obligation is therefore on the *declared* type: what the store keeps
        and returns is a ``SourceGrant``, whatever it was handed.

        **``model_dump`` is the second overridable route and the sharper one**, so
        the subject here lies through both. ``model_copy`` returning ``self`` costs
        detachment; a ``model_dump`` that does not describe its own instance costs
        *fidelity* — a store that snapshots through it appends a **wider grant than
        the one it was handed**, here a ``FACET``-only record stored as covering
        ``INGEST`` too, and the driver's next check authorises a use the user never
        granted. That is not the caller-falsifies-its-own-record case ADR-0018 §3
        puts outside a store's reach: the object presented is a valid narrow grant
        and the record kept is a different one, which is what "stores a detached,
        validated snapshot" of it denies (ADR-0097 §4). Rebuilding from the
        instance's own field state rather than from a dispatched method is what
        closes it, and it costs any implementation one line.
        """

        class _Sticky(SourceGrant):
            def model_copy(self, **kwargs: object) -> _Sticky:
                return self

            def model_dump(self, **kwargs: object) -> dict[str, object]:
                return {
                    "id": self.id,
                    "source": self.source,
                    "scope": (GrantScope.FACET, GrantScope.INGEST),
                    "decided_at": self.decided_at,
                    "revokes": self.revokes,
                }

        original = source_grant(SOURCE, grant_id="g-1", scope=(GrantScope.FACET,))
        sticky = _Sticky.model_construct(**dict(original))
        await store.record(sticky)

        assert await store.live(source=SOURCE, use=GrantScope.INGEST) is None, (
            "the store kept a wider grant than the record it was handed"
        )
        stored = await store.live(source=SOURCE, use=GrantScope.FACET)
        assert stored is not None
        object.__setattr__(stored, "scope", (GrantScope.FACET, GrantScope.INGEST))

        reread = await store.live(source=SOURCE, use=GrantScope.FACET)
        assert reread is not None
        assert reread.scope == (GrantScope.FACET,)

    async def test_a_returned_list_is_a_detached_snapshot(self, store: SourceGrantStore) -> None:
        """``recent`` and ``export`` return ``list``, and a list is mutable."""
        await store.record(source_grant(SOURCE, grant_id="g-1"))

        (await store.recent()).clear()
        (await store.export()).clear()

        assert [each.id for each in await store.recent()] == ["g-1"]

    @pytest.mark.parametrize("query", ["live", "recent", "export"])
    async def test_every_query_returns_a_detached_record(
        self, store: SourceGrantStore, query: str
    ) -> None:
        """ADR-0018 §3's rule applied to a third store, on every read it offers.

        A caller holding a store's own object could rewrite the record of what was
        granted; the narrow suite pins it for ``live`` because that is the answer
        the gate rests on, and this pins it for the other two, which are what a
        user is shown and what they export.
        """
        await store.record(source_grant(SOURCE, grant_id="g-1", scope=(GrantScope.FACET,)))

        async def fetch() -> SourceGrant:
            if query == "live":
                one = await store.live(source=SOURCE, use=GrantScope.FACET)
                assert one is not None
                return one
            if query == "recent":
                return (await store.recent())[0]
            return (await store.export())[0]

        leaked = await fetch()
        object.__setattr__(leaked, "scope", (GrantScope.INGEST,))
        object.__setattr__(leaked, "revokes", "g-nobody")

        refetched = await fetch()
        assert refetched.scope == (GrantScope.FACET,)
        assert refetched.revokes is None

    # --- cancellation (ADR-0060) ---------------------------------------------

    #: Whether this implementation acquires nothing whose safety outlives the
    #: coroutine — no connection, lock, spawned task, file handle or transaction
    #: that a ``CancelledError`` could unwind past. ``core.protocols``' clause is
    #: then vacuously satisfied and there is nothing for the case below to
    #: observe. Left ``False``, the suite requires the implementation to prove the
    #: invariant by overriding :meth:`store_suspended_mid_write` — so a durable
    #: backend that reintroduces ADR-0054's bug fails here rather than passing a
    #: suite that never looked. Opting out is a visible declaration in the
    #: subclass, exactly as it is for ``AuditTrailContract``.
    acquires_no_shared_resource: bool = False

    #: Operations this implementation acquires no coroutine-outliving resource
    #: for, even though others do — the per-operation form of
    #: :attr:`acquires_no_shared_resource`, for a subject that takes the lock on
    #: some operations but not another. Empty by default: an implementation whose
    #: every operation is resource-backed proves them all.
    operations_without_shared_resource: frozenset[str] = frozenset()

    def store_suspended_mid_write(
        self,
    ) -> AbstractAsyncContextManager[SuspendedMidWrite[SourceGrantStore]]:
        """Supply a store whose named operation can be stopped *inside* its resource.

        Override unless :attr:`acquires_no_shared_resource` is set. The suite
        cancels the call while it is suspended and then watches what a second
        caller can reach, which is the only way to tell the fixed code from the
        broken code: pre-ADR-0054 the audit trail raised ``CancelledError``
        correctly and released the connection anyway, so a case that asserts only
        propagation certifies the bug (ADR-0060 §3).

        The returned :class:`SuspendedMidWrite` carries the store, its
        ``ResourceLog``, and an ``arm(operation)`` lever the case calls — *after*
        its preconditions, so a fake arming one modelled resource suspends the
        operation under test rather than a setup write. Every distinct lock site
        is a separate place the same regression can reappear, the locked *reads*
        included since ADR-0060 §3 binds any method that acquires the resource, so
        the case is run against each.
        """
        raise NotImplementedError

    @pytest.mark.optional_obligation
    @pytest.mark.parametrize("make_op", _CANCELLATION_OPS, ids=lambda op: op().name)
    async def test_a_cancelled_operation_holds_its_resource_until_the_work_finishes(
        self, make_op: Callable[[], _CancellationOp]
    ) -> None:
        """``core.protocols``' cancellation clause, on every operation (ADR-0060).

        A cancelled call must not hand the resource to the next caller while the
        work it started is still using it. The second call is what makes this a
        test of the invariant rather than of propagation: a single cancelled call
        in isolation looks identical either way. Run once per operation, so a
        regression reintroduced at any one lock site — not just ``record`` — is
        caught.

        The cancelled write's *effect* is deliberately not asserted (each op's
        ``verify`` pins only what a caller may rely on). The clause's third
        paragraph makes it indeterminate to the caller, so the two calls are
        independent subjects and what is pinned is that the second is whole and
        the store still serves reads. That an append-only store may hold a record
        whose caller was cancelled is not a gap: the guarantee is that nothing
        recorded is rewritten.
        """
        if self.acquires_no_shared_resource:
            pytest.skip("implementation acquires nothing whose safety outlives the coroutine")

        op = make_op()
        if op.name in self.operations_without_shared_resource:
            pytest.skip(f"{op.name} acquires nothing whose safety outlives the coroutine")

        async with self.store_suspended_mid_write() as harness:
            store = harness.store
            await op.prepare(store)
            suspended = harness.arm(op.name)
            visited_before = harness.log.visits

            first = asyncio.ensure_future(op.first(store))
            second: asyncio.Task[object] | None = None
            try:
                await suspended.reached()
                first.cancel()
                await settle()

                second = asyncio.ensure_future(op.second(store))
                await settle()
                assert not second.done(), _RELEASED_EARLY

                # Again, because deferring one cancellation is not the contract:
                # a second delivered while the deferred wait runs must not escape
                # and unwind out of the resource either.
                first.cancel()
                await settle()
                assert not second.done(), _RELEASED_EARLY
            finally:
                suspended.release()

            with pytest.raises(asyncio.CancelledError):
                await first
            assert second is not None
            await second

            # Decisive where the blocked-caller check above is not: the two calls
            # were never inside the resource at the same time. A delta, because a
            # fake's preconditions pass through the same logged resource.
            assert not harness.log.overlapped, _RELEASED_EARLY
            assert harness.log.visits - visited_before == 2, (
                "both calls should have reached the resource by now"
            )

            await op.verify(store)
