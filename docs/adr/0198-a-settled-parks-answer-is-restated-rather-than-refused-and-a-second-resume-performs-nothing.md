# 198. A settled park's answer is restated rather than refused, and a second resume performs nothing

- Status: Proposed
- Date: 2026-08-27
- **Partially supersedes:**
  [ADR-0042](0042-the-interface-adapter-contract.md) — §4's rule that
  `ActionPolicy.resolve` "is what turns `approved` into an `ALLOW` or `DENY`
  ruling, and only `approved=False → DENY` is guaranteed", **scoped to exactly one
  case**: a `resume` presenting a token whose binding this engine has already
  settled and still retains. There `approved` becomes no ruling at all, because
  the policy is not consulted a second time. §8 below classifies it, and it is the
  same shape and the same narrowness ADR-0197 §13 recorded for the routed park.
  Everything else §4 decided — the confirmation's content, the token's opacity,
  the adapter's forbidden authorship — is untouched and binds a restatement as
  hard as it binds a resolution.
- **This is a contract change**, and it is ratified and merged as its own PR
  before anything implements against it (golden rule 5, ADR-0015 §1). It adds no
  method and moves no `core/types.py` member, field or validator; what moves is
  the **contract of a promoted method**, `AssistantEngine.resume`, whose
  `Raises: UnknownContinuationError` clause enumerates "unknown, expired, already
  claimed, or from a previous process life" and after this decision reads more
  widely than it holds. A method's contract moving is a change to a promoted
  surface whether or not the surface gains a method — ADR-0197 §7's own words for
  its own two sentences — so this is decided first and implemented second, and it
  owes both the adversarial and the architecture lens.

## Context

### Where this comes from

PR #1612 (lane HC) fixed the gateway page's re-offer of an abandoned park, and its
adversarial round 7 raised a `blocker` that the fix could not reach. Issue #1621
records it whole. The page had been un-spending a continuation token wherever
`pending_confirmations` still listed the park, on this reading:

> `_resolve_park` records the answer and evicts the binding under the same
> `_recovery_lock` that `_pending_confirmations` takes across its enumeration and
> reconcile — so a park observed pending is one no resume had resolved.

That is true and insufficient. The lock establishes that no `resume` **has**
resolved the park; nothing establishes that none **will**. An abandoned answer may
still be in transit, a listing that reaches `_recovery_lock` first legitimately
returns the park as pending, and a second `resume` then races the first: whichever
reaches `_resolve_park` first decides the park and the loser raises
`UnknownContinuationError`. The gateway renders every `AssistantError` as
`assistant-declined`, which a browser reads as "the hub received the request and
declined it" — a denial announced for an action that ran, which ADR-0084 §7
refuses in terms.

#1612 shipped the surface half instead, on the coordinator's ruling: the page
keeps such a token spent for the life of the page and tells the user that a reload
is what makes the park answerable again. A reload is a deliberate act taken after
reading an explanation; it is not a proof that the race is over. Making a
re-answer **safe** rather than merely deliberate is an engine-seam decision, and
it is this one.

### What the engine does today, and the sentence that decided it

`Engine._resolve_park` runs under `_recovery_lock`, records the answer through the
runner, and then evicts:

> `self._parked.pop(token.handle, None)`

with the reason stated beside it — "a second answer would be refused by the
trail's single-resolution index anyway; evicting keeps the table bounded and turns
a replay into a clean 'unknown token'". The shared conformance suite ratifies that
choice as `test_a_token_is_answered_once`, whose own docstring calls the resulting
`UnknownContinuationError` "the one refusal that has a remedy".

**The remedy is the whole of the problem.** ADR-0084 §7's remedy is
`pending_confirmations()` — enumerate durable state and re-mint. That is the right
answer for a token that names nothing: a hub restart, an eviction under
`max_outstanding_confirmations`, a handle a client invented. It is the wrong answer
for a replay, because there is nothing to re-mint: ADR-0052 §1 step 2 skips a
binding whose confirmation the trail no longer holds pending, so a settled binding
is never listed and never re-minted. A client told to enumerate finds an empty
listing and cannot tell "my answer landed" from "the park is gone". ADR-0084 §7
collapsed a restart and a ceiling eviction into one error **because "the client's
remedy is identical in both cases"**; that is the test, and a replay fails it.

