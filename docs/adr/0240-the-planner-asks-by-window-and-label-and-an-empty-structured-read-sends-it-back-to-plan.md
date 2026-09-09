# 240. The planner asks by window and by label, and an empty structured read sends it back to plan

- Status: Proposed
- Date: 2026-09-08
- **Partially supersedes**
  [ADR-0228](0228-a-serviced-read-may-revise-the-plan-once-and-the-turn-stops-looking-at-a-bound-or-a-deadline.md)
  — **§2's condition (e), in exactly one scope: a `STRUCTURED_READ` whose store call
  ran and returned no record at all satisfies (e), under the other six conditions
  unchanged.** (e) reads *"The servicing returned **at least one record the supply did
  not already hold**, counted after ADR-0226 §7's deduplication"*, and a read that
  returned nothing returns none. A reader holding only ADR-0228 refuses that revision,
  which is ADR-0070 §1's test met, and §3's partial form is the sanctioned tool. **The
  scope is that condition and nothing else.** (a), (b), (c), (d), (f) and (g) bind
  verbatim; §2's *"all of them"* rule is unchanged; §2's last clause — that no
  implementation *"retries a failed servicing, widens a request, re-asks the planner on
  a different prompt, or substitutes a read of its own"* — binds entire and is what
  makes the broadening the **planner's** rather than the loop's; and (e)'s own reason,
  that a planner called twice over one input is asked the same question twice, is
  honoured rather than set aside, because §7 below gives the second call an input the
  first did not have. §3's bound of two planner calls is untouched and is the bound on
  this revision too.
- **And of the same ADR, two further scopes, taken together as one:** **§12's no-signal
  clause and §1's nothing-else clause**, in the single respect that the second planner
  call receives §7 below's carrier — a defaulted `Planner.plan` parameter holding, byte
  for byte, the asks of this turn's reads that returned nothing. §12 rules that *"No lane
  adds an iteration index, a 'last look' instruction or any other signal to the planner's
  input, and `Planner.plan`'s signature gains no parameter"*; §1 that *"what a revision
  plans over that the first plan did not is the fourth group and nothing else"*. **Every
  other signal those clauses forbid stays forbidden** — the iteration index, the "last
  look" instruction, a count of the turn's calls, and any signal about its budget or its
  deadline — and §1's enumeration of what is not re-run binds verbatim: one context
  assembly, one tail read, one retrieval, one episodic supplement, and no group of the
  supply beyond the fourth. §15 works both, including why §12's clause is recorded
  against on the reading that binds every lane rather than only ADR-0228's own.
- **Amends the same ADR** — **§11's two-kinds statement, and that alone.** §11 reads
  *"Both kinds a revision may emit are the two that ADR admits, both terminate in the
  owner's own `MemoryStore`"*, which ADR-0230 and ADR-0231 have already made an
  undercount and which §1 below undercounts again. **§11's rulings are untouched and
  two of them are load-bearing:** *"This ADR adds **no kind** to ADR-0226 §2's
  enumeration"* stays a true statement about ADR-0228; its no-filtering clause and its
  class clause on a planner-composed query bind on this kind unchanged; and its
  inward-only argument is **strengthened rather than moved**, because a
  `STRUCTURED_READ` terminates in the owner's own `MemoryStore` exactly as the two
  kinds §11 was written over do. This ADR's own leading token is a supersession of the
  same ADR, so under ADR-0082 §2 both records live in ADR-0228's appended dated note
  and no amendment qualifier is written on its `Status` line; the qualifier ADR-0230
  left there moves into the note carrying that record, which is ADR-0080 §8's
  operation as ADR-0082 §2 generalises it.
- **Amends**
  [ADR-0226](0226-the-planner-names-one-more-read-beside-its-plan-and-the-loop-services-it-into-the-supply.md)
  — **§2's membership sentence and §6's cross-kind precedence sentence, in one respect
  each.** §2 reads *"The enumeration's two members are `SIGHTED_QUERY` and
  `CITATION_HOP`"* and §6 reads *"**The citation hop is serviced first, and the sighted
  query fills what remains.**"* §1 below adds a fifth member and §5 below gives it a
  position between the hop and the query, so a reader holding only ADR-0226 reads both
  sentences more widely than they now hold and ADR-0082 §1's test is met on each.
  **Neither ruling is replaced.** §1's additive-entry clause is the licence this ADR is
  taken under and is quoted in §1 below; §2's statement of what each named kind *is*,
  its at-most-one-ask-of-each-kind rule and its closure against un-ADR'd additions bind
  entire; and §6's decision — the capped read ahead of the uncapped one, and the
  sighted query as the read that *fills what remains* — is not merely intact but is the
  reason §5 below puts this kind where it puts it. §3's namer rule and no-identifier
  rule, §5's channel scoping and degradation posture, §6's budget of ten and
  second-budget rule, §7's fourth group, whole-union deduplication,
  discards-nothing-by-class clause and constructed-once rule, §8's trigger and §9's
  audit all bind as ratified and are load-bearing here. ADR-0226's `Status` line
  carries the leading `Partially superseded by` token, so this record lives in its
  appended dated note and not on that line (ADR-0082 §2).
- **Amends**
  [ADR-0230](0230-the-planner-names-a-file-it-was-shown-and-the-loop-fetches-it-into-the-supply.md)
  — **§7's servicing-order sentence, and that alone.** §7 reads *"**The servicing order
  is: local file, then citation hop, then sighted query.**"* ADR-0231 §11 has already
  amended it once; §5 below inserts a fifth position, so it is over-wide in a further
  respect and ADR-0082 §1's test is met again. **§7's decision is applied and not
  replaced**: it orders by cap, which is ADR-0226 §6's rule, and §5 below reaches its
  own position by that same rule. Every other clause of §7 binds unchanged and is
  load-bearing: one servicing site, ADR-0226 §5 entire, the one budget of ten counted
  after deduplication, the fourth group with no fifth, the single evaluation over the
  turn's final supply, and a revision admitted on ADR-0228 §2's conditions. ADR-0230's
  `Status` line carries the leading `Partially superseded by` token from ADR-0232, so
  this record lives in an appended dated note (ADR-0082 §2).
- **Amends**
  [ADR-0231](0231-the-planner-asks-for-a-search-the-turns-own-words-compose-it-and-the-results-come-back-as-records.md)
  — **§11's servicing-order sentence, and that alone.** §11 reads *"**The servicing
  order is: local file, then web search, then citation hop, then sighted query.**"* §5
  below inserts a fifth position between the hop and the query. **§11's decision is
  applied and not replaced** — it fixes the order *"here rather than derived per
  deployment"* by sorting the kinds by their caps, and §5 below sorts one more kind by
  the same rule. §11's one-site clause, its channel scoping, its one-budget clause, its
  never-larger-than-the-budget clause and its revision clause bind unchanged.
  ADR-0231's `Status` line carries the leading `Partially superseded by` token from
  ADR-0235 and ADR-0238, so this record lives in an appended dated note (ADR-0082 §2).
- **Decides a change to `src/ai_assistant/core/types.py`** — one added `ReadKind`
  member, one added frozen model, one additive defaulted field on `ReadAsk` with its
  validator arm, and `PlanExport.schema_version` moving by one — **and a change to
  `src/ai_assistant/core/protocols.py`**: `Planner.plan` gains one additive, defaulted
  keyword parameter (§7). **That parameter is a Protocol change and is flagged as a
  breaking change under golden rule 5**, exactly as ADR-0230 §3 flagged its own
  `files`: every `Planner` implementation must be widened to declare it, and §7 states
  what survives the widening and what does not. **This ADR changes no code.** §12
  states what the implementing lane owes; nothing implements against it until it has
  merged (ADR-0015 §5, golden rule 5).

## Context

### Where this comes from

