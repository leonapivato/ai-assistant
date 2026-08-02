# 91. An elision obligates a distinction, not a rendering

- Status: Accepted
- Date: 2026-08-02
- Partially supersedes: ADR-0086 — §4's clause that two renderings of an elision
  and a tombstone must both exist; §1 below. The rest of §4 stands whole: the
  field, its recurrence over installs, the record-level obligation, the
  floor-plus-ceiling shape of a count that *is* rendered, the
  confidence-neutrality rule and `export`'s carriage of the stored number are all
  untouched, and no other section of ADR-0086 is replaced.
- **Four further defects are amendments, not supersessions**, and are recorded in
  ADR-0086's appended dated note rather than on its `Status` line, which now
  carries a leading supersession token (ADR-0082 §2). §2 through §5 classify each
  against ADR-0070 §1's test and say why none of them moves a decision.
- **No code changes with it** and no `core` surface is touched. This ADR decides
  no Protocol and no `core` type, so **adversarial is the required set** — the
  reading ADR-0082 §5, ADR-0088 §8 and ADR-0090 §5 each recorded for themselves.
  ADR-0015 §5's ratify-after-review sequencing is scoped to a substantive
  contract ADR and does not reach this one, so it is ratified before review
  rather than after (ADR-0090 §5), which is what lets the `Status` record on
  ADR-0086 point at a live decision from the first commit.
- **Closes #586 and #606.** Their five items are one kind of defect — an
  obligation stated wrongly, incompletely, or against a surface that cannot carry
  it — and only one of the five turns out to move a decision.

## Context

### Five reported defects, and the reason they arrive together

#586 and #606 report five defects in ADR-0086 between them. None is a citation
defect ADR-0088 §6's checker could find: four of the five are about what a
sentence *obligates*, and the fifth is a bare token ADR-0088 §1 leaves
unselectable by construction.

They arrive together because they share a shape. ADR-0086 is 1,051 lines of
careful argument in which the rules are not marked — it predates ADR-0089, which
is forward-only — so every sentence is a candidate rule and the document states
several of its obligations more than once, at more than one width. ADR-0089's
own Context uses ADR-0086 §2 as its worked example of exactly that. This ADR is
the other half of the same observation: ADR-0089 supplies a form for the ADRs
written after it, and says in as many words that it "fixes none of the three
instances that motivated it". Fixing them is what is left, and it takes a
ratified ruling per defect rather than a form.

### §4 says three things about rendering and they do not agree

