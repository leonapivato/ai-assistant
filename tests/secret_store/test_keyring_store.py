"""Both shared suites, run against the real adapter (ADR-0125 §11).

> **Normative.** The lane that lands the keyring-backed implementation runs **both
> shared suites against that adapter**, over a backend it controls, so every
> obligation the suites carry — the scope and installation refusals, the unavailable
> state, the locked backend, and §6's redaction over every derivation on every
> method — is proved against the real wrapper and not only against the fake.

That is the whole of this module's design. The subject is
:class:`~ai_assistant.secret_store.KeyringSecretStore` itself; only the backing
underneath it is doubled, because a keyring that cannot be reached and one whose
own error text names the credential are states no real backend can be asked for on
cue. The suites are inherited unchanged — nothing here weakens or skips a case, and
the four hooks are the only overrides.

The two obligations "no suite running against any subject can express" — that a
selection finding nothing usable raises rather than falling back, and that no
backend storing a value without the operating system's own access control is ever
selected — are in ``test_backend_selection.py``, because both are about which
backend gets *selected* and "a subject handed to a suite has already been
constructed".
"""

from __future__ import annotations

import contextlib
import logging
from typing import TYPE_CHECKING

import pytest
from controllable import ControllableKeyring
from secret_contract import (
    BOUND_SCOPE,
    OTHER_SCOPE,
    PLAINTEXT,
    WITNESS,
    Isolation,
    SecretsContract,
    SecretStoreContract,
    assert_discloses_nothing,
    assert_no_log_discloses,
    held,
    secret_name,
)

