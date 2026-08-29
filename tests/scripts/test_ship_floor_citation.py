"""ADR-0209 §§1-6 — when a floor base move actually costs a review round.

ADR-0027 §3 made nine paths invalidate a review artifact outright. Half of that
was a **path** test standing in for a **relation** — "the moved text bears on this
PR" — and #1743 measured the cost: of nine floor crossings in one day, three were
paid by a PR that neither names nor is named by the moved text, and none of those
three found anything. ADR-0209 narrows that half to four tests and keeps the
other half absolute.

This module is a test per clause, not a happy path (§10). Its shape follows the
decision's own:

- §1's standing contracts still bind with no test consulted — asserted here
  against a PR that *clears* an equivalent `docs/adr/**` move, so the two halves
  are separated by evidence rather than by assertion. (`test_ship_base_drift.py`
  enumerates the four paths; this module pins that no test is consulted.)
- §3's two tests, in both directions, at both endpoints of a rename.
- §4's unconditional limb — a `Protocol` added or widened — including the three
  spellings a bare-identifier reading would clear, and its second limb.
- §5's word rules, including the four free cases that are the whole point of
  splitting a dotted citation into a member that must be *touched* and qualifiers
  that need only be *present*.
- §6, one test per input that can fail to arrive.
- Issue #1750's snapshot: a citation deleted from the PR description after a
  review was recorded still binds.

**Every case is run twice, through `--drill` and through the real `ship`, and
the two must agree.** That is ADR-0209 §6's single-implementation clause made
checkable: #751 records a hand-built replica of this rule answering "floor clear"
for a base move that in fact breached the floor, and the answer to it is not a
comment but a pair of runs that cannot disagree.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from _repo_template import seed_bare_repo, seed_repo
from test_ship import _VERDICT, _fake_gh, _git, _record_review, _run_ship
from test_ship_base_drift import _advance_base

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

_ADR = "docs/adr/0042-a-decision-about-things.md"
_ADR_OTHER = "docs/adr/0043-another-decision.md"
_PLAN = "notes/plan.md"
#: A source file, because §3's "symbol" is a name the repository defines and a
#: definition lives in code. `notes/plan.md` is where a case wants prose instead.
_SURFACE = "src/ai_assistant/wire/surface.py"


def _adr(body: str) -> str:
    """An ADR whose Decision section says exactly ``body``."""
    return f"# 42. A decision about things\n\n- Status: Accepted\n\n## Decision\n\n{body}\n"


def _seed(repo: Path, files: Mapping[str, str]) -> None:
    for path, body in files.items():
        target = repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body)


def _init(
    repo: Path,
    base: Mapping[str, str],
    change: Mapping[str, str],
    *,
    deletes: tuple[str, ...] = (),
) -> None:
    """A repo on `feature`, with `origin` holding `main`, whose diff is `change`.

    The PR's diff is under the caller's control here — unlike
    ``test_ship_base_drift._init_repo``, which fixes it — because every case in
    this module turns on what the PR's own text says.
    """
    origin = repo.parent / "origin.git"
    assert shutil.which("git") is not None
    seed_bare_repo(origin)
    repo.mkdir(parents=True)
    seed_repo(repo)
    _seed(repo, base)
    (repo / ".gitignore").write_text(".review/\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    _git(repo, "remote", "add", "origin", str(origin))
    _git(repo, "push", "-q", "origin", "main")

    _git(repo, "checkout", "-qb", "feature")
    _seed(repo, change)
    for path in deletes:
        (repo / path).unlink()
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "the change")


@dataclass(frozen=True)
class Judgment:
    """What `ship` and its drill said about one base move.

    Attributes:
        owed: Whether the move cost a review round.
        reasons: The per-floor-path reason the drill printed, in listing order.
        stderr: The drill's whole report, for the assertions that read it.
    """

    owed: bool
    reasons: list[str]
    stderr: str


_REASON = re.compile(r"^ +(bind|free): (.*)$", re.MULTILINE)

# What the drill prints beside a floor path every test cleared. Asserted rather
# than inferred from the exit status in every free case below: a move whose floor
# path was never even recognised as one would also "pass" on the exit status
# alone, and that is the fail-open this whole rule is about.
_FREE = "free: every ADR-0209 §3/§4 test cleared this path"


def _judge(  # noqa: PLR0913  # one parameter per input ADR-0209 §5 names
    repo: Path,
    tmp_path: Path,
    mutate: Callable[[Path], object],
    *,
    body: str = "",
    pr_desc: str = "",
    description: str | None = None,
    gh_env: dict[str, str] | None = None,
) -> Judgment:
    """Record a review, move the base under it, and ask both paths of `ship`.

    Both are run against one state and must agree on whether the round is owed:
    the drill is not a model of `ship`, it *is* `ship` stopped before the write,
    and ADR-0209 §6 requires one implementation for both. A disagreement is what
    `.claude/agents/worker.md` tells a lane to escalate as a STOP, so it is a
    failed assertion here rather than a thing to discover in a lane.
    """
    sha = _git(repo, "rev-parse", "HEAD")
    _fake_gh(tmp_path / "bin")
    old_base = _git(repo, "merge-base", "main", sha)
    _record_review(
        repo,
        sha,
        "adversarial",
        f"a real finding\n{_VERDICT}\n",
        base_sha=old_base,
        pr_desc=pr_desc,
        description=description,
    )
    _advance_base(repo, mutate)
    rebased = _git(repo, "rev-parse", "HEAD")
    env = {"GH_PR_BODY": body, **(gh_env or {})}
    drill = _run_ship(repo, tmp_path, pr_sha=rebased, args=("--drill",), gh_env=env)
    ship = _run_ship(repo, tmp_path, pr_sha=rebased, gh_env=env)
    assert (drill.returncode == 0) == (ship.returncode == 0), (
        f"the drill and ship disagree (#751)\n--- drill ---\n{drill.stderr}\n"
        f"--- ship ---\n{ship.stderr}"
    )
    return Judgment(
        owed=ship.returncode != 0,
        reasons=[f"{kind}: {why}" for kind, why in _REASON.findall(drill.stderr)],
        stderr=drill.stderr,
    )


def _edit(path: str, text: str) -> Callable[[Path], object]:
    """A base move that rewrites ``path``."""

    def mutate(repo: Path) -> None:
        target = repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)

    return mutate


# --- §1: the standing contracts, with no test consulted -----------------------


def test_a_docs_review_move_binds_the_same_pr_that_clears_an_adr_move(tmp_path: Path) -> None:
    """§1 consults no test — shown against the PR that clears §2's half.

    The two halves of ADR-0027 §3 are separated here by evidence rather than by
    assertion: one PR, two base moves that differ only in which floor tree they
    land in. The `docs/adr/**` one clears because neither text names the other;
    the `docs/review/**` one binds anyway, because a review conducted under a
    superseded rubric is not a review under this repository's standard whatever
    its verdict says.
    """
    for i, (path, owed) in enumerate(
        ((_ADR, False), ("docs/review/guide.md", True), ("scripts/codex-review.sh", True))
    ):
        case = tmp_path / f"case-{i}"
        repo = case / "repo"
        _init(
            repo,
            {_ADR: _adr("Nothing here names anything."), "docs/review/guide.md": "rubric\n"},
            {_PLAN: "an ordinary change\n"},
        )
        judged = _judge(repo, case, _edit(path, "moved\n"))
        assert judged.owed is owed, f"{path}: {judged.stderr}"
        if owed:
            assert any("§1 — a standing review contract" in r for r in judged.reasons)


# --- §3: a moved ADR binds where either text names the other -------------------


def test_a_moved_adr_the_prs_diff_cites_by_number_is_owed(tmp_path: Path) -> None:
    """§3's first test: the direction a lane already knows about.

    A PR that cites a moved ADR by number has declared that the ADR bears on it,
    and #1743's table records that every round which found a real defect was on
    such a PR.
    """
    repo = tmp_path / "repo"
    _init(repo, {_ADR: _adr("Nothing.")}, {_PLAN: "This implements ADR-0042.\n"})

    judged = _judge(repo, tmp_path, _edit(_ADR, _adr("Ratified.")))

    assert judged.owed
    assert any("§3 — the PR's text cites ADR-0042" in r for r in judged.reasons)


def test_a_citation_only_in_the_pr_description_is_owed(tmp_path: Path) -> None:
    """§5 admits the description, and this is the path a diff-only reading clears.

    The diff carries no `ADR-0042` anywhere; the description does, and it was
    retrieved successfully. A rule reading the diff alone would clear the floor on
    a PR that has stated, in the one place a reader looks first, that the moved
    decision governs it.
    """
    repo = tmp_path / "repo"
    _init(repo, {_ADR: _adr("Nothing.")}, {_PLAN: "an ordinary change\n"})

    judged = _judge(
        repo, tmp_path, _edit(_ADR, _adr("Ratified.")), body="Implements **ADR-0042** (§3)."
    )

    assert judged.owed
    assert any("§3 — the PR's text cites ADR-0042" in r for r in judged.reasons)


def test_a_moved_adr_named_nowhere_in_the_prs_text_is_free(tmp_path: Path) -> None:
    """The saving this decision buys, and the one #1743 measured three times.

    Neither text names the other, so the move is published under ADR-0027 §4 and
    costs nothing. This is the case an unnarrowed floor charged for, and none of
    the three rounds it bought in #1743 found anything.
    """
    repo = tmp_path / "repo"
    _init(repo, {_ADR: _adr("Nothing here names anything.")}, {_PLAN: "an ordinary change\n"})

    judged = _judge(repo, tmp_path, _edit(_ADR, _adr("Ratified, still naming nothing.")))

    assert not judged.owed
    assert judged.reasons == [_FREE]
    assert judged.reasons == [_FREE]


def test_a_moved_adr_naming_a_path_the_pr_touches_is_owed(tmp_path: Path) -> None:
    """§3's second test: a decision that governs this PR's ground.

    §3's hazard is "an ADR merged under an open lane can contradict the one that
    lane is writing" — a decision that governs the PR *whether or not the PR knew
    to cite it*. ADR-0088 §1 makes such a decision name the paths it governs, so
    the hazard is checkable without the lane having known.
    """
    repo = tmp_path / "repo"
    _init(
        repo,
        {_ADR: _adr("Nothing."), "src/ai_assistant/wire/codec.py": "old\n"},
        {"src/ai_assistant/wire/codec.py": "new\n"},
    )

    judged = _judge(
        repo, tmp_path, _edit(_ADR, _adr("Framing is decided in `src/ai_assistant/wire/codec.py`."))
    )

    assert judged.owed
    assert any("a path this PR's diff touches" in r for r in judged.reasons)


def test_a_moved_adr_naming_a_symbol_the_pr_adds_is_owed(tmp_path: Path) -> None:
    """§3's second test again, through the other half of ADR-0088 §1's form.

    The PR's diff adds the definition, which is what makes `PROTOCOL_VERSION` a
    symbol rather than a backticked word: ADR-0088 §1(b) is a name "identifying
    something in the repository", and #1799 is what reading the token's *shape*
    instead cost.
    """
    repo = tmp_path / "repo"
    _init(repo, {_ADR: _adr("Nothing.")}, {_SURFACE: "PROTOCOL_VERSION = 19\n"})

    judged = _judge(repo, tmp_path, _edit(_ADR, _adr("The wire carries `PROTOCOL_VERSION`.")))

    assert judged.owed
    assert any("a symbol this PR's diff carries" in r for r in judged.reasons)


#: The vocabulary every ADR in the corpus carries: ADR-0070 §4's status words and
#: the literal the corpus spells an absent value with. `docs/adr/template.md` puts
#: `- Status: Proposed` at the head of every one of them.
_BOILERPLATE = (
    "A decision whose `Status` is `Proposed` binds nobody: the `Status` line is\n"
    "rewritten by the ratifying commit, and until then the facet it records is `None`.\n"
)


def test_an_adrs_header_vocabulary_is_not_a_symbol(tmp_path: Path) -> None:
    """#1799: the match that made ADR-0209's narrowing inert for ADR lanes.

    `None`, `Status` and `Proposed` are backtick-quoted words, not names
    identifying anything in this repository, so none of them is a symbol §3 can
    bind on (ADR-0088 §1(b)). Every ADR carries them and every ADR PR's own diff
    writes them, so a shape-only reading matched between *any* two ADR lanes —
    which is what cost PR #1795 five bound paths and a round, on ADRs whose
    subjects it has nothing to do with and whose numbers it never writes.
    """
    repo = tmp_path / "repo"
    _init(
        repo,
        {_ADR: _adr(_BOILERPLATE), _ADR_OTHER: _adr(_BOILERPLATE)},
        {
            "docs/adr/0044-a-lane-of-its-own.md": (
                "# 44. A lane of its own\n\n- Status: Proposed\n\n"
                "## Decision\n\nThe reconciler records `None` where it declines to rule.\n"
            )
        },
    )

    def mutate(r: Path) -> None:
        for path in (_ADR, _ADR_OTHER):
            (r / path).write_text(_adr(_BOILERPLATE + "\nRatified.\n"))

    judged = _judge(repo, tmp_path, mutate)

    assert not judged.owed, judged.stderr
    assert judged.reasons == [_FREE, _FREE]


def test_the_package_name_is_not_a_symbol_either(tmp_path: Path) -> None:
    """PR #1786's shape, strictly wider than #1799's: `ai_assistant`.

    The package name is a backticked token in most ADRs and appears in most
    diffs. It identifies a *tree*, and whether this PR changes that tree is the
    path test's question — asked and answered by
    `test_a_moved_adr_naming_a_path_the_pr_touches_is_owed`. Answering it a second
    time as a symbol restores the unconditional match rather than narrowing it.
    The package exists here, so what clears is the token's not being a
    *definition* rather than the tree's not being there.
    """
    repo = tmp_path / "repo"
    _init(
        repo,
        {_ADR: _adr("Nothing."), "src/ai_assistant/wire/codec.py": "class Frame:\n    pass\n"},
        {_PLAN: "The `ai_assistant` package is laid out by subsystem.\n"},
    )

    judged = _judge(
        repo, tmp_path, _edit(_ADR, _adr("Every subsystem lives under `ai_assistant`."))
    )

    assert not judged.owed, judged.stderr
    assert judged.reasons == [_FREE]


#: The JavaScript and shell spellings a resolver has to enumerate, and does not
#: here. The first five are what rounds 1-3 of PR #1803's own review found the
#: pattern of the day missing; the class methods are round 4's finding, which is
#: the one that ended the enumeration rather than extending it a fifth time.
_NON_PYTHON_SPELLINGS = (
    ("src/pkg/assets/app.js", "export function renderPane() {}\n"),
    ("src/pkg/assets/app.js", "export default class renderPane {}\n"),
    ("src/pkg/assets/app.js", "export const renderPane = 1;\n"),
    ("src/pkg/assets/app.js", "async function* renderPane(response) {}\n"),
    ("src/pkg/assets/app.js", "export async function *renderPane(response) {}\n"),
    ("src/pkg/assets/app.js", "class Pane {\n  async renderPane(response) {}\n}\n"),
    ("src/pkg/assets/app.js", "class Pane {\n  static renderPane() {}\n}\n"),
    ("src/pkg/assets/app.js", "class Pane {\n  get renderPane() {}\n}\n"),
    ("src/pkg/assets/app.js", "class Pane {\n  *renderPane() {}\n}\n"),
    ("scripts/tidy.sh", "renderPane() {\n  :\n}\n"),
    ("scripts/tidy.sh", "readonly renderPane=1\n"),
)


@pytest.mark.parametrize(("path", "body"), _NON_PYTHON_SPELLINGS)
def test_a_word_a_changed_non_python_source_line_carries_is_a_symbol(
    tmp_path: Path, path: str, body: str
) -> None:
    """The one reading left for the languages nothing here resolves.

    `src/ai_assistant/interfaces/gateway/assets/app.js` and the three shell
    scripts are first-party source, so a moved ADR naming something in them is
    naming this repository's own ground. Resolving those names needs a grammar,
    and four consecutive review rounds each found the grammar of the day short one
    form — silently, and in the direction ADR-0209 §5 forbids. So the question is
    asked of the diff instead: a word a changed line of one of those files carries
    is a symbol, whatever spelling declared it. Nothing below turns on the
    spelling, which is exactly the property that ends the recurrence.
    """
    repo = tmp_path / "repo"
    _init(repo, {_ADR: _adr("Nothing.")}, {path: body})

    judged = _judge(repo, tmp_path, _edit(_ADR, _adr("The pane is drawn by `renderPane`.")))

    assert judged.owed, judged.stderr
    assert any("a symbol this PR's diff carries" in r for r in judged.reasons)


_PANE = "class Pane {\n  async renderPane(response) {}\n}\n"


def test_a_dotted_citation_of_a_javascript_method_the_pr_changes_is_owed(
    tmp_path: Path,
) -> None:
    """`Pane.renderPane` — the citation form ADR-0088 §1(b) actually writes.

    This is why reading only Python was rejected: the ADR names a *method inside*
    a JavaScript file, and §3's path test answers for a cited path, never for a
    function within one. Dropping the file would clear the floor on the PR the
    moved ADR is about, which is the under-binding §5 forbids. The dotted split is
    unchanged — the member must be touched, the qualifier need only be present —
    and `class Pane` is present in the PR's own file.
    """
    repo = tmp_path / "repo"
    _init(
        repo,
        {_ADR: _adr("Nothing."), "src/pkg/assets/app.js": _PANE},
        {"src/pkg/assets/app.js": _PANE.replace("(response)", "(response, options)")},
    )

    judged = _judge(repo, tmp_path, _edit(_ADR, _adr("The pane is drawn by `Pane.renderPane`.")))

    assert judged.owed, judged.stderr
    assert any("`Pane.renderPane`" in r for r in judged.reasons)


def test_a_dotted_citation_of_a_javascript_method_the_pr_leaves_alone_is_free(
    tmp_path: Path,
) -> None:
    """The other direction of the same fallback, and the reason it is not a licence.

    The method is right there in the tree at both endpoints — but this PR changes
    no line of the file that holds it, so nothing it adds or removes carries the
    name and the moved ADR is not about it. A rule that read the *file* rather
    than the *changed lines* would bind here, which would give back the
    unconditional match the resolver was written to close.
    """
    repo = tmp_path / "repo"
    _init(
        repo,
        {_ADR: _adr("Nothing."), "src/pkg/assets/app.js": _PANE},
        {_PLAN: "the pane is unchanged in this lane\n"},
    )

    judged = _judge(repo, tmp_path, _edit(_ADR, _adr("The pane is drawn by `Pane.renderPane`.")))

    assert not judged.owed, judged.stderr
    assert judged.reasons == [_FREE]


def test_a_prose_line_beside_a_javascript_one_is_still_not_a_symbol(tmp_path: Path) -> None:
    """#1799's shape, in a PR that also changes a file the fallback does read.

    The fallback is attributed per file, off the patch's own headers, and this is
    what that has to be worth: a lane touching `assets/app.js` and an ADR in the
    same diff must not thereby make `Status`, `Proposed` and `None` symbols. A
    reader that admitted a whole patch once any section of it was source — or that
    failed to reset at the next `diff --git` — would bind both moved ADRs here and
    hand #1795 its round straight back.
    """
    repo = tmp_path / "repo"
    _init(
        repo,
        {_ADR: _adr(_BOILERPLATE), _ADR_OTHER: _adr(_BOILERPLATE)},
        {
            # `assets/` sorts before `docs/`, so the source section is rendered
            # first and a missing reset would carry into the prose one.
            "assets/app.js": "export function renderPane() {}\n",
            "docs/adr/0044-a-lane-of-its-own.md": (
                "# 44. A lane of its own\n\n- Status: Proposed\n\n"
                "## Decision\n\nThe reconciler records `None` where it declines to rule.\n"
            ),
        },
    )

    def mutate(r: Path) -> None:
        for path in (_ADR, _ADR_OTHER):
            (r / path).write_text(_adr(_BOILERPLATE + "\nRatified.\n"))

    judged = _judge(repo, tmp_path, mutate)

    assert not judged.owed, judged.stderr
    assert judged.reasons == [_FREE, _FREE]


def test_a_symbol_resolver_that_will_not_answer_binds_under_section_6(tmp_path: Path) -> None:
    """Found nowhere is decided; unable to look is not.

    #1799's fix turns a token the repository defines nowhere into an *evaluated*
    not-a-symbol, which is why it clears. The complement is this: a search that
    cannot be run has evaluated nothing, and §6 is a rule rather than a list, so
    the base move binds. The head endpoint here is a sha no object store holds.
    """
    repo = tmp_path / "repo"
    _init(repo, {_ADR: _adr("The wire carries `PROTOCOL_VERSION`.")}, {_SURFACE: "X = 19\n"})

    out = _run_floor_test(
        repo,
        entries=[("M", _ADR, "")],
        old=_git(repo, "rev-parse", "main"),
        new=_git(repo, "rev-parse", "HEAD"),
        pr_head="0" * 40,
    )

    assert out[0][1] == "bind"
    assert "§6" in out[0][2]


def test_an_adr_renamed_within_the_tree_is_read_at_both_endpoints(tmp_path: Path) -> None:
    """A rename inside `docs/adr/` is read under both of its names."""
    repo = tmp_path / "repo"
    _init(
        repo,
        {_ADR: _adr("Framing is `src/ai_assistant/wire/codec.py`."), "src/x.py": "old\n"},
        {"src/ai_assistant/wire/codec.py": "new\n"},
    )

    def rename(r: Path) -> None:
        _git(r, "mv", _ADR, _ADR_OTHER)

    judged = _judge(repo, tmp_path, rename)

    assert judged.owed
    assert any("a path this PR's diff touches" in r for r in judged.reasons)


def test_an_adr_renamed_out_of_the_tree_is_still_read_at_its_source(tmp_path: Path) -> None:
    """The SOURCE endpoint decides where the destination is not a floor path.

    ADR-0209 §8 leaves ADR-0027 §3's rename-aware both-endpoints reading exactly
    where it was, and a `--name-only` listing would report only the destination —
    so an ADR moved out of `docs/adr/` would drop off the floor entirely while
    still being the decision the review was conducted under.
    """
    repo = tmp_path / "repo"
    _init(
        repo,
        {_ADR: _adr("Framing is `src/ai_assistant/wire/codec.py`."), "src/x.py": "old\n"},
        {"src/ai_assistant/wire/codec.py": "new\n"},
    )

    def rename(r: Path) -> None:
        (r / "notes").mkdir(exist_ok=True)
        _git(r, "mv", _ADR, "notes/0042-a-decision-about-things.md")

    judged = _judge(repo, tmp_path, rename)

    assert judged.owed
    assert any("a path this PR's diff touches" in r for r in judged.reasons)


def test_a_file_renamed_into_the_adr_tree_is_read_at_its_destination(tmp_path: Path) -> None:
    """The DESTINATION endpoint decides where the source is not a floor path.

    A decision arriving in `docs/adr/` by rename is a decision landing on the
    base, and §3's both-endpoints reading is what sees it: read at the source
    alone, `notes/draft.md` is not a floor path at all.
    """
    repo = tmp_path / "repo"
    _init(
        repo,
        {"notes/draft.md": _adr("Framing is `src/ai_assistant/wire/codec.py`."), "src/x.py": "o\n"},
        {"src/ai_assistant/wire/codec.py": "new\n"},
    )

    def rename(r: Path) -> None:
        (r / "docs" / "adr").mkdir(parents=True, exist_ok=True)
        _git(r, "mv", "notes/draft.md", _ADR)

    judged = _judge(repo, tmp_path, rename)

    assert judged.owed
    assert any("a path this PR's diff touches" in r for r in judged.reasons)


def test_a_file_renamed_into_the_adr_tree_naming_nothing_is_free(tmp_path: Path) -> None:
    """The same rename, decided the other way, so the case above is not vacuous."""
    repo = tmp_path / "repo"
    # The PR's own file lives outside `notes/`, so git's rename detection cannot
    # mistake it for the draft the base move is moving and conflict on the rebase.
    _init(
        repo,
        {"notes/draft.md": _adr("Nothing here names anything."), "src/x.py": "old\n"},
        {"src/x.py": "new\n"},
    )

    def rename(r: Path) -> None:
        (r / "docs" / "adr").mkdir(parents=True, exist_ok=True)
        _git(r, "mv", "notes/draft.md", _ADR)

    judged = _judge(repo, tmp_path, rename)

    assert not judged.owed
    assert judged.reasons == [_FREE]


def test_an_adr_renamed_out_of_the_tree_naming_nothing_is_free(tmp_path: Path) -> None:
    """The same rename, decided the other way, so the case above is not vacuous."""
    repo = tmp_path / "repo"
    _init(repo, {_ADR: _adr("Nothing here names anything.")}, {_PLAN: "an ordinary change\n"})

    def rename(r: Path) -> None:
        (r / "notes").mkdir(exist_ok=True)
        _git(r, "mv", _ADR, "notes/0042-a-decision-about-things.md")

    judged = _judge(repo, tmp_path, rename)

    assert not judged.owed
    assert judged.reasons == [_FREE]


def test_a_docs_adr_path_carrying_no_number_is_owed(tmp_path: Path) -> None:
    """`docs/adr/template.md` has no number, so §3's first test cannot be asked.

    §6 binds anything undecidable, and "this file is not a decision" is not a
    judgement the acceptance rule may make on the author's behalf.
    """
    repo = tmp_path / "repo"
    _init(repo, {"docs/adr/template.md": "a template\n"}, {_PLAN: "an ordinary change\n"})

    judged = _judge(repo, tmp_path, _edit("docs/adr/template.md", "a changed template\n"))

    assert judged.owed
    assert any("carries no ADR number" in r for r in judged.reasons)


# --- §5: a dotted citation is split, and the four free cases ------------------

_LONG_CLASS = "class Widget:\n" + "".join(
    f"    def filler_{i}(self) -> None: ...\n" for i in range(200)
)


def test_a_dotted_citation_binds_a_pr_adding_the_class_and_the_member(tmp_path: Path) -> None:
    """`Class.member` against a PR whose diff adds both, on separate lines.

    No line of that diff carries the dotted string, which is exactly why the
    token is split: the member must be *touched*, and the qualifier need only be
    *present* in one of the PR's files.
    """
    repo = tmp_path / "repo"
    _init(
        repo,
        {_ADR: _adr("Nothing.")},
        {"src/pkg/widget.py": "class Widget:\n    def render(self) -> None: ...\n"},
    )

    judged = _judge(repo, tmp_path, _edit(_ADR, _adr("Rendering is `Widget.render`.")))

    assert judged.owed
    assert any("`Widget.render`" in r for r in judged.reasons)


def test_a_dotted_citation_binds_when_the_class_header_is_out_of_the_hunk(tmp_path: Path) -> None:
    """The case a context-line reading clears, with the header 200 lines up.

    Reading the qualifier from the diff's *context lines* was carried for a round
    of ADR-0209's own review and is wrong for this reason: the context window is a
    rendering option, so a member appended to a large class would clear the floor
    because its class header did not fit. §5 asks the qualifier of the PR's
    **files**, which is where the answer actually is.
    """
    repo = tmp_path / "repo"
    _init(
        repo,
        {_ADR: _adr("Nothing."), "src/pkg/widget.py": _LONG_CLASS},
        {"src/pkg/widget.py": _LONG_CLASS + "    def render(self) -> None: ...\n"},
    )

    judged = _judge(repo, tmp_path, _edit(_ADR, _adr("Rendering is `Widget.render`.")))

    assert judged.owed
    assert any("`Widget.render`" in r for r in judged.reasons)


def test_a_dotted_citation_is_free_where_no_pr_file_names_the_qualifier(tmp_path: Path) -> None:
    """A PR adding an unrelated `render` to a file that never mentions `Widget`.

    Matching the last part alone would bind almost every diff and the rule would
    buy nothing; this is the case that shows it does not.
    """
    repo = tmp_path / "repo"
    _init(
        repo,
        {_ADR: _adr("Nothing.")},
        {"src/other.py": "def render() -> None: ...\n"},
    )

    judged = _judge(repo, tmp_path, _edit(_ADR, _adr("Rendering is `Widget.render`.")))

    assert not judged.owed
    assert judged.reasons == [_FREE]


def test_a_dotted_citation_is_free_where_the_member_is_untouched(tmp_path: Path) -> None:
    """A PR touching a file that names `Widget` without adding or removing `render`.

    The *member* is what must be touched — that is what makes this a statement
    about the change rather than about its neighbourhood.
    """
    repo = tmp_path / "repo"
    _init(
        repo,
        {_ADR: _adr("Nothing."), "src/pkg/widget.py": _LONG_CLASS},
        {"src/pkg/widget.py": _LONG_CLASS + "    # a note about layout\n"},
    )

    judged = _judge(repo, tmp_path, _edit(_ADR, _adr("Rendering is `Widget.render`.")))

    assert not judged.owed
    assert judged.reasons == [_FREE]


def test_a_dotted_citation_is_free_where_only_the_qualifier_is_named(tmp_path: Path) -> None:
    """A PR whose diff names `Widget` and nothing about `render`."""
    repo = tmp_path / "repo"
    _init(repo, {_ADR: _adr("Nothing.")}, {"src/pkg/widget.py": "class Widget:\n    pass\n"})

    judged = _judge(repo, tmp_path, _edit(_ADR, _adr("Rendering is `Widget.render`.")))

    assert not judged.owed
    assert judged.reasons == [_FREE]


def test_a_removed_line_beginning_with_two_dashes_is_content_not_a_header(
    tmp_path: Path,
) -> None:
    """`---` at the start of a removed line is only sometimes a file header.

    A removed line whose own content begins with `--` renders as `---…`, so a
    reader dropping every line starting with three dashes discards content and
    under-binds — which is the one direction ADR-0209 §5 forbids. The headers are
    recognised by their whole shape (`--- a/…`, `+++ b/…`, `--- /dev/null`)
    instead.
    """
    repo = tmp_path / "repo"
    _init(
        repo,
        {
            _ADR: _adr("Nothing."),
            _SURFACE: "PROTOCOL_VERSION = 18\n",
            "notes/legacy.sql": "-- PROTOCOL_VERSION is pinned here\n",
        },
        {"notes/legacy.sql": "\n"},
    )

    judged = _judge(repo, tmp_path, _edit(_ADR, _adr("The wire carries `PROTOCOL_VERSION`.")))

    assert judged.owed
    assert any("a symbol this PR's diff carries" in r for r in judged.reasons)


def test_a_module_qualified_citation_is_satisfied_by_the_path(tmp_path: Path) -> None:
    """`pkg.mod.Symbol` where the module path, not the contents, carries the words.

    A PR adding `class Frame` to `src/ai_assistant/wire/codec.py` need never write
    the words `wire` or `codec` inside it: the module path is the statement, and
    it is carried by the filename. A contents-only reading clears this.
    """
    repo = tmp_path / "repo"
    _init(
        repo,
        {_ADR: _adr("Nothing.")},
        {"src/ai_assistant/wire/codec.py": "class Frame:\n    pass\n"},
    )

    judged = _judge(repo, tmp_path, _edit(_ADR, _adr("Framing is `wire.codec.Frame`.")))

    assert judged.owed
    assert "wire" not in (repo / "src/ai_assistant/wire/codec.py").read_text()
    assert any("`wire.codec.Frame`" in r for r in judged.reasons)


def test_a_pr_that_adds_the_cited_file_is_judged_on_the_endpoint_it_has(tmp_path: Path) -> None:
    """§5: an endpoint that does not exist is not a failure to read one.

    Reading a missing base-side endpoint as a failed read would charge a round on
    every PR that adds a file, so the rule reads the sides a path has and no more.
    """
    repo = tmp_path / "repo"
    _init(
        repo,
        {_ADR: _adr("Nothing.")},
        {"src/pkg/widget.py": "class Widget:\n    def render(self) -> None: ...\n"},
    )

    judged = _judge(repo, tmp_path, _edit(_ADR, _adr("Rendering is `Widget.render`.")))

    assert judged.owed
    assert not any("§6" in r for r in judged.reasons), "an absent endpoint is not an unread one"


def test_a_pr_that_deletes_the_cited_file_is_judged_on_the_endpoint_it_has(tmp_path: Path) -> None:
    """The mirror image: a deletion has no head-side endpoint and is not a failure.

    It carries a second load since #1799: `render` is a definition at the *base*
    endpoint and at no other, so a symbol resolver reading the head alone would
    clear the floor here — on exactly the PR the moved ADR is about.
    """
    repo = tmp_path / "repo"
    _init(
        repo,
        {
            _ADR: _adr("Nothing."),
            "src/pkg/widget.py": "class Widget:\n    def render(self) -> None: ...\n",
        },
        {_PLAN: "removing the widget\n"},
        deletes=("src/pkg/widget.py",),
    )

    judged = _judge(repo, tmp_path, _edit(_ADR, _adr("Rendering is `Widget.render`.")))

    assert judged.owed
    assert not any("§6" in r for r in judged.reasons), "an absent endpoint is not an unread one"


# --- §4: the contract surface -------------------------------------------------

_PROTOCOLS = "src/ai_assistant/core/protocols.py"
_TYPES = "src/ai_assistant/core/types.py"

_ONE_PROTOCOL = """from typing import Protocol


