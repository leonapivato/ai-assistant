# 213. A record carries the topics it is about, proposed once at write and never inferred at read

- Status: Proposed
- Date: 2026-08-29

## Context

### Where this comes from

Issue #1720, on the owner's direction of 2026-08-28 during the guarded-class
discussion of batch #1709: *"the topic thing needs to exist for forgetting
anyway."* The note is `track:memory`'s, and it names three consumers that each
key on an axis no record carries. This ADR decides the axis. It implements none
of the three.

### The gap: three acts the corpus can state and the store cannot answer

- **"Forget everything about my health."** A routed `forget` resolves its
  argument by a lookup that ADR-0197 §5 makes exact: "The lookup's candidates are
  **typed records**, and the operation's argument is a **scalar identity read off
  one of them** by a fixed per-operation mapping … `forget` takes `Belief.id`",
  and "Where it resolves to **more than one**, the route ends in
  `RouteOutcome.AMBIGUOUS`, nothing is performed, nothing is confirmed, and the
  outcome carries the candidates." An utterance naming a whole topic is by
  construction the ambiguous case, so it has no operation today. The subject-scoped
  erasure ADR-0101 §1 ratifies does not reach it either: it "erases by subject" —
  a person — and ADR-0100 §6 rules the subject axis "*whom*, not *what*. A belief
  about a company, a project, a device or a topic states no subject."
- **"Keep everything about my health to me."** The guarded-placement design note
  (#1719) ships **per-record** acts and names this axis as the widening that would
  make a class-level act expressible. It ships without this ADR; the class-level
  half does not.
- **"My coffee habits may be said aloud."** ADR-0199 §6 admits a recorded owner
  act that makes a withheld class speakable. Whether such a record generalises from
  coffee to breakfast is a question about what it is *keyed on*, and there is
  nothing on the record to key it on.

Three different lanes, one missing field. That is what makes this a decision worth
recording rather than a paragraph in whichever of the three arrives first — and
recording it once is what stops three lanes minting three incompatible answers.

### What the corpus already decides, and this ADR may not rebuild it

- **A class is read off a recorded value, never off the words.** ADR-0199 §2:
  "The **class** of a piece of content is decided from what the system recorded
  about where the content came from, and never by inspecting the content for what
  it appears to be about", and "No implementation, lane or later ADR may decide a
  class by reading `MemoryBase.content`, a facet's rendered text, a composed reply,
  or any other span of the content itself — not by keyword, not by pattern, not by
  a classifier, and not by asking a model what a passage is about." A topic axis
  that a consumer computed at read time would be exactly the forbidden thing. The
  shape that is *not* forbidden is the one every consumer of this axis needs: the
  model runs once, at write, and what a later read touches is a recorded field.
- **A model may not be in the read path, and the three grounds are stated.**
  ADR-0130 §11 rules that "A model may not rule on a notification candidate", and
  gives its reason in one sentence that generalises: "An interruption a model chose
  cannot be explained to the user who received it, cannot be tested
  deterministically, and cannot run when no provider is reachable — which is
  exactly when a resident process is still noticing." Those three grounds are the
  test this decision has to pass, and §4 below answers each by name.
- **Where a field goes is already settled by a normative test.** ADR-0100 §2:
  "`Provenance` carries what answers *why this should be believed* — the warrant,
  its source, and how far it is trusted. `MemoryBase` carries what answers *what is
  held, about what, and for how long*. A field is placed by which question it
  answers, not by who sets it."
- **The record graph is frozen.** ADR-0068 §1 makes every boundary-crossing model
  in `core/types.py` deeply immutable and rules that "Mutable collection fields
  become immutable collections. Every `list[X]` field on a frozen model becomes
  `tuple[X, ...]`, matching the house form".
- **Retrieval is band-neutral and stays that way.** ADR-0072 §5: "`MemoryStore.search`
  stays **band-neutral and confidence-neutral**: it ranks by relevance and returns
  whatever is live, whatever its standing." ADR-0113 §4 draws the line this axis
  must respect from the other side: "The band decides **which records are ranked**
  … and contributes nothing to **how ranked records compare**."
- **A cardinality bound on a `core` type is judged by one test, and the corpus has
  already worked the case where a fold overflows one.** ADR-0086 §2: "**The test is
  not 'is it a validator on a `core` type'; it is 'does it refuse something that
  already worked'.**" It puts `MAX_EVIDENCE_CITATIONS` at the `MemoryWriter` seam on
  *installs* rather than on the type, and ADR-0086 §3 decides what a `REINFORCE`
  whose union exceeds it does — "The surviving record retains the most recently
  accumulated `MAX_EVIDENCE_CITATIONS` citations of the union" — with ADR-0086 §4
  recording the loss as a count on the record. §1 below says why that answer does not
  transfer to this field.
- **A reader gets nothing from what it reads.** ADR-0183 §3: "A reader derives
  **no standing** from anything its source's bytes contain. No field, header,
  display name, address, claimed identifier, framing marker, or position of a unit
  within the file may set or raise the band, the confidence, the sensitivity, the
  record identity, the reporting identity, the retrieval precedence, or the grant
  that a proposal drawn from it carries."

### The tree, read rather than assumed — which producers can call a model at all

#1720 says the proposer is "the write-time model call (ingest/observation already
need a provider)". Half of that does not hold, and the half that does not is the
half that decides the design.

`ModelProvider` reaches exactly four production components:
`ModelBackedObserver` (`learning/observer.py`), `ConsolidationStage`
(`orchestration/consolidation.py`), the composing stage
(`orchestration/composing.py`) and the routing stage
(`orchestration/routing.py`). The reader-ingestion path holds none:
`IngestionStage.__init__` takes `reader`, `writes`, `grants`, `reads` and `now`,
and nothing else. Neither does capture (`orchestration/conversations.py`), and
neither does `RuleBasedFeedbackProcessor` (`learning/processor.py`), which is
rule-based by name and by ADR-0005 §3.

So there is no single "write-time model call" to hang this on. There are two
producers that already hold a provider and already send a distilling envelope, and
three that hold none and must not be given one: a provider on the capture path
would put a model call on every turn's hot path, and a provider on the ingestion
path would make a scheduled source read fail or degrade on a provider outage. §6
states each producer's answer by name, and the answer for three of the five is
*no topics*.

### An honest statement of what this ADR is not allowed to settle

It cannot decide any of the three consumers, because each of them changes a
surface of its own: a topic-scoped `forget` widens `RoutableOperation` and needs a
filtered store read, a topic-scoped guard is #1719's and waits on an ADR of its own,
and the reach of a disclosure preference is ADR-0199 §6's surface, which that ADR
itself defers.
It cannot decide a matching rule wider than equality, for ADR-0100 §6's reason
applied here. It cannot decide the surface on which the owner performs the acts §9
rules on, which is a promoted-surface change and therefore its own ADR under golden
rule 5 and ADR-0015 §5. And it cannot put anything derived from a belief into an
observation prompt: ADR-0077 §3 rules that payload, changing it is a record on
ADR-0077 under ADR-0070 §1, and this lane's fence reaches one ADR file. §5 states
what that costs and §15 names the instrument that may take it.

What it can decide is everything a consumer needs to *exist*: what the field is,
what a value in it means, what an empty one means, who may write one, what
happens to it under a fold, and what may never be done with it.

## Decision

### 1. One additive field on `MemoryBase`, and the three names beside it

> **Normative.** `core/types.py` gains `TopicLabel`, an annotated refinement of
> `EncodableText` admitting exactly the canonical form §3 fixes, and the two
> constants `MAX_TOPIC_LABEL_LENGTH` and `MAX_TOPICS_PER_PROPOSAL`.

> **Normative.** `MemoryBase` gains exactly one field, `topics`, of type
> `tuple[TopicLabel, ...]`, defaulting to the empty tuple. It records what the
> record is *about*, as a set of labels the owner can read. No other `core` type
> gains a member for this decision, and no existing member of any `core` type
> changes its type, its default or its meaning.

```python
topics: tuple[TopicLabel, ...] = Field(
    default=(),
    description=(
        "What this record is about, as canonical labels proposed at write "
        "(ADR-0213 §4). Empty means no topic was recorded, which is neither "
        "'no topic' nor 'every topic' (§7). Strictly increasing (§3)."
    ),
)
```

> **Normative.** The tuple is **strictly increasing** by code point: a value that
> is unsorted, or that repeats a label, is refused at construction. Order carries
> no meaning here, so fixing one is what makes two equal sets one value —
> serialise-and-reconstruct parity, digest stability and a store comparison all
> follow from it, and none of them survives a field where `("health", "sleep")`
> and `("sleep", "health")` are different bytes.

