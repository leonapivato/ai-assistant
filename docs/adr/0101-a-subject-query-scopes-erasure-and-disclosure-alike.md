# 101. A subject query scopes erasure and disclosure alike, and it matches a label rather than a person

- Status: Accepted
- Date: 2026-08-04
- **Note (2026-08-04): ratified.** `Proposed` → `Accepted`, in the separate lane
  #633 requires, after **both** required reviews came back green on the content
  this ADR merged with: adversarial **APPROVE with no findings** and architecture
  **APPROVE with no findings**, both at tree `fa87e807c7aa`, round 3, churn ratio
  1.0, each posted to PR #694 by `just ship`. That is the outcome ADR-0070 §1
  requires the ratifying edit to record, and it is taken from that comment rather
  than from a report: the comment's `<!-- ship:657b02802585 -->` anchor is #694's
  merged head, and `git rev-parse` resolves that head's tree to the tree named
  above — the same tree as `707c467`, the commit the PR merged as, so the content
  the reviews read is the content that landed. Beyond the `Status` line the only
  edit is the tense of the header bullet below that names the review set. **No
  decision text is touched and no normative clause acquires, loses or alters an
  obligation**, which is ADR-0070 §1's own test applied to the ratifying edit
  first.

  **No status premise had to be corrected, and the reason is the header bullet
  below that says so in advance.** The bullet discharging ADR-0100 §12 was
  written to survive its neighbours' ratification — "ADR-0099 and ADR-0100 both
  stood `Proposed` when this ADR was written … every reference below to either is
  to its text as merged on 2026-08-04, not to its status on any later day" — so
  the one present-tense status premise this document could have carried was never
  written. That is the device ADR-0097 §11 lacked and had to be corrected in
  place for at its own ratification. ADR-0099 and ADR-0100 were both ratified at
  `9f1832a`, exactly as that bullet anticipated, and every reference below to
  either is to text that flip did not touch.

  **Three merges landed between this ADR's authoring and its ratification, so
  the staleness check was run rather than recited.** Ratified against `b86e8c2`,
  where `git diff --name-only 08da580 b86e8c2` — `08da580` being the base this
  ADR was written and reviewed against — names this file, ADR-0099, ADR-0100,
  ADR-0102, the three files of the `SourceGrantStore` implementation (#695) and
  the three files of the sub-minute zone-offset fix (#701), and nothing else.
  **Every claim this ADR makes about the tree was re-read against the code at
  that commit and holds**: `AssistantEngine` still carries fifteen methods and
  neither an `export` nor a `clear`; `interfaces/cli.py` still registers the
  twelve commands the Context names and no export command; and
  `ConversationLifecycle.export` still composes a `DataExport` that is a frozen
  dataclass in `orchestration` and that nothing outside `orchestration` calls.
  **ADR-0102 is the merge that could have moved one of those and does not.** It
  decides four further `AssistantEngine` methods and implements none — it is a
  contract ADR under the same golden rule 5 sequence as this one — so the count
  the Context reads off the tree is unchanged; and its §14 and Context lean on
  §7's finding that ADR-0004 §6's export right reaches no user rather than
  discharging it. Neither #695 nor #701 reaches any claim here.

  **No deferral of this ADR has fired.** §7's two firing conditions are both
  about the export right's surface and neither has a lane; the `MemoryStore`
  triad §7 reserves to that lane is unbuilt, which is what §7's last clause
  requires rather than a gap. #691, filed by §3, is open.

  **One present-tense clause was checked and deliberately left.** The bullet
  below says "a separate lane ratifies them" of ADR-0099 and ADR-0100. It states
  the mechanism #633 mandates rather than either ADR's status, it is what
  happened at `9f1832a`, and no reader is misled by it — both documents carry
  `Status: Accepted`. **ADR-0070 §1's no-rewrite rule now protects this text**,
  so any later correction is an appended dated note.
- **Decides the `MemoryStore` contract for subject-scoped erasure and disclosure,
  and the matching rule ADR-0100 §6's second clause reserved.** `export` gains a
  scope argument, a new `delete_about` destroys what that same scope selects, and
  §2 fixes what a subject query matches — Unicode canonical caseless equality of
  two labels, and nothing else. No code ships with it.
- **Flagged as a breaking change under golden rule 5.** The implementing lane
  changes `core/protocols.py`: `MemoryStore.export` gains a keyword-only argument
  and `MemoryStore` gains one method. Its ADR is therefore ratified and merged as
  its own PR before anything implements against it (ADR-0015 §5). No `core/types.py`
  change: §2's query is `EncodableText`, which already exists, and this ADR adds no
  type.
- **Required review set: adversarial *and* architecture.** `ship.sh` gates the
  architecture lens on `core/protocols.py` or `core/types.py` changing, and the PR
  carrying this ADR touches neither — it is prose only. The set is taken anyway
  because the *decision* is `core` surface, which is what ADR-0093 through ADR-0100
  each declared it for. It was reviewed while `Proposed` and ratified only after,
  in a separate lane (`CONTRIBUTING.md` → "Contract ADRs land before their
  implementation"; #633 records why the flip could not ride in the PR that
  carried it).
- **Discharges the first deferral of ADR-0100 §12**, which reads in part
  "**Subject-scoped delete and export.** ADR-0007 §1's `delete(record_id)`,
  `clear()` and `export()` gaining a dimension … **It is the ADR §6's second clause
  reserves the matching rule to**". ADR-0099 and ADR-0100 both stood `Proposed`
  when this ADR was written, and a separate lane ratifies them; **every reference
  below to either is to its text as merged on 2026-08-04**, not to its status on
  any later day.
- **Amends no earlier ADR and supersedes none.** §11 applies ADR-0070 §1's test and
  ADR-0082 §1's record rule to the five places where the opposite reading is
  available: ADR-0100 §6's reservation, ADR-0007 §1's signature block, ADR-0007 §3,
  ADR-0073 §5's "the contract does not change", and the two deferrals this ADR
  discharges.
- **It records a finding about the tree that the deferral's framing does not
  anticipate, and §7 turns on it.** ADR-0004 §6's *export* right has **no user
  surface at all**: `AssistantEngine`'s fifteen methods (ADR-0085 §3) carry
  `forget` and no export or clear, `interfaces/cli.py` exposes no export command,
  and `ConversationLifecycle.export` composes a `DataExport` that nothing outside
  `orchestration` calls. So a subject-scoped export is not a dimension missing from
  a surface; the surface is missing. Filed, and §7 is written against the tree
  rather than against the assumption.

## Context

### ADR-0100 left exactly one question open, and named this ADR as the only thing that may answer it

ADR-0100 §6 stores a subject label verbatim and rules that it resolves to nothing:

> **Normative.** `about_person` holds a label as the user or the source stated
> it. It is not an identifier, not a key, and not a reference: under this ADR
> nothing resolves it, and no store, producer, surface or lane may treat two
> equal labels as the same person or two unequal labels as different people.

and then reserves the sequel, naming its instrument:

> **Normative.** Whether labels may be compared, matched, aliased or resolved to
> a person — and by what rule — is reserved to a later ADR, which is the only
> thing that may lift the clause above. No lane may reach that answer by
> implementing one.

That reservation is why this decision cannot be reached by an implementing lane
and cannot be reached by a review finding. It is also why "forget everything about
Marta" is not merely unimplemented but *unstatable*: with nothing permitted to
compare two labels, a store handed the string `"Marta"` has no rule by which any
record answers to it.

ADR-0100's Consequences state the cost in the terms this ADR is meant to settle:
"Two records saying `"Marta"` and `"marta"` are two subjects to every piece of code
in the system until a lane rules otherwise (§6). That is the cost of keeping person
identity out, and it is paid in a place — matching — where it can be paid off later
without rewriting stored data." This is that payment.

### ADR-0007's four operations, and which of them a subject dimension can sit on

ADR-0007 §1 gave `MemoryStore` its data-rights surface: `delete(record_id)`,
`clear()`, `export()` and `purge_expired()`. Only two of the four are candidates,
and the reason is structural rather than stylistic:

- **`delete(record_id)`** takes a required positional id. A subject scope is not a
  narrowing of it; it is a different question with a different answer cardinality.
- **`clear()`** means *everything*. An optional scope on it is a method whose name
  says "everything" and whose argument decides otherwise — and whose failure mode,
  a `None` reaching it where a label was meant, is the whole store.
- **`export()`** takes nothing and returns everything retained. A scope narrows it,
  and an absent scope means what it means today.
- **`purge_expired()`** is retention reclaim, not a data right, and is untouched.

So the shape is forced before any argument about taste: the erasure is a **new
method**, and the disclosure is a **scope on `export`**.

### The reach of an erasure and the reach of its confirmation must be one predicate, and only one read has that reach

ADR-0073 §5 ratifies show-then-confirm for the single-belief kill — "The surface
renders the belief it is about to destroy … and takes the user's confirmation
before deleting. A person cannot consent to destroying something they were not
shown" — and then records the limit that matters here:

> **This surface deletes what it can show.** `get` is live-only, so a retired
> record's id is not resolvable here and the surface declines it rather than
> deleting something it cannot display.

A subject-scoped erasure cannot take that way out. A right to be forgotten that
spared retired records would leave the user's own export contradicting their own
deletion, because `export` returns records "**whether their validity window is open
or closed** — a superseded belief is data the store holds, so a data-rights export
must include it" (`MemoryStore.export`, ADR-0045 §6 amending ADR-0007 §3).

It follows that **`export` is the only read in the contract with the erasure's
reach**. `get` and `get_many` are live-only. `search` is live-only and ranked.
`list_beliefs` is inspection, and its own contract says why it is not a candidate:
"Inspection reads **live beliefs only**: a retired record is not a belief the
assistant holds but a record of one it used to, and it stays reachable through
``export`` alone" (`MemoryStore.list_beliefs`, ratifying ADR-0073 §3). A
confirmation built on the belief listing would under-show exactly the records the
erasure destroys, which is the failure ADR-0073 §5 declined to commit in the
smaller case.

### The tree half: delete has a surface, export has none

The corpus reads as though ADR-0004 §6's three rights were discharged and only
their subject dimension were missing. The tree says otherwise, and this ADR was
written against the tree:

- `AssistantEngine` carries fifteen methods (ADR-0085 §3). `forget(record_id)` is
  there. **No `export`, no `clear`.**
- `interfaces/cli.py` registers `ask`, `conversations`, `forget-conversation`,
  `resume`, `learn`, `beliefs`, `questions`, `answer`, `forget-question`,
  `observe`, `forget` and `version`. **No export command.**
- `ConversationLifecycle.export` assembles a `DataExport` — "Everything a user's
  'export my data' hands back (ADR-0004 §6, ADR-0074 §9)" — and `DataExport` is a
  frozen dataclass in `orchestration.conversations`, not a `core` type. Nothing
  outside `orchestration` calls it.

So the *deletion* right reaches the user and the *export* right does not. That is
not this ADR's to fix, and §7 is the consequence: a subject-scoped export cannot be
added to a surface that does not exist, and inventing one here would decide the
whole export surface — the frame ceiling of ADR-0085 §8c, paging, whether an export
is a frame at all — as a side effect of a decision about subjects.

### Why decide it now, when nothing calls it yet

Three reasons, and the honest statement of the fourth thing that is *not* a reason.

1. **The reservation is live and it is an invitation.** ADR-0100 §6 forbids every
   lane from comparing two labels and names a later ADR as the only instrument.
   Left standing, the first lane that wants the comparison either stops or takes
   the decision in code, which §6's last sentence forbids and which is the exact
   failure that clause exists to prevent.
2. **Deciding matching costs a page now and a supersession later.** A rule chosen
   by an implementation is a rule nobody argued, and unwinding one after data has
   accumulated under it is the shape ADR-0100 §8 spent a section on.
3. **The field ships with ADR-0100's implementing lane, and subjects begin
   accumulating that day.** The erasure's *reach* should be settled before there is
   data whose reach is in question, which is ADR-0099's own argument for ruling a
   frame early, read one level down.

**What is not a reason: that a consumer exists.** It does not. ADR-0099 §5 fires
the subject axis on "subject-scoped delete or export", and this ADR is the decision
that consumer needs — but the *surface* is deferred (§7), so nothing calls these
two methods on the day this ADR is ratified. §7's last clause is what keeps that
from becoming the surface-with-no-consumer state ADR-0045 §1, ADR-0028 §7 and
ADR-0092 §10 each refused: the contract is ratified here, and the triad lands with
the surface that calls it, not before.

## Decision

We will scope both halves of ADR-0004 §6's memory rights by a **subject query** —
a label compared to a stored label by Unicode canonical caseless equality and by
nothing else — put the disclosure half on `export` and the erasure half on a new
method, and defer both user surfaces jointly to the lane that gives the export
right a surface at all.

### 1. Two operations on `MemoryStore`, and the shapes differ because the risks do

> **Normative.** `MemoryStore.export` becomes
> `async def export(self, *, about_person: EncodableText | None = None) -> list[MemoryRecord]`.
> Its one new argument is keyword-only, and `None` preserves the method's present
> meaning exactly — every retained record. A non-blank label returns exactly the
> retained records §2's query matches, unchanged in every other respect: expired
> records excluded, window-closed records included (ADR-0007 §3 as amended by
> ADR-0045 §6).

> **Normative.** `MemoryStore` gains
> `async def delete_about(self, about_person: EncodableText) -> int`, which
> destroys every record §2's query matches and returns the number removed. Its
> argument is **required** and positional; no value of it means "everything".

> **Normative.** `delete(record_id)`, `clear()` and `purge_expired()` are unchanged
> in name, signature and meaning, and no lane may add a subject dimension to any of
> them.

> **Normative.** A blank or whitespace-only `about_person` argument is refused with
> `ValueError` on both operations. It is never read as `None`, and it never matches
> a record.

**Docstrings are owed and are not reproduced here**, which is ADR-0085 §3's move
and its reason: `CONTRIBUTING.md`'s Google-style requirement applies to the real
`core/protocols.py`, and reproducing the prose would bury the shapes this section
exists to fix. What each docstring must state is settled by the clauses of this
section and of §§2, 4, 5, 6 and 9, and by nothing outside them (ADR-0089 §3).

**The asymmetry is the decision, not an oversight, and it is stated so it decides
the next case too.**

> **Normative.** A destructive store operation is never given an optional scope
> whose absent or default value widens what it destroys. A read may be.

`list_beliefs` already carries the read form — `bands=None` means every band, and an
empty sequence selects nothing — so the corpus has the permissive shape and has
never had the destructive one. The reason is the failure mode. A scope that
defaults to "everything" turns a dropped argument, a `None` propagated from an
absent CLI option, or a mistyped keyword into total erasure, with the method's own
name reading as though that were intended. On a read the same slip over-discloses
to a caller that already holds the store handle, which §6's surface obligation
covers and which destroys nothing. Requiring the erasure's argument makes the
catastrophic slip *unconstructable* rather than merely discouraged — the discipline
ADR-0092 §2 used to choose a value object, applied to an argument list.

**The name is `delete_about`, and the two rejected names are rejected for reasons.**
`delete_subject` reads as deleting a subject, and there is no subject to delete —
§3 forbids exactly the registry that name would imply, so a method invoking it
teaches the wrong model at the call site. `clear_*` is unavailable for the reason
above. `forget` is the *engine's* verb (ADR-0085 §3's `forget`); the store's verbs
are `delete` and `clear`, and a seam that borrows the layer above's vocabulary
makes two surfaces look like one. `about` is the field's own word (ADR-0100 §7's
`about_person`) and carries §6's *whom*-not-*what* constraint with it.

