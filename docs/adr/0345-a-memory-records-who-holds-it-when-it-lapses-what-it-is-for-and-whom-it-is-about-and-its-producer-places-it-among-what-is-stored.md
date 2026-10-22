# 345. A memory records who holds it, when it lapses, what it is for and whom it is about, and its producer places it among what is stored

- Status: Proposed
- Date: 2026-10-21
- Scope: the memory record and the write path a placed proposal takes. Who holds each support, the assistant's messages as statements it made and never as its beliefs, and the rule that a memory is changed only in its own holder's beliefs and never kept current by the assistant's statements alone; a proposal that names how it stands to each stored memory its producer retrieved, and the write that follows from it; a validity end set at creation; situation labels; marks; a producer for `about_person` and a search filter on it; the retirement of `topics` from the memory; and the upgrade. The observer's use of all of it, what it reads, its steps and its calls, is the second decision of this walk.
- Dependency: ADR-0328, ADR-0329, ADR-0336, ADR-0217, ADR-0219, ADR-0045, ADR-0100, ADR-0213, ADR-0326 and ADR-0338, as their status lines leave them.
- Authorization: the owner ruled this design in the observer walk of 2026-10-21, in the observer-and-learning fork, and directed it be written ("I think we get started"). This decision writes those rulings down and settles only what they leave open, each such point named where it is settled. The number is provisional until the owner assigns it (`CONTRIBUTING.md` → "ADR numbers are assigned at dispatch"). The owner reads it before it is ratified (§1:1).
- **Contract-surface decision.** It changes `core/types.py` (`MemorySupport` gains its holder; the memory gains labels and marks and loses `topics`; `MemoryUpdateProposal` gains a placement; the projections gain holders, labels, marks and a future validity end) and `core/protocols.py` (`MemoryStore.search` gains an `about_person` filter; `MemoryWriter.ingest` writes a placed proposal by §5; `MemoryWriter` gains a label write). It is a breaking change under golden rule 5.
- **Partially supersedes**, in the clauses §16's table names: ADR-0213, ADR-0328 and ADR-0336.

## Context

### What the owner ruled

The walk started from the observer and reached the record it writes. These rulings
shape the record.

- **Capture is not usage.** On a home device that knows who is talking, the owner
  says Sam can't be trusted with something and Sam says Sam can: "both statements
  should be into the system with the provenance … there's a difference between
  capture and usage. And so now we have to just make sure the capture is right."
  Which statement governs is usage's question, by topic and by who is asking. The
  record's job is to hold enough that usage can decide.
