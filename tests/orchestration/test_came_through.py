"""ADR-0378 §4:3 to §4:7 and §6:1: a hub chat message or tap through another device.

Where a hub chat message came through a device other than the one it is written from, its
sender is read from both devices' links: the identity both tie, at the lower level; no
identified person, at none, where either has no standing link or they tie different
identities; and, where either read gets no answer, ADR-0374 rules it as written. One that
came through the device it is written from is read exactly as before. The owner's own use
today reads as it did.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final, cast

import pytest
from structlog.testing import capture_logs

from ai_assistant.core.errors import IdentityStoreError, OversizedValueError
from ai_assistant.core.types import (
    OWNER_PERSON_ID,
    Account,
    ChatChanges,
    InputSender,
    LinkAct,
    LinkActHow,
    MessageAddedChange,
    MessageAuthor,
    NewMessage,
    RecordHome,
    Sureness,
    TranscriptMessage,
    TranscriptPage,
    UserMessage,
)
from ai_assistant.orchestration.conversations import (
    check_message_fits,
    fit_changes,
    fit_transcript,
)
from ai_assistant.orchestration.work_facts import (
    HUB_MACHINE,
    LINKS_UNREAD,
    NO_LINK,
    chat_account,
    chat_sender_of,
    chat_senders_of,
    sender_of,
)
from ai_assistant.testing import FakeIdentityStore

if TYPE_CHECKING:
    from ai_assistant.core.protocols import IdentityStore
    from ai_assistant.core.types import Link

_AT: Final = datetime(2026, 11, 24, 9, 0, tzinfo=UTC)

#: The hub's own machine; a browser device a gateway names; a gateway; an enrolled machine;
#: a device nobody linked; a device linked to someone else.
_HUB: Final = "hub"
_BROWSER: Final = "web-leo"
_GATEWAY: Final = "gateway-1"
_LAPTOP: Final = "laptop"
_STRANGER: Final = "device-stranger"
_OTHERS: Final = "device-other"
_OTHER_PERSON: Final = "person:other"

_OWNER: Final = InputSender(person=OWNER_PERSON_ID, level=Sureness.NORMAL)
_OWNER_UNREAD: Final = InputSender(person=OWNER_PERSON_ID, level=Sureness.NORMAL, links_unread=True)


async def _identities() -> FakeIdentityStore:
    """The owner's devices linked as a hub links them, and one device linked to another."""
    store = FakeIdentityStore(
        configured=[
            HUB_MACHINE,
            *(
                Account(kind="conversation", identifier=one)
                for one in (_BROWSER, _GATEWAY, _LAPTOP)
            ),
        ],
        now=lambda: _AT,
    )
    store.hold_identity(_OTHER_PERSON)
    others = chat_account(_OTHERS)
    assert others is not None
    await store.link(_OTHER_PERSON, others, act=LinkAct(how=LinkActHow.DEVICE, by=OWNER_PERSON_ID))
    return store


async def _lower(store: FakeIdentityStore, device: str, level: Sureness) -> None:
    account = chat_account(device)
    assert account is not None
    link = await store.find_link(account)
    assert link is not None
    await store.lower(link.id, level, by=OWNER_PERSON_ID)


class _Unreadable:
    """An identity store that cannot read one account, as a store fault does."""

    def __init__(self, store: IdentityStore, unreadable: str) -> None:
        self.store = store
        self.unreadable = chat_account(unreadable)

    async def find_link(self, account: Account) -> Link | None:
        if account == self.unreadable:
            raise IdentityStoreError("unreadable")
        return await self.store.find_link(account)


# --- §4:6: through the device it is written from ---------------------------------------


@pytest.mark.parametrize("device", [_HUB, _BROWSER, _LAPTOP, _STRANGER, _OTHERS])
async def test_a_message_through_its_own_device_reads_as_before(device: str) -> None:
    """ADR-0378 §4:6: one device's link alone, exactly as :func:`sender_of` reads it."""
    store = await _identities()
    before = await sender_of(store, chat_account(device), stage="t")
    assert await chat_sender_of(store, device, device, stage="t") == before
    assert await chat_sender_of(store, device, None, stage="t") == before


# --- §4:3: both links ------------------------------------------------------------------


async def test_both_links_tie_the_owner_at_the_lower_level() -> None:
    """ADR-0378 §4:3, ADR-0373 §2:9: the identity both tie, at the lower of the two."""
    store = await _identities()
    assert await chat_sender_of(store, _BROWSER, _GATEWAY, stage="t") == _OWNER
    await _lower(store, _GATEWAY, Sureness.WEAK)
    assert await chat_sender_of(store, _BROWSER, _GATEWAY, stage="t") == InputSender(
        person=OWNER_PERSON_ID, level=Sureness.WEAK
    )
    await _lower(store, _BROWSER, Sureness.NONE)
    lowered = await chat_sender_of(store, _BROWSER, _GATEWAY, stage="t")
    assert lowered == InputSender(person=OWNER_PERSON_ID, level=Sureness.NONE)
    assert not lowered.identified


