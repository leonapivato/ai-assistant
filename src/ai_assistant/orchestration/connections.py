"""The connection operations: connecting, replacing, disconnecting, and the two listings.

ADR-0151 §1 rules that the client surface for connections is exactly five methods
on :class:`~ai_assistant.core.protocols.AssistantEngine`, and §10 rules that they
are implemented **here**, in `orchestration`, "in one object that holds the
provisioner seam below and nothing else that reaches the keyring or the connection
store", with ``Engine`` delegating to it. This module is that object.

**`orchestration` is forced rather than chosen** (ADR-0151 §10), for ADR-0102 §7's
reason unchanged: the operations must be ``AssistantEngine`` methods to be
addressable over the socket at all — ADR-0084 §3 makes the envelope's ``method``
member "the ``AssistantEngine`` method name" and ``wire/surface.py`` derives the
legal set from the Protocol itself — ``AssistantEngine`` is provided by
`orchestration` (ADR-0085 §1), and `service/` holds the listener rather than the
surface. ADR-0149 §9 states the placement normatively anyway.

**What is new here is the one thing `orchestration` touches that it did not
before: a ``SecretValue`` in transit.** ADR-0151 §6's relay clause is what keeps
that from becoming a second path to the keyring, and it is the whole of this
module's discipline — it relays the credential to the provisioner and **does
nothing else with it**: it does not unwrap it, log it, retain it beyond the call,
copy it into any other value, retry a call with it, or read it back. Every method
below is a forward and a return, which is not laziness but the property being
asserted; a body with a branch over the credential would be a body a reviewer has
to read for disclosure.

**Holding this seam is not holding a keyring face**, which is the distinction
ADR-0102 §7 drew about a composition root and ``SourceGrantStore`` and ADR-0149 §8's
tenth clause states directly for this neighbourhood. This object names five members
that take and return `core` types; it cannot name ``set``, ``delete`` or ``get``,
and no annotation on it mentions
:class:`~ai_assistant.core.protocols.Secrets` or
:class:`~ai_assistant.core.protocols.SecretStore` — so ADR-0125 §8's fourth clause
stays true of `orchestration` word for word. `orchestration` constructs no
``SecretStore``, no ``Secrets`` and no connection store, and imports no module of
`tools` (golden rule 1); the composition root wires the one implementation.

**The three writes stay the provisioner's** (ADR-0149 §9, ADR-0151 §7). Nothing
here reorders ADR-0148 §6's order, splits it across calls, retries a displaced act,
rolls back a write that landed, or performs a liveness pre-check to narrow a
displacement window. Nothing here deletes, compacts or reconciles a displaced act's
entry or its slot either: ADR-0149 §5's deletion pass and ADR-0149 §8's purge are
the only things that remove either, and a surface that tidied one would be removing
the name that makes the other reachable (ADR-0151 §7).

**Argument validation is not here, and that is deliberate.** ADR-0085 §9's "refused
locally, before any I/O" lives one layer up, in the caller — ``Engine``, the
canonical fake and ``HubEngineClient`` alike — because a refusal that happened only
here would happen only on the hub, which is the round trip §9 exists to remove. By
the time a call reaches this object its identity has passed
:func:`~ai_assistant.orchestration.payloads.check_provisioning_call` and its ``limit``
:func:`~ai_assistant.orchestration.payloads.positive_page_argument`, which is why
:class:`~ai_assistant.core.errors.UnusableIdentityError` appears nowhere below and
why the seam declares no ``ValueError`` for an argument already validated
(ADR-0151 §10).

**Nothing a model steers can reach any of this** (ADR-0151 §13). No
``ToolDefinition`` binds these operations, no plan step may reach one, no
model-authored value may become an argument to one, and no scheduler job may invoke
one. Two of those are held mechanically — `tools` is a subsystem, subsystems never
import `orchestration` and never import one another — and the clause is written
anyway, because what would be inverted is ADR-0005 §3's "The model proposes; a
deterministic policy disposes", and because ADR-0149 §1 already transposes the same
prohibitions onto the provisioner, which would be defeated one layer up if the
operation calling it were reachable.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ai_assistant.core.protocols import ConnectionProvisioner
    from ai_assistant.core.types import (
        ConnectedAccount,
        ConnectionAct,
        Identifier,
        NonBlankEncodableText,
        SecretValue,
    )


class ConnectionOperations:
    """The five connection operations, over one provisioner seam and nothing else."""

    def __init__(self, *, provisioner: ConnectionProvisioner) -> None:
        """Wire the operations from the provisioner seam.

        Args:
            provisioner: The seam by which `orchestration` reaches the connection
                provisioner in `tools` (ADR-0149 §10, ADR-0151 §10). Reached
                **through the Protocol and never by an injected concrete**, so this
                object cannot name the store the provisioner opens, the keyring
                face it holds, or the slot any record names. It is the only
                collaborator, because §10 rules this object holds "nothing else
                that reaches the keyring or the connection store".
        """
        self._provisioner = provisioner

    # --- the two acts that carry a credential --------------------------------

    async def connect(
        self, *, identity: NonBlankEncodableText, credential: SecretValue
    ) -> ConnectedAccount:
        """Connect a fresh account, letting the provisioner mint its reference.

        **Nothing is passed for the reference and nothing could be** (ADR-0151 §3,
        §10): ADR-0149 §1 puts the act, and §3 the store, inside `tools`, so the
        only component that can mint a reference into that store is the
        provisioner — an engine-side factory would put the mint on the far side of
        the boundary from the compare-and-swap it has to be atomic with. The
        reference is read off the record this returns.

        Args:
            identity: The account identity, already refused by the caller if it is
                unusable (ADR-0151 §5), and relayed **verbatim**: nothing here
                strips, case-folds, case-normalises or Unicode-normalises it.
            credential: The account's secret, relayed still wrapped and read by
                nothing in this layer (ADR-0151 §6).

        Returns:
            The live record the act wrote, ``ACTIVE`` at the reference's first
            revision — the provisioner returns only once ADR-0148 §6's third write
            has landed, and nothing here converts a partial act into one.

        Raises:
            IncompleteProvisioningError: Propagated unchanged (ADR-0151 §7).
            ProvisioningOutcomeUnknownError: Propagated unchanged.
            ConnectionStoreError: Propagated unchanged.
        """
        return await self._provisioner.provision(identity=identity, credential=credential)

    async def reprovision(
        self,
        reference: Identifier,
        *,
        identity: NonBlankEncodableText,
        credential: SecretValue,
    ) -> ConnectedAccount:
        """Replace the credential under an existing reference.

        The reference is relayed **unaltered**, which is the whole of this layer's
        part in ADR-0151 §3's exact-comparison clause: no implementation matches a
        reference by prefix, by case-insensitive comparison or by any equivalence
        other than equality, and a layer that normalised one on the way past would
        defeat that below the clause.

        Args:
            reference: The connection to re-provision, already validated by the
                caller and passed on as it stands.
            identity: The account identity for the new revision, relayed verbatim.
            credential: The replacement secret, relayed still wrapped.

        Returns:
            The live record the act wrote, ``ACTIVE`` at the new revision.

        Raises:
            UnknownConnectionError: Propagated unchanged — the store is the arbiter
                of whether the reference exists, and this layer does not pre-check
                it (ADR-0151 §7).
            DisplacedProvisioningError: Propagated unchanged, and **never retried**
                (ADR-0149 §9). The recourse is the caller's: read what is connected
                and decide whether to run the act again.
            IncompleteProvisioningError: Propagated unchanged.
            ProvisioningOutcomeUnknownError: Propagated unchanged.
            ResidualCredentialError: Propagated unchanged, and never suppressed
                (ADR-0149 §5). It means the act **completed**.
            ConnectionStoreError: Propagated unchanged.
        """
        return await self._provisioner.reprovision(
            reference, identity=identity, credential=credential
        )

    # --- the act that removes one --------------------------------------------

    async def disconnect(self, reference: Identifier) -> ConnectedAccount | None:
        """Disconnect a reference, or report that there was no live record.

        Args:
            reference: The connection to disconnect, relayed unaltered.

        Returns:
            The live record removed, or ``None`` where there was none to remove.
            The ``None`` is relayed rather than converted into an error, because
            ADR-0151 §8 makes it a *report* — no live record was removed by this
            call — and turning it into a refusal would make a reference the store
            has never held indistinguishable from one already disconnected.

        Raises:
            ResidualCredentialError: Propagated unchanged. The removal entry
                landed, so the reference **is** disconnected; what failed is a
                credential deletion (ADR-0151 §8).
            ConnectionStoreError: Propagated unchanged.
        """
        return await self._provisioner.disconnect(reference)

    # --- the two listings, which answer different questions -------------------

    async def connected(self) -> tuple[ConnectedAccount, ...]:
        """Every live record, from the store's live records alone (ADR-0151 §9).

        **Not derived from** :meth:`recent_acts`, and not filtered by what the hub
        currently holds (ADR-0139 §1). Nothing here drops a reference because no
        tool is bound to it, because its integration is not built, or because
        configuration changed: the record exists, the credential exists in the
        keyring, and the user is the only party who can end it.

        Returns:
            Every live record the provisioner's single read saw, pending records
            included and carrying ``PENDING`` (ADR-0151 §4).

        Raises:
            ConnectionStoreError: Propagated unchanged, including the one a store
                holding an entry that no longer validates raises. This reports
                neither a partial set nor the references it could have answered
                for.
        """
        return await self._provisioner.connected()

    async def recent_acts(self, *, limit: int) -> tuple[ConnectionAct, ...]:
        """What was done, newest first, bounded by ``limit`` (ADR-0151 §9).

        **Not derived from** :meth:`connected`, and it does not derive it either.
        The unsoundness in either direction is the page boundary rather than a
        clock: a reference whose latest act falls outside the page is one a client
        walking the page would report by an earlier act.

        Args:
            limit: The most rows to return, already refused non-positive by the
                caller (ADR-0151 §2a). Passed on with **no default** — the default
                is ``AssistantEngine``'s, and a second one here would be a second
                place for one number to drift (ADR-0151 §10).

        Returns:
            Up to ``limit`` acts, newest first, one row per ``(reference,
            revision)``.

        Raises:
            ConnectionStoreError: Propagated unchanged.
        """
        return await self._provisioner.recent_acts(limit=limit)


__all__ = [
    "ConnectionOperations",
]
