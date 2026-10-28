"""How a structured call is sent, and how its response is read (ADR-0354 §4, §5).

:meth:`~ai_assistant.models.provider.PydanticAIProvider.complete_structured` sends each
structured call as exactly one request through pydantic-ai's direct request API, as
:class:`~ai_assistant.models.tool_calling.PydanticAIToolCallingCompleter` sends a
round. It never uses pydantic-ai's ``Agent`` output retries and never sends a second
request to repair, re-ask or validate a reply (§4:1): any further completion is the
stage's to decide. This module holds the two halves of that request that are not the
provider's own: what is asked for, and how what comes back is read.

**The mode** (§4:2, §4:3) is resolved per request, for the model the request goes to:
**native**, the provider's own JSON-schema output, where pydantic-ai's profile for that
model says it supports JSON-schema output; otherwise **prompted**, the schema following
the instructions under :data:`PROMPTED_INSTRUCTION`, this module's one fixed sentence.
The schema is :func:`~ai_assistant.core.reply_shapes.reply_schema`'s, closed and
carrying no text, and is never sent as a tool for the model to call. How a vendor's own
schema dialect adapts it on the way out is pydantic-ai's, through the model's profile.

**A fallback model is refused** before any request (§4:4): nothing in this project
builds one, and its mode could not be known before it answered.

**What comes back** (§4:6, §5:2) is every response the provider returned: the reply is
its text parts joined in order, a thinking part being no part of it, and it is the
first of ``refused``, ``cut``, ``empty`` and ``invalid`` that applies, in that order,
or else the shape's value, read by :func:`~ai_assistant.core.reply_shapes.read_reply`.
A response carrying a call, where none was offered, is ``invalid``. The exchange beside
it holds what §5:3 names and nothing derived from the value. Nothing that came back is
raised (§2:5): text no record can hold, a lone surrogate code point, is recorded with
U+FFFD in its place, and the response is still read as it came.

**The thinking's summary** (ADR-0355 §3, §4) is asked for and kept only by a provider
built to keep it. Such a provider's request to a model :data:`THINKS_UNASKED` names,
whose own settings configure no thinking, carries Anthropic's
``{"type": "adaptive", "display": "summarized"}`` and differs in nothing else
(:func:`summary_settings`): on those models it asks only to see the thinking the model
already does. What comes back is the response's thinking parts' text, on the exchange
and never in the reply; a provider not built to keep it keeps none.
"""

from __future__ import annotations

import copy
import sys
from typing import TYPE_CHECKING, Final, cast

from pydantic import BaseModel
from pydantic_ai.messages import BaseToolCallPart, TextPart, ThinkingPart
from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.models.fallback import FallbackModel
from pydantic_ai.models.wrapper import WrapperModel
from pydantic_ai.output import OutputObjectDefinition

