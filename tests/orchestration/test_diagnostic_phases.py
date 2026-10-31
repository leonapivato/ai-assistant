"""What recall, understanding, planning and digesting give the diagnostic record (ADR-0314 §4).

Each source writes from its own module through the sink it is handed, its given entry
before its model call or search and its returned entry once that returns or fails
(§4:1); with no sink, nothing is built and the work is unchanged (§2:1). The controller's
steps are pinned in ``test_controller.py`` and authorizing's entry in
``test_authorizer.py``; planning's thinking, which the completer writes, in
``tests/models/test_tool_calling_diagnostics.py``.

Every case binds an activation itself, as the controller does for a pass (§5:4).
"""

from __future__ import annotations

import asyncio
import json
import math
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Final

import pytest
from structured_support import structured
from understanding_support import TextAsStructured

from ai_assistant.core.diagnostics import diagnosed_activation, write_diagnostic
from ai_assistant.core.errors import MemoryStoreError, ModelError
from ai_assistant.core.reply_shapes import reply_shape_version
from ai_assistant.core.types import (
    ActivationDigest,
    ChannelIdentity,
    DiagnosticKind,
    DiagnosticSource,
    Memory,
    Message,
    OfferedTool,
    Placement,
    PlanningExchange,
    PlanningLabel,
    PlanningRound,
    ProposedActivationUnderstanding,
    RecallCue,
    ReplyFailure,
    ReplyUsage,
    Role,
    RoundResponse,
)
from ai_assistant.orchestration.digesting import (
    DIGESTING_PROMPT,
    ActivationLabels,
    DigestingStage,
    DigestReply,
)
from ai_assistant.orchestration.disclosure import BoundedAudienceSupply
from ai_assistant.orchestration.held_results import HeldResult
from ai_assistant.orchestration.planning import (
    PLANNING_PROMPT,
    PlaceWindow,
    PlanningInputs,
    PlanningStage,
)
from ai_assistant.orchestration.recall import RecallStage
from ai_assistant.orchestration.understanding import (
    UNDERSTANDING_PROMPT,
    TranscriptWindow,
    UnderstandingStage,
)
from ai_assistant.testing import (
    FakeDiagnosticSink,
    FakeMemoryStore,
    FakeModelProvider,
    FakeStoryStore,
    FakeToolCallingCompleter,
    default_prompt,
)
from ai_assistant.testing.memories import memory as memory_record
from ai_assistant.testing.memories import said_support
from ai_assistant.testing.structured import (
    DEFAULT_STRUCTURED_MODEL,
    FakeStructuredCompleter,
    ScriptedReply,
)

#: Understanding's and planning's shipped templates, as the composition root hands them on.
_UNDERSTANDING = default_prompt(UNDERSTANDING_PROMPT)
_PLANNING = default_prompt(PLANNING_PROMPT)

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

_AT: Final = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)
_ACTIVATION: Final = "3f2b8c4e-1d5a-4e7b-9c0d-2a6f8e1b7c35"
_AUDIENCE: Final = BoundedAudienceSupply(speakable_attested_sources=frozenset())
_CONVERSATION: Final = ChannelIdentity(channel_type="conversation", instance_id="c-1")
_PROPOSAL: Final = json.dumps({"understanding": "They mean the dentist."})


def _now() -> datetime:
    return _AT


def _body(entry: Any) -> Any:
    """An entry's body as the file holds it: plain JSON."""
    return entry.model_dump(mode="json")["body"]


def _fact(memory_id: str, fact: str) -> Memory:
    return memory_record(
        memory_id, fact, said_support(when=_AT, added_at=_AT), placement=Placement()
    )


# --- recall --------------------------------------------------------------------------------


async def _recall_stage(memory: FakeMemoryStore, sink: FakeDiagnosticSink | None) -> RecallStage:
    return RecallStage(
        memory=memory,
        stories=FakeStoryStore(),
        threshold=0.5,
        limit=3,
        budget=timedelta(seconds=2),
        diagnostics=sink,
    )


