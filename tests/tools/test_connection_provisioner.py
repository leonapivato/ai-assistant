"""The production provisioner: both shared suites, plus what only it can be held to.

The shared suites bind every implementation. What is here beside them is the set of
obligations ADR-0149 §14 and ADR-0151 §16 put on **the lane that owns the code**:
ADR-0148 §6's crash windows, its three displacement points, the two interleavings
ADR-0149 §5 exists for, and the confinement clauses. Each is reached by scripting
the real store or the real keyring rather than by a second implementation, which is
what :class:`ScriptedStore` and :class:`SuspendingSecrets` are for.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, final
from uuid import uuid4

import pytest
from connection_provisioner_contract import (
    IDENTITY,
    ConnectionProvisionerContract,
    credential,
)
from connection_purger_contract import ConnectionPurgerContract

from ai_assistant.core.errors import (
    AssistantError,
    ConnectionStoreError,
    DisplacedProvisioningError,
    IncompleteProvisioningError,
    ProvisioningOutcomeUnknownError,
    ResidualCredentialError,
    SecretStoreError,
)
from ai_assistant.core.types import (
    CONNECTION_REFERENCE_MAX_BYTES,
    ProvisioningState,
    SecretName,
    SecretScope,
)
from ai_assistant.testing import Disclosure, FakeSecretStore, SecretMethod
from ai_assistant.testing.cancellation import SuspendableResource
from ai_assistant.testing.secrets import SecretBacking
from ai_assistant.tools.connection_store import SqliteConnectionStore
from ai_assistant.tools.provisioning import MESSAGE_MAX_BYTES, KeyringConnectionProvisioner
from ai_assistant.wire.errors import error_payload

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Iterator
    from pathlib import Path

    from ai_assistant.core.protocols import ConnectionProvisioner, ConnectionPurger
    from ai_assistant.core.types import SecretValue
    from ai_assistant.testing.cancellation import SuspendedCall
    from ai_assistant.tools.connection_store import ConnectionEntry, Removal, StoredEntry


class ScriptedStore(SqliteConnectionStore):
    """The real store, with each call countable and each outcome scriptable.

    A subclass rather than a double, so every case below runs against the SQLite
    the hub actually opens. ADR-0151 §16 asks for "one deterministic case each" at
    every point a provisioning act can fail, and the points are distinguished by
    *which call* raised — so the counter is the whole mechanism: append 1 is the
    record's first write, append 2 the activation, and the reads between them are
    ADR-0148 §6's two re-reads.

    ``commit_then_fail_at`` is the one that is not merely a failure: the append
    lands and the store then raises, which is the "the store may have committed the
    compare-and-swap and failed before saying so" case ADR-0151 §7 gives
    :class:`~ai_assistant.core.errors.ProvisioningOutcomeUnknownError` and which
    §16 requires exercised, "since a following ``connected_accounts`` then shows
    that reference ``ACTIVE``".
    """

    def __init__(self, *, path: Path | str) -> None:
        """Open the store with nothing scripted."""
        super().__init__(path=path)
        self.appends = 0
        self.reads = 0
        self.fail_append_at: set[int] = set()
        self.commit_then_fail_at: set[int] = set()
        self.fail_read_at: set[int] = set()
        self.before_append: dict[int, Callable[[], Awaitable[Any]]] = {}
        self.before_read: dict[int, Callable[[], Awaitable[Any]]] = {}
        self.before_slots_below: Callable[[], Awaitable[Any]] | None = None

    async def append(
        self, entry: ConnectionEntry, *, expected_latest: int | None
    ) -> StoredEntry | None:
        """Count the append, run whatever was scheduled, then script the outcome."""
        self.appends += 1
        turn = self.appends
        if (scheduled := self.before_append.pop(turn, None)) is not None:
            await scheduled()
        if turn in self.fail_append_at:
            msg = f"scripted failure at append {turn}"
            raise ConnectionStoreError(msg)
        filed = await super().append(entry, expected_latest=expected_latest)
        if turn in self.commit_then_fail_at:
            msg = f"scripted failure after append {turn} committed"
            raise ConnectionStoreError(msg)
        return filed

    async def latest(self, reference: str) -> StoredEntry | None:
        """Count the read, run whatever was scheduled, then script the outcome."""
        self.reads += 1
        turn = self.reads
        if (scheduled := self.before_read.pop(turn, None)) is not None:
            await scheduled()
        if turn in self.fail_read_at:
            msg = f"scripted failure at read {turn}"
            raise ConnectionStoreError(msg)
        return await super().latest(reference)

    async def remove(self, reference: str) -> Removal | None:
        """Append the removal, then run the disconnection's scheduled interleaving.

        Scheduled *after* the removal entry lands and *before* the deletion pass
        reads its slots, which is the window ADR-0149 §5's revision cutoff exists
        for and the only place the inverse interleaving can be staged.
        """
        removal = await super().remove(reference)
        if (scheduled := self.before_slots_below) is not None:
            self.before_slots_below = None
            await scheduled()
        return removal


@final
class SuspendingSecrets:
    """A keyring face whose write and delete can be held open (ADR-0060).

    The production provisioner acquires nothing of its own across an ``await`` —
    the store's connection is the store's — so the only place a suite can hold one
    of its acts still is inside the keyring call it is making. This wraps the
    canonical fake rather than replacing it, so every disclosure and availability
    rule the fake enforces still applies.

    **Two resources rather than one**, and the split is load-bearing: the
    disconnect interleaving ADR-0149 §14 requires holds a *write* open and then
    runs a disconnection, whose *deletions* must be able to proceed past it. One
    shared lock would make that scenario deadlock rather than fail, which is the
    worst way for a test to be wrong.
    """

    def __init__(self, inner: FakeSecretStore) -> None:
        """Wrap ``inner``, with nothing armed."""
        self.inner = inner
        self._writes = SuspendableResource()
        self._deletions = SuspendableResource()

    def suspend_next_write(self) -> SuspendedCall:
        """Hold the next credential write open."""
        return self._writes.suspend_next()

    def suspend_next_deletion(self) -> SuspendedCall:
        """Hold the next credential deletion open."""
        return self._deletions.suspend_next()

    async def get(self, name: SecretName) -> SecretValue | None:
        """Read, which the provisioner must never do (ADR-0149 §1)."""
        return await self.inner.get(name)

    async def set(self, name: SecretName, value: SecretValue) -> None:
        """Write, holding the call open where one was armed."""
        async with self._writes.held():
            await self.inner.set(name, value)

    async def delete(self, name: SecretName) -> bool:
        """Delete, holding the call open where one was armed."""
        async with self._deletions.held():
            return await self.inner.delete(name)


@final
class CountingSecrets:
    """A keyring face that records which of its three members were called.

    ADR-0149 §14 asks for "a test that the provisioner never calls ``get``", and
    an assertion over one operation would prove it for that operation alone. This
    records every call so one case can drive all seven members and then assert the
    absence over the whole set.
    """

    def __init__(self, inner: FakeSecretStore) -> None:
        """Wrap ``inner`` with an empty call log."""
        self.inner = inner
        self.calls: list[str] = []

    async def get(self, name: SecretName) -> SecretValue | None:
        """Record and delegate."""
        self.calls.append("get")
        return await self.inner.get(name)

    async def set(self, name: SecretName, value: SecretValue) -> None:
        """Record and delegate."""
        self.calls.append("set")
        await self.inner.set(name, value)

    async def delete(self, name: SecretName) -> bool:
        """Record and delegate."""
        self.calls.append("delete")
        return await self.inner.delete(name)


@final
class RepeatableMint:
    """The reference factory, with the one switch ADR-0151 §3's store clause needs.

    Version 4 UUIDs, exactly as production's own factory draws, until a case asks
    for the previous value again — which is how a suite reaches the state §3 makes
    the *store* responsible for refusing, without the production module growing a
    test affordance of its own.
    """

    def __init__(self) -> None:
        """Create a factory that has minted nothing."""
        self.last = ""
        self.repeat = False

    def __call__(self) -> str:
        """Draw the next reference, or repeat the previous one."""
        if self.repeat:
            self.repeat = False
            return self.last
        self.last = str(uuid4())
        return self.last


class ProvisionerHarness:
    """Builds the production subject and supplies both suites' hooks.

    The store, the keyring, the suspender and the mint are kept on the instance
    because a binding's fixture is what constructs them; the hooks then reach the
    objects the subject was wired with rather than into the subject's own
    internals.
    """

    store: ScriptedStore
    keyring: FakeSecretStore
    secrets: SuspendingSecrets
    mint: RepeatableMint
    subject: KeyringConnectionProvisioner

    def build(self, tmp_path: Path) -> KeyringConnectionProvisioner:
        """Wire a provisioner over a real store in ``tmp_path``."""
        self.store = ScriptedStore(path=tmp_path / "connections.db")
        self.keyring = FakeSecretStore(scope=SecretScope.INTEGRATION)
        self.secrets = SuspendingSecrets(self.keyring)
        self.mint = RepeatableMint()
        self.subject = KeyringConnectionProvisioner(
            store=self.store, secrets=self.secrets, mint_reference=self.mint
        )
        return self.subject

    # --- the hooks both suites take ------------------------------------------

    def keyring_entries(self, provisioner: object) -> int:
        """How many credentials the subject's keyring holds."""
        del provisioner
        return len(self.keyring.backing)

    def fail_next(self, provisioner: object, method: SecretMethod) -> None:
        """Arm the subject's keyring to fail its next call to ``method``."""
        del provisioner
        self.keyring.fail(method, Disclosure.VERBATIM)

    def repeat_next_reference(self, provisioner: object) -> None:
        """Script the subject's injected reference factory to repeat its last value."""
        del provisioner
        self.mint.repeat = True

    def suspend_next_credential_write(self, provisioner: object) -> SuspendedCall:
        """Hold the subject's next credential write open."""
        del provisioner
        return self.secrets.suspend_next_write()

    def entry_count(self, purger: object) -> int:
        """How many entries the subject's connection store holds."""
        del purger
        return len(_entries(self.store))

    def fail_next_deletion(self, purger: object) -> None:
        """Arm the subject's keyring to fail its next deletion."""
        del purger
        self.keyring.fail(SecretMethod.DELETE, Disclosure.VERBATIM)

    def keyring_becomes_unreachable(self, purger: object) -> None:
        """Put the subject's keyring into ADR-0125 §7's unavailable state."""
        del purger
        self.keyring.become_unavailable()

    def suspend_next_deletion(self, purger: object) -> SuspendedCall:
        """Hold the subject's next credential deletion open."""
        del purger
        return self.secrets.suspend_next_deletion()

    async def connect(self, purger: object, identity: str) -> str:
        """Connect an account through the subject's wide face."""
        record = await _provisioner(purger).provision(identity=identity, credential=credential())
        return record.reference

    async def reprovision(self, purger: object, reference: str) -> None:
        """Re-provision ``reference`` through the subject's wide face."""
        await _provisioner(purger).reprovision(
            reference, identity="rotated", credential=credential("rotated")
        )

    async def disconnect(self, purger: object, reference: str) -> None:
        """Disconnect ``reference`` through the subject's wide face."""
        await _provisioner(purger).disconnect(reference)


