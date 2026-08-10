"""What a device holds about its hub, and the two acts that change it.

ADR-0124 §6's hand-off performed at the device, and §8's unenrolment. The subject
is :mod:`ai_assistant.wire.enrolment` over the canonical ``FakeSecretStore``, bound
to ``ENROLMENT`` — which is the wiring ADR-0125 §8 requires, so a store bound to any
other scope refuses this name outright rather than answering it.
"""

from __future__ import annotations

import json

import pytest
from pydantic import SecretStr
from secret_contract import assert_discloses_nothing

from ai_assistant.core.errors import SecretStoreError, SecretStoreUnavailableError
from ai_assistant.core.logging import _SENSITIVE_KEY_PARTS
from ai_assistant.core.types import SECRET_VALUE_MAX_BYTES, SecretName, SecretScope, SecretValue
from ai_assistant.testing import Disclosure, FakeSecretStore, SecretMethod
from ai_assistant.wire.credential import mint_credential
from ai_assistant.wire.enrolment import (
    ENROLMENT_KEY,
    Enrolment,
    enrolment_name,
    read_enrolment,
    remove_enrolment,
    store_enrolment,
)
from ai_assistant.wire.errors import IncompleteEnrolmentError, NotEnrolledError
from ai_assistant.wire.overlay import MAX_OVERLAY_IDENTITY_BYTES

HUB = "nQ8xYt2CNTRL"
OTHER_HUB = "zK1mBv9QOTHR"


class CountingSecret(SecretStr):
    """A ``SecretStr`` that counts the unwraps performed on it."""

    unwraps: int = 0

    def get_secret_value(self) -> str:
        """Count the unwrap, then answer as the real type does."""
        type(self).unwraps += 1
        return super().get_secret_value()


class CountingStore:
    """A store whose reads hand back a value that counts its own unwraps.

    Delegating rather than patching, so the subject under test stays
    :mod:`ai_assistant.wire.enrolment` driven through the canonical fake.
    """

    def __init__(self, inner: FakeSecretStore) -> None:
        self.inner = inner

    async def get(self, name: SecretName) -> SecretValue | None:
        held = await self.inner.get(name)
        return None if held is None else CountingSecret(held.get_secret_value())

    async def set(self, name: SecretName, value: SecretValue) -> None:
        await self.inner.set(name, value)

    async def delete(self, name: SecretName) -> bool:
        return await self.inner.delete(name)


@pytest.fixture
def store() -> FakeSecretStore:
    """An empty ``ENROLMENT``-scoped store, as a composition root would wire one."""
    return FakeSecretStore(scope=SecretScope.ENROLMENT)


async def held_record(store: FakeSecretStore) -> str:
    """The record as it is actually stored, for the cases that are about its shape."""
    stored = await store.get(enrolment_name())
    assert stored is not None
    return stored.get_secret_value()


async def put(store: FakeSecretStore, plaintext: str) -> None:
    """Write a record directly, for arranging a state the intake cannot produce."""
    await store.set(enrolment_name(), SecretStr(plaintext))


async def test_a_stored_pair_reads_back_whole(store: FakeSecretStore) -> None:
    """The ordinary path: both values in, both values out, the secret still wrapped."""
    credential = mint_credential()
    await store_enrolment(store, hub_identity=HUB, credential=credential)

    assert await read_enrolment(store) == Enrolment(
        hub_identity=HUB, credential=SecretStr(credential)
    )


async def test_the_pair_occupies_one_entry(store: FakeSecretStore) -> None:
    """One name, which is what makes the act atomic (ADR-0125 §4).

    Asserted over the backing rather than through the seam, because the number of
    entries is exactly what a reader cannot see from above — and it is the fact the
    whole atomicity argument rests on.
    """
    await store_enrolment(store, hub_identity=HUB, credential=mint_credential())

    assert len(store.backing) == 1


