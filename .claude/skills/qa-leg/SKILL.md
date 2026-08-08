---
name: qa-leg
description: Run the post-leg QA pass — drive a finished leg's ruled behaviors end-to-end through a live hub, before the operator rules its exit test. Use after a leg's last lane merges, when verifying a leg's mechanisms compose in the running system, or when opening the issue that records a QA run.
---

# qa-leg

Runs after a leg's last lane merges and **before the operator rules the exit
test**, so the ruling is made on composition evidence and not only on per-lane
green. This is a dev-process tool for building `ai-assistant` itself, not a
product feature.

## 1. What this pass owns, and what it does not

Everything per-PR has already run by the time a leg finishes — the gate, the
adversarial review, the conformance suites. Those own the *slices*. What none
of them can own is the **composition**: the seams where one lane's producer
meets another lane's machinery, in the real resident process, driven the way a
user or operator will drive it. That is this pass's whole jurisdiction.

The record supports the division: a leg's first QA run found a ruled mechanism
with **zero reachable producers** (every suite green, the behavior unreachable
end-to-end), and the lane fixing it then found that the obvious fix would have
shipped a duplicate-minting defect — both invisible from inside any single
lane, both caught only by driving the composed system.

So the highest-yield question, asked of every mechanism the leg ratified:

> **Does each ruled behavior have a reachable producer in the running system —
> not just a passing suite?**

A clause can be normative, implemented, conformance-tested, and still
unreachable, because the ADR that ruled it deferred the opt-in to a lane that
never fired. Nothing mechanical detects that; this pass exists to.

## 2. Build the charter from the rulings, not the diffs

Read the leg's ADRs and take the charter from their **normative clauses and the
leg's exit test** — what the system is ruled to do — never from what the PRs
happened to touch. For each ruled mechanism, plan to exercise:

- **The positive arm**: the behavior firing, end-to-end, through the hub's real
  API surface (wire client or CLI — the same door a user has).
- **The refusal arms**: what the rulings say must *not* happen — a clock that
  must never close, a job that must not be reachable, a path ruled withheld.
  Probe these adversarially: set the config that should not exist, name the
  method that should not dispatch. A withheld surface that can be tickled into
  acting is a finding even when no ordinary path reaches it.
- **The exit test, as a user**: the project's own standard is that a gap closes
  when a *user* can exercise the capability. Where the leg shipped an
  instrument, re-run it on demand and compare against the recorded numbers the
  ruling rested on — the shape matters, the absolute constants vary with the
  machine.

Where a leg ships no instrument, say so in the run's record — each leg should
leave one behind, and its absence is what makes the next leg's QA expensive.

## 3. Mechanics of a live-hub run

- **One tracking issue records the run**: the charter, then findings as they
  land, then a closing summary comment. The run is not a PR-shaped lane — it
  delivers issues and a record, never a diff, so it sits outside the
  one-lane-one-PR rule rather than bending it.
- **A scratch data directory at a short path.** The hub refuses a socket path
  over the platform `sun_path` budget (~108 bytes), which deep scratch paths
  exceed; use something like `~/.tmp/qa-<leg>`. Tear it down when the run
  closes.
- **Plant test stores with the production `HashingEmbedder`** and start the hub
  with `ASSISTANT_EMBEDDER=hashing`, so the planted store and the hub share an
  embedding space (the store pins `model_id` + dimensions and refuses a
  mismatch). Hashing similarity is lexical, not semantic — fine for mechanism
  QA, wrong for judging retrieval *quality*.
- **Reuse the leg's own harnesses** (fixtures, aging harnesses, instruments)
  rather than writing parallel ones; drivers that exist only for the run belong
  in the session scratchpad, not the tree.
- **Model-backed arms need a working credential.** The hub checks presence, not
  validity, at startup — a dead key surfaces as the first model call failing,
  which is itself worth one verification pass but blocks everything behind it.

## 4. Triage findings exactly like review findings

- A real defect becomes a **GitHub issue**, never a fix applied during the run
  — the run's value is a clean record of what the shipped system does.
- Distinguish the three verdicts explicitly in the record: **behaves as ruled**
  (cite the clause), **defect** (issue filed), and **ruled-but-unreachable**
  (issue filed naming which condition cannot fire and why — this is the class
  per-lane review cannot see, and it is not a defect in any lane's code).
- An environment fault (a bad credential, a path budget) is recorded but is not
  a finding against the leg.

## 5. Close out

Close the tracking issue with the summary: verdict per charter item, issues
filed, and what the run could not exercise and why. What the run found feeds
two places — fix lanes for defects, and the **operator's exit ruling** for the
leg, which is the reason this pass runs before that ruling rather than after.
