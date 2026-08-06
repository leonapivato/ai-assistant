"""Tests for `scripts/ship.sh --drill` — the pre-push moved-base check (#751).

A lane about to push a rebased branch wants to know, before it spends, whether
its existing artifact still covers HEAD or whether the base move costs a Codex
round. That is ADR-0027 §2's question. It used to be answered by a **replica**
assembled from `ship`'s parts, and issue #751 records two ways the replica
returned the *permissive* answer — "floor clear" — for a base move that in fact
breaches §3's floor:

1. **The helper is out of the replica's scope.** `_is_floor_path` is defined
   outside the `>>> shared-patch-identity` markers, and the markers are what a
   lane is told to source. `_is_floor_path "$p" && breach=1` with no such
   function fails, the `&&` does not fire, and nothing is ever marked.
2. **The replica ran before the rebase.** `git merge-base FETCH_HEAD HEAD` is
   then still the *old* base, so the base-move range is empty and every floor
   test passes over nothing — with every helper correctly in scope.

Both produce a verdict indistinguishable from a correct "clear", and nothing
downstream tells them apart. So the invariant these tests pin is not "the drill
computes the floor correctly" but the stronger one the issue asks for: **every
exit that says "clear" has actually evaluated the floor over a named file set,
and every exit that has not evaluated it says so instead.**

The other half is that the drill is not a *model* of `ship` — it is `ship`,
stopped before the write. So each case below is run twice where the comparison is
meaningful, once with `--drill` and once without, and the two must agree.

Helpers come from `test_ship` and `test_ship_base_drift` rather than being
re-derived, for the reason those modules already give: a second, subtly
different fake is how #45 shipped a no-op with green tests.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import TYPE_CHECKING

sys.path.insert(0, str(Path(__file__).parent))
from test_ship import (
    _VERDICT,
    _fake_gh,
    _git,
    _record_review,
    _run_ship,
    _shared_patch_identity_block,
)
from test_ship_base_drift import (
    _NEAR_LINE,
    _REVIEWED,
    _advance_base,
    _edit_line,
    _init_repo,
    _review_then_move,
)

if TYPE_CHECKING:
    from collections.abc import Callable

# One §3 floor path and one ordinary path, so a breaching base move and a
# clearing one differ in nothing but which file they land in.
_FLOOR_PATH = "docs/adr/0001-record-architecture-decisions.md"
_ORDINARY_PATH = "src/ai_assistant/orchestration/loop.py"


def _review_then_move_unrebased(
    repo: Path, tmp_path: Path, mutate: Callable[[Path], object]
) -> None:
    """Record a review, land a commit on `origin/main`, and do NOT rebase.

    The state every lane is in at the moment it is told to "rebase, re-gate,
    push": `origin/main` has moved, the branch has not. `ship` is legitimately
    happy here — a merge to `main` does not move a PR's merge base — which is
    exactly why a replica reading `ship`'s parameterisation in this state gets a
    confident answer to a question nobody asked.
    """
    sha = _git(repo, "rev-parse", "HEAD")
    _fake_gh(tmp_path / "bin")
    old_base = _git(repo, "merge-base", "main", sha)
    _record_review(repo, sha, "adversarial", f"a real finding\n{_VERDICT}\n", base_sha=old_base)
    _advance_base(repo, mutate, rebase=False)


# --- Mechanism 2: the drill run before the rebase ----------------------------


def test_the_drill_refuses_before_the_rebase_rather_than_clearing_the_floor(
    tmp_path: Path,
) -> None:
    """#751's second mechanism, in the exact shape that produced it.

    `origin/main` has moved and the move lands squarely on the floor
    (`docs/adr/**`), so the answer the lane is about to need is "this costs a
    round". Un-rebased, the merge base is still the old base, the base-move range
    is empty, and a replica computes a clear over nothing. The drill must refuse
    to answer instead — and the assertion that matters most is the negative one:
    the word "clear" must not appear anywhere in a run that evaluated nothing.
    """
    repo = tmp_path / "repo"
    _init_repo(repo)
    _review_then_move_unrebased(repo, tmp_path, lambda r: _edit_line(r, _FLOOR_PATH, 40, "moved"))
    sha = _git(repo, "rev-parse", "HEAD")

    result = _run_ship(repo, tmp_path, pr_sha=sha, args=("--drill",))

    assert result.returncode != 0, result.stderr
    assert "does not contain the fetched tip" in result.stderr
    assert "rebase first" in result.stderr
    # The refusal is reached before the report can run at all, so neither half of
    # a floor claim is emitted: no file set is listed and nothing is cleared over
    # it. (The refusal's own prose says the word "clear" while explaining what it
    # is refusing to print, which is why these are matched on the report's own
    # wording rather than on the bare word.)
    assert "files examined" not in result.stderr
    assert "clear over" not in result.stderr
    assert not (tmp_path / "comment.md").exists()


def test_ship_itself_is_unchanged_before_the_rebase(tmp_path: Path) -> None:
    """The drill is stricter than `ship` here, and deliberately so.

    A merge to `main` does not move a PR's merge base (ADR-0027, Context), so an
    un-rebased branch is a case `ship` accepts under path (a) with its recorded
    base and tree both matching. Nothing about that changes: the refusal above
    belongs to the *prediction*, which is being asked about a base move that has
    not happened in this working tree yet. Pinned as its own test because a fix
    that tightened `ship` instead would be a change to a ratified acceptance
    condition (ADR-0027 §2), not an implementation of one.
    """
    repo = tmp_path / "repo"
    _init_repo(repo)
    _review_then_move_unrebased(repo, tmp_path, lambda r: _edit_line(r, _FLOOR_PATH, 40, "moved"))
    sha = _git(repo, "rev-parse", "HEAD")

    result = _run_ship(repo, tmp_path, pr_sha=sha)

    assert result.returncode == 0, result.stderr
    assert "a real finding" in (tmp_path / "comment.md").read_text()


# --- Mechanism 1: the floor helper the replica did not have ------------------


def test_the_floor_helper_is_still_outside_the_shared_block() -> None:
    """The hazard #751 filed is a property of the file, and it still holds.

    `_is_floor_path` is not inside `>>> shared-patch-identity`, and moving it
    there was one of the directions the issue offered — it is not the one taken,
    because the markers' contract is that the block stays byte-identical in
    `scripts/codex-review.sh` and widening it widens what must stay in sync. So
    the hazard is closed by removing the need to source anything at all, and this
    test exists to say that the *condition* for the hazard is still present: if
    someone later moves the helper into the block, this fails and they are told
    that the drill, not the sourcing instruction, is what closes the case.
    """
    block = _shared_patch_identity_block()
    assert "_is_floor_path" not in block
    assert "patch_identity()" in block


def test_the_drill_marks_the_floor_path_of_a_moved_base(tmp_path: Path) -> None:
    """#751's first mechanism: the breach is named, not silently skipped.

    Everything else about the artifact is in order — proper-ancestor base,
    hashable identities, and the base move nowhere near the reviewed hunk — so
    §3's floor is the only clause that can refuse, which is what makes a silent
    "clear" here indistinguishable from an acceptance. The drill marks the path
    and says the round is owed.
    """
    repo = tmp_path / "repo"
    _init_repo(repo)
    rebased = _review_then_move(repo, tmp_path, lambda r: _edit_line(r, _FLOOR_PATH, 40, "moved"))

    result = _run_ship(repo, tmp_path, pr_sha=rebased, args=("--drill",))

    assert result.returncode != 0, result.stderr
    assert f"[FLOOR] M {_FLOOR_PATH}" in result.stderr
    assert "BREACHED" in result.stderr
    assert "unavailable — floor breach" in result.stderr
    assert not (tmp_path / "comment.md").exists()


def test_the_drill_and_ship_agree_on_a_floor_breach(tmp_path: Path) -> None:
    """The prediction and the thing predicted are the same code, so they agree.

    The drill's whole value is that a lane can trust it against `ship`'s later
    verdict; a disagreement is what `.claude/agents/worker.md` tells a lane to
    escalate as a STOP. Run both against one state and pin that they refuse
    together and for the same stated reason.
    """
    repo = tmp_path / "repo"
    _init_repo(repo)
    rebased = _review_then_move(repo, tmp_path, lambda r: _edit_line(r, _FLOOR_PATH, 40, "moved"))

    drill = _run_ship(repo, tmp_path, pr_sha=rebased, args=("--drill",))
    ship = _run_ship(repo, tmp_path, pr_sha=rebased)

    assert drill.returncode != 0
    assert ship.returncode != 0
    assert "ADR-0027 §3's floor" in drill.stderr
    assert "ADR-0027 §3's floor" in ship.stderr


# --- The listing is the claim, so a pathname may not forge it ----------------


# A per-path entry: six spaces, the eight-column floor marker, then git's status
# letter. Anchored tightly so the report's wrapped prose — which is also indented
# past column six — cannot be counted as evidence, and so that a pathname
# rendering as a second line would be *visible* as one rather than absorbed.
_ENTRY = re.compile(r"^ {6}(?:\[FLOOR\] | {8})[A-Z][0-9]* ")


def _drill_lines(stderr: str) -> list[str]:
    """The report's per-path lines, which are the evidence for its verdict."""
    return [ln for ln in stderr.splitlines() if _ENTRY.match(ln)]


