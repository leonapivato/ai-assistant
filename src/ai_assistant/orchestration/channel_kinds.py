"""What a channel kind declares, in code (ADR-0292, ADR-0323 §9).

ADR-0292 lists what every kind declares: its channels, its spokes and their
directions, whether it is pulled or pushes, which events are input, its push filter,
how it establishes authors, its places, its window, what counts as sent, its
description, its requirements and its audience. Until the Telegram line no kind was
declared in code: the hub chat's description is stated where the phases show it, and
what admission needs of every type — its input origin, and whether it establishes the
user as an author — is :mod:`ai_assistant.core.channel_validation`'s register.

**This module is the shape the first kind declared in code takes** (ADR-0323 §9:1,
ADR-0324's "the shape the first kind declared in code takes"): one frozen
:class:`ChannelKind`, a field per row of ADR-0292's table, each a value code reads
rather than prose. A kind declared here states what it is; the module that builds its
spoke reads the rows it acts on (its description, its window, its writer's rules), and
the rows admission reads stay in ``core``'s register, which :meth:`ChannelKind.
establishes_the_user` and :meth:`ChannelKind.input_origin` read rather than restate,
so the two can never disagree. A pulled kind's declaration needs of this only its
description (ADR-0324), and the shape takes it with no spoke at all.

**Places** (ADR-0306 §6, ADR-0292 §10:8). A message's effect record names the place it
went into as ``<channel type>:<instance id>`` — ``conversation:<id>`` for the hub chat,
as it always was. :func:`place_of` spells it, and :func:`users_place` reads from a
recorded place whether its kind establishes the user there, which is what authorizing
reads of a question's place (ADR-0323 §4:8) without naming a channel (§4:5).

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
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Final

from pydantic import ValidationError

from ai_assistant.core.channel_validation import establishes_the_user, input_origin, origin_kind
from ai_assistant.core.types import ChannelIdentity

if TYPE_CHECKING:
    from ai_assistant.core.channel_validation import OriginKind
    from ai_assistant.core.types import ApprovalGiver, InputOrigin

__all__ = [
    "Audience",
    "ChannelKind",
    "Direction",
    "Reach",
    "WindowSource",
    "confirms_delivery",
    "place_channel",
    "place_of",
    "users_place",
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
        authors: How it establishes authors (§5:4), in words; whether it establishes the
            user at all is ``core``'s register, read by :meth:`establishes_the_user`.
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
        approval_giver: Who a yes on its places is, where its kind establishes the user
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
        """A kind that establishes nobody gives no approval, and a window holds an item.

        Raises:
            ValueError: If the kind names an approval giver though ``core``'s register
                says it establishes nobody, or its window's size is not positive.
        """
        if self.approval_giver is not None and not self.establishes_the_user:
            msg = "only a kind that establishes the user as an author gives an approval"
            raise ValueError(msg)
        if (self.window is WindowSource.NONE) != (self.window_items is None):
            msg = "a kind with a window says how many items it holds, and one without none"
            raise ValueError(msg)
        if self.window_items is not None and self.window_items < 1:
            msg = "a window holds at least one item"
            raise ValueError(msg)

    @property
    def establishes_the_user(self) -> bool:
        """Whether the kind establishes the user as an author in its places (§5:4)."""
        return establishes_the_user(self.channel_type)

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

    def input_origin(
        self,
        channel: ChannelIdentity,
        *,
        takes_in_forward: bool,
        carries_outside_mark: bool = False,
    ) -> InputOrigin:
        """The origin the kind declares for one input on ``channel`` (ADR-0284 §2:2).

        A kind that declares its origin per input reads, for this one, whether it takes
        in a forward (ADR-0323 §4:11) or carries the outside-content mark (ADR-0350
        §6:3).

        Raises:
            ValueError: If ``channel`` is not of this kind, or the register declares no
                origin for the input.
        """
        if channel.channel_type != self.channel_type:
            msg = "a kind declares the origin of its own channels' input alone"
            raise ValueError(msg)
        return input_origin(
            channel, takes_in_forward=takes_in_forward, carries_outside_mark=carries_outside_mark
        )


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


def users_place(place: str | None) -> bool:
    """Whether a recorded place is one whose kind establishes the user as an author there.

    ADR-0323 §4:8's *shown to you*: one of the user's conversations, or the line's chat.
    Read from the place as its effect record names it (:func:`place_of`), so no rule
    reading it names a channel (§4:5). A place with no channel type, or none at all, is
    nobody's.
    """
    if not place:
        return False
    channel_type, separator, instance = place.partition(_PLACE_SEPARATOR)
    return bool(separator and instance) and establishes_the_user(channel_type)
