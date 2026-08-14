"""The relay `orchestration` performs, and the three things it must not do.

The shared conformance suite holds every ``AssistantEngine`` implementation to
ADR-0151's surface clauses, and ``tests/tools/connection_provisioner_contract.py``
holds every provisioner to ADR-0148 §6's orderings. What neither reaches is the
**layer between them**, and ADR-0151 §6 and §10 put three obligations there that no
return value expresses:

* it relays the credential and does nothing else with it — no unwrap, no log, no
  retention, no copy, no retry, no read-back;
* it holds the provisioner seam and **nothing else that reaches the keyring or the
  connection store**, so `orchestration` acquires no keyring face by carrying a
  Tier 0 value across its surface (ADR-0125 §8);
* it neither reorders, splits, retries nor rolls back ADR-0148 §6's three writes,
  and a cancellation crosses it unconverted (ADR-0060, ADR-0151 §7).

Each is a *negative*, so each is asserted against something the layer would have to
have done: an object that records what it was handed, an attribute list, a call
count, and a cancellation delivered mid-act.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import pytest
from pydantic import SecretStr

from ai_assistant.core.errors import ConnectionStoreError, IncompleteProvisioningError
from ai_assistant.core.protocols import ConnectionProvisioner
from ai_assistant.core.types import ProvisioningState, secret_value
from ai_assistant.orchestration import ConnectionOperations
from ai_assistant.testing import Disclosure, FakeConnectionProvisioner, SecretMethod

if TYPE_CHECKING:
    from ai_assistant.core.types import ConnectedAccount, ConnectionAct, SecretValue

pytestmark = pytest.mark.anyio

_PLAINTEXT = "corr3ct-h0rse-battery-staple"
_IDENTITY = "  Ada@Example.COM  "


def _credential(plaintext: str = _PLAINTEXT) -> SecretValue:
    """One credential, built the only supported way (ADR-0125 §3)."""
    return secret_value(SecretStr(plaintext))


class _Recording:
    """A provisioner that records what it was handed and answers minimally.

    Not a conformance subject and not a second implementation: it exists so a case
    can assert on the *arguments that arrived*, which is the only way to check a
    relay. Everything it returns is the least a caller will accept.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.record = FakeConnectionProvisioner()

    async def provision(self, **kwargs: Any) -> ConnectedAccount:
        self.calls.append(("provision", (), kwargs))
        return await self.record.provision(**kwargs)

    async def reprovision(self, reference: str, **kwargs: Any) -> ConnectedAccount:
        self.calls.append(("reprovision", (reference,), kwargs))
        return await self.record.reprovision(reference, **kwargs)

    async def disconnect(self, reference: str) -> ConnectedAccount | None:
        self.calls.append(("disconnect", (reference,), {}))
        return await self.record.disconnect(reference)

    async def connected(self) -> tuple[ConnectedAccount, ...]:
        self.calls.append(("connected", (), {}))
        return await self.record.connected()

    async def recent_acts(self, *, limit: int) -> tuple[ConnectionAct, ...]:
        self.calls.append(("recent_acts", (), {"limit": limit}))
        return await self.record.recent_acts(limit=limit)


async def test_the_credential_crosses_the_seam_still_wrapped() -> None:
    """ADR-0151 §6: `orchestration` relays it and does not unwrap it.

    **The wrapper is the property, not the value.** ADR-0125 §3's whole argument is
    that a disclosure has to be a line somebody wrote — so a layer that unwrapped
    here and re-wrapped below would satisfy every assertion about the plaintext
    arriving while removing the protection, and a layer that passed a bare ``str``
    would have made the redaction unavailable to everything downstream.
    """
    recording = _Recording()
    operations = ConnectionOperations(provisioner=recording)

    await operations.connect(identity=_IDENTITY, credential=_credential())

    _name, _positional, kwargs = recording.calls[0]
    assert isinstance(kwargs["credential"], SecretStr)
    assert kwargs["credential"].get_secret_value() == _PLAINTEXT
    # And the identity arrived byte-for-byte, un-stripped and un-case-folded.
    assert kwargs["identity"] == _IDENTITY


async def test_the_relay_holds_nothing_and_reads_nothing_back() -> None:
    """ADR-0151 §6: no retention beyond the call, no copy, no read-back.

    Asserted three ways, because "does not retain" is not directly observable: the
    object's own attributes are exactly the seam it was constructed with; the
    plaintext appears nowhere in its state; and one surface call produces exactly
    one seam call, so nothing is read back to confirm what was written.
    """
    recording = _Recording()
    operations = ConnectionOperations(provisioner=recording)

    await operations.connect(identity=_IDENTITY, credential=_credential())

    assert [name for name, _positional, _kwargs in recording.calls] == ["provision"]
    held = {key: value for key, value in vars(operations).items() if not key.startswith("__")}
    assert list(held) == ["_provisioner"]
    assert _PLAINTEXT not in repr(held)


async def test_the_relay_names_no_keyring_face() -> None:
    """ADR-0125 §8, ADR-0149 §8: holding the seam is not holding a face.

    The distinction ADR-0102 §7 drew about a composition root and
    ``SourceGrantStore``, checked here rather than asserted: this object can name
    five members over `core` types and cannot name ``set``, ``delete`` or ``get``.
    A future member that widened the seam would fail here before it reached review.
    """
    operations = ConnectionOperations(provisioner=FakeConnectionProvisioner())

    surface = {name for name in dir(operations) if not name.startswith("_")}

    assert surface == {"connect", "reprovision", "disconnect", "connected", "recent_acts"}
    assert not surface & {"set", "delete", "get", "purge"}