class Reader(Protocol):
    def read(self) -> str: ...
"""


def _protocols_case(tmp_path: Path, before: str, after: str) -> Judgment:
    """A `core/protocols.py` base move against a PR touching nothing in `core/`."""
    repo = tmp_path / "repo"
    _init(repo, {_PROTOCOLS: before}, {_PLAN: "an ordinary change\n"})
    return _judge(repo, tmp_path, _edit(_PROTOCOLS, after))


def test_a_base_move_adding_a_protocol_binds_unconditionally(tmp_path: Path) -> None:
    """§4's unconditional limb, and the fail-open it exists to close.

    "Or now should" is a relation the PR's own text cannot witness: a diff that
    ought to consume a Protocol landed an hour ago names nothing about it,
    precisely because it has not been written to consume it yet. So the case is
    not given to a citation test.
    """
    judged = _protocols_case(
        tmp_path,
        _ONE_PROTOCOL,
        _ONE_PROTOCOL + "\n\nclass Writer(Protocol):\n    def write(self) -> None: ...\n",
    )

    assert judged.owed
    assert any("adds Protocol `Writer`" in r for r in judged.reasons)


def test_a_base_move_adding_an_annotated_attribute_binds(tmp_path: Path) -> None:
    """A member-is-a-method reading would clear this, and §4 says it must not.

    An annotated attribute is a new structural requirement on every
    implementation of the Protocol, and a lane implementing it outside `core/`
    names nothing about the attribute because it did not exist when the diff was
    written.
    """
    judged = _protocols_case(
        tmp_path,
        _ONE_PROTOCOL,
        "from typing import Protocol\n\n\nclass Reader(Protocol):\n"
        "    encoding: str\n\n    def read(self) -> str: ...\n",
    )

    assert judged.owed
    assert any("widens Protocol `Reader`" in r and "encoding" in r for r in judged.reasons)


def test_a_base_move_adding_a_property_binds(tmp_path: Path) -> None:
    """The other half of the same clause: a property is a member too."""
    judged = _protocols_case(
        tmp_path,
        _ONE_PROTOCOL,
        "from typing import Protocol\n\n\nclass Reader(Protocol):\n"
        "    @property\n    def size(self) -> int: ...\n\n    def read(self) -> str: ...\n",
    )

    assert judged.owed
    assert any("widens Protocol `Reader`" in r and "size" in r for r in judged.reasons)


def test_a_base_move_adding_a_protocol_base_and_nothing_else_binds(tmp_path: Path) -> None:
    """The widening a declared-members comparison clears.

    This repository composes Protocols — `TraceStore(TraceSink, TraceRetention,
    Protocol)`, `SecretStore(Secrets, Protocol)` — so adding a `Protocol` base
    adds every member of that base to what an implementation must satisfy while
    declaring nothing in the child's own body. The surface compared is therefore
    the **effective** one.
    """
    before = (
        "from typing import Protocol\n\n\nclass Sink(Protocol):\n    def emit(self) -> None: ...\n"
        "\n\nclass Store(Protocol):\n    def close(self) -> None: ...\n"
    )
    after = before.replace("class Store(Protocol):", "class Store(Sink, Protocol):")

    judged = _protocols_case(tmp_path, before, after)

    assert judged.owed
    assert any("widens Protocol `Store`" in r and "emit" in r for r in judged.reasons)


def test_a_widening_under_an_aliased_protocol_base_binds(tmp_path: Path) -> None:
    """`from typing import Protocol as P` — a spelling on which both ends parse.

    A bare-identifier reading clears this, and §4's parse-failure limb never fires
    because nothing failed to parse. Identity is resolved through the module's own
    imports for exactly this case.
    """
    before = (
        "from typing import Protocol as P\n\n\nclass Base(P):\n    def a(self) -> None: ...\n"
        "\n\nclass Child(Base, P):\n    def b(self) -> None: ...\n"
    )
    after = before.replace(
        "    def b(self) -> None: ...", "    def b(self) -> None: ...\n    def c(self) -> None: ..."
    )

    judged = _protocols_case(tmp_path, before, after)

    assert judged.owed
    assert any("widens Protocol `Child`" in r and "c" in r for r in judged.reasons)


def test_a_widening_under_an_attribute_access_protocol_base_binds(tmp_path: Path) -> None:
    """`import typing` … `class Child(Base, typing.Protocol)` — the other spelling.

    `src/ai_assistant/wire/surface.py` does a bare `import typing` today, so this
    is a form the repository already writes elsewhere.
    """
    before = (
        "import typing\n\n\nclass Base(typing.Protocol):\n    def a(self) -> None: ...\n"
        "\n\nclass Child(Base, typing.Protocol):\n    def b(self) -> None: ...\n"
    )
    after = before.replace(
        "    def b(self) -> None: ...", "    def b(self) -> None: ...\n    def c(self) -> None: ..."
    )

    judged = _protocols_case(tmp_path, before, after)

    assert judged.owed
    assert any("widens Protocol `Child`" in r and "c" in r for r in judged.reasons)


def test_an_unresolvable_protocol_base_binds(tmp_path: Path) -> None:
    """A base resolving neither to `typing.Protocol` nor to a class this file declares.

    §4's last sentence sends every such spelling — a wildcard import, a
    subscripted base, a `Protocol` re-exported through a module of this
    repository — to §6, deliberately. Over-binding on a file that changes rarely
    and behind its own merged ADR is the cost this rule accepts.
    """
    weird = (
        "from elsewhere import Mystery\n\n\nclass Weird(Mystery):\n    def a(self) -> None: ...\n"
    )

    judged = _protocols_case(tmp_path, _ONE_PROTOCOL, _ONE_PROTOCOL + "\n\n" + weird)

    assert judged.owed
    assert any("resolves neither to typing.Protocol" in r for r in judged.reasons)


def test_a_widening_under_a_guarded_protocol_import_binds(tmp_path: Path) -> None:
    """The import may sit under a `try:`; the resolution has to find it there.

    `try: from typing import Protocol / except ImportError: from typing_extensions
    import Protocol` is an ordinary spelling, and reading only the module's
    top-level statements would resolve every base in such a file to nothing. §6
    would then bind — which is safe, but for a reason belonging to the reader
    rather than to the file, and it would make §4's unconditional limb
    unobservable in exactly the files that use it.
    """
    before = (
        "try:\n    from typing import Protocol\nexcept ImportError:\n"
        "    from typing_extensions import Protocol\n\n\n"
        "class Reader(Protocol):\n    def read(self) -> str: ...\n"
    )
    after = before.replace(
        "    def read(self) -> str: ...",
        "    def read(self) -> str: ...\n    def peek(self) -> str: ...",
    )

    judged = _protocols_case(tmp_path, before, after)

    assert judged.owed
    assert any("widens Protocol `Reader`" in r and "peek" in r for r in judged.reasons)


def test_an_import_shadowed_inside_a_function_does_not_resolve_a_base(
    tmp_path: Path,
) -> None:
    """Binding is lexical, so a nested import binds nothing at module scope.

    The module's real `Protocol` comes from somewhere else; a helper *function*
    imports `typing.Protocol` for its own use. A reader that collected every
    import in the file would resolve `class Legacy(Protocol)` to
    `typing.Protocol`, judge it a Protocol, find no widening, and clear a floor
    that §4's last sentence and §6 require it to bind — a base resolving neither
    to `typing.Protocol` nor to a class this file declares. The move here widens
    nothing precisely so that the *clear* is what the bug would produce.

    Adversarial review of PR #1755, round 1, blocker 2.
    """
    before = (
        "from elsewhere import Protocol\n\n\n"
        "def helper() -> None:\n    from typing import Protocol  # noqa: F401\n\n\n"
        "class Legacy(Protocol):\n    def read(self) -> str: ...\n"
    )
    after = before.replace('"""', "") + "\n\n# a comment the move adds\n"

    judged = _protocols_case(tmp_path, before, after)

    assert judged.owed
    assert any("resolves neither to typing.Protocol" in r for r in judged.reasons)


