# 95. The read-only seam is a `Reader`, "sensor" belongs to the peer layer, and the contract's weight stays in `core`

- Status: Proposed
- Date: 2026-08-02
- Partially supersedes: ADR-0093 — the contract's name and the package its
  concretes live in (§2's placement clause and §10's names); §1 below. Every
  other ruling ADR-0093 made stands unchanged and is read under §1's
  substitution rule.
- **Decides no new `core` surface, and removes none.** This ADR renames a
  contract that has not been built and refuses a proposal to lower its weight.
  The surface ADR-0093 §10 specified is unchanged member for member; only the
  names change. Golden rule 5 and ADR-0015 §5 still put the triad in its own
  later lane, merged after this ADR.
- **Required review set: adversarial *and* architecture**, even though the PR
  carrying it is prose only. It decides a package boundary and rules on whether
  a contract lives in `core`, which is the ground ADR-0093's and ADR-0094's
  headers each took the same set for. It is **reviewed while `Proposed` and
  ratified only after** (`CONTRIBUTING.md` → "Contract ADRs land before their
  implementation").
- **Amends ADR-0094, which stands `Proposed`, by editing its text rather than by
  appending to it** — §7 states the adjudication that permits this and records
  what was edited. **ADR-0094's ratification is not touched**; that flip is its
  own lane's and remains outstanding.

## Context

### The window this ADR uses, and why it closes

ADR-0093 ratified on 2026-08-02 and **nothing has been built against it**: there
is no `Sensor` in `core/protocols.py`, no `SensorReading` in `core/types.py`, no
`ai_assistant/sensors/` package, and no triad lane started. The rename below
therefore costs one ADR and no code. Once the triad lands it would cost a
Protocol change, a `core` type change, a package move and a `lint-imports`
contract rewrite — a breaking change under golden rule 5 owing its own ADR — to
buy the same result. That asymmetry is the whole reason this is decided now
rather than filed as a naming preference.

It is worth being blunt that partially superseding a two-day-old ADR is not
free. The corpus's own record is that whole supersession is near-unheard-of
(#597 counts exactly one), and a supersession that arrives this fast invites the
reading that the earlier decision was careless. It was not: **ADR-0093's rulings
are overwhelmingly correct and this ADR reopens none of them.** What changed is
one premise it did not have, and one collision it could not have seen because
the ADR that creates it was written in parallel.

### The premise that changed: where the hub runs

ADR-0093 §2 chose a top-level package for concrete sensors, and the four
rejections it argued are about *subsystem responsibilities*. What it did not
argue — because it did not need to — is the implicit assumption underneath the
whole category: that the hub shares a machine with the user's files.

The project owner's leg 5 steer is that the hub eventually gets a **dedicated
always-on box**, and that today's loopback-only posture is a consequence of that
box not existing yet rather than a design position. ADR-0083 made the hub a
resident process and ADR-0084 gave it a local API; ADR-0094 then made every
attachment that crosses the process boundary an **edge peer** that dials out.
Compose those and the user's laptop is a *peer*, not the host.

On a dedicated box there is no calendar, no notes vault, no git repository and
no browser history on local disk. So the category ADR-0093 built for — a
read-only producer reading a source the hub can open directly — is **materially
smaller than it assumed**. It does not vanish, and the two patterns that survive
are worth naming because they are what the seam is actually for:

- **Files synced onto the hub.** A notes vault mirrored by Syncthing or `rsync`,
  chosen deliberately over granting a connector access to the source.
- **Co-located fetchers.** `vdirsyncer`, `offlineimap`, or an RSS-to-maildir
  daemon running *on the hub box*, with the reader reading their output. This is
  a mainstream self-hosted arrangement and it is the stronger of the two: it
  delegates credential handling, network failure and protocol drift to mature
  tools instead of to a connector this project would write and then own.

**An earlier framing of this category listed five members, and three of them do
not survive scrutiny.** A drop folder is undesigned. Peer-deposited files belong
to the *peer's* submission path — ADR-0094 §3's release gate and §7's
re-derivability obligation — and not to a scheduled reader. Imports and exports
are one-shot user actions on a different surface. Correcting the membership from
five to two matters for §4 rather than being tidiness: a category argued from a
padded list looks like it is shrinking towards one deployment-bounded member,
and that reading is what made lowering the seam's weight look reasonable.

### The collision: "sensor" is double-booked, and the peer sense has the better claim

ADR-0093 uses `Sensor` for an **in-process** Protocol. ADR-0094 §1 uses "sensor"
as an example **peer profile name**, carrying explicitly no normative force —
"no rule may be conditioned on which profile name … is applied to a peer".

The two senses are not merely different, they are near-opposites on the one axis
ADR-0094 §1 makes load-bearing: a `Sensor` is inside the hub, an edge sensor is
across the process boundary. ADR-0094 needed a marked clause to keep them
apart — "In particular a `Sensor` (ADR-0093) is not one, and no clause of this
ADR binds it" — and its §11 records that **an earlier draft got this wrong in
exactly the way the collision predicts**, calling a locally-read calendar file a
"pull peer" and thereby requiring an in-process object to establish a connection
and declare a released set. Adversarial review caught it on the second round.

That is not a hypothetical cost, it is a spent one: one marked clause, one
paragraph of §1, one block of §11, and a review round. A vocabulary that needs a
standing disclaimer to stay usable is double-booked.

**The peer sense has the better claim to the word.** A peer is a device that
senses the world — a microphone, a camera, a phone; an in-process object opens a
file. The roadmap's "sensors before actuators" pairing is about what the system
perceives and acts on at its edge, which is the peer layer. Freeing the word
makes ADR-0094 §1's profile list unambiguous rather than merely legal.

**`peer` itself is not renamed and nothing here touches it.** `wire/peer.py`
already uses the word for the process at the other end of a socket, and
ADR-0094 §1 records that the two senses agree.

### An honest statement of what this ADR is not allowed to settle

- **The prose sweep.** `VISION.md`, `docs/roadmap.md` (leg 6's heading),
  `CONTRIBUTING.md` and `CLAUDE.md` are untouched here. §6 names the sweep as
  owed.
- **The absence / window-closing decision** — whether an entry present in an
  earlier read and absent from a later complete one should close the belief's
  validity window. ADR-0093 §11 gave it a firing condition that ADR-0092 has
  since met. It is its own ADR and §6 names it.
- **A threat model for the seam.** ADR-0093 has none and its §7 defences are
  resource-exhaustion-only. Parked, and named in §6.
- **Everything ADR-0093 §11 defers**, which this ADR neither discharges nor
  narrows.

## Decision

We will rename the read-only seam from `Sensor` to `Reader`, move its package
from `sensors/` to `readers/`, and **keep the contract exactly where ADR-0093
put it** — a Protocol in `core/protocols.py` shipping as a full triad.

### 1. The seam is a `Reader`, its package is `readers/`, and ADR-0093 is read under a substitution

> **Normative.** The contract ADR-0093 names `Sensor` is named `Reader`. The
> type ADR-0093 §10 names `SensorReading` is named `SourceReading`. The error
> class ADR-0093 §10 names `SensorError` is named `ReaderError`. The package
> ADR-0093 §2 names `ai_assistant/sensors/` is named `ai_assistant/readers/`,
> and its concretes are named for their source and their role — `CalendarReader`
> and so on.

> **Normative.** Throughout ADR-0093, "sensor" denotes a `Reader` and every name
> above is read as its replacement. ADR-0093's text is **not** rewritten, and
> every other ruling it makes binds unchanged under the substituted names.

The substitution rule is what makes this a partial supersession rather than a
restatement, and §7 argues that classification. ADR-0093 uses the word 153 times
across 1,615 lines; rewriting it is forbidden outright by ADR-0070 §1 ("ratified
decision text — the Context, Decision and Consequences — is never rewritten"),
and relocating its clauses into this file is the append-only violation ADR-0070
§3 refuses when it declines to require pre-splitting. A reader who follows
ADR-0093's `Status` line to this ADR gets the substitution and then reads the
remaining rulings as written. That is exactly the shape ADR-0070 §4 built when it
made a scope "a **pointer, not a machine-resolvable anchor**" whose authoritative
extent "is stated by the superseding ADR itself".

**Why `Reader`.** The corpus names a Protocol for its product role — `Planner`,
`Observer`, `MemoryPolicy`, and ADR-0093 §10 says so in as many words. The
product role here is *reading a source*, which is also ADR-0093's own title
verb. `Reader` has no collision anywhere in `src/` or `tests/`.

**Why not `Importer`, which was the runner-up.** It has real corpus alignment —
ADR-0092 §6 rules on how "an import" mints its ids, and `MemoryStore.export` is
the symmetric operation — and that alignment is precisely the problem twice
over. It would collide with ADR-0092's vocabulary the way `Sensor` collides with
ADR-0094's, and "import" denotes a **discrete act** while the stronger of the two
surviving patterns is a continuously-mirrored maildir that is never imported and
always read. Naming the seam after the weaker member is how the next lane
misreads its cadence.

**Why not `Source` or `Ingestor`.** Both are taken: `ContextSource` and
`MemorySource` are live `core` names, and `MemoryIngestor` is a live class. A
seam named `Source` sitting beside `ContextSource` — which ADR-0093 §3 requires
to *hold* one — would be the same double-booking this ADR exists to end.

**Why `SourceReading` and not `Reading`.** A bare `Reading` reads as ambiguous
beside the clock: `ClockReadingError` is a live `core` name and "reading the
clock" is how ADR-0093 §10's own `read_at` is described. `SourceReading` says
which of the two it is, and it keeps ADR-0093's title sentence — a reader reads
a *source* — legible in the type name.

### 2. `readers/` stays a top-level package, and each of ADR-0093 §2's four rejections is re-tested rather than inherited

> **Normative.** Concrete readers live in a top-level `ai_assistant/readers/`
> package. It may import `core` and nothing else in `ai_assistant`; no subsystem
> may import it. The `lint-imports` contract expressing that is the implementing
> lane's.

That is ADR-0093 §2's clause with the package renamed, and it is restated here
rather than left to the substitution because §4 leans on its second sentence.

**The premise moved and the conclusion did not, which is worth showing rather
than asserting.** ADR-0093 §2's four rejections are arguments about what each
subsystem *is*, and none of them was resting on where the hub runs:

- **`context/`** is advisory and non-durable (ADR-0008 §4). A reader living
  there would need a `MemoryWriter` to reach memory, making the advisory
  subsystem a belief producer. Unchanged — this is a property of ADR-0008, not
  of the deployment.
- **`memory/`** owns the store and the gate; a producer beside the policy ruling
  on it is what ADR-0028's propose/dispose split exists to prevent. Unchanged.
- **`learning/`** is model-backed distillation. A reader infers nothing.
  Unchanged, and the dedicated box *strengthens* it: a co-located fetcher's
  output is even further from distillation than a local `.ics` file was.
- **`tools/`** owns the registry and ADR-0017 §1's undesignated egress seam.
  Unchanged, and here the deployment change makes the rejection **more**
  load-bearing rather than less. A co-located fetcher is the pattern that most
  resembles a connector, and filing readers in `tools/` would put the seam
  inside the package whose network posture is governed by ADR-0017 §3's fourteen
  unmet conditions — at exactly the moment the surviving patterns are the ones a
  later lane might mistake for network clients. They are not: the fetcher does
  the network, the reader reads its output off disk.

One thing the deployment change *does* alter is which member the placement is
argued from. ADR-0093 §2 reasoned about a local `.ics` file. §2 now reasons about
a synced vault and a co-located fetcher's maildir, and reaches the same package.

### 3. The seam's weight stays in `core`: examined and refused

> **Normative.** `Reader` is a Protocol in `core/protocols.py` and ships as a
> full triad — Protocol, shared conformance suite, and canonical fake in
> `ai_assistant.testing` — exactly as ADR-0093 §10 specifies. It is not an
> internal seam of `readers/`, and its triad obligation is not waived.

A proposal was put to this lane to lower the seam's weight: make `Reader` an
internal seam of its own package on the model of `ContextSource` in
`context/sources.py`, and drop the triad. **It is refused, on two independent
grounds, each of which is decisive alone.** They are recorded here in the
ADR-0083 §15 pattern — examine a clause and state what it does — so the next lane
inherits the answer instead of re-deriving it.

**Ground one: a `core` Protocol cannot skip its triad, and the gate says so.**
`CONTRIBUTING.md` → "Adding a Protocol: land the triad together" makes the three
artifacts one unit of work, and `tests/core/test_protocol_triad.py` enforces it
on every run over every Protocol in `core/protocols.py`. Its `EXEMPTIONS` tuple
is empty, and a second assertion rejects any entry that is not legacy debt —
`CONTRIBUTING.md` states the closure directly: "the list is empty and no Protocol
remains that an exemption could name, both of which
`tests/core/test_protocol_triad.py` enforces on every run." So "a `core` Protocol
shipping no triad" is not a decision available to an ADR; it is a red gate.

**Ground two: the seam has two subsystem consumers, and ADR-0093 §2 forbids them
importing the package.** This is where the `ContextSource` analogy breaks, and it
breaks on the fact that made `ContextSource` internal in the first place.
`ContextSource` gets to be fully internal because **both the seam and its
implementations live in `context/`** and the name is never spoken outside it —
which is how ADR-0008 §2 could guarantee "the only data that crosses a subsystem
boundary is the typed `CurrentContext`". A `Reader` has the opposite shape: its
implementations live in a package **nothing may import** (§2), while the *type*
is held by two subsystems that ADR-0093 names:

- **`orchestration`** — §1 rules that "Selecting when a sensor runs, and
  ingesting what it returns, are `orchestration`'s", and §6 and §10 put the
  ingestion operation on the `Engine` as "new concrete surface in
  `orchestration`". The `Engine` therefore holds readers by injection and must
  name their type.
- **`context/`** — §3 rules that "A `ContextSource` in `context/` holds a
  `Sensor`". §7a defers the wiring until the facet field exists, so this consumer
  is queued rather than live; it is a consumer nonetheless.

Putting `Reader` in `readers/protocols.py` therefore requires `orchestration` to
import `ai_assistant.readers`, which **§2's own clause forbids in as many words**
— "no subsystem may import it" — a clause this ADR preserves. `CLAUDE.md`'s
golden rule 1 points the same way in its first sentence, that subsystems "talk
to each other only through the Protocols in `src/ai_assistant/core/protocols.py`";
it is named as corroboration rather than as the bite, because its mechanically
enforced half forbids importing another subsystem's **concrete module** and a
Protocol import would not strictly breach it. The clause that actually bites is
ADR-0093 §2's.

ADR-0093's split is the resolution of that tension, not an inflation of it: the
**contract** in `core` where every subsystem may name it, the **implementations**
in a leaf package nothing imports. Lowering the weight does not simplify the
arrangement, it breaks the property the arrangement exists to hold.

**Why this is a refusal and not a deferral.** A deferral owes a firing condition
(ADR-0093 §11's form, and ADR-0094 §10's). There is none available here: nothing
in the future makes a `core` Protocol able to skip a triad the gate enforces, and
nothing makes a package that no subsystem may import able to export a type two
subsystems hold. Both grounds are structural rather than timing-dependent, so
recording this as "deferred" would promise a revisit that no event can trigger.

**And the corrected membership inverts the argument that motivated the
proposal.** The case for lowering the weight was that the surviving category is
smaller than ADR-0093 assumed. It is — from a padded five to a real two — but
**shrinking the number of categories does not shrink the number of
implementations.** A synced-vault reader and a co-located maildir reader are two
implementations of one behaviour, which is precisely and only what a shared
conformance suite is for. ADR-0093 §10 already enumerates the clauses that bind
every reader without reference to a source — `name` stability, `source` equal to
`name`, tz-aware instants, no `EPISODIC` proposal, every proposal in the
`ATTESTED` band, an empty reading being a success, `ReaderError` on failure, and
the cancellation clause that keeps a conforming-looking reader from absorbing a
`CancelledError`. Two implementations is the condition under which that suite
starts paying rather than the condition under which it stops.

The cost of keeping the weight is honestly small and worth stating: one suite and
one fake, both fully specified by ADR-0093 §10 before this ADR was written. The
cost of dropping it would have been that the second reader is held to the first
one's behaviour by review alone — which `tests/core/test_protocol_triad.py`'s own
docstring names as "the same class of gap ADR-0015 names — an invariant held by
prose rather than mechanism".

### 4. What crosses the boundary, stated rather than left to be discovered

> **Normative.** `SourceReading` is a frozen pydantic model in `core/types.py`,
> as ADR-0093 §10 specifies. Renaming the seam moves nothing out of `core`.

This is the honest half of §3 and it is stated so a later lane does not read
"internal seam" into the rename. A reader's output **does** cross a subsystem
boundary — from `readers/` to `orchestration`, and later to `context/` — so
`CLAUDE.md`'s rule that public data crossing subsystems is a pydantic model in
`core/types.py` applies with full force, exactly as ADR-0093 §10 held.

There is no arrangement that avoids this without contorting something. A seam
returning an untyped mapping would put `context/`'s deliberately-internal shape
(ADR-0008 §2) on a path that leaves its package, which is the one thing that
section exists to prevent. A seam returning a bare sequence of proposals is what
ADR-0093 §3 already rejected, because the facet field then arrives as a signature
change owing its own breaking-change ADR under golden rule 5.

So the weight reduction was never available even in the half the proposal
conceded. `core/types.py` holds the reading either way; §3 shows
`core/protocols.py` holds the Protocol too.

### 5. What this ADR does not touch in ADR-0093

> **Normative.** Every ruling of ADR-0093 other than the names in §1 and the
> package in §2 is unchanged, and this ADR neither narrows nor discharges any of
> them.

Named individually because a supersession invites the reading that more moved
than did: §4's band, episode and absence rules; §5's bound, its
refuse-don't-truncate posture, its no-cursor argument and the re-readability that
buys it; §6's scheduler job and its enablement; §7's configuration discipline,
declared identity and the configuration-is-not-consent debt; §7a's figures and
enablement matrix; §7b's `.ics` overlap, seek, fold and override semantics; §8's
two failure postures; §9's ADR-0092 gates; §10's member-for-member surface; §11's
deferrals; and §12's classification of ADR-0093 itself. All of it binds, under
the substituted names.

### 6. Owed elsewhere, by name

- **The prose sweep.** `VISION.md`, `docs/roadmap.md` (leg 6's heading),
  `CONTRIBUTING.md` and `CLAUDE.md` use "sensor" for this seam. Correcting them
  is a separate change and is not this ADR's; #625 and #629 are the issues that
  carry the surrounding leg-6 context.
- **The absence / window-closing decision.** ADR-0093 §4 forbids a reader
  proposing an absence and §11 defers retraction with the condition "Fires with
  ADR-0092's override mechanism". ADR-0092 has merged, so the condition is met
  and the decision is unblocked. It is its own ADR and is filed as an issue by
  this lane.
- **A threat model for the seam.** ADR-0093's §7 defences are
  resource-exhaustion-only and it states no adversary. Filed as an issue by this
  lane, parked by the project owner rather than decided here.
- **Everything ADR-0093 §11 defers**, unchanged and not re-listed.

### 7. This ADR classified under ADR-0070 §1 and ADR-0082 §1

ADR-0082 §1 requires the judgement in the later ADR's text, naming the clause and
applying ADR-0070 §1's test. Two ADRs are touched and they are touched
differently.

**ADR-0093 — partially superseded, and the scope is the name and the package.**
§1's test is met on its face: a reader holding only ADR-0093 would build a
`Sensor` in `ai_assistant/sensors/`, and after this ADR they build a `Reader` in
`ai_assistant/readers/`. That is a decision changed, not a stale phrase
corrected, so it is a supersession and not an amendment — ADR-0082 §1's "**The
test controls, not the label**", applied to this ADR's own change first.

**Partial, not whole, and this is the question the lane owed.** The argument for
whole supersession is that a name saturates the document, so no clause can be
named as the scope. It fails on three grounds:

- **ADR-0070 §4 does not require the scope to bound the *text*.** A scope is "a
  specific, human-legible clause reference … required and specific, not a
  gesture", and explicitly "a **pointer, not a machine-resolvable anchor**", with
  the authoritative extent "stated by the superseding ADR itself". ADR-0001's own
  scope is a named clause (`the change-a-decision mechanism`), not a section
  range. Saturation of a *word* is not the test; what must be nameable is the
  *decision* replaced, and here it is two: what the contract is called, and which
  package its concretes live in.
- **ADR-0070 §3 forecloses the alternative.** Whole supersession would mean
  restating ADR-0093's roughly thirty normative clauses in this file under new
  names. §3 refuses exactly that operation — "splitting a ratified ADR's clause
  into a separate file would rewrite and relocate ratified text — the append-only
  violation §1 exists to prevent" — and rules partial supersession "the
  sanctioned tool when a later ADR replaces part of an earlier one, decided once
  here rather than re-argued per case".
- **It would be false to the record.** ADR-0093's rulings are live and this ADR
  keeps them (§5). A `Superseded by` token would tell every consumer that
  ADR-0093's no-cursor argument and `.ics` semantics are dead, which is the exact
  misreading ADR-0070 §4 names when it refuses to let `Partially superseded`
  collapse into either binary.

**ADR-0093's `Status` line gains the leading token and a dated note.** Under
ADR-0070 §1 recording a supersession that has landed is a permitted in-place
header edit, and ADR-0001's own header is the worked form this follows: the
`Status` field carries the leading token with the scope, and an appended dated
note states the extent. Under ADR-0082 §2 no *amendment* qualifier is written on
a leading-token line; that section does not bear on the supersession token
itself, which is what ADR-0070 §4 puts there.

**ADR-0094 — its text is edited in place, because it is `Proposed`.** This is the
adjudication the lane owed and it comes out cheaply. ADR-0070 §1's append-only
protection is scoped by its own words to "**ratified** decision text — the
Context, Decision and Consequences", and §1 separates the two states explicitly:
"A substantive contract ADR is still reviewed while `Proposed` and ratified only
after … the ratifying edit records that review's outcome." A `Proposed` ADR is by
definition still in the state where review changes its text; ADR-0093's own
history is the corpus's demonstration, having been returned to `Proposed` and
then substantively rewritten before ratification. Appending a dated note to an
unratified document, to correct text nobody has yet accepted, would record a
history that did not happen.

So ADR-0094's live-rule sites are corrected rather than annotated. What was
edited, exactly:

- **§1's marked clause**, which named `Sensor` as the thing that is not an edge
  peer, now names `Reader`. This is the clause the collision cost, and it is the
  one a later lane acts on.
- **The prose in §1 and in the Context** stating ADR-0093's placement as current
  fact — that §2 "places concrete sensors in `ai_assistant/sensors/`" — now
  states the live package.
- **A dated header note** recording that this ADR renamed the seam and that the
  edit was made in place under the adjudication above, so the change is legible
  to a reader who saw the earlier text.
- **§11's classification block is left untouched.** It is a record of that lane's
  review history — an earlier draft that called a local file a "pull peer", found
  on the second adversarial round — and rewriting a historical narrative to use a
  name that did not exist when the events happened would falsify it.

**The sweep of ADR-0094 is deliberately not finished here.** Its remaining uses
of the seam's name are read under §1's substitution, exactly as ADR-0093's are.
Completing them belongs to ADR-0094's own lane at ratification, which is when
that document is re-read whole; a second lane rewriting an unratified ADR's prose
underneath the author who owes its ratification buys inconsistency for nothing.

**ADR-0094's ratification is not touched.** Its `Status` stays `Proposed`.

**Nothing else in the corpus is amended.** ADR-0008 §2 is cited in §3 as it
stands and its boundary is described rather than moved; ADR-0070 and ADR-0082 are
applied, not narrowed; ADR-0092's rulings are untouched, and nothing here creates
a dependency for the lane implementing them; `CONTRIBUTING.md` and
`CLAUDE.md` are cited as authority for the triad and are unchanged by this ADR
(§6 names their prose sweep as owed). ADR-0015 §5's two-stage sequence is obeyed:
this ADR merges before the triad lane starts.

## Consequences

- **The rename is free now and would not be later.** One ADR, no code, no
  migration. The triad lane builds `Reader` from the start.
- **"Sensor" is available to the peer layer**, which is what ADR-0094 §1's
  profile vocabulary wanted and what the roadmap's "sensors before actuators"
  pairing describes. ADR-0094 §1's disclaimer clause becomes a plain statement
  about process boundaries rather than a defence against a homonym.
- **The seam's weight is settled with an argument rather than an assumption.**
  The next lane that finds the triad heavy has a section to read and two
  structural grounds to answer, instead of re-deriving them from the gate going
  red.
- **What gets harder:** ADR-0093 must now be read with §1's substitution in
  hand — one indirection on the corpus's second-largest ADR. That is the price of
  not rewriting ratified text, and ADR-0070 §4's pointer mechanism is what makes
  it one hop rather than a search.
- **A visible inconsistency is created and deliberately not fixed here.**
  `VISION.md`, `docs/roadmap.md`, `CONTRIBUTING.md` and `CLAUDE.md` keep saying
  "sensor" for this seam until the sweep in §6 lands. Naming it is what keeps it
  from reading as an oversight.
- **Revisit when** a reader arrives whose source is not a file the hub can open —
  which ADR-0093 §5's fence already sends to its own decision — or if the
  dedicated-box direction is abandoned, which would restore the premise §2's
  rejections were re-tested against.

## Alternatives considered

- **Leave the name alone and let ADR-0094's disclaimer carry the collision.**
  Cheapest today and the cost compounds: every later ADR touching either layer
  re-states the disclaimer, and the one draft that forgot it produced a decision
  change dressed as an illustration (ADR-0094 §11). Rejected because the window
  in which the rename is free closes when the triad lands.
- **`Importer` instead of `Reader`.** Rejected in §1: it collides with
  ADR-0092 §6's import vocabulary the way `Sensor` collides with ADR-0094's, and
  it names a discrete act when the stronger surviving pattern is a continuous
  mirror.
- **Lower the seam's weight to an internal `readers/` seam with no triad.** The
  proposal this ADR was asked to enact. Rejected in §3 on two independent
  structural grounds — the triad is gate-enforced for every `core` Protocol, and
  ADR-0093 §2 forbids the subsystem imports an internal seam would require. The
  motivating premise, a shrinking category, turns out to argue the other way once
  the membership is corrected: two patterns are two implementations, which is
  when a conformance suite starts earning its keep.
- **Whole supersession of ADR-0093, restating its clauses under the new names.**
  Rejected in §7: ADR-0070 §3 refuses the relocation of ratified text, and a
  `Superseded by` token would misreport thirty live rulings as dead.
- **Amend ADR-0093 in place rather than supersede it.** Rejected in §7 as
  failing ADR-0070 §1's test on its face — a reader builds a differently-named
  Protocol in a differently-named package, which is a changed decision however
  small the edit. ADR-0082 §1's "the test controls, not the label" is the
  clause, and it is applied to this ADR before it is applied to anything else.
