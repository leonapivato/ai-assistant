#!/usr/bin/env python3
"""Decide whether a CI Codex review should run, and with what parameters.

Extracted from ``.github/workflows/codex-review.yml`` so the event routing,
fork rejection, authorization, freshness (SHA-match) and command parsing are
unit-testable rather than untested shell buried in YAML (ADR-0012). The workflow
gathers the raw inputs — GitHub event fields and ``gh`` API results — into
environment variables and calls this; every *decision* lives here.

Reads from the environment: ``HAS_KEY``, ``EVENT``, ``WR_SHA``, ``WR_PR_NUMBER``,
``PR_JSON``, ``COMMENT_PERM``, ``COMMENT_BODY``, ``ISSUE_NUM``. Writes ``KEY=VALUE`` lines to
stdout — ``run``, ``num``, ``sha``, ``persona`` — ready to append to
``$GITHUB_OUTPUT``.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

# Repository permission levels that authorize a (paid) /review. author_association
# is not enough — a COLLABORATOR may be read-only — so the workflow resolves the
# actual permission and passes it here (ADR-0012 §4).
_WRITE_PERMISSIONS = frozenset({"admin", "write", "maintain"})
_COMMAND = "/review"
_DEFAULT_PERSONA = "adversarial"
_ARCHITECTURE = "architecture"


@dataclass(frozen=True)
class Decision:
    """The resolved review parameters.

    Attributes:
        run: Whether a review should run at all.
        num: The PR number to review and comment on.
        sha: The commit the review covers (freshness header, ADR-0012 §5).
        persona: The review lens — ``adversarial`` or ``architecture``.
    """

    run: bool
    num: str
    sha: str
    persona: str

    @classmethod
    def skip(cls) -> Decision:
        """Return the do-not-run decision."""
        return cls(run=False, num="", sha="", persona=_DEFAULT_PERSONA)


def _pr_field(pr_json: str, field: str) -> str:
    """Return a string field from the PR JSON, or ``""`` if absent/malformed.

    Args:
        pr_json: The raw JSON from ``gh pr view --json ...``.
        field: The field to read.

    Returns:
        The field's value as a string, or ``""`` when the JSON is empty,
        malformed, or lacks the field.
    """
    try:
        data = json.loads(pr_json)
    except ValueError, TypeError:
        return ""
    if not isinstance(data, dict):
        return ""  # valid JSON but not an object (e.g. [], null, "text")
    value = data.get(field)
    return "" if value is None else str(value)


def _is_fork(pr_json: str) -> bool:
    """Return whether the PR head is in a forked repository.

    A fork head must never be reviewed in CI: the job runs with the secret, and
    the head is untrusted (ADR-0012 §4). Forks are the escalation path, handled
    out of band.
    """
    return _pr_field(pr_json, "isCrossRepository") == "True"


def _persona_from_command(comment_body: str) -> str | None:
    """Return the persona for a ``/review [persona]`` comment.

    Args:
        comment_body: The full comment body.

    Returns:
        ``architecture`` or ``adversarial`` when the first token is exactly
        ``/review``; ``None`` when the comment is not the command (e.g.
        ``/reviewarchitecture`` or ``/review-this``), so a near-miss cannot
        trigger a paid run.
    """
    tokens = comment_body.split()
    if not tokens or tokens[0] != _COMMAND:
        return None
    rest = tokens[1:]
    requested = rest[0] if rest else ""
    return _ARCHITECTURE if requested == _ARCHITECTURE else _DEFAULT_PERSONA


def _decide_workflow_run(*, wr_sha: str, wr_pr_number: str, pr_json: str) -> Decision:
    """Decide the automatic (gate-succeeded) path."""
    if not wr_pr_number:
        return Decision.skip()  # fork PR: no pull_requests entry
    if _is_fork(pr_json):
        return Decision.skip()  # fork head: never runs with the secret
    if _pr_field(pr_json, "isDraft") != "False":
        return Decision.skip()  # only ready PRs auto-review
    head = _pr_field(pr_json, "headRefOid")
    if not wr_sha or head != wr_sha:
        # Fail closed on a missing SHA; require the gate SHA to still be the head
        # (a newer push owns its own gate run + review).
        return Decision.skip()
    return Decision(run=True, num=wr_pr_number, sha=wr_sha, persona=_DEFAULT_PERSONA)


def _decide_comment(
    *, comment_perm: str, comment_body: str, issue_num: str, pr_json: str
) -> Decision:
    """Decide the on-demand ``/review`` path."""
    if comment_perm not in _WRITE_PERMISSIONS:
        return Decision.skip()  # not write access
    persona = _persona_from_command(comment_body)
    if persona is None:
        return Decision.skip()  # not exactly the /review command
    if _is_fork(pr_json):
        return Decision.skip()  # fork head: never runs with the secret
    sha = _pr_field(pr_json, "headRefOid")
    if not sha or not issue_num:
        return Decision.skip()  # need a PR to comment on and a commit to name
    return Decision(run=True, num=issue_num, sha=sha, persona=persona)


def decide(env: Mapping[str, str]) -> Decision:
    """Resolve whether and how to review, from the gathered inputs.

    Args:
        env: The environment the workflow populated — ``HAS_KEY``, ``EVENT``,
            ``WR_SHA``, ``WR_PR_NUMBER``, ``PR_JSON``, ``COMMENT_PERM``,
            ``COMMENT_BODY``, ``ISSUE_NUM``. Missing keys are treated as empty;
            ``HAS_KEY`` other than ``"true"`` makes the review inert.

    Returns:
        The review decision.
    """
    if env.get("HAS_KEY", "") != "true":
        return Decision.skip()  # no OPENAI_API_KEY provisioned -> CI review is inert
    event = env.get("EVENT", "")
    pr_json = env.get("PR_JSON", "")
    if event == "workflow_run":
        return _decide_workflow_run(
            wr_sha=env.get("WR_SHA", ""),
            wr_pr_number=env.get("WR_PR_NUMBER", ""),
            pr_json=pr_json,
        )
    if event == "issue_comment":
        return _decide_comment(
            comment_perm=env.get("COMMENT_PERM", ""),
            comment_body=env.get("COMMENT_BODY", ""),
            issue_num=env.get("ISSUE_NUM", ""),
            pr_json=pr_json,
        )
    return Decision.skip()


def main() -> None:
    """Read the environment, decide, and print ``KEY=VALUE`` lines to stdout."""
    decision = decide(os.environ)
    print(f"run={'true' if decision.run else 'false'}")
    print(f"num={decision.num}")
    print(f"sha={decision.sha}")
    print(f"persona={decision.persona}")


if __name__ == "__main__":
    main()
