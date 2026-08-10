# 127. Withdrawing a proposal that was never ratified

- Status: Proposed
- Date: 2026-08-10
- Partially supersedes: ADR-0070 — §1's enumeration of permitted in-place header
  edits and §4's canonical status vocabulary, each only as it reaches an ADR that
  stands `Proposed` and is withdrawn. Everything else of both sections stands:
  §1's amend-vs-supersede test, its append-only mechanism, its four existing
  permitted edits and its protection of ratified decision text; §4's
  partial-supersession grammar, its one-physical-line rule, its accumulation and
  precedence rules, its no-retrofit rule, its whole-field consumer rule and its
  transitive walk. §7 applies ADR-0070 §1's test to each and states what
  survives. **No `core` surface is decided** — no Protocol in
  `core/protocols.py`, no type or member in `core/types.py`, `PROTOCOL_VERSION`
  untouched — and **no implementation lands with it**: no `src/`, no `tests/`.
- **Every reference below to ADR-NNNN is to its text as merged on 2026-08-10**,
  the durability form ADR-0100 established and ADR-0125 and ADR-0126 followed.
  ADR-0070 §4 carries an amendment dated 2026-07-31 and §1 two more, and this
  decision turns on the exact wording of both sections, so a citation meaning
  "whatever it says when you read it" would not be checkable.
- **Its required review set is adversarial alone.** No `core` path is touched, and
  `scripts/ship.sh` fires its architecture requirement on `core/protocols.py` or
  `core/types.py` alone. This is the reading ADR-0082, ADR-0088, ADR-0089 and
  ADR-0090 each took for a corpus-form decision, and `docs/adr/**` being in
  ADR-0027 §3's review floor bears on what a base move costs, not on which lens is
  required.
- **This ADR exists because a lane hit the gap, not because the gap was
  theorised.** PR #913 was dispatched to withdraw ADR-0043 on the operator's
  ruling and blocked three times on the same objection: ADR-0070 permits no such
  edit. The Context below is that lane's evidence.
- Refs: #898 (the ruling that found the gap), #913 (the blocked withdrawal, which
  lands after this ADR), #914 (the template's vocabulary, closed by §6).

## Context

### A merged `Proposed` ADR has exactly one exit, and the corpus needed a second

ADR-0015 §5 and `CONTRIBUTING.md` → "Contract ADRs land before their
implementation" put a substantive ADR on `main` as `Proposed`, reviewed "while it
is still `Proposed`, so a finding can still change the decision", and ratified
afterwards by a separate edit. The state is deliberate and it is durable: the
document is merged, citable and inert until someone flips it.

