# 260. A forecast read is its own seam, at a provider the deployment configured, and what it mints carries the extent that makes it evidence

- Status: Proposed
- Date: 2026-09-15
- **Partially supersedes**
  [ADR-0247](0247-the-configured-web-search-provider-is-the-destination-the-owner-chose-and-the-recipient-they-granted-and-the-call-budget-is-removed.md)
  — **§1's first clause and §8(a), in the limb that enumerates which request kinds a
  configured provider's authority covers, and in no other limb.** Both are written over
  a request *"whose kind is `WEB_SEARCH`"*, and §1 says so twice — its heading reads
  *"for `WEB_SEARCH` and for nothing else"*. §6 below widens that population to a closed
  **two**-member set, each kind at **its own separately configured** account and origin.
  Every conjunct is kept: the comparison stays `DurableIdentifier` equality and
  `CanonicalDestination` equality over recorded values, neither side inferred, folded,
  matched by domain or re-canonicalised. **Everything else of ADR-0247 binds entire** —
  §1's remaining clauses, §2's route (c) and its trail check, §3's retirements as §6
  below restates their reach, §4's `closed_loop` (untouched, and still search's alone),
  §5's removal of the call budget, §7, §8's (a′) to (d′), §9's unchanged list and §10's
  surface. **§9's second clause is read and is not this**: its subject is *"milestone
  32's bounded fetch … at destinations nobody configured"*, and a provider the
  deployment configured is the one thing that is not that.
- **Partially supersedes**
  [ADR-0238](0238-a-destination-the-user-chose-may-be-told-what-the-turn-knows-and-the-searching-that-follows-runs-under-a-per-conversation-budget.md)
  — **§1's third clause, in the forecast-read limb alone.** That clause reads *"The fact
  is **set by a recorded act of the user and by nothing else**. No configuration sets
  it"*; ADR-0247 §1 already superseded it in the `WEB_SEARCH` limb, and §6 below carries
  that same supersession to a forecast read at the configured forecast provider. **The
  clause binds entire on every other destination and every other kind**, and every other
  clause of ADR-0238 is untouched — the two-member vocabulary, the fail-closed absence,
  the record's five fields, the store surface and `trust_of`'s comparison-not-inference
  rule included. No trust record is minted, written, implied or synthesised here.
- **Amends** [ADR-0226](0226-the-planner-names-one-more-read-beside-its-plan-and-the-loop-services-it-into-the-supply.md)
  **§2's membership sentence and §6's cross-kind precedence sentence**, in one respect
  each: the enumeration gains a **sixth** member (§2 below), and a read that ADR did not
  admit is serviced between the web search and the citation hop (§7 below). This is the
  licence §1 of that ADR grants in terms — *"A later kind
  is an **additive entry** to this enumeration, not a second seam"* — exercised the way
  ADR-0230 §1, ADR-0231 §1 and ADR-0240 §1 each exercised it. §2's statement of what each
  named kind *is*, its at-most-one-ask-of-each-kind rule and its closure against un-ADR'd
  additions all bind entire.
- **Amends** [ADR-0251](0251-an-attempt-investigates-in-bounded-rounds-over-typed-read-outcomes-and-keeps-a-reserve-to-answer-with.md)
  **§2's per-member source lists**, in that one respect: each list names the members of
  `SearchDisposition`, `SearchRefusal`, `FetchRefusal` and `StructuredOutcome` that map
  onto it, and §7 below adds this decision's two vocabularies to them. §2's seven
  members, its closure, its classifier, its four facts, its total precedence and its
  no-message clause all bind entire and none moves.
- **Amends** [ADR-0264](0264-a-turn-that-reached-outside-this-system-says-so-and-a-reply-cannot-deny-a-contact-the-trail-recorded.md)
  **§3's first clause and §5's closure at one member**, in one respect each.
  `OutboundDestination` gains a second member, and a **second seam establishes a contact**
  — so §3's *"This decision establishes a contact from a `WEB_SEARCH` call and from
  nothing else"* stops being readable as a closure over the corpus, and §5's closure at one
  member stops holding. **Both are that ADR working rather than a departure from it**: §5
  requires the member in terms — *"A later outbound seam adds its own member with its own
  ADR. It does not render as `SEARCH_PROVIDER` and does not render as nothing"* — and a
  member that renders is a contact that was established, so §3's sentence and §5's
  invitation cannot both be read widely. **§3's prohibition binds entire and is what §3 is
  for**: no component derives `REACHED`, and none adds a destination class, from an
  `EgressBinding`, from `Disposition.EXECUTED`, from `StepStatus.SUCCEEDED` or from any
  combination of them — §10 below derives it from a forecast **call**'s own recorded
  disposition and from nothing else. §5's class-never-a-destination rule, §1's
  three-valued statement, §2's establishment partition and §4's carrier all bind entire.