def _provisioner(subject: object) -> KeyringConnectionProvisioner:
    """Narrow a suite's subject to the production provisioner."""
    assert isinstance(subject, KeyringConnectionProvisioner)
    return subject


def _entries(store: SqliteConnectionStore) -> list[tuple[Any, ...]]:
    """Every row the store holds, read straight out of SQLite.

    A test-side read of the file rather than a store method, so a case asserting
    "every entry is still in place" is not asserting it through the same query the
    code under test uses to decide what to delete.
    """
    connection: Any = store._conn
    rows = connection.execute(
        "SELECT reference, revision, state, slot FROM entries ORDER BY sequence"
    ).fetchall()
    return [tuple(row) for row in rows]


class TestKeyringConnectionProvisionerContract(ProvisionerHarness, ConnectionProvisionerContract):
    """Runs the production provisioner through the shared ``ConnectionProvisioner`` suite."""

    @pytest.fixture
    def provisioner(self, tmp_path: Path) -> Iterator[ConnectionProvisioner]:
        """A provisioner over an empty store in a temporary directory."""
        yield self.build(tmp_path)
        self.store.close()


class TestKeyringConnectionPurgerContract(ProvisionerHarness, ConnectionPurgerContract):
    """Runs the production provisioner through the shared ``ConnectionPurger`` suite."""

    @pytest.fixture
    def purger(self, tmp_path: Path) -> Iterator[ConnectionPurger]:
        """A purger over an empty store in a temporary directory."""
        yield self.build(tmp_path)
        self.store.close()


