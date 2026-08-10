r"""Shared conformance suites for the two keyring Protocols (ADR-0125 §11).

Every ``Secrets`` implementation must pass :class:`SecretsContract`, and every
``SecretStore`` implementation must pass :class:`SecretStoreContract` — which
inherits the first, because a store *is* the reading face plus the ability to
write. A concrete test subclasses one of them and supplies its subject.

**Two suites, because there are two Protocols and they have different subjects**
(ADR-0125 §11). A single suite asserting ``set`` "against every subject" would be
unrunnable against exactly the implementation ADR-0125 §9 exists to make possible:
a gating decorator that implements the reading face, consults ``permissions/`` and
delegates, and has no ``set`` to call. So the narrow suite arranges the state it
asserts about through an abstract :meth:`SecretsContract.given` hook the subject
implements — ``SourceGrantsContract``'s solution to the identical problem, and not
one to weaken by adding a write to the Protocol, since the absence of that write is
the property under test.

**Here rather than beside a subsystem.** The keyring-backed implementation lands
in a leaf package that does not exist yet (ADR-0125 §8), and a contract with no
owning subsystem package sits under ``tests/core/`` as ``reader_contract.py``
does. When that package arrives, its lane runs **both** suites against the adapter
over a backend it controls — every obligation here, the scope and installation
refusals, the unavailable state and §6's redaction included — plus the two
obligations no suite can express against a subject it was handed: that a backend
selection finding nothing usable raises rather than falling back, and that no
backend storing a value without the operating system's own access control is ever
selected (§11).

**What is deliberately not in here.** ADR-0125 §4's concurrency clauses — that a
``get`` never observes a partially written value, that ``delete``'s ``bool`` is
not a synchronisation primitive, that there is no atomicity across names — are
caller-facing rules rather than suite obligations, because a shared suite running
in one process can neither prove nor refute any of them portably. §4 says so in as
many words, and a suite that pretended otherwise would report an obligation as
held that nothing exercised.

Named ``*_contract`` (not ``test_*``) so pytest collects it only via a
``Test``-prefixed subclass, never the abstract bases directly.
"""

from __future__ import annotations

import contextlib
import logging
import traceback
from enum import StrEnum
from typing import TYPE_CHECKING, Final

import pytest
from pydantic import SecretStr

from ai_assistant.core.errors import SecretStoreError, SecretStoreUnavailableError
from ai_assistant.core.protocols import Secrets, SecretStore
from ai_assistant.core.types import (
    SECRET_VALUE_MAX_BYTES,
    SecretName,
    SecretScope,
    SecretValue,
)
from ai_assistant.testing import Disclosure, SecretMethod, disclosure_of

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Iterator, Mapping, Sequence

#: How long a derivation must be, once stripped, for its absence from a rendering
#: to mean anything. Below this a "derivation" is whitespace and an ellipsis —
#: what the slicing modes produce over a blank value — which ordinary source text
#: and ordinary messages contain, so asserting its absence would fail every
#: implementation while proving nothing about any of them.
MINIMUM_DISTINCTIVE_LENGTH: Final = 4

#: The scope every subject below is bound to unless a case is about another one.
BOUND_SCOPE: Final = SecretScope.PROVIDER

#: The scope a bound subject must refuse. ``ENROLMENT`` deliberately: it holds the
#: device credential ADR-0124 §6 spent a section confining, and a tool that could
#: name it would read that credential straight past §8's consumer boundary.
OTHER_SCOPE: Final = SecretScope.ENROLMENT

#: The entry every case is about unless it is about another entry.
WITNESS_KEY: Final = "github"

#: A second entry, differing from the first in ``key`` alone.
SECOND_KEY: Final = "github-work"

#: The plaintext the cases store. **Long and high-entropy on purpose**: ADR-0125
#: §11 requires the redaction case's value to be one over which a substring check
#: is a real assertion rather than one a short value would satisfy by accident.
PLAINTEXT: Final = "7f3ac9e15b2d84604ea7c1938df05b62a4e8c07d19f6b3a5c82e40d7b169fa3e"

#: Values a store must return exactly as it was given them (ADR-0125 §3). Each
#: names one thing a "helpful" implementation trims, folds or re-encodes, and each
#: is a different secret from its normalised form: an authentication failure
#: nobody can reproduce by inspection is what a stripped trailing newline buys.
VERBATIM_VALUES: Final = (
    pytest.param("  padded with spaces  ", id="leading and trailing whitespace"),
    pytest.param("first line\nsecond line\n", id="embedded and trailing newlines"),
    pytest.param("naïve-café-日本語-🙂", id="non-ASCII, composed and supplementary"),
    pytest.param("\tugly\r\n\xa0mixed  whitespace\t", id="tabs, CRLF and a no-break space"),
)