async def test_recall_writes_its_run_and_cues_then_each_find_and_what_it_kept() -> None:
    memory = FakeMemoryStore(now=_now)
    await memory.add(_fact("m1", "The dentist appointment is on Friday."))
    await memory.add(_fact("m2", "The garden needs water."))
    sink = FakeDiagnosticSink()
    stage = await _recall_stage(memory, sink)

    with diagnosed_activation(_ACTIVATION, clock=_now):
        recalled = await stage.recall("dentist appointment", audience=_AUDIENCE, deadline=math.inf)

    given, returned = sink.of(DiagnosticSource.RECALL)
    assert given.kind is DiagnosticKind.GIVEN
    assert _body(given) == {
        "run": "first",
        "cues": [{"text": "dentist appointment", "kinds": ["activation_input"]}],
    }
    body = _body(returned)
    assert body["outcome"] == "found"
    assert [one["id"] for one in body["kept"]] == [item.id for item in recalled.result.items]
    assert body["kept"][0]["found_by"] == ["activation_input"]
    assert {"m1"} <= {one["id"] for one in body["finds"]}
    find = next(one for one in body["finds"] if one["id"] == "m1")
    assert (find["band"], find["cue"], find["admitted"]) == (
        "asserted",
        "dentist appointment",
        True,
    )
    assert isinstance(find["score"], float)


async def test_recall_s_second_run_writes_each_cue_with_its_kinds() -> None:
    sink = FakeDiagnosticSink()
    stage = await _recall_stage(FakeMemoryStore(now=_now), sink)

    with diagnosed_activation(_ACTIVATION, clock=_now):
        await stage.recall_again(
            "the dentist",
            ("which Friday",),
            audience=_AUDIENCE,
            deadline=math.inf,
            passed_over=frozenset(),
            cap=3,
        )

    given = sink.of(DiagnosticSource.RECALL, DiagnosticKind.GIVEN)[0]
    assert _body(given) == {
        "run": "second",
        "cues": [
            {"text": "the dentist", "kinds": [RecallCue.UNDERSTOOD_MEANING.value]},
            {"text": "which Friday", "kinds": [RecallCue.UNDERSTOOD_GAP.value]},
        ],
    }
    assert _body(sink.of(DiagnosticSource.RECALL, DiagnosticKind.RETURNED)[0])["outcome"] == (
        "nothing_found"
    )


async def test_a_failed_recall_writes_its_failure() -> None:
    sink = FakeDiagnosticSink()
    stage = await _recall_stage(FakeMemoryStore(now=_now, failure="down"), sink)

    with diagnosed_activation(_ACTIVATION, clock=_now):
        await stage.recall("dentist", audience=_AUDIENCE, deadline=math.inf)

    body = _body(sink.of(DiagnosticSource.RECALL, DiagnosticKind.RETURNED)[0])
    assert body["outcome"] == "failed"
    assert body["failure"]["class"] == MemoryStoreError.__name__


async def test_a_recall_that_raises_writes_its_returned_entry_before_raising() -> None:
    sink = FakeDiagnosticSink()
    stage = await _recall_stage(FakeMemoryStore(now=_now), sink)

    with diagnosed_activation(_ACTIVATION, clock=_now), pytest.raises(TimeoutError):
        await stage.recall("dentist", audience=_AUDIENCE, deadline=0.0)

    body = _body(sink.of(DiagnosticSource.RECALL, DiagnosticKind.RETURNED)[0])
    assert body["failure"]["class"] == "TimeoutError"


# --- understanding -------------------------------------------------------------------------


async def _understand(stage: UnderstandingStage) -> None:
    await stage.understand(
        "Book the dentist.",
        channel=_CONVERSATION,
        window=TranscriptWindow(_CONVERSATION, ()),
        audience=_AUDIENCE,
        episodes=None,
        version=1,
        now=_now,
        deadline=math.inf,
    )


