"""Who sent an input, and a work's three facts, which decide.

ADR-0366 §4:1 and §5:6 have code decide who sent an input from the account it arrived
by, at that link's level; ADR-0368 §2 has code record three facts on every work when it
starts and again when an input joins it: whom it is for, whose authority it carries and
its level. This module is where both are decided, and **every reader reads them**
(ADR-0368 §9:1, §9:5): no code decides a sender, whom a work is for or whose authority it
carries from the channel type an input came by.

**Who sent an input** (:func:`sender_of`). The account each kind's input arrives by is
its reader's to name: the hub chat's is the device a message was written from
(:func:`chat_account`), the line's the Telegram account that sent it
(:func:`line_account`). The identity store's standing link for it names the person, at
:func:`~ai_assistant.core.channel_validation.link_level`; no link, no identified person,
at none. No other kind's input is sent by a person: an event a connected source pushes, a
task's occurrence and an approval's outcome record no sender.

**A hub chat message that came through another device** (:func:`chat_senders_of`,
ADR-0378 §4:3 to §4:6): where the device it came through is not the one it is written
from, both devices' links are read, each by :func:`sender_of`, and the message is from
the identity both tie, at the lower of the two levels, lowering included (ADR-0373
§2:9); from no identified person, at none, where either has no standing link or the two
tie different identities; and, where either read got no answer, one whose links cannot
be read, which ADR-0374 rules as written (:func:`unread`'s sender for the device it is
written from). A message that came through the device it is written from is read from
that device's link alone, as before. The same read serves a tap on the hub page through
another device (ADR-0378 §4:7). No signal raises such a sender (§4:4): nothing combines
signals under ADR-0366 §5:4 yet, so the lower level is the whole of the bound.

**Where the links cannot be read** (ADR-0374): the store raised, the read failed in any
other way, or no store is wired (§2:1). No fault is read as a link: the message is an
unidentified sender's, at none (:data:`LINKS_UNREAD`, §2:2), save one written on the
hub's own machine, the hub chat's device ``hub`` (:data:`HUB_MACHINE`, §3:1), which is
the owner's at the hub chat's declared most with no lowering read (§3:2, §4:2). Either
is marked ``links_unread`` (§5:1), and each read that got no answer is logged as
``input_sender_unread`` with the reader and the reason alone (§5:4). Where the links can
be read nothing changes (§3:3, §4:1).

**The three facts when a work starts** (:func:`started`), by ADR-0368 §3's table, for the
rows today's inputs produce:

- **A message** (its trigger records senders). For its sender where exactly one sender
  is identified (§3:1); for whoever the connection it came by belongs to otherwise
  (§3:3, §4:6). It carries its senders' authority (§3:2, §3:4) where it is their own
  words (ADR-0351 §6:1), as a forward is not (§6:2), and none otherwise. Its level is
  the lowest of its senders' (§4:1).
- **An input no person sent** (no senders): an event a connected source pushes, a task's
  occurrence or an approval's outcome. For whoever its connection or its record names,
  carrying no authority, at none (§3:5, the fourth and fifth rows), save a task's
  occurrence.
- **A task's occurrence** (its task handed in): its author's authority in advance, at the
  level the task records of the work that set it (§6:1, §6:3); none, at none, where the
  assistant set it, its task recording no person.
- **A kind with no row**: for no one, carrying no authority, at none (§3:7's row).

**Every connection belongs to the owner** until milestone 2 records whose each is
(ADR-0367 §6:1, #3642), and every task and approval request is the owner's (ADR-0350
§6:4, ADR-0361 §6:1), so each "whoever it belongs to" above is the owner, read in one
place (:func:`_its_owner`).

**When an input joins** (:func:`joined`), the facts are recorded again (§2:4). A join
never adds to the authority and never raises the level (§2:5): the level becomes the
lowest of the work's and the joining input's senders' (§4:1), and an input no person
sent lowers nothing; the authority stays where the joining input's is the same, and
becomes none where it differs. ADR-0368 §4:2 to §4:6's rules for several senders are not
built: ADR-0349 §7:5 still joins only inputs of one author, established alike, with one
authority, so whom the work is for does not move.

**What the readers read** (ADR-0368 §9). Whether a work is a person's, and whose
(:func:`persons_work`, §9:5): it is for a person, has no unidentified sender among the
senders its inputs record (:func:`held_senders`), read apart from its authority, and
carries the authority of no more than one person. Whose authority it carries
(:func:`persons_authority`, §9:1): the one identified person whose authority it carries,
now or in advance. Two inputs carry the same authority where they carry the same
people's (§9:2, :func:`authority_persons`). A work with no facts, because deciding them
failed, is no person's and carries no one's authority: **recording fails closed**.

**Only a person the hub admits** (ADR-0365 §1:3, ADR-0366 §1:3, ADR-0368 §1:4). The owner
is the one person a hub admits until a later decision provides for another, and nothing
the later milestones build to check a person's calls stands yet (ADR-0367). So both
readers answer for the owner alone: a work for, or carrying the authority of, any other
identity a link names is read as no person's, carrying no one's authority, whatever its
facts record. Nothing a real hub links names another identity (ADR-0366 §3:3); this
holds where a test's store does.

**A relay mark changes no fact.** Understanding marks an input relayed (ADR-0351 §5:6),
and a relayed input carries no authority (§6:5); but no model sets or changes a fact
(ADR-0368 §2:4), so the facts are recorded from the inputs alone and the relay mark,
which the episode keeps (ADR-0351 §5:9), is read beside them: :func:`persons_authority`
takes it.

**Where a condition naming a connection is met** (:func:`met_connection`, ADR-0368
§4:2, §6:4): the one connection every one of a work's senders' inputs came by, and in a
task's work the one its task records. A task records it of the work that set it (§6:3);
nothing reads it yet, and it is no fact of the work (§2:4).

**Whom the check runs for** (:func:`check_runs_for`, ADR-0368 §7): read from the work's
facts, a task's work's included, and what makes it carry none, and handed to the
authorizer, which decides none of it.

**One line per recording** (:func:`log_facts`): ``work_facts_recorded``, with what was
decided as codes and levels alone, never a person's identifier or an input's words, which
is what a running hub shows of the switch.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

import structlog
from pydantic import TypeAdapter, ValidationError

from ai_assistant.core.channel_validation import (
    APPROVALS,
    TASK_SCHEDULER,
    link_level,
    most_sureness,
    sent_by_a_person,
)
from ai_assistant.core.errors import IdentityStoreError
from ai_assistant.core.types import (
    HUB_DEVICE_ID,
    OWN_CHAT_CONNECTION,
    OWNER_PERSON_ID,
    Account,
    AuthorityKind,
    ChannelIdentity,
    CheckedFor,
    HolderKind,
    InputSender,
    LineConnection,
    RecordHome,
    Sureness,
    WorkAuthority,
    WorkFacts,
    WorkFor,
    WorkForKind,
    canonical_parties,
    senders_level,
)
from ai_assistant.orchestration.channel_kinds import place_of

if TYPE_CHECKING:
    from collections.abc import Hashable, Iterable, Mapping, Sequence

    from ai_assistant.core.protocols import IdentityStore
    from ai_assistant.core.types import (
        ApprovalTap,
        ChannelTarget,
        JoinedInput,
        RecordedChannelTrigger,
        RecordedInputMessage,
        ScheduledTask,
        SupportHolder,
    )

__all__ = [
    "CHAT_ACCOUNT_KIND",
    "HUB_MACHINE",
    "LINE_ACCOUNT_KIND",
    "LINKS_UNREAD",
    "NO_LINK",
    "authority_persons",
    "carries_in_advance",
    "chat_account",
    "chat_sender_of",
    "chat_senders_of",
    "check_runs_for",
    "held_senders",
    "joined",
    "line_account",
    "links_unread",
    "log_facts",
    "met_connection",
    "persons_authority",
    "persons_work",
    "record_joined",
    "record_started",
    "sender_of",
    "senders_of",
    "source_home",
    "started",
    "tap_runs_for",
    "unread",
    "unrecorded",
]

_log = structlog.get_logger(__name__)

#: The hub chat's account kind: its accounts are the devices it is written from
#: (ADR-0293 §4:1), as the identity store links them (ADR-0366 §3).
CHAT_ACCOUNT_KIND: Final = "conversation"

#: The line's account kind: its accounts are Telegram user ids, as text (ADR-0323 §3:2).
LINE_ACCOUNT_KIND: Final = "telegram"

#: Who sent an input that arrived by an account no standing link ties: no identified
#: person, at none (ADR-0366 §4:1, §5:6).
NO_LINK: Final = InputSender(person=None, level=Sureness.NONE)

#: Who sent a message whose link could not be read: no identified person, at none,
#: marked (ADR-0374 §2:2, §5:1).
LINKS_UNREAD: Final = InputSender(person=None, level=Sureness.NONE, links_unread=True)

#: The account a message written on the hub's own machine arrived by: the hub chat's
#: device ``hub``, a browser on a gateway's loopback listener there included (ADR-0374
#: §3:1, ADR-0298 §3:1). No other account is: no other kind's, and no other device's.
HUB_MACHINE: Final = Account(kind=CHAT_ACCOUNT_KIND, identifier=HUB_DEVICE_ID)

#: The kinds whose input no person sends, each with a row of ADR-0368 §3's table: an
#: event a connected source pushes (§3:5), a task's occurrence and an approval's outcome.
_SENT_BY_NO_PERSON: Final = frozenset({"informational_event", TASK_SCHEDULER, APPROVALS})

#: The people the hub admits: the owner alone, until a later decision provides for
#: another and it is built (ADR-0365 §1:3, ADR-0366 §1:3, ADR-0368 §1:4). The readers
#: answer for them alone (:func:`persons_work`, :func:`persons_authority`).
_ADMITTED: Final = frozenset({OWNER_PERSON_ID})

#: A connection as a line names it (ADR-0376 §2:4), which a place's spelling is checked
#: against before a task records it.
_LINE_CONNECTION: Final = TypeAdapter[str](LineConnection)

#: The parties of a message its sender wrote: a person a link establishes, or unknown
#: for a sender no link does (ADR-0351 §3:2). A forward's is an outside source, claimed.
_SENDERS_WORDS: Final = frozenset({HolderKind.PERSON, HolderKind.UNKNOWN})


def chat_account(device_id: str | None) -> Account | None:
    """The account a hub chat message arrived by: the device it was written from.

    Args:
        device_id: The message's device, as the transcript records it (ADR-0293 §5:2).

    Returns:
        The account; ``None`` where the message names no device.
    """
    if device_id is None or not device_id.strip():
        return None
    return Account(kind=CHAT_ACCOUNT_KIND, identifier=device_id)


def line_account(sender_id: int | None) -> Account | None:
    """The account a line message arrived by: the Telegram account that sent it.

    Args:
        sender_id: The account Telegram names as its sender (ADR-0323 §4:3).

    Returns:
        The account, its identifier the id as text; ``None`` where Telegram names none.
    """
    if sender_id is None:
        return None
    return Account(kind=LINE_ACCOUNT_KIND, identifier=str(sender_id))


async def sender_of(
    identities: IdentityStore | None, account: Account | None, *, stage: str
) -> InputSender:
    """Who sent an input that arrived by ``account``, and at what level (ADR-0366 §4:1).

    The person a standing link ties the account to, at that link's level (§5:3, §5:6),
    or :data:`NO_LINK` where none does, or where the input names no account. Where no
    identity store is wired, or it cannot be read, the links cannot be read for it
    (ADR-0374 §2:1): the fault is logged under a fixed event name, and the input is
    recorded as :func:`unread` says. A defect in the read is such a fault too: it is
    never read as a link, and never stops the input.

    Args:
        identities: The identity store, or ``None`` where none is wired.
        account: The account the input arrived by, or ``None`` where it names none.
        stage: The reader asking, named in the log entry of a read that got no answer.

    Returns:
        The sender.
    """
    if account is None:
        return NO_LINK
    if identities is None:
        return unread(account, stage=stage, reason="unwired")
    try:
        link = await identities.find_link(account)
    except IdentityStoreError:
        return unread(account, stage=stage, reason="identity_store")
    except Exception:  # ADR-0374 §2:1: any failed read is a fault, never a link
        return unread(account, stage=stage, reason="defect")
    if link is None:
        return NO_LINK
    return InputSender(person=link.person_id, level=link_level(link))


def unread(account: Account, *, stage: str, reason: str) -> InputSender:
    """Who sent a message that arrived by ``account`` when its link could not be read.

    ADR-0374: no fault is read as a link, and nothing stands in for it (§2:3), so the
    message is an unidentified sender's, at none (:data:`LINKS_UNREAD`, §2:2), save one
    written on the hub's own machine (:data:`HUB_MACHINE`, §3:1), which is the owner's at
    the most the hub chat's kind declares in this build, with no lowering read (§3:2,
    §4:2). Either is marked (§5:1). The read is logged as ``input_sender_unread`` with
    the reader and the reason, and with no account's or person's identifier (§5:4).

    Args:
        account: The account the message arrived by.
        stage: The reader that asked.
        reason: Why it got no answer: ``unwired``, ``identity_store`` or ``defect``.

    Returns:
        The sender, marked.
    """
    _log.warning("input_sender_unread", reader=stage, reason=reason)
    return _unread_sender(account)


def _unread_sender(account: Account | None) -> InputSender:
    """:func:`unread`'s sender for a message arriving by ``account``, unlogged.

    ADR-0374 §2:2, §3:2: the owner's for the hub's own machine, and otherwise no one's.
    """
    if account == HUB_MACHINE:
        return InputSender(
            person=OWNER_PERSON_ID, level=most_sureness(CHAT_ACCOUNT_KIND), links_unread=True
        )
    return LINKS_UNREAD


def _through(written: InputSender, through: InputSender, *, account: Account | None) -> InputSender:
    """Who sent a hub chat message read from both devices' links (ADR-0378 §4:3 to §4:5).

    Args:
        written: What the link of the device it is written from found.
        through: What the link of the device it came through found.
        account: The account of the device it is written from.

    Returns:
        The identity both links tie, at the lower level; no identified person, at none,
        where either has no standing link or they tie different identities; and where
        either read got no answer, ADR-0374's sender for the device it is written from.
    """
    if written.links_unread or through.links_unread:
        return _unread_sender(account)
    if written.person is None or written.person != through.person:
        return NO_LINK
    return InputSender(person=written.person, level=min(written.level, through.level))


async def chat_senders_of[K: Hashable](
    identities: IdentityStore | None,
    devices: Mapping[K, tuple[str | None, str | None]],
    *,
    stage: str,
) -> dict[K, InputSender]:
    """Who sent each hub chat message, by the device written from and the one come through.

    ADR-0378 §4:3 to §4:6: a message that came through the device it is written from, or
    that names no device it came through, is read from that device's link alone, as
    :func:`senders_of` reads it; one that came through another is read from both links,
    by :func:`_through`. Each account is read once.

    Args:
        identities: The identity store, or ``None`` where none is wired.
        devices: Each message's device it is written from and device it came through, by
            the key its reader holds it under.
        stage: The reader asking.

    Returns:
        Each message's sender, under its key.
    """
    found: dict[Account | None, InputSender] = {}

    async def read(account: Account | None) -> InputSender:
        if account not in found:
            found[account] = await sender_of(identities, account, stage=stage)
        return found[account]

    senders: dict[K, InputSender] = {}
    for key, (device_id, came_through) in devices.items():
        account = chat_account(device_id)
        written = await read(account)
        if came_through is None or came_through == device_id:
            senders[key] = written
            continue
        through = await read(chat_account(came_through))
        senders[key] = _through(written, through, account=account)
    return senders


async def chat_sender_of(
    identities: IdentityStore | None,
    device_id: str | None,
    came_through: str | None,
    *,
    stage: str,
) -> InputSender:
    """Who sent one hub chat message or tap, as :func:`chat_senders_of` reads each.

    Args:
        identities: The identity store, or ``None`` where none is wired.
        device_id: The device it is written from, or the tap's requesting device.
        came_through: The device it came through: the request's connecting device.
        stage: The reader asking.

    Returns:
        The sender.
    """
    found = await chat_senders_of(identities, {0: (device_id, came_through)}, stage=stage)
    return found[0]


async def senders_of[K: Hashable](
    identities: IdentityStore | None, accounts: Mapping[K, Account | None], *, stage: str
) -> dict[K, InputSender]:
    """Who sent each message, by the account each arrived by, each account read once.

    Args:
        identities: The identity store, or ``None`` where none is wired.
        accounts: Each message's account, by the key its reader holds it under.
        stage: The reader asking.

    Returns:
        Each message's sender, under its key.
    """
    found: dict[Account | None, InputSender] = {}
    for account in accounts.values():
        if account not in found:
            found[account] = await sender_of(identities, account, stage=stage)
    return {key: found[account] for key, account in accounts.items()}


def _kind(trigger: RecordedChannelTrigger) -> str:
    """The channel type a trigger's input came in on; a new conversation is the hub chat's."""
    if trigger.channel is not None:
        return trigger.channel.channel_type
    if isinstance(trigger.target, ChannelIdentity):
        return trigger.target.channel_type
    return CHAT_ACCOUNT_KIND


def _its_owner() -> WorkFor:
    """Whom a connection, a task or an approval request belongs to: today, the owner.

    ADR-0367 §6:1: every connection is the owner's until milestone 2 records whose each
    is (#3642), and every task and approval request is the owner's (ADR-0350 §6:4,
    ADR-0361 §6:1), as the hub serves one person.
    """
    return WorkFor.for_person(OWNER_PERSON_ID)


def _own_words(
    parties: Sequence[SupportHolder] | None, messages: Iterable[RecordedInputMessage]
) -> bool:
    """Whether an input is its senders' own words (ADR-0351 §6:1, §6:2).

    Its parties are known and not empty, each is a person or the unknown an unidentified
    sender's words take (ADR-0351 §3:2), and none of its messages is a forward, whose
    words are its original sender's, claimed, however the medium named them (§2:7).
    """
    return (
        bool(parties)
        and parties is not None
        and all(one.kind in _SENDERS_WORDS for one in parties)
        and not any(one.forwarded_from is not None for one in messages)
    )


def _authority(senders: Sequence[InputSender], *, own: bool) -> WorkAuthority:
    """The authority an input from ``senders`` carries (ADR-0368 §3:2, §3:4).

    Its senders', each identified one by id and whether one is unidentified, where it is
    their own words; none otherwise, as for a forward.
    """
    if not own:
        return WorkAuthority.none()
    persons = tuple(sorted({one.person for one in senders if one.identified and one.person}))
    return WorkAuthority(
        kind=AuthorityKind.SENDERS,
        persons=persons,
        unidentified=any(not one.identified for one in senders),
    )


def _whom(senders: Sequence[InputSender]) -> WorkFor:
    """Whom an input from ``senders`` is for (ADR-0368 §3:1, §3:3, §4:6)."""
    identified = {one.person for one in senders if one.identified and one.person}
    if len(identified) == 1 and all(one.identified for one in senders):
        return WorkFor.for_person(identified.pop())
    return _its_owner()


def _in_advance(task: ScheduledTask) -> WorkFacts:
    """A task's work's facts (ADR-0368 §6:1, §6:3, §7's fifth row).

    For whoever the task belongs to, carrying its author's authority in advance, at the
    level the task records of the work that set it; carrying none, at none, where the task
    records no person, as one the assistant set does.
    """
    author = task.author_person
    if author is None:
        return WorkFacts(for_whom=_its_owner(), authority=WorkAuthority.none(), level=Sureness.NONE)
    return WorkFacts(
        for_whom=_its_owner(),
        authority=WorkAuthority(kind=AuthorityKind.IN_ADVANCE, persons=(author,)),
        level=task.setting_level,
    )


def started(trigger: RecordedChannelTrigger, *, task: ScheduledTask | None = None) -> WorkFacts:
    """The three facts a work starts with, from its recorded trigger (ADR-0368 §2, §3).

    Args:
        trigger: The work's recorded trigger, with its senders.
        task: For a task's occurrence, the task its input names, whose recorded author and
            level its work carries (§6:1, §6:3); ``None`` for every other input.

    Returns:
        Whom it is for, whose authority it carries and its level.
    """
    if task is not None and _kind(trigger) == TASK_SCHEDULER and not trigger.senders:
        return _in_advance(task)
    senders = trigger.senders
    level = senders_level(senders)
    if level is not None:
        return WorkFacts(
            for_whom=_whom(senders),
            authority=_authority(senders, own=_own_words(trigger.parties, trigger.messages)),
            level=level,
        )
    kind = _kind(trigger)
    has_a_row = kind in _SENT_BY_NO_PERSON or sent_by_a_person(kind)
    whom = _its_owner() if has_a_row else WorkFor.no_one()
    return WorkFacts(for_whom=whom, authority=WorkAuthority.none(), level=Sureness.NONE)


def _parties(messages: Iterable[SupportHolder | None]) -> tuple[SupportHolder, ...] | None:
    """A joined input's parties, from its messages', or ``None`` where they are unknown."""
    held = list(messages)
    if any(one is None for one in held):
        return None
    return canonical_parties(one for one in held if one is not None)


def joined(facts: WorkFacts, input: JoinedInput) -> WorkFacts:  # noqa: A002 — the input that joins
    """The three facts once ``input`` joined a work that held ``facts`` (ADR-0368 §2:4).

    Never more authority and never a higher level (§2:5): the level is the lowest of the
    work's and the input's senders' (§4:1); an input no person sent lowers nothing; the
    authority stays where the input's is the same, and is none where it differs. Whom the
    work is for does not move (ADR-0349 §7:5 joins one author's inputs alone).

    Args:
        facts: The work's facts before the input joined.
        input: The input that joined, its messages each recording its sender.

    Returns:
        The work's facts now.
    """
    senders = input.senders
    level = senders_level(senders)
    if level is None:
        return facts
    own = _own_words(_parties(one.party for one in input.messages), input.messages)
    incoming = _authority(senders, own=own)
    authority = facts.authority if incoming == facts.authority else WorkAuthority.none()
    return WorkFacts(for_whom=facts.for_whom, authority=authority, level=min(facts.level, level))


def held_senders(
    trigger: RecordedChannelTrigger, joined: Iterable[JoinedInput]
) -> tuple[InputSender, ...]:
    """Every sender of every input a work holds: its trigger's, then each joined input's.

    What a reader hands :func:`persons_work` and :func:`persons_authority` for a stored
    work, from its episode's record (ADR-0368 §2:6).

    Args:
        trigger: The work's recorded trigger.
        joined: The inputs that joined it.

    Returns:
        The senders, as recorded.
    """
    return (*trigger.senders, *(sender for one in joined for sender in one.senders))


def _with_an_unidentified(senders: Iterable[InputSender]) -> bool:
    """Whether any of ``senders`` is unidentified: no person, or at none (ADR-0368 §9:4)."""
    return any(not one.identified for one in senders)


def persons_work(facts: WorkFacts | None, senders: Iterable[InputSender]) -> str | None:
    """The person whose work it is, where it is a person's (ADR-0368 §9:5).

    It is for a person, has no unidentified sender, and carries the authority of no more
    than one person: what ADR-0338 §2:3, ADR-0350 §3:4, ADR-0356 §4:5 and ADR-0361 §2:5
    read as an activation being a person's, as the person block, spawn's offer, the
    approval request and every reader of the person a work is for do. Whether it has an
    unidentified sender is read from the senders its inputs record, apart from whose
    authority it carries: a forward an unidentified sender sent carries no authority, so
    its authority says nothing of who sent it, and its work is still no person's. A work
    with no facts is no person's, and so is one for a person the hub does not admit
    (:data:`_ADMITTED`).

    Args:
        facts: The work's facts as they stand, or ``None`` where none were recorded.
        senders: Every sender of every input the work holds, as recorded
            (:func:`held_senders`).

    Returns:
        The person's id, or ``None`` where it is no person's.
    """
    if facts is None or _with_an_unidentified(senders):
        return None
    whom = facts.for_whom
    authority = facts.authority
    if whom.kind is not WorkForKind.PERSON or whom.id not in _ADMITTED:
        return None
    if authority.unidentified or len(authority.persons) > 1:
        return None
    return whom.id


def work_home(facts: WorkFacts | None) -> RecordHome:
    """The home a work's write takes, from whom it is for (ADR-0383 §4:1).

    :meth:`~ai_assistant.core.types.RecordHome.of_work` of whom its facts say it is for:
    a person's domain, or the shared things for a work for no one. An unidentified
    sender's work is for whoever its connection belongs to (ADR-0368 §3:3), which its
    facts already record, so it writes there (ADR-0383 §4:4). A work with no facts, one
    whose facts could not be decided (:func:`record_started`), is read as a work for no
    one, as :func:`record_started` and :func:`persons_work` already read it, so it
    writes into the shared things. Whom a work is for never changes once recorded, so
    every write it makes carries the same home.

    Args:
        facts: The work's facts as they stand, or ``None`` where none were recorded.

    Returns:
        The home.
    """
    return RecordHome.of_work(WorkFor.no_one() if facts is None else facts.for_whom)


def source_home() -> RecordHome:
    """The home of a record brought in outside any work, from its source (ADR-0383 §4:3).

    A notification a producer makes from a source takes the home of whoever its
    connection, account or source belongs to, read by the one rule the code reads ADR-0368
    §3:3's "whoever the connection it came by belongs to" by (:func:`_its_owner`): in this
    milestone, the owner's domain.

    Returns:
        The home.
    """
    return RecordHome.of_work(_its_owner())


def authority_persons(facts: WorkFacts | None) -> tuple[str, ...]:
    """The identified people whose authority a work carries, now or in advance (§9:1, §9:2).

    By id, in order; none where it carries an unidentified sender's beside them, no one's,
    or has no facts. Two inputs carry the same authority where this is the same for both
    (§9:2), whatever their levels.

    Args:
        facts: The facts, or ``None`` where none were recorded.

    Returns:
        The people.
    """
    if facts is None or facts.authority.unidentified:
        return ()
    return facts.authority.persons


def carries_in_advance(facts: WorkFacts | None) -> bool:
    """Whether a work carries a person's authority in advance, as a task's work does (§6:1).

    Such authority is the task's, not its input's words': whether those words are a
    sender's own is not read of it (ADR-0321 §3:3 reads a yes from words, and a task's input
    states its task). A relayed input still takes it away, as it takes any authority away
    from the activation holding it (ADR-0351 §6:5, which ADR-0368 §10 keeps).

    Args:
        facts: The work's facts, or ``None`` where none were recorded.

    Returns:
        Whether its authority is in advance.
    """
    return facts is not None and facts.authority.kind is AuthorityKind.IN_ADVANCE


def persons_authority(
    facts: WorkFacts | None, senders: Iterable[InputSender], *, relayed: bool = False
) -> str | None:
    """The person whose authority a work carries, where it carries one's (ADR-0368 §9:1).

    What every earlier decision's "the input carries the user's authority" reads: the
    work carries the authority of one identified person, now or in advance, and no
    unidentified sender's beside it (§2:2), no input it holds has an unidentified sender,
    and no input it holds is relayed (ADR-0351 §6:5), which no fact records (§2:4) and the
    caller hands in, authority in advance included. Where it names the user, it names this
    person. A person the hub does not admit carries none here (:data:`_ADMITTED`).

    Args:
        facts: The work's facts as they stand, or ``None`` where none were recorded.
        senders: Every sender of every input the work holds, as recorded
            (:func:`held_senders`).
        relayed: Whether any input the work holds is relayed.

    Returns:
        The person's id, or ``None`` where the work carries no person's authority.
    """
    persons = authority_persons(facts)
    if relayed or _with_an_unidentified(senders):
        return None
    if len(persons) != 1 or persons[0] not in _ADMITTED:
        return None
    return persons[0]


def _connection(target: ChannelTarget) -> str:
    """The connection an input came by, as a line names it (ADR-0376 §2:4).

    The system's own chat is one connection, whichever conversation; any other place is
    named as an effect record names it, ``<channel type>:<instance id>``.
    """
    if not isinstance(target, ChannelIdentity) or target.channel_type == CHAT_ACCOUNT_KIND:
        return OWN_CHAT_CONNECTION
    return place_of(target)


def met_connection(
    trigger: RecordedChannelTrigger | None,
    joined: Iterable[JoinedInput],
    *,
    task: ScheduledTask | None = None,
) -> str | None:
    """The one connection a grant's condition naming a connection is met for in a work.

    ADR-0368 §4:2: a condition naming a connection is met where every one of the work's
    senders' inputs came by it, so it is met for the one connection they all came by,
    and for none where they came by several or the work has no sender. §6:4: in a task's
    work, it is met where it was met in the work that set the task, which the task records
    (``setting_connection``), and the work's senders' inputs, where it holds any, came by
    that one too. What a task records of where it was set is this, read of the work that
    set it (§6:3); nothing here decides a fact of the work (§2:4).

    Args:
        trigger: The work's recorded trigger, or ``None`` where no channel admitted it.
        joined: The inputs that joined it.
        task: The task whose occurrence started it, where it is a task's work.

    Returns:
        The connection, as a line names it; ``None`` where no one connection is met.
    """
    connections: set[str] = set()
    if trigger is not None and trigger.senders:
        connections.add(_connection(trigger.channel or trigger.target))
    connections.update(_connection(one.channel) for one in joined if one.senders)
    if task is not None:
        if task.setting_connection is None:
            return None
        connections.add(task.setting_connection)
    if len(connections) != 1:
        return None
    (only,) = connections
    try:
        return _LINE_CONNECTION.validate_python(only)
    except ValidationError:  # a place no line can name meets no condition
        return None


def _admitted(person: str | None, level: Sureness) -> CheckedFor:
    """``person`` at ``level``, where the hub admits them; no one otherwise (:data:`_ADMITTED`)."""
    if person is None or person not in _ADMITTED:
        return CheckedFor.no_one()
    return CheckedFor.for_person(person, level)


def check_runs_for(
    facts: WorkFacts | None, *, own_input: bool, relayed: bool
) -> tuple[CheckedFor, ...]:
    """Whom the check runs for in a work, and at what level (ADR-0368 §7's table).

    Read from what the work's facts record, and decided nowhere else (ADR-0367 §4:1):

    - **A work carrying authority in advance**, as a task's work does: its author, at the
      level its facts record, the level the task records of the work that set it (§6:1,
      §6:3, §7's fifth row), whatever its input's words are (:func:`carries_in_advance`),
      and no one where it holds a relayed input (ADR-0351 §6:5). A task the assistant set
      carries none.
    - **A sender's work**: each identified person whose authority it carries, at the
      work's level, and a member of anyone alone, at none, where it carries an
      unidentified sender's (§7:1 to §7:3).
    - **A work that carries none** (§7:5): no one, at none. So is a work with no facts,
      and a sender's work whose input is not its senders' own words (``own_input``,
      ADR-0321 §3:3) or that holds a relayed input (ADR-0351 §6:5), whatever its facts
      say (ADR-0368 §9:1), as :func:`persons_authority` reads it.

    A person the hub does not admit is read as no one (:data:`_ADMITTED`).

    Args:
        facts: The work's facts as they stand, or ``None`` where none were recorded.
        own_input: Whether every message the work's input took in is its sender's own.
        relayed: Whether any input the work holds is relayed.

    Returns:
        Each one the check runs for, in order, no one repeated; at least one.
    """
    if facts is None or relayed:
        return (CheckedFor.no_one(),)
    authority = facts.authority
    if authority.kind is AuthorityKind.IN_ADVANCE:
        return (_admitted(authority.persons[0], facts.level),)
    if not own_input or authority.kind is AuthorityKind.NONE:
        return (CheckedFor.no_one(),)
    runs = [_admitted(one, facts.level) for one in authority.persons]
    if authority.unidentified:
        runs.append(CheckedFor.anyone())
    return tuple(dict.fromkeys(runs)) or (CheckedFor.no_one(),)


def tap_runs_for(tap: ApprovalTap) -> CheckedFor:
    """Whom the check runs for on a call run under a ticket, and at what level.

    ADR-0367 §5:5: the person whose tap approved it, at the level that tap came by, which
    the request's answer records (ADR-0377 §4:1, §4:2), and none where it records none
    (§4:4). A tap read as no one's is an unidentified tapper's, a member of anyone alone at
    none, as a message by that account would be (ADR-0377 §2, ADR-0368 §7:2). A person the
    hub does not admit is read as no one (:data:`_ADMITTED`).

    Args:
        tap: The request's answer, as the plan store holds it.

    Returns:
        Whom the check runs for.
    """
    if tap.person is None:
        return CheckedFor.anyone()
    return _admitted(tap.person, tap.level_read)


def links_unread(senders: Iterable[InputSender]) -> bool:
    """Whether any of ``senders`` was set because the links could not be read (ADR-0374 §5:1)."""
    return any(one.links_unread for one in senders)


def log_facts(
    facts: WorkFacts,
    senders: Sequence[InputSender],
    *,
    activation_id: str | None,
    at: str,
) -> None:
    """Log what was decided of a work: one ``work_facts_recorded`` entry.

    Each time the facts are recorded: when the work starts (``at="start"``) and when an
    input joins it (``at="join"``). It says whom the work is for (``for_whom``, a kind),
    whose authority it carries (``whose``, a kind, and ``unidentified``, whether an
    unidentified sender's is among it), its level (``facts_level``), whether the links
    could not be read for any input they were recorded from (``links_unread``, ADR-0374
    §5:1), and what the readers then read of it: whether it is a person's work
    (``persons_work``, ADR-0368 §9:5) and whether it carries a person's authority before
    any relay mark (``carries_a_persons``, §9:1). It carries codes, levels and truth
    values alone, never a person's id or an input's words (ADR-0275 §8), and changes no
    answer. Whose authority is logged as ``whose`` and its reading as
    ``carries_a_persons``: a key naming "auth" is masked by the log's redaction
    (``core.logging``). The level is logged as ``facts_level``: the configured chain's
    ``add_log_level`` owns ``level``, as it owns ``event`` and ``timestamp``.

    Args:
        facts: The facts recorded.
        senders: Every sender of every input they were recorded from.
        activation_id: The work's activation.
        at: When they were recorded: ``start`` or ``join``.
    """
    _log.info(
        "work_facts_recorded",
        activation_id=activation_id,
        at=at,
        links_unread=links_unread(senders),
        for_whom=facts.for_whom.kind.value,
        whose=facts.authority.kind.value,
        unidentified=facts.authority.unidentified,
        facts_level=facts.level.value,
        persons_work=persons_work(facts, senders) is not None,
        carries_a_persons=persons_authority(facts, senders) is not None,
    )


def _logged(
    facts: WorkFacts, senders: Sequence[InputSender], *, activation_id: str | None, at: str
) -> None:
    """:func:`log_facts`, whose own fault is logged and never undoes the recording."""
    try:
        log_facts(facts, senders, activation_id=activation_id, at=at)
    except Exception:  # the log is read beside the facts, never in their place
        _log.warning("work_facts_unlogged", at=at, reason="defect")


def record_started(
    trigger: RecordedChannelTrigger,
    *,
    activation_id: str | None,
    task: ScheduledTask | None = None,
) -> WorkFacts | None:
    """The facts a work starts with, logged; ``None`` on a defect.

    Recording them never stops an admission, and **fails closed**: a fault in deciding
    them is logged under a fixed event name and the work records none, which every
    reader reads as no person's work carrying no one's authority (:func:`persons_work`,
    :func:`persons_authority`); a fault in logging them is logged apart and keeps them.

    Args:
        trigger: The work's recorded trigger.
        activation_id: The work's activation.
        task: For a task's occurrence, its task (:func:`started`).

    Returns:
        The facts, or ``None`` where they could not be decided.
    """
    try:
        facts = started(trigger, task=task)
    except Exception:  # fails closed: no facts are no person's and carry no authority
        _log.warning("work_facts_unrecorded", at="start", reason="defect")
        return None
    _logged(facts, trigger.senders, activation_id=activation_id, at="start")
    return facts


def unrecorded(inputs: Sequence[JoinedInput]) -> tuple[JoinedInput, ...]:
    """``inputs`` with no facts: what another work recorded on them is not this work's.

    An absorption or a take brings the other activation's joined inputs, each carrying
    the facts *that* work recorded (ADR-0349 §7:7, §7:21). They are taken off before the
    inputs join, so the work that takes them in never reads another work's facts as its
    own, which could raise its level (ADR-0368 §2:5).

    Args:
        inputs: The inputs joining.

    Returns:
        Each, its ``facts`` ``None``.
    """
    return tuple(
        one if one.facts is None else one.model_copy(update={"facts": None}) for one in inputs
    )


def _closed(facts: WorkFacts) -> WorkFacts:
    """``facts`` with no authority, at none: what a join records where deciding failed."""
    return WorkFacts(for_whom=facts.for_whom, authority=WorkAuthority.none(), level=Sureness.NONE)


def record_joined(
    facts: WorkFacts,
    inputs: Sequence[JoinedInput],
    trigger: RecordedChannelTrigger,
    *,
    activation_id: str | None,
    earlier: Sequence[JoinedInput] = (),
) -> tuple[JoinedInput, ...]:
    """``inputs``, each carrying the work's facts as they stand once it joined.

    ADR-0368 §2:4, each recording logged. Whatever facts an input arrives with, another
    work's, are replaced (:func:`unrecorded`). Recording them never stops a join, and
    **fails closed**: on a fault in deciding them, logged under a fixed event name, each
    input records the work's facts with no authority, at none, so the work reads as
    carrying no one's authority from then on (§2:5); a fault in logging them is logged
    apart and keeps them.

    Args:
        facts: The work's facts before the first of them joined.
        inputs: The inputs joining, in order.
        trigger: The work's recorded trigger, read only for its senders, which the log
            reads (ADR-0374 §5:1, ADR-0368 §9:5).
        activation_id: The work's activation.
        earlier: The inputs that joined the work before these, which the facts were
            recorded from too: read only for their senders, as the trigger is.

    Returns:
        The inputs, each with this work's ``facts``.
    """
    try:
        recorded: list[tuple[JoinedInput, WorkFacts, tuple[InputSender, ...]]] = []
        senders = held_senders(trigger, earlier)
        for one in inputs:
            facts = joined(facts, one)
            senders = (*senders, *one.senders)
            recorded.append((one.model_copy(update={"facts": facts}), facts, senders))
    except Exception:  # fails closed: the work carries no one's authority from here
        _log.warning("work_facts_unrecorded", at="join", reason="defect")
        closed = _closed(facts)
        return tuple(one.model_copy(update={"facts": closed}) for one in inputs)
    for _, held, so_far in recorded:
        _logged(held, so_far, activation_id=activation_id, at="join")
    return tuple(one for one, _, _ in recorded)
