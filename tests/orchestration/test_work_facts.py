"""Who sent an input, each work's three facts, and what the readers read of them.

Every input today's hub takes is admitted here as the engine admits it
(``admit_channel``), its sender found as its reader finds it (``sender_of``) over the
canonical identity store, holding the owner's accounts as the hub's start links them.
For each, the facts recorded (ADR-0368 §2, §3), and what every reader then reads of
them (§9:1, §9:5): whether the work is a person's (``persons_work``) and whose
authority it carries (``persons_authority``). An owner's message on the hub chat and on
the line is the owner's work carrying their authority, as before; a forward, an event a
connected source pushes, a task's occurrence and an approval's outcome are the owner's
work carrying none, as before; a message by an account no link ties, or by a link the
owner lowered to none, is no person's work and carries no one's authority. Nothing a
message says counts (ADR-0366 §4:2), and no channel type decides any of it. The values
no input of today's hub produces, a group, several senders and no one, are held
expressible, by the rule that would record them.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final, cast

import pytest
from structlog.testing import capture_logs

from ai_assistant.core.errors import IdentityStoreError
from ai_assistant.core.types import (
    OWNER_PERSON_ID,
    Account,
    AuthorityKind,
    ChannelIdentity,
    ChannelInput,
    ClaimedAuthor,
    InputSender,
    JoinedInput,
    NewConversation,
    RecordedInputMessage,
    SupportHolder,
    Sureness,
    TextChannelPayload,
    WholeTextReply,
    WorkAuthority,
    WorkFacts,
    WorkFor,
    WorkForKind,
)
from ai_assistant.orchestration.activation_state import admit_channel
from ai_assistant.orchestration.approvals import THE_APPROVALS
from ai_assistant.orchestration.task_scheduler import SCHEDULE
from ai_assistant.orchestration.work_facts import (
    HUB_MACHINE,
    LINKS_UNREAD,
    NO_LINK,
    authority_persons,
    chat_account,
    joined,
    line_account,
    persons_authority,
    persons_work,
    sender_of,
    senders_of,
    started,
)
from ai_assistant.testing import FakeIdentityStore

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.core.protocols import IdentityStore
    from ai_assistant.core.types import Link
    from ai_assistant.orchestration.activation_state import ActivationState

_AT: Final = datetime(2026, 11, 23, 9, 0, tzinfo=UTC)
_ID: Final = "60f3c223-6a54-4b06-aab8-4fc397c3d43b"

#: The owner's Telegram account, and the line's chat with it.
_TELEGRAM_ID: Final = 424242
_LINE: Final = ChannelIdentity(channel_type="telegram", instance_id=f"conn-1:{_TELEGRAM_ID}")
_CHAT: Final = ChannelIdentity(channel_type="conversation", instance_id="chat-1")
_EVENT: Final = ChannelIdentity(channel_type="informational_event", instance_id="calendar")

#: A device the owner admitted, and one nobody linked.
_PHONE: Final = "device-phone"
_STRANGER: Final = "device-stranger"

_OWNER: Final = InputSender(person=OWNER_PERSON_ID, level=Sureness.NORMAL)
_OWNERS_WORK: Final = WorkFor.for_person(OWNER_PERSON_ID)
_OWNERS_AUTHORITY: Final = WorkAuthority(kind=AuthorityKind.SENDERS, persons=(OWNER_PERSON_ID,))


def _identities() -> FakeIdentityStore:
    """The owner's accounts as the hub's start links them: the line's and a device."""
    return FakeIdentityStore(
        configured=[
            Account(kind="telegram", identifier=str(_TELEGRAM_ID)),
            Account(kind="conversation", identifier=_PHONE),
        ],
        now=lambda: _AT,
    )


def _admitted(  # noqa: PLR0913 — one knob per thing an admission takes
    target: ChannelIdentity | NewConversation,
    text: str = "what's on today?",
    *,
    reply: bool = True,
    messages: Sequence[RecordedInputMessage] = (),
    senders: Sequence[InputSender] = (),
    carries_outside_mark: bool = False,
) -> ActivationState:
    return admit_channel(
        ChannelInput(target=target, payload=TextChannelPayload(text=text)),
        WholeTextReply() if reply else None,
        clock=lambda: _AT,
        id_factory=lambda: _ID,
        messages=messages,
        senders=senders,
        carries_outside_mark=carries_outside_mark,
    )


async def _chat(device: str, text: str = "what's on today?") -> ActivationState:
    """A hub chat message written from ``device``, admitted as the chat's reader does."""
    sender = await sender_of(_identities(), chat_account(device), stage="chat_reader")
    return _admitted(NewConversation(), text, senders=(sender,))