async def test_the_credential_is_returned_still_wrapped(store: FakeSecretStore) -> None:
    """ADR-0125 §3's one authorised unwrap belongs to the connect frame, not here.

    A read that handed back a plain ``str`` would put the credential in front of
    every caller of this module, and the type whose default rendering is
    ``**********`` is the mechanism that makes a disclosure deliberate rather than
    accidental.
    """
    credential = mint_credential()
    await store_enrolment(store, hub_identity=HUB, credential=credential)

    found = await read_enrolment(store)

    assert credential not in repr(found.credential)
    assert credential not in str(found.credential)


async def test_a_device_holding_nothing_is_not_enrolled(store: FakeSecretStore) -> None:
    """The state a fresh device is in, and the state §8's unenrolment leaves."""
    with pytest.raises(NotEnrolledError) as raised:
        await read_enrolment(store)

    assert not isinstance(raised.value, IncompleteEnrolmentError)
    assert "ai-assistant-device enrol" in str(raised.value)


@pytest.mark.parametrize(
    ("record", "shape"),
    [
        ("not json at all", "not JSON"),
        ('["hub", "credential"]', "a list rather than an object"),
        ('{"credential": "x"}', "no hub member"),
        ('{"hub": "h"}', "no credential member"),
        ('{"hub": "", "credential": "x"}', "a blank hub"),
        ('{"hub": "   ", "credential": "x"}', "a whitespace-only hub"),
        ('{"hub": "h", "credential": ""}', "a blank credential"),
        ('{"hub": 7, "credential": "x"}', "a hub that is not a string"),
        ('{"hub": "h", "credential": null}', "a credential that is not a string"),
        ('{"hub": "h", "credential": "x"}', "a credential of no scheme this build mints"),
        ('{"hub": "h", "credential": "' + "c" * 300 + '"}', "a credential over the frame bound"),
        ('{"hub": "' + "h" * 300 + '", "credential": "x"}', "an identity over the bound"),
    ],
)
async def test_a_record_that_is_not_a_whole_pair_is_refused(
    store: FakeSecretStore, record: str, shape: str
) -> None:
    """ADR-0124 §6's refusal, over every way a record can fail to be a pair.

    > holding the credential without the hub identity is an incomplete enrolment
    > the client refuses to connect on

    One sentence for all of them, because the owner's act is the same and a taxonomy
    would only invite a branch that tried to use half a record.

    **The last three are the ones a shape check alone would let through**, and they
    are what ADR-0085 §9's "refused locally, before any I/O" is for: a credential no
    scheme mints, one over ADR-0085 §8d's connect bound, and an identity over the
    overlay bound are all whole-looking pairs that a socket would be opened for and
    that the frame builder would then refuse with a ``ValueError`` no adapter's
    error boundary declares — a traceback where ADR-0083's ruling 4 asks for a
    sentence.
    """
    del shape
    await put(store, record)

    with pytest.raises(IncompleteEnrolmentError):
        await read_enrolment(store)


async def test_a_refused_record_is_never_quoted(store: FakeSecretStore) -> None:
    """ADR-0125 §6 binds every exception this seam raises, and the record is Tier 0.

    A message quoting what failed to parse would be the disclosure that section
    forbids arriving through the error path — and the record holds the credential
    whether or not it parses.
    """
    credential = mint_credential()
    await put(store, f'{{"hub": "{HUB}", "credential-typo": "{credential}"}}')

    with pytest.raises(IncompleteEnrolmentError) as raised:
        await read_enrolment(store)

    assert credential not in str(raised.value)
    assert credential[:8] not in str(raised.value)


async def test_a_refused_record_discloses_nothing_through_a_chained_cause(
    store: FakeSecretStore,
) -> None:
    """The leak a message check cannot see (ADR-0125 §6).

    ``json.JSONDecodeError`` carries the text it failed on in its ``doc`` attribute,
    so a refusal written as the obvious ``raise IncompleteEnrolmentError(...) from
    exc`` keeps a live reference to the whole record — the credential included — on
    an object a handler may render attribute by attribute, and ``core/logging.py``
    redacts by *key name*, which ``doc`` is not one of.

    Asserted with the conformance suites' own helper, which walks the chain and the
    formatted traceback rather than the message alone, and over every derivation
    ADR-0125 §6 forbids rather than the value verbatim.
    """
    credential = mint_credential()
    await put(store, f'{{"hub": "{HUB}", "credential": "{credential}"')

    with pytest.raises(IncompleteEnrolmentError) as raised:
        await read_enrolment(store)

    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None
    assert_discloses_nothing(raised.value, credential, context="an undecodable record")


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


