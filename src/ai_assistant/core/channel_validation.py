"""Pure validation of the channel contract values (ADR-0274 §§3-4).

No dispatch, collaborators, configuration, or authority lives here. Both local
and wire entry points apply the same closed set of representable combinations,
and read the same declaration of whose words each channel type's input carries, its
**parties** (ADR-0351 §3:1, in place of ADR-0284 §2:2's origin), and of which channel
types establish the user as an author in their places (ADR-0292 §5:4, ADR-0323 §4:8).

**No conversational combination is on the surface.** A typed message is written
into a conversation as an act in the medium (ADR-0293 §11), and spoken
conversation retired at the cutover (ADR-0313 §3:2), so ``receive`` admits an
event alone (§4:1).

**Nor is the Telegram line's** (ADR-0323 §2:2, §4:1). Its input is admitted by its
reader in the hub alone, which establishes the user by comparing the sender id
Telegram reports against the setting (§4:3): a ``telegram`` input handed to
``receive`` would carry the user's authority on nobody's establishment, so the
dispatch table refuses it as it refuses every type it does not list.

**Nor is the Task Scheduler's** (ADR-0350 §2:7, §7). It is a built-in channel whose
sensor pushes each scheduled task's occurrence in the hub alone; the register declares
its parties per input, the assistant's statement naming the task's instruction, with
unknown added for a task carrying the outside-content mark (ADR-0351 §3:6), and it
establishes no author as the user in its place.

**The parties each kind declares** (ADR-0351 §3's table), per input, set by code at
admission from the declaration and the record the sensor brings (§2:8): the hub chat's
input, and each message it takes in, carry the owner's words; the line's carry the
owner's, a forward's its original sender's, claimed (§2:7), and an input of several
messages the distinct parties of its messages (§2:6); an informational event's carries
its connected source's, established, named by the channel's identity (§3:5); and the
Task Scheduler's the assistant's statement (§3:6). The one person a party names is the
owner (§3:2). A kind not built, a mail channel or a spoke that tells who is talking,
declares nothing here until it is, and a channel type with no declaration is refused.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from pydantic import TypeAdapter, ValidationError

from ai_assistant.core.types import (
    OWNER_PERSON_ID,
    ChannelIdentity,
    ChannelInput,
    ClaimedAuthor,
    NewConversation,
    RecordedInputMessage,
    ReplyCapability,
    StatementPart,
    SupportHolder,
    TextChannelPayload,
    canonical_parties,
    forward_party,
    parties_origin,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.core.types import ChannelTarget, InputOrigin

_REPLY = TypeAdapter[ReplyCapability | None](ReplyCapability | None)

#: ADR-0350 §2:1, §2:8: the channel type of the **Task Scheduler**, the built-in channel
#: whose one place, the schedule, holds the scheduled tasks every spawn writes. Its kind
#: establishes no author as the user in its place (§2:7), so it is absent from
#: :data:`_ESTABLISHES_THE_USER`, and nothing a caller hands ``receive`` is one: its
#: sensor pushes each occurrence in the hub alone (§7).
TASK_SCHEDULER: Final = "task_scheduler"

#: ADR-0351 §3:1, §3:2: the channel types whose every message its sender wrote carries
#: the owner's words, the one person a party names until a decision on identified
#: people: the hub chat and the line. A kind absent from it declares no person's words.
_THE_OWNERS_WORDS: Final = frozenset({"conversation", "telegram"})

#: ADR-0351 §2:7, §3:1 (ADR-0323 §4:11): the channel types that take forwards in, each
#: forward's party its original sender, claimed. A kind absent from it takes in none.
_TAKES_FORWARDS: Final = frozenset({"telegram"})

#: ADR-0351 §3:5: the channel types whose input is a connected source's report, its
#: party that source, established, named by the channel's identity.
_A_SOURCES_REPORT: Final = frozenset({"informational_event"})

#: ADR-0292 §5:4, ADR-0323 §4:8: the channel types whose kind establishes the user as
#: an author in their places — one of the user's conversations, or the line's chat. A
#: question's message is *shown to you* only in such a place (ADR-0321 §4:4), and a
#: type absent from it establishes nobody.
_ESTABLISHES_THE_USER: Final = frozenset({"conversation", "telegram"})

#: A forward whose sender is not in hand, which :func:`input_origin` reads the kind's
#: declaration for: its party is unknown, an outside member, as every forward's is
#: outside whatever its sender (ADR-0351 §2:7, §5:1).
_SOME_FORWARD: Final = ClaimedAuthor(name="a forward's original sender")


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


def message_party(channel_type: str, forwarded_from: ClaimedAuthor | None) -> SupportHolder:
    """The party a kind declares for one message its input takes in (ADR-0351 §2:6, §3:1).

    A message its sender wrote, on a kind that carries the owner's words, is the
    owner's (§3:2); a forward, on a kind that takes forwards in, is its original
    sender's, claimed, or unknown where the medium names none (§2:7). Set from who sent
    the message, never from what it says (§2:9).

    Args:
        channel_type: The channel type the message came in on.
        forwarded_from: The forward's original sender, or ``None`` for a message its
            sender wrote.

    Returns:
        The message's party.

    Raises:
        ValueError: If the kind declares no party for such a message: it takes in no
            forward, or records no person's messages. Admission refuses it.
    """
    if forwarded_from is not None:
        if channel_type not in _TAKES_FORWARDS:
            msg = "the channel type takes in no forward (ADR-0351 §3:1)"
            raise ValueError(msg)
        return forward_party(forwarded_from)
    if channel_type not in _THE_OWNERS_WORDS:
        msg = "the channel type declares no party for a message it takes in (ADR-0351 §3:1)"
        raise ValueError(msg)
    return SupportHolder.person(OWNER_PERSON_ID)


def _parties(
    target: ChannelTarget, carried: Sequence[SupportHolder], *, carries_outside_mark: bool
) -> tuple[SupportHolder, ...]:
    """The parties ``target``'s kind declares for one input, its messages' ``carried``."""
    kind = _kind(target)
    if carries_outside_mark and (kind != TASK_SCHEDULER or carried):
        msg = "the channel type declares no parties for an input carrying the mark"
        raise ValueError(msg)
    if carried:
        # §2:6: an input of messages carries exactly their distinct parties.
        return canonical_parties(carried)
    if kind in _THE_OWNERS_WORDS:
        return (SupportHolder.person(OWNER_PERSON_ID),)
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
    msg = "the channel type declares no parties for its input (ADR-0351 §3:1)"
    raise ValueError(msg)


def declared_input(
    target: ChannelTarget,
    messages: Sequence[RecordedInputMessage] = (),
    *,
    carries_outside_mark: bool = False,
) -> tuple[tuple[SupportHolder, ...], tuple[RecordedInputMessage, ...]]:
    """The parties a kind declares for one input, and its messages each with its party.

    ADR-0351 §3:1, which admission records on the trigger and fixes on the episode
    (§2:8). Each message is given the party :func:`message_party` declares for it,
    whatever party it arrived with, and the input's parties are its messages' distinct
    parties (§2:6), or, for an input that records none, the one set its kind declares:
    the owner on the hub chat and the line, the source an informational event names,
    or the assistant's statement on the Task Scheduler, with unknown added for a task
    carrying the outside-content mark (§3:6). Admission never records ``None`` (§2:5).

    Args:
        target: The admitted input's target.
        messages: The messages it took in, as its sensor recorded them; none for a
            channel that records none.
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
            party=message_party(kind, one.forwarded_from),
        )
        for one in messages
    )
    carried = [one.party for one in stamped if one.party is not None]
    return _parties(target, carried, carries_outside_mark=carries_outside_mark), stamped


