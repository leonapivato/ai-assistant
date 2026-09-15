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
  **§2's membership sentence**, in that one respect: the enumeration gains a **sixth**
  member (§2 below). This is the licence §1 of that ADR grants in terms — *"A later kind
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
  **§5's closure at one member**, in that one respect: `OutboundDestination` gains a
  second member. §5 is the clause that requires this — *"A later outbound seam adds its
  own member with its own ADR. It does not render as `SEARCH_PROVIDER` and does not
  render as nothing"* — so this is that ADR rather than a departure from it. §5's
  class-never-a-destination rule, §1's three-valued statement, §2's establishment
  partition, §3's egress prohibition and §4's carrier all bind entire.
- **Decides new `core` surface — a BREAKING contract change (golden rule 5).** One
  Protocol, one `ReadKind` member, three models, two enumerations, one member on a third
  and one field on a fourth. Nothing implements against any of it until this ADR is
  merged, and the Protocol ships as a triad — contract, shared conformance suite,
  canonical fake — in its own later lane (ADR-0015 §5, `CONTRIBUTING.md` → "Adding a
  Protocol"). §11 cuts the lanes.
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

and the design report's Q3, which names what such a reader buys and what it must not
cost:

> **C-INFO — real-world information through dedicated readers and structured
> integrations.** A weather `Reader` (ADR-0095) and a booking integration declared at the
> `tools/` egress seam (ADR-0154, ADR-0016/0018). It demonstrates investigation,
> dependent execution, uncertain outcomes and verification **without any new
> destination-trust decision**, because a configured reader and a registered integration
> are already-governed shapes.

**This ADR is the forecast half and nothing else.** The booking integration is a `tools/`
integration at ADR-0154's seam and is its own decision; §13 names it among what is not
decided here.

The owner's ruling of 2026-09-14 fixes the reference provider: **Open-Meteo**, free and
keyless, configured on the hub the way the search provider is. This ADR names no vendor
in any normative clause — §6's authority is stated over *the configured provider*, which
is what makes it a rule rather than a registration — and §11 records that the
implementing lane delivers the real provider, with what would make it deliver a mock
behind the same contract instead.

### The tree, read rather than assumed, at `origin/main` `8dbfddf0`

- **`ReadKind` has five members** — `SIGHTED_QUERY`, `CITATION_HOP`, `LOCAL_FILE`,
  `WEB_SEARCH`, `STRUCTURED_READ` — and its docstring records that the third to fifth are
  additive entries under ADR-0226 §1's own licence. `ReadAsk` has one field per kind's
  argument and a validator with five arms, `WEB_SEARCH`'s being the arm that refuses all
  four arguments.
- **`Reader.read()` takes no arguments**, and `Fetcher`'s docstring records why that is
  not a seam a turn-time read can borrow (below).
- **The egress boundaries are three**, and ADR-0124 §1 is the live rule that replaced
  ADR-0017 §1's enumeration: `models/`, the designated `tools/` seam
  (`ai_assistant.tools.egress`, designated by ADR-0154 §1) and the hub's remote transport
  in both halves. *"Every other egress is a bug."*
- **`tools/web_search.py` is the worked shape** for a configured HTTPS provider at that
  seam: a declaration, a provider adapter and a searcher, driving the `HttpsExchange` the
  seam holds, reaching no transport of its own, and bound by the `network transports are
  confined to the tools egress seam` import contract.
- **`readers/calendar.py` is the only site in the tree that constructs a
  `ReportedExtent`.** ADR-0252 §3 says so as a dated observation and names the
  consequence: the evidence window axis *"is applied on rows over store-resident records
  that came from a calendar reading, and on nothing else until decision 8's reader
  lands"*.
- **`PROTOCOL_VERSION` is 43**, and several lanes in flight also move it; §10 states the
  obligation without fixing the figure.

### What the corpus already decides, and is used here as given

- **ADR-0226 §1** closes the read-request enumeration and fixes how it grows: an ADR
  admitting a kind *"adds a member and states that kind's namer, its servicing, its share
  of §6's budget and its audit fields; it does not introduce a second request object, a
  second servicing site, a second budget or a second audit."* §2 and §7 below are that
  statement.
- **ADR-0226 §3's namer invariant.** *"The namer may be data, or the user, or the model
  pointing outward — never the model pointing inward."* §3 below is this seam's answer.
- **ADR-0226 §1's record-not-payload rule.** What a serviced request returns is
  *"`MemoryRecord`s carrying their own `Provenance`, and never a payload, a rendering, a
  summary or free text of any kind."*
- **ADR-0230 §5 and ADR-0231 §10** are the two minting precedents, and §5 below follows
  the second where the two differ, because a forecast provider is a remote source
  answering a live interrogation.
- **ADR-0117 §2's extent, and §8's general rule.** *"Where a source's entries have a
  position in that source's world, that position is producer testimony and is carried by
  the extent (§2); it is never carried by the record's envelope validity window."* §8 goes
  on to name the property that made the calendar the hard case — it is
  **forward-looking** — which is a forecast's defining property too.
- **ADR-0252 §15** names exactly what an evidence row needs from this decision and
  declines to design the rest: the reader's declared identity, an
  `Attestation.reported_at` for `as_of`, and *"for `supported`, a `ReportedExtent`
  (ADR-0117 §2) … the only authority this decision will accept for what a reader
  covered"*, while *"how a reader's read is asked for, serviced, budgeted or audited is
  that lane's"*.
- **ADR-0264 §5** requires a second outbound seam to add its own `OutboundDestination`
  member, and §9 below does.
- **ADR-0251 §4** governs whether a further round fires, over facts that are not about
  the kind. Nothing here changes it and §7 says so.

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
*"one **attempt** by a driver to read one source"*, and §2 makes it an audit row that
*"carries **no source content**, no entry, no path and no configured location"*. It has no
`Provenance`, no `Validity` and no `Attestation` to carry; `produced` is a count. What a
serviced read returns into the supply is `MemoryRecord`s (ADR-0226 §1), and §5 below is
where their provenance is fixed. ADR-0230 §11 settles the neighbouring question the same
way for the fetch seam — it *"contracts no `SourceGrants` into the `Fetcher` seam"* — and
§4 below inherits that reasoning rather than re-arguing it.

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
the configured forecast provider. §13 names each of those with what fires it.

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

**Named for its product role, as every Protocol in that module is.** `Planner`,
`Observer`, `Reader`, `Fetcher`, `WebSearcher`: the role here is *asking a configured
outside source what it currently says about the days ahead*, so the seam is a
**`Forecaster`** and §4 fixes its three members.

**The difference from `Reader` is the one ADR-0230 §4 already named, and it is not about
the weather.** A `Reader` is bound by its own configuration and takes no address, so a
caller cannot widen its read; a turn-time read is asked for by the turn and must
therefore be a contract that can be *asked*. This seam takes the smallest possible ask —
§3 makes it none at all — which honours ADR-0093 §10's reason rather than working around
it: there is nothing for a caller to widen, and the bound stays the source's own
configuration exactly as that clause requires.

**And the difference from a `ContextProvider` is the cadence.** ADR-0096 §3 rules that
*"A facet is built from a reading taken during the assembly that returns it. No facet is
served from a cached, carried-over or previously assembled reading"*, and ADR-0252 §3
rules that no facet produces an evidence row. A forecast that reached a goal's evidence
through a facet would be exactly the carried-over reading those clauses refuse, read back
on a later turn as though it were current.
