"""Pure validation of the channel contract values (ADR-0274 §§3-4).

No dispatch, collaborators, configuration, or authority lives here. Both local
and wire entry points apply the same closed set of representable combinations,
and read the same declaration of where each channel type's input comes from
(ADR-0284 §2:2).

**No conversational combination is on the surface.** A typed message is written
into a conversation as an act in the medium (ADR-0293 §11), and spoken
conversation retired at the cutover (ADR-0313 §3:2), so ``receive`` admits an
event alone (§4:1).
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
#: declarations (#2578). A channel type absent from it is refused at admission.
_INPUT_ORIGINS: Final[Mapping[str, InputOrigin]] = MappingProxyType(
    {
        "conversation": InputOrigin.USER,
        "informational_event": InputOrigin.OUTSIDE,
    }
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


def input_origin(target: ChannelTarget) -> InputOrigin:
    """The origin a channel declares for its input, which admission records (ADR-0284 §2:2).

    A new conversation is a ``conversation`` channel not yet allocated, so it
    declares what that channel type declares.

    Args:
        target: The admitted input's target.

    Returns:
        The channel type's declared :class:`~ai_assistant.core.types.InputOrigin`.

    Raises:
        ValueError: If the channel type declares none; admission refuses it.
    """
    kind = "conversation" if isinstance(target, NewConversation) else target.channel_type
    origin = _INPUT_ORIGINS.get(kind)
    if origin is None:
        msg = "the channel type declares no input origin"
        raise ValueError(msg)
    return origin