### What the corpus already holds, and what it does not

The durable half of idempotency is built and ratified. ADR-0044 §2b's
single-resolution rule means a concrete `(execution_id, step_id)` binding carries
at most one resolution, and `AuditTrail.resolution_of` exists precisely so that a
binding whose ruling is durable but whose transition never committed "can be driven
to the disposition already decided — **idempotently, authoring nothing new** —
rather than re-authored". The engine already knows how to treat a second answer as
a question about a settled fact rather than as an act.

What is missing is one link: after eviction the handle names nothing, so the
engine cannot tell a replay from an invented token, and it therefore reports the
one as the other. The token is opaque by ADR-0042 §4 and the adapter may never
reconstruct the binding from it, so the surface cannot ask the question any other
way.

### The two directions #1621 names

1. **`resume` idempotent per binding** — a second `resume` for a binding already
   resolved answers with the recorded outcome instead of `UnknownContinuationError`.
2. **Recovery mints an invalidating token** — `pending_confirmations` mints a fresh
   token and refuses the older one with a condition that says so.

Direction 2 is refused below, on three grounds, the strongest of which is that it
does not answer the question the surface is asking.

### An honest statement of what this ADR is not allowed to settle

It decides the engine seam and nothing above it. What a browser page or a CLI
command **does** with a restatement — whether it re-offers a spent pair, and how it
renders an outcome that disagrees with the answer it just sent — is a surface
decision, ruled by ADR-0139 §4 and ADR-0177 §7 and taken in a lane that owns
`interfaces/`. It decides nothing about durable tokens: handles stay
process-scoped and unpersisted, exactly as ADR-0084 §7 ruled. And it changes
nothing about the routed park, for reasons §6 states rather than omits.

## Decision

### 1. A resolved binding is retained under its handle, and a second resume restates its answer

> **Normative.** Resolving a parked step **retains** the binding under the handle
> its continuation token names. The retained entry is a **settled record**: it
> carries the binding `(execution_id, step_id)` and the immutable facts §2 names,
> it is not a park, it holds no live turn, it authorises nothing, and no code path
> may resolve anything through it.

> **Normative.** The settled record is created in the **same critical section**
> that records the answer and evicts the park, and before that section's lock is
> released. A window in which the handle names neither a park nor a settled record
> would hand a concurrent `resume` the very `UnknownContinuationError` this
> decision exists to stop, and it would open on exactly the race #1621 describes.

> **Normative.** A `resume` presenting a token whose handle names a settled record
> **restates** that binding's answer: it returns a `TurnOutcome` describing the
> settled binding and raises no `UnknownContinuationError`.

> **Normative.** A restatement is returned **whatever the call's `approved`
> carries**, and the recorded answer stands unchanged. A park is answered once
> (ADR-0044 §2b), so a second answer is never honourable whatever it says, and the
> engine states what was decided rather than refusing to say.

**Restating rather than refusing is what makes the fourth clause resolvable.**
ADR-0177 §7's fourth clause rules that a browser request sent with no response read
is an outcome that is **not known** "whatever the gateway did", and ADR-0139 §4
rules that where a surface cannot read the state, "the user's next call can". A
`resume` presenting the same token **is** that next call, and after this decision
it reads the state instead of meeting a refusal. Nothing in either ADR moves: this
supplies the call that ADR-0139 §4's escape already promised and that no method
offered.

**Why the second `approved` is not compared against the first.** The engine could
retain the answer given and refuse a contradicting one with a second typed error.
That buys a distinct message and costs the surface the fact it came for: a caller
handed an error learns that the binding was answered and never learns *how*, and it
has no other way to ask. A caller handed the outcome learns both — it knows what it
sent, it can see what came back, and the disagreement is visible to it without a
second error class. `Alternatives considered` records the refused form.

### 2. What a restatement carries, and what it re-reads rather than caches

