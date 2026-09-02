"""The offline tools' operator recipes, held to the identifiers they name (#1022).

The two offline console scripts — ``ai-assistant-reembed`` (ADR-0104 §5) and
``ai-assistant-measures`` (ADR-0120 §9) — carry their operating instructions in
prose: a module docstring, an ``argparse`` description, an epilog, and the docstring
on the function that reads the decisions each leaves to the operator. Between them
they tell an operator which environment variables configure the run and which flags
the run takes, and nothing asserted either.

A docstring is where a rename lands without a failure: the identifier moves, the
prose keeps naming the old one, and every check this project runs still passes. The
demonstration this rests on is a *false* claim about a parser that shipped green in
:mod:`ai_assistant.readers.calendar`'s own recipe and was caught only by a review
round; ``tests/readers/test_calendar_recipe.py`` is this file's counterpart there.

What is pinned is the mechanically checkable half — every ``ASSISTANT_*`` a recipe
names is a setting the configuration defines, and every flag a recipe names is one
its own parser accepts. Whether a sentence is *true* is not reachable this way and is
not attempted.
"""

from __future__ import annotations

import inspect
import re
from typing import TYPE_CHECKING, Final

import pytest

from ai_assistant.core.config import Settings
from ai_assistant.service import measures, reembed

if TYPE_CHECKING:
    from types import ModuleType

#: The environment prefix every setting on this deployment is read under.
PREFIX: Final = str(Settings.model_config["env_prefix"])

#: The recipe-carrying modules, by the console script each one is.
RECIPES: Final = {"ai-assistant-reembed": reembed, "ai-assistant-measures": measures}

#: Long options in prose. Bounded on the left so that an em-dash-joined word and a
#: ``--`` inside a longer token are not read as flags.
_FLAG = re.compile(r"(?<![\w-])--[a-z][a-z0-9-]+")


def _prose(module: ModuleType) -> str:
    """Every operating instruction the module states in words.

    The four places one can be: the module docstring, the ``argparse`` description
    and epilog the tool prints under ``--help``, and the docstrings of the functions
    defined here — which is where both tools explain what comes from configuration
    rather than from a flag.

    Args:
        module: The console script's module.

    Returns:
        All of it, joined, for a regular expression to read.
    """
    parts = [module.__doc__ or ""]
    parts += [
        getattr(module, name) for name in ("_DESCRIPTION", "_EPILOG") if hasattr(module, name)
    ]
    parts += [
        function.__doc__ or ""
        for _, function in inspect.getmembers(module, inspect.isfunction)
        if function.__module__ == module.__name__
    ]
    return "\n".join(parts)


def _usage(module: ModuleType, capsys: pytest.CaptureFixture[str]) -> str:
    """The tool's own usage line, flattened, as ``--help`` prints it.

    Read from the **usage** block rather than from the whole help text, which would
    be circular: the help text embeds the description this file is checking, so a
    flag named only in prose would match itself. The usage line is composed by
    ``argparse`` from the options actually registered, and it ends at the first blank
    line.

    Args:
        module: The console script's module.
        capsys: The capture fixture the help text is printed through.

    Returns:
        The usage block with its wrapping removed.
    """
    with pytest.raises(SystemExit):
        module._parse_args(["--help"])
    return " ".join(capsys.readouterr().out.split("\n\n", 1)[0].split())


@pytest.mark.parametrize("script", sorted(RECIPES))
def test_every_setting_a_recipe_names_is_one_the_configuration_defines(script: str) -> None:
    """A renamed field must not leave an operator exporting a variable nothing reads.

    An unknown ``ASSISTANT_*`` variable is not refused at load — it is simply not
    read — so a recipe naming a stale one points the operator at a run configured by
    something else entirely. Both tools take the data directory this way *on purpose*
    (ADR-0104 §5, ADR-0120 §9: a tool that could be pointed at a different store than
    the hub uses is a way to build the mismatch it exists to report on), which is
    what makes the variable's name part of the instruction rather than a detail.
    """
    named = set(re.findall(rf"{PREFIX}[A-Z0-9_]+", _prose(RECIPES[script])))
    defined = {f"{PREFIX}{field.upper()}" for field in Settings.model_fields}

    assert named, "each recipe names the configuration its run comes from"
    assert named <= defined, f"named by {script} and not defined: {sorted(named - defined)}"


def test_every_flag_a_recipe_names_is_one_its_own_parser_accepts(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A flag spelled in prose and not registered is an instruction that exits 2.

    Written across both tools in one case rather than parametrised per module,
    because only one of them names a flag in its prose today — ``ai-assistant-reembed``
    describes its two by behaviour and never by name — and a per-module case would
    report a green for the empty half. The assertion that the roster is non-empty is
    what keeps *this* file from doing the same.
    """
    named = {
        (script, flag)
        for script, module in RECIPES.items()
        for flag in _FLAG.findall(_prose(module))
    }
    assert named, "at least one recipe spells a flag; a version that spells none has lost it"

    for script, flag in sorted(named):
        assert f"{flag} " in f"{_usage(RECIPES[script], capsys)} ", (
            f"{script}'s prose names {flag}, which its parser does not register"
        )
