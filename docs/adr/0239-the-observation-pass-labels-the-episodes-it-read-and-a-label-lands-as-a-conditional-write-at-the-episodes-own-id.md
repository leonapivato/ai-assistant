# 239. The observation pass labels the episodes it read, and a label lands as a conditional write at the episode's own id

- Status: Proposed
- Date: 2026-09-05
- **One record is owed on an earlier ADR and this change writes it.** §14 names
  the clauses of ADR-0213 this decision replaces — §4's set-at-write clause, §6's
  producer enumeration and its no-labelling-another-producer's-record clause, and
  §8's revised-only-by-two-routes clause, **each for `EpisodicMemory` records
  only** — quotes each, and applies ADR-0070 §1's test to it. ADR-0213's `Status`
  line carries no leading token, so under ADR-0082 §2 the record is written on that
  line **and** in an appended dated note. No other ADR's text is touched by this
  change, and nothing here supersedes anything else.

## Context

### Where this comes from

`track:planning`'s milestone 30 on #1908 — *the planner chooses how to read* —
sharpened by the owner on 2026-09-05. Its point (b) is an audit of the metadata the
milestone was about to rely on, and it comes back short:

> **Audit the metadata before relying on it.** Verified at main 2026-09-05:
> `MemoryStore.search` takes `query/limit/kinds/bands` only; records carry
> `occurred_at`, `participants`, `about_person`, `topics` — but the episode recorder
> (`orchestration/conversations.py`) sets **`occurred_at` only**, leaves
> `participants` empty by design, and sets no `topics`; the observer labels *beliefs*
> with topics/about_person, not episodes. So the who/what axes are **unpopulated on
> every captured episode** … M30 owes an episode-labelling producer (or the exit's
> "which conversation involved Alex" cannot be answered by structure).

This ADR is that producer. It decides who labels an episode, at what moment, with
what, what a label means, how it lands on a frozen record, and what a consumer may
never do with it. It decides **no read** — not a filter, not an argument law, not a
surface — and #1908 is explicit that each envelope kind "is inert until
`track:memory` has ratified the store read it maps to".

### The gap, verified in the tree rather than quoted from the issue

At `main` b732dc7e:

- `EpisodicMemory` (`core/types.py`) declares `occurred_at`, `participants:
  tuple[EncodableText, ...] = Field(default=())`, `outcome`, `disposition`,
  `capture` and `importance`, and inherits `topics` and `about_person` from
  `MemoryBase`. **Every field this decision needs already exists**; nothing about the
  record's shape is in question.
- `_episode` in `orchestration/conversations.py` stamps `occurred_at` and says why it
  stamps nothing else: "``participants`` stays empty, because the two parties to a
  turn are structural rather than informative and constants there would occupy, with
  noise, the field an observer means to fill with the people an episode is *about*."
  It writes no `topics` and no `about_person`.
- `ModelBackedObserver` (`learning/observer.py`) reads a batch of episodes and
  proposes beliefs. Under ADR-0213 §6 it labels **each `MemoryUpdateProposal` it
  returns** — a belief — and nothing else.
- Consequently `participants` and `topics` are the empty tuple on every episode any
  deployment of this system holds, and `about_person` is `None` on every one.

The recorder's own sentence is the finding: it names an observer as the intended
filler of `participants` and no observer fills it. That is not an oversight in
ADR-0074 — it is a job ADR-0213 §15 named, deferred, and gave a firing condition
for. The condition has fired.

### What the corpus already decides, and this ADR may not rebuild it

- **A class is read off a recorded value, never off the words at read time.**
  ADR-0199 §2: "No implementation, lane or later ADR may decide a class by reading
  `MemoryBase.content`, a facet's rendered text, a composed reply, or any other span
  of the content itself — not by keyword, not by pattern, not by a classifier, and
  not by asking a model what a passage is about." That prohibition binds the
  **consumer at the moment of the act**, and this ADR leaves it whole: nothing
  downstream of a labelled episode reads anything but a stored field.
- **ADR-0130 §11's three grounds are the test any model-in-the-loop decision has to
  pass.** "An interruption a model chose cannot be explained to the user who received
  it, cannot be tested deterministically, and cannot run when no provider is reachable
  — which is exactly when a resident process is still noticing." ADR-0213 §4 adopted
  those three as its own test and answered them one by one; §1 below does the same.
- **A topic's form, its bounds and its meaning are settled.** ADR-0213 §3 fixes the
  canonical form and rules that equality of the stored characters is the only relation
  two labels have; §4 fixes `MAX_TOPIC_LABEL_LENGTH` at 64 and
  `MAX_TOPICS_PER_PROPOSAL` at 4 and rules a bad entry **ignored, never repaired**;
  §7 rules an empty tuple "no topic was recorded"; §14 rules a topic "not a retrieval
  axis", "not a tier and not a sensitivity", "not a subject" and "not an identifier".
  Every one of those binds after this decision, unchanged, and this ADR restates none
  of them as its own.
- **A person label resolves to nothing, and the corpus says so of this very field.**
  ADR-0100 §6, arguing why `about_person` is a bare label rather than a handle: "A
  field that resolves to nothing takes none of those decisions, and the corpus already
  runs one: `EpisodicMemory.participants` has been free-text-resolving-to-nothing
  since ADR-0005 §1."
- **A producer may not infer a *subject*.** ADR-0100 §4: a producer fills
  `about_person` "only from a subject it actually received — an explicit user act, or
  a structured field of a source that names whom an entry is about — and never by
  inferring a person from content. The field widens no producer's warrant, and its
  existence may not be cited as though it did." §7 below is the firewall that keeps
  this clause exactly as strong as it is today.
- **The subject-scoped acts state their own honest limit.** ADR-0101 §6: "A record
  whose subject was never stated is never reached, whatever its content says, and this
  ADR authorises no component to infer a subject for it."
- **A stored row may be rewritten; the objects are what is frozen.** ADR-0213 §8:
  "ADR-0068's freeze is a property of the *objects*, not a promise that a row is never
  rewritten: `_merge` already returns `incoming.model_copy(update={"id": target.id,
  …})`, so a record at a stable id whose fields moved is the store's existing shape."
- **A conditional write exists and is the ratified instrument for exactly this
  shape.** ADR-0219 §1 puts a store-authored `revision` on `MemoryBase` and §2 puts
  `IF_UNCHANGED` on `MemoryWriteMode` with `expected_revision` on `MemoryWrite`.
  ADR-0217 §7's `guard`/`unguard` already write through it — an act that reads a
  record, changes one field of it, and writes it back at its own id.
- **The observation walk never goes back.** ADR-0212 §1's non-selection guarantee and
  ADR-0220 §1's anti-extension rule together make the walk a high-water mark: "no
  driver's pacing, no selector, no setting and no later clause may cause a page to
  reach below the watermark its own pass read", and "A lane that wants re-reading asks
  for a new operation, never a lower watermark." §8's backlog answer is a consequence
  of that, not a preference.
- **Capture judges nothing, and is exempt from the gate because it judges nothing.**
  ADR-0074 §4 and ADR-0075 §2 turn on the same sentence: the exemption "covers **only**
  the capture path ADR-0074 §3 ratifies: a deterministic, non-inferring recording of a
  turn the engine has already answered". A capture that labelled would not be that
  path, and its exemption would go with it.

### The tree, read rather than assumed — who can label at all

ADR-0213's own inventory still holds and this decision turns on it. Of the five
producers that write records, exactly two hold a `ModelProvider`:
`ModelBackedObserver` and `ConsolidationStage`. Capture holds none, the ingestion
path holds none, and `RuleBasedFeedbackProcessor` is rule-based by ADR-0005 §3.

Two further facts decide the seam, and both were read in the tree rather than
assumed:

- **`Observer` holds no store and writes nothing.** `core/protocols.py`: "It holds
  no store handle … :meth:`observe` receives the episodes; an implementation cannot
  fetch more" and "It writes nothing, and cannot rule on its own output." So an
  observer cannot perform the labelling write, and this ADR does not ask it to.
- **`ObservationStage` (`orchestration/observation.py`) holds both halves.** It is
  constructed with `observer`, `conversations`, `memory: MemoryStore`, `writes` and
  `batch_size`; it "Selects a batch of episodes, observes it, and ingests what comes
  back". It therefore holds the stored episodes it selected — with the revisions the
  store returned on that read (ADR-0219 §1) — and a `MemoryStore` to write them back
  through. The labelling write needs nothing this stage does not already have.

