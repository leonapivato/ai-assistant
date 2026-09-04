# 230. The planner names a file it was shown, and the loop fetches it into the turn's supply

- Status: Partially superseded by ADR-0232 (§6's account of what bounds an extraction's cost, in three sentences and no wider: the size-bound clause's second limb, *"which bounds the read **and the extraction's cost**"*, insofar as it makes `fetch_max_file_bytes` a bound on anything but the read — that field stays the file's size on disk at 4 MiB and bounds the read, and **one** `Settings` field, `fetch_max_decoded_bytes`, bounds the decoded bytes an extraction parses **as content-stream instructions**, which is the superlinear quantity; the decoded classes an extraction reads *linearly* — an object stream, a `/ToUnicode` CMap, an embedded font program — are **not** bounded by ADR-0232, which says so in terms and defers them by name, so what replaces the limb is narrower than the limb; the same clause's count in *"**Two** size bounds"*, which becomes three; and the enumeration in *"A file over **either** bound yields a refusal and no record"*, which becomes any of the three — while that clause's ruling, a bound is enforced by refusing and never by truncating, is extended rather than replaced and binds the new bound entire. The refusal stays `TOO_LARGE` and `FetchRefusal` stays closed at five members. Everything else in §6 stands — the one configured root and its unset default, the two-stage fail-closed eligibility, the listing's ordering, cap and type allow-list, `NOT_FOUND` for an unread type, `fetch_max_content_bytes` at 32 KiB counted on the quoted rendering while extracting, the stated-domain-and-load-time-refusal clause over the four fields this ADR adds, the every-member-is-reachable clause, the resolved-outcome clause, the shape fixed for the PDF adoption including *deterministic for a given file*, and off-until-configured — and §§1–5 and 7–16 are untouched, §4's re-applied-at-fetch clause governing the new bound as it governs the other two)
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
  rung #1844 names as having no channel out — and "the owner's own disk" is made a
  property of the wiring by §6's eligibility refusal rather than assumed of the
  deployment. §11's class clause on a planner-composed
  query, its no-filtering clause and its no-recomputation clause bind unchanged, and
  §7's monotonicity is what §8 rests on.
- **Partially supersedes**
  [ADR-0092](0092-an-attested-belief-names-its-source-and-a-user-assertion-retires-it.md) — **§3's
  local-substitute clause, in exactly one scope, stated about the producer rather than
  about the file: a source this system interrogates directly, whose answer is produced at
  the instant of the read rather than replayed from an answer another source gave
  earlier.** §3 rules
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
> the other.** The planner renders each file's label from the sequence it was given; the
> loop resolves a label by parsing *n* and indexing **the very sequence it passed on this
> call**, and fetches the entry at that same position of the listing it holds — the
> projection §4 requires is positional and one for one, so the two sequences have one
> ordering and one length. Nothing but that sequence and the `ActionPlan` that already
> crosses passes between `planning` and `orchestration`: no mapping, no table, no path,
> and **no capability, because a `ShownFile` carries none** (§4).

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

> **Normative.** `Planner.plan` gains one keyword parameter, `files: Sequence[ShownFile] = ()`,
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

**Additive and defaulted, and it is nonetheless a compatibility break for every
implementation.** This is a `Protocol` change flagged as a breaking change under golden
rule 5, and this ADR does not argue itself out of that classification — exactly as
ADR-0226 §10 declined to for the return. **Every `Planner` implementation must be widened
to accept the keyword**, and an implementation that is not does not conform: `plan`'s
other inputs are keyword-only, §3's clause above has the loop pass `files` on **every**
call, and a `plan` declaring no such parameter raises `TypeError` when it is called and
fails structurally under `mypy --strict` besides. An earlier draft of this paragraph said
an existing `Planner` "conforms and means what it meant", and that was two claims run
together: what survives the widening is the **semantics**, not the signature. An
implementation that accepts the parameter and ignores its value means exactly what it
meant, which is what `()`'s default encodes — *no file is nameable on this turn* — and is
why nothing about an existing planner's behaviour has to change. Its declaration does.

**So the widening is Lane C2's, and it reaches every implementation in the tree** —
`planning/planner.py`'s model-backed planner, `ai_assistant.testing`'s canonical fake, and
the planner doubles under `tests/orchestration/`. §13 binds that lane to extend the shared
`PlannerContract` for the widened input as well, for the reason ADR-0226 §10 gives — *"A
canonical fake updated without the suite is an unverified fake"*. The default is what makes
a **caller** that names no file correct, not what makes an un-widened implementation
callable; nothing here offers source compatibility to one.

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

> **Normative.** `core/types.py` gains four frozen models and one `StrEnum`, all
> refusing mutation and unknown fields:
>
> - `SourceListingEntry` — `name: NonBlankEncodableText`, `size_bytes: int` (≥ 0),
>   `modified_at: UtcInstant`, and `handle: EncodableText`. It carries **no path, no
>   root and no directory component**: `name` is what a person calls the file, and
>   `handle` is the opaque capability of the clause below, which is never rendered
>   anywhere. It is the **fetcher-facing** value — held by `orchestration`, handed back
>   to `fetch`, and never crossing into `planning`.
> - `ShownFile` — `name: NonBlankEncodableText`, `size_bytes: int` (≥ 0) and
>   `modified_at: UtcInstant`, and **nothing else**. It is the **planner-facing**
>   projection of an entry: what §3 renders into a prompt and the only listing value
>   that crosses `Planner.plan`. It carries no capability, so a planner has none to leak.
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

> **Normative.** **Membership is decided against the authenticated payload and never by
> value equality**, and this clause is what "is among that listing's `entries`" means.
> `fetch` establishes three things and nothing else: that **this** fetcher signed the
> `token`, whose payload **commits to the listing's ordered sequence of entry `name`s**;
> that the `handle` is one this fetcher minted **for that listing**, over that entry's
> `name` and its position; and that the name stands at that position of the committed
> sequence. **The `entries` tuple the caller handed in is untrusted input rather than
> evidence**: membership in it establishes nothing on its own, because a caller can put
> any tuple there. What an implementation does with it is compare its ordered `name`s
> against the sequence the signed payload commits to, and refuse on any difference — the
> clause below. The tuple is read; it is never believed.

> **Normative.** **The token's commitment is what makes an authentic token useless over an
> altered listing.** Without it, a caller keeping a real `token` and replacing `entries`
> with `()`, with a shorter tuple, or with the same entries reordered would present a
> value whose token and handle both verify while the entry it names is not in the listing
> it is presented in — and would satisfy every other clause of this section. With the
> ordered names inside the signed payload, each of those is refused `NOT_FOUND`, because
> the sequence presented is not the sequence signed.

> **Normative.** **The commitment covers the addresses and not the display**, which is the
> other half of the same rule. The signed payload commits to the entry `name`s in order;
> it does not commit to `size_bytes` or `modified_at`. So an entry whose display fields
> were altered still verifies, is **accepted, and its altered fields are ignored** — by
> the clause two below, no fetch decision consults either — while an altered `name`, an
> altered or reordered entry sequence, and a handle minted for another listing are all
> refused. Membership is a statement about **which file of which listing** is being named,
> and that is exactly what is authenticated.

> **Normative.** **The capability does not cross the planning seam, and that is a property
> of the types rather than a rule a planner is trusted to keep.** The loop projects each
> `SourceListingEntry` of the listing it holds onto a `ShownFile` — positionally, in
> order, one for one, the whole sequence — and passes **that** to `Planner.plan`. A
> `Planner` receives no `handle`, no `token` and no `SourceListing`, so an implementation
> that rendered every field of every value it was handed, logged them, or returned them
> discloses no capability, because there is none on the value to disclose. This is the
> move the handle itself makes one clause above — *an obligation the type cannot enforce
> is a convention and not a property* — applied to the seam that **carries** the entry as
> well as to the one that verifies it. A `Fetcher` is handed the entry and the listing it
> came from, and nothing in `planning/` ever is.

> **Normative.** **An exactly copied authentic value is the same authority and is
> accepted; what is refused is a value this fetcher did not mint.** Verification is over
> the values and must be: the fourth required property below forbids the fetcher retaining
> anything, so a byte-identical copy of a `SourceListing` and one of its entries is
> indistinguishable from what was minted and no conforming implementation attempts to
> distinguish them — one that did would be deciding from retained object identity, which
> is the counting mechanism this section already rejected. Nothing is lost by accepting
> it: a copy names the same entry of the same listing inside the same deadlines, so it
> resolves to the file the loop was already shown, and §2's claim is about the
> **resolvable set** and not about object identity. So *a listing the caller assembled*
> means one whose `token` this fetcher did not mint, and *an entry the caller assembled*
> one whose `handle` this fetcher did not mint for that listing — never a faithful copy
> of one it did.

> **Normative.** **An entry's display fields are not authority, and no fetch decision is
> taken from them.** `size_bytes` and `modified_at` are what §3 renders; the file is named
> by `name`, which is what a handle is bound over, and the size is decided against the
> object `fetch` opens by the bounded read below. So a copy carrying an altered
> `size_bytes` or `modified_at` widens nothing and reaches nothing — it edits a rendering
> that has already happened, and no clause of this section consults either field.

> **Normative.** **A listing's authority expires after `fetch_listing_ttl` of elapsed
> time** — a `Settings` field with a named default of **five minutes**, strictly positive
> by §6's domain clause, refused at load rather than at the first fetch.

> **Normative.** **Two deadlines are bound into the authenticated token and a listing is
> refused once *either* has passed.** When it mints a listing the fetcher reads both a
> monotonic source and its wall clock and binds `now_monotonic + fetch_listing_ttl` and
> `now_wall + fetch_listing_ttl` into the signed payload; at `fetch` it reads both again
> and refuses if either reading is at or past its deadline. Neither deadline is rendered
> anywhere and neither outlives the process.

> **Normative.** **Neither clock alone is sufficient, which is why both bind rather than
> one being chosen.** A wall clock stepped backwards leaves a listing minted at 12:00
> inside a five-minute window an hour of real time later, and the signed token stops a
> caller extending the value but nothing stops the producer's own clock regressing under
> it. A monotonic source is immune to that and has the opposite hole: the ordinary
> `CLOCK_MONOTONIC`-style source does **not** advance while the host is suspended, so a
> host suspended for an hour resumes with a five-minute window still open. Requiring a
> suspend-inclusive source instead would put a platform capability into a `core` contract
> — Python exposes `CLOCK_BOOTTIME` on Linux and no portable equivalent — where refusing
> on whichever deadline arrives first closes both holes with no platform requirement at
> all, because a suspend that hides from one clock does not hide from the other.

> **Normative.** **`SourceListing.read_at` is not the expiry's input.** It stays what it
> is — the tz-aware instant this system listed, which §3 renders and ADR-0026 §1 governs —
> and no implementation decides expiry from the value the caller was handed rather than
> from the deadlines inside the token.

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
> against a path the fetch then re-opens.** A conforming `Fetcher` holds an **opened
> directory handle on its configured root**, acquired once when the fetcher is constructed
> and held for the fetcher's life, and opens the entry's file **relative to that handle,
> by its single final component, without following a symbolic link** —
> `openat(dirfd, name, O_NOFOLLOW | O_NONBLOCK)` or the platform equivalent. It then
> decides every remaining question — that it is a regular file, and that it is within
> `fetch_max_file_bytes` — **against the object it has open**, never against a path or a
> `stat` taken before the open.

> **Normative.** **The acquiring open never blocks, because the object's kind is not known
> until it is open.** A listed regular file can be replaced between the listing and the
> fetch by a **named pipe**, and an ordinary read-mode open of a FIFO with no writer
> **blocks until a writer arrives**. An implementation that opens and only then asks what
> it is holding would therefore wedge on exactly the transition this section's race clauses
> already admit is possible, returning neither a record nor a refusal and neither
> succeeding nor failing — the one outcome §6 says a fetch never has. So the acquiring open
> is **non-blocking** (`O_NONBLOCK`, or the platform equivalent), which costs a regular
> file nothing because the flag does not affect one, and the kind check that follows
> refuses **every** non-regular object as `NOT_A_FILE`: a FIFO, a socket, a block or
> character device, a directory. **A `Fetcher` whose acquisition can block on the object it
> is acquiring does not conform**, whatever it does after the open.

> **Normative.** **`NOT_A_FILE` is decided by what the named object is, never by which step
> discovered it.** Some kinds cannot be held at all: opening a **Unix-domain socket** by its
> pathname fails rather than yielding a descriptor there is anything to inspect — Linux
> answers `ENXIO` — and a no-follow open of a symbolic link fails likewise. An
> implementation that classifies only what it managed to open, and folds every open
> *failure* into `UNREADABLE`, would pass the directory and the FIFO arms and mis-class the
> socket while satisfying the sentence above word for word. So the rule is stated by
> outcome: **where the open refuses because the named object is not of a kind that can be
> opened as a file, the class is `NOT_A_FILE`**, and `UNREADABLE` is for a failure that is
> not about the object's kind — a permission denial, an I/O error, a resource limit. An
> implementation folding the first into the second does not conform. Which platform error
> carries which meaning is the implementing lane's to establish (§13); what is fixed here is
> where the two classes are drawn, and §14's item 4 is what fails an implementation drawing
> them elsewhere.

> **Normative.** **The root handle is a resource the composition root owns, and it is
> released on the same path every other opened resource is.** The concrete fetcher exposes
> a `close`; the `Fetcher` Protocol does **not**, staying free of lifecycle exactly as
> `MemoryStore` and this system's other stores do, so the contract keeps saying what a
> fetch is and not who shuts one down. `app/composition.py` registers that `close` among
> the resources it has opened, which releases the handle **both** when a later construction
> step fails and in the façade's ordered shutdown (ADR-0042 §2). A fetcher wired outside
> that registration would pin its root's mount for the life of the process and leak a
> descriptor per build — the failure ADR-0042 §2's *"no half-built engine leaks a
> connection"* already forecloses for every other resource this root opens, and there is no
> reason for this one to be the exception.

> **Normative.** **The open handle, and not a stored pathname, is what "under the
> configured root" means.** No conforming implementation re-derives the root from a
> pathname at fetch time, and none acquires an entry by joining a name onto one. A root
> whose *pathname* is replaced after construction is not the configured root any more: the
> handle goes on naming the directory the operator configured, and whatever now occupies
> the pathname is never reached. Where the handle's directory has been removed or can no
> longer be used, the listing is empty and every fetch refuses — never a read of the
> substitute.

> **Normative.** **The read is itself bounded, so a file that grows after its size was
> observed is refused rather than read.** An implementation reads at most
> `fetch_max_file_bytes` plus one byte from the open object and refuses as `TOO_LARGE`
> where the object supplies more; it does not decide the bound from a size it observed
> earlier and then read to end of file. `fetch_max_content_bytes` is decided the same way,
> against the extracted text as it is produced.

> **Normative.** **A file replaced between the listing and the fetch yields exactly one
> object's answer, and never a mixture.** No implementation reports a size, a
> modification instant, a type or a name from one object and content from another. Where
> the open cannot be performed under the conditions above, or the object it yields is not
> a regular file — the final component became a symbolic link, a directory, a named pipe,
> a socket or a device — the outcome is `NOT_A_FILE`; where it fails for
> any other reason, `UNREADABLE`; and neither is ever a best-effort read.

> **Normative.** **Every bound is re-applied at `fetch` and none is carried from the
> listing.** A file that grew past the size bound between the listing and the fetch is
> refused as over-size; one that was deleted is refused as absent. No implementation reads
> a bound, a type or a size off the entry it was handed.

> **Normative.** **Neither member raises for a source reason.** An absent file, an
> unreadable one, an over-size one and a failed extraction are
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

**Four properties are required of the mechanism and its spelling is the lane's**, in
ADR-0093 §10's own form: a token and a handle must be **unforgeable without state private
to the fetcher**; a handle must be **bound to the listing that minted it**; a token must
**commit to its listing's ordered entry names**, so that an authentic token cannot be
carried onto an altered listing; and verification must **not depend on the fetcher
retaining anything**, so that no listing's validity is a function of how many others have
been produced since. A keyed digest — a per-listing random identifier and the listing's
ordered entry names signed together with a key generated when the fetcher is constructed
and never leaving it, and each handle signed over that identifier, the entry's name and
its position — satisfies all four, needs no table and no eviction, and carries both
deadlines inside the same signed payload rather than in a cache. This ADR fixes the
properties and names no construction as the required one.

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
implementation because there is no way to state them as conditions on a value.

**The root is the third window, and an earlier draft of this section left it open.** That
draft resolved the root once at construction and said only that it was not re-resolved per
fetch — which stores a **pathname**, and a pathname is re-traversed in full at every open.
Protecting the final component with `O_NOFOLLOW` therefore protects exactly one component
and leaves every ancestor substitutable: list `report.txt` under the configured root, then
rename the root away and put a symbolic link of its pathname in its place pointing at an
outside directory holding another `report.txt`, and the next fetch follows the substituted
root and reads the outside file — while satisfying the membership check, the deadlines,
the final-component clause and the bounded read, every one of them. The defect is the
traversal, not the number of components guarded, so the fix removes the traversal: an
opened directory handle is a reference to the directory itself rather than to a name for
it, so containment stops being a check performed against a path and becomes a property of
where the open starts. That is also why the against-the-object list above no longer
carries "lies under the root": with the handle, that question is answered by construction
and there is nothing left to decide.

§14 owes a test for each of the three transitions rather than for the static cases alone,
which is the difference between asserting the property and asserting the easy half of it.

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

> **Normative.** **The attested source is the configured root itself, and never whatever
> wrote the document.** `reported_by` names the fetcher's own source instance, and no
> implementation attributes a fetched record to a system a file may have arrived from — not
> a vendor, not a sender, not a service that synced it. What the record attributes to that
> source is the **current content of a document the root holds**, and it makes no claim at
> all about who composed that content or when.

> **Normative.** **`reported_at` is the fetch instant because the root is interrogated
> live and answers in the same instant, and this is the scope in which ADR-0092 §3's
> local-substitute clause is superseded.** The scope is a property of **the producer** and
> not of the file it reads: a source this system interrogates **directly**, whose answer is
> produced at the instant of the read rather than replayed from an answer some other source
> gave earlier. A configured local root is that by construction — the filesystem is asked
> what a document holds now and answers now — so "when the source said so" and "when we read
> it" are one event rather than two facts of which one stands in for the other.
> **It reaches nothing else.** A source that declares its own report time uses that time;
> and a kind whose fetch retrieves a remote source's earlier answer, or replays one from a
> cache of its own, is outside this scope entirely and ADR-0092 §3 binds it as written.

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

**The scope is a property of the producer because no scope stated about the file is
decidable, and an earlier draft of this section stated it about the file.** That draft
superseded §3 for *"a source read live, at the instant of its report, holding no claim made
earlier"* — which reads as a fact about the document, and §6 admits every supported direct
child of the root without distinction. A note the owner typed yesterday and a PDF a service
synced this morning sit alike inside that population, and no `Fetcher` can tell them apart:
there is no source-origin field on a file and nothing in the contract that could carry one.
A scope an implementation cannot decide is not a scope, and both review lenses reached that
from opposite sides on the same round — one that an ordinary existing file *does* hold an
earlier claim and so falls outside the stated scope while the rule still applies to it, the
other that the fetcher has no classification by which to keep a synced copy out.

**The repair is not a classifier, and adding one would be the wrong move.** What was
mis-stated is not the boundary but the identity of the thing being attested. This record
does not say the *document* reported anything at the fetch instant, and it does not say the
document's author did; it says the **root** — "the owner's documents folder" — reported, at
that instant, what the document it holds now contains. That is equally true of a file typed
yesterday and of one synced this morning, which is why the boundary can be drawn where an
implementation can see it: at what the producer *is*, which the fetcher knows by
construction, rather than at where a file came from, which it cannot know at all. A
classifier over file origin would be a guess dressed as a fact, and it would put the
attestation's honesty at the mercy of it.

**This is why the mtime is still forbidden and why the read instant is not the same
mistake.** ADR-0092 §3's failure mode is *"a true statement about us and a false one about
the source"* — a value that is *nearly* right. An mtime claims the source's claim was made
at the last local write, and a copy, a restore or a `touch` falsifies that while the claim
stays where it was. The read instant claims the root answered when we asked it, and nothing
can falsify that: it is not a proxy for the source's clock, it **is** the source's clock,
because the source is the local filesystem and the report is the answer to this system's
own call. What §3 forbids is substituting a local timestamp for an answer another source
produced at a time we do not know; here there is no other source and no earlier time being
stood in for. The read instant is, uniquely among the candidates, true by construction
rather than by luck.

**What the record therefore does not carry, and where the honest gap is.** Nothing in this
decision says when a document's *words* were composed. That fact exists, the mtime is not
it, no format on this rung is required to declare one, and this ADR invents none: a
consumer asking "when did the folder tell you this?" is answered exactly, and one asking
"when was it written?" is answered by nothing on the record — which is the correct answer
rather than a missing one, on §3's own reasoning that *"the capability is bounded by what
sources can actually say"*. §15 defers a format-declared instant by name, with the consumer
that would fire it.

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

> **Normative.** **The root's reads must not leave the device, and a `Fetcher` refuses to
> be constructed where that cannot be established.** The check runs **when the fetcher is
> constructed** — beside the bounds below and for their reason (ADR-0093 §5, refused at
> load rather than at the first fetch) — and it is **fail-closed**: what is refused is not
> merely a root the platform reports as remote, but **every root whose locality the
> platform does not affirmatively establish**. A refused root is a configuration error that
> stops the deployment, never an empty listing and never a `FetchRefusal`; a deployment
> with no root configured is unaffected, because there is nothing to check.

> **Normative.** **Eligibility is decided in two fail-closed stages, and no ordering of
> checks and opens establishes it — the resolution itself must be atomic.** Deciding
> locality against a **pathname** and then opening it is the defect §4 rules out one clause
> earlier: the configured root can be replaced in the interval, so the constructor binds
> its long-lived handle to storage it never checked. Deciding it against the **opened
> handle** first is right about the object and wrong about the order: the first `open` of a
> directory on an NFS or SMB mount resolves remote filesystem metadata, and on ext4 over an
> iSCSI or NBD volume it issues remote block I/O, so a constructor that opens before it
> admits has performed the very read the refusal exists to prevent. And **checking a table
> and then opening a component leaves the same window at every component it walks**: a
> mount landing between a component's check and its open is entered before anything refuses
> it, because refusing to *follow a symbolic link* is not refusing to *cross a mount*. So
> what §6 requires is not a better order but a resolution the platform performs atomically.

> **Normative.** **Stage 1 — admission — reads the platform's own mount and device tables
> and opens nothing.** The constructor identifies the mount the configured path falls
> under and establishes that **both** its filesystem and its backing device are local,
> refusing otherwise. Nothing is opened in this stage, so a root that is remote **as
> configured** is refused having been touched by nothing at all — and the tables' answer is
> a **claim to be checked against an opened object**, never the thing locality rests on.

> **Normative.** **Stage 2 — acquisition — opens the resolution's start, checks it against
> the claim, and resolves the rest atomically.** Construction opens the **start** — the
> root of the mount stage 1 named — takes that open object's **device identity from its
> handle**, and **refuses unless it matches what stage 1 admitted**. It then resolves the
> remainder of the configured path **relative to that handle, in one operation the platform
> makes atomic**, which **refuses rather than resolves** if resolution would cross a mount
> point, follow a symbolic link at any component, or escape above the start. The handle
> that operation returns is the root handle §4 anchors every fetch to; nothing is
> re-derived from a path afterwards.

> **Normative.** **This is what closes the window at every component, and the reason is one
> sentence: a resolution that refuses to cross a mount cannot reach an object on a
> filesystem other than the one it started on.** So the device identity established against
> the start's handle is the device identity of **every object the resolution can reach**,
> and the tables end up vouching for nothing that was opened — they name a mount, and the
> handle is what says what that mount is. A mount landing on any intermediate component
> mid-resolution is refused rather than entered; a symbolic link anywhere in the path is
> refused rather than followed; and there is no check-then-open pair left for anything to
> land between.

> **Normative.** **The property is required; no construction is.** In ADR-0093 §10's form
> and §4's, what is fixed here is that the descent refuses on mount crossing, on symbolic
> links and on escape above its start, and that it does so as one operation rather than as
> a sequence a race can be inserted into. **It is named achievable rather than
> aspirational**, because a requirement no platform is known to satisfy would be a
> deferral wearing a decision's clothes: Linux's `openat2` refuses in the kernel, during
> resolution, under `RESOLVE_NO_XDEV`, `RESOLVE_NO_SYMLINKS` and `RESOLVE_BENEATH`. That
> is evidence, not a requirement — the implementing lane owes the property, and how it
> reaches it is §13's.

> **Normative.** **Where a platform offers no such operation the mechanism is unavailable
> on it, and this is not a new rule.** It is this section's standing clause — *a platform
> that will not answer the question leaves the mechanism simply unavailable* — reaching one
> layer further. No lane substitutes a sequence of checks and opens for the atomic
> operation on the ground that it is nearly as good; nearly as good is the defect this
> clause exists to refuse, and the failure mode stays a legitimate configuration refused
> rather than a remote-backed one admitted.

> **Normative.** **One open precedes locality-against-an-object, it is irreducible, and it
> is stated rather than hidden.** No ordering removes it: a handle is the only thing an
> object's identity can be taken from, and a handle can only be got by opening something.
> What this decision does is make that one open as small as the argument allows — a single
> directory open of a **mount root the platform's own tables describe as local**, no
> component of the configured path among it, nothing read through it, refused on the
> device-identity mismatch, and survived by no handle. In the racing case it contacts a
> filesystem substituted under that mount root and is refused immediately; that is the
> fixed point of this argument rather than a layer left unexamined.

> **Normative.** **That one open is not the egress ADR-0017 §1 governs, and the scope is a
> ruling this ADR cites rather than an argument it makes.** Ruled by the owner on
> 2026-09-03 (batch #1996, comment 5532194014): §1 does **not** reach the remote metadata
> I/O caused by resolving an **operator-configured pathname at construction** — no user
> content, no model-influenced byte, nothing read through it, no handle surviving the
> refusal — and that includes the racing case above, where a mount is substituted under the
> configured path between stage 1's read of the tables and stage 2's open. The ground is
> that §1 exists to stop **this system** leaking the user's data, not to defend against a
> principal who already holds mount privilege on the machine and who, in the owner's words,
> *"could probably do a lot worse stuff already"*. The precedent is this system's own
> startup: the hub opens its data directory, its SQLite stores and its keyring on configured
> paths at every start, and the calendar and email readers open configured local sources,
> none of which this corpus has ever read as an egress.

> **Normative.** **The scope is exactly that and no wider, which is why it is stated as a
> bound rather than as a permission.** It covers **one** open, of **one** mount root, at
> **construction**, of a path an **operator** configured. It does not cover a listing, a
> fetch, a read of any content, any call a plan or a model can reach, or any open at all
> after the device identity has been checked — every one of which happens through the handle
> stage 2 bound, on a resolution that crosses no mount. And it changes **no clause of the
> mechanism**: the two stages, the tables-open-nothing rule, the check of the opened start
> against what the tables claimed, and the atomic no-cross, no-symlink, beneath-only descent
> all stand exactly as decided above. The ruling settled what §1 reaches, not what this ADR
> should build, and the mechanism is already the tightest a userspace program can be given.

> **Normative.** **Eligibility is decided over the whole backing chain and not over the
> filesystem's type alone.** A filesystem type is necessary and **not sufficient**: an
> ext4 or XFS volume on an iSCSI, NBD, NVMe-oF or otherwise network-attached block device
> reports an ordinary local type in the platform's mount table while every read of it
> traverses a network, and admitting it would be the same ADR-0017 §1 egress the NFS case
> is, reached one layer down. So the eligibility a `Fetcher` requires is that **both** the
> filesystem serving the root **and the device backing it** are established as local, and
> a chain the platform will not report through to that conclusion is refused.

> **Normative.** **The property is fixed here and the procedure is the implementing
> lane's**, in ADR-0093 §10's form and §4's — but no construction is offered here as
> sufficient, because the obvious one is not. **The failure mode is a legitimate local
> configuration refused until the lane can establish it** — a configuration error a
> deployment can see and fix — and never a remote-backed one silently admitted. Where a
> platform will not answer the question at all, this mechanism is simply unavailable on it,
> which is the correct outcome rather than a gap to fill with an assumption.

> **Normative.** **This is ADR-0017 §1 honoured, not a precaution.** Its rule is that
> *"User data may leave the device only from `models/` or from a designated integration
> seam inside `tools/`; every other egress is a bug"*, and a read served over a network —
> NFS, SMB, a FUSE-backed remote drive, or a local filesystem sitting on a network-attached
> block device — leaves the device from `readers/`, which is neither. ADR-0084 §1
> settled the same question for this system's own transport — a non-loopback hop *"owes its
> own ratified egress decision, and it cannot be reached by swapping an address family"* —
> and a root swapped onto network-backed storage is that move by another route, at whichever
> layer the swap is made. This ADR
> pre-authorises no such egress and does not seek to; it makes the configuration that would
> perform one **unwireable**, and the word is meant exactly and no wider than it is true:
> **no `Fetcher` is constructed over such a root, and no read of the configured path is
> performed in refusing a root that is remote as configured** — stage 1 decides from the
> platform's own tables, so that refusal costs the network nothing. What "unwireable" does
> **not** claim is that no byte can cross under an adversary who substitutes a mount
> mid-construction: the one open above can contact such a substitution and is refused on
> the device-identity mismatch, and that contact is outside §1's reach under the ruling
> recorded above — a scope this ADR cites rather than an exception it grants itself. **Every
> read the mechanism performs after construction is taken on the checked handle**, so the
> word holds entire over the listing, the fetch and everything a turn can reach.

> **Normative.** The listing is the root's **direct children only** — no recursion, no
> subdirectory traversal, no following of symbolic links out of the root — ordered
> **most recently modified first**, capped at `fetch_listing_max_entries` with a named
> default of **40**, and restricted to the readable types below.

> **Normative.** **The first rung reads plain text, Markdown and PDF, and nothing else.**
> Any other file is **not listed**, and there is therefore no authentic entry naming one:
> an entry a caller assembles for a `.docx` under the root is refused `NOT_FOUND` by §4's
> membership clause, exactly as an entry for a file the cap left out or for one that never
> existed is. A later format is admitted by the ADR that decides it, states what its
> extraction is, and says whether that extraction declares a report time (§5).

> **Normative.** **There is no `UNSUPPORTED_TYPE` refusal, and its absence is a decision
> rather than an omission.** The type allow-list is applied where the listing is built, so
> the only caller who can name an unsupported file is one presenting an entry this fetcher
> never minted — and §4 rules that refusal `NOT_FOUND`, *"deliberately the same class an
> absent file yields, so that it discloses nothing about whether a guessed name exists
> under the root"*. A distinct class for the unsupported case would be that disclosure
> restored: it would answer *a file of that name is there, and it is a `.docx`* to a caller
> holding nothing but a guess. So the class is not carried, and the general rule is the
> clause below.

> **Normative.** Two size bounds, both `Settings` fields with named defaults, both refused
> at load rather than at the first fetch (ADR-0093 §5): `fetch_max_file_bytes`, the file's
> size on disk, default **4 MiB**, which bounds the read and the extraction's cost; and
> `fetch_max_content_bytes`, the extracted text as the prompt will carry it, default
> **32 KiB**, which bounds what reaches the prompt — roughly 32,000 characters of English,
> about 5,400 CJK code points or about 2,700 emoji, by the clause below.

> **Normative.** **Every `Settings` field this ADR adds has a stated domain, and a value
> outside it is a load-time configuration error.** `fetch_listing_ttl` is **strictly
> positive**; `fetch_listing_max_entries`, `fetch_max_file_bytes` and
> `fetch_max_content_bytes` are integers of **at least 1**. Zero and negative values are
> refused rather than given a meaning. A zero entry cap is a mechanism that shows nothing
> while appearing configured, which §3 rules a listing may not be made to mean; and a
> negative one is worse than meaningless — *capped at −1* has no reading, while the
> obvious Python spelling of a cap, `entries[:-1]`, quietly yields all but the last
> entry, so a bound would be defeated by a configuration value rather than enforced by
> one. The root's own field is not in this class: its named default is unset, and unset
> means the mechanism is off (this section's first clause). Each refusal is `Settings`'s
> own, at load rather than at the first fetch (ADR-0093 §5), and stops the deployment
> exactly as an ineligible root does.

> **Normative.** **`fetch_max_content_bytes` is counted on the *quoted rendering* of the
> extracted text — `json.dumps` at its default `ensure_ascii=True`, its two delimiters
> included — and never on the source.** That rendering is pure ASCII, so its character
> count and its byte count are one number and the field's name stays honest. An
> implementation enforces the bound **while extracting** rather than after, so a file
> beyond it is refused without the whole of its text having been materialised.

> **Normative.** **No implementation bounds this on source characters or on source bytes**,
> and the reason is ADR-0222 §4's, which ruled the same question for a rendered reply: at
> `ensure_ascii=True` *"a newline costs two output characters, a BMP code point six and an
> astral one — an emoji — twelve, because `json.dumps` writes it as two surrogate escapes
> rather than one. A ceiling on **source** characters would admit a span six or twelve times
> this long while claiming to admit this much; counted on the output there is nothing left
> to get wrong."* A source-byte bound is the same defect one unit over: 32 KiB of emoji is
> 8,192 code points and renders as 96 KiB of escapes, so §6's claim that this bound is what
> reaches the prompt would be false by a factor of three on exactly the input an attacker
> would choose.

> **Normative.** **The transform is written out at the fetcher rather than imported**,
> which is ADR-0222 §4's own instruction where three subsystems already hold their own
> copy: what is shared is this ADR's number and that section's, not a module across a
> boundary golden rule 1 forbids crossing. A fetcher holding a fourth copy is the
> established shape and not a new coupling.

> **Normative.** **A file beyond the bound is refused and never elided**, which is where
> this departs from ADR-0222 §4 and the difference is the point: a reply exists and must
> be rendered somehow, so §4 keeps its longest fitting prefix and marks the elision; a file
> need not be fetched at all, and the refuse-never-truncate clause below says why an
> abridged document is the worse answer.

> **Normative.** **A bound is enforced by refusing, never by truncating.** A file over
> either bound yields a refusal and no record. No implementation returns a prefix, a
> first page, a first *n* bytes, an abridgement or a "first part of" record, and none
> records a truncation flag in place of refusing.

> **Normative.** `FetchRefusal`'s members are `NOT_FOUND`, `NOT_A_FILE`, `UNREADABLE`,
> `TOO_LARGE` and `EXTRACTION_FAILED`. The enumeration is closed and no lane adds a sixth
> without the ADR that decides it. A refusal names a **class** and carries no path, no
> name, no excerpt and no message from an underlying library.

> **Normative.** **Every member is reachable over a real filesystem from an authentic
> entry, and a class no authenticated fetch could produce is not carried.** Each of the
> five is reached through the seam §4 permits — a listed file deleted, replaced by a
> directory, made unreadable, or grown past the bound between the listing and the fetch,
> and a listed file of a supported format whose extraction fails — which is why §6
> re-applies every bound at `fetch` and carries none from the listing. §14's item 9
> asserts the five arm for arm, and the clause is stated because an enumeration is where
> a decision most easily acquires a member that only its own prose can reach.

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
> close on a filesystem: **this system composes no outward request and names no
> destination on the fetch path**, and this ADR authorises no egress, designates no seam,
> adds no `DestinationProtocol` member and is cited toward none of those (ADR-0154 §4, §7;
> ADR-0017 §1). (c) The one outward path a
> steered plan can reach is the **egress seam**, and a turn that fetched has stamped its
> capture, so ADR-0223 §6's allow applies and *"every subsequent turn of that
> conversation that reaches the egress seam is a confirmation rather than an allow"*.

> **Normative.** **(b) is what §6's eligibility refusal exists to keep true**, and a
> network-backed root is why it is a refusal rather than a documented condition. On a root
> whose reads cross a network — an NFS or SMB mount, a FUSE-backed remote drive, or an ext4
> volume on an iSCSI or NBD device — the fetch would still compose no request and name no
> destination — but **an observer of that storage would see which entry a turn opened**, and
> a revising turn's second ask may be composed over the first fetch's content (§7). That is
> a data-steered signal reaching a party off this device without passing the egress seam.
> It would be bounded — at most **which of the listing's at-most-`fetch_listing_max_entries`
> entries was read**, under five bits per servicing at the default of 40, never a name the
> model composed (§2 admits no composed address), never a payload this system assembled
> (there is no request body to put one in), and never an endpoint a plan selected — and
> **bounded is not contained**. ADR-0017 §1 admits no such egress from `readers/` whatever
> its width, and this ADR pre-authorises none. So the configuration is refused at
> construction rather than documented, argued about, or left to operator discipline.

> **Normative.** **What that refusal contains is the fetch path, and §6's construction-time
> residual sits outside this property rather than unstated inside it.** The containment
> above is a claim about what a **steered turn** can reach: every listing and every fetch
> resolves through the handle stage 2 opened and checked, on a descent that crosses no
> mount, so no turn of this system reads storage an observer off this device can watch. The
> one open that precedes that check happens **once, at construction, before any turn
> exists**, on a pathname an operator configured and no model influenced, and nothing is
> read through it; under the owner's ruling of 2026-09-03 (#1996, comment 5532194014) it is
> not the egress ADR-0017 §1 governs. So (b) holds unqualified where it is claimed — on the
> fetch path — and the residual is disclosed in §6 where it occurs, rather than being
> carried silently by a word here.

> **Normative.** **Three things would break it, and each is named so that a later lane
> meets it as a condition rather than discovers it.** A kind whose fetch itself leaves the
> device — that is #1996's Lane B, deferred in §15, and this ADR decides nothing for it. A
> fetch whose address space is composed by a model rather than shown to it, which §2
> forbids. And any relaxation of ADR-0223 §6's stamp or ADR-0154 §4's
> standing-authorisation floor, neither of which this ADR touches or may be cited toward.
> **A network-backed root is not a fourth**, because §6 makes a root that is remote **as
> configured** unwireable rather than discouraged, and refuses a substituted one on the
> device-identity mismatch before any component of the configured path is resolved through
> it; a relaxation of *that* refusal is the fourth by another name and needs the ratified
> egress decision ADR-0084 §1 says such a hop owes.

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
argument through which a name can be expressed; and it cannot cause this system to compose
an outward request on the read path, because the read path is a filesystem call and there
is no request to compose. And it cannot reach a filesystem whose reads would leave the
device, because §6 refuses to construct a fetcher on one — which is what makes "the owner's
own disk" a property of the wiring rather than a description of the intended deployment.

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
`Fetcher`; `core/types.py`'s `SourceListingEntry`, `ShownFile`, `SourceListing`, `FetchOutcome`,
`FetchRefusal`, `ReadKind.LOCAL_FILE` and `ReadAsk.entry` with its validator arm; the
`Settings` fields of §6 and §4 with their named defaults, their stated domains and their
load-time refusal;
§6's **eligibility refusal on the root**, satisfying its fail-closed property over the
backing chain in **both** of §6's stages — admitting the root from the platform's mount and
device tables with nothing opened at all, then checking the opened mount root's device
identity against that claim and resolving the remainder of the configured path relative to
its handle in **one atomic operation** that refuses on a mount crossing, a symbolic link at
any component, or an escape above the start — in the concrete fetcher and not in `core`;
§4's token-and-handle mechanism, satisfying all four of its stated properties and its
expiry, **in the fetcher and not in `core`** — the types carry the values and the fetcher
owns what makes them unforgeable; the **shared conformance suite** for `Fetcher`; the
**canonical fake** in `ai_assistant.testing`, which mints and verifies its own tokens and
handles so the suite's membership clauses are not vacuous on it; the concrete local-file
fetcher in `ai_assistant/readers/`, whose acquisition satisfies §4's race clauses; the
PDF extraction library's evaluation and adoption under ADR-0024; and `app/composition.py`'s
wiring, which constructs a `Fetcher` only where a root is configured **and registers its
`close` among the resources it has opened**, so the root handle is released on a later
construction failure and in the ordered shutdown alike (ADR-0042 §2).

> **Normative.** Lane C1 ships the **triad** — Protocol, shared conformance suite and
> canonical fake — **together with its primary production implementation**, under
> ADR-0137 §2. It is one lane and not two: the slice fails §1's single-subsystem test only
> because the contract and its first concrete are separated by that contract, which is the
> case §2 exists for. Splitting it would land a `Fetcher` no implementation had been
> written against, which is the failure `CONTRIBUTING.md` → "Adding a Protocol" names.

> **Normative.** **The primary production implementation here is the concrete fetcher and
> not the servicer, and the reading is ADR-0137's own.** §5 of that ADR quotes the sentence
> §2 widens — a triad *"stays a small diff because it is a contract and its guardrails,
> with no **production** implementation attached (the canonical fake is an implementation,
> but a test-only one)"* — so what §2 attaches to the triad is the implementation the fake
> stands in for. §2's *"the consumer whose demands shape the contract, not the one that is
> cheapest to write"* chooses **among** such implementations rather than naming a caller,
> and on this contract the demands that shape it are §4's unforgeable token and handle and
> §6's two-stage locality refusal — both the fetcher's, and neither exercisable by
> `orchestration`. Pairing C3 in instead would put new machinery into a third subsystem,
> which §1 forbids and §2 declines to license (*"any other cross-subsystem pairing remains
> outside the exception"*); and C3 is **adaptation** under §1 in any case, because
> `orchestration/reads.py` already holds the one servicer and the two existing kinds'
> branches and this kind adds a third under the same budget and the same audit.

> **Normative.** The conformance suite holds the clauses expressible **without a source**:
> `name` is stable and non-empty; a `SourceListing`'s `source` equals `name`; `read_at` is
> tz-aware; an **empty listing is a valid, successful listing** and every clause holds on
> it; a `FetchOutcome` carries a record **or** a refusal and never both or neither; a
> minted record is `SEMANTIC`, `EXTERNAL`-sourced, carries an `Attestation` whose
> `reported_by` equals `name`, and carries an empty `evidence`; **an entry the test
> assembles itself is refused**, and so is one built by copying a listed entry's `name`,
> `size_bytes` and `modified_at` onto a handle of the test's own choosing, and so is a
> listing the test assembled around a token of its own, and so is an entry of listing A
> presented with listing B's token, and so is **an authentic entry presented in a listing
> carrying its own authentic token but an altered `entries`** — emptied, shortened,
> reordered, or with an entry's `name` changed — which is the clause that fails any
> implementation whose token does not commit to the ordered names; while **a faithful copy
> of an authentic listing and entry is fetched**, and so is one whose `size_bytes` or
> `modified_at` was altered, the two clauses in the other direction, which fail an
> implementation deciding from retained object identity or from display fields; **a listing past either of §4's deadlines is refused** on fake clocks the suite
> drives while one inside both is not, **a wall clock stepped backwards does not extend
> one and a frozen monotonic source does not either**, and **producing further listings
> invalidates none of them**; **no
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
> `FetchRefusal` member); that a path escaping the root is refused and that the three race
> transitions of §4 are refused (a concrete fetcher's test over a real filesystem, and it
> owes `..`, a separator in `name`, a symlink out of the root, a replacement between
> validation and acquisition, a replacement by a **named pipe with no writer** between
> them, which must refuse under a deadline rather than block on the open, a growth past
> the bound between them, a replacement of
> the **root's own pathname** by a symlink to an outside directory between the listing and
> the fetch, and — at construction — a mount landing on the mount root between the tables'
> read and its open, and a mount landing on an intermediate component mid-resolution
> (§6) — a generic suite cannot replace an arbitrary fetcher's root, so these arms are the
> concrete fetcher's and not the suite's); and that the
> listing is ordered most-recently-modified-first and capped. Each is named here so the
> lane does not read its absence from the suite as its absence from the contract.

**Lane C2 — the listing across the seam and the planner's emission.** `Planner.plan`'s
`files` parameter and its documented meaning; the loop reading the listing once per turn,
projecting its entries onto `ShownFile`s positionally (§4) and passing that same sequence
to both calls, retaining the `SourceListing` itself in `orchestration`; §2's `F`-labelled
rendering of it in
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
   the test assembled around a real entry but carrying a token of its own. **And the
   tamper arm the other two do not reach**: an authentic entry presented inside a listing
   that keeps its own authentic token but whose `entries` was emptied, shortened,
   reordered, or had an entry's `name` changed — refused `NOT_FOUND` in every case, which
   is the arm that fails any implementation whose token does not commit to the listing's
   ordered names, and which such an implementation would otherwise pass the whole of this
   item on. **And two arms in the other direction**: a byte-identical copy of an authentic
   listing and one of its entries **fetches**, and so does one whose `size_bytes` or
   `modified_at` was altered — the record it mints being of the file `name` addresses,
   with no field of the record taken from the altered values — because the authority is
   the authenticated payload and not the object, and an implementation refusing either
   would be deciding from retained object identity or from display fields, both of which
   §4 forbids. Asserted at the `Fetcher` seam, because it is a
   property of the contract and not of the loop that happens to call it.
4. **The five race transitions are refused.** Over a real filesystem, deterministically
   sequenced so the transition lands **between** the fetcher's validation and its
   acquisition: a supported regular file replaced by a symbolic link pointing outside the
   root, which is refused `NOT_A_FILE` and reads nothing from the link's target; a file
   that grows past `fetch_max_file_bytes` after its size was observed, which is refused
   `TOO_LARGE` and puts no prefix of the grown content anywhere; and **the root's own
   pathname replaced by a symbolic link to an outside directory holding a file of the same
   name**, between the listing and the fetch, where the fetch either reads the original
   object through the handle it holds or refuses — and in **no** arm does the outside
   file's distinctive text reach the supply or the reply. None of the three yields a record
   mixing one object's metadata with another's content. The third arm is the one that fails
   on any implementation storing the root as a pathname and re-joining a name onto it.
   **And a fourth arm, for the transition that would hang rather than mis-read**: a
   supported regular file replaced by a **named pipe with no writer**, where the fetch
   refuses `NOT_A_FILE` **within the turn** rather than blocking on the open — asserted
   under a deadline the test fails on, since a hang is not a wrong answer this suite could
   otherwise observe. This is the arm that fails on any implementation whose acquiring open
   is not non-blocking, and it is the one an assertion about the *returned* class cannot
   reach on its own.
   **And a fifth arm, for the kind that cannot be held at all**: a supported regular file
   replaced by a **Unix-domain socket**, whose open fails rather than yielding anything to
   inspect, and which is refused `NOT_A_FILE` and **not** `UNREADABLE`. This is the arm that
   fails on any implementation classifying only what it managed to open and folding every
   open failure into `UNREADABLE` — which passes the directory and FIFO arms while
   mis-classing this one.
5. **A listing expires once either deadline passes, and on nothing else.** Four arms,
   each deterministic over fake clocks the test drives. A listing inside both deadlines is
   fetched, and one past both is refused `NOT_FOUND`. **A backward wall clock does not
   extend one:** minted, the wall clock stepped *backwards* by an hour, the monotonic
   source advanced past the TTL — still refused, the arm that fails on any implementation
   deciding from `read_at`. **A suspended host does not extend one either:** minted, the
   monotonic source *frozen* while the wall clock advances past the TTL — still refused,
   the arm that fails on any implementation deciding from a monotonic source alone. And
   **nine listings are produced before any of them is fetched from**, after which every one
   of the nine fetches its own entry successfully — the arm that fails on any
   implementation whose validity is a function of how many listings have been produced
   since. Each of the middle three is here because a successive draft of §4 had exactly
   that defect.
6. **A turn whose supply sufficed pays no fetch.** The plan carries no request, the fetcher
   is asked for no file, the supply is byte-for-byte the three groups it was, and the audit
   records a turn on which the trigger did not fire. Asserted over the audit and the supply,
   not over a mock's call count.
7. **The label is an ordinal into the listing the loop passed.** `F2` resolves to the second
   entry of that turn's listing and to nothing else; the same planner output against a
   different listing resolves to a different entry; the two packages agree with no shared
   table, asserted by resolving an ask against a listing the test constructs directly; and
   the same label resolves to the same entry on **both** planner calls of a revising turn.
   **And no listing survives its turn**, asserted over **two consecutive turns** of one
   conversation whose roots have changed between them, with the second turn beginning
   **inside** `fetch_listing_ttl` of the first — the interval in which a retained listing
   would still verify, so the arm turns on §3's discipline and not on the expiry. Turn 2
   renders its own listing, `F1` on turn 2 fetches turn 2's first entry, and turn 1's
   entries, token and handles appear in no prompt, no ask resolution and no fetch of turn 2.
   This is the arm that fails on an implementation caching a listing across turns, which §15
   names as the residual a turn identity on the contract would close.
8. **A file over either bound is refused, and nothing is truncated.** A file over
   `fetch_max_file_bytes` and a file whose extracted text is over `fetch_max_content_bytes`
   each yield a refusal, add no record, fail no turn, and put no prefix of the text
   anywhere in the supply or the reply. Asserted over the supply and over the audit's
   refusal class. **The content bound is counted on the quoted rendering**, asserted with
   three arms over **astral** code points — emoji, which `json.dumps` writes as two
   surrogate escapes each: text whose rendering is exactly `fetch_max_content_bytes` is
   fetched; text whose rendering is one character over is refused; and, through the
   **production renderer**, the span that at-limit record contributes to the assembled
   prompt is within the bound. An implementation counting source characters or source
   bytes passes the first arm and fails the other two.
9. **Every refusal class is reachable from a real source, through an authentic entry.**
   One arm per `FetchRefusal` member, over a real filesystem, each reached from an entry
   the fetcher itself minted: a listed file deleted before the fetch; one replaced by a
   directory; one made unreadable by permission; one grown past `fetch_max_file_bytes`; and
   a listed file of a supported format whose extraction fails. This is the concrete
   fetcher's test and not the suite's (§13). **And the arm in the other direction**: a
   `.docx` under the root appears in no listing, and an entry assembled for it is refused
   `NOT_FOUND` and not by a class of its own — which is item 3's seam asserted for the
   unsupported case and the arm that fails any implementation carrying a sixth member.
10. **A fetched record carries the external mark, and the conversation asks thereafter.** A
    bounded-audience turn that fetches captures an episode whose `derived_from_external` is
    `True`; the same turn's `SelectionOrigin` carries `planned_with_external_content`; and a
    **subsequent** turn of that conversation reaching the egress seam is a confirmation
    rather than an allow. This is the assertion standing between this rung and #1844's
    exfiltration channel, and it is asserted end to end rather than at the predicate.
    **And the fetch is not itself an egress**, asserted on the same turn: servicing the ask
    engages no `DestinationProtocol` member, requires no confirmation of its own and routes
    through no egress seam, which is §8's property (b) asserted rather than only stated.
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
15. **The audit copies no address, and no capability reaches a prompt, a log, an audit or
    a record.** A turn that
    fetches a file whose name carries a distinctive string emits a record in which that
    string appears nowhere — no path, no name, no extension, no size, no excerpt — the
    refusal field is a closed-enumeration member or absent, and the ambient correlation id
    is the only identifier on the event. Asserted over the emitted event's own fields, not
    over the redaction net. Separately, the `token` and the entry handles of that turn's
    listing appear in **no** prompt the turn assembled, in no log line and on no field of
    the record the fetch minted — the invariant being where a capability may **go**, not
    that it never leaves the fetcher, since §4 has the fetcher hand entries to
    `orchestration` and take them back on `fetch`.
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
20. **No capability crosses the planner seam, and the projection is positional.** A turn
    whose listing holds several entries: the value passed to `Planner.plan` is a sequence
    of `ShownFile`, one per entry in the listing's own order, and `SourceListingEntry`,
    `SourceListing`, `token` and `handle` reach `planning/` in no argument of any call.
    Asserted structurally — the planner-facing type has no field a capability could sit
    in — and behaviourally: a planner double that renders **every field of every value it
    receives** into its prompt produces a prompt in which no token and no handle of that
    turn appears. And `F`*n* fetches the entry at position *n* of the listing the loop
    holds, which is the arm that fails on any implementation projecting a filtered,
    reordered or partial sequence.
21. **An out-of-domain bound does not load.** One arm per field — a zero and a negative
    `fetch_listing_ttl`, `fetch_listing_max_entries`, `fetch_max_file_bytes` and
    `fetch_max_content_bytes` — each refused when `Settings` is constructed, before any
    fetcher is built and before any filesystem call, and each a configuration error that
    stops the deployment rather than an empty listing, a `FetchRefusal` or a degraded
    turn. This is the arm that fails on any implementation carrying an unchecked bound
    through to a slice.
22. **A root whose reads would leave the device does not wire, one whose locality is
    merely unproven does not either, and refusing one reads nothing through it.** Nine arms
    at construction, over a fetcher whose view of the platform's mount and device
    information the test supplies. Four decide admission: a root on a filesystem the
    platform reports as network-attached refuses; a root whose filesystem type is
    **unrecognised** refuses, which is the fail-closed arm that fails on any implementation
    written as a deny-list; **a root on an allow-listed local filesystem type whose backing
    device is network-attached — ext4 on an iSCSI or NBD volume — refuses**, which is the
    arm that fails on any implementation deciding eligibility from the mount table's type
    alone; and a root on an ordinary local filesystem over a local device constructs. Each
    refusal is a configuration error that stops construction — no `Fetcher` exists
    afterwards — and not an empty listing, not a `FetchRefusal` and not a degraded turn.
    A deployment with no root configured constructs no fetcher and reaches no arm.
    **A fifth arm asserts that the refusal cost no access**: with the filesystem calls the
    constructor makes instrumented, a root the platform reports as network-attached is
    refused and **no filesystem call at all is issued** — not on the configured path, not
    on anything beneath it, and not on the mount root — because stage 1 decides from the
    tables and opens nothing. This is §6 stage 1 asserted rather than only stated, and it
    is the arm that fails on any implementation opening before it admits.
    **A sixth arm, over a real filesystem, for the race at the start**: a mount lands on
    the mount root stage 1 named, deterministically sequenced **between** the tables' read
    and stage 2's open of it. Construction refuses on the device-identity mismatch taken
    from the handle, resolves no component of the configured path through the substituted
    mount, and survives with no handle. This is the arm that fails on any implementation
    treating the tables' answer as the locality rather than as a claim to check.
    **A seventh arm, for a symbolic link inside the configured path**: a root whose
    configured path has an ancestor component that is a symbolic link to a remote-backed
    directory is refused, **and, instrumented, nothing crosses the link** — no open of its
    target, of anything beneath that target, or of the configured path. This is the arm
    that fails on any implementation resolving the path as text before opening it.
    **And an eighth arm, for a mount landing mid-resolution**: with the resolution held at
    an intermediate component, a remote-backed filesystem is mounted onto the next one, and
    the resolution **refuses rather than entering it** — no open, no `stat` and no other
    call reaches the newly mounted filesystem, and construction ends holding no handle.
    This is the arm that fails on any implementation walking the path as a sequence of
    checks and opens, however each of them is guarded, and it is the one that distinguishes
    an atomic descent from a careful one.
    **And a ninth arm, bounding the one open the owner's ruling scopes**: in the sixth
    arm's substituted-mount sequence, with every filesystem call the constructor makes
    instrumented, the calls that reach the substituted filesystem are **exactly one
    directory open of the mount root and nothing else** — no read through it, no
    directory listing, no `openat` of any component of the configured path, no `stat` of
    anything beneath it, and no second attempt after the mismatch — and construction
    ends holding no handle and building no `Fetcher`. This is the arm that keeps the
    residual §6 discloses at the size §6 states it at, which is the size the ruling of
    2026-09-03 (#1996, comment 5532194014) scopes out of ADR-0017 §1; it asserts that
    bound and nothing wider. It is the arm that fails on any implementation that retries
    the open, that probes further after the mismatch, or that reads through the start
    handle before checking it.
23. **The root handle is released on both paths.** Three arms over `app/composition.py`:
    a built engine's `aclose` closes the fetcher, and a construction step that fails
    **after** the fetcher was built closes it before the error propagates. Asserted on the
    handle itself — the descriptor the fetcher held is closed — and not on a call count, and
    with a third arm that repeated build-and-shutdown cycles leave no descriptor
    accumulating. This is ADR-0042 §2's *"no half-built engine leaks a connection"* asserted
    for this resource, and it is the arm that fails on any wiring constructing a `Fetcher`
    without registering its `close`.

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
- **A root whose reads would leave the device, and any widening of what §6's eligibility
  admits.** §6 refuses one at construction, fail-closed over the whole backing chain, so a
  legitimate local configuration the lane's procedure cannot yet establish is refused until
  it can — a deliberate direction of failure and not a defect. Teaching that procedure to
  establish a further **local** filesystem or device is an implementation change and needs
  no ADR. Admitting a **network-attached** one — including one wearing a local filesystem
  type — is the egress decision ADR-0084 §1 says such a hop owes, and is fired only by that
  ADR: never by a deployment finding the refusal inconvenient, and never by this ADR, which
  pre-authorises none of it.
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
file"* and admits no fallback; §5 above sets it to the fetch instant for a source this
system interrogates directly, whose answer is produced at the instant of the read. A reader
holding only ADR-0092 would refuse to build that, so ADR-0070 §1's test is met and §3's
partial form is the sanctioned tool. **The scope is exactly the case where the two clocks
are one event**, it is a property of the producer rather than of the file — which is what
makes it decidable at all, since no `Fetcher` can classify where a file came from — and it
reaches no other: a kind that retrieves a remote source's earlier answer or replays one
from a cache is untouched, a source that declares its own instant uses it, and §3's
reason — that a substituted value asserts *"a report time the source never made"* — is why
the scope is drawn there and nowhere wider. What the record attributes to the source is the
document's **current content**, never a claim about who composed it or when.
**§3's mtime prohibition, its
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
  applies and does not relax. **ADR-0017 §1 is honoured on every read path by a refusal**:
  §6 will not construct a `Fetcher` on a root whose reads would leave the device, so the one
  configuration that could have made a `readers/` read an egress does not wire, and
  ADR-0084 §1's rule that such a hop *"owes its own ratified egress decision"* is left
  standing rather than approached. **The single construction-time open §6 discloses is
  scoped out of §1 by the owner's ruling of 2026-09-03 (#1996, comment 5532194014), and
  that is a reading of §1's reach rather than a movement of it.** ADR-0017's text is
  unchanged, its rule binds as written on everything this ADR builds, and the ruling is the
  owner's, cited here rather than recorded as this ADR's amendment: ADR-0082's records are
  owed for a clause this ADR itself makes false or over-wide, and §1 is neither.

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
- **`core` gains one Protocol, four models and one enumeration, and two versions move.**
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
- **Documenting the root as local and leaving it to the operator, rather than refusing a
  network-backed one at construction.** It was this ADR's answer for one round, on the
  ground that no portable locality check exists and that a fail-open allow-list guesses.
  Rejected because the width of the residual is not the question ADR-0017 §1 asks: its rule
  is that user data leaves the device only from `models/` or a designated `tools/` seam, and
  a read served over NFS leaves it from `readers/` however few bits it carries. A rule that
  admits the configuration and asks the operator not to use it has authorised the egress and
  then hoped. §6's refusal is fail-**closed** rather than fail-open, which answers the
  guessing objection in the only direction that matters: what is not established is refused,
  so the cost is a legitimate configuration that must be established before it is used, and
  never a remote-backed one silently admitted.
- **Deciding eligibility from the mount table's filesystem type alone.** §6 offered it for
  one round as a construction that satisfied the property, and it does not: ext4 or XFS on
  an iSCSI, NBD or NVMe-oF volume reports an ordinary local type while every read traverses
  a network, so a type-only check admits the ADR-0017 §1 egress the NFS case is, one layer
  down. §6 now requires the filesystem **and** its backing device to be established, names
  no construction as sufficient, and §14's item 22 carries the arm that fails a type-only
  implementation.
- **A distinct `UNSUPPORTED_TYPE` refusal for a file of a format the first rung does not
  read.** It was this ADR's sixth member for twenty rounds and it is unreachable: §6 keeps
  unsupported files out of the listing, so the only caller who can name one presents an
  entry the fetcher never minted, and §4 rules that `NOT_FOUND`. Making it reachable would
  mean either listing files the planner cannot use, or answering a guessed name with the
  fact that a file of that name exists — which is the disclosure §4's same-class rule was
  written to refuse. Dropped in §6, with §14's item 9 asserting the five that remain and the
  arm that fails an implementation carrying a sixth.
- **Refusing an exact copy of an authentic listing, so that only the object the fetcher
  handed out is fetchable.** It is the stricter reading of §4's *"a listing a caller
  assembled is refused"*, and it is unavailable: distinguishing a faithful copy from the
  original requires the fetcher to retain what it minted, which §4's fourth required
  property forbids and which the eight-listing window already failed on from both sides.
  It also buys nothing — a copy names the same entry of the same listing inside the same
  deadlines — so the refusal rule is stated over **unminted or altered** values instead,
  and §14's item 3 carries the arm in each direction.
- **Passing `SourceListingEntry` itself across `Planner.plan`, with a rule that a planner
  must not render the `handle`.** It was this ADR's answer for one round, and it makes the
  containment §2 claims a convention held at the `planning` boundary rather than a
  property of the seam — the very thing §4 refuses one clause earlier when it makes
  membership a minted capability instead of an obligation on the caller. A planner that
  serialised its inputs would put a live capability in a prompt, which is precisely what
  §2 exists to prevent. `ShownFile` removes the field rather than forbidding its use.
- **Admitting the root by a longest-prefix match of its configured path over the mount
  table, with an in-path symbolic link left to a later mismatch.** It was this ADR's answer
  for one round and it is unsound in the direction that costs: a prefix match reads the
  configured path as text, so for `/local/root/link/subdir` whose `link` targets an NFS
  mount it admits `/local`, and an open guarded only at the final component **follows**
  `link` — the remote filesystem is contacted and only then is the device mismatch seen.
  A mismatch detected after the read does not undo it.
- **Walking the path component by component, checking the mount tables before each descent
  and opening each component with no-follow.** It was this ADR's answer for the round after
  that, and it fixes the symbolic link while leaving the race one layer down: refusing to
  *follow a link* is not refusing to *cross a mount*, so a mount landing on an
  already-checked component between its check and its open is entered before anything can
  refuse it, and the walk simply repeats that window at every component. Both lenses found
  it on the same round, and architecture added that the final component's open has the same
  shape. The lesson taken is that **no ordering of separate checks and opens establishes
  this property** — which is why §6 requires an atomic resolution instead of a careful
  sequence, and why §14's item 22 carries an arm each for the in-path link and for a mount
  landing mid-resolution.
- **Opening the root first and deciding locality only against the opened handle.** It was
  this ADR's answer for one round, and it is right about the *object* the property must be
  established over — a pathname decided and then re-opened leaves the replacement interval
  §4 rules out. Rejected because it pays the read it exists to refuse: the first `open` of a
  directory on an NFS or SMB mount resolves remote metadata, and on ext4 over iSCSI it
  issues remote block I/O, so a root refused for being remote has already been reached over
  the network from `readers/` — the ADR-0017 §1 egress performed in the act of refusing it,
  and a rejection that asserts no `Fetcher` survives while asserting nothing about what the
  rejection cost. §6's two stages keep what was right about it — locality is finally decided
  against the open object — and drop what was not, that the object may be opened before it
  has been admitted. §14's item 22 carries the instrumented arm that fails an open-first
  implementation.
- **Classifying a file by where it came from, so that a synced or downloaded copy is
  refused an attestation and a locally authored one is granted it.** It is the shape a scope
  stated about the *file* would need, and it is unbuildable: a filesystem records no
  source-origin, nothing in the contract could carry one, and any implementation would be
  guessing from an extension, a directory or a download-marker convention. §5 draws the
  scope at what the producer *is* instead, which the fetcher knows by construction, and
  makes the root — not the document's author — the source the record attributes its report
  to.
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
