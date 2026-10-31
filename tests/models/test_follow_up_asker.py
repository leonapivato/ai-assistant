"""The follow-up asker on the owner's hub: a sink around the record's sink (ADR-0337 §8).

Every case wraps the canonical fake sink, hands the asker entries as an emitter would,
and reads back what the fake was written: the entries passed on unchanged, and the
asker's own ``follow_up`` entries. A ``FunctionModel`` is the world each follow-up is
sent to, so nothing here reaches a provider.
"""

from __future__ import annotations

import asyncio
import contextlib
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Final

import httpx
import pytest
import structlog
from anthropic import AsyncAnthropic
from network_guard import network_denied
from pydantic_ai.messages import (
    ModelMessagesTypeAdapter,
    ModelRequest,
    ModelResponse,
    SystemPromptPart,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.providers.anthropic import AnthropicProvider
from vendor_stacks import RequestRecorder, failing_status

from ai_assistant.core.correlation import correlated_operation, current_correlation
from ai_assistant.core.diagnostics import (
    DIAGNOSTIC_NOT_WRITTEN,
    diagnosed_activation,
    diagnosed_activation_id,
)
from ai_assistant.core.prompts import PromptDeclaration
from ai_assistant.core.protocols import DiagnosticSink
from ai_assistant.core.types import DiagnosticEntry, DiagnosticKind, DiagnosticSource
from ai_assistant.models.follow_up import (
    FOLLOW_UP_NOT_ASKED,
    FOLLOW_UP_PROMPT,
    FOLLOW_UP_ROUTES,
    NOT_RUN,
    FollowUpAsker,
)
from ai_assistant.testing import FakeDiagnosticSink, default_prompt, diagnostic_entry, prompt_from

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from pydantic_ai.messages import ModelMessage
    from pydantic_ai.models import Model

_ACTIVATION: Final = "3f0c2a8e-1b7d-4c55-9e21-6a4b8d0f1e2c"
_OTHER: Final = "9a1d4e2b-7c3f-4b8a-a1e5-2d6f0c9b3e71"
_AT: Final = datetime(2026, 10, 21, 12, 0, tzinfo=UTC)
_PROMPT: Final = {"name": "understanding", "version": "v1", "origin": "default", "flags": {}}
_TEMPLATE: Final = default_prompt(FOLLOW_UP_PROMPT)
_QUESTION: Final = _TEMPLATE.render()
#: Every route's spec, unless a case names others: the world's model, by the name it answers.
_ROUTE: Final = "fake:world"
_ANOTHER: Final = PromptDeclaration(name="another", package="ai_assistant.models")


class _World:
    """A ``FunctionModel`` answering each follow-up, keeping what it was sent and where."""

    def __init__(self, answer: str = "I had to guess the date.") -> None:
        self.answer = answer
        self.sent: list[list[ModelMessage]] = []
        self.bound: list[tuple[str | None, str | None]] = []
        self.gate: asyncio.Event | None = None
        self.failure: Exception | None = None
        self.built: list[str] = []
        self.opened = 0
        self.closed = 0
        world = self

        class _Owned(FunctionModel):
            """The world's model, counting how often its client is opened and closed."""

            async def __aenter__(self) -> _Owned:
                world.opened += 1
                return self

            async def __aexit__(self, *args: object) -> None:
                world.closed += 1

        self.model: FunctionModel = _Owned(self._respond, model_name="world")

    def build(self, spec: str) -> Model:
        """The model any spec names, here: the world's, counting each build."""
        self.built.append(spec)
        return self.model

    async def _respond(self, messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        del info
        self.sent.append(messages)
        self.bound.append((diagnosed_activation_id(), current_correlation()))
        if self.gate is not None:
            await self.gate.wait()
        if self.failure is not None:
            raise self.failure
        return ModelResponse(parts=[TextPart(self.answer)] if self.answer else [])


class _Clock:
    def __init__(self) -> None:
        self.at = 1_000.0

    def __call__(self) -> float:
        return self.at


def _asker(  # noqa: PLR0913 — the sink, the world, then the keyword-only knobs a case turns
    sink: DiagnosticSink,
    world: _World,
    *,
    daily_calls: int = 100,
    clock: Callable[[], float] | None = None,
    timeout: float = 30.0,
    routes: Mapping[str, str] | None = None,
) -> FollowUpAsker:
    return FollowUpAsker(
        sink,
        prompt=_TEMPLATE,
        routes=dict.fromkeys(FOLLOW_UP_ROUTES, _ROUTE) if routes is None else routes,
        daily_calls=daily_calls,
        timeout=timeout,
        now=lambda: _AT + timedelta(minutes=5),
        clock=clock or _Clock(),
        build=world.build,
    )


def _messages(text: str = "what is on today") -> list[dict[str, Any]]:
    return [
        {"role": "system", "content": "The stage's instruction.", "name": None},
        {"role": "user", "content": text, "name": None},
    ]


def _given(
    source: DiagnosticSource = DiagnosticSource.UNDERSTANDING,
    *,
    activation_id: str = _ACTIVATION,
    at: datetime = _AT,
    **body: object,
) -> DiagnosticEntry:
    held: dict[str, object] = {"messages": _messages(), "prompt": _PROMPT}
    if source is DiagnosticSource.PLANNING:
        # ADR-0356 §13:6: planning's given entry records the work's exchange.
        held["exchange"] = {
            "instruction": "The stage's instruction.",
            "briefing": "what is on today",
            "steps": [],
        }
    held.update(body)
    return diagnostic_entry(
        activation_id, source=source, kind=DiagnosticKind.GIVEN, recorded_at=at, body=held
    )


def _returned(
    source: DiagnosticSource = DiagnosticSource.UNDERSTANDING,
    *,
    activation_id: str = _ACTIVATION,
    at: datetime = _AT,
    **body: object,
) -> DiagnosticEntry:
    held: dict[str, object] = {"reply": '{"meaning": "a question"}'}
    held.update(body)
    return diagnostic_entry(
        activation_id,
        source=source,
        kind=DiagnosticKind.RETURNED,
        recorded_at=at + timedelta(seconds=2),
        body=held,
    )


def _round_response(model_name: str) -> dict[str, Any]:
    response = ModelResponse(
        parts=[
            TextPart("Looking now."),
            ToolCallPart("web_search", {"query": "stays"}, tool_call_id="a"),
        ],
        model_name=model_name,
    )
    dumped: dict[str, Any] = ModelMessagesTypeAdapter.dump_python([response], mode="json")[0]
    return dumped


_TOOLS: Final = [
    {
        "name": "web_search",
        "description": "Search the web.",
        "parameters": {"type": "object", "properties": {"query": {"type": "string"}}},
    }
]


def _body(entry: DiagnosticEntry) -> dict[str, Any]:
    """An entry's body as plain JSON, as a line of its file holds it."""
    body: dict[str, Any] = entry.model_dump(mode="json")["body"]
    return body


async def _settled(
    sink: FakeDiagnosticSink, count: int, *, also: Callable[[], bool] | None = None
) -> tuple[DiagnosticEntry, ...]:
    """Wait until the asker has written ``count`` follow-up entries, then a little more."""
    async with asyncio.timeout(5):
        while len(sink.of(DiagnosticSource.FOLLOW_UP)) < count or (also and not also()):  # noqa: ASYNC110 — the asker exposes no signal, by design
            await asyncio.sleep(0.005)
    for _ in range(20):
        await asyncio.sleep(0)
    return sink.of(DiagnosticSource.FOLLOW_UP)


async def _quiet() -> None:
    """Let the asker's worker run whatever it would."""
    for _ in range(50):
        await asyncio.sleep(0)


async def _hand(asker: FollowUpAsker, *entries: DiagnosticEntry) -> None:
    for one in entries:
        await asker.write(one)


# --- §8:5: a sink that passes each entry on unchanged ----------------------------------


async def test_it_is_a_sink_that_passes_every_entry_on_unchanged() -> None:
    sink, world = FakeDiagnosticSink(), _World()
    asker = _asker(sink, world)
    entries = (
        diagnostic_entry(_ACTIVATION, source=DiagnosticSource.CONTROLLER, kind=DiagnosticKind.STEP),
        _given(),
        _returned(),
        diagnostic_entry(_ACTIVATION, source=DiagnosticSource.RECALL, body={"n": 1}),
    )

    await _hand(asker, *entries)
    await _settled(sink, 1)

    assert isinstance(asker, DiagnosticSink)
    passed = [one for one in sink.recorded if one.source is not DiagnosticSource.FOLLOW_UP]
    assert passed == list(entries)
    await asker.aclose()


# --- §8:4, §8:9, §8:10: a recorded completion's follow-up -------------------------------


async def test_a_recorded_completion_is_asked_and_its_answer_written_as_a_follow_up() -> None:
    sink, world = FakeDiagnosticSink(), _World()
    asker = _asker(sink, world)

    await _hand(asker, _given(), _returned())
    written = await _settled(sink, 1)

    assert len(world.sent) == 1
    sent = world.sent[0]
    assert isinstance(sent[0], ModelRequest)
    assert [type(one) for one in sent[0].parts] == [SystemPromptPart, UserPromptPart]
    assert isinstance(sent[1], ModelResponse)
    assert sent[1].text == '{"meaning": "a question"}'
    assert isinstance(sent[2], ModelRequest)
    assert [one.content for one in sent[2].parts if isinstance(one, UserPromptPart)] == [_QUESTION]
    (entry,) = written
    assert entry.activation_id == _ACTIVATION
    assert entry.kind is DiagnosticKind.RETURNED
    assert entry.recorded_at == _AT + timedelta(minutes=5)
    body = entry.model_dump(mode="json")["body"]
    assert body == {
        "follows": {"source": "understanding", "recorded_at": "2026-10-21T12:00:00Z"},
        "prompt": _PROMPT,
        "follow_up_prompt": _TEMPLATE.rendered().provenance(),
        "model": _ROUTE,
        "answer": "I had to guess the date.",
    }
    assert not sink.of(DiagnosticSource.FOLLOW_UP, DiagnosticKind.GIVEN)
    await asker.aclose()


async def test_a_round_is_asked_through_the_seam_with_each_call_closed() -> None:
    sink, world = FakeDiagnosticSink(), _World()
    asker = _asker(sink, world)
    given = _given(DiagnosticSource.PLANNING, tools=_TOOLS)
    returned = _returned(DiagnosticSource.PLANNING, reply=None, response=_round_response("world"))

    await _hand(asker, given, returned)
    (entry,) = await _settled(sink, 1)

    sent = world.sent[0]
    assert isinstance(sent[1], ModelResponse)
    assert [type(one) for one in sent[1].parts] == [TextPart, ToolCallPart]
    closing = sent[2]
    assert isinstance(closing, ModelRequest)
    returns = [one for one in closing.parts if isinstance(one, ToolReturnPart)]
    assert [(one.tool_call_id, one.content) for one in returns] == [("a", NOT_RUN)]
    assert isinstance(closing.parts[-1], UserPromptPart)
    assert closing.parts[-1].content == _QUESTION
    assert _body(entry)["answer"] == "I had to guess the date."
    assert _body(entry)["follows"]["source"] == "planning"
    await asker.aclose()


@pytest.mark.parametrize(
    ("named", "sent_to"),
    [
        ("claude-x", "anthropic:claude-x"),
        ("claude-x-20250929", "anthropic:claude-x-20250929"),
        ("another-model", "anthropic:another-model"),
        ("", "anthropic:claude-x"),
    ],
)
async def test_a_round_is_asked_of_the_model_its_response_names_through_the_routes_provider(
    named: str, sent_to: str
) -> None:
    """§8:8: the model that answered where the returned entry names one, else the route's."""
    sink, world = FakeDiagnosticSink(), _World()
    routes = dict.fromkeys(FOLLOW_UP_ROUTES, _ROUTE)
    routes["planning"] = "anthropic:claude-x"
    asker = _asker(sink, world, routes=routes)
    returned = _returned(DiagnosticSource.PLANNING, reply=None, response=_round_response(named))

    await _hand(asker, _given(DiagnosticSource.PLANNING, tools=_TOOLS), returned)
    (entry,) = await _settled(sink, 1)

    assert world.built == [sent_to]
    assert _body(entry)["model"] == sent_to
    await asker.aclose()


async def test_each_models_client_is_built_once_and_closed_with_the_asker() -> None:
    """Each spec's model is the asker's own: built at its first follow-up, closed at the end."""
    sink, world = FakeDiagnosticSink(), _World()
    asker = _asker(sink, world)

    await _hand(asker, _given(), _returned(), _given(), _returned())
    await _settled(sink, 2)
    await _hand(asker, _given(DiagnosticSource.PLANNING, tools=_TOOLS))
    await _hand(
        asker, _returned(DiagnosticSource.PLANNING, reply=None, response=_round_response("other"))
    )
    await _settled(sink, 3)

    assert world.built == [_ROUTE, "fake:other"]
    assert world.opened == 2
    assert world.closed == 0
    await asker.aclose()
    assert world.closed == 2
    await asker.aclose()
    assert world.closed == 2


async def test_a_follow_up_on_a_vendors_client_is_one_request_on_the_wire() -> None:
    """§8:15: the client's own retries are off, so a 429 is one request, recorded failed."""
    recorder = RequestRecorder(failing_status(429))
    sink = FakeDiagnosticSink()

    with network_denied():
        async with httpx.AsyncClient(transport=httpx.MockTransport(recorder)) as http_client:

            def build(spec: str) -> Model:
                client = AsyncAnthropic(
                    api_key="test-key-not-a-credential", http_client=http_client
                )
                assert client.max_retries == 2  # the vendor's default, which is turned off
                return AnthropicModel(
                    spec.partition(":")[2], provider=AnthropicProvider(anthropic_client=client)
                )

            asker = FollowUpAsker(
                sink,
                prompt=_TEMPLATE,
                routes=dict.fromkeys(FOLLOW_UP_ROUTES, "anthropic:claude-x"),
                daily_calls=10,
                timeout=30.0,
                build=build,
            )
            await _hand(asker, _given(), _returned())
            (entry,) = await _settled(sink, 1)
            await asker.aclose()

    assert len(recorder.bodies) == 1
    assert _body(entry)["failure"]["class"] == "ModelRateLimitError"


@pytest.mark.parametrize(
    ("given", "returned"),
    [
        ({"prompt": None}, {}),
        ({}, {"reply": None, "failure": {"class": "ModelError", "message": ""}}),
    ],
    ids=["no-prompt-key", "a-failure-alone"],
)
async def test_a_call_that_is_not_recorded_is_not_asked(
    given: dict[str, Any], returned: dict[str, Any]
) -> None:
    """§8:4: a given entry carrying ``prompt``, a returned one holding the response."""
    sink, world = FakeDiagnosticSink(), _World()
    asker = _asker(sink, world)
    held = _given()
    body = {**held.model_dump(mode="json")["body"], **given}
    body = {key: value for key, value in body.items() if value is not None}

    await _hand(
        asker,
        diagnostic_entry(_ACTIVATION, source=held.source, recorded_at=_AT, body=body),
        _returned(**returned),
    )
    await _quiet()

    assert world.sent == []
    assert not sink.of(DiagnosticSource.FOLLOW_UP)
    await asker.aclose()


async def test_a_digest_part_with_an_unparsable_reply_is_still_asked() -> None:
    """§8:4: the reply is the model's response, though the stage could not read it."""
    sink, world = FakeDiagnosticSink(), _World()
    asker = _asker(sink, world)
    part: dict[str, Any] = {"result": None, "question": "what", "part": 1, "parts": 1}

    await _hand(
        asker,
        _given(DiagnosticSource.DIGESTING, **part),
        _returned(DiagnosticSource.DIGESTING, reply="not json", failure="unparsable", **part),
    )
    (entry,) = await _settled(sink, 1)

    assert _body(entry)["follows"]["part"] == 1
    await asker.aclose()


# --- §8:5: pairing, and asking nothing it cannot pair unambiguously ----------------------


async def test_a_digests_parts_sent_together_are_each_paired_with_their_own() -> None:
    sink, world = FakeDiagnosticSink(), _World()
    asker = _asker(sink, world)
    first: dict[str, Any] = {"result": "r1", "question": "what", "part": 1, "parts": 2}
    second: dict[str, Any] = {**first, "part": 2}

    await _hand(
        asker,
        _given(DiagnosticSource.DIGESTING, messages=_messages("one"), **first),
        _given(DiagnosticSource.DIGESTING, messages=_messages("two"), **second),
        _returned(DiagnosticSource.DIGESTING, reply="second", dropped=[], **second),
        _returned(DiagnosticSource.DIGESTING, reply="first", dropped=[], **first),
    )
    written = await _settled(sink, 2)

    asked = {
        next(
            one.content
            for one in sent[0].parts
            if isinstance(one, UserPromptPart) and isinstance(sent[0], ModelRequest)
        ): sent[1].text
        for sent in world.sent
        if isinstance(sent[1], ModelResponse)
    }
    assert asked == {"one": "first", "two": "second"}
    assert sorted(_body(one)["follows"]["part"] for one in written) == [1, 2]
    await asker.aclose()


async def test_two_waiting_given_entries_of_one_call_are_neither_asked_about() -> None:
    """§8:5: a returned entry either could be paired with is paired with neither, nor later."""
    sink, world = FakeDiagnosticSink(), _World()
    asker = _asker(sink, world)

    with structlog.testing.capture_logs() as captured:
        await _hand(asker, _given(), _given(), _returned(), _returned(), _given(), _returned())
        await _quiet()

    assert world.sent == []
    assert [one["reason"] for one in captured if one["event"] == FOLLOW_UP_NOT_ASKED] == [
        "unpaired"
    ]
    await asker.aclose()


async def test_a_returned_entry_with_no_given_one_is_not_asked_about() -> None:
    sink, world = FakeDiagnosticSink(), _World()
    asker = _asker(sink, world)

    await _hand(asker, _returned(), _given(activation_id=_OTHER), _returned())
    await _quiet()

    assert world.sent == []
    await asker.aclose()


async def test_one_activations_call_is_never_paired_with_anothers() -> None:
    sink, world = FakeDiagnosticSink(), _World()
    asker = _asker(sink, world)

    await _hand(
        asker, _given(), _given(activation_id=_OTHER), _returned(activation_id=_OTHER), _returned()
    )
    written = await _settled(sink, 2)

    assert sorted(one.activation_id for one in written) == sorted([_ACTIVATION, _OTHER])
    await asker.aclose()


# --- §8:11: an observer call written under several activations ---------------------------


def _observed(kind: DiagnosticKind, activation_id: str, at: datetime) -> DiagnosticEntry:
    named = {"episode": f"episode-{activation_id[:4]}", "attempt_started_at": _AT.isoformat()}
    body: dict[str, object] = (
        {"stage": "scout", "messages": _messages(), "prompt": _PROMPT}
        if kind is DiagnosticKind.GIVEN
        else {"stage": "scout", "reply": '{"findings": []}'}
    )
    return diagnostic_entry(
        activation_id,
        source=DiagnosticSource.OBSERVER,
        kind=kind,
        recorded_at=at,
        body={**named, **body},
    )


async def test_an_observer_call_under_several_activations_is_asked_once_written_under_each() -> (
    None
):
    sink, world = FakeDiagnosticSink(), _World()
    asker = _asker(sink, world)
    later = _AT + timedelta(milliseconds=3)

    await _hand(
        asker,
        _observed(DiagnosticKind.GIVEN, _ACTIVATION, _AT),
        _observed(DiagnosticKind.GIVEN, _OTHER, later),
        _observed(DiagnosticKind.RETURNED, _ACTIVATION, _AT + timedelta(seconds=4)),
        _observed(DiagnosticKind.RETURNED, _OTHER, _AT + timedelta(seconds=4)),
    )
    written = await _settled(sink, 2)

    assert len(world.sent) == 1
    follows = {one.activation_id: _body(one)["follows"] for one in written}
    assert follows == {
        _ACTIVATION: {
            "source": "observer",
            "recorded_at": "2026-10-21T12:00:00Z",
            "stage": "scout",
        },
        _OTHER: {
            "source": "observer",
            "recorded_at": "2026-10-21T12:00:00.003000Z",
            "stage": "scout",
        },
    }
    await asker.aclose()


async def test_a_copy_paired_after_its_answer_came_back_is_written_without_asking_again() -> None:
    sink, world = FakeDiagnosticSink(), _World()
    asker = _asker(sink, world)

    await _hand(
        asker,
        _observed(DiagnosticKind.GIVEN, _ACTIVATION, _AT),
        _observed(DiagnosticKind.GIVEN, _OTHER, _AT),
        _observed(DiagnosticKind.RETURNED, _ACTIVATION, _AT),
    )
    await _settled(sink, 1)
    await _hand(asker, _observed(DiagnosticKind.RETURNED, _OTHER, _AT))
    written = await _settled(sink, 2)

    assert len(world.sent) == 1
    assert {one.activation_id for one in written} == {_ACTIVATION, _OTHER}
    await asker.aclose()


async def test_the_same_observer_request_after_its_call_came_back_is_another_call() -> None:
    """§8:11: a given entry after a copy's returned one is a call of its own, however soon."""
    sink, world = FakeDiagnosticSink(), _World()
    asker = _asker(sink, world)

    await _hand(
        asker,
        _observed(DiagnosticKind.GIVEN, _ACTIVATION, _AT),
        _observed(DiagnosticKind.RETURNED, _ACTIVATION, _AT),
        _observed(DiagnosticKind.GIVEN, _OTHER, _AT),
        _observed(DiagnosticKind.RETURNED, _OTHER, _AT),
    )
    await _settled(sink, 2)

    assert len(world.sent) == 2
    await asker.aclose()


async def test_the_same_request_again_under_one_activation_is_another_call() -> None:
    """A retried attempt writes its given entry again under the same activation."""
    sink, world = FakeDiagnosticSink(), _World()
    asker = _asker(sink, world)
    later = _AT + timedelta(minutes=15)

    await _hand(
        asker,
        _observed(DiagnosticKind.GIVEN, _ACTIVATION, _AT),
        _observed(DiagnosticKind.RETURNED, _ACTIVATION, _AT),
        _observed(DiagnosticKind.GIVEN, _ACTIVATION, later),
        _observed(DiagnosticKind.RETURNED, _ACTIVATION, later),
    )
    await _settled(sink, 2)

    assert len(world.sent) == 2
    await asker.aclose()


@pytest.mark.parametrize("daily_calls", [1, 100])
async def test_a_copy_whose_returned_entry_comes_back_late_is_still_the_one_call(
    daily_calls: int,
) -> None:
    """§8:11: no clock decides it, so a stalled write splits nothing, budget or none."""
    sink, world, clock = FakeDiagnosticSink(), _World(), _Clock()
    asker = _asker(sink, world, clock=clock, daily_calls=daily_calls)

    await _hand(
        asker,
        _observed(DiagnosticKind.GIVEN, _ACTIVATION, _AT),
        _observed(DiagnosticKind.GIVEN, _OTHER, _AT),
        _observed(DiagnosticKind.RETURNED, _ACTIVATION, _AT),
    )
    await _settled(sink, 1)
    clock.at += 3_600
    await _hand(asker, _observed(DiagnosticKind.RETURNED, _OTHER, _AT))
    written = await _settled(sink, 2)

    assert len(world.sent) == 1
    assert {one.activation_id for one in written} == {_ACTIVATION, _OTHER}
    await asker.aclose()


async def test_a_copy_of_a_call_the_budget_turned_away_is_not_asked_either() -> None:
    """§8:11, §8:3: the one call was not asked, so no copy of it is."""
    sink, world = FakeDiagnosticSink(), _World()
    asker = _asker(sink, world, daily_calls=0)

    with structlog.testing.capture_logs() as captured:
        await _hand(
            asker,
            _observed(DiagnosticKind.GIVEN, _ACTIVATION, _AT),
            _observed(DiagnosticKind.GIVEN, _OTHER, _AT),
            _observed(DiagnosticKind.RETURNED, _ACTIVATION, _AT),
            _observed(DiagnosticKind.RETURNED, _OTHER, _AT),
        )
        await _quiet()

    assert world.sent == []
    assert [one["reason"] for one in captured if one["event"] == FOLLOW_UP_NOT_ASKED] == ["budget"]
    await asker.aclose()


# --- §8:3: the budget --------------------------------------------------------------------


async def test_the_budget_admits_its_calls_in_any_24_hours_and_no_more() -> None:
    sink, world, clock = FakeDiagnosticSink(), _World(), _Clock()
    asker = _asker(sink, world, daily_calls=2, clock=clock)

    with structlog.testing.capture_logs() as captured:
        for _ in range(3):
            await _hand(asker, _given(), _returned())
        await _settled(sink, 2)
        clock.at += 86_400
        await _hand(asker, _given(), _returned())
        await _settled(sink, 3)

    assert len(world.sent) == 3
    assert [one["reason"] for one in captured if one["event"] == FOLLOW_UP_NOT_ASKED] == ["budget"]
    await asker.aclose()


async def test_a_budget_of_zero_asks_none() -> None:
    sink, world = FakeDiagnosticSink(), _World()
    asker = _asker(sink, world, daily_calls=0)

    await _hand(asker, _given(), _returned())
    await _quiet()

    assert world.sent == []
    await asker.aclose()


async def test_queued_follow_ups_count_against_the_budget_before_they_are_sent() -> None:
    sink, world = FakeDiagnosticSink(), _World()
    world.gate = asyncio.Event()
    asker = _asker(sink, world, daily_calls=2)

    for _ in range(4):
        await _hand(asker, _given(), _returned())
    world.gate.set()
    await _settled(sink, 2)
    await _quiet()

    assert len(world.sent) == 2
    await asker.aclose()


# --- §8:7: off the activation's path, one at a time --------------------------------------


async def test_handing_it_an_entry_returns_before_the_follow_up_is_sent() -> None:
    sink, world = FakeDiagnosticSink(), _World()
    world.gate = asyncio.Event()
    asker = _asker(sink, world)

    async with asyncio.timeout(1):
        await _hand(asker, _given(), _returned())
    await _quiet()

    assert len(world.sent) == 1
    assert not sink.of(DiagnosticSource.FOLLOW_UP)
    world.gate.set()
    await _settled(sink, 1)
    await asker.aclose()


async def test_follow_ups_are_sent_one_at_a_time() -> None:
    sink, world = FakeDiagnosticSink(), _World()
    world.gate = asyncio.Event()
    asker = _asker(sink, world)

    await _hand(asker, _given(), _returned(), _given(), _returned())
    await _quiet()

    assert len(world.sent) == 1
    world.gate.set()
    await _settled(sink, 2)
    assert len(world.sent) == 2
    await asker.aclose()


async def test_nothing_the_activation_bound_is_the_follow_ups() -> None:
    sink, world = FakeDiagnosticSink(), _World()
    asker = _asker(sink, world)

    with (
        correlated_operation(),
        diagnosed_activation(_ACTIVATION, clock=lambda: _AT),
    ):
        await _hand(asker, _given(), _returned())
    await _settled(sink, 1)

    assert world.bound == [(None, None)]
    await asker.aclose()


# --- §8:15: a failure is recorded, and nothing is retried --------------------------------


async def test_a_failed_follow_up_is_recorded_and_not_retried() -> None:
    sink, world = FakeDiagnosticSink(), _World()
    world.failure = RuntimeError("the provider fell over")
    asker = _asker(sink, world)

    await _hand(asker, _given(), _returned())
    (entry,) = await _settled(sink, 1)

    assert len(world.sent) == 1
    assert "answer" not in entry.body
    assert _body(entry)["failure"]["class"] == "ModelError"
    await asker.aclose()


async def test_an_empty_answer_is_not_repaired_by_a_second_request() -> None:
    sink, world = FakeDiagnosticSink(), _World(answer="")
    asker = _asker(sink, world)

    await _hand(asker, _given(), _returned())
    (entry,) = await _settled(sink, 1)

    assert len(world.sent) == 1
    assert "failure" in entry.body
    await asker.aclose()


async def test_a_follow_up_past_its_deadline_is_recorded_as_failed() -> None:
    sink, world = FakeDiagnosticSink(), _World()
    world.gate = asyncio.Event()
    asker = _asker(sink, world, timeout=0.05)

    await _hand(asker, _given(), _returned())
    (entry,) = await _settled(sink, 1)

    assert _body(entry)["failure"]["class"] == "TimeoutError"
    await asker.aclose()


async def test_a_cancellation_the_model_raises_of_its_own_is_a_failure_and_the_queue_goes_on() -> (
    None
):
    """A cancellation not the asker's own fails one follow-up and stops none after it."""
    sink, world = FakeDiagnosticSink(), _World()
    asker = _asker(sink, world, daily_calls=2)
    failures: list[BaseException] = [asyncio.CancelledError()]

    async def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        del messages, info
        if failures:
            raise failures.pop()
        return ModelResponse(parts=[TextPart("I had to guess.")])

    world.model.function = respond  # the world's answer, swapped

    await _hand(asker, _given(), _returned(), _given(), _returned())
    first, second = await _settled(sink, 2)

    assert _body(first)["failure"]["class"] == "CancelledError"
    assert _body(second)["answer"] == "I had to guess."
    await asker.aclose()


async def test_a_rounds_follow_up_answered_past_its_deadline_is_recorded_as_failed() -> None:
    """A model that swallows the deadline's cancellation and answers anyway answered late."""
    sink, world = FakeDiagnosticSink(), _World()

    async def late(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        del messages, info
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.sleep(10)
        return ModelResponse(parts=[TextPart("too late")])

    world.model.function = late  # the world's answer, swapped
    asker = _asker(sink, world, timeout=0.05)

    await _hand(
        asker,
        _given(DiagnosticSource.PLANNING, tools=_TOOLS),
        _returned(DiagnosticSource.PLANNING, reply=None, response=_round_response("world")),
    )
    (entry,) = await _settled(sink, 1)

    assert "answer" not in _body(entry)
    assert _body(entry)["failure"]["class"] == "TimeoutError"
    await asker.aclose()


async def test_a_follow_up_entry_that_cannot_be_written_is_logged_and_not_retried() -> None:
    written: list[DiagnosticEntry] = []

    class _Refusing:
        async def write(self, entry: DiagnosticEntry) -> None:
            if entry.source is DiagnosticSource.FOLLOW_UP:
                msg = "the disk is full"
                raise OSError(msg)
            written.append(entry)

    world = _World()
    asker = _asker(_Refusing(), world)

    with structlog.testing.capture_logs() as captured:
        await _hand(asker, _given(), _returned())
        async with asyncio.timeout(5):
            while not any(one["event"] == DIAGNOSTIC_NOT_WRITTEN for one in captured):  # noqa: ASYNC110 — no signal, by design
                await asyncio.sleep(0.005)
        await _quiet()

    dropped = [one for one in captured if one["event"] == DIAGNOSTIC_NOT_WRITTEN]
    assert [(one["source"], one["error_class"]) for one in dropped] == [("follow_up", "OSError")]
    assert len(world.sent) == 1
    assert len(written) == 2
    await asker.aclose()


async def test_a_fault_reading_an_entry_never_reaches_the_emitter() -> None:
    class _Odd:
        """A given entry whose body cannot be read as one."""

        activation_id = _ACTIVATION
        source = DiagnosticSource.UNDERSTANDING
        kind = DiagnosticKind.GIVEN

        @property
        def body(self) -> dict[str, object]:
            msg = "unreadable"
            raise RuntimeError(msg)

    passed: list[object] = []

    class _Keeping:
        async def write(self, entry: object) -> None:
            passed.append(entry)

    asker = _asker(_Keeping(), _World())
    odd = _Odd()

    with structlog.testing.capture_logs() as captured:
        await asker.write(odd)  # type: ignore[arg-type]  # an entry no emitter could build

    assert passed == [odd]
    assert [(one["event"], one["reason"]) for one in captured] == [(FOLLOW_UP_NOT_ASKED, "unread")]
    await asker.aclose()


# --- §8:16: a follow-up not sent when the hub stops is not sent --------------------------


async def test_closing_drops_the_queue_and_abandons_the_follow_up_in_flight() -> None:
    sink, world = FakeDiagnosticSink(), _World()
    world.gate = asyncio.Event()
    asker = _asker(sink, world)
    await _hand(asker, _given(), _returned(), _given(), _returned())
    await _quiet()

    await asker.aclose()
    world.gate.set()
    await _hand(asker, _given(), _returned())
    await _quiet()

    assert len(world.sent) == 1
    assert not sink.of(DiagnosticSource.FOLLOW_UP)
    assert len(sink.recorded) == 6
    await asker.aclose()


# --- construction --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("change", "error"),
    [
        ({"prompt": prompt_from(_ANOTHER, "Another prompt.")}, ValueError),
        ({"routes": {"understanding": "anthropic:claude-x"}}, ValueError),
        ({"routes": dict.fromkeys(FOLLOW_UP_ROUTES, "no-provider")}, ValueError),
        ({"daily_calls": -1}, ValueError),
        ({"daily_calls": True}, TypeError),
        ({"timeout": 0.0}, ValueError),
    ],
    ids=["prompt", "routes", "spec", "budget", "budget-bool", "timeout"],
)
def test_what_it_is_built_with_is_checked(
    change: dict[str, object], error: type[Exception]
) -> None:
    built: dict[str, Any] = {
        "prompt": _TEMPLATE,
        "routes": dict.fromkeys(FOLLOW_UP_ROUTES, _ROUTE),
        "daily_calls": 1,
        "timeout": 1.0,
        **change,
    }

    with pytest.raises(error):
        FollowUpAsker(FakeDiagnosticSink(), **built)


async def test_framings_and_placements_calls_are_asked_each_on_its_own_route() -> None:
    """ADR-0337 §8:4, §8:8, ADR-0346 §10:1: framing and placement are recorded calls.

    Each is asked about through its own route; the retired commit step's stage names no
    route, and an entry under it is not asked about.
    """
    sink, world = FakeDiagnosticSink(), _World()
    routes = {**dict.fromkeys(FOLLOW_UP_ROUTES, _ROUTE), "observer.placement": "fake:placing"}
    asker = _asker(sink, world, routes=routes)

    def step(kind: DiagnosticKind, stage: str, minutes: int) -> DiagnosticEntry:
        at = _AT + timedelta(minutes=minutes)
        named = {"episode": "episode-1", "attempt_started_at": _AT.isoformat(), "stage": stage}
        body: dict[str, object] = (
            {"messages": _messages(stage), "prompt": _PROMPT, "finding": {"id": "f1"}}
            if kind is DiagnosticKind.GIVEN
            else {"reply": "{}", "finding": "f1"}
        )
        return diagnostic_entry(
            _ACTIVATION,
            source=DiagnosticSource.OBSERVER,
            kind=kind,
            recorded_at=at,
            body={**named, **body},
        )

    await _hand(
        asker,
        step(DiagnosticKind.GIVEN, "framing", 1),
        step(DiagnosticKind.RETURNED, "framing", 1),
        step(DiagnosticKind.GIVEN, "placement", 2),
        step(DiagnosticKind.RETURNED, "placement", 2),
        step(DiagnosticKind.GIVEN, "placement", 3),
        step(DiagnosticKind.RETURNED, "placement", 3),
        step(DiagnosticKind.GIVEN, "commit", 4),
        step(DiagnosticKind.RETURNED, "commit", 4),
    )
    written = await _settled(sink, 3)

    assert [_body(one)["follows"]["stage"] for one in written] == [
        "framing",
        "placement",
        "placement",
    ]
    assert world.built.count("fake:placing") == 1, "placement's route, built once"
    await asker.aclose()