async def _line(
    text: str = "what's on today?",
    *,
    forwarded_from: ClaimedAuthor | None = None,
    identities: FakeIdentityStore | None = None,
) -> ActivationState:
    """A line message, its sender found as the line's reader finds it."""
    store = _identities() if identities is None else identities
    sender = await sender_of(store, line_account(_TELEGRAM_ID), stage="telegram_reader")
    message = RecordedInputMessage(
        text=text, sent_at=_AT, position=7, forwarded_from=forwarded_from, sender=sender
    )
    return _admitted(_LINE, text, messages=(message,))


def _facts(state: ActivationState) -> WorkFacts:
    assert state.started_facts is not None
    return state.started_facts


def _reads(state: ActivationState) -> tuple[str | None, str | None]:
    """Whose work every reader reads it as, and whose authority (ADR-0368 §9:5, §9:1)."""
    return persons_work(state.work_facts), persons_authority(state.work_facts)


#: The owner's work, carrying the owner's authority: what an owner's own message was
#: and stays.
_THE_OWNERS: Final = (OWNER_PERSON_ID, OWNER_PERSON_ID)
#: The owner's work, carrying no one's authority: a forward's, an event's, a task's.
_FOR_THE_OWNER: Final = (OWNER_PERSON_ID, None)
#: No person's work, carrying no one's authority: an unidentified sender's.
_NO_ONES: Final = (None, None)


# --- who sent it ------------------------------------------------------------------------


async def test_a_linked_account_sends_as_its_person_at_its_links_level() -> None:
    """ADR-0366 §4:1, §5:3: the person a standing link names, at the kind's most."""
    store = _identities()
    assert await sender_of(store, chat_account(_PHONE), stage="t") == _OWNER
    assert await sender_of(store, line_account(_TELEGRAM_ID), stage="t") == _OWNER


async def test_an_account_no_link_ties_sends_as_no_one_at_none() -> None:
    """ADR-0366 §4:1, §5:6: no link, no identified person, at none."""
    store = _identities()
    assert await sender_of(store, chat_account(_STRANGER), stage="t") == NO_LINK
    assert await sender_of(store, line_account(1), stage="t") == NO_LINK
    assert await sender_of(store, None, stage="t") == NO_LINK
    assert await sender_of(None, None, stage="t") == NO_LINK
    assert chat_account(None) is None
    assert line_account(None) is None


async def test_a_lowering_lowers_the_sender_and_an_ended_link_ties_nothing() -> None:
    """ADR-0366 §5:5: a standing lowering sets the level; an ended link ties nothing."""
    store = _identities()
    link = await store.find_link(Account(kind="telegram", identifier=str(_TELEGRAM_ID)))
    assert link is not None
    lowered = await store.lower(link.id, Sureness.WEAK, by=OWNER_PERSON_ID)
    weak = await sender_of(store, line_account(_TELEGRAM_ID), stage="t")
    assert weak == InputSender(person=OWNER_PERSON_ID, level=Sureness.WEAK)
    assert lowered.record_id is not None
    await store.withdraw_lowering(lowered.record_id, by=OWNER_PERSON_ID)
    assert await sender_of(store, line_account(_TELEGRAM_ID), stage="t") == _OWNER
    await store.end_link(link.id)
    assert await sender_of(store, line_account(_TELEGRAM_ID), stage="t") == NO_LINK


async def test_a_store_that_cannot_be_read_reads_no_link_and_says_so() -> None:
    """ADR-0374 §2:1 to §2:3, §5:1, §5:4: a fault is logged under a fixed event name with
    the reader and the reason alone, and the message is an unidentified sender's, at none,
    marked: never read as a link."""

    class _Broken:
        async def find_link(self, account: Account) -> Link | None:
            raise IdentityStoreError("unreadable")

    broken = cast("IdentityStore", _Broken())
    with capture_logs() as logs:
        found = await sender_of(broken, chat_account(_PHONE), stage="chat_reader")
        on_the_line = await sender_of(broken, line_account(_TELEGRAM_ID), stage="telegram_reader")
    assert found == on_the_line == LINKS_UNREAD
    assert found == InputSender(person=None, level=Sureness.NONE, links_unread=True)
    assert logs == [
        {
            "event": "input_sender_unread",
            "reader": "chat_reader",
            "reason": "identity_store",
            "log_level": "warning",
        },
        {
            "event": "input_sender_unread",
            "reader": "telegram_reader",
            "reason": "identity_store",
            "log_level": "warning",
        },
    ]


async def test_each_account_is_read_once_for_every_message_it_sent() -> None:
    """The reader's messages share an account; the store is asked once for each."""
    asked: list[Account] = []

    held = FakeIdentityStore(configured=[Account(kind="conversation", identifier=_PHONE)])

    class _Counting:
        async def find_link(self, account: Account) -> Link | None:
            asked.append(account)
            return await held.find_link(account)

    found = await senders_of(
        cast("IdentityStore", _Counting()),
        {1: chat_account(_PHONE), 2: chat_account(_PHONE), 3: chat_account(_STRANGER)},
        stage="chat_reader",
    )
    assert found == {1: _OWNER, 2: _OWNER, 3: NO_LINK}
    assert len(asked) == 2


