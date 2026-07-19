---
name: find-parallel-work
description: Survey the roadmap, WORKING.md, and core/protocols.py to find independent subsystem slices ready for parallel agents, then draft a GitHub tracking issue for them. Use when asked to find, plan, or scope parallel work for multiple agents, or to open an issue coordinating that work.
---

# find-parallel-work

Produces one GitHub tracking issue that lays out a batch of independent,
non-colliding work slices — sized so each one maps to a single
`just claim-workspace <area>/<slug>` and a single agent. This is a
dev-process tool for building `ai-assistant` itself, not a feature of the
product. It **proposes** a batch; it never claims workspaces, edits
`WORKING.md`, or spawns agents itself — a human reviews the issue and decides
what to hand out.

## 1. Gather ground truth — don't hand-roll it

Run `git fetch origin` first and note `origin/master`'s resolved commit
(`git rev-parse origin/master`) — step 4 needs it later to tell whether
anything has changed since this survey. Then read these, in this order, and
trust them over any stale assumption:

- `just status` — the derived picture: module counts per package, the current
  `core/protocols.py` Protocol inventory, and ADR states. This is the
  canonical source for "what's actually built" — never guess it.
- `WORKING.md` — the *human-declared* picture: lane ownership and ADR numbers
  currently in flight. Any subsystem with a named owner, or any ADR number
  claimed against it that isn't yet `Accepted`, is off the table for this
  batch.
- `docs/roadmap.md` — the "first vertical" seven-artifact table and the build
  sequence checklist. A candidate lane must map to an unchecked item there;
  don't propose work the roadmap hasn't sequenced yet.
- `VISION.md` — pull the specific principle/section that justifies each lane,
  so the issue reads as "why this, now" rather than a bare task list.

## 2. Compute candidates

A subsystem is a valid candidate for this batch only if **all** of:

1. It's `_unclaimed_` in `WORKING.md` (no owner, no in-flight ADR against it).
2. `just status` shows it as not-yet-built (module count is "contract only"
   or clearly behind the others).
3. It maps to one of the roadmap's **first-vertical seven artifacts**
   (`UserProfile`, `Memory`, `CurrentContext`, `Goal`, `ToolDefinition`,
   `ActionPlan`, `FeedbackEvent`) — not merely to *any* unchecked
   build-sequence item, and not to the wider per-subsystem candidate-artifact
   table. The build-sequence checklist tells you which of the seven are
   still unbuilt; an unchecked item that isn't one of the seven (e.g.
   `permissions`' `ActionPolicy`) fails this rule and belongs in "Out of
   scope" as second-wave, not in the batch.

For each candidate, check whether it has entries in **both**
`core/protocols.py` and `core/types.py` yet. A subsystem can be missing
either independently — a new Protocol method can take/return a pydantic
model that doesn't exist yet, and CLAUDE.md requires any public data crossing
a subsystem boundary to live in `core/types.py`, not just the Protocol
signature. If either is missing, flag it explicitly: that's the shared
surface CONTRIBUTING.md calls out as highest-collision — two lanes both
proposing a `core/` addition the same day is exactly the scenario "push the
contract first, say so in the PR title" exists to defuse. Don't silently
omit this risk from the issue; state it as an instruction to whoever picks up
the lane, and name which of the two files (or both) is involved.

**Cross-check the batch, not just each lane in isolation.** If two or more
selected candidates would each need to touch `core/protocols.py` or
`core/types.py`, they are not actually independent — "push the contract
first" only defuses the collision for one of them; the second is now building
against a contract file that's about to change out from under it. Don't
present both as start-now-in-parallel. Either drop the batch to one `core/`
touching lane plus everything that's a pure leaf (no `core/` change needed),
or explicitly sequence the second to stack on the first once the first's
contract commit is pushed. The picker of the second lane must `git fetch
origin` first and stack on `origin/<first-lane-branch>`, not the bare branch
name — the first lane's contract commit exists on a teammate's push, not
necessarily as a local ref on the second picker's machine, and
`claim-workspace` resolves whatever base string it's given without fetching
for you (`just claim-workspace <area>/<slug> origin/<first-lane-branch>`).
State which of the two this batch is doing, don't leave it implicit.

## 3. Draft the issue

One issue, not one per lane — matches `WORKING.md`'s own lightweight-ledger
style. Structure:

- **Title**: short, names the batch (e.g. "Parallel work: planning + tools
  contracts").
- **Why**: 2-3 sentences linking the specific `VISION.md` principle and
  `docs/roadmap.md` line this batch advances.
**Pre-assign ADR numbers for the whole batch before writing any lane's
checklist item** — don't let each lane compute its own number independently,
even a stacked/sequenced one, or two `core/`-touching lanes in the same batch
can both land on the same number. Read `WORKING.md`'s "Highest merged ADR"
line and its "ADR numbers in flight" table once, take one past the higher of
the two as the batch's starting number, then hand out consecutive numbers —
first, second, third — to every `core/`-touching lane in the batch in the
order they're sequenced (the one starting now gets the first number; each
stacked lane after it gets the next). It is still provisional, the same as
any ADR number is (`CONTRIBUTING.md` — "provisional until merge"): unrelated
concurrent work *outside* this batch can still land one of these numbers
first, in which case the standard "second to merge renumbers" process
applies, unchanged.

- **One checklist section per lane**, each with:
  - Subsystem name and the roadmap artifact(s) it delivers.
  - Proposed `area/slug` for `just claim-workspace`.
  - Whether it touches `core/protocols.py`, `core/types.py`, or both. If so,
    write this lane's number from the batch-level assignment above into its
    checklist item (e.g. "touches `core/`: claim ADR-0014") — don't leave the
    picker to compute it independently later. The coordination instruction:
    **first**
    `just claim-workspace <area>/<slug>` (CLAUDE.md — claiming a workspace is
    the first action of any task, before editing anything, `WORKING.md`
    included); **then**, from inside that workspace, register the lane and
    the pre-assigned ADR number in `WORKING.md`; **then draft the ADR and
    get it through architecture review and ratified before implementing
    against the new contract** (golden rule 5 — claiming the number reserves
    it, it is not ratification); only once ratified, push the contract
    commit ahead of the dependent implementation and flag it in the PR
    title, so a concurrent lane sees the new shape before building against
    the old one.
  - A reminder that registering the lane in `WORKING.md` (per the ordering
    above) is the picker's job on pickup — this skill does not do that
    itself.
- **Out of scope**: name anything that looked tempting but got excluded in
  step 2 and why (already owned, not in the first vertical, etc.) so the
  issue doesn't get re-litigated in comments.

## 4. Confirm before posting

`gh issue create` is the one externally-visible action here — it posts to
shared GitHub state other people see. Print the drafted body and get
explicit confirmation before running it. Never auto-fire this step.

Also run `gh issue list --state open --limit 200 --json title,body,url` first
— the bare command only returns titles; without `--json body` a match hiding
in an issue's body text (a generic title, the lane named only in a checklist
line) is invisible — and scan both the titles and bodies of the result for an
existing tracking issue already proposing one or more of the same lanes —
two runs of this skill (by different people, or the same person re-running
it) can otherwise both observe the same unclaimed lane and each post a
duplicate issue, since nothing about `WORKING.md` reserves a lane just by
being read. If a match exists, don't create a new issue for the overlapping
lane(s) — point back to the existing one instead (in the batch's "Out of
scope" section, or by not posting at all if the whole batch overlaps). This
is a best-effort check, not an atomic reservation — same limitation as the
`WORKING.md` freshness check below, for the same reason: closing it fully
would need a real lane-reservation mechanism, out of scope for a proposal
tool.

State can go stale between step 1 and this one — not just `WORKING.md`
ownership, but *any* input the candidates were computed from: a lane's
roadmap item can get checked off, its `src/ai_assistant/core/protocols.py` or
`src/ai_assistant/core/types.py` entry can land, or its module count in
`just status` can move, all while the draft sits waiting for confirmation.
`just status` and a plain file read only ever reflect the *current checkout*
— they are not ref-aware, so re-running them in place still reports the old
state if you're standing on a branch cut before these changes landed, not
`origin/master` as of right now.

Immediately before creating the issue, run `git fetch origin` and check
whether `origin/master`'s commit has moved at all since step 1
(`git rev-parse origin/master`, compared against the SHA noted then). If it
hasn't, nothing could have changed — skip the rest of this. If it has, redo
step 1 and step 2 **against that new commit**, not the current checkout:
materialize it in a disposable worktree (`git worktree add --detach
<tmp-path> origin/master`) and rerun `just status` and the candidate checks
there, then remove it (`git worktree remove <tmp-path>`) once done. Drop or
re-flag any lane whose candidacy changed, rather than posting a batch that
includes work someone already picked up or finished. This closes the gap for
anything already merged to `master`; work only pushed to someone else's
still-open feature branch is outside what any of these sources guarantee at
any point — merged state is authoritative, not before (same reason
`CONTRIBUTING.md`'s "stay in your lane" check is best-effort, not atomic, for
two people claiming at once). If this recheck changes the lane list or any
checklist content from what was already shown, **re-print the revised draft
and get confirmation again** — never post a body different from the one
actually approved.
