"""What a device holds about its hub, and the two acts that change it.

ADR-0124 §6's hand-off performed at the device, and §8's unenrolment. The subject
is :mod:`ai_assistant.wire.enrolment` over the canonical ``FakeSecretStore``, bound
to ``ENROLMENT`` — which is the wiring ADR-0125 §8 requires, so a store bound to any
other scope refuses these names outright rather than answering them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from pydantic import SecretStr

from ai_assistant.core.errors import SecretStoreUnavailableError
from ai_assistant.core.logging import _SENSITIVE_KEY_PARTS
from ai_assistant.core.types import SecretName, SecretScope
from ai_assistant.testing import FakeSecretStore
from ai_assistant.wire.credential import mint_credential
from ai_assistant.wire.enrolment import (
    CREDENTIAL_KEY,
    HUB_IDENTITY_KEY,
    credential_name,
    hub_identity_name,
    read_enrolment,
    remove_enrolment,
    store_enrolment,
)
from ai_assistant.wire.errors import IncompleteEnrolmentError, NotEnrolledError
from ai_assistant.wire.overlay import MAX_OVERLAY_IDENTITY_BYTES

if TYPE_CHECKING:
    from ai_assistant.core.types import SecretValue

HUB = "nQ8xYt2CNTRL"


class RecordingStore:
    """A ``SecretStore`` that notes the order of the writes it passes through.

    A delegating wrapper rather than a patched method, because the order under test
    is a property of :func:`store_enrolment` and the subject it drives must stay the
    canonical fake — a store with one method replaced is a subject nothing else in
    the corpus has run against.
    """

    def __init__(self, inner: FakeSecretStore) -> None:
        self.inner = inner
        self.written: list[str] = []

    async def get(self, name: SecretName) -> SecretValue | None:
        return await self.inner.get(name)

    async def set(self, name: SecretName, value: SecretValue) -> None:
        self.written.append(name.key)
        await self.inner.set(name, value)

    async def delete(self, name: SecretName) -> bool:
        return await self.inner.delete(name)


def _held(plaintext: str) -> SecretValue:
    """A value built the way a caller builds one, for arranging a half-written state."""
    return SecretStr(plaintext)


@pytest.fixture
def store() -> FakeSecretStore:
    """An empty ``ENROLMENT``-scoped store, as a composition root would wire one."""
    return FakeSecretStore(scope=SecretScope.ENROLMENT)


async def test_a_stored_pair_reads_back_whole(store: FakeSecretStore) -> None:
    """The ordinary path: both values in, both values out, the secret still wrapped."""
    credential = mint_credential()
    await store_enrolment(store, hub_identity=HUB, credential=credential)

    held = await read_enrolment(store)

    assert held.hub_identity == HUB
    assert held.credential.get_secret_value() == credential


async def test_the_credential_is_returned_still_wrapped(store: FakeSecretStore) -> None:
    """ADR-0125 §3's one authorised unwrap belongs to the connect path, not here.

    A read that handed back a plain ``str`` would put the credential in front of
    every caller of this module, and the type whose default rendering is
    ``**********`` is the mechanism that makes a disclosure deliberate rather than
    accidental.
    """
    credential = mint_credential()
    await store_enrolment(store, hub_identity=HUB, credential=credential)

    held = await read_enrolment(store)

    assert credential not in repr(held.credential)
    assert credential not in str(held.credential)


async def test_a_device_holding_nothing_is_not_enrolled(store: FakeSecretStore) -> None:
    """The state a fresh device is in, and the state §8's unenrolment leaves."""
    with pytest.raises(NotEnrolledError) as raised:
        await read_enrolment(store)

    assert not isinstance(raised.value, IncompleteEnrolmentError)
    assert "ai-assistant-device enrol" in str(raised.value)