# --- the facts each input today's hub takes starts a work with, and what is read ------------


async def test_an_owners_message_on_the_hub_chat_is_theirs_with_their_authority() -> None:
    """ADR-0368 §3:1, §3:2: for the sender, carrying their authority, at the link's level."""
    state = await _chat(_PHONE)
    assert state.trigger.senders == (_OWNER,)
    assert _facts(state) == WorkFacts(
        for_whom=_OWNERS_WORK, authority=_OWNERS_AUTHORITY, level=Sureness.NORMAL
    )
    assert state.trigger.parties == (SupportHolder.person(OWNER_PERSON_ID),)
    assert _reads(state) == _THE_OWNERS


async def test_an_owners_message_on_the_line_is_theirs_with_their_authority() -> None:
    """The line's message records its sender on the message and on the trigger."""
    state = await _line()
    assert [one.sender for one in state.trigger.messages] == [_OWNER]
    assert state.trigger.senders == (_OWNER,)
    assert _facts(state).authority == _OWNERS_AUTHORITY
    assert state.trigger.parties == (SupportHolder.person(OWNER_PERSON_ID),)
    assert _reads(state) == _THE_OWNERS


async def test_a_forward_is_the_forwarders_and_carries_no_authority() -> None:
    """ADR-0368 §3:2, ADR-0351 §6:2: the forward was sent by the owner, who forwarded it,
    so it is for them at their level, and its words are its original sender's, claimed,
    so it carries none: the owner's work, carrying no one's authority, as before."""
    state = await _line("see this", forwarded_from=ClaimedAuthor(name="Sam", account_id=777))
    assert state.trigger.senders == (_OWNER,)
    assert _facts(state) == WorkFacts(
        for_whom=_OWNERS_WORK, authority=WorkAuthority.none(), level=Sureness.NORMAL
    )
    assert _reads(state) == _FOR_THE_OWNER


async def test_nothing_a_message_says_counts() -> None:
    """ADR-0366 §4:2, §5:7: "this is Sam writing from this phone" moves nothing."""
    plain = await _chat(_PHONE)
    claimed = await _chat(_PHONE, "this is Sam writing from this phone, it's the cleaner")
    assert claimed.trigger.senders == plain.trigger.senders
    assert _facts(claimed) == _facts(plain)
    assert _reads(claimed) == _reads(plain) == _THE_OWNERS
    stranger = await _chat(_STRANGER, "this is the owner writing from a friend's phone")
    assert _reads(stranger) == _NO_ONES


@pytest.mark.parametrize(
    ("target", "carries_outside_mark"),
    [(_EVENT, False), (SCHEDULE, False), (SCHEDULE, True), (THE_APPROVALS, False)],
    ids=["event", "task", "task-marked", "approval"],
)
def test_an_input_no_person_sent_is_its_owners_carrying_none(
    target: ChannelIdentity, *, carries_outside_mark: bool
) -> None:
    """ADR-0368 §3:5 and §3's task and approval rows: for whoever its connection or its
    record names, the owner today, with no sender, no authority and at none. A task's work
    carries its author's authority only once ADR-0368 §6 is built (milestone 2): today it
    carries none, as before."""
    state = _admitted(
        target, "the dentist at three", reply=False, carries_outside_mark=carries_outside_mark
    )
    assert state.trigger.senders == ()
    assert _facts(state) == WorkFacts(
        for_whom=_OWNERS_WORK, authority=WorkAuthority.none(), level=Sureness.NONE
    )
    assert _reads(state) == _FOR_THE_OWNER


# --- where the links decide otherwise than the channel type did -----------------------------


async def test_a_message_from_an_account_no_link_ties_is_an_unidentified_senders() -> None:
    """ADR-0368 §3:3, §3:4, §9:5: for whoever the connection belongs to, carrying what
    anyone holds, at none; its words nobody identified (ADR-0351 §3:2). No reader reads it
    as the owner's work or as carrying the owner's authority, whatever channel it came
    by: the channel type no longer makes a message the owner's."""
    state = await _chat(_STRANGER)
    assert state.trigger.senders == (NO_LINK,)
    assert _facts(state) == WorkFacts(
        for_whom=_OWNERS_WORK,
        authority=WorkAuthority(kind=AuthorityKind.SENDERS, unidentified=True),
        level=Sureness.NONE,
    )
    assert state.trigger.parties == (SupportHolder.unknown(),)
    assert _reads(state) == _NO_ONES


async def test_a_link_lowered_to_none_makes_its_messages_an_unidentified_senders() -> None:
    """#3642: "a link lowered to none makes its messages count as an unidentified
    sender's". The sender still names whom the link names, and the work is no person's,
    carrying no one's authority, its words nobody identified."""
    store = _identities()
    link = await store.find_link(Account(kind="telegram", identifier=str(_TELEGRAM_ID)))
    assert link is not None
    await store.lower(link.id, Sureness.NONE, by=OWNER_PERSON_ID)
    state = await _line(identities=store)
    assert state.trigger.senders == (InputSender(person=OWNER_PERSON_ID, level=Sureness.NONE),)
    assert _facts(state).authority == WorkAuthority(kind=AuthorityKind.SENDERS, unidentified=True)
    assert [one.party for one in state.trigger.messages] == [SupportHolder.unknown()]
    assert _reads(state) == _NO_ONES


