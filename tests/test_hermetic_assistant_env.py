"""The ambient environment reaches no test, and no test has to ask for that.

``Settings`` reads every field it was not given from the process environment and
from a ``.env`` beside the working directory, so a test asserting on a default is
asserting on whoever ran it (#1368). ``tests/conftest.py``'s
``hermetic_assistant_env`` closes both channels, and since #1058 / #1395 it is
**autouse**: the sweep is a property of the run, and the roster of modules that
had opted into it had fallen 45 modules behind.

**This module is the pin for the autouse half**, and it is written the way the
claim is: it names no fixture, carries no ``pytestmark``, and imports nothing from
``conftest``. If the guard stopped being autouse, every case below would fail —
which is the whole of what a module that merely *used* the fixture could not show.

**Its own ambient configuration is supplied, not inherited.** CI runs with a bare
environment, which is precisely the case in which a guard against the environment
cannot be observed to work — so the hostile machine is built here for this
module's duration, on both channels at once, exactly as
``tests/interfaces/test_cli_ambient_environment.py`` builds it for the CLI's. That
module is the end-to-end half of the same claim (an adapter's rendering does not
follow the shell); this one is the mechanism half.

**The ordering is pytest's rather than a convention.** The ambient configuration
is established by a *module*-scoped fixture and closed by the function-scoped
guard, and pytest instantiates higher-scoped fixtures first — which is the order
an ambient value genuinely has, in place before any test is set up.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Final

import pytest

from ai_assistant.core.config import Settings

if TYPE_CHECKING:
    from collections.abc import Iterator

#: A level that is valid (so it would load rather than be refused) and is not the
#: default, so an assertion on the default distinguishes the two.
_AMBIENT_LEVEL: Final = "ERROR"

#: The default the field carries in ``core/config.py``, restated here rather than
#: read off the model: reading it off ``Settings`` would make the assertion true by
#: construction whatever the environment did.
_DEFAULT_LEVEL: Final = "INFO"

#: A name under the prefix that is not a field of ``Settings`` at all. The sweep is
#: by prefix and not by the model's field names, and this is the difference: a
#: variable that no field reads today is read by the field somebody adds tomorrow,
#: which is the failure mode being fixed rather than a variant of it.
_AMBIENT_STRAY: Final = "ASSISTANT_NOT_A_FIELD_OF_SETTINGS"

#: Spelled lower case on purpose. pydantic-settings' loader is case-insensitive
#: (``tests/core/test_env_example.py`` pins that), so this reaches ``log_level``
#: exactly as the upper-case name does, and a sweep that matched case exactly would
#: leave it standing.
_AMBIENT_LOWER_CASE: Final = "assistant_log_level"


@pytest.fixture(scope="module", autouse=True)
def _ambient_configuration(tmp_path_factory: pytest.TempPathFactory) -> Iterator[None]:
    """Stand in for a developer's machine: exported variables and a ``.env`` in the clone.

    Both channels, because closing one would move the exposure rather than end it.
    Module-scoped so it is established before the function-scoped guard runs, and
    opened as its own context because ``monkeypatch`` is function-scoped and cannot
    be asked for here.
    """
    with pytest.MonkeyPatch.context() as ambient:
        ambient.setenv("ASSISTANT_LOG_LEVEL", _AMBIENT_LEVEL)
        ambient.setenv(_AMBIENT_STRAY, "1")
        ambient.setenv(_AMBIENT_LOWER_CASE, _AMBIENT_LEVEL)
        clone = tmp_path_factory.mktemp("ambient-clone")
        (clone / ".env").write_text(f"ASSISTANT_LOG_LEVEL={_AMBIENT_LEVEL}\n", encoding="utf-8")
        ambient.chdir(clone)
        yield


def test_a_test_that_asks_for_nothing_is_hermetic_anyway() -> None:
    """The autouse claim, on both channels and on the reading that follows from them.

    The channels are asserted alongside the reading rather than instead of it. Each
    is checkable on its own and neither is the point: the environment check would
    survive ``env_file`` being reopened, the file check would survive the sweep
    being dropped, and only the default reading says that a ``Settings`` this suite
    builds is the suite's. The ``.env`` is asserted *present* — the file is real and
    stays real; the claim is that it is not read.
    """
    assert "ASSISTANT_LOG_LEVEL" not in os.environ
    assert (Path.cwd() / ".env").exists()

    assert Settings().log_level == _DEFAULT_LEVEL


def test_the_sweep_is_by_prefix_rather_than_by_the_model_s_field_names() -> None:
    """A prefixed variable no field reads is swept too, and case does not save it.

    Both are properties of the sweep that a set of assertions about ``Settings``
    fields cannot see. The stray name matters because a value that is *invalid*
    rather than merely unexpected fails at construction, before the field a test
    names is ever reached — so a field-by-field guard is no guard at all. The
    lower-case name matters because the loader reads it, so leaving it standing
    would leave the exposure open under a spelling nobody would think to look for.
    """
    assert _AMBIENT_STRAY not in os.environ
    assert _AMBIENT_LOWER_CASE not in os.environ
    assert not [name for name in os.environ if name.upper().startswith("ASSISTANT_")]


def test_a_test_about_an_ambient_variable_supplies_it_itself(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Nothing opts out of the guard, and nothing needs to: it sweeps, it does not lock.

    This is the answer to #1395's objection that "a module that legitimately reads
    an ambient variable would break". The deletions go on the test's own
    ``monkeypatch`` stack, so a ``setenv`` after them wins and is undone with them,
    in order. A test whose subject is the environment therefore still has one —
    written down, which is the shape such a test wanted anyway, rather than
    whatever the shell happened to export.
    """
    monkeypatch.setenv("ASSISTANT_LOG_LEVEL", "WARNING")

    assert Settings().log_level == "WARNING"