> **Normative.** The field carries **no cardinality bound on the type**.
> `MAX_TOPICS_PER_PROPOSAL` bounds what a *producer* may propose (§4) and binds
> nowhere else; no validator on `MemoryBase`, no `MemoryWriter` check and no store
> refuses a record for carrying more labels than it.

**ADR-0086 §2's test does not decide this, and its own answer does not transfer.**
The test — "does it refuse something that already worked" — is answered *no* for a
brand-new field: nothing in any store carries topics, so a `max_length` here would
refuse nothing that exists today. So the type-level bound is available, and it is
declined on other grounds. ADR-0086's own answer to the case that matters —
`MAX_EVIDENCE_CITATIONS` at the `MemoryWriter` seam on installs (§2), with a fold's
overflow displacing the oldest of the union (§3) and the loss recorded as
`Provenance.evidence_elided` (§4) — is the obvious thing to copy, and three
differences stop it.

- **There is no age to displace by.** ADR-0086 §3 selects "the most recently
  accumulated" because that section could ratify the tuple's order as accumulation
  order: "§3's rule reads position as age and a rule that reads a property nobody
  guaranteed is not a rule." §1's order here is by code point, chosen *because* order
  carries no meaning, so there is no principled member to drop — displacement would
  discard `"sleep"` before `"work"` on an alphabetical accident.
- **The loss is a different kind of loss.** An elided citation weakens how a warrant
  is *presented*, and ADR-0086 §4 can say so honestly — the belief stays exactly as
  reachable as it was. A dropped label makes the record unreachable by a topic-scoped
  act, which changes what a later destructive or protective act touches, with nothing
  a count can restore. That is nearer ADR-0106 §4's laundering than ADR-0086 §4's
  elision, and §8 rules the union non-lossy for that reason.
- **The cost the bound exists to stop is absent.** ADR-0086 bounds `evidence` because
  citations are resolved — a Context section of it is headed "The read amplification
  is contract-mandated, not an implementation choice", and §6 lands `get_many` to
  serve it. A label resolves to nothing (§3) and costs one short string; there is no
  amplification here to bound.

So the bound sits on the proposer, where it shapes what is written without being able
to refuse a fold the policy has already ruled, and the growth §8's union leaves is
stated as residue in §15 rather than closed by a mechanism that would cost more than
it buys. `Provenance.evidence` is the corpus's own precedent for a `core` collection
whose type carries no length bound.

### 2. Placement: the envelope, on ADR-0100 §2's own test

> **Normative.** `topics` is a field of `MemoryBase` and not of `Provenance`.

ADR-0100 §2 states the test so that it "decides the next field rather than being
re-derived", and this is the next field: "`Provenance` carries what answers *why
this should be believed* — the warrant, its source, and how far it is trusted.
`MemoryBase` carries what answers *what is held, about what, and for how long*. A
field is placed by which question it answers, not by who sets it."

**A topic is the "about what" of that sentence, not a fact about the warrant.**
Two beliefs with identical warrant are about different things; two beliefs about
one thing can have entirely different warrants. That is the same orthogonality
ADR-0100 §2 found for the subject axis, and the field lands beside `about_person`
for the same reason: the two together are the *about* half of the envelope's
question, one asking *whom* and the other *what*. ADR-0100 §6's closing clause
already reserved the second half by name — "The axis is *whom*, not *what*. A
belief about a company, a project, a device or a topic states no subject" — so this
field occupies ground the corpus explicitly left empty rather than ground another
field holds.

**The contrast with the nearest recent field is what makes the test bite.**
ADR-0204 §1 put `supplied_withheld_content` on `Provenance` under the same test and
got the opposite answer, because "What material stood in front of the producer is
where a record came from, which is this class's question". A topic is not a
property of the material the producer saw; it is a property of what the record
says. Applying one test to two fields and getting two answers is the test working.

**And ADR-0100 §2's second, operational reason transfers word for word.** It
placed the subject on the envelope because "The first consumer this axis has … is
precisely a read-and-delete predicate. On `Provenance` it would be the only such
predicate reaching through a nested object into a JSON column; on the envelope it
is a column beside the two that already filter reads." Every consumer named in the
Context is a read-and-delete or a read-and-withhold predicate. §11 leaves the
column itself to the lane that first needs the filter.

### 3. The label's form is fixed, refused rather than normalised, and equality is the only relation it has

> **Normative.** A `TopicLabel` is admissible exactly when it is an
> `EncodableText` that is non-empty, is at most `MAX_TOPIC_LABEL_LENGTH`
> characters, equals its own `str.casefold()`, contains no whitespace character
> other than `U+0020 SPACE`, has no leading or trailing space, and contains no run
> of two consecutive spaces. A value failing any of those is **refused at
> construction**.

> **Normative.** Nothing normalises a label. No producer, store, surface, seam or
> later lane case-folds, strips, stems, singularises, transliterates, aliases or
> de-duplicates a label on the way in or on the way out. A value that is not
> already canonical is a producer error and is refused; it is never quietly
> repaired.

> **Normative.** The only relation this ADR gives two labels is **equality of the
> stored characters**. Nothing treats two unequal labels as one topic, nothing
> treats one label as narrower or broader than another, and no hierarchy, synonym
> set, stem, embedding or model judgement is a topic relation under this ADR.

> **Normative.** Any wider matching rule — case-insensitivity beyond the canonical
> form, prefixes, hierarchy, synonymy, or a similarity measure — is reserved to a
> later ADR, which is the only instrument that may lift the clause above. No lane
> reaches that answer by implementing one.

**The canonical form is the whole of what buys convergence at the type level, and
it is deliberately thin.** It makes `"Health"` and `"health"` the same value and
`"health"` and `"wellbeing"` different ones, which is exactly the split this ADR
can defend: the first is a spelling, the second is a judgement, and a type that
tried to decide the second would be the classifier ADR-0199 §2 forbids, moved to
construction time. What closes the second gap is §5's supplied vocabulary, on the one
producer it reaches, and §9's merge act — neither of which is a rule about strings.

**Refused rather than folded, on ADR-0100 §6's own reasoning.** That section keeps
a person label verbatim because "a value that is *nearly* right is harder to spot
than one that is missing. A normalised name is nearly right." The instinct is the
same here and the conclusion is one step stronger: a label that arrives
non-canonical means a producer did not fold its model's output, and folding it
under them hides that in the one place nobody looks. Refusing puts the failure at
the producer, which is where §4 puts the obligation. It is also the shape ADR-0100
§1 already chose for the blank — "a record stating `""` as its subject is a
producer that meant to speak and said nothing, and it must not be representable".

**A validator that refuses on decode is available here and is not available
everywhere, and the difference is ADR-0086 §2's test.** No record in any store
carries a topic, so no validator on this field can refuse a record that already
worked. That will stop being true the moment records carry topics, so **widening
the canonical form later is a change that must answer the same test on the data of
that day** — a wider form admits values an older peer refuses, which is the
direction that breaks. Narrowing it is worse. Stating that here is what stops a
later lane treating the form as a free parameter.

**Equality alone, because that is all the two things this ADR needs.** §5's
vocabulary is a grouping of stored labels by exact value; §9's merge act rewrites
one label to another under the owner's own instruction. Neither is a matching rule,
and neither presumes one. This is ADR-0100 §6's split taken whole: the first clause
"fixes what holds *while nothing else is ratified*: comparison behaves as though
the label resolved to nothing, which is the fail-safe reading and the only one
available before a matching rule exists", and the second "says which instrument may
change that — a later ADR, ratified, and never a lane deciding it in code".

### 4. A topic is proposed by the record's own producer, at write, in the envelope it already sends

> **Normative.** Topics are set by the producer of the record, at the moment the
> record is written, and by nothing else. No consumer, surface, store, retrieval
> path, scheduler job, migration or later ADR derives a record's topics at read
> time, and none derives them from `MemoryBase.content`, from a rendered facet, from
> a composed reply or from any other span of content, at any time after the write.

> **Normative.** A producer that proposes topics does so **inside the model
> envelope it already sends**. This ADR authorises no second model call, no second
> round trip and no second provider dependency anywhere in the system: a producer
> holding no `ModelProvider` proposes no topics and is given none (§6).