async def test_a_link_lowered_to_weak_keeps_the_work_and_lowers_its_level() -> None:
    """ADR-0366 §5:5: the owner's work and authority, at weak. No level gates anything in
    this milestone beyond identified or not (ADR-0367's, milestone 2)."""
    store = _identities()
    link = await store.find_link(Account(kind="telegram", identifier=str(_TELEGRAM_ID)))
    assert link is not None
    await store.lower(link.id, Sureness.WEAK, by=OWNER_PERSON_ID)
    state = await _line(identities=store)
    assert _facts(state) == WorkFacts(
        for_whom=_OWNERS_WORK, authority=_OWNERS_AUTHORITY, level=Sureness.WEAK
    )
    assert _reads(state) == _THE_OWNERS


# --- what no input of today's hub produces, held expressible --------------------------------


def test_several_senders_are_for_the_connections_owner_and_hold_every_one() -> None:
    """ADR-0368 §4:1, §4:6: several senders, one unidentified: for whoever the place
    belongs to, carrying each sender's, at the lowest level."""
    sam = InputSender(person="person:sam", level=Sureness.WEAK)
    state = _admitted(_CHAT, senders=(_OWNER, sam, NO_LINK))
    assert _facts(state) == WorkFacts(
        for_whom=_OWNERS_WORK,
        authority=WorkAuthority(
            kind=AuthorityKind.SENDERS,
            persons=(OWNER_PERSON_ID, "person:sam"),
            unidentified=True,
        ),
        level=Sureness.NONE,
    )
    assert _reads(state) == _NO_ONES
    assert authority_persons(state.work_facts) == ()


def test_a_kind_with_no_row_is_for_no_one() -> None:
    """ADR-0368 §3's last row: for no one, carrying none, at none."""
    state = _admitted(
        ChannelIdentity(channel_type="informational_event", instance_id="x"), reply=False
    )
    other = state.trigger.model_copy(
        update={"channel": ChannelIdentity(channel_type="upkeep", instance_id="tidy")}
    )
    assert started(other) == WorkFacts(
        for_whom=WorkFor.no_one(), authority=WorkAuthority.none(), level=Sureness.NONE
    )


# --- an input joining a work ----------------------------------------------------------------


def _joining(sender: InputSender | None, *, forwarded: bool = False) -> JoinedInput:
    author = ClaimedAuthor(name="Sam", account_id=777) if forwarded else None
    state = _admitted(
        _LINE,
        messages=(
            RecordedInputMessage(
                text="and Saturday", sent_at=_AT, forwarded_from=author, sender=sender
            ),
        ),
    )
    return JoinedInput(joined_at=_AT, channel=_LINE, messages=state.trigger.messages)


async def test_a_join_never_adds_authority_and_never_raises_the_level() -> None:
    """ADR-0368 §2:5, §4:1: the lowest level; the same authority kept, a different one
    dropped; an input no person sent lowers nothing."""
    owners = _facts(await _chat(_PHONE))
    weak = InputSender(person=OWNER_PERSON_ID, level=Sureness.WEAK)
    assert joined(owners, _joining(_OWNER)) == owners
    assert joined(owners, _joining(weak)) == owners.model_copy(update={"level": Sureness.WEAK})
    assert joined(owners, _joining(_OWNER, forwarded=True)).authority == WorkAuthority.none()
    assert joined(owners, _joining(NO_LINK)) == WorkFacts(
        for_whom=_OWNERS_WORK, authority=WorkAuthority.none(), level=Sureness.NONE
    )
    approval = JoinedInput(
        joined_at=_AT,
        channel=THE_APPROVALS,
        messages=(RecordedInputMessage(text="approved", sent_at=_AT),),
    )
    assert joined(owners, approval) == owners
    nothing = _facts(_admitted(SCHEDULE, reply=False))
    assert joined(nothing, _joining(_OWNER)).authority == WorkAuthority.none()


async def test_a_join_records_the_facts_again_on_the_input_and_the_episode() -> None:
    """ADR-0368 §2:4: each input that joins carries the facts as they stand once it did,
    and the record keeps those the work started with."""
    state = await _chat(_PHONE)
    weak = InputSender(person=OWNER_PERSON_ID, level=Sureness.WEAK)
    inputs = (_joining(weak), _joining(None))
    with capture_logs() as logs:
        state.take_inputs(inputs, merged=("act-other",))
    lowered = _facts(state).model_copy(update={"level": Sureness.WEAK})
    assert [one.facts for one in state.joined] == [lowered, lowered]
    assert state.work_facts == lowered
    record = state.open_processing()
    assert record.facts == _facts(state)
    assert record.facts_now == lowered
    assert [one["at"] for one in logs if one["event"] == "work_facts_recorded"] == [
        "join",
        "join",
    ]


