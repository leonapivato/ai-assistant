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

**One entry holding both, which is the shape ADR-0125 §4 licenses and argues for.**
That section permits either — "a client that prefers to avoid it entirely may store
the pair as one value under one name; both satisfy ADR-0124 §6 and this ADR rules
neither in" — and then gives the reason to prefer it: last-write-wins is what "lets
the device-side half of that act be **one call**".

**Two entries were tried and are a real defect, not merely a weaker choice.** With
the credential and the identity under separate names, re-enrolling a device that
already holds a live pair writes twice, and a failure between the two writes — a
locked keyring, a backend error, a killed process — leaves the *new* identity beside
the *old* credential. That pair is syntactically whole, so a read accepts it, §4's
identity check passes against the new hub, and the client presents the previous
hub's credential to it. It is worse than either incomplete state, because neither
end can detect it. One entry removes the state rather than detecting it: ADR-0125 §4
guarantees that "a ``get`` never observes a partially written value… never a mixture
and never a fragment", so what a device holds is always one whole pair or none.

**Everything here goes through the keyring and through no other path** (ADR-0124 §6,
ADR-0125 §8). Nothing opens a file, reads an environment variable, or touches a
database: the credential is Tier 0, "held **only** in the Tier 0 place ADR-0004 §3
names — the OS keyring, which is where the enrolled hub identity sits beside it".

**On the one unwrap this module performs.** ADR-0124 §6's marked clause is that the
client "reads the credential only on the connect path and for no other purpose. No
other code in the client reads it, it is never passed to the engine surface, and it
appears in no frame but the connect frame §7 requires" — and :func:`read_enrolment`
is that connect path, called from nowhere else. What it unwraps is the *record*, in
order to split the pair; the credential leaves here still wrapped, and the unwrap
ADR-0125 §3 talks about — the one immediately before the connect frame's member is
encoded — stays where that section puts it, in
:class:`~ai_assistant.wire.remote.RemoteHubEngineClient`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

from pydantic import SecretStr

from ai_assistant.core.types import SecretName, SecretScope, secret_value
from ai_assistant.wire.credential import CREDENTIAL_CHARACTERS, is_well_formed
from ai_assistant.wire.errors import IncompleteEnrolmentError, NotEnrolledError
from ai_assistant.wire.overlay import MAX_OVERLAY_IDENTITY_BYTES

if TYPE_CHECKING:
    from ai_assistant.core.protocols import Secrets, SecretStore
    from ai_assistant.core.types import SecretValue

#: The one entry a device's enrolment occupies. The name contains ``credential``
#: deliberately: ``core/logging.py`` redacts a key containing that substring, and
#: ADR-0124 §6 requires that "no implementation may give it a name that redaction
#: misses". The whole record is a secret-typed value, so the hub identity inside it
#: is redacted too — which is more than ADR-0125 §5's exception asks for and costs
#: nothing, since the identity is disclosed by the acts that need it.
ENROLMENT_KEY: Final = "hub-credential"

#: The record's two members. Kept short because the whole record is bounded by
#: ``SecretValue``'s 1024 UTF-8 bytes (ADR-0125 §3), which an identity of at most
#: :data:`~ai_assistant.wire.overlay.MAX_OVERLAY_IDENTITY_BYTES` bytes and a
#: credential of :data:`~ai_assistant.wire.credential.CREDENTIAL_CHARACTERS`
#: characters clear by an order of magnitude.
_HUB_MEMBER: Final = "hub"
_CREDENTIAL_MEMBER: Final = "credential"


