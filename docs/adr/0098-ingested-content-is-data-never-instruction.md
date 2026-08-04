# 98. Ingested content is data, never instruction — and the blast radius is bounded by construction

- Status: Proposed
- Date: 2026-08-03
- **Decides a posture and adds no `core` surface.** No Protocol, no type, no error
  class, no field. That is a finding rather than a restraint. **Two** seams this
  posture could have used are absent, and each is deferred in §12 with its trigger
  rather than specified here: a record from which externality is recoverable at the
  ruling point (§5 argues why it cannot be specified until a producer can breach the
  rule), and a `Question` that can name its source (§7 argues why the safety half of
  that obligation does not need it). Golden rule 5 and ADR-0015 §5 put
  a contract ADR in its own PR ahead of any implementation, and this PR carries no
  code for the separate reason that it *rules* on `orchestration`, `planning`,
  `learning` and `interfaces` without touching them.
- **Required review set: adversarial *and* architecture.** This is **declared, not
  compelled.** `CONTRIBUTING.md` → "Stop when the required reviews are green" makes
  a change contract-surface when it touches `core/protocols.py` or `core/types.py`
  "**or when it is the ADR deciding that surface**", and by §5 this ADR decides no
  surface; `scripts/ship.sh` gates the architecture lens on those two files
  changing, and would accept adversarial alone. The set is taken anyway, on three
  grounds: the decision constrains prompt assembly across `planning`, `learning`
  and `orchestration` at once; it binds the later ADR that designates an actuation
  seam (§3); and it is a security posture, where a second independent lens is worth
  more than the convention's minimum. It was **reviewed while `Proposed` and is
  ratified only afterwards**, in a separate lane (#633).
- **Filed as #668.** It **folds the downstream half of #641** and leaves that
  issue's reader-side half open; it **leaves #659** and takes a dependency on it
  (§8, §12); it **touches #663 without discharging it** and adds one named input to
  that revisit (§10).
- **Where this ADR and #668 disagree about the tree, this ADR is the corrected
  record** (Context, "What reaches a model today"). #668's second path names a
  mechanism ADR-0093 §4 forbids, and its citation of ADR-0088 for evidence
  discipline is a mis-citation. The threat #668 describes is real and understated;
  two of the three routes it names are not the routes that carry it.

## Context

### The corpus has recognised this input class exactly once, and never where we ingest on purpose

ADR-0013's diagnostics section refuses to log a provider exception's message, and
the sentence it refuses on is the whole of what this corpus has ever said about
hostile text arriving:

> Provider error text routinely quotes the offending request, so `str(exc)` is
> vendor- and attacker-controlled text that can carry a prompt — Tier 1 data that
> ADR-0004 §5 forbids in a log.

That recognition was applied to a *log*, which is the one destination where the
existing tiering rule already gave an answer. It has never been applied to a
*prompt*. ADR-0004 and ADR-0017 govern data **leaving** the device — `models/` and
a designated `tools/` seam, and nobody else. Nothing in the corpus governs hostile
content **arriving**, and the asymmetry is now load-bearing, because leg 6 ships a
reader whose entire job is to bring other people's text into the store.

The neighbouring recognition is ADR-0012's, and it is about the CI reviewer rather
than the assistant: a successful prompt injection through a diff could exfiltrate
the review key. It is worth naming because it shows the project already reasons
this way when the model in question is Codex, and has not when the model in
question is the assistant's own.

### What reaches a model today, read rather than remembered

At the commit this ADR was written against (`87d9214`), exactly **two** places in
`src/` assemble a message list for a `ModelProvider`:

- `planning.planner.ModelBackedPlanner.plan`, which sends a fixed system prompt
  and one flat user string built by `_render_request`;
- `learning.observer.ModelBackedObserver.observe`, which sends a fixed system
  prompt and one flat user string built by `_render_batch`.

Nothing in `orchestration/` or `context/` builds a prompt; `orchestration.loop`
and `orchestration.observation` are the feeders. `models/` neither assembles nor
inspects — `Message` carries `role`, a flat `content` and an `EncodableText | None`
`name` that no producer in `src/` sets and that `models.provider._to_model_messages`
drops on translation. There are no content parts, and `Role.TOOL` is rejected at
that seam. **So a trust distinction expressed at the message level does not exist
today and is not reachable without `core` surface**, which is one of the two facts
that shape §2.

Both assemblers embed record text in a line-oriented syntax of their own:
`planner._render_record` renders each record as a bullet prefixed by
`[kind/source]`, and `observer._render_batch` renders each episode as a line
prefixed by a `[E<n>]` label. **Neither escapes the embedded text, and neither
checks that it does not contain the syntax it is being embedded in.** A record
whose content carries a newline and a well-formed bullet writes a second bullet
with a source of its choosing; an episode whose content carries `[E7]` writes a
label the model may cite.

### The live chain, end to end — and #668's account of it is wrong in the middle

`readers.calendar._render` builds a belief's canonical text from an occurrence's
`SUMMARY` and `LOCATION` — `Calendar entry "…" at …, …` — and both fields are
**authored by whoever sent the invite**. That text becomes a `SemanticMemory` with
`MemorySource.EXTERNAL`, is ingested through the write path, and is retrieved by
`TurnLoop._retrieve` into `planner._render_record`. **That path is live.** It is
the path #668 does not name, and it is shorter than either of the two it does.

#668's first path — a context facet — carries no attacker string, for two reasons
rather than the one the issue assumes. ADR-0096 §6 rules that "The calendar facet
carries no entry text… no summary, location, description, organiser, attendee or
identifier"; and ADR-0096 was ratified on 2026-08-03 and **is not implemented** —
`ContextFacet` does not exist in `src/` at `87d9214`, and `CurrentContext` is four
temporal scalars that `_render_request` prints as scalars.

#668's second path — "the roadmap routes ingestion into the episodes the observer
reads" — names a mechanism **ADR-0093 §4 normatively forbids**. ADR-0093 is read
throughout this ADR under ADR-0095 §1's substitution, which renames its `Sensor` to
`Reader` and its `sensors/` to `readers/` while leaving its clauses otherwise
intact; quotations keep that ADR's own vocabulary. §4: "A sensor proposes
records in the `ATTESTED` band. It may not propose an `EpisodicMemory`", and
ADR-0093 §11 defers whether one may ever do so. ADR-0077 §1 gives the observer
`EpisodicMemory` records and nothing else, and §3 rules that "The payload is the
batch and nothing else… not the user's existing beliefs, not the profile, not the
context facet, not a plan". **A reader's output cannot reach the observer the way
#668 says it does.**

It reaches it another way, and the real chain is longer and worse:

1. the attested belief is retrieved into the planner's prompt
   (`planner._render_record`);
2. the model returns a plan whose `rationale` is a free-text string it authored,
   under whatever steer the belief carried (`planner._optional_rationale`);
3. `orchestration.engine._exchange_of` folds that rationale into the episode's
   canonical text — "The assistant's plan: …" — beside the user's own utterance;
4. `ObservationStage` selects that episode and `observer._render_batch` puts it in
   the observer's prompt;
5. the observer proposes a durable belief **about the user**, cites the episode,
   and `DefaultMemoryPolicy` rules `ACCEPT` on it whenever the computed confidence
   clears `_min_confidence` and no conflict is detected.

**At no hop after the first is anything about the belief's origin still recorded.**
The episode's `Provenance.source` is not `EXTERNAL`; it is a faithful record of an
exchange that happened. This is not a bug in `_exchange_of`: ADR-0075 §2 ruled that
line deliberately, on the producer's act rather than on where the characters came
from — "The same model output crosses both sides: quoted inside an episode it is
exempt; distilled by leg 3 into 'the user prefers…' it is a proposal like any
other." The consequence is that **the externality is destroyed by a ratified
decision that was right for its own reasons**, and §5 is where this ADR says so
instead of pretending otherwise.

**How much of that chain is armed.** `calendar_reader_interval` defaults to `None`
and `Engine.ingest` has no client surface — its only caller is the hub's scheduler
(#659) — so step 1 requires an operator to configure a path and an interval.
`observation_interval` also defaults to `None`, but `assistant observe` is a
shipped CLI command reaching `Engine.observe`, so **steps 4 and 5 are reachable
today with no configuration at all**. The accurate statement is therefore neither
"the exposure is small" nor "it is already running": one end of the chain is
disarmed by a default and the other is not, and arming the first end is one
setting.

### Three defences that are weaker against a steered model than against a mistaken one

#668 lists what already helps, and it is right that the pieces exist. Three of them
help less than the list implies, and saying so is most of this ADR's value.

**The `ATTESTED` band caps standing, not steering.** ADR-0072 §2's mapping is a
total function of `MemorySource` and ADR-0092 §1 makes an `Attestation` mandatory
and exclusive to the band, so an attested belief cannot claim to be the user's
word. That bounds what the record *asserts*. It does not bound what a model, having
read the record, is induced to *do* — propose, plan, or later act. The band is a
statement about provenance; injection is an attack on behaviour.

**Evidence discipline authenticates the id, never the support.** ADR-0077 §5 is
strong where it aims: ids are the producer's and never the model's, a label that
does not map is dropped, a proposal left citing nothing is discarded, and
`MemoryIngestor._require_resolvable_evidence` refuses a derived belief citing a
record the store does not hold. Together these guarantee that a citation names a
record the model was actually shown and the store actually holds. **They guarantee
nothing about whether that record supports the belief.** The `INFERRED` floor —
two distinct episode ids — counts what the model chose to cite, so a steered model
clears it by citing two episodes it was shown. Against confabulation the discipline
is decisive; against steering it is a formality. That distinction was invisible
while the only failure mode considered was a model being wrong by accident.

**"Readers are deterministic parsers with no model access" relocates the injection
point; it does not remove it.** #668 states this correctly and then draws the
comfortable half of the conclusion. The reader is not the injection point precisely
because it is a *faithful* transcriber: it carries the attacker's sentence through
without alteration and hands it to the model-backed consumers downstream. A reader
that reasoned about content would be a worse design and a smaller channel. The
determinism is a reason to trust the reader and no reason at all to trust what it
produces.

### The one thing the corpus already does, in a different medium, and has never done for the prompt

ADR-0042 §4 rules that "The engine carries semantic data; escaping is the
adapter's, per target", because a value like `\x1b[2J` "is valid data that a
terminal would interpret as a control sequence". `interfaces.cli._safe` implements
it: replace non-printable characters, escape Rich markup. The corpus therefore
already holds the exact principle this ADR needs — **a rendering target has a
syntax, and untrusted data is escaped for that syntax at the point of render** —
and applies it to the terminal, which cannot be steered, while not applying it to
the model, which can. §2 is that principle applied to the medium where the
consequences are larger.

### An honest statement of what this ADR is not allowed to settle

- **It may not re-decide ADR-0075 §2's producer line**, which is what erases
  externality at step 3 of the live chain. Moving it would make quoted model output
  non-exempt and reopen episodic capture. §5 records the residual instead.
- **It may not build the seam it would need.** A `MemoryPolicy` that can see
  whether a proposal's evidence is external needs either a field on
  `MemoryUpdateProposal` or a wider `decide` signature; both are `core` surface,
  and ADR-0073 §4's "with a producer in hand" standing is missing, because no
  producer on `main` can breach the rule (§5).
- **It may not decide the reader's own adversary model** — hostile `.ics`, a
  compromised sync peer, a public feed's tier. That is #641's reader-side half and
  §10 leaves it there.
- **It may not decide the actuator or egress design, and may not narrow ADR-0017
  §3 or ADR-0021 §6 in the attempt.** ADR-0017 §3's fourteen conditions and
  ADR-0021 §6's standing grants are ratified and are their lanes' to extend. §3
  states one obligation the actuator lane inherits, adds no condition to that list,
  and leaves the one question that would have narrowed both open by name.
- **It may not narrow ADR-0021's audit trail into a memory-ruling trail.** ADR-0021
  types the trail on `PermissionDecision` and mentions memory only as a contrast;
  a durable record of a memory ruling is an unclaimed gap, and §8's legibility rule
  is written so as not to assume one.

## Decision

Marked under ADR-0089: every obligation this ADR imposes is a marked clause, and
unmarked text supplies none.

### 1. The class: external content is text this system neither authored nor received from its user

> **Normative.** **External content** is any span of text that this system did not
> author and did not receive from its own user. A source's fields, a message body,
> a feed entry, a tool or MCP result, a provider's error text, and a third party's
> speech captured by a spoke are all external content, whatever subsystem carries
> them and whatever type they are stored in.

> **Normative.** Membership of the class is decided by **recorded origin**, never
> by inspecting the text.

> **Normative.** `MemorySource.EXTERNAL` is external, and any `MemorySource` added
> later is external unless the ADR adding it argues otherwise in its own text.

**An allow-list, for ADR-0092 §4's reason.** That section widened the supersedable
class to `{OBSERVED, INFERRED, EXTERNAL}` and insisted the set stay "enumerated
membership, never `is not USER_ASSERTED`", so that "a `MemorySource` added later is
not silently enrolled in a destructive rule by omission". Here the enrolment runs
the other way and the same shape is wanted: a source added later is enrolled in the
*protection* by default and must be argued out of it, not into it.

**Defined on origin rather than on subsystem, because the subsystem boundary does
not track the threat.** `readers/` is the obvious producer of external content and
it is not the only one: ADR-0013 already found it in a provider exception,
ADR-0094 §5 anticipates it in a spoke's submission, and the roadmap's MCP tools
will return it from a server nobody in this project wrote. A rule keyed on
`readers/` would have to be rewritten three times; a rule keyed on origin is
written once and each of those lanes inherits it.

**What is deliberately *not* external.** The user's own utterance is not, however
it was composed — a user who pastes an email into a turn is exercising judgement,
and treating their words as hostile would make the assistant unusable while
protecting nothing the user did not choose. §5 records what that costs.

### 2. The prompt is a rendering target, and external content is escaped for it

> **Normative.** Every span of external content that reaches a model call is
> presented to that model as third-party data, distinguishable from the system's
> own instructions and from the user's own words.

> **Normative.** That distinction is **not forgeable from inside the span**. The
> attribution the assembled prompt expresses — which span is whose — is a function
> of the data the assembler held, and no sequence of characters inside a span may
> change it. An assembler that embeds a span in a syntax the serialised span can
> itself produce does not conform, whatever labels it emits.

> **Normative.** The marking is derived from data the system holds about the span
> — `Provenance.source`, an `Attestation`, a facet's source — and never from
> inspecting the text.

> **Normative.** This ADR fixes what the assembler must convey and what must not be
> forgeable. It does not fix the wording, the delimiter, or the mechanism.

**This is ADR-0042 §4 in the one medium it was never applied to.** "Escaping-for-a-
target is rendering", and a model provider is a target with a syntax — the syntax
the assembler itself invented one function earlier. `interfaces.cli._safe` neutralises
control characters and Rich markup before writing to a terminal; nothing neutralises
a bullet or a label before writing to a model. The two assemblers on `main` are the
whole trust boundary, and both currently interpolate raw.

**Non-forgeability is the clause that has teeth, and it is stated separately
because the obvious reading of "label it" does not imply it.** `planner._render_record`
already emits `[kind/source]` on every line — a label, derived from held data,
exactly as the first and third clauses require — and it is defeated by a belief
whose content contains a newline and a second bullet claiming
`user_asserted`. `observer._render_batch`'s `[E<n>]` labels are defeated the same
way, and there the forgery is worse than cosmetic: a forged in-content label that
happens to map lets one episode supply what ADR-0077 §5's `INFERRED` floor counts
as two distinct supports. **Delimiting untrusted text with a delimiter that
untrusted text may contain is not a defence**, and the corpus should not acquire
one that looks like it is.

**One admissible construction, and it is deterministic.** The span is transformed on
render so that the container's syntax is **unrepresentable** in the serialised
result — escaped, replaced, or encoded — which is the terminal adapter's approach in
`interfaces.cli._safe` and is implementable against a flat `EncodableText` today.

**An unguessable terminator is not the second option, and adversarial review was
right to say so.** An earlier draft offered "a container whose terminator the span
cannot guess" as an alternative. A random nonce makes a collision *unlikely*; the
clause above admits no character sequence at all, so the two do not meet. Offering
it would have let an implementing lane reintroduce delimiter injection while
believing it conformed — the exact failure this section exists to name — and a
nonce scheme that additionally escapes a span containing the nonce is just the
deterministic construction with extra machinery. The probabilistic option is
therefore removed rather than qualified.

Expressing the distinction structurally instead — content parts, a trust-carrying
field — is not available at the `ModelProvider` seam: `Message` has `role`, a flat
`content`, and a `name` no producer sets and `models.provider._to_model_messages`
discards. §12 defers that as surface with its trigger.

**Marking derived from held data, never from the text, is the same rule ADR-0094 §5
states for a band**: "a claim carried in a submission is not evidence of the
standing it claims". A prompt assembler that decided how to label a span by reading
the span would be letting the attacker choose their own label.

**This division follows ADR-0072 §6's own.** That section ruled that a derived
belief reaching a prompt is rendered as a belief and then said: "The rule constrains
*what the assembler must convey*, not the wording it uses; the prompt-assembly lane
owns the phrasing." §6 is ratified and, at `87d9214`, not satisfied — the
`[kind/source]` bullet is the de facto stand-in, and there is no prompt-assembly
module. This ADR adds a second thing the assembler must convey and one property the
conveyance must have; the lane that finally lands still owns the phrasing of both.

### 3. Instructions inside external content are data, and external content may not be the authority for an action

> **Normative.** Imperative text inside external content is **data**. No component
> of this system acts on a **recorded external span** as an instruction: the span
> may not select a code path, set or alter a parameter, or change a policy decision.

> **Normative.** External content is never placed in a message the prompt's own
> structure attributes to the system or to the user — never in a `Role.SYSTEM`
> message, and never inside the region a `Role.USER` message presents as the user's
> own words. This is §2's obligation read on position rather than on labelling, and
> both must hold.

**Both clauses are stated on the *span* — the text whose origin is recorded — and
earlier drafts of both reached past it.** They said that "no consumer of this system
treats it as an instruction" and that no prompt places content "where a **model
would read it** as an instruction" — conditions whose truth depends on an inference
nobody can make deterministically, over a `Message.content` that is one
undifferentiated string. A third draft of the first clause still forbade a span from
determining "what any subsequent call does", which is the same overreach one hop
further out: once a planner's model has read a span and returned an `ActionPlan`,
tool selection receives the model's output and not the span, and §5 establishes that
nothing recovers the link. Architecture review named that on round 3, and the limb
was removed rather than qualified — an unbounded transitive prohibition over a
relation nobody can evaluate is not a weaker rule than the direct one, it is an
unenforceable one wearing the direct one's clothes. **The indirect case is not left
uncovered; it is covered by the things that do not need the link**: §4's ceilings on
what the resulting belief may become, and this section's actuator clause on what may
authorise an action.
Adversarial review found it on round 2, and it is the same defect the architecture
reviewer found in this section's actuator clause on round 1: **a bound stated over
something this system cannot obtain.** That is the discipline §5's clause and §6's
second clause each impose about detection, read here on model obedience — and this
section broke it twice before either reviewer arrived, which is the best evidence
available that the pull toward it is a property of the subject rather than of any
draft. Both clauses are now stated over what a serialiser and a caller do, which is
checkable in a test.

**What is therefore *not* promised, said plainly.** A model that reads a
well-marked, correctly positioned external span may still follow an instruction
inside it. Marking, escaping and positioning make that less likely and make the
system's own conduct correct; they do not make the model obedient, and no wording
in this ADR should be read as claiming they do. **That is the reason §4's ceilings
and this section's actuator clause exist at all**: they hold whether or not the
model was fooled, which is what "bounded blast radius by construction" means.
A posture that needed the model to resist would be VISION §Principle 3's "Trust
cannot depend only on a prompt telling the model to be careful" with the prompt on
the other side.

> **Normative.** No actuator is selected, parameterised, or confirmed by external
> content.

> **Normative.** The clause above binds the later ADR that designates an actuation
> or egress seam. It adds no condition to ADR-0017 §3's list and relaxes none of
> them; those fourteen stand exactly as written.

> **Normative.** Whether a **standing** authorisation — ADR-0021 §6's standing
> grants, or ADR-0017 §3's "**Recipient authorisation that traces to a user
> decision or a standing user policy**" — may cover an action a model selected
> while reading external content is **not settled here**. The lane that designates
> an actuation seam decides it explicitly, and may not inherit an answer from a
> rule written before any actuator existed.

**The actuator clause is ruled now because it is free now and expensive later.** No
actuator exists on `main`: `Role.TOOL` is rejected at the provider seam, no tool
transmits (ADR-0017 §1), and the roadmap defers tools to MCP. This is the moment
the rule costs nothing to state and constrains nobody's shipped code — and the
moment after the first actuator lands is the moment it becomes a supersession
instead of a paragraph. #668 names the "lethal trifecta" — attacker-authored input,
accumulated private memory, actuators with egress — and this ADR rules the third
leg negatively where it can, leaving the actuator's own design open.

**The line is drawn on the *span*, not on the model output downstream of it, and
an earlier draft drew it in the wrong place.** That draft forbade an actuator
driven "by a model output produced from external content without an intervening
user decision on that action", which is two defects in one sentence. It would
have narrowed ADR-0017 §3's standing-user-policy condition and ADR-0021 §6's
standing grants while §11 claimed it narrowed neither — architecture review found
exactly that on the first round. And it would have been a bound this ADR cannot
obtain: §5 establishes that "produced from external content" is **not recoverable**
once a model's output has been recorded truthfully, so a flat prohibition on it is
the unobtainable bound §6's second clause forbids anyone from stating. Ruling on
the span, where the origin is recorded, is the part that can actually be checked.

**What the retained clause forbids, and why it collides with nothing.** The system
closing the loop itself: content selecting the tool, content supplying the
parameters, content satisfying a confirmation. ADR-0017 §3's recipient-authorisation
condition is about *who may receive*, and its binding condition already insists that
"What is transmitted is bound to what was authorised… and consumed unchanged" —
content supplying arguments moves the semantic recipient those arguments select,
which that condition is already fighting. ADR-0021 §6's standing grants authorise a
*class of action*; nothing in them says content may choose one. The permission
chassis holds the shape — ADR-0042 §4 keeps the adapter from authoring the outcome,
and "`ActionPolicy.resolve`… is what turns `approved` into an `ALLOW` or `DENY`" —
and this clause names which inputs may never reach that resolution as authority.

**A user's own decision is never external content**, by §1: a user who reads "your
3pm moved" and says "cancel it" has decided; the entry that prompted them is not
the authority, they are. That is a consequence of §1's class, not an exception
carved into this section.

**It says nothing about which actions are permitted.** VISION §Principle 3 governs
that, and ADR-0021 §6's standing grants are untouched — the standing-authorisation
clause above leaves the one question that could have narrowed them open by name
rather than answering it.

### 4. Three ceilings on what external content may become

> **Normative.** No record whose content or evidence is external is written in the
> `ASSERTED` band, and no producer proposes one that would be.

> **Normative.** A producer does not raise the band of what it proposes by any
> means, including by claiming a `MemorySource` it is not.

> **Normative.** Where `orchestration` assembles a payload for a model-backed
> producer from material of mixed origin, the payload carries §2's marking within
> itself. The obligation is the assembling caller's, not the producer's.

> **Normative.** A model-authored proposal whose externality is recoverable at the
> ruling point is never auto-accepted into durable memory. Its terminal ruling is a
> user question or a refusal.

**The first two hold today by construction, and are written so they survive the
next producer.** `band_of` is a total function of `MemorySource` whose wildcard
"does nothing but `assert_never`" (ADR-0094 §5), `ASSERTED` is reached only through
`USER_ASSERTED`, and no producer that reads a source proposes that. ADR-0072 §4
already rules that "the standing is keyed on `source`, never on `confidence`, so no
producer can promote a belief into the profile by claiming certainty", and ADR-0094
§5 rules the same for a spoke's submission. These clauses are that rule read on the
one axis neither of them covered — the *origin of the content*, rather than the
identity of the producer — and they are worth stating precisely because they cost
nothing while they hold and are unrecoverable once broken.

**The third is the containment rule, and it is enforceable today.** It is ADR-0077
§3's posture generalised: that section keeps beliefs, the profile and the facet out
of the observer's payload on minimisation grounds, and the same seam is where a
mixed-origin payload would be assembled if anything ever assembled one. Putting the
obligation on `orchestration` rather than on the producer follows ADR-0077 §1's own
division — "Selection therefore belongs to `orchestration`", the one place holding
both stores — and it is fail-closed against a producer that forgets, because the
producer never had the choice.

**The fourth binds forward, and §5 says exactly how far forward.** It is the rule
#668 asks for, with one correction: #668 writes that "the `MemoryPolicy` dispose
gate never auto-`ACCEPT`s a proposal citing external-source evidence", and taken at
its word that is either vacuous or wrong. Vacuous, because a reader's own proposal
is `EXTERNAL` and cites nothing — ADR-0072 §3 requires citations of the `DERIVED`
band and exempts records that "legitimately cite nothing" — so no shipped proposal
matches the description. Wrong, if stretched to cover the reader's own output,
because it would route every calendar entry to the user as a question and make the
reader useless. The distinction the rule actually needs is between a **faithful
transcription** — a reader saying what its source says, at a band that already
caps its standing — and a **model-authored generalisation about the user** that an
attacker's sentence helped produce. Only the second is ruled here.

### 5. What is not enforceable, stated so that nothing claims it

The fourth clause of §4 says "recoverable at the ruling point", and this section is
why those four words are in it rather than a cleaner phrase.

**At `87d9214` nothing on `main` can breach that clause, and nothing can enforce it
either.** The only producer of `DERIVED` records is the observer, whose citations
are episode ids (ADR-0077 §5), and no episode is `EXTERNAL` because a reader may
not propose one (ADR-0093 §4). So no derived belief on `main` cites external
evidence, and the clause has no subject to bite. And the
seam that would give it one does not exist: `MemoryPolicy.decide` receives a
proposal and a sequence of conflicting records, and holds no store, so it cannot
resolve the ids in `Provenance.evidence` to see what they are. `MemoryIngestor`
*does* resolve them — `_require_resolvable_evidence` reads each cited record — but
it resolves them **before** the policy runs and may not re-rule afterwards: ADR-0081
§3 is explicit that the writer refuses by raising rather than returning "a
fabricated `REJECT`", because "a ruling is the policy's to make (ADR-0005 §3) and a
writer inventing one puts a decision nobody made into the ingest result". A
writer that converted an `ACCEPT` into a question would be inventing a ruling
nobody made.

> **Normative.** No lane may implement the fourth clause of §4 by having the writer
> substitute a ruling the policy did not make.

**And on the live chain of the Context, externality is not recoverable at all.** The
attacker's sentence reaches a durable belief through a plan rationale that our own
model authored and `engine._exchange_of` recorded truthfully. The episode is
`OBSERVED` because an exchange really did occur. Every provenance field along that
path is correct. **There is no field to read, and adding one would require
re-deciding ADR-0075 §2's producer line**, which this ADR is not allowed to touch
and would not want to: that line is what makes episodic capture possible at all.

> **Normative.** No ADR, lane, or surface may state or imply that this posture
> detects external content embedded in text whose recorded origin is not external.

It does not, and the containment available for that case is §4's band ceilings, the
producer floors already ratified, and the user's correction — never detection.

**What does bound the undetectable case, honestly enumerated.** The belief lands in
the `DERIVED` band, so a user assertion retires it (ADR-0038, ADR-0072 §4); its
confidence is computed by the producer and is "strictly below 1.0 always" (ADR-0077
§5); the observer's utility bar refuses proposals that are not about the user and
would not change a later answer (ADR-0077 §2); output is capped at
`observation_max_proposals`; and the belief is rendered as a belief carrying band
and confidence (ADR-0072 §6) so the user can see and correct it. That is a real
containment and it is not a prevention. The distance between those two words is
this ADR's accepted cost, and naming it is preferable to a rule that would look
like it closed the gap.

**Why the seam is deferred rather than specified now.** ADR-0073 §4 sets the
standing test for a decision of this shape — whether a `Provenance` field is owed
"is a `core` decision for that lane — **with a producer in hand** — not one to guess
here" — and ADR-0094 §10 declined the same surface on the same ground. It is not met
here. Specifying a taint field today would mean choosing between a producer-declared flag
(which lets a producer decide its own standing, the move ADR-0094 §5 refuses) and a
caller-stamped one (which needs a caller that mixes origins, and there is none)
with no evidence about which the first real case wants. §12 defers it with the
trigger that supplies the evidence.

### 6. Detection is not the plan, and no bound in this corpus may be bought from a filter

> **Normative.** No detector of injected instructions is a gate. Its output may not
> raise a band, satisfy a ceiling of §4, permit an auto-acceptance, or authorise an
> action.

> **Normative.** No ADR, lane, or surface may state a bound it obtains from such a
> detector. A detector may be added as defence in depth and is reported as
> best-effort.

**VISION §Principle 3's first line is the argument**: "Trust cannot depend only on
a prompt telling the model to be careful." A classifier is that sentence with a
model in place of the prompt — a probabilistic judgement about adversarial text,
made by the class of system the adversary is already steering. The posture is
bounded blast radius **by construction**: caps that are total functions, gates that
are deterministic, provenance that is recorded rather than inferred, and a marking
that cannot be forged from inside the data.

**The second clause is the one that matters in a year.** The failure mode is not
adding a filter; it is a later ADR reasoning "the filter catches that" and
therefore relaxing a ceiling — at which point the ceiling depends on a component
whose failure rate nobody measured and whose bypass nobody will notice. ADR-0013
has the precedent for the shape of an honest bound: it names what its taxonomy
mapping buys ("provider-controlled naming, which is the realistic threat") and then
says plainly "It is not a sandbox", with the out-of-scope case stated rather than
implied.

### 7. The escalation surface is a rendering target too

> **Normative.** A surface that presents a proposal, a question, a ruling, or a
> belief to the user presents every span **its projection identifies as external**
> as **third-party content**: words the surface does not attribute to the assistant
> and does not attribute to the user.

> **Normative.** That presentation holds under §2's non-forgeability property, read
> against the presenting surface's own syntax.

> **Normative.** A projection that carries content which may be external, and
> carries no origin for it, is **defective in that respect**. The obligation falls
> on the ADR that defines or next revises that projection, never on the surface
> reading it, and never as licence to present the span as the assistant's words.
> §12 names the ones known when this was written.

> **Normative.** Naming **which** source is §8's obligation, and is owed only on a
> surface that holds the source. The first clause is met without it.

**Every mitigation in this ADR terminates at a human, and that is where the text
arrives least examined.** §4's fourth clause routes a suspect proposal to a user
question; ADR-0078 makes that question durable and re-presentable; `DefaultMemoryPolicy`
already rules `ASK_USER` on secret-tier data and on a conflict with a user assertion.
Each of those puts attacker-authored text in front of the user under this system's
own framing — "the assistant would like to record that…" — which is precisely the
voice a phishing payload wants to borrow. **Escalating to the user is not a
mitigation if the escalation is where the attacker's sentence is read as ours.**

**Third-party presentation and non-forgeability are separate clauses because an
earlier draft had only the second, and the second alone does not close the case
this section names.** That draft required a §7 surface to render an external span
"under §2's non-forgeability property" and nothing more — which a surface satisfies
by escaping markup and control characters while still printing *The assistant would
like to record: &lt;escaped attacker prose&gt;*. The span is then unable to break the
frame and is still wearing the assistant's voice, which is the whole of the phishing
case. Adversarial review found it on round 4. **§8 does not cover the gap either**:
its attribution clause is scoped to a *stored belief* on the inspection surface, and
a question, a proposal and a ruling are none of those.

**The third clause exists because the round-4 repair over-reached, and the tree
said so.** That repair required the span to be "attributed to its source", and
adversarial review found on round 5 that **the durable-question path cannot satisfy
it**: `DefaultMemoryPolicy` rules `ASK_USER` on a proposal conflicting with a user
assertion, `QuestionStage` projects it into `core.types.Question`, and that model —
`extra="forbid"`, `frozen=True` — carries `content`, `kind`, `band`, `rationale`,
`reason` and no `Attestation` and no `reported_by`. A client can say *attested* and
cannot say *from your calendar*. Verified against `core/types.py`; the finding
holds.

**The third clause is what makes this section terminable, and it arrived four
rounds late.** Rounds 5 through 8 each found a different projected field that
cannot carry an origin — `Question` has no `Attestation`, `Retirement` has neither
band nor source, and the §4 seam's marker does not exist — and each was answered by
narrowing the clause around that one field. That is whack-a-mole, and the fourth
instance is what made the shape visible: **§7 was written as an unbounded obligation
over projections that were never designed to carry provenance**, so every field is a
finding waiting to happen. The third clause closes the class instead. A surface is
bound by what its projection gives it; a projection that can carry an external span
and no origin for it is defective, and the debt sits with the ADR that owns that
projection. A fifth such field is already answered.

**Two are known and named now.** `core.types.Question` — `extra="forbid"`,
`frozen=True` — carries `content`, `kind`, `band`, `rationale`, `reason` and no
`Attestation` and no `reported_by`. `core.types.Retirement` carries `record_id` and
`content` and nothing else, so a question's "what accepting would retire" can render
an external calendar record with no marker at all: a user assertion conflicting with
both a prior assertion and an attested record produces exactly that. Both verified
against `core/types.py`. Neither is a licence — a surface that cannot say *this is
from a source* must not therefore say *this is the assistant's*.

**The repair to the second clause is to state the obligation at the granularity that
carries the safety property, not at the one that reads best.** What defeats the phishing case is the
user knowing the words are **somebody else's**. Naming the source is *legibility*,
which is §8's subject and which §8 already bounds to source granularity and no
finer. Splitting them that way keeps the safety half binding on every surface today,
keeps this ADR free of `core` surface, and leaves a real residual rather than a
pretended one: **a question cannot name its source.** §12 defers that with its
trigger.

**Which projected field carries the safety half depends on the proposal, and the
two reviewers disagreed about it — the second was right.** Adversarial review argued
on round 6 that `Question.band` cannot carry it for the case §4's fourth clause
exists for: a model-authored proposal citing external evidence is `OBSERVED` or
`INFERRED`, so its `band` is `DERIVED`, and a client rendering `DERIVED` faithfully
says *the assistant inferred this* about a proposal an attacker's sentence helped
produce. A clause was added requiring the externality marker to propagate into the
projection. **Architecture review then found that clause incoherent, against this
ADR's own §1, and it was removed rather than repaired.**

**The reason it is incoherent is worth stating, because the mistake is easy and this
document made it under review pressure.** §1 defines external content by the
**recorded origin of the text**. A derived proposal's content is a sentence *our*
model wrote; the attacker's text is nowhere in it. External evidence *warranted* the
inference and did not *author* it — and §5 has already established that the
influence is not recoverable in any case. So §7's first clause, which is about
spans that are themselves external, does not reach that proposal's content, and a
clause pretending it does would either misattribute assistant-authored text or
smuggle in a provenance category this ADR never defined. **A finding is a hypothesis
to check against the text**, and round 6's was accepted without checking it against
§1 — which is the one process failure in this lane worth recording.

**The residual is real and is a different question, deferred rather than answered.**
An inference that stands on external evidence is not third-party text, and it is
also not quite an ordinary inference: its warrant came from outside, and a user
inspecting it has an interest in knowing that. Naming that state is a *presentation*
decision about evidence provenance — ADR-0073 §4's "why it is held" and §8's
subject, not §7's — and it needs the seam of §12's first deferral to exist before
there is anything to present. §12 defers it there, beside the marker it would read.

**Where §7 does bite on such a surface, and it does**: a question rendering an
external belief it would retire, or a rationale quoting the source, carries genuine
external spans, and the first two clauses govern those exactly as written.

**Five times across eight rounds this document reached past what the tree or its own
definitions supply** — §3's two model-obedience clauses, §3's transitive limb, §7's
source attribution, §7's propagation clause, and §7's unbounded scope — and every
one was caught by a reviewer rather than by its author. That is recorded rather than quietly fixed, for
the reason ADR-0089 §2 records its own defect: the pull toward stating a property
one layer further out than the data supports is a property of writing about this
subject, not of any one draft.

**The division is ADR-0042 §4's, unchanged and deliberately re-stated rather than
re-decided**: the engine carries the value verbatim, the adapter escapes for its
target. `interfaces.cli._safe` already does the escaping half for the terminal, and
does not do the attribution half, because nothing until now asked it to.

**It does not restate ADR-0073 §4.** That floor governs what the band-scoped
inspection surface must *convey* per belief — band, confidence, kind, content, why
it is held. This clause governs what the surface must not let the content *do* to
the surface's own framing. Both bind the same screen and neither implies the other.

### 8. Audit legibility: the band today, the source undischarged, the author never

> **Normative.** A belief whose content is external is inspectable as such: the
> surface conveys that the content came from **a source the user connected**, and
> neither from the user's own word nor from this system's inference.

> **Normative.** Naming **which** source is **not discharged**. It binds the ADR
> that next revises the projection carrying a belief to an inspection surface, and
> binds no surface that cannot do it. §12 records it as live.

> **Normative.** No surface claims to identify the author *within* a source.
> `Attestation.reported_by` names a reader's declared identity and nothing finer,
> and a surface that renders it as though it named a person asserts what this
> system does not hold.

**The first clause is satisfied today, and by the band rather than by anything new.**
ADR-0073 §4's floor already requires the band on every inspected belief and forbids
presenting an attested belief "as the user's word or as our inference", and
`Provenance._attested_iff_attestation` makes the `Attestation` mandatory and
exclusive, refusing a belief that would "acquire the standing of a band it is not in
by citing a source that never reported it". What this clause adds is that the
requirement is now a *security* property and not only an epistemic one, so a later
surface that drops the band for brevity is dropping a defence.

**The second clause exists because an earlier draft asserted the opposite of the
tree, twice in one sentence.** It required the surface to convey that the content
came "from a **named** source", and the prose called that "nearly discharged
already". Both are false. `core.types.Belief` carries `id`, `band`, `kind`,
`content`, `confidence`, `last_updated`, `evidence` and `valid_until` — **no
`Attestation` and no source** — and `BeliefSummary` likewise; `grep -rn attestation
src/ai_assistant/orchestration/*.py src/ai_assistant/interfaces/cli.py` returns
nothing. The `Attestation` exists on the stored `Provenance` and is dropped by the
projection. `interfaces.cli` says so in its own words on the attested branch:
*"Which source, and when it said so, are not recorded."* So the clause obliged
something no surface could do, and the prose beside it claimed the obligation was
nearly met. Adversarial review found it on round 10.

**Three tiers, and stating them separately is the honest version.** This system can
say **"a source you connected reported it"** today; it cannot yet say **"your
calendar"**; and it will never say **"Bob"**. The first is the band and is the
safety property §7 also rides on. The second is a projection gap, live and
undischarged. The third is refused on principle by the clause below.

**This is the third instance of one shape, not a new discovery.** `Belief` and
`BeliefSummary` already cannot carry a belief's elided-citation count (**#568**),
`Retirement` cannot carry a retired record's origin (**#673**, §12), and now the
`Attestation` does not survive the projection either. **The lossy inspection
projection is a known, tracked property of these types**, and §7's third clause
already assigns that class of debt to the ADR owning the projection rather than to
the surface reading it. This ADR states its gap and adds no `core` surface to close
it, for the reason it declined the same move at §5 and §12: the fix is a contract
decision on another subsystem's types and is a lane of its own.

**The third clause narrows #668's fifth bullet, deliberately.** #668 asks that the
user be able to see "this came from an email someone sent you". This system can
honestly say "this came from your calendar" and cannot say who sent the invite —
because ADR-0093 §7 rules that a reader's identity is "**declared by the sensor**
and is not a configurable value… never derived from the source's location or
contents", on the ground that "A free-text setting is precisely the mechanism by
which a user would put their email address or a path there", into `Provenance`,
every export and every log line. Attributing to the author within a
source would mean carrying an organiser's or a sender's identity on the record,
which is a Tier 1 decision nobody has taken and which this ADR does not take.
**Promising the finer attribution and delivering the coarser one is worse than
promising the coarser one**, because a user who reads "someone sent you" will read
the name they are shown as that someone.

**What this section deliberately does not require.** It says nothing about reporting
a *refused or capped* proposal, which is #668's other half, and the omission is
forced: `Engine.ingest`'s only caller is the hub's scheduler, which reads no job's
result, so a ruling made on the ingestion path reaches nobody at all. That is
**#659**, exactly and generally, and §10 records the dependency rather than ruling
over it with a channel that does not exist. ADR-0021's trail is typed on
`PermissionDecision` and holds no memory ruling; §12 defers that too.

### 9. What the implementing lanes owe

No lane is owed by this ADR alone; each of these rides with the lane that would
otherwise breach a clause. **The test below is marked, and the rest of this section
is not**, for a reason adversarial review had to point out: §11 puts this ADR in
ADR-0089's marked regime, where unmarked text supplies no obligation at all. An
earlier draft stated the injection-regression test in this section's first bullet
and called it "the clause" — which, under this ADR's own declared regime, obliged
nobody. A prompt-assembly lane could have shipped with no such test and conformed.
It is now a clause, at column 0, because ADR-0089 §2 also rules that a normative
clause "cannot live inside a list item".

> **Normative.** A lane that implements §2 for a prompt assembler ships a test
> that renders a record whose `content` contains that assembler's own container
> syntax — its bullet, label, header, and newline structure — and asserts that the
> assembled prompt's attribution of every span is unchanged by it. A test asserting
> only that a label is present does not satisfy this clause.

- **The prompt-assembly lane** (ADR-0072 §6's, still unbuilt; filed as **#672**)
  owes §2 in full for `planner._render_request` and `observer._render_batch`,
  including the clause above.
- **The same lane** owes the observer's label scheme the same property, and should
  record that the `INFERRED` support count rests on it (ADR-0077 §5).
- **Whoever lands ADR-0096's `ContextFacet`** owes §2 for any facet field that is
  ever rendered into a prompt. ADR-0096 §6 keeps entry text out of the calendar
  facet, and §6's own closing paragraph makes `entries` an additive later
  possibility — the lane that adds it inherits §2 and should be told so in its ADR.
- **The lane that builds the seam of §5** owes §4's fourth clause its enforcement
  point, and owes the choice between a caller-stamped and a producer-declared
  marker an argument against ADR-0094 §5.
- **Every client surface** owes §7 for its own target, on ADR-0042 §4's division:
  the third-party presentation *and* the non-forgeability, which are two clauses
  because either without the other leaves the phishing case open.
  `interfaces.cli._safe` is the model for the escaping half and supplies nothing for
  the presentation half.
- **The first actuator lane** owes §3, and owes it in its own tests rather than in
  prose.

### 10. #641, #659 and #663 — what is folded, what is left, what is narrowed

**#641 is split, and only its downstream half is folded here.** That issue asks four
questions. The second — "What can a crafted entry do downstream? … What is the blast
radius of attacker-controlled text there?" — is this ADR, and §§2–8 answer it. The
other three are a different scope and stay open: what the adversary at the seam is
(a hostile feed publisher, a compromised sync peer, another local process writing to
the watched directory), whether ADR-0093 §4's "`sensitivity` chosen for what the
source holds" survives a public feed, and whether `.ics` parsing wants hardening
beyond ADR-0093 §7's resource caps. **The two halves genuinely differ**: this ADR
assumes the reader parses hostile bytes correctly and asks what the correctly parsed
result may do; #641's remainder asks whether it parses them correctly at all, and
nothing here helps with a parser that crashes, hangs, or is coerced into
misclassifying a source's tier. #641's own firing condition — "before a reader is
pointed at a co-located fetcher's output" — is untouched by this ADR and still
fires.

**#659 is left where it is, and §8 takes a dependency on it rather than absorbing
it.** Its subject is a channel: `Engine.ingest`'s result reaches no adapter, so a
`SECRET`-tier ruling made on the ingestion path is made, honoured, and never
reported. That is not about attacker-authored content — it would be exactly as true
for a secret the user put in their own calendar — and folding it would mean this ADR
choosing between #659's two named shapes (a structured log line naming the ruling
and the reader's Tier 2 identity; or a rule that a reader may never propose Tier 0
at all) on no better evidence than #659 has. **The interlock is real and runs one
way**: §8's first clause is about *inspecting a stored belief*, which has a surface,
and it deliberately says nothing about reporting a refusal, which has none. A later
ADR that wanted to report a capped or refused external proposal would hit #659's
wall first, and should be told so.

**#663 is touched, narrowed by one input, and not discharged.** ADR-0072 §5's
revisit trigger — a real sensor — has fired, and this ADR is not the revisit: it
does not change the assembler's ordering, and band precedence is a question about
which beliefs fill a budget rather than about how they are presented, which is §2's
subject. It adds one input that #663 does not record and that neither ADR-0072 §5
nor ADR-0092 §10 could have: **`ATTESTED` is the band an outsider can write into,
and ordering it above `DERIVED` gives that outsider budget priority over the
system's own inferences.** ADR-0072 §5 argued the ordering on staleness — "a
connected source's record of the world is generally a better warrant than our
generalisation over behaviour, but it can be stale in ways we cannot detect" — and
adversariality was not in the frame. The revisit should weigh it. §2 makes the
ordering materially less dangerous, because the text now arrives labelled and
unforgeable, which is why this is an input to that decision rather than a reason to
pre-empt it.

### 11. This ADR classified under ADR-0070 §1 and ADR-0082 §1

ADR-0082 §1 requires the judgement in the later ADR's text, and it is made here.

**Every change this ADR makes is a stacked addition, and no record is owed against
any earlier ADR.** ADR-0082 §1's test is whether "a reader holding only the earlier
ADR" would now act differently or read one of its clauses more widely. Applied
clause by clause to the ADRs this one leans on hardest:

- **ADR-0072 §6** ruled that a derived belief reaching a prompt is rendered as a
  belief, and left the wording to the assembler. §2 adds a second thing to convey
  and a property the conveyance must have. Every sentence of §6 stays true and a
  reader of §6 alone still acts correctly, merely incompletely. **Addition.**
- **ADR-0077 §5** ruled the evidence floors. The Context observes that they
  authenticate the id rather than the support; §4 and §5 add obligations elsewhere.
  No sentence of §5 becomes false — it never claimed to bound a steered model — and
  a reader acting on it acts identically. **Addition, and a limit named rather than
  a clause amended.**
- **ADR-0042 §4** ruled that escaping is the adapter's, per target. §7 states the
  same division for a further class of surface content and §2 states it for the
  model. Nothing in §4 is read more widely against its own subject. **Addition.**
- **ADR-0073 §4** ruled what the inspection surface conveys per belief. §7 rules
  what the content may not do to the surface's framing, and §8 restates the band
  requirement as a security property without widening it. **Addition.**
- **ADR-0093 §4, ADR-0094 §5, ADR-0092 §4, ADR-0096 §6** are each *relied on* here
  as they stand — as the reason a rule holds by construction, or the shape a rule
  is copied from. None is narrowed or widened. **Addition.**
- **ADR-0017 §3 and ADR-0021 §6** are not amended, and this is the bullet an
  earlier draft got wrong. §3's fourteen conditions **do** exist as ratified text
  and one of them — "Recipient authorisation that traces to a user decision **or a
  standing user policy**" — is the clause a wider §3 would have narrowed, as would
  ADR-0021 §6's standing grants for actions. The first draft of §3 forbade an
  actuator driven by model output produced from external content absent a per-action
  user decision, which reads directly onto both; architecture review found it on
  round 1 and it was **narrowed rather than recorded as an amendment**, because the
  narrowing was owed on this ADR's own merits (§3, and §5's unobtainability
  argument) and not merely to avoid the record. As it now stands, §3 rules on the
  *span* — content selecting, parameterising or confirming — which neither of those
  clauses speaks to, and explicitly leaves the standing-authorisation question to
  the actuator lane. Every sentence of both stays true and a reader of either acts
  identically. **Addition.**

**Nothing here is a supersession**, wholly or partially: no decision moves, and
there is no sentence in the corpus a reader would now act differently on. So no
in-place edit to any earlier ADR is justified by this one, and this branch touches
no file but this one.

**This ADR is marked under ADR-0089** and is therefore in the marked regime: its
unmarked prose supplies no obligation and exists to determine what the marked
clauses mean (ADR-0089 §3). Marking is forward-only (§5), and nothing ratified
before it is drawn into the regime by it. **ADR-0089 itself stood `Proposed` at
`87d9214`**, which is what **#622** records — while ADR-0093, ADR-0094, ADR-0096
and ADR-0097 were each ratified carrying marks under it. This ADR follows that established practice rather than resolving the
inconsistency, which is #622's and not this lane's; whichever way #622 is resolved,
a marked ADR whose marks state its obligations is the reading both outcomes
support.

### 12. Deferred, by name, each with the condition that fires it

- **The seam that makes externality recoverable at the ruling point** — a marker on
  a record or a proposal, and whatever `MemoryPolicy` change reads it. §4's fourth
  clause is written against it and §5 argues why it cannot be specified now. **Fires
  with the first producer that can breach the clause**: a second reader whose output
  can be cited, an ADR that lets an ingested record be an `EpisodicMemory`
  (ADR-0093 §11's own deferral), or the first `orchestration` payload of mixed
  origin. The lane that takes it owes the caller-stamped/producer-declared argument
  named in §9.
- **Expressing the §2 distinction structurally rather than in-band** — content parts
  at the `ModelProvider` seam, or a trust-carrying field on `Message`. `Message.name`
  exists, is set by no producer in `src/`, and is discarded by
  `models.provider._to_model_messages`, so it is not the answer as it stands. **Fires
  when a provider seam can carry the structure, or when an in-band scheme is shown
  insufficient by a concrete bypass.** It is `core` surface and owes its own ADR.
- **The reader-side adversary model** — #641's remaining three questions, with that
  issue's own trigger.
- **A durable record of a memory ruling.** ADR-0021's trail is typed on
  `PermissionDecision` and §8 is written not to assume one. **Fires with the first
  surface obliged to show that a proposal was refused or capped**, which #659's
  channel question reaches first.
- **The projections that cannot carry an origin**, which §7's third clause makes
  their owners' debt rather than a surface's: `core.types.Question` (no
  `Attestation`, no `reported_by`), `core.types.Retirement` (no band, no source),
  and `core.types.Belief` / `BeliefSummary`, which drop the `Attestation` entirely —
  `grep -rn attestation` over `orchestration/` and `interfaces/cli.py` returns
  nothing, and `interfaces.cli` admits it in its own words on the attested branch:
  *"Which source, and when it said so, are not recorded."*
  All are `core` surface, and this is the **third instance of one lossy-projection
  shape** rather than three coincidences: **#568** already records that `Belief` and
  `BeliefSummary` cannot carry a belief's elided-citation count. Two distinct things
  are owed here and they have different weight: **origin at all** — enough for a
  surface to know a span is not the assistant's, which is §7's safety half and which
  `Retirement` lacks entirely — and **which source**, which is §8's legibility half,
  is **live and undischarged** under §8's second clause, and which `Question` and the
  belief surface both lack.
  **`Retirement`'s gap is live, not deferred, and an earlier draft of this bullet
  said the opposite.** That draft claimed neither was reachable without something
  beside it naming the origin; adversarial review falsified it on round 9 and the
  path is short. Arm the calendar reader, then assert something that conflicts with
  both an attested entry and an earlier assertion: `DefaultMemoryPolicy` rules
  `ASK_USER` on the prior assertion, `QuestionStage` resolves **every** frozen
  conflict into `Retirement(record_id, content)`, and `interfaces.cli` renders each
  as `_safe(retirement.content)` with the id — no band, no source, nothing. The
  question's own `band` describes the *proposal*, not the retirements, so there is
  no marker beside it either. Verified in `orchestration/questions.py` and
  `interfaces/cli.py`. **Filed as #673, and it fires now** rather than on a future
  revision. The **named-source** half — `Question`'s missing `reported_by` and the belief
  surface's dropped `Attestation` — is the weaker one and is deferred rather than
  blocking: §8's first clause is met by the band today, and the named half **fires
  with the second reader**, when "attested" stops identifying the source by
  elimination. **That trigger is this ADR's own and is independent of ADR-0093
  §11's two**, which an earlier draft of this bullet ran together with it. §11
  revisits the **source registry** "at the third source", and its **configurable
  display label** "acquires a subject at the second instance of one source type" —
  both later than, and conditioned differently from, a second *distinct* reader.
  A lane taking the projection work must not read this bullet as licence to
  introduce registry or label surface, neither of which ADR-0093 says is owed at
  two sources.
- **A presentation state for an inference that rests on external evidence.** Not a
  §7 case — §1 makes external content a property of a span's recorded origin, and a
  derived proposal's text is the assistant's own — but a real legibility question:
  a warrant that came from outside is not the same as one that came from the user's
  own behaviour, and ADR-0073 §4's "why it is held" is where it would be said. It
  needs the marker of the deferral above to exist before there is anything to
  present, so it **fires with that seam** and is plausibly one decision with it.
- **The actuator and egress design** — ADR-0017 §3's fourteen conditions, the
  approval and limit machinery of VISION §Principle 3, and **#241**'s open rule for
  choosing among several capable tools, which #668 names as inheriting this posture
  and which §3's actuator clause reaches directly: a ranking driven by an external
  span is that span selecting the actuator. **Fires with the first actuator.** §3 fixes
  what may never be an action's authority and nothing else about it.
- **Whether a standing authorisation covers a content-triggered action** — §3's
  last clause states the question and refuses to answer it, because answering it
  would narrow ADR-0017 §3's standing-user-policy condition or ADR-0021 §6's
  standing grants from an ADR with no actuator in hand. **Fires with the same lane**,
  which must answer it explicitly. §5's unobtainability argument is an input: an
  answer phrased over "output produced from external content" is not checkable, so
  whatever is decided has to be decidable from recorded origin.
- **Spoke-borne external content.** A bystander's speech is external content by §1
  and inherits §2, §3 and §4; the submission path, the per-spoke band ceiling and
  the custody handoff are ADR-0094 §5, §8 and §10's, deferred there on their own
  triggers. This ADR supplies the class, not the mechanism.
- **Tool and MCP results.** External content by §1, inheriting §2 and §3. **Fires
  with the first tool that returns text**, which the roadmap places behind MCP.
- **Whether a detector is ever added at all.** §6 rules only that one may not be a
  gate and may not buy a bound. Adding one is a later decision with its own cost
  argument, and nothing here recommends it.

## Consequences

**What becomes easier.** The three lanes that would otherwise each have invented a
posture — prompt assembly, the second reader, the first actuator — inherit one, and
the hardest question in each of them (what a label must guarantee, what a ceiling
rests on, what may authorise an action) is answered before they start. The
assembler's obligation is testable in the way the corpus prefers: feed a record
whose content is the assembler's own syntax, assert the attribution survives. And
the corpus gains a stated adversary, which it did not have — #641 filed that gap for
the reader seam and this closes the downstream half of it for the whole pipeline.

**What becomes harder.** Two prompt assemblers on `main` do not satisfy §2 and will
have to change, and the change is not cosmetic: an escaping or containment scheme
touches every rendered record and every fixture that asserts on prompt text.
`planner._render_record`'s `[kind/source]` bullet and `observer._render_batch`'s
`[E<n>]` label are both forgeable today, and the second one interacts with an
evidence floor, so that lane is doing security work rather than formatting work and
should be scoped as such. §7 adds an obligation to every client surface, present and
future. And §3's actuator clause will be inconvenient for the first actuator lane
exactly when a content-derived parameter looks obviously safe.

**The accepted cost, named once more because it is the thing most likely to be
misremembered.** This posture does not detect injection and does not claim to. On
the live chain of the Context — attested belief, planner prompt, model rationale,
episode, observer, durable belief — the externality is destroyed at step 3 by a
ratified decision that is right for its own reasons, and nothing here recovers it.
What is bounded is what the resulting belief can *be*: derived, never asserted;
below certainty; retirable by a word from the user; visible on a surface that says
what it is. A reader who takes away "we mark untrusted content, so we are safe" has
taken away the opposite of §5.

**What would trigger revisiting.** Any of §12's firing conditions. Also: a concrete
bypass of whatever in-band marking the prompt-assembly lane chooses, which would
promote §12's second bullet from deferred to owed; and the first evidence that a
model reliably ignores the marking, which would mean the posture's foundation is
weaker than §2 assumes and would make §4's ceilings the only defence rather than the
outer one.

## Alternatives considered

**Rule an injection classifier at the reader seam.** Rejected in §6, and worth
recording why it is tempting: it is the only proposal that looks like it *stops*
the attack rather than bounding it. It is bypassable by construction, it would
become load-bearing the moment a later ADR relaxed a ceiling on the strength of it,
and its failures are silent. VISION §Principle 3's opening line rules it out in the
project's own words.

**Refuse to render external content into prompts at all.** A reader whose output
never reaches a model is a reader with no purpose: VISION §Principle 1 names
"read-only sources it may ingest" as a source of observation, and ADR-0096 §6 keeps
the facet small on the premise that the *beliefs* carry the entries. The system that
survives this rule is one that reads calendars and cannot mention them.

**Put the fourth clause of §4 in `MemoryIngestor` instead of deferring its seam.**
The writer already resolves cited records, so it could see externality one hop out.
Rejected in §5: the writer runs before the policy and may not substitute a ruling
(ADR-0081 §3, ADR-0005 §3), so the only shapes available are refusing by raising —
which loses the belief instead of asking about it, and turns "a suspect proposal"
into an exception the caller must handle — or widening `MemoryPolicy.decide`, which
is `core` surface this ADR has no producer to justify.

**Carry the taint as a boolean the producer sets.** The cheapest possible mechanism
and it is refused for ADR-0094 §5's reason: it puts a producer in charge of its own
standing, and the failure mode is a producer that simply omits it, which no
validator can distinguish from an honest `False`. If the seam is built, the argument
against this shape is owed in that lane's text (§9).

**Define external content by subsystem — "anything from `readers/`".** Refused in
§1. Three producers of external content already exist or are anticipated outside
`readers/` (a provider exception, a spoke's submission, an MCP result), so the rule
would be rewritten three times, and each rewrite is a window in which the class is
wrong.

**Promise the finer attribution in §8 — "an email someone sent you".** Refused
because ADR-0093 §7's declared-never-configured identity makes it unavailable
without carrying a sender on the record, and a promise of author-level attribution
that renders a source-level string is a promise that misleads exactly the user who
relies on it.
