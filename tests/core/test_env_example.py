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
examples *parse*, and asserts nothing about what they parse to.

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

#: One commented assignment, as the file writes them: ``# ASSISTANT_NAME=value``.
#: Anchored to the line start so a name merely *mentioned* in the prose — the
#: header's "prefixed `ASSISTANT_`" — is not mistaken for a setting the file
#: offers. Unprefixed entries (``OPENAI_API_KEY`` and the other provider
#: credentials) are read by the provider SDKs rather than by ``Settings`` and are
#: outside what this module can check.
_ASSIGNMENT: Final = re.compile(r"^#\s*(ASSISTANT_[A-Z0-9_]+)=(.*)$")


def _assignments() -> list[tuple[str, str]]:
    """Every commented ``ASSISTANT_*`` assignment in the file, in file order."""
    return [
        (match.group(1), match.group(2))
        for line in _ENV_EXAMPLE.read_text(encoding="utf-8").splitlines()
        if (match := _ASSIGNMENT.match(line))
    ]


def _variables() -> set[str]:
    """The environment variable name of every field on :class:`Settings`."""
    return {f"ASSISTANT_{name.upper()}" for name in Settings.model_fields}


def test_the_example_file_offers_settings_to_set() -> None:
    """A guard on the two cases below, which a regex that stopped matching passes.

    Both of the real assertions are over a parsed set, and an empty set satisfies
    a subset check and a load alike. So the count is pinned loosely — not to a
    number, which would make every added setting a failing test, but to the fact
    that the parse found a substantial file rather than nothing.
    """
    assert len(_assignments()) > 10


def test_every_example_variable_is_a_real_settings_field() -> None:
    """A name here that no longer exists on ``Settings`` is a silent no-op.

    ``Settings.model_config`` sets ``env_prefix="ASSISTANT_"``, so the mapping is
    mechanical and the check is exact: uppercase the field name, prefix it, and
    the file may name nothing outside that set. Extra environment variables are
    simply ignored at load, which is what makes this failure silent and worth a
    test — the operator sets the variable, the feature stays off, and no error is
    produced at any point.
    """
    offered = {name for name, _ in _assignments()}

    assert offered <= _variables(), sorted(offered - _variables())


def test_the_example_file_names_each_variable_once() -> None:
    """Two assignments of one name would leave an operator with a silent winner.

    ``.env`` is last-wins, so a duplicate does not fail — it makes one of the two
    examples dead text, and which one is dead depends on file order rather than on
    anything a reader can see.
    """
    offered = [name for name, _ in _assignments()]

    assert sorted(offered) == sorted(set(offered))


def test_the_example_file_generates_a_loadable_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Uncommenting the whole file produces a ``.env`` that ``Settings`` accepts.

    This is the check PR #1275 ran by hand in a scratch directory and #1277 asked
    to be made repeatable. It is stronger than the name check and narrower than it
    looks: it asserts that every example is *well-formed for its field* and that
    the file's cross-field rules hold together — an interval with no path is
    refused at load, and the file arms several of those pairs at once — while
    asserting nothing about any value. A default that changes does not fail here;
    an example that stops being a legal duration, timezone, route or UUID does.

    It loads through the mechanism an operator actually uses rather than through a
    private constructor argument: ``model_config`` sets ``env_file=".env"``, a
    relative path resolved against the working directory, so writing the generated
    file into ``tmp_path`` and running there is the documented "copy to .env" step
    performed literally.

    The environment is cleared first because environment variables outrank
    ``env_file`` in pydantic-settings' source order, so an ambient ``ASSISTANT_*``
    — a developer's own shell, or CI — would otherwise be what the case actually
    loaded.
    """
    for variable in _variables():
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.chdir(tmp_path)
    baseline = Settings()
    assignments = _assignments()
    Path(".env").write_text(
        "".join(f"{name}={value}\n" for name, value in assignments), encoding="utf-8"
    )

    settings = Settings()

    # That construction raised nothing is half the claim; the other half is that
    # the file was *read*, which no exception can report — pydantic-settings
    # ignores a variable it does not recognise rather than objecting. So the two
    # loads are compared: something moved, and nothing moved that the file does
    # not name.
    offered = {name.removeprefix("ASSISTANT_").lower() for name, _ in assignments}
    moved = {
        field
        for field in Settings.model_fields
        if getattr(settings, field) != getattr(baseline, field)
    }
    assert moved, "the generated .env moved no setting, so it was not read at all"
    assert moved <= offered, sorted(moved - offered)
