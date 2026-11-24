"""What a channel kind declares, in code (ADR-0292, ADR-0323 §9).

ADR-0292 lists what every kind declares: its channels, its spokes and their
directions, whether it is pulled or pushes, which events are input, its push filter,
how it establishes authors, its places, its window, what counts as sent, its
description, its requirements and its audience. Until the Telegram line no kind was
declared in code: the hub chat's description is stated where the phases show it, and
what admission needs of every type — the parties of its input, and whether a person sends
on it by an account — is :mod:`ai_assistant.core.channel_validation`'s register.

**This module is the shape the first kind declared in code takes** (ADR-0323 §9:1,
ADR-0324's "the shape the first kind declared in code takes"): one frozen
:class:`ChannelKind`, a field per row of ADR-0292's table, each a value code reads
rather than prose. A kind declared here states what it is; the module that builds its
spoke reads the rows it acts on (its description, its window, its writer's rules), and
the rows admission reads stay in ``core``'s register, which :meth:`ChannelKind.
sent_by_a_person` and :meth:`ChannelKind.input_parties` read rather than restate,
so the two can never disagree. A pulled kind's declaration needs of this only its
description (ADR-0324), and the shape takes it with no spoke at all.

**Places** (ADR-0306 §6, ADR-0292 §10:8). A message's effect record names the place it
went into as ``<channel type>:<instance id>`` — ``conversation:<id>`` for the hub chat,
as it always was. :func:`place_of` spells it, and :func:`place_channel` reads it back.

**No place waits** (ADR-0349 §8:1). No kind declares that its places run one activation
at a time, or that an input waits for running work: every input on every place starts
its own activation once its place's start wait has passed, so the declaration ADR-0332
§2:3 gave the hub chat and the line is gone.

**Whether a kind can confirm delivery** (ADR-0350 §8:12). A kind declares whether it can
confirm, from its medium's own record, whether a message claimed into one of its places
was sent: :func:`confirms_delivery`'s register, keyed by channel type, so a kind not yet
declared in code (the hub chat's) declares it too, and which
:attr:`ChannelKind.confirms_delivery` reads. The hub chat's
conversations can: the hub hosts each one's transcript, a message is sent once that
transcript records it (ADR-0292 §7:4), and the transcript records with each of the
assistant's messages the effect record it was claimed under (§12:9). The line cannot: the
Bot API gives a bot no way to read its chat's history (ADR-0323 §10). Every other kind
declares that it cannot.

**What a connection is, and what the system can do with it** (ADR-0364 §3:3). Planning's
Connections section shows each connection by what its kind declares here, written once:
:data:`CONNECTION_KINDS`, keyed by channel type for a channel's places, and
:data:`ACCOUNT_KINDS` beside it, keyed by an account kind for a connected account. A kind
says what one of its connections is, what the system can do with it, sense it, look
things up in it or act in it, with its limits, whether its places take a text message,
the many-place connection it groups under, where it has one, and whether it reaches the
addresses a call names. :func:`takes_text` reads from a recorded place whether a text
message may go into it.

**What a briefing says of who sent an input** (ADR-0375 §4, §5). Understanding and planning
each render the stimulus's own ``said`` tag and the situation's sender line from the same
records, so both are composed here, once, and each briefing names the people in them its own
way: :func:`account_of` is a ``said`` tag's ``from``, the account or device the words came
by and its person; :func:`sender_line` is the sender line, by what each input came, how
strong a sign that is of who sent it, and whom the system counts it as, read from the
senders, parties and channel types the inputs record and the kinds' declarations alone
(§2:3). Whom the system counts as a person it serves is :func:`served`, read from ``core``'s
one declaration of whose words a sender's are (ADR-0351 §3:2), so the owner alone until a
later decision admits another (milestone 5), and a person identified but not served is never
named (§5's table).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Final

from pydantic import ValidationError

from ai_assistant.core.channel_validation import (
    APPROVALS,
    TASK_SCHEDULER,
    declared_input,
    most_sureness,
    origin_kind,
    sender_party,
    sent_by_a_person,
)
from ai_assistant.core.types import (
    ChannelIdentity,
    HolderKind,
    InputSender,
    Sureness,
    canonical_senders,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Sequence

    from ai_assistant.core.channel_validation import OriginKind
    from ai_assistant.core.types import ApprovalGiver, RecordedInputMessage, SupportHolder

__all__ = [
    "ACCOUNT_KINDS",
    "ACCOUNT_PREFIX",
    "CONNECTION_KINDS",
    "EMAIL_ACCOUNT_KIND",
    "FORECAST_ACCOUNT_KIND",
    "SEARCH_ACCOUNT_KIND",
    "SYSTEMS_OWN_MACHINE",
    "AccountConnection",
    "Audience",
    "ChannelKind",
    "ConnectionKind",
    "Direction",
    "Reach",
    "SentInput",
    "WindowSource",
    "account_kind",
    "account_of",
    "arrival",
    "confirms_delivery",
    "connection_kind",
    "place_channel",
    "place_of",
    "sender_line",
    "sender_unknown",
    "served",
    "takes_text",
]

#: What separates a place's channel type from its instance id.
_PLACE_SEPARATOR: Final = ":"

#: ADR-0350 §8:12: the channel types whose kind can confirm, from its medium's own record,
#: whether a message claimed into one of its places was sent: the hub chat's alone.
_CONFIRMS_DELIVERY: Final = frozenset({"conversation"})


class Reach(StrEnum):
    """How a kind's input reaches the assistant (ADR-0292 §6:5)."""

    PUSHES = "pushes"
    """The kind brings new input in as it arrives."""

    PULLED = "pulled"
    """The assistant asks the kind's sensor, and it answers (ADR-0324)."""

    BOTH = "both"
    """It pushes, and can also be pulled."""


