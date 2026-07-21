#!/usr/bin/env python3
"""Print the review aggregate across recently merged PRs — the cross-change view.

Every review aggregate today is scoped to one loop: ``codex-review.sh`` computes
round, net diff and churn for the branch it runs on, and ``ship.sh`` renders that
line into the PR comment. So each change reports on itself and nothing reads the
reports together — which leaves an agent at round 7 with no reference class, and
leaves ADR-0020 §2 and ADR-0025 §3 phrasing their upgrade condition ("observed
being ignored *across several changes*") in terms of a view that does not exist
(issue #146).

This adds no instrumentation. It reads the comments ``ship.sh`` already posts —
each carries a ``<!-- ship:<sha> -->`` marker and a summary line — and reports
the distribution. ``.review/*.md`` is deliberately *not* read: it is git-ignored
and holds only the loops that ran in one clone, so it could only make the picture
lossy in a way a reader could not see.

Three things the per-loop code gets right and this report must not flatten:

- A **lower-bound** churn figure (``churn_bound=lower``, history rewritten) is
  understated by an unknown amount. It is marked as a bound and kept out of the
  churn median rather than averaged in as if exact.
- **``churn n/a``** (a binary- or rename-only diff) is *absent*, not zero. It is
  counted and named, never folded in as a measured zero.
- A merged PR with **no ship comment** (merged before the marker existed, or
  admin-merged without one) is absent too, not a zero-round change. It is listed
  and excluded from both medians.

This reports; it does not gate. Whether the evidence argues for a soft gate is
ADR-0020's and ADR-0025's call to make, not this script's (issue #146, "out of
scope").

Run via ``just review-history`` (or ``python3 scripts/review_history.py``). Pass
``--limit`` for a different window, or ``--from-json`` to read a saved
``gh pr list --json number,title,comments`` payload instead of calling ``gh`` —
which is the seam the tests drive, so they never touch the network.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

# The two opening lines that identify a ship comment (scripts/ship.sh). Both are
# required: the marker alone is public text anyone can quote into a comment, and
# ship itself recognises its own comment by this pair.
_MARKER_RE = re.compile(r"^<!-- ship:[0-9a-fA-F]{7,40} -->$")
_HEADER_RE = re.compile(r"^🔍 \*\*Local Codex review\*\* — commit `[0-9a-fA-F]{7,40}`$")

# The summary line ship renders from the adversarial artifact's provenance, e.g.
#   _round 29 · 289 lines net across 3 commit(s) · churn >=1.0x (303 touched; ...)_
# The two non-ASCII glyphs ship uses are spelled as escapes so the source stays
# unambiguous (ruff RUF001) while matching the bytes GitHub actually carries.
_ROUND_RE = re.compile(r"^_round (?P<round>\d+) · (?P<net>-?\d+) lines net")
_COMMITS_RE = re.compile(r"across (?P<commits>\d+) commit\(s\)")
_TIMES = "\u00d7"  # MULTIPLICATION SIGN, as ship renders a churn ratio
_GE = "\u2265"  # GREATER-THAN OR EQUAL TO, ship's marker for a lower bound
_CHURN_RE = re.compile(
    rf"· churn (?:(?P<na>n/a)|{_GE}?(?P<ratio>\d+(?:\.\d+)?){_TIMES})"
    r" \((?P<touched>\d+) touched"
)
# Both spellings ship uses for a figure understated by a history rewrite: the
# ">=" form carries "lower bound", the n/a form carries only this phrase.
_LOWER_RE = re.compile(r"lower bound|history rewritten")

# The Conventional Commits type leading a PR title (`fix(dev): …` → `fix`).
_KIND_RE = re.compile(r"^(?P<kind>[a-z]+)")

# A round count more than this multiple of the median is called out as an
# outlier. Purely descriptive — nothing here blocks or gates (issue #146).
_OUTLIER_FACTOR = 2


@dataclass(frozen=True)
class Aggregate:
    """The review aggregate one ship comment reports for one merged change.

    Attributes:
        round: The terminal review round. Exact: a history rewrite drops churn
            history but not the count of recorded artifacts.
        net_lines: Net lines in the reviewed diff.
        commits: Commits the branch carries, or ``None`` on an artifact recorded
            before the field existed.
        churn_lines: Lines touched across all rounds, or ``None`` when ship
            rendered no churn clause at all.
        churn_ratio: Churn ÷ net. ``None`` means the loop reported ``n/a`` — a
            binary- or rename-only diff with no measurable text lines. That is
            *absent*, not zero, and must never be averaged as ``0.0``.
        churn_is_lower_bound: The figure was computed after a squash, amend or
            rebase, so it counts only the work still on the branch and
            understates the real churn by an unknown amount.
    """

    round: int
    net_lines: int
    commits: int | None
    churn_lines: int | None
    churn_ratio: float | None
    churn_is_lower_bound: bool


@dataclass(frozen=True)
class ShippedPr:
    """A merged pull request and the aggregate its ship comment reported.

    Attributes:
        number: The PR number.
        title: The PR title.
        aggregate: The terminal ship comment's aggregate, or ``None`` when the
            PR carries no ship comment (merged before the marker existed, or
            admin-merged without one). ``None`` is absent evidence, not a
            zero-round change, so it is excluded from every statistic.
    """

    number: int
    title: str
    aggregate: Aggregate | None

    @property
    def kind(self) -> str:
        """The Conventional Commits type from the title, or ``?`` if unparseable."""
        match = _KIND_RE.match(self.title)
        return match.group("kind") if match else "?"


def parse_summary(line: str) -> Aggregate | None:
    """Parse one ship summary line into an :class:`Aggregate`.

    Args:
        line: A single line from a ship comment body.

    Returns:
        The aggregate, or ``None`` if the line is not a summary line. A comment
        posted before the aggregate existed has none, which is why this can
        legitimately return ``None`` for a genuine ship comment.
    """
    head = _ROUND_RE.match(line)
    if head is None:
        return None
    commits = _COMMITS_RE.search(line)
    churn = _CHURN_RE.search(line)
    ratio: float | None = None
    touched: int | None = None
    if churn is not None:
        touched = int(churn.group("touched"))
        # `n/a` stays None: no measurable text lines means the ratio is absent.
        if churn.group("na") is None:
            ratio = float(churn.group("ratio"))
    return Aggregate(
        round=int(head.group("round")),
        net_lines=int(head.group("net")),
        commits=int(commits.group("commits")) if commits else None,
        churn_lines=touched,
        churn_ratio=ratio,
        churn_is_lower_bound=churn is not None and _LOWER_RE.search(line) is not None,
    )


def _is_ship_comment(body: str) -> bool:
    """Whether a comment body opens with ship's marker *and* its header.

    GitHub returns bodies with CRLF endings, so each line is stripped of its
    trailing carriage return before matching.
    """
    lines = [line.rstrip("\r") for line in body.split("\n")[:2]]
    return (
        len(lines) == 2  # noqa: PLR2004  # marker line + header line
        and _MARKER_RE.match(lines[0]) is not None
        and _HEADER_RE.match(lines[1]) is not None
    )


def aggregate_from_comments(bodies: list[str]) -> Aggregate | None:
    """Return the aggregate from a PR's *last* ship comment, if it has one.

    ship posts one comment per commit, so a PR that shipped more than once
    carries several. The last is the one covering the content that merged, so it
    is the one the history reports; earlier rounds on the same PR are already
    counted inside its round number.

    Args:
        bodies: Every comment body on the PR, in chronological order.

    Returns:
        The aggregate, or ``None`` when no ship comment carries a summary line.
    """
    for body in reversed(bodies):
        if not _is_ship_comment(body):
            continue
        for line in body.split("\n"):
            aggregate = parse_summary(line.rstrip("\r"))
            if aggregate is not None:
                return aggregate
    return None


def parse_pull_requests(payload: object) -> list[ShippedPr]:
    """Convert a ``gh pr list --json number,title,comments`` payload to records.

    Args:
        payload: The decoded JSON — a list of PR objects.

    Returns:
        One :class:`ShippedPr` per entry, in the order ``gh`` returned them.

    Raises:
        ValueError: If the payload is not the expected shape.
    """
    if not isinstance(payload, list):
        raise ValueError("expected a JSON list of pull requests")
    prs: list[ShippedPr] = []
    for entry in payload:
        if not isinstance(entry, dict):
            raise ValueError("expected each pull request to be a JSON object")
        comments = entry.get("comments") or []
        if not isinstance(comments, list):
            raise ValueError(f"PR {entry.get('number')}: 'comments' is not a list")
        bodies = [str(c.get("body", "")) for c in comments if isinstance(c, dict)]
        prs.append(
            ShippedPr(
                number=int(entry["number"]),
                title=str(entry.get("title", "")),
                aggregate=aggregate_from_comments(bodies),
            )
        )
    return prs


def fetch_pull_requests(limit: int) -> object:
    """Fetch the most recent merged PRs with their comments, via the ``gh`` CLI.

    This is the only network access in the module, and it is isolated here so
    the report itself can be exercised from a saved payload (``--from-json``).

    Args:
        limit: How many merged PRs to request.

    Returns:
        The decoded JSON payload.

    Raises:
        RuntimeError: If ``gh`` is missing, fails, or returns unparseable JSON.
    """
    argv = [
        "gh",
        "pr",
        "list",
        "--state",
        "merged",
        "--limit",
        str(limit),
        "--json",
        "number,title,comments",
    ]
    try:
        result = subprocess.run(  # noqa: S603  # fixed argv, no shell
            argv, capture_output=True, text=True, check=True
        )
    except FileNotFoundError as exc:
        raise RuntimeError("gh CLI not found on PATH — install it or pass --from-json") from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"`gh pr list` failed: {exc.stderr.strip()}") from exc
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"could not parse the `gh pr list` output as JSON: {exc}") from exc


def _format_number(value: float) -> str:
    """Render a median without a trailing ``.0`` on a whole number."""
    return f"{value:g}"


def _round_cell(aggregate: Aggregate) -> str:
    """Render the round count with its singular/plural noun."""
    return f"{aggregate.round} round" + ("" if aggregate.round == 1 else "s")


def _churn_cell(aggregate: Aggregate) -> str:
    """Render one PR's churn, preserving 'lower bound' and 'absent' as distinct.

    A lower bound keeps its bound marker; an ``n/a`` stays ``n/a``. Neither is rendered
    as a plain number, because a reader scanning the column has to be able to
    tell a measurement from a floor and from a missing value.
    """
    if aggregate.churn_ratio is None:
        return "n/a"
    prefix = _GE if aggregate.churn_is_lower_bound else ""
    return f"{prefix}{aggregate.churn_ratio:.1f}{_TIMES}"


@dataclass(frozen=True)
class _Stats:
    """The distribution over the PRs that carry a usable figure.

    Attributes:
        rounds: Every round count (exact for every ship comment).
        exact_churn: Churn ratios measured exactly — the only ones a median may
            be taken over.
        lower_bound: How many churn figures are understated by a rewrite.
        not_applicable: How many diffs had no measurable text lines.
        unshipped: How many merged PRs carry no ship comment at all.
    """

    rounds: list[int]
    exact_churn: list[float]
    lower_bound: int
    not_applicable: int
    unshipped: int


def summarize(prs: list[ShippedPr]) -> _Stats:
    """Split the PRs into the figures a median may use and the ones it may not."""
    rounds: list[int] = []
    exact: list[float] = []
    lower = na = unshipped = 0
    for pr in prs:
        agg = pr.aggregate
        if agg is None:
            unshipped += 1
            continue
        rounds.append(agg.round)
        if agg.churn_ratio is None:
            na += 1
        elif agg.churn_is_lower_bound:
            lower += 1
        else:
            exact.append(agg.churn_ratio)
    return _Stats(
        rounds=rounds,
        exact_churn=exact,
        lower_bound=lower,
        not_applicable=na,
        unshipped=unshipped,
    )


def _caveat_lines(stats: _Stats) -> list[str]:
    """The lines naming what was deliberately left out of the medians, and why."""
    lines: list[str] = []
    if stats.lower_bound:
        lines += [
            f"  {stats.lower_bound} churn figure(s) are lower bounds — history rewritten,",
            f"    earlier rounds not counted. Shown with {_GE}, and kept out of the",
            "    median, which they can only understate.",
        ]
    if stats.not_applicable:
        lines += [
            f"  {stats.not_applicable} diff(s) report churn n/a — binary- or rename-only,",
            f"    no measurable text lines. Absent, not zero, never counted as 0.0{_TIMES}.",
        ]
    if stats.unshipped:
        lines += [
            f"  {stats.unshipped} merged PR(s) carry no ship comment — merged before the",
            "    marker existed, or admin-merged without one. Absent evidence, not a",
            "    zero-round change, so excluded from both medians.",
        ]
    return lines


def _headline(prs: list[ShippedPr], stats: _Stats) -> list[str]:
    """The window line and the two medians it summarises."""
    shipped = len(stats.rounds)
    header = f"last {len(prs)} merged PR(s) — {shipped} with a ship comment"
    if not stats.rounds:
        return [header, "  no aggregate to report"]
    median_rounds = _format_number(statistics.median(stats.rounds))
    parts = [f"median {median_rounds} round(s) over {shipped} PR(s)"]
    if stats.exact_churn:
        median_churn = statistics.median(stats.exact_churn)
        parts.append(f"median churn {median_churn:.1f}{_TIMES} over {len(stats.exact_churn)} exact")
    else:
        parts.append("median churn n/a (no exact figure)")
    return [header, "  " + " · ".join(parts)]


def render(prs: list[ShippedPr]) -> str:
    """Build the full review-history report for the given pull requests."""
    stats = summarize(prs)
    lines = [
        "ai-assistant — review history",
        "(generated by `just review-history`; derived from the ship comments on",
        "merged PRs, which are the durable record — `.review/` is local and lossy)",
        "",
    ]
    lines += _headline(prs, stats)
    lines.append("")

    threshold = _OUTLIER_FACTOR * statistics.median(stats.rounds) if stats.rounds else float("inf")
    outliers = 0
    kind_width = max((len(p.kind) for p in prs), default=0)
    round_width = max((len(_round_cell(p.aggregate)) for p in prs if p.aggregate), default=0)
    churn_width = max((len(_churn_cell(p.aggregate)) for p in prs if p.aggregate), default=0)
    for pr in prs:
        cells = f"  #{pr.number:<5} {pr.kind.ljust(kind_width)}  "
        if pr.aggregate is None:
            lines.append(f"{cells}(no ship comment)")
            continue
        agg = pr.aggregate
        row = (
            f"{cells}{_round_cell(agg).rjust(round_width)}  "
            f"{_churn_cell(agg).rjust(churn_width)}  {agg.net_lines:>5} lines net"
        )
        if agg.round > threshold:
            outliers += 1
            row = f"{row}   <- outlier"
        lines.append(row)

    lines.append("")
    if stats.rounds:
        shipped = len(stats.rounds)
        lines.append(
            f"outliers (>{_OUTLIER_FACTOR}{_TIMES} median rounds): {outliers} of {shipped}"
        )
    caveats = _caveat_lines(stats)
    if caveats:
        lines += ["", "Not folded into the medians:", *caveats]
    lines += [
        "",
        "Descriptive only — nothing here gates a ship. Whether the distribution",
        "argues for the soft gate ADR-0020 §2 and ADR-0025 §3 each defer is a",
        "decision for those ADRs, not for this report (issue #146).",
    ]
    return "\n".join(lines)


def main() -> int:
    """Parse arguments, fetch (or load) the merged PRs, and print the report."""
    parser = argparse.ArgumentParser(
        description="Print the review aggregate across recently merged pull requests."
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="How many merged pull requests to report on (default: 20).",
    )
    parser.add_argument(
        "--from-json",
        type=Path,
        default=None,
        help=(
            "Read a saved `gh pr list --json number,title,comments` payload from this "
            "file instead of calling gh (used by the tests, and for offline runs)."
        ),
    )
    args = parser.parse_args()
    if args.limit < 1:
        print("review-history: --limit must be at least 1", file=sys.stderr)
        return 2
    try:
        if args.from_json is not None:
            payload = json.loads(args.from_json.read_text(encoding="utf-8"))
        else:
            payload = fetch_pull_requests(args.limit)
        prs = parse_pull_requests(payload)
    except (RuntimeError, ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"review-history: {exc}", file=sys.stderr)
        return 1
    print(render(prs))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
