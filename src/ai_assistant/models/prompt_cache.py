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
second caches both where neither does. Where a stage sends one user turn rendered afresh
per request, the messages are not marked: a mark on it would be written, at a quarter
more than the plain input price, and never read. Anthropic's automatic breakpoint
(``anthropic_cache``) is that mark, and is not set for the same reason. A planning
round's exchange only grows, so its newest report is marked
(:func:`marks_the_newest_report`).

**Anthropic only, and model-agnostic for everything else** (ADR-0061). The marks are
pydantic-ai's Anthropic settings, given only where the request goes to pydantic-ai's
Anthropic model, wrapped or not; any other model, a fallback model included, is
given none and its request is as it was.

**A model whose own settings configure caching keeps them, and is given no marks.**
Its settings are left to it as its own thinking setting is, and they are left whole
rather than filled in: Anthropic refuses a request whose cache lifetimes shorten and
lengthen again along the prefix (a one-hour entry may not follow a five-minute one),
so a five-minute mark added beside a one-hour one the model set could turn a request
it would have accepted into one it refuses.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING, Final, cast

from pydantic_ai.models.fallback import FallbackModel
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

#: Every pydantic-ai Anthropic setting that places a cache mark. A model whose own
#: settings set any of them is given no marks.
_CACHE_SETTINGS: Final = frozenset({*_MARKS, "anthropic_cache_messages", "anthropic_cache"})


def prompt_cache_settings(model: models.Model) -> ModelSettings:
    """The settings marking ``model``'s request's tools and instructions for caching.

    Args:
        model: The model the request goes to, as pydantic-ai resolved it.

    Returns:
        The marks, where ``model`` is pydantic-ai's Anthropic model or wraps one and
        its own settings configure no caching; otherwise no settings at all.
    """
    inner = model
    while isinstance(inner, WrapperModel):
        inner = inner.wrapped
    if not _is_anthropic(inner):
        return cast("ModelSettings", {})
    configured: Mapping[str, object] = inner.settings or {}
    if _CACHE_SETTINGS & configured.keys():
        return cast("ModelSettings", {})
    # Anthropic's own settings keys, which ``ModelSettings`` does not declare.
    return cast("ModelSettings", dict(_MARKS))


def marks_the_newest_report(model: models.Model) -> bool:
    """Whether a planning round to ``model`` ends its newest report on a cache point.

    A planning work's exchange is appended to and never re-rendered (ADR-0356 §5:2), so
    the request up to its newest report is the prefix of the next round's: a point there
    is written once and read back on the next round. It is pydantic-ai's
    model-agnostic :class:`~pydantic_ai.messages.CachePoint`, which a model that caches
    nothing drops. A model whose own settings configure caching is given none, for the
    reason the marks above are not (a five-minute point before its own one-hour mark
    would be refused), and so is a fallback model, which keeps the request it had.

    Args:
        model: The model the request goes to, as pydantic-ai resolved it.

    Returns:
        ``True`` where the point is set.
    """
    inner = model
    while isinstance(inner, WrapperModel):
        inner = inner.wrapped
    if isinstance(inner, FallbackModel):
        return False
    configured: Mapping[str, object] = inner.settings or {}
    return not _CACHE_SETTINGS & configured.keys()


def _is_anthropic(model: models.Model) -> bool:
    """Whether ``model`` is pydantic-ai's Anthropic model."""
    module = sys.modules.get(_ANTHROPIC_MODULE)
    return module is not None and isinstance(model, module.AnthropicModel)