def test_a_pathname_containing_a_newline_stays_one_report_line(tmp_path: Path) -> None:
    """git permits it, and unescaped it would forge the evidence, not just blur it.

    The report's per-path list is the drill's entire claim about *what* it
    evaluated — the distinction #751 exists to restore. A pathname carrying a
    line break renders as two apparent entries, so a name can be chosen to make
    the listing say something the floor test never concluded. §4 already answers
    exactly this for the published record (issue #165); the terminal report needs
    the same first layer.
    """
    repo = tmp_path / "repo"
    _init_repo(repo)
    name = "notes/two\n      [FLOOR] M CLAUDE.md\nlines.md"
    rebased = _review_then_move(repo, tmp_path, lambda r: (r / name).write_text("x\n"))

    result = _run_ship(repo, tmp_path, pr_sha=rebased, args=("--drill",))

    assert result.returncode == 0, result.stderr
    assert "files examined      1" in result.stderr
    assert len(_drill_lines(result.stderr)) == 1
    # The forged line is present only as escaped text inside the single real one.
    assert r"notes/two\n      [FLOOR] M CLAUDE.md\nlines.md" in result.stderr
    # The escaped name still *reads* `[FLOOR] M CLAUDE.md`, and that is fine —
    # what it can no longer do is occupy a line of its own. No report line begins
    # with the marker, so nothing in the listing is mistakable for a verdict the
    # floor test did not reach.
    assert not any(ln.startswith("      [FLOOR] ") for ln in result.stderr.splitlines())
    assert "clear over the 1 path(s)" in result.stderr


