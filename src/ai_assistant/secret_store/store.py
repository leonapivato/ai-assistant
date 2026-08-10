"""The keyring-backed ``SecretStore``: one class, one backing, one scope each.

ADR-0125 §1 fixes the shape and §§2-7 fix the behaviour; this implements them and
adds nothing. The two obligations no shared conformance suite can express against a
subject it was handed — that a selection finding nothing usable raises rather than
falling back, and that no unprotected backend is ever selected — live in
:mod:`ai_assistant.secret_store.backend` and in this package's own tests (§11).

**Everything a caller can get wrong is refused at the boundary, before the keyring
is touched** (ADR-0125 §4, §7). Both argument types are checkable and neither
protects the boundary on its own: ``SecretValue`` is ``Annotated[SecretStr, …]``
with no runtime identity of its own, so a bare ``SecretStr`` reaches ``set`` with
the validator never having run, and ``SecretName.model_construct`` yields a
well-typed object carrying a key ADR-0125 §2 forbids — which on a case-insensitive
backend addresses the very entry a lowercase key names.

**No exception this module raises carries a value, or anything derived from one**
(ADR-0125 §6): not the plaintext, not a prefix, a suffix, a truncation, a digest or
a length. That obligation reaches further than a message, because the obvious
conforming-looking wrapper defeats a message check while writing the credential
into every traceback a reader sees::

    raise SecretStoreError("the keyring read failed") from exc

So a backend's own exception is never chained and never logged here — every refusal
below is raised *outside* the ``except`` clause that caught it, which is what stops
it becoming the new exception's ``__context__``.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Final, TypeVar, final

import keyring.errors
from pydantic import SecretStr

from ai_assistant.core.errors import SecretStoreError, SecretStoreUnavailableError
from ai_assistant.core.types import SecretName, secret_value
from ai_assistant.secret_store.backend import select_backend

if TYPE_CHECKING:
    from collections.abc import Callable

    from ai_assistant.core.types import SecretScope, SecretValue
    from ai_assistant.secret_store.backend import KeyringBackend

_T = TypeVar("_T")

#: What every coordinate this project composes begins with, so entries belonging to
#: this system are distinguishable in a keyring an owner also uses for other things.
_PREFIX: Final = "ai-assistant"

#: The `keyring` failures that mean *this machine*, rather than *this call*. A
#: keyring that is absent, will not initialise, or is locked with no unlock possible
#: in this session is a deployment condition a human clears, and retrying it is
#: futile; a write the backend rejected may be transient (ADR-0125 §6, §7).
_UNAVAILABLE: Final = (
    keyring.errors.NoKeyringError,
    keyring.errors.InitError,
    keyring.errors.KeyringLocked,
)


@final
class KeyringSecretStore:
    """One installation's one scope, in the operating system's own keyring.

    Structurally implements :class:`~ai_assistant.core.protocols.SecretStore`, and
    therefore :class:`~ai_assistant.core.protocols.Secrets` — ADR-0125 §1's "one
    object satisfies both structurally, so a composition root hands each consumer
    the face its job needs without needing two classes".

    **Bound to two facts a caller can name neither of** (ADR-0125 §2): one
    installation, injected as a namespace rather than read from a setting here, and
    one :class:`~ai_assistant.core.types.SecretScope`. So two data directories on
    one machine share no entry — the keyring is per OS user, not per data directory,
    and a QA hub's enrolment overwriting the owner's real credential is the failure
    that cannot be noticed — and a consumer reaches only the scope it was given.
    """

    def __init__(
        self,
        *,
        scope: SecretScope,
        installation: str,
        select: Callable[[], KeyringBackend] = select_backend,
    ) -> None:
        """Bind a store to one scope of one installation. Nothing is opened here.

        ADR-0125 §7: "Constructing an implementation touches no keyring. The backend
        is resolved on the first call, so a deployment with no keyring and no
        consumer needing one starts normally." ``HubEngineClient`` already takes this
        shape and states why — "a constructor that connected would make 'is the hub
        up' a question asked at a moment no command chose".

        Args:
            scope: The one scope this instance answers for. Every method refuses a
                name outside it, before the keyring is touched.
            installation: The namespace ADR-0125 §2 binds an instance to — the
                resolved ``Settings.data_dir``, injected by whoever composes this.
            select: How the backing is chosen. The default is the real one; a
                caller supplying another is how this class is driven against a
                backend a test controls (ADR-0125 §11).
        """
        self._scope = scope
        self._installation = installation
        self._select = select

    def __repr__(self) -> str:
        """Describe the store by its two bindings, never by what it holds.

        ADR-0125 §11 requires no secret value to appear in the ``repr`` of the
        subject. A generated one would be safe here too — this object holds no
        entry — but stating it is what keeps a later field from quietly changing
        that, and naming the scope and the installation is what makes a failing
        isolation case legible.
        """
        return (
            f"{type(self).__name__}(scope={self._scope.value!r}, "
            f"installation={self._installation!r})"
        )

    # --- SecretStore ---------------------------------------------------------

    async def get(self, name: SecretName) -> SecretValue | None:
        """Return the value last written under ``name``, verbatim, or ``None``.

        Args:
            name: Which entry.

        Returns:
            What is stored, byte for byte, or ``None`` where nothing is. **Never
            ``None`` because the keyring could not be read** (ADR-0125 §7): if
            absence and unreachability were one observation, a client would report
            an enrolled owner as unenrolled, and an enrolment flow reading it as a
            first run could mint a replacement credential and revoke the working one.

        Raises:
            ValueError: If ``name`` fails its own model's invariants, or names
                another scope. Whatever the keyring's state.
            SecretStoreUnavailableError: If no protected backend is available, or
                the one that is cannot be unlocked in this session.
            SecretStoreError: If the backend failed the read.
        """
        service, username = self._coordinate(self._accept(name))
        backing = self._select()
        stored = await self._run("read", lambda: backing.get_password(service, username))
        return None if stored is None else SecretStr(stored)

    async def set(self, name: SecretName, value: SecretValue) -> None:
        """Store ``value`` under ``name``, creating the entry or replacing it.

        It never refuses on the ground that an entry already exists, and that is
        ADR-0125 §4's ruling rather than convenience: ADR-0124 §6 makes re-enrolling
        a live device a **single act** that mints a replacement credential and
        forbids an intermediate state, so a store that refused an occupied name
        would force delete-then-set at the device — with a window in which it holds
        nothing, and a crash in that window leaving it unenrolled.

        Args:
            name: Which entry.
            value: The plaintext, stored **verbatim**. Nothing here trims
                whitespace, normalises Unicode, changes case or re-encodes: two
                spellings of a secret are two different secrets, and a store that
                helpfully stripped a trailing newline would produce an
                authentication failure nobody could reproduce by inspection.

        Raises:
            ValueError: If either argument fails its own type's invariants, or if
                ``name`` names another scope. Nothing is written.
            SecretStoreUnavailableError: If no protected backend is available.
            SecretStoreError: If the backend failed the write.
        """
        service, username = self._coordinate(self._accept(name, value=value))
        # The value is read *after* the argument step, and the object read is the one
        # that was validated: ADR-0125 §3 stores a value verbatim, so ``secret_value``
        # returns what it was given and has nothing to carry back.
        plaintext = value.get_secret_value()
        backing = self._select()
        await self._run("write", lambda: backing.set_password(service, username, plaintext))

    async def delete(self, name: SecretName) -> bool:
        """Remove the entry under ``name``, reporting whether one was there.

        **Read, then remove**, and ADR-0125 §4 licenses exactly that: no
        cross-platform keyring offers a compare-and-delete, so ``delete``'s ``bool``
        "is **not** a synchronisation primitive: two callers deleting one entry may
        both be told ``True``". Which is fine for the caller this exists for —
        ADR-0124 §8's device-side unenrolment, "whose whole job is to make sure the
        entry is gone".

        A backend that raises because the entry vanished between the two steps is
        treated as having found nothing, for the same reason: an unenrolment that
        raised the second time it ran would be a worse surface for the one operation
        an owner performs when something has already gone wrong.

        Args:
            name: Which entry.

        Returns:
            Whether an entry was there to remove.

        Raises:
            ValueError: If ``name`` fails its own model's invariants, or names
                another scope. Nothing is removed.
            SecretStoreUnavailableError: If no protected backend is available.
            SecretStoreError: If the backend failed the removal.
        """
        service, username = self._coordinate(self._accept(name))
        backing = self._select()
        if await self._run("read", lambda: backing.get_password(service, username)) is None:
            return False
        return await self._run(
            "removal", lambda: _forgive_an_absent_entry(backing, service, username)
        )

    # --- the argument step, which comes first and wins (ADR-0125 §4, §7) -----

    def _accept(self, name: SecretName, *, value: SecretValue | None = None) -> SecretName:
        """Revalidate the arguments and check the scope, before anything else.

        The order is contract rather than an implementation choice. ADR-0125 §7
        makes the argument step come first and win: a call carrying a malformed name
        or value, **or a well-formed name outside this instance's scope**, raises
        ``ValueError`` whatever the keyring's state, including when there is no
        backend at all. A tool reaching for the device credential must be refused
        identically whether the keyring is locked, absent or wide open, or the
        refusal discloses the machine's state to the caller least entitled to ask.

        ``name`` is validated **as a whole**, before any attribute of it is read
        (§4): :class:`~ai_assistant.core.types.SecretName` sets
        ``revalidate_instances="always"``, so this one call re-runs the model's own
        invariants over an object ``model_construct`` produced without them, rather
        than this method reading ``scope`` for a coordinate prefix and so depending
        on an invariant it had not yet checked.

        Args:
            name: The entry the call names.
            value: The secret a write supplies, or ``None`` on a read.

        Returns:
            The validated name.

        Raises:
            ValueError: If either argument fails its own type's invariants, or if
                the name's scope is not this instance's. Its message names the
                scopes and the key, which is safe and is meant to be — a
                ``SecretName`` is not a secret (§2) — and names nothing about the
                value, which §6 forbids down to its length.
        """
        validated = SecretName.model_validate(name)
        if value is not None:
            secret_value(value)
        if validated.scope is not self._scope:
            msg = (
                f"this store is bound to the {self._scope.value!r} scope and was asked for "
                f"{validated.scope.value!r}: a call for another scope is a consumer holding "
                f"the wrong instance, which is a wiring fault at whoever composed it"
            )
            raise ValueError(msg)
        return validated

    def _coordinate(self, name: SecretName) -> tuple[str, str]:
        """Compose the backend's own coordinates for one name, injectively.

        ``(service, username)`` is the only addressing a cross-platform keyring
        offers, so the installation and the scope are folded into the service and
        the key is the username. The composition must be **injective** — two
        distinct :class:`~ai_assistant.core.types.SecretName` values that collide
        here are one secret silently overwriting another (ADR-0125 §2).

        Two things could break that and neither can. The key is a separate
        component, so it cannot run into the scope. And the installation is
        **length-prefixed**, so a path that itself contains the joining character
        cannot be confused with a longer path and a different scope — a key never
        can, because §2 forbids ``:`` outright for exactly this reason.

        Args:
            name: The validated name.

        Returns:
            The service and username to address the backend with.
        """
        installation = self._installation
        service = f"{_PREFIX}:{len(installation)}:{installation}:{name.scope.value}"
        return service, name.key

    async def _run(self, operation: str, call: Callable[[], _T]) -> _T:
        """Run one backend call off the event loop, and map what it raises.

        **In a worker thread**, because the library is synchronous and a keyring
        call is a round trip to an operating-system service — one whose duration, on
        a locked store, is bounded by the owner typing a passphrase rather than by
        I/O. ADR-0083 puts the hub on one event loop, and a synchronous read there
        would stall every other connection for that long.

        ADR-0054 is **inherited rather than restated** (ADR-0125 §1): its rule is
        that a cancelled call must not release what a worker thread still holds, and
        here the thread holds only two strings and a backing object this instance
        does not own or close, so a cancelled call leaves nothing to be used after
        it was let go.

        Args:
            operation: What the call was doing, for the message. Never a value.
            call: The backend call.

        Returns:
            Whatever the backend returned.

        Raises:
            SecretStoreUnavailableError: If the failure is a condition of the
                machine that a human clears.
            SecretStoreError: If the backend failed the operation.
        """
        try:
            return await asyncio.to_thread(call)
        except _UNAVAILABLE as exc:
            unavailable, fault = True, type(exc).__name__
        except keyring.errors.KeyringError as exc:
            unavailable, fault = False, type(exc).__name__
        except Exception as exc:
            # **Untranslated means it came from under the backend, which is why this
            # is the *unavailable* branch and not the other one.** A backend turns
            # every outcome it decides into a ``KeyringError``; what reaches here
            # instead came from the transport beneath it — the Secret Service
            # backend speaks to `secretstorage` over D-Bus, and a service that goes
            # away after selection surfaces as that stack's own exception. ADR-0125
            # §6 draws the line by "the correct response differs": a keyring that is
            # "absent, locked or not running is a deployment condition a human
            # clears… a write the backend *rejected* may be transient". A dead
            # transport is the first of those, and it is also the safe direction —
            # ``SecretStoreUnavailableError`` is a subclass, so every
            # ``except SecretStoreError`` still catches it and nothing is narrowed.
            # ``Exception`` and not ``BaseException``, so a cancellation still
            # propagates (ADR-0060).
            unavailable, fault = True, type(exc).__name__
        # Raised out here, past the ``except`` clauses, so that neither the backend's
        # exception nor anything it carries becomes this one's ``__context__`` —
        # ADR-0125 §6 binds every rendering of an exception this seam raises, and a
        # chained cause is rendered in the traceback a reader actually sees. Only the
        # failure's **class name** crosses, which is a fact about the library rather
        # than a derivation of a value.
        if unavailable:
            msg = (
                f"this machine's keyring could not complete a {operation} ({fault}): it is "
                f"present but could not be reached, opened or unlocked in this session. "
                f"Start and unlock your platform's credential service and try again; this "
                f"seam never falls back to storage the operating system does not protect "
                f"(ADR-0125 §7)"
            )
            raise SecretStoreUnavailableError(msg)
        msg = (
            f"the keyring could not complete a {operation} ({fault}). The entry is named by "
            f"its scope and key, which the caller has; nothing about the value is reported "
            f"here, by ADR-0125 §6"
        )
        raise SecretStoreError(msg)


def _forgive_an_absent_entry(backing: KeyringBackend, service: str, username: str) -> bool:
    """Remove one entry, reporting ``False`` where the backend says there was none.

    ``keyring`` spells "there was nothing to delete" as an exception, and this seam
    spells it as a ``False`` (ADR-0125 §4). The two callers that can produce it are
    a race against another deleter and a backend that disagrees with the read a
    moment earlier; both mean the entry is gone, which is what the caller asked for.

    Args:
        backing: The selected backend.
        service: The composed service coordinate.
        username: The key.

    Returns:
        Whether the backend removed something.
    """
    try:
        backing.delete_password(service, username)
    except keyring.errors.PasswordDeleteError:
        return False
    return True