> **Normative.** A producer proposes at most `MAX_TOPICS_PER_PROPOSAL` labels per
> record. A response naming more, naming a value the canonical form of §3 refuses, or
> naming none, yields **no topics on that record**: the topics entry is **ignored**,
> never repaired, never re-prompted for and never inferred locally. The record itself
> is unaffected — a bad topics entry never discards the proposal that carried it.

> **Normative.** An ignored topics entry is **not a discarded entry**. No counter of
> `ObservationOutcome` moves for it, and no `core` type gains a member to count it:
> `discarded_unusable` and `discarded_over_limit` keep exactly the meanings ADR-0077
> §4 gives them, and `ObservationOutcome`'s invariant —
> "`len(proposals) + discarded_unusable + discarded_over_limit` equals the number of
> entries the model emitted" — is untouched, because an entry whose topics were
> ignored still yields exactly one proposal.

> **Normative.** `MAX_TOPIC_LABEL_LENGTH` is **64** and `MAX_TOPICS_PER_PROPOSAL` is
> **4**. Both are fixed constants of `core/types.py`: neither is a `Settings` field,
> a constructor knob or a per-deployment value, and an implementation that admits a
> longer label or a fifth proposed topic does not conform.

**ADR-0130 §11's three grounds, answered one by one, because they are the test.**
That section's ruling is about a model in the *decision* path and its reason is
stated generally: such a decision "cannot be explained to the user who received it,
cannot be tested deterministically, and cannot run when no provider is reachable".

- **Explainable.** What a later act reads is a label recorded on the record, beside
  a `Provenance.source` naming the producer that put it there. "Why did forgetting
  my health reach this belief?" is answered by showing the belief and the word
  written on it, which is a field read.
- **Deterministic.** Nothing about a read varies with a model, a prompt or a
  provider's mood. Two reads of one store give one answer, and a test fixes an
  outcome by writing a label rather than by pinning a model.
- **Reachable with no provider.** A provider outage produces *no topics*, never a
  wrong one — and in the two producers §6 admits it produces no record either,
  because a `ModelError` ends the pass rather than degrading it (ADR-0077 §3). The
  three producers that hold no provider go on writing exactly what they wrote
  before, unlabelled.

This is the same shape ADR-0028 ratified for the write path and ADR-0130 §4 for a
notification's disposition — "`NotificationPolicy` is deterministic … It performs no
model call, and its ruling is a function of its inputs and of nothing else" — a model
*proposes*, and everything downstream reads a recorded value.
ADR-0199 §2 is left whole rather than bent — its prohibition is on deciding a class
"by inspecting the content", and after this decision no consumer inspects anything.
The one model reading of the words happens once, at write, by the producer that was
already reading them to produce the record at all.

**Ignored rather than repaired takes half of ADR-0077 §4's rule and deliberately
leaves the other half.** `ModelBackedObserver` already holds that rule for an entry
it cannot use — "Entries that cannot be used are discarded and *counted* rather than
repaired, invented, or re-prompted for: an observation has nothing waiting on it, so
the cheap remedy is a later run rather than a second call inside this one" — and the
*not repaired, not re-prompted* half transfers whole. The *counted* half does not,
and must not: `ObservationOutcome`'s two counts are "exhaustive and disjoint over
what the model emitted", so counting a usable entry whose topics were bad would break
the invariant in the one direction it is checked, reporting one proposal and one
discard for one entry. A topics entry is strictly less load-bearing than the proposal
carrying it: a rule that discarded the proposal over a bad label would trade a belief
for a filing word, and a rule that counted it as discarded would misreport the
model's output.

**Why the values are 64 and 4.** A label is a filing word the owner reads in a
listing, not a sentence: 64 characters is generous for the longest ordinary
compound and short enough that a producer writing prose into the field is refused
rather than accommodated, and it is the same figure `MAX_EVIDENCE_CITATIONS` takes
for the adjacent kind of bound. Four is the number at which a topic set stays
readable at a glance and a topic-scoped act stays meaningful; a record that is
genuinely about five things is a record that is about one thing the vocabulary has
not learned to name. Both are stated rather than left to the lane because a bound
whose value each implementation picks is not a bound — the failure ADR-0086 §1
names when it makes its own constant fixed.

**The budget is what makes the second clause affordable to state.** The added cost
of this decision at run time is: at most `MAX_TOPICS_PER_PROPOSAL` short labels per
proposal in the response, everywhere; and in the consolidation prompt alone, the
supplied vocabulary (§5, at most `DEFAULT_PAGE_SIZE` labels of at most 64
characters). No call count changes anywhere, and the observation prompt does not
grow at all.

**A fixed constant rather than a knob**, because the axis's whole value is that a
record's topic set is small enough for the owner to read and small enough that a
topic-scoped act means something. A deployment that raised it to fifty would degrade
every consumer of the axis, and neither the owner nor a later lane could see from the
data that it had. `MAX_EVIDENCE_CITATIONS` is a fixed constant for the adjacent
reason (ADR-0086 §1), and the observer's own `max_batch_size` and `max_proposals` are
knobs for the opposite one — they bound a *run*, not the shape of what is stored.

### 5. The vocabulary a proposer is supplied comes from the records it is already reading

> **Normative.** `ConsolidationStage` (`orchestration/consolidation.py`) accumulates,
> **in memory and for the duration of one run**, the distinct topic labels carried by
> the records that run has already read, and puts them in the prompt it already sends.
> It proposes against them: it uses an existing label where one fits and mints a new
> one only where none does.

> **Normative.** The supplied set is the labels the run has read so far, bounded to at
> most `DEFAULT_PAGE_SIZE` of them and selected by the number of read records carrying
> each, descending, ties broken by label ascending. The count is over what this run
> read and nothing else. The first chunk of a run is supplied nothing, because nothing
> has been read yet.

> **Normative.** The accumulation is **per run and never durable**. Nothing is
> written, no cursor, count, index, column or table records it, it does not survive the
> run that built it, and no later run inherits it. A run's vocabulary is a property of
> the walk it just performed.

> **Normative.** **No Protocol changes.** This ADR adds no member to `MemoryStore`, no
> argument to any of its reads, and no member or argument to `Observer`,
> `MemoryWriter`, `MemoryPolicy`, `ConversationStore`, `ContextProvider`, `Planner`,
> `Reader` or any other Protocol. Nothing in `core/protocols.py` changes.

> **Normative.** The supply is a **hint** and never an authority. The producer is not
> obliged to use a supplied label, a supplied vocabulary neither widens nor narrows
> what it may propose about, and no record is refused, altered or ranked for carrying a
> label the vocabulary did not offer.

> **Normative.** **No vocabulary is supplied to the `Observer`.** No belief, label
> derived from a belief, profile, facet or plan enters an observation prompt on this
> ADR's authority. `ModelBackedObserver` proposes topics from the batch it was handed
> and from nothing else.

**The observer is excluded because ADR-0077 §3 rules its payload, and this ADR is not
the instrument that changes it.** That section is titled "Which model reads the
episodes: a named route, no fallback, minimal payload", and its third part is explicit:
"**The payload is the batch and nothing else.** The prompt carries the episodes'
canonical `content` … and what the model needs to cite them. It does **not** carry the
user's existing beliefs, the profile, the context facet, or a plan. Sending beliefs
would be the obvious way to stop the observer re-proposing what is already known — and
it is refused, because de-duplication is the gate's job and the gate is deterministic
and local … Paying for that with a second class of Tier 1 data in the prompt would be
minimisation (ADR-0004 §7) traded away for something already solved."

A vocabulary derived from the user's beliefs is exactly that second class of Tier 1
data, arriving for exactly the reason ADR-0077 §3 refuses it — to stop the producer
re-minting what the store already has. The argument transfers without weakening.
**Supplying it anyway would be a change to ADR-0077 §3 requiring a record under
ADR-0070 §1 and ADR-0082 §1, and this ADR makes none** (§16): a reader holding only
ADR-0077 sends the same payload after this decision as before.

**Consolidation is a different payload, and the labels it is supplied are drawn from
the very records already in front of it.** `ConsolidationStage` prompts with a whole
chunk of stored records — its own composition notes that "a consolidation prompt
carries a whole chunk of stored records" — so labels of records this run has read are
the class of data that prompt already carries, from the same records, for the same
recipient. ADR-0004 §7's minimisation test is met on its own terms rather than waived:
no new class of data, no new recipient, and at most `DEFAULT_PAGE_SIZE` short strings
against a chunk of full records.