# ---------------------------------------------------------------------------
# What only the production subject can be held to
# ---------------------------------------------------------------------------


@pytest.fixture
def harness(tmp_path: Path) -> Iterator[ProvisionerHarness]:
    """A wired provisioner and the objects it was wired with."""
    built = ProvisionerHarness()
    built.build(tmp_path)
    yield built
    built.store.close()


def _subject(harness: ProvisionerHarness) -> KeyringConnectionProvisioner:
    """The provisioner the harness wired."""
    return harness.subject


# --- ADR-0151 §7's classification, one deterministic case per point ---------


async def test_a_store_failure_at_the_first_write_names_no_reference(
    harness: ProvisionerHarness,
) -> None:
    """ADR-0151 §7: before the first write returns, nothing about the act may be asserted."""
    provisioner = _subject(harness)
    harness.store.fail_append_at = {1}

    with pytest.raises(ConnectionStoreError) as caught:
        await provisioner.provision(identity=IDENTITY, credential=credential())

    assert not hasattr(caught.value, "reference")
    assert _entries(harness.store) == []


async def test_a_store_failure_at_the_first_re_read_is_incomplete(
    harness: ProvisionerHarness,
) -> None:
    """ADR-0151 §7: after the first write returns, the reference is known to exist."""
    provisioner = _subject(harness)
    harness.store.fail_read_at = {1}

    with pytest.raises(IncompleteProvisioningError) as caught:
        await provisioner.provision(identity=IDENTITY, credential=credential())

    live = await provisioner.connected()
    assert [record.reference for record in live] == [caught.value.reference]
    assert live[0].state is ProvisioningState.PENDING