> **Normative.** A restatement carries `turn` `None`, `routed` `None`, `reply`
> `None` and `reply_degraded` `False` — ADR-0170 §4's second shape exactly, which
> this decision obeys rather than widens — and a non-`None` `step` describing the
> settled binding.

> **Normative.** The restatement's `StepOutcome` carries the **immutable** facts
> the settled record holds: the `Disposition` the resolution reached, the
> `step_id` of the binding, and the `tool_id` the step bound. Its `confirmation` is
> `None`, which the type's own validator already requires of a disposition that is
> not `AWAITING_CONFIRMATION`.

> **Normative.** The restatement's `StepOutcome.state` is **re-read** from the plan
> store at the moment of the restatement and is never a snapshot cached at
> settlement. What can change is read; what cannot is retained.

> **Normative.** Where the plan store no longer holds the execution the settled
> record names, the restatement raises `PlanningError` — the same failure a
> resolution raises today for the same condition — and the engine asserts nothing
> about the outcome. An outcome it cannot read is not one it may state, which is
> ADR-0139 §4's third limb arriving at the engine seam.

**`turn` is `None` even where the settled park was an in-process one, and that is a
decision.** Retaining a `TurnResult` would keep a turn's assembled context and
retrieved memories alive for the life of the record, and it would show a caller a
turn this call did not drive. `turn` `None` is what ADR-0052 §3 already chose for a
resume with no live turn behind it, and a restatement is that shape: durable state,
no turn. §8 records the one sentence of ADR-0052 §3 this makes read too widely.

**`reply` is `None` because the answer was composed once, for the request that
performed the act.** Composing again would be a second model call about a step this
call did not drive, held behind the caller for as long as a provider takes, and it
would produce prose that differs from the prose the first caller read for reasons
no user could account for. `reply` `None` beside `reply_degraded` `False` is
ADR-0170 §4's own statement that no answer was owed, and it is true here.

**Reading `state` rather than caching it is ADR-0139 §2's rule at a second seam.**
`StepOutcome.state` is defined as "the durable execution state after the last
transition committed", and a value cached at settlement stops being that the moment
anything else advances the execution. The `Disposition` cannot go stale — it is the
gate's verdict on a decision already taken, which ADR-0044 §2b makes unrepeatable —
so it is retained. `AuditTrail.resolution_of` is the durable corroboration of that
same fact and this decision adds no store query, on the seam or off it.

### 3. A restatement performs nothing, records nothing, and captures nothing

> **Normative.** A restatement calls no `StepRunner`, consults no `ActionPolicy`,
> records no `PermissionDecision`, invokes no tool, composes no reply and captures
> no episode. One park yields one resolution, one ruling, at most one execution
> attempt and at most one captured resumption, however many times its token is
> presented.

> **Normative.** A restatement is not an exchange, so it is not captured under the
> conversation that parked. Capturing it would file a second episode for one
> answer, which ADR-0074 §3's binding cannot describe and a user reading their own
> history would read as two.

**This is ADR-0044 §2b's refusal reaching the caller as an answer instead of as an
error.** The trail's single-resolution index would refuse a second resolution
anyway; today the engine forestalls that refusal by evicting and reports the
consequence as an unknown token. After this decision it reports the fact the index
is protecting — the binding is answered, and here is what it was decided.

### 4. Retention is bounded, holds no slot, and is never enumerated

> **Normative.** A settled record holds **no** slot at
> `max_outstanding_confirmations`. That ceiling bounds **unanswered** parks, and a
> settled record is the opposite of one; counting it would let a client that
> answered every confirmation meet backpressure for having done so.

> **Normative.** The retained set is bounded by `max_outstanding_confirmations`,
> discarding the **least recently settled** record when a new one would exceed it.
> No new setting is added, and no setting scales, extends or disables the retention
> separately.

> **Normative.** A settled record has **no lifetime** and no clock is read to
> decide its retention. A count is the whole of the bound.

