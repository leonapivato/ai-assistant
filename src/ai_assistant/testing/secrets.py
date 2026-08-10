"""The canonical in-memory keyring fake for ADR-0125's two Protocols.

One class, :class:`FakeSecretStore`, implementing
:class:`~ai_assistant.core.protocols.SecretStore` and therefore
:class:`~ai_assistant.core.protocols.Secrets` structurally — which is ADR-0125
§1's shape rather than a convenience: there is one implementation class and one
keyring backing, and the composition root builds one instance per scope it wires.
:data:`FakeSecrets` is that same class under the reading face's name, for the
reason recorded on it.

**The backing is a separate object on purpose** (:class:`SecretBacking`). ADR-0125
§11 proves isolation with *two subjects over one backing*, twice — a pair
differing only in installation, and a pair differing only in scope — because two
subjects holding separate maps cannot observe each other's entries however the
adapter composes its coordinates, so the pairing alone would prove nothing. One
shared backing is also the real deployment: one OS keyring holds every scope of
every installation on the machine.

**What this fake cannot prove, and what therefore stays owed** (ADR-0125 §11).
That a backend selection finding nothing usable *raises* rather than falling back,
and that no backend storing a value without the operating system's own access
control is ever selected. Neither is expressible against a subject a suite was
handed, because both are about which backend gets *selected*, and this fake has
none to select. They are the keyring-backed adapter's own tests, and naming them
here is what stops them evaporating between two lanes.

ADR-0060's cancellation clause is **vacuous** for this subject and is meant to be:
no method here suspends or acquires anything whose safety outlives the coroutine.
It has real bite on the adapter — a keyring call is I/O, and a synchronous library
driven from a worker thread is exactly ADR-0054's shape — which is that lane's to
pin, over a backend it controls.
"""

from __future__ import annotations

import base64
from enum import StrEnum
from hashlib import blake2b, sha256
from typing import TYPE_CHECKING, Final, final

from pydantic import SecretStr

from ai_assistant.core.errors import SecretStoreError, SecretStoreUnavailableError
from ai_assistant.core.types import SecretName, SecretScope, secret_value

if TYPE_CHECKING:
    from ai_assistant.core.types import SecretValue

#: The installation namespace a fake takes when a test does not care which one.
#: A path-shaped value, because ADR-0125 §2 binds the namespace to the resolved
#: ``Settings.data_dir`` and the composition root injects it.
DEFAULT_INSTALLATION: Final = "/home/owner/.local/share/ai-assistant"

#: The second installation the isolation cases use. Differs from
#: :data:`DEFAULT_INSTALLATION` in its last component only, which is the shape a
#: second data directory on one machine actually has.
OTHER_INSTALLATION: Final = "/home/owner/.local/share/ai-assistant-qa"

#: How many characters a prefix, suffix or truncation discloses. Short enough to
#: be the sort of thing an error message would plausibly carry, long enough that
#: a substring assertion over it is not satisfied by accident.
_DISCLOSED_CHARACTERS: Final = 8


class SecretMethod(StrEnum):
    """Which method of the seam a fake's switch is armed against.

    Every switch is selectable per method because ADR-0125 §11 requires the
    redaction case to run for **every method the subject has**, not for ``set``
    alone. A ``set`` failure discloses a value the caller already holds; a ``get``
    failure discloses one the caller was *refused*, which is the worse of the two,
    and an adapter that redacts ``set`` while wrapping ``get``'s backend exception
    with ``SecretStoreError(str(exc))`` is both plausible and a leak.
    """

    GET = "get"
    SET = "set"
    DELETE = "delete"


class Disclosure(StrEnum):
    """One derivation of a secret that ADR-0125 §6 forbids an error to carry.

    **One member per entry in §6's list, and §6 is the single source.** A
    derivation added there is a mode this fake owes and a case the suite runs,
    which is why neither this enum nor the suite carries a second list of its own:
    two lists describing one obligation drift, and the shorter one becomes the
    floor.

    A verbatim check catches none of the others — a wrapper reporting
    ``value[:8]``, ``value[-8:]`` or a digest passes a substring assertion over the
    whole value while disclosing exactly what ADR-0021 §1 calls a weakened copy of
    a low-entropy secret.

    **A digest is carried in two members**, differing in algorithm *and* in
    encoding (§11). What §6 forbids is "a digest", not one hash: a suite pinned to
    a single algorithm would be testing string equality with that algorithm rather
    than the prohibition.

    :attr:`LENGTH` is included, and an earlier reading would have excluded it as
    untestable. That is true of a *real* backend's message and irrelevant here:
    this fake emits the failing text, so the suite chose both the value and the
    label and can assert that exact disclosure is absent. Leaving it out would
    leave the one derivation a wrapper is most likely to think harmless as the
    only one nothing tests.
    """

    VERBATIM = "verbatim"
    PREFIX = "prefix"
    SUFFIX = "suffix"
    TRUNCATION = "truncation"
    SHA256_HEX = "sha256-hex"
    BLAKE2B_BASE64 = "blake2b-base64"
    LENGTH = "length"


