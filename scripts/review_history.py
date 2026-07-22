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
  and excluded from both medians. A PR that *does* carry a ship comment whose
  summary line is not an aggregate is a **different** absence and is reported as
  its own case, because the first explanation would be false for it (issue
  #155). Its own cause — ordinarily an artifact predating ADR-0020 §2 — is
  offered as the likely one rather than asserted, since an edited summary is
  indistinguishable from here.

One further observation is recorded but deliberately *not* excluded: a PR whose
ship marker names a commit other than the PR's head (``headRefOid``, issue
#161). It is reported as exactly that and nothing more. The head, deliberately,
not the merge commit: GitHub's squash and rebase merges mint a new commit by
construction, so comparing that would flag every such PR and observe nothing. And
a differing head is *not* evidence that unreviewed work merged either — ADR-0020
§3 lets an amend, squash, rebase or revert keep its review where the reviewed
tree and base are unchanged, and every one of those produces a new commit ID.
Deciding between that and a genuinely unshipped commit needs the trees, which
this report does not read. Either way the loop the row reports happened, so the
row stays in both medians — this measures review loops, not merge coverage.

This reports; it does not gate. Whether the evidence argues for a soft gate is
ADR-0020's and ADR-0025's call to make, not this script's (issue #146, "out of
scope").

Run via ``just review-history`` (or ``python3 scripts/review_history.py``). Pass
``--limit`` for a different window, or ``--from-json`` to read a saved
``gh pr list --json number,title,comments,mergedAt,headRefOid`` payload instead
of calling ``gh`` —
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
_MARKER_RE = re.compile(r"^<!-- ship:(?P<sha>[0-9a-fA-F]{7,40}) -->$")
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

# A full Git object ID, which is what `gh` returns for `headRefOid`. Required
# before the head is compared against a ship marker: anything shorter or
# non-hexadecimal cannot support even the narrow observation that the two differ.
_FULL_SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")

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
        aggregate: The terminal ship comment's aggregate, or ``None`` when there
            is none to report. ``None`` is absent evidence, not a zero-round
            change, so it is excluded from every statistic. Read together with
            ``has_ship_comment``, which says *which* absence it is.
        has_ship_comment: A genuine ship comment from the trusted author was
            found. With ``aggregate is None`` this is the second absence: the
            marker and header are there but the summary line does not parse.
            Ordinarily that means an artifact predating ADR-0020 §2, which
            carries no ``round=`` field — but an edited or truncated summary is
            indistinguishable, so nothing here asserts which. Explaining it as
            "no ship comment" would be false either way (issue #155).
        comments_may_be_truncated: The fetched comment list filled a whole page,
            so GitHub may be holding more — including, possibly, this PR's last
            ship comment. Only ever set for a payload this script did not page
            itself; the live fetch pages the comments (issue #157).
        head_differs_from_marker: The last ship comment's marker names a commit
            other than the PR's head commit (``headRefOid`` — the branch head,
            not the merge commit, which a squash or rebase merge always mints
            anew). Only that: an amend or rebase onto the same tree keeps its
            review under ADR-0020 §3 and produces a new head too, so this is not
            evidence of unreviewed content. An observation, never an exclusion:
            the loop this row reports happened either way (issue #161).
        merged_at: The ISO-8601 merge timestamp, which sorts lexicographically.
            Empty when the payload carries none, in which case the caller's order
            is preserved.
    """

    number: int
    title: str
    aggregate: Aggregate | None
    has_ship_comment: bool = False
    comments_may_be_truncated: bool = False
    head_differs_from_marker: bool = False
    merged_at: str = ""

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
# does not paginate it. A live run completes any PR at that boundary through the
# REST endpoint (see `fetch_comments`), so this count is no longer a truncation
# there. It still is for a saved payload, whose provenance this script cannot
# know, so the check is kept and the affected PRs are named rather than quietly
# reported from a stale aggregate (see `render`).
# Where ship writes the aggregate: marker, header, blank, summary.
_SUMMARY_LINE = 3

# How much of a body is worth carrying: everything through the summary line, and
# nothing after it. `fetch_comments` trims to this in its jq filter, so a PR full
# of long review comments costs the comment count rather than their total length.
_BODY_LINES = _SUMMARY_LINE + 1

_COMMENT_PAGE = 100

# Extra merged PRs fetched beyond the reported window, so ordering them by merge
# time (see by_merge_time) has something to reorder. `gh pr list` sorts by
# creation, so a PR opened well before the window but merged inside it is only
# recoverable if it was fetched at all.
_ORDER_SLACK = 30


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


@dataclass(frozen=True)
class ShipRecord:
    """What a PR's *last* ship comment records — including its own absence.

    Attributes:
        found: A genuine ship comment from the trusted author was found at all.
            This is what separates "no ship comment" from "a ship comment with
            no aggregate": both leave ``aggregate`` at ``None``, and the report
            must not explain the second as the first (issue #155).
        aggregate: The aggregate that comment carried, or ``None`` when its
            summary line did not parse as one. Why it did not is not knowable
            here — an artifact predating ADR-0020 §2 and an edited summary look
            the same — so this records only that it did not.
        marker_sha: The commit named by the comment's ``<!-- ship:<sha> -->``
            marker — the head that was reviewed — or ``""`` when no ship comment
            was found.
    """

    found: bool
    aggregate: Aggregate | None
    marker_sha: str = ""


def last_ship_record(comments: list[Comment], ship_author: str) -> ShipRecord:
    """Return what a PR's *last* ship comment records, and whether it has one.

    ship posts one comment per commit, so a PR that shipped more than once
    carries several. The last is the one covering the content that merged, so it
    is the one the history reports; earlier rounds on the same PR are already
    counted inside its round number.

    Args:
        comments: Every comment on the PR, in chronological order.
        ship_author: The login whose ship comments count.

    Returns:
        A :class:`ShipRecord`. ``found=False`` means no ship comment from
        ``ship_author`` at all; ``found=True`` with ``aggregate=None`` means one
        was found but carries no summary line.
    """
    for comment in reversed(comments):
        if not _is_ship_comment(comment, ship_author):
            continue
        marker = _MARKER_RE.match(comment.body.split("\n")[0].rstrip("\r"))
        # _is_ship_comment matched this same line, so the marker is present;
        # the guard is for mypy, not for a case that can occur.
        sha = marker.group("sha") if marker else ""
        # The last ship comment is the terminal record, so the search stops
        # here whether or not it carries a summary. ship omits the summary for
        # an artifact predating ADR-0020 §2; falling through to an earlier
        # comment would then report a SUPERSEDED round as this PR's terminal
        # one — a wrong number, which is worse than the absence. The absence is
        # returned as `found=True, aggregate=None`, which is what lets the report
        # explain it as itself rather than as "no ship comment".
        #
        # Only the fixed position is read, never the whole body. ship writes
        # marker, header, blank, summary — so the summary is line 3 and nothing
        # else is one. The rest of the comment is the reviewer's own prose and
        # fenced code, which nothing constrains: a review that happened to quote
        # or discuss a summary-shaped line would otherwise be read as this PR's
        # aggregate and report fabricated figures.
        lines = comment.body.split("\n")
        if len(lines) <= _SUMMARY_LINE:
            return ShipRecord(found=True, aggregate=None, marker_sha=sha)
        return ShipRecord(
            found=True,
            aggregate=parse_summary(lines[_SUMMARY_LINE].rstrip("\r")),
            marker_sha=sha,
        )
    return ShipRecord(found=False, aggregate=None)


def aggregate_from_comments(comments: list[Comment], ship_author: str) -> Aggregate | None:
    """Return the aggregate from a PR's last ship comment, if it carries one.

    A thin view over :func:`last_ship_record` for callers that only need the
    figures. It cannot tell the two absences apart — use ``last_ship_record``
    when that distinction matters.

    Args:
        comments: Every comment on the PR, in chronological order.
        ship_author: The login whose ship comments count.

    Returns:
        The aggregate, or ``None`` when there is none to report.
    """
    return last_ship_record(comments, ship_author).aggregate


def parse_pull_requests(
    payload: object, ship_author: str, *, comments_complete: bool = False
) -> list[ShippedPr]:
    """Convert a ``gh pr list --json number,title,comments,mergedAt,headRefOid`` payload.

    Args:
        payload: The decoded JSON — a list of PR objects.
        ship_author: The login whose ship comments count.
        comments_complete: Every entry's ``comments`` array is the whole list,
            because the caller paged it (see :func:`fetch_pull_requests`). A
            full page then means a PR with exactly that many comments, not a
            truncated read, so the truncation warning is not raised. Left
            ``False`` for a saved payload, whose provenance this cannot know.

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
    return [_pull_request(entry, ship_author, complete=comments_complete) for entry in payload]


def _pull_request(entry: object, ship_author: str, *, complete: bool) -> ShippedPr:
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
    # Every member is validated rather than filtered. Skipping a non-object would
    # report a hand-edited payload as a PR with fewer comments than it claims —
    # and in a mixed list could hide the very ship comment being looked for —
    # while parse_pull_requests documents that a malformed payload raises
    # (issue #158). The index is named because that is what locates the fault.
    comments = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"PR {number}: comment at index {index} is not a JSON object")
        comments.append(_comment(item))
    record = last_ship_record(comments, ship_author)
    return ShippedPr(
        number=number,
        title=str(entry.get("title", "")),
        aggregate=record.aggregate,
        has_ship_comment=record.found,
        comments_may_be_truncated=not complete and len(raw) >= _COMMENT_PAGE,
        head_differs_from_marker=_head_differs_from_marker(
            record, str(entry.get("headRefOid") or "")
        ),
        merged_at=str(entry.get("mergedAt") or ""),
    )


def _head_differs_from_marker(record: ShipRecord, head: str) -> bool:
    """Whether the PR's head commit is not the one the last ship comment named.

    This answers only that question. It is deliberately *not* named for what a
    difference might mean: ADR-0020 §3 keeps a review valid across an amend,
    squash, rebase or revert that leaves the reviewed tree and base unchanged,
    and all of those change the commit ID. Reading a mismatch as "unreviewed work
    merged" would therefore be an inference the data does not carry, and settling
    it needs the two trees, which this report does not fetch.

    The head must be a full object ID to be compared at all. ``gh`` returns
    ``headRefOid`` as one, so anything else is a payload that cannot support even
    the narrow observation — reporting a difference on the strength of ``"1"``
    not matching a SHA would be a fabricated one.

    The comparison is case-insensitive and one-directional. Only the *marker* may
    be abbreviated — ``ship.sh`` writes the full SHA, but the marker pattern
    admits 7 characters — so a marker that prefixes the head is the same commit,
    while a head that prefixes the marker cannot arise from a full head.

    Args:
        record: The PR's last ship record.
        head: The PR's ``headRefOid`` — the branch head, which is what the ship
            marker names and so the only thing it can be compared against. Not
            the merge commit: a squash or rebase merge mints a new one for every
            PR, so that comparison would differ always and observe nothing.
            Absent, or anything that is not a full object ID, means nothing can
            be concluded and this is ``False``.
    """
    if not record.marker_sha or _FULL_SHA_RE.match(head) is None:
        return False
    return not head.lower().startswith(record.marker_sha.lower())


def _comment(raw: dict[str, object]) -> Comment:
    """Build a :class:`Comment` from one entry of ``gh``'s ``comments`` array."""
    author = raw.get("author")
    login = author.get("login", "") if isinstance(author, dict) else ""
    return Comment(body=str(raw.get("body", "")), author=str(login))


def by_merge_time(prs: list[ShippedPr], limit: int) -> list[ShippedPr]:
    """Return the ``limit`` most recently merged pull requests, newest first.

    ``gh pr list`` orders by *creation*, not by merge, so slicing its output
    would report the most recently opened merged PRs — a different set, and not
    the one the report claims. A PR opened long ago and merged yesterday belongs
    in the window; one opened yesterday and merged last week may not.

    Reordering can only work over what was fetched, which is why
    :func:`fetch_pull_requests` asks for a pool larger than ``limit``. A PR
    whose creation rank falls outside that pool is still missed; the pool bounds
    how far that can reach, and the ordering is at least the documented one.

    Args:
        prs: The parsed pull requests, in whatever order they arrived.
        limit: How many to keep.

    Returns:
        The newest ``limit`` by merge time. Entries carrying no timestamp keep
        their relative order (the sort is stable), so a payload without
        ``mergedAt`` — a saved fixture — is passed through unshuffled.
    """
    return sorted(prs, key=lambda pr: pr.merged_at, reverse=True)[:limit]


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


def fetch_comments(number: int) -> list[dict[str, object]]:
    """Fetch every comment on one PR, paging properly, via the REST endpoint.

    ``gh pr list --json comments`` reads the nested GraphQL connection one page
    at a time and does not page it, so a PR sitting on the boundary can be
    missing its *last* ship comment — the one this report reads. The REST
    endpoint pages correctly under ``--paginate``, and is what ``ship.sh``
    already uses for the same lookup.

    The REST field names differ from the GraphQL ones — ``user.login``, not
    ``author.login`` — so the ``jq`` filter renames as it goes and returns the
    shape the rest of this module already parses. It also makes the output one
    compact JSON object per line, which is unambiguous to read back however
    ``gh`` chooses to join its pages.

    Bodies are truncated to their first ``_BODY_LINES`` lines in the filter, for
    the reason ``ship.sh`` gives at the same endpoint: whole bodies are megabytes
    on a long-running PR, and nothing here reads past the summary. Everything the
    parser looks at — marker, header, blank, summary — is in that prefix, so the
    trim is invisible to it and the retained data is bounded by the comment count
    rather than by how much anyone wrote.

    Args:
        number: The pull request number.

    Returns:
        Every comment, oldest first, as ``{"body": ..., "author": {"login": ...}}``,
        each body trimmed to its opening lines.

    Raises:
        RuntimeError: If ``gh`` is missing, fails, or returns unparseable JSON.
    """
    stdout = _gh(
        [
            "gh",
            "api",
            "--paginate",
            f"repos/{{owner}}/{{repo}}/issues/{number}/comments",
            "--jq",
            f'.[] | {{body: ((.body // "") | split("\\n")[0:{_BODY_LINES}] | join("\\n")),'
            ' author: {login: (.user.login // "")}}',
        ]
    )
    comments: list[dict[str, object]] = []
    for line in stdout.splitlines():
        if not line.strip():
            continue
        try:
            comments.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"PR {number}: could not parse a fetched comment: {exc}") from exc
    return comments


def _repage_comments(payload: object) -> object:
    """Refetch the comments of any PR whose list came back at the page boundary.

    Only the boundary entries cost an extra call: below it, ``gh`` returned the
    whole connection already and there is nothing to complete (issue #157).

    A malformed entry is passed through untouched — :func:`parse_pull_requests`
    is where a payload is validated, and it reports the fault with context.
    """
    if not isinstance(payload, list):
        return payload
    for entry in payload:
        if not isinstance(entry, dict):
            continue
        comments = entry.get("comments")
        if not isinstance(comments, list) or len(comments) < _COMMENT_PAGE:
            continue
        try:
            number = int(entry["number"])
        except KeyError, TypeError, ValueError:
            continue
        entry["comments"] = fetch_comments(number)
    return payload


def fetch_pull_requests(limit: int) -> object:
    """Fetch the most recent merged PRs with their comments, via the ``gh`` CLI.

    This is the only network access in the module, and it is isolated here so
    the report itself can be exercised from a saved payload (``--from-json``).

    Comments are completed by :func:`_repage_comments` for any PR at the page
    boundary, so the payload this returns carries every comment — which is why
    the caller may parse it with ``comments_complete=True``.

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
        str(limit + _ORDER_SLACK),
        "--json",
        # `comments` carries the author login as well as the body; both are
        # needed, because a ship comment counts only from the account that could
        # have run ship (see _is_ship_comment). `mergedAt` is what the window is
        # actually defined by — see by_merge_time. `headRefOid` is the PR's head
        # commit, checked against the ship marker (see _head_differs_from_marker).
        "number,title,comments,mergedAt,headRefOid",
    ]
    stdout = _gh(argv)
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"could not parse the `gh pr list` output as JSON: {exc}") from exc
    return _repage_comments(payload)


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
        # Two different absences. `n/a` is a measurement ship made and could not
        # express as a ratio (no measurable text lines), and it carries a
        # touched-line count. No churn clause at all is an artifact that recorded
        # no churn fields — nothing was measured. Rendering both as `n/a` would
        # claim a binary- or rename-only diff for a change that may have been
        # neither.
        return "n/a" if aggregate.churn_lines is not None else "-"
    prefix = _GE if aggregate.churn_is_lower_bound else ""
    return f"{prefix}{aggregate.churn_ratio:.1f}{_TIMES}"


@dataclass(frozen=True)
class _Stats:
    """The distribution over the PRs that carry a usable figure.

    Attributes:
        rounds: Every round count (exact for every ship comment).
        exact_churn: Churn ratios measured exactly — the only ones a median may
            be taken over.
        lower_bound: How many measurable churn ratios are understated by a
            rewrite.
        not_applicable: How many diffs ship measured as ``n/a`` — binary- or
            rename-only, no measurable text lines.
        no_churn_clause: How many aggregates carried no churn clause at all, so
            nothing was measured. Distinct from ``n/a``: one is a measurement
            with no expressible ratio, the other is no measurement.
        rewritten_not_applicable: How many of those ``n/a`` diffs ALSO had their
            history rewritten, so even the touched-line count behind them is a
            floor. Tracked separately because a rewrite and an absent ratio are
            independent facts, and folding one into the other would drop it.
        unshipped: How many merged PRs carry no ship comment at all.
        no_aggregate: How many carry a ship comment whose summary line does not
            parse as an aggregate. Distinct from ``unshipped``: the review record
            exists, only the figures are missing, so the "merged without a
            review" explanation is false for these (issue #155).
        head_differs_from_marker: How many rows carry a head commit the last ship
            comment does not name — the bare fact, carrying no claim about what
            merged (see :func:`_head_differs_from_marker`). Counted, never
            subtracted: these PRs are in ``rounds`` like any other, because the
            loop happened (issue #161).
    """

    rounds: list[int]
    exact_churn: list[float]
    lower_bound: int
    not_applicable: int
    rewritten_not_applicable: int
    no_churn_clause: int
    unshipped: int
    no_aggregate: int
    head_differs_from_marker: int


def summarize(prs: list[ShippedPr]) -> _Stats:
    """Split the PRs into the figures a median may use and the ones it may not."""
    rounds: list[int] = []
    exact: list[float] = []
    lower = na = na_rewritten = no_clause = unshipped = no_aggregate = past = 0
    for pr in prs:
        past += int(pr.head_differs_from_marker)
        agg = pr.aggregate
        if agg is None:
            # Two absences, kept apart: a ship comment with no summary line is
            # not a PR that merged without a review (issue #155).
            if pr.has_ship_comment:
                no_aggregate += 1
            else:
                unshipped += 1
            continue
        rounds.append(agg.round)
        if agg.churn_ratio is None and agg.churn_lines is None:
            no_clause += 1
        elif agg.churn_ratio is None:
            na += 1
            # An absent ratio and a rewritten history are independent facts. A
            # diff can be both, and counting it only as `n/a` would silently drop
            # the caveat ship itself states separately for exactly this case.
            na_rewritten += int(agg.churn_is_lower_bound)
        elif agg.churn_is_lower_bound:
            lower += 1
        else:
            exact.append(agg.churn_ratio)
    return _Stats(
        rounds=rounds,
        exact_churn=exact,
        lower_bound=lower,
        not_applicable=na,
        rewritten_not_applicable=na_rewritten,
        no_churn_clause=no_clause,
        unshipped=unshipped,
        no_aggregate=no_aggregate,
        head_differs_from_marker=past,
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
        if stats.rewritten_not_applicable:
            # The row keeps a bare `n/a` rather than gaining a bound marker, for
            # the reason ship.sh gives: `n/a` is not a ratio, so it takes neither
            # the ">=" nor the multiplication sign. The rewrite is stated on its
            # own instead — dropping it would be the flattening this report
            # exists to avoid.
            lines.append(
                f"    {stats.rewritten_not_applicable} of those also had history rewritten, "
                "so even the touched-line count is a floor."
            )
    if stats.no_churn_clause:
        lines += [
            f"  {stats.no_churn_clause} aggregate(s) carry no churn clause at all — an",
            "    artifact recorded before churn was measured. Shown as `-`: nothing was",
            "    measured, which is not the same as ship measuring n/a.",
        ]
    if stats.unshipped:
        lines += [
            f"  {stats.unshipped} merged PR(s) carry no ship comment — merged before the",
            "    marker existed, or admin-merged without one. Absent evidence, not a",
            "    zero-round change, so excluded from both medians.",
        ]
    if stats.no_aggregate:
        # Deliberately not folded into the line above. That one explains the
        # absence as a PR that merged without a review record; here the record is
        # present and only the figures are missing, so borrowing that explanation
        # would state something false about a correctly-excluded PR.
        #
        # And the cause of *this* absence is stated as the likely one, not as
        # fact. An artifact predating ADR-0020 §2 is the ordinary reason a ship
        # comment carries no summary, but an edited or truncated one is
        # indistinguishable from here — asserting the benign provenance would be
        # the same over-claim one level down.
        lines += [
            f"  {stats.no_aggregate} merged PR(s) carry a ship comment whose summary line is",
            "    not an aggregate. A review was recorded — the marker and header are",
            "    there — but its figures are not readable, so these are excluded from",
            "    both medians as missing figures, not as unreviewed changes. Ordinarily",
            "    an artifact predating ADR-0020 §2, which records no round; an edited or",
            "    truncated summary reads the same from here, so neither is asserted.",
        ]
    return lines


def _headline(prs: list[ShippedPr], stats: _Stats) -> list[str]:
    """The window line and the two medians it summarises."""
    shipped = len(stats.rounds)
    # "with an aggregate", not "with a ship comment": a ship comment carrying no
    # summary line is counted in neither the rounds nor this figure, and calling
    # the count something it is not is the flattening issue #155 is about.
    header = f"last {len(prs)} merged PR(s) — {shipped} with a review aggregate"
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


def _warning_lines(
    prs: list[ShippedPr],
    *,
    pool_saturated: bool,
    undated: list[int] | None,
) -> list[str]:
    """The ``!`` blocks: what the report cannot prove, and what it observed.

    Each names the PRs it applies to rather than stating a bound in the
    abstract, because a reader can only discount a row they can identify.

    Args:
        prs: The window being reported.
        pool_saturated: See :func:`render`.
        undated: See :func:`render`.
    """
    lines: list[str] = []
    # Ordering can only reorder what was fetched, and `gh pr list` orders by
    # creation. GitHub offers no server-side merge-time ordering to ask for
    # instead, so the pool is the bound and the report says so rather than
    # claiming a window it cannot prove.
    if pool_saturated:
        lines += [
            "",
            "! the pool this window was ordered within was full, so a PR created",
            "  further back but merged inside the window may never have been",
            f"  fetched (live: {_ORDER_SLACK} beyond --limit; from a saved payload:",
            "  whatever it was captured with, which this cannot know). Raise",
            "  --limit to widen it.",
        ]
    if undated is None:
        undated = [pr.number for pr in prs if not pr.merged_at]
    if undated:
        listed = ", ".join(f"#{n}" for n in undated)
        lines += [
            "",
            f"! no merge time on {listed}, so those could not be ordered by merge",
            "  time and sorted below everything dated — some may have been cut from",
            "  the window on that basis alone (a payload captured without",
            "  `mergedAt`).",
        ]
    # A PR whose comment list filled a page may be missing its LAST ship comment,
    # which is the one reported — so the figure above it could be a stale round.
    # A live run pages the comments itself, so this can only fire on a saved
    # payload; it is named rather than silently trusted (issue #157).
    truncated = [pr.number for pr in prs if pr.comments_may_be_truncated]
    if truncated:
        listed = ", ".join(f"#{n}" for n in truncated)
        lines += [
            "",
            f"! comment list may be truncated on {listed} — the saved payload holds a",
            f"  full page ({_COMMENT_PAGE}) and `gh pr list` does not page the nested",
            "  connection, so the last ship comment may be missing and the row above",
            "  may report an earlier round — which the medians above then include.",
            "  Not excluded: the page may well hold the terminal comment, and",
            "  dropping a probably-correct figure is its own distortion. A live run",
            "  pages these itself and never reaches this line.",
        ]
    differing = [pr.number for pr in prs if pr.head_differs_from_marker]
    if differing:
        listed = ", ".join(f"#{n}" for n in differing)
        lines += [
            "",
            f"! ship marker names a commit other than the PR head on {listed}. That",
            "  is the whole observation. `headRefOid` is the branch head, not the merge",
            "  commit — a squash or rebase merge mints a new one every time, so that",
            "  would flag everything and observe nothing. Nor does a differing head say",
            "  unreviewed work merged: ADR-0020 §3 keeps a review valid across an",
            "  amend, squash, rebase or revert that leaves the reviewed tree and base",
            "  unchanged, and each of those changes the commit ID too. Telling that",
            "  apart from a commit that was never shipped needs the trees, which this",
            "  does not read. Marked, never excluded: the loop each row reports",
            "  happened either way, and this measures review loops, not merge coverage.",
        ]
    return lines


def render(
    prs: list[ShippedPr],
    *,
    pool_saturated: bool = False,
    undated: list[int] | None = None,
) -> str:
    """Build the full review-history report for the given pull requests.

    Args:
        prs: The window to report, already ordered and sliced.
        pool_saturated: The fetch returned every PR it asked for, so ordering by
            merge time could only order what was fetched — an older PR merged
            inside the window may not have been fetched at all. Stated in the
            report rather than assumed away.
        undated: PR numbers carrying no merge time, taken from the whole
            candidate pool rather than the window. An undated PR sorts to the
            bottom and so is the one most likely to have been *sliced out* — a
            warning drawn from the window alone would go quiet in exactly the
            case it exists to report. Defaults to those visible in ``prs``.
    """
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
        agg = pr.aggregate
        if agg is None:
            # The two absences read differently, because they mean different
            # things about the change (issue #155).
            row = cells + (
                "(ship comment, no aggregate)" if pr.has_ship_comment else "(no ship comment)"
            )
        else:
            row = (
                f"{cells}{_round_cell(agg).rjust(round_width)}  "
                f"{_churn_cell(agg).rjust(churn_width)}  {agg.net_lines:>5} lines net"
            )
            if agg.round > threshold:
                outliers += 1
                row = f"{row}   <- outlier"
        if pr.head_differs_from_marker:
            # The bare fact, not a verdict on it — see _head_differs_from_marker.
            # Marked on the row, and still counted in every median above it: the
            # loop this row reports happened either way (issue #161).
            row = f"{row}   <- head differs from ship marker"
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
    lines += _warning_lines(prs, pool_saturated=pool_saturated, undated=undated)
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
            "Read a saved `gh pr list --json number,title,comments,mergedAt,headRefOid` "
            "payload from this "
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
        # Only the live path knows its comments are whole — fetch_pull_requests
        # pages them. A saved payload carries no record of how it was captured,
        # so it keeps the truncation check.
        parsed = parse_pull_requests(
            payload, args.ship_author, comments_complete=args.from_json is None
        )
        # Saturation is what makes the window unprovable, so it is measured
        # against what was asked for rather than assumed.
        # Live: the pool is known, so saturation is measurable. From a saved
        # payload it is not — the capture's own limit is not recorded — so any
        # payload big enough to be sliced is reported as a bound this cannot
        # verify, rather than as a window it cannot prove.
        saturated = (
            len(parsed) >= args.limit + _ORDER_SLACK
            if args.from_json is None
            # `>=`, not `>`: a payload holding exactly the window may be a
            # capture that was itself capped at that size, and nothing in the
            # payload distinguishes the two. Equality is the boundary where the
            # claim stops being provable, so it is where the caveat starts.
            else len(parsed) >= args.limit
        )
        prs = by_merge_time(parsed, args.limit)
        # Drawn from the pool, not the window: an undated PR sorts last, so it is
        # the one most likely to have been sliced away, and reporting only what
        # survived would hide precisely that.
        undated = [pr.number for pr in parsed if not pr.merged_at]
    except (RuntimeError, ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"review-history: {exc}", file=sys.stderr)
        return 1
    print(render(prs, pool_saturated=saturated, undated=undated))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
