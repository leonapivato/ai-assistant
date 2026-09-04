# 155. Residency governs the assistant's own store, and that store is never externalised

- Status: Partially superseded by ADR-0233 (§3's third clause, to the extent of the four conditions the commissioned approval surface states, and §4's marked no-mechanism clause, to the extent a recorded coverage makes the refusal mechanical; §3's second clause and every other clause of this ADR stand)
- Date: 2026-08-14
- **Partially superseded: 2026-09-04 by ADR-0233 — §3's third clause, in two of its
  sentences, and §4's marked clause, in one direction. Those two scopes, and nothing
  else in this ADR.** The owner ruled arm **(b)** on 2026-09-04
  (#1996), and ADR-0233 is the ADR that arm commissions: it designs the content-bearing
  approval surface, states its privacy consequences, and states four conditions on a
  call under which this clause no longer forbids a span.
  **The prohibition sentence is the first of the two.** "An egress span may not carry
  covered content all of whose covered paths contain a model call" acquires the
  exception those four conditions state, so a reader holding only this ADR would read it
  more widely than it now holds. That is a change a lane acts on differently, which
  ADR-0070 §1 puts on the supersession side of its line whatever the size of the edit —
  hence a partial supersession rather than the amendment an earlier draft of this record
  claimed.
  **The closing sentence is the second.** It reads *"An owner ruling alone does not
  relax this clause; relaxation requires the commissioned ADR and its approval surface,
  ratified, and **until then every lane implements the prohibition as written**."* That
  condition is now met, so "until then" stops running, and a reader holding only this
  ADR would read it as still running.
  **What this clause reserved was the route and not the relaxation**, which is why the
  record is a supersession and not a discharge: arm (b) commissions an ADR "under which
  a relaxation could **then be considered**", and considering it is what ADR-0233 did.
  **What is *not* changed, and a reader stopping at the qualifier will get this
  wrong.** Ratifying ADR-0233 relaxes nothing for any call: its condition is a
  property of a call — the call's coverage recorded on its binding, a per-call
  `CONFIRM` answered by the user, a confirmation that carried every span's own bytes
  under its surface floor, and those bytes bound by `parameters_digest` — so before
  that mechanism exists in code no call can meet it and this clause binds exactly as
  written.
  §3's **second** clause is untouched, unrelaxed and now *more* strictly enforced:
  ADR-0233 §6 makes a call any covered path of whose content contains no model call
  refusable at `EgressBinding` construction, which is the first mechanism any clause
  of §3 has ever had.
  **That mechanism is the second scope, because it is what §4's marked clause denied
  was possible.** §4 rules that "No lane, ADR or surface states or implies that §3 is
  enforced mechanically in this tree", resting on the observation that "Nothing in the
  payload path can distinguish a span drawn from the assistant's own store from one
  composed for the send". ADR-0233 §4 does not contradict that observation — it records
  the distinguishing fact **beside** the payload rather than seeking it inside one — and
  §6 then enforces §3's second clause on it. So the conclusion no longer holds whole and
  a reader of this ADR alone would read it over-wide.
  **The remainder of §4's clause binds entire, and it is the larger half.** ADR-0233 §6's
  fourth clause discharges this clause "only to the extent the value was honestly
  recorded": nothing detects a component that records the wrong coverage for a call
  carrying a store value, nothing inspects content to check a recorded state against it,
  and no bound in this corpus is obtained from a claim that something does. A lane citing
  ADR-0233 for more than that is citing it against its own text. §3's first, fourth, fifth and sixth
  clauses bind entire, and ADR-0233 is neither the export ADR §3's fifth clause
  reserves nor cited toward one. §4's marked clause is discharged only for spans
  whose coverage was honestly recorded, and ADR-0233 §6 says so in its own marked
  clause rather than claiming more. §4's *account of the tree* is unmarked and has
  since gone stale in two respects that change no obligation: `send_email` **is**
  now registered at the seam (`build_send_email_integration`, wired in
  `app/composition.py`), so #1154's stated trigger has fired, and `recall_memory`
  was removed by ADR-0208 §1.
- **Note (2026-08-14): ratified.** `Proposed` → `Accepted` on the repaired tree
  `953aec450d77`, printed round 25, churn ratio 2.8. Adversarial returned **APPROVE
  with no findings**, recording that it checked the repaired clause references and
  the carried-tier account against ADR-0146, ADR-0150, ADR-0152 and ADR-0154.
  Architecture's `blocker` — that ADR-0154 §6 carries three marked clauses — was
  **waived on the record**, not complied with: §6 spans ADR-0154's lines 1120–1213
  and carries four marked clauses, and that ADR's own ratification account binds
  "§6's four". The waiver and its grounds are recorded on PR #1153. Both lenses were
  re-run on the flipped tree for coverage.
- **This is the answer to #95.** ADR-0017 §1 deferred it at its own ratification;
  five ratified ADRs route to it and none answers it (ADR-0004, ADR-0017,
  ADR-0124, ADR-0146, ADR-0154); ADR-0154 §6's third clause makes it blocking for
  **any** registration at the now-designated `tools/` egress seam; and #1152
  records the registration lane stopping on it rather than reading an answer out of
  the corpus, which ADR-0154 §6's fourth clause forbids.
- **It partially supersedes ADR-0004 §2's residency clause, and it is a
  supersession rather than a clarification on purpose.** Read flatly the clause
  forbids every write-capable integration. This ADR does not explain that reading
  away — it replaces it, states what the clause governs instead, and states what
  refusing the flat reading costs (§1). ADR-0017 §5 refuses "a narrowing of a
  ratified clause presented as a clarification"; the instrument that is not that
  refusal is the one ADR-0070 §1 and §3 provide, and it is used here.
- **It is narrower in reach and stronger in force.** The flat reading forbade what
  nobody could obey and, by #95's own finding, still left a hole: assistant-derived
  state written into a connected service and excused because "the data now lives in
  the user's account". §3 closes that hole with a prohibition no authorisation
  cures. A reader checking that this ADR strengthens ADR-0004 §2's honest meaning
  rather than diluting it should read §1's rationale and §3 together — §3 is the
  half the clause never had.
- **§4 states what enforces §3 in this tree: nothing yet.** The finding is named
  with an issue (#1154) rather than smoothed, and the reason is structural — the
  marker the corpus has (ADR-0146's discloser provenance) records *who disclosed* a
  span, not *where it came from*, and the two questions come apart exactly on this
  line.
- **§3 defines one class and partitions only its governance.** §3's first clause
  defines **covered content**: a value obtained from any store under
  `Settings.data_dir`, and the output of any operation — model call or otherwise —
  supplied covered content, propagating through every operation without exception and
  decided at each supply site from recorded origin, never by inspecting content. §3's
  second clause forbids introducing covered content into an egress span wherever
  **any** of its covered paths contains no model call; §3's third clause forbids a span
  carrying covered content **all** of whose covered paths contain one. Content merging a
  raw record with model output has a non-model path, so the absolute clause holds it.
  The two quantifiers are exclusive and exhaustive, so nothing escapes both and no
  relaxation of the reserved clause can ever carry a direct store record out. No
  authorisation cures either.
- **The ordinary machinery is untouched**, because nothing on the send path
  *introduces* covered content: ADR-0150 §4 pins a span to a key of the request's own
  `parameters`, so the runner carries what was composed rather than adding to it, and
  the binder's connection read reaches the binding and the destination set, which are
  not spans.
- **§3's third clause is an interim, and only its relaxation is reserved to the
  owner.** Model-influenced content — the boundary twelve review rounds could not
  state a *permissive* rule for — is forbidden outright today. What an owner ruling
  decides is whether to ratify that permanently or to commission a later ADR designing
  a content-bearing approval surface compatible with ADR-0150 §10, under which a
  relaxation could then be considered — so **relaxation needs its own decision and its
  own mechanism**, and neither exists today. An owner ruling alone does not relax the
  clause. Earlier drafts reached the case by derivation, by a carve-out with its own
  antecedent, by an exception for the call's own recorded arguments, by a store
  partition, by a read-relation pair, by a persistence moment and by a chain limb with
  the model carved out of it; all seven were defeated in review, and §3 records how
  rather than quietly repairing it, because ADR-0098, ADR-0146 and ADR-0154 each made
  and corrected the first of them.
- **Adds no `core` surface.** No Protocol, no type, no field, no enum member. The
  recorded origin §4 finds missing is `core` surface and owes its own ADR (golden
  rule 5, ADR-0015 §5); §4 defers it with its trigger rather than specifying it.
- **Required review set: adversarial *and* architecture.** This decides the extent
  of a foundational privacy clause and gates every integration registration at an
  operational egress boundary. `CONTRIBUTING.md` makes a change contract-surface
  when it is the ADR deciding that surface, and ADR-0154 §8 took both lenses for
  the neighbouring decision on the same boundary.
- **Marked under ADR-0089**: every obligation is a marked clause and unmarked text
  supplies none. §8 records the count and the route.
- **Written to be overruled cheaply if the owner disagrees.** §1 carries the
  decision, the four readings that were available, and why each of the other three
  was refused, in one section, so that a reader deciding whether to overrule it
  reads one place. §1's last paragraph names which clause an overrule would have to
  move and which clauses survive every reading. Refs #95, #1152, #1096.

## Context

### The question, in ADR-0004's own words and #95's

ADR-0004 §2's first bullet:

> All persistent data lives on the user's machine, under a single
> platform-appropriate data directory (resolved via `platformdirs`, e.g.
> `~/.local/share/ai-assistant/` on Linux). No cloud storage by default.

Unqualified. #95 states the tension exactly:

> a write-capable integration puts data in a remote service by design. Creating a
> calendar event stores data in Google's calendar; sending an email persists it in
> a mailbox. Read flatly, the residency clause forbids every write-capable tool —
> which cannot be what ADR-0004 decided, since its own §3 provisions credentials
> for exactly those integrations and its §7 gates "every side-effecting tool call".

### Why the corpus could not answer it until now, and why it must now

ADR-0017 §1 was the first ADR with a reason to read the clause, and it declined in
terms: "answering it here would be narrowing a ratified clause this ADR does not
supersede, which is the move §5 exists to refuse. Issue #95." Its ground for the
deferral was stated beside it — "Nothing turns on it yet: no tool transmits, and
the seam stays undesignated until §3 holds."

#95 also records what that ADR's *removed* draft had said, and what adversarial
review of PR #72 said about it. The draft offered the reading that residency
governs where the assistant keeps its own state and not what a user's connected
service holds because the user asked for an action. Review called it "a narrowing
of a ratified clause presented as a clarification" and found a hole in it: "a tool
could persistently write assistant-derived *memory* into a calendar and claim
compliance, since the data now lives in 'the user's account'. That is cloud storage
of assistant state by another name, and the reading as drafted does not exclude
it." The paragraph was removed rather than left as an unratified reinterpretation.

Both halves of that finding bind this ADR. The route is forbidden — a reading
adopted by clarification is refused however long the argument for it — and the
consequence is defective on its own terms unless the hole is closed. §1 takes the
first seriously by superseding rather than explaining; §3 closes the second.

Three ADRs since have met the clause and each declined to read it, which is the
strongest available evidence that the question was real rather than pedantic.
**ADR-0124 §3** examined it for the overlay control plane, found "every sentence of
the residency clause stays true after this decision", and "sends the residual
question about residency's *intent* to **#95** … rather than narrowing or widening
it". **ADR-0123**'s classification list found it "not engaged" because the backup
tool writes to a local path and transmits nothing. **ADR-0146 §8** decided "nothing
about residency (#95)" in terms.

**ADR-0154 changed the facts, and it said which half of ADR-0017 §1's ground it
spent.** §6's #95 residue:

> Half of that ground is now spent. The other half is not: designation
> **registers no tool** (§2), so nothing transmits on this merge and no data
> reaches a remote service. What makes the question live is a **registration**, not
> a designation — and that is the point at which it is answered, by the lane that
> reaches it.

The lane reached it. #1152 records lane Y of this batch making ADR-0154 §6's first
statement — "**Yes — and on any other reading, unclear**" — and stopping, because
§6's third clause makes the consequent unconditional and §6's fourth clause forbids
reading an answer out of the designation. That stop was correct on the corpus as it
then stood: no reading of the clause was ratified, so *unclear* was the honest
answer and there was no lawful route to any other.

### What the clause's own words and rationale supply

Four things in the ratified text, none of which is an argument from convenience.

**The clause prescribes a location, and for a sent message the location it
prescribes is unreachable.** "under a single platform-appropriate data directory
(resolved via `platformdirs`, e.g. `~/.local/share/ai-assistant/` on Linux)" is a
sentence about where a store is kept. A message in a colleague's mailbox cannot be
brought into `~/.local/share/ai-assistant/`; there is no act that would make the
send compliant, only the act of not sending. A rule whose compliant state is
unreachable for a case is not a rule that decides the case one way — it is a rule
that has no application to it or that prohibits it outright, and the second is the
flat reading §1 refuses on other grounds.

**"No cloud storage by default" names an alternative to a data directory.** Cloud
storage is where a system keeps *its* store instead of keeping it locally. And "by
default" is the vocabulary of a configuration posture, which is incoherent about a
tool call: since ADR-0148 §3 and ADR-0154 §4 no egress call has a default at all —
every one is authorised by a fresh decision of the user about that call.

**§2's own structure already separates residency from transmission.** The section
is titled "Residency and egress" and carries three bullets: where data lives, which
component may send it, and telemetry. The bullet governing *sending* is the one
ADR-0017 §1 replaced and ADR-0154 §1 designated the second boundary under. Reading
residency to govern transmission as well would make ADR-0017's supersession
incomplete on its own terms: ADR-0017 granted that user data may leave the device
from a designated seam, and a neighbouring untouched clause would then revoke the
grant, because sending data to a service *is* causing that service to persist it.
The corpus cannot hold both, and ADR-0017, ADR-0124 §1 and ADR-0154 §1 are the
later, express decisions on that axis.

**ADR-0004's own Context says whose data the ADR is about.** "The assistant's value
comes from knowing its user deeply … That makes **the data it holds** among the most
sensitive a person owns," and "`memory/`, `tools`, and `permissions` all depend on
how we classify, store, protect, and expose this data." The subject throughout is
the store the assistant accumulates.

### The property residency protects, which is what decides the line

Residency is not a preference for local disks. It is what makes ADR-0004's other
guarantees reachable: §4's at-rest posture applies to a directory, §6's view,
export and delete rights are exercised over a store, §7's audit trail is a Tier 1
store beside it, and ADR-0126 gives §6's delete right a surface by destroying the
contents of `Settings.data_dir` with the hub stopped. Every one of those is an act
on **one place on one machine the owner controls**.

So the property is: *the owner can enumerate, inspect and destroy everything this
system has accumulated about them by acting on a machine they hold.* ADR-0123
states the same property from the other end when it says the leg's exit test is
"losing the laptop does not lose the model", and that "the model is the accumulated
Tier 1 record (ADR-0004 §1)".

That property tells us precisely where the line falls, and it tells us both halves
at once.

- It is **destroyed** when assistant-derived state is written into a connected
  service. Emptying `data_dir` does not delete a memory record copied into a
  calendar; the owner's delete right stops at the machine boundary and the
  accumulated model has acquired a second custodian nobody can reach. This is #95's
  hole, and the property names why it is a breach rather than a technicality.
- It is **not touched** when the owner directs a message to a recipient. The
  accumulated model stays exactly where it was; what left is content for that send,
  and this system's record of having sent it — the decision, the binding, the
  claimed step, the audit row — stays in `data_dir` under §6 and §7.

The distinction #95 proposed on intuition — "data the user authored or explicitly
requested be sent, versus assistant-derived state being externalised" — is the
distinction this rationale produces. It is adopted here because the clause's own
purpose yields it, not because it is the convenient place to stop.

## Decision

Marked under ADR-0089: every obligation this ADR imposes is a marked clause, and
unmarked text supplies none.

### 1. What the residency clause governs — and the three readings that were refused

> **Normative.** ADR-0004 §2's residency clause — "All persistent data lives on the
> user's machine, under a single platform-appropriate data directory … No cloud
> storage by default" — governs **the assistant's own store**: the persistent data
> this system keeps on the owner's behalf, under the data directory
> `Settings.data_dir` resolves. That store lives on the owner's machine, under that
> one directory, and no component of this system places any part of it in a service
> another party operates — save to the extent an ADR reserved by §3's fifth clause
> permits, which is the only exception to this clause and to §3's second.

> **Normative.** Whether a value belongs to the assistant's own store is decided by
> **where this system persists it**, never by what it contains and never by how
> sensitive it is. A record in any store this system writes under
> `Settings.data_dir` belongs to it, whatever that store is called and whenever it
> was added. A value this system does not persist is not made part of it by
> resembling one.

> **Normative.** The residency clause does not govern the persistence a connected
> service performs as the ordinary consequence of an egress call authorised under
> §2. A copy retained by the service the call reaches, by the owner's own connected
> account, or by a recipient's provider is outside the clause's scope. No lane reads
> the clause as permitting, forbidding or conditioning such a call: whether one may
> happen at all is ADR-0017 §1's rule as ADR-0124 §1 restates it, and every
> condition on one is ADR-0017 §3's and ADR-0148's.

**The second clause is stated over where a value is persisted because an
enumeration would drift, and the corpus has measured the drift.** ADR-0123's
Context records that ADR-0083 counts five databases in the data directory three
times over, that `app/composition.py` opens seven, and that "the count in the most
authoritative document about the data directory is already wrong by two, and
nothing detected it". A clause listing the stores would be wrong by the same two on
the day it merged and by more later, and the failure would be silent in the
permissive direction — a store added next month would not be covered. Keyed on
where a value is persisted, the clause covers a store nobody has written yet.
Memory records, beliefs, episodes, user-model facts, evaluation traces, audit
records, plans, conversation records, deferrals, source grants and connection
records are all inside it today; that sentence is an illustration and obligates
nothing.

**The first clause carries the export exception inside itself, and it had to.** An
earlier draft stated the prohibition unconditionally here and reserved the exception
in §3's fifth clause alone. Adversarial review found on round 1 that the pair left
the reserved ADR with no lawful outcome: an export it permitted would satisfy §3 and
still breach §1, so the route §3 offers would have been unreachable without
superseding a clause that never mentioned it. That is ADR-0089 §3's requirement
arriving on this document — "A marked clause states its own scope, its conditions
and its exceptions" — and the repair is to name the one exception in both clauses
rather than to widen either. Nothing else moves: the exception is still available
only to an ADR that decides the export in its own text and decides ADR-0004 §6's
reach for it.

**The third clause is what the flat reading loses, and it is worth being exact
about what it costs.** Under a flat reading the owner would have an absolute
guarantee: nothing this system does causes any of their data to sit on anyone
else's machine. That is a stronger promise than the one this ADR leaves, and
refusing it is a real reduction in reach, not a discovery that the clause never
meant it. What the refusal buys is a rule the system can actually keep — and, in
§3, a prohibition the flat reading's own hole made unavailable.

#### The four readings, and why the other three were refused

This subsection is the audit trail for the decision and is **not normative**
(ADR-0089 §1). It is written so that a reader deciding whether to overrule the
clauses above can see the whole field in one place.

**(A) The flat reading — residency governs all data the system causes to be
persisted anywhere.** Refused on three grounds, of which the third is decisive.

1. It is internally contradicted by ADR-0004 itself. §3 provisions credentials for
   calendar, email, GitHub and messaging integrations; §7 gates "every
   side-effecting tool call" — a gate over an act the same ADR forbids outright is
   not a design; and its Consequences provision for "the designated `tools/`
   integration boundary" importing network clients. #95 makes this point first.
2. It prescribes an unreachable compliant state for the cases it would decide, as
   the Context sets out.
3. It contradicts three later express decisions on the transmission axis — ADR-0017
   §1's rule, ADR-0124 §1's three boundaries, and ADR-0154 §1's designation of
   `ai_assistant.tools.egress`. Read flatly, residency revokes a permission the
   corpus has ratified and attested against fourteen conditions. Two ratified rules
   cannot both hold, and the flat reading is the one that was never argued for.

**Its honest attraction, stated rather than dismissed:** it is the reading with the
strongest guarantee and the one a privacy-minded reader would want to be true. The
reason it is refused is not that it asks too much of the implementation; it is that
it was never a live rule — it has been contradicted by its own ADR since
ratification, which is what ADR-0017 §1 calls "a contradiction ADR-0004 has carried
since ratification" about the neighbouring bullet.

**(B) The removed-draft reading — residency governs the assistant's own state, and
what a connected service holds because the user asked for an action is simply
outside it.** Refused as a complete answer and refused as a route.

- **As a complete answer**, it is the reading #95 shows has a hole: the memory
  record written into a calendar is "the assistant's own state" *and* is now held by
  a connected service because a call was made, and the reading as drafted does not
  say which limb wins. §1's first clause and §3 together are what (B) lacked — the
  store is defined by where this system persists it, and placing any of it in a
  service is prohibited outright rather than being excused by the account it landed
  in.
- **As a route**, it is unavailable at all. Adopting it by clarification is what
  ADR-0017 §5 refuses, what ADR-0017 §1 declined, and what ADR-0154 §6's fourth
  clause forbids sourcing from the designation. This ADR reaches a related
  conclusion by the only lawful instrument — ADR-0070 §1's supersession — and §5
  performs it.

**(C) Per-integration adjudication — no general rule; each registering lane argues
the clause afresh.** Refused. It is the state the corpus has been in, and its cost
is on the record: five ADRs routing to an unanswered issue, and a registration lane
correctly refusing to proceed (#1152). It also produces a rule nobody can design
against in advance, so a lane cannot tell before writing a tool whether the tool is
permissible, and it makes the answer depend on who is asking. ADR-0154 §6 already
requires a per-integration *statement*, and §6 below keeps it; what (C) would add
is a per-integration *decision*, which is what a general rule exists to avoid.

**(D) Residency governs everything, and a write-capable integration requires the
owner to flip "no cloud storage by default".** This is the most plausible reading to
overrule toward, because "by default" invites it. Refused because it would be
strictly weaker than what the corpus already has. A configuration flag is a standing
authorisation set once; ADR-0154 §4 has already ruled that no standing authorisation
covers an egress call at this seam, and ADR-0148 §3's route (a) makes every send a
fresh decision of the user about that call, against a payload description and a
canonical destination set. Replacing a per-call decision with a settings toggle is
the trade ADR-0021 §5 and ADR-0148 §8 both declined in the safe direction, and
ADR-0098 §3's reasoning about standing authorisations applies with full force. (D)
also does nothing about #95's hole: a flipped flag would authorise the memory record
in the calendar exactly as it authorises the email.

#### If this is overruled

The clauses are severable and it is worth saying which way. **§3 holds under every
one of the four readings**, including (A) *a fortiori* — no reading of the residency
clause permits the accumulated model to be relocated into a third-party service. An
overrule that prefers (A) or (D) would move §1's first and third clauses and §2, and
would leave §3, §4's finding and §6's per-integration statement standing. The
supersession mechanics for doing so are ADR-0070 §1 and §3, and ADR-0082 §1 and §2
govern where the record goes; nothing in this ADR is written in a way that would
have to be unpicked to reach a different answer on §1.

### 2. What leaves legitimately: owner-directed content, per call, through the designated seam

> **Normative.** Content may leave the device through the designated `tools/` egress
> seam (ADR-0154 §1) only as the payload of an egress call authorised whole, per
> call, by a decision of the user about that call — ADR-0148 §1's single route, §3's
> route (a), §4's whole-set rule and §8's approver, with ADR-0154 §4's floor closing
> the standing route. This clause states which content the residency clause permits
> to be in such a payload and nothing about who may receive it; it adds no route,
> relaxes no condition of ADR-0017 §3 and authorises no call ADR-0148 does not
> already authorise.

> **Normative.** The content that clause admits is content composed for that call:
> the owner's own words, and content this system composed at the owner's direction
> for that send. It is subject in every case to §3, which no authorisation cures.

**Why this is the owner's act and not this system's disclosure of its store.**
ADR-0148 §8 makes the approver the user, reached by a `CONFIRM` that parks the step
and is answered through an interface, "never by the turn on the user's behalf".
ADR-0148 §3's second clause refuses every near-miss that would let something other
than a user act authorise a recipient — a tool's declaration, a credential's
audience, a configured host, an assembled allowlist, a recipient from a prior call,
and a destination this system extracted from a span it selected. ADR-0154 §4 closes
the standing route at this seam and states the floor over a fact an authoriser can
evaluate. So every send is a recorded decision of the owner, about that call, over a
canonical destination set and a payload description the owner is shown. That is what
makes the resulting persistence at the far end the owner's disposition of their own
content rather than this system relocating its store.

**Discloser provenance does not decide §2's line, and confusing the two is the
error this ADR most wants to prevent.** ADR-0146 §1's second clause classifies a
span by *who disclosed it*: user-authored, or system-selected in every other case
"including a span this system's own model authored and a span the system retrieved
from its own stores". Under it a body a model drafted for this send is
**system-selected**, and a memory record recited into a body is **system-selected**
too. §2 admits the first and §3 forbids the second, so the two axes cross here:
ADR-0146 answers *whose words these are*, and §§2–3 answer *where the content came
from*. Both are useful and neither substitutes for the other — which is exactly why
§4 finds no mechanism in the tree.

**Nothing here is read onto `models/`.** ADR-0017 §2 adds no precondition to
`models/` and ADR-0146 §6's second clause repeats it; this ADR imposes none either,
and §7 forbids citing it toward one. What `models/` may transmit and to whom is
ADR-0004 §2's egress bullet as amended and as superseded by ADR-0017 §1, untouched.

**Why the permission is stated on the composing component rather than on the
seam.** §2's second clause is decidable where it is written: the component
assembling an argument knows whether it drew the text from a store read or composed
it for the send, which is a fact about what it did rather than an inference about
what the text is. That is ADR-0146 §3's shape — keyed on what a component *holds
as* Tier 0, "not on what a span contains, because the second is the unobtainable
bound" — and ADR-0098 §12's constraint that "whatever is decided has to be decidable
from recorded origin". §3 carries the same rule as a prohibition, which is the
checkable direction and the one a reviewer can test a change against.

### 3. The hard line: assistant-derived state is never externalised

> **Normative.** **Covered content** is: a value any component obtained from a store
> this system keeps under `Settings.data_dir`; and the output of any operation — a
> model call or any other — to which any component of this system supplied covered
> content, under any parameter and whatever that parameter is named. The class
> propagates through every operation without exception; what varies below is only which
> clause governs its reaching an egress span. A **covered path** of a piece of covered
> content is a path by which it derives from such a store: the value itself, where a
> component obtained it from the store; and otherwise, for an operation's output, each
> path continuing back through each covered input that operation was supplied. Content
> may have several covered paths, and they need not be alike. Membership and the
> character of each path are decided at each supply site from recorded origin — a
> component that knows its inputs' membership knows their paths' character, which is
> three-valued at every supply: covered with a model call on the path, covered with
> none, or not covered — and never by inspecting content for resemblance, which is the
> unrecoverable relation ADR-0098 §5 and §12 forbid deciding on.

> **Normative.** No component introduces covered content into a span of an egress call
> at the designated `tools/` egress seam, wherever **any covered path of that content
> contains no model call**. This holds at any moment and by any route, whether the
> content travels verbatim or as a copy, an excerpt, a re-encoding, a rendering, a
> summary or a translation. No authorisation cures it, and its only exception is the
> export ADR this section reserves below.

> **Normative.** An egress span may not carry covered content **all of whose covered
> paths contain a model call** — wherever on a path that model call sits, upstream or
> downstream of any other operation. What is reserved to an owner ruling is whether to
> **(a)** ratify this clause as permanent, or **(b)** commission a later ADR that
> designs a content-bearing approval surface compatible with ADR-0150 §10 and states
> its privacy consequences, under which a relaxation could then be considered. **An
> owner ruling alone does not relax this clause; relaxation requires the commissioned
> ADR and its approval surface, ratified, and until then every lane implements the
> prohibition as written.** No lane, reviewer or later ADR makes that choice without an
> owner ruling, and this clause is deliberately the more restrictive reading.

> **Normative.** No authorisation makes a transmission either prohibition above
> forbids lawful. A per-call user
> decision under ADR-0148 §3 does not; a standing user policy does not, and
> ADR-0154 §4 admits none at this seam in any case; and neither a configuration, a
> connected account, a tool declaration nor an approved payload description does.

> **Normative.** The one exception available is an ADR deciding in its own text that
> the owner may export the accumulated model into a service the owner names, which
> may permit what the second clause above and §1's first clause forbid, only to the
> extent it decides, and which decides the reach of ADR-0004 §6's export right for
> that act rather than inheriting one.

> **Normative.** No lane reads this ADR, ADR-0004 §6, ADR-0073 §10's deferred
> `export` command, ADR-0007's `MemoryStore.export`, or ADR-0123's backup artifact
> as being, or as authorising, the ADR the clause above reserves the exception to.

**The first clause is stated over what a component obtained and supplied, and an
earlier draft stated it over "an artifact derived from one" — which is the bound
this corpus has already ruled nobody may state.** Architecture review found it on
round 2 of the loop, and it is the most valuable finding this document received. A
model handed recalled memory and asked to draft a message produces a body, and no
component can tell which of its words derive from which of the model's inputs;
ADR-0098 §5 holds that "produced from external content" is "**not recoverable** once
a model's output has been recorded truthfully", and §12 makes the constraint general:
"whatever is decided has to be decidable from recorded origin". A rule two conforming
implementations answer oppositely is not a contract the seam can extend against.
ADR-0154 §4 was corrected for the identical defect on its own round 6, ADR-0146 was
corrected for it twice, and ADR-0098 §3 records the corpus making it and fixing it
before either. **The pull toward it is a property of writing about this subject**, so
it is recorded rather than quietly repaired.

**The class is defined once and only its governance is partitioned, which is what
rounds 19 and 20 forced.** Earlier drafts wrote the propagation into the prohibition
itself and then carved the model call out of it, and that entangled two different
questions: *what is covered* and *which clause governs it*. Every version of the
entanglement leaked. A limb reaching only an operation directly supplied a store value
was defeated by inserting a second one — record to formatter A, A's output to formatter
B, introduce B's output (architecture, round 19). Closing the chain but carving the
model call out broke propagation at the model boundary in both directions: a store-fed
model reply passed to a formatter before the span (both lenses, round 20), and a
formatter's output fed *into* a model call, which the model clause's own predicate did
not reach. Defining **covered content** once, with propagation through every operation
and no exception, removes the seam rather than patching it: there is no boundary left
for the class to stop at.

**The two prohibitions partition that class exhaustively, and the quantifiers are what
make it a partition.** Content is covered by several paths at once whenever an operation
merges inputs, so a predicate written over "the" chain would leave the merged case
claimed by both clauses. Architecture review found that on round 21. Quantified, the
conditions are mutually exclusive and jointly exhaustive by construction: either **some**
covered path contains no model call, or **every** covered path contains one, and never
both. §3's second clause governs the first, §3's third the second, so **no span carrying
covered content escapes both** — which answers rounds 19, 20 and 21 by construction
rather than by another patch.

**The overlap falls to the absolute clause, and that is the strict reading.** An
operation combining a raw memory record with model-produced content yields output with a
non-model covered path — the record's — so §3's second clause holds it, absolutely and
with no reservation. That matters for what an owner can later do: because one non-model
path suffices to keep content under the absolute clause **forever**, a relaxation of the
reserved clause can never carry a direct store record out with it. The reserved fork
therefore reaches exactly the model-influenced subclass and nothing adjacent to it —
upstream and downstream variants alike, wherever on a path the model call sits — so an
owner relaxing it later relaxes the whole of what they were asked about and only that.

**Decidability is per supply site and unchanged.** A component knows whether what it is
handing to an operation is covered, because it knows where it got it; nothing here asks
whether a span's text *resembles* a stored record, which is the relation ADR-0098 §5
holds unrecoverable and §12 forbids stating a bound over. **#1154** remains the gap
between a rule authors and reviewers are bound by and a mechanism that enforces it, for
both clauses equally.

**The clause reaches #95's case whole, and reaches it without a time test.** #95's
case is a *component* act — "a tool could persistently write assistant-derived
*memory* into a calendar and claim compliance" — and it is forbidden absolutely,
including the evasion of routing the record through a summariser first, because the
store value was supplied to an operation whose output the component then introduced.
No moment qualifies the prohibition, so there is no window in which the same act is
lawful, and no store is excepted, so there is no store to launder through.

**Why the ordinary machinery is untouched by a rule this broad.** The clause binds a
component that *introduces* a value, and the two reads the pipeline performs on the
way to a send introduce nothing.

- **The runner introduces nothing.** ADR-0150 §4 pins a span to the pair
  `(argument, index)`, where `argument` "is a top-level key of the request's
  `parameters`" — so the spans of a call *are* its arguments, decomposed. Reading the
  step back and passing its parameters to the binder therefore carries what was
  already composed into the request rather than introducing anything into a span, and
  `EgressBindingSeam._spans_of` derives every span from those same arguments. A
  component that adds nothing adds nothing under this clause either.
- **The binder's connection read reaches the binding, not a span.** What
  `EgressBindingSeam` takes from the connection record is the account identity, and
  what it builds with it is the binding and the canonical destination set — the
  addressing of the call. A destination is not a span of the payload, and this clause
  is stated over spans. So the ordinary bind is outside it as written, with no
  exception needed and none granted.

That is the whole reason this maximally restrictive rule is compatible with §2 and
with §6's fourth clause: **`send_email` sends what was composed for the send**, and
nothing on its path introduces a stored value into a span.

**The boundary this document does not decide, and why it is the owner's.** Rounds 4
through 15 of this document's review loop worked the line between a store value a
component routes into a span and store content that merely shaped what a model wrote,
and every formulation of that line was defeated. The record is on PR #1153 and is
worth keeping as evidence rather than summarising away: a carve-out with its own
antecedent (rounds 4 and 6), a derivation test the corpus forbids (round 2,
architecture), a stage predicate with no determinate boundary (round 7), a
construction moment that was satisfiable before anything was recorded (round 8), an
exception for the call's own recorded arguments that could not be stated without
either excusing a laundering route or forbidding the ordinary path (rounds 9 through
13), a store-scoped partition that `PlanStore.get_plan`'s arbitrary `plan_id` defeated
(round 14), and a read-relation pair whose granularity did not match the store APIs
(round 15, adversarial). Round 15's architecture finding closed the circle from the
other side: any rule whose coverage begins at a moment leaves the pre-moment planner
route open.

Twelve rounds is enough evidence to conclude something other than "try again". The
two remaining rules are stated in the clause above and they differ on a question no
ADR in this corpus settles: whether an assistant drafting outbound content *from what
it knows about its owner, at that owner's request* is the product working or the
protection failing. That is a question about what this system is for. It is reserved
to the owner by name, the more restrictive reading governs meanwhile, and no lane
resolves it by writing a fourteenth formulation.

**The reserved clause is a reservation, not a disposition, and the difference is the
point.** Architecture review on round 3 required the model-context case to have one
explicit disposition rather than being left outside §3 while §2's general permission
reached it, and every disposition attempted since was defeated. What it has now is
stronger than the "accepted residue" earlier drafts offered: the case is **governed**
by the clause above — the restrictive reading — rather than left to §2, and what is
open is only whether the owner relaxes it. A reader who wants to know what a lane may
do today does not need the fork resolved; they need the clause above, which is
unconditional.

**Why the clause defines its own scope for a word the codebase already uses.**
"Context" is a parameter name in this tree: `ModelBackedPlanner.plan` takes `context:
CurrentContext` *and* `memories: Sequence[MemoryRecord]` as separate arguments, and
`ConversationLoop` passes recalled records under the second. A clause saying "whose
context carried store content" could therefore be read as reaching only the first
argument, and an email body drafted from records passed as `memories` would slip the
rule entirely. Adversarial review found exactly that on round 17. ADR-0089 §3 requires
a marked clause to state its own scope rather than borrow one, and this is the case
that shows why: the borrowed word had a narrower meaning waiting for it in the code.
The clause therefore reaches every value supplied to the call and says so.

**What the reservation now costs, which is more than the first draft of it did.** An
earlier draft of this clause offered relaxation as a live option, premised on the owner
reading the payload at confirmation. Architecture review found on round 17 that the
premise contradicts the corpus: ADR-0150 §10 makes the payload description hold no
content, so the confirmation carries spans, extents, provenance and destinations and
never the body. An owner cannot recognise their own memory in a body they are not
shown, and a reservation resting on that mechanism would have reserved something
unreachable. So relaxation is no longer an arm the owner can simply take. Arm (b)
commissions a *mechanism* — a content-bearing approval surface that does not exist,
compatible with a clause that currently forbids one, with its own privacy consequences
to state — and only then could a relaxation be considered on top of it. **The
relaxation arm now requires its own decision and its own mechanism, neither of which
exists today**, which makes the interim clause considerably harder to displace than
the draft that merely called it interim.

**Both arms were reachable and neither is obviously right, which is why the choice is
the owner's.** Ratifying the interim is decidable from recorded origin — whether store
content was supplied to a model call is a fact about the request, not an inference
about the output, so nothing in ADR-0098 §5's unrecoverability bars it; its cost is
that the assistant may not draft outbound content from what it knows about its owner,
which is the "false on the day it is written" shape ADR-0146's Context refuses.
Commissioning the surface keeps that capability available but buys it with a new
content-bearing approval path, and content in an approval surface is itself a privacy
decision with its own blast radius. Both costs are real and they fall on different
things — one on the product, one on the protection — which is exactly the trade an
owner makes and a lane does not.

**Gating registration until the fork resolves was considered and refused.** ADR-0154
§6's bar is "until an ADR has answered #95", #95's question is the residency scope
question §1 answers, and this ADR answers it. Holding registration open for the fork
as well would gate it on a ruling nobody has asked the owner for, and — under the
clause above — would gate it while the restrictive rule is already in force. The
recorded origin **#1154** carries remains what would let a *mechanism* enforce any of
this; §4 names it with its trigger, and it is orthogonal to the fork.

**This is the clause the removed draft did not have, and it is why this ADR is a
strengthening.** #95's hole was that a reading confining residency to the
assistant's own state says nothing about that state being *moved* — a tool writes a
memory record into a calendar and the reading has no sentence to refuse it with,
"since the data now lives in 'the user's account'". §3's second clause refuses it
directly, and its own words refuse the excuse: the account it lands in is not a
defence, and neither is the owner having pressed *yes*.

**Why a per-call user decision cannot cure it, which is the part most likely to be
argued with.** ADR-0148 §8's fourth clause fixes what the owner is shown: the
connected account's identity, the canonical destination set in both forms, and the
payload description. ADR-0150 §10 makes the description hold no content. So the
question actually put to the owner is *send this many characters, from these
arguments, to these recipients* — a question about a message. The question §3 is
about is *relocate part of your accumulated model into a service you do not
administer, permanently, beyond the reach of the delete right ADR-0004 §6 gives you*.
Those are different decisions with different consequences and different durations,
and the first does not contain the second. Treating an answer to the first as an
answer to the second is the shape ADR-0097 §7 already named and refused on a
neighbouring seam — "the floor satisfied by a consent the user gave about something
else entirely".

**And the consequence is irreversible in the one direction that matters.** A message
the owner sends can be regretted; the accumulated model placed in a third-party
service cannot be recovered, because ADR-0126's destruction of `Settings.data_dir`
does not reach it and nothing else does. ADR-0004 §6's rights and ADR-0126's act are
the guarantees residency exists to make reachable, and §3 is what keeps them
reachable once a boundary that can send to an arbitrary third party is operational.

**The third clause leaves the export question open with its shape rather than
closing it.** An owner may legitimately want their memory in a service they chose,
and nothing here calls that illegitimate. What it may not be is a side effect of a
send. ADR-0073 §10 defers an `export` command as an implementation question over
`MemoryStore.export`, which produces portable JSON *for the owner*; that is a local
act and this ADR does not disturb it. ADR-0123 §11 writes an encrypted artifact to a
local path and leaves the operator's carrying it elsewhere as the operator's own
act — also untouched, and §7 says so. What would be new is this system placing store
content into a service, and that needs an ADR that faces the delete-right question
head-on.

### 4. What enforces §3 in this tree today, and what does not

> **Normative.** No lane, ADR or surface states or implies that §3 is enforced
> mechanically in this tree. Nothing in the payload path can distinguish a span
> drawn from the assistant's own store from one composed for the send, and no clause
> of this corpus is satisfied, and no bound in it obtained, by a claim that
> something can.

This section is otherwise an account of the tree and is **not normative**
(ADR-0089 §1). It was verified by reading `origin/main` at `9a401306`, not by
transcribing a prior ADR's summary.

**Two absences, and both clauses are statable — what neither has is a mechanism.**
§3's second clause is **statable and unenforced**: it is decidable at the component, a
reviewer can test a change against it, and what is missing is enforcement. §3's third
clause is **also statable**, and that is the change rounds 17 and 20 forced into the
open: both are stated over §3's first clause's *supply-site* class, over what a
component supplied to what, which is a fact about the request. What remains
unrecoverable is the different relation
ADR-0098 §5 and §12 name — whether a particular span's content was *produced from* a
particular input — and no clause here is stated over that. So the two clauses differ
in what they reach, not in whether they can be said. Issue #1154 carries the
payload-origin mechanism that would let code enforce either, which is why its trigger
is written where it is rather than at the first externalisation.

**What holds today, and it is a fact rather than a control.** No tool is registered
at the seam: `build_default_registry` in `ai_assistant.tools.builtin` returns
`CURRENT_TIME` and `RECALL_MEMORY` and nothing else, `app/composition.py` builds an
empty `RegistrationTable`, and `SendEmail.__call__` refuses. Nothing transmits, so
nothing can externalise anything. ADR-0154 §2 states this and it is not a property
§3 can rest on, because the registration lane is next.

**What holds after a registration.** Two real controls and one absence.

- The payload is the arguments and there is no second copy.
  `EgressBindingSeam._spans_of` in `ai_assistant.tools.egress_binder` derives every
  span from the call's own arguments; `SmtpEgressTransport._check_spans_cover`
  refuses a text span the approved description does not cover and `smtp_message`
  refuses an argument key the seam does not transmit. So store content cannot reach
  the wire except through a declared argument the owner was shown a description of.
- Every send is a fresh user decision (§2). The owner sees the destination set and
  the description.
- **Nothing reads where an argument's text came from.** `DiscloserProvenance` in
  `ai_assistant.core.types` has two members, `USER_AUTHORED` and `SYSTEM_SELECTED`,
  and neither is "obtained from the assistant's store"; `AttemptRunner._bound` in
  `ai_assistant.orchestration.runner` passes `CarriedProvenance(spans={})`
  unconditionally, so every span the seam describes today is `SYSTEM_SELECTED`
  regardless; and no gate consults a span at all — `.spans` is read nowhere outside
  `core/types.py`, `tools/egress*` and `testing/egress.py`, and `permissions/`
  contains no reference to a span's provenance or tier.

**So the honest answer to "what refuses a `SYSTEM_SELECTED` span sourced from the
store reaching an egress payload, today, in code?" is: nothing.** The owner's
`CONFIRM` is the only control, and it is shown a description that states the span's
argument, position, extent and discloser provenance — and *not* where the content
came from. A memory record recited into `body` and a paragraph the model wrote for
the send are described identically, because ADR-0146's axis does not separate them.
ADR-0146 §5's third clause obliges better than that and no mechanism delivers it,
which is a gap rather than a licence, and two ratified ADRs already record it as one
(ADR-0150 §6, ADR-0152 §12). That clause rules on this case directly: moving a value
"into a field that establishes none … does not relieve the implementation of
describing it at its tier". So a value this system holds as Tier 1, recited into a
body field, is *owed* a description at its tier — and what the owner is shown today
states an extent and a provenance and no tier, because the description's determinism
inputs cannot produce one. ADR-0150 §6 declines to close that and names the lane
owing the mechanism, a recorded per-span classification carried from selection; and
ADR-0152 §12's third clause states that nothing since has discharged it. The
absent machinery is the same recorded-origin machinery **#1154** carries for §3,
which is why the two residues have one shape and one remedy. ADR-0154 §6 carries
both and this ADR closes neither.

**Two concrete paths, and §3 answers them differently — a registration lane should
not confuse them.** `recall_memory` is registered today and returns matching records
to the turn as JSON.

- **A turn that recalls and then sends.** `ConversationLoop` supplies the records to
  the planner's model call, so that call's output is covered content whose every
  covered path runs through that call, as is anything a later operation derives from it
  alone. §3's **third clause** forbids it reaching a span — no component needed to
  route an extractable value, which is the point. An owner ruling may later ratify that,
  or commission the
  approval surface under which relaxing it could be considered; a lane may not read
  the reservation as a permission now.
- **A component that reads a store and introduces the value, or the output of any
  chain of operations it fed that value into, into a span**, where some covered path
  of what it introduces carries no model call — including content merged from a raw
  record and a model output. Any store, at any moment and to any depth, whether during
  that step, an earlier step of the same plan, or before any plan existed.
  §3's **second clause**, forbidden absolutely, and **no code checks it**. That is the
  gap #1154 carries.

The two differ in **whether every covered path runs through a model call or some path
does not**, which is the predicate the two clauses partition on, and they are not
opposite in disposition today: the first is forbidden by the interim clause with its
relaxation reserved to
the owner, the second is forbidden outright with no reservation at all. That is why
the enforcement point is worth its own issue rather than a note. Nothing in the
payload path records the fact: `EgressBindingSeam._spans_of` derives spans from
arguments and knows nothing about how those arguments came to hold what they hold,
and no supply of covered content is correlated with a span anywhere. The fact is
*recordable* — which is what makes #1154 a mechanism question rather than another
unrecoverable relation — and it is not recorded.

**What closing it would take, and why this ADR does not specify it.** It wants a
**recorded origin** carried with a span — the same discipline ADR-0098 §12 requires
of an answer ("a fact the request carries, never an inference about how a model
produced it") and ADR-0146 §2 requires of provenance ("decided by recorded origin,
never by inspecting a span"). That is `core` surface: either a third state on the
provenance marker or a field beside it, plus whoever stamps it. Golden rule 5 and
ADR-0015 §5 put it in its own ADR, and ADR-0073 §4's standing test — decided "with a
producer in hand" — is unmet while no tool is registered, which is the ground
ADR-0146 §8 used to defer the marker itself.

**Filed as issue #1154 rather than left in prose**, so it is tracked where a lane
will meet it: the gap is recorded there with §3 as its rule, ADR-0152 §5's
provenance residue and ADR-0146 §5's third clause as its neighbours, and **its
trigger is the first lane that registers an integration whose declared arguments
admit free text**. That is a strictly earlier trigger than "the first
externalisation", which is the point of stating it.

**Why §3 is worth ratifying with no mechanism behind it.** ADR-0017 §4's honest
accounting is the precedent — "an import contract is a net, not a proof" — and so is
ADR-0146 §7, which states a residual the posture does not detect and forbids anyone
claiming it does. A rule an author and a reviewer are bound by is worth more than
silence, and it is what a later mechanism will be built to enforce. What would not
be worth having is the same rule with a claim of enforcement attached, which the
marked clause above forbids.

### 5. The supersession, and every other ADR classified

> **Normative.** This ADR **partially supersedes ADR-0004 §2's residency clause**
> and nothing else of ADR-0004. §2's egress clause is ADR-0017 §1's and stays so;
> §2's telemetry clause, §2's configured-set amendment, §1's tiers, §3's secrets
> rule, §4's at-rest posture, §5's logging and redaction, §6's data rights and §7's
> gate and minimisation rule are untouched, and no lane cites this ADR toward any of
> them.

> **Normative.** ADR-0119 §12's clause — "No `EvaluationTrace` leaves the device, by
> any route, under any setting" — is stricter than §3 and is untouched by it. No
> lane reads §2 as opening a route for a trace, and no lane reads §3, whose subject
> is the `tools/` seam, as narrowing §12 to that seam.

> **Normative.** No clause of this ADR states or implies that this system can reach,
> bound or destroy a copy a connected service or a recipient's provider holds.
> ADR-0004 §6's rights reach this system's own store; they do not reach a message
> the owner has sent, and no lane reads §1 or §2 as a claim that they do.

**The edits this change makes outside its own file are two, both on ADR-0004.** Its
`Status` line accumulates one `ADR-0155 (<scope>)` pair, and its header gains one
appended dated note recording what is replaced and what is not. **No accepted text
of ADR-0004 is rewritten anywhere** — §2's residency bullet is left exactly as
ratified, because a reader must be able to see the clause this ADR replaces and
judge the replacement against it (ADR-0070 §1; the form ADR-0017 §7 recorded and
ADR-0124, ADR-0125 and ADR-0126 each repeated on this same file).

**ADR-0004's `Status` is a grandfathered `Accepted, partially superseded by …`
line**, and the pair is added to it in the shape it already carries, which is
ADR-0070 §4's accumulation rule applied to the line as it stands: "Adding the second
pair is a §1 Status edit (recording a supersession that landed) and it does **not**
drop the first." The line is not converted to the leading-token form — ADR-0070 §4's
non-retrofit rule and ADR-0082 §3's reasoning both hold that a ratified line is not
reformatted to satisfy a later convention, and ADR-0124, ADR-0125 and ADR-0126 each
added a pair to this line without converting it.

**No in-§2 note is appended, and that is a choice with a reason.** ADR-0017 §7
appended one at the end of ADR-0004 §2 as well as in the header; the three
supersessions since have put the whole record in the header note alone. ADR-0082 §6
declines to prescribe a form for an amendment note, so both are available, and the
recent precedent is followed rather than a fourth shape invented. The header note is
the first thing a reader of ADR-0004 meets and it carries more than a marginal note
could.

#### ADR-0082 §1's test applied to every other ADR a record might look owed on

ADR-0082 §1 requires the judgement in the later ADR's text: would a reader holding
only the earlier ADR "now act differently, or read one of its clauses more widely
than it now holds"? Where the answer is no, "no record is owed against it at all, on
`Status` or in a note". A reviewer disagreeing with any entry below does so by
naming the sentence that becomes false or over-wide (ADR-0082 §1).

**ADR-0017 §1 — no record owed, and this is the one that needs the argument.** Its
deferral paragraph says the residency clause "is left untouched and unread", that
answering it there "would be narrowing a ratified clause this ADR does not
supersede", and "Issue #95." Every sentence stays true: they are a record of what
ADR-0017 did and deliberately declined to do, and they remain accurate history after
the question is answered elsewhere. A reader holding only ADR-0017 still does not
read the residency clause out of it, still follows the pointer to #95, and now finds
an answer there — which is the pointer working, not breaking. This is exactly the
treatment ADR-0017 §6 chose for the prior amendment's declining clause ("a record of
what that amendment did and deliberately declined to do") and the treatment
ADR-0146 §10 applied to ADR-0017 §9 for the same shape. The closing sentence
"Nothing turns on it yet: no tool transmits" was already spent by ADR-0154's
designation, which wrote no note on ADR-0017 for it either.

**ADR-0017 §3 — no record owed.** No condition is discharged, relaxed or added here;
§6 below says so in a clause.

**ADR-0154 §6 — no record owed.** Its third clause's bar is stated over the corpus
— "until an ADR has answered #95" — and an ADR now has. A condition satisfied is not
a condition made false or over-wide: that is ADR-0146 §10's finding about ADR-0017
§3's classification condition ("The condition is not made false or over-wide by
being answered; it stands as written and stays a condition"), and it is ADR-0154's
own relation to ADR-0017 §3, which it satisfied while leaving "exactly as ratified".
Its second clause is untouched and §6 keeps it live; its fourth clause stays true,
because this ADR is not read out of ADR-0154 — it is a separate decision, reached by
supersession of ADR-0004.

**ADR-0146 — no record owed.** §8's "It decides nothing about … residency (#95)" is
a record of what that ADR declined and stays true. §1's and §2's axis is untouched;
§4 above states that the discloser axis and this ADR's source axis are different
questions and neither narrows the other, in the same form ADR-0146 §10 used for
ADR-0098's externality axis.

**ADR-0148, ADR-0150, ADR-0152 — no record owed.** Every condition, floor and
derivation stands; §2 is stated as resting on them and adds nothing to them.

**ADR-0124 §3 — no record owed.** It found "every sentence of the residency clause
stays true" for the overlay control plane and sent residency's intent to #95. Its
finding is unaffected: on §1's reading the control plane's records are still not
this system's store, so ADR-0124 §3's conclusion is reached by a shorter route
rather than a different one, and its marked clauses are untouched.

**ADR-0123 — no record owed.** Its classification list holds that "ADR-0004 §2's
residency clause … is not engaged. §11 makes the tool write to a local path and
transmit nothing." Still true and now true for a second reason. §7 states that the
operator's carriage of a backup artifact is left exactly where ADR-0123 §11 left it.

**ADR-0119 §12 — no record owed**, and §5's second clause above says why in terms:
it is stricter and untouched.

**ADR-0004 §6 and §7 — no record owed.** §6's rights are unchanged in extent: they
reached this system's store before this ADR and reach it after. §5's third clause
above states what they never reached, which is a clarification of scope stated in
*this* ADR rather than a narrowing of §6 — the honest reading is that §6 never
purported to reach a recipient's mailbox, and §3 is what stops the store arriving in
one.

### 6. ADR-0154 §6's gate, and what a registering lane still owes

> **Normative.** ADR-0154 §6's third clause — "the lane does not register the
> integration until an ADR has answered #95" — has its condition satisfied on this
> ADR's merge. The clause is not amended, narrowed or read away: its bar is stated
> over the corpus rather than over an integration, so it is discharged for **every**
> integration at once and not for one.

> **Normative.** ADR-0154 §6's second clause stands unchanged and binds every
> registering lane. A lane registering an integration at the seam states in its own
> change whether that integration's ordinary operation places the owner's data into
> a third-party service in the sense ADR-0004 §2's residency clause is about, and on
> what reading of that clause — which is now §1's.

> **Normative.** That lane states in addition that §3 is honoured by the integration
> it registers, naming the declared arguments through which a value from the
> assistant's own store could reach the payload, and what keeps one out.

> **Normative.** For `ai_assistant.tools.send_email` the first statement is made
> here and a registering lane may cite it rather than re-derive it: its ordinary
> operation places **no** part of the assistant's own store into a third-party
> service, so §1's first clause is not engaged by it, and the copies its operation
> causes — the sent-mail copy in the owner's own connected account, and each
> recipient's mailbox — fall under §1's third clause as the ordinary consequence of
> an owner-directed send under §2. Its ordinary execution path does not engage §3
> either: its execution introduces nothing into a span — the runner carries the
> request's own `parameters`, which ADR-0150 §4 makes the spans themselves, and the
> binder's connection read reaches the binding and the destination set rather than a
> span, and it feeds no chain of operations whose output reaches one. This statement is
> about §3's second clause only and does not reach §3's third: whether a particular
> call's arguments are covered content all of whose covered paths run through a model
> call is a fact about
> that call, and the registering lane's statement under the clause above addresses it
> call by call rather than once for the tool. The
> statement is about the tool's ordinary operation and its declared arguments; it is
> not a statement about the payload of any particular call, which §3 governs call by
> call.

**Why the gate lifts corpus-wide rather than per integration, decided rather than
assumed.** ADR-0154 §6's third clause names its own condition, and the condition is
a fact about the corpus. Reading it as requiring an ADR *per integration* would read
it more narrowly than it is written, which ADR-0089 §3 forbids doing to a marked
clause and which nothing in ADR-0154 supports — §6's own framing is that "the one
residue that binds a later lane" binds "a lane registering an integration at this
seam", and it fixes the remedy as "an ADR has answered #95", singular and
unqualified. The per-integration work stays where §6 actually put it, in the first
clause's statement, and this ADR adds to that statement rather than removing it.

**What the statement is now worth, which is the change.** Before this ADR the first
clause asked a lane to answer a question with no ratified reading available, so the
only honest answers were "yes" and "unclear" and both fired the third clause —
which is precisely what #1152 records. With §1 ratified the question has an
answerable form, and answering it is a real check rather than a formality: a lane
must look at what its integration's ordinary operation persists, and a lane whose
integration would write assistant-derived state as part of its ordinary operation
now finds §3 rather than an open question.

**This diverges from #1152's stated answer, and the divergence is the point.**
#1152 answered ADR-0154 §6's second clause "**Yes — and on any other reading,
unclear**", and that was correct on the corpus as it stood: the only reading under
which the answer was no was the one three ratified grounds made unavailable. The
fourth clause above answers **no** — not because #1152 misread anything, but because
the sense the question is asked in has now been decided, and under it `send_email`
places no part of the assistant's store anywhere. #1152's own proposed resolution is
the shape this ADR takes; where it differs is that §3 is stated as a prohibition
binding a component rather than as a boundary of §1, and §4 states that nothing
enforces it yet.

**What the registration lane still owes is unchanged in every other respect.** Its
survey in #1152 — `build_default_registry`, the `EgressRegistration` into the
`RegistrationTable` that `app/composition.py` builds empty, `SendEmail.__call__`'s
refusal message naming ADR-0017 §2, and its tests — is that lane's work and this ADR
neither performs nor blesses any of it.

### 7. What is not decided here

> **Normative.** Beyond §1's three clauses, §2's two, §3's six, §4's one, §5's
> three and §6's four, this ADR decides nothing. It registers no tool, designates
> no seam, attests, relaxes or adds no condition of ADR-0017 §3, adds no `core`
> name, changes no Protocol, adds no `DestinationProtocol` member and authorises no
> dependency or destination.

> **Normative.** No lane cites this ADR toward a change to `models/` or toward
> ADR-0124's hop. ADR-0017 §2's three pre-existing `models/` gaps — #83's `models/`
> half, #74 and #89 — are untouched, and this ADR asserts nothing about them.

Named individually, because each is a question a reader may expect this ADR to have
absorbed:

- **#57 — the payload manifest's granularity.** Open, and §4 is where it meets this
  decision: a description that cannot distinguish a memory record from arbitrary
  text is #57's granularity question arriving on §3's line. #57 stays as ADR-0148
  §13 and ADR-0154 §6 leave it, and no clause here is a claim about what a
  description should carry.
- **The owner's export of their own model into a service they name.** §3's fifth
  clause reserves it to its own ADR and states what that ADR must decide.
  ADR-0073 §10's deferred `export` command and ADR-0007's `MemoryStore.export`
  produce portable JSON locally and are untouched.
- **The backup artifact's journey off the machine.** ADR-0123 §11 makes the tool
  write to a local path, holds the destination to ADR-0083 D3's deployment standard,
  and leaves the operator carrying the encrypted artifact elsewhere as the
  operator's own act which "ADR-0017 does not govern in either direction". Exactly
  as left; §3 binds components of this system and reaches no act of the operator's.
- **The recipient provider's retention, which no control here reaches.** Once a
  message is sent, the recipients' providers persist copies for as long as their own
  policies say, and neither this system nor the owner's delete right can reach them.
  §5's third clause states this rather than letting §2 imply otherwise. It is the
  inherent cost of sending anything at all, it is the same cost the owner pays using
  an email client directly, and the guarantee this ADR does make is that what can be
  in such a message is bounded by §2 and §3.
- **Whether a standing authorisation may ever cover an egress call.** ADR-0154 §4
  answered no at this seam and named the condition for revisiting; not reopened.
- **Which integrations may be registered, against which accounts, and how.**
  ADR-0154 §7 leaves it to the registration lane and this ADR adds nothing.
- **#75's apparent-secret warning and ADR-0146 §7's undetected paste.** Untouched;
  §4's marked clause is the same posture applied to a different absence.

## Consequences

- **#95 is answered and the registration gate lifts.** ADR-0154 §6's third clause
  is discharged for every integration, its second clause survives with more content
  than it had, and the registration lane can proceed against a ratified reading
  instead of stopping (#1152).
- **ADR-0004 §2's residency clause becomes narrower in reach and stronger in
  force.** It stops purporting to forbid the tool layer the same ADR provisions, and
  it acquires — in §3 — the prohibition #95 showed the natural reading lacked.
- **Three states are now distinguished where the corpus had one.** A rule that is
  *unenforceable as stated* (the flat reading), a rule that is *statable and
  unenforced* (§3's second clause, with #1154 as its mechanism), and a question that is
  *not decided here at all* and reserved to the owner (§3's third clause). Naming the
  third and putting the restrictive rule in force meanwhile, rather than covering it
  with a form of words, is what architecture review's round-2 and round-3 blockers and
  twelve later rounds bought.
- **`send_email` can be registered and QA'd under the interim rules, within a
  narrowed envelope.** A send whose spans carry only content the owner authored, or
  content composed for that send from what the turn itself supplied, introduces no
  store value and is produced by no model call carrying store content — so neither
  clause of §3 reaches it. **A recall-then-send turn cannot draft egress arguments
  under the interim**: once recalled records are supplied to the planner's model call,
  its output is covered content all of whose covered paths run through that call, and
  §3's third clause forbids it reaching a span. A QA send therefore composes from
  turn content only. That is a real narrowing of what a first integration may do, it
  is what makes the interim restrictive rather than nominal, and it is stated here
  rather than discovered during QA.
- **The batch ratifies what the corpus could decide and stops where it could not.**
  Fourteen of this ADR's clauses were settled by reading the corpus; the fifteenth's
  crux is a question about what this system is *for*, and it is recorded as the
  owner's rather than answered by a lane. The evidence is the review record on
  PR #1153, kept rather than summarised away.
- **A rule that was unenforceable and a rule that is unenforced are now distinct,
  and the second is written down.** §3 binds authors and reviewers today; §4 says in
  a marked clause that nothing in code enforces it, and the issue it files carries
  the trigger. That is ADR-0017 §4's honest accounting applied to a privacy rule
  rather than to an import contract.
- **The corpus gains a second axis on an egress span, and knows it does not have
  it.** ADR-0146's discloser axis and this ADR's source axis cross at the `tools/`
  seam, and no field expresses the second. The `core` change that would is deferred
  with a trigger rather than guessed.
- **The owner's delete right keeps its meaning as the seam goes operational.**
  ADR-0126's destruction of `Settings.data_dir` remains the act that removes the
  accumulated model, because §3 forbids the only route by which a second custodian
  could acquire part of it.
- **A later ADR wanting to permit owner-directed export has a clean question**,
  reserved by §3's fifth clause with the decision it must make named, rather than
  being pre-empted or arrived at by accident.
- **Revisit trigger.** The first lane that registers an integration whose declared
  arguments admit free text. That is the moment §4's absence becomes reachable and
  the moment ADR-0073 §4's "with a producer in hand" test is met for the recorded
  origin the enforcement wants.

### 8. Marking, review and ratification

This ADR is in **ADR-0089's marked regime**: it carries well-formed clauses, so the
marked clauses are the whole of what it obligates and the prose beside them supplies
nothing. ADR-0089 §5 makes marking forward-only, so nothing this ADR cites is
retro-marked. What binds is **twenty-one clauses**: §1's three, §2's two, §3's six,
§4's one, §5's three, §6's four and §7's two. Every one is a block quote at column 0
preceded by a blank line, which ADR-0089 §2 requires, and each states one obligation
with its own scope — two passages were split in drafting for that reason, §3's
export reservation and §6's registering-lane statement, and §3's **third clause** was
added in review to reserve the model-context boundary to an owner ruling rather than
decide it, after twelve rounds established that no formulation of it held. The
ordinals of §3's clauses in this document were corrected in the same review: the
export reservation is §3's fifth clause and had been cited as its third since the
drafting split.

§1's four-reading subsection, §4's account of the tree, §5's ADR-0082 §1 classifications
and every argument in this document are deliberately unmarked: they are argument and
attestation, which ADR-0089 §1 classifies as non-normative however load-bearing.

**Required reviews: adversarial *and* architecture.** This is a contract-surface
change in `CONTRIBUTING.md`'s sense — not because it touches `core/protocols.py` or
`core/types.py`, which it does not, but because it decides the extent of the clause
every egress decision in the corpus is measured against, and gates every integration
registration at an operational boundary. ADR-0154 §8 declared both lenses for the
neighbouring decision on the same boundary and ADR-0146's header declared them for
the classification beneath it. It was drafted, reviewed and revised as `Proposed`, and
the route was `CONTRIBUTING.md` → "Finishing an ADR PR", including its route B: an
earlier flip was returned to `Proposed` because the text had moved after the pair
that cleared it, and the reviews were re-run on the repaired tree before the status
flipped again. The ratification note in this ADR's header records the set that ran,
the outcome it got, and the one finding waived rather than complied with
(ADR-0070 §1).
