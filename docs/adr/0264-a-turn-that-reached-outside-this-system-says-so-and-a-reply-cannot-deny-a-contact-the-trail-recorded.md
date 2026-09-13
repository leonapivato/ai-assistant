# 264. A turn that reached outside this system says so, and a reply cannot deny a contact the trail recorded

- Status: Proposed
- Date: 2026-09-13

## Context

### Where this comes from

Issue [#2268](https://github.com/leonapivato/ai-assistant/issues/2268), raised by
the milestone 31 QA re-run, drive C2: *"Turn 2 fired a search to the configured
provider … the composed reply told the user 'nothing was searched just now.'"*
The issue states the asymmetry that produced it:

> ADR-0242 §6/§8 make a turn say a search did not happen, with a typed statement,
> when a servicing yielded nothing. There is no counterpart for the inverse: a
> servicing that succeeded contributes records to the supply, and whether the reply
> acknowledges it is left to the model's prose. So a reply can deny an outbound call
> that the trail records.

and names what is owed:

> whether a turn that dispatched an outbound call owes a typed, surface-rendered
> statement that it did — the mirror of ADR-0242 §6 — so the trail and the reply
> cannot disagree about whether the world was contacted.

The owner's 2026-09-13 note lists *contradictory reporting* among milestone 31's
remaining failures. This decision closes that one.

### The tree, read rather than assumed, at `origin/main` `05656952`

- **The negative half is built and the positive half is not.** `TurnOutcome`
  carries `search_not_serviced` (ADR-0242 §9), `orchestration.composing` holds
  `_SEARCH_NOT_SERVICED_PROMPTS` — one fixed fragment per member — and
  `interfaces.cli._render_search_not_serviced` renders one fixed statement per
  member beside the reply. Nothing anywhere carries the fact that a lookup **was**
  made.
- **The records arrive indistinguishable from stored ones.** A serviced
  `WEB_SEARCH` puts `MemoryRecord`s into the turn's supply, which reach the
  composing stage as `turn.memories` — the same shape a relevance read produces.
  The model is not told which of them arrived this turn from outside, and there is
  no field in which it could be.
- **The plan block actively invites the denial.** `orchestration.composing`'s
  `_render_plan` closes a decline with *"Nothing: the planner named no capability
  for this turn, so no action was taken"*. The line that scopes that statement,
  `_PLAN_IS_ABOUT_ACTING` — *"nothing above says whether a lookup was made"* —
  is appended **only** where `search_unserviced` is true (#2213). On a turn whose
  search succeeded it is not appended at all, so the plan block reads as an account
  of the whole turn and says no action was taken. That is the sentence #2268
  observed coming back.
- **The servicing site already holds the fact.** `orchestration.reads.ServicedRead`
  carries `kinds`, `supplied` and `disposition` per servicing, and
  `SearchDisposition` is a closed seventeen-member vocabulary naming *the stage
  that produced the outcome*. `SearchRefusal.NO_RESULT` is deliberately not among
  them, because a search that reached the provider and yielded nothing is a
  completed servicing.
- **The egress side holds its own.** `orchestration.runner` builds the
  `ActionRequest` the policy rules on and sets `egress_binding` from what
  `EgressBinder.bind` returned, so a step whose call carried a binding is known
  inside `orchestration` at the time the step is driven. `tools/send_email.py` is
  a live egress tool.
- `TurnOutcome` carries fifteen members today; five of them were added by later
  ADRs as `None`-defaulting widenings.

### The gap this closes, stated exactly

ADR-0242 §6 makes eligibility *"the disposition's presence and nothing else"*, and
its second clause states the consequence in terms: *"A turn on which every
servicing yielded records carries **no** `SearchNotServiced` member."* That is
correct for what §6 decides and is precisely the hole: on the successful turn the
system says nothing, has no field in which to say anything, and hands the model a
plan block that accounts for acting alone. The user is then told whatever the
model infers — and #2268 records it inferring the opposite of the truth.

### What this ADR is not allowed to settle

- **ADR-0242 §6's not-serviced statement.** Every clause of §§6-9 binds entire and
  none is narrowed, widened or re-read here.
- **The browser's rendering arrears.** Issue #2237 records that the browser renders
  none of ADR-0242 §9's statements. That is its own lane and this decision neither
  closes it nor competes with it (§9).
- **What the model writes.** No clause here inspects, classifies or corrects a
  composed reply.
