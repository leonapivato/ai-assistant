"""The shared conformance suite for ``ConnectionProvisioner`` (ADR-0151 §16).

Every implementation of
:class:`~ai_assistant.core.protocols.ConnectionProvisioner` must pass this suite
(``CONTRIBUTING.md`` -> "Protocol conformance suites"). A concrete test subclasses
it and supplies the subject fixture and the four hooks below.

**What the hooks exist for.** Most of what ADR-0151 §7 rules is about a *partial*
act — a credential written and never activated, a predecessor slot that would not
delete — and none of it is reachable through the Protocol's own five members,
because the Protocol has no way to make a keyring fail. So the suite asks the
**subject** it was handed, never the seam every consumer depends on: three hooks
arm a keyring failure, count what the keyring holds, and script the reference
factory to repeat.

**What is deliberately *not* asserted here, and why the line falls where it
does.**

* **The identity refusals** ADR-0149 §4 and ADR-0151 §5 require. ADR-0151 §10
  states that no member of this Protocol declares
  :class:`~ai_assistant.core.errors.UnusableIdentityError`, because §5 refuses
  such a call "locally, before any I/O" in every implementation of the *engine*
  operation — the wire client included — "so no such call arrives". A provisioner
  that refused here would raise an undeclared failure. Those cases belong to the
  ``AssistantEngine`` suite (ADR-0151 §16 item 2).
* **The three displacement points** ADR-0148 §6 names, and the crash windows
  either side of each write. Reaching them means interleaving a competing act
  *inside* an act, which is a fact about how a given implementation suspends
  rather than about the contract; ADR-0149 §14 and ADR-0151 §16 put them on the
  lane that owns the code, and they live beside the production subject.
* **The frame floor.** ADR-0151 §16's frame clauses are stated against the *wire*
  implementation, and nothing is serialised across this seam.

Named ``*_contract`` (not ``test_*``) so pytest collects these only via a
``Test``-prefixed subclass, never the abstract base directly.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

import pytest
from pydantic import SecretStr

from ai_assistant.core.errors import (
    ConnectionStoreError,
    IncompleteProvisioningError,
    ResidualCredentialError,
    UnknownConnectionError,
)
from ai_assistant.core.types import (
    ACCOUNT_IDENTITY_MAX_BYTES,
    ConnectedAccount,
    ConnectionAct,
    ProvisioningState,
)
from ai_assistant.testing import SecretMethod

if TYPE_CHECKING:
    from ai_assistant.core.protocols import ConnectionProvisioner
    from ai_assistant.core.types import SecretValue
    from ai_assistant.testing.cancellation import SuspendedCall

#: The account identity most cases use. Ordinary, so a case that cares about the
#: shape of an identity says so by using something else.
IDENTITY = "owner@example.com"

__all__ = ["IDENTITY", "ConnectionProvisionerContract", "credential"]


def credential(plaintext: str = "hunter2") -> SecretValue:
    """A credential, in the redacting holder ADR-0125 §3 puts one in."""
    return SecretStr(plaintext)


class ConnectionProvisionerContract(ABC):
    """What every ``ConnectionProvisioner`` must do (ADR-0148 §6, ADR-0149, ADR-0151)."""

    @pytest.fixture
    @abstractmethod
    def provisioner(self) -> ConnectionProvisioner:
        """The subject, holding no connection and an empty keyring."""

    # --- the hooks a narrow Protocol cannot supply ---------------------------

    @abstractmethod
    def keyring_entries(self, provisioner: ConnectionProvisioner) -> int:
        """How many credentials the subject's keyring holds."""

    @abstractmethod
    def fail_next(self, provisioner: ConnectionProvisioner, method: SecretMethod) -> None:
        """Arm the subject's keyring to fail its next call to ``method``."""

    @abstractmethod
    def repeat_next_reference(self, provisioner: ConnectionProvisioner) -> None:
        """Script the subject's reference factory to repeat its last value."""

    @abstractmethod
    def mint_an_unusable_reference(self, provisioner: ConnectionProvisioner) -> None:
        """Script the subject's factory to mint a reference past ADR-0151 §11's bound."""

    @abstractmethod
    def suspend_next_credential_write(self, provisioner: ConnectionProvisioner) -> SuspendedCall:
        """Hold the subject's next credential write open."""

    # --- ADR-0148 §6: a completed act ---------------------------------------

    async def test_a_fresh_connection_is_active_at_its_first_revision(
        self, provisioner: ConnectionProvisioner
    ) -> None:
        """ADR-0151 §7: an act returns only once the third write has landed."""
        record = await provisioner.provision(identity=IDENTITY, credential=credential())

        assert record.state is ProvisioningState.ACTIVE
        assert record.revision == 1
        assert record.identity == IDENTITY
        assert self.keyring_entries(provisioner) == 1

    async def test_each_connection_takes_its_own_minted_reference(
        self, provisioner: ConnectionProvisioner
    ) -> None:
        """ADR-0151 §3: the reference is minted, and a caller supplies none.

        Two connections to the *same* account is a state ADR-0148 §6 permits and
        nothing prevents, so the references cannot be derived from the identity.
        """
        first = await provisioner.provision(identity=IDENTITY, credential=credential())
        second = await provisioner.provision(identity=IDENTITY, credential=credential())

        assert first.reference != second.reference

    async def test_the_identity_is_returned_byte_for_byte(
        self, provisioner: ConnectionProvisioner
    ) -> None:
        """ADR-0149 §4: nothing strips, case-folds or normalises an identity.

        Both cases ADR-0151 §16 names — one with leading and trailing whitespace,
        and one differing from another only by case — because a normaliser
        typically defeats exactly one of them.
        """
        padded = await provisioner.provision(identity="  Owner  ", credential=credential())
        lowered = await provisioner.provision(identity="owner", credential=credential())

        assert padded.identity == "  Owner  "
        assert lowered.identity == "owner"

    async def test_a_repeated_minted_reference_is_refused(
        self, provisioner: ConnectionProvisioner
    ) -> None:
        """ADR-0151 §3: the store refuses an append introducing a reference it holds.

        The half of the uniqueness guarantee a store can establish by itself; the
        other half is the factory's, and §3 states it as a rule on the factory
        rather than as something a test could observe.
        """
        first = await provisioner.provision(identity=IDENTITY, credential=credential())
        self.repeat_next_reference(provisioner)

        with pytest.raises(ConnectionStoreError):
            await provisioner.provision(identity="second", credential=credential())

        live = await provisioner.connected()
        assert [record.identity for record in live] == [IDENTITY]
        assert live[0].reference == first.reference

    async def test_a_reference_the_caller_could_never_receive_is_refused(
        self, provisioner: ConnectionProvisioner
    ) -> None:
        """ADR-0151 §11: no minted reference exceeds CONNECTION_REFERENCE_MAX_BYTES.

        The bound's ceiling is fixed by §11 rather than left to a lane, and the
        asymmetry with the identity's bound is the mint: an oversized identity
        refuses the request the caller sent and the caller can send a shorter one,
        while an oversized reference refuses a **response** carrying a value that
        exists only in the hub — so the act would have landed with its handle
        unreachable, recoverable only by matching on an identity nothing makes
        unique. Refused before the first write, so nothing is written.
        """
        self.mint_an_unusable_reference(provisioner)

        with pytest.raises(ConnectionStoreError):
            await provisioner.provision(identity=IDENTITY, credential=credential())

        assert await provisioner.connected() == ()
        assert await provisioner.recent_acts(limit=10) == ()
        assert self.keyring_entries(provisioner) == 0

    @pytest.mark.parametrize(
        "identity",
        [
            pytest.param("owner\nadmin", id="line-break"),
            pytest.param("owner\u2028admin", id="unicode-line-separator"),
            pytest.param("owner\x07", id="control-character"),
            pytest.param("o" * (ACCOUNT_IDENTITY_MAX_BYTES + 1), id="over-the-bound"),
        ],
    )
    async def test_the_store_refuses_an_identity_outside_its_shape(
        self, provisioner: ConnectionProvisioner, identity: str
    ) -> None:
        """ADR-0149 §4: bounded, single-line printable text, enforced by the store.

        §4 puts the length bound "and the store enforces" in as many words, and
        ADR-0151 §17 records that fixing the bound's *location* in ``core`` left
        the enforcement exactly where §4 had it: "a lane holding only ADR-0149 §4
        sets a bound and enforces it in the store, which stays exactly what they
        must do".

        So this is the second of two refusals rather than a duplicate of one. The
        engine's is the one a person sees, raised locally with nothing sent
        (ADR-0151 §5) — and it is not this Protocol's, because §10 states that no
        member here declares
        :class:`~ai_assistant.core.errors.UnusableIdentityError`. What the seam
        owes is that a record outside §4's shape never becomes durable state,
        whatever reached it.

        The Unicode line separator is parametrised beside the newline because a
        rule written over ``"\n"`` passes it while ``str.splitlines`` and a
        terminal both treat it as a line break.
        """
        with pytest.raises(ConnectionStoreError):
            await provisioner.provision(identity=identity, credential=credential())

        assert await provisioner.connected() == ()
        assert await provisioner.recent_acts(limit=10) == ()

    # --- ADR-0148 §6: re-provisioning ---------------------------------------

    async def test_re_provisioning_an_unheld_reference_is_refused(
        self, provisioner: ConnectionProvisioner
    ) -> None:
        """ADR-0151 §2a: an unknown reference is the one refusal reprovision adds."""
        with pytest.raises(UnknownConnectionError):
            await provisioner.reprovision(
                "not-a-reference", identity=IDENTITY, credential=credential()
            )

        assert await provisioner.connected() == ()

    async def test_re_provisioning_takes_the_next_revision(
        self, provisioner: ConnectionProvisioner
    ) -> None:
        """ADR-0148 §6: every act increments the revision, identity unchanged or not."""
        first = await provisioner.provision(identity=IDENTITY, credential=credential())

        second = await provisioner.reprovision(
            first.reference, identity=IDENTITY, credential=credential("rotated")
        )

        assert second.reference == first.reference
        assert second.revision == first.revision + 1
        assert second.state is ProvisioningState.ACTIVE

    async def test_re_provisioning_deletes_the_predecessors_credential(
        self, provisioner: ConnectionProvisioner
    ) -> None:
        """ADR-0148 §6: the predecessor's slot goes once the activation has landed."""
        first = await provisioner.provision(identity=IDENTITY, credential=credential())

        await provisioner.reprovision(
            first.reference, identity=IDENTITY, credential=credential("rotated")
        )

        assert self.keyring_entries(provisioner) == 1

    async def test_a_disconnected_reference_re_provisions_above_every_revision_it_held(
        self, provisioner: ConnectionProvisioner
    ) -> None:
        """ADR-0149 §5: a disconnection never resets the revision.

        The ABA sequence ADR-0148 §6's revision exists to refuse, arriving through
        the one act §6 did not enumerate: a store that dropped history with the
        record would restart this at revision 1.
        """
        first = await provisioner.provision(identity=IDENTITY, credential=credential())
        await provisioner.disconnect(first.reference)

        again = await provisioner.reprovision(
            first.reference, identity=IDENTITY, credential=credential("again")
        )

        assert again.revision > first.revision + 1

    # --- ADR-0149 §5: disconnection -----------------------------------------

    async def test_disconnecting_returns_the_record_it_removed(
        self, provisioner: ConnectionProvisioner
    ) -> None:
        """ADR-0151 §8: the live record as it stood before the removal was appended."""
        record = await provisioner.provision(identity=IDENTITY, credential=credential())

        removed = await provisioner.disconnect(record.reference)

        assert removed == record
        assert await provisioner.connected() == ()

    async def test_disconnecting_an_unheld_reference_writes_nothing(
        self, provisioner: ConnectionProvisioner
    ) -> None:
        """ADR-0149 §5: a typo leaves no tombstone and creates no revision sequence."""
        assert await provisioner.disconnect("not-a-reference") is None

        assert await provisioner.recent_acts(limit=10) == ()

    async def test_disconnecting_twice_removes_nothing_the_second_time(
        self, provisioner: ConnectionProvisioner
    ) -> None:
        """ADR-0149 §5: the act is idempotent, and a ``None`` is not a report of one."""
        record = await provisioner.provision(identity=IDENTITY, credential=credential())
        await provisioner.disconnect(record.reference)

        assert await provisioner.disconnect(record.reference) is None

        acts = await provisioner.recent_acts(limit=10)
        assert [act.account is None for act in acts] == [True, False]

    async def test_disconnecting_deletes_every_slot_the_reference_named(
        self, provisioner: ConnectionProvisioner
    ) -> None:
        """ADR-0149 §5: every distinct slot below the removal's revision, not just one.

        Reached through a re-provisioning whose predecessor deletion failed, which
        is how two slots for one reference exist at all. An implementation that
        deletes only the live record's slot leaves one behind here.
        """
        record = await provisioner.provision(identity=IDENTITY, credential=credential())
        self.fail_next(provisioner, SecretMethod.DELETE)
        with pytest.raises(ResidualCredentialError):
            await provisioner.reprovision(
                record.reference, identity=IDENTITY, credential=credential("rotated")
            )
        assert self.keyring_entries(provisioner) == 2

        await provisioner.disconnect(record.reference)

        assert self.keyring_entries(provisioner) == 0

    # --- ADR-0151 §7: the partial outcomes ----------------------------------

    async def test_a_credential_write_failure_leaves_the_reference_pending(
        self, provisioner: ConnectionProvisioner
    ) -> None:
        """ADR-0151 §7: the reference exists, and this act did not complete.

        And ADR-0151 §2a's conversion: a keyring failure becomes the class that
        says what the *act* did, never the raw ``SecretStoreError``, which says
        the keyring failed and nothing about which write had landed.
        """
        self.fail_next(provisioner, SecretMethod.SET)

        with pytest.raises(IncompleteProvisioningError) as caught:
            await provisioner.provision(identity=IDENTITY, credential=credential())

        live = await provisioner.connected()
        assert [record.reference for record in live] == [caught.value.reference]
        assert live[0].state is ProvisioningState.PENDING

    async def test_a_predecessor_deletion_failure_reports_the_new_revision_as_active(
        self, provisioner: ConnectionProvisioner
    ) -> None:
        """ADR-0151 §7: the act **completed**; an old credential could not be deleted.

        The case ADR-0151 §16 calls "the case that distinguishes a mapping from a
        rule about ordering" — ADR-0148 §6's predecessor deletion runs *after* the
        activation, so a client deriving the outcome from the write order would
        report a live connection as pending and rotate a working credential.
        """
        record = await provisioner.provision(identity=IDENTITY, credential=credential())
        self.fail_next(provisioner, SecretMethod.DELETE)

        with pytest.raises(ResidualCredentialError) as caught:
            await provisioner.reprovision(
                record.reference, identity=IDENTITY, credential=credential("rotated")
            )

        assert caught.value.reference == record.reference
        live = await provisioner.connected()
        assert live[0].state is ProvisioningState.ACTIVE
        assert live[0].revision == record.revision + 1

    async def test_a_disconnection_deletion_failure_leaves_the_reference_disconnected(
        self, provisioner: ConnectionProvisioner
    ) -> None:
        """ADR-0151 §8: the removal landed; the deletion did not. Never a failure to disconnect."""
        record = await provisioner.provision(identity=IDENTITY, credential=credential())
        self.fail_next(provisioner, SecretMethod.DELETE)

        with pytest.raises(ResidualCredentialError) as caught:
            await provisioner.disconnect(record.reference)

        assert caught.value.reference == record.reference
        assert await provisioner.connected() == ()

    # --- ADR-0151 §7: cancellation is not a failure --------------------------

    async def test_a_cancelled_act_propagates_rather_than_being_converted(
        self, provisioner: ConnectionProvisioner
    ) -> None:
        """ADR-0151 §7: "a `CancelledError` is not one [a failure]".

        A cancellation at any point of a provisioning act propagates unconverted —
        ADR-0060's rule that external cancellation is re-raised is neither relaxed
        nor satisfied by a report — and no implementation turns one into
        :class:`~ai_assistant.core.errors.ProvisioningOutcomeUnknownError` or into
        any other class on this surface. The act leaves the same outcome those
        classes describe, and the caller says so under the unread-outcome clause
        **without** the reference and without starting a call to obtain one, which
        is why this case asserts nothing about what the store then holds.

        It is the case a suite testing only failures never reaches.
        """
        held = self.suspend_next_credential_write(provisioner)
        task = asyncio.ensure_future(
            provisioner.provision(identity=IDENTITY, credential=credential())
        )
        await held.reached()

        task.cancel()
        held.release()
        with pytest.raises(asyncio.CancelledError):
            await task

    # --- ADR-0151 §9: the two listings --------------------------------------

    async def test_connected_reports_every_reference_that_has_a_live_record(
        self, provisioner: ConnectionProvisioner
    ) -> None:
        """ADR-0151 §9: the complete set, from the store's live records alone."""
        first = await provisioner.provision(identity="one", credential=credential())
        second = await provisioner.provision(identity="two", credential=credential())
        await provisioner.provision(identity="three", credential=credential())
        await provisioner.disconnect(second.reference)

        live = await provisioner.connected()

        assert {record.identity for record in live} == {"one", "three"}
        assert first.reference in {record.reference for record in live}

    async def test_recent_acts_reports_one_row_per_act(
        self, provisioner: ConnectionProvisioner
    ) -> None:
        """ADR-0151 §9: one row per ``(reference, revision)``, newest first.

        The store's entry granularity is `tools/`-internal, so an implementation
        writing the record twice per act still owes one row.
        """
        record = await provisioner.provision(identity=IDENTITY, credential=credential())
        await provisioner.reprovision(
            record.reference, identity=IDENTITY, credential=credential("rotated")
        )

        acts = await provisioner.recent_acts(limit=10)

        assert [(act.reference, act.revision) for act in acts] == [
            (record.reference, 2),
            (record.reference, 1),
        ]

    async def test_recent_acts_marks_a_removal_by_an_absent_record(
        self, provisioner: ConnectionProvisioner
    ) -> None:
        """ADR-0151 §4: ``account`` is ``None`` exactly when the act was a disconnection."""
        record = await provisioner.provision(identity=IDENTITY, credential=credential())
        await provisioner.disconnect(record.reference)

        acts = await provisioner.recent_acts(limit=10)

        assert acts[0].account is None
        assert acts[1].account is not None
        assert acts[1].account.reference == acts[1].reference
        assert acts[1].account.revision == acts[1].revision

    async def test_recent_acts_is_bounded_by_the_limit(
        self, provisioner: ConnectionProvisioner
    ) -> None:
        """ADR-0151 §9: bounded by ``limit``, which is why it cannot state liveness."""
        for name in ("one", "two", "three"):
            await provisioner.provision(identity=name, credential=credential())

        acts = await provisioner.recent_acts(limit=2)

        assert len(acts) == 2

    # --- ADR-0149 §10: what may not cross ------------------------------------

    def test_no_result_type_carries_a_credential_or_a_secret_name(self) -> None:
        """ADR-0149 §10: no credential value and no ``SecretName`` in a return type.

        Asserted over the promoted models rather than over one call's result,
        because the prohibition is about the *shape* a caller can ever receive: a
        field added later would satisfy every value-level assertion on the day it
        landed.
        """
        assert set(ConnectedAccount.model_fields) == {
            "reference",
            "identity",
            "revision",
            "state",
        }
        assert set(ConnectionAct.model_fields) == {"reference", "revision", "account"}
