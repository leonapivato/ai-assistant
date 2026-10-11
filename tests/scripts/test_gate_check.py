"""Tests for ``scripts/gate_check.py``, the ``gate`` half of ``just ready``.

ADR-0311 §4: the PR leaves draft only while ``gate`` is green on its current head
commit, and the refusal names the state it saw — pending, failing, cancelled or
absent. The recipe itself has no test (CI carries no ``just``, #1615), so the rule
lives here.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from _repo_template import GIT, seed_repo

if TYPE_CHECKING:
    from types import ModuleType

_SCRIPT = Path(__file__).parents[2] / "scripts" / "gate_check.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("gate_check", _SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_MODULE = _load()
_SHA = "a" * 40


def _run(
    name: str = "gate",
    status: str = "COMPLETED",
    conclusion: str = "SUCCESS",
    completed: str = "2026-10-11T10:00:00Z",
) -> dict[str, object]:
    return {
        "__typename": "CheckRun",
        "name": name,
        "status": status,
        "conclusion": conclusion if status == "COMPLETED" else "",
        "completedAt": completed if status == "COMPLETED" else None,
        "workflowName": "gate",
    }


# --- judge: what the rollup says -------------------------------------------


@pytest.mark.parametrize(
    ("rollup", "state"),
    [
        ([_run()], "green"),
        ([_run(status="IN_PROGRESS")], "pending"),
        ([_run(status="QUEUED")], "pending"),
        ([_run(conclusion="FAILURE")], "failing"),
        ([_run(conclusion="TIMED_OUT")], "failing"),
        ([_run(conclusion="CANCELLED")], "cancelled"),
        ([_run(conclusion="SKIPPED")], "skipped"),
        ([], "absent"),
        ([_run(name="lint")], "absent"),
    ],
)
def test_judge_names_the_state(rollup: list[object], state: str) -> None:
    assert _MODULE.judge(rollup) == state


def test_a_commit_status_named_gate_is_not_the_check() -> None:
    status = {"__typename": "StatusContext", "context": "gate", "state": "SUCCESS"}
    assert _MODULE.judge([status]) == "absent"


def test_another_check_cannot_make_gate_green() -> None:
    assert _MODULE.judge([_run(name="other"), _run(conclusion="FAILURE")]) == "failing"


def test_the_latest_completed_run_decides() -> None:
    old_fail = _run(conclusion="FAILURE", completed="2026-10-11T09:00:00Z")
    new_pass = _run(completed="2026-10-11T10:00:00Z")
    assert _MODULE.judge([old_fail, new_pass]) == "green"
    assert (
        _MODULE.judge([new_pass, _run(conclusion="FAILURE", completed="2026-10-11T11:00:00Z")])
        == "failing"
    )


def test_any_run_in_progress_is_pending_even_beside_a_green_one() -> None:
    assert _MODULE.judge([_run(), _run(status="IN_PROGRESS")]) == "pending"


# --- check: the decision, the wait and the head ----------------------------


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def _check(
    answers: list[list[object]],
    *,
    wait: float = 60.0,
    pr_head: str = _SHA,
    local: str = _SHA,
) -> tuple[int, str, _Clock, list[str]]:
    clock = _Clock()
    said: list[str] = []
    queue = list(answers)

    def read() -> tuple[str, list[object]]:
        return pr_head, queue.pop(0) if len(queue) > 1 else queue[0]

    status, message = _MODULE.check(
        wait=wait,
        interval=10.0,
        world=_MODULE.World(
            read=read, head=lambda: local, sleep=clock.sleep, clock=clock.time, say=said.append
        ),
    )
    return status, message, clock, said


def test_green_passes_without_waiting() -> None:
    status, message, clock, said = _check([[_run()]])
    assert status == 0
    assert "green" in message
    assert clock.sleeps == []
    assert said == []


@pytest.mark.parametrize(
    ("conclusion", "state"), [("FAILURE", "failing"), ("CANCELLED", "cancelled")]
)
def test_a_final_state_refuses_at_once_and_names_it(conclusion: str, state: str) -> None:
    status, message, clock, _ = _check([[_run(conclusion=conclusion)]])
    assert status == 1
    assert f"is {state} on {_SHA[:12]}" in message
    assert clock.sleeps == []


@pytest.mark.parametrize(
    ("rollup", "state"), [([_run(status="IN_PROGRESS")], "pending"), ([], "absent")]
)
def test_an_undecided_check_is_waited_on_then_refused_naming_it(
    rollup: list[object], state: str
) -> None:
    status, message, clock, said = _check([rollup], wait=30.0)
    assert status == 3
    assert f"still {state}" in message
    assert "run `just ready` again" in message
    assert sum(clock.sleeps) == pytest.approx(30.0)
    assert len(said) == 1


def test_a_pending_check_that_turns_green_passes() -> None:
    status, _, clock, _ = _check([[_run(status="IN_PROGRESS")], [_run()]])
    assert status == 0
    assert clock.sleeps == [10.0]


def test_a_pending_check_that_fails_refuses() -> None:
    status, message, _, _ = _check([[_run(status="IN_PROGRESS")], [_run(conclusion="FAILURE")]])
    assert status == 1
    assert "is failing" in message


def test_no_wait_refuses_a_pending_check_without_sleeping() -> None:
    status, _, clock, _ = _check([[_run(status="IN_PROGRESS")]], wait=0.0)
    assert status == 3
    assert clock.sleeps == []


def test_a_pr_head_that_is_not_local_head_refuses_even_when_green() -> None:
    status, message, _, _ = _check([[_run()]], pr_head="b" * 40)
    assert status == 1
    assert "push first" in message


# --- the CLI, through a fake gh in a real repository -----------------------


def _repo(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    seed_repo(repo)
    (repo / "f.txt").write_text("one\n")
    subprocess.run([GIT, "add", "f.txt"], cwd=repo, check=True)  # noqa: S603
    subprocess.run([GIT, "commit", "-qm", "base"], cwd=repo, check=True)  # noqa: S603
    head = subprocess.run(  # noqa: S603
        [GIT, "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()
    return repo, head


def _cli(tmp_path: Path, repo: Path, answer: str, *args: str) -> subprocess.CompletedProcess[str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    gh = bin_dir / "gh"
    gh.write_text(
        "#!/usr/bin/env bash\n"
        '[[ "$1 $2 $3 $4" == "pr view --json headRefOid,statusCheckRollup" ]] || exit 9\n'
        'cat "$GH_ANSWER"\n'
    )
    gh.chmod(0o755)
    answer_file = tmp_path / "answer.json"
    answer_file.write_text(answer)
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    env["GH_ANSWER"] = str(answer_file)
    return subprocess.run(  # noqa: S603  # fixed argv, no shell
        [sys.executable, str(_SCRIPT), *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def test_cli_passes_on_green(tmp_path: Path) -> None:
    repo, head = _repo(tmp_path)
    answer = json.dumps({"headRefOid": head, "statusCheckRollup": [_run()]})
    done = _cli(tmp_path, repo, answer)
    assert done.returncode == 0, done.stderr
    assert "green" in done.stdout


def test_cli_refuses_pending_naming_it(tmp_path: Path) -> None:
    repo, head = _repo(tmp_path)
    answer = json.dumps({"headRefOid": head, "statusCheckRollup": [_run(status="IN_PROGRESS")]})
    done = _cli(tmp_path, repo, answer, "--wait", "0")
    assert done.returncode == 3
    assert "still pending" in done.stderr


def test_cli_refuses_without_a_pr(tmp_path: Path) -> None:
    repo, _ = _repo(tmp_path)
    done = _cli(tmp_path, repo, json.dumps({"headRefOid": "", "statusCheckRollup": []}))
    assert done.returncode == 1
    assert "no PR found" in done.stderr
