"""The owner's linked accounts: the listing, a lowering and a withdrawal (ADR-0373 §2, §3).

``AssistantEngine``'s three members for links and levels, answered here over the
identity store (:class:`~ai_assistant.core.protocols.IdentityStore`), so the engine and
the canonical fake answer them alike. Neither reads the store for them itself.

**A link to the owner's identity is a standing one** (ADR-0373 §6:3): a link whose act
no longer stands ties nothing, so the listing leaves it out, a lowering of it is
``unknown_link`` (the store refuses it ``unknown_record`` as well), and a lowering on it
stands on no link, so withdrawing it is ``not_standing``. Everything the two writes can
name is something the listing shows.

**The order of ``lower_link``'s outcomes is ADR-0373 §2:4's.** This module decides the
first, ``unknown_link``, from one read of the owner's identity, and hands the rest to the
store's ``lower``, which decides ``unchanged`` and then ``not_a_lowering`` in that order
in one atomic step with its write. The store's own order puts its refusals that name a
person (``unknown_person``, ``not_allowed``) between the two, and neither can arise for
a lowering by the owner of the owner's own link: the owner's identity is the store's from
its creation (ADR-0366 §2:5), and the owner may lower any link (§5:5). A store answering
either is not the store the contract describes, and is raised as its fault. A link that
ends between the read and the write is refused ``unknown_record`` by the store, and is
``unknown_link`` here, as it would have been a moment later.

**The level each entry shows is computed here, on the hub** (§3:2), from the kind's
declared most as the running build declares it
(:func:`~ai_assistant.core.channel_validation.most_sureness`) and the standing lowerings
(ADR-0366 §5:3): :meth:`~ai_assistant.core.types.Link.level`.

**Every lowering these members make is the owner's** (§4:3): ``by`` is
:data:`~ai_assistant.core.types.OWNER_PERSON_ID`, which no caller supplies. **With no
identity store** the hub holds no link: the listing is empty, a lowering names an unknown
link and a withdrawal names no standing lowering, as the engine records every message as
arriving by no link where it has none.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ai_assistant.core.channel_validation import most_sureness
from ai_assistant.core.errors import IdentityStoreError
from ai_assistant.core.types import (
    OWNER_PERSON_ID,
    LinkedAccount,
    LinkRefusal,
    LinkWriteKind,
    LowerLinkOutcome,
    LowerLinkRefusal,
    LowerLinkResult,
    StandingLowering,
    WithdrawLoweringOutcome,
    WithdrawLoweringResult,
)

if TYPE_CHECKING:
    from ai_assistant.core.protocols import IdentityStore
    from ai_assistant.core.types import Link, LinkWrite, Sureness

__all__ = ["linked_accounts", "lower_link", "withdraw_lowering"]


def entry(link: Link) -> LinkedAccount:
    """One link as the listing shows it, its level computed here (ADR-0373 §3:1, §3:2).

    Args:
        link: The link, with its lowerings.

    Returns:
        Its entry: only its standing lowerings, and its level under ADR-0366 §5:3.
    """
    most = most_sureness(link.account.kind)
    return LinkedAccount(
        link_id=link.id,
        person_id=link.person_id,
        account=link.account,
        most=most,
        lowerings=tuple(_shown(one.id, one.level, one.by) for one in link.standing_lowerings),
        level=link.level(most),
    )


def _shown(lowering_id: str, level: Sureness, by: str) -> StandingLowering:
    return StandingLowering(id=lowering_id, level=level, by=by)


async def _owners_links(store: IdentityStore | None) -> tuple[Link, ...]:
    """Every standing link to the owner's identity, in the order made; none without a store."""
    if store is None:
        return ()
    owner = await store.identity(OWNER_PERSON_ID)
    return () if owner is None else owner.standing_links


async def linked_accounts(store: IdentityStore | None) -> tuple[LinkedAccount, ...]:
    """Every standing link to the owner's identity, one entry each (ADR-0373 §2:2, §3).

    Args:
        store: The identity store, or ``None`` where the hub holds none.

    Returns:
        The entries, in the order the links were made, which is no contractual order.

    Raises:
        IdentityStoreError: If the store cannot be read.
    """
    return tuple(entry(link) for link in await _owners_links(store))


