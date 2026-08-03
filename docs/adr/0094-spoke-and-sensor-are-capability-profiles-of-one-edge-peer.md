# 94. Client, sensor and actuator are capability profiles of one spoke: the edge dials out, the hub decides the band, and nothing at the edge distils

- Status: Accepted
- Date: 2026-08-02
- **Note (2026-08-02): ADR-0095 renamed the in-process seam this ADR is at pains
  to exclude, and the word "sensor" is now free for the spoke profile §1 uses it
  for.** ADR-0093's `Sensor` is a `Reader`, and its package
  `ai_assistant/sensors/` is `ai_assistant/readers/` (ADR-0095 §1). **This ADR's
  text was corrected in place rather than by an appended amendment, because it
  stands `Proposed`**: ADR-0070 §1 scopes its no-rewrite rule to "**ratified**
  decision text", and separates the two states itself — a contract ADR "is still
  reviewed while `Proposed` and ratified only after". ADR-0095 §7 states the
  adjudication in full. What was corrected: §1's marked clause excluding an
  in-process producer, the two places in the Context and in §1 that state
  ADR-0093's package as live fact, and the remaining references to the seam by
  its old name in live rules. Quotations of ADR-0093's own text keep the words it
  used. **§11's classification block was left untouched by that
  substitution** — it records this lane's own review history, including an earlier
  draft that called a locally-read calendar file a "pull peer", and rewriting a
  historical narrative to use a name that did not exist when the events happened
  would falsify the record. **The substitution is scoped to this ADR's
  references to ADR-0093's in-process seam and to nothing else.** In particular
  §1's profile name "sensor" — the vocabulary this ADR applies to a
  *spoke* — keeps its own meaning and is **not** read as `Reader`; freeing the word
  for that use is what ADR-0095 was for, and reading it as the in-process seam
  would contradict §1's marked clause that a `Reader` is not a spoke.
  Completing the remaining prose was left to this ADR's own lane, at ratification,
  and the note below records it done. **Nothing decided by that edit changed, and
  it was not a status token** — it left the `Status` field alone and the
  ratification flip outstanding.
- **Note (2026-08-02, second correction): "spoke" is this ADR's genus, the
  profiles are client / sensor / actuator, and "peer" is retired from
  architectural use.** An earlier text of this ADR made **edge peer** the genus
  and demoted **spoke** to one of its profile names. That is reversed: an
  attachment across the process boundary is a **spoke**, and §1 reserves "peer"
  for its transport sense and for a future hub-to-hub relationship, as a clause
  with its own firing condition. **The text was corrected in place, for the
  reason the note above gives** — ADR-0070 §1's no-rewrite rule is scoped to
  *ratified* decision text and this ADR stood `Proposed`, the adjudication
  ADR-0095 §7 states in full. **ADR-0095's own architectural uses of "peer" were
  corrected to match in the same change**; it also stands `Proposed`, and its
  ratification is its own lane's and remains outstanding.
  **What was corrected here:** the title, every architectural use of "peer",
  §1's marked clauses and its profile list, and — completing the sweep ADR-0095
  §7 left to this lane at ratification — the remaining live-rule references to
  ADR-0093's in-process seam by its old name. **What was not:** quotations of
  other documents, which keep the words those documents used; `wire/peer.py` and
  the transport-sense uses of "peer" throughout `src/` and `tests/`, which are
  correct and untouched; and the review-history narrative in §1 and §11, which
  records an earlier draft's "pull peer" in the vocabulary of the time. §11's
  statements of *current* fact about live clauses are corrected, because leaving
  them would make §11 misdescribe the §1 it points at. **The filename is
  unchanged** — ADR-0093's was left alone through the same kind of rename
  (ADR-0095 §1), and the number is the stable identifier.
- **Decides no `core` surface — no Protocol, no type, no field — and no
  implementation. The refusal is the decision rather than a scoping
  convenience.** There is one client in the tree, no sensor, and no capture
  producer anywhere. Deciding an enrolment schema or a capability descriptor here
  is precisely what ADR-0073 §4 forbade — a decision "for that lane — with a
  producer in hand — not one to guess here" — and what ADR-0093 §7 deferred to the
  third source. What this ADR decides is **rules about conduct**; the surface that
  expresses them is owed when a second spoke exists, and §10 states the condition.
- **Decided with no producer in hand, which this corpus normally refuses, and the
  justification is deliberately narrow.** The test applied to every candidate
  ruling was: is it cheap to state now and structurally unrecoverable later —
  meaning the wrong answer, once shipped, cannot be corrected without a breaking
  protocol change or destroyed data? Three clear it outright: the connection
  direction (§2), the band ceiling (§5), and the edge's re-derivability obligation
  (§7). Three more are applications of ratified clauses to a channel that does not
  exist yet, stated because the evasion they close is specific and the cost of
  stating them is a paragraph (§3, §4, §6). Two bound a hub-side window and
  adjudicate an apparent conflict in the corpus that would otherwise be re-derived
  by every later lane (§8, §9). **An earlier scoping of this decision proposed
  several further rulings — a transport shape for pull, retention figures, a
  capability descriptor and the custody handoff — and none of them clears the bar;
  each is a deferral in §10 rather than a decision.** The custody handoff is the
  instructive one: four consecutive adversarial rounds each found a hole in the
  previous round's fix, and §8 records the sequence and defers the protocol with
  three of those findings carried forward as constraints and the fourth as a
  question the custody lane may not answer by silence. The header says so because an
  ADR that quietly decides less than it set out to is worse than one that names
  what it declined — and because a document that had ratified that protocol would
  have been worse than either.