def test_a_pathname_carrying_an_ansi_escape_is_neutralised(tmp_path: Path) -> None:
    """An ESC byte in a name can repaint what an operator already read."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    rebased = _review_then_move(
        repo, tmp_path, lambda r: (r / "notes/esc\x1b[2Kbell\x07.md").write_text("x\n")
    )

    result = _run_ship(repo, tmp_path, pr_sha=rebased, args=("--drill",))

    assert result.returncode == 0, result.stderr
    assert "\x1b" not in result.stderr
    assert "\x07" not in result.stderr
    assert r"notes/esc\x1b[2Kbell\x07.md" in result.stderr


def test_an_ordinary_path_is_not_entity_encoded_in_the_report(tmp_path: Path) -> None:
    """The terminal report takes §4's control layer and not its Markdown layer.

    `_encode_path`'s second pass exists for GitHub's inline Markdown and would
    render every `_` in an ordinary source path as `&#95;`. On a terminal that is
    not safety, it is a harder-to-read file set — and the file set being readable
    is the point of printing it. §4's own output is unaffected, which the
    round-trip tests in `test_ship_base_drift` continue to pin.
    """
    repo = tmp_path / "repo"
    _init_repo(repo)
    rebased = _review_then_move(
        repo, tmp_path, lambda r: _edit_line(r, _ORDINARY_PATH, 40, "line 40 — moved")
    )

    result = _run_ship(repo, tmp_path, pr_sha=rebased, args=("--drill",))

    assert result.returncode == 0, result.stderr
    assert _ORDINARY_PATH in result.stderr
    assert "&#95;" not in result.stderr


def test_both_rename_endpoints_are_escaped_in_the_report(tmp_path: Path) -> None:
    """§3 reads both endpoints, so the report must render both the same way."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    rebased = _review_then_move(
        repo, tmp_path, lambda r: _git(r, "mv", "notes/thing.md", "notes/re\tnamed.md")
    )

    result = _run_ship(repo, tmp_path, pr_sha=rebased, args=("--drill",))

    assert result.returncode == 0, result.stderr
    assert r"notes/thing.md -> notes/re\tnamed.md" in result.stderr
    assert len(_drill_lines(result.stderr)) == 1