async def test_a_store_failure_at_the_second_re_read_is_incomplete(
    harness: ProvisionerHarness,
) -> None:
    """ADR-0151 §7: the re-read before the activation is the same bucket as the first."""
    provisioner = _subject(harness)
    harness.store.fail_read_at = {2}

    with pytest.raises(IncompleteProvisioningError) as caught:
        await provisioner.provision(identity=IDENTITY, credential=credential())

    assert caught.value.reference != ""
    assert len(harness.keyring.backing) == 1


async def test_an_activation_that_fails_leaves_the_outcome_unknown(
    harness: ProvisionerHarness,
) -> None:
    """ADR-0151 §16: exercised with the store scripted to **commit and then fail**.

    The case that makes the distinction from
    :class:`~ai_assistant.core.errors.IncompleteProvisioningError` real: a
    following read shows that reference ``ACTIVE``, so a client that re-ran the act
    on the assumption it had failed would rotate a credential that was live.
    """
    provisioner = _subject(harness)
    harness.store.commit_then_fail_at = {2}

    with pytest.raises(ProvisioningOutcomeUnknownError) as caught:
        await provisioner.provision(identity=IDENTITY, credential=credential())

    live = await provisioner.connected()
    assert [record.reference for record in live] == [caught.value.reference]
    assert live[0].state is ProvisioningState.ACTIVE


