"""Tests for ``scripts/prompt_replay.py suite`` (ADR-0337 §3-§5).

Each test writes its own cases into a temporary directory, so the seed cases stay the
form test's (``test_prompt_cases.py``). The model is a ``FunctionModel`` sent to through
the package's own model layer, so no call leaves the machine and nothing contacts a hub.
Every case's input and every reply carries :data:`PRIVATE`, which nothing the run prints
may hold (§4:5).
"""

from __future__ import annotations

import asyncio
import json
import stat
import sys
from dataclasses import dataclass, field
from importlib.resources import files
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

import pytest
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    SystemPromptPart,
    TextPart,
    ToolCallPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel

from ai_assistant.core.types import ProposedCall, RoundResponse

sys.path.insert(0, str(Path(__file__).parent))
from _operator_recipes import load

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from pydantic_ai.messages import ModelMessage, ModelResponsePart

replay_tool = load("prompt_replay")

pytestmark = pytest.mark.integration

#: Text a case's input and a reply hold that nothing the run prints may carry (§4:5).
PRIVATE: Final = "private-words-the-run-must-never-print"

#: An understanding reply its stage reads, carrying :data:`PRIVATE`.
MEANING: Final = json.dumps({"understanding": PRIVATE})

#: The planning flags, every one declared, as a case gives them.
PLANNING_FLAGS: Final = {
    "takes_message": True,
    "story_calls": False,
    "story_reads": False,
    "approved": False,
    "candidates": False,
    "reliance": False,
    "person": False,
    "suggestions": False,
    "spawn": False,
    "scheduled": False,
    "running_work": False,
    "offers": False,
    "waiting": False,
    "earlier_work": False,
}

WEB_SEARCH: Final = {
    "name": "web_search",
    "description": "Search the web.",
    "parameters": {"type": "object", "properties": {"query": {"type": "string"}}},
}


# --- writing cases --------------------------------------------------------------------------