async def test_understanding_writes_its_rendered_request_and_the_reply() -> None:
    """ADR-0354 §7:1-§7:2: the given entry names the reply's shape and version, and the
    returned entry keeps the reply as written with the model, the mode, the finish and
    the usage the exchange holds."""
    usage = ReplyUsage(input_tokens=900, output_tokens=40, cache_read_tokens=800)
    model = FakeStructuredCompleter(
        ScriptedReply(text=_PROPOSAL, usage=usage, model="anthropic:claude-x")
    )
    sink = FakeDiagnosticSink()
    stage = UnderstandingStage(
        model=model, excerpt_chars=200, prompt=_UNDERSTANDING, diagnostics=sink
    )

    with diagnosed_activation(_ACTIVATION, clock=_now):
        await _understand(stage)

    given, returned = sink.of(DiagnosticSource.UNDERSTANDING)
    sent = model.calls[0].messages
    assert _body(given) == {
        "messages": [one.model_dump(mode="json") for one in sent],
        # ADR-0334 §8:2: which template, in which version, the system message came from;
        # ADR-0353 §8:3: and it declares no flag.
        "prompt": {
            "name": "understanding",
            "version": _UNDERSTANDING.version,
            "origin": "default",
            "flags": {},
        },
        "reply_shape": {
            "name": "ProposedActivationUnderstanding",
            "version": reply_shape_version(ProposedActivationUnderstanding),
        },
    }
    assert _body(returned) == {
        "reply": _PROPOSAL,
        "model": "anthropic:claude-x",
        "mode": "native",
        "finish_reason": "stop",
        "refusal": None,
        "refusal_category": None,
        "usage": {
            "input_tokens": 900,
            "output_tokens": 40,
            "cache_read_tokens": 800,
            "cache_write_tokens": 0,
        },
        "failure": None,
    }


async def test_understanding_s_repair_is_a_second_given_and_returned_pair() -> None:
    model = FakeStructuredCompleter.scripted("not json", _PROPOSAL)
    sink = FakeDiagnosticSink()
    stage = UnderstandingStage(
        model=model, excerpt_chars=200, prompt=_UNDERSTANDING, diagnostics=sink
    )

    with diagnosed_activation(_ACTIVATION, clock=_now):
        await _understand(stage)

    entries = sink.of(DiagnosticSource.UNDERSTANDING)
    kinds = [one.kind for one in entries]
    assert kinds == [DiagnosticKind.GIVEN, DiagnosticKind.RETURNED] * 2
    # The repair resends the system message, so its given entry names the template and
    # the reply's shape too.
    assert _body(entries[2])["prompt"] == _body(entries[0])["prompt"]
    assert _body(entries[2])["reply_shape"] == _body(entries[0])["reply_shape"]
    # ADR-0354 §7:2: written before the stage acts on the failure, its kind named.
    first = _body(sink.of(DiagnosticSource.UNDERSTANDING)[1])
    assert (first["reply"], first["failure"]) == ("not json", "invalid")


async def test_understanding_writes_the_failure_of_its_call() -> None:
    def down(_: Sequence[Message]) -> str:
        msg = "the provider is down"
        raise ModelError(msg)

    sink = FakeDiagnosticSink()
    stage = UnderstandingStage(
        model=TextAsStructured(FakeModelProvider(reply=down)),
        excerpt_chars=200,
        prompt=_UNDERSTANDING,
        diagnostics=sink,
    )

    with diagnosed_activation(_ACTIVATION, clock=_now), pytest.raises(ModelError):
        await _understand(stage)

    failure = _body(sink.of(DiagnosticSource.UNDERSTANDING, DiagnosticKind.RETURNED)[0])["failure"]
    assert failure["class"] == "ModelError"
    assert "the provider is down" in failure["message"]


# --- planning ------------------------------------------------------------------------------


class _Recorder:
    async def record(
        self,
        planning_round: PlanningRound,
        labels: tuple[PlanningLabel, ...],
        *,
        questions: object = None,
    ) -> None:
        del planning_round, labels, questions


def _inputs() -> PlanningInputs:
    return PlanningInputs(
        activation_id=_ACTIVATION,
        place=PlaceWindow(takes_message=True, description="the kitchen chat"),
        capabilities=(),
    )


