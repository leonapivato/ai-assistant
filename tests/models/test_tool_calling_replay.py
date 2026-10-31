"""``PydanticAIToolCallingCompleter.replay_round``: the replay tool's seam (ADR-0335 §4:8).

It sends a recorded planning round as ``respond`` sends it where the diagnostic record is
on, summarised thinking included, and returns the provider's whole response, with no sink
(§4:8). It writes no entry and binds no activation, and nothing outside ``models/`` names it
(§4:9). It sends to the one model it is named and never to another (§4:7), and it sends once
and continues nothing (§4:10).

As in ``test_tool_calling``, a ``FunctionModel`` is the world, and where the vendor decides
the request's shape it is read off the wire of Anthropic's real SDK over a mock transport,
with the network denied.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Final

import httpx
import pytest
from anthropic import AsyncAnthropic
from network_guard import network_denied
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.messages import (
    ModelMessagesTypeAdapter,
    ModelRequest,
    ModelResponse,
    SystemPromptPart,
    TextPart,
    ThinkingPart,
    ToolCallPart,
)
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.models.fallback import FallbackModel
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.wrapper import WrapperModel
from pydantic_ai.providers.anthropic import AnthropicProvider
from vendor_stacks import RequestRecorder, anthropic_success

import ai_assistant
from ai_assistant.core.diagnostics import (
    diagnosed_activation,
    diagnosed_activation_id,
    returned_written,
)
from ai_assistant.core.errors import ModelError, ModelRateLimitError, ModelResponseError
from ai_assistant.core.types import (
    CallResult,
    DiagnosticSource,
    ExchangeStep,
    Message,
    OfferedTool,
    PlanningExchange,
    ProposedCall,
    Role,
    RoundContinuation,
    RoundReport,
    RoundResponse,
)
from ai_assistant.models import PydanticAIToolCallingCompleter, tool_calling
from ai_assistant.testing import FakeDiagnosticSink

if TYPE_CHECKING:
    from pydantic_ai.messages import ModelMessage, ModelResponsePart
    from pydantic_ai.models import Model
    from vendor_stacks import Handler

    from ai_assistant.models.tool_calling import ReplayedRound

_DUMMY_KEY: Final = "test-key-not-a-credential"
_ACTIVATION: Final = "7c1e9a2b-4d3f-4a8e-b5c6-1f2e3d4a5b6c"


def _now() -> datetime:
    return datetime(2026, 10, 20, 12, 0, tzinfo=UTC)


def _exchange() -> PlanningExchange:
    return PlanningExchange(instruction="A candidate instruction.", briefing="book me a stay")


def _given_entry() -> dict[str, object]:
    """A recorded planning given entry's request, as planning's module writes it."""
    return {
        "exchange": _exchange().model_dump(mode="json"),
        "messages": [
            Message(role=Role.SYSTEM, content="A candidate instruction.").model_dump(mode="json"),
            Message(role=Role.USER, content="book me a stay").model_dump(mode="json"),
        ],
        "tools": [
            OfferedTool(
                name="web_search",
                description="Search the web.",
                parameters={"type": "object", "properties": {"query": {"type": "string"}}},
            ).model_dump(mode="json")
        ],
    }


def _recorded() -> tuple[PlanningExchange, list[OfferedTool]]:
    """The request a script outside the package rebuilds from a given entry's JSON."""
    entry = _given_entry()
    tools = entry["tools"]
    assert isinstance(tools, list)
    return (
        PlanningExchange.model_validate(entry["exchange"]),
        [OfferedTool.model_validate(one) for one in tools],
    )


