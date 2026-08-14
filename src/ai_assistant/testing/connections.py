"""The canonical in-memory fake for ADR-0151's and ADR-0153's two Protocols.

One class, :class:`FakeConnectionProvisioner`, implementing
:class:`~ai_assistant.core.protocols.ConnectionProvisioner` and
:class:`~ai_assistant.core.protocols.ConnectionPurger` structurally — which is
ADR-0153 §2's shape rather than a convenience: the two faces are **disjoint**,
neither contains the other, and "one implementation satisfies both faces with one
method" for :meth:`FakeConnectionProvisioner.connected`. :data:`FakeConnectionPurger`
is that same class under the narrow face's name, for the reason recorded on it.

**It performs ADR-0148 §6's three writes rather than short-cutting them**, over an
in-memory append-only list and a :class:`~ai_assistant.testing.secrets.FakeSecretStore`
bound to :attr:`~ai_assistant.core.types.SecretScope.INTEGRATION`. A fake that set
a dictionary entry and returned would pass every listing obligation in the shared
suite while exhibiting none of the ordering the suite exists to hold an
implementation to — and the interesting obligations are all about what a *partial*
act leaves.

**It is written independently of the production provisioner and imports none of
it.** A canonical fake that delegated to the implementation under test would make
the shared conformance suite a tautology; the point of the suite is that two
implementations built from the contract agree.

ADR-0060's cancellation clause **has bite** for this subject, and
:meth:`FakeConnectionProvisioner.suspend_next_deletion` is the lever ADR-0153 §8's
resource obligation needs — "only a subject the suite drives can be held still long
enough to observe" whether a cancelled ``purge`` left something still using the
store. ADR-0065's input-observation clause is **vacuous** here: every argument is a
string, an integer or a redacting holder over a string, so there is no caller-owned
container for a result to be torn across.

Test-only, and no composition root wires it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, final
from uuid import uuid4

from ai_assistant.core.errors import (
    ConnectionStoreError,
    DisplacedProvisioningError,
    IncompleteProvisioningError,
    ResidualCredentialError,
    SecretStoreError,
    UnknownConnectionError,
)
from ai_assistant.core.types import (
    ConnectedAccount,
    ConnectionAct,
    ProvisioningState,
    SecretName,
    SecretScope,
)
from ai_assistant.testing.cancellation import SuspendableResource
from ai_assistant.testing.secrets import FakeSecretStore

if TYPE_CHECKING:
    from collections.abc import Callable

    from ai_assistant.core.types import NonBlankEncodableText, SecretValue
    from ai_assistant.testing.cancellation import LoopSuspension, ResourceLog

#: The prefix the fake's slot factory uses. Mirrors the production one so a test
#: reading a keyring's coordinates sees the same shape from either subject.
SLOT_PREFIX: Final = "connection."


@final
@dataclass(frozen=True, slots=True)
class FakeConnectionEntry:
    """One append to the fake's connection log (ADR-0148 §6, ADR-0149 §5).

    A provisioning entry carries the identity, the state and this act's own slot;
    a **removal entry** carries none of the three, which is what says the
    reference has no live record — and not a third
    :class:`~ai_assistant.core.types.ProvisioningState`, which ADR-0149 §5 forbids.

    Attributes:
        reference: The connection this entry is about.
        revision: ADR-0148 §6's monotonic revision.
        identity: The account identity, verbatim, or ``None`` on a removal.
        state: How far the act had got, or ``None`` on a removal.
        slot: The credential slot the act wrote to, or ``None`` on a removal.
    """

    reference: str
    revision: int
    identity: str | None
    state: ProvisioningState | None
    slot: SecretName | None

    def account(self) -> ConnectedAccount | None:
        """This entry as the promoted record, or ``None`` for a removal."""
        if self.identity is None or self.state is None:
            return None
        return ConnectedAccount(
            reference=self.reference,
            identity=self.identity,
            revision=self.revision,
            state=self.state,
        )


@final
@dataclass(frozen=True, slots=True)
class _FakeAct:
    """What differs between a provisioning act and a re-provisioning one.

    Attributes:
        reference: The connection being written.
        revision: The revision this act takes.
        predecessor: The slot this act's predecessor named, or ``None``.
        displaceable: Whether another act can hold this reference.
    """

    reference: str
    revision: int
    predecessor: SecretName | None
    displaceable: bool


@final
class FakeConnectionProvisioner:
    """A non-persistent provisioner and purger over an in-memory append-only log.

    Structurally implements :class:`~ai_assistant.core.protocols.ConnectionProvisioner`
    and :class:`~ai_assistant.core.protocols.ConnectionPurger`, which is why both
    conformance suites are bound against this one class.

    **The log is append-only, exactly as ADR-0149 §3 requires of the real store**,
    and the compare-and-swap is stated over it the same way: an act appends only if
    the entry it observed is still the reference's latest. The list index is the
    swap token, which is what an in-memory subject has instead of a rowid.

    Three explicit switches, all test-only and none part of any contract:
    :meth:`repeat_next_reference` scripts the mint to repeat, so a suite can prove
    the store refuses a reference it already holds (ADR-0151 §3); the keyring's own
    :meth:`~ai_assistant.testing.secrets.FakeSecretStore.fail` and
    :meth:`~ai_assistant.testing.secrets.FakeSecretStore.become_unavailable` are
    reached through :attr:`secrets`; and :meth:`suspend_next_deletion` holds a purge
    open inside a deletion so ADR-0153 §8's cancellation obligation is observable.

    Test-only, and no composition root wires it.

    Attributes:
        entries: The whole append-only log, oldest first. Test-only, and the
            **negative control** several obligations need: an assertion that a
            refused act "wrote nothing" is worth nothing unless a test can see the
            log it did not write to.
    """

    def __init__(
        self,
        *,
        secrets: FakeSecretStore | None = None,
        mint_reference: Callable[[], str] | None = None,
        mint_slot: Callable[[], str] | None = None,
    ) -> None:
        """Create an empty provisioner over its own keyring.

        Args:
            secrets: The ``INTEGRATION``-scoped keyring face. Omit it for one of
                this subject's own, which is what lets a binding class supply the
                fake through a fixture taking nothing but ``self``.
            mint_reference: The reference factory (ADR-0151 §3). Defaults to a
                version 4 UUID, which is one of the two forms §3 names — never a
                counter, because a counter restarts in a fresh process and re-mints
                a reference the store still holds.
            mint_slot: The credential-slot factory, one draw per act (ADR-0148 §6).
        """
        self.entries: list[FakeConnectionEntry] = []
        self.secrets = (
            secrets if secrets is not None else FakeSecretStore(scope=SecretScope.INTEGRATION)
        )
        self._mint_reference = mint_reference if mint_reference is not None else _reference
        self._mint_slot = mint_slot if mint_slot is not None else _slot
        self._repeat_reference: str | None = None
        self._last_reference: str | None = None
        self._resource = SuspendableResource()

    def __repr__(self) -> str:
        """Describe the subject by its size, never by an identity it holds.

        An account identity is Tier 1 personal data (ADR-0149 §3), so a generated
        ``repr`` over ``self.__dict__`` would put one wherever a failing assertion
        prints the subject.
        """
        return f"{type(self).__name__}(entries={len(self.entries)})"

    # --- the test-only switches ----------------------------------------------

    def repeat_next_reference(self) -> None:
        """Make the next mint repeat the value the previous one produced.

        ADR-0151 §3 splits the uniqueness guarantee: the factory mints from a
        source no fresh process resumes, and the **store** refuses an append that
        would introduce a reference it already holds. This switch is how a suite
        exercises the second half, which is the only one an implementation can be
        held to.

        A no-op until one reference has been minted, because there is nothing to
        repeat before then.
        """
        self._repeat_reference = self._last_reference

    def suspend_next_deletion(self) -> LoopSuspension:
        """Hold the next credential deletion open, for ADR-0153 §8's cancellation case.

        Returns:
            The suspension, which the suite waits on and then releases.
        """
        return self._resource.suspend_next()

    @property
    def resource_log(self) -> ResourceLog:
        """What the suspendable resource saw, so a suite can prove no overlap."""
        return self._resource.log

    # --- ConnectionProvisioner ------------------------------------------------

    async def provision(
        self, *, identity: NonBlankEncodableText, credential: SecretValue
    ) -> ConnectedAccount:
        """Connect a fresh account under a reference this subject mints."""
        reference = self._next_reference()
        if any(entry.reference == reference for entry in self.entries):
            msg = (
                "the connection log already holds the reference this act minted, so "
                "nothing was written; the factory repeated a value it must not repeat"
            )
            raise ConnectionStoreError(msg)
        return await self._act(
            _FakeAct(reference=reference, revision=1, predecessor=None, displaceable=False),
            identity=identity,
            credential=credential,
        )

    async def reprovision(
        self,
        reference: str,
        *,
        identity: NonBlankEncodableText,
        credential: SecretValue,
    ) -> ConnectedAccount:
        """Replace the credential under an existing reference."""
        latest = self._latest(reference)
        if latest is None:
            msg = (
                f"connection {reference!r} is not recorded, so there is nothing to "
                f"re-provision; read what is connected and act on a reference from there"
            )
            raise UnknownConnectionError(msg)
        return await self._act(
            _FakeAct(
                reference=reference,
                revision=self.entries[latest].revision + 1,
                predecessor=self.entries[latest].slot,
                displaceable=True,
            ),
            identity=identity,
            credential=credential,
        )

    async def _act(
        self, plan: _FakeAct, *, identity: str, credential: SecretValue
    ) -> ConnectedAccount:
        """Perform ADR-0148 §6's three writes in its order, over the in-memory log."""
        reference, revision = plan.reference, plan.revision
        slot = SecretName(scope=SecretScope.INTEGRATION, key=self._mint_slot())
        self.entries.append(
            FakeConnectionEntry(reference, revision, identity, ProvisioningState.PENDING, slot)
        )
        filed = len(self.entries) - 1

        # ADR-0148 §6: re-read before the credential write.
        self._still_ours(reference, filed, displaceable=plan.displaceable)
        try:
            await self.secrets.set(slot, credential)
        except SecretStoreError as exc:
            msg = (
                f"the credential for connection {reference!r} could not be written, so the "
                f"act did not complete; re-provision it or disconnect it"
            )
            raise IncompleteProvisioningError(msg, reference) from exc

        # ADR-0148 §6: re-read again, then the activation's own compare-and-swap.
        # The re-read is not what makes the activation safe; the swap is.
        self._still_ours(reference, filed, displaceable=plan.displaceable)
        if self._latest(reference) != filed:
            raise self._displaced(reference, displaceable=plan.displaceable)
        self.entries.append(
            FakeConnectionEntry(reference, revision, identity, ProvisioningState.ACTIVE, slot)
        )

        # ADR-0148 §6: the predecessor's slot goes once the activation has landed.
        if plan.predecessor is not None:
            try:
                await self.secrets.delete(plan.predecessor)
            except SecretStoreError as exc:
                msg = (
                    f"connection {reference!r} is connected at revision {revision}; the "
                    f"credential it replaced could not be deleted and remains unreferenced"
                )
                raise ResidualCredentialError(msg, reference) from exc
        return ConnectedAccount(
            reference=reference,
            identity=identity,
            revision=revision,
            state=ProvisioningState.ACTIVE,
        )

    async def disconnect(self, reference: str) -> ConnectedAccount | None:
        """Remove a reference's live record and delete its credentials."""
        latest = self._latest(reference)
        if latest is None:
            return None
        entry = self.entries[latest]
        if entry.state is None:
            # Already removed: no second removal entry, and the deletion pass
            # repeats at the latest removal's revision (ADR-0149 §5).
            removed, cutoff = None, entry.revision
        else:
            removed, cutoff = entry, entry.revision + 1
            self.entries.append(FakeConnectionEntry(reference, cutoff, None, None, None))

        failure: SecretStoreError | None = None
        for slot in self._slots(reference=reference, below=cutoff):
            try:
                await self.secrets.delete(slot)
            except SecretStoreError as exc:
                failure = failure if failure is not None else exc
        if failure is not None:
            msg = (
                f"connection {reference!r} is disconnected; at least one of its credentials "
                f"could not be deleted and remains unreferenced. Run the disconnection again"
            )
            raise ResidualCredentialError(msg, reference) from failure
        return None if removed is None else removed.account()

    async def connected(self) -> tuple[ConnectedAccount, ...]:
        """The live record for every reference that has one, in first-seen order."""
        live: dict[str, FakeConnectionEntry] = {}
        for entry in self.entries:
            live[entry.reference] = entry
        return tuple(record for entry in live.values() if (record := entry.account()) is not None)

    async def recent_acts(self, *, limit: int) -> tuple[ConnectionAct, ...]:
        """Up to ``limit`` acts, newest first, one row per ``(reference, revision)``."""
        furthest: dict[tuple[str, int], FakeConnectionEntry] = {}
        for entry in self.entries:
            furthest[entry.reference, entry.revision] = entry
        acts = [
            ConnectionAct(
                reference=entry.reference, revision=entry.revision, account=entry.account()
            )
            for entry in furthest.values()
        ]
        acts.reverse()
        return tuple(acts[:limit])

    # --- ConnectionPurger -----------------------------------------------------

    async def purge(self) -> None:
        """Delete every credential the log names, then the entries (ADR-0149 §8)."""
        for slot in self._slots():
            async with self._resource.held():
                await self.secrets.delete(slot)
        self.entries.clear()

    # --- the log's own reads --------------------------------------------------

    def _latest(self, reference: str) -> int | None:
        """The index of the reference's latest entry, or ``None``."""
        for index in range(len(self.entries) - 1, -1, -1):
            if self.entries[index].reference == reference:
                return index
        return None

    def _still_ours(self, reference: str, filed: int, *, displaceable: bool) -> None:
        """Abandon unless the reference's latest entry is still this act's own."""
        if self._latest(reference) != filed:
            raise self._displaced(reference, displaceable=displaceable)

    def _displaced(
        self, reference: str, *, displaceable: bool
    ) -> DisplacedProvisioningError | IncompleteProvisioningError:
        """The failure for a record this act no longer holds (ADR-0151 §7)."""
        if displaceable:
            msg = (
                f"another act took connection {reference!r} over, so nothing this act wrote "
                f"is live; read what is connected and decide whether to run it again"
            )
            return DisplacedProvisioningError(msg)
        msg = (
            f"connection {reference!r} is no longer the record this act wrote, so the act "
            f"did not complete; re-provision it or disconnect it"
        )
        return IncompleteProvisioningError(msg, reference)

    def _slots(
        self, *, reference: str | None = None, below: int | None = None
    ) -> tuple[SecretName, ...]:
        """Every distinct slot the log names, optionally narrowed and bounded.

        With no arguments this is ADR-0149 §8's purge set. With both it is
        ADR-0149 §5's deletion set: every distinct slot named by an entry for that
        reference whose revision is **strictly below** the removal's — a slot at or
        above belongs to an act the disconnection did not displace.
        """
        seen: dict[tuple[str, str], SecretName] = {}
        for entry in self.entries:
            if entry.slot is None:
                continue
            if reference is not None and entry.reference != reference:
                continue
            if below is not None and entry.revision >= below:
                continue
            seen.setdefault((entry.slot.scope.value, entry.slot.key), entry.slot)
        return tuple(seen.values())

    def _next_reference(self) -> str:
        """Draw the next reference, honouring :meth:`repeat_next_reference`."""
        if self._repeat_reference is not None:
            repeated, self._repeat_reference = self._repeat_reference, None
            return repeated
        self._last_reference = self._mint_reference()
        return self._last_reference