class Direction(StrEnum):
    """Which ways a kind's spoke carries (ADR-0292 §2:11)."""

    IN = "in"
    OUT = "out"
    IN_AND_OUT = "in_and_out"


class WindowSource(StrEnum):
    """Where a kind's place window comes from (ADR-0292 §10:1-§10:2)."""

    MEDIUM = "medium"
    """The medium's own history, read by the sensor (ADR-0292 §10:1)."""

    EPISODES = "episodes"
    """The recent episodes on the channel and place, each linked to the activation it
    records: a kind whose sensor cannot read its medium's history (ADR-0323 §10:1)."""

    NONE = "none"
    """The kind's places have no window."""


class Audience(StrEnum):
    """Who a kind's places reach (ADR-0292 §9)."""

    PRIVATE = "private"
    """The user alone, declared by the user's act setting the channel up (§9:6)."""

    UNDECLARED = "undeclared"
    """No audience is declared, so nothing is assumed of one."""


@dataclass(frozen=True, slots=True)
class ChannelKind:
    """One channel kind's declaration, a field per row of ADR-0292's table (ADR-0323 §9).

    Attributes:
        channel_type: The kind's channel type, as a channel identity carries it.
        channels: How its channels come to exist (ADR-0292 §2:5-§2:6).
        direction: Which ways its spoke carries (§2:11).
        reach: Whether it pushes, is pulled, or both (§6:5).
        input: Which of its medium's events are input (§6:9).
        push_filter: Its push filter, or ``None`` where it has none (§6:11).
        authors: How it establishes authors (§5:4), in words; whether a person sends on it
            by an account at all is ``core``'s register, read by :meth:`sent_by_a_person`.
        places: What its places are and what keys them (§2:1, §10:8).
        window: Where its place window comes from (§10:1-§10:2).
        window_items: How many items its window holds, where it has one.
        sent: What counts as a message sent (§7:4).
        description: What planning is shown of the place (§8:1).
        text_only: Whether its writer sends text alone, a channel's rule held at the
            writer whatever a model produced (§8:3).
        message_limit: The spoke's limit on one message, where it has one, in the
            measure its medium counts (§8).
        audience: Who its places reach (§9).
        approval_giver: Who a yes on its places is, where a person sends on it
            (ADR-0321 §4:6, ADR-0323 §4:9); ``None`` where no yes on it approves.
    """

    channel_type: str
    channels: str
    direction: Direction
    reach: Reach
    input: str
    push_filter: str | None
    authors: str
    places: str
    window: WindowSource
    window_items: int | None
    sent: str
    description: str
    text_only: bool
    message_limit: int | None
    audience: Audience
    approval_giver: ApprovalGiver | None

    def __post_init__(self) -> None:
        """A kind no person sends on gives no approval, and a window holds an item.

        Raises:
            ValueError: If the kind names an approval giver though ``core``'s register
                says no person sends on it, or its window's size is not positive.
        """
        if self.approval_giver is not None and not self.sent_by_a_person:
            msg = "only a kind a person sends on gives an approval"
            raise ValueError(msg)
        if (self.window is WindowSource.NONE) != (self.window_items is None):
            msg = "a kind with a window says how many items it holds, and one without none"
            raise ValueError(msg)
        if self.window_items is not None and self.window_items < 1:
            msg = "a window holds at least one item"
            raise ValueError(msg)

    @property
    def sent_by_a_person(self) -> bool:
        """Whether a person sends on the kind by an account (ADR-0366 §4:1)."""
        return sent_by_a_person(self.channel_type)

    @property
    def origin(self) -> OriginKind | None:
        """What understanding is told of one of its origins (ADR-0353 §6:3, §7:5).

        Beside :attr:`description`, which is planning's, and read from ``core``'s
        register, which keys it by channel type so the hub chat, declared in no
        ``ChannelKind``, declares it too.
        """
        return origin_kind(self.channel_type)

    @property
    def confirms_delivery(self) -> bool:
        """Whether the kind can confirm a claimed message's delivery (ADR-0350 §8:12)."""
        return confirms_delivery(self.channel_type)

    def input_parties(
        self,
        channel: ChannelIdentity,
        messages: Sequence[RecordedInputMessage] = (),
        *,
        carries_outside_mark: bool = False,
    ) -> tuple[tuple[SupportHolder, ...], tuple[RecordedInputMessage, ...]]:
        """The parties the kind declares for one input on ``channel`` (ADR-0351 §3:1).

        Per input, as admission records them: each message with the party the kind
        declares for it, a forward's its original sender, claimed (§2:7), and the
        input's parties their distinct parties (§2:6).

        Raises:
            ValueError: If ``channel`` is not of this kind, or the register declares no
                parties for the input.
        """
        if channel.channel_type != self.channel_type:
            msg = "a kind declares the parties of its own channels' input alone"
            raise ValueError(msg)
        return declared_input(channel, messages, carries_outside_mark=carries_outside_mark)


