# 256. An authorization with no stated instant and no goal deadline takes the retention window its act's own record lives under

- Status: Proposed
- Date: 2026-09-12
- **Partially supersedes** [ADR-0254](0254-phase-4-validates-the-plan-in-code-and-route-d-authorises-a-concrete-call-against-fixed-values-and-permitted-ranges-from-recorded-acts.md)
  — **seven limbs, all about one field, `Authorization.expires_at`.** **§12's ladder rung 3
  entire**, its *"no row at all"* and its *"Nothing is invented, nothing is defaulted and
  nothing falls back to a configuration"* included: where the recorded act states no instant and
  the goal carries no `deadline`, `expires_at` is now the **earliest instant among the recorded
  turns the row's coverage rests on** advanced by the deployment's turn-retention window and a
  row **is** written, where that window is finite and that sum is strictly after `proposed_at`
  (§1).
  **§12's stated cost of that rung** — *"a goal carrying no `deadline` whose user stated no
  horizon has no route (d) at all, and every call of it asks"* — which is true only where that
  window is set to keep turns forever, and there the ratified rung stands verbatim as the
  ladder's last (§3). **§12's no-deployment-wide-expiry clause, in the single respect that the
  third rung reads one deployment value, `core.config.Settings.episode_retention`**, together
  with **§12's justification clause in its limb *"and in neither case by a deployment"***; every
  other limb of both stands, `Settings` gains nothing and no figure bounds rung 1 or rung 2 (§2,
  §7). **§12's path-(ii) transcription clause together with §1's path-(ii) *"transcribed
  unchanged"* list and §1's path-(i) *"the only path that may … set `expires_at`"***, each in
  the `expires_at` limb alone and in the **narrowing direction alone** (§5). **§9 clause (ii)'s
  bar limb *"move `expires_at`"***, in that same narrowing direction alone. **§9 clause (iii)'s
  *"not taken"* half, only as §12 reads it onto an `expires_at` and only on a path-(ii)
  correction**: an instant the correction's span does not settle is now resolved to the
  **earliest admissible** reading rather than discarded, and clause (iii)'s asking limb is not
  superseded — it follows the discarding, and in that scope there is none (§5). And **§19's
  entry *"What the user is shown where §12's ladder yields no instant"***,
  **narrowed in application and not replaced** (§7). Every other clause of ADR-0254 §12 binds
  entire and several are what this decision rests on: no `Settings` **field**, the expiry per
  `Authorization` and shown when it is granted, no ceiling over rung 1 or rung 2, the expiry
  taken once and never recomputed, an answer arriving at or after it establishing nothing, the
  recipient-grant and configured-provider exclusions, the visible-at-the-act rule and the
  no-deletion rule. §§1–11 and §§13–22 stand as they are, but for the limbs of §1 and §9 named
  above.

## Context

### Where this comes from

ADR-0254 §12 states the expiry ladder for a route-(d) `Authorization` and calls it **total in
three rungs**: the instant the user's own act states; otherwise the goal's own `deadline`;
otherwise **no row at all**. The third rung's cost is stated in the ADR rather than hidden:

> **The cost of step 3 is stated rather than hidden**: a goal carrying no `deadline` whose user
> stated no horizon has no route (d) at all, and every call of it asks. That is the fail-closed
> direction and the only one compatible with an expiry the user can be said to have seen; the
> repair is a goal with a deadline or a user who names one, both of which are the user's own
> act. §19 books the decision that would ask for the instant instead.

The owner read that rung after ADR-0254 was ratified and ruled against it:

> *"it can reproduce the interruption problem for ordinary requests without deadlines. I would
> prefer a defined way to establish an appropriate expiry once, rather than repeatedly
> confirming actions."*

Two of the rulings ADR-0254 itself records are the ground the replacement is built on, and both
are quoted whole rather than paraphrased.

**Decision 4.** *"Allow reopening while the goal and applicable history remain retained; no
separate arbitrary timer."*

**Decision 7.** *"Workflow-specific authorization carries a justified, visible expiry. This does
not apply indiscriminately to existing standing permissions or to configured-provider authority
(ADR-0247)."*

### The gap this closes, stated as the ordinary case

A user says *"book that campsite for the weekend, under sixty pounds"*. There is no deadline on
the goal — the objective is the booking, not a date the system recorded — and the user named no
horizon, because naming one is not how people speak. Under ADR-0254 §12 as ratified, rung 1
finds no instant, rung 2 finds no `deadline`, and rung 3 writes **no row**. Every call of that
goal is then confirmed under ADR-0148 §3's route (a), which is exactly the *"a disclosing tool
prompts every time, which is the correct default and a poor steady state"* ADR-0021 §6 names and
which ADR-0254 exists to end. The mechanism works precisely where the user happened to supply a
date and does nothing at all for the ordinary request — the owner's *"interruption problem for
ordinary requests without deadlines"*.

The two exits ADR-0254 leaves are both rejected by the ruling above rather than merely unchosen.
**Asking the user for a horizon** — §19's booked decision — puts a second question at the moment
this design exists to remove one, and ADR-0254 §19 says so itself: *"which is a second question
at the moment this design exists to remove one and is not taken here"*. **A figure minted for
this record** — a `Settings` field, or a constant — is refused by §12's own words: an operator's
figure is *"a clock the user never saw"*, and decision 7's *"justified, visible"* cannot be
satisfied by one.

So what is needed is an instant that is **not a timer minted for this record** — decision 4's
*"no separate arbitrary timer"* — and that is nonetheless stated at the act and readable off the
row. There is exactly one window already in the corpus that answers that description, and it is
the one the act's own record lives under.

### What is already ratified and is read rather than rebuilt

**ADR-0074 §7 — retention.** *"Captured episodes carry a finite `expires_at` by default,
stamped at capture from the injected clock and a **dedicated** retention window on
`core.config.Settings` — `episode_retention: timedelta | None`, **defaulting to a finite
duration**, with `None` meaning "keep forever" and available only by the user setting it."* The
accepted cost is stated there too: *"a conversation whose turns have passed the horizon
continues with no history"*, its turns gone from retrieval and export. The conversation record
is reclaimed on the same horizon, *"when it has **no live turns *and* its `last_active_at` is
past the horizon**"*, and *"`episode_retention = None` disables conversation reclaim entirely"*.

