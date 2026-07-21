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
which is the seam the tests drive, so they never touch the network. ``--limit``
applies to either path, so both report the same window.

A ship comment counts only from the account that could have run ship — by
default the authenticated ``gh`` login, which is the identity ``ship.sh`` checks
its own comment against. The ``<!-- ship:<sha> -->`` marker is public text any
commenter can quote, and the *last* ship comment on a PR is the one reported, so
an unchecked marker would hand any commenter control of the figure.
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
        comments_may_be_truncated: The fetched comment list filled a whole page,
            so GitHub may be holding more — including, possibly, this PR's last
            ship comment. Reported rather than ignored (issue #157).
    """

    number: int
    title: str
    aggregate: Aggregate | None
    comments_may_be_truncated: bool = False

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


@dataclass(frozen=True)
class Comment:
    """One PR comment: its body and who wrote it.

    Attributes:
        body: The raw comment body, CRLF endings included.
        author: The commenter's login.
    """

    body: str
    author: str


# GitHub returns a nested comments connection one page at a time, and `gh pr list`
# does not paginate it. A PR sitting exactly on the boundary may therefore be
# missing its *last* ship comment — which is the one this report reads — so the
# count is checked and the affected PRs are named rather than quietly reported
# from a stale aggregate (see `render`). Issue #157 tracks paginating properly.
_COMMENT_PAGE = 100


def _is_ship_comment(comment: Comment, ship_author: str) -> bool:
    """Whether a comment is a genuine ship comment from the trusted ship author.

    ``ship.sh`` recognises its own comment by marker + header + *author*, because
    the ``<!-- ship:<sha> -->`` marker is public text any commenter can quote.
    The same three conditions are required here, and the author is an exact login
    rather than a GitHub association: ``COLLABORATOR`` and ``MEMBER`` describe a
    relationship to the repository, not write access, so a read-only collaborator
    carries them too. Since the *last* ship comment on a PR is the one reported, a
    looser test would hand such an account control of the figure outright.

    This does not make the record tamper-proof and does not try to: as ship.sh
    already notes, a byte-identical forgery from the ship account itself is
    indistinguishable. What it closes is every author who is not that account.

    GitHub returns bodies with CRLF endings, so each line is stripped of its
    trailing carriage return before matching.

    Args:
        comment: The comment to test.
        ship_author: The login whose ship comments count.
    """
    if comment.author != ship_author:
        return False
    lines = [line.rstrip("\r") for line in comment.body.split("\n")[:2]]
    return (
        len(lines) == 2  # noqa: PLR2004  # marker line + header line
        and _MARKER_RE.match(lines[0]) is not None
        and _HEADER_RE.match(lines[1]) is not None
    )


def aggregate_from_comments(comments: list[Comment], ship_author: str) -> Aggregate | None:
    """Return the aggregate from a PR's *last* ship comment, if it has one.

    ship posts one comment per commit, so a PR that shipped more than once
    carries several. The last is the one covering the content that merged, so it
    is the one the history reports; earlier rounds on the same PR are already
    counted inside its round number.

    Args:
        comments: Every comment on the PR, in chronological order.
        ship_author: The login whose ship comments count.

    Returns:
        The aggregate, or ``None`` when no ship comment from ``ship_author``
        carries a summary line.
    """
    for comment in reversed(comments):
        if not _is_ship_comment(comment, ship_author):
            continue
        for line in comment.body.split("\n"):
            aggregate = parse_summary(line.rstrip("\r"))
            if aggregate is not None:
                return aggregate
    return None


def parse_pull_requests(payload: object, ship_author: str) -> list[ShippedPr]:
    """Convert a ``gh pr list --json number,title,comments`` payload to records.

    Args:
        payload: The decoded JSON — a list of PR objects.
        ship_author: The login whose ship comments count.

    Returns:
        One :class:`ShippedPr` per entry, in the order ``gh`` returned them.

    Raises:
        ValueError: If the payload is not the expected shape. Every malformed
            input arrives this way — a missing or non-numeric ``number``
            included — so the caller has one exception to handle rather than a
            traceback from whichever access happened to fail first.
    """
    if not isinstance(payload, list):
        raise ValueError("expected a JSON list of pull requests")
    return [_pull_request(entry, ship_author) for entry in payload]


def _pull_request(entry: object, ship_author: str) -> ShippedPr:
    """Build one :class:`ShippedPr`, raising ``ValueError`` on any bad field."""
    if not isinstance(entry, dict):
        raise ValueError("expected each pull request to be a JSON object")
    if "number" not in entry:
        raise ValueError("a pull request entry has no 'number'")
    try:
        number = int(entry["number"])
    except (TypeError, ValueError) as exc:
        raise ValueError(f"pull request 'number' is not an integer: {entry['number']!r}") from exc
    # `is None` rather than falsy: an absent or null `comments` is legitimately
    # "no comments", but any other non-list value is a malformed payload and must
    # not be silently read as an empty one.
    raw = entry.get("comments")
    if raw is None:
        raw = []
    if not isinstance(raw, list):
        raise ValueError(f"PR {number}: 'comments' is not a list")
    comments = [_comment(c) for c in raw if isinstance(c, dict)]
    return ShippedPr(
        number=number,
        title=str(entry.get("title", "")),
        aggregate=aggregate_from_comments(comments, ship_author),
        comments_may_be_truncated=len(raw) >= _COMMENT_PAGE,
    )


def _comment(raw: dict[str, object]) -> Comment:
    """Build a :class:`Comment` from one entry of ``gh``'s ``comments`` array."""
    author = raw.get("author")
    login = author.get("login", "") if isinstance(author, dict) else ""
    return Comment(body=str(raw.get("body", "")), author=str(login))


def authenticated_login() -> str:
    """Return the GitHub login ``gh`` is authenticated as.

    This is the identity ``ship.sh`` checks its own comment against, so it is the
    identity whose ship comments this report counts by default.

    Raises:
        RuntimeError: If ``gh`` is missing or the call fails.
    """
    return _gh(["gh", "api", "user", "--jq", ".login"]).strip()


def _gh(argv: list[str]) -> str:
    """Run a ``gh`` command and return its stdout.

    Raises:
        RuntimeError: If ``gh`` is missing or exits non-zero.
    """
    try:
        result = subprocess.run(  # noqa: S603  # fixed argv, no shell
            argv, capture_output=True, text=True, check=True
        )
    except FileNotFoundError as exc:
        raise RuntimeError("gh CLI not found on PATH — install it or pass --from-json") from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"`{' '.join(argv[:3])}` failed: {exc.stderr.strip()}") from exc
    return result.stdout


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
        # `comments` carries the author login as well as the body; both are
        # needed, because a ship comment counts only from the account that could
        # have run ship (see _is_ship_comment).
        "number,title,comments",
    ]
    stdout = _gh(argv)
    try:
        return json.loads(stdout)
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
    # A PR whose comment list filled a page may be missing its LAST ship comment,
    # which is the one reported — so the figure above it could be a stale round.
    # Named rather than silently trusted (issue #157).
    truncated = [pr.number for pr in prs if pr.comments_may_be_truncated]
    if truncated:
        listed = ", ".join(f"#{n}" for n in truncated)
        lines += [
            "",
            f"! comment list may be truncated on {listed} — GitHub returned a full",
            f"  page ({_COMMENT_PAGE}) and `gh pr list` does not page the nested",
            "  connection, so the last ship comment may be missing and the row above",
            "  may report an earlier round (issue #157).",
        ]
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
            "file instead of calling gh (used by the tests, and for offline runs). "
            "--limit still applies, so the window is the same either way."
        ),
    )
    parser.add_argument(
        "--ship-author",
        default=None,
        help=(
            "The login whose ship comments count. Defaults to the authenticated "
            "GitHub account — the same identity ship.sh checks its own comment "
            "against. Required with --from-json, which cannot resolve it offline."
        ),
    )
    args = parser.parse_args()
    if args.limit < 1:
        print("review-history: --limit must be at least 1", file=sys.stderr)
        return 2
    try:
        if args.from_json is not None:
            if args.ship_author is None:
                print(
                    "review-history: --from-json needs --ship-author (the login whose "
                    "ship comments count); it cannot be resolved without calling gh",
                    file=sys.stderr,
                )
                return 2
            payload = json.loads(args.from_json.read_text(encoding="utf-8"))
        else:
            payload = fetch_pull_requests(args.limit)
            args.ship_author = args.ship_author or authenticated_login()
        # Applied to both paths, not only the fetch. `gh` already honours
        # --limit, but a saved payload holds whatever it was captured with, and a
        # flag that silently does nothing on one path would report a different
        # window than the one asked for.
        prs = parse_pull_requests(payload, args.ship_author)[: args.limit]
    except (RuntimeError, ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"review-history: {exc}", file=sys.stderr)
        return 1
    print(render(prs))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
