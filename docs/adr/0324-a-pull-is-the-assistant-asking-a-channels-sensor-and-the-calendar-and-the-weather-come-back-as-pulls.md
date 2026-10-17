# 324. A pull is the assistant asking a channel's sensor, and the calendar and the weather come back as pulls

- Status: Proposed
- Date: 2026-10-17
- Scope: batch [#3113](https://github.com/leonapivato/ai-assistant/issues/3113), lane L2, and [#2890](https://github.com/leonapivato/ai-assistant/issues/2890): the rule for a pull, and the calendar and weather channels declared whole, with only their pulls built. It answers [#2593](https://github.com/leonapivato/ai-assistant/issues/2593)'s "which read capabilities survive" for these two capabilities alone, and decides the coverage half of [#2685](https://github.com/leonapivato/ai-assistant/issues/2685).
- Dependency: the phases as ADR-0306 to ADR-0309 decide them, the grant uses as ADR-0318 leaves them, and the forecast seam as ADR-0260 leaves it, all Accepted and on `main` at `abf4e206`.
- Authorization: the owner's rulings of 2026-10-17, given in the walk-through of batch #3113 (lane L2): both the calendar and the forecast come back as pulls, each kind is declared whole and only its pull is built, a pull takes no arguments, and a late answer is dropped. The dispatcher assigned 0324 and left the grant use and the coverage half to this decision.
- **Changes `core`, so it is a contract-surface decision.** `GrantScope` gains one member, `PULL` (§6). No Protocol changes and no type is added. `GrantScope` crosses the wire, so `PROTOCOL_VERSION` advances (§10).
- **Partially supersedes**, each in the scope §11 states:
  [ADR-0260](0260-a-forecast-read-is-its-own-seam-at-a-configured-provider-and-what-it-mints-carries-the-extent-that-makes-it-evidence.md) (§1:4's closing of the route to planning, for the phases);
  [ADR-0133](0133-a-producers-read-is-a-third-use-of-a-source-and-the-user-grants-it-separately.md) (§2:3's subset, in the addition alone);
  [ADR-0177](0177-the-browsers-control-surface-is-thirty-operations-and-a-credential-is-entered-only-on-a-loopback-origin.md) (§6:2's members, in the addition alone);
  [ADR-0294](0294-readers-no-longer-ingest-into-memory-and-what-they-wrote-stays.md) (§4:3's and §4:6's subsets, in the addition alone);
  [ADR-0318](0318-the-old-paths-vocabulary-leaves-the-episode-record-the-decision-row-and-the-grant-uses.md) (§6:2's *`NOTIFY` alone*, in the addition alone).

## Context

**What the cutover dropped.** The old path handed every turn a calendar facet and could
service a forecast read. Both went with it. The phases offer planning neither:
`_build_phase_path` in `app/composition.py` says "The forecast read is kept out of every
registry (ADR-0260 §1), so it is not offered", and `orchestration/phase_path.py`'s module
docstring says "**Left to later lanes:** pulls (ADR-0292 §13:3), which nothing builds
yet." #2890 records the gap. ADR-0307 §6:6 already lets planning look up pulls, and
ADR-0306 §3:4 already says how a pull's result is declared; nothing builds one.

**What is built, at `abf4e206`.**

- The web search is offered to planning beside the registry's capabilities, its declaration
  read from its searcher's own proposal (`PhaseTools.search_declaration`), and declared in
  `tools/web_search.py` with effect none, leaving the hub, a result that may carry outside
  text, an outcome that can be unknown, and safe to repeat. It takes a query.
- The forecast seam stands whole: `Forecaster` (ADR-0260 §4:1), whose `request` takes no
  arguments and proposes the call with the configured origin and coordinate; the
  declaration `FORECAST_READ` in `tools/forecast.py`, with the same five properties as the
  search's and no argument planning could write; the configured-provider route in
  `ThresholdActionPolicy` and `registered_forecast` in authorizing. The provider is a
  reference provider that "accepts a credential and does not use it" (`tools/forecast.py`'s
  module docstring), because a keyless connection is #2396's.
- The calendar reader, `CalendarReader`, reads the synced local `.ics` within its configured
  bound and returns one `SourceReading`, which may declare the `ReadCoverage` it exhausted.
  `Reader.read` "takes no arguments, and that is a decision (ADR-0093 §10)". Its one consumer
  is the upcoming-event producer, gated on a `NOTIFY` grant (ADR-0319 §7:1).
- `GrantScope` holds `INGEST` and `NOTIFY`. A new grant names `NOTIFY` alone (ADR-0318
  §6:2), and `FACET`, the use the request path's facet read under, left because nothing was
  gated on it.

**The model this applies.** ADR-0292 §6:3 defines a pull as "the assistant asking and the
far side answering within that request: a forecast, a calendar lookup, earlier messages in a
conversation", and §6:5 has each kind declare whether it can be pulled and whether it
pushes. ADR-0292's own Context table puts the reader as "an in-hub sensor on its channel",
and §13:3 rules that a reader's context facet becomes a pull. ADR-0094 §1's prose says
"Pull has no instance today" of a spoke's pull across the process boundary, and §2 that the
current protocol cannot carry one.

**The owner's rulings, 2026-10-17.** Each clause below that records a ruling states it as
ruled. The clauses that settle what the rulings leave open are listed as such in the pull
request.

## Decision

We will define a pull as the assistant asking one of a channel's sensors within the
request, reached by planning as a capability whose answer it sees only through a digest;
declare the calendar and the weather as kinds whole and build only their pulls; gate the
calendar's on a new grant use; keep the reading's coverage for the calendar pull to state;
and drop any answer a pull would give past its deadline.

### 1. Status and delivery

> **Normative.** This document remains `Proposed` until the reviews `CONTRIBUTING.md` →
> "Finishing an ADR PR" requires have returned green on one tree.

> **Normative.** No lane implements this decision until it has merged `Accepted`.

### 2. A pull

> **Normative.** A pull is ADR-0292 §6:3's: the assistant asking one of a channel's sensors,
> and the far side answering within that request. The rule holds wherever the sensor runs,
> in the hub or on a device.

> **Normative.** Planning reaches a pull as a capability it may call (ADR-0307 §6:6),
> declared with ADR-0306 §2:1's five properties: its effect is none, its result may carry
> outside text, and it is safe to repeat. Whether it leaves the hub and whether its outcome
> can be unknown are its declaration's, under ADR-0306 §2:4–§2:6.

> **Normative.** A pull's answer reaches planning only as a digest's evidence (ADR-0306
> §5:14–§5:15, ADR-0308 §4), and planning is never given it raw.

> **Normative.** A pull's answer carries its channel and its author, stated by the hub and
> never by its content (ADR-0292 §5:1, §5:8), and its digest is given them as the hub's
> attribution of the outside content it reads.

> **Normative.** A pull's answer informs the activation that asked and authorizes nothing
> (ADR-0292 §5:5).

> **Normative.** Only pulls of a sensor in the hub are built under this decision. A pull of
> a sensor on a device is served over a connection the device established (ADR-0094 §2:1);
> how it rides that connection is the device session's to decide, and no lane builds one
> before that decision.

The web search is the first pull built (ADR-0309 §4:2), and its declaration already has
§2:2's shape. This decision declares no kind for its channel, and its query argument is the
search's own (§3:3).

### 3. A pull's arguments

> **Normative.** Neither pull this decision declares takes an argument planning writes,
> beyond the *looking for* the hub adds (ADR-0306 §2:9). Each returns its sensor's own
> bounded reading, and its digest answers the *looking for* (ADR-0308 §4:3).

> **Normative.** No pull widens, narrows or offsets its sensor's bound. ADR-0093 §10's
> argument-free `Reader.read` stands, and so do ADR-0260 §3:2–§3:3: no place crosses the
> planning seam, and the forecast's horizon is the forecaster's own.

> **Normative.** A pull gains an argument planning writes only by the decision that
> declares its kind, as the web search's query is the search's own decision (ADR-0231).

> **Normative.** The arguments a sensor's own proposal names, such as the forecast's origin
> and coordinate, are the hub's: filled from that proposal, as the search's origin is, and
> never offered to planning (ADR-0306 §2:10).

No Protocol, and no member of one, is needed for a pull: the reader and the forecaster are
asked exactly as their seams already take it.

### 4. The calendar channel

| What a kind declares (ADR-0292) | The calendar |
| --- | --- |
| Its channels (§2:5–§2:6) | One for each calendar source the deployment configures, its identity the source's `Reader.name`, which the configuration fixes (ADR-0189 §6) |
| Its spokes and directions (§2:11) | One spoke in the hub, whose sensor is the calendar reader facing the synced local `.ics` (ADR-0095); in only, with no actuator |
| Pulled, and pushing (§6:5) | Pulled, built now. It pushes an upcoming event and a change to an entry (§6:12, §13:3), declared now and built with proactivity |
| Its push filter (§6:11) | Decided with its push |
| How it establishes authors (§5:4) | It establishes none: every entry's author is a service, the calendar, claimed, and written when the source reported it |
| Places (§2:1, §10:8) | None yet |
| Its window (§10:2) | A pull takes none; its push's is decided with its push |
| Its requirements (§8) | No hosted medium and no actuator, so no medium's or channel's rules; its spoke's limits are the reader's bound (ADR-0093 §7a's figures) |

> **Normative.** The calendar is a kind as the table declares it: one channel for each
> configured calendar source, whose one spoke is in the hub and whose sensor is the
> calendar reader, with no actuator and no place.

> **Normative.** The calendar kind can be pulled, and its pull is built under this
> decision.

> **Normative.** The calendar kind pushes an upcoming event and a change to an entry,
> noticed by checking its file periodically (ADR-0292 §6:12). The push is declared here and
> built with proactivity, and until then the upcoming-event producer keeps working as
> ADR-0132 decides it (ADR-0292 §13:1).

> **Normative.** The calendar kind establishes no author. Every entry's author is a
> service, the calendar, claimed, and written when the source reported it.

> **Normative.** The calendar pull is declared with effect none; it does not leave the hub,
> its result may carry outside text, its outcome cannot be unknown, and it is safe to
> repeat. It is not side-effecting and discloses nothing.

> **Normative.** The hub offers the calendar pull to planning where the deployment
> configures a calendar source, and on no pass whose audience posture is unbounded
> (ADR-0281 §4:2).

> **Normative.** The calendar pull runs through acting's invoker, as a call that is not on
> the assistant's own records does (ADR-0306 §3:3), so its answer is one record whose
> writer is not known (ADR-0306 §5:15).

> **Normative.** Its answer is the reader's one `SourceReading`: every entry the reading
> proposes, each with the instants the reading carries for it, the reading's `read_at`,
> and its coverage as §7 states it.

### 5. The weather channel

| What a kind declares (ADR-0292) | The weather |
| --- | --- |
| Its channels (§2:5–§2:6) | One, where the deployment configures a forecast provider whole (ADR-0260 §11), its identity the forecaster's `name` (ADR-0260 §4:1) |
| Its spokes and directions (§2:11) | One spoke in the hub, whose sensor is the forecast client, `Forecaster`, facing the configured provider; in only, with no actuator |
| Pulled, and pushing (§6:5) | Pulled, built now. It does not push |
| How it establishes authors (§5:4) | It establishes none: a forecast's author is a service, the provider, claimed, and written when the provider reported it (`ForecastOutcome.reported_at`) |
| Places (§2:1, §10:8) | None |
| Its window (§10:2) | None |
| Its requirements (§8) | No hosted medium and no actuator; its spoke's limits are the forecaster's bound (ADR-0260 §3:3, §11) |

> **Normative.** The weather is a kind as the table declares it: one channel where the
> deployment configures a forecast provider whole, whose one spoke is in the hub and whose
> sensor is the forecast client, `Forecaster`, with no actuator and no place.

> **Normative.** The weather kind can be pulled, and its pull is built under this decision.
> It does not push.

> **Normative.** The weather kind establishes no author. A forecast's author is a service,
> the provider, claimed, and written when the provider reported it.

> **Normative.** The weather pull is the forecast read as `tools/forecast.py` declares it,
> `FORECAST_READ`. The hub offers it to planning where a forecaster is configured, beside
> the registry's capabilities as it offers the search, and acting's invoker sends its call
> to `Forecaster.read`.

> **Normative.** The forecast read stays registered at the egress seam and in no
> `ToolRegistry`, absent from `capabilities()` and `all_tools()` (ADR-0260 §1:4, §6:1).

> **Normative.** The weather pull reads the forecast for the deployment's configured place
> alone (ADR-0260 §3:2). A place the user names is a later decision (#2388, #2513).

> **Normative.** The weather pull is checked as every call is (ADR-0306 §4:1), its policy
> ruling under ADR-0260 §6. This decision changes no authorizing rule, and no grant gates
> the weather pull (ADR-0260 §15:3).

> **Normative.** The weather pull transmits as ADR-0306 §5:7 decides for a call that leaves
> the hub: its attempt and outcomes are its `InvocationLedger` claim and completion.

> **Normative.** This decision decides nothing about a connection's shape. The weather
> pull reaches the provider the deployment's connection names, and a keyless provider waits
> on #2396.

### 6. The grant use

> **Normative.** `GrantScope` gains `PULL`, valued `pull`: reading the source when an
> activation pulls it, for that activation alone.

> **Normative.** `PULL` authorizes the read and nothing else: no contact, no write to
> memory and no action (ADR-0097 §7, ADR-0133 §1:2).

> **Normative.** `PULL` implies neither `NOTIFY` nor `INGEST`, and neither implies it. No
> implementation infers one from another, ranks them or treats one as a superset of
> another.

> **Normative.** A new grant names a non-empty subset of `NOTIFY` and `PULL`, and a surface
> offering the uses for a new grant offers both, each named in words. `INGEST` stays
> refused as ADR-0294 §4:3 refuses it.

> **Normative.** No existing grant is migrated, back-filled or widened by `PULL`'s arrival.
> A grant recorded before it does not authorize it, and a live grant acquires it by the
> two acts, revoke then grant (ADR-0139 §4:1).

> **Normative.** The calendar pull reads its reader only under a live grant naming `PULL`
> and covering the reader's identity, checked at the instant the read starts and again when
> it returns, under ADR-0097 §5 and §5a, and each attempt is recorded to the source read
> trail with `PULL` as its use (ADR-0185 §1:1, §5).

> **Normative.** Where no live grant covers the read, nothing is opened, and the call comes
> back not done with a code-owned reason saying the source is not granted. A grant check
> that cannot be answered comes back not done with a different code-owned reason, so the
> two are told apart (ADR-0097 §5a:4–§5a:5).

The weather pull reads no `Reader`. ADR-0260 §15:3 gates it on no source grant, and this
section leaves that as it is.

### 7. Coverage: the half #2685 leaves to this decision

> **Normative.** `SourceReading.coverage`, `ReadCoverage` with its containment test, and the
> coverage the calendar reader declares stay as they are (ADR-0110 §2, ADR-0117 §5), and the
> calendar pull is their consumer.

> **Normative.** The calendar pull's answer states the interval its reading covered where
> the reading declares one, as the hub's own fact about the read and never as the source's,
> and states that the reading declares none where it does not.

> **Normative.** Nothing a pull reads closes, demotes or withdraws a record in memory. An
> entry absent from a pulled reading says nothing about any belief.

Coverage is what lets "nothing on Friday" be said of a reading that looked at Friday, and
not of one whose bound stopped short of it. Whether the calendar's push reads coverage to
notice a deleted entry is decided with that push.

### 8. The deadline, and late answers

> **Normative.** A pull runs under its call's deadline (ADR-0307 §8:2). At the deadline its
> read is cut short and cancelled, and its outcome is the one its declaration's
> `interrupted_outcome` gives: not done for the calendar pull, unknown for the weather
> pull.

> **Normative.** Nothing a pull would have answered after its deadline reaches the
> activation that asked, and none starts an activation: the read is cancelled, so no
> answer arrives late, and neither kind declares a late answer among its pushes (ADR-0292
> §6:6).

### 9. A pull marks the activation

> **Normative.** A pull's answer is outside content. An activation whose pull's digest
> answered has read digested evidence (ADR-0308 §5:4), and so has read outside content
> (ADR-0306 §4:5), and this decision makes no exception for a pull.

That is a cost, named here and left to the outside-content redesign (#2856): after a pull,
a remember is asked about, and a call that leaves the hub needs you unless the policy's
configured-provider route reaches it.

### 10. The code it binds

| Code | Change |
| --- | --- |
| `GrantScope` | Gains `PULL`, valued `pull` (§6:1) |
| `GRANTABLE_SCOPES` in `orchestration/payloads.py`, `AssistantEngine.grant` | A new grant may name `NOTIFY` and `PULL`; `INGEST` stays refused (§6:4) |
| The calendar pull's declaration | New `ToolDefinition`, the hub's (ADR-0306 §2:4), outside `readers/` (§4:5) |
| The calendar pull's driver | New, in `orchestration`: takes the reader, a `SourceGrants` and a `SourceReadRecorder` as required arguments (ADR-0097 §5:3, ADR-0185 §5:2), gates, re-checks and records each read, and answers as §4:8 and §7:2 state |
| `PhaseTools` | Offers both pulls (§4:6, §5:4) and sends each call to its sensor: the calendar's to its driver, the weather's to `Forecaster.read` with the arguments `Forecaster.request` proposed (§3:4) |
| The forecast integration | Claims and completes each call's `InvocationLedger` row (§5:8), as the searcher does |
| `app/composition.py` | Wires both pulls; `_build_phase_path`'s "so it is not offered" goes |
| `orchestration/phase_path.py` | The module docstring's "Left to later lanes: pulls" goes |
| The gateway's grant form, `interfaces/cli.py` | Offer and phrase `PULL`, named in words (§6:4) |
| The source read trail's arms (ADR-0185 §11) | Gain the pull's driver and its use, under ADR-0319 §7:2 |
| A kind's declaration in code | Takes the shape the first kind declared in code takes. A pull needs of it only its description (ADR-0292 §8:1), carried by the pull's declaration, and this decision adds no `core` type for it |
| `Reader`, `SourceReading`, `ReadCoverage`, `Forecaster`, `FORECAST_READ`, `ForecastOutcome` | Unchanged |

> **Normative.** The `core` member the table names is added as it states. Every other shape
> is the implementation lane's, within the table.

> **Normative.** The change that adds `PULL` advances `PROTOCOL_VERSION`, on ADR-0124 §9:2's
> rule.

### 11. Relationship to earlier decisions

| Earlier decision | What changes |
| --- | --- |
| ADR-0260 §1:4 | Its closing of the route to planning, *unreachable by any plan step* and *un-invocable through `ToolInvoker`*, for the phases: the forecast read is the weather pull, offered beside the registry's capabilities, and acting's invoker sends its call to `Forecaster.read` (§5:4). Its registration at the egress seam and in no `ToolRegistry`, and its absence from `capabilities()` and `all_tools()`, stand (§5:5) |
| ADR-0260 §1:1–§1:3, §3:2–§3:3, §4, §5, §6, §15:3 | Nothing: the seam, its place, its horizon, what it mints, its egress and its want of a grant stand |
| ADR-0133 §2:3 | Its subset, in the addition alone: a scope names a non-empty subset of the uses, `PULL` among them (§6:4). The members' independence and the rule against ranking them stand |
| ADR-0177 §6:2 | Its members, in the addition alone: the browser offers and renders `PULL`, named in words (§6:4) |
| ADR-0294 §4:3, §4:6 | Their subsets, in the addition alone: a new grant may name `PULL`, and a surface offers it (§6:4). The refusal of `INGEST` stands |
| ADR-0318 §6:2 | *`NOTIFY` alone*, in the addition alone: a new grant names a non-empty subset of `NOTIFY` and `PULL`, and a surface offers both, named in words (§6:4) |
| ADR-0097 §5, §5a | Nothing: they are written over "a reader … for a use" and "every site that drives a reader", so `PULL` lands inside them, and naming the calendar pull's driver as the caller for `PULL` is a stacked addition (ADR-0082 §1) |
| ADR-0185 §5:1 | Nothing: the calendar pull's driver writes the record for `PULL`, a stacked addition, and §5:2–§5:4 bind it |
| ADR-0093 §3:1, §10 | Nothing: a pull is a further consumer of a reading, a stacked addition, and the argument-free read stands (§3:2) |
| ADR-0094 §2:1 | Nothing: a device's pull rides a connection the device established, and none is built here (§2:6) |
| ADR-0292 §6:3, §6:5, §6:6, §13:1–§13:3 | Nothing: this decision applies them, and builds the pull §13:3 makes of the facet |
| ADR-0306 §2, §3:3–§3:4, §5:7, §5:14–§5:15 | Nothing: the pulls are declared, run, transmitted and routed under them |
| ADR-0307 §6:6; ADR-0308 §4, §5:4 | Nothing: these are the pulls planning may look up, digested as every outside result is |
| ADR-0319 §7:1–§7:2 | Nothing: §7:2 binds the lane that adds the pull's driver |
| ADR-0320 §2:4 | Nothing: this is the decision it waits for, and it keeps the coverage (§7:1) |
| ADR-0132 | Nothing: the upcoming-event producer keeps working until the calendar's push is built (§4:3) |

> **Normative.** This numbered draft records its replacements on the status lines and in a
> dated header note of ADR-0133, ADR-0177, ADR-0260, ADR-0294 and ADR-0318, atomically with
> this ADR under ADR-0070 and ADR-0082, preserving their ratified bodies. The replacements
> take effect on this ADR's ratification.

## Consequences

**What becomes possible.**
- "What's on Friday?" and "will it rain tomorrow?" are answered from the calendar and the
  forecast as they stand when asked, each through a digest, so planning never reads an
  entry's or a forecast's text.
- The calendar is read only where the user granted the pull, and every read is on the trail.
- A pulled reading says what it covered, so "nothing on Friday" is not said of a reading
  that never looked at Friday.

**What it costs.**
- Each pull's answer costs a digest, as every outside result does.
- A pull marks the activation (§9): after one, a remember is asked about and a call that
  leaves the hub may need you, until the outside-content redesign (#2856).
- A user who granted the calendar `NOTIFY` alone grants `PULL` by revoking and granting
  again.
- A peer at the old `PROTOCOL_VERSION` and one at the new cannot talk.

**What stays open.**
- The calendar's push, its filter and its window, and whether it reads coverage, with
  proactivity.
- A forecast for a place the user names (#2388, #2513), and a keyless provider (#2396).
- A pull of a sensor on a device, with the device session.
- What an activation keeps in memory from a pull, with the learning design. Until then a
  pull's answer reaches memory only as planning remembers it.
- The unbounded-audience gate on reads in general (#2593); the calendar pull is simply not
  offered on such a pass (§4:6).

## Alternatives considered

- **Gating the calendar pull on `NOTIFY`.** Rejected: ADR-0133 §1:2 has `NOTIFY` authorize
  one thing, a producer's read, and a user granting reminders has not granted reading their
  calendar whenever the assistant chooses.
- **Reviving `FACET`.** Rejected: it named a read on every turn, unasked, which ADR-0318
  retired; a pull is a read an activation asks for, and a fresh member keeps the two apart.
- **No grant for the calendar, as for the forecast.** Rejected: ADR-0097 §5:1 reads no
  reader for a use without a live grant, and a forecast reads no source of the user's.
- **A date range on the calendar pull.** Not taken: the reader's bound is its own (ADR-0093
  §10), and the digest answers the *looking for* over what the bound returned.
- **Registering the forecast read in a `ToolRegistry`.** Not taken: offering it beside the
  registry, as the search is offered, needs no change at the egress seam.
- **A late answer as a push** (ADR-0292 §6:6's second sentence). Not needed: the read is
  cancelled at its deadline, so no answer arrives late.
- **Retiring coverage.** Not taken: the calendar pull has a use for it, and retiring it now
  would owe a supersession the calendar's push might have to undo.
