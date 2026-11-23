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

**Each act is written as it left the record, in the order the acts were made.** Whether
the record admits the device is read in the act's own step, and one worker replays the
acts in order: linked where the act left the device admitted, its ``device`` link ended
where it did not. So an enrolment and its revocation made back to back cannot land in the
wrong order, and a revocation and a restore made back to back end the old link and make
a new one, as two acts do (ADR-0366 §3), however late the writes run.

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
whatever its link says, so the residue changes no answer the hub gives. A revoked
device admitted again before that repair never keeps the old link: a ``device`` link
made before the device's current, unbroken admission began
(:meth:`~ai_assistant.service.enrolment.DeviceRegistry.admitted_since`, read from the
record, which keeps every revocation) stood on an admission that has ended, so it is
ended and a new one made, at the re-admitting act or at the next start.

**One standing link per account.** The store ties an account to one identity at most
and answers ``unchanged`` where a standing link already ties it to the owner, whatever
act that link came from. So the web door's hosted device, which the owner's
configuration links (``configured``), gains no second link when a gateway registers it,
and its ``configured`` link is never ended here: only a ``device`` link is. Where a
``device`` link this ends ties an account the configuration names — the hosted device set
to a device already linked by its admission — the account is linked again by the
``configured`` act it still stands on, so it is never left unlinked. ``hub`` and
the hub's own overlay identity are never followed here at all (the registry's
:meth:`~ai_assistant.service.enrolment.DeviceRegistry.admits`): the hub's own machine is
the configuration's ``hub`` link.
"""

from __future__ import annotations

import asyncio
from collections import deque
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
    from collections.abc import Collection

    from ai_assistant.core.protocols import IdentityStore
    from ai_assistant.core.types import Link
    from ai_assistant.service.enrolment import DeviceRegistry

__all__ = ["HUB_CHAT", "DeviceLinks"]

_log = structlog.get_logger(__name__)

#: The hub chat's channel type (ADR-0292), whose accounts are the devices it is written
#: from (ADR-0293 §4:1): the kind every device link's account carries.
HUB_CHAT: Final = "conversation"

#: The act every device link is recorded from: the owner's admitting the device.
_DEVICE_ACT: Final = LinkAct(how=LinkActHow.DEVICE, by=OWNER_PERSON_ID)

#: The act a configured account is linked by, where ending a device link hands it back.
_CONFIGURED_ACT: Final = LinkAct(how=LinkActHow.CONFIGURED, by=OWNER_PERSON_ID)


def _account(device: str) -> Account:
    """The hub chat's account a device writes as."""
    return Account(kind=HUB_CHAT, identifier=device)