def _planning(completer: Any, sink: FakeDiagnosticSink | None) -> PlanningStage:
    return PlanningStage(
        prompt=_PLANNING,
        completer=completer,
        recorder=_Recorder(),
        excerpt_chars=200,
        now=_now,
        diagnostics=sink,
    )


async def test_planning_writes_its_rendered_request_and_offered_tools_before_the_round() -> None:
    completer = FakeToolCallingCompleter(RoundResponse(text="On it."))
    sink = FakeDiagnosticSink()

    with diagnosed_activation(_ACTIVATION, clock=_now):
        await _planning(completer, sink).plan(_inputs())

    (given,) = sink.of(DiagnosticSource.PLANNING, DiagnosticKind.GIVEN)
    sent = completer.last_call
    assert _body(given) == {
        # ADR-0356 §13:6: the exchange as handed in, and beside it the same request as
        # the system and user messages it is sent as, which the replay tool reads.
        "exchange": sent.exchange.model_dump(mode="json"),
        "messages": [
            Message(role=Role.SYSTEM, content=sent.exchange.instruction).model_dump(mode="json"),
            Message(role=Role.USER, content=sent.exchange.briefing).model_dump(mode="json"),
        ],
        "tools": [one.model_dump(mode="json") for one in sent.tools],
        # ADR-0334 §8:2: the template the system message was rendered from, and ADR-0335
        # §9:1: every flag it declares, which is none (ADR-0356 §4:2).
        "prompt": {
            "name": "planning",
            "version": _PLANNING.version,
            "origin": "default",
            "flags": {},
        },
    }
    # A response came back, and the completer is the one that writes it (§5:2); this
    # fake writes none, and planning does not write one in its place.
    assert sink.of(DiagnosticSource.PLANNING, DiagnosticKind.RETURNED) == ()


async def test_where_no_response_came_back_planning_writes_the_failure() -> None:
    """§5:2: the completer wrote nothing, so planning's module writes the entry."""

    def down(_exchange: PlanningExchange, _tools: Sequence[OfferedTool]) -> RoundResponse:
        msg = "the provider is down"
        raise ModelError(msg)

    sink = FakeDiagnosticSink()

    with diagnosed_activation(_ACTIVATION, clock=_now), pytest.raises(ModelError):
        await _planning(FakeToolCallingCompleter(down), sink).plan(_inputs())

    (returned,) = sink.of(DiagnosticSource.PLANNING, DiagnosticKind.RETURNED)
    failure = _body(returned)["failure"]
    assert failure["class"] == "ModelError"
    assert "the provider is down" in failure["message"]


async def test_where_the_completer_wrote_the_response_planning_writes_no_second() -> None:
    """§5:2: a response that came back and did not read as a round is the completer's."""

    class _Writing:
        def __init__(self, sink: FakeDiagnosticSink) -> None:
            self._sink = sink

        async def respond(
            self,
            exchange: PlanningExchange,
            tools: Sequence[OfferedTool],
            *,
            model: str | None = None,
        ) -> RoundResponse:
            del exchange, tools, model
            await write_diagnostic(
                self._sink,
                DiagnosticSource.PLANNING,
                DiagnosticKind.RETURNED,
                lambda: {"response": {"parts": []}, "read_as_round": False},
            )
            msg = "not a round"
            raise ModelError(msg)

    sink = FakeDiagnosticSink()

    with diagnosed_activation(_ACTIVATION, clock=_now), pytest.raises(ModelError):
        await _planning(_Writing(sink), sink).plan(_inputs())

    (returned,) = sink.of(DiagnosticSource.PLANNING, DiagnosticKind.RETURNED)
    assert _body(returned)["read_as_round"] is False


# --- digesting -----------------------------------------------------------------------------


class _DigestRecorder:
    async def record(self, digest: ActivationDigest, labels: tuple[PlanningLabel, ...]) -> None:
        del digest, labels


