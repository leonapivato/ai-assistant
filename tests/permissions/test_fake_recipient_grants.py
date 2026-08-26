"""The canonical recipient-grant fakes, bound to the three shared suites.

ADR-0193 §14 lands a triad per Protocol, and this is the third artifact of each:
without a binding class the suites collect nothing and the fakes are unverified
however many files exist (``tests/core/test_protocol_triad.py`` makes that
mechanical).

**Each narrow suite is bound twice** — once against its own narrow fake and once
against :class:`~ai_assistant.testing.recipient_grants.FakeRecipientGrantStore` —
which is ADR-0193 §1's "one concrete store satisfies all three faces" turned from
an assertion into a test. It also means a divergence between the narrow fake and
the store fake is a failure rather than a latent surprise, which matters here
because all three answer from one shared log and a future lane could easily give
one of them its own.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from recipient_builders import ALICE, AT, MovableClock, binding, member, request
from recipient_grant_contract import (
    CEILING,
    RecipientGrantResolutionContract,
    RecipientGrantsContract,
    RecipientGrantStoreContract,
)

from ai_assistant.core.errors import RecipientGrantError
from ai_assistant.testing import (
    FakeRecipientGrantResolution,
    FakeRecipientGrants,
    FakeRecipientGrantStore,
    recipient_grant,
)

if TYPE_CHECKING:
    from ai_assistant.core.protocols import (
        RecipientGrantResolution,
        RecipientGrants,
        RecipientGrantStore,
    )
    from ai_assistant.core.types import RecipientGrant


class TestFakeRecipientGrantsContract(RecipientGrantsContract):
    """``FakeRecipientGrants`` against the query seam's clauses."""

    @pytest.fixture
    def grants(self, clock: MovableClock) -> RecipientGrants:
        return FakeRecipientGrants(now=clock)

    async def given(self, grants: RecipientGrants, *records: RecipientGrant) -> None:
        assert isinstance(grants, FakeRecipientGrants)
        grants.hold(*records)


class TestFakeRecipientGrantResolutionContract(RecipientGrantResolutionContract):
    """``FakeRecipientGrantResolution`` against the resolution seam's clauses."""

    @pytest.fixture
    def resolution(self) -> RecipientGrantResolution:
        return FakeRecipientGrantResolution()

    async def held(self, resolution: RecipientGrantResolution, *records: RecipientGrant) -> None:
        assert isinstance(resolution, FakeRecipientGrantResolution)
        resolution.hold(*records)


class TestFakeRecipientGrantStoreContract(RecipientGrantStoreContract):
    """``FakeRecipientGrantStore`` against all three seams' clauses.

    Inherits both narrow suites through :class:`RecipientGrantStoreContract`, so
    the store fake answers the query and resolution clauses through **itself**
    rather than through a second object — which is what makes the inheritance
    evidence rather than decoration.
    """

    def make_store(self, *, max_outstanding: int, now: MovableClock) -> RecipientGrantStore:
        return FakeRecipientGrantStore(max_outstanding=max_outstanding, now=now)

    def reopened(self, store: RecipientGrantStore, *, max_outstanding: int) -> RecipientGrantStore:
        assert isinstance(store, FakeRecipientGrantStore)
        return store.reopened_at(max_outstanding)


# --- the scripted capabilities, which are the fakes' and not the contract's ---


async def test_a_scripted_failure_raises_from_the_query_face() -> None:
    """ADR-0193 §14 requires it, and a policy's fail-closed branch needs it.

    Without a ``covering`` that raises, the branch is unreachable from any test —
    and an implementation that caught the error and carried on with the last
    successful lookup would pass every other policy test while authorising sends
    after its authorisation stopped being checkable (§1's last clause).
    """
    grants = FakeRecipientGrants([recipient_grant(member(ALICE), grant_id="g-1")])
    grants.fail_covering(RuntimeError("disk gone"))

    with pytest.raises(RecipientGrantError) as raised:
        await grants.covering(request(binding(ALICE)))

    assert isinstance(raised.value.__cause__, RuntimeError)