`ObservationOutcome` appears in `core/types.py`, `core/protocols.py`,
`learning/observer.py` and `testing/observation.py` and **nowhere else**: not in
`wire/`, not in `service/`, not in `interfaces/`, not in `app/`. It is an in-process
seam value, which is what makes §9's version answer short.

### An honest statement of what this ADR is not allowed to settle

It cannot decide a **read**: no `MemoryStore` filter, no argument law for one, and
no rule about what a filtered read returns. That is a Protocol change and therefore
its own ratified, separately-merged ADR (golden rule 5, ADR-0015 §5), and #1908
scopes it to `track:memory`. It cannot decide the **surface** on which the owner
relabels or merges — ADR-0213 §9 already defers that and this ADR inherits the
deferral without narrowing it. It cannot decide a **matching rule wider than
equality**, which ADR-0213 §3 reserves. It cannot decide **whether an episode's
`occurred_at` is the exchange's instant or the event's**, which #1908's point (b)
also names and which is a different field with a different producer. And it does not
label anything but an episode: every clause below is scoped to `EpisodicMemory`, and
ADR-0213 governs every other record exactly as it does today.

## Decision

### 1. The observation pass labels the episodes it read, inside the envelope it already sends

> **Normative.** `ModelBackedObserver` proposes, for each episode of the batch it was
> handed, the `topics` and the `participants` that episode carries. It does so
> **inside the model envelope it already sends**: one optional key of the response it
> already parses, on the provider call it already makes. This ADR authorises no second
> model call, no second round trip, no second provider dependency and no second walk
> anywhere in the system.

> **Normative.** No other producer labels an episode. Capture
> (`orchestration/conversations.py`) writes no `topics` and no `participants`, and is
> given no `ModelProvider`; `ConsolidationStage` labels the records it distils and no
> episode it read; `RuleBasedFeedbackProcessor` and every `Reader` label nothing, and
> ADR-0213 §6's clauses about each of them bind unchanged.

> **Normative.** A labelling is proposed for an episode of **the batch the caller
> handed the producer** and for no other. A labelling naming anything else — an
> episode id the producer was not handed, a record of another kind, a conversation, or
> a value that is not one of the caller's own labels for the batch — is **ignored**.
> The producer maps its own labels back to the ids it read, and no id reaches the model
> and none is accepted from it.

> **Normative.** A provider outage yields **no labels**, never a wrong one. It also
> yields no proposals, because a `ModelError` ends the pass rather than degrading it
> (ADR-0077 §3), and every episode of that batch stays exactly as capture wrote it.

**ADR-0130 §11's three grounds, answered one by one, because they are the test
ADR-0213 §4 set and this decision must pass the same one.**

- **Explainable.** What a later act reads is a label recorded on the record. "Why did
  this question reach that conversation?" is answered by showing the episode and the
  words written on it — a field read, not a re-derivation, and not a model's opinion
  reconstructed after the fact.
- **Deterministic at read.** Nothing about a read varies with a model, a prompt or a
  provider's availability. Two reads of one store give one answer, and a test fixes an
  outcome by writing a label rather than by pinning a model.
- **Reachable with no provider.** An unreachable provider leaves the episode
  unlabelled, which §6 rules is "no label was recorded" and which §8's disclosure
  obliges a consumer to say. It never leaves a wrong label, and it never leaves the
  system unable to answer at all: the record, its `content` and its `occurred_at` are
  all exactly as they were.

**Why the observer and not a producer of its own.** A labelling producer of its own
would read the same episodes, with the same model, over the same batch, in a second
prompt — and pay twice for one reading. ADR-0213 §4's second clause is a general
discipline and its ground does not weaken here: a second call is a second round trip,
a second failure surface, and a second transmission of the same Tier 1 material to
the same recipient, which is the wrong direction under ADR-0004 §7's minimisation
test. The observer is already reading these exact words, in a rendering it already
built under ADR-0098 §2's no-span-writes-syntax discipline, for the purpose of saying
what they were about. Asking it for one more sentence about the same batch is the
cheapest correct answer available, and the Alternatives record the one that was
weighed against it.

**Why not capture, in the terms of the clause that forbids it.** ADR-0074 §4 rules
"Capture judges nothing else … importance is a judgement, and salience is leg 7's
decision, not a number the recorder invents", and a label is the same kind of
judgement. The deeper reason is ADR-0075 §2: capture's exemption from the
proposal→policy gate "covers **only** … a deterministic, non-inferring recording of a
turn the engine has already answered". A capture that asked a model what a turn was
about would stop being non-inferring, would need a provider on the turn's hot path,
and would forfeit the exemption on the same sentence that grants it. This ADR
therefore leaves ADR-0213 §6's capture clause standing word for word, and the
recorder's docstring becomes true rather than aspirational: an observer now fills the
field it names.

### 2. The seam: one additive `core/types.py` member, and the write is the stage's

> **Normative.** `core/types.py` gains one frozen model, `EpisodeLabelling`, carrying
> `episode_id: EncodableText`, `topics: tuple[TopicLabel, ...]` and `participants:
> tuple[TopicLabel, ...]`, both defaulting to the empty tuple; and
> `ObservationOutcome` gains exactly one additive member, `labellings:
> tuple[EpisodeLabelling, ...]`, defaulting to the empty tuple. **`core/protocols.py`
> gains nothing and changes nothing**: `Observer.observe`'s signature is untouched, no
> `MemoryStore` member is added or widened, and no other Protocol is touched.

> **Normative.** No existing member of any `core` type changes its type, its default
> or its meaning. `EpisodicMemory.participants` keeps its `tuple[EncodableText, ...]`
> annotation and gains no validator: a record already stored, or imported from a
> deployment under a different rule, is **read rather than refused**.

> **Normative.** `ObservationOutcome`'s two counts are **untouched** and no member is
> added to count a labelling. `len(proposals) + discarded_unusable +
> discarded_over_limit` keeps exactly the meaning ADR-0077 §4 and ADR-0213 §4 give it:
> a labelling is not an entry of the proposal population, an ignored labelling is not a
> discard, and no counter moves for either.

> **Normative.** **The write is the caller's, never the producer's.** The component
> that selected the batch performs the labelling write, from the stored record it
> already holds. `Observer` holds no store and writes nothing, and this ADR does not
> change that.

> **Normative.** **The producer names labels, never a record.** The write is
> constructed by applying the labelling's two tuples to the **stored** episode the
> caller read — every other field carried across unchanged — and never by storing a
> record the producer supplied. No value a model emits can reach `content`,
> `occurred_at`, `outcome`, `disposition`, `capture`, `importance`, `about_person`,
> `provenance`, `placement`, `validity`, `expires_at` or the record's id.

**The last clause is the security property, and it is ADR-0047 §2's rule in a second
currency.** `learning/observer.py` already holds it for citations — "The prompt labels
each episode and the model cites labels; this module maps every label back to the id
of the episode it actually read … A model that can write an id can write one for an
episode it never saw." A labelling seam that carried a record rather than two tuples
would hand a model a way to rewrite an episode's text, its instant, or its band under
the cover of filing it. Carrying labels alone makes that unreachable by construction
rather than by review.

**Why a named value and not two parallel mappings.** `ObservationOutcome`'s own
docstring gives the rule: it "follows :class:`MemoryIngestResult`'s precedent that a
seam returning more than one fact returns a named value rather than a tuple". Two
`Mapping[str, tuple[...]]` members can disagree about which episodes were labelled;
one model per episode cannot.

**Why `TopicLabel` annotates both tuples.** The canonical form §4 fixes for a
participant label is *literally* ADR-0213 §3's, and minting a second annotated type
with an identical predicate would be two statements of one rule — the defect ADR-0086
§1 names when it declines a second enforcement point. The name is about the form, not
about the axis, and §7 below states in terms that sharing a form shares nothing else.

### 3. The write: a conditional revision at the episode's own id, of two fields and nothing else

