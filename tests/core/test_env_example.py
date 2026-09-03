"""`.env.example` names real settings, and the file it describes actually loads.

The subject here is the repository-root file rather than :class:`Settings`, which
is why it sits in its own module instead of inside ``test_config.py``: nothing in
it is about a bound or a validator, and every case reads a file that is not under
``src/``. Issue #1277 left the placement to whoever took it.

**What is load-bearing is the names.** An operator copies ``ASSISTANT_DATA_DIR``
verbatim out of this file, so a field renamed or removed on :class:`Settings`
leaves the file naming a variable that does nothing — set it, nothing happens,
and nothing anywhere says so. That is the drift batch #1273 was opened to stop
re-arming, and it is the one failure a test can catch cheaply.

**What is deliberately not tested is the converse and the values.** The file's own
header states its inclusion rule: it lists the settings that *arm* something plus
the few that say what a deployment is, and it explicitly does not copy the rest,
because "every other setting — every bound, cap, timeout, retention and sweep
cadence — has a working default and carries its own description on its `Settings`
field". A test asserting every field appears would fail on the next new bound and
push the file back toward being a drifting copy of ``config.py``, which is the
shape the rule exists to prevent. The values are likewise disclaimed in the header
as "examples of the *form*, not a record of the defaults", so pinning one would
re-arm the staleness the file disclaims. The load case below asserts that the
examples *parse* and *arrive*, and asserts nothing about what they parse to.

Refs #1277, #1273, #1021.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING, Final

from ai_assistant.core.config import Settings

if TYPE_CHECKING:
    import pytest

#: The file under test, resolved from this module rather than from the working
#: directory — a test that only passes when pytest is invoked from the repository
#: root is a test that silently stops running.
_ENV_EXAMPLE: Final = Path(__file__).resolve().parents[2] / ".env.example"

#: ``Settings.model_config``'s ``env_prefix``, in the case ``config.py`` writes it
#: and the file uses — which is **not** the only case the loader accepts.
_PREFIX: Final = "ASSISTANT_"

#: One commented assignment, as the file writes them: ``# ASSISTANT_NAME=value``.
#:
#: Anchored to the line start so a name merely *mentioned* in the prose — the
#: header's "prefixed `ASSISTANT_`" — is not mistaken for a setting the file
#: offers. Unprefixed entries (``OPENAI_API_KEY`` and the other provider
#: credentials) are read by the provider SDKs rather than by ``Settings`` and are
#: outside what this module can check.
#:
#: **Case-insensitive on purpose, though every line in the file today is upper
#: case.** ``SettingsConfigDict`` leaves ``case_sensitive`` at its ``False``
#: default, so ``assistant_log_level`` is a live assignment for an operator in
#: exactly the way ``ASSISTANT_LOG_LEVEL`` is. A parser that only saw upper case
#: would let a lower-case line into the file unchecked — unbound to any field, and
#: invisible to the uniqueness case below, which is the one place where the two
#: cases genuinely collide.
_ASSIGNMENT: Final = re.compile(rf"^#\s*({_PREFIX}[A-Z0-9_]+)=(.*)$", re.IGNORECASE)


def _assignments() -> list[tuple[str, str]]:
    """Every commented ``ASSISTANT_*`` assignment, verbatim and in file order.

    The name is returned **as written** rather than normalised, because the load
    case has to write back exactly the text an operator would uncomment. Every
    case that compares names canonicalises for itself.
    """
    return [
        (match.group(1), match.group(2))
        for line in _ENV_EXAMPLE.read_text(encoding="utf-8").splitlines()
        if (match := _ASSIGNMENT.match(line))
    ]


def _fields() -> list[str]:
    """The ``Settings`` field each assignment names, canonicalised, in file order."""
    return [name.upper().removeprefix(_PREFIX).lower() for name, _ in _assignments()]


def _variables() -> set[str]:
    """The environment variable name of every field on :class:`Settings`."""
    return {f"{_PREFIX}{name.upper()}" for name in Settings.model_fields}


def test_the_example_file_offers_settings_to_set() -> None:
    """A guard on the cases below, which a regex that stopped matching passes.

    Every real assertion here is over a parsed set, and an empty set satisfies a
    subset check and a load alike. So the count is pinned loosely — not to a
    number, which would make every added setting a failing test, but to the fact
    that the parse found a substantial file rather than nothing.
    """
    assert len(_assignments()) > 10


def test_every_example_variable_is_a_real_settings_field() -> None:
    """A name here that no longer exists on ``Settings`` is a silent no-op.

    ``Settings.model_config`` sets ``env_prefix="ASSISTANT_"``, so the mapping is
    mechanical and the check is exact: uppercase the field name, prefix it, and
    the file may name nothing outside that set. Extra environment variables are
    simply ignored at load (``extra="ignore"``), which is what makes this failure
    silent and worth a test — the operator sets the variable, the feature stays
    off, and no error is produced at any point.
    """
    offered = {name.upper() for name, _ in _assignments()}

    assert offered <= _variables(), sorted(offered - _variables())


def test_the_example_file_names_each_setting_once() -> None:
    """Two assignments of one setting would leave an operator a silent winner.

    ``.env`` is last-wins, so a duplicate does not fail — it makes one of the two
    examples dead text, and which one is dead depends on file order rather than on
    anything a reader can see. Compared **after** canonicalisation, because the
    loader is case-insensitive: ``ASSISTANT_LOG_LEVEL`` and ``assistant_log_level``
    are one setting assigned twice, and that is the duplicate a reader is least
    likely to spot unaided.
    """
    named = _fields()

    assert sorted(named) == sorted(set(named))


def test_the_example_file_generates_a_loadable_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Uncommenting the whole file produces a ``.env`` that arms what it advertises.

    This is the check PR #1275 ran by hand in a scratch directory and #1277 asked
    to be made repeatable. It is stronger than the name check and narrower than it
    looks: it asserts that every example is *well-formed for its field*, that the
    file's cross-field rules hold together — an interval with no path is refused at
    load, and the file arms several of those pairs at once — and that every
    advertised variable actually **reaches** its setting, while asserting nothing
    about any value. A default that changes does not fail here; an example that
    stops being a legal duration, timezone, route or UUID does, and so does a
    variable that stops being the name the loader looks for.

    Arrival is read off ``model_fields_set``, which reports the fields that came in
    as *input* rather than from a default. That is what makes the check exact where
    a value comparison cannot be: ten of these examples are equal to their field's
    default, so a setting silently ignored — a field that grew a validation alias,
    say, while keeping its name and its line here — would be indistinguishable from
    one that loaded. The relation is ``<=`` rather than equality because a model
    validator may set further fields that no variable named.

    It loads through the mechanism an operator actually uses rather than through a
    private constructor argument: ``model_config`` sets ``env_file=".env"``, a
    relative path resolved against the working directory, so writing the generated
    file into ``tmp_path`` and running there is the documented "copy to .env" step
    performed literally.

    **This is the one case in the corpus that wants the dotenv channel open**, and
    it says so in one line. ``tests/conftest.py``'s ``hermetic_assistant_env`` is
    autouse and closes both channels a ``Settings`` reads ambient configuration
    through, ``env_file`` included (#1058, #1395) — so a case whose subject *is*
    ``env_file`` re-selects it, on the same ``monkeypatch`` stack and therefore
    only for itself. That is the shape the guard is built for: it sweeps rather
    than locks, and a test about an ambient channel supplies the value it reads
    instead of inheriting one. What it may not do is reach back to the literal
    ``".env"`` the model ships and hope the working directory is bare; the name is
    written here because the file this case loads is the one it just wrote, three
    lines down, in a directory of its own.

    The ambient environment needs no clearing here, and the sweep this case used to
    open with is gone with the roster it belonged to. It mattered because
    environment variables outrank ``env_file`` in pydantic-settings' source order,
    so an ambient ``ASSISTANT_*`` — a developer's own shell — would otherwise be
    what the case actually loaded; the guard does that for every test now, by
    prefix and case-insensitively, which is what this case did for itself.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.setitem(Settings.model_config, "env_file", ".env")
    Path(".env").write_text(
        "".join(f"{name}={value}\n" for name, value in _assignments()), encoding="utf-8"
    )

    settings = Settings()

    advertised = set(_fields())
    assert advertised <= settings.model_fields_set, sorted(advertised - settings.model_fields_set)
