"""The prompts as the composition root reads them at start (ADR-0334 §3, §5, §8:3).

Each shipped default renders under every combination of its flags (§4:4); an override is
read only where ``prompt_overrides`` is on, and every malformed or unsafe one refuses
the start, naming the file and its defect and never its text (§5:1, §5:2). The cases
read a temporary data directory and open no store, save the one that builds an engine.
"""

from __future__ import annotations

import errno
import hashlib
import os
from importlib.resources import files
from pathlib import Path

import pytest
import structlog
from hatchling.builders.wheel import WheelBuilder

from ai_assistant.app import build_engine
from ai_assistant.app.composition import PROMPTS, read_prompts
from ai_assistant.core.config import EmbedderKind, Settings
from ai_assistant.core.errors import ConfigurationError
from ai_assistant.core.prompts import PromptDeclaration, PromptOrigin
from ai_assistant.memory._reconciler import MEMORY_RECONCILER_PROMPT
from ai_assistant.models.follow_up import FOLLOW_UP_PROMPT
from ai_assistant.orchestration.digesting import DIGESTING_PROMPT
from ai_assistant.orchestration.matters_pass import MATTERS_PASS_PROMPT
from ai_assistant.orchestration.observer.prompts import (
    OBSERVER_FRAMING_PROMPT,
    OBSERVER_PLACEMENT_PROMPT,
    OBSERVER_SCOUT_PROMPT,
)
from ai_assistant.orchestration.planning import PLANNING_PROMPT
from ai_assistant.orchestration.story_tidy_up import STORY_TIDY_UP_PROMPT
from ai_assistant.orchestration.understanding import UNDERSTANDING_PROMPT
from ai_assistant.testing import default_prompt, flag_combinations

pytestmark = pytest.mark.integration

#: The checkout, whose ``pyproject.toml`` declares the wheel target.
_ROOT = Path(__file__).resolve().parents[2]

#: Text an override holds that no refusal and no log line may carry (§5:2, §8:3).
_PRIVATE = "the owner's private wording 9d41"

#: A well-formed override of understanding's prompt, naming both its flags.
_OVERRIDE = f"{_PRIVATE}\nunderstood\n"


def _settings(*, overrides: bool) -> Settings:
    return Settings(prompt_overrides=overrides)


def _directory(data_dir: Path) -> Path:
    directory = data_dir / "prompts"
    directory.mkdir(mode=0o700)
    directory.chmod(0o700)
    return directory


def _write(path: Path, data: str | bytes, *, mode: int = 0o600) -> Path:
    path.write_bytes(data.encode("utf-8") if isinstance(data, str) else data)
    path.chmod(mode)
    return path


def _refusal(data_dir: Path, *, overrides: bool = True) -> str:
    with pytest.raises(ConfigurationError) as refused:
        read_prompts(_settings(overrides=overrides), data_dir=data_dir)
    message = str(refused.value)
    assert _PRIVATE not in message
    return message


# --- §4:4, §3:1: the defaults -----------------------------------------------------------------


@pytest.mark.parametrize("declaration", PROMPTS, ids=lambda one: one.name)
def test_each_default_renders_under_every_combination_of_its_flags(
    declaration: PromptDeclaration,
) -> None:
    """§4:4. A value is the code's, so a placeholder stands in for each one declared."""
    template = default_prompt(declaration)
    values = {name: f"<{name}>" for name in declaration.values}

    rendered = [
        template.render(flags=flags, values=values) for flags in flag_combinations(declaration)
    ]

    assert len(rendered) == 2 ** len(declaration.flags)
    assert all(text.strip() for text in rendered)


def test_each_default_ships_in_the_wheel_beside_its_module() -> None:
    """§3:1: package data the wheel target carries, so the hub reads it where it runs."""
    shipped = {
        included.distribution_path for included in WheelBuilder(str(_ROOT)).recurse_included_files()
    }

    for declaration in PROMPTS:
        assert f"{declaration.package.replace('.', '/')}/{declaration.filename}" in shipped


