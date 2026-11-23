"""Shared conformance suite for the IdentityStore Protocol (ADR-0366 §2, §3, §5:5).

Every ``IdentityStore`` implementation must pass this suite (CONTRIBUTING, "Protocol
conformance suites"). A concrete test subclasses :class:`IdentityStoreContract` and
supplies two fixtures: ``factory``, which builds a subject as opened, holding the owner's
identity, with the configured accounts it is handed linked, and a chosen clock; and
``reopen``, which opens a subject again under a new configuration, as the hub's next
start does.

The cases follow the contract: the owner's identity from the start (§2:5); the
configured accounts followed by the owner's act as the store opens, linked when newly
named and ended when no longer (#3642); a link recorded from an act naming whose it is,
a standing link tying an account to one identity at most, and a link ended when its act
no longer stands (§3:1); finding the standing link an account is tied to, exactly
(§4:1); a lowering, its repetition, its withdrawal, and the level that results (§5:3,
§5:5); the export; and malformed arguments refused before anything is read. What only
one implementation owes — a persistent store's file, what survives its reopening, its
upgrade under ADR-0326, a backend fault; the fake's arranged fault — is that
implementation's own test, and so is every rule naming a second identity (§5:5's
refusals), since no member adds one.

Named ``*_contract`` (not ``test_*``) so pytest collects it only via a ``Test``-prefixed
subclass.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from itertools import count
from typing import TYPE_CHECKING, Final, Protocol

import pytest

from ai_assistant.core.channel_validation import link_level
from ai_assistant.core.protocols import IdentityStore
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

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from ai_assistant.core.types import Link

pytestmark = pytest.mark.anyio

#: An identity the store does not hold.
STRANGER: Final = "person:someone-else"

#: The first reading of the clock :func:`ticking` hands out, and its step.
START: Final = datetime(2026, 11, 23, 9, 0, tzinfo=UTC)
STEP: Final = timedelta(seconds=1)

PHONE: Final = Account(kind="conversation", identifier="phone.tailnet.example")
LAPTOP: Final = Account(kind="conversation", identifier="laptop.tailnet.example")
LINE: Final = Account(kind="telegram", identifier="424242")
#: A kind that declares no most (ADR-0366 §5:2).
MAIL: Final = Account(kind="email", identifier="robin@example.invalid")

#: The owner's admitting a device, the act a later lane records device links from.
BY_THE_OWNER: Final = LinkAct(how=LinkActHow.DEVICE, by=OWNER_PERSON_ID)
CONFIGURED: Final = LinkAct(how=LinkActHow.CONFIGURED, by=OWNER_PERSON_ID)

WRITTEN: Final = LinkWriteKind.WRITTEN
UNCHANGED: Final = LinkWriteKind.UNCHANGED
REFUSED: Final = LinkWriteKind.REFUSED


def ticking() -> Callable[[], datetime]:
    """A clock that reads :data:`START`, then one :data:`STEP` later on each reading.

    Returns:
        The clock.
    """
    seconds = count()
    return lambda: START + next(seconds) * STEP


class IdentityStoreFactory(Protocol):
    """Builds a subject as opened, with the accounts configured and the clock given."""

    def __call__(
        self, *, configured: Sequence[Account] = (), now: Callable[[], datetime] | None = None
    ) -> IdentityStore: ...


class IdentityStoreReopener(Protocol):
    """Opens a subject again, as the hub's next start does, under ``configured``."""

    def __call__(
        self, store: IdentityStore, *, configured: Sequence[Account] = ()
    ) -> IdentityStore: ...


def written_id(write: LinkWrite) -> str:
    """The record a write wrote, asserting that it wrote one.

    Args:
        write: What a write returned.

    Returns:
        Its record's id.
    """
    assert write.kind is WRITTEN, write
    assert write.record_id is not None
    return write.record_id


async def linked(store: IdentityStore, account: Account) -> Link:
    """The link ``account`` is tied to, asserting that one is.

    Args:
        store: The subject.
        account: The account.

    Returns:
        Its link.
    """
    found = await store.find_link(account)
    assert found is not None, account
    return found


