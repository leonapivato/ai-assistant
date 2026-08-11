# 130. A notification is a proposal, and only a perishable one earns an interruption

- Status: Partially superseded by ADR-0131 (§2's validation rules, only as to a bound on `NotificationCandidate`'s encoded size)
- Date: 2026-08-10
- Partially superseded: 2026-08-11 by ADR-0131 — **one clause, one property, and it
  is a bound this ADR had no reason to know it needed.** ADR-0131 decides the delivery
  seam, and a candidate crosses the wire nested inside its `NotificationDelivery`.

  **Replaced — §2's validation rules, only as to encoded size.** §2 fixes what a
  `NotificationCandidate` carries and the conditions it is refused under, and states
  no bound on how large the whole may encode to. ADR-0131 §4 adds one: the canonical
  encoding is bounded by ADR-0085 §8's contract limit less a 256-byte delivery
  reserve, because what §8 measures is the *result* — the delivery wrapper — and a
  candidate sized at the full limit is one the hub could accept and could never send.
  A reader holding only this ADR builds the type, and its conformance suite, accepting
  candidates ADR-0131 refuses, which is ADR-0070 §1's first limb.

  **Not replaced — the rest of §2, which is all of it.** Every field the clause names,
  the rule that a candidate references what it is about and does not contain it, the
  producer-chosen sensitivity that is never defaulted, the `DataTier.SECRET` refusal
  and the already-perished refusal are untouched and stay accepted.

  **Not replaced — anything else in this ADR.** §3's one-call chassis and its
  atomicity, §5's dispositions and budget, §6's standing preferences, §7's cap and
  retention, §8's candidate key, and §9's surface list all stand, and ADR-0131 rests
  on nearly every one of them. ADR-0131 §9 records the extent; the implementing lane
  carries the bound into this type's validation and its conformance coverage.

## Context

### Leg 10 has two halves, and this decides the first

`docs/roadmap.md`'s leg 10 names three things — "the push seam,
`NotificationCandidate`, and the interruption policy". Two of them are one
question: *what may the assistant decide to tell the user, and what earns being
told now?* The third is a different question: *how do the bytes get to a device?*
They are dispatched as two lanes of #943, and this ADR is the first. The delivery
seam is the second lane's, bound by ADR-0094 §2, ADR-0084 §3 and ADR-0124 §10,
and nothing below decides any part of it.

The lane B ADR's number is assigned and its file does not exist yet, so its
number is shown here rather than cited — a citation to a number above the issued
set's maximum fails ADR-0088 §6's Tier 1 and is not exempted by ADR-0090 §1,
which exempts only a gap the issued set encloses. ADR-0088 §1 supplies the form —
"a fenced block is display, not citation" — and ADR-0088 §5 records fencing as
"not a courtesy" but "the mechanism", used there so that the ADR forbidding a form
would not fail on its own examples of it:

```text
The delivery seam is ADR-0131.
```

### The chassis has never disposed of a proposal that could not wait

ADR-0005 §3 states the principle: "the model proposes; a deterministic policy
disposes". ADR-0028 gives it its path — `MemoryUpdateProposal` reaches
`MemoryWriter.ingest`, which resolves conflicts, asks the injected `MemoryPolicy`
to rule, and applies the ruling. ADR-0077 puts the observer behind it, ADR-0093
puts a `Reader` behind it, and ADR-0078 gives a deferred ruling a durable home as
a question the user answers.

Every artifact on that path shares one property nobody had to state, because
nothing violated it: **it waits.** A `DeferredProposal` is enumerable through
`DeferralStore.pending` and reachable through the engine's `questions`; both are
read when a client asks. `AssistantEngine`'s whole surface is client-initiated
request/response — `pending_confirmations` is the closest thing to "here is what
is waiting for you", and it is polled, never pushed. Nothing in `core/types.py`
models something the assistant wants to *volunteer*, and nothing in
`core/protocols.py` gives it a way to say so. `Goal`'s docstring is the one place
the corpus reaches for the word, and it reaches for it as a justification rather
than a mechanism: a goal "outlives any one conversation and is what makes a plan
resumable and a notification justifiable" (ADR-0014 §1).

So the roadmap's sentence is exact: what earns an interruption "is a judgement
the propose/dispose chassis has never had to make, because every other proposal
it gates waits patiently to be read".

### ADR-0078 §8 declined the bookkeeping, and named what would carry it

ADR-0078 §8 ruled that delivery state — "was it sent? seen?" — is "deliberately
**not** on `DeferredProposal`: it is a transport concern, it differs per spoke,
and putting it on the record would make a memory decision carry a notification's
bookkeeping". That is a refusal with a shape in it. The bookkeeping it refused to
carry has had no home since, and this ADR mints the artifact that has one.

The same section names three reaches to the user and declines the third:
"**Not injected into `respond`.** A turn
answers the user's request; interleaving an unrelated interrogation into every
turn is the 'blanket interrogation' … it would make a turn's content depend on
queue depth." Its deferred list keeps the count-on-every-turn variant open and
files it to "revisit **when the hub can push**". The hub still cannot push, so
that trigger has not fired and this ADR does not fire it.

### VISION §5 lists six criteria, and today only some of them have a source

VISION.md's Principle 5, "Proactivity Must Earn Its Place", says proactive
suggestions should be evaluated on "expected usefulness; urgency; confidence;
interruption cost; relevance to an active goal; whether the opportunity will
expire", and closes "the assistant should learn when the user welcomes
intervention and when silence is better". Its Notification Fatigue risk answers
with "interruption-cost modeling, quiet periods, relevance thresholds, and
feedback-based adaptation". `docs/roadmap.md`'s gap register carries the promise
as "proactivity that earns its place".

