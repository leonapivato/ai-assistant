"""The engine's half of ADR-0298 §5's route table: the rows that need membership.

**The wire server checks the rows that need only the roster** — the command role,
the role of host of spokes, a known device, the notification poll's connecting
device — before dispatch, and **the engine checks every row that depends on
membership of "my devices" or of a conversation**, reading the requesting device
(ADR-0298 §5:6). This module is the engine's side: one method per membership row,
each given the requesting device the façade read from
:mod:`ai_assistant.core.device_context` and raising
:class:`~ai_assistant.core.errors.DeviceRefusedError` before the operation has
changed anything (§6:1).

**The hub's own machine passes every row** (§3:2), so each check returns at once for
it, with no read: until the cutover every request is ``hub``'s (§9:2), and the checks
are built and tested but refuse nothing and cost nothing.

**A conversation's ends are its devices as the conversation store holds them**
(§5:7). A conversation the store does not hold — never started, or stamped deleted —
has no ends, so a row that needs the device to be one of them refuses it, rather than
letting the operation say whether such a conversation exists. The legacy turn alone
reads otherwise, because its row says so: a call naming no existing conversation
needs "my devices" instead.

**Which of §6:2's reasons a membership refusal carries** is decided here, because the
wire server cannot (it sees roster roles and no membership): ``NO_ROLE`` where the
device holds none of ADR-0296 §2's three roles — no roster role, not in "my devices",
and an end for reading of no conversation — and ``NOT_ALLOWED`` otherwise. §7:13 has a
device refused ``chat_changes`` with ``NO_ROLE`` drop every conversation it holds, so a
device that reads any conversation is never told it holds no role. A device that is
only a writing end of conversations outside "my devices" holds the user's end too
(ADR-0296 §2), and the conversation store lists a device's conversations by reading
alone (``device_conversations``), so that last case is found by replaying the set
changes that reach the device. The several reads a negative takes are bracketed by
the chat space's latest sequence number, so ``NO_ROLE`` is decided over one state
(:meth:`DeviceChecks.holds_a_role`); where that cannot be settled the refusal says
``NOT_ALLOWED`` instead, never ``NO_ROLE``.

**Not here.** The command role, the role of host of spokes and the known-device check
are the wire server's (:mod:`ai_assistant.wire.routes`). ``forget_conversation``'s
"be its end for writing" lapsed with ADR-0293 §11:4, which made it memory-only: it
no longer deletes the conversation, so its row is the command role alone. The change
stream's filter, which keeps a conversation the device no longer reads to its removal
and deletion notices, is ADR-0298's lane 6.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final, NoReturn

from ai_assistant.core.errors import DeviceRefusal, DeviceRefusedError
from ai_assistant.core.types import (
    ChannelIdentity,
    ChatChanges,
    ConversationStartedChange,
    DevicesChangedChange,
    NewConversation,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.core.types import ChatDevice, DeviceAccess, RequestingDevice, UserMessage
    from ai_assistant.orchestration.conversations import ConversationLifecycle

#: The ``channel_type`` of a channel whose input is a conversation's, which makes a
#: ``receive`` a legacy turn rather than spoke traffic (ADR-0298 §5's table).
CONVERSATION_CHANNEL: Final = "conversation"

#: How many changes one page of the replay in :meth:`DeviceChecks._an_end` reads.
_REPLAY_PAGE: Final = 100

#: How many times a negative role decision is bracketed before it is left unsettled.
_ATTEMPTS: Final = 3

#: A cursor past every change, so a read of the changes after it answers with the
#: chat space's latest sequence number alone (``ChatChanges.next_after``).
_LAST: Final = 2**63 - 1


def _access(devices: Sequence[ChatDevice] | None, device_id: str) -> DeviceAccess | None:
    """The access ``device_id`` holds in ``devices``, or ``None`` where it is not in it."""
    for one in devices or ():
        if one.device_id == device_id:
            return one.access
    return None


class DeviceChecks:
    """The membership rows of ADR-0298 §5, read over the engine's chat space.

    Every check takes the requesting device rather than reading it, so the façade
    reads it once, at the call, inside the request the wire server set it for
    (§2:2) — never inside a task that may have been started in another context.
    """

    def __init__(self, conversations: ConversationLifecycle) -> None:
        """Read membership from the chat space the engine acts on.

        Args:
            conversations: The engine's conversation stage, whose devices and "my
                devices" are the ones the operations it gates act on.
        """
        self._conversations = conversations

    async def starting(self, device: RequestingDevice) -> None:
        """§5 "Starting": be in "my devices", with any access (ADR-0296 §2).

        Raises:
            DeviceRefusedError: If the device is not in "my devices".
        """
        if device.is_hub:
            return
        if _access(await self._conversations.my_devices(), device.device_id) is None:
            await self._refuse(device, "start_conversation needs a device in my devices")

    async def writing(self, device: RequestingDevice, conversation_id: str, method: str) -> None:
        """§5 "Writing": be the named conversation's end for writing.

        Raises:
            DeviceRefusedError: If the device is not, or the conversation has no ends.
        """
        if device.is_hub:
            return
        held = _access(
            await self._conversations.conversation_devices(conversation_id), device.device_id
        )
        if held is None or not held.writes:
            await self._refuse(
                device, f"{method} needs a device that is an end for writing of the conversation"
            )

    async def reading(self, device: RequestingDevice, conversation_id: str, method: str) -> None:
        """§5 "Reading one": be the named conversation's end for reading.

        Raises:
            DeviceRefusedError: If the device is not, or the conversation has no ends.
        """
        if device.is_hub:
            return
        held = _access(
            await self._conversations.conversation_devices(conversation_id), device.device_id
        )
        if held is None or not held.reads:
            await self._refuse(
                device, f"{method} needs a device that is an end for reading of the conversation"
            )

    async def writing_message(
        self, device: RequestingDevice, conversation_id: str, message: UserMessage
    ) -> None:
        """§2:7 then §5 "Writing", for ``write_message``.

        Where the requesting device is not ``hub``, the message's ``device_id`` is
        bound to it: a message naming another device is refused (§2:7). Where it is
        ``hub``, the message keeps the device it names (§2:8), and the conversation
        store answers a device that is no writing end as it always has.

        Raises:
            DeviceRefusedError: If the message names another device, or the device
                is not the conversation's end for writing.
        """
        if device.is_hub:
            return
        if message.device_id != device.device_id:
            await self._refuse(
                device, "write_message names a device other than the one it comes from"
            )
        await self.writing(device, conversation_id, "write_message")

    async def turn(
        self, device: RequestingDevice, conversation_id: str | None, method: str
    ) -> None:
        """§5 "A legacy turn": both ends of the named conversation, or of "my devices".

        Where the call names an existing conversation, be its end for writing and for
        reading; otherwise — no conversation named, or one the store does not hold —
        be in "my devices" for writing and for reading. A legacy turn is input to the
        assistant answered with its reply, so it needs both.

        Raises:
            DeviceRefusedError: If the device is not such an end.
        """
        if device.is_hub:
            return
        devices = (
            None
            if conversation_id is None
            else await self._conversations.conversation_devices(conversation_id)
        )
        if devices is None:
            devices = await self._conversations.my_devices()
        held = _access(devices, device.device_id)
        if held is None or not (held.reads and held.writes):
            await self._refuse(
                device, f"{method} needs a device that writes and reads the conversation"
            )

    async def receiving(self, device: RequestingDevice, target: object, method: str) -> None:
        """§5's row for a channel input, chosen by its target alone (§5:2).

        A ``NewConversation``, or a channel whose ``channel_type`` is
        ``conversation``, is a legacy turn (:meth:`turn`); any other target is spoke
        traffic, which needs only the role of host of spokes and is the wire
        server's to check (§5:6), so nothing is checked here.

        Raises:
            DeviceRefusedError: If the input is a legacy turn the device may not make.
        """
        if device.is_hub:
            return
        if isinstance(target, NewConversation):
            await self.turn(device, None, method)
        elif isinstance(target, ChannelIdentity) and target.channel_type == CONVERSATION_CHANNEL:
            await self.turn(device, target.instance_id, method)

    async def polling(self, device: RequestingDevice) -> None:
        """§5 "Notification poll": be in "my devices" for reading.

        The wire server has already refused a poll relayed for another device
        (§5:5), so the requesting device here is the connecting device.

        Raises:
            DeviceRefusedError: If the device is not in "my devices" for reading.
        """
        if device.is_hub:
            return
        held = _access(await self._conversations.my_devices(), device.device_id)
        if held is None or not held.reads:
            await self._refuse(device, "next_notification needs a device in my devices for reading")

    async def reading_many(self, device: RequestingDevice, method: str) -> None:
        """§5 "Reading many": hold a role; the caller then answers by the device.

        Only the role is checked here. That the answer holds only the conversations
        the device reads is the caller's, which reads by the device rather than
        filtering a whole answer.

        Raises:
            DeviceRefusedError: With ``NO_ROLE`` if the device holds no role, or
                ``NOT_ALLOWED`` if whether it holds one could not be settled.
        """
        if device.is_hub:
            return
        held = await self.holds_a_role(device)
        if held is True:
            return
        _raise(f"{method} needs a device that holds a role", _reason(held))

    async def holds_a_role(self, device: RequestingDevice) -> bool | None:
        """Whether the device holds any of ADR-0296 §2's three roles, or ``None``.

        A roster role, or the user's end of conversations: in "my devices", or an end
        of a conversation the store holds, for reading or for writing.

        **A negative is decided over one state of the chat space.** It takes several
        reads, so they are bracketed by the chat space's latest sequence number: the
        store writes each change's number in the same step as the change, and no
        reader sees a later number before an earlier one (``ConversationStore``), so
        equal numbers before and after mean every read saw the same state. A positive
        is true at the read that found it and is answered at once. Where the number
        moves on every one of :data:`_ATTEMPTS` brackets, the answer is ``None``:
        unsettled, which no refusal reports as ``NO_ROLE``.

        Returns:
            ``True`` where the device holds a role, ``False`` where it settledly
            holds none, ``None`` where that could not be settled.
        """
        if device.is_hub or device.roles:
            return True
        for _ in range(_ATTEMPTS):
            before = await self._latest()
            if await self._an_end(device.device_id):
                return True
            if await self._latest() == before:
                return False
        return None

    async def _latest(self) -> int:
        """The chat space's latest sequence number, as one read answers it."""
        page = await self._conversations.changes(after=_LAST, conversation_ids=None, limit=1)
        return page.next_after

    async def _an_end(self, device_id: str) -> bool:
        """Whether ``device_id`` is in "my devices" or an end of any conversation.

        "My devices" and the reading ends are one read each. A writing end is found by
        replaying the set changes that reach the device: ``device_changes`` reaches a
        device with every change that sets a set it is in before or after (ADR-0298
        §7:4), so the last one per conversation is its membership there; each
        conversation that leaves it a member is then read as it stands, since a
        deletion is not a set change and does not reach a device that only writes.
        """
        if _access(await self._conversations.my_devices(), device_id) is not None:
            return True
        if await self._conversations.device_conversations(device_id, limit=1):
            return True
        member: dict[str, bool] = {}
        after = 0
        while True:
            page = await self._conversations.device_changes(
                device_id, after=after, limit=_REPLAY_PAGE
            )
            for one in page.changes:
                if (
                    isinstance(one, (ConversationStartedChange, DevicesChangedChange))
                    and one.conversation_id is not None
                ):
                    member[one.conversation_id] = _access(one.devices, device_id) is not None
            if len(page.changes) < _REPLAY_PAGE or page.next_after <= after:
                break
            after = page.next_after
        for conversation_id in [one for one, held in member.items() if held]:
            devices = await self._conversations.conversation_devices(conversation_id)
            if _access(devices, device_id) is not None:
                return True
        return False

    async def _refuse(self, device: RequestingDevice, message: str) -> NoReturn:
        """Refuse a membership row, with the reason §6:2 gives this device."""
        held = await self.holds_a_role(device)
        _raise(message, DeviceRefusal.NOT_ALLOWED if held is True else _reason(held))