async def _entry_after(store: IdentityStore, link_id: str) -> LinkedAccount:
    """The link's entry as it stands after an act on it, read again from the store.

    Read from every link the owner's identity holds, ended ones included: a link that
    ended in the moment after the act is shown as it then stands, not lost.

    Raises:
        IdentityStoreError: If the store cannot be read, or no longer holds the link or
            the owner's identity, which a store that keeps every link cannot do.
    """
    owner = await store.identity(OWNER_PERSON_ID)
    held = None if owner is None else next((one for one in owner.links if one.id == link_id), None)
    if held is None:
        msg = "the identity store no longer holds a link it has just acted on"
        raise IdentityStoreError(msg)
    return entry(held)


def _unexpected(write: LinkWrite, act: str) -> IdentityStoreError:
    """A store answer the contract rules out for the owner's act on the owner's link."""
    said = write.kind.value if write.refusal is None else f"refused {write.refusal.value}"
    return IdentityStoreError(f"the identity store answered {said} to the owner's {act}")


async def lower_link(store: IdentityStore | None, link_id: str, level: Sureness) -> LowerLinkResult:
    """Lower one of the owner's links to ``level``, by the owner's act (ADR-0373 §2:3, §2:4).

    The caller has validated both arguments.

    Args:
        store: The identity store, or ``None`` where the hub holds none.
        link_id: The link, by id.
        level: The level to lower it to.

    Returns:
        ``refused`` ``unknown_link``; ``unchanged`` with the standing lowering and the
        entry; ``refused`` ``not_a_lowering``; or ``lowered`` with the new lowering and
        the entry; in that order.

    Raises:
        IdentityStoreError: If the store cannot be read or written, or answers what its
            contract rules out for the owner's lowering of the owner's link.
    """
    unknown = LowerLinkResult(
        outcome=LowerLinkOutcome.REFUSED, refusal=LowerLinkRefusal.UNKNOWN_LINK
    )
    if store is None or not any(one.id == link_id for one in await _owners_links(store)):
        return unknown
    write = await store.lower(link_id, level, by=OWNER_PERSON_ID)
    if write.kind is LinkWriteKind.REFUSED:
        if write.refusal is LinkRefusal.UNKNOWN_RECORD:
            return unknown
        if write.refusal is LinkRefusal.NOT_A_LOWERING:
            return LowerLinkResult(
                outcome=LowerLinkOutcome.REFUSED, refusal=LowerLinkRefusal.NOT_A_LOWERING
            )
        raise _unexpected(write, "lowering")
    if write.record_id is None:
        raise _unexpected(write, "lowering")
    shown = await _entry_after(store, link_id)
    lowering = _shown(write.record_id, level, OWNER_PERSON_ID)
    outcome = (
        LowerLinkOutcome.LOWERED
        if write.kind is LinkWriteKind.WRITTEN
        else LowerLinkOutcome.UNCHANGED
    )
    return LowerLinkResult(outcome=outcome, lowering=lowering, entry=shown)


async def withdraw_lowering(
    store: IdentityStore | None, lowering_id: str
) -> WithdrawLoweringResult:
    """Withdraw a lowering standing on one of the owner's links (ADR-0373 §2:6).

    The caller has validated the argument. The withdrawal is the owner's (§4:3, §4:4).

    Args:
        store: The identity store, or ``None`` where the hub holds none.
        lowering_id: The lowering, by id.

    Returns:
        ``withdrawn`` with the link's entry after the act, or ``not_standing`` where no
        lowering standing on one of the owner's standing links has that id.

    Raises:
        IdentityStoreError: If the store cannot be read or written, or answers what its
            contract rules out for the owner's withdrawal of the owner's lowering.
    """
    not_standing = WithdrawLoweringResult(outcome=WithdrawLoweringOutcome.NOT_STANDING)
    on = next(
        (
            link.id
            for link in await _owners_links(store)
            if any(one.id == lowering_id for one in link.standing_lowerings)
        ),
        None,
    )
    if store is None or on is None:
        return not_standing
    write = await store.withdraw_lowering(lowering_id, by=OWNER_PERSON_ID)
    if write.kind is LinkWriteKind.UNCHANGED or write.refusal is LinkRefusal.UNKNOWN_RECORD:
        # Withdrawn, or gone, in the moment since the read: it no longer stands.
        return not_standing
    if write.kind is LinkWriteKind.REFUSED:
        raise _unexpected(write, "withdrawal")
    return WithdrawLoweringResult(
        outcome=WithdrawLoweringOutcome.WITHDRAWN, entry=await _entry_after(store, on)
    )