def disclosure_of(disclosure: Disclosure, plaintext: str) -> str:
    """The exact text a backend error discloses under ``disclosure``.

    Shared by the fake, which embeds it in the backend error it models, and by the
    conformance suite, which asserts it is absent from the error the subject
    surfaces. One definition rather than two, so the case cannot pass by the two
    sides disagreeing about what "a prefix of the plaintext" means.

    Args:
        disclosure: Which derivation to render.
        plaintext: The secret the backend error would be about.

    Returns:
        The disclosing text.

    Raises:
        UnicodeEncodeError: If ``plaintext`` has no UTF-8 encoding and
            ``disclosure`` is one that measures or hashes it. Deliberately not
            caught here: a digest and a length of a value with no byte form do not
            exist, and inventing one would put a derivation in a caller's hands
            that no backend could have produced. The slicing derivations are
            unaffected and stay checkable.
    """
    match disclosure:
        case Disclosure.VERBATIM:
            disclosed = plaintext
        case Disclosure.PREFIX:
            disclosed = plaintext[:_DISCLOSED_CHARACTERS]
        case Disclosure.SUFFIX:
            disclosed = plaintext[-_DISCLOSED_CHARACTERS:]
        case Disclosure.TRUNCATION:
            disclosed = f"{plaintext[:_DISCLOSED_CHARACTERS]}..."
        case Disclosure.SHA256_HEX:
            disclosed = sha256(plaintext.encode("utf-8")).hexdigest()
        case Disclosure.BLAKE2B_BASE64:
            digest = blake2b(plaintext.encode("utf-8")).digest()
            disclosed = base64.b64encode(digest).decode("ascii")
        case Disclosure.LENGTH:
            disclosed = f"length {len(plaintext.encode('utf-8'))}"
    return disclosed


@final
class SecretBacking:
    """One machine's keyring, as the subjects over it see it (ADR-0125 §11).

    Every entry every subject holds lives in one map, keyed by the coordinate the
    subject composed, so two subjects that compose the same coordinate for two
    distinct :class:`~ai_assistant.core.types.SecretName` values **do** collide
    here — which is the failure the isolation cases exist to catch: ``api-key``
    under ``PROVIDER`` and under ``INTEGRATION`` collapsing into one entry, and a
    second data directory overwriting the first's credential and deleting it at
    unenrolment.

    Its ``repr`` discloses no entry and no coordinate: it is reachable from a
    subject's own ``repr``, and ADR-0125 §11 requires no secret value to appear in
    that.
    """

    def __init__(self) -> None:
        """Create an empty backing."""
        self._entries: dict[str, str] = {}

    def __repr__(self) -> str:
        """Describe the backing by size alone, never by content."""
        return f"{type(self).__name__}(entries={len(self._entries)})"

    def __len__(self) -> int:
        """How many entries the whole machine holds, across every subject."""
        return len(self._entries)

    def read(self, coordinate: str) -> str | None:
        """Return the plaintext stored at ``coordinate``, or ``None``."""
        return self._entries.get(coordinate)

    def write(self, coordinate: str, plaintext: str) -> None:
        """Store ``plaintext`` at ``coordinate``, replacing whatever was there."""
        self._entries[coordinate] = plaintext

    def remove(self, coordinate: str) -> bool:
        """Remove ``coordinate``, reporting whether anything was there."""
        return self._entries.pop(coordinate, None) is not None