Every rule the corpus has written for that state describes the same exit. ADR-0070
§1's first permitted in-place header edit is "ratifying an ADR — `Proposed` →
`Accepted`". `CONTRIBUTING.md`'s "Trivial ADR edits" names "the `Proposed` →
`Accepted` ratification flip". `docs/adr/template.md` offers `Proposed | Accepted
| Superseded by … | Partially superseded by …`. Nothing anywhere says what happens
when the answer is **no**.

That was tolerable while it had not happened. It has now happened.

### ADR-0043 is the case, and it is not disposable under the rules as they stand

ADR-0043 merged `Proposed` on 2026-07-23 (PR #272), proposing to replace two
inferences in the review tooling — retirement inferred from a finding's absence in
`codex-review.sh` `_write_snapshot`, and the fence heuristic in
`render_dispositions` — with explicit reviewer-emitted markers, behind its own
ratify-before-build gate. That gate never released it. In the 17 days between its
merge and this ADR, 257 pull requests merged, every one reviewed through those
same inference mechanisms, including loops that ran past round 20, and the
operator's ruling of 2026-08-09 on #898 records no wrong merge attributable to a
dropped finding across that load. The ruling is that the evidence decided it:
withdraw, do not implement.

The document is therefore neither ratifiable nor, under the rules as they stand,
disposable. Left as `Proposed` it reads as a live proposal still pending a
decision that has in fact been made — which is what #898 was filed about in the
first place, from the opposite direction: a document standing `Proposed` while
ADR-0089 §2 cited it as precedent.

### Both halves of the objection are ratified text, and both are correct

PR #913 flipped the status to `Withdrawn` and was blocked three times. Two clauses
carry the objection.

ADR-0070 §1, on in-place header edits:

```text
In-place edits to the header lines are permitted only where they change no
decision (§1's test applied to the Status field and header themselves):
```

followed by four bullets — ratifying, recording a landed supersession, correcting
a status line to match what landed, adding a dated header note. None is a
withdrawal.

ADR-0070 §4, on the vocabulary:

```text
The canonical vocabulary is §4's four forms, `Partially superseded` carrying one
or more `ADR-XXXX (<scope>)` pairs (its accumulation and precedence rules below).
```

`Withdrawn` is not among them. Two answers were attempted in that lane and both
failed. The first — that §1 governs only the amendment of a document that decided
something — is defeated by §1's own first bullet, which addresses a never-ratified
record. The second — that §4's sentence is scoped to its consumer-collapse rule —
is arguable but does not carry a fifth form into a vocabulary §4 calls canonical.

### The corpus's own method for a ratified rule that misses a real case is an ADR

ADR-0090 is the precedent and it is exact. ADR-0088 §6 put "a decision citation
naming an **ADR file that does not exist**" in the tier that may fail a build; a
legitimate case appeared that the rule misclassified — a citation to a number that
was assigned and never written — and the answer was a new ADR **partially
superseding §6**, not a lane reasoning that the tier boundary was illustrative.

ADR-0082 §1 is the same posture from the other side. #537 reported that ADR-0070
§1's two amendment triggers did not cover an ADR that misstated a fact predating
it, and proposed either widening the enumeration or "demoting it to illustrations
of the operative condition". **Neither was taken.** The case was resolved by
showing it was already inside a trigger — and where that showing is unavailable,
as it is here, what remains is an ADR.

So the objection is upheld, and this is the document it asks for.

## Decision

### 1. Withdrawal is a fifth permitted in-place header edit, available from `Proposed` alone

> **Normative.** An ADR whose `Status` field reads exactly `Proposed` may be
> withdrawn by an in-place edit replacing that field with `Withdrawn`. This is a
> fifth permitted in-place header edit under ADR-0070 §1, and it is available from
> that status alone: no edit withdraws an ADR whose `Status` is `Accepted`,
> `Superseded by` or `Partially superseded by`, and a change to what such an ADR
> decided remains ADR-0070 §1's supersession side.

**The restriction is the whole safety of the rule, and it is where ADR-0070 §1's
test is actually satisfied.** §1 permits an in-place header edit "only where
[it] change[s] no decision", and asks whether "a reader acting on the ADR would
act **identically** before and after". For a `Proposed` document the answer is
yes and it is not a close call: the document is in force under neither status, so
a reader acting on its decision has no decision to act on either way. What
changes is what an *author* would do next, and §1's test cannot be about that
without failing the ratification flip it expressly permits.

For an `Accepted` document the answer is no, and obviously so. Withdrawing a
decision the corpus has been acting on is the largest possible change to what was
decided, so it is exactly what §1 sends to a superseding ADR — and this ADR does
not touch that route. **The rule is deliberately narrower than "an ADR may be
withdrawn".** It is "a proposal that was never adopted may be closed", which is
the case that exists and the only one whose safety the argument above establishes.

**Withdrawing is not refusing to ratify in silence.** An author who simply never
flips a `Proposed` ADR leaves the state this ADR exists to end. The edit is the
act of deciding not to adopt, and §3 requires it to say so.

### 2. `Withdrawn` is terminal

> **Normative.** `Withdrawn` is terminal. No edit returns a withdrawn ADR to
> `Proposed` or advances it to `Accepted`. A later decision on the question it
> raised is a new ADR with its own number, which may cite the withdrawn document
> but does not revive it.

**Terminality is what keeps the status honest rather than merely convenient.** A
revivable `Withdrawn` would be a pause button, and a document parked in it would
carry no information: a reader could not tell a proposal that was rejected on
evidence from one whose author lost interest. Terminal, the status means one
thing.

It also protects the review record. A `Proposed` ADR is reviewed while `Proposed`
so that a finding can still change the decision (ADR-0015 §5); a document revived
years later would carry a review of text nobody has re-examined against the corpus
it would rejoin. Requiring a new ADR forces that re-examination, and costs
little — the withdrawn text is still there to be read, quoted, or copied wholesale
into the new document.

### 3. The withdrawal is recorded in a dated note, in the same change

> **Normative.** The edit of §1 is made together with an appended dated header
> note, in the same change, stating the date of the withdrawal, the authority that
> ruled it, and the ground.

> **Normative.** A `Status` of `Withdrawn` carrying no such note is a defective
> record and not a withdrawal: §1 is unsatisfied, the ADR is not withdrawn, and §2
> does not bind it. It is corrected in place — by appending the note the
> withdrawal owed, or by restoring `Proposed` — under ADR-0070 §1's third
> permitted edit, correcting a `Status` line to match what actually landed.

**A bare `Withdrawn` would be a state claim with no record behind it**, which is
the shape ADR-0019 refuses and ADR-0070 §1 already avoids for every other status
edit it permits: a supersession names the ADR that landed, a ratification records
the review outcome ("the ratifying edit records that review's outcome, it does not
replace it"). Withdrawal names no ADR — there is none — so the note is the only
place a record can live, and requiring it is what stops the field becoming an
unexplained flag.

**The three required contents are the three questions a reader of a withdrawn ADR
asks**, and each is answerable at the moment of the edit and nearly unrecoverable
later: when, on whose authority, and on what ground. The note is an appended dated
header note, which is ADR-0070 §1's fourth permitted edit, so §3 adds a
requirement to an edit already permitted rather than a new kind of edit.

**§3's two clauses bind an author; §4's binds a consumer; and they key on
different things deliberately.** The author is obliged to write the note. The
consumer is not obliged — and must not be asked — to check that it is there,
because ADR-0088 §6 forbids a checker to read prose or infer document structure,
and "is there a dated note below this line, and does it name an authority" is
exactly that inference. So §4 keys on the token alone and §3's second clause
governs the record, not the read. **A note-less `Withdrawn` is an authoring
defect, corrected by an edit rather than detected by a consumer**, and the
consequence of leaving it uncorrected is bounded: a consumer reads it as holding
no live rule, which is the same answer it would have reached while the ADR stood
`Proposed`, since a proposal holds no live rule either. Nothing becomes live, and
nothing live becomes dead — only the record is poorer, which is what §3's second
clause makes correctable.

**Whether any tool reports the defect is left open, as ADR-0089 §7 left the
equivalent question open** for a malformed mark: no tier, no gate step, no hook is
decided here. That an author could reach a restored `Proposed` by first writing a
defective withdrawal and then correcting it is not a loophole worth armouring
against — it is two visible edits to a floor path in the history of a document
whose whole purpose is to be read, and the corpus armours nowhere against an
author acting in bad faith.

### 4. `Withdrawn` in the vocabulary, and what a consumer does with it

> **Normative.** `Withdrawn` is a canonical status form under ADR-0070 §4. Its
> whole value is the bare token: it carries no `ADR-NNNN`, no scope parenthesis
> and no qualifier, so it names no supersession target and enters no supersession
> read. A consumer that classifies liveness reads a `Withdrawn` ADR as holding no
> live rule and as naming no ADR to defer to, keying on the token alone and never
> on the presence of §3's note; ADR-0070 §4's transitive walk neither begins nor
> continues at it.

**The bare token is ADR-0082 §2's reasoning applied to a new leading token.** §2
keeps a leading-token status line clean and puts the record four lines lower in
the dated note, because the field's machine-legible job is small and the reader
who needs the substance is reading the ADR. §3 above already puts the withdrawal's
substance in a note on the same screen, so nothing is lost by keeping the value to
one word — and a qualifier-bearing `Withdrawn … — …` line would be a second place
the ground could be stated, and so a second place it could disagree with itself.

**`Withdrawn` cannot cause the failure ADR-0070 §4 was built against, and closes
it off.** §4's hazard is #87's: a superseded ADR read as fully current, its
replaced scope hidden, which is why "the supersession leads; `Accepted` is
dropped". A withdrawn ADR has no live remainder to hide. The one error available
is the opposite — a consumer that does not recognise the token drops the record
from a live-rule collection, which is the correct answer for a document that never
held a rule — and the collapse §4 forbids, reading it as `Accepted`, is made
impossible by the token not containing that word.

**This adds a form to §4; it changes nothing §4 decided about the others.** The
supersession grammar, the `ADR-XXXX (<scope>)` pairs and their accumulation and
precedence, the one-physical-line rule, the no-retrofit rule and the whole-field
consumer read are untouched, and no existing status line is rewritten by this ADR.
`Withdrawn` is one physical line by construction.

### 5. Withdrawal is not deletion

> **Normative.** Withdrawal does not remove the document. A withdrawn ADR's file,
> number and text stay in the corpus, its Context, Decision and Consequences are
> not rewritten, and its number is never reissued. A citation of a withdrawn ADR
> for what its text says — its form, its reasoning, or a fact it records — is
> unaffected by the withdrawal; what a withdrawn ADR no longer offers is an
> obligation.

**This clause exists because the case is already on `main`.** ADR-0089 §2 cites
ADR-0043 as the precedent for column-0 markers — "a marker that may be indented is
a marker whose block boundary depends on the enclosing structure" — and that
citation is a claim about ADR-0043's *text*, which withdrawal does not touch.
Without this clause a reader could take ADR-0043's withdrawal as breaking a
ratified ADR's grounding, and a checker author could take it as licence to fail
the citation. Neither is right: ADR-0089 §2's precedent survives, and so does
every other historical claim the corpus makes about a withdrawn document.

**Keeping the file is also required by rules this ADR does not touch.** ADR-0001's
sequential numbering and append-only history, and ADR-0088 §6's Tier 1 failure for
a decision citation naming an absent ADR file, both assume the file stays; ADR-0090
exempts only a number in a gap that was *never issued*, which a withdrawn ADR is
not. Deleting a withdrawn ADR would break live citations and leave a hole no rule
describes.

### 6. `docs/adr/template.md` gains the form in this change, and #914 closes

The template edit rides with this lane rather than being directed elsewhere,
because **ADR-0070 §4 is the precedent and it is the same section, the same file
and the same field**: §4 wrote "`docs/adr/template.md` gains the partial form"
and wrote it, on the ground that "the template carries the vocabulary itself".
A vocabulary decided here and absent from the one document an author meets when
writing an ADR is a gap that defeats the next author, and it is one line.

That is the narrower of the corpus's two dispositions and the reason for choosing
it is the difference between the cases. ADR-0088 §5 and ADR-0089 both *directed* a
`CONTRIBUTING.md` or template correction and filed it (#595, and ADR-0089's own),
each because the edit was a body of authoring guidance beyond the deciding lane's
fence. This one is a token in an enumeration the ADR is itself amending. #914 was
filed from PR #913 for exactly this edit, before this ADR existed to carry it; it
closes with this change.

**`CONTRIBUTING.md` needs nothing.** It carries no status vocabulary, and its
"Trivial ADR edits" paragraph is about *review cost* — which edits skip a separate
review of the edit itself. This ADR decides permission, not cost, and makes no
claim that a withdrawal is trivial to review: PR #913's own withdrawal note is
substantive and took a real review. ADR-0070 §5's reconciliation of that paragraph
with §1's test stands unchanged.

### 7. Records under ADR-0070 §1 and ADR-0082 §1

**ADR-0070 §1 — partially superseded, one clause, and the record lands in this
change.** The clause is §1's "In-place edits to the header lines are permitted
only where they change no decision" together with the four bullets enumerating
them. ADR-0070 §1's own test: a reader holding only §1 would read the enumeration
as closed — which is how the corpus reads its enumerations, ADR-0082 §1 having
declined to demote one to illustrations — and would conclude that a merged
`Proposed` ADR ruled against can never be disposed of: not ratifiable, because the
ruling is no, and not withdrawable, because no bullet names it. That is a clause
read more widely than it now holds, ADR-0070 §1's second limb, and it requires a
supersession rather than an amendment. It is narrow in the way ADR-0090's was: one
status, named, with the rest of the section standing — the amend-vs-supersede test
itself, the append-only mechanism, the protection of ratified decision text, and
all four existing permitted edits, none of which this ADR alters or reorders.

**ADR-0070 §4 — partially superseded, one clause, and the record lands in the same
change.** The clause is "The canonical vocabulary is §4's four forms". ADR-0070
§1's test: a reader holding only §4 would reject `Withdrawn` as non-canonical and
would have no form in which to record §1's newly permitted edit, so the two
sections would disagree — the first permitting an edit whose value the second
forbids. Again the clause is read more widely than it now holds. Everything else
of §4 stands and is listed in the header above; §4's own reservation of its rule
to "any liveness-classifying consumer added later" is not narrowed but **supplied
for one more form**, which is what §4 asked of whoever added one.

**Both records are written here.** ADR-0070's `Status` line is a bare `Accepted`
carrying no leading token and no qualifier, so it takes the leading-token form
with one `ADR-0127 (<scope>)` pair whose scope names clauses and no ADR (ADR-0070
§4's authoring constraint), and it gains an appended dated `Partially superseded:`
note carrying the substance (ADR-0070 §1, ADR-0082 §1 and §2). No ratified text of
ADR-0070 is rewritten.

**ADR-0082, ADR-0088, ADR-0089, ADR-0090 and ADR-0001 — nothing owed.** ADR-0082
§1's test is applied here, not narrowed, and §2's leading-token reasoning is
extended to a new token by analogy rather than amended; ADR-0088 §1's citation
forms and §6's tiers are unchanged, and §5 above shows why its Tier 1 rule is
undisturbed; ADR-0089 §2's marking form is used by this document and §5's
forward-only rule is obeyed rather than touched — this ADR is marked; ADR-0090's
gap exemption is cited for what it excludes and is not widened; ADR-0001's
sequential numbering, append-only history and one-file-per-decision structure are
each relied on by §5 and none is altered. Every one is a **stacked addition** under
ADR-0082 §1: no sentence of any of them becomes false or over-wide.

**ADR-0019 — nothing owed.** Its subject is a state claim in a *living* document.
An ADR is a dated record, and §3's dated note is the corpus's established form for
exactly this.

## Alternatives considered

**Leave ADR-0043 `Proposed` and record the withdrawal in a dated note alone.**
This is permitted today — the note is ADR-0070 §1's fourth bullet and needs no ADR
— and it was the blocking reviewer's own first direction. Rejected because the
`Status` field would then say *pending* about a proposal that is *closed*, and the
field is the one part of an ADR a consumer reads. It is the state #898 was filed
about, improved only by a note a machine does not read. It also scales badly: the
next withdrawn proposal, and the one after, would each be discoverable only by
reading the whole header.

**Supersede ADR-0043 with a stub ADR that decides nothing.** Rejected on two
counts. ADR-0070 §1 is explicit that recording a supersession "presupposes the
superseding ADR *exists*" and describes flipping "a **live** decision"; ADR-0043 is
not live. And the content of such a stub would be "the previous ADR is not
adopted" — a decision-shaped record of the absence of a decision, which would then
itself be a ratified ADR that a later reader must resolve against. Withdrawal says
the same thing in one field and one note, and consumes no number for a non-decision.

**Delete the file.** Rejected by §5's reasoning: it breaks ADR-0089 §2's live
citation, contradicts ADR-0001's append-only history, and fails ADR-0088 §6's
Tier 1 — which ADR-0090 exempts only for a number that was never issued. It would
also destroy the record the withdrawal exists to make: the ground on which a
proposal was rejected is worth more than the proposal.

**`Rejected` rather than `Withdrawn`.** A near-tie, settled by what the act
records. `Rejected` reads as a verdict on the proposal's merit; the ruling on
ADR-0043 was that a real defect did not prove urgent enough, which is a decision
not to adopt rather than a finding that the document was wrong. `Withdrawn` also
matches the language of the ruling and of #898. Nothing turns on it beyond
readability, and §2's terminality is the same either way.

**Widen ADR-0070 §1's enumeration by amendment rather than supersession.**
Rejected: adding a fifth bullet to a ratified enumeration changes what a reader
holding §1 may do, which is ADR-0070 §1's own definition of a change to what was
decided. ADR-0082 §1 declined this exact move for this exact section, and ADR-0090
declined it for ADR-0088 §6.

## Consequences

**Easier.** A proposal that was reviewed and ruled against has an exit, so the
corpus can hold "we considered this and decided not to" as a first-class state
rather than as an indefinitely pending `Proposed`. The `Status` field keeps its
meaning: `Proposed` again means *awaiting a decision* rather than *awaiting a
decision or already refused*, which is what makes a sweep for unratified ADRs —
the sweep that produced #622 and #898 — return a set someone can act on. The
withdrawn document stays readable, so the reasoning survives for whoever raises
the question again.

**Harder.** The vocabulary has five forms rather than four, and a
liveness-classifying consumer must handle one more — bounded by §4, which gives
that consumer its whole rule in one sentence and guarantees the token carries
nothing to parse. Authors gain one more decision at the end of a `Proposed` ADR's
life: ratify, or withdraw and say why. §3 makes the second cost a paragraph, which
is the intended price of not leaving the record silent.

**Follow-on.** PR #913 lands after this ADR merges, flipping ADR-0043 to
`Withdrawn` under §1 with the dated note §3 requires, citing this ADR as the
authority. #914 closes with §6's template edit. No implementation and no test
change with this decision; `scripts/project_status.py` displays the new value with
no change, and `scripts/check_citations.py` reads the field only for supersession
tokens, of which `Withdrawn` carries none.

**Revisit if** an `Accepted` ADR ever needs withdrawing rather than superseding.
§1 refuses that case deliberately and on an argument specific to a document that
was never in force; if a real instance appears, it is a different decision with a
different safety argument, not a widening of this one. Also revisit if a
liveness-classifying consumer is built and finds §4's one-sentence rule
underspecified in practice — that consumer is ADR-0070 §4's own reserved reader,
and it is the first thing to actually exercise this form.