`track:planning` (#1908) earns the planner sight rung by rung. Milestone 27 built the
envelope — the planner names one read beside its plan and the loop services it into the
supply (ADR-0226); milestone 28 made the plan revisable over what that read returned
(ADR-0228); milestone 29 took the planner off the store, first to the owner's disk
(ADR-0230) and then to the web (ADR-0231). **Milestone 30 is the rung on which the
planner asks by *structure* rather than by text** — a period, and the people and topics
a record carries — and #1908 states it in three parts: the store read, the producer
that fills the labels, and the envelope kind that asks for it.

The first two are ratified and merged. **ADR-0237** gives `MemoryStore` four filter
axes over values the records already carry and a query-less `select` beside `search`;
its §9 names *this* lane in as many words — *"a planner envelope kind carrying a time
window, mapped onto `occurred_within` (#1908's M30, `track:planning`)"*. **ADR-0239**
gives the observation pass the ability to label the episodes it read, and its §11
defers *"A structured read over these labels"* to the ADR that decides that read. This
is the planner-facing half of that read, and nothing else: the store surface is
ADR-0237's and the producer is ADR-0239's.

#1908's own audit for this milestone is the sharpening this ADR is written against, and
its third point is the one that shapes §6: **"an empty structured result is not proof
nothing happened — the planner broadens rather than concluding"**.

### The tree, read rather than assumed, at `origin/main` `fd191f5d`

- `core/types.py` carries `ReadKind` with **four** members — `SIGHTED_QUERY`,
  `CITATION_HOP`, `LOCAL_FILE`, `WEB_SEARCH` — and `ReadAsk` with `kind`, `query`,
  `labels` and `entry` under `ConfigDict(extra="forbid", frozen=True)`, its
  `_the_ask_carries_exactly_its_kind_s_argument` validator dispatching one arm per
  kind. `ReadRequest` refuses an empty `asks` and a second ask of one kind.
- `orchestration/reads.py`'s `service_read_request` is the one servicing site, and it
  services in the order ADR-0231 §11 fixes. **The sighted query's store call is
  `assemble_by_band(store, statement, limit=allowed, kinds=BELIEF_KINDS, …)`**, and
  `BELIEF_KINDS` in `orchestration/conversations.py` is `SEMANTIC`, `PREFERENCE`,
  `PROCEDURAL`. So the sighted query **cannot reach an episode at all**, and no read on
  the envelope can.
- `planning/planner.py` renders `f"  now: {context.now.isoformat()}"` into the
  user-turn prompt, so an absolute window is composable from *"last week"* without the
  planner being told the date twice. `_optional_read_request` reads the request back
  from the envelope, builds at most one ask per kind, and **drops what it cannot read,
  logging each drop** — a malformed request costs the request and never the plan.
  `_system_prompt(capabilities, *, files_shown)` states the `file` member **only where
  the turn passed a listing**, because ADR-0230 §2 makes a turn with no listing one on
  which no file is nameable.
- `core/protocols.py`'s `Planner.plan` takes `goal`, and keyword-only `context`,
  `memories`, `capabilities` and `files: Sequence[ShownFile] = ()`.
- `wire/envelope.py` carries `PROTOCOL_VERSION` **31**; `core/types.py` carries
  `PlanExport.schema_version` as `Literal[6]`.
- **`TimeWindow`, `occurred_within` and `MemoryStore.select` are not in `src/` yet.**
  ADR-0237 is Accepted and merged; its implementation is PR #2140, open at the time of
  writing. Every reference to them below is to ADR-0237's ratified text, which is what
  this ADR is written against and what the implementing lane will find in the tree.

### What the corpus already decides, and is used here as given

- **ADR-0226 §1** — the enumeration is closed, and *"A later kind is an **additive
  entry to this enumeration**, not a second seam. An ADR admitting one adds a member
  and states that kind's namer, its servicing, its share of §6's budget and its audit
  fields"*. It also rules that *"no lane widens an admitted kind's meaning to carry a
  read the ADR that admitted it did not describe"*, which is why the window does not go
  on `SIGHTED_QUERY` and why §2 below states this kind's four axes at admission rather
  than leaving room to add one later.
- **ADR-0226 §3** — the namer rule, the no-identifier rule, and that a label outside
  the shown set resolves to nothing, silently and into the audit.
- **ADR-0226 §5, §6, §7, §9** — one servicing site, the channel scoping, the
  degrade-never-fail posture, one budget of ten counted after deduplication, the capped
  read ahead of the uncapped one, the fourth group, and an audit of counts and kinds
  that copies no text.
- **ADR-0228 §1, §2, §3, §7** — a revision is a second plan over the supply the first
  plan's read produced; seven conditions and all of them; two planner calls and not
  configurable; each servicing draws its own budget of ten.
- **ADR-0237 §1–§8** — the four axes and their pre-cut binding; `TimeWindow`'s
  half-open `[start, end)` shape and its two refusals; the argument law (`None` is not
  applied, an empty sequence selects nothing, disjunction within an axis and
  conjunction across); ADR-0101 §2's fold on both person axes and exact characters on
  `topics`; `select`'s order and cleared `score`; **§6's empty-means-unrecorded rule
  and its disclosure obligation**; and **§7's certification** — that on an uncapped
  read *"an empty structured result does tell a caller that no record carries those
  labels in that window"* while asserting nothing about the world.
- **ADR-0239 §4, §6** — a participant label's canonical form, that it resolves to
  nothing, and that an empty axis states that no label was recorded.
- **ADR-0230 §3** — the precedent for an additive, defaulted keyword on `Planner.plan`,
  and its honest paragraph on what such a widening does and does not buy.
- **ADR-0228 §10** — the shape of a bare fact carried to the composing stage: inside
  `orchestration`, no `core` field, no Protocol member, no count and no copied text.

### Claims in the framing that do not survive contact with the tree

Three, recorded because each would have produced a wrong design or a wrong citation.

1. **The lane's brief cites "ADR-0230 §2's *conditional guidance* reasoning" for the
   prompt rule. ADR-0230 carries no such phrase.** What it carries is §2's ruling that
   *"A turn on which the loop passed no listing is a turn on which no file is
   nameable"* and §3's that a deployment with no fetcher *"renders no listing into any
   prompt"*; the conditional *guidance* is `planning/planner.py`'s
   `_system_prompt(…, files_shown=…)`, which the tree carries and which ADR-0230 §3
   licenses rather than states. §9 below takes the substance and cites it where it
   actually lives.
2. **"The planner broadens (28's revision) rather than concluding" is not available on
   the mechanism as ratified**, and ADR-0237's own Context says so: §2(e) of ADR-0228
   fires no revision on a read that returned nothing. This ADR does not work around
   that sentence — it moves it, narrowly, in the header record above and in §6.
3. **ADR-0237 §7 may not be cited toward the broadening**, by its own words: *"no lane
   may cite this section as evidence that the broadening exists"*. It is cited here for
   what it **rules** — what an empty result means, and what no consumer may compose
   from one — and the ground for §6 is #1908's milestone and §6's own argument.

### What this ADR is not allowed to settle

- **The store surface.** ADR-0237 decided it. This ADR adds no axis, no matching rule,
  no order and no member to `MemoryStore`, and it may not read one of ADR-0237's
  clauses more widely than that ADR wrote it.
- **The producer that fills the who/what axes.** ADR-0239 decided it and its
  implementation is its own lane. This ADR designs no labeller and proposes no label.
- **Hybrid or lexical search** (ADR-0006 §5, ADR-0226 §12) — a different retrieval
  mechanism, not a filter over stored values, and a later lane's.
- **An event-time axis** (ADR-0237 §8, §11). `occurred_within` filters on the instant
  of the *exchange*, and §3 below inherits that caveat rather than repairing it.
- **Anything at the egress seam.** This kind reads the owner's own store and nothing
  else; ADR-0154 §7 and ADR-0017 §1 are neither approached nor cited toward anything.
- **A transcript-archive entry anywhere** (ADR-0225 §4, §12), which stays unapproached.

## Decision

We will admit **one more kind** to ADR-0226 §1's enumeration — a **structured read the
planner composes from the conversation**, naming a period and the people and topics a
record carries — service it through ADR-0237's two reads into the same fourth group
under the same budget, and rule that a structured read which reached the store and
found **nothing** is a fact the planner is told, so that the turn broadens under
ADR-0228's revision instead of concluding from an absence.

### 1. The kind: `STRUCTURED_READ`, an additive fifth member and not a second seam

> **Normative.** `ReadKind` gains one member, `STRUCTURED_READ`, valued
> `structured_read`. It is an **additive entry** under ADR-0226 §1 — *"A later kind is
> an additive entry to this enumeration, not a second seam. An ADR admitting one adds a
> member and states that kind's namer, its servicing, its share of §6's budget and its
> audit fields; it does not introduce a second request object, a second servicing site,
> a second budget or a second audit."* It adds none of those four, and every clause
> ADR-0226, ADR-0228, ADR-0230 and ADR-0231 state over a read request binds on it
> except where a section below names the exception and shows its working.

> **Normative.** ADR-0226 §2's at-most-one-ask-of-each-kind rule and `ReadRequest`'s
> validator bind unchanged: one emission carries at most one `STRUCTURED_READ` ask, and
> a request naming two is not an emission this corpus admits. A turn that revises may
> emit a second `STRUCTURED_READ` ask on its second plan, which is ADR-0228 §3 applied
> and not widened.

> **Normative.** **One ask is one read.** No implementation issues two store calls for
> one ask, splits an ask across axes into several calls, re-issues a call with a
> different window, or repairs, widens or narrows the ask it was given. There is no
> pagination and no traversal, and no later lane adds one without the ADR that decides
> it.

**A fifth member rather than a window bolted onto `SIGHTED_QUERY`, and ADR-0226 decides
it twice over.** §1 rules that *"no lane widens an admitted kind's meaning to carry a
read the ADR that admitted it did not describe"*, and §2 says what a `SIGHTED_QUERY`
**is**: *"a **query** the planner composed"*, serviced by `assemble_by_band` *"with the
band precedence, per-band composition and kind selection of the retrieval stage's own
read unchanged"*. Adding filters to it would widen an admitted kind's meaning against
the first sentence and would change the second's servicing against the second. The
enumeration's own growth path is the additive entry, and this is one.

**And on the tree the two kinds do not even reach the same records.** The sighted
query's kind selection is `BELIEF_KINDS`, so it reaches semantic, preference and
procedural records and **no episode**; §4 below fixes this kind to episodes. A reader
looking for the overlap that would make a fifth member redundant does not find one: the
envelope has had no read that can reach an episode since ADR-0226 opened it, and the
milestone's whole subject — *"which conversation was that"* — is episodes.

**One read and not a decomposition.** ADR-0226 §12 and ADR-0228 §14 defer splitting a
compound question across several asks of one kind, and this ADR takes no part of it: a
planner that wants two periods issues one ask and gets one read, exactly as ADR-0237 §2
says a caller wanting two disjoint periods *"issues two calls and composes"* — which
across turns is what iteration already gives it.

### 2. The ask: one structure, four axes, an optional query, and what the model refuses

> **Normative.** `core/types.py` gains one frozen model, `StructuredAsk`, carrying the
> four axes ADR-0237 §1 put on `MemoryStore`: `window: TimeWindow | None`,
> `participants: tuple[NonBlankEncodableText, ...] | None`, `topics: tuple[TopicLabel,
> ...] | None` and `about_person: tuple[NonBlankEncodableText, ...] | None`, each
> defaulting to `None`. It refuses unknown fields and refuses mutation.

> **Normative.** **`None` on an axis means the axis is not applied, and an empty
> sequence is refused with `ValueError` on every sequence axis.** The axes this model
> carries reach `MemoryStore` unchanged — `None` for `None`, and the values given
> otherwise — so no implementation translates between an ask's convention and the
> store's, and no lane reads `()` here as "not applied" or as "selects nothing".

> **Normative.** **A `StructuredAsk` applies at least one of its four axes**, and one
> applying none is refused with `ValueError`. A query alone is a `SIGHTED_QUERY` and
> not this kind.

> **Normative.** `ReadAsk` gains one field, `structure: StructuredAsk | None`,
> defaulting to `None`, carried for a `STRUCTURED_READ` ask and for no other. Its
> validator gains one arm: a `STRUCTURED_READ` ask carries a non-`None` `structure`, no
> `labels` and no `entry`, and **may** carry a non-blank `query`; every other kind
> carries no `structure`. Each condition is enforced by the model rather than by its
> callers, exactly as ADR-0226 §4 requires of the arms already there.

> **Normative.** **`ReadAsk.query`'s meaning widens by exactly one kind and by nothing
> else.** It stays the query the planner composed, non-blank, carried byte for byte,
> required on a `SIGHTED_QUERY` and refused on a `CITATION_HOP`, a `LOCAL_FILE` and a
> `WEB_SEARCH`. On a `STRUCTURED_READ` it is optional, and its presence is what §4
> makes the difference between the two store members.

> **Normative.** `TimeWindow` is used exactly as ADR-0237 §2 defines it and is not
> re-expressed: the half-open `[start, end)` reading, the unset ends, the refusal of a
> window with both ends unset and the refusal of one whose `end` is not strictly after
> its `start` are that ADR's and are inherited whole. This ADR adds no second window
> type, no second window on one ask, and no sequence of windows.

**A value object for the four axes rather than four fields on `ReadAsk`, and the reason
is ADR-0237 §2's own.** That section put the window in a type because *"the three
ambiguities … are exactly what two stores would implement differently"* and a value
object *"puts them in one validated place"*. The same holds one level up for the axis
set: "at least one axis applied" is a condition over the four together, and a model
carrying them is where it is stated once. It also keeps `ReadAsk` legible — one field
per kind's argument, which is ADR-0230 §1's rule for `entry` applied rather than bent.

**But `query` is reused rather than twinned, and that is the same rule reaching the
opposite answer.** ADR-0230 §1 gave `entry` its own field because a `CITATION_HOP`
label and a `LOCAL_FILE` label *"name different sequences"* — two namespaces in one
field, where a reader would have to consult `kind` to know which sequence a string
indexes. A query is not a namespace: it is a text the planner composed, passed to
`MemoryStore.search` byte for byte, with one meaning at both sites. A second field
carrying the same value under a second name would be the drift ADR-0128 §5 and ADR-0237
§4 both refuse, and a reader consulting `kind` would learn nothing they did not already
know.

**The empty sequence is refused here where ADR-0237 admits it, and the asymmetry is the
one ADR-0237 §2 already drew for the window.** `TimeWindow()` is refused on a query
where `Validity()` is admitted on a record, because a query that reached for a bound
and named none is a caller that said nothing. An `()` on `participants` is the same
shape: on the store it means *select nothing*, which is a coherent thing for a caller
to compute and an incoherent thing for a planner to ask for — an ask occupying the one
slot its kind has while asking for a result that is empty by construction, which is
ADR-0226 §4's empty-request reasoning one level down. Refusing it at the model also
removes the convention mismatch outright: there is exactly one spelling of "not
applied" on this path, and it is `None`.

**At least one axis, because a query-only structured read is a `SIGHTED_QUERY` wearing
another kind's name.** ADR-0237 §4 makes the same requirement of `select` — *"A
`select` call applies **at least one** of its six axes"* — for the same reason: no
value of any axis means "everything". Requiring a *structural* axis rather than merely
any axis is this ADR's own addition, and it is what keeps the two kinds distinct at the
type rather than by convention.

### 3. The namer: values the planner composed, and the grammar it writes them in

> **Normative.** ADR-0226 §3's namer rule binds this kind as written: **the namer may
> be data, or the user, or the model pointing outward — never the model pointing
> inward.** A window and a label are **values**, of the same class as a `SIGHTED_QUERY`
> ask's query — composed by the planner from the conversation and from the records it
> was shown, matched by the store's own rule, and resolving to nothing.

> **Normative.** ADR-0226 §3's no-identifier rule binds and is not approached. **No
> record identifier is rendered to a model, and none is accepted from one.** No axis of
> a `StructuredAsk` is an identifier, a key or a reference; a person label resolves to
> nothing (ADR-0237 §3, ADR-0239 §4), a topic label resolves to nothing (ADR-0213 §3),
> and a window names an interval rather than a record. No implementation resolves any
> of them to a record, an id, a person or a concept.

> **Normative.** **The window is written in absolute UTC instants and the loop composes
> none.** The planner writes ISO-8601 instants; no implementation converts a relative
> phrase into a window, infers a window from the utterance, supplies a default window,
> extends one, or clamps one to a retention horizon. The clock the planner reads is the
> `now` the turn's own prompt already carries.

> **Normative.** **A label is carried byte for byte from the planner to the store.** No
> implementation trims, casefolds, normalises, strips, tokenises, truncates or
> otherwise transforms a value on any axis at the planner seam or at the servicing
> seam. Matching is ADR-0237 §3's and is the store's alone.

> **Normative.** **A malformed member costs the whole ask and never the plan, and the
> ask is never partially repaired.** Where any axis of a `STRUCTURED_READ` ask cannot be
> read as the model this section fixes — a window **endpoint that is present and is not
> a readable instant**, a window `TimeWindow` refuses, a label the canonical form
> refuses, an empty sequence, an axis set applying nothing — the ask is dropped whole,
> the drop is logged as every other unreadable ask already is, and the plan stands. No
> implementation drops the offending axis and services the rest.

> **Normative.** **An absent endpoint is not a malformed one.** ADR-0237 §2 admits a
> window with either end unset — an unbounded side — and refuses only the both-unset and
> the inverted cases, so *"everything since the first of September"* is a window this ask
> carries and no implementation drops it for naming one instant.

**A composed value is admitted by §3's own terms, and the sentence that decides it is
§2's.** ADR-0226 §2 admits a `SIGHTED_QUERY` ask carrying *"a **query** the planner
composed"*, so the corpus already rules that a planner-composed *value* is not the model
pointing inward. What §3 forbids is a model naming a **record** — *"it never parses an
identifier out of model output, and it never treats a model-supplied string as an
identifier"* — and the widest abuse this kind admits is asking the store for records
that carry values the planner named, which the store answers by matching characters. A
label the planner invented reaches records that carry it; a label nothing carries
reaches nothing (ADR-0237 §6). Neither is a pointer.

**The window is absolute because the alternative puts a clock in two places.** A
relative window — "last week" — resolved by the loop would make the turn's answer depend
on which of two components read the clock and when, and ADR-0228 §1 has already ruled
that the context is assembled once per turn and the second call receives the same one. The
planner is shown `now` in its own prompt (`planning/planner.py` renders it), so an
absolute window costs it nothing and leaves exactly one reading of the turn's instant.

**Dropping the whole ask rather than the offending axis is ADR-0228 §2's last clause
applied at the emitting seam.** A read composed of *some* of the axes the planner named
is a different read from the one it asked for — wider, and wider in a direction nobody
chose — and *"substitutes a read of its own for one the planner did not ask for"* is the
thing no implementation may do. ADR-0239 §5 judges a *labelling* per axis, and that is a
different object for a stated reason: a labelling's two axes are *"never read for each
other"*, where a structured read's axes compose by conjunction and dropping one changes
what the remaining ones select.

**What this inherits and does not repair.** `occurred_within` filters on the instant of
the exchange and not of the event (ADR-0237 §8), so a window is a question about when
the talking happened. §8 below is where a turn's reply is kept honest about that, and
§14 defers the axis that would change it.

### 4. What is read: episodes, through ADR-0237's two members and nothing else

> **Normative.** **A `STRUCTURED_READ` is serviced over episodic records and over no
> other kind.** The servicer passes `kinds` naming `MemoryKind.EPISODIC` on every call
> it makes for this ask, and the ask carries **no kind axis and no band axis**: neither
> is a value the planner names, and no later lane adds one without the ADR that decides
> it.

> **Normative.** **The ask maps onto ADR-0237's two reads and the query decides
> which.** An ask carrying a `query` is serviced by `MemoryStore.search`, with the
> query passed as handed and the four axes passed from the `StructuredAsk`; an ask
> carrying none is serviced by `MemoryStore.select` with the same axes. No other member
> is called for this kind, no call is made twice, and no implementation substitutes one
> member for the other.

> **Normative.** Every clause of ADR-0237 binds on those calls as written and none is
> narrowed here: the pre-cut binding of every axis, the argument law, the matching
> rules, `select`'s order and cleared `score`, `search`'s relevance order and populated
> `score`, ADR-0128 §2's four `capped` clauses, and **§6's rule that a filter reaches a
> record if and only if the record carries a value on that axis**.

> **Normative.** **Beliefs stay reachable exactly as they are today** — by the
> retrieval stage and by a `SIGHTED_QUERY` — and this ADR neither narrows nor widens
> either. No lane widens this kind to beliefs, and no lane narrows the sighted query to
> episodes.

**One axis is admitted knowing no producer can fill it, and that is ADR-0226 §1 working
rather than an oversight.** `about_person` reaches no episode any producer writes:
capture writes none, and ADR-0239 §7 rules that the episode-labelling producer *"writes
**no `about_person`**, on an episode or on anything else"*, with ADR-0100 §4 forbidding
one to be inferred. ADR-0239 §11 defers the field on an episode by name and fires it only
*"with an ADR that reckons with that clause"*. The axis is nonetheless stated here,
because ADR-0226 §1 forbids a later lane from *"widening an admitted kind's meaning to
carry a read the ADR that admitted it did not describe"* — an axis this ADR left out
could not be added to this kind afterwards without superseding §1. So it is described at
admission and it is **inert until ADR-0239 §11's deferral fires**; §9's gate keeps it out
of the prompt meanwhile, because no record in any supply carries a value on it, and §13
asserts that inertness as the *specified* behaviour rather than leaving it to be
discovered. The milestone's own exit is served by `participants`, which ADR-0239 §1's
producer does write.

**Episodes, because that is the population the envelope cannot otherwise reach and the
one the milestone is about.** The turn already reads beliefs three ways — the retrieval
stage, the sighted query, and the citation hop's evidence — and reads episodes twice,
both blind: the conversation tail and the episodic supplement. #1908's milestone is
*"it remembered the right conversation"*, and a conversation is an episode. Fixing the
kind here rather than admitting a kind axis also keeps ADR-0237 §5's own caveat out of
this path: that section orders `select` by `provenance.last_updated` for totality,
because *"a call whose filters admit a semantic belief and an episode has no
`occurred_at` to compare across the pair"*, and a read confined to episodes never
produces that pair.

**And the kind axis is not the planner's to name, which is the same line ADR-0226 §3
draws elsewhere.** `kinds` and `bands` are the store's partitioning vocabulary; a
planner writing one would be steering *how the store is read* rather than naming what
it wants, and the loop would have to render the vocabulary into the prompt to make it
nameable. The planner names a period and the labels a record carries; the servicer
knows which population answers that.

**Two members and not one, because ADR-0237 §4 decided it and its reason binds here.**
A structured lookup expressed as a similarity search *is* a similarity search, and *"which
conversations involved Alex in March" has no text to be near*. Where the planner **does**
have text, ADR-0237 §4's own sentence is the case: *"'A time-window filter over episodes
**plus** the existing text query' is a filtered *relevance* read … That is `search` with
`occurred_within`, and it is why the axes are not confined to the new member."* One ask
covers both because the planner's own composition — did it have text worth ranking by? —
is exactly the distinction between them.

### 5. Servicing: one site, one budget, and where the structured read sits

> **Normative.** A `STRUCTURED_READ` ask is serviced in `orchestration/reads.py`'s
> `service_read_request` and nowhere else, inside the turn, after the planner returns
> and before the `TurnResult` is constructed. ADR-0226 §5 binds entire: the servicer is
> not the composing stage, is not a tool, is registered nowhere, advertises no
> capability, and **a servicing failure degrades the turn and never fails it**.

> **Normative.** **ADR-0226 §5's channel scoping binds this kind unchanged.** A request
> is not serviced on an operation whose output channel's audience is unbounded, and no
> lane services a `STRUCTURED_READ` ask there on the ground that the reply will
> otherwise be thin. A planner on such a turn is not told; what is scoped is the
> servicing, so the trigger goes on being measured on every channel.

> **Normative.** **The servicing order is: local file, then web search, then citation
> hop, then structured read, then sighted query.** ADR-0226 §6's decision is applied
> and not moved — the capped read ahead of the uncapped one, with the sighted query as
> the read that *fills what remains* — and no configuration reorders them.

> **Normative.** **One budget, and the structured read is asked for the slots that
> remain when it is reached.** ADR-0226 §6's budget of ten binds per servicing
> (ADR-0228 §7), counted after deduplication; the store call's `limit` is the number of
> slots remaining at that point. It is not a share, not a second budget, and no lane
> funds it by lowering `RETRIEVAL_LIMIT` or `EPISODIC_SUPPLEMENT_LIMIT`.

> **Normative.** **Where fewer than one slot remains when the structured read is
> reached, no store call is made at all**, the audit records that the read was not
> reached (§10), and §6's empty-read fact does **not** arise. A read the budget
> prevented is not a read that found nothing, and no implementation, carrier or audit
> field conflates them.

> **Normative.** The records it returns enter **ADR-0226 §7's fourth group**, appended
> whole with the rest of the servicing's yield in servicing order. There is no fifth
> group and no structured group (ADR-0228 §7); the three groups the planner saw keep
> their contents, their order and their positions; and §7's whole-union deduplication,
> discards-nothing-by-class clause and constructed-once rule bind on these records as
> on any others.

> **Normative.** **`truncated_kinds` records this kind where the budget shortened its
> ask**: where the read was reached with fewer slots than the whole budget and returned
> as many records as the slots it was given. A read given the whole budget was not
> truncated by it, however much more the store might have held — ADR-0226 §6's own rule
> for the sighted query, applied unchanged.

> **Normative.** **The ask is not serviced where its records would form the leading run
> of `EPISODIC` records in `memories`** — that is, where every record of the supply as it
> stands when the structured read is reached, the pre-servicing supply and everything
> this servicing has already admitted alike, is `EPISODIC`. There the servicer makes no
> store call, §10's audit records it, §6's empty-read fact does not arise, and every
> other ask of the request is serviced as usual.

> **Normative.** **The test is made before the read and never after it**, so nothing is
> discarded: ADR-0226 §7's clause that *"The servicer discards no record on the ground of
> its class"* binds unchanged and is not approached, because a read that was never made
> returns no record to discard. This is ADR-0158 §4's own construction — *"The check is
> made before the read rather than after it, because dropping the result is the decision
> either way"* — applied to this kind for its own reason.

> **Normative.** **ADR-0204 §2's withholding evaluation and ADR-0223 §2's externality
> value are computed once, over the turn's final supply**, as ADR-0226 §7 moved the
> first and ADR-0228 §7 refined both. Neither is computed twice and neither from an
> intermediate supply. Records this kind returns are inside both by construction.

**The position is reached by ADR-0226 §6's rule rather than chosen.** That section
orders the capped read ahead of the uncapped one and names the sighted query as the one
that *"fills what remains"*; ADR-0230 §7 and ADR-0231 §11 sorted their kinds by cap on
the same rule, giving one file, three results and ten via two labels. This kind has no
cap of its own — its `limit` is what is left — so the rule cannot place it by a number,
and what places it is the second half of §6's sentence: **the sighted query is the
residual read, and there can only be one.** Between two reads that take what remains,
the one the planner bounded by naming a period and a person is the more selective by
construction, and the one it bounded by nothing is the one that ADR-0226 §6 says *"can
return the whole budget on every firing"*.

**Putting the query first would reduce this kind to the case where the belief layer
returned nothing**, which is the inversion ADR-0231 §11 refused for the search and
ADR-0230 §7 for the file: it would make a kind's availability *"a function of how full
the budget happened to be rather than of what the planner asked for"*. It would also
starve the read the milestone's exit is about on exactly the turns where the store is
richest.

**The separator condition is ADR-0158 §4's, and this kind is the first whose yield is
episodes by design.** That section drops the episodic supplement *"wherever nothing
before it is non-`EPISODIC`"*, because `planning/planner.py` splits `memories` into the
conversation tail and the retrieved group by taking the **leading run** of `EPISODIC`
records, and without a separator the whole run renders under the tail's heading — *"telling
the model that an episode from three weeks ago was said moments ago … a fabricated claim
about continuity, produced silently"*. ADR-0226 §7 answered this for its fourth group with
the sentence *"a group added at the tail cannot extend that run"*, which is true only
while something non-`EPISODIC` precedes it. On the tree the guard is written over the
supplement alone — `orchestration/loop.py` tests `all(MemoryKind(record.kind) is
MemoryKind.EPISODIC for record in preceding)` before the supplement's read and nowhere
else — so the fourth group is unguarded, and a `CITATION_HOP` already reaches it: ADR-0074
§4 makes an episode *"the terminal citation: the thing other records cite"*, so a hop's
evidence is ordinarily episodes. **That hole predates this ADR and this ADR does not fix
it** — it is filed as #2147 and §14 defers the general rule with what fires it —
but this kind returns episodes on every servicing rather than occasionally, so the fail-closed
answer for the kind being admitted is to take ADR-0158 §4's rule rather than to inherit an
unguarded position and widen the exposure.

**What it costs is named and is the cost ADR-0158 §4 already accepted.** A turn whose
belief composition came back empty and whose earlier kinds admitted nothing non-`EPISODIC`
gets no structured read — the first turn of a fresh conversation against a store with no
matching beliefs is the reachable case. The alternative is the fabricated continuity above,
which ADR-0158 §4 judged *"worse than the supplement being absent"*, and that judgement is
inherited rather than re-made. Note what does **not** trigger it: a `LOCAL_FILE` fetch mints
an attested belief and a `WEB_SEARCH` mints records, so a servicing that admitted either has
its own separator by the time the structured read is reached, which is why the test is stated
over the supply as it stands at that moment rather than over the pre-servicing supply.

**A budget-starved structured read does not suppress the turn's revision, and the
arithmetic is worth stating because it looks as though it might.** ADR-0226 §6 counts the
budget of ten **after** deduplication — *"ten records that were not already in the turn's
supply"* — so a servicing that leaves the structured read no slot is by construction a
servicing that admitted ten records the supply did not hold. ADR-0228 §2(e)'s original
novelty branch is therefore satisfied on exactly those turns, and where the other six
conditions hold the turn revises anyway. What §6 withholds from such a turn is not the
revision but the **empty-read fact**: the structured read established nothing, so §7's
carrier is empty and the second plan is composed over the ten new records rather than
over an absence. §13's eighth test is written to assert that pair rather than a
suppression.

**The not-reached case is stated as a clause because it is the one an implementation
gets silently wrong.** A structured read that made no call has returned nothing in the
ordinary English sense and nothing at all in ADR-0237 §7's: the certification an empty
result carries is a statement about what the *store* holds, and a read that never
reached the store certifies nothing. §6 fires a model round trip on that certification,
so conflating the two would fire a revision on a fact nobody established.

### 6. An empty structured read is a fact, and it fires ADR-0228's revision

> **Normative.** **An *empty structured read* is a `STRUCTURED_READ` ask that was
> serviced, was reached with at least one slot of the budget remaining, whose store
> call completed, and whose store call returned **no record at all**.** A read whose
> records were all deduplicated out is **not** one: the store returned records, and a
> planner told otherwise would broaden away from records already in front of it.

> **Normative.** **ADR-0228 §2's condition (e) is satisfied where the servicing
> returned at least one record the supply did not already hold, *or* where the
> servicing performed an empty structured read.** This partially supersedes (e) in that
> one respect and in no other. Conditions (a), (b), (c), (d), (f) and (g) bind
> unchanged and all of them must still hold; §2's closing clause — that where any
> condition fails the turn proceeds with the plan it has — binds unchanged.

> **Normative.** **The broadening is the planner's and never the loop's.** No
> implementation widens a window, drops an axis, re-issues the ask, falls back to a
> different kind, or substitutes a read of its own on account of an empty result.
> ADR-0228 §2's last clause binds verbatim, and what an empty read buys is a second
> **plan**, whose ask is the planner's own composition.

> **Normative.** **The bound is ADR-0228 §3's and is not raised.** A turn makes at most
> two planner calls, so a turn takes at most one revision whatever fired it; a second
> empty structured read on the second plan fires nothing, and the turn stops. No
> implementation, setting, deployment flag or later lane makes the figure configurable
> for this fire condition or any other.

> **Normative.** **No lane cites ADR-0237 §7 as the ground for this section.** That
> section rules what an empty result means and forbids composing an assertion of
> absence from one; it says in terms that no lane may cite it as evidence that the
> broadening exists. The ground for this section is #1908's milestone 30 and the
> argument below.

**What an empty read is, is exactly what ADR-0237 §7 certifies, and that is why it is
worth a model call.** On an uncapped read, an empty result tells the caller that **no
record carries those labels in that window** — a real fact about the store, and one the
first plan did not have when it composed the ask. Everything else about the turn is
unchanged, which is precisely (e)'s worry; what is not unchanged is that the turn now
knows a specific structural question has no answer in the store. The honest responses to
that fact are all the planner's: widen the window, drop the person, ask the same
question as text, or answer from what it has and say what it could not reach. A loop
cannot choose between them, and ADR-0228 §2's last clause forbids it trying.

**(e)'s own reason is met rather than waived, and §7 is why.** (e) says a planner called
twice over one input *"is being asked the same question twice at the price of a model
round trip"*. That is true on this tree and would be true of this revision — ADR-0228 §1
gives the second call the same goal, the same context and the same three groups, and an
empty read grows the fourth group by nothing. So the amendment is not a claim that the
second call is worth making anyway: it is paired with §7, which gives the second call an
input the first did not have. **Without §7 this section would be exactly what (e)
forbids**, and a later lane that drops §7's carrier while keeping this section has
reinstated the defect (e) exists to prevent.

**The narrowing to `STRUCTURED_READ` is not squeamishness, and the other kinds are
different cases.** A `SIGHTED_QUERY` that returns nothing has established nothing about
the store — it establishes that nothing was near some text, which is a fact about a
query the planner wrote and would invite it to rewrite the query, which is reformulation
rather than broadening and is the loop ADR-0226 §12 defers. A `CITATION_HOP` that
reaches nothing has resolved no label, which the audit already counts and which no
second plan improves. A `LOCAL_FILE` refusal and a `WEB_SEARCH` decline are decided
non-yields with their own recorded reasons, and neither is an absence in the store. Only
a structured read carries a certification about the owner's own records, so only a
structured read supports the inference the broadening rests on.

**The spend is one model round trip on a turn that already spent one and asked for
more, and it is bounded twice over.** ADR-0228 §3's two-call bound caps it at one
revision per turn; (a) and (g) mean a turn only iterates where its operation declared a
planning budget and is still inside it, so `converse_spoken` — which declares none —
takes no such revision at all. And §10's audit records which turns fired this way, so
whether it is worth its cost is a number a deployment can read rather than an opinion
this ADR asserts.

### 7. The planner is told what came back empty, and that crosses the seam

> **Normative.** `Planner.plan` gains one keyword parameter, `empty_reads:
> Sequence[ReadAsk] = ()`, additive and defaulted. `Planner.plan`'s other parameters,
> its return type and every other Protocol are unchanged by this clause.

> **Normative.** **It carries the asks of this turn's already-serviced reads that were
> empty in §6's sense — each the frozen `ReadAsk` the planner itself emitted, carried
> back byte for byte — and nothing else.** Under this ADR the only kind that ever
> appears in it is `STRUCTURED_READ`; no lane adds another without the ADR that decides
> it. On a turn's **first** planner call it is always `()`, and `()` means **no read of
> this turn came back empty** — which is the semantically correct answer for the first
> call, for a turn that asked for nothing, for a servicing that failed or was declined,
> and for a `Planner` that knows nothing of this parameter.

> **Normative.** **Nothing the store said crosses on it.** No record, no count, no
> identifier, no instant of the read, no `capped` value and no value of any kind that
> the store returned or computed. The only content it carries is the planner's own
> prior composition, and the only thing it says about the read is that it returned
> nothing.

> **Normative.** **The ask is carried back unaltered and is never edited on the way.**
> No implementation widens a window, drops an axis, rewrites a label or composes a
> suggested ask to put in its place. What the second call receives is what the first
> call emitted, and the ask the second call makes is its own composition (§6).

> **Normative.** **This carrier and §10's audit record are governed separately, and
> neither is read as licence for the other.** The audit is a Tier 2 log event and
> carries no value on any axis (§10); this carrier is an in-process argument handed to
> the author of the value it carries. No lane logs an ask because this section carries
> one, and no lane withholds an ask from this parameter because §10 withholds it from
> the log.

> **Normative.** **A read the budget did not reach is not in it** (§5), a servicing
> that failed or was partial is not in it (ADR-0226 §5 leaves the supply as planning
> saw it, so nothing was established), and a read whose records were deduplicated out
> is not in it (§6).

> **Normative.** **This is a Protocol change and is flagged as a breaking change under
> golden rule 5.** Every `Planner` implementation must be widened to declare the
> parameter; what survives the widening is the **semantics** and not the signature, and
> an implementation that accepts it and ignores its value means exactly what it meant.
> ADR-0230 §3's paragraph on its own `files` is inherited whole and not re-argued.

**This parameter moves two clauses of ADR-0228 and the records are owed**, which §15
works and the header carries. §12 rules that *"the planner is not told which iteration it
is on. No lane adds an iteration index, a 'last look' instruction or any other signal to
the planner's input, and `Planner.plan`'s signature gains no parameter"*, and §1 concludes
that *"what a revision plans over that the first plan did not is the fourth group and
nothing else"*. This carrier is a signal to the planner's input and a parameter on that
signature, so both are partially superseded in one narrow scope. **What stays forbidden
is everything else those clauses forbid**: no iteration index, no "last look"
instruction, no count of the turn's calls, no budget or deadline signal, no second
context read, no second retrieval, no second supplement, and no group of the supply the
first call did not see beyond the fourth.

**A Protocol input rather than ADR-0228 §10's carrier, and the difference is which
subsystem needs the fact.** §10 carries its stop fact *"inside
`ai_assistant.orchestration`, from the component that knows it to the render site"*,
which works because the composing stage is in that package. The planner is not: it is
`planning`, and golden rule 1 forbids the two packages agreeing a private channel — the
same reasoning ADR-0226 §3 gives for deriving labels from `memories` rather than sharing
a table. A fact `planning` must read is a fact on the `Planner` seam, and ADR-0230 §3
has already taken exactly this shape for exactly this reason.

**The ask itself and not merely its kind, because ADR-0228 §1's restraint makes the two
calls' inputs otherwise identical.** §1 gives the second call the same goal, the same
`CurrentContext` and the same three groups, and an empty read grows the fourth by
nothing; `ModelBackedPlanner` builds a fresh conversation on each call and retains no
prior response. So a planner told only *that* a structured read was empty is a planner
holding exactly the inputs that produced the ask, and the likeliest composition over
those inputs is the ask it just made. A mechanism whose second call re-issues the first
call's read has spent a model round trip to learn nothing, which is the outcome
ADR-0228 §2(e) exists to prevent and which §6's supersession would otherwise have
reinstated by a different route. **Carrying the ask back is the minimum that makes
"broadening" a composition rather than a coin flip**, and the architecture lens raised
it as a `major` on round 1 against a draft that carried the kind alone.

**And it discloses nothing, which is why the smaller carrier bought no protection.** The
ask is the planner's own output; it is already durable on the frozen `ActionPlan` the
planning store keeps (ADR-0226 §4); and handing it back to its author reveals it to
nobody who did not compose it. What ADR-0226 §9's no-copy reasoning actually protects is
a **Tier 2 log event** that a deployment retains, ships and reads — *"nothing bounds what
a planner may put in a query"* — and §10 keeps every value out of that record exactly as
that section requires. Conflating the two would have made the log's discipline into a
prohibition on the planner reading its own composition, which no clause of the corpus
states.

**A sequence rather than a flag, because the shape has to survive the next kind.**
ADR-0226 §9's audit speaks in kinds and ADR-0228 §9 accounts per emission; a boolean
would have to be renamed or twinned the first time a second kind establishes an absence,
and ADR-0226 §4's *"added to and never renamed"* discipline is the corpus's own view of
that trade. The narrowing to one kind is stated as a clause so that the shape being
general is not read as a licence.

**What it costs is one more thing in the planner's prompt, and the cost is bounded by
what it may say.** The rendering is the implementing lane's, but the clauses above fix
its content: it can say what this turn already asked and that the store returned nothing
for it, and it cannot say how many records anything held, how much of the budget is
gone, or how long the turn has left — so a planner cannot learn the turn's budget or the
store's shape from it, and a reply cannot be shaped by it except through a second ask.

### 8. The reply says what the read did not reach

> **Normative.** **Three facts, and they are separate.** The **reach** fact is that a
> structured read reached only records carrying a recorded value on the axes it
> filtered. The **temporal** fact is that such a read filtered on the instant of the
> exchange rather than of the event. The **emptiness** fact is that such a read returned
> nothing. Each is given to the composing stage on its own condition below, any two or
> three are given together where their conditions hold together, and none is inferred
> from another.

> **Normative.** **The reach fact is given on every turn on which *any* structured read
> the turn performed applied a `participants`, `topics` or `about_person` axis, whether
> that read returned records or none, and whether or not a later read of the same turn
> did.** A read that returned records excluded every unlabelled record just as an empty
> one did, so the obligation does not turn on the yield; and ADR-0228 §7 keeps every
> servicing's records in one growing fourth group, so a label-filtered read's records are
> still in front of the composing stage after a second read the turn went on to make.

> **Normative.** **The temporal fact is given on every turn whose structured read
> applied a window, whether that read returned records or none.** It states that the
> read filtered on the instant the exchange was recorded and not on the instant of
> whatever the exchange was about (ADR-0237 §8), and it is what discharges ADR-0237 §8's
> second clause — *"A surface answering a time-scoped question over captured episodes
> says which instant it filtered on wherever the distinction could mislead"* — for this
> consumer. No lane reads that clause as discharged by anything else, or as owed only
> where a read came back empty.

> **Normative.** **A window-only structured read owes no reach fact**, and the ground is
> a property of the records rather than a convenience: this kind reads episodes (§4),
> every episodic record carries the `occurred_at` a window filters on, and ADR-0237 §6's
> obligation is about *records carrying no value on the axes the read filtered*. Where
> that population is empty by the record type's own shape, there is nothing the read did
> not reach for want of a value. A lane that finds an episodic record without that
> instant stops and says so rather than rendering a fact it cannot support.

> **Normative.** **The emptiness fact is given on a turn whose last structured read was
> empty in §6's sense**, and on no other turn.

> **Normative.** **On a turn given none of the three facts the composing stage receives
> nothing, and the assembled prompt is byte-identical to what it is today.**

> **Normative.** No fact carries **a window, an instant, a label, a query, a count or a
> kind name** — the temporal fact says *which instant the filter was on*, which is a
> property of the field rather than a value read off the ask. All three are carried
> **inside `ai_assistant.orchestration`**, from the component that knows them to the
> render site, as data; they add **no field to a `core` type**, no member to a Protocol,
> and none is inferred at the render site — not from the plan, not from the supply's
> length, not from the audit. This is ADR-0228 §10's rule and ADR-0227 §3's, applied to
> three more facts for their own reason.

> **Normative.** **The reach fact is what discharges ADR-0237 §6's third clause and
> ADR-0239 §6's third clause for this consumer**, and no lane reads either as discharged
> by anything else or as discharged only where a read came back empty. What the reply
> states is the reach of the read — that records carrying no value on the axes it
> filtered were not reached, and that the reach is the values that were **recorded**
> rather than the subject the owner has in mind — and it never states that the thing did
> not happen. ADR-0237 §7's no-assertion-of-absence clause binds the composed reply
> entirely.

> **Normative.** No lane renders this fact through the step account. ADR-0170 §5a's
> closed vocabularies are unchanged and gain no member.

**ADR-0237 §8's clause is the third fact's, and a draft left it undischarged.** That
section rules that `occurred_within` filters on *"the exchange's"* instant and that a
surface answering a time-scoped question *"says which instant it filtered on wherever the
distinction could mislead"*. The architecture lens found on round 5 that a **successful
window-only** read supplied none of this ADR's facts and left the prompt unchanged, so
*"what repairs happened last week"* could answer from an exchange recorded last week about
a repair from a year ago with nothing saying which instant was filtered. The composing
stage renders an episode's `occurred_at` but renders no `read_request` and names no
applied filter, so nothing else on the path could carry it.

**ADR-0237 §6 puts the reach obligation on the surface performing the read, and this ADR
is that surface.** Its clause is that such a surface *"says what the read did not reach …
and that the reach of the read is the values that were **recorded** rather than the
subject the owner has in mind"*. On the tree that reach is nearly nothing on the who and
what axes — capture writes no labels and ADR-0239's producer has not landed — so a turn
that filtered by person and found none has almost certainly not established that the
owner never spoke to that person. Saying so is the difference between an assistant that
is honest about its own index and one that reports an absence in the world.

**Two facts and not one, and an earlier draft had only the second.** That draft gave the
composing stage the emptiness fact alone and claimed ADR-0237 §6 discharged by it; both
lenses raised the same `blocker` on round 1 and both were right. §6's clause is stated
over *"A surface performing a structured read"* without qualification, and the case it
most obviously reaches is the successful one: a person-filtered read that returns the
one labelled episode has excluded every unlabelled episode about that person, and a
reply presenting it as *the* conversations with Alex is exactly the over-claim §6 exists
to prevent. The emptiness fact could not carry that, because on such a turn the read was
not empty. So the reach fact is the discharge and emptiness is a fact beside it.

**The reach fact ranges over the turn and the emptiness fact over its last read, and the
asymmetry is not an oversight.** A draft keyed both to the last read, and both lenses
raised it as a `blocker` on round 2 with the same fixture: a first read filtered by person
returns a labelled episode and fires a revision through novelty, a second read filtered by
window alone returns more, and the reply presents the first read's result while the last
read owed no reach fact. ADR-0228 §7's monotonicity is precisely what makes that wrong —
*"the fourth group only grows; and nothing is removed from the supply"* — so the earlier
read's records are in the answer and its reach is what the reply must be honest about.
Emptiness is the opposite shape: it is a fact about **the answer being composed**, so a
turn that broadened and found records has an answer and needs no note about the path it
took there, which is what §10's audit records instead. Where the turn *ended* on an empty
read that also applied a label axis, both facts hold and both are given.

### 9. The prompt offers a who or what axis only where the turn can name one

> **Normative.** **The window axis is offered on every turn on which the envelope is
> described at all.** Every episode carries an `occurred_at`, so a window is always
> answerable and there is no condition to state.

> **Normative.** **The `participants`, `topics` and `about_person` axes are described
> to the planner only where at least one record of the sequence the loop passed on that
> call carries a value on that axis.** Where none does, the prompt states neither the
> axis nor its spelling, and a turn on which no axis is described states no
> `STRUCTURED_READ` member at all.

> **Normative.** **Where an axis is offered, the values that opened it are rendered.**
> A record of the sequence the loop passed that carries a value on an offered axis has
> that value rendered to the planner, as a quoted span under ADR-0098 §2 exactly as the
> record's other spans already are, so the planner can copy the stored spelling byte for
> byte. No axis is described to the planner whose values the same call leaves unrendered.

> **Normative.** **The condition governs the invitation and never the ask.** A
> `STRUCTURED_READ` naming a label no record of the supply carried is a valid emission,
> is serviced, and is neither refused nor re-written: ADR-0226 §3 admits the **user** as
> a namer, and a person the user named in this turn is a value the planner may write
> whether or not the supply happens to show it.

**This is ADR-0230 §2's rule about the file listing reaching one axis over, and the tree
already carries its shape.** `_system_prompt(…, files_shown=…)` states the `file` member
only where a listing was passed, because a turn with no listing is one on which no file
is nameable and *"a standing invitation to name a file"* would produce emissions that can
only resolve to nothing. Three of these four axes are in that position today by ADR-0239
§8's own decision: no backlog pass is run, so labels exist only on episodes a labelling
observation has since read.

**And the gate buys more than a saved drop: it is what makes a label *copyable* — but
only if the value is on the page, which today it is not.** A `TopicLabel` is refused
rather than normalised (ADR-0213 §3, ADR-0237 §2), so a planner inventing a spelling
loses its whole ask under §3. `planning/planner.py`'s `_render_record` renders a record's
`content`, its `outcome` or disposition phrase and an episode's `occurred_at`, and
renders **neither `participants` nor `topics` nor `about_person`** — so two records
carrying different canonical topics render identically, and a gate keyed on a value the
model cannot see would offer an axis whose spelling the model would then have to guess.
Both lenses raised that on round 5 and both were right. The rendering clause above is
what makes the gate mean what §9 says it means: the axis is offered **because** a value
is in front of the planner, and the value is in front of it **as characters it can
copy** — which is ADR-0226 §3's namer rule in its strongest form, **data**, reached
without an ordinal or a table. As ADR-0239's producer fills episodes, the gate opens on
its own, on the turns where it can be answered, with no ADR and no configuration.

**What it costs is named.** A question about a person no shown record mentions gets no
person axis, so the planner asks by window or by text instead. That is a real
limitation, it falls hardest on exactly the store this milestone starts from — one whose
episodes are unlabelled — and it shrinks as the producer runs. §14 defers the
alternative, which is a store-side discovery read ADR-0237 §11 has already refused once.

### 10. The audit: two fields per servicing, and no value on any axis

> **Normative.** ADR-0226 §9 binds entire and this kind adds **no second audit, no
> second event key and no new emission point**. One `INFO`-level structured log event
> per turn, under the one fixed key, emitted once, conditioned on nothing, carrying the
> ambient correlation identifier and **no other identifier**. A `STRUCTURED_READ` ask
> appears in the servicing's `kinds` exactly as the other four do, and every existing
> count — returned, new, deduplicated, unresolved labels, truncation, the two failure
> fields — is contributed to unchanged.

> **Normative.** The record gains **one field naming the axes the ask applied**: which
> of the window, the participants axis, the topics axis, the subject axis and the query
> the ask carried. Each is a member of a **closed enumeration** and never free text.
> **It is recorded wherever a `STRUCTURED_READ` ask was emitted** — serviced, declined
> under ADR-0226 §5, or lost with a servicing that failed — because it describes the
> **ask**, which is a fact of the plan, exactly as the kind ADR-0226 §9 already records
> per ask is. It is empty where no such ask was emitted.

> **Normative.** The record gains **one field naming the structured read's outcome**, a
> member of a closed enumeration distinguishing exactly five states: **no
> `STRUCTURED_READ` was asked**; the ask was **not reached for want of a separator**,
> because every record of the supply was `EPISODIC` when the read was reached (§5); the
> ask was **not reached for want of a slot**, because fewer than one slot of the budget
> remained (§5); the read **ran and returned nothing**, which is §6's empty read; and the
> read **returned records**. Nothing else is a member, and no implementation collapses
> any two of them.

> **Normative.** **Where both of §5's conditions hold, the separator outcome is the one
> recorded.** A supply with no separator blocks the read whatever the budget holds, where
> a spent budget is a fact about one turn's other asks, so the record names the condition
> that would still have blocked it.

> **Normative.** **That field is recorded over a servicing that completed and is absent
> otherwise.** Where the servicing failed, was partial, or was declined under ADR-0226
> §5's channel scoping, the field carries **nothing** — the shape ADR-0230 §9 gave its
> own refusal field — and what happened is read from ADR-0226 §9's existing declined and
> failure fields beside every count it makes zero. No implementation records a
> completed-servicing outcome for a servicing that did not complete, and none reads an
> absent value as any of the four.

> **Normative.** **No value on any axis appears anywhere in this event.** No instant,
> no window, no person label, no topic label, no query, no record, no excerpt and no
> count of a label's characters. ADR-0226 §9's no-copy rule — *"counts and kinds, and
> copies no text"* — binds this kind without qualification, and ADR-0004 §5's rule that
> Tier 0/1 data is never logged is why: a person label is a name, chosen by whoever
> wrote it, and a Tier 2 event carrying one is a Tier 1 leak on a value this system did
> not mint. The ask stays durable on the frozen `ActionPlan` (ADR-0226 §4), and the
> record neither copies it nor points at it.

> **Normative.** **The trigger is measured for this kind exactly as ADR-0226 §8
> measures it, from the first deploy, with no new instrument**, and ADR-0228 §9's
> per-emission accounting binds unchanged. The fire rate, the novelty rate and — new
> here — the **empty rate per axis set** are readable over a population of turns from
> this one event. Every figure is computed over a population and never as a per-turn
> quantity, and no lane calls any of them precision or recall, for ADR-0226 §8's
> unchanged reason.

**Five members and not four, and the fifth is the one round 3 found missing.** A draft
enumerated four, and §5's separator condition then produced a state none of them
described: on an episode-only supply with the whole budget free, a structured ask beside a
sighted query is skipped, the query returns a belief, and the servicing **completes** — so
the absence rule below does not reach it either, and §5's own instruction to record the
skip was unsatisfiable. Both lenses raised it as a `blocker` and both were right. The two
not-reached states are separate members rather than one because they have different causes
and different fixes, which is ADR-0230 §9's own reason for keeping an unresolved label and
a refusal apart: a deployment blocked for want of a separator learns that its belief
composition is coming back empty, and one blocked for want of a slot learns that its
earlier kinds are filling the budget.

**The outcome field is stated over a completed servicing because that is the only
servicing it can be true of, and an earlier draft made it mandatory in every state.**
Both lenses raised that as a finding on round 1 and both were right: a structured ask
whose store call raises was asked, was not blocked by either condition, and produced
neither an empty result nor records, so no value is honest, and a declined ask is the same
gap one condition over. ADR-0226 §9 already scopes its counts the same way — *"Every
count above is taken over a servicing that completed"* — so the field joins that regime
rather than inventing a fifth member for a state the record already reports twice. The
axes field is not scoped that way, and the asymmetry is the point: an ask that was
emitted is an ask whichever way the servicing went, and suppressing its shape on a failed
turn would hide the emissions an operator most wants to see.

**Two fields and not one, because they answer different questions and neither is
derivable from the other.** The outcome answers *did the read work*, and it is the field
a deployment reads to see whether §6's revision is firing and whether it is firing on
budget-starved reads it should not (it cannot be, but an operator is entitled to see
that rather than trust it). The axes answer *what was tried*, and it is the field that
makes ADR-0239's producer measurable from this end: before that lane lands, §9's gate
means the who and what axes are described on few turns and used on fewer; after it, the
same field says whether the planner started using them. Neither number can be read off
the other, and neither can be read off the existing per-servicing counts, which are
stated over the whole servicing rather than per ask.

**The axes and not the values, and the line is the same one ADR-0230 §9 drew for a
path.** That section kept a file name out because *"it is chosen by whoever named the
file, it can carry anything a filename can carry"*. A person label is worse: it is a
person's name, the very class ADR-0004 §5 puts at Tier 1, and it is written by a model
reading the owner's own records. The class is safe and useful; the value is neither.

### 11. Persistence, and the versions that move

> **Normative.** **This kind writes nothing.** No record it returns is ingested,
> proposed, folded, superseded or written to any store, and nothing is written to any
> store on account of a structured read. The records are the store's own, read into one
> turn's supply, and what persists is the turn, through the capture path this decision
> leaves untouched.

> **Normative.** **`PROTOCOL_VERSION` moves by one from the value in the tree on the
> day the implementing lane lands**, and `wire/envelope.py`'s log gains an entry naming
> this ADR and this reason. The conjunction ADR-0228 §6 states is what obliges it:
> `ActionPlan` is carried to a client inside `TurnOutcome.turn.plan`, `wire/codec.py`'s
> projection dumps every field of a model, and `ReadAsk` sets
> `ConfigDict(extra="forbid", frozen=True)` — so a peer whose `ReadKind` predates
> `STRUCTURED_READ`, or whose `ReadAsk` predates `structure`, fails to decode a
> `TurnOutcome` whose plan carries either.

> **Normative.** **`PlanExport.schema_version` moves by one from the value in the tree
> on that day**, by ADR-0039 §10's mechanism as ADR-0226 §4, ADR-0228 §6, ADR-0230 §12
> and ADR-0231 §16 last applied it: the annotation is edited rather than defaulted, so
> a document of an earlier shape does not validate against this contract at all.

> **Normative.** **`EXPORT_VERSION` does not move.** No stored record gains a field,
> loses one or changes shape, and `StructuredAsk` reaches no store.

> **Normative.** No lane reads this section as authority for bumping on a defaulted
> addition alone; ADR-0213 §11's no-bump ruling stands for the case it decided. **The
> lane verifies both figures against the tree of its day rather than against this
> section**, which is why neither is written here as a numeral: ADR-0238 has already
> scheduled `PROTOCOL_VERSION` 31 → 32 for a lane that may land before or after this
> one, and a numeral in a ratified ADR that the tree has moved past is the failure
> ADR-0226 §4's own successors had to correct.

> **Normative.** **This ADR neither repairs nor inherits #1956** — the window ADR-0226
> §4 left open by shipping `ActionPlan.read_request` at `PROTOCOL_VERSION` 26. ADR-0228
> §6, ADR-0230 §12 and ADR-0231 §16 each filed and declined it for the same reason: it
> is a decision about a released version rather than about this mechanism.

### 12. What the implementing lane owes

> **Normative.** **One lane**, briefed from this ADR's merged text, and not before this
> ADR is Accepted and merged (golden rule 5, ADR-0015 §5). It lands after ADR-0237's
> implementation, whose `TimeWindow`, `occurred_within` and `MemoryStore.select` it
> calls.

**What it builds.** In `core/types.py`: `ReadKind.STRUCTURED_READ`, `StructuredAsk` with
its two refusals, `ReadAsk.structure` with its validator arm and the widened `query`
docstring, and `PlanExport.schema_version`. In `core/protocols.py`: `Planner.plan`'s
`empty_reads` parameter with a docstring carrying §7's clauses. In `planning/`: §3's
grammar in the prompt, §9's conditional guidance, the envelope arm that builds the ask
and drops it whole where it cannot be read, and the rendering of §7's fact. In
`orchestration/`: §5's servicing branch and precedence, §4's mapping onto the two store
members, §6's empty-read fact and the revision condition it satisfies, §8's carrier to
the composing stage, and §10's two audit fields. In `ai_assistant.testing`: the
canonical planner fake, widened for §7's parameter and able to construct a
`STRUCTURED_READ` ask.

> **Normative.** The lane **extends the shared `PlannerContract` conformance suite**
> (`tests/planning/planner_contract.py`) for the widened input, so that every `Planner`
> implementation is held to it — the model-backed planner and the canonical fake alike,
> through the `Test…Contract` subclasses that already run it. ADR-0226 §10's reason
> binds: *"A canonical fake updated without the suite is an unverified fake."*

> **Normative.** The lane implements §5's separator condition **before** the store call
> and asserts it through the production renderer (§13), and it takes no part of #2147 —
> the unguarded fourth group is ADR-0226 §7's to answer across all five kinds, and a lane
> that widened this condition to the other four would be deciding that ADR's question
> inside this one.

> **Normative.** The lane implements, prepares for and leaves a hook for **nothing §14
> defers** — and in particular admits no archive entry to a prompt, to the supply or to
> a citation resolution (ADR-0225 §12), adds no axis to `MemoryStore`, and adds no
> member to `ReadKind` beyond the one §1 names.

**One lane and not two, and ADR-0137 §1's test is what decides it.** Its rule is that
*"A slice is one lane only if its implementation puts substantial new machinery into at
most one subsystem"*, and ADR-0226 §10 was decomposed under it because Lane B's servicer
was genuinely new machinery in `orchestration` — *"a servicing site, a label resolver, a
budget, an audit"* — beside a new labelled rendering in `planning`. None of that is
built here. Every mechanism this decision uses exists in the tree and has since
ADR-0231: `ReadAsk`'s per-kind validator arms, the envelope reader's per-kind arms and
its drop counter, `service_read_request`'s per-kind branches and its shared union and
budget, the audit's per-kind fields, the composing-stage carrier ADR-0228 §10 built, and
`Planner.plan`'s defaulted-keyword widening ADR-0230 §3 performed. What this lane adds is
one arm in each of them, which is §1's own carve-out — *"a call site updated, an argument
threaded through"* — and there is no triad, because no Protocol is added.

**Two things a reviewer should check the lane for rather than assume.** That §6's empty
read is computed from the store call's own result and not from the union's admissions,
which is the one place a plausible implementation gets the deduplication case wrong; and
that §9's gate is computed over the sequence the loop passed on **that** call, so a
revision's guidance reflects the supply the revision is planning over.

### 13. The representative-input tests this decision owes

> **Normative.** The implementing lane owes tests for each of the following, and each is
> a test over behaviour rather than over a call count.

1. **The milestone's exit, over episodes shaped as a producer writes them.** Several
   conversations on one topic, all near in similarity; exactly one carries the asked
   person **and** falls in the asked period. The planner emits a `STRUCTURED_READ`
   conjoining **`participants`** and `window`; the fourth group carries that one episode
   and no other; and the answer carries it. Asserted over the supply and the reply, with
   the distractors crowding the candidate budget. **`participants` and not
   `about_person`**, because ADR-0239 §7 forbids the episode labeller from writing a
   subject and capture writes none, so a fixture hand-populating `about_person` would
   pass while demonstrating a capability no production path can reach (§4).
2. **The first slice, with text.** A window plus a query returns the week's
   conversations about the thing asked and excludes an identically-worded conversation
   from the month before — the arm serviced by `search` rather than `select`, asserted
   to have gone through `search` by the `score` the records carry (ADR-0237 §5, §12).
3. **Missing, and what the turn does about it.** A structured read naming a value no
   record carries returns nothing; the audit records the empty outcome; ADR-0228 §2's
   other six conditions holding, the turn makes a second planner call; the second call
   receives `empty_reads` carrying **the very ask the first plan emitted**, byte for
   byte, and nothing the store returned; and the plan it returns is the planner's own. Asserted end to end, and asserted again with (a) failing — an
   operation declaring no planning budget — where no second call is made.
4. **Ambiguous.** Two episodes match the same person and window; both reach the fourth
   group, in ADR-0237 §5's order on the query-less arm, and neither is preferred by any
   quantity.
5. **The subject axis is inert, and that is the specified behaviour.** Over a store of
   episodes written as capture and ADR-0239's labeller write them, a `STRUCTURED_READ`
   applying `about_person` returns nothing, the audit records the empty outcome, and the
   test asserts that as the decision working rather than as a defect — ADR-0237 §10 item
   7's shape, for the axis ADR-0239 §11 defers. Asserted beside a call whose supply
   carries no `about_person` at all, where §9's gate leaves the axis out of the prompt.
6. **A caption is never the reason.** An episode whose text is engineered to sit near
   unrelated questions is not returned by a structured read whose filters it fails, at
   any similarity — run on the query-less arm, and again on the `search` arm with a
   query the caption matches, which is the arm where similarity would otherwise win.
7. **Deduplication is not emptiness.** A servicing whose only ask is a structured read,
   and whose every returned record was already in the supply, fires **no** revision —
   nothing satisfies either branch of ADR-0228 §2(e) — records the outcome as having
   returned records, and puts nothing in `empty_reads`. This is the case §6 turns on and
   the one a servicer reading the union's admissions rather than the store's own result
   gets wrong.
8. **The budget is not emptiness, and it does not suppress the revision either.** A
   servicing in which the earlier kinds admit ten records the supply did not hold
   reaches the structured read with no slot and makes **no store call**; the audit
   records the not-reached outcome; `empty_reads` is **empty** on the second planner
   call; and — because ADR-0226 §6 counts the budget after deduplication, so those ten
   satisfy ADR-0228 §2(e)'s novelty branch — the turn **does** revise where the other
   six conditions hold. Asserted as that pair, and asserted beside a run of the same
   fixture with one slot left, which does make the call. What it is written against is
   an implementation that reads a not-reached read as an empty one, putting an ask into
   `empty_reads` that established nothing.
9. **The separator condition, asserted through the production renderer and in the
   audit.** On a turn whose belief composition is empty and whose supply is entirely
   `EPISODIC` when the structured read is reached, no store call is made, the audit
   records **the separator outcome by name**, and the assembled prompt carries no episode
   of another conversation under the recent-turns heading — asserted over
   `planning/planner.py`'s rendered prompt rather than over the supply alone, because the
   heading is the thing at risk. Four more arms. With one belief in the supply the read
   **is** made. On a servicing whose `LOCAL_FILE` fetch minted an attested record first
   the read is also made, because that record is the separator. On a request carrying a
   structured read **and** a sighted query over an episode-only supply with the whole
   budget free, the structured read is skipped with the separator outcome recorded, the
   query is serviced normally, and the servicing **completes** — the arm §10's fifth
   member exists for. And where the supply is episode-only **and** the budget is spent,
   the separator outcome is the one recorded, not the slot one.
10. **The servicing order and the truncation.** A request carrying a file, a search, a
    hop, a structured read and a query yields a fourth group in that order; a structured
    read reached with fewer slots than the whole budget and filling every one of them is
    recorded in `truncated_kinds`; one given the whole budget is not, however much more
    the store held.
11. **Every condition §2 puts on the models is refused by the models**, arm for arm: a
    `StructuredAsk` applying no axis; an empty sequence on each of the three sequence
    axes; a `TimeWindow` with both ends unset and one whose end is not after its start
    (ADR-0237 §2's two refusals, reached through this ask); a `STRUCTURED_READ` ask with no
    `structure`; one carrying `labels` or an `entry`; a `structure` on each of the other
    four kinds; an unknown field on `StructuredAsk`; and a mutation after construction.
12. **A malformed member costs the ask and never the plan — and an unset endpoint is
    not malformed.** An envelope whose structured member carries an unreadable instant,
    a topic label the canonical form refuses, an empty sequence, or an axis set applying
    nothing yields a plan with `read_request` `None`, one logged drop, and no
    partially-serviced read; asserted for each, and asserted that no axis of the
    offending ask was serviced. Beside them, **two acceptance arms**: a window naming
    only a `start` and a window naming only an `end` each build an ask and are serviced,
    which is ADR-0237 §2's unbounded side reaching this seam intact.
13. **The guidance is conditional, the values are visible, and the ask is not gated.**
    On a call whose `memories` carry no value on any of the three label axes, the
    assembled prompt states no participants, topics or subject member — asserted over the
    rendered prompt through the production renderer, not over a fake's reply (ADR-0226's
    ADR-0227 amendment). On a call whose supply carries one record labelled
    `participants=("alex",)` and another labelled `topics=("home maintenance",)`, both
    axes are stated **and both stored spellings appear in the prompt as quoted spans the
    planner can copy** — asserted with labels whose characters appear nowhere in either
    record's `content`, which is the arm a renderer that shows only `content` fails. And
    a `STRUCTURED_READ` naming a label nothing in the supply carried is serviced
    normally, which is the clause that keeps the gate off the ask.
14. **The reply says what it did not reach and which instant it filtered, on a
    successful read as well as an empty one.** Six arms, each asserted **through `orchestration/composing.py`'s production
    renderer** over records shaped as the production capture site writes them (ADR-0226's
    ADR-0227 amendment). Over a store holding one episode labelled with the asked person
    and a second, unlabelled episode that is in fact about that person, a person-filtered
    read returns the first and the reply **states the reach** — that records carrying no
    value on that axis were not reached — rather than presenting the one as the whole.
    A turn ending on an empty structured read states the reach **and** the emptiness. A
    turn whose structured read applied the window alone is given the **temporal** fact
    and no other — the reply says which instant the read filtered on, which is ADR-0237
    §8's clause — and a turn with no structured read at all is given none of the three,
    with the assembled prompt byte-identical to what it is today. And a further arm for
    the two-servicing case:
    a first read filtered by person returns a record and fires a revision, a second read
    filtered by window alone returns more, and the reply **still states the reach** —
    because ADR-0228 §7 keeps the first read's record in the final supply.
15. **The two carriers carry different things, and the audit carries no value.** A turn
    whose structured ask named a distinctive person label, a distinctive topic and a
    distinctive query emits an audit event in which **none of those three, and neither
    of the window's instants, appears anywhere** — the event carries the axes as
    enumeration members and the outcome, and nothing else — while `empty_reads` on the
    second planner call carries that ask **whole**, equal to the one the first plan
    emitted. The composing stage's two facts carry neither. Asserted over the emitted
    event's own fields, over the parameter's own value and over the assembled second
    prompt, not over the redaction net.
16. **The channel scoping holds.** A turn on `converse_spoken` whose planner emits a
    `STRUCTURED_READ` performs no store call for it, reaches the composing stage with
    the three groups ADR-0203 §1 narrowed, records the emission as declined, and makes
    no second planner call — the last because ADR-0228 §2(c) fails and, independently,
    because that operation declares no planning budget.
17. **A failed servicing degrades and establishes nothing.** A store that raises during
    a structured read leaves the turn composing from the supply planning saw, records
    the degradation with ADR-0226 §9's pair of failure fields, fires no revision, and
    puts nothing in `empty_reads` — the arm that keeps ADR-0228 §2(d) meaning what it
    means.
18. **The bound is not raised.** A turn whose first structured read is empty and whose
    second plan's structured read is also empty makes exactly two planner calls, and the
    composing stage is told both that the turn stopped while still asking (ADR-0228 §10)
    and, under §8, what the last read did not reach.

### 14. Deferred, by name, each with what fires it

- **A negation or exclusion on any axis** — "not about Alex", "outside this window".
  ADR-0237 §11 defers it on the store side, and this ADR adds no ask for one. **Fires**
  as that section says, with a consumer that needs one and can say which answer it wants
  for the unlabelled.
- **An event-time axis** — a filter on when something *happened* rather than when it was
  said (ADR-0237 §8, §11). **Fires** with the first producer that records such an
  instant, which owes the field before it owes the filter or the ask.
- **A second window, or a disjunction of windows, on one ask.** §2 admits one.
  **Fires** with a consumer that needs two disjoint periods in one read and can say why
  two turns will not do.
- **A kind or band axis on the ask** (§4). **Fires** with an ADR that decides how a
  store's partitioning vocabulary is rendered to a planner at all — which is a namer
  question this ADR does not open.
- **Admitting a second kind's ask to `empty_reads`** (§7). **Fires** with an ADR that
  shows what that kind's empty result certifies about the store and what a planner would
  do differently on it. **Not** fired by a lane finding the parameter's type general
  enough to allow it.
- **Hybrid or lexical search** (ADR-0006 §5, ADR-0226 §12). A different retrieval
  mechanism rather than a filter over stored values, and a later milestone-30 lane's.
  **Fires** with the ADR that decides it.
- **Discovery of the values a store holds on an axis** — "which people do you have
  records about" — which would let §9's guidance be offered unconditionally. ADR-0237
  §11 refuses it today on ADR-0101 §10's ground. **Fires** as that section says, with
  the first surface that must offer discovery without handing over the whole export;
  **not** fired by a lane finding §9's gate inconvenient.
- **Repairing a planner-composed label to canonical form.** §3 drops the ask instead,
  and ADR-0213 §9's refusal to normalise is why. **Fires** with §10's audit showing that
  refused labels rather than absent ones dominate this kind's drops.
- **A structured read on a channel of unbounded audience** (§5, ADR-0226 §5, §12).
  Deferred for ADR-0203 §2's backfill reason, unchanged by this kind. **Not** fired by a
  lane finding spoken replies thin.
- **A second structured ask per emission**, or several asks of one kind. ADR-0226 §12
  and ADR-0228 §14 already defer decomposition and this ADR takes no part of it.
- **Raising ADR-0228 §3's bound for an empty-read revision.** §6 refuses it. **Fires**
  only with an ADR that moves the bound itself, on evidence of the kind ADR-0228 §3 read
  off the replay.
- **A separator rule for the whole of ADR-0226 §7's fourth group** (#2147). §5 takes
  ADR-0158 §4's rule for this kind alone; the same hole is open for a `CITATION_HOP`
  whose evidence is episodes, and closing it across five kinds is ADR-0226's question —
  plausibly with the explicit tail boundary `_split_conversation_tail`'s own docstring
  says *"would be a `Planner` contract change taking its own ADR"* rather than with a
  drop. **Fires** with that ADR. **Not** fired by a lane widening §5's condition to the
  other four kinds on this ADR's authority.
- **Anything §10's record would need a store to answer.** ADR-0226 §12 defers a durable,
  queryable surface for the audit; this kind adds two fields to the same log event and
  inherits that deferral whole.

### 15. Scope, and what this records against earlier ADRs

**This ADR partially supersedes one ratified ADR in one scope and amends four in one
respect each, and no others** — ADR-0228 partially, and ADR-0226, ADR-0228, ADR-0230 and
ADR-0231 by amendment — and every other clause it cites binds as written. That is a
classification of this change and is therefore stated as prose rather than marked
(ADR-0089 §1). The header carries each record; what follows is the working under
ADR-0070 §1's and ADR-0082 §1's test — *would a reader holding only the earlier ADR now
act differently, or read one of its clauses more widely than it now holds?* — and the
clauses a reader would most expect to have moved and which did not.

**ADR-0228 §2(e) is partially superseded, and this is the heaviest instrument in this
ADR.** (e) rules that a revision fires only where the servicing *"returned **at least
one record the supply did not already hold**"*. §6 fires one where a structured read
returned none. A reader holding only ADR-0228 refuses that call, which is not a stale
phrase or a broken cross-reference but a **change to what was decided** — ADR-0070 §1's
line — so the amendment form is unavailable and §3's partial supersession is the
sanctioned tool. **The scope is (e) and nothing else in §2**: the other six conditions,
the all-of-them rule, the closing clause, and (e)'s companion prohibition on the loop
widening or substituting a read are untouched, and the last of those is what §6 relies
on. **§2's own reasoning is honoured rather than set aside** — (e) exists so that a
planner is not asked the same question twice, and §7 is what makes the second question
different. **§3 is untouched entirely**, and it is the bound on this revision as on any
other; §4's budget declaration and its clock rule are untouched and gate this fire
condition exactly as they gate the others; §7's monotonicity and per-servicing budget are
untouched and are what make a second structured read's deduplication well-defined; §9's
per-emission accounting is untouched and covers this turn's second servicing as it covers
any; §10's carrier is untouched and §8 above carries three facts beside it rather than
changing it; §11's rulings are untouched and are treated in the header record. §1's and
§12's two further scopes are worked below.

**ADR-0228 §12's no-signal clause and §1's nothing-else clause are partially superseded
too, in one scope between them, and the architecture lens is why they are recorded.** §12
rules that *"No lane adds an iteration index, a 'last look' instruction **or any other
signal to the planner's input**, and `Planner.plan`'s signature gains no parameter"*, and
§1 that *"what a revision plans over that the first plan did not is the fourth group and
nothing else"*. §7's carrier is a signal to the planner's input, arrives on that
signature, and is something the second call has that the first did not — so a reader
holding only ADR-0228 refuses to build it and ADR-0070 §1's test is met on both. **The
scope is §7's carrier and nothing else.** Every other signal those clauses name stays
forbidden — the iteration index, the "last look" instruction, a count of the turn's
calls, and any signal about the budget or the deadline — and §1's enumeration of what is
**not** re-run binds verbatim: one context assembly, one conversation-tail read, one
retrieval, one episodic supplement, and no group of the supply beyond the fourth.

**Two things a reader will want said about that record.** §12's evident subject is
*"What the implementing lane owes"*, so the clause reads first as an instruction to
ADR-0228's own lane — and on that reading ADR-0230 §3 added `files: Sequence[ShownFile] =
()` to the same signature and recorded nothing against it. This ADR does not rest on that
reading: the sentence says *"No lane"*, a lane reading it would refuse this parameter,
and ADR-0082 §1 puts the test on what a reader would do rather than on what an author
meant. Recording it is the cheaper error. And the record is owed *because of the
carrier*, not because of §6: the supersession of (e) admits a revision, and this one
admits the input that makes the revision worth making — which is why §6 and §7 are argued
as one and are superseded as one.

**ADR-0228 §11's two-kinds statement is amended and its rulings are obeyed.** *"Both
kinds a revision may emit are the two that ADR admits"* stopped being true when ADR-0230
admitted a third, and §1 above makes it an undercount again; ADR-0082 §1's test is met
and the record is owed. What §11 **rules** is untouched and is load-bearing: *"This ADR
adds no kind to ADR-0226 §2's enumeration"* stays a true statement about ADR-0228; its
prohibition on a lane *"reading this ADR as preparing for"* an outward kind is honoured,
because this kind is not outward and this ADR cites ADR-0228 toward nothing but the
condition §6 moves; and its inward-only argument is **strengthened**, since a
`STRUCTURED_READ` becomes a `MemoryStore` call over the owner's own store and no byte of
a model-composed ask leaves the process.

**ADR-0226 §2's membership sentence and §6's precedence sentence are amended, and
neither ruling is replaced.** The working is ADR-0230 §16's and is not re-derived: §1 of
ADR-0226 tells its own reader in terms how a later member arrives, and §4 says the
vocabulary *"is added to and never renamed"*, so a reader holding only ADR-0226 is not
led to refuse the addition — only to believe the enumeration has two members, which is
what the note corrects. §6's decision is not replaced but applied: the capped read ahead
of the uncapped one is the rule §5 above reaches its position by, and the sighted query
*filling what remains* is the half of the sentence that decides which of two uncapped
reads goes last.

**ADR-0226 §9 is *not* amended, and showing that is the point of this paragraph.** §9
ends by providing for exactly this: *"These are the fields milestone 2 raises rather than
replaces … it does not rename them, drop them, or start a second audit beside this
one."* §10 above adds two fields for a new kind, renames nothing, drops nothing, keeps
every field's meaning and starts no second audit — the same treatment ADR-0230 §9 and
ADR-0231 §13 took for one field each. No sentence of §9 becomes false or over-wide, so
under ADR-0082 §1 this is a stacked addition, recorded here and nowhere else.

**ADR-0226 §12's structured-read deferral is discharged, and a discharge is not a
record.** §12 defers *"Structured read keys and hybrid search"* — *"A kind carrying a
time window, participants, topics or the person a record is about, mapped onto
`MemoryStore.search` filters"* — and fires it *"by `track:memory` ratifying the store
read each maps to; a kind here is inert until then"*. ADR-0237 is that ratification and
it has merged, so the condition is met on its own terms. §12's second half, hybrid and
lexical ranking, is **not** taken and is deferred again by name in §14. Firing a
deferral is the deferral working rather than a clause becoming false.

**ADR-0230 §7's and ADR-0231 §11's servicing-order sentences are amended, and both
decisions are applied.** Each orders by cap on ADR-0226 §6's rule and each says so; §5
above sorts one more kind by the same rule and shows its working for a kind that has no
cap of its own. Every other clause of both sections binds unchanged, and §5 relies on
several of them: one servicing site, the one budget counted after deduplication, the
fourth group with no fifth, the never-larger-than-the-budget clause, and the single
evaluation over the turn's final supply.

**ADR-0237 is used at its stated scope and nothing of it moves.** §1's axes, §2's shapes
and argument law, §3's matching rules, §4's two members and their three-way test, §5's
order and cleared `score`, §6's empty-means-unrecorded rule and its disclosure
obligation, §7's certification and its no-assertion-of-absence clause and §8's
exchange-instant caveat are all applied as written; this ADR adds no axis, no member, no
matching rule and no order, and it narrows none. **§11's `TimeWindow`-reuse deferral is
fired rather than contradicted.** That entry reads *"It has one meaning at one site under
this ADR. **Fires** with a lane that needs an instant window on another read and argues
that the half-open, both-ends-refused shape is right there too"*, and the argument is
made in §2 above: the window on the ask **is** the value passed to `occurred_within`,
carried across the seam without translation, so a second window type would be two
answers to which end is inclusive on one path. **§7's prohibition binds this ADR and is
obeyed** — no clause here cites §7 as evidence that the broadening exists, and §6 says so
in terms.

**ADR-0239 is used at its stated scope and nothing of it moves either.** §4's canonical
form and its resolves-to-nothing clause govern every participant label this ask carries;
§6's empty-means-no-label rule is why §8 exists and §9 is conditional; §11's deferral of
*"A structured read over these labels"* names *"the `track:memory` lane that decides the
`MemoryStore` surface"* as what fires it, which ADR-0237 was, and this ADR takes the
planner-facing half of the consumer that deferral anticipated. No clause of ADR-0239
becomes false: it decides what a label **is** and who may write one, and this ADR writes
none.

**ADR-0208 §1's one-site clause needs no further supersession, and this is the clause a
reader should check.** ADR-0226 §13 superseded it once, for the sighted query, *"in the
single respect that §2's sighted query is a second such site"*, and §1's own scoping
sentence is that *"One site is not one call"*. A `STRUCTURED_READ` is serviced at that
same second site — `service_read_request`, which ADR-0230 §7 and ADR-0231 §11 each
confirmed adds no third — so it opens no site ADR-0226 did not already open. On the
query-less arm it is not a relevance selection at all: ADR-0237 §4 and §5 rule that
`select` ranks nothing and returns a cleared `score`, which puts it closer to §1's
**keyed load** than to a retrieval. Either way no sentence of ADR-0208 §1 becomes false
that ADR-0226 §13 had not already moved, and §1's tool clauses are honoured by §5 rather
than approached.

**ADR-0158 §4 is applied and not moved, and ADR-0226 §7 is not reached by the
application.** §4's separator clause is stated over *"The supplement"*, so it says nothing
about a fourth group and nothing of it becomes false; §5 above takes the same rule for a
different read, which is a stacked addition recorded here and nowhere else. ADR-0226 §7's
discards-nothing-by-class clause is the one a reader should check, and it is untouched
because §5's test runs **before** the store call: the servicer returns no record on such a
turn, so it discards none, applies no placement test and performs no subtraction. §4's own
construction is the precedent for taking the decision at that point rather than after.
ADR-0074 §5's order and ADR-0158 §4's append-never-interleave rule bind unchanged.

**Seven more clauses a reader would expect to have moved, and did not.**

- **ADR-0113 §3 and §4.** §4's clause that *"Within the result of one call the order is
  relevance alone"* binds on every `search` call this kind makes, filters included —
  ADR-0237 §1 states that in terms and this ADR adds nothing to it. §3's argument law is
  restated by ADR-0237 §2 and reaches `MemoryStore` unchanged; §2 above refuses an empty
  sequence on the **ask**, which is a different object and changes nothing about what an
  empty sequence means to the store.
- **ADR-0128 §1 and §2.** The pre-cut binding and the four `capped` clauses bind on both
  members through ADR-0237 §1 and §7; §6 above rests on the first clause's certification
  and weakens none of them.
- **ADR-0203 §§1 and 2, ADR-0204 §§2 and 4, and ADR-0210 §1.** ADR-0226 §5's channel
  scoping binds this kind (§5), so this envelope still adds no supply member to a turn
  that has a subtraction; there is nothing to backfill and nothing to re-filter, and the
  evaluation ADR-0226 §7 moved and ADR-0228 §7 refined is taken once over the final
  supply with these records inside it.
- **ADR-0170 §2 and §5a.** The composing stage gains no collaborator, performs no second
  assembly and no second retrieval; §8's carrier is a bare fact of the same class as
  ADR-0228 §10's, and the step account's closed vocabularies gain no member.
- **ADR-0100 §3 and ADR-0101 §2.** There is no way to ask for the owner's own records by
  the subject axis and this ADR adds none: ADR-0237 §6 rules that a sentinel meaning
  "unstated" would spell an owner the corpus says has no label, and §9's guidance may not
  invite one. A caller wanting the owner's records omits the axis, which excludes
  nothing.
- **ADR-0213 §3, §4 and §7.** A topic label is refused rather than normalised and its
  only relation is equality of the stored characters; no filter here derives a topic at
  read time, which is §4's write-time rule holding on this read as ADR-0237 §1 already
  states; and §7's empty-means-unrecorded rule is what §8 discloses.
- **ADR-0225 §4 and §12, ADR-0154 §7, ADR-0017 §1.** No transcript-archive entry reaches
  a prompt, a supply or a citation resolution; no egress is authorised, no seam
  designated, no `DestinationProtocol` member added, and this ADR is cited toward none of
  those. This kind reads the owner's own store, which is the rung below even ADR-0230's
  disk.

**Everything else this ADR cites is used as ratified**: ADR-0004 §5 and §7; ADR-0006 §5;
ADR-0014 §2; ADR-0015 §§1 and 5; ADR-0024; ADR-0027; ADR-0039 §10; ADR-0070 §§1, 3 and 4
and ADR-0082 §§1 and 2 for the supersession and amendment forms; ADR-0072 §5; ADR-0080
§8; ADR-0088 and ADR-0089 for the citation forms and the marks; ADR-0093 §1; ADR-0098
§§1–2; ADR-0137 §1; ADR-0158 §§4 and 5; ADR-0187 §4; ADR-0211 §3; ADR-0223 §§2 and 6;
ADR-0227 §§3 and 4.

### 16. Marking, review and ratification

> **Normative.** This ADR is marked under ADR-0089: the block quotes above are the whole
> of what it obliges, and unmarked text is read to determine what a marked clause means
> and never supplies an obligation.

What binds is **seventy-three marked clauses**: §1's three, §2's six, §3's six, §4's
four, §5's ten, §6's five, §7's seven, §8's nine, §9's four, §10's seven, §11's six,
§12's four, §13's one, and this section's one. §14's list, §15's classification and every argument in
this document are deliberately unmarked: they are deferral, attestation and argument,
which ADR-0089 §1 classifies as non-normative however load-bearing.

**Required reviews: adversarial *and* architecture.** This is a contract-surface change
in `CONTRIBUTING.md`'s sense — it decides a `ReadKind` member, a `core/types.py` model, a
`ReadAsk` field and validator arm, and a `Planner.plan` parameter, and it moves a clause
of ADR-0228 — so it owes both lenses under ADR-0015 §1. It is drafted, reviewed and
revised as `Proposed`, its status flipped only once both required reviews return clean on
one tree, and the route is `CONTRIBUTING.md` → "Finishing an ADR PR". Nothing implements
against it until it has merged (ADR-0015 §5, golden rule 5).

**It records itself as ratified on its second flip**, which is that section's step 3 taken
as written. Both lenses returned clean on one tree and the status was flipped; a base move
then landed ADR-0237's implementation, the round that move owed produced findings, and the
ADR was **returned to `Proposed`** and re-entered at step 1 rather than being amended
under an `Accepted` header. That is ADR-0070 §1's third permitted in-place header edit,
the route ADR-0127 §3 names and ADR-0127 and ADR-0133 each took on their own PRs, and it
is available only pre-merge: an `Accepted` flip sitting on a branch has landed nowhere and
binds no reader.

## Consequences

- **The assistant can ask by structure.** A question about a period, a person or a topic
  reaches the records that carry those values rather than the records nearest some text,
  and the milestone's exit — several conversations on one topic, one matching the asked
  person and period — becomes constructible from the planner's side. The injection
  hazard #1874 names is sidestepped structurally, as it is on the store side: a caption
  an adversary wrote is content the read returns, never the reason it was selected.
- **An absence becomes a reason to look again rather than a reason to conclude.** This
  is the milestone's own mechanism and the one clause of ADR-0228 this ADR had to move.
  A turn that asked a structural question and found nothing gets one more plan, and a
  turn that ends on an empty read says what it could not reach.
- **One clause moves and four sentences are corrected.** ADR-0228 §2(e) admits one more
  way to fire; ADR-0226's membership and precedence sentences, ADR-0230 §7's order and
  ADR-0231 §11's order each gain a member or a position. Nothing else in the envelope
  corpus moves, and the servicing site, the budget, the fourth group, the audit and the
  channel scoping are all inherited whole.
- **`Planner.plan` widens for the second time**, and every implementation must declare
  the new keyword. What crosses on it is the planner's own prior ask and the fact that
  it returned nothing — the minimum that makes a second composition different from the
  first — and that is the honest cost of a planner that learns something from its own
  read. It is the same cost ADR-0230 §3 paid for the listing.
- **Three of the four axes reach nothing on the day this merges**, exactly as ADR-0237
  §6 records for the store side: capture writes no labels and ADR-0239's producer is its
  own lane. §9's conditional guidance is what keeps that from becoming a stream of
  emissions that cannot resolve, and it opens on its own as the producer runs.
- **The prompt grows by up to ten more records on the turns that fire**, drawn from the
  same budget of ten rather than a second one, and a turn that revises may pay a second
  model call it would not have paid before. §10's audit is where a deployment watches
  both.
- **What would trigger revisiting this.** §10's audit showing that empty-read revisions
  fire often and change nothing; an event-time instant on a record, which makes §3's
  inherited caveat and ADR-0237 §5's order both look different; or a measured store in
  which §9's gate suppresses the asks the milestone was built for.

## Alternatives considered

**Put the window on `SIGHTED_QUERY` and amend ADR-0226 §2.** One fewer member, one fewer
servicing branch, and the sighted query is already the relevance read. Refused in §1 on
two grounds that point the same way: ADR-0226 §1 forbids widening an admitted kind's
meaning *"to carry a read the ADR that admitted it did not describe"*, so the change
would be a supersession of §1's own prohibition rather than an entry under §1's licence;
and on the tree the sighted query's kind selection is `BELIEF_KINDS`, so a window on it
would filter beliefs — none of which carries an `occurred_at` — and reach nothing at all.
The kind that needed the window was one the enumeration did not have.

**Give the ask no query, and map it onto `select` alone.** Cleaner: one kind, one store
member, no overlap with `SIGHTED_QUERY`'s argument. Refused in §4 because it makes
ADR-0237 §4's own first slice unreachable from the planner — *"a time-window filter over
episodes **plus** the existing text query"* is a filtered relevance read, it is the
example #1908's milestone leads with, and a caller with text who is forced onto a
query-less read gets ADR-0237 §5's write-stamp order over a period instead of the nearest
records within it.

**Give the ask a kind axis, so the planner can ask the same question of beliefs.**
Refused in §4: `kinds` and `bands` are the store's partitioning vocabulary, rendering
them to a planner is a namer question this ADR does not open, and beliefs are already
read three ways on the turn path.

**Let the loop broaden after an empty read** — drop the narrowest axis and read again,
with no second planner call. It is cheaper by a model round trip and needs no clause of
ADR-0228 to move. Refused in §6 because ADR-0228 §2's last clause forbids it in terms —
no implementation *"widens a request … or substitutes a read of its own for one the
planner did not ask for"* — and because the choice between widening the window, dropping
the person and asking as text is a judgement about the user's question that no rule in
the loop can make. Buying a clause's timing with a prohibition's substance is the trade
ADR-0226 §13 already refused twice.

**Leave ADR-0228 §2(e) alone and disclose the empty read to the composing stage only** —
§8 without §6. It is the smaller change, it needs no supersession and no Protocol
parameter, and it delivers the honest half of the milestone: the reply says what it could
not reach. It was refused because #1908's milestone 30 states the broadening as the
mechanism rather than as an aspiration, and because the case it leaves unserved is the
one the milestone is about — a period named too narrowly, or a person named as the
records do not spell them, is a question this system can answer on the second ask and
cannot answer on the first. §8 is kept as well rather than instead: the two answer
different halves, and a turn that broadens and still finds nothing needs both.

**Carry the empty-read fact to the planner inside `orchestration`, as ADR-0228 §10 does
for the stop fact.** Refused in §7: the planner is in another subsystem, so the two
packages would have to agree a channel that appears in no contract — the import golden
rule 1 forbids and the private-protocol failure ADR-0226 §3 argues at length. ADR-0230 §3
already took the sanctioned route for exactly this shape.

**Record the ask's values in the audit**, so an operator can see which windows and which
people the planner asks about. Refused in §10 on ADR-0230 §9's ground, sharpened: a
person label is a name, ADR-0004 §5 puts a name at Tier 1, and ADR-0226 §9's no-copy
clause and a clause retaining the label would contradict each other on the same bytes.
The ask stays durable on the frozen `ActionPlan`, and a reader who wants it reads it
there.

**Offer the who and what axes unconditionally.** Simpler prompt, no gate, no
supply-dependent guidance. Refused in §9: on today's episodes the three axes reach
nothing, ADR-0239 §8 declines a backlog pass, and a `TopicLabel` the planner spells
freshly is refused rather than normalised — so an unconditional invitation produces asks
that are dropped or empty, and it does so on exactly the deployments that have not yet
run the producer. The gate also buys the property the corpus values most in a namer: a
label the planner copies from a record it was shown is **data** naming the read, which is
ADR-0226 §3's strongest form.