Checked against the tree, those six do not stand on the same ground:

- **Confidence, expected usefulness and relevance to a goal** are things the
  producer knows at the moment it notices, and the chassis already carries the
  first two shapes (`ObservedProposal.confidence`, `MemoryUpdateProposal.rationale`).
- **Whether the opportunity will expire** is a fact the producer can commit to.
- **Urgency** is a claim, and nothing falsifies it.
- **Interruption cost** has no signal source at all. ADR-0008 §6 deferred
  "**Attention and urgency**, which belong with the proactivity slice (VISION §5)
  and have no signal source yet", and `CurrentContext` still has no attention
  facet. #920 holds the device-as-context-facet work and is unscheduled.

A policy that weighs interruption cost is therefore not buildable today, and a
policy that weighs a producer's self-declared urgency is a policy a producer
writes for itself.

### Nothing here may be calibrated from usage that has not happened

VISION §5's last sentence and the Notification Fatigue response both reach for
learning. The owner's ruling on #879 (2026-08-10) is that this leg exits on
mechanism evidence and that the experiential half of its exit test is deferred
until daily use resumes. A tuning surface that needs weeks of signal before it
is usable at all would therefore ship into a system with nothing to calibrate it
and no way to tell whether it worked.

That is a design constraint, not an inconvenience: **the tuning surface has to
work on the first day, from an empty store, with no history.**

### The noticer exists; the channel does not

Leg 5 built the half VISION §8 names — "proactivity needs something awake to
notice". `src/ai_assistant/service/scheduler.py` holds a real `Scheduler` over a
`Job` table built by `jobs_for`, and ADR-0083 §7 rules the loop serial, each job
re-armed from its completion, a failing job logged rather than fatal, and
"disabled" spelled `None` and never `0`. `Scheduler._run_job`'s own docstring
records what it cannot do: it "is generic over jobs and cannot know which results
are safe to render", so today no job's result reaches a person.

The other half is closed by three independent, currently-binding rules —
ADR-0094 §2 ("the hub may not initiate a connection to a spoke"), ADR-0084 §3's
serial, correlated, client-initiated envelope with no push kind, and ADR-0124 §10
("no lane may read this ADR as deciding any part of a delivery seam for
proactivity"). Lane B decides that. This ADR must therefore be writable, and
reviewable, without assuming any channel exists.

### Re-noticing is the normal case, and a cursor is not the remedy

A scheduler-driven producer that re-reads an overlapping window proposes the same
thing again. The corpus has already been here twice. ADR-0093 §5 rules a reader's
bound "a function of the clock, its configuration and the source's own content,
and of nothing else", carries "no cursor and no durable per-source state", and is
explicit that a re-read destroys nothing "and it is **not** free of duplicates".
Its §5 also states what buys that result — a window that moves with the clock, so
"there is no accumulating backlog for a cursor to track" — and scopes it to
sources that can be re-read in full. ADR-0111 then decides the durable cursor for a
scheduled *walk* — a position in an order the store maintains — and its §11 is
explicit about the limit: "**Coverage over an external source.** … A reader over
a source this system does not own has no such order … A cursor is not the remedy
for a receding window over somebody else's data."

So a noticer over a calendar cannot have a cursor, and a noticer over a
store-owned order already has ADR-0111's. Either way the notification layer sees
the same candidate more than once, and idempotence has to live here rather than
upstream. #632 tracks what remains open around the cursor and is not moved by
this decision.

### What makes this a decision rather than an implementation detail

Three things a later lane could not settle for itself. Whether the disposition is
a model's judgement or a mechanical rule decides whether an interruption is ever
explainable. Whether silence or contact is the default decides what a new
producer does on the day it ships. And whether the tuning surface is a
preferences panel or an act taken at the moment of contact decides whether the
exit test's second half is reachable before there is any usage to learn from.

## Decision

### 1. A `NotificationCandidate` is a proposal, and producing one reaches nobody

> **Normative.** A `NotificationCandidate` is the proposal artifact for proactive
> contact: a producer's assertion that the user may be worth telling something
> they did not ask for. It is not a decision to tell them, and holding one confers
> no authority to contact anyone.

> **Normative.** A producer holds no channel, no delivery seam and no client
> connection. Its only outcome is the `NotificationDisposition` returned to it by
> the seam in §3, and it may take no other action on the strength of having
> produced a candidate.

> **Normative.** Any component may produce a candidate, subject to the import
> boundaries `lint-imports` enforces and to its own contract: this ADR widens no
> existing prohibition, and ADR-0093 §1's rule that a reader "takes no store
> handle, no writer, no policy and no engine" is unchanged, so a `Reader` may not
> hold the seam of §3.

> **Normative.** A producer may not select its own disposition, exempt itself
> from §5, or write to the notification store other than through §3's seam.

This is ADR-0093 §1's posture applied to the other end of the system:
"Selecting when a sensor runs, and ingesting what it returns, are
`orchestration`'s. A sensor is never its own caller." (ADR-0093 writes `Sensor`
where the ratified contract now writes `Reader`; ADR-0095 renamed it.) The
producer notices; it does not decide, and it does not
deliver. In practice the first producers will be scheduler jobs of ADR-0083 §7's
shape, driven from the composition root — but the contract does not name them,
because what makes proactive contact safe is that producing is not delivering,
not that some list of producers was blessed.

### 2. What a candidate carries, and what it may not