**Reading the walk rather than the store is what makes this free, and three rounds of
review are why it is stated that way.** An earlier draft added a `MemoryStore` read
returning the store's whole vocabulary, and it could not be made to hold: an
exact global ordering costs a walk of every record, moving that walk before the first
chunk relocates the cost without bounding it (ADR-0111 §4), and requiring it to be
served from write-maintained storage collides head-on with liveness — a record leaves
the live set when a clock passes its `expires_at` or its `validity` window, with no
write to maintain anything, so a maintained count and `MemoryStore.get` would disagree
about what the store holds. The Alternatives record that path and why it was abandoned.
Reading what the walk already decoded has none of those problems: the records are in
hand, they were returned by a read that already applied the store's own liveness
predicate, and the cost is a dictionary update per record.

**What it buys, and what it does not.** Within a run, every chunk after the first is
supplied the labels the earlier chunks carried, so a run converges on itself rather
than minting a synonym per chunk. Across runs, ADR-0111's cursor walks the whole store,
so a later run reads records earlier runs labelled and is steered by them. What it does
**not** buy is a store-wide vocabulary at the first prompt of a run, and it buys the
observer nothing at all — so an unmerged store will carry `"health"` and `"wellbeing"`
side by side until consolidation or the owner brings them together. Both residues are
named in §15 with the instrument that would close each.

**A hint and not an authority, stated because the opposite reading is available.** A
producer obliged to choose from the supplied set would file a genuinely new subject
under the nearest old label, and the first hundred records would fix the vocabulary of
the store forever. The merge act of §9 is the instrument for collapsing a vocabulary
that fragmented; nothing is the instrument for recovering a distinction that was never
recorded.

### 6. Every producer's answer, stated by name

> **Normative.** Exactly two producers propose topics: `ModelBackedObserver`
> (`learning/observer.py`), on each `MemoryUpdateProposal` it returns, and
> `ConsolidationStage` (`orchestration/consolidation.py`), on each record it
> distils. Every other producer writes the empty tuple.

> **Normative.** Capture (`orchestration/conversations.py`) writes no topics on the
> `EpisodicMemory` it records per turn. No topic is proposed on any episode under
> this ADR, by any producer.

> **Normative.** `RuleBasedFeedbackProcessor` (`learning/processor.py`) writes no
> topics, and is given no `ModelProvider` by this ADR.

> **Normative.** A `Reader` states no topics, and no proposal reaching
> `IngestionStage` carries any. A source's own categories, folder, labels, tags or
> headers are **not** a route by which a topic reaches a record, and no reader, lane
> or later ADR may make one without an ADR that reckons with ADR-0183 §3.

> **Normative.** No producer infers a topic for a record it did not itself produce,
> and no producer proposes topics on a record another producer wrote.

