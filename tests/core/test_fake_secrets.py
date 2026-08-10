"""The canonical keyring fake passes both shared conformance suites (ADR-0125 §11).

Two bindings, because there are two Protocols and
``tests/core/test_protocol_triad.py`` enumerates every one of them: the fake runs
through the narrow suite as a ``Secrets`` and through the wide one as itself, which
is what turns ADR-0125 §1's "one object satisfies both structurally" from an
assertion into a test.

Below the bindings are the fake's own capabilities — the two switches ADR-0125 §11
requires it to carry, and the coordinate composition the isolation cases rest on.
None of that is contract, but each is what makes a *contract* obligation reachable
from a test at all, so a capability that quietly stopped working would take the
obligation's meaning with it while leaving the suite green. The redaction case's
negative control is the sharpest of these: if the fake stopped building a
disclosing backend error, every "the plaintext is absent from the surfaced error"
assertion would pass while proving nothing.
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING

import pytest
from secret_contract import (
    BOUND_SCOPE,
    OTHER_SCOPE,
    PLAINTEXT,
    WITNESS,
    Isolation,
    SecretsContract,
    SecretStoreContract,
    checkable_disclosures,
    held,
    secret_name,
)

from ai_assistant.core.errors import SecretStoreError, SecretStoreUnavailableError
from ai_assistant.core.protocols import Secrets, SecretStore
from ai_assistant.core.types import SecretName, SecretScope
from ai_assistant.testing import (
    DEFAULT_INSTALLATION,
    OTHER_INSTALLATION,
    Disclosure,
    FakeSecrets,
    FakeSecretStore,
    SecretBacking,
    SecretMethod,
    disclosure_of,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Iterator

    from ai_assistant.core.types import SecretValue


class FakeSecretHooks:
    """The four hooks both suites take, supplied once for the one canonical fake.

    Shared rather than written twice, because the fake is one class: the narrow
    binding and the wide one differ only in which suite they run and which fixture
    hands the subject over.
    """

    async def given(self, secrets: Secrets, name: SecretName, value: SecretValue) -> None:
        """Arrange through the fake's own ``set``.

        The narrow suite has no contract-level way to write — that absence is the
        property it tests — so it asks the subject it was handed. This subject
        happens to have a write, so the arrangement runs through the store's own
        path rather than reaching in behind it.
        """
        assert isinstance(secrets, SecretStore)
        await secrets.set(name, value)

    def paired_over_one_backing(self, *, differing: Isolation) -> tuple[Secrets, Secrets]:
        """Two subjects over one :class:`SecretBacking`, differing in one fact.

        One backing is what gives the isolation cases teeth: two fakes holding
        separate maps could not observe each other's entries however either
        composed its coordinates, so the pairing alone would prove nothing.
        """
        backing = SecretBacking()
        first = FakeSecretStore(
            scope=BOUND_SCOPE, installation=DEFAULT_INSTALLATION, backing=backing
        )
        second = (
            FakeSecretStore(scope=OTHER_SCOPE, installation=DEFAULT_INSTALLATION, backing=backing)
            if differing is Isolation.SCOPE
            else FakeSecretStore(
                scope=BOUND_SCOPE, installation=OTHER_INSTALLATION, backing=backing
            )
        )
        return first, second

    @contextlib.contextmanager
    def unavailable(self, secrets: Secrets) -> Iterator[None]:
        """Drive the fake into ADR-0125 §7's state, and back out of it.

        Restored on the way out so the case can read its witness back — a refusal
        changes nothing, and proving that requires a subject that can answer again
        afterwards.
        """
        assert isinstance(secrets, FakeSecretStore)
        secrets.become_unavailable()
        try:
            yield
        finally:
            secrets.become_available()

    def arm_disclosing_failure(
        self, secrets: Secrets, *, method: SecretMethod, disclosure: Disclosure
    ) -> None:
        """Arm the fake's per-method, per-derivation failure switch."""
        assert isinstance(secrets, FakeSecretStore)
        secrets.fail(method, disclosure)


class TestFakeSecretsContract(FakeSecretHooks, SecretsContract):
    """Runs the canonical fake through the shared ``Secrets`` conformance suite."""

    @pytest.fixture
    def secrets(self) -> Secrets:
        return FakeSecretStore(scope=BOUND_SCOPE, installation=DEFAULT_INSTALLATION)


class TestFakeSecretStoreContract(FakeSecretHooks, SecretStoreContract):
    """Runs the canonical fake through the shared ``SecretStore`` suite.

    Every obligation of the narrow suite is inherited and binds this same subject
    through the reading face, so nothing here is a second object standing in for
    the one under test.
    """

    @pytest.fixture
    def store(self) -> SecretStore:
        return FakeSecretStore(scope=BOUND_SCOPE, installation=DEFAULT_INSTALLATION)


# --- the fake's own capabilities, and the negative controls behind them -------


def test_the_narrow_fake_is_the_store_fake() -> None:
    """One class under two names, which is ADR-0125 §1's seam rather than two seams.

    §11 rules a single canonical fake — "an in-memory implementation of
    ``SecretStore``" — and §1 rules one implementation class and one keyring
    backing. What forces the second *name* is the triad check, which enumerates
    every Protocol in ``core/protocols.py`` and wants a ``Fake<Protocol>`` for
    each. Pinned here so a later lane that reaches for a separate narrow fake
    finds the decision rather than the omission.
    """
    assert FakeSecrets is FakeSecretStore