class _Provider:
    def __init__(self, answer: Callable[[Sequence[Message]], str]) -> None:
        self._answer = answer
        self.calls: list[tuple[Message, ...]] = []

    async def complete(self, messages: Sequence[Message], *, model: str | None = None) -> Message:
        del model
        self.calls.append(tuple(messages))
        return Message(role=Role.ASSISTANT, content=self._answer(messages))


def _digesting(provider: Any, sink: FakeDiagnosticSink | None) -> DigestingStage:
    return DigestingStage(
        provider=structured(provider),
        recorder=_DigestRecorder(),
        part_chars=10_000,
        now=_now,
        diagnostics=sink,
        prompt=default_prompt(DIGESTING_PROMPT),
    )


_HELD: Final = HeldResult(
    result_id="result:1", round_id="r1", decision_id="d1", content="The loop closes on the 15th."
)


async def test_digesting_writes_each_part_s_prompt_its_reply_and_the_items_dropped() -> None:
    reply = json.dumps(
        {
            "evidence": [
                {"text": "closes on the 15th", "source": "D1"},
                {"text": "made up", "source": "D9"},
            ]
        }
    )
    usage = ReplyUsage(input_tokens=900, output_tokens=40, cache_read_tokens=800)
    provider = FakeStructuredCompleter(
        ScriptedReply(text=reply, usage=usage, model="anthropic:claude-sonnet-5-5")
    )
    sink = FakeDiagnosticSink()

    with diagnosed_activation(_ACTIVATION, clock=_now):
        await _digesting(provider, sink).digest_result(
            _HELD, question="when", labels=ActivationLabels(), deadline=_AT + timedelta(seconds=30)
        )

    given, returned = sink.of(DiagnosticSource.DIGESTING)
    about = {"result": "result:1", "question": "when", "part": 1, "parts": 1}
    assert _body(given) == {
        **about,
        "messages": [one.model_dump(mode="json") for one in provider.last_call.messages],
        # ADR-0335 §9:1: the prompt declares no flag, so the key records an empty set.
        "prompt": {
            "name": "digesting",
            "version": default_prompt(DIGESTING_PROMPT).version,
            "origin": "default",
            "flags": {},
        },
        # ADR-0354 §7:1: the shape's name and version.
        "reply_shape": {"name": "DigestReply", "version": reply_shape_version(DigestReply)},
    }
    # ADR-0354 §7:2: the reply as written, and what came back with it.
    assert _body(returned) == {
        **about,
        "reply": reply,
        "model": "anthropic:claude-sonnet-5-5",
        "mode": "native",
        "finish_reason": "stop",
        "refusal": None,
        "refusal_category": None,
        "usage": {
            "input_tokens": 900,
            "output_tokens": 40,
            "cache_read_tokens": 800,
            "cache_write_tokens": 0,
        },
        "dropped": [{"source": "D9", "text": "made up"}],
    }


async def test_parts_run_in_parallel_are_told_apart_however_they_finish() -> None:
    """Each part's labels start at ``D1``, so its entries name the digest and the part."""
    later_answered = asyncio.Event()

    class _Reversed:
        """Echoes which piece it read, the first piece answering last."""

        async def complete(
            self, messages: Sequence[Message], *, model: str | None = None
        ) -> Message:
            del model
            piece = json.loads(messages[-1].content)["records"][0]["part"]
            if piece.startswith("1 of"):
                await later_answered.wait()
            else:
                later_answered.set()
            evidence = [{"text": f"read {piece}", "source": "D1"}]
            return Message(role=Role.ASSISTANT, content=json.dumps({"evidence": evidence}))

    held = HeldResult(result_id="result:2", round_id="r1", decision_id="d1", content="x" * 150)
    sink = FakeDiagnosticSink()
    stage = DigestingStage(
        provider=structured(_Reversed()),
        recorder=_DigestRecorder(),
        part_chars=60,
        now=_now,
        diagnostics=sink,
        prompt=default_prompt(DIGESTING_PROMPT),
    )

    with diagnosed_activation(_ACTIVATION, clock=_now):
        await stage.digest_result(
            held, question="what", labels=ActivationLabels(), deadline=_AT + timedelta(seconds=30)
        )

    entries = [_body(one) for one in sink.of(DiagnosticSource.DIGESTING)]
    read = {
        one["part"]: json.loads(one["reply"])["evidence"][0]["text"]
        for one in entries
        if "reply" in one
    }
    shown = {
        one["part"]: json.loads(one["messages"][-1]["content"])["records"][0]["part"]
        for one in entries
        if "messages" in one
    }
    assert len(read) == len(shown) == 3
    assert {part: f"read {piece}" for part, piece in shown.items()} == read
    returned = [one["part"] for one in entries if "reply" in one]
    assert returned[-1] == 1, "the first part answered last, and is still matched"
    assert {(one["result"], one["parts"]) for one in entries} == {("result:2", 3)}