# --- what the readers read (ADR-0368 §9) -----------------------------------------------------

_SAM: Final = "person:sam"


def _work(whom: WorkFor, authority: WorkAuthority, level: Sureness = Sureness.NORMAL) -> WorkFacts:
    return WorkFacts(for_whom=whom, authority=authority, level=level)


@pytest.mark.parametrize(
    ("facts", "work", "authority"),
    [
        pytest.param(
            _work(_OWNERS_WORK, _OWNERS_AUTHORITY), OWNER_PERSON_ID, OWNER_PERSON_ID, id="owners"
        ),
        pytest.param(
            _work(_OWNERS_WORK, WorkAuthority.none()), OWNER_PERSON_ID, None, id="carries-none"
        ),
        pytest.param(
            _work(
                _OWNERS_WORK,
                WorkAuthority(kind=AuthorityKind.IN_ADVANCE, persons=(OWNER_PERSON_ID,)),
            ),
            OWNER_PERSON_ID,
            OWNER_PERSON_ID,
            id="in-advance",
        ),
        pytest.param(
            _work(
                _OWNERS_WORK,
                WorkAuthority(kind=AuthorityKind.SENDERS, unidentified=True),
                Sureness.NONE,
            ),
            None,
            None,
            id="unidentified",
        ),
        pytest.param(
            _work(
                _OWNERS_WORK,
                WorkAuthority(
                    kind=AuthorityKind.SENDERS, persons=(OWNER_PERSON_ID,), unidentified=True
                ),
                Sureness.NONE,
            ),
            None,
            None,
            id="one-unidentified-beside",
        ),
        pytest.param(
            _work(
                _OWNERS_WORK,
                WorkAuthority(kind=AuthorityKind.SENDERS, persons=(OWNER_PERSON_ID, _SAM)),
            ),
            None,
            None,
            id="several",
        ),
        pytest.param(
            _work(
                WorkFor.for_person(_SAM), WorkAuthority(kind=AuthorityKind.SENDERS, persons=(_SAM,))
            ),
            None,
            None,
            id="a-person-the-hub-does-not-admit",
        ),
        pytest.param(
            _work(WorkFor(kind=WorkForKind.GROUP, id="group:home"), WorkAuthority.none()),
            None,
            None,
            id="a-group",
        ),
        pytest.param(
            _work(WorkFor.no_one(), WorkAuthority.none(), Sureness.NONE), None, None, id="no-one"
        ),
        pytest.param(None, None, None, id="no-facts"),
    ],
)
def test_the_readers_read_a_persons_work_and_authority_from_the_facts(
    facts: WorkFacts | None, work: str | None, authority: str | None
) -> None:
    """ADR-0368 §9:5: a person's work is for a person, with no unidentified sender and no
    more than one person's authority; §9:1: the one identified person whose authority it
    carries. Both answer for a person the hub admits alone (ADR-0365 §1:3, ADR-0368 §1:4),
    and a work with no facts is no person's, carrying none: recording fails closed."""
    assert persons_work(facts) == work
    assert persons_authority(facts) == authority


def test_a_relay_mark_takes_the_authority_away_and_leaves_the_work() -> None:
    """ADR-0351 §6:5, ADR-0368 §2:4: no fact records the mark; the reader takes it."""
    owners = _work(_OWNERS_WORK, _OWNERS_AUTHORITY)
    assert persons_authority(owners, relayed=True) is None
    assert persons_work(owners) == OWNER_PERSON_ID


def test_two_inputs_carry_the_same_authority_whatever_their_levels() -> None:
    """ADR-0368 §9:2: the same people's, whatever their levels."""
    normal = _work(_OWNERS_WORK, _OWNERS_AUTHORITY)
    weak = _work(_OWNERS_WORK, _OWNERS_AUTHORITY, Sureness.WEAK)
    assert authority_persons(normal) == authority_persons(weak) == (OWNER_PERSON_ID,)
    unidentified = _work(
        _OWNERS_WORK, WorkAuthority(kind=AuthorityKind.SENDERS, unidentified=True), Sureness.NONE
    )
    assert authority_persons(unidentified) == ()


# --- the line a running hub shows -----------------------------------------------------------