- **Required review set: adversarial *and* architecture**, even though the PR
  carrying it is prose only. ADR-0093's header set that precedent for an ADR that
  decides architecture without touching code; this one rules on the hub's door,
  on which producer may claim which band, and on where the system's intelligence
  may run, so it took the same set. It was **reviewed while `Proposed` and
  ratified only after** (`CONTRIBUTING.md` → "Contract ADRs land before their
  implementation").
- **Amends no earlier ADR and supersedes none**, and §11 applies ADR-0070 §1's
  test and ADR-0082 §1's record rule clause by clause to show why — including at
  the two places where the opposite reading is available and was the expected
  answer when this lane opened: ADR-0084 §7's stateless client, and ADR-0093 §5's
  scope fence.

## Context

### One microphone breaks a split the corpus has been drawing without stating

The project has two names for a thing that feeds the hub, and they differ on two
axes at once, which is why they have been mistaken for a single split.

A **client** is a spoke that dials the local API (ADR-0084): it lives in **its own
process**, dials in, sends what the user typed, and holds nothing. A **reader**
is a read-only producer (ADR-0093, which called it a `Sensor`; renamed by
ADR-0095): it lives **inside the hub** — §2 puts concrete readers in
`ai_assistant/readers/` and §1 gives them no caller of their own — and it reads a
source and proposes what it read. So one is out-of-process and addressed; the
other is in-process and unaddressed. Nothing has ever forced the question,
because the one client that exists is a CLI and the one reader that is specified
reads a file on the same disk.

Ambient capture — the rolling-buffer design #441 records — is **out-of-process and
unaddressed at once**, and that is the combination the corpus has no name for. A
microphone is on a device, so it is on the far side of a process boundary like a
client; and it produces material nobody addressed to us, like a reader. Worse, one
connection carries both halves: when the user says "assistant, capture that", the
same device delivers an addressed instruction *and* the overheard material around
it.

**Neither existing set of rules reaches it, and this is a gap rather than an
ambiguity.** ADR-0093 §5 fences a non-re-readable source out of the `Reader`
contract in as many words, and a reader is in-process besides, so an ambient
producer is not one on two independent grounds. ADR-0084's rules are written for a
client relaying what a user typed, and say nothing about a producer. A lane
building ambient capture today would find both ADRs declining jurisdiction and no
third one accepting it.

### What the corpus actually says about the two, read rather than remembered

Both names turn out to be narrower than their reputations, and the narrowness is
what makes a unification possible rather than presumptuous.

**ADR-0084's statelessness is about tokens, not about the device.** §7's ruling is
that "the client stays stateless **with respect to tokens**", and its reason is
ruling 4's legibility: a client that cached continuation tokens "would behave
differently depending on whether the hub happened to restart between two
commands". §3 leans on the same property for its idle timeout, and names the
operative half — the client "holds no **server-side session** to lose". The
Consequences record it as "the client stays stateless by decision rather than by
accident (§7)", with §7 the referent. Nothing in ADR-0084 forbids a device from
holding anything; what it forbids is the hub's behaviour depending on state the
client keeps.

**ADR-0093's `Reader` already fences ambient capture out of itself.** §5 buys the
no-cursor result with re-readability and then states the limit: "A source that
cannot be re-read in full within its bound — an append-only feed, a paginated API,
a mailbox — is out of this contract's scope and owes its own decision." A live
audio stream is the purest instance of that class: the past second is gone unless
something held it. §7a's whole configuration model is a path and an interval,
which does not describe a device that speaks first. So a capture spoke is not a
`Reader` under ADR-0093, and cannot become one by implementing the Protocol.

**So the gap is real, and the answer is not "add a third name".** A third name
leaves the same question open for the fourth kind of attachment, and it puts the
rules back where a later lane escapes them by not matching one. What this ADR does
instead is fix the boundary at the **process edge** — where the hub's guarantees
stop being enforceable by the hub — and attach rules to what an attachment across
that edge *does*. An in-process producer stays entirely ADR-0093's; §1 says so as
a marked clause, because the alternative reading would require the calendar reader
a queued lane is about to build to grow a transport.

### The band is assigned by the door today, and that is the fact §5 turns on

`AssistantEngine` carries three client-facing operations, and `wire/surface.py`
derives the wire's method set from the Protocol itself — "a method the Protocol
grows is a method this module already knows about" — so **every public engine
method is reachable by anything that completes ADR-0084 §2's handshake**.

One of them writes beliefs. `AssistantEngine.learn` takes a `FeedbackEvent`
carrying content the caller supplied, and `LearningProcessor._provenance` stamps
every record built from it:

```python
return Provenance(
    source=MemorySource.USER_ASSERTED,
    confidence=_FULL_CONFIDENCE,
    evidence=event.evidence,
    last_updated=event.created_at,
)
```

Unconditionally. Nothing consults who called, and there is nothing to consult:
ADR-0084 §2 declines `SO_PEERCRED` as authorisation on the explicit ground that
"the `0600` bit already restricts connection to the owning user, so a
`SO_PEERCRED` check would re-derive the same fact one layer up". The band is
therefore a function of **which door the content arrived through**, and of nothing
about the sender.

**Today that is correct, and saying otherwise would misread ADR-0084's threat
model.** Everything running as the owning user *is* the user, by ratified
decision, and the one thing dialling that door is a CLI where the user is
literally typing. `USER_ASSERTED` is the honest classification of what arrives.

**Under one kind of attachment it stops being correct, and the failure is at the
top of the ladder rather than the bottom.** A capture spoke runs as the same user
and speaks the same protocol. A sentence a bystander said in the room, promoted by
a user trigger, would arrive through the same operation and be stamped
`USER_ASSERTED` at confidence 1.0 — the band ADR-0072 defines as the user's own
word, which `_refuse_unsafe_fold`'s first clause protects from any fold and which
ADR-0038 §3's one-way asymmetry protects from retirement by anything else. It is
the single hardest record in the store to dislodge, manufactured from something
the user never said. That is what §5 exists to make unreachable.

### An honest statement of what this ADR is not allowed to settle

Four things adjacent to every section below belong to other decisions, and are
named here so their absence reads as a boundary rather than an oversight. §10
states each with the condition that fires it.

- **A revocable permission-grant model.** #629 records that a reader may be
  enabled with no grant at all, and ADR-0093 §7 rules that "configuration is not
  a grant, and no surface may present it as one". §3 below is careful to be a
  prohibition on the hub rather than a grant on the spoke, for exactly that reason.
- **The remote hop.** ADR-0017 §1 and ADR-0084 §1/§11 are untouched and §10 says
  so in as many words, because "designed for remote spokes" being read as
  permission already granted is the failure ADR-0084's Consequences warn about by
  name.
- **The ambient episode exemption.** ADR-0075 §2 listed "the buffered ambient
  capture #441 sketches" among the producers that inherit nothing and *reserved*
  the argument; ADR-0093 §4 then forbade a reader proposing an `EpisodicMemory`.
  §10 states the shape of the collision and does not grant it.
- **`VISION.md`'s sensor-spectrum amendment.** Owed, and #441's standing
  discipline is to ratify it only when a real sensor exists. Named, not written.

## Decision

We will treat every attachment that reaches the hub across a process boundary as
**one kind of thing — a spoke — and attach rules to what it does rather than
to what it is called.**

### 1. One kind of attachment, and it is bounded by the process boundary

> **Normative.** A **spoke** is an attachment that reaches the hub across a
> process boundary, over the local API of ADR-0084. There is one kind of it, and
> no rule may be conditioned on which profile name — "client", "sensor",
> "actuator", or a later one — is applied to a spoke.

> **Normative.** A producer running inside the hub is **not** a spoke. In
> particular a `Reader` (ADR-0093, renamed by ADR-0095 §1) is not one, and no
> clause of this ADR binds it.

> **Normative.** An attachment exercises some combination of three capabilities:
> **push** — the edge sends content to the hub unsolicited; **doorbell** — the
> edge tells the hub there is something to come for, carrying no content;
> **pull** — the hub asks the edge for content the edge has released.

> **Normative.** Every obligation below names its own scope: the capabilities it
> binds, or the whole attachment. A rule scoped to an attachment binds it once,
> however many capabilities it exercises. No obligation in this corpus may be
> conditioned on which profile name a spoke is given.

**Both scopes are needed and the mixture is deliberate, so §1 states the rule
rather than a preference for one of them.** Most obligations here are properties
of a channel and are scoped to the capabilities that open it — §3's release gate
binds push and pull, §4 binds the doorbell, §7 binds whatever submits. Three are
properties of the attachment and would be defeated by capability scoping. §5's
ceiling is the clear case: a ceiling per capability gives a spoke that both pushes
and pulls two ceilings, and content then takes the looser route, which is the
laundering §5 exists to forbid arriving through the taxonomy. §6 and §9 are the
same shape — a device that may not distil is not permitted to distil on its second
channel, and a bound on ephemeral state that reset per capability would bound
nothing.

The CLI is push-only. A capture spoke is the case that needs all three: it pushes
what a promotion released, it may ring when a detector fires, and the hub fetches
the promoted slice rather than being handed it. The profiles are useful vocabulary
and they are not types: a **client** carries a person, a **sensor** reads the
world, an **actuator** acts on it, and each names a bundle of capabilities rather
than a class this ADR binds.

**Pull has no instance today, and the honest statement is that it is named
because the *wrong* shape of it is unrecoverable, not because something needs
it.** §2's ruling is entirely about pull, and its whole value is that it forbids
the reading which puts a listening socket on an edge device. Naming the capability
is what gives that ruling a subject; a capability this ADR declined to name is one
a later lane introduces together with its transport, which is the order in which
the expensive answer gets chosen by default.

**An in-process `Reader` is not a spoke, and nothing in this ADR reaches
it.** ADR-0093 §1 gives a reader no caller of its own — "Selecting when a sensor
runs, and ingesting what it returns, are `orchestration`'s" — and §2 places
concrete readers in `ai_assistant/readers/`, inside the hub. There is no
connection to establish, no released set to declare and no handshake, so §2 and §3
have nothing to bind. **A calendar file read from local disk is therefore not a
pull-capable spoke, and an earlier draft of this section called it a "pull
peer".** That draft
would have required the ADR-0093 reader a queued lane is about to build to acquire
a transport it has no reason to have — a decision change to ADR-0093 dressed as an
illustration. Adversarial review found it on the second round. The error is worth
recording because it is the one this taxonomy invites: a capability vocabulary
reads as though it must classify everything in sight, and the fence is a **process
boundary**, not a role.

**This decides less than it looks like, which is the point.** It does not name a
descriptor, an enrolment record or a field; §10 defers all three. What it does is
fix where a later lane must look for its obligations. Under two names, an ambient
capture lane could reason "I am not a `Reader` — ADR-0093 §5 says so — and I am
not the CLI, so ADR-0084 §7 is not about me", and arrive at a device governed by
nothing. Under one kind with three capabilities, that lane's obligations are
decided by what it does, and doing something new means arguing a new capability
rather than inheriting silence.

> **Normative.** "Peer" is reserved for its transport sense — the process at the
> other end of a socket, which is what `wire/peer.py` means by it — and for a
> future hub-to-hub relationship. No architectural noun in this corpus calls a
> spoke a peer.

**The reservation has a firing condition, which is why it is a clause rather
than a note about a word nobody is using.** If hubs ever talk to each other —
federation, a household running two, a hub that backs another up — *those* are
peers in the word's ordinary sense: equal parties, neither holding authority
over the other, either able to open the conversation. That is the one
relationship in this system's foreseeable shape the word describes accurately,
and it is what the reservation is holding the word for. **Fires when a second hub
exists.** Nothing here authorises one: ADR-0083's resident hub is singular, and
§10's remote-hop deferral is untouched and is about a spoke off the device, not a
second hub. This is the ADR-0093 §7 move — decline the word now, and name the
condition that would revive the question — rather than leaving it merely unused,
because a word left merely unused gets taken by the next lane that needs a noun.

**And "peer" was the wrong word for an attachment on its own terms, which is why
an earlier text of this ADR is corrected rather than defended.** That text made
**edge peer** the genus and demoted **spoke** to a profile name. A peer is an
equal; this architecture is explicitly not one. The hub owns all state and all
intelligence (`VISION.md` §8, ADR-0083), a spoke holds nothing authoritative
(§9), the hub decides the band of everything a spoke submits (§5), and every
connection runs one way (§2). That is a star with an authority at its centre —
hub and spokes — and not a mesh. The vocabulary was also at odds with the corpus
that already had a word: ADR-0084 uses "spoke" for the whole category, not for
one profile of it — §5's "a spoke needs the whole surface" is about the engine's
API, §8's "every spoke built in between would inherit the blind spot" is about
anything the transport reaches — and `docs/roadmap.md`'s later-arc leg is "Remote
spokes", meaning attachments in general. **Restoring "spoke" as the genus
therefore removes an inconsistency rather than creating one, and no clause of
ADR-0084, ADR-0083 or the roadmap needed changing**; every one of their uses is
genus-sense already, and a term broadened from a profile to the genus cannot
falsify a sentence calling some particular attachment a spoke.

### 2. The edge dials out; the hub never dials the edge

*Scope: the attachment.*

> **Normative.** Every connection between the hub and a spoke is established by
> the spoke. The hub may not initiate a connection to a spoke, and a spoke may not
> accept one. Pull is served over a connection the spoke already established.

This is the ruling with the widest gap between its cost now and its cost later,
and it is cheap now because **it is what the tree already does**: ADR-0084 §1 has
the hub listening on `<data_dir>/hub.sock` and the client connecting, and there is
no code anywhere that dials outward from the hub. The clause forbids the
alternative rather than changing anything.

**The naive reading of pull is the expensive one.** "The hub fetches from the
device" reads as the hub opening a connection to the device, and that means a
listening socket on a phone, a laptop or a microphone; an address for the hub to
hold; NAT traversal the day the spoke is not on this machine; and an inbound
attack surface on every edge device in the deployment. Each of those is a
protocol-shaped commitment, and reversing one after spokes are deployed is the
lockstep upgrade ADR-0084's "What is expensive to retrofit" section says a
single-user install has no machinery for.

**It looks academic on loopback, and that is the argument for deciding it now
rather than against.** Two processes on one machine make the direction invisible:
either party can connect to either. The direction only becomes observable at the
first remote spoke, which is precisely the moment at which it has stopped being
changeable. ADR-0084 spent its care on three retrofits for this reason and treated
"swapping the address family" as the reversible decision it is; connection
direction is on the expensive side of that line, and it was not one of the three.

**What is deliberately not decided here is how pull rides the connection, and the
current protocol cannot carry it.** ADR-0084 §3 makes a connection **serial**: "A
request frame sent while another is outstanding is a protocol violation, and the
connection is closed", and a response whose correlation id does not match the
outstanding request closes it too. A hub-initiated request over that connection is
not expressible in the ratified envelope. §3 also says what makes it expressible —
the correlation id exists so that "multiplexing or a progress stream be added
*additively*", which is ADR-0042 §5's deferred extension and ADR-0084 §11's
deferral. So the mechanism is an additive wire decision owing its own ADR (§10),
and this section decides only the direction, which that decision must not reverse.

### 3. Nothing leaves the edge that the spoke has not released

*Scope: push and pull.*

> **Normative.** The hub has no operation that reads edge state a spoke has not
> released to it. A pull may return only what the spoke has already placed in its
> released set, and a spoke that receives a pull for anything else refuses it.

> **Normative.** A push carries only what the spoke has placed in its released
> set. Release is the single gate on everything that leaves the edge, and the
> direction the material travels in does not weaken it.

> **Normative.** What a spoke releases is the spoke's declaration, and the hub may
> not widen it. A hub-side configuration value, a policy, or an operator setting
> may not enlarge what a push or a pull can reach.

**Push is bound by the same gate as pull, and an earlier draft bound only pull.**
That version was defeated on its own illustration: a capture spoke could run a
voice-activity detector under §6, treat every voiced segment as promoted under §9,
and push it under §7 without ever being pulled — satisfying every clause while
sending a bystander's audio to the hub. Adversarial review found it on the first
round, and the defect is worth recording rather than quietly fixing, because it is
the shape a *reach* rule takes when it is written against the channel that looks
dangerous instead of against the property being protected. Pull looks dangerous
because the hub is the actor; push is the wider channel precisely because the edge
is. Releasing is the property, so the gate is on release.

**The property this buys is structural rather than promised.** The alternative
shape — a general "read the edge's buffer" verb, with the hub trusted to ask only
for what it should — makes the consent story a property of hub code, where any
bug, any future caller, and any policy default can breach it. Under these clauses
the hub can ask for anything and get only what was released, so the guarantee
survives a hub that is wrong. This is the same move ADR-0092 §1 made when it
attached the attestation to `Provenance` under an if-and-only-if validator: "a
precondition that a producer can satisfy by remembering is one it can fail by
forgetting, and the failure is silent".

The capture shape is what makes the rule concrete, and it is the shape the rule
was written against. A capture spoke's rolling buffer is **never** in its released
set (§9), so nothing reaches it in either direction: a hub asking for "the last
thirty seconds" receives a refusal rather than audio, and the spoke cannot push it
either. Only a promoted slice is releasable. Note that a spoke whose released set
is large and static — a process that holds a document and offers all of it, at any
time — satisfies these clauses trivially, which is the correct outcome: the gate
is not a bound on how much may be released, it is a bound on the hub reaching past
what was.

> **Normative.** What may cause a release is **not decided here**. A spoke may not
> read this section as authorising any particular promotion, and in particular
> release is not authorisation: a released slice still faces §5's ceiling and
> whatever grant model #629 settles.

**Deliberately not decided, because deciding it would settle the trigger ladder
by implication.** #441's sketched shape is that a user trigger promotes a slice —
"assistant, capture that" — and #441 says of itself that "**Nothing here is
ratified**", so this ADR must not present it as though it were. The ladder's later
rungs (suggested capture, autonomous salience capture) move promotion away from an
explicit trigger by degrees, and each rung is a permission question. What §3 fixes
is that whatever answers it does so by governing **release**, which is one place,
rather than by governing the hub's asking, which would be two. §10 carries the
deferral.

**This is not the grant model, and calling it one would discharge a deferral it
does not discharge.** #629 records that `VISION.md` promises a sensor is
"granted, scoped, and revocable" and that none of the three holds today; ADR-0093
§7 rules that a `Settings` field "cannot be revoked by the user through the
assistant, cannot be scoped, and leaves no audit record". Nothing above supplies
any of that. A spoke's released set is a *bound on reach*, not a record of the
user's permission: it does not say who agreed, it is not revocable through the
assistant, and it leaves no audit trail. The clauses are worth having anyway, and
their value is that they give the grant model **one place to attach**: a grant
governs what may be *released*, and everything that leaves the edge in either
direction is already bounded by release. Without them a grant model would have to
govern the hub's asking and the spoke's sending separately, and a spoke that sends
is the half no hub-side rule can reach. §10 keeps the deferral live.

**The relationship between the two questions is worth stating, because they are
arriving from opposite ends and will meet.** #441's trigger ladder —
push-to-capture, retrospective buffered capture, suggested capture, autonomous
salience capture — is a ladder of *permission* questions wearing product
vocabulary: each rung moves the decision to capture further from the user. A grant
model designed for a calendar file alone answers "may you read this?" once, for a
static source, with no bystander in the room. It will not survive a microphone,
four rungs of autonomy, and a third party who never addressed us. Whoever takes
#629 should take it knowing that.

### 4. A doorbell is a wake, not a delivery

*Scope: the doorbell capability.*

> **Normative.** A doorbell carries no user data. It may not carry content, a
> summary of content, a classifier's label, or any field of `Provenance` — and in
> particular it may never supply `Attestation.reported_at` or
> `Attestation.reported_by`.

**Provenance is the half that is easy to lose, and it is the same failure one
layer down.** The content prohibition is obvious: a "wake" that carries the
utterance is a push wearing a thinner name, and it moves user data over whatever
channel the doorbell was allowed to be cheap on. The provenance prohibition is
not obvious, and it is the reason this section exists. ADR-0092 §3 is strict that
`reported_at` is "the instant the reporting source asserts the fact was current,
on that source's own clock", with **no fallback** — "not our clock, not the ingest
instant, and in particular **not the file's mtime**" — and it settles the outcome
structurally: "Where the source genuinely says nothing about when it spoke, the
producer has no attestation to make", and §1's validator then keeps the record out
of the attested band entirely.

A doorbell says nothing about when a source spoke; it says only that there is
something to come for. Letting it fill `reported_at` would substitute the wake's
own instant for the source's claim, which is ADR-0092 §3's prohibition exactly,
arriving through a channel that ADR did not have in view. The clause is stated
because the substitution is *nearly right* — that is §3's own word for why the
mtime case is hard to spot — and because a doorbell is the natural place for an
implementer to put a timestamp, it being the one part of the exchange that already
has one.

**This is an application of ADR-0092 §3 and not a new rule**, and §11 classifies
it that way. It is worth a marked clause anyway: ADR-0092 §3 forbids substituting
a *local* fact for the source's claim, and a doorbell's instant is a fact about a
transmission rather than about the local filesystem, so a reader could reach the
wrong answer without disobeying anything §3 wrote.

### 5. The hub decides the band; a submission never raises its own

*Scope: the band rule binds every submission — push, and whatever a pull returns. The ceiling is the attachment's.*

> **Normative.** The band of a record a spoke's submission produces is decided by
> the hub from what it knows about the submitting spoke. A spoke may not decide,
> claim, or influence the band of what it submits, and a claim carried in a
> submission is not evidence of the standing it claims.

> **Normative.** Every spoke has a band ceiling, and a submission that would
> produce a record above that spoke's ceiling is **refused**, not downgraded and
> not silently reclassified.

**This is ADR-0093 §1's rule with the producer changed.** "A sensor … may not
decide the fate of anything it proposes" is the same principle read on the
memory-write path; here it is read on the classification path, and it is the rule
the unification owes, because collapsing the two names is what puts a producer
that is not the user on the door that assigns the user's own band.

**`band_of` is untouched and the band architecture survives the collapse
intact.** ADR-0072 §2's mapping is a total function of `MemorySource`, enforced
mechanically — `band_of`'s wildcard "does nothing but `assert_never`", so a source
added without choosing its band fails the gate. Nothing here makes the band a
function of the transport. What the ceiling constrains is which `MemorySource` a
given spoke's submission may *result in*, which is upstream of the classification
and leaves the classification exactly where ADR-0072 §4 put it: "keyed on `source`
and never on `confidence`, so no producer can promote a belief into the asserted
band by claiming certainty". A spoke promoting itself by claiming a source is the
same laundering by a third field, and it gets the same answer.

**Refused rather than downgraded, and the alternative is worse in a specific
way.** Silently reclassifying an over-ceiling submission to the highest band the
spoke may reach produces a record that is *plausible* and wrong: a bystander's
sentence lands as `ATTESTED` with the capture spoke named as the source that
reported it, which is a claim the spoke never made and cannot support. Refusing is
ADR-0093 §5's posture — "A bound is enforced by **refusing**, never by
truncating" — for the same reason it gave: the alternative produces output a
consumer cannot distinguish from a correct one.

**Where the ceiling is declared, and what a spoke's identity is, are deliberately
not decided.** Both are surface: an enrolment record with a ceiling field, and an
identity minted or declared. §10 defers them together, and §11 rules on whether a
hub-minted identity would touch ADR-0092 §3.

### 6. Detection at the edge, distillation at the hub

*Scope: the attachment.*

> **Normative.** A spoke may decide **whether to send** — voice-activity
> detection, wake-phrase spotting, bounding, thresholding. It may not decide
> **what a submission means**: no classification into a `MemoryKind`, no
> extraction of a belief, no summarisation, no assignment of any `Provenance`
> field. Detection is what rings the doorbell; distillation is the hub's.

**The line is drawn on the output, not on the technique, and that is what makes
it applicable.** A detector's output is a decision about a transmission and never
enters the store; a distiller's output is a claim that becomes, or becomes part
of, a record. `VISION.md` §8 puts "the state and the intelligence" in one resident
service, and ADR-0075 §2 already drew this exact line one layer up — the boundary
is "on *what the producer does* — record, or infer" — and refused to draw it on
where the characters came from: "The same model output crosses both sides: quoted
inside an episode it is exempt; distilled by leg 3 into 'the user prefers…' it is
a proposal like any other."

**Read the other way, the corpus would make ambient capture unbuildable**, which
is why the permissive half is marked rather than assumed. An unqualified reading
of "the hub owns the intelligence" forbids a voice-activity threshold on the
device, and then the only conforming design streams a microphone continuously to
the hub — strictly more user data crossing strictly more boundary, in the name of
a principle about where meaning is made. The permission is the safer half of this
clause, not the concession.

**What a detector may itself *be* is not decided here.** A wake-phrase spotter is
a model, and the corpus has three decisions about models that are written for the
assistant's own inference: ADR-0013's router, ADR-0062's operator-named fallbacks,
and ADR-0061's agnosticism testing. Whether an edge detector is governed by them,
by something weaker, or by nothing is a real question and it needs a producer to
answer; §10 defers it with its trigger. What this clause fixes is that the answer
cannot be reached by letting the detector emit meaning.

### 7. The edge may not destroy the only artifact its submission can be re-read from

*Scope: push and pull.*

> **Normative.** Where a spoke's submission is derived from source material the
> spoke holds, the spoke submits the source material and may not substitute a lossy,
> model-dependent derivation of it.

> **Normative.** A spoke may not destroy the material a submission was derived from
> while that submission is unresolved.

> **Normative.** A custody rule fails the clause above if it lets the material be
> destroyed on the strength of an **acknowledgement** the hub makes before durably
> holding it, or if it admits an attempt with no terminal outcome. Destroying the
> material after an attempt has terminally failed **is** permitted, provided the
> failure is reported and not silent; what the report says is §10's.

> **Normative.** That clause governs what a spoke **does**, not what it survives. A
> spoke that loses unresolved material to a crash has suffered a fault, not
> destroyed it, and whether such material must survive a restart is **not decided
> here** (§10).

**The durability condition attaches to the acknowledgement and not to every exit,
and an earlier draft attached it to both.** That version made deletion after a
terminal refusal simultaneously required — §8 will not let a spoke hold material
forever — and forbidden, since the hub never durably holds material it refuses.
Adversarial review found it after §8 was narrowed, which is where the defect came
from: the terminal-failure exit moved out of §8 into §10's deferral and this
clause was not re-read against its absence. The two exits are different acts. An
acknowledgement is a *transfer*, so it may not precede the custody it asserts; a
terminal failure is an *abandonment*, so what it owes is not custody but
legibility — the user asked for this capture, and ADR-0084's ruling 4 is that a
failure must be legible rather than silent.

**The act-versus-fault line is drawn because the alternative reading boxes the
custody lane, and architecture review found the box.** Read as a durability
guarantee, the clause above would require an unresolved submission to survive a
spoke restart — which is durable storage at the edge, which reverses §9 and reaches
`VISION.md` §8's "stateless client", which §10 defers and this lane may not touch.
A constraint whose only satisfying mechanism a document forbids elsewhere is not a
constraint; it is a decision made by omission, in the direction nobody argued. So
the clause is scoped to conduct, where it is enforceable and where its whole
purpose lies — a spoke must not *choose* to drop the source — and the durability
question goes to §10 as a question the custody lane must answer rather than as an
answer it must reach.

For an audio-shaped spoke this means the promoted slice, not a transcript made at
the edge. The clause is stated over derivations rather than over audio because the
argument is not about audio.

**The deciding argument is ADR-0093 §5's, running the other way.** §5 buys the
no-cursor result with re-readability and fences out sources that lack it. A stream
lacks it absolutely — and #441's rolling buffer is the device that manufactures a
bounded amount of it back, which is what makes a capture spoke answerable to §5's
reasoning at all. The promoted slice is then **the only artifact in the whole
pipeline that can be re-read**. A transcript is a lossy projection through one
model at one moment; if the edge transcribes and drops the audio, a mis-hearing is
permanent from that instant, and it propagates — into an episode, and then into
`DERIVED` beliefs citing it. ADR-0077 §6's unresolvable-citation story does not
catch it, because the citation resolves perfectly; it resolves to a wrong
transcript.

**Speaker attribution lives only in the audio, and §5 above needs it.** Within one
capture, what separates an utterance the user addressed to us from a bystander's
remark is who spoke — which is exactly the input a band ceiling has to act on. Flat
text has already made that decision at the edge, unauditably and irreversibly,
which turns §5 into a rule with nothing to apply.

**A transcribing spoke breaks hub-and-spokes at its premise.** ADR-0083's shape and
`VISION.md` §8 put the intelligence in the hub; a transcriber is a model outside
`models/`, outside ADR-0013's router, with no ADR-0062 fallback naming and no
ADR-0061 agnosticism testing — reached by an implementation choice rather than by
a decision. §6's line is what separates this from the detector case: a detector's
output gates a transmission, a transcript *is* the submission.

**And it is the embedder migration with the recovery path removed.** ADR-0083 §6
refuses to start when state "cannot be served correctly by this build", and #425
is its worked instance: an embedder change invalidates every stored vector, and
the remedy is re-embedding, which is available because the source text is still
there. A better transcription model arriving after the audio is destroyed has no
equivalent remedy. The upgrade-with-state discipline exists for exactly this, and
this is the case where it has nothing to work with.

**A transcript does not rescue the remote case either**, which is worth one
sentence because it is the argument someone will reach for. Sending a transcript
instead of audio does not make a remote hop cheaper in the sense that matters: a
transcript of a colleague's words is still their words leaving the device, so
ADR-0017 §1 is engaged identically. §10 keeps the remote hop where it is.

### 8. The verification window is bounded — and the custody handoff is deferred

*Scope: the hub, and the attachment for what it may retain.*

> **Normative.** Material a spoke submits under §7 is retained by the hub only for
> a bounded verification window, during which the user may read what was made of
> it and correct it, and it is destroyed when the window closes.

> **Normative.** Raw source material is never an episode.

> **Normative.** The window is bounded by **both** a duration and a size, and a
> bound is enforced by refusing rather than by truncating or by silently
> discarding early.

> **Normative.** The figures are named in the deciding ADR of the producer that
> needs them, refused at load rather than at first use, and are not named here.

> **Normative.** A spoke does not retain submitted material once its submission has
> resolved, and a producer's ADR may not leave a spoke holding submitted material
> indefinitely. **What resolution is, and the custody handoff that defines it, are
> not decided here** (§10).

**Two dimensions rather than one, and this is ADR-0093 §7a's byte-cap argument
transposed.** §7a separates `calendar_max_bytes` from `calendar_max_entries`
because "a cap on entries alone lets a 2 GiB `.ics` file be fully parsed before
anything refuses it — the bound applied one step too late to bound the work". The
same asymmetry appears here with the axes swapped: a duration cap alone bounds
seconds of audio and not bytes, so a pathological sample rate, channel count or
codec satisfies the window and fills the disk. A size cap alone bounds bytes and
not exposure, which is the thing a *verification* window is for.

**The figures are not named here, and ADR-0093 is the authority for not naming
them.** §7a names nine figures for the calendar reader and then draws the line
explicitly: "**These figures belong to the calendar sensor, not to the `Sensor`
contract.** What the contract obligates is §5: bounded, named, refused at load …
and enforced by refusing." ADR-0074 §9.3's rule that a bounded default with no
figure is two conforming implementations diverging fires when there *are* two
implementations; here there are none, and a number invented for a producer nobody
has built is not a default, it is a guess wearing the authority of a ratified
figure. What is obligated is the shape; the figures arrive with the producer.

#### The custody handoff is deferred, and the evidence for deferring it is this ADR's own review record

**Earlier drafts of this section decided the handoff, and four consecutive
adversarial rounds each found a hole in the previous round's fix.** The record is
worth keeping rather than erasing, because it is the clearest evidence this
document contains for where its own bar (header) actually falls:

1. The first version said only that a spoke "retains nothing after the hub
   acknowledges", which lets a hub acknowledge into memory and crash before
   persisting — destroying the one re-readable artifact §7 exists to protect.
2. Defining an acknowledgement as durable custody then left a submission the hub
   can *never* accept with no exit: §7 forbade destroying it, acquisition could
   not happen, and retrying could not change the answer.
3. Adding a terminal outcome and a bounded retry window bounded each submission
   and not their number, so an unreachable hub plus a promoting spoke fills the
   device with individually-conforming submissions — ADR-0093 §7b's own
   per-component-versus-source-wide argument, one level up.
4. Bounding the pending set in aggregate still left a spoke that **crashes**
   mid-attempt: the queue and the slice are in memory, so the attempt neither
   retries nor terminally resolves, and the loss is silent. This one is not
   carried as a constraint but as a question (§10), because its only satisfying
   mechanism is durable edge storage — see §7's act-versus-fault clause.

**Each of those fixes was correct, and the sequence is the finding.** A custody
handoff is a two-party protocol over a lossy channel with independent failure on
both sides. Deciding it needs the transport (§10), a spoke state model (surface,
§10) and a producer, and this ADR has none of the three. **Continuing to decide it
would be the exact failure the header sets out to avoid**: an ADR ratifying a
protocol that has needed four corrections and is visibly owed a fifth.

**Findings 1–3 are carried as constraints; finding 4 is carried as a question,
and the asymmetry is deliberate.** The first three are satisfiable by any custody
protocol and rule out specific broken ones, so binding them costs the later lane
nothing it should have wanted. Finding 4 is different: the only mechanism that
satisfies it is durable storage at the edge, which reverses §9 and reaches
`VISION.md` §8's "stateless client" — neither of which this lane may decide. So
binding it would decide durable edge state by implication, in the direction nobody
argued, which is the failure §7's act-versus-fault clause exists to prevent. It is
carried as a question the custody lane must answer explicitly instead.

**Deferred with its findings carried is stronger than deciding it badly and weaker
than nothing**, and that is the honest description. §10 states the deferral, and
nothing above is left as a lesson someone has to learn again.

**The duplicate a retry can produce is named here rather than left to the
deferral**, because it is the one residual that is decidable without the protocol:
whatever resolution rule the later lane picks, a lost acknowledgement over a lossy
channel can deliver the same material twice. That is duplication and not loss,
which is the trade ADR-0092 §7 already ruled acceptable for a re-proposing
producer on the same grounds — both copies are visible, neither destroys anything.
De-duplicating submitted media needs an identity scheme, so it is the producer's
ADR's and not this one's.

> **Normative.** After the verification window closes, a capture is no longer
> correctable from its source, and any surface that presents it must not imply
> otherwise.

**The cost is stated rather than discovered.** This is the real price of §7 plus a
bounded window: for the length of the window a mis-transcription is a correction,
and after it the transcript is all there is, so a correction becomes a new
assertion overriding an old one rather than a repair of the record. That is a
tolerable trade — the alternative is retaining raw audio indefinitely, which #441
rules out — and it is the kind of consequence that becomes a support question if
nobody wrote it down.

### 9. Ephemeral edge state is permitted, bounded, and never authoritative

*Scope: the attachment.*

> **Normative.** A spoke may hold ephemeral state, bounded in size and in age, and
> destroyed continuously rather than at a checkpoint.

> **Normative.** Ephemeral state is never authoritative: nothing the hub does may
> depend on it, and it is not part of the spoke's released set until a promotion
> places a slice there (§3).

> **Normative.** Material a promotion has released is held under §8 rather than
> under this section: it is bounded by the resolution of its submission attempt,
> not by the buffer's age bound, and it is destroyed when that attempt resolves.
> That the pending set must itself be bounded in aggregate — and how — is §10's.

**The two hold-times are separate, and stating that is what keeps the two sections
from contradicting each other.** The buffer's bound is an age: nothing sits in it
longer than the window, whether or not anything ever reads it. A released slice
has left that regime — it is awaiting a two-party handoff whose duration is not
the spoke's to fix — so collapsing the two would either make a promotion expire
mid-transfer or let an unresolved submission sit at the edge forever. **Saying
which regime a released slice is in is this ADR's; saying how long it may stay
there is not**, and §10 carries that as an obligation on the custody lane rather
than leaving it to be discovered — the fourth adversarial round of this ADR
discovered it, which is why it is written down.

**The useful reframing is that this is not "state at the edge" at all.** A rolling
buffer is **a bounded backward read window, materialised in advance because the
source will not hold still**. That is the same object ADR-0093 §5 requires and
fences on: §5's no-cursor result is bought by re-readability, and a stream has
none, so the buffer is the compensating device that manufactures exactly the
property §5 depends on — in bounded quantity, which is why §5's fence is satisfied
by a capture spoke that has one and not by a stream that does not.

**Read as an exception to ADR-0084, this section would be an amendment. It is
not one, and the reading is worth refuting rather than dismissing**, because it
was the expected answer when this lane opened. ADR-0084 §7's clause is "the client
stays stateless **with respect to tokens**", its stated reason is that a cached
token "would behave differently depending on whether the hub happened to restart
between two commands", and §3's idle-timeout argument names the operative
property: the client "holds no **server-side session** to lose". Every one of
those is about the client's relationship to *hub* state. A rolling buffer holds
nothing of the hub's, resolves against nothing the hub minted, and cannot make the
spoke behave differently across a hub restart — the buffer is the same buffer
either way. ADR-0084's §7 sentences all stay true, and a reader holding only
ADR-0084 acts identically before and after. Under ADR-0070 §1 that is not an
amendment; §11 records it.

**What does strain is `VISION.md` §8's unqualified "Every interface should be a
**stateless client** of that service", and this ADR deliberately does not touch
it.** #441 records the standing discipline — the sensor-spectrum amendment is
ratified "only when a real sensor exists" — and none does. The sentence is named
here as owed so a later reader does not mistake silence for agreement, and §10
carries it as a deferral.

**The three qualifiers are the whole of the permission and none is decoration.**
*Bounded* is what keeps it from being a store. *Continuously destroyed* is what
makes "ephemeral" a property rather than an intention — a buffer flushed at a
checkpoint is durable between checkpoints. *Never authoritative* is what stops the
next lane building a feature on it, at which point the hub's correctness would
depend on state it neither owns nor can inspect, which is the thing ADR-0083's
resident-hub shape and `VISION.md` §8 are both built to prevent.

### 10. Deferred, by name, each with the condition that fires it

- **All `core` surface for any of the above** — an enrolment record, a capability
  descriptor, a band-ceiling field, a spoke identity, a released-set
  representation. Fires when a **second** spoke exists: one spoke cannot show which
  of these differ per spoke, and ADR-0073 §4's "with a producer in hand" is the
  standing this ADR does not have. §10a marks what that costs a later lane.
- **How pull rides the connection** (§2). ADR-0084 §3's connection is serial and
  cannot express a hub-initiated request; the correlation id is what makes the
  extension additive, and ADR-0084 §11 and ADR-0042 §5 already hold the deferral.
  Fires with the first spoke that needs pull. The direction §2 fixes is an input to
  that decision, not a question it reopens.
- **What may cause a release** (§3) — #441's trigger ladder, from an explicit
  "capture that" to autonomous salience capture. §3 fixes that release is the gate
  on everything leaving the edge and decides nothing about what opens it, and #441
  is a tracker record that says of itself that nothing in it is ratified. Fires
  with the first capture producer, and it is probably one decision with the grant
  model below rather than two.
- **The revocable grant model** (#629, ADR-0093 §11). §3 bounds what may leave the
  edge in either direction and supplies none of granted, scoped or revocable.
  Fires on #629's own trigger. It should be taken knowing that the trigger ladder's rungs are
  permission questions and that a model sized for one static file will not carry a
  microphone and a bystander.
- **What governs an edge detector that is itself a model** (§6) — whether
  ADR-0013's router, ADR-0062's fallback naming and ADR-0061's agnosticism testing
  reach it, or whether an edge detector is a different class of thing. Fires with
  the first spoke that ships one. §6 fixes only that its output may not be meaning.
- **The figures** (§8, §9) — the verification window's duration and size, and the
  buffer's age and size bounds. Fires with the deciding ADR of the first producer
  that needs any of them, which names them under ADR-0093 §5's discipline: named,
  refused at load, enforced by refusing. What is decided here is which dimensions
  must be bounded, not by how much. The custody lane below owns its own figures on
  the same terms.
- **The custody handoff** (§8) — what an acknowledgement asserts, when an attempt
  resolves, what happens to material the hub can never accept, how long a spoke may
  keep retrying, how a spoke restart is recovered from, and what any of it is
  reported as. **It is a two-party protocol over a lossy channel with independent
  failure on both sides, and this ADR has neither the transport (deferred above),
  a spoke state model (surface, deferred above), nor a producer.** Fires with the
  first spoke that submits material it holds — plausibly the same decision as the
  transport. **The conditions it inherits are marked in §10a**, because ADR-0089
  §3 makes marked clauses the whole of a marked ADR's obligations and a clause
  cannot live inside a list item (§2).
- **Whether ambient capture may write an `EpisodicMemory`, and on what
  exemption.** ADR-0075 §2 named "the buffered ambient capture #441 sketches" in
  its exclusion list and reserved the argument rather than granting it; ADR-0093 §4
  then forbade a reader proposing an episode, citing ADR-0075 §4's demonstration
  that the gate is destructive to episodes — kind-scoped conflict detection,
  `REINFORCE` on the first conflict, and a merge that returns "the **new turn
  stored at the older turn's id**". Ambient capture's whole product is episodes, so
  the collision is real and near. **The shape it will take, stated so the argument
  starts from the right place and not granted here:** a capture spoke can vouch for
  *the recording being faithful* and cannot vouch for *the exchange being ours*,
  because the third party in the room never addressed us. That suggests the
  episode may be exemptible on ADR-0075's own grounds — deterministic recording of
  an event, no inference — while everything derived from it stays gated. It is a
  larger claim than ADR-0075 §2 made, it needs a producer, and it needs its own
  ADR. Fires when something wants a timeline rather than beliefs.
- **The remote hop. Nothing in this ADR authorises a non-loopback spoke.**
  ADR-0017 §1 governs user data leaving the device and §3's fourteen conditions
  govern designating the `tools/` seam; ADR-0084 §1 and §11 hold the transport
  half. All are untouched. §2's connection direction and §7's re-derivability rule
  are *designed so that a remote spoke would not force a redesign*, and that is the
  whole of what they buy — the same distinction ADR-0084's Consequences draw
  between "one bind away on the wire" and "one ratified decision away in fact".
  §7's closing paragraph is why a transcript does not shortcut it, and §10a marks
  the refusal so it is an obligation rather than a reassurance.
- **`VISION.md`'s sensor-spectrum amendment** — the ephemeral buffer,
  consent-per-capture, and graduated trigger autonomy, and with it §8's
  "stateless client" sentence (§9). Owed; #441 holds it. **Its trigger is tightened
  here**, and marked in §10a: #441's standing condition is "a real sensor", and the
  sharper one is that the amendment is ratified **before the first producer that
  relies on §9's permission ships**, not merely before some sensor exists. §9 permits edge state
  now and the Vision sentence forbids it in general terms; leaving that open past
  the point where something depends on it is how a living document and the corpus
  drift apart (ADR-0019). Architecture review raised the sequencing; this ADR
  cannot write the amendment — the fence — but it can state when it comes due.

#### 10a. What the deferrals bind, marked

Several of the deferrals above constrain the lanes that take them, and a deferral
that constrains nothing is a lane's blank cheque. They are gathered here because
ADR-0089 §2 puts a clause at column 0 and §3 makes the marks the whole of the
obligation — stated inside §10's list they would have bound nothing, which
adversarial review demonstrated by exhibiting a conforming producer that omits the
aggregate bound. Most restate a finding against a draft of §8 that tried to
decide the protocol; the arguments are in §8 and are not repeated.

**The `core` clause forbids a lane acting without an ADR, not the ADR.** An
earlier wording forbade implementing any rule here "by adding a field to `core`"
full stop, which would have blocked the very surface §10 defers — a band-ceiling
field and a spoke identity are exactly what the second-spoke contract may need.
Architecture review caught it. What this ADR refuses is surface arriving *without*
a decision, which is golden rule 5 rather than a new rule; whether the later
contract needs a `core` field is that ADR's to answer, and it is expected to.

> **Normative.** An ADR deciding the custody handoff may not let an
> acknowledgement precede the hub's durable custody of the submitted material.

> **Normative.** An ADR deciding the custody handoff gives every submission
> attempt a terminal outcome reachable in finite time.

> **Normative.** An ADR deciding the custody handoff bounds a spoke's unresolved
> submissions **in aggregate**, by count and by total bytes, and not per
> submission alone.

> **Normative.** An ADR deciding the custody handoff states explicitly whether an
> unresolved submission survives a spoke restart, and at what cost to §9. It may
> not settle that question by silence.

> **Normative.** No lane may add `core` surface expressing a rule of this ADR
> without an ADR deciding that surface, merged before anything implements against
> it (golden rule 5).

> **Normative.** Nothing in this ADR authorises a spoke that is not on this
> machine. ADR-0017 §1 and §3 and ADR-0084 §1 and §11 are untouched, and §2's
> connection direction and §7's re-derivability rule are not permission to cross a
> device boundary.

> **Normative.** No producer relying on §9's permission to hold ephemeral edge
> state ships before `VISION.md`'s sensor-spectrum amendment is ratified (#441).

The first three exist to protect §7, which is the clause that does not move, and a
custody rule meeting fewer than all three does not satisfy it. The fourth is a
question rather than an answer for the reason §8 gives: its only satisfying
mechanism is durable edge storage, and binding it would decide that by
implication.

### 11. This ADR classified under ADR-0070 §1 and ADR-0082 §1

ADR-0082 §1 requires the judgement to be made in the later ADR's text, naming the
clause and applying ADR-0070 §1's test: would a reader holding only the earlier
ADR now act differently, or read one of its clauses more widely than it now holds?
The answer here is that **no earlier ADR's status line changes**, and the four
places where the opposite reading is available are argued rather than asserted.

- **ADR-0084 §7's stateless client.** §9's permission for ephemeral edge state
  looks on its face like an exception. It is not: §7's clause is scoped to
  continuation tokens, its reason is a client's behaviour changing across a hub
  restart, and §3's use of it names the property as holding "no **server-side
  session** to lose". A rolling buffer engages none of that. Every sentence
  ADR-0084 §7 wrote stays true, and a reader holding only ADR-0084 behaves
  identically before and after. **Not an amendment.** The strain is on
  `VISION.md` §8's broader sentence, which is not an ADR and is deferred to
  #441's amendment (§10) rather than reinterpreted here.
- **ADR-0093's `Reader` contract.** A taxonomy that used the word "sensor" looks
  like it should amend it, and **an earlier draft did amend it without saying
  so** — by calling a locally-read calendar file a "pull peer", which would have
  required a `Sensor` to establish a connection (§2) and declare a released set
  (§3), neither of which an in-process object can do. That is a decision change to
  ADR-0093 §1 and §2 arriving inside an illustration, and it is exactly what
  ADR-0082 §1 means by "**The test controls, not the label**". Adversarial review
  found it on the second round. **It is repaired by narrowing rather than by
  recording an amendment**, because narrowing is what was intended: §1 now fixes
  the process boundary as this ADR's outer edge and states as a marked clause that
  a `Reader` is not a spoke.

  On the corrected text, **no amendment is owed on two independent grounds.** No
  clause of this ADR binds an in-process producer at all, so nothing of ADR-0093's
  can be narrowed by one. And §5's fence had already placed a stream outside the
  contract — "A source that cannot be re-read in full within its bound … is out of
  this contract's scope and **owes its own decision**" — so this ADR is the
  decision that clause anticipated rather than an encroachment on it. Nothing
  above changes what a `Reader` is, what it may propose, how it is bounded or how
  it is driven; a calendar reader conforming to ADR-0093 conforms unchanged, and a
  reader holding only ADR-0093 acts identically. **Not an amendment.**
- **ADR-0092 §3's `reported_by`, and whether a hub-minted spoke identity would
  touch it.** §3 rules that `reported_by` "identifies the connected source
  *instance*, not the vendor" and must be "stable across syncs", and ADR-0093 §7
  then ruled a reader's identity **declared, not configured**, specifically to keep
  a path or an address out of `Provenance`, exports and logs — "A declared constant
  cannot carry personal data at all, which is a property rather than a rule." A
  hub-minted identity would close that hazard by construction and is therefore
  strictly stronger, at the cost of stability across re-enrolment, which is exactly
  what §3 requires. **This ADR does not touch it**, and the reason is the standing
  one: minting is surface, deferred in §10 with every other field, and ruling on it
  here would decide a `core` question with no producer. The observation is recorded
  so the later lane inherits both halves of the trade rather than rediscovering
  one. No clause of ADR-0092 becomes false or over-wide; **not an amendment.**
- **ADR-0075 §2's exclusion list.** It named ambient capture among the producers
  that inherit no exemption and said each "may argue for the same exemption on the
  same grounds when it exists". §10 declines to argue it and states its shape.
  Agreeing with a ratified clause is not amending it. **Not an amendment.**

**ADR-0092 §3's `reported_at`, and §4's doorbell clause.** §4 forbids a channel
ADR-0092 never contemplated from supplying a field ADR-0092 already governs. It
adds an obligation that contradicts no sentence ADR-0092 wrote, which under
ADR-0082 §1 is a **stacked addition**: recorded here and nowhere else.

**ADR-0072 §2 and §4 are conformed to, not narrowed.** §5's ceiling constrains
which `MemorySource` a spoke's submission may result in; `band_of` stays a total
function of `MemorySource` and classification stays keyed on `source`. ADR-0084 §2
and §3 are cited as they stand; §2's connection direction adds a rule where
ADR-0084 gave none, since nothing in it contemplated the hub as an initiator.
ADR-0017 §1 and §3 are examined in §10 and found not to engage, a local spoke
crossing no device boundary — ADR-0084 §1 settled that "A loopback listener moves
bytes between two processes on one machine; it engages neither clause", and
ADR-0092 §10 and ADR-0093's Context both rest on it.

## Consequences

- **A later lane's obligations are decided by what its attachment does**, so a
  producer that is neither the CLI nor a `Reader` inherits rules rather than
  silence. That is the whole product of §1, and it is worth exactly as much as
  the clauses attached to it.
- **The band ceiling closes a gap before it opens.** Nothing today can put a
  bystander's sentence in the store at `USER_ASSERTED` confidence 1.0, because
  nothing but a CLI dials the door; §5 is what keeps that true on the day
  something else does. It costs nothing now and it is unbuildable-after-the-fact,
  because the records it would have prevented are the hardest in the store to
  retire.
- **The connection direction is fixed while it is still free.** Every spoke
  dials out; no spoke ever listens. On loopback this changes nothing, which is the
  point: the alternative is only observable once it is no longer reversible.
- **A capture spoke is now known to be expensive**, and honestly so. It owes source
  media rather than a transcript (§7), a bounded verification window with figures
  it must name (§8), a custody protocol meeting three stated constraints and
  answering the restart-survival question explicitly (§10),
  a detector whose governance is undecided (§6, §10), and it cannot ship remote
  (§10). Anyone reading this as encouragement is reading it wrong; what it removes
  is the cheap version that would have been unrecoverable.
- **The custody handoff is a whole decision, and this ADR is the evidence.** Four
  adversarial rounds against §8 produced four correct fixes and a fifth open hole,
  which is what a two-party protocol costs when it is designed without a
  transport, a state model or a producer. Three findings are carried into §10 as
  constraints and the fourth as a question, so the cost was not wasted — but the
  lane that takes it should expect a decision, not a section.
- **What gets harder:** an edge that wants to do more than detect needs an ADR
  rather than a design choice, and a spoke that wants the hub to reach further has
  to release more rather than be trusted more. Both are deliberate, and both are
  the kind of thing otherwise reached by an implementation.
- **Two debts stay open and are now visible.** `VISION.md` §8's "stateless client"
  is broader than what ADR-0084 decided and broader than §9 permits, and #629's
  grant model is still unmet. Neither is closed here; both are named so the gap is
  a stated debt rather than a sentence nobody re-reads.
- **Revisit when** a second spoke exists (every deferred surface in §10 fires at
  once), when a spoke needs pull (§2's mechanism), or when something wants an
  ingested timeline (§10's episode question).

## Alternatives considered

- **Add a third name for the ambient case and leave client and reader alone.**
  Rejected in §1: it answers this instance and leaves the same question open for
  the fourth kind of attachment, and it puts the rules back on names, where a
  later lane can escape them by not matching one.
- **Decide the enrolment surface now, since the rules imply fields.** Rejected as
  the central scoping decision. One spoke cannot exhibit which of these values
  differ per spoke, and ADR-0073 §4 already ruled that this class of question is
  decided "with a producer in hand — not one to guess here". A field designed
  against an imagined producer is surface with no consumer, which ADR-0045 §1 and
  ADR-0028 §7 refuse, and it would arrive as `core` contract surface owing an ADR
  to remove.
- **Let the edge transcribe and send text, keeping audio off the wire entirely.**
  Superficially the more private answer, and rejected in §7: it destroys the only
  re-readable artifact in the pipeline, it makes a mis-hearing permanent and
  citable, it takes the speaker attribution §5 needs out of the system before the
  hub sees it, it puts a model outside `models/` with none of ADR-0013/0061/0062's
  governance, and it does not rescue the remote case, since a transcript of
  someone's words is still their words leaving the device.
- **Give the hub a general read verb over edge state and trust it to ask
  narrowly.** Rejected in §3: it makes the consent property depend on hub code
  being correct forever, where releasing makes it depend on nothing. This is the
  same trade ADR-0092 §1 made against a producer convention, and it goes the same
  way.
- **Let the hub dial the spoke, which is the obvious shape for pull.** Rejected in
  §2: it puts a listening socket on every edge device, needs an address for the
  hub to hold and NAT traversal the day the spoke is off this machine, and is
  invisible on loopback right up to the moment it becomes unchangeable.
- **Defer the whole taxonomy until a capture producer exists.** The strongest
  alternative, and it is why this ADR's header states its own bar rather than
  assuming one. It is taken in part: the surface, the transport, the figures and
  the grant model are all deferred (§10). What is not deferred is the small set of
  rulings whose cost is a paragraph now and a breaking change or destroyed data
  later. Deferring those too would have been tidier and would have bought nothing
  a later ADR could give back.
