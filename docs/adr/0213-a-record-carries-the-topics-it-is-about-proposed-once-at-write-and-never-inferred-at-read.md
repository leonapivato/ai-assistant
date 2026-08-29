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
rule 5 and ADR-0015 §5. And it does not put anything derived from a belief into an
observation prompt: ADR-0077 §3 rules that payload on ADR-0004 §7's minimisation
ground, and reopening that trade wants evidence this decision does not have — a
measured store in which the vocabulary demonstrably fails to converge — rather than a
paragraph. §5 states what declining it costs and §15 names the condition that fires
the ADR which may take it.

What it can decide is everything a consumer needs to *exist*: what the field is,
what a value in it means, what an empty one means, who may write one, what
happens to it under a fold, and what may never be done with it.

## Decision

### 1. One additive field on `MemoryBase`, the four names beside it, and the bound on a record's set

> **Normative.** `core/types.py` gains `TopicLabel`, an annotated refinement of
> `EncodableText` admitting exactly the canonical form §3 fixes, and the three
> constants `MAX_TOPIC_LABEL_LENGTH`, `MAX_TOPICS_PER_PROPOSAL` and
> `MAX_TOPICS_PER_RECORD`.

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
        "'no topic' nor 'every topic' (§7). Strictly increasing by code point "
        "(§1). No record this system installs carries more than "
        "MAX_TOPICS_PER_RECORD labels; the bound is enforced at the "
        "MemoryWriter seam and not here, so a longer tuple is admissible and "
        "a record stored with one stays readable (§1)."
    ),
)
```

> **Normative.** The tuple is **strictly increasing** by code point: a value that
> is unsorted, or that repeats a label, is refused at construction. Order carries
> no meaning here, so fixing one is what makes two equal sets one value —
> serialise-and-reconstruct parity, digest stability and a store comparison all
> follow from it, and none of them survives a field where `("health", "sleep")`
> and `("sleep", "health")` are different bytes.

> **Normative.** `MAX_TOPICS_PER_RECORD` is **16**, a fixed constant of
> `core/types.py`. **No `MemoryWriter` *installs* a record whose `topics` carries
> more labels than it.** Where the record it would install does, it installs the
> retained subset §8 specifies. "Install" is ADR-0081 §1's sense, which is the scope
> ADR-0086 §2 states its own bound with: a write that merely *retires* an existing
> record — storing it back with only its validity window narrowed (ADR-0080 §1) —
> asserts nothing new about what the record is about, changes no label, and carries
> the tuple as it stands.

> **Normative.** The bound is a **writer obligation and not a validator on the
> type**. `MemoryBase` admits a longer tuple, and a record decoded from storage
> carrying one is read rather than refused. `MAX_TOPICS_PER_PROPOSAL` bounds
> separately and earlier what a *producer* may propose (§4). The two are one rule at
> two seams over two different objects — a proposal's suggestion and an installed
> record — and neither is a second enforcement point for the other.

**This is ADR-0086's shape, taken because its reasoning holds here and not because
the fields rhyme.** That ADR bounds `Provenance.evidence` with a fixed `core`
constant (§1), enforces it at the `MemoryWriter` seam on installs (§2), gives the
fold an overflow rule (§3) and records the loss on the record (§4). The first three
are taken; the fourth is declined below, with its own argument. Two questions decide
the placement, and ADR-0086 answers both in its own currency.

- **ADR-0086 §2's test is answered *no* here, so the type-level bound is available —
  and is still the wrong seam.** The test is "does it refuse something that already
  worked", and a `max_length` on a brand-new field refuses nothing that exists today
  (§3 says the same thing about the canonical form). What rules it out is the
  direction the field will be changed in. §11 lets an older peer decode a newer hub's
  record because the member has a default and `MemoryBase` does not set
  `extra="forbid"`; a `max_length` would take that back for the one change a later
  ADR is most likely to make — raising this constant — by making a record written at
  the new bound unreadable to a peer at the old one. ADR-0086 §1's third bullet
  refuses a *configurable* bound for exactly that reason ("A record exported from a
  deployment at 512 and imported into one at 64 would be a record the receiving
  system's own contract refuses, for a reason the user cannot see and did not
  cause"), and a fixed constant that a later ADR raises reaches the same place one
  ratification later. The writer seam has no such edge: it decides what this
  deployment *writes*, never what it may *read*.
- **A type-level bound would be enforced at the fold anyway, and then enforced
  twice.** §8's union is a ratchet, and a fold whose union exceeds the bound is a
  legitimate `REINFORCE` whose result must be a *bounded record* rather than a raised
  write. The only place that can be arranged is the seam that computes the union —
  which is the `MemoryWriter` seam, where the bound already is. A `max_length` above
  it enforces nothing that seam does not, and adds a way for the two to disagree: one
  rule in two places to drift, the defect ADR-0086 §1 names when it declines a second
  enforcement point at the feedback boundary. And where they *did* disagree — a caller
  constructing a proposal the writer would have bounded — the type would raise on the
  ingest path in place of the bounded record §8 requires, which is ADR-0086 §2's own
  objection in this field's currency: it refuses "a rule that can only be obeyed by
  breaking the rule above it", and the retire exemption above exists for the same
  reason its does.

**An over-bound record is readable, converges, and is never repaired on the read
path.** The permissive type and §8's total retained subset together give exactly
ADR-0086 §2's outcome for a record that arrived from outside this deployment's bound:
it decodes and reads, its next *install* brings it under the bound, a write that only
retires it carries it whole into the history `export` keeps, and nothing walks the
store rewriting anything. That ADR states the property in as many words — "an over-long
tuple can only shrink … No migration, no backfill, no read-path repair, and nothing
that rewrites a record because of something that happened to another one" — and it is
what makes this a rule about what the deployment *writes* rather than a rule about what
it may hold.

**Why 16.** ADR-0086 §1 is right that "a bound with no number is not a bound", and
the number is chosen the way it chose 64:

- It is four times `MAX_TOPICS_PER_PROPOSAL`, so a record accumulates through
  several disjoint folds before the bound can bite at all — the shape ADR-0086 §1
  used to set 64 "comfortably above `observation_batch_size`'s default of 20". A
  bound at or near the per-proposal cap would make ordinary reinforcement displace,
  which is the churn that section refuses.
- It is small enough that a record's topic set stays readable at a glance, which §4
  gives as the axis's whole value, and small enough that a topic-scoped act over such
  a record still means something.
- It is far past the record §4 describes as "genuinely about five things", which
  that section already calls a record about one thing the vocabulary has not learned
  to name. Sixteen is a ceiling nobody should reach, not a quota to fill.

**A fixed constant and not a `Settings` field**, on §4's own reason for the sibling
two and ADR-0086 §1's for its own: a bound a deployment can raise is not a bound, and
this one crosses deployments in `export`. Nothing here is a knob.

**What this closes is ADR-0111 §4's admissibility condition, stated rather than
implied.** That section admits chunking only where "every operation it performs
inside one chunk is itself bounded", and warns that "a job whose chunk reaches an
operation with no deadline is not a job that may be chunked under this ADR". §5's
accumulation is such an operation, and with this bound its cost per chunk is the sum
of two terms, each a product of figures the configuration already holds and **neither
a function of how many chunks the run has already done**:

- **Offering the chunk's labels.** A chunk of at most `scheduler_chunk_size` records
  offers at most `scheduler_chunk_size × MAX_TOPICS_PER_RECORD` labels of at most
  `MAX_TOPIC_LABEL_LENGTH` characters, one lookup each. §1's bound is what makes the
  per-record factor a constant; without it that factor is the length of a tuple
  nothing limits, and the product is not computable at all.
- **Ordering what the accumulator holds.** §5 bounds the accumulator itself at
  `DEFAULT_PAGE_SIZE` distinct labels, so the ordering is over at most that many
  entries at every chunk of every run. Bounding only the *supplied* set would leave
  this term growing with the run — the state selected *from* would be everything the
  run had read — which is the shape a job with a growing per-chunk cost has, and is
  why the cap is on the accumulator and not on its output.

**Which operations §4's deadline clause is about, read out of §4 itself.** What a
bounded, synchronous, in-memory operation raises is whether it also owes a *timer*.
Three things in §4 answer no, so this ADR applies that clause rather than narrowing it
or amending it — §16 classifies it.

- **ADR-0111's own header says what that clause was written to stop, and it is
  blocking.** The clause is not a first draft's wording; it was added in review, and
  ADR-0111's header records why. Its ratification note reports round 1's finding "that
  §4's budget bounds nothing **if a chunk can block indefinitely**", "repaired by §4's
  second normative clause making a per-operation deadline a precondition of being
  chunked at all". A bounded synchronous loop cannot block indefinitely, and a
  precondition written against indefinite blocking does not reach one. This is the
  sentence of ADR-0111 that decides the question, and it is in ADR-0111's own file —
  so a reader holding only that ADR reads the clause this way too, which is why §16
  finds no record owed rather than arguing one away.
- **§4 supplies no way to enforce one.** "**This ADR adds no cancellation mechanism**
  and does not reach inside a chunk." A deadline is enforceable only against an
  operation that yields — an `await` on a provider call or on I/O — because nothing
  preempts a synchronous Python frame. Reading the clause as demanding a timer around
  an operation that never yields would have it require exactly what its own section
  says it does not supply.
- **§4's arithmetic carries no term for local work.** It computes "a chunk's true
  bound" as "``max_attempts * timeout + total backoff``, multiplied by the chunk's
  records" — a per-record *provider* cost times a record count, with nothing in it for
  a decode, a digest, a comparison or a sort. That is a correct bound only if such
  operations are not what the clause counts, and §4 offers it as the figure "worth
  computing before setting a chunk size".
- **The literal reading would forbid the jobs ADR-0111 exists to admit.** Every
  chunked job already performs local operations with no deadline: the JSON decode and
  model reconstruction a store runs per record on every read (`SqliteMemoryStore._decode`,
  which ADR-0086 §2 relies on by name), the digest, and the disjunctions `_merge`
  already computes over `derived_from_external` and `supplied_withheld_content`. Under a
  reading that demands a timer on each of those, no job in this system may be chunked at
  all — consolidation and the retention purge included, which are the jobs §4 is written
  for. A clause is not read into a form that forbids what its own ADR ratifies.

**And what §4 does demand of this operation, it gets.** The hazard §4 names is "a
provider call that never returns", and its instruction is that admissibility "must be
checked rather than assumed". Checked, here: the accumulation's per-chunk cost is the
two terms above, each a constant of the configuration and of this ADR and neither
growing with the run; and the only operation in a consolidation chunk that can fail to
return is the model call, which `model_timeout_seconds` already bounds and which this
decision does not touch. The rounds that raised this were right about the *earlier*
draft — with no bound anywhere the per-record factor was the length of a tuple nothing
limited, and the product §4 asks for could not be computed at all. §5 restates the
arithmetic where the accumulation is defined, and §12 pins the two inputs that would
otherwise have broken it.

**What is deliberately *not* copied is ADR-0086 §4's recorded count**, and the
asymmetry is in what the two tuples claim.

- **`evidence` claims a count and `topics` claims nothing.** ADR-0086 §4 records
  `evidence_elided` because ADR-0073 §4 obliges the surface to convey "how many
  citations stand behind it" and forbids a citation being "silently dropped" — the
  tuple stands for a warrant whose size is itself an answer. §7 rules the opposite
  for this field before any bound existed: an empty tuple is "no topic recorded", the
  set is never a claim to completeness, and every surface performing a topic-scoped
  act already owes the owner the disclosure "that the reach of the act is the labels
  that were recorded rather than the subject the owner has in mind". A count of
  labels not carried answers a question no surface asks and no clause obliges.
- **Nothing a record this deployment wrote already carried is lost.** §8's overflow
  admits the *incoming* record's labels and never displaces the labels of a target that
  conforms to the bound — which is every record this deployment installs — so a record
  filed under `"health"` cannot stop being reachable by a health-scoped act through a
  fold —
  which is the laundering ADR-0106 §4 closes and which §8 takes the union for. What
  the bound declines is a *proposal's* suggestion that did not fit, and §4 already
  rules that class: a topics entry a producer offers and the system cannot use is
  **ignored**, with no counter moving and no `core` type gaining a member to count it.
  A second treatment for the same class of non-event would contradict it.
- §15 names the condition that would fire a recorded count anyway, so this is a
  decision with a stated expiry rather than an omission.

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
> the records this run has put in a prompt — **the chunk being prompted included** —
> and puts them in the prompt it already sends. It proposes against them: it uses an
> existing label where one fits and mints a new one only where none does.

> **Normative.** The accumulation is updated **when a chunk's prompt is composed and
> before that prompt is sent**, from exactly the records that prompt carries: the
> chunk the walk returned, less the records this run itself produced, which
> `ConsolidationStage.run` already withholds. It is updated there and nowhere else. It
> does not depend on how the chunk's proposals route, on whether the write stage
> commits any of them, or on whether the cursor advances — so a run that halts at an
> unrecorded chunk (ADR-0111 §5) leaves nothing behind, there being nothing durable to
> leave.

> **Normative.** **The accumulator itself is bounded, not merely what it supplies.**
> It holds at most `DEFAULT_PAGE_SIZE` distinct labels, each with a count. A label it
> already holds has its count incremented. A label it does not hold is admitted only
> while it holds fewer than `DEFAULT_PAGE_SIZE`; once it is full it admits no new label
> for the remainder of the run, and it **never evicts** one it holds. Labels are
> offered to it in the order the records of the prompt being composed present them, and
> within one record in that tuple's own order, so what a full accumulator holds is a
> function of the walk and not of arrival timing.

> **Normative.** The supplied set is exactly what the accumulator holds, ordered by
> count descending, ties broken by label ascending. The count is over what this run
> read and nothing else. **The first chunk of a run is supplied its own chunk's
> labels**, which is the empty set exactly when that chunk carries none.

> **Normative.** The accumulation reads at most `MAX_TOPICS_PER_RECORD` labels of any
> one record. §1 bounds every record this system installs to that many; where a record
> decoded from storage carries more — which only a bound a later ADR raised, or a
> record imported from a deployment holding a higher one, can produce — the first
> `MAX_TOPICS_PER_RECORD` labels in the tuple's own order are read and the rest are
> not.

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

**Including the chunk being prompted is what makes the clause implementable, and it is
also the stronger position.** `ConsolidationStage.run` obtains a chunk from
`walk_records` and hands it to `_consolidate`, which composes the prompt — so by the
time a prompt exists, that chunk's records have been read. A rule supplying "the labels
read so far" while also requiring the first prompt to carry none is two rules an
implementation cannot both obey, and the choice between them is not a wash. Taking the
labels of the records the prompt itself carries makes the supplied set a *projection of
that prompt's own content*: not merely the same class of data from the same records for
the same recipient, but the same data, restated as labels. ADR-0004 §7's test is then
met by construction rather than by argument. It also deletes the wart the other reading
needs — a first chunk supplied nothing, which is the chunk most in need of a vocabulary
in the one configuration where it is the only chunk.

**And the work it adds has a bound the configuration can compute**, which is what
ADR-0111 §4 asks of an operation inside a chunk. §1 states the arithmetic; the two
terms are one lookup per label the chunk offers — bounded by `scheduler_chunk_size ×
MAX_TOPICS_PER_RECORD`, because §1 bounds an installed record and the clause above
bounds the *read* of any record whatever the store holds — and one ordering of at most
`DEFAULT_PAGE_SIZE` entries, because the clause above bounds the accumulator and not
merely its output. Neither term grows with the run: the hundredth chunk of a run costs
what the first did. Nothing in it calls a provider, waits on I/O, or scales with
anything outside the chunk. That is the "dictionary update per record" the Consequences
claim, now true of every admissible input rather than of the expected one — and §12
pins the two inputs that would otherwise have broken it.

**What the accumulator's cap costs is named rather than hidden.** A run that reads
more than `DEFAULT_PAGE_SIZE` distinct labels stops learning new ones part-way through,
so a label first minted late in a long run is not supplied to that run's later chunks.
That is a loss of convergence at the margin and nothing more: §5's supply is a hint and
never an authority, a producer may always mint the label it needs, and the labels the
accumulator does hold are still the ones the run met first and most often. The
alternative — evicting a held label to make room — buys a marginally better hint by
making the supplied set depend on an eviction order this ADR would then have to defend,
and the first thing it would evict is the vocabulary the run has been converging on.
§15 names the condition that would reopen it.

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

**What it buys, and what it does not — stated as narrowly as a forward-only walk
allows.** Within a run, every prompt is supplied the labels of every record the run has
prompted with, its own chunk included, so a run converges on itself rather than minting
a synonym per chunk.

**Across runs it buys strictly less, and the limit is the walk's own shape.**
`MemoryStore.walk_records` reads "beginning strictly after the position recorded for
`walk`", and "a record whose eligibility changes *below* the cursor is not revisited" —
a high-water mark, never a re-read. So a later run is **not** steered by what an earlier
run *read*; it is steered only by what an earlier run *wrote*, because a committed
consolidation is a new record above the cursor that a later run's walk reaches in the
ordinary way. That is a real channel and a slow one, and it is the whole of the
cross-run effect. Nothing carries a vocabulary from one run to the next, by §5's third
clause, and nothing is meant to.

**The one-chunk run is the case that shows the difference, and it is a permitted
configuration.** `scheduler_run_budget` admits any finite, strictly positive duration,
and the budget is checked only at a chunk boundary, so a deployment whose single model
call spends the budget processes exactly one chunk per run. Under the earlier reading of
this section — a first chunk supplied nothing — such a deployment would send an empty
vocabulary in *every* prompt it ever composed, and this section's claim would be false
for it rather than merely weak. Under the clause above it is supplied its own chunk's
labels, which is the same supply every other run's first chunk gets; what it loses,
honestly, is the within-run accumulation, because it has one chunk to accumulate over.
§12 pins that configuration.

What this does **not** buy is a store-wide vocabulary at any prompt, and it buys the
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
> §1's canonical order. **Where the target conforms to §1's bound** — which is every
> record this deployment installs — no fold, record merge, reinforcement or
> consolidation drops a label the target carried, and no implementation writes one
> side's tuple over the other's. The one target that does not conform is ruled two
> clauses below, and it is a target this deployment cannot have written.

> **Normative.** **The retained subset, and it is total over every install.** Where
> an install would carry more than `MAX_TOPICS_PER_RECORD` labels, the record installed
> carries the **first `MAX_TOPICS_PER_RECORD` labels of an admission order**, and the
> admission order is:
>
> - **for a fold** — the target's own labels in §1's canonical order, then the labels
>   of the incoming record that the target does not already carry, in §1's canonical
>   order;
> - **for every other install** — an `ACCEPT`, the surviving record of a `SUPERSEDE`,
>   an owner act, or any other write that stores a proposal's content at an id — the
>   record's own labels in §1's canonical order.
>
> That is a total function on every install: fold or not, and whatever the target
> carried. Nothing is counted and no other field moves. Admission order decides *which*
> labels survive; §1's canonical order decides how the tuple is **stored**, and the
> stored tuple is strictly increasing whatever order they were admitted in.

> **Normative.** **A target that itself exceeds the bound converges downward.** No
> record this deployment installs carries more than the bound, so a fold whose target
> does is a target that arrived by import, or under a constant a later ADR raised. The
> clause above brings it under the bound on its next install, keeping the first
> `MAX_TOPICS_PER_RECORD` of its own labels ahead of any incoming one — so the
> guarantee that a fold displaces nothing the target carried holds for **every record
> this deployment installed**, and the one case it does not cover is the one it cannot
> have produced.

> **Normative.** A fold of two records both written under this decision cannot reach
> the bound: `MAX_TOPICS_PER_PROPOSAL` is 4, so an unfolded record carries at most 4
> labels and their union at most 8. Overflow requires a target that has already
> accumulated through repeated folds, which is the case §1's constant is sized for, or
> a record from outside this deployment's bound.

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

**The admission order is what keeps that ratchet whole under §1's bound, and it is
the honest order for a second reason.** The failure the union exists to stop is a
record quietly leaving the reach of an act it was already inside; keeping the target's
labels first makes that failure *unreachable by construction* for every record this
deployment installed, because a conforming target's labels all fit ahead of any
incoming one. What the bound
declines is always a label of the *incoming* record — a proposal about the target, made
by a producer that has just read a batch, which no act had previously reached and which
nothing downstream has yet relied on. That is the asymmetry: the target's labels have
already been ruled onto a live record, by an earlier install, an earlier fold or the
owner's own act; the incoming record's are a suggestion of the same standing as any
other topics entry, and §4 already rules that such an entry may be ignored in whole
without anything being counted.

**Code-point order is the only order available among the incoming labels, and that is
a fact about this field rather than a preference.** ADR-0086 §3 selects "the most
recently accumulated" because it could first ratify `Provenance.evidence`'s order as
accumulation order, observing that "§3's rule reads position as age and a rule that
reads a property nobody guaranteed is not a rule". §1 fixes this tuple's order by code
point precisely so that order carries *no* meaning, so position here is not age and
cannot be read as any other property either. Applying ADR-0086 §3's own method — ask
which criteria the data actually supports — gives a different answer for a differently
ordered tuple, and the criterion left standing is the one §1's storage order already
fixes: deterministic, implementation-independent, and identical on every store. It is
not a *good* order among peers, and it does not need to be: by the paragraph above,
every label it ranks is one the surviving record was never previously filed under.

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

> **Normative.** A relabel is an *install* and §1's bound applies to it. A relabel
> naming more than `MAX_TOPICS_PER_RECORD` labels is **refused, and the owner is told
> what the bound is** — not silently truncated to it. The owner is present, so there is
> someone to tell; that is the whole of the difference from §8's fold, which has no
> addressee and therefore elides. Refusing here is §3's rule about values that are
> "nearly right" applied to a set: a relabel that quietly kept twelve of the sixteen
> words the owner typed is harder to notice than one that did not happen.

> **Normative.** A **merge** cannot exceed the bound and needs no rule of its own. It
> replaces label A with label B on each record it reaches, so a record's label count
> either stays the same or — where the record already carried B — falls by one.

> **Normative.** The owner may **merge** two labels: every **live** record the act
> reaches that carries label A carries label B instead, and none of the records it
> reached carries A afterwards. The merge is all-or-nothing over those records — it
> commits for every one of them or for none — and it destroys nothing: a record whose
> only label was A carries B, never the empty tuple, and no record is deleted, retired
> or superseded by a merge.

> **Normative.** **"The records it reaches" is the set the act read, and this clause
> promises nothing about a record written after that.** A merge is an edit of the store
> at a moment and not a lock on a label: a producer that installs an A-labelled record
> while the act is in flight, or a second after it commits, has installed a record the
> merge did not reach — the case the last clause of this section already rules on. The
> guarantee is stated over the read set rather than over "every live record" because
> the wider phrasing would promise, of a store with another writer in it, an outcome no
> read-then-`write_atomic` sequence over today's `MemoryStore` surface can deliver, and
> this ADR adds no Protocol member that could. What a surface wanting the stronger
> guarantee would owe — a predicate write, a conditional revision or a serialised act,
> and the concurrency tests for it — is §15's, and belongs to the lane that builds the
> surface, because the remedy's shape depends on the act's.

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
> because the labels it carries are the labels of the records the run has prompted with
> and nothing else. What
> steers the next proposal is the **merge act above**: after it, the abandoned label is
> on none of the records the act reached, so a later run reading those records reads
> the corrected label and is supplied that instead. A record carrying the abandoned
> label that the act did **not** reach — one installed after its read, or one a
> producer mints afterwards — is read like any other, so a later prompt may still be
> supplied the abandoned label until the owner acts again. That is the same fact the
> clause below states from the other side, and it is why the merge is a correction of
> what the store holds rather than a guarantee about what it will hold. A run already
> under way keeps the vocabulary it has accumulated (§5); the correction reaches the
> next one.

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

> **Normative.** This ADR adds one field to one `core` type and four names to
> `core/types.py` (`TopicLabel`, `MAX_TOPIC_LABEL_LENGTH`, `MAX_TOPICS_PER_PROPOSAL`,
> `MAX_TOPICS_PER_RECORD`), and changes nothing else in `core`. The bound of §1 is
> applied at the `MemoryWriter` seam, which is `memory/ingest.py` and not a `core`
> file. **`core/protocols.py` is untouched**: no new
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
8. **The chunk being prompted is in its own vocabulary.** A consolidation run whose
   first chunk carries records labelled `("health",)` sends `["health"]` in **that**
   chunk's prompt, and a second chunk carrying `("sleep",)` is prompted with both. The
   first prompt is the assertion that separates this from the rejected reading: an
   implementation supplying only the chunks it has already finished sends nothing there
   and does not pass.
9. **The vocabulary is ordered, and the *accumulator* is capped rather than only its
   output.** With three labels across the records a run has read, they are supplied
   commonest first, ties broken by label ascending. A run that meets more than
   `DEFAULT_PAGE_SIZE` distinct labels holds exactly the first `DEFAULT_PAGE_SIZE` it
   met, in the order the prompted records presented them, and admits none afterwards:
   a label first seen in a later chunk of that run reaches no prompt, while a further
   occurrence of a label it does hold still increments that label's count. The
   assertion that separates this from a cap on the output alone is that the state
   selected *from* never exceeds `DEFAULT_PAGE_SIZE` entries, however many chunks the
   run has done.
10. **The vocabulary counts only what this run read.** Two consecutive runs over
    disjoint chunks supply disjoint vocabularies: the second run's first prompt carries
    its own chunk's labels and carries no label that appeared only among the records
    the first run read.
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
23. **A one-chunk run is supplied a vocabulary.** A run whose budget is spent after a
    single chunk sends that chunk's own labels in its only prompt, and does so on every
    such run — the configuration under which the rejected reading of §5 would have sent
    an empty vocabulary in every prompt the deployment ever composed.
24. **A record carrying more labels than the bound does not unbound the chunk.** A
    chunk containing one record whose decoded `topics` carries
    `MAX_TOPICS_PER_RECORD + 1` labels contributes exactly `MAX_TOPICS_PER_RECORD` of
    them, taken from the head of that tuple's own order, and the run completes and
    advances its cursor.
25. **The bound is on the install and not on the type.** A `MemoryBase` constructed
    with `MAX_TOPICS_PER_RECORD + 1` labels is admissible, and a record serialised with
    that many decodes without raising — the direction a `max_length` would have broken.
    Installing a proposal carrying them — a non-fold install, so §8's second admission
    arm — stores exactly the first `MAX_TOPICS_PER_RECORD` of them in canonical order; a
    write that only **retires** such a record stores it back carrying all of them.
26. **The fold's overflow keeps the target's labels and admits the incoming's in code
    point order.** A target already at the bound, reinforced by an incoming record
    carrying a label it does not have, survives carrying exactly the labels it had —
    none displaced. A target one label short of the bound, reinforced by an incoming
    record carrying two labels it does not have, admits the code-point-lesser of the two
    and not the other. In both cases the survivor's stored tuple is strictly increasing,
    so the admission order is not the storage order.
27. **An overflow is not counted anywhere.** The survivor of the fold above carries no
    field recording what was not admitted, no `core` type gains one, and every other
    field of the survivor is what the same fold produces under a bound it does not
    reach.
28. **A relabel over the bound is refused rather than truncated.** An owner relabel
    naming `MAX_TOPICS_PER_RECORD + 1` labels leaves the record's topics exactly as they
    were and reports the bound; one naming exactly `MAX_TOPICS_PER_RECORD` is admitted.
29. **A fold whose target already exceeds the bound converges downward rather than
    raising.** A target carrying `MAX_TOPICS_PER_RECORD + 1` labels — reachable only by
    import or under a raised constant — reinforced by an incoming record carrying none,
    installs exactly the first `MAX_TOPICS_PER_RECORD` of its own labels in canonical
    order. Reinforced by an incoming record carrying a label it lacks, it installs that
    same set and admits the incoming label nowhere. Neither case raises, and a write
    that only retires such a target leaves all of its labels in place.
30. **A merge promises only over the records it reached.** A record installed carrying
    label A after the merge has read its set still carries A when the merge commits, and
    the merge reports the set it reached rather than a claim about the store.
31. **Consolidation's own bad topics entry is ignored, asserted on
    `ConsolidationReport`.** §4's rule binds both model-backed producers, and
    consolidation has its own counters, so the assertion is made twice rather than
    once. A consolidation response whose topics entry is absent, null, not a list,
    carries a non-canonical string, or names more than `MAX_TOPICS_PER_PROPOSAL`
    labels yields a record routed to the write stage with `topics=()`, with
    `proposed` incremented and **`discarded_unusable` and `discarded_over_limit`
    unchanged**. The failure this pins is the plausible implementation: a bad label
    reaching `MemoryBase` construction raises a `ValidationError`, the parser treats
    it as unusable output, and the whole belief is discarded and counted — which
    trades a belief for a filing word, exactly as §4 forbids, on the producer whose
    counters tests 6 and 7 do not reach.

### 13. What the implementing lane owes

The implementation is one lane, briefed after this ADR merges (ADR-0015 §5, golden
rule 5). It owes:

1. **The four names and the field** in `core/types.py`, documented in place with
   what a value means and what an empty tuple means, and the canonical fakes and
   record builders in `ai_assistant.testing` extended to carry them. `topics` carries
   **no** `max_length`: §1's bound is a writer obligation and the type stays
   permissive.
2. **The `MemoryStore` conformance suite** pinning the field's round-trip, so every
   implementation persists and returns it rather than silently dropping it. **No
   Protocol changes and no new Protocol is added, so no triad is owed**
   (`CONTRIBUTING.md` → "Adding a Protocol"); `core/protocols.py` is not edited.
3. **The producer half**: the topics entry in `ModelBackedObserver`'s envelope and in
   `ConsolidationStage`'s, ignored rather than counted where it cannot be used (§4),
   with the canonical form applied by the producer before construction.
4. **The run-scoped accumulation** in `ConsolidationStage` alone: an in-memory count
   over the labels of the records each prompt carries, updated as that prompt is
   composed and before it is sent so the chunk is in its own vocabulary, reading at most
   `MAX_TOPICS_PER_RECORD` labels of any one record, **holding at most
   `DEFAULT_PAGE_SIZE` distinct labels and never evicting one**, ordered as §5 states,
   reset per run, and threaded into the prompt the stage already builds. The cap is on
   the accumulator, not on a larger structure it is selected from. No store read, no
   migration and no durable state.
5. **The fold's bounded union** in `memory/ingest.py`, written on both arms beside
   the two computations that already take a disjunction there, with §8's admission
   order — the target's labels whole, then the incoming's in code-point order to the
   bound — and the result stored in §1's canonical order.
6. **§1's bound at the `MemoryWriter` seam**, applied to every *install* and not to a
   retire, in the same place and the same sense ADR-0086 §2 puts
   `MAX_EVIDENCE_CITATIONS`, and applied through §8's retained subset on **both** its
   arms — the fold's and every other install's — so an over-bound target and an
   over-bound direct proposal each have a defined outcome. It is the one place the bound
   is enforced; nothing is added to `MemoryBase`, to a store or to a producer to enforce
   it a second time.
7. **The exclusion** of `topics` from `MemoryUpdateProposal`'s fingerprint
   projection.
8. **The thirty-one tests of §12**, less those of the owner's acts (20-22, 28 and 30),
   which belong to the surface lane the clause below defers them to.

> **Normative.** The owner's acts of §9 are **not** in the implementing lane above.
> They need a surface, the surface is a promoted-surface change, and it is therefore
> its own ADR and its own lane (golden rule 5, ADR-0015 §5). A lane implementing the
> eight items above and adding an owner-facing relabel or merge operation has exceeded
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
- **A recorded count of what an overflow did not carry.** §1 takes ADR-0086 §§1–3
  and declines its §4: an overflow records no number, because §7 already rules that a
  topic set is never a claim to completeness, and §4 already rules that a topics entry
  the system cannot use is ignored with no counter moving and no `core` type gaining a
  member. **Fires** on either of two things this decision cannot see today — a measured
  store in which folds reach `MAX_TOPICS_PER_RECORD` often enough that owners are losing
  proposed labels they wanted, or the first surface that renders a record's topics
  beside a claim about their completeness, which would put this field under the
  ADR-0073 §4 obligation that ADR-0086 §4 exists to answer and which no surface makes
  now. A lane taking it on owes the field, its recurrence over every install, and the
  §7 disclosure it interacts with — not a number appended to the record.
- **The concurrency contract of the owner's merge.** §9 states its guarantee over the
  records the act read, because a stronger one is not deliverable by a read followed by
  a `write_atomic` while another writer may install an A-labelled record in between, and
  this ADR adds no Protocol member. **Fires** with §9's surface ADR, which owes the
  choice — a predicate write, a conditional revision, or serialising the act against the
  writers that could race it — and the tests that hold it. It is that lane's because the
  cheapest sound answer depends on the surface's own shape, and none of the three can be
  chosen from here.
- **Evicting from a full vocabulary accumulator.** §5 caps it at `DEFAULT_PAGE_SIZE`
  distinct labels and never evicts, so a run that meets more than that many stops
  learning part-way. **Fires** with a measured run in which that demonstrably costs
  convergence — and it owes an eviction order it can defend, which is what this
  decision declines to invent for a hint.
- **Raising `MAX_TOPICS_PER_RECORD`.** §1 fixes it at 16 and gives the arithmetic the
  figure comes from. **Fires** with a measurement showing records legitimately about
  more than sixteen things, and it owes the §11 version test on the day it is taken:
  §1 keeps the bound off the type precisely so that a raise is a change to what this
  deployment *writes* and not to what an older peer can *read*, and a lane that raised
  the constant and added a `max_length` in the same change would take that back.
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

**Nothing here is withheld for want of room to write it.** A header-only record under
ADR-0082 §1 — a `Status` line and one dated note, no Decision text rewritten — is
cheap, and the corpus makes such records in the superseding ADR's own change
(ADR-0204's, for two earlier ADRs at once). So the absence of one below is a finding
about this decision's reach, not an economy: where a record were owed, it would be
made here.

The eight nearest candidates are worked through, because each is close enough that a
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
  reader acting differently, which is ADR-0070 §1's line, and it was **removed rather
  than recorded**. Removing it is the honest order of the two: ADR-0077 §3's ground is
  ADR-0004 §7 minimisation, and a decision that widened an observation payload would
  owe that trade an argument and a measurement, not a Status line appended to carry a
  change made for a different decision's convenience. §15 names the condition that
  fires an ADR which may take it, and what such an ADR would then owe ADR-0077 under
  ADR-0070 §1 and ADR-0082 §1.
- **ADR-0074 §4's "capture judges nothing else".** That section enumerates what
  capture declines to fill — "`importance` stays at its default … `participants` stays
  empty … `validity` stays fully open" — and states the principle those three are
  instances of. §6 gives a fourth instance rather than a fourth rule: capture writes no
  topics, for the reason §4 already gives, on a field §4 could not have named because it
  did not exist. A reader holding only ADR-0074 stamps an episode exactly as they did
  and declines exactly what they declined. That is ADR-0070's amend-vs-supersede test
  answered *below* amendment: this is an ADR applying an earlier one's stated principle
  to new ground, which changes neither its text nor its reach, so ADR-0074's `Status`
  line is not touched by this change.
- **ADR-0086 §§1-4's evidence bound.** §1 above applies that ADR's shape to a second
  field — a fixed `core` constant (§1), enforcement at the `MemoryWriter` seam on
  installs and not on the type (§2), an overflow rule for the fold (§3) — and declines
  its §4. A reader holding only ADR-0086 bounds `Provenance.evidence` at 64, enforces
  it exactly where §2 puts it, retains the most recently accumulated of a union, and
  records `evidence_elided`, after this decision precisely as before. Every clause of
  that ADR is scoped to `evidence` by its own words — §1 states its bound "on the
  record type rather than on the field" and spends two paragraphs on why it does not
  even reach `Goal` — so a second field decided the same way widens nothing and
  narrows nothing there. Reusing a ratified ADR's reasoning is what a corpus is for,
  and §1 argues each of the three transfers, and the one refusal, on this field's own
  merits rather than citing ADR-0086 as authority over a field it does not name.
- **ADR-0111 §4's admissibility condition.** §5 puts an operation inside a
  consolidation chunk, and §1 and §5 give it a per-chunk cost computed from figures the
  configuration and this ADR already fix. That is the clause being **satisfied** — "a
  job whose chunk reaches an operation with no deadline is not a job that may be chunked
  under this ADR" — and §4's own instruction that this "must be checked rather than
  assumed" is discharged here rather than altered.

  **The reading under which a record *would* be owed is named, and answered from
  ADR-0111's own file, because ADR-0082 §1 asks the sentence to be named either way.**
  If §4's "bounded by a deadline" reached every synchronous in-memory operation, then
  admitting one on a cardinality bound alone would read that clause more narrowly than
  it holds, and a record would be owed. **The sentence that settles it is ADR-0111's own
  account of where the clause came from**: its ratification note records round 1's
  finding "that §4's budget bounds nothing **if a chunk can block indefinitely**", and
  the clause as the repair — "making a per-operation deadline a precondition of being
  chunked at all". The hazard the clause was written against is an operation that can
  block indefinitely; a loop bounded by two constants of the configuration is not one.
  §1 above adds two further readings from §4's own text — that ADR-0111 supplies no
  cancellation mechanism with which a deadline on a non-yielding operation could be
  enforced, and that §4's chunk arithmetic carries no term for local work — and notes
  that the wide reading would forbid consolidation and the retention purge, the two jobs
  §4 was written for.

  So a reader holding only ADR-0111 admits exactly the jobs they admitted before this
  decision, on exactly the test they applied, and no clause of it is read more widely or
  more narrowly. That is ADR-0070 §1's line and this falls below it — the same place the
  ADR-0074 §4 case above falls: an ADR applying an earlier one's stated condition to new
  ground. **And a record made anyway would be a mis-declaration**, which ADR-0082 §1
  names as its own failure: "a later ADR that calls its change an amendment of ADR-N
  without a clause of ADR-N failing §1's test has mis-declared it, and the record is
  wrong however the declaration reads." A `Status` note asserting that this decision
  narrowed §4 would tell every later reader that §4 once reached bounded local work,
  which is the thing ADR-0111's own header says it never did.
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
prompts with — bounded, by §1's constant, to at most `MAX_TOPICS_PER_RECORD` labels of
that record — a slightly longer prompt per consolidation chunk, and a few more tokens in
each producer's response. The work one chunk adds is at most
`scheduler_chunk_size × MAX_TOPICS_PER_RECORD` lookups plus an ordering of at most
`DEFAULT_PAGE_SIZE` entries, and neither term grows with the run — which is the bound
ADR-0111 §4 asks a chunked job's operations to have. No store read is added and no
schema changes. The observation prompt does not grow at all. No new call, no new provider dependency, no
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

**Leaving the tuple unbounded and stating the residue.** Four rounds of review
converged on this axis, each reaching the same gap from a different direction, so the
rejected shape is recorded rather than quietly replaced. The proposal
was: no cardinality bound anywhere, a clause in §5 observing that the accumulation is
bounded by the labels of records the chunk had already decoded, and §15 naming the
condition that would fire a bound later. It fails on the one thing it was meant to
answer. The observation is true and does not help: ADR-0111 §4 asks whether every
operation *inside a chunk* is bounded, and "the walk had already decoded this, so the
chunk was already unbounded" concedes the point rather than rebutting it — a job whose
chunk is unbounded before this decision is a job §4 does not admit, and adding an
operation over the same unbounded data leaves it there. The comparison to
`Provenance.evidence` fails in the same place and for a better reason: that field is
bounded, at 64, by ADR-0086 §1, and its type is permissive only so that records written
*before* the bound stay readable. Topics have no such population — the field is new —
so the only thing a permissive type buys here is the forward compatibility §1 keeps it
for, and nothing at all excuses the absence of a bound at the writer.

**A `max_length` on `MemoryBase.topics`.** Rejected in §1. It is available — ADR-0086
§2's test is answered *no* for a field no store carries — and it is still the wrong
seam: it would refuse on decode the records a raise of the constant will produce, and it
would turn §8's fold into a raised write rather than a bounded record.

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
refuses, so taking it would have needed a record on ADR-0077 under ADR-0070 §1 and
ADR-0082 §1 — and, before that record, the argument the record would stand on: why the
minimisation ADR-0077 §3 protects is worth trading for a filing hint, measured rather
than asserted. This decision has no such measurement, so it declines the payload rather
than buying it on credit. It is deferred in §15 with the condition that fires it. What is *not* an alternative is taking the payload
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
