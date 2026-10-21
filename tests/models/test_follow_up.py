"""The follow-up's prompt: a ninth template of ADR-0334's form (ADR-0337 §6:1).

What the default says is not pinned here (ADR-0334 §9:1): the regression suite judges
what a reply does, and a promotion's review reads the wording.
"""

from __future__ import annotations

from ai_assistant.core.prompts import PromptOrigin
from ai_assistant.models.follow_up import FOLLOW_UP_PROMPT
from ai_assistant.testing import default_prompt


def test_it_declares_no_flag_and_no_value() -> None:
    """§6:1."""
    assert FOLLOW_UP_PROMPT.name == "follow_up"
    assert FOLLOW_UP_PROMPT.flags == frozenset()
    assert FOLLOW_UP_PROMPT.values == frozenset()


def test_its_default_ships_beside_the_module_and_renders() -> None:
    """§6:1: the default is a well-formed template in ``models/``, rendered under nothing."""
    template = default_prompt(FOLLOW_UP_PROMPT)

    assert FOLLOW_UP_PROMPT.package == "ai_assistant.models"
    assert template.origin is PromptOrigin.DEFAULT
    assert template.render(flags={}, values={}).strip()