def test_the_ten_prompts_carry_their_flags_and_values() -> None:
    """§2:1: all ten prompts, ADR-0346 §10:1's two in ``observer_commit``'s place."""
    assert PROMPTS == (
        UNDERSTANDING_PROMPT,
        PLANNING_PROMPT,
        DIGESTING_PROMPT,
        STORY_TIDY_UP_PROMPT,
        MATTERS_PASS_PROMPT,
        OBSERVER_SCOUT_PROMPT,
        OBSERVER_FRAMING_PROMPT,
        OBSERVER_PLACEMENT_PROMPT,
        MEMORY_RECONCILER_PROMPT,
        FOLLOW_UP_PROMPT,
    )
    # ADR-0353 §8:3: understanding's template takes no flag.
    assert UNDERSTANDING_PROMPT.flags == frozenset()
    assert UNDERSTANDING_PROMPT.values == frozenset()
    # ADR-0356 §4:2: nor does planning's: every part of its instruction is sent each round.
    assert PLANNING_PROMPT.flags == frozenset()
    assert PLANNING_PROMPT.values == frozenset()
    assert STORY_TIDY_UP_PROMPT.values == frozenset({"story_summary_cap_chars"})
    # ADR-0338 §9:1-§9:3: the scout, given a person's fields or not; framing and
    # placement declare no flag (ADR-0346 §10:1).
    assert OBSERVER_SCOUT_PROMPT.flags == frozenset({"person"})
    for declaration in PROMPTS[2:]:
        if declaration is not OBSERVER_SCOUT_PROMPT:
            assert declaration.flags == frozenset()
    assert "observer_commit" not in {one.name for one in PROMPTS}
    for declaration in (
        DIGESTING_PROMPT,
        MATTERS_PASS_PROMPT,
        OBSERVER_SCOUT_PROMPT,
        OBSERVER_FRAMING_PROMPT,
        OBSERVER_PLACEMENT_PROMPT,
        MEMORY_RECONCILER_PROMPT,
        FOLLOW_UP_PROMPT,
    ):
        assert declaration.values == frozenset()


def test_with_no_override_directory_every_prompt_runs_its_default(tmp_path: Path) -> None:
    for overrides in (False, True):
        templates = read_prompts(_settings(overrides=overrides), data_dir=tmp_path)

        assert set(templates) == {declaration.name for declaration in PROMPTS}
        for declaration in PROMPTS:
            shipped = files(declaration.package).joinpath(declaration.filename).read_bytes()
            template = templates[declaration.name]
            assert template.origin is PromptOrigin.DEFAULT
            assert template.version == hashlib.sha256(shipped).hexdigest()[:12]
    assert not (tmp_path / "prompts").exists()


def test_with_overrides_off_an_empty_directory_is_allowed(tmp_path: Path) -> None:
    _directory(tmp_path)

    templates = read_prompts(_settings(overrides=False), data_dir=tmp_path)

    assert templates["understanding"].origin is PromptOrigin.DEFAULT


def test_the_data_dir_keyword_wins_over_the_setting(tmp_path: Path) -> None:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    _write(_directory(tmp_path) / "understanding.txt", _OVERRIDE)
    settings = Settings(prompt_overrides=True, data_dir=elsewhere)

    assert read_prompts(settings, data_dir=tmp_path)["understanding"].origin.value == "override"
    assert read_prompts(settings)["understanding"].origin.value == "default"


# --- §3:3: an override -------------------------------------------------------------------------


def test_an_override_replaces_its_prompts_default_whole(tmp_path: Path) -> None:
    written = _write(_directory(tmp_path) / "understanding.txt", _OVERRIDE)

    template = read_prompts(_settings(overrides=True), data_dir=tmp_path)["understanding"]

    assert template.origin is PromptOrigin.OVERRIDE
    assert template.version == hashlib.sha256(written.read_bytes()).hexdigest()[:12]
    assert template.render(flags={}) == f"{_PRIVATE}\nunderstood"