> **Normative.** `pending_confirmations` neither lists a settled binding nor mints
> a token for one, and its reconciliation neither evicts a settled record nor
> treats one as a park. ADR-0052 §1 step 2 skips a binding the trail no longer
> holds pending, and that skip is unchanged: a settled binding is exactly such a
> binding, and re-presenting it would be the #257 hazard §1 closes.

> **Normative.** A handle naming a settled record is **not minted** for a new park,
> a new routed park or a new reservation while the record is retained. The engine's
> existing mint already tests a candidate against every live table, and the
> retained set joins them.

> **Normative.** Settled records are **process-scoped and never persisted**, as
> ADR-0084 §7 rules of the handle table itself. A restart empties them and a token
> from a previous process life yields `UnknownContinuationError` exactly as before.

**Why the ceiling is the size and no figure is invented.** The number of answers a
client can be uncertain about at once is bounded by the number of tokens it can
hold at once, and that is what `max_outstanding_confirmations` already bounds.
Reusing it makes the two numbers one, and a deployment that raises the ceiling
raises the window in the same breath and for the same reason.

**Why a count and not a lifetime, when ADR-0197 §7 chose a lifetime.** That section
bounds a **live** routed park, which holds a ceiling slot and a route identity —
scarce resources that a park nobody answers would hold forever, so the leak is real
and a clock is what closes it. A settled record holds neither. Its only cost is a
few fields of memory, and a count bounds memory exactly, needs no injected clock at
the lookup, and cannot make a token's answerability depend on how long a user
stared at a page. The asymmetry is decided here rather than left to be read as an
inconsistency.

**What the bound costs, stated rather than hidden.** A restatement sought after
`max_outstanding_confirmations` other parks have settled meets
`UnknownContinuationError` again. That is the behaviour every replay has today, so
the bound narrows the improvement and regresses nothing.

### 5. `UnknownContinuationError` keeps every case it had, and loses exactly one

> **Normative.** `UnknownContinuationError` covers, unchanged: an unknown handle, a
> handle from a previous process life, a park evicted under
> `max_outstanding_confirmations`, an expired park, a routed park already claimed,
> an expired routed park, and a settled record discarded under §4's bound. In every
> one of them it is **never a denial** (ADR-0084 §7).

> **Normative.** It ceases to cover exactly one case — a token whose binding this
> engine has settled and still retains — and it gains none.

> **Normative.** No error class is added to `core/errors.py` by this decision, and
> `resume`'s declared failure set (ADR-0085 §9) is unchanged: every class it
> declares is still raised by some input.

**The test that decides which case gets which answer is ADR-0084 §7's own.** It
gave one error to a restart and to a ceiling eviction "because the client's remedy
is identical in both cases", and the remedies here are not identical: a token that
names nothing is answered by enumerating and re-minting, and a token whose binding
is settled is answered by reading what was decided. Where the remedies coincide the
error stays one; where they diverge the engine answers instead of refusing. Nothing
in §7 becomes false — a settled-and-retained token is no longer "a token the server
cannot resolve", which is that section's subject.

### 6. The routed park is ruled exactly as ADR-0197 §7 rules it

> **Normative.** ADR-0197 §7's one-shot claim is unchanged in every respect. A
> routed park is claimed once and atomically, the claim evicts it, and a second
> `resume` presenting its token — concurrent or later, and whatever its `approved`
> value — resolves nothing and raises `UnknownContinuationError`. No settled record
> is retained for a routed park, and nothing in §§1–5 above reaches one.

Three reasons, in the order they bind.

**A routed operation's effect is readable, and a parked tool's may not be.** Every
confirm-owed member of the routable vocabulary writes to the hub's own state:
`revoke` is read back by `standing_grants` and `forget_question` by `questions` —
both read-only members of that same vocabulary, so the next ask reads them — and
`forget` is read back by the belief listing the promoted surface already carries.
ADR-0139 §4's escape is therefore available for every one of them without a
restatement. A parked tool step is the opposite case and is why ADR-0052 exists:
the act may be irreversible and its effect may be visible nowhere the assistant can
read.