# --- ADR-0148 §6's three displacement points -------------------------------


async def test_a_displacement_at_the_taking_swap_writes_nothing(
    harness: ProvisionerHarness,
) -> None:
    """ADR-0148 §6: an act whose compare-and-swap fails never held it and writes nothing."""
    provisioner = _subject(harness)
    record = await provisioner.provision(identity=IDENTITY, credential=credential())
    harness.store.appends = 0
    harness.store.before_append = {1: lambda: harness.store.remove(record.reference)}

    with pytest.raises(DisplacedProvisioningError):
        await provisioner.reprovision(
            record.reference, identity=IDENTITY, credential=credential("rotated")
        )

    acts = await provisioner.recent_acts(limit=10)
    assert [act.revision for act in acts] == [2, 1]


@pytest.mark.parametrize("read", [2, 3])
async def test_a_displacement_at_a_re_read_leaves_this_acts_own_row(
    harness: ProvisionerHarness, read: int
) -> None:
    """ADR-0151 §16: the displaced act's own row survives, at its own revision, PENDING.

    Both later points, because they differ in how far the displaced act had got —
    at the second re-read its credential is already in its own slot. A suite that
    asserted the store holds nothing from the displaced act would contradict
    ADR-0149 §3's append-only store and remove the entry ADR-0149 §5's deletion
    pass and §8's purge each reach that act's slot through.
    """
    provisioner = _subject(harness)
    record = await provisioner.provision(identity=IDENTITY, credential=credential())
    harness.store.reads = 0
    harness.store.before_read = {read: lambda: harness.store.remove(record.reference)}

    with pytest.raises(DisplacedProvisioningError):
        await provisioner.reprovision(
            record.reference, identity=IDENTITY, credential=credential("rotated")
        )

    acts = await provisioner.recent_acts(limit=10)
    displaced = next(act for act in acts if act.revision == 2)
    assert displaced.account is not None
    assert displaced.account.state is ProvisioningState.PENDING


# --- ADR-0149 §5's two interleavings ---------------------------------------


async def test_a_disconnection_between_the_pending_entry_and_the_credential_write(
    harness: ProvisionerHarness,
) -> None:
    """ADR-0149 §14: the disconnect interleaving §5 exists for.

    A re-provisioning that has appended its pending entry and paused, a
    disconnection that lands between that entry and the credential write, and the
    write landing afterwards. The disconnection deletes every slot the store then
    names — the pending one and the previously active one — the reference is left
    with no live record, and the slot the displaced write created is deleted by a
    **re-run** of the disconnection.

    A test that disconnects only a quiescent reference satisfies none of this.
    """
    provisioner = _subject(harness)
    record = await provisioner.provision(identity=IDENTITY, credential=credential())
    held = harness.secrets.suspend_next_write()
    rotating = asyncio.ensure_future(
        provisioner.reprovision(
            record.reference, identity=IDENTITY, credential=credential("rotated")
        )
    )
    await held.reached()

    assert await provisioner.disconnect(record.reference) is not None
    held.release()
    with pytest.raises(DisplacedProvisioningError):
        await rotating

    assert await provisioner.connected() == ()
    assert len(harness.keyring.backing) == 1
    assert await provisioner.disconnect(record.reference) is None
    assert len(harness.keyring.backing) == 0


async def test_a_re_provisioning_inside_a_disconnections_deletion_window_survives(
    harness: ProvisionerHarness,
) -> None:
    """ADR-0149 §14: the inverse interleaving §5's revision cutoff exists for.

    A disconnection whose removal entry has landed and whose deletion pass has not
    yet run; a re-provisioning that appends its pending entry and writes its
    credential in that window; the deletion pass running afterwards. The
    re-provisioned slot **survives**, and an implementation that deletes every slot
    the store names *at deletion time* fails this.
    """
    provisioner = _subject(harness)
    record = await provisioner.provision(identity=IDENTITY, credential=credential())

    async def rotate() -> None:
        await provisioner.reprovision(
            record.reference, identity=IDENTITY, credential=credential("rotated")
        )

    harness.store.before_slots_below = rotate
    await provisioner.disconnect(record.reference)

    live = await provisioner.connected()
    assert [record.reference for record in live] == [record.reference]
    assert live[0].state is ProvisioningState.ACTIVE
    assert len(harness.keyring.backing) == 1