def _toml(value: object) -> str:
    """A value as TOML: JSON's string escapes are TOML's basic string's, and tables inline."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | str):
        return json.dumps(value)
    if isinstance(value, list):
        return "[" + ", ".join(_toml(one) for one in value) + "]"
    assert isinstance(value, dict)
    return "{ " + ", ".join(f"{key} = {_toml(one)}" for key, one in value.items()) + " }"


def _write(path: Path, case: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(f"{key} = {_toml(value)}\n" for key, value in case.items()))
    return path


def _understanding(**changes: Any) -> dict[str, Any]:
    case: dict[str, Any] = {
        "prompt": "understanding",
        "guards": "label_in_text",
        "came_from": "2026-10-21",
        "set": "development",
        "samples": 2,
        "property": {"check": "no_label", "fields": ["understanding"], "labels": ["H", "P"]},
        "input": {"messages": [{"role": "user", "content": json.dumps({"input": PRIVATE})}]},
    }
    case.update(changes)
    return case


def _planning(**changes: Any) -> dict[str, Any]:
    case: dict[str, Any] = {
        "prompt": "planning",
        "guards": "yes_without_question",
        "came_from": "#3104",
        "set": "held_out",
        "samples": 3,
        "flags": PLANNING_FLAGS,
        "property": {"check": "asks_about", "calls": ["1.1"]},
        "input": {
            "messages": [{"role": "user", "content": json.dumps({"rounds": PRIVATE})}],
            "tools": [WEB_SEARCH],
        },
    }
    case.update(changes)
    return case


def _cases(tmp_path: Path, *written: tuple[str, dict[str, Any]]) -> Path:
    directory = tmp_path / "cases"
    directory.mkdir(exist_ok=True)
    for name, case in written:
        _write(directory / name, case)
    return directory


def _defects(directory: Path) -> list[str]:
    reading = replay_tool.read_cases(directory, replay_tool.declared_prompts())
    defects: list[str] = reading.defects
    return defects


def _default_text(prompt: str) -> bytes:
    declaration = replay_tool.declared_prompts()[prompt]
    return files(declaration.package).joinpath(declaration.filename).read_bytes()


# --- the fake model ---------------------------------------------------------------------------


@dataclass
class Model:
    """A fake model: each request's system message, and a reply chosen from it."""

    reply: Callable[[str], ModelResponse] = field(
        default=lambda system: ModelResponse(parts=[TextPart(MEANING)])
    )
    fail: Exception | None = None
    systems: list[str] = field(default_factory=list)
    tools: list[list[str]] = field(default_factory=list)

    def answer(self, messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        self.tools.append(sorted(one.name for one in info.function_tools))
        system = next(
            part.content
            for message in messages
            if isinstance(message, ModelRequest)
            for part in message.parts
            if isinstance(part, SystemPromptPart)
        )
        self.systems.append(system)
        if self.fail is not None:
            raise self.fail
        return self.reply(system)

    def caller(self) -> Any:
        return replay_tool.ModelCaller(FunctionModel(self.answer), timeout=10)


def _suite(
    directory: Path,
    model: Model,
    reports: list[str],
    *,
    results: Path | None,
    **options: Any,
) -> int:
    status: int = asyncio.run(
        replay_tool.suite(
            replay_tool.SuiteOptions(
                model="fake:model", results=results, cases=directory, **options
            ),
            report=reports.append,
            caller=model.caller(),
        )
    )
    return status


def _lines(results: Path) -> list[dict[str, Any]]:
    (only,) = sorted(results.glob(replay_tool.SUITE_PREFIX + "*"))
    return [json.loads(one) for one in only.read_text().splitlines()]


def _candidate(tmp_path: Path, name: str, text: str) -> Path:
    drafts = tmp_path / "drafts"
    drafts.mkdir(exist_ok=True)
    path = drafts / name
    path.write_text(text)
    return path


# --- §3: reading and checking the cases -------------------------------------------------------


def test_a_well_formed_case_reads_whole(tmp_path: Path) -> None:
    directory = _cases(tmp_path, ("understanding/one.toml", _understanding()))

    reading = replay_tool.read_cases(directory, replay_tool.declared_prompts())

    assert reading.defects == []
    (case,) = reading.cases
    assert case.name == "understanding/one"
    # ADR-0353 §8:3, §13:4: understanding declares no flag, and its case names none.
    assert case.flags == {}
    assert case.samples == 2
    assert not case.held_out
    assert case.tools is None
    assert [one.role.value for one in case.messages] == ["user"]


def test_an_input_may_be_a_json_file_beside_the_case(tmp_path: Path) -> None:
    held = _planning()
    directory = _cases(tmp_path, ("planning/one.toml", _planning(input={"file": "one.json"})))
    (directory / "planning" / "one.json").write_text(json.dumps(held["input"]))

    reading = replay_tool.read_cases(directory, replay_tool.declared_prompts())

    assert reading.defects == []
    (case,) = reading.cases
    assert case.held_out
    assert case.tools is not None
    assert [one.name for one in case.tools] == ["web_search"]


@pytest.mark.parametrize(
    ("case", "defect"),
    [
        (_understanding(extra=1), "unknown ['extra']"),
        ({k: v for k, v in _understanding().items() if k != "samples"}, "missing ['samples']"),
        (_understanding(prompt="planning"), "a prompt other than its directory's"),
        (_understanding(guards="something_else"), "guards no failure class"),
        (_understanding(came_from="last week"), "came_from"),
        (_understanding(came_from="2026-02-30"), "came_from"),
        (_understanding(set="training"), "set is none of"),
        (_understanding(samples=0), "samples"),
        (_understanding(samples=True), "samples"),
        (_understanding(guards="approval_as_habit", samples=2), "at least 3"),
        (_understanding(flags={"recalled": False}), "undeclared ['recalled']"),
        (_understanding(flags={"x": True}), "['x']"),
        (_understanding(flags={"x": "no"}), "true and false"),
        (_understanding(property={"check": "guess"}), "no code check"),
        (_understanding(property={"check": "asks_about", "calls": ["1.1"]}), "reads no reply"),
        (
            _understanding(property={"check": "no_label", "fields": ["understanding"]}),
            "takes exactly",
        ),
        (
            _understanding(property={"check": "no_label", "fields": [], "labels": ["H"]}),
            "fields is not strings",
        ),
        (
            _understanding(property={"check": "no_label", "fields": ["a"], "labels": ["h1"]}),
            "capital letters",
        ),
        (
            _understanding(property={"check": "no_label", "fields": ["meanign"], "labels": ["H"]}),
            "names fields no understanding reply holds as text: ['meanign']",
        ),
        (
            _understanding(property={"check": "no_label", "fields": ["unclear"], "labels": ["H"]}),
            "names fields no understanding reply holds as text: ['unclear']",
        ),
        (_understanding(property={"check": "read"}), "a read property"),
        (_understanding(property={"check": "read", "read": " "}), "a read property"),
        (_understanding(property={"check": "read", "read": "x", "more": "y"}), "a read property"),
        (_understanding(input={"messages": []}), "one message or more"),
        (
            _understanding(input={"messages": [{"role": "system", "content": "told"}]}),
            "a system message",
        ),
        (
            _understanding(input={"messages": [{"role": "user", "content": "x", "at": "y"}]}),
            "keys other than",
        ),
        (
            _understanding(input={"messages": [{"role": "user", "content": "x"}], "tools": []}),
            "holds exactly ['messages']",
        ),
        (
            _understanding(
                input={
                    "messages": [
                        {"role": "user", "content": "x"},
                        {"role": "assistant", "content": "y"},
                    ]
                }
            ),
            "ends on a message other than the user's",
        ),
        (_understanding(input={"file": "../elsewhere.json"}), "beside the case"),
        (_understanding(input={"file": "absent.json"}), "is not a JSON file beside it"),
        (_understanding(input={"file": "x.json", "messages": []}), "names that file alone"),
    ],
)
def test_a_malformed_case_is_a_defect_naming_its_file(
    tmp_path: Path, case: dict[str, Any], defect: str
) -> None:
    directory = _cases(tmp_path, ("understanding/bad.toml", case))

    (found,) = _defects(directory)

    assert found.startswith("understanding/bad.toml: ")
    assert defect in found


@pytest.mark.parametrize(
    ("case", "defect"),
    [
        (
            _planning(input={"messages": [{"role": "user", "content": "x"}]}),
            "['messages', 'tools']",
        ),
        (
            _planning(property={"check": "no_label", "fields": ["meaning"], "labels": ["S"]}),
            "a planning round's text fields",
        ),
        (
            _planning(
                property={"check": "relation_in", "memory": "M1", "relations": ["contained"]}
            ),
            "reads no reply",
        ),
        (
            _planning(
                input={
                    "messages": [{"role": "user", "content": "x"}],
                    "tools": [WEB_SEARCH, WEB_SEARCH],
                }
            ),
            "names one tool twice",
        ),
        (
            _planning(
                input={
                    "messages": [{"role": "user", "content": "x"}],
                    "tools": [{**WEB_SEARCH, "name": "planning_round"}],
                }
            ),
            "which the completer adds itself",
        ),
        (
            _planning(
                input={
                    "messages": [{"role": "user", "content": "x"}],
                    "tools": [{"name": "t", "description": "d", "parameters": {"type": "array"}}],
                }
            ),
            "not an offered tool",
        ),
    ],
)
def test_a_planning_case_takes_its_tools_and_round_checks(
    tmp_path: Path, case: dict[str, Any], defect: str
) -> None:
    directory = _cases(tmp_path, ("planning/bad.toml", case))

    (found,) = _defects(directory)

    assert defect in found


def test_a_case_is_one_file_under_a_declared_prompts_directory(tmp_path: Path) -> None:
    directory = _cases(
        tmp_path,
        ("loose.toml", _understanding()),
        ("not_a_prompt/one.toml", _understanding()),
        ("understanding/one.toml", _understanding()),
    )
    (directory / "README.md").write_text("not a case")
    (directory / "understanding" / "notes.txt").write_text("x")
    (directory / "understanding" / "orphan.json").write_text("{}")
    (directory / "understanding" / "deeper").mkdir()
    (directory / "understanding" / "broken.toml").write_text("prompt = ")
    (directory / "planning").symlink_to(directory / "understanding")

    defects = _defects(directory)

    assert defects == [
        "loose.toml: a case lies under its prompt's directory",
        "not_a_prompt/: names no prompt the package declares",
        "planning: is a link, which the suite does not follow",
        "understanding/broken.toml: is not TOML (1:10)",
        "understanding/deeper: is not a regular file",
        "understanding/notes.txt: is neither a case nor a case's input",
        "understanding/orphan.json: no case names this input",
    ]


def test_a_defect_quotes_nothing_of_the_input(tmp_path: Path) -> None:
    held = {"messages": [{"role": "system", "content": PRIVATE}]}
    directory = _cases(
        tmp_path, ("understanding/bad.toml", _understanding(input={"file": "x.json"}))
    )
    (directory / "understanding" / "x.json").write_text(json.dumps(held))

    (found,) = _defects(directory)

    assert PRIVATE not in found


# --- §3:5: the code checks --------------------------------------------------------------------


def _judge(check: str, params: dict[str, object], prompt: str, text: str) -> str | None:
    reply = replay_tool.completion_reply(prompt, text)
    judged: str | None = replay_tool.CODE_CHECKS[check].judge(reply, params)
    return judged


def _round(check: str, params: dict[str, object], round_: RoundResponse | None) -> str | None:
    judged: str | None = replay_tool.CODE_CHECKS[check].judge(
        replay_tool.Reply(round=round_), params
    )
    return judged


def _meaning(**fields: object) -> str:
    return json.dumps({"understanding": "asks which venue fits", **fields})


def test_no_label_reads_the_named_fields_anywhere_in_the_reply() -> None:
    params: dict[str, object] = {"fields": ["understanding", "gap"], "labels": ["H", "P"]}
    clean = _meaning(unclear=[{"gap": "which venue", "readings": ["that one"]}], cites=["H1"])
    leaked = _meaning(unclear=[{"gap": "the one in H1", "readings": ["it"]}], cites=["H1"])
    elsewhere = _meaning(cites=["H1"])

    assert _judge("no_label", params, "understanding", clean) is None
    assert _judge("no_label", params, "understanding", leaked) == "a label stands in gap"
    assert _judge("no_label", params, "understanding", elsewhere) is None
    fenced = "```json\n" + leaked + "\n```"
    assert _judge("no_label", params, "understanding", fenced) == "a label stands in gap"


@pytest.mark.parametrize(
    ("prompt", "text"),
    [
        ("understanding", "not json"),
        ("understanding", json.dumps(["H1"])),
        ("understanding", "{}"),
        ("understanding", json.dumps({"understanding": None})),
        ("understanding", json.dumps({"understanding": "x", "unclear": [{"gap": "g"}]})),
        ("observer_scout", json.dumps({"findings": [{"rests_on": ["P1"]}]})),
        ("observer_framing", json.dumps({"memories": [{"supports": []}]})),
        ("observer_framing", json.dumps({"memories": "none"})),
        ("observer_framing", "{}"),
        ("observer_framing", json.dumps({"error": "could not frame"})),
        ("observer_framing", json.dumps({"memories": [], "nothing": " "})),
        ("observer_placement", json.dumps({"relations": "M1"})),
        ("observer_placement", json.dumps({"relations": ["M1"]})),
        ("observer_placement", json.dumps({"relations": []})),
        ("observer_placement", json.dumps({"relations": [{"relation": "restates"}]})),
        ("observer_placement", json.dumps({"relations": [{"relation": "independent"}]})),
        (
            "observer_placement",
            json.dumps({"relations": [{"memory": None, "relation": "restates", "note": "n"}]}),
        ),
        (
            "observer_placement",
            json.dumps({"relations": [{"memory": " ", "relation": "independent"}]}),
        ),
        (
            "observer_placement",
            json.dumps({"relations": [{"memory": "M1", "relation": "contained"}]}),
        ),
        (
            "observer_placement",
            json.dumps({"relations": [{"memory": "M1", "relation": "contained", "note": " "}]}),
        ),
        (
            "observer_placement",
            json.dumps({"relations": [{"memory": "M1", "relation": "alike", "note": "n"}]}),
        ),
    ],
)
def test_a_reply_its_stage_would_refuse_passes_no_check(prompt: str, text: str) -> None:
    checks = [one for one in replay_tool.CODE_CHECKS.values() if prompt in one.prompts]
    params: dict[str, dict[str, object]] = {
        "no_label": {"fields": ["understanding", "claim", "wording"], "labels": ["H"]},
        "frames_nothing": {},
        "relation_in": {"memory": "M1", "relations": ["contained"]},
        "continues_exactly": {"labels": ["R1"]},
        "continues_nothing": {},
        "belongs_to_each": {"labels": ["S1"]},
        "belongs_to_nothing": {},
        "understanding_names": {"phrases": ["x"]},
        "says_none_of": {"fields": ["understanding"], "phrases": ["x"]},
        "not_relayed": {},
        "relayed": {},
    }

    for check in checks:
        assert _judge(check.name, params[check.name], prompt, text) == (
            "the reply is not one its stage reads"
        ), check.name


@pytest.mark.parametrize(
    "relation",
    [
        {"memory": "M1", "relation": "contained"},
        {"memory": "M1", "relation": "contained", "note": " "},
        {"memory": "M1", "relation": "alike", "note": "n"},
    ],
)
def test_a_pair_the_stage_reads_as_unclear_is_read_so_by_the_check(
    relation: dict[str, str],
) -> None:
    """#3398: beside a readable pair, the stage reads an unreadable one as ``unclear``.

    And so does the check; a reply with no readable pair the stage refuses, and so every
    check fails it (above).
    """
    params: dict[str, object] = {"memory": "M1", "relations": ["contained"]}
    readable = {"memory": "M2", "relation": "restates", "note": "Same."}
    text = json.dumps({"relations": [relation, readable]})

    assert _judge("relation_in", params, "observer_placement", text) == (
        "the reply names another relation"
    )
    assert (
        _judge("relation_in", {**params, "relations": ["unclear"]}, "observer_placement", text)
        is None
    )


def test_a_key_the_stage_drops_is_not_read() -> None:
    params: dict[str, object] = {"fields": ["claim", "aside"], "labels": ["P"]}
    reply = json.dumps({"findings": [{"claim": "prefers window seats", "aside": "see P1"}]})

    assert _judge("no_label", params, "observer_scout", reply) is None


def test_no_label_may_name_a_nested_field_of_the_reply_shape() -> None:
    declared = replay_tool.reply_fields

    assert {"understanding", "gap"} <= declared("understanding")
    assert "claim" in declared("observer_scout")
    assert {"claim", "why", "reason"} <= declared("observer_scout")
    assert {"wording", "note", "nothing"} <= declared("observer_framing")
    assert {"note", "relation"} <= declared("observer_placement")
    assert "findings" not in declared("observer_scout")
    assert {"unclear", "readings", "cites", "meaning"}.isdisjoint(declared("understanding"))
    assert {"supports", "memories"}.isdisjoint(declared("observer_framing"))


def test_no_label_takes_a_label_as_a_whole_word_alone() -> None:
    params: dict[str, object] = {"fields": ["claim"], "labels": ["P", "M"]}

    def scouted(claim: str) -> str:
        return json.dumps({"findings": [{"claim": claim, "rests_on": ["P1"]}]})

    for text in ("MP3 player", "H2O", "uses P", "PM2.5 levels"):
        assert _judge("no_label", params, "observer_scout", scouted(text)) is None, text
    for text in ("as P2 says", "(M1)", "P10."):
        assert _judge("no_label", params, "observer_scout", scouted(text)) is not None, text


def test_no_label_reads_a_rounds_message_and_notes() -> None:
    noted = RoundResponse(text="Booked S1", notes="see S1")

    assert _round("no_label", {"fields": ["notes"], "labels": ["S"]}, noted) == (
        "a label stands in notes"
    )
    assert _round("no_label", {"fields": ["message"], "labels": ["S"]}, noted) == (
        "a label stands in message"
    )
    assert _round("no_label", {"fields": ["notes"], "labels": ["S"]}, RoundResponse(text="hi")) is (
        None
    )
    assert _round("no_label", {"fields": ["notes"], "labels": ["S"]}, None) == (
        "the reply is not one its stage reads"
    )


def test_asks_about_needs_a_message_and_every_call_named() -> None:
    params: dict[str, object] = {"calls": ["1.1"]}

    assert _round("asks_about", params, RoundResponse(text="Shall I?", asks=("1.1",))) is None
    assert _round("asks_about", params, RoundResponse(text="", asks=("1.1",))) == (
        "the round writes no message"
    )
    assert _round("asks_about", params, RoundResponse(text="It waits for your yes.")) == (
        "the round's asks leave out 1 of the calls that need a yes"
    )
    assert _round("asks_about", params, None) == "the response reads as no round"


def test_the_framing_check_reads_whether_any_memory_is_kept() -> None:
    nothing = json.dumps({"memories": [], "nothing": "One choice is no habit."})
    kept = json.dumps({"memories": [{"wording": "The user books ahead."}]})

    assert _judge("frames_nothing", {}, "observer_framing", nothing) is None
    assert _judge("frames_nothing", {}, "observer_framing", kept) == "the reply frames a memory"


def test_the_placement_check_reads_the_relation_named_for_the_memory() -> None:
    params: dict[str, object] = {"memory": "M1", "relations": ["contained", "supports"]}

    def placed(*relations: tuple[str, str]) -> str:
        return json.dumps(
            {"relations": [{"memory": one, "relation": two, "note": "n"} for one, two in relations]}
        )

    assert _judge("relation_in", params, "observer_placement", placed(("M1", "contained"))) is None
    assert _judge(
        "relation_in", params, "observer_placement", placed(("M1", "no_longer_true"))
    ) == ("the reply names another relation")
    assert _judge("relation_in", params, "observer_placement", placed(("M2", "contained"))) == (
        "the reply does not name the memory once"
    )
    assert _judge(
        "relation_in", params, "observer_placement", placed(("M1", "contained"), ("M1", "supports"))
    ) == ("the reply does not name the memory once")


# --- §4, §5: running the suite ------------------------------------------------------------------


def test_each_case_is_sent_for_each_sample_under_the_candidate_and_the_control(
    tmp_path: Path,
) -> None:
    directory = _cases(tmp_path, ("understanding/one.toml", _understanding()))
    candidate = _candidate(tmp_path, "understanding.txt", "Candidate understanding.\n")
    model = Model()
    reports: list[str] = []
    results = tmp_path / "results"

    status = _suite(directory, model, reports, results=results, candidates=(str(candidate),))

    assert status == 0
    control = replay_tool.default_candidate(replay_tool.declared_prompts()["understanding"])
    rendered = control.template.render(flags={})
    assert model.systems == ["Candidate understanding."] * 2 + [rendered] * 2
    lines = _lines(results)
    assert [(one["version"]["role"], one["sample"]) for one in lines] == [
        ("candidate", 1),
        ("candidate", 2),
        ("control", 1),
        ("control", 2),
    ]
    first = lines[0]
    assert first["case"] == "understanding/one"
    assert first["set"] == "development"
    assert first["guards"] == "label_in_text"
    assert first["samples"] == 2
    assert first["check"] == "no_label"
    assert first["passed"] is True
    assert first["reason"] is None
    assert first["reply"] == MEANING
    assert first["version"]["origin"] == "override"
    assert lines[2]["version"]["origin"] == "default"
    assert lines[2]["version"]["version"] == control.template.version
    assert (
        "understanding/one [development, label_in_text]: no_label passed: candidate 2 of 2, "
        "control 2 of 2; at least the control's; every sample passed"
    ) in reports
    assert not any(PRIVATE in one for one in reports)


def test_the_results_are_owner_only_in_the_directory_the_run_names(tmp_path: Path) -> None:
    directory = _cases(tmp_path, ("understanding/one.toml", _understanding()))
    results = tmp_path / "results"

    _suite(directory, Model(), [], results=results)

    assert stat.S_IMODE(results.stat().st_mode) == 0o700
    (written,) = results.iterdir()
    assert written.name.startswith(replay_tool.SUITE_PREFIX)
    assert written.name.endswith(".jsonl")
    assert stat.S_IMODE(written.stat().st_mode) == 0o600


def test_with_no_candidate_each_case_is_sent_under_its_default_alone(tmp_path: Path) -> None:
    directory = _cases(tmp_path, ("understanding/one.toml", _understanding()))
    model = Model()
    reports: list[str] = []

    _suite(directory, model, reports, results=tmp_path / "results")

    assert len(model.systems) == 2
    assert {one["version"]["role"] for one in _lines(tmp_path / "results")} == {"default"}
    assert any("default 2 of 2" in one for one in reports)


def test_a_candidate_that_is_the_default_sends_no_control(tmp_path: Path) -> None:
    directory = _cases(tmp_path, ("understanding/one.toml", _understanding()))
    candidate = _candidate(tmp_path, "understanding.txt", _default_text("understanding").decode())
    model = Model()
    reports: list[str] = []

    _suite(directory, model, reports, results=tmp_path / "results", candidates=(str(candidate),))

    assert len(model.systems) == 2
    assert any(one.endswith("the default itself, so no control") for one in reports)
    assert {one["version"]["role"] for one in _lines(tmp_path / "results")} == {"candidate"}


def test_a_candidate_runs_its_prompts_cases_alone(tmp_path: Path) -> None:
    directory = _cases(
        tmp_path,
        ("understanding/one.toml", _understanding()),
        ("planning/one.toml", _planning()),
    )
    candidate = _candidate(tmp_path, "understanding.txt", "Candidate.\n")
    model = Model()
    reports: list[str] = []

    _suite(directory, model, reports, results=tmp_path / "results", candidates=(str(candidate),))

    assert {one["prompt"] for one in _lines(tmp_path / "results")} == {"understanding"}
    assert reports[0] == "1 cases of 1 prompts (1 development, 0 held out)"


def test_a_planning_case_is_sent_as_a_round_with_its_tools_and_its_asks_read(
    tmp_path: Path,
) -> None:
    directory = _cases(tmp_path, ("planning/one.toml", _planning(samples=3)))
    answers: Iterator[list[ModelResponsePart]] = iter(
        [
            [
                TextPart("Shall I book it? " + PRIVATE),
                ToolCallPart("planning_round", {"asks": ["1.1"]}),
            ],
            [TextPart("It waits for your yes. " + PRIVATE)],
            [TextPart("Shall I book it?"), ToolCallPart("planning_round", "not json")],
        ]
    )
    model = Model(reply=lambda system: ModelResponse(parts=next(answers)))
    reports: list[str] = []

    _suite(directory, model, reports, results=tmp_path / "results")

    assert model.tools == [["planning_round", "web_search"]] * 3
    lines = _lines(tmp_path / "results")
    assert [one["passed"] for one in lines] == [True, False, False]
    assert lines[1]["reason"] == "the round's asks leave out 1 of the calls that need a yes"
    assert lines[2]["read_as_round"] is False
    assert lines[2]["reason"] == "the response reads as no round"
    assert lines[0]["response"]["parts"][0]["content"].endswith(PRIVATE)
    assert any(
        one.startswith(
            "planning/one [held_out, yes_without_question]: asks_about passed: default 1 of 3"
        )
        for one in reports
    )
    assert not any(PRIVATE in one for one in reports)


def test_a_read_case_is_recorded_for_reading_and_judged_by_no_code(tmp_path: Path) -> None:
    read = {"check": "read", "read": "Greets back, recaps nothing."}
    directory = _cases(
        tmp_path, ("understanding/one.toml", _understanding(guards="greeting_recap", property=read))
    )
    reports: list[str] = []

    _suite(directory, Model(), reports, results=tmp_path / "results")

    lines = _lines(tmp_path / "results")
    assert [one["passed"] for one in lines] == [None, None]
    assert lines[0]["read"] == "Greets back, recaps nothing."
    assert (
        "understanding/one [development, greeting_recap]: to be read: samples sent: default 2"
        in reports
    )
    assert reports[-2] == "0 cases checked by code, 1 to be read"


def test_the_report_says_where_the_candidate_passes_fewer_samples_than_the_control(
    tmp_path: Path,
) -> None:
    directory = _cases(tmp_path, ("understanding/one.toml", _understanding()))
    candidate = _candidate(tmp_path, "understanding.txt", "Candidate.\n")

    def reply(system: str) -> ModelResponse:
        meaning = "the one in H1" if system == "Candidate." else "the venue"
        reading = {"understanding": meaning}
        return ModelResponse(parts=[TextPart(json.dumps(reading))])

    reports: list[str] = []

    _suite(
        directory,
        Model(reply=reply),
        reports,
        results=tmp_path / "results",
        candidates=(str(candidate),),
    )

    assert (
        "understanding/one [development, label_in_text]: no_label passed: candidate 0 of 2, "
        "control 2 of 2; fewer than the control's; not every sample passed"
    ) in reports
    assert reports[-2] == (
        "1 cases checked by code, 0 to be read; the candidate passes fewer samples than the "
        "control on understanding/one"
    )


def test_a_failed_call_is_recorded_and_counted_as_no_pass(tmp_path: Path) -> None:
    directory = _cases(tmp_path, ("understanding/one.toml", _understanding()))
    reports: list[str] = []

    status = _suite(
        directory, Model(fail=RuntimeError(PRIVATE)), reports, results=tmp_path / "results"
    )

    assert status == 0
    lines = _lines(tmp_path / "results")
    assert [one["passed"] for one in lines] == [False, False]
    assert lines[0]["reason"] == "the call failed"
    assert lines[0]["failure"]["class"]
    assert any("default 0 of 2" in one and "; failed: 2 (" in one for one in reports)
    assert not any(PRIVATE in one for one in reports)


def test_every_sample_counts_against_the_bound_before_anything_is_sent(tmp_path: Path) -> None:
    directory = _cases(tmp_path, ("understanding/one.toml", _understanding(samples=3)))
    candidate = _candidate(tmp_path, "understanding.txt", "Candidate.\n")
    model = Model()
    reports: list[str] = []

    status = _suite(
        directory,
        model,
        reports,
        results=tmp_path / "results",
        candidates=(str(candidate),),
        bound=5,
    )

    assert status == 1
    assert model.systems == []
    assert not (tmp_path / "results").exists()
    assert reports[-1] == "refused: 6 calls exceed the bound of 5"


def test_the_bound_is_counted_from_the_samples_before_any_call_is_built(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory = _cases(tmp_path, ("understanding/one.toml", _understanding(samples=10**9)))
    planned: list[object] = []

    def plan(*args: object) -> list[object]:
        planned.append(args)
        return []

    monkeypatch.setattr(replay_tool, "plan_suite", plan)
    reports: list[str] = []

    status = _suite(directory, Model(), reports, results=None, count_only=True)

    assert status == 1
    assert planned == []
    assert reports[-1] == "refused: 1000000000 calls exceed the bound of 100"


def test_a_reply_a_check_cannot_read_fails_its_sample_and_the_run_goes_on(
    tmp_path: Path,
) -> None:
    case = _understanding(
        prompt="observer_placement",
        guards="narrower_write_loses_fact",
        samples=3,
        flags={},
        property={"check": "relation_in", "memory": "M1", "relations": ["contained"]},
    )
    directory = _cases(tmp_path, ("observer_placement/one.toml", case))
    replies = iter(
        [
            {"relations": "M1"},
            {"relations": [{"memory": "M1"}]},
            {"relations": [{"memory": "M1", "relation": "contained", "note": "Part of it."}]},
        ]
    )
    model = Model(reply=lambda system: ModelResponse(parts=[TextPart(json.dumps(next(replies)))]))
    reports: list[str] = []

    status = _suite(directory, model, reports, results=tmp_path / "results")

    assert status == 0
    lines = _lines(tmp_path / "results")
    assert [one["passed"] for one in lines] == [False, False, True]
    assert lines[0]["reason"] == "the reply is not one its stage reads"
    assert any("relation_in passed: default 1 of 3" in one for one in reports)


def test_a_check_that_raises_fails_its_sample_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory = _cases(tmp_path, ("understanding/one.toml", _understanding()))

    def broken(reply: object, params: object) -> str | None:
        raise RecursionError

    check = replay_tool.CODE_CHECKS["no_label"]
    monkeypatch.setitem(
        replay_tool.CODE_CHECKS,
        "no_label",
        replay_tool.CodeCheck(check.name, check.what, check.prompts, check.params, broken),
    )

    _suite(directory, Model(), [], results=tmp_path / "results")

    lines = _lines(tmp_path / "results")
    assert [one["reason"] for one in lines] == [
        "the check could not read the reply (RecursionError)"
    ] * 2


def test_count_sends_nothing_and_needs_no_results_directory(tmp_path: Path) -> None:
    directory = _cases(tmp_path, ("understanding/one.toml", _understanding()))
    model = Model()
    reports: list[str] = []

    status = _suite(directory, model, reports, results=None, count_only=True)

    assert status == 0
    assert model.systems == []
    assert reports[-1] == "2 calls to send, samples included (bound 100)"


def test_a_run_that_sends_names_its_results_directory(tmp_path: Path) -> None:
    directory = _cases(tmp_path, ("understanding/one.toml", _understanding()))

    with pytest.raises(replay_tool.ReplayError, match="--results"):
        _suite(directory, Model(), [], results=None)


@pytest.mark.parametrize(
    ("options", "refusal"),
    [
        ({"candidates": ("recorded",)}, "a candidate is a template file"),
        ({"names": frozenset({"understanding/absent"})}, "no case is named"),
        ({"prompts": frozenset({"absent"})}, "no prompt the package declares"),
    ],
)
def test_a_run_is_refused_before_it_sends(
    tmp_path: Path, options: dict[str, Any], refusal: str
) -> None:
    directory = _cases(tmp_path, ("understanding/one.toml", _understanding()))
    model = Model()

    with pytest.raises(replay_tool.ReplayError, match=refusal):
        _suite(directory, model, [], results=tmp_path / "results", **options)

    assert model.systems == []


def test_two_candidates_of_one_prompt_are_refused(tmp_path: Path) -> None:
    directory = _cases(tmp_path, ("understanding/one.toml", _understanding()))
    first = _candidate(tmp_path, "understanding.txt", "One.\n")
    second = tmp_path / "other" / "understanding.txt"
    second.parent.mkdir()
    second.write_text("Two.\n")

    with pytest.raises(replay_tool.ReplayError, match="two candidates of the prompt understanding"):
        _suite(directory, Model(), [], results=None, candidates=(str(first), str(second)))


def test_a_malformed_case_refuses_the_run_before_it_sends(tmp_path: Path) -> None:
    directory = _cases(
        tmp_path,
        ("understanding/one.toml", _understanding()),
        ("understanding/bad.toml", _understanding(samples=0)),
    )
    model = Model()

    with pytest.raises(replay_tool.ReplayError, match="1 defects in the cases: understanding/bad"):
        _suite(directory, model, [], results=tmp_path / "results")

    assert model.systems == []


def test_a_case_and_a_prompt_narrow_the_run(tmp_path: Path) -> None:
    directory = _cases(
        tmp_path,
        ("understanding/one.toml", _understanding()),
        ("understanding/two.toml", _understanding()),
        ("planning/one.toml", _planning()),
    )
    reports: list[str] = []

    _suite(
        directory,
        Model(),
        reports,
        results=None,
        count_only=True,
        names=frozenset({"understanding/two"}),
    )
    _suite(
        directory, Model(), reports, results=None, count_only=True, prompts=frozenset({"planning"})
    )

    assert reports[0] == "1 cases of 1 prompts (1 development, 0 held out)"
    assert reports[2] == "2 calls to send, samples included (bound 100)"
    assert reports[3] == "1 cases of 1 prompts (0 development, 1 held out)"
    assert reports[5] == "3 calls to send, samples included (bound 100)"


def test_the_command_line_runs_the_suite(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    directory = _cases(tmp_path, ("understanding/one.toml", _understanding()))

    status = replay_tool.main(
        ["suite", "--model", "test", "--cases", str(directory), "--count", "--bound", "7"]
    )

    assert status == 0
    printed = capsys.readouterr().out
    assert "prompt_replay: 2 calls to send, samples included (bound 7)" in printed


def test_the_command_line_prints_a_refusal(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    directory = _cases(tmp_path, ("understanding/one.toml", _understanding(samples=0)))

    status = replay_tool.main(["suite", "--model", "test", "--cases", str(directory), "--count"])

    assert status == 1
    assert "prompt_replay: refused: 1 defects in the cases" in capsys.readouterr().out


# --- ADR-0349 §7:3, §7:20, §4:6: the checks on running work -----------------------------


def test_continues_exactly_reads_the_labels_as_the_stage_does() -> None:
    """The reply names exactly the R labels the case names, in any order."""
    params: dict[str, object] = {"labels": ["R1", "R2"]}
    assert (
        _judge("continues_exactly", params, "understanding", _meaning(meant_for=["R2", "R1"]))
        is None
    )
    assert (
        _judge("continues_exactly", params, "understanding", _meaning(meant_for=["R1"])) is not None
    )
    assert _judge("continues_exactly", params, "understanding", _meaning()) is not None
    assert (
        _judge("continues_exactly", params, "understanding", _meaning(meant_for="R1"))
        == "the reply is not one its stage reads"
    ), "the old shape, one label, is no reply the stage reads"


def test_continues_nothing_passes_only_an_empty_list() -> None:
    assert _judge("continues_nothing", {}, "understanding", _meaning(meant_for=[])) is None
    assert _judge("continues_nothing", {}, "understanding", _meaning()) is None
    assert _judge("continues_nothing", {}, "understanding", _meaning(meant_for=["R1"])) is not None


@pytest.mark.parametrize(("finish", "failure"), [("length", "cut"), ("content_filter", "refused")])
def test_a_structured_failure_passes_no_check_whatever_its_text_holds(
    tmp_path: Path, finish: str, failure: str
) -> None:
    """ADR-0354 §8:3, §8:4, §8:6: a case is scored on the value the seam read, so a reply
    the stage would repair or refuse passes nothing, though its text would read."""
    text = json.dumps({"understanding": "A note to self.", "relayed": False})
    model = Model(
        reply=lambda _system: ModelResponse(parts=[TextPart(text)], finish_reason=finish)  # type: ignore[arg-type]  # a finish reason in pydantic-ai's vocabulary
    )
    directory = _cases(
        tmp_path, ("understanding/one.toml", _understanding(property={"check": "not_relayed"}))
    )
    results = tmp_path / "results"

    _suite(directory, model, [], results=results)

    lines = _lines(results)
    assert [one["passed"] for one in lines] == [False, False]
    assert [one["reason"] for one in lines] == ["the reply is not one its stage reads"] * 2
    assert {one["structured"]["failure"] for one in lines} == {failure}


# --- ADR-0353 §13:4: the checks of the probe stimuli and the controls -------------------


def test_belongs_to_each_passes_where_every_named_label_is_linked() -> None:
    params: dict[str, object] = {"labels": ["S1"]}
    assert (
        _judge("belongs_to_each", params, "understanding", _meaning(belongs_to=["P2", "S1"]))
        is None
    )
    assert _judge("belongs_to_each", params, "understanding", _meaning(belongs_to=["P2"])) == (
        "the reply's belongs_to leaves out 1 of the named labels"
    )
    assert _judge("belongs_to_each", params, "understanding", _meaning()) is not None


def test_belongs_to_nothing_passes_only_an_empty_list() -> None:
    assert _judge("belongs_to_nothing", {}, "understanding", _meaning()) is None
    assert _judge("belongs_to_nothing", {}, "understanding", _meaning(belongs_to=["S1"])) == (
        "the reply links the stimulus to a matter"
    )


def test_understanding_names_reads_the_understanding_in_any_case() -> None:
    params: dict[str, object] = {"phrases": ["27 October"]}
    said = json.dumps({"understanding": "A reminder at 9 am on Tuesday 27 october 2026."})
    assert _judge("understanding_names", params, "understanding", said) is None
    unsaid = json.dumps({"understanding": "A reminder at 9 tomorrow."})
    assert _judge("understanding_names", params, "understanding", unsaid) == (
        "the understanding leaves out 1 of the named phrases"
    )


def test_says_none_of_reads_each_named_field_where_a_word_begins() -> None:
    params: dict[str, object] = {"fields": ["understanding", "readings"], "phrases": ["suggest"]}
    clean = _meaning(unclear=[{"gap": "which", "readings": ["the cake came early"]}])
    advice = _meaning(unclear=[{"gap": "which", "readings": ["Suggests telling Maren"]}])
    inside = json.dumps({"understanding": "Autosuggestion is not advice."})
    assert _judge("says_none_of", params, "understanding", clean) is None
    assert _judge("says_none_of", params, "understanding", advice) == (
        "a named phrase stands in readings"
    )
    assert _judge("says_none_of", params, "understanding", inside) is None


def test_not_relayed_passes_only_where_relayed_is_false() -> None:
    assert _judge("not_relayed", {}, "understanding", _meaning()) is None
    assert _judge("not_relayed", {}, "understanding", _meaning(relayed=False)) is None
    assert _judge("not_relayed", {}, "understanding", _meaning(relayed=True)) == (
        "the reply marks the stimulus relayed"
    )


def test_relayed_passes_only_where_relayed_is_true() -> None:
    assert _judge("relayed", {}, "understanding", _meaning(relayed=True)) is None
    for unmarked in (_meaning(), _meaning(relayed=False)):
        assert _judge("relayed", {}, "understanding", unmarked) == (
            "the reply leaves the stimulus unmarked"
        )


def test_says_none_of_refuses_a_field_no_reply_holds_as_text(tmp_path: Path) -> None:
    case = _understanding(
        property={"check": "says_none_of", "fields": ["unclear"], "phrases": ["x"]}
    )
    directory = _cases(tmp_path, ("understanding/bad.toml", case))

    (found,) = _defects(directory)

    assert "names fields no understanding reply holds as text: ['unclear']" in found


def _calls(*calls: tuple[str, dict[str, object]]) -> RoundResponse:
    return RoundResponse(
        calls=tuple(
            ProposedCall(call_id=f"c{n}", name=name, arguments=arguments)  # type: ignore[arg-type]  # JSON values
            for n, (name, arguments) in enumerate(calls, 1)
        )
    )


def test_proposes_and_answers_offer_read_the_rounds_calls() -> None:
    """Each names its target: a call naming another label, or none, fails."""
    stopping: dict[str, object] = {
        "capability": "stop_activation",
        "argument": "activation",
        "value": "E1",
    }
    assert _round("proposes", stopping, _calls(("stop_activation", {"activation": "E1"}))) is None
    assert (
        _round("proposes", stopping, _calls(("stop_activation", {"activation": "E9"}))) is not None
    )
    assert _round("proposes", stopping, _calls(("stop_activation", {}))) is not None
    assert _round("proposes", stopping, _calls()) is not None
    assert _round("proposes", stopping, None) is not None
    take = _calls(("answer_offer", {"offer": "E1", "take": True}))
    decline = _calls(("answer_offer", {"offer": "E1", "take": False, "reason": "sent"}))
    elsewhere = _calls(("answer_offer", {"offer": "E9", "take": True}))
    assert _round("answers_offer", {"answer": "take", "offer": "E1"}, take) is None
    assert _round("answers_offer", {"answer": "take", "offer": "E1"}, decline) is not None
    assert _round("answers_offer", {"answer": "take", "offer": "E1"}, elsewhere) is not None
    assert _round("answers_offer", {"answer": "decline", "offer": "E1"}, decline) is None
    assert _round("answers_offer", {"answer": "decline", "offer": "E1"}, _calls()) is not None