> **Normative.** A labelling lands as a `write_atomic` element in
> `MemoryWriteMode.IF_UNCHANGED`, whose `expected_revision` is the revision carried by
> **the very `EpisodicMemory` the producer was handed** — the record the read that
> selected the batch returned (ADR-0219 §1, §2). **No implementation re-reads the
> episode between that selection and the write**, and no other revision is expected. It
> is a write at the episode's own id. It is never an `add`, never an `UPSERT`, never an
> `INSERT_IF_ABSENT`, and never a supersession.

> **Normative.** It changes `topics` and `participants` and **no other field**. No
> validity window is opened or closed, no `expires_at` moves, no `placement` changes,
> no id is minted and no record is retired, deleted or superseded by it.

> **Normative.** **A pass labels an episode that carries no label on either axis, and
> no other.** Where the episode the pass read carries a non-empty `topics` or a
> non-empty `participants`, the pass writes nothing for it and its labelling is
> discarded. No pass overwrites a label — its own, an earlier pass's, or the owner's.

> **Normative.** On `MemoryStoreStaleError` the labelling for that episode is
> **abandoned**: not retried, not re-read, not re-proposed and not written
> unconditionally. The pass continues with the rest of its labellings.

> **Normative.** **A labelling is written only where every episode of the batch the
> producer was handed carries the same placement reach and the same placement setter as
> the destination episode.** Where the batch is not uniform in both, **no labelling is
> written for any episode of that page**. No labelling write changes a placement,
> narrows one, widens one, or reads one for any other purpose.

> **Normative.** The labelling write is **not** part of the batch that installs the
> pass's proposals, and neither is a condition of the other. A refused or failed
> labelling write leaves every belief the pass installed exactly where the write path
> put it, and leaves the watermark exactly where the pass committed it.

> **Normative.** **The labelling write is attempted only after the pass's watermark
> advance has committed, and for the episodes of the page that advance covers.** Where
> the advance is not attempted, does not commit, or the pass fails before it, **no
> labelling is written at all** and every episode of that page stays exactly as it was.

> **Normative.** The labelling write is **never a condition of the watermark**.
> ADR-0212 §5's advance is computed, attempted and committed exactly as it is today: it
> is unchanged where a proposal fails to be ruled or a belief install raises
> (ADR-0212 §§5-6), and no clause here delays it, lowers it, adds a condition to it, or
> makes it depend on whether a labelling landed or could have landed.

> **Normative.** **A labelling write is not a write of a belief, and the
> proposal-to-policy path does not reach it.** It passes through no `MemoryPolicy`, is
> ruled by no `Disposition`, opens no deferred question and is counted in no
> `MemoryIngestResult`. Every belief the pass proposes goes through that path exactly as
> it does today, and no lane may cite this clause for any write that asserts something
> about the user.

> **Normative.** What stands in the gate's place is stated rather than assumed, and an
> implementation owes all six: the producer names labels and never a record (§2); the
> destination is a record the caller selected and read, never one the model named (§1);
> the form is refused at the seam and never repaired (§4, §5); the write is conditional,
> write-once, two fields wide and abandoned on a race (§3); the label carries no
> posture, no permission, no band and no disclosure consequence (§7); and the owner's
> relabel is final over it (ADR-0213 §9).

**Why the gate does not reach it, in ADR-0075's own currency.** ADR-0075 §1 replaced
ADR-0005's "every write goes through a reviewable proposal → policy path" with "**every
write of a belief** goes through that path", and §2 gives the test that decides which
side a write is on: "the exemption follows the record's *claim*, not the provenance of
its characters" — recording that something happened is an event, recording "that X is
true of the user" is an assertion. A labelling asserts nothing about the user. It adds
no claim to the store, contradicts nothing already in it, and says only how an existing
record is filed; ADR-0213 §14 rules that a topic is "not a tier and not a sensitivity",
carries "no posture, no permission, no band and no disclosure consequence", and §7 above
binds a participant label to the same. So the rule ADR-0075 §1 states does not reach
this write, and this write claims no exemption from it.

**And the gate has nothing to rule with.** `MemoryPolicy`'s five outcomes are
operations on a belief — accept it, reinforce it, supersede one, defer it to the owner,
reject it. A labelling offers none of them: there is no belief to accept, nothing to
reinforce, nothing for it to contradict, and nothing an owner could usefully be asked
about that ADR-0213 §9's relabel does not answer better and deterministically. Putting
it through the gate would mean inventing an operation for it, which is a
`core/protocols.py` change and a larger decision than this one; ADR-0213 §10 already
took the same view of the field from the other side when it excluded `topics` from the
proposal fingerprint, so the policy's own dedupe does not see a label today either.

**What that argument is not.** It is not a claim that a model's output about a person
needs no check — ADR-0075 §2 is right that "the observer is the paradigm case the gate
exists for", and every belief that producer proposes still goes through it, unchanged.
It is a claim about **which** of the observer's outputs is a belief. The clause above
therefore states the replacement discipline as six obligations rather than leaving it as
an absence, which is ADR-0075 §3's own shape: "The exemption is not 'no safeguards'; it
is a different set." §14 applies ADR-0070 §1's test to ADR-0005 and ADR-0075 and finds
no clause of either made false or over-wide.

**Why in place at the same id rather than a superseding record.** ADR-0213 §8 already
argued this for the owner's relabel and the argument is stronger for an episode: "a
relabel changes no belief, so retiring the record and minting a new id would close a
true belief's validity window, break every `evidence` citation that names it, and put
the belief where ADR-0073 §3 makes it 'unreachable by phrase and destroyable by id'".
An episode is the **terminal citation** — `orchestration/conversations.py` says so in
terms, "an episode is the terminal citation: the thing other records cite" — so every
belief the observer proposes from a batch cites the ids of that batch's episodes in
`Provenance.evidence`. Minting a new id for a labelled episode would break exactly the
citations the same pass just wrote. And an episode records that something happened;
superseding it to record what it was about would assert that the earlier account was
wrong, which is a claim about the world this write does not make.

**Why conditional, and why abandonment rather than a retry.** ADR-0219 §5's two
consumers retry once because their write is the point of the operation. A labelling is
not: nothing waits on it, and the only writes that can move an episode's row between
the pass's read and its write are the owner's own relabel act (ADR-0213 §9) and a
concurrent pass. **Both should win.** A retry computed against the older row would
overwrite the owner's correction with a model's guess, which is the one outcome
ADR-0213 §9 exists to make impossible — "the instrument is the relabel act above,
which is deterministic and final for that record". Abandoning is therefore not a
weaker answer than retrying; it is the correct one, and it makes ADR-0220 §1's
re-reading cases safe by construction rather than by a rule about them.

**Why write-once, stated as a rule and not left to the walk.** ADR-0212 §1's guarantee
means a pass does not ordinarily meet an episode twice, but ADR-0220 §1 names three
readings in which one turn is selected again — a trailing unresolved run, two
concurrent passes, and a page whose advance did not commit. Without the clause above,
the third of those would re-label an already-labelled episode with a second model
judgement over the same words, for no gain and at the cost of ADR-0213 §8's "set once".

**Why after the advance, and why an empty tuple alone would not have been enough.**
Emptiness is a proxy for "never labelled", and the owner can produce emptiness: ADR-0213
§9's relabel replaces the whole of a record's `topics` with a set the owner states, and
that set may be empty. Left on the emptiness test alone, this decision would admit a
sequence that undoes an owner's act — a pass labels an episode, its advance does not
commit, the owner clears those labels, and the next pass re-reads the page, sees two
empty tuples, reads the owner's current revision and writes model labels back over the
correction. That defeats ADR-0213 §9's guarantee that a relabel is "final for that
record until the owner acts again", and no `IF_UNCHANGED` can catch it because the
revision the second pass expects is the one the owner's own act left.

Ordering the write **after** the advance closes it without a byte of new state, because
it makes the premise unreachable. ADR-0220 §1 rules that where the stamp did commit the
page "is not re-read and does not need to be", and where it did not, the page "is
re-read whole by the next pass". So an episode a later pass re-reads is one whose
advance did not commit — and under the clause above, one no pass ever labelled. The
other two re-readings are safe on the two clauses already stated: an unresolved turn has
no episode to label, and two concurrent passes over one page are separated by
`IF_UNCHANGED` and by the write-once test, whichever of them writes first.

