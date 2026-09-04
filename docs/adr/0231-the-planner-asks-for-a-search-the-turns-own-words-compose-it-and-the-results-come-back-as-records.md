# 231. The planner asks for a search, the turn's own words compose it, and the results come back as records

- Status: Proposed
- Date: 2026-09-04
- **Amends** [ADR-0226](0226-the-planner-names-one-more-read-beside-its-plan-and-the-loop-services-it-into-the-supply.md)
  — **§2's membership sentence, §4's not-ruled-on clause and §6's cross-kind
  precedence sentence, in one respect each.** §2's membership sentence has already
  been amended once by ADR-0230 §1 and is amended again here, because §1 below adds a
  fourth member. §4 reads that a `ReadAsk` *"is not selected against the capability
  vocabulary, not resolved to a tool, **not ruled on by the permission gate**, and
  never reaches `StepExecutor` or `ExecutionState`"*, and §9 below puts a
  `WEB_SEARCH` servicing's **send** in front of `ActionPolicy`. §6's precedence
  sentence, as ADR-0230 §7 last restated it, gains a fourth position (§11).
  **No ruling is replaced.** §1's additive-entry clause is the licence this ADR is
  taken under and is quoted in §1 below; §2's at-most-one-ask-of-each-kind rule and
  its closure against un-ADR'd additions bind entire; §4's other three prohibitions
  bind **verbatim and are load-bearing** — a `WEB_SEARCH` ask is not a `PlanStep`, is
  not selected against the capability vocabulary, is **not resolved to a tool**
  (§5 holds its declaration by value and resolves no id), and reaches neither
  `StepExecutor` nor `ExecutionState`; §4's reason for the amended clause —
  *"Reading the owner's own store is not an act in the world"* — is precisely why the
  amendment is confined to the one kind whose servicing **is** an act in the world;
  and §5's channel scoping, no-tool clause and degradation posture, §6's budget of
  ten and second-budget rule, §7's fourth group and whole-union deduplication, §8's
  trigger and §9's audit all bind as ratified. ADR-0226's `Status` line carries the
  leading `Partially superseded by` token, so this record lives in its appended dated
  note and not on that line (ADR-0082 §2).
- **Amends** [ADR-0230](0230-the-planner-names-a-file-it-was-shown-and-the-loop-fetches-it-into-the-supply.md)
  — **§7's servicing-order sentence, and that alone.** §7 reads *"**The servicing
  order is: local file, then citation hop, then sighted query.**"* §11 below inserts
  a fourth kind between the first two, so a reader holding only ADR-0230 would read
  that sentence more widely than it now holds. **§7's decision is not replaced but
  applied**: it orders by cap — *"the capped read ahead of the uncapped one"* — and
  §11 places this kind by the same rule and shows its working. Every other clause of
  ADR-0230 binds as ratified, and three are load-bearing here: §5's externality
  argument, whose reasoning §10 follows for a remote source; §5's own statement that
  *"a kind whose fetch retrieves a remote source's earlier answer, or replays one
  from a cache of its own, is outside this scope entirely and ADR-0092 §3 binds it as
  written"*, which §10 obeys rather than extends; and §15's first entry, which leaves
  this lane its questions open and which §1, §2 and §5 below answer one by one.
- **Amends** [ADR-0148](0148-an-egress-call-is-authorised-as-one-whole-and-nothing-in-it-moves-after-the-ruling.md)
  — **§1's single-route clause and §9's first, second and fourth clauses, in the
  single scope of a `WEB_SEARCH` servicing's send, and nothing else.** §1 routes every
  send through `ToolInvoker.invoke`; §6 below shows why that route is unavailable to
  this send and what replaces it. §9's first clause rules that *"There is no egress
  outside a claimed step"*, its second that *"`PermissionDecision.step_id` is set on
  every egress decision"*, and its fourth that the reconciliation path for a pending
  attempt is ADR-0014 §4's recovery scan; §6 below keeps the **property** all three
  buy — ADR-0017 §3's condition 12, an attempt identifier carrying an explicit
  outcome — through ADR-0192's invocation ledger, whose claim is keyed on a
  `PermissionDecision` rather than on a step, and shows why a servicing that produces
  one record has nothing to reconcile. §9's **third** clause is already partially
  superseded by ADR-0192 on *where* an outcome is recorded, and this ADR neither
  extends nor narrows that record. **Everything else in ADR-0148 binds entire and is
  load-bearing here**: §2's canonical destination set, §3's recipient authorisation
  tracing to a user act and its refusal of every near-miss, §4's whole-set rule, §6's
  determinism, §7's positional credential gate, §8's approver and its three floors,
  §9's four outcomes with *pending* among them, and §9's prohibition on resolving a
  pending attempt by guessing. No clause of ADR-0148 is relaxed; one route is added
  beside one, under conditions §6 states.
- **Amends** [ADR-0154](0154-the-tools-egress-seam-is-designated-and-the-fourteen-conditions-are-attested-in-code.md)
  — **§2's second clause, in the same single scope and for the same reason.** That
  clause reads *"Every send remains subject to ADR-0148's per-call machinery whole:
  §1's single route through `ToolInvoker.invoke`, …"*, and it is stated over **every
  send**, so ADR-0082 §1's test is met the moment a send leaves the seam by another
  route. **ADR-0154 is otherwise untouched and this ADR rests on it entire**: §1's
  designation is the ground of §5 below and no second seam is designated; §2's
  remaining clauses bind — this ADR registers no tool in any registry the turn path
  selects from, approves no destination on the strength of designation, lifts no
  ADR-0016 obligation, and takes **no first-use exemption and no standing
  authorisation from a configuration**; §4's fourteen attestations are gone through
  one by one in §7 below, and §4's actuator clause is the reason §19 defers the page
  fetch; §6's residues are carried unchanged; and §7's reservation of a
  `DestinationProtocol` member is **exercised** by §8 rather than moved.
- **This ADR does not move [ADR-0155](0155-residency-governs-the-assistants-own-store-and-that-store-is-never-externalised.md)
  §3, and the whole shape of the decision is built so that it does not have to.**
  §3's third clause forbids an egress span carrying covered content all of whose
  covered paths contain a model call, and reserves its relaxation to an owner ruling
  **and** a commissioned ADR designing a content-bearing approval surface. §3 and §4
  below take the other route ADR-0155's own Consequences names — a query composed
  *"from what the turn itself supplied"*, which *"introduces no store value and is
  produced by no model call carrying store content — so neither clause of §3 reaches
  it"*. §3's reserved fork stays exactly where §3 put it, is opened in parallel as a
  separate ADR lane, and §19 defers a memory-enriched query to it **by name and by
  purpose**, pre-empting nothing about it.
- **This ADR does not move [ADR-0092](0092-an-attested-belief-names-its-source-and-a-user-assertion-retires-it.md)
  §3 either.** ADR-0230 §5 superseded §3's local-substitute clause in a scope it
  states reaches nothing but a directly-interrogated local source. §10 below takes
  no part of that scope: the search provider's `reported_at` is **the instant that
  provider's own response declares on its own clock**, and a response declaring none
  mints no record. That is §3 as written — *"the capability is bounded by what
  sources can actually say"* — and the honest gap it leaves, that no record here says
  when a page's words were composed, is stated in §10 rather than filled.
- **Requires new `core` contract surface and lands none of it.** Two Protocols
  (`QueryComposer`, `WebSearcher`), one `ReadKind` member, one `ReadAsk` validator
  arm, one `DestinationProtocol` member and the types they carry. Flagged under
  golden rule 5; §17 says which lane lands each, and none may start before this ADR
  is Accepted and merged.
- **Ships legible and inert until the user has authorised the provider, and says so
  in §9 rather than leaving it to be discovered.** A search send draws a `CONFIRM` on
  ADR-0021 §5's disclosure floor; the servicer may not ask (ADR-0226 §5), so the only
  route to an `ALLOW` is ADR-0193's standing recipient grant, and no surface
  establishes one today. §9 states the consequence, §19 names the firing condition,
  and ADR-0193 §13 forbids this ADR deciding the surface.
- **Required review set: adversarial *and* architecture.** It decides `core`
  contract surface, adds a member to the enumeration ADR-0150 §3 closed behind a
  ratified contract ADR, and moves clauses of the two ADRs that stand behind the
  egress seam's designation. `CONTRIBUTING.md` makes a change contract-surface when
  it is the ADR deciding that surface.
- **Marked under ADR-0089**: every obligation is a marked clause and unmarked text
  supplies none. §21 records the count.
- Refs #1996, #1908, #1844, #1548, #1158, #1154, #75, #1907.

## Context

### Where this comes from

#1908's milestone 29 is the rung on which the planner may name a source **outside
the store**. Its order is fixed by #1844: local files first, *"because a steered loop
that can only read the owner's own disk has no channel out"*; then web reach *"under
the egress seam's attested conditions (ADR-0154) with the externality stamp
(ADR-0223) as the control: a tainted conversation asks first."* ADR-0230 landed the
first half. This ADR is the second, and #1908's exit sentence for it is: **a search
result is cited as a record and that conversation's egress asks first thereafter.**

The lane was dispatched once before and stopped at pre-flight (#1996, comment
5532816594). Its finding was that the design it had been briefed on — *the planner
composes a query and that query leaves the machine* — is forbidden outright by
ADR-0155 §3's third clause, because `Planner.plan` is called with `memories`
drawn from a store under `Settings.data_dir`, so the planner's output is covered
content every covered path of which runs through the planner's own model call.
ADR-0155's own Consequences states the case in terms: *"A recall-then-send turn
cannot draft egress arguments under the interim."*