async def test_a_lowering_of_the_gateway_binds_what_comes_through_it() -> None:
    """ADR-0378 §4 prose: a lowering of the connecting device's link binds every message
    through it, whatever the named device's link says."""
    store = await _identities()
    await _lower(store, _GATEWAY, Sureness.NONE)
    assert await chat_sender_of(store, _BROWSER, _BROWSER, stage="t") == _OWNER
    assert await chat_sender_of(store, _BROWSER, _GATEWAY, stage="t") == InputSender(
        person=OWNER_PERSON_ID, level=Sureness.NONE
    )


@pytest.mark.parametrize(
    ("device", "through"),
    [
        (_STRANGER, _GATEWAY),
        (_BROWSER, _STRANGER),
        (_OTHERS, _GATEWAY),
        (_BROWSER, _OTHERS),
    ],
    ids=["written-unlinked", "through-unlinked", "written-other", "through-other"],
)
async def test_no_standing_link_or_two_identities_is_no_one_at_none(
    device: str, through: str
) -> None:
    """ADR-0378 §4:3: either has no standing link, or they tie different identities."""
    store = await _identities()
    found = await chat_sender_of(store, device, through, stage="t")
    assert found == NO_LINK
    assert not found.links_unread


async def test_an_ended_link_on_either_device_is_no_one() -> None:
    """ADR-0378 §4:3: an ended link is no standing link."""
    store = await _identities()
    account = chat_account(_GATEWAY)
    assert account is not None
    link = await store.find_link(account)
    assert link is not None
    await store.end_link(link.id)
    assert await chat_sender_of(store, _BROWSER, _GATEWAY, stage="t") == NO_LINK


# --- §4:5: a read that gets no answer ----------------------------------------------------


@pytest.mark.parametrize("unreadable", [_BROWSER, _GATEWAY])
async def test_either_read_getting_no_answer_is_adr_0374s(unreadable: str) -> None:
    """ADR-0378 §4:5, ADR-0374 §2:2: an unidentified sender's, at none, marked; the
    failed read logged once, with the reader and the reason alone."""
    store = cast("IdentityStore", _Unreadable(await _identities(), unreadable))
    with capture_logs() as logs:
        found = await chat_sender_of(store, _BROWSER, _GATEWAY, stage="chat_reader")
    assert found == LINKS_UNREAD
    assert logs == [
        {
            "event": "input_sender_unread",
            "reader": "chat_reader",
            "reason": "identity_store",
            "log_level": "warning",
        }
    ]


async def test_no_store_wired_is_adr_0374s_off_the_hubs_machine() -> None:
    """ADR-0378 §4:5, ADR-0374 §2:1, §3:1: with no store, a message written from another
    device through ``hub`` is no one's, at none; one written from ``hub`` stays the owner's
    at the chat's most."""
    assert await chat_sender_of(None, _BROWSER, _HUB, stage="t") == LINKS_UNREAD
    assert await chat_sender_of(None, _HUB, _HUB, stage="t") == _OWNER_UNREAD


# --- §6:1: the local socket naming a device ------------------------------------------


async def test_the_local_socket_naming_a_device_is_bounded_by_hubs_link() -> None:
    """ADR-0378 §6:1: a message the local socket wrote under another device's name came
    through ``hub``, so both links are read: a label only lowers."""
    store = await _identities()
    assert await chat_sender_of(store, _LAPTOP, _HUB, stage="t") == _OWNER
    assert await chat_sender_of(store, _STRANGER, _HUB, stage="t") == NO_LINK
    await _lower(store, _HUB, Sureness.WEAK)
    assert await chat_sender_of(store, _LAPTOP, _HUB, stage="t") == InputSender(
        person=OWNER_PERSON_ID, level=Sureness.WEAK
    )
    assert await chat_sender_of(store, _HUB, _HUB, stage="t") == InputSender(
        person=OWNER_PERSON_ID, level=Sureness.WEAK
    )


async def test_the_local_socket_naming_a_device_is_no_one_when_unread() -> None:
    """ADR-0378 §4 prose, ADR-0374 §3:1: the exception is for a message written from
    ``hub`` alone, so one written from another device through ``hub`` is no one's."""
    store = cast("IdentityStore", _Unreadable(await _identities(), _HUB))
    assert await chat_sender_of(store, _LAPTOP, _HUB, stage="t") == LINKS_UNREAD


