"""A canonical :class:`~ai_assistant.core.protocols.IdentityStore` fake (ADR-0366 §2, §3).

The shared test double for the hub's identities and their links, so the lanes that
decide who sent an input from a link, and those that list and lower links, can exercise
links, lowerings and a store that fails without a file. It keeps everything in memory
and follows the contract's every rule, so a consumer's test sees what the store would do.

**It holds the owner from the start** (§2:5): built, it holds the one identity
:data:`~ai_assistant.core.types.OWNER_PERSON_ID`, created at its clock's first reading,
and links each configured account to it by the owner's ``configured`` act, in the order
given, as the store does when it opens. :meth:`FakeIdentityStore.reopen` follows a new
configuration as the store does when it is opened again: it ends each configured link
whose account is no longer named, and links each one newly named.

**It mints each record's id once**: an id ``new_id`` mints that a link or a lowering the
store holds already carries is a store fault, raised before anything changes.

**What only a test can ask of it.** :meth:`FakeIdentityStore.fail_next` makes the next
member called raise :class:`~ai_assistant.core.errors.IdentityStoreError` before it
reads or writes anything, as a store fault would. :meth:`FakeIdentityStore.hold_identity`
gives it a second identity, which no member of the contract adds before a later decision
provides for one (§1:3, §2:4), so that a test can reach the rules that name someone other
than the owner: who may lower a link and who may withdraw a lowering (§5:5).

Every member runs to its end without awaiting, so on one event loop each is one
indivisible step, which is the exclusion the contract asks of it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from itertools import count
from typing import TYPE_CHECKING, Final, final

from pydantic import BaseModel, ValidationError

from ai_assistant.core.channel_validation import most_sureness
from ai_assistant.core.clock import ClockReadingError, checked_clock
from ai_assistant.core.errors import IdentityStoreError
from ai_assistant.core.types import (
    OWNER_PERSON_ID,
    Account,
    Identity,
    IdentityExport,
    Link,
    LinkAct,
    LinkActHow,
    LinkRefusal,
    LinkWrite,
    LinkWriteKind,
    Lowering,
    Sureness,
    describe_untrusted,
    encodable_text,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

__all__ = ["FakeIdentityStore"]

#: The act every configured account is linked by: the owner's own configuration.
_CONFIGURED: Final = LinkAct(how=LinkActHow.CONFIGURED, by=OWNER_PERSON_ID)


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _refused(refusal: LinkRefusal) -> LinkWrite:
    return LinkWrite(kind=LinkWriteKind.REFUSED, refusal=refusal)


def _checked(value: object, *, name: str) -> str:
    """A non-blank ``str`` with a UTF-8 encoding, or a ``ValueError`` before anything is read."""
    if not isinstance(value, str) or not value.strip():
        msg = f"{name} must be a non-blank str, got {describe_untrusted(value)}"
        raise ValueError(msg)
    try:
        return encodable_text(value)
    except ValueError as exc:
        msg = f"{name} must be text with a UTF-8 encoding"
        raise ValueError(msg) from exc


def _validated[M: BaseModel](value: object, kind: type[M], *, name: str) -> M:
    """``value`` as a ``kind`` whose every field passes validation, or a ``ValueError``.

    An instance is not proof of its own validity: ``model_copy(update=…)`` and
    ``model_construct`` skip validation, so the instance's contents are validated again.
    """
    if not isinstance(value, kind):
        msg = f"{name} must be a {kind.__name__}, got {describe_untrusted(value)}"
        raise ValueError(msg)
    try:
        return kind.model_validate(value.model_dump())
    except ValidationError as exc:
        msg = f"{name} is not a valid {kind.__name__}"
        raise ValueError(msg) from exc


def _level(value: object) -> Sureness:
    """``value`` where it is a level, or a ``ValueError`` before anything is read."""
    if not isinstance(value, Sureness):
        msg = f"level must be a Sureness, got {describe_untrusted(value)}"
        raise ValueError(msg)
    return value


def _configured(configured: Sequence[Account]) -> tuple[Account, ...]:
    return tuple(_validated(one, Account, name="a configured account") for one in configured)


@final
class FakeIdentityStore:
    """An in-memory identity store holding the owner (ADR-0366 §2:5, §3, §5:5)."""

    def __init__(
        self,
        *,
        configured: Sequence[Account] = (),
        now: Callable[[], datetime] = _utcnow,
        new_id: Callable[[str], str] | None = None,
    ) -> None:
        """Build the store as opened: the owner, with each configured account linked.

        Args:
            configured: The accounts the owner's configuration names, each linked to the
                owner by a ``configured`` act of the owner's, in the order given; one
                named twice is linked once.
            now: The clock every instant the store records is read from.
            new_id: Mints a record's id from its kind (``link`` or ``lowering``);
                sequential per kind where ``None``. An id it mints that a held record
                carries is refused as a store fault.

        Raises:
            ValueError: If an entry of ``configured`` is not a valid ``Account``.
            IdentityStoreError: If a clock reading is not an aware instant, or an id is
                minted twice, as the store's opening would fail.
        """
        accounts = _configured(configured)
        # ADR-0026 §2: every reading aware and converted to UTC, checked where it is read.
        self._clock = checked_clock(now, owner="FakeIdentityStore")
        numbers: dict[str, count[int]] = {}
        self._new_id = new_id or (lambda kind: f"{kind}:{next(numbers.setdefault(kind, count(1)))}")
        self._identities: dict[str, datetime] = {OWNER_PERSON_ID: self._now()}
        self._links: dict[str, Link] = {}
        self._fail = False
        self._follow(accounts)

    def _now(self) -> datetime:
        """One reading of the clock, taken before the write it dates changes anything.

        Raises:
            IdentityStoreError: If the reading is not an aware instant (ADR-0026 §4).
        """
        try:
            return self._clock()
        except ClockReadingError as exc:
            msg = f"the identity store cannot record its clock's reading: {exc}"
            raise IdentityStoreError(msg) from exc

    def fail_next(self) -> None:
        """Make the next member called raise ``IdentityStoreError``, touching nothing."""
        self._fail = True

    def hold_identity(self, person_id: str) -> None:
        """Hold a second identity, for a test of a rule naming someone but the owner.

        No member of the contract adds an identity (ADR-0366 §1:3, §2:4); this stands in
        for the later decision that will, so a test can reach §5:5's refusals.

        Args:
            person_id: The identity's id; one already held is left as it is.

        Raises:
            ValueError: If ``person_id`` is not a non-blank ``str``.
            IdentityStoreError: If the clock's reading is not an aware instant.
        """
        person = _checked(person_id, name="person_id")
        if person not in self._identities:
            self._identities[person] = self._now()

    def reopen(self, *, configured: Sequence[Account] = ()) -> None:
        """Follow ``configured`` as the store does when it is opened again, in one step.

        Args:
            configured: The accounts the owner's configuration names now.

        Raises:
            ValueError: If an entry of ``configured`` is not a valid ``Account``.
            IdentityStoreError: If a clock reading is not an aware instant, or an id is
                minted twice; nothing is changed.
        """
        accounts = _configured(configured)
        before = dict(self._links)
        try:
            self._follow(accounts)
        except BaseException:
            self._links = before
            raise

    def _follow(self, accounts: tuple[Account, ...]) -> None:
        """End the configured links ``accounts`` no longer names; link those no link holds."""
        at: datetime | None = None
        for link in list(self._links.values()):
            ended = link.act.how is LinkActHow.CONFIGURED and link.account not in accounts
            if link.standing and ended:
                at = at or self._now()
                self._links[link.id] = link.model_copy(update={"ended_at": at})
        for account in accounts:
            if self._standing_link(account) is None:
                self._add_link(OWNER_PERSON_ID, account, _CONFIGURED)

    def _fault(self) -> None:
        if self._fail:
            self._fail = False
            msg = "the fake identity store was told to fail"
            raise IdentityStoreError(msg)

    def _mint(self, kind: str) -> str:
        """A new record's id, never one a held link or lowering carries.

        Raises:
            IdentityStoreError: If the id minted is one a held record already carries.
        """
        minted = self._new_id(kind)
        held = {
            *self._links,
            *(lowering.id for link in self._links.values() for lowering in link.lowerings),
        }
        if minted in held:
            msg = f"the identity store minted an id a record already carries: {kind}"
            raise IdentityStoreError(msg)
        return minted

    def _standing_link(self, account: Account) -> Link | None:
        return next(
            (one for one in self._links.values() if one.standing and one.account == account),
            None,
        )

    def _add_link(self, person_id: str, account: Account, act: LinkAct) -> str:
        # Minted and read before anything held changes, so a fault changes nothing.
        link_id = self._mint("link")
        made = Link(id=link_id, person_id=person_id, account=account, act=act, made_at=self._now())
        self._links[link_id] = made
        return link_id

    def _lowering(self, lowering_id: str) -> tuple[Link, Lowering] | None:
        for link in self._links.values():
            for lowering in link.lowerings:
                if lowering.id == lowering_id:
                    return link, lowering
        return None

    # --- reads ------------------------------------------------------------------------

    async def identity(self, person_id: str) -> Identity | None:
        """Read one identity, with every link and lowering (ADR-0366 §2:1, §5:5)."""
        person = _checked(person_id, name="person_id")
        self._fault()
        created = self._identities.get(person)
        if created is None:
            return None
        links = tuple(one for one in self._links.values() if one.person_id == person)
        return Identity(id=person, created_at=created, links=links)

    async def find_link(self, account: Account) -> Link | None:
        """Find the standing link ``account`` is tied to (ADR-0366 §4:1)."""
        checked = _validated(account, Account, name="account")
        self._fault()
        return self._standing_link(checked)

    async def export(self) -> IdentityExport:
        """Every record held (ADR-0004 §6)."""
        self._fault()
        return IdentityExport(
            identities=tuple(
                Identity(
                    id=person,
                    created_at=created,
                    links=tuple(one for one in self._links.values() if one.person_id == person),
                )
                for person, created in self._identities.items()
            )
        )

    # --- writes -----------------------------------------------------------------------

    async def link(self, person_id: str, account: Account, *, act: LinkAct) -> LinkWrite:
        """Tie ``account`` to ``person_id``'s identity from ``act`` (ADR-0366 §3:1)."""
        person = _checked(person_id, name="person_id")
        checked = _validated(account, Account, name="account")
        made_by = _validated(act, LinkAct, name="act")
        self._fault()
        if person not in self._identities or made_by.by not in self._identities:
            return _refused(LinkRefusal.UNKNOWN_PERSON)
        held = self._standing_link(checked)
        if held is not None:
            if held.person_id != person:
                return _refused(LinkRefusal.ALREADY_LINKED)
            return LinkWrite(kind=LinkWriteKind.UNCHANGED, record_id=held.id)
        return LinkWrite(
            kind=LinkWriteKind.WRITTEN, record_id=self._add_link(person, checked, made_by)
        )

    async def end_link(self, link_id: str) -> LinkWrite:
        """End a link whose act no longer stands, keeping it (ADR-0366 §3)."""
        held_id = _checked(link_id, name="link_id")
        self._fault()
        link = self._links.get(held_id)
        if link is None:
            return _refused(LinkRefusal.UNKNOWN_RECORD)
        if not link.standing:
            return LinkWrite(kind=LinkWriteKind.UNCHANGED, record_id=held_id)
        self._links[held_id] = link.model_copy(update={"ended_at": self._now()})
        return LinkWrite(kind=LinkWriteKind.WRITTEN, record_id=held_id)

    async def lower(self, link_id: str, level: Sureness, *, by: str) -> LinkWrite:
        """Lower a standing link's level, by the owner or its person (ADR-0366 §5:5)."""
        held_id = _checked(link_id, name="link_id")
        lowered = _level(level)
        maker = _checked(by, name="by")
        self._fault()
        link = self._links.get(held_id)
        if link is None or not link.standing:
            return _refused(LinkRefusal.UNKNOWN_RECORD)
        if maker not in self._identities:
            return _refused(LinkRefusal.UNKNOWN_PERSON)
        if maker not in {OWNER_PERSON_ID, link.person_id}:
            return _refused(LinkRefusal.NOT_ALLOWED)
        same = next(
            (one for one in link.standing_lowerings if (one.by, one.level) == (maker, lowered)),
            None,
        )
        if same is not None:
            return LinkWrite(kind=LinkWriteKind.UNCHANGED, record_id=same.id)
        if lowered >= most_sureness(link.account.kind):
            return _refused(LinkRefusal.NOT_A_LOWERING)
        lowering = Lowering(id=self._mint("lowering"), level=lowered, by=maker, made_at=self._now())
        self._links[held_id] = link.model_copy(update={"lowerings": (*link.lowerings, lowering)})
        return LinkWrite(kind=LinkWriteKind.WRITTEN, record_id=lowering.id)

    async def withdraw_lowering(self, lowering_id: str, *, by: str) -> LinkWrite:
        """Withdraw a lowering, by its maker alone (ADR-0366 §5:5)."""
        held_id = _checked(lowering_id, name="lowering_id")
        maker = _checked(by, name="by")
        self._fault()
        found = self._lowering(held_id)
        if found is None:
            return _refused(LinkRefusal.UNKNOWN_RECORD)
        if maker not in self._identities:
            return _refused(LinkRefusal.UNKNOWN_PERSON)
        link, lowering = found
        if maker != lowering.by:
            return _refused(LinkRefusal.NOT_ALLOWED)
        if not lowering.standing:
            return LinkWrite(kind=LinkWriteKind.UNCHANGED, record_id=held_id)
        withdrawn = lowering.model_copy(update={"withdrawn_at": self._now()})
        lowerings = tuple(withdrawn if one.id == held_id else one for one in link.lowerings)
        self._links[link.id] = link.model_copy(update={"lowerings": lowerings})
        return LinkWrite(kind=LinkWriteKind.WRITTEN, record_id=held_id)
