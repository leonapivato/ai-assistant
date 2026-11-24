"""Pure validation of the channel contract values (ADR-0274 §§3-4).

No dispatch, collaborators, configuration, or authority lives here. Both local
and wire entry points apply the same closed set of representable combinations,
and read the same declaration of whose words each channel type's input carries, its
**parties** (ADR-0351 §3:1, in place of ADR-0284 §2:2's origin), and of which channel
types a person sends on by an account, whose link names the sender (ADR-0366 §4:1).

**No conversational combination is on the surface.** A typed message is written
into a conversation as an act in the medium (ADR-0293 §11), and spoken
conversation retired at the cutover (ADR-0313 §3:2), so ``receive`` admits an
event alone (§4:1).

**Nor is the Telegram line's** (ADR-0323 §2:2, §4:1). Its input is admitted by its
reader in the hub alone, which finds each message's sender from the link the Telegram
account that sent it holds (ADR-0366 §4:1): a ``telegram`` input handed to ``receive``
would name a sender no reader found, so the dispatch table refuses it as it refuses
every type it does not list.

**Nor is the Task Scheduler's** (ADR-0350 §2:7, §7). It is a built-in channel whose
sensor pushes each scheduled task's occurrence in the hub alone; the register declares
its parties per input, the assistant's statement naming the task's instruction, with
unknown added for a task carrying the outside-content mark (ADR-0351 §3:6), and no
person sends on it.

**Nor is the Approvals channel's** (ADR-0361 §3:1, §3:6). It is a built-in channel whose
sensor pushes each approval request answered or expired in the hub alone; no person
sends on it, and the register declares its inputs' parties empty:
an approval's input carries no one's words (ADR-0351 §2:4, ADR-0361 §6:1).

**The parties each kind declares** (ADR-0351 §3's table), per input, set by code at
admission from the declaration and the record the sensor brings (§2:8). A message a
person sends by an account, on the hub chat or the line, carries its sender's words:
the owner's where a link establishes the owner as its sender, and unknown otherwise,
the one person a party names being the owner (§3:2, as ADR-0366 §4:1 and ADR-0368 §9:4
decide the sender; ADR-0351 §3's row for a speaker no kind establishes). A forward
carries its original sender's, claimed (§2:7), and an input of several messages the
distinct parties of its messages (§2:6);
an informational event's carries its connected source's, established, named by the
channel's identity (§3:5); and the Task Scheduler's the assistant's statement (§3:6).
No channel type decides whose words a message is: a kind declares only whether a person
sends on it by an account (:func:`sent_by_a_person`), and the sender its reader found
names the party. A kind not built, a mail channel or a spoke that tells who is talking,
declares nothing here until it is, and a channel type with no declaration is refused.

**What the models are told of an origin** (ADR-0353 §6:3, §7:5, ADR-0375 §7:2). Beside
the parties, each kind declares how the models name one of its origins, what the origin is
and who is there, in the system's words, and how a stimulus from it is framed: the
account a person sends one by, the preposition its origin takes, and what its content is
called (:class:`OriginKind`). It is keyed by channel type, as the parties are, so the hub chat,
which no ``ChannelKind`` declares in code, declares it here too, and a declared kind reads
it rather than restating it. A kind with no row is rendered with the fallback ADR-0353
§6:3 and §7:5 give it.

**The most sureness each kind can give** (ADR-0366 §5:2), declared beside how it
establishes authors, and a link's level read from it (§5:3, :func:`link_level`). Who sent
an input and at what level is its reader's finding from the link its account holds
(ADR-0368 §2:6), and decides (ADR-0366 §4:1): no channel type here says who sent one.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

from pydantic import TypeAdapter, ValidationError

from ai_assistant.core.types import (
    OWNER_PERSON_ID,
    ChannelIdentity,
    ChannelInput,
    ClaimedAuthor,
    InputSender,
    NewConversation,
    RecordedInputMessage,
    ReplyCapability,
    StatementPart,
    SupportHolder,
    Sureness,
    TextChannelPayload,
    canonical_parties,
    forward_party,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from ai_assistant.core.types import ChannelTarget, Link

_REPLY = TypeAdapter[ReplyCapability | None](ReplyCapability | None)

#: ADR-0350 §2:1, §2:8: the channel type of the **Task Scheduler**, the built-in channel
#: whose one place, the schedule, holds the scheduled tasks every spawn writes. No person
#: sends on it (§2:7), so it is absent from :data:`_SENT_BY_A_PERSON`, and nothing a
#: caller hands ``receive`` is one: its sensor pushes each occurrence in the hub alone
#: (§7).
TASK_SCHEDULER: Final = "task_scheduler"

#: ADR-0361 §3:1, §3:6: the channel type of **Approvals**, the built-in channel whose one
#: place, the approvals, holds the approval requests ``request_approval`` writes. No
#: person sends on it (§3:6), so it is absent from :data:`_SENT_BY_A_PERSON`, and its
#: inputs' parties are empty (ADR-0351 §2:4): an
#: approval's input is structured and carries no one's words (§6:1-§6:2). Nothing a caller
#: hands ``receive`` is one: its sensor pushes each outcome in the hub alone (§3:4).
APPROVALS: Final = "approvals"

#: ADR-0366 §4:1, ADR-0351 §3:1: the channel types a person sends on by an account, whose
#: every message its sender wrote carries its sender's words, as its reader found the
#: sender from the link the account holds: the hub chat, whose accounts are the devices
#: it is written from, and the line, whose account is the Telegram account that sent the
#: message. Membership says that a person may send there, never who: a kind absent from
#: it declares no person's words.
_SENT_BY_A_PERSON: Final = frozenset({"conversation", "telegram"})

#: ADR-0351 §2:7, §3:1 (ADR-0323 §4:11): the channel types that take forwards in, each
#: forward's party its original sender, claimed. A kind absent from it takes in none.
_TAKES_FORWARDS: Final = frozenset({"telegram"})

#: ADR-0351 §3:5: the channel types whose input is a connected source's report, its
#: party that source, established, named by the channel's identity.
_A_SOURCES_REPORT: Final = frozenset({"informational_event"})

#: ADR-0366 §5:2: the most sureness each kind can give, declared beside how it
#: establishes authors. The hub chat's accounts are the devices it is written from, each
#: admitted by the owner and behind its own login, and the line's is a messaging account
#: behind Telegram's: both give normal (§5's table). No kind gives weak or strong yet:
#: no mail kind is declared until a decision rules how that channel establishes a sender
#: (ADR-0368 §9:8), and strong waits on combining signals (ADR-0366 §5:4). A kind absent
#: from it gives none.
_MOST_SURENESS: Final[Mapping[str, Sureness]] = MappingProxyType(
    {"conversation": Sureness.NORMAL, "telegram": Sureness.NORMAL}
)


def snapshot(
    supplied: ChannelInput, reply: ReplyCapability | None
) -> tuple[ChannelInput, ReplyCapability | None]:
    """Copy and validate nested caller data before processing can suspend.

    Invalid nested recordings leave no rejected input or exception chain in the
    refusal (ADR-0200 §9). Revalidation starts from dictionaries so even nested
    frozen models containing caller-mutated values are checked and detached.

    Args:
        supplied: The channel input as the caller handed it.
        reply: The reply capability the caller offered, or ``None``.

    Returns:
        The detached input and reply capability.

    Raises:
        ValueError: If either value is malformed, or the combination is not one
            this entry admits.
    """
    accepted: ChannelInput | None = None
    accepted_reply: ReplyCapability | None = None
    try:
        checked = ChannelInput.model_validate(supplied.model_dump(mode="python", warnings=False))
        accepted_reply = _REPLY.validate_python(
            None if reply is None else reply.model_dump(mode="python", warnings=False)
        )
        accepted = checked
    except ValidationError, ValueError:
        pass
    if accepted is None:
        msg = "invalid channel input or reply declaration"
        raise ValueError(msg) from None
    validate_combination(accepted, accepted_reply)
    return accepted, accepted_reply


def validate_combination(supplied: ChannelInput, reply: ReplyCapability | None) -> None:
    """Refuse every combination outside the dispatch table this entry admits.

    ADR-0274 §4's table, less its conversational rows: ADR-0293 §11 takes the text
    one off the surface and ADR-0313 §3:2 retires the spoken one, so an
    informational event with text and no reply is the one combination admitted
    (§4:1). ``converse``'s own typed input left with ``converse`` (ADR-0309 §5:1).
    A ``telegram`` input is not in it: the line's reader admits it in the hub, and
    nothing a caller hands this entry is one (ADR-0323 §4:1, §4:3).

    Args:
        supplied: The detached channel input.
        reply: The detached reply capability, or ``None``.

    Raises:
        ValueError: If the combination is not in the table.
    """
    target = supplied.target
    kind = "conversation" if isinstance(target, NewConversation) else target.channel_type
    text = isinstance(supplied.payload, TextChannelPayload)
    if not (kind == "informational_event" and text and reply is None):
        msg = "unsupported channel input and reply combination"
        raise ValueError(msg)


def _kind(target: ChannelTarget) -> str:
    """The channel type ``target`` declares for: a new conversation is the hub chat's."""
    return "conversation" if isinstance(target, NewConversation) else target.channel_type


