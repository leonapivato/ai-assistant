# 225. A transcript archive keeps the exchange as text, and nothing but the user reads it

- Status: Proposed
- Date: 2026-09-02

## Context

### Where this comes from

The owner ruled on 2026-09-02, recorded on #1843: **the archive is scoped —
transcript-only, user-searchable.** In the owner's words, *"an archive so that the
user can search through old conversations as a transcript only. The mechanism to
feed back into the assistant doesn't have to be made yet — I can just imagine this
being a tool call in the future."* The same ruling holds every retention *value*
where it is: no change to `episode_retention` until there is information
supporting a specific number, and renewal-on-retrieval parked with it.

So this ADR decides a store, its non-reachability, its deletion, and one user
surface. It decides no retention value of the working set, and it builds no path
from the archive back into a prompt.

### The horizon's justification is under measurement, and this is the worst-case net

ADR-0074 §7 justifies a finite episodic horizon by pointing past it: *"The
distillation that carries value past the horizon is leg 3's observation and leg
7's consolidation"*, and *"a finite window is what makes that claim expire when it
stops being true."* That argument assumes extraction happens once, at the right
time, well enough — and extraction is lossy and one-shot, so a better observer, an
additive lens or a new belief field improves what is understood about the *next*
month and can never revisit the previous year. #1843 states the case and #1886 is
measuring the premise.

The archive is what makes the horizon survivable if that premise turns out weak:
after this decision, reaching the horizon **evicts a turn from the working set**
rather than destroying it. Nothing about the working set changes — the same
horizon, the same read-time expiry, the same reclaim, the same retrieval, the same
prompts.

### What ADR-0074 §10 refused, and why this is not that

§10's declined entry is precise about its subject:

> **A separate verbatim transcript store, with episodes distilled from it.** §3.
> It duplicates Tier 1 content, splits retention and deletion across two stores
> with no transaction, and makes leg 2 depend on leg 3's distiller to produce
> anything citable.

What was refused is **transcript-as-primary**. This inverts it: episodes stay
primary, stay citable, and are written by capture exactly as they are today; the
archive derives from the same exchange and **nothing derives from the archive**.
Of §10's three objections, the third is dead — leg 3 shipped, and capture cites
nothing — and the first two are live and are answered in §5 and §6 rather than
noted.

§3's own third reason is broader than §10's entry and is the one this ADR has to
meet head-on: *"A second verbatim store duplicates Tier 1 content. The turn text
would exist twice, under two retention rules and two deletion surfaces with no
transaction between them."* Both halves are true of this design and both are
deliberate. The duplication is the price of the retroactivity, stated at §6 with
its size. The "two deletion surfaces with no transaction" is not accepted: §3 and
§5 together remove it, by giving the archive **the episode's own address** and a
destroy resolved inside the archive, so a conversation-scoped erasure needs no
enumeration of a second store and no ordering between them.

### Four claims in the batch's own framing that do not survive contact with `origin/main`

Each was checked in the tree before this ADR was written, and each changes a
decision below.

- **`EpisodicMemory.content` is not a transcript.** The batch describes what is
  archived as *"the exchange's text — both halves (`content` and the stored reply
  in `outcome`)"*. `content` is `_exchange_of`'s rendering in
  `orchestration/engine.py`: `"The user asked: {turn.goal.statement}"`, then
  `"The assistant's plan: {turn.plan.rationale}"` where a rationale exists, then
  a confirmation line and a tool line. The plan rationale is model prose. Copying
  `content` into the archive would archive the model's reasoning as though it were
  something a party to the conversation said, and would duplicate model prose into
  the one store nothing may read. §1 takes the user's own words instead.
- **`delete_about` is ratified and not implemented.** ADR-0101 §1 puts it on
  `MemoryStore`; it exists nowhere in `src/`, and ADR-0101 §7 defers its surface.
  §5's cascade therefore binds the lane that lands it rather than a command that
  exists.
- **There is no whole-memory export surface, and no `purge` command.** The three
  exports in `interfaces/cli.py` are `export-decisions`, `export-reads` and
  `export-invocations`; `MemoryStore.export` and `MemoryStore.purge_expired` have
  no user surface at all. ADR-0101 named this itself — *"delete has a surface,
  export has none"*. §7 therefore makes the archive's own read the export rather
  than pointing at one that does not exist.
- **There is no way to read a past conversation back today.** `Engine.conversation`
  returns a `ConversationDigest` — *"the count and span a deletion is about to
  destroy"* — and `assistant beliefs --kind episodic` enumerates live episodes,
  newest first, with no query. So the surface §7 decides is the first transcript
  read this system has ever had, not a second one.

### What is not in dispute, and is used as given

- **The namer rule.** #1844 states the line ADR-0208 was drawing: *"The namer may
  be data, or the user, or the model pointing outward — never the model pointing
  inward."* A user reading their own history is the user naming, which is why this
  surface is legal and why §12 defers the model-directed form.
- **ADR-0119 §7's fence is the precedent for non-reachability by construction**,
  and its own words about what the fence protects are used as given: *"The property
  being protected was never 'the pipeline may not touch the store'; it is 'the
  pipeline may not read a trace back', so the seam is cut at the walk and the
  clause says so."*
- **ADR-0074 §3's capture protocol**, §7's horizon and §8's deletion protocol are
  used exactly as they stand. This ADR adds a store to §8's sequence; it changes
  no clause of it.
- **ADR-0221 §5's three capture cases** partition every capture site by what user
  material the episode renders, and §1 below is stated over that partition rather
  than inventing a fourth.

### An honest statement of what this ADR is not allowed to settle

