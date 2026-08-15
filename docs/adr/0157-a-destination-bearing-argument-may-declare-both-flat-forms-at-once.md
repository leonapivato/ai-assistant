# 157. A destination-bearing argument may declare both flat forms at once, and nothing else widens

- Status: Accepted
- Date: 2026-08-15
- Partially supersedes: ADR-0152 (§4's flat-declaration clause, and §6's unshaped-destination refusal in its declaration limb alone)
- **This ADR adds a third admitted declaration shape and admits no new value.**
  ADR-0152 §4 fixed the shapes a destination-bearing argument's subschema may
  take at "exactly one of two forms and no other" — a JSON string, or an array of
  JSON strings. §1 below adds a third: the two-branch `anyOf` whose branches are
  exactly those two forms. The set of **values** the seam accepts is not touched
  and cannot be: ADR-0152 §4's per-call clause already admits "a JSON string or a
  JSON array of JSON strings", which is the union this ADR lets an author
  *declare*. So every refusal **this ADR reaches** — the binding seam's, in
  ADR-0152 §4 and §6 — fires on exactly the calls it fired on before. One refusal
  this ADR does not reach does change, and it is the point of the change rather
  than a side effect: once the implementing lane widens `send_email`'s own schema,
  ADR-0145's validation stops refusing a bare-string `to` against that tool. That
  follows from the **producer's** declaration moving, which is a fact about one
  tool, and not from any rule stated here.
- **It is a partial supersession, not an amendment, and §6 shows the working.**
  A reader holding only ADR-0152 §4 refuses the three-form declaration; after
  this ADR they admit it. That is ADR-0070 §1's test coming out on the
  supersession side, so ADR-0152's ratified text is left unrewritten and its
  `Status` line and appended dated note are the whole of the record (ADR-0070 §1,
  ADR-0082 §1 and §2).
- **It is not the widening ADR-0152 §4's last clause asks for, and does not
  discharge it.** That clause governs "a **structured** destination-bearing
  argument" and requires its ADR to state "how a supplied form is located inside
  that shape". There is no structure here and no supplied form is located inside
  anything, so §2 below re-states the structural bar rather than spending it, and
  it stays live and unspent for the shape it was written against.
- **No implementation lands with it, and here that is obligatory rather than an
  operating preference.** This change touches no `src/`, no `tests/` and no
  `pyproject.toml`. What it does touch is the rule the `EgressBinder` Protocol
  states as its own contract, so a conforming implementation must move — both of
  them, the seam and the canonical fake. That is ADR-0015 §5's and golden rule
  5's condition met, and they require this ADR ratified and merged before the
  implementation PR. §7 points at those two rules rather than asserting a
  delivery clause of its own, and inventories the five edits and the tests, so
  the implementing lane is briefable from this text alone.
- **Every reference below to ADR-NNNN is to its text as merged on 2026-08-15**,
  the durability form ADR-0100 established and ADR-0149, ADR-0150, ADR-0151,
  ADR-0152 and ADR-0153 each applied. This decision rests most heavily on
  ADR-0152 §4 and §6 and on ADR-0150 §4, and ADR-0152 **is edited by this change**,
  in the same commit that proposes it (§6).
- **Records owed on other ADRs: one, against ADR-0152, and §6 shows the working**
  ADR by ADR — including the near misses: ADR-0152's own §1, §2 and §13, which
  §7's `core/protocols.py` edit puts in a reader's way; ADR-0150 §11's routed
  question; and ADR-0145 §5's one-dialect rule. Each is a reviewer's to contest
  by naming the sentence that becomes false. No other `Status` line moves.

## Context

