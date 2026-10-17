"""Pure validation of the channel contract values (ADR-0274 §§3-4).

No dispatch, collaborators, configuration, or authority lives here. Both local
and wire entry points apply the same closed set of representable combinations,
and read the same declaration of where each channel type's input comes from
(ADR-0284 §2:2), and of which channel types establish the user as an author in
their places (ADR-0292 §5:4, ADR-0323 §4:8).

**No conversational combination is on the surface.** A typed message is written
into a conversation as an act in the medium (ADR-0293 §11), and spoken
conversation retired at the cutover (ADR-0313 §3:2), so ``receive`` admits an
event alone (§4:1).

**Nor is the Telegram line's** (ADR-0323 §2:2, §4:1). Its input is admitted by its
reader in the hub alone, which establishes the user by comparing the sender id
Telegram reports against the setting (§4:3): a ``telegram`` input handed to
``receive`` would carry the user's authority on nobody's establishment, so the
dispatch table refuses it as it refuses every type it does not list.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import TYPE_CHECKING, Final

from pydantic import TypeAdapter, ValidationError

from ai_assistant.core.types import (
    ChannelInput,
    InputOrigin,
    NewConversation,
    ReplyCapability,
    TextChannelPayload,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from ai_assistant.core.types import ChannelTarget

_REPLY = TypeAdapter[ReplyCapability | None](ReplyCapability | None)

#: ADR-0284 §2:2: what each channel type declares about where its input comes from.
#: It lives here, beside the dispatch table, until channels carry their own
#: declarations (#2578). A channel type absent from it is refused at admission. This
#: is the origin of an input that takes in no forward; a kind that takes forwards in
#: declares theirs beside it, in :data:`_FORWARDED_ORIGINS`.
_INPUT_ORIGINS: Final[Mapping[str, InputOrigin]] = MappingProxyType(
    {
        "conversation": InputOrigin.USER,
        "informational_event": InputOrigin.OUTSIDE,
        # ADR-0323 §4:11: the Telegram line declares its origin per input, `user` for
        # an input that takes in no forward.
        "telegram": InputOrigin.USER,
    }
)

#: ADR-0323 §4:11, on ADR-0284 §2:2: the origin a kind declares for an input that takes
#: in a forward, which is therefore an outside trigger (ADR-0306 §4:5). A channel type
#: absent from it takes in no forward.
_FORWARDED_ORIGINS: Final[Mapping[str, InputOrigin]] = MappingProxyType(
    {"telegram": InputOrigin.OUTSIDE}
)

#: ADR-0292 §5:4, ADR-0323 §4:8: the channel types whose kind establishes the user as
#: an author in their places — one of the user's conversations, or the line's chat. A
#: question's message is *shown to you* only in such a place (ADR-0321 §4:4), and a
#: type absent from it establishes nobody.
_ESTABLISHES_THE_USER: Final = frozenset({"conversation", "telegram"})


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


def input_origin(target: ChannelTarget, *, takes_in_forward: bool = False) -> InputOrigin:
    """The origin a channel declares for its input, which admission records (ADR-0284 §2:2).

    A new conversation is a ``conversation`` channel not yet allocated, so it
    declares what that channel type declares. A kind declares its origin per input
    where it takes forwards in (ADR-0323 §4:11): an input that takes one in has the
    origin the kind declares for it, and every other input the kind's plain one.

    Args:
        target: The admitted input's target.
        takes_in_forward: Whether the input takes in a forward.

    Returns:
        The channel type's declared :class:`~ai_assistant.core.types.InputOrigin`.

    Raises:
        ValueError: If the channel type declares none, or declares none for an input
            that takes in a forward; admission refuses it.
    """
    kind = "conversation" if isinstance(target, NewConversation) else target.channel_type
    origin = (_FORWARDED_ORIGINS if takes_in_forward else _INPUT_ORIGINS).get(kind)
    if origin is None:
        msg = "the channel type declares no input origin for this input"
        raise ValueError(msg)
    return origin


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
