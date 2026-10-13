"""A :class:`~ai_assistant.core.protocols.ToolCallingCompleter` backed by pydantic-ai.

The planning round's sibling of :mod:`ai_assistant.models.provider` (ADR-0307 §10):
one model response in the provider's native tool-calling shape, through pydantic-ai's
direct request API, so the provider's own tool calling carries the calls and nothing
parses them out of reply text. Nothing here runs a call: pydantic-ai's direct request
returns the model's response and executes no tool.

**How the notes and the mark ride the native shape is this module's** (ADR-0307 §2:7).
They ride one reserved tool, :data:`ROUND_TOOL`, offered beside the capabilities. Its
description tells the model that it runs nothing; a call to it is read back into
:class:`~ai_assistant.core.types.RoundResponse`'s ``notes`` and ``another_round`` and
never returned as a call. Outside this module neither is a call (§2:2). A model may
call it more than once in one response: the notes are joined in order, and the mark is
set where any call sets it. An offered capability may not take its name.

**Each round is asked afresh** (§2:6). The request is the rendered ``Message`` history,
translated exactly as :class:`~ai_assistant.models.provider.PydanticAIProvider`
translates it, so a ``Role.TOOL`` turn is refused there and no earlier tool exchange is
ever replayed natively.

**Planning is given room to reason before it writes** (#2861). The request asks for the
provider's thinking through pydantic-ai's unified ``thinking`` setting, which a model or
provider without it ignores. The model reasons in thinking parts and writes the round's
message in text parts, so its working stays out of the words the user reads (§3:1). A
thinking part is none of a round's four parts (§2:1): it is dropped here, never returned,
recorded or replayed, and the next round is asked afresh without it (§2:6). A provider
may count thinking against the response's output ceiling, as Anthropic's does, so where
the model takes the setting the ceiling is widened by the thinking budget pydantic-ai
gives the level on a budget-based Anthropic model: the thinking never takes the room the
message had, and a budget-based model is never refused for a ceiling at or below it.

**Nothing here retries or re-routes**, as nothing in the streaming sibling does:
``RoutingProvider`` and ``RetryingProvider`` wrap ``ModelProvider`` completions, and a
round's resilience is the caller's to decide.
"""

from __future__ import annotations

import copy
from typing import TYPE_CHECKING, Any, Final

from pydantic import ValidationError
from pydantic_ai.direct import model_request
from pydantic_ai.messages import ToolCallPart
from pydantic_ai.models import ModelRequestParameters, infer_model
from pydantic_ai.profiles.anthropic import ANTHROPIC_THINKING_BUDGET_MAP
from pydantic_ai.settings import ModelSettings
from pydantic_ai.tools import ToolDefinition as NativeTool

from ai_assistant.core.errors import ModelError, ModelResponseError
from ai_assistant.core.types import OfferedTool, ProposedCall, Role, RoundResponse
from ai_assistant.models.provider import _classify, _to_model_messages

if TYPE_CHECKING:
    from collections.abc import Sequence

    from pydantic_ai import models
    from pydantic_ai.messages import ModelResponse
    from pydantic_ai.profiles import ModelProfile
    from pydantic_ai.settings import ThinkingLevel

    from ai_assistant.core.types import Message

#: The reserved tool the notes and the mark ride (ADR-0307 §2:7). No capability takes
#: this name.
ROUND_TOOL: Final = "planning_round"

#: How much a round may reason before it writes (#2861): on, at the provider's own
#: default effort. On a model with adaptive thinking that is the model's own judgement of
#: how much each round needs, and no effort setting narrows the message it writes.
DEFAULT_THINKING: Final[ThinkingLevel] = True

#: The output a round's message and calls had before it could think: pydantic-ai's
#: Anthropic default ceiling. Thinking is given its room on top of this, never out of it.
_MESSAGE_TOKENS: Final = 4096