def sender_party(sender: InputSender | None) -> SupportHolder:
    """The party of a message a person wrote and sent, from who sent it (ADR-0351 §3:2).

    The owner, where a link establishes the owner as its sender (ADR-0366 §4:1,
    ADR-0368 §9:4); unknown otherwise, as for a speaker no kind establishes (ADR-0351
    §3's table): an account no link ties, a link lowered to none, the links unread off
    the hub's own machine (ADR-0374 §2:2), or a message whose reader found no sender. A
    kind establishes a person as a party only where it establishes that person as an
    author, and until a decision on identified people adds others, the one person a
    party names is the owner (§3:2): an identity a link names that no decision admits
    (ADR-0366 §1:3) is no party's person, so its words are held as nobody identified's.
    No channel type stands in for any of it.

    Args:
        sender: Who sent the message, as its reader found it, or ``None`` where it found
            none.

    Returns:
        The message's party.
    """
    if sender is not None and sender.identified and sender.person == OWNER_PERSON_ID:
        return SupportHolder.person(OWNER_PERSON_ID)
    return SupportHolder.unknown()


def message_party(
    channel_type: str, forwarded_from: ClaimedAuthor | None, sender: InputSender | None
) -> SupportHolder:
    """The party a kind declares for one message its input takes in (ADR-0351 §2:6, §3:1).

    A message its sender wrote, on a kind a person sends on by an account, is its
    sender's words (:func:`sender_party`, §3:2); a forward, on a kind that takes forwards
    in, is its original sender's, claimed, or unknown where the medium names none
    (§2:7). Set from who sent the message, never from what it says (§2:9), and never
    from the channel type alone.

    Args:
        channel_type: The channel type the message came in on.
        forwarded_from: The forward's original sender, or ``None`` for a message its
            sender wrote.
        sender: Who sent it, as its reader found it from the account it arrived by, or
            ``None`` where it found none.

    Returns:
        The message's party.

    Raises:
        ValueError: If the kind declares no party for such a message: it takes in no
            forward, or no person sends on it. Admission refuses it.
    """
    if forwarded_from is not None:
        if channel_type not in _TAKES_FORWARDS:
            msg = "the channel type takes in no forward (ADR-0351 §3:1)"
            raise ValueError(msg)
        return forward_party(forwarded_from)
    if channel_type not in _SENT_BY_A_PERSON:
        msg = "the channel type declares no party for a message it takes in (ADR-0351 §3:1)"
        raise ValueError(msg)
    return sender_party(sender)