**Capture writes none because capture judges nothing.** ADR-0074 §4 rules it in
those words: "**Capture judges nothing else.** `importance` stays at its default:
importance is a judgement, and salience is leg 7's decision, not a number the
recorder invents." A topic is the same kind of judgement, and capture is on the
turn's own path with no provider and no budget for one. Two consequences follow and
both are named rather than left to be discovered: a topic-scoped act does not reach
the transcript of the conversation the belief came from (§15's residue), and
ADR-0201 §1's exclusion of `EPISODIC` from a routed `forget`'s lookup is therefore
already aligned with this decision rather than in tension with it.

**A reader states none for ADR-0100 §4's reason and ADR-0183 §3's.** ADR-0100 §4
worked the same case: "`CalendarReader` states none, because `Occurrence` parses no
attendee or organiser and the reader may not infer one from `summary`." Neither
reader parses anything topic-shaped today, and admitting a source's own labels would
be worse than merely unimplemented — a topic drives a *destructive* act in one of
the three deferred consumers, so an adversary who can place bytes in a source
(ADR-0183 §1: "anyone who can cause bytes to appear in a source a reader reads")
would be choosing which of the owner's records a later "forget everything about X"
destroys. ADR-0183 §3's list of what a source may not set does not name topics
because topics did not exist; the clause above adds this axis to it rather than
reading the omission as permission.

**The feedback processor writes none, and that is a real gap rather than an
oversight.** A belief the owner asserts through `learn` is unlabelled, so an
utterance the owner most clearly meant — "remember that I am allergic to
penicillin" — produces the record a topic-scoped act would most want to reach and
cannot. Making it labelled needs either a provider on a rule-based component, which
ADR-0005 §3's split forbids in spirit and this ADR declines, or an owner-stated
topic at the moment of the act, which needs a carrier on the promoted surface and
is therefore §9's deferred surface. §15 names it with its condition; it is not
closed here and it is not pretended away.

**Nobody labels another producer's record.** Without that clause, "the observer
could label the episodes it reads" is one paragraph away, and it is the read-time
classifier ADR-0199 §2 forbids wearing a write-time costume: the observer would be
deciding what an episode is about by reading its words, after the episode was
written, and stamping the answer on a record it did not produce.

### 7. An empty tuple is "no topic recorded", and it is neither "no topic" nor "every topic"

> **Normative.** An empty `topics` states that **no topic was recorded** for that
> record. It does not state that the record is about nothing, and it does not state
> that the record is about everything.

> **Normative.** No consumer, surface, store or later ADR reads an empty `topics`
> as matching a topic-scoped query, and none reads it as excluded from a query that
> names no topic. A topic-scoped act reaches a record if and only if the record
> carries the label the act names.

> **Normative.** A surface performing a topic-scoped act says what the act did not
> reach: that records carrying no topic were not reached, and that the reach of the
> act is the labels that were recorded rather than the subject the owner has in
> mind.

**The two wrong readings are both available and both are damaging in opposite
directions.** Read as "every topic", an unlabelled record is destroyed by the first
"forget everything about X" the owner utters, whatever X is — the store emptied by a
default. Read as "no topic", an unlabelled record is silently outside every act the
owner performs, and the owner is told their health facts are guarded while the
majority of them are not. Stating the third reading, and obliging the surface to
disclose it, is the only honest position while §6 leaves three producers writing
none.

**This is ADR-0101 §6's honest limit, transposed.** That section obliges the
subject-scoped erasure's surface to say what it did not reach, and ADR-0100 §12
records the same limit for the same axis — "it inherits §8's honest limit: a
subject-scoped delete cannot reach a record whose subject was never stated". The
same sentence with "topic" in it is true of this axis and will stay true of it for
as long as any producer writes unlabelled records, which §6 makes permanent for
three of the five.

**It is deliberately a two-state field and not a three-state one.** ADR-0204 §1
considered and rejected a `None`-for-unrecorded third state for a boolean, and the
reason transfers: "A `None` meaning 'unrecorded' that a supply site had to withhold
on would withhold every belief in the store from the spoken channel until every
producer in the system was taught to write `False`". An empty tuple is already the
unrecorded state and needs no second spelling; what it needs is the clause above
saying how it is read.

### 8. Topics are set once, and revised by exactly two routes

> **Normative.** A record's topics are set by its producer at write and are revised
> only by the two routes below. No re-observation, no consolidation of an already
> stored record, no retrieval, no re-embedding, no reconciliation, no scheduler job,
> no migration and no backfill revises the topics of a record already in the store.

> **Normative.** **The fold's union.** Where two records are folded — a `REINFORCE`
> on either arm — the survivor's topics are the **union** of both sides' labels, in
> §1's canonical order. No fold, record merge, reinforcement or consolidation drops a
> label the target or the incoming record carried, and no implementation writes one
> side's tuple over the other's.

> **Normative.** The clause above is about **two records becoming one**. The owner's
> **label** merge of §9 is a different act on a different object — it renames one
> label across many records and folds no record into another — and is governed by §9
> alone. Neither clause is an exception to the other, and the word "merge" is not one
> operation in this ADR.

> **Normative.** **A `SUPERSEDE` carries nothing across.** The correction's topics
> are the ones its own producer proposed for it, and the retired target keeps its
> own. ADR-0040 §5a's differential governs, unchanged: the surviving record carries
> nothing of the target.

> **Normative.** **The owner's act** (§9) is the only in-place write of this field,
> and it writes the record's topics at the record's own id.

**The union is ADR-0204 §5's disjunction with a wider carrier, and it is taken for
the same reason.** That section rules "the survivor's value is the **disjunction**
of both sides' values, and no implementation writes `False` over a `True`", on
ADR-0106 §4's ratchet: "a fold's value is the **disjunction** of both sides, so a
tainted belief reinforced by a clean observation stays tainted. Without that, the
laundering the marker exists to stop simply moves one step along". A dropped label
is the same failure in this currency — a record the owner filed under "health"
quietly stops being reachable by a health-scoped act the first time an unlabelled
proposal reinforces it, and nothing about the survivor looks wrong afterwards.
`_merge` in `memory/ingest.py` already computes exactly this shape for
`derived_from_external` and `supplied_withheld_content`, once before its two arms so
neither can drift; the union joins them in that minority rather than the majority
that takes the incoming record's value.

**A `SUPERSEDE` is not an operation on this field at all**, for the reason
ADR-0204 §5 gives: ADR-0040 §5a "carries nothing of the target onto the surviving
record", the correction's topics are a member of the correction's own statement of
what it is about, and the target is "retained with a closed validity window"
(ADR-0045 §4) still carrying its own.

**In place at the same id for the owner's act, and only for the owner's act.**
ADR-0068's freeze is a property of the *objects*, not a promise that a row is never
rewritten: `_merge` already returns `incoming.model_copy(update={"id": target.id,
…})`, so a record at a stable id whose fields moved is the store's existing shape.
What the owner's act must not do is supersede: a relabel changes no belief, so
retiring the record and minting a new id would close a true belief's validity
window, break every `evidence` citation that names it, and put the belief where
ADR-0073 §3 makes it "unreachable by phrase and destroyable by id" — three real
losses to record a filing correction. The durable record of the act is the
preference §9 captures, not a second belief id.

### 9. The owner's acts: relabel, merge, and what the correction is allowed to reach

> **Normative.** The owner may **relabel** a record: replace the whole of that
> record's `topics` with a set they state. The act writes the record's topics at its
> own id, changes no other field of it, and is final for that record until the owner
> acts again.

> **Normative.** The owner may **merge** two labels: every **live** record carrying
> label A carries label B instead, and no live record carries A afterwards. The merge
> is all-or-nothing over the records it reaches — it commits for every one of them or
> for none — and it destroys nothing: a record whose only label was A carries B, never
> the empty tuple, and no record is deleted, retired or superseded by a merge.

> **Normative.** A record that is **not live** — a target ADR-0045 §4 retained with a
> closed validity window — is untouched by a merge and keeps the labels it was written
> with, as §8 requires. A merge edits what the store believes now; it does not rewrite
> what the store believed then, and no clause here obliges or permits a surface to say
> that a retired record's labels were changed.

> **Normative.** An act under either clause above is created **only** by an
> explicit owner act through a client. No model, plan, tool, reader, scheduler job,
> `Settings` value, migration, upgrade or first run performs one, and no installation
> infers one from what it holds.

> **Normative.** An owner act that corrects a proposed labelling is captured by
> `learning/` as a `PreferenceMemory`. The preference is a record like any other: it
> is the owner's, it is correctable, and it is deletable, and it is the durable record
> of what the owner asked for.

> **Normative.** That preference is **not** an input to any proposer under this ADR,
> and no clause here guarantees that it reaches one. §5's supply is
> `Sequence[TopicLabel]` and carries labels alone — no preference text and no
> rejected-to-corrected mapping — and no implementation may read a preference into it,
> because the labels it carries are the store's distinct labels and nothing else. What
> steers the next proposal is the **merge act above**: after it, the abandoned label
> is on no live record, so no later run reads it and no later prompt is supplied it,
> and the corrected one takes its place. A run already under way keeps the vocabulary
> it has accumulated (§5); the correction reaches the next one.

> **Normative.** A merge is an edit of the store and **not a prohibition on a label**.
> No clause of this ADR forbids any producer from minting an admissible label the owner
> once merged away, on this record or a later one; the owner's remedy is to merge
> again, and the deterministic instrument for one record is the relabel act. No
> implementation maintains a list of forbidden labels, and no lane adds one without an
> ADR deciding it.

> **Normative.** A supply that carries the preference's own semantics is deferred
> (§15) and belongs to the surface ADR below, which is the instrument that knows what
> shape a correction takes. No lane widens §5's seam to carry one without it.

> **Normative.** No consumer of the axis reads a preference at read time to decide
> what a record is about. Where the owner wants a record's label settled rather than
> steered, the instrument is the relabel act above, which is deterministic and final
> for that record.

> **Normative.** The **surface** carrying these acts — its operations, their
> arguments, their rendering and their confirmation — is not decided here, and no
> lane implements one without an ADR deciding it (golden rule 5, ADR-0015 §5).

**This is ADR-0199 §6's shape, clause for clause, and it is adopted because that
section already argued it.** There, the owner's disclosure record is "created
**only** by an explicit user act through a client", never minted "from a source it
is already reading or a channel it is already serving", and "The surface carrying
these records … is not decided here". Every one of those properties is independent
of what the record is *about*, they are what make an owner act mean anything, and
adopting them costs nothing and settles the questions the surface lane would
otherwise re-argue.

**The relabel/merge pair is the model-trained-by-the-owner shape #1719 §4 settles
for its own axis**, and it is the same here: "The model is trained by the owner, not
switched off." The deterministic layer is the act on the record; the soft layer is
the vocabulary the next proposal is supplied, which the merge act *is what edits*.
Neither substitutes for the other, and the clauses above say which is which so that a
lane does not implement the correction as a read-time rewrite, which would be the
read-time classifier again.

**And the preference is held to what it can actually do.** #1720 asks for "the
correction path, which is a `PREFERENCE` memory the proposer is supplied next time",
and half of that is unreachable through the only seam this ADR defines: a
`Sequence[TopicLabel]` cannot carry "not `wellbeing`, `health`" — it carries labels,
without text and without a relation between two of them. Writing the guarantee anyway
would be a clause no conforming implementation could satisfy, which is worse than a
named deferral. What is kept is the part that works and is the part that matters: the
owner's act changes the store, the store is what the vocabulary is read from, and the
next proposal sees the corrected world rather than a sentence about it.

**A merge destroys nothing, stated because the obvious implementation does.** The
natural way to write "merge A into B" is to drop A and add B, and on a record whose
only label was A a bug in that order leaves the empty tuple — a record that silently
falls out of every topic-scoped act, which is §7's second wrong reading arriving by
accident. All-or-nothing is ADR-0101 §5's rule for the erasure, taken here for a
weaker act because the failure mode it prevents is partial state the owner cannot
see.

**Why a relabel is not a `SUPERSEDE`, in one line**: §8's last paragraph. A merge is
the same act performed over a set, and inherits it.

### 10. Topics are out of the proposal fingerprint

> **Normative.** `topics` is excluded from the canonical projection
> `MemoryUpdateProposal.proposal_fingerprint` digests, alongside `id`, `score` and
> `provenance.last_updated`. Two proposals differing only in their topics have one
> fingerprint and are one question.

**This applies ADR-0078 §7's stated criterion rather than amending it.** That
section rules: "The projection is the whole record minus the fields that are
*bookkeeping about the record rather than the belief it states*, and there are
exactly three", and it fixes the criterion rather than the inventory — "where a
field is arguable the criterion decides it rather than taste".
`MemoryUpdateProposal.proposal_fingerprint`'s docstring states the same
forward-looking intent, that the criterion "decides the next one rather than an
inventory having to be extended by whoever adds it". Topics are bookkeeping about
the record: they say how it is filed, not what is believed.
The owner asked to accept "you dislike early meetings" is being asked about the
proposition, and whether the proposer filed it under `"work"` or `"routine"` is not
part of the offer.

**And the operational reason is the one that section gives for
`provenance.last_updated`.** It is excluded because "two identical observations
produced a minute apart carry different stamps, so every one of them is a new
question and the user is nagged by the mechanism whose job is to stop that". A
model-proposed label is not a deterministic
function of the episodes; re-observing the same material can legitimately yield
`("health",)` on one pass and `("health", "sleep")` on the next. Including it would
mint a fresh question for a proposal the user has already answered, on a difference
they were never shown — the exact failure. `ModelBackedObserver` guards the same
property from the other side by making its confidence "a pure function of the
epistemic step and the number of distinct supporting episodes — no clock, no
randomness, nothing from the response"; a field that *is* from the response has to be
kept out of the digest instead.

**Excluding it is also what makes §8's union reachable.** A `REINFORCE` folds a
proposal against a target it matches; if two labellings of one belief were two
questions, they would rarely reach a fold at all, and the union would be a rule
about a case that does not arise.

### 11. Scope: one `core` file, no Protocol, and no `PROTOCOL_VERSION` bump

> **Normative.** This ADR adds one field to one `core` type and three names to
> `core/types.py` (`TopicLabel`, `MAX_TOPIC_LABEL_LENGTH`, `MAX_TOPICS_PER_PROPOSAL`),
> and changes nothing else in `core`. **`core/protocols.py` is untouched**: no new
> Protocol, no new member on one, no changed signature. It adds no `Settings` field, no
> member of the promoted `AssistantEngine` surface, no wire operation, no tool and no
> `RoutableOperation` member.

> **Normative.** `PROTOCOL_VERSION` does not move for this change.

> **Normative.** No read returning records is filtered on topics by this ADR.
> `MemoryStore.search`, `list_beliefs`, `get`, `get_many`, `export` and `walk_records`
> gain no topic argument, and no surface, consumer or later lane may add one without
> the ADR that decides it.

> **Normative.** This ADR requires **no column, index, migration or derived storage
> of any kind**, and forbids none. A record's tuple round-trips through whatever the
> store already persists a record's fields with; §5's vocabulary is accumulated in
> memory from records already read and is never stored. The storage a **filtered record
> read** would need is the consumer lane's, decided in its own ADR alongside the read
> it serves.

> **Normative.** Nothing here authorises egress, relaxes a permission floor, widens
> a grant, or is cited toward a designation, a registration or a destination.

**The version rule is applied rather than asserted past.** ADR-0124 §9's test is
that `PROTOCOL_VERSION` is bumped by any change after which a frame a conforming
peer at the new version may send would be refused by a conforming peer at the old
version, or accepted with a different meaning. `MemoryBase` carries
`model_config = ConfigDict(frozen=True)` and does not set `extra="forbid"`, and the
new member has a default, so an older peer decoding a newer hub's record ignores a
member it does not know. The direction that would break — a peer *sending* a record
whose label the receiver's validator refuses — does not exist: no
`AssistantEngine` method takes a `MemoryRecord` or a `MemoryBase` as an argument,
and `wire/surface.METHODS` is derived from that Protocol. That is the same test
ADR-0204 §7 applied to `Provenance` and reached the same answer, and it is what
distinguishes both from ADR-0181 §3's field, which was required with no default on a
model that sets `extra="forbid"`.

**No storage, because nothing reads the field from the store.** ADR-0100 §8 gave
`about_person` a nullable column because a filtered read was that axis's first
consumer. Here there is no such read: §5's vocabulary is built from records the walk
already decoded, and every record-filtering consumer is deferred. Fixing a schema
before the read that has to use it exists is how a schema gets chosen for the wrong
query, and the lane that adds the read is the one that will know whether it wants a
column, a child table or an index. ADR-0201 §3's reasoning is what that lane will owe
— "the exclusion is expressed as the `kinds` argument of the `MemoryStore.list_beliefs`
read behind the lookup, so it is applied by the store before the page cut" — and it
cannot be discharged by a decision taken before the read exists.

### 12. The representative-input tests this decision owes

These are what the implementing lane must make a test say, not a suggested file
layout. Each names an input and the outcome it fixes.

1. **A canonical label round-trips.** A record constructed with
   `topics=("health",)` serialises and reconstructs carrying the same tuple, through
   the `MemoryStore` conformance suite so every implementation persists it rather
   than silently dropping it.
2. **`"Health"` is refused**, and so are `" health"`, `"health "`, `"health  care"`,
   `""` and a 65-character label — each at construction, each with the value unchanged
   in the error rather than folded. A 64-character label is admitted, so the boundary
   is pinned on both sides. **The whitespace arm is exercised beyond the tab**:
   `"health\tcare"`, `"health\ncare"` and `"health\u00a0care"` are each refused, so an
   implementation that checked only the space and the tab does not pass — U+00A0 is
   the case that separates a check written against `str.isspace()` from one written
   against a two-character list.
3. **An unsorted tuple is refused**, and so is `("health", "health")`. `("health",
   "sleep")` is admitted and `("sleep", "health")` is not.
4. **A record constructed with no `topics` carries the empty tuple**, and decoding a
   serialised record written before the field lands yields the empty tuple.
5. **A tuple of five labels is admissible on the type**, and the producer bound is
   asserted where the producer is — a model response naming five labels yields no
   topics on that proposal, and the proposal itself is returned.
6. **A malformed topics entry does not discard the proposal and moves no counter.** A
   response whose topics entry is absent, null, not a list, or carries a non-canonical
   string yields a proposal with the empty tuple, and the pass reports
   `discarded_unusable` and `discarded_over_limit` unchanged — so
   `len(proposals) + discarded_unusable + discarded_over_limit` still equals the
   number of entries the model emitted.
7. **A provider failure yields no topics and no record.** The observation pass
   raises and writes nothing, rather than writing unlabelled beliefs.
8. **The vocabulary is accumulated across a run's chunks.** A consolidation run whose
   first chunk carries records labelled `("health",)` sends no vocabulary in that
   chunk's prompt and sends `["health"]` in the next chunk's.
9. **The vocabulary is ordered and bounded.** With three labels across the records a
   run has read, they are supplied commonest first, ties broken by label ascending; a
   run that has read more than `DEFAULT_PAGE_SIZE` distinct labels supplies exactly
   `DEFAULT_PAGE_SIZE` of them from the head of that order.
10. **The vocabulary counts only what this run read.** Two consecutive runs over
    disjoint chunks supply disjoint vocabularies; the second run's first prompt carries
    nothing, whatever the first run read.
11. **Nothing durable records it.** A run leaves the store byte-identical to a run of
    the same chunks with the field absent, apart from the records it wrote: no new
    table, column, row or cursor, and a second process reading the store concurrently
    sees no vocabulary state.
12. **The consolidation prompt carries the vocabulary and the observation prompt does
    not.** An observation pass over a store full of labels sends the batch and nothing
    derived from a belief, which is the assertion that keeps ADR-0077 §3 true.
13. **A record that leaves the live set leaves the vocabulary with it.** A run reads
    only what the store returns, so a record whose `validity` window has closed or
    whose `expires_at` has passed contributes no label — asserted by driving the walk
    over such a store rather than by a rule about a cache, because there is no cache.
14. **A supplied label is a hint and not a constraint.** A producer that proposes a
    label the vocabulary did not offer has its proposal accepted unchanged, and one
    that proposes nothing is not made to.
15. **The fold takes the union, on both arms.** A target carrying `("health",)`
    reinforced by an incoming record carrying `("sleep",)` survives with
    `("health", "sleep")`. The direction that must be exercised is the one an
    implementation copying the incoming tuple would pass: a **labelled target
    reinforced by an unlabelled incoming**, whose survivor keeps `("health",)`.
16. **A `SUPERSEDE` carries nothing across.** A correction proposed with
    `("sleep",)` against a target carrying `("health",)` writes `("sleep",)`, and the
    retired target still reads `("health",)`.
17. **Capture writes the empty tuple** on every episode it records, on both the
    ordinary and the resumption path.
18. **A reader's proposal carries the empty tuple**, whatever the source entry
    contains — including a source entry whose own fields are named like labels.
19. **Two proposals differing only in `topics` share a `proposal_fingerprint`**, and
    therefore one `question_key` against one conflict set.
20. **A relabel writes at the same id.** The record's id, `content`, `provenance`
    and `validity` are unchanged and every citation naming it still resolves.
21. **A merge is all-or-nothing and destroys nothing.** A record whose only label was
    the merged-away one carries the survivor label, not the empty tuple; a merge that
    fails part-way leaves no record carrying the new label.
22. **A merge leaves a retired record alone.** A target retired with a closed validity
    window that carries the merged-away label still carries it afterwards, and the
    merge reports having reached only the live records.

### 13. What the implementing lane owes

The implementation is one lane, briefed after this ADR merges (ADR-0015 §5, golden
rule 5). It owes:

1. **The three names and the field** in `core/types.py`, documented in place with
   what a value means and what an empty tuple means, and the canonical fakes and
   record builders in `ai_assistant.testing` extended to carry them.
2. **The `MemoryStore` conformance suite** pinning the field's round-trip, so every
   implementation persists and returns it rather than silently dropping it. **No
   Protocol changes and no new Protocol is added, so no triad is owed**
   (`CONTRIBUTING.md` → "Adding a Protocol"); `core/protocols.py` is not edited.
3. **The producer half**: the topics entry in `ModelBackedObserver`'s envelope and in
   `ConsolidationStage`'s, ignored rather than counted where it cannot be used (§4),
   with the canonical form applied by the producer before construction.
4. **The run-scoped accumulation** in `ConsolidationStage` alone: an in-memory count
   over the labels of records the run has read, bounded and ordered as §5 states, reset
   per run, and threaded into the prompt the stage already builds. No store read, no
   migration and no durable state.
5. **The fold's union** in `memory/ingest.py`, written on both arms beside the two
   computations that already take a disjunction there.
6. **The exclusion** of `topics` from `MemoryUpdateProposal`'s fingerprint
   projection.
7. **The twenty-two tests of §12.**

> **Normative.** The owner's acts of §9 are **not** in the implementing lane above.
> They need a surface, the surface is a promoted-surface change, and it is therefore
> its own ADR and its own lane (golden rule 5, ADR-0015 §5). A lane implementing the
> seven items above and adding an owner-facing relabel or merge operation has exceeded
> this decision.

### 14. What a topic is not

> **Normative.** A topic is **not a retrieval axis**. `MemoryStore.search` stays
> band-neutral and confidence-neutral in the sense ADR-0072 §5 ruled, gains no topic
> argument here, and no implementation, lane or later ADR makes a topic a term in any
> ordering, score, weight, threshold or cut applied to retrieved records. Whether a
> topic may be an *eligibility* filter on a read is a separate question, reserved to
> an ADR that argues it as ADR-0113 argued the band.

> **Normative.** A topic is **not a tier and not a sensitivity**. It carries no
> posture, no permission, no band and no disclosure consequence. `DataTier`,
> `BeliefBand`, `Provenance.source` and every clause of ADR-0199 §3 are untouched: no
> record becomes speakable, unspeakable, guarded or exempt by carrying a label, and
> no lane may cite a topic as ground for any of those before an ADR makes it one.

> **Normative.** A topic is **not a subject**. `MemoryBase.about_person` keeps
> exactly the meaning ADR-0100 gives it, its clauses bind unchanged, and neither
> field is read for the other. A record may carry both, either or neither, and no
> validator ties them.

> **Normative.** A topic is **not an identifier**. It names no entity, resolves to
> nothing, is not a key into anything, and is not usable as a cross-hub or
> cross-store reference.

**Read together with ADR-0199 §2, this is what keeps the axis honest.** A label is
recorded at write and read as a field; it does not acquire authority by being read
often, and no consumer may promote it into one of the four things above by treating
it as one. The clauses are stated as prohibitions rather than left as omissions
because each of them is a plausible next step that a lane could take without
noticing it was a decision.

### 15. Deferred, by name, each with the condition that fires it

- **A topic-scoped `forget`.** #1720's first consumer. It owes three things this
  ADR cannot give it: a `MemoryStore` read that selects records by label, which is a
  Protocol change and therefore its own ratified, separately-merged ADR (golden
  rule 5, ADR-0015 §5); a `RoutableOperation` member, which ADR-0197 §3's widening
  rule admits only where "its arguments are either none, or resolvable by §5's
  deterministic lookup from a router-named query" — a topic is not the "scalar
  identity read off one of them" §5 fixes, and a lookup resolving to many records is
  the case §5 ends in `RouteOutcome.AMBIGUOUS`, so the member needs its own argument
  law rather than a paragraph; and a fresh reading of ADR-0201 §1, whose exclusion of
  `EPISODIC` from the lookup was decided for a single-record `forget` and means
  something different when the act is "everything about X" — with §6 above, the
  transcripts carry no label, so the act cannot reach them however §1 is read, and
  that has to be said to the owner rather than discovered. **Fires** when the
  utterance is scheduled.
- **A topic-scoped guard.** #1719's class-level act, which that note already defers
  to this axis. **Fires** after #1719's ADR ratifies and its per-record acts land;
  this ADR names the seam it widens and decides no part of it.
- **The reach of a disclosure preference.** Whether an ADR-0199 §6 owner record may
  be keyed on a topic rather than on a class, so that "my coffee habits may be said
  aloud" generalises. **Fires** with the surface ADR-0199 §6 defers, which is the
  first instrument that can carry such a record at all.
- **An owner-stated topic at the moment of an assertion.** The gap §6 names: a
  belief the owner asserts through `learn` is unlabelled, because
  `RuleBasedFeedbackProcessor` holds no provider and `AssistantEngine.learn` takes a
  `FeedbackEvent` with nowhere to put a topic. **Fires** with §9's surface ADR, which
  is the same lane and the same argument: an owner-stated topic is an owner act, and
  it needs a carrier on the promoted surface.
- **Topics on episodes.** §6 rules that no producer proposes one today. **Fires**
  where a consumer's promise is materially wrong without them — the first case is a
  topic-scoped guard, since an unguarded transcript of a guarded conversation is the
  laundering shape ADR-0204 §5 closed for its own axis by inheritance rather than by
  a second proposal.
- **A vocabulary supplied to the `Observer`.** §5 withholds it because ADR-0077 §3
  rules that observation's "payload is the batch and nothing else", and this ADR is
  not the instrument that changes another ADR's ruling. **Fires** with an ADR that
  amends or partially supersedes that clause under ADR-0070 §1 and ADR-0082 §1 and
  argues the ADR-0004 §7 minimisation trade in its own terms — most likely the lane
  that measures the fragmentation §5 predicts, because the trade is worth arguing once
  there is a figure rather than a fear.
- **A supply that carries the owner's correction to a proposer.** §9 keeps the
  `PreferenceMemory` and declines to promise it reaches one, because
  `Sequence[TopicLabel]` cannot carry a preference's text or a rejected-to-corrected
  mapping. **Fires** with §9's surface ADR, which decides the shape of the correction
  and is therefore the only lane that can say what a seam carrying it would look like.
- **A matching rule wider than equality.** §3 reserves it. **Fires** with the first
  consumer whose promise cannot be kept by exact labels — most likely the same
  topic-scoped `forget`, where "health" and "healthcare" reaching different sets is
  the owner's first surprise.
- **A source's own categories as a topic route.** §6 refuses it. **Fires** with an
  ADR that reckons with ADR-0183 §3 and states what an adversary who can place bytes
  in a source may thereby cause a topic-scoped act to reach.
- **A per-record record of who last set a record's topics.** After §9's relabel a
  record's labels are not its producer's, and `Provenance.source` names the producer
  rather than the labeller. **Fires** with the first surface that renders a topic
  beside where it came from, which is §9's surface lane.
- **A bound on the topic set a fold may accumulate.** §1 leaves the type unbounded
  and §8's union can grow it. **Fires** with the first record whose accumulated set is
  no longer owner-legible, which is a measurement on a real store rather than a number
  to guess now. The shape such a bound would take is already worked: ADR-0086 §2 puts
  it at the `MemoryWriter` seam on installs, and §§3–4 oblige a rule for choosing what
  is dropped and a recorded count of the loss. §1 above says why neither is available
  for this field today, so a lane taking this on owes an answer to both rather than a
  `max_length`.
- **A store-wide vocabulary read.** §5 supplies a producer the labels of the records
  its own run walked, and nothing wider, because a `MemoryStore` read returning the
  store's whole vocabulary could not be made both cheap and honest about liveness (§5,
  and the Alternatives). **Fires** with a measured store in which the run-scoped
  vocabulary demonstrably fails to converge, and it owes what this ADR could not
  supply: a bound that survives a store of millions of labels, and a liveness rule that
  cannot disagree with `MemoryStore.get`.
