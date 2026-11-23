"""Who sent an input, and a work's three facts, recorded beside today's path.

ADR-0366 §4:1 and §5:6 have code decide who sent an input from the account it arrived
by, at that link's level; ADR-0368 §2 has code record three facts on every work when it
starts and again when an input joins it: whom it is for, whose authority it carries and
its level. This module is where both are decided, and **nothing reads them yet**
(ADR-0368 §1:3): who a work is for and whether it carries the user's authority are still
read from the channel type, by
:func:`~ai_assistant.orchestration.person_block.activation_person` and the true or false
``users_authority``, and each recording here is compared with that reading and logged,
so a running hub shows where the two disagree before any reader moves to the facts.

**Who sent an input** (:func:`sender_of`). The account each kind's input arrives by is
its reader's to name: the hub chat's is the device a message was written from
(:func:`chat_account`), the line's the Telegram account that sent it
(:func:`line_account`). The identity store's standing link for it names the person, at
:func:`~ai_assistant.core.channel_validation.link_level`; no link, no identified person,
at none. No other kind's input is sent by a person: an event a connected source pushes, a
task's occurrence and an approval's outcome record no sender.

**The three facts when a work starts** (:func:`started`), by ADR-0368 §3's table, for the
rows today's inputs produce:

- **A message** (its trigger records senders). For its sender where exactly one sender
  is identified (§3:1); for whoever the connection it came by belongs to otherwise
  (§3:3, §4:6). It carries its senders' authority (§3:2, §3:4) where its parties are the
  senders' own words (ADR-0351 §6:1), as a forward's are not (§6:2), and none otherwise.
  Its level is the lowest of its senders' (§4:1).
- **An input no person sent** (no senders): an event a connected source pushes, a task's
  occurrence or an approval's outcome. For whoever its connection or its record names,
  carrying no authority, at none (§3:5, the fourth and fifth rows). A task's work carries
  its author's authority only once ADR-0368 §6 is built, which is milestone 2's.
- **A kind with no row**: for no one, carrying no authority, at none (§3:7's row).

**Every connection belongs to the owner** until milestone 2 records whose each is
(ADR-0367 §6:1, #3642), and every task and approval request is the owner's (ADR-0350
§6:4, ADR-0361 §6:1, as ``activation_person`` reads them), so each "whoever it belongs
to" above is the owner, read in one place (:func:`_its_owner`).

**When an input joins** (:func:`joined`), the facts are recorded again (§2:4). A join
never adds to the authority and never raises the level (§2:5): the level becomes the
lowest of the work's and the joining input's senders' (§4:1), and an input no person
sent lowers nothing; the authority stays where the joining input's is the same, and
becomes none where it differs. ADR-0368 §4:2 to §4:6's rules for several senders are not
built: ADR-0349 §7:5 still joins only inputs of one author, established alike, with one
authority, so whom the work is for does not move.

**A relay mark changes no fact.** Understanding marks an input relayed (ADR-0351 §5:6),
and a relayed input carries no authority (§6:5); but no model sets or changes a fact
(ADR-0368 §2:4), so the facts are recorded from the inputs alone and the relay mark,
which the episode keeps (ADR-0351 §5:9), is read beside them, as ``users_authority`` is
read beside it today.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

import structlog

from ai_assistant.core.channel_validation import (
    APPROVALS,
    TASK_SCHEDULER,
    establishes_the_user,
    link_level,
)
from ai_assistant.core.errors import IdentityStoreError
from ai_assistant.core.types import (
    OWNER_PERSON_ID,
    Account,
    AuthorityKind,
    ChannelIdentity,
    InputSender,
    Sureness,
    WorkAuthority,
    WorkFacts,
    WorkFor,
    WorkForKind,
    canonical_parties,
    parties_are_persons_own,
    senders_level,
)
from ai_assistant.orchestration.person_block import activation_person

if TYPE_CHECKING:
    from collections.abc import Hashable, Iterable, Mapping, Sequence

    from ai_assistant.core.protocols import IdentityStore
    from ai_assistant.core.types import JoinedInput, RecordedChannelTrigger, SupportHolder

__all__ = [
    "CHAT_ACCOUNT_KIND",
    "LINE_ACCOUNT_KIND",
    "NO_LINK",
    "TodaysPath",
    "chat_account",
    "disagreements",
    "joined",
    "line_account",
    "log_facts",
    "record_joined",
    "record_started",
    "sender_of",
    "senders_of",
    "started",
    "todays_path",
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

#: The kinds whose input no person sends, each with a row of ADR-0368 §3's table: an
#: event a connected source pushes (§3:5), a task's occurrence and an approval's outcome.
_SENT_BY_NO_PERSON: Final = frozenset({"informational_event", TASK_SCHEDULER, APPROVALS})

#: The kinds whose input a person sends, by an account: the hub chat and the line.
_SENT_BY_A_PERSON: Final = frozenset({CHAT_ACCOUNT_KIND, LINE_ACCOUNT_KIND})


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
    or :data:`NO_LINK` where none does. Where no identity store is wired, or it cannot be
    read, no link is found: the fault is logged under a fixed event name, and the input
    is recorded as arriving by no link. Nothing reads the sender yet (ADR-0368 §1:3), so
    no answer the hub gives moves on it.

    Args:
        identities: The identity store, or ``None`` where none is wired.
        account: The account the input arrived by, or ``None`` where it names none.
        stage: The reader asking, named in the log entry of a store that failed.

    Returns:
        The sender.
    """
    if identities is None or account is None:
        return NO_LINK
    try:
        link = await identities.find_link(account)
    except IdentityStoreError:
        _log.warning("input_sender_unread", stage=stage, reason="identity_store")
        return NO_LINK
    except Exception:  # nothing reads a sender yet, so no fault stops an input
        _log.warning("input_sender_unread", stage=stage, reason="defect")
        return NO_LINK
    if link is None:
        return NO_LINK
    return InputSender(person=link.person_id, level=link_level(link))


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
    """The channel type a trigger's input came in on, as ``activation_person`` reads it."""
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