def test_the_start_logs_each_prompts_name_version_and_origin_and_none_of_its_text(
    tmp_path: Path,
) -> None:
    """§8:3."""
    _write(_directory(tmp_path) / "understanding.txt", _OVERRIDE)

    with structlog.testing.capture_logs() as logged:
        templates = read_prompts(_settings(overrides=True), data_dir=tmp_path)

    lines = [entry for entry in logged if entry["event"] == "prompt_template"]
    assert [(line["prompt"], line["version"], line["origin"]) for line in lines] == [
        (name, template.version, template.origin.value) for name, template in templates.items()
    ]
    assert lines[0]["origin"] == "override"
    assert _PRIVATE not in repr(logged)


# --- §5:1: the start's refusals ----------------------------------------------------------------


def test_with_overrides_off_a_directory_holding_anything_is_refused(tmp_path: Path) -> None:
    directory = _directory(tmp_path)
    _write(directory / "understanding.txt", _OVERRIDE)

    message = _refusal(tmp_path, overrides=False)

    assert "prompt_overrides is false" in message
    assert str(directory) in message


def test_with_overrides_off_a_subdirectory_alone_is_refused(tmp_path: Path) -> None:
    (_directory(tmp_path) / "drafts").mkdir()

    assert "prompt_overrides is false" in _refusal(tmp_path, overrides=False)


@pytest.mark.parametrize("overrides", [False, True])
def test_a_prompts_path_that_is_not_a_directory_is_refused(
    tmp_path: Path, *, overrides: bool
) -> None:
    _write(tmp_path / "prompts", _OVERRIDE)

    assert "is not a directory" in _refusal(tmp_path, overrides=overrides)


@pytest.mark.parametrize("overrides", [False, True])
def test_a_prompts_path_that_is_a_link_is_refused(tmp_path: Path, *, overrides: bool) -> None:
    target = tmp_path / "real"
    target.mkdir(mode=0o700)
    (tmp_path / "prompts").symlink_to(target)

    assert "is not a directory" in _refusal(tmp_path, overrides=overrides)


@pytest.mark.parametrize(
    "name",
    ["no_such_prompt.txt", "understanding", "understanding.txt.bak", ".understanding.txt.swp"],
)
def test_a_file_that_names_no_prompt_is_refused(tmp_path: Path, name: str) -> None:
    """§5:1: an entry whose name is no prompt's `<name>.txt` names no prompt."""
    _write(_directory(tmp_path) / name, _OVERRIDE)

    message = _refusal(tmp_path)

    assert message.endswith(f"{tmp_path / 'prompts' / name} names no prompt")


def test_an_entry_that_is_a_directory_is_refused(tmp_path: Path) -> None:
    (_directory(tmp_path) / "understanding.txt").mkdir()

    assert "understanding.txt is not a regular file" in _refusal(tmp_path)


def test_an_entry_that_is_a_link_is_refused_however_safe_its_target(tmp_path: Path) -> None:
    target = _write(tmp_path / "elsewhere.txt", _OVERRIDE)
    (_directory(tmp_path) / "understanding.txt").symlink_to(target)

    assert "understanding.txt is not a regular file" in _refusal(tmp_path)


def test_an_entry_that_is_a_pipe_is_refused_without_waiting_on_it(tmp_path: Path) -> None:
    os.mkfifo(_directory(tmp_path) / "understanding.txt", 0o600)

    assert "understanding.txt is not a regular file" in _refusal(tmp_path)


@pytest.mark.parametrize(
    ("data", "defect"),
    [
        (b"\xff" + _PRIVATE.encode(), "is not UTF-8"),
        (" \n\t\n", "holds only whitespace"),
        (f"{_PRIVATE}\n$if planning_only\nx\n$end", "line 2: a block names a flag"),
        (f"{_PRIVATE}\n$end", "line 2: an $end closes no block"),
        (f"{_PRIVATE} costs 5$", "line 1: a $ is none of"),
        (f"{_PRIVATE} $tool", "line 1: names a flag or value its prompt does not declare"),
    ],
    ids=["not utf-8", "whitespace", "undeclared flag", "unbalanced", "stray dollar", "no values"],
)
def test_a_malformed_override_is_refused_naming_the_file_and_its_defect(
    tmp_path: Path, data: str | bytes, defect: str
) -> None:
    written = _write(_directory(tmp_path) / "understanding.txt", data)

    message = _refusal(tmp_path)

    assert message.startswith(f"the prompt override {written}: ")
    assert defect in message