def test_two_classes_sharing_a_name_in_one_endpoint_bind(tmp_path: Path) -> None:
    """A base written under an ambiguous name resolves to nothing decidable.

    §6 binds it. This is over-binding on a spelling `core/protocols.py` does not
    use, which is the asymmetry ADR-0209 §5 states and prices: under-binding is
    the failure it must not have.
    """
    duplicated = (
        "from typing import Protocol\n\n\nclass Reader(Protocol):\n    def read(self) -> str: ...\n"
        "\n\nif True:\n    class Reader(Protocol):\n        def read(self) -> bytes: ...\n"
    )

    judged = _protocols_case(tmp_path, _ONE_PROTOCOL, duplicated)

    assert judged.owed
    assert any("two classes are named `Reader`" in r for r in judged.reasons)


def test_a_protocols_endpoint_that_will_not_parse_binds(tmp_path: Path) -> None:
    """§4 says an endpoint that cannot be parsed binds, on §6's footing."""
    judged = _protocols_case(tmp_path, _ONE_PROTOCOL, "class Reader(Protocol)\n    def read(\n")

    assert judged.owed
    assert any("will not parse" in r for r in judged.reasons)


def test_a_protocols_move_that_widens_nothing_is_free(tmp_path: Path) -> None:
    """The acceptance without which a fail-closed implementation passes by refusing.

    A docstring edit inside a Protocol adds no member and lands no class, and the
    PR touches nothing under `core/` and names nothing the move defined.
    """
    before = (
        "from typing import Protocol\n\n\nclass Reader(Protocol):\n"
        '    """Read."""\n\n    def read(self) -> str: ...\n'
    )
    after = before.replace('"""Read."""', '"""Read some bytes."""')

    judged = _protocols_case(tmp_path, before, after)

    assert not judged.owed
    assert judged.reasons == [_FREE]