def _reason(held: bool | None) -> DeviceRefusal:
    """``NO_ROLE`` only where the device settledly holds no role.

    An unsettled answer is refused as ``NOT_ALLOWED``: the request is not allowed,
    which is true, and a device told ``NO_ROLE`` drops every conversation it holds
    (ADR-0298 §7:13), which an unsettled answer must not make it do.
    """
    return DeviceRefusal.NO_ROLE if held is False else DeviceRefusal.NOT_ALLOWED


def device_page(page: ChatChanges, conversation_ids: Sequence[str] | None) -> ChatChanges:
    """Restrict a device's page of changes to the conversations its caller named.

    As ``ConversationStore.changes`` restricts a page: the named conversations'
    changes, together with the changes to "my devices", which belong to no
    conversation. The cursor is the device's page's own, so a restricted read still
    moves across every change the device's page passed over.

    Args:
        page: What ``ConversationStore.device_changes`` answered.
        conversation_ids: The conversations the caller asked about, or ``None`` for
            every one the device may see.

    Returns:
        The page, restricted.
    """
    if conversation_ids is None:
        return page
    named = frozenset(conversation_ids)
    kept = tuple(
        one for one in page.changes if one.conversation_id is None or one.conversation_id in named
    )
    return ChatChanges(changes=kept, next_after=page.next_after)


def _raise(message: str, reason: DeviceRefusal) -> NoReturn:
    """Raise the one refusal ADR-0298 §6 gives every check."""
    raise DeviceRefusedError(message, reason=reason)


__all__ = ["CONVERSATION_CHANNEL", "DeviceChecks", "device_page"]