**#1621's mechanism has no routed instance.** The race it describes is a **recovery
listing** overtaking a resume, and ADR-0197 §7 refuses to list a routed park at
all. There is no enumeration for a resume to overtake, and no surface that can
re-offer a routed card off a snapshot.

**Extending it would reopen an invariant on `core/types.py` for a case the first
reason already answers.** `TurnOutcome`'s validator rules that a routed pass "owes
an answer exactly when `routed.outcome` is not `AWAITING_CONFIRMATION`", and where
one is owed the outcome carries a `reply` or carries `reply_degraded` `True`
(ADR-0197 §8). A restatement composes nothing, so it would need a third `reply`
shape minted for a pass that drove nothing — a `core/types.py` validator change,
bought to duplicate a read the vocabulary already offers.

**Revisit if** the routable vocabulary gains a confirm-owed member whose effect is
**not** readable through the promoted surface, or if a routed park becomes
enumerable. Either would put a routed park in the position §§1–5 answer, and the
third reason above is a cost to weigh rather than a prohibition.

### 7. What the implementing lanes owe

> **Normative.** The implementation is **one lane**: `orchestration/engine.py`
> together with the `core/protocols.py` docstring clauses this decision moves, plus
> the shared conformance suite and the canonical fake. It is briefed after this ADR
> merges (golden rule 5), and it changes no file under `interfaces/`.

