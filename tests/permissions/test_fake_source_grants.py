"""The canonical grant fakes pass the shared conformance suites (ADR-0097 §10).

Three bindings, not two, and the third is the one that carries an argument.
``TestFakeSourceGrantsContract`` and ``TestFakeSourceGrantStoreContract`` are the
ordinary ones — each fake against its own seam's suite, which is what lets other
subsystems trust ``ai_assistant.testing``'s doubles as stand-ins.

``TestFakeSourceGrantStoreSatisfiesTheNarrowSeam`` runs the **store** fake
through the ``SourceGrants`` suite, which ADR-0097 §10 requires in as many words:
"``FakeSourceGrantStore`` is the wider seam's fake and satisfies the narrow one
structurally, so binding it there costs one class and turns §3's 'one
implementation satisfies both' from an assertion into a test." That claim is what
lets a composition root pass one object to a driver's ``SourceGrants`` parameter
and to the hub's ``SourceGrantStore`` one, and without this binding it would be a
sentence in an ADR rather than something the gate checks.

The scripted capabilities each fake carries beyond its contract — a raising
``live``, a raising ``record``, a revocation that lands between two ``live``
calls — are tested here too. They are not contract, but they are what makes a
*driver's* ADR-0097 §5a branches reachable from a test at all, so a capability
that quietly stopped working would take a later lane's coverage with it.
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING

import pytest
from source_grant_contract import SOURCE, SourceGrantsContract, SourceGrantStoreContract

from ai_assistant.core.errors import GrantError, InvalidGrantError
from ai_assistant.core.protocols import SourceGrants, SourceGrantStore
from ai_assistant.core.types import GrantScope
from ai_assistant.testing import (
    DEFAULT_GRANTED_SOURCE,
    FakeReader,
    FakeSourceGrants,
    FakeSourceGrantStore,
    revocation_of,
    source_grant,
)
from ai_assistant.testing.cancellation import SuspendedMidWrite

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from ai_assistant.core.types import SourceGrant


class TestFakeSourceGrantsContract(SourceGrantsContract):
    """Runs FakeSourceGrants through the shared SourceGrants conformance suite."""

    @pytest.fixture
    def grants(self) -> SourceGrants:
        return FakeSourceGrants()

    async def given(self, grants: SourceGrants, *records: SourceGrant) -> None:
        """Arrange through the fake's own test-only lever.

        The query seam has no write member — that is the property under test — so
        the narrow fake's history is arranged by the test that built it rather
        than through the Protocol the code under test would hold.
        """
        assert isinstance(grants, FakeSourceGrants)
        grants.hold(*records)


class TestFakeSourceGrantStoreContract(SourceGrantStoreContract):
    """Runs FakeSourceGrantStore through the shared SourceGrantStore suite."""

    # No ``operations_without_shared_resource`` opt-out: every operation on this
    # fake — the two writes and the three reads — enters the one modelled
    # resource, so ADR-0060's case runs against every lock site rather than
    # skipping some and leaving them proved only by a durable store that does not
    # exist yet.

    @pytest.fixture
    def store(self) -> SourceGrantStore:
        return FakeSourceGrantStore()

    @contextlib.asynccontextmanager
    async def store_suspended_mid_write(
        self,
    ) -> AsyncIterator[SuspendedMidWrite[SourceGrantStore]]:
        """The fake models the resource it does not really own (ADR-0060 §3).

        A list needs no serialising, so without this the canonical fake could only
        opt out — and the cancellation case would run against nothing at all,
        since ADR-0097 §10 puts the ``permissions/`` implementation in a later
        lane. Every method passes through the *one* modelled resource, so ``arm``
        ignores which operation it is handed: the parametrised cases exercise the
        same ``held()`` path here and earn their keep on the durable store, where
        each operation is a separate lock site. Nothing to dispose of, hence the
        bare yield.
        """
        store = FakeSourceGrantStore()
        yield SuspendedMidWrite(
            store=store,
            log=store.resource_log,
            arm=lambda _operation: store.suspend_next_operation(),
        )


class TestFakeSourceGrantStoreSatisfiesTheNarrowSeam(SourceGrantsContract):
    """The store fake, run through the *narrow* seam's suite (ADR-0097 §10).

    ADR-0097 §3's "one implementation satisfies both" as a test rather than an
    assertion. Deliberately a separate class from
    :class:`TestFakeSourceGrantStoreContract`: that one binds the store to the
    wider suite through the ``store`` fixture, and this one binds it to the narrow
    suite through ``grants`` — which is the fixture a *driver* would be handed,
    and therefore the one whose answers the gate actually depends on.
    """

    @pytest.fixture
    def grants(self) -> SourceGrants:
        return FakeSourceGrantStore()

    async def given(self, grants: SourceGrants, *records: SourceGrant) -> None:
        """Arrange through ``record``, since this subject has one."""
        assert isinstance(grants, SourceGrantStore)
        for record in records:
            await grants.record(record)


# --- the scripted capabilities ADR-0097 §10 requires of the fakes ------------


async def test_the_narrow_fake_offers_no_way_to_record() -> None:
    """The capability split modelled in the fake, not only in the annotation.

    ADR-0097 §3's guarantee is static — a driver cannot *name* ``record`` on a
    ``SourceGrants`` parameter — and a canonical fake that carried the method
    anyway would let a driver's own test reach it through a concrete annotation,
    which is the one place the type stops arguing.
    """
    # Typed `object` so the check is a runtime one: mypy already knows the answer
    # (the fake is `@final`), and an annotated subject would make the assertion
    # unreachable rather than merely redundant.
    grants: object = FakeSourceGrants()

    assert not isinstance(grants, SourceGrantStore)
    for member in ("record", "recent", "export", "clear"):
        assert not hasattr(grants, member), member


@pytest.mark.parametrize(
    "make",
    [FakeSourceGrants, FakeSourceGrantStore],
    ids=["the narrow fake", "the store fake"],
)
async def test_both_fakes_can_be_scripted_to_raise_from_live(
    make: type[FakeSourceGrants] | type[FakeSourceGrantStore],
) -> None:
    """§5a's fail-closed clause is otherwise unreachable from any test.

    Required of **both** fakes because a driver may be handed either — the
    composition root is free to pass the concrete store to a ``SourceGrants``
    parameter — and a capability present on only one would leave that wiring's
    ``GrantError`` branch untested. The cause survives, so a driver's own test can
    assert what it wrapped.
    """
    subject = make([source_grant(SOURCE)])
    cause = OSError("disk gone")
    subject.fail_live(cause)

    with pytest.raises(GrantError) as raised:
        await subject.live(source=SOURCE, use=GrantScope.INGEST)

    assert raised.value.__cause__ is cause


async def test_the_store_fake_can_be_scripted_to_raise_from_record() -> None:
    """A store fault on the write path, distinct from a refusal.

    ``fail_record`` raises :class:`GrantError` rather than
    :class:`InvalidGrantError`, because a refusal is what the invariants already
    produce from a badly-formed record and a caller arranging one of those builds
    the record instead. What this scripts is "the store could not be written",
    which no well-formed input can provoke.
    """
    store = FakeSourceGrantStore()
    store.fail_record()

    with pytest.raises(GrantError) as raised:
        await store.record(source_grant(SOURCE))

    assert not isinstance(raised.value, InvalidGrantError)
    assert await store.export() == [], "a scripted store fault must not half-write"


async def test_the_narrow_fake_can_revoke_between_two_live_calls() -> None:
    """The capability §5a's *second* clause is untestable without.

    A driver checks the grant, reads, and re-checks — and must discard a reading
    whose grant went away in between. The query seam has no method a test could
    record a revocation with, so without this lever the discard path is
    unreachable and the clause would report as held while nothing exercised it.

    The revocation that lands is a **real appended record**, so the fake ends up
    in a state a conforming store could genuinely be in: ``recent`` on the store
    fake would show both records, and nothing about the history is private to the
    lever.
    """
    grants = FakeSourceGrants([source_grant(SOURCE)])
    grants.revoke_after(1)

    assert await grants.live(source=SOURCE, use=GrantScope.INGEST) is not None
    assert await grants.live(source=SOURCE, use=GrantScope.INGEST) is None
    assert await grants.live(source=SOURCE, use=GrantScope.FACET) is None
    assert grants.call_count == 3


async def test_the_narrow_fake_can_be_scripted_to_hold_a_revoked_grant() -> None:
    """The third state a driver needs: granted once, and withdrawn."""
    granted = source_grant(SOURCE)
    grants = FakeSourceGrants([granted, revocation_of(granted)])

    assert await grants.live(source=SOURCE, use=GrantScope.FACET) is None


@pytest.mark.parametrize("calls", [0, 2])
async def test_revoke_after_lands_where_it_was_told_to(calls: int) -> None:
    """Zero is meaningful — revoke before the next call — and so is a later count."""
    grants = FakeSourceGrants([source_grant(SOURCE)])
    grants.revoke_after(calls)

    answers = [
        await grants.live(source=SOURCE, use=GrantScope.FACET) is not None for _ in range(calls + 1)
    ]

    assert answers == [True] * calls + [False]


async def test_a_negative_revoke_after_names_no_moment() -> None:
    with pytest.raises(ValueError, match="negative"):
        FakeSourceGrants().revoke_after(-1)


# --- the scripts a conforming fake must refuse -------------------------------


@pytest.mark.parametrize(
    "make",
    [FakeSourceGrants, FakeSourceGrantStore],
    ids=["the narrow fake", "the store fake"],
)
def test_neither_fake_can_be_constructed_into_an_impossible_history(
    make: type[FakeSourceGrants] | type[FakeSourceGrantStore],
) -> None:
    """A script the fake could only honour by breaking its own contract is refused.

    At construction rather than at query time, so it fails where it was written.
    Two live grants for one source is the state ADR-0097 §4 says cannot exist, and
    a fake that could be put into it would let a consumer's test assert against
    answers no real store could give — ``FakeReader``'s trade, for its reason.
    """
    with pytest.raises(InvalidGrantError):
        make([source_grant(SOURCE, grant_id="g-1"), source_grant(SOURCE, grant_id="g-2")])


def test_hold_applies_the_same_invariants_a_store_would() -> None:
    """The lever is not a way behind the invariants, only around the Protocol."""
    grants = FakeSourceGrants([source_grant(SOURCE, grant_id="g-1")])

    with pytest.raises(InvalidGrantError):
        grants.hold(source_grant(SOURCE, grant_id="g-2"))


# --- the default that makes the natural wiring work --------------------------


async def test_a_default_grant_covers_a_default_fake_reader() -> None:
    """The two defaults line up, and that is worth pinning rather than hoping.

    ADR-0097 §1 keys a grant on the reader's **declared identity**, so a driver's
    test that wires a :class:`FakeReader` beside a granted
    :class:`FakeSourceGrants` gets a gate that passes only if the two default
    names are the same value. Two defaults that drifted apart would make every
    such test read as ungranted, and the failure would look like a bug in the
    gate rather than in a fixture.
    """
    reader = FakeReader()
    grants = FakeSourceGrants([source_grant()])

    assert reader.name == DEFAULT_GRANTED_SOURCE
    assert await grants.live(source=reader.name, use=GrantScope.INGEST) is not None