> **Normative.** A `NotificationCandidate` is a frozen pydantic model in
> `core/types.py` carrying: a `candidate_key`; the producer's declared name; the
> notification class §6 tunes; a one-line summary and an optional detail, both
> being what the user would be told; the instant it was noticed; an optional
> expiry; an optional `Goal` reference; a confidence in `[0.0, 1.0]`; a chosen
> sensitivity `DataTier`; and references, by identifier, to the records it is
> about.

> **Normative.** A candidate references what it is about and does not contain it.
> A reference is an identifier resolved through an existing ratified read; the
> summary and detail are the only free text a candidate carries, and they are what
> the user would be shown rather than a copy of a record.

> **Normative.** A candidate's sensitivity is chosen by its producer and never
> defaulted, on ADR-0093 §4's rule for an attested proposal.

> **Normative.** A candidate whose sensitivity is `DataTier.SECRET` is refused at
> validation. Tier 0 never reaches the notification store, in any disposition and
> under any setting.

The refusal is `DeferredProposal`'s, whose coherence validator refuses a
`DataTier.SECRET` proposal outright rather than gating it. The reason is
ADR-0004 §3: a Tier 0 value lives in the OS keyring, "never in the memory
database, never in a committed file", and a notification store is a database
holding free text a producer wrote to be shown to a person. Refusing at
validation rather than at disposition is what keeps that true of every
disposition, including the held one — a rule that only stopped Tier 0
*interrupting* would still have written it down.

> **Normative.** A candidate carries no delivery state. Whether contact was
> attempted, reached a device, or was seen is not a field of the candidate and not
> a field of its disposition, and no clause of this ADR may be read as placing one
> there.

The last clause is ADR-0078 §8's refusal kept rather than reversed: transport
state differs per spoke, so it belongs to the seam lane B decides. What this ADR
mints is the record that seam attaches to, which is the thing ADR-0078 §8 said a
memory decision must not become.

> **Normative.** A candidate whose expiry is not later than the instant it was
> noticed is refused at validation, in the form `DeferredProposal`'s coherence
> validator takes: a candidate that has already perished is not a proposal, it is
> a defect.

### 3. The chassis it enters: propose, dispose, persist — with one call

> **Normative.** A producer offers a candidate through a single seam method on a
> `NotificationWriter` Protocol, which reads the standing preferences and the
> durable record, asks the injected `NotificationPolicy` to rule, records the
> ruling where §5 requires a record, and returns the resulting
> `NotificationDisposition`.

> **Normative.** For every offer and every reconsideration, the duplicate lookup
> of §8, the cap check of §7, the budget read of §6, the ruling of §5 and the
> writing or updating of any record are **one atomic act** in the store. Two
> rulings made concurrently may not both proceed on the strength of the same last
> remaining unit of budget, the same last free slot under the cap, or the same
> absence of an actionable record for one key.

ADR-0028 §3 ruled that one method suffices for the memory write path "because
conflict detection is not a separate stage"; the same holds here, and the
atomicity clause is the notification analogue of ADR-0078 §2's resolve-once
compare-and-set. It covers every durable outcome rather than the interrupting one
alone: a `HOLD` that races another `HOLD` breaks duplicate suppression and the
cap just as a raced `INTERRUPT` breaks the budget, and each of those is a
guarantee some later clause states unconditionally. Without this, all three are
advisory.

### 4. The disposition is mechanical, and no model makes it

> **Normative.** `NotificationPolicy` is deterministic: for the same candidate,
> the same standing preferences, the same durable record and the same instant it
> returns the same disposition. It performs no model call, and its ruling is a
> function of its inputs and of nothing else.

> **Normative.** A producer's confidence, its summary and its choice of class are
> **evidence on the proposal**. The policy may read them; no clause of §5 is
> satisfied by a producer asserting that it should be.

A model may decide whether something is worth *proposing* and may write the
sentence the user would read — that is the proposing half, and ADR-0005 §3 has
always allowed it. What a model may not do is rule on its own proposal. Making
the disposition mechanical is what makes an interruption explainable after the
fact, testable before it, and cheap enough to run on every scheduler tick with no
provider reachable.

### 5. Three dispositions, five conditions, and silence is the default

> **Normative.** A disposition is exactly one of `INTERRUPT`, `HOLD` or `DROP`.
> `HOLD` is the outcome whenever no clause of this section selects another.

> **Normative.** `INTERRUPT` means the user is to be reached at the earliest
> instant a channel permits. It is not an assertion that a channel exists, and it
> binds no transport.

> **Normative.** A candidate is ruled `INTERRUPT` only when **all** of the
> following hold: it declares an expiry later than the ruling instant; the reach
> level for its class is `interrupt`; no quiet window covers the ruling instant;
> and §6's interruption budget for the window containing the ruling instant is not
> exhausted.

> **Normative.** Four conditions are evaluated first, in this order, and each
> yields `DROP` naming itself as the reason: the candidate declares an expiry not
> later than the ruling instant; the reach level for its class is `off`; it
> duplicates an actionable record under §8; the store is at the cap of §7. A
> candidate that passes all four is ruled `INTERRUPT` when the conjunctive clause
> above is satisfied and `HOLD` otherwise, naming the first unsatisfied condition
> of that clause — which for a candidate declaring no expiry at all is the expiry
> condition.

> **Normative.** Sensitivity is not a condition of this section. `DataTier.SECRET`
> is refused at validation by §2 and no candidate carrying it reaches a ruling.

> **Normative.** A `NotificationDisposition` carries the kind, the identifier of
> the record it produced where §8 requires one, the notification class, the ruling
> instant, a stated reason naming the condition that decided it, and where the
> kind is `HOLD` an optional `reconsider_at` instant.

