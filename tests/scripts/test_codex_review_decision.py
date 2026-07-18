"""Tests for the CI Codex-review decision helper (scripts/codex_review_decision.py).

The helper is invoked as a subprocess — exactly as the workflow calls it — so the
test exercises the real env-in / KEY=VALUE-out contract, not an imported shape.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

_SCRIPT = Path(__file__).parents[2] / "scripts" / "codex_review_decision.py"


def test_helper_uses_only_single_type_excepts() -> None:
    # The CI runner invokes this script with its *stock* python3 (older than the
    # project's 3.14). A multi-type `except (A, B)` is reformatted by ruff to the
    # 3.14-only `except A, B:` — a SyntaxError there. Keep excepts single-type.
    tree = ast.parse(_SCRIPT.read_text())
    multi = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.ExceptHandler) and isinstance(n.type, ast.Tuple)
    ]
    assert not multi, "multi-type except becomes 3.14-only syntax; use single-type here"


def _run(env: dict[str, str]) -> dict[str, str]:
    """Run the helper with ``env`` and parse its ``KEY=VALUE`` output."""
    result = subprocess.run(  # noqa: S603  # fixed interpreter + in-repo script, test-controlled env
        [sys.executable, str(_SCRIPT)],
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )
    out: dict[str, str] = {}
    for line in result.stdout.splitlines():
        key, _, value = line.partition("=")
        out[key] = value
    return out


def _workflow_run(
    *, sha: str, pr_number: str, is_draft: bool, head: str, fork: bool = False
) -> dict[str, str]:
    return {
        "HAS_KEY": "true",
        "EVENT": "workflow_run",
        "WR_SHA": sha,
        "WR_PR_NUMBER": pr_number,
        "PR_JSON": (
            f'{{"isDraft": {"true" if is_draft else "false"}, '
            f'"headRefOid": "{head}", '
            f'"isCrossRepository": {"true" if fork else "false"}}}'
        ),
    }


def _comment(
    *, perm: str, body: str, issue_num: str, head: str, fork: bool = False
) -> dict[str, str]:
    return {
        "HAS_KEY": "true",
        "EVENT": "issue_comment",
        "COMMENT_PERM": perm,
        "COMMENT_BODY": body,
        "ISSUE_NUM": issue_num,
        "PR_JSON": (
            f'{{"headRefOid": "{head}", "isCrossRepository": {"true" if fork else "false"}}}'
        ),
    }


# --- automatic (workflow_run) path ------------------------------------------


def test_ready_pr_at_gate_sha_runs_adversarial() -> None:
    out = _run(_workflow_run(sha="abc123", pr_number="7", is_draft=False, head="abc123"))
    assert out == {"run": "true", "num": "7", "sha": "abc123", "persona": "adversarial"}


def test_draft_pr_is_not_auto_reviewed() -> None:
    out = _run(_workflow_run(sha="abc123", pr_number="7", is_draft=True, head="abc123"))
    assert out["run"] == "false"


def test_stale_gate_sha_is_skipped() -> None:
    # The gate passed on an older commit; the PR head has since moved on.
    out = _run(_workflow_run(sha="old", pr_number="7", is_draft=False, head="new"))
    assert out["run"] == "false"


def test_fork_pr_without_number_is_skipped() -> None:
    out = _run(_workflow_run(sha="abc", pr_number="", is_draft=False, head="abc"))
    assert out["run"] == "false"


def test_fork_head_is_skipped_even_with_a_number() -> None:
    # Belt-and-suspenders: a fork head must not be reviewed with the secret.
    out = _run(_workflow_run(sha="abc", pr_number="7", is_draft=False, head="abc", fork=True))
    assert out["run"] == "false"


def test_empty_sha_fails_closed() -> None:
    # An empty gate SHA must not match an empty/absent head and authorize a run.
    env = {
        "HAS_KEY": "true",
        "EVENT": "workflow_run",
        "WR_SHA": "",
        "WR_PR_NUMBER": "7",
        "PR_JSON": '{"isDraft": false, "headRefOid": null, "isCrossRepository": false}',
    }
    assert _run(env)["run"] == "false"


def test_malformed_pr_json_is_skipped_not_crashed() -> None:
    env = {
        "HAS_KEY": "true",
        "EVENT": "workflow_run",
        "WR_SHA": "abc",
        "WR_PR_NUMBER": "7",
        "PR_JSON": "not json",
    }
    assert _run(env)["run"] == "false"


def test_non_object_pr_json_is_skipped_not_crashed() -> None:
    # Valid JSON that is not an object must not raise on field access.
    for payload in ("[]", "null", '"text"', "42"):
        env = {
            "HAS_KEY": "true",
            "EVENT": "workflow_run",
            "WR_SHA": "abc",
            "WR_PR_NUMBER": "7",
            "PR_JSON": payload,
        }
        assert _run(env)["run"] == "false", payload


# --- on-demand (/review comment) path ---------------------------------------


def test_comment_from_writer_runs_and_defaults_to_adversarial() -> None:
    out = _run(_comment(perm="write", body="/review", issue_num="9", head="zzz"))
    assert out == {"run": "true", "num": "9", "sha": "zzz", "persona": "adversarial"}


def test_comment_can_request_architecture_persona() -> None:
    out = _run(_comment(perm="admin", body="/review architecture", issue_num="9", head="zzz"))
    assert out["run"] == "true"
    assert out["persona"] == "architecture"


def test_comment_unknown_persona_falls_back_to_adversarial() -> None:
    out = _run(_comment(perm="maintain", body="/review please", issue_num="9", head="zzz"))
    assert out["persona"] == "adversarial"


def test_comment_from_read_only_actor_is_ignored() -> None:
    out = _run(_comment(perm="read", body="/review", issue_num="9", head="zzz"))
    assert out["run"] == "false"


def test_comment_from_triage_actor_is_ignored() -> None:
    # A collaborator with triage (not write) must not trigger a paid review.
    out = _run(_comment(perm="triage", body="/review", issue_num="9", head="zzz"))
    assert out["run"] == "false"


def test_comment_on_a_fork_pr_is_ignored() -> None:
    out = _run(_comment(perm="admin", body="/review", issue_num="9", head="zzz", fork=True))
    assert out["run"] == "false"


def test_review_command_must_be_an_exact_word() -> None:
    # A near-miss must not trigger a run, even from a writer.
    for body in ("/reviewarchitecture", "/review-this", "please /review"):
        out = _run(_comment(perm="write", body=body, issue_num="9", head="zzz"))
        assert out["run"] == "false", body


def test_comment_without_a_pr_number_is_skipped() -> None:
    # A valid command from a writer must still not run without a PR to comment on.
    out = _run(_comment(perm="write", body="/review", issue_num="", head="zzz"))
    assert out["run"] == "false"


def test_unknown_event_is_skipped() -> None:
    assert _run({"HAS_KEY": "true", "EVENT": "push"})["run"] == "false"


def test_missing_key_makes_review_inert() -> None:
    # An otherwise-eligible ready PR must not run when no OPENAI_API_KEY is set.
    env = _workflow_run(sha="abc123", pr_number="7", is_draft=False, head="abc123")
    env["HAS_KEY"] = "false"
    assert _run(env)["run"] == "false"
