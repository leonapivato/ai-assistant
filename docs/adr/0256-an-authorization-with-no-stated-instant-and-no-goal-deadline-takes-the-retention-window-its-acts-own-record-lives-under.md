# 256. An authorization with no stated instant and no goal deadline takes the retention window its act's own record lives under

- Status: Partially superseded by ADR-0268 (one scope. **§1's bound clause, in the direction of the bound alone**, and with it this decision's title: *"**A row written on this rung is bounded by the turn-retention window in force at its own write, measured from `proposed_at`, and by nothing longer**"* stays true as an **upper** bound and stops being the horizon — such a row is ended by a closing act of its goal where one reaches it, and lapses on that instant where none does, the rung being the expiry of a row no closing act ends and of no other. A reader holding only this decision reads the window as when the authority ends, and would report a live authority over a request the user considers finished for the rest of it. **Every other clause binds entire and several are what the superseding decision rests on**: §1's rung and its `proposed_at`-only read, its no-new-reader rule and its illustrative list of rows that outlive an act's record; §2's `Settings`-gains-nothing rule, its read-once-and-never-recomputed clause and its fail-closed arithmetic; §3's keep-turns-forever case, which writes no row at all and is untouched; §4's rendering and its refusal of a `source` member on the row; §5's narrowing correction; and **§6 entire**, whose *"No row is moved, shortened or settled by anything that happens to the act's own record"* is stated over the **act's record** and is reached by no clause of that decision — what ends a row there is the **goal's** status, which is neither an episode nor a conversation — and whose `RecipientGrant` and configured-provider exclusions are likewise untouched. §§7-11 stand as they are)
- Date: 2026-09-12
- **Partially supersedes** [ADR-0254](0254-phase-4-validates-the-plan-in-code-and-route-d-authorises-a-concrete-call-against-fixed-values-and-permitted-ranges-from-recorded-acts.md)
  — **six limbs, all about one field, `Authorization.expires_at`.** **§12's ladder rung 3
  entire**, its *"no row at all"* and its *"Nothing is invented, nothing is defaulted and
  nothing falls back to a configuration"* included: where the recorded act states no instant and
  the goal carries no `deadline` **or carries one at or before `proposed_at`**, `expires_at` is
  now `proposed_at` advanced by the deployment's turn-retention window and a row **is** written,
  where that window is finite; with it **§1's fourth proposal condition**, *"§12's ladder yields
  an `expires_at` … There is no deployment figure to fall back on and none is invented"*, which
  governs path (iii) too, and **§20's arm 69 in its two rung-3 cases alone**, every other case of
  that arm standing verbatim (§1, §7).
  **§12's stated cost of that rung** — *"a goal carrying no `deadline` whose user stated no
  horizon has no route (d) at all, and every call of it asks"* — which is true only where that
  window is set to keep turns forever, and there the ratified rung stands verbatim as the
  ladder's last (§3). **§12's no-deployment-wide-expiry clause, in the single respect that the
  third rung reads one deployment value, `core.config.Settings.episode_retention`**, together
  with **§12's justification clause in its limb *"and in neither case by a deployment"***; every
  other limb of both stands, `Settings` gains nothing and no figure bounds rung 1 or rung 2 (§2,
  §7). **The path-(ii) transcription rule in all six places ADR-0254 states it** — §12's
  path-(ii) transcription clause, §1's path-(ii) *"transcribed unchanged"* list, §1's path-(i)
  *"the only path that may … set `expires_at`"*, §1's *"what path (ii) may change"* clause in its
  limb *"or move `expires_at`"*, §1's path-(ii) liveness clause in its reason limb *"because a
  correction transcribes the predecessor's `expires_at`"* — that limb alone, the live-row
  requirement itself untouched — and §5's *"`expires_at` is transcribed from the row it
  supersedes"* — **together with §20's arm 17 in its `expires_at` field alone and §20's arm 25
  in its *"carry one `expires_at`"* limb alone**, each in the `expires_at` limb and in the
  **narrowing direction alone** (§5). **§9 clause (ii)'s
  bar limb *"move `expires_at`"*, and §20's arm 20 which tests it***, in that same narrowing
  direction alone — arm 20 standing entire on its own terms, its subject being a widening.
  **§9 clause (iii)
  stands entire and no limb of it is superseded** — an instant a correction's span does not
  settle to one value is not taken and the user is asked, exactly as ratified (§5). And **§19's
  entry *"What the user is shown where §12's ladder yields no instant"***,
  **narrowed in application and not replaced** (§7). Every other clause of ADR-0254 §12 binds
  entire and several are what this decision rests on: no `Settings` **field**, the expiry per
  `Authorization` and shown when it is granted, no ceiling over rung 1 or rung 2, the expiry
  taken once and never recomputed, an answer arriving at or after it establishing nothing, the
  recipient-grant and configured-provider exclusions, the visible-at-the-act rule and the
  no-deletion rule. **§§1–11 and §§13–22 stand as they are, but for the limbs of §1, §5, §9, §19
  and §20 named above** — those five sections and §12 are the whole of what this decision
  reaches, and §7 is the inventory.

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
> (rung 2), `expires_at` is **`proposed_at` advanced by the deployment's turn-retention
> window** — `core.config.Settings.episode_retention` (ADR-0074 §7) — **where that window is
> finite**. The rung is taken **on paths (i) and (iii) alone and at the instant the row is
> written**, which is ADR-0254 §12's own rule for the ladder; **path (ii) takes none of the
> ladder**, and §5 below is the one motion a correction may make on this field.