async def test_each_recording_is_logged_with_what_was_decided() -> None:
    """One entry each time the facts are recorded, saying whom the work is for, whose
    authority it carries, its level, whether the links could not be read, and what the
    readers read of it, with codes, levels and truth values alone, never a person's id
    and never the input's words."""
    with capture_logs() as logs:
        await _chat(_PHONE, "a secret only the owner knows")
        await _chat(_STRANGER)
    entries = [one for one in logs if one["event"] == "work_facts_recorded"]
    assert entries == [
        {
            "event": "work_facts_recorded",
            "log_level": "info",
            "activation_id": _ID,
            "at": "start",
            "for_whom": "person",
            "whose": "senders",
            "unidentified": False,
            "facts_level": "normal",
            "links_unread": False,
            "persons_work": True,
            "carries_a_persons": True,
        },
        {
            "event": "work_facts_recorded",
            "log_level": "info",
            "activation_id": _ID,
            "at": "start",
            "for_whom": "person",
            "whose": "senders",
            "unidentified": True,
            "facts_level": "none",
            "links_unread": False,
            "persons_work": False,
            "carries_a_persons": False,
        },
    ]
    assert not any(OWNER_PERSON_ID in str(one) for one in entries)
    assert not any("secret" in str(one) for one in entries)


# --- recording fails closed -----------------------------------------------------------------


async def test_a_defect_in_the_lookup_or_the_recording_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A defect in finding a sender is a fault of the read, never a link (ADR-0374 §2:1);
    a defect in deciding the facts is logged and stops no input, and the work then reads
    as no person's carrying no one's authority: a work records none, and a join records
    the work's facts with no authority, at none, so no reader reads more than was
    decided."""
    import ai_assistant.orchestration.work_facts as module  # noqa: PLC0415 — patched here

    class _Defective:
        async def find_link(self, account: Account) -> Link | None:
            raise RuntimeError("a defect")

    with capture_logs() as logs:
        found = await sender_of(
            cast("IdentityStore", _Defective()), chat_account(_PHONE), stage="chat_reader"
        )
    assert found == LINKS_UNREAD
    assert [one["reason"] for one in logs] == ["defect"]

    def _raises(*_: object, **__: object) -> WorkFacts:
        raise RuntimeError("a defect")

    state = await _chat(_PHONE)
    joining = _joining(_OWNER)
    monkeypatch.setattr(module, "started", _raises)
    monkeypatch.setattr(module, "joined", _raises)
    with capture_logs() as logs:
        broken = await _chat(_PHONE)
        state.take_inputs((joining,), merged=("act-other",))
    assert broken.started_facts is None
    assert broken.trigger.senders == (_OWNER,)
    assert _reads(broken) == _NO_ONES
    closed = WorkFacts(for_whom=_OWNERS_WORK, authority=WorkAuthority.none(), level=Sureness.NONE)
    assert [one.facts for one in state.joined] == [closed]
    assert state.work_facts == closed
    assert _reads(state) == _FOR_THE_OWNER
    assert [(one["event"], one["at"]) for one in logs] == [
        ("work_facts_unrecorded", "start"),
        ("work_facts_unrecorded", "join"),
    ]


async def test_another_works_facts_never_join_as_this_ones(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADR-0368 §2:5: an absorption brings the other work's joined inputs, each carrying
    the facts that work recorded. They are never kept as this work's: replaced by its own,
    or taken off where it records none, or closed where its recording fails, so no join
    raises its level. A fault in logging the facts keeps them."""
    import ai_assistant.orchestration.work_facts as module  # noqa: PLC0415 — patched here

    weak = InputSender(person=OWNER_PERSON_ID, level=Sureness.WEAK)
    donors = _facts(await _chat(_PHONE))
    brought = _joining(_OWNER).model_copy(update={"facts": donors})

    def recipient() -> ActivationState:
        state = _admitted(
            _LINE,
            messages=(RecordedInputMessage(text="hi", sent_at=_AT, position=1, sender=weak),),
        )
        assert _facts(state).level is Sureness.WEAK
        return state

    held = recipient()
    held.take_inputs((brought,), merged=("act-other",))
    assert held.work_facts is not None
    assert held.work_facts.level is Sureness.WEAK

    unfacted = recipient()
    unfacted.started_facts = None
    unfacted.take_inputs((brought,), merged=("act-other",))
    assert [one.facts for one in unfacted.joined] == [None]
    assert unfacted.work_facts is None

    def _raises(*_: object, **__: object) -> None:
        raise RuntimeError("a defect")

    monkeypatch.setattr(module, "log_facts", _raises)
    unlogged = recipient()
    with capture_logs() as logs:
        unlogged.take_inputs((brought,), merged=("act-other",))
    assert unlogged.work_facts == held.work_facts
    assert [(one["event"], one["at"]) for one in logs] == [("work_facts_unlogged", "join")]

    monkeypatch.setattr(module, "joined", _raises)
    failed = recipient()
    failed.take_inputs((brought,), merged=("act-other",))
    assert failed.work_facts == WorkFacts(
        for_whom=_OWNERS_WORK, authority=WorkAuthority.none(), level=Sureness.NONE
    )


# --- when the links cannot be read (ADR-0374) ---------------------------------------------------


class _Unreadable:
    """An identity store whose every read fails, as a store fault does (ADR-0374 §2:1)."""

    def __init__(self, error: Exception) -> None:
        self.error = error

    async def find_link(self, account: Account) -> Link | None:
        raise self.error


