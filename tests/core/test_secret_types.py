r"""The three keyring types, proved over themselves (ADR-0125 §11).

Beside the conformance suites rather than inside them, because these are
obligations of :class:`~ai_assistant.core.types.SecretName`,
:data:`~ai_assistant.core.types.SecretValue` and
:func:`~ai_assistant.core.types.secret_value` rather than of any subject: an
implementation cannot satisfy or breach them, it only inherits them. What the
suites carry is the other half — that a seam **revalidates** rather than trusting
that these ran (ADR-0125 §4), which is a different claim and is not provable here.

The two exceptions are deliberate and are called out where they appear: a value
built as a bare ``SecretStr`` and a name built through ``model_construct`` both
reach a seam with no validator having run, so those live in the suites, over a
subject, where they mean something.
"""

from __future__ import annotations

import unicodedata
from typing import Final

import pytest
from pydantic import BaseModel, SecretStr, ValidationError

from ai_assistant.core.types import (
    SECRET_KEY_MAX_LENGTH,
    SECRET_VALUE_MAX_BYTES,
    SecretName,
    SecretScope,
    SecretValue,
    secret_value,
)
from ai_assistant.testing import Disclosure, disclosure_of

#: A plaintext long enough that every derivation of it is distinctive.
PLAINTEXT: Final = "7f3ac9e15b2d84604ea7c1938df05b62a4e8c07d19f6b3a5c82e40d7b169fa3e"


class _Carrier(BaseModel):
    """A model field annotated with the alias, which is the other real spelling.

    :data:`SecretValue` is an ``Annotated`` alias, so pydantic runs its
    ``AfterValidator`` when a model carrying the field is validated. That path and
    :func:`secret_value` must agree, or "the callable is the only supported way to
    build one" would be true of one spelling and false of the other.
    """

    value: SecretValue


# --- SecretScope: closed at three, and the closure is the mechanism ----------


def test_the_scope_enum_is_closed_at_the_three_members_the_adr_names() -> None:
    """A fourth consumer needs a fourth member, which is `core` surface (§2).

    Pinned as a test because the closure is what converts ADR-0004 §3's discipline
    — one contracted path to the keyring, not a bespoke one per layer — from a
    sentence a lane can overlook into a question that has to be answered on the
    record. ADR-0078 §11's secret-tier arm is the standing example of a lane whose
    first act is a contract ADR adding one; ADR-0004 §4's encryption key is the
    other.
    """
    assert [member.value for member in SecretScope] == ["provider", "integration", "enrolment"]


# --- SecretName: the key grammar (ADR-0125 §2) -------------------------------


@pytest.mark.parametrize(
    "key",
    [
        pytest.param("github", id="a bare word"),
        pytest.param("g", id="one character"),
        pytest.param("g" * SECRET_KEY_MAX_LENGTH, id="exactly the maximum length"),
        pytest.param("api.key_v2-beta", id="every admitted punctuation mark"),
        pytest.param("0auth2", id="beginning with a digit"),
    ],
)
def test_a_key_within_the_grammar_is_admitted(key: str) -> None:
    """The grammar admits what a real consumer would name an entry."""
    assert SecretName(scope=SecretScope.PROVIDER, key=key).key == key


@pytest.mark.parametrize(
    "key",
    [
        pytest.param("GitHub", id="uppercase"),
        pytest.param("git hub", id="an internal space"),
        pytest.param(" github", id="a leading space"),
        pytest.param("github ", id="a trailing space"),
        pytest.param("git\thub", id="a tab"),
        pytest.param("git\nhub", id="a newline"),
        pytest.param("git\x00hub", id="a control character"),
        pytest.param("github:work", id="a colon, the joining character"),
        pytest.param("github/work", id="a slash, the other joining character"),
        pytest.param("café", id="non-ASCII"),
        pytest.param("", id="empty"),
        pytest.param("g" * (SECRET_KEY_MAX_LENGTH + 1), id="one character over the maximum"),
        pytest.param(".github", id="leading punctuation"),
        pytest.param("github-", id="trailing punctuation"),
    ],
)
def test_a_key_outside_the_grammar_is_refused(key: str) -> None:
    """Each exclusion earns its place, and none of them is stylistic.

    ``:`` and ``/`` because the concrete implementation composes a backend
    coordinate out of an installation namespace, the scope and the key, and that
    composition must be injective — a component containing the joining character
    breaks it, and two names that collide on the backend are one secret silently
    overwriting another.

    **Uppercase is the subtler one.** At least one mainstream backend matches its
    target names case-insensitively, so ``github`` and ``GitHub`` would be one
    entry there and two elsewhere: a credential stored on Linux that cannot be
    found on Windows, or worse, that finds a different one.
    """
    with pytest.raises(ValidationError):
        SecretName(scope=SecretScope.PROVIDER, key=key)