> **Normative.** A `HOLD` also carries the **whole set** of conditions that failed
> at its ruling, not the first alone. The reason names the first for rendering;
> the set is what §6 reads, and a rule that read the reason instead would miss a
> record whose second failure is the one a setting change removes.

> **Normative.** `reconsider_at` is the instant at which a held record next falls
> due, and it has two writers: the ruling that produced the record, under the
> clause below, and a standing-setting write, under §6.

> **Normative.** A ruling of `HOLD` sets `reconsider_at` to the earliest instant
> at which every condition that failed could next hold, and sets none where any
> failing condition is not one that time alone resolves — the reach level and an
> absent expiry are each such a condition. A quiet window's end and the instant
> the budget window next frees a unit are the two that time does resolve.

> **Normative.** A held record is **reconsidered** on the first run of the
> reconsideration operation at or after its `reconsider_at` instant: the policy
> rules it afresh against the standing state as it then is, and the existing
> record is updated in place with the new disposition. A reconsideration is not a
> new offer — it introduces no second record, and §8's duplicate rule does not
> read the record being reconsidered as a duplicate of itself.

> **Normative.** A late reconsideration is not a fault. `reconsider_at` is the
> instant before which a record may not be reconsidered, never a deadline by which
> it must have been, on ADR-0083 §7's rule that "a missed or late tick is never a
> correctness bug".

> **Normative.** Reconsideration is a public operation on the **concrete
> `orchestration` engine** that rules every record whose `reconsider_at` has
> arrived. It is part of the maintenance surface ADR-0083 §8 places "on a class in
> `orchestration`, not `core` contract surface", and it is **not** a member of
> `AssistantEngine`: no client asks for it and no interface adapter may drive it.

> **Normative.** Reconsideration is driven by a job on ADR-0083 §7's scheduler
> whose body is that engine call and which holds no store, on ADR-0093 §6's
> shape — so ADR-0083 §7's "no job gets new store surface" and ADR-0083 §8's rule
> that every job is a bound public engine method both hold unchanged.

> **Normative.** The job's interval is a `Settings` field on ADR-0083 §7's
> convention — a `timedelta`, finite and strictly positive, or `None` for
> disabled and never `0` — defaulting to **five minutes**. It ships enabled: with
> no producers it rules nothing, and a held record whose window has passed is the
> one thing this ADR cannot leave to a later act.

> **Normative.** A reconsideration ruled `INTERRUPT` spends a unit of budget like
> any other ruling, and ruled `HOLD` carries a fresh `reconsider_at` on the same
> rule. A reconsideration never deletes a record and never writes a second one:
> ruled `DROP` — by expiry, or by a reach level lowered to `off` since the hold —
> it records that disposition, the record ceases to be actionable, and §7's
> retention is what removes it.

> **Normative.** A unit of the budget is spent when a disposition of `INTERRUPT`
> is recorded, never when contact is attempted and never when contact succeeds.

> **Normative.** No spent unit is refunded except by an act that says so. A
> delivery seam may not refund a unit implicitly on a failed attempt, and may not
> retry into a second unit without a second disposition ruled under this section.

**Perishability is the whole of the escalation test, and that is the decision.**
VISION §5 lists urgency and expiry as separate criteria; only one of them is a
fact. A producer that declares "this expires at 14:00" has committed to something
falsifiable, and the harm of holding it is real and bounded. A producer that
declares "this is urgent" has committed to nothing, and every producer's author
believes their own producer is urgent. So the perishable case escalates and
everything else is held, which is also the reading of "proactivity must earn its
place" that a policy can actually apply: **something that keeps is not an
interruption, it is a message.**

**`HOLD` is not silence.** A held candidate is readable (§7); the user is still
told something they did not ask for, on their next arrival. What `HOLD` withholds
is the *interruption*, which is the scarce thing.

**The budget is what bounds a wrong producer.** A policy can be right about every
individual candidate and still be intolerable in aggregate, and no per-candidate
condition catches that. Spending the unit at disposition rather than at delivery
keeps the bound computable with no channel in existence, and errs toward silence
when delivery is unreliable — which is the direction a system with no attention
signal should err in.

### 6. The tuning surface: three standing settings, one act at the moment of contact

> **Normative.** What reaches the user is tuned by three standing settings, held
> as durable user state in the notification store and not in `Settings`: a
> **reach level** per notification class, one of `off`, `hold` or `interrupt`; a
> set of **quiet windows**; and an **interruption budget** expressed as a count
> per rolling window.

> **Normative.** Every standing setting has a shipped default, so an empty store
> is a working policy and no setting is a precondition of the system running.
> The defaults are: reach `hold` for every class, including a class no preference
> names; no quiet windows; and a budget of three interruptions per rolling
> twenty-four hours.

> **Normative.** A notification class is declared by its producer and is not a
> configurable value, on ADR-0093 §7's rule for a reader's identity: "a stable
> Tier 2 name, never derived from the source's location or contents". It is not a
> closed enumeration, so adding a producer is not a contract change, and a class
> no preference names takes the default reach.

> **Normative.** Quiet windows are read in `Settings.timezone` — the same value
> ADR-0008 §5 gives the temporal context and ADR-0093 §7b binds the calendar
> reader to. No second timezone source is introduced.

> **Normative.** A quiet window is a half-open local-time-of-day interval, may
> cross midnight, and resolves a DST-ambiguous local instant at `fold=0`, on
> ADR-0093 §7b's rule for the same hazard.