def confirms_delivery(channel_type: str) -> bool:
    """Whether the kind of ``channel_type`` can confirm a claimed message's delivery.

    ADR-0350 §8:11-§8:12: the hub chat's conversations can, from the transcript, which
    records each assistant message with the effect record it was claimed under; the line
    cannot, and every other kind declares that it cannot.
    """
    return channel_type in _CONFIRMS_DELIVERY


def place_channel(place: str) -> ChannelIdentity | None:
    """The channel a recorded place names, :func:`place_of`'s inverse, or ``None``."""
    channel_type, separator, instance = place.partition(_PLACE_SEPARATOR)
    if not (separator and channel_type and instance):
        return None
    try:
        return ChannelIdentity(channel_type=channel_type, instance_id=instance)
    except ValidationError:
        return None


def place_of(channel: ChannelIdentity) -> str:
    """The place a message on ``channel`` goes into, as its effect record names it.

    ``<channel type>:<instance id>`` (ADR-0306 §6): the conversation, by its id, for the
    hub chat, and the line's chat, by the line's instance, for Telegram.
    """
    return f"{channel.channel_type}{_PLACE_SEPARATOR}{channel.instance_id}"


# --- what a connection is (ADR-0364 §3:3) ---------------------------------------------


@dataclass(frozen=True, slots=True)
class ConnectionKind:
    """What a connection of one kind is, and what the system can do with it (§3:3).

    Attributes:
        is_a: What one of its connections is, in planning's words.
        can: What the system can do with it, sense it, look things up in it or act in it,
            with its limits.
        takes_text: Whether a text message may go into it.
        group: The many-place connection its places are grouped under, where it is one,
            shown for reading only and taking no label (§3:2); ``None`` for a connection
            with one place.
        reaches_named: Whether it reaches the addresses a call names in place of a person,
            as an email account does (§4:3).
        reaches_people: Whether it reaches the people it is for, the owner alone today
            (ADR-0361 §7:4).
    """

    is_a: str
    can: str
    takes_text: bool = False
    group: str | None = None
    reaches_named: bool = False
    reaches_people: bool = True