# --- ADR-0149 §1, §3, §8: the confinement clauses ---------------------------


async def test_the_provisioner_never_reads_a_credential(tmp_path: Path) -> None:
    """ADR-0149 §1, §14: it calls ``set`` and ``delete`` and never calls ``get``.

    Driven across every member, because an assertion over one operation would
    prove it for that operation alone.
    """
    store = SqliteConnectionStore(path=tmp_path / "connections.db")
    counting = CountingSecrets(FakeSecretStore(scope=SecretScope.INTEGRATION))
    provisioner = KeyringConnectionProvisioner(store=store, secrets=counting)
    try:
        record = await provisioner.provision(identity=IDENTITY, credential=credential())
        await provisioner.reprovision(
            record.reference, identity=IDENTITY, credential=credential("rotated")
        )
        await provisioner.connected()
        await provisioner.recent_acts(limit=10)
        await provisioner.disconnect(record.reference)
        await provisioner.purge()
    finally:
        store.close()

    assert "get" not in counting.calls
    assert set(counting.calls) == {"set", "delete"}


async def test_a_provisioning_act_appends_rather_than_overwriting(
    harness: ProvisionerHarness,
) -> None:
    """ADR-0149 §14: the store still answers what the previous act recorded."""
    provisioner = _subject(harness)
    record = await provisioner.provision(identity="first", credential=credential())

    await provisioner.reprovision(
        record.reference, identity="second", credential=credential("rotated")
    )

    history = await harness.store.entries_for(record.reference)
    assert [entry.identity for entry in history] == ["first", "first", "second", "second"]


async def test_the_purge_reaches_no_other_scope_or_installation(tmp_path: Path) -> None:
    """ADR-0149 §14: scope-confined by construction (ADR-0125 §2).

    Two subjects over **one** backing, differing only in scope, because two
    subjects holding separate maps could not observe each other's entries however
    the adapter composed its coordinates — so the pairing alone would prove
    nothing.
    """
    backing = SecretBacking()
    integration = FakeSecretStore(scope=SecretScope.INTEGRATION, backing=backing)
    provider = FakeSecretStore(scope=SecretScope.PROVIDER, backing=backing)
    await provider.set(
        SecretName(scope=SecretScope.PROVIDER, key="api-key"), credential("provider")
    )
    store = SqliteConnectionStore(path=tmp_path / "connections.db")
    provisioner = KeyringConnectionProvisioner(store=store, secrets=integration)
    try:
        await provisioner.provision(identity=IDENTITY, credential=credential())
        assert len(backing) == 2

        await provisioner.purge()
    finally:
        store.close()

    assert len(backing) == 1
    assert await provider.get(SecretName(scope=SecretScope.PROVIDER, key="api-key")) is not None


async def test_a_keyring_failure_is_never_reported_as_nothing_to_purge(
    harness: ProvisionerHarness,
) -> None:
    """ADR-0153 §4: an unavailable keyring is the deployment condition it is."""
    provisioner = _subject(harness)
    await provisioner.provision(identity=IDENTITY, credential=credential())
    harness.keyring.become_unavailable()

    with pytest.raises(SecretStoreError):
        await provisioner.purge()

    assert _entries(harness.store) != []