> **Normative.** **The rung reads `proposed_at` and no other instant of any record, and this
> decision adds no reader to any store.** It does not read an episode's stamp, a conversation's
> `last_active_at`, or the `occurred_at` of the recorded turn any coverage member's basis names.
> `proposed_at` is already on the row being written — ADR-0254 §1 makes it the recorded
> `CONFIRM`'s `decided_at` on path (i) and the recorded turn's instant on path (iii) — so the
> rung is arithmetic over one value in hand and one `Settings` duration, and **no store, seam,
> field, type, member or cross-store contract is added for it**. The title of this decision names
> the **window** the act's own record is kept for, which is a duration; it does not claim that
> the row and any particular record expire together, and the bound clause below is what it does
> claim.

**The window, and not the act's episode's own stamp, and the reason is that the stamp is not
reachable.** ADR-0074 §3 captures one `EpisodicMemory` per turn *outcome*, so on path (i) — where
`proposed_at` is the recorded `CONFIRM`'s `decided_at` — the episode of the turn the act rode may
not have been written when the row is. A rung that could not be taken on one of its two paths
would not be a rung of a total ladder, and reading one would put a `MemoryStore` read on the
write path of a permissions record, which ADR-0254 §16's roster does not contemplate. **The same
answer disposes of the recorded turn's own `occurred_at`, which is a second record and not a
value in hand**: ADR-0254 §8 closes `AuthorizationBasis` at `act`, `span` and `resolution`, so a
basis names a turn and carries no instant of it; `TurnResult` carries the utterance §9 clause (i)
checks a span against and no instant either; and the only place the instant exists is
`ConversationTurn.occurred_at`, reachable through `ConversationStore.turn_of_episode` — a second
store read on the write path of a permissions record, with its own absent-versus-failed
distinction to rule on. **That read is not minted here** (`Alternatives considered`), and §8
books what would fire a decision that mints it. So the row takes the **same window** as the act's
record, measured from the row's own instant.

> **Normative.** **The bound, which is what this rung guarantees, and it is not a coincidence.**
> **A row written on this rung is bounded by the turn-retention window in force at its own write,
> measured from `proposed_at`, and by nothing longer. No clause of this decision asserts that the
> row and the record of any act it rests on expire together, and a row may outlive such a
> record.** It does so, among other ways, where the row rests on an act older than the write —
> ADR-0254 §8 makes the basis **per member**, so a path-(i) proposal may carry a member resting on
> an earlier turn and the row then outlives that act's episode by the act's age; where
> `episode_retention` was **widened** between an act's capture and the row's write; where the
> clock **moved backwards** before an episode was captured, which ADR-0254 §1 admits in terms
> (*"the clock can move backwards — an operator correction, an NTP step"*); and immediately, where
> the **user deleted** the episode or its conversation under ADR-0074 §8, which §6 rules leaves
> the row standing. **That list is illustrative and the bound is the rule**: nothing here is
> repaired and nothing is hidden — §4's rendering shows the instant the row actually carries, §9's
> arms pin the cases above, and §8 books the decision that would couple an authority's liveness to
> the record of its act.

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
the basis carries is what stops pointing at anything. So the claim this rung makes is about the
**duration** and not about a coincidence of instants: an authority lasts no longer than this
deployment keeps a recorded turn, and where it rests on an act older than the grant it can
outlive that act's record by the act's age — which the bound clause above states, §9's arm pins,
and §8 books for the decision that would close it.

**It is shorter than the reclaim of the conversation the row is written in, which is the
fail-closed direction.** That conversation is reclaimed only when it has no live turns **and**
`last_active_at` is past the horizon, and `last_active_at` is at or after the instant of the turn
this row is written against — so it survives at least as long as this rung's answer and usually
far longer. **The comparison is stated over that conversation and no other**: a row resting on a
member whose act belongs to an earlier conversation says nothing about *that* conversation's
reclaim, which the bound clause above is what governs. Taking the window rather than the
conversation's eligibility also keeps the instant **fixed**: the conversation's is a moving
target, and §2's read-once rule could not be stated over one.

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

> **Normative.** **The arithmetic is fail-closed, and where it cannot be taken no row is
> written.** `episode_retention` is refused at load unless it is strictly positive, so a horizon
> taken from it is **strictly after** `proposed_at` and ADR-0254 §1's construction refusal never
> fires on this rung. Where the addition cannot be taken at all — a clock reading near
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
> standing. **A span that states an instant it does not settle to one value is not the first
> case**: ADR-0254 §9 clause (iii) reaches it first, and the clause below says so.

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

