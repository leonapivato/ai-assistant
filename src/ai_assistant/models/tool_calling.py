"""A :class:`~ai_assistant.core.protocols.ToolCallingCompleter` backed by pydantic-ai.

The planning round's sibling of :mod:`ai_assistant.models.provider` (ADR-0307 §10):
one model response in the provider's native tool-calling shape, through pydantic-ai's
direct request API, so the provider's own tool calling carries the calls and nothing
parses them out of reply text. Nothing here runs a call: pydantic-ai's direct request
returns the model's response and executes no tool.

**A round is the model's response in two parts and its continuation** (ADR-0356 §7:1,
§6:1). Its text is the text parts alone, joined as pydantic-ai joins them, and is the
model's reply to the system, which planning keeps as its notes; its calls are every call
the model proposed. No tool carries notes and no tool name is reserved (§7:4): a tool
of any name is offered as given, ``planning_round`` included. No part of the response
names the calls a message asks about (§7:5).

**The exchange is translated into the provider's messages** (ADR-0356 §5, §13). The
instruction is the system part and the briefing one user part, in the request that opens
the history, exactly as :class:`~ai_assistant.models.provider.PydanticAIProvider` sends a
system and a user turn. Each earlier round's response is handed back as the provider
returned it, rebuilt from its continuation (§6:2); each report follows it as one request
of the provider's tool-result parts, under their call ids and in order, then the news as
a user part. The newest report carries a cache point, so the exchange up to it is read
back from the cache on the next round; a model that caches nothing drops the point.

**A failed call is flagged to the provider** (ADR-0364 §6:5-§6:6). A result whose
outcome is not done or refused goes back as a tool result whose ``outcome`` is
``failed``, and an unknown, a done and a result with no outcome as ``success``. Where the
provider takes a flag of its own, it carries it: Anthropic's ``is_error``. pydantic-ai's
Anthropic model sends every tool result with ``is_error`` false whatever its outcome, so
a round to it goes through :func:`_flagging`'s subclass, which sets the flag on each
result whose outcome is ``failed`` once pydantic-ai has mapped the request, and changes
nothing else. The flag is never set by handing pydantic-ai a ``RetryPromptPart``, whose
wording tells the model to retry (§6:6).

**Thinking is handed back** (ADR-0356 §6). A response's continuation is the provider's
whole response, every part in order, thinking and the thinking's signatures included,
with the ``"provider:model"`` that wrote it. It is handed back as it was only to the
model that wrote it, and only where it still reads as that response, its calls under the
same ids. Anywhere else, where a response carries no continuation, one another model
wrote, or one that no longer reads as the response, the response is handed back as its
text and its calls alone, which every provider accepts and which carries no thinking for
another model to refuse (§6:3).

**Planning is given room to reason before it writes** (#2861). The request asks for the
provider's thinking through pydantic-ai's unified ``thinking`` setting, which a model or
provider without it ignores. The model reasons in thinking parts and writes its reply to
the system in text parts. A thinking part is no part of a round's text: it reaches the
response's continuation alone, and the episode never carries it (ADR-0356 §6:4). A
provider may count thinking against the response's output ceiling, as Anthropic's does, so where
the model takes the setting the ceiling is widened by the thinking budget pydantic-ai
gives the level on a budget-based Anthropic model, or by the budget the model's own
settings give it: the thinking never takes the room the message had, and a budget-based
model is never refused for a ceiling at or below its budget. A response cut at its
ceiling is not a round: its message may stop mid-sentence and whatever followed the cut
is lost, so it is refused as unreadable rather than returned.

**The diagnostic record keeps the thinking** (ADR-0314 §5), and beyond it only the
response's continuation does, held in memory for the work's life (ADR-0356 §6:4).
Where the composition root hands the completer a
:class:`~ai_assistant.core.protocols.DiagnosticSink` — the record is on — a round on a
model with Anthropic's adaptive thinking asks for the thinking's summarised text, which
that thinking otherwise omits, and the completer writes planning's returned entry from
the provider's whole response, every part in order, thinking included, whether or not
it reads as a round, before it returns or raises. Beside the response it writes every
tool the request offered (#2894). Each tool's parameters are recorded as the chosen
model's request preparation sent them (#2910), since a provider's schema transformer may
rewrite them (OpenAI's adds ``additionalProperties: false``); where that cannot be
computed they are recorded as the round built them, and the entry says so. The entry is
written for the activation :mod:`ai_assistant.core.diagnostics` carries, and nothing is
written where none is bound. Where the record is off, the request is as it is without
this.

**A round asks the provider to cache its tools and instructions** (#3077): they are
the same from one round to the next, and :mod:`~ai_assistant.models.prompt_cache` marks
them where the model is Anthropic's, as it does for every completion; the newest report
is marked as above. A fallback model
keeps the request it had, so it is given no marks either.

**Nothing here retries or re-routes**, as nothing in the streaming sibling does:
``RoutingProvider`` and ``RetryingProvider`` wrap ``ModelProvider`` completions, and a
round's resilience is the caller's to decide.

**A recorded round can be sent again, for the owner's replay tool alone** (ADR-0335
§4:8-§4:9). :meth:`PydanticAIToolCallingCompleter.replay_round` sends one round exactly
as :meth:`~PydanticAIToolCallingCompleter.respond` sends it where the record is on,
summarised thinking included, and hands the caller the provider's whole response, every
part in order, thinking included, beside the round it reads as or why it reads as none
(ADR-0335 §10 lets that thinking reach the replay's results). Where the run's
instruction differs from the one the exchange was recorded with, earlier responses are
handed back without their continuations (ADR-0356 §6:3, §13). It writes no entry, even
where the completer holds a sink, binds no activation and is on no Protocol, and no
stage calls it (§4:9). It sends to the one model it is named, which may not fall back to
another (§4:7), and it sends once and continues nothing (§4:10).
"""

