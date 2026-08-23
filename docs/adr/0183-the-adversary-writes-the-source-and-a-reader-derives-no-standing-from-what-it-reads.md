# 183. The adversary writes the source, and a reader derives no standing from what it reads

- Status: Proposed
- Date: 2026-08-23
- **Decides no `core` surface: no Protocol, no type, no field, no error class and
  no function.** It is a threat model for the `readers/` seam — an adversary, the
  assets, the channels out of a reader, and the defence ruled per channel. Every
  clause below is a rule about what a reader, a lane or a surface may do with
  bytes the system does not own; none of them changes a signature. Golden rule 5
  and ADR-0015 §5 are therefore satisfied by having nothing to put in a contract
  PR, not by deferring one.
- **Required review set: adversarial.** `CONTRIBUTING.md` → "Stop when the
  required reviews are green" makes a change contract-surface when it decides
  `core/protocols.py` or `core/types.py`, or is the ADR deciding that surface.
  This is neither, which is the second of the three grounds ADR-0181 §9 gives for
  splitting this decision out of that one. The lane carrying it ran the
  architecture lens as well, which can only over-satisfy the set.
- **Discharges what ADR-0095 §6 named as owed**, in the words that section used:
  "A threat model for the seam. ADR-0093's §7 defences are
  resource-exhaustion-only and it states no adversary." It is #641's remaining
  three questions and nothing wider — ADR-0098 §10 folded the fourth (the
  downstream blast radius) and that half is **not re-decided here**.
- **Routed here by ADR-0181 §9**, which rules these questions "not decided here"
  and sends them to "a **sibling ADR**, dispatched as its own lane with its own
  number" alongside milestone 23 (#1427's ruling 2). That section also records
  that #641's own firing condition — "before a reader is pointed at a co-located
  fetcher's output" — has fired, because `src/ai_assistant/readers/email.py` is
  on `main` and ADR-0140's title is "The email source is a file **the fetcher
  replaces whole**".
- **A stacked addition under ADR-0082 §1: no earlier ADR's status line changes.**
  §12 makes that judgement clause by clause, including for ADR-0093 §4's
  sensitivity rule, which is the one place the opposite reading is available.
  Dated header notes are appended to ADR-0093 and ADR-0095 — pointers permitted
  in place by ADR-0070 §1, changing no decision — and to nothing else.
- **Adds no classifier and no detector, and forecloses one** (§9). #1427's ruling
  4 defers "any classifier-based defence" out of milestone 23; ADR-0098 §6 already
  forbids buying a bound from one. Nothing here is bought from one.

## Context

### What is owed, by whom, and why it is owed now rather than later

ADR-0093 specifies a reader that opens a file this system does not own and turns
its contents into proposals in the `ATTESTED` band. **It names no adversary.** Its
§7 and §7a defences are real and are all of one kind — a byte cap, an entry cap, an
expansion budget, a content budget, a read deadline, an off-loop worker, one
outstanding reservation. Every one of them bounds what a *large or slow* source can
cost. None of them says anything about what a *hostile* source can do.

ADR-0095 §6 recorded that gap under "Owed elsewhere, by name" and filed it as
**#641**, which the project owner parked rather than decided. ADR-0098 then folded
one of #641's four questions — the downstream one — and left three, adjudicating
the split in its §10 in terms this ADR adopts rather than relitigates:

> **The two halves genuinely differ**: this ADR assumes the reader parses hostile
> bytes correctly and asks what the correctly parsed result may do; #641's
> remainder asks whether it parses them correctly at all, and nothing here helps
> with a parser that crashes, hangs, or is coerced into misclassifying a source's
> tier.

ADR-0181 §9 re-affirmed that finding, declined to fold the halves back together,
and routed the remainder here. **The trigger #641 set for itself has fired.**
`EmailReader` reads a store a co-located fetcher writes whole, and the bytes in it
originate off-device, placed there by anyone who learns an address. The trust
assumption ADR-0093 reasoned under — "a local `.ics` calendar file" the user
already has — is no longer the assumption the tree runs on.

### The three questions actually left, and nothing wider

1. **What is the adversary at the seam?** #641 names three candidates: a hostile
   feed publisher, a compromised sync peer, another local process writing to the
   watched directory.
2. **Does ADR-0093 §4's "`sensitivity` chosen for what the source holds rather
   than defaulted" survive a source the open internet writes**, rather than a
   personal calendar?
3. **Does parsing want hardening beyond ADR-0093 §7's resource caps?** §7b's
   overlap, saturation and cancellation semantics are correctness rules, not
   hardening ones.

### What is already decided, and this ADR may not rebuild it

- **ADR-0098** is the downstream posture, entire: external content is a class
  decided by recorded origin (§1); the prompt is a rendering target and the
  attribution is not forgeable from inside a span (§2); an instruction inside
  external content is data and external content is never the authority for an
  action (§3); three ceilings on what it may become (§4); what is not enforceable
  (§5); detection is not a gate (§6); the escalation surface is a rendering target
  too (§7); the band is inspectable and the source is not yet nameable (§8).
- **ADR-0106** carries taint through consolidation, defines
  `rests_on_recorded_external_content` over a stored record, and puts the ceiling
  on `MemoryPolicy` at §6.
- **ADR-0140** decides the email source: nothing a message says is authenticated
  and no field is an identity (§4); the reader proposes an envelope and no body
  span at all (§5); the grant is on the read and the fetcher is not granted (§9);
  ADR-0098 governs unchanged and what email changes is volume rather than
  mechanism (§10).
- **ADR-0097** puts the grant on the caller and refuses the read outright where
  none is live (§5), with §5a's bounded guarantee.
- **ADR-0148, ADR-0154 and ADR-0181** hold the egress floor: an egress call is
  authorised whole, per call, with no standing authorisation, and ADR-0181
  establishes the recorded origin an authoriser evaluates.

None of that is re-argued below. Where a channel is already closed, this ADR says
so and names the clause — that is §9's first list, and it is deliberately the
longest of the three.

### The tree, read rather than assumed

Eight facts about what a reader actually does with bytes it does not own. Each is
read off `main` and each is load-bearing for a clause below.

- **Adversary-chosen bytes reach a third-party parser in the hub's own process.**
  `readers/_occurrences.py` calls `icalendar`'s `Calendar.from_ical` and expands
  recurrence with `dateutil.rrule.rrulestr`; `readers/email.py` frames the store
  by hand in `EmailReader._frame` and interprets each header block with the
  standard library's `email.parser.BytesParser` under the `compat32` policy. The
  bytes handed to each of those have already passed a byte cap and nothing else.
  Both parse paths are pure Python: neither installed distribution ships a
  compiled extension.
- **A parse failure is a refusal, and it is already payload-free.**
  `_occurrences._parse` wraps every exception the parser raises in
  `SourceNotParseableError`, and each reader's `read` wraps that again in
  `ReaderError` whose message `_failure` builds from the reader's declared
  identity and the exception classes alone. ADR-0093 §8 ruled both; the tree
  meets them.