> **Normative.** **An instant a correction's span does not settle to one value is ADR-0254 §9
> clause (iii)'s, entire, and this decision changes nothing about it.** Where the span admits
> more than one admissible instant, *"the resolution is **not taken** and no member is minted
> from it: the user is asked, by **ADR-0250 §6's three conditions and no fewer**"* — both halves,
> unqualified. `expires_at` is then transcribed unchanged, which is ADR-0254 §12's path-(ii)
> clause standing, and **whether a question is raised is §6's test and not this decision's**.
> **No limb of clause (iii) is superseded, narrowed or suppressed anywhere in this decision**,
> and §7 records nothing against it.

> **Normative.** **Nothing here enumerates a reading, orders a set of them, or takes a value from
> a model.** The narrowing in the first clause fires only where §10's resolutions settle the span
> to **one** instant, which is the same total function rung 1 takes; this decision adds no
> candidate set, no carrier for one and no rule for generating one, so ADR-0250 §7's
> `ProposedQuestion` is untouched and ADR-0254 §9's *"a value a model wrote into a durable audit
> chain is unprovenanced"* is never reached for. §8 books the decision that would take an
> unsettled instant without a question, with what fires it.

**Which span, and how a horizon is told from a date the same sentence sets: both questions are
ADR-0254's, and neither is minted here.** The span is the correcting **turn's** — the one
ADR-0254 §1's path-(ii) clause names, *"A later recorded turn of the same goal whose span names
an argument a **live** row of that goal already carries a member for"* — and not a coverage
member's basis span of the act that established the row. Telling *"only until Friday"* from the
date the same sentence sets on an argument is **rung 1's** question, and ADR-0254 §12 answers it
for path (i): rung 1 is *"the instant the user's own act states, where the recorded act states
one and §10's resolutions take it … resolved by `DATE_FROM_CONTEXT` or `AS_STATED` under §9's
clauses entire"*. A correction reads its own span by that reading and no other, so a turn stating
dates for several arguments and a horizon is read exactly as the same turn would be on path (i):
where that reading yields no horizon the first clause does not fire and `expires_at` is
transcribed unchanged, and where it yields more than one admissible instant §9 clause (iii)
reaches it first. **This decision mints no expiry-span carrier, no provenance for one and no rule
for generating one** — `Alternatives considered` records the draft that did and why it is not
taken, and §8 books what would fire it.

**Why the unsettled case is left exactly where ADR-0254 put it.** An earlier draft of this
decision took the **earliest admissible** reading of an unsettled instant and put no question,
on the argument that the earliest is the narrowest and so the fail-closed choice. The argument
about direction is sound and the rule is not implementable: the corpus gives `orchestration` a
**predicate** — §9 clause (iii)'s *"the span admits more than one admissible value"*, reported
by the planner under ADR-0250 §6 — and never a **set**, so there is nothing to take a minimum
over. Building one would mean deriving candidate instants from model-written prose and writing
the least of them into a durable authority, which is precisely what ADR-0254 §9's no-model-output
clause forbids in terms, and some spans admit readings with no earliest member at all. So the
unsettled case stays §9 clause (iii)'s, and what this decision narrows is only the case §10's
resolutions **do** settle — which is the case the owner's *"make it Sunday, and only until
Friday"* actually presents. What the correction does to the coverage is unaffected either way:
ADR-0254 §12's *"a correction is never refused for want of an instant it was never going to
set"* binds entire, and the user's own act for ending an authority outright is still
`revoke_authorization` (ADR-0254 §11), which this decision does not re-spell.

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
> (§1). It reads no episode's stamp, no conversation's `last_active_at` and no recorded turn's
> `occurred_at`, and §8 books the decision that would read the last of those.

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
   a configuration"*. **With it, §1's fourth proposal condition** — *"**§12's ladder yields an
   `expires_at`** — the act states an instant, or the goal carries a `deadline` strictly after
   `proposed_at`. **There is no deployment figure to fall back on and none is invented**"*,
   which §1 makes govern **path (iii) too** and whose failure is *"no row is proposed"*. It
   enumerates the ladder's first two rungs as the whole of it and denies the fallback this
   decision takes, so it is the same supersession stated in a second place and is
   **superseded on the same narrowing** — a third case now satisfies it, and the figure is not
   invented but read (§2). And with both, **§20's arm 69** in its two rung-3 cases alone — *"An
   act naming none on a goal carrying **no** `deadline`, and one carrying a `deadline` at or before
   `proposed_at` → **no path-(i) proposal and no path-(iii) row is written** … one test each"* —
   which a lane must now ship as §9's arms instead — **two of them, one per case**, matching arm
   69's own *"one test each"*: §9's ordinary-case arm for a goal carrying no `deadline`, and its
   stale-or-equal-`deadline` arm for one carrying a `deadline` at or before `proposed_at`. A
   reader holding only ADR-0254 writes no row for a deadline-free goal **and none for a goal whose
   `deadline` is at or before `proposed_at`**, and ships a test asserting each; after this
   decision they write one in **both** cases wherever the turn-retention window is finite, which
   is the default. **Superseded wherever `episode_retention` is finite — which is its shipped
   default — and not otherwise**: the ratified rung and its no-row outcome survive **verbatim** in
   the one case where `episode_retention` is `None`, and there alone (§1, §3). **Every other case
   of arm 69 stands verbatim**: rung 1's, rung 2's, its path-(ii) case — *"a live row with an
   explicit future `expires_at` on a goal carrying **no** `deadline`, corrected by 'make it
   Sunday' naming no horizon → the correction **is written**, transcribing that `expires_at`
   unchanged"*, which §5 leaves untouched because that correction's span states no instant — its
   `deadline`-edited-after-the-write case, its `Settings` roster test and its recipient-grant and
   configured-provider limbs.
