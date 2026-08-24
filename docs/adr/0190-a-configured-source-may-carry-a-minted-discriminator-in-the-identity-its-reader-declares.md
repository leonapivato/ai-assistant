# 190. A configured source may carry a minted discriminator in the identity its reader declares, and the type-name half stays the sensor's

- Status: Proposed
- Date: 2026-08-24
- **Decides a `core` contract and implements none of it — a breaking `Reader`
  change (golden rule 5).** It changes what `Reader.name` may return, and so what
  every consumer of a source identity may rely on: today an identity is a class
  constant and two objects of one reader class always agree; after this ADR two
  configured sources of one reader type declare different identities, and a
  consumer that assumed one identity per reader *class* is wrong. No signature
  changes and no `core/types.py` change is owed (§3), but the semantics of a
  ratified Protocol member do, which is the breaking half. **Because this ADR
  decides a Protocol's semantics, its required review set is adversarial *and*
  architecture**, even though the PR carrying it is prose only — ADR-0093's own
  header took that reading for the same member, and `CONTRIBUTING.md` → "Stop when
  the required reviews are green" makes it "the ADR deciding that surface" rather
  than the diff that decides. ADR-0015 §5 and golden rule 5 put it in **its own
  PR, prose only, ratified before anything implements against it**; the correction
  it obliges on `core/protocols.py` is §3's, and belongs to the lane that admits a
  discriminated identity.

## Context

ADR-0189 §6 specifies, completely, the identity a second configured source of one
reader type would carry — and its last clause but one refuses to authorise it:

> **Nothing in this ADR permits a discriminated identity to be built.** ADR-0093 §7
> rules that a sensor's identity "is **declared by the sensor** and is not a
> configurable value", and a minted discriminator reaching `Reader.name` from a
> deployment's configuration is a change to what §7 decided — a **partial
> supersession** under ADR-0070 §1, not an amendment […] This ADR does not make it,
> and no lane reads this section as having made it. §12 defers that act with the
> properties above as its specification.

ADR-0189 §12 then carries the deferral by name, calls it "a **small, fully-specified
ADR lane** — one clause of one ADR, one Status line", and names its own successor.
This is that ADR. It is the whole of the act ADR-0189 declined, and nothing else:
issue #1515 is its record, and the specification is ADR-0189 §6's, adopted rather
than re-derived.

### Two gates stood in front of a second configured source, and one is already down

ADR-0097 §9a gates grantability on a *rule* existing — "A second instance of one
source type may not become grantable before that rule exists." ADR-0189 §7 states
that rule and discharges the gate on its own terms, and that discharge is cited
here, not reopened.

The other gate is ADR-0093 §7's, and until this ADR nothing in the corpus recorded
it as one:

```text
**Normative.** A sensor's identity is **declared by the sensor** and is not a
configurable value. It is a stable Tier 2 name, never derived from the source's
location or contents; a path, filename, address or account identifier may not be
used as one. The calendar sensor's identity is `"calendar"`.
```

That is ADR-0093 §7's mark shown, not made: it is fenced so that quoting the clause
this ADR supersedes does not re-impose it here (`docs/adr/template.md`, ADR-0089 §2).

A second configured source of one reader type needs an identity that distinguishes
it from the first. Every `CalendarReader` returns the same class constant, so the
distinguishing part can only come from the deployment's configuration — and
ADR-0097 §1 forecloses reaching it by another seam: "A grant's subject is a
**reader's declared identity** — the value `Reader.name` returns … A grant keys on
nothing else." One seam, and a clause forbidding what has to go into it.

### This is ruled ahead of its trigger, and what ADR-0189 §6 declined is not what is done here