class _Counted:
    """A ``FunctionModel`` answering with fixed parts, counting the requests it was sent."""

    def __init__(self, *parts: ModelResponsePart, finish: str | None = None) -> None:
        self.parts = list(parts)
        self.finish = finish
        self.requests = 0
        self.bound: list[str | None] = []
        self.model = FunctionModel(self.answer)

    def answer(self, messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        del messages, info
        self.requests += 1
        self.bound.append(diagnosed_activation_id())
        return ModelResponse(parts=list(self.parts), finish_reason=self.finish)  # type: ignore[arg-type]


def _refusing() -> tuple[FunctionModel, list[int]]:
    """A model whose every request fails with a rate limit, and how many it was sent."""
    calls: list[int] = []

    def refuse(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        del messages, info
        calls.append(1)
        raise ModelHTTPError(status_code=429, model_name="named")

    return FunctionModel(refuse), calls


def _never() -> FunctionModel:
    def answer(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        del messages, info
        msg = "the completer's default model was asked"
        raise AssertionError(msg)

    return FunctionModel(answer)


async def _replay(model: Model) -> ReplayedRound:
    exchange, tools = _recorded()
    return await PydanticAIToolCallingCompleter(_never()).replay_round(exchange, tools, model=model)


# --- §4:8: sent as `respond` sends it with the record on, the whole response returned --------


def _anthropic(name: str, http_client: httpx.AsyncClient) -> Model:
    client = AsyncAnthropic(api_key=_DUMMY_KEY, http_client=http_client, max_retries=0)
    return AnthropicModel(name, provider=AnthropicProvider(anthropic_client=client))


async def _wire(name: str, handler: Handler, *, replay: bool) -> dict[str, object]:
    """The body one round put on Anthropic's wire: replayed with no sink, or with one."""
    recorder = RequestRecorder(handler)
    exchange, tools = _recorded()
    with network_denied():
        async with httpx.AsyncClient(transport=httpx.MockTransport(recorder)) as http_client:
            model = _anthropic(name, http_client)
            if replay:
                await PydanticAIToolCallingCompleter(_never()).replay_round(
                    exchange, tools, model=model
                )
            else:
                completer = PydanticAIToolCallingCompleter(model, diagnostics=FakeDiagnosticSink())
                await completer.respond(exchange, tools)
    return recorder.only


async def test_a_replay_with_no_sink_asks_adaptive_thinking_for_its_summarised_text() -> None:
    body = await _wire("claude-sonnet-5-5", anthropic_success, replay=True)
    assert body["thinking"] == {"type": "adaptive", "display": "summarized"}


@pytest.mark.parametrize("name", ["claude-sonnet-5-5", "claude-opus-4-8", "claude-haiku-4-5"])
async def test_a_replay_puts_on_the_wire_what_respond_puts_there_with_the_record_on(
    name: str,
) -> None:
    replayed = await _wire(name, anthropic_success, replay=True)
    responded = await _wire(name, anthropic_success, replay=False)
    assert replayed == responded


async def test_a_replay_returns_the_whole_response_thinking_included() -> None:
    world = _Counted(
        ThinkingPart("They asked for a stay, so search first."),
        TextPart("Looking now."),
        ToolCallPart("web_search", {"query": "stays"}, tool_call_id="a"),
    )

    replayed = await _replay(world.model)

    parts = replayed.response["parts"]
    assert [part["part_kind"] for part in parts] == ["thinking", "text", "tool-call"]
    assert parts[0]["content"] == "They asked for a stay, so search first."
    assert replayed.round is not None
    assert replayed.round.model_copy(update={"continuation": None}) == RoundResponse(
        text="Looking now.",
        calls=(ProposedCall(call_id="a", name="web_search", arguments={"query": "stays"}),),
    )
    assert replayed.failure is None


async def test_a_replay_returns_a_response_that_reads_as_no_round_with_why() -> None:
    world = _Counted(ThinkingPart("Weighing it…"), finish="length")

    replayed = await _replay(world.model)

    assert replayed.round is None
    assert isinstance(replayed.failure, ModelResponseError)
    assert replayed.response["parts"][0]["content"] == "Weighing it…"
    assert replayed.response["finish_reason"] == "length"


# --- §4:9: no entry, no activation bound -----------------------------------------------------


async def test_a_replay_writes_no_entry_even_where_the_completer_holds_a_sink() -> None:
    world = _Counted(ThinkingPart("hm"), TextPart("ok"))
    sink = FakeDiagnosticSink()
    completer = PydanticAIToolCallingCompleter(_never(), diagnostics=sink)
    exchange, tools = _recorded()

    with diagnosed_activation(_ACTIVATION, clock=_now):
        before = returned_written(DiagnosticSource.PLANNING)
        replayed = await completer.replay_round(exchange, tools, model=world.model)
        after = returned_written(DiagnosticSource.PLANNING)

    assert replayed.round is not None
    assert replayed.round.text == "ok"
    assert sink.recorded == ()
    assert after == before


async def test_a_replay_binds_no_activation() -> None:
    world = _Counted(TextPart("ok"))

    await _replay(world.model)

    assert world.bound == [None]


# --- §4:7: one named model, no fallback, a failure reported as failed --------------------------


async def test_a_replay_sends_to_the_model_it_is_named_not_the_completers_default() -> None:
    world = _Counted(TextPart("ok"))

    await _replay(world.model)

    assert world.requests == 1


@pytest.mark.parametrize("wrapped", [False, True], ids=["bare", "wrapped"])
async def test_a_replay_to_a_fallback_model_is_refused_before_any_model_is_asked(
    wrapped: bool,
) -> None:
    primary, secondary = _Counted(TextPart("one")), _Counted(TextPart("two"))
    model: Model = FallbackModel(primary.model, secondary.model)
    if wrapped:
        model = WrapperModel(model)

    with pytest.raises(ModelError) as caught:
        await _replay(model)

    assert type(caught.value) is ModelError
    assert (primary.requests, secondary.requests) == (0, 0)


async def test_a_failed_replay_raises_classified_and_asks_no_other_model() -> None:
    model, calls = _refusing()

    with pytest.raises(ModelRateLimitError):
        await _replay(model)

    assert calls == [1]


# --- §4:10: sent once, nothing continued -----------------------------------------------------


async def test_a_replay_is_sent_once_and_its_calls_are_not_run_or_answered() -> None:
    world = _Counted(ToolCallPart("web_search", {"query": "stays"}, tool_call_id="a"))

    replayed = await _replay(world.model)

    assert world.requests == 1
    assert replayed.round is not None
    assert [call.name for call in replayed.round.calls] == ["web_search"]


def _stepped(*, signed: bool) -> PlanningExchange:
    """The recorded exchange with one earlier step, its response signed or not."""
    continuation = (
        RoundContinuation(
            model="function:function:answer:",
            parts=ModelMessagesTypeAdapter.dump_python(
                [
                    ModelResponse(
                        parts=[
                            ThinkingPart("search first", signature="sig"),
                            ToolCallPart("web_search", {"query": "stays"}, tool_call_id="a"),
                        ]
                    )
                ],
                mode="json",
            )[0],
        )
        if signed
        else None
    )
    step = ExchangeStep(
        response=RoundResponse(
            calls=(ProposedCall(call_id="a", name="web_search", arguments={"query": "stays"}),),
            continuation=continuation,
        ),
        report=RoundReport(
            results=(CallResult(call_id="a", text="Two stays."),), news="Nothing changed."
        ),
    )
    return _exchange().model_copy(update={"steps": (step,)})


class _Seeing:
    """A ``FunctionModel`` that keeps every history it was sent."""

    def __init__(self) -> None:
        self.sent: list[list[ModelMessage]] = []

    def answer(self, messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        del info
        self.sent.append(list(messages))
        return ModelResponse(parts=[TextPart("ok")])


@pytest.mark.parametrize(
    ("instruction", "thinking_kept"),
    [
        pytest.param(None, True, id="as-recorded"),
        pytest.param("A candidate instruction.", True, id="the-same-instruction"),
        pytest.param("Another candidate.", False, id="another-instruction"),
    ],
)
async def test_a_candidates_replay_hands_earlier_responses_back_without_continuations(
    instruction: str | None, thinking_kept: bool
) -> None:
    """ADR-0356 §13: thinking written under one instruction is not handed to another."""
    seeing = _Seeing()
    model = FunctionModel(seeing.answer)
    assert tool_calling.model_id(model) == "function:function:answer:"
    _, tools = _recorded()

    await PydanticAIToolCallingCompleter(_never()).replay_round(
        _stepped(signed=True), tools, model=model, instruction=instruction
    )

    (sent,) = seeing.sent
    opening, handed = sent[0], sent[1]
    assert isinstance(opening, ModelRequest)
    assert isinstance(opening.parts[0], SystemPromptPart)
    assert opening.parts[0].content == (instruction or "A candidate instruction.")
    assert isinstance(handed, ModelResponse)
    assert any(isinstance(part, ThinkingPart) for part in handed.parts) is thinking_kept


async def test_a_replay_under_a_blank_instruction_is_refused_before_the_model() -> None:
    world = _Counted(TextPart("ok"))
    _, tools = _recorded()

    with pytest.raises(ModelError) as caught:
        await PydanticAIToolCallingCompleter(_never()).replay_round(
            _stepped(signed=False), tools, model=world.model, instruction="  "
        )

    assert type(caught.value) is ModelError
    assert world.requests == 0


# --- §4:9: no stage calls it -----------------------------------------------------------------

_ROOT: Final = Path(ai_assistant.__file__).resolve().parent

#: The one module that may name the seam: its own.
_HOME: Final = Path("models/tool_calling.py")


def test_nothing_in_the_package_but_its_own_module_names_the_seam() -> None:
    # A claim about something not happening, so checked over the source, as
    # test_speech_wiring checks the hub holds no speech seam: a runtime test shows only
    # that the path it drove did not reach the seam. Textual on purpose: a call, an
    # import or a getattr by name would each have to spell it.
    sources = sorted(_ROOT.rglob("*.py"))
    naming = {
        path.relative_to(_ROOT)
        for path in sources
        if "replay_round" in path.read_text(encoding="utf-8")
        or "ReplayedRound" in path.read_text(encoding="utf-8")
    }

    assert _ROOT / _HOME in sources
    assert naming == {_HOME}
