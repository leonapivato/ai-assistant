# 107. The elision reaches the inspection surface: both DTOs carry it, and ADR-0086 §10 deferred the form

- Status: Proposed
- Date: 2026-08-05
- **This is a contract change.** §3 adds one field to `Belief` and one to
  `BeliefSummary` in `core/types.py` — two types the `AssistantEngine` Protocol
  returns, which `orchestration` produces and `interfaces` and `wire` consume.
  `CONTRIBUTING.md` → "Contract ADRs land before their implementation" puts "a
  Protocol **or a `core` type that crosses subsystem boundaries**" in its own PR,
  ratified before the implementation PR that depends on it (golden rule 5,
  ADR-0015 §5), and states the limit outright: "what must not happen is the
  implementation landing *with* the ADR that justifies it". So **no code changes
  with it** — the two fields, the two projections, the CLI rendering and the
  canonical fake are a later lane (§8). This is the shape ADR-0096 took for one
  optional field on `CurrentContext`, ADR-0092 for one on `Provenance`, and
  ADR-0086 for `evidence_elided` itself.
- **Required review set: adversarial *and* architecture**, though the PR carrying
  it is prose only. It decides `core/types.py` surface, which is what
  `CONTRIBUTING.md` → "Stop when the required reviews are green" makes
  contract-surface: a change is contract-surface "when it is the ADR deciding that
  surface". Worth stating because it is not mechanical here — `scripts/ship.sh`
  fires its architecture requirement on a diff touching
  `src/ai_assistant/core/protocols.py` or `src/ai_assistant/core/types.py`, and a
  docs-only PR deciding those files trips neither. The requirement is
  `CONTRIBUTING.md`'s, not the script's; ADR-0096's header records the same for
  the same reason.
- **Closes #568 and #624, and they are one question.** #568 asks whether the
  inspection surface conveys `Provenance.evidence_elided` and on which type; #624
  asks whether ADR-0086 §10's deferral of "its rendering" reaches ADR-0073 §4's
  floor, which is unrecorded either way. Deciding #568 without #624 would answer
  "the surface conveys it" while leaving the governing text ambiguous, and
  deciding #624 without #568 would settle which text governs while leaving the
  DTOs with nowhere to put the number. §1 takes the second, §2–§7 the first.
- **Records owed on earlier ADRs (ADR-0082 §1), declared and written here.** §11
  names each clause, quotes it, and applies ADR-0070 §1's test. One is owed on
  ADR-0085 as a partial supersession, two as dated notes on ADR-0086 and
  ADR-0091, and six commonly-assumed others are argued *not* owed — ADR-0073 §4
  and ADR-0077 §6 among them. **All three land in this change**, atomically with
  the ADR that causes them, which is what ADR-0082 §7 asks for: ADR-0070 §1's
  condition "is that the superseding ADR **exists**, not that it is ratified — the
  hazard §1 names is a `Status` line pointing at nothing, and an atomic pair makes
  that unreachable". ADR-0073's own ADR-0084 note is the exercised form, written
  while the causing ADR was still `Proposed` — "the form ADR-0075 established".
  §11 says why the deferred shape ADR-0086 §11 took is available and worse here.
