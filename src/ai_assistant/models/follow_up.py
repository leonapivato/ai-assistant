"""The follow-up question: its prompt, and the seam that asks it of a planning round (ADR-0337 §6).

The **follow-up** is a second request about a model call that has completed: the
followed call's request as it was sent, its system message and its offered tools
included, then the followed call's response, then this prompt's template rendered as
one user message (§6:3). It asks after the answer, so it cannot change the answer.

**The prompt.** The template ships beside the module in ``models/`` that sends it on the
hub (§6:1), which is this one: the hub-side asker of ADR-0337 §8:5 is to live here.

**A planning round's follow-up** goes through :func:`follow_up_round`, the follow-up's
sibling of the completer's seam for the owner's replay tool (ADR-0335 §4:8), which
ADR-0337 §7:3 sends it through. Its request is the round's own, built exactly as
:class:`~ai_assistant.models.tool_calling.PydanticAIToolCallingCompleter` builds a round
with the record on, summarised thinking included, so the offered tools stay in it; then
the followed response whole, its thinking and the thinking's signatures included, so
that the provider accepts the request (§6:6); then one request closing each call the
response proposed, the reserved notes tool's included, with a result saying it was not
run because the request is for review only (§6:4), and holding the question last. It is
sent once to the one model it is named, which may not fall back to another, and it
returns the answer as text (§6:5): no call the answer proposes is run or returned. It
writes no entry, binds no activation and is on no Protocol, and no stage calls it
(ADR-0335 §4:9).

**A completion's follow-up needs no seam**: the provider's ``complete`` takes the
request, the reply as an assistant turn and the question as the last user turn.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from pydantic import ValidationError
from pydantic_ai.direct import model_request
from pydantic_ai.messages import (
    ModelMessagesTypeAdapter,
    ModelRequest,
    ModelResponse,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models import infer_model

from ai_assistant.core.errors import ModelError
from ai_assistant.core.prompts import PromptDeclaration
from ai_assistant.models.provider import _classify
from ai_assistant.models.tool_calling import (
    DEFAULT_THINKING,
    _falls_back,
    _round_request,
    _settings,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from pydantic_ai import models
    from pydantic_ai.settings import ThinkingLevel

    from ai_assistant.core.types import Message, OfferedTool

#: The follow-up's prompt (ADR-0337 §6:1), the ninth: it declares no flag and no value.
#:
#: **What the instruction must say**, which binds the default and every override alike
#: (ADR-0334 §7:1), and which a promotion's review reads it against (§7:3): that it asks
#: what the model had to guess, what it needed and was not given, and which rules or
#: instructions pulled against each other, and asks it to name for each the passage of
#: the instruction or of the data that it is about (ADR-0337 §6:2).
FOLLOW_UP_PROMPT: Final = PromptDeclaration(name="follow_up", package="ai_assistant.models")

#: The result closing each call a followed response proposed (ADR-0337 §6:4).
NOT_RUN: Final = "Not run: this request is for review only."


async def follow_up_round(  # noqa: PLR0913 — the round's request, its response and the question; keyword-only, the model and the thinking
    messages: Sequence[Message],
    tools: Sequence[OfferedTool],
    response: Mapping[str, object],
    question: str,
    *,
    model: models.Model | str,
    thinking: ThinkingLevel = DEFAULT_THINKING,
) -> str:
    """Ask the follow-up of a planning round that has completed (ADR-0337 §6:3-§6:6).

    Args:
        messages: The followed round's request as it was sent, oldest first, its system
            message the one it was sent with.
        tools: The capabilities it offered, as planning's given entry records them: the
            reserved notes tool is added here and may not be among them.
        response: The followed round's whole response, as pydantic-ai serialises it to
            JSON: the form planning's returned entry keeps it in.
        question: The ``follow_up`` template, rendered.
        model: The one model the follow-up goes to, which may not be a fallback model,
            wrapped or not.
        thinking: The thinking the request asks for, as the completer's own.

    Returns:
        The answer's text, its text parts joined; empty where it wrote none.

    Raises:
        ModelError: The bare class, before any model is contacted, where the round's
            request would be refused, ``response`` is not one model response, the
            question is blank, or ``model`` is a fallback model. A failure sending the
            request is narrowed as a round's is.
    """
    history, parameters = _round_request(messages, tools, caller="follow_up_round()")
    followed = _followed(response)
    if not question.strip():
        msg = "a follow-up asks a question"
        raise ModelError(msg)
    closing: list[ToolReturnPart | UserPromptPart] = [
        ToolReturnPart(tool_name=part.tool_name, content=NOT_RUN, tool_call_id=part.tool_call_id)
        for part in followed.parts
        if isinstance(part, ToolCallPart)
    ]
    closing.append(UserPromptPart(content=question))
    history = [*history, followed, ModelRequest(parts=closing)]
    try:
        chosen = infer_model(model)
    except Exception as exc:
        # As a round's: resolving a string model may fail, and is classified.
        raise _classify(exc) from exc
    if _falls_back(chosen):
        msg = "a follow-up goes to the one model it names, which a fallback model may not be"
        raise ModelError(msg)
    try:
        settings = _settings(thinking, chosen, summarised=True)
        answer = await model_request(
            chosen, history, model_settings=settings, model_request_parameters=parameters
        )
    except Exception as exc:
        # Broad on purpose, as a round's: `_classify` is the taxonomy (ADR-0063).
        raise _classify(exc) from exc
    return answer.text or ""


def _followed(response: Mapping[str, object]) -> ModelResponse:
    """The followed response, rebuilt whole from its JSON.

    Raises:
        ModelError: The bare class, if it is not one model response.
    """
    try:
        rebuilt = ModelMessagesTypeAdapter.validate_python([dict(response)])
    except ValidationError, TypeError, ValueError:
        rebuilt = []
    if len(rebuilt) != 1 or not isinstance(rebuilt[0], ModelResponse):
        msg = "the followed response is not one model response"
        raise ModelError(msg)
    return rebuilt[0]