async def test_every_seam_member_is_reached_with_the_arguments_it_was_given() -> None:
    """ADR-0151 §10: the reference and the limit cross unaltered.

    The reference matters most: ADR-0151 §3 requires exact comparison at the store,
    and a layer that stripped or case-folded one on the way past would defeat that
    clause below the level it is stated at — which is precisely how ADR-0102 §2's
    annotation hazard works one argument over.
    """
    recording = _Recording()
    operations = ConnectionOperations(provisioner=recording)
    record = await operations.connect(identity="ada", credential=_credential())

    await operations.reprovision(
        record.reference, identity="ada2", credential=_credential("rotated")
    )
    await operations.disconnect(record.reference)
    await operations.connected()
    await operations.recent_acts(limit=3)

    names = [name for name, _positional, _kwargs in recording.calls]
    assert names == ["provision", "reprovision", "disconnect", "connected", "recent_acts"]
    assert recording.calls[1][1] == (record.reference,)
    assert recording.calls[2][1] == (record.reference,)
    assert recording.calls[4][2] == {"limit": 3}


async def test_a_failed_act_is_neither_retried_nor_converted() -> None:
    """ADR-0149 §9, ADR-0151 §7: propagated unchanged, and exactly once.

    Two claims in one case because they fail together: a layer that retried would
    also be a layer that had decided the first failure was not final, and
    ``IncompleteProvisioningError`` is precisely the class that says a *durable*
    partial write happened. Retrying it would rotate a credential over a record the
    caller has not been told about.
    """
    recording = _Recording()
    recording.record.secrets.fail(SecretMethod.SET, Disclosure.VERBATIM)
    operations = ConnectionOperations(provisioner=recording)

    with pytest.raises(IncompleteProvisioningError) as caught:
        await operations.connect(identity=_IDENTITY, credential=_credential())

    assert len(recording.calls) == 1
    assert caught.value.reference
    assert _PLAINTEXT not in str(caught.value)
    assert _IDENTITY.strip() not in str(caught.value)


async def test_a_store_failure_before_the_first_write_carries_no_reference() -> None:
    """ADR-0151 §7: the act's outcome is **not known**, so nothing may be asserted.

    ``ConnectionStoreError`` is the one class on this surface that deliberately
    carries no reference: the first write did not return, so there may be no
    reference to carry. A relay that attached one would be manufacturing the very
    claim the class exists to withhold.
    """

    class _Refusing(_Recording):
        """A seam whose first write never returns. Composed rather than subclassed:
        the canonical fake is ``@final``, deliberately, so a case needing different
        behaviour writes the one member it needs over this module's recorder."""

        async def provision(self, **_kwargs: Any) -> ConnectedAccount:
            msg = "the connection store could not be written; nothing may be asserted"
            raise ConnectionStoreError(msg)

    operations = ConnectionOperations(provisioner=_Refusing())

    with pytest.raises(ConnectionStoreError) as caught:
        await operations.connect(identity=_IDENTITY, credential=_credential())

    assert not hasattr(caught.value, "reference")


async def test_a_cancellation_crosses_the_relay_unconverted() -> None:
    """ADR-0060, ADR-0151 §7: "a ``CancelledError`` is not one [a failure]".

    **The case a suite testing only failures never reaches.** ADR-0151 §7 is
    explicit that a cancellation at any point of a provisioning act propagates
    unconverted and is never turned into ``ProvisioningOutcomeUnknownError`` or any
    other class on this surface — the client reports the outcome as *not known*
    under the unread-outcome clause instead, without the reference and without
    starting a call to obtain one.

    Delivered while the act is suspended **inside its credential write**, which is
    the window that exists at all: the canonical fake's own lever holds the keyring
    open so the cancellation lands between two of ADR-0148 §6's three writes rather
    than before or after all of them.
    """
    provisioner = FakeConnectionProvisioner()
    operations = ConnectionOperations(provisioner=provisioner)
    suspension = provisioner.suspend_next_credential_write()

    running = asyncio.ensure_future(
        operations.connect(identity=_IDENTITY, credential=_credential())
    )
    await suspension.reached()
    running.cancel()
    suspension.release()

    with pytest.raises(asyncio.CancelledError):
        await running


async def test_the_seam_is_satisfied_structurally_by_what_the_root_wires() -> None:
    """Golden rule 1: reached through the Protocol, never by an injected concrete.

    The narrowing lives on ``ConnectionOperations.__init__``'s annotation, and this
    is what makes that annotation mean something at runtime: the canonical fake is
    a ``ConnectionProvisioner`` by structure alone, with no inheritance and no
    registration, which is the property that lets `orchestration` import no module
    of `tools`.
    """
    assert isinstance(FakeConnectionProvisioner(), ConnectionProvisioner)


async def test_the_two_listings_are_not_derived_from_one_another() -> None:
    """ADR-0139 §1, ADR-0151 §9: each reaches its own seam member.

    Asserted at the relay because this is the layer where a "helpful" derivation
    would be cheapest to write — ``connected`` could plausibly be computed by
    walking ``recent_acts``, and the page boundary is exactly what makes that
    unsound: a reference whose latest act falls outside the page would be reported
    by an earlier one.
    """
    recording = _Recording()
    operations = ConnectionOperations(provisioner=recording)
    record = await operations.connect(identity=_IDENTITY, credential=_credential())
    recording.calls.clear()

    live = await operations.connected()
    acts = await operations.recent_acts(limit=1)

    assert [name for name, _positional, _kwargs in recording.calls] == [
        "connected",
        "recent_acts",
    ]
    assert [one.reference for one in live] == [record.reference]
    assert live[0].state is ProvisioningState.ACTIVE
    assert [act.revision for act in acts] == [1]