_ROUND_TOOL_DESCRIPTION: Final = (
    "Not a capability: calling it runs nothing and goes to no one. Call it to keep "
    "episode notes on this activation, to ask for another planning round once every "
    "call of this round has finished, or both. Notes are free text for your own later "
    "rounds and later activations to read."
)

_ROUND_TOOL_SCHEMA: Final[dict[str, Any]] = {
    "type": "object",
    "properties": {
        "notes": {
            "type": "string",
            "description": "Episode notes to keep with this round. Optional.",
        },
        "another_round": {
            "type": "boolean",
            "description": ("True to ask for another round once this round's calls have finished."),
        },
    },
    "additionalProperties": False,
}


class PydanticAIToolCallingCompleter:
    """Native tool-calling client implemented on top of pydantic-ai.

    Structurally implements
    :class:`~ai_assistant.core.protocols.ToolCallingCompleter`. The default model may
    be a ``"provider:model"`` string (the production path) or a pydantic-ai
    :class:`~pydantic_ai.models.Model` instance (used by tests to inject a
    deterministic fake without network access), as
    :class:`~ai_assistant.models.provider.PydanticAIProvider`'s is.
    """

    def __init__(
        self, default_model: models.Model | str, *, thinking: ThinkingLevel = DEFAULT_THINKING
    ) -> None:
        """Initialise the completer.

        Construction stays offline: a string model is resolved, and its credential
        required, at the first round rather than at wiring time.

        Args:
            default_model: The model used when a call does not override it.
            thinking: The thinking every round asks for, as pydantic-ai's unified
                setting: ``True`` for the provider's default effort, an effort level,
                or ``False`` to ask for none. A model without thinking ignores it.
        """
        self._default_model = default_model
        self._thinking: ThinkingLevel = thinking

    async def respond(
        self,
        messages: Sequence[Message],
        tools: Sequence[OfferedTool],
        *,
        model: str | None = None,
    ) -> RoundResponse:
        """Produce one planning round's response to ``messages``, offering ``tools``.

        The request is built on the call, before the first await, from one observation
        of each argument (ADR-0065): the history is translated and the tools are
        rebuilt through validation, so a caller mutating either while the round is out
        cannot tear it.

        Args:
            messages: The round's rendered request, oldest first.
            tools: The capabilities offered for this round.
            model: Optional ``"provider:model"`` override.

        Returns:
            The round's response.

        Raises:
            ModelError: The bare class, before any model is contacted, if ``messages``
                is empty, ends on a ``Role.ASSISTANT`` turn or carries a ``Role.TOOL``
                turn, or if two tools share a name or one takes :data:`ROUND_TOOL`'s.
                A provider failure is narrowed to the most specific subclass, and a
                response that cannot be read as a round is a
                :class:`~ai_assistant.core.errors.ModelResponseError`.
        """
        if not messages:
            msg = "respond() requires at least one message"
            raise ModelError(msg)
        if messages[-1].role is Role.ASSISTANT:
            msg = "respond() requires a conversation awaiting a reply"
            raise ModelError(msg)
        history = _to_model_messages(messages)
        offered = [_native(OfferedTool.model_validate(tool.model_dump())) for tool in tools]
        names = [tool.name for tool in offered]
        if len(set(names)) != len(names):
            msg = "respond() requires distinct tool names"
            raise ModelError(msg)
        if ROUND_TOOL in names:
            msg = f"the tool name {ROUND_TOOL!r} is reserved for the round's notes and mark"
            raise ModelError(msg)
        parameters = ModelRequestParameters(
            function_tools=[*offered, _round_tool()], allow_text_output=True
        )
        try:
            chosen = infer_model(self._default_model if model is None else model)
            response = await model_request(
                chosen,
                history,
                model_settings=_settings(self._thinking, chosen.profile),
                model_request_parameters=parameters,
            )
        except Exception as exc:
            # Broad on purpose: `_classify` is the taxonomy, and its default for an
            # unrecognised failure is the conservative bare `ModelError` (ADR-0063).
            raise _classify(exc) from exc
        return _round(response)