def _reference() -> str:
    """Draw a version 4 UUID as a connection reference (ADR-0151 §3)."""
    return str(uuid4())


def _slot() -> str:
    """Draw a credential slot key inside ADR-0125 §2's grammar."""
    return f"{SLOT_PREFIX}{uuid4().hex}"


#: The canonical fake for :class:`~ai_assistant.core.protocols.ConnectionPurger`,
#: which is :class:`FakeConnectionProvisioner` under the narrow face's name.
#:
#: **One class, two names, and that is ADR-0153 §2's decision rather than a
#: shortcut around it.** §2 rules that the primary production implementation of
#: ``ConnectionPurger`` *is* the connection provisioner, that one implementation
#: satisfies both faces with one ``connected``, and that "no lane gives them
#: divergent behaviour". A second fake here would be a second implementation with
#: exactly the drift that clause forbids. What forces the *name* is
#: ``tests/core/test_protocol_triad.py``, which requires a ``Fake<Protocol>``
#: exported from this package for every Protocol in ``core/protocols.py`` — so the
#: name has to exist even though the object behind it does not have to be new.
#: :data:`~ai_assistant.testing.secrets.FakeSecrets` is the same arrangement for
#: the same reason.
FakeConnectionPurger = FakeConnectionProvisioner

__all__ = [
    "SLOT_PREFIX",
    "FakeConnectionEntry",
    "FakeConnectionProvisioner",
    "FakeConnectionPurger",
]