def test_a_core_types_move_the_pr_neither_touches_nor_names_is_free(tmp_path: Path) -> None:
    """§4's limb is scoped to `core/protocols.py`, and this is what that buys.

    A field added to a `core/types.py` model obliges no open PR to do anything:
    the "now should consume" hazard is a *Protocol* hazard. #1743's one contract
    crossing is this case — the base move changed `Provenance` while the PR's ADR
    named `SpokenTurn`.
    """
    repo = tmp_path / "repo"
    _init(repo, {_TYPES: "class Provenance:\n    pass\n"}, {_PLAN: "an ordinary change\n"})

    judged = _judge(repo, tmp_path, _edit(_TYPES, "class Provenance:\n    kind: str\n"))

    assert not judged.owed
    assert judged.reasons == [_FREE]


def test_a_core_types_move_changing_a_definition_the_pr_names_is_owed(tmp_path: Path) -> None:
    """§4's second limb: a definition, never a mention.

    A mention that is not a definition tells a PR nothing it could act on, so what
    binds is a name whose *definition* the move changed — here a class the move
    lands, which this PR's text names.
    """
    repo = tmp_path / "repo"
    _init(repo, {_TYPES: "class Provenance:\n    pass\n"}, {_PLAN: "we will need SpokenTurn\n"})

    judged = _judge(
        repo,
        tmp_path,
        _edit(_TYPES, "class Provenance:\n    pass\n\n\nclass SpokenTurn:\n    pass\n"),
    )

    assert judged.owed
    assert any("changed the definition of `SpokenTurn`" in r for r in judged.reasons)


