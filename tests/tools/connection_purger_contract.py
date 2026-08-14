"""The shared conformance suite for ``ConnectionPurger`` (ADR-0153 §8).

Every implementation of :class:`~ai_assistant.core.protocols.ConnectionPurger`
must pass this suite. ADR-0153 §8 names what it proves, "at minimum", and the
naming is normative there: this module's cases are that list, one case per clause,
and the docstrings quote it.

**The seeding hooks exist because the face is narrow on purpose.**
``ConnectionPurger`` carries no member that writes, which is the whole of ADR-0153
§2's argument for it — so a suite cannot arrange a store that names slots through
the Protocol under test. It asks the *subject* instead, which in production and in
the fake is the same object under its wide face.

**What is deliberately *not* asserted here.** ADR-0153 §8's second clause puts the
act-side obligations — that a raising ``purge`` is followed by no destruction, that
the store is closed before the first destruction, that a cancellation is not routed
through ``classify`` — on the routing lane, "because a suite binds implementations
of ``ConnectionPurger`` and cannot reach the act". An implementation whose ``purge``
raised and which then destroyed ``data_dir`` anyway would pass every obligation
here while producing exactly the unrepairable state ADR-0153 exists to prevent.

Named ``*_contract`` (not ``test_*``) so pytest collects these only via a
``Test``-prefixed subclass, never the abstract base directly.
"""

from __future__ import annotations

import asyncio
import contextlib
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

import pytest

from ai_assistant.core.errors import SecretStoreError
from ai_assistant.core.protocols import ConnectionPurger
from ai_assistant.core.types import ConnectedAccount

if TYPE_CHECKING:
    from ai_assistant.testing.cancellation import SuspendedCall

__all__ = ["ConnectionPurgerContract"]