- **The storage a filtered record read needs.** §11 requires none, because no read here
  filters records by label. **Fires** with the lane that adds that read, which is the
  lane that knows whether it wants a column, a child table or an index.

### 16. This ADR classified under ADR-0070 §1 and ADR-0082 §1

ADR-0082 §1's test is ADR-0070 §1's applied to the earlier ADR's text: would a
reader holding only that ADR now act differently, or read one of its clauses more
widely than it now holds?

> **Normative.** This ADR supersedes nothing, amends nothing and records nothing
> against any earlier ADR. Every ADR it cites binds after it exactly as it bound
> before, and no `Status` line moves.

The four nearest candidates are worked through, because each is close enough that a
reader might expect a record and its absence should be argued rather than assumed.

- **ADR-0100 §6's "whom, not what".** That clause reads: "The axis is *whom*, not
  *what*. A belief about a company, a project, a device or a topic states no
  subject." A reader holding only ADR-0100 states no subject on a topical belief
  before this decision and states no subject on one after it. Nothing they do
  changes; this ADR occupies the *what* axis that clause declines, which is the
  clause being relied on rather than narrowed.
- **ADR-0100 §4's "nobody may infer one".** That clause is scoped by its own words
  to the subject: "No producer may infer a subject from content — not by a model, not
  by a name-matching heuristic, not by parsing a title." A reader holding only
  ADR-0100 infers no subject after this decision either — §14 keeps the two fields
  unread for each other, and §6 forbids any producer proposing topics for a record it
  did not produce. What this ADR does is decide a *different* field's rule, and it
  decides it differently on grounds ADR-0100 §4 itself names: inferring a subject is
  person-identification, which "decides who counts as a person, when two mentions are
  one person, and when a name in a sentence is its subject rather than its scenery"
  and is #691's question. A topic label resolves to nothing and enrols nobody, so
  none of the three sub-decisions arises. The asymmetry is argued rather than
  inherited.