# --- A listing too large to publish is omitted whole, never truncated --------
#
# `_evaluate_drift` short-circuits an oversized drift set to `toobig` *without*
# rendering it, because the path encoder costs a subprocess per pathname. The
# drill's report has to respect the same bound or it spends exactly the work the
# acceptance rule declined to — on a set it has usually already refused — and a
# pre-push check a lane waits on turns into minutes of unreadable output. The
# budget is `CODEX_SHIP_DRIFT_BUDGET`, lowered here so the case needs two files
# rather than a thousand.

_TINY_BUDGET = {"CODEX_SHIP_DRIFT_BUDGET": "20"}


def _two_file_move(path: str) -> Callable[[Path], None]:
    """A base move touching two files, which a 20-byte budget makes oversized.

    Two rather than the thousand-odd the real default would need: the bound is
    `n * 20 > budget`, the same arithmetic `_evaluate_drift` short-circuits on, so
    lowering the budget exercises the identical branch at a size a test can build.
    """

    def mutate(repo: Path) -> None:
        _edit_line(repo, path, 40, "moved")
        (repo / "notes/second.md").write_text("x\n")

    return mutate


def test_an_oversized_listing_is_omitted_whole_and_says_so(tmp_path: Path) -> None:
    """Omitted, not shortened — a truncated set is #751's failure in a costume.

    §4 already rules that a partial file set is worse than none, because the
    omitted tail is exactly where the breaching path hides. The same holds for
    the report: what it must never do is print a short list that reads like a
    complete one. So it prints none, says it printed none, and gives the command
    that reproduces the set.
    """
    repo = tmp_path / "repo"
    _init_repo(repo)
    rebased = _review_then_move(repo, tmp_path, _two_file_move(_ORDINARY_PATH))

    result = _run_ship(repo, tmp_path, pr_sha=rebased, args=("--drill",), gh_env=_TINY_BUDGET)

    assert result.returncode != 0, result.stderr
    assert "files examined      2" in result.stderr
    assert "listing             OMITTED" in result.stderr
    # The recovery is the script's own pinned, escaped listing at a larger budget,
    # not a hand-run git command: a bare `git diff --name-status` is neither
    # NUL-delimited nor pinned against config nor control-escaped, so on exactly
    # the unusual names this bound might be hiding it would answer differently
    # from what the floor actually read.
    assert "CODEX_SHIP_DRIFT_BUDGET=<bytes> scripts/ship.sh --drill" in result.stderr
    assert "git diff --name-status" not in result.stderr
    assert _drill_lines(result.stderr) == []
    assert _ORDINARY_PATH not in result.stderr
    # And having omitted the set, it claims nothing over it. The floor WAS
    # computed — `drift_floor` is set by `_read_base_move` with no rendering at
    # all — but a clear the reader cannot check is the shape of claim this whole
    # change removes, so the bound must not buy back a weaker version of it.
    assert "§3 floor            NOT CLAIMED" in result.stderr
    # No "clear over …" anywhere: the report's own affirmative form. (Its prose
    # says "not a clear you can check" while declining to make one, which is the
    # point, so the match is on the claim rather than on the bare word.)
    assert "clear over" not in result.stderr
    # Declining to claim concedes nothing: §2(b) is unavailable here regardless,
    # because `_evaluate_drift` applies this same arithmetic after its floor test.
    assert "unavailable — drift record exceeds §4's budget" in result.stderr
    assert result.returncode != 0


