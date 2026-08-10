"""What an enrolled device holds, and the two acts that put it there and take it away.

ADR-0124 §6 mints a credential **at the hub** and discloses it once, together with
the hub's own overlay identity; this module is the other end of that hand-off — the
act by which the owner, holding both values, stores them on the device, and the
read the connect path makes of them.

> **Normative.** Enrolment also discloses the **hub's own overlay identity**, and
> the two values travel together: the client holds both, and holding the credential
> without the hub identity is an incomplete enrolment the client refuses to connect
> on. The hub identity is not a secret; it is carried with the credential because
> §4 makes it the thing a destination has to match.

**Two entries rather than one packed value, and the pair is checked rather than
assumed.** ADR-0125 §4 permits either shape and rules neither in: "a crash between
the two ``set`` calls leaves one… That is not a gap this seam must close, because
ADR-0124 §6 already rules that 'holding the credential without the hub identity is
an incomplete enrolment the client refuses to connect on' — the client must detect
exactly this state whatever the storage does." Since the detection is owed either
way, two entries are taken: they keep the non-secret value legible as a separate
thing, and they make the half-written state a real state this module's tests can
reach rather than one nothing can produce.

**Both go through the keyring and through no other path** (ADR-0124 §6, ADR-0125
§8). Nothing here opens a file, reads an environment variable, or touches a
database: the credential is Tier 0, "held **only** in the Tier 0 place ADR-0004 §3
names — the OS keyring, which is where the enrolled hub identity sits beside it".

**Nothing here unwraps the credential.** ADR-0125 §3 puts the one authorised
``get_secret_value`` call in the client, "immediately before encoding the connect
frame's credential member, and nowhere else", so :func:`read_enrolment` hands the
value back still wrapped. That is also why the credential's *shape* is checked at
intake and not on the way out: intake is the moment the plaintext is legitimately
in hand, because the owner is typing it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from pydantic import SecretStr

from ai_assistant.core.types import SecretName, SecretScope, secret_value
from ai_assistant.wire.credential import CREDENTIAL_CHARACTERS, is_well_formed
from ai_assistant.wire.errors import IncompleteEnrolmentError, NotEnrolledError
from ai_assistant.wire.overlay import MAX_OVERLAY_IDENTITY_BYTES

if TYPE_CHECKING:
    from ai_assistant.core.protocols import Secrets, SecretStore
    from ai_assistant.core.types import SecretValue

#: The device credential's entry. The name contains ``credential`` deliberately:
#: ``core/logging.py`` redacts a key containing that substring, and ADR-0124 §6
#: requires that "no implementation may give it a name that redaction misses".
CREDENTIAL_KEY: Final = "hub-credential"

#: The enrolled hub identity's entry, beside it (ADR-0124 §4, §6). Not a secret —
#: it is here because §5 of ADR-0125 admits "a non-secret value that ADR-0124 §4 and
#: §6 require to travel with one", and because putting it anywhere a configuration
#: setting could reach would defeat §4's third clause.
HUB_IDENTITY_KEY: Final = "hub-identity"


def credential_name() -> SecretName:
    """The name the device credential is stored under.

    Returns:
        An ``ENROLMENT``-scoped name. The scope is what an instance is bound to
        (ADR-0125 §2), so a store wired for another scope refuses this outright
        rather than answering it.
    """
    return SecretName(scope=SecretScope.ENROLMENT, key=CREDENTIAL_KEY)


def hub_identity_name() -> SecretName:
    """The name the enrolled hub identity is stored under.

    Returns:
        An ``ENROLMENT``-scoped name.
    """
    return SecretName(scope=SecretScope.ENROLMENT, key=HUB_IDENTITY_KEY)


@dataclass(frozen=True, slots=True)
class Enrolment:
    """The two facts a device holds about the hub it may reach.

    Attributes:
        hub_identity: The hub's overlay identity, as it was disclosed at enrolment.
            This is what ADR-0124 §4 makes a destination match, and it is **not**
            configuration: "changing the client's destination address does not
            change the identity the clause above requires it to match, and no
            configuration setting may override that identity."
        credential: The device credential, still wrapped. Unwrapped once, by the
            connect path, immediately before the frame is encoded — and nowhere
            else (ADR-0125 §3).
    """

    hub_identity: str
    credential: SecretValue


@dataclass(frozen=True, slots=True)
class Unenrolment:
    """What ADR-0124 §8's device-side act actually removed.

    Attributes:
        credential_removed: Whether a credential was there to remove.
        hub_identity_removed: Whether a hub identity was there to remove.
    """

    credential_removed: bool
    hub_identity_removed: bool

    @property
    def removed_anything(self) -> bool:
        """Whether this device held any part of an enrolment before the act."""
        return self.credential_removed or self.hub_identity_removed


async def read_enrolment(secrets: Secrets) -> Enrolment:
    """Read both values on the connect path, refusing anything but a whole pair.

    ADR-0124 §6 confines this read to "one purpose and one path", and it is the read
    ADR-0004 §7's gate is superseded for — narrowly, against three replacements, one
    of which is that confinement. The other two are the operating system's own
    access control on the keyring, which :class:`~ai_assistant.core.protocols.Secrets`
    is the only path to, and the hub's record of every use.

    **A ``None`` is absence and never unreachability** (ADR-0125 §7). If the two
    were one observation, "this device is not enrolled" and "this device's keyring
    is locked" would read the same, and an intake reading it as a first run could
    mint a state the owner never asked for. The seam raises for the second, and this
    function lets that raise through untouched.

    Args:
        secrets: The reading face, bound to ``ENROLMENT`` and to this installation.
            Nothing wider: the connect path holds no ability to write or delete
            (ADR-0125 §8).

    Returns:
        Both values, the credential still wrapped.

    Raises:
        NotEnrolledError: If this device holds neither value — which is the state
            ADR-0124 §8's unenrolment deliberately leaves, and the state of a device
            nobody has enrolled yet.
        IncompleteEnrolmentError: If it holds one and not the other.
        SecretStoreUnavailableError: If the keyring cannot be reached. Distinct from
            both of the above, which is the whole of ADR-0125 §7's argument.
        SecretStoreError: If the keyring failed the read.
    """
    identity = await secrets.get(hub_identity_name())
    credential = await secrets.get(credential_name())
    if identity is None and credential is None:
        msg = (
            "this device holds no enrolment, so it has nothing to present to a hub's "
            "remote listener. Enrol it at the hub with 'ai-assistant-device enrol', then "
            "run 'assistant device enrol' here with the two values it printed"
        )
        raise NotEnrolledError(msg)
    if identity is None or credential is None:
        held, missing = (
            ("a credential", "the hub identity that travels with it")
            if identity is None
            else ("the hub's identity", "the credential that travels with it")
        )
        msg = (
            f"this device holds {held} but not {missing}, which ADR-0124 §6 makes an "
            f"incomplete enrolment a client refuses to connect on — the identity is what "
            f"a destination has to match, and admitting a hub without checking it is the "
            f"whole of the attack. Run 'assistant device enrol' again with both values"
        )
        raise IncompleteEnrolmentError(msg)
    return Enrolment(hub_identity=identity.get_secret_value(), credential=credential)


async def store_enrolment(store: SecretStore, *, hub_identity: str, credential: str) -> None:
    """Store the pair the hub disclosed, refusing anything but a whole one.

    ADR-0124 §6's hand-off, performed at the device. It replaces whatever was there
    rather than refusing an occupied name, which is ADR-0125 §4's ruling and the one
    rotation needs: re-enrolling a device at the hub "mints a replacement credential"
    in a single act, and a device that had to delete before it could store would
    have a window in which it holds nothing.

    **The identity is written first and the credential second**, which is the only
    part of the order that matters. A crash between the two leaves an incomplete
    pair either way and :func:`read_enrolment` refuses both shapes — but ADR-0124 §6
    names "the credential without the hub identity" as the dangerous half, and
    writing the identity first is what keeps a crash from producing exactly that.

    Args:
        store: The writing face, bound to ``ENROLMENT`` and to this installation.
        hub_identity: The hub's overlay identity, as ``ai-assistant-device`` printed
            it. Refused if blank, unencodable, or longer than
            :data:`MAX_OVERLAY_IDENTITY_BYTES` encoded.
        credential: The credential, as it was printed once. Refused unless it is a
            value of the scheme ADR-0124 §6 mints — checked **here**, where the
            plaintext is legitimately in hand because the owner is typing it, rather
            than on the connect path, which ADR-0125 §3 confines to one unwrap.

    Raises:
        ValueError: If either value is not one this device can hold. Its message
            names neither the credential nor any part of it: a rejected value's own
            length included (ADR-0125 §6).
        SecretStoreUnavailableError: If the keyring cannot be reached.
        SecretStoreError: If the keyring failed a write.
    """
    _check_hub_identity(hub_identity)
    if not is_well_formed(credential):
        msg = (
            f"that is not a credential this hub could have minted, so storing it would "
            f"buy a refusal at the first connect instead of a message now. One is "
            f"{CREDENTIAL_CHARACTERS} characters of letters, digits, '-' and '_', printed "
            f"once by 'ai-assistant-device enrol' — check it was copied whole"
        )
        raise ValueError(msg)
    await store.set(hub_identity_name(), secret_value(SecretStr(hub_identity)))
    await store.set(credential_name(), secret_value(SecretStr(credential)))


async def remove_enrolment(store: SecretStore) -> Unenrolment:
    """Remove both values from this device (ADR-0124 §8).

    > **Normative.** The client offers an **unenrolment** act that removes the
    > credential and the enrolled hub identity from the device, and that act is what
    > discharges ADR-0004 §6's purge of Tier 0 keyring entries on that device. It is
    > performed at the device, it needs no hub, and it works whether or not the
    > enrolment it removes is still live.

    Nothing here reaches a hub, and nothing here asks whether the enrolment is live:
    a device the owner has stopped using, or one whose hub is gone, is exactly the
    case this exists for. Running it twice is safe — ``delete`` reports ``False``
    for an absent entry and raises nothing (ADR-0125 §4).

    **The credential is removed first.** ADR-0125 §5 refuses enumeration, so "a
    complete purge of Tier 0 data is composed from the names its holders know", and
    a failure part-way through leaves whichever entry has not been reached yet. Of
    the two, the one that must not be the survivor is the secret.

    Args:
        store: The writing face, bound to ``ENROLMENT`` and to this installation.

    Returns:
        What was there to remove, so a surface can say what it did rather than
        assert a purge — which is ADR-0124 §8's own standard for the hub-side
        delete, applied on this side of the boundary.

    Raises:
        SecretStoreUnavailableError: If the keyring cannot be reached, in which case
            nothing was removed and the owner has an act still to perform.
        SecretStoreError: If the keyring failed a removal.
    """
    credential_removed = await store.delete(credential_name())
    identity_removed = await store.delete(hub_identity_name())
    return Unenrolment(credential_removed=credential_removed, hub_identity_removed=identity_removed)


def _check_hub_identity(identity: str) -> None:
    """Refuse a hub identity no overlay could have produced.

    Args:
        identity: The value the owner supplied.

    Raises:
        ValueError: If it is blank, has no UTF-8 encoding, or is over
            :data:`MAX_OVERLAY_IDENTITY_BYTES` bytes encoded. **The message echoes it**,
            which is safe and is meant to be: ADR-0124 §6 states that "the hub
            identity is not a secret", and an owner who mistyped it needs to see
            what this device read.
    """
    if not identity.strip():
        msg = (
            "a hub identity is required beside the credential: it is what this device "
            "checks a destination against, and holding one without the other is an "
            "incomplete enrolment (ADR-0124 §6). It is the 'Hub:' line "
            "'ai-assistant-device enrol' printed"
        )
        raise ValueError(msg)
    try:
        size = len(identity.encode("utf-8"))
    except UnicodeEncodeError as exc:
        # A lone surrogate is non-blank, is one character, and has no byte length at
        # all — measuring it *is* encoding it — so it survives every other check and
        # would reach a backend as a string with no wire form (ADR-0087 §2b).
        msg = "a hub identity must have a UTF-8 encoding; no overlay produces one that has none"
        raise ValueError(msg) from exc
    if size > MAX_OVERLAY_IDENTITY_BYTES:
        msg = (
            f"a hub identity of {size} bytes is over the {MAX_OVERLAY_IDENTITY_BYTES}-byte "
            f"bound, which no overlay this client accepts produces; check that the value "
            f"was copied rather than the whole line: {identity!r}"
        )
        raise ValueError(msg)
