"""Who sent an input, and each work's three facts, held equal to today's path (ADR-0368 §2).

Every input today's hub takes is admitted here as the engine admits it
(``admit_channel``), its sender found as its reader finds it (``sender_of``) over the
canonical identity store, holding the owner's accounts as the hub's start links them.
For each, the facts recorded say what today's path says (``todays_path``): an owner's
message on the hub chat and on the line, a forward, an event a connected source pushes,
a task's occurrence and an approval's outcome. Where the two differ by design, a message
by an account no link ties or by a link the owner lowered to none, the case says so and
holds the difference as a disagreement the log names. Nothing a message says counts
(ADR-0366 §4:2). The values no input of today's hub produces, a group, several senders
and no one, are held expressible, by the rule that would record them.
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
    Sureness,
    TextChannelPayload,
    WholeTextReply,
    WorkAuthority,
    WorkFacts,
    WorkFor,
)
from ai_assistant.orchestration.activation_state import admit_channel
from ai_assistant.orchestration.approvals import THE_APPROVALS
from ai_assistant.orchestration.task_scheduler import SCHEDULE
from ai_assistant.orchestration.work_facts import (
    NO_LINK,
    chat_account,
    disagreements,
    joined,
    line_account,
    sender_of,
    senders_of,
    started,
    todays_path,
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


def _agrees(state: ActivationState) -> tuple[str, ...]:
    return disagreements(_facts(state), todays_path(state.trigger))


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
    assert await sender_of(None, chat_account(_PHONE), stage="t") == NO_LINK
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


async def test_a_store_that_cannot_be_read_finds_no_link_and_says_so() -> None:
    """A fault is logged under a fixed event name, and the input arrives by no link."""

    class _Broken:
        async def find_link(self, account: Account) -> Link | None:
            raise IdentityStoreError("unreadable")

    broken = cast("IdentityStore", _Broken())
    with capture_logs() as logs:
        found = await sender_of(broken, chat_account(_PHONE), stage="chat_reader")
    assert found == NO_LINK
    assert logs == [
        {
            "event": "input_sender_unread",
            "stage": "chat_reader",
            "reason": "identity_store",
            "log_level": "warning",
        }
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


# --- the facts each input today's hub takes starts a work with, held equal ------------------


async def test_an_owners_message_on_the_hub_chat_is_theirs_with_their_authority() -> None:
    """ADR-0368 §3:1, §3:2: for the sender, carrying their authority, at the link's level."""
    state = await _chat(_PHONE)
    assert state.trigger.senders == (_OWNER,)
    assert _facts(state) == WorkFacts(
        for_whom=_OWNERS_WORK, authority=_OWNERS_AUTHORITY, level=Sureness.NORMAL
    )
    assert _agrees(state) == ()


async def test_an_owners_message_on_the_line_is_theirs_with_their_authority() -> None:
    """The line's message records its sender on the message and on the trigger."""
    state = await _line()
    assert [one.sender for one in state.trigger.messages] == [_OWNER]
    assert state.trigger.senders == (_OWNER,)
    assert _facts(state).authority == _OWNERS_AUTHORITY
    assert _agrees(state) == ()


async def test_a_forward_is_the_forwarders_and_carries_no_authority() -> None:
    """ADR-0368 §3:2, ADR-0351 §6:2: the forward was sent by the owner, who forwarded it,
    so it is for them at their level, and its words are its original sender's, claimed,
    so it carries none, as today's path says."""
    state = await _line("see this", forwarded_from=ClaimedAuthor(name="Sam", account_id=777))
    assert state.trigger.senders == (_OWNER,)
    assert _facts(state) == WorkFacts(
        for_whom=_OWNERS_WORK, authority=WorkAuthority.none(), level=Sureness.NORMAL
    )
    assert _agrees(state) == ()


async def test_nothing_a_message_says_counts() -> None:
    """ADR-0366 §4:2, §5:7: "this is Sam writing from this phone" moves nothing."""
    plain = await _chat(_PHONE)
    claimed = await _chat(_PHONE, "this is Sam writing from this phone, it's the cleaner")
    assert claimed.trigger.senders == plain.trigger.senders
    assert _facts(claimed) == _facts(plain)


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
    carries none, as today's path says."""
    state = _admitted(
        target, "the dentist at three", reply=False, carries_outside_mark=carries_outside_mark
    )
    assert state.trigger.senders == ()
    assert _facts(state) == WorkFacts(
        for_whom=_OWNERS_WORK, authority=WorkAuthority.none(), level=Sureness.NONE
    )
    assert _agrees(state) == ()