def secret_name(key: str = WITNESS_KEY, scope: SecretScope = BOUND_SCOPE) -> SecretName:
    """A well-formed name, built the way a caller builds one."""
    return SecretName(scope=scope, key=key)


def held(plaintext: str = PLAINTEXT) -> SecretValue:
    """A well-formed value, built through the type a caller holds."""
    return SecretStr(plaintext)


#: The witness every refusal case leaves behind it. A refusal changes nothing, so
#: this entry reads back unchanged afterwards — and it shares its key with the
#: uppercase forged name below, which is the collision ADR-0125 §2's character
#: rule exists to prevent: on a case-insensitive backend ``GitHub`` addresses the
#: very entry ``github`` names.
WITNESS: Final = secret_name()

#: Names no method may act on (ADR-0125 §2, §4, §7). The first is well-formed and
#: simply belongs to another scope; the rest are **forged** — built through
#: ``model_construct``, which is public, skips validation entirely, and yields an
#: object that passes ``isinstance`` and every static check while carrying a key
#: §2 forbids. A suite that only built names the normal way would prove the
#: validator runs, never that the seam calls it.
REFUSED_NAMES: Final = (
    pytest.param(secret_name(scope=OTHER_SCOPE), id="another scope, well-formed"),
    pytest.param(
        SecretName.model_construct(scope=BOUND_SCOPE, key=WITNESS_KEY.title()),
        id="forged: uppercase key, colliding with the witness",
    ),
    pytest.param(
        SecretName.model_construct(scope=BOUND_SCOPE, key="github:work"),
        id="forged: a colon in the key",
    ),
    pytest.param(
        SecretName.model_construct(scope=BOUND_SCOPE, key="g" * 65),
        id="forged: a 65-character key",
    ),
    pytest.param(
        SecretName.model_construct(scope="not-a-scope", key=WITNESS_KEY),
        id="forged: no valid scope",
    ),
)

#: A plaintext of exactly one byte over ADR-0125 §3's bound, and high-entropy so
#: that every derivation of it is checkable.
OVERSIZED_PLAINTEXT: Final = (PLAINTEXT * 20)[: SECRET_VALUE_MAX_BYTES + 1]

#: Values ``set`` must refuse, each built as a **bare** ``SecretStr`` — which is
#: the argument ``set`` actually receives. :data:`~ai_assistant.core.types.
#: SecretValue` is ``Annotated[SecretStr, …]`` with no runtime identity of its
#: own, so pydantic runs its validator only when a model field carrying the
#: annotation is validated; a direct construction satisfies every static check
#: while the validator never runs (ADR-0125 §4).
REFUSED_VALUES: Final = (
    pytest.param(SecretStr("   "), id="blank"),
    pytest.param(SecretStr(OVERSIZED_PLAINTEXT), id="one byte over the bound"),
    pytest.param(SecretStr(f"{PLAINTEXT}\ud800"), id="an unpaired surrogate"),
)


class Isolation(StrEnum):
    """Which of the two facts ADR-0125 §2 binds to an instance a pair differs in.

    Both pairs are proved over **one backing**, which is what gives either teeth:
    two subjects holding separate maps cannot observe each other's entries however
    the adapter composes its coordinates, so the pairing alone would prove nothing.
    Over one backing they can, and that is the real deployment — one OS keyring
    holding every scope of every installation on the machine.
    """

    INSTALLATION = "installation"
    SCOPE = "scope"


def checkable_disclosures(plaintext: str) -> Mapping[Disclosure, str]:
    """Every derivation ADR-0125 §6 names that is checkable over ``plaintext``.

    §6's list is the single source, so this iterates :class:`Disclosure` rather
    than naming derivations again — a second list beside the prohibition is how
    the two drift, and the shorter one becomes the floor.

    Two are dropped, each for a stated reason rather than by convenience. A
    derivation of an **unencodable** plaintext has no byte form at all, so a
    digest and a length are not merely absent from a message but uncomputable.
    And a derivation shorter than :data:`MINIMUM_DISTINCTIVE_LENGTH` once
    stripped is not a *disclosure*: the slicing derivations of a blank value are
    whitespace and an ellipsis, which ordinary source text and ordinary messages
    contain, so asserting their absence would fail every implementation while
    proving nothing about any of them. The derivations that stay distinctive for a
    short value — its digest and its length — are unaffected, and
    ``test_fake_secrets.py`` pins that nothing at all is dropped over the plaintext
    the cases actually store.

    Args:
        plaintext: The value a refusal or a backend error was about.

    Returns:
        Each checkable derivation, mapped to the exact text it discloses.
    """
    checkable: dict[Disclosure, str] = {}
    for disclosure in Disclosure:
        try:
            text = disclosure_of(disclosure, plaintext)
        except UnicodeEncodeError:
            continue
        if len(text.strip()) >= MINIMUM_DISTINCTIVE_LENGTH:
            checkable[disclosure] = text
    return checkable