def test_a_test_about_a_dotenv_file_supplies_that_itself_too(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The second channel reopens the same way, and on a file the test wrote.

    The guard neutralises ``env_file`` through ``model_config`` rather than by
    moving the working directory, so a test about dotenv loading points it at its
    own file instead of hoping the clone has one. That is strictly better than what
    it replaces: the file under test exists because the test wrote it.
    """
    dotenv = tmp_path / "supplied.env"
    dotenv.write_text("ASSISTANT_LOG_LEVEL=DEBUG\n", encoding="utf-8")
    monkeypatch.setitem(Settings.model_config, "env_file", str(dotenv))

    assert Settings().log_level == "DEBUG"


def test_no_module_asks_for_the_guard_by_name() -> None:
    """One mechanism, applied once — the guard against the roster growing back.

    Before #1058 / #1395 the sweep was a ``usefixtures`` mark each module added for
    itself, and the defect was not that the marks were wrong but that the set of
    them had to be maintained and had not been: 45 of the 57 modules constructing a
    ``Settings`` carried none. Autouse removes the roster; this keeps it removed.

    A re-added mark is harmless to *run* — pytest deduplicates it — which is exactly
    why it needs saying. It is harmful to read: it tells the next author that the
    modules carrying it are the protected ones and the rest are not, which is the
    belief that let three reader-settings modules sit exposed for as long as they
    did, and it is a per-module roster reappearing one line at a time.

    Scanned as text rather than through pytest's marker API because the claim is
    about what is written in the corpus. A mark applied at run time by some other
    route would still be covered by the paragraph above; it is not covered here,
    and a marker-API scan would not see a mark on a module this run did not
    collect.
    """
    needle = 'usefixtures("hermetic_assistant_env")'
    root = Path(__file__).resolve().parent
    asking = sorted(
        str(module.relative_to(root))
        for module in root.rglob("*.py")
        if module != Path(__file__).resolve() and needle in module.read_text(encoding="utf-8")
    )

    assert asking == [], (
        f"`hermetic_assistant_env` is autouse in tests/conftest.py, so these modules "
        f"ask for what they already have: {asking}. Delete the mark."
    )
