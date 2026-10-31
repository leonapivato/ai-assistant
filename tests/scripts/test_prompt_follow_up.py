"""Repeated samples and the offline follow-up in ``scripts/prompt_replay.py`` (ADR-0337 §5-§7).

A replay may send each call several times (§5:4), and a replay or a suite run may ask the
follow-up question after every response it records (§7). A ``follow_up`` case holds the
followed call's request whole and its response (§3:5). The model is a ``FunctionModel``
sent to through the package's own model layer, and the follow-up's seam in ``models/``,
so no call leaves the machine and nothing contacts a hub. Every reply and every input
carries a private string nothing the tool prints may hold (ADR-0335 §5:3).
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

import pytest
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.messages import (
    ModelMessagesTypeAdapter,
    ModelRequest,
    ModelResponse,
    SystemPromptPart,
    TextPart,
    ThinkingPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel

from ai_assistant.models.follow_up import NOT_RUN

sys.path.insert(0, str(Path(__file__).parent))
from _replay_record import (
    ACT_A,
    ACT_B,
    PRIVATE,
    UNDERSTANDING_TOLD,
    Model,
    lines,
    make_copy,
    now,
    replay_tool,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from pydantic_ai.messages import ModelMessage

pytestmark = pytest.mark.integration

#: An understanding reply, as the followed call's response in a case.
MEANING: Final = json.dumps({"understanding": "find a flight " + PRIVATE})

#: Understanding's flags: none, since ADR-0353 §8:3.
UNDERSTANDING_FLAGS: Final[dict[str, bool]] = {}

WEB_SEARCH: Final = {
    "name": "web_search",
    "description": "Search the web.",
    "parameters": {"type": "object", "properties": {"query": {"type": "string"}}},
}


def _question() -> str:
    """The follow-up's default, rendered: what a run naming no file asks."""
    follow_up = replay_tool.load_follow_up("", replay_tool.declared_prompts())
    assert follow_up is not None
    question: str = follow_up.question
    return question


def _replay(copy: Path, model: Any, reports: list[str] | None = None, **options: Any) -> int:
    told = [] if reports is None else reports
    caller = model.caller() if isinstance(model, Model) else model
    status: int = asyncio.run(
        replay_tool.replay(
            replay_tool.ReplayOptions(copy=copy, model="fake:model", **options),
            report=told.append,
            caller=caller,
            now=now,
        )
    )
    return status


def _results(copy: Path, activation_id: str = ACT_A) -> list[dict[str, Any]]:
    return lines(copy / "diagnostics" / f"{activation_id}{replay_tool.REPLAY_SUFFIX}")


def _asking(request: list[ModelMessage]) -> bool:
    """Whether a request is a follow-up: it holds the model's earlier response."""
    return any(isinstance(one, ModelResponse) for one in request)


def _said(message: ModelMessage) -> list[tuple[str, object]]:
    """A message's parts, kind and content, without the instants pydantic-ai stamps."""
    return [(type(one).__name__, getattr(one, "content", None)) for one in message.parts]


def _caller(answer: Callable[[list[ModelMessage], AgentInfo], ModelResponse]) -> Any:
    return replay_tool.ModelCaller(FunctionModel(answer), timeout=10)


# --- §5:4: repeated samples in a replay ---------------------------------------------------------


def test_a_replay_sends_each_call_as_many_times_as_it_names_one_result_each(
    tmp_path: Path,
) -> None:
    copy = make_copy(tmp_path)
    model = Model()
    reports: list[str] = []

    status = _replay(copy, model, reports, sources=frozenset({"understanding"}), samples=3)

    assert status == 0
    assert model.systems == [UNDERSTANDING_TOLD] * 6
    for activation_id in (ACT_A, ACT_B):
        written = _results(copy, activation_id)
        assert [(one["body"]["sample"], one["body"]["samples"]) for one in written] == [
            (1, 3),
            (2, 3),
            (3, 3),
        ]
        assert len({one["body"]["replays"]["line"] for one in written}) == 1
    assert "6 calls to send (bound 100); 0 under stated flags" in reports
    assert "2 requests, each sent 3 times" in reports
    assert any(
        one.startswith("run ") and one.endswith(": 6 calls sent, 6 replied") for one in reports
    )


