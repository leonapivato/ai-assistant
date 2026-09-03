# 230. The planner names a file it was shown, and the loop fetches it into the turn's supply

- Status: Proposed
- Date: 2026-09-03
- **Amends** [ADR-0226](0226-the-planner-names-one-more-read-beside-its-plan-and-the-loop-services-it-into-the-supply.md)
  — **§2's membership sentence and §6's cross-kind precedence sentence, in one
  respect each.** §2 reads *"The enumeration's two members are `SIGHTED_QUERY` and
  `CITATION_HOP`"*, and §6 reads *"**The citation hop is serviced first, and the
  sighted query fills what remains.**"* §1 below adds a third member and §7 below
  puts it ahead of the hop, so a reader holding only ADR-0226 would read both
  sentences more widely than they now hold and ADR-0082 §1's test is met on each.
  **Neither ruling is replaced.** §1's additive-entry clause is the licence this ADR
  is taken under and is quoted in §1 below; §2's statement of what each named kind
  *is*, its at-most-one-ask-of-each-kind rule and its closure against un-ADR'd
  additions bind entire; and §6's decision — the capped read ahead of the uncapped
  one — is not merely intact but is the reason §7 gives this kind the position it
  gives it. §3's namer rule, no-identifier rule and ordinal scheme, §5's channel
  scoping and degradation posture, §6's budget of ten and second-budget rule, §7's
  fourth group, whole-union deduplication, discards-nothing-by-class clause and
  constructed-once rule, §8's trigger and §9's audit all bind as ratified and are
  load-bearing here. ADR-0226's `Status` line carries the leading
  `Partially superseded by` token, so this record lives in its appended dated note
  and not on that line (ADR-0082 §2).
- **Amends** [ADR-0228](0228-a-serviced-read-may-revise-the-plan-once-and-the-turn-stops-looking-at-a-bound-or-a-deadline.md)
  — **§11's two-kinds statement, and that alone.** §11 reads *"Both kinds a revision
  may emit are the two that ADR admits, both terminate in the owner's own
  `MemoryStore`"*, which stops being true of the tree once §1 below admits a third.
  **§11's rulings are untouched and are obeyed:** *"This ADR adds **no kind** to
  ADR-0226 §2's enumeration"* stays a true statement about ADR-0228, and its
  prohibition — *"no lane admits an outward kind here or reads this ADR as preparing
  for one"* — is honoured, because this decision is taken on #1844, #1908 and
  ADR-0226 §12 and cites ADR-0228 toward none of it. §11's steered-loop argument is
  **extended rather than moved**, and §8 below is the extension: the loop moves up
  exactly one rung, from the owner's own store to the owner's own disk, which is the
  rung #1844 names as having no channel out. §11's class clause on a planner-composed
  query, its no-filtering clause and its no-recomputation clause bind unchanged, and
  §7's monotonicity is what §8 rests on.