- **A memory is a belief someone holds.** "If I say the wall is red and Sam says the
  wall is blue, is that really contradictory? No, because it's saying I believe the
  wall is red, Sam believes the wall is blue. Both are true." A contradiction exists
  only inside one holder's beliefs over time. The owner agreed that a holder retires
  only their own backing, and asked to keep the existing ranking as usage's default:
  recall that prefers what the owner said ("maybe a recall does a filtering for
  statements made by the owner first").
- **A holder is a connection, and never a claim.** "It's not the identification that
  matters here, it's the connection": two parts under one stable identifier are one
  holder, and the person behind it can be linked later. A forwarded "message from the
  user", a screenshot, or Sam saying "the user agrees with me" stays Sam's: only an
  identity the channel establishes holds a person's belief.
- **A contradiction is kept beside, as evidence against.** Nobody's word removes another
  holder's belief by rule. A claim against a memory from someone who does not hold it is
  installed beside it and recorded on it as evidence against.
- **No beliefs of the assistant's own, for now.** After the owner's worry that an
  advertisement could convince the assistant and, through it, the user, long-term memory
  holds only what people and sources believe. The assistant's message is a statement it
  made, "the source of I stated this at this time in this chat, not that I believe this",
  and never a
  belief it holds. Where a person keeps something the assistant said with nothing behind
  it, the memory cites what it can, the assistant's message: "make it not that there's no
  source. Instead, it should cite what it can." With the assistant holding nothing, there
  is nothing to convince it of; convincing waits for a decision on its standards of
  belief.
- **A person is a kind of source.** "Person is a type of source, no?" One holder, of
  several kinds, under one set of capture rules.
- **The commit step frames, then places.** The new memory's wording and metadata come
  from what it rests on alone, without the stored memories: "I don't see why
  information about what's already in the store should affect how it frames the
  memory". Then "code mechanically retrieves similar memories. It doesn't have to be
  capped at 5", and "for each one, the model can decide … some sort of enum on its
  relationship". The owner agreed the closed set §4 adopts, with "weakens" and
  "recheck" kept apart.
- **No kinds; labels and marks instead.** A kind field was rejected: "there's so many
  memories that linger between two or three kinds", and "for plan, isn't that
  time-bounded stuff covered by the validity window". In its place, free-text labels
  "attached to the memory … for a separate kind of recall that is a semantic search
  over labels instead of the content", with "some minimum semantic search distance"
  against near-duplicates at write, and a writer free to "reorganize the labels".
  Machine-filterable values such as a one-time occasion are a separate closed field
  (agreed as "D22 confirmed").
- **Writes stay safe without new machinery.** "We have to make sure it's also async
  safe", then "unless I'm wrong, it doesn't need to write at the same time safely":
  the observer is the one writer and runs one run at a time, so the existing guards
  are the whole answer (§11).

Two more rulings set what the record carries: the scout extracts whom a memory is
about from the episode, and a memory's sensitivity is a placement the scout proposes
(the observer's decision, §9 here only names the producer).

### What is there today

Surveyed at `15e62f08`.

- **A support carries an origin but no holder** (ADR-0328 §4). The origin table says
  how the part reached the assistant: the user's message, a confirmation, a source's
  evidence, the assistant's words, an inference. Who held the belief is implicit: the
  user's message is the owner's, since the owner is the only person whose input any
  channel admits (`orchestration/telegram.py` takes input only from the configured
  account; the hub chat and the web door admit only the owner's devices and sign-in).
- **Retirement follows a ranking across origins.** ADR-0328 §6:5 refuses a retiring
  operation whose cited support ranks below the memory's standing.
  `DefaultMemoryPolicy` (`memory/policy.py`) rules over the reconciler's relations by
  band: an asserted proposal supersedes a derived or attested member it contradicts
  (its rule 9, ADR-0336 §3(b)).
- **The relation is judged inside the write path.** `MemoryIngestor` invokes a
  reconciler model on every admissible unconfirmed ingest (ADR-0336 §2:1), labelling
  each member of a similarity-cut conflict set `RESTATES`, `ADDS` or `CONTRADICTS`
  (`ConflictRelation`). The observer's commit step has already chosen an action over
  up to five similar memories it was shown (ADR-0329 §9:3), so the same question is
  answered twice.
- **A validity end cannot lie in the future.** ADR-0328 §5:10 refuses an end whose
  about-when lies after the operation's instant: "a claim that holds until a later
  time is worded so". Nothing then knows the claim has lapsed.
- **`about_person` and `topics` have no producer** (ADR-0328 §3:6). `topics` is
  ADR-0213's canonical exact-match tag list.
- **`MemoryStore.search` ranks by relevance alone** over the content, filtered by
  kind and band.
- **Style marks and pin suggestions** live in the person-model store (ADR-0338 §9:4,
  §9:5).

### Words

A **holder** is the party whose belief a support records (§2). A **placement** is a
producer's statement of how a proposed memory stands to each stored memory it
retrieved (§4); a proposal carrying one is **placed**. A **situation label** is a
free-text descriptor of when or for what a memory matters (§7). A **mark** is a member
of a closed set describing the memory itself (§8). A memory's **holders** are the
holders of its counted `for` supports that back it as worded (§2:8). **Standing**,
**support**, **origin**,
**operation** and **counted** are ADR-0328's.

## Decision

We will record, on every support, who holds the belief it records, and change a memory
only in its own holder's beliefs. A producer that has retrieved the stored memories
similar to its proposal names how the proposal stands to each, from a closed set, and
the writer derives the write from those relations by rule, with no reconciler and no
ranking across holders. A memory may carry a validity end in the future, situation
labels, marks and whom it is about, and stops carrying `topics`.

### 1. Status, scope and delivery

> **Normative.** This document remains `Proposed` until the reviews `CONTRIBUTING.md` →
> "Finishing an ADR PR" requires have returned green on one tree and the owner, having
> read it, has authorized its ratification. An assigned number or a green review alone
> does not change its status.

> **Normative.** No lane implements against this decision before it merges `Accepted`
> (golden rule 5, ADR-0015 §5).

> **Normative.** The implementation is cut into lanes by the dispatcher under ADR-0137, as
> §15 sets out, and each lane keeps the gate green.

### 2. Who holds a support

| What the support points at | Its holder |
| --- | --- |
| The input or one of its messages, where the input's `InputOrigin` is `USER` and the message carries no `forwarded_from` | The person who sent it: the owner, today |
| A confirmation | The person who gave the yes: the owner, today |
| A pin (ADR-0338 §4:4) | The person who made the pin |
| A message carrying `forwarded_from`, or an input whose `InputOrigin` is `OUTSIDE` | A claimed source: the forward's claimed original sender where the trigger records one (`ClaimedAuthor`), held as claimed, and otherwise unknown |
| An evidence item | The source the record names: its digest's `Attestation.reported_by` where the record states one, and otherwise unknown |
| A round's message, a remember call, or an observer's inference | The assistant's statement: what it said, where and when |
| A legacy record | Unknown |

> **Normative.** Every support records its holder, set by code from the part it points at
> and the episode's record, as the table rules. No model's output sets or changes a
> holder.

> **Normative.** A holder is the source of the claim a support records, and is one of four
> kinds, a closed set added to and never renamed: a person, named by an identifier; an
> outside source, named by an identifier and marked established or claimed; the
> assistant's statement, naming the message it made; and unknown. Every kind is held
> under the same capture rules.

> **Normative.** A holder of the kind the assistant's statement records that the assistant
> said something, where and when, and never that it believes it. The assistant holds no
> belief, and nothing in this decision changes, retires or keeps a memory on the ground
> that the assistant believes anything.

> **Normative.** Until a decision on identified people adds others, the one person a
> holder names is the owner, and the identifier that names the owner is a
> composition-root constant.

> **Normative.** A holder is named by the stable identifier the record carries for whoever
> said or reported the part, whether or not that identifier resolves to a known person:
> `Attestation.reported_by` for an evidence item, and the claimed sender's identifier for
> a forward. Two holders are the same holder exactly where they name the same identifier,
> and connecting two parts to one identifier is enough, with no identity behind it. A
> part whose record carries no identifier has an unknown holder, which is never the same
> holder as any other.

> **Normative.** A person holder is named only by an identity the channel itself establishes
> for whoever sent the part (ADR-0323 §4:2). An author the part only claims, in a forward,
> a quotation or a report, names a claimed source holder, which is never the same holder
> as an established one, whatever identifier either carries, and becomes the same only by
> the owner's act linking the two.

> **Normative.** A holder is set from who sent or reported a part, never from what the
> part says. A part claiming what another person believes is held by whoever sent it.

> **Normative.** A support keeps the identifier its holder was recorded under, and no write
> rewrites it. Which person an identifier belongs to is a link held outside the support,
> by a later decision on identified people. Once such a link exists, every support
> carrying that identifier is attributed to that person without being rewritten, and two
> holders whose identifiers link to the same person are the same holder in every write
> made after the link.

> **Normative.** A memory's holders are the holders of its counted `for` supports that back
> it as worded, and its partial supporters are the holders of its other counted `for`
> supports. Both are values ADR-0328 §7 computes from the stored record, never stored as a
> judgment, and a partial supporter is never shown as holding the memory.

> **Normative.** A memory's standing stays as ADR-0328 §6 computes it. It says how the
> memory's backing reached the assistant, and in a placed proposal's write (§5) it ranks
> no holder above another.

**Why only an established identity holds.** Sam forwarding a text "from the user", or
showing a screenshot of one, or saying "the user agrees with me", must never make a belief
the user's. Each is held by Sam, with the claimed author recorded as a claimed source. What
the user believes comes only from the user's own words on a channel that establishes them.

**Why a holder beside the origin.** The origin says how a part reached the assistant;
the holder says whose belief it is. Today they coincide, because only the owner speaks,
and the table maps every origin to one holder. They part once a device knows who is
talking: Sam's message to a home speaker is a person's direct word, with an origin like
the owner's and a different holder. Recording the holder now, while it is always
derivable, costs one field and spares an upgrade that would have to guess.

### 3. A memory changes only in its holder's beliefs

> **Normative.** In the write a placed proposal yields (§5), a retiring relation changes a
> stored memory only through the supports whose holder is a holder of one of the
> proposal's backing supports: each such counted support stops counting, by one stop
> counting each, citing that holder's backing support, added to the stored memory as
> `against`.

> **Normative.** The proposal's backing supports, in the clause above and throughout §5,
> are its counted `for` supports that back it as worded, and its first backing support is
> the first of them.

> **Normative.** A stored memory whose supports the clause above stopped is retired in the
> same atomic write, by the operation the relation names (§5), exactly where no counted
> `for` support backing it as worded remains on it. A memory some other holder still
> holds stays current.

> **Normative.** A retiring relation from holders none of whom holds a counted support of
> the stored memory stops nothing and retires nothing. The writer installs the proposal
> beside the stored memory, adds the proposal's backing supports to the stored memory as
> `against`, and adds the stored memory's backing supports to the proposal as `against`,
> so the dispute is recorded on both.

> **Normative.** Until a decision on the assistant's standards of belief decides otherwise,
> supports whose holder is the assistant's statement never keep a memory current on their
> own. A write that leaves every counted `for` support backing a memory as worded the
> assistant's statement retires it in the same atomic write, by an end citing the support
> whose stopping left it so.

> **Normative.** ADR-0328 §6:5's refusal by standing does not bind the write a placed
> proposal yields. The clauses above are its guard.

**Why per holder.** A stored "the wall is red" held by the owner and a new "the wall is
blue" held by Sam are both true as beliefs. Retiring either would destroy a fact about
what someone believes, on a ranking that usage, not capture, should apply. Inside one
holder's beliefs a change is real: the owner's "I eat meat again" ends the owner's
"vegetarian", and a page that updates ends what that page said.

A memory held by several people, Sam's and Tom's "blue", outlives one of them changing
their mind: Sam's support stops counting, Tom's keeps it current.

**Saying something, and what the assistant said.** Nobody's word removes another holder's
belief by rule: saying something records the speaker's belief, and adds it to what it
contradicts as evidence against, so the dispute is visible from either memory. The
assistant's messages are statements it made, not beliefs it holds, so there is nothing of
the assistant's to convince or overrule. Whether the assistant should ever hold beliefs,
and by what standard it would be convinced of one, is a later decision's. No belief, of
anyone's, is authority to act.

### 4. A placed proposal

> **Normative.** `MemoryUpdateProposal` gains an optional placement: for each stored memory
> its producer retrieved, the memory's id, the revision the producer read it at, and one
> relation; and, optionally, one open question on one of those memories that the proposal
> answers.

| Relation | The proposed memory, against the stored one |
| --- | --- |
| `restates` | Makes the same claim, whatever the wording |
| `contained` | States part of what the stored one states, and nothing it does not |
| `supports` | Makes a different claim that is evidence for the stored one |
| `weakens` | Makes a different claim that is evidence against the stored one, settling nothing |
| `recheck` | Bears on the stored one without being for or against it, and makes it worth checking |
| `no_longer_true` | Shows the stored one held and has stopped holding |
| `never_true` | Shows the stored one was never true |
| `claimed_too_much` | Is the narrower truth of a stored one that claimed more than holds |
| `independent` | Neither restates, supports, weakens nor changes it |

> **Normative.** The relation is one of the table's nine values, a closed set added to and
> never renamed. It is not `ConflictRelation`, and neither is read as the other.

> **Normative.** A placed proposal may name only memories its producer read, each at the
> revision it read. How the producer retrieves them is its own decision's.

> **Normative.** For a placed proposal, `MemoryIngestor` invokes no reconciler, and
> `MemoryPolicy` is consulted only for its admissibility floor and its rule on a
> confirmed proposal. On `DefaultMemoryPolicy` those are its rules 1 to 4; its rules 5 to
> 12 read no placed proposal.

> **Normative.** Where the policy's floor or its confirmation rule rules on a placed
> proposal, that ruling is final and the placement is not applied. Otherwise the writer
> applies the placement by §5.

> **Normative.** The writer reads every memory a placement names. Where any named memory's
> stored revision differs from the revision the placement records, or a named memory is no
> longer held, the writer refuses the whole proposal with nothing written, and its result
> says so.

> **Normative.** The writer computes every holder and standing it rules on from the stored
> records and the proposal's supports, and reads none from the placement.

A proposal with no placement is ruled as today, through the reconciler and every rule of
the policy. The observer's decision makes the observer's proposals placed; no other
producer writes a memory today.

### 5. The write a placement yields

| Relation to a stored memory | What the writer does to that memory |
| --- | --- |
| `restates` | Adds the proposal's supports to it, where §5:2 allows; otherwise nothing, and the proposal is installed beside it |
| `contained` | Where every holder of the proposal's backing supports already holds it, adds the proposal's supports to it as `for`, none backing it as worded; otherwise adds the backing supports to it as `for`, none backing it as worded, and the proposal is installed beside it |
| `supports` | Adds the proposal's backing supports to it as `for`, none backing it as worded |
| `weakens` | Adds the proposal's backing supports to it as `against` |
| `recheck` | Raises a `recheck` question on it, resting on the proposal's first backing support |
| `no_longer_true` | §3: within its holders' own beliefs, stops their supports, and where it retires, an end, closed at the about-when of the backing support whose stopping left it unbacked where that support carries one, and at the write's instant otherwise; from holders who hold none of it, `against` supports both ways and the proposal beside it |
| `never_true` | §3, as above; where it retires, a mark wrong |
| `claimed_too_much` | §3, as above; where it retires, a replace naming the proposed memory |
| `independent` | Nothing |

> **Normative.** The writer applies, to each memory a placement names, what the table's
> row for its relation says.

> **Normative.** A `restates` adds the proposal's supports to the stored memory only where
> adding them would not raise the stored memory's standing and the proposal carries no
> confirmation support. Otherwise the stored memory is left as it is and the proposal is
> installed beside it.

> **Normative.** The writer installs the proposed memory exactly where no `restates` added
> its supports to a stored memory and no `contained` added them to one its holders already
> hold, or where any retiring relation is present.

> **Normative.** Where the proposed memory is installed, each memory a retiring relation
> retired names it as successor, and it names each as a memory it replaces (ADR-0328
> §5:6).

> **Normative.** An answered question named by the placement is resolved by a resolve
> question citing the proposal's first backing support, whether or not the proposed memory
> is installed.

> **Normative.** Everything one placed proposal yields is written in one atomic write,
> conditional on the revision of every memory it changes (ADR-0219 §2).

> **Normative.** Every write the table names is an operation ADR-0328 §5 already defines,
> and every rule of ADR-0328 §4 binds the supports it adds: a support whose part the
> memory already carries changes nothing, and a confirmation support is added to no
> memory but the one it backs or one its own ingest retires (ADR-0328 §4:6).

**Why `restates` can install beside.** A restatement judged by a model and folded onto a
stored wording would add the new support as backing that wording, and the stored
memory's standing would rise to the new support's on the model's judgement that two
wordings say the same thing. That is the laundering ADR-0336 §3:3 refused. Where the
standing would not rise, as when the owner says again in other words what the owner
already said, the fold only dates the memory again, and a repeat makes no duplicate.
Where it would, the new memory stands at its own standing beside the old one, and store
maintenance may merge them later.

**Why `contained` writes no new memory for the same holder, and one for another.** Where
the owner says again part of what the owner said, the stored memory already states it,
and the new supports count as evidence for it without backing its whole wording, so its
standing does not move (ADR-0328 §6:2). Where Sam says "Ana lives in Lisbon" against the
owner's "Ana lives in Lisbon and teaches piano", Sam's belief is his own memory: folded
in, it would end with the owner's if the owner corrected the piano half, and Sam would
never have held the rest. Sam's support still counts as evidence for the owner's memory,
as a partial supporter, never as its holder. A retiring relation in the same placement
installs the proposal, so a retired memory always has its successor.

A compound memory is where `contained` is weakest: one held only inside "lives in Lisbon
and teaches piano" ends with it when half of it is corrected
([#3259](https://github.com/leonapivato/ai-assistant/issues/3259)). The observer's
decision frames one claim per memory, so the store holds few compounds. Splitting the
ones it holds is store maintenance's.

### 6. A memory that lapses

> **Normative.** A create may set the memory's validity end after the create's instant,
> where the support it cites carries an about-when naming that end.

> **Normative.** A memory past its validity end keeps its status and is not live (ADR-0328
> §11:2, ADR-0045 §6): reads that return live memories do not return it, and a projection
> of it shows the end.

> **Normative.** An end, a mark wrong or a replace whose about-when lies after its instant
> stays refused (ADR-0328 §5:10). Only a create sets a future end.

"Flying to Lisbon on the 5th" is created with its validity ending on the 6th, and drops
out of what planning is shown once that passes, with nothing written. A memory that is
true from now on carries no end.

### 7. Situation labels

> **Normative.** A memory carries situation labels: a tuple of entries, each a free-text
> label, the instant it was added and the writer that added it.

> **Normative.** A label says when or for what the memory matters, or what kind of
> statement the memory is. Its wording is its producer's.

> **Normative.** A memory carries at most a composition-root number of labels, and a label
> is at most a composition-root number of characters.

> **Normative.** The store embeds each label as it embeds a memory's wording.

> **Normative.** A label whose embedding lies within a composition-root distance of a label
> the memory already carries is not added, and its write says so.

> **Normative.** `MemoryWriter` gains a member that replaces a memory's labels whole,
> conditionally on the revision read, recording each new label's instant and writer. A
> label write is not an operation and changes nothing but the labels.

> **Normative.** A create may carry labels, written with it under §7:3 and §7:5.

> **Normative.** Labels change no standing, status, validity, support or operation, and
> nothing this decision adds ranks a search by them. A search over labels is a later
> decision's.

**Why a field of their own, not `topics`.** `topics` is ADR-0213's: canonical labels
compared exactly, strictly ordered, unioned on a fold. A situation label is matched by
meaning, carries who added it and when, and is reorganised by its writer, which none of
those rules fits. `topics` has no producer (ADR-0328 §3:6), so it retires (§10) rather
than serving two purposes.

### 8. Marks

> **Normative.** A memory carries marks: a set of members of one closed enumeration, added
> to and never renamed. This decision adds two members. `one_occasion`: the memory states a
> single occasion, such as one choice made once on a date. `assistant_statement`: what the
> memory states traces to the assistant's own words in a round's message, with nothing
> recorded behind them, which a person kept or
> took on.

> **Normative.** A mark is set by the memory's producer at its create, and changes later
> only by a decision that names how.

> **Normative.** The writer refuses a memory marked `assistant_statement` that carries no
> support pointing at a round's message.

> **Normative.** A memory marked `one_occasion` carries no validity end set at its create.

> **Normative.** Marks about how a person wants to be treated stay in the person-model
> store: ADR-0338's style marks and pin suggestions are unchanged, and this field holds
> marks about the memory itself.

A one-occasion memory is an ordinary memory: its wording dates it, and it stays true
that it happened. The mark lets recall and store maintenance find occasions by an exact
filter, where a label matched by meaning could miss one.

**Why `assistant_statement` is a mark and not computed.** A memory a person keeps from
what the assistant said is the person's: their "remember that" takes on the words shown,
so it backs the memory as worded and makes them its holder, which §3:5's guard needs. Code
then cannot tell from the supports alone that the assistant's words were all that stood
behind it, because the person's support looks like any statement of theirs. The producer,
which saw the parts, says so; code checks that the assistant's message is among the
supports. The memory still cites what it can: the message, where and when the assistant
said it. Every claim has a source, and here the source is that statement.

### 9. Whom a memory is about

> **Normative.** `about_person` keeps ADR-0100's meaning, a label as given, and gains a
> producer: the observer, as its decision says.

> **Normative.** `MemoryStore.search` gains an optional `about_person` filter that returns
> only memories whose `about_person` equals the given label, bound before the ranking cut
> as every eligibility predicate is (ADR-0128 §1).

> **Normative.** A memory whose `about_person` is `None` is read as the owner's, as
> ADR-0100 has it.

> **Normative.** A memory's placement may be narrowed by its producer's proposal at its
> create (ADR-0217 §4), and the observer's decision names the observer as such a
> producer. Nothing here widens what a proposal may do.

### 10. `topics` retires from the memory

> **Normative.** The memory carries no `topics`. ADR-0213 no longer governs a memory, and
> its rules for an episode stand as ADR-0239 and ADR-0285 leave them.

> **Normative.** A memory stored with topics carries each as a situation label after the
> upgrade (§13), added by `migration`.

### 11. Concurrent writes

> **Normative.** This decision adds no lock, queue or second writer. A placed proposal is
> made safe by the guards already in force: one observer run at a time (ADR-0329 §16:6),
> the conditional write (ADR-0219 §2), the refusal of a stale placement (§4:6), one atomic
> write per proposal (§5:6), and a support keyed by its part so a retry adds nothing
> twice (ADR-0328 §4:8).

Between the producer's retrieval and the write the producer may make a model call, so a
placement can go stale. The writer refuses it whole and the producer places again. Two
producers creating the same claim at once could leave a near-duplicate; none runs today,
and store maintenance would merge one.

### 12. What a reading surface shows

> **Normative.** Every projection of a memory ADR-0328 §15:1 names also carries its
> holders and partial supporters, its labels, its marks, and its validity end where it lies
> in the future.

> **Normative.** The single-memory projection ADR-0328 §15:2 names also carries each
> support's holder.

> **Normative.** Planning's label for a memory conveys its holders wherever they are not the
> owner alone, and its validity end where it lies in the future. The text is planning's.

> **Normative.** Every projection and planning's label convey a memory marked
> `assistant_statement` as what the assistant said, citing that message, where and when it
> was said, and the person who kept it, and never as "from a source" or as what the person
> said, whatever standing ADR-0328 §6 computes
> for it.

> **Normative.** A change to a shape the wire carries advances `PROTOCOL_VERSION` in that
> change (ADR-0124 §9).

### 13. The upgrade

> **Normative.** On open, the memory store upgrades every memory in place, with no model and
> nothing dropped (ADR-0326 §4:1): each support gains its holder by §2's table, from the
> record it points at as the store holds it, with a legacy support's holder unknown; each
> memory gains no labels but those §10:2 carries over, and no marks.

> **Normative.** A support whose episode no longer resolves gains the holder its origin
> alone determines where the table maps that origin to one holder, and unknown otherwise.

> **Normative.** The memory store's label advances, a file at the previous label is
> upgraded rather than refused, and the upgrading lane ships ADR-0326 §4:2's test over a
> file the previous release wrote and raises the memory store's `Store.shape` in
> `scripts/upgrade_stores.py` with a carry from the shape it replaces (ADR-0326 §7).

### 14. What the observer's decision decides

> **Normative.** This decision does not decide what the observer reads, how it retrieves
> the memories it places against, which model calls it makes, how it words a memory or
> its labels, how it decides a relation, or how it proposes whom a memory is about or its
> placement. The observer's decision decides each, and no lane builds one under this
> decision alone.

### 15. Delivery

> **Normative.** The implementation is one contract-surface lane under ADR-0137 §2: the
> types and protocols, `memory` (the writer's placed path, the label write, the search
> filter, the holder computation and the upgrade), the canonical `MemoryWriter` and
> `MemoryStore` fakes in `ai_assistant.testing`, the shared conformance suites, the
> projections and the wire, and their tests.

> **Normative.** That lane's tests include, each failing on a writer that implements only
> the others: Sam's `no_longer_true` against the owner's memory installs beside, stops
> nothing and adds an `against` support; the owner's against the owner's memory retires
> it; one of two holders withdrawing leaves the memory current; two holders backing one
> proposal each withdraw their own supports, and the memory both held is retired; a
> contradiction from another holder records `against` supports on both memories; a claimed
> author is never
> the same holder as an established one with the same identifier; a part saying what
> another person believes is held by its sender; two parts under one identifier are one
> holder; a partial supporter is not a holder; a `contained` from another holder installs
> beside; a memory left with only the assistant's statements backing it is retired; an `assistant_statement` memory without the assistant's message is
> refused, and one with it is shown citing that message;
> a `restates` that would raise standing installs beside; a `restates` at equal standing
> folds with no new memory; a `contained` adds supports without raising standing; a stale
> revision refuses the whole proposal; a create with a future validity end drops out of
> live reads after it; a near-duplicate label is refused; the `about_person` filter binds
> before the cut; and the upgrade assigns holders by §2's table.

### 16. Relationship to earlier decisions

Superseded in part; every clause the middle column does not name stands:

| Earlier decision | What it replaces | By |
| --- | --- | --- |
| ADR-0213 | Every clause, as it applies to a memory | §7, §10 |
| ADR-0328 | §3:1's field table, in the additions of labels and marks and the removal of `topics`; §3:6, as to `about_person`'s producer and `topics`; §4:1's support fields, in the addition of the holder; §5:10, for a create; §6:5, §11:5, §11:6 and §11:7, for a placed proposal; §11:9, as to the union of topics; §15:1, §15:2 and §15:5, in the additions alone; §15:4 and §15:5, for a memory marked `assistant_statement` | §2–§10, §12 |
| ADR-0336 | §2:1, §3:1–§3:3, §4:1, §5:1 and §7:1, for a placed proposal | §4, §5 |

## Consequences

**What gets easier.**
- A false claim from someone else can add only a belief they hold. It can never end,
  mark wrong or outrank what the owner said, because a holder changes only their own
  beliefs (§3).
- A forged forward, a screenshot or "the user agrees with me" never becomes the user's
  belief, because only an identity the channel establishes holds a person's belief (§2).
- The relation is judged once, by the producer that framed the memory, and the writer
  derives the write by rule. The reconciler's second model call goes for placed
  proposals.
- Plans lapse on their own (§6), and occasions can be found exactly (§8).
- Recall can prefer a holder by an exact filter, once usage asks for it, because holders
  are structured.

**What gets harder, and what this leaves.**
- **Usage now carries the ranking.** Planning sees beliefs from several holders and needs
  rules for choosing among them: by topic, role, recency and credibility. On a one-person
  hub nothing changes, because the owner is the only person holder and the existing
  ranking is usage's default. Recall should bring competing beliefs together, and every
  surface shows holders. These need design with the household.
- **More memories stand side by side.** A restatement that would raise standing, a claim
  from another holder, and a near-duplicate from a racing create all install beside.
  Store maintenance, a later decision, merges them.
- **Two write paths.** A proposal with no placement keeps the reconciler and every policy
  rule. No producer makes one once the observer's decision is built. A later decision may
  retire that path.
- **Labels are written before they are searched.** A label search is a later decision, of
  the store's search contract and recall.
- **Forgetting loses `topics`.** ADR-0213 came from the owner's direction that "the topic
  thing needs to exist for forgetting anyway". Forgetting stays undesigned and deferred,
  to be approached with care. It will likely draw on situation labels and the exact
  `about_person` filter in place of exact topic tags, and this decision rules nothing about
  it.
- **Person holders other than the owner** wait on a decision on identified people.
  Until then the person column of §2 names the owner alone.
- **The assistant keeps no memory of its own** until a decision on its standards of
  belief: independence, interest (a source never vouches for itself), directness, track
  record, proportion, recency, coherence, the person first on themselves, and humility.
  That decision, with store maintenance, is where earned opinions and credibility per
  source begin.

## Alternatives considered

- **A kind field** (state, event, plan, instruction). Rejected by the owner: memories
  straddle kinds, the validity window already bounds time, and marks and labels cover the
  rest without forcing one category.
- **One mixed label list**, structured and free entries together. Not chosen: an exact
  filter and a match by meaning are used differently and follow different rules, so a
  mixed list would need a kind tag per entry and is two fields in one.
- **Keeping the reconciler as a second judge.** Not chosen: it answers the question the
  producer already answered, with a narrower view, and the two can disagree. The safety
  it was kept for, a write never ending a fact on resemblance alone, is §3 and §5's.
- **A person's word withdrawing the assistant's belief by rule**, by anyone or by the
  subject and the owner alone. Withdrawn: an inference is a belief like any other, so it
  would change only by its holder's own judgement, and an `against` support keeps the
  dispute visible either way.
- **The assistant as a holder of beliefs, convinced by judgement.** Adopted during the walk
  and then withdrawn: once the assistant holds no beliefs, its messages are statements it
  made, and there is nothing of its own to convince. It returns, if ever, with the
  decision on the assistant's standards of belief.
- **A person as a kind apart from a source.** Not chosen: "Person is a type of source,
  no?" Every holder is the source of a claim; the kinds matter to usage, not to capture's
  rules.
- **A ranking across holders for retirement**, the owner above sources above inference.
  Withdrawn: that is usage's choice, and capture that applies it destroys a belief usage
  might need.
- **Wording another holder's claim as theirs**, "Sam says …". Not chosen: the holder on
  the support carries it, agreement across holders then reinforces one memory, and one
  holder changing their mind withdraws only their own backing. A source's report keeps
  ADR-0329 §9:8's wording until the outside-content rework.
- **The model as the holder of an untraced statement.** Withdrawn: a model's output
  depends on its whole context, the system prompt, the person's message and whatever it
  read, mixed with what it already knew, so no claim can be pinned on the model alone. The
  statement is the assistant's, and what was in its context stays one pointer away, in the
  episode its support points at.
- **Saying "no source".** Withdrawn by the owner: "make it not that there's no source.
  Instead, it should cite what it can." A kept statement of the assistant's cites the
  assistant's message.
- **Computing that a memory rests on the assistant's statement alone, from the supports.**
  Not chosen: a person's "remember that" backs the memory as worded, so the supports cannot
  show that nothing else stood behind it. The producer marks it (§8).
- **Links between related memories**, from the reconciler's `ADDS`. Withdrawn: stripped
  down it says "similar and not in conflict", which the search recomputes from
  embeddings with no model call.
