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
  onto it, and §8 below adds this decision's two vocabularies to them. §2's seven
  members, its closure, its classifier, its four facts, its total precedence and its
  no-message clause all bind entire and none moves.
- **Amends** [ADR-0252](0252-evidence-is-what-a-response-supports-sufficiency-to-act-is-four-mechanical-tests-and-a-refresh-supersedes-the-row-it-displaces.md)
  **§1's second axis, in its ephemeral-kind list alone.** That axis puts `WEB_SEARCH` and
  `LOCAL_FILE` on the side where `records` is empty and the count stands alone; §9 below
  puts a third kind there, for the axis's own stated reason that *"the split is by where
  the record lives and not by which ADR minted it"*. **§3 is not amended** — its
  `requested` enumeration is scoped in terms to a vocabulary a sixth member lies outside,
  so §9's entry is ADR-0082 §1's *stacked addition* — and §2's algebra, §3's window axis
  and prohibition list, and §§4-19 bind entire.
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

and the design report's Q3, over a weather reader and a booking integration at the `tools/`
seam: it demonstrates investigation and verification *"**without any new destination-trust
decision** … already-governed shapes."*

**This ADR is the forecast half and nothing else.** It decides one read kind and one seam,
and no relaxation reachable by anything that is not a forecast read at the configured
provider. **§14 names everything it does not settle, each with what fires it.**

The owner's ruling of 2026-09-14 fixes the reference provider: **Open-Meteo**, free and
keyless, configured the way the search provider is. No vendor is named in any normative
clause — §6's authority is stated over *the configured provider* — and §12 records what L1
delivers.

### The tree, read rather than assumed, at `origin/main` `8dbfddf0`

- **`ReadKind` has five members** — `SIGHTED_QUERY`, `CITATION_HOP`, `LOCAL_FILE`,
  `WEB_SEARCH`, `STRUCTURED_READ` — its docstring recording the third to fifth as additive
  entries under ADR-0226 §1's licence. `ReadAsk` has one field per kind's argument and a
  five-arm validator, `WEB_SEARCH`'s being the arm that refuses all four arguments.
- **`tools/web_search.py` is the worked shape** for a configured HTTPS provider at that
  seam — a declaration, a provider adapter and a searcher driving the seam's own
  `HttpsExchange`, reaching no transport of its own, bound by the import contract.

### What the corpus already decides, and is used here as given

- **ADR-0226 §1** closes the read-request enumeration and fixes how it grows: an ADR
  admitting a kind *"adds a member and states that kind's namer, its servicing, its share
  of §6's budget and its audit fields; it does not introduce a second request object, a
  second servicing site, a second budget or a second audit."* §2 and §7 are that statement.
- **ADR-0230 §5 and ADR-0231 §10** are the two minting precedents, and §5 below follows
  the second where they differ, a forecast provider being a remote source answering a live
  interrogation.
- **ADR-0117 §2's extent, and §8's general rule.** *"Where a source's entries have a
  position in that source's world, that position is producer testimony and is carried by
  the extent (§2); it is never carried by the record's envelope validity window."* §8 names
  what made the calendar the hard case — it is **forward-looking**, a forecast's own property.
- **ADR-0252 §15** names what an evidence row needs from this decision and declines the
  rest: the reader's declared identity, an `Attestation.reported_at` for `as_of`, and
  *"for `supported`, a `ReportedExtent` (ADR-0117 §2) … the only authority this decision
  will accept for what a reader covered"* — while *"how a reader's read is asked for,
  serviced, budgeted or audited is that lane's"*.

### The premise in the framing that does not survive contact with the tree

It is recorded because, taken at face value, it would have produced a different and wrong
decision. The other two — a `Reader`, and a `Validity` as the evidence window — are refused
under "Alternatives considered" and by §5's own clause.

**`SourceReadRecord` is not what a forecast read returns.** ADR-0185 §2 makes it an
audit row that *"carries **no source content**, no entry, no path and no configured
location"* — no `Provenance`, no `Validity`, no `Attestation`. What a serviced read returns
into the supply is `MemoryRecord`s (ADR-0226 §1), and §5 fixes their provenance.


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

**Named for its product role, as every Protocol in that module is** (`Planner`, `Observer`,
`Reader`, `Fetcher`, `WebSearcher`): the role is *asking a configured outside source what it
says about the days ahead*, so the seam is a **`Forecaster`**.

**The difference from `Reader` is the one ADR-0230 §4 already named, and it is not about the
weather.** A `Reader` takes no address; a turn-time read must be a contract that can be
*asked*, and §3 makes this one's ask none at all — so ADR-0093 §10's reason is honoured.

**And the difference from a `ContextProvider` is the cadence.** ADR-0252 §3 rules that no
facet produces an evidence row, and ADR-0096 §3 bars one from a carried-over reading.

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
over.** §1 of that ADR rules that *"no lane widens an admitted kind's meaning to carry a read
the ADR that admitted it did not describe"*, and ADR-0231 §1 says a `WEB_SEARCH` **is** one
search whose query is composed from the turn's utterance. A forecast read composes nothing —
so folding the two would widen a kind's meaning and change its servicing, against both.

**And the two do not reach the same records.** A search mints transcriptions carrying no
structural axis — *"every `WEB_SEARCH` and every `LOCAL_FILE` row carries `supported`
empty"* — where a forecast mints records that each declare an extent (§9).

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