Retention values for episodes (the owner's ruling, above). Whether a belief whose
evidence expired renders differently — ADR-0072 §3's filed question, which §4
leaves exactly where it is. The raw-source archive and `Capture.source`, which are
milestone 21's (#1318) and #1845's. And the feed-back mechanism, which §12 defers
by name.

## Decision

### 1. What the archive holds: one entry per captured turn, the user's words and the assistant's

> **Normative.** The archive holds one **transcript entry** per captured
> conversation turn, and holds nothing else. Capture writes one, at the moment it
> records the turn; no other producer writes to the archive, and no episode that is
> not a captured conversation turn — a sensor's, a reader's, a harness's — is
> archived by this decision.

> **Normative.** An entry carries exactly: its **address** (§3), the instant the
> turn occurred, **what the user said**, **what the assistant said**, the turn's
> `ExchangeDisposition`, which is always present (§10), and — as **grouping fields,
> not the key** — the id of the conversation the turn belongs to and the turn's
> ordinal. It carries no other
> field, and in particular carries no embedding, no score, no band, no confidence,
> no provenance and no belief.

> **Normative.** **The entry is keyed by its address alone**, and a conversation is
> something an entry belongs *to* rather than something an entry is filed *under*.
> No implementation makes an entry's identity, storage or retrieval depend on it
> having a conversation, and a later ADR admitting a producer of episodes that
> belong to no conversation may widen the two grouping fields — making them
> optional, or adding a second grouping beside them — and supersedes no clause of
> this ADR by doing it (§15).

> **Normative.** **What the user said** is the user's own words on the pass that
> produced the turn, unrewritten and unrendered: the turn's goal statement where the
> pass carried a turn, the utterance where a routed pass threads one (ADR-0197 §10),
> and **absent** where the pass received no user words at all. The three cases are
> ADR-0221 §5's three capture cases and no other partition is introduced.

> **Normative.** On the resolution of a parked step — ADR-0221 §5's second case —
> the entry carries **no** user words. The utterance that parked was archived at its
> own address by the pass that parked, and repeating it here would render one
> sentence as though the user had said it twice.

> **Normative.** **What the assistant said** is the composed reply, whole, exactly
> as ADR-0221 §1 requires of `EpisodicMemory.outcome`: no prefix, no summary, no
> elision and no other lossy rendering. Absent where the pass produced no reply.

> **Normative.** The entry carries no part of `EpisodicMemory.content` beyond the
> user's own words: not the plan rationale, not the confirmation line, not the tool
> line. No implementation, setting or later lane writes a model-composed rationale
> into an archive entry.

> **Normative.** The value each of these fields carries is **handed to capture, not
> computed there**, threaded per call site exactly as `modality`,
> `supplied_withheld` and `derived_from_external` already are. Capture judges
> nothing (ADR-0074 §4) and derives no part of an entry from the rendering it is
> given.

**A transcript is what the two parties said, and that is why `content` is refused
rather than reused.** The tempting implementation is the cheap one: the store
already holds a canonical rendering of the exchange, so copy it. But `content` is a
rendering built for the *observer* and for lexical and vector retrieval — ADR-0005
§1's *"canonical text rendering"* — and it interleaves the model's own plan
rationale with the user's sentence. Archiving it would put model prose into the one
store nothing may read, for no reader who wants it, which is ADR-0004 §7's
minimisation rule failing on the store where it matters most. It would also make
the archive's answer to *"what did I actually say?"* a rendering the user has to
parse rather than a quotation.

**And it is the argument that settles when the write happens** (§2). The user's own
words exist as a value only at the capture point: `turn.goal.statement`, before
`_exchange_of` folds them into a rendering. At expiry there is no turn, no goal and
no utterance — only `content`, from which the user's sentence is recoverable, if at
all, by parsing a prefix this system is free to change. A copy-at-expiry archive is
therefore not merely later; it is a strictly worse artifact.

**The disposition is carried and the modality is not, and the asymmetry is
deliberate.** `ExchangeDisposition` is a closed vocabulary this system already
computes (ADR-0221 §2), and without it a turn that parked reads in the transcript
as a question nobody answered. Modality is a fact about *how* the words arrived,
and the record that states it is the episode, at the address the entry already
carries; putting `Capture` on a transcript entry would also make this store a
carrier for the two fields ADR-0221 §5 reserves for decisions this ADR may not
make (§11). §15 defers a modality of the entry's own with what fires it.

### 2. The write is at capture, and it lands between the index entry and the episode

> **Normative.** ADR-0074 §3's capture sequence gains one write and changes in no
> other respect. The order is: the conversation index entry is appended first, then
> the archive entry is written, then the episode is written, then §8's verification
> runs.

> **Normative.** The archive write **never fails a turn and never fails a capture**.
> A store failure writing it is logged and reported on the capture's own degraded
> outcome exactly as a failed episode write is (ADR-0074 §3, §9), the episode write
> proceeds, and nothing is retried.

> **Normative.** ADR-0074 §8's verification compensates the archive as well as the
> episode: capture re-reads the conversation after its writes and destroys **both**
> the episode and the archive entry at that address if the conversation is stamped
> deleted or gone.

> **Normative.** That verification runs whenever **either** write landed, the path
> on which the episode write failed included. Today capture returns its degraded
> report without verifying when the episode write raises, because on that path
> nothing had been written; with an archive entry already at the address, that path
> now has something to compensate and takes the verification.

> **Normative.** Capture writes at most one archive entry per outcome, at the
> address the store allocated for that turn (§3), and never retries. An entry
> already present at that address is a fault of the same class ADR-0074 §3 names for
> a colliding episode id — a broken ordinal invariant or a foreign producer in the
> reserved namespace — and is failed loudly rather than resolved.

**Written at capture rather than copied at expiry, and the reasons compound.**
Three of them, in the order they bind:

- **The user's words only exist at capture** (§1). This one is decisive on its own.
- **Expiry is a read-time predicate and the sweep is not guaranteed to run.**
  ADR-0007 §2 is explicit that a record past `expires_at` is *"treated as already
  forgotten"* whether or not `purge_expired` has run, precisely so *"the privacy
  guarantee does not depend on a background job"*. A copy-at-expiry archiver would
  have to read records the store has already undertaken to hide from `get`,
  `search` and `export` — which is a new `MemoryStore` operation, bought for one
  caller, whose whole purpose is to defeat the read-time guarantee. That is a
  contract change in the wrong direction and this ADR does not make it.
- **It would make the archive a function of when a sweep ran**, rather than of what
  happened. A deployment whose scheduler is down for a fortnight loses a fortnight
  of transcript permanently, and no user act could recover it.

**The archive write goes before the episode write because the archive is the copy
that must survive.** ADR-0074 §3 accepts a failed episode write on the ground that
*"A missing episode is the one outcome that loses nothing but the record"* — true
when the record's whole life is thirty days, and less true once there is a store
whose job is to still hold the exchange in three years. Ordering the archive last
would make the long-lived copy the one most exposed to the very failure §3 accepts.
Ordering it first costs nothing that §8 does not already handle: the index entry
still lands before either write, so the intent log still names the address before
anything exists at it, and a crash between the archive write and the episode write
leaves exactly the state §3 already ratifies and every reader already renders as a
gap — with the transcript intact.

**What this does not do is change ADR-0074 §3's degraded outcome.** A capture that
loses its episode is still degraded, is still reported, and is still not retried.
The archive makes the loss smaller; it does not make it disappear, and no
implementation reports a capture as undegraded because the archive entry landed.

### 3. The address is the captured episode's id, and it is stable

> **Normative.** A transcript entry's address **is the id of the episode it
> derives from**, whatever produced that episode. For the one producer this ADR
> admits, that is the value `ConversationStore.append` derived and returned on the
> turn (ADR-0074 §3). The archive mints no identifier, derives none, and predicts
> none; it is handed the episode's id and stores it.

> **Normative.** An address is **stable**: it never changes, it is never reissued,
> and it stays a valid name for its entry after the episode it names has expired,
> been reclaimed, or been destroyed. An address naming a destroyed entry resolves to
> nothing, and resolves to nothing for good.

> **Normative.** An address is a name and never a capability. Nothing in this ADR
> makes an address resolvable by any component the fence in §4 excludes, and holding
> one confers no read.

**Reusing the episode's id rather than minting a second identifier is the decision
that answers ADR-0074 §3's own objection to a second store.** That objection is
*"two retention rules and two deletion surfaces with no transaction between them"*.
With a shared address there is one namespace: a conversation-scoped erasure names a
conversation and a record-scoped one names an id, and each resolves inside the
archive without enumerating anything or ordering anything against a second store
(§5). A minted archive id would have reintroduced the whole of the objection —
a mapping to maintain, a mapping to delete, and a window in which the two disagree.

**Keyed by the episode and not by the conversation, which is a choice and not an
accident of what exists today.** ADR-0074 §3 already rules that *"every turn is an
episode, and not every episode is a turn"*, and that an episode belonging to no
conversation is *"the default shape rather than a permitted exception"* — there is
no `conversation_id` on the record to leave unset. An archive keyed on the
conversation would have contradicted that the moment a second producer of episodes
existed, and would have made the widening a supersession rather than an addition.
Keyed on the episode, the conversation is a grouping over addresses, `forget` and
`forget-conversation` are a lookup and a filter over one key rather than two
schemes, and a later producer costs this ADR nothing (§15).

**The property that makes this safe is already ratified and already
collision-free.** ADR-0074 §3 derives a captured episode's id from the
conversation's id and the store-allocated ordinal, in a namespace *"structurally
recognisable and reserved to captured conversation turns"*, so *"two captured
episodes cannot collide, by construction rather than by probability"*. Stability
follows from the same construction: the conversation id is a UUID4 this hub minted
and the ordinal is monotone, so no later turn can be handed an address a destroyed
entry once had.

**It is also the whole of what this ADR owes the future** (§12). A later pointer
naming a transcript entry names this string — which is the same string
`Provenance.evidence` already carries for that episode, so a mechanism that follows
a belief's citation and a mechanism that reaches a transcript are reaching one
address rather than two. §4 forbids that to happen automatically, today, in either
direction; §3 is what makes it cheap when it is decided deliberately.

### 4. What the archive is not: the never-list, and the three properties that enforce it

> **Normative.** No transcript entry is embedded. The archive holds no embedding of
> any kind, its store is constructed with **no `Embedder`**, and no implementation,
> setting or later lane gives it one.

> **Normative.** No transcript entry, and no text derived from one, is rendered into
> any prompt sent to any model — not the router's, not the planner's, not the
> composing stage's, not the observer's, not the reconciler's, and not a
> consolidator's.

> **Normative.** No transcript entry enters a turn's supply, in any group. It is
> not in ADR-0074 §5's tail, not in the belief composition ADR-0072 §5 orders, and
> not in ADR-0158's episodic supplement.

> **Normative.** No transcript entry is a citation target. ADR-0072 §3's rule that
> *"An evidence reference denotes the id of a record in the same store"* is
> unchanged and denotes a `MemoryStore` record still: an `Evidence` reference is
> never read as naming a transcript entry, no producer writes one intending to, and
> **no citation resolution reads the archive**. That an expired episode's address
> is also a live archive address is a property of §3's reuse and is not a fallback:
> what a belief whose cited episode has expired renders is unchanged by this
> decision, and remains ADR-0072 §3's open question and ADR-0073 §4's gate.

> **Normative.** The archive carries **no walk**. It is not observed, has no
> watermark, no cursor and no resumable enumeration for a producer, and no
> observation, consolidation or reconciliation pass reads it.

> **Normative.** No transcript entry's text is written to any log, evaluation trace,
> audit trail, source-read trail, routing trail, outbox or notification. A failure
> handling an entry names its address and never its text (ADR-0004 §5).

> **Normative.** Nothing in this ADR authorises egress. No archive text is sent to
> a model provider, to a designated integration seam, or anywhere off the device,
> and no lane cites this ADR toward a designation, a registration or a destination
> (ADR-0017 §1, ADR-0154 §2, ADR-0155 §1).

Three independent properties enforce that list, and none of them is a convention.

> **Normative.** **The package fence.** The archive is its own subsystem package,
> `ai_assistant.archive` (§10). An `import-linter` contract forbids every other
> package from importing it, `ai_assistant.app` alone excepted as the composition
> root, in the shape ADR-0119 §7 already uses for `ai_assistant.evaluation`. A
> violation fails the gate.

> **Normative.** **The turn-path fence.** No component of the turn path holds a
> seam carrying an archive **read**. The conversation loop, the retrieval stage, the
> context assembler, the planner, the composing stage, the observer, the reconciler,
> the router and every tool hold no archive seam at all. `ConversationLifecycle`
> holds the **writer** seam of §10 and nothing wider, so the one component that
> writes an entry cannot read one back. Only `AssistantEngine` holds the wide seam,
> and it reaches it from its user-facing and data-rights operations and from no
> operation on the turn path. A turn-path component that could read the archive does
> not type-check.

> **Normative.** **The absent embedder.** The archive's search is lexical by
> construction, over text the archive stores as text (§7). There is no vector column
> to populate and no embedder to reach, so "never embedded" is a property of the
> shape rather than a rule a later lane must remember.

**The fence is cut where the property is, which is ADR-0119 §7's own reasoning
applied to a different capability.** There the pipeline had to keep the purge and
lose the walk, so the seam was cut at the walk. Here the engine has to keep the
*read* — it is what serves the user's own surface — so the fence is cut one level
in: no **stage** holds it, and no turn-path operation calls it. That is checkable
by construction, and §13 requires the test that pins it.

**The citation clause is the one that would otherwise leak silently.** An archive
addressed by episode id is, by construction, a store in which every expired
citation resolves to something. Letting citation resolution fall through to it
would answer ADR-0072 §3's open question by accident, in the direction nobody
argued, and would put archived text into the prompts that render a warrant — which
is the whole never-list defeated by one convenience. So it is refused in terms, and
a lane that wants it needs the ADR that decides it.

### 5. Expiry evicts; only the user destroys, and destruction reaches the archive whole

> **Normative.** **Expiry is eviction and never destruction.** A captured episode
> reaching `episode_retention` — hidden at read time, or physically reclaimed by
> `purge_expired` — removes nothing from the archive. The reclaim ADR-0074 §7
> performs on an emptied conversation's index and record removes nothing from the
> archive either.

> **Normative.** **Destruction is a user act, and it reaches the archive whole.**
> Forgetting one record by id destroys the entry at that address, and forgetting a
> conversation destroys that conversation's entries, each in the same act and
> neither performed by halves.

> **Normative.** A **record-scoped** destruction discards the archive entry
> **before** it destroys the memory record, and it attempts that discard whether or
> not the store holds a live record at the id. So a failure between the two leaves a
> record the user can still forget rather than text they were told was gone, and a
> second attempt at the same id reaches the entry however the first one failed. No
> implementation short-circuits a forget on an absent memory record.

> **Normative.** A **conversation-scoped** destruction performs its archive discard
> inside ADR-0074 §8's reclaim, which is idempotent and re-runs — in the deleting
> call, at engine start, and later on the hub's schedule. §8's step 3 gains a third
> conjunct: the index and the record are dropped once step 2 has nothing left that
> resolves, **and the archive holds no entry for that conversation**, and the grace
> has passed. A failed archive discard therefore keeps the tombstone alive to be
> re-run rather than stranding a transcript behind a dropped index.

> **Normative.** A **subject erasure** cascades by an enumerate-then-erase-then-
> discard sequence, because ADR-0101 §1 gives `delete_about` the shape
> `async def delete_about(self, about_person: EncodableText) -> int` — it returns a
> count and names nothing. The stage holding both stores therefore reads the
> addresses first through ADR-0101 §1's scoped export,
> `export(about_person=…)`, erases through `delete_about`, and then discards each
> address it enumerated. No implementation infers a subject for an archive entry,
> and no entry carries a subject of its own for anything to match on.

> **Normative.** That sequence's residue is named rather than claimed away, and it
> is one class: a matched record the scoped export does not return, which by
> ADR-0007 §3 as amended by ADR-0045 §6 is an **expired-but-unpurged** one, and a
> matching record written between the export and the erasure. Neither entry is
> discarded by the cascade, both stay reachable through this section's address- and
> conversation-scoped destroys, and a surface offering the operation states its
> reach under ADR-0101 §6 exactly as that section requires. What would close it is
> named: an implementation of `delete_about` that returns the ids it destroyed
> rather than their number. This ADR does not make that change to another ADR's
> contract, and no lane cites this section as authority to.

> **Normative.** A whole-store erasure erases the archive in the same act
> (`MemoryStore.clear`, ADR-0007 §4), when one gets a surface.

> **Normative.** The archive's own destroy operations are **by address** and **by
> conversation**, each resolved inside the archive against its own entries. Neither
> requires the conversation index, the conversation record, or the memory record to
> still exist, and neither enumerates a second store.

> **Normative.** Both destroys are **idempotent** and destroy what they match or
> nothing: an address with no entry is a no-op, and a conversation with no entries
> is a no-op returning zero.

> **Normative.** A surface offering the archive's conversation-scoped destroy obeys
> ADR-0073 §5's show-then-confirm at the unit the user thinks in, exactly as
> `forget-conversation` does, and states what will be destroyed before consent is
> taken.

> **Normative.** No lane ships a whole-store erasure surface, or a whole-memory
> export surface, that reaches the memory store and not the archive. Each is
> shipped for both stores in one change or for neither. (At-rest encryption carries
> the same obligation and is stated once, in §9.)

**Eviction versus destruction is the whole design, and it is one clause because
conflating them is the failure mode.** Today one mechanism does both: a turn
reaches the horizon and the text is gone, and a user says "forget that" and the
text is gone. After this ADR the horizon governs the *working set* — what is
retrieved, what is observed, what reaches a prompt, what an id resolves to — and
destruction governs the *text*. The owner's ruling is exactly this and no more:
retention values stay where they are, and what changes is what reaching them means.

**Both orderings put the archive first, and one rule chooses both.** On the write
the archive goes before the episode (§2); on a destruction it goes before the
record. The rule is not "archive first" for its own sake — it is that **the residue
of a partial failure must be the one the user can still reach and destroy.** A crash
mid-capture leaves an episode missing, which ADR-0074 §3 already ratifies and which
the horizon would have taken anyway. A crash mid-destruction leaves a *record*
present, which `forget` destroys on the next attempt. The order that fails the other
way leaves retained text after a deletion the user was told succeeded, and that is
the one residue ADR-0004 §6 cannot tolerate. This is ADR-0074 §8's own third
mitigation — *"the residue is visible and destroyable, not invisible"* — used as a
design rule rather than as a consolation.

**The archive's own destroy is what closes the hole the reclaim would otherwise
open.** ADR-0074 §7 reclaims a conversation's index and record once it has no live
turns and has been idle for the horizon. After that, `forget-conversation` on that
id refuses it as unknown — correctly, because there is nothing left to stamp. If
the cascade had been stated as "delete what the index names", a user whose
conversation had been reclaimed would be able to *read* their transcript and unable
to *destroy* it, which is ADR-0004 §6's right made conditional on a sweep. Keying
the destroy to the conversation id inside the archive removes that entirely: the
scope the user names is the scope the archive resolves, forever.

**What remains of ADR-0074 §8's window, stated rather than claimed away.** §8
accepts one residual: an episode that commits and whose process dies before its own
verification, on a conversation whose tombstone has already been reclaimed. The
archive is written inside the same capture, under the same stamp-refuses-appends
rule and the same verification, so the window is the same conjunction of failures
and is not widened in *reach*. It is widened in *content*: what an orphan holds is
now text rather than §8's *"ordinals, timestamps and episode ids — no content"*.
That is stated here rather than buried, and §8's own third mitigation carries: the
residue is visible and destroyable, because the archive's search returns it and the
archive's destroy-by-address reaches it, so what is lost is the automatic sweep and
not the user's reach.

**The subject erasure is the hardest of the four to state, and the sequence above is
what the ratified contract actually admits.** The tempting clause — "it destroys the
entries at the addresses it destroyed" — is unimplementable against
`delete_about`'s ratified shape, which returns an `int`. Reversing the order does
not help either: erase first and the addresses are gone. So the enumeration comes
first, through the scoped `export` ADR-0101 §1 adds in the same breath as
`delete_about`, and the discard follows the erasure so that no entry is destroyed
for a record the erasure did not in fact reach.

**And the whole of it is currently unreachable, which is worth stating so nobody
implements a phantom.** Capture stamps no `about_person`:
`ConversationLifecycle._episode` builds its `EpisodicMemory` with no such argument,
so the field takes `MemoryBase`'s `None` default and ADR-0101 §2's query matches no
captured episode at all. Every clause above therefore binds a path that today
destroys nothing — and is written now, in the ADR that creates the second store,
because retrofitting a cascade into a populated archive is the expensive version.

**The limit is ADR-0101 §6's, inherited exactly.** A subject erasure reaches only
records that *state* a matching subject, and an archived transcript that names a
person in its words is not reached, whatever the words say. ADR-0100 §4's
prohibition on inferring a subject applies to an archive entry with at least as much
force as to a record: nothing here authorises reading an entry's text to decide whom
it is about, and there is no field on an entry for a match to be made against.

### 6. Retention and bounds of its own, and the honest size story

> **Normative.** The archive's retention is its **own** setting,
> `transcript_archive_retention: timedelta | None` on `core.config.Settings`,
> **defaulting to `None`**, where `None` means *keep forever* and a finite duration
> means *evict entries older than that*. It is read from nowhere else: no
> implementation, setting or later lane derives it from `episode_retention`, and a
> change to `episode_retention` moves nothing in the archive.

> **Normative.** Whether the archive is written at all is a second setting,
> `transcript_archive_enabled: bool`, defaulting to `True`. Turning it off stops the
> write and destroys nothing: entries already held stay, stay searchable and stay
> destroyable, so a configuration change is never a silent deletion.

> **Normative.** This ADR sets no size or count cap on the archive. ADR-0007 §5's
> deferral of eviction policy is inherited whole and is not answered here.

> **Normative.** The archive's read surface reports the archive's current entry
> count and stored size, without being asked, so the cap's trigger is a figure
> somebody has rather than one nobody ever produces. The seam that supplies it is
> `TranscriptArchive.size` (§10), and it reads no entry.

**The `None` default is the deliberate opposite of ADR-0074 §7's, and the reason it
does not contradict §7 is that §7's argument is about a different store.** §7
requires a finite default for `episode_retention` because an unbounded one *"would
ship an ever-growing Tier-1 log of everything the user has ever typed"* inside the
store the pipeline retrieves from and the observer mines. Every limb of that
argument is about the read path and the growth of what a model sees. The archive is
in neither: nothing retrieves it, nothing observes it, nothing reads it into a
prompt (§4), and its growth is invisible to every model. What is left of §7's worry
is the at-rest one, which §9 answers in its own terms rather than by inheriting a
horizon.

**And a finite default here would reintroduce exactly the loss the archive exists
to remove**, at a number nobody can argue for. #1843 records that the 30-day figure
itself *"was never argued"* — ADR-0074 §7 says so in terms: *"The exact default
duration is the lane's; only its finiteness is ratified."* Inventing a second
unargued number, and then defending a permanent record whose default horizon is a
guess, is worse than declining to invent one. The user may set one; the system does
not choose one on their behalf.

**Two settings rather than one, because one field cannot spell both answers.**
"How long" and "whether at all" are different questions, and the durations in
`core/config.py` are validated `gt=timedelta(0)`, so there is no duration that
spells "off". Collapsing them would mean either a zero duration — the value ADR-0074
§8 calls out as breaking its own protocol — or reading `None` as "off", which is
the mirror image of the mistake §7 warns about for `confirmation_ttl`: the same
spelling meaning "keep forever" in one field and "keep nothing" in another.

**The honest size story, shown as arithmetic rather than asserted.** A transcript
entry is the user's sentence plus the composed reply. On the shapes this system
produces today that is of the order of 1–2 KiB of text; a lexical index over it
costs roughly as much again, so call an entry 3–4 KiB stored. At thirty turns a day
that is about 40 MiB a year, and at two hundred turns a day about 250 MiB a year.
The measured volume today is far below either — #1845 records 52 episodes on the
live hub on 2026-08-30. These are estimates and are labelled as such, which is
precisely why the surface is obliged to report the real figure: #1843's own reading
of ADR-0162 §5 is that a trigger with no instrument never fires — pilot 5 ran, closed
and *"reported no store-growth figures"*, leaving that trigger resting on a
deployment becoming unusable. This ADR declines to repeat that. The cap stays
deferred, and the number that would fire it is on the screen every time the user
looks.

### 7. Search and reading: lexical, bounded, and the user's alone

> **Normative.** The archive answers exactly four reads **over its entries**: a
> **lexical search**; an **ordered read of one conversation's** entries; a **read of
> one entry by address**; and an **unfiltered enumeration** of every entry it holds.
> It answers no other, and offers no relevance model, no ranking by similarity and
> no vector search. §6's size report is a read over the store rather than over its
> entries, and is the only operation beside these four.

> **Normative.** The search is lexical over the text the archive stores. Whether it
> is served by a full-text index or by a scan is the implementing lane's; the
> matching predicate is not, and the conformance suite pins the predicate rather
> than the mechanism.

> **Normative.** The predicate is a **case-insensitive substring match**, evaluated
> separately over an entry's `asked` and over its `replied`, never across the two.
> Both sides are normalised to Unicode NFC and then case-folded under **full**
> Unicode case folding — `str.casefold`'s semantics, which fold `ß` to `ss`, and not
> simple case folding, which does not — and the entry matches where the folded,
> normalised query occurs as a contiguous run in either folded, normalised field.

> **Normative.** Nothing else is applied: no stemming, no lemmatisation, no
> stop-word removal, no accent stripping beyond what NFC performs, no fuzzy or
> edit-distance matching, and no minimum query length. An implementation whose index
> cannot answer this predicate is not a conforming implementation, and the predicate
> is not relaxed to fit one.

> **Normative.** The three **enumerating** reads — the search, a conversation's
> entries, and the unfiltered enumeration — are each bounded by a caller-supplied
> limit and return a page, never an unbounded result set; a limit of zero or below
> is refused with a `ValueError`, as ADR-0114 §6 refuses one and for the same
> reason. The **addressed** read names one entry and is bounded by that: it takes no
> limit, and there is no limit on it to refuse.

> **Normative.** Result order is **total and deterministic**, and entries come back
> newest first: by the instant the turn occurred, descending, and by the address for
> two entries sharing an instant. A conversation's own read is in **ordinal order**,
> because a transcript's order is the order it was said in.

> **Normative.** A **search** result carries each hit's address, its conversation,
> its instant, and a bounded excerpt of the matching text — never an entry's text
> beyond that bound, and never both halves of an entry in full where either exceeds
> it. Reading an entry whole is a second, addressed act. Where an entry's own text
> is at or below the bound the excerpt may be the whole of it, which is what a
> bound means rather than an exception to it. The other three reads return entries
> **whole**, and elide, truncate and summarise nothing.

> **Normative.** An excerpt is at most **512 bytes of UTF-8**. Where the text it is
> taken from exceeds that, it is truncated at a codepoint boundary — so the encoded
> result never exceeds the bound and never splits a codepoint — and `elided` is
> `True`. Where it does not, the excerpt is that text and `elided` is `False`.
> Which window of the entry the excerpt is taken from is the implementing lane's;
> the bound is not. The response is therefore bounded by the
> caller's `limit` times that figure plus the fixed fields, and a conformance suite
> asserts the bound over an entry far larger than it.

> **Normative.** The unfiltered enumeration **is** the archive's export: every
> entry, whole, paged, in the total order above, and it satisfies ADR-0004 §6's
> export right for the archive. Any surface that later exports the memory store
> exports the archive beside it (§5).

**The predicate is named because two conforming implementations would otherwise
diverge on ordinary input.** `Straße` and a query of `STRASSE` match under
`str.casefold`, which folds `ß` to `ss`, and do not match under a tokenizer that
lower-cases ASCII only; a composed `é` and a decomposed one differ byte for byte and
are one string under NFC. Either divergence is invisible in a test suite written
against one implementation and immediately visible to a user who switches backends —
which is ADR-0074 §9.3's rule that a bounded default with no figure is two
conforming implementations diverging, applied to a predicate instead of a number,
and the same standard §7 already applies to the excerpt bound. Ordering is already
total and recency-based (above), so no ranking function is left free to diverge
either.

**Lexical rather than semantic, and it is a property rather than a preference.**
The never-list forbids an embedding (§4), so a vector search is not available even
in principle — and it is not wanted: the question a transcript search answers is
*"where did I say that word?"*, which is exactly the class of query #1844 identifies
vectors as weakest on — *"vectors are weakest on rare tokens, which is the class of
question ('which lender', a model number, a proper name)"*. The store has no
full-text index of any kind today, which is what makes the archive the natural home
for one: it is a new store, so it can carry an index without touching
`MemoryStore.search` and without the signature change #1844 notes that would take.

**Show-a-hit-then-read-the-entry rather than rendering everything.** A transcript
search over a year of conversation can match hundreds of turns, and rendering each
one whole makes the result unreadable and the bound meaningless. Splitting it makes
the address load-bearing in the surface the user actually touches, which is the
cheapest possible way for §3's stability to be exercised rather than asserted.

**The excerpt's figure is named here rather than left as "bounded", and ADR-0094 §8
is the authority for naming it.** That section requires a bound to be *"named in the
deciding ADR of the producer that needs them"*, because a bound with no figure is
two conforming implementations diverging (ADR-0074 §9.3). "Bounded" alone would have
admitted an implementation returning an entry's whole text minus one byte — bounded
in the letter, unbounded in the response — and would have left a scan-backed
implementation and an index-backed one with no shared assertion to conform to. The
figure is in bytes rather than characters because what it bounds is a response that
crosses the local API, and the truncation is stated at a codepoint boundary because
a byte bound applied to UTF-8 without that clause produces invalid text.

**The export is a read rather than a fourth artifact, and that is not a shortcut.**
ADR-0004 §6 requires that the user can view, export and delete. For a store that
holds text and nothing else, a paged, ordered, unfiltered read of every entry *is* a
portable snapshot of everything it holds; inventing a second serialisation would be
a second thing to keep correct for no information the first does not carry. This also makes the
archive the first Tier-1 store whose export exists on day one rather than
deferred — the gap ADR-0101 names for the memory store is not inherited here.

### 8. The surfaces, and the channel posture ADR-0199 §3 obliges this ADR to state

> **Normative.** The archive's reads are reachable **only** on an operation whose
> output channel's audience is **bounded** (ADR-0199 §1). No archive text is
> available on a channel of unbounded audience — not in a reply, not in a delivery,
> not in a deflection, not in any rendering of a search result. There is no setting,
> user act or grant that admits it, and admitting one takes an ADR that supersedes
> this clause.

> **Normative.** The archive's reads and destroys live on their **own** command,
> distinct from `beliefs` and from `conversations`, and never as a mode of either. No surface
> presents a transcript entry as a belief, as something the assistant holds, or as
> evidence for anything.

> **Normative.** A surface rendering archive content states, without being asked,
> that what it shows is a record of what was said and not what the assistant
> believes or retrieves.

> **Normative.** The CLI carries the surface first. A gateway page is permitted and
> is not required by this decision; where one ships it offers the same four reads
> and the same two destroys and adds no fifth.

**This section exists because ADR-0199 §3 requires it to.** That clause is explicit:
*"An ADR admitting a new source, a new facet, a new notification producer, or any
other producer of content that can reach an output channel states the posture of
what it produces on a channel of unbounded audience, in its own text. It may not
settle that question by silence, and until it does, what that producer produces is
withheld from such a channel."* The posture stated here is the strongest available
and it is not a default falling through — it is decided, and it is decided for a
reason the mechanism forces.

**The reason is that the withholding cannot be evaluated over a transcript at all.**
ADR-0199 §3 withholds *"any record whose `MemoryBase.about_person` is stated"* from
an unbounded channel, and calls that *"the highest-value withholding available and
the cheapest to enforce"* precisely because it is a field read with no inference in
it. A transcript entry has no such field, carries no band and no provenance, and
holds free text in which a third party may be named anywhere. Deciding whether a
transcript is speakable would therefore mean inspecting the words — which ADR-0199
§2 forbids in terms, deciding a class *"from recorded origin, never by inspecting
the words"* — or inferring a subject, which ADR-0100 §4 forbids. There is no third
option, so there is no way for archive content to be placed as speakable, and the
honest form of that is a clause rather than a silence. #1843 points at the same
observation from the other side, in #1842 §16.1's `about_person` blindness.

**And it is what makes gate 2 true rather than aspirational** (§9): a surface only
the user is looking at is what makes "the explicit act is the whole authorisation"
a statement about who can hear the answer, and not only about who asked.

### 9. The five security gates on #1843, one by one

The design note's condition was that the mechanism is good and *"whether it ships
depends on how sure we can be about its security"*, and it named five things the
argument had to cover. Each is answered in its own terms.

**Gate 1 — non-reachability, structurally, not by convention.** §4. Three
independent properties, each mechanical: an `import-linter` contract on the model
ADR-0119 §7 already runs for `ai_assistant.evaluation`, so a pipeline package that
imports the archive fails the gate; a construction rule under which no component of
the turn path holds a seam carrying a *read* — capture holds the writer and nothing
wider — so a component that could read one does not type-check; and the absence of
an embedder, so there is nothing to embed with. #1843 named
ADR-0119 §7 as *"probably the right shape"*, and it is — with one difference stated
rather than glossed: there the pipeline was forbidden the read outright, and here
the engine must keep it, because the read serves the user's own surface. So the
fence is cut at the read, exactly as ADR-0119 §7 cut its own at the walk, and §13
requires the representative-input test that pins it — a distinctive span archived, a turn run, and the span found in
no prompt.

**Gate 2 — the explicit act is the whole authorisation.** §7 and §8. Nothing reads
the archive on a turn, so there is no lure, no budget pressure and no injection
surface: the archive cannot influence what the assistant says, because the assistant
never sees it. What the user chooses to read is theirs, on a channel only they are
on. This is the ratified line and not a new one — #1844 states it as *"The namer may
be data, or the user, or the model pointing outward — never the model pointing
inward"*, and names *"why a user hand-back (#1843) is legal"* as one of the four
cases it covers. §12 keeps it that way by deferring the model-directed form rather
than half-building it.

**Gate 3 — deletion atomic across both stores.** §5. The design note asked for this
to be *solved* rather than noted, and the solution is the shared address (§3): the
archive resolves both deletion scopes against its own entries, so there is no
enumeration to lose, no ordering to get wrong and no mapping to fall out of step.
The residual is ADR-0074 §8's existing conjunction of failures, not widened in
reach, honestly widened in content, and reachable through the archive's own destroy.
Two properties the two-store objection assumed are simply absent here: there is no
second identifier, and there is no scope that resolves in one store and not the
other. What is *not* claimed is atomicity under a process death across three stores;
ADR-0074 §8 declined to claim it across two, named what would close it — leg 5's
transactional posture across the local stores — and that remains the answer.

**Gate 4 — at-rest exposure doubles.** This is the gate this ADR cannot close, and
saying so is the answer. ADR-0004 §4's baseline is `0600` plus assumed OS full-disk
encryption, with application-level encryption *"off by default"* — and it is not
merely off, it is **unimplemented**: `core/config.py` carries no encryption setting
at all. So the archive ships at the same baseline as the memory store, holding the
same class of content for longer, and #1843's reading is upheld rather than
answered: *"A full verbatim archive may be the first store for which that default
is not good enough — which would be a finding about ADR-0004 §4, not about this
store."*

What this ADR does about it is the one thing it can do without deciding a question
ADR-0004 owns:

> **Normative.** No lane ships application-level encryption at rest for the memory
> store without covering the archive in the same change, and none ships it for the
> archive alone. An archive protected more weakly than the store it derives from is
> a downgrade the user did not choose; one protected more strongly is a claim the
> memory store's own content does not support.

> **Normative.** The archive's database file is created with owner-only permissions
> (`0600`) in `Settings.data_dir`, as ADR-0004 §4 requires of the memory database.

And the mitigation that is real today is the one the user already has: the archive
can be turned off (§6), and what it holds can be destroyed at any scope (§5).

**Gate 5 — disclosure, and a spoken channel must not reach it.** §8, in terms, with
the mechanism-level reason: the withholding ADR-0199 §3 performs is a field read
over records, and a transcript entry has no field to read. ADR-0210's subtraction is
untouched — it operates over a turn's supply, and no archive entry is ever in one
(§4) — so there is nothing here for it to range over and nothing it must be widened
to cover. The hand-back case the design note worried about, *"a user act with a
consequence they may not have modelled"*, is not reachable at all until §12's
mechanism is decided, and this ADR decides none of it.

### 10. The contract surface owed, and why the archive is its own subsystem

> **Normative.** `core/protocols.py` gains **two** Protocols, and neither inherits
> the other. `TranscriptArchiveWriter` carries §2's append and the discard of one
> entry by address that §2's compensation performs, and carries no read.
> `TranscriptArchive` carries that same address-scoped discard, §5's
> conversation-scoped destroy, §7's four reads and §6's size report — and **no
> append**. One concrete class satisfies both structurally, and the composition root
> hands each holder exactly the seam it is entitled to (§4).

> **Normative.** Every site that writes to the archive **declares** its seam as a
> `TranscriptArchiveWriter`, as a required constructor argument with no default. A
> composition that omits it does not type-check, and the holder cannot call a read:
> a read on a value of that declared type fails `mypy`, whatever object was passed.

> **Normative.** No holder of `TranscriptArchive` may write to the archive. The
> Protocol carries no `append`, and the engine acquires none: no lane adds one to
> it, and no lane reaches the concrete class to get one (§4's package fence). §1's
> "no other producer writes to the archive" is therefore a property of the seam the
> engine holds and not only a rule it is asked to keep.

> **Normative.** What the composition root *passes* is still the root's discipline.
> A value declared `TranscriptArchive` does not satisfy `TranscriptArchiveWriter` —
> it has no `append` — so handing the engine's seam to the write site fails `mypy`;
> what still type-checks is handing the **concrete** archive, which satisfies both.
> `app/` passes the seam each collaborator is entitled to, and lane B's tests assert
> the wiring it performs. No clause of this ADR is read as claiming a type checker
> rejects the concrete object at either parameter.

> **Normative.** `core/types.py` gains three frozen pydantic models —
> `TranscriptEntry`, `TranscriptHit` and `TranscriptArchiveSize` — carrying exactly
> the fields ratified below **as this ADR ships them** and no other. A later ADR may
> widen any of them by an additive, defaulted field, as §1's grouping clause and §11
> each contemplate; no implementation, setting or lane widens one without an ADR.

> **Normative.** The shapes below are the ratified surface. Docstrings are owed on
> the real `core/protocols.py` and are not reproduced here, which is ADR-0101 §1's
> move and its reason: what each must state is settled by the clauses of this ADR
> and by nothing outside them (ADR-0089 §3).

```python
# core/types.py — all three frozen, all three additive-only

class TranscriptEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    address: Identifier                     # §3: the episode's own id
    conversation_id: Identifier             # §1: a grouping, not the key
    ordinal: int = Field(ge=FIRST_TURN_ORDINAL, lt=2**63)   # §1: ConversationTurn's own domain
    occurred_at: UtcInstant
    asked: EncodableText | None             # §1: the user's own words; None where none
    replied: EncodableText | None           # §1: the composed reply, whole; None where none
    disposition: ExchangeDisposition        # §1: required; capture always has one

class TranscriptHit(BaseModel):
    model_config = ConfigDict(frozen=True)

    address: Identifier
    conversation_id: Identifier
    occurred_at: UtcInstant
    excerpt: EncodableText                  # §7: at most the excerpt bound
    elided: bool                            # §7: True where the bound truncated it

class TranscriptArchiveSize(BaseModel):
    model_config = ConfigDict(frozen=True)

    entries: int                            # §6: what the surface reports, unasked
    stored_bytes: int


# core/protocols.py — narrow, then wide

class TranscriptArchiveWriter(Protocol):
    async def append(self, entry: TranscriptEntry) -> None: ...
    async def discard(self, address: Identifier) -> bool: ...

class TranscriptArchive(Protocol):          # NOT a subclass of the writer: no append
    async def discard(self, address: Identifier) -> bool: ...
    async def discard_conversation(self, conversation_id: Identifier) -> int: ...
    async def search(                       # query is NEVER normalised: §7's predicate
        self, query: NonBlankEncodableText, *, limit: int = 20, offset: int = 0
    ) -> list[TranscriptHit]: ...
    async def conversation(
        self, conversation_id: Identifier, *, limit: int = 50, offset: int = 0
    ) -> list[TranscriptEntry]: ...
    async def entry(self, address: Identifier) -> TranscriptEntry | None: ...
    async def entries(self, *, limit: int = 50, offset: int = 0) -> list[TranscriptEntry]: ...
    async def size(self) -> TranscriptArchiveSize: ...
```

> **Normative.** `append` raises on a store failure and never swallows one; §2 is
> what decides that capture *degrades* rather than propagates, and it decides it at
> the caller. `discard` returns whether an entry was removed; `discard_conversation`
> returns how many were. Every operation raises a single archive error class on a
> backend failure, as ADR-0101 §4's `MemoryStoreError` clause does for its own.

> **Normative.** A `limit` of zero or below is refused with `ValueError` on the
> three reads that take one (§7), and a negative `offset` is refused the same way.
> `entry` takes neither. A blank or whitespace-only `query`, `address` or
> `conversation_id` is refused with `ValueError` on every operation that takes one,
> and is never read as "everything" — ADR-0101 §1's own rule for a blank label.

> **Normative.** `query` is typed `NonBlankEncodableText` and not `Identifier`, and
> the difference is load-bearing: `Identifier` *strips* the value it accepts, which
> would rewrite the user's search text before §7's predicate ever saw it and would
> make `" hello"` and `"hello"` one query. An id may be stripped and a query may
> not. No implementation, setting or later lane trims, collapses or otherwise
> normalises a query beyond §7's NFC and case folding.

> **Normative.** `TranscriptEntry.disposition` is **required** and carries no
> `None`. The one production caller of `ConversationLifecycle.capture` computes a
> member on every path — `_outcome_of` and `_routed_outcome_of` are total over their
> vocabularies — so an optional field here would be a `None`-only slot with no
> producer, which ADR-0073 §4's standing test refuses and which would recreate for a
> parked turn exactly the ambiguity §1 carries the field to prevent. A caller that
> supplies no disposition is recording an exchange this system did not drive, and
> **writes no archive entry**: the archive holds what this system's own capture
> recorded.

> **Normative.** `TranscriptEntry.ordinal` carries `ConversationTurn.ordinal`'s own
> domain — `[FIRST_TURN_ORDINAL, 2**63)`, the range `ConversationStore`'s own
> refusals are stated over — and a value outside it is refused at validation. The
> archive does not restate that domain in its own words or its own constant, and a
> later change to `ConversationTurn`'s domain carries here without an edit.

> **Normative.** Neither Protocol carries a walk, a cursor, a resumable position, an
> embedder, a subject axis, or any operation this ADR has not named. ADR-0101 §9's
> rule that a destructive operation is never given an optional scope whose absent
> value widens what it destroys binds both destroys here: `discard` and
> `discard_conversation` each take a **required, positional** argument, and no
> spelling of either means "everything".

> **Normative.** The archive is a new subsystem package, `ai_assistant.archive`,
> which depends on `ai_assistant.core` and on nothing else in `ai_assistant`. The
> implementing lane adds it to `CLAUDE.md`'s architecture map, in the form the map
> already uses for the packages nothing imports.

> **Normative.** Under golden rule 5 and ADR-0015 §5 this ADR is ratified and merged
> as its own PR before anything implements against it, and it is reviewed by both
> the adversarial and the architecture lens (ADR-0015 §1).

**Two Protocols rather than one, because the write has a different holder from the
read, and that is ADR-0119 §7's test rather than a preference.** That ADR split
`TraceSink`, `TraceRetention` and `TraceStore` because three capabilities had three
different holders, and its own words say what the split buys: *"what you cannot
reach, you cannot misuse"*. The same test applied here returns two rather than one.
The write does not happen in `AssistantEngine`: §2 puts it between the index append
and the episode write, both of which are inside `ConversationLifecycle.capture`, and
moving it out would split one sequence across two objects and break the single clock
reading the append and the episode already share. So capture is a genuine second
holder — and a single wide Protocol handed to it would give a turn-path collaborator
all four reads, defeating §4's fence in the same breath that states it. The narrow
seam is therefore bought against a specific failure and not for symmetry.

**Neither Protocol inherits the other, and that is the decision rather than a
formatting choice.** The obvious shape is a wide face that *is* the narrow one plus
more, which is what `InvocationLedger(InvocationCompleter, Protocol)` does. It is
wrong here, and in a way that only shows up when the capability is asked what it
grants: a wide seam inheriting the writer would hand `AssistantEngine` an `append`,
and §1 reserves writing to capture. A future engine helper could then write to the
archive without changing a Protocol, without crossing an import boundary, and
without anybody noticing — the capability split defeated by the convenience that
looked like tidiness. So the two faces overlap in the one operation both holders
genuinely perform, the address-scoped discard, and in nothing else.

**What each seam buys, stated without over-claiming.** The holder cannot call what
its declared type does not carry: `ConversationLifecycle` declares a
`TranscriptArchiveWriter`, so `self._archive.search(...)` fails `mypy`; the engine
declares a `TranscriptArchive`, so `self._archive.append(...)` fails `mypy` too.
Both directions are mechanical, and both compose with the package fence to become
more than convention — `orchestration` may not import `ai_assistant.archive` at all
(§4), so it cannot name the concrete class, cannot widen a value back to it, and
sees exactly the members its declared Protocol has. What is *not* mechanical is
which object `app/` chooses to pass, and ADR-0119 §7 leaves precisely that to the
root in its own words: one concrete satisfies every seam, and *"the composition root
hands each collaborator exactly the seam it is entitled to"*. That ADR did not claim
a type check enforced the handing, and neither does this one.

**Two rather than three, and this is where the count stops.** ADR-0119 needed a
third because its purge had a third holder; here the conversation-scoped destroy and
every read are `AssistantEngine`'s alike, so a `TranscriptArchiveRetention` beside
these two would be surface with no distinct consumer — which is what ADR-0073 §7 and
ADR-0074 §10 each declined for a count and a title. A third becomes worth adding
when a third holder exists, and adding one then is additive.

**Its own package rather than a corner of `memory/`, and the fence is the reason.**
An `import-linter` contract can forbid importing a package; it cannot forbid
importing part of one. Putting the archive inside `memory/` would leave every
pipeline subsystem that legitimately imports `memory` one attribute away from the
store the never-list is about, and the mechanical enforcement gate 1 asks for would
be unavailable. This is exactly why `evaluation/` and `secret_store/` are their own
packages, and the map already names the shape: *"no subsystem imports it"*.

**Its own database file under `Settings.data_dir`, not a table in the memory
database.** ADR-0119 §6's reasoning transfers: a separate file is what makes the
reach of every whole-store operation a decided question instead of an accident of
which tables share a connection. `MemoryStore.clear` empties the memory store and
does not touch the archive; §5 obliges whoever gives `clear` a surface to erase both
in one act, which is a decision stated in an ADR rather than a consequence of SQL.

### 11. Relation to milestone 21's source-material archive: what this does not foreclose

> **Normative.** This ADR decides a store of **text**. It does not decide, authorise
> or forbid the retention of raw source material of any modality; ADR-0094 §7 and §8
> are untouched, and §8's clause that submitted material *"is destroyed when the
> window closes"* stands exactly as written until milestone 21's deciding ADR
> supersedes it.

> **Normative.** No transcript entry carries source material, a pointer to source
> material, or `Capture`. `Capture`'s two reserved fields — which derivation
> produced the text, and whether and where the source material is retained — remain
> ADR-0221 §5's deferral and are not filled, named or constrained by this decision.

> **Normative.** A later ADR deciding source-material custody may place its store
> beside this one, inside `ai_assistant.archive`, or elsewhere; may add an additive,
> defaulted field to `TranscriptEntry` or decline to; and supersedes no clause of
> this ADR by doing any of it. What it may not do without superseding §4 is admit
> either store's content to a model prompt.

**The two archives answer different questions, and the 2026-09-02 ruling is what
separates them.** #1843's 2026-09-01 direction was for one archive over source
material of any modality, and asked the two lanes to *"Decide between you which ADR
carries the store so it is not designed twice."* The 2026-09-02 ruling narrows this
ADR to transcripts, so the division is now clean: **this ADR carries the transcript
store, and milestone 21 carries source-material custody**, including the verification
window's figures, the custody handoff ADR-0094 §8 defers, per-capture retention, and
whatever `Capture.source` comes to mean.

**Nothing here is in that lane's way, and two things are deliberately left for it.**
The package is named for what it holds rather than for this producer, so a second
store can land inside it without a rename. And the episode's address is the join for
both: a source pointer and a transcript entry name the same turn, so the two archives
compose by address exactly as §3 makes the future feed-back path compose, with no
coupling between the stores themselves.

**One thing this ADR does assert about the pair.** ADR-0094 §8 requires a bound
*"by both a duration and a size"*, enforced by refusing, because the material is
large and its derivation is lossy in a way that varies by modality. §6 sets no size
cap for transcripts, and that difference is not an oversight: text is small, its
bound is arithmetic rather than a guess, and refusing a *write* is not available to
a store that records exchanges which have already happened. A source archive's bounds
are its own and are argued in its own ADR.

### 12. The feed-back mechanism is deferred, and the ground it will be decided on

> **Normative.** No mechanism by which archived text reaches the assistant is decided
> here, and no lane cites this ADR toward one. Admitting an archive entry to a
> model prompt, to a turn's supply, or to a citation resolution takes an ADR that
> supersedes the relevant clause of §4.

The owner anticipates it and named its likely shape — *"I can just imagine this
being a tool call in the future"* — and the corpus is already some way toward
disagreeing with the spelling while agreeing with the intent. When it is decided,
the ratified ground is #1844's namer rule: *"The namer may be data, or the user, or
the model pointing outward — never the model pointing inward."* ADR-0208 §1 is that
rule's own instance — it took `recall_memory` out of the default registry and ruled
that *"A component on the turn path that wants records the supply does not hold does
not obtain them by invoking a tool"* — and its second clause binds any lane that
would re-add one. So a literal registered tool is the **unlikely** shape; the likely
one is #1844's envelope, in which the planner names a label it can already see, the
loop resolves the label to a record it selected, and no identifier reaches the model
in either direction. This ADR's only obligation to that future is §3's stable
address, and it is discharged.

### 13. The representative-input tests this decision owes

> **Normative.** The implementing lanes owe tests for each of the following, and each
> is a test over behaviour rather than over a call count.

1. **The never-list holds on a turn.** Archive an entry carrying a distinctive span,
   run a turn — routed and unrouted, spoken and typed — and assert the span appears
   in no prompt any model seam receives: the router's, the planner's, the composing
   stage's and the observer's. This is the test a later feed-back lane must
   consciously delete, which is the point of it.
2. **The fence is mechanical, on each half that can be.** An `import-linter`
   contract fails when a pipeline package imports `ai_assistant.archive`, and passes
   for `ai_assistant.app`. A composition omitting either seam fails `mypy`. A read
   called on a declared `TranscriptArchiveWriter` fails `mypy`, and an `append`
   called on a declared `TranscriptArchive` fails `mypy` — both asserted as
   type-level tests, not runtime ones. And the composition root's wiring is asserted
   directly: what `app/` hands `ConversationLifecycle` is the narrow seam. No test
   asserts that the *concrete* archive is rejected at either parameter, because no
   such rejection exists (§10).
3. **Eviction keeps and destruction destroys.** An entry survives its episode's
   expiry, its `purge_expired` reclaim, and the conversation reclaim ADR-0074 §7
   performs; and does not survive a forget of its record, a forget of its
   conversation, or the archive's own destroy at either scope.
4. **Destruction after reclaim.** A conversation whose index and record have been
   reclaimed still yields its transcript to the archive's conversation-scoped read
   and still yields to its conversation-scoped destroy.
5. **The capture ordering and its degradations.** The archive entry lands when the
   episode write fails; the capture is still reported degraded; a failing archive
   write degrades the capture and does not stop the episode write; and neither
   failure fails the turn.
6. **The verification compensates both.** A conversation stamped deleted between the
   append and the verification leaves neither an episode nor an archive entry.
7. **The user's words, not the rendering.** The entry's user half is the goal
   statement and never `content`; a turn whose plan carried a rationale archives no
   part of it; a routed pass archives its utterance; a recovered resumption and a
   parked step's resolution archive no user words.
8. **Both settings.** An unset configuration keeps entries forever; a finite
   `transcript_archive_retention` evicts past it; `transcript_archive_enabled` set
   false stops the write and destroys nothing, and the reads still serve what is
   there.
9. **The reads are bounded and ordered.** A limit of zero or below and a negative
   offset each raise `ValueError` on the three reads that take them, and `entry`
   takes neither; a blank `query`, `address` or `conversation_id` raises
   `ValueError` and matches nothing; the search order is newest-first and total; a
   conversation's read is in ordinal order.
10. **The excerpt bound holds at both ends.** An entry far larger than 512 bytes
    yields a hit whose `excerpt` encodes to at most 512 bytes of UTF-8, splits no
    codepoint, and carries `elided` `True`; an entry whose whole text is one
    character yields that character with `elided` `False`; and a multi-byte
    codepoint straddling the bound is dropped rather than split. The same
    assertions run against every conforming implementation, index-backed or
    scan-backed.
    Each of the three `core/types.py` models refuses mutation, as a frozen model
    does.
11. **The subject cascade, over the sequence and over its residue.** With a captured
    episode carrying a stated `about_person`: the enumeration precedes the erasure,
    every enumerated address is discarded after it, and the count `delete_about`
    returns is not read as an address. And with a matched record that is
    expired-but-unpurged: its entry survives the cascade — the residue §5 names —
    and is destroyed by the archive's own address-scoped destroy.
12. **The ordinal's domain is refused, not merely documented.** A
    `TranscriptEntry` with an ordinal below `FIRST_TURN_ORDINAL`, negative, or at or
    above `2**63` fails validation, so a forged entry cannot sort ahead of a real
    first turn in a conversation's read.
13. **The matching predicate, over the cases that separate implementations.**
    `Straße` matched by `STRASSE`, which full case folding admits and simple case
    folding does not; a composed `é` matched by a decomposed one and the reverse; an
    all-caps query against lower-case text and the reverse; a one-character query; a
    query whose leading or trailing whitespace is significant, which matches only
    text carrying it; and a query spanning the boundary between `asked` and
    `replied`, which matches nothing. Every case runs against every conforming
    implementation, index-backed and scan-backed alike.
14. **The destruction failure paths, both scopes.** A record-scoped forget whose
    archive discard raises leaves the memory record present and reports the
    failure; a second forget at the same id destroys the entry although the store
    now holds no live record for it. A conversation-scoped delete whose archive
    discard raises does not drop the index or the record, and the reclaim run again
    finishes it. Neither path ever leaves a transcript reachable behind a dropped
    index.
15. **No archive text in a log or a trace**, on the capture path and on every
    failure path (ADR-0004 §5).

### 14. What the implementing lanes owe

> **Normative.** Two lanes, in order, each briefed from this ADR's merged text.

**Lane B — the contract, the store, the write and the cascade.** `core/protocols.py`
(`TranscriptArchiveWriter` and `TranscriptArchive`), `core/types.py`
(`TranscriptEntry`, `TranscriptHit`, `TranscriptArchiveSize`), the shared conformance
suite, the canonical fake in `ai_assistant.testing`, the SQLite implementation in the
new `ai_assistant.archive` package, the two `Settings` fields, the `import-linter`
contract, the `CLAUDE.md` map entry, the composition-root wiring in `app/`, and — in
`orchestration/` — the user's words threaded per call site, the archive write in
`ConversationLifecycle.capture`, the compensation in its verification, and the
cascade in the conversation-scoped and record-scoped deletions. **Not** the subject
cascade: `delete_about` is not on `MemoryStore` in the tree, so there is nothing for
lane B to cascade from, and §5's sequence binds the lane that lands ADR-0101's
operations instead.

That is one lane under ADR-0137 on both of its tests. §1's: the substantial new
machinery is in one subsystem, `archive/`, and what lands in `orchestration/` is one
threaded argument, one write beside an existing one and one destroy beside an
existing one — adaptation, which §1 admits anywhere. And
§2's: the triad rides with its primary production implementation, *"the consumer whose
demands shape the contract"*, which is capture — the caller whose needs fix `append`'s
shape. §2's reason applies exactly here: the contract stays soft while its hardest
consumer stress-tests it, and a `TranscriptArchive` whose only exercise was its own
conformance suite would harden before anything had tried to write an entry from a
routed pass or a recovered resumption. §3 binds too: the triad is not split.

**Lane C — the surfaces.** The engine's four read operations and two destroy
operations, their registration on the local API in `wire/` and `service/`, the
`PROTOCOL_VERSION` bump the added methods oblige, the CLI command group, and the
statements §8 requires. A gateway page may ride with it or follow as its own lane
touching `interfaces/` alone; the ADR requires the CLI and permits the page.

> **Normative.** Lane C moves `PROTOCOL_VERSION`. Adding a method to the engine
> surface is a method-set change, and the obligation falls on the change that adds
> the method, in that same change. Lane B moves it not at all: no type it adds crosses
> `wire/` or `service/`.

> **Normative.** Neither lane implements, prepares for, or leaves a hook for the
> mechanism §12 defers.

### 15. Deferred, by name, each with what fires it

- **The feed-back mechanism** (§12). Fired by a decision to build it, on #1844's
  envelope ground; not by this ADR and not by an implementing lane.
- **A size or count cap on the archive**, and which entries an eviction would take
  (§6). ADR-0007 §5's deferral, inherited. Fired by the figure §6 puts on the
  screen, or by the first deployment in which the archive's size is what makes the
  data directory or a backup unusable.
- **Application-level encryption at rest** (§9, gate 4). ADR-0004 §4's question, not
  this store's. Fired by the lane that first implements it, which §5 obliges to cover
  both stores.
- **A modality on a transcript entry** (§1). Fired by a user-visible need to tell a
  spoken turn from a typed one in the transcript; additive, and it takes an additive
  defaulted field rather than `Capture`.
- **Source-material custody and `Capture.source`** (§11). Milestone 21's, #1318 and
  #1845.
- **Relevance ranking, hybrid retrieval, or any query decomposition over the
  archive** (§7). Fired by a lexical search that demonstrably fails a question a
  user actually asked; a ranking is additive to a total order, an embedding is not
  available at all (§4).
- **Archiving an episode that belongs to no conversation** — §1 admits one producer,
  and ADR-0074 §3 already rules that a conversationless episode is the default shape
  rather than an exception. Fired by the ADR that admits such a producer (#1874's
  direction; ADR-0075 §2 names a future capture source and declines to grant it
  capture's exemption in advance). Nothing here forecloses
  it: §3's address is the episode's id whatever produced it, and §1's grouping
  fields widen without superseding a clause of this ADR. This ADR designs none of
  it, and whether such an episode belongs in a *transcript* archive at all is that
  ADR's question, not this one's.
- **Import of an exported archive.** ADR-0007 §5's deferral, unchanged.
- **What a belief whose evidence has expired renders** (§4). ADR-0072 §3's filed
  question and ADR-0073 §4's gate, untouched: this ADR does not answer it, and
  forbids answering it by accident.
- **Retention values for episodes, and renewal on retrieval.** The owner's
  2026-09-02 ruling: the revisit trigger is data, not a better argument.

### 16. Scope, and what this records against earlier ADRs

**This ADR supersedes no clause of any ratified ADR, in whole or in part**, and
every clause it cites binds as written. That is a classification of this change and
is therefore stated as prose rather than marked (ADR-0089 §1); what follows is the
working that supports it, clause by clause, under ADR-0070 §1's test.

**ADR-0074 §3 is distinguished, not superseded, and the distinction is exact.** Its
ruling — every turn is an episode, capture writes one `EpisodicMemory` per outcome,
the episode is the citable record — is untouched and is relied on throughout. What
§3 additionally *argues*, in its third reason, is that a second verbatim store is a
bad trade. This ADR knowingly takes that trade for a benefit §3 did not have in view,
pays the first of its two costs (duplication, §6) and removes the second (two
deletion surfaces with no transaction, §5). An argument that a cost is not worth
paying is not a rule that it may not be paid, and ADR-0074 §10's declined entry —
the shape that *is* a rule — is a different design, refused for reasons §Context
answers one by one.

**ADR-0074 §7 is untouched, clause by clause.** Its horizon, its finite default, its
`None` spelling, its conversation-reclaim rule and its setting all stand and are read
unchanged. Its accepted cost is stated over the surfaces it is about, and each
statement stays true: a conversation past the horizon still *"continues with no
history"*, because the archive is not in the read path (§4); its turns are still gone
from retrieval and from `MemoryStore.export`, because the archive is a different
store with a different read; and a reclaimed conversation's id still stops resolving
for everything §2 governs. Reading a transcript is not continuing a conversation, and
this ADR gives no reclaimed id back its ability to be continued, appended to, or
retrieved from.

**ADR-0074 §8 is extended in application and unchanged in text, and the extension
is named rather than slipped in.** §2 adds one write inside its capture sequence;
§5 adds one destroy inside its compensation, one destroy inside its reclaim, and a
third conjunct to its step 3 — the archive holds no entry for the conversation.
Every clause §8 states about the two stores it knew binds unchanged, and a reader
running its protocol over those two stores runs it exactly as written; what is added
is a step and a condition over a store §8 did not have, which is what "extended in
application" means here. Its accepted window is inherited, restated, and honestly
described as widened in content rather than in reach.

**ADR-0004 §7's "prefer references over copies where practical" is not satisfied and
this ADR says so.** A reference would be a pointer to a record that will not exist,
which is the whole problem the archive addresses; the copy is what makes the
retroactivity possible. What §7's minimisation clause *does* bind here is what is
copied, and §1 answers it: the user's words and the assistant's reply, and not the
model's rationale.

**ADR-0199 §3's obligation to state a posture is discharged in §8**, and this is
recorded here so a later reader can find it: the posture is that archive content is
withheld from every channel of unbounded audience, unconditionally.

**Everything else this ADR cites is used as ratified**: ADR-0004 §1, §4, §5, §6 and
§7; ADR-0005 §1; ADR-0007 §2, §4 and §5; ADR-0015 §1 and §5; ADR-0017 §1; ADR-0072
§3 and §5; ADR-0073 §4, §5 and §7; ADR-0075 §2; ADR-0088 and ADR-0089 for the
citation forms and the marks; ADR-0094 §7 and §8; ADR-0100 §4; ADR-0101 §1, §4, §6
and §7; ADR-0114 §6; ADR-0119 §6 and §7; ADR-0137 §1, §2 and §3; ADR-0154 §2;
ADR-0155 §1; ADR-0158 §1; ADR-0162 §5; ADR-0197 §10; ADR-0199 §1, §2 and §3;
ADR-0208 §1; ADR-0210 §1; ADR-0221 §1, §2 and §5.

## Consequences

- **The horizon stops destroying and starts evicting.** Every improvement to how
  well this system reads an exchange becomes applicable to the whole of the user's
  history rather than to next month's, the day a mechanism for it is decided — which
  is the argument #1843 records and the reason the 30-day figure can go on being
  unargued while #1886 measures its premise.
- **The user gets the first transcript read this system has ever had.** Today a past
  conversation is a count and a span; after lane C it is text they can search.
- **Tier 1 content is duplicated, deliberately, from the moment of capture.** This is
  the cost ADR-0074 §3 named and #1843 called *"the real cost"*, and it is paid at
  ADR-0004 §4's existing at-rest baseline. Gate 4 is upheld rather than closed, and
  the finding belongs to ADR-0004 §4.
- **A third local store joins the deletion protocol.** ADR-0074 §8's window is
  inherited rather than widened in reach, and what would close it is unchanged: leg
  5's transactional posture across the local stores.
- **`PROTOCOL_VERSION` moves once**, in lane C, and the hub is redeployed with it.
- **A new subsystem package appears in the architecture map**, with an
  `import-linter` contract that fails the gate on a violation — the third package
  nothing imports, after `evaluation/` and `secret_store/`.
- **The lane that lands ADR-0101's `delete_about` inherits an obligation** it did
  not have before: §5's enumerate-then-erase-then-discard sequence, and the residue
  it must state. It becomes cheaper the day that operation returns the ids it
  destroyed rather than their count.
- **Revisit if** the size figure the surface reports makes the deferred cap real; if
  application-level encryption is implemented; if the feed-back mechanism is decided;
  or if a lexical search is shown to fail questions users actually ask.

## Alternatives considered

- **Copy at expiry rather than write at capture.** Rejected in §2. It cannot recover
  the user's own words, needs a `MemoryStore` read that defeats ADR-0007 §2's
  read-time guarantee, and makes the archive's contents a function of whether a sweep
  ran.
- **Archive `EpisodicMemory.content` verbatim.** Rejected in §1. It archives the
  model's plan rationale as though it were something said, and it is a rendering
  rather than a quotation.
- **A minted archive identifier, with a mapping to episode ids.** Rejected in §3. It
  reintroduces the whole of ADR-0074 §3's two-store objection — a mapping to
  maintain, to delete, and to disagree — in exchange for nothing.
- **A table in the memory database rather than a package and a file.** Rejected in
  §10. `import-linter` can fence a package and cannot fence part of one, so gate 1's
  mechanical enforcement would be unavailable.
- **One Protocol for every capability.** Rejected in §10, and rejected on this
  ADR's own first review round, which found the contradiction: §2 puts the write
  inside `ConversationLifecycle.capture`, so a single wide seam would hand a
  turn-path collaborator all four reads in the same breath §4 forbids them. The
  narrow writer is bought against that failure.
- **A wide Protocol inheriting the narrow one**, on `InvocationLedger`'s shape.
  Rejected in §10, and rejected on this ADR's third review round: it would give
  `AssistantEngine` an `append`, and §1 reserves writing to capture. The two faces
  overlap in the one operation both holders perform and in nothing else.
- **Three Protocols, on ADR-0119 §7's exact shape.** Rejected in §10. There the
  purge had a third holder; here the conversation-scoped destroy and every read are
  `AssistantEngine`'s alike, so the third seam would have no distinct consumer.
  Additive when a third holder exists.
- **Stating the subject cascade as "destroy the entries at the addresses it
  destroyed".** Rejected in §5. `delete_about` returns an `int` by ADR-0101 §1, so
  the clause names something no implementation can compute; the enumerate-then-
  erase-then-discard sequence is what the ratified contract admits, with its residue
  named.
- **A finite default retention for the archive.** Rejected in §6. It reintroduces the
  loss the archive exists to remove, at a second number nobody can argue for, and
  ADR-0074 §7's argument for a finite episodic default is entirely about the read
  path the archive is not on.
- **Letting citation resolution fall through to the archive** when a belief's cited
  episode has expired. Rejected in §4. It would answer ADR-0072 §3's open question by
  accident and put archived text into the prompts that render a warrant.
- **An opt-in archive, off by default.** Rejected in §6. A worst-case net that is off
  by default catches nothing, and the owner's ruling is that the net gets built now.
  The off switch exists; the default is on.
- **Making the archive speakable when its entry names no third party.** Rejected in
  §8. Deciding that requires inspecting the words, which ADR-0199 §2 forbids, or
  inferring a subject, which ADR-0100 §4 forbids.
