"""The canonical FakeIdentityStore passes the shared conformance suite (ADR-0366 §11).

This is what lets the lanes that read who sent an input from a link, and those that list
and lower links, trust ``ai_assistant.testing.FakeIdentityStore`` as a stand-in for the
store in ``memory/``: it is held to the same contract. Below the binding, what only the
fake has: the fault it can be told to raise, the ids an injected ``new_id`` mints, and the
second identity a test can give it to reach §5:5's rules on who may lower a link and who
may withdraw a lowering.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from identity_store_contract import (
    BY_THE_OWNER,
    LINE,
    PHONE,
    IdentityStoreContract,
    IdentityStoreFactory,
    ticking,
    written_id,
)

from ai_assistant.core.errors import IdentityStoreError
from ai_assistant.core.types import (
    OWNER_PERSON_ID,
    Account,
    LinkAct,
    LinkActHow,
    LinkRefusal,
    LinkWrite,
    LinkWriteKind,
    Sureness,
)
from ai_assistant.testing import FakeIdentityStore

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from datetime import datetime

    from ai_assistant.core.protocols import IdentityStore

pytestmark = pytest.mark.anyio

#: A second identity, which only a test gives the fake (no member adds one).
SAM = "person:sam"
SAMS_PHONE = Account(kind="conversation", identifier="sams-phone.tailnet.example")


class TestFakeIdentityStoreContract(IdentityStoreContract):
    """Runs FakeIdentityStore through the shared IdentityStore suite."""

    @pytest.fixture
    def factory(self) -> IdentityStoreFactory:
        def build(
            *, configured: Sequence[Account] = (), now: Callable[[], datetime] | None = None
        ) -> IdentityStore:
            if now is None:
                return FakeIdentityStore(configured=configured)
            return FakeIdentityStore(configured=configured, now=now)

        return build


async def test_an_arranged_fault_fails_the_next_member_and_touches_nothing() -> None:
    store = FakeIdentityStore()
    store.fail_next()

    with pytest.raises(IdentityStoreError):
        await store.link(OWNER_PERSON_ID, PHONE, act=BY_THE_OWNER)

    assert await store.find_link(PHONE) is None


async def test_an_id_a_held_record_carries_is_never_minted_again() -> None:
    store = FakeIdentityStore(now=ticking(), new_id=lambda kind: "record:one")
    link_id = written_id(await store.link(OWNER_PERSON_ID, LINE, act=BY_THE_OWNER))
    assert link_id == "record:one"
    before = await store.export()

    with pytest.raises(IdentityStoreError, match="already carries"):
        await store.lower(link_id, Sureness.NONE, by=OWNER_PERSON_ID)
    with pytest.raises(IdentityStoreError, match="already carries"):
        await store.link(OWNER_PERSON_ID, PHONE, act=BY_THE_OWNER)

    assert await store.export() == before


async def _with_sam() -> tuple[FakeIdentityStore, str, str]:
    """A store holding Sam beside the owner, with a link of each and a lowering by each."""
    store = FakeIdentityStore(now=ticking())
    store.hold_identity(SAM)
    owners = written_id(await store.link(OWNER_PERSON_ID, LINE, act=BY_THE_OWNER))
    sams = written_id(
        await store.link(SAM, SAMS_PHONE, act=LinkAct(how=LinkActHow.OWN_ACT, by=SAM))
    )
    return store, owners, sams


async def test_the_person_a_link_identifies_may_lower_it_and_so_may_the_owner() -> None:
    """§5:5: "The owner, or the person a link identifies, may lower that link's level"."""
    store, _, sams = await _with_sam()

    by_sam = await store.lower(sams, Sureness.WEAK, by=SAM)
    by_the_owner = await store.lower(sams, Sureness.NONE, by=OWNER_PERSON_ID)

    assert by_sam.kind is LinkWriteKind.WRITTEN
    assert by_the_owner.kind is LinkWriteKind.WRITTEN


async def test_a_lowering_by_someone_neither_the_owner_nor_the_links_person_is_refused() -> None:
    store, owners, _ = await _with_sam()
    before = await store.export()

    refused = await store.lower(owners, Sureness.NONE, by=SAM)

    assert refused == LinkWrite(kind=LinkWriteKind.REFUSED, refusal=LinkRefusal.NOT_ALLOWED)
    assert await store.export() == before


async def test_a_lowering_is_withdrawn_only_by_whoever_made_it() -> None:
    """§5:5: "Each lowering stands until whoever made it withdraws it" — the owner too."""
    store, _, sams = await _with_sam()
    sams_lowering = written_id(await store.lower(sams, Sureness.WEAK, by=SAM))
    owners_lowering = written_id(await store.lower(sams, Sureness.NONE, by=OWNER_PERSON_ID))
    before = await store.export()

    by_the_owner = await store.withdraw_lowering(sams_lowering, by=OWNER_PERSON_ID)
    by_sam = await store.withdraw_lowering(owners_lowering, by=SAM)

    not_allowed = LinkWrite(kind=LinkWriteKind.REFUSED, refusal=LinkRefusal.NOT_ALLOWED)
    assert by_the_owner == not_allowed
    assert by_sam == not_allowed
    assert await store.export() == before
    assert (await store.withdraw_lowering(sams_lowering, by=SAM)).kind is LinkWriteKind.WRITTEN


async def test_an_account_linked_to_one_identity_is_not_linked_to_another() -> None:
    store, owners, _ = await _with_sam()
    before = await store.export()

    refused = await store.link(SAM, LINE, act=LinkAct(how=LinkActHow.OWN_ACT, by=SAM))

    assert refused == LinkWrite(kind=LinkWriteKind.REFUSED, refusal=LinkRefusal.ALREADY_LINKED)
    assert await store.export() == before
    found = await store.find_link(LINE)
    assert found is not None
    assert found.id == owners
    assert found.person_id == OWNER_PERSON_ID


async def test_holding_an_identity_twice_changes_nothing() -> None:
    store = FakeIdentityStore(now=ticking())
    store.hold_identity(SAM)
    before = await store.export()

    store.hold_identity(SAM)

    assert await store.export() == before
    assert [one.id for one in before.identities] == [OWNER_PERSON_ID, SAM]


def test_a_malformed_configured_account_is_a_value_error() -> None:
    with pytest.raises(ValueError, match="configured account"):
        FakeIdentityStore(configured=("424242",))  # type: ignore[arg-type]  # the malformed argument under test