@pytest.mark.parametrize("method", list(SecretMethod), ids=str)
@pytest.mark.parametrize("disclosure", list(Disclosure), ids=str)
async def test_the_armed_backend_error_really_quotes_the_derivation(
    method: SecretMethod, disclosure: Disclosure
) -> None:
    """The redaction case's negative control (ADR-0125 §11).

    The suite asserts that a derivation of the plaintext is **absent** from the
    error the subject surfaces. That assertion is satisfied for free by a fake that
    never built a disclosing backend error in the first place — so what makes the
    obligation real is that the fake did model one, per method and per derivation,
    over the plaintext the call was about: the value held for the name on ``get``
    and ``delete``, the value it was given on ``set``.
    """
    store = FakeSecretStore(scope=BOUND_SCOPE)
    await store.set(WITNESS, held())
    store.fail(method, disclosure)

    calls: dict[SecretMethod, Callable[[], Awaitable[object]]] = {
        SecretMethod.GET: lambda: store.get(WITNESS),
        SecretMethod.SET: lambda: store.set(WITNESS, held()),
        SecretMethod.DELETE: lambda: store.delete(WITNESS),
    }

    with pytest.raises(SecretStoreError):
        await calls[method]()

    modelled = store.last_backend_failure
    assert modelled is not None
    assert disclosure_of(disclosure, PLAINTEXT) in modelled


async def test_the_surfaced_error_chains_no_disclosing_cause() -> None:
    """A chained cause would put the plaintext in every traceback (ADR-0125 §6).

    §11 binds the surfaced error's message, its arguments and its ``repr``, and a
    ``raise … from exc`` satisfies all three while disclosing the value through the
    one rendering none of them covers. The fake therefore builds its backend error
    and drops it, which is the behaviour a conforming adapter owes too.
    """
    store = FakeSecretStore(scope=BOUND_SCOPE)
    await store.set(WITNESS, held())
    store.fail(SecretMethod.GET, Disclosure.VERBATIM)

    with pytest.raises(SecretStoreError) as raised:
        await store.get(WITNESS)

    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None


async def test_an_armed_failure_fires_once_and_then_the_store_answers() -> None:
    """ "Make the *next* call fail" rather than "fail from now on".

    A latching switch would make every case that arms one end by discarding the
    subject; a one-shot lets a case assert what the store holds afterwards, which
    is what "a failure left the entry where it was" needs.
    """
    store = FakeSecretStore(scope=BOUND_SCOPE)
    await store.set(WITNESS, held())
    store.fail(SecretMethod.GET, Disclosure.PREFIX)

    with pytest.raises(SecretStoreError):
        await store.get(WITNESS)

    found = await store.get(WITNESS)
    assert found is not None
    assert found.get_secret_value() == PLAINTEXT


async def test_the_unavailable_switch_is_reversible() -> None:
    """Both directions, because every doubled refusal case reads its witness back."""
    store = FakeSecretStore(scope=BOUND_SCOPE)
    await store.set(WITNESS, held())

    store.become_unavailable()
    with pytest.raises(SecretStoreUnavailableError):
        await store.get(WITNESS)

    store.become_available()
    found = await store.get(WITNESS)
    assert found is not None


async def test_the_coordinate_stays_injective_when_a_path_holds_the_joiner() -> None:
    """The length prefix is why, and it is not decoration (ADR-0125 §2).

    A backend coordinate composed by joining installation, scope and key must be
    injective, or two distinct names are one entry and one credential silently
    overwrites another. A ``key`` can never contribute an ambiguity because §2
    forbids ``:`` and ``/`` outright — but an *installation* is a filesystem path
    that this contract does not constrain, so the composition has to survive one
    that contains the joining character.
    """
    backing = SecretBacking()
    first = FakeSecretStore(scope=BOUND_SCOPE, installation="/data/a:b", backing=backing)
    second = FakeSecretStore(scope=BOUND_SCOPE, installation="/data/a", backing=backing)

    await first.set(WITNESS, held("the first installation's"))
    await second.set(WITNESS, held("the second installation's"))

    held_by_first = await first.get(WITNESS)
    assert held_by_first is not None
    assert held_by_first.get_secret_value() == "the first installation's"
    assert len(backing) == 2


async def test_neither_the_subject_nor_its_backing_renders_a_stored_value() -> None:
    """Asserted over the pair, because the subject's ``repr`` reaches the backing.

    A generated ``repr`` over ``self.__dict__`` would satisfy the class's own
    obligation and breach it through the object it holds, which is exactly how a
    redaction written once at the outer layer leaks.
    """
    backing = SecretBacking()
    store = FakeSecretStore(scope=BOUND_SCOPE, backing=backing)
    await store.set(WITNESS, held())

    assert PLAINTEXT not in repr(store)
    assert PLAINTEXT not in repr(backing)
    assert BOUND_SCOPE.value in repr(store), "the repr should still say what it is bound to"


async def test_a_scope_bound_subject_refuses_every_other_member() -> None:
    """Every member, not the one the suite happens to parametrise over.

    ``SecretScope`` is closed at three, and a subject bound to one must refuse the
    other two identically — ADR-0125 §2's boundary is "the scope this instance is
    bound to", not "the scopes somebody remembered to test".
    """
    store = FakeSecretStore(scope=BOUND_SCOPE)

    for scope in SecretScope:
        if scope is BOUND_SCOPE:
            continue
        with pytest.raises(ValueError, match="bound to"):
            await store.get(secret_name(scope=scope))


def test_every_derivation_the_adr_forbids_is_checkable_over_a_real_plaintext() -> None:
    """The suite's helper drops nothing it should be asserting (ADR-0125 §6, §11).

    :func:`~secret_contract.checkable_disclosures` skips a derivation it cannot
    compute or that is entirely whitespace, which is right for a blank or
    unencodable value and would be a silent hole for an ordinary one. Over the
    plaintext the cases actually store, every member of §6's list survives — so a
    derivation added to that list arrives as a case rather than as a skip.
    """
    assert set(checkable_disclosures(PLAINTEXT)) == set(Disclosure)
