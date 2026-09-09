"""The canonical ``DestinationTrustStore`` fake, through the shared suite (ADR-0238 §14).

The triad's binding: without a ``Test…Contract`` subclass the abstract suite collects
nothing and the fake is unverified however many files exist
(``CONTRIBUTING.md`` → "Adding a Protocol"). Plus the arms that are about *this*
subject rather than about the contract — the scripted faults, and the one asymmetry
ADR-0238 §1 puts between ``trust_of`` and every other member.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from destination_trust_store_contract import (
    AT,
    LATER,
    DestinationTrustStoreContract,
    trust_record,
)
from recipient_builders import ALICE, member

from ai_assistant.core.errors import InvalidDestinationTrustError
from ai_assistant.core.types import DestinationTrust
from ai_assistant.testing import FakeDestinationTrustStore


class TestFakeDestinationTrustStoreContract(DestinationTrustStoreContract):
    """The canonical fake against every clause of ADR-0238 §1."""

    @pytest.fixture
    def store(self) -> FakeDestinationTrustStore:
        return FakeDestinationTrustStore()

    def concurrently_openable(self) -> bool:
        """This store does not outlive its object, so a second handle is unreachable.

        The posture the ledger and spend contracts already take for the same reason,
        and it costs the fake nothing: durability is a property of the *durable*
        implementation, which is bound to the same suite one module over and does not
        skip this case.
        """
        return False


async def test_a_seeded_history_is_applied_under_the_write_invariants() -> None:
    """A history a conforming store could not hold is refused at construction.

    Refused *here* rather than at the first read, because a fake that quietly held two
    live records over one destination set would certify a consumer against the very
    state ADR-0238 §1's duplicate refusal exists to make unreachable.
    """
    first = trust_record(ALICE, record_id="t-1")

    with pytest.raises(InvalidDestinationTrustError):
        FakeDestinationTrustStore([first, trust_record(ALICE, record_id="t-2")])


async def test_a_seeded_history_is_readable() -> None:
    """The ordinary case beside the refusal above: what is seeded is what is held."""
    store = FakeDestinationTrustStore([trust_record(ALICE, record_id="t-1")])

    assert await store.trust_of([member(ALICE)]) is DestinationTrust.USER_CHOSEN


async def test_a_scripted_write_fault_reaches_both_write_members() -> None:
    """Both writes fail closed on a store fault, as one error class (ADR-0238 §13).

    §13 closes this decision's ``core/errors.py`` surface at one name, so a refusal and
    a fault arrive as the same class — which is ``InvalidRecipientGrantError``'s own
    ground for one class rather than several, the caller's recourse being identical.
    """
    store = FakeDestinationTrustStore([trust_record(ALICE, record_id="t-1")])
    store.fail_writes()

    with pytest.raises(InvalidDestinationTrustError):
        await store.record(trust_record("bob@example.com", record_id="t-2"))
    with pytest.raises(InvalidDestinationTrustError):
        await store.revoke("t-1", LATER)


async def test_a_scripted_read_fault_reaches_the_two_reads_and_not_the_trust_answer() -> None:
    """ADR-0238 §1's asymmetry, and it is a clause rather than a gap.

    ``live`` and ``export`` are the surface read and the data right, so a store that
    cannot be read owes their callers an error. ``trust_of`` is the read a *policy
    path* depends on, and §1 rules the trust ``UNCHOSEN`` "in every other case,
    including … where a record cannot be read" — so an unreadable store is an **answer**
    there, and the fail-closed direction is taken by answering rather than by raising.
    """
    store = FakeDestinationTrustStore([trust_record(ALICE, record_id="t-1")])
    store.fail_reads()

    with pytest.raises(InvalidDestinationTrustError):
        await store.live()
    with pytest.raises(InvalidDestinationTrustError):
        await store.export()
    assert await store.trust_of([member(ALICE)]) is DestinationTrust.USER_CHOSEN


async def test_a_store_that_cannot_read_answers_unchosen() -> None:
    """The other half of the same clause, driven through the hook made for it.

    ``break_trust_reads`` scripts what ``fail_reads`` deliberately cannot: a
    ``trust_of`` that has no records to consult. The answer is ``UNCHOSEN`` — a
    destination the store cannot vouch for is one nobody chose, which is the direction
    §1 fails in everywhere.
    """
    store = FakeDestinationTrustStore([trust_record(ALICE, record_id="t-1")])
    assert await store.trust_of([member(ALICE)]) is DestinationTrust.USER_CHOSEN

    store.break_trust_reads()

    assert await store.trust_of([member(ALICE)]) is DestinationTrust.UNCHOSEN


async def test_a_revocation_is_the_only_field_a_record_ever_changes() -> None:
    """§1's "rewrites no recorded decision", over the fake's own stored state.

    The durable store enforces this with a trigger; the fake holds it by construction,
    and this is where that claim is checked rather than asserted.
    """
    recorded = trust_record(ALICE, record_id="t-1", established_at=AT)
    store = FakeDestinationTrustStore([recorded])

    await store.revoke("t-1", LATER)

    (kept,) = await store.export()
    assert kept.model_dump(exclude={"revoked_at"}) == recorded.model_dump(exclude={"revoked_at"})
    assert kept.revoked_at == LATER


async def test_the_fake_hands_back_no_object_it_keeps() -> None:
    """Detachment on the write path as well as the read path.

    A caller that could rewrite the record it handed over — through ``__dict__``, which
    ``frozen=True`` does not stop — would widen an authorisation after the store
    accepted it. The fake revalidates on the way in for that reason and not for a
    test's convenience.
    """
    recorded = trust_record(ALICE, record_id="t-1")
    store = FakeDestinationTrustStore()
    await store.record(recorded)

    recorded.__dict__["established_at"] = AT + timedelta(days=365)

    (kept,) = await store.live()
    assert kept.established_at == AT