The owner ruled on 2026-09-04 (#1996):

> **Milestone 29's web rung takes the utterance-only route.** The search query is
> composed by a model call supplied **only the turn's own utterance** — never a
> record from the store — so no covered content (ADR-0155 §3) is in view when it is
> written, the namer is the user, and the steered-loop channel closes by
> construction. ADR-0155's own Consequences blesses this shape ("neither clause of
> §3 reaches it"). Search results are minted as records with provenance; **page fetch
> is deferred by name** (a result URL is an egress selected by external content,
> ADR-0154 §4).

and, in the same ruling, opened ADR-0155 §3's fork (b) as a **separate ADR lane
running in parallel** — the content-bearing approval surface whose first customers
are memory-drawn email and memory-enriched search. That lane is cited here by
purpose and never by number, it does not block this rung, and nothing below
pre-empts it.

The owner had ruled the day before (#1996, comment 5532194014) that ADR-0017 §1 does
not reach an operator-configured pathname resolved at construction, and carried the
question forward in terms:

> **Carried forward to Lane B (web fetch):** the owner notes this is "important to
> think about when the next one is search results and online stuff". Yes: on that rung
> every planner-composed request leaves the machine by design, so the steered-loop
> channel is the normal path, not a corner case.

So that ruling gives a **model-composed or user-composed query no shelter**. A search
request is user-derived content leaving the machine on purpose, and it is an egress
at the designated seam.

### The exit, and what this ADR can and cannot demonstrate

#1908's exit has two clauses and ADR-0230 met the first. The second — *"a search
result is cited as a record and that conversation's egress asks first thereafter"* —
is two assertions about one conversation, and §18 owes a test for each. Both are
assertable over the production renderer and the production policy. What this ADR
cannot supply is a **live** deployment in which a search is serviced at all, because
that needs an `ALLOW`, and §9 shows the only route to one is a standing recipient
grant no surface establishes. That is stated here rather than discovered at the
probe.

### What the tree settles, verified against `origin/main` at `50c6373b`

Read rather than recalled. Each of these is load-bearing below.

- **`ReadKind` is a closed enumeration of three members** — `SIGHTED_QUERY`,
  `CITATION_HOP`, `LOCAL_FILE` — and `ReadAsk` carries `query`, `labels` and `entry`
  with a validator arm per kind, each enforced by the model rather than by its
  callers. `ReadRequest` carries at least one ask and at most one of each kind.
- **`service_read_request` is the one servicer**, in `orchestration/reads.py`, with
  `READ_BUDGET` at ten counted after deduplication, and `emit_read_audit` writes one
  `INFO` event under one fixed key per turn carrying counts and kinds and no text.
- **`SelectionOrigin.over` is `orchestration`'s**, not `core`'s, and
  `Engine._run_turn` computes it once per pass over `turn.memories`;
  `AttemptRunner._bound` is the one place it is written onto the bind path, as
  `CarriedProvenance.planned_with_external_content`.
- **`ActionRequest` carries a `ToolDefinition` by value**, *"so a policy never
  consults a registry"*, and `egress_binding` is the one field that makes it an egress
  call.
- **`EgressBindingSeam._registered` reaches a registration without a registry
  original.** Its own words: *"Where the registry holds no definition for the id the
  comparison is not reached, exactly as ADR-0152 §1 states."* It then reads
  `self._registrations.registration(tool.id)` and returns it. So a tool registered at
  the **egress seam** and absent from the `ToolRegistry` binds, while
  `ToolRegistry.capabilities()` — which is what `LearningLoop._turn` passes the
  planner — never sees it, and `ToolInvoker.invoke` cannot act on it, because *"An id
  is invocable if and only if it is registered."* §5 and §6 rest on this pair of
  facts and on nothing else.
- **`ThresholdActionPolicy`'s table**: a non-empty `discloses` confirms and is not
  configurable; an `UNKNOWN` cost confirms; risk and reversibility confirm or deny at
  the configured thresholds; an `egress_binding` carrying
  `planned_with_external_content` confirms and is not configurable. *"A
  `RecipientGrants` changes exactly one row of the table above … Where it is the only
  clause standing between the request and an `ALLOW`, `_DISCLOSURE_FLOOR` is
  discharged by a covering standing grant."*
- **The recipient-grant store is wired and empty.** `app/composition.py` constructs
  `SqliteRecipientGrantStore` and hands the policy its query face, with the reason
  written beside it: *"until a surface offers the establishing act (§13) the store is
  empty, so every ruling is the one it was before."* Nothing in `src/` establishes a
  grant.
- **ADR-0192's invocation ledger is keyed on a decision, not a step.**
  `InvocationLedger.claim_invocation(*, decision: PermissionDecision)` returns a row
  whose id `complete_invocation` completes with a `ToolOutcome`, and `orchestration`
  already holds the **narrow** face for its recovery scan and *"must not claim"*.
- **`SpendGate.admit_invocation(*, estimate: ToolCost)` is held by
  `ToolInvoker.invoke` and never a `SpendLedger`.** *"Where neither ceiling is
  configured this returns before it reads the clock"*, so an unconfigured deployment
  pays nothing for the call.
- **`OutboundTransport` is a byte channel and deliberately not an HTTP client**
  (ADR-0191 §2), and ADR-0191 §2 already priced the consequence: *"A future
  integration that speaks HTTP will build or import an HTTP client over the channel …
  that work is confined to the designated seam."*
- **`DestinationProtocol` has one member, `SMTP`**, and its own docstring records
  ADR-0150 §3's rule: the membership is fixed and *"requires a ratified contract ADR
  for every further member, stating which equivalences that protocol establishes and
  which it does not."* The canonicaliser lives at the seam, in
  `tools/destinations.py`, never in `core`.
- **`Attestation` has three fields** — `reported_by`, `reported_at`, `extent` — and
  `extent` is a `ReportedExtent`, a half-open `[from, until)` pair of instants
  (ADR-0117 §2). **There is no address field anywhere on `Provenance` or
  `Attestation`**, and ADR-0092 §3 forbids putting *"a filesystem path that discloses
  more than the source's identity"* in `reported_by`.
- **No HTTP client and no search-provider SDK is a dependency**, and
  `pyproject.toml`'s import-linter contract *"network transports are confined to the
  tools egress seam"* enumerates every module under `ai_assistant.tools` except the
  seam as a source and names `httpx`, `requests`, `aiohttp`, `urllib3`, `websockets`
  and the standard-library transports as forbidden. The SMTP exchange is hand-rolled
  over `asyncio` streams and `ssl` inside `tools/egress.py`.
- **`PROTOCOL_VERSION` is 28** (`wire/envelope.py`) and `PlanExport.schema_version`
  is 5, both moved by ADR-0230 §12.

### Claims in the framing that do not survive contact with the tree

- **"`ActionRequest` is tool-shaped, so a non-tool egress call cannot reach
  `ActionPolicy` today."** True of the type and **not** a bar. A tool-shaped request
  is exactly what `ActionRequest` is for — it carries the definition by value so no
  registry is consulted — and a declaration may be registered at the egress seam
  without being in any registry the turn path selects from (above). What is genuinely
  unavailable is `ToolInvoker.invoke`, and §6 states the amendment that costs.
- **"A search result's `Provenance` names the URL."** #1908 and the lane brief both
  say so; no field on `Provenance` or `Attestation` can carry an address, and
  ADR-0230 §5 deliberately keeps the address off the record. §10 puts the provider's
  own result text — including the address it reported — in the record's `content`,
  and adds no `core` field.
- **"ADR-0223 §6's stamp is the control."** It is *a* control and it is not the one
  that closes the steered loop. §12 shows that the loop is closed first by there being
  no field in which a model-composed byte could reach the wire, and second by the
  origin bar on the ruling; the stamp is what carries the second control across turns.
- **ADR-0226 §12's and #1844's "milestone 3"** is milestone 29 under #1908's global
  renumbering of 2026-09-03. Confirmed.
- **The hub has no search provider, no page-fetching HTTP client and no SMTP
  transport in production** (#1148). Confirmed at `50c6373b`; none is cited below as
  existing.

### What this ADR is not allowed to settle

It designates no seam, attests no condition of ADR-0017 §3 that ADR-0154 §4 did not
attest, registers no tool in any registry the turn path selects from, relaxes no
clause of ADR-0155, decides nothing about `models/`, decides no surface for
establishing a recipient grant (ADR-0193 §13), builds no source-material archive
(#1907), and answers neither #1154 nor #75 nor #95. §20 lists what it does record
against earlier ADRs, and §19 lists what it defers.

## Decision

We will admit **one more kind** to ADR-0226 §1's enumeration — a **web search** — in
which the planner asks only *that* the web be consulted, the **query is composed by a
model call supplied the turn's own utterance and nothing else**, the request leaves
through ADR-0154's designated seam as an egress call ruled by `ActionPolicy`, and
what comes back is a small number of `MemoryRecord`s carrying the provider's own
words and the provider's own attestation. The records enter the turn's supply as part
of ADR-0226 §7's fourth group, are written to no store, and carry the external mark —
which is what makes a conversation that has read a result ask before its next outward
call.

### 1. The kind: `WEB_SEARCH`, and the ask that carries nothing

> **Normative.** `ReadKind` gains one member, `WEB_SEARCH`, valued `web_search`. It
> is an **additive entry** under ADR-0226 §1 — *"A later kind is an additive entry to
> this enumeration, not a second seam. An ADR admitting one adds a member and states
> that kind's namer, its servicing, its share of §6's budget and its audit fields; it
> does not introduce a second request object, a second servicing site, a second budget
> or a second audit."* It adds none of those four, and every clause ADR-0226,
> ADR-0228 and ADR-0230 state over a read request binds on it except where a section
> below names the exception and shows its working.

> **Normative.** **A `WEB_SEARCH` ask carries no argument at all.** `ReadAsk`'s
> validator gains one arm: a `WEB_SEARCH` ask carries no `query`, no `labels` and no
> `entry`. `ReadAsk` gains **no field** for this kind, and no later lane adds one
> without the ADR that decides it. A `WEB_SEARCH` ask states its kind and nothing
> else.

> **Normative.** ADR-0226 §2's at-most-one-ask-of-each-kind rule and `ReadRequest`'s
> validator bind unchanged: one emission carries at most one `WEB_SEARCH` ask, and a
> request naming two is not an emission this corpus admits. A turn that revises may
> emit a second `WEB_SEARCH` ask on its second plan, which is ADR-0228 §3 applied and
> not widened — and §9 is why the second one is not serviced in the ordinary case.

> **Normative.** **One ask is one search.** No implementation issues two requests for
> one ask, follows a link out of a result, requests a further page of results, or
> retries a refused or failed request inside the turn. There is no pagination, no
> depth and no traversal of any kind, and no later lane adds one without the ADR that
> decides it.

**The empty ask is the whole of this kind's safety mechanism, and it is a property of
the type rather than a rule an implementation is trusted to keep.** The thing the
first attempt at this lane found forbidden is a planner-composed query reaching an
egress span: `Planner.plan` is handed `memories` read from a store under
`Settings.data_dir`, so anything the planner writes is covered content whose every
covered path runs through the planner's own model call, and ADR-0155 §3's third
clause forbids that reaching a span. **A field the planner cannot write is a field
that cannot carry covered content.** Giving `WEB_SEARCH` an argument — even one a
prompt told the planner to keep short, or generic, or free of anything recalled —
would put the prohibition back on the wrong side of the seam, where it would depend
on a model's compliance and on a reviewer noticing. There is no such field, so there
is nothing to comply with.

**It also settles ADR-0230 §15's open question about the namer without needing an
ordinal.** That section left this lane the question honestly: §2's ordinal scheme
*"has no analogue for the web, where there is no listing the loop produced and a URL
is a string a model composes, so that lane's namer question is genuinely
different"*. It is different, and the answer is not a smaller address space but **no
address space at all**: this kind takes no address, so the question ADR-0230 §2
answers with an ordinal does not arise. §2 states what that makes the namer.

**One search and not several, which is this kind's bound.** ADR-0226 §6 gives the hop
at most two labels and ADR-0230 §1 gives the file exactly one, each because the capped
read is what makes the budget's precedence honest. This kind is capped at one request
and, by §10, at three records. A kind that could issue two requests would be a
decomposition decision — how a question is split across sources — which ADR-0226 §12
and ADR-0228 §14 defer by name, and iteration already gives a turn a second look
(§12 is why it does not in fact get a second search).

### 2. The namer: the planner points outward, and the user names

> **Normative.** ADR-0226 §3's namer rule binds this kind as written: **the namer may
> be data, or the user, or the model pointing outward — never the model pointing
> inward.** A `WEB_SEARCH` ask is the planner pointing outward and naming nothing;
> what is named — the query — is composed from the user's own utterance and from
> nothing else (§3). The namer is **the user**.

> **Normative.** **No address crosses the seam in either direction as an
> instruction.** No `ReadKind` accepts a URL, a host, a domain or any other address
> from a model, and none is minted from model output. A minted record's `content`
> carries the address the provider reported (§10) and is presented to every later
> model call as third-party data (ADR-0098 §2); no component reads an address out of
> a record, a reply, an utterance or a prompt and acts on it, and §19 defers both
> address spaces that would.

**This is the strongest namer in ADR-0226 §3's hierarchy, and it is worth saying why
rather than only that it is.** §3 admits three namers and refuses one. Of the three,
the user is the one that needs no mechanism to keep honest: a `CITATION_HOP` label is
kept honest by the loop resolving it against the very sequence it passed, and a
`LOCAL_FILE` entry by the fetcher minting and verifying its own listing tokens.
Here there is nothing to keep honest, because the model contributes no part of the
address and the address space is a single origin the operator connected. What the
planner contributes is the **judgement that this turn's question is one the web can
answer**, which is exactly ADR-0226 §8's trigger and carries no content anywhere.

**And it is why the search is not a decision about *whether the user meant it*.** The
utterance the composer is handed is the user's own words for this turn, unrewritten,
which is what `_goal_from` already holds and what ADR-0226 §3's rule means by "the
user". A design in which the planner *paraphrased* the utterance into the ask would
have made the planner the namer again with an extra step.

### 3. The query composer: one argument, and that is the safety claim

> **Normative.** `core/protocols.py` gains one Protocol, **`QueryComposer`**, with
> exactly one member:
>
> `async def compose(self, utterance: NonBlankEncodableText) -> QueryOutcome`
>
> It takes **one positional argument and no other**, and no later lane adds a
> parameter, a keyword, a constructor dependency on a `MemoryStore`, a
> `ContextProvider`, a `ConversationStore`, a `TranscriptArchive` or any other store
> seam, or a second member. A caller able to widen the input is a caller able to
> defeat the bound (ADR-0093 §10), and this contract gives one none.

> **Normative.** **The argument is the turn's own utterance and nothing else** — the
> unrewritten user text for the turn being planned, as `orchestration` already holds
> it. No implementation is passed, and none may be passed, a `MemoryRecord`, a
> supply, a context facet, a listing, a plan, a rationale, a prior turn, a
> conversation tail, an episode, a capability set or any value obtained from a store
> under `Settings.data_dir`. There is no parameter through which any of them could
> arrive.

> **Normative.** `QueryOutcome` carries a **query or a refusal, never both and never
> neither** — ADR-0230 §4's shape, for its reason. The query is
> `NonBlankEncodableText` bounded at `SEARCH_QUERY_MAX_CHARS` Unicode code points; a
> composition exceeding the bound is **refused rather than truncated**, and the
> refusal is a member of a closed `QueryRefusal` enumeration and never free text.
> `compose` **raises for no composition reason**: an unavailable model, an unparseable
> answer, an over-long answer and a composer that judged the turn unsearchable are all
> refusals, and only `CancelledError` leaves it.

> **Normative.** **A composed query is a model completion with no recorded origin**,
> of the same class as `ActionPlan.rationale` (ADR-0226 §9, ADR-0228 §11). Wherever it
> is rendered, read back or exported it is treated as that class already is, and
> nothing here makes it speakable, placeable, or admissible to a channel a rationale
> is inadmissible to. No lane infers a placement for it by inspecting it, and no lane
> reads its having been composed over the user's own words as making it a better class
> than one composed over a wider supply — ADR-0228 §11's clause read on the other
> axis.

> **Normative.** The production composer lives in **`ai_assistant.planning`** and is
> reached by `orchestration` through this Protocol and by no other route. It holds a
> `ModelProvider` and nothing else that reads. `orchestration` imports no name from
> `planning` on account of this decision, and no lane wires a composer that holds a
> store seam of any kind.

**The signature is the mechanism, and this is the one paragraph of this ADR a
reviewer should check hardest.** The whole safety claim of the utterance-only route
is *no store value is in view when the query is written*, and a claim of that shape is
worth exactly as much as what makes it true. Two things could have made it true: a
rule that implementations must not pass records, or a contract with no parameter for
them. The corpus has already ruled which of those is worth having — ADR-0093 §10 gave
`Reader.read()` no arguments *by decision*, on the ground that *"a caller able to
widen the read is a caller able to defeat the bound"*, and ADR-0230 §4 built the
`Fetcher` bound the same way. The same discipline here means the property is
**decidable from the signature**: a `QueryComposer` implementation that wanted store
content would have to acquire it out of band, which is a different defect in a
different place and one a reviewer of `planning/` is looking straight at.

**The tail is the value a well-meaning lane would add, so it is named.** A composer
handed the last few turns would write better queries — a follow-up question ("and
what about Porto?") is unsearchable without them. And the tail is read from the
conversation store under `Settings.data_dir`, so it is **covered content** by
ADR-0155 §3's first clause, and a query composed over it is covered content all of
whose covered paths run through the composer's model call, which §3's third clause
forbids reaching a span. The cost is real and is accepted: this rung searches well for
a self-contained question and badly for a follow-up, and §19 defers the widening to
the lane ADR-0155 §3(b) reserves rather than taking a piece of it here.

**`planning/` and not `orchestration/`, because the composer is a prompt.** It turns
the user's words into a model call and reads the answer back, which is what
`planning/` already does for `ModelBackedPlanner` and where this repository keeps the
prompt discipline ADR-0098 §2 imposes. Putting it in `orchestration/` would put prompt
authorship in the subsystem that is meant to hold none, and would make the loop the
only place two different prompts are written. What `orchestration` gets is the
Protocol and the outcome, which is golden rule 1 as written.

**Refusal and not an exception, for ADR-0230 §4's reason.** A composer that raised
would make ADR-0226 §5's degradation posture the servicer's problem to catch
correctly at every call site; a closed refusal enumeration makes the non-yield a value
the audit can count (§13) and the turn can ignore.

### 4. Why ADR-0155 §3 does not reach the query, stated in terms

> **Normative.** No component supplies a `QueryComposer` with covered content in
> ADR-0155 §3's sense, and no component composes, augments, re-ranks, filters or
> annotates a search query from covered content at any point between the composer and
> the seam. What reaches the wire is the composer's own output, byte for byte, beside
> the connected account's origin.

> **Normative.** No lane reads this ADR as relaxing, narrowing, scoping or
> interpreting **any** clause of ADR-0155 §3, and none cites it toward the fork §3
> reserves. §3's third clause stands exactly as ratified, and the ADR that fork
> commissions is the only instrument that may move it.

**The argument, laid out once so a reader can check it rather than take it.**
ADR-0155 §3's first clause defines covered content as *"a value any component obtained
from a store this system keeps under `Settings.data_dir`; and the output of any
operation — a model call or any other — to which any component of this system supplied
covered content"*. The composer is supplied one value: the turn's own utterance,
which this system **received from its user** and obtained from no store. So the
utterance is not covered content, the composer's model call is supplied no covered
content, and its output is therefore not covered content either. Neither §3's second
clause (some covered path with no model call) nor its third (every covered path with
one) has a subject. That is not an inference: ADR-0155's own Consequences states this
exact case as the shape that survives the interim —

> A send whose spans carry only content the owner authored, or content composed for
> that send **from what the turn itself supplied**, introduces no store value and is
> produced by no model call carrying store content — **so neither clause of §3 reaches
> it**.

— and ADR-0155 §2's second clause admits it positively: the content §2 permits in an
egress payload is *"the owner's own words, and content this system composed at the
owner's direction for that send."*

**The one place the argument could be broken is the supply site, which is why the
clause above is stated over components rather than over the composer.** ADR-0155 §3
is decided *"at each supply site from recorded origin"*, so the property is a fact
about who hands what to whom. §3's Protocol makes the composer's own supply site
narrow by construction; the clause above closes the second site — the servicer
assembling the request — where a lane might otherwise think a query "improved" with a
recalled fact is a better query. It is a query the corpus forbids sending.

**And a `WEB_SEARCH` ask carrying no argument is what makes the whole of this
checkable rather than argued.** The planner is the component holding covered content;
it emits a kind and no bytes; the composer holds no covered content and emits the
bytes. The two capabilities are in different components on purpose, and neither has
the other's input.

### 5. The egress: the designated seam, and a registration with no registry entry

> **Normative.** A `WEB_SEARCH` request leaves through **`ai_assistant.tools.egress`**
> — the module ADR-0154 §1 designates — and through no other module. This ADR
> **designates no second seam**, and no lane reads it as designating one, as widening
> ADR-0154 §1's designation, or as making `app/`, `orchestration/` or `planning/` an
> egress boundary.

> **Normative.** The transport is an **HTTPS exchange built inside that module**, over
> the injected `OutboundTransport` ADR-0191 §1 contracts, and it holds four properties
> whatever library the implementing lane uses or writes: it opens a channel to the
> **one origin the connected account names** and to no other; it **follows no
> redirect** — a redirect response is a refusal and never a second request; it opens a
> channel **per call** and closes it, retaining no pool, cache or keep-alive
> (ADR-0191 §3); and it carries the account's credential to that origin and to
> nothing else.

> **Normative.** Adopting a transport-bearing dependency for this exchange is
> ADR-0003's ordinary route under ADR-0024's pinning rule, is confined to the
> designated module, and **extends ADR-0147 §3's import-linter contract by naming that
> dependency in its forbidden set** — which is what that clause already requires of
> *"any lane adding a transport-bearing dependency"*. This ADR authorises no
> dependency and chooses none.

> **Normative.** The search integration is declared as a `ToolDefinition` and
> **registered at the egress seam against a connected account, and in no
> `ToolRegistry`**. It is therefore absent from `ToolRegistry.capabilities()` and
> `all_tools()`, unreachable by any plan step, and un-invocable through
> `ToolInvoker`. No lane registers it in the default registry or in any registry the
> turn path selects from, and no lane reads this ADR as licence to register a tool
> whose result the turn path turns into records.

> **Normative.** The declaration's fields are stated on their own ground, as
> ADR-0016 §1 requires, and are: `discloses=(PERSONAL,)`; `reads=(SECRET,)`;
> `writes=()`; `side_effecting=True`; `risk_level=LOW`; `reversibility=REVERSIBLE`;
> `idempotency=NONE`; and a `cost` that is the operator's configured per-call figure
> where one is configured and `UNKNOWN` where none is. Its schema declares exactly two
> arguments: an **origin**, carrying `x-egress-destination: "https"` and
> `x-egress-tier: "operational"`, and a **query**, carrying neither keyword.

> **Normative.** The credential is read by the seam itself, from
> `Secrets.get` at `SecretScope.INTEGRATION` (ADR-0125 §1, §2), inside the call the
> ruling authorised — ADR-0148 §7's positional gate, unchanged and not restated. **No
> credential crosses the `QueryComposer` or `WebSearcher` seams in either direction**,
> and no component outside `tools/` holds one on account of this decision.

**The registration-without-a-registry-entry is the hinge of this whole design, and it
is a fact about the tree rather than a device invented here.**
`EgressBindingSeam._registered` performs the registry-original comparison only where
the registry holds a definition for the id — its own docstring says *"Where the
registry holds no definition for the id the comparison is not reached, exactly as
ADR-0152 §1 states"* — and then returns the **egress** registration. Meanwhile
`ToolRegistry.capabilities()` is what `LearningLoop._turn` passes the planner, and
`ToolInvoker`'s contract is that *"An id is invocable if and only if it is
registered."* So the two halves of what "registered" has meant since leg 12 come
apart exactly here, and the half this kind needs is the seam's.

**What that buys is the thing #1908 asks for in one sentence — "Not a tool step" —
made structural.** If the search were in the registry, the planner would see a
capability, could name a plan step for it, and the turn would drive a tool whose result
is a JSON payload with no per-span provenance: ADR-0170 §5a's own reason for saying a
reply is not a tool, and ADR-0208 §1's for saying that a component wanting records
does not obtain them by invoking one. Not being in the registry means the planner
cannot name it, so the failure mode is not forbidden by a rule — it is unreachable.

**And it is not a loophole in ADR-0154 §2, which is the reading a reviewer should
test.** That section's prohibitions are on what designation *authorises*: it registers
no tool, approves no destination, lifts no ADR-0016 obligation, and gives no first-use
exemption and no configuration-granted standing authorisation. This decision takes
none of those. The search integration is registered by **a registering lane**, which
ADR-0154 §2's own last paragraph anticipates (*"a registration lane is no longer
blocked by ADR-0017 §2 — it is blocked only by its own work"*), and ADR-0154 §6's
residency clause binds that lane: §14 below is where this ADR discharges it.

**The declaration, field by field, because ADR-0016 §1 forbids deriving any of them
from what the integration is called.**

- **`discloses=(PERSONAL,)`.** A query composed from the user's own words is Tier 1
  and it leaves the device, which is what this field is for. Non-empty is what makes
  ADR-0021 §5's floor bite on every search, so none is auto-granted and the approver
  is the user (ADR-0148 §8's second clause read for its purpose rather than for its
  literal subject, which is a *registered* tool). Naming `SECRET` would declare that
  this integration may select a Tier 0 value for a third party, which ADR-0146 §3
  forbids outright; `send_email`'s declaration refuses the same move for the same
  reason. The query span itself establishes **no** tier, exactly as a message body
  does — arbitrary text however well the composer knows what it is for (ADR-0146 §5) —
  so the payload description states none for it, and ADR-0146 §5's *"containment, not
  prevention"* is the honest description of what the user is shown.
- **`reads=(SECRET,)`.** The callable reads an `INTEGRATION`-scoped credential, which
  is Tier 0, and ADR-0148 §7 makes that read part of this call. `reads=()` would be
  the false claim ADR-0016 §1 names.
- **`writes=()`.** The search changes nothing this system stores.
- **`side_effecting=True`**, which a non-empty `discloses` makes structurally
  mandatory anyway.
- **`reversibility=REVERSIBLE`.** ADR-0016 §2 scopes reversibility to *"the effect on
  the system acted upon"* and is explicit that disclosure is a separate axis. A search
  is a **read** of a remote index: nothing at the far end changes, so there is no
  effect to reverse. `send_email` is `IRREVERSIBLE` because a message arrived and SMTP
  has no unsend; nothing arrives here. The disclosure that cannot be withdrawn is real
  and is carried by `discloses`, which is the axis ADR-0016 §2 assigns it to.
- **`risk_level=LOW`, and this is the field to press hardest on.** ADR-0016 §2's scale
  is how much damage **one invocation** could do, and three facts bound this one: the
  recipient is a single origin fixed by the connected account and reachable by no
  argument the model can write; the payload is one bounded string composed by a model
  call supplied only the user's own utterance (§3), so neither a store value nor an
  external span can be in it; and nothing anywhere changes. `send_email` is `HIGH`
  because *"a send discloses to a recipient chosen per call from arguments a model
  produced"* — the clause that makes it `HIGH` is exactly the clause that is false
  here. **The honest accounting is that the field was decided on §2's scale and then
  checked against what it enables, and both are stated**: `LOW` is also what keeps the
  disclosure floor the *only* clause standing between the request and an `ALLOW`, which
  is the condition ADR-0193 §3 and §7 put on route (b) being reachable at all. A
  deployment, an owner or a later ADR that judges `MEDIUM` honest gets a mechanism that
  is never serviced under the shipped thresholds; that outcome is legible, fail-closed
  and costs nothing but the capability, and §19 records it as the thing a
  reconsideration would move.
- **`idempotency=NONE`.** No provider guarantees deduplication of a query, so `KEYED`
  would advertise a guarantee ADR-0029 §5's derived key cannot make true.
- **`cost`.** ADR-0016 §4 keeps "free" and "not known" apart, and `SpendGate` can only
  count a known figure (§15). A deployment that configures a per-call figure declares
  it; one that does not declares `UNKNOWN`, which confirms — the fail-closed direction,
  and the reason §15 needs no ceiling of its own.

**The schema's two arguments, and why the origin is one of them.** ADR-0148 §8's third
floor refuses an `ALLOW` where a request carries no canonical destination set, and the
set is derived from spans whose argument declares a destination (ADR-0152 §3). So the
origin is an argument bearing `x-egress-destination: "https"`, which is what makes the
call's recipient a value the policy, the grant and the confirmation all range over —
and it is what §8's canonical form is for. Its tier is `operational`: an origin is the
operator's own configuration, it is the same value for every call, and it is a field
every value of which carries one tier by what the field is for, which is ADR-0146 §5's
test passed. The query declares neither keyword: it selects no recipient, and it
establishes no tier.

### 6. The route: not `ToolInvoker.invoke`, and how condition 12's property is kept

> **Normative.** The send is **not** made through `ToolInvoker.invoke`. Every other
> element of ADR-0148's per-call machinery is performed, in this order and by these
> components: `orchestration` builds the `ActionRequest` from the declaration held by
> value and the two arguments; `EgressBinder.bind` derives the `EgressBinding` whole
> and accepts no part of it; `ActionPolicy.decide` rules on the request;
> the `AuditTrail` records the `PermissionDecision`; and only then is a `ToolCall`
> constructed — which is unconstructable unless the decision authorises the request —
> and handed to the seam.

> **Normative.** **The attempt identifier and the four outcomes ADR-0017 §3's
> condition 12 requires are ADR-0192's**, not a plan step's. The seam claims the
> invocation on an `InvocationLedger` from the recorded `PermissionDecision`, sends,
> and completes the claim with a `ToolOutcome` and an incurred cost on every exit it
> observes, exactly as ADR-0192 §3 obliges `ToolInvoker.invoke`. `orchestration`
> **claims nothing** and holds only the narrow `InvocationCompleter` face it already
> holds (ADR-0192 §3).

> **Normative.** **A claim left open states, as its own state, that the search may
> have reached the provider, and nothing reconciles it.** ADR-0148 §9's
> reconciliation clause reconciles a step's record with a claim; a `WEB_SEARCH`
> servicing produces **one** record, so there is nothing to reconcile and no scan
> reaches it. **No lane adds a recovery arm for it, completes it from outside the
> seam, or resolves it by guessing** — ADR-0192 §3 already rules that such a claim is
> read as `SUCCEEDED`, as `FAILED`, as "did not run" or as an omission by nobody, and
> ADR-0148 §9's third clause makes *pending* one of the four outcomes rather than the
> absence of one. No further claim is admitted under that decision, which is correct:
> the decision authorised one call.

> **Normative.** `PermissionDecision.step_id` is **`None`** on a `WEB_SEARCH`
> decision, and `execution_id` is `None`. No lane synthesises a plan step, an
> `ExecutionState`, an execution or a claim on one in order to satisfy a clause
> written about steps, and no lane reads this section as licence to drive a
> `ReadAsk` through `StepExecutor` — ADR-0226 §4's other three prohibitions bind
> verbatim.

> **Normative.** No lane reads this section as opening a second route for **any other
> send**, and no lane synthesises a plan step, an execution or a `RUNNING` claim in
> order to give a clause about steps a subject here. It is stated over a `WEB_SEARCH` servicing's request and nothing else; every
> tool call, `send_email` included, goes through `ToolInvoker.invoke` exactly as
> ADR-0148 §1 rules, and a lane wanting a further exception needs the ADR that decides
> it.

**Why the invoker's route is genuinely unavailable rather than merely inconvenient.**
`ToolInvoker`'s contract is that *"An id is invocable if and only if it is
registered"*, and `all_tools()` and the invocable set *"are the same set, always"*,
with the composition root obliged to inject **one object** as both registry and
invoker (ADR-0029 §8). So taking the invoker's route requires putting the search in
the registry, and putting it in the registry puts its capability in front of the
planner — the outcome §5 exists to prevent. The two clauses are jointly unsatisfiable
for this kind, and this ADR chooses which to move: the route, which is a mechanism,
rather than the capability boundary, which is a property #1908, ADR-0170 §5a and
ADR-0208 §1 all rest on.

**What the amendment costs, and what it does not.** It costs `ToolInvoker`'s three
pre-execution checks — revalidation and detachment, the authorisation re-check against
a detached copy, and the deadline — which the seam performs itself for this call
because `ToolCall`'s own validator runs `PermissionDecision.authorises` at
construction and ADR-0029 §4's invocation deadline is the seam's to hold either way.
It does **not** cost the payload binding (the request's `parameters_digest` is bound
into the decision and compared by `authorises`), the immutability (`ToolCall` is
frozen and the binding is derived, never accepted), the approver (§9), the credential
gate (§5), or the audit (this section). Condition 12's property is not weakened but
carried by a different bearer — which is what ADR-0154 §4's own clause demands of a
change that would otherwise falsify a subsection: *"the lane that makes it either
restores the property in the same change or opens an ADR reconsidering the
designation."*

**ADR-0192's ledger is the right bearer, and that it is keyed on a decision is the
whole reason.** `claim_invocation(*, decision: PermissionDecision)` takes the
authorising decision and nothing about a step; `complete_invocation` closes the claim
with one of ADR-0029 §3's outcomes. ADR-0148 §9 was written when the only thing that
claimed was a step execution; the ledger that arrived afterwards records exactly the
fact §9 wanted, keyed on exactly the value an egress decision already has. The step
was the bearer, not the property — which ADR-0148's own 2026-08-24 note half-concedes
when it records ADR-0192 superseding §9's third clause on *where* an outcome lives.

**And the missing reconciliation is a real difference from a step's attempt, so it is
stated rather than papered over.** `orchestration/recovery.py`'s scan finds a durable
`RUNNING` step and completes the open claims under its `approval_ref`; a search
decision has no step, so that scan never reaches its claim and this ADR does not teach
it to. What that costs is nothing, because the reconciliation exists to stop **two**
records disagreeing — ADR-0192 §3 is explicit that the pair *"can differ in either
direction"* and that neither is inferred from the other's absence — and a search
produces one. An open claim after a crash is therefore not an unresolved state but the
honest one: the query may have reached the provider, nobody can tell, and the corpus
already has a word for it. The step-shaped alternative would have been to synthesise a
plan step so that a scan had something to find, which §6's third clause forbids and
which would be inventing a subject to satisfy a clause rather than keeping its
property.

**The claim and the completion are the seam's and never `orchestration`'s**, because
ADR-0192 §3 hands `orchestration` the narrow face on purpose — *"a dependency that
cannot express the call"* — and reversing that to let the loop claim would hand the
turn path a capability the corpus removed from it on ADR-0029 §1's argument. So the
`WebSearcher`'s one acting member takes an authorised `ToolCall` and owns everything
after it, which is `ToolInvoker.invoke`'s own division of labour with the registry
lookup removed.

### 7. ADR-0017 §3's fourteen conditions, for a search request

This subsection is attestation and argument, not obligation (ADR-0089 §1); the
obligations it depends on are marked in §5, §6, §8 and §9. ADR-0154 §4 attested each
condition for the seam and ruled that *"A later change that falsifies any
subsection's stated property removes the ground on which designation rests."* Each row
below says which of three it is: **unchanged** (the property holds for this request by
the same code and the same mechanism ADR-0154 attested), **attested anew** (this
request reaches code ADR-0154's row did not range over, and this ADR states what must
hold of it), or **not applicable** (the condition has no subject for a read).

| # | Condition | This request |
|---|---|---|
| 1 | A named seam and an import-linter contract pinning it | **Attested anew** — §5 keeps transport inside `ai_assistant.tools.egress` and extends ADR-0147 §3's forbidden set with any dependency adopted for it |
| 2 | Per-call gating before transmission | **Unchanged** — §6's order puts `ActionPolicy.decide` and the recorded decision before any channel is opened |
| 3 | Recipient authorisation tracing to a user act, bound to the resolved destination | **Unchanged** — §9; the destination is the canonical origin §8 fixes, and ADR-0148 §3's refusal of every near-miss binds, the connected account included |
| 4 | Credential access gated, not just transmission | **Unchanged** — §5's credential clause is ADR-0148 §7 applied; the ruling that authorises the call is the gate on the read it performs |
| 5 | Transport pinned to the connected service, redirects unable to carry the request or its credential elsewhere | **Attested anew** — §5's no-redirect and one-origin properties, which is why this ADR fixes them rather than leaving them to a library's defaults |
| 6 | The payload bound before transmission and described inspectably after it | **Unchanged** — `EgressBinder` derives the binding; `parameters_digest` binds the payload; ADR-0150's spans describe it. #57's granularity residue is carried, not closed |
| 7 | A named approver able to refuse | **Unchanged** — `ActionPolicy` is the authority and the user is the approver (ADR-0148 §8); §9 states what a refusal does here |
| 8 | What is transmitted is bound to what was authorised, immutably, and consumed unchanged | **Unchanged** — `ToolCall` is unconstructable unless `PermissionDecision.authorises` holds, and is frozen; §6 |
| 9 | Multi-recipient calls authorised as one set | **Not applicable, and stated rather than skipped** — one call names one origin, so the canonical destination set is a singleton; ADR-0148 §4's whole-set rule holds vacuously and is not relaxed |
| 10 | Destinations canonicalised per protocol, exact where equivalence is unproven | **Attested anew** — §8, which is the ADR-0150 §3 contract ADR the new member requires |
| 11 | Resolving a name to an identifier is a gated audited call, or is forbidden | **Unchanged (forbidden branch)** — nothing resolves a recipient *name* to an address here; the origin is the connected account's own configured value, compared as text before it is parsed. Name resolution performed by the transport to reach a pinned host is not this condition's subject, exactly as it is not for SMTP |
| 12 | Audit records carry an attempt identifier and an explicit outcome | **Attested anew** — §6; the bearer is ADR-0192's invocation claim rather than a step execution, and the four outcomes and the reconciliation path are unchanged |
| 13 | Outbound payload classification settled | **Unchanged, with ADR-0154's own limits carried** — §5's declaration states the tiers; ADR-0146 §5's third clause is undischarged here exactly as it is everywhere, #1150 is untouched, and no gate in the tree reads a span's tier |
| 14 | Failure paths tested, not just the happy path | **Attested anew** — §18's failure arms, which the implementing lane owes for the transport as ADR-0154 §4 required of the SMTP exchange |

**Two things this table is careful not to claim.** It does not attest that a search
integration exists — none does, and §17 is where it is built. And it does not
re-attest the seam: ADR-0154 §4's rows stand on the code they name, and the three rows
marked *attested anew* are obligations on the implementing lane stated here so that
lane meets them as conditions rather than discovering them.

**#1154, #75 and #95 are untouched and each is live here.** Nothing in the tree
distinguishes an egress span drawn from the assistant's own store (#1154) — §3 and §4
close that gap for *this* payload by construction rather than by mechanism, and the
general absence stays exactly as ADR-0155 §4 records it. Nothing detects a secret the
user pasted into their own utterance (#75), and the composer may carry it into a
query; that is the same corridor ADR-0098 §5 says stays open, and §12 restates the
honesty clause. And ADR-0154 §6's residency clause binds this registering lane: §14.

### 8. `DestinationProtocol.HTTPS`: the canonical form, the grammar, and what it does not establish

> **Normative.** `DestinationProtocol` gains one member, `HTTPS`, valued `https`.
> This section is the ratified contract ADR that member requires (ADR-0150 §3), and it
> states below exactly which equivalences the protocol establishes and which it does
> not. The member **authorises nothing**: it registers no tool, permits no
> transmission, and implies no canonicaliser beyond the one this section fixes.

> **Normative.** The **canonical form** of an `HTTPS` destination is
> `https://<host>:<port>` — the scheme, the host and the port, always all three, with
> the port rendered explicitly even where the supplied form omitted it. It carries
> **no path, no query, no fragment, no userinfo and no trailing separator**. Two
> supplied forms denote one recipient when and only when their canonical forms are
> byte-identical.

> **Normative.** The **equivalences this protocol establishes are exactly three**: the
> scheme differs only by ASCII case; the host differs only by ASCII case; and one form
> omits the port where the other states `443`. Every other difference makes two
> destinations, and the comparison is otherwise exact — ADR-0017 §3's condition 10
> read as ADR-0154 §4 attested it.

> **Normative.** The equivalences this protocol **does not** establish, each stated so
> that no lane infers it: no equivalence between a name and any address it resolves
> to; none between a host with a trailing dot and one without; none between a
> percent-encoded octet and its decoded form; none between an internationalised host
> and any ASCII-compatible encoding of it; none between `http` and `https`; and none
> at all involving a path, a query or a fragment, which are not part of a destination.

> **Normative.** The canonicaliser **refuses** rather than canonicalises a supplied
> form that: names a scheme other than `https` after ASCII case-folding; carries
> userinfo, a path other than the empty one, a query or a fragment; has an empty host;
> has a host carrying any character outside ASCII letters, digits, `-` and `.`; has a
> host with a leading, trailing or doubled `.`, a label longer than 63 characters, a
> label beginning or ending with `-`, or a total host length above 253; has a host
> that is an IP literal in any notation; or states a port that is not one to five
> decimal digits without a leading zero denoting a value in 1–65535. A refusal is an
> `EgressBindingError` at the derivation, never a silent normalisation.

> **Normative.** The canonicaliser lives at the seam, in `ai_assistant.tools`, and
> **never in `core`** — ADR-0148 §2's sixth clause, and the reason
> `DestinationProtocol.SMTP`'s own contract gives: *"a copy of the rule in `core` would
> be the second canonicaliser that clause exists to forbid."*

> **Normative.** This section **does not repair `parse_smtp_endpoint`** and closes
> neither #1147 nor #1158. Those defects stay open on their own terms; what this
> section owes them is not to reproduce the one they name, and the grammar above is
> written for that reason.

**The origin and nothing below it, because a path is not a recipient.** ADR-0148 §2
makes a destination the *semantic recipient the arguments select*, and ADR-0017 §3's
own words warn against the coarse version — *"authorising `googleapis.com` would let a
send reach any address"*. For SMTP the recipient is an address and the host is a
detail of reaching it; for HTTPS the recipient **is** the origin: it is the party that
receives the bytes, holds the credential's audience, and is what a user could
recognise and grant. A destination carrying a path would make the grant, the
confirmation and the comparison range over a value the request composes per call, and
two calls to one provider would be two recipients — which is a false statement about
who received the query and would make a standing grant either useless or
over-permissive.

**Refusing rather than canonicalising is condition 10's own direction.** ADR-0154 §4
attests destinations *"canonicalised per protocol, defaulting to exact comparison"*,
and the failure that matters is two forms that denote one recipient being read as two,
or worse, two that denote different recipients being read as one. Every refusal above
is a form whose equivalence class this ADR cannot state truthfully — an
internationalised host has an IDNA answer this ADR has not evaluated and will not
guess; a trailing dot is the DNS root and whether it denotes the same origin is a
resolver question; an IP literal has a whole notation family behind it. #1158 is the
worked example of what happens when an authority is accepted without a grammar, and
the grammar above is the smallest one that admits every ordinary provider origin and
nothing whose meaning is unsettled.

**And the member is a safety claim, which is why ADR-0150 §3 put it behind an ADR.**
`DestinationProtocol`'s own contract says a member *"is a **safety claim**, not a
label: its whole content is a ruling about which two supplied forms denote one
recipient"*. The three equivalences above are the whole of the claim, and the six
non-equivalences are stated because a canonicaliser that quietly added one would be
widening a grant nobody widened.

### 9. The ruling: what makes a search `ALLOW`, and what a non-`ALLOW` does

> **Normative.** A `WEB_SEARCH` request is serviced **only on an `ALLOW`**. On any
> other ruling — `CONFIRM`, `DENY`, or an `ActionPolicy` that raised — no channel is
> opened, no credential is read, no record is minted, the read budget is untouched,
> and the servicing of this kind yields nothing.

> **Normative.** **The servicer asks the user nothing and parks nothing.** ADR-0226
> §5's clause binds unchanged: a servicing that did not yield leaves the supply as
> planning saw it, the turn composes from it, and no implementation raises out of the
> turn, parks it, or puts a question to the user on account of a read that did not
> land. A recorded `CONFIRM` on a `WEB_SEARCH` decision **resolves in no turn**: no
> lane resumes it, offers it to an interface, or treats it as outstanding work, and
> §19 defers the surface that would.

> **Normative.** **The composing stage is told nothing new**, and the assembled prompt
> on a turn whose search was refused is byte-identical to what it would be had the
> planner asked for nothing. ADR-0228 §10's carrier is stated over a turn that stopped
> at the bound or the budget and is neither widened, re-used nor read as covering this
> case.

> **Normative.** **No lane makes a search reachable by weakening its declaration.**
> A `discloses` narrowed to reach an `ALLOW`, a `risk_level` or `reversibility`
> restated for that purpose, a `cost` declared `FREE` where the figure is not known,
> or a deployment setting that suppresses the disclosure floor are each the
> mis-declaration ADR-0016 §1 and ADR-0148 §2 refuse, and no reading of this ADR
> licenses one.

> **Normative.** The one route to an `ALLOW` is ADR-0193's **standing recipient
> grant** over the provider's canonical destination set, established by a recorded act
> of the user, and ADR-0193 §4 binds unchanged: no grant covers a request whose
> binding carries `planned_with_external_content`. This ADR **decides no surface for
> establishing a grant**, and ADR-0193 §13 forbids it deciding one.

**So on `origin/main` today a search is never serviced, and that is stated here rather
than found at the probe.** The chain is short and every link is ratified. The
declaration's `discloses` is non-empty because a query composed from the user's words
is Tier 1 leaving the device, so `ThresholdActionPolicy`'s disclosure floor fires and
`ActionPolicy` returns `CONFIRM`. ADR-0148 §3's route (a) needs a recorded resolution
of a `CONFIRM` about this request, which needs someone to ask, which ADR-0226 §5
forbids the servicer doing. Route (b) needs a grant, and `app/composition.py` records
the state of the store in terms: *"until a surface offers the establishing act (§13)
the store is empty, so every ruling is the one it was before."* The mechanism is
therefore **legible and inert**, exactly as ADR-0230's fetcher is inert until a root is
configured, and §19 names the surface as its firing condition.

**That is the corpus's answer and not an accident of sequencing, which is why this ADR
does not engineer around it.** ADR-0154 §2 is explicit that there is *"no first-use
exemption, no configuration that grants a standing authorisation for a recipient, and
no route by which designation pre-authorises anything"*, and ADR-0148 §3's second
clause refuses in terms every near-miss a lane would reach for here — *"a tool's own
declaration, the scope or audience of a credential, a configured base URL or host, an
allowlist the system assembled"*. A search that reached a third party because an
operator had configured a provider would be each of those at once. The question "may
this system talk to this party?" is the user's, it has one ratified answer mechanism,
and the mechanism's surface is another lane's.

**Three alternatives were available and each is refused on the record.** *Parking the
turn on a read* would put a durable confirmation, a resume path, a wire operation and
a surface behind a mechanism ADR-0226 §5 designed to be invisible, and would let a
marginal improvement in reach take a reply down — the exact posture that section
adopted and the reason it adopted it. *Recording a pending confirmation for the user to
answer later* invents an outstanding-work concept the corpus has nowhere to put and
that nothing would resolve. *Declaring `discloses=()`* on the ground that the search
integration is not a **registered** tool, so ADR-0148 §8's second clause does not
reach it literally, is the loophole this ADR most wants named: the clause's purpose is
that ADR-0021 §5's floor bites on every egress call, the query is Tier 1 and does
leave the device, and taking the loophole would auto-grant the one call this system
makes to a party the user never named.

**What a deployment can change, stated so that nobody reads inertness as
permanence.** Two things make a search serviceable and both are the user's or the
operator's: a standing grant, once a surface offers the establishing act; and the
thresholds `Settings` already exposes, which govern the risk and reversibility rows but
**not** the disclosure floor or the external-content floor, neither of which is
configurable. A third thing does not: nothing in this ADR, and nothing a lane may add
under it, makes a search fire without the user having authorised the recipient.

### 10. What a search mints, and the attestation under ADR-0092 §3 unamended

> **Normative.** A `WebSearcher` mints the records; nothing outside it stamps a
> `Provenance` for a search result. A successful search mints **at most
> `SEARCH_MAX_RESULTS` `MemoryRecord`s**, one per result the provider returned, in the
> order it returned them, of kind `SEMANTIC`. No model is on that path: nothing
> summarises, abridges, rewrites, re-ranks, annotates, deduplicates or classifies a
> result between the provider's response and the record.

> **Normative.** A record's `content` is **three spans the provider supplied**, in a
> fixed order and each verbatim: the result's **title**, the **address** it reported
> for the result, and the result's **snippet**, one per line, separated by a single
> `\n`, with no other byte added. Where the provider supplied no title or no snippet
> the line is omitted and the remaining lines keep their order; a result for which the
> provider supplied **no address** is dropped. This form is fixed here so that two
> conforming implementations over one response produce byte-identical records; it adds
> no word of this system's, and is a **transcription** rather than a rendering in
> exactly the sense ADR-0230 §5 gives for a decoding.

> **Normative.** A record whose `content` exceeds `SEARCH_MAX_RESULT_CHARS` — measured
> as ADR-0230 §6 measures a fetched document, on the JSON-quoted rendering the prompt
> will carry — is **dropped rather than truncated**, the remaining results are minted,
> and §13's audit counts the drop. Where every result is dropped the search yields
> nothing and is recorded as having yielded nothing.

> **Normative.** The record's `Provenance` carries `source=MemorySource.EXTERNAL`,
> which `band_of` places in the `ATTESTED` band, so
> `rests_on_recorded_external_content` is `True` for it. `confidence` is **0.9**, the
> figure the corpus's other attested producers carry and for their reason (ADR-0038
> §2a). `evidence` is empty, `derived_from_external` is `False` and asserts nothing in
> this band (ADR-0106 §1), `topics` is empty, `about_person` is `None`, `placement` is
> the default that narrows nothing (ADR-0217 §6), and `validity` is fully open.

> **Normative.** The `Attestation` carries `reported_by` equal to the searcher's
> `name` — the **source instance**, "the owner's web search", never a vendor, never an
> origin, never a URL and never a credential (ADR-0092 §3) — and `extent` is `None`:
> this producer states no position for a result in the source's own world, and a
> result's rank is not a half-open interval of instants (ADR-0117 §2).

> **Normative.** **`reported_at` is the instant the provider's own response declares,
> on the provider's own clock, and there is no substitute.** ADR-0092 §3 binds as
> written: it is not the instant we sent the request, not the instant we received the
> response, not a clock this system read, and not a value derived from any of them. A
> response that declares **no** instant mints **no record** — the whole search yields
> nothing and §13's audit records the class. `Provenance.last_updated` and
> `last_confirmed_at` are ours and keep ADR-0045 §3's meaning.

> **Normative.** **What is attested is the provider's claim about what its index
> returns for this query**, and the record makes **no claim about when the words it
> carries were composed, by whom, or whether they are true.** No lane states or
> implies otherwise, derives an authorship instant from a result, or reads a
> `reported_at` here as a fact about a page.

> **Normative.** The record's `id` is **minted by the searcher and opaque to the
> source** (ADR-0092 §6). It is never rendered to a model, never accepted from one,
> and — since §16 stores nothing — never installed. `MAX_EVIDENCE_CITATIONS` and every
> other `MemoryWriter`-seam bound is not engaged, because no minted record reaches
> that seam.

**ADR-0092 §3 is honoured rather than superseded, and ADR-0230 §5 is why that is the
only available reading.** That section superseded §3's local-substitute clause in a
scope it states in terms — *"a source this system interrogates **directly**, whose
answer is produced at the instant of the read rather than replayed from an answer some
other source gave earlier"* — and then closes the door on this kind explicitly: *"a
kind whose fetch retrieves a remote source's earlier answer, or replays one from a
cache of its own, is outside this scope entirely and ADR-0092 §3 binds it as
written."* A search index **is** a store of earlier answers, and a provider may serve a
cached result set; nothing in a response tells us which. So the reasoning that made a
local root's read instant true by construction is unavailable, and the honest move is
the one ADR-0092 §3 already prescribes: take the source's own declared time, and where
the source declares none, mint nothing. *"The capability is bounded by what sources
can actually say, which is the honest place for the boundary."*

**In practice it rarely binds, for the same reason ADR-0092 §3 gives about
`DTSTAMP`.** An HTTPS response from an origin server that has a clock carries the
instant it was generated, and a provider that returns a structured result set commonly
declares one in the body as well. The implementing lane states, for the provider the
owner chose, **where** that instant is read from and what makes the value the
provider's own statement rather than our reading of it; the rule is written for the
provider that declares none, so that lane meets it as a constraint rather than
reaching for the nearest local clock. Refusing to mint is not a degradation to repair:
a result set we cannot attest is one we would have to lie about to put in the
`ATTESTED` band, and ADR-0092 §1's validator settles the outcome structurally rather
than by discretion.

**The attested source is the provider and never the page, which is the same
distinction ADR-0230 §5 drew for a root and a document.** `reported_by` names the
search source instance; what it reports is *what its index returns for this query
now*. It is not a claim that the page is accurate, that its author said anything at a
particular time, or that the snippet is a faithful excerpt of the page. Those are
facts about parties this system has not spoken to, and stating any of them would be
ADR-0073 §4's *"a true statement about us and a false one about the source"* one seam
further out. §19 defers a page-declared authorship instant by name, with the consumer
that would fire it.

**The address is in `content` because there is nowhere else true to put it, and this
is a decision rather than an omission.** #1908 and this lane's brief both describe a
record whose `Provenance` names the URL. No field can: `Provenance` has no address
field, `Attestation.reported_by` is the source instance and ADR-0092 §3 forbids
putting in it *"a filesystem path that discloses more than the source's identity"*,
and `Attestation.extent` is a pair of instants. Adding one would be `core` surface for
a value only this kind produces, on a model every record in the store carries — and
ADR-0230 §5 decided the neighbouring case the other way, keeping a fetched document's
address off the record entirely. What is different here is that the address **is part
of what the provider reported**: a search result *is* a title, an address and a
snippet, and dropping the address would be transcribing two of the source's three
spans. So it goes where the source's words go, and no `core` field is added.

**And an address in `content` is shown, never acted on.** The record is
`EXTERNAL`-sourced, so ADR-0098 §2's marking presents it to every model call as
third-party data, non-forgeably. ADR-0098 §3's first clause makes imperative text
inside it data — *"the span may not select a code path, set or alter a parameter, or
change a policy decision"* — and here that is structural rather than a rule: **no kind
of this envelope accepts an address from a model** (§2), a `WEB_SEARCH` ask carries no
argument at all (§1), and the query is composed from the utterance alone (§3). A URL
in the prompt is inert because nothing will take one, which is ADR-0230 §15's own
phrasing for why deferring the fetch is safe rather than merely smaller.

**Three results, and the figure is bounded rather than measured.** ADR-0226 §6's ten
is a measured figure; nothing has measured this one, and this ADR says so instead of
implying otherwise. What bounds it is the budget it draws from and the prompt it
enters: three results at `SEARCH_MAX_RESULT_CHARS` each is a prompt addition of the
same order as the episodic supplement's ordinary contribution, it leaves seven of
ADR-0226 §6's ten for the inward kinds, and it is small enough that §11's precedence
costs the other kinds little. §19 defers the movement of the figure to §13's audit
showing what a turn actually needed.

**The externality mark is the milestone's control and is argued from ADR-0098 §1
rather than assumed.** External content is *"any span of text that this system did not
author and did not receive from its own user"*, decided *"by **recorded origin**, never
by inspecting the text"*. A search result is a third party's words arriving as a
provider's answer; nobody exercised the judgement ADR-0098 §1 carves the user's own
utterance out for. ADR-0230 §5 reached the same place for a file on the owner's own
disk, on the stronger case; this one needs no argument at all.

### 11. Servicing: one site, one budget, and where the search sits

> **Normative.** A `WEB_SEARCH` ask is serviced in `orchestration/reads.py`'s
> `service_read_request` and nowhere else, inside the turn, after the planner returns
> and before the `TurnResult` is constructed. ADR-0226 §5 binds entire: the servicer is
> not the composing stage, is not a tool, is registered nowhere, advertises no
> capability, and a servicing failure degrades the turn and never fails it.

> **Normative.** **ADR-0226 §5's channel scoping binds this kind unchanged.** A
> request is not serviced on an operation whose output channel's audience is unbounded,
> and no lane services a `WEB_SEARCH` ask there on the ground that the reply will
> otherwise be thin. A planner on such a turn is not told; what is scoped is the
> servicing, so the trigger goes on being measured on every channel.

> **Normative.** **The servicing order is: local file, then web search, then citation
> hop, then sighted query.** ADR-0226 §6's decision is applied and not moved — the
> capped read ahead of the uncapped one — and this kind is capped by §10 at three
> records where the hop's cap is ten and the query has none.

> **Normative.** **One budget, and the search draws at most `SEARCH_MAX_RESULTS`
> slots of it.** ADR-0226 §6's budget of ten binds per servicing (ADR-0228 §7),
> counted after deduplication. It is not a share, not a second budget, and no lane
> funds it by lowering `RETRIEVAL_LIMIT` or `EPISODIC_SUPPLEMENT_LIMIT`. **Where fewer
> than one slot remains when the search is reached, no request is composed, no ruling
> is sought and no channel is opened**, and §13's audit records it.

> **Normative.** The minted records enter **ADR-0226 §7's fourth group**, appended
> whole with the rest of the servicing's yield in servicing order. There is no fifth
> group and no attested group (ADR-0228 §7); the three groups the planner saw keep
> their contents, their order and their positions; and §7's whole-union deduplication,
> discards-nothing-by-class clause and constructed-once rule bind on a minted record as
> on any other.

> **Normative.** **The order inside one servicing is: compose, then bind, then rule,
> then record, then send.** No channel is opened before a recorded `ALLOW` exists, and
> no query is composed after the ruling — the ruling is over the request the query is
> in, which is ADR-0148 §6's determinism and ADR-0150 §4's binding read forward.

> **Normative.** **The `planned_with_external_content` on a search request's binding
> is the disjunction of `rests_on_recorded_external_content` over the turn's
> pre-servicing supply and over every record this servicing has already contributed**,
> computed by `orchestration` at the moment the request is built, from records it holds
> as data it fetched. It is written onto the carrier before `EgressBinder.bind` and is
> discarded, never merged, if any producer emitted one — ADR-0181 §4 applied at a
> second call site and not widened.

> **Normative.** **A serviced search may revise the plan exactly as an inward read
> may.** ADR-0228 §2's seven conditions are unchanged and none of them is about the
> kind; no lane adds an eighth for this kind, and none suppresses a revision because
> the read was outward. §12 is where that is faced rather than glossed.

> **Normative.** **ADR-0223 §2's externality value and ADR-0204 §2's withholding
> value are computed once, over the turn's final supply**, exactly as ADR-0230 §7
> rules. Neither is computed twice, neither from an intermediate supply, and neither
> is the value the clause above computes for a binding — that one is a per-request
> fact at a per-request instant, and §12 states what the difference costs.

**The precedence is ADR-0226 §6's own rule and not a new one.** That section orders the
hop ahead of the query because *"ordering the capped read ahead of the uncapped one
makes the union the *measured* union in the ordinary case"* and because a query *"can
return the whole budget on every firing"*; ADR-0230 §7 put the file first for the same
reason, at one slot. Sorting the four kinds by their caps gives one file, three
results, ten via two labels, and then the uncapped query — which is the order above,
reached by applying a ratified rule rather than by preferring an outcome.

**The alternative was to service the search last, and it was refused for a reason
worth recording.** Last is the position at which the turn has selected the most, so the
origin fact on the search's binding would be the most complete. It is also the position
at which the budget is ordinarily gone: the sighted query is uncapped and fills what
remains, so a search placed after it would fire only on turns where the store returned
almost nothing new. That would make the kind's availability a function of how full the
budget happened to be rather than of what the planner asked for, and would put the
weakest-cap read ahead of the strongest namer — the inversion ADR-0230 §7 refused for
the file.

**So the residual is named instead of removed.** With the search third, an `EXTERNAL`
record that a *later* inward read of the **same** servicing would have contributed is
not in view when the search's binding is stamped, and that binding can therefore carry
`False` where the turn's final supply would have carried `True`. Three things bound it.
The pre-servicing supply — the tail, retrieval and the episodic supplement — is already
in view, and that is where an `EXTERNAL` record ordinarily comes from; a local-file
fetch is in view too, because it is serviced first and is always `EXTERNAL` (ADR-0230
§5). The value is monotone within a turn and across a conversation: nothing clears it,
ADR-0223 §1 stamps the captured episode from the **final** supply, and every later turn
of the conversation therefore sees it. And the fact is honest about what it is:
ADR-0181 §2's second clause and ADR-0223 §7 already forbid reading a `False` as an
assurance that nothing external was involved. What is left is one turn's window, on a
record the second inward read found and the first did not, and this ADR states it
rather than claiming a completeness it does not have.

**Compose before bind, because the query is what is being ruled on.** ADR-0148 §6
makes the payload description a deterministic derivation of the request's own
arguments and ADR-0150 §4 pins a span to a key of `parameters`; a ruling taken before
the query existed would be a ruling about a call whose payload nobody had. It costs the
composer's model call on a turn whose search is then refused — a real cost, paid by
every deployment with no grant — and the alternative costs correctness, which is not a
trade this corpus makes. §13 records the disposition so the cost is visible.

### 12. The steered loop: what closes it, and what it does not catch

> **Normative.** **A revision's request may be composed over a search result's
> content, and that is admitted rather than prevented.** No lane filters the fourth
> group, subtracts a minted record from a supply, narrows what a second planner call
> sees on the strength of a record's origin, or refuses a revision because the turn
> searched. ADR-0204 §4's narrowing prohibition, ADR-0226 §7's
> discards-nothing-by-class clause and ADR-0228 §11's no-filtering clause bind here
> unchanged.

> **Normative.** **No byte of a search result can reach a later search request.** The
> query is composed by a `QueryComposer` supplied the turn's own utterance and nothing
> else (§3); a `WEB_SEARCH` ask carries no argument (§1); and no component augments,
> re-ranks or annotates a query from anything (§4). This holds at every iteration and
> is a property of the two contracts rather than a rule an implementation keeps.

> **Normative.** **A second search in a conversation that has read a result is
> refused by the policy, not by a rule this ADR adds.** Once a minted record is in a
> turn's supply the binding of any later request in that turn carries
> `planned_with_external_content` (§11), ADR-0193 §4 admits no grant on such a request
> and ADR-0181 §5's floor admits no `ALLOW` but a decision of the user about that
> request, and §9 makes a non-`ALLOW` decline. On every later turn of the conversation
> ADR-0223 §1's stamped episode carries the fact into the supply and the same bar
> applies. **No lane adds a carve-out to any of those clauses for this kind**, and no
> lane makes a minted record invisible to `SelectionOrigin.over` in order to keep
> searching.

> **Normative.** **ADR-0098 §5's honesty clause binds this ADR as it binds every
> other.** No lane cites this section as authority that external content embedded in
> text whose recorded origin is not external is detected, that the corridor ADR-0098
> §5 describes has narrowed, or that a `False` on any origin fact is an assurance about
> anything.

**#1844's one genuinely new risk arrives on this rung and is answered in two places.**
Its shape is exact: *"iteration one reads attacker-controlled content; iteration two
decides what to fetch **based on it** … That is an exfiltration channel needing no
write capability at all."* ADR-0228 §11 could answer it by there being nowhere to
steer to, and ADR-0230 §8 by the address space being one configured root's listing.
Neither answer is available here: the address space is the world, and the loop can
reach it.

**The first answer is that there is no channel for the steering to travel down.** An
exfiltration channel needs attacker-chosen bytes to leave. Iteration two's request is
composed from the same utterance iteration one's was — the composer holds no record, no
supply, no tail and no prior query — so the bytes that leave are the same bytes that
would have left had iteration one read nothing. What a result **can** influence is the
planner's decision to ask for a search at all, which is one bit per iteration under a
bound of two planner calls (ADR-0228 §3), carrying no attacker-chosen content in either
direction. That is the whole of the channel, and it is a channel with no payload.

**The second answer is that the policy closes even that.** By §11's clause a turn that
has already minted a result carries the origin fact, so iteration two's search draws a
`CONFIRM` and is declined; and by ADR-0223 §1 the captured episode carries the fact
into every later turn of the conversation while it is in the tail. **This is #1908's
exit sentence, mechanically**: a search result is cited as a record, and that
conversation's egress asks first thereafter — for a second search, for an email, for
anything at the seam. It is ADR-0223 §6's product sentence with a second cause, and
that section already accepted its cost in terms: in a deployment with a reader enabled
this *"approaches 'every outward call in a conversation asks'"*. This decision enlarges
that population to deployments that search, and accepts it on ADR-0223's own reasoning
rather than re-arguing it.

**What the controls do not catch, said plainly.** **The first turn's query leaves.** A
conversation with no external record in its supply carries a clean binding, so a
standing grant covers the request and no one is asked; the query — the user's own
question, reformulated by a model that saw nothing else — reaches the provider, and the
provider keeps it under its own policy for as long as it likes. That is not a gap in
the controls; it is what the user authorised when they granted the recipient, and it is
the whole of what this rung does. **The conversation un-taints as the tail moves on.**
ADR-0223 §6's mechanism holds *"until the stamped episodes fall out of the tail"*, so a
long conversation regains a clean binding and may search again. That is ADR-0223's own
bound and not this ADR's to move; it is recorded here because a reader would otherwise
take the product sentence for a permanent property of the conversation. **And nothing
detects a secret the user typed** (#75): the composer is handed the utterance and may
carry a pasted credential into a query, exactly as `send_email` may carry one into a
body. ADR-0098 §5 says that corridor cannot be closed by a detector and ADR-0098 §6
forbids buying a bound from one; what this ADR adds to it is one more destination, and
it says so.

### 13. The audit

> **Normative.** ADR-0226 §9 binds entire and this kind adds **no second audit, no
> second event key and no new emission point**. One `INFO`-level structured log event
> per turn, under the one fixed key, emitted once, conditioned on nothing, carrying the
> ambient correlation identifier and **no other identifier**. A `WEB_SEARCH` ask
> appears in the servicing's kinds exactly as the other three do.

> **Normative.** The record gains **one field per servicing**: the **disposition** a
> `WEB_SEARCH` ask resolved to, where it resolved to one, and nothing where the search
> yielded records or where no `WEB_SEARCH` ask was made. It is a **member of a closed
> enumeration** and never free text, and it distinguishes at least: no search account
> connected; no budget slot remaining; the composer refused; the ruling was `CONFIRM`;
> the ruling was `DENY`; the spend gate refused; the request failed in transport; the
> provider refused the request; the response declared no report instant; the response
> carried no result this kind could mint.

> **Normative.** **The query, the address and the results are Tier 1 and this record
> carries none of them.** No query text, no fragment of one, no length of one, no
> origin, no host, no address, no title, no snippet and no provider message appears
> anywhere in this event. ADR-0226 §9's no-copy rule — *"counts and kinds, and copies
> no text"* — binds without qualification, and ADR-0004 §5's *"Tier 0/1 data must never
> be logged"* is why. What keeps the record inside Tier 2 is these clauses and not the
> redaction net.

> **Normative.** **The trigger is measured for this kind exactly as ADR-0226 §8
> measures it, from the first deploy, with no new instrument.** The fire rate, the
> novelty rate and the per-kind refusal rate ADR-0230 §9 added are all readable over a
> population of turns from this one event; every figure is computed over a population
> and never as a per-turn quantity; and no lane calls any of them precision or recall,
> for §8's unchanged reason.

> **Normative.** **A deployment with no search account connected, or none whose
> recipient the user has granted, reads a 0% yield for this kind, and that is a true
> statement about that configuration rather than a reading of a trigger.** No lane
> reports a figure for this kind without saying which of the two it is, and the
> disposition field is what tells them apart.

> **Normative.** **The permission decision and the invocation claim are the Tier 1
> record of what left**, and they are `AuditTrail`'s and `InvocationLedger`'s
> respectively (§6). This ADR adds no field to either, no store, no Protocol and no
> injected sink, and no lane invents one.

**One field and not a family, for ADR-0230 §9's reason.** Every other question §9 might
ask — how many records came back, how many were new, how many the deduplication
removed, whether the budget truncated, whether the servicing failed — is a
per-servicing count this kind contributes to unchanged. What only this kind produces is
a **decided non-yield**, and unlike ADR-0230's it has nine causes an operator would act
on differently: an unconnected account is a provisioning fact, an ungranted recipient is
a user act waiting to happen, a `DENY` is a policy the operator set, a spend refusal is
a ceiling, a transport failure is an outage, and a response with no declared instant is
a provider that cannot be attested (§10). Collapsing them would make the one field
useless at exactly the moment someone reads it.

**And what left the machine is recorded nowhere in full, which is a consequence rather
than an oversight.** The query is not on the `ActionPlan` — a `WEB_SEARCH` ask carries
no argument, so ADR-0226 §9's *"the ask stays durable on the frozen `ActionPlan`"* has
nothing to hold. It is not in the trail either: `ActionRequest.parameters` are *"bound
by digest, never stored"* (ADR-0148 §6), and `EgressBinding`'s spans state an argument,
a position, an extent and a tier and *"hold no content"* (ADR-0150 §10). So an auditor
can establish **that** a search was authorised, to which origin, at what instant, with
a payload of what extent, and whether it succeeded — and cannot establish what was
asked. That is the same property every egress call in this corpus has, it is the direct
consequence of two decisions taken to keep Tier 1 out of durable records, and it is
also precisely the gap ADR-0155 §3(b)'s content-bearing approval surface exists to close
on the *authorisation* side. §19 defers the durable record with what would fire it, and
names that lane by purpose as the one that would decide what a user is shown.

### 14. Residency, and no grant seam

> **Normative.** **ADR-0154 §6's residency clause is discharged here, for this
> integration.** A search integration's ordinary operation places **no** data of the
> owner's into a third-party service in the sense ADR-0004 §2's residency clause is
> about. It creates no account-side object, stores nothing, and writes nothing: it
> asks a question and reads an answer. What the provider retains is a record of having
> been asked, which ADR-0155 §5's third clause already states is beyond the reach of
> any control here and is the inherent cost of asking anything at all.

> **Normative.** No lane reads the clause above as an answer to #95, as an answer for
> any other integration, or as a claim that ADR-0155 §3 permits anything it does not.
> It is the statement ADR-0154 §6 obliges **this** registering lane to make, on the
> reading it states, and nothing more.

> **Normative.** This ADR adds **no `GrantScope` member**, contracts no `SourceGrants`
> into any seam it names, and gates neither the composer nor the search on a source
> grant. ADR-0097's grant seam, ADR-0132 and ADR-0133 are untouched, and no lane reads
> this section as relaxing any of them.

> **Normative.** **What authorises a search is the user's own turn over a recipient
> the user granted**, and both halves are required: the mechanism is off until an
> account is connected and a grant covers its origin (§9), and it fires only inside a
> turn the user started, only where that turn's planner asked. **No scheduled job,
> timer, proactive producer or background pass reaches a `QueryComposer` or a
> `WebSearcher`**, and no lane wires either to anything that is not a turn.

> **Normative.** **Three things fire a grant decision, and a lane meeting any of them
> stops rather than proceeding.** A `WebSearcher` or a `QueryComposer` driven from
> anything that is not a user-started turn. A search whose yield is written to any
> store, which §16 forbids. And a composer supplied anything beyond the turn's own
> utterance, which §3 forbids and which would make the query a different object under
> ADR-0155 §3.

**The residency statement is short because the case is easy, and ADR-0154 §6 requires
it to be made anyway.** That section's clause is stated over *"a lane registering an
integration at this seam"* and requires the lane to say whether the integration's
ordinary operation puts the owner's data into a third-party service, *"and on what
reading of that clause"*. A write-capable integration — the case ADR-0017 §1 had in
mind when it sent the question to #95 — creates a durable object in someone else's
account. A search creates none: the provider learns that a question was asked, which is
a log line about an interaction rather than the owner's data relocated into a second
custodian. ADR-0155's own §5 already covers the residue on the recipient side and
refuses to let §2 imply otherwise.

**The grant seam is absent for ADR-0230 §11's reason, which transfers whole.**
`SourceGrants` exists because *"A driver handed the whole store is a scheduler job that
can mint its own authorisation"*; there is no timer here, nothing is written, and the
driver is a turn the user is sitting in front of. ADR-0133 §2 fixes the grant axis at
one scope per consumer of a **reading**, and a `WebSearcher` produces no
`SourceReading`. What *is* gated is the far more consequential thing: the recipient,
by ADR-0193's machinery, per §9.

### 15. Spend

> **Normative.** **The search's transport call is admitted by a `SpendGate` before it
> is made** (ADR-0194 §3), held by the searcher inside the seam and never by
> `orchestration`, over the `ToolCost` the declaration carries. The searcher holds no
> `SpendLedger`, appends no row, and reads no totals projection. A refusal by the gate
> is a disposition (§13) and never a retry.

> **Normative.** This ADR sets **no ceiling of its own**, adds no `Settings` field for
> one, and adds no per-turn, per-conversation or per-day monetary bound beside
> ADR-0194's. A deployment that configures none has none, exactly as ADR-0194 §1
> rules.

> **Normative.** **The composer's model call is outside ADR-0194's subject and this
> ADR accounts for it nowhere.** No lane reads §15 as bringing model spend under a
> `SpendGate`, as declaring a `ToolCost` for a completion, or as claiming this
> mechanism's cost is bounded in money. What is bounded is the **count**: one composer
> call and at most one provider call per servicing, at most two servicings per turn
> (ADR-0228 §3), no retry and no second page (§1).

**#1548's spend-ceiling finding is answered with the corpus's own instrument rather
than a new one.** That survey's third subject is what caps *"what the world may
cost"*, and ADR-0194 built the cap: a gate consulted *"the instant before the act"*,
reading the declared cost, the configured values, the clock and the rows, and *"no
caller-controlled value"*. Routing the search past `ToolInvoker.invoke` (§6) would have
dropped that gate on the floor, which is exactly the kind of loss an amendment makes
silently; naming the gate here and putting it inside the seam keeps it. And the
declaration's `cost` being `UNKNOWN` where the operator configured no figure is what
makes the whole thing hold together: an unpriced provider confirms rather than runs
(§5), so the gate is never asked to count a call it cannot price.

**The composer's spend is stated as unaccounted because the honest answer is that it
is.** ADR-0194's subject is `ToolCost` on an invocation, and a model completion is not
one; this system meters no model spend anywhere. A turn that emits a `WEB_SEARCH` ask
therefore costs one extra completion whether or not the search is ever serviced (§11's
compose-before-bind order), and on a deployment with no grant that is a completion
spent for a refusal. §19 defers model-spend accounting by name, and §13's disposition
field is what makes the waste visible in the meantime.

### 16. Persistence, and the versions that move

> **Normative.** **A minted record is supply and never a store write.** No minted
> record is ingested, proposed, folded, superseded or written to the `MemoryStore`, and
> nothing is written to any store on account of a search. It reaches
> `MemoryWriter.ingest` at no point and is not exempt from ADR-0093 §1's rule — that
> rule governs what a producer **proposes to memory**, and this producer proposes
> nothing.

> **Normative.** **It is not a citation target and not a durable reference.** Its `id`
> is minted for one turn, rendered to no model, accepted from none, and resolves in no
> store; nothing writes it into a `Provenance.evidence`, and no later turn reaches it.
> A `CITATION_HOP` naming a minted record's label on a turn's second call reaches the
> record itself (ADR-0229 §1) and finds its `evidence` empty, which is the correct
> answer and not a degradation.

> **Normative.** **What persists is the turn, through the path that already persists
> it.** The episode captured for a turn that searched carries the exchange as it always
> does and is stamped `derived_from_external` by ADR-0223 §1's disjunction, and the
> observer reaches it as it reaches every other episode. This decision adds no capture,
> no writer and no second retention rule.

> **Normative.** **A second turn re-searches** — where §9 and §12 permit it at all —
> and mints records whose `reported_at` is that response's declared instant. There is
> no earlier record to contradict, no fold, no supersession and no staleness question,
> because nothing was retained.

> **Normative.** **Retention by address in a source-material archive is deferred, not
> declined**, and §19 names what fires it. **No archive entry is admitted to a prompt,
> to the supply or to a citation resolution by this ADR** (ADR-0225 §4, §12), and no
> implementing lane leaves a hook for one.

> **Normative.** **`PROTOCOL_VERSION` moves 28 → 29**, and `wire/envelope.py`'s log
> gains an entry naming this ADR and this reason. `ActionPlan` is carried to a client
> inside `TurnOutcome.turn.plan` (ADR-0228 §6), `wire/codec.py`'s projection dumps
> every field of a model, and `ReadAsk` sets `ConfigDict(extra="forbid", frozen=True)`,
> so a peer whose `ReadKind` predates `WEB_SEARCH` fails to decode a `TurnOutcome`
> whose plan carries one.

> **Normative.** **`PlanExport.schema_version` moves 5 → 6**, by ADR-0039 §10's
> mechanism as ADR-0226 §4, ADR-0228 §6 and ADR-0230 §12 last applied it: the
> annotation is edited rather than defaulted, so a document of an earlier shape does
> not validate against this contract at all.

> **Normative.** No lane reads this section as authority for bumping on a defaulted
> addition alone. What obliges each move is the conjunction ADR-0228 §6 states — a
> wire-carried type, a projection that emits defaults, and `extra="forbid"` — and
> ADR-0213 §11's no-bump ruling stands for the case it decided. This ADR neither
> repairs nor inherits **#1956**.

**Turn-scoped for ADR-0230 §10's reason and one of its own.** Writing a search result
into the belief store would put an object into `MemoryStore` that supersedes nothing,
folds with nothing and is retrieved by relevance against beliefs — ADR-0092 §7 already
records what the second read of an edited source does (*"a small edit folds; a rewrite
duplicates"*, #631, open). The reason of its own is sharper: a search result is a third
party's answer to a question, true of an instant, and the corpus has no mechanism that
would ever retire one. A stored search result would become an attested belief nobody
could correct, in a band where a user assertion is the only exit (ADR-0092 §5).

**What is genuinely lost is stated rather than minimised**: a second turn asking about
the same thing pays the search again, where §9 and §12 let it search at all, and a
conversation cannot cite a result a week later by pointer. The first is a bounded cost.
The second is real and is softened by the same thing that softens it for a fetched
file: the *answer* survives, because the turn's own episode carries what the assistant
said about the result through the capture path this decision leaves untouched.

### 17. What the implementing lanes owe

> **Normative.** **Five lanes, in order, each briefed from this ADR's merged text**,
> and none before this ADR is Accepted and merged (golden rule 5).

**Lane 1 — the query composer.** `core/protocols.py`'s `QueryComposer`;
`core/types.py`'s `QueryOutcome` and `QueryRefusal`; the `Settings` field for
`SEARCH_QUERY_MAX_CHARS` with its named default, its stated domain and its load-time
refusal; the **shared conformance suite**; the **canonical fake** in
`ai_assistant.testing`; and the model-backed composer in `ai_assistant.planning`, with
its prompt under ADR-0098 §2's marking and its parse. Nothing calls it yet.

> **Normative.** Lane 1 ships the **triad** — Protocol, shared conformance suite and
> canonical fake — **together with its primary production implementation**, under
> ADR-0137 §2. The demands that shape this contract are the composer's own: the single
> argument, the bounded output, the refusal set and the raise-for-nothing posture, none
> of which `orchestration` exercises.

> **Normative.** The conformance suite holds the clauses expressible **without a
> model**: an outcome carries a query **or** a refusal and never both or neither; a
> returned query is non-blank and within the bound; a composition over the bound is a
> refusal and never a truncation; `compose` raises for no composition reason and
> re-raises `CancelledError` unchanged when cancelled while suspended; and — the clause
> that fails an implementation that grew a second input — **the member takes exactly
> one positional parameter and no keyword parameters**, checked against the runtime
> signature. That last is a suite clause and not the concrete composer's because it is
> the clause on which §3's whole safety claim rests for **every** `QueryComposer` this
> system ever wires.

**Lane 2 — the destination protocol and the transport.**
`core/types.py`'s `DestinationProtocol.HTTPS`; the canonicaliser in
`ai_assistant.tools.destinations` implementing §8's canonical form, its three
equivalences and every refusal in its grammar; the HTTPS exchange inside
`ai_assistant.tools.egress` over `OutboundTransport`, holding §5's four properties; the
import-linter contract extension where a dependency is adopted, under ADR-0024's
pinning rule; and the failure-path suite ADR-0154 §4's condition 14 requires — a
refused redirect, a closed channel mid-response, a TLS failure, a response that is not
the shape the provider documents, a deadline, and each of §8's refusals. Nothing calls
it yet.

**Lane 3 — the searcher.** `core/protocols.py`'s `WebSearcher`; `core/types.py`'s
`SearchOutcome` and `SearchRefusal`; the **shared conformance suite** and the
**canonical fake** in `ai_assistant.testing`; the concrete searcher inside
`ai_assistant.tools.egress` — its declaration and its egress registration against a
connected account with **no registry entry**, its credential read through `Secrets` at
`SecretScope.INTEGRATION`, its `SpendGate` admission, its `InvocationLedger` claim and
completion, its transcription and its minting under §10; the `Settings` fields for
`SEARCH_MAX_RESULTS` and `SEARCH_MAX_RESULT_CHARS`; and `app/composition.py`'s wiring,
which constructs a searcher only where an account is connected and registers its
close among the resources it has opened (ADR-0042 §2).

> **Normative.** `WebSearcher` has three members and no more: `name`, a stable
> non-empty source-instance identifier; `request`, which returns the `ActionRequest`
> for a composed query or `None` where no account is connected and which **reads no
> store, mints no id and takes no decision**; and `search`, which takes an authorised
> `ToolCall` and returns a `SearchOutcome`. **`search` takes a `ToolCall` and never an
> `ActionRequest`**, so an unauthorised search is unconstructable at the type level —
> `ToolCall`'s own validator runs `PermissionDecision.authorises` — which is
> `ToolInvoker.invoke`'s guarantee obtained without `ToolInvoker`.

> **Normative.** The conformance suite holds the clauses expressible **without a
> provider**: a `SearchOutcome` carries records **or** a refusal and never both or
> neither; at most `SEARCH_MAX_RESULTS` records; every minted record is `SEMANTIC`,
> `EXTERNAL`-sourced, carries an `Attestation` whose `reported_by` equals `name`,
> carries an empty `evidence`, and carries a `content` within the bound; **a
> `SearchOutcome` carrying a record whose `reported_at` the outcome's own response did
> not declare is unconstructable**; `search` raises for no source reason and re-raises
> `CancelledError` unchanged; and `request` returns `None` or an `ActionRequest` whose
> `tool` is the searcher's own declaration and whose `parameters` carry exactly the
> origin and the query it was given. The canonical fake satisfies all of them without a
> network, and a test may drive it to each `SearchRefusal` member.

> **Normative.** Four rulings are deliberately **not** suite clauses, and putting them
> there would be the error: that the transport follows no redirect and reaches one
> origin (a generic suite cannot make an arbitrary searcher's transport redirect —
> those are Lane 2's tests over a real exchange); that the declaration is absent from
> every `ToolRegistry` (a property of a composition, asserted in Lane 3's own
> composition test); that a real provider failure produces each refusal class; and that
> the credential is read inside the authorised call and never outside it. Each is named
> here so no lane reads its absence from the suite as its absence from the contract.

**Lane 4 — the kind and the emission.** `core/types.py`'s `ReadKind.WEB_SEARCH` and
`ReadAsk`'s validator arm; §16's two version moves; the prompt in
`ai_assistant.planning` that describes the kind and asks for it, and the parse that
reads one; and the extension of the shared `PlannerContract`
(`tests/planning/planner_contract.py`) so the model-backed planner and the canonical
fake are both held to it. `Planner.plan`'s signature is **unchanged**: nothing is shown
for this kind, so nothing crosses the seam, and a planner is not told whether a search
will be serviced — ADR-0226 §5's scoping posture applied, and the reason this lane
needs no contract change at all.

**Lane 5 — the servicing, the precedence and the audit.** In `ai_assistant.orchestration`:
§11's servicing order and budget clause; the compose–bind–rule–record–send sequence and
its origin-fact computation; §9's decline on any non-`ALLOW`; the minted records'
entry into the fourth group under ADR-0226 §7's deduplication; §13's one added audit
field; and `app/composition.py`'s wiring of the composer and the searcher into the
loop.

> **Normative.** **Lane 1, then 2, then 3, then 4, then 5, and each is useful alone.**
> A merged Lane 1 is a composer nothing calls. A merged Lane 2 is a canonicaliser and a
> transport nothing drives, reviewable against a real exchange before anything is
> minted. A merged Lane 3 is a searcher no turn reaches, in a deployment with no
> account connected. A merged Lane 4 is a planner that can ask for a search nothing
> services — §16's versions move here because that is where the wire shape changes.
> Lane 5 without them would be a servicer with nothing to service.

> **Normative.** Between Lane 4 and Lane 5 there is no mechanism: a Lane-4 turn's
> `WEB_SEARCH` ask reaches no composer and no searcher, adds no record to any supply,
> opens no channel, changes no reply and changes nothing a capture records. Nothing is
> deployed that §13's audit cannot measure.

> **Normative.** No lane invents a second servicing site, a second budget, a second
> audit, a second seam, a second `DestinationProtocol` member, a registry entry for the
> search declaration, a park, a resume, or a route by which a composer obtains anything
> beyond the utterance. No lane implements, prepares for, or leaves a hook for anything
> §19 defers.

**Five lanes and not three, under ADR-0137 §1**, whose test is where substantial new
machinery lands: *"A slice is one lane only if its implementation puts substantial new
machinery into at most one subsystem."* Lane 1 is `core` plus `planning` and rides §2's
triad exception. Lane 2 is new machinery in `tools/` — a canonicaliser and a protocol
exchange — with one `core` enum member. Lane 3 is `core` plus `tools/` and rides the
triad exception again, with the composition wiring §1's own carve-out covers. Lane 4 is
`core` plus `planning`, a prompt and a parse. Lane 5 is `orchestration`, which is
**adaptation** under §1 rather than new machinery: `service_read_request` already holds
the one servicer and three kinds' branches, and this kind adds a fourth under the same
budget and the same audit. Pairing Lane 2 into Lane 3 would put a transport, a
canonicaliser, a triad and a registration in one review; ADR-0230 §13 split its three
for less.

### 18. The representative-input tests this decision owes

> **Normative.** The implementing lanes owe tests for each of the following, and each
> is a test over behaviour rather than over a call count.

1. **The exit's search clause, first half: a search result is cited as a record.** A
   turn whose supply holds nothing about the subject; a connected search account whose
   origin a seeded `RecipientGrant` covers; a fake searcher returning one result whose
   snippet carries a distinctive word; the planner emits a `WEB_SEARCH` ask; the search
   is `ALLOW`ed on route (b); one record is minted; and **the reply carries the word**,
   asserted through `orchestration/composing.py`'s **production renderer**, with the
   record's origin phrase rendered as ADR-0223 §4 renders an attested one.
2. **The exit's search clause, second half: that conversation's egress asks first
   thereafter.** The same conversation's **next** turn plans a step at the egress seam;
   the binding carries `planned_with_external_content`; the same seeded grant covers the
   same destination set; and the ruling is **`CONFIRM` and not `ALLOW`**, asserted
   through the production `ThresholdActionPolicy` with a real `RecipientGrants`. The
   assertion is that the grant did not cover it, and the cause is ADR-0193 §4 with
   ADR-0223 §1's stamp behind it — not a rule this ADR added.
3. **A second search in the same turn is refused, and no channel is opened.** A turn
   whose first servicing minted a result and whose revision emits a second
   `WEB_SEARCH` ask: the second request's binding carries the origin fact, the ruling
   is not `ALLOW`, the searcher's `search` is **never reached**, and §13's disposition
   records the `CONFIRM`. Asserted over a searcher fake that fails the test if `search`
   is called.
4. **The composer never receives a record, and the assertion is mechanical.** The
   conformance-suite clause of §17 — the member's runtime signature takes exactly one
   positional parameter and no keyword parameters — plus a servicing test in which the
   supply holds a record with a distinctive span and the messages the composer's
   `ModelProvider` fake received are asserted to contain the utterance and **no byte of
   that span**, no tail, no listing and no rationale. This is #1154's shape asked of one
   payload: the general absence is untouched, and what is asserted here is what this
   payload was built from.
5. **A `WEB_SEARCH` ask carrying an argument is unconstructable.** `ReadAsk(kind=WEB_SEARCH, query=…)`,
   `labels=…` and `entry=…` each refuse at construction, and a bare `WEB_SEARCH` ask
   validates — the arm of §1 asserted at the model, not at a caller.
6. **A non-`ALLOW` degrades the turn and never fails it, and the prompt does not
   move.** With no grant seeded: the turn completes, the reply is composed from the
   supply planning saw, no record enters the fourth group, the read budget is
   unspent, the assembled prompt is **byte-identical** to the same turn with no
   `WEB_SEARCH` ask, and §13's disposition names the `CONFIRM`.
7. **No budget, no request.** A turn whose local-file fetch and whose earlier yield
   leave no slot: no query is composed, no ruling is sought, `search` is never reached,
   and the disposition says so.
8. **A response declaring no report instant mints nothing.** The searcher's own test,
   over a response the provider shape admits and that carries no declared instant: the
   outcome is a refusal, and the suite's unconstructability clause covers the type-level
   half.
9. **A result over the content bound is dropped and its siblings are minted**, and a
   response every one of whose results is over the bound yields nothing.
10. **`HTTPS` canonicalisation.** `HTTPS://Example.COM` and `https://example.com:443`
    canonicalise identically; each of §8's refusals is refused — a non-`https` scheme,
    userinfo, a path, a query, a fragment, an empty host, a non-ASCII host, a trailing
    dot, a doubled dot, an over-long label, a hyphen-edged label, an IP literal, a port
    with a leading zero, and a port outside 1–65535 — and `https://example.com/a` and
    `https://example.com/b` are **one** destination after the path is refused, never two.
11. **A redirect is a refusal.** Lane 2's transport, driven against a fake exchange that
    answers a redirect: no second channel is opened, no credential reaches a second
    origin, and the refusal class is the one §13 records.
12. **The declaration is in no registry.** The composition test asserts that
    `ToolRegistry.capabilities()` and `all_tools()` on the wired registry hold no member
    of the search declaration, on a deployment with a search account connected — the
    property §5 rests on, asserted where it can be broken.
13. **The credential is read inside the authorised call and nowhere else**, and a
    turn whose ruling was not `ALLOW` reads none — the `Secrets` fake fails the test if
    `get` is called on that path.
14. **The invocation is claimed and completed**, and `orchestration` claims nothing: a
    serviced search leaves one claim completed with a `SUCCEEDED` outcome, a transport
    failure leaves one completed with a failure outcome, and a crash between them leaves
    an open claim the existing recovery scan closes as `INDETERMINATE`.

### 19. Deferred, by name, each with what fires it

- **A surface for establishing a recipient grant.** The condition that makes this
  mechanism fire at all (§9). ADR-0193 §13 rules that *"No lane reads this ADR as
  deciding **which** surfaces offer the establishing act, what the wire carries for it,
  or how a browser or command-line surface lays it out"*, and assigns them to ADR-0177,
  ADR-0178 and ADR-0186. Fired by those lanes. **Not** fired by this one, and no lane
  reads this ADR's dependence on it as licence to mint a grant beside them.
- **Fetching a result's URL.** An egress **selected by external content**, which
  ADR-0154 §4's actuator clause forbids at this seam in terms — *"No egress call
  through the designated seam is selected, parameterised or confirmed by external
  content, in ADR-0098 §1's sense of a recorded external span"* — and which ADR-0098 §3
  assigns to the designating lane. A search result's address **is** a recorded external
  span. Fired by an ADR superseding that clause, or by a design in which the **user**
  picks the result, which is a user act ADR-0193's machinery already knows how to
  record. Not fired by a lane finding a snippet thin.
- **Fetching a URL the user typed.** Not blocked by the clause above — ADR-0098 §1
  carves the user's own utterance out of external content — but a third address space
  with its own grammar (#1158 is its precondition), its own arbitrary-host destination
  problem, and its own extraction dependency. Fired by the ADR that decides those three.
- **A memory-enriched query.** The relaxation ADR-0155 §3 reserves to fork (b), whose
  content-bearing approval surface is being designed in a parallel ADR lane cited here
  by purpose. This ADR pre-empts nothing about it: it decides no approval surface, shows
  the user nothing, and takes no position on what a relaxation would permit. Fired by
  that ADR ratified **and** implemented, and by a follow-on lane widening this kind.
- **A durable record of the query that left**, and with it the join from §13's audit to
  the content of a search. §13 explains why nothing holds it today. A Tier 1 store of
  outbound payloads is a decision about retention and data rights, not about this
  mechanism. Fired by an audit requirement nobody has stated, or by the approval-surface
  lane deciding what a user is shown before a send.
- **Moving `SEARCH_MAX_RESULTS`, or a second search per servicing.** §10's three is
  bounded rather than measured and §1 admits one request per ask. Fired by §13's audit
  showing what turns actually needed. Not fired by a lane finding three results thin.
- **Model-spend accounting for the composer's call** (§15). Nothing in this system
  meters model spend. Fired by the ADR that decides a model-spend surface.
- **Telling the user that a search was refused.** §9 gives the composing stage nothing,
  and a reply that said *"I would have searched but I am not permitted"* is a product
  surface with a user action behind it — which is the grant-establishing act, and
  therefore that lane's to design together with the message. Fired by that lane.
- **A second search provider, or a provider the user names in the turn.** §5 fixes one
  connected account. A second is a precedence and destination-set decision; a
  provider named in a turn is a model-reachable address by another name and §2 forbids
  it. Fired by an ADR deciding how several outward sources are ordered.
- **A page-declared authorship instant.** §10 takes the provider's declared response
  instant and states that no record here says when a page's words were written. A
  format or a provider that declares one has a claim ADR-0092 §3 would prefer, and using
  it needs a rule for an absent, malformed or future one and a consumer that benefits.
  Fired by that consumer.
- **Retention by address in a source-material archive** (#1907, ADR-0225 §11). §16
  keeps a minted record for one turn. Fired by that store existing **and** by an ADR
  answering ADR-0225 §4's admission question for it. Not fired by a lane finding a
  re-search wasteful.
- **A search on a channel of unbounded audience** (§11, ADR-0226 §5, §12). Deferred for
  ADR-0203 §2's backfill reason, unchanged by this kind. Not fired by a lane finding
  spoken replies thin.
- **Reconsidering `risk_level`** (§5). A judgement that `MEDIUM` is the honest figure
  makes the mechanism unserviceable under the shipped thresholds. Fired by the owner or
  by an ADR revisiting ADR-0016 §2's scale; the consequence is stated in §5 so that
  such a lane knows what it is moving.
- **Anything §13's record would need a store to answer.** ADR-0226 §12 defers a
  durable, queryable surface for the audit; this kind adds one field to the same log
  event and inherits that deferral whole.

### 20. Scope, and what this records against earlier ADRs

**This ADR amends four ratified ADRs — ADR-0226 in three scopes, ADR-0230, ADR-0148
in two scopes and ADR-0154 in one each — and supersedes none.** That is a
classification of this change and is therefore stated as prose rather than marked
(ADR-0089 §1). The header carries each record; what follows is the working under
ADR-0082 §1's test, and the clauses a reader would most expect to have moved and which
did not.

**Why every record is an amendment and none is a supersession.** ADR-0070 §1's test is
whether a reader acting on the earlier text today does the wrong thing. On every clause
below the answer is no: ADR-0226 §2's membership sentence undercounts a closed
enumeration a reader can read off `ReadKind`; §4's not-ruled-on clause is true of the
three kinds it was written about and of every kind whose servicing reads the owner's
own store; §6's and ADR-0230 §7's precedence sentences state an order that is still
correct on the reads they name; ADR-0148 §1's single route and §9's claimed step are
true of every tool call, which is every send this system makes today; and ADR-0154 §2's
restatement is true of every send at the seam until Lane 3 lands. A reader holding only
the earlier text would in each case read a sentence **more widely than it now holds** —
ADR-0082 §1's test — and would not be led into an error. So each is a record on the
earlier ADR and none replaces a ruling.

**ADR-0148 §9 is the one a reviewer should press, and the answer is that the property
moved bearers rather than being narrowed.** Its clauses exist to satisfy ADR-0017 §3's
condition 12, which ADR-0154 §4 attested; and ADR-0154 §4's own clause says a change
falsifying a subsection's property removes designation's ground unless the lane
*"restores the property in the same change"*. §6 restores it in the same change, on
ADR-0192's ledger, whose claim is keyed on the `PermissionDecision` an egress call
already has. What would have been a supersession is a change of bearer, and the
alternative — synthesising a plan step for a read, so that a clause about steps would
have a subject — is refused in §6 because it would put a `ReadAsk` in front of
`StepExecutor`, which ADR-0226 §4 forbids and which this ADR does not amend.

**Four ADRs a reader would expect to have moved, and did not.**

- **ADR-0155 §3.** Untouched, in every clause. §3 and §4 above take the route
  ADR-0155's own Consequences names, and the reserved fork is another lane's.
- **ADR-0092 §3.** Untouched. §10 takes the provider's declared instant and mints
  nothing where there is none, which is §3 as written; ADR-0230 §5's supersession scopes
  itself away from this kind and this ADR does not reach for it.
- **ADR-0226 §5.** Untouched, and load-bearing: the ask-nothing, park-nothing,
  never-fail-the-turn posture is what §9's decline rests on, and its channel scoping
  binds this kind unchanged.
- **ADR-0228 §11.** Untouched as a statement about ADR-0228, and its prohibition —
  *"no lane admits an outward kind here or reads this ADR as preparing for one"* — is
  honoured: this decision is taken on #1844, #1908, ADR-0226 §12 and ADR-0230 §15, and
  cites ADR-0228 toward none of it. §11's containment argument is **extended** rather
  than moved, and §12 above is the extension: ADR-0228's loop could reach only the
  store, ADR-0230's only the owner's disk, and this one can reach the world — so the
  argument that there is nowhere to steer to is replaced by two arguments of a different
  kind, that there is no channel for the steering to travel down and that the policy
  bars the second call. §11's class clause on a planner-composed query, its no-filtering
  clause and its no-recomputation clause bind unchanged and are cited in §3, §11 and
  §12.

**Two reservations are exercised rather than moved.** ADR-0154 §7 reserves a
`DestinationProtocol` member to an ADR like this one; §8 is that ADR. ADR-0150 §3
requires *"a ratified contract ADR for every further member, stating which equivalences
that protocol establishes and which it does not"*; §8 states three and six.

**And one obligation is discharged.** ADR-0154 §6's residency clause binds *"a lane
registering an integration at this seam"* to state whether the integration's ordinary
operation places the owner's data into a third-party service and on what reading; §14
is that statement, and it answers #95 for nothing else.

## Consequences

- **The loop can reach the world, and what it may say there is the user's own
  question.** This is the rung #1844 called the one genuinely new risk, taken with the
  content channel closed at the type level rather than by a rule: the planner has no
  field for a query, and the composer has no parameter for a record.
- **The mechanism ships legible and inert.** Until a user has granted a search
  provider's origin, every search draws a `CONFIRM` the servicer may not answer and the
  turn degrades. That is not a defect to engineer around; it is ADR-0154 §2's *"no
  configuration that grants a standing authorisation for a recipient"* meeting a
  mechanism for the first time, and the surface that lifts it is named in §19.
- **ADR-0193 acquires its first customer, and ADR-0181's floor acquires its second
  live subject.** A standing recipient grant has had no reachable use since it was
  ratified; a search is the first call for which route (b) is the *only* route. And the
  origin bar that makes a grant not cover a tainted call becomes the thing that closes
  a steered loop rather than a clause with nothing to decide.
- **Milestone 29's exit sentence becomes a mechanical consequence rather than a
  property to arrange.** A conversation that has read a result stamps its episodes, its
  later bindings carry the fact, and no grant covers them: every outward call in that
  conversation asks. §18's second test asserts it through the production policy.
- **The egress seam gains a second route and a second protocol**, and both are stated
  narrowly. The route is a `WEB_SEARCH` servicing's request and nothing else; the
  protocol is an origin comparison with three equivalences and six refusals. Every other
  send goes through `ToolInvoker.invoke` exactly as before.
- **A search costs one model completion whether or not it is serviced**, because the
  query must exist before the call can be ruled on. On a deployment with no grant that
  completion is spent for a refusal, and §13's disposition is what makes it visible.
- **An auditor can establish that a search happened and not what was asked.** That is
  the same property every egress call has and it follows from two decisions taken to
  keep Tier 1 out of durable records — and it is exactly the gap the content-bearing
  approval surface exists to close on the authorisation side.
- **`PROTOCOL_VERSION` and `PlanExport.schema_version` move again**, three weeks after
  ADR-0230 moved both. Each additive `ReadKind` member costs a protocol move while
  `ReadAsk` forbids extras, and that is ADR-0228 §6's conjunction working rather than
  churn.
- **Revisit trigger.** §13's audit showing a non-trivial rate of `WEB_SEARCH` asks on a
  deployment that cannot service them — the signal that the grant surface is the thing
  holding the rung up rather than an abstraction — or the owner ruling `risk_level`
  differently, which §19 names as the reconsideration that would move most.

## Alternatives considered

- **Let the planner compose the query.** Forbidden by ADR-0155 §3's third clause and
  ruled out by the owner on 2026-09-04; the first attempt at this lane stopped on it
  (#1996). Rejected, and §4 records why the utterance-only route is not a workaround
  but the shape ADR-0155's own Consequences blesses.
- **Give the `WEB_SEARCH` ask a query field the prompt tells the planner to keep
  free of anything recalled.** Rejected: it puts a privacy prohibition on a model's
  compliance and on a reviewer noticing, where a missing field puts it on the type.
- **Register the search as an ordinary tool and let the planner name a step.**
  Rejected by #1908's own sentence, by ADR-0170 §5a (*"a tool's result is a JSON payload
  with no per-span provenance"*) and by ADR-0208 §1. It is also the shape that would
  have needed no amendment at all, which is worth naming: the amendments in §6 are the
  price of keeping records-not-payloads, and they are cheaper than the thing they buy.
- **Service the search last, after the citation hop and the sighted query.** Rejected in
  §11: it would make the kind's availability a function of how full the budget happened
  to be, and would put the weakest-cap read ahead of the strongest namer.
- **Park the turn on a `CONFIRM`, or record a pending confirmation for later.**
  Rejected in §9: both put a durable confirmation, a resume path, a wire operation and a
  surface behind a mechanism ADR-0226 §5 designed to be invisible, and the first lets a
  marginal improvement in reach take a reply down.
- **Declare `discloses=()` on the ground that ADR-0148 §8's second clause binds a
  *registered* tool.** Rejected in §9 as the loophole it is: the query is Tier 1 and does
  leave the device, and taking it would auto-grant the one call this system makes to a
  party the user never named.
- **Take the response's received instant as `reported_at`, on ADR-0230 §5's
  reasoning.** Rejected in §10: that supersession scopes itself away from a source that
  may replay an earlier answer, and a search index is exactly that. ADR-0092 §3's own
  answer — take what the source says, and mint nothing where it says nothing — is
  available and is used.
- **Put the result's address in a new `core` field on `Provenance`.** Rejected in §10:
  `core` surface on a model every record carries, for a value one kind produces, where
  the address is part of what the provider reported and belongs with the provider's
  other words.
- **Designate a second seam for HTTPS.** Rejected: ADR-0154 §1 designates one module and
  §7 forbids reading a second designation out of it; ADR-0191 §3 puts the one production
  transport there and §2 already priced building HTTP over the channel. A second
  designation would in any case be a document rather than a designation, because
  designation is attested against code that exists (ADR-0154 §3).
- **Ship nothing until the grant surface lands.** Rejected: the surface is another
  track's, the contracts this ADR decides are what its implementing lanes need, and a
  mechanism that is inert for a stated reason with a named firing condition is a state
  this corpus already ships (ADR-0193's empty store, ADR-0230's unconfigured root).

### 21. Marking, review and ratification

This ADR is in **ADR-0089's marked regime**: it carries well-formed clauses, so the
marked clauses are the whole of what it obligates and the prose beside them supplies
nothing. ADR-0089 §5 makes marking forward-only, so nothing this ADR cites is
retro-marked. What binds is **eighty-nine clauses**: §1's four, §2's two, §3's five, §4's two,
§5's six, §6's five, §8's seven, §9's five, §10's eight, §11's nine, §12's four, §13's
six, §14's five, §15's three, §16's eight, §17's nine and §18's one. §7's table, §19's
list, §20's classification and every argument in this document are deliberately
unmarked: they are attestation, deferral and argument, which ADR-0089 §1 classifies as
non-normative however load-bearing.

**Required reviews: adversarial *and* architecture.** This is a contract-surface change
in `CONTRIBUTING.md`'s sense: it decides two Protocols, a `ReadKind` member, a
`ReadAsk` validator arm and a `DestinationProtocol` member, and it moves clauses of the
two ADRs that stand behind the egress seam's designation. It is drafted, reviewed and
revised as `Proposed`, and the route is `CONTRIBUTING.md` → "Finishing an ADR PR".