#: Each channel kind's connections, by channel type (ADR-0364 §3:3): the system's own
#: chat's conversations, the line's chat, the schedule and the approvals, each in the
#: system's words (ADR-0375 §7).
CONNECTION_KINDS: Final[dict[str, ConnectionKind]] = {
    "conversation": ConnectionKind(
        is_a="a conversation in the system's own chat",
        can="sense it, and act in it: it takes text messages",
        takes_text=True,
        group="The system's own chat",
    ),
    "telegram": ConnectionKind(
        is_a="the messaging line's chat, on Telegram",
        can=(
            "sense it, and act in it: it takes text messages, in plain text: formatting"
            " such as Markdown is not rendered"
        ),
        takes_text=True,
    ),
    TASK_SCHEDULER: ConnectionKind(
        is_a="the schedule, where scheduled tasks fall due and start work",
        can="sense it, look things up in it and act in it: it takes no message",
        reaches_people=False,
    ),
    APPROVALS: ConnectionKind(
        is_a="the approvals, where a request for approval waits on a card for its answer",
        can="sense it, and act in it: it takes no message",
    ),
}

#: What an account connection's id starts with: ``account:`` and its reference.
ACCOUNT_PREFIX: Final = "account:"

#: The account kinds the composition root registers (ADR-0364 §3:6).
EMAIL_ACCOUNT_KIND: Final = "email"
SEARCH_ACCOUNT_KIND: Final = "search"
FORECAST_ACCOUNT_KIND: Final = "forecast"

#: Each account kind's connections, by kind, beside the channel kinds (ADR-0364 §3:3,
#: §3:6): what the composition root registers, each with its kind.
ACCOUNT_KINDS: Final[dict[str, ConnectionKind]] = {
    EMAIL_ACCOUNT_KIND: ConnectionKind(
        is_a="an email account",
        can="act in it: it sends email, and takes no text message",
        reaches_named=True,
        reaches_people=False,
    ),
    SEARCH_ACCOUNT_KIND: ConnectionKind(
        is_a="the search account, which searches the web",
        can="look things up in it: it takes no message",
        reaches_people=False,
    ),
    FORECAST_ACCOUNT_KIND: ConnectionKind(
        is_a="the forecast provider, which reads the weather forecast",
        can="look things up in it: it takes no message",
        reaches_people=False,
    ),
}


@dataclass(frozen=True, slots=True)
class AccountConnection:
    """One account connection the composition root registers, with its kind (§3:6).

    Orchestration's own value: no ``core`` type gains a kind for an account, and
    ``ConnectedAccount`` is unchanged (ADR-0151 §18).

    Attributes:
        reference: The connection record's reference, as ``Settings`` names it, which
            its state is read by and which no entry shows (§3:4).
        kind: Its account kind, one of :data:`ACCOUNT_KINDS`.
    """

    reference: str
    kind: str

    @property
    def place(self) -> str:
        """What its ``L`` label names: ``account:`` and its reference."""
        return f"{ACCOUNT_PREFIX}{self.reference}"