async def test_a_credential_without_a_hub_identity_is_refused(store: FakeSecretStore) -> None:
    """ADR-0124 §6's own sentence, as a test.

    > holding the credential without the hub identity is an incomplete enrolment
    > the client refuses to connect on

    It is the dangerous half: a device holding a credential and no identity has
    nothing to check a destination against, so it would hand the credential to
    whichever node answered.
    """
    await store.set(credential_name(), _held(mint_credential()))

    with pytest.raises(IncompleteEnrolmentError):
        await read_enrolment(store)


async def test_a_hub_identity_without_a_credential_is_refused(store: FakeSecretStore) -> None:
    """The other half, which a crash between the two writes can produce (ADR-0125 §4).

    Refused for the same reason and with a different sentence, so an owner can tell
    which act to repeat.
    """
    await store.set(hub_identity_name(), _held(HUB))

    with pytest.raises(IncompleteEnrolmentError):
        await read_enrolment(store)


async def test_an_unreachable_keyring_is_not_an_unenrolled_device(
    store: FakeSecretStore,
) -> None:
    """ADR-0125 §7's clause, at the one call site whose behaviour it argues about.

    "A client would report the owner as unenrolled while they are enrolled" is the
    failure §7 exists to prevent, and this module is where the two would otherwise
    be flattened: an implementation that caught the store's error and reported
    "not enrolled" would look correct and be exactly wrong.
    """
    await store_enrolment(store, hub_identity=HUB, credential=mint_credential())
    store.become_unavailable()

    with pytest.raises(SecretStoreUnavailableError):
        await read_enrolment(store)


async def test_the_identity_is_written_before_the_credential(store: FakeSecretStore) -> None:
    """So a crash between the two cannot leave the half ADR-0124 §6 names.

    Both incomplete states are refused, so the ordering buys nothing about
    *correctness* — it buys which of the two an interrupted intake leaves behind,
    and the one to avoid is the credential sitting on a device with nothing to
    check a destination against.
    """
    recorder = RecordingStore(store)

    await store_enrolment(recorder, hub_identity=HUB, credential=mint_credential())

    assert recorder.written == [HUB_IDENTITY_KEY, CREDENTIAL_KEY]


async def test_intake_refuses_a_credential_the_scheme_could_not_have_minted(
    store: FakeSecretStore,
) -> None:
    """Refused now rather than as a hub's refusal at the first connect.

    ADR-0124 §7 refuses a malformed credential at the listener as one "that did not
    verify", which is the right answer there and an unhelpful one here: the owner
    is holding a value they just copied, and "check it was copied whole" is a better
    sentence than "the credential presented does not verify".
    """
    with pytest.raises(ValueError, match="copied whole"):
        await store_enrolment(store, hub_identity=HUB, credential="not-a-credential")

    assert await store.get(hub_identity_name()) is None, "a refused intake stored a half"


async def test_a_refused_credential_is_never_echoed(store: FakeSecretStore) -> None:
    """ADR-0125 §6 binds every exception this system raises about a value.

    A refusal is the likelier leak of the two, because the obvious message contains
    one — and the value here has just been typed by the owner, so an echo would put
    it in a terminal's scrollback as well as in whatever reads the error.
    """
    mistyped = f"{mint_credential()}xyz"

    with pytest.raises(ValueError, match="copied whole") as raised:
        await store_enrolment(store, hub_identity=HUB, credential=mistyped)

    assert mistyped not in str(raised.value)
    assert mistyped[:8] not in str(raised.value)


@pytest.mark.parametrize(
    ("identity", "reason"),
    [
        ("", "blank"),
        ("   ", "whitespace only"),
        ("h" * (MAX_OVERLAY_IDENTITY_BYTES + 1), "over the bound"),
        ("\ud800", "no UTF-8 form"),
    ],
)
async def test_intake_refuses_a_hub_identity_no_overlay_produces(
    store: FakeSecretStore, identity: str, reason: str
) -> None:
    """Including the surrogate, which survives every other check.

    ``"\\ud800"`` is non-blank, is one character, and has no byte length at all —
    measuring it *is* encoding it — so a bound written as ``len(x.encode())`` raises
    ``UnicodeEncodeError`` rather than the ``ValueError`` this refusal promises.
    """
    del reason

    with pytest.raises(ValueError):  # noqa: PT011 - the type is the assertion
        await store_enrolment(store, hub_identity=identity, credential=mint_credential())

    assert await store.get(credential_name()) is None, "a refused intake stored the credential"


