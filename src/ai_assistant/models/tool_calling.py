"""A :class:`~ai_assistant.core.protocols.ToolCallingCompleter` backed by pydantic-ai.

The planning round's sibling of :mod:`ai_assistant.models.provider` (ADR-0307 §10):
one model response in the provider's native tool-calling shape, through pydantic-ai's
direct request API, so the provider's own tool calling carries the calls and nothing
parses them out of reply text. Nothing here runs a call: pydantic-ai's direct request
returns the model's response and executes no tool.

**How the notes ride the native shape is this module's** (ADR-0315 §3:3). They ride one
reserved tool, :data:`ROUND_TOOL`, offered beside the capabilities. Its description tells
the model that it runs nothing; a call to it is read back into
:class:`~ai_assistant.core.types.RoundResponse`'s ``notes`` and never returned as a call.
Outside this module the notes are not a call (§3:2). A model may call it more than once
in one response, and the notes are joined in order. Nothing it carries asks for a round:
the controller's rule alone decides whether one runs (§2, §3:4). An offered capability
may not take its name.

**The round's naming of the calls its message asks about rides the same tool**
(ADR-0321 §2:3, which leaves the native shape to this module as ADR-0315 §3:3 does). It
is the tool's ``asks``, an array of strings, read back into ``RoundResponse.asks``: each
name once, in the order the model first gave it across every call of the tool, and a
blank name dropped as blank notes are. This module reads nothing of a name; what each
refers to is planning's, which tells the model what to give.

**Each round is asked afresh** (§2:6). The request is the rendered ``Message`` history,
translated exactly as :class:`~ai_assistant.models.provider.PydanticAIProvider`
translates it, so a ``Role.TOOL`` turn is refused there and no earlier tool exchange is
ever replayed natively.

**Planning is given room to reason before it writes** (#2861). The request asks for the
provider's thinking through pydantic-ai's unified ``thinking`` setting, which a model or
provider without it ignores. The model reasons in thinking parts and writes the round's
message in text parts, so its working stays out of the words the user reads (§3:1). A
thinking part is none of a round's three parts (ADR-0315 §3:1): it is dropped here, never returned,
recorded or replayed, and the next round is asked afresh without it (§2:6). A provider
may count thinking against the response's output ceiling, as Anthropic's does, so where
the model takes the setting the ceiling is widened by the thinking budget pydantic-ai
gives the level on a budget-based Anthropic model, or by the budget the model's own
settings give it: the thinking never takes the room the message had, and a budget-based
model is never refused for a ceiling at or below its budget. A response cut at its
ceiling is not a round: its message may stop mid-sentence and whatever followed the cut
is lost, so it is refused as unreadable rather than returned.

**The diagnostic record keeps the thinking** (ADR-0314 §5), and nothing else does.
Where the composition root hands the completer a
:class:`~ai_assistant.core.protocols.DiagnosticSink` — the record is on — a round on a
model with Anthropic's adaptive thinking asks for the thinking's summarised text, which
that thinking otherwise omits, and the completer writes planning's returned entry from
the provider's whole response, every part in order, thinking included, whether or not
it reads as a round, before it returns or raises. Beside the response it writes every
tool the request offered, :data:`ROUND_TOOL` and its description included (#2894):
planning's module writes the given entry with the capabilities it offers, and the
reserved tool is added here, so this is the one place the record can show the whole
list the provider received. Each tool's parameters are recorded as the chosen model's
request preparation sent them (#2910), since a provider's schema transformer may rewrite
them (OpenAI's adds ``additionalProperties: false``); where that cannot be computed they
are recorded as the round built them, and the entry says so. The entry is written for the
activation :mod:`ai_assistant.core.diagnostics` carries, and nothing is written where
none is bound. The thinking still reaches nothing else: :class:`RoundResponse`, the
episode and the next round never carry it (§5:3). Where the record is off, the request
is as it is without this.

**Nothing here retries or re-routes**, as nothing in the streaming sibling does:
``RoutingProvider`` and ``RetryingProvider`` wrap ``ModelProvider`` completions, and a
round's resilience is the caller's to decide.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final, cast

from pydantic import ValidationError
from pydantic_ai.direct import model_request
from pydantic_ai.messages import ModelMessagesTypeAdapter, ToolCallPart
from pydantic_ai.models import ModelRequestParameters, infer_model
from pydantic_ai.models.fallback import FallbackModel
from pydantic_ai.models.instrumented import InstrumentedModel
from pydantic_ai.models.wrapper import WrapperModel
from pydantic_ai.profiles.anthropic import ANTHROPIC_THINKING_BUDGET_MAP
from pydantic_ai.settings import ModelSettings
from pydantic_ai.tools import ToolDefinition as NativeTool

from ai_assistant.core.diagnostics import failure_body, write_diagnostic
from ai_assistant.core.errors import ModelError, ModelResponseError
from ai_assistant.core.types import (
    DiagnosticKind,
    DiagnosticSource,
    OfferedTool,
    ProposedCall,
    Role,
    RoundResponse,
)
from ai_assistant.models.provider import _classify, _to_model_messages

if TYPE_CHECKING:
    from collections.abc import Sequence

    from pydantic_ai import models
    from pydantic_ai.messages import ModelResponse
    from pydantic_ai.settings import ThinkingLevel

    from ai_assistant.core.protocols import DiagnosticSink
    from ai_assistant.core.types import Message

#: The reserved tool the notes ride (ADR-0315 §3:3). No capability takes
#: this name.
ROUND_TOOL: Final = "planning_round"

#: How much a round may reason before it writes (#2861): on, at the provider's own
#: default effort. On a model with adaptive thinking that is the model's own judgement of
#: how much each round needs, and no effort setting narrows the message it writes.
DEFAULT_THINKING: Final[ThinkingLevel] = True

#: How a round asks Anthropic's adaptive thinking for its text where the diagnostic record
#: keeps it (ADR-0314 §5:1): adaptive thinking omits the text unless the request asks for
#: the summarised display.
_SUMMARISED_ADAPTIVE: Final[Mapping[str, str]] = {"type": "adaptive", "display": "summarized"}

#: The returned entry's key saying its ``offered_tools`` are as the round built them, not
#: as the model's request preparation sent them, and why (#2910). It is present only
#: where the tools as prepared could not be computed.
_UNPREPARED: Final = "offered_tools_unprepared"

#: The output a round's message and calls had before it could think: pydantic-ai's
#: Anthropic default ceiling. Thinking is given its room on top of this, never out of it.
_MESSAGE_TOKENS: Final = 4096

_ROUND_TOOL_DESCRIPTION: Final = (
    "Not a capability: calling it runs nothing and goes to no one. Call it to keep "
    "episode notes on this activation: free text for your own later rounds and later "
    "activations to read; and to name, in asks, each call that needs the user that this "
    "round's message asks them about."
)

_ROUND_TOOL_SCHEMA: Final[dict[str, Any]] = {
    "type": "object",
    "properties": {
        "notes": {
            "type": "string",
            "description": "Episode notes to keep with this round.",
        },
        "asks": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "Each call that needs the user that this round's message asks them "
                "about, named as your instructions say."
            ),
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
        self,
        default_model: models.Model | str,
        *,
        thinking: ThinkingLevel = DEFAULT_THINKING,
        diagnostics: DiagnosticSink | None = None,
    ) -> None:
        """Initialise the completer.

        Construction stays offline: a string model is resolved, and its credential
        required, at the first round rather than at wiring time.

        Args:
            default_model: The model used when a call does not override it.
            thinking: The thinking every round asks for, as pydantic-ai's unified
                setting: ``True`` for the provider's default effort, an effort level,
                or ``False`` to ask for none. A model without thinking ignores it.
            diagnostics: The diagnostic record's write seam, where the record is on
                (ADR-0314 §5:1); ``None`` otherwise, and then the request and the
                round are as they are without it.
        """
        self._default_model = default_model
        self._thinking: ThinkingLevel = thinking
        self._diagnostics = diagnostics

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
                response that cannot be read as a round, or was cut at its output
                ceiling, is a :class:`~ai_assistant.core.errors.ModelResponseError`.
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
            msg = f"the tool name {ROUND_TOOL!r} is reserved for the round's notes"
            raise ModelError(msg)
        sent = [*offered, _round_tool()]
        parameters = ModelRequestParameters(function_tools=sent, allow_text_output=True)
        try:
            chosen = infer_model(self._default_model if model is None else model)
            settings = _settings(self._thinking, chosen, summarised=self._diagnostics is not None)
            # Where the record is on, the tools as prepared are taken here, with no await
            # between this and the request preparing itself (#2910). `_offered` never
            # raises.
            offered_record = (
                _offered(_Request(model=chosen, settings=settings, parameters=parameters))
                if self._diagnostics is not None
                else None
            )
            response = await model_request(
                chosen, history, model_settings=settings, model_request_parameters=parameters
            )
        except Exception as exc:
            # Broad on purpose: `_classify` is the taxonomy, and its default for an
            # unrecognised failure is the conservative bare `ModelError` (ADR-0063).
            raise _classify(exc) from exc
        try:
            read = _round(response)
        except ModelResponseError as exc:
            await self._returned(offered_record, response, exc)
            raise
        await self._returned(offered_record, response, None)
        return read

    async def _returned(
        self,
        offered: _Offered | None,
        response: ModelResponse,
        failure: ModelResponseError | None,
    ) -> None:
        """Write planning's returned entry from the provider's whole response (§5:2).

        Every part in order, thinking included, as pydantic-ai serialises the response;
        every tool the request offered, in the order it offered them, the reserved one
        included (#2894), each as the chosen model's request preparation gave it to the
        provider (#2910); and where the response did not read as a round, why not.
        Where the tools as prepared cannot be computed they are kept as the round built
        them, and :data:`_UNPREPARED` says why.

        Args:
            offered: The tools as the record keeps them, taken before the request was
                sent, or ``None`` where the record is off and nothing is written.
            response: The provider's whole response.
            failure: Why the response did not read as a round, or ``None``.
        """
        if offered is None:
            # Taken wherever a sink is: none is, so the record is off.
            return
        tools, unprepared = offered

        def body() -> dict[str, object]:
            returned: dict[str, object] = {
                "offered_tools": tools,
                "response": ModelMessagesTypeAdapter.dump_python([response], mode="json")[0],
                "read_as_round": failure is None,
            }
            if unprepared is not None:
                returned[_UNPREPARED] = unprepared
            if failure is not None:
                returned["failure"] = failure_body(failure)
            return returned

        await write_diagnostic(
            self._diagnostics, DiagnosticSource.PLANNING, DiagnosticKind.RETURNED, body
        )


def _settings(
    thinking: ThinkingLevel, model: models.Model, *, summarised: bool = False
) -> ModelSettings | None:
    """A round's model settings: the thinking it asks for, and room for it.

    A budget-based Anthropic model is given a budget and refuses a ceiling that does
    not exceed it; an adaptive one spends its thinking out of the same ceiling. So where
    thinking is asked for and the model takes the setting, as pydantic-ai decides that
    from its profile, the ceiling is the message's own plus the budget in effect: the
    one the model's own settings give Anthropic's thinking, which pydantic-ai lets take
    precedence, or else the one the level maps to. A larger ceiling the model's own
    settings already allow is kept. Anywhere else the ceiling is left as it was: a model
    without thinking keeps the request it had.

    A :class:`~pydantic_ai.models.fallback.FallbackModel`, wrapped or not, keeps the
    request it had, with no settings at all: it sends one request's settings to each
    model it holds in turn, and one ceiling cannot fit models whose budgets and
    allowances differ, so it is asked for no thinking. Nothing in this project builds
    one; the round's resilience is the caller's (see the module docstring).

    Where ``summarised`` — the diagnostic record is on — and the thinking is asked for
    of a model with Anthropic's adaptive thinking whose own settings do not configure
    it, the request asks for the thinking's summarised text (ADR-0314 §5:1). The key is
    Anthropic's own, so any other model ignores it.
    """
    inner = model
    while isinstance(inner, WrapperModel):
        inner = inner.wrapped
    if isinstance(inner, FallbackModel):
        return None
    ceiling = None if thinking is False else _ceiling(thinking, inner)
    settings = (
        ModelSettings(thinking=thinking)
        if ceiling is None
        else ModelSettings(thinking=thinking, max_tokens=ceiling)
    )
    if summarised and thinking is not False and _adaptive_unconfigured(inner):
        # Anthropic's own settings key, which ``ModelSettings`` does not declare and
        # every other model ignores.
        widened: dict[str, object] = {**settings, "anthropic_thinking": dict(_SUMMARISED_ADAPTIVE)}
        return cast("ModelSettings", widened)
    return settings


def _adaptive_unconfigured(model: models.Model) -> bool:
    """Whether ``model`` thinks adaptively and its own settings leave that to the request."""
    configured: Mapping[str, object] = model.settings or {}
    return (
        bool(model.profile.get("anthropic_supports_adaptive_thinking", False))
        and "anthropic_thinking" not in configured
    )


def _ceiling(thinking: ThinkingLevel, model: models.Model) -> int | None:
    """The ceiling ``model`` needs for ``thinking``, or ``None`` where it takes none."""
    profile = model.profile
    if not (
        profile.get("supports_thinking", False) or profile.get("thinking_always_enabled", False)
    ):
        return None
    configured: Mapping[str, object] = model.settings or {}
    budget = ANTHROPIC_THINKING_BUDGET_MAP[thinking]
    provider_thinking = configured.get("anthropic_thinking")
    if isinstance(provider_thinking, Mapping):
        configured_budget = provider_thinking.get("budget_tokens")
        if isinstance(configured_budget, int):
            budget = configured_budget
    ceiling = _MESSAGE_TOKENS + budget
    allowed = configured.get("max_tokens")
    if isinstance(allowed, int):
        ceiling = max(ceiling, allowed)
    return ceiling


def _native(tool: OfferedTool) -> NativeTool:
    """One offered capability as a pydantic-ai function tool, its schema thawed."""
    schema: dict[str, Any] = tool.model_dump()["parameters"]
    return NativeTool(name=tool.name, description=tool.description, parameters_json_schema=schema)


@dataclass(frozen=True, slots=True)
class _Request:
    """What a round sent the model: the model, the settings and the request parameters."""

    model: models.Model
    settings: ModelSettings | None
    parameters: ModelRequestParameters


#: Every tool a request offered as the record keeps it, and why not as prepared, if so.
type _Offered = tuple[list[dict[str, object]], dict[str, object] | None]


def _offered(request: _Request) -> _Offered:
    """Every tool ``request`` offered as the record keeps it, and why not as prepared.

    Each tool's parameters are as the model's own request preparation gives them to its
    provider (#2910). The request prepares itself inside pydantic-ai, where nothing can
    observe it, so the record prepares the same model, settings and parameters again,
    immediately before the request is sent. pydantic-ai's own preparation is a function
    of those alone, built by replacement over a deep copy, and pydantic-ai replays it
    itself (its fallback model prepares a request apart from sending it), so that gives
    what the request carried without touching what it sent. The name, the description
    and the order are the round's own.

    Nothing can change those inputs between the two: each of pydantic-ai's own models
    prepares at the top of its ``request``, before anything it awaits, so with no await
    between the replay and the request, and only wrappers that hand the request
    straight on (:data:`_HANDING_STRAIGHT_ON`), nothing else on the event loop runs
    between them. A wrapper that may wait first, as pydantic-ai's concurrency-limited
    model waits for a slot, leaves a window in which they could change, and is not
    replayed.

    So, too, the replay is made only where every piece of code the preparation runs is
    pydantic-ai's own: each model the request passes through is an instance of one of
    pydantic-ai's classes with no method shadowed, and the profile's schema transformer,
    the one hook a profile gives preparation, is pydantic-ai's too. Code of anyone
    else's may keep state a replay would change, recording what was never sent and
    moving the next request on, or carry the request somewhere a replay cannot see.

    Where that cannot be computed, each tool is kept as the round built it and the
    second value says why: where the replay is not made, as above; where the model is a
    :class:`~pydantic_ai.models.fallback.FallbackModel`, which prepares each request for
    whichever model it holds answers; and where the preparation raises, or gives back
    other tools than were sent. Nothing here fails the round or drops the entry.
    """
    sent = request.parameters.function_tools
    try:
        prepared = _prepared(request)
    except Exception as exc:
        # Broad on purpose: the record must not fail the round (ADR-0314 §2:4), and
        # whatever stops the preparation the tools are still kept, marked.
        return [_recorded(tool, tool) for tool in sent], failure_body(exc)
    return [_recorded(tool, as_sent) for tool, as_sent in zip(sent, prepared, strict=True)], None


def _prepared(request: _Request) -> list[NativeTool]:
    """The function tools as ``request.model``'s own request preparation gives them.

    Raises:
        ModelError: If the preparation runs code other than pydantic-ai's own, a
            wrapper may wait before the model it wraps prepares, the model is a
            fallback one, or preparation gives back tools other than the ones sent, by
            name and order.
    """
    inner = request.model
    while True:
        if not _pydantic_ais_own(inner):
            msg = (
                f"{type(inner).__qualname__} is not one of pydantic-ai's own models, so its "
                "preparation is not replayed"
            )
            raise ModelError(msg)
        if not isinstance(inner, WrapperModel):
            break
        if type(inner) not in _HANDING_STRAIGHT_ON:
            msg = (
                f"{type(inner).__qualname__} may wait before the model it wraps prepares the "
                "request, so the preparation is not replayed"
            )
            raise ModelError(msg)
        inner = inner.wrapped
    if isinstance(inner, FallbackModel):
        msg = "a fallback model prepares the request for whichever model it holds answers"
        raise ModelError(msg)
    transformer = inner.profile.get("json_schema_transformer")
    if transformer is not None and not _pydantic_ais(transformer):
        msg = (
            f"the schema transformer {transformer.__qualname__} is not one of pydantic-ai's "
            "own, so the preparation is not replayed"
        )
        raise ModelError(msg)
    _, parameters = request.model.prepare_request(request.settings, request.parameters)
    prepared = list(parameters.function_tools)
    if [tool.name for tool in prepared] != [
        tool.name for tool in request.parameters.function_tools
    ]:
        msg = "the model's request preparation gave back other tools than were sent"
        raise ModelError(msg)
    return prepared


#: The wrappers that hand a request straight to the model they wrap, awaiting nothing
#: before it: pydantic-ai's base wrapper, and the instrumentation ``model_request`` may add.
_HANDING_STRAIGHT_ON: Final[frozenset[type[models.Model]]] = frozenset(
    {WrapperModel, InstrumentedModel}
)


def _pydantic_ais(code: type) -> bool:
    """Whether ``code`` is defined by pydantic-ai itself."""
    return code.__module__.startswith("pydantic_ai.")


def _pydantic_ais_own(model: models.Model) -> bool:
    """Whether ``model`` is an instance of pydantic-ai's own class, its methods unshadowed.

    Then the code that prepares and sends its requests is pydantic-ai's alone, down to
    every method a preparation calls on it.
    """
    cls = type(model)
    shadowed = any(callable(getattr(cls, name, None)) for name in getattr(model, "__dict__", {}))
    return _pydantic_ais(cls) and not shadowed


def _recorded(tool: NativeTool, prepared: NativeTool) -> dict[str, object]:
    """One offered tool as the record keeps it, in the shape planning's given entry has.

    Its name and description are as the round offered it, its parameters as ``prepared``.
    """
    return {
        "name": tool.name,
        "description": tool.description,
        "parameters": copy.deepcopy(prepared.parameters_json_schema),
    }


def _round_tool() -> NativeTool:
    """The reserved tool carrying the notes, built afresh per request."""
    return NativeTool(
        name=ROUND_TOOL,
        description=_ROUND_TOOL_DESCRIPTION,
        parameters_json_schema=copy.deepcopy(_ROUND_TOOL_SCHEMA),
    )


def _round(response: ModelResponse) -> RoundResponse:
    """Read a provider response as a round's three parts (ADR-0315 §3:1).

    The text is the text parts alone: a thinking part is none of the three, and is
    dropped.

    Raises:
        ModelResponseError: If the response was cut at its output ceiling, a call's
            arguments are not a JSON object, the reserved tool's arguments are not of
            its shape, or the parts do not make a round.
    """
    if response.finish_reason == "length":
        msg = "the model's response was cut at its output ceiling, so it is not a whole round"
        raise ModelResponseError(msg)
    calls: list[ProposedCall] = []
    notes: list[str] = []
    asks: dict[str, None] = {}
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
            written = _round_notes(arguments)
            if written is not None and written.strip():
                notes.append(written)
            asks.update(dict.fromkeys(name for name in _round_asks(arguments) if name.strip()))
        return RoundResponse(
            text=response.text or "",
            calls=tuple(calls),
            notes="\n\n".join(notes) if notes else None,
            asks=tuple(asks),
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


def _round_notes(arguments: dict[str, object]) -> str | None:
    """The notes one call of the reserved tool carries.

    Raises:
        ValueError: If they are present and not text, or anything but the notes and the
            naming is present, the retired mark included (ADR-0315 §3:4).
    """
    if set(arguments) - {"notes", "asks"}:
        msg = "the round's tool takes notes and the calls its message asks about alone"
        raise ValueError(msg)
    notes = arguments.get("notes")
    if notes is not None and not isinstance(notes, str):
        msg = "the round's notes are text"
        raise ValueError(msg)
    return notes


def _round_asks(arguments: dict[str, object]) -> list[str]:
    """The names one call of the reserved tool gives the calls its message asks about.

    Raises:
        ValueError: If they are present and not an array of text (ADR-0321 §2:3).
    """
    asks = arguments.get("asks")
    if asks is None:
        return []
    if not isinstance(asks, list) or not all(isinstance(name, str) for name in asks):
        msg = "the calls a round's message asks about are named by text"
        raise ValueError(msg)
    return asks
