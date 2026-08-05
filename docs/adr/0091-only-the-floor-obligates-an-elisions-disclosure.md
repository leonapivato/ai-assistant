# 91. An elision obligates a distinction, and only ADR-0073 §4's floor obligates its disclosure

- Status: Accepted
- Date: 2026-08-02
- Note (2026-08-05): **Three of §6's deferrals are taken, and no clause of this
  ADR is replaced.** §6 defers "how an inspection surface conveys the elision, and
  on which type" to #568; "whether ADR-0086 §10's deferral of 'its rendering'
  reaches ADR-0073 §4's floor" to #624; and "whether
  `BeliefSummary.evidence_count`'s documented meaning needs correcting" to #568's
  change. ADR-0107 decides all three: its §3 gives both `Belief` and
  `BeliefSummary` a field `evidence_elided: int = 0` (`ge=0`); its §1 settles #624
  for the reading that §10 deferred only the *form*, so ADR-0073 §4's floor
  governs the inspection surface as ratified; and its §6 rules that
  `evidence_count` keeps its value and loses the floor's wording, with the floor's
  question answered by the pair of counts. A reader holding only this ADR would
  otherwise still believe the three open, which is the ADR-0082 §1 trigger.

  **Nothing this ADR decided changes, and its `Status` takes no token.** §1's
  first marked clause is relied on by ADR-0107 §1 and §2 exactly as written —
  its release "is bounded by §4's authority and reaches no other ADR", so it
  neither created the obligation ADR-0107 acts on nor removed it, and ADR-0073
  §4's floor arrives there intact because this ADR left it so. §1's second marked
  clause is **satisfied** by ADR-0107 §5 and §9, not narrowed: an elision is
  rendered as capacity rather than loss, and ADR-0107 §9 declines to render one as
  an `Evidence` entry precisely because `Evidence` has one nullable field and the
  marker would read as a tombstone. §2, §3, §4, §5, §7 and §8 are untouched. So no
  clause is superseded, and under ADR-0070 §4 no leading token is owed; the record
  ADR-0082 §1 requires is this note.

  **§6's remaining entries stand.** When the first displacement happens is still
  unpredicted; `MAX_EVIDENCE_CITATIONS`, the fold, the recurrence and
  `MemoryStore.get_many` are still untouched; and ADR-0086 stays unmarked
  (ADR-0089 §5) — ADR-0107 adds no mark to it and its own note carries none.
  Appended note per ADR-0070 §1; no ratified text is rewritten. Refs #568, #624.
- Partially supersedes: ADR-0086 — §4's clause that two renderings of an elision
  and a tombstone must both exist; §1 below. The rest of §4 stands whole: the
  field, its recurrence over installs, the record-level obligation, the
  floor-plus-ceiling shape of a count that *is* rendered, the
  confidence-neutrality rule and `export`'s carriage of the stored number are all
  untouched, and no other section of ADR-0086 is replaced.
- **ADR-0073 §4's floor is untouched, and it is the obligation that survives
  here.** §1's release is bounded by ADR-0086 §4's authority and reaches no other
  ADR. The floor binds the inspection surface on its own, ADR-0086 §11 already
  ruled it "*satisfied* here, not narrowed", and a citation the bound displaced is
  inside it. That reach is argued in Context and deliberately **not** marked: it
  adds no obligation this ADR makes, and marking a restatement of it would owe
  ADR-0073 §4 a partial supersession for a rule that is correct as ratified
  (ADR-0089 §5). **Whether ADR-0086 §10's deferral of "its rendering" reaches that
  floor is left open and filed as #624**, because settling it against §10 means
  superseding a section neither #586 nor #606 reported.
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

### The obligation that survives is ADR-0073 §4's, and three ratified texts put a displaced citation inside it

Removing ADR-0086 §4's requirement would lapse a ratified floor if that floor
rested on it. It does not, and the direction runs the other way: ADR-0073 §4 is
where the obligation was decided, ADR-0086 §4 is one of two ADRs that read it.
Its terms, on the inspection surface for a `DERIVED` belief:

> - **The floor**, requiring no further read: the surface conveys that the belief
>   is derived and how many citations stand behind it, and it **must not present a
>   derived belief as carrying a warrant it cannot show.** A citation the surface
>   cannot render as evidence is never rendered *as* evidence — not as a
>   reassuring id, not silently dropped.

**A displaced citation is inside it, and the corpus has already said so three
times.**

- **ADR-0077 §6 reads "not silently dropped" as forbidding a silent gap.** Its
  tombstone rule cites this floor for exactly that: "Not a bare id, **not a silent
  gap** — ADR-0073 §4's floor already forbids both". So the floor's second half is
  an *under*-claim prohibition and not only the reassuring-id over-claim.
- **ADR-0086 §4 opens by invoking the same floor for the same reason.** "Silent
  truncation is not available. ADR-0073 §4's floor … is the rule #473 names as
  closing this off … **A displaced citation that leaves no trace would make a
  belief report a narrower warrant than it has, which is a *false* answer to the
  one question the provenance display exists to answer.**" That sentence is why
  `evidence_elided` exists at all.
- **ADR-0086 §11 ran ADR-0070 §1's test on it and left it standing.** "ADR-0073
  §4's floor is *satisfied* here, not narrowed — §4 above is what keeps the drop
  from being silent." A floor that is *satisfied* by a mechanism is a floor the
  mechanism was measured against, not one the later ADR replaced.

**And the surface's own type uses the floor's words.** ADR-0085 §4a's
`BeliefSummary` documents `evidence_count` as "How many citations stand behind
it, resolved or not" — ADR-0073 §4's phrase verbatim — and its class docstring
claims the floor: "**ADR-0073 §4's floor becomes a static guarantee rather than a
convention** … It holds how many there are and how many are gone, which is what
§4 asked the listing to convey." `Engine._summarise` computes that field as the
length of the retained tuple.

**Which makes the floor met today and unmet on the first displacement, and this
is the finding.** Before ADR-0086 §1's bound nothing could be displaced, so "how
many citations stand behind it" and the tuple's length were one number by
construction — ADR-0073 could not have distinguished them and did not. After the
bound they can differ, and ADR-0086 §4 is explicit which way: "an elided citation
is not unresolved, and the belief did not lose support — **the record lost the
reference**." So a displaced episode still stands behind the belief, and a
surface reporting only the retained count reports fewer than stand behind it,
under a field name that says otherwise.

**ADR-0086 §4's "gap in reach, not a false statement" is true of the interim and
dates its own end.** Its third surfaces bullet opens "**Until it is taken**", and
what makes the silence tolerable is stated in the same breath — the surface "is
silent about a quantity it does not hold". That holds while no belief has
displaced, because there is then no quantity and the retained count *is* the whole
count. It stops holding the first time a fold displaces, which ADR-0086 §2 says is
reachable on the next `REINFORCE` of any belief a deployment already carries above
64. At that moment the floor is unmet, and #568 stops being a question about
whether the DTOs should grow a field.

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

### 1. What ADR-0086 §4 obligates, and what ADR-0073 §4's floor still does

ADR-0086 §4's "The renderings must differ, and both must exist" is replaced by
two clauses. The first says what it does not obligate, and carries the one
exception that matters; the second keeps what it does.

> **Normative.** ADR-0086 §4 obligates no surface, no lane and no later ADR to
> render `Provenance.evidence_elided`, and no lane owes a rendering on §4's
> authority. **This release is bounded by §4's authority and reaches no other
> ADR**: in particular it neither narrows nor restates ADR-0073 §4's floor, which
> binds the inspection surface on its own and which this ADR leaves exactly as it
> stands. This clause replaces nothing else in §4: the field, its recurrence over
> every install, the record-level obligation, `export`'s carriage of the stored
> number and the confidence-neutrality rule are untouched.

