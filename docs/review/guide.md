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

*Operator note, not a rule for the reviewer: the read-only sandbox has one
switch. `CODEX_REVIEW_NO_SANDBOX=1` — and `GITHUB_ACTIONS` exactly `true`, which
`scripts/codex-review.sh` treats the same way — runs Codex under
`--dangerously-bypass-approvals-and-sandbox`: no sandbox at all, so the whole
filesystem and the network are reachable, no session is kept, and the read-only
proof of ADR-0025 §4 is skipped. It is there for CI-like environments where
bubblewrap cannot set up its network namespace; do not set it for an ordinary
local review.*

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
grounding rather than changing the code to satisfy it.

A finding worded with full confidence, and carrying specific-looking grounding,
can still be factually false — complying with one makes the code worse on the
strength of a confident sentence. ADR-0020 §1 records the cases this rule comes
from.

**Every review the change requires coming back green is a terminal state, not a
checkpoint.** That is adversarial alone for most changes, and adversarial *and*
architecture for a contract-surface one (ADR-0015 §1). When the required set is
green, ship. Do not treat it as a base to improve on: a further commit destroys
those records and starts a fresh round, and a *good* commit does this exactly as
thoroughly as a bad one. ADR-0020 §2 records the evidence.

Waiving a `blocker` or `major` is allowed; write the one-line rationale in the PR
or the commit. `CONTRIBUTING.md` covers triaging a finding that is real but
belongs in its own issue.

*Operator note, not a rule for the reviewer: a round runs for minutes, and a
caller that cannot hold one process open that long starts it and polls it instead
— `just review-codex-start <persona>`, then `just review-codex-wait <persona>`
until it exits 0 with the artifact path and verdict. Exit 3 is `still running`
(ask again, nothing is lost); exit 4 is no round in flight for HEAD's tree. It is
the same round as the foreground form — same locks, same artifact, same
acceptance — started detached rather than reimplemented (issue #1594).*

*Two further operator notes, both bought by lanes that lost time to them. A
`--start` that returns non-zero without confirming is **not** a statement that
the round is dead — it cannot see that; it is saying only that no claim arrived
in the grace, and a round renders the whole diff and computes the patch identity
before it claims. Ask `--wait`, which can tell the two apart, and never relaunch
(issues #1670, #1674). And when `--wait` answers exit 4 about a round that failed,
read the log it prints: `codex exec --json` puts its failures on **stdout**, so
until issue #1674 that log ended at "Running Codex …" with nothing after it and
the reason was discarded unread.*

*One more, for an ADR lane. Where `HEAD` is the one-line ratification flip, a
round reviews and records `HEAD`'s **parent** — the content `ship` judges
coverage over under ADR-0165 §3 — and says so on stderr as it starts. A round
recorded against the flip's own tree could not satisfy `ship` at all, which is
issue #1672.*

## When a change owes both lenses

Two shapes require both reviewers rather than adversarial alone: a change to the
contract surface (`core/protocols.py`, `core/types.py`), and the ADR deciding
that surface (ADR-0015 §1; `CONTRIBUTING.md` → "Stop when the required reviews
are green" owns the test). On those, **run both lenses in the same round, from
round 1** — `just review-codex-both`, or the `-both-start`/`-both-wait` pair
where the round has to be polled — and triage the union before editing anything.

**The reason is that one lens can reverse the other, and running them in
sequence decides that after the edits are paid for.** On PR #1377 (ADR-0178)
architecture returned `APPROVE` with no findings at rounds 2–3 and did not run
again while adversarial worked rounds 8–9: a blocker there called a browser
rendering requirement unsatisfiable and directed a *cross-language derivation
contract the browser may implement*, and the next round required that contract's
full field schema. When architecture next ran, at rounds 10–11, it returned a
blocker on exactly that result — recomputing the canonical destination set in the
browser is "business logic in `interfaces/`, violating golden rule 3" — and
directed the opposite: `core` derives the set, surfaces only render it. That
reading is the one the ADR shipped with. Both lenses on round 8's tree would have
put the contradiction in front of the author before the first edit, instead of
after three rounds of them.

**Terminal is both verdicts green on one tree**, which is what the rule above
already says: the required *set* coming back green is the terminal state
(ADR-0020 §2), not each lens in turn. Nothing about shipping changes — what
changes is that the set is measured every round rather than once at the end.

**When the two lenses contradict, take neither.** Complying with whichever
arrived last is the failure this exists to prevent.

1. **Resolve it against the texts.** The authority hierarchy above ranks them,
   and a golden rule or a ratified ADR settles most such pairs outright — golden
   rule 3 settled #1377's.
2. **Record the reading in the PR**, as the grounds for the finding you are now
   waiving. Both lenses are advisory; a waived finding with grounding on the
   record is a normal outcome.
3. **Where the texts do not settle it, that is a deadlock, not a finding** —
   issue #1155's case. Nothing puts your counter-evidence in front of a lens, so
   the moves are to waive with grounding, or to hand the loop over (ADR-0138).
   Editing back and forth to satisfy each lens in turn is the one move that
   cannot terminate.

**A both-lens round is one round.** `scripts/codex-review.sh` counts distinct
reviewed *trees* of the branch, so two personas on one tree print the same round
number and ADR-0138 §2's per-lens counts each advance by one. Running both does
not spend the handoff threshold twice as fast.
