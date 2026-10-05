"""Pure validation of the channel contract values (ADR-0274 §§3-4).

No dispatch, collaborators, configuration, or authority lives here. Both local
and wire entry points apply the same closed set of representable combinations,
and read the same declaration of where each channel type's input comes from
(ADR-0284 §2:2).

**The text conversational combination is no longer on the surface** (ADR-0293 §11):
a typed message is written into a conversation as an act in the medium, and
``receive`` refuses it. The one input that still carries it is the one
``converse`` builds for itself, kept for the turn that carries a reference until
question messages do (the owner's cut (a), 2026-10-05), and that caller alone
says so with ``typed_turn``.
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
    supplied: ChannelInput, reply: ReplyCapability | None, *, typed_turn: bool = False
) -> tuple[ChannelInput, ReplyCapability | None]:
    """Copy and validate nested caller data before processing can suspend.

    Invalid nested recordings leave no rejected input or exception chain in the
    refusal (ADR-0200 §9). Revalidation starts from dictionaries so even nested
    frozen models containing caller-mutated values are checked and detached.

    Args:
        supplied: The channel input as the caller handed it.
        reply: The reply capability the caller offered, or ``None``.
        typed_turn: ``True`` only for the input ``converse`` builds for its own
            turn, the one entry that still admits the text conversational
            combination (see :func:`validate_combination`).

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
    validate_combination(accepted, accepted_reply, typed_turn=typed_turn)
    return accepted, accepted_reply


def validate_combination(
    supplied: ChannelInput, reply: ReplyCapability | None, *, typed_turn: bool = False
) -> None:
    """Refuse every combination outside the dispatch table this entry admits.

    ADR-0274 §4's table, less the text conversational combination ADR-0293 §11
    takes off the surface: an informational event is text with no reply, and a
    conversation's input is speech with a spoken reply. ``typed_turn`` admits the
    text conversational combination with a whole text reply as well, for
    ``converse``'s own input alone; no streaming combination remains.

    Args:
        supplied: The detached channel input.
        reply: The detached reply capability, or ``None``.
        typed_turn: Whether this is ``converse``'s own input.

    Raises:
        ValueError: If the combination is not in the table.
    """
    target = supplied.target
    kind = "conversation" if isinstance(target, NewConversation) else target.channel_type
    options = supplied.conversation
    valid = False
    if kind == "informational_event":
        valid = (
            isinstance(supplied.payload, TextChannelPayload) and reply is None and options is None
        )
    elif kind == "conversation":
        options = options or ConversationInputOptions()
        if isinstance(supplied.payload, TextChannelPayload):
            valid = typed_turn and options.delivery is None and isinstance(reply, WholeTextReply)
        elif isinstance(supplied.payload, SpeechChannelPayload):
            valid = isinstance(reply, SpokenReply) and options.reference is None
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
