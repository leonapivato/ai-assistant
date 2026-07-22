"""Tests for the cross-change review-history view (scripts/review_history.py).

Hermetic by construction: every test drives the script's ``--from-json`` seam
with a payload written into a tmp_path, or calls the parsing/rendering functions
directly. Nothing here invokes ``gh``, so ``uv run pytest`` makes no network call
and no assertion depends on the live state of this repo's pull requests.

The cases the report must not flatten each get their own test: a lower-bound
churn figure, a ``churn n/a`` diff, a merged PR with no ship comment, and a ship
comment carrying no aggregate. All of them are "absent or understated", never
zero — and the last two are different absences that must not share one
explanation.

The two non-ASCII glyphs ship renders are spelled as escapes (``_TIMES``,
``_GE``) so the source stays unambiguous while matching the bytes ship posts.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from types import ModuleType

_SCRIPT = Path(__file__).parents[2] / "scripts" / "review_history.py"


def _load() -> ModuleType:
    """Import the script as a module so its functions can be called directly."""
    spec = importlib.util.spec_from_file_location("review_history", _SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Registered before execution: dataclasses resolves annotations through
    # sys.modules[cls.__module__], which is absent for a module loaded by spec.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


rh = _load()


def _ship(sha: str, summary: str | None) -> str:
    """Build a ship comment body exactly as scripts/ship.sh renders it (CRLF)."""
    lines = [f"<!-- ship:{sha} -->", f"🔍 **Local Codex review** — commit `{sha[:12]}`", ""]
    if summary is not None:
        lines += [f"_{summary}_", ""]
    lines += ["<details><summary><strong>adversarial</strong></summary>", "APPROVE", "</details>"]
    return "\r\n".join(lines)


def _comment(body: str, author: str = "owner") -> dict[str, object]:
    """One comment as `gh pr list --json comments` returns it."""
    return {"body": body, "author": {"login": author}, "authorAssociation": "OWNER"}


_ABSENT = object()  # `headRefOid` not in the payload at all, vs. present and null.


def _pr(
    number: int,
    title: str,
    comments: list[str | dict[str, object]],
    merged_at: str = "",
    head: object = _ABSENT,
) -> dict[str, object]:
    entry: dict[str, object] = {
        "number": number,
        "title": title,
        "mergedAt": merged_at,
        "comments": [_comment(c) if isinstance(c, str) else c for c in comments],
    }
    if head is not _ABSENT:
        entry["headRefOid"] = head
    return entry


_TIMES = "\u00d7"
_GE = "\u2265"

_EXACT = f"round 3 · 346 lines net across 3 commit(s) · churn 1.1{_TIMES} (366 touched)"
_LOWER = (
    f"round 29 · 289 lines net across 3 commit(s) · churn {_GE}1.0{_TIMES} "
    "(303 touched; lower bound — history rewritten, earlier rounds not counted)"
)
_NA = "round 2 · 0 lines net across 1 commit(s) · churn n/a (40 touched)"
_NA_LOWER = (
    "round 4 · 0 lines net across 2 commit(s) · churn n/a (40 touched) · "
    "history rewritten, earlier rounds not counted"
)


def _run(payload: list[dict[str, object]], tmp_path: Path, *args: str) -> str:
    saved = tmp_path / "prs.json"
    saved.write_text(json.dumps(payload), encoding="utf-8")
    result = subprocess.run(  # noqa: S603  # fixed interpreter + in-repo script
        [sys.executable, str(_SCRIPT), "--from-json", str(saved), "--ship-author", "owner", *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


# --- summary-line parsing ----------------------------------------------------


def test_parses_an_exact_aggregate() -> None:
    agg = rh.parse_summary(f"_{_EXACT}_")
    assert agg is not None
    assert (agg.round, agg.net_lines, agg.commits) == (3, 346, 3)
    assert agg.churn_ratio == pytest.approx(1.1)
    assert agg.churn_lines == 366
    assert agg.churn_is_lower_bound is False


def test_lower_bound_churn_is_flagged_not_treated_as_exact() -> None:
    agg = rh.parse_summary(f"_{_LOWER}_")
    assert agg is not None
    assert agg.round == 29
    assert agg.churn_ratio == pytest.approx(1.0)
    assert agg.churn_is_lower_bound is True


def test_not_applicable_churn_is_none_not_zero() -> None:
    agg = rh.parse_summary(f"_{_NA}_")
    assert agg is not None
    assert agg.churn_ratio is None  # absent, not 0.0
    assert agg.churn_lines == 40
    assert agg.churn_is_lower_bound is False


def test_not_applicable_churn_can_also_be_a_lower_bound() -> None:
    agg = rh.parse_summary(f"_{_NA_LOWER}_")
    assert agg is not None
    assert agg.churn_ratio is None
    assert agg.churn_is_lower_bound is True


def test_a_pre_aggregate_summary_line_is_not_a_summary() -> None:
    assert rh.parse_summary("_something else entirely_") is None
    assert rh.parse_summary("") is None


def test_an_aggregate_without_a_churn_clause_still_parses() -> None:
    agg = rh.parse_summary("_round 2 · 40 lines net across 1 commit(s)_")
    assert agg is not None
    assert (agg.round, agg.churn_ratio, agg.churn_lines) == (2, None, None)


# --- which comment counts ----------------------------------------------------


def _c(body: str, author: str = "owner") -> object:
    return rh.Comment(body=body, author=author)


def test_a_quoted_marker_without_the_header_is_not_a_ship_comment() -> None:
    forged = "<!-- ship:66f455957a6c00b227013b5b06cd2324f11d4472 -->\r\nsee above\r\n"
    assert rh.aggregate_from_comments([_c(forged)], "owner") is None


@pytest.mark.parametrize("impostor", ["stranger", "read-only-collaborator", "org-member"])
def test_a_complete_forgery_from_another_account_is_ignored(impostor: str) -> None:
    """Any account can quote the marker, header and a summary verbatim.

    A GitHub association is a relationship to the repository, not write access —
    a read-only COLLABORATOR or an org MEMBER can post a comment too. Only the
    ship account's own login is accepted, so none of them can displace the
    genuine terminal aggregate.
    """
    forged = _ship("f" * 40, "round 999 · 1 lines net · churn 9.9x (10 touched)")
    comments = [_c(_ship("a" * 40, _EXACT)), _c(forged, impostor)]
    agg = rh.aggregate_from_comments(comments, "owner")
    assert agg is not None
    assert agg.round == 3  # the genuine one, not the later forgery


def test_a_terminal_ship_comment_without_a_summary_does_not_fall_back() -> None:
    """The last ship comment is the terminal record, summary or not.

    Falling through to an earlier one would report a superseded round as this
    PR's terminal figure — a wrong number, worse than the absence.
    """
    bodies = [_c(_ship("a" * 40, _EXACT)), _c(_ship("b" * 40, None))]
    assert rh.aggregate_from_comments(bodies, "owner") is None


def test_a_summary_shaped_line_in_the_review_body_is_not_the_aggregate() -> None:
    """Only line 3 is the aggregate; the review prose below it is unconstrained."""
    body = "\r\n".join(
        [
            "<!-- ship:" + "c" * 40 + " -->",
            "\N{LEFT-POINTING MAGNIFYING GLASS} **Local Codex review** \N{EM DASH} commit `"
            + "c" * 12
            + "`",
            "",
            "<details><summary><strong>adversarial</strong></summary>",
            "The author claimed _round 999 \N{MIDDLE DOT} 1 lines net \N{MIDDLE DOT} "
            "churn 9.9\N{MULTIPLICATION SIGN} (10 touched)_ which is wrong.",
            "APPROVE",
            "</details>",
        ]
    )
    assert rh.aggregate_from_comments([_c(body)], "owner") is None


def test_the_last_ship_comment_wins() -> None:
    bodies = [_c(_ship("a" * 40, _EXACT)), _c("unrelated chatter"), _c(_ship("b" * 40, _LOWER))]
    agg = rh.aggregate_from_comments(bodies, "owner")
    assert agg is not None
    assert agg.round == 29


def test_a_pr_with_no_ship_comment_has_no_aggregate() -> None:
    prs = rh.parse_pull_requests([_pr(90, "docs: something", ["just a review note"])], "owner")
    assert prs[0].aggregate is None
    assert prs[0].kind == "docs"


@pytest.mark.parametrize(
    ("entry", "expected"),
    [
        ({"title": "x", "comments": []}, "no 'number'"),
        ({"number": "not-a-number"}, "not an integer"),
        ({"number": 1, "comments": {}}, "'comments' is not a list"),
        ("a string", "expected each pull request"),
        # A malformed *member* of a well-formed list raises too, naming where.
        ({"number": 7, "comments": [None]}, r"PR 7: comment at index 0"),
        ({"number": 7, "comments": ["a string"]}, r"PR 7: comment at index 0"),
    ],
)
def test_every_malformed_entry_raises_value_error(entry: object, expected: str) -> None:
    """The documented ValueError, never a bare KeyError or TypeError from inside."""
    with pytest.raises(ValueError, match=expected):
        rh.parse_pull_requests([entry], "owner")


def test_a_malformed_comment_member_is_not_silently_dropped() -> None:
    """Filtering it would report a PR as having fewer comments than it carries.

    In a mixed list that is worse than a wrong count: the dropped member could be
    the ship comment the report exists to read, and the row would then show an
    earlier round or none at all (issue #158).
    """
    entry = {"number": 7, "comments": [None, _comment(_ship("1" * 40, _EXACT))]}
    with pytest.raises(ValueError, match=r"PR 7: comment at index 0 is not a JSON object"):
        rh.parse_pull_requests([entry], "owner")


def test_a_malformed_comment_member_is_reported_by_the_cli(tmp_path: Path) -> None:
    saved = tmp_path / "prs.json"
    saved.write_text(json.dumps([{"number": 7, "comments": [None]}]), encoding="utf-8")
    result = subprocess.run(  # noqa: S603  # fixed interpreter + in-repo script
        [sys.executable, str(_SCRIPT), "--from-json", str(saved), "--ship-author", "owner"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert "PR 7: comment at index 0 is not a JSON object" in result.stderr


def test_a_full_page_of_comments_is_flagged_as_possibly_truncated(tmp_path: Path) -> None:
    filler = [_comment("chatter") for _ in range(rh._COMMENT_PAGE - 1)]
    payload = [
        _pr(1, "fix: a", [*filler, _comment(_ship("1" * 40, _EXACT))]),
        _pr(2, "fix: b", [_ship("2" * 40, _EXACT)]),
    ]
    out = _run(payload, tmp_path)
    assert "comment list may be truncated on #1" in out
    assert "which the medians above then include" in out
    assert "#2" not in out.split("truncated on")[1]


def test_a_malformed_payload_is_reported_not_crashed(tmp_path: Path) -> None:
    saved = tmp_path / "prs.json"
    saved.write_text('{"not": "a list"}', encoding="utf-8")
    result = subprocess.run(  # noqa: S603  # fixed interpreter + in-repo script
        [sys.executable, str(_SCRIPT), "--from-json", str(saved), "--ship-author", "owner"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert "expected a JSON list" in result.stderr


def test_from_json_without_a_ship_author_is_refused(tmp_path: Path) -> None:
    saved = tmp_path / "prs.json"
    saved.write_text("[]", encoding="utf-8")
    result = subprocess.run(  # noqa: S603  # fixed interpreter + in-repo script
        [sys.executable, str(_SCRIPT), "--from-json", str(saved)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "--from-json needs --ship-author" in result.stderr


def test_a_bad_limit_is_rejected(tmp_path: Path) -> None:
    saved = tmp_path / "prs.json"
    saved.write_text("[]", encoding="utf-8")
    result = subprocess.run(  # noqa: S603  # fixed interpreter + in-repo script
        [
            sys.executable,
            str(_SCRIPT),
            "--from-json",
            str(saved),
            "--ship-author",
            "o",
            "--limit",
            "0",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "--limit must be at least 1" in result.stderr


# --- the report --------------------------------------------------------------


def test_medians_use_only_the_exact_figures(tmp_path: Path) -> None:
    payload = [
        _pr(1, "fix(dev): a", [_ship("1" * 40, _EXACT)]),  # round 3, 1.1x exact
        _pr(2, "docs: b", [_ship("2" * 40, _LOWER)]),  # round 29, lower bound
        _pr(3, "feat: c", [_ship("3" * 40, _NA)]),  # round 2, n/a
        _pr(4, "docs: d", ["no ship here"]),  # no ship comment
    ]
    out = _run(payload, tmp_path)
    # Three PRs have a round; median of {3, 29, 2} is 3. Only one exact churn.
    assert "3 with a review aggregate" in out
    assert "median 3 round(s) over 3 PR(s)" in out
    assert f"median churn 1.1{_TIMES} over 1 exact" in out
    # Each excluded figure is named, and none is silently zero.
    assert "1 churn figure(s) are lower bounds" in out
    assert "1 diff(s) report churn n/a" in out
    assert "1 merged PR(s) carry no ship comment" in out
    # No row renders an absent figure as a measured zero.
    assert not [
        line for line in out.splitlines() if line.startswith("  #") and f"0.0{_TIMES}" in line
    ]


def test_rows_distinguish_lower_bound_absent_and_missing(tmp_path: Path) -> None:
    payload = [
        _pr(1, "fix(dev): a", [_ship("1" * 40, _EXACT)]),
        _pr(2, "docs: b", [_ship("2" * 40, _LOWER)]),
        _pr(3, "feat: c", [_ship("3" * 40, _NA)]),
        _pr(4, "docs: d", ["no ship here"]),
    ]
    rows = {
        line.split()[0]: line
        for line in _run(payload, tmp_path).splitlines()
        if line.startswith("  #")
    }
    assert f"1.1{_TIMES}" in rows["#1"]
    assert _GE not in rows["#1"]
    assert f"{_GE}1.0{_TIMES}" in rows["#2"]
    assert "n/a" in rows["#3"]
    assert "(no ship comment)" in rows["#4"]


def test_outliers_are_flagged_against_the_median(tmp_path: Path) -> None:
    payload = [
        _pr(
            n,
            "fix: x",
            [_ship(str(n) * 40, f"round 2 · 10 lines net · churn 1.0{_TIMES} (10 touched)")],
        )
        for n in range(1, 5)
    ]
    payload.append(
        _pr(
            9,
            "docs: big",
            [_ship("9" * 40, f"round 21 · 10 lines net · churn 1.0{_TIMES} (10 touched)")],
        )
    )
    out = _run(payload, tmp_path)
    assert f"outliers (>2{_TIMES} median rounds): 1 of 5" in out
    assert "<- outlier" in [
        line.split("  ")[-1].strip() for line in out.splitlines() if "#9" in line
    ]


def test_an_empty_window_renders_without_statistics(tmp_path: Path) -> None:
    out = _run([], tmp_path)
    assert "no aggregate to report" in out
    assert "outliers" not in out


def test_the_window_is_ordered_by_merge_time_not_creation(tmp_path: Path) -> None:
    """gh orders by creation, so an old PR merged recently must still make the cut."""
    payload = [
        _pr(50, "fix: newly created, merged first", [_ship("5" * 40, _EXACT)], "2026-01-01T00:00Z"),
        _pr(40, "fix: also old", [_ship("4" * 40, _EXACT)], "2026-01-02T00:00Z"),
        _pr(3, "fix: old PR, merged last", [_ship("3" * 40, _EXACT)], "2026-06-01T00:00Z"),
    ]
    rows = [
        line
        for line in _run(payload, tmp_path, "--limit", "1").splitlines()
        if line.startswith("  #")
    ]
    assert len(rows) == 1
    assert "#3" in rows[0]


def test_a_payload_without_merge_times_keeps_its_order_and_says_so(tmp_path: Path) -> None:
    """A fixture captured without `mergedAt` cannot be merge-ordered.

    The fallback is the payload's own order, which is what makes hermetic
    fixtures possible — but the report names the PRs it could not order rather
    than presenting the result as a merge-time window.
    """
    payload = [_pr(n, "fix: x", [_ship(str(n) * 40, _EXACT)]) for n in (9, 4, 7)]
    out = _run(payload, tmp_path)
    numbers = [line.split()[0] for line in out.splitlines() if line.startswith("  #")]
    assert numbers == ["#9", "#4", "#7"]
    assert "no merge time on #9, #4, #7" in out


def test_an_undated_pr_cut_from_the_window_is_still_named(tmp_path: Path) -> None:
    """An undated PR sorts last, so it is the one slicing removes first.

    Reporting only the undated PRs that survived would go quiet in exactly the
    case the warning exists for.
    """
    payload = [
        _pr(1, "fix: undated", [_ship("1" * 40, _EXACT)]),
        _pr(2, "fix: dated", [_ship("2" * 40, _EXACT)], "2026-06-01T00:00Z"),
    ]
    out = _run(payload, tmp_path, "--limit", "1")
    rows = [line for line in out.splitlines() if line.startswith("  #")]
    assert len(rows) == 1
    assert "#2" in rows[0]
    assert "no merge time on #1" in out


def test_a_fully_dated_window_claims_no_ordering_fallback(tmp_path: Path) -> None:
    payload = [_pr(1, "fix: x", [_ship("1" * 40, _EXACT)], "2026-01-01T00:00Z")]
    assert "no merge time on" not in _run(payload, tmp_path)


def test_an_n_a_churn_that_was_also_rewritten_keeps_both_facts(tmp_path: Path) -> None:
    payload = [_pr(1, "fix: a", [_ship("1" * 40, _NA_LOWER)])]
    out = _run(payload, tmp_path)
    assert "1 diff(s) report churn n/a" in out
    assert "1 of those also had history rewritten" in out


def test_no_churn_clause_is_not_reported_as_n_a(tmp_path: Path) -> None:
    """An aggregate with no churn clause measured nothing; `n/a` is a measurement."""
    payload = [_pr(1, "fix: a", [_ship("1" * 40, "round 2 · 40 lines net across 1 commit(s)")])]
    out = _run(payload, tmp_path)
    assert "carry no churn clause at all" in out
    assert "report churn n/a" not in out
    row = next(line for line in out.splitlines() if line.startswith("  #1"))
    assert "n/a" not in row


def test_a_plain_n_a_churn_claims_no_rewrite(tmp_path: Path) -> None:
    payload = [_pr(1, "fix: a", [_ship("1" * 40, _NA)])]
    out = _run(payload, tmp_path)
    assert "1 diff(s) report churn n/a" in out
    assert "also had history rewritten" not in out


def test_a_sliced_saved_payload_reports_the_pool_it_cannot_verify(tmp_path: Path) -> None:
    payload = [
        _pr(n, "fix: x", [_ship(str(n) * 40, _EXACT)], f"2026-01-{n:02d}T00:00Z")
        for n in range(1, 4)
    ]
    assert "the pool this window was ordered within was full" in _run(
        payload, tmp_path, "--limit", "2"
    )
    # Equality is the boundary: a payload of exactly the window size may be a
    # capture capped at that size, so it takes the caveat too.
    assert "the pool this window was ordered within was full" in _run(
        payload, tmp_path, "--limit", "3"
    )
    assert "the pool this window was ordered within was full" not in _run(
        payload, tmp_path, "--limit", "5"
    )


def test_limit_applies_to_a_saved_payload_too(tmp_path: Path) -> None:
    payload = [
        _pr(n, "fix: x", [_ship(str(n) * 40, _EXACT)], f"2026-01-{6 - n:02d}T00:00Z")
        for n in range(1, 6)
    ]
    out = _run(payload, tmp_path, "--limit", "2")
    rows = [line for line in out.splitlines() if line.startswith("  #")]
    assert "last 2 merged PR(s)" in out
    assert [r.split()[0] for r in rows] == ["#1", "#2"]


# --- the two absences (#155) -------------------------------------------------


def test_a_ship_comment_without_an_aggregate_is_not_reported_as_unshipped(
    tmp_path: Path,
) -> None:
    """The marker is there; only the figures are missing.

    Explaining it as "merged before the marker existed, or admin-merged without
    one" would be a false statement about a correctly-excluded PR (issue #155).
    """
    payload = [
        _pr(1, "fix: shipped, pre-aggregate", [_ship("1" * 40, None)]),
        _pr(2, "fix: never shipped", ["just a review note"]),
    ]
    out = _run(payload, tmp_path)
    rows = {line.split()[0]: line for line in out.splitlines() if line.startswith("  #")}
    assert "(ship comment, no aggregate)" in rows["#1"]
    assert "(no ship comment)" in rows["#2"]
    assert "1 merged PR(s) carry a ship comment whose summary line is" in out
    assert "1 merged PR(s) carry no ship comment" in out
    # Neither contributes a round, and the headline says aggregates, not comments.
    assert "0 with a review aggregate" in out


def test_an_unparseable_summary_is_not_claimed_to_predate_the_aggregate(
    tmp_path: Path,
) -> None:
    """A missing summary and a corrupted one are indistinguishable from here.

    A pre-ADR-0020 §2 artifact is the ordinary cause, but an edited or truncated
    line 3 lands in the same bucket — so the report offers that cause rather than
    asserting it, the same over-claim issue #155 is about one level down.
    """
    payload = [_pr(1, "fix: a", [_ship("1" * 40, "round x - not a summary at all")])]
    out = _run(payload, tmp_path)
    assert "(ship comment, no aggregate)" in out
    assert "an edited or" in out
    assert "truncated summary reads the same from here, so neither is asserted." in out


def test_the_two_absences_are_counted_separately() -> None:
    prs = rh.parse_pull_requests(
        [
            _pr(1, "fix: a", [_ship("1" * 40, None)]),
            _pr(2, "fix: b", ["chatter"]),
        ],
        "owner",
    )
    assert [p.has_ship_comment for p in prs] == [True, False]
    stats = rh.summarize(prs)
    assert (stats.no_aggregate, stats.unshipped) == (1, 1)


def test_last_ship_record_reports_the_marker_and_the_absence() -> None:
    found = rh.last_ship_record([rh.Comment(body=_ship("a" * 40, _EXACT), author="owner")], "owner")
    assert found.found is True
    assert found.marker_sha == "a" * 40
    assert found.aggregate is not None
    missing = rh.last_ship_record([rh.Comment(body="chatter", author="owner")], "owner")
    assert (missing.found, missing.aggregate, missing.marker_sha) == (False, None, "")


# --- head differs from the ship marker (#161) --------------------------------


def test_a_head_the_ship_marker_does_not_name_is_marked_but_still_counted(
    tmp_path: Path,
) -> None:
    """The row is marked and the medians still include it.

    The loop each row reports happened whatever the difference means, and this
    report measures review loops, not merge coverage (issue #161).
    """
    payload = [
        _pr(1, "fix: a", [_ship("a" * 40, _EXACT)], "2026-01-02T00:00Z", head="b" * 40),
        _pr(2, "fix: b", [_ship("c" * 40, _EXACT)], "2026-01-01T00:00Z", head="c" * 40),
    ]
    out = _run(payload, tmp_path)
    rows = {line.split()[0]: line for line in out.splitlines() if line.startswith("  #")}
    assert "<- head differs from ship marker" in rows["#1"]
    assert "head differs" not in rows["#2"]
    assert "! ship marker names a commit other than the PR head on #1." in out
    # Not excluded: both PRs are in the median.
    assert "2 with a review aggregate" in out
    assert "median 3 round(s) over 2 PR(s)" in out


def test_a_differing_head_is_not_reported_as_unreviewed_content(tmp_path: Path) -> None:
    """A new commit ID is not evidence that unreviewed work merged.

    ADR-0020 §3 keeps a review valid across an amend, squash, rebase or revert
    that leaves the reviewed tree and base unchanged — each of which produces a
    different head. Only the trees could tell that apart from an unshipped
    commit, and this report does not read them, so it claims neither.
    """
    payload = [_pr(1, "fix: a", [_ship("a" * 40, _EXACT)], head="b" * 40)]
    out = _run(payload, tmp_path)
    assert "is the whole observation." in out
    assert "Nor does a differing head say" in out
    assert "ADR-0020 §3 keeps a review valid across an" in out
    # No wording anywhere that would read as a verdict on the merge.
    assert "merged past" not in out
    assert "outran" not in out


def test_the_observation_names_the_pr_head_not_the_merge_commit(tmp_path: Path) -> None:
    """`headRefOid` is the branch head, which is what the ship marker names.

    The merge commit is deliberately not what is compared: GitHub's squash and
    rebase merges mint a new one for every PR, so that comparison would differ
    always and observe nothing. The report says which commit it read.
    """
    payload = [_pr(1, "fix: a", [_ship("a" * 40, _EXACT)], head="b" * 40)]
    out = _run(payload, tmp_path)
    assert "`headRefOid` is the branch head, not the merge" in out
    assert "commit — a squash or rebase merge mints a new one every time, so that" in out


def test_an_abbreviated_marker_of_the_merged_head_is_not_a_difference(tmp_path: Path) -> None:
    payload = [_pr(1, "fix: a", [_ship("a" * 12, _EXACT)], head="a" * 40)]
    assert "head differs" not in _run(payload, tmp_path)


def test_a_payload_without_a_head_reports_no_difference(tmp_path: Path) -> None:
    """`headRefOid` absent proves nothing, so nothing is observed."""
    payload = [_pr(1, "fix: a", [_ship("a" * 40, _EXACT)])]
    assert "head differs" not in _run(payload, tmp_path)


@pytest.mark.parametrize("head", [1, "", "aaaaaaaa", "z" * 40, "a" * 41, None, ["a" * 40]])
def test_a_head_that_is_not_a_full_object_id_supports_no_observation(
    head: object, tmp_path: Path
) -> None:
    """Even the narrow observation needs a head that can be compared.

    `gh` returns `headRefOid` as a full object ID. Anything else is a payload
    that cannot support it, and reporting a difference anyway — `"1"` does not
    match a SHA, so the row would be marked — would be fabricated.
    """
    payload = [_pr(1, "fix: a", [_ship("a" * 40, _EXACT)], head=head)]
    assert "head differs" not in _run(payload, tmp_path)


def test_a_head_is_matched_case_insensitively(tmp_path: Path) -> None:
    payload = [_pr(1, "fix: a", [_ship("A" * 40, _EXACT)], head="a" * 40)]
    assert "head differs" not in _run(payload, tmp_path)


def test_a_pr_with_no_ship_comment_never_reports_a_differing_head(
    tmp_path: Path,
) -> None:
    """There is no marker to compare, so nothing can be observed about the head."""
    payload = [_pr(1, "fix: a", ["chatter"], head="b" * 40)]
    assert "head differs" not in _run(payload, tmp_path)


# --- paginating a PR's comments (#157) ---------------------------------------


def test_fetch_comments_pages_and_renames_the_rest_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`gh api --paginate` is asked for the REST endpoint, one object per line.

    The REST payload names the commenter `user.login`, not `author.login`, so the
    jq filter renames it — this pins both the invocation and the shape returned.
    """
    seen: list[list[str]] = []

    def fake_gh(argv: list[str]) -> str:
        seen.append(argv)
        return '{"body":"one","author":{"login":"owner"}}\n{"body":"two","author":{"login":"x"}}\n'

    monkeypatch.setattr(rh, "_gh", fake_gh)
    comments = rh.fetch_comments(42)
    assert comments == [
        {"body": "one", "author": {"login": "owner"}},
        {"body": "two", "author": {"login": "x"}},
    ]
    argv = seen[0]
    assert argv[:3] == ["gh", "api", "--paginate"]
    assert argv[3] == "repos/{owner}/{repo}/issues/42/comments"
    assert ".user.login" in argv[-1]


def test_fetch_comments_asks_for_only_the_opening_lines_of_each_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Whole bodies are megabytes on a long-running PR, and nothing reads them.

    `ship.sh` fetches only the opening lines at this same endpoint for exactly
    that reason. Everything the parser looks at — marker, header, blank, summary
    — is in that prefix, so the trim bounds what is retained by the comment count
    rather than by how much anyone wrote.
    """
    seen: list[list[str]] = []

    def fake_gh(argv: list[str]) -> str:
        seen.append(argv)
        return ""

    monkeypatch.setattr(rh, "_gh", fake_gh)
    rh.fetch_comments(42)
    assert f'split("\\n")[0:{rh._BODY_LINES}]' in seen[0][-1]


def test_a_body_trimmed_to_the_opening_lines_still_yields_its_aggregate() -> None:
    """The trim must not cost the figures — the summary is inside the prefix."""
    full = _ship("a" * 40, _EXACT)
    trimmed = "\n".join(full.split("\n")[: rh._BODY_LINES])
    record = rh.last_ship_record([rh.Comment(body=trimmed, author="owner")], "owner")
    assert record.aggregate is not None
    assert record.aggregate.round == 3
    assert record.marker_sha == "a" * 40


def test_a_pr_at_the_page_boundary_is_refetched_in_full(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A full page means the connection may be short of the last ship comment.

    That comment is exactly the one the report reads, so the boundary entry is
    refetched through the paging endpoint and the whole list replaces it.
    """
    calls: list[int] = []

    def fake_fetch(number: int) -> list[dict[str, object]]:
        calls.append(number)
        return [_comment("filler"), _comment(_ship("1" * 40, _LOWER))]

    monkeypatch.setattr(rh, "fetch_comments", fake_fetch)
    payload = [
        # A full page whose last ship comment is the (stale) one gh returned.
        _pr(1, "fix: a", [*[_comment("chatter") for _ in range(99)], _ship("0" * 40, _EXACT)]),
        _pr(2, "fix: b", [_ship("2" * 40, _EXACT)]),
    ]
    repaged = rh._repage_comments(payload)
    assert calls == [1]  # only the boundary PR costs a call
    prs = rh.parse_pull_requests(repaged, "owner", comments_complete=True)
    assert prs[0].aggregate is not None
    assert prs[0].aggregate.round == 29  # the comment gh had truncated away
    assert prs[1].aggregate is not None
    assert prs[1].aggregate.round == 3


def test_a_paged_payload_raises_no_truncation_warning() -> None:
    """The detection is kept for saved payloads, whose provenance is unknown."""
    payload = [_pr(1, "fix: a", [_comment("chatter") for _ in range(rh._COMMENT_PAGE)])]
    paged = rh.parse_pull_requests(payload, "owner", comments_complete=True)
    saved = rh.parse_pull_requests(payload, "owner")
    assert paged[0].comments_may_be_truncated is False
    assert saved[0].comments_may_be_truncated is True


def test_repaging_leaves_a_malformed_entry_for_the_parser_to_report() -> None:
    """Validation lives in one place; repaging must not raise its own error."""
    payload = [{"number": "not-a-number", "comments": [{} for _ in range(rh._COMMENT_PAGE)]}]
    assert rh._repage_comments(payload) is payload
    with pytest.raises(ValueError, match="not an integer"):
        rh.parse_pull_requests(payload, "owner")


def test_the_report_states_it_does_not_gate(tmp_path: Path) -> None:
    out = _run([_pr(1, "fix: a", [_ship("1" * 40, _EXACT)])], tmp_path)
    assert "nothing here gates a ship" in out