2. **§12's stated cost.** *"a goal carrying no `deadline` whose user stated no horizon has no
   route (d) at all, and every call of it asks"*. Over-wide as it stands: true only under a
   deployment that keeps turns forever. **Superseded in scope, and verbatim where §3 fires.**
3. **§12's no-deployment-wide-expiry clause, and §12's justification clause's limb *"and in
   neither case by a deployment"*.** A reader holding only ADR-0254 reads no deployment value
   for an expiry at all. **Superseded in the single respect that §1's rung reads
   `episode_retention`**, and in no other: `Settings` gains nothing, the expiry stays per
   `Authorization` and shown when granted, and no figure bounds rung 1 or rung 2 (§2, §6).
4. **The path-(ii) transcription rule, in all six places ADR-0254 states it, and the two arms
   that test it.** §12's path-(ii) transcription clause; §1's path-(ii)
   *"`expires_at` … transcribed unchanged"*; §1's path-(i) *"the only path that may … set
   `expires_at`"*; **§5's
   *"`expires_at` is transcribed from the row it supersedes"***; **§1's *"what path (ii)
   may change, and what it may never touch"* clause, in its limb *"or move `expires_at`"***,
   which is the flattest statement of the rule and would on its own refuse the narrowing; and
   **§1's path-(ii) liveness clause, in its reason limb *"because a correction transcribes the
   predecessor's `expires_at`"*** — **that limb alone and not the requirement it explains**. The
   requirement stands entire and is untouched: a correction still supersedes a **live** row only,
   which §5's own bound restates, the narrowed instant having to be strictly before the superseded
   row's `expires_at` and strictly after the new row's `proposed_at`. Each of the six states the
   same rule, and any one of them left standing would refuse the narrowing. With them, **§20's
   arm 25** — *"Three successive superseding records carry **one** `expires_at`"* — **in that
   limb alone**, a chain that narrows carrying two or three; arm 25's own headline, *"A chain of
   corrections does not outlive the first act's expiry"*, and its *"the third covers nothing
   after it"* both stand and hold **a fortiori**. And **§20's arm 17** — *"`goal`, `tool`,
   `account`, `destinations` and `expires_at` altered on an otherwise valid superseding
   record → the store refuses the transcription, one test per field"* — **in its `expires_at`
   field alone**, which a lane must now test as an acceptance for a narrowing and a refusal for
   everything else (§9). A reader holding only ADR-0254 refuses every movement of that field on
   a correction and ships a test asserting the refusal. **Superseded in the `expires_at` limb of
   each and in the narrowing direction alone** (§5); the widening direction, the rest of each
   list — `goal`, `tool`, `account`, `destinations`, `origin` — arm 17's other four fields, §5's
   *"A path-(ii) correction never extends authority in time"* headline and its *"No sequence of
   corrections outlives the confirmation that began it"*, and the whole of path (ii)'s
   carry-forward rule all stand entire.
5. **§9 clause (ii)'s bar limb *"move `expires_at`"*, and §20's arm 20 which tests it.**
   **Superseded in the narrowing direction alone** (§5), on that clause's own stated principle.
   Arm 20 — *"An interpretation that would widen — … a moved `expires_at` → each **refused at
   construction**"* — **stands entire on its own terms**, its subject being a widening, and is
   named here only because a lane reading *"a moved `expires_at`"* as *any* move would fail the
   narrowing §5 requires; read that way it is superseded in the same direction and in no other.
   Clause (i) and the no-model-output rule stand entire.
6. **§19's entry *"What the user is shown where §12's ladder yields no instant"*.** **Narrowed in
   application and not replaced.** The entry books a decision — *"a decision that would ask
   'until when?' at the act"* — and **this is not that decision and does not take it**. What
   changes is the entry's premise: the case now arises only where §3 fires, not for every
   deadline-free goal. A reader holding only §19 would read the booking more widely than it now
   holds, so the record is owed; the booking itself stands open.

**ADR-0254 §9 clause (iii) is relied on and not amended**, and it is worth saying so here
because an earlier draft of this decision did record a limb against it. It binds entire: for
every coverage member, for a consequence outside scope, and — under §5 — for an instant a
correction's span does not settle, both its *"not taken"* half and its *"the user is asked"*
limb. §5 narrows only the case §10's resolutions settle to one value, which clause (iii) does
not reach.