def test_a_refused_key_is_never_quietly_normalised() -> None:
    """Refused, not case-folded or stripped (ADR-0096 §2's rule, applied).

    Normalising here would produce exactly the collision the grammar exists to
    prevent, silently, at the one layer that could still have reported it — and it
    would do so at the layer whose whole job is to keep two spellings of one name
    from becoming two entries on one platform and one on another.
    """
    with pytest.raises(ValidationError):
        SecretName(scope=SecretScope.PROVIDER, key="GitHub")
    with pytest.raises(ValidationError):
        SecretName(scope=SecretScope.PROVIDER, key="  github  ")


def test_two_names_are_equal_exactly_when_both_fields_are() -> None:
    """Which is what "the same entry" means (ADR-0125 §2)."""
    name = SecretName(scope=SecretScope.PROVIDER, key="github")

    assert name == SecretName(scope=SecretScope.PROVIDER, key="github")
    assert name != SecretName(scope=SecretScope.INTEGRATION, key="github")
    assert name != SecretName(scope=SecretScope.PROVIDER, key="github-work")
    assert hash(name) == hash(SecretName(scope=SecretScope.PROVIDER, key="github"))


def test_a_name_is_frozen() -> None:
    """It crosses a seam and is held past the call, so nothing rewrites it."""
    name = SecretName(scope=SecretScope.PROVIDER, key="github")

    with pytest.raises(ValidationError):
        name.key = "github-work"


def test_revalidating_a_forged_name_refuses_it() -> None:
    """The mechanism a seam's argument step relies on (ADR-0125 §4).

    ``model_construct`` is public, skips validation entirely, and yields an object
    that passes ``isinstance`` and every static check while carrying a key §2
    forbids. ``revalidate_instances="always"`` is what lets an implementation
    re-run the invariants over the object **as a whole**, in one call, before it
    has read any attribute of it — rather than dumping its fields or reading its
    ``scope`` for a backend prefix and so depending on invariants it had not
    checked.
    """
    forged = SecretName.model_construct(scope=SecretScope.PROVIDER, key="GitHub")

    with pytest.raises(ValidationError):
        SecretName.model_validate(forged)

    honest = SecretName(scope=SecretScope.PROVIDER, key="github")
    assert SecretName.model_validate(honest) == honest


# --- SecretValue: bounded, non-blank, encodable, and never normalised --------


def test_a_value_at_exactly_the_bound_constructs() -> None:
    """1024 UTF-8 bytes is admitted; the bound is inclusive (ADR-0125 §3)."""
    at_the_bound = "a" * SECRET_VALUE_MAX_BYTES

    assert secret_value(SecretStr(at_the_bound)).get_secret_value() == at_the_bound
    assert len(at_the_bound.encode("utf-8")) == SECRET_VALUE_MAX_BYTES