def _parties(
    target: ChannelTarget,
    carried: Sequence[SupportHolder],
    senders: Sequence[InputSender],
    *,
    carries_outside_mark: bool,
) -> tuple[SupportHolder, ...]:
    """The parties ``target``'s kind declares for one input, its messages' ``carried``."""
    kind = _kind(target)
    if carries_outside_mark and (kind != TASK_SCHEDULER or carried):
        msg = "the channel type declares no parties for an input carrying the mark"
        raise ValueError(msg)
    if carried:
        # §2:6: an input of messages carries exactly their distinct parties.
        return canonical_parties(carried)
    if kind in _SENT_BY_A_PERSON:
        # §3:2: its senders' words, each as :func:`sender_party` names it, and unknown
        # where its reader found no sender at all.
        return canonical_parties(sender_party(one) for one in senders or (None,))
    if kind in _A_SOURCES_REPORT and isinstance(target, ChannelIdentity):
        # §3:5: the connected source instance it came from, established.
        identity = f"{target.channel_type}:{target.instance_id}"
        return (SupportHolder.source(identity, claimed=False),)
    if kind == TASK_SCHEDULER:
        # §3:6: the assistant's statement, with unknown where the task is marked.
        statement = SupportHolder.statement(StatementPart.SCHEDULED_INSTRUCTION)
        if carries_outside_mark:
            return canonical_parties((statement, SupportHolder.unknown()))
        return (statement,)
    if kind == APPROVALS:
        # ADR-0361 §3:6, §6:1: empty, for an input carrying no one's words.
        return ()
    msg = "the channel type declares no parties for its input (ADR-0351 §3:1)"
    raise ValueError(msg)