ADR-0093 §11's registry trigger has not fired: `main` carries two source *types*
with one configured source each. ADR-0189 §6 records the precedent for deciding
ahead of a trigger (ADR-0107, "Why this is worth deciding before the trigger
fires") and takes it for the specification.

ADR-0189 §6 gave two grounds for stopping short of the permission, and only one of
them was substantive: that authorising means "editing ADR-0093's Status line, which
is a decision about another ADR's document", and that it would be taken "with **no
second source in hand** to check the choice against". The first is a lane fence —
ADR-0189 was fenced to its own file, and #1515 was filed rather than fixed for
exactly that reason. The second is answered by what this ADR does and does not do:
**the choice a second source would check is §6's specification, and this ADR adopts
it unchanged and re-opens none of it.** What is added is the permission, and a
permission has nothing to check against a second source that the specification it
points at does not already carry.

What has changed since ADR-0189 §6 was written is that §6 is ratified. Adopting it
at the time would have meant superseding a ratified clause on the strength of
unratified text; adopting it now does not. That is the whole of the difference, and
it is why this ADR is short.

### An honest statement of what this ADR is not allowed to settle

It builds nothing. There is still no source registry, no list-valued source
configuration, and no client surface that shows two sources — ADR-0189 §8 defers
all three with their triggers unfired, and this ADR leaves every one of them
exactly where it found it. Removing the last gate in front of a capability is not
the same as supplying it, and a reader who takes this ADR as having configured a
second calendar has misread it.

## Decision

### 1. ADR-0093 §7's non-configurable-identity clause is partially superseded, in one respect

> **Normative.** ADR-0093 §7's ruling that a sensor's identity "is **declared by the
> sensor** and is not a configurable value" is **partially superseded**. A source
> identity may carry a part that comes from the deployment's configuration, in
> exactly the shape ADR-0189 §6 specifies and in no other: the **first** source of a
> reader type a deployment configures may hold that type's bare declared name, and
> every source of that type configured **after** it carries a **discriminator** the
> deployment mints — 128 bits, rendered as 32 lowercase hexadecimal characters,
> assigned once at configuration, never changed, never re-used.

> **Normative.** **The discriminator is not the identity.** An identity is one of
> exactly two things: a **bare** identity, which is a reader type's declared name and
> nothing else, or a **discriminated** identity, which is that declared name together
> with one discriminator, spelled as §4 rules. Where this ADR or ADR-0189 §6 states a
> width, an alphabet or a mint, it states it of the **discriminator**; the identity
> is what `Reader.name` returns and what §4 spells.

> **Normative.** The **type-name half stays the sensor's**, declared and not
> configurable. What a deployment supplies is the discriminator alone. No deployment
> may configure the declared name of a reader type, and no identity — bare or
> discriminated — may lack a declared part.

> **Normative.** Holding the bare name is a **permission and not an obligation**: a
> deployment may mint a discriminator for the first source of a type as well, and
> ADR-0189 §6's "may hold … and a deployment that has assigned that bare name has
> spent it" is adopted with its permissive word intact. What is forbidden is the
> converse — a source configured after one of its type has taken the bare name may
> not hold a bare identity — and that is the whole of what assign-once needs.

> **Normative.** ADR-0093 §7's last sentence — "The calendar sensor's identity is
> `"calendar"`" — is **narrowed to the first configured calendar** of a deployment
> that assigned it, which under ADR-0189 §6's assign-once rule is every deployment
> in existence. It is no longer true of a `CalendarReader` as such.

**Everything about the shape is ADR-0189 §6's and is cited rather than restated.**
The mint's arithmetic, the assign-once rule and its reason, why a fixed form closes
the hazard §7 named, why the unit is the configured source rather than the reader
object, and the two residuals §6 states — a collision with a retired identity at
2⁻¹²⁸ and a deliberate re-installation of one — are all ratified there. This ADR
adopts them whole and re-opens none of them; a reader wanting the argument reads §6.

### 2. What ADR-0093 §7 keeps, and it is everything else

> **Normative.** ADR-0093 §7's surviving identity properties bind every identity,
> discriminated or bare: it is a **stable Tier 2 name**; it is **never derived from
> the source's location or contents**; and **a path, filename, address or account
> identifier may not be used as one, or as any part of one**. A minted discriminator
> carries no information about the source it names, which is what makes it
> admissible under these three rather than an exception to them.

> **Normative.** Every other ruling of ADR-0093 §7 stands unchanged — the
> one-source-by-explicit-`Settings`-fields rule, the interval convention,
> disabled-by-default, the shape-versus-existence validation split, the
> non-blocking open, the byte cap on the read itself, the whole-read-off-the-loop
> rule, the terminable worker, the deadline, the one-outstanding-worker
> reservation, the no-configurable-display-label clause, and
> "configuration is not a grant". Nothing here reaches any of them.

> **Normative.** ADR-0093 §7a and §7b are untouched. §7a's note that "The sensor's
> identity is deliberately not in that table" stays true of the **one configured
> source** §7a's nine fields describe, which under ADR-0189 §6's assign-once rule
> holds the bare declared name and needs no field. Where a deployment's
> configuration carries a discriminator is the registry lane's (ADR-0189 §8), and
> nothing in this ADR adds a field to §7a's table or to `Settings`.

**The identity clause is the only thing this ADR is about, and §7 is a long
section.** Naming what survives is not book-keeping: ADR-0070 §4 requires the
Status-line scope to name "exactly what was replaced", and a reader arriving at
ADR-0093 §7 through a supersession pointer needs to know that the other rulings
under that heading are untouched. They are enumerated rather than counted, for
ADR-0189 §9's reason — a numeral in a list of this kind went stale inside one
review round there.

### 3. What `Reader.name` may return, and what the implementing lane owes

ADR-0189 §10 assigns three things to this lane by name: "what `Reader.name` returns
today, what `ReaderContract` requires of it, [and] what the shared conformance suite
(ADR-0095 §3) asserts about it. The lane that takes §12's partial supersession
decides all three." They are decided here.

> **Normative.** `Reader.name` returns **the identity assigned to the configured
> source that reader serves**, in §4's form — bare or discriminated under §1, and
> never a discriminator on its own. It is still a property of the reader, still
> stable across calls, and still the only seam a source identity reaches (ADR-0097
> §1). No member is added to `Reader`, and ADR-0102's rule that "No component reads
> a source's identity from anything but a `Reader`" is unchanged.

> **Normative.** `Reader.name`'s docstring in `core/protocols.py` restates the
> superseded clause — "declared rather than configured", and "**Stable across
> calls**, and not a configurable value" — citing ADR-0093 §7. From this ADR's
> ratification that citation is read as naming §7 **as partially superseded here**,
> so the "not a configurable value" sentence binds nothing and no lane may rely on
> it. Its "stable across calls" half is untouched and still binds.

> **Normative.** The lane that admits a discriminated identity **corrects that
> docstring in the same change**, and may not land one against a sentence that
> forbids it. No lane may land a discriminated identity earlier by any other route.

> **Normative.** `ReaderContract`'s two identity clauses — that the declared
> identity is non-empty, and that it is stable across calls — are **unchanged and
> still bind**. Neither is disturbed by a discriminator: an identity assigned once
> at configuration cannot move under a read, which is the property that clause
> exists to pin. The suite gains no clause from this ADR.

> **Normative.** No `core/types.py` change is owed. An identity is carried as
> `Identifier` — non-blank, stripped, UTF-8-encodable — and both of §4's two forms
> satisfy it as written. ADR-0097 §9's canonicality rule reaches a discriminated
> identity exactly as it reaches a bare one (ADR-0189 §6). `Identifier` is not
> tightened to §4's form, because it types every identifier in the system and only
> a source identity has this shape; the refusal sits at §4's admitting seam.

**The docstring clause is stated as an obligation on a later lane rather than
discharged here, and the reason is golden rule 5.** A contract ADR lands as its own
PR ahead of anything implementing against it (ADR-0015 §5), and editing
`core/protocols.py` in this PR would make this ADR its own implementation. What the
clause buys is that the correction cannot be forgotten: the docstring is the text a
reader of the seam actually reads, and a discriminated identity landing beneath a
sentence saying identities are not configurable is the failure this clause names in
advance.

**The interval where the prose leads the code is ADR-0015 §5's design and not a
contradiction this ADR introduces.** A ratified contract ADR whose implementation
has not landed is the *ordinary* state of every contract decision in this corpus —
that is the whole content of "ratified before anything implements against it". The
docstring is not a second contract competing with this one; it is a restatement of
ADR-0093 §7 in code, and a restatement of a partially superseded clause is stale
prose rather than a live rule. The clause above says exactly which sentence goes
inert and which does not, so nothing in the interval is left to a reader's judgement,
and the tree stays conforming throughout because nothing in it returns a
discriminated identity — no second source can be configured at all (§6, ADR-0189 §8).

### 4. How an identity is spelled, in full, and the one seam that refuses a malformed one

> **Normative.** A **bare** identity is a reader type's declared name and nothing
> else: `"calendar"`, `"email"`. It is unchanged from what ADR-0093 §7 rules and what
> every reader on `main` returns today.

> **Normative.** A **discriminated** identity is that same declared name, then a
> single ASCII colon `":"`, then the discriminator — 32 characters drawn from
> `0123456789abcdef` and nothing else. There is no other form:
> `calendar:0f3c9d1a7b45e28c6d90fa3b17e4c852` is one, and a bare discriminator, an
> uppercase one, a differently-ordered one and a differently-separated one are not
> identities at all.

> **Normative.** A reader type's **declared name may not contain a colon**. That is
> what makes the declared part recoverable — it is the text before the first colon —
> and it is a new obligation on every `Reader`, stacked on ADR-0093 §7's existing
> ones and contradicting none of them, since no declared name in the tree or in the
> corpus contains one.

> **Normative.** Every seam that admits a source identity from configuration
> **refuses** a value that is neither of the two forms above, and refuses at the
> point of admission rather than at the point of use. This is ADR-0189 §6's "refused
> by every admitting seam if it is not of that form", made checkable by fixing the
> form. `Identifier`'s own rules (non-blank, stripped, UTF-8-encodable) and ADR-0097
> §9's canonicality rule bind in addition and neither is relaxed.

**The colon and the ordering are decided here, not left to the implementing lane,
and architecture review was right that they could not be.** An earlier draft deferred
both to "the lane that admits the second configured source, in the same change" — and
that lane is an implementation lane, so deferring a normative constraint on the values
crossing `Reader.name`, `SourceReading.source` and `Attestation.reported_by` into it
is precisely the contract decision ADR-0015 §5 and golden rule 5 put in a `Proposed`
ADR ahead of the implementation. The same draft also let §1's width read as the whole
identity while §4 required a recoverable declared part, which cannot both be true of
a 32-character value; §1's second clause now separates the discriminator from the
identity and this section spells the identity.

**Type first, discriminator second, because the prefix is the half that stays useful
when the value is cut short.** An identity lands in `Attestation.reported_by`, in
every export and in every log line, and ADR-0189 §5's display label is deferred — so
until it lands, a surface renders this value as the source's name. `calendar:0f3c…`
truncates to something a person can read; `0f3c…:calendar` does not, and a bare hex
identity would make ADR-0189 §4's requirement that a surface name the source
unsatisfiable in the interval. Sorting and grepping by type fall out of the same
choice.

**A colon rather than a dot or a dash, and the reason is that the alternatives are
already spoken for by the declared names themselves.** A declared name is a lowercase
word today, but nothing forbids `calendar-work` or `mail.local`, and a separator a
declared name may plausibly contain moves the ambiguity into the value. A colon has
never appeared in an identity in this corpus, is unambiguous against the hex
alphabet, and the "may not contain a colon" clause above makes the split total rather
than conventional. It stays inside `Identifier` — it is neither whitespace nor a
control character, so it is untouched by #62's open canonical-syntax question and
prejudges none of it (ADR-0018 §2).

### 5. This ADR classified under ADR-0070 §1 and ADR-0082 §1

**Against ADR-0093 — a partial supersession, recorded in this PR.** ADR-0070 §1's
test comes out on the supersession side and #1515 states why: a reader holding §7
would refuse to give a second configured calendar its own identity, and after this
ADR they would not. They act differently, so it is not an amendment. It is
**partial** — §2 above names what survives — and it is recorded the way ADR-0070 §4
and ADR-0082 §2 require: this ADR's `ADR-NNNN (<scope>)` pair is **added** to
ADR-0093's `Status` line beside ADR-0095's and ADR-0110's rather than replacing
either, and the extent is stated in an appended dated header note. That edit rides
in this same change, which is ADR-0110's own precedent on that file. No qualifier is
written on the `Status` line beyond the pair, because ADR-0082 §2 rules that a line
led by `Partially superseded by` carries the record in the note alone — and a
partial supersession pair is a canonical ADR-0070 §4 token rather than an amendment
qualifier, which is the same reading ADR-0110's note took on the same line.

**Against ADR-0189 — nothing is owed.** §6's refusal is written about ADR-0189
itself ("Nothing in **this ADR** permits…"), and stays true forever; §12 defers the
act to a named successor, and a reader holding ADR-0189 alone reads that a
discriminated identity awaits a later lane, which is exactly what has now happened.
Discharging a deferral on the terms it set is not amending it — ADR-0189 §11's own
words about ADR-0098 §8, applied to ADR-0189.

**Against ADR-0097 — nothing is owed.** §1's seam is adopted verbatim, §9's
canonicality rule is adopted verbatim, and §9a's precondition was discharged by
ADR-0189 §7 and is cited rather than re-ruled. What this ADR does to §9a is make
ADR-0189 §7's own last clause true: "until an ADR partially supersedes ADR-0093 §7
there is no second identity for a grant to name. When there is, its grantability is
decided by ADR-0097 §9 and ADR-0102 §4 exactly as a first source's is." Nothing
about how a grant is made, scoped or revoked changes.

**Against ADR-0102 — nothing is owed, and the near miss is worth naming.** Its
alternatives record "Give each configured reader instance its own grantable
identity" as "**Not available** rather than rejected: ADR-0093 §7 makes an identity
declared rather than configured", and half of that ground is what this ADR
supersedes. The entry's *conclusion* survives on stronger ground than the one it
cites: ADR-0189 §6's first clause rules the unit to be the configured source and not
the reader object, and `app/composition.py` builds three `CalendarReader` objects
for one configured calendar, so per-*instance* identities stay foreclosed. Under
ADR-0082 §1 no record is owed against ADR-0102 anyway — the entry is an alternatives
note and not a clause a reader acts on, and every normative clause of ADR-0102 stays
true, including "Several readers declaring one identity carry one configured
location", which two configured sources with two identities do not engage.

**Against ADR-0092 and ADR-0095 — nothing is owed.** `Attestation.reported_by`
carries "the connected source instance that reported this belief", which is what a
discriminated identity makes true rather than false; ADR-0095's renaming is
orthogonal.

**§4's no-colon rule is a stacked addition and is recorded here alone.** It puts a
new obligation on every `Reader`'s declared name, and it contradicts no sentence
ADR-0093 wrote: §7 already forbids deriving an identity from a location or contents
and names `"calendar"` as the calendar's, no declared name in the tree or the corpus
contains a colon, and no clause of ADR-0093 becomes false or over-wide. ADR-0082 §1
rules that such an addition "is recorded in the ADR that makes it, and nowhere
else", so ADR-0093's note carries the supersession's extent and not this.

Under ADR-0070 §1 this is a **partial supersession of ADR-0093 §7 and nothing
else**.

### 6. Deferred, by name, each with the condition that fires it

- **Where in a deployment's configuration a discriminator is written, and by what
  the value is minted.** §4 fixes the value's form and §1 fixes when it is assigned;
  the `Settings` shape that carries it is the registry's, since a deployment with one
  configured source per type never writes one (ADR-0189 §8, ADR-0093 §7a). Fires with
  the registry.
- **`Reader.name`'s docstring correction** (§3). Fires with that same lane, or with
  a contract lane that reaches `core/protocols.py` earlier, whichever comes first.
- **The source registry, the display label's configuration, and the client surface
  for more than one configured source.** Unchanged and still ADR-0189 §8's, with
  ADR-0093 §11's trigger unfired. This ADR removes a gate and supplies none of them.
- **Which of the three phrasings ADR-0093 §11's trigger has.** ADR-0189 §12's, and
  untouched: nothing here turns on which of them fires first.
- **A collision between a minted identity and a retired one, and a deliberate
  re-installation of a retired one.** ADR-0189 §12's two residuals, adopted with
  their stated bounds and their stated firing conditions, and not re-decided.

## Consequences

**The corpus no longer records a blocking gate with no owner.** #1515's finding was
that a capability four ratified documents plan for was blocked by a clause none of
them named as blocking it. After this ADR the remaining obstacles to a second
configured source are all *machinery* with stated triggers, which is a state a lane
can plan against.

**A lane that wants a second source can now start.** It still has to build the
registry, correct the docstring, and take ADR-0102 §14's client surface — but the
identity's form is settled (§4), so none of that needs an ADR-lane detour first,
which is what this PR costs and what it removes.

**ADR-0093 §7 becomes harder to read at a glance.** Its `Status` line now carries
three supersession pairs and its header three notes, and its identity clause reads
one way in the ratified text and another under the pointer. That is the price of the
append-only rule and ADR-0070 §3 already ruled it worth paying — "there is **no
requirement to pre-split** in anticipation of a future partial supersession" — but
the reading cost is real and lands on the next reader of that section.

**Nothing migrates.** Every attested record carries `reported_by="calendar"` or
`"email"` and every grant carries the same values as `source`; under the assign-once
rule those identities keep naming the source they have always named. No record is
rewritten and no grant is re-keyed, which ADR-0189 §6 already recorded when it
specified the rule.

## Alternatives considered

- **Leave ADR-0093 §7 standing and put the discriminator somewhere other than
  `Reader.name`.** Not available. ADR-0097 §1 rules that a grant "keys on nothing
  else", and ADR-0189 §6 tested the deferral of *which seam* carries the identity
  and found it foreclosed by that clause on its own round 2. An instance-identity
  value beside `Reader` cannot authorise a read, so it is not an identity.
- **Supersede ADR-0093 §7's identity clause wholly rather than partially.** Rejected.
  Three of its four properties — stable Tier 2, never derived from location or
  contents, no path or address as any part — are what make a minted discriminator
  admissible in the first place, and ADR-0189 §6 adopts all three by name. A whole
  supersession would drop the grounds along with the prohibition.
- **Wait for the second source before writing this.** Rejected, and this is the
  ADR-0189 §6 judgement revisited rather than reversed (Context). The cost of waiting
  is not a delayed decision: it is that the lane building the second source
  discovers, at the moment it starts, that it must stop and run an ADR lane against
  another document's `Status` line first. The specification it would write is already
  ratified, so waiting buys no information — it only moves a fixed cost onto a lane
  that has something else to do.
- **Defer the identity's spelling to the lane that admits the second source, beside
  the validator that enforces it.** This is what the first draft did, and it is
  **rejected** — architecture review's round-1 blocker was correct. The argument for
  it was that a separator is chosen best where it is enforced; the answer is that the
  lane enforcing it is an implementation lane, and a normative constraint on the
  values crossing `Reader.name`, `SourceReading.source` and `Attestation.reported_by`
  is a contract decision ADR-0015 §5 and golden rule 5 require in a `Proposed` ADR
  merged ahead of any implementation. Half a specification in a doorway ADR is also
  the failure ADR-0189 §12 named in advance when it called this lane
  "fully-specified".
- **Make a later source's identity the bare 32-hex discriminator, with no declared
  part.** Rejected in §4. It is the simplest form and it costs ADR-0093 §7's
  "declared by the sensor" half entirely, where this ADR only needed the "not a
  configurable value" half. It also makes ADR-0189 §4's requirement that a surface
  name the source unsatisfiable until §5's display label lands, since the only thing
  a surface could render is 32 hex characters.
- **Tighten `Identifier` to §4's two forms.** Rejected in §3. `Identifier` types
  every identifier in the system — deferral ids, conversation ids, grant ids — and
  only a source identity has this shape, so the tightening would refuse values that
  are correct. The refusal belongs at the seam that admits a source identity, which
  is where §4 puts it.
