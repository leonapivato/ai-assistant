"""Tests for ``scripts/prompt_replay.py`` (ADR-0335).

The tool is loaded by its path, as every script here is: it is no package, and nothing in
``ai_assistant`` may import it (§2:2). Its record is written with ADR-0314's own store
(``_replay_record``), and its model is a ``FunctionModel`` sent to through the package's
own model layer, so no call leaves the machine and nothing contacts a hub.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import os
import socket
import sqlite3
import stat
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

import pytest
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.messages import ModelResponse, TextPart, ThinkingPart
from pydantic_ai.models.function import FunctionModel

import ai_assistant
from ai_assistant.core.config import EmbedderKind
from ai_assistant.core.errors import ModelError
from ai_assistant.core.reply_shapes import read_reply, reply_shape_version
from ai_assistant.core.types import Message, ProposedActivationUnderstanding, ReplyFailure, Role
from ai_assistant.models import PydanticAIProvider, RetryingProvider
from ai_assistant.models.retry import RetryPolicy
from ai_assistant.orchestration import planning
from ai_assistant.orchestration.digesting import DigestReply
from ai_assistant.orchestration.matters_pass import MattersPassReply
from ai_assistant.orchestration.observer.replies import (
    FramingReplyShape,
    PersonScoutReplyShape,
    PlacementReplyShape,
    ScoutReplyShape,
)
from ai_assistant.orchestration.observer.stage import RunOutcome
from ai_assistant.orchestration.story_tidy_up import TidyUpReply
from ai_assistant.service.lock import InstanceLock

sys.path.insert(0, str(Path(__file__).parent))
from _replay_record import (
    ACT_A,
    ACT_B,
    DIGEST_TOLD,
    OLD_INPUT,
    ORIGINAL_MODEL,
    PLANNING_INPUT,
    PLANNING_TOLD,
    PRIVATE,
    SCOUT_TOLD,
    UNDERSTANDING_INPUT,
    UNDERSTANDING_TOLD,
    Model,
    lines,
    live_snapshot,
    make_copy,
    now,
    replay_tool,
    write_live,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

pytestmark = pytest.mark.integration

#: A prompt that declares flags, for the replay's flag machinery (ADR-0335 §9:1): the
#: understanding prompt as it declared its three flags before ADR-0353 §8:3 took them
#: away, so these cases go on exercising rendering under recorded and stated flags over
#: the record's understanding entries. Only the cases naming :func:`flagged` read it.
FLAGS: Final = frozenset({"recalled", "stories", "person"})


def _flagged() -> dict[str, Any]:
    declared = dict(_DECLARED())
    declared["understanding"] = dataclasses.replace(declared["understanding"], flags=FLAGS)
    return declared


_DECLARED: Final = replay_tool.declared_prompts


@pytest.fixture
def flagged(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """The run's declared prompts, understanding's with :data:`FLAGS`."""
    monkeypatch.setattr(replay_tool, "declared_prompts", _flagged)
    return _flagged()


#: An understanding template that branches on two of :data:`FLAGS`.
TEMPLATE = (
    "Candidate understanding instruction.\n"
    "$if recalled\n"
    "Recalled memories are shown.\n"
    "$end\n"
    "$if not stories\n"
    "No stories are shown.\n"
    "$end\n"
)


def _replay(
    copy: Path,
    model: Model,
    reports: list[str] | None = None,
    *,
    clock: Callable[[], datetime] = now,
    **options: Any,
) -> int:
    told = [] if reports is None else reports
    status: int = asyncio.run(
        replay_tool.replay(
            replay_tool.ReplayOptions(copy=copy, model="fake:model", **options),
            report=told.append,
            caller=model.caller(),
            now=clock,
        )
    )
    return status


def _results(copy: Path) -> dict[str, list[dict[str, Any]]]:
    record = copy / "diagnostics"
    return {path.name: lines(path) for path in sorted(record.glob("*" + replay_tool.REPLAY_SUFFIX))}


def _template(tmp_path: Path, text: str = TEMPLATE, name: str = "understanding.txt") -> Path:
    drafts = tmp_path / "drafts"
    drafts.mkdir(exist_ok=True)
    path = drafts / name
    path.write_text(text)
    return path


# --- §3: the copy ------------------------------------------------------------------------------


def test_the_copy_is_owner_only_and_carries_the_record_whole_up_to_its_last_line(
    tmp_path: Path,
) -> None:
    live = write_live(tmp_path)
    torn = live / "diagnostics" / f"{ACT_A}.jsonl"
    with torn.open("ab") as handle:
        handle.write(b'{"half a line')
    copy = tmp_path / "copy"

    counts = replay_tool.copy_data_dir(live, copy, retention=timedelta(days=3), now=now)

    assert stat.S_IMODE(copy.stat().st_mode) == 0o700
    for path in copy.rglob("*"):
        expected = 0o700 if path.is_dir() else 0o600
        assert stat.S_IMODE(path.stat().st_mode) == expected, path
    copied = (copy / "diagnostics" / f"{ACT_A}.jsonl").read_bytes()
    assert copied == torn.read_bytes()[: torn.read_bytes().rfind(b"\n") + 1]
    assert (copy / "prompts" / "planning.txt").read_text() == "An override, no final line break"
    reader = sqlite3.connect(copy / "memory.db")
    assert reader.execute("select text from memories").fetchall() == [(PRIVATE,)]
    reader.close()
    assert not (copy / "hub.lock").exists()
    assert counts.databases == 1
    assert counts.record_files == 4
    mark = replay_tool.read_mark(copy)
    assert mark.made_at == now()
    assert mark.retention == timedelta(days=3)


def test_the_copy_writes_nothing_in_the_live_directory_while_a_writer_holds_a_database(
    tmp_path: Path,
) -> None:
    live = write_live(tmp_path)
    writer = sqlite3.connect(live / "plans.db")
    writer.execute("pragma journal_mode=wal")
    writer.execute("create table plans (x)")
    writer.execute("insert into plans values (1)")
    writer.commit()
    listener = socket.socket(socket.AF_UNIX)
    short = Path(f"/tmp/lane-rt3-{os.getpid()}.sock")  # noqa: S108 — a socket path must be short
    listener.bind(str(short))
    (live / "hub.sock").symlink_to(short)
    (live / "elsewhere").symlink_to(tmp_path)
    before = live_snapshot(live)
    try:
        counts = replay_tool.copy_data_dir(live, tmp_path / "copy", retention=timedelta(1))
    finally:
        listener.close()
        short.unlink()
    after = live_snapshot(live)
    writer.close()

    # Every file is left as it was, and no side file is created (§3:2). The one exception
    # is SQLite's own: a reader of a WAL database records its read mark in the shared
    # memory index beside it, as the hub's own readers do, so that a writer does not
    # checkpoint past what it reads. That index holds no data and none of the copy's.
    shared = "plans.db-shm"
    assert after.keys() == before.keys()
    assert {k: v for k, v in after.items() if k != shared} == {
        k: v for k, v in before.items() if k != shared
    }
    assert after[shared][:2] == before[shared][:2]
    assert not (live / "memory.db-wal").exists()
    copied = sqlite3.connect(tmp_path / "copy" / "plans.db")
    assert copied.execute("select x from plans").fetchall() == [(1,)]
    copied.close()
    names = {path.name for path in (tmp_path / "copy").iterdir()}
    assert not names & {"hub.lock", "hub.sock", "elsewhere", "plans.db-wal", "plans.db-shm"}
    assert counts.skipped >= 5


def test_the_copy_goes_into_a_new_directory_outside_the_live_one(tmp_path: Path) -> None:
    live = write_live(tmp_path)
    taken = tmp_path / "taken"
    taken.mkdir()

    with pytest.raises(replay_tool.ReplayError, match="already exists"):
        replay_tool.copy_data_dir(live, taken, retention=timedelta(1))
    with pytest.raises(replay_tool.ReplayError, match="one inside the other"):
        replay_tool.copy_data_dir(live, live / "inner", retention=timedelta(1))

    assert not (live / "inner").exists()
    assert list(taken.iterdir()) == []


def test_a_copy_that_fails_part_way_leaves_nothing(tmp_path: Path) -> None:
    live = write_live(tmp_path)
    (live / "memory.db-wal").write_bytes(b"")  # a side file alone: no consistent read

    with pytest.raises(replay_tool.ReplayError, match="side files"):
        replay_tool.copy_data_dir(live, tmp_path / "copy", retention=timedelta(1))

    assert not (tmp_path / "copy").exists()


def test_replay_and_rerun_refuse_a_directory_without_the_marker_naming_it(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()

    for run in (
        lambda: _replay(plain, Model()),
        lambda: asyncio.run(
            replay_tool.rerun(
                replay_tool.RerunOptions(copy=plain, model="fake:model"), report=print
            )
        ),
        lambda: replay_tool.delete_copy(plain),
    ):
        with pytest.raises(replay_tool.ReplayError, match=str(plain)):
            run()


def test_a_copy_older_than_its_retention_is_refused_and_can_be_deleted(tmp_path: Path) -> None:
    copy = make_copy(tmp_path, retention=timedelta(hours=1))

    _replay(copy, Model(), clock=lambda: now() + timedelta(minutes=59), count_only=True)
    with pytest.raises(replay_tool.ReplayError, match="past its retention"):
        _replay(copy, Model(), clock=lambda: now() + timedelta(minutes=61))
    replay_tool.delete_copy(copy)

    assert not copy.exists()


def test_a_run_holds_the_copys_lock_for_its_whole_run_and_refuses_a_held_one(
    tmp_path: Path,
) -> None:
    copy = make_copy(tmp_path)
    contended: list[bool] = []
    model = Model()
    model.during.append(lambda: contended.append(not InstanceLock(copy / "hub.lock").acquire()))

    _replay(copy, model, sources=frozenset({"digesting"}))
    other = InstanceLock(copy / "hub.lock")
    assert other.acquire()
    try:
        with pytest.raises(replay_tool.ReplayError, match="instance lock"):
            _replay(copy, Model())
        with pytest.raises(replay_tool.ReplayError, match="instance lock"):
            replay_tool.delete_copy(copy)
    finally:
        other.release()

    assert contended == [True]


# --- §4-§6: replaying recorded calls -----------------------------------------------------------


def test_the_recorded_instruction_replays_every_model_call_as_recorded(tmp_path: Path) -> None:
    copy = make_copy(tmp_path)
    model = Model()

    status = _replay(copy, model)

    assert status == 0
    # One call for each distinct request: understanding twice, planning, the digest part,
    # and the scout once for the two activations it read for (§4:11).
    assert sorted(model.systems) == sorted(
        [UNDERSTANDING_TOLD, UNDERSTANDING_TOLD, PLANNING_TOLD, DIGEST_TOLD, SCOUT_TOLD]
    )
    assert {UNDERSTANDING_INPUT, OLD_INPUT, PLANNING_INPUT} <= set(model.users)
    assert ["web_search", "planning_round"] in model.tools
    results = _results(copy)
    assert set(results) == {f"{ACT_A}.replay.jsonl", f"{ACT_B}.replay.jsonl"}
    for line in (one for each in results.values() for one in each):
        assert set(line) == {"activation_id", "source", "kind", "recorded_at", "body"}
        assert (line["source"], line["kind"]) == ("replay", "returned")
        assert line["body"]["candidate"]["origin"] == "recorded"
        assert line["body"]["model"] == "function:answer:"


def test_each_result_names_the_entry_it_replays_and_what_the_original_used(
    tmp_path: Path,
) -> None:
    copy = make_copy(tmp_path)

    _replay(copy, Model())

    by_source = {
        one["body"]["replays"]["source"]: one["body"]
        for one in _results(copy)[f"{ACT_A}.replay.jsonl"]
    }
    planned = by_source["planning"]
    assert planned["replays"] == {
        "file": f"{ACT_A}.jsonl",
        "line": 2,
        "recorded_at": "2026-10-19T09:00:00.030000Z",
        "source": "planning",
        "stage": None,
    }
    assert planned["prompt"] == "planning"
    assert planned["recorded_prompt"] == {"version": "0123456789ab", "origin": "default"}
    assert planned["candidate"]["instruction"] == PLANNING_TOLD
    assert planned["original_model"] == ORIGINAL_MODEL
    assert planned["original_model_known"] is True
    assert planned["response"]["parts"][0]["content"].startswith("a replayed reply")
    assert planned["response"]["model_name"] == "function:answer:"
    assert "read_as_round" in planned
    understood = by_source["understanding"]
    assert understood["reply"].startswith("a replayed reply")
    assert understood["original_model"] is None
    assert understood["original_model_known"] is False
    # A digest part's entry predates ADR-0334's key: its prompt is the one the package
    # declares under its source's name, and no recorded version is claimed for it.
    assert by_source["digesting"]["prompt"] == "digesting"
    assert by_source["digesting"]["recorded_prompt"] is None
    assert by_source["digesting"]["candidate"]["version"] is None


def test_a_call_the_observer_wrote_under_two_activations_is_sent_once_and_written_under_each(
    tmp_path: Path,
) -> None:
    copy = make_copy(tmp_path)
    model = Model()

    _replay(copy, model, sources=frozenset({"observer"}))

    assert model.systems == [SCOUT_TOLD]
    results = _results(copy)
    for activation_id in (ACT_A, ACT_B):
        (only,) = results[f"{activation_id}.replay.jsonl"]
        assert only["activation_id"] == activation_id
        assert only["body"]["replays"]["file"] == f"{activation_id}.observer.jsonl"
        assert only["body"]["replays"]["stage"] == "scout"


def test_no_call_is_taken_to_replay_from_a_follow_up_file(tmp_path: Path) -> None:
    """ADR-0337 §8:18: a follow-up file is read for nothing, even a line shaped as a call."""
    copy = make_copy(tmp_path)
    record = copy / "diagnostics"
    before = [(one.file, one.line) for one in replay_tool.read_givens(record)]
    shaped = {
        "activation_id": ACT_A,
        "source": "understanding",
        "kind": "given",
        "recorded_at": "2026-10-19T09:00:00Z",
        "body": {
            "messages": [
                {"role": "system", "content": "Not a call.", "name": None},
                {"role": "user", "content": "Not an input.", "name": None},
            ]
        },
    }
    followed = record / f"{ACT_A}.followup.jsonl"
    followed.write_text(json.dumps(shaped) + "\n", encoding="utf-8")
    followed.chmod(0o600)
    model = Model()

    _replay(copy, model)

    assert [(one.file, one.line) for one in replay_tool.read_givens(record)] == before
    assert "Not a call." not in model.systems
    assert f"{ACT_A}.followup.replay.jsonl" not in _results(copy)


@pytest.mark.usefixtures("flagged")
def test_a_template_is_rendered_under_stated_flags_where_the_entry_records_none(
    tmp_path: Path,
) -> None:
    copy = make_copy(tmp_path)
    candidate = _template(tmp_path)
    model = Model()
    reports: list[str] = []

    _replay(
        copy,
        model,
        reports,
        candidates=(str(candidate), "recorded"),
        flags=(
            "understanding.recalled=true",
            "understanding.stories=false",
            "understanding.person=false",
        ),
    )

    rendered = (
        "Candidate understanding instruction.\nRecalled memories are shown.\nNo stories are shown."
    )
    # The candidates' prompt alone is replayed: both understanding entries, the one written
    # before ADR-0334's key included, each with the candidate and the control.
    assert sorted(model.systems) == sorted(
        [rendered, rendered, UNDERSTANDING_TOLD, UNDERSTANDING_TOLD]
    )
    results = [one["body"] for each in _results(copy).values() for one in each]
    templated = [one for one in results if one["candidate"]["origin"] == "override"]
    assert len(templated) == 2
    for one in templated:
        assert one["flags"] == {"recalled": True, "stories": False, "person": False}
        assert one["flags_from"] == "stated"
        assert one["candidate"]["instruction"] == rendered
        assert (
            one["candidate"]["version"]
            == replay_tool.load_candidate(
                str(candidate), replay_tool.declared_prompts()
            ).template.version
        )
        assert one["prompt"] == "understanding"
    assert any("entries of the candidates' prompts only: understanding" in one for one in reports)


@pytest.mark.usefixtures("flagged")
def test_a_template_is_left_out_where_no_flags_are_recorded_or_stated(tmp_path: Path) -> None:
    copy = make_copy(tmp_path)
    model = Model()
    reports: list[str] = []

    _replay(copy, model, reports, candidates=(str(_template(tmp_path)),))

    assert model.systems == []
    assert "left out: 2 (no flags recorded or stated)" in reports
    assert _results(copy) == {}


@pytest.mark.usefixtures("flagged")
def test_a_template_is_rendered_under_the_flags_the_entry_records(tmp_path: Path) -> None:
    live = write_live(tmp_path)
    record = live / "diagnostics" / f"{ACT_A}.jsonl"
    record.write_text(
        record.read_text().replace(
            '"prompt":{"name":"understanding","version":"0123456789ab","origin":"default"}',
            '"prompt":{"name":"understanding","version":"0123456789ab","origin":"default",'
            '"flags":{"recalled":false,"stories":true,"person":false}}',
        )
    )
    copy = tmp_path / "copy"
    replay_tool.copy_data_dir(live, copy, retention=timedelta(days=1), now=now)
    model = Model()

    _replay(copy, model, candidates=(str(_template(tmp_path)),), activations=frozenset({ACT_A}))

    assert model.systems == ["Candidate understanding instruction."]
    (only,) = _results(copy)[f"{ACT_A}.replay.jsonl"]
    assert only["body"]["flags"] == {"recalled": False, "stories": True, "person": False}
    assert only["body"]["flags_from"] == "recorded"


def test_a_template_is_refused_naming_its_file_and_defect_and_never_its_content(
    tmp_path: Path,
) -> None:
    copy = make_copy(tmp_path)
    broken = _template(tmp_path, "Fine first line.\n$if " + PRIVATE + "\n")
    model = Model()

    with pytest.raises(replay_tool.ReplayError) as refused:
        _replay(copy, model, candidates=(str(broken),))

    assert str(broken) in str(refused.value)
    assert "line 2" in str(refused.value)
    assert PRIVATE not in str(refused.value)
    assert model.systems == []
    with pytest.raises(replay_tool.ReplayError, match="names no prompt"):
        _replay(copy, model, candidates=(str(_template(tmp_path, name="nothing.txt")),))


def test_a_template_where_its_default_ships_is_a_default() -> None:
    shipped = Path(planning.__file__).parent / "planning.txt"

    candidate = replay_tool.load_candidate(str(shipped), replay_tool.declared_prompts())

    assert candidate.origin == "default"
    assert candidate.values == planning._PLANNING_VALUES


def test_stated_flags_must_name_declared_flags_and_state_every_one(
    tmp_path: Path, flagged: dict[str, Any]
) -> None:
    declared = flagged

    for stated, defect in (
        (["understanding.recalled=true"], "unstated"),
        (["understanding.nothing=true"], "names no flag"),
        (["understanding.recalled=perhaps", "understanding.stories=no"], "no true or false"),
    ):
        with pytest.raises(replay_tool.ReplayError, match=defect):
            replay_tool.parse_flags(stated, declared)
    assert replay_tool.parse_flags(
        ["understanding.recalled=yes", "understanding.stories=0", "understanding.person=no"],
        declared,
    ) == {"understanding": {"recalled": True, "stories": False, "person": False}}


# --- §8: the bound -------------------------------------------------------------------------------


def test_a_run_past_its_bound_sends_nothing_after_printing_its_count(tmp_path: Path) -> None:
    copy = make_copy(tmp_path)
    model = Model()
    reports: list[str] = []

    status = _replay(copy, model, reports, bound=4)

    assert status == 1
    assert "5 calls to send (bound 4); 0 under stated flags" in reports
    assert "refused: 5 calls exceed the bound of 4" in reports
    assert model.systems == []
    assert _results(copy) == {}


def test_a_count_only_run_sends_nothing(tmp_path: Path) -> None:
    copy = make_copy(tmp_path)
    model = Model()
    reports: list[str] = []

    assert _replay(copy, model, reports, count_only=True) == 0

    assert "5 calls to send (bound 100); 0 under stated flags" in reports
    assert model.systems == []


# --- §4:7, §5:3: failures, and what is printed ----------------------------------------------------


def test_a_call_the_model_fails_is_recorded_as_failed_and_printed_by_class(
    tmp_path: Path,
) -> None:
    copy = make_copy(tmp_path)
    reports: list[str] = []

    _replay(copy, Model(fail=RuntimeError(PRIVATE)), reports, sources=frozenset({"digesting"}))

    (only,) = _results(copy)[f"{ACT_A}.replay.jsonl"]
    assert only["body"]["failure"]["class"] == "ModelError"
    assert "reply" not in only["body"]
    assert "failed: 1 (ModelError)" in reports


@pytest.mark.usefixtures("flagged")
def test_nothing_printed_comes_from_an_entry_or_a_reply(tmp_path: Path) -> None:
    copy = make_copy(tmp_path)
    reports: list[str] = []

    _replay(
        copy,
        Model(),
        reports,
        candidates=(str(_template(tmp_path)), "recorded"),
        flags=(
            "understanding.recalled=true",
            "understanding.stories=true",
            "understanding.person=false",
        ),
    )
    _replay(copy, Model(fail=RuntimeError(PRIVATE)), reports)

    assert reports
    assert not any(PRIVATE in one for one in reports)
    assert not any("Candidate understanding" in one for one in reports)


def test_main_prints_a_refusal_and_exits_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()

    status = replay_tool.main(["replay", str(plain), "--model", "anthropic:claude-test"])

    assert status == 1
    assert f"refused: {plain} carries no replay copy's marker" in capsys.readouterr().out


def test_main_copies_and_deletes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    live = write_live(tmp_path)
    copy = tmp_path / "copy"

    assert replay_tool.main(["copy", str(live), str(copy), "--retention-days", "2"]) == 0
    assert replay_tool.read_mark(copy).retention == timedelta(days=2)
    assert replay_tool.main(["delete", str(copy)]) == 0

    out = capsys.readouterr().out
    assert "1 databases, 4 record files, 1 other files" in out
    assert f"deleted {copy}" in out
    assert not copy.exists()


# --- §7: the rerun -------------------------------------------------------------------------------


class _Engine:
    """An engine answering the observer's runs from a script, and noting its close."""

    def __init__(self, outcomes: Sequence[RunOutcome], copy: Path) -> None:
        self.outcomes = list(outcomes)
        self.copy = copy
        self.closed = False
        self.locked: list[bool] = []

    async def observe_episodes(self) -> RunOutcome:
        self.locked.append(not InstanceLock(self.copy / "hub.lock").acquire())
        return self.outcomes.pop(0)

    async def aclose(self) -> None:
        self.closed = True