- **A reader composes the belief's whole text.** `CalendarReader._render` returns
  `f'Calendar entry "{title}"{place}, {_when(occurrence)}.'` and
  `EmailReader._render` returns
  `f'Email from "{sender}" with subject "{subject}", delivered {_when(envelope)}.'`
  — attacker-chosen spans interpolated into a sentence of the reader's own, inside
  quotation marks the span may itself contain. `EncodableText`, the type that text
  lands in, validates that a string has a UTF-8 encoding and refuses nothing else;
  its own docstring records that "a C0 control character takes an escape, U+007F is
  emitted raw, and so are U+2028 and U+2029".
- **The two readers already neutralise differently, and nothing states which is
  required.** `EmailReader`'s `_unfolded` removes carriage returns and line feeds
  from a header value, because "one reaching a rendered belief would put a newline
  inside a quoted span". The calendar path does no equivalent: `_occurrences._text`
  is `"" if value is None else str(value)` and `_render` calls only `.strip()`, so
  an attacker-chosen `SUMMARY` carrying a newline reaches a stored belief's
  `content` verbatim. Neither reader touches a quotation mark.
- **A reader's `rationale` carries no span of its source.** Both readers emit
  `f"the {self.name} source reported this entry"` — or "…this message" — over a
  declared, Tier 2, constant identity. That is a property worth keeping rather
  than a coincidence.
- **Three assemblers put a stored record into a prompt, all three escape, and two
  of the three carry an origin term.** `orchestration/composing.py`,
  `orchestration/consolidation.py` and `planning/planner.py` each render a record
  through their own `_quoted_span` — `json.dumps` at its default
  `ensure_ascii=True` — and each emits a band-derived stance
  (`"a source the user connected reported"`). Composing and consolidation
  additionally build a `standing` term read from
  `rests_on_recorded_external_content(provenance)`; `planning/planner.py`'s
  `standing` is `f"{band.value}, confidence {provenance.confidence:.2f}"` and
  consults that predicate nowhere. §8 states what follows and what does not.
- **Both readers state `sensitivity=DataTier.PERSONAL` uniformly**, per source
  rather than per record, and each says in its own comment why: for the calendar
  because `PERSONAL` "is correct for a calendar and must not be *assumed* correct
  for the next source", and for email because "An envelope is `PERSONAL` and is
  uniformly `PERSONAL`" — the tier being honest *because* ADR-0140 §5 admits
  envelopes and forbids bodies.
- **The calendar reader declares a coverage and a per-proposal extent**, so its
  beliefs are absence-demotable; the email reader declares neither (ADR-0140 §7).
  `MemoryIngestor._absence_candidates` selects candidates from the `ATTESTED` band
  and skips any record whose `attestation.reported_by != source`, so the demotion
  a reading warrants reaches only records that reader itself reported.

### An honest statement of what this ADR is not allowed to settle

It may not redesign a reader, add a reader, add a defence that is a classifier, or
decide any `core` surface. It may not re-open ADR-0098's downstream posture, whose
§10 already adjudicated the split and whose §5 residual it inherits unaltered. It
may not decide the projection surface #1431 names, the band precedence #663 names,
or the body gate #1432 names — each is another lane's, and §10 says which and why.
And it may not state a bound it cannot ground: where the seam has no defence, the
sections below say so in a marked clause rather than leaving the silence to be read
as coverage.

## Decision

### 1. The adversary is whoever can place bytes in the source, and the fetcher is one of them

> **Normative.** The adversary at the `readers/` seam is **anyone who can cause
> bytes to appear in a source a reader reads**. The class is defined by that
> capability and by no other property: an invite sender, anyone who learns a mail
> address, a feed publisher, a sync peer, another local process with write access
> to the configured path, and the co-located fetcher itself are all members, and a
> reader distinguishes none of them from the user.

> **Normative.** The **fetcher is a member of that class and is not part of the
> trusted base.** No reader, lane or surface may assume a co-located fetcher wrote
> what it was configured to write: the framing, the headers the arrangement asks
> the fetcher to supply, and the content alike are adversary-influenceable.
> ADR-0140 §5's "Whether the framing is honest is the fetcher's, and the reader may
> not assume it" is this rule for one source; this clause is that rule at the seam,
> and every later reader inherits it rather than re-deriving it.

> **Normative.** Two capabilities are **outside** this model, and no clause of this
> ADR is offered as a defence against either: an adversary who can execute code in
> the hub's process or on its box, and an adversary who can write `Settings` or the
> hub's data directory. Each reaches every asset below by a shorter route than the
> seam, and a threat model that listed them among the things it bounds would be
> claiming a containment it does not have.

**The capability ladder, stated because the members are not interchangeable.** A
member who can only *send* controls the content of fields the framing admits, and
nothing else — an invite's `SUMMARY`, a message's `Subject` and `From`. A member
who can *write the store* controls that and the framing besides, including any
header the arrangement expects the fetcher to have written and stripped: ADR-0140
§5 requires the fetcher to strip every `X-Assistant-Delivered-At` a message
carried and write its own, so a hostile or subverted fetcher simply does not, and
window membership becomes the sender's to choose. A member who can *replace the
file* additionally controls **omission**, which §6 treats separately because it is
the one capability that removes rather than adds.

**Why the top rung is occupied by default now and was not before.** ADR-0140 §10
names the three things email changed — volume, unsolicited reach, and the
attacker's choice of arrival time — and rules that all three move the probability
that ADR-0098 §5's residual is exercised rather than the enforceability of
anything. That ruling stands. What this section adds is the population question it
did not need to ask: a calendar file implies a channel the user established, so its
writers are people the user chose; a mailbox has no such implication, so its
writers are everyone. The seam's adversary is therefore no longer hypothetical, and
#641's condition fired for exactly this reason.

**Configuration and a grant say nothing about the fetcher.** ADR-0093 §7 rules that
"Configuration is not a grant", and ADR-0140 §9's fourth clause reaches one step
further out: withdrawing a grant "stops the reading and does not stop the fetcher".
Both are consequences of this section rather than exceptions to it — the component
outside the boundary is outside the boundary for authorisation as well as for
trust.

### 2. The assets, and the channels out of a reader

> **Normative.** The assets this ADR states defences over are three, and a clause
> below is a statement about one of them and about nothing else: the store's
> **bands and confidences**; what reaches a **model call**; and the **egress seam**
> ADR-0154 designates. Availability of the hub is bounded rather than defended
> (§7), and no other asset is claimed.

> **Normative.** Adversary-chosen bytes leave a reader through exactly these five
> channels, and a lane that opens a sixth names it in that lane's own text:
> (i) **proposal content**, through `MemoryWriter.ingest` and the `MemoryPolicy`
> behind it; (ii) **proposal metadata the reader computes** — the minted id,
> `Attestation.reported_at`, `Attestation.extent` and `MemoryUpdateProposal.sensitivity`;
> (iii) a **facet scalar** into `CurrentContext`; (iv) `SourceReading.coverage`
> and `as_of`, the reading-wide declarations, whose consequence is a **retirement**
> rather than a write; and (v) the **framing and parse** themselves, whose product
> is which units exist at all and which bytes are which unit's.