def connection_kind(place: str) -> ConnectionKind | None:
    """What the connection ``place`` names is, by its channel type or account kind.

    A channel no kind here declares, such as one an informational event comes from, is
    still a connection, since every origin is one (§3:2): the system senses it and it
    takes no message. ``None`` where ``place`` names no channel.
    """
    channel = place_channel(place)
    if channel is None:
        return None
    declared = CONNECTION_KINDS.get(channel.channel_type)
    if declared is not None:
        return declared
    return ConnectionKind(
        is_a=f"a place of the {channel.channel_type} channel",
        can="sense it: it takes no message",
        reaches_people=False,
    )


def account_kind(kind: str) -> ConnectionKind | None:
    """What an account connection of ``kind`` is, or ``None`` where none is declared."""
    return ACCOUNT_KINDS.get(kind)


def takes_text(place: str) -> bool:
    """Whether a text message may go into the connection ``place`` names (ADR-0364 §9:2)."""
    kind = connection_kind(place)
    return kind is not None and kind.takes_text


# --- who sent an input, as a briefing says it (ADR-0375 §4, §5) -----------------------

#: The ``from`` of words written on the system's own machine where the links could not be
#: read (ADR-0375 §4:1, ADR-0374 §3:2): no link is named, since none was read.
SYSTEMS_OWN_MACHINE: Final = "the system's own machine"

#: The account a message came by where its kind declares no noun for one.
_AN_ACCOUNT: Final = "an account"

#: Who sent a message whose reader found no sender: no link, at none (ADR-0366 §5:6).
_NO_SENDER: Final = InputSender(person=None, level=Sureness.NONE)


@dataclass(frozen=True, slots=True)
class SentInput:
    """One input a stimulus section renders, as the sender line reads it (ADR-0375 §5:2).

    Attributes:
        channel_type: The channel type it came in on, whose kind declares the noun for the
            account it came by and its most sureness; ``None`` where none is recorded.
        senders: Who sent it, as recorded (ADR-0368 §2:6); none for an input no person
            sent (ADR-0368 §3:5).
        messages: Its recorded messages, each with its own party and sender; none for an
            input that records none.
        parties: Its recorded parties, which an input that records no messages is
            counted by; ``None`` where they are unknown.
        count: How many messages the stimulus section renders of it, for an input that
            records none.
    """

    channel_type: str | None
    senders: tuple[InputSender, ...] = ()
    messages: tuple[RecordedInputMessage, ...] = ()
    parties: tuple[SupportHolder, ...] | None = None
    count: int = 1


@dataclass(slots=True)
class _Sent:
    """What one sender sent of the inputs a stimulus section renders."""

    channel_type: str | None
    count: int = 0
    forwards: int = 0
    own: list[SupportHolder] = field(default_factory=list)


def served(person_id: str | None) -> bool:
    """Whether the system counts ``person_id`` as a person it serves (ADR-0375 §5:5).

    Read from ``core``'s one declaration of whose words an identified sender's are
    (:func:`~ai_assistant.core.channel_validation.sender_party`, ADR-0351 §3:2): a person
    whose identified sender's words it counts as that person's. That is the owner alone
    until a later decision admits another (ADR-0366 §1:3, milestone 5); an identity a link
    names that no decision admits is not served, and is never named (§5's table).

    Args:
        person_id: A person's id, or ``None``.

    Returns:
        Whether that person is one the system serves.
    """
    if person_id is None:
        return False
    party = sender_party(InputSender(person=person_id, level=Sureness.WEAK))
    return party.kind is HolderKind.PERSON


def sender_unknown(senders: Iterable[InputSender]) -> bool:
    """Whether any of ``senders`` is one the system counts as an unknown sender (§6:2).

    No link establishes it as a person the system serves: no person, a link at none, or
    a person the system knows but does not serve.
    """
    return any(not (one.identified and served(one.person)) for one in senders)


def _noun(channel_type: str | None) -> str:
    """The account a person sends a message by on ``channel_type``'s kind (ADR-0375 §5)."""
    kind = None if channel_type is None else origin_kind(channel_type)
    return kind.noun if kind is not None and kind.noun else _AN_ACCOUNT