**The clause bounds this ADR's release and imposes no disclosure of its own, and
the distinction is the whole of what ADR-0089 §3 is for.** Adversarial review
found the first draft of it marking both — it bounded the release *and* stated
that a belief which has displaced a citation is owed a disclosure — while the
paragraph beneath it said the floor was "deliberately not marked". That is one
obligation written twice at two widths inside the section correcting exactly
that defect, and it is recorded rather than quietly fixed for the reason ADR-0089
§2 and ADR-0090 §1 each recorded their own: the drift is a property of the form,
not of any author's care, and both of the two ADRs written under ADR-0089 have
now produced an instance of it inside their own marked clause.

**Why the floor's reach is argued and not marked.** A clause is marked because it
obligates; ADR-0073 §4's floor already obligates, on its own authority, and
ADR-0073 is an unmarked ADR that binds as prose exactly as the ratified corpus
does (ADR-0089 §4). Marking a restatement of it would add nothing a lane owes and
would cost two things: ADR-0089 §5 names one legal route by which an old rule
enters the marked regime — "restate an earlier ADR's rule as its own marked clause
**and partially supersede the earlier one for that scope**" — so the mark would owe
ADR-0073 §4 a supersession for a rule that is correct as ratified; and it would
put one obligation in two live documents to drift. Under ADR-0089 §3 the argument
in Context does precisely the job unmarked text is for: it determines what this
clause *means* when it says the release reaches no other ADR.

**What that leaves open is named rather than assumed away, and it is #624.**
ADR-0073 §4 requires the surface to convey how many citations stand behind a
`DERIVED` belief; ADR-0086 §10 defers "**Whether the inspection DTOs grow a field
for the elision**, and its rendering" to #568. Once a belief displaces a citation
those two point in different directions, and which governs turns on whether §10
deferred the *form* of the disclosure or the obligation itself — the second
reading making ADR-0086 §10 a narrowing of ADR-0073 §4 that owes it a record
ADR-0086 never wrote, and contradicting §11's own "not narrowed". **This ADR does
not settle it**, because settling it against §10 means partially superseding a
section of ADR-0086 that neither #586 nor #606 reported and that this lane was
not read for. §6 records the deferral and #624 carries it.

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

**The alternative classification was considered and it does not survive.** It is
arguable that the sentence never was a rule — that it
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
here that reaches the product.** Less than the section title suggests, and the
direction is the opposite of a relaxation.

- **What is removed** is a reading under which ADR-0086 §4 mandated, on its own
  authority and immediately, that two renderings be built. The exposure that
  reading created ran towards *doing* something: it invited a lane to put a count
  onto `Belief` or `BeliefSummary`, which ADR-0085 owns and which ADR-0086 §4
  and §10 both declined to reach into.