# --- the owner's own use today --------------------------------------------------------


async def test_the_owners_own_use_reads_exactly_as_before() -> None:
    """What must not change: the hub's machine, a browser device the hub's own machine
    names where both links stand at one level, and an enrolled machine writing as itself."""
    store = await _identities()
    cases = {
        "hub": (_HUB, _HUB),
        "browser named by the hub": (_BROWSER, _HUB),
        "enrolled machine as itself": (_LAPTOP, _LAPTOP),
    }
    for name, (device, through) in cases.items():
        before = await sender_of(store, chat_account(device), stage="t")
        assert await chat_sender_of(store, device, through, stage="t") == before == _OWNER, name


async def test_each_account_is_read_once_across_messages() -> None:
    """Messages sharing a device, or a gateway, read each account once."""
    asked: list[Account] = []
    store = await _identities()

    class _Counting:
        async def find_link(self, account: Account) -> Link | None:
            asked.append(account)
            return await store.find_link(account)

    found = await chat_senders_of(
        cast("IdentityStore", _Counting()),
        {1: (_BROWSER, _GATEWAY), 2: (_BROWSER, _GATEWAY), 3: (_GATEWAY, _GATEWAY)},
        stage="t",
    )
    assert found == {1: _OWNER, 2: _OWNER, 3: _OWNER}
    assert asked == [chat_account(_BROWSER), chat_account(_GATEWAY)]


# --- what a message costs to read back ---------------------------------------------------


_CONVERSATION: Final = "3f2b8c1e-5d4a-4f6b-9a7c-1e2d3c4b5a69"
_LONG_DEVICE: Final = "d" * 128
_LIMIT: Final = 4096


def _recorded(text: str, *, came_through: str | None) -> TranscriptMessage:
    """A user's message as the widest record holds it; built without ``came_through``
    where it is ``None``, as a record from before the field is."""
    held: dict[str, object] = {
        "conversation_id": _CONVERSATION,
        "position": 2**63 - 1,
        "written_at": datetime(9999, 12, 31, 23, 59, 59, 999999, tzinfo=UTC),
        "author": MessageAuthor.USER,
        "text": text,
        "device_id": _LONG_DEVICE,
        "message_id": "m",
        "home": RecordHome.owners(),
    }
    if came_through is not None:
        held["came_through"] = came_through
    return TranscriptMessage.model_validate(held)


def test_a_message_through_its_own_device_dumps_as_before_the_field() -> None:
    """ADR-0378 §8:2: only a message that came through another device carries the field
    in a dump; decoding puts it back, and an assistant's message carries none."""
    itself = _recorded("hi", came_through=None)
    named = _recorded("hi", came_through=_GATEWAY)
    assert itself.came_through == _LONG_DEVICE
    assert "came_through" not in itself.model_dump(mode="json")
    assert named.model_dump(mode="json")["came_through"] == _GATEWAY
    assert TranscriptMessage.model_validate(itself.model_dump(mode="json")) == itself
    assert TranscriptMessage.model_validate(named.model_dump(mode="json")) == named
    said = NewMessage(author=MessageAuthor.ASSISTANT, text="hello", home=RecordHome.owners())
    assert said.came_through is None
    assert "came_through" not in said.model_dump()


def test_a_message_admitted_at_the_bound_before_the_field_is_still_read_back() -> None:
    """ADR-0293 §4:7, ADR-0326 §4:4: the largest message the bound admitted before the
    field, from a long device id, reads back within the limit once the upgrade records
    it as having come through that device; one through a gateway is measured with it."""
    low, high = 1, 4096
    while high - low > 1:
        middle = (low + high) // 2
        try:
            check_message_fits(
                _CONVERSATION,
                UserMessage(device_id=_LONG_DEVICE, message_id="m", text="x" * middle),
                max_bytes=_LIMIT,
                home=RecordHome.owners(),
            )
            low = middle
        except OversizedValueError:
            high = middle
    largest = "x" * low
    upgraded = _recorded(largest, came_through=_LONG_DEVICE)
    page = TranscriptPage(conversation_id=_CONVERSATION, entries=(upgraded,), as_of=2**63 - 1)
    assert fit_transcript(page, max_bytes=_LIMIT) == page
    added = MessageAddedChange(seq=2**63 - 1, message=upgraded)
    changes = ChatChanges(changes=(added,), next_after=2**63 - 1)
    assert fit_changes(changes, max_bytes=_LIMIT) == changes
    with pytest.raises(OversizedValueError):
        check_message_fits(
            _CONVERSATION,
            UserMessage(device_id=_LONG_DEVICE, message_id="m", text=largest),
            max_bytes=_LIMIT,
            came_through="g" * 128,
            home=RecordHome.owners(),
        )