**An empty ask is the strongest form available and is chosen for that reason.** The
alternatives — a planner-composed window and a planner-named place — are refused in
"Alternatives considered". What the corpus says of the search seam's empty arm holds word
for word: *"a field the planner cannot write is a field that cannot carry covered content"*.

**The honest cost is that one deployment reads one place**, stated rather than glossed.
The campsite walkthrough's forecast half is answered for the owner's own configured place;
a forecast *at the campsite* needs a recorded coordinate no type on the tree carries today,
which §14 defers with what fires it.

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
> changes either way. **A keyless provider is still provisioned as a connection like any
> other, and this ADR gives it no exemption**: §6's binding needs the ACTIVE record
> `Settings.forecast_connection` names, ADR-0148 §6's and ADR-0149 §3's shape for that
> record is untouched, and its credential slot is one the forecaster never reads rather
> than one that does not exist. **A credential-free connection representation is
> explicitly not decided here** — it would amend ADR-0148, ADR-0149 and ADR-0151 in
> `tools/`, which is another decision in another lane, and no clause of this ADR needs it.

> **Normative.** `core/types.py` gains **`ForecastOutcome`**, a frozen model refusing
> mutation and unknown fields, carrying exactly `records: tuple[MemoryRecord, ...]`,
> `reported_at: UtcInstant | None` and `refusal: ForecastRefusal | None`, with **exactly
> one of** a non-empty `records` and a non-`None` `refusal`, enforced by the model —
> neither both nor neither — and `reported_at` present exactly where `records` is.
> **It carries no count of the days §5 dropped**, for the reason §7 gives.

> **Normative.** **`ForecastOutcome` itself enforces exactly the following and no others**,
> in `SearchOutcome`'s own shape and for its stated reason: conditions on the model are
> *"decidable in any process and true of every"* implementation this system ever wires,
> **the canonical fake included**. Every record is `SEMANTIC`, carries
> `MemorySource.EXTERNAL`, carries empty `evidence`, carries empty `topics`, carries no
> `about_person`, carries a fully-open `validity`,
> carries an `Attestation` whose `reported_by` is one value shared by every record of the
> outcome, carries an `extent` that is a constructible half-open interval, and carries a
> `reported_at` **equal to the outcome's own** — a record disagreeing with its outcome
> about when the source spoke is two answers in one value. **No condition reaches for a
> bound, a clock, a store or a configuration**: `forecast_max_days`,
> `forecast_max_day_chars` and `forecast_max_response_bytes` are `Settings` the
> *configured* forecaster enforces, so this model carries none of them and validates
> identically in every deployment.
>
> **Everything else §5 requires is the producer's**, not being decidable over this value's
> own fields: `confidence`'s figure, `derived_from_external`, `placement`, the
> transcription, the extent's agreement with the day the provider named, and `reported_by`'s
> **equality with this forecaster's own `name`**, which the outcome cannot check, holding no
> forecaster. That is `SearchOutcome`'s own division of labour — `_check_minted_by_a_search`
> enforces kind, source, evidence and the attestation instant and nothing else — and §13's
> arms test this list over the **production** forecaster.

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
> could not classify its own expiry. **The keyword takes ADR-0241 §1's form exactly** —
> `timeout: timedelta`, **required and with no default**, so there is no spelling for
> unbounded — and **a value that is not a `timedelta`, or is not strictly positive, is
> refused with `ValueError` before the call is revalidated, before any credential is read
> and before any channel is opened**. Zero and negative durations are refused and never
> read as instantly expired, which is that section's own disposal of them at a second
> seam.

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
> provider's answer covers**, in the order the provider returned them, of kind `SEMANTIC`.
> **Where more days survive the drop rule below than `forecast_max_days` (§11) admits, the
> records minted are the *first* that many in the order the provider returned them and the
> rest are not minted** — the cap is taken over the surviving days and taken from the
> front, because a cap that did not say which days it kept would let two implementations
> mint different evidence, and different goal outcomes, from one response.
> **No model is on that path**: nothing
> summarises, abridges, rewrites, re-ranks, annotates, deduplicates, interprets or
> classifies a value between the provider's response and the record.

> **Normative.** A record's `content` is a **transcription** of the fields the provider's
> documented format names for that day, in a fixed order, each rendered **as the
> provider's own response spelled it** — the octets of the value the response carried, and
> never a re-rendering of a parsed number. **The form is the provider's, and each
> implementation pins its own**: the field selection, their order, the separators and the
> omission rule are fixed by the implementation that reads that provider's documented
> format, and are pinned by a test of its own. **There is no cross-implementation form, and
> no implementation conforms by matching another's output** — a second provider's format
> names different fields, so a matching requirement would have nothing to match against.
> What this clause fixes is that the form is *fixed somewhere a test asserts*, and that
> nothing between the response and the record re-renders a value; **which fields those are
> is the implementing lane's, read off the provider §12 names**, and not a list this ADR
> states. This is ADR-0231 §10's transcription-not-rendering rule and ADR-0230 §5's
> decoding-not-rendering rule at a third producer, and neither is relaxed: **no word of
> this system's is added.**

