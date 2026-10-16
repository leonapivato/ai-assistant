"""Which parts of a request the provider is asked to cache (#3077).

Every planning round re-sends the same standing instructions and tool schemas, and
every understanding call the same instructions: about 40% of what the hub sends a
model. Anthropic caches a request's prefix where the request marks it, and reads a
cached prefix back at a tenth of the input price; nothing is cached where nothing is
marked. So the two request paths in this package, :mod:`~ai_assistant.models.provider`
and :mod:`~ai_assistant.models.tool_calling`, both mark it here, and nothing else in
the request changes.

**What is marked.** Anthropic renders a request as tools, then the system prompt,
then the messages, and caches the prefix up to each marked block. Two marks are set:
after the last tool, and after the system prompt. Tools and instructions are what
repeat from one request to the next; the first mark keeps the tools cached where the
instructions vary (planning's do, a little, with what the round offers) and the
second caches both where neither does. The messages are not marked: each stage sends
one user turn rendered afresh per request, so a mark on it would be written, at a
quarter more than the plain input price, and never read. Anthropic's automatic
breakpoint (``anthropic_cache``) is that mark, and is not set for the same reason.

**Anthropic only, and model-agnostic for everything else** (ADR-0061). The marks are
pydantic-ai's Anthropic settings, given only where the request goes to pydantic-ai's
Anthropic model, wrapped or not; any other model, a fallback model included, is
given none and its request is as it was. A mark the model's own settings already set
is left to them, as a model's own thinking setting is.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING, Final, cast

from pydantic_ai.models.wrapper import WrapperModel

if TYPE_CHECKING:
    from collections.abc import Mapping

    from pydantic_ai import models
    from pydantic_ai.settings import ModelSettings

#: The module pydantic-ai's Anthropic model is defined in. It imports the vendor SDK,
#: so it is looked up rather than imported: until something has imported it, no
#: Anthropic model can exist, and a deployment that never uses one never loads it.
_ANTHROPIC_MODULE: Final = "pydantic_ai.models.anthropic"

#: The marks, as pydantic-ai's Anthropic settings: after the last tool and after the
#: system prompt, each at the provider's default lifetime (five minutes).
_MARKS: Final[Mapping[str, object]] = {
    "anthropic_cache_tool_definitions": True,
    "anthropic_cache_instructions": True,
}


def prompt_cache_settings(model: models.Model) -> ModelSettings:
    """The settings marking ``model``'s request's tools and instructions for caching.

    Args:
        model: The model the request goes to, as pydantic-ai resolved it.

    Returns:
        The marks, where ``model`` is pydantic-ai's Anthropic model or wraps one,
        less any its own settings already set; otherwise no settings at all.
    """
    inner = model
    while isinstance(inner, WrapperModel):
        inner = inner.wrapped
    if not _is_anthropic(inner):
        return cast("ModelSettings", {})
    configured: Mapping[str, object] = inner.settings or {}
    marks = {key: value for key, value in _MARKS.items() if key not in configured}
    # Anthropic's own settings keys, which ``ModelSettings`` does not declare.
    return cast("ModelSettings", marks)


def _is_anthropic(model: models.Model) -> bool:
    """Whether ``model`` is pydantic-ai's Anthropic model."""
    module = sys.modules.get(_ANTHROPIC_MODULE)
    return module is not None and isinstance(model, module.AnthropicModel)