### 2. What a subject query matches

> **Normative.** A subject query `q` matches a record `r` exactly when `r` states a
> subject and the two labels are **canonically caseless-equal** in the Unicode
> Standard's sense (definition D145): `NFD(toCasefold(NFD(q)))` equals
> `NFD(toCasefold(NFD(r.about_person)))`. A record with `about_person` unset is
> matched by no query.

> **Normative.** Nothing else is compared. Neither operation trims, strips
> diacritics, removes punctuation, tokenises, splits, truncates or otherwise
> transforms either label beyond the fold above.

**Why caseless rather than exact, decided on which way the error runs.** The two
rules fail in opposite directions and the failures are not symmetric. Under exact
equality a user who has written both `"Marta"` and `"marta"` runs the erasure, is
told records were destroyed, and keeps the rest — a **silent under-delivery of an
erasure right**, which is the failure ADR-0100 §8 argues is worse than a stated
limit. Under caseless equality the over-reach case requires two *different people*
whose labels differ only in case, which no user distinguishes them by and which the
system could not tell apart under any rule that is not a registry. A rule whose
error mode is "the user got what they asked for" is preferable to one whose error
mode is "the user believes something is gone and it is not".

**Why D145 rather than a rule of this ADR's own devising, and this is the load-bearing
choice.** The fold is not a judgement about names; it is the Unicode Standard's own
definition of "these two strings differ only by case". Anchoring on an external
standard is what makes §3's prohibition enforceable: every further step a lane might
reach for — trimming, folding diacritics, stripping honorifics, matching nicknames —
is *someone's judgement about people*, and none of them is available without
superseding a clause. A rule invented here would have no such edge. Two further
properties come free and are worth naming because a reviewer should be able to check
them: matching is an equivalence relation, because it is equality of a derived key
`fold(x)`, so it is reflexive, symmetric and transitive by construction; and it is
computable identically by any implementation with NFD and full case folding, which
is what lets a shared conformance suite pin it across two stores rather than one.