**ADR-0254 §8, §9 and §11 — the basis, and where the instant is already shown.** Every coverage
member rests on a basis naming *a recorded turn and a span inside that turn's stored utterance*
(§9 clause (i)), the listing renders that span, and `export` carries the basis whole. The expiry
is already rendered in all three places an authority is put in front of the user: the
confirmation's `AuthorizationProjection.expires_at`, the `TurnOutcome.authorizations`
announcement's `AuthorizationView.expires_at`, and the per-goal listing's. **This decision adds
no surface**, and that is why decision 7's *"visible"* needs nothing new.

**ADR-0254 §12's prospectivity, which this rung inherits.** *"a later edit to the goal's
`deadline` moves no row already written — a row states the horizon that stood when the authority
was granted"*.

### The tree, read rather than assumed, at `origin/main` `ebc2f8bb`

**None of ADR-0254 is implemented.** Its lanes have not been briefed, `Authorization`,
`GoalAuthorizationStore` and route (d) exist nowhere in `src/`, and this decision therefore makes
no claim about code that would implement §12. The one code claim it does make is about the input
the new rung reads, and it is read rather than recalled:

- `core/config.py` carries `episode_retention: _OptionalDuration`, `default=timedelta(days=30)`,
  `gt=timedelta(0)`, described as *"How long a captured conversation turn's episode is retained.
  Finite by default (ADR-0074 §7); set it to 'none' to keep episodes forever, which also stops
  idle conversations being reclaimed."* It is **strictly positive when set**, refused at load
  otherwise, and `None` is reachable only by the disable sentinel.
