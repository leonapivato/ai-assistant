"""Tests for ``scripts/prompt_replay.py`` (ADR-0335).

The tool is loaded by its path, as every script here is: it is no package, and nothing in
``ai_assistant`` may import it (§2:2). Its record is written with ADR-0314's own store
(``_replay_record``), and its model is a ``FunctionModel`` sent to through the package's
own model layer, so no call leaves the machine and nothing contacts a hub.
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import sqlite3
import stat
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

import ai_assistant
from ai_assistant.core.config import EmbedderKind
from ai_assistant.orchestration import planning
from ai_assistant.orchestration.observer.stage import RunOutcome
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

#: An understanding template that branches on both of its flags.
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
        flags=("understanding.recalled=true", "understanding.stories=false"),
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
        assert one["flags"] == {"recalled": True, "stories": False}
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


def test_a_template_is_left_out_where_no_flags_are_recorded_or_stated(tmp_path: Path) -> None:
    copy = make_copy(tmp_path)
    model = Model()
    reports: list[str] = []

    _replay(copy, model, reports, candidates=(str(_template(tmp_path)),))

    assert model.systems == []
    assert "left out: 2 (no flags recorded or stated)" in reports
    assert _results(copy) == {}


def test_a_template_is_rendered_under_the_flags_the_entry_records(tmp_path: Path) -> None:
    live = write_live(tmp_path)
    record = live / "diagnostics" / f"{ACT_A}.jsonl"
    record.write_text(
        record.read_text().replace(
            '"prompt":{"name":"understanding","version":"0123456789ab","origin":"default"}',
            '"prompt":{"name":"understanding","version":"0123456789ab","origin":"default",'
            '"flags":{"recalled":false,"stories":true}}',
        )
    )
    copy = tmp_path / "copy"
    replay_tool.copy_data_dir(live, copy, retention=timedelta(days=1), now=now)
    model = Model()

    _replay(copy, model, candidates=(str(_template(tmp_path)),), activations=frozenset({ACT_A}))

    assert model.systems == ["Candidate understanding instruction."]
    (only,) = _results(copy)[f"{ACT_A}.replay.jsonl"]
    assert only["body"]["flags"] == {"recalled": False, "stories": True}
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


def test_stated_flags_must_name_declared_flags_and_state_every_one(tmp_path: Path) -> None:
    declared = replay_tool.declared_prompts()

    for stated, defect in (
        (["understanding.recalled=true"], "unstated"),
        (["understanding.nothing=true"], "names no flag"),
        (["understanding.recalled=perhaps", "understanding.stories=no"], "no true or false"),
    ):
        with pytest.raises(replay_tool.ReplayError, match=defect):
            replay_tool.parse_flags(stated, declared)
    assert replay_tool.parse_flags(
        ["understanding.recalled=yes", "understanding.stories=0"], declared
    ) == {"understanding": {"recalled": True, "stories": False}}


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


def test_nothing_printed_comes_from_an_entry_or_a_reply(tmp_path: Path) -> None:
    copy = make_copy(tmp_path)
    reports: list[str] = []

    _replay(
        copy,
        Model(),
        reports,
        candidates=(str(_template(tmp_path)), "recorded"),
        flags=("understanding.recalled=true", "understanding.stories=true"),
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


def test_a_rerun_composes_the_real_package_over_a_copy(tmp_path: Path) -> None:
    live = tmp_path / "live"
    (live / "prompts").mkdir(parents=True, mode=0o700)
    (live / "prompts" / "understanding.txt").write_text(TEMPLATE)
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


def test_the_prompt_key_the_package_writes_is_read_for_its_flags(tmp_path: Path) -> None:
    # ADR-0335 §9:1's key as the package itself builds it, for a prompt with flags and
    # for one that declares none, which records an empty object.
    declared = replay_tool.declared_prompts()
    shipped = {
        name: replay_tool.load_candidate(
            str(Path(planning.__file__).parent / f"{name}.txt"), declared
        ).template
        for name in ("understanding", "digesting")
    }
    understood = shipped["understanding"].rendered(flags={"recalled": True, "stories": False})
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
    assert bodies["understanding"]["flags"] == {"recalled": True, "stories": False}
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
