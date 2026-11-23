"""The owner's linked accounts, as the engine harness links them by default (milestone 20).

Who sent an input is read from the link its account holds (ADR-0366 §4:1), and a work
is the owner's only where the links say so (ADR-0368 §9:1, §9:5). A hub links the
owner's accounts from its configuration and the devices the owner admitted (ADR-0373
§6:2, §6:3); the harness stands in for that with one canonical
:class:`~ai_assistant.testing.FakeIdentityStore`, built afresh for each harness, that
links to the owner every device the cases here write the hub chat from as the owner,
and the Telegram account the line's cases write as the owner (``telegram_support.CHAT``).

A device the owner never admitted (``stranger``, and any id a case invents) is linked
to no one, so its messages are an unidentified sender's, as on a hub. A case about the
links themselves builds its own store, or passes ``identities=None`` for an engine with
none wired, whose every message is read as ADR-0374 rules for links that cannot be
read.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final

from telegram_support import CHAT

from ai_assistant.core.channel_validation import declared_input, sent_by_a_person
from ai_assistant.core.types import (
    HUB_DEVICE_ID,
    Account,
    ChannelContext,
    ChannelIdentity,
    ChannelInput,
    RecordedChannelTrigger,
    RecordedTextInput,
    TextChannelPayload,
    WholeTextReply,
    canonical_senders,
)
from ai_assistant.orchestration.activation_state import (
    CURRENT_ACTIVATION,
    ActivationScope,
    admit_channel,
)
from ai_assistant.orchestration.work_facts import CHAT_ACCOUNT_KIND, LINE_ACCOUNT_KIND, started
from ai_assistant.testing import FakeIdentityStore
from ai_assistant.testing.parties import OWNER_SENDER, owners_facts

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

    from ai_assistant.core.types import (
        ChannelTarget,
        InputSender,
        RecordedInputMessage,
        WorkFacts,
    )
    from ai_assistant.orchestration.activation_state import ActivationState

#: The devices the cases write the hub chat from as the owner: the hub's own machine and
#: the owner's admitted devices.
OWNERS_DEVICES: Final = (
    HUB_DEVICE_ID,
    "phone",
    "watch",
    "laptop",
    "pen",
    "tablet",
    "keyboard",
    "console",
    "new-phone",
)

#: Every account the harness links to the owner: each device, and the line's account.
OWNERS_ACCOUNTS: Final = (
    *(Account(kind=CHAT_ACCOUNT_KIND, identifier=one) for one in OWNERS_DEVICES),
    Account(kind=LINE_ACCOUNT_KIND, identifier=str(CHAT)),
)


def owners_identities() -> FakeIdentityStore:
    """A fresh identity store linking :data:`OWNERS_ACCOUNTS` to the owner (ADR-0366 §2:5)."""
    return FakeIdentityStore(configured=OWNERS_ACCOUNTS)


@contextmanager
def admitted(
    target: ChannelTarget | None = None,
    *,
    senders: Sequence[InputSender] = (OWNER_SENDER,),
    text: str = "hello",
) -> Iterator[ActivationState]:
    """An activation admitted on ``target`` as the running one, from ``senders``.

    The hub chat's conversation ``c-1`` where no target is given, sent by the owner's
    linked account unless a case names other senders, so a working set begun inside it
    reads that work's facts (ADR-0368 §9:1).

    Yields:
        The activation's state, current for the block.
    """
    state = admit_channel(
        ChannelInput(
            target=target or ChannelIdentity(channel_type="conversation", instance_id="c-1"),
            payload=TextChannelPayload(text=text),
        ),
        WholeTextReply(),
        clock=lambda: datetime(2026, 11, 23, 9, tzinfo=UTC),
        id_factory=lambda: "0b8f8f0e-2a5c-4c55-9a6c-6a2c1f0b0d99",
        senders=senders,
    )
    token = CURRENT_ACTIVATION.set(ActivationScope(state))
    try:
        yield state
    finally:
        CURRENT_ACTIVATION.reset(token)


def recorded_facts(trigger: RecordedChannelTrigger) -> WorkFacts:
    """The facts admission records on a work ``trigger`` started, for a hand-built episode.

    A trigger a test builds names no senders; where a person sends on its kind, its input
    is taken as the owner's linked account's (:func:`~ai_assistant.testing.parties.
    owners_facts`), and any other kind's as admission decides it (:func:`started`): an
    event's, a task's or an approval's the owner's work carrying none, and a kind with no
    row no one's. Every episode a hub holds carries its facts, an old one's given by the
    upgrade (ADR-0368 §2).
    """
    if trigger.senders or not sent_by_a_person(trigger_kind(trigger)):
        return started(trigger)
    return owners_facts(trigger.parties)


def trigger_kind(trigger: RecordedChannelTrigger) -> str:
    """The channel type a trigger's input came by; a new conversation is the hub chat's."""
    if trigger.channel is not None:
        return trigger.channel.channel_type
    target = trigger.target
    return target.channel_type if isinstance(target, ChannelIdentity) else "conversation"


def owners_trigger(
    target: ChannelTarget,
    text: str = "hello",
    messages: Sequence[RecordedInputMessage] = (),
) -> RecordedChannelTrigger:
    """The trigger admission records for an input the owner's linked account sent.

    Its parties as the kind declares them from that sender (ADR-0351 §3:2), its
    messages each sent by the owner, and its senders theirs; on a kind no person sends
    on, the kind's own parties and no sender.
    """
    channel = target if isinstance(target, ChannelIdentity) else None
    kind = "conversation" if channel is None else channel.channel_type
    person = sent_by_a_person(kind)
    sent = tuple(
        one
        if one.sender is not None or not person
        else one.model_copy(update={"sender": OWNER_SENDER})
        for one in messages
    )
    senders = (OWNER_SENDER,) if person and not sent else ()
    parties, recorded = declared_input(target, sent, senders=senders)
    return RecordedChannelTrigger(
        target=target,
        channel=channel,
        payload=RecordedTextInput(text=text),
        context=ChannelContext(),
        reply=WholeTextReply(),
        parties=parties,
        messages=recorded,
        senders=canonical_senders(
            (*senders, *(one.sender for one in recorded if one.sender is not None))
        ),
    )