**The overlap race is why the expected revision is pinned to the selecting read, and
that is the load-bearing half.** ADR-0212 §5 permits two passes over one conversation to
select the same page and advance to different positions, so ordering the write after an
advance does not by itself stop this: pass A advances, labels an episode, the owner
clears those labels, and pass B — which had already selected that page — writes model
labels back over the correction, because by then the tuples are empty again and the
revision B holds is the owner's. **The clause above closes it because B's expectation is
not the owner's revision.** B's page can only contain that episode if B selected it
before A's advance, so the record B was handed carries the revision the row held *then*,
and A's own labelling write has moved it since. B's write is refused, its labelling is
abandoned, and the owner's empty labels stand. Re-reading the episode after the producer
returns would throw exactly that guarantee away, which is why the clause forbids it in
terms rather than leaving the read site to an implementer.

What the ordering costs is named rather than hidden: a labelling write that fails after a
committed advance is never retried and that page is never re-read, so those episodes
stay unlabelled for good. That is §8's horizon in miniature and it is the safe
direction — a lost label, never a wrong one, and never a label over the owner's word.

**Why a labelling declines a non-uniform page rather than moving a placement.** A batch
is not uniform in placement: capture writes reach `OWNER` setter `DERIVED` on an episode
whose turn ran over withheld content and the default `Placement()` on every other, and
ADR-0217 §7's acts write reach `OWNER` or `ANYONE` with setter `OWNER_ACT` on a record
already in the store — so one page can hold several. A label proposed over such a page
is a derivation over all of it, and ADR-0217 §3 rules that "a producer deriving a record
from records of this store writes the **narrowest** reach over every record it was
supplied, never over the subset it cited, selected, ranked or judged relevant". Its
ground is ADR-0204 §5's: an `OWNER` input discarded is "an `OWNER` input **laundered**".
Without a rule, a model that resolves a reference inside a restricted episode could file
a less restricted one under the label that reference produced, and the restriction would
have leaked into a record that stays exactly as disclosable as it was.

**The setter is part of the test and not an afterthought, because reach alone does not
say who can lift the restriction.** Two episodes can share reach `OWNER` and differ
entirely in what may become of it: ADR-0217 §7 rules that "Where the placement's setter
is `DERIVED`, `unguard` writes **nothing** — §3's closing clause is not lifted by an
act", while a placement the owner set with `OWNER_ACT` is exactly what `unguard` lifts to
reach `ANYONE`. A rule comparing reach alone would let a label drawn from a `DERIVED`
episode land on an `OWNER_ACT` one and reach `ANYONE` the moment the owner unguards it —
the same laundering one act later, which is the shape ADR-0204 §5's closing prohibition
and ADR-0217 §3's precedence exist to refuse. Comparing both fields closes that without
any arithmetic of this ADR's own.