def declared_input(
    target: ChannelTarget,
    messages: Sequence[RecordedInputMessage] = (),
    *,
    senders: Sequence[InputSender] = (),
    carries_outside_mark: bool = False,
) -> tuple[tuple[SupportHolder, ...], tuple[RecordedInputMessage, ...]]:
    """The parties a kind declares for one input, and its messages each with its party.

    ADR-0351 §3:1, which admission records on the trigger and fixes on the episode
    (§2:8). Each message is given the party :func:`message_party` declares for it from
    the sender it arrived with, whatever party it arrived with, and the input's parties
    are its messages' distinct parties (§2:6), or, for an input that records none, the
    set its kind declares: on the hub chat, its ``senders``' words (:func:`sender_party`),
    unknown where none is named; the source an informational event names; the
    assistant's statement on the Task Scheduler, with unknown added for a task carrying
    the outside-content mark (§3:6); and none on Approvals, whose input carries no one's
    words (ADR-0361 §3:6). Admission never records ``None`` (§2:5). Each message keeps
    the sender it arrived with, which its reader found from the account it came by
    (ADR-0368 §2:6): no kind declares one.

    Args:
        target: The admitted input's target.
        messages: The messages it took in, as its sensor recorded them; none for a
            channel that records none.
        senders: Who sent an input that records no messages, as its reader found them
            from the accounts it arrived by; none for an input no person sent.
        carries_outside_mark: Whether the input carries the outside-content mark, as an
            occurrence of a scheduled task carrying it does (ADR-0350 §3:8).

    Returns:
        The input's parties, and its messages each carrying its party.

    Raises:
        ValueError: If the channel type declares no parties for the input, a message,
            a forward or the mark; admission refuses it.
    """
    kind = _kind(target)
    stamped = tuple(
        RecordedInputMessage(
            text=one.text,
            sent_at=one.sent_at,
            position=one.position,
            forwarded_from=one.forwarded_from,
            party=message_party(kind, one.forwarded_from, one.sender),
            sender=one.sender,
        )
        for one in messages
    )
    carried = [one.party for one in stamped if one.party is not None]
    return (
        _parties(target, carried, senders, carries_outside_mark=carries_outside_mark),
        stamped,
    )


def sent_by_a_person(channel_type: str) -> bool:
    """Whether a person sends on a channel type's kind by an account (ADR-0366 §4:1).

    The hub chat and the line: their input's sender is the person the link its account
    holds names, as its reader finds it. It says that a person may have sent an input
    there, never who did, which is the link's alone.

    Args:
        channel_type: The channel type; the hub chat's is ``conversation``.

    Returns:
        ``True`` exactly for a type whose kind declares it.
    """
    return channel_type in _SENT_BY_A_PERSON


def most_sureness(channel_type: str) -> Sureness:
    """The most sureness a kind can give, as it declares it (ADR-0366 §5:2).

    Args:
        channel_type: The channel type; the hub chat's is ``conversation``.

    Returns:
        The kind's declared most, or ``none`` for a kind that declares none.
    """
    return _MOST_SURENESS.get(channel_type, Sureness.NONE)