**Channel (v) is the one that has no analogue downstream, and it is why #641's
remainder is a different scope from ADR-0098.** Channels (i) through (iv) carry
values, and ADR-0098's ceilings, ADR-0106's taint and ADR-0154's floor all act on
values. Channel (v) decides what a value *is* before any of them sees one: whether
this run of bytes is one message or two, whether a field belongs to the unit it
appears beside, whether the document parses at all. Nothing downstream can
compensate for a wrong answer there, because everything downstream is reasoning
about the units the framing produced.

**Channel (iv) points the other way from the rest and is easy to miss.** Every
other channel is a way for an adversary to put something *into* the store. This one
is a way to take something *out*: a reading that declares a coverage closes the
validity window of a live attested record the reading left untouched (ADR-0110 §3).
It is treated in §6.

### 3. A reader derives no standing from anything inside its source

> **Normative.** A reader derives **no standing** from anything its source's bytes
> contain. No field, header, display name, address, claimed identifier, framing
> marker, or position of a unit within the file may set or raise the band, the
> confidence, the sensitivity, the record identity, the reporting identity, the
> retrieval precedence, or the grant that a proposal drawn from it carries.

> **Normative.** Deciding **whether a unit is read at all** is not standing and is
> not forbidden by the clause above. ADR-0140 §4's second clause is the worked
> instance — window membership decided on a delivery header "confers nothing" — and
> its reasoning is general: a unit that buys its own admission to a window buys a
> place it could have reached by being placed in the source again, which is not a
> capability.

> **Normative.** Where a source's framing is **in-band** — delimited by a marker the
> content can itself produce — the boundary between units is adversary-influenceable,
> and every field of every unit inherits the standing of the **whole source** rather
> than of the unit it appears in. No reader may state, and no consumer may assume,
> that a field it read belongs to the unit the framing placed it in.

**This is one rule and it answers three of #641's worries at once**, which is why
it is stated over standing rather than over any particular field. A hostile feed
publisher choosing an `ORGANIZER`, a subverted fetcher choosing a delivery header,
and an mbox body line beginning `From ` that splits one message into two are the
same move: adversary-chosen bytes attempting to buy the record they land in
something it would not otherwise have. ADR-0140 §4 ruled it for email in four
clauses, and gave the reason the rule has to be general — "Anyone who can send mail
can already put any `From:` they like on a real message; SMTP has never
authenticated it". Generalising it here is what stops the third reader re-deriving
it, and what stops a lane reading ADR-0140 §4 as a fact about mbox.

**The third clause is stated as an inheritance rather than as a prohibition on
in-band formats, because the prohibition is unavailable.** Both formats this system
reads are in-band: an mbox delimits with a `From ` line, and an `.ics` document
delimits components with `BEGIN`/`END` lines that a folded property value can
produce. ADR-0140 §14 defers "A self-delimiting store format the reader can frame
without trusting a writer" and records that its condition may never be met. So the
honest rule is not "do not use such a format" — it is that the unit boundary confers
nothing, which is true whether or not a format is ever found. It also composes: a
belief drawn from a split fragment is in the `ATTESTED` band under §4, carries the
source's tier under §5, and is visible and killable by the user, exactly as one from
an honestly framed unit is.

**What this clause does not say.** It does not say a reader may not *read* a field —
readers read every field their ADR admits, and must. It says the reading confers
nothing. The distinction is ADR-0140 §4's own and it is the difference between a
useful reader and a useless one.

### 4. The tier is the source's, over the field set the reader's ADR admits (#641's second question)

> **Normative.** `MemoryUpdateProposal.sensitivity` is a property of the **source**,
> not of a record. A reader declares one tier, states it on every proposal it makes,
> and applies it uniformly. It is never defaulted — ADR-0093 §4's clause binds
> unchanged — and it is never **computed from, varied by, raised on, or lowered on
> account of** anything the source's bytes contain.

> **Normative.** ADR-0093 §4's "chosen for what the source holds" is read as **what
> the source's admitted field set may hold** — a ceiling over everything the
> reader's own ADR permits it to carry out of that source, chosen when the reader is
> specified and argued in that reader's own text. It is not a claim about what the
> source contains, and it is not a per-record judgement.

> **Normative.** Widening a reader's admitted field set is therefore a **re-tiering
> decision as well as an injection decision**, and the lane widening it owes both
> arguments in its own text. A widening that would bring `DataTier.SECRET` material
> inside the admitted field set may not ship while **#659**'s channel gap stands.

**#641's question has an answer and it is "yes, and here is what the words have to
mean".** ADR-0093 §4's clause survives a source the open internet writes, but only
under the second clause above, and the alternative reading is the failure the
question was pointing at. Read per record, "chosen for what the source holds" is an
instruction to inspect content and pick a tier from it — which is a **detector**, so
ADR-0098 §6 forbids it as a gate; and it is external content **setting a
parameter**, which ADR-0098 §3's first clause forbids outright. It would hand the
attacker the choice of their own tier, and the tier gates `MemoryUpdateProposal`'s
refusal of a confirmation on secret-tier material
(`_secret_data_carries_no_confirmation`). A rule whose enforcement the adversary
picks is not a rule.

**A public source is not a lower tier than a personal one, and the reason is what
the record discloses rather than what the material is.** #641 asks whether the
answer changes for "a public feed rather than a personal calendar". It does not. The
belief a reader writes does not say "the world contains this"; it says **this user's
connected source reported this**, carrying `reported_by`, `reported_at` and a
retrievable, exportable copy of the text. That the underlying item was published to
everyone makes the *item* public and leaves the *subscription* personal, and the
subscription is what the store now holds. A reader that lowered its tier because its
source is public would be reasoning about the wrong fact.

**The ceiling is over the admitted field set and not over the source, and that
distinction is what makes `EmailReader`'s `PERSONAL` honest.** A mailbox's bodies
hold everything from a newsletter to a password-reset link, and no honest ceiling
over "what a mailbox contains" is `PERSONAL`. ADR-0140 §5 admits a sender, a
subject and two instants and forbids a body span at all — so the ceiling over what
this reader can carry out is genuinely `PERSONAL`, and the reader's own comment says
so in as many words. **This makes ADR-0140 §5's envelopes-only prohibition a tiering
defence as well as an injection one, which neither ADR states**, and it is why the
third clause above attaches a re-tiering obligation to any widening rather than only
an injection one.

**The #659 condition is a real bar rather than a caution.** `MemoryUpdateProposal`
refuses a confirmation on a `DataTier.SECRET` proposal, because ADR-0004 §3 puts
Tier 0 content in the keyring and forbids it a committed file, so such a proposal is
never queued as a question. #659 records the neighbouring fact: `Engine.ingest`'s
only caller is the hub's scheduler, which reads no job's result, so a ruling made on
the ingestion path reaches nobody. A reader whose ceiling is Tier 0 would therefore
refuse silently, on a schedule, with no surface saying so — a source the user
believes is being read and is not. That is a channel problem before it is a reader
problem, and #659 is where it is tracked.

### 5. Parsing: the refusal is already ruled, and three properties are not (#641's third question)

> **Normative.** A reader's parser is **not a sandbox and is not offered as one**.
> Every bound of ADR-0093 §7 and §7a is stated over the reader's own work — bytes
> consumed, units counted, occurrences expanded, output materialised, wall-clock
> elapsed, workers outstanding — and none of them bounds what a parser does inside
> itself. No ADR, lane or surface may state that this corpus bounds a parser's
> memory, its stack depth, its recursion, or any I/O of its own.