# --- rotation, and the state one entry makes unreachable ---------------------


async def test_intake_over_a_live_enrolment_replaces_it(store: FakeSecretStore) -> None:
    """Rotation is one act, which is why ADR-0125 §4 makes ``set`` replace.

    ADR-0124 §6 makes re-enrolling a live device "a **single act**… and the two
    halves are not separable". A device that had to remove before it could store
    would hold nothing in between, and a crash there would leave it unenrolled.
    """
    await store_enrolment(store, hub_identity=HUB, credential=mint_credential())
    rotated = mint_credential()

    await store_enrolment(store, hub_identity=HUB, credential=rotated)

    assert (await read_enrolment(store)).credential.get_secret_value() == rotated
    assert len(store.backing) == 1


async def test_a_failed_re_enrolment_leaves_the_previous_pair_whole(
    store: FakeSecretStore,
) -> None:
    """**The state one entry exists to make unreachable.**

    With the pair under two names, re-enrolling at a second hub writes twice, and a
    failure between the writes leaves the *new* identity beside the *old*
    credential. That pair is syntactically whole, so a read accepts it, ADR-0124
    §4's identity check passes against the new hub, and the client presents the
    previous hub's credential to it — a Tier 0 value sent to a node it was never
    minted for, in a state neither end can detect.

    One entry removes it rather than detecting it: ADR-0125 §4 guarantees a ``get``
    "never observes a partially written value… never a mixture and never a
    fragment", so a device holds the old pair or the new one and nothing else.
    """
    first = mint_credential()
    await store_enrolment(store, hub_identity=HUB, credential=first)
    store.fail(SecretMethod.SET, Disclosure.VERBATIM)

    with pytest.raises(SecretStoreError):
        await store_enrolment(store, hub_identity=OTHER_HUB, credential=mint_credential())

    survived = await read_enrolment(store)
    assert survived.hub_identity == HUB, "a failed re-enrolment moved the identity alone"
    assert survived.credential.get_secret_value() == first
    assert len(store.backing) == 1


# --- what intake refuses ------------------------------------------------------


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

    assert await store.get(enrolment_name()) is None, "a refused intake stored a record"


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

    assert await store.get(enrolment_name()) is None, "a refused intake stored a record"


# --- what the record is -------------------------------------------------------


async def test_the_record_carries_both_values_verbatim(store: FakeSecretStore) -> None:
    """Stored byte for byte, which is what ADR-0125 §3's verbatim clause requires.

    Two spellings of a secret are two different secrets, so nothing between intake
    and the connect frame may trim, fold or re-encode either member.
    """
    credential = mint_credential()
    await store_enrolment(store, hub_identity=HUB, credential=credential)

    assert json.loads(await held_record(store)) == {"hub": HUB, "credential": credential}