def test_a_floor_breach_survives_an_omitted_listing(tmp_path: Path) -> None:
    """The floor verdict is computed before the rendering and outlives it.

    `_read_base_move` sets `drift_floor` over the complete set with no per-path
    rendering at all, so bounding the *display* cannot bound the *decision*. This
    is the assertion that makes the bound safe rather than a third way to reach a
    false clear: the answer must still be BREACHED with nothing on screen.
    """
    repo = tmp_path / "repo"
    _init_repo(repo)
    rebased = _review_then_move(repo, tmp_path, _two_file_move(_FLOOR_PATH))

    result = _run_ship(repo, tmp_path, pr_sha=rebased, args=("--drill",), gh_env=_TINY_BUDGET)

    assert result.returncode != 0, result.stderr
    assert "listing             OMITTED" in result.stderr
    assert _drill_lines(result.stderr) == []
    assert "BREACHED somewhere in the 2 path(s) examined" in result.stderr
    assert "clear" not in result.stderr.split("§3 floor")[1]


# --- The clearing case, which a fail-closed drill could otherwise fake --------


def test_the_drill_clears_a_moved_base_and_names_what_it_cleared(tmp_path: Path) -> None:
    """A base move off the floor and off the reviewed hunk: covered, no round.

    Without this the two refusals above could be satisfied by a drill that
    refuses everything. The positive assertions are what distinguish a real
    evaluation from a bare verdict: the file set is listed, its size is stated,
    and the "clear" is scoped to those paths.
    """
    repo = tmp_path / "repo"
    _init_repo(repo)
    rebased = _review_then_move(
        repo, tmp_path, lambda r: _edit_line(r, _ORDINARY_PATH, 40, "line 40 — moved")
    )

    result = _run_ship(repo, tmp_path, pr_sha=rebased, args=("--drill",))

    assert result.returncode == 0, result.stderr
    assert f"        M {_ORDINARY_PATH}" in result.stderr
    assert "files examined      1" in result.stderr
    assert "clear over the 1 path(s) listed above" in result.stderr
    assert "available — the artifact covers HEAD" in result.stderr
    assert "[FLOOR]" not in result.stderr


def test_the_drill_writes_nothing_when_it_clears(tmp_path: Path) -> None:
    """A dry run that posted would be worse than no dry run at all.

    Pinned separately from the verdict because the exit status says the review
    *would* ship, and the whole point of running it before the push is that the
    PR record is untouched until the lane decides to touch it.
    """
    repo = tmp_path / "repo"
    _init_repo(repo)
    rebased = _review_then_move(
        repo, tmp_path, lambda r: _edit_line(r, _ORDINARY_PATH, 40, "line 40 — moved")
    )

    result = _run_ship(repo, tmp_path, pr_sha=rebased, args=("--drill",))

    assert result.returncode == 0, result.stderr
    assert "Nothing was written." in result.stderr
    assert not (tmp_path / "comment.md").exists()
    assert not (tmp_path / "gh-comment-calls").exists()
    assert not any((tmp_path / "comments").iterdir())