- **Decides new `core` surface — a BREAKING contract change (golden rule 5).** One
  Protocol, one `ReadKind` member, three models, two enumerations, one member on a third
  and one field on a fourth. Nothing implements against any of it until this ADR is
  merged, and the Protocol ships as a triad — contract, shared conformance suite,
  canonical fake — in its own later lane (ADR-0015 §5, `CONTRIBUTING.md` → "Adding a
  Protocol"). §12 cuts the lanes.
- **Required review set: adversarial *and* architecture**, prose-only though this PR is.
  It decides a `core/protocols.py` addition and a package boundary, which is the ground
  ADR-0095's header takes the same set for (ADR-0015 §1). It is **reviewed while
  `Proposed` and ratified only after**.
- **This ADR authorises no byte and configures no deployment.** It decides a contract.
  Nothing transmits on its merge: no provider is configured, no integration is
  registered, and a deployment that configures none is unchanged in every respect.
- Refs [#2255](https://github.com/leonapivato/ai-assistant/issues/2255).

## Context

### Where this comes from

The project owner's ruling of 2026-09-12 on #2255, decision 8:

> A useful real-information reader lands alongside M32. Autonomous web research stays
> separate, scheduled after the investigation foundation is stable; it need not wait for
> M34.

and the design report's Q3, over *"A weather `Reader` (ADR-0095) and a booking
integration declared at the `tools/` egress seam (ADR-0154, ADR-0016/0018)"*: *"It
demonstrates investigation, dependent execution, uncertain outcomes and verification
**without any new destination-trust decision**, because a configured reader and a
registered integration are already-governed shapes."*

**This ADR is the forecast half and nothing else.** The booking integration is a `tools/`
integration at ADR-0154's seam and is its own decision; §14 names it among what is not
decided here.

The owner's ruling of 2026-09-14 fixes the reference provider: **Open-Meteo**, free and
keyless, configured the way the search provider is. This ADR names no vendor in any
normative clause — §6's authority is stated over *the configured provider* — and §12
records that the implementing lane delivers the real one, with what would make it deliver
a mock behind the same contract instead.

### The tree, read rather than assumed, at `origin/main` `8dbfddf0`

- **`ReadKind` has five members** — `SIGHTED_QUERY`, `CITATION_HOP`, `LOCAL_FILE`,
  `WEB_SEARCH`, `STRUCTURED_READ` — and its docstring records that the third to fifth are
  additive entries under ADR-0226 §1's own licence. `ReadAsk` has one field per kind's
  argument and a validator with five arms, `WEB_SEARCH`'s being the arm that refuses all
  four arguments.
- **The egress boundaries are three**, ADR-0124 §1 being the live rule that replaced
  ADR-0017 §1's enumeration: `models/`, the designated `tools/` seam and the hub's remote
  transport in both halves. *"Every other egress is a bug."*
- **`tools/web_search.py` is the worked shape** for a configured HTTPS provider at that
  seam — a declaration, a provider adapter and a searcher driving the `HttpsExchange` the
  seam holds, reaching no transport of its own and bound by the transport-confinement
  import contract.
- **`readers/calendar.py` is the only site in the tree that constructs a
  `ReportedExtent`**, which ADR-0252 §3 records as a dated observation: the evidence window
  axis applies *"on nothing else until decision 8's reader lands"*.
- **`PROTOCOL_VERSION` is 43**, and lanes in flight also move it; §11 states the
  obligation without fixing the figure.

### What the corpus already decides, and is used here as given

- **ADR-0226 §1** closes the read-request enumeration and fixes how it grows: an ADR
  admitting a kind *"adds a member and states that kind's namer, its servicing, its share
  of §6's budget and its audit fields; it does not introduce a second request object, a
  second servicing site, a second budget or a second audit."* §2 and §7 below are that
  statement.
- **ADR-0230 §5 and ADR-0231 §10** are the two minting precedents, and §5 below follows
  the second where they differ, a forecast provider being a remote source answering a live
  interrogation. **ADR-0264 §5** requires a second outbound seam to add its own
  `OutboundDestination` member, and §10 does. **ADR-0251 §4** governs whether a further
  round fires, over facts that are not about the kind; nothing here changes it.
- **ADR-0117 §2's extent, and §8's general rule.** *"Where a source's entries have a
  position in that source's world, that position is producer testimony and is carried by
  the extent (§2); it is never carried by the record's envelope validity window."* §8 names
  the property that made the calendar the hard case — it is **forward-looking** — which is
  a forecast's defining property too.
- **ADR-0252 §15** names exactly what an evidence row needs from this decision and
  declines to design the rest: the reader's declared identity, an
  `Attestation.reported_at` for `as_of`, and *"for `supported`, a `ReportedExtent`
  (ADR-0117 §2) … the only authority this decision will accept for what a reader
  covered"*, while *"how a reader's read is asked for, serviced, budgeted or audited is
  that lane's"*.

### Three premises in the framing that do not survive contact with the tree

These are recorded because each one, taken at face value, would have produced a different
and wrong decision, and because a reader comparing this ADR against #2255's wording is
owed the reason for the difference.

**1. It cannot be a `Reader`, and the corpus has already ruled on exactly this shape.**
ADR-0093 §10 gives `read()` no arguments *by decision*: *"It takes no arguments because §1
gives the sensor its own source and §5 makes the bound the sensor's own configuration: a
caller able to widen the read is a caller able to defeat the bound"* (read under ADR-0095
§1's substitution). ADR-0230 §4 met the same question for the fetch seam and answered it:
*"Reusing `Reader` was never available … an argument is exactly what this contract
needs"*, so *"it is a `core/protocols.py` addition and this is its ADR (golden rule 5)"*.
A turn-time forecast read is a read the turn asks for; a `Reader` is a whole-source read
on the reader's own cadence. §1 decides a seam of its own, and "Alternatives considered"
argues the `Reader` shape out at length so the ruling is reversible on the page.

**2. `SourceReadRecord` is not what a forecast read returns.** ADR-0185 §1 makes its unit
*"one **attempt** by a driver to read one source"*, and §2 an audit row that *"carries
**no source content**, no entry, no path and no configured location"* — it has no
`Provenance`, no `Validity` and no `Attestation` to carry, and `produced` is a count. What
a serviced read returns into the supply is `MemoryRecord`s (ADR-0226 §1), and §5 fixes
their provenance. ADR-0230 §11 settles the neighbouring grant question the same way for
the fetch seam, and §15 inherits that reasoning rather than re-arguing it.

**3. The evidence window is a `ReportedExtent` and never a `Validity`**, and ADR-0252 §3
marks the prohibition in terms: *"Neither `valid_from` nor `valid_until` contributes to
any region's `window`, on any kind, under any fallback, and **no lane reinstates one**."*
Its worked failure is this reader: *"A weather record written on Saturday with
`valid_from` set to that instant and no `ReportedExtent` declares an interval running from
Saturday with no end … Read as coverage, it would have supported **every later date**,
Sunday included, off a persistence timestamp no source ever said anything with."* §5 mints
the extent that clause asks for, and §8 composes from it.

### What this ADR is not allowed to settle

It decides one read kind and one seam. It decides no booking integration, no fetch, no
autonomous web research, no second reader kind, no geocoding, no cache, no scheduled or
proactive forecast, and no relaxation reachable by anything that is not a forecast read at
the configured forecast provider. §14 names each of those with what fires it.

## Decision

### 1. The shape: a seam of its own, in `Fetcher`'s and `WebSearcher`'s form

> **Normative.** The forecast read is a **new seam**: one Protocol in
> `core/protocols.py` (§4), whose production implementation lives in
> `ai_assistant.tools` at the designated egress seam (§6), wired by
> `app/composition.py` and held by one servicing site in `orchestration` (§7). It is
> **not** a `Reader`, is **not** a `ContextProvider`, and is **not** a registered tool.

> **Normative.** **`Reader` is untouched.** ADR-0093 §10's no-arguments rule, ADR-0095's
> placement ruling and every clause governing `readers/` bind exactly as they do today.
> No lane widens `Reader.read`, adds an argument to it, adds a member to `Reader`, or
> reads this ADR as licence to do any of those. `ai_assistant.readers` gains **nothing**
> from this decision, and the `readers depend on core and nothing else` and `nothing
> imports the readers` import contracts are unchanged.

> **Normative.** **No egress boundary is added, and `readers/` acquires none.** ADR-0124
> §1's three boundaries are the whole list, and the forecast provider is reached from
> `ai_assistant.tools.egress` and from nowhere else — through the injected
> `OutboundTransport` (ADR-0191 §1), under ADR-0154 §1's designation, inside the
> `network transports are confined to the tools egress seam` contract, whose enumerated
> `source_modules` the implementing lane extends with the new module in the same change.
> **A lane that finds itself opening a connection from `ai_assistant.readers` has built
> the wrong thing and stops.**

> **Normative.** **It is not a registered tool, and the route is closed at the type
> rather than by a rule.** The integration is registered at the egress seam against the
> configured connection and in **no** `ToolRegistry`, exactly as ADR-0231 §5 registers
> the search: absent from `capabilities()` and `all_tools()`, unreachable by any plan
> step, un-invocable through `ToolInvoker`. ADR-0208 §1 — *"A component on the turn path
> that wants records the supply does not hold does not obtain them by invoking a tool"* —
> is satisfied by not being a tool, and ADR-0170 §5a's *"a tool's result is a JSON
> payload with no per-span provenance"* is not approached.

**Named for its product role, as every Protocol in that module is** (`Planner`,
`Observer`, `Reader`, `Fetcher`, `WebSearcher`): the role is *asking a configured outside
source what it currently says about the days ahead*, so the seam is a **`Forecaster`** and
§4 fixes its three members.

**The difference from `Reader` is the one ADR-0230 §4 already named, and it is not about
the weather.** A `Reader` is bound by its own configuration and takes no address; a
turn-time read must be a contract that can be *asked*. This seam takes the smallest
possible ask — §3 makes it none at all — which honours ADR-0093 §10's reason rather than
working around it: there is nothing for a caller to widen, and the bound stays the
source's own configuration.

**And the difference from a `ContextProvider` is the cadence again.** ADR-0252 §3 rules
that no facet produces an evidence row, and ADR-0096 §3 that *"No facet is served from a
cached, carried-over or previously assembled reading"*.

### 2. The kind: `FORECAST_READ`, an additive sixth member and not a second seam

> **Normative.** `ReadKind` gains one member, **`FORECAST_READ`**, valued
> `forecast_read`. It is an **additive entry** under ADR-0226 §1 — *"A later kind is an
> additive entry to this enumeration, not a second seam. An ADR admitting one adds a
> member and states that kind's namer, its servicing, its share of §6's budget and its
> audit fields; it does not introduce a second request object, a second servicing site, a
> second budget or a second audit."* It adds none of those four, and every clause
> ADR-0226, ADR-0228, ADR-0230, ADR-0231, ADR-0240 and ADR-0251 state over a read request
> binds on it except where a section below names the exception and shows its working.

> **Normative.** ADR-0226 §2's at-most-one-ask-of-each-kind rule and `ReadRequest`'s
> validator bind unchanged: one emission carries at most one `FORECAST_READ` ask, and a
> request naming two is not an emission this corpus admits. A turn that revises may emit
> a second on its second plan, which is ADR-0228 §3 applied and not widened.

> **Normative.** **One ask is one read.** No implementation issues two provider requests
> for one ask, follows a link out of a response, requests a further page, re-issues with
> a different window, retries a refused or failed request inside the turn, or repairs,
> widens or narrows the ask it was given. There is no pagination, no depth and no
> traversal of any kind, and no later lane adds one without the ADR that decides it.

**A sixth member rather than a widening of `WEB_SEARCH`, and ADR-0226 decides it twice
over.** §1 of that ADR rules that *"no lane widens an admitted kind's meaning to carry a
read the ADR that admitted it did not describe"*, and ADR-0231 §1 says what a `WEB_SEARCH`
**is**: one search of the web whose query is composed from the turn's own utterance. A
forecast read sends no query and composes nothing, and its answer is a table rather than a
result list — so folding the two would widen an admitted kind's meaning against the first
sentence and change its servicing against the second.

**And the two do not reach the same records.** A search mints transcriptions carrying no
structural axis at all — ADR-0252 §3 records that *"every `WEB_SEARCH` and every
`LOCAL_FILE` row carries `supported` empty"* — where a forecast mints records that each
declare an extent, which is the whole reason this kind is worth adding (§9).

### 3. The ask carries nothing at all, and that is this kind's whole safety mechanism

> **Normative.** A `FORECAST_READ` ask carries **no query, no labels, no entry and no
> structure**. `ReadAsk` gains **no field** for this kind, and no later lane adds one
> without the ADR that decides it. A `FORECAST_READ` ask **states its kind and nothing
> else**, and its validator arm is `WEB_SEARCH`'s arm applied to a sixth member: each of
> the four existing arguments is refused **separately**, because each would be a
> different mistake with a different fix.

> **Normative.** **The place is the deployment's own configured place, and the
> configuration is the naming act** — §11's `Settings` pair, read by the composition root
> and held by the forecaster as its own configuration. **No place crosses the planning
> seam in either direction**: no coordinate, no place name and no identifier of a place
> is rendered to a model, and none is accepted from one. A planner cannot name where a
> forecast is read for, so the failure mode ADR-0231 §1 is built against — a
> planner-writable field carrying covered content to an egress seam — is **unreachable
> rather than forbidden**.

> **Normative.** **The horizon is the forecaster's own bound, not a caller's.** How many
> days ahead one read covers is fixed by §11's `Settings` figure and by the provider's
> own answer, and no caller widens, narrows or offsets it. This is ADR-0093 §10's rule
> honoured rather than worked around — *"a caller able to widen the read is a caller able
> to defeat the bound"* — at a seam that does take a call.

> **Normative.** ADR-0226 §3's namer rule binds this kind as written, and the namer here
> is **the operator's configuration** for the place and **the source's own answer** for
> the days. The model points outward and names **nothing at all**; no record identifier,
> no label and no address crosses the seam in either direction.

**An empty ask is the strongest form available and it is chosen for that reason.** The
alternatives — a planner-composed window and a planner-named place — are refused in
"Alternatives considered" on one ground each. What the corpus says about the empty arm at
the search seam is true here word for word: *"a field the planner cannot write is a field
that cannot carry covered content"*.

**The honest cost is that one deployment reads one place**, and it is stated rather than
glossed. The campsite walkthrough's forecast half is answered for the owner's own
configured place; a forecast *at the campsite* needs a place this system holds a recorded
coordinate for, which no type on the tree carries today. §14 defers the place listing with
what fires it, and that is a narrowing rather than a gap: a reader answering "what is the
weather this weekend" for the place the owner lives is the useful reader decision 8 asks
for, and every later place arrives as a widening of §3 rather than a second seam.

### 4. The contract: `Forecaster`, and the bound the caller cannot widen

> **Normative.** `core/protocols.py` gains **one** Protocol, **`Forecaster`**,
> `@runtime_checkable` as the seams around it are, owing three members:
>
> - a **`name` property**, `str` — the stable Tier 2 identity of the **source instance**,
>   in `Reader.name`'s, `Fetcher.name`'s and `WebSearcher.name`'s own form and under
>   their obligations: *"the owner's forecast"* and never a vendor, never an origin, never
>   a URL, never a credential and never a place. It is what §5 puts in an attestation's
>   `reported_by` and what ADR-0252 §1's `source` field carries.
> - an **`async request` method** taking **no arguments** and returning
>   `ActionRequest | None` — the proposal, reaching **no** authorisation conclusion. It
>   returns `None` where the deployment has configured no forecast provider, which is a
>   configuration fact and never a failure.
> - an **`async read` method** taking a `ToolCall` positionally and a `timeout`
>   keyword, and returning one `ForecastOutcome`. It takes a `ToolCall` and never an
>   `ActionRequest`, so **an unauthorised forecast read is unconstructable at the type
>   level** — `ToolInvoker.invoke`'s guarantee obtained without `ToolInvoker`, which is
>   `WebSearcher`'s own property (ADR-0231 §17).

> **Normative.** **No member takes a store, a supply, a policy, a trail or a record.**
> Not a `MemoryRecord`, not a `MemoryStore`, not an `ActionPolicy`, not an `AuditTrail`,
> not a `RecipientGrants` — and **no later lane adds one that does**. Between `request`
> and `read` stand the binder, the policy and the trail, none of which this contract
> names.

> **Normative.** **A `Forecaster` holds the credential where there is one, and this
> contract never carries one.** Any `Secrets` read is at `SecretScope.INTEGRATION`,
> *inside* `read`, after the checks §6 names have passed — ADR-0148 §7's positional gate
> with one word changed. **A keyless provider reads no credential at all**, and that is a
> property of the registration rather than an exemption: no credential value is in a
> binding (ADR-0148 §6), so nothing about the ruling, the trail or the resumability
> changes either way.

> **Normative.** `core/types.py` gains **`ForecastOutcome`**, a frozen model refusing
> mutation and unknown fields, carrying exactly `records: tuple[MemoryRecord, ...]`,
> `reported_at: UtcInstant | None` and `refusal: ForecastRefusal | None`, with **exactly
> one of** a non-empty `records` and a non-`None` `refusal`, enforced by the model —
> neither both nor neither — and `reported_at` present exactly where `records` is.

> **Normative.** **Every §5 invariant that is *structural* — decidable over this value's
> own fields — is enforced by `ForecastOutcome` itself and not by its producers**, in
> `SearchOutcome`'s own shape and for its stated reason: conditions on the model are
> *"decidable in any process and true of every"* implementation this system ever wires,
> **the canonical fake included**. Every record is `SEMANTIC`, carries
> `MemorySource.EXTERNAL`, carries empty `evidence`, carries a fully-open `validity`,
> carries an `Attestation` whose `reported_by` is one value shared by every record of the
> outcome, carries an `extent` that is a constructible half-open interval, and carries a
> `reported_at` **equal to the outcome's own** — a record disagreeing with its outcome
> about when the source spoke is two answers in one value. **No condition reaches for a
> bound, a clock, a store or a configuration**: `forecast_max_days`,
> `forecast_max_day_chars` and `forecast_max_response_bytes` are `Settings` the
> *configured* forecaster enforces, so this model carries none of them and validates
> identically in every deployment.

> **Normative.** `core/types.py` gains **`ForecastRefusal`**, a **closed** `StrEnum`
> valued by lower-cased member name, of why a read produced no record, with exactly these
> members: `TRANSPORT_FAILED`, `DEADLINE_EXPIRED`, `RESPONSE_TOO_LARGE`,
> `PROVIDER_REFUSED`, `UNATTESTED` and `NO_RESULT`. The vocabulary is **added to and
> never renamed**, and no implementation, setting or later lane adds a seventh without the
> ADR that decides it.

> **Normative.** **Neither acting member raises for a source reason.** Every one of those
> six is **returned** and none is raised, for `Fetcher`'s and `WebSearcher`'s reason: a
> closed refusal enumeration makes the non-yield a value the audit can count and the turn
> can ignore, where an exception would make ADR-0226 §5's degradation posture the
> servicer's problem to catch correctly at every call site. **This ADR adds no error class
> to `core/errors.py`.**

> **Normative.** **The seam owns its deadline and the caller does not wrap it**
> (ADR-0241 §1, §4): `read` takes the remaining time as its `timeout` keyword, an expiry
> is `DEADLINE_EXPIRED` and is an outcome of its own rather than a failure, and a caller
> wrapping this member in `asyncio.timeout` would cancel the forecaster mid-await and
> could not classify its own expiry.

> **Normative.** **It carries no lifecycle member, deliberately**, exactly as `Fetcher`
> and `WebSearcher` do: a concrete forecaster holding an opened resource exposes a
> `close`, and `app/composition.py` registers that `close` among the resources it has
> opened (ADR-0042 §2). The contract keeps saying what a forecast read *is* and not who
> shuts one down.

> **Normative.** **Cancelling either acting member re-raises.** This module's cancellation
> clause (ADR-0060) binds, with the one consequence spelled out because it is where a
> conforming-looking implementation could satisfy every other clause and still get it
> wrong: a call cancelled from outside while suspended re-raises `CancelledError` and is
> converted into neither an outcome nor a refusal.

### 5. What a forecast read mints, and the extent that makes it evidence

> **Normative.** A `Forecaster` mints the records; **nothing outside it stamps a
> `Provenance` for a forecast**. A successful read mints **one `MemoryRecord` per day the
> provider's answer covers**, in the order the provider returned them, of kind `SEMANTIC`,
> at most `forecast_max_days` of them (§11). **No model is on that path**: nothing
> summarises, abridges, rewrites, re-ranks, annotates, deduplicates, interprets or
> classifies a value between the provider's response and the record.

> **Normative.** A record's `content` is a **transcription** of the fields the provider's
> documented format names for that day, in a fixed order, each rendered **as the
> provider's own response spelled it** — the octets of the value the response carried, and
> never a re-rendering of a parsed number. The exact field order and line form are fixed
> by the implementing lane and pinned by a test, so that **two conforming implementations
> over one response mint byte-identical records**. This is ADR-0231 §10's
> transcription-not-rendering rule and ADR-0230 §5's decoding-not-rendering rule at a
> third producer, and neither is relaxed: **no word of this system's is added.**

> **Normative.** **A day the response does not describe completely is dropped whole**, and
> the remaining days are minted: a day for which the provider omitted a documented field,
> supplied it as `null`, or supplied a value of a type its documented format does not
> admit, and a day whose transcription exceeds `forecast_max_day_chars` measured as
> ADR-0230 §6 measures a fetched document. **Where every day is dropped the read yields
> nothing**, the refusal is `NO_RESULT`, and §7's audit counts the drops.

> **Normative.** The record's `Provenance` carries `source=MemorySource.EXTERNAL`, which
> `band_of` places in the `ATTESTED` band, so `rests_on_recorded_external_content` is
> `True` for it. `confidence` is **0.9**, the figure the corpus's other attested producers
> carry and for their reason (ADR-0038 §2a). `evidence` is empty, `derived_from_external`
> is `False` and asserts nothing in this band (ADR-0106 §1), `topics` is empty,
> `about_person` is `None`, `placement` is the default that narrows nothing (ADR-0217 §6),
> and **`validity` is fully open**.

> **Normative.** **`validity` is fully open and no lane sets it to the day the record is
> about.** ADR-0045 §2 makes the envelope window *"a lifecycle property of the record's
> life in the store, set operationally by the applier"*, and ADR-0252 §3 forbids reading
> it as coverage *"on any kind, under any fallback"*. A producer setting it to the
> forecast's own day would be writing the source's testimony into the operational axis —
> the authorship mixing ADR-0117 §2 refuses — and would hand the prohibited fallback
> exactly the value it was written to refuse.

> **Normative.** The `Attestation` carries `reported_by` equal to the forecaster's `name`
> — the **source instance**, *"the owner's forecast"*, never a vendor, never an origin,
> never a URL, never a credential and never a place (ADR-0092 §3).

> **Normative.** **`reported_at` is the instant the provider's own response declares, on
> the provider's own clock, and there is no substitute.** ADR-0092 §3 binds as written and
> ADR-0230 §5's local-substitute scope expressly does not reach here — that section closes
> the door on this case in terms, *"a kind whose fetch retrieves a remote source's earlier
> answer, or replays one from a cache of its own, is outside this scope entirely"*, and a
> forecast is a claim a model run made before we asked. It is **not** the instant we sent
> the request, not the instant we received the response, and not a clock this system read.
> A response declaring **no** instant, or carrying in that position a value that cannot be
> read as one, mints **no record**: the refusal is `UNATTESTED`, and §7's audit records the
> class. **No implementation reads an unparseable field as licence to fall back to a clock
> it read.**

> **Normative.** **The `Attestation` carries a `ReportedExtent` equal to the day that
> record is about, and this is the field the whole decision is bought for.** Its ends are
> the half-open bounds of that day, computed **from the day the provider named and the
> UTC offset the provider's own response declared for it**, and from nothing else — never
> from a clock of ours, never from a timezone database of ours, never from the reader's
> configuration, and never from the place. **A day the provider named without declaring
> the offset it is in declares no extent**, and that day is dropped under the clause above
> rather than minted with an extent this system computed.

> **Normative.** **The extent is never trimmed, widened or substituted.** ADR-0117 §2's
> clauses bind entire: an extent *"states where the reported entry lies"*, is *"never
> trimmed to fit a coverage, never widened past what the source says, and never derived
> from the read's own bound or from the reader's configuration"*, and no producer
> constructs a degenerate or inverted one. Where the provider's own values would not make
> a constructible extent, **none is declared and the day is dropped** — the fail-closed
> direction ADR-0252 §3 names, because an unbounded extent would cover every window where
> a declined one covers none.

> **Normative.** **What is attested is the provider's claim about what its forecast says
> for that day, and the record makes no claim that the weather will be so.** No lane
> states or implies otherwise, derives a certainty from a value, reads a `reported_at` as a
> fact about the weather, or treats a forecast record as an observation. The record's `id`
> is **minted by the forecaster and opaque to the source** (ADR-0092 §6): never rendered
> to a model, never accepted from one, and — since §11 stores nothing — never installed.

**This is the producer ADR-0252 §3 says the corpus is missing, and names.** That clause
records that *"`readers/calendar.py` is the only site in the tree that constructs a
`ReportedExtent`"* and that the window axis therefore applies *"on nothing else until
decision 8's reader lands"*. ADR-0117 §8 says why the calendar was the hard case — *"its
entries lie ahead of the read, so a position-stating envelope window would not yet be
open"* — and a forecast is that property in its purest form.

### 6. The egress: a configured provider, and the authority that reaches it

> **Normative.** The forecast integration is registered at the **designated** egress seam
> against the configured connection reference and one origin, in ADR-0231 §5's own shape:
> built at one site in `ai_assistant.tools`, pinned by the transport to that origin **as
> text, before parsing** (ADR-0154's condition 5), registered in **no** `ToolRegistry`,
> and reachable from nowhere else. ADR-0154 §2's clauses bind unchanged — designation
> approves no destination, no recipient, no account and no payload, and every send remains
> subject to ADR-0148's per-call machinery whole.

> **Normative.** **A forecast request is *at the configured forecast provider* when all
> three hold**: the request carries §11's `forecast_reach` fact; the binding's
> `account.reference` equals this deployment's configured `Settings.forecast_connection`;
> and the binding's canonical destination set is the one `Settings.forecast_origin`
> canonicalises to. Both comparisons are over **recorded values** — `DurableIdentifier`
> equality and `CanonicalDestination` equality, every field, never across protocols — and
> neither is inferred, folded, matched by domain or re-canonicalised. **A request failing
> any of the three is not at the configured forecast provider**, and every clause this
> section relaxes binds on it exactly as it binds today.

> **Normative.** **ADR-0247 §2's route (c) admits this request, and its population is
> widened to a closed two-member set.** ADR-0148 §3's first clause gains no fourth route:
> route (c) becomes *"the request is a `WEB_SEARCH` at the configured search provider, **or
> a forecast read at the configured forecast provider**"*, and nothing else is added to it.
> **Each kind is compared against its own configured pair**; a forecast request bound to
> the search provider's account or origin, or the reverse, takes no route at all. **This
> supersedes ADR-0247 §1's first clause and §8(a) in that limb and in no other**, and
> ADR-0247 §8's (a′), (b), (b′), (b″), (c) and (d) bind on this kind word for word, with
> `forecast_connection` and `forecast_origin` read for `web_search_connection` and
> `web_search_origin`.

> **Normative.** **On such a request the destination is the one the owner chose and the
> configuration is the choosing act**, which is ADR-0247 §1's third clause carried to this
> kind — and with it that clause's supersession of ADR-0238 §1's third clause, in the
> forecast-read limb alone. **`DestinationTrust`, `DestinationTrustRecord` and
> `DestinationTrustStore` are untouched**, `trust_of` answers exactly as it does today for
> every caller, and **no record is minted, written, implied or synthesised by a
> configuration.**

> **Normative.** **The configured provider is also the granted recipient, and no
> `RecipientGrant` is established, read, extended or implied** — ADR-0247 §1's seventh
> clause at this kind. ADR-0193 §3's five comparisons bind entire wherever a grant *is* the
> route, and **ADR-0193 §5 is relied upon and not superseded**: a grant still reaches the
> recipient and never the payload.

> **Normative.** **Both limbs of `_only_the_disclosure_floor` are restated over the
> generalised derived fact**, and become *"the binding does not carry
> `planned_with_external_content`, **or** the request is at its kind's configured
> provider"* and *"the binding carries no covered content, **or** the request is at its
> kind's configured provider"*. **That is a change of text and not only of reach**, and it
> keeps the retirement exactly as wide as the predicate above: a binding whose account or
> origin is not its kind's configured pair satisfies neither limb, so both floors bind on
> it in full. ADR-0247 §3's remaining clauses and ADR-0238 §7's own governing sentence are
> unmoved.

> **Normative.** **Both floors are retired together here as for a search, and the reason is
> ADR-0247 §3's rather than a new one.** A deployment retiring the lineage floor alone
> would still be stopped by the coverage limb on every turn that had read anything, and one
> retiring the coverage exception alone by the lineage floor. **Both limbs are satisfied by
> one fact and are not two decisions.**

> **Normative.** **No new user-facing question is created by a forecast read.** A read at
> the configured forecast provider is ruled `ALLOW` on route (c) with no confirmation
> sought and no grant seam consulted, and **no lane adds a prompt, a first-use
> confirmation, a per-conversation admission or a standing question for this kind.** This
> is the standing rule of 2026-09-12 binding in terms — convenience alone never justifies a
> user-facing restriction, and the owner's own words for this decision are *"without any
> new destination-trust decision"*.

> **Normative.** **Nothing rides this that is not a forecast read at the configured
> forecast provider.** An email, a fetch, a tool call, a search bound anywhere else and a
> forecast request bound anywhere else each keep ADR-0181 §5's floor, ADR-0193 §3 and §4,
> ADR-0155 §3 and ADR-0233 §9 exactly as written, in the very same conversation and the
> very same turn. **This is ADR-0238 §5's own last clause, restated because this ADR widens
> the exception ADR-0247 §3 guards.**

**Why the rule is stated over the request and not over the destination**, which is
ADR-0247 §1's argument inherited whole: a fact about a *destination* is readable by every
kind, so a call of another kind bound to the forecast provider's set would inherit an
authorisation the owner gave about forecasts. That call is unreachable today, and
*"unreachable today is exactly the argument this corpus refuses to rest on"*.

**And why the third conjunct is a carried fact rather than `closed_loop`.** ADR-0247 §4
defines `closed_loop` as *"the request's kind is `WEB_SEARCH` and this deployment holds a
search registration"*, so it is the conjunct that says *which act this is* — the derived
fact *"cannot assert which account and origin the binding carries; a lane reading it alone
reopens the hole §3's limbs are stated to close"*, and the converse holds too. §11
therefore gives `CarriedProvenance` **one more boolean in `closed_loop`'s own shape**
rather than widening `closed_loop`'s meaning, which would rewrite what every stored row
asserts and supersede a clause ADR-0247 §4 states as unchanged. §14 books the fold.

### 7. Servicing: one site, one budget, and where the forecast sits

> **Normative.** A `FORECAST_READ` ask is serviced in `orchestration/reads.py`'s
> `service_read_request` and **nowhere else**, inside the turn, after the planner returns
> and before the `TurnResult` is constructed. ADR-0226 §5 binds entire: the servicer is
> not the composing stage, is not a tool, is registered nowhere, advertises no capability,
> and **a servicing failure degrades the turn and never fails it.** `app/composition.py`
> wires the forecaster into that one site and into nothing else, and no lane adds a second
> caller.

> **Normative.** **ADR-0226 §5's channel scoping binds this kind unchanged.** A request is
> not serviced on an operation whose output channel's audience is unbounded, and no lane
> services a `FORECAST_READ` ask there on the ground that the reply will otherwise be
> thin. A planner on such a turn is not told; what is scoped is the servicing.

> **Normative.** **The servicing order is: local file, then web search, then forecast
> read, then citation hop, then structured read, then sighted query.** ADR-0226 §6's
> decision is applied and not moved — the capped read ahead of the uncapped one, with the
> sighted query as the read that *fills what remains* — and no configuration reorders
> them. **Where two kinds declare the same cap the earlier-admitted kind is serviced
> first**, which is the tiebreak this section fixes so that a seventh kind is placed by a
> rule rather than by a preference: a file is capped at one record, a search at
> `search_max_results` (no value above three), a forecast at `forecast_max_days` (no value
> above three), a hop at ten through its two labels, and the structured read and the query
> at what remains.

> **Normative.** **One budget, and the forecast draws at most `forecast_max_days` slots of
> it.** ADR-0226 §6's budget of ten binds per servicing, counted after deduplication. It
> is not a share, not a second budget, and **no lane funds it by lowering
> `RETRIEVAL_LIMIT` or `EPISODIC_SUPPLEMENT_LIMIT`.** Where the slots remaining when the
> forecast is reached are fewer than the days minted, the servicer admits the records that
> fit, in the order §5 minted them, and admits no more.

> **Normative.** **Where fewer than one slot remains when the forecast is reached, no
> request is composed, no ruling is sought and no channel is opened**, the disposition is
> `NO_BUDGET`, and §8's classifier produces **no outcome entry at all** for the ask. A read
> the budget prevented is not a read that found nothing, and no implementation, carrier or
> audit field conflates them.

> **Normative.** The admitted records enter **ADR-0226 §7's fourth group**, appended whole
> with the rest of the servicing's yield in servicing order. There is no fifth group and no
> forecast group; the three groups the planner saw keep their contents, their order and
> their positions; and §7's whole-union deduplication, discards-nothing-by-class clause and
> constructed-once rule bind on a minted forecast record as on any other.

> **Normative.** **The order inside one servicing is: bind, then rule, then record, then
> send.** No channel is opened before a recorded `ALLOW` exists. There is **no compose
> step**, because §3 gives the ask no argument to compose — which is one stage fewer than
> a search and is the whole of the difference between the two servicings.

> **Normative.** **`planned_with_external_content` on a forecast request's binding is the
> disjunction of `rests_on_recorded_external_content` over the turn's pre-servicing supply
> and over every record this servicing has already contributed**, computed by
> `orchestration` at the moment the request is built, from records it holds as data it
> fetched. It is written onto the carrier before `EgressBinder.bind` and is **discarded,
> never merged**, if any producer emitted one — ADR-0181 §4 applied at a third call site
> and not widened.

> **Normative.** **A serviced forecast read may revise the plan exactly as any other read
> may.** ADR-0251 §4's conditions are unchanged and none of them is about the kind; no lane
> adds one for this kind, and none suppresses a revision because the read was outward.
> **ADR-0204 §2's withholding evaluation and ADR-0223 §2's externality value are computed
> once, over the turn's final supply**, neither twice and neither from an intermediate
> supply; records this kind returns are inside both by construction.

> **Normative.** **The audit gains two fields on ADR-0226 §9's existing per-turn record
> and no second audit**: whether the ask was serviced, and its `ForecastDisposition` where
> it has one. **No value the provider returned, no day, no place, no coordinate, no origin,
> no account and no `Settings` field name reaches it**, which is ADR-0226 §9's
> counts-and-no-copy rule binding unchanged.

### 8. The typed outcome: `ForecastDisposition`, and where it lands in ADR-0251 §2's seven

> **Normative.** **`ai_assistant.orchestration.reads` gains `ForecastDisposition`** — a
> **closed** `StrEnum` valued by lower-cased member name, the servicing's own account of
> why a forecast read put no record into the supply — beside `SearchDisposition`, which is
> where ADR-0231 §13's test puts it: it *"crosses no subsystem boundary, being the
> servicer's own account"*, where `ForecastRefusal`, `ForecastOutcome`, `ReadOutcomeKind`
> and `ForecastNotRead` do cross one and are `core`'s. Its members are exactly: `NOT_CONFIGURED`,
> `NO_BUDGET`, `BINDING_FAILED`, `RULING_CONFIRM`, `RULING_DENY`, `RULING_UNAVAILABLE`,
> `SPEND_REFUSED`, `TRANSPORT_FAILED`, `DEADLINE_EXPIRED`, `RESPONSE_TOO_LARGE`,
> `PROVIDER_REFUSED` and `UNATTESTED`. The vocabulary is **added to and never renamed**,
> and no implementation, setting or later lane adds a thirteenth without the ADR that
> decides it.

> **Normative.** **A read that reached the provider and was answered records *no*
> disposition**, records or none: `ForecastRefusal.NO_RESULT` maps to no disposition, which
> is ADR-0231 §13's own construction and is what §10's contact rule is computed from.

> **Normative.** **Every member of both vocabularies maps onto exactly one member of
> `ReadOutcomeKind`, and ADR-0251 §2's classifier is extended and not replaced.** Its seven
> members, its closure, its four facts and its total precedence bind entire; what this
> decision adds is the two source vocabularies' members to §2's lists:
>
> - **`EXPIRED`** — `ForecastRefusal.DEADLINE_EXPIRED`, `ForecastDisposition.DEADLINE_EXPIRED`.
> - **`FAILED`** — `ForecastRefusal.TRANSPORT_FAILED` and `RESPONSE_TOO_LARGE`,
>   `ForecastDisposition.TRANSPORT_FAILED`, `RESPONSE_TOO_LARGE` and `BINDING_FAILED`.
> - **`REFUSED`** — `ForecastRefusal.PROVIDER_REFUSED` and `UNATTESTED`, and
>   `ForecastDisposition.NOT_CONFIGURED`, `RULING_CONFIRM`, `RULING_DENY`,
>   `RULING_UNAVAILABLE`, `SPEND_REFUSED`, `PROVIDER_REFUSED` and `UNATTESTED`.
> - **`EMPTY`** — `ForecastRefusal.NO_RESULT`, which is the provider answering with
>   nothing this read could use.
> - **No entry at all** — `ForecastDisposition.NO_BUDGET`, under §2's case 1, because
>   *"A read the budget did not reach is not in it."*
>
> `TRUNCATED` displaces `EMPTY`, `DUPLICATE` and `RETURNED_RECORDS` where ADR-0226 §6's
> budget cut this kind's yield, exactly as §2's precedence rules for every other kind, and
> `DUPLICATE` and `RETURNED_RECORDS` are reached by §2's own counting facts and by no rule
> of this ADR's.

> **Normative.** **Exactly one `ReadAskOutcome` per forecast ask the servicing reached**,
> and its `ask` is the frozen ask the planner emitted, carried back **byte for byte**.
> ADR-0251 §3 binds entire: nothing the source said crosses on it — *"No record, no count,
> no identifier, no instant of the read"* — the ask is never edited on the way, and the
> planner is still not told which round it is on.

> **Normative.** **No member of either vocabulary carries a message, a ground, a provider
> name, a destination, a place, a monetary figure, a duration, a count or a `Settings`
> field name**, and no statement rendered for one carries any of them. ADR-0242 §9's bar
> binds these vocabularies as it binds `SearchNotServiced`: **they state what became of the
> ask and never why a source ruled the way it did.**

**Two vocabularies and not one, which is ADR-0231's shape taken for its reason.** The seam
answers for what *it* did; the servicing answers for the stages the seam never sees — a
deployment that configured nothing, a budget that did not reach the ask, a binding that
would not derive, a ruling that was not an `ALLOW`. One vocabulary would make the
forecaster's contract carry members it can never return.

### 9. The evidence row: `requested` absent, `supported` composed from the extent

> **Normative.** A forecast servicing on a turn working on a goal produces a
> `READ_OUTCOME` evidence row under ADR-0252 §14's production rule, unchanged. Its
> `read_kind` is `FORECAST_READ`; its `source` is the forecaster's `name` (§4), which is
> what makes ADR-0252 §8's limb 3 finer than the kind; its `read_at` is the instant this
> system performed the read, from the injected clock; and its **`as_of` is the
> `Attestation.reported_at` the provider declared** (§5), absent on a read that minted no
> record.

> **Normative.** **`requested` is absent on a forecast row.** ADR-0252 §3's rule is
> applied and not bent: `requested` is composed *"from the **typed** part of the ask and
> from nothing else, and is absent where the ask has no typed part"*, and §3 above gives
> this ask no part at all. **No lane composes a `requested` from the configured place, the
> configured horizon, the provider's answer or the days it returned** — none of those is
> the ask, and a `requested` built from what came back is the manufactured applicability
> ADR-0252 §2 exists to prevent.

> **Normative.** **`supported` is one region per record the ask returned, composed from
> that record's own values**, and its **window axis is applied from the record's
> `Provenance.attestation.extent` and from nowhere else** — the day that record is about,
> as the provider stated it (§5). ADR-0252 §3's prohibition binds entire and is the rule
> here: *"a record's `Validity` is never read as a declared interval … Neither `valid_from`
> nor `valid_until` contributes to any region's `window`, on any kind, under any fallback,
> and no lane reinstates one."*

> **Normative.** **No other axis is applied**, and no lane infers one. A forecast record
> carries `topics` empty, `about_person` `None` and no `participants`, so each region
> applies its window and nothing else; and ADR-0252 §3's prohibition list binds word for
> word — `supported` is **never** derived from `requested`, from the fact that the read
> completed or reached its source, from a `ReadOutcomeKind` member on its own, from a
> model's sentence about what a response covered, or from any inspection of a record's
> text. **In particular no axis is derived from the configured place**, which is a fact
> about where we asked and not about what the answer established.

> **Normative.** **A forecast row names no record and its count stands alone.** ADR-0252
> §1's second axis gains this kind on its **ephemeral** side, beside `WEB_SEARCH` and
> `LOCAL_FILE` and for that side's stated reason — *"their records are minted for one turn
> and resolve in no store … the split is by where the record lives and not by which ADR
> minted it"* — so `records` is empty, `returned` and `admitted` are counts, and no
> identifier of a minted record reaches a durable row. §15 records the amendment this makes
> to that clause.

> **Normative.** **The digest the planner sees is ADR-0252 §11's, unchanged.** This
> decision adds no member to `EvidenceDigest`, no field to its rendering and no
> configuration of it; a forecast row's regions render by §11's deterministic rule exactly
> as any other row's, and the planner is still not told which rows satisfy anything.
> `MAX_GOAL_EVIDENCE`, ADR-0252 §13's bound and its elision disclosure are untouched.

**This is the row ADR-0252 §3 says the corpus cannot write today, and the difference is
one field.** That section observes that *"every `WEB_SEARCH` and every `LOCAL_FILE` row
carries `supported` empty, fails §6's first test, and satisfies no condition"*, because
neither minting clause declares an extent. A forecast record declares one per day, so a
goal whose criterion is about Saturday meets a region that covers Saturday and one that
does not. **What it still does not establish is whether the forecast is right**: an extent
says where the reported entry lies, never that the report is accurate.

### 10. What the user is told, and the contact this turn made

> **Normative.** `core/types.py` gains **`ForecastNotRead`**, a **closed** `StrEnum` valued
> by lower-cased member name — the **user-facing** fold of §8's disposition — with exactly
> these members: `NOT_CONFIGURED`, `AUTHORISATION_AWAITED`, `SPEND_EXHAUSTED`, `DECLINED`,
> `INTERRUPTED` and `UNAVAILABLE`. It is a fold and is **non-injective by design**, which
> is ADR-0242 §8's shape for its own reason: the surface is told a class, never a cause.

> **Normative.** `TurnOutcome` gains exactly one field, **`forecast_not_read`**, typed
> `ForecastNotRead | None` and defaulting to `None`, carrying **the member the servicing
> computed, by value, and never a second computation** — ADR-0242 §9's placement for its
> own member. **`None` means the servicing recorded no `ForecastDisposition`, and means
> nothing else**: a turn that serviced no forecast read, and a read the provider answered.
> **`SpokenTurn` gains nothing**, and no lane adds a second field for this fact anywhere.

> **Normative — the fold, stated totally over the twelve dispositions**, because a fold
> whose domain is not enumerated is a fold two implementations will disagree about:
> `NOT_CONFIGURED` → `NOT_CONFIGURED`; `RULING_CONFIRM` → `AUTHORISATION_AWAITED`;
> `SPEND_REFUSED` → `SPEND_EXHAUSTED`; `RULING_DENY` → `DECLINED`; `DEADLINE_EXPIRED` →
> `INTERRUPTED`; and `NO_BUDGET`, `BINDING_FAILED`, `RULING_UNAVAILABLE`,
> `TRANSPORT_FAILED`, `RESPONSE_TOO_LARGE`, `PROVIDER_REFUSED` and `UNATTESTED` →
> `UNAVAILABLE`. **It is non-injective and that is the point** (ADR-0242 §8): seven
> dispositions the user has no act for fold onto the one member that names none. **A
> contact and an `UNAVAILABLE` ride together where both hold** — a `RESPONSE_TOO_LARGE`
> or an `UNATTESTED` reached the provider and yielded nothing usable — which is ADR-0264
> §8's both-statements rule and not an exception to it.

> **Normative.** A surface renders, **beside the reply and never in place of it**, one
> fixed statement per member, under ADR-0242 §9's bar binding word for word: **no statement
> says that performing the act it names will make the next read happen, and none says why a
> ruling was not an `ALLOW`.** No statement names a floor, a threshold, a `Settings` field,
> a configuration value, a provider, an origin, a place or a coordinate. `NOT_CONFIGURED`
> says a forecast source is not configured in this deployment and that it is an operator
> setting, **naming no user act**; `SPEND_EXHAUSTED` says a spend ceiling refused it and
> that it is an operator setting; `AUTHORISATION_AWAITED` says the read was put to the user
> as a question instead of being made and that a decision is recorded, naming `assistant
> decisions` as where it is read; `DECLINED` says it was declined when it was ruled on;
> `INTERRUPTED` says it was begun and stopped; and `UNAVAILABLE` says the read produced
> nothing the turn could use, **naming no cause and no act**. The exact wording is the
> lane's; what is fixed is which command each names and that `UNAVAILABLE` names none.

> **Normative.** `OutboundDestination` gains a **second member, `FORECAST_PROVIDER`** — the
> configured forecast provider, which §6 makes the destination the owner chose and the
> recipient they granted. It renders **after** `SEARCH_PROVIDER` in ADR-0264 §5's own
> order, and §5's class-never-a-destination rule binds on it: it names, encodes and is
> derived from no provider, host, account, connection or tool. This is the addition
> ADR-0264 §5 requires of a later outbound seam rather than a departure from it.

> **Normative.** **A forecast read establishes an outbound contact where its call completed
> and recorded no `ForecastDisposition`** — which is a read that reached the provider and
> was answered, records or none — **or** where the disposition it recorded is
> `RESPONSE_TOO_LARGE` or `UNATTESTED`, each of which this system reaches only from octets
> the provider's channel had already returned. A call whose disposition is
> `NOT_CONFIGURED`, `NO_BUDGET`, `BINDING_FAILED`, `RULING_CONFIRM`, `RULING_DENY`,
> `RULING_UNAVAILABLE` or `SPEND_REFUSED` establishes **no** contact — every one of those
> is a stage before the send. A call whose disposition is `TRANSPORT_FAILED`,
> `DEADLINE_EXPIRED` or **`PROVIDER_REFUSED`** establishes **nothing either way** and
> contributes `INDETERMINATE`: `PROVIDER_REFUSED` is recorded **both** for a response the
> provider gave and this system refused **and** for an account that changed across the
> credential read, whose limbs *"discarded the credential and wrote nothing to any channel
> — none was opened"* (ADR-0148 §6), and the disposition carries no value separating them.
> **The partition is total over the twelve members and the absence of one is the
> thirteenth case**, and the least-claiming direction is taken deliberately, which is
> ADR-0264 §2's own reading of its own third group at a second performing site. It is
> computed **at that site** from the outcome it holds, and **no site recomputes
> another's**.

> **Normative.** **The fact is never derived from `ForecastNotRead`**, which is
> non-injective by design; a site holding only the folded member cannot compute it and does
> not try. ADR-0264 §1's three-valued statement, its never-inferred clause and §8's
> both-statements-ride-together rule bind entire, and a turn that searched and read a
> forecast carries one statement naming both classes.

**The negative statement is owed for ADR-0242's own reason and the positive one for
ADR-0264's.** A forecast that did not happen is invisible in a reply composed without its
records, and the model is then free to say something the trail contradicts — the asymmetry
#2268 recorded for search, arriving at a second seam. It costs one enumeration and one
optional field here, where discovering it afterwards cost a milestone QA run.

### 11. `Settings`, persistence, and the versions that move

> **Normative.** `Settings` gains nine fields, **in `web_search_*`'s own shape field for
> field**, so that an operator configuring the second provider configures the same shape
> twice: `forecast_connection: str | None` and `forecast_origin: str | None`, **set
> together or neither**; `forecast_latitude: float | None` and `forecast_longitude: float
> | None`, set together and only where the pair above is set; `forecast_cost_per_call:
> Decimal | None` and `forecast_cost_currency: str | None`, in
> `web_search_cost_per_call`'s own cross-field shape; and the three bounds
> `forecast_max_days: int`, `forecast_max_day_chars: int` and
> `forecast_max_response_bytes: int`, each in `search_max_results`',
> `search_max_result_chars`' and `search_max_response_bytes`' own shape, **each shipping
> with a value** so that no deployment is unbounded by omission.

> **Normative — every domain is closed and a value outside it stops the deployment**, which
> is the fail-fast `Settings` already performs on the search pair rather than a new posture.
> `forecast_latitude` is a **finite** float in `-90.0..90.0` inclusive and
> `forecast_longitude` a **finite** float in `-180.0..180.0` inclusive, `NaN` and either
> infinity refused on both — a coordinate that is not a place would compose a request no
> provider documents an answer for. `forecast_max_days` is an integer in `1..3`
> inclusive (§7), `forecast_max_day_chars` and `forecast_max_response_bytes` are integers
> **strictly greater than zero**, and a zero or negative bound is refused rather than read
> as "no limit": a bound whose value makes every successful read unrepresentable is a
> misconfiguration and never a policy.

> **Normative.** **`forecast_max_response_bytes` bounds what is read off the channel, and
> it is enforced *while reading* and before anything is parsed.** A response whose body
> reaches the bound is abandoned at that point and the read is `RESPONSE_TOO_LARGE`; **no
> implementation buffers a whole body and measures it afterwards**, which would let a
> provider buy memory from a client that has already opened a channel. This is the bound
> `ForecastRefusal.RESPONSE_TOO_LARGE` and `ForecastDisposition.RESPONSE_TOO_LARGE` are
> the outcome of, and it is stated here because a refusal member with no defined trigger
> is a member no implementation can reach correctly.

> **Normative.** **No second deadline figure is added.** The forecast read runs under the
> deadline ADR-0241 §1 already hands the servicing, and §4's `timeout` is the remaining
> time at that point. A `Settings` figure of its own would be a second bound on one turn.

> **Normative.** **Where the cost pair is unset the unknown-cost floor binds unchanged**
> (ADR-0016 §4, ADR-0236 §1, §4), which ADR-0247 §9 keeps untouched and this ADR does not
> approach. That floor is a question about **cost** and not about destination trust, so
> §6's no-new-question clause is not in tension with it; a deployment that wants the read
> to run without one states the provider's cost, which for a keyless free provider is zero
> in the currency it states.

> **Normative.** `CarriedProvenance`, and so `EgressBinding`, gains **one boolean,
> `forecast_reach`**, defaulting to `False` — in `closed_loop`'s own shape and for its own
> reason. It is written `True` exactly where the request's kind is a forecast read and this
> deployment holds a forecast registration, which `orchestration` knows because
> `Forecaster.request` answered a proposal rather than `None`. **It is written by
> `orchestration` alone**, at the moment the request is built, from values it holds as data
> it fetched; **discarded, never merged**, if any producer emitted one; and no model output,
> request content or provider answer contributes to it. **`False` is the restrictive
> value**, so a composition site that fails to compute it yields a request that is not at
> the configured forecast provider and rules exactly as `origin/main` rules today.
> **`closed_loop` is untouched** in its field, its type, its default, its carriage and its
> comparison inside `PermissionDecision.authorises`, and keeps meaning *"this deployment's
> own search"* and nothing else.

> **Normative.** **`forecast_reach` is compared inside `PermissionDecision.authorises`
> beside `closed_loop`**, in that field's own shape, so a ruling authorises only a request
> carrying the fact it was taken over. **And `EgressBinder.rebind` transcribes nothing new,
> because no forecast binding is ever rebound**: this decision mints **no park** for a
> forecast read — ADR-0244's park is a `CONFIRM` on a **search**, and nothing here widens
> it — so a forecast read ruled `CONFIRM` is recorded, is not made, is not parked, and is
> reported under §10's `AUTHORISATION_AWAITED`. **ADR-0152 §7's and ADR-0247 §7's closed
> transcription count is therefore untouched and this ADR supersedes neither**: `rebind`
> rebuilds a `CarriedProvenance` for a **search** binding, where `forecast_reach`'s
> restrictive default is the correct value. §14 defers the resumable forecast park and
> names what fires it — and the lane that opens one owes the fifth transcription and the
> record against those counts, in its own ADR.

> **Normative.** **Nothing a forecast read produces is stored.** No minted record reaches
> `MemoryWriter.ingest` or any store, no response is cached, no answer is retained past the
> turn, and `MAX_EVIDENCE_CITATIONS` and every other `MemoryWriter`-seam bound is not
> engaged. ADR-0052 §3's ephemerality is the rule and this decision adds no exception; what
> survives the turn is the evidence row §9 writes and the audit fields §7 names.

> **Normative.** **`PROTOCOL_VERSION` moves by one on the lane that lands the `core`
> surface, with its own log entry naming this ADR.** The figure is that lane's, because
> more than one lane in flight moves it and a number written here would be a claim that
> goes stale silently.

### 12. What the implementing lanes owe

> **Normative.** **Three lanes, in this order, each its own PR.** **L1 — the contract with
> its primary production implementation, one lane and one PR**, which is ADR-0137 §2's
> sanctioned cut and not a licence taken here: *"the contract triad together with its
> primary production implementation is one unit of work"*, primary being *"the consumer
> whose demands shape the contract"*, so the contract stays **soft while its hardest
> consumer stress-tests it**. It lands the `Forecaster` Protocol with its **conformance
> suite** and its **canonical fake in `ai_assistant.testing`**; the concrete forecaster,
> its declaration and its provider adapter in `tools/`, driving the `HttpsExchange` the
> designated seam holds, reaching **no transport of its own**, and added to the
> transport-confinement contract's enumerated `source_modules` in the same change;
> `ForecastOutcome` **with its structural validator**, `ForecastRefusal`,
> `ForecastNotRead`, the `ReadKind` member and `ReadAsk`'s sixth arm, the
> `OutboundDestination` member, `CarriedProvenance.forecast_reach` with its comparison
> inside `PermissionDecision.authorises`, `TurnOutcome.forecast_not_read`, the nine
> `Settings` fields with their domains, the `PROTOCOL_VERSION` move, and
> `app/composition.py` building the forecaster. **`ForecastDisposition` is not L1's**: §8
> places it in `orchestration/reads.py`, with L3.

> **Normative.** **L2 — the authority, in `permissions/` alone**: §6's widened route (c),
> the two restated `_only_the_disclosure_floor` limbs, the one new constructor argument
> carrying the configured forecast destination, and `app/composition.py` supplying it — the
> one file outside `permissions/` this lane touches and the composition root's own job.
> **It lands before L3 and changes no live behaviour on its own**, because nothing yet
> asks for a forecast read.

> **Normative.** **L3 — the servicing, in `orchestration/` alone**: §7's servicing site and
> its two audit fields, §8's `ForecastDisposition` and its classifier entries, §9's
> evidence composition, and §10's fold and contact carrier.

> **Normative.** **Every lane corrects, in its own change, every docstring and comment
> that cites a rule it moved** — `ReadKind`'s count sentence, `ReadAsk`'s arm docstrings,
> `permissions/policy.py`'s `_at_configured_provider` and `_only_the_disclosure_floor`
> notes, `CarriedProvenance.closed_loop`'s description and `wire/envelope.py`'s version
> log. A module describing a check the tree does not have is a false statement these
> decisions create, and it is not a second change. **No lane files or defers anything this
> ADR has not named**; no lane re-drives the mechanism on a live hub, and the deployment
> owed after L1 is the dispatcher's act.

> **Normative.** **L1 delivers the real provider.** Open-Meteo is keyless and free, so
> there is no quota and no credential; its response carries the RFC 9110 `Date` field the
> search seam's declared-instant rule already reads (§5); and its daily table names its
> days and declares the UTC offset they are in, which is what §5's extent is computed from.
> **A mock behind the same `Forecaster` contract is the fallback and changes no clause of
> this ADR** — delivered instead only where the real provider cannot be registered against
> a connection reference with no credential to hold, and the lane says which and why.

### 13. The arms this decision owes

> **Normative.** Each arm is a test the owning lane owes, over the **production** type or
> component and never over a fake standing in for it, and each is **deterministic, offline
> and in the ordinary gate**.

> **Normative.** **(a) The empty ask.** A `ReadAsk` of this kind carrying a `query`,
> carrying `labels`, carrying an `entry` and carrying a `structure` is refused, each with
> its own message; one carrying none of the four constructs. **L1.**

> **Normative.** **(b) The extent, and the fallback that is not taken.** A response whose
> day the provider names with a declared offset mints a record whose
> `Attestation.extent` is that day's own half-open interval and whose `MemoryBase.validity`
> is fully open; a response naming a day without declaring an offset mints **no record for
> that day**. **L1.**

> **Normative.** **(b′) The refusals at the boundaries.** A `ForecastOutcome` carrying a
> record that is not `SEMANTIC`, one whose `Provenance` is not `EXTERNAL`, one carrying
> non-empty `evidence`, one whose `validity` is not fully open, one carrying no `extent`,
> one whose `reported_by` differs from its siblings', and one whose attestation instant
> differs from the outcome's `reported_at`, is **refused at construction** in each case; a
> `Settings` naming a non-finite or out-of-range coordinate, a `forecast_max_days` outside
> `1..3`, a non-positive `forecast_max_day_chars` or `forecast_max_response_bytes`, **or
> any half-set pair** — connection without origin or the reverse, one coordinate without
> the other, one cost field without the other, and coordinates or costs with no provider
> pair — **does not start**; and a body of exactly `forecast_max_response_bytes` is read
> and minted where one of that figure plus one is abandoned **while reading**, yielding
> `RESPONSE_TOO_LARGE` with no parse attempted. And over the **production** forecaster's
> own output, a minted record's `confidence` is `0.9`, its `derived_from_external` is
> `False` and its `placement` is the default that narrows nothing — the three §5 facts that
> are the producer's rather than `ForecastOutcome`'s, in `SearchOutcome`'s own division of
> labour. **L1.**

> **Normative.** **(c) The declared instant.** A response declaring no instant, and one
> carrying an unreadable value in that position, each mint **no record** and yield
> `UNATTESTED` — and in neither case does any minted value equal a clock the test
> controls. **L1.**

> **Normative.** **(d) The mismatched binding.** A forecast request whose account or
> origin is not the configured pair, and a request of another kind bound to the configured
> forecast pair, each take **no** route (c): both `_only_the_disclosure_floor` limbs bind
> in full and the ruling is what it is today. **L2.**

> **Normative.** **(e) No new question.** A turn on a goal whose supply already carries an
> external record asks for a forecast at the configured provider and is ruled `ALLOW` with
> **no** `CONFIRM`, **no** grant seam read and `authorised_subject` unset — and the same
> turn's search at an unconfigured destination is unaffected. **L2.**

> **Normative.** **(f) The budget and the order.** A servicing whose file and search have
> taken nine slots admits **one** forecast record and records the kind as truncated; one
> reached with no slots left composes no request, opens no channel, and yields **no
> outcome entry** for the ask. **L3.**

> **Normative.** **(g) The evidence row.** A forecast servicing on a goal turn writes a
> row whose `requested` is absent, whose `records` is empty, and whose `supported` carries
> one region per admitted record applying **only** a window equal to that record's extent —
> and a row over a record whose extent is absent carries no region for it. **L3.**

> **Normative.** **(h) The statement and the contact.** A read the provider answered
> carries `forecast_not_read` `None` and an outbound statement naming
> `FORECAST_PROVIDER`; a read refused before the send carries the folded member, its fixed
> statement and **no** destination class; a transport failure carries `INDETERMINATE`; and
> **both** producers of `PROVIDER_REFUSED` — a response the provider gave and this system
> refused, and an account that changed across the credential read — carry `INDETERMINATE`
> with `destinations` empty, asserted separately so that neither can regress to `REACHED`
> or `NOT_REACHED` while the other holds. **L3.**

### 14. Deferred, by name, each with what fires it

> **Normative.** This decision settles nothing about the following, and no lane cites it
> toward any of them. Each is named so that a reader cannot mistake this ADR's silence for
> a ruling.

- **A place listing, and a forecast for a place the turn named.** §3 fixes one configured
  place. Fired by a type that carries a recorded coordinate — a location belief, or the
  booking integration's own answer — at which point the ask gains a **label into a listing
  the loop showed**, in ADR-0230 §2's address-space shape, and never a coordinate the
  planner wrote.
- **Geocoding.** Turning a place name into a coordinate is a second destination and a
  second registration. Fired by the lane that needs the bullet above.
- **The booking integration**, a `tools/` integration at ADR-0154's seam and its own
  decision under ADR-0016/ADR-0018. Fired by #2255's M33 walkthrough lane.
- **Autonomous web research (C-WEB)** and **milestone 32's bounded fetch**. ADR-0247 §9's
  bar stands, and **no clause of this ADR is cited toward either.**
- **A second reader kind** — a tide, an air-quality, a transit source. Fired by its own
  ADR under ADR-0226 §1.
- **Folding `closed_loop` and `forecast_reach` into one closed enumeration on
  `CarriedProvenance`.** §6 declines it because it would rewrite what stored rows assert.
  Fired by a **third** configured-provider kind, where two booleans become the drift the
  fold exists to remove.
- **A resumable forecast park.** §11 mints none, so a forecast read ruled `CONFIRM` is
  recorded and not made. Fired by a decision that parks one, which owes `rebind` a fifth
  transcription and the record against ADR-0152 §7's and ADR-0247 §7's counts.
- **Caching, retention or scheduling of a forecast.** §11 stores nothing and §7 services
  inside a user-started turn only. Fired by a decision that gives an ephemeral read a
  durable home, which ADR-0251 §14 already owns for typed outcomes.
- **Whether a forecast is *right*.** §5 attests the provider's claim and nothing more;
  verification against a goal's criteria is A10's (ADR-0252 §15).

### 15. Scope, and what this records against earlier ADRs

**The six records this ADR owes are declared here, each with ADR-0070 §1's test applied
to the earlier ADR's text, which is what ADR-0082 §1 asks of an author.**

> **Normative.** **ADR-0155 §3's second clause, ADR-0233 §7 and ADR-0233 §9's four
> conditions are untouched and are not reachable from here.** A span carrying covered
> content some covered path of which contains **no** model call stays forbidden absolutely:
> `SpanCoverage.PATH_WITHOUT_MODEL` is refused by ADR-0233 §6's construction-time refusal
> before any policy sees it, and no clause here relaxes, conditions or routes around it.

> **Normative.** **No grant seam, and this ADR contracts none.** It adds no `GrantScope`
> member, contracts no `SourceGrants` into this seam, and gates the read on no source
> grant. ADR-0097, ADR-0132, ADR-0133 and ADR-0185 are untouched, and no lane reads this
> section as relaxing any of them for a `Reader`. **What authorises a forecast read is the
> owner's own turn and §6's ruling**, and ADR-0230 §11's three firing conditions are
> inherited whole: a forecaster driven from anything that is not a user-started turn, one
> over a source this deployment did not configure, and a read whose yield is written to
> any store each **fire a grant decision, and a lane meeting any of them stops rather than
> proceeding.**

- **ADR-0247 §1's first clause and §8(a) — partially superseded** (header). A reader
  holding only ADR-0247 would read *"whose kind is `WEB_SEARCH`"* and *"that account and
  that origin, and no other"* as the whole population of the configuration-based
  authority, and would refuse §6's ruling. The test comes out on the supersession side,
  and ADR-0070 §3's partial form is the sanctioned tool.
- **ADR-0238 §1's third clause — partially superseded** in the forecast-read limb alone
  (header), carrying ADR-0247 §1's own supersession of it to a second kind. A reader
  holding only ADR-0238 would read *"No configuration sets it"* as binding here.
- **ADR-0226 §2 and §6 — amended**, the membership sentence and the cross-kind precedence
  sentence, one respect each. A reader holding only ADR-0226 would read the enumeration as
  five members and would read *"The citation hop is serviced first"* as naming the first
  serviced read; §1 of that ADR expressly provides for the first, and the third, fourth and
  fifth members each amended both in turn.
- **ADR-0251 §2 — amended**, per-member source lists only. A reader holding only ADR-0251
  would find this decision's two vocabularies unclassified and would have no member to
  place them on.
- **ADR-0252 §1 — amended**, the second axis's ephemeral-kind list only. A reader holding
  only ADR-0252 would validate a `FORECAST_READ` row under the durable arm and require
  `len(records)` to equal `returned`, which §9 makes wrong.
- **ADR-0264 §3 and §5 — amended**, §3's first clause and §5's closure at one member, one
  respect each. A reader holding only ADR-0264 would read *"from a `WEB_SEARCH` call and
  from nothing else"* as barring §10 and the vocabulary as closed at one, and §5's own
  invitation to a later seam is what shows both readings cannot stand. **§3's prohibition —
  its actual subject, the egress step machinery — binds entire**, and §10 derives the fact
  from a forecast call's recorded disposition and from nothing that clause names.

**The clause above is the first of two things this section states; the second is the
clauses a reader would expect to have moved, and which did not.** **ADR-0093
§10's no-arguments rule** — `Reader.read()` still takes no arguments, and its reason is
**honoured** by §3 rather than worked around: this seam's ask carries nothing either, and
the bound stays the source's own configuration. **ADR-0092 §3** — unamended, and §5 takes
the provider's declared instant with no substitute; ADR-0230 §5's local-substitute scope
expressly does not reach a remote source's earlier answer. **ADR-0208 §1** — honoured by §1 rather than approached, and this
kind is no relevance selection over the store, so it needs no supersession either. **ADR-0252
§3** — its `requested` enumeration is scoped in terms to *"the vocabulary ADR-0226 §2,
ADR-0230 §1, ADR-0231 §1 and ADR-0240 §1 leave closed"*, so a sixth member is outside what
it names; §9 is a **stacked addition** recorded here and, under ADR-0082 §1, owing that ADR
no record. **ADR-0117 §2** — used as given, and §8's general rule is the ground §5 mints an
extent on. **ADR-0185, ADR-0097, ADR-0132 and ADR-0133** — untouched; §4 contracts no grant
seam, for ADR-0230 §11's reason.

### 16. Marking, review and ratification

This ADR is **marked** under ADR-0089: every clause a reader could disobey is a
`**Normative.**` block quote, and unmarked text is read to determine what a marked clause
*means* and supplies no obligation of its own (§3). ADR-0257's labelled form is available
and unused. Marking is forward-only and nothing already ratified is marked by it (§5).

**The required review set is adversarial *and* architecture**, for ADR-0015 §1's reason:
this decides `core/protocols.py` surface and a package boundary, prose-only though the PR
is. It is **reviewed while `Proposed`** and ratified only after, and **no lane implements
against any clause until this ADR is merged** (golden rule 5, ADR-0015 §5).

## Consequences

**What becomes easier.** A turn can ask the world a structured question whose answer is
records rather than prose, and the evidence machinery ADR-0252 built acquires its first
producer that can make a `supported` window mean something — the half of #2255's lifecycle
that has been stated and never exercised. §6 is also the first time the
configuration-based authority is written over more than one kind, so the lane that adds a
third finds it already general.

**What becomes harder, stated rather than glossed.** There are now **two** carried facts
about being at a configured provider where there was one, and §14 books the fold rather
than pretending the drift is not there. The egress relaxations reach two kinds instead of
one, a wider surface for a later ADR to widen again — §6's last clause and ADR-0247 §9's
bar hold that line, both stated over the *request*. And a deployment that configures a
forecast provider spends up to three of ADR-0226 §6's ten record slots on it whenever the
planner asks, which the hop and the query then do without.

**What would trigger revisiting this.** A measurement that the three-day cap is the wrong
figure; a place listing arriving from the booking side, which fires §14's first bullet; a
third configured-provider kind, which fires the fold; or a provider whose response declares
no instant, which §5 makes unusable — the honest answer there is a different provider
rather than a substituted clock.

## Alternatives considered

**A `Reader` over a configured forecast source, read on its own cadence and ingested.**
This is #2255's own wording and it is the alternative a reader will most want. It is
refused because the two consumers it would have are the wrong two: ADR-0095's `Reader`
feeds the situational-context facet and the ingestion stage, both *cadences*, and ADR-0096
§3 and ADR-0252 §3 between them forbid a facet from serving a carried-over reading or
producing an evidence row at all. A forecast a turn asks for, whose answer becomes that
turn's evidence, is a turn-time read — and ADR-0230 §4 already ruled that *"Reusing
`Reader` was never available"* for exactly that shape. The refusal costs one more Protocol
in `core`; accepting it would have cost a scheduled ingester writing durable weather
beliefs about the owner, which ADR-0230 §11's third firing condition makes a **stop**.

**An ask carrying a planner-composed `TimeWindow`.** It would give ADR-0252 §3's
`requested` a typed part and let a planner ask about a specific weekend. It is refused
because a window the planner composed is model output reaching an egress payload, and what
it buys is small — the provider's own horizon already covers the days a planner would name
— against the property ADR-0231 §1 calls a kind's *whole safety mechanism*. §14's
place-listing deferral is the shape in which an argument returns, and it returns as a
**label into a listing the loop showed**, never as a value the model wrote.

**A registered tool at the egress seam, invoked through `ToolInvoker`.** Refused by two
rulings §1 satisfies by not being a tool: ADR-0170 §5a, *"a tool's result is a JSON payload
with no per-span provenance"*, and ADR-0208 §1, *"A component on the turn path that wants
records the supply does not hold does not obtain them by invoking a tool"*.