- **Partially supersedes**
  [ADR-0092](0092-an-attested-belief-names-its-source-and-a-user-assertion-retires-it.md) — **§3's
  local-substitute clause, in exactly one scope: a source that is read live, at the
  instant of its report, and that holds no claim of its own made earlier.** §3 rules
  that `reported_at` *"is not when we read the file, not when we wrote the record, and
  not a value we may substitute for"*, and that *"A source that supplies no report
  time cannot be attested — there is no fallback"*. §5 below rules that where our
  clock and the source's report are **the same event**, the fetch instant is the
  source's own report time rather than a substitute for one. **§3's mtime prohibition
  is untouched and is load-bearing here** — §6 below is why the fetch never reads a
  file's mtime into an attestation — and so are §3's two further rulings (a
  `reported_at` earlier than `last_updated` is normal; one in our future is not
  refused) and its whole account of `reported_by`, which §5 applies as written.
  ADR-0092's `Status` line takes the leading token in this change, and ADR-0121's
  existing qualifier moves off it into the note already carrying that record
  (ADR-0082 §2's last clause).

## Context

### Where this comes from

`track:planning` (#1908) earns the planner sight rung by rung. Milestone 27 built the
envelope — the planner names one read beside its plan and the loop services it into
the supply (ADR-0226) — and milestone 28 made the plan revisable over what that read
returned (ADR-0228). Both were ruled PASSED on 2026-09-03. **Milestone 29 is the
first rung on which the planner names a source outside the store**, and the roadmap
orders it: local files first, then the web.

The order is not a convenience. #1844 names *"one genuinely new risk"* in the whole
programme and it is not resource-shaped:

> iteration one reads attacker-controlled content; iteration two decides what to
> fetch based on it… That is an exfiltration channel needing no write capability at
> all.

and its sequencing consequence is the sentence this milestone is built on:

> A steered loop that can only read the owner's own disk has no channel out.

ADR-0226 §12 defers *"The outward fetch"* on exactly that ground and fires it at this
milestone. This ADR discharges that deferral for the local-disk half; the web half is
#1996's Lane B and is deferred by name in §15.

**The numbering, since three ratified documents say otherwise.** ADR-0226 §12 and
#1844 call this *"milestone 3"*. #1908's milestones were renumbered globally by the
owner on 2026-09-03 with the mapping *"1→27, 2→28, 3→29, 4→30"*. This ADR uses **29**
throughout. ADR-0070 §1 forbids rewriting ratified text, so ADR-0226 §12's own words
stand and this paragraph is where a reader learns; no record is owed against ADR-0226
for it, because the sentence was true when written and §12's deferral is discharged
rather than contradicted.

### The exit, and why it is a task capability rather than a benchmark point

#1908's exit for this milestone has two clauses, and the first is this ADR's:

> "summarise the PDF I saved yesterday" answers from disk; a search result is cited
> as a record and that conversation's egress asks first thereafter.

#1908's charter caution is written in on purpose — *"do not justify the loop by
memory-benchmark numbers … **Exits are task-shaped, not retrieval-shaped**"* — and
this ADR takes it literally. **No retrieval figure is claimed for this decision and
none is available**: the replay on #1844 priced the *inward* envelope and measured
nothing about a document on disk, because no corpus in this project contains one. The
justification is capability: a question about a file the owner saved is one this
system cannot answer at all today, at any score, and the shape of the answer — a
provenance-stamped record in the supply, subject to the same disclosure filter, the
same external mark, the same policy gate and the same citations — is the shape #1908's
first invariant requires of every rung.

### What the tree settles, verified against `origin/main` at `d3291a9e`

- The envelope is a **closed enumeration of kinds** with two members. ADR-0226 §1:
  *"A read request is a closed enumeration of **kinds**. This ADR admits exactly two,
  named in §2. No implementation, setting or later lane adds a third without the ADR
  that decides it"* — and, in the same section, the clause this decision is taken
  under: *"A later kind is an **additive entry to this enumeration**, not a second
  seam. An ADR admitting one adds a member and states that kind's namer, its
  servicing, its share of §6's budget and its audit fields; it does not introduce a
  second request object, a second servicing site, a second budget or a second
  audit."* `core/types.py` carries `ReadKind`, `ReadAsk` and `ReadRequest` exactly as
  §4 fixes them.
- The servicer is one function. `orchestration/reads.py`'s `service_read_request`,
  with `resolve_label`, `ServicedRead`, `TurnReadAudit` and `emit_read_audit` beside
  it, and the loop's servicing site in `orchestration/loop.py`. There is no second
  site and this ADR adds none.
- **A `Reader` cannot be this.** ADR-0093 §10 gives `Reader.read` no arguments *by
  decision*: *"It takes no arguments because §1 gives the sensor its own source and §5
  makes the bound the sensor's own configuration: a caller able to widen the read is a
  caller able to defeat the bound"* (read under ADR-0095 §1's substitution). A turn-time
  read of an address named on the turn is a different contract, so it is a
  `core/protocols.py` addition and this is its ADR (golden rule 5).
- **It is not a tool step, in two independent rulings.** ADR-0170 §5a renders the step
  account from closed vocabularies because *"a tool's result is a JSON payload with no
  per-span provenance"*; ADR-0208 §1 rules that *"A component on the turn path that
  wants records the supply does not hold does not obtain them by invoking a tool"*.
  ADR-0226 §5 satisfies both by not being a tool, and this ADR does not approach either.
- **The externality machinery is built and is the control.** ADR-0098 §1 defines
  external content as *"any span of text that this system did not author and did not
  receive from its own user"*, with membership decided *"by **recorded origin**, never
  by inspecting the text"*. ADR-0106 §1–§2 give the predicate
  `rests_on_recorded_external_content`. ADR-0223 §1 stamps a captured episode from
  `SelectionOrigin.over(turn.memories).planned_with_external_content`, and §6 states the
  product sentence: *"every subsequent turn of that conversation that reaches the egress
  seam is a confirmation rather than an allow"*.
- **An attested belief must name a report time.** `Provenance`'s
  `_attested_iff_attestation` validator is keyed on `band_of(source) is ATTESTED`, and
  ADR-0092 §3 rules the field is the source's clock with no fallback. §5 below is where
  this decision meets that rule.

### Claims in the framing that do not survive contact with the tree, and one correction

- **There is no PDF reader, no fetcher and no file-type reader anywhere.**
  `src/ai_assistant/readers/` holds `calendar.py` and `email.py` and nothing else. No
  dependency in this project extracts text from a PDF. §6 and §13 name that as a
  library adoption the implementing lane makes under ADR-0024's pinning discipline,
  and this ADR names no library.
- **#1908's persistence line is a lean and not a ruling.** It reads *"Decides whether
  fetched content persists (lean: retained by address in the source archive, #1907)"*.
  #1907 is a design note, not dispatched and not numbered, and its store does not
  exist. §10 decides persistence without building it.
- **#1908's milestone-29 text says the fetched record carries the `ATTESTED` band.**
  It does, and §5 rules so — but the route is not the one that text implies, because
  `Attestation.reported_at` admits no local substitute and a plain text file declares
  no instant. §5 takes the narrow supersession that makes the band reachable and says
  what it costs, rather than reading the lean as having settled it.
- **`ActionPlan` does cross `wire/`.** ADR-0226 §4 and §10 say it crosses neither
  `wire/` nor `service/`; ADR-0228 §6 found otherwise — *"`ActionPlan` is carried to a
  client inside `TurnOutcome.turn.plan`"* — and moved `PROTOCOL_VERSION` 26 → 27. §12
  below inherits that finding rather than ADR-0226's statement of it.

### What this ADR is not allowed to settle

It decides nothing at the egress seam. ADR-0154 §7 rules that beyond its own three
decisions that ADR *"registers no tool, adds no `core` name, changes no Protocol, adds
no `DestinationProtocol` member, designates no second seam, and authorises no
dependency"*, and §4's standing-authorisation floor stands untouched here. It admits
no transcript-archive entry anywhere: ADR-0225 §4's never-list and §12's gate — *"Admitting
an archive entry to a model prompt, to a turn's supply, or to a citation resolution
takes an ADR that supersedes the relevant clause of §4"* — are neither superseded nor
approached. And it decides nothing about the web, which is a second kind with a
different namer question and its own egress argument (§15).

## Decision

We will admit **one more kind** to ADR-0226 §1's enumeration — a **local file the
planner names by pointing at a listing the loop showed it** — and contract a
**`Fetcher`** seam that reads one such file, once, within a bound its caller cannot
widen, and mints one attested record carrying the file's own text and its own
provenance. The record enters the turn's supply as part of ADR-0226 §7's fourth
group, is never written to any store, and carries the external mark, which is what
makes a conversation that read a file ask before its next outward call.

### 1. The kind: `LOCAL_FILE`, an additive third member and not a second seam

> **Normative.** `ReadKind` gains one member, `LOCAL_FILE`, valued `local_file`. It
> is an **additive entry** under ADR-0226 §1: it adds no second request object, no
> second servicing site, no second budget and no second audit, and every clause
> ADR-0226 and ADR-0228 state over a read request binds on it except where a section
> below names the exception and shows its working.

> **Normative.** A `LOCAL_FILE` ask carries **one entry label** and nothing else.
> `ReadAsk` gains one field, `entry: EncodableText | None`, defaulting to `None`,
> carried for a `LOCAL_FILE` ask and for no other. Its validator gains one arm: a
> `LOCAL_FILE` ask carries a non-blank `entry`, no `query` and no `labels`; a
> `SIGHTED_QUERY` and a `CITATION_HOP` ask carry no `entry`. Each condition is
> enforced by the model rather than by its callers, exactly as ADR-0226 §4 requires
> of the two arms already there.

> **Normative.** ADR-0226 §2's at-most-one-ask-of-each-kind rule and `ReadRequest`'s
> validator bind unchanged: one emission carries at most one `LOCAL_FILE` ask, and a
> request naming two is not an emission this corpus admits. A turn that revises may
> emit a second `LOCAL_FILE` ask on its second plan, which is ADR-0228 §3 applied and
> not widened.

> **Normative.** **A `LOCAL_FILE` ask fetches one file.** No implementation reads two
> files for one ask, reads a directory as a file, follows a reference out of a fetched
> file, or fetches a file it was not asked for. There is no depth, no recursion and no
> traversal of any kind, and no later lane adds one without the ADR that decides it.

**A separate field rather than reusing `labels`, and the reason is that they name
different sequences.** A `CITATION_HOP` label is an ordinal into the `memories`
sequence the loop passed; a `LOCAL_FILE` label is an ordinal into the *listing* it
passed (§2). Two namespaces in one field would make `ReadAsk` a place where the
reader has to consult `kind` to know which sequence a string indexes, and would make
the model's output ambiguous at exactly the seam ADR-0226 §3 exists to keep
unambiguous. A field per argument keeps every arm of the validator uniform: each kind
carries exactly its own argument and refuses the others.

**One file and not several, which is the whole of this kind's bound.** ADR-0226 §6
gives the hop *"at most two labels"* and notes that the capped read is what makes the
budget's precedence honest. This kind is capped harder: one label, one file, one
record (§5), one slot of the ten. A kind that could name three files would be a
decomposition decision — how a question is split across sources — which ADR-0226 §12
defers by name and #1908 places at a later milestone.

### 2. The namer: an ordinal into the listing the loop showed, and what "shown" means for a filesystem

> **Normative.** ADR-0226 §3's namer rule binds this kind as written: **the namer may
> be data, or the user, or the model pointing outward — never the model pointing
> inward.** A `LOCAL_FILE` ask is the model pointing outward at an address it was
> shown, and at nothing else.

> **Normative.** **"Shown", for a filesystem, is an entry of the listing the loop
> passed the planner on that call, and is nothing else.** Not a path in the user's
> utterance, not a string in a record's `content`, not a name the model composed, and
> not a file that happens to sit under the configured root. A turn on which the loop
> passed no listing is a turn on which no file is nameable.

> **Normative.** **The label is an ordinal into that listing.** The label of the entry
> at 1-based index *n* of the sequence the loop passed is the ASCII string `F` followed
> by *n* in decimal with no padding. That is the whole of the scheme. `F` and not `M`
> because the two index different sequences, and a single namespace over two sequences
> would be a label whose meaning depends on which kind quoted it.

> **Normative.** **Both sides derive the label from the listing and neither consults
> the other.** The planner renders each entry's label from the sequence it was given;
> the loop resolves a label by parsing *n* and indexing **the very sequence it passed
> on this call**. No mapping, table, path or handle crosses between `planning` and
> `orchestration` other than that sequence and the `ActionPlan` that already crosses.

> **Normative.** **A label outside the shown set resolves to nothing.** A string that
> does not match the form, an *n* below 1 or beyond the sequence's length, and a label
> whose entry the fetcher can no longer resolve all resolve to nothing. Each is
> discarded silently — not an error, not a park, not a degradation of the turn — and
> recorded in §9's audit as an unresolved label, exactly as ADR-0226 §3 rules for a
> record label.

> **Normative.** **No string a model produced is ever interpreted as a filesystem
> address, in any form.** The loop passes the fetcher an entry the fetcher itself
> minted, carrying the capability §4 requires; it never constructs a path, never joins a
> model-supplied fragment to a root, never assembles a `SourceListingEntry` of its own,
> and never hands a model-supplied string to any filesystem call. A conforming
> implementation in which a model's output reaches a path is not this decision
> however carefully it is bounded.

> **Normative.** **The resolvable set is bounded at two places, and this ADR says which
> property each one buys rather than claiming one enforcer buys both.** At the **seam**,
> §4's minted token and handle make it impossible to fetch a file that was in **no**
> listing this fetcher produced — a file the cap or the type allow-list left out, one of
> an unsupported type, one that never existed — against every caller, this loop included.
> At the **loop**, §3's obligations make the listing in hand **this turn's**: one listing
> read per turn, labels resolved only against the sequence passed on that call, and no
> listing or entry retained past the turn that read it.

> **Normative.** **The seam is not asked to know what a turn is, and no lane reads §4 as
> though it did.** A `Fetcher` verifies that it produced the listing and that the listing
> is inside §4's expiry; it cannot distinguish a delayed call from that turn from a lane
> that kept the listing and called in a later one. That distinction is §3's, held where
> the turn is known, and it is exactly the division ADR-0226 §3 already makes for a
> record label — no `MemoryStore` enforces that an `M` label is this turn's either; the
> loop resolves against *"the very sequence it passed on this call"*. **The residual is
> stated rather than papered over**: a lane that breached §3 and retained a listing could,
> within the expiry, fetch a file the current turn did not show. That is a lane defect and
> not a route a model can reach, because no model ever sees a token or a handle; closing
> it at the seam would mean threading a turn identity onto this contract, which is a wider
> surface than this decision needs and is named in §15.

**This is ADR-0226 §3's scheme applied one sequence over, and it is taken for §3's own
reason rather than by analogy.** That section's argument is that the label discipline
*"forecloses"* a model steering what it is shown, because *"the resolvable set is
exactly what the loop chose to render, so the widest possible abuse of the mechanism
is asking for something already on screen"*. On a filesystem that property is worth
strictly more than it is over a store, because the alternative is a path — and a
model-supplied path bounded by a containment check is a whole class of defect this
decision can simply not have. `..` normalisation, a symlink pointing out of the root, a
case-insensitive filesystem, a Unicode normalisation the check and the kernel disagree
about: each of those is a way for a containment check to be *nearly* right, which is
the same failure mode ADR-0092 §3 names for a substituted report time. An ordinal
cannot be nearly right. It is an index into a sequence, and an index outside the range
resolves to nothing.

**It is also the honest answer to ADR-0093 §10's argument rather than an evasion of
it.** That section refuses to let a caller widen a read because *"a caller able to
widen the read is a caller able to defeat the bound"*. Here the caller names an index.
The root, the listing's size, the type allow-list and the size bounds are the fetcher's
own configuration (§4, §6), and there is no argument through which any of them can be
moved. The bound is not merely un-widenable; the address space is not reachable from
model output at all.

**What it costs is that the planner can only name what the listing showed**, and the
listing is bounded (§4). A file the owner saved that fell outside the listing is not
nameable on that turn. That is a real limitation, it is the direct price of the
property above, and §6's ordering — most recently modified first — is chosen so that
the case the exit names, a file saved yesterday, is the case the bound serves best.

### 3. The listing crosses the seam on `Planner.plan`, and it is read once per turn

> **Normative.** `Planner.plan` gains one keyword parameter, `files: Sequence[SourceListingEntry] = ()`,
> additive and defaulted. `Planner.plan`'s other parameters, its return type and every
> other Protocol are unchanged by this clause. `()` means **no file is nameable on this
> turn** and is the semantically correct answer for a deployment with no fetcher wired
> and for a `Planner` that knows nothing of this kind; no implementation reads it as an
> error, a degradation, or an instruction to fetch a default.

> **Normative.** The loop reads the listing **once per turn**, from the `Fetcher` it
> holds, **before the first planner call**, and passes the **same sequence** to both
> planner calls of a turn that revises. ADR-0228 §1's restraint binds: no lane adds a
> second listing read, and no lane re-reads it between a turn's two calls.

> **Normative.** A label's meaning is therefore **stable across a turn's two planner
> calls**, which is where this scheme differs from ADR-0226 §3's and the difference is
> deliberate. ADR-0228 §8 rules that an `M` label *"may name different records on a
> turn's two calls"* because the supply grows; the listing does not grow, so `F3` names
> the same entry on both calls of one turn. No label survives the **turn** that rendered
> it, none is persisted as a reference, and no implementation resolves a label against a
> listing from an earlier turn.

> **Normative.** A deployment with no `Fetcher` wired passes `()`, renders no listing
> into any prompt, and can service no `LOCAL_FILE` ask. A `Fetcher` whose listing comes
> back empty is the same case for the turn, and the emptiness **carries no further
> meaning**: it does not distinguish unconfigured, an empty root, an unreadable root or
> a failed read, and no consumer may infer which it was. That is `CurrentContext`'s own
> ruling for a `None` facet, applied here for its reason — an operator fact wearing
> situational clothes is *"a grant conversation conducted by a field nobody designed"* —
> and the fetcher's own log line is what serves the operator.

> **Normative.** The listing is **external content** under ADR-0098 §1 — this system
> did not author a file's name and did not receive it from its user as an utterance — so
> every entry rendered into a prompt is escaped for that target under ADR-0098 §2,
> exactly as any other external span is. No lane renders a listing entry as a bare fact
> of the system's own.

**On the Protocol and not on `CurrentContext`, and the alternative was close enough to
be worth recording.** A file listing looks like a situational facet: `CurrentContext`
says its remaining facets *"are added as optional fields when their source subsystems
exist"*, `context/`'s own `ContextSource` already holds a `Reader` over a local file,
and a facet is stamped with its source and its instants, which a listing wants. Three
things decide it the other way. A `ContextFacet` is produced by a `ContextSource`
holding a `Reader` and a `SourceGrants`, so the listing would arrive through machinery
built for a different contract and would drag `GrantScope` into a decision §11 argues
it does not need. The label scheme requires the loop to resolve against *"the very
sequence it passed on this call"* (§2), and a value the context assembler built and the
loop merely forwards is one indirection further from that guarantee than ADR-0226 §3's
construction. And the listing's producer is the same object as the fetcher (§4): one
`Fetcher` answers both members, so one root, one type allow-list and one bound govern
what is shown and what is fetched, where a facet route would put the listing's bound in
`context/` and the fetch's in `orchestration` with nothing keeping them equal.

**Additive and defaulted, so the widening breaks nothing.** This is a `Protocol` change
and it is flagged as a breaking change under golden rule 5 — the documented meaning of
what `Planner.plan` receives changes and `orchestration` calls it — and this ADR does
not argue itself out of that classification, exactly as ADR-0226 §10 declined to for the
return. What the flag does not assert is a compatibility break: an existing `Planner`
that ignores the parameter conforms and means what it meant. §13 binds the implementing
lane to extend the shared `PlannerContract` for the widened input, for the reason
ADR-0226 §10 gives — *"A canonical fake updated without the suite is an unverified
fake"*.

**One filesystem read per turn is the cost, and it is stated rather than hidden.** The
listing is read before the planner has said whether it wants a file, so a deployment
with a root configured pays one bounded directory read on every turn against a trigger
that fired on 13.6% of turns in the replay. It is paid because there is no other order:
the planner cannot name an entry it was not shown, and a listing cannot be the *yield*
of a serviced read, because ADR-0226 §1 rules that what a serviced request returns is
*"`MemoryRecord`s carrying their own `Provenance`, and never a payload, a rendering, a
summary or free text of any kind"* — and a listing is none of those things. The read is
local, bounded by entry count, and involves no model call; the honest comparison is
against the turn's own model round trips, which it is orders of magnitude below.

### 4. The fetch contract: `Fetcher`, and the bound the caller cannot widen

> **Normative.** `core/protocols.py` gains **one** Protocol, `Fetcher`,
> `@runtime_checkable` as the seams around it are, owing three members:
>
> - a **`name` property**, `str` — the stable Tier 2 identity of the source instance,
>   in `Reader.name`'s own form and under its own obligation (ADR-0093 §7, ADR-0189,
>   ADR-0190). It is what §5 puts in an attestation's `reported_by`.
> - an **`async listing` method** taking **no arguments** and returning one
>   `SourceListing`. It takes no arguments for ADR-0093 §10's reason, unchanged: the
>   root, the ordering, the entry cap and the type allow-list are the fetcher's own
>   configuration, and a caller able to widen the listing is a caller able to defeat
>   every bound behind it.
> - an **`async fetch` method** taking the `SourceListing` an entry came from and that
>   `SourceListingEntry`, and returning one `FetchOutcome`. It takes the listing because
>   the listing is the authority the entry's membership is verified against, and a
>   contract in which the caller supplies only the entry has nothing to verify it in.

> **Normative.** `core/types.py` gains three frozen models and one `StrEnum`, all
> refusing mutation and unknown fields:
>
> - `SourceListingEntry` — `name: NonBlankEncodableText`, `size_bytes: int` (≥ 0),
>   `modified_at: UtcInstant`, and `handle: EncodableText`. It carries **no path, no
>   root and no directory component**: `name` is what a person calls the file and is
>   what a prompt renders, and `handle` is the opaque capability of the clause below,
>   which is never rendered anywhere.
> - `SourceListing` — `source: EncodableText` equal to the producing fetcher's `name`,
>   `read_at: UtcInstant` (the instant **this system** listed, captured once at
>   acquisition), `entries: tuple[SourceListingEntry, ...]`, possibly empty, and
>   `token: EncodableText`, the opaque authority of the clauses below, which like a
>   handle is rendered nowhere.
> - `FetchOutcome` — exactly one of `record: MemoryRecord | None` and
>   `refusal: FetchRefusal | None`, enforced by the model. Neither both nor neither.
> - `FetchRefusal` — a **closed** enumeration of why a fetch produced no record, whose
>   members are fixed in §6.

> **Normative.** **Listing membership is a capability the fetcher mints and verifies,
> and never a claim its caller makes.** A `Fetcher` mints a fresh, unguessable `token`
> for each listing it produces and a fresh, unguessable `handle` for each entry of it,
> both derived from state **private to the fetcher**. `fetch` refuses unless this fetcher
> minted that `token`, that `handle` belongs to **that** listing, and the entry is among
> that listing's `entries` — and the refusal is `NOT_FOUND`, **deliberately the same
> class an absent file yields**, so that it discloses nothing about whether a guessed
> name exists under the root. A `SourceListingEntry` or a `SourceListing` a caller
> assembled — for a file the cap left out, for one of an unsupported type, or for one
> that never existed — is refused whatever its other fields say, and a `Fetcher` that
> decides membership by re-reading its caller's `name` does not conform.

> **Normative.** **A listing's authority expires after `fetch_listing_ttl` of elapsed
> time** — a `Settings` field with a named default of **five minutes**, refused at load
> rather than at the first fetch.

> **Normative.** **The expiry is decided against a monotonic deadline the fetcher bound
> into the token, and never against a wall clock.** The fetcher reads a monotonic source
> when it mints a listing, binds `deadline = now_monotonic + fetch_listing_ttl` into the
> authenticated token, and at `fetch` compares a fresh reading of that same source against
> it. `SourceListing.read_at` stays what it is — the tz-aware instant this system listed,
> which §3 renders and ADR-0026 §1 governs — and **is not the expiry's input**: it is a
> wall-clock value, and a wall clock that steps backwards would leave a listing minted at
> 12:00 inside a five-minute window an hour of real time later. The signed token stops a
> caller extending the value; only a clock that cannot be set stops the producer's own
> clock from regressing under it. The monotonic reading is the fetcher's, is never
> rendered, and does not outlive the process — which is the same restart behaviour the
> clause below already states for the token itself.

> **Normative.** **No listing is invalidated by the production of another.** A `Fetcher`
> is composed once and may serve turns that overlap, so a mechanism that evicted by count
> would refuse a live turn's own listing for a reason no operator could see and would make
> one label's usable target depend on unrelated turns. Nothing about verification requires
> the fetcher to retain a listing, and no conforming implementation makes a listing's
> validity a function of how many others have been produced since.

> **Normative.** **A token and a handle are never persisted, never cross a process
> boundary, and never outlive the fetcher that minted them.** A restarted hub mints new
> ones and refuses every value from before the restart, which is the correct behaviour
> and not a limitation to repair: a turn does not survive a restart either.

> **Normative.** **No token and no handle is rendered to any model, written to any log,
> put in any audit record, or carried on any record a fetch mints.** §3's listing
> rendering carries `name`, `size_bytes` and `modified_at` and the `F` label the loop
> derives, and carries neither. Either in a prompt would be a capability offered to a
> model, which is the whole of what §2 exists to prevent.

> **Normative.** **The membership check does not replace the root bound; both bind.**
> `fetch` refuses any entry that does not resolve to a regular file directly under its
> configured root — a name carrying a directory separator or a parent reference, a
> symbolic link at the final component, a directory, a device — and a `Fetcher` that
> reads outside its configured root for any entry, however that entry was constructed,
> does not conform. The handle establishes *that this fetcher showed it*; the root check
> establishes *that it is still what may be read*, and a bug in either is not covered by
> the other.

> **Normative.** **Resolution and acquisition are one operation, and no bound is decided
> against a path the fetch then re-opens.** A conforming `Fetcher` opens the entry's file
> from its configured root **without following a symbolic link at the final component**,
> and then decides every remaining question — that it is a regular file, that it lies
> under the root, and that it is within `fetch_max_file_bytes` — **against the object it
> has open**, never against a path or a `stat` taken before the open. The root itself is
> resolved once, when the fetcher is constructed, and is not re-resolved per fetch.

> **Normative.** **The read is itself bounded, so a file that grows after its size was
> observed is refused rather than read.** An implementation reads at most
> `fetch_max_file_bytes` plus one byte from the open object and refuses as `TOO_LARGE`
> where the object supplies more; it does not decide the bound from a size it observed
> earlier and then read to end of file. `fetch_max_content_bytes` is decided the same way,
> against the extracted text as it is produced.

> **Normative.** **A file replaced between the listing and the fetch yields exactly one
> object's answer, and never a mixture.** No implementation reports a size, a
> modification instant, a type or a name from one object and content from another. Where
> the open cannot be performed under the conditions above — the final component became a
> symbolic link, a directory or a device — the outcome is `NOT_A_FILE`; where it fails for
> any other reason, `UNREADABLE`; and neither is ever a best-effort read.

> **Normative.** **Every bound is re-applied at `fetch` and none is carried from the
> listing.** A file that grew past the size bound between the listing and the fetch is
> refused as over-size; one that was deleted is refused as absent. No implementation reads
> a bound, a type or a size off the entry it was handed.

> **Normative.** **Neither member raises for a source reason.** An absent file, an
> unreadable one, an over-size one, an unsupported type and a failed extraction are
> `FetchRefusal` members and never exceptions; an unreadable root is an empty listing.
> This ADR adds **no error class** to `core/errors.py`, because there is no failure a
> caller would handle differently from a refusal it must already handle.

> **Normative.** **Cancellation passes through both members unchanged.** A `listing()`
> or a `fetch()` cancelled from outside while suspended re-raises `CancelledError` and
> converts it into neither an empty listing nor a refusal. This is ADR-0093 §10's clause
> one contract over, stated because it is the one place a conforming-looking
> implementation could satisfy every other clause here and still absorb a cancellation.

> **Normative.** A `Fetcher` holds **no store, no writer, no policy, no engine and no
> model**. It reads its own configured source and returns what it read. It may not write
> to any store, may not read a belief, and may not decide the fate of anything it mints.
> This is ADR-0093 §1's rule for its own reason: a producer that held a store would make
> the scope of what a fetch can do a property of an implementation rather than of a
> ratified seam.

**The handle is what makes §2's property a property of the seam rather than of its
caller, and an earlier draft of this section did not have one.** That draft required
`fetch` to refuse *"anything the fetcher did not itself list"* and gave the fetcher no
way to tell: a `SourceListingEntry` is a public frozen model carrying display metadata,
so a caller could assemble one for any direct child of the root — including one the
listing's cap left out, which is precisely the file a planner was **not** shown. The
containment §2 claims is that *the resolvable set is exactly what the loop showed*, and
an obligation the type cannot enforce is a convention, not that property. A minted,
verified capability makes it structural, which is the same move `Provenance`'s
attested-iff-attestation validator made for a producer that could otherwise forget
(ADR-0092 §1) and that ADR-0226 §3 made by deriving a label from a position rather than
from an agreement.

**Three properties are required of the mechanism and its spelling is the lane's**, in
ADR-0093 §10's own form: a token and a handle must be **unforgeable without state private
to the fetcher**; a handle must be **bound to the listing that minted it**; and
verification must **not depend on the fetcher retaining anything**, so that no listing's
validity is a function of how many others have been produced since. A keyed digest — a
per-listing random identifier signed with a key generated when the fetcher is constructed
and never leaving it, and each handle signed over that identifier and the entry's name —
satisfies all three, needs no table and no eviction, and carries the monotonic deadline
inside the same signed payload rather than in a cache. This ADR fixes the properties and names no
construction as the required one.

**An earlier draft of this section bounded the authority by a window of eight listings,
and the two review lenses found it wrong from opposite sides on the same round.** Read as
a bound it was too **narrow**: nine turns whose listings interleave with their planner
calls would evict the first turn's listing before its own plan came back, so a label's
usable target depended on unrelated turns and §3's within-turn stability was untrue. Read
as a claim it was too **wide**: an entry eight listings old was accepted, so §2's "exactly
what this turn showed" was not a property the seam held. Both are properties of counting,
and the union of the two findings is what says the count was the defect rather than the
figure. An expiry on the listing's own signed instant removes the first entirely and
bounds the second, and §2's split of the claim across the seam and the loop is what makes
the remainder honest instead of overstated.

**Race-safe acquisition is stated because a check-then-open implementation would satisfy
every other clause of this section and still be wrong.** A file may pass the root check
and the size check and then be replaced by a symbolic link pointing out of the root, or
grow past the bound, before it is opened — and the outcome would be a read outside the
configured root or an unbounded read, both of which §§4 and 6 exist to refuse. Deciding
every question against the object already open removes the window rather than narrowing
it, and bounding the read itself removes the second one; both are conditions on the
implementation because there is no way to state them as conditions on a value. §14 owes
a test for each transition rather than for the static cases alone, which is the
difference between asserting the property and asserting the easy half of it.

**Named `Fetcher` for its product role**, as every Protocol here is (`Planner`,
`Observer`, `Reader`). The role is fetching one named thing, now, for this turn, which
is what separates it from `Reader` — a whole-source read on the fetcher's own cadence,
bound by its own configuration, taking no address at all. Reusing `Reader` was never
available: ADR-0093 §10 gives `read()` no arguments *by decision*, and an argument is
exactly what this contract needs.

**Three members and not two, because the listing is the address space.** A contract
offering only `fetch` would need its caller to hold the addresses, which is the design
§2 refuses; a contract offering only `listing` cannot deliver a file. The two are one
seam because the same configuration must govern both — an entry that is shown but not
fetchable, or fetchable but never shown, is a bug in a place no test would look.

### 5. What a fetch mints, and the externality decision

> **Normative.** A successful fetch mints **exactly one `MemoryRecord`**, of kind
> `SEMANTIC`, whose `content` is the file's text as extracted, **verbatim**. No model is
> on that path: nothing summarises, abridges, rewrites, annotates or classifies the text
> between the file and the record. Extraction from a container format is a **decoding**
> and never a rendering — a deterministic, library-performed transformation of bytes into
> the text they encode — and ADR-0226 §1's refusal of *"a payload, a rendering, a summary
> or free text of any kind"* is satisfied because what enters the supply is a
> provenance-carrying record and not the payload.

> **Normative.** The record's `Provenance` carries `source=MemorySource.EXTERNAL`, which
> `band_of` places in the `ATTESTED` band, so `rests_on_recorded_external_content` is
> `True` for it. `confidence` is **0.9**, the figure the corpus's other attested
> producers carry and for their reason: a connected source may legitimately report a
> fact it is certain of (ADR-0038 §2a), and a third party's claim is not the user's own
> word. `evidence` is empty, `derived_from_external` is `False` and asserts nothing in
> this band (ADR-0106 §1), `topics` is empty, `about_person` is `None`, `placement` is
> the default that narrows nothing (ADR-0217 §6), and `validity` is fully open.

> **Normative.** The `Attestation` carries `reported_by` equal to the fetcher's `name` —
> the **source instance**, "the owner's documents folder" and not a vendor, and never a
> path — and `reported_at` equal to the **instant the file was read**. `Provenance.last_updated`
> and `last_confirmed_at` carry that same instant. `Attestation.extent` is `None`: this
> producer states no position for the file in the source's own world (ADR-0117 §2).

> **Normative.** **`reported_at` is the fetch instant because our clock and the source's
> report are one event, and this is the scope in which ADR-0092 §3's local-substitute
> clause is superseded.** A fetcher asks a source that holds no earlier claim of its own
> and the source answers in the same instant, so "when the source said so" and "when we
> read it" are not two facts of which one stands in for the other. The scope is exactly
> that: a source read **live**, at the instant of its report, holding no claim made
> earlier. **It reaches nothing else.** A source that declares its own report time uses
> that time; a synced or cached copy of a remote source is outside this scope entirely
> and ADR-0092 §3 binds it as written.

> **Normative.** **The file's mtime is never read into an attestation.** ADR-0092 §3's
> prohibition on it is untouched and is the rule here: an mtime *"is a property of the
> last local write and is changed by a copy, a restore or a `touch` while the source's
> claim stays where it was"*. A listing entry's `modified_at` is a fact about the
> filesystem, offered so a person or a planner can tell one file from another, and no
> implementation moves it into a `Provenance` or an `Attestation`.

> **Normative.** The record's `id` is **minted by the fetcher and opaque to the source**
> (ADR-0092 §6). It is never rendered to a model, never accepted from one, and — since
> §10 stores nothing — never installed. `MAX_EVIDENCE_CITATIONS` and every other
> `MemoryWriter`-seam bound are not engaged, because no fetched record reaches that seam.

**The external mark is argued from the mark's definition and not from convenience,
because the convenient answer is the wrong one.** It is tempting to say that a file on
the owner's own disk is the owner's own material and carries no taint. ADR-0098 §1
settles it the other way and does so on origin rather than on location: external content
is *"any span of text that this system did not author and did not receive from its own
user"*, and membership is decided *"by **recorded origin**, never by inspecting the
text"*. A PDF the owner downloaded was authored by someone else and reaches this system
as a file rather than as an utterance; the owner **saving** it is not the owner
**saying** it. ADR-0098 §1's own carve-out is deliberately narrow — *"The user's own
utterance is not [external], however it was composed — a user who pastes an email into a
turn is exercising judgement"* — and a file is precisely the case where that judgement
was not exercised on the text.

**The tree already agrees, at the same rung.** `CalendarReader` reads a local `.ics`
file the owner put on the owner's own disk and mints `MemorySource.EXTERNAL` records in
the `ATTESTED` band. A local-file fetch that marked itself clean would be claiming, for
a document the owner never wrote, a standing this system refuses to a calendar entry.

**And the mark is the milestone's control rather than its cost.** ADR-0223 §1 stamps the
captured episode from the disjunction over `turn.memories`, so a turn that fetched a
file captures a stamped episode; §6 then rules that the egress allow applies *"exactly as
it applies for any other reason"* and states the product sentence — *"every subsequent
turn of that conversation that reaches the egress seam is a confirmation rather than an
allow"*. §8 below is why that is the containment this rung needs, and §6 of ADR-0223
already accepted the cost in terms: in a deployment with a reader enabled it
*"approaches 'every outward call in a conversation asks'"*. This decision enlarges the
population of such deployments to those with a fetch root configured, and accepts it on
ADR-0223's own reasoning rather than re-arguing it.

**The supersession is narrow and it is the smallest instrument that reaches the case.**
Three alternatives were available and each is worse. **Requiring a format-declared
instant** — a PDF's `/ModDate` — and refusing every file whose format declares none is
faithful to ADR-0092 §3's *"The capability is bounded by what sources can actually say"*,
and it excludes plain text and Markdown, which is most of what a person's notes are; the
mechanism would be defined by what its formats happen to carry rather than by what it is
for. **Using the mtime** is refused above for §3's own reason and is the *nearly right*
value that section exists to forbid. **Placing the record in the `DERIVED` band** with
`derived_from_external=True` needs no supersession and fires the same mark, and it says
something false: `DERIVED` means *"We worked it out from evidence; provisional … and
re-derivable while the observations behind it are retained"*, and a verbatim document
excerpt is neither worked out nor re-derivable. Superseding one clause in one stated
scope is a smaller falsehood than any of those — it is, in fact, none.

### 6. What is readable: a configured root, three formats on the first rung, and refusing rather than truncating

> **Normative.** A `Fetcher` reads from **one configured root** and from nothing else.
> The root is a `Settings` field with a named default of **unset**, so the mechanism is
> **off until a deployment configures it** — no root, no listing, no ask, no fetch.

> **Normative.** The listing is the root's **direct children only** — no recursion, no
> subdirectory traversal, no following of symbolic links out of the root — ordered
> **most recently modified first**, capped at `fetch_listing_max_entries` with a named
> default of **40**, and restricted to the readable types below.

> **Normative.** **The first rung reads plain text, Markdown and PDF, and nothing else.**
> Any other file is not listed and, if named, is refused as an unsupported type. A later
> format is admitted by the ADR that decides it, states what its extraction is, and says
> whether that extraction declares a report time (§5).

> **Normative.** Two size bounds, both `Settings` fields with named defaults, both refused
> at load rather than at the first fetch (ADR-0093 §5): `fetch_max_file_bytes`, the file's
> size on disk, default **4 MiB**, which bounds the read and the extraction's cost; and
> `fetch_max_content_bytes`, the extracted text, default **32 KiB**, which bounds what
> reaches the prompt.

> **Normative.** **A bound is enforced by refusing, never by truncating.** A file over
> either bound yields a refusal and no record. No implementation returns a prefix, a
> first page, a first *n* bytes, an abridgement or a "first part of" record, and none
> records a truncation flag in place of refusing.

> **Normative.** `FetchRefusal`'s members are `NOT_FOUND`, `NOT_A_FILE`, `UNREADABLE`,
> `TOO_LARGE`, `UNSUPPORTED_TYPE` and `EXTRACTION_FAILED`. The enumeration is closed and
> no lane adds a seventh without the ADR that decides it. A refusal names a **class** and
> carries no path, no name, no excerpt and no message from an underlying library.

> **Normative.** **A refusal is a resolved outcome and never a failure.** It adds no
> record, fails no turn, degrades no servicing and discards no other kind's records: the
> turn composes over the supply it has, and §9's audit records the refusal's class. This
> is ADR-0226 §3's disposition for a label that resolves to nothing — *"not an error, not
> a park, not a degradation of the turn"* — applied to the outcome one step later.

**Refusing rather than truncating is ADR-0093 §5's ruling taken for its own reason, and
it is the clause a lane will be tempted to soften.** That section rules that *"A read
whose source exceeds any of its bounds raises under §8 rather than returning the part
that fitted"*, because *"a truncated reading is indistinguishable from a source that
simply has fewer entries, and a consumer cannot tell which it holds"*. Here the consumer
is a model asked to summarise a document, and the failure is worse than indistinguishable:
a model handed the first 32 KiB of a 90-page report will answer *about the report*, in the
assistant's own voice, having seen a third of it. That is ADR-0072 §6's laundering — *"a
wrong record laundered into a fact by flat prose, restated back to the user with the
assistant's authority, and never questioned because it did not arrive looking
questionable"* — reached by a route no clause was watching. A refusal the user is told
about is a worse answer and an honest one.

**The listing's cap is a truncation and it is not that case, which is worth showing
rather than asserting.** ADR-0093 §5's objection is that a consumer *cannot tell*. A
listing states in terms that it is the most recently modified entries of the root, up to
its cap; the truncation is declared, the ordering is declared, and the listing proposes
no belief and mints no record. The alternative — refusing to list a root holding 41
files — would make the mechanism unusable on the first real documents folder it met, and
would trade a real capability for a property the declaration already supplies.

**PDF is in the first rung because the exit names it, and it is the one line of this ADR
that costs a dependency.** Nothing in this project extracts text from a PDF today. §13
binds the implementing lane to evaluate and adopt a library under ADR-0024's pinning
discipline and this project's library-evaluation practice, and **this ADR names none**:
naming one here would decide a dependency on no evaluation, in a document whose reviewers
are not evaluating it. What this ADR does fix is the shape the adoption must satisfy: the
extraction runs in-process, reaches no network, is deterministic for a given file, and
converts a failure into `EXTRACTION_FAILED` rather than raising out of the fetch.

**Off until configured, which is what makes the standing cost zero.** A deployment with
no root pays no listing read, renders no listing block, and cannot service the kind. That
is also why §9's fire rate for this kind reads 0% in such a deployment, and why §9 says
that is a true statement about the configuration rather than a reading of a trigger.

### 7. Servicing: one site, one budget, and the fetch goes first

> **Normative.** A `LOCAL_FILE` ask is serviced in `orchestration/reads.py`'s
> `service_read_request` and nowhere else, inside the turn, after the planner returns
> and before the `TurnResult` is constructed. ADR-0226 §5 binds entire: the servicer is
> not the composing stage, is not a tool, is registered nowhere, advertises no
> capability, and **a servicing failure degrades the turn and never fails it**.

> **Normative.** **ADR-0226 §5's channel scoping binds this kind unchanged.** A request
> is not serviced on an operation whose output channel's audience is unbounded, and no
> lane services a `LOCAL_FILE` ask there on the ground that the reply will otherwise be
> thin. A planner on such a turn is not told; what is scoped is the servicing, so the
> trigger goes on being measured on every channel.

> **Normative.** **The servicing order is: local file, then citation hop, then sighted
> query.** ADR-0226 §6's decision is applied and not moved — the capped read ahead of the
> uncapped one — and this kind is the most tightly capped of the three: one label, one
> file, one record, always. Where the fetch takes its slot the hop is serviced with nine
> and the query with what remains; a fetch that refuses takes none.

> **Normative.** **One budget, and the fetch draws one slot of it.** ADR-0226 §6's budget
> of ten binds per servicing (ADR-0228 §7), counted after deduplication, and this kind
> takes at most one of those ten. It is not a share, not a second budget, and no lane
> funds it by lowering `RETRIEVAL_LIMIT` or `EPISODIC_SUPPLEMENT_LIMIT`.

> **Normative.** The fetched record enters **ADR-0226 §7's fourth group**, appended whole
> with the rest of the servicing's yield in servicing order. **There is no fifth group**
> — ADR-0228 §7 rules it in terms — and no attested group: the three groups the planner
> saw keep their contents, their order and their positions, and §7's whole-union
> deduplication, discards-nothing-by-class clause and constructed-once rule bind on the
> fetched record as on any other.

> **Normative.** **A fetched record fires ADR-0204 §2's evaluation**, as ADR-0226 §7
> moved it and ADR-0228 §7 refined it: once, after the last servicing, over the turn's
> final supply. ADR-0223 §2's externality value is computed over that same final supply.
> Neither is computed twice and neither from an intermediate supply.

> **Normative.** **A serviced fetch may revise the plan exactly as an inward read may.**
> ADR-0228 §2's seven conditions are unchanged and none of them is about the kind: a turn
> whose operation declares a planning budget, whose plan carried a request, whose request
> was serviced, and which meets the other four, makes its second planner call over the
> supply the fetch produced. No lane adds an eighth condition for this kind, and none
> suppresses a revision because the read was outward.

**The fetch goes first, and the argument is ADR-0226 §6's own.** That section orders the
hop ahead of the query because *"ordering the capped read ahead of the uncapped one makes
the union the *measured* union in the ordinary case"*, and because a query *"can return
the whole budget on *every* firing"*. This kind is capped at one record by §1, so putting
it first costs the hop at most one slot of ten and guarantees that a turn which asked for
a file gets the file. The reverse order would let a hop that reached ten records starve
the one read the user pointed at — the strongest namer in ADR-0226 §3's hierarchy losing
to the weakest. It is also, at one slot, the cheapest precedence position this corpus has
ever had to argue for.

**A revision over a fetched file is the mechanism working, and §8 is where its risk is
faced.** ADR-0228 §1 makes a revision *"the model's judgement over a wider supply"*, and a
document the planner asked for is exactly the material a second judgement is worth making
over — it is the shape #1908's exit describes, where the answer depends on what the first
read found. That this is also #1844's steered loop is not glossed: it is §8's whole
subject.

### 8. Inward-only becomes disk-only: what ADR-0228 §11's argument becomes

> **Normative.** **A revision's request may be composed over a fetched file's content,
> and that is admitted rather than prevented.** No lane filters the fourth group,
> subtracts a fetched record from a supply, narrows what a second planner call sees on
> the strength of a record's origin, or refuses a revision because the turn fetched.
> ADR-0204 §4's narrowing prohibition, ADR-0226 §7's discards-nothing-by-class clause and
> ADR-0228 §11's own no-filtering clause bind here unchanged.

> **Normative.** **The containment is that there is nowhere to steer to, and it rests on
> three properties, each of which is a clause of this corpus rather than an
> implementation detail.** (a) The address space is the listing of one root a deployment
> configured, and the model names an **ordinal into it** — §2, under which no byte of
> model output is ever interpreted as an address. (b) A fetch is an open, a read and a
> close on the local filesystem: **nothing leaves the device on the fetch path**, and this
> ADR authorises no egress, designates no seam, adds no `DestinationProtocol` member and
> is cited toward none of those (ADR-0154 §4, §7; ADR-0017 §1). (c) The one outward path a
> steered plan can reach is the **egress seam**, and a turn that fetched has stamped its
> capture, so ADR-0223 §6's allow applies and *"every subsequent turn of that
> conversation that reaches the egress seam is a confirmation rather than an allow"*.

> **Normative.** **Three things would break it, and each is named so that a later lane
> meets it as a condition rather than discovers it.** A kind whose fetch itself leaves the
> device — that is #1996's Lane B, deferred in §15, and this ADR decides nothing for it. A
> fetch whose address space is composed by a model rather than shown to it, which §2
> forbids. And any relaxation of ADR-0223 §6's stamp or ADR-0154 §4's
> standing-authorisation floor, neither of which this ADR touches or may be cited toward.

> **Normative.** A planner-composed query is a **model completion with no recorded
> origin**, of the same class as `ActionPlan.rationale`, at every iteration and whether or
> not a file was in the supply it was composed over (ADR-0226 §9, ADR-0228 §11). A query
> composed after reading a document is not of a better class than one composed before, and
> no lane renders it to a channel a rationale is inadmissible to, infers a placement for
> it, or treats it as evidence of anything.

**ADR-0228 §11 said the loop could read the owner's own store, "which is the rung below
even that", and this ADR moves it to exactly that rung and no further.** #1844's sentence
is the whole permission being exercised: *"A steered loop that can only read the owner's
own disk has no channel out."* The steering is real and this ADR says so rather than
denying it — a second plan's ask **is** composed over the first fetch's yield, and a file
under the root may hold text an attacker wrote. What that text can cause is a second
fetch of another file under the same root, or a sighted query over the owner's own store.
It cannot cause a fetch of anything the listing did not show, because there is no
argument through which a name can be expressed; and it cannot cause a byte to leave the
device on the read path, because the read path is a filesystem call.

**What it *can* reach is an act, and the corpus already governs that, in the same words
ADR-0228 §11 used.** A revised plan may name a step and that step may reach the egress
seam. ADR-0223 §6 rules that the binding carries `planned_with_external_content` *"exactly
as it applies for any other reason"*, and forbids a carve-out. Under ADR-0228 §7's
monotonicity nothing leaves a supply between iterations, so a turn whose revision was
composed over a fetched file stamps its binding and its capture, and every later turn of
that conversation asks. **That is not a side effect of this rung; it is the reason this
rung is affordable.** The containment this corpus claims has always been the user's own
judgement — ADR-0181 §5's *"a call the user is asked about, with the fact in front of
them, is the containment #668 asks for"* — and a fetch is the event that arms it.

**The honest residual, stated because a decision that claimed none would be wrong.** A
fetched file's text reaches the model provider, exactly as every record in every turn's
supply does, under ADR-0004 §2's permitted egress to providers the user configured. A
document the owner would not have pasted into a chat can therefore reach a provider
because a planner asked for it. That is a real widening of what leaves the device, it is
bounded by the root the owner configured and by §6's size bound, and it is disclosed here
rather than discovered. A deployment that will not accept it configures no root, which is
§6's default.

### 9. The audit: one record per turn, one new field, and no address anywhere

> **Normative.** §9 of ADR-0226 binds entire and this kind adds **no second audit, no
> second event key and no new emission point**. One `INFO`-level structured log event per
> turn, under the one fixed key, emitted once, conditioned on nothing, carrying the
> ambient correlation identifier and **no other identifier**. A `LOCAL_FILE` ask appears
> in the servicing's `kinds` exactly as the other two do.

> **Normative.** The record gains **one field per servicing**: the `FetchRefusal` the
> fetch resolved to, where it resolved to one, and nothing where the fetch returned a
> record or where no `LOCAL_FILE` ask was made. It is a **member of a closed enumeration**
> and never free text.

> **Normative.** **The address is Tier 1 and the record carries none of it.** No path, no
> root, no file name, no extension, no size, no `modified_at`, no excerpt of the extracted
> text and no message from an extraction library appears anywhere in this event. ADR-0226
> §9's no-copy rule — *"counts and kinds, and copies no text"* — binds this kind without
> qualification, and ADR-0004 §5's *"Tier 0/1 data must never be logged"* is why. What
> keeps the record inside Tier 2 is these clauses and not the redaction net.

> **Normative.** **An unresolved label and a refusal are two facts and are recorded
> separately.** A label that resolved to nothing never reached the fetcher and counts in
> the existing unresolved-label count; a refusal is a label that resolved to an entry the
> fetcher then declined. An implementation that collapses them makes the two
> indistinguishable, and they have different causes and different fixes.

> **Normative.** **The trigger is measured for this kind exactly as ADR-0226 §8 measures
> it, from the first deploy, with no new instrument.** A turn on which any plan carried a
> request is a firing; the ask's kind says what was asked for; the fire rate, the novelty
> rate and — new here — the **refusal rate per kind** are all readable over a population
> of turns from this one event. Every figure is computed over a population and never as a
> per-turn quantity, and no lane calls any of them precision or recall: §8's reason is
> unchanged, that the record carries no per-turn label of whether the supply in fact
> sufficed.

> **Normative.** **A deployment with no root configured reads a 0% fire rate for this
> kind, and that is a true statement about that configuration rather than a reading of a
> trigger.** No lane reports a fire rate for this kind without saying whether a root was
> configured, for the reason §8 of ADR-0226 gives about the `Planner` a deployment runs.

**One field and not a family, because everything else §9 would want is already there or
is forbidden.** How many records came back, how many were new, how many the deduplication
removed, whether the budget truncated, whether the servicing failed — all of those are
per-servicing counts that this kind contributes to unchanged. What only this kind can
produce is a *decided non-yield*: a label that resolved to a real entry which the fetcher
then declined, which no existing field distinguishes from a fetch that returned nothing
because none was asked for. That distinction is the one worth an operator's attention —
it is how a deployment learns that its size bound is set below its documents, or that its
root holds formats the rung does not read — and it is a class, so §9's no-copy rule
admits it.

**And the address stays out for the reason ADR-0226 §9 kept the query out.** That section
removed a retained query because *"nothing bounds what a planner may put in a query"* and
the retaining clause and the no-content clause *"would then contradict each other on the
same bytes"*. A file name is the same shape of value: it is chosen by whoever named the
file, it can carry anything a filename can carry, and a Tier 2 event that logged one would
be a Tier 1 leak on a value this system did not mint. The ask stays durable on the frozen
`ActionPlan` — the label, which is an ordinal and discloses nothing — and the record
neither copies it nor points at it.

### 10. Persistence: turn-scoped, and what the ordinary capture path already keeps

> **Normative.** **A fetched record is supply and never a store write.** No fetched record
> is ingested, proposed, folded, superseded or written to the `MemoryStore`, and nothing
> is written to any store on account of a fetch. It reaches `MemoryWriter.ingest` at no
> point and is not exempt from ADR-0093 §1's rule — that rule governs what a producer
> **proposes to memory**, and this producer proposes nothing.

> **Normative.** **It is not a citation target and not a durable reference.** Its `id` is
> minted for one turn, is rendered to no model, is accepted from none and resolves in no
> store; nothing writes it into a `Provenance.evidence`, and no later turn reaches it. A
> `CITATION_HOP` naming a fetched record's label on a turn's second call reaches the record
> itself (ADR-0229 §1) and finds its `evidence` empty, which is the correct answer and not
> a degradation.

> **Normative.** **What persists is the turn, through the path that already persists it.**
> The episode captured for a turn that fetched carries the exchange as it always does and
> is stamped `derived_from_external` by ADR-0223 §1's disjunction, and the observer reaches
> it as it reaches every other episode. This decision adds no capture, no writer and no
> second retention rule.

> **Normative.** **A second turn re-fetches**, reads the file as it stands at that instant,
> and mints a record whose `reported_at` is that instant. There is no earlier record to
> contradict, no fold, no supersession and no staleness question, because nothing was
> retained. Two turns over a changed file hold two readings, each true of its own instant —
> which is ADR-0073 §4's distinction working rather than a conflict to resolve.

> **Normative.** **Retention by address in a source-material archive is deferred, not
> declined**, and §15 names what fires it.

**Turn-scoped is the decision the store's own contracts point at, and #1908's lean is
where it points too.** Writing a 32 KiB document into the belief store as one attested
record would put an object into `MemoryStore` that supersedes nothing, folds with nothing
and is retrieved by relevance against beliefs — and ADR-0092 §7 already records what
happens on the second fetch of an edited file: *"a small edit folds; a rewrite
duplicates"*, filed as #631 and not closed. The memory store is a store of beliefs and
episodes; a document cache is a different thing, and #1907's direction says so by naming
the **source archive** rather than the store as the destination.

**What is genuinely lost is stated rather than minimised**: a second turn that asks about
the same document pays the fetch again, and a conversation cannot cite the document a
week later by pointer. The first is a bounded local read. The second is real, and it is
what §15's deferral is for — and it is softened by the fact that the *answer* survives:
the turn's own episode carries what the assistant said about the file, through the
capture path this decision leaves untouched.

### 11. No grant seam, and what would fire one

> **Normative.** This ADR adds **no `GrantScope` member**, contracts no `SourceGrants`
> into the `Fetcher` seam, and gates neither the listing nor the fetch on a source grant.
> ADR-0097's grant seam, ADR-0132 and ADR-0133 are untouched, and no lane reads this
> section as relaxing any of them for a `Reader`.

> **Normative.** **What authorises a fetch is the owner's own turn over the owner's own
> configured root**, and both halves are required: the mechanism is off until a root is
> configured (§6), and it fires only inside a turn the user started, only where that
> turn's planner asked, and only for an entry the loop showed. No scheduled job, timer,
> proactive producer or background pass reaches a `Fetcher`, and no lane wires one to
> anything that is not a turn.

> **Normative.** **Three things fire a grant decision, and a lane meeting any of them
> stops rather than proceeding.** A `Fetcher` driven from anything that is not a
> user-started turn. A `Fetcher` over a source that is not a root configured on this
> machine — #1996's Lane B is exactly that case. And a fetch whose yield is written to any
> store, which §10 forbids and which would make the fetch a producer of durable beliefs.

**The grant seam's own reason is what decides this, and it is a reason about
unattended drivers.** `SourceGrants` exists because *"A driver handed the whole store is
a scheduler job that can mint its own authorisation: the ingestion stage runs on ADR-0083
§7's timer, and a `record` on the object in its hand is a valid `SourceGrant` away from
authorising itself, with nothing about the resulting record looking wrong afterwards."*
Every element of that is absent here. There is no timer, nothing is written, and the
driver is a turn the user is sitting in front of, whose reply will contain what the file
said. ADR-0133 §2 fixes the grant axis *"at one scope per consumer of a **reading**"* — a
`SourceReading`, which a `Fetcher` does not produce and no `Reader` is driven to make.

**It is not "local, therefore ungated", and it would be wrong if it were.** The calendar
reader also reads a local file and *is* gated. The distinguishing fact is not where the
bytes are but who asked and what becomes of them: an unattended pass that writes durable
beliefs about the owner from a source, versus one turn's read of one file the owner named
a folder for, retained nowhere. The three firing conditions above are drawn on exactly
that line, so a later lane that erodes it meets a stop rather than a silence.

### 12. The versions that move

> **Normative.** **`PROTOCOL_VERSION` moves 27 → 28**, and `wire/envelope.py`'s log gains
> an entry naming this ADR and this reason. `ActionPlan` is carried to a client inside
> `TurnOutcome.turn.plan` (ADR-0228 §6), `wire/codec.py`'s projection dumps every field of
> a model, and `ReadAsk` sets `ConfigDict(extra="forbid", frozen=True)`. So a peer whose
> `ReadKind` predates `LOCAL_FILE`, or whose `ReadAsk` predates `entry`, fails to decode a
> `TurnOutcome` whose plan carries either.

> **Normative.** **`PlanExport.schema_version` moves 4 → 5**, by ADR-0039 §10's mechanism
> as ADR-0226 §4 and ADR-0228 §6 last applied it: the annotation is edited rather than
> defaulted, so a document of an earlier shape does not validate against this contract at
> all. `PlanExport` carries `tuple[ActionPlan, ...]` and a member of it changed shape.

> **Normative.** No lane reads this section as authority for bumping on a defaulted
> addition alone. What obliges each move is the conjunction ADR-0228 §6 states — a
> wire-carried type, a projection that emits defaults, and `extra="forbid"` — and
> ADR-0213 §11's no-bump ruling stands for the case it decided.

> **Normative.** **This ADR neither repairs nor inherits #1956**, the window ADR-0226 §4
> left open by shipping `ActionPlan.read_request` at `PROTOCOL_VERSION` 26. §6 of ADR-0228
> filed it and declined it for the same reason: it is a decision about a released version
> rather than about this mechanism.

### 13. What the implementing lanes owe

> **Normative.** **Three lanes, in order, each briefed from this ADR's merged text**, and
> none before this ADR is Accepted and merged (golden rule 5).

**Lane C1 — the contract, the fetcher, and the composition.** `core/protocols.py`'s
`Fetcher`; `core/types.py`'s `SourceListingEntry`, `SourceListing`, `FetchOutcome`,
`FetchRefusal`, `ReadKind.LOCAL_FILE` and `ReadAsk.entry` with its validator arm; the
`Settings` fields of §6 and §4 with their named defaults and their load-time refusal;
§4's token-and-handle mechanism, satisfying all three of its stated properties and its
expiry, **in the fetcher and not in `core`** — the types carry the values and the fetcher
owns what makes them unforgeable; the **shared conformance suite** for `Fetcher`; the
**canonical fake** in `ai_assistant.testing`, which mints and verifies its own tokens and
handles so the suite's membership clauses are not vacuous on it; the concrete local-file
fetcher in `ai_assistant/readers/`, whose acquisition satisfies §4's race clauses; the
PDF extraction library's evaluation and adoption under ADR-0024; and `app/composition.py`'s
wiring, which constructs a `Fetcher` only where a root is configured.

> **Normative.** Lane C1 ships the **triad** — Protocol, shared conformance suite and
> canonical fake — **together with its primary production implementation**, under
> ADR-0137 §2. It is one lane and not two: the slice fails §1's single-subsystem test only
> because the contract and its first concrete are separated by that contract, which is the
> case §2 exists for. Splitting it would land a `Fetcher` no implementation had been
> written against, which is the failure `CONTRIBUTING.md` → "Adding a Protocol" names.

> **Normative.** The conformance suite holds the clauses expressible **without a source**:
> `name` is stable and non-empty; a `SourceListing`'s `source` equals `name`; `read_at` is
> tz-aware; an **empty listing is a valid, successful listing** and every clause holds on
> it; a `FetchOutcome` carries a record **or** a refusal and never both or neither; a
> minted record is `SEMANTIC`, `EXTERNAL`-sourced, carries an `Attestation` whose
> `reported_by` equals `name`, and carries an empty `evidence`; **an entry the test
> assembles itself is refused**, and so is one built by copying a listed entry's `name`,
> `size_bytes` and `modified_at` onto a handle of the test's own choosing, and so is a
> listing the test assembled, and so is an entry of listing A presented with listing B's
> token; **a listing past `fetch_listing_ttl` is refused** on a fake monotonic source
> while one inside it is not, **a wall clock stepped backwards does not extend one**, and
> **producing further listings invalidates none of them**; **no
> member raises for a source reason**; and a `listing()` or `fetch()` cancelled while
> suspended re-raises `CancelledError` unchanged — checkable through the fake's suspension
> gate (`SuspendableResource.suspend_next`), without which the clause passes vacuously.
> The handle clauses are suite clauses and not the concrete fetcher's, because they are
> decidable from `name` and two return values and they are the clauses on which §2's
> containment rests for **every** `Fetcher` this system ever wires.

> **Normative.** Four rulings are deliberately **not** suite clauses, and putting them
> there would be the error: that the root bound is un-widenable (the Protocol takes no
> argument that could widen it, so a generic suite has nothing to over-supply); that a
> **real** source failure produces each refusal class (a suite cannot make an arbitrary
> fetcher's source fail — those are the concrete fetcher's tests, and it owes one per
> `FetchRefusal` member); that a path escaping the root is refused and that the two race
> transitions of §4 are refused (a concrete fetcher's test over a real filesystem, and it
> owes `..`, a separator in `name`, a symlink out of the root, a replacement between
> validation and acquisition, and a growth past the bound between them); and that the
> listing is ordered most-recently-modified-first and capped. Each is named here so the
> lane does not read its absence from the suite as its absence from the contract.

**Lane C2 — the listing across the seam and the planner's emission.** `Planner.plan`'s
`files` parameter and its documented meaning; the loop reading the listing once per turn
and passing the same sequence to both calls; §2's `F`-labelled rendering of it in
`planning/planner.py` with ADR-0098 §2's escaping; the prompt that asks for a
`LOCAL_FILE` ask and the parse that reads one; and the extension of the shared
`PlannerContract` (`tests/planning/planner_contract.py`) for the widened input, so the
model-backed planner and the canonical fake are both held to it.

**Lane C3 — the servicing, the precedence and the audit.** In `orchestration/`: §2's
label resolution by index into the listing the loop passed; the fetch's position ahead of
the hop; its single slot of ADR-0226 §6's budget; its record's entry into the fourth
group under §7's deduplication; §6's refusal disposition; and §9's one added audit field.

> **Normative.** **Lane C1 then C2 then C3, and each is useful alone.** A merged C1 is a
> fetcher nothing calls, in a deployment with no root configured — reviewable against real
> files before anything reaches a prompt. A merged C2 is a planner that can name a file
> nothing fetches, which is §3's defaulted parameter read from the other side and lets the
> emission's shape be reviewed against real prompts before any read fires. C3 without
> either would be a servicer with nothing to service.

> **Normative.** Between C2 and C3 there is no mechanism: a C2 turn's `LOCAL_FILE` ask
> reaches no fetcher, adds no record to any supply, changes no reply and changes nothing a
> capture records. Nothing is deployed that §9's audit cannot measure.

> **Normative.** No lane invents a second label scheme, a shared label table, a path
> crossing `planning` and `orchestration`, a second servicing site, a second budget or a
> second audit. No lane implements, prepares for, or leaves a hook for anything §15 defers
> — and in particular none admits a transcript-archive entry to a prompt, to the supply or
> to a citation resolution (ADR-0225 §4, §12).

**Three lanes and not two, under ADR-0137 §1**, whose test is where substantial new
machinery lands: *"A slice is one lane only if its implementation puts substantial new
machinery into at most one subsystem."* C1 is `core` plus `readers` and rides §2's triad
exception. C2 is new machinery in `planning` — a labelled rendering, a second thing the
prompt asks for and the parser reads — with a threaded argument in `orchestration` that
§1's own carve-out covers (*"a call site updated, an argument threaded through"*). C3 is
new machinery in `orchestration`. ADR-0226 §10 decomposed the same shape into two for the
same reason; this decision adds a contract, so it adds a lane.

### 14. The representative-input tests this decision owes

> **Normative.** The implementing lanes owe tests for each of the following, and each is a
> test over behaviour rather than over a call count.

1. **The exit's disk clause answers from disk.** A turn whose supply holds nothing about a
   document; a root holding a PDF whose text carries a distinctive word; the listing shows
   it; the planner names its label; the fetch mints one record; and **the reply carries the
   word**. Asserted through `orchestration/composing.py`'s **production renderer** over a
   record shaped as the fetcher writes it, with a fake `ModelProvider` that reads the
   assembled prompt — ADR-0226's amendment of 2026-09-03 by ADR-0227 binds this item: *"A
   required representative-input test that asserts a fact about **what a model was shown**
   runs the production renderer for that surface, and drives it over records **shaped as
   the production capture site writes them**."*
2. **An address outside the root resolves to nothing and is audited.** Four arms, each
   adding no record, failing no turn and raising nothing: a label past the listing's end; a
   label that is not of the form; an entry whose `name` carries a directory separator or a
   parent reference; and an entry naming a symbolic link that resolves outside the root.
   The first two are recorded as unresolved labels, the last two as refusals, and **no
   model-supplied string reaches a filesystem call in any arm**.
3. **A file the listing did not show is not fetchable, however the entry was built.**
   A root holding more supported files than the cap; an entry assembled for one the
   listing omitted, with a plausible `name`, `size_bytes` and `modified_at` and a handle
   the test invented; and an entry that copies a *listed* entry's display fields onto that
   invented handle. Both are refused `NOT_FOUND`, no record is added, and the file's
   distinctive text appears nowhere in the supply or the reply. Two further arms at the
   same seam: an entry of listing A presented with listing B's token, and a `SourceListing`
   the test assembled around a real entry. Asserted at the `Fetcher` seam, because it is a
   property of the contract and not of the loop that happens to call it.
4. **The two race transitions are refused.** Over a real filesystem, deterministically
   sequenced so the transition lands **between** the fetcher's validation and its
   acquisition: a supported regular file replaced by a symbolic link pointing outside the
   root, which is refused `NOT_A_FILE` and reads nothing from the link's target; and a file
   that grows past `fetch_max_file_bytes` after its size was observed, which is refused
   `TOO_LARGE` and puts no prefix of the grown content anywhere. Neither yields a record
   mixing one object's metadata with another's content.
5. **A listing expires on elapsed time and on nothing else.** Three arms, each
   deterministic. On a fake **monotonic** source, a listing past `fetch_listing_ttl` is
   refused `NOT_FOUND` and one inside it is fetched. **The wall clock does not decide it:**
   a listing is minted, the wall clock is stepped *backwards* by an hour, the monotonic
   source is advanced past the TTL, and the listing is still refused — the arm that fails
   on any implementation comparing `read_at` against a wall clock, and it is here because
   an earlier draft of §4 did exactly that. And **nine listings are produced before any of
   them is fetched from**, after which every one of the nine fetches its own entry
   successfully — the arm that fails on any implementation whose validity is a function of
   how many listings have been produced since, and it is here because a still earlier draft
   had that defect.
6. **A turn whose supply sufficed pays no fetch.** The plan carries no request, the fetcher
   is asked for no file, the supply is byte-for-byte the three groups it was, and the audit
   records a turn on which the trigger did not fire. Asserted over the audit and the supply,
   not over a mock's call count.
7. **The label is an ordinal into the listing the loop passed.** `F2` resolves to the second
   entry of that turn's listing and to nothing else; the same planner output against a
   different listing resolves to a different entry; the two packages agree with no shared
   table, asserted by resolving an ask against a listing the test constructs directly; and
   the same label resolves to the same entry on **both** planner calls of a revising turn.
8. **A file over either bound is refused, and nothing is truncated.** A file over
   `fetch_max_file_bytes` and a file whose extracted text is over `fetch_max_content_bytes`
   each yield a refusal, add no record, fail no turn, and put no prefix of the text
   anywhere in the supply or the reply. Asserted over the supply and over the audit's
   refusal class.
9. **Every refusal class is reachable from a real source.** One arm per `FetchRefusal`
   member, over a real filesystem: absent, a directory, unreadable by permission,
   over-size, an unsupported extension, and a corrupt file of a supported format. This is
   the concrete fetcher's test and not the suite's (§13).
10. **A fetched record carries the external mark, and the conversation asks thereafter.** A
    bounded-audience turn that fetches captures an episode whose `derived_from_external` is
    `True`; the same turn's `SelectionOrigin` carries `planned_with_external_content`; and a
    **subsequent** turn of that conversation reaching the egress seam is a confirmation
    rather than an allow. This is the assertion standing between this rung and #1844's
    exfiltration channel, and it is asserted end to end rather than at the predicate.
11. **The fetch is serviced before the hop and takes one slot.** A request carrying a
    `LOCAL_FILE` ask and a `CITATION_HOP` whose evidence would fill the budget produces a
    fourth group holding the fetched record first and exactly nine hop records after it, in
    that order, with the truncation in the audit.
12. **A refusal degrades nothing.** A request carrying a `LOCAL_FILE` ask that refuses and a
    `SIGHTED_QUERY` that returns produces a fourth group holding the query's records in
    full: the refusal takes no slot, discards nothing, and is recorded as a refusal rather
    than as a servicing failure. This is the arm that distinguishes §6's refusal disposition
    from ADR-0226 §5's all-or-nothing failure posture.
13. **A serviced fetch may revise the plan.** A turn whose first plan names a file and
    whose second plan, made over the fetched record, names a different one; both fetches
    are serviced, the fourth group holds both records in servicing order, and each
    servicing draws its own budget (ADR-0228 §7). Asserted over the supply and the audit's
    per-servicing entries.
14. **An unbounded-audience operation fetches nothing.** A turn on `converse_spoken` whose
    planner emits a `LOCAL_FILE` ask reaches the composing stage with the three groups
    ADR-0203 §1 narrowed, performs no filesystem read for the request, and records the
    emission as declined.
15. **The audit copies no address, and no handle leaves the fetcher.** A turn that
    fetches a file whose name carries a distinctive string emits a record in which that
    string appears nowhere — no path, no name, no extension, no size, no excerpt — the
    refusal field is a closed-enumeration member or absent, and the ambient correlation id
    is the only identifier on the event. Asserted over the emitted event's own fields, not
    over the redaction net. Separately, the entry handles of that turn's listing appear in
    **no** prompt the turn assembled, in no log line and on no field of the record the
    fetch minted.
16. **The listing is bounded, ordered and declared.** A root holding more entries than the
    cap lists exactly the cap, most recently modified first; a root holding unsupported
    types lists none of them; a root that cannot be read and an empty root both produce an
    empty listing, and no consumer distinguishes them.
17. **The models refuse what §1 says they refuse**, arm for arm: a `LOCAL_FILE` ask with a
    blank or whitespace-only `entry`; one carrying `entry` **and** a query; one carrying
    `entry` **and** labels; a `SIGHTED_QUERY` or `CITATION_HOP` ask carrying an `entry`; a
    `ReadRequest` with two `LOCAL_FILE` asks; a `FetchOutcome` carrying both a record and a
    refusal, and one carrying neither; and a mutation of any of them after construction.
18. **Nothing is written.** A turn that fetches leaves the `MemoryStore` byte-for-byte as it
    was but for the ordinary capture: no fetched record is ingested, none is retrievable on
    a later turn, and its id resolves in no store. Asserted over the store, not over a
    writer mock.
19. **The versions moved and announce the shape.** A `PlanExport` whose plans carry a
    `LOCAL_FILE` ask round-trips with `schema_version` 5; a document labelled 4 does not
    validate as a `PlanExport` at all; both conforming `PlanStore` implementations export
    the new version; and `PROTOCOL_VERSION` reads 28 with `wire/envelope.py`'s log naming
    this ADR.

### 15. Deferred, by name, each with what fires it

- **Web search and fetch** (#1996 Lane B, #1908 milestone 29's second clause). A second
  outward kind naming a source **off the device**. What this ADR leaves open for it is
  stated so that lane inherits a question rather than an assumption: whether it is a kind
  of this enumeration or a sibling; whether it can use `Fetcher` at all, which turns on
  whether a URL has a *shown* address space — §2's ordinal scheme has no analogue for the
  web, where there is no listing the loop produced and a URL is a string a model composes,
  so that lane's namer question is genuinely different and this ADR pre-empts none of it;
  and **the egress seam**, which is ADR-0154's and about which this ADR decides nothing
  (ADR-0154 §7). Fired by that lane's own ADR.
- **Retention by address in a source-material archive** (#1907, ADR-0225 §11). §10 keeps a
  fetched record for one turn. A design that wants a document reachable a week later
  retains it in the source archive, which milestone 21 carries and which does not exist;
  ADR-0225 §11 rules that a later ADR deciding source-material custody *"may place its
  store beside this one … and supersedes no clause of this ADR by doing any of it"*, and
  that *"What it may not do without superseding §4 is admit either store's content to a
  model prompt"*. Fired by that store existing **and** by an ADR that answers §4's
  admission question for it. Not fired by a lane finding a re-fetch wasteful.
- **A second file per ask, or several asks of one kind.** §1 admits one file per ask and
  ADR-0226 §2 one ask per kind per emission. Both are the decomposition question ADR-0226
  §12 and ADR-0228 §14 already defer, and iteration already gives a turn a second file with
  sight of the first (§7). Fired by §9's audit showing that a turn's two file asks are
  ordinarily facets of one compound question rather than a follow-up.
- **More than one root, or a root the user names in the turn.** §6 fixes one configured
  root. A second root is a listing-composition and precedence decision; a root named in a
  turn is a model-composed address by another name and §2 forbids it. Fired by an ADR that
  decides how several address spaces are labelled and ordered.
- **A format whose extraction declares a report time.** §5 takes the fetch instant for
  every format. A format that carries its own declared instant — a PDF's `/ModDate`, a
  document's core properties — has a claim ADR-0092 §3 would prefer, and using it needs a
  rule for an absent, malformed or future one and a consumer that benefits. Fired by that
  consumer.
- **Recursion, subdirectories and a filesystem query.** §6 lists direct children only, so
  a document in a subfolder is unreachable. Recursion multiplies the listing against a
  fixed cap and a *query* over the filesystem is a relevance selection at a third site,
  which is ADR-0208 §1's question and not this one's. Fired by an ADR that decides how a
  listing is selected rather than ordered.
- **A turn identity threaded onto the fetch contract**, so the seam itself could refuse a
  listing that is not the calling turn's rather than one that has expired (§2, §4). It
  would close the residual §2 states — a lane that breached §3 and retained a listing
  could fetch inside the expiry — and it costs a wider contract: a turn identity is a value
  `orchestration` holds and `core` does not, and putting one on this Protocol would make
  every `Fetcher` a party to the turn model. Fired by a second caller of a `Fetcher` beside
  the loop, or by §9's audit showing a fetch reaching a turn that did not show its listing.
  Not fired by a lane preferring a tighter-sounding clause.
- **A grant scope for a fetch** (§11), fired by any of §11's three named conditions.
- **A fetch on a channel of unbounded audience** (§7, ADR-0226 §5, §12). Deferred for
  ADR-0203 §2's backfill reason, unchanged by this kind. Not fired by a lane finding spoken
  replies thin.
- **Anything §9's record would need a store to answer.** ADR-0226 §12 defers a durable,
  queryable surface for the audit; this kind adds one field to the same log event and
  inherits that deferral whole.

### 16. Scope, and what this records against earlier ADRs

**This ADR amends two ratified ADRs in one scope each and partially supersedes a third in
one scope, and no others** — ADR-0226, ADR-0228 and ADR-0092 — and every other clause it
cites binds as written. That is a classification of this change and is therefore stated as
prose rather than marked (ADR-0089 §1). The header carries each record; what follows is the
working under ADR-0082 §1's test, and the clauses a reader would most expect to have moved
and which did not.

**ADR-0226 §2's membership sentence and §6's precedence sentence are amended, and neither
ruling is replaced.** ADR-0082 §1's test is *"Would a reader holding only the earlier ADR
now act differently, or read one of its clauses more widely than it now holds?"* — and on
both sentences it comes out yes, so a record is owed. It is an **amendment** and not a
supersession because the rulings survive: §1 of ADR-0226 tells its own reader in terms how
a third member arrives (*"A later kind is an **additive entry** to this enumeration"*), and
§4 says the vocabulary *"is **added to** and never renamed"*, so a reader holding only
ADR-0226 is not led to refuse the addition — only to believe the enumeration currently has
two members, which is what the note corrects. §6's decision, that the capped read precedes
the uncapped one, is not replaced but applied: it is the reason §7 above puts a one-record
read ahead of a ten-record one. ADR-0226's `Status` line carries the leading `Partially
superseded by` token from ADR-0228, so ADR-0082 §2 puts this record in the appended dated
note and writes no qualifier on that line — the shape ADR-0229 used one day earlier for its
own amendment of the same ADR.

**ADR-0226 §9 is *not* amended, and showing that is the point of this paragraph.** §9 ends
by providing for exactly this: *"These are the fields milestone 2 **raises rather than
replaces**. An ADR admitting a second serviced emission per turn extends this record to
account per emission and keeps every field's meaning; it does not rename them, drop them,
or start a second audit beside this one."* §9 above adds one field for a new kind, renames
nothing, drops nothing, keeps every field's meaning and starts no second audit. No sentence
of §9 becomes false or over-wide, so under ADR-0082 §1 no record is owed and this is a
stacked addition, recorded in the ADR that makes it and nowhere else.

**ADR-0226 §12's outward-fetch deferral is discharged, and a discharge is not a record.**
§12 defers the outward fetch and fires it at this milestone; firing a deferral is the
deferral working rather than a clause becoming false. What §12 also does is state the
ground — #1844's steered loop, the honest first rung being local files, and ADR-0154's seam
granting nothing standing — and §8 above answers each of those on its own terms rather than
citing the deferral as permission. ADR-0226 §12's *"Fired by milestone 3"* is milestone 29
under #1908's global numbering, per Context.

**ADR-0228 §11's two-kinds statement is amended and its rulings are obeyed.** §11's
sentence *"Both kinds a revision may emit are the two that ADR admits"* stops being true,
so ADR-0082 §1's test is met. What it rules is untouched: *"This ADR adds **no kind** to
ADR-0226 §2's enumeration"* remains a true statement about ADR-0228, and its prohibition on
a lane *"reading this ADR as preparing for one"* is honoured — §8 above rests on #1844,
#1908 and ADR-0226 §12, and cites ADR-0228 only for what it **rules**: §7's monotonicity,
§11's no-filtering clause and §11's class clause on a planner-composed query, every one of
which binds here. ADR-0228's `Status` line reads `Accepted` and takes the qualifier
alongside its dated note (ADR-0082 §2).

**ADR-0092 §3's local-substitute clause is partially superseded, in one scope, and this is
the heaviest instrument in this ADR.** §3 rules that `reported_at` *"is not when we read the
file"* and admits no fallback; §5 above sets it to the fetch instant for a source read live
at the moment of its report. A reader holding only ADR-0092 would refuse to build that, so
ADR-0070 §1's test is met and §3's partial form is the sanctioned tool. **The scope is
exactly the case where the two clocks are one event** and reaches no other: a synced or
cached copy of a remote source is untouched, a source that declares its own instant uses
it, and §3's reason — that a substituted value asserts *"a report time the source never
made"* — is why the scope is drawn there and nowhere wider. **§3's mtime prohibition, its
`reported_by` account, its ruling that a `reported_at` earlier than `last_updated` is
normal, and its ruling that one in our future is not refused all stand and are used as
given.** ADR-0092 §1's `_attested_iff_attestation` validator is satisfied rather than
avoided: the record carries an attestation because it is in the attested band.

**Six clauses a reader would expect to have moved, and did not.**

- **ADR-0093 §10's no-arguments rule.** `Reader.read()` still takes no arguments, and its
  reason — *"a caller able to widen the read is a caller able to defeat the bound"* — is
  **honoured** by §4 rather than worked around: `Fetcher.listing()` takes none either, and
  `fetch` takes an entry the fetcher itself minted. ADR-0093 §5's refuse-never-truncate rule
  is applied in §6 for its own reason, and its bound-in-configuration rule is what §6's
  `Settings` fields are.
- **ADR-0208 §1.** Its one-site clause was already superseded by ADR-0226 §13 for the
  sighted query. A `LOCAL_FILE` fetch is not a relevance selection over the store at all —
  it is a keyed read of one file the turn already names — so it needs no supersession, and
  §1's tool clauses are honoured by §7 rather than approached.
- **ADR-0170 §2 and §5a.** The composing stage gains no collaborator, performs no second
  assembly and no second retrieval; §5a's reason for refusing a tool result — *"no per-span
  provenance"* — is why §5 above mints a provenance-carrying record rather than a payload.
- **ADR-0203 §§1 and 2, and ADR-0210 §1.** ADR-0226 §5's channel scoping binds this kind
  (§7), so this envelope still adds no supply member to a turn that has a subtraction, and
  there is nothing to backfill and nothing to re-filter.
- **ADR-0225 §4 and §12.** No transcript-archive entry reaches a prompt, a supply or a
  citation resolution. A *file* is not an archive entry, the two stores share no address,
  and §13 binds the lanes to the same.
- **ADR-0154 §1, §4 and §7, and ADR-0017 §1.** This ADR authorises no egress, designates
  no seam, registers no tool, adds no `DestinationProtocol` member, and is cited toward none
  of those. §8's containment rests on ADR-0223 §6's stamp, which is a control this ADR
  applies and does not relax.

## Consequences

- **A question about a document the owner saved becomes answerable**, which it is not today
  at any configuration. That is the milestone's exit clause and the whole of what this rung
  buys.
- **A deployment pays nothing until it configures a root.** No listing read, no prompt
  block, no ask, no fetch — and a 0% fire rate for this kind that §9 requires be reported as
  a fact about the configuration.
- **A deployment that configures one pays a bounded local directory read on every turn**,
  and a listing block in every planning prompt. It is the price of §2's property and §3
  states it rather than amortising it.
- **A conversation that reads a file asks before its next outward call**, for as long as the
  stamped episodes are in its tail. ADR-0223 §6 accepted that cost in terms and this
  decision enlarges the population it applies to. In a deployment with a root configured and
  an egress destination registered, it approaches "every outward call in that conversation
  asks" — which is the containment working, and is the loudest consequence here.
- **A file's text reaches the configured model provider** when a planner asks for it, under
  ADR-0004 §2's permitted egress. That is a real widening of what leaves the device and §8
  discloses it.
- **`core` gains one Protocol, three models and one enumeration, and two versions move.**
  Every existing `Planner` and `Fetcher`-less deployment keeps working unchanged; a peer
  built before this ADR does not, which is what the protocol move announces.
- **A document is not remembered.** §10 keeps nothing, so the second turn re-reads and a
  later week cannot cite it. §15 names what fires the retention that would change it.
- **Nothing is deployed that the audit cannot measure.** §13's order puts the fetcher, then
  the emission, then the servicing, and §9's record exists from the moment a fetch can fire.
- **What would reopen this decision:** an audit showing the fire rate for this kind is high
  and its refusal rate higher, which would say the bounds are wrong; a listing cap that is
  routinely the reason a file is unnameable, which would say the address space needs
  selecting rather than ordering (§15); or a source-material archive existing, which fires
  §10's deferral.

## Alternatives considered

- **A path the planner composes, bounded by a containment check against a configured
  root.** This is what #1996's survey text contemplates as one of two shapes and what most
  comparable systems do. It is rejected in §2 on the ground that a containment check over a
  model-supplied string is a class of defect — `..`, symlinks, case folding, Unicode
  normalisation — where being *nearly* right is indistinguishable from being right until it
  is not, and on the ground that it forfeits ADR-0226 §3's actual property: that the
  resolvable set is exactly what the loop chose to render. It would have been a smaller
  change: no `files` parameter, no `Planner` widening, no per-turn listing read. The
  property is worth those three.
- **A `CurrentContext` facet carrying the listing.** Considered at length in §3 and close
  enough to record. It needs no Protocol change and puts the listing where situational
  context lives, with a ratified stamp and a ratified failure posture. It is rejected
  because a facet arrives through a `ContextSource` holding a `Reader` and a
  `SourceGrants`, which is machinery for a different contract; because the loop would
  forward a value it did not build, one indirection away from ADR-0226 §3's
  resolve-against-what-you-passed guarantee; and because it would put the listing's bound
  in `context/` and the fetch's in the fetcher, with nothing keeping the two equal.
- **A tool.** Ruled out twice over before this ADR began — ADR-0170 §5a because *"a tool's
  result is a JSON payload with no per-span provenance"*, ADR-0208 §1 because *"A component
  on the turn path that wants records the supply does not hold does not obtain them by
  invoking a tool"* — and not reopened here. ADR-0225 §12 already recorded that the owner's
  own guess at the shape (*"a tool call in the future"*) is the unlikely one for this
  reason.
- **Truncating an over-size file with the truncation recorded.** Rejected in §6: a model
  handed a third of a report answers about the report in the assistant's own voice, which is
  ADR-0072 §6's laundering reached by a new route. ADR-0093 §5 already ruled the general
  case and its reason transfers with force.
- **Placing the fetched record in the `DERIVED` band with `derived_from_external=True`.**
  It fires the same external mark and needs no supersession of ADR-0092 §3, which makes it
  genuinely tempting. Rejected in §5 because it is false: `DERIVED` means we worked it out
  and can re-derive it, and a verbatim document excerpt is neither.
- **Requiring a format-declared report time, so only PDFs are readable.** The most faithful
  reading of ADR-0092 §3 — *"The capability is bounded by what sources can actually say,
  which is the honest place for the boundary"* — and rejected in §5 because it would define
  the mechanism by its formats' metadata rather than by its purpose, excluding the plain
  text and Markdown most people's notes are written in.
- **Writing fetched records to the store as ordinary attested beliefs.** Rejected in §10:
  ADR-0092 §7's *"a small edit folds; a rewrite duplicates"* is unresolved (#631), the store
  is not a document cache, and #1907's own direction names the source archive rather than the
  store. What the corpus already persists — the turn's episode, stamped — is the honest
  answer for this rung.
- **Gating the fetch on a source grant.** Rejected in §11, on the grant seam's own reason:
  it exists against unattended drivers that write durable beliefs, and this one is a
  user-started turn that writes nothing. Three conditions that would reverse it are named
  there so a later lane meets a stop rather than a silence.
