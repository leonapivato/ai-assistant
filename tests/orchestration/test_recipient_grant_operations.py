"""The recipient-grant listings and the revocation (ADR-0235 §7).

What :class:`~ai_assistant.orchestration.recipient_grants.RecipientGrantOperations`
answers on its own: the two listings and the revocation. The establishing act on a
``CONFIRM`` no park holds, and the listing of what it could ride, left the engine
surface (ADR-0313 §5:1), and their cases with them.

**Nothing here is arranged through a lever the production path does not have.**
The store is seeded by recording grants, and the race cases fire through the
store seam the operation awaits —
which is what ADR-0235 §12 requires of them: "deterministic rather than
timing-dependent … and never by racing two tasks and hoping".
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Final

import pytest

from ai_assistant.core.errors import (
    InvalidRecipientGrantError,
    PlanningError,
)
from ai_assistant.core.types import (
    ActionRequest,
    CanonicalDestination,
    DestinationProtocol,
    RecipientGrant,
)
from ai_assistant.orchestration.recipient_grants import RecipientGrantOperations
from ai_assistant.testing import FakeRecipientGrantStore
from ai_assistant.testing.recipient_grants import (
    recipient_grant,
    recipient_revocation_of,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from ai_assistant.core.protocols import RecipientGrantStore

#: The recipient the cases here are arranged over.
ALICE: Final = "alice@example.com"

#: When a confirmation was asked.
AT: Final = datetime(2026, 7, 20, 12, 0, tzinfo=UTC)

#: The instant every act here is stamped at, and the one an expiry is compared
#: against. An hour after the confirmation, so the ordering the trail enforces
#: holds without a case having to arrange it.
_ANSWERED_AT: Final = AT + timedelta(hours=1)

#: An expiry comfortably after the answer, so a case not *about* the expiry never
#: brushes ADR-0235 §1's refusal.
EXPIRES: Final = AT + timedelta(days=1)


def member(canonical: str) -> CanonicalDestination:
    """One selected-recipient member of a canonical destination set."""
    return CanonicalDestination(protocol=DestinationProtocol.SMTP, canonical=canonical)


def _ids(prefix: str) -> Iterator[str]:
    """Ids that differ per call, so a second record is never a duplicate."""
    index = 0
    while True:
        index += 1
        yield f"{prefix}-{index}"


class _WrappedStore:
    """A ``RecipientGrantStore`` that delegates to the canonical fake, with one hook.

    **Composition rather than inheritance**, because
    :class:`~ai_assistant.testing.FakeRecipientGrantStore` is ``@final`` — the fake
    is the subject a conformance suite is bound to, and a subclass of it is a
    different implementation wearing its name. Structural typing is what makes a
    wrapper the right shape here: every member below forwards, and what a case
    varies is :meth:`before_record`.

    The arms that need one are the two ADR-0235 §12 states over a **refusal the
    operation cannot have caused** — a revoking ``record`` refusing while the grant
    still stands, and a competing revocation landing between the read and the write
    — neither of which the fake's own ``fail_writes`` lever can produce, since that
    one raises the base :class:`RecipientGrantError` by design.
    """

    def __init__(self, held: FakeRecipientGrantStore) -> None:
        """Wrap ``held``."""
        self.held = held

    async def before_record(self, grant: RecipientGrant) -> None:
        """Run before every append. Overridden by the cases that need a hook."""

    async def record(self, grant: RecipientGrant) -> str:
        """Run the hook, then append."""
        await self.before_record(grant)
        return await self.held.record(grant)

    async def covering(self, request: ActionRequest) -> RecipientGrant | None:
        """Forward."""
        return await self.held.covering(request)

    async def outstanding(self, grant_id: str) -> RecipientGrant | None:
        """Forward."""
        return await self.held.outstanding(grant_id)

    async def standing(self) -> list[RecipientGrant]:
        """Forward."""
        return await self.held.standing()

    async def recent(self, *, limit: int = 50) -> list[RecipientGrant]:
        """Forward."""
        return await self.held.recent(limit=limit)

    async def export(self) -> list[RecipientGrant]:
        """Forward."""
        return await self.held.export()

    async def clear(self) -> int:
        """Forward."""
        return await self.held.clear()


class _StoreRefusingRevocations(_WrappedStore):
    """A store that refuses a **revoking** record while the grant still stands."""

    async def before_record(self, grant: RecipientGrant) -> None:
        """Refuse a revocation, and admit a grant.

        Raises:
            InvalidRecipientGrantError: On a revoking record.
        """
        if grant.revokes is not None:
            msg = "the store refused this revoking record"
            raise InvalidRecipientGrantError(msg)


def _operations(*, store: RecipientGrantStore | None = None) -> RecipientGrantOperations:
    """The operations over the store, at one instant."""
    return RecipientGrantOperations(
        store=FakeRecipientGrantStore(now=lambda: _ANSWERED_AT) if store is None else store,
        id_factory=lambda: next(_MINTED),
        clock=lambda: _ANSWERED_AT,
    )


#: One id stream for the module, so every record a case makes carries a distinct id
#: without a case having to arrange one.
_MINTED = _ids("minted")


# --- §7: the two listings and the revocation ---------------------------------


async def test_the_standing_listing_states_liveness_and_the_log_does_not() -> None:
    """ADR-0235 §7: an expired grant is in the log and in no standing listing."""
    store = FakeRecipientGrantStore(now=lambda: EXPIRES + timedelta(days=2))
    expired = recipient_grant(member(ALICE), grant_id="g-expired")
    await store.record(expired)
    operations = _operations(store=store)

    assert await operations.standing_recipient_grants() == ()
    assert [record.id for record in await operations.recent_recipient_grants(limit=50)] == [
        "g-expired"
    ]


async def test_the_log_carries_revoking_records_too() -> None:
    """A revoking record is the record of an act, which is what it is (§7)."""
    store = FakeRecipientGrantStore(now=lambda: _ANSWERED_AT)
    granted = recipient_grant(member(ALICE), grant_id="g-1")
    await store.record(granted)
    await store.record(recipient_revocation_of(granted, grant_id="r-1"))
    operations = _operations(store=store)

    assert {record.id for record in await operations.recent_recipient_grants(limit=50)} == {
        "g-1",
        "r-1",
    }
    assert await operations.standing_recipient_grants() == ()


async def test_a_non_positive_log_limit_is_refused_locally() -> None:
    """``recent`` refuses a non-positive limit, and so does this (ADR-0235 §7)."""
    operations = _operations()

    with pytest.raises(ValueError, match="strictly positive"):
        await operations.recent_recipient_grants(limit=0)


async def test_revocation_appends_a_record_transcribing_the_grant() -> None:
    """The revoking record says what was withdrawn without a join (ADR-0193 §1)."""
    store = FakeRecipientGrantStore(now=lambda: _ANSWERED_AT)
    granted = recipient_grant(member(ALICE), grant_id="g-1")
    await store.record(granted)
    operations = _operations(store=store)

    revoked = await operations.revoke_recipient_grant("g-1")

    assert revoked is not None
    assert revoked.revokes == "g-1"
    assert revoked.tool == granted.tool
    assert revoked.account == granted.account
    assert revoked.destinations == granted.destinations
    assert await operations.standing_recipient_grants() == ()


async def test_revoking_an_absent_grant_answers_none() -> None:
    """The store held no outstanding record with that id, which is what ``None`` means."""
    operations = _operations()

    assert await operations.revoke_recipient_grant("g-absent") is None


async def test_a_lost_revocation_race_answers_none_and_appends_nothing() -> None:
    """ADR-0235 §12's concurrent-revocation pair, deterministic like §3's.

    A second revoking record for the same grant is appended **between** this
    operation's ``outstanding`` read and its write, through a store that performs the
    competing write from inside its own ``record``. The call returns ``None`` and
    raises nothing, the store holds exactly one revoking record for that grant, and
    the grant is absent from the standing listing.

    It fails against an implementation that let the loser's refusal reach a user
    performing ADR-0193 §1's stated recourse — the one act the ceiling makes users
    perform.
    """
    granted = recipient_grant(member(ALICE), grant_id="g-1")

    class _RacingStore(_WrappedStore):
        """A store that revokes ``granted`` itself, once, the moment it is armed."""

        armed = False

        async def before_record(self, grant: RecipientGrant) -> None:
            """Let the competitor in first, once."""
            if self.armed:
                self.armed = False
                await self.held.record(recipient_revocation_of(granted, grant_id="r-winner"))

    held = FakeRecipientGrantStore(now=lambda: _ANSWERED_AT)
    await held.record(granted)
    store = _RacingStore(held)
    operations = _operations(store=store)
    store.armed = True

    assert await operations.revoke_recipient_grant("g-1") is None

    revoking = [record for record in await held.export() if record.revokes == "g-1"]
    assert [record.id for record in revoking] == ["r-winner"]
    assert await operations.standing_recipient_grants() == ()


async def test_a_refusal_while_the_grant_still_stands_propagates() -> None:
    """The companion arm a roster would omit (ADR-0235 §12).

    An ``InvalidRecipientGrantError`` from a revoking ``record`` while the grant
    **is** still outstanding propagates unchanged. It fails against an implementation
    that converted the class rather than re-reading the store, which would report a
    fault as a completed revocation.
    """
    held = FakeRecipientGrantStore(now=lambda: _ANSWERED_AT)
    await held.record(recipient_grant(member(ALICE), grant_id="g-1"))
    operations = _operations(store=_StoreRefusingRevocations(held))

    with pytest.raises(InvalidRecipientGrantError):
        await operations.revoke_recipient_grant("g-1")

    assert await held.outstanding("g-1") is not None


# --- §4: detachment ----------------------------------------------------------


async def test_the_two_reads_return_detached_snapshots() -> None:
    """ADR-0235 §12's detachment arms, over both listings at once.

    A caller mutating a returned record through its ``__dict__`` — which
    ``frozen=True`` does not refuse — changes nothing a later call returns. Asserted
    on the two together because the failure is one bug in one place: a read that
    handed back the store's own object.
    """
    store = FakeRecipientGrantStore(now=lambda: _ANSWERED_AT)
    granted = recipient_grant(member(ALICE), grant_id="g-1")
    await store.record(granted)
    operations = _operations(store=store)

    standing = await operations.standing_recipient_grants()
    logged = await operations.recent_recipient_grants(limit=50)
    standing[0].__dict__["destinations"] = ()
    logged[0].__dict__["expires_at"] = AT

    assert (await operations.standing_recipient_grants())[0].destinations == granted.destinations
    assert (await operations.recent_recipient_grants(limit=50))[0].expires_at == granted.expires_at


# --- ADR-0026 §2, §4: the clock is guarded where it is stored ----------------


def _naive_clock() -> datetime:
    """A reading with its offset dropped, which is what ``checked_clock`` refuses."""
    return AT.replace(tzinfo=None)


async def test_a_non_conforming_clock_reading_is_the_stages_own_error() -> None:
    """ADR-0026 §2's guard and §4's translation, on the reading path left.

    §2 puts the wrap **where the clock is stored** — "a call site cannot forget" —
    and §4 gives the failure to the *stage*, because ``core/errors.py`` defines no
    error for `orchestration`. Without both, a naive reading is used silently — a
    revocation stamped at an instant nobody can locate. The revocation is the one
    operation here that reads a clock since the establishing act and its listing
    left the surface (ADR-0313 §5:1).
    """
    granted = recipient_grant(member(ALICE), grant_id="g-1")
    store = FakeRecipientGrantStore(now=lambda: _ANSWERED_AT)
    await store.record(granted)
    operations = RecipientGrantOperations(
        store=store,
        id_factory=lambda: next(_MINTED),
        clock=_naive_clock,
    )

    with pytest.raises(PlanningError, match="non-conforming reading"):
        await operations.revoke_recipient_grant("g-1")
