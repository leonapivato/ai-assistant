"""The gate's form test of the synthetic prompt cases (ADR-0337 §3:6).

It reads every case under ``prompt_cases/`` and checks its form, its prompt, its flags and
its code check against what the package and the runner declare, and renders each one's
instruction from its prompt's default. It sends no model call: nothing here builds a
model, and no test in the gate sends a case to one (§3:6).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Final

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
        assert call.messages[0].role.value == "system"
        assert call.messages[0].content.strip()
        assert call.messages[1:] == call.case.messages
        assert (call.case.tools is not None) == (call.case.prompt == replay_tool.PLANNING)