def account_of(channel_type: str | None, sender: InputSender | None, person: str) -> str | None:
    """A ``said`` tag's ``from``: the account the words came by and its person (§4:1).

    ``a device linked to Maren``, ``the Telegram account linked to Maren``, or the
    system's own machine where the links could not be read and the sender was decided as
    ADR-0374 §3:2 decides it, naming no link.

    Args:
        channel_type: The channel type the words came in on.
        sender: Who sent them, as recorded; ``None`` where none is recorded.
        person: The sender's person, as the briefing names a person in a tag.

    Returns:
        The ``from``; ``None`` where no sender naming a person is recorded, so the caller
        names the person alone.
    """
    if sender is None or sender.person is None:
        return None
    if sender.links_unread:
        return SYSTEMS_OWN_MACHINE
    return f"{_noun(channel_type)} linked to {person}"


def _grouped(inputs: Sequence[SentInput]) -> list[tuple[InputSender, _Sent]]:
    """Each distinct sender of ``inputs``, in ``canonical_senders``' order, with what it sent.

    A sender is distinct by its person, level and whether the links were read, and by the
    kind it came by, so no part of the line claims of one input what only another's
    record shows (ADR-0375 §2:1, §5:2): a person's Telegram message and a message
    written on the system's own machine are two parts. Senders of one person stand in
    the order they were first taken in.

    A recorded message is its own sender's, or its input's one sender's where it records
    none; an input that records no messages is each of its senders', counted by its
    recorded party where it has one sender, and as ``core`` declares a sender's words
    otherwise (ADR-0351 §3:2).
    """
    sent: dict[tuple[InputSender, str | None], _Sent] = {}

    def add(
        sender: InputSender, channel_type: str | None, party: SupportHolder | None, *, count: int
    ) -> None:
        held = sent.setdefault((sender, channel_type), _Sent(channel_type=channel_type))
        held.count += count
        if party is None or party.kind not in {HolderKind.PERSON, HolderKind.UNKNOWN}:
            # A forward's party is its original sender, claimed (ADR-0351 §2:7).
            held.forwards += count
        else:
            held.own.append(party)

    for one in inputs:
        sole = one.senders[0] if len(one.senders) == 1 else None
        if one.messages:
            for message in one.messages:
                party = message.party
                if message.forwarded_from is not None:
                    party = None
                elif party is None:
                    party = sender_party(message.sender or sole)
                add(message.sender or sole or _NO_SENDER, one.channel_type, party, count=1)
            continue
        recorded = one.parties if one.parties is not None and len(one.parties) == 1 else None
        for sender in one.senders:
            party = recorded[0] if recorded is not None and sole else sender_party(sender)
            add(sender, one.channel_type, party, count=one.count if sole else 1)
    # ADR-0375 §5:2: in ``canonical_senders``' order, which orders by person alone.
    order = {one.person: at for at, one in enumerate(canonical_senders(key[0] for key in sent))}
    keys = sorted(sent, key=lambda key: order[key[0].person])
    return [(key[0], sent[key]) for key in keys]


def _whose(
    sent: _Sent, named: Callable[[str], str], them: str, theirs: str, *, still: bool
) -> str | None:
    """Whom the system counts one sender's own words as, by their parties (§5:5)."""
    if not sent.own:
        return None
    people = {one.identifier for one in sent.own if one.kind is HolderKind.PERSON}
    if len(people) == 1 and all(one.kind is HolderKind.PERSON for one in sent.own):
        (person,) = people
        if person is not None:
            again = "still " if still else ""
            return f"the system {again}counts {them} as {named(person)}'s"
    return f"the system counts {them} as an unknown sender's, whatever {theirs} text says"


def _counted(
    sender: InputSender, sent: _Sent, named: Callable[[str], str], them: str, *, still: bool
) -> str:
    """The sender line's last part for one sender: whom the system counts it as (§5:5)."""
    theirs = "their" if them == "them" else "its"
    own = _whose(sent, named, them, theirs, still=still)
    if not sent.forwards:
        return f"{_upper(own or '')}."
    by = named(sender.person) if sender.person is not None and sender.identified else None
    if by is not None and not served(sender.person):
        by = None
    not_theirs = (
        f"The forwarded words are not {by}'s"
        if by
        else ("The forwarded words are not the forwarder's")
    )
    if own is None:
        return f"{not_theirs}."
    return f"{not_theirs}; {own.replace(f'counts {them}', 'counts the rest', 1)}."