async def test_the_widest_record_this_device_accepts_fits_the_value_bound(
    store: FakeSecretStore,
) -> None:
    """ADR-0125 §3's 1024 UTF-8 bytes, against the largest pair intake admits.

    The bound is the store's and it refuses rather than truncating, so a record that
    did not fit would be an enrolment the owner could perform at the hub and not
    complete at the device. Driven at the widest admissible identity — in a script
    that costs more than one byte a character — so the margin is measured rather
    than assumed.
    """
    wide = "ǆ" * (MAX_OVERLAY_IDENTITY_BYTES // len("ǆ".encode()))
    await store_enrolment(store, hub_identity=wide, credential=mint_credential())

    assert len((await held_record(store)).encode("utf-8")) <= SECRET_VALUE_MAX_BYTES
    assert (await read_enrolment(store)).hub_identity == wide


# --- unenrolment (ADR-0124 §8) ------------------------------------------------


async def test_unenrolment_removes_the_record_and_says_it_did(
    store: FakeSecretStore,
) -> None:
    """ADR-0124 §8's device-side act, and ADR-0125 §5's "say what you did"."""
    await store_enrolment(store, hub_identity=HUB, credential=mint_credential())

    assert await remove_enrolment(store) is True
    assert await store.get(enrolment_name()) is None
    assert len(store.backing) == 0


async def test_unenrolment_is_safe_to_repeat(store: FakeSecretStore) -> None:
    """ "It works whether or not the enrolment it removes is still live" (§8).

    The case an owner reaches for it in is usually one where something has already
    gone wrong, so an act that raised the second time it ran would be the wrong
    surface for it.
    """
    await store_enrolment(store, hub_identity=HUB, credential=mint_credential())
    await remove_enrolment(store)

    assert await remove_enrolment(store) is False


async def test_unenrolment_removes_a_record_this_build_cannot_read(
    store: FakeSecretStore,
) -> None:
    """A purge composed from the names its holder knows (ADR-0125 §5).

    There is no enumeration, so this act is the only thing that removes this entry —
    and a device holding a record nothing can read is exactly the device an owner
    reaches for it on. A purge that first tried to *parse* what it was removing
    would leave behind the one entry it exists to remove.
    """
    await put(store, "not json at all")

    assert await remove_enrolment(store) is True
    assert await store.get(enrolment_name()) is None


# --- the name, and the scope it is reached through ----------------------------


async def test_the_name_is_enrolment_scoped_and_no_other_scope_may_reach_it() -> None:
    """The scope is a property of the object a consumer holds (ADR-0125 §2, §8).

    A store bound to another scope refuses this name rather than answering it, which
    is what makes "the wire client's enrolment paths hold an ``ENROLMENT``-scoped
    store" mechanical instead of advisory — and it is the boundary that keeps a tool
    from reading the device credential.
    """
    assert enrolment_name().scope is SecretScope.ENROLMENT

    elsewhere = FakeSecretStore(scope=SecretScope.INTEGRATION)
    with pytest.raises(ValueError, match="scope"):
        await elsewhere.get(enrolment_name())


def test_the_entry_is_named_so_the_log_redaction_covers_it() -> None:
    """ADR-0124 §6: "no implementation may give it a name that redaction misses".

    ``core/logging.py`` redacts by *key name*, matching ``credential`` as a
    case-insensitive substring, so the name is chosen to be covered by it rather
    than to be pretty.
    """
    assert any(part in ENROLMENT_KEY.casefold() for part in _SENSITIVE_KEY_PARTS)


# --- how many times the record is unwrapped, and where ------------------------


async def test_the_record_is_unwrapped_exactly_once_per_read(store: FakeSecretStore) -> None:
    """One unwrap of the stored value, in the one function ADR-0124 §6 confines it to.

    Packing the pair means :func:`read_enrolment` unwraps the *record* to split it,
    which is the cost of the shape ADR-0125 §4 licenses and the one that removes the
    mismatched-pair state two entries admit. What this pins is the bound on that
    cost: it happens once, in the connect path, and the credential leaves still
    wrapped — so the number of places a Tier 0 value is in the clear does not grow
    with the number of members the record gains.
    """
    await store_enrolment(store, hub_identity=HUB, credential=mint_credential())
    counting = CountingStore(store)
    CountingSecret.unwraps = 0

    await read_enrolment(counting)

    assert CountingSecret.unwraps == 1


async def test_unenrolment_never_unwraps_the_record(store: FakeSecretStore) -> None:
    """The purge removes a name and reads nothing (ADR-0124 §6, §8).

    "No other code in the client reads it" is the marked clause, and the act most
    likely to grow a read is this one — a surface tempted to report *which* hub it
    just unbound would have to open the record to find out.
    """
    await store_enrolment(store, hub_identity=HUB, credential=mint_credential())
    counting = CountingStore(store)
    CountingSecret.unwraps = 0

    assert await remove_enrolment(counting) is True

    assert CountingSecret.unwraps == 0