> **Normative.** Every `INTERRUPT` disposition carries its notification class, so
> any surface rendering it can offer the two acts that tune it in one step:
> dismissing the notification, and lowering that class's reach.

> **Normative.** Writing a standing setting sets `reconsider_at` to the instant of
> the write, as one atomic act with the write itself, on every actionable held
> record whose **failed-condition set** holds a condition that change could
> remove. `reconsider_at` is a floor, so this may move a record's due instant
> earlier as well as give it one, and a record whose set holds only the expiry
> condition is reached by no setting and keeps the stamp its ruling gave it.

> **Normative.** Lowering a class's reach to `off` is the one setting change that
> reads no failed-condition set: it makes **every actionable held record** of that
> class due at the instant of the write, so each is ruled `DROP` and ceases to be
> actionable. "Never tell me this" reaches what is already held, not only what
> comes next.

> **Normative.** No setting change reaches a record already ruled `INTERRUPT`.
> Reconsideration is an operation on a held record throughout, and whether contact
> already handed to a channel can be recalled is the delivery seam's question, not
> this ADR's.

> **Normative.** No standing setting and no default in this ADR is derived from
> observed user behaviour. Adapting a reach level from what a user ignored is not
> decided here and no implementation may infer one.

**The default is `hold` for every class, and that is deliberate.** It means a
producer cannot interrupt on the day it ships, however sure its author is;
raising a class is an act the user performs. It also means leg 10's exit test is
exercised in its natural order — the user tunes what reaches them, and then
something reaches them — rather than requiring the system to guess right first.
The cost is named in Consequences: out of the box, nothing interrupts.

**Which is exactly why a setting change re-rules what is already held.** Reach is
not a condition time resolves, so a record held because its class was at `hold`
carries no `reconsider_at` from its ruling and would otherwise sit there until it
expired — the user raises the class, agrees to be interrupted, and is not.
Stamping the write instant onto the records the change actually reaches routes
the act through §5's one ruling path instead of adding a second, and the existing
job picks them up on its next run. That is the ordinary case of this leg's exit
test, not an edge of it.

**The whole failed set is what makes the rule correct, and the first reason is
not.** A candidate inside a quiet window closing at 08:00 whose budget is also
spent until 10:00 is held with two failures and due at 10:00. If the user raises
the budget at 07:30, a rule reading only the recorded first reason sees "quiet
window", leaves the record at 10:00, and loses the two hours the user just bought.
Reading the set moves it to 07:30, where it re-rules and re-holds to 08:00 —
which is why `reconsider_at` is a floor rather than a schedule, and why a setting
write may move it earlier. The same property keeps the two writers consistent: a
record held for an absent expiry has only that condition in its set, no setting
removes it, and §5's ruling clause is never contradicted.

**`off` is the exception, and it runs the other way.** Every other setting change
can only turn a hold into contact, so reaching a record it cannot help is merely
wasted work. Turning a class off is a user asking for less, and a rule reading the
failed set would leave a record held for an absent expiry actionable and
suppressing duplicates forever — the one direction where under-reaching costs the
user something rather than the machine. It still stops at held records: an
`INTERRUPT` was a decision to reach the user, which by then may have been carried
out, and unmaking it is a transport question this ADR does not own.

**Learning is what VISION §5 asks for and is not what ships here.** "The
assistant should learn when the user welcomes intervention and when silence is
better" needs signal from usage that, per the ruling on #879, does not yet exist.
Three standing settings and one act at the moment of contact need none, and the
act is taken exactly when the user's judgement is sharpest. Feedback-based
adaptation stays VISION's promise and this ADR's deferral, not its mechanism.

### 7. A held candidate is read, never injected

> **Normative.** Held notifications are reachable only through an explicit
> enumeration the client asks for. No notification, and no count of notifications,
> is injected into a turn's result, into `converse`, or into any response to a
> request that did not ask for it.

This is ADR-0078 §8's third reach applied unchanged — a turn's content may not
depend on queue depth — and its count-on-every-turn variant stays declined, its
"revisit when the hub can push" trigger unfired because the hub still cannot.

> **Normative.** A record is **actionable** while it is neither dismissed, nor
> expired, nor ruled `DROP` by a reconsideration. It is **retained** until
> retention removes it. Expiry ends a record's interruptibility and its
> actionability; it deletes nothing, and an expired record stays enumerable and
> renders as expired.

> **Normative.** The cap counts **actionable** records and no others, so
> dismissing a notification frees capacity at once and an expired one holds none.
> §8's duplicate rule reads the same population, so a fact that recurs after its
> notification expired or was dismissed is a new candidate and not a duplicate.

> **Normative.** The cap is a `Settings` field of the notification store,
> defaulting to **100 actionable records**, with no spelling for "unlimited". It
> is exactly an integer in `0 < value < 2**63`, validated at load rather than per
> admission — `deferral_queue_limit`'s bounds and its `_IntegerSetting` shape,
> whose upper bound keeps a configured value inside the domain a store's own count
> can hold. At the cap a new candidate is ruled `DROP` naming the cap, and no
> existing record is displaced.

> **Normative.** Retention is a `Settings` duration stamped onto each record at
> admission — never consulted from the setting afterwards — and it runs from the
> instant the record **ceased to be actionable**, not from its admission. It
> defaults to **seven days**, with `None` meaning a record is never purged.

> **Normative.** A record is purgeable only once it is no longer actionable and
> its retention has elapsed. No record is purged while it is still actionable,
> whatever its retention, so a record's key suppresses duplicates for the whole
> time §8 says it does.

