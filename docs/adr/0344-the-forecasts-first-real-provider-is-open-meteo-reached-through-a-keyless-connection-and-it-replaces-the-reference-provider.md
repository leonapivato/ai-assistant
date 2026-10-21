# 344. The forecast's first real provider is Open-Meteo, reached through a keyless connection, and it replaces the reference provider

- Status: Accepted
- Date: 2026-10-21
- Scope: `tools/`, the forecast integration: the Open-Meteo adapter ADR-0325 §6:1 defers as its first item, the records that item owes against ADR-0260, and the lanes that build it. Tracker: [#2396](https://github.com/leonapivato/ai-assistant/issues/2396), [#2513](https://github.com/leonapivato/ai-assistant/issues/2513), batch [#3113](https://github.com/leonapivato/ai-assistant/issues/3113).
- Dependency: ADR-0260 as its status line leaves it, and ADR-0324 and ADR-0325, all on `main` at `c973d57a`.
- Authorization: the direction is the owner's ruling of 2026-10-17 in batch #3113 that the calendar and the weather come back as pulls, which ADR-0324 decides and which needs a real forecast source to reach anyone. The dispatcher assigned 0344, and walks and ratifies this decision under the owner's standing delegation of 2026-10-21: "Dont draw the line who ratifies what, Ill just check in and if I see something wrong I'll give input to you".
- **Does not change `core`.** No Protocol, type, error class, constant or `Settings` field is added or changed, and `PROTOCOL_VERSION` does not move (§8:3). Its required review set is adversarial *and* architecture, because it supersedes part of the forecast seam's credential clause, ADR-0260 §4:3.
- **Partially supersedes** [ADR-0260](0260-a-forecast-read-is-its-own-seam-at-a-configured-provider-and-what-it-mints-carries-the-extent-that-makes-it-evidence.md), in §4:3's credential and provisioning limbs, §6:2's *before the credential is read* and its re-read limb, §12:5's and §12:6's reference-provider limbs, §13:3's arm (b) in its omitted-field limb, and its arm (c) in its credential limbs, each as it reaches the production forecaster and in the scope §9 states.

## Context

**What is built, at `origin/main` `c973d57a`.**

- `tools/forecast.py`'s `ForecastEgress` is the one production `Forecaster`. It reads a
  *reference provider's* documented format: `/v1/forecast`, a `days` list of objects whose
  values are JSON strings, and a credential in an `X-Forecast-Token` field. Its module
  docstring calls it a source that "accepts a credential and does not use it" and says
  "replacing the adapter is replacing the constants below and `_provider_days` in this one
  module". No deployed service speaks that format.
- `FORECAST_READ` declares `reads=(DataTier.SECRET,)`, argued in its docstring because the
  callable reads an `INTEGRATION`-scoped credential.
- `build_forecast_integration` lives in `tools/builtin.py`, not in `app/composition.py`. It
  takes a `secrets` face and constructs a credentialed `HttpsEgressTransport`.
  `app/composition.py` calls it with `secrets=integration_secrets` where all four of
  `forecast_connection`, `forecast_origin`, `forecast_latitude` and `forecast_longitude`
  are set. Its comment records that nothing calls the forecaster since the old path's
  servicing was deleted: the weather pull (ADR-0324 §5) is not built yet.
- `HttpsEgressTransport` built with no `Secrets` face is keyless (commit `249be9c9`, ADR-0325
  §2:1). It reads the record once, refuses a record that names a slot, and raises
  `BoundCallChangedError` for that refusal as for every other pre-transmit one.
  `ForecastEgress._asked` already returns `ForecastRefusal.PROVIDER_REFUSED` for that error.
- The keyless act is on the engine and on the loopback wire as `connect_keyless_account`
  (commit `41af805e`). No client offers it: `interfaces/cli.py` has no command for it, and
  ADR-0325 §5:6 makes a CLI command a separate change.
- `Settings` carries ADR-0260 §11's nine `forecast_*` fields with their load-time
  refusals, and an unrelated `timezone` for the situational context.

**Open-Meteo, as its own pages state it, read 2026-10-21.**

- The forecast API (https://open-meteo.com/en/docs). `latitude` and `longitude` are
  "Geographical WGS84 coordinates of the location". "If daily weather variables are
  specified, parameter timezone is required"; `auto` resolves the zone from the coordinate,
  and the zone's offset is "used for ISO 8601 timestamps and daily boundaries throughout the
  response". "Daylight saving time (DST) changes within the requested range are ignored."
  `forecast_days` runs from 0 to 16. In the response, `utc_offset_seconds` is the "UTC
  offset for the requested timezone, in seconds, resolved at request time and fixed
  throughout the response". For `daily`: "For each selected daily weather variable, data
  will be returned as a floating point array", beside a `time` array of ISO 8601 dates, and
  `daily_units` names each variable's unit. The response's `latitude` and `longitude` are
  those of "the center of the weather grid-cell which was used to generate this forecast".
  An error is "a JSON error object … with a HTTP 400 status code", `{"error": true,
  "reason": "…"}`. `apikey` is "Only required to commercial use to access reserved API
  resources for customers", on a server whose name takes the prefix `customer-`. The page
  does not mention the `Date` field.
- The terms (https://open-meteo.com/en/terms). "You may only use the free API services for
  non-commercial purposes", the sentence ADR-0325 quoted on 2026-10-17, still stands.
  "Non-commercial use is defined as elaborated by creative commons." Its non-commercial
  examples include "Private or non-profit websites or apps that do not have subscriptions or
  advertising." and "Personal home automation purposes."; its commercial examples include
  "Websites or apps that have subscriptions or display advertisements." and "Commercial
  products or promotional activities." The free API allows "Less than 10'000 API calls per
  day, 5'000 per hour and 600 per minute", and "Rate limits are applied by IP addresses and
  application." "The data obtained through the API is provided under the terms of the
  CC-BY 4.0 licence".
- The licence (https://open-meteo.com/en/licence). "API data are offered under Attribution
  4.0 International (CC BY 4.0)". "You must include a link next to any location Open-Meteo
  data are displayed", with the example `<a href="https://open-meteo.com/">Weather data by
  Open-Meteo.com</a>`.
- CC BY 4.0's legal code (https://creativecommons.org/licenses/by/4.0/legalcode.en). Its
  conditions open with "If You Share the Licensed Material (including in modified form), You
  must:", "Share means to provide material to the public by any means or process that
  requires permission under the Licensed Rights", and "You may satisfy the conditions in
  Section 3(a)(1) in any reasonable manner based on the medium, means, and context in which
  You Share the Licensed Material."

**Two points where the framing does not survive contact with the texts.**

- **The declared instant does not rest on ADR-0260 §14.** §14:1 bars citing that section
  toward anything it defers, and Open-Meteo is one of those things. The authority here is
  §5:7, which takes the instant the provider's own response declares, and
  `tools/http_reading.py`'s `declared_instant`, which reads it from RFC 9110's `Date` field.
  §14's bullet describes Open-Meteo, and this decision relies on nothing it says.
- **A JSON number can be transcribed verbatim.** `tools/forecast.py` argues that a format
  carrying `19.2` as a number "would oblige this module to render a parsed float". It would
  not: a decoder can keep each number token as the text the response carried, which is
  exactly what ADR-0260 §5:2 asks for (§5:2 below).

## Decision

We will make Open-Meteo the forecast seam's one production provider, reached through a
keyless connection the owner makes by naming it. The reference provider leaves the tree. The
request carries the configured coordinate, a fixed set of daily fields, the forecaster's
horizon and `timezone=auto`, and nothing else. The response maps onto `ForecastOutcome` with
no new refusal class. The free API is used only where use is non-commercial, with a standing
credit and no credit added to each reply. Three lanes build it, none touching `core`.

### 1. Status and delivery

> **Normative.** This document remains `Proposed` until the reviews `CONTRIBUTING.md` →
> "Finishing an ADR PR" requires have returned green on one tree and the authorization to
> ratify stands. An assigned number or a green review alone does not change its status.

> **Normative.** No lane implements this decision before it merges `Accepted` (ADR-0015 §5).

### 2. The provider

> **Normative.** The production forecaster's provider is Open-Meteo. `ForecastEgress` reads
> Open-Meteo's documented `/v1/forecast` format as §4 and §5 state it, and no other format.

> **Normative.** The reference provider leaves the tree in the adapter lane (§8:1): its
> request path, its `days` list, its credential field and the constants and functions that
> read them. It is not kept beside Open-Meteo and not kept as a test double.

> **Normative.** The forecast integration is keyless (ADR-0325 §2:1).
> `build_forecast_integration` takes no `Secrets` face and constructs its
> `HttpsEgressTransport` with none, and `app/composition.py` hands it none. That code is
> what fixes its shape (ADR-0325 §2:2).

> **Normative.** No `Settings` field, flag or value selects the forecast provider, its
> format or its connection shape.

> **Normative.** `FakeForecaster` stays the test double for consumers of the seam. ADR-0260
> §13's arms over the production forecaster run on Open-Meteo-shaped responses served
> through the injected `OutboundTransport`.

**Why replace it rather than keep it.** The reference provider was "the M33 walkthrough's
forecast half until a real one lands" (ADR-0260 §12:6), and no deployed service speaks its
format, so no deployment can use it. Keeping it beside Open-Meteo would need a setting to
choose between them. Each integration's shape is fixed by its code, so that setting would
choose a connection shape through configuration, which ADR-0325 §2:2 forbids. Keeping it as a
test double would leave a second production format that ADR-0260 §13:1 owes arms over, and
consumers of the seam already have the canonical fake.

### 3. The connection, and the records ADR-0325 §6:1 says this owes

> **Normative.** ADR-0260 §4:3's *"A `Forecaster` holds the credential"*, as it reaches the
> production forecaster: it holds no credential and reads none, and its transport holds no
> `Secrets` face. *This contract never carries one*, and no credential value being in a
> binding, both stand.

> **Normative.** ADR-0260 §4:3's provisioning limb, *provisioned by the explicit user act
> ADR-0149 §4 requires, supplying an identity and a credential*, as it reaches the
> production forecaster: its connection is made by ADR-0325's keyless act, which supplies an
> identity alone (ADR-0325 §4:1–§4:2). §6's binding still needs the `ACTIVE` record
> `Settings.forecast_connection` names.

> **Normative.** ADR-0260 §4:3's *a source needing no credential at all is a shape this
> corpus does not have*, and its deferral of that shape to §14: ADR-0325 §2:1 adds the
> shape, and the production forecaster has it.

> **Normative.** ADR-0260 §6:2's *before the credential is read*, as it reaches the
> production forecaster, reads: before the connection record's one read (ADR-0325 §2:5) and
> before any channel is opened. Its three checks, their order, `ToolBindingError` on each,
> and their carrying no `ForecastRefusal` stand.

> **Normative.** ADR-0260 §6:2's mapping of the pre-transmit refusals to
> `ForecastRefusal.PROVIDER_REFUSED`, as it reaches the production forecaster, covers ADR-0325
> §2:3–§2:5's refusals against the one read: a reference that is not connectable, a recorded
> identity other than the bound one, and a record that names a credential slot. Each is
> returned as `PROVIDER_REFUSED` before any byte is transmitted.

> **Normative.** ADR-0260 §6:2's re-read limb, *its re-read after the credential is in
> hand*, has no subject on the production forecaster. A provisioning act landing after the
> one read is ADR-0148 §6:21's case, and the read proceeds (ADR-0325 §2:6).

> **Normative.** `FORECAST_READ` declares `reads=()`, because the keyless forecaster reads no
> Tier 0 value and ADR-0016 §1 makes every field of a declaration a claim. Every other field
> stands as `tools/forecast.py` argues it, `discloses=(DataTier.PERSONAL,)` included.

ADR-0260 §4:8's *before any credential is read* is left standing: a refusal made before the
call is revalidated is made before the record is read, and no credential is read at all.

### 4. The request

> **Normative.** One read sends one request: `GET /v1/forecast` at the configured origin,
> whose query carries exactly the parameters `latitude`, `longitude`, `daily`, `timezone`
> and `forecast_days`, and no credential.

> **Normative.** `latitude` and `longitude` are the ruled call's coordinate, read off the
> revalidated copy after `ForecastEgress` has compared it with its own configured place, as
> it does today (ADR-0260 §3:2).

> **Normative.** `daily` names a set of daily weather variables from Open-Meteo's documented
> list. The set is a constant of the adapter's code, pinned by a test, and no `Settings`
> value, caller or response widens or narrows it. Its first members are `weather_code`,
> `temperature_2m_max`, `temperature_2m_min`, `precipitation_sum`,
> `precipitation_probability_max` and `wind_speed_10m_max`, in that order.

> **Normative.** `timezone` is the literal `auto`. The provider resolves the zone from the
> coordinate, and the hub sends no zone of its own.

> **Normative.** `forecast_days` is `Settings.forecast_max_days`, the forecaster's own bound,
> held from construction (ADR-0260 §3:3).

> **Normative.** Nothing else leaves the hub in the request: no `Settings.timezone`, no unit
> parameter, no `apikey`, no identifier of a person, the hub, the connection or its identity,
> and no place the user named (#2388). The adapter adds no request field beyond `Accept:
> application/json`.

**Why `auto` and not the hub's own zone.** The ruling ranges over the call's arguments, and
`parameters_digest` binds them (ADR-0017 §3, ADR-0021 §1). `latitude` and `longitude` are
arguments; the daily set, `auto` and the horizon are constants of the forecaster. Sending
`Settings.timezone` would put a deployment value on the wire that the ruling never saw, or
would add an argument to `FORECAST_READ`'s schema. `auto` sends nothing new, and it makes the
days those of the place the forecast is for.

### 5. The response, and what it mints

| | What the response read off the channel carries | What the read yields |
| --- | --- | --- |
| 1 | More than `forecast_max_response_bytes` octets | `RESPONSE_TOO_LARGE`, abandoned while reading (ADR-0260 §11:3) |
| 2 | A status other than `200`, a `400` error object and a `429` included | `PROVIDER_REFUSED` |
| 3 | A body that is not a UTF-8 JSON object, as `decoded_object` reads one | `PROVIDER_REFUSED` |
| 4 | `daily` present and not an object, `daily.time` present and not an array, or a requested variable's member present and not an array or not of `daily.time`'s length | `PROVIDER_REFUSED`: the response does not say which value belongs to which day |
| 5 | No single readable `Date` field | `UNATTESTED` (ADR-0260 §5:7) |
| 6 | `daily` absent, or `daily.time` absent | `NO_RESULT`: the response names no day |
| 7 | `utc_offset_seconds` absent, not an integer token, or of magnitude 86 400 or more | Every day declares no offset and is dropped (ADR-0260 §5:8) |
| 8 | A requested variable whose member is absent, or whose unit `daily_units` does not give as a string | Every day is dropped (ADR-0260 §5:3) |
| 9 | A `time` element that is not a `YYYY-MM-DD` string naming a calendar day | That position names no day and is dropped |
| 10 | A day whose date and offset make no constructible extent, such as `9999-12-31` whose end is past the representable range | That day is dropped (ADR-0260 §5:9) |
| 11 | A day named more than once in `daily.time` | Every one of its positions is dropped (ADR-0260 §5:3) |
| 12 | A day whose element for a requested variable is `null`, a boolean, a string, an array or an object | That day is dropped (ADR-0260 §5:3) |
| 13 | A day whose transcription exceeds `forecast_max_day_chars` | That day is dropped (ADR-0260 §5:3) |
| 14 | Days surviving rows 7 to 13 | The first `forecast_max_days` of them are minted, in `daily.time`'s order (ADR-0260 §5:1); none surviving is `NO_RESULT` |

> **Normative.** The production forecaster maps a response onto `ForecastOutcome` as the
> table above states. Rows 1 to 6 are taken in order and the first that holds decides the
> read; rows 7 to 13 each drop days, and row 14 mints what survives them. No refusal class is
> added: `ForecastRefusal`'s six members say each case (ADR-0260 §4:6).

> **Normative.** The body is decoded with each number token kept as the text the response
> carried, and no transcribed value is parsed to a number or re-rendered on the way to a
> record (ADR-0260 §5:2).

> **Normative.** Day *i* is the *i*-th element of `daily.time`, and its value for a requested
> variable is that variable's *i*-th element. No value is assigned to a day by any other
> rule.

> **Normative.** `utc_offset_seconds` is the offset every day the response names is in. A
> day's extent is the half-open interval from that day's midnight at that offset to 24 hours
> later, computed from the date and the offset alone (ADR-0260 §5:8).

> **Normative.** A record's content transcribes, for its day, the `time` value and then each
> requested variable in the `daily` order, each with the provider's field name, its token as
> the response spelled it and, for a variable, its unit as `daily_units` spells it. The
> separators are fixed by the adapter and pinned by a test (ADR-0260 §5:2).

> **Normative.** No other member of the response reaches a record: not `latitude`,
> `longitude`, `elevation`, `timezone` or `timezone_abbreviation`, each of which locates or
> names a place (ADR-0260 §3:2), and not `generationtime_ms` or `utc_offset_seconds`, which
> are not about a day.

> **Normative.** `reported_at` is the instant the response's `Date` field declares, read by
> `declared_instant`, and there is no substitute (ADR-0260 §5:7).

> **Normative.** ADR-0260 §13:3's arm (b), in its limb *a response one of whose days omits a
> documented field … mints its siblings only*, as it reaches the production forecaster: a
> column of Open-Meteo's table cannot be absent for one day alone, so that limb is asserted
> as row 8, a requested variable's member absent dropping every day and yielding
> `NO_RESULT`, and as row 4, a member of another length than `daily.time`'s yielding
> `PROVIDER_REFUSED`. Its limbs for a value supplied as `null` and for one of a type the
> format does not admit, each of which mints the siblings, stand.

**The order is the reference adapter's.** The status and the shape are judged first, then the
declared instant, then the days, which is how `ForecastEgress._read` orders them today. A
transport failure, an expired deadline and a pre-transmit refusal end the read before any row
applies, as they do now.

**Why the extent is a fixed 24 hours, across a DST change too.** Open-Meteo aggregates each
day over "daily boundaries" set by the one offset, and ignores DST changes inside the range.
On a transition, the provider's day is therefore 24 hours at the fixed offset, not the civil
day. An extent computed from a timezone database would state a span the provider did not
aggregate over, which ADR-0260 §5:9 refuses. The extent computed here is where the reported
entry lies.

**Why a missing array drops days and a short one refuses the response.** ADR-0260 §5:3 drops
a day for which "the provider omitted a documented field", and a variable absent from `daily`
is omitted for every day. A variable present with the wrong length is a different thing: the
response no longer says which value is which day's, and pairing them by position would be
this system deciding what the provider said. That is "a body its documented format does not
admit", as ADR-0260 §10 described `PROVIDER_REFUSED` and as the adapter maps it today.

### 6. The terms, the licence and the credit

> **Normative.** A deployment configures Open-Meteo's free API, the origin
> `https://api.open-meteo.com`, only where its use is non-commercial in Open-Meteo's terms.
> This decision reads that to include the owner's own hub, and a pilot hub while the pilot
> charges nothing, carries no subscription or advertising, and is not offered as a product.

> **Normative.** A commercial deployment does not use the free API. It needs Open-Meteo's
> paid plan, which is a credentialed connection, the shape ADR-0325 leaves as it was, or an
> instance it hosts itself. The credentialed Open-Meteo integration is not decided here
> (§10).

> **Normative.** No credit is added to a reply for the forecast. Before a pilot hub
> configures the forecast, the welcome the pilot gives its people carries the standing
> credit "Weather data by Open-Meteo.com", linked to `https://open-meteo.com/`, with a link
> to the CC BY 4.0 licence and a statement that the assistant's replies summarise the data.

**Why a standing credit is enough here.** CC BY 4.0's conditions attach when material is
Shared, "to provide material to the public". The owner's own hub provides it to nobody, and
"Personal home automation purposes" is among Open-Meteo's own non-commercial examples. A pilot
is a few invited people, not the public, so the conditions arguably do not attach. A standing
credit costs one line, and it meets them if they do, in the "reasonable manner based on the
medium" §3(a)(2) allows. Open-Meteo's own page asks for a link "next to any location
Open-Meteo data are displayed". This decision reads that request as reaching data provided to
the public, and a deployment that does that is outside this decision (§10). A credit on every
reply would also need the reply to carry which sources it used. Under the phases no reply does,
and building that would cost a carrier through `orchestration/` and every surface.

**The pilot's standing is a reading, recorded so it can be overturned.** The pilot charges
nothing and shows no advertising, which puts it inside the terms' examples. It is also the
first step of a venture the owner may make commercial, and "Commercial products or promotional
activities" is among the commercial examples. §6:1's conditions are the line this decision
draws. The owner can move it, and the paid plan is the remedy on the other side.

**The rate limit is far away.** It is applied per IP address, and the pilot's hubs may share
one box. One pull is one request (ADR-0260 §2:3), against a limit of ten thousand a day.

### 7. Configuration, and the owner's act

> **Normative.** A deployment names Open-Meteo through ADR-0260 §11's existing fields and no
> others: `forecast_connection` is the reference the keyless act minted; `forecast_origin`
> is `https://api.open-meteo.com` where §6:1 allows it, or the origin of an Open-Meteo
> instance the deployment hosts itself; and the coordinate and the three bounds are as
> ADR-0260 §11 states them.

> **Normative.** `Settings` gains no field and no load-time rule that names Open-Meteo or
> its origin. Its existing refusals are the whole of the validation.

> **Normative.** A deployment on the free API states its cost as `forecast_cost_per_call`
> zero in the currency `forecast_cost_currency` names, as ADR-0260 §11:5 describes for a
> free provider. Unset, the unknown-cost floor binds unchanged.

> **Normative.** The connection's identity is the name the owner types in the keyless act,
> recorded verbatim (ADR-0325 §4:2). No client, configuration, default or lane supplies it.

> **Normative.** The keyless act reaches the owner through a CLI command of its own, separate
> from `assistant connect`, built under ADR-0325 §4:1–§4:5 in the lane §8:1 names, and served
> over the loopback socket only (ADR-0325 §5:5).

ADR-0325 §4's own example of an identity is "Open-Meteo", and it is what the owner is likely
to type; §7:4 keeps it the owner's to type. The identity the approver sees is that name. Every
minted record is still attested to the forecaster's `name`, `forecast`, which is never a
vendor (ADR-0260 §5:6).

### 8. Delivery

> **Normative.** Three lanes build this decision, each its own PR, none before it merges
> `Accepted`:
>
> - **The adapter**: `tools/forecast.py`, `tools/builtin.py`'s `build_forecast_integration`
>   and `app/composition.py`'s forecast wiring, with their tests. It corrects in the same
>   change every docstring and comment that cites the reference provider or the forecast's
>   credential (ADR-0260 §12:4), the reasons recorded on `FORECAST_READ` and the wiring's
>   comment included.
> - **The keyless command**: `interfaces/cli.py` and its tests (§7:5).
> - **The weather pull**: ADR-0324 §5 and §10, scoped there. This decision adds nothing to
>   it.

> **Normative.** The weather pull's lane merges after the adapter's. Both change
> `tools/forecast.py`, the pull through ADR-0324 §5:8's ledger claim, and a pull offered
> against the reference provider would reach no source. The keyless command is independent
> of both.

> **Normative.** Neither the adapter lane nor the keyless command lane touches `core/` or
> advances `PROTOCOL_VERSION`: no type, Protocol, method or encoding changes, and the wire
> method the command calls already exists. The weather pull's lane moves it only on ADR-0324
> §10:2's account.

> **Normative.** The adapter lane owes ADR-0260 §13:3's arms over the Open-Meteo format, and
> beside them: each row of §5's table; a number token transcribed as it was spelled, `17.20`
> and `1e1` included; the request target asserted whole, so that an added parameter fails;
> the transport constructed with no `Secrets` face; and a record naming a slot returning
> `PROVIDER_REFUSED` with no channel opened.

Deploying the adapter, making the owner's keyless connection and setting the forecast
settings in the owner's hub are the dispatcher's acts and come after the adapter lane and the keyless
command have both merged.

### 9. Relationship to earlier decisions

| Earlier decision | What changes |
| --- | --- |
| ADR-0260 §4:3 | Its *holds the credential*, its *supplying an identity and a credential*, and its *a source needing no credential at all is a shape this corpus does not have*, as they reach the production forecaster (§3:1–§3:3). *This contract never carries one*, no credential in a binding, the `ACTIVE` record `forecast_connection` names, and *claims no exemption from the connection model* stand |
| ADR-0260 §6:2 | *Before the credential is read*, read as before the record's one read, and the re-read limb, which has no subject, as they reach the production forecaster (§3:4–§3:6). The three checks, their order, `ToolBindingError` and the `PROVIDER_REFUSED` mapping stand |
| ADR-0260 §12:5, §12:6 | Their reference-provider limbs: the production forecaster is no longer the reference provider (§2:1–§2:2). What §12:6 asked of it carries to the Open-Meteo forecaster: every §5 outcome reachable through its format, a refusal on a connection that is not the bound one, and the deadline arm run against a real suspension of the injected transport |
| ADR-0260 §13:3 | Arm (b)'s omitted-field limb, asserted as a variable absent for every day and as a column of the wrong length, its `null` and ill-typed limbs standing (§5:8). Arm (c)'s *before any credential is read*, asserted as before the connection record is read; and its interleaving limb, *a reprovisioning landing between the credential read and the re-read*, replaced by a record re-provisioned to name a slot before the one read, which returns `PROVIDER_REFUSED` with no channel opened while the three checks still raise (§8:4). Every other arm and limb stands |
| ADR-0260 §1:1–§1:4, §2:3, §3:2–§3:3, §4:1–§4:2, §4:4–§4:10, §5:1–§5:10, §6:1, §6:3–§6:10, §11:1–§11:3, §11:5–§11:9, §12:1–§12:2, §12:4, §13:1–§13:2, §13:4, §14:1, §15:1–§15:3 | Nothing: read through and left standing, as earlier status lines leave them. §4:8's *before any credential is read* holds, with nothing read. §5:2's form and §5:3's drops are applied (§5). §11:5 is applied (§7:3) |
| ADR-0260 §2:1–§2:2, §3:1, §3:4, §7–§10, §11:4, §12:3, §13:5 | Nothing: ADR-0309, ADR-0319 and ADR-0320 already retire them |
| ADR-0325 §6:1 | Nothing: this is the decision its first item defers to, and §2–§5 bind the forecaster as they bind every keyless callable |
| ADR-0324 §5 | Nothing: the weather pull reaches the provider the deployment's connection names (ADR-0324 §5:9), now keyless, and its lane follows the adapter's (§8:2) |
| ADR-0324 §10 | Nothing: its row naming `FORECAST_READ` unchanged is what that decision's lanes change; the adapter lane changes `reads` (§3:7) |
| ADR-0016 §1 | Nothing: applied to `reads` (§3:7) |
| ADR-0148 §6 | Nothing beyond what ADR-0325 §2 already restates for a keyless callable |
| ADR-0151 §13, ADR-0177 §1 | Nothing: the keyless command is a CLI on the loopback socket, and the browser does not get the act |

> **Normative.** This numbered draft records its replacements on ADR-0260's status line and
> in a dated header note of ADR-0260, atomically with this ADR under ADR-0070 and ADR-0082,
> preserving its ratified body and its earlier records. The replacements take effect on this
> ADR's ratification.

### 10. What is not decided here

> **Normative.** This decision settles nothing about the following, and no lane cites it
> toward any of them.

- **A place the user names, and geocoding** (#2388). Fired as ADR-0260 §14 states.
- **Caching, retention or scheduling of a forecast** (ADR-0260 §14). Fired as stated there.
- **A credentialed Open-Meteo integration, for the paid plan.** Fired by the first deployment
  §6:2 reaches. Open-Meteo takes its key as a query parameter, `apikey`, where
  `HttpsEgressTransport` puts a credential in a request field, so that decision also owes the
  seam a credential placed in the query.
- **A deployment that provides the forecast to the public**, and the per-reply credit
  Open-Meteo's page asks for there. Fired by such a deployment, or by Open-Meteo asking for
  more than §6:3's credit.
- **Units other than Open-Meteo's defaults.** Fired by a deployment whose people need
  Fahrenheit or inches in the record itself and not only in the reply.
- **Another keyless source**, which uses ADR-0325's shape under its own decision.
- **The calendar pull and `GrantScope.PULL`** (ADR-0324 §4, §6).

## Consequences

**What becomes possible.**
- Once the three lanes merge and the owner connects it, "will it rain tomorrow?" is answered
  from a real forecast for the configured place, through the weather pull's digest.
- The forecast reads no secret, and the keyring holds nothing for it.
- A deployment can point `forecast_origin` at an Open-Meteo instance it hosts itself, with no
  change of code, because the format is the same.

**What it costs.**
- The reference provider's tests are rewritten against Open-Meteo's format.
- The free API binds every deployment that uses it to non-commercial use. A commercial one
  needs a later decision and a credential, or its own instance.
- A pilot hub cannot configure the forecast until its welcome carries the credit.
- The days are the place's days at the offset in force when the request was made. Across a
  DST change they are 24 hours at that offset, which is what Open-Meteo aggregated over.
- Units are Celsius, millimetres and kilometres an hour. A reply in other units converts
  them.

**What would make us revisit it.** Open-Meteo changing its terms, licence or format; a
response that routinely lacks a `Date` field, which would make every read `UNATTESTED`; a
pilot that starts charging or is presented as a product; or a deployment open to the public.

## Alternatives considered

- **Keep the reference provider beside Open-Meteo, chosen by a setting.** Rejected (§2): no
  deployed service speaks its format, and the setting would choose a connection shape
  through configuration, against ADR-0325 §2:2.
- **Keep the reference provider as a test double.** Rejected (§2): the canonical fake already
  serves consumers, and a second production format would owe ADR-0260 §13's arms twice.
- **Send `Settings.timezone`.** Rejected (§4): it is a value the ruling would not range over,
  unless `FORECAST_READ` gains an argument for it.
- **`timezone=GMT`.** Rejected: the days would be UTC days, misaligned with the place's
  mornings and evenings.
- **`timeformat=unixtime` with DST-aware extents.** Rejected (§5): Open-Meteo's daily
  aggregation ignores DST, so a DST-aware extent would state a span the provider did not
  aggregate over.
- **Parse numbers and render them again.** Rejected: ADR-0260 §5:2 forbids it, and a decoder
  can keep the tokens.
- **A refusal class for a malformed table.** Not needed: `PROVIDER_REFUSED` already covers a
  body the documented format does not admit, as the adapter maps it today.
- **A credit on every reply.** Not taken for these deployments (§6): it needs a per-reply
  carrier the phases do not have, and a standing credit meets the licence where it binds.
- **A setting for units.** Not taken: it is one more value leaving the hub and one more
  field, for a conversion the reply can make.