def test_a_core_types_move_binds_a_pr_that_touches_core(tmp_path: Path) -> None:
    """The other half of §4's second limb: the PR's diff reaches `core/`."""
    repo = tmp_path / "repo"
    _init(
        repo,
        {_TYPES: "class Provenance:\n    pass\n", "src/ai_assistant/core/errors.py": "old\n"},
        {"src/ai_assistant/core/errors.py": "new\n"},
    )

    judged = _judge(repo, tmp_path, _edit(_TYPES, "class Provenance:\n    kind: str\n"))

    assert judged.owed
    assert any("touches a path under" in r for r in judged.reasons)


# --- §6: every input that can fail to arrive ----------------------------------


def test_a_python_file_that_will_not_parse_binds(tmp_path: Path) -> None:
    """§6 names "a parse failure at either endpoint" as its own first instance.

    The alternative was carried on this branch and adversarial review broke it: a
    line-oriented fallback is one more enumeration of Python's grammar, and the
    form it lacked was `type Widget = object`. A definition dropped that way is
    invisible, so a moved ADR citing it clears a floor that was owed — the one
    direction ADR-0209 §5 forbids. Binding is loud instead, and it names the file.
    """
    repo = tmp_path / "repo"
    _init(
        repo,
        {_ADR: _adr("Nothing."), "src/pkg/broken.py": "type Widget = object\ndef (:\n"},
        {_PLAN: "an unrelated note\n"},
    )

    judged = _judge(repo, tmp_path, _edit(_ADR, _adr("Rendering is `Widget`.")))

    assert judged.owed, judged.stderr
    assert any("§6" in r and "broken.py" in r for r in judged.reasons), judged.reasons