- `memory/conversation_store.py`'s `SqliteConversationStore._drop_if_eligible_sync` is the
  reclaim rule this decision relies on. Where the conversation is not deleted it computes
  `eligible = self._retention is not None and now - conversation.last_active_at >=
  self._retention`, re-read **inside the dropping transaction** with a clock reading taken there,
  and `self._retention` is the same `episode_retention`. Its own comment records why the
  subtraction is written that way: *"`now - stamp >= duration` rather than `stamp + duration <=
  now`: the two are equivalent, but only the first cannot overflow"*, because `checked_clock`
  admits a reading a day short of `datetime.max` (ADR-0026 §3).

**One premise this lane was handed does not survive that reading, and the decision is stated on
what is actually true instead.** It is tempting to describe the new rung as *the instant the
conversation's own retention would let the goal go*. On `origin/main` a conversation's retention
**never lets a goal go**: ADR-0250 §13 rules that *"a goal whose **conversation** was deleted
keeps its row and **stays referenceable**"*, and `PlanStore` carries no retention at all. What
decision 4's *"the goal **and applicable history** remain retained"* actually names is the
**history** — the recorded act the authority quotes — and that is what carries a window. The
decision below is stated over that window and over nothing else, and §1 states exactly how far
the correspondence between the row and the act's own episode holds.

### What this ADR is not allowed to settle

It touches **one field's value on one rung**. It adds no type, no field, no `Settings` entry, no
store member, no engine member, no surface and no write path. It changes nothing about what
route (d) covers, what a coverage member is, what the policy reads, what the audit trail records
or what any adapter renders. It is not the decision ADR-0254 §19 books about asking the user for
an instant, and it does not take that decision by another route.

## Decision

### 1. The ladder's third rung becomes the deployment's turn-retention window

> **Normative.** **ADR-0254 §12's ladder is taken exactly as it stands, and its third rung is
> replaced.** Where the recorded act states no instant that ADR-0254 §10's resolutions take
> (rung 1), and the goal carries no `deadline` or carries one at or before `proposed_at`
> (rung 2), `expires_at` is **the row's basis instant advanced by the deployment's
> turn-retention window** — `core.config.Settings.episode_retention` (ADR-0074 §7) — **where
> that window is finite**. The rung is taken **on paths (i) and (iii) alone and at the instant
> the row is written**, which is ADR-0254 §12's own rule for the ladder; **path (ii) takes none
> of the ladder**, and §5 below is the one motion a correction may make on this field.

> **Normative.** **The row's basis instant is the earliest recorded-turn instant its coverage
> rests on, and it is `proposed_at` where the row carries no coverage at all.** Every
> `CoverageMember` carries an `AuthorizationBasis` naming a recorded turn (ADR-0254 §8, §9
> clause (i)); the basis instant is **the earliest of those turns' own instants**, taken over
> every member of the row being written. A path-(i) proposal about an argument-free call carries
> `coverage=()` (ADR-0254 §11), rests on no act but the recorded `CONFIRM` itself, and takes
> **`proposed_at`**. A path-(iii) row's coverage is minted from its own act, so its basis
> instant **is** `proposed_at` and the two readings coincide.

> **Normative.** **That instant is resolved by the rule ADR-0254 already requires of every
> member, and this decision adds no reader.** ADR-0254 §9 clause (i) makes an `Authorization`
> constructible *"**only** with a basis naming a recorded turn and a span inside that turn's
> stored utterance, on **every** coverage member"*, and §16 assigns that comparison in terms —
> *"a rule comparing a basis against a **recorded turn** is **`orchestration`'s** … before the
> row is built"*. So the turn each member rests on is in `orchestration`'s hand at the write
> already, and its instant is the same value ADR-0254 §1 reads off a recorded turn for
> `proposed_at` on paths (ii) and (iii). **No store, seam, field, type or contract is added for
> it**, and **where the instant of any basis act cannot be resolved at the write — the turn is
> gone — no row is written**, the ladder falls to §3's last rung and the concrete call is
> confirmed under ADR-0148 §3's route (a).

**The window, and not the act's episode's own stamp, and the reason is that the stamp is not
reachable.** ADR-0074 §3 captures one `EpisodicMemory` per turn *outcome*, so on path (i) — where
`proposed_at` is the recorded `CONFIRM`'s `decided_at` — the episode of the turn the act rode may
not have been written when the row is. A rung that could not be taken on one of its two paths
would not be a rung of a total ladder, and reading one would put a `MemoryStore` read on the
write path of a permissions record, which ADR-0254 §16's roster does not contemplate. **The
recorded turn and the episode of that turn are two different records and only one of them is
already in hand**: the turn is what §9 clause (i)'s own resolution reaches for on every member,
and the episode is a `MemoryStore` record nothing on this path reads. So the row takes the
**same window** as the act's record, measured from the act's own recorded instant rather than
from that record's stamp.

> **Normative.** **A row outlives the episode of an act it rests on in exactly one case, and
> that case is named rather than hidden.** An episode is stamped at capture from the same
> setting (ADR-0074 §7) and capture is at or after its turn's own instant, so a row taking the
> window from the **earliest** turn its coverage rests on expires at or before that act's
> episode — **except** where `episode_retention` was **widened between that act's capture and
> the row's write**, the episode carrying the window in force when it was captured and the row
> the window in force when it was written. **That one case is not repaired here and is not
> hidden**: the row is bounded by the window in force at its own write and by nothing longer,
> §4's rendering shows the instant it actually carries, and §9's arms pin it.

> **Normative.** **An authority is never granted on an act the deployment's own horizon has
> already passed.** Where the basis instant advanced by the window is at or before
> `proposed_at` — which is exactly the case where the oldest act the row would rest on is older
> than the window itself — the row would be born expired, ADR-0254 §1's construction refuses it,
> and **no row is written**: the ladder falls to §3's last rung and the concrete call is
> confirmed under ADR-0148 §3's route (a). Nothing is clamped to make such a row
> constructible. **This is the clause that makes ADR-0254 §8's per-member basis safe here** — a
> path-(i) proposal may carry members resting on acts far older than the `CONFIRM` it rides
> (§8's *"Two members of one record may name two different acts"*), and a window measured from
> the write would hand such a row a full horizon past the point at which the evidence for it
> stopped being kept.

**What the rung does claim, and it is exactly decision 4's.** It is **not a separate arbitrary
timer**: no figure is minted for this record, no `Settings` field is added for it, and the
duration is the one the deployment already applies to the act's own record rather than one chosen
for an authority. That claim is true without qualification, and it is the claim decision 4 makes
— *"no separate arbitrary timer"* — rather than a guarantee of coincidence with any particular
episode's stamp. The reason the window is the **right** one is that the authority's whole
justification is a recorded act: every coverage member carries a basis naming a turn and a span
(ADR-0254 §9 clause (i)), the listing renders that span, and `export` carries the basis whole
(§11). Past that window *"a conversation whose turns have passed the horizon continues with no
history"* (ADR-0074 §7) — the turn a basis names is gone from retrieval and from export. **What
survives is the row's own transcription of the user's words, and what does not is the
independently recorded turn that transcription could be checked against**: ADR-0254 §11 puts the
span on the row, so a listing never loses the ability to say what the user said, and the `act`
the basis carries is what stops pointing at anything. An authority granted for materially longer
than the acts it rests on are kept would be an authority whose own account of itself had become
uncheckable, and that is what this rung declines to write — which is why the window runs from the
**earliest** act the row rests on rather than from the row's own instant.

**It is shorter than the conversation's own reclaim, which is the fail-closed direction, and it
is now so across conversations too.** A conversation is reclaimed only when it has no live turns
**and** `last_active_at` is past the horizon, and `last_active_at` is at or after the instant of
every turn that conversation holds — so a conversation holding a basis act survives at least
until that act's instant advanced by the window, which is at or after this rung's answer. The
comparison held before only for the conversation the row was written in; measuring from the
earliest basis act makes it hold for every conversation the row rests on. Taking the window
rather than the conversation's eligibility also keeps the instant **fixed**: the conversation's
is a moving target, and §2's read-once rule could not be stated over one.

### 2. `Settings` gains nothing, the one deployment value read is recorded, and the arithmetic is fail-closed

> **Normative.** **`core.config.Settings` gains nothing.** No field is added, no default about an
> authorization is minted, no ceiling is placed on rung 1 or rung 2, and there is **no sentinel,
> no "forever" spelling and no disable spelling** for an `Authorization.expires_at`. ADR-0254
> §20's *"**no `Settings` field at all**"* binds every implementing lane unchanged.

> **Normative.** **ADR-0254 §12's bar on a deployment-wide expiry is superseded in one respect
> and in one only**: the ladder's third rung reads one deployment value,
> `core.config.Settings.episode_retention` (§1). Every other limb of that clause stands — the
> expiry is **per `Authorization`**, set when the authority is granted and shown then; no
> operator figure bounds rung 1 or rung 2; and no clause of this decision reads a deployment
> value for any other purpose. **§12's justification clause is superseded in its limb *"and in
> neither case by a deployment"* and in no other**: the instant is now justified by the act, by
> the objective, **or by the window the deployment keeps the act's own record for**, and §7
> records both.

**Why the harm §12 names is absent here, stated so a reader can check it rather than take it.**
The bar's reason is given in the clause: *"An operator's figure is **a clock the user never
saw**, and decision 7's 'justified, visible' cannot be satisfied by one: a long-lived goal whose
authority lapsed on a deployment default would lose it for a reason nobody stated at the act and
nobody could read off the row."* Both halves of that harm are absent. The instant **is** stated
at the act, because ADR-0254 §11 already requires the projection and the announcement to name it;
and it **is** read off the row, because it is the row's own `expires_at`. What remains true is
that the *duration* is an operator's — it is the operator's figure for **how long the act's own
record is kept**, not a figure for how long an authority may last — and because that is a
difference of ground rather than of effect, the supersession above is **recorded** rather than
argued away.

> **Normative.** **The window is read once, by `orchestration`, at the instant the row is
> written, and is never recomputed.** ADR-0254 §15's writer clause binds unchanged: no store, no
> `ActionPolicy`, no `AuditTrail`, no interface adapter, no reader, no tool and no model output
> reads it or writes a row from it. **A later change to `episode_retention` moves no row already
> written**, which is ADR-0254 §12's own prospectivity clause — *"a later edit to the goal's
> `deadline` moves no row already written"* — read onto the one further input this rung takes,
> and a widened window neither extends a live row nor revives a lapsed one.

> **Normative.** **The arithmetic is fail-closed, and wherever it does not yield a usable
> instant no row is written.** `episode_retention` is refused at load unless it is strictly
> positive, so the sum is **strictly after the basis instant** — but it is **not** thereby
> strictly after `proposed_at`, the basis instant being at or before the write, and §1's clause
> on that case governs: the row is not clamped to satisfy ADR-0254 §1's construction, it is not
> written. Where the addition cannot be taken at all — a clock reading near
> `datetime.max`, which `checked_clock` admits (ADR-0026 §3) and which `SqliteConversationStore`
> already guards its own comparison against — **no row is written**, the ladder falls to §3's
> last rung, and the concrete call is confirmed under ADR-0148 §3's route (a). **Nothing is
> clamped, rounded, saturated or defaulted.**

### 3. Where the deployment keeps turns forever, ADR-0254 §12's rung 3 stands as the ladder's last

> **Normative.** **The ladder stays total, and its last rung is the ratified one.** Where
> `episode_retention` is `None` there is **no window to read**, and ADR-0254 §12's third rung
> applies exactly as written: **no path-(i) proposal and no path-(iii) row is written**,
> `Confirmation.authorization` is absent (§11), and the concrete call is confirmed under
> ADR-0148 §3's route (a) exactly as it is today. **A path-(ii) correction takes no rung of this
> ladder at all** — under `None` exactly as under any window, which is ADR-0254 §12's own
> path-(ii) rule and §1's — so **no clause of this section bears on a correction's expiry** and
> §5 alone settles it. Its stated cost stands with it, in this case alone: every call of such a
> goal asks.

**This is not a defect to repair with a number.** `None` is *"keep forever"*, it is *"available
only by the user setting it"* (ADR-0074 §7), and it also switches conversation reclaim off. So
the deployment where this rung fires is one where a user has deliberately said that nothing
lapses — and inventing a horizon for an authority there would be minting exactly the figure §12
forbids, on a deployment whose owner has said the opposite. The repair is the one ADR-0254 §12
already names and it is unchanged: *"a goal with a deadline or a user who names one, both of
which are the user's own act."*

**And it is what keeps "there is no spelling for one without it" true.** ADR-0254 §12's first
clause admits *"no null, no sentinel, no 'forever'"* for `expires_at`. A rung that answered
*"keep forever"* with an unbounded authority would need one of the three. Withholding the row is
the only answer compatible with that clause, and it is the fail-closed one.

### 4. What the user is shown, and why no row records which rung set its expiry

> **Normative.** **The instant is shown exactly where ADR-0254 §11 already shows it, and this
> decision adds no surface, no carrier, no member and no second rendering.** The confirmation's
> `AuthorizationProjection.expires_at` on path (i), the `TurnOutcome.authorizations`
> announcement's `AuthorizationView.expires_at` on path (iii), and the per-goal listing's on
> every read afterwards. Decision 7's *"visible"* is discharged by those clauses unchanged.

> **Normative.** **`Authorization`'s field list stays closed and no row records its rung.**
> ADR-0254 §1's list is closed and *"a lane adding a member is changing this decision rather
> than implementing it"*; this decision adds none, and no lane may add one to say where an
> expiry came from.

**How decision 7's *"justified"* is discharged.** By this ADR stating the justification, which is
ADR-0254 §12's own device — *"the justification, stated in the ADR so a lane need not invent
one"* — and the justification for this rung is §1's: **an authority takes the window the
deployment keeps the record of its act for, and never a window minted for it.**

**The alternative was considered and rejected.** A `source` member on the row — naming which rung
set the expiry, so a surface could render *"until your weekend"* against *"as long as this
conversation is kept"* — would reopen a field list ADR-0254 calls closed, add a value every
migration and every export must carry, and buy a phrase rather than a fact. What the user checks
before answering is **the instant**, and the instant is true whatever produced it. A reader who
wants the ground reads this ADR, which is where §12 already puts the justification for the two
rungs above.

### 5. A correcting act that states an earlier instant narrows the horizon, and nothing lengthens one

> **Normative.** **A path-(ii) correction may move `expires_at` in exactly one way.** Where the
> correction's **own span** states an instant, resolved by `DATE_FROM_CONTEXT` or `AS_STATED`
> under ADR-0254 §10's resolutions and §9's clauses (i) and (ii) entire — the same machinery
> rung 1 takes and no other — **and that instant is strictly after the new row's `proposed_at`
> and strictly before the superseded row's `expires_at`**, the new row carries that instant.
> **Where the correction's span states no instant at all, or states one outside those two
> bounds, `expires_at` is transcribed unchanged**, which is ADR-0254 §12's path-(ii) clause
> standing. A span that states an instant it does not settle to **one** value is neither of
> those cases and is governed by the third clause below.

> **Normative.** **Nothing lengthens a horizon on any path but (i).** An instant at or after the
> superseded row's `expires_at` is **not taken**; an instant at or before the new row's
> `proposed_at` is **not taken**, such a row being born expired and refused at construction
> (ADR-0254 §1); a `Goal.deadline` edited after the fact moves no row; a widened
> `episode_retention` moves no row (§2); and a chain of corrections can therefore only ever
> shorten. ADR-0254 §12's *"No sequence of corrections outlives the confirmation that began it"*
> holds **a fortiori**. **Lengthening or renewing an authority is path (i)'s alone** — ADR-0254
> §1's *"That is what renews an authority whose expiry has passed as well as what widens a live
> one"* — because extending an authority is the direction that needs the user to have been shown
> what they are extending.

> **Normative.** **An instant a correction's span does not settle to one value takes the
> earliest admissible reading.** Where the span admits more than one instant, the new row
> carries **the earliest of the admissible ones** — admissible being exactly the two bounds the
> first clause of this section states, strictly after the new row's `proposed_at` and strictly
> before the superseded row's `expires_at`. Where those bounds admit **none** of the readings,
> nothing is taken and `expires_at` is transcribed unchanged.

> **Normative.** **That supersedes ADR-0254 §9 clause (iii)'s *"not taken"* half on this field
> and this path alone, and its asking limb is not superseded.** The resolution is taken rather
> than discarded, so clause (iii)'s *"the user is asked"* limb — which is the consequence of the
> discarding — is not engaged, and **no question is put about the instant**. The scope is
> exactly: an `expires_at`, on a path-(ii) correction, under this decision's narrowing. Clause
> (iii) binds entire everywhere else — for every coverage member, for a consequence outside
> scope, and for an instant taken under §12's rung 1 on paths (i) and (iii). §7 records it.

> **Normative.** **The earliest reading is the narrowest one, and that is why it is the one
> taken.** ADR-0254 §9 clause (ii) states its own principle — *"The interpretation narrows what
> the act covers and can never widen it"* — and of the readings a span admits, the earliest
> yields the **least** authority. So an unsettled instant leaves strictly less authority than
> transcription would and never more; and the readings it is taken over are exactly the ones §9
> clause (iii) already quantifies over in *"the span admits more than one admissible value"*.
> **This decision enumerates no reading that clause does not and mints no determination of its
> own**, so nothing here needs a discriminator on a raised question and ADR-0250 §7's
> `ProposedQuestion` is untouched.

**Why an unsettled instant is resolved rather than asked about, and what that buys over
discarding it.** The correction lands regardless — ADR-0254 §12's *"a correction is never refused
for want of an instant it was never going to set"* binds entire — so a question here could not
change what the correction does to the coverage, and it would be a second question at the moment
this decision exists to remove one, which is the ruling this ADR rests on. What taking the
earliest reading buys over the ratified discarding is that **the user's restriction is never
dropped**: *"actually, make it Sunday, and only until Friday"* lands both halves whether or not
the system can tell which Friday, and the half it lands is the shorter one. Nor is anything
dropped **silently**: the instant the row carries is rendered in the per-goal listing on every
read afterwards and carried by `export` (ADR-0254 §11), the correcting act is on the row as the
basis of the member it replaced — so `export` names the turn the instant was read from — and the
revocation handle is in front of the user beside it. The user's own act for ending an authority
outright is still `revoke_authorization` (ADR-0254 §11), which this decision does not re-spell.

> **Normative.** **This mints no write path.** The narrowing rides a path-(ii) correction ADR-0254
> §1 would write anyway — *"A later recorded turn of the same goal whose span names an argument
> a **live** row of that goal already carries a member for"*. **An act that names only an instant
> and corrects no argument is not a correction under that clause**, writes no row and moves
> nothing; ADR-0254 §15's *"there is no fourth path"* binds entire.

**Why the narrowing is taken at all, rather than left to revocation.** Under ADR-0254 as
ratified, every `expires_at` a correction transcribes came from an instant the user named or
from the goal's own `deadline`. After §1, a correction can transcribe an instant that came from
**this rung** — one the user was shown but never chose. A user who then says *"actually, make it
Sunday, and only until Friday"* would, under strict transcription, have the second half of their
own sentence **silently dropped** while the first half landed. That is the failure mode this
corpus refuses everywhere it can see it, and it is a restriction being dropped rather than a
request: ADR-0254 §9's own asymmetry is that *"A model is a safe denier and an unsafe allower"*,
and a user-stated narrowing is the safest motion available. Revocation is a coarser act — it ends
the authority now, rather than bounding it — and offering it as the only answer to *"only until
Friday"* answers a different question.

**Why §9 clause (ii) does not forbid it, read as it actually stands.** That clause's bar list —
*"raise a `maximum`, lower a `minimum`, add a member to `terms`, widen `destinations`, change
`account` or `tool`, or move `expires_at`"* — is a list of **widenings**, and the clause states
its own principle in the next sentence: *"The interpretation narrows what the act covers and can
never widen it."* `expires_at` appears in that list absolutely because, when §9 was written, no
narrowing of it was representable — §12 transcribed it in every case. This decision makes one
representable and confines it to the direction §9's own principle permits. §9's clause (i) and
its no-model-output rule are untouched, and the instant is resolved by the same machinery as any
other value the act states.

### 6. What this decision leaves exactly as it stands

> **Normative.** **Rungs 1 and 2 take no ceiling from this decision.** A user-stated instant and
> a `Goal.deadline` may each run past the window §1 reads, and neither is clamped, shortened or
> refused for it. A user's own instant is what ADR-0254 §11 shows them, and showing an instant
> other than the one they said would defeat the clause this rung exists to satisfy; a goal's
> `deadline` is likewise the objective's own horizon and not a figure. §8 books the question that
> would cap either.

> **Normative.** **`RecipientGrant.expires_at` is untouched, and so is ADR-0247's
> configured-provider authority.** ADR-0254 §12's negative clause naming both binds entire and
> this decision narrows neither: no clause here shortens, defaults or recomputes a grant's
> instant, and the configured-provider authority still has no record, no instant and no expiry.
> **A lane that applied this rung to either has breached that clause**, in its own words.

> **Normative.** **ADR-0074 is read and not changed.** `episode_retention`'s finite default, its
> `None` spelling, the per-episode stamp, the read-time enforcement, `purge_expired`, the
> conversation reclaim rule and §8's deletion all stand exactly as ratified. **This decision adds
> no reader to the episode store or the conversation store and no cross-store contract of any
> kind**: the one value it reads from ADR-0074's side of the corpus is the `Settings` duration
> (§1), and the recorded-turn instant §1's rung measures from is reached by ADR-0254 §9 clause
> (i)'s own basis resolution, which `orchestration` performs on every member of every row it
> builds whether or not this decision exists.

> **Normative.** **No row is moved, shortened or settled by anything that happens to the act's
> own record.** A row whose act's episode has lapsed, or whose act's conversation was deleted
> under ADR-0074 §8, keeps the `expires_at` it was written with and stands until that instant;
> ADR-0254 §12's no-deletion clause binds entire, and §8 books the decision that would couple the
> two.

**Why the deletion case is left alone rather than closed.** Coupling an authority's liveness to
its act's record would need a cross-store read on `ActionPolicy.decide`'s path or a cross-store
deletion — machinery ADR-0254 §16's roster does not contain and §19 books next door as *"Retention
for this store beyond `clear`"*. It would also answer the wrong question: deleting a conversation
is a user act on a **conversation**, and the user's act for ending an **authority** is
`revoke_authorization`, which the listing puts in front of them with its handle at the moment the
authority comes into being (ADR-0254 §11). §1's claim is about what window an authority is
**granted** for, and it is stated prospectively for exactly that reason.

### 7. What this records against ADR-0254, clause by clause, under ADR-0082 §1

ADR-0082 §1's test is ADR-0070 §1's applied to the earlier ADR's text: would a reader holding
only ADR-0254 now act differently, or read one of its clauses more widely than it now holds? For
each limb the answer is yes, and the sentence that becomes false or over-wide is named.

1. **§12's ladder, rung 3, entire.** *"**no row at all.** Where the act states no instant **and**
   the goal carries no `deadline` … **no path-(i) proposal and no path-(iii) row is written**"*,
   and with it that rung's *"Nothing is invented, nothing is defaulted and nothing falls back to
   a configuration"*. A reader holding only ADR-0254 writes no row for every deadline-free goal;
   after this decision they write one wherever the turn-retention window is finite — which is the
   default — **and the earliest act the row rests on is still inside it**. **Superseded, narrowed
   to where a window exists and the row's basis instant advanced by it is strictly after
   `proposed_at`** (§1, §3).
2. **§12's stated cost.** *"a goal carrying no `deadline` whose user stated no horizon has no
   route (d) at all, and every call of it asks"*. Over-wide as it stands: true only under a
   deployment that keeps turns forever. **Superseded in scope, and verbatim where §3 fires.**
3. **§12's no-deployment-wide-expiry clause, and §12's justification clause's limb *"and in
   neither case by a deployment"*.** A reader holding only ADR-0254 reads no deployment value
   for an expiry at all. **Superseded in the single respect that §1's rung reads
   `episode_retention`**, and in no other: `Settings` gains nothing, the expiry stays per
   `Authorization` and shown when granted, and no figure bounds rung 1 or rung 2 (§2, §6).
4. **§12's path-(ii) transcription clause, §1's path-(ii) *"`expires_at` … transcribed
   unchanged"* and §1's path-(i) *"the only path that may … set `expires_at`"*.** A reader
   holding only ADR-0254 refuses every movement of that field on a correction. **Superseded in
   the `expires_at` limb of each and in the narrowing direction alone** (§5); the widening
   direction, the rest of each list — `goal`, `tool`, `account`, `destinations`, `origin` — and
   the whole of path (ii)'s carry-forward rule stand entire.
5. **§9 clause (ii)'s bar limb *"move `expires_at`"*.** **Superseded in the narrowing direction
   alone** (§5), on that clause's own stated principle. Clause (i) and the no-model-output rule
   stand entire.
6. **§9 clause (iii)'s *"not taken"* half, *"the resolution is **not taken** and no member is
   minted from it"*.** §12 reads §9's clauses onto the instant a rung takes, so as ADR-0254
   stands an instant a correction's span does not settle is discarded and the user asked. §5
   **takes** it, as the earliest admissible reading, **for an `expires_at`, on a path-(ii)
   correction, and nowhere else**. **Superseded in that scope alone.** **Clause (iii)'s asking
   limb is not superseded and loses no sentence**: it is the consequence of the discarding, and
   in that one scope there is nothing discarded for it to follow. Its asking for every coverage
   member, its consequence-outside-scope limb, its bar clause and the *"not taken"* half
   everywhere but here all stand entire.
7. **§19's entry *"What the user is shown where §12's ladder yields no instant"*.** **Narrowed in
   application and not replaced.** The entry books a decision — *"a decision that would ask
   'until when?' at the act"* — and **this is not that decision and does not take it**. What
   changes is the entry's premise: the case now arises only where §3 fires, not for every
   deadline-free goal. A reader holding only §19 would read the booking more widely than it now
   holds, so the record is owed; the booking itself stands open.

**Every other ADR this decision touches is relied on, not amended.** ADR-0074 §7 supplies a
setting and a window and loses no sentence (§6). ADR-0193 §9's *"The user chooses the instant in
the establishing act"* is about `RecipientGrant` and is untouched. ADR-0250 §5's announcement
rule is untouched — the announcement this decision's instants ride is `TurnOutcome.authorizations`,
which ADR-0254 §11 already added beside §5's four members for its own stated reason. ADR-0148 §3's
route (a) is what §3 falls back to, unchanged. ADR-0247 §8(b)'s prospectivity is the shape §2's
read-once clause takes and is not moved.

**The record lands in the same change as this document** (ADR-0082 §7): ADR-0254's `Status`
qualifier is written with it and not after it, and **nothing else in ADR-0254 is edited** — no
Decision text is rewritten, which ADR-0070 §1 forbids.

### 8. What this ADR does not decide, by name, each with what fires it

> **Normative.** This decision settles nothing about the following, and no lane cites it toward
> any of them.

- **Whether a user-stated instant or a `Goal.deadline` may run past the window §1 reads.** §6
  leaves rungs 1 and 2 uncapped. Fired by a decision that would cap either, which must answer
  what ADR-0254 §11 shows a user whose stated instant was shortened — a question this rung does
  not have, because nobody stated its instant.
- **Asking the user for a horizon at the act.** ADR-0254 §19's booked decision, **still booked
  and still not taken**; this decision exists to make the question unnecessary in the ordinary
  case, not to answer it. Fired exactly as §19 says.
- **Coupling an authority's liveness to the actual lifecycle of its act's record.** §6 keeps a
  row standing when the act's episode lapses or its conversation is deleted; §1 states the one
  case in which the row outlives that episode at all, and refuses the row outright where the act
  is already older than the window. Fired by a decision that lands a
  cross-store read or deletion between this store and the conversation store — which ADR-0254
  §16's roster does not contain and §19 books next door.
- **Recording on the row which rung set its expiry.** §4 adds no member and forbids one. Fired by
  a surface that must state the *ground* rather than the instant, which would reopen ADR-0254
  §1's closed field list and needs that argument made.
- **Retention for the authorization store itself.** ADR-0254 §19's entry — issue #108's shape one
  store over — untouched. What happens to a **lapsed** row's storage is that decision's.
- **Whether an act naming only an instant may open or move a row.** §5 rules that it does not, on
  ADR-0254 §15's *"there is no fourth path"*. Fired by a decision that adds a write path, which
  is a change to ADR-0254 §1 and §15 rather than to this one.
- **Every other entry of ADR-0254 §19**, which stands exactly as written.

### 9. The lane cut, and the arms this decision owes

> **Normative.** **This decision cuts no lane of its own.** It changes one rung of a ladder
> ADR-0254 §20 already assigns: *"**Lane 2, the proposal, the settlement and the recheck** …
> writing a path-(ii) correction **and a path-(iii) opening act** … **taking §12's ladder**"*.
> Lane 2 takes the ladder as this decision leaves it, and **§5's narrowing is Lane 2's too**,
> being a rule of the path-(ii) write path. Lanes 1 and 3 are untouched.

> **Normative.** **No lane bumps the wire for this decision.** No `core` type gains a field, no
> member reaches the promoted surface and no wire-carried value changes shape, so ADR-0124 §9 is
> not engaged.

**Lane 2 owes the arms below for this decision**, each a representative-input test shipped with
it, and **each is a clause of its own** because each is separately satisfiable: a lane could ship
the ordinary case and omit the refusals, and ADR-0089 §2's *"A clause states one obligation"* is
what forbids joining them into one.

> **Normative.** **The ordinary case.** A finite `episode_retention`; a goal with no `deadline`;
> an act naming no instant → a row **is** written on path (i) and on path (iii), `expires_at`
> equals the row's basis instant advanced by that window, and the goal's **second** call inside
> the coverage reaches route (d) with **no `CONFIRM`**.

> **Normative.** **`episode_retention = None`.** The same inputs → **no row on either path**,
> `Confirmation.authorization` absent, route (a), and no deployment value read for anything else.

> **Normative.** **Rung 2 is not displaced.** A goal carrying a `deadline` takes rung 2 and the
> goal's own instant, though a finite window exists and would give a different one.

> **Normative.** **Rung 1 is not displaced and is not clamped.** An act naming an instant takes
> rung 1 **even where that instant is later than the window would give**, and the row carries it
> unshortened.

> **Normative.** **Prospectivity after the write.** Widen `episode_retention` between the write
> and a later read → the row's `expires_at` is **unchanged**, and a lapsed row is not revived.

> **Normative.** **The capture-to-write interval, which is the one divergence §1 admits.** Widen
> `episode_retention` between an act's capture and a path-(i) row's write → the row carries the
> window in force **at the write**, so it outlives that act's episode, and that is the ruled
> behaviour rather than a defect the lane repairs.

> **Normative.** **An older basis act shortens the row.** A path-(i) proposal whose coverage
> carries a member resting on a recorded turn materially older than the `CONFIRM` it rides →
> `expires_at` is **that turn's instant** advanced by the window, **not** `proposed_at` advanced
> by it, so the row expires strictly earlier than one resting on the confirming turn alone. The
> arm takes the **earliest** of several bases, not the latest and not the row's own instant.

> **Normative.** **An act older than the window writes no row.** A path-(i) proposal whose
> earliest basis act's instant advanced by the window is at or before `proposed_at` → **no row is
> written**, `Confirmation.authorization` is absent, route (a), and **no clamped, saturated or
> minimum-length instant is produced anywhere**.

> **Normative.** **An unresolvable basis act writes no row.** A row whose members are complete but
> the instant of some basis act cannot be resolved at the write → **no row is written**, route
> (a), and the lane does not substitute `proposed_at` for the instant it could not read.

> **Normative.** **An argument-free call takes `proposed_at`.** A path-(i) proposal about a call
> carrying no arguments, whose row carries `coverage=()` (ADR-0254 §11) → the rung takes
> `proposed_at` advanced by the window, there being no basis act to measure from.

> **Normative.** **A correction stating an earlier admissible instant narrows.** A path-(ii)
> correction whose span states an instant strictly after the new row's `proposed_at` and strictly
> before the superseded row's `expires_at` → **the new row carries that instant**.

> **Normative.** **A correction stating a later instant does not lengthen.** An instant at or
> after the superseded row's `expires_at` → `expires_at` **transcribed unchanged**.

> **Normative.** **A correction stating an instant already past does not narrow to it.** An
> instant at or before the new row's `proposed_at` → `expires_at` **transcribed unchanged**, and
> no row is written born expired.

> **Normative.** **An unsettled instant takes the earliest admissible reading.** A correction
> whose span admits more than one instant, two or more of them admissible → the new row carries
> **the earliest admissible** one, and **no question is raised**.

> **Normative.** **An unsettled instant none of whose readings is admissible changes nothing.** A
> correction whose span admits more than one instant, none of them inside the two bounds →
> `expires_at` **transcribed unchanged**, and **no question is raised**.

> **Normative.** **No fourth path.** A turn naming only an instant and correcting no argument →
> **no row written, none superseded, nothing moved.**

> **Normative.** **The arithmetic edge.** A clock reading for which the addition cannot be taken →
> **no row written**, route (a), and no clamped or saturated instant anywhere.

### 10. This ADR classified under ADR-0070 §1 and ADR-0082 §1

**A reader acts differently, so this is a decision and not a clarification.** A reader holding
the corpus without it writes no `Authorization` for any goal whose user named no horizon and
whose objective carried no date — which is the ordinary request — and refuses every movement of
`expires_at` on a correction. That is ADR-0070 §1's test met, and a new ADR is the instrument:
ADR-0254's Decision text may not be rewritten (ADR-0070 §1's append-only rule), and the change
reverses what one of its rungs instructs.

**It is a partial supersession of exactly one document** (ADR-0070 §3) — ADR-0254, in the seven
limbs §7 enumerates — and that document's `Status` line names the scope **without an `ADR-NNNN`
token inside the parentheses**, so ADR-0070 §4's extraction invariant holds and the line stays
one physical line.

### 11. Marking, review and ratification

**This ADR is marked** under ADR-0089: every obligation it imposes is a clause whose first line
begins `> **Normative.**` at column 0, preceded by a blank line and containing no fenced block,
which is §2's grammar exactly; unmarked text beside a mark is read to determine what the mark
means and supplies no obligation of its own. Quoted marks from other ADRs appear inside quotation
marks in running prose rather than as marks of this document.

**It owes both review lenses** — adversarial and architecture — on one tree. It decides the value
of a field on `core/types.py`'s contract surface and partially supersedes a contract ADR, and
ADR-0015 §1 makes that true of a prose-only PR.

**It merges as its own PR, ratified, before anything implements against it** (golden rule 5,
ADR-0015). It briefs no lane of its own; ADR-0254 §20's Lane 2 takes it, and the ratification
flip is one line and no other byte (ADR-0165).

## Consequences

**The ordinary request stops asking twice.** A goal with no date and a user who named no horizon
now establishes an authority on its first concrete call and reuses it on the second, which is the
owner's *"a defined way to establish an appropriate expiry once, rather than repeatedly confirming
actions"*. The mechanism ADR-0254 built stops working only for the requests that happen to carry
a date.

**The window is longer than most goals, and that is the trade.** A default `episode_retention` of
thirty days means an ordinary authority runs for thirty days rather than for the weekend it was
about — **thirty days from the act, not from the grant**, so a goal picked up again three weeks
later gets what is left of the window and not a fresh one. Three things bound what that costs
and each is already ratified: the coverage is narrow —
one goal, one declaration, one account, one destination set, fixed values and bounded ranges, and
**anything outside it asks** (ADR-0254 §6, §9 clause (iii)); the row is revocable at any moment
and its handle is put in front of the user **at the act** (§11); and a user who wants less says so
and is now heard (§5). What is **not** available is a deployment shortening it centrally with a
figure of its own, and that is deliberate.

**An operator's retention setting now has a second effect, and it is legible.** Shortening
`episode_retention` shortens new authorities; setting it to `None` stops them being written at
all. The second is the surprising one, and §3 states it rather than leaving a deployment to
discover it. It is also the honest direction: a deployment that keeps everything forever is not
one where an authority should quietly last forever. §7 limb 3 is the record that this is a real
change to what ADR-0254 decided, and not a reading of it.

**A correction can now move a field that was previously immutable**, in one direction. The
invariant ADR-0254 stated over corrections — none outlives the confirmation that began it —
survives strengthened rather than weakened, and the implementing lane owes arms in both
directions (§9) because a rule that only ever narrows is the one a refactor most easily inverts.

**An ambiguous instant on a correction now resolves where it used to be discarded**, to the
earliest reading the span admits inside the two bounds. That is a real change to what ADR-0254
§9 clause (iii) instructs and §7 limb 6 records it as one. It raises no question, because there
is nothing left ambiguous to ask about, and it can only ever leave less authority standing than
the transcription it replaces — but it does mean a user whose words admitted two Fridays gets the
first, and reads which one on the row.

**What would trigger revisiting this.** A deployment where `episode_retention` is routinely
`None` — at which point §3's withholding is the common case rather than the deliberate one, and
ADR-0254 §19's asking decision becomes worth taking. Or a retention decision for the authorization
store itself, which would give a row a horizon of its own and make §1's borrowed one a second
clock rather than the only one.

## Alternatives considered

**Ask the user for a horizon once, at the act.** ADR-0254 §19's booked decision. Rejected on the
owner's ruling: it is a second question at the moment this design exists to remove one, and it
reproduces the interruption for exactly the ordinary requests this decision is about. A user may
of course always state an instant, and rung 1 takes it — what is refused is *asking*.

**Keep ADR-0254 §12's rung 3 as it stands.** Rejected by the ruling, and the ADR's own text
admits the cost: *"every call of it asks"*. It survives as the ladder's last rung where no window
exists (§3), which is where the argument for it still holds.

**A figure minted for this record — a `Settings` field, or a constant in the ADR.** Rejected
twice over: §12 calls an operator's figure *"a clock the user never saw"* and ADR-0254 §20
requires *"no `Settings` field at all"*; and decision 7's *"justified"* could not be met by a
number nobody chose for this act. The distinction from what §1 does take is stated in §2 and is
the load-bearing one: this rung reads the window the **act's own record** is kept for, and the
respect in which that is nonetheless a deployment value is **recorded as a supersession** rather
than argued away.

**The conversation's own reclaim eligibility, rather than the act's window.** Rejected on two
grounds read off the tree: a conversation is reclaimable only when `last_active_at` is past the
horizon, and that stamp moves with every turn — so the instant would be a moving target §2's
read-once rule could not be stated over — and `PlanStore` carries no retention at all, so the
reclaim never reaches the goal in any case (ADR-0250 §13).

**The act's episode's own `expires_at`, read from the store.** Rejected because it does not exist
when the row is written on path (i): capture writes one episode per turn **outcome** (ADR-0074
§3), and a rung that fires on one of its two paths is not a rung of a total ladder. It would also
put a `MemoryStore` read on the write path of a permissions record, which ADR-0254 §16's roster
does not contemplate. **The line this decision draws is between two records, not between a record
and a computation**: the act's *recorded turn* is what §9 clause (i) already makes
`orchestration` resolve for every member, so its instant costs nothing; the act's *episode* is a
second record nothing on this path reads. The cost of not reading the episode is stated in §1 and
pinned by §9's capture-to-write arm rather than left for a reader to find.

**Taking the window from the row's own `proposed_at`.** This decision's own first draft, and
rejected on ADR-0254 §8's *"The basis is per member and never per record. Two members of one
record may name two different acts"*. A path-(i) proposal may carry members resting on acts far
older than the `CONFIRM` it rides, so a window measured from the write would hand a row written
on the twenty-ninth day of a thirty-day horizon a further thirty days of authority over an act
whose record dies the next day — the authority outliving its evidence by almost a full window,
which is exactly what §1 claims it does not do. Measuring from the **earliest** basis act costs
no new machinery, collapses the divergence to the single widened-window case, and turns the same
arithmetic into §1's refusal for an act already past the horizon.

**Asking the user which instant an ambiguous correction meant.** Rejected on the same ruling the
whole decision rests on — it is a second question at the moment this design exists to remove one,
and *"repeatedly confirming actions"* is what the owner ruled against. It is also the more
expensive answer to a question that has a safe one: the earliest admissible reading is the
narrowest available (§5), it can only leave less authority than transcription, and it is rendered
in the establishing row, in every listing afterwards and in `export` beside the act it was read
from — so the user can see which reading was taken and revoke it with the handle ADR-0254 §11
puts in front of them, rather than being asked before it is known whether they care.

**Discarding an ambiguous instant and transcribing the horizon unchanged**, which is ADR-0254 §9
clause (iii)'s *"not taken"* applied as it stands. Rejected because it drops the safety half of
the user's own sentence while landing the argument half: *"make it Sunday, and only until
Friday"* would move the date and leave the longer horizon standing. That is the failure this
corpus refuses everywhere it can see it, and refusing it here needed no new question and no new
type.

**Capping rungs 1 and 2 at the same window.** Rejected in §6: shortening an instant the user
named would make ADR-0254 §11 show them something other than what they said, which defeats the
very clause this decision satisfies, and a goal's `deadline` is the objective's own horizon rather
than a figure. §8 books it with what would fire it.

**Recording the rung on the row.** Rejected in §4: it reopens a field list ADR-0254 calls closed
and buys a phrase rather than a fact, when the instant is true whatever produced it.

**Letting a correction lengthen as well as shorten.** Rejected in §5: extending an authority is
the direction that needs the user to have been shown what they are extending, and ADR-0254 §1
already has the mechanism for it — a path-(i) proposal carrying `supersedes`, which *"renews an
authority whose expiry has passed as well as … widens a live one"*.

**Refusing a correction that names an instant it cannot take.** Rejected in §5: ADR-0254 §12 is
explicit that *"a correction is never refused for want of an instant it was never going to set"*,
and refusing the correction would lose the argument fix the user actually made.