def test_one_sample_is_the_default(tmp_path: Path) -> None:
    copy = make_copy(tmp_path)

    _replay(copy, Model(), sources=frozenset({"digesting"}))

    (only,) = _results(copy)
    assert (only["body"]["sample"], only["body"]["samples"]) == (1, 1)
    assert "follow_up" not in only["body"]


def test_every_sample_counts_against_the_bound_before_anything_is_sent(tmp_path: Path) -> None:
    copy = make_copy(tmp_path)
    model = Model()
    reports: list[str] = []

    status = _replay(copy, model, reports, sources=frozenset({"understanding"}), samples=3, bound=5)

    assert status == 1
    assert model.requests == []
    assert reports[-1] == "refused: 6 calls exceed the bound of 5"


def test_a_replay_of_no_sample_is_refused() -> None:
    with pytest.raises(replay_tool.ReplayError):
        _replay(Path("unused"), Model(), samples=0)


# --- §7: the follow-up after every response a replay records -------------------------------------


def test_a_completions_follow_up_is_its_request_its_reply_then_the_question(
    tmp_path: Path,
) -> None:
    copy = make_copy(tmp_path)
    model = Model()
    reports: list[str] = []

    status = _replay(copy, model, reports, sources=frozenset({"digesting"}), follow_up="")

    assert status == 0
    called, asked = model.requests
    assert not _asking(called)
    first, reply, last = asked
    assert _said(first) == _said(called[0])
    assert isinstance(reply, ModelResponse)
    assert reply.parts == [TextPart(model.reply)]
    assert isinstance(last, ModelRequest)
    assert [type(one) for one in last.parts] == [UserPromptPart]
    assert last.parts[0].content == _question()
    (only,) = _results(copy)
    held = only["body"]["follow_up"]
    default = replay_tool.default_candidate(replay_tool.declared_prompts()["follow_up"])
    assert held == {
        "version": default.template.version,
        "origin": "default",
        "file": "ai_assistant.models/follow_up.txt",
        "question": _question(),
        "answer": model.reply,
    }
    assert only["body"]["reply"] == model.reply
    assert "2 calls to send (bound 100); 0 under stated flags" in reports
    assert any(one.startswith("1 requests, each sent 1 times, with a follow-up") for one in reports)
    assert "follow-ups: 1 sent, 1 answered" in reports
    assert not any(PRIVATE in one for one in reports)


def test_each_follow_up_carries_its_own_samples_system_message(tmp_path: Path) -> None:
    """§7:2: the candidate's instruction for the candidate's sample, the control's for its."""
    copy = make_copy(tmp_path)
    template = tmp_path / "understanding.txt"
    template.write_text("A candidate understanding instruction.")
    model = Model()

    _replay(
        copy,
        model,
        candidates=(str(template), "recorded"),
        activations=frozenset({ACT_A}),
        sources=frozenset({"understanding"}),
        samples=2,
        follow_up="",
    )

    systems = [
        next(
            part.content
            for message in request
            if isinstance(message, ModelRequest)
            for part in message.parts
            if isinstance(part, SystemPromptPart)
        )
        for request in model.requests
    ]
    candidate, control = "A candidate understanding instruction.", UNDERSTANDING_TOLD
    assert systems == [candidate] * 4 + [control] * 4
    written = _results(copy)
    assert [(one["body"]["candidate"]["origin"], one["body"]["sample"]) for one in written] == [
        ("override", 1),
        ("override", 2),
        ("recorded", 1),
        ("recorded", 2),
    ]
    assert all(one["body"]["follow_up"]["answer"] == model.reply for one in written)