**Uniformity rather than an ordering, deliberately.** The alternative is a rule that
computes whether a destination is "restricted enough" against every input — a meet over
reach, a total order over setters, and an answer for every pair a later ADR makes
reachable (`PlacementReach` says in terms that new denotations "not totally ordered with
these two" are admissible). That is placement arithmetic invented in an ADR about filing
words, and each pair it gets wrong is a disclosure. Equality of reach and setter needs no
order, is checkable by inspection, stays correct when a later ADR adds a denotation or a
setter, and fails in the one safe direction. What it costs is a page's labels whole
wherever its episodes' placements differ; §6's disclosure covers those episodes like
every other unlabelled one.

**And the write still moves nothing.** Writing the meet onto the destination — the shape
§3's derivation clause describes for a derived *record* — would make a filing word change
what may be said about an episode, silently restricting records the owner never asked to
restrict because they happened to be observed beside a withheld turn. §7 forbids exactly
that: a label "carries no posture and no disclosure consequence". So this decision
**declines the write** instead. Nothing is laundered because nothing is written, no
placement moves, and §14 records the clause as a stacked addition rather than a change to
ADR-0217 or ADR-0204 — it reads two fields and writes neither.
With it, a machine labelling happens at most once per episode and the owner's act is
final over it, which is ADR-0213 §8's shape preserved rather than merely respected.

**Why the two writes are separate, in the direction that matters.** ADR-0077 §2 makes
proposals the pass's product; a labelling is filing. Making the belief install
conditional on a filing write would trade a belief for a label — the trade ADR-0213 §4
already refuses in its own currency ("a rule that discarded the proposal over a bad
label would trade a belief for a filing word").

### 4. What a label is, on each axis

> **Normative.** A **topic** label is a `TopicLabel` in ADR-0213 §3's canonical form,
> and every clause of that section binds it: refused rather than normalised, and
> equality of the stored characters is the only relation two labels have. Nothing
> here widens, narrows or reinterprets that form.

> **Normative.** A **participant** label takes **the same canonical form**: non-empty,
> at most `MAX_TOPIC_LABEL_LENGTH` characters, equal to its own `str.casefold()`, no
> whitespace character other than `U+0020 SPACE`, no leading or trailing space, and no
> run of two consecutive spaces. A value failing any of those is refused at the seam
> and the axis is ignored (§5).

> **Normative.** A participant label **resolves to nothing**. It is not an identifier,
> not a key and not a reference; nothing treats two equal labels as the same person or
> two unequal labels as different people, and no hierarchy, synonym set, stem,
> embedding or model judgement is a relation between two of them. "Alex" in two
> episodes is one label exactly when the stored characters are equal, and for no other
> reason.

> **Normative.** Any wider matching rule — case-insensitivity beyond the canonical
> form, prefixes, initials, surnames, nicknames, a person registry or a similarity
> measure — is reserved to a later ADR, which is the only instrument that may lift the
> clause above. No lane reaches that answer by implementing one.

> **Normative.** **The owner is never named.** No labelling names the owner, the user,
> the assistant, this system or any constant standing for one of them as a participant.
> There is no user identity anywhere in this system (ADR-0036 §3, ADR-0097 §1), and the
> two parties to a turn are structural rather than informative
> (`orchestration/conversations.py`, ADR-0074 §4).

> **Normative.** A producer proposes at most `MAX_TOPICS_PER_PROPOSAL` topic labels
> and at most `MAX_TOPICS_PER_PROPOSAL` participant labels per episode, and each tuple
> is strictly increasing by code point with no repeats, exactly as ADR-0213 §1 requires
> of a stored `topics` tuple. `MAX_TOPICS_PER_PROPOSAL` is 4 and no constant is added
> or changed by this ADR.

**Why a participant label is case-folded, when ADR-0100 §6 keeps a subject label
verbatim.** ADR-0100 §6 stores `about_person` exactly as given because the value is a
label "as the user or the source stated it" — the stated spelling is evidence, and
"a value that is *nearly* right is harder to spot than one that is missing. A
normalised name is nearly right." That reason does not reach here, and the difference
is which object the label is a fact about. `about_person` records **what somebody
said** about a belief's subject; a participant label is **minted by the producer** from
what it read, so there is no stated spelling to preserve and folding one hides nothing.
The spelling the conversation actually used is preserved whole, in the episode's own
`content`, which this decision does not touch. What the canonical form buys is the
axis's entire value: "Alex" and "alex" are one label rather than two, which is exactly
the split ADR-0213 §3 defends at the type — "the first is a spelling, the second is a
judgement". It costs a listing that reads "alex" where the owner wrote "Alex", and
ADR-0213 §3 already accepted that cost for "health" against "Health".

**Why the same form and not a form of its own.** A second canonical form would be a
second rule to keep in step, and the one property both axes need is identical:
deterministic equality over short readable strings. ADR-0213 §3's form is already
ratified, already implemented and already argued; adopting it whole is cheaper than
defending a variant, and §7 states in terms that the shared form transfers no other
property.

**What the equality rule genuinely costs, named rather than hidden.** Two different
people called Alex are one label, and one person written "alex" in one conversation
and "alex chen" in another is two. Both are real losses and neither is repairable by a
string rule: the first needs a person registry (#691, deferred by ADR-0094 §10), the
second needs the wider matching rule ADR-0213 §3 reserves. §11 names both with their
firing conditions. What makes them tolerable now is what makes ADR-0213 §7 tolerable:
the axis is a filing aid whose reach is disclosed, not a claim about who was there.

### 5. The vocabulary, the bound, and the ignored entry

> **Normative.** **No vocabulary is supplied to the observer, on either axis.** No
> belief, label derived from a belief, profile, facet, plan or preference enters an
> observation prompt on this ADR's authority. ADR-0213 §5's last clause and ADR-0077
> §3's "the payload is the batch and nothing else" bind unchanged, and this ADR is not
> the instrument that changes them. The producer proposes from the batch it was handed
> and from nothing else.

> **Normative.** A labelling entry is judged **per axis**. An axis naming more than
> `MAX_TOPICS_PER_PROPOSAL` labels, naming a value the canonical form refuses, or
> naming a value §4's owner clause forbids yields **no labels on that axis** for that
> episode; the other axis stands. The offending value is ignored — never repaired,
> never re-prompted for, never truncated to the bound, and never inferred locally.

> **Normative.** An ignored axis, an ignored labelling and a labelling for an episode
> the pass declines to write are **not discards**. No counter of `ObservationOutcome`
> moves for any of them and no `core` type gains a member to count them.

> **Normative.** A labelling naming an admissible value on neither axis, and a batch
> for which the response carries no labelling key at all, are both **normal outcomes**.
> They leave the episodes unlabelled and are not errors, are not reported as
> degradation, and do not discard the pass's proposals.

**The observer is excluded from a vocabulary for ADR-0077 §3's reason, which this ADR
inherits rather than re-argues.** ADR-0213 §5 already worked the case and refused it:
a vocabulary derived from the store is "a second class of Tier 1 data in the prompt …
arriving for exactly the reason ADR-0077 §3 refuses it — to stop the producer
re-minting what the store already has", and "Supplying it anyway would be a change to
ADR-0077 §3 requiring a record under ADR-0070 §1 and ADR-0082 §1, and this ADR makes
none". This ADR makes none either. The honest consequence is named rather than
softened: **episode labels do not converge across passes.** One conversation may be
filed under "renovation" and the next under "house renovation", with nothing in this
decision to bring them together, and consolidation's within-run accumulation (ADR-0213
§5) reaches the records it distils, not the episodes a different pass read. §11 names
the instrument that could close it and the measurement that fires it.

**Why per axis, where ADR-0213 §4 is per record.** §4's rule is stated for a one-axis
entry, where "the entry" and "the axis" are the same object; a labelling has two, and
ADR-0213 §14's third clause makes them "never read for each other". A malformed topic
is therefore no evidence at all about the participant list beside it, and discarding a
usable list over it would lose information for nothing. This is a fresh rule about a new
object rather than a change to §4's, which continues to bind the observer's proposals
exactly as it does today.

**Why ignoring is right here for the same reason it was right there.** A labelling is
strictly less load-bearing than the episode carrying it and than the proposals beside
it. Repairing a bad label would put the system's guess on top of the model's; counting
it would break an invariant that is exhaustive over a different population; and
truncating an over-long axis to the bound is ADR-0213 §9's refused shape — "a relabel
that quietly kept twelve of the sixteen words the owner typed is harder to notice than
one that did not happen".

### 6. Empty means "no label was recorded", on both axes

> **Normative.** An empty `topics` and an empty `participants` on an episode each state
> that **no label was recorded** for that episode on that axis. Neither states that the
> episode is about nothing or involved nobody, and neither states that it is about
> everything or involved everyone. ADR-0213 §7 binds `topics` unchanged; this clause
> states the same rule for `participants`, which §7 does not reach.

> **Normative.** No consumer, surface, store or later ADR reads an empty tuple on
> either axis as matching a label-scoped act or read, and none reads it as excluded
> from one that names no label. An act or a read reaches an episode if and only if the
> episode carries the label it names.

> **Normative.** A surface performing a label-scoped act or presenting the result of a
> label-scoped read says what it did not reach: that episodes carrying no label were
> not reached, and that the reach is the labels that were recorded rather than the
> subject or the person the owner has in mind.

**The two wrong readings are the ones ADR-0213 §7 named, and on this axis the second
is the live one.** Read as "every participant", an unlabelled episode is returned for
every question about every person — the store's whole history answering one question.
Read as "no participant", an unlabelled episode is silently outside every structured
read, and the owner is told the assistant looked and found nothing when it never looked
at most of what it holds. §8 makes the second reading the one an owner will actually
meet, which is why the disclosure clause is not optional.

**This is ADR-0101 §6's honest limit in a third currency**, and it is stated the way
that section states it — as the surface's *reach* rather than its *miss*, because the
miss is exactly what cannot be computed: naming which unlabelled episodes were really
about Alex would require inferring a participant for them, which is the thing the
absence of a label means nobody did.

### 7. A participant label is not a subject, and the firewall is stated in terms

> **Normative.** A participant label is **not** `about_person` and never becomes one.
> Nothing reads `participants` for the subject axis or `about_person` for the
> participant axis, no validator ties them, an episode may carry both, either or
> neither, and no implementation, lane or later ADR derives one from the other.

> **Normative.** The episode-labelling producer writes **no `about_person`**, on an
> episode or on anything else. ADR-0100 §4 binds unchanged: a producer fills
> `about_person` only from a subject it actually received, never by inferring a person
> from content, and nothing in this ADR may be cited as widening that warrant.

> **Normative.** ADR-0101's subject-scoped erasure and disclosure **do not reach an
> episode through its participants**. A subject query reaches records that state a
> matching `about_person` and no others, exactly as ADR-0101 §6 rules, and no lane may
> extend either act to this axis without an ADR that argues it against ADR-0100 §4 and
> ADR-0101 §§1 and 6.

> **Normative.** A participant label is **not a tier, not a sensitivity, not a band,
> not a grant and not a permission**. It carries no posture and no disclosure
> consequence; `DataTier`, `BeliefBand`, `Provenance.source`, `MemoryBase.placement`
> and every clause of ADR-0199 §3 are untouched, and no episode becomes speakable,
> unspeakable, guarded or exempt by carrying one. ADR-0199 §2's enumeration of what a
> class is decided from is not widened by this ADR.

> **Normative.** A participant label is **not an identifier and not a retrieval
> ordering term**. It resolves to nothing, is not a key into anything, is not a
> cross-hub or cross-store reference, and is no term in any ordering, score, weight,
> threshold or cut applied to retrieved records. Whether it may be an *eligibility*
> filter on a read is a separate question reserved to the ADR that decides that read.

**This section is the price of §1, and it is stated as five prohibitions because each
is a plausible next step a lane could take without noticing it was a decision.** The
decision above admits, for the first time in this corpus, a producer that names a
**person** from the content of a record. ADR-0100 §4 forbids exactly that for
`about_person`, in the strongest terms the corpus has, and the reason is not squeamish:
`about_person` is the key ADR-0101 §1 scopes an **erasure** by and ADR-0199 §2 reads a
**class** off. A person inferred wrongly into that field destroys the wrong records or
speaks the wrong ones aloud.

None of that transfers to this axis, and the clauses above are what keep it that way. A
participant label keys no erasure, no disclosure, no grant, no band and no ordering.
Its only consumer is a filter over the owner's own episodes, shown to the owner alone,
and the cost of a wrong one is that a conversation is offered for a question it does not
answer — a retrieval false positive the owner can see and dismiss. That asymmetry is
the whole argument for admitting the inference here and refusing it there, and it holds
only while the five clauses above do. A lane that keys any consequential act on this
axis has not extended a filing aid; it has moved the subject axis's power onto a field
that was never argued for it.

### 8. The backlog: no pass, and what that costs the owner

> **Normative.** **Nothing labels an episode the observation walk has already passed.**
> No migration, no backfill, no scheduler job, no first-run task, no upgrade step and no
> read-path repair walks the store to label existing episodes, and none is authorised by
> this ADR. ADR-0213 §8's prohibition on migrations and backfills revising a stored
> record's topics is untouched for every record and every route except the one §3 above
> names.

> **Normative.** No implementation may lower, reset or reinitialise an observation
> watermark to bring already-observed episodes back into a pass. ADR-0220 §1's clause —
> "A lane that wants re-reading asks for a new operation, never a lower watermark" —
> binds this ADR exactly as it binds every other.

> **Normative.** The disclosure a surface owes is §6's and is keyed on the **absence of
> a label**, never on a date: episodes carrying no label were not reached, whenever they
> were captured and whatever the reason they carry none. No surface states or implies
> that a capture date decides reachability.

**Why no pass, in the terms of what one would cost.** A backfill is a model call over
every episode the store holds, which is a number no configuration bounds and no run
budget contains — the shape ADR-0111 §4 refuses outright, "a job whose chunk reaches an
operation with no deadline is not a job that may be chunked under this ADR". It would
spend the owner's money on a quantity nobody can see before it starts, to file
conversations the owner may never ask about, and it would do it by re-reading material
the system already read once. Against that, what it buys is a horizon a month of use
erases on its own.

**What it costs, stated so nobody discovers it.** Every episode the observation walk
had already passed when this landed is permanently unlabelled, and §6's reading applies
to it: a structured read over participants or topics does not reach it, ever, and no
later act repairs that. **The horizon is the watermark's, not the calendar's**, and the
difference is not pedantry — an episode captured long before the upgrade but still above
its conversation's watermark is read and labelled by the first pass after it, exactly
like any other, so a disclosure phrased as "conversations before the upgrade were not
reached" would be false in the owner's favour on precisely the records they are most
likely to ask about. That is why the clause above keys on the missing label, which is
what a read can actually see. The
owner's own relabel (ADR-0213 §9) is the one instrument that can label such an episode,
one record at a time, once the surface deferred there exists. §11 names a bounded,
owner-initiated pass as a deferral with the condition that would fire it — a measured
store in which the horizon demonstrably defeats a consumer's promise, and a budget the
owner sees before it is spent.

### 9. Scope: the `core` surface, the version, and the triad

> **Normative.** The `core` change is exactly: `core/types.py` gains
> `EpisodeLabelling`, and `ObservationOutcome` gains `labellings`. **`core/protocols.py`
> gains nothing, changes nothing and removes nothing.** No constant is added or changed,
> no enum gains a member, and `core/errors.py` is untouched.

> **Normative.** `PROTOCOL_VERSION` does **not** move for this change.
> `ObservationOutcome` and `EpisodeLabelling` cross no wire: they appear in
> `core/types.py`, `core/protocols.py`, `learning/observer.py` and
> `testing/observation.py` and in no other module, and no wire payload reaches either.
> `EpisodicMemory` does cross the wire, inside `TurnResult.memories`, and this decision
> changes neither its shape nor its defaults — a labelled episode serialises through the
> members it already had, so an older peer decodes a newer hub's episode exactly as it
> decodes today's.

> **Normative.** The canonical fake in `ai_assistant.testing` gains whatever the
> widened seam value requires of it, in the same change (`CONTRIBUTING.md` → "Adding a
> Protocol"). No lane lands the type widening and the fake separately.

> **Normative.** The `core` change and the `learning`/`orchestration` implementation
> **land in the same PR or in that order, never the reverse**, and this ADR is merged
> and ratified before either (golden rule 5, ADR-0015 §5).

**Why this is a contract-surface change and is being stated as one.** #2133 briefed
this lane expecting no `core` change, and the tree says otherwise: `Observer` "holds no
store handle" and "writes nothing", so a labelling the producer computes has to reach
its caller through the value `observe` returns, and that value is a `core` type. The
alternatives to widening it are a second model call (§1 and the Alternatives), a
`core/protocols.py` change (strictly larger), or a labelling derived from the beliefs
that cite an episode (a derivation from another record, which ADR-0213 §1 forbids in
terms — "nothing that rewrites a record because of something that happened to another
one"). One additive member on one in-process seam value, with `core/protocols.py`
untouched, is the smallest surface this decision can be had for.

### 10. What the implementing lane owes

The lane briefed from this text owes, beyond the change itself:

- **The two seam refusals, as tests.** A labelling naming an episode outside the batch
  is ignored; a labelling whose axis violates §4 leaves that axis empty and the other
  standing.
- **The write's shape, asserted rather than assumed.** That the write is
  `IF_UNCHANGED` against the revision the pass read; that a stale write is abandoned and
  not retried; that an episode carrying a label on either axis is not written; that no
  field but the two moves, asserted field by field against the stored record.
- **The ordering and the two failure arms.** That no labelling is written where the
  watermark advance is not attempted or does not commit — a belief install that raises
  leaves the watermark unmoved (ADR-0212 §§5-6) and therefore leaves every episode of
  that page unlabelled, which is the existing advance behaviour asserted afresh rather
  than changed. And that a labelling write which fails or is refused **after** a
  committed advance leaves the pass's installed beliefs and its committed watermark
  exactly where they were.
- **The clear-then-reread arm.** A pass labels a page, its advance does not commit, the
  owner clears those labels, and the next pass re-reads the page: the owner's empty
  labels stand, because the ordering means the first pass wrote none. Pinned as the arm
  that holds ADR-0213 §9's finality.
- **The non-uniform placement arms, both of them.** A page holding a reach-`OWNER`
  episode beside reach-`ANYONE` ones is labelled nowhere; and a page whose episodes share
  reach `OWNER` but split between setters `DERIVED` and `OWNER_ACT` is labelled nowhere
  either. No episode's placement moves in either arm.
- **The overlap-race arm.** Two passes select one page; the first advances and labels;
  the owner clears those labels; the second — holding the record it was handed at
  selection — is refused by `IF_UNCHANGED` and writes nothing. Pinned as the arm that
  holds ADR-0213 §9's finality against ADR-0212 §5's permitted concurrency, and it fails
  only if an implementation re-reads the episode after the producer returns.
- **The provider-down arm.** A `ModelError` leaves every episode of the batch exactly
  as capture wrote it, and the pass reports what it reports today.
- **The owner arm.** An episode the owner relabelled between the pass's read and its
  write keeps the owner's labels, and the pass's labelling is discarded.
- **A representative-input arm on the label form.** A response naming "Alex" leaves the
  participants axis empty for that episode. The value the model emitted is validated **as
  it stands**: nothing case-folds, strips or otherwise repairs it on the way to a label,
  because §5's ignore-never-repair rule and ADR-0213 §3's prohibition on normalising both
  bind here, and a producer that folded its response would hide its own miss "in the one
  place nobody looks". A producer that wants canonical output constrains its prompt; it
  does not correct the answer.
- **The owner-never-named arm.** A response naming the owner, the user or the assistant
  as a participant yields no participants for that episode.

### 11. Deferred, by name, each with the condition that fires it

- **A structured read over these labels.** The filters, their argument law, what a
  filtered read returns, and what "capped" means under one. **Fires** with the
  `track:memory` lane that decides the `MemoryStore` surface; it is a Protocol change and
  therefore its own ratified, separately-merged ADR. Nothing in this ADR is usable until
  it lands, and that is by design rather than by omission.
- **A bounded, owner-initiated labelling pass over the backlog.** §8 declines an
  automatic one. **Fires** with a measured store in which the unlabelled horizon
  demonstrably defeats a consumer's promise, and it owes what §8 says a pass cannot have
  today: a bound the configuration can compute, and a cost the owner sees before it is
  spent.
- **A vocabulary supplied to the observer, on either axis.** §5 withholds it on
  ADR-0077 §3's ground, and ADR-0213 §5 already named this deferral for topics. **Fires**
  with an ADR that amends or partially supersedes that clause under ADR-0070 §1 and
  ADR-0082 §1 and argues the ADR-0004 §7 trade in its own terms — most likely the lane
  that measures the fragmentation §5 predicts, now that there is a second axis
  fragmenting.
- **A matching rule wider than equality for a participant label.** §4 reserves it.
  **Fires** with the first consumer whose promise cannot be kept by exact labels — "alex"
  and "alex chen" reaching different sets is the owner's first surprise.
- **Two people with one name.** §4 names the loss. **Fires** with the person registry
  #691 and ADR-0094 §10 defer, which is the only instrument that can tell them apart; no
  string rule can.
- **`about_person` on an episode.** §7 forbids this producer from writing one and
  ADR-0100 §4 forbids inferring one. **Fires** only with an ADR that reckons with that
  clause; an episode's subject is not a gap this decision left, it is a field the corpus
  deliberately keeps closed.
- **A per-record record of who set an episode's labels.** ADR-0213 §15 already carries
  this deferral and this ADR does not fire it: after §3 an episode's labels came from the
  observation pass that read it or from the owner's act, which is the same two-source
  ambiguity §15 already contemplates for beliefs, and no new class of labeller is
  introduced. **Fires** where §15 says it does — with the first surface that renders a
  label beside where it came from.
- **Whether an episode's `occurred_at` is the exchange's instant or the event's.**
  #1908's point (b) names it beside the who/what gap. It is a different field with a
  different producer and this ADR touches neither. **Fires** with the lane that needs an
  event time distinct from a recording time.
- **The owner's relabel and merge surface, and the one obligation this decision adds to
  it.** ADR-0213 §9 defers the surface and this decision inherits the deferral unchanged.
  It adds one thing that lane owes: **a rule distinguishing an episode whose labels the
  owner deliberately emptied from one no pass has yet reached.** §3's eligibility test is
  the two empty tuples, and it cannot tell those apart. Every sequence in which that
  matters *after* a pass has labelled is closed by §3's ordering and its pinned revision;
  what is not closed is an owner emptying an episode's labels **before** any pass reaches
  it, after which the next pass labels it. That act is unperformable today — §9 rules
  that no lane implements the surface without an ADR deciding it — so the gap is
  reachable only from the lane that would open it, and it is that lane's to close, with
  the durable distinction and the eligibility rule it implies. **Fires** as §9 says, with
  this obligation attached.

### 12. This ADR fires ADR-0213 §15's "topics on episodes", as its second case

ADR-0213 §15 deferred this ground with a condition:

> **Topics on episodes.** §6 rules that no producer proposes one today. **Fires**
> where a consumer's promise is materially wrong without them — the first case is a
> topic-scoped guard, since an unguarded transcript of a guarded conversation is the
> laundering shape ADR-0204 §5 closed for its own axis by inheritance rather than by a
> second proposal.

The topic-scoped guard is still the first case and is still unbuilt. **This is the
second**, and the condition is met on its own terms: #1908's milestone 30 promises that
the assistant finds the right part of the owner's history by *when, who and what*, its
exit turns on a question naming a person and a topic, and its own audit says the promise
"cannot be answered by structure" while the axes are empty. A consumer whose exit
question cannot be answered at all is a promise materially wrong without them.

The section also lists "The storage a filtered record read needs" as a deferral of its
own, and this ADR does not take it: nothing here filters a record by label, and the lane
that adds that read is still the lane that knows whether it wants a column, a child table
or an index.

### 13. What this ADR does not decide

> **Normative.** **Any `MemoryStore` read, filter or argument.** No member is added,
> no read gains a parameter, and no clause here says what a label-scoped read returns.

> **Normative.** **Anything about `ConsolidationStage`.** ADR-0213 §5's accumulator and
> §6's answer for that producer bind unchanged; it labels the records it distils and no
> episode it read.

> **Normative.** **The observation prompt's schema.** ADR-0077 §9.5 declines to ratify
> one and this ADR does not mint one: §1 fixes that the labelling rides the envelope the
> producer already sends and that the ids are the caller's, and the shape of the key is
> the implementing lane's, exactly as ADR-0217 §4's placement key was.

> **Normative.** **Any change to the observation walk, its watermark, its batch size or
> its trigger.** ADR-0212, ADR-0218 and ADR-0220 are untouched.

> **Normative.** **Any change to capture.** ADR-0074 §3 and §4 and ADR-0075's exemption
> are untouched, and `orchestration/conversations.py` writes exactly what it writes
> today.

> **Normative.** **Anything about a placement.** ADR-0217's three setters, its meet and
> its precedence, and ADR-0204 §5's ratchet, are untouched. §3's placement clause
> decides only whether a *labelling* is written; no clause here writes, narrows, widens
> or reads a placement for any other purpose, and no lane may cite it as a placement
> rule.

> **Normative.** **Whether a labelling should ever be retried, or a failed one
> recovered.** §3 abandons and §8 declines a pass; a bounded recovery is §11's deferral
> and is not opened here.

> **Normative.** **Any client-facing surface.** No `Belief`, `BeliefSummary`, gateway,
> CLI or spoke renders, filters on or sets a label under this ADR.

### 14. This ADR classified under ADR-0070 §1 and ADR-0082 §1

ADR-0082 §1's test is ADR-0070 §1's applied to the earlier ADR's text: would a reader
holding only that ADR now act differently, or read one of its clauses more widely than
it now holds?

**ADR-0213 — partially superseded, in three named clauses, for `EpisodicMemory` records
only.**

- **§4's first clause.** "Topics are set by the producer of the record, at the moment
  the record is written, and by nothing else." A reader holding only ADR-0213 would
  refuse §1's labelling outright. After this ADR an episode's topics are set by a
  producer that is not the record's, at a moment after the record was written. The test
  comes out on the supersession side. **The second half of that same clause is not
  replaced and binds unchanged**: no consumer, surface, store, retrieval path, scheduler
  job, migration or later ADR derives a record's topics *at read time*, and none derives
  them from `content`, a rendered facet, a composed reply or any other span of content
  after the write. §1 above sets a label at a fixed, recorded moment; it does not derive
  one at read.
- **§6's first clause.** "Exactly two producers propose topics: `ModelBackedObserver`
  …, on each `MemoryUpdateProposal` it returns, and `ConsolidationStage` …, on each
  record it distils. Every other producer writes the empty tuple." The set of producers
  is unchanged and the second half stays true, but the enumeration of *what* the observer
  labels is now too narrow: a reader holding only ADR-0213 would read it as excluding an
  episode, and would act differently. Replaced to the extent of that enumeration; the
  clause's answer for `ConsolidationStage` and for every other producer stands.
- **§6's fifth clause.** "No producer infers a topic for a record it did not itself
  produce, and no producer proposes topics on a record another producer wrote." This is
  unqualified and this ADR makes it false for episodes. Replaced for `EpisodicMemory`
  records; it binds every other record exactly as written, so no producer labels a
  belief, a preference, a fact or a procedure it did not produce.
- **§8's first clause.** "A record's topics are set by its producer at write and are
  revised only by the two routes below. No re-observation, no consolidation of an
  already stored record, no retrieval, no re-embedding, no reconciliation, no scheduler
  job, no migration and no backfill revises the topics of a record already in the
  store." §3 above is a scheduled pass revising a stored record's topics, so the clause
  is false for episodes. Replaced for `EpisodicMemory` records, and replaced narrowly:
  §3's write-once rule and §8's prohibition on migrations and backfills keep everything
  else that clause was protecting, and the fold's union, the retained subset and the
  `SUPERSEDE` rule are untouched on every record.
- **§8's last clause.** "**The owner's act** (§9) is the only in-place write of this
  field, and it writes the record's topics at the record's own id." §3 above introduces
  a second in-place writer, so the word "only" becomes false and a reader holding just
  ADR-0213 would refuse the write. Replaced for `EpisodicMemory` records, and replaced
  as narrowly as the sentence allows: the owner's act remains an in-place write at the
  record's own id, remains the only one on every other kind of record, and remains
  **final** over an episode a pass has labelled — §3's write-once rule and its ordering
  are what keep that half true rather than merely asserted.

**§6's second clause is *not* superseded, and the distinction is load-bearing.**
"Capture (`orchestration/conversations.py`) writes no topics on the `EpisodicMemory` it
records per turn. No topic is proposed on any episode under this ADR, by any producer."
Its first sentence stays true — capture still writes none, and §1 above says so in terms
— and its second is self-limiting: it states what holds *under ADR-0213*, and ADR-0213
§15 anticipated this ADR by name. A reader holding only ADR-0213 reads that sentence
correctly before and after.

**Everything else in ADR-0213 stands and is relied on rather than replaced**: §1's
field, its bound and its canonical order; §3's label form and equality rule; §4's
envelope discipline, its constants and its ignored-entry rule; §5's vocabulary rules
including the observer's exclusion; §7's empty-means-unrecorded and its disclosure; §9's
owner acts and their deferred surface; §10's fingerprint exclusion; §14's four
prohibitions.

**No record is owed on any other ADR, and each near case is named with the test's
answer.**

- **ADR-0074.** Capture is unchanged in every particular, so no sentence of it becomes
  false or over-wide. Its §4 observation that `participants` is "the field an observer
  means to fill" is the same expectation this ADR meets rather than contradicts.
- **ADR-0005 and ADR-0075.** ADR-0075 §1 already narrowed ADR-0005's path to "**every
  write of a belief**", and §3 above argues at length that a labelling is not one: it
  adds no claim about the user, which is the test ADR-0075 §2 states in terms. So the
  rule does not reach this write and this write claims no exemption from it — ADR-0075
  §2's list is a list of what **capture's** exemption does not cover, and nothing here
  invokes capture's exemption. Neither ADR has a clause made false or read more widely:
  every belief the observer proposes still goes through the gate, capture is still the
  one exempt producer, and the observer is still "the paradigm case the gate exists for"
  for the output that is a belief. **No record is owed on either**, and the reason is
  recorded here so a reviewer can check the test rather than the label.
- **ADR-0217 and ADR-0204.** §3's placement clause **writes no placement**, so ADR-0217
  §3's three setters, its meet and its precedence are untouched, and ADR-0204 §5's
  ratchet is neither weakened nor restated. What the clause does is decline a write
  whose result would have carried a narrowing's information onto a wider record — it
  honours their ground by refusing, where a derived *record* would have inherited. A
  **stacked addition**, recorded here and nowhere else.
- **ADR-0077.** §3's minimal payload is honoured, not widened (§5). §4's
  discard-and-count rule binds the proposals population exactly as written; §5 above
  states a fresh rule for a new object and takes nothing from it. §9.5's declining to
  ratify a prompt schema is relied on.
- **ADR-0100.** §4's prohibition on inferring a subject is untouched — this producer
  writes no `about_person` (§7) — and §6's verbatim rule binds `about_person` alone.
  §6's own observation that `EpisodicMemory.participants` "has been
  free-text-resolving-to-nothing since ADR-0005 §1" is quoted as support, not amended.
  A **stacked addition**, recorded here and nowhere else.
- **ADR-0101.** §7 above states that the subject-scoped acts do not reach an episode
  through its participants, which is what §1 and §6 of that ADR already say — they reach
  records stating a matching subject label. Nothing becomes false.
- **ADR-0199.** §2's enumeration of what a class is decided from is not widened (§7),
  and no consumer inspects content at read time (§1). Nothing becomes false.
- **ADR-0212, ADR-0218, ADR-0220.** The walk, its watermark, its trigger and its budget
  are untouched (§3, §8, §13).
- **ADR-0219.** §5 names two users of `IF_UNCHANGED` and this ADR adds a third. That
  section is an enumeration of who uses the mode, not a closed set of who may — §8 of
  that ADR lists what it does not decide and a third consumer is not among the things it
  reserves. A **stacked addition**, recorded here.
- **ADR-0068.** The freeze is a property of the objects; §3 above writes a new record at
  an existing id, which is the shape ADR-0213 §8 already ratified for the owner's act.
  Nothing becomes false.

## Consequences

**Easier.**

- **The who/what axes stop being empty.** Milestone 30's exit question — "which
  conversation with you involved Alex and the conference" — becomes answerable by
  structure the moment the read it maps to lands, on every conversation captured after
  this implementation.
- **It costs nothing to run.** No new provider call, no new round trip, no new failure
  mode on the turn's hot path, and no new walk. The added cost of a pass is at most eight
  short strings per episode in a response the producer already parses.
- **The corpus states one rule for one axis in one place.** A participant label and a
  topic label have the same form, the same equality rule and the same
  empty-means-unrecorded reading, so a lane consuming either has one thing to learn.
- **The recorder's own docstring becomes true.** `orchestration/conversations.py` has
  named an observer as the intended filler of `participants` since ADR-0074; the field
  stops being a promise nobody kept.

**Harder.**

- **The corpus admits, for the first time, a producer that names a person from content.**
  §7 is five clauses long because that is what it costs to admit it safely, and every one
  of them is load-bearing. A future lane that wants an erasure, a disclosure or a grant
  keyed on this axis has a wall to argue through, and it should.
- **Labels do not converge across passes.** Two conversations about one subject may be
  filed under two labels with nothing to bring them together. §5 names it; §11 names the
  instrument and the measurement that would close it.
- **Every episode the walk had already passed is permanently unlabelled.** §8 is
  explicit about this and §6 obliges every surface to say so — keyed on the missing
  label rather than on a date, because the horizon is the watermark's.
- **A mixed-placement page loses labels on its wider episodes**, and a labelling write
  that fails after a committed advance loses them for that page for good. Both are §3's
  choices and both fail in the same direction: a lost label, never a wrong one and never
  one over the owner's word.
- **A `core` type widens, and the implementation lane is a `core` holder.** #2133 briefed
  it as "no `core`"; it is one additive member and one small model, with
  `core/protocols.py` untouched, but it has to be sequenced with the batch's other `core`
  lanes rather than beside them.
- **ADR-0213 acquires a partial supersession four clauses wide.** A reader of that ADR
  now has to carry "except for episodes" through §4, §6 and §8. §14 states the scope
  exactly so the exception is bounded rather than atmospheric.

## Alternatives considered

**A labelling producer of its own, with its own model call.** A stage in
`orchestration` holding a `ModelProvider` and a `MemoryStore` — architecturally a
sibling of `ConsolidationStage` — reading the same batch and prompting for labels alone.
Its one real advantage is that it needs **no `core` change at all**, which would have
kept the implementing lane out of #2133's `core` sequence. It was rejected on three
counts, in order of weight. It pays a second model call to read material the observer is
already reading, doubling the cost of a pass for one sentence of output — and ADR-0213
§4's discipline, "This ADR authorises no second model call, no second round trip and no
second provider dependency anywhere in the system", states exactly that principle for
exactly this axis. It transmits the same Tier 1 material to the same recipient a second
time, which is the wrong direction under ADR-0004 §7 whether or not it is a new class of
data. And it adds a second failure surface to a pass that already has one, so a pass
could now half-fail in a new way. Trading a ratified cost discipline for a smaller
`core` diff is the wrong trade; the sequencing consequence is a scheduling fact, and the
provider call is the owner's money.

**Capture labels at write.** The shape ADR-0213 §4's first clause would have preferred,
and the one that needs no revision of a stored record at all. Rejected because it needs a
`ModelProvider` on the turn's hot path — latency on every turn, and a turn that fails
when a provider is down — and because it would forfeit ADR-0075 §2's exemption on the
sentence that grants it: the exemption covers "a deterministic, non-inferring recording
of a turn", and a capture that asked a model what a turn was about is neither
deterministic nor non-inferring. The exemption is the thing that lets an episode be
written at all without a policy gate; spending it on a filing word is not a trade worth
making.

**Deriving an episode's labels from the beliefs that cite it.** The observer already
labels each proposal and each proposal cites the episodes it came from, so the mapping
appears to be free. Rejected on two grounds. ADR-0213 §1 forbids the shape in terms —
"nothing that rewrites a record because of something that happened to another one" — and
the semantics are wrong anyway: a belief distilled from a conversation is not what the
conversation was about, and a belief's subject is not who was in the room. It would also
leave an episode that produced no belief permanently unlabelled, which is a large and
arbitrary fraction of them.

**Storing the labels somewhere other than on the episode.** A side table, a labelling
record, or a second kind. Rejected because the fields already exist on `EpisodicMemory`,
because every consumer #1908 contemplates is a filter on a record read, and because a
second object would need its own type, its own store surface, its own liveness rule and
its own answer to what happens when the episode is forgotten — all to avoid a write that
ADR-0213 §8 has already ratified the shape of.

**Verbatim participant labels, on ADR-0100 §6's rule.** Keeping the spelling the
conversation used, exactly as `about_person` keeps the spelling the user or source
stated. Rejected because the reason for that rule does not transfer: §6 preserves a
*stated* label because the statement is evidence, and this label is minted rather than
stated. Verbatim storage would make "Alex" and "alex" two labels on the one axis whose
entire value is that they are one, and the spelling the conversation used is preserved
anyway, in the episode's own `content`. What it would have bought — leaving every wider
matching rule available — §4 keeps regardless: a canonical form narrows nothing that a
later matching rule could have used, because casefolding is the one normalisation a
case-insensitive rule would have applied itself.

**Retrying a refused labelling write.** ADR-0219 §5's two consumers retry once. Rejected
because a retry computed against the older row would overwrite whatever moved it, and the
likeliest thing that moved it is the owner's own relabel — the one write ADR-0213 §9
makes final. A labelling has nothing waiting on it, so abandoning costs a filing word and
buys the owner's correction surviving a race.