The reported tension (#606 item 1, flagged independently by two agents) is this
sentence, closing §4's paragraph on why an elision is not a tombstone:

> The renderings must differ, and both must exist, because conflating them would
> tell the user their data was lost when it was not.

Read alone it obligates two renderings to be built. Two sentences of the same
ADR say the opposite. §4's own list of what follows for the surfaces opens by
placing the obligation elsewhere — "This is the obligation this ADR sets, and it
is deliberately set on the *record* rather than on the inspection DTOs" — and its
third bullet ratifies that today nothing renders the count at all:

> **And as the promoted surface stands, that count does not reach the inspection
> DTOs at all — stated rather than assumed away.** … Until it is taken, the
> disclosure lives on the record and in `export`, and no surface misreports — it
> is silent about a quantity it does not hold, which is a gap in reach, not a
> false statement.

And §10 puts the rendering outside the ADR entirely: "**Whether the inspection
DTOs grow a field for the elision**, and its rendering. §4, filed as **#568**."

So a document that declines to decide the rendering contains a sentence
requiring two of them. That is an internal contradiction in ADR-0070 §1's first
sense, and it is the one of the five with a consequence outside the corpus:
under the wide reading a lane could take ADR-0086 as licence to put an elision on
a DTO that ADR-0085 owns, or as a blocker on #568.

**What the wide reading is missing is that §4 already states the constraint in
its addressed form**, one bullet above:

> **Where a count *is* rendered, the honest shape is a floor plus a ceiling** —
> `len(evidence)` citations shown, and *up to* `evidence_elided` further episodes
> supported this belief and are no longer carried.

"Where a count *is* rendered" is conditional and has an addressee. "Both must
exist" is neither. §1 below keeps the first and replaces the second.

### The instruction that named the wrong method has already been discharged

#586 item 1 reports that §8 item 6 names a symbol that cannot deliver §6's
argument:

> **The presentation path** — `Engine._project` calls `get_many` once per belief
> instead of `get` per citation. **That is the whole of what this lane owes
> there** …

Verified against the tree. `Engine._project` serves the single-belief view;
`Engine._summarise` serves the listing page, which is the path §6's whole
quantitative case is about ("**The scale is 50 × 64** … **3,200** reads for one
screen"); and both call `Engine._resolved_citations`, which holds the loop that
issues one read per citation. A lane migrating only the symbol §8 item 6 names
would leave the listing on 3,200 singles and buy none of the saving, while
passing every single-belief test.

**Two things about that instruction bear on how it is classified, and both are
facts rather than readings.** First, §8 item 6's own next clause names *both*
DTOs — "`Engine._project` builds the DTOs ADR-0085 §4a ratified, **neither** of
which can carry `evidence_elided`" — and only `Engine._summarise` builds the
second of them, so the sentence's own scope was never one method. Second,
ADR-0086's Consequences state the outcome the instruction exists to produce:
"**The listing's worst case drops from 3,200 store reads to 50**". An instruction
read so as to make its own ADR's Consequences unreachable is misread.

Second, and decisively for §3 below: **the instruction is spent.** PR #582
closed #575 by migrating `Engine._resolved_citations`, which covers both callers,
and `ConversationLifecycle.history` took `get_many` with it. No future lane
reads §8 item 6 as a brief.

### The other three, checked against the tree

**#606 item 2 — §2's pointer.** §2's enforcement clause says a writer "installs
the retained subset §3 specifies", and §3 is headed "What a `REINFORCE` whose
union would exceed the bound does". The heading is fold-scoped; the rule is not.
§3's own text carries the non-fold case — "**Where there is no fold there is no
accumulation order** … so the retained subset is a suffix of an order that
carries nothing" — and §8 item 3 pins it in the conformance suite, requiring an
oversized `ACCEPT`, `STORE_TEMPORARY` and `SUPERSEDE` proposal to "each assert
the retained suffix". So the rule for an oversized non-fold install exists, is
determinate, and is tested. What is defective is the *pointer*: a reader who
navigates §2 by §3's heading concludes §3 does not reach them.

**#606 item 3 — the elided `description`.** §4 sketches the new field as

```python
evidence_elided: int = Field(default=0, ge=0, description=...)
```

and the issue reads the literal `...` as content fixed in no ratified place. **The
tree and the ADR both refute it**, and §5 records why: the block quote
immediately below that sketch is the description's content, stated in full and
ratified, and §8 item 1 assigns where it goes.

**#586 item 2 — a class that does not exist.** §6, counting the two callers,
writes

```text
Conversation resume fetches *k* turn ids (`ConversationService`'s history tail,
`orchestration/conversations.py`)
```

The class is `ConversationLifecycle`, which §8 item 7 names correctly two hundred
lines later. The file path is right, so the reference is recoverable. This is the
half of #586 that ADR-0089 §1's Context set aside as "a citation defect and …
ADR-0088's subject": it is an ADR-0088 §1 b3 bare token, so no checker selects
it, and it is corrected here because #586 cannot be closed while it stands.

## Decision

### 1. An elision obligates a distinction, not a rendering

ADR-0086 §4's "The renderings must differ, and both must exist" is replaced by
two clauses. The first says what it does not obligate; the second keeps what it
does.

> **Normative.** ADR-0086 §4 obligates no surface, no lane and no later ADR to
> render `Provenance.evidence_elided` at all. Whether any inspection surface
> carries the count, and in what words, stays #568's to decide, as ADR-0086 §10
> already leaves it. This clause replaces nothing else in §4: the field, its
> recurrence over every install, the record-level obligation, `export`'s carriage
> of the stored number and the confidence-neutrality rule are untouched.

> **Normative.** Where one surface renders both a lost citation under ADR-0077
> §6's tombstone and a count of elided citations from
> `Provenance.evidence_elided`, it renders them so a reader can tell the two
> apart: an elision is not an assertion that the episode was lost. Where a
> surface renders neither, or only one of them, this clause requires nothing of
> it. Where a count of elisions is rendered, ADR-0086 §4's floor-plus-ceiling
> shape governs how, unchanged.

**This is a partial supersession and not an amendment, and the reason is that a
reader acts differently.** ADR-0070 §1's test asks whether what was decided
changes. A reader holding only ADR-0086 §4's sentence reads a standing
requirement that two renderings exist; after this ADR they read a conditional
requirement on a surface that renders both, and no requirement to render
anything. That is a change in what a lane owes, so it takes a new ADR (ADR-0070
§1) and ADR-0086's `Status` takes the leading token (ADR-0070 §4).

**The alternative classification was considered and it does not survive §3
below's own logic.** It is arguable that the sentence never was a rule — that it
is the argument for why the field is distinct from the tombstone, which is what
its paragraph's bold lead announces ("**It is an elision, not a tombstone, and
the two are different facts**"), and that §4's conditional bullet and §10's
deferral are the operative text. On that reading the correction changes no
decision and a dated note would carry it. **Two things refuse it.** The reading
is not available to a reader of the sentence alone, and two independent readers
of the whole document reached the opposite one — which is the evidence that the
sentence obligates on its face. And under ADR-0089 §3 a ruling that constrains a
later lane has to sit inside a mark to bind at all; ADR-0089 §5 forbids adding a
mark to a ratified ADR and names exactly one legal route by which an old rule
enters the marked regime — "restate an earlier ADR's rule as its own marked
clause and partially supersede the earlier one for that scope". Marking the
surviving constraint without superseding the sentence it comes from would leave
two live documents stating one obligation at two widths, which is #477's failure
and the defect this ADR is fixing.

**What changes outside the corpus, stated plainly because it is the only item
here that reaches the product.** Nothing renders `evidence_elided` today and
nothing is now obliged to. Before this ADR a lane could read ADR-0086 as
requiring an elision rendering to exist; after it, an elision rendering is
built only if #568 decides one is wanted, and the constraint ADR-0086 was
protecting — that a user is never told their data was lost when it was merely
no longer referenced — survives as a property of any surface that renders both.
The exposure the wide reading actually created ran the other way: it invited a
lane to put a count onto `Belief` or `BeliefSummary`, which ADR-0085 owns and
ADR-0086 §4 declined to reach into.

### 2. §2's pointer reaches §3 whole, and §3's heading is not its scope

ADR-0086 §2's "it installs the retained subset §3 specifies" points at §3
entire, including the paragraph beginning "**Where there is no fold there is no
accumulation order**". §3's heading names the case §3 principally argues; it does
not bound what §3 rules. For an install that is not a fold — an oversized
`ACCEPT`, `STORE_TEMPORARY` or `SUPERSEDE` proposal — the retained subset is the
suffix §3's degeneracy paragraph names and §8 item 3 pins, and §2's "It applies
to every *install*, not only to a fold" is what puts those installs inside the
bound in the first place.

**No decision moves, so this is an amendment and no clause of it is marked.** The
rule for an oversized non-fold install is the same before and after: §2 states
the bound over every install, §3 states the retained subset, §8 item 3 tests it
on all three non-fold rulings, and `MemoryWriter`'s conformance suite has
enforced it since the implementing lane landed. A reader who read §3 rather than
its heading acted correctly before this ADR and acts identically after it, which
is ADR-0070 §1's test. What is corrected is a navigation defect: the pointer's
target has a narrower title than its content. That is a "broken cross-reference"
in §1's enumeration, which ADR-0070 §1's dated note of 2026-07-31 is explicit
makes a reader follow a different pointer and is nonetheless an amendment,
"because the ADR **decided** nothing the correction touches".

**Restating the rule here as a marked clause was considered and declined**, in
§7. A rule stated in two live documents is the drift ADR-0089 §9 refused a
`## Ruling` section over, and the rule as ADR-0086 states it is not defective.

### 3. §8 item 6 names `Engine._project` where the site is `Engine._resolved_citations`, and the instruction is spent

The presentation-path migration §8 item 6 assigns is the one that makes ADR-0086
§6's saving real, and it lands at `Engine._resolved_citations`, which both
`Engine._project` and `Engine._summarise` call. `Engine._project` alone is the
single-belief view and cannot deliver §6's stated 3,200-to-50 reduction, which is
a claim about the listing page.

**"That is the whole of what this lane owes there" bounds the *rendering*, not
the call sites.** Its own colon-clause says what it refuses: "so this lane
renders no elision and changes no field". That refusal stands entirely — §1
above is where the rendering question is now settled, and this lane changed no
DTO field. What the sentence does not do is license leaving the listing on one
read per citation, because §8 item 6's next words name both ADR-0085 §4a DTOs
and only `Engine._summarise` builds the second.

**This is an amendment, and the reason is that the instruction is spent.**
ADR-0082 §4 is the precedent on all fours: it undid ADR-0078 §10's ratification
instruction "as *rendering* and kept it as *substance*", classified the change as
an amendment rather than a supersession, and gave the ground in six words —
"§10's instructions are spent, not live". ADR-0086 §8 is a checklist of what an
implementing lane owes, headed "in the order golden rule 5 fixes", and its
item 6 was discharged by PR #582 at the correct site. No reader will act on it
again. What ADR-0086 *decided* — that `get_many` lands, that the listing's worst
case drops from 3,200 store reads to 50, that no elision is rendered — is
unchanged by naming the method correctly, and a reader acting on §6 and on
Consequences acted correctly before this ADR.

**A supersession was the expected classification and it is refused on the
text.** The case for one is that "the whole of what this lane owes" is a refusal,
and ADR-0089 §1 is right that a refusal is normative and that undoing one takes a
partial supersession. But the refusal's stated content is the rendering, and this
ADR leaves it standing; and ADR-0086's own Consequences already commit to the
listing dropping to 50 reads, so a reading of §8 item 6 that forbids migrating the
listing makes the document contradict itself rather than decide something. Under
ADR-0070 §1 that is the first enumerated amendment case — an internal
contradiction — not a decision being changed.

### 4. §6's `ConversationService` is `ConversationLifecycle`

The class ADR-0086 §6 names as the second `get_many` caller does not exist and
never did. The class is `ConversationLifecycle`, in the module §6 names
correctly, and §8 item 7 names it correctly. Nothing about §6's count of two
callers, or about the resume path's obligations, changes.

**An amendment, on ADR-0070 §1's "a stale phrase" and ADR-0082 §1's reading of
that bucket** — "The two buckets divide by where the defect is, not by when it
arose … An ADR that misstated a fact predating it has a defect in its own words".
No reader acts differently as to any decision: the two-callers argument, the
scale, and §8 item 7's instruction are all unaffected, and §8 item 7 already
carries the right name for the lane that had to act.

### 5. §4's elided `description=` fixes nothing that is not already fixed

#606 item 3 reports that §4 writes `description=` with a literal ellipsis and
that the required content "is fixed in no ratified place". **Nothing is owed,
because the content is in §4 and the placement is in §8.**

The block quote directly beneath that sketch is the description, ratified and
complete — "**The number of displacements this record's history has performed**,
and therefore an **upper bound** on the number of distinct citations it no longer
carries. It is a count and never an id" — followed by the recurrence over
installs and by §4's elision-is-not-a-tombstone paragraph. §8 item 1 says where
that content goes: `Provenance.evidence_elided` "with its `ge=0` bound and a
docstring stating §4's elision-is-not-a-tombstone distinction". The shipped type
carries both, in `core/types.py`.

What is genuinely absent is the **literal string** of a `Field` description, and
no ADR in this corpus fixes one for any field. Requiring it would make every ADR
that sketches a type the archive of its docstrings, which is the positional
citation ADR-0088 §5 refuses one level up: the text would go stale on the next
edit while still looking ratified. Under ADR-0070 §1 no reader acts differently
as to any decision, so there is nothing to record on ADR-0086 for this item, and
the dated note says so rather than staying silent.

### 6. What this ADR does not decide

- **Whether any inspection surface renders the elision.** §1 leaves it exactly
  where ADR-0086 §10 left it: **#568**, against ADR-0085's DTOs, which are
  ADR-0085's contract surface and not this ADR's to reach into.
- **What a rendering would say.** ADR-0086 §4's floor-plus-ceiling shape governs
  a count that is rendered, unchanged, and §1's second clause adds only that a
  surface rendering both an elision and a tombstone distinguishes them. The words
  stay the surface lane's, exactly as ADR-0077 §6 left the tombstone's.
- **Anything about `MAX_EVIDENCE_CITATIONS`, the fold, the recurrence, or
  `MemoryStore.get_many`.** §2 above corrects a pointer and §3 a method name;
  neither touches a rule. ADR-0086 §1, §3, §5, §6, §7 and §9 are untouched in
  full.
- **Whether ADR-0086 §8's other items were correctly discharged.** Only items 6
  and 7 are read here, and only for what they say rather than for what shipped
  against them.
- **Any form for ADR-0086 itself.** It is unmarked and stays unmarked (ADR-0089
  §5); this ADR adds no mark to it and its dated note carries none.

### 7. Explicitly declined

- **Rewriting any sentence of ADR-0086.** ADR-0070 §1 forbids it — "ratified
  decision text — the Context, Decision and Consequences — is never rewritten" —
  and ADR-0090 §4 refused the same edit on ADR-0067 three days ago on #71's
  reasoning. Every correction here is a `Status` line, an appended note, or a
  clause of this ADR. Not marked as a refusal, because no later lane could do it
  anyway; named because it is the option a reader reaches for first.
- **Restating ADR-0086 §3's retained-subset rule as a marked clause of this
  ADR.** It would put one live rule in two documents to drift, which is the
  defect ADR-0089 §9 declined a `## Ruling` section over, and it would owe
  ADR-0086 §3 a partial supersession (ADR-0089 §5's one legal route) for a rule
  that is correct as ratified. §2 corrects the pointer instead.
- **Superseding ADR-0086 §8 item 6.** §3 gives the ground: the instruction is
  spent (ADR-0082 §4), its refusal is about rendering and stands, and ADR-0086's
  own Consequences already decide the listing's 3,200-to-50 drop. A supersession
  would record a decision change that did not happen, which ADR-0082 §1's "**The
  test controls, not the label**" refuses in both directions.
- **A mechanical check that a cited symbol is the *right* symbol for the claim
  beside it.** ADR-0088 §2 already concedes it — "`Engine._project` resolves and
  is still the wrong symbol for the claim ADR-0086 §8 attaches to it (#586)" —
  and #586 is the proof that reading found it where no checker could.
- **Retrofitting ADR-0086 with marks so its obligations could be enumerated.**
  ADR-0089 §5 and §9 decline it for the whole corpus on ratified grounds, and
  nothing about this ADR reopens it.

### 8. This ADR classified under ADR-0070 §1 and ADR-0082 §1, edit by edit

- **ADR-0086 §4 — a partial supersession, and the `Status` record is owed.** §4
  *decided*, on its face, that two renderings must exist. §1 above decides that
  none must. A reader holding only ADR-0086 acts differently, which is ADR-0070
  §1's test met. The `Status` line takes the leading `Partially superseded by`
  token and the scope names the clause, carrying no `ADR-NNNN` (ADR-0070 §4).
- **ADR-0086 §2/§3, §8 item 6, §6 — amendments, recorded in the dated note
  alone.** Each is an internal contradiction or a stale phrase in ADR-0070 §1's
  first bucket, as ADR-0082 §1's note of 2026-07-31 reads that bucket, and §2
  through §4 above apply §1's test to each. Under ADR-0082 §2 the `Status` line
  now carries a leading supersession token, so no amendment qualifier is written
  on it and the note is the whole record. No ratified sentence is rewritten.
- **ADR-0086 §4's `description=` — nothing owed, and the note says so.** §5
  above. A non-finding is recorded because #606 filed it and a later reader
  should not have to re-derive the answer.
- **The record lands atomically with this ADR**, in the shape ADR-0090 §5 used
  and for its reason: ADR-0082 §7 relies on it — "the hazard §1 names is a
  `Status` line pointing at nothing, and an atomic pair makes that unreachable" —
  and splitting the change would open a window in which ADR-0086 asserts a
  rendering obligation the ADR refuting it sits beside in the same directory.
- **ADR-0085 — nothing owed.** `Belief` and `BeliefSummary` are its contract
  surface and neither gains or loses a field here; §1 above returns the question
  to #568 rather than deciding it, which is where ADR-0086 §4 and §10 already put
  it. No sentence of ADR-0085 becomes false or over-wide.
- **ADR-0077 — nothing owed.** §6's tombstone is cited for what it is and §1's
  second clause constrains only a surface that renders it *beside* an elision,
  which is a case §6 never addressed. Under ADR-0082 §1 that is a **stacked
  addition**, recorded here and nowhere else.
- **ADR-0070, ADR-0082 — nothing owed.** Both are applied, not narrowed: §1's
  amend-versus-supersede test and §1/§2's record placement are used exactly as
  ratified, including ADR-0082 §4's spent-instruction reading, which §3 above
  follows rather than extends.
- **ADR-0088, ADR-0089 — nothing owed.** No citation form is added and nothing is
  made selectable that ADR-0088 §1 leaves unselectable; `ConversationService` is
  exhibited inside a fenced block, which §1 excludes from the input set. ADR-0089
  §5's forward-only rule is obeyed on both halves: this ADR marks its own
  normative clauses and adds no mark to ADR-0086. ADR-0089's `Status` reads
  `Proposed` on `main` and its own §8 says it flips before merge; the marking
  rule binds this ADR through `CONTRIBUTING.md` either way (ADR-0003), and the
  discrepancy is filed as **#622** rather than resolved here.
- **ADR-0015, ADR-0027 — nothing owed.** Neither the contract-ADR sequencing nor
  the review floor is touched, and `docs/adr/**` stays inside ADR-0027 §3's
  floor.
- **This ADR's own marks.** Two clauses, both in §1, and they are the whole of
  what this ADR obligates (ADR-0089 §3). §2 through §5 classify amendments and
  a non-finding, which ADR-0089 §1 excludes from the normative set as "a
  classification of the change being made"; §6 and §7 record what is not decided
  and what is refused, and neither refuses anything a later lane could otherwise
  have done.

## Consequences

**Easier.**

- **A lane reading ADR-0086 §4 knows what it owes.** The count lives on the
  record and in `export`; no rendering is owed; if a rendering is built it
  distinguishes an elision from a tombstone and uses §4's floor-plus-ceiling
  shape. That is three sentences where the document previously offered a
  standing requirement and two ratified denials of it.
- **#568 inherits a constraint instead of a mandate.** The lane that decides
  whether `Belief` or `BeliefSummary` grows a field is not answering a question
  ADR-0086 already answered in the affirmative, and it is not blocked by one
  either.
- **Two navigation defects stop costing a reading.** §2's pointer reaches §3's
  non-fold paragraph and §6's second caller has the name the tree carries, so a
  reader of ADR-0086 no longer has to check the tree to use either sentence.
- **#586 and #606 close against a ratified answer**, including the item that
  turns out not to be a defect. A refuted report that is filed and never
  adjudicated is re-found.

**Harder.**

- **ADR-0086 now has to be read with its note and its `Status` line.** Its §4
  sentence stays in the file, because ratified text is not rewritten, and a
  reader who reads §4 and stops has read something this ADR replaces. That is
  the append-only shape working as designed and it is the cost ADR-0090 §5
  already priced for ADR-0088.
- **One more ADR sits between a reader and what ADR-0086 obligates.** ADR-0086
  §4 is now read through §1 here, the way ADR-0088 §6 is read through ADR-0090
  §1 and ADR-0070 §4 through ADR-0082 §2.
- **Four of the five defects took a ratified ruling to record and none of them
  could be fixed where it lives.** An unmarked ADR that states one obligation at
  two widths cannot be corrected by narrowing the wider sentence, only by
  superseding it or by appending a note that a reader may not reach. ADR-0089
  removes the cause for ADRs written after it and nothing removes it for the 87
  written before, which is the standing cost §5 of that ADR accepted.
- **The classification stays a judgement, and this ADR splits it four ways
  against one document.** Whether "both must exist" was a rule while "that is the
  whole of what this lane owes there" was a spent instruction is a reading, made
  here on quoted text and reviewable against it (ADR-0082 §1), and a reviewer who
  reads either the other way has a clause to name.

**Revisit when** #568 is taken. §1's second clause is written for a surface that
does not exist yet, and the lane that builds one is the first reader able to say
whether "so a reader can tell the two apart" is enough of a constraint to be
worth having.