#: The owner on the hub's own machine while the links cannot be read (ADR-0374 §3:2).
_OWNER_UNREAD: Final = InputSender(person=OWNER_PERSON_ID, level=Sureness.NORMAL, links_unread=True)


@pytest.mark.parametrize(
    "identities",
    [
        None,
        cast("IdentityStore", _Unreadable(IdentityStoreError("unreadable"))),
        cast("IdentityStore", _Unreadable(RuntimeError("a defect"))),
    ],
    ids=["unwired", "identity_store", "defect"],
)
async def test_the_hubs_own_machine_is_the_owner_at_the_chats_most_marked(
    identities: IdentityStore | None,
) -> None:
    """ADR-0374 §3:1, §3:2, §5:1: while the links cannot be read, the hub chat's device
    ``hub`` is the owner's at the hub chat's declared most, marked; every other device and
    the line are an unidentified sender's at none, marked. Each read is logged once, with
    the reader and the reason, and no account's or person's identifier."""
    with capture_logs() as logs:
        hub = await sender_of(identities, chat_account("hub"), stage="chat_reader")
        phone = await sender_of(identities, chat_account(_PHONE), stage="chat_reader")
        line = await sender_of(identities, line_account(_TELEGRAM_ID), stage="telegram_reader")
    assert chat_account("hub") == HUB_MACHINE
    assert hub == _OWNER_UNREAD
    assert hub.identified
    assert phone == line == LINKS_UNREAD
    assert not phone.identified
    assert {one["event"] for one in logs} == {"input_sender_unread"}
    assert len(logs) == 3
    assert {tuple(sorted(one)) for one in logs} == {("event", "log_level", "reader", "reason")}
    assert not any(word in str(one) for one in logs for word in ("hub'", _PHONE, str(_TELEGRAM_ID)))


async def test_no_other_kind_or_device_is_the_hubs_own_machine() -> None:
    """ADR-0374 §3:1: only the hub chat's device ``hub``; a Telegram account whose id
    reads ``hub``, or a device named like it, is not that machine."""
    broken = cast("IdentityStore", _Unreadable(IdentityStoreError("unreadable")))
    for account in (
        Account(kind="telegram", identifier="hub"),
        chat_account("hub-laptop"),
        chat_account("HUB"),
    ):
        assert await sender_of(broken, account, stage="t") == LINKS_UNREAD, account


async def test_a_message_naming_no_account_is_no_fault() -> None:
    """ADR-0374 §2:1: a message that names no account arrived by no link, whether or not
    a store is wired, and is not marked; nothing is logged."""
    broken = cast("IdentityStore", _Unreadable(IdentityStoreError("unreadable")))
    with capture_logs() as logs:
        assert await sender_of(None, None, stage="t") == NO_LINK
        assert await sender_of(broken, None, stage="t") == NO_LINK
    assert not NO_LINK.links_unread
    assert logs == []


async def test_a_lowering_on_the_hubs_link_stands_only_while_the_links_can_be_read() -> None:
    """ADR-0374 §3:3, §4:1, §4:2: the hub's own machine's link, lowered, lowers its
    messages while the store reads; during a fault no lowering is read, and the hub
    chat's most stands; once the store reads again, the lowering applies again."""
    store = FakeIdentityStore(configured=[HUB_MACHINE], now=lambda: _AT)
    link = await store.find_link(HUB_MACHINE)
    assert link is not None
    await store.lower(link.id, Sureness.NONE, by=OWNER_PERSON_ID)
    lowered = InputSender(person=OWNER_PERSON_ID, level=Sureness.NONE)

    assert await sender_of(store, HUB_MACHINE, stage="t") == lowered
    store.fail_next()
    assert await sender_of(store, HUB_MACHINE, stage="t") == _OWNER_UNREAD
    assert await sender_of(store, HUB_MACHINE, stage="t") == lowered


async def test_where_the_links_can_be_read_nothing_is_marked() -> None:
    """ADR-0374 §3:3: a read that answers is a link's or no link's, never marked."""
    store = FakeIdentityStore(configured=[HUB_MACHINE], now=lambda: _AT)
    for account in (HUB_MACHINE, chat_account(_STRANGER), line_account(1)):
        found = await sender_of(store, account, stage="t")
        assert not found.links_unread, account
    assert await sender_of(store, HUB_MACHINE, stage="t") == _OWNER