def test_a_multibyte_value_is_measured_in_bytes_and_not_in_characters() -> None:
    """The budget is a *storage* budget, which is the whole of §3's arithmetic.

    A backend's limit is bytes; measuring characters would admit a value four
    times over it, which stores on the developer's platform and fails on the
    owner's.
    """
    half_as_many_characters = "é" * (SECRET_VALUE_MAX_BYTES // 2)

    assert len(half_as_many_characters) == SECRET_VALUE_MAX_BYTES // 2
    assert secret_value(SecretStr(half_as_many_characters))

    with pytest.raises(ValueError, match="UTF-8 bytes"):
        secret_value(SecretStr(half_as_many_characters + "é"))


def test_a_value_one_byte_over_the_bound_is_refused() -> None:
    """Refused by this clause rather than discovered on the owner's machine."""
    with pytest.raises(ValueError, match="UTF-8 bytes"):
        secret_value(SecretStr("a" * (SECRET_VALUE_MAX_BYTES + 1)))


@pytest.mark.parametrize(
    "plaintext",
    [
        pytest.param("", id="empty"),
        pytest.param("   ", id="spaces"),
        pytest.param("\t\n", id="a tab and a newline"),
    ],
)
def test_a_blank_value_is_refused(plaintext: str) -> None:
    """A blank credential authenticates nothing and hides that it is missing."""
    with pytest.raises(ValueError, match="blank"):
        secret_value(SecretStr(plaintext))


def test_an_unpaired_surrogate_is_refused_with_a_value_error() -> None:
    r"""The case that survives every other check (ADR-0125 §3, ADR-0087 §2b).

    ``"\ud800"`` is non-blank, is one character, and has no byte length at all —
    measuring it *is* encoding it. So a budget check written as
    ``len(value.encode())`` raises ``UnicodeEncodeError`` rather than the
    ``ValueError`` this contract promises, and the ordering of the checks is what
    makes the promise true: encodability is decided before anything measures.
    """
    with pytest.raises(ValueError, match="UTF-8 encoding") as raised:
        secret_value(SecretStr("\ud800"))

    assert not isinstance(raised.value, UnicodeEncodeError)


@pytest.mark.parametrize(
    "plaintext",
    [
        pytest.param("  padded  ", id="leading and trailing whitespace"),
        pytest.param("line\nbreak\n", id="embedded and trailing newlines"),
        pytest.param("MiXeD-CaSe", id="mixed case"),
        pytest.param("éclair", id="a decomposed character NFC would compose"),
    ],
)
def test_a_value_is_not_normalised_between_construction_and_the_accessor(
    plaintext: str,
) -> None:
    """Two spellings of a secret are two different secrets (ADR-0125 §3).

    Stated because the corpus normalises for good reasons elsewhere — ADR-0121 §1
    casefolds and normalises where two spellings of a *name* should be one thing —
    and a credential is the exact inverse. The decomposed case is the one a
    well-meaning implementation reaches for: ``unicodedata.normalize("NFC", …)``
    changes the bytes while leaving the string looking identical, and the
    authentication failure it buys is one nobody can reproduce by inspection.
    """
    assert secret_value(SecretStr(plaintext)).get_secret_value() == plaintext
    assert _Carrier(value=SecretStr(plaintext)).value.get_secret_value() == plaintext


def test_the_decomposed_case_would_really_have_changed_under_normalisation() -> None:
    """A control for the case above, which is otherwise vacuous.

    If the chosen plaintext were already in NFC, "the store did not normalise it"
    and "the store normalised it and nothing changed" would be the same
    observation.
    """
    assert unicodedata.normalize("NFC", "éclair") != "éclair"


def test_the_annotated_alias_and_the_callable_refuse_the_same_values() -> None:
    """Both spellings are real, and neither may be the lenient one (§3).

    A model field annotated with the alias validates through pydantic; a hand-built
    value validates through the callable. If they disagreed, "a violation raises at
    construction" would be true of whichever path a reader happened to take.
    """
    for plaintext in ("", "a" * (SECRET_VALUE_MAX_BYTES + 1), "\ud800"):
        with pytest.raises(ValidationError):
            _Carrier(value=SecretStr(plaintext))
        with pytest.raises(ValueError, match="secret value"):
            secret_value(SecretStr(plaintext))


def test_a_directly_constructed_value_reaches_a_seam_unvalidated() -> None:
    """Which is why ADR-0125 §4 makes every method revalidate its arguments.

    :data:`SecretValue` is ``Annotated[SecretStr, …]`` and has no runtime identity
    distinct from ``SecretStr``: pydantic runs the validator when a model field
    carrying the annotation is validated, and constructing the origin directly
    satisfies every static check while the validator never runs. Pinned as a fact
    about the type rather than left implicit, because it is the whole reason the
    conformance suites carry a bare-``SecretStr`` refusal case at all.
    """
    bypassed: SecretValue = SecretStr("")

    assert bypassed.get_secret_value() == ""


# --- nothing renders, and no refusal discloses (ADR-0125 §3, §6) -------------


def test_a_value_redacts_itself_in_both_renderings() -> None:
    """``repr`` and ``str``, which is what makes a leak deliberate rather than easy.

    ``core/logging.py`` redacts by *key name*, so a plain ``str`` keeps ADR-0124
    §6's promise only for as long as every call site chooses a covered key. A type
    whose default rendering is ``**********`` inverts the default: a disclosure
    requires somebody to write ``get_secret_value``.
    """
    value = secret_value(SecretStr(PLAINTEXT))

    assert PLAINTEXT not in repr(value)
    assert PLAINTEXT not in str(value)
    assert value.get_secret_value() == PLAINTEXT


@pytest.mark.parametrize(
    "plaintext",
    [
        pytest.param(PLAINTEXT * 20, id="oversized"),
        pytest.param(f"{PLAINTEXT}\ud800", id="an unpaired surrogate"),
    ],
)
def test_a_refusal_discloses_no_derivation_of_the_value_it_refused(plaintext: str) -> None:
    """Including its length, which is the one a size check naturally reports (§6).

    §11 binds the redaction obligation to **every way this seam raises**, not to
    backend failures alone, and a refusal is the likelier leak of the two because
    the obvious message contains one: "secret length is 1025" hands over a
    derivation from the seam's own code rather than from a backend it was
    wrapping.

    Every derivation §6 names is checked, read off :class:`Disclosure` rather than
    listed again here — a second list beside the prohibition is how the two drift.
    A derivation that cannot be computed over an unencodable value is skipped,
    because a digest and a length of a value with no byte form do not exist.
    """
    with pytest.raises(ValueError, match="secret value") as raised:
        secret_value(SecretStr(plaintext))

    rendered = (str(raised.value), repr(raised.value), *map(str, raised.value.args))
    for disclosure in Disclosure:
        try:
            text = disclosure_of(disclosure, plaintext)
        except UnicodeEncodeError:
            continue
        for rendering in rendered:
            assert text not in rendering, f"{disclosure} disclosed in {rendering!r}"


def test_a_refused_key_may_be_echoed_because_a_name_is_not_a_secret() -> None:
    """The permission and the prohibition are one clause (ADR-0125 §2).

    Diagnosing "the keyring has no entry for this" requires saying which entry, so
    a name may be logged, carried in an error and shown to the owner. What makes
    that safe is the other half: a caller may never encode a secret value into a
    key, because the name is chosen by the code and not by the secret.
    """
    with pytest.raises(ValidationError, match="GitHub"):
        SecretName(scope=SecretScope.PROVIDER, key="GitHub")
