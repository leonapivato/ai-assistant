"""The owner's admitted devices, followed into the identity store as links (ADR-0373 §6).

ADR-0373 §6:2 names enrolling a device as one of the owner's acts a link is recorded
from, and §6:3 says such a link stands only while that act stands. The device record
(:mod:`ai_assistant.service.enrolment`) holds those acts — each enrolment at the hub
and each registration of a browser device by a gateway (ADR-0296 §1) — and this module
follows it: every device the record admits is linked to the owner's identity as the hub
chat's account, ``conversation`` with the device's id (ADR-0293 §4:1), by the owner's
``device`` act; and a ``device`` link whose device nothing admits any more is ended.

**At the act.** :class:`DeviceLinks` registers on the registry
(:meth:`~ai_assistant.service.enrolment.DeviceRegistry.when_admission_acted`), which
calls it once each enrolment, revocation, restored registration or first naming has
taken effect. The callback only schedules: the identity store is asynchronous, and the
record's acts are synchronous so that ADR-0124 §8's commit, live-view transition and
expulsion are one instant. An ``await`` inside them would split it, so the link is
written just after the act, never as part of it.

**Each write reads the record when it runs, not the event that scheduled it.** One lock
orders them, and each settles its device to what the live view says at that moment:
linked where the record admits it, its ``device`` link ended where it does not. So two
acts in quick succession — an enrolment and its revocation — cannot land in the wrong
order, since the write that runs last reads the record after the last act.

**At start.** :meth:`DeviceLinks.follow` does for the device record what the identity
store's opening does for the owner's configuration (L1): every admitted device that no
standing link holds is linked, and every standing ``device`` link whose device is not
admitted is ended. It lives here because the record is ``service``'s, and neither
``memory`` nor ``app`` may import it.

**What a failed write does.** Admission is the record's and does not wait on, or
depend on, a link: an act whose link write fails has still taken effect, and the owner's
reply reports it as before. The failure is logged (``device_link_unwritten``) and the
store is left as it was — a device admitted with no link, or a revoked device whose link
still stands — until the next start's following, which repairs both. Nothing reads the
links yet (L4 switches the readers), and a revoked device is refused at admission
whatever its link says, so the residue changes no answer the hub gives.

**One standing link per account.** The store ties an account to one identity at most
and answers ``unchanged`` where a standing link already ties it to the owner, whatever
act that link came from. So the web door's hosted device, which the owner's
configuration links (``configured``), gains no second link when a gateway registers it,
and its ``configured`` link is never ended here: only a ``device`` link is. ``hub`` and
the hub's own overlay identity are never followed here at all (the registry's
:meth:`~ai_assistant.service.enrolment.DeviceRegistry.admits`): the hub's own machine is
the configuration's ``hub`` link.
"""

from __future__ import annotations

import asyncio
from functools import partial
from typing import TYPE_CHECKING, Final

import structlog

from ai_assistant.core.errors import IdentityStoreError
from ai_assistant.core.types import (
    OWNER_PERSON_ID,
    Account,
    LinkAct,
    LinkActHow,
    LinkWriteKind,
)

if TYPE_CHECKING:
    from ai_assistant.core.protocols import IdentityStore
    from ai_assistant.service.enrolment import DeviceRegistry

__all__ = ["HUB_CHAT", "DeviceLinks"]

_log = structlog.get_logger(__name__)

#: The hub chat's channel type (ADR-0292), whose accounts are the devices it is written
#: from (ADR-0293 §4:1): the kind every device link's account carries.
HUB_CHAT: Final = "conversation"

#: The act every device link is recorded from: the owner's admitting the device.
_DEVICE_ACT: Final = LinkAct(how=LinkActHow.DEVICE, by=OWNER_PERSON_ID)


def _account(device: str) -> Account:
    """The hub chat's account a device writes as."""
    return Account(kind=HUB_CHAT, identifier=device)