@pytest.mark.parametrize("mode", [0o620, 0o602, 0o666])
def test_an_override_others_may_write_is_refused(tmp_path: Path, mode: int) -> None:
    _write(_directory(tmp_path) / "understanding.txt", _OVERRIDE, mode=mode)

    assert "is writable by its group or by others" in _refusal(tmp_path)


@pytest.mark.parametrize("mode", [0o770, 0o707, 0o777])
def test_a_directory_others_may_write_is_refused(tmp_path: Path, mode: int) -> None:
    directory = _directory(tmp_path)
    _write(directory / "understanding.txt", _OVERRIDE)
    directory.chmod(mode)

    message = _refusal(tmp_path)

    assert message == (
        f"the prompt override directory {directory} is writable by its group or by others; "
        "chmod go-w it"
    )


@pytest.mark.parametrize("overrides", [False, True])
def test_an_empty_directory_others_may_write_is_refused_whatever_the_setting(
    tmp_path: Path, *, overrides: bool
) -> None:
    """§5:1 makes the directory's mode a refusal of its own, not one of overrides on."""
    _directory(tmp_path).chmod(0o777)

    assert "is writable by its group or by others" in _refusal(tmp_path, overrides=overrides)


@pytest.mark.parametrize("overrides", [False, True])
def test_an_empty_directory_another_user_owns_is_refused_whatever_the_setting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, overrides: bool
) -> None:
    _directory(tmp_path)
    owner = os.geteuid()
    monkeypatch.setattr(os, "geteuid", lambda: owner + 1)

    assert f"is owned by uid {owner}" in _refusal(tmp_path, overrides=overrides)


def test_an_override_that_cannot_be_read_is_refused_naming_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    written = _write(_directory(tmp_path) / "understanding.txt", _OVERRIDE)

    def failing(descriptor: int, size: int) -> bytes:
        del descriptor, size
        raise OSError(errno.EIO, "Input/output error")

    monkeypatch.setattr(os, "read", failing)

    assert _refusal(tmp_path) == (
        f"the prompt override {written} could not be read: Input/output error"
    )


def test_a_directory_that_cannot_be_listed_is_refused_naming_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory = _directory(tmp_path)

    def failing(path: object) -> object:
        del path
        raise OSError(errno.EIO, "Input/output error")

    monkeypatch.setattr(os, "scandir", failing)

    assert _refusal(tmp_path) == (
        f"the prompt override directory {directory} could not be listed: Input/output error"
    )


def test_a_directory_and_a_file_owned_by_another_user_are_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The hub's uid is read where the check is made, so another one stands in for it."""
    _write(_directory(tmp_path) / "understanding.txt", _OVERRIDE)
    owner = os.geteuid()
    monkeypatch.setattr(os, "geteuid", lambda: owner + 1)

    message = _refusal(tmp_path)

    assert f"is owned by uid {owner}, not by the hub's uid {owner + 1}" in message


def test_a_refused_override_refuses_the_build_before_any_store_opens(tmp_path: Path) -> None:
    """§3:4: before the API accepts a request, and before a store is written."""
    _write(_directory(tmp_path) / "understanding.txt", f"{_PRIVATE} $")
    settings = Settings(embedder=EmbedderKind.HASHING, prompt_overrides=True)

    with pytest.raises(ConfigurationError, match="the prompt override") as refused:
        build_engine(settings, data_dir=tmp_path)

    assert _PRIVATE not in str(refused.value)
    assert sorted(path.name for path in tmp_path.iterdir()) == ["prompts"]


async def test_the_engine_hands_understanding_the_template_it_read(tmp_path: Path) -> None:
    _write(_directory(tmp_path) / "understanding.txt", _OVERRIDE)
    settings = Settings(embedder=EmbedderKind.HASHING, prompt_overrides=True)

    engine = build_engine(settings, data_dir=tmp_path)
    try:
        assert engine._understanding is not None
        prompt = engine._understanding._prompt
        assert prompt.origin is PromptOrigin.OVERRIDE
        assert prompt.name == "understanding"
    finally:
        await engine.aclose()
