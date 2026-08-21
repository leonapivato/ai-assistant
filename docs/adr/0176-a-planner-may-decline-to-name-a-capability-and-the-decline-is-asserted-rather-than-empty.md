# 176. A planner may decline to name a capability, and the decline is asserted rather than empty

- Status: Proposed
- Date: 2026-08-21
- **Partially supersedes:**
  [ADR-0047](0047-the-model-backed-planner.md) — §4 step 2's requirement that the
  envelope's `steps` be a **non-empty list**, and the paragraph of §4 that states
  it and gives its reason (*"A **non-empty** `steps` list is required: a
  production planner returning zero steps for a goal is indistinguishable from a
  failure to decompose it…"*). §4's goal, step 1 as ADR-0071 replaced it, steps 3
  and 4, the never-a-corrupt-plan property, §5's open capability vocabulary and
  §6's bounded repair all stand.
  [ADR-0071](0071-strengthen-the-planner-envelope-extraction.md) — the Decision's
  **envelope-discriminator predicate**: its first bullet's *"first decoded object
  whose `steps` is a **non-empty list**"* test together with that bullet's
  treatment of an empty list as a shape to step over, and its third bullet's
  clause that *"an outer envelope whose `steps` is empty is therefore rejected as
  an empty plan"*. The scanning parse itself, the advance-past-never-re-enter
  rule, the miss budget, the fall-back to the first decoded object, and the
  never-a-corrupt-plan guarantee are untouched — §2 below restates the predicate
  so that every shape ADR-0071 ruled on is ruled the same way.
- **This decides the defect #1315 records**, named as a deferred follow-on by
  ADR-0170 (`track:conversation` milestone 17 of #1312) and evidenced live on QA
  run #1334.
- **No implementation lands with it.** No `src/`, no `tests/`.
- **It decides no `core/protocols.py` and no `core/types.py` surface** (§8), so
  golden rule 5 is not triggered and this is `Accepted` on merge rather than
  ratified contract-first — the position ADR-0047 declared for itself.

## Context

`ModelBackedPlanner` cannot express "nothing needs to be done." Its system prompt
says `steps` "must be a non-empty list"; `_require_steps` refuses a missing,
mistyped or empty list; `_repair_prompt` closes by re-demanding "a non-empty
`steps` list"; and `_extract_object` will not even *select* an object whose
`steps` is empty as the envelope. Four mechanisms, one rule, and it is a rule two
ratified ADRs decided on purpose.

So for a goal that needs no action at all, the planner is structurally obliged to
invent a capability. That is not a hypothetical. On QA run #1334, against the live
hub, the milestone-17 exit test asked what the assistant knew about the user; the
planner named `retrieve_user_profile`, which nothing binds; the step reached
`Disposition.NO_CAPABLE_TOOL`; and the composed answer — being honest about the
step account it was handed, exactly as ADR-0170 §5 obliges — told the user *"I
don't have a working memory-retrieval tool right now, so I'm reciting this from
what surfaced in context"* **in the same turn whose prompt carried all six
retrieved beliefs**. Retrieval had worked. The invented step made the answer
disclaim it.

That is the shape of the cost, and it is worth naming precisely because it looks
like a prompt problem and is not one. ADR-0170 §5 behaved exactly as ruled: it
guarantees the stage is never *ignorant* of what happened, and it guarantees
nothing about prose. The stage was told a step found no capable tool, because a
step *had* found no capable tool. The honesty obligation faithfully reported a gap
that did not exist, because the gap was manufactured one stage earlier. Every
memory-shaped ask in this system takes that path today.

**The relaxation is not one line, and that is why this is an ADR.** Two ratified
clauses stand in the way, and only one of them is the obvious one.

- **ADR-0047 §4 step 2** requires the non-empty list and gives its reason in
  terms: zero steps "is indistinguishable from a failure to decompose", so an
  empty plan is treated as "no plan could be produced". That objection is
  correct as stated. Any decision that simply deletes the check leaves it true.
- **ADR-0071's Decision** then builds the same test into the *envelope
  discriminator*. Its scan takes "the first decoded object whose `steps` is a
  non-empty list", so a decoy object in the model's prose ahead of the real
  envelope is stepped over — "including one that carries a `steps` key of the
  wrong type or an empty list (which would otherwise shadow a valid envelope
  behind it)". Make a bare empty `steps` legal and that same decoy becomes an
  accepted plan and the real envelope behind it is never read: "send an email"
  would silently plan nothing. ADR-0071 names that failure and rejects it.

The second is the load-bearing one. A relaxation confined to `_require_steps`
would be a new wrong-answer path in `_extract_object`, in the one direction —
an act silently not taken — that this system's whole step-account machinery
exists to make visible.

**Prior art on the same dead end.** ADR-0053 added a selection-time capability
alias layer, mitigating the invented-capability problem *downstream* by resolving
an emitted capability onto one the registry advertises. That approach cannot
reach this case, because there is no advertised capability to resolve onto: the
right answer is that no capability is wanted at all, and every branch of
`resolve_capability` returns a name. The decision belongs at the planner, and
there is an architectural reason it does — the
retrieved memories and the assembled context are **passed into** `plan` and
rendered into the planner's own prompt (ADR-0047 §3, `Planner.plan`). The planner
is the first and only stage that can see, at once, both the goal and the material
that already answers it.

`ActionPlan` already admits the shape. `steps: tuple[PlanStep, ...]` carries no
`min_length`; its only validator is the step-id uniqueness check, which is
vacuously true of an empty tuple. `Planner.plan`'s docstring says nothing about
non-emptiness, and the `PlannerContract` conformance suite reads `plan.steps` only
to check id uniqueness. `Engine._run_turn` already carries an empty-plan branch
and `composing._render_plan` already carries an empty-plan rendering. The whole
downstream half is built. It is unreachable in production for exactly one reason,
and that reason is a ratified decision rather than a missing mechanism.

## Decision

### 1. The decline is a second legal envelope shape, asserted twice over

> **Normative.** The planner's output envelope has two legal shapes. A **plan
> envelope** carries a `steps` key whose value is a non-empty list, exactly as
> ADR-0047 §4 step 2 requires. A **decline envelope** carries a `steps` key whose
> value is a list of length zero **and** a `no_capability_needed` key whose value
> is the JSON boolean `true`. No other shape is an envelope.

> **Normative.** The `no_capability_needed` marker is the JSON boolean `true` and
> nothing else. A value of `1`, `"true"`, `"yes"`, a non-empty string, or any
> other value a language might treat as truthy is not the marker, and an object
> carrying one is not a decline envelope. An implementation in a language whose
> booleans are a numeric subtype (Python's `bool` is a subclass of `int`) tests
> the type as well as the value.

> **Normative.** The marker is consulted only where `steps` is a list of length
> zero. On an object whose `steps` is a non-empty list the marker is inert: the
> object is a plan envelope, its steps are planned, and the marker's presence
> neither changes that nor is an extraction failure.

**Both halves are positive assertions, and that is the whole answer to ADR-0047
§4.** §4's objection is that zero steps is indistinguishable from a failure to
decompose — that absence cannot be told from breakage. It is a good objection
against an *absence*. It has no purchase on an assertion. Under this decision a
model that cannot produce a plan still produces malformed output, still enters
§6's bounded repair, and still ends in `PlanningError`; a model that *declines*
has written down, in two places at once, that it named no capability on purpose.
The two are now distinguishable in the text of the reply itself, which is
precisely what §4 said they were not.

**Requiring the empty list as well as the marker is not redundancy for its own
sake.** It keeps one envelope shape rather than two — the decline is the plan
envelope with an emptied `steps`, so §4 step 3's per-step validation is vacuous
over it and step 4 constructs the `ActionPlan` by the same path with `steps=()`.
And it means the decline cannot be reached by *omitting* anything. An object with
no `steps` key at all is not a decline; it is the malformed reply ADR-0047 §4
step 2 already refuses, and it still gets step 2's specific verdict.

### 2. The extraction predicate, restated so ADR-0071 keeps every shape it ruled

> **Normative.** `_extract_object`'s scan takes the first decoded object that is
> an envelope under §1 — a plan envelope or a decline envelope. Every other
> decoded object is stepped over, including an object whose `steps` is an empty
> list without the marker, an object whose `steps` is of the wrong type, and an
> object carrying no `steps` key. Where no decoded object in the reply is an
> envelope, the first decoded object stands in, so a single malformed object
> still reaches step 2's specific verdict rather than a generic miss.

> **Normative.** Nothing else about ADR-0071's Decision moves. The scanning
> `raw_decode` parse, the rule that a decoded object is advanced past and never
> re-entered, the treatment of a non-syntax bounded parse error as a miss, and the
> `_MAX_EXTRACTION_MISSES` budget all stand as ratified.

**This preserves ADR-0071's guarantee verbatim on every shape it rules on
today.** A bare `{"steps": []}` in the model's prose is stepped over now and is
stepped over after. So is an outer object whose `steps` is empty and whose
metadata hides a plan-shaped object — that shape is still rejected, still for
ADR-0071's own reason, and the advance-past rule that makes it so is untouched.
The predicate widens by exactly one shape, and it is a shape a decoy does not
reach by accident: an empty `steps` list is a plausible fragment, a template echo
or a truncation, whereas an empty `steps` list *accompanied by an affirmative
boolean marker* is a thing a reply contains only if something wrote it
deliberately.

**Two genuine envelopes still cannot be told apart locally and the earlier still
wins**, which is ADR-0071's ruling and is unchanged. The one new instance of it —
a decline envelope ahead of a plan envelope, or the reverse — resolves the same
way, and §7 is why that is acceptable rather than merely bounded.

### 3. A decline states why, because the rationale is the whole of its content

> **Normative.** A decline envelope carries a `rationale` whose value is a string
> with at least one non-whitespace character. A decline envelope whose `rationale`
> is absent, null, not a string, or blank is an extraction failure and enters
> ADR-0047 §6's bounded repair. On a plan envelope `rationale` stays optional,
> exactly as ADR-0047 §4 step 2 leaves it.

On a plan, `rationale` supplements: the steps themselves record what was decided,
and each carries an `intent` and a `capability`. On a decline there are no steps,
so `rationale` is the only thing the persisted `ActionPlan` says — the sole record
of *why* no capability was named, and exactly the field `ActionPlan` documents for
that job. A decline with no rationale persists an audit record that is empty in
substance, which is the auditability ADR-0014 §2 asks of plan state failing at the
one shape where the record has nothing else in it.

**The type does not supply this and must not be assumed to.** `rationale` is
`EncodableText | None`; `EncodableText` refuses unwritable text but neither
refuses nor strips a blank, so `"   "` validates. The non-blank condition is the
planner's to enforce at step 2, not something `core` enforces for it.

**The cost is stated rather than hidden.** This makes a decline strictly harder to
emit than a plan, and a model that gets the shape wrong is pushed toward the very
plan-with-an-invented-capability this decision exists to stop. §5 is the
mitigation and it is a real one: the repair message for this failure asks for the
rationale on a decline, and never for steps.

### 4. The prompt carries both shapes and the test between them

> **Normative.** The planner's system prompt states both legal envelope shapes of
> §1 and the condition under which each is wanted. It states the decline as a
> legitimate, expected outcome for a goal that calls for no action, not as a
> fallback, an error path or a last resort.

> **Normative.** The test the prompt states is what the goal *requires*: a plan
> envelope where accomplishing the goal requires the assistant to act in the world
> or to reach for something this turn has not already been given; a decline
> envelope where the goal is answered from what the turn already carries — the
> retrieved memories, the assembled context, and the conversation rendered into
> this same prompt. The prompt states the test in those terms rather than by
> enumerating request categories.

The test is stated that way because it is one the planner can actually apply. The
material is not somewhere else to be fetched — ADR-0047 §3 renders the retrieved
memories and the assembled context into the planner's own user message, one line
each. "Can this be answered from what is in front of me?" is a question about the
prompt the model is holding.

Naming the two directions concretely, since the boundary is the behavioural heart
of this decision: *"what do you know about me?"* declines, because the beliefs
that answer it are already rendered above; *"send Ana an email"* plans, because
sending is an act and no amount of context performs it. A goal that needs both —
recall something and then act on it — is a plan, because the act is required.

### 5. Bounded repair never pushes a decline back into inventing a capability

> **Normative.** `_repair_prompt`'s message states both legal envelope shapes and
> does not instruct the model to produce steps. It may not close by requiring a
> non-empty `steps` list.

> **Normative.** Where the extraction failure was a decline-shaped reply — an
> empty `steps` list without the marker, or a decline envelope failing §3's
> rationale condition — the repair message names that specific defect and asks for
> the decline to be completed. It does not ask for steps.

Today `_repair_prompt` closes with "with a non-empty `steps` list", which under
this decision would take a model that correctly judged no capability was needed
and instruct it, in the next turn, to name one anyway. That would convert a
recoverable shape error into precisely the defect #1315 records — and it would do
so on the reply where the model had already got the *judgement* right and only the
*form* wrong.

ADR-0047 §6 is otherwise untouched: repair stays bounded by `max_attempts`, a
final failure is `PlanningError`, and a `ModelError` from the provider still
propagates unwrapped.

### 6. A decline is persisted and composed, drives nothing, and the engine already does this

> **Normative.** A declined plan is persisted and its turn is composed. The
> engine's existing empty-plan handling — save the goal, save the plan, compose the
> turn's answer with no step outcome, capture the turn, start no execution and take
> no step-execution capacity slot — is this decision's ruled behaviour for a
> decline, not an artefact of the branch having been unreachable. No
> `orchestration/` change is required to make it so, and this decision requires
> none.

> **Normative.** A decline is persisted whether or not the composed answer
> succeeds. It is a decision the system made about the user's request, and ADR-0014
> §2's audit record is owed for it on the same terms as for a plan.

**Endorsing the branch is a ruling, not a shrug**, because it becomes a production
path the moment the implementation lands and someone will otherwise read it as
untested legacy. Two of its properties are worth stating as deliberate.

**It takes no capacity slot, and the ceiling is not thereby weakened.** The
engine's admission ceiling is by its own terms a *step-execution* throttle — it
exists because the engine cannot know before running a step whether it will park,
and a parked step holds durable state. A decline drives no step, so there is
nothing that could park and nothing to reserve. What does change is that after
this lands not every production turn reaches the ceiling, where today every one
does; the ceiling still bounds exactly what it was built to bound. If composition
rather than execution ever becomes the resource worth throttling, that is a
different ceiling and a different decision.

**`_render_plan`'s existing empty-plan wording becomes true.** It renders
"Nothing: the planner produced no steps for this turn, so no action was taken and
none was needed." The final clause — *none was needed* — is an assertion no fake's
scripted empty plan supports. Under §1 it is supported: it is what the marker
positively asserts. The rendering was written for the decline before the decline
was expressible.

### 7. What this decision cannot promise, and what makes a wrong decline visible

> **Normative.** No clause of this ADR is a guarantee about the content of model
> output, and none is read as one. A conforming `ModelProvider` may decline a goal
> that plainly required an action, or plan an invented capability for a goal that
> needed none, and no prompt, clause or test in this decision makes either
> impossible. The obligations of §§3–5 are on the planner's **construction** —
> what it asks for and what it accepts — which a lane can discharge and a test can
> pin.

This is ADR-0170 §5's precedent applied to the same seam, and it is applied for
the same reason: a marked obligation no mechanism can discharge is worse than an
honest limit. What is bought here is not a correct boundary; it is that the
boundary becomes *expressible*, and that a model which judges it correctly is no
longer forced to lie about it.

**The residual failure is disclosed by construction, and this is the argument that
makes the honest limit tolerable.** ADR-0170 §6 renders the composed answer
**beside** a deterministic step account, never in place of it. On a wrong decline
that account reads "Nothing: the planner produced no steps for this turn" — so a
user who asked for an email to be sent, and whose planner declined, is looking at
a screen that says nothing was done. The failure is a visible under-response, not
a silent one. That is the same property, reached the same way, as the wrong
direction the corpus already tolerates: an invented capability today produces a
`NO_CAPABLE_TOOL` line the user can read.

**The two failure directions are therefore both bounded and both visible, and
neither is silent.** That symmetry is what lets this decision rule the boundary as
a prompt construction rather than as a guarantee it could not keep.

**One echo hazard is pre-existing and does not worsen.** A model that echoes its
own system prompt's example envelope produces a plan whose capability is the
literal placeholder — `capability` need only be a non-blank `Identifier`, so it
validates and reaches `NO_CAPABLE_TOOL`. Adding a decline example to the prompt
adds the mirror of that: an echoed decline example produces a decline. Both are
bounded, both are disclosed by ADR-0170 §6, and neither is a corrupt plan. The
decline direction is if anything the cheaper of the two, since it drives nothing.

### 8. This is a non-contract decision, and the scope of what it touches

> **Normative.** This decision changes no `core/protocols.py` and no
> `core/types.py` surface. `ActionPlan.steps` already admits an empty tuple and
> gains no validator; `Planner.plan` gains no obligation about non-emptiness; the
> `PlannerContract` conformance suite is unchanged by it. The implementing lane
> that finds otherwise stops and says so rather than making the change.

> **Normative.** `no_capability_needed` is a key of the planner's *prompt-level
> JSON envelope*, which is a private protocol between `ModelBackedPlanner` and the
> model it prompts. It is not a field of `ActionPlan`, is not persisted, and
> crosses no subsystem boundary. What crosses the boundary is an `ActionPlan`
> whose `steps` is empty and whose `rationale` says why.

That second clause is where the non-contract claim actually rests. The envelope is
text this planner writes into a prompt and parses back out of a reply; ADR-0047
§4 defined it and ADR-0071 has already changed it once without touching `core`.
The durable artefact is unchanged in type and in every invariant it carries — a
frozen plan, unique step ids, a `goal_id`, a clock-stamped `created_at`.

The implementing lane is therefore `planning/` alone: the system prompt,
`_extract_object`, `_require_steps`, the rationale condition, `_repair_prompt`,
and their tests under `tests/planning/`, plus a case under `tests/orchestration/`
on the now-reachable empty-plan branch.

### 9. What this decision does not decide

**`_render_plan`'s empty branch drops the plan's `rationale` (#1355), and this
decision does not fix it.** That branch returns before reaching the line that
renders the rationale, so a declining turn's only content never reaches the
composing stage. The gap is real and this decision is what makes it user-visible.
It is nevertheless a defect in `orchestration/` with a known one-line fix and no
decision inside it — nothing a reader could disobey — so absorbing it here would
put an ADR in front of a bug fix and would make one change span two subsystems.
It is cited, not absorbed. The two lanes are independent and either order works;
#1355 is worth landing with or just after the implementation.

**`FakePlanner` is not given a decline mode here.** It already returns an empty
default plan to record a call, and whether a canonical fake should be able to
script a *marked* decline is a `testing/` question the implementing lane may raise
on its own account.

**ADR-0053's alias layer is untouched.** It resolves an emitted capability onto
an advertised one at selection time and keeps doing so; this decision is about
the case where no capability should be named at all, which its four branches —
exact, surface variant, curated synonym, unknown — have no way to express.

**No claim is made about how often either direction is taken.** The QA evidence on
#1334 is one observation of the current failure, not a measured rate. Whether the
decline is judged well is a question for a QA pass after the implementation lands,
and the milestone-17 exit test is the probe already written for it.

### 10. This change classified under ADR-0070 §1 and ADR-0082 §1

ADR-0070 §1's test is whether a reader holding only the earlier ADR would act
differently. Applied clause by clause:

**A partial supersession is owed on ADR-0047.** §4 step 2 requires a non-empty
list and the paragraph below it rules an empty plan "not a valid answer". A reader
holding only ADR-0047 would build a planner that refuses the decline envelope §1
now makes legal. That is a change to what was decided, however small the edit, so
it is a supersession and not an amendment — and it is **partial**, because
everything else §4 decided stands, including step 2's `rationale` clause and its
"other envelope keys are ignored" rule, which is what makes `no_capability_needed`
admissible on a plan envelope without further ceremony.

**A partial supersession is owed on ADR-0071.** Its Decision's first bullet makes
"`steps` is a non-empty list" the envelope test and its third rejects an empty
outer envelope as an empty plan. A reader holding only ADR-0071 would build a scan
that steps over the decline envelope §1 defines, and the reply would fall to
bounded repair. That is a change to what was decided. It is **partial** and
deliberately narrow: §2 restates the predicate and leaves the parse, the
advance-past rule, the miss budget and the fall-back exactly as ratified.

**No record is owed on ADR-0170.** §5's clauses stay true word for word. The stage
is still told what was and was not driven; on a decline there is nothing driven
and nothing to disclaim, which is §5 operating rather than §5 narrowed. §5's own
"no guarantee about the content of model output" clause is not narrowed either —
§7 above restates it for this seam rather than replacing it. A reader holding only
ADR-0170 would build the composing stage identically.

**No record is owed on ADR-0014.** §2's capability abstraction and its audit
record both stand; §6 above extends the audit record to a decline rather than
qualifying it.

**No record is owed on ADR-0053.** Its alias layer's clauses stay true; this
decision joins them rather than contradicting any.

Both records ride this change, as ADR-0070 §1 permits and ADR-0082 §1 requires:
each earlier ADR's `Status` line gains this ADR's `ADR-NNNN (<scope>)` pair,
accumulating rather than replacing what is there (ADR-0070 §4), and each gains an
appended dated header note. Neither ADR's Context, Decision or Consequences text
is rewritten.

## Consequences

- **"Nothing needs to be done" becomes expressible, and the invented capability
  stops being structural.** A memory-shaped ask that declines creates no fictional
  step, so no step reaches `NO_CAPABLE_TOOL`, so ADR-0170 §5's honesty obligation
  has no gap to report. The #1334 disclaimer disappears as a *structural*
  consequence of the step never existing — not as a prompt improvement, and
  testable at the planning seam and at the engine's empty-plan branch without
  asserting on model prose.
- **`Engine._run_turn`'s empty-plan branch and `_render_plan`'s empty-plan
  rendering become production paths.** Both already exist and both are already
  correct; what changes is that they stop being fake-only. #1355 is the one gap in
  that pair and is filed rather than fixed here.
- **A declined turn no longer passes the engine's admission ceiling.** The ceiling
  bounds step execution, and a decline drives none — but where today every
  production turn is admitted, after this some are not. Stated so it is a decision
  on the record rather than a discovery.
- **The planner's contract with its model grows a key, and its `core` contract
  does not.** `no_capability_needed` lives in the prompt envelope and never
  reaches `ActionPlan`. A provider offering typed structured output would replace
  the whole envelope — decline shape included — which is the revisit ADR-0047 and
  ADR-0071 already flag.
- **A decline is strictly harder for a model to emit than a plan** (§3's rationale
  condition, §1's two-part marker), and a model that fumbles the shape falls into
  bounded repair. §5's repair wording is what keeps that from degrading into the
  original defect, so §5 is load-bearing rather than a courtesy — a lane that
  implements §1 and §3 without §5 has shipped a regression dressed as a fix.
- **The boundary itself is not guaranteed and cannot be** (§7). A wrong decline
  under-responds and a wrong plan invents; both are bounded, and both are
  disclosed by ADR-0170 §6's deterministic account beside the answer. This is the
  honest limit rather than an obligation nobody could discharge.
- **Harder / revisit when**: a provider with enforced structured output lands and
  the text envelope retires with its decline marker; or the plan-driving stage
  (#242) makes a multi-step plan's later steps drivable, at which point "no steps
  at all" and "no step left to drive" become two states a consumer might want to
  tell apart; or measurement after the implementation shows the boundary is
  judged badly often enough to want a mechanism rather than a prompt.

## Alternatives considered

**Delete the check in `_require_steps` and change nothing else.** Rejected, and it
is the option the issue's own framing suggests. It leaves ADR-0047 §4's objection
true — an empty plan would again be indistinguishable from a failure to decompose
— and it converts ADR-0071's stepped-over decoy into an accepted plan, so a
`{"steps": []}` fragment in the prose ahead of a real envelope would silently plan
nothing for "send an email". That is the failure ADR-0071 names and rejects, and
it is in the one direction the corpus works hardest to prevent.

**Relax the discriminator to "carries a `steps` key that is a list".** Rejected
for the same reason, stated more directly: it is verbatim the shadowing failure
ADR-0071's first bullet rules against, and no marker distinguishes the decoy from
the decline.

**Change the discriminator's *positional* rule instead — prefer the last decoded
object, or require the reply to contain exactly one.** Rejected. Either would let
an empty `steps` list stand alone as the decline, but both reopen more of
ADR-0071 than the decline needs: the last-object rule inverts a scan whose
left-to-right order the miss budget and the advance-past rule are both built
around, and the sole-object rule discards §4's prose tolerance, which is the
property ADR-0071 exists to deliver.

**A decline envelope with no `steps` key at all** — `{"decline": "…"}` or a
`rationale`-only object. Rejected. It makes the decline reachable by *omission*,
which is exactly the absence ADR-0047 §4 objected to, and it splits one envelope
into two shapes so that step 3 and step 4 acquire a second construction path for
no gain. Requiring `"steps": []` keeps one shape and makes both halves of the
decline something the model had to write down.

**Require the marker but leave `rationale` optional.** Rejected, though it is the
closest call here. It would make a decline the easiest thing in the envelope to
emit, which has real value against §3's stated cost. But it also permits a
persisted plan that records a decision and says nothing whatever about it, at the
one shape where no step is there to speak for it — and #1355 is only worth fixing
if there is reliably something to render.

**Rule #1355's rendering fix here.** Rejected. It is `orchestration/`, it contains
no decision a reader could disobey, and absorbing it would make one change span
two subsystems. Cited in §9 instead.