def test_a_planning_rounds_follow_up_sends_its_whole_response_and_closes_each_call(
    tmp_path: Path,
) -> None:
    copy = make_copy(tmp_path)
    sent: list[tuple[list[ModelMessage], list[str]]] = []

    def answer(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        sent.append((list(messages), [one.name for one in info.function_tools]))
        if _asking(messages):
            return ModelResponse(parts=[TextPart("I had to guess the dates. " + PRIVATE)])
        return ModelResponse(
            parts=[
                ThinkingPart("weighing " + PRIVATE, signature="sig", provider_name="anthropic"),
                TextPart("Searching. " + PRIVATE),
                ToolCallPart("web_search", {"query": "stays"}, tool_call_id="a"),
                ToolCallPart("web_search", {"query": "flights"}, tool_call_id="r"),
            ]
        )

    reports: list[str] = []
    status = _replay(copy, _caller(answer), reports, sources=frozenset({"planning"}), follow_up="")

    assert status == 0
    (round_, round_tools), (asked, asked_tools) = sent
    assert asked_tools == round_tools == ["web_search"]
    first, response, closing = asked
    assert _said(first) == _said(round_[0])
    assert isinstance(response, ModelResponse)
    assert response.parts[0] == ThinkingPart(
        "weighing " + PRIVATE, signature="sig", provider_name="anthropic"
    )
    assert isinstance(closing, ModelRequest)
    assert [
        (one.tool_call_id, one.content) for one in closing.parts if isinstance(one, ToolReturnPart)
    ] == [("a", NOT_RUN), ("r", NOT_RUN)]
    assert _said(closing)[-1] == ("UserPromptPart", _question())
    (only,) = _results(copy)
    assert only["body"]["follow_up"]["answer"] == "I had to guess the dates. " + PRIVATE
    assert only["body"]["response"]["parts"][0]["part_kind"] == "thinking"
    assert not any(PRIVATE in one for one in reports)


def test_a_follow_up_that_fails_is_written_into_its_responses_result(tmp_path: Path) -> None:
    copy = make_copy(tmp_path)

    def answer(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        del info
        if _asking(messages):
            raise ModelHTTPError(status_code=429, model_name="named")
        return ModelResponse(parts=[TextPart("a reply " + PRIVATE)])

    reports: list[str] = []
    status = _replay(copy, _caller(answer), reports, sources=frozenset({"digesting"}), follow_up="")

    assert status == 0
    (only,) = _results(copy)
    assert only["body"]["reply"] == "a reply " + PRIVATE
    held = only["body"]["follow_up"]
    assert "answer" not in held
    assert held["failure"]["class"] == "ModelRateLimitError"
    assert "follow-ups: 1 sent, 0 answered" in reports
    assert "follow-ups failed: 1 (ModelRateLimitError)" in reports


class _Cut:
    """A caller whose every follow-up is cut by the run stopping, as Ctrl-C cancels it."""

    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.model_name = inner.model_name

    async def complete(self, messages: Any) -> str:
        reply: str = await self.inner.complete(messages)
        return reply

    async def complete_structured(self, messages: Any, shape: Any) -> Any:
        return await self.inner.complete_structured(messages, shape)

    async def replay_round(self, messages: Any, tools: Any) -> Any:
        return await self.inner.replay_round(messages, tools)

    async def follow_up(self, messages: Any, reply: str, question: str) -> str:
        del messages, reply, question
        raise asyncio.CancelledError

    async def follow_up_round(
        self, messages: Any, tools: Any, response: Any, question: str, steps: Any = ()
    ) -> str:
        del messages, tools, response, question, steps
        raise asyncio.CancelledError


def test_a_replay_stopped_during_a_follow_up_still_writes_the_response(tmp_path: Path) -> None:
    copy = make_copy(tmp_path)
    model = Model()

    with pytest.raises(asyncio.CancelledError):
        _replay(copy, _Cut(model.caller()), sources=frozenset({"digesting"}), follow_up="")

    (only,) = _results(copy)
    assert only["body"]["reply"] == model.reply
    assert only["body"]["follow_up"]["failure"]["class"] == "CancelledError"
    assert "answer" not in only["body"]["follow_up"]


def test_a_call_that_failed_is_not_followed_up(tmp_path: Path) -> None:
    copy = make_copy(tmp_path)
    model = Model(fail=ModelHTTPError(status_code=500, model_name="named"))
    reports: list[str] = []

    _replay(copy, model, reports, sources=frozenset({"digesting"}), follow_up="")

    assert len(model.requests) == 1
    (only,) = _results(copy)
    assert "follow_up" not in only["body"]
    assert not any(one.startswith("follow-ups:") for one in reports)


def test_follow_ups_count_against_the_bound_before_anything_is_sent(tmp_path: Path) -> None:
    copy = make_copy(tmp_path)
    model = Model()
    reports: list[str] = []

    status = _replay(
        copy, model, reports, sources=frozenset({"digesting"}), samples=2, follow_up="", bound=3
    )

    assert status == 1
    assert model.requests == []
    assert reports[-1] == "refused: 4 calls exceed the bound of 3"


def test_a_follow_up_file_is_checked_as_any_candidate(tmp_path: Path) -> None:
    declared = replay_tool.declared_prompts()
    drafts = tmp_path / "drafts"
    drafts.mkdir()
    good = drafts / "follow_up.txt"
    good.write_text("What did you guess? " + PRIVATE)
    malformed = tmp_path / "follow_up.txt"
    malformed.write_text("$if anything\n" + PRIVATE + "\n$end\n")
    other = drafts / "understanding.txt"
    other.write_text("Not a follow-up.")

    loaded = replay_tool.load_follow_up(str(good), declared)

    assert loaded is not None
    assert loaded.question == "What did you guess? " + PRIVATE
    assert loaded.candidate.origin == "override"
    assert replay_tool.load_follow_up(None, declared) is None
    with pytest.raises(replay_tool.ReplayError) as refused:
        replay_tool.load_follow_up(str(malformed), declared)
    assert PRIVATE not in str(refused.value)
    with pytest.raises(replay_tool.ReplayError, match="template of no follow-up"):
        replay_tool.load_follow_up(str(other), declared)


def test_the_command_line_names_samples_and_the_follow_up() -> None:
    named = replay_tool.parse_args(
        ["replay", "copy", "--model", "m", "--samples", "3", "--follow-up"]
    )
    filed = replay_tool.parse_args(["suite", "--model", "m", "--follow-up", "drafts/follow_up.txt"])
    neither = replay_tool.parse_args(["replay", "copy", "--model", "m"])

    assert (named.samples, named.follow_up) == (3, "")
    assert filed.follow_up == "drafts/follow_up.txt"
    assert (neither.samples, neither.follow_up) == (1, None)
    with pytest.raises(SystemExit):
        replay_tool.parse_args(["replay", "copy", "--model", "m", "--samples", "0"])


# --- §3:5: follow_up cases ----------------------------------------------------------------------


def _dumped_round() -> dict[str, Any]:
    response = ModelResponse(
        parts=[
            TextPart("Searching. " + PRIVATE),
            ToolCallPart("web_search", {"query": "stays"}, tool_call_id="a"),
        ]
    )
    dumped: dict[str, Any] = ModelMessagesTypeAdapter.dump_python([response], mode="json")[0]
    return dumped


#: A followed round's whole response, as planning's returned entry keeps it.
FOLLOWED_ROUND: Final = _dumped_round()


def _followed_round() -> dict[str, Any]:
    copied: dict[str, Any] = json.loads(json.dumps(FOLLOWED_ROUND))
    return copied


def _follow_up_input(**changes: Any) -> dict[str, Any]:
    held: dict[str, Any] = {
        "followed": {"prompt": "understanding", "flags": UNDERSTANDING_FLAGS},
        "messages": [
            {"role": "system", "content": "The followed instruction."},
            {"role": "user", "content": json.dumps({"input": PRIVATE})},
        ],
        "response": MEANING,
    }
    held.update(changes)
    return held


def _round_input(**changes: Any) -> dict[str, Any]:
    held: dict[str, Any] = {
        "followed": {"prompt": "planning"},
        "tools": [WEB_SEARCH],
        "response": _followed_round(),
        **changes,
    }
    return _follow_up_input(**held)


def _case(
    tmp_path: Path,
    held: dict[str, Any],
    *,
    name: str = "one",
    check: str = 'check = "read"\nread = "Each point names its passage."',
    samples: int = 1,
) -> Path:
    directory = tmp_path / "cases"
    folder = directory / "follow_up"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{name}.json").write_text(json.dumps(held))
    (folder / f"{name}.toml").write_text(
        'prompt = "follow_up"\nguards = "follow_up_unanchored"\ncame_from = "2026-10-21"\n'
        f'set = "development"\nsamples = {samples}\n\n[property]\n{check}\n\n'
        f'[input]\nfile = "{name}.json"\n'
    )
    return directory


def _understanding_case(directory: Path, samples: int = 2) -> None:
    folder = directory / "understanding"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "plain.toml").write_text(
        'prompt = "understanding"\nguards = "label_in_text"\ncame_from = "2026-10-21"\n'
        f'set = "development"\nsamples = {samples}\n\n'
        '[property]\ncheck = "no_label"\nfields = ["understanding"]\nlabels = ["H"]\n\n'
        "[input]\n"
        f'messages = [{{ role = "user", content = {json.dumps(json.dumps({"in": PRIVATE}))} }}]\n'
    )


def _read(directory: Path) -> Any:
    return replay_tool.read_cases(directory, replay_tool.declared_prompts())


def test_a_follow_up_case_of_a_completion_holds_the_request_whole_and_its_reply(
    tmp_path: Path,
) -> None:
    reading = _read(_case(tmp_path, _follow_up_input()))

    assert reading.defects == []
    (case,) = reading.cases
    assert case.prompt == "follow_up"
    assert case.flags == {}
    assert [one.role.value for one in case.messages] == ["system", "user"]
    assert case.tools is None
    assert case.followed == replay_tool.Followed(
        prompt="understanding", flags=UNDERSTANDING_FLAGS, response=MEANING
    )


def test_a_follow_up_case_of_a_round_holds_its_tools_and_whole_response(tmp_path: Path) -> None:
    reading = _read(_case(tmp_path, _round_input()))

    assert reading.defects == []
    (case,) = reading.cases
    assert [one.name for one in case.tools] == ["web_search"]
    assert case.followed.prompt == "planning"
    assert case.followed.flags is None
    assert case.followed.response == _followed_round()


@pytest.mark.parametrize(
    ("held", "defect"),
    [
        (_follow_up_input(followed={"prompt": "follow_up"}), "names no prompt a follow-up"),
        (_follow_up_input(followed={"prompt": "nowhere"}), "names no prompt a follow-up"),
        (_follow_up_input(followed="understanding"), "is not a table"),
        (
            _follow_up_input(followed={"prompt": "understanding", "flags": {"recalled": True}}),
            "flags are not exactly the prompt's",
        ),
        (
            _follow_up_input(messages=[{"role": "user", "content": "x"}]),
            "with its one system message",
        ),
        (
            _follow_up_input(
                messages=[
                    {"role": "system", "content": "a"},
                    {"role": "system", "content": "b"},
                    {"role": "user", "content": "x"},
                ]
            ),
            "with its one system message",
        ),
        (
            _follow_up_input(messages=[{"role": "system", "content": "a"}]),
            "ends on a message other than the user's",
        ),
        (_follow_up_input(response="  "), "reply as text"),
        (_follow_up_input(response={"parts": []}), "reply as text"),
        (_follow_up_input(tools=[WEB_SEARCH]), "holds exactly"),
        (_round_input(response=MEANING), "whole response"),
        (_round_input(response={"kind": "request", "parts": []}), "whole response"),
        ({"messages": [], "response": MEANING}, "is not a table"),
    ],
)
def test_a_malformed_follow_up_case_is_a_defect(
    tmp_path: Path, held: dict[str, Any], defect: str
) -> None:
    (found,) = _read(_case(tmp_path, held)).defects

    assert found.startswith("follow_up/one.toml: ")
    assert defect in found
    assert PRIVATE not in found


def test_a_follow_up_case_takes_a_read_property_alone(tmp_path: Path) -> None:
    check = 'check = "no_label"\nfields = ["understanding"]\nlabels = ["H"]'

    (found,) = _read(_case(tmp_path, _follow_up_input(), check=check)).defects

    assert "reads no reply of the prompt follow_up" in found


def _suite(directory: Path, caller: Any, reports: list[str], results: Path, **options: Any) -> int:
    status: int = asyncio.run(
        replay_tool.suite(
            replay_tool.SuiteOptions(
                model="fake:model", results=results, cases=directory, **options
            ),
            report=reports.append,
            caller=caller,
        )
    )
    return status


def _suite_lines(results: Path) -> list[dict[str, Any]]:
    (only,) = sorted(results.glob(replay_tool.SUITE_PREFIX + "*"))
    return [json.loads(one) for one in only.read_text().splitlines()]


def test_a_follow_up_case_of_a_completion_renders_the_question_as_the_last_user_message(
    tmp_path: Path,
) -> None:
    directory = _case(tmp_path, _follow_up_input(), samples=2)
    model = Model()
    reports: list[str] = []

    status = _suite(directory, model.caller(), reports, tmp_path / "results")

    assert status == 0
    for request in model.requests:
        first, reply, last = request
        assert isinstance(first, ModelRequest)
        assert first.parts[0] == SystemPromptPart(
            content="The followed instruction.", timestamp=first.parts[0].timestamp
        )
        assert isinstance(reply, ModelResponse)
        assert reply.parts == [TextPart(MEANING)]
        assert isinstance(last, ModelRequest)
        assert [one.content for one in last.parts] == [_question()]
    written = _suite_lines(tmp_path / "results")
    assert [one["sample"] for one in written] == [1, 2]
    assert written[0]["followed"] == {"prompt": "understanding", "flags": UNDERSTANDING_FLAGS}
    assert written[0]["reply"] == model.reply
    assert written[0]["passed"] is None
    assert "follow_up" not in written[0]
    assert not any(PRIVATE in one for one in reports)


def test_a_follow_up_case_of_a_round_goes_through_the_follow_ups_seam(tmp_path: Path) -> None:
    directory = _case(tmp_path, _round_input())
    sent: list[tuple[list[ModelMessage], list[str]]] = []

    def answer(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        sent.append((list(messages), [one.name for one in info.function_tools]))
        return ModelResponse(parts=[TextPart("It was unclear. " + PRIVATE)])

    reports: list[str] = []
    _suite(directory, _caller(answer), reports, tmp_path / "results")

    ((request, tools),) = sent
    assert tools == ["web_search"]
    _, response, closing = request
    assert isinstance(response, ModelResponse)
    assert isinstance(closing, ModelRequest)
    assert isinstance(closing.parts[0], ToolReturnPart)
    assert closing.parts[0].content == NOT_RUN
    assert closing.parts[-1].content == _question()
    (written,) = _suite_lines(tmp_path / "results")
    assert written["reply"] == "It was unclear. " + PRIVATE


def test_a_follow_up_candidate_runs_the_follow_up_cases_against_the_default(
    tmp_path: Path,
) -> None:
    directory = _case(tmp_path, _follow_up_input())
    drafts = tmp_path / "drafts"
    drafts.mkdir()
    candidate = drafts / "follow_up.txt"
    candidate.write_text("A candidate question.")
    model = Model()
    reports: list[str] = []

    _suite(directory, model.caller(), reports, tmp_path / "results", candidates=(str(candidate),))

    asked = [request[-1].parts[-1].content for request in model.requests]  # type: ignore[union-attr]
    assert asked == ["A candidate question.", _question()]
    written = _suite_lines(tmp_path / "results")
    assert [one["version"]["role"] for one in written] == ["candidate", "control"]


def test_a_suite_run_asks_the_follow_up_after_each_sample_but_a_follow_up_cases(
    tmp_path: Path,
) -> None:
    directory = _case(tmp_path, _follow_up_input())
    _understanding_case(directory, samples=2)
    model = Model()
    reports: list[str] = []

    status = _suite(directory, model.caller(), reports, tmp_path / "results", follow_up="")

    assert status == 0
    # Two samples, each followed up, and the follow_up case's one sample alone.
    assert len(model.requests) == 5
    assert "5 calls to send, samples and follow-ups included (bound 100)" in reports
    written = {(one["case"], one["sample"]): one for one in _suite_lines(tmp_path / "results")}
    assert "follow_up" not in written[("follow_up/one", 1)]
    for sample in (1, 2):
        held = written[("understanding/plain", sample)]["follow_up"]
        assert held["answer"] == model.reply
        assert held["origin"] == "default"
    assert not any(PRIVATE in one for one in reports)


def test_a_suite_stopped_during_a_follow_up_still_writes_the_sample(tmp_path: Path) -> None:
    directory = tmp_path / "cases"
    _understanding_case(directory, samples=2)
    model = Model()

    with pytest.raises(asyncio.CancelledError):
        _suite(directory, _Cut(model.caller()), [], tmp_path / "results", follow_up="")

    (only,) = _suite_lines(tmp_path / "results")
    assert (only["case"], only["sample"]) == ("understanding/plain", 1)
    assert only["reply"] == model.reply
    assert only["follow_up"]["failure"]["class"] == "CancelledError"


def test_a_suites_follow_ups_count_against_its_bound(tmp_path: Path) -> None:
    directory = tmp_path / "cases"
    _understanding_case(directory, samples=2)
    model = Model()
    reports: list[str] = []

    status = _suite(directory, model.caller(), reports, tmp_path / "results", follow_up="", bound=3)

    assert status == 1
    assert model.requests == []
    assert reports[-1] == "refused: 4 calls exceed the bound of 3"


def test_a_follow_up_cases_reply_is_judged_by_no_code() -> None:
    assert replay_tool.FOLLOW_UP not in replay_tool.REPLY_READERS
    for check in replay_tool.CODE_CHECKS.values():
        assert replay_tool.FOLLOW_UP not in check.prompts