- **Refs:** ADR-0073 §4 (the floor this turns on), ADR-0077 §6 (the surface split
  and the tombstone precedent), ADR-0085 §4a/§4b/§4/§6b/§8f (the DTOs, their
  invariants, the derived predicates, and the frame arithmetic), ADR-0086 §4/§10
  (`evidence_elided`, its shape, and the deferral this collects), ADR-0091 §1/§6
  (the bounded release and the fork it filed), ADR-0089 (marking), ADR-0070 and
  ADR-0082 (amendment, supersession, and where a record goes), ADR-0103 (the
  quantity this deliberately does not pre-empt; #744).

## Context

### What is on the record, and what is not

ADR-0086 §1 bounds `Provenance.evidence` at `MAX_EVIDENCE_CITATIONS`, and §4
records what the bound displaces on the record itself:

> `evidence_elided: int = Field(default=0, ge=0, description=...)`
>
> **The number of displacements this record's history has performed**, and
> therefore an **upper bound** on the number of distinct citations it no longer
> carries.

§4 also fixes what a rendering of it would say — "**Where a count *is* rendered,
the honest shape is a floor plus a ceiling** — `len(evidence)` citations shown,
and *up to* `evidence_elided` further episodes supported this belief and are no
longer carried" — and what it must not say: "**It is an elision, not a tombstone,
and the two are different facts** … An elision says an evidence item stood here
and **we stopped carrying it**: the episode may be perfectly intact."

The field exists in the tree. `core/types.py`'s `Provenance` carries it,
`memory/ingest.py` maintains §4's recurrence over every install, and
`MemoryStore.export` returns `MemoryRecord`s whole (ADR-0007 §3), so a
data-rights export carries the number.

**What has no home is the inspection surface.** ADR-0085 §4a ratified the two
DTOs the promoted engine returns:

> `beliefs()` returns `tuple[BeliefSummary, ...]`; `belief()` returns `Belief |
> None`. `BeliefSummary` carries `evidence_count` and `lost_evidence` as
> **fields** and has **no `evidence` field at all**. `Belief` is unchanged: it
> carries the resolved `evidence` tuple, and its counts stay derived from it.

| type | `evidence_count` | `lost_evidence` | elided |
| --- | --- | --- | --- |
| `BeliefSummary` | field | field | **nowhere** |
| `Belief` | property over `evidence` | property over `evidence` | **nowhere** |

So a client holding either cannot distinguish sixty-four citations with nothing
displaced from sixty-four with a thousand displaced. ADR-0086 §4 states this
rather than assuming it away, files it as #568, and says where the disclosure
lives meanwhile: "Until it is taken, the disclosure lives on the record and in
`export`, and no surface misreports — it is silent about a quantity it does not
hold, which is a gap in reach, not a false statement."

### The two texts that point in different directions

ADR-0073 §4's floor, on the inspection surface, for a `DERIVED` belief:

> **The floor**, requiring no further read: the surface conveys that the belief
> is derived and how many citations stand behind it, and it **must not present a
> derived belief as carrying a warrant it cannot show.** A citation the surface
> cannot render as evidence is never rendered *as* evidence — not as a reassuring
> id, not silently dropped.

ADR-0086 §10, under "What this ADR does not decide":

> **Whether the inspection DTOs grow a field for the elision**, and its
> rendering. §4, filed as **#568**. `Belief` and `BeliefSummary` are ADR-0085's
> contract surface and neither can carry the count today; the disclosure lives on
> the record and in `export` until that lane rules.

Before ADR-0086 §1's bound nothing could displace, so "how many citations stand
behind it" and "how many the record carries" were one number and the question
could not arise. After it the two can differ, and #624 records that which text
governs is unwritten under either reading: on reading A §10 deferred only the
form and the floor still binds; on reading B §10 deferred the obligation, which
makes it a narrowing of ADR-0073 §4 that owes a record ADR-0086 never wrote and
contradicts ADR-0086 §11's own "ADR-0073 §4's floor is *satisfied* here, not
narrowed".

ADR-0091 declined to settle it, and its §6 says why: resolving it against §10
partially supersedes a section neither #586 nor #606 reported. What ADR-0091 §1
*did* fix is the boundary — its release of ADR-0086 §4's rendering obligation "is
bounded by §4's authority and reaches no other ADR: in particular it neither
narrows nor restates ADR-0073 §4's floor, which binds the inspection surface on
its own". So the floor arrives here intact, and the fork arrives here undecided.

### Read against the tree, because three of the claims are about code

- `core/types.py`'s `BeliefSummary.evidence_count` documents itself in ADR-0073
  §4's words — "How many citations stand behind it, resolved or not" — and its
  class docstring claims the floor outright: "**ADR-0073 §4's floor becomes a
  static guarantee rather than a convention** … It holds how many there are and
  how many are gone, which is what §4 asked the listing to convey." Both are
  exactly right while nothing has displaced, and both stop being right on the
  first displacement, because more citations then stand behind the belief than
  the record carries. ADR-0091 §6 records this as #568's, not its own.
- `orchestration/engine.py`'s `belief_summary_from_record` computes the count from
  the caller's `cited`, and `belief_from_record` reads the whole `MemoryRecord`.
  **Both already hold the record**, so `provenance.evidence_elided` is available
  at both projection sites without a second store read — which is what makes this
  a DTO decision and not a retrieval one.
- `interfaces/cli.py`'s `_why` is one renderer over `Belief | BeliefSummary`,
  reading only the counts both types carry, and `_render_belief_fields` is shared
  for the same reason. A field with one name on both types keeps that single code
  path; a field on one type only forks it.

### Why this is worth deciding before the trigger fires

Nothing misreports today: no shipped belief has displaced a citation, since the
bound is ADR-0086 §1's and nothing predating it could displace. The trigger is
reachable rather than scheduled — ADR-0086 §2 records that "a deployment that has
been running since ADR-0077's observer shipped may already hold a belief above
64", whose next `REINFORCE` displaces — and consolidation (roadmap leg 7) is a
producer of large elisions by construction: a fold over hundreds of episodes
retains the bound and displaces the rest. The day that lands, a user reading a
distilled belief sees sixty-four citations and no indication there were ever nine
hundred, on the one screen whose whole job is "why do you believe that?".

## Decision

### 1. ADR-0086 §10 deferred the *form* of the disclosure, not the obligation

This settles #624, and it settles it for reading A.

> **Normative.** ADR-0086 §10's entry — "Whether the inspection DTOs grow a field
> for the elision, and its rendering" — defers **which type carries the count and
> in what words**, and nothing else. It does not defer, suspend, narrow or
> condition ADR-0073 §4's floor, which binds the inspection surface on its own
> authority and is unaffected by this ADR. A later reader resolving the two
> against each other applies ADR-0073 §4's floor and reads §10 as fixing only the
> form.

**Three things decide it, and the third is the one that makes it more than a
preference.**

- **A section headed "What this ADR does not decide" takes no position.** §10's
  own sentence says the DTOs "are ADR-0085's contract surface", which is a
  statement about ADR-0086's reach, not a licence granted to anyone. Reading a
  disclaimer of authority as an exercise of it inverts what the section is for.
- **ADR-0086 §11 states the conclusion from the other side.** Under its
  "Not owed" list: "ADR-0073 §4's floor is *satisfied* here, not narrowed — §4
  above is what keeps the drop from being silent." That sentence only parses if
  the floor reached the elision, and ADR-0086 §11 is the section that applied
  ADR-0070 §1's test clause by clause. Reading B requires that sentence to be
  false; reading A requires nothing in the corpus to be false.
- **Reading B is unavailable on the record's own rules.** Narrowing a ratified
  floor is a change to what was decided, so ADR-0070 §1 makes it a supersession
  requiring a new ADR and a `Status` edit on ADR-0073, and ADR-0082 §1 requires
  the judgement to be argued in the narrowing ADR's own text. ADR-0086 did
  neither: it named ADR-0073 §4 in §11 expressly to say no record was owed. An
  unrecorded partial supersession is not a thing the corpus can contain — which
  is what makes this a question with an answer rather than a matter of taste.

**ADR-0091 §1's marked clause is consistent with this and does not decide it.**
Its release "is bounded by §4's authority and reaches no other ADR", so it
neither creates the obligation nor removes it. What obligates is ADR-0073 §4, as
it always did.

**No supersession of ADR-0086 §10 is owed, and §11 records why in advance.**
Taking up a question an earlier ADR filed is "a stacked addition to *that* ADR,
which is the treatment ADR-0082 §1 classifies as correct on `main` for ADR-0072
§3 → ADR-0077 §7". A reader holding only ADR-0086 §10 would, however, still
believe the DTO question is open, so §11 below records a dated note rather than
nothing.

### 2. The inspection surface conveys the elision, and `export` is not a substitute

> **Normative.** Where a belief's `Provenance.evidence_elided` is above zero, the
> inspection surface conveys that more citations stood behind the belief than it
> carries. It is not discharged by `MemoryStore.export`, by the record, or by any
> surface other than the one a user reads to ask why a belief is held.

**The argument for "export is enough" is real and it fails on one word.**
ADR-0086 §4 says the record-level obligation "is what makes the truncation
non-silent, which is all ADR-0073 §4 and ADR-0084 §4 require of it". That is true
of the *truncation*: the displacement leaves a trace, so nothing is dropped
silently. But ADR-0073 §4's floor has two halves, and the one it answers is the
second. The first — "**the surface** conveys that the belief is derived and how
many citations stand behind it" — is addressed to the inspection surface by name,
and an export is not it. A user auditing a belief is on the screen ADR-0073 built
for the question; telling them to run an export and count is exactly the "no
further read" the floor's own words rule out.

**And the quantity being an upper bound is a reason to state it, not to
withhold it.** ADR-0086 §4 chose a bound over an exact count deliberately —
"where an exact answer costs the thing the mechanism is for, the mechanism says
less rather than saying something false" — and named ADR-0077 §6's tombstone,
which "deliberately does not say what it was", as the same trade. A tombstone is
rendered. The precedent runs towards disclosing an imprecise fact in imprecise
words, not towards silence.

**What is *not* claimed here.** ADR-0086 §4's floor-plus-ceiling shape already
governs how a rendered count is shaped, and ADR-0091 §1 already governs a surface
rendering both an elision and a tombstone. This clause adds only that the
inspection surface is a surface that renders the count, which the floor decides
and §1 above confirms is undeferred.

### 3. Both DTOs carry `evidence_elided`, as a field, under one name

> **Normative.** `BeliefSummary` and `Belief` each gain a field
> `evidence_elided: int = 0` with `ge=0`, carrying `Provenance.evidence_elided`
> as stored. It is a **field on both** — not a property, not a computed field,
> and not derived from anything either type carries.

**On `BeliefSummary` this is additive and needs no argument beyond §2**: the type
already carries its counts as fields because it has no evidence to derive them
from, and one more count is the same shape for the same reason.

**On `Belief` it is the half ADR-0085 §4a fenced off, and three things decide
it.**

- **It cannot be derived.** §4a keeps `Belief`'s counts derived "from `evidence`"
  because they are counts *over* that tuple. An elision is a count of citations
  the tuple no longer contains; no function of the tuple yields it. The choice is
  a field or nothing.
- **A listing that disclosed more than the detail view would invert the split.**
  ADR-0077 §6 divides the surfaces so the listing "resolves *existence* and
  renders the count" while the single-belief view "renders the surviving
  citations as readable evidence and the lost ones as tombstones" — the detail
  view is the *fuller* answer. Putting the elision only on `BeliefSummary` makes
  drilling into a belief lose information, and it is the single-belief view that
  `forget` shows before destroying a record (ADR-0073 §5), where the warrant is
  what the user is judging.
- **One name keeps one renderer.** ADR-0085 §4a's stated principle is that "the
  same three names read identically on both types", which is "what keeps a
  renderer from needing two code paths". `interfaces/cli.py`'s `_why` and
  `_render_belief_fields` are that shared path today. The name matches
  `Provenance.evidence_elided`, so one quantity has one word from the record to
  the screen.

**Not a `computed_field`, and this is ADR-0085 §6b's rule rather than a fresh
one.** Nothing on this surface serialises a derived value, because a value a
client can compute exactly but one implementation sends and another omits makes
the same call measure two different sizes against ADR-0085 §8c's limit. That rule
does not bear on `evidence_elided`, which is *not* computable by a client — which
is precisely why it must be a plain field carried on the wire, and why it does
not join ADR-0085 §6b's derived-predicate list.

**It moves no figure in ADR-0085 §8.** §8f's belief-page worst case is "fifty
beliefs' own `content` plus a handful of scalars each"; one bounded integer per
row is another scalar. The contract limit is `hub_max_frame_bytes - 512` applied
to the whole payload (§8c) and is unchanged, and §8f's point — that `BeliefSummary`
removes the `beliefs × citations × content` *product* — is untouched, because a
count is not a citation's content.

### 4. No cross-field invariant is added, and the absence is the decision

> **Normative.** No validator relates `evidence_elided` to `evidence_count`,
> `lost_evidence` or `evidence` on either type. `BeliefSummary`'s existing
> `lost_evidence <= evidence_count` invariant is unchanged.

ADR-0085 §4b promotes cross-field invariants with the fields, so their absence
here has to be argued rather than assumed. **There is no true relation to
assert.** `evidence_elided` counts displacements over a record's whole history
and double-counts in two reachable cases ADR-0086 §4 names — a displaced citation
re-cited, and two elided histories folded — so it is an upper bound over a
different population than the retained tuple. It may exceed `evidence_count`, and
`evidence_count` may be zero while it is not.

**Asserting one anyway would invent a read-path failure**, which is the argument
`Provenance` already makes for refusing a `max_length` on `evidence`: a validator
runs on deserialisation, so a rule the store's own records can violate turns a
legitimately-held belief into an unconstructable DTO and breaks `belief()` for it.
`BeliefSummary`'s existing invariant is safe precisely because both of its counts
are taken over one tuple at one instant; this one is not.

### 5. What the surface renders: a floor, a ceiling, and capacity rather than loss

> **Normative.** Wherever a surface renders a belief's citation count and
> `evidence_elided` is above zero, it renders the retained count as a floor and
> `evidence_elided` as an explicit ceiling on further citations, and it conveys
> that those citations were **stopped being carried** rather than lost. Where a
> surface renders no count for a belief, this clause requires nothing of it.

The shape is ADR-0086 §4's, unchanged and not restated as a new rule: "`len(evidence)`
citations shown, and *up to* `evidence_elided` further episodes supported this
belief and are no longer carried". The capacity-not-loss half is ADR-0086 §4's
"the episode may be perfectly intact" and ADR-0091 §1's second marked clause,
which already requires a surface rendering both an elision and a tombstone to
render them so a reader can tell them apart. **This clause adds the trigger, not
the words**: it says *when* the ceiling is owed, and leaves what it says to the
surface, exactly as ADR-0077 §6 left the tombstone's and ADR-0086 §10 intended.

**Conditioning on "wherever a count is rendered" is what settles the band
question mechanically**, rather than by a second ruling. `interfaces/cli.py`'s
`_why` renders a citation count for a `DERIVED` belief and for no other band —
ADR-0073 §4 gives `ASSERTED` its own complete answer ("a user's assertion is its
own warrant … there is nothing further to cite") and gives `ATTESTED` a floor
about source and clock with no count in it. So the obligation lands on the
derived band today and travels by itself if another band starts rendering counts.
For a band that renders no count, ADR-0086 §4's record-and-`export` disclosure
remains what it always was.

*Illustrative and not normative* (ADR-0089 §3): a derived belief carrying
sixty-four citations with none lost and nine hundred elided reads as "I worked it
out from 64 piece(s) of evidence, and up to 900 more stood behind it that I no
longer keep a reference to — those may still exist; I stopped carrying them, they
were not lost." The implementing lane owns the wording.

### 6. `evidence_count` keeps its value and loses its wording

> **Normative.** `evidence_count` on both types continues to mean **how many
> citations the belief carries** and its value is unchanged. Its documented
> meaning is corrected to say so, and ADR-0073 §4's "how many citations stand
> behind it" is answered by the **pair** `evidence_count` and `evidence_elided`,
> never by `evidence_count` alone.

This is #568's second half, which ADR-0091 §6 explicitly left here: the field
"reads 'How many citations stand behind it, resolved or not', which is ADR-0073
§4's phrase and which the retained count stops answering after a displacement".

**Changing the wording rather than the value is the whole of the fix.** The number
is correct and every consumer of it is correct: the presented confidence is a
function of how many citations *resolved* out of how many are *carried*
(ADR-0077 §6), the listing's tombstone count is over the same population, and
ADR-0085 §4b's invariant relates two counts over one tuple. Redefining
`evidence_count` to include elisions would break all three at once and would put
a number on the type that no citation corresponds to. What was wrong is a
description that promised the floor's wider question; what answers that question
is now two fields.

### 7. `unsupported` keeps its ratified definition, and its rendering gains a qualifier

> **Normative.** `unsupported` is unchanged on both types — `evidence_count > 0
> and lost_evidence == evidence_count`, one definition everywhere (ADR-0085 §4a).
> A surface rendering an `unsupported` belief whose `evidence_elided` is above
> zero does not state that nothing supports the belief; it states that every
> citation the belief still carries has gone, and that up to `evidence_elided`
> further citations stood behind it whose fate this surface cannot report.

**The predicate is right and the sentence built on it is not.** `interfaces/cli.py`'s
`_why` renders an unsupported derived belief as "…none of which still exists. I
still hold it … but **nothing supports it any more**." For a belief that also
elided nine hundred citations that is a false statement in the direction ADR-0073
§4 forgives least: ADR-0086 §4 rules that "an elided citation is not unresolved,
and the belief did not lose support — the record lost the reference", so those
episodes may be intact and still supporting it.

**Redefining the predicate was considered and refused.** Adding `and
evidence_elided == 0` would make the same belief report `unsupported == False`,
which is no better founded: nothing on the record says whether an elided citation
still resolves, because resolving it is what the discarded id was for. Neither
value is a confident answer, so the honest repair is at the sentence, where "we
cannot say" is expressible, and not at a boolean, where it is not. Keeping the
definition also keeps ADR-0085 §4a's "one definition everywhere" and §6b's
derived-predicate list exactly as ratified.

### 8. What the implementing lane owes

Its own PR, after this ADR is ratified (golden rule 5). The fence is
`core/types.py`, the two projections, the CLI, the canonical fake and their
tests; it needs no `core/protocols.py` change, because no signature moves.

1. **`core/types.py`** — `evidence_elided: int = Field(default=0, ge=0, …)` on
   `BeliefSummary` and on `Belief`, in the declaration order ADR-0085 §4's table
   fixes for the rest of each type, with the field appended. No validator (§4).
   `BeliefSummary`'s class docstring and `evidence_count`'s description are
   corrected per §6; `Belief.evidence_count`'s property docstring likewise.
2. **`orchestration/engine.py`** — `belief_summary_from_record` and
   `belief_from_record` each pass `record.provenance.evidence_elided` through
   unchanged. **No rounding, no clamping, and no recomputation**: ADR-0086 §4's
   `export` rule is that the stored number travels so "the bound's imprecision
   travels with the field rather than being resolved in the artifact", and a
   projection that clamped it to the retained count would resolve exactly that
   imprecision wrongly.
3. **`presented_confidence` is not touched.** ADR-0086 §4 is explicit: "Feeding
   elisions into that function would lower a belief's presented confidence because
   the system worked, which inverts the signal." Its arguments stay `cited` and
   `resolved` over the carried tuple.
4. **`interfaces/cli.py`** — `_why`'s derived branches gain the ceiling per §5 and
   the unsupported branch is repaired per §7. `_render_evidence` is **not**
   touched: an elision is not an `Evidence` entry and must not be rendered in the
   citation list, where ADR-0091 §1's second clause makes it indistinguishable
   from a tombstone.
5. **`testing/engine.py`** — `_summary_of` carries the field through, so the
   canonical fake and the real projection agree.
6. **Tests** — a projection test at each site that a non-zero `evidence_elided`
   reaches both DTOs; a rendering test that a derived belief with elisions states
   the ceiling and does not call them lost; a rendering test that an
   `unsupported` belief with elisions does not say nothing supports it; and a
   round-trip through `wire/codec.py` (which projects generically over
   `model_dump`, so it needs no edit, and a test is what proves that).
7. **Nothing under `docs/adr/`.** The three records §11 owes land with this ADR,
   not with the implementation, so that lane's fence is `src/` and `tests/` only.
   The one `docs/adr/` edit still outstanding after this change is the
   `Proposed` → `Accepted` flip, which is a separate trivial ratification PR
   (`CONTRIBUTING.md` → "Trivial ADR edits"; #633 records why it cannot ride
   here).

### 9. Explicitly declined

- **Carrying the elided ids.** They are the payload ADR-0086 §1 exists to stop
  carrying, and the bound would be defeated by the field that discloses it.
- **Rendering elisions as `Evidence` entries.** `Evidence` has one nullable field
  and a lost citation is one whose content is `None`, so an elision entry would be
  a tombstone to every reader — the exact conflation ADR-0091 §1's second clause
  forbids and ADR-0086 §4 calls "telling the user their data was lost when it was
  not". It would also need one entry per elision for a number that is an upper
  bound, not an enumeration.
- **A boolean `evidence_elided: bool` in ADR-0085 §9's `details_elided` shape.**
  ADR-0086 §4 already ruled on the pair: `details_elided` "marks a loss whose size
  the *client* cannot know, so a boolean is all that is honest there", while this
  one "marks a capacity decision the *writer* made and can count". A flag would
  discard a magnitude the record holds.
- **A total field (`evidence_count + evidence_elided`).** ADR-0086 §4 refuses it:
  reporting the sum "as an exact *total* overstates it in the two collision cases",
  and a client that wants it can add two numbers whose separate meanings it can
  see.
- **Making `beliefs()` or `list_beliefs` order or filter on the count.** ADR-0086
  §4 keeps both order-neutral and confidence-neutral, on ADR-0077 §6's ground that
  "a number computed at presentation cannot reorder a store it never touches".
  Nothing here is a ranking input.
- **Reaching `Goal.provenance`.** ADR-0086 §1 scopes the bound to `MemoryRecord`
  installs, so a goal's `evidence_elided` is always zero, and ADR-0077 §11 owns
  that path. No goal surface changes.

### 10. What this ADR does not decide

- **Where ADR-0103's currency lives on these DTOs.** ADR-0103 ratifies that
  confidence is two quantities, and neither `Belief` nor `BeliefSummary` carries a
  currency today. That is #744's, the split's implementing lane, and it is
  deliberately not pre-empted: this ADR adds one field for a different reason and
  does not open the two types to that lane's question. If #744 concludes the
  inspection surface needs a currency, it decides its own field, its own name and
  its own rendering — including whether `confidence` on these types stays one
  number, which is a question this ADR takes no position on.
- **Whether `Provenance` should record which connected source attested a belief,
  and whether the belief DTOs should carry it.** ADR-0092 §1 answered the first;
  the second is ADR-0073 §4's other open gate and is not this field's question.
- **When the first displacement happens.** ADR-0091 §6 declined to schedule it and
  so does this: the condition is stated, the calendar is not.
- **Anything about consolidation.** Leg 7's consolidation lanes are the producer
  that makes large elisions ordinary, which is why this is worth deciding now, but
  nothing here bounds, schedules or shapes them.
- **`MemoryStore`, `MemoryWriter` or `AssistantEngine` signatures.** No Protocol
  changes; §8 states the fence.

### 11. Records owed on earlier ADRs, under ADR-0082 §1

ADR-0082 §1 requires the judgement to be made in this ADR's text, clause by
clause, against ADR-0070 §1's test: *would a reader holding only the earlier ADR
now act differently, or read one of its clauses more widely than it now holds?*

**Owed — ADR-0085 §4a and §4's `Belief` and `BeliefSummary` rows, as a partial
supersession.** §4a's marked clause reads:

> `BeliefSummary` carries `evidence_count` and `lost_evidence` as **fields** and
> has **no `evidence` field at all**. `Belief` is unchanged: it carries the
> resolved `evidence` tuple, and its counts stay derived from it.

"**`Belief` is unchanged**" becomes false: §3 above gives it a field. §4's table
is headed "the twenty-four promoted types and their **normative** fields", so a
reader building either type from it now ships an incomplete one and fails
conformance. That is a change to what was decided, so under ADR-0070 §1 it is a
**partial supersession** of ADR-0085 §4a and of §4's `Belief` and `BeliefSummary`
rows, in the shape ADR-0086 §11 used for ADR-0040 and ADR-0074. ADR-0085's
`Status` is a plain `Accepted`, so under ADR-0070 §4 and ADR-0082 §2 it takes the
leading `Partially superseded by ADR-0107 (…)` token with the scope named, plus
the dated note.

**Three parts of §4a survive verbatim and the record says so**, because the scope
matters more than the token: `BeliefSummary` still has no `evidence` field and
still carries its two counts as fields; `Belief`'s `evidence_count` and
`lost_evidence` are still derived from `evidence` (§6); and `unsupported` still
has one definition on both types (§7). What is replaced is only the completeness
of the field lists and the absoluteness of "unchanged". §4a's deciding reason —
that a `BeliefSummary` has nowhere to put a citation's content, so a conforming
listing cannot over-deliver — is untouched and is the reason §3 adds a **count**
and not a tuple.

**Also carried in the same note, as an amendment rather than a supersession**:
§4a's "It holds how many there are and how many are gone, which is what §4 asked
the listing to convey." That was true when written and is completed rather than
reversed — after §6 the floor's question is answered by the pair. A reader acting
on it acts identically, which is ADR-0070 §1's test, so it is a stale phrase in
that section's first bucket. It rides in the note ADR-0082 §2 already requires
rather than earning a second record.

**Owed — ADR-0086 §10, as a dated note and not a supersession.** §10's second
entry says the DTO question is open and "the disclosure lives on the record and
in `export` until that lane rules". This ADR is that lane, so a reader holding
only ADR-0086 would still believe the question open — the ADR-0082 §1 trigger,
and the same one ADR-0073's 2026-08-02 note answered when ADR-0092 discharged its
`core` question. Collecting a deferral an earlier ADR filed is a stacked addition
and not a supersession (ADR-0086 §11's own treatment of ADR-0077 §6), and
ADR-0086's `Status` already leads with `Partially superseded by ADR-0091`, so
under ADR-0082 §2 the record is the dated note and nothing is written on the
`Status` line. §1 above is what the note records; ADR-0086 §4's rulings, its
recurrence, `export`'s carriage and the confidence-neutrality rule are all
untouched.

**Owed — ADR-0091 §6, as a dated note.** Its first two entries defer "how an
inspection surface conveys the elision, and on which type" and "whether ADR-0086
§10's deferral … reaches ADR-0073 §4's floor — filed as #624", and its fifth
defers `BeliefSummary.evidence_count`'s documented meaning to #568. All three are
decided above, so a reader holding only ADR-0091 would still believe them open.
Nothing ADR-0091 **decided** changes: §1's first marked clause is relied on here
exactly as written, and its second is satisfied by §5 and §9 rather than
narrowed. ADR-0091's `Status` is a plain `Accepted` and takes no token, because
no clause of it is superseded; the record is the dated note ADR-0082 §1 requires.

**Not owed — ADR-0073 §4.** Its floor is applied here as ratified and is neither
widened nor narrowed: §1 above finds it was never deferred, and §2 finds the
inspection surface is where it always pointed. A reader holding only ADR-0073 §4
acts identically before and after. Its `DERIVED` gate ("resolving citations into
readable evidence") and its `ATTESTED` gate are both untouched. This is the same
finding ADR-0086 §11 made and ADR-0091 §1 preserved; making good on it is not a
change to it.

**Not owed — ADR-0077 §6.** Its surface split, its lazy resolution, its tombstone
and its presented-confidence function are all used exactly as written; §5 and §7
above are what keep an elision from being rendered as, or folded into, any of
them. §6's "small by construction" premise was already addressed by ADR-0086 §11
and is not touched again here.

**Not owed — ADR-0086 §4.** Its floor-plus-ceiling shape and its
elision-is-not-a-tombstone rule are *performed* here, not modified. §4's own
statement that the DTOs cannot carry the count — "as the promoted surface
stands" — was a true observation about the surface as it then stood, and §4
itself scopes it with "Until it is taken". A phrase that anticipated a later ADR
and is discharged by it is a stacked addition (ADR-0082 §1's ADR-0072 §3 →
ADR-0077 §7 precedent, and ADR-0086 §11's own §8e treatment). The §10 note above
carries the reader-facing half.

**Not owed — ADR-0084 §4, ADR-0085 §8 and ADR-0087.** ADR-0084 §4's rule that the
size limit is contract and every implementation enforces it is unchanged; ADR-0085
§8's figures do not move (§3), and §8f's argument is about a product this field is
not a factor of; ADR-0087 fixes the encoding an integer already had.

**Not owed — ADR-0085 §6b and §4b.** §6b's derived-predicate list is unchanged
because `evidence_elided` is a field and not a predicate (§3), and §4b's invariant
table is unchanged because §4 adds none.

**Not owed — ADR-0103.** §10 defers currency's representation to #744 rather than
deciding it, and adding an unrelated count to two DTOs neither settles nor
forecloses where a currency lives. ADR-0103's own §5 is untouched.

**All three edits land in this change, and the deferred shape is refused.**
ADR-0086 §11 took the other route, reasoning that "ADR-0070 §1 permits 'recording
a supersession **that has landed**', and a `Proposed` ADR's decision has not".
**ADR-0082 §7 names that reading as the recurring failure it is** — filed as #458,
"not a governance gap but a reviewer failure mode" — and states §1's condition
outright: "§1's condition is that the superseding ADR **exists**, not that it is
ratified — the hazard §1 names is a `Status` line pointing at nothing, and an
atomic pair makes that unreachable." ADR-0082 is ratified and later than the
reading it corrects, and ADR-0073's ADR-0084 note is the exercised atomic form,
written while ADR-0084 was `Proposed`.

**Deferring is permitted and is worse here, for three reasons specific to this
lane.** ADR-0086 §11's second reason was that "two lanes are writing under
`docs/adr/` this wave, so the edits need ordering that this lane does not own" —
true there, and inapplicable here: the two lanes in flight write a new ADR file
and a `Status` flip on a third, and neither touches ADR-0085, ADR-0086 or
ADR-0091. Its third was that a later review round could move the decision — which
is an argument *for* atomicity, since a note in the same change moves with it and
one in a following change silently does not. And the interval matters more here
than it did there: a `main` carrying ADR-0107's "`Belief` gains a field" beside
ADR-0085 §4a's "`Belief` is unchanged", with no pointer in either direction, is
two live documents stating one thing at two widths — #477's failure, and the one
ADR-0089 §5 exists to stop. **What ADR-0082 §1 puts in this text is the
judgement**, quoted and argued above where this review reaches it; the edits
transcribe it, in the same commit.

## Consequences

**Easier.** The one screen whose job is "why do you believe that?" answers it
completely for the first time since ADR-0086 §1's bound made it possible for the
answer to be incomplete. A client of `AssistantEngine` — the CLI, a spoke, any
later surface — can distinguish a belief with sixty-four citations from one with
sixty-four and nine hundred displaced, using two fields it can read on either DTO
without a second call. Consolidation can land without taking the inspection
surface's honesty with it, which is the reason for deciding this before its
producer exists rather than after.

**Harder.** Two more fields cross the wire on the largest response this surface
produces; ADR-0085 §8's arithmetic absorbs them (§3), but the belief page is the
worst case and its worst case grew, however slightly. Every future surface that
renders a citation count now owes a ceiling beside it, and the `unsupported`
predicate now has a rendering rule attached that a naive consumer will not know
about — the price of keeping the predicate's ratified definition (§7). And the
corpus gains one more clause pair — `evidence_count` and `evidence_elided` — that
must be read together to answer one question, which is a shape a reader can
half-read.

**What would trigger revisiting this.** Three things, named so a later lane does
not have to derive them. If #744 gives the inspection DTOs a currency, the
question of how many scalars this surface should carry before it wants a nested
provenance object is worth asking once rather than four times. If a producer ever
needs the *identities* of elided citations — a consolidation audit, say — that is
a change to ADR-0086 §1's bound and not to this ADR, and it would make this field
a lower-resolution view of something richer. And if the two collision cases
ADR-0086 §4 names turn out to be common rather than reachable in practice, the
upper bound may be wide enough that "up to N" stops being useful information, at
which point the honest move is to say the count is unreliable rather than to
quietly keep rendering it.

## Alternatives considered

**Answer "never": leave the disclosure on the record and in `export`.** The
narrowest reading of ADR-0086 §10 permits it, and it costs nothing to build. It
fails on ADR-0073 §4's first half, which addresses the *surface* by name and
rules out "requiring no further read" (§2), and it would leave the corpus with an
unrecorded narrowing of a live floor (§1). It also degrades exactly as
consolidation scales, so the moment it becomes wrong is the moment the store
becomes valuable.

**Put the field on `BeliefSummary` only.** Cheapest, additive, and it needs no
record on ADR-0085 §4a — which is what makes it tempting. Refused in §3: the
single-belief view would then disclose less than the listing it was drilled into,
and it is the single-belief view that `forget` renders before destroying a record.

**Put the field on `Belief` only.** Defensible on the ground that the detail view
is where a warrant is judged, and it keeps the listing's field count down. Refused
because the listing renders a citation count on every row (`_why` is shared), so
every row would carry the floor with no ceiling — the under-claim ADR-0077 §6
glosses as "a silent gap".

**Redefine `evidence_count` to include elisions.** It answers ADR-0073 §4's
question in one number and needs no new field. Refused in §6: it breaks the
presented-confidence computation, ADR-0085 §4b's invariant and the tombstone count
in one move, and it puts a number on the type that no citation corresponds to —
while ADR-0086 §4 has already ruled that reporting the sum as a total is the
overstatement its two collision cases make false.

**Widen `Evidence` to carry an elision marker.** It keeps the citation list as the
single home for everything about a belief's warrant. Refused in §9: `Evidence` has
one nullable field, so the marker is a tombstone to every reader, and the count is
a bound rather than an enumeration.

**Settle #624 the other way — rule that ADR-0086 §10 deferred the obligation.**
This is #624's reading B, and it is the only alternative that changes §1 rather
than §3. It would require partially superseding ADR-0073 §4 in this ADR, writing
ADR-0086 the record it never wrote, and finding ADR-0086 §11's "not narrowed"
false. Refused because reading A requires nothing in the corpus to be false and
reading B requires two things to be — and because an ADR cannot narrow a floor by
declining to decide about it.