class DeviceLinks:
    """Keeps a ``device`` link standing for exactly the devices the record admits."""

    def __init__(
        self,
        identities: IdentityStore,
        registry: DeviceRegistry,
        *,
        configured: Collection[Account] = (),
    ) -> None:
        """Follow ``registry``'s acts into ``identities`` from now on.

        Args:
            identities: The hub's identity store, opened by the composition root.
            registry: The device record's live view; this registers on it.
            configured: The accounts the owner's configuration names, as the store was
                opened with (:func:`~ai_assistant.app.composition.configured_accounts`).
                Where a ``device`` link this ends ties one of them, the account is
                linked again by the owner's ``configured`` act, as the store's opening
                would have done had that link not held it.
        """
        self._identities = identities
        self._registry = registry
        self._configured = frozenset(configured)
        # One write at a time, so the start's following and the acts never interleave.
        self._writing = asyncio.Lock()
        # Each act's device and whether the record admitted it once the act took effect,
        # in the order the acts were made, replayed in that order by one worker.
        self._acts: deque[tuple[str, bool]] = deque()
        self._worker: asyncio.Task[None] | None = None
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
                if (
                    held.act.how is LinkActHow.DEVICE
                    and (held.account not in accounts or self._outlived(held))
                    and await self._end(held.id, held.account)
                ):
                    ended += 1
        linked = 0
        for device in sorted(admitted):
            if await self._link(device):
                linked += 1
        return linked, ended

    async def settled(self) -> None:
        """Wait until every write already scheduled has run."""
        while (worker := self._worker) is not None and not worker.done():
            await asyncio.wait({worker})

    async def aclose(self) -> None:
        """Stop following, before the drain closes the identity store.

        A write still pending is let go; an act after this writes nothing. Either
        leaves the store as the next start's following repairs, and is logged.
        """
        self._closed = True
        if self._worker is not None:
            self._worker.cancel()
        await self.settled()
        self._unwritten("the hub stopped first; its next start follows the record")

    def _acted(self, device: str) -> None:
        """Note one act on ``device`` and what the record says after it. Never raises.

        The record is read here, in the act's own step, so each act is replayed as it
        left the record: a revocation and a restore made back to back end the old link
        and make a new one, as two acts do (ADR-0366 §3), however late the writes run.
        """
        self._acts.append((device, self._registry.admits(device)))
        try:
            loop = None if self._closed else asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop is None:
            self._unwritten("the hub is not following its devices; its next start does")
            return
        if self._worker is None or self._worker.done():
            self._worker = loop.create_task(self._replay())
            self._worker.add_done_callback(self._done)

    def _unwritten(self, reason: str) -> None:
        """Let go of every act not yet written, saying which devices it leaves."""
        while self._acts:
            device, _ = self._acts.popleft()
            _log.warning("device_link_unwritten", device=device, reason=reason)

    def _done(self, worker: asyncio.Task[None]) -> None:
        """Log a fault the worker met that nobody was left waiting to see."""
        if not worker.cancelled() and (fault := worker.exception()) is not None:
            _log.error(
                "device_link_unwritten",
                reason=str(fault),
                error_class=type(fault).__name__,
            )
            self._unwritten("an earlier write failed; the next start follows the record")

    async def _replay(self) -> None:
        """Write each act's link in the order the acts were made."""
        async with self._writing:
            while self._acts:
                device, admitted = self._acts.popleft()
                try:
                    await self._settle(device, admitted=admitted)
                except (IdentityStoreError, ValueError) as exc:
                    _log.warning(
                        "device_link_unwritten",
                        device=device,
                        reason=str(exc),
                        error_class=type(exc).__name__,
                    )

    async def _settle(self, device: str, *, admitted: bool) -> None:
        """Link ``device`` where the act left it admitted; end its link where not.

        A standing ``device`` link recorded from an admission that has since ended — its
        revocation's write failed, and the device was admitted again — is ended before
        the device is linked anew, so the new admission never stands on the old link.
        """
        account = _account(device)
        held = await self._identities.find_link(account)
        # Only the owner's ``device`` link is the record's to end: a ``configured`` one is
        # the configuration's (L1), and every device link this records is the owner's.
        own = (
            held is not None
            and held.act.how is LinkActHow.DEVICE
            and held.person_id == OWNER_PERSON_ID
        )
        if held is not None and own and (not admitted or self._outlived(held)):
            await self._end(held.id, account)
        if admitted:
            await self._link(device)

    def _outlived(self, held: Link) -> bool:
        """Whether a ``device`` link was recorded before its device's current admission.

        Such a link stood on an admission the owner has since revoked, so its act no
        longer stands (ADR-0373 §6:3), whatever admits the device now: a later act
        naming the account makes a new link (ADR-0366 §3). Read from the record, which
        keeps every revocation, so a start repairs a revocation whose write failed.
        """
        since = self._registry.admitted_since(held.account.identifier)
        return since is not None and held.made_at < since

    async def _link(self, device: str) -> bool:
        """Tie ``device``'s account to the owner by the ``device`` act.

        Returns:
            Whether a link was made: ``False`` where one already stood, or the store
            refused, which is logged.
        """
        written = await self._identities.link(OWNER_PERSON_ID, _account(device), act=_DEVICE_ACT)
        if written.kind is LinkWriteKind.REFUSED:
            _log.warning(
                "device_link_refused",
                device=device,
                refusal=None if written.refusal is None else written.refusal.value,
            )
        elif written.kind is LinkWriteKind.WRITTEN:
            _log.info("device_linked", device=device, link_id=written.record_id)
        return written.kind is LinkWriteKind.WRITTEN

    async def _end(self, link_id: str, account: Account) -> bool:
        """End a ``device`` link, and hand its account back to the configuration's act.

        Where the owner's configuration names the account, as when the web door's hosted
        device was set to a device already linked by its admission, the account is
        linked again by the ``configured`` act it still stands on, so ending the device's
        act leaves it linked as the store's opening links every configured account.

        Returns:
            Whether the link was ended by this call.
        """
        written = await self._identities.end_link(link_id)
        if written.kind is not LinkWriteKind.WRITTEN:
            return False
        _log.info("device_link_ended", device=account.identifier, link_id=link_id)
        if account in self._configured:
            await self._identities.link(OWNER_PERSON_ID, account, act=_CONFIGURED_ACT)
        return True