**Every other ADR this decision touches is relied on, not amended, and ADR-0074 §7 is the one to
test because it is where the window comes from.** Its word *"**dedicated**"* is stated of the
**field** and against a named alternative — §7's reason is that `confirmation_ttl` *"is the right
*shape* to copy and the wrong default to inherit"*, so `episode_retention` is *"Its own field,
with its own default"* — and it says nothing about which subsystems may **read** the value. Every
clause of §7 stays true word for word: episodes still carry a finite `expires_at` stamped at
capture, the default is still finite, `None` still means keep forever and is still available only
by the user setting it, expiry is still enforced at read time and reclaimed by `purge_expired`,
and the stated cost — *"a conversation whose turns have passed the horizon continues with no
history"* — is untouched. `Settings` gains nothing (§2), no default moves, and **no `memory`
module, no `MemoryStore` and no episode record is read** for this rung (§1): what is read is one
duration on `core.config.Settings`, which is how every subsystem reads configuration. So a reader
holding only ADR-0074 acts no differently and reads no clause of it more widely than it now
holds — ADR-0070 §1's test is not met and no record is owed against it. What **does** become
over-wide is a clause of **ADR-0254**, its *"there is no deployment-wide expiry, and
`core.config.Settings` gains nothing"*, and limb 3 above is that record. **The borrowing is
deliberate and is decision 4's**: the window is taken rather than minted precisely so that no
figure of the permissions layer's own exists to be set, which is what ADR-0254 §12's *"An
operator's figure is a clock the user never saw"* asks for (§1, §2).

ADR-0193 §9's *"The user chooses the instant in the establishing act"* is about `RecipientGrant`
and is untouched. ADR-0250 §5's announcement
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
- **Coupling an authority's liveness to the actual lifecycle of its act's record, and reading
  any instant of that record.** §6 keeps a row standing when the act's episode lapses or its
  conversation is deleted, and §1's bound clause states that the row may outlive such a record
  rather than claiming it does not. The same entry books **reading a basis act's own
  `occurred_at`** — through `ConversationStore.turn_of_episode`, the only place it exists — so
  that a row could be bounded by the horizon of the oldest act it rests on instead of by its own
  write; that decision must rule on absent-versus-failed for the read and on what a lane does
  with each. Fired by a decision that lands a
  cross-store read or deletion between this store and the conversation store — which ADR-0254
  §16's roster does not contain and §19 books next door.
- **Recording on the row which rung set its expiry.** §4 adds no member and forbids one. Fired by
  a surface that must state the *ground* rather than the instant, which would reopen ADR-0254
  §1's closed field list and needs that argument made.
- **Retention for the authorization store itself.** ADR-0254 §19's entry — issue #108's shape one
  store over — untouched. What happens to a **lapsed** row's storage is that decision's.
- **Taking an instant a correction's span does not settle, without putting a question.** §5
  leaves that case entirely to ADR-0254 §9 clause (iii) — not taken, and the user asked under
  ADR-0250 §6's three conditions — because the corpus carries a predicate for ambiguity and
  never a set of candidate readings, and building one out of model-written prose is what §9's
  no-model-output clause forbids. Fired by a decision that authorises a typed carrier for
  candidate instants, which must say what makes the set finite, what orders it, and how a value
  taken from it is provenanced. That is a change to ADR-0254 §9 and ADR-0250 §7 rather than to
  this one.
- **Whether an act naming only an instant may open or move a row.** §5 rules that it does not, on
  ADR-0254 §15's *"there is no fourth path"*. Fired by a decision that adds a write path, which
  is a change to ADR-0254 §1 and §15 rather than to this one.
- **Every other entry of ADR-0254 §19**, which stands exactly as written.

### 9. The lane cut, and the arms this decision owes

> **Normative.** **This decision cuts no lane of its own and splits its work across the two
> ADR-0254 §20 already assigns.** It changes one rung of a ladder §20 gives Lane 2 — *"**Lane 2,
> the proposal, the settlement and the recheck** … writing a path-(ii) correction **and a
> path-(iii) opening act** … **taking §12's ladder**"* — so **Lane 2 takes the ladder as this
> decision leaves it, computes the narrowed instant on a path-(ii) correction and submits the
> row**. **Lane 3 is untouched.**

> **Normative.** **The store half is Lane 1's, because §20 puts the store there and a contract is
> landed once.** ADR-0254 §20 assigns `GoalAuthorizationStore`, its shared conformance suite and
> `SqliteGoalAuthorizationStore` to **Lane 1**, and §5's narrowing changes what `record` refuses.
> **Lane 1 therefore owns the revised refusal, its conformance arm and every implementation of
> it** — on a **path-(ii) row alone**, one written `ESTABLISHED` directly with `confirmation`
> unset and `supersedes` set: accept it where its `expires_at` is strictly after its own
> `proposed_at` and strictly before the superseded row's, refuse every other movement of that
> field and every movement of the other five. **A path-(i) proposal carrying `supersedes` is
> untouched by this and by the transcription rule it narrows**: ADR-0254 §1 lets it set
> `expires_at`, §5 has it *"compute a fresh `expires_at`"*, and it may therefore carry a **later**
> instant than the row it names, which is what renews an authority. **Lane 2 owns computing the
> instant and submitting such a row**. Splitting it the other way would land a validation rule in
> the lane that does not own the validator, which is the drift ADR-0254 §16's roster-and-lane
> pairing exists to prevent. **§20's lane cut is not superseded by this**: Lane 1 still owns the
> store and Lane 2 still owns the write path, and what moves is only the content of Lane 1's arm
> 17 (§7 limb 4).