**Where it is computed is the implementing lane's, and one shape is worth naming so
the rule is not mistaken for unbuildable.** SQLite's `LOWER()` and `COLLATE NOCASE`
are ASCII-only, so a conforming store computes the fold outside the collation — a
derived, indexed comparison column beside the verbatim one is the obvious form.
That is not a normalisation of stored data: ADR-0100 §6's third clause binds what is
*stored as the label* and *returned*, and a derived key is neither. A later ADR that
changes §2's rule makes such a column a recomputation, which is a migration and not
a loss, because the verbatim label is what was kept.

**What it deliberately does not reach.** `"Marta"` does not match `"Marta Kowalski"`,
`"Marti"`, `" Marta"` or `"M. Kowalski"`. §6 is where that is said out loud rather
than left for a user to discover.

### 3. Matching is a pure function of two strings, and that is what keeps the registry out

> **Normative.** Subject matching is a total, deterministic function of the two
> label strings and of nothing else. No component may consult a person record, a
> registry, an alias or nickname table, a stored mapping, a similarity measure, an
> embedding, or a model when deciding whether a subject query matches a record.

> **Normative.** A match asserts nothing about persons. That a query matched a
> record is never evidence that two labels name one person, and no component,
> surface or later ADR may derive from a match a person identity, a merge of two
> labels, or a canonical spelling of either.