> **Normative.** The retention purge job ADR-0083 §7 already runs calls this
> store's purge, in the shape it already calls `MemoryStore.purge_expired` and
> `DeferralStore.purge`.

Both figures follow ADR-0078 §7's rulings for the deferral queue, which decided
this exact pair for the same reasons: a cap that "refuses new questions and keeps
old ones", strictly positive because "a cap of `0` is at capacity before its first
admission", and with no unlimited spelling because the duration axis is where the
deliberate escape lives. Naming the values here rather than leaving them to the
lane is ADR-0093 §7a's practice; a cap of 1 and a cap of 50 are both "a cap", and
a conformance suite cannot test a boundary nobody stated.

Seven days is shorter than the deferral queue's horizon on purpose. A question
keeps its value until it is answered; a notification about a thing that already
happened does not, and the whole of this ADR is that proactive contact is about a
moment rather than a backlog.

**Retention runs from cessation rather than from admission, and that is a
correction to the obvious form.** Measured from admission, a record whose expiry
sits beyond the horizon is purged while it is still actionable — at which point
its key suppresses nothing, a cursorless producer re-notices the same fact, and
the same observation interrupts a second time on a schedule set by the retention
figure. §8's guarantee is stated unconditionally, so retention has to be the
clause that yields.

**The cap counts the actionable set for the same reason.** Counting every
retained record makes dismissal fail to free capacity, so a hundred dismissed
notifications under a retention of `None` close the store permanently. Bounding
the actionable set is what the cap is actually for — it is the list a person
reads — and the storage the non-actionable tail occupies is bounded by retention
and emptied by §9's delete surface.

### 8. Re-noticing is expected, and the candidate key is what makes it safe

> **Normative.** A `candidate_key` is a digest over the producer's declared name
> and a canonical projection of what was noticed. It contains no clock reading,
> no random value, and nothing derived from the run that produced it, so the same
> observation yields the same key across ticks and across process lives.

> **Normative.** A candidate offered by a producer whose key matches an
> **actionable** record (§7) is ruled `DROP` naming the duplicate. A
> reconsideration is not an offer and never matches itself (§5).

> **Normative.** A `DROP` writes no durable record. `HOLD` and `INTERRUPT` do.

> **Normative.** No producer may require a durable cursor in order to be correct.
> A producer that re-notices the same fact on every tick is behaving as designed,
> and this section is what makes that safe.

This is `MemoryUpdateProposal.proposal_fingerprint`'s discipline and ADR-0078
§7's dedup-by-question, reached for the same reason and by the same means. It is
also what lets the noticer live with ADR-0093 §5's cursorless read and with
ADR-0111 §11's finding that no cursor helps a window over somebody else's data:
duplicate suppression at the notification layer absorbs the repetition those
rules guarantee. What it does not buy is *coverage* — a fact never noticed is
never proposed — and that is stated in Consequences rather than solved here.

### 9. The contract surface this ratifies, and what the triad lane owes

Names below are ratified as **shape, not spelling**, in ADR-0073 §7's form.

> **Normative.** The implementing lane adds to `core/types.py`:
> `NotificationCandidate` (§2), `NotificationDisposition` and its kind enumeration
> (§5), a reach-level enumeration and a quiet-window value, a standing-preferences
> value (§6), and the durable held-notification record. All are frozen pydantic
> models or `StrEnum`s, on the conventions `core/types.py` already carries.

> **Normative.** The implementing lane adds to `core/protocols.py`:
> `NotificationPolicy`, holding the ruling of §4 and §5; `NotificationWriter`,
> holding the single seam call of §3; and `NotificationStore`, holding the durable
> records, the standing preferences, the cap of §7, the enumerations the read
> surface of §7 serves, and the records due for reconsideration under §5.

> **Normative.** `NotificationStore` carries a per-record delete, a clear, an
> export and a retention purge, in the four shapes `DeferralStore` already carries
> as `delete`, `clear`, `export` and `purge`. A dismissal is not a deletion: it
> ends actionability and leaves the record readable, so the delete surface is what
> ADR-0004 §6's delete right reaches, and the export is what its export right
> reaches.

> **Normative.** `NotificationPolicy`'s ruling method is `async`, mirroring
> `MemoryPolicy.decide`, and §4's determinism is an obligation of the contract
> rather than a property of the signature.

> **Normative.** The implementing lane adds three `Settings` fields — the cap and
> the retention duration of §7, validated at load in the shape
> `deferral_queue_limit` and `deferral_ttl` already take, and the reconsideration
> interval of §5 in the shape `retention_purge_interval` takes. No standing
> setting of §6 becomes a `Settings` field.

> **Normative.** The reconsideration operation of §5 and this store's purge are
> added to the concrete engine's maintenance surface and to no Protocol. Nothing
> in this ADR widens `AssistantEngine` with an operation a scheduler drives.

> **Normative.** `AssistantEngine` gains, in the same lane, a read surface for
> held notifications, a dismissal, a per-notification delete beside it in the
> shape `forget_question` takes, and a read and a write of the standing
> preferences of §6. These are contract surface, because `AssistantEngine` is a
> Protocol in `core/protocols.py`.

