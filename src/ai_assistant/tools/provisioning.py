"""The one component that provisions a connection (ADR-0149 §1).

It performs ADR-0148 §6's three-write act, ADR-0149 §5's disconnection and
ADR-0149 §8's purge, over :mod:`ai_assistant.tools.connection_store` and an
``INTEGRATION``-scoped keyring face — and nothing else in this system does any of
them.

**It holds the only ``INTEGRATION``-scoped**
:class:`~ai_assistant.core.protocols.SecretStore` **in the system**, by injection
from the composition root, and it **calls ``set`` and ``delete`` and never calls
``get``** (ADR-0149 §1). It reads no credential value, and no credential value it
wrote is read back by it or returned by any operation it serves: ADR-0148 §7's
rule that an ``INTEGRATION`` credential is read only from inside a callable
reached by ``ToolInvoker.invoke`` is inherited exactly as written.

**It is not a tool.** No ``ToolDefinition`` binds it, it is never registered in a
``ToolRegistry``, it is not reachable through ``ToolInvoker.invoke``, no callable
holds a reference to it, and no plan step and no model-authored value reaches it
(ADR-0149 §1). Two of those are held mechanically rather than by this sentence —
`tools/` is a subsystem, subsystems never import `orchestration`, so nothing a
model or a plan steers can reach the engine methods that reach this.

**It performs no network I/O and launches no subprocess** (ADR-0149 §1): it opens
no socket, contacts no service to verify an identity or a credential, and reaches
no MCP server. Nothing here designates ADR-0017 §3's egress seam or relaxes any
of its conditions.

**It satisfies two disjoint Protocols with one object**, which is ADR-0153 §2's
shape: :class:`~ai_assistant.core.protocols.ConnectionProvisioner` for
`orchestration`, and :class:`~ai_assistant.core.protocols.ConnectionPurger` for
ADR-0126's offline delete act — the second carrying :meth:`purge`, which the
first must not have, and lacking the four members that write. A composition root
hands each consumer the face its job needs; what the offline tool cannot do is
*name* :meth:`provision`.

**It validates no account identity, and that absence is the contract.** ADR-0151
§5 refuses an unusable identity **locally, before any I/O**, in every
implementation of the engine operation — the wire client included — and ADR-0151
§10 states that no member of ``ConnectionProvisioner`` declares
:class:`~ai_assistant.core.errors.UnusableIdentityError` "so no such call
arrives". A defence-in-depth check here would raise a failure the seam does not
declare, which is the contract broken rather than tightened.

**Nothing here creates a connection from configuration** (ADR-0149 §4). There is
no path from a ``Settings`` value, an existing file, an upgrade, a migration, a
first run or a backup restore to a record: the only way an entry appears is a
caller invoking one of the two provisioning methods, and ADR-0151 §13 keeps those
reachable only by an explicit user act through a client.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final, final
from uuid import uuid4

from ai_assistant.core.errors import (
    ConnectionStoreError,
    DisplacedProvisioningError,
    IncompleteProvisioningError,
    ProvisioningOutcomeUnknownError,
    ResidualCredentialError,
    SecretStoreError,
    UnknownConnectionError,
)
from ai_assistant.core.types import (
    ConnectedAccount,
    ProvisioningState,
    SecretName,
    SecretScope,
)
from ai_assistant.tools.connection_store import ConnectionEntry, receivable

if TYPE_CHECKING:
    from collections.abc import Callable

    from ai_assistant.core.protocols import SecretStore
    from ai_assistant.core.types import (
        ConnectionAct,
        Identifier,
        NonBlankEncodableText,
        SecretValue,
    )
    from ai_assistant.tools.connection_store import SqliteConnectionStore, StoredEntry

#: The prefix every credential slot this component mints carries. Present so an
#: operator reading a keyring can tell which entries this system wrote; it is
#: **not** parsed by anything, because ADR-0125 §5 refuses enumeration and the
#: connection store is the only thing entitled to say which slots exist.
_SLOT_PREFIX: Final = "connection."

#: The most a failure message on this surface may encode to, in UTF-8 bytes.
#:
#: ADR-0151 §11 makes the lane size the message of **every error class on this
#: surface that carries a reference** so that the whole error payload — the code,
#: the message and the one ``details`` member — fits the payload budget
#: ``hub_max_frame_bytes`` leaves at its 1024-byte floor, which is 512 bytes
#: (ADR-0085 §8c, §8d). The arithmetic at that floor: the widest code is
#: ``ProvisioningOutcomeUnknownError``'s 31 bytes, a reference is at most
#: :data:`~ai_assistant.core.types.CONNECTION_REFERENCE_MAX_BYTES` (64), and the
#: envelope's four member names and JSON punctuation come to under 60 — so
#: 31 + 64 + 60 + 256 is 411 against a budget of 512, leaving a hundred bytes of
#: headroom and putting the reduction ADR-0085 §10a would perform out of reach.
#: That matters because the reduction **nulls ``details`` before it truncates a
#: message**, and on the two classes ``connect_account`` raises the reference is
#: the only handle the caller will ever have.
#:
#: **A message carries its own reference, so the bound is over the rendered
#: text** rather than over a template: ADR-0151 §2a has a refusal name the
#: reference the call carried, and a bound that excluded it would be measuring
#: the wrong string.
#:
#: Held by ``tests/tools/test_connection_provisioner.py`` rather than by a check
#: in this module: a bound enforced at the raise site would turn a report about a
#: failure into a second failure.
MESSAGE_MAX_BYTES: Final = 256


def _mint_reference() -> str:
    """Draw a fresh connection reference (ADR-0151 §3).

    **A version 4 UUID**, which is one of the two forms ADR-0151 §3 names: a
    source no fresh process resumes, "never a counter, a clock or a hash of a
    supplied value". A counter would restart at 1 in a new process and re-mint a
    reference the store still holds; a clock would do the same across a
    correction; and a hash of the identity would make two connections to one
    account collide, which ADR-0148 §6 permits and §3 does nothing to prevent.

    Its canonical hyphenated form is 36 bytes, inside
    :data:`~ai_assistant.core.types.CONNECTION_REFERENCE_MAX_BYTES` with room to
    spare.

    Returns:
        The reference, in its canonical form.
    """
    return str(uuid4())


def _mint_slot() -> str:
    """Draw a fresh credential slot key (ADR-0148 §6, ADR-0125 §2).

    **Per act, from its own draw, and never derived from the reference.** ADR-0148
    §6 requires that "a provisioning act writes its own slot, never a slot an
    earlier act wrote, and a slot is never written by two acts", and a key built
    out of the reference and the revision would inherit the reference's length —
    which a conforming factory may take up to
    :data:`~ai_assistant.core.types.CONNECTION_REFERENCE_MAX_BYTES`, past ADR-0125
    §2's 64-character key bound once a prefix and a revision are added. A draw of
    its own is 43 characters whatever the reference is.

    It is not derived from the credential either, which ADR-0125 §2 forbids in
    terms: a key is disclosable, so a caller may never encode a secret into one.

    Returns:
        A key inside ADR-0125 §2's grammar — lowercase hex and one ``.``.
    """
    return f"{_SLOT_PREFIX}{uuid4().hex}"


@final
class _Act:
    """What differs between a provisioning act and a re-provisioning one.

    ADR-0148 §6 gives the two one shape — "Provisioning **or re-provisioning** a
    connected account is three writes in a fixed order" — so
    :meth:`KeyringConnectionProvisioner._act` is one body, and these five values
    are the whole of what the two call sites disagree about. Bundled into a value
    rather than passed as five keyword arguments so that the shared body's
    signature stays readable and so that a call site cannot supply four of them.

    Attributes:
        reference: The connection being written.
        revision: The revision this act takes.
        observed: The entry this act observed as the reference's latest, or
            ``None`` to require that the store holds none for it — which is the
            mint's uniqueness refusal (ADR-0151 §3).
        predecessor: The slot this act's predecessor named, deleted once this
            act's activation has landed (ADR-0148 §6), or ``None`` where there is
            no live record to displace.
        displaceable: Whether another act can hold this reference. ``False`` only
            for a freshly minted one, where no other act can name it.
    """

    __slots__ = ("displaceable", "observed", "predecessor", "reference", "revision")

    def __init__(
        self,
        *,
        reference: str,
        revision: int,
        observed: StoredEntry | None,
        predecessor: SecretName | None,
        displaceable: bool,
    ) -> None:
        """Describe one act.

        Args:
            reference: The connection being written.
            revision: The revision this act takes.
            observed: The entry observed as the reference's latest, or ``None``.
            predecessor: The predecessor's slot, or ``None``.
            displaceable: Whether another act can hold this reference.
        """
        self.reference = reference
        self.revision = revision
        self.observed = observed
        self.predecessor = predecessor
        self.displaceable = displaceable


@final
class KeyringConnectionProvisioner:
    """The connection provisioner (ADR-0149 §1), over a store and a keyring face.

    Satisfies :class:`~ai_assistant.core.protocols.ConnectionProvisioner` and
    :class:`~ai_assistant.core.protocols.ConnectionPurger` structurally, with one
    :meth:`connected` serving both — ADR-0153 §2's "one implementation satisfies
    both faces with one method; no lane gives them divergent behaviour".

    **Every write ordering here is ratified rather than chosen**, and the module's
    tests are written against the crash windows each ordering leaves rather than
    against an atomicity nobody claims: ADR-0148 §6's three writes in a fixed
    order with the activation as the single live-deciding compare-and-swap;
    ADR-0149 §5's removal entry before its deletion pass; and ADR-0149 §8's slots
    before the store, with the entries removed only once every distinct slot has
    been confirmed deleted or confirmed absent.
    """

    def __init__(
        self,
        *,
        store: SqliteConnectionStore,
        secrets: SecretStore,
        mint_reference: Callable[[], str] = _mint_reference,
        mint_slot: Callable[[], str] = _mint_slot,
    ) -> None:
        """Wire the provisioner.

        Args:
            store: The connection store, opened by the composition root under
                ``Settings.data_dir`` and closed with the others it opens
                (ADR-0149 §3). A concrete class rather than a Protocol: its seam
                is `tools/`-internal, and ADR-0149 §3 adds no ``core`` Protocol
                for it.
            secrets: An ``INTEGRATION``-scoped keyring face, by injection. This is
                the only holder of one in the system (ADR-0149 §1), and it
                constructs none: `tools/` may not import
                :mod:`ai_assistant.secret_store` at all, which ``lint-imports``
                enforces.
            mint_reference: The reference factory (ADR-0151 §3). Injected so a
                test can script a repeated value and prove the store refuses the
                append — the half of the uniqueness guarantee a store can
                establish by itself.
            mint_slot: The credential-slot factory. Injected for the same reason
                and used once per act.
        """
        self._store = store
        self._secrets = secrets
        self._mint_reference = mint_reference
        self._mint_slot = mint_slot

    def __repr__(self) -> str:
        """Describe the provisioner by its store, never by what either holds."""
        return f"{type(self).__name__}(store={self._store!r})"

    # --- ConnectionProvisioner: the two provisioning acts ---------------------

    async def provision(
        self, *, identity: NonBlankEncodableText, credential: SecretValue
    ) -> ConnectedAccount:
        """Connect a fresh account under a reference this component mints.

        Raises:
            IncompleteProvisioningError: If the credential write failed, if either
                re-read failed, or if the activation did not land.
            ProvisioningOutcomeUnknownError: If the activation failed rather than
                returning.
            ConnectionStoreError: If the act's own first write did not return, or
                if the reference factory produced a value the store already holds
                or one a caller could never receive (:func:`receivable`). It names
                no reference, because nothing was written and ADR-0151 §7 permits
                no assertion about the act.
        """
        reference = receivable(self._mint_reference())
        return await self._act(
            _Act(
                reference=reference,
                revision=1,
                observed=None,
                predecessor=None,
                displaceable=False,
            ),
            identity=identity,
            credential=credential,
        )

    async def reprovision(
        self,
        reference: Identifier,
        *,
        identity: NonBlankEncodableText,
        credential: SecretValue,
    ) -> ConnectedAccount:
        """Replace the credential under an existing reference.

        Raises:
            UnknownConnectionError: If the store holds no entry for ``reference``.
            DisplacedProvisioningError: If another act took the record over.
            IncompleteProvisioningError: On :meth:`provision`'s terms.
            ProvisioningOutcomeUnknownError: On :meth:`provision`'s terms.
            ResidualCredentialError: If the predecessor-slot deletion failed after
                the activation landed. The act **completed**.
            ConnectionStoreError: If the act's own first write did not return.
        """
        observed = await self._store.latest(reference)
        if observed is None:
            msg = (
                f"connection {reference!r} is not recorded, so there is nothing to "
                f"re-provision; read what is connected and act on a reference from there"
            )
            raise UnknownConnectionError(msg)
        return await self._act(
            _Act(
                reference=reference,
                # Strictly greater than every revision this reference has ever
                # held, because the store is append-only and its latest entry
                # therefore carries the highest one — which is what makes
                # ADR-0149 §5's "a disconnection does not reset the revision"
                # true by construction rather than by a counter anyone has to
                # remember to keep.
                revision=observed.entry.revision + 1,
                observed=observed,
                # ``None`` where the latest entry is a removal: there is no live
                # record, so this act displaces nothing and has no predecessor
                # slot to delete (ADR-0148 §6).
                predecessor=observed.entry.slot,
                displaceable=True,
            ),
            identity=identity,
            credential=credential,
        )

    async def _act(
        self, plan: _Act, *, identity: NonBlankEncodableText, credential: SecretValue
    ) -> ConnectedAccount:
        """Perform ADR-0148 §6's three writes, in its order, and classify by §7's two facts.

        One body for both operations because ADR-0148 §6 gives them one shape —
        "Provisioning **or re-provisioning** a connected account is three writes in
        a fixed order". What differs is what each may conclude, which is why
        ADR-0151 §1 keeps them two operations: a fresh connection cannot fail with
        an unknown reference and cannot lose a compare-and-swap.

        The classification is ADR-0151 §7's, by **two facts this act knows** —
        whether its own first write *returned*, and whether its activation
        *returned having landed* — and never by which call raised or by a phase
        inferred after the fact.

        Args:
            plan: What this act is, and what it may conclude. Its
                ``displaceable`` is what decides whether a swap that did not land
                is reported as displaced or as incomplete, because
                :class:`~ai_assistant.core.errors.DisplacedProvisioningError` is
                not a declared failure of ``connect_account`` (ADR-0151 §2a).
            identity: The account identity, recorded verbatim.
            credential: The credential, written to this act's own slot.

        Returns:
            The live record this act wrote, ``ACTIVE`` at the plan's revision.
        """
        reference = plan.reference
        revision = plan.revision
        displaceable = plan.displaceable
        slot = SecretName(scope=SecretScope.INTEGRATION, key=self._mint_slot())
        pending = ConnectionEntry(
            reference=reference,
            revision=revision,
            identity=identity,
            state=ProvisioningState.PENDING,
            slot=slot,
        )

        # Write one: the record, as *pending*. A ``ConnectionStoreError`` from
        # here propagates unchanged and carries no reference — the write did not
        # return, so whether it landed cannot be asserted (ADR-0151 §7).
        filed = await self._store.append(
            pending, expected_latest=None if plan.observed is None else plan.observed.sequence
        )
        if filed is None:
            raise self._did_not_take(reference, displaceable=displaceable, written=False)

        # ADR-0148 §6: re-read before the credential write, and abandon unless the
        # record still carries what this act's own first write recorded.
        await self._still_ours(reference, filed, displaceable=displaceable)

        # Write two: the credential, into this act's own slot. ADR-0151 §2a
        # converts a keyring failure here into the class that says what the act
        # did, chaining the original rather than re-making ADR-0125 §7's own
        # classification.
        try:
            await self._secrets.set(slot, credential)
        except SecretStoreError as exc:
            msg = (
                f"the credential for connection {reference!r} could not be written, so the "
                f"act did not complete; re-provision it or disconnect it"
            )
            raise IncompleteProvisioningError(msg, reference) from exc

        # ADR-0148 §6: re-read again before the activation.
        await self._still_ours(reference, filed, displaceable=displaceable)

        # Write three: the activation, itself a compare-and-swap from exactly the
        # pending state this act's own first write recorded. The re-read above is
        # not what makes it safe — an activation issued after a passing re-read
        # may still be in flight when a displacing act's swap lands.
        active = ConnectionEntry(
            reference=reference,
            revision=revision,
            identity=identity,
            state=ProvisioningState.ACTIVE,
            slot=slot,
        )
        try:
            landed = await self._store.append(active, expected_latest=filed.sequence)
        except ConnectionStoreError as exc:
            # The activation *failed rather than returning*: the store may have
            # committed the swap and failed before saying so, so neither
            # completion nor incompletion may be asserted (ADR-0151 §7).
            msg = (
                f"the outcome of the act on connection {reference!r} is not known; read what "
                f"is connected rather than running it again"
            )
            raise ProvisioningOutcomeUnknownError(msg, reference) from exc
        if landed is None:
            raise self._did_not_take(reference, displaceable=displaceable, written=True)

        # ADR-0148 §6: the predecessor's slot goes once this act's activation has
        # landed, and never before. A failure here means the act **completed**.
        if plan.predecessor is not None:
            try:
                await self._secrets.delete(plan.predecessor)
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

    async def _still_ours(self, reference: str, filed: StoredEntry, *, displaceable: bool) -> None:
        """Abandon unless the reference's latest entry is still this act's own.

        ADR-0148 §6's re-read, compared on the store's own append position rather
        than on the identity and revision it names. The two are equivalent here
        and the position is the stronger of them: the store is append-only, so an
        entry's sequence never moves, and an act whose pending entry is still the
        latest is one whose identity and revision are still what it recorded —
        while a comparison on the pair alone would be satisfied by a second entry
        carrying the same values.

        Raises:
            IncompleteProvisioningError: If the re-read itself failed, or if the
                record was taken over and this act cannot be displaced.
            DisplacedProvisioningError: If a later act holds the record.
        """
        try:
            latest = await self._store.latest(reference)
        except ConnectionStoreError as exc:
            msg = (
                f"connection {reference!r} could not be re-read, so the act did not "
                f"complete; re-provision it or disconnect it"
            )
            raise IncompleteProvisioningError(msg, reference) from exc
        if latest is None or latest.sequence != filed.sequence:
            raise self._did_not_take(reference, displaceable=displaceable, written=True)

    def _did_not_take(
        self, reference: str, *, displaceable: bool, written: bool
    ) -> DisplacedProvisioningError | IncompleteProvisioningError | ConnectionStoreError:
        """The failure for a swap that did not land, by what this act could conclude.

        Three cases, and the last two only exist because of the mint. Where the
        reference could be held by another act, this is ADR-0151 §7's
        displacement — no record this act wrote is the reference's live one, and
        it is deliberately **not** a claim that the act wrote nothing. Where it
        could not and this act had written **nothing**, the only way the first
        append is refused is that the store already holds the freshly minted
        reference: the factory repeated a value, which ADR-0151 §3 makes the
        store's own refusal to establish. And where it could not but this act
        *had* written, the record was taken over by something that cannot name
        it — unreachable rather than merely unlikely — so the report is that the
        act did not complete, which is the classification ADR-0151 §7 gives every
        other post-first-write failure and the only one
        :meth:`KeyringConnectionProvisioner.provision` declares.

        Args:
            reference: The connection the act was on.
            displaceable: Whether another act can hold this reference.
            written: Whether this act's own first write has returned.

        Returns:
            The failure to raise.
        """
        if displaceable:
            msg = (
                f"another act took connection {reference!r} over, so nothing this act wrote "
                f"is live; read what is connected and decide whether to run it again"
            )
            return DisplacedProvisioningError(msg)
        if written:
            msg = (
                f"connection {reference!r} is no longer the record this act wrote, so the act "
                f"did not complete; re-provision it or disconnect it"
            )
            return IncompleteProvisioningError(msg, reference)
        msg = (
            "the connection store already holds the reference this act minted, so nothing "
            "was written; the reference factory repeated a value it must not repeat"
        )
        return ConnectionStoreError(msg)

    # --- ConnectionProvisioner: disconnection and the two listings ------------

    async def disconnect(self, reference: Identifier) -> ConnectedAccount | None:
        """Remove a reference's live record and delete its credentials.

        Raises:
            ResidualCredentialError: If the removal entry landed and at least one
                credential deletion did not. The reference **is** disconnected.
            ConnectionStoreError: If the store could not be read or written.
        """
        removal = await self._store.remove(reference)
        if removal is None:
            # ADR-0149 §5: a reference the store has never held. Nothing is
            # written and nothing is deleted, so a typo leaves no tombstone and
            # creates no revision sequence.
            return None

        slots = await self._store.slots_below(reference, removal.cutoff)
        failure: SecretStoreError | None = None
        for slot in slots:
            try:
                await self._secrets.delete(slot)
            except SecretStoreError as exc:
                # The pass continues rather than stopping at the first failure:
                # ADR-0149 §5 asks that the failure be reported and never
                # suppressed, and deleting the rest leaves strictly less behind
                # for the re-run that is the remedy either way. The first failure
                # is what the report names, because a keyring that refused one
                # deletion will usually refuse them all and a caller needs one
                # cause rather than a list.
                failure = failure if failure is not None else exc
        if failure is not None:
            msg = (
                f"connection {reference!r} is disconnected; a credential could not be "
                f"deleted and remains unreferenced. Run the disconnection again"
            )
            raise ResidualCredentialError(msg, reference) from failure
        return None if removal.removed is None else removal.removed.account()

    async def connected(self) -> tuple[ConnectedAccount, ...]:
        """The live record for every reference that has one.

        The one method that serves both Protocols' member of this name (ADR-0153
        §2).

        Raises:
            ConnectionStoreError: If the store cannot be read.
        """
        return await self._store.live()

    async def recent_acts(self, *, limit: int) -> tuple[ConnectionAct, ...]:
        """Up to ``limit`` acts, newest first.

        Raises:
            ConnectionStoreError: If the store cannot be read.
        """
        return await self._store.recent(limit=limit)

    # --- ConnectionPurger -----------------------------------------------------

    async def purge(self) -> None:
        """Delete every credential the store names, then its entries (ADR-0149 §8).

        **The entries go last and only on a complete pass.** A deletion that
        raises leaves every entry in place, the failure reported and never
        suppressed, and no part of the purge proceeding past it — because "slots
        before the store" is satisfied by a purge that attempts every slot, has
        one deletion raise, and destroys the store anyway, which leaves a
        credential with no remaining durable name. The failure propagates
        unwrapped: this is not a provisioning act, ADR-0151 §2a's conversion
        clause is about one, and ADR-0153 §4 requires the deployment condition to
        be reported as itself rather than as "there was nothing to purge".

        **A cancellation lands in the same place.** Nothing is cleared until every
        deletion has returned, so a ``CancelledError`` in flight leaves every
        entry in place and the re-run deletes the remainder — ADR-0153 §3's first
        interruption window, reached by a cancellation exactly as by a crash.

        **An installation that never provisioned a connection makes no keyring
        call at all**, so this cannot fail on an absent, locked or backendless
        keyring: the loop runs zero times, and constructing a keyring face touches
        nothing (ADR-0125 §7, ADR-0153 §4).

        Raises:
            SecretStoreUnavailableError: If the keyring cannot be reached and the
                store names at least one slot.
            SecretStoreError: If the keyring was reached and a deletion failed.
            ConnectionStoreError: If the store cannot be read or cleared.
        """
        for slot in await self._store.slots():
            await self._secrets.delete(slot)
        await self._store.clear()


__all__ = ["MESSAGE_MAX_BYTES", "KeyringConnectionProvisioner"]
