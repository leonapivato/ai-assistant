"""The follow-up question's prompt: what a model call had to guess (ADR-0337 §6).

The **follow-up** is a second request about a model call that has completed: the
followed call's request as it was sent, its system message and its offered tools
included, then the followed call's response, then this prompt's template rendered as
one user message (§6:3). It asks after the answer, so it cannot change the answer.

The template ships beside the module in ``models/`` that sends it on the hub (§6:1),
which is this one: the hub-side asker of ADR-0337 §8:5 is to live here. Until it does,
nothing in the package sends the follow-up; the owner's replay tool sends it from the
default it reads through this declaration (§7:1).
"""

from __future__ import annotations

from typing import Final

from ai_assistant.core.prompts import PromptDeclaration

#: The follow-up's prompt (ADR-0337 §6:1), the ninth: it declares no flag and no value.
#:
#: **What the instruction must say**, which binds the default and every override alike
#: (ADR-0334 §7:1), and which a promotion's review reads it against (§7:3): that it asks
#: what the model had to guess, what it needed and was not given, and which rules or
#: instructions pulled against each other, and asks it to name for each the passage of
#: the instruction or of the data that it is about (ADR-0337 §6:2).
FOLLOW_UP_PROMPT: Final = PromptDeclaration(name="follow_up", package="ai_assistant.models")