> **Normative.** The shared conformance suite asserts, on every implementation:
> that identical inputs yield an identical disposition (§4); that the ordering of
> §5 selects the reason it names; that a `DataTier.SECRET` candidate is refused at
> validation and reaches no store (§2); that a duplicate of an actionable record
> is dropped and writes no record, and that a candidate re-offered after its
> predecessor expired or was dismissed is **not** a duplicate (§7, §8); that a
> record held behind a quiet window or an exhausted budget is reconsidered at its
> `reconsider_at` instant, is not dropped as a duplicate of itself, and becomes
> `INTERRUPT` once the condition clears (§5); that raising a class's reach to
> `interrupt` makes an actionable record already held under that class due for
> reconsideration, that raising the budget moves a record held behind *both* a
> quiet window and the budget to the earlier due instant the change bought, and
> that lowering a class to `off` drops every actionable held record of that class
> including one held only for an absent expiry while leaving an `INTERRUPT` record
> untouched (§6); that two concurrent rulings cannot
> both take the last unit of budget, the last free slot under the cap, or the same
> absent actionable record (§3); that the cap refuses at its boundary, displaces
> nothing, and is freed by a dismissal (§7); that no actionable record is purged
> however long its retention has run, and that a record dismissed, expired or
> dropped by a reconsideration is purged neither before nor at its retention
> horizon measured from **that** instant but immediately after it, with the
> `None` case never purged (§7); that a deleted record is gone from the
> enumeration and from the export (§9); and that an empty preference store rules
> every class at the default reach (§6).

> **Normative.** Nothing implements against this surface until this ADR is
> ratified and merged, and the Protocols, their conformance suite and their
> canonical fakes land as one triad.

The last clause restates golden rule 5 and `CONTRIBUTING.md` → "Adding a
Protocol: land the triad together" rather than adding to them; it is marked
because a reader holding only this ADR could otherwise take §9 as licence to
build against a `Proposed` contract.

### 10. What this ADR does not decide

- **How a disposed notification reaches a device.** The delivery seam is lane B
  of #943, bound by ADR-0094 §2, ADR-0084 §3 and ADR-0124 §10. This ADR states
  only that an `INTERRUPT` disposition binds no transport (§5) and that no
  delivery state lands on the candidate (§2).
- **Whether a failed delivery may be retried, and on what.** §5 bounds it from
  this side — no implicit refund, no second unit without a disposition — and
  leaves the mechanism to the seam.
- **Whether contact already handed to a channel can be recalled.** §6 stops the
  `off` sweep at held records for that reason: an `INTERRUPT` may already have
  been carried out, and unmaking it is a transport act. A seam that can revoke
  one decides so on its own ground.
- **Which producers exist, and what any of them notices.** Each producer is its
  own lane and its own scheduler job under ADR-0083 §7, and what a producer may
  conclude is its own decision's, on ADR-0111 §11's split between binding the
  walk and binding the verdict.
- **The scheduler's durable cursor.** #632 holds it. §8 is what lets a producer
  ship without one; it does not close the deferral, and ADR-0111 §11 already
  rules that no cursor answers a receding window over an external source.
- **Attention as a context facet.** ADR-0008 §6 deferred attention and urgency
  together; §5 answers the urgency half by declining to weigh a self-declared
  urgency at all, and leaves attention exactly where ADR-0008 §6 and #920 have
  it. Under ADR-0083 §15's rule — "a deferral discharged by the ADR it named is a
  stacked addition, not an amendment" — nothing is owed on ADR-0008's status
  line, and this ADR writes none.
- **Feedback-based adaptation of the tuning surface**, which VISION §5 promises
  and §6 declines to ship. Its precondition is the daily use the ruling on #879
  defers.
- **Surfacing a pending count on every turn.** ADR-0078 §11 files it with a
  "revisit when the hub can push" trigger; §7 keeps that trigger unfired.

### 11. Explicitly declined

> **Normative.** A model may not rule on a notification candidate. No
> implementation of `NotificationPolicy` may consult a `ModelProvider`, and no
> lane may add a model-judged disposition without superseding §4.

An interruption a model chose cannot be explained to the user who received it,
cannot be tested deterministically, and cannot run when no provider is reachable
— which is exactly when a resident process is still noticing.

> **Normative.** A numeric priority or urgency score is not part of this contract
> and no implementation may add one to substitute for §5's conditions.

Weighed by a producer, a score is self-granted authority; weighed by the policy,
it is a threshold nobody can calibrate on the first day. Perishability replaces
it because it is falsifiable, and the class reach level replaces the tuning it
was reaching for. This is the same conclusion ADR-0078 §7 reached from the other
direction when it ordered the deferral queue by admission and declined an
"urgency-ordered or imminent-expiry view".

> **Normative.** Neither of §7's two rules — that no notification and no count of
> them is injected into a turn, and that the store's cap refuses rather than
> evicts — may be relaxed by an implementing lane.

