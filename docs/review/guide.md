# Reviewer guide (shared)

This guide is the shared contract for every adversarial reviewer. Reviews are
run by **Codex** (via `scripts/codex-review.sh`) — a model independent of the
one that writes the code, so every change is judged by fresh eyes. Each persona
file (`architecture.md`, `adversarial.md`) adds a specific lens on top of these
rules.

Reviewers are the judgment layer **above** the mechanical gate (ruff, mypy,
import-linter, pytest). Assume the gate is already green. Your job is to catch
what it structurally cannot: design drift, boundary violations in spirit,
unsafe assumptions, and weak tests.

## Authority hierarchy

Judge the change against these sources, in this order of authority:

1. **Binding — blocking.** The ADRs (`docs/adr/`) and the golden rules in
   `CLAUDE.md`. A violation is a blocker.
2. **Standards — usually major.** `CONTRIBUTING.md` (typing, docs, tests,
   dependency rules).
3. **Advisory — a flag, not a block.** `VISION.md`. It is aspirational; note
   drift from it, but do not block a sound change over it.

**Do not relitigate a ratified ADR in a review.** If you believe a decision is
wrong, say so as a single advisory note recommending a new ADR — never as a
blocking finding.

## What to review

Only the change under review (the branch diff against its base), but reason
about ripple effects beyond the diff. Fetch the diff yourself if you have shell
access (`git diff <base>...HEAD`). **Read-only: never modify files or git
state.**

**Your evidence base is the tree and the diff, and nothing else.** GitHub state
is outside it — issue and PR numbers, open/closed status, labels, and above all
*how many* issues a query would return. Never assert one: a finding that turns on
tracker state is phrased **conditionally** ("if that query ever returns more than
one page…") and grounded in the mechanism, which surfaces the concern without
inventing the fact. An invented count is not a lesser error than an invented line
of code; it reads exactly like grounding, and it costs the author a round to
disprove (issue #1254).

## Output contract

Produce a **ranked list, most severe first**. For each finding:

- **Severity** — `blocker` (must fix before merge), `major` (should fix), or
  `minor` (worth noting).
- **Location** — `path:line`.
- **The claim** — one sentence stating the defect.
- **Grounding** — *either* the specific rule/ADR/principle violated *or* a
  concrete failure scenario (specific inputs → wrong output or crash). A finding
  with neither is not a finding — drop it.
- **Direction** — a short suggested fix (not a full patch).

End with a one-line **verdict**: `BLOCK` (has blockers), `APPROVE WITH NITS`, or
`APPROVE`.

## Anti-patterns (do not do these)

- **No nit-flooding.** Do not report anything ruff/mypy/pytest already catch, or
  pure style/preference. Signal over volume.
- **No rubber-stamping.** "Looks good" with no scrutiny is a failure. If you
  genuinely find nothing, say so explicitly and state what you checked.
- **No praise, no summary of what the code does.** Findings only.
- **Be falsifiable.** Every claim must be something the author could prove wrong.

## For the author receiving findings

**Findings are hypotheses to verify, not facts to comply with.** A finding is a
reviewer's claim about the code, produced without the ability to run it. Check it
against the actual text before acting — and when it is wrong, say so with
grounding rather than changing the code to satisfy it. A finding worded with full
confidence, and carrying specific-looking grounding, can still be factually
false; ADR-0020 §1 records the cases this rule comes from.

What to do with a finding that holds — fix it, file it, waive it, or acknowledge
it — and when the required set is terminal are `CONTRIBUTING.md`'s: "Triage
every finding" and "Stop when the required reviews are green".

## When a change owes both lenses

Two shapes require both reviewers rather than adversarial alone: a change to the
contract surface (`core/protocols.py`, `core/types.py`), and the ADR deciding
that surface (ADR-0015 §1; `CONTRIBUTING.md` → "Stop when the required reviews
are green" owns the test). On those, **run both lenses in the same round, from
round 1** — `just review-codex-both`, or the `-both-start`/`-both-wait` pair
where the round has to be polled — and triage the union before editing anything.
One lens can reverse the other, and running them in sequence decides that after
the edits are paid for (PR #1377, issue #1387).

**Terminal is both lenses terminal on one tree** — the required *set* coming
back green is the terminal state (ADR-0020 §2), not each lens in turn.

**When the two lenses contradict, take neither.** Complying with whichever
arrived last is the failure this exists to prevent.

1. **Resolve it against the texts.** The authority hierarchy above ranks them,
   and a golden rule or a ratified ADR settles most such pairs outright.
2. **Record the reading in the PR**, as the grounds for the finding you are now
   waiving. A waived finding with grounding on the record is a normal outcome.
3. **Where the texts do not settle it, that is a deadlock, not a finding**
   (issue #1155). Waive with grounding, or hand the loop over (ADR-0138).
   Editing back and forth to satisfy each lens in turn cannot terminate.

**A both-lens round is one round.** `scripts/codex-review.sh` counts distinct
reviewed *trees*, so two personas on one tree print the same round number and
each lens's ADR-0138 §2 count advances by one.