def test_an_unretrievable_pr_description_binds(tmp_path: Path) -> None:
    """§5 names the live body, so a body that will not come back is undecidable.

    Every floor path binds and every other path is left alone: §6 is about the
    tests, not about the listing.
    """
    repo = tmp_path / "repo"
    _init(repo, {_ADR: _adr("Nothing.")}, {_PLAN: "an ordinary change\n"})

    judged = _judge(repo, tmp_path, _edit(_ADR, _adr("Ratified.")), gh_env={"GH_PR_BODY_FAIL": "1"})

    assert judged.owed
    assert any("could not be retrieved from GitHub" in r for r in judged.reasons)


def test_an_unreadable_moved_endpoint_binds(tmp_path: Path) -> None:
    """An endpoint that exists in the listing and not in the object store.

    Driven at `floor_test.py` directly, because the failure being tested is one
    `ship` cannot produce on purpose: a listing naming a blob no commit carries.
    """
    repo = tmp_path / "repo"
    _init(repo, {_ADR: _adr("Nothing.")}, {_PLAN: "an ordinary change\n"})
    out = _run_floor_test(
        repo,
        entries=[("M", "docs/adr/0099-never-existed.md", "")],
        old=_git(repo, "rev-parse", "main"),
        new=_git(repo, "rev-parse", "HEAD"),
    )

    assert out[0][1] == "bind"
    assert "§6" in out[0][2]


def test_an_unparseable_pr_listing_binds(tmp_path: Path) -> None:
    """A `-z` listing that runs off the end is not a safe listing."""
    repo = tmp_path / "repo"
    _init(repo, {_ADR: _adr("Nothing.")}, {_PLAN: "an ordinary change\n"})
    out = _run_floor_test(
        repo,
        entries=[("M", _ADR, "")],
        old=_git(repo, "rev-parse", "main"),
        new=_git(repo, "rev-parse", "HEAD"),
        pr_listing=b"M\0",
    )

    assert out[0][1] == "bind"
    assert "not a listing this can parse" in out[0][2]