from ai_assistant.core.errors import SecretStoreError, SecretStoreUnavailableError
from ai_assistant.core.protocols import Secrets, SecretStore
from ai_assistant.core.types import SecretScope
from ai_assistant.secret_store import KeyringSecretStore
from ai_assistant.testing import (
    DEFAULT_INSTALLATION,
    OTHER_INSTALLATION,
    Disclosure,
    SecretMethod,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Iterator

    from ai_assistant.core.types import SecretName, SecretValue


def store_over(
    backing: ControllableKeyring,
    *,
    scope: SecretScope = BOUND_SCOPE,
    installation: str = DEFAULT_INSTALLATION,
) -> KeyringSecretStore:
    """One real adapter over a backend a test controls.

    The selector is a closure returning the same object every time, which is what
    ADR-0125 §7's "the backend is resolved on the first call" permits and what makes
    a backend driven unavailable mid-test observable to the adapter: it asks again
    on every call rather than caching an answer from the first.
    """
    return KeyringSecretStore(scope=scope, installation=installation, select=lambda: backing)


def refusing_store(scope: SecretScope = BOUND_SCOPE) -> KeyringSecretStore:
    """An adapter whose selection finds nothing usable, as a headless box does."""

    def refuse() -> ControllableKeyring:
        msg = "no protected backend on this machine"
        raise SecretStoreUnavailableError(msg)

    return KeyringSecretStore(scope=scope, installation=DEFAULT_INSTALLATION, select=refuse)


class KeyringStoreHooks:
    """The four hooks both suites take, supplied once for the one adapter."""

    backing: ControllableKeyring

    @pytest.fixture(autouse=True)
    def _one_backing(self) -> None:
        """The machine's keyring, held so the two switch hooks can reach it.

        Held on the instance rather than read back off the subject, so no hook here
        reaches into the adapter: what a test drives is the backend it built, which
        is the same seam the constructor already takes.
        """
        self.backing = ControllableKeyring()

    @pytest.fixture
    def store(self) -> SecretStore:
        """The adapter under test, empty and bound to the suite's scope."""
        return store_over(self.backing)

    async def given(self, secrets: Secrets, name: SecretName, value: SecretValue) -> None:
        """Arrange through the adapter's own ``set``, not behind it."""
        assert isinstance(secrets, SecretStore)
        await secrets.set(name, value)

    def paired_over_one_backing(self, *, differing: Isolation) -> tuple[Secrets, Secrets]:
        """Two adapters over one backend, differing in exactly one binding.

        One backend is what gives either pair teeth: two adapters composing
        coordinates wrongly *can* observe each other here, which is the real
        deployment — one OS keyring holding every scope of every installation on the
        machine.
        """
        shared = ControllableKeyring()
        first = store_over(shared)
        second = (
            store_over(shared, scope=OTHER_SCOPE)
            if differing is Isolation.SCOPE
            else store_over(shared, installation=OTHER_INSTALLATION)
        )
        return first, second

    @contextlib.contextmanager
    def unavailable(self, secrets: Secrets) -> Iterator[None]:
        """Lock the backend under ``secrets`` for the duration of the block."""
        del secrets
        self.backing.available = False
        try:
            yield
        finally:
            self.backing.available = True

    def arm_disclosing_failure(
        self, secrets: Secrets, *, method: SecretMethod, disclosure: Disclosure
    ) -> None:
        """Make the backend's next call to ``method`` fail with a disclosing error."""
        del secrets
        self.backing.arm(method, disclosure)


class TestKeyringSecretStoreSecretsContract(KeyringStoreHooks, SecretsContract):
    """The adapter through the reading face (ADR-0125 §11)."""

    @pytest.fixture
    def secrets(self, store: SecretStore) -> Secrets:
        """The same subject, seen as a ``Secrets`` — not a second object."""
        return store


class TestKeyringSecretStoreContract(KeyringStoreHooks, SecretStoreContract):
    """The adapter through the whole seam (ADR-0125 §11)."""


# --- what only this lane can prove about the wrapper -------------------------


async def test_an_unresolvable_backend_raises_on_every_method() -> None:
    """§7's other half: unavailable at *selection*, not merely locked at the call.

    The suites drive the locked branch, because that is the one a backend object can
    be put into. This is the branch where there is no backend at all — and ADR-0125
    §7 makes the two "one visible state" deliberately, so both reach the same error
    and neither reaches ``None``.
    """
    store = refusing_store()

    with pytest.raises(SecretStoreUnavailableError):
        await store.get(WITNESS)
    with pytest.raises(SecretStoreUnavailableError):
        await store.set(WITNESS, held())
    with pytest.raises(SecretStoreUnavailableError):
        await store.delete(WITNESS)


async def test_the_argument_step_wins_over_an_unresolvable_backend() -> None:
    """And the argument step still comes first, with no backend to resolve at all.

    ADR-0125 §7 makes the precedence total: a call carrying a malformed name or
    value, or a well-formed name outside the instance's scope, raises ``ValueError``
    whatever the keyring's state, "**including when there is no backend at all**".
    An adapter that resolved first would report the machine's state to the caller
    least entitled to ask.
    """
    store = refusing_store()

    with pytest.raises(ValueError, match="scope"):
        await store.get(secret_name(scope=OTHER_SCOPE))
    with pytest.raises(ValueError, match="scope"):
        await store.delete(secret_name(scope=OTHER_SCOPE))


async def test_a_locked_backend_is_unavailable_and_a_rejected_call_is_not() -> None:
    """The two `keyring` families map to the two errors the corpus narrows for.

    ADR-0125 §6: "a keyring that is absent, locked or not running is a deployment
    condition a human clears, and retrying it is futile; a write the backend
    rejected may be transient". That distinction is worth a type check rather than a
    message match, and this is what makes it one here.

    **This is the other half of the classification** and it is what stops the
    unavailable branch from swallowing everything: an error the backend itself
    produced is an outcome of the *operation*, so it stays the wider type however
    the transport underneath is behaving.
    """
    backing = ControllableKeyring()
    store = store_over(backing)
    backing.available = False

    with pytest.raises(SecretStoreUnavailableError):
        await store.get(WITNESS)

    backing.available = True
    await store.set(WITNESS, held())
    backing.arm(SecretMethod.GET, Disclosure.VERBATIM)

    with pytest.raises(SecretStoreError) as raised:
        await store.get(WITNESS)
    assert not isinstance(raised.value, SecretStoreUnavailableError)


async def test_a_failing_backend_is_never_chained() -> None:
    """No backend exception becomes the surfaced error's cause or context (§6).

    The suites assert the *renderings*, which is the obligation; this asserts the
    mechanism that makes them hold, because it is the one an ordinary refactor
    breaks. Moving the ``raise`` back inside the ``except`` clause that caught the
    backend's error re-attaches it as ``__context__``, every rendering starts
    carrying the plaintext again, and nothing about the message changed.
    """
    backing = ControllableKeyring()
    store = store_over(backing)
    await store.set(WITNESS, held())
    backing.arm(SecretMethod.GET, Disclosure.VERBATIM)

    with pytest.raises(SecretStoreError) as raised:
        await store.get(WITNESS)

    assert backing.last_backend_failure is not None, "the case did not model a disclosure"
    assert PLAINTEXT in backing.last_backend_failure, "the case did not model a disclosure"
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None


async def test_distinct_names_compose_distinct_backend_coordinates() -> None:
    """The composed coordinate is injective over installation, scope and key (§2).

    Asserted over the backend's own map rather than through the seam, because the
    failure §2 exists to prevent is invisible from above: two names that collide on
    the backend are one secret silently overwriting another, and from the seam the
    second write simply looks like a write.
    """
    backing = ControllableKeyring()
    provider = store_over(backing, scope=SecretScope.PROVIDER)
    enrolment = store_over(backing, scope=SecretScope.ENROLMENT)
    elsewhere = store_over(backing, installation=OTHER_INSTALLATION)

    await provider.set(secret_name(scope=SecretScope.PROVIDER), held("a"))
    await enrolment.set(secret_name(scope=SecretScope.ENROLMENT), held("b"))
    await elsewhere.set(secret_name(), held("c"))

    assert len(backing.entries) == 3, "two distinct names composed one coordinate"
    assert len({service for service, _ in backing.entries}) == 3
    assert {username for _, username in backing.entries} == {"github"}


async def test_the_installation_is_length_prefixed_so_a_colon_cannot_shift_it() -> None:
    """Two installations whose paths differ only around the joining character (§2).

    A composition that simply joined the three components would map
    ``("/a:provider", key)`` and ``("/a", "provider", key)`` onto one coordinate.
    The length prefix pins where the installation ends, which is why ADR-0125 §2
    forbids ``:`` in a *key* but has nothing to say about an installation path.
    """
    backing = ControllableKeyring()
    innocent = store_over(backing, installation="/a", scope=SecretScope.PROVIDER)
    contrived = store_over(backing, installation="/a:provider", scope=SecretScope.PROVIDER)

    await innocent.set(secret_name(), held("the real one"))
    await contrived.set(secret_name(), held("the impostor"))

    survived = await innocent.get(secret_name())
    assert survived is not None
    assert survived.get_secret_value() == "the real one"
    assert len(backing.entries) == 2


@pytest.mark.parametrize("method", list(SecretMethod), ids=str)
@pytest.mark.parametrize("disclosure", list(Disclosure), ids=str)
async def test_a_backend_failure_the_library_never_wraps_reads_as_unavailable(
    method: SecretMethod, disclosure: Disclosure, caplog: pytest.LogCaptureFixture
) -> None:
    """An untranslated failure came from *under* the backend, so the keyring is unreachable.

    A backend turns every outcome it decides into a ``KeyringError``; what arrives
    instead came from the transport beneath it — the Secret Service backend speaks
    to ``secretstorage`` over D-Bus, and a service that goes away after selection
    surfaces as that stack's own exception. ADR-0125 §6 draws the line by "the
    correct response differs": a keyring "absent, locked or not running is a
    deployment condition a human clears", where "a write the backend *rejected* may
    be transient". A dead transport is the first, so it reads as unavailable — and
    that is also the safe direction, since the type is a subclass and every
    ``except SecretStoreError`` still catches it.

    An adapter catching only the library's hierarchy would instead let it out as a
    traceback, past every caller's error boundary and carrying whatever the backend
    put in its message — so this runs over every method and every derivation on the
    suites' own terms, because normalising the *type* while passing the *message* on
    would move the leak rather than close it.
    """
    backing = ControllableKeyring()
    store = store_over(backing)
    await store.set(WITNESS, held())
    backing.arm_untranslated(method, disclosure)
    calls: dict[SecretMethod, Callable[[], Awaitable[object]]] = {
        SecretMethod.GET: lambda: store.get(WITNESS),
        SecretMethod.SET: lambda: store.set(WITNESS, held()),
        SecretMethod.DELETE: lambda: store.delete(WITNESS),
    }

    with caplog.at_level(logging.DEBUG), pytest.raises(SecretStoreUnavailableError) as raised:
        await calls[method]()

    assert isinstance(raised.value, SecretStoreError), "the narrower type is still the wider one"
    assert backing.last_backend_failure is not None, "the case did not model a disclosure"
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None
    assert_discloses_nothing(raised.value, PLAINTEXT, context=(method, disclosure))
    assert_no_log_discloses(caplog.records, PLAINTEXT, context=(method, disclosure))