> **Normative.** That lane restates `AssistantEngine.resume`'s `Raises:
> UnknownContinuationError` clause, whose enumeration "unknown, expired, already
> claimed, or from a previous process life" is what this decision makes read too
> widely, and states the restatement positively in the method's own contract. It
> resolves none of issue #1636's separate sentence in passing.

> **Normative.** The lane updates the shared `AssistantEngineContract`, which binds
> `Engine`, the `wire` client and `FakeAssistantEngine` alike.
> `test_a_token_is_answered_once` is **replaced** rather than deleted: the case that
> pinned a replay as an unknown token becomes the case that pins it as a
> restatement, and a second case pins that the restatement performed nothing — the
> execution ran once and the trail holds one resolution.
> `test_a_routed_park_is_answered_once` is left exactly as it stands, which is what
> pins §6's scope.

> **Normative.** `FakeAssistantEngine` conforms in the same change. A fake that
> raised where the real engine restates would let every consumer's tests pass
> against behaviour no implementation has.

> **Normative.** No module under `wire/` changes and `PROTOCOL_VERSION` is **not**
> bumped. That constant gates the **representation** contract ADR-0084 §3 froze,
> and this decision changes no byte any payload can take: `TurnOutcome`'s shape is
> untouched, and a client built against the older behaviour is handed a success
> where it expected a typed refusal — a case every ratified client already handles,
> since a first resume produces it.

> **Normative.** The ADR-0082 §1 records §8 states are applied to the earlier ADRs'
> bodies by that same lane, in the change that implements this decision. This ADR
> states them and writes none of them, and the deferral is tracked as **#1640** so
> it cannot be lost.

### 8. This ADR classified under ADR-0070 §1 and ADR-0082 §1

ADR-0082 §1's test is ADR-0070 §1's applied to the earlier ADR's text: would a
reader holding only that ADR now act differently, or read one of its clauses more
widely than it now holds?

**ADR-0042 §4 — a record is owed, and it is a partial supersession.** That section
rules that `ActionPolicy.resolve` "is what turns `approved` into an `ALLOW` or
`DENY` ruling, and only `approved=False → DENY` is guaranteed". §§1 and 3 above
answer a `resume` in which `approved` becomes no ruling at all, because the policy
is not consulted a second time — the guarantee's subject is absent rather than its
value different. A reader acting on §4 would build a resume that always calls the
policy, so this replaces what §4 decided in a named case rather than reading it too
widely, which is ADR-0070 §1's line between the two. It is **partial** and narrow:
every `resume` that resolves a park is ruled exactly as §4 rules it, and §4's
account of what an adapter may not do — author the permission outcome — binds a
restatement whole. ADR-0197 §13 already recorded a partial supersession of the same
sentence for the routed park; this pair is added beside it rather than in place of
it (ADR-0070 §4).

**ADR-0052 §3 — a record is owed, and it is an amendment.** That section made
`TurnOutcome.turn` optional and wrote that "the in-process path is unchanged and
still carries the real turn". §2 above gives `turn` `None` to a restatement of a
park the same process parked in-process, so that sentence now reads more widely
than it holds — ADR-0082 §1's second limb. Nothing §3 decided changes: a reader
implementing it writes identical code, every resume that resolves a park carries
the turn §3 gives it, and §3's "the step outcome … is always present" stays true of
a restatement, which carries one. ADR-0052's `Status` is led by
`Partially superseded by`, so ADR-0082 §2 puts this record in the appended dated
note alone.

**ADR-0197 §7 — a record is owed on one incidental clause, and it is an
amendment.** Every clause §7 states about a **routed** park stands whole and is
restated by §6 above rather than changed. What moves is §7's parenthetical
enumeration of the tokens `UnknownContinuationError` covers — "unknown, expired,
already claimed, or from a previous process life" — whose "already claimed" limb
reads across both kinds of park and, after §§1 and 5, no longer holds of a settled
step binding this engine retains. A reader implementing §7 writes identical code:
that enumeration describes ADR-0084 §7's rule rather than deciding anything, which
is why it is an amendment and not a supersession. ADR-0197's `Status` carries no
leading token, so the qualifier accumulates on it in the established shape beside
the dated note.

**ADR-0084 §7 — no record is owed, and this one is worth stating rather than
omitting.** Its decision is that "presenting a token the server cannot resolve
yields one specific, typed refusal … and never a denial", and every word of it
stays true: what changes is which tokens the server can resolve, not what happens
to one it cannot. Its "one error covers both ways a handle can go missing … because
the client's remedy is identical in both cases" is the **test** §5 applies rather
than a clause §5 contradicts, and its ruling that handles stay process-scoped and
the table is not persisted is obeyed by §4's last clause. A reader checking the
records above will look for one here, and ADR-0082 §1 forbids a record demanded on
book-keeping grounds alone.

**ADR-0052 §§1–2 — no record is owed.** §1's four-step algorithm is unchanged and
still skips a binding the trail no longer holds pending; §2's idempotence and
boundedness are claims about the `_parked` table and stay exactly true of it. §4
above adds a second, separately bounded table and states that neither §1's
enumeration nor §2's reconciliation reaches it, which is a stacked addition.

**ADR-0044 §2b and §3 — no record is owed.** This decision rests on the
single-resolution rule and on `resolution_of`'s idempotent restatement of a settled
binding; it changes neither and adds no store query.

**ADR-0139 §4 and ADR-0177 §7 — no record is owed.** Both are obeyed. ADR-0139 §4's
"where this surface cannot read it, the user's next call can" gains a call that can
read it, which is the escape it named rather than a change to it; ADR-0177 §7's
fourth clause keeps its subject — the browser's own lost request is still an
outcome that is not known — and gains a way for the *next* request to resolve it.
Neither is narrowed, and neither ADR obliges a surface to take the new call.

**ADR-0170 §4 and ADR-0197 §8 — no record is owed.** A restatement carries `turn`
`None`, `routed` `None`, `reply` `None` and `reply_degraded` `False`, which is
ADR-0170 §4's second shape unchanged; §6 above declines the one extension that
would have reached ADR-0197 §8's owes-an-answer clause.

**ADR-0085 §9 — no record is owed.** Its per-method table declares a method's
failure **set** rather than which input produces one. `UnknownContinuationError`
and `PermissionDeniedError` both stay in `resume`'s set, and §5 adds nothing to it.

**Everything else is a stacked addition.** ADR-0042 §§3 and 6 (the token stays
opaque, the adapter still renders and relays and authors nothing). ADR-0074 §3 (the
parked binding's conversation is resolved exactly as before, and §3 above declines
to write a second episode under it rather than changing what one means). ADR-0009
(no clock is read, so no clause of it is engaged). ADR-0192 (a restatement spends
no authorisation and writes no invocation row, which is that decision's shape
obeyed). ADR-0186 (no trail row is written or read differently).

## Consequences

- A surface still holding a continuation token can ask "did my answer land?" and be
  answered. That is what makes ADR-0177 §7's fourth clause resolvable at this seam
  for the first time: the browser's lost request stays an unknown outcome, and its
  next request reads the state instead of meeting a refusal that means the opposite
  of what a page renders it as.
- The gateway page's re-offer becomes **safe** rather than merely deliberate. What
  the page does with that — whether it un-spends the pair, and how it renders an
  outcome that disagrees with the answer it just sent — is a later lane's, in a
  fence this ADR does not enter. #1621 stays open until that lane and the engine
  lane have both landed.
- A surface that does **not** hold the token gains nothing directly. ADR-0084 §7
  rules that a client stays stateless with respect to tokens and re-enumerates, and
  the CLI does; a settled binding is not listed, so the CLI's remedy is unchanged
  and remains reading the effect through the promoted surface. This is a stated
  limit of the decision, not an oversight: making a listing state a settled binding
  is refused below.
- The engine holds one more small in-memory table, bounded by a number that already
  exists, holding no ceiling slot and read only on a `resume`. Nothing about
  shutdown, persistence or recovery changes.
- The corpus gains a distinction it did not have: a token that names nothing and a
  token whose binding is answered are different questions with different answers.
  Every future surface meets both.
- **Revisit if** a turn ever drives more than one step (#242), which would let a
  settled binding's execution advance after settlement: §2's rule that `state` is
  re-read rather than cached is what keeps a restatement honest then, and it should
  be checked against whatever that lane makes an `ExecutionState` mean.

## Alternatives considered

- **Direction 2: `pending_confirmations` mints a fresh token and invalidates the
  outstanding one.** Refused on three grounds. It does not answer the question the
  surface is asking: a client told "you were overtaken" still does not learn whether
  **its** answer landed, which is the whole of #1621. It makes a **read** mutate
  answerability, so two surfaces enumerating concurrently would each invalidate the
  other's token and a second listing would become a denial of service against the
  first — while ADR-0084 §7 rules that clients re-enumerate freely because
  "re-enumerating costs one bounded read and behaves identically either way". And it
  contradicts ADR-0052 §2's ratified idempotence in terms, so it would need to
  supersede a decision that is working in order to reach an answer this one reaches
  without touching it.
- **Restate from a `TurnOutcome` cached at settlement.** Refused: `StepOutcome.state`
  is defined as the durable execution state after the last transition committed, and
  a cached value stops being that as soon as anything advances the execution. Reading
  what can change and retaining only what cannot is ADR-0139 §2's rule — read the
  store, not what the process happens to hold — and it costs one query.
- **List settled bindings from `pending_confirmations` so any surface can read the
  outcome.** Refused: ADR-0052 §1 step 2 skips a resolved binding precisely so that
  an answered confirmation is never re-presented (#257), and a listing that carried
  settled bindings would put a resolved action back in front of a user in the type
  whose whole purpose is "what you may still answer". The outcome belongs on the
  answer to the act, not in the queue of pending ones.
- **A second typed refusal for a repeat carrying the opposite decision.** Refused,
  and it was the shape this decision started from. It buys a distinct message and
  costs the caller the fact: an error says the binding was answered and never says
  how, and the caller has no other way to ask, because the token is opaque and the
  listing will not carry it. The disagreement a distinct error announces is one the
  caller can already see — it knows what it sent — so the class would carry no
  information the outcome does not.
- **Extend the restatement to the routed park.** Refused for §6's three reasons, the
  operative one being that a routed operation's effect is readable through the
  surface the client already has, so the corpus's own remedy is available without a
  new mechanism and without minting a third `reply` shape on `TurnOutcome`.
- **Leave it: a page reload is an adequate remedy.** Refused because it is not a
  remedy for the thing that is wrong. A reload makes the page willing to answer
  again; it does not make the second answer safe, and the race it is offered against
  is one the page cannot observe. #1612 shipped it knowingly as the surface half, and
  #1621 exists because the engine half was still owed.