- **A per-candidate "interruption cost" input.** VISION §5 asks for it and
  ADR-0008 §6 records that it has no signal source. Quiet windows and the budget
  are the standing, user-declared substitutes; a modelled cost is what a later
  ADR can add once an attention facet exists (#920).
- **A fourth disposition for "tell them later at instant X".** `HOLD` with
  `reconsider_at` covers it with one field and no new kind, and keeps every
  disposition a statement about *now* rather than a scheduled promise the store
  would have to keep.
- **Making the deferral queue a notification producer as part of this ADR.**
  ADR-0078 §8's ruling that a scheduler polling `pending` and delivering "is a
  *reader*" makes such a producer an ordinary lane against §1, and this ADR is
  deliberately not that lane. Naming it here is what shows the seam works: the
  notification bookkeeping ADR-0078 §8 refused to put on a memory decision now
  has a place to live that a memory decision never has to know about.

### 12. What this records against earlier ADRs

- **ADR-0005, ADR-0028, ADR-0078, ADR-0093 — nothing owed.** Each is applied
  rather than narrowed: §1 and §3 reuse ADR-0005 §3's split and ADR-0028's
  one-call path, §2 and §7 keep ADR-0078 §8's two refusals as ratified, and §8
  and §6 apply ADR-0093 §5's cursorless posture and §7's identity discipline to a
  new producer.
- **ADR-0008 — a stacked addition, not an amendment**, under ADR-0083 §15's rule
  quoted in §10. §6 of ADR-0008 named the proactivity slice as the owner of
  urgency, and §5 above decides it by declining to weigh it. `CurrentContext`
  gains no field and ADR-0008's decision is unchanged.
- **ADR-0083, ADR-0111 — nothing owed.** §8 relies on ADR-0093 §5 and ADR-0111
  §11 as ratified and asks neither to change; no existing job's default is
  flipped and no cursor is decided. §5's reconsideration job is a **new row on
  ADR-0083 §7's table**, which is an addition of the kind ADR-0093 §6 already made
  when it added the calendar reader — ADR-0083's `Status` records only ADR-0111's
  amendment, so growing the table is not one. Three clauses that could have been
  strained are met rather than waived: the job body is a public engine call
  holding no store (§7's "no job gets new store surface", §8's bound public
  method); the operation sits on the concrete `orchestration` engine, which is
  where §8 puts a maintenance surface — "not `core` contract surface"; and §5's
  tolerance of a late reconsideration is §7's own rule that a late tick is never a
  correctness bug, applied rather than excepted.
- **ADR-0094, ADR-0084, ADR-0124 — nothing owed and nothing read across.** Their
  clauses constrain delivery, which §10 leaves whole to lane B.
- **This ADR's `Status`.** It decides a contract surface, so the required review
  set is adversarial **and** architecture (ADR-0015 §1, `CONTRIBUTING.md` →
  "Stop when the required reviews are green"), and ADR-0015 §5's
  ratify-after-review sequencing reaches it: it was drafted, reviewed and revised
  as `Proposed`, and its status flipped only once both required reviews returned
  clean on one tree. Findings raised after the flip were folded the same way and
  both reviews re-run. The PR carries the round record; nothing implements
  against §9 until this has merged.

## Consequences

**Easier.**

- **An interruption can be explained.** Every disposition names the condition
  that produced it, and every condition is a fact about the candidate or a
  setting the user chose. "Why did you tell me that?" and "why didn't you?" have
  answers a surface can render without a model in the loop.
- **The tuning surface works on an empty store.** Three defaults and one act at
  the moment of contact need no history, which is what makes the exit test's
  second half reachable before daily use resumes.
- **A wrong producer is bounded twice.** The budget caps the aggregate however
  many candidates it emits, and duplicate suppression caps the repetition a
  cursorless, clock-bounded read guarantees. Neither depends on the producer
  behaving.
- **The bookkeeping ADR-0078 §8 refused has a home.** A memory question can
  become a notification without `DeferredProposal` gaining a transport field, and
  the same is true of any future producer.
- **Tier 0 cannot reach the store at all.** §2 refuses a `DataTier.SECRET`
  candidate at validation rather than gating its disposition, so ADR-0004 §3's
  rule holds without the delivery seam having to enforce anything, and a producer
  that wants to notify about a credential learns so at the point it proposes.
- **Lane B inherits a clean seam.** An `INTERRUPT` disposition and a durable
  record are all the delivery decision needs from this side; nothing above
  presumes a channel, a spoke, a device or a direction of dialling.

**Harder.**

- **Out of the box, nothing interrupts.** Every class defaults to `hold`, so the
  first interruption requires a deliberate act. That is the intended reading of
  "proactivity must earn its place" and it is a real cost: a QA run must tune
  before it can observe an interruption, and a user who never tunes never gets
  one. **Revisit when there is usage evidence that a specific class is welcome**
  — that is the point at which shipping a class at `interrupt` becomes an
  argument rather than a guess.
- **Coverage stays every producer's own argument, and silence is now ambiguous.**
  §8 makes re-noticing safe; nothing here makes noticing complete. A fact a
  producer's window never covers is never proposed, and from the outside that is
  indistinguishable from a fact the policy held. ADR-0093 §5 supplies the
  argument for one shape of producer — a window that moves with the clock over a
  re-readable source, where "there is no accumulating backlog for a cursor to
  track" — and ADR-0111 §11 rules out a cursor as the remedy where the order is
  somebody else's. A producer that fits neither owes its own coverage argument,
  and #632 holds what remains open around the cursor.
- **The triad lane is large.** Three Protocols, six-ish types, three `Settings`
  fields, four additions to `AssistantEngine`, a conformance suite with the
  obligations §9 names, and canonical fakes land in one change. That is the size
  the contract is, and splitting it is what `CONTRIBUTING.md` → "Adding a
  Protocol" forbids.
- **A reconsideration is only as prompt as its job's interval.** §5 rules
  `reconsider_at` a floor rather than a deadline, so a candidate held behind a
  quiet window ending at 08:00 is contacted at the job's first run after that —
  by 08:05 at the default interval. That is the same latency ADR-0083 §7 already
  accepts everywhere else, and the remedy available to a deployment is a shorter
  interval rather than a different guarantee. It does mean the interval is a
  user-visible figure here in a way it is not for a retention purge, and it is
  the one job on the table whose default is minutes rather than hours.
- **`Settings.timezone` becomes load-bearing for a user-visible behaviour.** A
  wrong timezone previously skewed context; it now also decides when the
  assistant is allowed to interrupt. The validator that refuses an unknown IANA
  zone at load is what stands behind that, and it is now guarding more.