def enrolment_name() -> SecretName:
    """The name a device's enrolment is stored under.

    Returns:
        An ``ENROLMENT``-scoped name. The scope is what an instance is bound to
        (ADR-0125 §2), so a store wired for another scope refuses this outright
        rather than answering it — which is what makes ADR-0125 §8's consumer
        boundary a mechanism instead of a sentence.
    """
    return SecretName(scope=SecretScope.ENROLMENT, key=ENROLMENT_KEY)


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
            connect path, immediately before the frame is encoded (ADR-0125 §3).
    """

    hub_identity: str
    credential: SecretValue


async def read_enrolment(secrets: Secrets) -> Enrolment:
    """Read the record on the connect path, refusing anything but a whole pair.

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
        NotEnrolledError: If this device holds no record — which is the state
            ADR-0124 §8's unenrolment deliberately leaves, and the state of a device
            nobody has enrolled yet.
        IncompleteEnrolmentError: If it holds one this build cannot read as a whole
            pair. ADR-0125 §4 rules out a *partially written* record, so what
            reaches this is a record written by something else, or by a build whose
            format this one does not know — and ADR-0124 §6's answer to holding half
            an enrolment is the answer to holding an unreadable one.
        SecretStoreUnavailableError: If the keyring cannot be reached. Distinct from
            both of the above, which is the whole of ADR-0125 §7's argument.
        SecretStoreError: If the keyring failed the read.
    """
    held = await secrets.get(enrolment_name())
    if held is None:
        msg = (
            "this device holds no enrolment, so it has nothing to present to a hub's "
            "remote listener. Enrol it at the hub with 'ai-assistant-device enrol', then "
            "run 'assistant device enrol' here with the two values it printed"
        )
        raise NotEnrolledError(msg)
    return _record(held.get_secret_value())


def _record(plaintext: str) -> Enrolment:
    """Split one stored record into the pair it carries, or refuse it whole.

    **Nothing this raises names the record or any part of it** (ADR-0125 §6): the
    plaintext holds the credential, so a message quoting what failed to parse would
    be the disclosure that section forbids, arriving through the error path.

    Args:
        plaintext: The stored record.

    Returns:
        The pair.

    Raises:
        IncompleteEnrolmentError: If the record is not an object carrying both
            members as non-blank strings.
    """
    decoded = _decoded(plaintext)
    if not isinstance(decoded, dict):
        raise IncompleteEnrolmentError(_UNREADABLE)
    identity, credential = decoded.get(_HUB_MEMBER), decoded.get(_CREDENTIAL_MEMBER)
    if not isinstance(identity, str) or not identity.strip():
        raise IncompleteEnrolmentError(_UNREADABLE)
    if not isinstance(credential, str) or not credential.strip():
        raise IncompleteEnrolmentError(_UNREADABLE)
    return Enrolment(hub_identity=identity, credential=SecretStr(credential))


def _decoded(plaintext: str) -> Any:
    """Decode one stored record, refusing it without letting the decoder's error out.

    **The decoder's exception is caught and dropped rather than chained**, and that
    is the point of this function existing at all. ``json.JSONDecodeError`` carries
    the text it failed on in its ``doc`` attribute, so the whole record — the
    credential included — hangs off any exception that keeps it as a ``__cause__``
    or a ``__context__``. It reaches no message, no argument and no traceback, but
    it is a live reference to a Tier 0 value on an object a handler may render
    attribute by attribute, and ``core/logging.py`` redacts by *key name*, which
    ``doc`` is not one of. Raising after the ``try`` statement rather than inside the
    ``except`` clause is what leaves the new exception with neither link set.

    Args:
        plaintext: The stored record.

    Returns:
        Whatever the record decodes to.

    Raises:
        IncompleteEnrolmentError: If it is not JSON at all.
    """
    undecodable = False
    try:
        decoded: Any = json.loads(plaintext)
    except ValueError:
        undecodable = True
    if undecodable:
        raise IncompleteEnrolmentError(_UNREADABLE)
    return decoded


#: What an unreadable record is reported as. One sentence for every way of failing
#: to be a whole pair, because the owner's act is the same for all of them and a
#: taxonomy here would only invite a branch that tried to use half a record.
_UNREADABLE: Final = (
    "this device's enrolment record cannot be read as a whole pair, which ADR-0124 §6 "
    "makes an incomplete enrolment a client refuses to connect on — the hub identity is "
    "what a destination has to match, and admitting a hub without checking it is the "
    "whole of the attack. Run 'assistant device enrol' again with both values"
)


async def store_enrolment(store: SecretStore, *, hub_identity: str, credential: str) -> None:
    """Store the pair the hub disclosed, in one write and as one value.

    ADR-0124 §6's hand-off, performed at the device. It replaces whatever was there
    rather than refusing an occupied name, which is ADR-0125 §4's ruling and the one
    rotation needs: re-enrolling a device at the hub "mints a replacement credential"
    in a single act, and a device that had to delete before it could store would have
    a window in which it holds nothing.

    **One ``set``, which is what makes the act atomic against a failure part-way
    through.** ADR-0125 §4 guarantees that a concurrent or interrupted write leaves
    one of the written values whole and never a mixture, so a device re-enrolled at a
    second hub holds either the old pair or the new one — never the new identity
    beside the old credential, which is the state that would send one hub's
    credential to another and that no read could detect.

    Args:
        store: The writing face, bound to ``ENROLMENT`` and to this installation.
        hub_identity: The hub's overlay identity, as ``ai-assistant-device`` printed
            it. Refused if blank, unencodable, or longer than
            :data:`~ai_assistant.wire.overlay.MAX_OVERLAY_IDENTITY_BYTES` encoded.
        credential: The credential, as it was printed once. Refused unless it is a
            value of the scheme ADR-0124 §6 mints — checked **here**, where the
            plaintext is legitimately in hand because the owner is typing it, and
            where a mistyped value can still be reported as one.

    Raises:
        ValueError: If either value is not one this device can hold. Its message
            names neither the credential nor any part of it, a rejected value's own
            length included (ADR-0125 §6).
        SecretStoreUnavailableError: If the keyring cannot be reached.
        SecretStoreError: If the keyring failed the write.
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
    record = json.dumps(
        {_HUB_MEMBER: hub_identity, _CREDENTIAL_MEMBER: credential},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    await store.set(enrolment_name(), secret_value(SecretStr(record)))


async def remove_enrolment(store: SecretStore) -> bool:
    """Remove this device's enrolment (ADR-0124 §8).

    > **Normative.** The client offers an **unenrolment** act that removes the
    > credential and the enrolled hub identity from the device, and that act is what
    > discharges ADR-0004 §6's purge of Tier 0 keyring entries on that device. It is
    > performed at the device, it needs no hub, and it works whether or not the
    > enrolment it removes is still live.

    Nothing here reaches a hub, and nothing here asks whether the enrolment is live:
    a device the owner has stopped using, or one whose hub is gone, is exactly the
    case this exists for. Running it twice is safe — ``delete`` reports ``False``
    for an absent entry and raises nothing (ADR-0125 §4).

    **One entry, so the purge is one removal and cannot be partial.** ADR-0125 §5
    refuses enumeration, so "a complete purge of Tier 0 data is composed from the
    names its holders know" and every consumer that writes an entry owes a path that
    deletes it. This is that path, and there is exactly one name on it.

    Args:
        store: The writing face, bound to ``ENROLMENT`` and to this installation.

    Returns:
        Whether an enrolment was there to remove, so a surface can say what it did
        rather than assert a purge — ADR-0124 §8's own standard for the hub-side
        delete, applied on this side of the device boundary.

    Raises:
        SecretStoreUnavailableError: If the keyring cannot be reached, in which case
            nothing was removed and the owner has an act still to perform.
        SecretStoreError: If the keyring failed the removal.
    """
    return await store.delete(enrolment_name())


def _check_hub_identity(identity: str) -> None:
    """Refuse a hub identity no overlay could have produced.

    Args:
        identity: The value the owner supplied.

    Raises:
        ValueError: If it is blank, has no UTF-8 encoding, or is over
            :data:`~ai_assistant.wire.overlay.MAX_OVERLAY_IDENTITY_BYTES` bytes
            encoded. **The message echoes it**, which is safe and is meant to be:
            ADR-0124 §6 states that "the hub identity is not a secret", and an owner
            who mistyped it needs to see what this device read.
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