- **What survives is the whole of the user-facing protection**, and none of it
  rested on the sentence being replaced. ADR-0073 §4's floor requires the surface
  to convey how many citations stand behind a `DERIVED` belief and never to drop
  one silently; §1's clause is bounded so that it releases nothing of it. A user
  is not told their data was lost when it was merely no longer referenced (the
  second clause), and a user is not shown a narrower warrant than the belief has
  (the floor, on its own authority, subject to #624).
- **What is unchanged today** is what the product renders. No shipped belief has
  displaced a citation, because the bound is ADR-0086 §1's and nothing predating
  it could displace; while `evidence_elided` is zero the retained count *is* how
  many stand behind the belief, and the floor is met by what already ships.
- **What #568 inherits** is therefore a live floor and a named fork rather than a
  blank slate: ADR-0073 §4 requires the surface to convey how many citations stand
  behind the belief, a displaced citation is inside that, and whether ADR-0086
  §10's deferral reaches it is #624's to settle. The finding is recorded on #568
  so the lane meets it in its own issue rather than rediscovering it from four
  ADRs.

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

- **How an inspection surface conveys the elision, and on which type.** Whether
  `Belief` or `BeliefSummary` grows a field, whether the listing reports it some
  other way, and in what words, is **#568**'s against ADR-0085's contract
  surface, which is not this ADR's to reach into.
- **Whether ADR-0086 §10's deferral of "its rendering" reaches ADR-0073 §4's
  floor — filed as #624.** Context establishes that the floor reaches a displaced
  citation; §10 defers the rendering to #568; once a belief displaces, the two
  point in different directions. Resolving it against §10 is a partial
  supersession of a section neither #586 nor #606 reported and this lane was not
  read for, and resolving it the other way is a ruling that ADR-0086 §11's "not
  narrowed" already implies but does not state. **§1's clause is written so that
  neither answer depends on it**: it releases only what §4 obligated, so ADR-0073
  §4 and ADR-0086 §10 stand in exactly the relation they stood in before this
  ADR. Naming the fork is what this ADR owes; deciding it is #624's.
- **When the first displacement happens.** It is reachable — ADR-0086 §2 says a
  deployment may already hold a belief above the bound, whose next `REINFORCE`
  displaces — and nothing here predicts it or schedules #568 against a date.
  What is stated is the condition, not the calendar.
- **What a rendering would say.** ADR-0086 §4's floor-plus-ceiling shape governs
  a count that is rendered, unchanged, and §1's second clause adds only that a
  surface rendering both an elision and a tombstone distinguishes them. The words
  stay the surface lane's, exactly as ADR-0077 §6 left the tombstone's.
- **Whether `BeliefSummary.evidence_count`'s documented meaning needs correcting.**
  It reads "How many citations stand behind it, resolved or not", which is
  ADR-0073 §4's phrase and which the retained count stops answering after a
  displacement. That is a `core` docstring and an ADR-0085 surface question, and
  it belongs with #568's change rather than to a lane whose fence is two ADR
  files. It is recorded on #568.
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
- **Reading ADR-0073 §4's floor as not reaching a displaced citation.** It is the
  reading that would make §1's release total, and it is available on one narrow
  construction: that "a citation the surface cannot render" means a citation the
  record still carries and the surface cannot resolve, so a displacement — which
  removes the reference entirely — is outside it. **Refused, because three
  ratified texts read it the other way** (Context): ADR-0077 §6 glosses the same
  clause as forbidding "a silent gap", ADR-0086 §4 invokes it to call a traceless
  displacement "a *false* answer", and ADR-0086 §11 ruled the floor "*satisfied*
  here, not narrowed". Refused also on the floor's other half, which the narrow
  construction never reaches: "how many citations stand behind it" is a count of
  the warrant, and ADR-0086 §4 is explicit that a displaced episode's support
  survives — "the belief did not lose support — the record lost the reference".
- **Marking ADR-0073 §4's floor as a clause of this ADR.** §1 gives the ground:
  it would add no obligation and would owe ADR-0073 §4 a partial supersession
  under ADR-0089 §5's one legal route, for a rule that is correct as ratified and
  already binds as prose (ADR-0089 §4). What is marked instead is the boundary of
  this ADR's own release.
- **Ruling on `BeliefSummary.evidence_count`'s documented meaning.** It uses
  ADR-0073 §4's words for a number that stops answering them after a
  displacement, which is a real defect and is recorded on #568. Deciding it here
  would reach into ADR-0085's contract surface from an ADR nobody read for it —
  the widening ADR-0086 §4 declined once and this ADR declines again.

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
- **ADR-0073 §4 — nothing owed, and this is the bullet the change turns on.** Its
  floor is applied here, not narrowed and not widened. No sentence of it becomes
  false: it says the surface conveys how many citations stand behind a `DERIVED`
  belief and never drops one silently, and that is exactly what §1's clause
  preserves against ADR-0086 §4's release. What this ADR adds is a *reading* — that
  a displaced citation is inside the floor — and the reading is not new either:
  ADR-0086 §11 already ruled the floor "*satisfied* here, not narrowed", which
  only parses if the floor reached the elision. A reader holding only ADR-0073
  acts identically before and after, which is ADR-0070 §1's test and ADR-0082 §1's
  condition for owing nothing.

  **An earlier draft owed a record here and no longer does, which is worth the
  three lines.** That draft marked the disclosure itself — "a belief that has
  displaced one is therefore owed a disclosure" — and adversarial review raised
  it as a `blocker` on the ground that it narrows ADR-0086 §10's deferral of "its
  rendering" while the supersession scope names only §4. **The finding was
  correct**, and the fix is not to widen the scope but to stop the clause
  obligating what it was never this ADR's to obligate: §1 now bounds the release
  and imposes nothing, so §10 and ADR-0073 §4 stand in the relation they stood in
  before. The tension between them is real, predates both this ADR and ADR-0086's
  ratification, and is filed as **#624** rather than settled from inside a lane
  scoped to five reported defects.
- **ADR-0085 — nothing owed *from this ADR*.** `Belief` and `BeliefSummary` are
  its contract surface and neither gains nor loses a field here; §1 returns the
  form of the disclosure to #568 rather than deciding it. `BeliefSummary`'s
  `evidence_count` documents itself in ADR-0073 §4's words and will stop answering
  them after a displacement — that is a defect in a `core` docstring and a
  question for #568's change, recorded there, and it is not created by anything
  this ADR decides.
- **ADR-0077 — nothing owed.** §6's tombstone is cited for what it is, and §6's
  own gloss of ADR-0073 §4 ("not a silent gap") is used as ratified rather than
  extended. §1's second clause constrains only a surface that renders the
  tombstone *beside* an elision, which is a case §6 never addressed. Under
  ADR-0082 §1 that is a **stacked addition**, recorded here and nowhere else.
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
  have done. **ADR-0073 §4's reach is argued and not marked**, on §1's ground —
  it obligates nothing this ADR adds, and marking it would owe ADR-0073 §4 a
  supersession under ADR-0089 §5's route. Under ADR-0089 §3 that leaves the
  argument doing exactly the job §3 assigns unmarked text: it determines what
  §1's first clause *means* when that clause says it releases nothing ADR-0073 §4
  requires.

## Consequences

**Easier.**

- **A lane reading ADR-0086 §4 knows what it owes.** The count lives on the
  record and in `export`; §4 mandates no rendering; the disclosure a displaced
  citation owes is ADR-0073 §4's; and a surface rendering both an elision and a
  tombstone distinguishes them, in §4's floor-plus-ceiling shape. That is four
  sentences where the document previously offered a standing requirement and two
  ratified denials of it.
- **#568 stops being a question ADR-0086 had already answered.** The lane that
  decides how the surface carries the count is not answering one ADR-0086
  answered in the affirmative and is not blocked by one; what it meets instead is
  ADR-0073 §4's floor and #624's fork, both stated where it will look.
- **A ratified floor is written down as reaching a case that postdates it**,
  against three texts that already read it that way, so the next lane does not
  re-derive it from ADR-0073, ADR-0077 §6 and two sections of ADR-0086.
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
- **The corpus carries a named fork it has not settled.** ADR-0073 §4's floor is
  met today and stops being met on the first displacement — reachable on the next
  `REINFORCE` of a belief a deployment already holds above the bound (ADR-0086
  §2) — while ADR-0086 §10 defers the rendering to a lane that has not ruled.
  **#624** holds it, with no dated trigger and no gate that fires. That is a
  worse position than a settled reading and a much better one than a floor
  lapsing unmentioned, which is what a narrower fix to §1 would have produced.
- **This ADR's own marked clause drifted from the prose beside it on the first
  round**, and had to be narrowed after adversarial review raised it as a
  `blocker` (§1, §8). Both of the two ADRs written under ADR-0089 have now done
  this inside their own marks — ADR-0090 §1's gap definition and this clause's
  scope — which is evidence for ADR-0089 §3's demand that a clause carry its own
  scope and against any expectation that marking makes the drift stop happening.
- **`BeliefSummary.evidence_count` documents itself in the floor's words.** "How
  many citations stand behind it, resolved or not" is ADR-0073 §4's phrase, and
  the shipped value is the retained count; the two coincide only while nothing
  has displaced. Nothing here corrects it — it is `core` text and ADR-0085's
  surface — and #568 carries it.

**Revisit when** #568 is taken. §1's second clause is written for a surface that
does not exist yet, and the lane that builds one is the first reader able to say
whether "so a reader can tell the two apart" is enough of a constraint to be
worth having.
