"""The gate's form test of the synthetic prompt cases (ADR-0337 §3:6).

It reads every case under ``prompt_cases/`` and checks its form, its prompt, its flags and
its code check against what the package and the runner declare, and renders each one's
instruction from its prompt's default. It sends no model call: nothing here builds a
model, and no test in the gate sends a case to one (§3:6).
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, Final

from ai_assistant.core.types import parameter_violations

sys.path.insert(0, str(Path(__file__).parent))
from _operator_recipes import load

replay_tool = load("prompt_replay")

#: The repository's root, which holds ``prompt_cases/`` beside ``src/`` and ``tests/``.
ROOT: Final = Path(__file__).resolve().parents[2]

#: The seven failure classes reading found on 2026-10-20 and 21, each of which the seed
#: cases cover at least once (§3:7).
SEED_CLASSES: Final = frozenset(
    {
        "greeting_recap",
        "label_in_text",
        "approval_as_habit",
        "yes_without_question",
        "compound_backed_as_worded",
        "unstated_detail",
        "narrower_write_loses_fact",
    }
)

#: The classes whose property is one of §5:1's three safety-relevant ones.
SAFETY_CLASSES: Final = frozenset(
    {"approval_as_habit", "yes_without_question", "narrower_write_loses_fact"}
)


def test_the_cases_live_at_the_repository_root_outside_the_package_and_tests() -> None:
    directory = replay_tool.CASES_DIRECTORY
    assert directory == ROOT / "prompt_cases"
    assert directory.is_dir()
    assert not directory.is_relative_to(ROOT / "src")
    assert not directory.is_relative_to(ROOT / "tests")


def test_every_case_is_well_formed_against_the_package_and_the_runner() -> None:
    reading = replay_tool.read_cases(replay_tool.CASES_DIRECTORY, replay_tool.declared_prompts())

    assert reading.defects == []
    assert reading.cases


def test_the_seed_cases_cover_each_failure_class_reading_found() -> None:
    reading = replay_tool.read_cases(replay_tool.CASES_DIRECTORY, replay_tool.declared_prompts())

    assert set(replay_tool.FAILURE_CLASSES) >= SEED_CLASSES
    assert {case.guards for case in reading.cases} >= SEED_CLASSES


def test_the_safety_classes_are_the_three_and_their_cases_declare_three_samples() -> None:
    reading = replay_tool.read_cases(replay_tool.CASES_DIRECTORY, replay_tool.declared_prompts())
    declared = {name for name, one in replay_tool.FAILURE_CLASSES.items() if one.safety}

    assert declared >= SAFETY_CLASSES
    assert declared & SEED_CLASSES == SAFETY_CLASSES
    for case in reading.cases:
        if case.safety:
            assert case.samples >= replay_tool.SAFETY_SAMPLES, case.name


def test_every_case_renders_from_its_prompts_default_under_its_flags() -> None:
    declared = replay_tool.declared_prompts()
    reading = replay_tool.read_cases(replay_tool.CASES_DIRECTORY, declared)
    prompts = {case.prompt for case in reading.cases}
    versions = {one: replay_tool.suite_versions(one, {}, declared) for one in prompts}

    calls = replay_tool.plan_suite(reading.cases, versions)

    assert len(calls) == sum(case.samples for case in reading.cases)
    for call in calls:
        followed = call.case.followed
        if followed is None:
            assert call.messages[0].role.value == "system"
            assert call.messages[0].content.strip()
            assert call.messages[1:] == call.case.messages
            assert (call.case.tools is not None) == (call.case.prompt == replay_tool.PLANNING)
            continue
        # A follow-up's instruction is the request's last user message, after the
        # followed request whole and its response (§3:5).
        assert call.case.prompt == replay_tool.FOLLOW_UP
        assert call.case.flags == {}
        assert (call.case.tools is not None) == (followed.prompt == replay_tool.PLANNING)
        question = call.question if call.question is not None else call.messages[-1].content
        assert question.strip()
        assert call.messages[: len(call.case.messages)] == call.case.messages


#: An entry of a briefing's Connections, or one a report shows later (ADR-0364 §3:3, §3:10).
_CONNECTION_ENTRY: Final = re.compile(r'<connection label="(L[0-9]+)"')
#: A connection's ``L`` label, wherever it stands.
_CONNECTION_LABEL: Final = re.compile(r"\bL[0-9]+\b")
#: Any label a prompt names a thing by: a letter, then a number from 1.
_ANY_LABEL: Final = re.compile(r"\b[A-Z][1-9][0-9]*\b")
#: Who a person's words are from: a ``P`` label (ADR-0364 §4:2).
_SAID_FROM: Final = re.compile(r'<said from="([^"]*)"')
_PERSON_LABEL: Final = re.compile(r"P[1-9][0-9]*")
#: The one result that opens with no outcome: a tidy-up that started (ADR-0364 §6:1).
_TIDY_STARTED: Final = "started"


def _strings(value: object) -> list[str]:
    """Every string a JSON value holds, its keys among them, in order."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [text for key, one in value.items() for text in (key, *_strings(one))]
    if isinstance(value, list):
        return [text for one in value for text in _strings(one)]
    return []