async def test_a_failed_digest_writes_the_part_s_reply_and_the_digest_s_reason() -> None:
    sink = FakeDiagnosticSink()

    with diagnosed_activation(_ACTIVATION, clock=_now):
        await _digesting(_Provider(lambda _: "not json"), sink).digest_result(
            _HELD, question="when", labels=ActivationLabels(), deadline=_AT + timedelta(seconds=30)
        )

    returned = [_body(one) for one in sink.of(DiagnosticSource.DIGESTING, DiagnosticKind.RETURNED)]
    assert returned == [
        {
            "result": "result:1",
            "question": "when",
            "part": 1,
            "parts": 1,
            "reply": "not json",
            "model": DEFAULT_STRUCTURED_MODEL,
            "mode": "native",
            "finish_reason": "stop",
            "refusal": None,
            "refusal_category": None,
            "usage": ReplyUsage().model_dump(mode="json"),
            "failure": "invalid",
            "dropped": [],
        },
        {"result": "result:1", "question": "when", "digest": "failed", "reason": "unparsable"},
    ]


async def test_a_refused_part_writes_the_refusal_and_fails_the_digest_as_raised() -> None:
    """ADR-0354 §7:2, §9:2: the refusal is recorded, then lands where a raised one does."""
    sink = FakeDiagnosticSink()
    provider = FakeStructuredCompleter(
        ScriptedReply(failure=ReplyFailure.REFUSED, refusal="I can't help with that.")
    )

    with diagnosed_activation(_ACTIVATION, clock=_now):
        await _digesting(provider, sink).digest_result(
            _HELD, question="when", labels=ActivationLabels(), deadline=_AT + timedelta(seconds=30)
        )

    part, digest = [
        _body(one) for one in sink.of(DiagnosticSource.DIGESTING, DiagnosticKind.RETURNED)
    ]
    assert (part["failure"], part["finish_reason"], part["refusal"]) == (
        "refused",
        "content_filter",
        "I can't help with that.",
    )
    assert digest == {
        "result": "result:1",
        "question": "when",
        "digest": "failed",
        "reason": "raised",
    }


# --- with the record off -------------------------------------------------------------------


async def test_with_no_sink_every_phase_writes_nothing_and_decides_the_same() -> None:
    """§2:1: off by default, nothing is built, and nothing changes."""
    memory = FakeMemoryStore(now=_now)
    await memory.add(_fact("m1", "The dentist appointment is on Friday."))
    sink = FakeDiagnosticSink()

    with diagnosed_activation(_ACTIVATION, clock=_now):
        on = await (await _recall_stage(memory, sink)).recall(
            "dentist appointment", audience=_AUDIENCE, deadline=math.inf
        )
        off = await (await _recall_stage(memory, None)).recall(
            "dentist appointment", audience=_AUDIENCE, deadline=math.inf
        )
        await _understand(
            UnderstandingStage(
                model=TextAsStructured(FakeModelProvider(reply=_PROPOSAL)),
                excerpt_chars=200,
                prompt=_UNDERSTANDING,
            )
        )
        await _planning(FakeToolCallingCompleter(RoundResponse(text="ok")), None).plan(_inputs())

    assert on == off
    assert {one.source for one in sink.recorded} == {DiagnosticSource.RECALL}