class ConnectionPurgerContract(ABC):
    """What every ``ConnectionPurger`` must do (ADR-0149 §8, ADR-0153 §2, §8)."""

    @pytest.fixture
    @abstractmethod
    def purger(self) -> ConnectionPurger:
        """The subject, holding no connection and an empty keyring."""

    # --- the hooks the narrow face cannot supply -----------------------------

    @abstractmethod
    async def connect(self, purger: ConnectionPurger, identity: str) -> str:
        """Connect an account through the subject's wide face, returning its reference."""

    @abstractmethod
    async def reprovision(self, purger: ConnectionPurger, reference: str) -> None:
        """Re-provision ``reference``, so the store names a superseded slot too."""

    @abstractmethod
    async def disconnect(self, purger: ConnectionPurger, reference: str) -> None:
        """Disconnect ``reference``, so the store holds a removal entry."""

    @abstractmethod
    def keyring_entries(self, purger: ConnectionPurger) -> int:
        """How many credentials the subject's keyring holds."""

    @abstractmethod
    def entry_count(self, purger: ConnectionPurger) -> int:
        """How many entries the subject's connection store holds."""

    @abstractmethod
    def fail_next_deletion(self, purger: ConnectionPurger) -> None:
        """Arm the subject's keyring to fail its next deletion."""

    @abstractmethod
    def keyring_becomes_unreachable(self, purger: ConnectionPurger) -> None:
        """Put the subject's keyring into ADR-0125 §7's unavailable state."""

    @abstractmethod
    def suspend_next_deletion(self, purger: ConnectionPurger) -> SuspendedCall:
        """Hold the subject's next credential deletion open."""

    # --- ADR-0153 §2: the face itself ---------------------------------------

    def test_conforms_to_the_purger_protocol(self, purger: ConnectionPurger) -> None:
        """ADR-0153 §2: the decorator is stated as a decision, and this is why.

        Without ``@runtime_checkable`` this obligation would not fail — it would
        *error*, because ``isinstance`` against a bare ``Protocol`` raises
        ``TypeError`` rather than answering.
        """
        assert isinstance(purger, ConnectionPurger)

    async def test_connected_returns_every_live_record_and_no_removal(
        self, purger: ConnectionPurger
    ) -> None:
        """ADR-0153 §8: every live record, and no reference whose latest entry is a removal.

        The same question ``ConnectionProvisioner.connected`` answers, with the
        same semantics — ADR-0153 §2 forbids the two faces divergent behaviour, so
        this is the one method serving both.
        """
        first = await self.connect(purger, "one")
        second = await self.connect(purger, "two")
        await self.disconnect(purger, second)

        live = await purger.connected()

        assert [record.reference for record in live] == [first]
        assert all(isinstance(record, ConnectedAccount) for record in live)

    # --- ADR-0149 §8: what the purge deletes and in what order --------------

    async def test_a_purge_over_a_store_naming_no_slot_touches_no_keyring(
        self, purger: ConnectionPurger
    ) -> None:
        """ADR-0153 §4: an installation that never connected runs this act unchanged.

        Proved by making the keyring unreachable first: ADR-0125 §7's state raises
        on any call that gets past the argument step, so a purge that completes
        here is one that made none. That is what keeps a headless box — one with
        no keyring at all — able to discharge the owner's delete right.
        """
        self.keyring_becomes_unreachable(purger)

        await purger.purge()

        assert self.entry_count(purger) == 0

    async def test_a_purge_deletes_every_distinct_slot_then_the_entries(
        self, purger: ConnectionPurger
    ) -> None:
        """ADR-0153 §8: including a superseded slot and a removed one, then the entries.

        A superseded slot exists because a re-provisioning whose predecessor
        deletion failed left one; a removed reference's slot exists because its
        disconnection's deletion pass failed. Both are unreferenced credentials the
        store still names, and ADR-0149 §8's first clause is what puts them inside
        the purge rather than outside it.
        """
        superseded = await self.connect(purger, "one")
        self.fail_next_deletion(purger)
        with contextlib.suppress(Exception):
            await self.reprovision(purger, superseded)
        removed = await self.connect(purger, "two")
        self.fail_next_deletion(purger)
        with contextlib.suppress(Exception):
            await self.disconnect(purger, removed)
        assert self.keyring_entries(purger) == 3

        await purger.purge()

        assert self.keyring_entries(purger) == 0
        assert self.entry_count(purger) == 0

    async def test_a_deletion_that_raises_leaves_every_entry_in_place(
        self, purger: ConnectionPurger
    ) -> None:
        """ADR-0149 §8: a partial purge is a failed purge, and the entries stay.

        "Slots before the store" is satisfied by a purge that attempts every slot,
        has one deletion raise, and destroys the store anyway — which leaves a
        credential with no remaining durable name. The completeness clause is what
        closes that, and this case is what holds an implementation to it.
        """
        await self.connect(purger, "one")
        before = self.entry_count(purger)
        self.fail_next_deletion(purger)

        with pytest.raises(SecretStoreError):
            await purger.purge()

        assert self.entry_count(purger) == before

    async def test_a_purge_re_run_after_a_failure_completes(self, purger: ConnectionPurger) -> None:
        """ADR-0149 §8: idempotent — a re-run deletes what remains.

        Idempotence is what makes refusing whole cheap: the owner clears the
        keyring condition and runs the command again, and every already-deleted
        slot costs one ``delete`` that raises nothing (ADR-0125 §4).
        """
        await self.connect(purger, "one")
        await self.connect(purger, "two")
        self.fail_next_deletion(purger)
        with pytest.raises(SecretStoreError):
            await purger.purge()

        await purger.purge()

        assert self.keyring_entries(purger) == 0
        assert self.entry_count(purger) == 0

    async def test_a_purge_after_a_purge_does_nothing_and_raises_nothing(
        self, purger: ConnectionPurger
    ) -> None:
        """ADR-0153 §8: a second call after a success does nothing and raises nothing."""
        await self.connect(purger, "one")
        await purger.purge()

        await purger.purge()

        assert self.entry_count(purger) == 0
        assert self.keyring_entries(purger) == 0

    # --- ADR-0060: the resource half ----------------------------------------

    async def test_a_cancelled_purge_leaves_every_entry_and_propagates(
        self, purger: ConnectionPurger
    ) -> None:
        """ADR-0153 §8: a cancellation during a deletion is not a failed purge.

        Three things at once, which is why the clause names them together: every
        connection-store entry stays in place, so the re-run deletes the
        remainder; whatever the subject acquired has been released or completed by
        the moment the ``CancelledError`` leaves it (ADR-0060's resource half); and
        the ``CancelledError`` propagates rather than being converted into a purge
        failure.
        """
        await self.connect(purger, "one")
        before = self.entry_count(purger)
        held = self.suspend_next_deletion(purger)
        task = asyncio.ensure_future(purger.purge())
        await held.reached()

        task.cancel()
        held.release()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert self.entry_count(purger) == before

    # --- ADR-0149 §10: what may not cross ------------------------------------

    async def test_no_return_value_carries_a_credential_or_a_slot(
        self, purger: ConnectionPurger
    ) -> None:
        """ADR-0153 §2: no credential value, ``SecretName`` or slot in a return value.

        ``purge`` returns nothing at all — there is no success value, because
        ADR-0149 §8's third clause rules that a partial purge is a failed purge and
        no value distinguishes a lesser outcome.
        """
        await self.connect(purger, "one")

        live = await purger.connected()

        assert set(ConnectedAccount.model_fields) == {
            "reference",
            "identity",
            "revision",
            "state",
        }
        assert live
        assert all(isinstance(record, ConnectedAccount) for record in live)