> **Normative.** **No lane bumps the wire for this decision.** No `core` type gains a field, no
> member reaches the promoted surface and no wire-carried value changes shape, so ADR-0124 §9 is
> not engaged.

> **Normative.** **One Protocol's behavioural contract does change, and it is flagged as
> breaking under golden rule 5.** `GoalAuthorizationStore.record`, which ADR-0254 §16 puts on
> `core/protocols.py`, is defined there to refuse a superseding row whose `expires_at` was
> altered, and §20's arm 17 tests that refusal. After §5 it must **accept** exactly one such
> alteration — the narrowing — and refuse every other. **No member is added, removed or
> re-signed, and no argument or return type changes**; what changes is the refusal the
> implementation and its conformance suite assert. ADR-0254's own lane cut lands that store, so
> **the change is to a contract that has not yet been written** and is carried by Lane 1's two
> arms below rather than by a migration; the flag is owed regardless, and this clause is it.

**The arms below are owed for this decision, and each names the lane that owes it.** **Lane 1**
owes the two that are about what `GoalAuthorizationStore.record` accepts and refuses — they are
its conformance suite's, because §20 puts the store, its suite and
`SqliteGoalAuthorizationStore` there — and **Lane 2** owes every other, they being about the
instant `orchestration` computes and the behaviour a turn then shows. Together they **replace
ADR-0254 §20's arm 69 in its two rung-3 cases and its arm 17 in the `expires_at` field alone**
(§7 limbs 1 and 4); every other case of both stands and is still owed by the lane that already
owes it. Each is a representative-input test shipped with it, and **each is a clause of its
own** because each is separately satisfiable: a lane could ship the ordinary case and omit the
refusals, and ADR-0089 §2's *"A clause states one obligation"* is what forbids joining them into
one.

> **Normative.** **The ordinary case.** A finite `episode_retention`; a goal with no `deadline`;
> an act naming no instant → a row **is** written on path (i) and on path (iii), `expires_at`
> equals `proposed_at` advanced by that window, and the goal's **second** call inside the
> coverage reaches route (d) with **no `CONFIRM`**.

> **Normative.** **`episode_retention = None`.** The same inputs → **no row on either path**,
> `Confirmation.authorization` absent, route (a), and no deployment value read for anything else.

> **Normative.** **Rung 2 is not displaced.** A goal carrying a `deadline` **strictly after
> `proposed_at`**; an act naming **no** instant → rung 2 is taken and the row carries the goal's
> own instant, though a finite window exists and would give a different one.

> **Normative.** **A stale or equal `deadline` reaches rung 3, not rung 2.** A finite
> `episode_retention`; a goal carrying a `deadline` **at or before `proposed_at`**; an act naming
> no instant → rung 2 does **not** take that `deadline`, rung 3 fires, and a row **is** written on
> path (i) and on path (iii) with `expires_at` equal to `proposed_at` advanced by the window —
> which is the second of the two cases §7 limb 1 records against ADR-0254 §20's arm 69, and the
> one an implementation keeping the old no-row behaviour would otherwise still pass.

> **Normative.** **Rung 1 is not displaced and is not clamped.** An act naming an instant takes
> rung 1 **even where that instant is later than the window would give**, and the row carries it
> unshortened.

> **Normative.** **Prospectivity after the write, widening.** Widen `episode_retention` between
> the write and a later read → the row's `expires_at` is **unchanged**, and a lapsed row is not
> revived.

> **Normative.** **Prospectivity after the write, shortening.** **Shorten** `episode_retention`
> between the write and a later read → the row's `expires_at` is **unchanged** and its liveness
> is decided on the instant it was written with, not on `proposed_at` advanced by the current
> setting. The arm exists because an implementation recomputing `min(stored, proposed_at +
> current)` passes the widening arm and fails this one, and §2's read-once clause is stated over
> **a later change** in either direction.

> **Normative.** **The capture-to-write interval.** Widen `episode_retention` between an act's
> capture and a path-(i) row's write → the row carries the window in force **at the write**, so
> it outlives that act's episode, and that is the ruled behaviour rather than a defect the lane
> repairs.

> **Normative.** **A clock rollback before capture.** Move the injected clock backwards between an
> act's turn and that act's episode capture, with `episode_retention` unchanged **and the
> proposal's `proposed_at` read strictly after the capture's own reading** → the episode is
> stamped from the earlier reading and the row outlives it, which is again §1's bound and not a
> defect. **The proviso is part of the arm and not scenery**: the clock may move backwards again
> before the write, and where `proposed_at` is read **equal to** the capture's reading the two
> expire together, and where it is read **earlier** the row expires first — both of which §1's
> bound permits, it being a bound and not an equality. Nothing in the row is clamped, re-stamped
> or recomputed in any of the three cases.

> **Normative.** **An older basis act does not shorten the row, and the row then outlives that
> act's record.** A path-(i) proposal whose coverage carries a member resting on a recorded turn
> materially older than the `CONFIRM` it rides — an act retained but near its own horizon →
> `expires_at` is **`proposed_at`** advanced by the window, unshortened, so the row stands after
> that act's episode has lapsed. That is §1's bound clause and the ruled behaviour, **not** a
> defect the lane repairs and **not** a case in which the lane reads the act's own `occurred_at`.