- **ADR-0077 §3's payload clause.** "The payload is the batch and nothing else …
  It does **not** carry the user's existing beliefs, the profile, the context facet,
  or a plan." A reader holding only ADR-0077 sends the episodes and their citation
  labels before this decision and sends exactly those after it: §5's fourth clause
  adds nothing to the observation prompt, and its supply lands on
  `ConsolidationStage`, which ADR-0077 does not govern. An earlier draft of this ADR
  *did* put a store-derived vocabulary into `Observer.observe`; that would have been a
  reader acting differently, which is ADR-0070 §1's line, and it was removed rather
  than recorded — a record on ADR-0077 is a change to ADR-0077's text, and this lane's
  fence does not reach it. §15 names the instrument that may take it.
- **ADR-0072 §5 and ADR-0113 §4.** §14's first clause restates their rules for this
  axis rather than touching them, and §11 adds no argument to `search`. A reader
  holding only either ADR ranks exactly as they did.
- **ADR-0199 §2.** Its prohibition is on deciding a class "by inspecting the
  content" at the point of decision, and this ADR adds a recorded value that a later
  read keys on — which is the shape §2's first clause *requires*, not an exception to
  it. A reader holding only ADR-0199 withholds exactly what they withheld before:
  §14's second clause makes carrying a label change no placement.

