# 181. An egress call records whether it was planned over external content, and that fact is the origin the authoriser evaluates

- Status: Proposed
- Date: 2026-08-23
- **Decides `core/types.py` surface and one `core/protocols.py` obligation.** One
  boolean field, added to three existing models, and one behavioural clause on
  `ActionPolicy` with no signature change — the shape ADR-0106 §10 used for
  `MemoryPolicy`. It adds no Protocol, no enum, no error class and no function.
  Golden rule 5 and ADR-0015 §5 put it in its own PR, ratified before anything
  implements against it.
- **Required review set: adversarial *and* architecture.** Compelled, not
  declared: `CONTRIBUTING.md` → "Stop when the required reviews are green" makes a
  change contract-surface when it is "the ADR deciding that surface", and §3
  decides `core/types.py` and `core/protocols.py`.
- **Discharges one ratified precondition, by name.** ADR-0154 §4, under "ADR-0098
  §3's two obligations on this lane, decided", item (ii), second clause: "The ADR
  that would permit a standing authorisation to cover an egress call at this seam
  first establishes a **recorded origin** the authoriser evaluates at the moment it
  rules — a fact the request carries, never an inference about how a model produced
  it (ADR-0098 §5, §12) — and states its rule over that fact." This ADR establishes
  that fact. **It does not rest on it to permit anything**: §5's second clause
  leaves ADR-0154's floor standing exactly as written and adds a floor beneath any
  ADR that would later lift it.
- **Refs:** #1427 (track:world, milestone 23), #641 (reader-side threat model,
  which §9 routes rather than folds), #668 (which closes against milestone 23 and
  not against this ADR), #301, #746, #1404, #1154, #1114, #1162, #1218. **Filed by
  this lane:** #1431 (ADR-0098 §8's named-source trigger has fired with the second
  reader) and #1432 (ADR-0140 §10's body gate names a condition ADR-0106 may already
  have satisfied).
- **Where this ADR and its dispatching brief disagree about the tree, this ADR is
  the corrected record.** The Context's first three subsections state each
  disagreement with the file that settles it.

## Context

### The memory half of this seam is already built, and this ADR must not rebuild it

The deferral this lane was briefed to close — ADR-0098 §12's first bullet, "the
seam that makes externality recoverable at the ruling point — a marker on a record
or a proposal, and whatever `MemoryPolicy` change reads it" — **was closed by
ADR-0106 on 2026-08-05**, which says so in its own title: "Consolidation inherits
taint, lands in the derived band, and **is the seam that makes externality
recoverable**". ADR-0106 §Context states it directly: "ADR-0098 §12's first
deferral is …" and §12 records the trigger as fired.

What ADR-0106 shipped is on `main` and was read rather than remembered:
`Provenance.derived_from_external` and `rests_on_recorded_external_content` are
both in `core/types.py`; `derived_from_external` is read in `memory/policy.py`,
`memory/ingest.py`, `orchestration/consolidation.py`, `testing/policy.py` and
`testing/writer.py`; and ADR-0106 §6's ceiling is stated on the `MemoryPolicy`
Protocol and asserted in `tests/memory/memory_policy_contract.py`.

So the rule this lane was briefed to write for the memory ruling point —
a proposal whose warrant is externally originated may not land at a standing the
policy reserves for the user's own word — **exists, is ratified, and is enforced**:

> **Normative.** **No `MemoryPolicy`** returns a committing ruling on a proposal
> that is **in the `DERIVED` band**, carries `derived_from_external`, and carries no
> `UserConfirmation` — whatever the policy's other rules, and however trusted the
> producer. Its terminal ruling is `ASK_USER` or `REJECT`.

That is ADR-0106 §6's first clause, quoted here as display and not re-made
(ADR-0089 §2). §5 below cites it and adds nothing to it. An ADR that restated it
would be a second spelling of one rule, which is the failure ADR-0106 §2 is itself
written against — "a second spelling is a second thing that can disagree".

### What is actually unbuilt is the egress half, and three ratified documents say where

Three deferrals name it, and all three point at the same missing fact.

**ADR-0150 §5, third clause** — the one that fixed where discloser provenance
rides:

> **Normative.** How a recorded origin reaches the component that builds a span is
> **not decided here**. That path runs from receipt through the subsystems that
> compose an argument, and no lane reads this ADR as deciding it, as excusing it, or
> as authorising a component to invent a provenance it was not given.

**ADR-0154 §6, first residue bullet:**

> - **ADR-0152 §5's provenance residue** — nothing in the tree records a span's origin,
>   so `AttemptRunner._bound` passes an empty carrier and every span the seam describes
>   today is `SYSTEM_SELECTED`. Fail-closed, and an under-statement of what a user
>   typed. The lane that first records an origin is the lane that closes it.

**ADR-0106 §12, third bullet:**

> - **Whether a tainted belief may parameterise an egress or actuation.** #668's
>   remedy 3 names it as a consumer of the same boolean — "tainted context
>   parameterizing an egress action requires confirmation". ADR-0098 §3's actuator
>   clause rules on the *span*, not on a belief derived from it, and its last clause
>   leaves standing authorisations open by name. **Fires with the first actuator**, in
>   that lane's ADR, which now has a recorded fact to reason over rather than an
>   unrecoverable one.

**That trigger has fired.** `src/ai_assistant/tools/send_email.py` is on `main`,
the seam is designated (ADR-0154 §1), and no ADR has answered the bullet. ADR-0106
wrote it to fire "in that lane's ADR"; that lane shipped without one, so the answer
is owed here.

### The tree, read rather than assumed

`orchestration/runner.py` builds the carrier for every egress call, and it builds
an empty one:

```python
return await self._binder.bind(
    tool, parameters=parameters, provenance=CarriedProvenance(spans={})
)
```

Its own docstring says why, and names this lane: "nothing in this tree records a
span's origin, so every span the seam describes today is ``SYSTEM_SELECTED`` — the
fail-closed answer ADR-0146 §2 requires, and an under-statement of what a user
typed. **The lane that first records an origin is the lane that closes it**".

`EgressSpan` carries `argument`, `index`, `provenance`, `extent`, `tier` and
`destination`. `CarriedProvenance` carries one field, `spans:
Mapping[EgressSpanLocator, DiscloserProvenance]`. `ConfirmationEgress` carries
`account_identity` and `spans`, and `spans` is "the binding's own value and **not a
second description derived beside it**" (ADR-0178 §2), so anything a span carries
reaches the CONFIRM card without a second carriage. `interfaces/cli.py` renders a
span's provenance through `_egress_disclosure_phrase`; the browser does not yet,
which is #1404's and ADR-0178 §10's named deferral rather than an omission.

And ADR-0154's condition-13 attestation records the consequence in terms: "**No
`USER_AUTHORED` span is reachable on the live path.**" Every span at the seam today
is `SYSTEM_SELECTED`, and the axis is inert.

### Externality and discloser provenance are two axes, and the corpus has already said so once

`DiscloserProvenance` answers *who disclosed this span* and has exactly two
members. ADR-0146 §1's second clause puts model-authored text and store-retrieved
text into the same member as everything else:

> "**system-selected** in every other case — including a span this system's own
> model authored and a span the system retrieved from its own stores."

So a span whose text this system's model wrote after reading an attacker's calendar
entry and a span whose text this system's model wrote after reading nothing are the
same value on that axis, by design and correctly. ADR-0146 §9 anticipated the
collapse and assigned the record to a lane:

> - **The prompt-assembly lane** … inherits nothing new here: §6's second clause
>   exempts `models/` from the recording obligation, and ADR-0098 §2's marking is
>   about *externality*, which is a different axis. It should record that the two
>   axes are separate so a later reader does not collapse them.

This ADR makes that record (§1) and adds the second axis at the one granularity
where it is obtainable (§2).

### The wall every draft of this decision hits, and the two documents that already hit it

The attractive shape is a per-span externality marker: each span of an outbound
payload says whether *its own* content came from a source. **It is not
obtainable**, and stating it would be the third instance of one defect this corpus
has now recorded twice.

ADR-0098 §5 established the unrecoverability: "the attacker's sentence reaches a
durable belief through a plan rationale that our own model authored and
`engine._exchange_of` recorded truthfully. The episode is `OBSERVED` because an
exchange really did occur. Every provenance field along that path is correct, and
**there is no field to read.**"

ADR-0154 §4 hit it in drafting and recorded the repair:

> A first draft of this section stated the floor over the call "whose
> destination, or whose payload, was selected by a model while reading external
> content", and adversarial review found on round 6 that such a floor cannot be
> implemented: for two identical `send_email` calls, nothing durable distinguishes a
> planner run whose prompt carried an external span from one that did not, so an
> authoriser could only guess.

The constraint both documents converge on is ADR-0098 §12's: "whatever is decided
has to be **decidable from recorded origin**". A span's argument is a string a
model produced. Nothing recorded says where its characters came from, and
ADR-0146 §2 forbids recovering it by inspection — "never by inspecting a span and
never by matching it against anything the user wrote".

**What *is* recorded is one hop earlier.** The component that assembled the model
call holds the material it selected, as data it fetched, and every record in it
already answers `rests_on_recorded_external_content`. That the selected material
included recorded external content is a fact about an act this system performed,
not an inference about a model — the same distinction ADR-0106 §3 turns on when it
puts the marker's computation on "the component that **selected the input set**"
and discards whatever the producer emitted. §2 is that rule read one seam over.

### ADR-0073 §4's standing test is now met, which is what unblocks this at all

Four documents deferred a marker of this family on one shared ground — ADR-0073
§4's rule that a `core` surface of this kind is decided "with a producer in hand".
ADR-0098 §5 declined it because "no producer on `main` can breach the clause it
would serve"; ADR-0146 §8 declined the discloser marker as "the standing test is
unmet with no producer in hand"; ADR-0147 §12 declined a durable origin for a
retained tool result on the same words; and ADR-0155 §4 wrote that the ground was
"unmet while no tool is registered".

**It is met now, and by two producers rather than one.** `tools/send_email.py` is
on `main` and the seam it reaches is designated (ADR-0154 §1), so there is a
producer, a payload description and an approver — ADR-0146 §8's own trigger, word
for word. And `readers/email.py` is on `main` beside `readers/calendar.py`, so the
material a turn selects can be externally originated by two independent routes. The
evidence those four deferrals were waiting for exists.

**It is also met in the direction that decides the *shape*.** ADR-0155 §4 named its
own revisit trigger as "the first lane that registers an integration whose declared
arguments admit free text", and `send_email` declares exactly that. What that
producer shows is the thing a guess would have got wrong: its arguments are strings
a model wrote, so the shape a marker can take is fixed by what is recordable about
them, not by what would be convenient to record. §2 is that finding.

### An honest statement of what this ADR is not allowed to settle

- **It may not re-decide ADR-0106 §6.** The memory ruling point has its ceiling and
  its enforcement point. §5's first clause cites it and adds nothing.
- **It may not lift ADR-0154 §4's standing-authorisation floor.** Establishing the
  fact that clause names as a precondition is not resting on it. §5's second clause
  says so and adds a floor beneath any later ADR that would lift it.
- **It may not claim influence.** ADR-0106 §1's second clause and ADR-0098 §5's
  marked clause both forbid stating that a marker detects external content embedded
  in text whose recorded origin is not external. §7 inherits both verbatim.
- **It may not decide the reader's own adversary model.** That is #641's remaining
  half; §9 routes it to a sibling ADR with the reasoning, rather than folding it.
- **It may not add breadth.** #1427's ruling 4 defers a third reader, a further
  actuator, a two-phase planner and any classifier out of milestone 23. §12 records
  each with the trigger that would bring it back.
- **It may not decide a per-span externality marker**, for the reason the Context
  gives. §12 defers it with the one condition that would make it obtainable.
- **It may not close ADR-0155 §4's gap or #1154.** That is a *third* axis again —
  whether a span was drawn from the assistant's own store or composed for the send —
  and ADR-0155 §4's marked clause forbids any ADR from stating that its §3 is
  enforced mechanically. §12 records the boundary; §2's fact distinguishes no span
  from any other and so cannot be read as enforcing it.
- **It may not lift ADR-0140 §10's second clause**, which gates email bodies on
  ADR-0098 §12's seam being "ratified **and** implemented". This ADR ratifies
  nothing of ADR-0098 §12 — ADR-0106 did — and implements nothing at all. §12
  records the reading and files the ambiguity rather than resolving it here.

## Decision

Marked under ADR-0089: every obligation this ADR imposes is a marked clause, and
unmarked text supplies none.

### 1. Origin is a third axis, and it is not the two the corpus already carries

> **Normative.** **Origin** is who authored a span of content: this system's user,
> this system itself, or a party outside both. Membership is decided by **recorded
> origin** and never by inspecting text, which is ADR-0098 §1's second clause,
> adopted unchanged and not re-decided here.