> **Normative.** **A deleted act leaves the row exactly as it stands.** Delete the act's episode,
> or its whole conversation, under ADR-0074 §8 → the row keeps the `expires_at` it was written
> with, stays live until that instant, and is settled by nothing (§6). No sweep, no reclaim and
> no cross-store deletion touches it.

> **Normative.** **Lane 2. A correction stating an earlier admissible instant narrows.** A
> path-(ii) correction whose span states an instant strictly after the new row's `proposed_at` and
> strictly before the superseded row's `expires_at` → **the new row carries that instant**.

> **Normative.** **Lane 1. The store accepts exactly that row.** A path-(ii) row — written
> `ESTABLISHED` directly, `confirmation` unset, `supersedes` set — whose `expires_at` is strictly
> after its own `proposed_at` and strictly before the superseded row's → **`record` accepts it**,
> where ADR-0254 §20's arm 17 refused every altered `expires_at`. The arm belongs to the shared
> conformance suite, so every implementation answers it.

> **Normative.** **Lane 1. The store refuses every other movement of a transcribed field on a
> path-(ii) row, exactly as before.** A path-(ii) row altering `goal`, `tool`, `account` or
> `destinations` → **refused**, one test per field, which is ADR-0254 §20's arm 17 standing entire
> in its other four fields; one altering **`origin`** → **refused** too, on ADR-0254 §1's
> path-(ii) transcription list, which names `origin` where arm 17 does not; and one altering
> `expires_at` in any direction but the single narrowing §5 permits → **refused**. **A path-(i)
> proposal carrying `supersedes` is not this arm's subject and is refused by none of it**: it may
> set `expires_at` to an instant later than the row it names (ADR-0254 §1, §5), and an
> implementation that applied the path-(ii) rule to it would break renewal.

> **Normative.** **A correction stating a later instant does not lengthen.** An instant at or
> after the superseded row's `expires_at` → `expires_at` **transcribed unchanged**.

> **Normative.** **A correction stating an instant already past does not narrow to it.** An
> instant at or before the new row's `proposed_at` → `expires_at` **transcribed unchanged**, and
> no row is written born expired.

> **Normative.** **A chain narrows against the row it supersedes, not against the first.** A
> first correction narrows the horizon; a second states an instant strictly after the narrowed
> row's `expires_at` and strictly before the original's → `expires_at` **transcribed unchanged**,
> the bound being the **superseded** row's instant and never the chain's first. The arm exists
> because an implementation comparing against the first row's `expires_at` passes every
> single-correction arm above and lengthens on the second, and because §7 limb 4 supersedes
> ADR-0254 §20's arm 25 in its *"carry **one** `expires_at`"* limb alone — that arm's own
> *"A chain of corrections does not outlive the first act's expiry"* standing and holding a
> fortiori is what this pins.

> **Normative.** **An unsettled instant is ADR-0254 §9 clause (iii)'s and is not narrowed.** A
> correction whose span admits more than one admissible instant → the resolution is **not
> taken**, `expires_at` **transcribed unchanged**, and whether a question is raised is ADR-0250
> §6's three conditions and **not** a rule of this decision. The arm exists to pin that this
> decision's narrowing does **not** fire on an unsettled span.

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

**It is a partial supersession of exactly one document** (ADR-0070 §3) — ADR-0254, in the six
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
of a field on `core/types.py`'s contract surface, changes the behavioural contract of one
`core/protocols.py` member — `GoalAuthorizationStore.record`'s refusal of an altered
`expires_at` (§9) — and partially supersedes a contract ADR. **That Protocol change is breaking
under golden rule 5 and is flagged here as well as in §9**, and ADR-0015 §1 makes the both-lens
requirement true of a prose-only PR.

**It merges as its own PR, ratified, before anything implements against it** (golden rule 5,
ADR-0015). It briefs no lane of its own; ADR-0254 §20's **Lane 1 and Lane 2** take it between
them as §9 partitions, and the ratification
flip is one line and no other byte (ADR-0165).

## Consequences

**The ordinary request stops asking twice.** A goal with no date and a user who named no horizon
now establishes an authority on its first concrete call and reuses it on the second, which is the
owner's *"a defined way to establish an appropriate expiry once, rather than repeatedly confirming
actions"*. The mechanism ADR-0254 built stops working only for the requests that happen to carry
a date.

**The window is longer than most goals, and that is the trade.** A default `episode_retention` of
thirty days means an ordinary authority runs for thirty days rather than for the weekend it was
about, counted from the grant — so a goal picked up again three weeks later, on acts three weeks
old, gets a fresh window rather than what is left of theirs (§1's bound clause, §8's booking).
Three things bound what that costs and each is already ratified: the coverage is narrow —
one goal, one declaration, one account, one destination set, fixed values and bounded ranges, and
**anything outside it asks** (ADR-0254 §6, §9 clause (iii)); the row is revocable at any moment
and its handle is put in front of the user **at the act** (§11); and a user who wants less says so
and is now heard (§5). What is **not** available is a deployment shortening it centrally with a
figure of its own, and that is deliberate.