def _part(
    sender: InputSender, sent: _Sent, named: Callable[[str], str], *, subject: str, plural: bool
) -> str:
    """One sender's part of the sender line: by what, how strong a sign, whom (§5:2-§5:5)."""
    them = "them" if plural else "it"
    verb = "forwarded" if not sent.own and sent.forwards else "sent"
    noun = _noun(sent.channel_type)
    unknown = f"so who or what {verb} {them} is unknown"
    if sender.links_unread:
        return _unread(sender, sent, named, subject=subject, plural=plural, unknown=unknown)
    counted = _counted(sender, sent, named, them, still=False)
    if sender.person is None:
        return f"{subject} came by {noun} the system cannot tie to anyone, {unknown}. {counted}"
    if not served(sender.person):
        return (
            f"{subject} came by {noun} linked to a person the system knows but does not serve. "
            f"{counted}"
        )
    person = named(sender.person)
    most = Sureness.NONE if sent.channel_type is None else most_sureness(sent.channel_type)
    lowered = sender.level < most
    if sender.level is Sureness.NONE:
        marked = " that is marked as not to be relied on" if lowered else ""
        return f"{subject} came by {noun} linked to {person}{marked}, {unknown}. {counted}"
    # §5:3: strong, which no kind reaches, takes normal's words until it has its own.
    sign = "a weak sign" if sender.level is Sureness.WEAK else "a strong sign"
    marked = " that is marked as less reliable" if lowered else ""
    counted = _counted(sender, sent, named, them, still=lowered)
    return (
        f"{subject} came by {noun} linked to {person}{marked}, which is {sign} that {person} "
        f"{verb} {them}. {counted}"
    )


def _unread(  # noqa: PLR0913 — the sender, what it sent, how people are named, and the three words its sentence takes
    sender: InputSender,
    sent: _Sent,
    named: Callable[[str], str],
    *,
    subject: str,
    plural: bool,
    unknown: str,
) -> str:
    """A part for a sender set because the links could not be read (ADR-0374 §2:2, §3:2).

    No link is named, since none was read; one written on the system's own machine is
    said to be, and whom the system counts it as.
    """
    them = "them" if plural else "it"
    counted = _counted(sender, sent, named, them, still=False)
    unread = f"the system could not read its record of linked accounts when {subject} arrived"
    if sender.person is None:
        return f"{unread}, {unknown}. {counted}"
    machine = f"{_upper(subject)} {'were' if plural else 'was'} written on the system's own machine"
    people = {one.identifier for one in sent.own if one.kind is HolderKind.PERSON}
    if not sent.forwards and people == {sender.person}:
        return f"{unread}. {machine}, which the system counts as {named(sender.person)}'s."
    return f"{unread}. {machine}. {counted}"


def _upper(words: str) -> str:
    """``words`` with its first letter capitalised, to begin a sentence."""
    return words[:1].upper() + words[1:]