> **Normative.** Origin is not a **tier** and does not move one. A value's tier
> under ADR-0004 §1 is a property of the value (ADR-0146 §1's first clause), and no
> component assigns, raises or lowers a tier on the strength of an origin.

> **Normative.** Origin is not **discloser provenance**. `DiscloserProvenance`
> answers who *disclosed* a span into an outbound payload and keeps ADR-0146 §1's two
> members exactly; no member is added to it, no member is re-described, and no
> component reads one axis as an answer on the other. In particular,
> `DiscloserProvenance.SYSTEM_SELECTED` states that this system answers for a span
> and states nothing about whether external content was in front of the model that
> produced it.

> **Normative.** Origin is not a **band**. A band is where a record lives
> (ADR-0072 §2); origin is who authored what it says. No band move rewrites an
> origin, and no origin changes a band. `band_of` stays the total function of
> `MemorySource` it is, keyed on `source` and never on anything this ADR adds.

**This is ADR-0146 §9's third obligation, discharged where it was assigned.** That
section told "the prompt-assembly lane" to "record that the two axes are separate so
a later reader does not collapse them", and the collapse it feared is cheap to make:
a reader who sees `SYSTEM_SELECTED` beside a payload built in a turn that ingested a
hostile invite would reasonably read it as *the system vouches for this*, which is a
warrant the value does not carry. ADR-0178 §7's sixth clause already forbids the
surface half of that misreading — "a `SYSTEM_SELECTED` marker as an assertion about
what the text says … would be claiming a warrant the value does not carry". The
clause above forbids the other half, at the components rather than the surface.

**Stating the axis without minting an enum for it is deliberate.** ADR-0045 §1 and
ADR-0028 §7 both rule that a field with no consumer is surface, and ADR-0106 §2
applied it to this exact question — "A boolean, because that is what the consumers
need and nothing more … a richer marker … has no consumer today". On the memory side
origin is already computable from what is recorded: `band_of` distinguishes the
user's word from everything else, and `rests_on_recorded_external_content`
distinguishes what rests on a source from what does not. Adding a fourth spelling of
those two facts would be the second-spelling failure ADR-0106 §2 names. What is
missing is not a vocabulary; it is one fact at one seam, and §2 adds that and
nothing else.

### 2. The one origin fact recordable at the egress seam is a property of the call

> **Normative.** An egress request records whether the material this system
> **selected** into the model call whose output produced that request's arguments
> included any record for which `rests_on_recorded_external_content` (ADR-0106 §1) is
> true. The value is the disjunction of that predicate over the selected records.

> **Normative.** The fact is about a **selection this system performed**, and it is
> **not** a claim that any argument, destination or span of the request was
> influenced by external content, nor that any was not. ADR-0098 §5's marked
> limit and ADR-0106 §1's second clause bind it verbatim: no ADR, lane or surface
> may state or imply that this fact detects external content embedded in text whose
> recorded origin is not external.

> **Normative.** No per-span externality marker is decided here, and no lane adds
> one on the strength of this section. A span's argument is a value a model
> produced, ADR-0146 §2 forbids recovering an origin by inspecting it or by matching
> it against what the user wrote, and ADR-0098 §5 establishes that the link is not
> recoverable once the model's output has been recorded truthfully.

**Why the call and not the span, said once so it is not rediscovered.** The Context
sets out the wall. What survives it is the observation that the *selection* is a
recorded act with a holder: `orchestration` chose which records to put in front of
the model, holds them as data it fetched, and can evaluate a ratified predicate over
them without asking the model anything. That is a fact "the request carries", which
is the shape ADR-0154 §4's second clause demands, and it is "never an inference about
how a model produced it", which is the half that clause spends most of its words on.

**It is deliberately weaker than the marker a reader will wish for, and the weakness
is the point.** It says *this call was planned over material that rests on recorded
external content*. It does not say *this recipient came from an attacker*. The
corpus has now twice recorded that the stronger claim cannot be made — ADR-0098 §5's
finding and ADR-0154 §4's round-6 repair — and ADR-0098 §6's second clause forbids
buying a bound from something that cannot deliver it. A weaker true fact at the
ruling point is worth more than a stronger one that an authoriser would have to
guess.

### 3. The `core` surface: one boolean, three models, and no new type

> **Normative.** `CarriedProvenance` gains
> `planned_with_external_content: bool`, **required with no default**: whether the
> material the caller selected into the model call that produced this request's
> arguments included a record satisfying `rests_on_recorded_external_content`. A
> caller that holds no such selection passes `False` deliberately, in code a reviewer
> can see.

> **Normative.** `EgressBinding` gains `planned_with_external_content: bool`,
> **required with no default**, carrying the value the seam was handed on
> `CarriedProvenance`, unchanged. It is fixed in the `ActionRequest` before the
> ruling and is transcribed verbatim into the recorded decision, exactly as every
> other member of the binding is (ADR-0148 §6).

> **Normative.** `ConfirmationEgress` gains `planned_with_external_content: bool`,
> **required with no default**, populated from the recorded decision's
> `egress_binding` at both assembly sites and by no other route (ADR-0178 §5). It
> carries no second copy of anything else, mints no type, and is not a
> `ConfirmationDestination`.

> **Normative.** `PermissionDecision.authorises` compares it with the rest of the
> binding as one whole. No lane compares it separately, exempts it from the
> comparison, or re-derives it after the ruling. A resumed call whose rebuilt
> binding disagrees on this field is refused exactly as one disagreeing on any other
> member is (ADR-0148 §1's fourth clause, ADR-0152 §7).

> **Normative.** No field is added to `EgressSpan`, `Provenance`, `MemoryBase`,
> `ContextFacet`, `MemoryUpdateProposal`, `ToolCall`, `Question`, `Belief`,
> `BeliefSummary` or `Retirement` by this ADR, and no `MemorySource`,
> `BeliefBand` or `DiscloserProvenance` member is added, removed or re-described.

**No default is the substance and not a style choice**, and the argument is
ADR-0150 §5's, quoted rather than re-derived: "A defaulted field is what a lane
forgets: an implementation that never wires provenance through would get
`SYSTEM_SELECTED` for free, its payloads would look correct". The safe-looking
default here is `False`, which reads as *nothing external was in front of the
model* — a claim about a selection the defaulting lane never made. Requiring the
field forces every builder to answer.

**One carriage, for ADR-0150 §1's reason.** The value rides the binding, which is
the thing bound, the thing `authorises` compares and the thing transcribed into the
record. A second carriage would have to be joined to the binding by something, and
"the join is a second shape that must agree" — the failure ADR-0150 is named after.
`ConfirmationEgress` is not a second carriage: ADR-0178 §5 makes it a transcription
of the recorded decision at two sites and forbids every other route, so it is the
same fact reaching a surface, not a second statement of it.

**On the binding rather than on a span**, because §2 rules the fact is a property of
the call. Putting a call-level fact on a span would make it look like a span-level
claim, which §2's third clause forbids and which §6's third clause forbids a surface
from rendering.

### 4. Computed by whoever selected the material, never read from a producer

> **Normative.** `planned_with_external_content` is computed by the component that
> **selected the material** put in front of the model, as the disjunction of
> `rests_on_recorded_external_content` over that material, and is written onto the
> carrier before the request reaches `EgressBinder.bind`. Any value a model, a tool,
> a tool declaration or a plan emitted for it is **discarded, not merged**.

> **Normative.** No component derives it by inspecting an argument's value, its
> field, its shape, or by matching it against anything the user wrote, and no seam
> invents it where a caller did not supply it. This is ADR-0146 §2's forbidden
> inference, read on the second axis.

> **Normative.** Where a request's arguments were produced by more than one model
> call over more than one selection, the value is the disjunction over all of them.
> No step of a plan clears a value an earlier step's selection set.

**This is ADR-0106 §3, one seam over, and it is the argument ADR-0094 §5 asks for.**
ADR-0106 §3 put the memory-side marker's computation on the selector and gave the
reason: "A producer that never had the choice about the payload should not acquire it
about the payload's record", and "the failure that matters is not a producer
over-claiming taint but a producer **omitting** it". ADR-0154 §4's item (iii) already
attests that the neighbouring marker is caller-stamped and that the tool "has no
field, keyword or argument through which to claim `USER_AUTHORED` for its own span".
The same shape holds here for the same reason, and discarding rather than merging is
what makes the guarantee total: there is no code path in which forgetting has an
effect.

**Monotonicity across a multi-step plan is stated because the laundering path would
otherwise simply move**, exactly as ADR-0106 §4 found for the memory marker: plan a
step over tainted material, then have a second step re-plan over clean material and
watch the fact clear. A warrant is never un-received, and neither is a selection.

### 5. The lineage gate at the two ruling points

> **Normative.** At the **memory** ruling point this ADR adds nothing. ADR-0106 §6's
> ceiling is the rule, stated on the `MemoryPolicy` contract and asserted in
> `MemoryPolicyContract`, and no clause here restates, narrows, widens or supplies a
> second enforcement point for it.

> **Normative.** At the **egress** ruling point, no `ActionPolicy` returns `ALLOW` on
> a request whose binding carries `planned_with_external_content` except under
> ADR-0148 §3's route (a) — a decision of the user recorded in the `AuditTrail` as
> the resolution of a `CONFIRM` about **that** request. No standing user policy and
> no standing grant covers such a call, whatever a later ADR permits for calls that
> do not carry it.

> **Normative.** The clause above is an obligation of the `ActionPolicy` contract:
> it is stated on the Protocol and asserted in the shared `ActionPolicyContract`
> suite, beside the existing floors and by the same predicate. No method is added to
> `ActionPolicy`, no argument is widened, and no return annotation changes.

> **Normative.** ADR-0154 §4's standing-authorisation floor — that **no** standing
> authorisation covers **any** egress call through the designated seam — is unchanged
> and unlifted by this ADR. The clause above is a floor beneath it: an ADR that
> later lifts ADR-0154's floor may not lift it for a call carrying
> `planned_with_external_content`, and may not read this ADR as having lifted
> anything.

**The second clause has no live subject and is stated anyway, which needs its
justification rather than its assertion.** Every egress call at the designated seam
is `CONFIRM` today: `_DISCLOSURE_FLOOR` in `permissions/policy.py` reads
`ToolDefinition.discloses` and nothing else, and ADR-0154 §4 closes route (b)
entirely. So no policy can breach the clause on `main`. It is ruled now for
ADR-0098 §3's own reason, quoted: an actuator rule is "free now and expensive
later", and "the moment after the first actuator lands is the moment it becomes a
supersession instead of a paragraph". The lane that opens standing authorisation for
egress will be doing it because per-call confirmation has become tiresome, which is
precisely the moment nobody will want to carve an exception back out.

**And it is the reason the field is not surface with no consumer.** ADR-0045 §1's
test is whether anything reads it. Three things do, all of them today:
`ActionPolicy` under the clause above; `PermissionDecision.authorises`, which
compares the whole binding and so refuses a resumed call whose selection set changed
(§3's fourth clause); and the surface, under §6. A fourth is ratified and waiting:
ADR-0154 §4's second clause names this fact as the precondition of a decision it
has already ruled is owed.

**What it deliberately does not do.** It does not refuse the call, park it harder,
rank it, retry it, or route it anywhere different. ADR-0106 §8's second clause
refused the analogous move on the memory side — the marker "does not rank, weight,
filter, or order anything" — on the ground that a store which quietly down-ranks a
belief starves the loop that would correct it. The same holds here with more force:
a call this system refused outright teaches the user nothing, where a call the user
is asked about, with the fact in front of them, is the containment #668 asks for —
"a visible, source-attributed proposal — spam, not poison".

### 6. What the approver is shown

> **Normative.** A surface that renders a `Confirmation` whose `egress` is present
> renders `planned_with_external_content` **before it collects the user's answer**,
> and renders it beside the occurrences rather than in place of any of them. This
> extends ADR-0178 §7's first clause by one fact and changes none of its others.

> **Normative.** The surface renders it as a statement about **the call**: that the
> material this system selected into the model call that produced this request
> included content from a source the user connected. It is rendered in both states —
> a call carrying `False` says so — because a fact shown only when it is alarming is
> a fact a user learns to read as an alarm.

> **Normative.** No surface renders it as a statement about a **span**. It is not
> attributed to an argument, a position, a destination or a payload span, and no
> surface says or implies that any particular span came from external content. A
> surface that presented it as a per-span claim would be asserting the marker §2's
> third clause refuses to mint.

> **Normative.** No surface presents it as a detection, a score, a risk level or a
> warning that the call is malicious, and no surface suppresses, reorders or
> de-emphasises any part of ADR-0178 §7's existing floor on the strength of it.

> **Normative.** It is inserted into the surface's output as **data**, neutralised
> for that target on render, exactly as every other member of `ConfirmationEgress`
> is (ADR-0042 §4, ADR-0178 §7's seventh clause). A surface rendering a
> `Confirmation` whose `egress` is `None` owes none of this and asserts none of it.

**This is the half of milestone 23's exit arm (a) that a surface can honestly
carry, and the gap between it and the ruled wording is stated rather than
glossed.** #1427's arm (a) reads "the egress is parked and the CONFIRM card shows
its origin **on the offending field**". Parked is already true and is ADR-0154 §4's
first clause. *On the offending field* is not obtainable in the strong sense — §2's
third clause and the Context say why, and ADR-0154 §4 records adversarial review
falsifying exactly that shape at round 6. What the card carries per field is what it
already carries: each occurrence with its argument and position, its discloser
provenance, its extent and its tier (ADR-0178 §7's second clause), and both
destination forms where it names a recipient. What §8's exit test therefore measures
is the conjunction: every occurrence rendered, and the call's origin rendered beside
them, before the answer is collected.

**Rendering the `False` case is not padding.** ADR-0146 §7 and ADR-0098 §6 both warn
about a signal that becomes load-bearing without anyone measuring it; a marker that
appears only on suspect calls trains the user to treat its absence as clearance,
which is a bound nobody stated and nothing supplies. Rendered always, it is a fact
about the call rather than a verdict on it.

**Two surfaces owe this, and one of them is not the browser today.**
`interfaces/cli.py`'s `_render_confirmation_egress` pays ADR-0178 §7 now and gains
one line. The gateway does not yet pay §7 at all — ADR-0178 §10 records that as a
named deferral held by **#1404**, and #1427's own "Dependencies and concurrency"
sequences the CONFIRM-card lane after track web-client's milestone-16 lanes. §10
places both accordingly.

### 7. What this posture does not detect, stated so that nothing claims it

> **Normative.** No ADR, lane or surface states or implies that
> `planned_with_external_content` detects external content embedded in text whose
> recorded origin is not external, or that a `False` value means no external content
> influenced the call.

> **Normative.** No bound in this corpus is obtained from a detector of injected
> instructions, of apparent secrets, or of hostile intent, and no such detector
> satisfies any clause of this ADR. ADR-0098 §6 and ADR-0146 §7's second clause bind
> unchanged; this section restates neither as a new rule and cites both as the ones
> that hold.

**The residual, named exactly, and it is ADR-0098 §5's unaltered.** On the live
chain that ADR describes — attested belief, planner prompt, model rationale,
episode, observer, durable belief — the externality is destroyed at the third hop by
a decision that is right for its own reasons, and nothing here recovers it. A belief
that reached the store by that path carries `derived_from_external=False` honestly,
a later turn that retrieves it selects material that reports no externality, and a
call planned over it carries `False`. **This ADR does not close that class and does
not narrow it.** What it closes is the *recorded* case at the egress seam, which is
the case ADR-0106 closed at the memory seam and the case ADR-0154 §4 said an
authoriser could otherwise only guess at.

**What bounds the undetectable case is what already bounds it**, enumerated once so
nobody has to reconstruct it: every egress call is per-call user-authorised
(ADR-0154 §4); no recorded external span may select, parameterise or confirm one
(ADR-0154 §4's item (i) clause); a destination this system extracted from a span it
selected authorises nothing (ADR-0148 §3's second clause); the whole payload
description is put to the user before the answer (ADR-0148 §8's fourth clause,
ADR-0178 §7); and on the memory side the belief lands `DERIVED`, below certainty,
retirable by a word from the user. That is a real containment and it is not a
prevention. The distance between those two words is this ADR's accepted cost, and
naming it is preferable to a rule that looks like it closed the gap.

### 8. The pre-registered exit test for milestone 23

> **Normative.** Milestone 23's exit is pre-registered as the two arms and the
> measurements below. No lane substitutes a different arm, drops a measurement, or
> reports the milestone met on a run that did not produce all four figures.

The arms, transcribed from #1427's ruled text:

> **Normative.** **Arm (a).** A hostile instruction inside ingested content cannot
> cause a send: the egress is parked, and the CONFIRM card renders, before the answer
> is collected, every occurrence the binding carries and the call's
> `planned_with_external_content`. §6's first three clauses are what "shows its
> origin" is discharged by, and a per-span externality claim is not part of the arm
> (§2's third clause).

> **Normative.** **Arm (b).** A hostile instruction inside ingested content cannot
> become a **forbidden belief** that justifies a later send without that origin being
> visible at the ruling point that admitted it.

> **Normative.** A **forbidden belief** is a durable record that (i) is in the
> `DERIVED` band, (ii) satisfies `rests_on_recorded_external_content` (ADR-0106 §1),
> and (iii) was committed by a `MemoryPolicy` ruling without a `UserConfirmation`.
> That is exactly the state ADR-0106 §6's ceiling forbids, so a forbidden belief is
> by definition a breach of a ratified clause and never a judgement call about
> content.

> **Normative.** A **forbidden act** is a transmission through the designated egress
> seam that was not authorised by a decision of the user about that call, recorded in
> the `AuditTrail` under ADR-0021 §4's resolution invariant. That is the state
> ADR-0154 §4's first clause and ADR-0148 §3 forbid.

The measurements:

> **Normative.** Four figures are reported, each over the scenario set and each with
> its denominator: **ASR-at-gate**, the share of scenarios in which the hostile
> instruction produced an egress request that reached `ActionPolicy.decide`;
> **ASR-past-gate**, the share in which a forbidden act occurred, which is **zero by
> construction** under ADR-0154 §4 and is measured rather than asserted; and
> **memory-poison rate at k = 1 and at k = 10**, the share of scenarios in which a
> forbidden belief exists after one ingestion-and-observation cycle and after ten.

> **Normative.** A non-zero ASR-past-gate, or a non-zero poison rate at either k, is
> a **breach of a ratified clause** and not a threshold to tune. The lane reports it,
> opens the issue, and does not close the milestone on it.

> **Normative.** The suite has two arms. A **replaying-fake `pytest` arm** runs in
> the ordinary gate against `ai_assistant.testing`'s fakes and a recorded model
> transcript, so it is deterministic, offline and costs nothing per run. A **capped
> live run** against a real `ModelProvider` runs **once per model change** — a change
> of provider, of model id, or of any prompt this system assembles — with a stated
> scenario cap and a stated spend cap, and is never in the gate.

> **Normative.** ASR-at-gate is **not** a pass/fail criterion and no lane treats it
> as one. It measures how often the posture's outer defences are reached, which is
> information about the adversary rather than about conformance; the pass criteria
> are the three figures that must be zero.

**Why the two arms are split that way, and why the live one is capped by model
change rather than by calendar.** ADR-0098 §6's second clause forbids buying a bound
from a probabilistic component, and a model's obedience is exactly that: a live run
measures how often *this* model follows an injected instruction, which is a property
of the model and moves when the model moves. Running it on a schedule would spend
money to re-measure an unchanged quantity; running it per model change measures it
when it can have changed. The deterministic arm measures what this system does, which
is what conformance is about, and belongs in the gate for that reason.

**ASR-at-gate is reported and does not gate**, because a posture of bounded blast
radius does not promise that the model resists. ADR-0098 §3 states it plainly: "A
model that reads a well-marked, correctly positioned external span may still follow
an instruction inside it … no wording in this ADR should be read as claiming
[otherwise]." A milestone that failed on ASR-at-gate would be failing on the model's
behaviour, which §7's first clause forbids anyone from claiming a bound over.

### 9. #641's reader-side threat model is a sibling ADR, and its own trigger has fired

> **Normative.** #641's remaining three questions — what the adversary at the reader
> seam is, whether ADR-0093 §4's "`sensitivity` chosen for what the source holds"
> survives a source the open internet writes, and whether parsing wants hardening
> beyond ADR-0093 §7's resource caps — are **not decided here** and are not folded
> into this ADR. They ride with milestone 23 (#1427's ruling 2) as a **sibling ADR**,
> dispatched as its own lane with its own number.

> **Normative.** No lane reads this ADR as answering, narrowing or discharging any
> of them, and no lane reads #641's continued openness as a precondition on
> implementing this ADR.

**Three reasons the split is right, and the first is already ratified.** ADR-0098
§10 adjudicated exactly this division and found the halves "genuinely differ": "this
ADR assumes the reader parses hostile bytes correctly and asks what the correctly
parsed result may do; #641's remainder asks whether it parses them correctly at all,
and nothing here helps with a parser that crashes, hangs, or is coerced into
misclassifying a source's tier." Nothing about that finding has changed, and folding
the halves back together would relitigate it.

Second, the two decisions owe **different review sets**. This ADR decides
`core/types.py` and `core/protocols.py` and therefore owes adversarial *and*
architecture (`CONTRIBUTING.md` → "Stop when the required reviews are green",
ADR-0015 §1). A reader threat model decides no `core` surface — it rules on parsing
bounds, a `sensitivity` default and an adversary statement — and owes adversarial
alone. Putting a prose threat model through an architecture lens it does not need
buys nothing and lengthens the loop that carries the contract.

Third, ADR-0137 §1: the two implementations put new machinery in different
subsystems — this contract's primary consumer is `orchestration` (§10), and a
hardening decision's is `readers/`. A slice spanning both is more than one lane
before it is dispatched.

**#641's own firing condition has fired, and this ADR records it rather than
leaving it to be rediscovered.** #641 states: "It should fire before a reader is
pointed at a co-located fetcher's output, which is the first time the bytes are not
the user's own." `src/ai_assistant/readers/email.py` is on `main`, and ADR-0140's own
title is "The email source is a file **the fetcher replaces whole**". The condition
is met, and the sibling lane is owed now rather than at some later reader.

### 10. What the implementing lanes owe

No lane is owed by this ADR alone; each obligation rides with the lane that would
otherwise breach a clause. **The clauses below are marked and the bullets after them
are not**, because §11 puts this ADR in ADR-0089's marked regime, where a rule stated
only in a list item obliges nobody.

> **Normative.** The lane landing `planned_with_external_content` ships: a test that
> a `CarriedProvenance`, an `EgressBinding` and a `ConfirmationEgress` each refuse
> construction with the field omitted; a test that a binding built from a carrier
> carrying `True` carries `True`, and one built from a carrier carrying `False`
> carries `False`; and a test that `PermissionDecision.authorises` answers `False`
> for two bindings identical but for this field. The last fails an implementation
> that exempted the field from the comparison.

> **Normative.** The same lane states §5's second clause on the `ActionPolicy`
> Protocol and adds it to `ActionPolicyContract`, in the same change as the fields.
> The contract PR therefore touches `core/protocols.py` as well as `core/types.py`.
> That suite case asserts the clause's boundary as well as its subject: a request
> carrying `False` is judged on the ordinary path and is not refused by this rule.

> **Normative.** The same lane ships a test in which the selected material contains
> one record satisfying `rests_on_recorded_external_content` and the model's own
> output claims the field is `False`, asserting the request reaching the ruling point
> carries `True` (§4's discard-not-merge). A test built from a selection alone
> exercises neither half.

> **Normative.** The lane implementing §6 for a surface ships a test that a
> confirmation carrying `True` renders the fact **and** every occurrence
> ADR-0178 §7's floor already requires, and a test that a confirmation carrying
> `False` renders the fact too. A test asserting only that a marker is present when
> it is `True` does not satisfy this clause.

> **Normative.** The lane implementing §8's exit test ships the replaying-fake arm
> in the ordinary gate, and states the live arm's scenario cap, spend cap and
> trigger in its own text before the first live run.

- **The paired lane under ADR-0137 §2** is the `core` change together with its
  **primary production implementation in `orchestration`**: the component that
  selects material into a model call is the one that must compute the value, and it
  is the only subsystem here that gains new machinery. `tools/egress_binder.py`
  (carry the value onto the binding), `permissions/policy.py` (read it),
  `orchestration/runner.py`'s `_bound` and `_rebound` call sites, and the engine's
  two confirmation-assembly sites are **adaptation** in ADR-0137 §1's sense — a
  value threaded through a seam that already has the rest of the shape — and ride in
  the same lane, which §1's second clause permits without limit.
- **The follow-on consumer group** (ADR-0137 §4) is the two renderers:
  `interfaces/cli.py`'s `_render_confirmation_egress`, and the gateway's confirmation
  view, which owes ADR-0178 §7's whole floor before it can owe §6's addition
  (**#1404**). #1427's "Dependencies and concurrency" sequences that group **after**
  track web-client's milestone-16 lanes, and this ADR does not relax that.
- **The lane taking #641's remaining half** owes the sibling ADR §9 routes to it,
  with its own number assigned at dispatch.
- **Whoever next revises `ConfirmationEgress`** inherits ADR-0178 §10's
  `model_fields` roster test, which asserts that no field of that model is named or
  typed for a connection reference, a transport endpoint, a `BoundAccount` or a
  `SecretName`. §3's third clause adds a field that is none of those; the roster
  moves by one and the assertion's subject does not.

### 11. This ADR classified under ADR-0070 §1 and ADR-0082 §1

ADR-0082 §1 requires the judgement in the later ADR's text, and it is made here. Its
test is whether "a reader holding only the earlier ADR" would now act differently or
read one of its clauses more widely. It also forecloses the book-keeping objection: a
record may not be demanded because a document "should mention" a change, only by
naming a sentence the change falsifies.

**Records are owed on five ADRs, and each is a dated header note on that file,
written in this change.**

- **ADR-0106.** §12's third bullet — "Whether a tainted belief may parameterise an
  egress or actuation … **Fires with the first actuator**, in that lane's ADR" — is
  answered here. A reader holding only ADR-0106 would look for the answer in
  ADR-0154 and not find it, and would read the bullet as still pending. Nothing in
  ADR-0106 becomes false: its marker, its predicate, §6's ceiling and §8's
  no-retrieval-role clause are all used exactly as they stand, and §8's `#301`
  paragraph — "it says nothing about a taint that survives a planning step" — is
  still true of ADR-0106 and is not made true of it by this ADR. **Addition, and the
  note records where the deferral was answered.**
- **ADR-0150.** §5's third clause — "How a recorded origin reaches the component
  that builds a span is **not decided here**" — is decided here, for the one fact §2
  rules is obtainable. And §5's first clause says there is "no separate marker type,
  no second carriage of provenance in the request, and no field on `ActionRequest`
  outside the binding that states it": a reader holding only ADR-0150 could read
  that as forbidding §3's field. It does not — §5's clause is about **discloser
  provenance**, whose marker is and stays `EgressSpan.provenance`, and §1 above rules
  the two axes separate — but the misreading is available and the note is what
  forecloses it. §3's field is on the binding, which is where §5 puts the one
  carriage. **Addition, with the note stating which axis §5's clause governs.**
- **ADR-0152.** §5's named residue — that the carrier is empty, every span is
  `SYSTEM_SELECTED`, and "the lane that first records an origin is the lane that
  closes it" — is addressed here in one direction and **not** in the other, and the
  note says which. This ADR records a call-level origin and closes the residue's
  *first* half. It records **no span-level origin**, so no span becomes
  `USER_AUTHORED` by anything here and ADR-0154's condition-13 limit (b) stands
  exactly as attested. A reader holding only ADR-0152 would otherwise read the
  residue as wholly spent. **Addition, with a partial-closure note.**
- **ADR-0154.** §4's item (ii), second clause, names a precondition — "The ADR that
  would permit a standing authorisation … first establishes a **recorded origin** the
  authoriser evaluates at the moment it rules" — and adds "Until such a surface
  exists and an ADR rests on it, the clause above holds as written". The surface now
  exists. A reader holding only ADR-0154 would read the precondition as unmet, which
  is a fact about the tree that has changed. **The floor itself is unchanged**: no
  ADR rests on the surface to lift it, this ADR expressly declines to (§5's fourth
  clause), and §5's second clause adds a floor beneath any later ADR that would.
  §6's residue bullet likewise moves by half, exactly as ADR-0152's does.
  **Addition, and the note records the precondition as met and the floor as
  standing.**
- **ADR-0178.** §7's first clause enumerates what a surface renders before it
  collects the answer, and §6 above adds one fact to that enumeration. A reader
  holding only ADR-0178 would render an egress confirmation without it and believe
  the floor met — which after this ADR's implementation lands is false. That is a
  clause of ADR-0178 that a reader would now act differently on, so the record is
  owed. **This is an amendment to §7's first clause and not a supersession of it**
  under ADR-0070 §1's test: the clause's obligation is extended by one item, its
  subject, its timing and its other seven clauses are untouched, and no decision
  moves. §2's exactly-two-fields clause on `ConfirmationEgress` **is** narrowed by
  §3's third clause, and the note says so in those terms rather than leaving it to
  be inferred.

**No record is owed on the following, and the test is applied rather than asserted.**

- **ADR-0098 — nothing owed.** Every deferral of its §12 that this ADR touches was
  already closed or already assigned: the first bullet by ADR-0106, which wrote that
  record itself; the standing-authorisation bullet by ADR-0154 §4; the actuator
  bullet by ADR-0154 §4's item (i). §3's actuator clause is **applied** here and not
  read more widely — this ADR adds no condition to it and rules on a fact about a
  selection rather than on what a span may do. §5's and §6's marked limits are
  inherited verbatim in §7. A reader holding only ADR-0098 acts identically.
  **Addition.**
- **ADR-0146 — nothing owed.** §1's two members are unchanged and §9's third bullet
  asked for exactly the record §1 above makes, which is a discharge of an
  unmarked instruction rather than a change to a clause. §8's deferred marker was
  spent by ADR-0150 §5 and is not respent here. **Addition.**
- **ADR-0148 — nothing owed.** §1's completeness rule, §3's routes, §6's four facts
  and its determinism clause, and §8's four clauses are used as given. §3's second
  clause is cited as the ratified rule it is; §6's binding gains a member, which
  §6's own text contemplates by making the binding the thing that travels, and no
  clause of §6 becomes false. **Addition.**
- **ADR-0072 — nothing owed, stated because the brief asked either way.** No clause
  of it is changed. §2's `band_of` stays a total function of `MemorySource`, §4's
  keying on `source` is restated by §1's fourth clause without widening, and §5's
  precedence is untouched — §5's own revisit trigger fired long ago and is #663's,
  which this ADR neither discharges nor narrows.
- **ADR-0093, ADR-0095, ADR-0097 — nothing owed.** §4's band rule, §7's declared
  identity, ADR-0095 §1's substitution and ADR-0097 §7's grant-is-not-an-action-
  authorisation clause are each relied on as they stand. This ADR adds no field to
  `Provenance` or `Attestation` and asks no reader to declare anything.
- **ADR-0155 — nothing owed, and this is the one most likely to be assumed
  otherwise.** Its §4 marked clause — that nothing in the payload path "can
  distinguish a span drawn from the assistant's own store from one composed for the
  send", and that no ADR may state or imply otherwise — is **still true after this
  ADR**, because §2's fact distinguishes no span from any other. Its Consequences
  observe that "the corpus gains a second axis on an egress span, and knows it does
  not have it"; this ADR adds a fact about a **call** and still does not give the
  span that axis. **#1154 stays open**, its trigger stays fired, and a lane may not
  cite this ADR toward it. A reader holding only ADR-0155 acts identically.
  **Addition.**
- **ADR-0140 — nothing owed, and its §10 second clause is not lifted.** That clause
  gates email bodies until "ADR-0098 §12's externality-recoverable seam is ratified
  **and implemented**". This ADR is neither the ratification of that seam (ADR-0106
  was) nor an implementation of anything. Whether ADR-0106's merge already satisfied
  the condition is a question about ADR-0140's own text that predates this lane and
  is **filed rather than answered** (#1432, §12). Either way a reader holding only
  ADR-0140 acts identically on the strength of this ADR. **Addition.**
- **ADR-0147 — nothing owed.** Its §6 makes `StepExecution.output` a projection
  defective under ADR-0098 §7's third clause, and §12 defers a durable origin for a
  retained tool result as **#1114**. This ADR adds no field to `StepExecution`,
  reaches no tool result, and does not close #1114. **Addition.**
- **ADR-0163 — nothing owed.** Its §8 leaves open how a mixed-origin episode carries
  its origins, on the ground that "`Provenance` records one origin for a whole
  record" (#1162, #1218). That is a per-span marker *inside one record*, which §2's
  third clause refuses to mint. Neither issue is closed or narrowed here.
  **Addition.**
- **ADR-0170 — nothing owed.** Its §9 leaves open "whether the step-result surface
  should carry provenance". This ADR adds none to it, so §5a's exclusion and §10's
  test are untouched and a lane may not cite this ADR as having relaxed either.
  **Addition.**
- **ADR-0017, ADR-0021 — nothing owed.** §3's fourteen conditions and §6's standing
  grants are neither narrowed nor relaxed. §5's second clause is stricter than
  ADR-0017 §3's third condition obliges and satisfies it by its first limb alone,
  which is the same posture ADR-0154 §4 declared for itself and is declared here for
  the same reason rather than glossed.

**Nothing here is a supersession**, wholly or partially, except the one narrowing
§11 names on ADR-0178 §2. No other decision moves, and the branch touches this file
and five dated header notes.

**This ADR is marked under ADR-0089** and is in the marked regime: its unmarked
prose supplies no obligation and exists to determine what the marked clauses mean
(ADR-0089 §3). Marking is forward-only (§5), and nothing ratified before it is drawn
into the regime by it.

### 12. Deferred, by name, each with the condition that fires it

- **A per-span externality marker** — a field on `EgressSpan` saying that *this*
  span's content came from a source. §2's third clause refuses it, and the Context
  gives the ground: an argument is a value a model produced, and neither inspection
  nor matching may recover its origin. **Fires with a path on which an argument's
  value is **carried** from a recorded-origin value rather than regenerated by a
  model** — a structured argument construction, which #1427's ruling 4 defers out of
  milestone 23. Until then the honest per-span facts are the ones `EgressSpan`
  already carries.
- **Whether a standing authorisation may cover an egress call**, now that the
  recorded origin ADR-0154 §4 asks for exists. §5's fourth clause leaves that floor
  standing and its second clause fixes what such an ADR may not do. **Fires with the
  ADR that establishes standing grants for egress recipients** — ADR-0148 §3's fifth
  clause names the three questions it must answer, and this ADR adds none.
- **A per-read audit record of what a source said and when**, and authorised cloud
  egress in the audit trail. `planned_with_external_content` reaches the trail free,
  by ADR-0148 §6's transcription; the ledger that would make a read reconstructible
  from the trail alone is **milestone 24's** (#1017, #747, ADR-0097 §12's audit
  bullet). **Fires with that milestone.**
- **A structured presentation state for a belief whose warrant rests on recorded
  external content** — ADR-0106 §12's first bullet, filed as **#746**, owned by the
  lane that next revises `Question`, `Belief` and `BeliefSummary`. Untouched here and
  not narrowed: this ADR adds no field to any of those three.
- **Naming which external source a call was planned over.** §3's boolean names none,
  deliberately, on ADR-0106 §2's ground — a richer marker has no consumer today, and
  ADR-0093 §7's declared identity is the only source name this system holds.
  **Fires with the surface that would act on the difference**, and it inherits
  ADR-0098 §8's second clause, whose own trigger — "the second reader" — has fired
  (`readers/email.py` is on `main`) and which stays undischarged. **Filed as #1431**,
  which carries ADR-0093 §11's neighbouring display-label trigger with it.
- **Whether a span was drawn from the assistant's own store or composed for the
  send** — ADR-0155 §4's gap, filed as **#1154**, whose own trigger ("the first lane
  that registers an integration whose declared arguments admit free text") fired
  with `send_email`. It is a third axis, it is per-span, and §2's third clause
  refuses to mint a per-span marker; it therefore fires with the same condition that
  bullet names — an argument path on which a value is carried rather than
  regenerated — and no lane cites this ADR toward it.
- **A durable origin for a retained tool result** — ADR-0147 §12's **#1114**, and
  **how a mixed-origin episode carries its origins** — ADR-0163 §8's **#1162** and
  **#1218**. Both are per-span-within-one-record problems and inherit §12's first
  bullet's trigger. Untouched here.
- **Whether ADR-0140 §10's second clause is already satisfied.** That clause gates
  email bodies on "ADR-0098 §12's externality-recoverable seam … ratified **and**
  implemented"; ADR-0106 ratified and implemented a seam that closes ADR-0098 §12's
  first deferral, and ADR-0140 was written after it while treating the condition as
  unmet. Two readings are available and this ADR takes neither, because the question
  is about ADR-0140's own text and answering it here would decide a neighbouring
  lane's scope by a sentence. **Filed as #1432**, and it fires with the lane that
  would ingest a message body, which must resolve it in its own text before it does.
- **Whether taint survives a planning step** — #301, and this ADR does not close it.
  §2's second clause is explicit that the fact is about a selection and not about
  influence, so a lane taking #301 inherits the field and none of its reasoning.
- **Breadth, deferred by #1427's ruling 4 and recorded here with each trigger.** A
  third reader: fires when a source arrives that neither `CalendarReader` nor
  `EmailReader` covers, and it carries ADR-0093 §11's source-registry and
  display-label deferrals and ADR-0097 §9a's identity-change precondition with it. A
  further actuator: fires with the second tool registered at the designated seam, and
  ADR-0154 §4's attestation clause makes that lane re-check every condition this one
  rests on. A two-phase planner: fires with the per-span marker above, which it is
  the mechanism for. Any classifier: **does not fire**, and §7's second clause is why
  — adding one is a later decision with its own cost argument, and nothing here
  recommends it.

## Consequences

**What becomes easier.** The ADR that opens standing authorisation for egress has
the fact ADR-0154 §4 said it must have before it may exist, so that lane argues about
policy rather than about whether the question is answerable. The CONFIRM card gains
the one thing a user needs in order to treat a plausible-looking send sceptically,
and gains it as a statement about the call rather than as a verdict they must
interpret. Milestone 23's exit stops being a judgement about content and becomes four
figures over two ratified prohibitions — a forbidden belief is a breach of ADR-0106
§6, a forbidden act is a breach of ADR-0154 §4, and neither definition requires
anyone to read a sentence and decide whether it is hostile. And `CarriedProvenance`
stops being a value the tree constructs empty, which is the state in which a contract
is quietly wrong.

**What becomes harder.** `orchestration` has to hold its selection set as far as the
step that emits an egress call, which today it does not; that is the new machinery
§10 assigns to the paired lane, and it is real work rather than threading. Three
frozen `core` models gain a required field, so every construction site in `src/` and
in every fixture states it — the cost `no default` buys, and ADR-0150 §5 already paid
it once for the same reason. `PROTOCOL_VERSION` moves, because `ConfirmationEgress`
is a wire type (ADR-0178 §6's rule), and the implementing lane owes that arithmetic.
And every surface rendering an egress confirmation gains a line, including one that
does not yet render any of ADR-0178 §7's floor.

**The accepted cost, named once more because it is the thing most likely to be
misremembered.** This decision records that external material was *selected* into a
model call. It does not record, and cannot record, that external material *shaped*
the call's arguments — ADR-0098 §5 established that the link is destroyed by a
ratified decision that is right for its own reasons, and ADR-0154 §4 established that
a floor stated over it cannot be implemented. A reader who takes away "we now know
which sends the attacker caused" has taken away the opposite of §2's second clause.

**What would trigger revisiting.** Any of §12's firing conditions. Also: an exit run
under §8 whose ASR-at-gate is high enough that the per-call confirmation is the only
thing between the adversary and a send, which would make §5's second clause the load-
bearing rule rather than the outer one; and the first evidence that users approve
egress confirmations without reading them, which would mean §6's rendering is
containment on paper and would make the per-span marker of §12's first bullet worth
its cost sooner.

## Alternatives considered

**Add a third member to `DiscloserProvenance` — `EXTERNALLY_ORIGINATED`.** The
cheapest possible mechanism, and it is refused for the reason ADR-0146 §9 already
gave: externality "is a different axis". A third member would make the enum answer
two questions at once, and the two answers are not exclusive — a span this system
selected out of an attacker's email is both system-selected and externally
originated. Collapsing them would force every consumer to choose which question the
value answers, and ADR-0146 §1's whole Context is about the cost of asking two
questions as one.

**Put the marker on `EgressSpan` and let the seam infer it from the argument's
value.** Refused twice over: ADR-0146 §2 forbids deciding a span's provenance "by
reading its value, its field or its shape", and ADR-0148 §11 records that its
determinism clause "does **not** rule that provenance is recoverable from an
argument's value, which would be ADR-0146 §2's forbidden inference arriving late".

**Have the producer declare it — a tool, or the model, saying whether its arguments
came from external content.** Refused for ADR-0094 §5's reason, which ADR-0106 §3
and ADR-0154 §4's item (iii) each applied to the neighbouring marker: a producer
declaring its own standing is a claim carried in a submission, and the failure that
matters is not over-claiming but **omitting**, which no validator can distinguish
from an honest `False`.

**State the floor over "an egress call whose destination or payload field is
externally originated", as the dispatching brief's wording proposes.** Refused
because it is the shape ADR-0154 §4 already tried and adversarial review falsified at
round 6 — "nothing durable distinguishes a planner run whose prompt carried an
external span from one that did not, so an authoriser could only guess" — and because
read as an exhaustive statement it would be *weaker* than what is ratified: ADR-0154
§4's first clause closes standing authorisation for **every** egress call at this
seam, and a rule closing it only for externally-originated ones would read as opening
it for the rest. §5's fourth clause is the corrected form.

**Refuse the call outright when `planned_with_external_content` is `True`.**
Refused on ADR-0106 §8's ground one seam over: a system that silently declines
starves the loop that would correct it, and the user learns nothing. The containment
#668 asks for is "a visible, source-attributed proposal — spam, not poison", and a
refusal is neither visible nor correctable. It would also be the first branch in the
tree where a span's recorded facts change a policy outcome, and ADR-0154's
condition-13 attestation records that no gate reads them today; changing that in the
refusing direction would need the attestation re-made for a rule nobody asked for.

**Fold #641's reader-side threat model into a section of this ADR.** Refused in §9
on ADR-0098 §10's already-ratified finding that the two halves genuinely differ, on
the different review sets the two decisions owe, and on ADR-0137 §1.

**Show the marker only when it is `True`.** Refused in §6. A signal that appears
only on suspect calls teaches the user to read its absence as clearance, which is a
bound nobody stated and which ADR-0098 §6's second clause exists to stop the corpus
acquiring.
