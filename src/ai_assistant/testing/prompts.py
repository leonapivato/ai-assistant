"""The shipped prompt templates, as a test hands them to the module that sends them.

The composition root reads each prompt's default and hands the module its template
(ADR-0334 §3:5); a test that builds such a module directly reads the same file the same
way here, so it runs the text the hub runs and keeps no copy of it. A test that needs
to tell one prompt's call from another's asks :func:`default_renderings` rather than
matching words, which no test asserts (§9:1).
"""

from __future__ import annotations

import itertools
from importlib.resources import files
from typing import TYPE_CHECKING

from ai_assistant.core.prompts import PromptDeclaration, PromptOrigin, PromptTemplate

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping


def default_prompt(declaration: PromptDeclaration) -> PromptTemplate:
    """The prompt's shipped default, read from beside the module that sends it (§3:1).

    Args:
        declaration: The prompt, as its module declares it.

    Returns:
        The default template, parsed against ``declaration``.
    """
    data = files(declaration.package).joinpath(declaration.filename).read_bytes()
    return PromptTemplate.parse(declaration, data, origin=PromptOrigin.DEFAULT)


def prompt_from(declaration: PromptDeclaration, text: str) -> PromptTemplate:
    """A template of the test's own, as an override of ``declaration`` would be parsed.

    Lets a test see which flags and values the code handed a template (§9:2) through a
    text that prints them, without reading the default's words.

    Args:
        declaration: The prompt the text stands in for.
        text: The template's text.

    Returns:
        The parsed template, with origin ``override``.
    """
    return PromptTemplate.parse(declaration, text.encode("utf-8"), origin=PromptOrigin.OVERRIDE)


def flag_combinations(declaration: PromptDeclaration) -> Iterator[dict[str, bool]]:
    """Every combination of the prompt's flags, in a fixed order (§4:4).

    Args:
        declaration: The prompt.

    Yields:
        One mapping of every declared flag to a value, per combination.
    """
    names = sorted(declaration.flags)
    for chosen in itertools.product((False, True), repeat=len(names)):
        yield dict(zip(names, chosen, strict=True))


def default_renderings(
    declaration: PromptDeclaration, values: Mapping[str, str] | None = None
) -> frozenset[str]:
    """Every instruction the prompt's default renders, one per combination of its flags.

    Args:
        declaration: The prompt.
        values: Its declared values, where it declares any.

    Returns:
        The rendered instructions.
    """
    template = default_prompt(declaration)
    return frozenset(
        template.render(flags=flags, values=values) for flags in flag_combinations(declaration)
    )