def test_a_rerun_composes_from_stated_settings_alone_and_runs_until_nothing_is_due(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    copy = make_copy(tmp_path)
    monkeypatch.setenv("ASSISTANT_TELEGRAM_CONNECTION", "live-line")
    monkeypatch.setenv("ASSISTANT_TELEGRAM_USER_ID", "5")
    monkeypatch.setenv("ASSISTANT_WEB_SEARCH_CONNECTION", "live-search")
    monkeypatch.setenv("ASSISTANT_OBSERVER_DAILY_CALLS", "9999")
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("ASSISTANT_SEND_EMAIL_CONNECTION=live-mail\n")
    built: list[tuple[Any, int]] = []
    engine = _Engine(
        [RunOutcome(processed=2, waiting=1), RunOutcome(processed=1), RunOutcome()], copy
    )

    def build(settings: Any) -> Any:
        built.append((settings, replay_tool.composition.UNDERSTANDING_EPISODE_LIMIT))
        return engine

    reports: list[str] = []
    status = asyncio.run(
        replay_tool.rerun(
            replay_tool.RerunOptions(
                copy=copy,
                model="anthropic:claude-test",
                bound=7,
                episode_limit=1,
                timezone="Europe/Lisbon",
            ),
            report=reports.append,
            build=build,
            check_model=lambda _: None,
            now=now,
        )
    )

    assert status == 0
    ((settings, limit),) = built
    assert settings.telegram_connection is None
    assert settings.telegram_user_id is None
    assert settings.web_search_connection is None
    assert settings.send_email_connection is None
    assert settings.data_dir == copy.resolve()
    assert settings.diagnostic_record is True
    assert settings.prompt_overrides is True
    assert settings.observer_daily_calls == 7
    assert settings.fallback_models == ()
    assert {
        settings.default_model,
        settings.observer_scout_model,
        settings.observer_commit_model,
    } == {"anthropic:claude-test"}
    assert settings.timezone == "Europe/Lisbon"
    # The bound is narrowed for the build alone (§7:4), and restored after.
    assert limit == 1
    assert replay_tool.composition.UNDERSTANDING_EPISODE_LIMIT == 10
    assert engine.locked == [True, True, True]
    assert engine.closed
    assert "the episode selector's bound is narrowed from 10 to 1" in reports
    assert "the observer's daily budget is set to the bound, 7 calls" in reports
    assert len([one for one in reports if one.startswith("observer run")]) == 3


def test_a_rerun_stops_where_the_budget_holds_it(tmp_path: Path) -> None:
    copy = make_copy(tmp_path)
    engine = _Engine([RunOutcome(processed=1, held=True), RunOutcome(processed=1)], copy)

    asyncio.run(
        replay_tool.rerun(
            replay_tool.RerunOptions(copy=copy, model="anthropic:claude-test"),
            report=lambda _: None,
            build=lambda _: engine,
            check_model=lambda _: None,
            now=now,
        )
    )

    assert len(engine.outcomes) == 1
    assert engine.closed


def test_a_rerun_composes_the_real_package_over_a_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Each model is built at composition, as the rerun counts its requests there; no
    # episode is due, so no request is made and the key is never used.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-a-credential")
    counted: list[Any] = []
    real = replay_tool.CountedModel.__init__

    def noting(self: Any, wrapped: Any, meter: Any) -> None:
        counted.append(meter)
        real(self, wrapped, meter)

    monkeypatch.setattr(replay_tool.CountedModel, "__init__", noting)
    live = tmp_path / "live"
    (live / "prompts").mkdir(parents=True, mode=0o700)
    (live / "prompts" / "understanding.txt").write_text("Candidate understanding instruction.\n")
    copy = tmp_path / "copy"
    replay_tool.copy_data_dir(live, copy, retention=timedelta(days=1), now=now)
    reports: list[str] = []

    asyncio.run(
        replay_tool.rerun(
            replay_tool.RerunOptions(
                copy=copy, model="anthropic:claude-test", embedder=EmbedderKind.HASHING
            ),
            report=reports.append,
            check_model=lambda _: None,
            now=now,
        )
    )

    # No episode is due in this copy, so the observer makes no call and the run ends.
    assert "observer run 1: 0 processed, 0 skipped, 0 waiting, 0 stuck" in reports
    # Every completion provider the composition built counts on the one meter: the
    # conversation routes, consolidation's, the reconciler's and the observer's two.
    assert len(counted) >= 4
    assert len({id(one) for one in counted}) == 1
    assert "0 model calls made (bound 100); 0 refused" in reports
    assert not any("narrowed" in one for one in reports)


# --- §2:2: nothing in the package names it -------------------------------------------------------


def test_nothing_in_the_package_names_the_tool() -> None:
    # A claim about something not happening, so checked over the source, as the seam's own
    # test checks that no stage names it.
    root = Path(ai_assistant.__file__).resolve().parent

    naming = [
        path.relative_to(root)
        for path in sorted(root.rglob("*"))
        if path.is_file()
        and path.suffix in {".py", ".txt", ".toml", ".service", ".sh"}
        and "prompt_replay" in path.read_text(encoding="utf-8", errors="replace")
    ]

    assert naming == []


def test_the_prompt_key_the_package_writes_is_read_for_its_flags(
    tmp_path: Path, flagged: dict[str, Any]
) -> None:
    # ADR-0335 §9:1's key as the package itself builds it, for a prompt with flags and
    # for one that declares none, which records an empty object.
    declared = flagged
    shipped = {
        name: replay_tool.load_candidate(
            str(Path(planning.__file__).parent / f"{name}.txt"), declared
        ).template
        for name in ("understanding", "digesting")
    }
    understood = shipped["understanding"].rendered(
        flags={"recalled": True, "stories": False, "person": False}
    )
    digested = shipped["digesting"].rendered()
    live = write_live(tmp_path)
    record = live / "diagnostics" / f"{ACT_A}.jsonl"
    text = record.read_text()
    text = text.replace(
        '"prompt":{"name":"understanding","version":"0123456789ab","origin":"default"}',
        '"prompt":' + json.dumps(understood.provenance(), separators=(",", ":")),
    )
    text = text.replace(
        '"part":1,"parts":1,',
        '"part":1,"parts":1,"prompt":'
        + json.dumps(digested.provenance(), separators=(",", ":"))
        + ",",
    )
    record.write_text(text)
    copy = tmp_path / "copy"
    replay_tool.copy_data_dir(live, copy, retention=timedelta(days=1), now=now)
    understanding = _template(tmp_path)
    digesting = _template(tmp_path, "A candidate digest instruction.\n", name="digesting.txt")
    model = Model()

    _replay(
        copy,
        model,
        candidates=(str(understanding), str(digesting)),
        activations=frozenset({ACT_A}),
    )

    bodies = {one["body"]["prompt"]: one["body"] for one in _results(copy)[f"{ACT_A}.replay.jsonl"]}
    assert bodies["understanding"]["flags"] == {
        "recalled": True,
        "stories": False,
        "person": False,
    }
    assert bodies["understanding"]["flags_from"] == "recorded"
    assert bodies["understanding"]["candidate"]["instruction"] == (
        "Candidate understanding instruction.\nRecalled memories are shown.\nNo stories are shown."
    )
    assert bodies["understanding"]["recorded_prompt"] == {
        "version": understood.template.version,
        "origin": "default",
    }
    assert bodies["digesting"]["flags"] == {}
    assert bodies["digesting"]["flags_from"] == "recorded"
    assert bodies["digesting"]["candidate"]["instruction"] == "A candidate digest instruction."


def _given(
    source: str,
    line: int,
    prompt: dict[str, Any] | None,
    *,
    activation: str = ACT_A,
    seconds: float = 0,
    **body: Any,
) -> Any:
    held = {
        "messages": [
            {"role": "system", "content": "told", "name": None},
            {"role": "user", "content": "the same request", "name": None},
        ],
        **body,
    }
    if prompt is not None:
        held["prompt"] = prompt
    return replay_tool.Given(
        file=f"{activation}.observer.jsonl" if source == "observer" else f"{activation}.jsonl",
        activation_id=activation,
        line=line,
        recorded_at=(now() + timedelta(seconds=seconds)).isoformat(),
        source=source,
        stage=body.get("stage"),
        body=held,
    )


def _calls(plan: Any) -> dict[tuple[str, tuple[tuple[str, int], ...]], Any]:
    return {
        (call.candidate.origin, tuple((one.activation_id, one.line) for one in call.givens)): call
        for call in plan.calls
    }


def test_entries_are_one_call_only_as_copies_of_the_observers_call_under_other_activations(
    tmp_path: Path,
) -> None:
    declared = replay_tool.declared_prompts()
    scout = {"name": "observer_scout", "version": "v", "origin": "default", "flags": {}}
    givens = [
        # The scout's call, written under three activations at once: one call (§4:11).
        _given("observer", 0, scout, stage="scout"),
        _given("observer", 0, scout, activation=ACT_B, seconds=0.01, stage="scout"),
        _given("observer", 0, scout, activation="act-c", seconds=0.02, stage="scout"),
        # The same request retried in A's own file, fifteen minutes on: another call.
        _given("observer", 1, scout, seconds=900, stage="scout"),
        # And under B at that retry's time: a copy of the retry, not of the first call.
        _given("observer", 1, scout, activation=ACT_B, seconds=900.01, stage="scout"),
        # The same request with another prompt key: a call of its own.
        _given("observer", 2, None, seconds=0.03, stage="scout"),
        # Two understanding entries holding one request are two calls.
        _given("understanding", 0, None),
        _given("understanding", 0, None, activation=ACT_B),
    ]
    recorded = replay_tool.load_candidate("recorded", declared)

    plan = replay_tool.plan_run(givens, [recorded], declared=declared, stated={})

    assert set(_calls(plan)) == {
        ("recorded", ((ACT_A, 0), (ACT_B, 0), ("act-c", 0))),
        ("recorded", ((ACT_A, 1), (ACT_B, 1))),
        ("recorded", ((ACT_A, 2),)),
        ("recorded", ((ACT_A, 0),)),
        ("recorded", ((ACT_B, 0),)),
    }
    assert plan.requests == 5


def test_no_entry_is_rendered_from_another_entrys_flags(
    tmp_path: Path, flagged: dict[str, Any]
) -> None:
    declared = flagged
    flagged = {
        "name": "understanding",
        "version": "v",
        "origin": "default",
        "flags": {"recalled": False, "stories": True, "person": False},
    }
    unflagged = {"name": "understanding", "version": "v", "origin": "default"}
    givens = [_given("understanding", 0, unflagged), _given("understanding", 1, flagged)]
    template = replay_tool.load_candidate(str(_template(tmp_path)), declared)

    plan = replay_tool.plan_run(givens, [template], declared=declared, stated={})

    ((key, call),) = _calls(plan).items()
    assert key == ("override", ((ACT_A, 1),))
    assert call.flags == {"recalled": False, "stories": True, "person": False}
    assert call.flags_from == "recorded"
    assert plan.left_out == {"no flags recorded or stated": 1}


def _empty_then_text(requests: list[int]) -> Any:
    def answer(messages: list[Any], info: Any) -> Any:
        del messages, info
        requests.append(1)
        return ModelResponse(parts=[TextPart("" if len(requests) == 1 else "a repair")])

    return answer


def test_a_replay_sends_no_repair_after_an_empty_reply(tmp_path: Path) -> None:
    # pydantic-ai's agent asks again of its own accord after an empty reply; a replay sends
    # each call once and no repair (§4:10), so the call is recorded as failed.
    copy = make_copy(tmp_path)
    requests: list[int] = []
    caller = replay_tool.ModelCaller(FunctionModel(_empty_then_text(requests)), timeout=10)
    reports: list[str] = []

    asyncio.run(
        replay_tool.replay(
            replay_tool.ReplayOptions(
                copy=copy, model="fake:model", sources=frozenset({"digesting"})
            ),
            report=reports.append,
            caller=caller,
            now=now,
        )
    )

    assert len(requests) == 1
    (only,) = _results(copy)[f"{ACT_A}.replay.jsonl"]
    assert "reply" not in only["body"]
    assert only["body"]["failure"]["class"] == "ModelError"
    assert "failed: 1 (ModelError)" in reports


def test_a_rerun_counts_the_agents_own_repair_against_its_bound(tmp_path: Path) -> None:
    copy = make_copy(tmp_path)
    requests: list[int] = []
    failures: list[str] = []

    class _Engine:
        def __init__(self) -> None:
            # Built inside the composition, as each of its providers is.
            self.provider = replay_tool.composition.PydanticAIProvider(
                FunctionModel(_empty_then_text(requests))
            )

        async def observe_episodes(self) -> RunOutcome:
            try:
                await self.provider.complete([Message(role=Role.USER, content="x")])
            except ModelError as exc:
                failures.append(type(exc).__name__)
            return RunOutcome(processed=1)

        async def aclose(self) -> None:
            return None

    reports: list[str] = []
    asyncio.run(
        replay_tool.rerun(
            replay_tool.RerunOptions(copy=copy, model="anthropic:claude-test", bound=1),
            report=reports.append,
            build=lambda _: _Engine(),
            check_model=lambda _: None,
            now=now,
        )
    )

    assert len(requests) == 1
    assert failures == ["ModelError"]
    assert "1 model calls made (bound 1); 1 refused" in reports
    assert replay_tool.composition.PydanticAIProvider is PydanticAIProvider


async def _no_wait(_: float) -> None:
    return None


class _Metering:
    """An engine whose observer run makes completions through the package's own provider,
    behind a retrying wrapper as the reconciler's route is, past the bound."""

    def __init__(self, model: Any, calls: int) -> None:
        self.provider = RetryingProvider(
            replay_tool.composition.PydanticAIProvider(model),
            policy=RetryPolicy(max_attempts=3, backoff_base_seconds=0.001),
            sleep=_no_wait,
        )
        self.calls = calls
        self.failures: list[str] = []
        self.runs = 0

    async def observe_episodes(self) -> RunOutcome:
        self.runs += 1
        for _ in range(self.calls):
            try:
                await self.provider.complete([Message(role=Role.USER, content="x")])
            except ModelError as exc:
                self.failures.append(type(exc).__name__)
        return RunOutcome(processed=1)

    async def aclose(self) -> None:
        return None


def test_a_rerun_counts_every_model_request_retries_included_against_its_bound(
    tmp_path: Path,
) -> None:
    copy = make_copy(tmp_path)
    requests: list[int] = []

    def answer(messages: list[Any], info: Any) -> Any:
        del messages, info
        requests.append(1)
        raise ModelHTTPError(status_code=429, model_name="fake")

    built: list[_Metering] = []
    reports: list[str] = []

    def build(_: Any) -> _Metering:
        built.append(_Metering(FunctionModel(answer), calls=2))
        return built[0]

    asyncio.run(
        replay_tool.rerun(
            replay_tool.RerunOptions(copy=copy, model="anthropic:claude-test", bound=4),
            report=reports.append,
            build=build,
            check_model=lambda _: None,
            now=now,
        )
    )

    # Three attempts of the first call and one of the second are sent; the second's next
    # attempt is refused unsent, and the refusal is not retried.
    (engine,) = built
    assert len(requests) == 4
    assert engine.failures == ["ModelRateLimitError", "ModelError"]
    assert engine.runs == 1
    assert "the bound of 4 model calls is reached" in reports
    assert "4 model calls made (bound 4); 1 refused" in reports


def test_a_rerun_counts_a_call_that_names_its_own_route_as_the_reconciler_does(
    tmp_path: Path,
) -> None:
    # The reconciler names its route on every call (``complete(..., model=route)``), which
    # replaces the provider's default model for that call: it is counted all the same.
    copy = make_copy(tmp_path)
    requests: list[int] = []
    failures: list[str] = []

    def answer(messages: list[Any], info: Any) -> Any:
        del messages, info
        requests.append(1)
        return ModelResponse(parts=[TextPart("a reply")])

    class _Engine:
        def __init__(self) -> None:
            self.provider = RetryingProvider(
                replay_tool.composition.PydanticAIProvider(FunctionModel(answer)),
                policy=RetryPolicy(max_attempts=3, backoff_base_seconds=0.001),
                sleep=_no_wait,
            )

        async def observe_episodes(self) -> RunOutcome:
            messages = [Message(role=Role.USER, content="x")]
            await self.provider.complete(messages)
            for route in ("test", None):
                try:
                    await self.provider.complete(messages, model=route)
                except ModelError as exc:
                    failures.append(type(exc).__name__)
            return RunOutcome(processed=1)

        async def aclose(self) -> None:
            return None

    reports: list[str] = []
    asyncio.run(
        replay_tool.rerun(
            replay_tool.RerunOptions(copy=copy, model="anthropic:claude-test", bound=2),
            report=reports.append,
            build=lambda _: _Engine(),
            check_model=lambda _: None,
            now=now,
        )
    )

    # The named route ("test", pydantic-ai's offline model) takes the second request; the
    # third is refused unsent, whichever model it names.
    assert len(requests) == 1
    assert failures == ["ModelError"]
    assert "2 model calls made (bound 2); 1 refused" in reports


def test_a_counted_provider_refuses_a_named_route_once_the_bound_is_reached() -> None:
    meter = replay_tool.CallMeter(1, "the bound is reached")
    provider = replay_tool.CountedProvider("test", meter)
    messages = [Message(role=Role.USER, content="x")]

    asyncio.run(provider.complete(messages, model="test"))
    with pytest.raises(ModelError, match="the bound is reached"):
        asyncio.run(provider.complete(messages, model="test"))
    with pytest.raises(ModelError, match="the bound is reached"):
        asyncio.run(provider.complete(messages))

    assert (meter.made, meter.refused) == (1, 2)


# --- ADR-0354 §8:6-§8:7: understanding's structured calls ----------------------------------


def _with_reply_shape(tmp_path: Path, name: str, version: str) -> Path:
    """A copy whose activation A's understanding entry records ``reply_shape`` (§7:1)."""
    live = write_live(tmp_path)
    record = live / "diagnostics" / f"{ACT_A}.jsonl"
    record.write_text(
        record.read_text().replace(
            '"prompt":{"name":"understanding","version":"0123456789ab","origin":"default"}',
            '"prompt":{"name":"understanding","version":"0123456789ab","origin":"default"},'
            f'"reply_shape":{{"name":"{name}","version":"{version}"}}',
        )
    )
    copy = tmp_path / "copy"
    replay_tool.copy_data_dir(live, copy, retention=timedelta(days=1), now=now)
    return copy


def test_a_recorded_call_with_no_reply_shape_replays_as_a_plain_completion_marked_so(
    tmp_path: Path,
) -> None:
    """§8:7: written before the move, so sent as it was made, and marked as sent plain."""
    copy = make_copy(tmp_path)

    _replay(copy, Model(), candidates=("recorded",), sources=frozenset({"understanding"}))

    bodies = [one["body"] for each in _results(copy).values() for one in each]
    assert len(bodies) == 2
    assert all(one["sent_plain"] is True for one in bodies)
    assert all("structured" not in one for one in bodies)


def test_a_recorded_structured_call_replays_with_the_packages_shape_and_marks_its_version(
    tmp_path: Path,
) -> None:
    """§8:7: sent as a structured call with the shape of its recorded name, the result
    marked where the recorded version differs from the package's."""
    copy = _with_reply_shape(tmp_path, "ProposedActivationUnderstanding", "000000000000")
    model = Model(reply=json.dumps({"understanding": "Means what it says."}))

    _replay(
        copy,
        model,
        candidates=("recorded",),
        sources=frozenset({"understanding"}),
        activations=frozenset({ACT_A}),
    )

    (only,) = _results(copy)[f"{ACT_A}.replay.jsonl"]
    body = only["body"]
    assert body["structured"]["shape"] == "ProposedActivationUnderstanding"
    assert body["structured"]["version"] == reply_shape_version(ProposedActivationUnderstanding)
    assert body["structured"]["failure"] is None
    assert (body["recorded_shape_version"], body["shape_version_differs"]) == (
        "000000000000",
        True,
    )
    assert "sent_plain" not in body


def test_a_recorded_shape_the_package_holds_none_of_fails_that_call_naming_the_defect(
    tmp_path: Path,
) -> None:
    copy = _with_reply_shape(tmp_path, "NoSuchShape", "000000000000")
    model = Model()

    _replay(
        copy,
        model,
        candidates=("recorded",),
        sources=frozenset({"understanding"}),
        activations=frozenset({ACT_A}),
    )

    (only,) = _results(copy)[f"{ACT_A}.replay.jsonl"]
    failure = only["body"]["failure"]
    assert "the recorded reply shape is none the package holds" in failure["message"]
    assert model.systems == []


# --- ADR-0354 §9:8: the digest's and the observer's structured calls ------------------------


def _with_shapes(tmp_path: Path, shapes: dict[str, tuple[str, str]]) -> Path:
    """A copy whose given entries record a ``reply_shape``, by source (§7:1).

    ``shapes`` maps a source to the shape's name and version its given entries record.
    """
    live = write_live(tmp_path)
    for path in (live / "diagnostics").glob("*.jsonl"):
        written = []
        for line in path.read_text().splitlines():
            entry = json.loads(line)
            held = shapes.get(entry["source"])
            if held is not None and entry["kind"] == "given":
                entry["body"]["reply_shape"] = {"name": held[0], "version": held[1]}
            written.append(json.dumps(entry, separators=(",", ":")))
        path.write_text("".join(one + "\n" for one in written))
    copy = tmp_path / "copy"
    replay_tool.copy_data_dir(live, copy, retention=timedelta(days=1), now=now)
    return copy


def test_a_digest_and_an_observer_call_recorded_before_the_move_replay_plain_marked_so(
    tmp_path: Path,
) -> None:
    """§9:8, §8:7: a recording with no ``reply_shape`` is sent as it was made, and marked."""
    copy = make_copy(tmp_path)

    _replay(copy, Model(), candidates=("recorded",), sources=frozenset({"digesting", "observer"}))

    bodies = [one["body"] for each in _results(copy).values() for one in each]
    # The digest part, and the scout's one call written under each of two activations.
    assert len(bodies) == 3
    assert all(one["sent_plain"] is True for one in bodies)
    assert all("structured" not in one for one in bodies)


@pytest.mark.parametrize(
    ("source", "shape"),
    [
        ("digesting", DigestReply),
        ("observer", ScoutReplyShape),
        ("observer", PersonScoutReplyShape),
    ],
)
def test_a_recorded_structured_digest_or_observer_call_replays_with_its_shape(
    tmp_path: Path, source: str, shape: type[Any]
) -> None:
    """§9:8, §8:7: sent with the package's shape of the recorded name, its version marked."""
    copy = _with_shapes(tmp_path, {source: (shape.__name__, reply_shape_version(shape))})
    model = Model(reply=json.dumps({"evidence": []} if source == "digesting" else {}))

    _replay(copy, model, candidates=("recorded",), sources=frozenset({source}))

    bodies = [one["body"] for each in _results(copy).values() for one in each]
    assert bodies
    for body in bodies:
        assert body["structured"]["shape"] == shape.__name__
        assert body["structured"]["failure"] is None
        assert body["shape_version_differs"] is False
        assert "sent_plain" not in body


def test_every_moved_consumers_shape_is_one_a_recording_can_name() -> None:
    """§8:7, §9:8: each shape a moved stage records is found by its recorded name."""
    for shape in (
        DigestReply,
        ScoutReplyShape,
        PersonScoutReplyShape,
        FramingReplyShape,
        PlacementReplyShape,
        MattersPassReply,
        TidyUpReply,
    ):
        assert replay_tool.REPLY_SHAPES_BY_NAME[shape.__name__] is shape


def test_a_suite_case_is_sent_with_the_shape_its_stage_sends_under_its_flags() -> None:
    """§8:6, §9:8: the scout's person shape under its person flag, and its plain one else."""
    shape = replay_tool.structured_shape

    assert shape("observer_scout", {"person": True}) is PersonScoutReplyShape
    assert shape("observer_scout", {"person": False}) is ScoutReplyShape
    assert shape("observer_framing", {"person": True}) is FramingReplyShape
    assert shape("observer_placement", {}) is PlacementReplyShape
    assert shape("digesting", {}) is DigestReply
    assert shape("planning", {}) is None


@pytest.mark.parametrize(
    ("prompt", "shape"),
    [
        ("observer_scout", ScoutReplyShape),
        ("observer_framing", FramingReplyShape),
        ("observer_placement", PlacementReplyShape),
    ],
)
def test_the_observers_suite_reader_and_its_stage_read_one_reply_alike(
    prompt: str, shape: type[Any]
) -> None:
    """§9:8, §8:6: the suite reads an observer reply by the one rule, as the stage does."""
    findings = {"findings": [{"claim": "x", "rests_on": ["P1"]}]}
    replies = [
        json.dumps(findings),
        "```json\n" + json.dumps(findings) + "\n```",
        "Here it is: " + json.dumps(findings),
        json.dumps({"memories": [], "nothing": "One choice is no habit."}),
        json.dumps({"relations": [{"memory": "M1", "relation": "independent"}]}),
        "",
    ]
    for reply in replies:
        read = read_reply(shape, reply)
        stage = None if isinstance(read, ReplyFailure) else read.model_dump(mode="json")
        assert replay_tool.completion_reply(prompt, reply).reading == stage


def test_a_counted_provider_counts_a_structured_call_on_any_route_and_refuses_past_its_bound() -> (
    None
):
    """F2's gap, closed: a structured call naming its route is counted on the one meter."""
    meter = replay_tool.CallMeter(2, "the bound is reached")
    provider = replay_tool.CountedProvider("test", meter)
    messages = [Message(role=Role.USER, content="x")]

    asyncio.run(provider.complete_structured(messages, DigestReply))
    asyncio.run(provider.complete_structured(messages, DigestReply, model="test"))
    with pytest.raises(ModelError, match="the bound is reached"):
        asyncio.run(provider.complete_structured(messages, DigestReply, model="test"))
    with pytest.raises(ModelError, match="the bound is reached"):
        asyncio.run(provider.complete_structured(messages, DigestReply))

    assert (meter.made, meter.refused) == (2, 2)


def test_a_rerun_counts_the_observers_and_the_reconcilers_structured_calls(
    tmp_path: Path,
) -> None:
    """§8:2-§8:4: every provider the composition builds counts its structured calls too.

    The observer's routes ask with no ``model=``, and the reconciler names its route on
    every call: each is a ``PydanticAIProvider`` the composition builds, so each counts.
    """
    copy = make_copy(tmp_path)
    requests: list[int] = []
    failures: list[str] = []

    def answer(messages: list[Any], info: Any) -> Any:
        del messages, info
        requests.append(1)
        return ModelResponse(parts=[TextPart('{"evidence": []}')])

    class _Engine:
        def __init__(self) -> None:
            self.route = RetryingProvider(
                replay_tool.composition.PydanticAIProvider(FunctionModel(answer)),
                policy=RetryPolicy(max_attempts=3, backoff_base_seconds=0.001),
                sleep=_no_wait,
            )

        async def observe_episodes(self) -> RunOutcome:
            messages = [Message(role=Role.USER, content="x")]
            await self.route.complete_structured(messages, DigestReply)
            for route in ("test", None):
                try:
                    await self.route.complete_structured(messages, DigestReply, model=route)
                except ModelError as exc:
                    failures.append(type(exc).__name__)
            return RunOutcome(processed=1)

        async def aclose(self) -> None:
            return None

    reports: list[str] = []
    asyncio.run(
        replay_tool.rerun(
            replay_tool.RerunOptions(copy=copy, model="anthropic:claude-test", bound=2),
            report=reports.append,
            build=lambda _: _Engine(),
            check_model=lambda _: None,
            now=now,
        )
    )

    assert len(requests) == 1
    assert failures == ["ModelError"]
    assert "2 model calls made (bound 2); 1 refused" in reports


def test_the_suites_reader_and_the_stage_read_one_reply_alike() -> None:
    """§8:6, §12:6: both read by ``core``'s one rule with the proposal as the shape."""
    replies = [
        json.dumps({"understanding": "Fine.", "cites": ["H1"]}),
        "```json\n" + json.dumps({"understanding": "Fenced."}) + "\n```",
        json.dumps({"understanding": "Extra.", "answers": []}),
        "not json",
        "",
    ]
    for reply in replies:
        read = read_reply(ProposedActivationUnderstanding, reply)
        stage = None if isinstance(read, ReplyFailure) else read.model_dump(mode="json")
        assert replay_tool.completion_reply("understanding", reply).reading == stage


# --- ADR-0355 §8:2, §9:2: the counted providers keep a summary where built to -------------

_EVIDENCE: Final = '{"evidence": []}'
_SUMMARY: Final = "Weighing the evidence."


def _thinking_world(requests: list[int]) -> FunctionModel:
    """A model whose every response thinks before it replies, counting each request."""

    def answer(messages: list[Any], info: Any) -> Any:
        del messages, info
        requests.append(1)
        return ModelResponse(parts=[ThinkingPart(_SUMMARY), TextPart(_EVIDENCE)])

    return FunctionModel(answer)


@pytest.mark.parametrize("keeps", [True, False], ids=["kept", "not-kept"])
def test_a_counted_provider_keeps_a_summary_where_built_to_on_any_route(
    monkeypatch: pytest.MonkeyPatch, keeps: bool
) -> None:
    """The argument reaches the default model's call and a call naming its route alike."""
    requests: list[int] = []
    world = _thinking_world(requests)
    monkeypatch.setattr(replay_tool, "infer_model", lambda wrapped: world)
    meter = replay_tool.CallMeter(2, "the bound is reached")
    provider = replay_tool.CountedProvider("test", meter, thinking_summaries=keeps)
    messages = [Message(role=Role.USER, content="x")]

    default = asyncio.run(provider.complete_structured(messages, DigestReply))
    named = asyncio.run(provider.complete_structured(messages, DigestReply, model="test"))

    expected = _SUMMARY if keeps else None
    assert (default.exchange.thinking, named.exchange.thinking) == (expected, expected)
    assert (default.exchange.reply, named.exchange.reply) == (_EVIDENCE, _EVIDENCE)
    assert (meter.made, len(requests)) == (2, 2)


def test_a_rerun_keeps_the_observers_summaries_and_not_the_reconcilers_and_counts_each_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§8:2: the package composed as the rerun composes it, every call still counted.

    The observer's two routes are built keeping summaries, the record being on in a rerun
    (ADR-0335 §7:1), and the reconciler's is not; each is a counted provider on the one
    meter, so a call past the bound is refused unsent whichever route makes it.
    """
    requests: list[int] = []
    world = _thinking_world(requests)
    monkeypatch.setattr(replay_tool, "infer_model", lambda wrapped: world)
    live = tmp_path / "live"
    live.mkdir(mode=0o700)
    copy = tmp_path / "copy"
    replay_tool.copy_data_dir(live, copy, retention=timedelta(days=1), now=now)
    kept: dict[str, bool] = {}
    thinking: list[str | None] = []
    failures: list[str] = []

    class _Composed:
        """The composed engine, whose observer run calls each of its routes."""

        def __init__(self, engine: Any) -> None:
            self.engine = engine

        async def observe_episodes(self) -> RunOutcome:
            observer = self.engine._observer
            reconciler = observer._writer._writes._writer._reconciler
            routes = {
                "scout": observer._scout,
                "commit": observer._commit,
                "reconciler": reconciler._completer,
            }
            for name, route in routes.items():
                assert type(route._inner) is replay_tool.CountedProvider
                kept[name] = route._inner.thinking_summaries
            messages = [Message(role=Role.USER, content="x")]
            for route, named in (
                (observer._scout, None),
                (observer._commit, None),
                (reconciler._completer, reconciler._route),
                (observer._scout, None),
            ):
                try:
                    reply = await route.complete_structured(messages, DigestReply, model=named)
                except ModelError as exc:
                    failures.append(type(exc).__name__)
                else:
                    thinking.append(reply.exchange.thinking)
            return RunOutcome(processed=1)

        async def aclose(self) -> None:
            await self.engine.aclose()

    reports: list[str] = []
    asyncio.run(
        replay_tool.rerun(
            replay_tool.RerunOptions(
                copy=copy, model="anthropic:claude-test", bound=3, embedder=EmbedderKind.HASHING
            ),
            report=reports.append,
            build=lambda settings: _Composed(replay_tool.build_engine(settings)),
            check_model=lambda _: None,
            now=now,
        )
    )

    assert kept == {"scout": True, "commit": True, "reconciler": False}
    assert thinking == [_SUMMARY, _SUMMARY, None]
    assert len(requests) == 3
    assert failures == ["ModelError"]
    assert "3 model calls made (bound 3); 1 refused" in reports
