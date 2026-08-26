"""Shared conformance suites for the three recipient-grant Protocols (ADR-0193 §14).

Every ``RecipientGrants`` implementation must pass :class:`RecipientGrantsContract`,
every ``RecipientGrantResolution`` must pass
:class:`RecipientGrantResolutionContract`, and every ``RecipientGrantStore`` must
pass :class:`RecipientGrantStoreContract` — which inherits both, because a store
**is** the two narrow seams plus the ability to write. A concrete test subclasses
one of them and supplies its subject fixture.

**Here rather than under ``tests/core/``.** The corpus puts a suite beside the
subsystem that implements it, and ADR-0193 §1 puts every implementation in
``permissions/`` — ``audit_trail_contract.py``, ``action_policy_contract.py`` and
``source_grant_contract.py`` are already here for the same reason. The Protocols
themselves stay in ``core``, which is what lets a policy and a trail hold their
own narrow faces by injection without either importing ``permissions``.

**Three suites, and the cost is named rather than discovered.** One Protocol would
have cost one suite; the split costs three, and it buys the property that a policy
**cannot name** ``record`` or ``outstanding`` and a trail cannot name ``record`` or
``covering`` — ADR-0193 §1's central clause held by ``mypy --strict`` instead of by
review. Part of the cost comes back as evidence: the two narrow suites are bound
against the **store** fake as well as against their own, so "one concrete store
satisfies all three faces" is a test rather than an assertion.

**What is deliberately not in here**, restated so its absence does not read as
absence from the contract. The test is whether a clause is decidable from the
store's own surface:

* **ADR-0193 §4's origin bar and §7's lookup discipline.** Obligations on
  ``ActionPolicy``, not on a store — ``covering`` does not read
  ``planned_with_external_content`` at all, and no store exhibits how often a
  policy calls it. They are ``tests/permissions/test_action_policy.py``'s.
* **§6's eight checks.** Obligations on ``AuditTrail.record``; a store exhibits
  none of them. They are ``audit_trail_contract.py``'s, which is why that suite
  gains a factory taking a resolution seam.
* **§2's establishing act.** A pure constructor on the record, tested in
  ``tests/core/test_recipient_grant.py`` where it lives.
* **ADR-0060's cancellation matrix.** Not among §14's clauses, and the
  implementations inherit the SQLite family's own ``_run_to_completion``; filed
  rather than half-built here.

Named ``*_contract`` (not ``test_*``) so pytest collects it only via a
``Test``-prefixed subclass, never the abstract bases directly.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import TYPE_CHECKING

import pytest
from recipient_builders import (
    ACCOUNT,
    ALICE,
    AT,
    BOB,
    EXPIRES,
    OTHER_ACCOUNT,
    SHARED_CLOCK,
    TOOL,
    MovableClock,
    account_member,
    binding,
    member,
    request,
)

from ai_assistant.core.errors import InvalidRecipientGrantError, RecipientGrantError
from ai_assistant.core.protocols import (
    RecipientGrantResolution,
    RecipientGrants,
    RecipientGrantStore,
)
from ai_assistant.core.types import CanonicalDestination, DestinationProtocol
from ai_assistant.testing.recipient_grants import (
    recipient_grant,
    recipient_revocation_of,
)

if TYPE_CHECKING:
    from ai_assistant.core.types import RecipientGrant

#: The ceiling every store the suite builds starts at. Small enough that the
#: count cases can reach it with a handful of records and large enough that no
#: case *not* about the ceiling ever brushes it.
CEILING = 4


async def _refuses(
    store: RecipientGrantStore,
    rejected: RecipientGrant,
    error: type[RecipientGrantError] = InvalidRecipientGrantError,
) -> None:
    """Assert ``record`` refuses ``rejected`` **and writes nothing**.

    ADR-0193 §1 makes ``record`` atomic — the duplicate-id check, the
    duplicate-subject refusal, the ceiling count, the revocation invariants and
    the append are one operation — so a refusal is not a partial write with an
    exception on top. Asserting only that it raised would accept a store that
    appended a bad record and *then* rejected it, leaving a history the contract
    says is unrecordable and, for a revocation, a grant spent.

    The whole store is compared rather than just the rejected id, because a write
    that landed under a different id, or that mutated the record it named on its
    way through, is the same failure wearing a disguise.
    """
    before = await store.export()

    with pytest.raises(error):
        await store.record(rejected)

    assert await store.export() == before, "a refused write must leave no trace"


class RecipientGrantsContract:
    """Behaviour every ``RecipientGrants`` implementation must exhibit (ADR-0193 §3).

    Four of ADR-0193 §3's five comparisons, the precedence rule that makes the
    answer single-valued, the liveness interval, the single clock reading, and
    detachment. The fifth comparison is the policy's and is not stated here
    (ADR-0193 §1's clause about ``covering`` not reading the origin fact).

    Every clause binds a ``RecipientGrantStore`` too, which is why
    :class:`RecipientGrantStoreContract` inherits rather than repeats them.
    """

    @pytest.fixture(autouse=True)
    def clock(self) -> MovableClock:
        """The clock the subject evaluates liveness against, reset for this case.

        **Autouse**, and that is load-bearing rather than convenience: the reset is
        what makes one shared object behave per-case, and a case that did not
        request the clock would otherwise inherit whatever the last liveness case
        left it reading. Autouse also puts the reset before the subject fixture,
        which no longer depends on it.

        Concrete rather than abstract: a suite that let each implementation bring
        its own clock could not state the interval boundary at all, and every
        liveness case would be racing the suite's own runtime instead of asserting
        a comparison.

        It is :data:`~recipient_builders.SHARED_CLOCK` rather than a fresh object,
        and that constant carries the reason: a subject fixture that took *this*
        fixture could not be evaluated by ``tests/core/test_protocol_triad.py``,
        so the canonical fakes would go unbound. Resetting here is what makes one
        object behave per-case.
        """
        return SHARED_CLOCK.reset()

    @pytest.fixture
    def grants(self, clock: MovableClock) -> RecipientGrants:
        """Override in a subclass to supply the implementation under test.

        The subject must start **empty**: every case below arranges the history it
        is about through :meth:`given`, and a subject that arrived holding a grant
        would make the coverage cases assert against a state the case did not set
        up.
        """
        raise NotImplementedError

    async def given(self, grants: RecipientGrants, *records: RecipientGrant) -> None:
        """Override to make ``records`` part of the subject's history.

        The one thing a generic case cannot do for itself. ``RecipientGrants`` has
        a single member and it is a query, so a suite for the narrow seam has no
        contract-level way to arrange the state it asserts about — which is
        exactly the property being tested and therefore not one to weaken by
        adding a write to the Protocol.

        Records are applied **in order**, and an implementation must apply the
        same invariants a store's ``record`` does: a suite that could arrange two
        identical outstanding grants would be asserting about a state ADR-0193 §1
        says cannot exist.
        """
        raise NotImplementedError

    def test_conforms_to_the_query_protocol(self, grants: RecipientGrants) -> None:
        assert isinstance(grants, RecipientGrants)

    # --- §3: the four comparisons covering makes ---------------------------

    async def test_a_grant_covers_a_request_whose_recipients_it_names(
        self, grants: RecipientGrants
    ) -> None:
        """The record rather than a boolean, so the caller can name what authorised."""
        granted = recipient_grant(member(ALICE), grant_id="g-1")
        await self.given(grants, granted)

        found = await grants.covering(request(binding(ALICE)))

        assert found == granted

    async def test_a_grant_covers_a_subset_of_the_recipients_it_names(
        self, grants: RecipientGrants
    ) -> None:
        """Containment, not equality: a grant over two covers a call to one."""
        await self.given(grants, recipient_grant(member(ALICE), member(BOB), grant_id="g-1"))

        found = await grants.covering(request(binding(ALICE)))

        assert found is not None
        assert found.id == "g-1"

    async def test_a_grant_covers_nothing_where_one_recipient_is_outside_it(
        self, grants: RecipientGrants
    ) -> None:
        """Every member, or none of the call (ADR-0193 §3, §8).

        A partially covered set is not ``ALLOW``ed on route (b), and the half of
        that the *store* owns is that ``covering`` answers ``None`` rather than
        returning a grant the policy would then have to narrow the call against.
        """
        await self.given(grants, recipient_grant(member(ALICE), grant_id="g-1"))

        assert await grants.covering(request(binding(ALICE, BOB))) is None

    async def test_a_request_carrying_no_binding_is_answered_none(
        self, grants: RecipientGrants
    ) -> None:
        """A request with no ``egress_binding`` is not an egress call (ADR-0193 §1)."""
        await self.given(grants, recipient_grant(member(ALICE), grant_id="g-1"))

        assert (
            await grants.covering(
                request(binding(ALICE)).model_copy(update={"egress_binding": None})
            )
            is None
        )

    async def test_a_grant_covers_nothing_under_a_different_declaration(
        self, grants: RecipientGrants
    ) -> None:
        """By value alone: the same identifier, the same capability, one reworded line.

        An implementation comparing only ``tool.id`` passes every account,
        destination, liveness and precedence case in this suite, returns a grant
        after the declaration it was established about has changed, and produces
        the ``ALLOW`` where ADR-0193 §3 requires a ``CONFIRM``. Only
        ``AuditTrail.record`` would then catch it, and it would catch it *after*
        the ruling — so §1's whole "embedded by value, and a declaration edit
        re-prompts" argument would rest on a comparison no test reached.
        """
        reworded = TOOL.model_copy(update={"description": "Send an email, politely."})
        await self.given(grants, recipient_grant(member(ALICE), grant_id="g-1", tool=reworded))

        assert await grants.covering(request(binding(ALICE), tool=TOOL)) is None

    async def test_a_grant_covers_nothing_through_a_different_connected_account(
        self, grants: RecipientGrants
    ) -> None:
        """Two facts, identity **and** connection reference, and never one.

        The pair differs in the reference alone and shares an identity, so a store
        comparing identity alone fails here rather than passing on a fixture where
        the two differ in both — which is the shape ``BoundAccount``'s own
        declaration says "a standing grant would cover a record the user never
        granted" about.
        """
        await self.given(grants, recipient_grant(member(ALICE), grant_id="g-1", account=ACCOUNT))

        found = await grants.covering(request(binding(ALICE, account=OTHER_ACCOUNT)))

        assert found is None

    # --- §3's third clause: the account member -----------------------------

    async def test_an_account_only_grant_covers_a_call_selecting_no_recipient(
        self, grants: RecipientGrants
    ) -> None:
        """ADR-0148 §2's third clause: the derived set is the account itself."""
        granted = recipient_grant(account_member(), grant_id="g-1")
        await self.given(grants, granted)

        found = await grants.covering(request(binding()))

        assert found == granted

    async def test_an_account_only_grant_covers_no_selected_recipient(
        self, grants: RecipientGrants
    ) -> None:
        """And the strings are chosen to **coincide** (ADR-0193 §3, §14).

        The recipient's canonical form is the account's own identity, so an
        implementation that flattened both arms of
        :class:`~ai_assistant.core.types.CanonicalDestination` to an identity or to
        canonical text answers ``True`` here — while authorising a send to a
        recipient the user never named. Nothing else in this suite reaches that.
        """
        await self.given(grants, recipient_grant(account_member(), grant_id="g-1"))

        found = await grants.covering(request(binding(ACCOUNT.identity)))

        assert found is None

    # --- §1, §9: liveness ---------------------------------------------------

    async def test_a_revoked_grant_covers_nothing(self, grants: RecipientGrants) -> None:
        """Liveness's clock-free half: a fact about two records."""
        granted = recipient_grant(member(ALICE), grant_id="g-1")
        await self.given(grants, granted, recipient_revocation_of(granted, grant_id="r-1"))

        assert await grants.covering(request(binding(ALICE))) is None

    async def test_a_grant_covers_nothing_at_and_after_its_expiry(
        self, grants: RecipientGrants, clock: MovableClock
    ) -> None:
        """The interval is open above: live **strictly before** ``expires_at``."""
        await self.given(grants, recipient_grant(member(ALICE), grant_id="g-1"))

        clock.set(EXPIRES)
        assert await grants.covering(request(binding(ALICE))) is None

        clock.set(EXPIRES + timedelta(days=365))
        assert await grants.covering(request(binding(ALICE))) is None

    async def test_a_grant_covers_normally_an_instant_before_its_expiry(
        self, grants: RecipientGrants, clock: MovableClock
    ) -> None:
        """The other side of the same boundary, so the pair is about the comparison."""
        await self.given(grants, recipient_grant(member(ALICE), grant_id="g-1"))

        clock.set(EXPIRES - timedelta(microseconds=1))

        assert await grants.covering(request(binding(ALICE))) is not None

    async def test_a_future_dated_grant_covers_nothing(
        self, grants: RecipientGrants, clock: MovableClock
    ) -> None:
        """Liveness is bounded **below** as well as above (ADR-0193 §1, §9).

        Without this half the two seams disagree: the store would call a
        future-dated grant live, the policy would author an ``ALLOW`` on it, and
        ``AuditTrail.record`` would refuse that ``ALLOW`` because the grant
        post-dates the decision. Adversarial review found exactly that at round 15
        of ADR-0193's own loop, and the repair is here rather than at ``record``,
        because a rule the store applies is one the policy cannot skip. Instants
        are caller-supplied and a host clock can be corrected backwards, so this is
        a state a store can genuinely hold.
        """
        await self.given(grants, recipient_grant(member(ALICE), grant_id="g-1"))

        clock.set(AT - timedelta(seconds=1))

        assert await grants.covering(request(binding(ALICE))) is None

    async def test_a_grant_decided_at_this_instant_covers_normally(
        self, grants: RecipientGrants, clock: MovableClock
    ) -> None:
        """The interval is **closed** below, and this is the case that says so.

        An implementation reaching for ``decided_at < now`` by symmetry with the
        open upper end passes the future-dated, ordinary-live and expiry cases
        above while excluding a grant established and spent in one coarse-clock
        instant — which ADR-0021 §4 already contemplates and which is an ordinary
        thing rather than a suspicious one.
        """
        await self.given(grants, recipient_grant(member(ALICE), grant_id="g-1"))

        clock.set(AT)

        assert await grants.covering(request(binding(ALICE))) is not None

    # --- §1: precedence is total -------------------------------------------

    async def test_the_latest_decided_covering_grant_wins(self, grants: RecipientGrants) -> None:
        """Overlapping grants are permitted, so the selection must be total.

        A grant over ``{Alice}`` and one over ``{Alice, Bob}`` are two things a
        user may reasonably have said; without a rule, two conforming stores record
        different ``authorised_by`` values for one state and one request. A store
        returning the first match it finds passes every other case in this suite.
        """
        await self.given(
            grants,
            recipient_grant(member(ALICE), member(BOB), grant_id="g-older", decided_at=AT),
            recipient_grant(
                member(ALICE),
                grant_id="g-newer",
                decided_at=AT + timedelta(hours=1),
            ),
        )

        found = await grants.covering(request(binding(ALICE)))

        assert found is not None
        assert found.id == "g-newer"

    async def test_the_least_id_breaks_a_tie_on_decided_at(self, grants: RecipientGrants) -> None:
        """The tie-break is what makes the order total rather than mostly determined.

        Recorded in **descending** id order, so a store answering in insertion
        order returns the wrong one.
        """
        await self.given(
            grants,
            recipient_grant(member(ALICE), member(BOB), grant_id="g-b", decided_at=AT),
            recipient_grant(member(ALICE), grant_id="g-a", decided_at=AT),
        )

        found = await grants.covering(request(binding(ALICE)))

        assert found is not None
        assert found.id == "g-a"

    # --- §9: one clock reading per liveness-evaluating query ---------------

    async def test_covering_reads_the_clock_exactly_once(
        self, grants: RecipientGrants, clock: MovableClock
    ) -> None:
        """A per-row reading could return an answer valid at no real instant (§9).

        The clock advances a **day** at every reading, so any record a second
        reading measured would be far outside every interval this suite describes;
        the count is asserted beside the answer because ``covering`` returns one
        record and no list-shaped assertion can reach the clause.
        """
        await self.given(
            grants,
            recipient_grant(member(ALICE), member(BOB), grant_id="g-older", decided_at=AT),
            recipient_grant(member(ALICE), grant_id="g-newer", decided_at=AT + timedelta(hours=1)),
        )
        clock.advance_by()

        found = await grants.covering(request(binding(ALICE)))

        assert clock.readings == 1
        assert found is not None
        assert found.id == "g-newer"

    # --- §1: the answer is a detached snapshot ------------------------------

    async def test_a_returned_grant_is_detached_from_the_store(
        self, grants: RecipientGrants
    ) -> None:
        """``frozen=True`` does not close the bypass (ADR-0193 §1).

        A caller can write past a frozen model through ``__dict__``, and a store
        handing back its own object would let a grant be **widened after it was
        read** — the gate defeated through its own answer.

        **Both levels**, because §1 says "the list, the records in it, and
        everything mutable those reach": rewriting the recipient *inside* the
        returned destination reaches the same widening through a snapshot that
        detached only its root.
        """
        await self.given(grants, recipient_grant(member(ALICE), grant_id="g-1"))
        found = await grants.covering(request(binding(ALICE)))
        assert found is not None

        found.__dict__["destinations"] = (member(ALICE), member(BOB))
        found.destinations[0].__dict__["canonical"] = BOB

        again = await grants.covering(request(binding(ALICE)))
        assert again is not None
        assert again.destinations == (member(ALICE),)


class RecipientGrantResolutionContract:
    """Behaviour every ``RecipientGrantResolution`` must exhibit (ADR-0193 §1, §6).

    One member, and it answers one question: the **granting** record with this id,
    if the store holds it and no revoking record names it. Everything worth
    getting wrong about it is a boundary — a revoking record's own id, a revoked
    grant, and an **expired but unrevoked** one, which this member returns rather
    than withholding because expiry is not its question.
    """

    @pytest.fixture
    def resolution(self) -> RecipientGrantResolution:
        """Override in a subclass to supply the implementation under test, empty."""
        raise NotImplementedError

    async def held(self, resolution: RecipientGrantResolution, *records: RecipientGrant) -> None:
        """Override to make ``records`` part of the subject's history, in order."""
        raise NotImplementedError

    def test_conforms_to_the_resolution_protocol(
        self, resolution: RecipientGrantResolution
    ) -> None:
        assert isinstance(resolution, RecipientGrantResolution)

    async def test_outstanding_returns_a_granting_record_nothing_revokes(
        self, resolution: RecipientGrantResolution
    ) -> None:
        """Existence, kind and unrevokedness in one answer (ADR-0193 §1)."""
        granted = recipient_grant(member(ALICE), grant_id="g-1")
        await self.held(resolution, granted)

        assert await resolution.outstanding("g-1") == granted

    async def test_outstanding_answers_none_for_an_absent_id(
        self, resolution: RecipientGrantResolution
    ) -> None:
        """``None`` means exactly that, and never that the store could not be read."""
        assert await resolution.outstanding("g-missing") is None

    async def test_outstanding_answers_none_for_a_revoking_records_own_id(
        self, resolution: RecipientGrantResolution
    ) -> None:
        """A revoking record is never a valid ``authorised_by`` (ADR-0193 §9).

        It is never live, never returned by ``covering`` or ``standing``, and
        appears in ``recent`` and ``export`` as the record of an act — which is
        what it is. A store answering with it here would let a row rest on a
        revocation.
        """
        granted = recipient_grant(member(ALICE), grant_id="g-1")
        await self.held(resolution, granted, recipient_revocation_of(granted, grant_id="r-1"))

        assert await resolution.outstanding("r-1") is None

    async def test_outstanding_answers_none_for_a_revoked_grant(
        self, resolution: RecipientGrantResolution
    ) -> None:
        """Revocation is prospective and it **bites twice** (ADR-0193 §9).

        It governs every ``covering`` read that begins after it is recorded, and it
        refuses the write of any route-(b) ``ALLOW`` whose resolution read begins
        after it — which is this answer, and is the fail-closed direction a user
        who revokes expects.
        """
        granted = recipient_grant(member(ALICE), grant_id="g-1")
        await self.held(resolution, granted, recipient_revocation_of(granted, grant_id="r-1"))

        assert await resolution.outstanding("g-1") is None

    async def test_outstanding_returns_an_expired_but_unrevoked_grant(
        self, resolution: RecipientGrantResolution
    ) -> None:
        """This member reads **no clock**, and that is the contract (ADR-0193 §1, §6).

        Outstanding is a fact about two records; expiry is decided by
        ``AuditTrail.record`` against the *decision's* own ``decided_at``, which is
        the only question about liveness a durable record answers identically on
        every later read. A resolution face that filtered by a clock would make a
        grant that expired between the ruling and the write retract an honest
        ``ALLOW``.
        """
        granted = recipient_grant(
            member(ALICE),
            grant_id="g-1",
            decided_at=AT - timedelta(days=30),
            expires_at=AT - timedelta(days=29),
        )
        await self.held(resolution, granted)

        assert await resolution.outstanding("g-1") == granted

    async def test_a_returned_record_is_detached_from_the_store(
        self, resolution: RecipientGrantResolution
    ) -> None:
        """Detached like every other query on this seam (ADR-0193 §1).

        Both levels, for the reason ``RecipientGrantsContract``'s own detachment
        case gives: §1's clause reaches everything mutable a returned record does.
        """
        await self.held(resolution, recipient_grant(member(ALICE), grant_id="g-1"))
        found = await resolution.outstanding("g-1")
        assert found is not None

        found.__dict__["destinations"] = (member(ALICE), member(BOB))
        found.destinations[0].__dict__["canonical"] = BOB

        again = await resolution.outstanding("g-1")
        assert again is not None
        assert again.destinations == (member(ALICE),)


class RecipientGrantStoreContract(RecipientGrantsContract, RecipientGrantResolutionContract):
    """Behaviour every ``RecipientGrantStore`` must exhibit (ADR-0193 §1, §9).

    Inherits both narrow seams' clauses, because a store *is* the two narrow seams
    plus the ability to write — which is ADR-0193 §1's "one concrete store
    satisfies all three faces" tested rather than asserted. The store is an
    **active participant** rather than a filing cabinet: it is append-only, it
    validates the revocation pointer it is handed, it refuses a grant that *is*
    one it already holds, it counts against a configured ceiling inside its own
    atomic act, and it detaches what it stores as well as what it returns.
    """

    def make_store(self, *, max_outstanding: int, now: MovableClock) -> RecipientGrantStore:
        """Override to build a **fresh, empty** store at ``max_outstanding``.

        Separate from :meth:`reopened` because the two ask different questions: this
        one is how a case that is *about* the ceiling gets a store at the ceiling it
        needs, and that one is how a case about a *changed* setting gets the same
        history under a new one. A single hook would have to be one or the other.
        """
        raise NotImplementedError

    def reopened(self, store: RecipientGrantStore, *, max_outstanding: int) -> RecipientGrantStore:
        """Override to return **this store's history** under a different ceiling.

        What a deployment does when it edits ``Settings`` and restarts. It is a
        hook rather than a constructor call because "the same history" means a file
        for a durable store and a shared log for a fake, and the clause under test
        — that a lowered ceiling hides, evicts and truncates nothing — is
        unreachable without it.
        """
        raise NotImplementedError

    @pytest.fixture
    def store(self, clock: MovableClock) -> RecipientGrantStore:
        """An empty store at :data:`CEILING`, over the suite's own clock."""
        return self.make_store(max_outstanding=CEILING, now=clock)

    @pytest.fixture
    def grants(self, store: RecipientGrantStore) -> RecipientGrants:
        """The same subject, seen through the query face.

        Not a second object: the inherited clauses must bind *this* store, which
        is ADR-0193 §1's "one concrete store satisfies all three faces" being
        tested rather than asserted. A store that answered a narrow suite through a
        different instance would prove nothing about the one under test here.
        """
        return store

    @pytest.fixture
    def resolution(self, store: RecipientGrantStore) -> RecipientGrantResolution:
        """The same subject again, seen through the resolution face."""
        return store

    async def given(self, grants: RecipientGrants, *records: RecipientGrant) -> None:
        """Arrange the inherited clauses' history through ``record`` itself.

        A store has a contract-level way to do this, so it uses it — which means
        the narrow clauses run against state the store's own write path produced,
        not against state a test reached in behind it.
        """
        assert isinstance(grants, RecipientGrantStore)
        for record in records:
            await grants.record(record)

    async def held(self, resolution: RecipientGrantResolution, *records: RecipientGrant) -> None:
        """The same, for the resolution face's inherited clauses."""
        assert isinstance(resolution, RecipientGrantStore)
        for record in records:
            await resolution.record(record)

    def test_conforms_to_the_store_protocol(self, store: RecipientGrantStore) -> None:
        assert isinstance(store, RecipientGrantStore)

    # --- §1: append-only, write-once ---------------------------------------

    async def test_a_recorded_grant_comes_back_under_its_own_id(
        self, store: RecipientGrantStore
    ) -> None:
        """The id is the **caller's**, minted before the call (ADR-0021 §3, kept)."""
        granted = recipient_grant(member(ALICE), grant_id="g-1")

        returned = await store.record(granted)

        assert returned == "g-1"
        assert await store.outstanding("g-1") == granted

    async def test_recording_a_known_id_is_refused_rather_than_upserted(
        self, store: RecipientGrantStore
    ) -> None:
        """A store that upserts is one where a user's decision can be rewritten."""
        await store.record(recipient_grant(member(ALICE), grant_id="g-1"))

        await _refuses(store, recipient_grant(member(BOB), grant_id="g-1"))

        held = await store.outstanding("g-1")
        assert held is not None
        assert held.destinations == (member(ALICE),)

    # --- §1: a second grant that *is* the first ----------------------------

    async def test_a_granting_record_duplicating_an_outstanding_subject_is_refused(
        self, store: RecipientGrantStore
    ) -> None:
        """Revoking one would leave the other standing, so the user revokes nothing."""
        await store.record(recipient_grant(member(ALICE), grant_id="g-1"))

        await _refuses(store, recipient_grant(member(ALICE), grant_id="g-2"))

    async def test_a_granting_record_over_a_different_destination_set_is_admitted(
        self, store: RecipientGrantStore
    ) -> None:
        """Overlapping grants are permitted, and are what precedence is for."""
        await store.record(recipient_grant(member(ALICE), grant_id="g-1"))

        await store.record(recipient_grant(member(ALICE), member(BOB), grant_id="g-2"))

        assert {held.id for held in await store.standing()} == {"g-1", "g-2"}

    async def test_an_identical_grant_is_refused_while_the_first_is_expired_but_outstanding(
        self, store: RecipientGrantStore, clock: MovableClock
    ) -> None:
        """The duplicate rule is stated over **outstanding**, not over live (§1).

        Two drafts of that clause died finding out why: a refusal over "already
        live" obliges ``record`` to read a clock, and one that substituted the
        caller's ``decided_at`` is breakable by skew in both directions at once —
        a forward-skewed instant admits a second grant that is live immediately,
        and a backward-skewed one refuses a renewal after the first has genuinely
        expired. Outstanding is a fact about two records, so the write path can
        decide it; the cost is this case, and the recourse is the one below.
        """
        await store.record(recipient_grant(member(ALICE), grant_id="g-1"))
        clock.set(EXPIRES + timedelta(days=1))

        await _refuses(store, recipient_grant(member(ALICE), grant_id="g-2"))

    async def test_an_identical_grant_is_admitted_once_the_first_is_revoked(
        self, store: RecipientGrantStore
    ) -> None:
        """The other side of the same rule: re-granting is revoke-then-grant."""
        granted = recipient_grant(member(ALICE), grant_id="g-1")
        await store.record(granted)
        await store.record(recipient_revocation_of(granted, grant_id="r-1"))

        await store.record(recipient_grant(member(ALICE), grant_id="g-2"))

        assert [held.id for held in await store.standing()] == ["g-2"]

    async def test_two_identical_grants_recorded_at_once_leave_exactly_one(
        self, store: RecipientGrantStore
    ) -> None:
        """The check and the insert are one operation (ADR-0193 §1).

        A sequential test passes an implementation whose check and insert are two,
        which is the race ADR-0021 §4's atomicity argument is about: "the system
        composes on one event loop" is precisely the setting in which an ``await``
        between a check and a write is an interleaving point.
        """
        first = recipient_grant(member(ALICE), grant_id="g-1")
        second = recipient_grant(member(ALICE), grant_id="g-2")

        outcomes = await asyncio.gather(
            store.record(first), store.record(second), return_exceptions=True
        )

        refused = [outcome for outcome in outcomes if isinstance(outcome, BaseException)]
        assert len(refused) == 1, outcomes
        assert isinstance(refused[0], InvalidRecipientGrantError)
        assert len(await store.export()) == 1

    # --- §1: the revocation invariants -------------------------------------

    async def test_a_revocation_naming_an_absent_grant_is_refused(
        self, store: RecipientGrantStore
    ) -> None:
        """Nothing revokes a record the store does not hold."""
        granted = recipient_grant(member(ALICE), grant_id="g-1")

        await _refuses(store, recipient_revocation_of(granted, grant_id="r-1"))

    async def test_a_revocation_naming_a_revoking_record_is_refused(
        self, store: RecipientGrantStore
    ) -> None:
        """Only a granting record can be revoked."""
        granted = recipient_grant(member(ALICE), grant_id="g-1")
        revocation = recipient_revocation_of(granted, grant_id="r-1")
        await store.record(granted)
        await store.record(revocation)

        await _refuses(
            store,
            recipient_revocation_of(granted, grant_id="r-2").model_copy(update={"revokes": "r-1"}),
        )

    async def test_a_second_revocation_of_one_grant_is_refused(
        self, store: RecipientGrantStore
    ) -> None:
        """A grant revoked twice is a history saying the user withdrew one thing twice."""
        granted = recipient_grant(member(ALICE), grant_id="g-1")
        await store.record(granted)
        await store.record(recipient_revocation_of(granted, grant_id="r-1"))

        await _refuses(store, recipient_revocation_of(granted, grant_id="r-2"))

    @pytest.mark.parametrize(
        "substituted",
        [
            pytest.param({"destinations": (member(BOB),)}, id="a different destination set"),
            pytest.param({"account": OTHER_ACCOUNT}, id="a different account"),
            pytest.param({"expires_at": EXPIRES + timedelta(days=1)}, id="a different expiry"),
        ],
    )
    async def test_a_revocation_transcribing_a_different_field_is_refused(
        self, store: RecipientGrantStore, substituted: dict[str, object]
    ) -> None:
        """A revoking record transcribes **what it withdraws** (ADR-0193 §1).

        The store verifies it because a record in isolation cannot see the record
        it names — ADR-0021 §1's reason for embedding a whole declaration rather
        than a name, one store over. There is no partial revocation, so a
        revocation naming a *narrower* destination set is not a narrowing: it is a
        record that does not describe what it is withdrawing.
        """
        granted = recipient_grant(member(ALICE), grant_id="g-1")
        await store.record(granted)

        await _refuses(
            store,
            recipient_revocation_of(granted, grant_id="r-1").model_copy(update=substituted),
        )

    async def test_a_revocation_predating_the_grant_it_revokes_is_accepted(
        self, store: RecipientGrantStore
    ) -> None:
        """There is **no** timestamp invariant here, and the absence is the decision.

        ``decided_at`` is caller-supplied and this store reads no clock on the
        write path, so refusing a revocation that predates its grant would make a
        grant permanently unrevokable across a backwards clock correction. That
        matters more here than on the source-grant store it is taken from:
        revocation is also the recourse ADR-0193 §1's ceiling depends on, so
        trapping it would trap a user above the ceiling with no way down.
        """
        granted = recipient_grant(member(ALICE), grant_id="g-1")
        await store.record(granted)

        await store.record(
            recipient_revocation_of(granted, grant_id="r-1", decided_at=AT - timedelta(days=7))
        )

        assert await store.standing() == []

    # --- §1: the count ceiling ---------------------------------------------

    async def _fill(self, store: RecipientGrantStore, count: int) -> list[RecipientGrant]:
        """Record ``count`` grants of distinct subjects, and return them.

        Distinct by **destination set**, so nothing here brushes the
        duplicate-subject refusal: the ceiling cases have to fail on the count and
        on nothing else, which is the whole reason ADR-0193 §14 asks for a
        concurrent case of *different* subjects beside the duplicate one.
        """
        recorded = []
        for index in range(count):
            granted = recipient_grant(
                member(f"recipient-{index}@example.com"), grant_id=f"g-{index}"
            )
            await store.record(granted)
            recorded.append(granted)
        return recorded

    async def test_a_grant_that_would_breach_the_ceiling_is_refused(
        self, store: RecipientGrantStore
    ) -> None:
        """Refused, not truncated: nothing already recorded is removed to make room."""
        await self._fill(store, CEILING)

        await _refuses(store, recipient_grant(member(ALICE), grant_id="g-over"))

        assert len(await store.standing()) == CEILING

    async def test_a_grant_is_admitted_once_a_revocation_brings_the_count_under(
        self, store: RecipientGrantStore
    ) -> None:
        """The recourse §1 names: revoke a grant you hold, and the way down opens."""
        recorded = await self._fill(store, CEILING)
        await store.record(recipient_revocation_of(recorded[0], grant_id="r-0"))

        await store.record(recipient_grant(member(ALICE), grant_id="g-new"))

        assert len(await store.standing()) == CEILING

    async def test_the_ceiling_counts_expired_but_unrevoked_grants(
        self, store: RecipientGrantStore, clock: MovableClock
    ) -> None:
        """The outstanding-not-live substitution, stated rather than assumed (§1).

        It is in the **tighter** direction and never looser: outstanding is a
        superset of live, and the price is that an expired grant occupies its slot
        until it is revoked — the same shape the duplicate rule already has, and
        the cost of a write path that reads no clock.
        """
        await self._fill(store, CEILING)
        clock.set(EXPIRES + timedelta(days=1))
        assert await store.standing() == []

        await _refuses(store, recipient_grant(member(ALICE), grant_id="g-over"))

    async def test_a_revoking_record_is_never_refused_for_the_count(
        self, store: RecipientGrantStore
    ) -> None:
        """A ceiling that could block a revocation would trap a user with no way down."""
        recorded = await self._fill(store, CEILING)

        for index, granted in enumerate(recorded):
            await store.record(recipient_revocation_of(granted, grant_id=f"r-{index}"))

        assert await store.standing() == []

    async def test_two_grants_of_distinct_subjects_at_the_ceiling_leave_exactly_one(
        self, store: RecipientGrantStore
    ) -> None:
        """The ceiling is counted **inside** the atomic act (ADR-0193 §1).

        Not the concurrent duplicate case one clause up, and the difference is the
        point: two writers of *different* subjects at one below the ceiling both
        see room, both append, and the store ends one over — a race the
        duplicate-subject refusal cannot catch, because the two subjects differ.
        """
        await self._fill(store, CEILING - 1)

        outcomes = await asyncio.gather(
            store.record(recipient_grant(member(ALICE), grant_id="g-a")),
            store.record(recipient_grant(member(BOB), grant_id="g-b")),
            return_exceptions=True,
        )

        refused = [outcome for outcome in outcomes if isinstance(outcome, BaseException)]
        assert len(refused) == 1, outcomes
        assert isinstance(refused[0], InvalidRecipientGrantError)
        assert len(await store.standing()) == CEILING

    async def test_a_zero_ceiling_over_a_populated_store_retracts_nothing(
        self, store: RecipientGrantStore, clock: MovableClock
    ) -> None:
        """Zero is **admission-only**, not a kill switch (ADR-0193 §1).

        The empty-store case alone does not satisfy this clause. A store holding a
        live grant, reopened at zero, still returns it from ``covering`` and
        ``standing`` and still sources a recordable route-(b) ``ALLOW``; what it
        refuses is the *next* grant. An implementation reading zero as a kill
        switch would be a ``Settings`` value retracting an authorisation the user
        gave, with no act and nothing in the trail to show it — what may not be
        created by configuration may not be destroyed by it either.
        """
        granted = recipient_grant(member(ALICE), grant_id="g-1")
        await store.record(granted)

        declined = self.reopened(store, max_outstanding=0)

        assert await declined.standing() == [granted]
        assert await declined.covering(request(binding(ALICE))) == granted
        assert await declined.outstanding("g-1") == granted
        await _refuses(declined, recipient_grant(member(BOB), grant_id="g-2"))

    async def test_a_lowered_ceiling_hides_evicts_and_truncates_nothing(
        self, store: RecipientGrantStore
    ) -> None:
        """A store above a newly lowered ceiling is a **legal** state (ADR-0193 §1).

        Every record in it was admitted under the ceiling in force at the time, and
        a query that hid records to make the current setting look satisfied would be
        lying to the user about their own standing policy. No other case in this
        suite reaches it: the ceiling cases above all run at one setting.
        """
        recorded = await self._fill(store, CEILING)

        lowered = self.reopened(store, max_outstanding=1)

        assert {held.id for held in await lowered.standing()} == {held.id for held in recorded}
        assert len(await lowered.recent(limit=CEILING * 2)) == CEILING
        assert len(await lowered.export()) == CEILING
        await _refuses(lowered, recipient_grant(member(ALICE), grant_id="g-over"))

        for index, granted in enumerate(recorded):
            await lowered.record(recipient_revocation_of(granted, grant_id=f"r-{index}"))
        await lowered.record(recipient_grant(member(ALICE), grant_id="g-new"))

        assert [held.id for held in await lowered.standing()] == ["g-new"]
        assert len(await lowered.export()) == CEILING * 2 + 1

    # --- §1, §9: standing, recent, export and clear ------------------------

    async def test_standing_returns_every_live_grant_and_no_other_record(
        self, store: RecipientGrantStore, clock: MovableClock
    ) -> None:
        """Live, and complete: no page, no sample, no elision."""
        live = recipient_grant(member(ALICE), grant_id="g-live")
        expired = recipient_grant(
            member(BOB),
            grant_id="g-expired",
            decided_at=AT - timedelta(days=30),
            expires_at=AT - timedelta(days=29),
        )
        revoked = recipient_grant(member("carol@example.com"), grant_id="g-revoked")
        await store.record(live)
        await store.record(expired)
        await store.record(revoked)
        await store.record(recipient_revocation_of(revoked, grant_id="r-1"))

        assert [held.id for held in await store.standing()] == ["g-live"]

    async def test_standing_reads_the_clock_exactly_once(
        self, store: RecipientGrantStore, clock: MovableClock
    ) -> None:
        """Two records sharing an ``expires_at``: one query returns both or neither.

        A ``standing`` reading an advancing clock per row could return one and omit
        the other, which is a set true at no real instant. This is the list-shaped
        half of §9's single-read clause, and it cannot reach ``covering``, which
        returns one record — which is why both have their own case.
        """
        await store.record(recipient_grant(member(ALICE), grant_id="g-a"))
        await store.record(recipient_grant(member(BOB), grant_id="g-b"))
        clock.advance_by()

        held = await store.standing()

        assert clock.readings == 1
        assert {record.id for record in held} == {"g-a", "g-b"}

    async def test_outstanding_reads_no_clock_at_all(
        self, store: RecipientGrantStore, clock: MovableClock
    ) -> None:
        """It is outside §9's single-read clause rather than an exception to it."""
        await store.record(recipient_grant(member(ALICE), grant_id="g-1"))
        readings = clock.readings

        await store.outstanding("g-1")

        assert clock.readings == readings

    @pytest.mark.parametrize("limit", [0, -1])
    async def test_recent_refuses_a_non_positive_limit(
        self, store: RecipientGrantStore, limit: int
    ) -> None:
        """Raised rather than clamped or passed through (ADR-0021 §4's reason).

        ``LIMIT ?`` against SQLite turns ``-1`` into no limit at all, which is the
        one failure a bounded read of a Tier 1 store exists to prevent, and no
        other case in this suite reaches it.
        """
        with pytest.raises(ValueError, match="strictly positive"):
            await store.recent(limit=limit)

    async def test_recent_admits_a_limit_wider_than_the_store(
        self, store: RecipientGrantStore
    ) -> None:
        """Every strictly positive integer is admissible (ADR-0193 §1).

        A store passing the value straight to SQLite raises ``OverflowError`` on it
        while passing the zero and negative cases above. Not a new rule:
        ``SourceGrantStore``'s own shared suite pins exactly this boundary, as
        ``AuditTrail``'s does, and a third grant-shaped store that omitted it would
        be the one implementation free to have the bug.
        """
        await store.record(recipient_grant(member(ALICE), grant_id="g-1"))

        assert len(await store.recent(limit=2**63)) == 1

    async def test_recent_orders_by_decision_time_then_by_id(
        self, store: RecipientGrantStore
    ) -> None:
        """Recorded in an order that is not the answer's, on both halves (§1).

        An older ``decided_at`` recorded **after** a newer one, and two sharing a
        ``decided_at`` whose ids are recorded in **descending** code-point order. A
        store returning insertion order passes the limit, wide-limit, detachment
        and lowered-ceiling cases and returns the wrong sequence on both halves;
        the tie-break in particular is the half a single-record fixture can never
        fail.
        """
        newer = AT + timedelta(hours=1)
        await store.record(recipient_grant(member(ALICE), grant_id="g-newer", decided_at=newer))
        await store.record(recipient_grant(member(BOB), grant_id="g-older", decided_at=AT))
        await store.record(
            recipient_grant(member("carol@example.com"), grant_id="g-b", decided_at=AT)
        )
        await store.record(
            recipient_grant(member("dave@example.com"), grant_id="g-a", decided_at=AT)
        )

        ordered = [held.id for held in await store.recent(limit=10)]

        assert ordered == ["g-newer", "g-a", "g-b", "g-older"]

    async def test_export_omits_no_record_of_any_kind(self, store: RecipientGrantStore) -> None:
        """What discharges ADR-0004 §6's portability obligation, so it omits nothing.

        Seeded with a live grant, an expired-but-unrevoked grant, a revoked grant
        and the revoking record that revoked it: an implementation delegating
        ``export`` to ``standing`` passes every query case in this suite while
        silently dropping three of the four.
        """
        live = recipient_grant(member(ALICE), grant_id="g-live")
        expired = recipient_grant(
            member(BOB),
            grant_id="g-expired",
            decided_at=AT - timedelta(days=30),
            expires_at=AT - timedelta(days=29),
        )
        revoked = recipient_grant(member("carol@example.com"), grant_id="g-revoked")
        revocation = recipient_revocation_of(revoked, grant_id="r-1")
        for record in (live, expired, revoked, revocation):
            await store.record(record)

        exported = await store.export()

        assert sorted(held.id for held in exported) == [
            "g-expired",
            "g-live",
            "g-revoked",
            "r-1",
        ]

    async def test_clear_returns_the_count_of_every_record_removed(
        self, store: RecipientGrantStore
    ) -> None:
        """Of **every** record, not of the live ones (ADR-0193 §9).

        An implementation that erases correctly and returns the live count
        satisfies every other ``clear`` case; the mixed store is what separates
        them.
        """
        assert await store.clear() == 0

        revoked = recipient_grant(member(ALICE), grant_id="g-revoked")
        for record in (
            recipient_grant(member(BOB), grant_id="g-live"),
            recipient_grant(
                member("carol@example.com"),
                grant_id="g-expired",
                decided_at=AT - timedelta(days=30),
                expires_at=AT - timedelta(days=29),
            ),
            revoked,
            recipient_revocation_of(revoked, grant_id="r-1"),
        ):
            await store.record(record)

        assert await store.clear() == 4
        assert await store.export() == []

    async def test_clear_retains_nothing_an_id_could_collide_with(
        self, store: RecipientGrantStore
    ) -> None:
        """No record, no id, no tombstone, no derived value (ADR-0193 §1).

        Round 3 of ADR-0193's own loop reached for a tombstone of every id the
        store had ever held, and round 5 found the opaque id type it needed could
        not deliver — thirty-two hex characters encode sixteen bytes of anything a
        caller chooses. What stands in its place is the row's own
        ``subject_digest``, which is ``AuditTrail.record``'s to check; here the
        clause is simply that the id is free again.
        """
        granted = recipient_grant(member(ALICE), grant_id="g-1")
        await store.record(granted)
        await store.clear()

        await store.record(recipient_grant(member(BOB), grant_id="g-1"))

        held = await store.outstanding("g-1")
        assert held is not None
        assert held.destinations == (member(BOB),)

    # --- §1: detachment on the write path too ------------------------------

    async def test_a_recorded_grant_is_detached_from_the_caller(
        self, store: RecipientGrantStore
    ) -> None:
        """The write-side half, and the one that is easy to drop (ADR-0018 §4).

        ``frozen=True`` refuses ``grant.destinations = …`` and does not refuse
        ``grant.__dict__["destinations"] = …``, so a store keeping the caller's
        object would let a grant be **widened after it was appended** — through a
        store whose entire premise is that its records are not rewritten.
        """
        granted = recipient_grant(member(ALICE), grant_id="g-1")
        await store.record(granted)

        granted.__dict__["destinations"] = (member(ALICE), member(BOB))

        held = await store.outstanding("g-1")
        assert held is not None
        assert held.destinations == (member(ALICE),)

    async def test_a_returned_list_is_detached_from_the_store(
        self, store: RecipientGrantStore
    ) -> None:
        """The list, the records in it, and everything mutable those reach.

        The third clause is the one a root-only snapshot passes: the nested
        ``CanonicalDestination`` is rewritten here as well as the record's own
        ``expires_at``, so a store handing back its own nested models is caught by
        the same case rather than by a later one.
        """
        await store.record(recipient_grant(member(ALICE), grant_id="g-1"))

        held = await store.standing()
        held.clear()
        exported = await store.export()
        exported[0].__dict__["expires_at"] = AT + timedelta(days=3650)
        exported[0].destinations[0].__dict__["canonical"] = BOB

        assert len(await store.standing()) == 1
        again = await store.export()
        assert again[0].expires_at == EXPIRES
        assert again[0].destinations == (member(ALICE),)

    async def test_a_recorded_grant_shares_no_model_beneath_its_root(
        self, store: RecipientGrantStore
    ) -> None:
        """§1's snapshot is recursive, and a shallow one is not detached at all.

        A mapping of the grant's *own* field values still holds the caller's
        ``CanonicalDestination``, ``ToolDefinition`` and ``BoundAccount`` objects —
        pydantic's default ``revalidate_instances="never"`` keeps whatever instance
        was passed — so the snapshot and the caller share every model beneath the
        root. ``frozen=True`` refuses ``destination.canonical = …`` and does not
        refuse ``destination.__dict__["canonical"] = …``, which is the same gate
        ``test_a_recorded_grant_is_detached_from_the_caller`` defeats one level up.

        So the widening that clause exists to deny is available one level down: a
        caller rewrites the recipient **after** ``record`` accepted the grant, and
        the store holds an authorisation over Bob established by an act that named
        Alice. The declaration and the account carry it too — coverage compares all
        three by value (§3), so rewriting either widens what the grant covers just
        as rewriting a destination does.

        The three nested values are **copies**, because the builder's defaults are
        module-level singletons: mutating those in place would rewrite what every
        other case in this suite is arranged around.
        """
        tool = TOOL.model_copy(deep=True)
        account = ACCOUNT.model_copy(deep=True)
        granted = recipient_grant(member(ALICE), grant_id="g-1", tool=tool, account=account)
        await store.record(granted)

        granted.destinations[0].__dict__["canonical"] = BOB
        tool.__dict__["description"] = "a declaration the user never saw"
        account.__dict__["reference"] = "conn-9999"

        held = await store.outstanding("g-1")
        assert held is not None
        assert held.destinations == (member(ALICE),)
        assert held.tool == TOOL
        assert held.account == ACCOUNT

    async def test_a_grant_holding_a_nested_subclass_is_refused(
        self, store: RecipientGrantStore
    ) -> None:
        """The other half of a recursive snapshot: what the rebuild would **drop**.

        A ``CanonicalDestination`` subclass carrying a field of its own survives
        validation for the reason above, and the rebuild that detaches the record
        emits the *declared* fields and drops that one — so the stored grant would
        compare equal to a record the user never authorised, and the store would
        have kept less than it was handed. Refused rather than narrowed, which is
        the ruling the invocation ledger reached on the identical shape and which
        the shared helper carries to this store.
        """
        wider = type(
            "_WiderDestination",
            (CanonicalDestination,),
            {"__annotations__": {"note": str}, "note": "carried past the record"},
        )
        granted = recipient_grant(member(ALICE), grant_id="g-1")
        granted.__dict__["destinations"] = (
            wider(protocol=DestinationProtocol.SMTP, canonical=ALICE),
        )

        with pytest.raises(InvalidRecipientGrantError, match="not a valid record"):
            await store.record(granted)

        assert await store.outstanding("g-1") is None

    async def test_a_grant_mutated_while_its_write_is_queued_stores_what_was_submitted(
        self, store: RecipientGrantStore
    ) -> None:
        """ADR-0065: a post-call mutation test does not detect tearing.

        The case above pins what a store **retains**; this pins what it
        *serialises*, which is the half a store that writes JSON inside its lock
        survives by accident. ``record`` takes its snapshot and then awaits — for
        the lock, and for the write behind it — so an implementation whose snapshot
        shares the caller's nested models writes whatever those say by the time it
        gets there. A first write occupying the lock makes that interval a real one
        rather than a hoped-for interleaving: the second ``record`` is suspended,
        with its grant accepted and not yet stored, when the recipient is rewritten.

        The three nested values are copies for
        ``test_a_recorded_grant_shares_no_model_beneath_its_root``'s reason.
        """
        tool = TOOL.model_copy(deep=True)
        account = ACCOUNT.model_copy(deep=True)
        granted = recipient_grant(member(ALICE), grant_id="g-1", tool=tool, account=account)

        async def _rewrite_the_recipient() -> None:
            granted.destinations[0].__dict__["canonical"] = BOB
            tool.__dict__["description"] = "a declaration the user never saw"
            account.__dict__["reference"] = "conn-9999"

        await asyncio.gather(
            store.record(recipient_grant(member(BOB), grant_id="g-block")),
            store.record(granted),
            _rewrite_the_recipient(),
        )

        held = await store.outstanding("g-1")
        assert held is not None
        assert held.destinations == (member(ALICE),)
        assert held.tool == TOOL
        assert held.account == ACCOUNT
