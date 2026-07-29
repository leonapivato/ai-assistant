---
name: pre-dispatch-survey
description: Establish current repository state before dispatching agent lanes — what has merged, what open PRs and issues already claim, and where the slices would collide — then record the batch as one GitHub issue. Use before briefing agents, when checking whether work is already claimed, or when opening the issue that tracks a batch of lanes.
---

# pre-dispatch-survey

Runs immediately before `dispatch-agents`. It establishes *state* — what is
merged, what is claimed, where lanes would collide — so the briefs are written
against reality. It does **not** decide what the work should be; see §2.

This is a dev-process tool for building `ai-assistant` itself, not a product
feature.

## 1. Survey a pinned `origin/main`

State on disk can be stale, and a plan computed from a stale tree proposes work
that is already done. Read the ref, not the checkout.

Resolve the ref to a commit **once**, then read everything from that commit.
`origin/main` is a moving target — a concurrent fetch between two `git show`
calls would mix a roadmap from one commit with protocols from another, and the
staleness check in §4 would compare against a third:

```bash
git fetch origin
surveyed="$(git rev-parse origin/main^{commit})"   # every read below uses this
git show "$surveyed:docs/roadmap.md"
git show "$surveyed:src/ai_assistant/core/protocols.py"
git show "$surveyed:src/ai_assistant/core/types.py"
git show "$surveyed:VISION.md"
```

For the derived picture — module counts per package, Protocol inventory, ADR
states — `project_status.py` reads a *checkout*, not a ref, so point it at a
disposable one rather than at wherever you happen to be standing:

```bash
tmp="$(mktemp -d)"
# Clean up on any exit path — a failure between add and remove would otherwise
# leave a worktree registered, and the two steps are independent so neither
# blocks the other.
trap 'git worktree remove --force "$tmp/survey" 2>/dev/null || true; rm -rf "$tmp"' EXIT
git worktree add --detach --quiet "$tmp/survey" "$surveyed"   # the same commit, not the ref
# Run the *surveyed* commit's own copy of the script, not the one on your
# branch: if origin/main changed how packages are classified, your branch's
# version would analyse the new tree with stale logic.
python3 "$tmp/survey/scripts/project_status.py" --root "$tmp/survey"
```

`--root` exists for exactly this — the script is stdlib-only and runnable bare,
so it needs no environment in the temporary checkout.

Then find what open work already claims:

```bash
gh pr list --state open --limit 200 --json number,title,headRefName,body
gh issue list --state open --limit 200 --json number,title,body
```

Set `--limit` on **both**: both default to 30, so work claimed by an older open
item silently falls off the page and reads as available.

**If either command returns exactly 200 results, stop** — the list was probably
truncated, and work claimed beyond it would read as unclaimed. Page through with
`gh api --paginate` instead, or raise the limit until the count comes back
short. A scan that might be incomplete cannot support "nothing already covers
this."

Read the **bodies**, not just the titles: a PR called "First vertical follow-up"
on a branch named `feature/next` can claim a subsystem in a checklist line and
be invisible to a title scan.

Open PRs and issues are where work-in-flight lives (ADR-0015). There is no
ledger file; do not look for one.

## 2. Scope comes from the roadmap, not from this skill

`docs/roadmap.md` states the legs **in order**, and says each one *"decomposes
into ADR-backed slices when it is dispatched, contract first."* The gap register
maps each `VISION.md` promise to the legs that close it, and "Parked" records
what was deliberately deferred and behind what.

So the scope question is already answered on disk, by the operator. This skill's
job is to say what state that plan meets, not to re-derive the plan. Two things
follow:

- **Read the surveyed roadmap and take the current leg from it.** Where the
  roadmap and the survey disagree — a leg's slice looks already built, or a
  parked item has an open PR — **name the discrepancy and stop** rather than
  resolving it yourself. That is an operator decision.
- **Do not encode a scope test here.** A previous revision of this skill gated
  candidates on the roadmap's then-current "first-vertical seven artifacts". The
  roadmap was reoriented to the accumulation legs and the gate silently admitted
  nothing. A living document carries rules, never snapshots of what the plan
  currently is (ADR-0019) — and a scope heuristic in a skill is exactly that
  snapshot, with the added cost that it looks authoritative while it rots.

## 3. Check the batch for collisions

Slices within a leg are not automatically independent. Before proposing a batch:

- **`core/protocols.py` and `core/types.py` are the high-collision surface.**
  One lane holds them at a time. Two lanes both touching `core/` are not
  independent — the second would build against a contract about to change.
  Either keep one `core/`-touching lane plus pure leaves, or explicitly sequence
  the second behind the first's contract PR. State which; never leave it
  implicit.
- **A new Protocol carries its triad** — Protocol, conformance suite, canonical
  fake plus the `Test…Contract` subclass — as one lane, after its ADR has merged
  (`CONTRIBUTING.md` → "Adding a Protocol"). Do not split it across lanes to
  make them look parallel.
- **Note for each slice** whether it needs `core/protocols.py`,
  `core/types.py`, or neither. A Protocol method can take or return a type that
  does not exist yet, and public data crossing a subsystem boundary must live in
  `core/types.py`.
- **The roadmap's leg order is a dependency order.** Slices from a later leg are
  not parallel work just because they touch different files.

## 4. Record the batch as one issue

One issue for the batch, not one per lane. It records what is being dispatched —
in-flight state belongs in the tracker (ADR-0015), not in a document.

- **Title** names the batch (e.g. "Leg 1 slices: profile ADR + inspection
  surface").
- **Why**: 2–3 sentences tying the batch to the roadmap leg and the `VISION.md`
  principle its exit test serves.
- **One checklist section per lane**, each with: what it delivers, a proposed
  `<area>/<slug>` branch name, and whether it touches `core/protocols.py`,
  `core/types.py`, or both.
- For a `core/`-touching lane, say that the contract ADR ships as its own PR and
  merges before the implementation (ADR-0015 §5, golden rule 5).
- **Out of scope**: what you excluded and why, so it is not re-litigated in
  comments.

**Do not assign ADR numbers here.** The operator assigns them at dispatch
(`dispatch-agents` §1); a number proposed in an issue that then sits open
recreates the stale-ledger problem ADR-0015 removed.

### Confirm before posting

`gh issue create` posts to shared state. Print the drafted body and get explicit
confirmation first — never auto-fire it.

State can go stale while confirmation is pending, and work that merged in the
meantime is exactly what this skill exists not to propose. Using `$surveyed` —
the commit every read actually came from — **immediately before**
`gh issue create`:

1. `git fetch origin` and compare against `$surveyed`. If it moved, redo §§1–3
   against the new commit — an issue rescan alone will not catch work that
   merged, since a merged lane leaves no open issue behind.
2. Re-run **both** scans from §1 — PRs *and* issues — regardless of whether the
   ref moved. An overlapping PR or issue can appear while `origin/main` stands
   still; an issues-only rescan misses the PR case entirely.
3. If either changed the draft, show the revised body and get confirmation
   again — never post a body that was not the one approved.

Both are courtesy checks, not reservations; merged and posted state is
authoritative, nothing before it.