class DeviceLinks:
    """Keeps a ``device`` link standing for exactly the devices the record admits."""

    def __init__(self, identities: IdentityStore, registry: DeviceRegistry) -> None:
        """Follow ``registry``'s acts into ``identities`` from now on.

        Args:
            identities: The hub's identity store, opened by the composition root.
            registry: The device record's live view; this registers on it.
        """
        self._identities = identities
        self._registry = registry
        # One write at a time, so each reads the record after every write before it.
        self._writing = asyncio.Lock()
        self._pending: set[asyncio.Task[None]] = set()
        self._closed = False
        registry.when_admission_acted(self._acted)

    async def follow(self) -> None:
        """Follow the record at start: link each admitted device, end each link it left.

        Devices admitted before this hub linked them, or while a link write failed, are
        linked; each standing ``device`` link whose device the record no longer admits
        is ended. A link from any other act is left as it is.

        A store fault is logged (``device_links_unfollowed``) and the hub starts all
        the same: admission does not depend on a link, and the next start follows
        again.
        """
        async with self._writing:
            try:
                linked, ended = await self._follow()
            except (IdentityStoreError, ValueError) as exc:
                _log.warning(
                    "device_links_unfollowed",
                    reason=str(exc),
                    error_class=type(exc).__name__,
                )
                return
        if linked or ended:
            # No device is named: the count is what tells a start that repaired something.
            _log.info("device_links_followed", linked=linked, ended=ended)

    async def _follow(self) -> tuple[int, int]:
        """Link the admitted devices and end the links of those no longer admitted.

        Returns:
            How many links were made, and how many ended.
        """
        admitted = self._registry.admitted_devices()
        accounts = {_account(device) for device in admitted}
        owner = await self._identities.identity(OWNER_PERSON_ID)
        ended = 0
        if owner is not None:
            for held in owner.standing_links:
                if held.act.how is LinkActHow.DEVICE and held.account not in accounts:
                    written = await self._identities.end_link(held.id)
                    if written.kind is LinkWriteKind.WRITTEN:
                        ended += 1
        linked = 0
        for device in sorted(admitted):
            written = await self._identities.link(
                OWNER_PERSON_ID, _account(device), act=_DEVICE_ACT
            )
            if written.kind is LinkWriteKind.REFUSED:
                _log.warning(
                    "device_link_refused",
                    device=device,
                    refusal=None if written.refusal is None else written.refusal.value,
                )
            elif written.kind is LinkWriteKind.WRITTEN:
                linked += 1
        return linked, ended

    async def settled(self) -> None:
        """Wait until every write already scheduled has run."""
        while running := [task for task in self._pending if not task.done()]:
            await asyncio.wait(running)

    async def aclose(self) -> None:
        """Stop following, before the drain closes the identity store.

        A write still pending is cancelled; an act after this writes nothing. Either
        leaves the store as the next start's following repairs, and is logged.
        """
        self._closed = True
        for task in self._pending:
            task.cancel()
        await self.settled()

    def _acted(self, device: str) -> None:
        """Schedule the link write that follows one act on ``device``. Never raises."""
        try:
            loop = None if self._closed else asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop is None:
            _log.warning(
                "device_link_unwritten",
                device=device,
                reason="the hub is not following its devices; its next start does",
            )
            return
        task = loop.create_task(self._settle(device))
        self._pending.add(task)
        task.add_done_callback(partial(self._done, device))

    def _done(self, device: str, task: asyncio.Task[None]) -> None:
        """Forget a finished write, logging a fault nobody was left waiting to see."""
        self._pending.discard(task)
        if task.cancelled():
            _log.warning(
                "device_link_unwritten",
                device=device,
                reason="the hub stopped first; its next start follows the record",
            )
        elif (fault := task.exception()) is not None:
            _log.error(
                "device_link_unwritten",
                device=device,
                reason=str(fault),
                error_class=type(fault).__name__,
            )

    async def _settle(self, device: str) -> None:
        """Bring ``device``'s link to what the record says now, logging a failed write."""
        async with self._writing:
            try:
                await self._settle_holding(device)
            except (IdentityStoreError, ValueError) as exc:
                _log.warning(
                    "device_link_unwritten",
                    device=device,
                    reason=str(exc),
                    error_class=type(exc).__name__,
                )

    async def _settle_holding(self, device: str) -> None:
        """Link ``device`` where the record admits it, and end its device link where not."""
        account = _account(device)
        if self._registry.admits(device):
            written = await self._identities.link(OWNER_PERSON_ID, account, act=_DEVICE_ACT)
            if written.kind is LinkWriteKind.REFUSED:
                _log.warning(
                    "device_link_refused",
                    device=device,
                    refusal=None if written.refusal is None else written.refusal.value,
                )
            elif written.kind is LinkWriteKind.WRITTEN:
                _log.info("device_linked", device=device, link_id=written.record_id)
            return
        held = await self._identities.find_link(account)
        if held is None or held.act.how is not LinkActHow.DEVICE:
            return
        written = await self._identities.end_link(held.id)
        if written.kind is LinkWriteKind.WRITTEN:
            _log.info("device_link_ended", device=device, link_id=held.id)