async def test_the_mark_combines_on_a_trigger_as_on_its_messages() -> None:
    """ADR-0374 §5:2: an input's sender records the fault where any of its messages'
    does, so the trigger's senders stay exactly its messages' (ADR-0368 §2:6)."""
    messages = (
        RecordedInputMessage(text="one", sent_at=_AT, position=1, sender=_OWNER),
        RecordedInputMessage(text="two", sent_at=_AT, position=2, sender=_OWNER_UNREAD),
        RecordedInputMessage(text="three", sent_at=_AT, position=3, sender=NO_LINK),
        RecordedInputMessage(text="four", sent_at=_AT, position=4, sender=LINKS_UNREAD),
    )
    state = _admitted(_LINE, "one two three four", messages=messages)
    assert state.trigger.senders == (_OWNER_UNREAD, LINKS_UNREAD)
    chat = _admitted(NewConversation(), senders=(_OWNER, NO_LINK, _OWNER_UNREAD))
    assert chat.trigger.senders == (_OWNER_UNREAD, NO_LINK)
    joining = JoinedInput(joined_at=_AT, channel=_LINE, messages=messages)
    assert joining.senders == state.trigger.senders


async def test_a_fault_off_the_hubs_machine_is_no_ones_and_on_it_the_owners() -> None:
    """ADR-0374 §2:2, §3:2, §5:1: off the hub's own machine a message whose links could
    not be read is no person's work carrying no one's authority; on it, the owner's work
    carrying their authority; the log says the links could not be read for either. A
    fault is never read as a link: the line during a fault is no one's too."""
    with capture_logs() as logs:
        off = _admitted(NewConversation(), senders=(LINKS_UNREAD,))
        on = _admitted(NewConversation(), senders=(_OWNER_UNREAD,))
        line = _admitted(
            _LINE,
            messages=(RecordedInputMessage(text="hi", sent_at=_AT, sender=LINKS_UNREAD),),
        )
        read = _admitted(NewConversation(), senders=(_OWNER,))
    assert _facts(off) == WorkFacts(
        for_whom=_OWNERS_WORK,
        authority=WorkAuthority(kind=AuthorityKind.SENDERS, unidentified=True),
        level=Sureness.NONE,
    )
    assert _facts(on) == WorkFacts(
        for_whom=_OWNERS_WORK, authority=_OWNERS_AUTHORITY, level=Sureness.NORMAL
    )
    entries = [one for one in logs if one["event"] == "work_facts_recorded"]
    assert [(one["persons_work"], one["links_unread"]) for one in entries] == [
        (False, True),
        (True, True),
        (False, True),
        (True, False),
    ]
    assert _reads(off) == _reads(line) == _NO_ONES
    assert _reads(on) == _reads(read) == _THE_OWNERS


async def test_a_join_logs_a_fault_on_any_input_the_facts_were_recorded_from() -> None:
    """ADR-0374 §5:1: a join's facts are the lowest of every input's so far, so its
    entry says the links could not be read where they could not for the trigger, an
    input that joined before, or the one joining."""
    clean = _admitted(NewConversation(), senders=(_OWNER,))
    faulted = _admitted(NewConversation(), senders=(_OWNER_UNREAD,))
    owners, unread = _joining(_OWNER), _joining(LINKS_UNREAD)
    with capture_logs() as logs:
        clean.take_inputs((owners,), merged=("act-a",))
        clean.take_inputs((unread, owners), merged=("act-b",))
        clean.take_inputs((owners,), merged=("act-c",))
        faulted.take_inputs((owners,), merged=("act-d",))
    joins = [one["links_unread"] for one in logs if one["event"] == "work_facts_recorded"]
    assert [one["at"] for one in logs if one["event"] == "work_facts_recorded"] == ["join"] * 5
    assert joins == [False, True, True, True, True]


async def test_the_facts_line_keeps_its_level_through_the_configured_chain() -> None:
    """The line a running hub writes, through the chain ``core.logging`` configures rather
    than ``capture_logs``, which skips it: the chain's ``add_log_level`` owns ``level``,
    so the facts' level is ``facts_level`` and reaches the output, and no key of either
    line is masked by the redaction."""
    import structlog  # noqa: PLC0415 — the configured chain, read here

    from ai_assistant.core.config import Settings  # noqa: PLC0415 — configured here
    from ai_assistant.core.logging import REDACTED, configure_logging  # noqa: PLC0415

    configure_logging(Settings())
    chain = structlog.get_config()["processors"]
    captured = structlog.testing.LogCapture()
    # The configured chain, every enricher and the redaction, with the renderer's place
    # taken by a capture, so each entry is read as the renderer would be handed it.
    structlog.configure(processors=[*chain[:-1], captured])
    _admitted(NewConversation(), senders=(LINKS_UNREAD,))
    await sender_of(None, chat_account(_PHONE), stage="chat_reader")

    facts, unread = (
        next(one for one in captured.entries if one["event"] == name)
        for name in ("work_facts_recorded", "input_sender_unread")
    )
    assert facts["level"] == "info"
    assert facts["facts_level"] == "none"
    assert facts["links_unread"] is True
    assert facts["persons_work"] is False
    assert facts["carries_a_persons"] is False
    assert facts["whose"] == "senders"
    assert facts["unidentified"] is True
    assert REDACTED not in facts.values()
    assert unread["level"] == "warning"
    assert unread["reader"] == "chat_reader"
    assert unread["reason"] == "unwired"
    assert REDACTED not in unread.values()
