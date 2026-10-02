"""Pure validation of the channel contract values (ADR-0274 §§3-4).

No dispatch, collaborators, configuration, or authority lives here. Both local
and wire entry points apply the same closed set of representable combinations,
and read the same declaration of where each channel type's input comes from
(ADR-0284 §2:2).
"""

from __future__ import annotations

from types import MappingProxyType
from typing import TYPE_CHECKING, Final

from pydantic import TypeAdapter, ValidationError

from ai_assistant.core.types import (
    ChannelInput,
    ConversationInputOptions,
    InputOrigin,
    NewConversation,
    ReplyCapability,
    SpeechChannelPayload,
    SpokenDeliveryState,
    SpokenReply,
    StreamingTextReply,
    TextChannelPayload,
    WholeTextReply,
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
    supplied: ChannelInput, reply: ReplyCapability | None, *, streaming: bool
) -> tuple[ChannelInput, ReplyCapability | None]:
    """Copy and validate nested caller data before processing can suspend.

    Invalid nested recordings leave no rejected input or exception chain in the
    refusal (ADR-0200 §9). Revalidation starts from dictionaries so even nested
    frozen models containing caller-mutated values are checked and detached.
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
    validate_combination(accepted, accepted_reply, streaming=streaming)
    return accepted, accepted_reply


def validate_combination(
    supplied: ChannelInput, reply: ReplyCapability | None, *, streaming: bool
) -> None:
    """Refuse every combination outside ADR-0274 §4's complete dispatch table."""
    target = supplied.target
    kind = "conversation" if isinstance(target, NewConversation) else target.channel_type
    options = supplied.conversation
    valid = False
    if kind == "informational_event":
        valid = (
            not streaming
            and isinstance(supplied.payload, TextChannelPayload)
            and reply is None
            and options is None
        )
    elif kind == "conversation":
        options = options or ConversationInputOptions()
        if isinstance(supplied.payload, TextChannelPayload):
            valid = options.delivery is None and (
                isinstance(reply, StreamingTextReply)
                if streaming
                else isinstance(reply, WholeTextReply)
            )
        elif isinstance(supplied.payload, SpeechChannelPayload):
            valid = not streaming and isinstance(reply, SpokenReply) and options.reference is None
            if options.delivery is not None:
                valid = (
                    valid
                    and not isinstance(target, NewConversation)
                    and (options.delivery.delivery.state is not SpokenDeliveryState.UNKNOWN)
                )
    if not valid:
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