def sender_line(
    inputs: Sequence[SentInput],
    *,
    named: Callable[[str], str],
    origin: str,
    taken_in: bool = False,
) -> str:
    """The situation's sender line (ADR-0375 §5), for the inputs a stimulus section renders.

    By what each input came, how strong a sign that is of who sent it and whom the system
    counts it as, and nothing else: one part for each distinct sender, in
    ``canonical_senders``' order (§5:2). A link below its kind's declared most is said to
    be marked as less reliable, or as not to be relied on at none, and never by whom
    (§5:4). Whom it is counted as is read from the recorded parties (§5:5). An input no
    person sent says so and names its origin (§5:6). No part says that a person typed,
    wrote or sent anything, only how strong a sign the account is (§2:1).

    Args:
        inputs: The inputs the stimulus section renders: the trigger's, then each joined
            one's.
        named: A person the system serves, named in words, as the lines between the tags
            name them.
        origin: The trigger's origin, by its name, for an input no person sent.
        taken_in: Whether the inputs were taken in after the work was briefed, as
            planning's news says of them (ADR-0375 §2:2): the line says so.

    Returns:
        The line, with its leading ``- ``.
    """
    groups = _grouped(inputs)
    of = " of what was taken in" if taken_in else ""
    if not groups:
        return f"- The sender{of}: {_unrecorded(inputs, named, origin)}"
    several = len(groups) > 1
    parts: list[str] = []
    for sender, sent in groups:
        forwards_only = not sent.own and sent.forwards > 0
        if several:
            subject, plural = "some of the messages", True
        else:
            plural = sent.count > 1
            noun = "forward" if forwards_only else "message"
            subject = f"the {noun}s" if plural else f"the {noun}"
        part = _part(sender, sent, named, subject=subject, plural=plural)
        parts.append(part if not parts else _upper(part))
    heading = "The senders" if several else "The sender"
    return f"- {heading}{of}: {' '.join(parts)}"


def _unrecorded(inputs: Sequence[SentInput], named: Callable[[str], str], origin: str) -> str:
    """The sender line where no input records a sender (§5:6).

    An input of a kind no person sends on, whose parties are recorded, says that no person
    sent it and where it came from; any other says that nothing of who sent it is
    recorded, and whom the system counts it as where its parties say.
    """
    if all(
        one.channel_type is not None
        and not sent_by_a_person(one.channel_type)
        and one.parties is not None
        for one in inputs
    ):
        return f"no person sent it; it came from {origin}."
    parties = [party for one in inputs for party in (one.parties or ())]
    people = {one.identifier for one in parties if one.kind is HolderKind.PERSON}
    recorded = "the system recorded nothing of how the message came."
    if parties and len(people) == 1 and all(one.kind is HolderKind.PERSON for one in parties):
        (person,) = people
        if person is not None:
            return f"{recorded} The system counts it as {named(person)}'s."
    if parties and all(one.kind is HolderKind.UNKNOWN for one in parties):
        return f"{recorded} The system counts it as an unknown sender's, whatever its text says."
    return recorded


#: How many messages the framing sentence spells as a word (ADR-0353 §7:1).
_COUNTS: Final = ("two", "three", "four", "five", "six", "seven", "eight", "nine", "ten")


def _how_many(number: int) -> str:
    """How many messages, as the framing sentence says it: ``three``, or ``12``."""
    return _COUNTS[number - 2] if 2 <= number <= len(_COUNTS) + 1 else str(number)  # noqa: PLR2004 — "two" is the first spelled


def arrival(kind: OriginKind, person: str, *, count: int, forwards: int) -> tuple[str, str]:
    """A framing sentence's ``{what}`` and ``{content}`` for messages a person sends.

    ADR-0375 §3:1: where the messages arrived, by the origin's description, and for a
    forward that it was forwarded, naming no sender and no act: ``a message that arrived
    in Maren's private chat with the system``, ``three messages that arrived in …``, ``a
    message forwarded into …``.

    Args:
        kind: The origin's kind, a kind a person sends on.
        person: The person whose place it is, named as the lines between the tags name
            them, already escaped.
        count: How many messages the input holds.
        forwards: How many of them are forwards.

    Returns:
        ``{what}`` and ``{content}``.
    """
    place = kind.described.replace("{person}", person)
    several = count > 1
    many = _how_many(count)
    if count and forwards == count:
        what = (
            f"{many} messages forwarded into {place}"
            if several
            else (f"a message forwarded into {place}")
        )
    else:
        what = (
            f"{many} messages that arrived in {place}"
            if several
            else (f"a message that arrived in {place}")
        )
        if forwards:
            some = "one" if forwards == 1 else _how_many(forwards)
            what += f", {some} of them forwarded"
    return what, "these messages" if several else kind.content