@final
class FakeSecretStore:
    """A non-persistent ``SecretStore`` bound to one installation and one scope.

    Structurally implements :class:`~ai_assistant.core.protocols.SecretStore` and
    therefore :class:`~ai_assistant.core.protocols.Secrets`, which is why both
    conformance suites are bound against this one class — ADR-0125 §11's "through
    the narrow suite as a ``Secrets``, and through the wide one as itself".

    **It composes a single string coordinate, as an adapter does**, rather than
    keying its map on a tuple. A tuple key would make the injectivity ADR-0125 §2
    argues for true by construction, and the isolation cases would then be
    asserting about an arrangement no real backend has. The composition is
    length-prefixed on the installation so that it stays injective even where an
    installation path contains the joining character — a key never can, because §2
    forbids ``:`` outright.

    Two explicit switches, both test-only and neither part of any contract:
    :meth:`become_unavailable` puts it into ADR-0125 §7's state, and :meth:`fail`
    arms one method to fail with a backend error quoting a derivation §6 forbids.
    The seam grows no affordance for either — the suite asks the *subject* it was
    handed, never the Protocol every consumer depends on.

    Test-only, and no composition root wires it.

    Attributes:
        last_backend_failure: The text of the backend error the last armed failure
            modelled, or ``None``. Test-only, and the **negative control** the
            redaction case needs: without it, a fake that quietly stopped building
            a disclosing text would make every "the plaintext is absent from the
            surfaced error" assertion pass while proving nothing.
    """

    def __init__(
        self,
        *,
        scope: SecretScope = SecretScope.PROVIDER,
        installation: str = DEFAULT_INSTALLATION,
        backing: SecretBacking | None = None,
    ) -> None:
        """Create the store.

        Args:
            scope: The one :class:`~ai_assistant.core.types.SecretScope` this
                instance answers for. Every method refuses a name outside it.
            installation: The namespace ADR-0125 §2 binds an instance to,
                injected rather than read from a setting.
            backing: The machine's keyring. Pass one shared object to build two
                subjects that can observe each other's entries if either composes
                its coordinates wrongly; omit it for a subject of its own.
        """
        self._scope = scope
        self._installation = installation
        self._backing = backing if backing is not None else SecretBacking()
        self._available = True
        self._armed: dict[SecretMethod, Disclosure] = {}
        self.last_backend_failure: str | None = None

    def __repr__(self) -> str:
        """Describe the subject by its two bindings, never by what it holds.

        ADR-0125 §11 requires no secret value to appear in the ``repr`` of the
        subject, which a generated one over ``self.__dict__`` would breach through
        the backing. Naming the scope and the installation is safe — both are
        wiring, not secrets — and is what makes a failing isolation case legible.
        """
        return (
            f"{type(self).__name__}(scope={self._scope.value!r}, "
            f"installation={self._installation!r}, backing={self._backing!r})"
        )

    @property
    def scope(self) -> SecretScope:
        """The scope this instance is bound to."""
        return self._scope

    @property
    def installation(self) -> str:
        """The installation namespace this instance is bound to."""
        return self._installation

    @property
    def backing(self) -> SecretBacking:
        """The machine's keyring, shared with any subject built over the same one."""
        return self._backing

    # --- the two test-only switches ------------------------------------------

    def become_unavailable(self) -> None:
        """Put the subject into ADR-0125 §7's unavailable state.

        Models "no backend at all" and "present and locked with no unlock possible
        in this session" alike, which §7 makes one visible state deliberately.
        Every method that gets past the argument step then raises
        :class:`~ai_assistant.core.errors.SecretStoreUnavailableError`, and
        :meth:`get` never answers ``None`` for it.
        """
        self._available = False

    def become_available(self) -> None:
        """Undo :meth:`become_unavailable`, so a case can read its witness back."""
        self._available = True

    def fail(self, method: SecretMethod, disclosure: Disclosure) -> None:
        """Arm the next call to ``method`` to fail with a disclosing backend error.

        The backend error's own text quotes :func:`disclosure_of` over the
        plaintext the call is about — the value held for that name on
        :attr:`SecretMethod.GET` and :attr:`SecretMethod.DELETE`, the value it was
        given on :attr:`SecretMethod.SET` (ADR-0125 §11). What the subject
        *surfaces* is a clean :class:`~ai_assistant.core.errors.SecretStoreError`,
        which is the behaviour under test: the leak this models is the obvious
        wrapper, ``SecretStoreError(str(exc))``.

        Args:
            method: Which method fails.
            disclosure: Which derivation the backend error's text carries.
        """
        self._armed[method] = disclosure

    # --- SecretStore ---------------------------------------------------------

    async def get(self, name: SecretName) -> SecretValue | None:
        """Return the value stored under ``name``, verbatim, or ``None``."""
        coordinate = self._coordinate(self._accept(name))
        stored = self._backing.read(coordinate)
        self._fail_if_armed(SecretMethod.GET, stored)
        return None if stored is None else SecretStr(stored)

    async def set(self, name: SecretName, value: SecretValue) -> None:
        """Store ``value`` under ``name``, creating or replacing the entry."""
        accepted = self._accept(name, value=value)
        plaintext = value.get_secret_value()
        self._fail_if_armed(SecretMethod.SET, plaintext)
        self._backing.write(self._coordinate(accepted), plaintext)

    async def delete(self, name: SecretName) -> bool:
        """Remove the entry under ``name``, reporting whether one was there."""
        coordinate = self._coordinate(self._accept(name))
        self._fail_if_armed(SecretMethod.DELETE, self._backing.read(coordinate))
        return self._backing.remove(coordinate)

    # --- the argument step, which comes first and wins (ADR-0125 §4, §7) -----

    def _accept(self, name: SecretName, *, value: SecretValue | None = None) -> SecretName:
        """Revalidate the arguments, then check the scope, then the availability.

        In that order, and the order is contract rather than an implementation
        choice. ADR-0125 §7 makes the argument step come first and win: a call
        carrying a malformed name or value, **or a well-formed name outside this
        instance's scope**, raises ``ValueError`` whatever the keyring's state,
        including when there is no backend at all. A tool reaching for the device
        credential must be refused identically whether the keyring is locked,
        absent or wide open, or the refusal discloses the machine's state to the
        caller least entitled to ask.

        ``name`` is validated **as a whole**, before any attribute of it is read
        (§4). :class:`~ai_assistant.core.types.SecretName` sets
        ``revalidate_instances="always"``, so this one call re-runs the model's own
        invariants over an object ``model_construct`` produced without them —
        rather than this method dumping fields or reading ``scope`` for a backend
        prefix and so depending on invariants it had not yet checked.

        Args:
            name: The entry the call names.
            value: The secret a write supplies, or ``None`` on a read.

        Returns:
            The validated name.

        Raises:
            ValueError: If either argument fails its own type's invariants, or if
                the name's scope is not this instance's.
            SecretStoreUnavailableError: If the arguments were fine and the
                subject is in the unavailable state.
        """
        validated = SecretName.model_validate(name)
        if value is not None:
            secret_value(value)
        if validated.scope is not self._scope:
            msg = (
                f"this store is bound to the {self._scope.value!r} scope and was asked for "
                f"{validated.scope.value!r}: a call for another scope is a consumer holding "
                "the wrong instance, which is a wiring fault at the composition root"
            )
            raise ValueError(msg)
        if not self._available:
            msg = (
                "no keyring backend is available: looked for the in-memory backing this "
                "test double stands for, and found it switched off"
            )
            raise SecretStoreUnavailableError(msg)
        return validated

    def _coordinate(self, name: SecretName) -> str:
        """Compose the backend coordinate this name addresses on this instance.

        Injective over ``(installation, scope, key)``: the length prefix pins where
        the installation ends, so a path containing the joining character cannot be
        confused with a longer path and a different scope. A ``key`` never contains
        one, because ADR-0125 §2 forbids ``:`` and ``/`` for exactly this reason.
        """
        return f"{len(self._installation)}:{self._installation}:{name.scope.value}:{name.key}"

    def _fail_if_armed(self, method: SecretMethod, plaintext: str | None) -> None:
        """Raise a redacted store error where ``method`` was armed by :meth:`fail`.

        The modelled backend error is built and **dropped**, not chained: attaching
        it would put the plaintext into every traceback that prints this exception,
        which is the disclosure ADR-0125 §6 forbids arriving through the one path a
        message check cannot see. Its text is kept on
        :attr:`last_backend_failure` so a test can prove the disclosure was really
        modelled rather than quietly skipped.

        Raises:
            SecretStoreError: If ``method`` was armed. Its message names the
                operation and nothing about the value.
        """
        disclosure = self._armed.pop(method, None)
        if disclosure is None:
            return
        self.last_backend_failure = (
            None
            if plaintext is None
            else f"keyring: {method.value} rejected {disclosure_of(disclosure, plaintext)}"
        )
        msg = f"the keyring could not complete a {method.value}"
        raise SecretStoreError(msg)


#: The canonical fake for :class:`~ai_assistant.core.protocols.Secrets`, which is
#: :class:`FakeSecretStore` under the reading face's name.
#:
#: **One class, two names, and that is ADR-0125 §1's decision rather than a
#: shortcut around it.** §11 rules one canonical fake — "an in-memory
#: implementation of ``SecretStore``" — bound to both suites, and §1 rules one
#: implementation class and one keyring backing, of which a root builds one
#: instance per scope. A second class here would contradict both. What forces the
#: *name* is ``tests/core/test_protocol_triad.py``, which enumerates every
#: Protocol in ``core/protocols.py`` and requires a ``Fake<Protocol>`` exported
#: from this package for each; ``Secrets`` is such a Protocol, so the name has to
#: exist even though the object behind it does not have to be new.
FakeSecrets = FakeSecretStore

__all__ = [
    "DEFAULT_INSTALLATION",
    "OTHER_INSTALLATION",
    "Disclosure",
    "FakeSecretStore",
    "FakeSecrets",
    "SecretBacking",
    "SecretMethod",
    "disclosure_of",
]