class IdentityStoreContract:
    """Behaviour every IdentityStore implementation must exhibit."""

    @pytest.fixture
    def factory(self) -> IdentityStoreFactory:
        """Build a subject as opened. Overridden per implementation."""
        raise NotImplementedError

    @pytest.fixture
    def reopen(self) -> IdentityStoreReopener:
        """Open a subject again under a new configuration. Overridden per implementation."""
        raise NotImplementedError

    @pytest.fixture
    def store(self, factory: IdentityStoreFactory) -> IdentityStore:
        """A subject holding the owner's identity alone, with no account configured."""
        return factory(now=ticking())

    # --- the owner's identity (§2:5) ---------------------------------------------------

    def test_it_satisfies_the_protocol(self, store: IdentityStore) -> None:
        assert isinstance(store, IdentityStore)

    async def test_it_holds_the_owners_identity_from_the_start(
        self, factory: IdentityStoreFactory
    ) -> None:
        store = factory(now=ticking())

        owner = await store.identity(OWNER_PERSON_ID)

        assert owner is not None
        assert owner.id == OWNER_PERSON_ID
        assert owner.created_at == START
        assert owner.links == ()
        exported = await store.export()
        assert [one.id for one in exported.identities] == [OWNER_PERSON_ID]

    async def test_an_identity_it_does_not_hold_reads_as_none(self, store: IdentityStore) -> None:
        assert await store.identity(STRANGER) is None

    # --- the configured accounts (#3642) -----------------------------------------------

    async def test_each_configured_account_is_linked_to_the_owner_by_their_act(
        self, factory: IdentityStoreFactory
    ) -> None:
        store = factory(configured=(PHONE, LINE), now=ticking())

        owner = await store.identity(OWNER_PERSON_ID)

        assert owner is not None
        assert [one.account for one in owner.links] == [PHONE, LINE]
        assert all(one.act == CONFIGURED for one in owner.links)
        assert all(one.person_id == OWNER_PERSON_ID for one in owner.links)
        assert all(one.lowerings == () for one in owner.links)
        assert (await linked(store, LINE)).id == owner.links[1].id

    async def test_an_account_configured_twice_is_linked_once(
        self, factory: IdentityStoreFactory
    ) -> None:
        store = factory(configured=(LINE, PHONE, LINE), now=ticking())

        owner = await store.identity(OWNER_PERSON_ID)

        assert owner is not None
        assert [one.account for one in owner.links] == [LINE, PHONE]
        assert len({one.id for one in owner.links}) == 2

    async def test_a_configured_account_is_one_a_later_link_finds_unchanged(
        self, factory: IdentityStoreFactory
    ) -> None:
        store = factory(configured=(LINE,), now=ticking())
        held = await linked(store, LINE)

        again = await store.link(OWNER_PERSON_ID, LINE, act=BY_THE_OWNER)

        assert again == LinkWrite(kind=UNCHANGED, record_id=held.id)
        assert (await linked(store, LINE)).act == CONFIGURED

    async def test_an_account_configured_later_is_linked_at_the_next_open(
        self, factory: IdentityStoreFactory, reopen: IdentityStoreReopener
    ) -> None:
        store = reopen(factory(configured=(PHONE,), now=ticking()), configured=(PHONE, LINE))

        owner = await store.identity(OWNER_PERSON_ID)

        assert owner is not None
        assert [one.account for one in owner.standing_links] == [PHONE, LINE]
        assert all(one.act == CONFIGURED for one in owner.links)

    async def test_a_configured_link_whose_account_is_no_longer_named_is_ended(
        self, factory: IdentityStoreFactory, reopen: IdentityStoreReopener
    ) -> None:
        """A link stands only while the act it was recorded from stands (§3:1)."""
        first = factory(configured=(PHONE, LINE), now=ticking())
        line = await linked(first, LINE)
        lowering_id = written_id(await first.lower(line.id, Sureness.WEAK, by=OWNER_PERSON_ID))

        store = reopen(first, configured=(PHONE,))

        assert await store.find_link(LINE) is None
        owner = await store.identity(OWNER_PERSON_ID)
        assert owner is not None
        assert [one.account for one in owner.standing_links] == [PHONE]
        ended = next(one for one in owner.links if one.id == line.id)
        assert not ended.standing
        assert ended.ended_at is not None
        assert [one.id for one in ended.lowerings] == [lowering_id]

    async def test_an_account_configured_again_is_a_new_link(
        self, factory: IdentityStoreFactory, reopen: IdentityStoreReopener
    ) -> None:
        first = factory(configured=(LINE,), now=ticking())
        old = await linked(first, LINE)
        written_id(await first.lower(old.id, Sureness.WEAK, by=OWNER_PERSON_ID))

        store = reopen(reopen(first, configured=()), configured=(LINE,))

        again = await linked(store, LINE)
        assert again.id != old.id
        assert again.act == CONFIGURED
        assert again.lowerings == ()
        owner = await store.identity(OWNER_PERSON_ID)
        assert owner is not None
        assert [(one.id, one.standing) for one in owner.links] == [
            (old.id, False),
            (again.id, True),
        ]

    async def test_a_link_from_another_act_is_left_as_it_is_by_the_configuration(
        self, factory: IdentityStoreFactory, reopen: IdentityStoreReopener
    ) -> None:
        first = factory(now=ticking())
        written_id(await first.link(OWNER_PERSON_ID, PHONE, act=BY_THE_OWNER))
        before = await first.export()

        store = reopen(first, configured=())

        assert await store.export() == before
        assert (await linked(store, PHONE)).act == BY_THE_OWNER

    async def test_a_configured_account_another_act_linked_keeps_that_link(
        self, factory: IdentityStoreFactory, reopen: IdentityStoreReopener
    ) -> None:
        first = factory(now=ticking())
        link_id = written_id(await first.link(OWNER_PERSON_ID, PHONE, act=BY_THE_OWNER))

        store = reopen(reopen(first, configured=(PHONE,)), configured=())

        found = await linked(store, PHONE)
        assert (found.id, found.act) == (link_id, BY_THE_OWNER)

    # --- linking (§3:1) ----------------------------------------------------------------

    async def test_a_link_ties_the_account_to_the_identity_by_the_act_named(
        self, factory: IdentityStoreFactory
    ) -> None:
        store = factory(now=ticking())

        link_id = written_id(await store.link(OWNER_PERSON_ID, PHONE, act=BY_THE_OWNER))

        found = await linked(store, PHONE)
        assert found.id == link_id
        assert found.person_id == OWNER_PERSON_ID
        assert found.account == PHONE
        assert found.act == BY_THE_OWNER
        assert found.made_at == START + STEP  # the owner's creation read the clock first
        assert found.lowerings == ()
        owner = await store.identity(OWNER_PERSON_ID)
        assert owner is not None
        assert owner.links == (found,)

    async def test_links_are_listed_in_the_order_made(self, store: IdentityStore) -> None:
        first = written_id(await store.link(OWNER_PERSON_ID, LINE, act=BY_THE_OWNER))
        second = written_id(await store.link(OWNER_PERSON_ID, PHONE, act=BY_THE_OWNER))
        third = written_id(await store.link(OWNER_PERSON_ID, LAPTOP, act=BY_THE_OWNER))

        owner = await store.identity(OWNER_PERSON_ID)

        assert owner is not None
        assert [one.id for one in owner.links] == [first, second, third]
        assert len({first, second, third}) == 3

    async def test_linking_an_account_already_linked_to_that_identity_changes_nothing(
        self, store: IdentityStore
    ) -> None:
        link_id = written_id(await store.link(OWNER_PERSON_ID, PHONE, act=BY_THE_OWNER))
        before = await store.export()

        again = await store.link(OWNER_PERSON_ID, PHONE, act=CONFIGURED)

        assert again == LinkWrite(kind=UNCHANGED, record_id=link_id)
        assert await store.export() == before

    @pytest.mark.parametrize(
        ("person_id", "act"),
        [
            (STRANGER, BY_THE_OWNER),
            (OWNER_PERSON_ID, LinkAct(how=LinkActHow.DEVICE, by=STRANGER)),
        ],
        ids=["to-an-identity-not-held", "by-an-identity-not-held"],
    )
    async def test_a_link_naming_an_identity_it_does_not_hold_is_refused(
        self, store: IdentityStore, person_id: str, act: LinkAct
    ) -> None:
        before = await store.export()

        refused = await store.link(person_id, PHONE, act=act)

        assert refused == LinkWrite(kind=REFUSED, refusal=LinkRefusal.UNKNOWN_PERSON)
        assert await store.export() == before
        assert await store.find_link(PHONE) is None

    # --- ending a link (§3:1) ----------------------------------------------------------

    async def test_an_ended_link_is_kept_and_ties_nothing(self, store: IdentityStore) -> None:
        link_id = written_id(await store.link(OWNER_PERSON_ID, PHONE, act=BY_THE_OWNER))

        ended = await store.end_link(link_id)

        assert ended == LinkWrite(kind=WRITTEN, record_id=link_id)
        assert await store.find_link(PHONE) is None
        owner = await store.identity(OWNER_PERSON_ID)
        assert owner is not None
        assert owner.standing_links == ()
        assert [one.id for one in owner.links] == [link_id]
        assert owner.links[0].ended_at == START + 2 * STEP

    async def test_ending_an_ended_link_changes_nothing(self, store: IdentityStore) -> None:
        link_id = written_id(await store.link(OWNER_PERSON_ID, PHONE, act=BY_THE_OWNER))
        written_id(await store.end_link(link_id))
        before = await store.export()

        again = await store.end_link(link_id)

        assert again == LinkWrite(kind=UNCHANGED, record_id=link_id)
        assert await store.export() == before

    async def test_ending_a_link_it_does_not_hold_is_refused(self, store: IdentityStore) -> None:
        refused = await store.end_link("link:missing")

        assert refused == LinkWrite(kind=REFUSED, refusal=LinkRefusal.UNKNOWN_RECORD)

    async def test_an_account_whose_link_ended_is_linked_anew(self, store: IdentityStore) -> None:
        old = written_id(await store.link(OWNER_PERSON_ID, PHONE, act=BY_THE_OWNER))
        written_id(await store.end_link(old))

        new = written_id(await store.link(OWNER_PERSON_ID, PHONE, act=BY_THE_OWNER))

        assert new != old
        assert (await linked(store, PHONE)).id == new

    async def test_an_ended_link_is_not_lowered(self, store: IdentityStore) -> None:
        link_id = written_id(await store.link(OWNER_PERSON_ID, LINE, act=BY_THE_OWNER))
        written_id(await store.end_link(link_id))
        before = await store.export()

        refused = await store.lower(link_id, Sureness.NONE, by=OWNER_PERSON_ID)

        assert refused == LinkWrite(kind=REFUSED, refusal=LinkRefusal.UNKNOWN_RECORD)
        assert await store.export() == before

    # --- finding a link (§4:1) ---------------------------------------------------------

    async def test_an_account_no_link_ties_finds_nothing(self, store: IdentityStore) -> None:
        assert await store.find_link(PHONE) is None

    async def test_an_account_is_matched_by_its_kind_and_identifier_exactly(
        self, store: IdentityStore
    ) -> None:
        written_id(await store.link(OWNER_PERSON_ID, PHONE, act=BY_THE_OWNER))

        assert await store.find_link(Account(kind="telegram", identifier=PHONE.identifier)) is None
        assert (
            await store.find_link(Account(kind="conversation", identifier="Phone.tailnet.example"))
            is None
        )
        assert (
            await store.find_link(Account(kind="conversation", identifier=" phone.tailnet.example"))
            is None
        )
        assert (await linked(store, PHONE)).account == PHONE

    async def test_the_same_identifier_on_two_kinds_is_two_accounts(
        self, store: IdentityStore
    ) -> None:
        on_the_chat = Account(kind="conversation", identifier="424242")

        first = written_id(await store.link(OWNER_PERSON_ID, LINE, act=BY_THE_OWNER))
        second = written_id(await store.link(OWNER_PERSON_ID, on_the_chat, act=BY_THE_OWNER))

        assert first != second
        assert (await linked(store, LINE)).id == first
        assert (await linked(store, on_the_chat)).id == second

    # --- lowerings and the level (§5:3, §5:5) ------------------------------------------

    async def test_a_link_with_no_lowering_is_at_its_kinds_most(self, store: IdentityStore) -> None:
        written_id(await store.link(OWNER_PERSON_ID, LINE, act=BY_THE_OWNER))
        written_id(await store.link(OWNER_PERSON_ID, MAIL, act=BY_THE_OWNER))

        assert link_level(await linked(store, LINE)) is Sureness.NORMAL
        assert link_level(await linked(store, MAIL)) is Sureness.NONE

    async def test_a_lowering_stands_on_the_link_and_lowers_its_level(
        self, store: IdentityStore
    ) -> None:
        link_id = written_id(await store.link(OWNER_PERSON_ID, LINE, act=BY_THE_OWNER))

        lowering_id = written_id(await store.lower(link_id, Sureness.WEAK, by=OWNER_PERSON_ID))

        found = await linked(store, LINE)
        assert [one.id for one in found.lowerings] == [lowering_id]
        lowering = found.lowerings[0]
        assert lowering.level is Sureness.WEAK
        assert lowering.by == OWNER_PERSON_ID
        assert lowering.made_at == START + 2 * STEP
        assert lowering.standing
        assert found.standing_lowerings == (lowering,)
        assert link_level(found) is Sureness.WEAK

    async def test_the_lowest_standing_lowering_sets_the_level(self, store: IdentityStore) -> None:
        link_id = written_id(await store.link(OWNER_PERSON_ID, LINE, act=BY_THE_OWNER))
        written_id(await store.lower(link_id, Sureness.WEAK, by=OWNER_PERSON_ID))
        lowest = written_id(await store.lower(link_id, Sureness.NONE, by=OWNER_PERSON_ID))

        assert link_level(await linked(store, LINE)) is Sureness.NONE

        written_id(await store.withdraw_lowering(lowest, by=OWNER_PERSON_ID))

        assert link_level(await linked(store, LINE)) is Sureness.WEAK

    @pytest.mark.parametrize(
        ("account", "level"),
        [
            (LINE, Sureness.NORMAL),
            (LINE, Sureness.STRONG),
            (MAIL, Sureness.NONE),
            (MAIL, Sureness.WEAK),
        ],
        ids=["normal-on-the-line", "strong-on-the-line", "none-on-mail", "weak-on-mail"],
    )
    async def test_a_level_not_below_the_kinds_most_is_no_lowering(
        self, store: IdentityStore, account: Account, level: Sureness
    ) -> None:
        link_id = written_id(await store.link(OWNER_PERSON_ID, account, act=BY_THE_OWNER))
        before = await store.export()

        refused = await store.lower(link_id, level, by=OWNER_PERSON_ID)

        assert refused == LinkWrite(kind=REFUSED, refusal=LinkRefusal.NOT_A_LOWERING)
        assert await store.export() == before

    async def test_a_repeated_lowering_is_unchanged_and_makes_no_second(
        self, store: IdentityStore
    ) -> None:
        link_id = written_id(await store.link(OWNER_PERSON_ID, LINE, act=BY_THE_OWNER))
        lowering_id = written_id(await store.lower(link_id, Sureness.WEAK, by=OWNER_PERSON_ID))
        before = await store.export()

        again = await store.lower(link_id, Sureness.WEAK, by=OWNER_PERSON_ID)

        assert again == LinkWrite(kind=UNCHANGED, record_id=lowering_id)
        assert await store.export() == before

    async def test_a_lowering_at_a_level_once_withdrawn_is_made_anew(
        self, store: IdentityStore
    ) -> None:
        link_id = written_id(await store.link(OWNER_PERSON_ID, LINE, act=BY_THE_OWNER))
        first = written_id(await store.lower(link_id, Sureness.WEAK, by=OWNER_PERSON_ID))
        written_id(await store.withdraw_lowering(first, by=OWNER_PERSON_ID))

        second = written_id(await store.lower(link_id, Sureness.WEAK, by=OWNER_PERSON_ID))

        assert second != first
        assert [one.id for one in (await linked(store, LINE)).standing_lowerings] == [second]

    async def test_a_withdrawn_lowering_is_kept_and_stands_no_more(
        self, store: IdentityStore
    ) -> None:
        link_id = written_id(await store.link(OWNER_PERSON_ID, LINE, act=BY_THE_OWNER))
        lowering_id = written_id(await store.lower(link_id, Sureness.NONE, by=OWNER_PERSON_ID))

        withdrawn = await store.withdraw_lowering(lowering_id, by=OWNER_PERSON_ID)

        assert withdrawn == LinkWrite(kind=WRITTEN, record_id=lowering_id)
        found = await linked(store, LINE)
        assert [one.id for one in found.lowerings] == [lowering_id]
        assert found.lowerings[0].withdrawn_at == START + 3 * STEP
        assert not found.lowerings[0].standing
        assert found.standing_lowerings == ()
        assert link_level(found) is Sureness.NORMAL

    async def test_withdrawing_a_withdrawn_lowering_changes_nothing(
        self, store: IdentityStore
    ) -> None:
        link_id = written_id(await store.link(OWNER_PERSON_ID, LINE, act=BY_THE_OWNER))
        lowering_id = written_id(await store.lower(link_id, Sureness.NONE, by=OWNER_PERSON_ID))
        written_id(await store.withdraw_lowering(lowering_id, by=OWNER_PERSON_ID))
        before = await store.export()

        again = await store.withdraw_lowering(lowering_id, by=OWNER_PERSON_ID)

        assert again == LinkWrite(kind=UNCHANGED, record_id=lowering_id)
        assert await store.export() == before

    async def test_a_lowering_is_the_one_links_alone(self, store: IdentityStore) -> None:
        lowered = written_id(await store.link(OWNER_PERSON_ID, LINE, act=BY_THE_OWNER))
        written_id(await store.link(OWNER_PERSON_ID, PHONE, act=BY_THE_OWNER))

        written_id(await store.lower(lowered, Sureness.NONE, by=OWNER_PERSON_ID))

        assert link_level(await linked(store, LINE)) is Sureness.NONE
        assert (await linked(store, PHONE)).lowerings == ()
        assert link_level(await linked(store, PHONE)) is Sureness.NORMAL

    async def test_a_lowering_of_a_link_it_does_not_hold_is_refused(
        self, store: IdentityStore
    ) -> None:
        before = await store.export()

        refused = await store.lower("link:missing", Sureness.NONE, by=OWNER_PERSON_ID)

        assert refused == LinkWrite(kind=REFUSED, refusal=LinkRefusal.UNKNOWN_RECORD)
        assert await store.export() == before

    async def test_a_lowering_by_an_identity_it_does_not_hold_is_refused(
        self, store: IdentityStore
    ) -> None:
        link_id = written_id(await store.link(OWNER_PERSON_ID, LINE, act=BY_THE_OWNER))
        before = await store.export()

        refused = await store.lower(link_id, Sureness.NONE, by=STRANGER)

        assert refused == LinkWrite(kind=REFUSED, refusal=LinkRefusal.UNKNOWN_PERSON)
        assert await store.export() == before

    async def test_withdrawing_a_lowering_it_does_not_hold_is_refused(
        self, store: IdentityStore
    ) -> None:
        refused = await store.withdraw_lowering("lowering:missing", by=OWNER_PERSON_ID)

        assert refused == LinkWrite(kind=REFUSED, refusal=LinkRefusal.UNKNOWN_RECORD)

    async def test_a_withdrawal_by_an_identity_it_does_not_hold_is_refused(
        self, store: IdentityStore
    ) -> None:
        link_id = written_id(await store.link(OWNER_PERSON_ID, LINE, act=BY_THE_OWNER))
        lowering_id = written_id(await store.lower(link_id, Sureness.NONE, by=OWNER_PERSON_ID))
        before = await store.export()

        refused = await store.withdraw_lowering(lowering_id, by=STRANGER)

        assert refused == LinkWrite(kind=REFUSED, refusal=LinkRefusal.UNKNOWN_PERSON)
        assert await store.export() == before
        assert link_level(await linked(store, LINE)) is Sureness.NONE

    # --- the export (ADR-0004 §6) ------------------------------------------------------

    async def test_the_export_carries_every_link_and_every_lowering(
        self, factory: IdentityStoreFactory
    ) -> None:
        store = factory(configured=(PHONE,), now=ticking())
        link_id = written_id(await store.link(OWNER_PERSON_ID, LINE, act=BY_THE_OWNER))
        withdrawn = written_id(await store.lower(link_id, Sureness.NONE, by=OWNER_PERSON_ID))
        written_id(await store.withdraw_lowering(withdrawn, by=OWNER_PERSON_ID))
        standing = written_id(await store.lower(link_id, Sureness.WEAK, by=OWNER_PERSON_ID))

        exported = await store.export()

        owner = await store.identity(OWNER_PERSON_ID)
        assert exported.identities == (owner,)
        assert owner is not None
        assert [one.account for one in owner.links] == [PHONE, LINE]
        assert [one.id for one in owner.links[1].lowerings] == [withdrawn, standing]

    # --- malformed arguments, refused before anything is read --------------------------

    @pytest.mark.parametrize("person_id", ["", "   ", 7, None])
    async def test_a_malformed_identity_id_is_a_value_error(
        self, store: IdentityStore, person_id: object
    ) -> None:
        with pytest.raises(ValueError, match="person_id"):
            await store.identity(person_id)  # type: ignore[arg-type]  # the malformed argument under test
        with pytest.raises(ValueError, match="person_id"):
            await store.link(person_id, PHONE, act=BY_THE_OWNER)  # type: ignore[arg-type]  # the malformed argument under test

    @pytest.mark.parametrize(
        "account",
        [
            "phone.tailnet.example",
            None,
            Account.model_construct(kind="conversation", identifier="   "),
            Account.model_construct(kind="", identifier="phone"),
        ],
        ids=["a-str", "none", "blank-identifier", "blank-kind"],
    )
    async def test_a_malformed_account_is_a_value_error(
        self, store: IdentityStore, account: object
    ) -> None:
        with pytest.raises(ValueError, match="account"):
            await store.find_link(account)  # type: ignore[arg-type]  # the malformed argument under test
        with pytest.raises(ValueError, match="account"):
            await store.link(OWNER_PERSON_ID, account, act=BY_THE_OWNER)  # type: ignore[arg-type]  # the malformed argument under test
        assert (await store.export()).identities[0].links == ()

    @pytest.mark.parametrize(
        "act",
        [None, LinkAct.model_construct(how=LinkActHow.DEVICE, by="  ")],
        ids=["none", "blank-maker"],
    )
    async def test_a_malformed_act_is_a_value_error(
        self, store: IdentityStore, act: object
    ) -> None:
        with pytest.raises(ValueError, match="act"):
            await store.link(OWNER_PERSON_ID, PHONE, act=act)  # type: ignore[arg-type]  # the malformed argument under test
        assert await store.find_link(PHONE) is None

    @pytest.mark.parametrize("level", ["none", 0, None])
    async def test_a_level_that_is_not_one_is_a_value_error(
        self, store: IdentityStore, level: object
    ) -> None:
        link_id = written_id(await store.link(OWNER_PERSON_ID, LINE, act=BY_THE_OWNER))

        with pytest.raises(ValueError, match="level"):
            await store.lower(link_id, level, by=OWNER_PERSON_ID)  # type: ignore[arg-type]  # the malformed argument under test
        assert (await linked(store, LINE)).lowerings == ()

    @pytest.mark.parametrize("blank", ["", "  ", None])
    async def test_a_malformed_record_or_maker_is_a_value_error(
        self, store: IdentityStore, blank: object
    ) -> None:
        link_id = written_id(await store.link(OWNER_PERSON_ID, LINE, act=BY_THE_OWNER))
        lowering_id = written_id(await store.lower(link_id, Sureness.NONE, by=OWNER_PERSON_ID))

        with pytest.raises(ValueError, match="link_id"):
            await store.lower(blank, Sureness.NONE, by=OWNER_PERSON_ID)  # type: ignore[arg-type]  # the malformed argument under test
        with pytest.raises(ValueError, match="by"):
            await store.lower(link_id, Sureness.NONE, by=blank)  # type: ignore[arg-type]  # the malformed argument under test
        with pytest.raises(ValueError, match="lowering_id"):
            await store.withdraw_lowering(blank, by=OWNER_PERSON_ID)  # type: ignore[arg-type]  # the malformed argument under test
        with pytest.raises(ValueError, match="by"):
            await store.withdraw_lowering(lowering_id, by=blank)  # type: ignore[arg-type]  # the malformed argument under test
        with pytest.raises(ValueError, match="link_id"):
            await store.end_link(blank)  # type: ignore[arg-type]  # the malformed argument under test
        assert [one.id for one in (await linked(store, LINE)).standing_lowerings] == [lowering_id]