def test_the_drill_and_ship_agree_on_a_cleared_base_move(tmp_path: Path) -> None:
    """The other half of the agreement: both accept, and only `ship` posts."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    rebased = _review_then_move(
        repo, tmp_path, lambda r: _edit_line(r, _ORDINARY_PATH, 40, "line 40 — moved")
    )

    drill = _run_ship(repo, tmp_path, pr_sha=rebased, args=("--drill",))
    assert drill.returncode == 0, drill.stderr
    assert not (tmp_path / "comment.md").exists()

    ship = _run_ship(repo, tmp_path, pr_sha=rebased)
    assert ship.returncode == 0, ship.stderr
    assert "a real finding" in (tmp_path / "comment.md").read_text()


# --- The claim a drill must not make: a floor it never looked at -------------


def test_an_unmoved_base_makes_no_floor_claim_at_all(tmp_path: Path) -> None:
    """ "Not evaluated" and "evaluated and clear" are different sentences.

    Where the base has not moved, ADR-0027 §2 path (a) governs and §3's floor is
    never consulted — the tree comparison is the whole test. A drill that printed
    "floor clear" here would be stating something true by accident and unfalsely
    reusable next time, which is precisely how both of #751's mechanisms read to
    the lane that hit them. So the output must name the absence.
    """
    repo = tmp_path / "repo"
    sha = _init_repo(repo)
    _fake_gh(tmp_path / "bin")
    _record_review(repo, sha, "adversarial", f"a real finding\n{_VERDICT}\n")

    result = _run_ship(repo, tmp_path, pr_sha=sha, args=("--drill",))

    assert result.returncode == 0, result.stderr
    assert "NOT EVALUATED — no artifact reached §2(b)" in result.stderr
    assert "NO floor claim" in result.stderr
    assert "clear over" not in result.stderr
    assert not (tmp_path / "comment.md").exists()


def test_a_refusal_before_the_floor_reports_its_inputs_and_claims_nothing(
    tmp_path: Path,
) -> None:
    """The report is printed on the refusing path too, and states its inputs.

    Here the base moves *into* the reviewed hunk's context, so the patch identity
    moves and §2(b) is unavailable before the floor is ever reached. That is a
    second, distinct "not evaluated": the floor may or may not be clear and the
    drill does not know, so it must not say. What it must say is which HEAD,
    which merge base and which identity it was working from — a verdict with no
    inputs is the shape that made #751 hard to catch.
    """
    repo = tmp_path / "repo"
    _init_repo(repo)
    rebased = _review_then_move(
        repo, tmp_path, lambda r: _edit_line(r, _REVIEWED, _NEAR_LINE, "line 58 — moved")
    )

    result = _run_ship(repo, tmp_path, pr_sha=rebased, args=("--drill",))

    assert result.returncode != 0, result.stderr
    assert f"  HEAD                  {rebased}" in result.stderr
    assert "  PR merge base         " in result.stderr
    assert "  HEAD patch identity   " in result.stderr
    assert "NOT EVALUATED — no artifact reached §2(b)" in result.stderr
    assert "clear over" not in result.stderr
    assert "the base moved INTO the region the diff touches" in result.stderr


# --- The command surface -----------------------------------------------------


def test_the_drill_runs_before_the_push(tmp_path: Path) -> None:
    """The PR head lagging local HEAD is the drill's normal state, not an error.

    `ship` refuses it — reporting a review naming a SHA no reader can find on the
    PR is the failure that check exists for — and the drill must not, or it could
    only ever be run after the spend it exists to inform.
    """
    repo = tmp_path / "repo"
    sha = _init_repo(repo)
    _fake_gh(tmp_path / "bin")
    _record_review(repo, sha, "adversarial", f"a real finding\n{_VERDICT}\n")
    stale = _git(repo, "rev-parse", "HEAD~1")

    drill = _run_ship(repo, tmp_path, pr_sha=stale, args=("--drill",))
    ship = _run_ship(repo, tmp_path, pr_sha=stale)

    assert drill.returncode == 0, drill.stderr
    assert "the drill runs before the push" in drill.stderr
    assert ship.returncode != 0
    assert "push first" in ship.stderr


def test_an_unknown_argument_is_refused(tmp_path: Path) -> None:
    """`ship` took no arguments and ignored any it was given; now it refuses.

    A mistyped `--dril` that silently posted the review would be the worst
    available outcome for a flag whose entire purpose is *not* to post.
    """
    repo = tmp_path / "repo"
    sha = _init_repo(repo)
    _fake_gh(tmp_path / "bin")
    _record_review(repo, sha, "adversarial", f"a real finding\n{_VERDICT}\n")

    result = _run_ship(repo, tmp_path, pr_sha=sha, args=("--dril",))

    assert result.returncode != 0
    assert "unknown argument '--dril'" in result.stderr
    assert not (tmp_path / "comment.md").exists()