def link_level(link: Link) -> Sureness:
    """A link's level: its kind's declared most, or its lowest standing lowering.

    Whichever is lower (ADR-0366 §5:3, §5:5): nothing raises a link above its kind's
    most, and a link of a kind that declares none is at none.

    Args:
        link: The link, with its lowerings.

    Returns:
        The level.
    """
    return link.level(most_sureness(link.account.kind))


@dataclass(frozen=True, slots=True)
class OriginKind:
    """What the models are told of an origin of one channel type (ADR-0353 §6:3, §7:5).

    Every value is the system's own words, never a record's (§3:4), and none says how a
    reply is shown there, which is planning's (§6:3, ADR-0292 §8:1). Each calls the system
    "the system", never "the hub" (ADR-0375 §7:1), and each is declared here once, beside
    the kind (§7:2).

    Attributes:
        name: How an origin of the kind is named, as ``origin=`` and the situation write
            it (§4:4): ``the system's own chat``.
        where: The name with the preposition a stimulus's place takes: ``in the system's
            own chat``.
        described: What the origin is and who is there, after its name in the situation's
            line (§6:1), with ``{person}`` standing for the person whose place it is,
            named; the framing sentence of a message a person sends says the message
            arrived in it (ADR-0375 §3:1).
        noun: The account a person sends a message there by, as the sender line and a
            ``said`` tag's ``from`` name it (ADR-0375 §4:1, §5): ``a device``; empty for a
            kind whose input no person sends.
        content: What its input's content is called in the framing sentence's
            ``{content}`` slot (§7:1): ``this text`` or ``this report``.
        remembered: Whether its place window is built from the episodes the system
            recorded there, rather than read from the medium, so that understanding renders
            it as memory and says that the origin provides no history (ADR-0353 §2, §8:1;
            ADR-0323 §10:1).
        person_where: Where, as a person reading a card is told it, for a kind whose
            words for a person differ from the models' (ADR-0375 §1:2 changes only what
            the models are told); ``None`` where they are the same.
    """

    name: str
    where: str
    described: str
    noun: str
    content: str
    remembered: bool = False
    person_where: str | None = None

    @property
    def where_for_a_person(self) -> str:
        """Where, as a person reading a card is told it: ``in the hub chat``."""
        return self.where if self.person_where is None else self.person_where


#: ADR-0353 §6:3, §7:5, ADR-0375 §3, §5 and §7: each kind's origin, as the models are told
#: of it.
_ORIGINS: Final = {
    "conversation": OriginKind(
        name="the system's own chat",
        where="in the system's own chat",
        described="{person}'s private chat with the system",
        noun="a device",
        content="this text",
        person_where="in the hub chat",
    ),
    "telegram": OriginKind(
        name="Telegram",
        where="on Telegram",
        described="{person}'s private chat with the system on Telegram",
        noun="the Telegram account",
        content="this text",
        remembered=True,
    ),
    "informational_event": OriginKind(
        name="a connected source",
        where="from a connected source",
        described="a source connected to the system that reports to it; no one there talks with it",
        noun="",
        content="this report",
    ),
    TASK_SCHEDULER: OriginKind(
        name="the schedule",
        where="on the schedule",
        described="the system's schedule of the work set to run later; no one is there",
        noun="",
        content="this text",
    ),
    # ADR-0361 §3:6: the Approvals channel's origin, in the Task Scheduler's style.
    APPROVALS: OriginKind(
        name="the approvals",
        where="on the approvals",
        described=(
            "the system's requests for {person}'s yes, each answered on a card; no one is there"
        ),
        noun="",
        content="this text",
    ),
}


def origin_kind(channel_type: str) -> OriginKind | None:
    """What understanding is told of an origin of ``channel_type`` (ADR-0353 §6:3, §7:5).

    Args:
        channel_type: The channel type; a new conversation's is the hub chat's.

    Returns:
        The kind's declaration, or ``None`` where it declares none, which understanding
        renders with the fallback that says only what the record establishes.
    """
    return _ORIGINS.get(channel_type)