> **Normative.** This ADR lifts ADR-0100 §6's reservation only as far as
> *comparison* and *matching*, and only for §1's two operations. **Aliasing and
> resolution to a person stay reserved** exactly as ADR-0100 §6's second clause left
> them, and ADR-0100 §6's first and third clauses stand unchanged: outside §1's
> operations nothing resolves a label, and a label is stored and returned verbatim.

**This is the clause the ADR is most at risk of losing, so it is stated as a
prohibition on the mechanism rather than on the outcome.** A rule phrased as "do not
build a person registry" is a rule about intent, and intent is not checkable. A rule
that the matching function may read nothing but its two arguments is checkable by
looking at the function, and every registry-shaped design fails it at the first
lookup. It also survives whatever the voice-spoke leg decides about people: a
person registry, should one
arrive, is a supersession of this clause, argued and visible, rather than something
that accreted through a sequence of individually-reasonable widenings. ADR-0094 §10
defers *device* identity — "a spoke identity" — and ADR-0099 §5 is the sentence that
keeps the two apart: "knowing which microphone spoke is not knowing who talked into
it, and the two must not be conflated by a lane that finds one of them already
deferred."

**A finding recorded rather than fixed, in ADR-0099 §6's shape.** ADR-0099 §5 and
ADR-0100 §6 and §12 each file person identity, enrolment and speaker identification
against **#665**. That issue as written is "Voice spoke: aloud read-back is a
disclosure surface and needs its own decision" — an *output*-side disclosure
question, which says of the request path that "Speaker ID gates who the hub thinks
*asked*" and treats that gating as settled elsewhere. So the person-identity question
those ADRs defer has no tracker record of its own; what it has is the voice-spoke leg
(ADR-0094's spoke profiles), which is where all three ADRs also place it in prose.
This ADR does not correct their texts — they are another lane's, and the correction
changes no decision any of them made — and cites the leg rather than the number.
Filed as **#691**.

### 4. The erasure destroys, reaches retired records, and is not a supersession

> **Normative.** `delete_about` destroys the records it matches: each is removed
> from the store and from every subsequent `export`, exactly as `delete` removes one
> (ADR-0007 §1). It writes no replacement, retires nothing, and closes no validity
> window.

> **Normative.** It reaches a matched record whether that record's validity window
> is open or closed. Retirement does not shelter a record from erasure.

> **Normative.** `delete_about` is a data-rights operation and never a supersession
> event. It consults no `MemoryPolicy`, resolves no conflict, and this ADR may never
> be cited for a subject-conditional supersession rule (ADR-0099 §4).

The second clause follows from the first read against `export`. A retired belief is
data the store holds — that is precisely why ADR-0045 §6 widened ADR-0007 §3 to
carry it into an export — so an erasure that spared it would hand the user, in their
own export, the records they had been told were destroyed.

The third is hazard control rather than new law. ADR-0099 §1 ratifies the store as
the owner's world model, under which "the owner's assertion beating an external
report is correct **by construction**" (ADR-0099 §4), and §4 forbids any ADR citing
it for a subject-conditional supersession rule. Scoping *erasure* by subject is a
data right; scoping *precedence* by subject is a change to the supersession law. The
clause exists because the two are one word apart in English and nothing mechanical
separates them.

### 5. The erasure is all-or-nothing, and the show/act window is ADR-0073 §5's

> **Normative.** `delete_about` is atomic: every matched record is removed, or none
> is. No read ever observes a partial erasure.

> **Normative.** `delete_about` raises `MemoryStoreError` on any backend failure,
> and nothing is removed. §1's `ValueError` for a blank argument is raised before
> any record is read. A query that matches nothing is not a failure: it removes
> nothing and returns `0`, as `delete` returns `False`.

`write_atomic` already establishes the primitive and its reason — "a batch that
commits in full or not at all" (ADR-0046) — and the reason binds harder here. A
failed erasure the user can retry is a nuisance; a *partial* erasure the user
believes completed is the silent under-delivery §6 exists to prevent, arriving
through a mechanism the user cannot see. Both shipped store shapes meet it with one
statement, so the clause costs nothing.

The module's cancellation clause (ADR-0060) is unchanged and still governs: a
cancelled call's effect is indeterminate to the caller, who "may not assume the
write did not land". What atomicity adds is that the indeterminacy is binary — the
erasure landed or it did not — rather than a set of records the caller cannot
enumerate.

**No compare-and-delete, for ADR-0073 §5's three reasons unchanged.** A record
written between a subject-scoped read and the erasure that follows it is destroyed
without having been shown. This ADR does not close that window: the mechanism would
be a revision on the record and a compare-and-swap seam, which ADR-0046 §5 deferred
"for want of a consumer that runs two writers on one store" (quoted at ADR-0073 §5),
and a deletion surface is still "one reader with a confirmation prompt". The
obligation ADR-0073 §5 places on the adapter — take the render as late as it can be
— carries over unchanged, and the consent is consent to forget what the query names,
not a guarantee that the bytes destroyed are the bytes rendered.

### 6. The honest limit, and what the surface must say about what it did not reach

> **Normative.** A subject query reaches only records that state a matching label.
> A record whose subject was never stated is never reached, whatever its content
> says, and this ADR authorises no component to infer a subject for it (ADR-0100
> §4, §8).

> **Normative.** A surface offering either operation states, every time it is used
> and without being asked, that it covers only records whose subject was stated
> under a matching label, and that records with no stated subject — including every
> record written before `about_person` existed — are not covered. The statement is
> made whether or not any such record exists, because no read can tell.

> **Normative.** No surface may present either operation as everything the system
> holds about a person, or as the erasure of a person from the store.

**Why the disclosure is unconditional rather than computed.** The tempting form is a
count — "7 destroyed, 3 records with no stated subject not examined" — and it is
unavailable in both directions. The store cannot say which unstated records are
*about* the label without inferring a subject, which ADR-0100 §4 forbids in the
strongest terms it has; and reporting the raw count of unstated records would report
most of the store, which is alarming and tells the user nothing. So the surface
states its *reach*, which it knows exactly, rather than its *miss*, which it cannot
know at all.

**Why the third clause is separate from the second.** ADR-0073 §5 requires that a
surface "must not represent a deletion as more final than it is, nor as less final",
and a scoped erasure is where the over-claim is most natural: "Marta has been
forgotten" is a shorter and more satisfying sentence than the true one. Under
ADR-0089 §3 the marked clauses are the whole of what this ADR obligates, so the
prohibition is marked rather than left to the argument beside it.

**This is ADR-0100 §8's limit inherited, not a new one.** That section rules that
"`assistant learn` has accepted arbitrary third-party content since it shipped, so a
deployed store may already hold beliefs about other people that will be read as the
owner's forever", and that the imprecision "is correctable only by the user". A
subject-scoped erasure does not narrow that and does not widen it. What it adds is
that the user now meets the limit at the moment it matters — when they are asking
for something to be destroyed — rather than never.

### 7. Where the surface lives: deferred, jointly, with two conditions that fire

> **Normative.** This ADR puts neither operation on `AssistantEngine` and adds no
> CLI command. The engine and CLI surface for both is deferred.

> **Normative.** The two surfaces land together or neither lands. No lane may ship a
> user-facing subject-scoped erasure without the subject-scoped read that shows what
> it will destroy, and no lane may cite this ADR for one.

> **Normative.** The `MemoryStore` triad for §1's operations — the Protocol change,
> the extended conformance suite pinning §2's rule, and the canonical fake — lands
> with the first surface that offers them, and not before. Ratifying this ADR
> authorises no implementation lane on its own.

**Fires with the earlier of two conditions**, both of which are about the export
right rather than about subjects:

1. **The lane that gives ADR-0004 §6's export right a user surface at all.** The
   Context records that it has none. That lane owes the subject dimension in the
   same change, because ADR-0004 §6's rights are symmetric and §8 rules the halves
   inseparable.
2. **The first client that must answer "show me everything you hold about Marta"**
   over the hub socket, which is the same lane approached from the other side.

**Why the deferral is principled and not convenience.** Three things would have to
be decided to put a subject-scoped export on `AssistantEngine` today, and none of
them is a question about subjects:

- **The frame.** ADR-0085 §8c bounds the whole serialised payload at
  `hub_max_frame_bytes - 512`, and an export is unbounded in every factor — record
  count, content length, and the citations §8e records as still unbounded. ADR-0085
  §8e's answer for an oversized `Belief` is a declared failure naming the field,
  "a sentence a user can read and act on". That answer is right for a *read of one
  belief* and wrong for a *data right*: an export that refuses because the store is
  large is a right that stops working precisely for the users who have most to
  export. So the export surface needs paging, a non-frame channel, or a bound —
  a design, and one the unscoped export needs identically.
- **What an export *is* on that surface.** `DataExport` composes `MemoryStore` and
  `ConversationStore` (ADR-0074 §9), is a dataclass in `orchestration`, and is not a
  promoted `core` type. Whether it promotes, whether the subject scope reaches the
  conversation half, and what a turn whose episode was subject-erased renders as,
  are all that lane's.
- **The confirmation read.** The Context establishes that only `export` has the
  erasure's reach. A subject-scoped erasure on the CLI, built on `beliefs()`, would
  show the user live beliefs and destroy retired ones too — the failure ADR-0073 §5
  declined to commit when it ruled that "this surface deletes what it can show".

The third is what makes the *joint* deferral necessary rather than tidy. Shipping
the erasure alone would put an irreversible operation behind a confirmation that
cannot show what it destroys, which is worse than shipping neither.

### 8. Symmetry: the two halves are one decision

> **Normative.** No ADR or lane may take §1's erasure without §1's scoped
> disclosure, or ship one on a user surface without the other.

ADR-0004 §6 gives "view, export, and delete" together in one sentence. ADR-0099 §5
sequenced their subject-scoped forms together — "**Both, not just delete**: ADR-0004
§6's rights are symmetric and an export that cannot be scoped is the same gap facing
the other way" — and ADR-0100 §12 restated it. This clause is not a restatement for
its own sake: §7's deferral is the moment the halves could come apart, since the
erasure's surface exists today and the disclosure's does not, and a lane under
schedule pressure would find the split easy to take and hard to notice.

There is a second reason that is this ADR's own. The two operations share one
predicate (§2). A disclosure that answered a different question from the erasure —
a different fold, a different set of records, a different treatment of retirement —
would make the confirmation a lie by construction rather than by timing. One
predicate, defined once, used by both, is what §5's window is *narrow* rather than
unbounded.

### 9. The axes neither operation may reach for

> **Normative.** Neither operation may be scoped or filtered by `Provenance.source`,
> by belief band, or by any other origin-axis value, and neither may alter its result
> on one. A stated subject is not evidence of externality and an `EXTERNAL` source is
> not evidence of a third-party subject (ADR-0100 §10).

> **Normative.** Neither operation refuses or spares a record for the band it sits
> in, the kind it is, or the confidence it carries.

The first is ADR-0100 §10 applied to the first consumer of the axis, which is where
it was always going to be tested: the intuition that a belief about someone else
came from somewhere else is strong, wrong, and would make an erasure quietly
incomplete for every third-party belief the owner asserted themselves.

The second is ADR-0073 §5's rule at scale — "ADR-0004 §6 gives the user an
unconditional right to delete their data; a store that refused to delete a belief
because of the band it sat in would make a data-right conditional on a
classification the system assigned." A bulk erasure is where a band-conditional
carve-out would look most defensible, and it is where it would do the most damage.

### 10. Deferred, by name, each with the condition that fires it

- **Enumerating the subjects a store holds** — "which people do you have beliefs
  about". **Refused rather than deferred on cost**: it is derivable today from
  `export()`, which returns every retained record with its `about_person`, so a new
  method would be surface with a derivation already in hand — the refusal ADR-0045
  §1, ADR-0028 §7 and ADR-0092 §10 each made. It is *deferred* only in the shape §7
  defers everything else: fires with the first surface that must offer subject
  discovery **without** handing over the whole export, which is the frame problem §7
  already holds and not a separate question.
- **Aliasing, and resolving a label to a person.** Still reserved by ADR-0100 §6's
  second clause, which §3 lifts only as far as comparison and matching. Fires with
  whatever ADR decides person identity, and it is a supersession of §3's
  first two clauses rather than an extension of them.
- **Widening §2's fold** — trimming, diacritic folding, honorific stripping,
  nickname matching, or any similarity measure. Refused in §2 and §3. Fires only as
  a supersession of §2, and the ADR that takes it owes an argument about the
  over-reach direction, which §2 argues is the one that cannot be undone.
- **Whether a stated subject scopes conflict detection.** ADR-0100 §12's own
  deferral, untouched here. Erasing by subject and *detecting a conflict* by subject
  are different questions; nothing in §1 reads a subject on the write path.
- **Rendering a subject.** ADR-0100 §11 rules normatively that it adds nothing to
  ADR-0073 §4's per-belief enumeration and that rendering is deferred. This ADR takes
  nothing of it either: §6's obligations are about what a surface says about an
  *operation's reach*, not about what it renders per belief.
- **Cross-store and cross-tier erasure.** §1's erasure is a `MemoryStore` operation
  and reaches Tier 1 rows of that store only, which is ADR-0007 §4's boundary
  unchanged. A subject-erased episode leaves a `ConversationTurn` indexing it, and
  the coordinator that owns every cross-store sequence is ADR-0074 §9's stage in
  `orchestration` — `DataExport` already drops a turn whose episode does not resolve.
  Nothing today states a subject on an episode (ADR-0100 §4; ADR-0075 §2's "Capture
  judges nothing"), so the case is reachable but unpopulated. Fires with §7's surface
  lane, which is where the coordinator sequence would be written.
- **A compare-and-delete keyed on a revision.** #248 and ADR-0046 §5, unchanged; §5
  above declines it for ADR-0073 §5's reasons.

### 11. This ADR classified under ADR-0070 §1 and ADR-0082 §1

**It amends nothing and supersedes nothing.** ADR-0082 §1 requires the judgement in
this ADR's text, clause by clause, against ADR-0070 §1's test: *would a reader
holding only the earlier ADR now act differently, or read one of its clauses more
widely than it now holds?* Applied to the five places where the opposite reading is
available.

**ADR-0100 §6's reservation — not owed, and this is the closest of the five.** The
first clause forbids treating "two equal labels as the same person or two unequal
labels as different people"; §3's second clause preserves it word for word, because
a match under §2 asserts nothing about persons and no component may derive one from
it. The second clause reserves four things — "compared, matched, aliased or resolved
to a person" — and names "a later ADR" as "the only thing that may lift the clause
above". This ADR is that instrument, it takes the first two and leaves the last two
reserved, and it does so by the mechanism §6 wrote for it. A reader holding only
ADR-0100 reads a prohibition whose own text says a later ADR may lift it, and
ADR-0100's Consequences say the same in the plainest available words: two spellings
are two subjects "**until a lane rules otherwise (§6)**". No sentence of ADR-0100
becomes false or over-wide. **Stacked addition**, and the same treatment ADR-0100 §11
gave its own discharge of ADR-0099 §5: "a condition firing as written is the
mechanism working."

**ADR-0007 §1's signature block — argued both ways, and ruled not owed.** §1 states:

```python
async def export(self) -> list[MemoryRecord]:
    """Return a portable snapshot of all live (non-expired) records."""
```

*The case for a record*, stated at its strongest: an implementer acting on ADR-0007
alone writes that signature and, after this ADR, has a non-conforming
implementation. That is "acting differently" in the test's most literal reading,
and this ADR was reviewed by a lens that read it exactly that way.

*The case against, which governs, and it is settled by asking the question
ADR-0082 §1 puts to a reviewer:* **which sentence of ADR-0007 becomes false or
over-wide?** Walk them. "`MemoryStore` gains:" — still true, it did. "`add`, `get`,
and `search` keep their existing names and async shape" — about other methods.
"This is an **additive** Protocol change: existing callers are unaffected; new
callers gain the data-rights surface" — still true, and true of *this* change in the
same words, since `export()` called with no argument returns exactly the records §1
and §3 say it returns and the default is chosen so that it does. The signature line
itself becomes **incomplete**, not false: `export` is still `async`, still returns
`list[MemoryRecord]`, and still answers a bare call the same way. ADR-0082 §1's test
is "false or over-wide", and an addition characteristically leaves earlier text true
and incomplete — which is what makes it a *stacked addition* rather than an
amendment.

**Two ratified precedents point the same way, and the contrary reading contradicts
both.** ADR-0086 §11 ruled "Not owed — … ADR-0068. ADR-0068 froze the graph and did
not close it, and §4's field is additive": an additive field on a type an earlier
ADR specified, which makes an implementation built to that earlier ADR incomplete in
exactly the way a keyword argument does. And ADR-0086 §6 added `get_many` to **this
very Protocol**, which likewise leaves a reader of ADR-0007 building a non-conforming
store, and recorded nothing against ADR-0007 — which does not even appear in its
"not owed" list.

**The strongest evidence is on ADR-0007's own `Status` line, and it is a worked
example of what an `export` amendment costs.** ADR-0045 §6 changed *which records
`export` returns* — live to retained — and that is recorded, on the `Status` line
and in a dated header note, on this same §3/§1 pair. So the corpus already
demonstrates the trigger for an `export` record, and it is a change to the answer.
This ADR does not move that answer by one record.

**And the contrary reading is a rule change made by review rather than by ADR.**
If a signature growing owes a record, so does every Protocol addition, on whichever
ADR first listed the method — which is unbounded book-keeping and is the ground
ADR-0082 §1 puts out of a reviewer's reach: "What a reviewer may not do is demand a
record, or its removal, on book-keeping grounds alone: that the earlier ADR's list
'should mention' the change, that a conformance list has grown, or that a sibling
ADR was recorded differently." Changing that line is a decision worth taking, and
the instrument is an ADR superseding ADR-0082 §1, not a finding on this one.

**Addition.** A reviewer who still reads the test the other way is invited to name
the sentence of ADR-0007 that becomes false or over-wide, which is the showing
ADR-0082 §1 requires and which this section has tried and failed to find.

**ADR-0007 §3 — not owed.** §3 decides that an export is portable, one-way, carries
no embeddings, and that the caller serialises. All four are untouched. §3's
"Expired-but-not-yet-purged rows are excluded" is preserved by §1's clause and was
already narrowed by ADR-0045 §6, which ADR-0007's `Status` line records. A reader
acting on §3 acts identically.

**ADR-0073 §5's "The contract does not change" — not owed.** The sentence is scoped
by the clause that immediately glosses it — "and in particular the store does not
grow a band-conditional refusal" — and by the surface §5 is about, the single-belief
kill. §1 does not change `delete`, and §9's second clause restates §5's refusal
rather than eroding it. §5's "This surface deletes what it can show" is likewise
preserved: §7's second clause is that principle applied to a scope rather than an
id, which is why the surfaces are deferred jointly. No sentence of ADR-0073 becomes
false.

**ADR-0099 §5's and ADR-0100 §12's deferrals — not owed.** Both name this decision
and defer it; ADR-0099 §5 adds "Fires with the subject axis, which it strictly
depends on", and ADR-0100 §12 names it "the next one". Discharging a deferral by the
route the deferral itself specified is the mechanism working, not an amendment
(ADR-0100 §11). Every sentence of both stays true.

**No ADR's decision text, header or `Status` line is edited by this lane**, and
neither `VISION.md` nor `CLAUDE.md` is touched. ADR-0099 §7 already ruled what
VISION owes and when — "An amendment becomes owed with §3's federation" — and this
ADR makes no product-shape promise VISION does not already make.

## Consequences

- **"Forget everything about Marta" becomes statable, and it was not before.** The
  blocker was not a missing method; it was ADR-0100 §6's reservation, under which no
  component was permitted to decide that any record answers to the string `"Marta"`.
  §2 is that decision, and it is the whole of what this ADR unlocks that could not be
  unlocked by an implementation.
- **The erasure right acquires a stated reach and keeps its honest limit.** §6 is
  what stops the gain becoming a loss: a scoped erasure that let a user believe a
  person had been removed from the store would be worse than the unscoped one it
  replaces, because the unscoped one never made the claim.
- **Person identity stays out, and the door it would come through is now named.**
  §3's mechanism prohibition — the matching function reads nothing but its two
  arguments — is checkable by inspection, where "do not build a registry" is not.
  Whatever the person-identity decision turns out to be, it arrives as a
  supersession of a clause rather than as an
  accretion of reasonable-looking widenings.
- **The export right's absence is on the record.** The Context's finding is the
  larger practical result of this lane: ADR-0004 §6 requires view, export and delete
  "from day one", and the export half reaches no user. §7's deferral is keyed to the
  lane that fixes it, so the subject dimension cannot be forgotten when it is.
- **Two store methods are ratified and nothing calls them, deliberately.** §7's last
  clause is what makes that a sequencing decision rather than the
  surface-with-no-consumer state this corpus refuses: the contract is decided while
  it is cheap to argue, and it lands with the caller that needs it.
- **The scoped read costs more than the unscoped one on a large store**, because a
  fold is computed rather than an id looked up. §2 names the derived-column shape
  that makes it an indexed equality; a store that scans instead is conforming and
  slower, which is an implementation property and not a contract one.
- **Revisit if** the voice-spoke leg lands person identity (#691), at which point
  §3's first two clauses
  are what must either be superseded or shown to survive; if a producer appears that
  receives a *structured* subject from a source (ADR-0100 §4's unexercised clause),
  since a source-supplied label may have a canonical form that a user-typed one does
  not; or if a user is observed to run an erasure and find records surviving under a
  spelling §2 does not fold, which is the evidence a widening would need.

## Alternatives considered

- **Exact codepoint equality, with no fold.** The most conservative rule and the
  easiest to defend as "we decided nothing about people". Rejected in §2 on the
  direction of the error: it under-delivers an erasure silently, which is the failure
  ADR-0100 §8 spends a section arguing is the worst outcome available, and it buys
  that with a purity the user never sees.
- **A configurable or pluggable matching rule.** Rejected without a section, and
  named here because it is the shape a lane reaches for when a decision is close: it
  converts a ratified rule into a deployment variable, so two installs answer the
  same erasure differently and no conformance suite can pin either. ADR-0100 §6
  reserved matching to *an ADR* precisely to keep it out of code; a setting is code
  with a longer reach.
- **A dimension on `clear()` rather than a new method** — `clear(about_person=...)`,
  where `None` keeps today's meaning. Rejected in §1. It is symmetric with `export`
  and it makes a dropped argument erase the store, under a method name that reads as
  though that were the intent. The symmetry is not worth the failure mode, and §1's
  general rule is what stops the next lane rediscovering it.
- **Two new methods, `export_about` and `delete_about`, leaving `export()` alone.**
  Genuinely close, and rejected on duplication: `export_about` would have to restate
  the retained/expired/window-closed semantics ADR-0007 §3 and ADR-0045 §6 settled,
  and two methods that must agree about which records exist is one more thing for two
  implementations to disagree about. The scope argument is the same predicate applied
  to the same read.
- **Decide delete here and defer export.** Rejected in §8, and the convenience
  argument for it is real — the erasure has an engine surface today and the
  disclosure has none. It fails on ADR-0073 §5's own principle: the confirmation for
  a scoped erasure must show what will be destroyed, and only `export` has that
  reach, so shipping the erasure alone means shipping an irreversible operation
  behind a confirmation that cannot show its subject. ADR-0004 §6's symmetry is the
  second reason, not the first.
- **Decide the engine and CLI surface here as well.** Rejected in §7. It would decide
  the frame question (ADR-0085 §8c), whether `DataExport` promotes to `core`, whether
  an export is a frame or a file, and how the conversation half is scoped — a design
  the *unscoped* export needs identically and which has nothing to do with subjects.
  A subject decision is the wrong vehicle for the export surface.
- **Add a subject enumeration**, so a user can see which labels are held and run the
  erasure on each. Attractive, because it is the only thing that makes §2's
  under-reach *actionable* rather than merely disclosed. Rejected in §10: it is
  derivable from `export()` today, so it is surface with the derivation in hand, and
  it is a person-shaped list one step from the registry §3 refuses. It returns with
  §7's surface lane, where the reason to want it — an export too large to hand over
  whole — is the same reason that lane exists.
- **Report what the erasure did not reach**, as a count of unstated-subject records
  beside the count destroyed. Rejected in §6. The store cannot say which unstated
  records are about the label without inferring a subject (ADR-0100 §4), and the raw
  count is most of the store — a number that alarms without informing. The reach is
  knowable and the miss is not, so the surface states the reach.
- **Let the erasure retire rather than destroy**, closing each matched record's
  validity window so the act is reversible. Rejected in §4. It is #112's shape and
  it is right for a *correction*; an erasure right is not a correction. ADR-0073 §5
  already rules that forgetting destroys — "nothing is kept, not even in an export" —
  and a deletion right discharged by retirement would leave every erased record in
  the user's next export.
- **Scope the erasure to live records only**, matching `list_beliefs`' reach and
  letting the CLI's existing listing serve as the confirmation. Rejected in §4 and
  §7. It is the version that ships soonest and it is not an erasure: the retired
  records survive, `export` returns them, and the user is told the person was
  forgotten.