def _planning_cases() -> list[Any]:
    reading = replay_tool.read_cases(replay_tool.CASES_DIRECTORY, replay_tool.declared_prompts())
    return [one for one in reading.cases if one.prompt == replay_tool.PLANNING]


def _shown(case: Any) -> str:
    """What a planning case's input shows: its briefing, then each report, as text."""
    texts = [case.messages[0].content]
    for step in case.steps:
        texts.append(step.report.news)
        texts.extend(text for one in step.report.results for text in _strings(json.loads(one.text)))
    return "\n".join(texts)


def test_every_planning_case_is_rendered_against_the_shipped_briefing() -> None:
    """#3603: each case is the exchange the stage renders now (ADR-0364, ADR-0337 §3:4).

    Its briefing shows Connections and no place list, and a person's words are from a ``P``
    label; every ``L`` label it or a report shows, or a recorded call names, is an entry's;
    each recorded call is to an offered tool and fits its schema; and each result opens
    with its outcome, which the result's ``outcome`` carries for the provider.
    """
    cases = _planning_cases()
    assert cases
    for case in cases:
        briefing = case.messages[0].content
        assert "## Connections" in briefing, case.name
        assert "<place " not in briefing, case.name
        shown = _shown(case)
        for writer in _SAID_FROM.findall(shown):
            assert _PERSON_LABEL.fullmatch(writer), (case.name, writer)
        entries = set(_CONNECTION_ENTRY.findall(shown))
        assert set(_CONNECTION_LABEL.findall(shown)) <= entries, case.name
        offered = {one.name: one for one in case.tools}
        for step in case.steps:
            for call in step.response.calls:
                assert call.name in offered, (case.name, call.name)
                arguments = call.model_dump(mode="json")["arguments"]
                assert not parameter_violations(offered[call.name].parameters, arguments), (
                    case.name,
                    call.name,
                )
                assert set(_CONNECTION_LABEL.findall(json.dumps(arguments))) <= entries
            for result in step.report.results:
                body = json.loads(result.text)
                assert isinstance(body, dict), case.name
                opening = next(iter(body))
                assert opening == "outcome", (case.name, opening)
                if body["outcome"] == _TIDY_STARTED:
                    assert result.outcome is None, case.name
                    continue
                assert result.outcome is not None, case.name
                assert result.outcome.value.replace("_", " ") == body["outcome"], case.name


def test_every_planning_check_is_decidable_on_its_rendered_input() -> None:
    """#3603: a check names only tools the case offers and labels its input shows."""
    for case in _planning_cases():
        offered = {one.name for one in case.tools}
        params = case.params
        named = [
            *params.get("capabilities", ()),
            *([params["capability"]] if "capability" in params else []),
        ]
        assert set(named) <= offered, (case.name, set(named) - offered)
        shown = set(_ANY_LABEL.findall(_shown(case)))
        labels = {
            label
            for key in ("value", "offer", "read", "connection")
            if isinstance(params.get(key), str)
            for label in _ANY_LABEL.findall(params[key])
        }
        assert labels <= shown, (case.name, labels - shown)
        if isinstance(params.get("connection"), str):
            # #3608 review round 2: a message the check wants must be one the stage sends.
            entry = re.search(
                rf'<connection label="{params["connection"]}"[^>]*can="([^"]*)"', _shown(case)
            )
            assert entry is not None, case.name
            assert "it takes text messages" in entry.group(1), case.name


def test_the_follow_up_has_a_seed_case() -> None:
    """§3:5: the suite holds a case of the ninth prompt once it is declared."""
    reading = replay_tool.read_cases(replay_tool.CASES_DIRECTORY, replay_tool.declared_prompts())

    assert any(case.prompt == replay_tool.FOLLOW_UP for case in reading.cases)