**And one non-candidate worth naming.** ADR-0078 §7's fingerprint criterion is
applied by §10, not amended: that section fixes a criterion and says that "where a
field is arguable the criterion decides it rather than taste", so a fourth excluded
field decided by it is the criterion working. What §7 also says — "there are exactly
three" — is a count of the fields that existed to be judged when it was written, not
a bound on the criterion; a reader holding only ADR-0078 applies the same test to the
same three fields after this decision as before. The projection's *code* changes; the
rule does not.

## Consequences

**What becomes possible.** Three deferred acts become expressible for the first
time, each in its own lane and each without re-deciding this axis: "forget everything
about my health", "keep everything about my health to me", and a disclosure
preference with a reach. None of them is any closer to *shipping* than it was, and
that is deliberate — what this removes is the shared dependency that would otherwise
have been decided three times, differently.

**What becomes harder.** Every record now carries a field that three of five
producers leave empty, so every surface that acts on the axis owes §7's disclosure of
what it did not reach, and will owe it for as long as that is true. A lane that finds
that unacceptable has one honest remedy — giving a provider-free producer a route to a
label, which is §15's owner-stated topic — and one dishonest one, inferring the label
at read, which §4 forbids.

**What this costs at run time.** A dictionary update per record a consolidation run
reads, a slightly longer prompt per consolidation chunk after the first, and a few more
tokens in each producer's response. No store read is added and no schema changes. The
observation prompt does not grow at all. No new call, no new provider dependency, no
new failure mode on any path that had none: the three producers that hold no provider
are untouched, and the two that do already end their pass on a `ModelError`.

**What would trigger revisiting it.** A measured store in which the observer's labels
fragment — which §5 predicts, because the observer is supplied no vocabulary and
ADR-0077 §3 is why. That measurement is the input the deferral in §15 waits for, and
the candidates it would choose between are an amendment to ADR-0077 §3, an
owner-curated vocabulary, and the matching rule §3 reserves. Or a consumer arriving
that genuinely needs the axis at read time, which this decision forbids and which
would have to be argued as a supersession rather than an extension.

**What it does not fix.** The store the owner has today is unlabelled, and this
decision labels nothing retrospectively: a belief written before the field lands
carries the empty tuple, and §4's prohibition on read-time inference means no backfill
can honestly produce one. The remedy available to the owner is §9's relabel, one
record at a time, and the remedy available to the system is time.

## Alternatives considered

**A single topic per record rather than a set.** ADR-0100 §6 chose exactly this for
the subject — "A belief has at most one subject. A belief about two people is two
beliefs" — and its reason does not transfer. There, the split is free: "two beliefs
about two people are two things the user can correct and delete independently". Here
it is not free but lossy in the other direction — "I stopped drinking coffee after my
doctor asked me to" is one proposition that a health-scoped act and a coffee-scoped act
should both reach, and splitting it into two beliefs would duplicate a fact the store
would then have to keep consistent with itself. The cost of the set is §1's ordering
clause and §8's union; the cost of the scalar is a duplicated proposition, which is
worse.

**An owner-curated closed vocabulary.** Refusing a label the owner has not
authorised would make convergence structural rather than encouraged. It was rejected
because it needs a management surface before the axis has a single consumer, because
the first hundred records would be written before the owner had any basis for curating
anything, and because a producer that cannot mint a label for a genuinely new subject
files it under the nearest wrong one — losing the distinction permanently, which §5's
last paragraph gives as the asymmetry that decides this. The merge act of §9 is the
curation instrument, applied after the evidence exists rather than before.

**Normalising a non-canonical label instead of refusing it.** Rejected in §3 on
ADR-0100 §6's reasoning about values that are nearly right, and on the practical
ground that the only producer that can emit a non-canonical label is one that did not
fold its own model's output — a bug that a silent fold would hide in the one place
nobody reads.

**A `None`-for-unrecorded third state.** Rejected in §7 on ADR-0204 §1's argument
against the same shape: the empty tuple already is the unrecorded state, and a third
state would oblige every consumer to hold a rule about data no producer will ever
write.

**A `MemoryStore` read returning the store's whole vocabulary.** Three rounds of
review were spent on this and it does not hold, so it is recorded rather than quietly
dropped. Its promise was the distinct labels of every live record, ordered by usage.
Ordering by usage costs a walk of the store; moving that walk before the first chunk
relocates the cost without bounding it, which is ADR-0111 §4's concern wherever the
delay sits on a serial loop; and the only way to bound it — answering from storage
maintained as records are written — contradicts liveness, because a record leaves the
live set when a clock passes its `expires_at` or its `validity` window with no write to
maintain anything, so the maintained answer and `MemoryStore.get` would disagree about
what the store holds. A derived table would additionally have to join every write path,
`write_atomic`'s rollback included, to avoid a failed batch leaving the index ahead of
the records. Each of those is soluble; together they are a storage subsystem bought for
a prompt hint. §5 takes the labels the walk already decoded instead, which is exact
about liveness by construction, costs a dictionary update, and needs no contract at
all. §15 names what a later ADR would have to supply to take the wider read.

**Supplying the vocabulary to the observer as well.** This was the first draft, and
it read well until ADR-0077 §3 was quoted rather than remembered: "The payload is the
batch and nothing else … Sending beliefs would be the obvious way to stop the observer
re-proposing what is already known — and it is refused". A store-wide label set is a
second class of Tier 1 data in that prompt, arriving for the very reason that clause
refuses, so taking it would have needed a record on ADR-0077 under ADR-0070 §1 — an
edit to another ADR's text, which this lane's fence does not reach and which deserves
its own argument rather than a paragraph here. It is deferred in §15 with the
instrument that may take it. What is *not* an alternative is taking the payload
quietly and leaving §16 saying nothing changed.

**Dropping the vocabulary supply altogether.** The smallest ADR of all, and it was
rejected because the supply is genuinely free in the form §5 takes: the records are
already decoded, the prompt already carries them, and the accumulation is a dictionary.
Declining it would leave §9's merge act as the sole convergence instrument and make the
axis's usefulness a function of how often the owner tidies it.

**Putting the field on `Provenance`.** Rejected in §2 on ADR-0100 §2's own test.
The tell is that it would sit beside `derived_from_external` and
`supplied_withheld_content`, both of which answer "what stood in front of the
producer", and answer a different question from either.

**Giving capture or the readers a `ModelProvider` so every record is labelled.**
Rejected in §6. On the capture side it puts a model call on the turn's own path for a
filing word, against ADR-0074 §4's rule that capture judges nothing; on the reader
side it makes a scheduled source read depend on a provider, and buys a label whose
input is content ADR-0183 §1's adversary controls.