async def test_a_disconnection_failure_chains_the_keyring_error(
    harness: ProvisionerHarness,
) -> None:
    """ADR-0151 §2a: the underlying ``SecretStoreError`` is chained as the cause.

    Nothing is discarded and the seam's own classification is not re-made; what
    the conversion adds is a class that says what the *act* did.
    """
    provisioner = _subject(harness)
    record = await provisioner.provision(identity=IDENTITY, credential=credential())
    harness.keyring.fail(SecretMethod.DELETE, Disclosure.VERBATIM)

    with pytest.raises(ResidualCredentialError) as caught:
        await provisioner.disconnect(record.reference)

    assert isinstance(caught.value.__cause__, SecretStoreError)


# --- ADR-0151 §11: the reference survives the frame floor -------------------


#: The widest reference ADR-0151 §11 lets a factory mint. Every payload case below
#: uses one, because the bound is what the arithmetic is done against.
_MAXIMAL_REFERENCE = "r" * CONNECTION_REFERENCE_MAX_BYTES

#: The payload budget ``hub_max_frame_bytes`` leaves at its 1024-byte floor
#: (ADR-0085 §8c, §8d). The one number ADR-0151 §11's clause is stated over.
_FLOOR_BUDGET = 512


def _maximal(harness: ProvisionerHarness) -> KeyringConnectionProvisioner:
    """The subject, rewired to mint the widest reference §11 permits."""
    return KeyringConnectionProvisioner(
        store=harness.store,
        secrets=harness.secrets,
        mint_reference=lambda: _MAXIMAL_REFERENCE,
    )


async def _raised(call: Awaitable[Any]) -> AssistantError:
    """Run ``call`` and return the failure it raised."""
    with pytest.raises(AssistantError) as caught:
        await call
    return caught.value


@pytest.mark.parametrize("arm", ["credential-write", "activation", "disconnection"])
async def test_every_reference_carrying_failure_survives_the_frame_floor(
    harness: ProvisionerHarness, arm: str
) -> None:
    """ADR-0151 §11: the whole payload fits the budget the floor leaves.

    Stated over **the class** rather than over a list of names, so a class added
    later carrying a reference inherits the bound instead of needing the clause
    amended — which is why this case is parametrised by the *act* that reaches
    each one rather than by the class it produces.

    ADR-0085 §10a nulls ``details`` before it truncates a message, so a payload
    that has to be reduced is one that arrives **without its reference** — and on
    the two classes ``connect_account`` raises, that is the only handle the caller
    will ever have, because the mint made it.
    """
    provisioner = _maximal(harness)
    if arm == "credential-write":
        harness.keyring.fail(SecretMethod.SET, Disclosure.VERBATIM)
        failure = await _raised(provisioner.provision(identity=IDENTITY, credential=credential()))
    elif arm == "activation":
        harness.store.commit_then_fail_at = {2}
        failure = await _raised(provisioner.provision(identity=IDENTITY, credential=credential()))
    else:
        record = await provisioner.provision(identity=IDENTITY, credential=credential())
        harness.keyring.fail(SecretMethod.DELETE, Disclosure.VERBATIM)
        failure = await _raised(provisioner.disconnect(record.reference))

    payload = error_payload(failure, max_bytes=_FLOOR_BUDGET)

    assert payload["reduced"] is False
    assert payload["details"] == {"reference": _MAXIMAL_REFERENCE}
    assert len(str(failure).encode("utf-8")) <= MESSAGE_MAX_BYTES


async def test_no_failure_message_names_the_identity_or_the_credential(
    harness: ProvisionerHarness,
) -> None:
    """ADR-0151 §2a: no class on this surface names either value, or any part of one.

    The identity is Tier 1 personal data (ADR-0149 §3) and the credential is Tier
    0; what a refusal names is the reference, which ADR-0149 §3 rules a non-secret
    handle chosen by code.
    """
    provisioner = _subject(harness)
    harness.keyring.fail(SecretMethod.SET, Disclosure.VERBATIM)

    failure = await _raised(
        provisioner.provision(identity="secret-account", credential=credential("hunter2"))
    )

    assert "secret-account" not in str(failure)
    assert "hunter2" not in str(failure)