def test_an_unparseable_base_move_listing_is_refused_outright(tmp_path: Path) -> None:
    """The stdin contract is three fields per entry; anything else exits non-zero.

    A caller that cannot be joined by position gets a refusal rather than a
    verdict, and `ship` reads a non-zero exit as "the floor could not be decided",
    which §6 binds.
    """
    repo = tmp_path / "repo"
    _init(repo, {_ADR: _adr("Nothing.")}, {_PLAN: "an ordinary change\n"})
    result = _floor_test_process(
        repo,
        stdin=b"M\0" + _ADR.encode() + b"\0",
        old=_git(repo, "rev-parse", "main"),
        new=_git(repo, "rev-parse", "HEAD"),
    )

    assert result.returncode == 2
    assert "not a whole number of 3-field entries" in result.stderr.decode()


def test_ship_binds_when_the_floor_test_is_not_beside_it(tmp_path: Path) -> None:
    """No helper, no answer, so the round is owed — and no path is marked.

    `ship` no longer carries its own copy of the floor's path list (ADR-0209 §6,
    issue #751), so it cannot say *which* path bound when the run that decides
    that is the run that did not happen. It says so instead of guessing.
    """
    repo = tmp_path / "repo"
    _init(repo, {_ADR: _adr("Nothing.")}, {_PLAN: "an ordinary change\n"})
    lonely = tmp_path / "lonely"
    lonely.mkdir()
    shutil.copy(Path(__file__).parents[2] / "scripts" / "ship.sh", lonely / "ship.sh")

    sha = _git(repo, "rev-parse", "HEAD")
    _fake_gh(tmp_path / "bin")
    _record_review(
        repo,
        sha,
        "adversarial",
        f"a real finding\n{_VERDICT}\n",
        base_sha=_git(repo, "merge-base", "main", sha),
    )
    _advance_base(repo, _edit(_ADR, _adr("Ratified.")))
    rebased = _git(repo, "rev-parse", "HEAD")
    result = _run_ship(repo, tmp_path, pr_sha=rebased, args=("--drill",), script=lonely / "ship.sh")

    assert result.returncode != 0
    assert "§3 floor            NOT DECIDED" in result.stderr
    assert "floor_test.py is missing" in result.stderr


# --- §6's disclosure: the record names the test, per floor path ---------------


def test_the_published_record_names_the_test_that_cleared_each_floor_path(tmp_path: Path) -> None:
    """Narrowing what the floor charges for narrows nothing about what is shown.

    ADR-0027 §4 is explicit that the published file set is "not context for a
    decision, it *is* the decision", and ADR-0209 §6 adds the reason beside each
    floor path — so the merge reviewer sees the same whole set plus why each floor
    path was cleared, which is strictly more than they saw before.
    """
    repo = tmp_path / "repo"
    _init(
        repo,
        {_ADR: _adr("Nothing here names anything."), "notes/other.md": "x\n"},
        {_PLAN: "an ordinary change\n"},
    )

    def mutate(r: Path) -> None:
        (r / _ADR).write_text(_adr("Ratified, still naming nothing."))
        (r / "notes" / "other.md").write_text("y\n")

    judged = _judge(repo, tmp_path, mutate)

    assert not judged.owed
    posted = (tmp_path / "comment.md").read_text()
    # The whole set, as §4 has always required.
    assert "**2 file(s) changed by the base move**" in posted
    assert "0042-a-decision-about-things.md" in posted
    assert "notes/other.md" in posted
    # The reason, on the floor path and only on the floor path.
    floor_line = next(line for line in posted.splitlines() if "0042-a-decision" in line)
    other_line = next(line for line in posted.splitlines() if "notes/other.md" in line)
    assert "every ADR-0209 §3/§4 test cleared this path" in floor_line
    assert "—" not in other_line.split("</code>")[-1]


# --- Issue #1750: the description snapshot ------------------------------------


def test_a_citation_deleted_from_the_description_after_a_review_still_binds(
    tmp_path: Path,
) -> None:
    """Issue #1750, closed by the union rather than by a digest.

    ADR-0209 §5 admits the description so that it can ADD a binding and never
    remove one, and states the removal case as an obligation on the lane because
    the acceptance rule reads the body in front of it. The snapshot each round
    records makes that computable: the body at ship time cites nothing, and the
    body the review was taken beside cited `ADR-0042`, so the round is owed.
    """
    repo = tmp_path / "repo"
    _init(repo, {_ADR: _adr("Nothing.")}, {_PLAN: "an ordinary change\n"})

    judged = _judge(
        repo,
        tmp_path,
        _edit(_ADR, _adr("Ratified.")),
        body="No citation here any more.",
        description="This lane implements ADR-0042.",
    )

    assert judged.owed
    assert any("§3 — the PR's text cites ADR-0042" in r for r in judged.reasons)


def test_a_description_edit_that_bound_no_test_still_costs_nothing(tmp_path: Path) -> None:
    """§5 exempts the removal of a citation binding no test, and so does this.

    A digest comparison — issue #1750's own sketch — refuses on any edit at all,
    including this one, which would charge a round the decision does not oblige.
    """
    repo = tmp_path / "repo"
    _init(repo, {_ADR: _adr("Nothing.")}, {_PLAN: "an ordinary change\n"})

    judged = _judge(
        repo,
        tmp_path,
        _edit(_ADR, _adr("Ratified.")),
        body="A tidier description.",
        description="A first draft of the description, citing nothing.",
    )

    assert not judged.owed
    assert judged.reasons == [_FREE]


def test_an_artifact_can_never_select_another_rounds_body(tmp_path: Path) -> None:
    """The snapshot is content-addressed, so the pairing question does not exist.

    An artifact's name is deliberately reused for a re-review of byte-identical
    content (ADR-0027 §6), so naming the snapshot after the artifact meant that an
    interruption between the two writes left one round's artifact beside another
    round's body — in *either* write order, which is what adversarial review of
    this PR found in rounds 1 and 2. Here the artifact names the hash of the body
    it was taken beside; an older body sitting in the same directory is simply a
    different file, and cannot be reached.

    The state that remains after such an interruption is the artifact naming a
    hash whose body never landed, and that is the case below.
    """
    repo = tmp_path / "repo"
    _init(repo, {_ADR: _adr("Nothing.")}, {_PLAN: "an ordinary change\n"})
    stale = repo / ".review" / "descriptions"
    stale.mkdir(parents=True)
    (stale / ("a" * 40)).write_text("an older body, citing nothing at all.")

    judged = _judge(
        repo,
        tmp_path,
        _edit(_ADR, _adr("Ratified.")),
        body="No citation here any more.",
        description="This lane implements ADR-0042.",
    )

    assert judged.owed
    assert any("§3 — the PR's text cites ADR-0042" in r for r in judged.reasons)


def test_a_malformed_snapshot_id_binds(tmp_path: Path) -> None:
    """`pr_desc` is joined onto a path, so anything but a hash is refused.

    The field is read from a file `ship` does not own. Unvalidated it is a read of
    whatever a `../..` in it names, and a value that is neither empty, nor
    `unavailable`, nor a well-formed hash is not a snapshot this script knows how
    to fetch — so §6 binds rather than guessing which of those it meant.
    """
    repo = tmp_path / "repo"
    _init(repo, {_ADR: _adr("Nothing.")}, {_PLAN: "an ordinary change\n"})

    sha = _git(repo, "rev-parse", "HEAD")
    _fake_gh(tmp_path / "bin")
    _record_review(
        repo,
        sha,
        "adversarial",
        f"a real finding\n{_VERDICT}\n",
        base_sha=_git(repo, "merge-base", "main", sha),
        pr_desc="../../../etc/passwd",
    )
    _advance_base(repo, _edit(_ADR, _adr("Ratified.")))
    rebased = _git(repo, "rev-parse", "HEAD")

    result = _run_ship(repo, tmp_path, pr_sha=rebased, args=("--drill",))

    assert result.returncode != 0
    assert "malformed PR-description snapshot id" in result.stderr