from ai_assistant.core.reply_shapes import read_reply, recordable
from ai_assistant.core.types import (
    ReplyExchange,
    ReplyFailure,
    ReplyMode,
    ReplyUsage,
    StructuredReply,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from pydantic_ai import models
    from pydantic_ai.messages import ModelResponse
    from pydantic_ai.settings import ModelSettings

#: The one fixed sentence a prompted request's schema follows (§4:2). The schema is
#: appended after it, on its own paragraph.
PROMPTED_INSTRUCTION: Final = (
    "Reply with one JSON object and nothing else, matching this JSON schema:"
)

#: The models Anthropic documents as thinking adaptively when a request carries no
#: ``thinking`` field, matched exactly against the name of the model a request goes to
#: (ADR-0355 §3:2). A name is added only by a change citing the vendor's statement that
#: the model does so: on any other model, asking to see the thinking would turn it on.
THINKS_UNASKED: Final = (
    "claude-opus-5-5",
    "claude-opus-5",
    "claude-sonnet-5-5",
    "claude-sonnet-5",
    "claude-haiku-5-5",
    "claude-fable-5-1",
    "claude-fable-5",
    "claude-mythos-5-1",
    "claude-mythos-5",
    "claude-mythos-preview",
)

#: Anthropic's thinking configuration a request keeping the summary carries (§3:1): the
#: adaptive thinking those models already do, its summary shown.
_SUMMARISED_ADAPTIVE: Final[Mapping[str, str]] = {"type": "adaptive", "display": "summarized"}

#: The settings keys, pydantic-ai's unified one and Anthropic's own, by which a model's
#: own settings configure its thinking. A model whose settings hold either, at any
#: value, is sent the request it would be sent anyway (§3:4).
_THINKING_SETTINGS: Final = frozenset({"thinking", "anthropic_thinking"})

#: The module pydantic-ai's Anthropic model is defined in, looked up rather than
#: imported, as :mod:`~ai_assistant.models.prompt_cache` looks it up: it imports the
#: vendor SDK, and until something has imported it no Anthropic model can exist.
_ANTHROPIC_MODULE: Final = "pydantic_ai.models.anthropic"

#: pydantic-ai's normalised finish reasons that end a response as a returned failure,
#: before its reply is read (§5:2).
_FINISHED_AS: Final[Mapping[str, ReplyFailure]] = {
    "content_filter": ReplyFailure.REFUSED,
    "length": ReplyFailure.CUT,
}


def falls_back(model: models.Model) -> bool:
    """Whether ``model``, under any wrappers, is a fallback model (§4:4)."""
    inner = model
    while isinstance(inner, WrapperModel):
        inner = inner.wrapped
    return isinstance(inner, FallbackModel)


def mode_for(model: models.Model) -> ReplyMode:
    """The mode a request to ``model`` is sent in (§4:2, §4:3).

    Args:
        model: The model the request goes to, as pydantic-ai resolved it.

    Returns:
        :attr:`ReplyMode.NATIVE` where pydantic-ai's profile for ``model`` says it
        supports JSON-schema output, :attr:`ReplyMode.PROMPTED` otherwise.
    """
    if model.profile.get("supports_json_schema_output", False):
        return ReplyMode.NATIVE
    return ReplyMode.PROMPTED


def summary_settings(model: models.Model) -> ModelSettings:
    """The settings asking ``model``'s request to show its thinking's summary (§3).

    Args:
        model: The model the request goes to, as pydantic-ai resolved it.

    Returns:
        Anthropic's ``{"type": "adaptive", "display": "summarized"}`` as the settings
        key ``anthropic_thinking``, where ``model`` is pydantic-ai's Anthropic model or
        wraps one, its name is one :data:`THINKS_UNASKED` names, and no layer's own
        settings configure thinking; otherwise no settings at all, so the request is
        the one it would be without them (§3:4).
    """
    layer = model
    while True:
        configured: Mapping[str, object] = layer.settings or {}
        if _THINKING_SETTINGS & configured.keys():
            return cast("ModelSettings", {})
        if not isinstance(layer, WrapperModel):
            break
        layer = layer.wrapped
    if not _is_anthropic(layer) or layer.model_name not in THINKS_UNASKED:
        return cast("ModelSettings", {})
    # Anthropic's own settings key, which ``ModelSettings`` does not declare.
    return cast("ModelSettings", {"anthropic_thinking": dict(_SUMMARISED_ADAPTIVE)})


def _is_anthropic(model: models.Model) -> bool:
    """Whether ``model`` is pydantic-ai's Anthropic model."""
    module = sys.modules.get(_ANTHROPIC_MODULE)
    return module is not None and isinstance(model, module.AnthropicModel)


def request_parameters(schema: Mapping[str, object], mode: ReplyMode) -> ModelRequestParameters:
    """The request parameters asking for ``schema`` in ``mode``, with no tool offered.

    Args:
        schema: The shape's schema, as :func:`~ai_assistant.core.reply_shapes.reply_schema`
            gave it.
        mode: The mode the request is sent in.

    Returns:
        Parameters offering no tool and admitting text output, carrying ``schema`` as
        the output object: as the provider's JSON-schema output in native mode, and
        under :data:`PROMPTED_INSTRUCTION` in prompted mode.
    """
    # Unnamed and undescribed, so nothing pydantic-ai writes beside the schema gives it
    # a title or a description (§3:2).
    wanted = OutputObjectDefinition(json_schema=copy.deepcopy(dict(schema)))
    if mode is ReplyMode.NATIVE:
        return ModelRequestParameters(
            output_mode="native", output_object=wanted, allow_text_output=True
        )
    return ModelRequestParameters(
        output_mode="prompted",
        output_object=wanted,
        prompted_output_template=PROMPTED_INSTRUCTION,
        allow_text_output=True,
    )


def structured_reply[T: BaseModel](  # noqa: PLR0913 — the response, its shape, and the four facts of the request it answers
    response: ModelResponse,
    shape: type[T],
    *,
    mode: ReplyMode,
    version: str,
    model: models.Model,
    thinking_summaries: bool,
) -> StructuredReply[T]:
    """Read ``response`` as ``shape``, or as the returned failure it is (§4:6, §5).

    Args:
        response: The provider's whole response.
        shape: The shape the reply is read as.
        mode: The mode the request was sent in.
        version: The shape's version (§3:3).
        model: The model the request went to, which names the answer where the response
            does not.
        thinking_summaries: Whether the provider keeps the thinking's summary: where
            it does, the exchange's ``thinking`` is the response's thinking parts' text
            (ADR-0355 §4:1); where it does not, it is ``None``.

    Returns:
        The shape's value or a returned failure, with the exchange beside it. Nothing
        is raised: every response that came back is returned (§2:5).
    """
    reply = "".join(part.content for part in response.parts if isinstance(part, TextPart))
    details: Mapping[str, object] = response.provider_details or {}
    exchange = ReplyExchange(
        reply=recordable(reply),
        model=recordable(answered_by(response, model)),
        mode=mode,
        finish_reason=_stated(response.finish_reason),
        refusal=_stated(details.get("refusal")),
        refusal_category=_stated(details.get("refusal_category")),
        usage=ReplyUsage(
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            cache_read_tokens=response.usage.cache_read_tokens,
            cache_write_tokens=response.usage.cache_write_tokens,
        ),
        shape=shape.__name__,
        shape_version=version,
        thinking=_summary(response) if thinking_summaries else None,
    )
    # Read off the response as it came, never off the record of it: a refusal is
    # refused and a reply read as the model wrote it, whatever the record had to change.
    read = _read(response, shape, reply)
    if isinstance(read, ReplyFailure):
        return StructuredReply(failure=read, exchange=exchange)
    return StructuredReply(value=read, exchange=exchange)


def _summary(response: ModelResponse) -> str | None:
    """The response's thinking parts' text, in order, joined by one blank line (§4:1).

    A part with no text, as one whose display was omitted or one that was redacted, is
    left out, and where no part has text there is no summary.
    """
    texts = [
        part.content for part in response.parts if isinstance(part, ThinkingPart) and part.content
    ]
    return recordable("\n\n".join(texts)) if texts else None


def answered_by(response: ModelResponse, model: models.Model) -> str:
    """The ``"provider:model"`` that answered, as ``response`` names it (§5:3).

    Each half is the response's own where it gives one, and the model the request went
    to otherwise, as a test double answering without a provider name does.
    """
    provider = response.provider_name or model.system
    name = response.model_name or model.model_name
    return f"{provider}:{name}"


def _read[T: BaseModel](response: ModelResponse, shape: type[T], reply: str) -> T | ReplyFailure:
    """The first of §5:2's failures that applies, in order, or the shape's value."""
    finished_as = _FINISHED_AS.get(response.finish_reason or "")
    if finished_as is not None:
        return finished_as
    read = read_reply(shape, reply)
    if read is ReplyFailure.EMPTY:
        return read
    if any(isinstance(part, BaseToolCallPart) for part in response.parts):
        # No tool was offered, so a call is no reply (§4:6).
        return ReplyFailure.INVALID
    return read


def _stated(value: object) -> str | None:
    """A response's statement, as text a record can hold, or ``None`` where none was given."""
    if value is None:
        return None
    return recordable(value if isinstance(value, str) else str(value))