**An operator's retention setting now has a second effect, and it is legible — but it reaches
§1's rung and nothing above it.** Shortening `episode_retention` shortens new authorities **that
take rung 3**; setting it to `None` stops **those** being written at all. It bounds neither of
the rungs above: an act that states an instant takes rung 1 unclamped and a goal carrying a
`deadline` strictly after `proposed_at` takes rung 2, under any setting and under `None` as well,
so an operator cannot shorten or stop an authority the user's own act or the goal's own horizon
bounds (§1, §2, §6). That is the ratified direction and not an oversight: ADR-0254 §12 refuses a
deployment figure over an instant the user was shown, and §2 keeps that refusal entire. The
`None` case is the surprising one, and §3 states it rather than leaving a deployment to discover
it. It is also the honest direction: a deployment that keeps everything forever is not
one where an authority should quietly last forever. §7 limb 3 is the record that this is a real
change to what ADR-0254 decided, and not a reading of it.

**A correction can now move a field that was previously immutable**, in one direction. The
invariant ADR-0254 stated over corrections — none outlives the confirmation that began it —
survives strengthened rather than weakened, and the implementing lane owes arms in both
directions (§9) because a rule that only ever narrows is the one a refactor most easily inverts.

**A user whose words the system cannot settle is still asked, and that is deliberate rather than
left over.** The narrowing fires only where ADR-0254 §10's resolutions settle the span to one
instant; where they do not, §9 clause (iii) binds entire and nothing here touches it. So *"only
until Friday"* shortens the horizon when there is one Friday to take and reaches §9 clause (iii)
when there are two, which is the same treatment the corpus already gives every other value a
user states. §8 books the decision that would take an unsettled instant without a question and
says what it would have to supply first.

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
does not contemplate. **And resolving a basis is not the same as reading a record's instants**:
ADR-0254 §9 clause (i) makes `orchestration` resolve a member's act and the span inside that
turn's stored utterance, and **neither that resolution nor anything else on this path yields an
instant** — not the episode's stamp, and not the turn's own `occurred_at`, which the alternative
below rejects separately and for its own reasons. The cost of not reading the episode is stated
in §1's bound clause and pinned by §9's capture-to-write arm rather than left for a reader to
find.

**Measuring the window from the earliest recorded turn the row's coverage rests on, rather than
from `proposed_at`.** A draft of this decision did that, to bound the row by the horizon of the
oldest act it stands on: ADR-0254 §8 makes the basis **per member**, so a path-(i) proposal
written on the twenty-ninth day of a thirty-day horizon may rest on an act whose episode dies the
next day, and a window measured from the write gives that row a further thirty days. **Rejected
because the instant is not a value this decision has, and reaching it is a decision of its own.**
`AuthorizationBasis`'s field list is closed at `act`, `span` and `resolution` (ADR-0254 §8), so a
basis names a turn and carries no instant of it; the utterance §9 clause (i) checks a span
against, `TurnResult`, carries none either; and the instant exists only as
`ConversationTurn.occurred_at`, reachable through `ConversationStore.turn_of_episode`. Taking it
would put a **second store read on the write path of a permissions record** — one ADR-0254 §16's
roster does not contemplate — and would oblige this ADR to rule on that read's
absent-versus-failed distinction and to arm both. That is a larger decision than one rung's
value, so §1 states the **bound** it can actually guarantee, §9 arms the case, and §8 books the
decision that would read the instant. The honest form of the claim is that an authority lasts no
longer than this deployment keeps a recorded turn, counted from the grant — not that it dies with
any particular record.

**Taking the earliest admissible reading of an instant the span does not settle, and putting no
question.** A draft of this decision did exactly that, on the argument that the earliest reading
is the narrowest and therefore the fail-closed one. **Rejected because it is not implementable
from anything the corpus carries.** ADR-0254 §10's three resolutions are total functions yielding
one value or no resolution; §9 clause (iii) recognises that a span *may* admit more than one and
never enumerates them; and ADR-0250 §7's `ProposedQuestion` carries only `text` and a
whole-element `about`. So there is no set to take a minimum over, the only place candidate
instants could come from is model-written prose, and ADR-0254 §9's no-model-output clause forbids
a value a model wrote reaching a durable authority — *"a value a model wrote into a durable audit
chain is unprovenanced"*. Some spans admit readings with no earliest member in any case. §8 books
the decision, with what it would have to supply.

**Suppressing the question for an ambiguous instant while transcribing the horizon unchanged.**
An earlier draft of this decision did that instead, so that no second question was put on a
correction. **Rejected on both halves.** It is not decidable from the contract — `about` names a
whole goal element, so `orchestration` cannot tell an expiry-only ambiguity from a coverage one
without reading the model's question text, which is the reading ADR-0254 §9 forbids. And it runs
the wrong way on safety: it would drop the restricting half of *"make it Sunday, and only until
Friday"* while landing the argument half, leaving the **longer** horizon standing, which is the
outcome this decision exists to avoid rather than to cause.

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