ADR-0152 §4 took the structural option ADR-0150 §11 left open and constrained a
destination-bearing argument to a flat shape. The constraint is stated twice — as
a rule about **declarations** ("an argument may be marked destination-bearing
**only** where its subschema is a flat declaration") and as a rule about **calls**
("a call in which a declared destination-bearing argument carries a value that is
not a JSON string and not a JSON array of JSON strings … is refused"). The two are
not the same width. The per-call clause admits the union of both forms; the
declaration clause makes an author pick one of them and forbids expressing the
union, naming "a union of types" and "an applicator (`allOf`, `anyOf`, `oneOf`,
`not`, `if`/`then`/`else`) in place of a type" among the shapes that are not flat.

`send_email` picked the array. ADR-0152 §4 recorded the consequence as costless:

> `send_email` declares `to`, `cc` and `bcc` as `{"type": "array", "items": {"type":
> "string"}}`, so every destination it can name already sits in a span that can carry
> it and this constraint refuses none of its calls.

**That sentence is true and was read as more than it says.** §4's constraint does
refuse none of `send_email`'s calls — it never gets the chance, because ADR-0145
validates the arguments against the schema §4 forced first, and refuses there.
The gap between the two readings is the whole of this ADR's subject, and it did
not surface until something composed a call.

**What composed one was the pipeline, and it composes strings.** Leg 12's QA run
(#1159) drove three natural phrasings through a live hub against a registered
`send_email` and recorded the result in #1160: both singular phrasings — "send an
email to X", "Email X saying …" — produced `to` as a bare JSON string and were
refused with `step_parameters_invalid` before any ruling; the plural phrasing
produced an array and reached the binder. Two of two singular sends were
unreachable, and the singular send is the commonest form of the act.

The composition is nobody's defect. `planning/` is deliberately tool-blind — steps
name abstract capabilities and the model composes parameters with no schema in
hand (ADR-0044 lineage) — so the model's choice between a string and an array is
made without knowing which one the declaration picked, and it picks the one the
sentence's grammar suggests. ADR-0145 then refuses the step exactly as ruled. Each
piece behaves as its ADR requires and the composition makes the commonest form of
the act systematically unreachable.

**Three routes were available and two are worse.** Feeding selected tools' schemas
into planning breaches the capability abstraction on purpose and wants its own
decision; a bounded replan carrying violation shapes back to the model is ADR-0145
§13 adjacency and is parked as this arc's successor (#1105, #1106). Both are
mechanisms. The third is to stop making the author pick — to let the declaration
say what the per-call clause already says. That is this ADR, and it is the only
one of the three that adds no mechanism at all.

**The evidence test ADR-0152 §4 decided itself on is what changed.** §4 declined
the structured shape on ADR-0073 §4's standing test — "the producer in hand wants
flat, and the producer that wants structured does not exist, so the constraint is
the decision the evidence supports and the widening is the decision that waits for
evidence." The producer that wants the union does exist, is in the tree, and is
measured. That is the evidence arriving, which is the condition §4 itself set for
revisiting.

## Decision

### 1. The third flat form is the two-branch `anyOf`, and its branches are the two existing forms

> **Normative.** A subschema is a **flat declaration** — ADR-0152 §4's term, and
> the property an argument must have to be marked destination-bearing — where it
> takes any one of three forms: `"type": "string"`; `"type": "array"` whose
> `items` is a subschema whose own `"type"` is `"string"`; or an `anyOf` holding
> **exactly two** branch subschemas, one of them the first form and the other the
> second, in either order. This replaces ADR-0152 §4's enumeration of two forms
> and changes nothing else that clause states.

> **Normative.** The `anyOf` form admits no other spelling of the same union. A
> subschema declaring a union of types (`"type": ["string", "array"]`), a
> `oneOf`, an `allOf`, a `not`, an `if`/`then`/`else`, an `anyOf` with one branch
> or with three or more, an `anyOf` whose branch is itself an applicator or a
> `$ref`, or an `anyOf` carried beside a sibling `"type"` on the same subschema,
> is **not** a flat declaration, and a declaration marking such an argument
> destination-bearing is **refused** when the declaration is read, before any
> call is made.

**One spelling rather than every equivalent one, and the reason is not tidiness.**
A union of types would be the shorter form and it is the one refused most firmly,
because it decides the element type somewhere the reader does not look. Under
draft 2020-12 `items` applies to an instance only when the instance is an array,
so `{"type": ["string", "array"]}` with no sibling `items` admits an array of
numbers, and with one it admits the right thing only because a keyword outside the
type declaration happened to be present. Reading it correctly means knowing which
sibling keywords apply to which branch of a type union — a model of the dialect's
applicator vocabulary, which `tools/egress_declaration.py` deliberately does not
have and says so: its walk "knows nothing about the dialect", because "an unknown
applicator is exactly where a mis-declaration would hide". The `anyOf` form keeps
each branch **self-contained**: every branch is literally one of the two shapes
already admitted, checkable by the check that already exists, applied once per
branch.

`oneOf` is refused for a different reason and a weaker one — it would be
*equivalent* here, since no instance is both a string and an array, so the choice
between them is free. Two spellings of one fact in one vocabulary is the
duplication ADR-0150 is named against, and `anyOf` is the one that states the
weaker claim: a reader confirming a declaration is well-formed does not have to
establish that the branches are disjoint.

> **Normative.** Both keywords ADR-0152 §3 defines stay on the argument's **own**
> subschema — beside `anyOf`, where they sit beside `"type"` today — and appear
> on no branch. ADR-0152 §3's rule stands unchanged and unweakened: a keyword
> anywhere other than the immediate subschema of a top-level property is refused
> rather than ignored, and a branch of an `anyOf` is not that subschema. No lane
> reads the third form as opening a second place a declaration may be written.

That clause adds no machinery. ADR-0152 §3's deep, structure-blind walk already
refuses either keyword inside any applicator, which is exactly where a branch is;
the clause is here because the third form puts an applicator on a subschema that
carries the keywords for the first time, and a rule that is enforced but unstated
is the kind a later lane relaxes by accident.

> **Normative.** A constraint the argument's array form carries is **not dropped**
> in the restructuring. `send_email`'s `to` carries `minItems: 1`; under the third
> form it is carried on the array **branch**, where it constrains what it
> constrained before. Placement binds the author who restructures a declaration;
> it is not a condition of flatness, and the next clause states what follows.

`minItems: 1` is load-bearing rather than decorative, and the restructuring is
where it would be lost. Without it `{"to": []}` satisfies the schema and
`required`; the binder's decomposition then yields **no** span for `to` at all,
and ADR-0152 §6's omitted-destination refusal does not fire, because that refusal
is written over a span that carries no destination and not over an argument that
produced no span. An empty array is ADR-0150 §4's total omission, the one member
of the family §4 says stays reachable, and `minItems` is what keeps it out of
`send_email`. The string branch needs no counterpart: `{"to": ""}` reaches the
canonicaliser, which produces no canonical form for it, and ADR-0152 §6's
uncompletable-call refusal fires.

> **Normative.** A keyword sitting beside `anyOf` on the argument's own subschema
> **does not bear on whether that subschema is a flat declaration**, with exactly
> two exceptions, both of them already refused there by clauses above: `"type"`,
> which the second clause refuses beside `anyOf` by name, and `"$ref"`, which §2's
> first clause refuses and which ADR-0152 §4 refused before it. Subject to those
> two, a declaration is not refused for carrying an array constraint beside
> `anyOf` rather than on the array branch. The two existing forms already work
> this way and always have, so the third form inherits the tolerance rather than
> being granted a new one.

**The tolerance is safe because keywords on one subschema are conjunctive, and
the two exceptions are not exceptions to that.** A sibling beside `anyOf` is
`AND`-ed with it, so it can only *narrow* what the subschema admits; no sibling
can admit a value the `anyOf` refuses, and §2's structural bar therefore cannot
be reached by adding one. `"type"` and `"$ref"` are refused for the other reason
the first clause's reasoning turns on — not that they widen, but that they put
the shape somewhere the seam does not read. A sibling `"type"` leaves which
branch applies to be settled by a model of the dialect's applicator vocabulary;
a sibling `"$ref"` leaves the shape itself outside the walk, which is why
`_flat_defect` guards `$ref` before it reads anything else and refuses it for
both existing forms today. The remaining spellings the second clause names —
`oneOf`, `allOf`, `not`, `if`/`then`/`else` — are already caught as siblings,
because that clause refuses a subschema *declaring* one of them however it is
carried.

**What that leaves is the misplaced array constraint, and refusing it would cost
the property the third form was chosen for.** `send_email`'s `to` carries
`minItems: 1` beside `"type": "array"` today and is a flat declaration under
ADR-0152 §4; the seam's check reads `type`, `items` and `$ref` and is blind to
every other sibling. To refuse `minItems` beside `anyOf` while admitting it beside
`"type": "array"`, the seam would have to know that `minItems` is a constraint on
arrays — a fact about the dialect's applicator vocabulary, which is exactly the
model `tools/egress_declaration.py` deliberately does not have, and which the
first clause's own reasoning for preferring `anyOf` over a union of types turns
on. A rule cannot be justified by that blindness in one clause and require its
opposite in another.

**And nothing is lost by admitting it, which is why the placement rule above binds
the author rather than the seam.** Under draft 2020-12 `minItems` applies to an
instance only when the instance is an array, so on the argument's own subschema it
constrains the array branch's instances and is vacuously satisfied by the string
branch's: `{"to": []}` is refused either way, for the same reason. The two
placements admit the same values, and the array branch is still where the keyword
belongs — a reader checking the array form's constraints should find them on the
array form — which makes it an authoring rule that §7 briefs and a reviewer of the
implementing lane enforces, not a refusal the binder grows a dialect model to
reach.

### 2. Nothing structural widens, and ADR-0152 §4's widening clause is untouched

> **Normative.** This ADR admits no structured destination-bearing argument. An
> object, an array of objects, an array holding a non-string element, a `$ref`
> reaching either, or any shape from which a supplied form would have to be
> located *inside* a value stays refused at the declaration and at the call.

> **Normative.** ADR-0152 §4's widening clause is **not discharged** by this ADR
> and stays live in full. A later ADR admitting a structured destination-bearing
> argument still arrives on the terms that clause fixes — with the producer whose
> recipient shape forces it, stating how a supplied form is located inside that
> shape and how the check ADR-0150 §4 could not perform is then performed. No
> lane cites this ADR toward that widening, and no lane widens the shape by
> building a seam that accepts more.

**Every property ADR-0152 §4 bought survives this change verbatim, and the reason
is that the value set is identical.** §4's purchase was that two of ADR-0150 §4's
three under-representation failures stop being *reachable* for a destination: a
destination-bearing argument's value decomposes to exactly one recipient in
exactly one span, so partial omission has no instance, and a supplied form is
never extracted from inside a structured value, so mis-representation has none. A
string decomposes to exactly one recipient in exactly one span. An array of
strings decomposes to exactly one recipient per span. Those are the only two
values the third form admits, and they are the only two the per-call clause
admitted already. `core`'s own supplied-form invariant — stated over "a JSON
string" and "a JSON array whose element at `index` is a JSON string" — stays
total, over the same set it was total over yesterday.

**So the asymmetry ADR-0152 §4 weighed comes out the other way here, on §4's own
scales.** §4 weighed a recoverable authoring-time error against "a description
narrower than the payload … reached by a recipient sitting inside a value the
description could not decompose", and refused the shape because the second cost is
one ADR-0148 §6 says an approver may never bear. Neither side of that ledger has
an entry in this change. No description narrows, because no value is admitted that
was not admitted before; nothing sits inside anything. What is on the ledger
instead is measured: a form of the act that cannot be performed at all (#1159,
#1160).

### 3. The per-call clause, the binder and the seam are untouched

> **Normative.** ADR-0152 §4's per-call clause is unchanged and is not widened by
> this ADR: a call in which a declared destination-bearing argument carries a
> value that is not a JSON string and not a JSON array of JSON strings is refused
> before the ruling, whether or not the declaration clause has already refused the
> declaration. ADR-0152 §6's five other refusals, its read-binding clause and its
> residual clause are likewise unchanged.

> **Normative.** The binding seam's derivation is unchanged. A destination-bearing
> argument holding a JSON string is one span whose locator carries no index; one
> holding an array of JSON strings is one span per element, each locator carrying
> its index. That is ADR-0150 §4's decomposition applied to the values it already
> governed, and no lane reads this ADR as changing an extent, a locator, a
> canonical form, a tier or a provenance.

This section is why the change is narrow enough to be worth making. The seam
already implements both halves: `tools/egress_binder.py` returns from its
per-call shape refusal on a string as readily as on a tuple of strings, and its
decomposition already puts a string in a single indexless span. What made the
string unreachable was never the seam — it was that no declaration could be
written that let one arrive.

**One consequence is worth stating rather than discovering.** The same recipient
reaches a different locator depending on which form the caller composed:
`{"to": "a@example.com"}` yields a span with no index, `{"to": ["a@example.com"]}`
yields one with index `0`. This is not created here — both were already admitted
values, and ADR-0150 §4 already assigned them those locators — but this ADR makes
both reachable through one declaration for the first time, so a reader comparing
two decisions over semantically identical calls will now see it. Nothing depends
on the two agreeing: a decision is bound to its own parameters digest, `rebind`
re-derives from the same parameters it was recorded against, and no clause
compares locators across calls.

### 4. What this ADR does not decide

Scoping something out is a decision, so each carries its reason (ADR-0029 §7's
form).

> **Normative.** Nothing here decides how a planner composes parameters, and no
> lane cites this ADR toward feeding tool schemas into `planning/`, toward a
> replan-on-`INVALID_PARAMETERS` loop, or toward any other repair mechanism.
> #1105 and #1106 carry that territory and it is deliberately unspent: this ADR
> removes the mismatch rather than building a path to report it.

> **Normative.** Nothing here decides how a violation is reported to a user,
> which ADR-0145 §11's refusal-message discipline owns, nor relaxes ADR-0145 §5's
> one-dialect rule: the third form is draft 2020-12 `anyOf`, evaluated by the
> dialect the repository already reads, and no new dialect, vocabulary or keyword
> is introduced.

> **Normative.** Nothing here adds a `DestinationProtocol` member, widens `SMTP`'s
> acceptance boundary, authorises a canonicaliser, designates a seam, attests an
> ADR-0017 §3 condition, or registers a tool. Each of those needs its own ratified
> ADR on the terms ADR-0150 §3, ADR-0017 §2 and ADR-0154 fix.

> **Normative.** Nothing here decides whether any other tool's arguments should
> take the third form. It admits the shape; a tool's author declares what that
> tool's arguments are, and ADR-0016 §1's "declared, not inferred" is unchanged.

### 5. Why this is one clause of ADR-0152 and not a rewrite of it

ADR-0152 is a large contract ADR and this ADR replaces one enumeration inside one
of its sections. §6 states the extent formally; this section states what a reader
of ADR-0152 should still act on, because a partial supersession is only legible if
the remainder is named.

Everything ADR-0152 decides outside §4's declaration enumeration stands: the seam
derives the binding whole and accepts no part of it (§5); the six refusals, with
the one limb §6 below names (§6); `rebind`'s re-derivation and the forged-canonical
refusal (§7); the non-egress path (§8); the failure class and disposition (§9); the
seam's placement and its one-record read budget (§10); the refusal-message
discipline (§11); everything §12 declines to decide; and every obligation §13 puts
on the implementing lane, all of which have since been discharged. §3's two-keyword
vocabulary is not merely unchanged but relied on: §1 above puts a clause behind it.

### 6. This ADR classified under ADR-0070 §1 and ADR-0082 §1

ADR-0082 §1 requires the judgement in the later ADR's text and fixes its form: a
record is owed on an earlier ADR exactly where this ADR **amends a named clause**
of it — where "a reader holding only the earlier ADR now acts differently, or reads
one of its clauses more widely than it now holds". ADR-0148 §12, ADR-0150 §13,
ADR-0152 §15 and ADR-0153 §10 are the worked precedents for this section's form.

**The conclusion first: one record is owed, against ADR-0152, and it is written.**
What follows is the working, and a disagreement with it takes ADR-0082 §1's own
form — naming the sentence that does, or does not, become false or over-wide.

**ADR-0152 §4 — record owed, and this is a supersession rather than an
amendment.** The clause is §4's first normative clause, and the sentence that
becomes false is exact: "which is exactly one of two forms and no other". After
this ADR it is three. A reader holding only ADR-0152 refuses a declaration this
ADR requires them to admit, which is ADR-0070 §1's test — "a change to what was
decided is anything a reader would act on differently" — coming out on the
supersession side without ambiguity. It is **partial**: §4's per-call clause, its
assumes-nothing clause, its "these clauses are the whole of the constraint" clause
and its widening clause each stay true word for word, and §2 and §3 above rely on
all four.

**ADR-0152 §6 — record owed, one limb of one refusal.** The *unshaped destination*
refusal has two limbs in one sentence: "The seam refuses a call in which a declared
destination-bearing argument carries a value that is not a JSON string or a JSON
array of JSON strings (§4), and refuses a declaration that marks such an argument
at all (§4)." The first limb is unchanged — the values are the same values. The
second reads through to §4's enumeration, so it is over-wide the moment that
enumeration grows, in exactly ADR-0082 §1's second sense. It is restated **here**
rather than rewritten there, because ADR-0070 §4 makes the superseding ADR the
authority on extent and ADR-0070 §1 forbids rewriting ratified text: the limb now
refuses a declaration that is not one of §1's three forms.

**The record's form, and why ADR-0152's body is not edited.** ADR-0070 §1 permits
exactly two header edits to ADR-0152 here, and both are made:

1. its `Status` line, replaced with the leading-token partial form ADR-0070 §4
   fixes — §1's "recording a supersession that has landed";
2. an appended dated header note, which is §1's fourth permitted edit and which
   ADR-0082 §2 makes the place the **substance** of the record lives on a line led
   by `Partially superseded by`.

Nothing else is touched, and neither reaches ADR-0152's Context, Decision or
Consequences.

**Both are made in the change that proposes this ADR, not deferred to its
ratification commit** — the two files move as one atomic pair, and this ADR says
so explicitly because the contrary reading is a known and recurring one. ADR-0070
§1 permits the `Status` edit for "a supersession that has landed" and glosses the
permission as presupposing that "the superseding ADR *exists*". ADR-0082 §7 rules
on the misreading of that phrase by name, as **#458**, and calls it "not a
governance gap but a reviewer failure mode":

> §1's condition is that the superseding ADR **exists**, not that it is ratified —
> the hazard §1 names is a `Status` line pointing at nothing, and an atomic pair
> makes that unreachable.

An atomic pair is what this is: no state of `main` carries either half without the
other, so the hazard has no instance here. Deferring the record would also cost
something ADR-0082 §7's reasoning implies and this ADR states outright — the scope
record *is* the substance of the supersession, and moving it into the
`Proposed` → `Accepted` flip would land it in the one edit `CONTRIBUTING.md` marks
as skipping review, so the only reviewed artifact would be the one that never
carried it. The flip therefore moves this ADR's own `Status` line and records its
review outcome, and nothing else.

**No `Accepted:` line is added to ADR-0152, and the temptation to add one is worth
naming because the next lane will meet it.** ADR-0070 §4 requires the supersession
token to **lead** and `Accepted` to be dropped from the line, so a filter
prefix-matching `Accepted` cannot read a partially-superseded ADR as fully
current. The cost is that ADR-0152's header stops saying it was ever ratified —
and adding an `Accepted: 2026-08-14` line to put that back reads like a
no-decision correction. It is declined on two grounds. **ADR-0070 §1 enumerates
the header edits it permits** — ratifying, recording a supersession, correcting a
`Status` line, appending a dated note — and this is none of them; the enumeration
is the permission, and reading the sentence's no-decision-change condition as a
standing licence beside it would make the list decorative. **And ADR-0126 is not
the precedent it appears to be**: its `Accepted: 2026-08-10` line was written by
its own ratification commit, before ADR-0153 touched it, so no superseding lane
has ever added one. Nothing is lost that matters — ADR-0152's `Date` line stands,
its ratification is in the history, and the note above is dated.

Not one word of ADR-0152's Context, Decision or Consequences is touched, so §4 and
§6 stay legible as ratified beside the pointer to this ADR — which is what
ADR-0070 §2 did to ADR-0001 and ADR-0153 §10 did to ADR-0126.

**ADR-0152 §1, §2 and §13 — no record owed, and §7's `core/protocols.py` edit is
why a reader might expect one.** §1 fixes `EgressBinder`'s two members and §2 the
six `core` names, and neither moves: §7 authorises the docstring's statement of
§4's rule and nothing else in the file. The docstring is a **transcription** of
ADR-0152 §4, not an independent decision, so correcting it records what the record
against §4 already records rather than a second thing. §13's obligations on the
implementing lane were discharged and stay discharged — the triad still exists and
still has all three parts; what §7 asks of the fake and the shared suite is those
parts tracking a rule that moved, which is ADR-0137 §3 working rather than
ADR-0152 §13 reopening.

**ADR-0150 §4 and §11 — no record owed, and this is the nearest miss, so the
working is explicit.** §11 routed the structural question to ADR-0152 and neither
required nor forbade the answer; §4 states the decomposition and the supplied-form
invariant. The contrary case a reviewer is entitled to press is that §4's
invariant was made *total* by ADR-0152 §4's constraint, so loosening that
constraint reads §4's invariant more widely. It does not, and the reason is
arithmetic rather than argument: §4's invariant is stated over "a JSON string" and
"a JSON array whose element at `index` is a JSON string", which is the value set
this ADR leaves bit-for-bit unchanged. Totality is a property of the values a
destination-bearing argument can hold, and no value is added. §11's routed
question was answered by ADR-0152 and stays answered; this ADR changes the answer's
enumeration, not its addressee, which is why the record is owed there and not
here.

**ADR-0145 §5 and §9 — no record owed.** §5's one-dialect rule requires the
dialect to be declared rather than assumed and is satisfied unchanged: `anyOf` is
draft 2020-12's own applicator, evaluated by the evaluator the repository already
runs, and §4 above states that no keyword or vocabulary is added. §9's "an absent
schema declares no constraint" is untouched — this ADR is about a schema that is
present and says more than it did. A reviewer pressing this would need a sentence
of ADR-0145 that becomes false, and the schema this ADR admits is one ADR-0145
already evaluates correctly today.

**ADR-0044, ADR-0016 §1, ADR-0148 §2, ADR-0146 §5 — no record owed, each a
stacked non-change.** The planner stays tool-blind and nothing here reaches
`planning/`; declarations stay declared rather than inferred, and §1's third form
is a shape an author writes rather than one anything derives; a mis-declared
destination-bearing argument stays undetectable in the semantic sense ADR-0152 §12
names, neither more nor less than before; and which fields establish a tier is
untouched, since this ADR changes a shape and not a field's meaning.

**ADR-0154 and ADR-0155 — no record owed.** Designation and residency are
untouched; this ADR authorises no byte and §4 says so normatively.

### 7. What the implementing lane owes

> **Normative.** The implementation's **production** surface is authorised in
> exactly three locations and no others: `core/protocols.py`,
> `src/ai_assistant/testing/egress.py`, and `src/ai_assistant/tools/**`. Inside
> `core/protocols.py` the authorisation is narrow and exhaustive: the
> `EgressBinder` docstring's statement of the flat-declaration rule — the
> class-level sentence enumerating the flat forms, and the `bind` `Raises`
> entry's declaration limb, which reads through to it — restated to §1's three
> forms. **No member, no signature, no `core` type, no validator and no `core`
> invariant moves**, because the value set is unchanged (§3): `core/types.py` is
> not touched at all, and ADR-0150 §4's supplied-form invariant stays total over
> the same values it was total over before.

> **Normative.** The tests these changes require are expected to fall entirely
> within `tests/tools/**`, which is where every case stating the declaration rule
> lives today, including the shared conformance suite. No test outside it states
> that rule; a test elsewhere needing an incidental adjustment is adaptation the
> lane makes without this clause being read as forbidding it.

**The rule this ADR changes is enforced by two independent implementations and
stated normatively in a third file, and a scope clause naming only the seam's own
check would send this ADR's implementing lane into a STOP.** The obvious location
is `tools/egress_declaration.py`'s `_flat_defect`, the check the seam runs. The
other two are why the clause above enumerates rather than excludes:

- **`core/protocols.py` states the rule normatively, as `EgressBinder`'s own
  contract.** Its class docstring reads "A destination-bearing argument is flat
  (ADR-0152 §4): its subschema is `"type": "string"` or `"type": "array"` whose
  `items` is a subschema whose own `"type"` is `"string"`, and nothing else." The
  closing three words are the ones §1 makes false, and that sentence is not a
  comment about an implementation — under golden rule 1 it is the thing
  implementations are written against. Leaving it would have `core` asserting a
  rule the seam no longer enforces, with no lane authorised to correct it.
- **`testing/egress.py` carries an independent second copy of it.**
  `FakeEgressBinder._refuse_unflat` re-implements the flat test rather than
  calling the seam's, and `tests/tools/test_fake_egress_binder.py` holds the fake
  to the shared suite through `TestFakeEgressBinderContract`. So a suite case for
  §1's third form fails against the fake until the fake moves, and a fake left
  behind refuses a declaration the real seam admits — the drift the triad exists
  to prevent. ADR-0137 §3 forbids splitting a triad, and this is that clause
  biting on a rule change rather than on a new Protocol.

**All three locations are adaptation in ADR-0137 §1's sense, so the
implementation stays one lane.** Nothing here is a store, a loop, a codec, a
producer or a policy; every edit restates one already-implemented rule in a place
that already states it. §1's own clause settles what follows: "Adaptation does not
count against the bound in this section. A lane may carry adaptation across any
number of subsystems." So the at-most-one-subsystem bound is not engaged, and
whoever dispatches this fences the lane at the three locations above rather than
splitting `core/`, `testing/` and `tools/` into three.

**This ADR is therefore delivered ahead of its implementation because ADR-0015 §5
and golden rule 5 require it, not because a dispatcher preferred it.** §5 obliges
separate delivery of "a substantive contract ADR — one adding or changing a
Protocol or a `core/` type crossing subsystem boundaries", and golden rule 5
obliges it of a Protocol change. This decision changes what the `EgressBinder`
Protocol requires of a conforming implementation — both implementations in the
tree become non-conforming the moment it is ratified — and it changes the text
`core/protocols.py` states as that contract. No member and no signature moves, so
the change is confined to the stated rule; the obligation is the same either way,
and it is discharged by this PR. **This ADR still asserts no delivery clause of
its own**: the obligation is those two rules', read against the scope the clause
above states, and a later lane cites them rather than this section.

**One knock-on for the implementing lane's own review.** ADR-0015 §1: "A change
touching `core/protocols.py` or `core/types.py` must additionally carry the
architecture lens." The implementation PR touches the first, so its required set
is adversarial **and** architecture, as this ADR's own is (§8).

The five edits, inventoried so the lane is briefable from this text:

- **`core/protocols.py`** — the `EgressBinder` class docstring's flat-form
  sentence, restated to §1's three forms, and the `bind` `Raises` entry's
  declaration limb if the lane judges that it reads over-wide on its own. The
  per-call limb beside it — "whose value is not a JSON string or a JSON array of
  JSON strings" — is correct as written and stays (§3). Nothing else in the file.
- **`testing/egress.py`** — `FakeEgressBinder._refuse_unflat`, the fake's own
  copy of the rule, moved to §1's three forms and refusing every other spelling
  §1's second clause names. Its refusal message names the argument and the defect
  as it does today; ADR-0152 §11's discipline is unchanged and no value is
  rendered.
- **`tools/egress_declaration.py`** — the flatness check admits §1's third form
  and refuses every other spelling of the union (§1's second clause). The natural
  shape is to apply the existing per-subschema check to each branch, so the third
  form is checked by the check that already exists rather than by a second one,
  and to keep the refusal messages naming the argument and the defect as they do
  today. The message ending "widening that needs its own ratified ADR" is updated
  to say which widening still needs one (Consequences).
- **`tools/send_email.py`** — `to`, `cc` and `bcc` take the third form, with
  `to`'s `minItems: 1` on the array branch (§1's fourth clause). The module's
  docstring states the array form is "one of exactly two shapes"; that sentence
  is this lane's to correct, and it is not ratified text.
- **`tools/egress.py`** — `smtp_message` reads each recipient argument as a list
  and refuses a string outright, so the transport accepts one form of a pair the
  seam now admits both of. It canonicalises a string to a one-element list at that
  point. This is a rendering of an already-authorised call rather than a
  re-derivation of one, so ADR-0148 §4's third clause is not engaged: the
  arguments still reach the transport exactly as authorised, and what changes is
  how the message is rendered from them.

> **Normative.** The declaration cases go into the **shared conformance suite**
> `tests/tools/egress_binder_contract.py` and not into a per-implementation test,
> so the seam and the canonical fake are held to §1 by one suite (ADR-0152 §13).
> That suite's `test_a_non_flat_destination_bearing_declaration_is_refused`
> parametrisation and its `test_a_flat_string_destination_argument_is_admitted`
> are where the enumeration is stated today, and they are the cases that move.

> **Normative.** The lane ships, at minimum: a declaration test per admitted form
> and per refused spelling named in §1's second clause; the two cases §1's fifth
> clause separates, which are where two conforming implementations could otherwise
> diverge on whether a tool loads — the third form **admitted** while carrying an
> array constraint beside `anyOf` on the argument's own subschema, and the third
> form **refused** while carrying a sibling `"$ref"` there; a call-level test that a
> string-valued and an array-valued destination argument each bind, with the
> locators §3 states; a test that `{"to": []}` is still refused; and a transport
> test that a string-valued recipient argument transmits to exactly that one
> recipient. `tests/tools/test_egress_failure_paths.py` currently pins a
> string-valued `to` as refused at the transport under the id
> `recipients-not-a-list`; that case is inverted rather than deleted, so the
> record shows the behaviour changed rather than the test disappearing.

> **Normative.** At least one of those tests is taken over the **real**
> `SEND_EMAIL` definition and not a synthetic one: with the schema this section's
> inventory changes, a call whose `to` is a bare JSON string is reported by
> ADR-0145's schema validation as carrying **no** violation, binds, and reaches
> the transport. A suite exercising only a synthetic tool that declares the third
> form does not discharge this clause.

**That clause is the one a reviewer should press hardest, and it is here because
every other test in the list can pass while #1160 stays open.** A lane could widen
the flatness check, widen the transport, prove both against a synthetic tool
declaring the third form, leave `SEND_EMAIL`'s own `to` array-only, and ship a
green suite over the exact call #1159 recorded as refused — because nothing else
in the list requires the *registered producer's* schema to have moved. #1160's
first sentence is that every per-lane suite was green while the composed act was
unreachable, and an obligation that could be discharged the same way would be that
failure restated one level up, in the ADR written to remove it.

> **Normative.** The lane closes #1160 and states in its PR that the
> feedback-loop half of that issue's title is out of scope and stays with #1105
> and #1106.

### 8. Marking, review and ratification

**Marked under ADR-0089**, so this ADR is in the marked regime: its unmarked prose
supplies no obligation and exists to determine what the marked clauses mean (§3
there). Marking is forward-only (§5), and nothing ratified before it is drawn into
the regime by it.

**The required set is adversarial *and* architecture.** `CONTRIBUTING.md` →
"Contract ADRs land before their implementation" requires both on an ADR PR, and
this one earns the architecture lens twice over. By category: it partially
supersedes a contract ADR and changes the rule a Protocol states as its own
contract (§7). And on its own facts: the question a reviewer most needs to press
— whether the value set really is unchanged, and therefore whether ADR-0150 §4's
invariant really does stay total — is an architecture question answerable from
the prose before an implementation has committed to an answer. Both are run
while this ADR stands `Proposed` so that a finding can still change the decision.
`CONTRIBUTING.md` → "Finishing an ADR PR" owns the sequence; this section points at
it rather than re-deriving it, and the outcome is recorded here on ratification —
in the ratification commit itself, not before it, because a paragraph asserting a
verdict a review has not yet returned is a claim rather than a record.

**Outcome.** Both required lenses returned **APPROVE with no findings on one
tree** — `419f1a1fc0da`, reviewed while this ADR stood `Proposed`, which is what
the paragraph above asks for. The loop ran long and across three holders under
ADR-0138, and four findings changed the decision rather than its wording:

- **The scope clause was factually wrong, and would have sent this ADR's own
  implementing lane into a STOP.** §7 once said no `core/` change was required or
  authorised and that the whole implementation lay in `tools/**`. A conforming
  implementation must also move `testing/egress.py`, whose canonical fake carries
  an independent copy of the flat rule, and the `EgressBinder` docstring in
  `core/protocols.py`, which states that rule as the Protocol's own contract —
  the one edit golden rule 5 makes a hard STOP for a dispatched lane told it is
  unauthorised. §7 now authorises three production locations exhaustively and
  argues one lane from ADR-0137 §1's adaptation clause.
- **The delivery grounding was inverted, and the correction is not the one the
  finding that raised it asked for.** An architecture round objected to citing
  ADR-0015 §5 and golden rule 5 for the separate-PR delivery; its *mechanism*
  stood — do not cite a rule for something it does not state — but its premise did
  not, because this ADR does change the rule a Protocol states as its own
  contract. So the citation returns on corrected grounds. The delivery itself
  never moved; only whether it was obligatory or an operating preference, and it
  is obligatory.
- **§1's third form was silent on keywords sitting beside `anyOf`**, while its
  fourth clause normatively placed an array constraint on the array branch — so
  two conforming implementations could have diverged on whether the same tool
  loads, which is the drift the shared conformance suite exists to prevent. §1's
  fifth clause settles it, and settles it toward tolerance because the seam is
  deliberately blind to the dialect and refusing a misplaced constraint would
  require the model §1's own reasoning says it lacks.
- **That clause's first form was itself too wide**, admitting a sibling `$ref`
  that §2's first clause refuses and that the seam has guarded before every other
  read since ADR-0152 §4. It now names its two exceptions and rests the tolerance
  on the fact that carries it — keywords on one subschema are conjunctive, so a
  sibling can only narrow and cannot reach §2's structural bar.

No finding was waived, none is contested, and no issue was deferred out of this
PR.

**That commit carries two things and no others**: this `Status` line moving
`Proposed` → `Accepted`, and the outcome paragraph above it. It touches one file.
ADR-0152's record is **not** in it — §6 states why, and the short of it is that a
scope record made in an edit that skips review would be the substance of this
supersession arriving where nobody reviewed it.

## Consequences

- **The commonest form of a send becomes reachable, and no mechanism was added to
  reach it.** The route out of #1160 costs five edits — three inside `tools/`, one
  docstring in `core/protocols.py` and one in the canonical fake — and no new
  machinery, no new seam, no new keyword and no new dialect. Every one of them
  restates a rule that already exists, in a place that already states it, which
  is why §7 can fence them together as one lane. The alternatives named in #1160
  each cost a mechanism; both stay available and neither is spent.
- **A tool author gains a choice and a small obligation with it.** Declaring both
  forms is now possible, so an author who wants only one still states only one,
  and an author who takes the third form must put the array form's constraints on
  the array branch. §1's `minItems` clause exists because that is the one place
  the restructuring silently loses a safety property.
- **The refusal text a tool author sees stops being the last word.** The message
  `tools/egress_declaration.py` renders today ends "widening that needs its own
  ratified ADR", which was accurate and is now half-true: widening to the union of
  the flat forms has this ADR, and widening to a structured shape still needs one.
  The implementing lane owes that message an update, and §7 asks for it.
- **ADR-0152 §4's evidence test is discharged in the direction it pointed, not
  overruled.** §4 said the widening "waits for evidence" and named ADR-0073 §4.
  The evidence arrived from a QA run against a live hub rather than from an
  argument, which is the shape ADR-0073 §4 asks for, and the part of §4 that was
  never about evidence — the structural bar on shapes with a supplied form buried
  inside them — is untouched.
- **A locator now varies with the form the caller composed, for one argument
  across two calls.** §3 states it. Nothing depends on the two agreeing today, and
  a later lane that wants them to agree is choosing a canonicalisation this ADR
  deliberately does not impose: normalising a string to a one-element array at the
  seam would be the seam accepting one shape and describing another, which is what
  ADR-0152 §5 forbids.
- **The corpus gains a precedent for narrowing a structural constraint without
  reopening it.** ADR-0152 §4 wrote its own conditions for being revisited and
  this ADR meets them rather than arguing around them; the shape of the record —
  one enumeration replaced, one limb of one refusal restated in the superseding
  ADR, no ratified text rewritten — is ADR-0070 §3's partial supersession working
  as designed.
- **Nothing here authorises a byte.** No call this seam refused yesterday is
  admitted today. What changes is which declarations a tool author may write, and
  until the implementing lane lands, not even that.