def _settings(thinking: ThinkingLevel, profile: ModelProfile) -> ModelSettings:
    """A round's model settings: the thinking it asks for, and room for it.

    A budget-based Anthropic model is given the level's budget and refuses a ceiling
    that does not exceed it; an adaptive one spends its thinking out of the same
    ceiling. So where thinking is asked for and the model takes the setting, as
    pydantic-ai decides that from its profile, the ceiling is the message's own plus
    that budget. Anywhere else the ceiling is left as it was: a model without thinking
    keeps the request it had.
    """
    takes_it = profile.get("supports_thinking", False) or profile.get(
        "thinking_always_enabled", False
    )
    if thinking is False or not takes_it:
        return ModelSettings(thinking=thinking)
    return ModelSettings(
        thinking=thinking, max_tokens=_MESSAGE_TOKENS + ANTHROPIC_THINKING_BUDGET_MAP[thinking]
    )


def _native(tool: OfferedTool) -> NativeTool:
    """One offered capability as a pydantic-ai function tool, its schema thawed."""
    schema: dict[str, Any] = tool.model_dump()["parameters"]
    return NativeTool(name=tool.name, description=tool.description, parameters_json_schema=schema)


def _round_tool() -> NativeTool:
    """The reserved tool carrying the notes and the mark, built afresh per request."""
    return NativeTool(
        name=ROUND_TOOL,
        description=_ROUND_TOOL_DESCRIPTION,
        parameters_json_schema=copy.deepcopy(_ROUND_TOOL_SCHEMA),
    )


def _round(response: ModelResponse) -> RoundResponse:
    """Read a provider response as a round's four parts.

    The text is the text parts alone: a thinking part is none of the four, and is
    dropped.

    Raises:
        ModelResponseError: If a call's arguments are not a JSON object, the reserved
            tool's arguments are not of its shape, or the parts do not make a round.
    """
    calls: list[ProposedCall] = []
    notes: list[str] = []
    another_round = False
    try:
        for part in response.parts:
            if not isinstance(part, ToolCallPart):
                continue
            arguments = _arguments(part)
            if part.tool_name != ROUND_TOOL:
                calls.append(
                    ProposedCall(
                        call_id=part.tool_call_id, name=part.tool_name, arguments=arguments
                    )
                )
                continue
            written, marked = _round_parts(arguments)
            if written is not None and written.strip():
                notes.append(written)
            another_round = another_round or marked
        return RoundResponse(
            text=response.text or "",
            calls=tuple(calls),
            notes="\n\n".join(notes) if notes else None,
            another_round=another_round,
        )
    except (ValidationError, ValueError) as exc:
        msg = "the model's response could not be read as a planning round"
        raise ModelResponseError(msg) from exc


def _arguments(part: ToolCallPart) -> dict[str, Any]:
    """A call's arguments as a JSON object.

    Raises:
        ValueError: If they are not one.
    """
    try:
        return part.args_as_dict(raise_if_invalid=True)
    except AssertionError as exc:
        msg = "a call's arguments are not a JSON object"
        raise ValueError(msg) from exc


def _round_parts(arguments: dict[str, object]) -> tuple[str | None, bool]:
    """The notes and the mark one call of the reserved tool carries.

    Raises:
        ValueError: If either is present and not of its type, or anything else is.
    """
    if set(arguments) - {"notes", "another_round"}:
        msg = "the round's tool takes notes and another_round alone"
        raise ValueError(msg)
    notes = arguments.get("notes")
    mark = arguments.get("another_round", False)
    if (notes is not None and not isinstance(notes, str)) or not isinstance(mark, bool):
        msg = "the round's notes are text and its mark is a boolean"
        raise ValueError(msg)
    return notes, mark