# --- where they differ by design ----------------------------------------------------------


async def test_a_message_from_an_account_no_link_ties_is_an_unidentified_senders() -> None:
    """ADR-0368 §3:3, §3:4: for whoever the connection belongs to, carrying what anyone
    holds, at none. Today's path takes every hub chat message as the owner's: the two
    disagree on the authority and the level, which is what the log shows a hub where a
    device is not linked."""
    state = await _chat(_STRANGER)
    assert state.trigger.senders == (NO_LINK,)
    assert _facts(state) == WorkFacts(
        for_whom=_OWNERS_WORK,
        authority=WorkAuthority(kind=AuthorityKind.SENDERS, unidentified=True),
        level=Sureness.NONE,
    )
    assert _agrees(state) == ("authority", "level")


async def test_a_link_lowered_to_none_makes_its_messages_an_unidentified_senders() -> None:
    """#3642: "a link lowered to none makes its messages count as an unidentified
    sender's". The sender still names whom the link names; today's path does not read
    the lowering, so the two disagree."""
    store = _identities()
    link = await store.find_link(Account(kind="telegram", identifier=str(_TELEGRAM_ID)))
    assert link is not None
    await store.lower(link.id, Sureness.NONE, by=OWNER_PERSON_ID)
    state = await _line(identities=store)
    assert state.trigger.senders == (InputSender(person=OWNER_PERSON_ID, level=Sureness.NONE),)
    assert _facts(state).authority == WorkAuthority(kind=AuthorityKind.SENDERS, unidentified=True)
    assert _agrees(state) == ("authority", "level")


async def test_a_link_lowered_to_weak_keeps_the_work_and_lowers_its_level() -> None:
    """ADR-0366 §5:5: the owner's work and authority, at weak, which today's path agrees
    with: it establishes the owner, and weak is established."""
    store = _identities()
    link = await store.find_link(Account(kind="telegram", identifier=str(_TELEGRAM_ID)))
    assert link is not None
    await store.lower(link.id, Sureness.WEAK, by=OWNER_PERSON_ID)
    state = await _line(identities=store)
    assert _facts(state) == WorkFacts(
        for_whom=_OWNERS_WORK, authority=_OWNERS_AUTHORITY, level=Sureness.WEAK
    )
    assert _agrees(state) == ()


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


# --- the line a running hub shows -----------------------------------------------------------


async def test_each_recording_is_logged_with_where_it_disagrees() -> None:
    """One entry each time the facts are recorded, naming the facts that disagree with
    today's path, with codes and levels alone, never a person's id."""
    with capture_logs() as logs:
        await _chat(_PHONE)
        await _chat(_STRANGER)
    entries = [one for one in logs if one["event"] == "work_facts_recorded"]
    assert [(one["at"], one["agrees"], one["differs"]) for one in entries] == [
        ("start", True, ()),
        ("start", False, ("authority", "level")),
    ]
    assert entries[0] == {
        "event": "work_facts_recorded",
        "log_level": "info",
        "activation_id": _ID,
        "at": "start",
        "agrees": True,
        "differs": (),
        "for_whom": "person",
        "whose": "senders",
        "unidentified": False,
        "level": "normal",
        "today_person": True,
        "today_users": True,
        "today_established": True,
    }
    assert not any(OWNER_PERSON_ID in str(one) for one in entries)


# --- recording never stops a work -----------------------------------------------------------


async def test_a_defect_in_the_lookup_or_the_recording_stops_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Nothing reads a sender or a fact yet (ADR-0368 §1:3): a defect in finding one or
    in recording them is logged, and the input is admitted and joins as before."""
    import ai_assistant.orchestration.work_facts as module  # noqa: PLC0415 — patched here

    class _Defective:
        async def find_link(self, account: Account) -> Link | None:
            raise RuntimeError("a defect")

    with capture_logs() as logs:
        found = await sender_of(
            cast("IdentityStore", _Defective()), chat_account(_PHONE), stage="chat_reader"
        )
    assert found == NO_LINK
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
    assert [one.facts for one in state.joined] == [None]
    assert state.work_facts == state.started_facts
    assert [(one["event"], one["at"]) for one in logs] == [
        ("work_facts_unrecorded", "start"),
        ("work_facts_unrecorded", "join"),
    ]