def test_a_recorded_snapshot_that_has_gone_missing_binds(tmp_path: Path) -> None:
    """An artifact that CLAIMS a snapshot whose body will not open is §6's.

    This is the one interruption state content-addressing leaves: the snapshot is
    written before the artifact, so a crash between them leaves an orphan body no
    artifact names (inert), and the converse — an artifact naming a hash whose
    body never landed — fails closed here.

    An artifact recording no snapshot at all is a different case and is not a
    failure: it makes no claim about the description.
    """
    repo = tmp_path / "repo"
    _init(repo, {_ADR: _adr("Nothing.")}, {_PLAN: "an ordinary change\n"})

    sha = _git(repo, "rev-parse", "HEAD")
    _fake_gh(tmp_path / "bin")
    _record_review(
        repo,
        sha,
        "adversarial",
        f"a real finding\n{_VERDICT}\n",
        base_sha=_git(repo, "merge-base", "main", sha),
        description="This lane implements ADR-0042.",
    )
    for snapshot in (repo / ".review" / "descriptions").iterdir():
        snapshot.unlink()
    _advance_base(repo, _edit(_ADR, _adr("Ratified.")))
    rebased = _git(repo, "rev-parse", "HEAD")

    result = _run_ship(repo, tmp_path, pr_sha=rebased, args=("--drill",))

    assert result.returncode != 0
    assert "which is missing from .review/descriptions/" in result.stderr


def test_an_artifact_recording_no_snapshot_makes_no_claim(tmp_path: Path) -> None:
    """Every artifact written before the field existed, and the bypass path.

    `pr_desc` absent says "this round asserts nothing about the description", not
    "the description could not be read", so the live body is the whole of §5's
    description input and the move clears. Treating the absence as a failure would
    charge a round on every artifact the repository already holds.
    """
    repo = tmp_path / "repo"
    _init(repo, {_ADR: _adr("Nothing.")}, {_PLAN: "an ordinary change\n"})

    judged = _judge(repo, tmp_path, _edit(_ADR, _adr("Ratified.")), body="Nothing cited.")

    assert not judged.owed
    assert judged.reasons == [_FREE]


def test_an_unreadable_pr_file_binds(tmp_path: Path) -> None:
    """§5's **PR's files** is an input like any other, and §6 reaches it.

    The dotted citation forces the qualifier to be looked for in the complete
    content of every path the PR's diff touches, and the listing names one no
    commit carries — so the input §5 asks for exists in the listing and cannot be
    read. Distinguish that from the endpoint a PR simply does not have, which §5
    says is not a failed read at all.
    """
    repo = tmp_path / "repo"
    _init(
        repo, {_ADR: _adr("Rendering is `Widget.render`.")}, {"src/pkg/w.py": "def render(): ...\n"}
    )
    out = _run_floor_test(
        repo,
        entries=[("M", _ADR, "")],
        old=_git(repo, "rev-parse", "main"),
        new=_git(repo, "rev-parse", "HEAD"),
        # The member IS touched, so the qualifier lookup runs and reaches for the
        # complete content of every path the listing names — one of which is not
        # in any commit.
        pr_diff=b"+def render(self) -> None: ...\n",
        pr_listing=b"M\0src/pkg/never-existed.py\0",
    )

    assert out[0][1] == "bind"
    assert "§6" in out[0][2]


def test_a_cleared_floor_is_necessary_and_not_sufficient(tmp_path: Path) -> None:
    """ADR-0209 §8: clearing the floor buys nothing on its own.

    The base move here touches a `docs/adr/**` path that no test binds — so the
    floor clears — and *also* lands inside the reviewed hunks, which moves the
    patch identity. ADR-0027 §2 refuses that whatever §§1-4 here say, and a
    narrowed floor must not have quietly become a second acceptance path.
    """
    lines = [f"line {i}" for i in range(1, 121)]
    reviewed = list(lines)
    reviewed[59] = "line 60 — the reviewed change"
    moved = list(reviewed)
    # Two lines above the reviewed edit: inside its three lines of context, so the
    # identity moves, and far enough apart that the rebase applies cleanly rather
    # than testing git's merge.
    moved[57] = "line 58 — the base moved"
    repo = tmp_path / "repo"
    _init(
        repo,
        {_ADR: _adr("Nothing here names anything."), "src/x.py": "\n".join(lines) + "\n"},
        {"src/x.py": "\n".join(reviewed) + "\n"},
    )

    def mutate(r: Path) -> None:
        (r / _ADR).write_text(_adr("Ratified, still naming nothing."))
        base_moved = list(lines)
        base_moved[57] = "line 58 — the base moved"
        (r / "src" / "x.py").write_text("\n".join(base_moved) + "\n")

    judged = _judge(repo, tmp_path, mutate)

    assert judged.owed
    # Not a floor verdict at all: no artifact reached §2(b), so nothing was tested
    # and the drill makes no floor claim either way.
    assert judged.reasons == []
    assert "§3 floor              NOT EVALUATED" in judged.stderr
    assert (
        "reviewed patch is no longer"
        in _run_ship(repo, tmp_path, pr_sha=_git(repo, "rev-parse", "HEAD")).stderr
    )


# --- Driving `floor_test.py` directly -----------------------------------------

_FLOOR_TEST = Path(__file__).parents[2] / "scripts" / "floor_test.py"


def _floor_test_process(  # noqa: PLR0913  # one parameter per input the helper reads
    repo: Path,
    *,
    stdin: bytes,
    old: str,
    new: str,
    pr_listing: bytes | None = None,
    pr_diff: bytes = b"",
    pr_head: str | None = None,
) -> subprocess.CompletedProcess[bytes]:
    """Run `floor_test.py` against `repo`, with inputs the caller controls."""
    scratch = repo.parent / "floor-inputs"
    scratch.mkdir(exist_ok=True)
    diff = scratch / "pr.diff"
    listing = scratch / "pr.listing"
    diff.write_bytes(pr_diff)
    if pr_listing is None:
        pr_listing = subprocess.run(  # noqa: S603  # resolved git path, test-controlled repo
            [
                str(shutil.which("git")),
                "diff",
                "--name-status",
                "-M",
                "-z",
                f"{_git(repo, 'merge-base', 'main', 'HEAD')}...HEAD",
            ],
            cwd=repo,
            check=True,
            capture_output=True,
        ).stdout
    listing.write_bytes(pr_listing)
    description = scratch / "description"
    description.write_text("")
    return subprocess.run(  # noqa: S603  # fixed argv, in-repo script
        [
            sys.executable,
            str(_FLOOR_TEST),
            "--repo",
            str(repo),
            "--old-base",
            old,
            "--new-base",
            new,
            "--pr-base",
            _git(repo, "merge-base", "main", "HEAD"),
            "--pr-head",
            pr_head if pr_head is not None else _git(repo, "rev-parse", "HEAD"),
            "--pr-diff",
            str(diff),
            "--pr-listing",
            str(listing),
            "--description",
            str(description),
        ],
        cwd=repo,
        input=stdin,
        check=False,
        capture_output=True,
    )


def _run_floor_test(  # noqa: PLR0913  # one parameter per input the helper reads
    repo: Path,
    *,
    entries: list[tuple[str, str, str]],
    old: str,
    new: str,
    pr_listing: bytes | None = None,
    pr_diff: bytes = b"",
    pr_head: str | None = None,
) -> list[tuple[str, str, str]]:
    """Return one `(floor, verdict, reason)` triple per entry."""
    stdin = b"".join(b"\0".join(field.encode() for field in entry) + b"\0" for entry in entries)
    result = _floor_test_process(
        repo,
        stdin=stdin,
        old=old,
        new=new,
        pr_listing=pr_listing,
        pr_diff=pr_diff,
        pr_head=pr_head,
    )
    assert result.returncode == 0, result.stderr.decode()
    fields = result.stdout.decode().split("\0")[:-1]
    assert len(fields) == len(entries) * 3
    return [(fields[i], fields[i + 1], fields[i + 2]) for i in range(0, len(fields), 3)]