def disclosing_renderings(error: BaseException) -> tuple[str, ...]:
    """Everything ``error`` can put in front of a reader (ADR-0125 §6).

    **Wider than ADR-0125 §11's three renderings, deliberately, because §6 is
    wider.** §11 requires the surfaced error's message, its arguments and its
    ``repr`` to disclose nothing, and those three are the floor rather than the
    prohibition: §6 binds "**no exception raised by this seam**", and the obvious
    conforming-looking adapter defeats all three at once with

        raise SecretStoreError("the keyring read failed") from exc

    where ``exc`` is the backend's own error naming the credential. Message, args
    and ``repr`` are all clean; the traceback anyone reads — in a log, in a crash
    report, in a terminal — carries the secret. So the chain is walked and the
    formatted traceback is included, and a conforming implementation may still
    chain, as long as what it chains discloses nothing.

    ``traceback.format_exception`` already renders the whole chain, which is
    exactly what a reader sees. The explicit walk beside it adds each link's own
    ``str``, ``repr`` and arguments, because an argument may be an object whose
    rendering inside a traceback differs from its own, and it is cycle-guarded
    because ``__context__`` can close a loop.

    Args:
        error: The exception the seam surfaced.

    Returns:
        Every rendering to assert against.
    """
    renderings: list[str] = list(traceback.format_exception(error))
    seen: set[int] = set()
    pending: list[BaseException] = [error]
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        renderings.extend((str(current), repr(current), *(str(a) for a in current.args)))
        pending.extend(
            link for link in (current.__cause__, current.__context__) if link is not None
        )
    return tuple(renderings)


def log_renderings(records: Sequence[logging.LogRecord]) -> tuple[str, ...]:
    """Every log line ``records`` would actually emit (ADR-0125 §6).

    **Formatted rather than ``getMessage()``**, and that is the whole point.
    ``logger.exception("keyring read failed")`` inside a handler produces a record
    whose message is four harmless words and whose ``exc_info`` carries the backend
    exception naming the credential; every formatter in ordinary use emits the
    traceback with it. A check reading only ``getMessage()`` passes an
    implementation that writes the secret into its log on every failure.
    """
    formatter = logging.Formatter()
    return tuple(formatter.format(record) for record in records)