> **Normative.** **A day the response does not describe completely is dropped whole**, and
> the remaining days are minted: a day for which the provider omitted a documented field,
> supplied it as `null`, or supplied a value of a type its documented format does not
> admit, and a day whose transcription exceeds `forecast_max_day_chars` measured as
> ADR-0230 §6 measures a fetched document. **A day the response names more than once is
> dropped in every one of its rows**, whether they agree or conflict: the response has not
> described that day once, and preferring one row over another would be this system
> deciding what the provider said. That is not a deduplication — nothing is merged, no row
> is preferred, and ADR-0226 §7's whole-union rule at the supply is untouched. **Where
> every day is dropped the read yields
> nothing** and the refusal is `NO_RESULT`, whose class §8's disposition carries. **A
> partial drop is reported nowhere**, which §7 states as a limit and §14 defers with what
> fires it.

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
> read as one, mints **no record**: the refusal is `UNATTESTED`, whose class §8's
> disposition carries into §7's audit. **No implementation reads an unparseable field as
> licence to fall back to a clock it read.**

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

**This is the producer ADR-0252 §3 says the corpus is missing, and names**: the window axis
applies *"on nothing else until decision 8's reader lands"*, the calendar having been the
hard case for the property a forecast has purely — *"its entries lie ahead of the read"*.

### 6. The egress: a configured provider, and the authority that reaches it