def input_origin(
    target: ChannelTarget, *, takes_in_forward: bool = False, carries_outside_mark: bool = False
) -> InputOrigin:
    """The origin computed from the parties a kind declares, until it retires.

    ADR-0351 §10:2 keeps ``origin`` as a value computed from the parties alone, so
    this reads the one declaration :func:`declared_input` reads and computes the
    origin from it, rather than declaring an origin of its own: ``user`` for the
    owner's words, ``outside`` for a forward, an informational event or a marked task,
    and ``assistant`` for a scheduled task's instruction. A new conversation declares
    what the hub chat declares.

    Args:
        target: The input's target.
        takes_in_forward: Whether the input takes in a forward.
        carries_outside_mark: Whether the input carries the outside-content mark.

    Returns:
        The computed :class:`~ai_assistant.core.types.InputOrigin`.

    Raises:
        ValueError: If the channel type declares no parties for the input, or the input
            both takes in a forward and carries the mark.
    """
    if takes_in_forward and carries_outside_mark:
        msg = "an input takes in a forward or carries the outside-content mark, not both"
        raise ValueError(msg)
    carried = (message_party(_kind(target), _SOME_FORWARD),) if takes_in_forward else ()
    return parties_origin(_parties(target, carried, carries_outside_mark=carries_outside_mark))


def establishes_the_user(channel_type: str) -> bool:
    """Whether a channel type's kind establishes the user as an author in its places.

    ADR-0292 §5:4 as ADR-0323 §4:8 reads it: one of the user's conversations, or the
    line's chat. What authorizing reads of a question's place, so no rule of its names
    a channel (§4:5).

    Args:
        channel_type: The channel type.

    Returns:
        ``True`` exactly for a type whose kind declares it.
    """
    return channel_type in _ESTABLISHES_THE_USER
