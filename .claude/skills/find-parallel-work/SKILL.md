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

## 1. Gather ground truth — don't hand-roll it, and don't trust the checkout

`just status` and a plain file read both reflect whatever is currently
checked out — they are not ref-aware. Running this skill from any branch
other than an up-to-the-second `origin/master` (a workspace claimed an hour
ago, the main checkout before its next fetch, anything) means these can
silently report stale state even right after a `git fetch`, since fetch only
updates the remote-tracking ref, not what's on disk. So never read them from
"wherever this happens to be run" — always survey a disposable, freshly
fetched `origin/master` on its own:

1. `git fetch origin`.
2. Materialize it at a freshly generated, unique path — `tmp_path="$(mktemp
   -u)"` then `git worktree add --detach "$tmp_path" origin/master` — never a
   fixed literal path, so two runs of this skill (or a rerun after a failed
   one) can't collide on the same worktree.
3. Note the commit it resolved to (`git rev-parse origin/master`) — step 4
   needs it later to tell whether anything has changed since this survey.
   Remove the worktree (`git worktree remove "$tmp_path"`) if anything from
   here through step 4 fails partway — don't leave it registered.
4. From `<tmp-path>`, read these, in this order, and trust them over any
   stale assumption:
   - `just status` — the derived picture: module counts per package, the
     current `core/protocols.py` Protocol inventory, and ADR states. This is
     the canonical source for "what's actually built" — never guess it.
   - `WORKING.md` — the *human-declared* picture: lane ownership and ADR
     numbers currently in flight. Any subsystem with a named owner, or any
     ADR number claimed against it that isn't yet `Accepted`, is off the
     table for this batch.
   - `docs/roadmap.md` — the "first vertical" seven-artifact table and the
     build sequence checklist. A candidate lane must map to an unchecked item
     there; don't propose work the roadmap hasn't sequenced yet.
   - `VISION.md` — pull the specific principle/section that justifies each
     lane, so the issue reads as "why this, now" rather than a bare task
     list.
5. Remove the worktree (`git worktree remove <tmp-path>`) once the survey is
   read — steps 2-4 don't need it kept around.

## 2. Compute candidates

A subsystem is a valid candidate for this batch only if **all** of:

1. It's `_unclaimed_` in `WORKING.md` (no owner, no in-flight ADR against it).
2. It maps to one of the roadmap's **first-vertical seven artifacts**
   (`UserProfile`, `Memory`, `CurrentContext`, `Goal`, `ToolDefinition`,
   `ActionPlan`, `FeedbackEvent`) — not merely to *any* unchecked
   build-sequence item, and not to the wider per-subsystem candidate-artifact
   table. The build-sequence checklist tells you which of the seven are
   still unbuilt; an unchecked item that isn't one of the seven (e.g.
   `permissions`' `ActionPolicy`) fails this rule and belongs in "Out of
   scope" as second-wave, not in the batch. **This is the authoritative
   signal for "still needs building," not rule 3 below.**
3. `just status`'s module count is consistent with rule 2 — "contract only"
   or clearly behind the others, matching the roadmap's unchecked state.
   `scripts/project_status.py` itself calls this count "a rough progress
   proxy," not a completion test: a subsystem can be genuinely built with
   few, dense modules, and the roadmap checkbox is what actually says so. If
   the module count *disagrees* with the roadmap checklist — the checklist
   says unbuilt but the count looks substantial, or vice versa — don't
   silently trust either one: drop that lane from the batch and name the
   discrepancy in "Out of scope" instead of guessing which source is right.

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

State can go stale between step 1 and this one — a lane's roadmap item can
get checked off, its `core/` entry can land, its `WORKING.md` ownership can
change, or its module count can move, all while the draft sits waiting for
confirmation. Immediately before creating the issue, `git fetch origin` and
compare `origin/master`'s commit against the one noted in step 1. If it
hasn't moved, nothing could have changed — skip the rest of this. If it has,
redo step 1's survey (steps 1-5 there: fetch, fresh detached worktree at the
new commit, read, remove the worktree) and step 2's candidate computation
against that new commit. Drop or re-flag any lane whose candidacy changed in
any way, rather than posting a batch that includes work someone already
picked up or finished. This closes the gap for anything already merged to
`master`; work only pushed to someone else's still-open feature branch is
outside what any of these sources guarantee at any point — merged state is
authoritative, not before (same reason `CONTRIBUTING.md`'s "stay in your
lane" check is best-effort, not atomic, for two people claiming at once). If
this recheck changes the lane list or any checklist content from what was
already shown, **re-print the revised draft and get confirmation again** —
never post a body different from the one actually approved.