> **Normative.** A parser a reader hands adversary-chosen bytes to **resolves no
> reference whose target the source directs**: it makes no network request, opens
> no file the source names or locates, and expands no external entity, however the
> source spells the request. A parser that would is not adoptable at this seam; a
> reader using one would be reaching the world from outside the designated `tools/`
> egress seam (ADR-0017 §1, ADR-0154 §3) through a library, on a schedule, with no
> permission check in the path.

> **Normative.** Resolving a name the source supplies against a **fixed local
> namespace the source cannot direct or extend** is not forbidden by the clause
> above, and is admissible only where the namespace refuses to be escaped by the
> name — where a supplied key can select a member and can never denote a path
> outside it. The reader's own configuration is not a source-directed reference at
> all and is outside this clause entirely.

> **Normative.** A parser at this seam is **memory-safe over its input**:
> adversary-chosen bytes may not reach a compiled parse path in which a malformed
> document is an out-of-bounds access or a controlled allocation. A lane adopting a
> parser with a compiled parse path over such bytes argues that property in its own
> text and inherits it from nothing here.

> **Normative.** The wrapping at a reader's seam catches **every exception arising
> from interpreting the source's bytes**, including the ones the parser's own
> documentation does not name. The breadth of that catch is the obligation rather
> than a lapse in it, and no lane may narrow it to an enumerated set of exception
> classes on the grounds of precision.

> **Normative.** ADR-0093 §8's cancellation carve-out is **untouched** and takes
> precedence over the clause above: a cancellation delivered from outside the call
> is delivered onward unchanged and is never converted into a `ReaderError`, and
> nothing in this ADR obliges or permits a reader to catch a `BaseException` that is
> not a failure of interpreting its source. `core/protocols.py`'s cancellation
> preamble and ADR-0060 bind this seam exactly as they did.

**The refusal half of #641's question is already answered and this ADR adds
nothing to it.** ADR-0093 §8 rules that a read "either completes within its bound
and returns a `SourceReading`, or **raises**", that it "may not return what it
managed to gather", that a source-level exception may not cross the seam unwrapped,
and that the resulting message is payload-free. A parser that crashes therefore
produces a legible refusal with a class name in it, the scheduler logs it and
re-arms, the facet degrades to `None`, and nothing is proposed. A parser that hangs
is bounded by the reader's own deadline and by the one-outstanding-worker
reservation, which §7 keys to the *worker* precisely so that a cancellation cannot
release it early. **That is the honest state of the parse-failure half: met, by
clause, and met in the tree.**

**The cancellation clause above is a fence around the breadth, and an earlier draft
did not have it.** That draft said the wrapping catches "every exception its parser
can raise", which a lane could read as licence to catch `BaseException` — and
ADR-0093 §8's carve-out is explicit that a cancellation delivered from outside "is
delivered onward unchanged and is never converted into a `SensorError`", with the
harm named: both consumers would treat a caller's own cancellation as a degraded
source, on a shutdown that was working correctly. `core/protocols.py` states the
same carve-out on the seam. The breadth this ADR wants is over *what interpreting
hostile bytes can throw* and stops exactly where ADR-0093 §8 already stopped it;
saying so is cheaper than leaving a lane to reconcile two rules that only appear to
disagree. Architecture review found the earlier wording on round 1.

**What was genuinely unruled is the class of parser a reader may hand hostile bytes
to at all**, and the clauses above are that. Each is stated because the
obvious reasoning fails in a specific way:

- **"The caps bound it" is false about the parser**, because the caps are the
  reader's own accounting. `calendar_max_bytes` is enforced on the read, before
  `Calendar.from_ical` is called; `calendar_max_expansion` bounds occurrences this
  reader counts; `calendar_read_timeout` bounds wall clock. A parser that allocates
  quadratically in its input, or recurses per nesting level, does so entirely
  inside the deadline and entirely under the byte cap. What contains that today is
  that both parse paths are pure Python, so a stack overflow arrives as a
  `RecursionError` and is caught by the wrapping clause above and reported as a
  source fault. That containment is a property of the libraries chosen, not of any
  rule — which is exactly why the second and third clauses state it as a rule for
  the next choice.
- **A reference-resolving parser is an egress hole that no egress clause covers.**
  Nothing in ADR-0154's fourteen conditions is expressed over a library call inside
  a reader, because a reader is a read-only seam whose whole premise is that it
  opens a file. A parser that fetched a `URI` a document named would make an
  outbound request with no `ActionPolicy` in the path, no CONFIRM card, and no
  ADR-0181 origin, driven by a scheduler on a timer. The class is familiar — an
  XML external entity, a stylesheet reference, a remote schema — and it does not
  arrive by anyone deciding to add egress. It arrives by adopting a parser. The
  clause exists so the third parser is chosen with that as a criterion rather than
  discovered to have it.