from __future__ import annotations

import copy
import functools
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final, Literal, cast

from pydantic import ValidationError
from pydantic_ai.direct import model_request
from pydantic_ai.messages import (
    CachePoint,
    ModelMessagesTypeAdapter,
    ModelRequest,
    ModelResponse,
    SystemPromptPart,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
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
    CallOutcomeKind,
    DiagnosticKind,
    DiagnosticSource,
    OfferedTool,
    PlanningExchange,
    ProposedCall,
    RoundContinuation,
    RoundResponse,
)
from ai_assistant.models.prompt_cache import marks_the_newest_report, prompt_cache_settings
from ai_assistant.models.provider import _classify

if TYPE_CHECKING:
    from collections.abc import Sequence

    from pydantic_ai import models
    from pydantic_ai.messages import ModelMessage, ModelRequestPart, ModelResponsePart
    from pydantic_ai.settings import ThinkingLevel

    from ai_assistant.core.protocols import DiagnosticSink
    from ai_assistant.core.types import CallResult

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

#: ADR-0364 §6:5: the outcomes flagged to the provider as an error. An unknown is not, and
#: a result with no outcome is not.
_FLAGGED: Final = frozenset({CallOutcomeKind.NOT_DONE, CallOutcomeKind.REFUSED})

#: pydantic-ai's Anthropic model's module, read only where a round has resolved it.
_ANTHROPIC_MODULE: Final = "pydantic_ai.models.anthropic"


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
        exchange: PlanningExchange,
        tools: Sequence[OfferedTool],
        *,
        model: str | None = None,
    ) -> RoundResponse:
        """Produce one planning round's response to ``exchange``, offering ``tools``.

        The request is built on the call, before the first await, from one observation
        of each argument (ADR-0065): the exchange is translated and the tools are
        rebuilt through validation, so a caller mutating the tools while the round is
        out cannot tear it.

        Args:
            exchange: The work's exchange, oldest first.
            tools: The capabilities offered for this round.
            model: Optional ``"provider:model"`` override.

        Returns:
            The round's response, its continuation the provider's whole response.

        Raises:
            ModelError: The bare class, before any model is contacted, if two tools
                share a name. A provider failure is narrowed to the most specific
                subclass, and a response that cannot be read as a round, or was cut at
                its output ceiling, is a
                :class:`~ai_assistant.core.errors.ModelResponseError`.
        """
        parameters = _round_parameters(tools, caller="respond()")
        try:
            chosen = _flagging(infer_model(self._default_model if model is None else model))
            settings = _settings(self._thinking, chosen, summarised=self._diagnostics is not None)
            recipient = model_id(chosen)
            history = exchange_history(
                exchange, recipient, cache_point=marks_the_newest_report(chosen)
            )
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
            read = _round(response, _writer(recipient, response))
        except ModelResponseError as exc:
            await self._returned(offered_record, response, exc)
            raise
        await self._returned(offered_record, response, None)
        return read

    async def replay_round(
        self,
        exchange: PlanningExchange,
        tools: Sequence[OfferedTool],
        *,
        model: models.Model | str,
        instruction: str | None = None,
    ) -> ReplayedRound:
        """Send one recorded round again, as :meth:`respond` sends it with the record on.

        The owner's replay tool's seam (ADR-0335 §4:8): the request is built as
        :meth:`respond` builds it, and its settings are the ones :meth:`respond` sends
        where it holds a sink, so a model with Anthropic's adaptive thinking is asked
        for the thinking's summarised text. Nothing is written, whether or not this
        completer holds a sink, and no activation is bound (§4:9). It is sent once, to
        ``model`` alone (§4:7), and nothing is continued: no further round, no repair
        and no tool's result (§4:10).

        Args:
            exchange: The round's recorded exchange, oldest first.
            tools: The capabilities the round offered, as planning's given entry records
                them.
            model: The one model the run names, as a ``"provider:model"`` string or a
                pydantic-ai model. It replaces this completer's default model for this
                call, and may not be a fallback model, wrapped or not.
            instruction: A candidate's instruction, sent in place of the exchange's own;
                where it differs from it, earlier responses are handed back without
                their continuations (ADR-0356 §6:3, §13). ``None`` sends the exchange's
                own.

        Returns:
            The provider's whole response, with the round it reads as or why it reads as
            none.

        Raises:
            ModelError: The bare class, before any model is contacted, where
                :meth:`respond` would refuse ``tools``, ``instruction`` is blank, or
                ``model`` is a fallback model. A failure sending the request, where no
                response came back, is narrowed as :meth:`respond` narrows it; a
                response that does not read as a round is returned, not raised.
        """
        parameters = _round_parameters(tools, caller="replay_round()")
        sent = candidate_exchange(exchange, instruction, caller="replay_round()")
        try:
            chosen = _flagging(infer_model(model))
        except Exception as exc:
            # As in `respond`: resolving a string model may fail, and is classified.
            raise _classify(exc) from exc
        if _falls_back(chosen):
            msg = "a replay sends to the one model it names, which a fallback model may not be"
            raise ModelError(msg)
        try:
            settings = _settings(self._thinking, chosen, summarised=True)
            recipient = model_id(chosen)
            response = await model_request(
                chosen,
                exchange_history(sent, recipient, cache_point=marks_the_newest_report(chosen)),
                model_settings=settings,
                model_request_parameters=parameters,
            )
        except Exception as exc:
            # Broad on purpose, as in `respond`: `_classify` is the taxonomy (ADR-0063).
            raise _classify(exc) from exc
        whole = ModelMessagesTypeAdapter.dump_python([response], mode="json")[0]
        try:
            read = _round(response, _writer(recipient, response))
        except ModelResponseError as exc:
            return ReplayedRound(response=whole, round=None, failure=exc)
        return ReplayedRound(response=whole, round=read, failure=None)

    async def _returned(
        self,
        offered: _Offered | None,
        response: ModelResponse,
        failure: ModelResponseError | None,
    ) -> None:
        """Write planning's returned entry from the provider's whole response (§5:2).

        Every part in order, thinking included, as pydantic-ai serialises the response;
        every tool the request offered, in the order it offered them (#2894), each as
        the chosen model's request preparation gave it to the provider (#2910); and
        where the response did not read as a round, why not.
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


@dataclass(frozen=True, slots=True)
class ReplayedRound:
    """What a replayed round got back (ADR-0335 §4:8): the whole response, and its reading.

    Attributes:
        response: The provider's whole response, every part in order, thinking included,
            as pydantic-ai serialises it to JSON: the form planning's returned entry
            keeps it in.
        round: The response read as a round, or ``None`` where it reads as none.
        failure: Why the response reads as no round, or ``None`` where it reads as one.
    """

    response: dict[str, Any]
    round: RoundResponse | None
    failure: ModelResponseError | None


def _round_parameters(tools: Sequence[OfferedTool], *, caller: str) -> ModelRequestParameters:
    """A round's tools as the request offers them, every one as given and none added.

    Built from one observation of ``tools`` (ADR-0065): each is rebuilt through
    validation. No name is reserved (ADR-0356 §7:4).

    Raises:
        ModelError: The bare class if two tools share a name.
    """
    offered = [_native(OfferedTool.model_validate(tool.model_dump())) for tool in tools]
    names = [tool.name for tool in offered]
    if len(set(names)) != len(names):
        msg = f"{caller} requires distinct tool names"
        raise ModelError(msg)
    return ModelRequestParameters(function_tools=offered, allow_text_output=True)


def model_id(model: models.Model) -> str | None:
    """The ``"provider:model"`` a request to ``model`` goes to, under any wrappers.

    A continuation names the model that wrote it (ADR-0356 §13), and it is handed back
    as it was only to the model of the same name (§6:3). A fallback model has no one
    name: which model it holds answers is known only once one has, so it is ``None``,
    and nothing is handed back to it as it was.
    """
    inner = model
    while isinstance(inner, WrapperModel):
        inner = inner.wrapped
    if isinstance(inner, FallbackModel):
        return None
    return f"{inner.system}:{inner.model_name}"


def _writer(recipient: str | None, response: ModelResponse) -> str:
    """The ``"provider:model"`` that wrote ``response``, sent to ``recipient``.

    The model the request went to, where it was one model; for a fallback model's, the
    model the response names as having answered (ADR-0356 §13).
    """
    if recipient is not None:
        return recipient
    provider = response.provider_name or "unknown"
    return f"{provider}:{response.model_name or 'unknown'}"


def candidate_exchange(
    exchange: PlanningExchange, instruction: str | None, *, caller: str
) -> PlanningExchange:
    """``exchange`` under ``instruction``, its continuations dropped where that differs.

    A response's thinking was written under the instruction the exchange was recorded
    with, so a candidate's replay or follow-up under another instruction hands earlier
    responses back without their continuations (ADR-0356 §13).

    Raises:
        ModelError: The bare class if ``instruction`` is blank.
    """
    if instruction is None or instruction == exchange.instruction:
        return exchange
    if not instruction.strip():
        msg = f"{caller} requires a non-blank instruction"
        raise ModelError(msg)
    steps = tuple(
        step.model_copy(
            update={"response": step.response.model_copy(update={"continuation": None})}
        )
        for step in exchange.steps
    )
    return exchange.model_copy(update={"instruction": instruction, "steps": steps})


def exchange_history(
    exchange: PlanningExchange, recipient: str | None, *, cache_point: bool = True
) -> list[ModelMessage]:
    """The provider's messages for ``exchange``, as the model ``recipient`` names is sent it.

    The instruction is the system part and the briefing a user part of the first
    request; then each earlier response, handed back as :func:`_handed_back` gives it,
    and the request after it: the report's results as tool-result parts under their
    call ids and in order, then the news. Where ``cache_point``, the newest report ends
    on a cache point (ADR-0356 §13). A response with nothing to hand back is left out,
    and its report follows the request before it, which providers join into one turn.

    Args:
        exchange: The exchange, oldest first.
        recipient: The ``"provider:model"`` the request goes to (:func:`model_id`), or
            ``None`` for a fallback model, which is handed back no continuation.
        cache_point: Whether the newest report ends on a cache point.

    Returns:
        The history, ending on a request.
    """
    history: list[ModelMessage] = [
        ModelRequest(
            parts=[
                SystemPromptPart(content=exchange.instruction),
                UserPromptPart(content=exchange.briefing),
            ]
        )
    ]
    for index, step in enumerate(exchange.steps):
        handed = _handed_back(step.response, recipient)
        if handed is not None:
            history.append(handed)
        names = {call.call_id: call.name for call in step.response.calls}
        parts: list[ModelRequestPart] = [
            ToolReturnPart(
                tool_name=names[result.call_id],
                content=result.text,
                tool_call_id=result.call_id,
                outcome=_returned_outcome(result),
            )
            for result in step.report.results
        ]
        newest = cache_point and index == len(exchange.steps) - 1
        parts.append(
            UserPromptPart(content=[step.report.news, CachePoint()] if newest else step.report.news)
        )
        history.append(ModelRequest(parts=parts))
    return history


def _returned_outcome(result: CallResult) -> Literal["success", "failed"]:
    """How a call's result goes back to the provider (ADR-0364 §6:5).

    ``failed`` where planning was shown it not done or refused, and ``success`` for a
    done, an unknown and a result with no outcome.
    """
    return "failed" if result.outcome in _FLAGGED else "success"


def _flagging(model: models.Model) -> models.Model:
    """``model``, flagging a failed call's result where its provider takes a flag (§6:5).

    pydantic-ai's own Anthropic model, unwrapped, is rebuilt as :func:`_flagging_class`'s
    subclass of it, with its name, provider, profile and settings; every other model is
    returned as it is. A wrapped one is left alone, so a wrapper's request is never
    rebuilt under it.
    """
    module = sys.modules.get(_ANTHROPIC_MODULE)
    if module is None or type(model) is not module.AnthropicModel:
        return model
    flagging = _flagging_class(module.AnthropicModel)
    return cast(
        "models.Model",
        flagging(
            model.model_name,
            provider=model._provider,
            profile=model._profile,
            settings=model._settings,
        ),
    )


@functools.cache
def _flagging_class(anthropic: type[Any]) -> type[Any]:
    """The subclass of pydantic-ai's Anthropic model that sets ``is_error`` (§6:5).

    pydantic-ai maps a round's history to Anthropic's messages in ``_map_message`` and
    sends every tool result with ``is_error`` false. The subclass lets it map them, then
    sets ``is_error`` on each tool result whose part's ``outcome`` is ``failed``, by its
    call id, and changes nothing else: preparation, settings and the response are
    pydantic-ai's own.
    """

    class FlaggingAnthropicModel(anthropic):  # type: ignore[misc]  # built from the module the round resolved
        async def _map_message(  # type: ignore[no-untyped-def]  # pydantic-ai's own signature
            self, messages, model_request_parameters, model_settings
        ):
            system, mapped = await super()._map_message(
                messages, model_request_parameters, model_settings
            )
            failed = {
                part.tool_call_id
                for message in messages
                if isinstance(message, ModelRequest)
                for part in message.parts
                if isinstance(part, ToolReturnPart) and part.outcome == "failed"
            }
            for one in mapped:
                content = one.get("content")
                if not isinstance(content, list):
                    continue
                for block in content:
                    if (
                        isinstance(block, dict)
                        and block.get("type") == "tool_result"
                        and block.get("tool_use_id") in failed
                    ):
                        block["is_error"] = True
            return system, mapped

    return FlaggingAnthropicModel


def _handed_back(response: RoundResponse, recipient: str | None) -> ModelResponse | None:
    """``response`` as the provider is handed it back, or ``None`` where it holds nothing.

    Its continuation rebuilt, where the model it goes to wrote it and it still reads as
    this response: one model response whose text and calls, by id, name and arguments,
    are the response's own. Anywhere else, its text and its calls alone (ADR-0356 §6:3).
    """
    continuation = response.continuation
    if continuation is not None and recipient is not None and continuation.model == recipient:
        rebuilt = _rebuilt(continuation)
        if rebuilt is not None and _reads_as(rebuilt, response):
            return rebuilt
    parts: list[ModelResponsePart] = []
    if response.text:
        parts.append(TextPart(content=response.text))
    parts.extend(
        ToolCallPart(
            tool_name=call.name,
            args=call.model_dump(mode="json")["arguments"],
            tool_call_id=call.call_id,
        )
        for call in response.calls
    )
    return ModelResponse(parts=parts) if parts else None


def _rebuilt(continuation: RoundContinuation) -> ModelResponse | None:
    """The response a continuation holds, or ``None`` where it holds no one response."""
    try:
        rebuilt = ModelMessagesTypeAdapter.validate_python([_thawed(continuation.parts)])
    except ValidationError, TypeError, ValueError:
        return None
    if len(rebuilt) != 1 or not isinstance(rebuilt[0], ModelResponse):
        return None
    return rebuilt[0]


def _thawed(value: object) -> object:
    """A frozen JSON value as plain JSON: mappings as dicts, sequences as lists."""
    if isinstance(value, Mapping):
        return {str(key): _thawed(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [_thawed(item) for item in value]
    return value


def _reads_as(rebuilt: ModelResponse, response: RoundResponse) -> bool:
    """Whether ``rebuilt`` reads as ``response``: the same text, and the same calls."""
    try:
        read = _round(rebuilt, None)
    except ModelResponseError:
        return False
    return read.text == response.text and read.calls == response.calls


def _falls_back(model: models.Model) -> bool:
    """Whether ``model``, under any wrappers, is a fallback model."""
    inner = model
    while isinstance(inner, WrapperModel):
        inner = inner.wrapped
    return isinstance(inner, FallbackModel)


def _settings(
    thinking: ThinkingLevel, model: models.Model, *, summarised: bool = False
) -> ModelSettings | None:
    """A round's model settings: the thinking it asks for, room for it, and the cache marks.

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

    Where the model is Anthropic's, the round's tools and instructions are marked for
    caching (:func:`~ai_assistant.models.prompt_cache.prompt_cache_settings`); any other
    model is given no marks.
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
    widened: dict[str, object] = {**settings, **prompt_cache_settings(inner)}
    if summarised and thinking is not False and _adaptive_unconfigured(inner):
        # Anthropic's own settings key, which ``ModelSettings`` does not declare and
        # every other model ignores.
        widened["anthropic_thinking"] = dict(_SUMMARISED_ADAPTIVE)
    return cast("ModelSettings", widened)


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
    if cls.__qualname__.endswith("FlaggingAnthropicModel") and cls.__module__ == __name__:
        # The flagging subclass overrides the message mapping alone, which preparation
        # never calls (ADR-0364 §6:5), so its preparation is pydantic-ai's own.
        cls = cls.__mro__[1]
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


def _round(response: ModelResponse, written_by: str | None) -> RoundResponse:
    """Read a provider response as a round's parts (ADR-0356 §7:1, §6:1).

    The text is the text parts alone, joined as pydantic-ai joins them: a thinking part
    is no part of it. Every call is a call, whatever its name (§7:4). The continuation
    is the whole response, every part in order, written by ``written_by``, or none where
    that is ``None``.

    Raises:
        ModelResponseError: If the response was cut at its output ceiling, a call's
            arguments are not a JSON object, or the parts do not make a round.
    """
    if response.finish_reason == "length":
        msg = "the model's response was cut at its output ceiling, so it is not a whole round"
        raise ModelResponseError(msg)
    try:
        calls = tuple(
            ProposedCall(call_id=part.tool_call_id, name=part.tool_name, arguments=_arguments(part))
            for part in response.parts
            if isinstance(part, ToolCallPart)
        )
        continuation = (
            None
            if written_by is None
            else RoundContinuation(
                model=written_by,
                parts=ModelMessagesTypeAdapter.dump_python([response], mode="json")[0],
            )
        )
        return RoundResponse(text=response.text or "", calls=calls, continuation=continuation)
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