> **Normative.** The forecast integration is registered at the **designated** egress seam
> against the configured connection reference and one origin, in ADR-0231 §5's own shape:
> built at one site in `ai_assistant.tools`, pinned by the transport to that origin **as
> text, before parsing** (ADR-0154's condition 5), registered in **no** `ToolRegistry`,
> and reachable from nowhere else. ADR-0154 §2's clauses bind unchanged — designation
> approves no destination, no recipient, no account and no payload, and every send remains
> subject to ADR-0148's per-call machinery whole.

> **Normative.** **`read` performs ADR-0029 §2's three pre-execution checks itself, in
> that order, before the credential is read and before any channel is opened** — ADR-0231
> §6's clause at a second seam and in its own words, because this seam is likewise **not**
> `ToolInvoker.invoke` and inherits nothing written about `WEB_SEARCH`. (1) The `ToolCall`
> is **revalidated and detached**, so a mutation landed after construction cannot survive
> into the read. (2) The definition on that detached copy is compared for equality against
> **the forecaster's own registered declaration** — the authoritative original here,
> standing where ADR-0029 §2 puts the registry's, because this section gives the
> integration an egress registration and no registry entry — and an unequal one is refused.
> (3) `PermissionDecision.authorises` is **re-evaluated against that same detached copy**
> rather than trusted from construction. **Every subsequent step reads the revalidated copy
> and never the argument**; a failure at any of the three raises `ToolBindingError` and is
> **no outcome of the read**, carrying no `ForecastRefusal` and no disposition; and the
> order is part of the rule, for ADR-0029 §2's own stated reason. §4's construction-time
> validator *"catches the honest mistake at the point it is made"*; these are what hold
> against a deliberate one, and **a validly authorised call naming another declaration is
> exactly what (2) exists for**.

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

**Why the rule is stated over the request and not over the destination**, which is ADR-0247
§1's argument inherited whole: a fact about a *destination* is readable by every kind, so a
call of another kind bound to the forecast provider's set would inherit an authorisation the
owner gave about forecasts — and *"unreachable today"* is not an argument this corpus rests on.

**And why the third conjunct is a carried fact rather than `closed_loop`.** ADR-0247 §4
defines `closed_loop` as *"the request's kind is `WEB_SEARCH` and this deployment holds a
search registration"* — the conjunct saying *which act this is*, which *"cannot assert which
account and origin the binding carries"*. §11 therefore gives `CarriedProvenance` **one more
boolean in `closed_loop`'s own shape** rather than widening `closed_loop`, which would
rewrite every stored row and supersede a clause ADR-0247 §4 states as unchanged.

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
>
> **No count of dropped days is added to that record, and this ADR amends ADR-0226 §9 in no
> respect.** Such a count is a *within-ask* fidelity fact, and §9 refuses that class in
> terms: every count there *"is taken over a servicing that completed"* and is **zero** on
> one that failed, *"the partial case included"*, because *"a count of discarded records
> would report a yield on a turn §5 defines as having received none"* — the pair of failure
> fields being *"deliberately the whole of it"*. A drop count would thus have to be zeroed
> by a later ask's failure to obey §9, and non-zero to be worth having. **The honest
> consequence is that a response this system thinned is not distinguishable in the audit
> from one the provider gave thin**, which §14 defers rather than glosses.

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

> **Normative.** **Every member of both vocabularies that names a read the servicing
> reached maps onto exactly one member of `ReadOutcomeKind` — `NO_BUDGET` alone names one
> it did not, and produces no entry — and ADR-0251 §2's classifier is extended and not
> replaced.** Its seven
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
answers for what *it* did; the servicing answers for the stages the seam never sees — no
registration, no budget, no derivable binding, no `ALLOW`.

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
carries `supported` empty, fails §6's first test, and satisfies no condition"*, neither
minting clause declaring an extent. A forecast record declares one per day, so a goal whose
criterion is about Saturday meets a region that covers it and one that does not. **It still
does not establish whether the forecast is right**: an extent says where the reported entry
lies, never that the report is accurate.

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
>
> **Where a revising turn serviced more than one forecast read** (§2), the members are
> declared **in precedence order** and the field carries the **earliest-declared** member
> any servicing of the turn recorded — ADR-0242 §7's rule at this seam, unchanged. **A
> later read does not clear an earlier one's member**: a turn that was denied and then
> answered still reports `DECLINED`, because the user was told about a read this turn did
> not make and a second read does not unmake it.

> **Normative — the fold, stated totally over the twelve dispositions**, because a fold
> whose domain is not enumerated is a fold two implementations will disagree about:
> `NOT_CONFIGURED` → `NOT_CONFIGURED`; `RULING_CONFIRM` → `AUTHORISATION_AWAITED`;
> `SPEND_REFUSED` → `SPEND_EXHAUSTED`; `RULING_DENY` → `DECLINED`; `DEADLINE_EXPIRED` →
> `INTERRUPTED`; and `NO_BUDGET`, `BINDING_FAILED`, `RULING_UNAVAILABLE`,
> `TRANSPORT_FAILED`, `RESPONSE_TOO_LARGE`, `PROVIDER_REFUSED` and `UNATTESTED` →
> `UNAVAILABLE`. **It is non-injective and that is the point** (ADR-0242 §8): seven
> dispositions the user has no act for fold onto the one member that names none. **A
> contact and an `UNAVAILABLE` ride together where both hold** — a `RESPONSE_TOO_LARGE`
> an `UNATTESTED` or a `PROVIDER_REFUSED` reached the provider and yielded nothing usable —
> which is ADR-0264
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
> `RESPONSE_TOO_LARGE`, `UNATTESTED` or **`PROVIDER_REFUSED`**, each of which this system
> reaches only from octets the provider's channel had already returned. ADR-0264 §2 decides
> all three in one sentence — *"A contact is established the moment a response arrived, and
> nothing that happens to the enclosing servicing afterwards unmakes it"* — and every
> producer this ADR admits for `PROVIDER_REFUSED` is a **response the provider gave and this
> system refused**: a rate limit, a blocked origin, a body its documented format does not
> admit. The disposition carries no value saying which, and it does not need to: the contact
> question is answered by the arrival, not by the cause.
>
> **No credential-change producer is recorded here, and that is why this member is
> `REACHED` and not `INDETERMINATE`.** ADR-0148 §6's account-changed limbs *"discarded the
> credential and wrote nothing to any channel — none was opened"*, so that producer alone
> could have put a pre-send path under this member and forced the least-claiming direction;
> §12's provider is keyless and reads no credential at all, so no such path exists here.
> §14 defers it, and **the lane that adds a credentialed provider owes this partition its
> round**: a pre-send producer under this member would make `REACHED` wrong, and that lane
> either gives the path a disposition of its own or re-decides this clause.
>
> A call whose disposition is `NOT_CONFIGURED`, `NO_BUDGET`, `BINDING_FAILED`,
> `RULING_CONFIRM`, `RULING_DENY`, `RULING_UNAVAILABLE` or `SPEND_REFUSED` establishes
> **no** contact — every one of those is a stage before the send. A call whose disposition
> is `TRANSPORT_FAILED` or `DEADLINE_EXPIRED` establishes **nothing either way** and
> contributes `INDETERMINATE`, the least-claiming direction, because neither says whether
> octets arrived.
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
records, and the model is then free to say what the trail contradicts — the asymmetry #2268
recorded for search, arriving at a second seam and costing one enumeration to prevent.

### 11. `Settings`, persistence, and the versions that move

> **Normative.** `Settings` gains nine fields, **in `web_search_*`'s own shape field for
> field**, so that an operator configuring the second provider configures the same shape
> twice: `forecast_connection: str | None` and `forecast_origin: str | None`, **set
> together or neither**; `forecast_latitude: float | None` and `forecast_longitude: float
> | None`, **all four set together or all four unset** — a connection and an origin
> without a coordinate would start a deployment whose `request` must answer a proposal it
> has no place to build, so the four are one pair of pairs and the load-time refusal
> covers every half-set combination of them; `forecast_cost_per_call:
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

> **Normative.** **`forecast_max_response_bytes` is the most octets one response may take
> off the channel — its status line and headers included — enforced *on the read itself*
> and before any part of it is parsed.** That population is `search_max_response_bytes`'
> word for word, so the two bounds mean the same thing at two seams. A response **at** the
> bound is read and minted; a response **beyond** it is **abandoned and refused**, never
> truncated, and the read is `RESPONSE_TOO_LARGE` — the outcome
> `ForecastRefusal.RESPONSE_TOO_LARGE` and `ForecastDisposition.RESPONSE_TOO_LARGE` name.
> **No implementation buffers a whole response and measures it afterwards**, which would
> let a provider buy memory from a client that has already opened a channel; at most one
> octet past the bound is read, to detect that it was passed. This is stated because a
> refusal member with no defined trigger is a member no implementation can reach correctly.

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

> **Normative.** **L3 — the servicing, in `orchestration/` plus the composition root**:
> §7's servicing site and its two audit fields, §8's `ForecastDisposition` and its
> classifier entries, §9's evidence composition, and §10's fold and contact carrier. **It
> also takes `app/composition.py`'s injection of the forecaster into that site**, which is
> the one file outside `orchestration/` this lane touches and is L2's own allowance for
> the same reason: golden rule 1 makes the engine receive implementations by injection and
> `app/` is the only place a concrete is wired, so the call site and its wiring cannot land
> in different lanes. **L1 builds the forecaster and registers its `close`** (§4); L3 hands
> it to the servicing it creates.

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

> **Normative.** Each arm is a test the owning lane owes, **deterministic, offline and in
> the ordinary gate**. **The subject is the production type or component, and the rule is
> stated per assertion rather than per arm**: every assertion below is owed over the
> production subject unless the arm names the canonical fake for it, and **exactly one
> assertion does — (c)'s `request` limb**, admitted there because §4 lets a `request` answer
> from held configuration with no await, so the contract does not oblige that member to
> suspend and a production arm would be asserting a suspension point no implementation owes.
> **No other assertion stands over a fake**, and no lane reads this one allowance more
> widely. **They are grouped below by owning lane, and the grouping carries no obligation of
> its own**: every lettered arm is owed separately and in full, and a lane discharges the
> arms under its own heading.

> **Normative.** **The enumeration below is a floor and not a ceiling**, on ADR-0219 §7's
> ground and in its words, as ADR-0264 §13 already takes it. **Every normative clause of
> this decision that an implementation can fail is owed an arm**; what is named below are
> *"the ones whose absence would otherwise be non-obvious, each with the failure it exists
> to catch"*, written that way deliberately, because *"a conformance list read as
> exhaustive is ADR-0108 §4's 'false-shelter shape' at one more remove, this time in the
> suite rather than in the contract"*. So **a lane adds the arm a normative clause needs
> whether or not that clause is listed here**, and no implementation is conformant on the
> ground that a rule it breaches has no arm below. **This is also what the count of fifteen
> does and does not bound**: it bounds what this ADR names, never what a lane owes.

> **Normative — L1: the contract, what it mints, and the model.**
>
> - **(a) The empty ask.** A `ReadAsk` of this kind carrying a `query`, carrying `labels`,
>   carrying an `entry` and carrying a `structure` is refused, each with its own message;
>   one carrying none of the four constructs.
> - **(b) The declarations the source owes, and the fallbacks that are not taken.** A
>   response whose day the provider names with a declared offset mints a record whose
>   `Attestation.extent` is that day's own half-open interval and whose
>   `MemoryBase.validity` is fully open; a response naming a day without declaring an
>   offset mints **no record for that day**; a response one of whose days omits a
>   documented field, supplies it as `null`, or supplies a type its format does not admit
>   mints its **siblings only**; a response naming one day in **two** rows mints no record
>   for that day and mints its siblings, asserted over agreeing rows and conflicting ones
>   alike **and with the second occurrence placed beyond `forecast_max_days`**, because an
>   implementation capping before it looks for duplicates mints the first row and passes
>   every arm that keeps the duplicate inside the cap; a response every day of which is so dropped mints nothing
>   and yields `NO_RESULT`; and a response declaring no instant, and one carrying an
>   unreadable value in that position, each mint **no record** and yield `UNATTESTED`. In
>   none of them does any minted value equal a clock the test controls.
> - **(b′) The refusals at the boundaries.** A `ForecastOutcome` carrying a record that is
>   not `SEMANTIC`, one whose `Provenance` is not `EXTERNAL`, one carrying non-empty
>   `evidence`, one carrying a `topics` or an `about_person`, one whose `validity` is not
>   fully open, one carrying no `extent`, one whose `reported_by` differs from its
>   siblings', and one whose attestation instant differs from the outcome's `reported_at`,
>   is **refused at construction** in each case; a `Settings` naming a non-finite or
>   out-of-range coordinate, a `forecast_max_days` outside `1..3`, a non-positive
>   `forecast_max_day_chars` or `forecast_max_response_bytes`, **or any half-set pair** —
>   connection without origin or the reverse, one coordinate without the other, one cost
>   field without the other, coordinates or costs with no provider pair, **and a connection
>   and origin with both coordinates unset** — **does not start**; and a **response** of
>   exactly `forecast_max_response_bytes`, its status line and headers included, is read
>   and minted where one of that figure plus one is abandoned **while reading**, yielding
>   `RESPONSE_TOO_LARGE` with no parse attempted; a day whose transcription is exactly
>   `forecast_max_day_chars` is minted where one of that figure plus one is dropped; and a
>   provider answer of fewer than, of exactly, and of more than `forecast_max_days` days
>   mints that many, that many, and exactly `forecast_max_days`, **the last asserted over
>   which days those are and over their extents rather than over the count alone** — taking
>   the first and taking the last both satisfy a count while minting different evidence —
>   and a response whose days exceed the figure only once an incomplete one has been
>   dropped mints the **first** `forecast_max_days` of what survived. And over the
>   **production** forecaster's own output, a minted record's `confidence` is `0.9`, its
>   `derived_from_external` is `False`, its `placement` is the default that narrows
>   nothing, and its `Attestation.reported_by` **equals that forecaster's own `name`** —
>   asserted against the configured instance's `name` and not merely against its siblings',
>   which §4's model already enforces and which a vendor string stamped consistently would
>   satisfy. These are the §5 facts that are the producer's rather than
>   `ForecastOutcome`'s, in `SearchOutcome`'s own division of labour.
> - **(c) The cancellation that stays an exception, the deadline's own shape, and the three
>   checks before the channel.**
>   **`read`**, cancelled from outside while suspended, re-raises `CancelledError` over the
>   **production** forecaster: it yields no `ForecastOutcome`, no `ForecastRefusal`, and in
>   particular no `DEADLINE_EXPIRED`, which is `read`'s **own** expiry and never an outer
>   one (ADR-0241 §4). **`request` is asserted over the canonical fake**, under the
>   preamble's one allowance and only where an implementation suspends in it —
>   `WebSearcher`'s own shape, which tests cancellation on the suspendable member and
>   models the rest on its fake. And `read`'s `timeout` is **required with no default**, so
>   omitting it is a `TypeError`; a value that is not a `timedelta`, a zero and a negative
>   each raise `ValueError` **before** the call is revalidated, before any
>   credential is read and before any channel is opened, asserted over those three
>   orderings so that zero cannot pass as an instant expiry. **And §6's three
>   pre-execution checks are asserted over the production forecaster**, each refusing with
>   `ToolBindingError` before any credential is read and any channel is opened: a
>   `ToolCall` mutated through `__dict__` after construction; one whose definition is not
>   the forecaster's own registered declaration, **which `authorises` would otherwise pass**;
>   and one whose decision does not authorise the detached copy. An implementation trusting
>   the validator that ran at construction fails all three, and one that runs them after
>   opening the channel fails the ordering they are asserted in.
> - **(i) The deadline that actually expires, and the one request §3 allows.** A production
>   forecaster whose exchange is suspended past a **positive** `timeout` **returns**
>   `DEADLINE_EXPIRED`, raises no `CancelledError` outward, opens no second channel, and
>   does not report `TRANSPORT_FAILED`. This is the case that separates a seam enforcing its
>   own deadline from one that merely accepts the keyword, and (c) does not reach it: (c)
>   asserts what an invalid timeout refuses, this asserts what a valid one does. **And §3's
>   *one ask is one read* is asserted over every terminal outcome that could invite a
>   retry**, **enumerated exhaustively over `ForecastRefusal`** rather than over a chosen
>   few — `NO_RESULT`, `UNATTESTED`, `RESPONSE_TOO_LARGE`, `PROVIDER_REFUSED`,
>   `TRANSPORT_FAILED` and `DEADLINE_EXPIRED` — each issuing **exactly one** provider
>   request and opening **exactly one** channel before returning. A member added without
>   this assertion fails the arm, as it does in (k). Without it an implementation may
>   retry after any of them, return the same outcome from the second exchange, and satisfy
>   every disposition, contact and statement arm while contacting the provider twice
>   against a clause §3 states absolutely.
> - **(j) The outcome's exactly-one rule, and the instant that rides with it.** A
>   `ForecastOutcome` carrying **both** a non-empty `records` and a non-`None` `refusal`,
>   and one carrying **neither**, is refused at construction; so is one carrying records
>   with no `reported_at`, and one carrying a refusal **with** a `reported_at`. The
>   *neither* case is asserted in its own right, because an outcome accepted while empty
>   and unrefused is one a servicing can read as an answered read — and would then report a
>   provider the turn never reached.

> **Normative — L2: the authority.**
>
> - **(d) The mismatched binding, over each of §6's three conjuncts.** A forecast request
>   whose account or origin is not the configured pair; a request of another kind bound to
>   the configured forecast pair; and **a forecast request whose kind, account and origin
>   all match and whose `forecast_reach` is `False`** — each takes **no** route (c), both
>   `_only_the_disclosure_floor` limbs bind in full and the ruling is what it is today.
>   The third is asserted in its own right because `forecast_reach` is §6's **first**
>   conjunct and a policy reading only the kind and the pair passes the other two shapes
>   while granting route (c) where §6 refuses it; **it is also the value a composition site
>   that never computed the fact leaves behind**, which is what §11 makes `False` the
>   restrictive default for.
> - **(e) No new question.** A turn on a goal whose supply already carries an external
>   record asks for a forecast at the configured provider and is ruled `ALLOW` with **no**
>   `CONFIRM`, **no** grant seam read and `authorised_subject` unset — and the same turn's
>   search at an unconfigured destination is unaffected.

> **Normative — L3: the servicing.**
>
> - **(f) The budget and the order.** A servicing whose file and search have taken nine
>   slots admits **one** forecast record and records the kind as truncated; one reached
>   with no slots left composes no request, opens no channel, and yields **no outcome
>   entry** for the ask; and a servicing carrying an ask of **all six** kinds services them
>   in §7's stated order, asserted over the whole sequence and not only over the kinds
>   ahead of the forecast, so that no later kind can take the slot this one was reached
>   with.
> - **(g) The evidence row.** A forecast servicing on a goal turn writes a row whose
>   `requested` is absent, whose `records` is empty, and whose `supported` carries one
>   region per record **the ask returned** — §9's population, not the admitted one —
>   applying **only** a window equal to that record's extent. **A servicing returning three
>   records of which the budget admits one still writes three regions**, asserted as its
>   own case, because ADR-0252 §2 composes `supported` from what the read returned and (b′)
>   already refuses a record with no extent at construction, so no forecast servicing can
>   present one.
> - **(h) The statement and the contact.** A read the provider answered carries
>   `forecast_not_read` `None` and an outbound statement naming `FORECAST_PROVIDER`; a read
>   refused before the send carries the folded member, its fixed statement and **no**
>   destination class; a transport failure and a deadline expiry each carry
>   `INDETERMINATE` with `destinations` empty, asserted separately so that neither can
>   regress to `REACHED` or `NOT_REACHED` while the other holds; a **revising** turn whose
>   two forecast servicings recorded `RULING_DENY` and `TRANSPORT_FAILED` reports
>   `DECLINED` in **both** encounter orders, and one whose denied read is followed by an
>   answered read still reports `DECLINED` and its statement rather than `None`; and
>   **`RESPONSE_TOO_LARGE`, `UNATTESTED` and `PROVIDER_REFUSED` each carry `UNAVAILABLE`
>   with `FORECAST_PROVIDER` `REACHED`**, asserted separately too, because §10 classes all
>   three as reached from octets this system took off the channel and any of them folded to
>   `INDETERMINATE` would deny a contact the trail recorded.
> - **(k) The classifier and the fold, each total over its own domain.** Every member of
>   `ForecastRefusal`, and every member of `ForecastDisposition` **§8 maps**, is asserted
>   against the `ReadOutcomeKind` member §8 gives it, **enumerated exhaustively over both
>   types** so that a member added without a mapping fails the arm rather than passing
>   silently. **`ForecastDisposition.NO_BUDGET` is §8's one stated exception and is asserted
>   as itself** — it names a read the servicing did not reach, so the arm asserts **no
>   outcome entry at all** for it and asserts no `ReadOutcomeKind`, an assertion demanding
>   one being unsatisfiable against §8 as written. And `TRUNCATED` displaces `EMPTY`,
>   `DUPLICATE` and `RETURNED_RECORDS` where ADR-0226 §6's budget cut this kind's yield.
>   **§10's fold is walked the same way, over all twelve dispositions**, each asserted
>   against the `ForecastNotRead` member §10 declares for it and the seven that fold onto
>   `UNAVAILABLE` named individually, so that an omitted member cannot pass as a default;
>   §10's precedence over a revising turn's two servicings is (h)'s and is not repeated
>   here. A fold stated totally and tested selectively is one an implementation can leave
>   partial while passing every other arm.
> - **(l) Two seams, one statement.** A turn that reached the configured **search**
>   provider and the configured **forecast** provider carries **one** outbound statement
>   naming **both** destination classes, in §10's stated order, neither displacing the
>   other — because an implementation overwriting `SEARCH_PROVIDER` with
>   `FORECAST_PROVIDER` would deny a contact the trail recorded, which is the asymmetry
>   §10 exists to close.
> - **(m) The carried external-content fact.** A turn whose pre-servicing supply carries
>   **no** external record, and whose web search then contributes one, builds a forecast
>   binding carrying `planned_with_external_content` **`True`** — asserted over the binding
>   itself, because §7 computes it over the pre-servicing supply **and** over every record
>   this servicing has already contributed, and an implementation inspecting only the first
>   passes every other arm while writing `False`.
> - **(n) The contact that outlives the servicing.** A servicing whose forecast read was
>   **answered** and whose **later** read of another kind then raises carries
>   `FORECAST_PROVIDER` `REACHED` with `records` `0` and `forecast_not_read` `None` —
>   ADR-0226 §5 discarded the servicing's records, and §10's quoted clause, *"nothing that
>   happens to the enclosing servicing afterwards unmakes it"*, is what survives them. The
>   same servicing having recorded `UNATTESTED` **before** that later failure carries the
>   contact **and** `UNAVAILABLE`; and one that raised **before** the forecast was
>   serviced, having opened no channel, carries **no** contact and `None`. An
>   implementation computing the fact off the ended servicing rather than at the performing
>   site passes every other arm here and fails all three, which is why §10 fixes the site
>   and forbids any other to recompute it — ADR-0264 §13's own arm 7 arriving at a second
>   seam.

### 14. Deferred, by name, each with what fires it

> **Normative.** This decision settles nothing about the following, and no lane cites it
> toward any of them. Each is named so that a reader cannot mistake this ADR's silence for
> a ruling.

- **A place listing, and a forecast for a place the turn named.** §3 fixes one configured
  place, so this rung answers for the deployment's own place and not for the campsite; the
  **next rung is an ask carrying a place the user named in their own words, resolved at the
  configured provider** (**#2388**). Fired by a type carrying a recorded coordinate — a
  location belief, or the booking integration's answer — at which point the ask gains a
  **label into a listing the loop showed**, in ADR-0230 §2's address-space shape, never a
  coordinate the planner wrote.
- **Per-day drop visibility in the audit.** §7 carries the refusal classes and no count,
  so a response this system thinned reads like one the provider gave thin (**#2391**).
  Fired by ADR-0226 §12's deferred **durable** audit surface, where a within-ask fidelity
  field does not have to obey §9's zero-on-failure rule — never by adding a count to §9's
  per-turn record, which would need its own ADR amending a clause stated against it.
- **Geocoding.** Turning a place name into a coordinate is a second destination and a
  second registration. Fired by the lane that needs the bullet above.
- **The credential-change producer of `PROVIDER_REFUSED`.** §10 records that member for a
  response the provider gave and this system refused, and for nothing else, because §12's
  provider is keyless and an arm over a production component cannot reach a path no
  production component has. Fired by the **first credentialed forecast provider**, whose
  lane adds the producer to §10's partition and its arm to §13(h). The member itself is
  **not** deferred and needs no widening: it is reachable today.
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

**The six records are declared here, each with ADR-0070 §1's test applied to the earlier
ADR's text — what ADR-0082 §1 asks of an author.**

> **Normative.** **The six header edits ride in this PR, while this ADR is `Proposed`, and
> are not held back for the ratification commit.** ADR-0082 §7 states the condition in
> terms, and names the contrary reading as a recurring reviewer failure rather than a
> governance gap: *"§1's condition is that the superseding ADR **exists**, not that it is
> ratified — the hazard §1 names is a `Status` line pointing at nothing, and an atomic pair
> makes that unreachable."* The pair is atomic here — the six records and the ADR they name
> land in one merge — so no reader ever meets a qualifier resolving to nothing. **They are
> not deferred to an implementing lane either**: a record is decision bookkeeping and
> travels with the decision. The ratification commit therefore flips one `Status` line and
> changes no other byte, which is ADR-0165 §2's exempt shape.

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
  five members and *"The citation hop is serviced first"* as naming the first serviced read;
  §1 provides for the first, and the third to fifth members each amended both in turn.
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

**The second thing this section states is the clauses a reader would expect to have moved,
and which did not.** **ADR-0093 §10** — `Reader.read()` still takes no arguments, its reason
**honoured** by §3 rather than worked around. **ADR-0092 §3** — unamended; §5 takes the
declared instant with no substitute, and ADR-0230 §5's local-substitute scope expressly does
not reach a remote source's earlier answer. **ADR-0208 §1** — honoured by §1; this kind is no
relevance selection over the store. **ADR-0252 §3** — its `requested` enumeration is scoped
to *"the vocabulary ADR-0226 §2, ADR-0230 §1, ADR-0231 §1 and ADR-0240 §1 leave closed"*, so
a sixth member is outside it and §9 is a **stacked addition** owing no record (ADR-0082 §1).
**ADR-0117 §2, ADR-0185, ADR-0097, ADR-0132, ADR-0133** — used as given or untouched; §4
contracts no grant seam, for ADR-0230 §11's reason.

### 16. Marking, review and ratification

This ADR is **marked** under ADR-0089: every clause a reader could disobey is a
`**Normative.**` block quote, and unmarked text is read to determine what a marked clause
*means*, supplying no obligation of its own (§3). ADR-0257's labelled form is available and
unused, and marking is forward-only (§5).

**The required review set is adversarial *and* architecture**, for ADR-0015 §1's reason:
this decides `core/protocols.py` surface and a package boundary, prose-only though the PR
is. It is **reviewed while `Proposed`** and ratified only after, and **no lane implements
against any clause until this ADR is merged** (golden rule 5, ADR-0015 §5).

## Consequences

**What becomes easier.** A turn can ask the world a structured question whose answer is
records rather than prose, and ADR-0252's evidence machinery acquires its first producer
that can make a `supported` window mean something.

**What becomes harder, stated rather than glossed.** There are now **two** carried facts
about being at a configured provider where there was one, and §14 books the fold rather
than pretending the drift is not there. The egress relaxations reach two kinds, a wider
surface for a later ADR to widen again — §6's last clause and ADR-0247 §9's bar hold that
line, both over the *request*. And a forecast draws up to three of §6's ten slots.

**What would trigger revisiting this.** A measurement that the three-day cap is wrong; a
place listing from the booking side, firing §14's first bullet; a third configured-provider
kind, firing the fold; or a provider declaring no instant, which §5 makes unusable.

## Alternatives considered

**A `Reader` over a configured forecast source, read on its own cadence and ingested.**
#2255's own wording, and the alternative a reader will most want. Refused because the two
consumers it would have are the wrong two: ADR-0095's `Reader` feeds the
situational-context facet and the ingestion stage, both *cadences*, and ADR-0096 §3 and
ADR-0252 §3 between them forbid a facet from serving a carried-over reading or producing an
evidence row. ADR-0093 §10 also gives `read()` no arguments *by decision*, and ADR-0230 §4
already ruled *"Reusing `Reader` was never available … an argument is exactly what this
contract needs"* for this shape. Accepting it would have cost a scheduled ingester writing
durable weather beliefs about the owner, which ADR-0230 §11 makes a **stop**.

**An ask carrying a planner-composed `TimeWindow`.** It would give ADR-0252 §3's
`requested` a typed part and let a planner ask about a specific weekend. Refused because a
window the planner composed is model output reaching an egress payload, and what it buys is
small — the provider's horizon already covers the days a planner would name — against the
property ADR-0231 §1 calls a kind's *whole safety mechanism*. §14's place-listing deferral
is the shape an argument returns in: a **label into a listing the loop showed**.

**A registered tool at the egress seam, invoked through `ToolInvoker`.** Refused by two
rulings §1 satisfies by not being a tool: ADR-0170 §5a, *"a tool's result is a JSON payload
with no per-span provenance"*, and ADR-0208 §1, *"A component on the turn path that wants
records the supply does not hold does not obtain them by invoking a tool"*.
