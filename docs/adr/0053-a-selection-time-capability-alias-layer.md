# 53. A selection-time capability alias layer

- Status: Accepted
- Date: 2026-07-24

## Context

ADR-0048 shipped the first local tools (`current_time` advertising capability
`report_current_time`, `recall_memory` advertising `recall_memory`) and wired
them into the composition root, so a planned step can now be selected, gated and
executed **when the plan names a tool's exact advertised capability**.

But `ModelBackedPlanner` (ADR-0047) emits capability strings from an **open**
vocabulary and is kept deliberately blind to the tool set (ADR-0014 §2, ADR-0016
§5). So whether the model, planning a real utterance, names the exact string a
tool advertises is not guaranteed: a plausible plan for "what time is it" may
name `get_time` or `tell_time`, `ToolRegistry.find` returns `[]`, and the step is
`SKIPPED`/`NO_CAPABLE_TOOL` (ADR-0037 §1). That outcome is legitimate and
detectable (ADR-0016 §5 reserved the `SkipReason` for it), not a bug — but it
means the wired tools may never fire from natural language, which is the gap
issue #296 exists to close.

Issue #296 records three options and decides none:

- **Publish the registry's vocabulary to the planner** — `Planner.plan` gains a
  capability list. This is a *planning-contract* change (golden rule 5, issue
  #60's territory) with a real downside: a planner constrained to the tools that
  exist today cannot express a goal the system should grow to meet.
- **A capability alias / normalisation layer** at selection time.
- **A shared naming convention** both sides are held to.

This ADR is **non-contract.** It adds no member to `core/protocols.py` or
`core/types.py`; the `Planner.plan` surface is untouched and the planner learns
nothing about the tool set. So it is Accepted on merge rather than ratified
contract-first (ADR-0015), and reviewed adversarial-only.

## Decision

We will add a **selection-time capability alias / normalisation layer** — the
second option — and keep it entirely inside the selection path.

A pure function `resolve_capability(emitted, advertised)` lives in
`orchestration/capability_alias.py`. `StepRunner.run` calls it immediately
before `ToolRegistry.find`, passing the step's capability and the registry's own
`capabilities()`. `find` is then called on the resolved name. Resolution is, in
order:

1. **Exact** — `emitted` is already an advertised capability: return it
   untouched.
2. **Surface variant** — `emitted` folds (case-fold, and every run of
   *non-alphanumeric* characters collapsed to a single `_`) onto exactly one
   advertised capability: return that advertised name. Folding is Unicode-aware
   (`str.isalnum`), so a letter in any script is preserved and only genuine
   separators fold — an ASCII-only rule would treat `é` as a separator and fold
   `deleteéaccount` onto `delete_account`. If two *distinct* advertised
   capabilities fold to the same key (`delete-user` and `delete_user`), the fold
   is ambiguous and this branch declines, because choosing one would be a ranking
   rule (ADR-0037 §1).
3. **Curated synonym** — `emitted` folds onto a key of a hand-maintained
   `CAPABILITY_ALIASES` table whose target **is currently advertised**: return
   the target. The table holds *retrieval/read* synonyms only — a write-intent
   like `remember` is deliberately absent, since ADR-0048 ships no memory writer
   and aliasing a store-intent onto the read-only `recall_memory` would be the
   wrong-tool hazard this layer exists to avoid.
4. **Unknown** — none of the above: return `emitted` unchanged.

The registry is the authority on the vocabulary (ADR-0016 §5): every rewrite
lands on a member of `advertised`, verified against the live set on each call.

**We deliberately do not take the contract option.** Publishing the vocabulary
to the planner is deferred to issue #60 / a future ADR, for the downside #296
names — it would constrain the planner to today's tools, foreclosing a goal the
system should grow to meet. The alias layer buys the natural-language win now
without touching the planning contract, and can be removed the day a better
contract lands.

### How this stays honest — an alias maps a synonym, it does not guess

The hazard of any normalisation is that it silently fires the *wrong* tool. Two
properties, both structural rather than disciplinary, prevent it:

- **A rewrite only ever resolves onto a capability the registry currently
  advertises.** Branches 2 and 3 check the target against `advertised` on every
  call, so a synonym can never rewrite a step onto a capability no tool serves.
  An alias entry whose target is not (yet) advertised is inert: the step falls
  through to branch 4 and is reported `NO_CAPABLE_TOOL`, exactly as if the alias
  did not exist.
- **An unrecognised capability is returned verbatim.** Resolution is total but
  conservative: anything that is not an exact advertised name, a case/separator
  variant of one, or an enumerated synonym is passed through unchanged, reaches
  `find` as the planner named it, and yields `NO_CAPABLE_TOOL` honestly. Nothing
  is invented.

`CAPABILITY_ALIASES` is a table of **deliberate** synonyms authored against the
shipped tools, not a similarity or fuzzy-match heuristic. Surface folding
(case, separators) never changes which *word* was named — `get-time` and
`GET_TIME` fold to `get_time`, they do not reach across to a different name — so
it cannot turn one capability into another. Adding a tool with a new vocabulary
means adding entries here; it never teaches the layer to guess.

Aliasing does not weaken the single-candidate rule (ADR-0037 §1): it changes
*which* capability is looked up, never *how many* candidates a lookup may pick
from. If the resolved capability is advertised by two tools, the runner still
declines to choose and leaves the step `PENDING`.

## Consequences

- **Natural-language requests now reach the wired tools.** A plan naming
  `get_time` selects and runs `current_time`; a plan naming `search_memory`
  selects `recall_memory`. The end-to-end pipeline fires from utterances the
  planner phrases in its own words, which is what #296 asked for.
- **The planning contract is untouched.** `Planner.plan` is unchanged, the
  planner stays blind to the tool set (ADR-0014 §2), and the layer can be
  deleted wholesale if a future ADR publishes the vocabulary to the planner
  instead. This is a self-contained selection-path concern.
- **The alias table is maintenance the tool set imposes.** Every new tool with a
  vocabulary a planner might phrase differently wants entries here, and the table
  lives in `orchestration/` while the tools live in `tools/` — a coupling that is
  acceptable at two tools and would not scale to a large catalogue. That is a
  further argument for the deferred contract option, not against this one: the
  layer is explicitly the interim bridge.
- **No composition wiring.** The runner already holds the registry; resolution
  is a pure function over its `capabilities()`, so nothing in `app/composition.py`
  changes and no collaborator is injected.
- **What would trigger revisiting this.** The contract option landing (#60), or
  the table growing past the point where a curated map is honest — at which point
  a shared naming convention (#296's third option) or the published vocabulary
  supersedes it.

Refs: ADR-0048, ADR-0047, ADR-0016 §5, ADR-0014 §2, ADR-0037 §1, #296, #60