async def test_a_scripted_failure_raises_from_the_resolution_face() -> None:
    """The trail's fail-closed branch needs the same, one face over."""
    resolution = FakeRecipientGrantResolution([recipient_grant(member(ALICE), grant_id="g-1")])
    resolution.fail_outstanding()

    with pytest.raises(RecipientGrantError):
        await resolution.outstanding("g-1")


async def test_the_store_fake_fails_reads_and_writes_separately() -> None:
    """A store fault and a refused record are different facts (ADR-0193 §1).

    ``fail_writes`` raises the **base** class rather than
    ``InvalidRecipientGrantError``, because a refusal is what the invariants
    already produce from a badly-formed record and a caller arranging one of those
    builds the record instead. What this scripts is the other failure, which no
    well-formed input can provoke.
    """
    store = FakeRecipientGrantStore()
    store.fail_reads()

    with pytest.raises(RecipientGrantError):
        await store.standing()

    healthy = FakeRecipientGrantStore()
    healthy.fail_writes()
    with pytest.raises(RecipientGrantError):
        await healthy.record(recipient_grant(member(ALICE), grant_id="g-1"))


def test_the_query_face_cannot_name_the_wider_members() -> None:
    """The split is a **type** rather than a promise (ADR-0193 §1).

    ``mypy --strict`` is what enforces it over ``src`` and ``tests``; this asserts
    the runtime shape the annotation describes, so a fake that quietly grew a
    ``record`` — and a consumer's test that then arranged state through the very
    object the policy holds — fails here rather than passing everything.
    """
    grants = FakeRecipientGrants()

    for member_name in ("record", "outstanding", "standing", "recent", "export", "clear"):
        assert not hasattr(grants, member_name), member_name


def test_the_resolution_face_cannot_name_the_wider_members() -> None:
    """A trail that could append a grant could authorise the row it validates."""
    resolution = FakeRecipientGrantResolution()

    for member_name in ("record", "covering", "standing", "recent", "export", "clear"):
        assert not hasattr(resolution, member_name), member_name


async def test_the_narrow_fakes_refuse_a_history_no_store_could_hold() -> None:
    """A script a fake could only honour by breaking its own contract is refused.

    Where it is written, rather than at the assertion it would have distorted:
    these must stay the things a conforming implementation is compared against
    (``FakeSourceGrants`` makes the same trade), so a test that arranged two
    identical outstanding grants would be asserting about a state ADR-0193 §1 says
    cannot exist.
    """
    granted = recipient_grant(member(ALICE), grant_id="g-1")

    with pytest.raises(RecipientGrantError):
        FakeRecipientGrants([granted, recipient_grant(member(ALICE), grant_id="g-2")])

    with pytest.raises(RecipientGrantError):
        FakeRecipientGrantResolution([granted, granted])


def test_a_negative_ceiling_names_no_bound() -> None:
    """Zero is meaningful and admitted; a negative is a value nobody meant."""
    with pytest.raises(ValueError, match="negative"):
        FakeRecipientGrantStore(max_outstanding=-1)


async def test_a_reopened_store_sees_writes_through_the_earlier_view() -> None:
    """``reopened_at`` is one history under two ceilings, and this says so.

    The lowered-ceiling clause in the shared suite rests on it, so a
    ``reopened_at`` that quietly copied the records would make that case assert
    about two stores rather than about one setting change — and would pass while
    proving nothing.
    """
    store = FakeRecipientGrantStore(max_outstanding=CEILING)
    await store.record(recipient_grant(member(ALICE), grant_id="g-1", decided_at=AT))

    lowered = store.reopened_at(0)
    await store.record(recipient_grant(member("bob@example.com"), grant_id="g-2"))

    assert {held.id for held in await lowered.export()} == {"g-1", "g-2"}