async def test_intake_over_a_live_enrolment_replaces_it(store: FakeSecretStore) -> None:
    """Rotation is one act, which is why ADR-0125 §4 makes ``set`` replace.

    ADR-0124 §6 makes re-enrolling a live device "a **single act**… and the two
    halves are not separable". A device that had to remove before it could store
    would hold nothing in between, and a crash there would leave it unenrolled.
    """
    await store_enrolment(store, hub_identity=HUB, credential=mint_credential())
    rotated = mint_credential()

    await store_enrolment(store, hub_identity=HUB, credential=rotated)

    held = await read_enrolment(store)
    assert held.credential.get_secret_value() == rotated


async def test_unenrolment_removes_both_and_says_what_it_removed(
    store: FakeSecretStore,
) -> None:
    """ADR-0124 §8's device-side act, and ADR-0125 §5's "say what you did"."""
    await store_enrolment(store, hub_identity=HUB, credential=mint_credential())

    removed = await remove_enrolment(store)

    assert removed.credential_removed is True
    assert removed.hub_identity_removed is True
    assert removed.removed_anything is True
    assert await store.get(credential_name()) is None
    assert await store.get(hub_identity_name()) is None


async def test_unenrolment_is_safe_to_repeat(store: FakeSecretStore) -> None:
    """ "It works whether or not the enrolment it removes is still live" (§8).

    The case an owner reaches for it in is usually one where something has already
    gone wrong, so an act that raised the second time it ran would be the wrong
    surface for it.
    """
    await store_enrolment(store, hub_identity=HUB, credential=mint_credential())
    await remove_enrolment(store)

    again = await remove_enrolment(store)

    assert again.removed_anything is False


async def test_unenrolment_on_a_device_that_holds_a_half_removes_it(
    store: FakeSecretStore,
) -> None:
    """A purge composed from the names its holder knows (ADR-0125 §5).

    There is no enumeration, so this act is the only thing that removes these two
    entries — and a device left in the half-written state is one whose purge has to
    reach the half that is there.
    """
    await store.set(credential_name(), _held(mint_credential()))

    removed = await remove_enrolment(store)

    assert removed.credential_removed is True
    assert removed.hub_identity_removed is False
    assert await store.get(credential_name()) is None


async def test_the_two_names_are_enrolment_scoped_and_distinct() -> None:
    """The scope is a property of the object a consumer holds (ADR-0125 §2, §8).

    A store bound to another scope refuses these names rather than answering them,
    which is what makes "the wire client's enrolment paths hold an
    ``ENROLMENT``-scoped store" mechanical instead of advisory.
    """
    assert credential_name().scope is SecretScope.ENROLMENT
    assert hub_identity_name().scope is SecretScope.ENROLMENT
    assert credential_name() != hub_identity_name()

    elsewhere = FakeSecretStore(scope=SecretScope.INTEGRATION)
    with pytest.raises(ValueError, match="scope"):
        await elsewhere.get(credential_name())


def test_the_credential_key_is_one_the_log_redaction_covers() -> None:
    """ADR-0124 §6: "no implementation may give it a name that redaction misses".

    ``core/logging.py`` redacts by *key name*, matching ``credential`` as a
    case-insensitive substring, so the name is chosen to be covered by it rather
    than to be pretty.
    """
    assert any(part in CREDENTIAL_KEY.casefold() for part in _SENSITIVE_KEY_PARTS)