class SecretsContract:
    """Behaviour every ``Secrets`` implementation must exhibit (ADR-0125 §11).

    Every obligation here binds a ``SecretStore`` too, which is why
    :class:`SecretStoreContract` inherits rather than repeats them — and inherits
    them **against the same subject**, seen through the narrow face, so "one
    implementation satisfies both" is a test rather than an assertion.
    """

    # --- what a subclass supplies -------------------------------------------

    @pytest.fixture
    def secrets(self) -> Secrets:
        """Override in a subclass to supply the implementation under test.

        The subject must start **empty** and must be bound to :data:`BOUND_SCOPE`:
        every case arranges the entries it is about through :meth:`given`, and the
        scope cases assert that a name for :data:`OTHER_SCOPE` is refused.
        """
        raise NotImplementedError

    async def given(self, secrets: Secrets, name: SecretName, value: SecretValue) -> None:
        """Override to make ``name`` hold ``value`` in the subject.

        The one thing a generic case cannot do for itself. ``Secrets`` has a single
        member and it is a query, so a suite for the narrow face has no
        contract-level way to arrange the state it asserts about — which is exactly
        the property being tested, and therefore not one to weaken by adding a
        write to the Protocol. A store implements this with ``set``; a gating
        decorator implements it by arranging the store it delegates to.
        """
        raise NotImplementedError

    def paired_over_one_backing(self, *, differing: Isolation) -> tuple[Secrets, Secrets]:
        """Override to return two empty subjects sharing one backing.

        They differ in exactly the fact ``differing`` names and in nothing else:
        the same installation and two scopes, or the same scope and two
        installations. The first is always bound to :data:`BOUND_SCOPE` and to the
        installation :attr:`secrets` uses.
        """
        raise NotImplementedError

    @contextlib.contextmanager
    def unavailable(self, secrets: Secrets) -> Iterator[None]:
        """Override to drive ``secrets`` into ADR-0125 §7's unavailable state.

        Restored on exit, so a case can read its witness back afterwards. The
        default skips, which is what the ``optional_obligation`` marks on the cases
        that use it are for: an implementation that cannot be driven into that
        state opts out, and the canonical fake, which can, does not.
        """
        pytest.skip("this subject cannot be driven into the unavailable state")
        yield  # type: ignore[unreachable]  # never runs; `yield` is what makes this a generator

    def arm_disclosing_failure(
        self, secrets: Secrets, *, method: SecretMethod, disclosure: Disclosure
    ) -> None:
        """Override to make the next call to ``method`` fail disclosingly.

        The subject's backend must fail with an error whose own text contains
        :func:`~ai_assistant.testing.disclosure_of` over the plaintext that call is
        about — the value held for the name on ``get`` and ``delete``, the value it
        was given on ``set``. What the subject must then *surface* is what the case
        asserts.

        The default skips, on :meth:`unavailable`'s terms.
        """
        pytest.skip("this subject cannot be driven to fail with a disclosing backend error")

    # --- the shared machinery every refusal case runs through ----------------

    def calls_of(
        self, secrets: Secrets, name: SecretName, value: SecretValue
    ) -> Mapping[SecretMethod, Callable[[], Awaitable[object]]]:
        """Every method **the subject has**, as a call carrying ``name``.

        Discovered from the subject rather than listed per case, and that is the
        point of it. ADR-0125 §11 binds its argument-refusal obligations to "every
        method that has one" and its redaction obligation to "every method the
        subject has"; a hand-written list beside them is a second enumeration that
        review found narrower than the rule three times running while this ADR was
        being written. A method added to either Protocol later is covered here by
        overriding one mapping, not by revisiting every case.
        """
        calls: dict[SecretMethod, Callable[[], Awaitable[object]]] = {
            SecretMethod.GET: lambda: secrets.get(name)
        }
        if isinstance(secrets, SecretStore):
            store = secrets
            calls[SecretMethod.SET] = lambda: store.set(name, value)
            calls[SecretMethod.DELETE] = lambda: store.delete(name)
        return calls

    async def assert_every_method_refuses(self, secrets: Secrets, name: SecretName) -> None:
        """Assert every method the subject has raises ``ValueError`` for ``name``.

        ``ValueError`` and not a store error, whatever the keyring's state: a
        malformed or out-of-scope argument is a caller fault, deterministic and
        reproducible, and nothing about the store failed (ADR-0125 §6). Neither
        :class:`SecretStoreError` nor
        :class:`SecretStoreUnavailableError` is a ``ValueError``, so the assertion
        below discriminates on its own.
        """
        for method, call in self.calls_of(secrets, name, held()).items():
            with pytest.raises(ValueError) as raised:  # noqa: PT011  # the type is the assertion
                await call()
            assert_discloses_nothing(raised.value, PLAINTEXT, context=method)

    async def assert_witness_intact(self, secrets: Secrets) -> None:
        """Assert the witness entry survived whatever the case just did.

        A refusal "changes nothing", and the sharpest case is the forged uppercase
        key: on a case-insensitive backend it addresses the very entry the witness
        names, so a seam that dereferenced it before validating would have read,
        overwritten or removed the witness while reporting a refusal.
        """
        found = await secrets.get(WITNESS)
        assert found is not None, "a refusal removed the witness entry"
        assert found.get_secret_value() == PLAINTEXT, "a refusal rewrote the witness entry"

    # --- the reading face's obligations (ADR-0125 §3, §4, §11) ---------------

    def test_conforms_to_protocol(self, secrets: Secrets) -> None:
        assert isinstance(secrets, Secrets)

    @pytest.mark.parametrize("plaintext", VERBATIM_VALUES)
    async def test_a_stored_value_comes_back_verbatim(
        self, secrets: Secrets, plaintext: str
    ) -> None:
        """Byte for byte, with nothing trimmed, folded, re-cased or re-encoded.

        Stated as an obligation because the corpus has a *normalising* habit for
        good reasons elsewhere — ADR-0121 §1 casefolds and normalises where two
        spellings of a name should be one thing — and a credential is the exact
        inverse. Two spellings of a secret are two different secrets.
        """
        await self.given(secrets, WITNESS, held(plaintext))

        found = await secrets.get(WITNESS)

        assert found is not None
        assert found.get_secret_value() == plaintext

    async def test_an_unset_name_reads_as_none(self, secrets: Secrets) -> None:
        """``None`` is a clean answer about an empty keyring, not a failure.

        The state every first run is in: no credential has been provisioned, and
        that is not a fault (ADR-0125 §4). What it must never mean is "the keyring
        could not be read" — see the unavailable case, which is the same method
        answering the other way.
        """
        assert await secrets.get(WITNESS) is None

    async def test_two_names_differing_only_in_key_are_distinct_entries(
        self, secrets: Secrets
    ) -> None:
        """The key is part of the address, not decoration on it."""
        await self.given(secrets, WITNESS, held("first"))
        await self.given(secrets, secret_name(SECOND_KEY), held("second"))

        first = await secrets.get(WITNESS)
        second = await secrets.get(secret_name(SECOND_KEY))

        assert first is not None
        assert second is not None
        assert first.get_secret_value() == "first"
        assert second.get_secret_value() == "second"

    @pytest.mark.parametrize("name", REFUSED_NAMES)
    async def test_every_method_refuses_a_name_it_may_not_act_on(
        self, secrets: Secrets, name: SecretName
    ) -> None:
        """The argument step: revalidation and the scope binding, on every method.

        **The scope refusal is what makes ADR-0125 §8's consumer boundary a
        mechanism rather than a sentence.** A ``SecretName`` carries its scope as
        data and §2 makes it safe to log, so a tool holding a subject bound only to
        an installation could construct an ``ENROLMENT`` name — a value it can read
        off the ADR — and read the device credential §6 confines. Splitting read
        from write does not touch that: the whole attack is a read.

        The forged names are the cases ordinary construction cannot reach.
        ``model_construct`` is public and yields an object carrying a key §2
        forbids, so a suite that only built names the normal way would prove the
        validator runs, never that the seam calls it.
        """
        await self.given(secrets, WITNESS, held())

        await self.assert_every_method_refuses(secrets, name)

        await self.assert_witness_intact(secrets)

    @pytest.mark.optional_obligation
    @pytest.mark.parametrize("name", REFUSED_NAMES)
    async def test_the_argument_step_wins_over_an_unreachable_keyring(
        self, secrets: Secrets, name: SecretName
    ) -> None:
        """The same refusals again, with the subject driven unavailable (§7, §11).

        **Every** argument-refusal obligation runs twice, and binding the
        precedence to the refusal cases rather than listing it against some of them
        is the decision ADR-0125 §11 records: review found the gap three times
        running, each time one method or one malformed argument further out,
        because a hand-written list of "which refusals are also tested while
        unavailable" is a second enumeration beside the refusals themselves.

        ``ValueError`` is required in both states. §4 already requires revalidation
        *before* the keyring is touched, so an implementation reporting
        unavailability first would have had to reach the backend to find out; and a
        tool reaching for the device credential must be refused identically whether
        the keyring is locked, absent or wide open, or the refusal discloses the
        machine's state to the caller least entitled to ask.
        """
        await self.given(secrets, WITNESS, held())

        with self.unavailable(secrets):
            await self.assert_every_method_refuses(secrets, name)

        await self.assert_witness_intact(secrets)

    @pytest.mark.optional_obligation
    async def test_an_unreachable_keyring_raises_and_never_answers_none(
        self, secrets: Secrets
    ) -> None:
        """Absence and unreachability are different answers (ADR-0125 §7).

        The clause that stops the worst failure available here. If an unreachable
        keyring answered ``None``, "this device is not enrolled" and "this device's
        keyring is locked" would be one observation: a client would report the
        owner as unenrolled while they are enrolled, and an enrolment flow reading
        ``None`` as a first run could mint a replacement credential and, under
        ADR-0124 §6's uniqueness clause, revoke the working one.

        ``pytest.raises`` is what proves the second half: a ``get`` that returned
        ``None`` would fail this case rather than pass it quietly.
        """
        await self.given(secrets, WITNESS, held())

        with self.unavailable(secrets):
            for method, call in self.calls_of(secrets, WITNESS, held()).items():
                with pytest.raises(SecretStoreUnavailableError):
                    await call()
                assert isinstance(method, SecretMethod)

        await self.assert_witness_intact(secrets)

    @pytest.mark.parametrize("differing", list(Isolation), ids=str)
    async def test_two_subjects_over_one_backing_share_no_entry(self, differing: Isolation) -> None:
        """Under one key, neither subject's entry reaches the other (§2, §11).

        The two failures §2 exists to prevent, and both are silent. ``api-key``
        under ``PROVIDER`` and under ``INTEGRATION`` collapsing into one entry; and
        a second data directory on one machine overwriting the first's credential
        at enrolment and deleting it at unenrolment — data loss produced by a
        namespace nobody chose, and routine during QA, because the keyring is per
        OS user rather than per data directory.

        It is also the only arrangement that catches an adapter serialising ``key``
        alone.
        """
        first, second = self.paired_over_one_backing(differing=differing)
        first_name = secret_name()
        second_name = secret_name(scope=OTHER_SCOPE) if differing is Isolation.SCOPE else WITNESS

        await self.given(first, first_name, held("the first subject's"))

        assert await second.get(second_name) is None, "an entry reached the wrong subject"

        await self.given(second, second_name, held("the second subject's"))
        reread = await first.get(first_name)

        assert reread is not None, "the second subject's write removed the first's entry"
        assert reread.get_secret_value() == "the first subject's", "one entry overwrote the other"

    # --- nothing renders a secret (ADR-0125 §3, §6, §11) ---------------------

    async def test_no_secret_value_appears_in_a_repr(self, secrets: Secrets) -> None:
        """Not in the subject's, not in the value's, not in an error the seam raises.

        The redacting type is the mechanism rather than a convenience:
        ``core/logging.py`` redacts by *key name*, so a plain ``str`` keeps that
        promise only for as long as every call site chooses a covered key. A type
        whose default rendering is ``**********`` inverts the default — a
        disclosure requires somebody to write the unwrapping call, which makes it
        deliberate and reviewable rather than accidental.
        """
        await self.given(secrets, WITNESS, held())
        found = await secrets.get(WITNESS)
        assert found is not None

        assert PLAINTEXT not in repr(secrets)
        assert PLAINTEXT not in repr(found)
        assert PLAINTEXT not in str(found)

        with pytest.raises(ValueError) as raised:  # noqa: PT011  # the type is the assertion
            await secrets.get(secret_name(scope=OTHER_SCOPE))
        assert_discloses_nothing(raised.value, PLAINTEXT, context="a scope refusal")

    @pytest.mark.optional_obligation
    @pytest.mark.parametrize("disclosure", list(Disclosure), ids=str)
    @pytest.mark.parametrize("method", list(SecretMethod), ids=str)
    async def test_a_failing_backend_discloses_no_derivation(
        self,
        secrets: Secrets,
        method: SecretMethod,
        disclosure: Disclosure,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """A backend that names the value must not surface one that does (§6, §11).

        **This is the leak the other redaction case cannot see.** Proving a
        ``SecretValue``'s ``repr`` redacts says nothing about the path where the
        value has already left the type: a backend that rejects a call and names
        the value in its message, wrapped by the obvious
        ``SecretStoreError(str(exc))``, writes the credential into an error that
        ADR-0004 §5's redaction processor will not catch, because that processor
        redacts by key rather than by content.

        **It runs for every method the subject has, and ``set`` alone would have
        been the wrong half.** A ``set`` failure discloses a value the caller
        already holds; a ``get`` failure discloses one the caller was *refused* —
        the credential a reader could not obtain, arriving through the error path
        instead. An adapter that redacts ``set`` and wraps ``get``'s backend
        exception is both plausible and a leak, and every case written only around
        ``set`` passes it.

        **And over every derivation, because a verbatim check catches none of
        them.** A wrapper reporting ``value[:8]``, ``value[-8:]`` or a digest
        passes a substring assertion over the whole value while disclosing what
        ADR-0021 §1 calls a weakened copy of a low-entropy secret.
        """
        calls = self.calls_of(secrets, WITNESS, held())
        if method not in calls:
            pytest.skip(f"this subject has no {method.value}")
        await self.given(secrets, WITNESS, held())
        self.arm_disclosing_failure(secrets, method=method, disclosure=disclosure)

        with caplog.at_level(logging.DEBUG), pytest.raises(SecretStoreError) as raised:
            await calls[method]()

        assert_discloses_nothing(raised.value, PLAINTEXT, context=(method, disclosure))
        assert_no_log_discloses(caplog.records, PLAINTEXT, context=(method, disclosure))


class SecretStoreContract(SecretsContract):
    """Behaviour every ``SecretStore`` implementation must exhibit (ADR-0125 §11).

    Inherits every obligation of the reading face and binds it to **this** subject
    through the narrow face rather than to a second object, which is ADR-0125 §1's
    "one object satisfies both structurally" tested rather than asserted. On top of
    that it adds the write obligations, and the argument refusals that only a write
    can carry.
    """

    @pytest.fixture
    def store(self) -> SecretStore:
        """Override in a subclass to supply the store under test, empty."""
        raise NotImplementedError

    @pytest.fixture
    def secrets(self, store: SecretStore) -> Secrets:
        """The same subject, seen through the reading face.

        Not a second object: the inherited obligations must bind *this* store.
        """
        return store

    async def given(self, secrets: Secrets, name: SecretName, value: SecretValue) -> None:
        """Arrange through ``set`` itself, since a store has a contracted way to.

        So the inherited cases run against state the store's own write path
        produced, rather than against state a test reached in behind it.
        """
        assert isinstance(secrets, SecretStore)
        await secrets.set(name, value)

    def test_conforms_to_the_store_protocol(self, store: SecretStore) -> None:
        assert isinstance(store, SecretStore)

    # --- the write path (ADR-0125 §4) ---------------------------------------

    async def test_a_set_then_get_round_trip_returns_the_value_verbatim(
        self, store: SecretStore
    ) -> None:
        """The round trip through the contract's own members, end to end."""
        await store.set(WITNESS, held())

        found = await store.get(WITNESS)

        assert found is not None
        assert found.get_secret_value() == PLAINTEXT

    async def test_set_over_an_occupied_name_replaces_and_leaves_one_entry(
        self, store: SecretStore
    ) -> None:
        """Replace rather than refuse, because rotation is the case that matters.

        ADR-0124 §6 makes re-enrolling a device that already has a live enrolment a
        single act that mints a replacement credential, and forbids an intermediate
        state. A store that refused an occupied name would force delete-then-set at
        the device, with a window in which it holds nothing and a crash in that
        window leaving it unenrolled.

        "Leaves one entry" is proved through ``delete``, which is the only member
        that can count: one removal succeeds and the next reports nothing there.
        """
        await store.set(WITNESS, held("first"))
        await store.set(WITNESS, held("second"))

        found = await store.get(WITNESS)
        assert found is not None
        assert found.get_secret_value() == "second"

        assert await store.delete(WITNESS) is True
        assert await store.delete(WITNESS) is False

    async def test_deleting_an_unset_name_reports_false_and_raises_nothing(
        self, store: SecretStore
    ) -> None:
        """Absence is never an error, and repeating a delete is safe (§4, §6).

        The caller is ADR-0124 §8's device-side unenrolment, whose whole job is to
        make sure the entry is gone. An unenrolment that raised the second time it
        ran would be a worse surface for the one operation an owner performs when
        something has already gone wrong.
        """
        assert await store.delete(WITNESS) is False

    async def test_delete_reports_true_once_and_false_thereafter(self, store: SecretStore) -> None:
        """And the entry is gone afterwards, which is what the caller needed."""
        await store.set(WITNESS, held())

        assert await store.delete(WITNESS) is True
        assert await store.delete(WITNESS) is False
        assert await store.get(WITNESS) is None

    # --- the write path's own argument refusals (ADR-0125 §3, §4, §7) --------

    async def assert_set_refuses(self, store: SecretStore, value: SecretValue) -> None:
        """Assert ``set`` refuses ``value`` against an unset name **and an occupied one**.

        Both, because "stores nothing" has two halves and the weaker one is the
        easy assertion to stop at. Against an unset name a refusal must create no
        entry; against a name that already holds a value it must not overwrite or
        remove what is there — and an implementation that wrote first and validated
        afterwards passes the first half while failing the second, having destroyed
        a credential on its way to reporting a refusal.

        The refusal itself must also disclose nothing, which ADR-0125 §11 binds to
        *every* way this seam raises rather than to backend failures alone: "secret
        length is 1025" is what a size check naturally reports, and it hands over a
        derivation from the seam's own code.

        The caller asserts the surviving state afterwards, because the doubled
        variant runs this inside the unavailable context and can only read the
        subject back once it has left.
        """
        rejected = value.get_secret_value()

        with pytest.raises(ValueError) as on_unset:  # noqa: PT011  # the type is the assertion
            await store.set(secret_name(SECOND_KEY), value)
        assert_discloses_nothing(on_unset.value, rejected, context="refused on an unset name")

        with pytest.raises(ValueError) as on_occupied:  # noqa: PT011  # the type is the assertion
            await store.set(WITNESS, value)
        assert_discloses_nothing(on_occupied.value, rejected, context="refused on an occupied name")

    @pytest.mark.parametrize("value", REFUSED_VALUES)
    async def test_set_refuses_a_value_its_type_would_not_admit(
        self, store: SecretStore, value: SecretValue
    ) -> None:
        """And stores nothing, in every case (ADR-0125 §4, §11).

        Neither type protects this boundary on its own.
        :data:`~ai_assistant.core.types.SecretValue` is ``Annotated[SecretStr, …]``
        with no runtime identity distinct from ``SecretStr``, so a caller building
        one directly satisfies every static check while the validator never runs.
        An implementation may not rely on it having been validated upstream, which
        is what :class:`~ai_assistant.core.errors.AssistantError` already does for
        the same reason.

        **The surrogate case is named rather than left to "UTF-8 encodable",
        because it is the one that survives every other check.** ``"\\ud800"`` is
        non-blank, is one character, and has no byte length at all — measuring it
        *is* encoding it, so a budget check written as ``len(value.encode())``
        raises ``UnicodeEncodeError`` instead of the ``ValueError`` §3 promises,
        and an adapter that skips the check hands a backend a string with no wire
        form (ADR-0087 §2b).

        **And the refusal discloses nothing**, which §11 binds to *every* way this
        seam raises rather than to backend failures alone. A refusal is the
        likelier leak of the two, because the obvious message contains one:
        "secret length is 1025" is what a size check naturally reports, and it
        hands over a derivation from the seam's own code.
        """
        await store.set(WITNESS, held())

        await self.assert_set_refuses(store, value)

        await self.assert_witness_intact(store)
        assert await store.get(secret_name(SECOND_KEY)) is None, "a refused write created an entry"

    @pytest.mark.optional_obligation
    @pytest.mark.parametrize("value", REFUSED_VALUES)
    async def test_set_refuses_a_bad_value_while_the_keyring_is_unreachable(
        self, store: SecretStore, value: SecretValue
    ) -> None:
        """The same refusals, doubled — §7's argument step wins here too (§11).

        This is the case the enumeration kept missing: scope mismatches covered and
        blank values not. Doubling *every* refusal is a mechanical rule with no edge
        for a later variant to arrive through.
        """
        await store.set(WITNESS, held())

        with self.unavailable(store):
            await self.assert_set_refuses(store, value)

        await self.assert_witness_intact(store)
        assert await store.get(secret_name(SECOND_KEY)) is None, "a refused write created an entry"

    async def test_an_out_of_scope_write_or_delete_leaves_the_other_scope_alone(
        self, store: SecretStore
    ) -> None:
        """Refused, and the entry it would have addressed is untouched (§2, §11).

        Proved over one backing rather than by inspecting the subject: the entry an
        ``ENROLMENT`` name addresses is real, another subject holds it, and the
        question is whether this subject can reach it. That is the device
        credential, and a tool that could write or delete it would defeat the
        boundary ADR-0124 §6 spent a section building.
        """
        bound, other = self.paired_over_one_backing(differing=Isolation.SCOPE)
        assert isinstance(bound, SecretStore)
        elsewhere = secret_name(scope=OTHER_SCOPE)
        await self.given(other, elsewhere, held())

        with pytest.raises(ValueError):  # noqa: PT011  # the type is the assertion
            await bound.set(elsewhere, held("overwritten"))
        with pytest.raises(ValueError):  # noqa: PT011  # the type is the assertion
            await bound.delete(elsewhere)

        survived = await other.get(elsewhere)
        assert survived is not None, "an out-of-scope delete removed another scope's entry"
        assert survived.get_secret_value() == PLAINTEXT, "an out-of-scope write landed"

    async def test_a_second_installation_cannot_delete_the_first_s_entry(
        self, store: SecretStore
    ) -> None:
        """The data loss ADR-0125 §2 names, on the removal side (§11).

        ADR-0083 puts one resident process per data directory, so two data
        directories on one machine is a supported deployment and a routine one
        during QA. A test hub's unenrolment deleting the owner's real credential is
        the failure that cannot be noticed, which is why it is asserted rather than
        argued.
        """
        first, second = self.paired_over_one_backing(differing=Isolation.INSTALLATION)
        assert isinstance(second, SecretStore)
        await self.given(first, WITNESS, held())

        assert await second.delete(WITNESS) is False

        survived = await first.get(WITNESS)
        assert survived is not None, "another installation's unenrolment removed the entry"
        assert survived.get_secret_value() == PLAINTEXT


def assert_discloses_nothing(error: BaseException, plaintext: str, *, context: object) -> None:
    """Assert ``error`` carries no derivation of ``plaintext`` (ADR-0125 §6).

    Over everything :func:`disclosing_renderings` reaches — the message, the
    arguments and the ``repr`` §11 names, and the chained causes and formatted
    traceback §6 also binds. The derivations come from
    :func:`checkable_disclosures`, which reads §6's list rather than repeating it,
    so a derivation added to that list is a case this helper starts making without
    any of the suites being edited.

    Args:
        error: The exception the seam surfaced.
        plaintext: The value the failing call was about.
        context: What the case was doing, for a legible failure.
    """
    _assert_none_disclose(disclosing_renderings(error), plaintext, context=context)


def assert_no_log_discloses(
    records: Sequence[logging.LogRecord], plaintext: str, *, context: object
) -> None:
    """Assert no captured log line carries a derivation of ``plaintext`` (§6).

    ADR-0125 §6 binds "no log line an implementation emits" on the same terms as
    the exception, so this reads the same derivation list and formats each record
    the way a handler would — see :func:`log_renderings` for why ``getMessage()``
    alone is not the line that gets emitted.

    Args:
        records: Whatever the case captured while the subject ran.
        plaintext: The value the failing call was about.
        context: What the case was doing, for a legible failure.
    """
    _assert_none_disclose(log_renderings(records), plaintext, context=context)


def _assert_none_disclose(renderings: Sequence[str], plaintext: str, *, context: object) -> None:
    """The one assertion both public helpers make, over whatever they rendered."""
    for disclosure, text in checkable_disclosures(plaintext).items():
        for rendering in renderings:
            assert text not in rendering, f"{disclosure} disclosed in {rendering!r} ({context})"
