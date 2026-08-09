# 124. The hop is a third egress boundary, and a device is admitted by two independent facts

- Status: Proposed
- Date: 2026-08-09
- **This ADR partially supersedes ADR-0017 §1, and the record lands in this
  change.** §12 applies ADR-0070 §1's test and finds ADR-0017 §1's two-boundary
  enumeration — "user data may leave the device only from `models/` or from a
  designated integration seam inside `tools/`; every other egress is a bug" —
  contradicted rather than joined. ADR-0017's `Status` line and its appended dated
  note are the whole of the record (ADR-0070 §1, ADR-0082 §1 and §2); no ratified
  text of ADR-0017 is rewritten, and its §3 conditions on designating the `tools/`
  seam are untouched.
- **No implementation lands with it.** No `src/`, no `tests/`. The remote listener,
  the client's addressing and the credential handling are a separate lane, briefed
  against this text once it merges.
- **No `core` surface is decided.** No Protocol, no `core/types.py` model. §10
  rules that if the implementing lane finds it needs either, it stops and owes its
  own contract ADR (golden rule 5, ADR-0015 §5). `Settings` fields are expected and
  are contract surface in ADR-0054's sense rather than golden rule 5's, as
  ADR-0084 §3's four already were.
- **Its required review set is adversarial *and* architecture.** This decision
  fixes an egress boundary, an admission rule on a ratified handshake, and a
  version-bump rule the wire has been operating without (#872) — the edge cases
  are answerable from prose, before an implementation commits to an answer
  (`CONTRIBUTING.md` → "Contract ADRs land before their implementation").

## Context

### The wire is ready and the hop is not authorised

ADR-0084 bought three retrofits in advance and leg 5 shipped them: a versioned
connect handshake, a defined place for a credential the loopback transport carries
nothing in, and a client stateless by decision. Its §1 then said the sentence this
ADR exists to answer:

```text
But it engages ADR-0017 the moment the transport stops being loopback… A hub on a
dedicated machine serving a spoke on a laptop *is* user data leaving the device,
and the hub's API is neither `models/` nor a designated `tools/` seam — so under
ADR-0017 §1 as it stands, that egress "is a bug". **The remote leg therefore owes
its own ratified egress decision, and it cannot be reached by swapping an address
family.**
```

ADR-0084 §11 holds the same deferral by name, `docs/roadmap.md`'s leg 9 restates
it, and ADR-0094 §10a marks its own refusal to grant it: "Nothing in this ADR
authorises a spoke that is not on this machine." Three ratified documents point at
a decision nobody has made. This is it.

### What is new is a recipient, not a network

The recipient of this egress is **the owner, on a second machine they own**. That
is not what either existing boundary is: `models/` transmits to a provider the
user configured, and the `tools/` seam would transmit to an external service. A
reader can reach two opposite conclusions from that fact and both are available
in the corpus, which is why the argument is made in §1 rather than assumed.

The conclusion that is *wrong* is that a hop to the owner's own laptop is not
egress at all. ADR-0017 §1's rule is scoped to the **device**, not to the party:
"user data may leave the **device**". Two of the owner's machines are two devices.
Bytes on a network between them are bytes on a network, subject to whoever can
observe the path, and the store's contents are Tier 1 (ADR-0004 §1).

The conclusion that is *right* is that the recipient being the principal changes
what the boundary has to protect against, and therefore what its conditions are.
ADR-0017 §3's fourteen conditions are conditions on *designating the `tools/`
seam*, and most of them are shaped by a problem this boundary does not have: a
destination chosen at call time from arguments a model produced. Here the
destination set is the devices the owner enrolled, fixed by an act the owner
performed at the hub, and the payload is the answer to the request that device
just made.

### What is unsettled about the version integer

ADR-0084 §3 defends the exact-match handshake on the ground that "there is no
supported deployment in which they differ except a half-finished upgrade". A hop
is the deployment where they genuinely can differ: two machines, upgraded
separately, by hand. #872 records that **nothing ratified says when an incompatible
payload change bumps `PROTOCOL_VERSION`** — ADR-0087 §8 rules it for one case
(a vector change) and no clause generalises it, and ADR-0122 required the bump for
its own change while deliberately declining the general case. The integer is at 2
today (`wire/envelope.py`), bumped by ADR-0122 for exactly the reason §9 below
generalises.

Deciding the hop without deciding that rule would ship the first deployment where
the guarantee matters, still resting on nothing.

### What the tree actually holds, checked rather than remembered

- **`PROTOCOL_VERSION` is 2**, not 1 (`wire/envelope.py`).
- **The credential member already exists in the schema.** `CONNECT_CREDENTIAL` is
  a defined member, `connect_payload` writes it when asked to, and `read_connect`
  refuses a non-empty one with `CREDENTIAL_NOT_SUPPORTED` (`wire/envelope.py`).
  Nothing about the frame's shape has to change for a credential to be carried.
- **The connect payload is bounded at 256 bytes encoded** (ADR-0085 §8d,
  `CONNECT_PAYLOAD_BYTES` in `wire/codec.py`), with the client identifier bounded
  at 64. A credential occupies what is left, and raising that bound would amend a
  ratified clause.
- **`SecretStore` does not exist.** ADR-0004 §3 provisions it and ADR-0084 §11
  calls it "the obvious home" for a credential; `core/protocols.py` does not
  declare it. Today's Tier 0 credential — the provider key — is read from the
  process environment by the provider SDK (`models/provider.py`). A decision that
  assumed the keyring path exists would be designing against a premise the tree
  does not hold.
- **`credential` is already redacted in logs.** `core/logging.py`'s
  `_SENSITIVE_KEY_PARTS` matches it as a substring, case-insensitively.
- **A handshake refusal an old client cannot name still renders.**
  `_raise_handshake_error` reads the message and raises `ProtocolError`
  (`wire/client.py`); it does not switch on the code. The closed code set lives in
  `_raise_reply_error`, on the *call* path, which is a different frame.

### The dedicated box is not available and is not needed

The owner has ruled that the inhabitation arc completes without a dedicated
always-on machine (#882, on #879): nothing in legs 9–12 may depend on hardware
that does not exist. Two processes on one machine exercise the protocol path and
not the thing ADR-0017 §1 governs — data leaving the device, a distinct device
identity, an enrolment and a revocation. So the validation plan in §11 is written
for a **second commodity device** the owner already has, and the accepted cost is
duty cycle rather than capability.

## Decision

We will authorise a **third egress boundary** — the hub's remote listener — under
a transport posture that keeps the API off the public internet, and admit a device
to it only when **two independent facts** agree: an identity the transport
attests, and a credential the owner minted at the hub.

### 1. The rule: a third egress boundary, and it is the hub's remote listener

> **Normative.** User data may leave the device only from `models/`, from a
> designated integration seam inside `tools/`, or from the hub's remote listener
> to a device the owner has enrolled under §6; every other egress is a bug.

> **Normative.** `models/` and the `tools/` seam are unchanged by this ADR.
> `models/` continues under ADR-0004 §2's permission as ADR-0017 §2 records it,
> and the `tools/` seam stays approved and undesignated until ADR-0017 §3's
> conditions hold in code and a later ADR ratifies that they do. Nothing in this
> ADR discharges, weakens or substitutes for any of those conditions, and no lane
> may cite this ADR toward designating that seam.

**That is the whole of the widening.** It replaces ADR-0017 §1's enumeration and
nothing else — §3's conditions, §4's argument, §8's deferred capability and §9's
open list all stand as ratified, and §12 below is the record.

**ADR-0017 §3's fourteen conditions do not bind this boundary, and saying so is
not the same as saying nothing binds it.** §3 opens "None is discharged today"
and its subject is stated in its own heading: *conditions on designating the
`tools/` seam*. Examining a clause and finding it unmet changes nothing about it
(the ADR-0083 §15 pattern ADR-0084 §12 applied to ADR-0017 itself). What replaces
them here is §§2–8, and the reason the list is different is that the conditions
are shaped by a *destination chosen at call time from arguments*:
canonicalisation per protocol, multi-recipient authorisation as one set, name
resolution as a gated call, a payload description bound before transmission. None
of those has a subject on this boundary. The destination is not selected by
anything; it is the device that opened the connection, and it is either enrolled
or refused.

**Why a third boundary costs ADR-0017 §4's property nothing, in its own terms.**
§4 found that ADR-0004 §2's rationale "is about egress being **accountable** —
few, named, and answerable for what it sends — never about the number of
accountable places", and that "'One' was never argued for; it was a count of the
subsystems that existed." Two was a count as well. This boundary is accountable on
every axis §4 names:

- **Named.** The listener is one module in the packages ADR-0084 §6 already
  placed — the server half in `service`, the client half in `wire` — and no new
  package is created.
- **Few.** The recipients are exactly the devices in the enrolment record, a set
  no model, plan, tool or configuration value can add to (§6).
- **Answerable for what it sends.** It sends the response to the request the
  device just made, over the ratified envelope, bounded by ADR-0084 §3's frame
  ceiling and ADR-0085 §8's contract limit. There is no path by which it
  transmits something nobody asked for.

**And the recipient is the principal, which is the substantive difference.** A
belief crossing this boundary is disclosed to the owner, on a machine the owner
enrolled, under ADR-0099 §1's single principal. `models/` discloses to a vendor and
the `tools/` seam would disclose to a service; both are disclosures to a third
party and both are why ADR-0017 §3's list is as long as it is. The honest
statement of the residual is that "to the owner" is a property of the *recipient*
and not of the *path*, and §2 is what closes the path.

**Honest accounting.** A third exit point is a third thing that can be got wrong,
and this one is the first that a stranger can attempt to reach without already
having code running on the owner's machine. `models/` and `tools/` dial out; this
listens. That asymmetry is why §2 constrains where it may bind, §4 requires the
hub to authenticate the peer before admitting it, and §7 fails closed in the
direction ADR-0084 §2 declined to.

### 2. The transport posture: an overlay network, and Tailscale accepted as the first one

> **Normative.** The hub's remote listener is reachable only over an **overlay
> network** satisfying all three properties: every participant is authenticated by
> the overlay before any byte of this protocol is exchanged; the payload is
> encrypted end to end between the two participating devices, such that no third
> party — including the overlay's operator and any relay it routes through —
> holds a key that decrypts it; and membership is administered by the owner.

> **Normative.** The remote listener binds only to an address that exists on that
> overlay. It may not bind a wildcard address, an address of a physical interface,
> or any address reachable from the public internet, and a configuration that
> would have it do so is refused at load time rather than bound.

> **Normative.** The remote listener is off unless it is configured on. A hub with
> no remote-listener configuration binds only ADR-0084 §1's loopback socket, and
> the loopback socket is bound whether or not the remote listener is.

**Tailscale is accepted as the first implementation, in writing, and the
acceptance is of an overlay rather than of a vendor.** #664 records the survey's
verdict — "Tailscale pragmatic first, NetBird/Headscale as the self-hosted
upgrade" — and it is input, not a decision. The decision is that the clause above
is what binds, and Tailscale satisfies it: WireGuard between the two devices, keys
that never leave them, and a relay path that forwards ciphertext it cannot read
when a direct path cannot be established.

> **Normative.** Nothing in this ADR is conditioned on Tailscale. Moving to
> another overlay that satisfies the clause above — Headscale and NetBird are the
> named candidates (#664) — is a configuration and operating change, and no clause
> of this ADR is reopened by it.

**Why an overlay rather than the two alternatives, in the order the reasons
bind.** A public listener with TLS and a bearer token is the obvious cheap answer
and it is refused in Alternatives: it puts the door on the internet, where the
population that can attempt the credential is everyone, and where the credential
is the *only* thing between a stranger and the store. An SSH tunnel or a reverse
proxy the owner runs is genuinely defensible and is refused for a narrower reason:
it terminates somewhere, and the somewhere has to be authenticated, enrolled and
revoked — which is this ADR's §§5–8 with an extra moving part and no overlay
identity to bind them to.

**The overlay does not replace the credential and §7 is why.** An overlay
membership is a fact about a network the owner administers, and networks acquire
members: an ACL edit, a shared node, a device the owner adds for an unrelated
reason. Admitting on membership alone would mean the hub admits on a decision the
owner never made *at the hub*. That is the failure ADR-0017 §3's own
recipient-authorisation condition names in a different context — authorisation
that "traces to a user decision" — and it is the one condition from that list
whose subject survives the move to this boundary.

### 3. What the coordination metadata discloses, and that the disclosure is accepted

**#664 flags this as part of this decision and it is faced here rather than
absorbed.** An overlay whose control plane is operated by a third party tells that
operator things about the owner, and those things are not the payload.

> **Normative.** Accepting a third-party-operated overlay control plane discloses
> to its operator: the set of devices on the overlay and the account identity that
> owns them; each device's name, platform and public key; the network endpoints
> each device is reachable at; and the times at which each device is online and
> attempts to reach another. That disclosure is accepted. It discloses no request,
> no response, and no byte of the store, and an overlay requiring the operator to
> see any part of a request or a response is refused by §2.

**Its honest classification is Tier 1, and it is stated rather than argued down.**
Device names, endpoint addresses and online times are facts about where the owner
is and when they are working; ADR-0004 §1 puts "anything identifying the user" at
Tier 1. The claim this ADR makes is not that the disclosure is nothing. It is that
it is bounded, enumerable, and small against what it buys — a door that is not on
the public internet — and that the owner is the one accepting it.

**ADR-0004 §2's telemetry clause is examined and found unengaged.** That clause
says "telemetry is off by default and there is no data egress for observability",
and its subject is instrumentation of *this system*. Coordination metadata is what
a network needs to route, produced by an agent the owner installed, about devices
rather than about the assistant. The opposite reading is available — it is egress,
and it is metadata — which is why it is examined here rather than passed over.
Nothing about ADR-0004 §2 changes either way (§12).

**ADR-0004 §2's residency clause is examined and found unengaged, on ADR-0017
§1's own reasoning.** "All persistent data lives on the user's machine… no cloud
storage by default" is about data at rest. The store does not move: the hub keeps
exclusive ownership of the databases in its data directory (ADR-0083), a spoke
holds nothing authoritative (ADR-0094 §9), and nothing here puts a record in a
remote service. ADR-0017 §1 declined to read that clause and left it to #95; this
ADR declines the same, and for the same reason — narrowing a ratified clause it
does not supersede.

> **Normative.** The self-hosted control plane is the named exit from §3's
> disclosure and it is not a new decision. Standing one up removes the third party
> without changing any clause of this ADR; it is an operating act, and this ADR
> neither schedules it nor makes it a precondition on anything.

**Revisit when** the chosen overlay's operator changes what its control plane
collects, such that §3's enumeration stops being accurate. The enumeration is the
thing that was accepted; a disclosure beyond it was not.

### 4. Both ends authenticate the peer, and neither takes the peer's word for it

ADR-0084 §1 has the *client* authenticate the *server* by reading the peer's
credentials from the kernel, and gives the reason: filesystem checks are "a walk
over topology the operator controls, and a walk can be wrong". `SO_PEERCRED` has
no analogue across a network, so the obligation is restated in terms of the fact
rather than the syscall — which is what ADR-0084 §1 did for the same rule across
platforms.

> **Normative.** Before admitting a connection on the remote listener, the hub
> obtains the connecting device's overlay identity from the overlay agent running
> on the hub's own machine, over a local interface. It may not take that identity
> from anything the peer asserts, and it may not obtain it by a call that leaves
> the device. A connection whose overlay identity cannot be obtained is refused.

> **Normative.** Before sending anything on the remote transport, the client
> obtains the hub's overlay identity from the overlay agent on its own machine and
> refuses unless it equals the identity recorded when this device was enrolled.
> ADR-0084 §1's peer-credential check governs the loopback transport and is
> unavailable here; this clause stands in its place, in the same direction.

**The second clause is the one that is easy to omit, and omitting it is the whole
of the attack.** Without it, any node on the overlay that can occupy the hub's
address — or that the client can be pointed at by a configuration edit — receives
the utterance and everything the session carries, exactly as ADR-0084 §1's
replaced-socket case does on one machine. Mutual authentication is what makes the
credential in §7 a proof of *this pair* rather than a bearer token the client will
hand to whoever answers.

**Querying the local overlay agent is not egress.** It is a call to a daemon on
the same machine over a local interface, in the class ADR-0084 §1 already reasoned
about: "a loopback listener moves bytes between two processes on one machine; it
engages neither clause."

### 5. A device is the unit of admission; it is not a principal, not a spoke, and not a grant

> **Normative.** A **device** is the unit of admission to the remote listener: one
> machine, identified to the hub by one overlay identity. Admission is decided per
> device and revocation acts on a device.

> **Normative.** A device is not a spoke and a spoke is not a device. One device
> may run several spokes (ADR-0094 §1), and every spoke reaching the hub over the
> remote listener is admitted by, and expelled with, the device it runs on. No
> obligation of ADR-0094 is conditioned on which device a spoke runs on, and this
> ADR adds none that is.

**The vocabulary is related to ADR-0094's rather than parallel to it, which §1 of
that ADR makes a requirement and not a courtesy.** ADR-0094 fixes one kind of
attachment and forbids conditioning a rule on a profile name; a "remote spoke" is
therefore not a new kind of thing and this ADR does not make one. What it adds is
an axis ADR-0094 does not have: a spoke reaches the hub across a *process*
boundary, and some spokes now also cross a *device* boundary. Admission is the
device-boundary question. Everything ADR-0094 binds — the release gate, the
doorbell rule, the band ceiling, the custody obligations — is unchanged and still
binds the spoke.

> **Normative.** This ADR sets no spoke's band ceiling and raises none. A spoke
> running on an enrolled device is bound by ADR-0094 §5 exactly as it is on the
> hub's own machine, and being remote neither raises a ceiling nor supplies one.

**Whether being remote should *lower* a ceiling is left open, deliberately, with
its condition.** ADR-0094 §10 defers all `core` surface for a spoke identity, a
capability descriptor and a band-ceiling field to the decision that fires "when a
**second** spoke exists". A second *device* is not a second spoke — the CLI
running on a second laptop is the same profile exercising the same capability —
so that trigger does not fire here, and deciding a ceiling policy with one spoke
in hand is exactly the standing ADR-0094 §10 says it does not have.

> **Normative.** A device is not a principal. Enrolling one adds no account, no
> asserting identity and no set of data rights, and no ADR or lane may cite this
> one to add any of the three (ADR-0099 §1). Every enrolled device carries the
> owner's single principal, and a belief produced through a spoke on an enrolled
> device is the owner's exactly as it is on the hub's own machine.

> **Normative.** Enrolment is not a grant in ADR-0097's sense and no surface may
> present it as one. ADR-0097 keys a grant on a reader's declared identity and
> scopes it to reading a source; a device is neither a source nor a reader, and
> enrolling one authorises no read of anything. Nothing here discharges any part
> of #629.

**Both refusals exist because the opposite reading is the natural one.** "Device
identity" is the vocabulary of multi-user systems, where a device is admitted
*as somebody*; here it is admitted *for the owner*, and ADR-0099 §1 forbids a
second principal without superseding it. And an enrolment record with a revocation
looks so much like ADR-0097's grant record that a later lane could reasonably fold
them — at which point revoking a device would start reading as revoking a source's
grant, which is a different act with a different subject.

### 6. Enrolment is an act the owner performs at the hub, and it mints one credential

> **Normative.** A device is enrolled only by an explicit act of the owner
> performed at the hub — on the hub's own machine, over ADR-0084 §1's loopback
> transport or a hub-local entry point. No connection to the remote listener may
> create, extend or modify an enrolment. No model, plan, tool, scheduler job,
> `Settings` value, migration or upgrade may create one.

> **Normative.** Enrolment mints one **credential**: a value of at least 128 bits
> drawn from the operating system's cryptographic random source, disclosed to the
> owner once at enrolment and never again. The hub retains only a verifier from
> which the credential cannot be recovered, so the hub holds no device's Tier 0
> secret at rest.

> **Normative.** The credential is compared in constant time, and the verifier is
> a cryptographic hash rather than a memory-hard password derivation. The clause
> above makes the credential machine-generated and high-entropy, so there is no
> guessable secret for a work factor to defend; what a comparison can still leak
> is timing.

**Naming the hash's shape rather than leaving it to the lane is deliberate, and
the reason is that the obvious review finding is wrong here.** "Use Argon2" is
correct advice about a secret a human chose and wrong about 128 bits of `urandom`:
an attacker cannot enumerate the space at any work factor, and a memory-hard
derivation on the hub's admission path is a cost paid on every connect for
nothing. Recording the argument is what stops the next lane from re-deciding it in
either direction.

> **Normative.** The credential's encoded form leaves the connect payload within
> ADR-0085 §8d's 256-byte bound, which this ADR does not raise. A scheme whose
> credential does not fit — a certificate chain, a signed token carrying claims —
> is refused by this clause rather than by amending ADR-0085.

**That bound is load-bearing and it selects the design.** ADR-0085 §8d bounds each
connect payload at 256 bytes and the client identifier at 64, and states that
"every other member's encoded width is bounded by the payload bound, whatever
members a later protocol version adds" — so the credential is already bounded and
nothing has to change for it. An opaque high-entropy secret is a few tens of bytes
and fits with room; a token carrying claims does not, and would have forced an
amendment to a ratified clause in service of a design this ADR has no need for.

> **Normative.** The enrolment record — a device's overlay identity, its
> credential verifier, when it was enrolled and when it was revoked — is durable
> state the hub owns, held inside `data_dir` under ADR-0083's layout, written by
> the hub alone, and surviving a hub restart. Which store holds it is the
> implementing lane's, under ADR-0083 §6's discipline.

> **Normative.** A revocation is recorded rather than erasing the enrolment it
> revokes, so the record says what the owner actually decided and when.

**Where the record lives makes it an artifact of whatever backup decision lands,
and this ADR rules nothing about backup.** Placing it inside `data_dir` is the
whole of what is decided; whether and how a backup carries it belongs to the
backup/restore decision running as its own lane (#883), and this ADR neither
anticipates nor constrains it.

> **Normative.** On the device, the credential is Tier 0 under ADR-0004 §1. It is
> never written to any store, never committed, and never reaches a log, an audit
> record or an error message. `core/logging.py` already redacts a key containing
> `credential`, and no implementation may give it a name that redaction misses.

> **Normative.** How the credential is held at rest on the device follows ADR-0004
> §3, which this ADR does not narrow. If the implementing lane's answer requires
> the `SecretStore` Protocol that ADR-0004 §3 provisions and `core/protocols.py`
> does not declare, that Protocol is its own contract ADR, merged before anything
> implements against it (golden rule 5, ADR-0015 §5); this ADR does not mint it.

**The gap is recorded rather than closed, because closing it here would be minting
a Protocol in an ADR about a hop.** ADR-0084 §11 called `SecretStore` "the obvious
home" for a credential, and the tree does not have one — today's Tier 0 credential
is read from the process environment by the provider SDK. The device credential
joins the provider credential in whatever change builds that Protocol; an issue
carries it (Consequences).

### 7. The remote admission rule, and why it inverts ADR-0084 §2's

> **Normative.** On the remote listener a connect frame is admitted only when both
> hold: the overlay identity §4 obtained names a device whose enrolment is live,
> and the frame's credential member verifies against that device's verifier.
> Neither fact admits a connection on its own.

> **Normative.** On the remote listener a connect frame whose credential member is
> absent or empty is refused, with a distinct error naming the reason, and the
> connection closes after the refusal — the decoded-frame treatment ADR-0084 §3
> gives the handshake's own refusals.

> **Normative.** ADR-0084 §2's rule is unchanged on the loopback transport: there a
> non-empty credential is still refused with `credential_not_supported`. The two
> listeners hold opposite rules, and a hub running both applies each rule to its
> own listener.

**One principle stands behind both rules and it is ADR-0084 §2's own.** That
section refused to accept-and-ignore a credential because "a client that presents
a credential and is admitted has been told, by admission, that its credential was
checked", and nothing on loopback checks anything. Invert the transport and the
same sentence produces the opposite rule: a client admitted without presenting a
credential, on a listener whose whole purpose is that something is checked, has
been told by admission that it was admitted on a check that never ran. **Admission
never asserts a check that did not happen** — that is the rule, and the two
listeners are its two cases.

> **Normative.** A refusal on the remote listener distinguishes an unenrolled
> device, a revoked device, and a credential that did not verify, in the error it
> returns and in what the hub logs. It never includes the credential or the
> verifier in either.

**Distinguishing them is a deliberate choice against the reflex, and the reflex is
worth stating.** A login surface is usually built to say only "no", so that a
prober cannot enumerate accounts. That reasoning does not transfer: the population
that can reach this listener is the overlay's members (§2), and the overlay's
members are the owner's own devices, so the disclosure is to a party already
inside the boundary. Against that, an owner who cannot tell "I never enrolled this
laptop" from "I revoked it last week" from "I pasted the wrong string" is
ADR-0083's ruling 4 failure — the hub is unreachable for a reason that is not
legible. Legibility wins, and it wins because §2 made the audience small.

> **Normative.** The remote listener is held to ADR-0084 §3's frame ceiling, read
> deadline, connection ceiling and pending-handshake ceiling, exactly as the
> loopback listener is. Adding it may not let the hub's total concurrent
> connections exceed `hub_max_connections`, and a connection awaiting admission on
> the remote listener counts against `hub_max_pending_handshakes`.

**That clause exists because a second listener is the natural place to double a
budget by accident.** ADR-0084 §3 set both ceilings against a *resident* process
being held down by a peer that connects and stops sending, and the remote listener
is where an unauthenticated peer first becomes possible at all. Two listeners each
honouring the figure independently would mean the hub honours neither.

> **Normative.** A refusal code this section introduces is a lowercase token, not
> a class name, so a client can tell a transport refusal from a reconstructable
> `AssistantError` by the code alone (ADR-0085 §9, §10a). It appears on the
> handshake path and never on the call path.

**That last clause has an existing enforcement point the implementing lane has to
find, and it is easy to miss.** `_raise_reply_error` (`wire/client.py`) carries a
closed set of handshake-vocabulary codes so that one arriving on the *call* path
is raised as a protocol fault rather than handed to `raise_from_payload`, which
expects a class name. A new refusal code that is not added to that set would reach
an older client's reconstruction path as an unknown class. The rule is the clause;
the set is where the tree currently keeps it honest.

### 8. Revocation is prospective, and two levers exist that do not substitute for each other

> **Normative.** Revoking a device is an explicit act of the owner at the hub.
> After it, the device's credential verifies against nothing: it admits no new
> connection on the remote listener, from any overlay identity and on any device.

> **Normative.** Revoking a device closes any connection that device currently
> holds.

> **Normative.** Revocation is prospective. It does not retract what the hub
> already sent to that device, and no surface may present it as though it did.
> What a revoked device holds when it is expelled, it keeps.

**The prospective rule is ADR-0097's shape applied to a different subject, and
stating the residual is the point.** ADR-0097 ruled that revoking a grant stops
future reads and does not reach what was already read; the same honesty is owed
here, and more sharply, because a device is a whole machine with a screen and a
disk. Revocation is a statement about the *door*, not about the past. A surface
that renders it as "this device no longer has your data" would be asserting
something the hub cannot know and did not do.

> **Normative.** Removing a device from the overlay and revoking it at the hub are
> independent acts and neither substitutes for the other. The hub's revocation is
> the one that binds: a device removed from the overlay but not revoked would be
> admitted again if it rejoined, and a device revoked but not removed reaches the
> listener and is refused there.

**Naming the ordering is what keeps the two-fact rule from degrading into one.**
The tempting operating shortcut is to revoke at the overlay alone, because that is
the lever an operator reaches for first and it appears to work. It leaves a live
credential whose only remaining protection is a network membership the owner can
restore by accident.

> **Normative.** Re-enrolling a device that was revoked mints a new credential
> under §6 and is a new enrolment. A revoked credential is never reinstated.

### 9. This change does not bump `PROTOCOL_VERSION`, and here is the rule that decides when one does

> **Normative.** No lane implementing this decision changes `PROTOCOL_VERSION` for
> it. The remote listener adds no member to the connect exchange, changes no
> frame's encoding, and changes no method's arguments or results; what differs
> between the two listeners is which connect frames are admitted, which is policy
> reported in the ratified error frame rather than a change to what a frame is.

**The freeze ADR-0084 §3 bought is what makes that true rather than merely
convenient.** Its permanent clause fixes "the length prefix, the UTF-8 JSON codec,
and the connect frame's version member" in every version and permits a later
version to add members. This adds none: `CONNECT_CREDENTIAL` is a member ADR-0084
§2 defined and `wire/envelope.py` already writes and reads. A peer at version 2 on
either listener exchanges exactly the frames it exchanges today.

**#872 is settled as to the rule and as to who checks it, and scoped as to the
mechanism.** #872 asks three questions: is there a stated rule that an
incompatible change to a wire-carried `core` type bumps the version, who checks
it, and is the check mechanical or a review obligation. The first two are answered
here because the hop is the deployment that makes them real — two machines
upgraded by hand — and answering them anywhere else would leave the first remote
spoke resting on nothing.

> **Normative.** `PROTOCOL_VERSION` is bumped by any change after which a frame a
> conforming peer at the new version may send would be refused by a conforming
> peer at the old version, or would be accepted by it with a different meaning.
> The obligation is on whoever makes the change, in the same change.
>
> It reaches, without limiting itself to: a change to the encoding of a
> wire-carried value (ADR-0087 §8's rule, which is unchanged and is not restated
> by this one); a change to a wire-carried `core` type that makes a value one peer
> emits invalid for the other, whether the change widens or narrows the type; and
> any change to the promoted surface's method set or to a method's arguments or
> results (ADR-0085 §3).
>
> It does not reach: adding a listener, changing which connect frames a listener
> admits, or adding a refusal code on the handshake path. The connect exchange's
> decodability is frozen across versions (ADR-0084 §3), and a handshake refusal an
> older peer cannot name is still rendered from its message rather than refused.

**The widening limb is the one the corpus has already been caught by.** ADR-0122
made `FeedbackEvent.memory_kind` optional — a widening — and a new client sending
`"memory_kind": null` to an old hub fails validation there. Read as "narrowing
bumps, widening is safe", the rule would have got that case wrong, which is why it
is stated directionally: the test is whether *some* frame one side may send is
unacceptable to the other, in either direction.

**Adding a method bumps, and that is the honest consequence rather than an
oversight.** A sixteenth method on the promoted surface is a request an older hub
answers with a failure the client did not ask for. Before the hop that cost
nothing, because both halves shipped from one environment (ADR-0084 §3). After the
hop it is the case ADR-0084 §3's exact-match rule exists for, and a bump is what
makes the half-finished upgrade legible instead of arriving as an unexplained
error inside a call.

> **Normative.** Compliance with the clauses above is a review obligation on any
> change to `core/types.py`, to the promoted surface's method set, or to the wire
> encoding. This ADR decides no mechanical check and creates none.

> **Normative.** A mechanical check for those clauses is owed. Its shape is a
> `wire` decision wanting implementation contact, it is not this ADR's, and it is
> not a precondition on the remote listener landing.

**Declining to design the check here is a scoping answer and not a dismissal.**
#872's own framing is right that "a rule nobody checks reproduces the same silent
failure one layer up". What it needs is a schema fingerprint over the wire-carried
types, computed and compared in the gate — a real design, with real decisions
about what is in the fingerprint and what a false positive costs, and none of them
answerable from an ADR about a hop. An issue carries it (Consequences).

### 10. What this does not authorise

> **Normative.** The hub still never dials a spoke. ADR-0094 §2 is unchanged: every
> connection between the hub and a spoke is established by the spoke, and nothing
> in this ADR — including an overlay on which the hub can address the device — is
> permission to initiate one.

**That clause is here because this is the first moment the forbidden thing becomes
easy.** ADR-0094 §2 observed that on loopback the direction is invisible, "either
party can connect to either", and that the direction becomes observable at the
first remote spoke — which is now. An overlay gives the hub a routable address for
every enrolled device, and the shortest path to a notification is to use it. §2
forbids that, and this ADR restates the prohibition rather than leaving it to be
inferred from an ADR whose subject was a microphone.

> **Normative.** This ADR decides no `core/protocols.py` or `core/types.py`
> surface. An implementing lane that finds it needs either stops and owes its own
> contract ADR, merged first (golden rule 5, ADR-0015 §5).

> **Normative.** No lane may read this ADR as deciding any part of a delivery seam
> for proactivity. That seam is the additive wire decision ADR-0094 §10,
> ADR-0084 §11 and ADR-0042 §5 already defer, and it is unmoved by this one.

**So the answer to whether this transport choice forecloses or enables push is
neither, and the distinction is worth being exact about.** The overlay makes the
*network* path bidirectional — before it, the hub had no address for the device at
all. What stands between that and a delivered notification is not networking; it
is ADR-0094 §2's direction rule and ADR-0084 §3's serial envelope. The delivery
seam is therefore a wire decision that this hop supplies a prerequisite for and
does not answer, and a leg-10 lane that reads an overlay address as a delivery
channel has skipped the two clauses that actually govern.

> **Normative.** Nothing here authorises a second hub. ADR-0094 §1's reservation of
> "peer" for a hub-to-hub relationship is untouched, and an enrolled device is a
> device the owner's one hub serves, never a second one.

**Also not decided, and named so nobody reads silence as an answer:** backup and
restore, which is its own lane (#883); what the hop feeds once it lands — a device
as a context facet, a device-scoped permission input, and the audit trail's
"approved from where" — which `docs/roadmap.md`'s leg 9 carries as inherited
follow-ups to be filed when the listener lands, not decided here; the live calendar
(#883); and the grant model (#629), which §5 declares this ADR does not touch.

### 11. The validation plan, on two commodity devices

The owner has ruled that the arc completes without a dedicated box (#882), and
that two processes on one machine exercise the protocol path but not what
ADR-0017 §1 governs. So the plan names a **second commodity device** — a second
laptop or equivalent, on the overlay — and it is the second device that makes the
plan a test rather than a rehearsal.

> **Normative.** The remote listener is not ruled validated until every check
> below has been performed with the hub on one physical machine and the client on a
> second physical machine the owner already has, both on the overlay.

1. **The hop carries an ordinary session.** From the second device, a turn
   completes end to end: an utterance, a response, a belief read back, and a parked
   confirmation resumed through `pending_confirmations()` — ADR-0084 §7's
   enumerate-and-re-mint, now across a device as well as a process.
2. **The loopback transport is unchanged.** On the hub's machine the CLI still
   serves over `hub.sock`, and a connect carrying a non-empty credential is still
   refused with `credential_not_supported` (ADR-0084 §2).
3. **The remote listener fails closed in all three ways.** A connect with no
   credential, a connect with a wrong credential, and a connect from an overlay
   member never enrolled are each refused, each naming its own reason (§7).
4. **The door is not on the internet.** From a network path outside the overlay,
   the listener does not answer; and the hub refuses at load a configuration that
   would bind it anywhere §2 forbids.
5. **Mutual authentication holds.** The client refuses a hub whose overlay
   identity is not the one recorded at enrolment (§4).
6. **Revocation works and is prospective.** Revoking the second device closes its
   live connection, its next connect is refused naming revocation, and re-enrolling
   mints a new credential against which the old one still verifies against nothing
   (§8).
7. **The record is durable.** Enrolment and revocation both survive a hub restart
   (§6).
8. **No version bump was needed.** Both halves report the same
   `PROTOCOL_VERSION` and the handshake passes on both listeners (§9).
9. **The relayed path is exercised.** Where the overlay cannot establish a direct
   path between the two devices, the session still completes over the overlay's
   relay — which is the case §2's end-to-end encryption clause is written for.

**What this plan does not prove, stated so nobody reads it as more than it is.**
Two devices on one overlay account do not exercise a hostile network, a device the
owner does not control, or an overlay operator behaving badly. A laptop hub sleeps,
so it tests reach and not duty cycle — the cost #879 already priced. And a single
enrolled device shows that admission and revocation *work*, not that they scale to
a set; the second-spoke surface ADR-0094 §10 defers is still deferred.

### 12. Amendment records under ADR-0082 §1

ADR-0082 §1 requires the judgement to be made in this ADR's text, naming the
clause and applying ADR-0070 §1's test: would a reader holding only the earlier
ADR now act differently, or read one of its clauses more widely than it now holds?

**ADR-0017 is partially superseded, and this change writes the record.**

Two clauses fail the test:

- **§1's rule.** "User data may leave the device only from `models/` or from a
  designated integration seam inside `tools/`; every other egress is a bug." §1
  above adds a third boundary, so the sentence becomes false. A reader holding only
  ADR-0017 would read the hub's remote listener as a bug and would refuse to build
  it — which is exactly what ADR-0084 §1 records that reader doing.
- **§2's framing of the boundaries as two.** Its heading is "The two boundaries"
  and its text enumerates `models/` and `tools/` as the complete set. Nothing in it
  becomes false about either boundary; what fails is the second limb of the test —
  a reader reads the enumeration more widely than it now holds, as the closed list
  of everything that may transmit.

**What survives, which a reader needs as much as what falls:**

- **§3's fourteen conditions stand entirely**, and they still govern designating
  the `tools/` seam and nothing else. §1 above states that no lane may cite this
  ADR toward them.
- **§4's argument survives and is what licenses this change.** Its finding that
  the rationale is about egress being accountable "never about the number of
  accountable places", and that "'One' was never argued for", is the ground §1
  above stands on. Two was a count as well.
- **§2's account of `models/`** — what it transmits, and the three pre-existing
  controls it lacks (issues #83, #74, #89) — is untouched, as is its ruling that
  `tools/` is approved and undesignated.
- **§5's instrument argument, §6's treatment of the prior amendment, §7's record of
  what acceptance did to ADR-0004, §8's deferred injected capability and §9's open
  list** are all untouched.

**The instrument is partial supersession rather than amendment**, and the test is
ADR-0070 §1's, which is categorical: "Any change to what was decided requires a new
ADR that supersedes the old one — wholly, or partially." "Every other egress is a
bug" is a decision, and this ADR authorises one of the others. ADR-0083 §15's
stacked-addition carve-out does not reach it on its own stated test — that rule
holds where "the deferring sentence **stays true** and now has an answer", and
ADR-0017 §1's sentence does not stay true.

**ADR-0017's `Status` therefore takes the leading `Partially superseded by`
token**, with the appended dated note ADR-0070 §1 requires in every case. Under
ADR-0082 §2 a leading-token line carries no amendment qualifier beside it, and
there is none to move — ADR-0017's line was plain `Accepted`. The record is
append-only: the superseded sentences are left standing exactly as written, and
the note records that they became false and which clause of this ADR did it.
**It lands in this change**, so ADR-0017's `Status` never names an ADR that does
not exist; while this ADR is `Proposed` the line names a supersession that is
drafted rather than ratified, the form ADR-0075 established and ADR-0084 §12
applied.

**The citation fan-out was enumerated semantically rather than by phrase**, which
is the method ADR-0084 §12 recorded after its own lexical search missed ADR-0077.
Every ADR naming ADR-0017 was read for *what it relied on it for*:

- **ADR-0084 — no record owed.** §1 relies on ADR-0017 §1 to conclude that "the
  remote leg therefore owes its own ratified egress decision", and §11 holds the
  same deferral. Both sentences **stay true and now have an answer**, which is
  ADR-0083 §15's stacked addition on its own test — the deferral is discharged by
  the ADR it named. §1's argument that a loopback listener engages neither clause
  is untouched, because this ADR does not change what a loopback listener does.
- **ADR-0004 — no record owed.** §1's tiers are used as given. §2's residency and
  telemetry clauses are examined in §3 above and found unengaged, which is the
  ADR-0083 §15 pattern and changes nothing. §3's keyring rule is applied, not
  narrowed: §6 above requires the credential to be held under it and declines to
  invent a mechanism.
- **ADR-0094 — no record owed.** §10a's marked clause is "Nothing in **this ADR**
  authorises a spoke that is not on this machine", a statement about what ADR-0094
  authorises, and it stays true — ADR-0094 still authorises none. §2's connection
  direction is restated and reinforced by §10 above, not narrowed. §5's ceiling and
  §10's deferral of spoke surface are left exactly where they are.
- **ADR-0083 — no record owed.** §3's startup sequence, §6's durable-state
  discipline and §8's package rule are used as given; the remote listener starts
  where ADR-0084 §1 put the loopback listener, at step 6.
- **ADR-0085 — no record owed.** §8d's 256-byte connect-payload bound is used as
  given and §6 above designs inside it rather than raising it; §8d's own sentence
  that "every other member's encoded width is bounded by the payload bound,
  whatever members a later protocol version adds" is what makes the credential
  already-bounded. §9's transport-condition list gains a sibling refusal of the
  same class, which is a stacked addition — §9 does not state the list closed.
- **ADR-0087 — no record owed.** §8's rule that a vector change bumps the version
  is used unchanged and is not restated by §9 above; §9's clause reaches a class §8
  explicitly did not ("no clause generalises it", #872), so it adds an obligation
  rather than widening one. §8's "None of this reaches the connect exchange"
  stays true and §9 above agrees with it.
- **ADR-0097 — no record owed.** §5 above declares that enrolment is not a grant
  and adds nothing to `SourceGrants`, `SourceGrantStore` or the grant vocabulary.
  Every sentence of ADR-0097 stays true about its own subject.
- **ADR-0099 — no record owed.** §1's single principal is relied on and reinforced
  by §5 above; §5 of that ADR — a second household member is served by their own
  hub — is untouched, an enrolled device being a second machine and not a second
  person.
- **ADR-0042, ADR-0052, ADR-0044 — no record owed.** §7's stateless client,
  ADR-0052 §1's enumerate-and-re-mint and answer-time freshness are used as given
  and unchanged; §11 above exercises them across a device rather than redefining
  them.

## Consequences

- **The hop is authorised and bounded.** A third egress boundary exists, its
  recipient set is the devices the owner enrolled, its path is an overlay the owner
  administers, and its payload is end-to-end encrypted with no third party holding
  a key.
- **ADR-0017 §1's rule is superseded** (§12), and its §3 conditions are untouched.
  The next lane that wants to designate the `tools/` seam inherits the same
  fourteen conditions it inherited yesterday.
- **A credential-less connect on the remote listener is refused**, which inverts
  ADR-0084 §2's loopback rule and leaves it standing. A hub running both listeners
  runs two opposite rules from one principle.
- **Admission needs two facts.** An overlay membership alone admits nothing, and a
  stolen credential alone reaches nothing, because the listener is not on a network
  a stranger can route to.
- **`PROTOCOL_VERSION` does not move for the hop**, and the wire gains the rule it
  has been operating without: #872's question is answered as to the rule and as to
  who checks it, and scoped as to the mechanism.
- **What is harder.** Enrolment is durable state the hub owns, so it is one more
  thing that must survive a restart and one more thing a restore has to think
  about. The owner acquires an operating obligation with two levers — revoke at the
  hub, remove from the overlay — and §8 rules which one binds. And a change to a
  wire-carried `core` type now carries a version obligation that nothing mechanical
  enforces yet.
- **What is accepted.** A bounded, enumerated disclosure of coordination metadata
  to a third-party operator (§3), with the self-hosted control plane as its named
  exit.

**Follow-on, filed as issues with this change:**

- **The mechanical version check** §9 rules is owed — a schema fingerprint over the
  wire-carried types, compared in the gate — with #872 as its ground.
- **The device credential joins the provider credential** in whatever change builds
  the `SecretStore` Protocol ADR-0004 §3 provisions and `core/protocols.py` does
  not declare (§6).
- **What the hop feeds** — a device as a context facet, a device-scoped permission
  input, and the audit trail's "approved from where" — is filed when the listener
  lands, as `docs/roadmap.md`'s leg 9 directs (§10).

**Revisit when** the hub moves to a machine the owner does not carry, at which
point §3's duty-cycle cost disappears and §2's binding rule wants re-reading
against a host that is always reachable; when a second *spoke* exists, which is
ADR-0094 §10's trigger for the surface §5 declines to mint; or when the chosen
overlay's operator changes what §3 enumerates.

## Alternatives considered

- **A public TLS listener with a bearer token.** The cheapest answer and the one
  most systems ship. Rejected in §2: it puts the door on the internet, where the
  population that may attempt the credential is everyone rather than the owner's
  own devices, and where the credential becomes the single thing between a stranger
  and a store of Tier 1 data. It also forfeits §2's second fact entirely — there is
  no transport-attested identity to require alongside the credential — so the
  two-fact rule collapses into one.
- **The overlay alone, with no credential.** Genuinely arguable: the overlay
  authenticates every participant, so a member is already known. Rejected in §2
  because membership is a property of a *network* the owner administers for other
  reasons, and networks acquire members by ACL edits and shared nodes. Admission
  would then rest on a decision the owner never made at the hub, which is precisely
  the recipient-authorisation property ADR-0017 §3 names.
- **The credential alone, with no overlay.** Rejected for the mirror reason: a
  bearer token works from anywhere the listener answers, so its safety is entirely
  a function of who can reach the listener — which is what the overlay decides.
- **Reusing ADR-0084 §1's `SO_PEERCRED` check.** Not available: it reports a uid on
  a local socket and has no analogue across a network. §4 restates the obligation in
  terms of the fact rather than the syscall, which is the move ADR-0084 §1 itself
  made for cross-platform reasons.
- **An SSH tunnel or an owner-run reverse proxy.** Defensible, and rejected in §2
  on a narrow ground rather than a broad one: the tunnel terminates somewhere, and
  that somewhere needs authenticating, enrolling and revoking — this ADR's §§5–8
  with an extra component and no transport-attested identity to bind them to.
- **Modelling a device as an ADR-0097 grant.** The record shapes are nearly
  identical — a subject, an act, a revocation that is prospective — and folding them
  would save a store. Rejected in §5: a grant's subject is a reader's declared
  identity and its scope is what a source may be read for, so a device would be a
  subject the vocabulary cannot describe, and revoking a device would begin to read
  as revoking a source.
- **Giving a remote device its own band ceiling.** Rejected in §5 as decided too
  early rather than wrong: ADR-0094 §10 defers the whole spoke-surface question to
  the decision that fires when a second spoke exists, and a second *device* running
  the same spoke does not fire it. Setting a ceiling here would decide part of that
  surface in an ADR nobody read for it.
- **A signed token carrying claims in the credential slot** — an expiry, a device
  id, a capability set — instead of an opaque secret. Rejected in §6 on a mechanical
  ground before a design one: it does not fit ADR-0085 §8d's 256-byte connect
  payload, so it would have required amending a ratified bound to buy claims the hub
  can read out of its own enrolment record.
- **A memory-hard derivation for the credential verifier.** Rejected in §6: it
  defends a human-chosen secret and there is none, and it puts a deliberate cost on
  the admission path of every connect.
- **A single undifferentiated refusal on the remote listener.** The conventional
  choice, and rejected in §7: the population that can reach the listener is the
  owner's own devices, so it hides nothing from anyone outside, while making a hub
  the owner cannot reach illegible — ADR-0083's ruling 4 failure.
- **Deferring #872's version rule to its own lane.** Rejected in §9: the hop is the
  first deployment in which the two halves can genuinely differ, so deferring would
  ship the case the rule exists for while the rule is still unwritten. What is
  deferred instead is the *mechanical check*, which wants implementation contact
  the prose does not have.
- **Deciding the hop against the dedicated box.** Refused by #882's direction: no
  arc-3 slice may depend on hardware that does not exist, so §11 validates on a
  second commodity device and the box stays an operating act (#879).