- **The calendar path already resolves a source-supplied name, and that is why the
  rule is stated over the reference's *target* rather than over resolution as
  such.** An earlier draft of the clause above said "opens no second file", and it
  was false of the tree it claimed to describe: `readers/_occurrences.py` records
  that "`icalendar` does the format — line unfolding, property escaping, **`TZID`
  resolution**", and resolving `DTSTART;TZID=Europe/Berlin` means reading the
  platform's timezone database. **That is admissible, and the second clause is what
  says why rather than an exception carved for it.** The source supplies a *key*
  into a fixed local namespace it cannot direct or extend: `zoneinfo.ZoneInfo`
  refuses an absolute path ("ZoneInfo keys may not be absolute paths") and refuses a
  key that would leave `TZPATH` ("ZoneInfo keys must refer to subdirectories of
  TZPATH"), so no `TZID` denotes a file of the adversary's choosing, and the worst
  a hostile one produces is a `ZoneInfoNotFoundError` or an `OSError` that the
  wrapping clause turns into a legible refusal. A parser resolving a `URI`, a
  filesystem path, or a `SYSTEM` entity is the opposite case on every one of those
  properties, which is the distinction the two clauses draw. Adversarial review
  found the earlier wording on round 1.
- **Memory safety is a dependency-selection property and belongs where the
  selection is made.** `CONTRIBUTING.md` already filters dependencies, and ADR-0024
  §3 already exact-pins the behaviour-affecting stack. Neither is expressed over
  "parses adversary-chosen bytes", which is a different axis from either. Stating
  it here gives the lane adopting the next parser a question to answer in its own
  ADR, which is the only place the answer can be argued.

**How the parsers are declared is named as a residual rather than ruled, and the
declaration is the weaker half of it.** `icalendar` is declared as a range
(`icalendar>=6.0`) and resolves to a major version above that floor, so the parse
behaviour over hostile bytes can change under a lockfile refresh without any
decision being taken. `dateutil` is declared **nowhere in the runtime
dependencies**: `readers/_occurrences.py` imports `dateutil.rrule.rrulestr`
directly while the package arrives transitively with `icalendar`, so the one
library that expands an adversary-chosen `RRULE` is not named in this project's own
requirements at all and would disappear if `icalendar` dropped it. Whether either
argues for an exact pin is ADR-0024 §3's question and not this ADR's — that
section's exact-pin rule is scoped closed to the four behaviour-affecting embedding
packages for a reason of its own, and widening it is a dependency-policy decision
with its own consequences. §13 defers both with the issue this lane files.

### 6. Omission is an adversary capability, and the retirement it reaches is confined by construction

> **Normative.** **Removing** an entry from a source is an adversary act of the same
> class as adding one, and every clause of this ADR is read over it. A reader, a
> lane or a surface that reasons only about content an adversary *inserts* has
> reasoned about half of channel (iv).

> **Normative.** No clause of this ADR, and nothing in ADR-0110 or ADR-0117, may be
> read as detecting whether an entry's absence from a reading is the user's act, the
> source's, or an adversary's. The three are indistinguishable from the reading, and
> the containment is the confinement below rather than a discrimination.

**ADR-0093 §4 forbade a reader to propose absence and gave the reason — "a bounded
read, a truncated file, a permission error and a genuinely deleted entry are
**indistinguishable from the reading**". ADR-0110 then built a narrow, opt-in path
by which an absence *can* close a window, and #641 predates it.** So the question
#641 could not have asked is whether that path gives an adversary a
belief-retirement capability. It does, and the size of it is worth stating exactly
rather than either alarming or dismissing.

**What an adversary who can rewrite a source gets.** The calendar reader declares a
coverage and a per-proposal extent, so a reading that exhausts its window and
accounts for every entry retires live attested records this reader reported whose
own extent lies inside that coverage and which the ingest left untouched. An
adversary with write access to the `.ics` file therefore causes a retirement by
deleting an entry — a real capability, and the mirror of the insertion capability
everything else in this ADR is about.

**What confines it, by clause and in the tree, is that the retirement cannot cross a
source.** `MemoryIngestor._absence_candidates` lists only the `ATTESTED` band and
skips every record whose `attestation.reported_by` is not the reading's own source.
So the capability is bounded to *records that source itself wrote*: it can retract
its own testimony and nothing else. A user's asserted belief carries no
`Attestation` at all — `Provenance` makes the attestation mandatory-and-exclusive to
the attested band — so it has no extent, is contained by no coverage, and is
unreachable from this channel by construction rather than by a filter. A derived
belief is outside the band the enumeration reads. And an adversary on one source
cannot retire another source's records even where the windows overlap.

**Two further confinements, named so the bound is not overstated in either
direction.** The email reader declares neither coverage nor extent (ADR-0140 §7), so
this channel is closed for it entirely and stays closed for any reader that does not
opt into both halves. And the calendar reader withholds coverage outright where the
read skipped anything it could not interpret, which means the cheapest way to
manufacture a retirement — feed the reader one uninterpretable entry so it stops
accounting — produces *fewer* retirements rather than more. That is the safe
direction and it is not an accident: ADR-0117 §5 chose it deliberately.

**What is left is a real residual and it is not closed.** An adversary who can
rewrite the source can retract that source's own beliefs, silently, on the reader's
schedule, and no surface reports it. §9 lists it under what is not detected.

### 7. Resource exhaustion is bounded per read and unbounded in the store

> **Normative.** ADR-0093 §7's and §7a's caps, and ADR-0140 §12's, bound **one
> read**. They bound nothing cumulative, and no ADR, lane or surface may state that
> this seam bounds what a source can cause this system to **store**.

> **Normative.** That gap is stated rather than closed here. A bound on cumulative
> growth — retention by count, a per-source quota, or an eviction rule over the
> `ATTESTED` band — is a `memory/` decision about the store's own lifecycle, not a
> reader's, and no lane may add one at this seam in place of it.

**#641's own framing was that ADR-0093 §7's defences "are all of one kind —
resource exhaustion", and the finding here is that they do not fully cover even that
kind.** Each cap refuses a single read that is too large: too many bytes, too many
framed messages, too many expanded occurrences, too much materialised content, too
long on the clock. None of them looks at the store. A reader mints a fresh
identifier per proposal, sets no expiry on what it proposes, and
`MemoryStore.purge_expired` "Physically remove[s] records past their `expires_at`"
— so a proposal that declares none is never reclaimed. Nothing in `memory/` caps a
record count, quotas a source, or evicts an attested record.

**Re-reading the same material is already idempotent, so the growth needs *fresh*
material rather than merely repeated reads.** `DefaultMemoryPolicy`'s `_re_reported`
rule folds an `EXTERNAL` proposal agreeing with a stored `EXTERNAL` record from the
same `reported_by` as a reinforcement at the target's id (ADR-0161 §1), which is
what stops every scheduled read retiring and re-installing its whole previous set
(#1198). So the growth is not a loop; it is a supply. An adversary who can place
*distinct* material in the source — which for a mailbox is one message per send —
adds durable records on every read, indefinitely, within every cap, with each read
refusing nothing. A record can be retired or window-closed later, which changes what
it warrants and not whether the row is there.

**Two things that make it worth a clause rather than an issue alone.** The first is
that the growth is *retrievable*: the records land in the `ATTESTED` band, which
ADR-0072 §5 orders above `DERIVED` when a retrieval budget is filled. ADR-0098 §10
already flagged that ordering as an input to **#663** on the ground that "`ATTESTED`
is the band an outsider can write into, and ordering it above `DERIVED` gives that
outsider budget priority over the system's own inferences". This section supplies
the volume argument that input did not have: the outsider's budget priority is not
over a fixed quantity of attested material, because the quantity is theirs to
choose. **That strengthens #663's input and does not decide it** — band precedence is
ADR-0072 §5's revisit and its own lane's, and pre-empting it here would be deciding
a retrieval question inside a reader's threat model.

The second is that availability is the asset §2 declines to defend. A store that
grows without bound degrades read latency and disk before it degrades anything this
ADR does defend, and saying "the caps bound it" would be false in the direction that
matters.

### 8. A reader composes, and composition is not escaping

> **Normative.** A reader's rendering of a proposal's content is a **composition,
> not an escaping**. It confers no structure a consumer may rely on and is not a
> trust boundary. The whole of a reader-composed content string is external content
> under ADR-0098 §1 for every purpose that ADR governs, including §2's prompt
> obligation and §7's surface obligation.

> **Normative.** The external span inside a reader-composed string is **not
> separately addressable**, and no consumer may attempt to locate it by parsing the
> rendering — by its quotation marks, its sentence shape, its field order, or any
> other artefact of the reader's phrasing. A surface owing ADR-0098 §7 presents the
> whole string as third-party content.

> **Normative.** A reader's `rationale` carries the reader's declared identity and
> **no span of its source**. It is the field a consumer reads as the reader's own
> account rather than the source's, and a reader that interpolated source text into
> it would destroy that distinction with nothing to signal it had.

**The failure this closes is a plausible-looking optimisation, not a mistake anyone
has made.** Both readers wrap external text in quotation marks —
`Calendar entry "{title}"…`, `Email from "{sender}" with subject "{subject}"…` — and
a later surface, wanting to satisfy ADR-0098 §7's "presents every span its
projection identifies as external as third-party content" without a projection that
identifies spans, could reach for the quotation marks as the identification. It
would be defeated by a `SUMMARY` containing a quotation mark, which is a character
the type permits and neither reader touches: `EncodableText` validates that a string
has a UTF-8 encoding and refuses nothing else. **Delimiting untrusted text with a
delimiter untrusted text may contain is not a defence** — ADR-0098 §2 states that
for the prompt assembler, and this is the same sentence for the surface, one
producer earlier.

**The two readers already neutralise differently, which is the argument for stating
this over the composition rather than repairing a reader.** `EmailReader._unfolded`
strips carriage returns and line feeds from a header value on the stated ground that
one "would put a newline inside a quoted span"; the calendar path strips only
leading and trailing whitespace, so an adversary-chosen `SUMMARY` carrying an
embedded newline reaches a stored belief's `content` verbatim. Neither touches a
quotation mark. Nothing in the corpus says which of the two behaviours is required,
and this ADR does not decide it: the divergence is filed as **#1449**,
and the clauses above are what make the answer not matter to a consumer. A rule that
said "readers strip control characters" would leave the quotation mark and would
teach a consumer that reader output is safe, which is the worse of the two errors.

**The prompt assemblers are not the exposed consumer here, and saying so keeps the
residual narrow.** All three of them — `orchestration/composing.py`,
`orchestration/consolidation.py` and `planning/planner.py` — pass a record's content
through `json.dumps` at `ensure_ascii=True` before it reaches a model, so ADR-0098
§2's deterministic construction holds wherever a stored belief becomes a prompt. What
is exposed is everything *else* that reads a stored belief: an inspection surface, an
export, a log line, a client rendering. Those owe ADR-0098 §7, and this section is
what tells them the reader's punctuation is not a help.

**One divergence among the three is recorded rather than ruled, because ruling it is
not this ADR's.** For an `ATTESTED` record all three convey externality the same way,
through a band-derived stance — `"a source the user connected reported"` — which is
ADR-0098 §2's marking-from-held-data clause met and is the case this seam produces.
Where they differ is one band further on: composing and consolidation add an origin
term computed from `rests_on_recorded_external_content`, so a `DERIVED` belief
carrying ADR-0106's taint reaches those two prompts marked as resting on a connected
source's report, and reaches the planner's marked only `derived, confidence …`.
**Whether that is a defect is a question about ADR-0098 §2's reach over a
system-authored span whose *warrant* is external, and about ADR-0106 §2's marker
rather than about a reader** — a derived belief's text is not itself external
content under ADR-0098 §1, which is why this ADR does not assert a nonconformance it
has not established. It is `src/` besides, and outside this lane's fence. Filed as
**#1453**. Adversarial review found the inventory and the divergence on round 1; an
earlier draft of this ADR asserted that both assemblers carried the origin term and
that there were two of them, and both halves were wrong.

**This is ADR-0181 §2's unobtainability met at the other end of the same chain, and
reached by the same argument.** That section withdrew "on the offending field" from
milestone 23's exit arm because a call's origin is a property of the call and not of
a field, and #1427's ruling 5 accepted the withdrawal and re-rendered the arm at
call granularity. The reader-side statement of the same fact is that a belief's
externality is a property of the record and not of a substring: the record is
`ATTESTED`, `rests_on_recorded_external_content` reports `True` for it, and neither
says which characters the adversary chose. Nothing in the tree can say, because the
reader did not record it and the string it built is flat. A surface that showed a
user "this part is theirs and that part is ours" would be asserting what this system
does not hold, which is the failure ADR-0098 §8's third clause names for authorship
and this clause names for extent.

**The `rationale` clause is a preservation rather than a repair.** Both readers
already satisfy it, and the reason to state it is that the field is the natural
place a later lane would put "what the source said" to make a question more legible
— at which point the one field a consumer could rely on to be the reader's own voice
would carry the adversary's, and no type, band or clause would mark the change.

### 9. The honest split: closed by construction, bounded, and not detected

This is ADR-0181 §7's shape, and its rule is inherited: nothing below is bought from
a detector, and the third list is stated so nothing claims it.

> **Normative.** No ADR, lane or surface states or implies that this seam detects a
> hostile instruction, a hostile source, a dishonest fetcher, a forged framing, or
> an adversarial omission. ADR-0098 §6 binds unchanged; no bound stated in this ADR
> is obtained from a detector, and none is available to be relaxed on the strength
> of one that is later added as defence in depth.

**Closed by construction, each by the clause that closes it.** These need no
vigilance, and listing them is what makes the third list credible.

- **The band.** `band_of` is a total function of `MemorySource` whose wildcard does
  nothing but `assert_never` (ADR-0094 §5); `ASSERTED` is reached only through
  `USER_ASSERTED`; a reader proposes `EXTERNAL`. So no reader-proposed record is
  `ASSERTED`, and no producer raises its own band (ADR-0098 §4's first two clauses).
- **A user's own belief is not supersedable by a source**, and it is closed twice.
  ADR-0092 §4 enumerates the supersedable class as membership rather than as a
  negation, precisely so that a later source is not silently enrolled; `memory/`
  spells that set identically in the policy and in the writer. `DefaultMemoryPolicy`
  rules `ASK_USER` on a conflict with a user-asserted memory rather than
  superseding, and `MemoryIngestor`'s own fold guard raises rather than folding an
  `EXTERNAL` record onto a `USER_ASSERTED` one — a writer-side floor that holds
  whatever policy a deployment injects.
- **A span reaches a model call escaped and labelled.** All three assemblers that
  put a stored record into a prompt — `orchestration/composing.py`,
  `orchestration/consolidation.py`, `planning/planner.py` — render its content
  through `json.dumps` and emit a band-derived stance, so ADR-0098 §2's two
  properties hold for an attested record at every one of them: a deterministic
  transform, and a marking derived from held data rather than from the text. The
  one place they diverge is a `DERIVED` record's origin term, which is a band this
  seam does not produce; §8 records it and #1453 carries it.
- **No episode, and no absence proposed.** ADR-0093 §4, and the `Reader` Protocol's
  own docstring. The narrow absence path ADR-0110 opened is opt-in in both halves
  and confined to the source's own records (§6).
- **Nothing a source says is an authority for an action.** ADR-0098 §3; ADR-0154 §4's
  item (i); ADR-0148 §3's second clause on a destination extracted from a selected
  span; ADR-0181 §7 enumerates the set once and this ADR cites rather than restates
  it.
- **Taint at consolidation.** ADR-0106 §6's ceiling on `MemoryPolicy`: a `DERIVED`
  proposal carrying `derived_from_external` and no `UserConfirmation` cannot commit.
- **Origin at the egress call.** ADR-0181 §3 and §5, as ruled; its implementation is
  a lane of its own and this ADR claims nothing about its state.
- **Never an authority at render.** ADR-0098 §7's three clauses on the escalation
  surface, under §2's non-forgeability read against the presenting surface's syntax.
- **No live grant, no read.** ADR-0097 §5 — not resolved, not opened, not parsed —
  with §5a's bounded guarantee stated rather than overstated.
- **A parse failure is a refusal and is payload-free.** ADR-0093 §8, met in the tree
  (§5).
- **A source cannot retire another source's records, or any user assertion.** §6.

**Bounded — a number, and each refuses rather than truncates.** `calendar_max_bytes`,
`calendar_max_entries`, `calendar_max_expansion`, `calendar_max_content_bytes`,
`calendar_read_timeout` and the one-worker reservation (ADR-0093 §7, §7a);
`email_max_bytes`, `email_max_messages`, `email_max_content_bytes`,
`email_read_timeout` and the same reservation (ADR-0140 §12). These are the whole of
the quantitative bounds at this seam. Each is per read (§7).

**Not detected, and not claimed.**

- **A hostile instruction inside a correctly parsed field that steers a selection
  without touching a guarded seam.** ADR-0098 §5's residual, restated unaltered by
  ADR-0181 §7. This ADR neither closes nor narrows it, and the containment is the
  one those sections enumerate.
- **Whether any byte of the source is honest.** No reader authenticates anything.
  ADR-0140 §4 rules it for a message's fields; §1 and §3 generalise it to the seam,
  the fetcher included.
- **Whether a field belongs to the unit the framing placed it in**, where the
  framing is in-band (§3).
- **Which member of §1's class placed a byte.** The reader records `reported_by` — a
  reader's declared identity — and ADR-0098 §8's third clause refuses to name an
  author within a source at all.
- **An adversarial omission** (§6).
- **What a source can cause this system to store, cumulatively** (§7).

### 10. #1431 and #1432 are routed, not discharged, and each gets one input

> **Normative.** This ADR **routes** #1431 and discharges neither of its fired
> triggers. ADR-0098 §8's second clause binds "the ADR that next revises the
> projection carrying a belief to an inspection surface"; this ADR revises no
> projection and decides no `core` surface, so the clause does not bind it, and no
> lane may read this ADR as having met it. ADR-0093 §11's display-label half is the
> same shape and is routed the same way.

> **Normative.** This ADR **routes** #1432 and takes neither of its readings. The
> question is about ADR-0140 §10's own text and about when that gate lifts; nothing
> in this ADR lifts it, narrows it, or supplies the seam it conditions on.

**The one input #1431 does not record.** ADR-0098 §8's three tiers were written
against one reader: this system "can say **'a source you connected reported it'**
today; it cannot yet say **'your calendar'**". #1431 correctly observes that the
first tier stopped doing the second's work by elimination when the second reader
landed. What this threat model adds is *why that matters for security and not only
for legibility*: the two sources now differ in **adversary reachability**. A
calendar file is written by peers the user chose; a mailbox is written by anyone who
learns an address (§1, ADR-0140 §10). A user ruling on an attested belief is
therefore choosing between two materially different trust properties with nothing on
the surface to distinguish them, and the coarse tier hides exactly the axis this ADR
is about. **That is an argument for the projection lane's priority, not a reason for
this ADR to pre-empt it** — the fix is a `core` surface decision on `Belief`,
`BeliefSummary` and `Question`, which golden rule 5 puts in its own PR and which
ADR-0106 §12 sequences behind the lane reconciling the three lossy projections
(#568, #673, #746).

**The one input #1432 does not record.** #1432 asks whether ADR-0140 §10's body gate
has already lifted, and reads it two ways. Whichever reading the lane that ingests a
message body takes, §4 and §5 above now attach two obligations to it that #1432 does
not name: bodies are outside `EmailReader`'s admitted field set, so admitting them
is a **re-tiering decision** and not only an injection one (§4's third clause), and
a body is where a format's own nested framing lives, so a lane admitting them owes
§5's parser properties for whatever interprets them. Both are conditions on that
lane, and neither settles which of #1432's readings is right.

### 11. What this ADR records elsewhere, and where it records nothing

> **Normative.** This ADR appends a dated header note to **ADR-0093** and to
> **ADR-0095** and to no other document. Each note is a pointer permitted in place
> by ADR-0070 §1 — it changes no decision, rewrites no ratified text, and alters no
> `Status` field.

> **Normative.** No clause of ADR-0098, ADR-0106, ADR-0140, ADR-0097, ADR-0133 or
> ADR-0181 changes, and none receives a note. Where this ADR generalises one of
> their rulings to the seam — ADR-0140 §4's at §3, ADR-0140 §5's at §4 — the
> original binds unchanged over its own subject and the generalisation is an
> addition beside it.

**ADR-0095 §6 is the note's own justification.** That section names "A threat model
for the seam" under "Owed elsewhere, by name" and records that it was "Filed as an
issue by this lane, parked by the project owner rather than decided here". The note
records that the ADR it named now exists. It also records that §6's "parked by the
project owner" is spent: #1427's ruling 2 dispatched it.

**ADR-0093's note is navigational and is worth the two lines.** #641's whole
complaint is against ADR-0093 specifically — a document whose §7 defences are one
kind and whose text names no adversary. A reader who reaches §7 and wonders what it
does not cover should find the answer on the page rather than by searching the
corpus.

### 12. This ADR classified under ADR-0070 §1 and ADR-0082 §1

ADR-0082 §1 requires the judgement in the later ADR's text, naming the clause and
applying ADR-0070 §1's test: a change to what was decided is anything a reader would
act on differently. **The answer is that no earlier ADR's status line changes.**
Everything here is a stacked addition at a seam two ratified documents left open by
name. Three places where the opposite reading is available:

- **ADR-0093 §4's third marked clause** — "A sensor's proposals carry a `rationale`
  naming the source, and a `sensitivity` chosen for what the source holds rather
  than defaulted" — is the strongest candidate, because §4 above fixes what "for
  what the source holds" means and a reader who had picked the other meaning would
  now act differently. **The test is unmet, on §4's own supporting text.** That
  section's prose reads "`MemoryUpdateProposal.sensitivity` defaults to
  `DataTier.PERSONAL`, which is correct for a calendar and must not be assumed
  correct for the next source" — per-source language throughout, with the tier
  attached to the source and revisited at the next one, never to an entry. §4 above
  states the reading §4's own prose already carries and adds the ceiling's domain
  (the admitted field set), which ADR-0093 could not have decided because no reader
  then had a field set to admit. Both readers on `main` satisfy the earlier clause
  and this one identically. The honest counter-reading is that removing an available
  meaning is itself something a reader acts on differently; it is rejected because
  the meaning removed is one ADR-0093's own text argues against, which makes this a
  determination and not a change. **Nothing is rewritten either way**: §4's clause
  stands verbatim and this ADR's clause stands beside it.
- **ADR-0093 §7 and §7a** acquire, at §5 and §7 above, statements about what they do
  *not* bound. Naming a bound's limit is not narrowing the bound: every figure binds
  exactly as it did, every refusal refuses the same reads, and a lane acting on §7
  alone builds the same reader. What changes is that a lane can no longer read §7 as
  covering a parser's internals or the store's growth — which §7 never said and
  which this ADR is the first document to say it never said. Not a supersession.
- **ADR-0140 §4 and §5** are generalised at §3 and §4 above. A generalisation that
  leaves the original binding over its own subject adds a clause at a wider scope
  and replaces none: `EmailReader` is bound by ADR-0140 §4 exactly as before, and by
  §3 above because it is a reader. ADR-0070 §1's test is unmet — nothing about email
  changes — and ADR-0140's status line is untouched.

**This ADR marks its clauses** (ADR-0089 §5): marking is forward-only, so nothing
above binds any ratified text and every obligation this document imposes is inside a
mark. Unmarked text here determines what a marked clause means and supplies no
obligation (ADR-0089 §3).

### 13. Deferred, by name, each with the condition that fires it

- **A cumulative bound on what a source can cause this system to store** (§7).
  Fires with the `memory/` lane that decides the `ATTESTED` band's lifecycle —
  retention by count, a per-source quota, or an eviction rule. Filed as **#1447**. It is not a reader's to add: a reader that refused to propose because
  the store was large would be making a store's policy decision inside a producer,
  which the `Reader` Protocol denies it in as many words.
- **How a parser over adversary-chosen bytes is declared and pinned** (§5).
  ADR-0024 §3's exact-pin rule is scoped closed to four embedding packages;
  `icalendar` is declared as a range, and `dateutil` — whose `rrulestr` expands an
  adversary-chosen `RRULE` — is imported directly by `readers/_occurrences.py` and
  declared in no runtime dependency at all. Fires with a dependency-policy decision
  about a second axis for pinning; filed as **#1448**.
- **Which neutralisation, if any, a reader owes over the text it composes** (§8).
  `EmailReader` strips CR/LF from a header value and the calendar path strips
  nothing equivalent, with no clause stating which is right. Fires with the lane
  that rules on it; filed as **#1449**. §8's clauses are what make the
  answer safe to defer.
- **Reporting an adversarial omission** (§6). A retirement this seam warrants
  reaches no surface for the same reason a refused proposal does not — `Engine.ingest`'s
  result reaches no adapter. Fires with **#659**, which owns the channel, and not
  before.
- **Naming which source a belief traces to** (§10). #1431, routed. Fires with the
  lane revising the belief projection, which ADR-0106 §12 sequences behind #568,
  #673 and #746.
- **Band precedence between `ATTESTED` and `DERIVED` under an adversary who chooses
  the volume** (§7). #663, whose input this ADR strengthens and does not decide.
  Fires with ADR-0072 §5's revisit.
- **A self-delimiting store format** (§3). ADR-0140 §14 already defers it and
  records that its condition may never be met; §3's third clause is what makes the
  wait safe rather than a wait for a fix.
- **A parser-hardening decision for a reader that needs one** — a subprocess, a
  memory ceiling, a seccomp-style confinement. Fires with the first source whose
  only available parser fails §5's second or third clause. It is deliberately not
  pre-designed: every mechanism costs a process boundary or a platform dependency,
  and choosing one with no candidate parser in hand is the guess ADR-0073 §4's
  standing test exists to prevent.
- **Everything ADR-0093 §11, ADR-0097 §12, ADR-0098 §12, ADR-0106 §12 and ADR-0140
  §14 defer**, unchanged and not re-listed.

## Consequences

**What becomes easier.** The seam has an adversary, so a lane can ask whether a
change gives that adversary something rather than deriving the question from
scratch. The three lists in §9 are the answer to "is this closed?" for every channel
at once, and the first is long enough that the third reads as a residual rather than
as a hole. A lane adding the third reader now has four questions it must answer in
its own text — its tier ceiling over its admitted field set (§4), its parser's two
properties (§5), whether it opts into coverage and extent (§6), and what it renders
(§8) — instead of discovering them in review. And two rulings that were stated for
one source, ADR-0140 §4's no-standing-from-a-field and §5's envelopes-only, now bind
the seam, so the next reader inherits them rather than re-deriving them.

**What becomes harder.** Three things a lane could previously have done cheaply now
cost an argument: varying `sensitivity` per record, adopting a parser without
checking what it resolves, and widening a reader's field set. The third is the
heaviest and it is deliberate — a widening is now two decisions rather than one, and
one of them (Tier 0 inside the admitted set) has a bar it cannot clear until #659 is
answered.

**What is honestly worse than it looks.** Two residuals are named here for the first
time and neither is closed. A source that supplies fresh material can grow the store
without bound within every cap (§7), and an adversary who can rewrite a source can
retract that source's own beliefs silently on the reader's schedule (§6). Both are
filed or routed; neither is defended today, and §9's third list says so.

**What would trigger revisiting this.** A reader whose source is a stream rather
than a re-readable file, which ADR-0093 §11 already defers and which changes §5's
refusal posture because there is no whole document to refuse. A parser with a
compiled parse path that a lane wants for good reasons. The first surface that can
name which source a belief came from, which would let §9's third list lose an entry.
And a second instance of one source type, which fires ADR-0093 §11's registry and
ADR-0097 §9a's precondition together and makes "which source" a question with two
answers rather than one.

## Alternatives considered

**Fold the threat model into ADR-0181 rather than write a sibling.** Refused there,
in §9, on three grounds this lane agrees with: ADR-0098 §10 already adjudicated the
split and found the halves genuinely different; the two decisions owe different
review sets; and their implementations put new machinery in different subsystems
(ADR-0137 §1). Re-folding them would relitigate a ratified finding in order to
lengthen the loop carrying a contract.

**Rule a sanitisation step between the parser and the store** — strip control
characters, collapse newlines, escape quotation marks in a reader's rendering.
Refused, and the reason is that it would look like a defence while being one only
against the case that is already closed. ADR-0098 §2 puts the non-forgeability
obligation on the assembler, over *the assembler's own syntax*, and a reader cannot
know that syntax — a reader that escaped for a bullet list would be wrong for a JSON
container and wrong again for HTML. Escaping at the producer is the exact mistake
ADR-0042 §4 identifies: escaping is a property of the rendering target. Worse, a
sanitised span *looks* safe, which is how a consumer stops doing its own escaping.
§8's clause — the composition confers nothing — is the honest form of the same
concern.

**Rule a per-record `sensitivity` decided by inspection**, so a calendar entry
mentioning a password could be tiered above one mentioning a lunch. Refused twice
over: it is a detector, which ADR-0098 §6 forbids as a gate, and it is external
content setting a parameter, which ADR-0098 §3 forbids outright. It would also fail
silently in the direction that matters, because #659 makes a Tier 0 refusal
invisible — the user would be told nothing about the entry the classifier caught or
the one it missed.

**Cap the store at the reader** — refuse to propose once a source's records exceed a
figure. Refused because it puts a store's policy inside a producer that the `Reader`
Protocol denies a store handle to, and because the cap would be enforced against the
wrong thing: a reader cannot tell its own accumulated records from another's without
the read surface ADR-0092 §10 declined to add. §13 sends it to the lane that holds
the store.

**Require an out-of-process parser for adversary-chosen bytes** — a subprocess with
a memory ceiling, or a seccomp-style confinement. Refused for this wave rather than
on principle. Both parsers on `main` are pure Python with no reference resolution,
so the mechanism would buy nothing measurable today while adding a process boundary
to a seam whose §7 worker discipline was already hard to get right — ADR-0093 §7
spends a page on why a `ThreadPoolExecutor` fails its exit requirement, and a
subprocess pool re-opens every one of those questions. §13 defers it with the
condition that supplies a candidate: the first source whose only available parser
fails §5's second or third clause.