def _authority(senders: Sequence[InputSender], *, own: bool) -> WorkAuthority:
    """The authority an input from ``senders`` carries (ADR-0368 §3:2, §3:4).

    Its senders', each identified one by id and whether one is unidentified, where its
    parties are the senders' own words; none otherwise, as for a forward.
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


def started(trigger: RecordedChannelTrigger) -> WorkFacts:
    """The three facts a work starts with, from its recorded trigger (ADR-0368 §2, §3).

    Args:
        trigger: The work's recorded trigger, with its senders.

    Returns:
        Whom it is for, whose authority it carries and its level.
    """
    senders = trigger.senders
    level = senders_level(senders)
    if level is not None:
        return WorkFacts(
            for_whom=_whom(senders),
            authority=_authority(senders, own=parties_are_persons_own(trigger.parties)),
            level=level,
        )
    kind = _kind(trigger)
    whom = _its_owner() if kind in _SENT_BY_NO_PERSON | _SENT_BY_A_PERSON else WorkFor.no_one()
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
    own = parties_are_persons_own(_parties(one.party for one in input.messages))
    incoming = _authority(senders, own=own)
    authority = facts.authority if incoming == facts.authority else WorkAuthority.none()
    return WorkFacts(for_whom=facts.for_whom, authority=authority, level=min(facts.level, level))


@dataclass(frozen=True, slots=True)
class TodaysPath:
    """What the channel-type rules say of a work, which still decide (ADR-0368 §1:3).

    Attributes:
        person: The person it is for, as ``activation_person`` reads it.
        users_authority: Whether its input carries the user's authority, before any relay
            mark, as ``InputStanding`` reads it (ADR-0292 §5:5, ADR-0351 §6:1).
        established: Whether its place's kind establishes the user as its author
            (ADR-0292 §5:4).
    """

    person: str | None
    users_authority: bool
    established: bool


def todays_path(trigger: RecordedChannelTrigger) -> TodaysPath:
    """What today's path says of the work ``trigger`` started.

    Args:
        trigger: The work's recorded trigger.

    Returns:
        Today's reading.
    """
    established = establishes_the_user(_kind(trigger))
    return TodaysPath(
        person=activation_person(trigger),
        users_authority=established and parties_are_persons_own(trigger.parties),
        established=established,
    )


def disagreements(facts: WorkFacts, today: TodaysPath) -> tuple[str, ...]:
    """Where ``facts`` say other than today's path, by fact: ``for``, ``authority``, ``level``.

    - **for**: the person the facts say the work is for, where it is a person's, against
      the person today's path says.
    - **authority**: whether the facts carry the owner's authority alone, their senders'
      now, against whether today's path says the input carries the user's.
    - **level**: whether the facts' level is above none, against whether today's path
      establishes the user as the author (ADR-0368 §9:4).

    Args:
        facts: The facts recorded.
        today: What today's path says of the same work.

    Returns:
        The facts that disagree, in that order; empty where they all agree.
    """
    whom = facts.for_whom
    person = whom.id if whom.kind is WorkForKind.PERSON else None
    authority = facts.authority
    owners = (
        authority.kind is AuthorityKind.SENDERS
        and authority.persons == (OWNER_PERSON_ID,)
        and not authority.unidentified
    )
    differs: list[str] = []
    if person != today.person:
        differs.append("for")
    if owners != today.users_authority:
        differs.append("authority")
    if (facts.level > Sureness.NONE) != today.established:
        differs.append("level")
    return tuple(differs)


def log_facts(
    facts: WorkFacts, trigger: RecordedChannelTrigger, *, activation_id: str | None, at: str
) -> None:
    """Log the facts recorded on a work, and where they disagree with today's path.

    One ``work_facts_recorded`` entry each time the facts are recorded: when the work
    starts (``at="start"``) and when an input joins it (``at="join"``). ``agrees`` is
    whether every fact says what today's path says, and ``differs`` names those that do
    not, which is what the first deploy reads on the owner's hub (#3642). It carries
    codes and levels alone, never a person's id or an input's words (ADR-0275 §8), and
    changes no answer. Whose authority the facts carry is logged as ``whose`` and
    today's reading of it as ``today_users``: a key naming "auth" is masked by the log's
    redaction (``core.logging``), which would hide the one value the comparison is for.

    Args:
        facts: The facts recorded.
        trigger: The work's recorded trigger, which today's path reads.
        activation_id: The work's activation.
        at: When they were recorded: ``start`` or ``join``.
    """
    today = todays_path(trigger)
    differs = disagreements(facts, today)
    _log.info(
        "work_facts_recorded",
        activation_id=activation_id,
        at=at,
        agrees=not differs,
        differs=differs,
        for_whom=facts.for_whom.kind.value,
        whose=facts.authority.kind.value,
        unidentified=facts.authority.unidentified,
        level=facts.level.value,
        today_person=today.person is not None,
        today_users=today.users_authority,
        today_established=today.established,
    )


def _logged(
    facts: WorkFacts, trigger: RecordedChannelTrigger, *, activation_id: str | None, at: str
) -> None:
    """:func:`log_facts`, whose own fault is logged and never undoes the recording."""
    try:
        log_facts(facts, trigger, activation_id=activation_id, at=at)
    except Exception:  # the comparison is read beside the facts, never in their place
        _log.warning("work_facts_unlogged", at=at, reason="defect")


def record_started(
    trigger: RecordedChannelTrigger, *, activation_id: str | None
) -> WorkFacts | None:
    """The facts a work starts with, logged beside today's path; ``None`` on a defect.

    Nothing reads the facts yet (ADR-0368 §1:3), so recording them never stops an
    admission: a fault in deciding them is logged under a fixed event name and the work
    records none; a fault in logging them is logged apart and keeps them.

    Args:
        trigger: The work's recorded trigger.
        activation_id: The work's activation.

    Returns:
        The facts, or ``None`` where they could not be decided.
    """
    try:
        facts = started(trigger)
    except Exception:  # nothing reads the facts yet, so no fault stops a work
        _log.warning("work_facts_unrecorded", at="start", reason="defect")
        return None
    _logged(facts, trigger, activation_id=activation_id, at="start")
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


def record_joined(
    facts: WorkFacts,
    inputs: Sequence[JoinedInput],
    trigger: RecordedChannelTrigger,
    *,
    activation_id: str | None,
) -> tuple[JoinedInput, ...]:
    """``inputs``, each carrying the work's facts as they stand once it joined.

    ADR-0368 §2:4, each recording logged beside today's path. Whatever facts an input
    arrives with, another work's, are replaced or taken off (:func:`unrecorded`). Nothing
    reads the facts yet (§1:3), so recording them never stops a join: on a fault in
    deciding them, logged under a fixed event name, the inputs join recording none; a
    fault in logging them is logged apart and keeps them.

    Args:
        facts: The work's facts before the first of them joined.
        inputs: The inputs joining, in order.
        trigger: The work's recorded trigger, which today's path reads.
        activation_id: The work's activation.

    Returns:
        The inputs, each with this work's ``facts``, or with none.
    """
    try:
        recorded: list[tuple[JoinedInput, WorkFacts]] = []
        for one in inputs:
            facts = joined(facts, one)
            recorded.append((one.model_copy(update={"facts": facts}), facts))
    except Exception:  # nothing reads the facts yet, so no fault stops a join
        _log.warning("work_facts_unrecorded", at="join", reason="defect")
        return unrecorded(inputs)
    for _, held in recorded:
        _logged(held, trigger, activation_id=activation_id, at="join")
    return tuple(one for one, _ in recorded)
