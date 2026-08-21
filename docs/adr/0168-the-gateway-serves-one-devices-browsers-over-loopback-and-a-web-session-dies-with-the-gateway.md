# 168. The gateway serves one device's browsers over loopback, and a web session is minted at the gateway and dies with it

- Status: Partially superseded by ADR-0174 (§2's loopback-only bind clause, §2's one-gateway-one-device clause, §4's sole-admitter clause, and §6's exclusive record enumeration, each only as it reaches a separately configured remote browser listener) and ADR-0175 (§8's read-deadline clause, only as it reaches a connection carrying a response the gateway has not finished writing)
- Date: 2026-08-21
- Partially superseded: 2026-08-21 by ADR-0174 — **four clauses, one listener,
  and the deferral §2 wrote for exactly this is discharged rather than replaced.**
  ADR-0174 is the fourth-boundary decision this ADR's §2 deferred by name, taken
  for `track:web-client` milestone 14 (#1230), whose exit test puts a browser on a
  phone — a device that cannot host a gateway. Every replacement below is scoped
  to a **separately configured remote browser listener**; nothing about the
  loopback listener this ADR was written for changes.

  **Replaced — §2's first clause, only as it reaches a separately configured
  remote browser listener.** "The gateway's browser-facing listener binds a
  **loopback** address and only a loopback address … and no `Settings` value may
  make it do so. A configuration that would have it bind anything else is refused
  at load rather than bound." ADR-0174 §2 authorises a second listener on an
  overlay address, off unless configured on, with the five load-time refusals
  ADR-0124 §2 already gives the hub's own remote listener. A reader holding only
  §2 builds a gateway no configuration can make reachable from another device —
  which is what `src/ai_assistant/interfaces/gateway/server.py` does today, with
  `_LOOPBACK` a module constant deliberately rather than a setting — so this fails
  ADR-0070 §1's first limb.

  **Replaced — §2's second clause's first sentence, on the same scope.** "One
  gateway serves the browsers on its own device." After ADR-0174 §1 a gateway may
  serve browsers on other devices of the owner's overlay, on two facts: an overlay
  identity its own local agent attests (ADR-0124 §4's obligation, which had no
  subject at this door before) and the web session §4 of this ADR already mints.

  **Not replaced — everything §2 says about the loopback listener.** It still
  binds a loopback address and only a loopback address, no `Settings` value may
  widen it, and ADR-0174 §2 keeps it bound whether or not the remote one is.

  **Not replaced — §2's proxy prohibition, which is reinforced.** "Reaching a
  gateway's listener from a second device — by an operator-configured proxy, a
  port forward, a tunnel, or any other means — is user data leaving a device …
  and no clause of this ADR authorises it." Only the parenthetical count of
  boundaries goes stale; a proxy path is outside ADR-0174 §1's enumeration too,
  and ADR-0174 §2 refuses it a second time on a mechanical ground this ADR did not
  have — a terminating proxy destroys the peer identity the new listener's
  admission requires, leaving a header the proxy asserts as the only source, which
  ADR-0124 §4 forbids taking.

  **Not replaced — §2's third clause, which is the one that sent the question
  there.** "A gateway serving a browser on a device that cannot itself run a
  gateway is deferred, not decided. It requires a fourth egress boundary and
  therefore its own ratified decision superseding ADR-0124 §1's enumeration."
  That sentence stays true and now has an answer, which is ADR-0083 §15's stacked
  addition on its own test — the deferral is discharged by the decision it named.

  **Replaced — §4's sole-admitter clause, on that same scope.** "A **web session**
  is the gateway's own admission record for one browser … and it is the only thing
  that admits a browser request." ADR-0174 §4 makes admission on the remote
  listener turn on **two** facts — an overlay identity the gateway's own agent
  attests, and the session — and admits the bootstrap exchange only from a device
  the owner listed at the gateway. A reader holding only §4 builds a door that
  admits a browser the agent cannot place, and mints a session for whoever holds a
  phished bootstrap value. ADR-0174 records that an earlier draft of it called
  this an addition rather than a replacement, reading "the only thing that admits"
  as a claim about sufficiency that a second *necessary* fact leaves standing; the
  reading is defensible and ADR-0070 §1's test is whether a reader acts
  differently, and this one does.

  **Replaced — §6's exclusive record enumeration, on that same scope.** "No such
  record carries anything outside that enumeration." ADR-0174 §3 requires the
  attested overlay identity — a Tier 2 fact about a device — on records about a
  connection on the remote listener, so a reader holding only §6 rejects a record
  that ADR requires.

  **Not replaced — the whole of §4 and §6 besides, and the form of §6's
  enumeration most of all.** What a session is, its entropy and constant-time
  comparison, the verifier-only retention, the process-memory table, death with
  the process, continuous expiry and refusing rather than evicting at the ceiling
  all bind the new listener unchanged. §6's enumeration stays a closed list of
  what may appear rather than a list of what may not, and everything it excludes —
  session halves, verifiers, bootstrap values, bodies, paths, query strings,
  headers, cookies, and anything the hub or a model returned — stays excluded on
  both listeners; so do its trigger clause, its rate bound and collapse key, its
  retention-free emission, the two-value session, the distinct replaced-cookie
  fault, the text-not-markup clause and the content-security policy.

  **Not replaced — §§1, 3, 5, 7–13, none of them.** §3's two pre-session
  exceptions keep their extent — still exactly those two request classes and
  nothing else — and gain prior conditions on the remote listener, a different one
  for each: the assets on an attested overlay membership, the bootstrap exchange
  on a device the owner listed, because §5 has that exchange return "the two
  session values §6 requires" while the assets hand back nothing of the kind. Both
  narrow §3's population and neither widens it. §5's single bootstrap value and
  one mint per process are untouched — ADR-0174 §9 declines to relax them and
  leaves #1320 and #1329 open — as is §9's hub-down legibility, which binds the
  new listener word for word. §7's `Host` and `Origin` checks are restated for a
  listener whose bound authority is not loopback, on §7's own scoping to "the
  loopback names it bound". §8's ten figures are the gateway's totals across both
  listeners rather than each listener's, and its rule that none of those ten is
  nullable is untouched by three new fields outside its table. §10's in-repo
  bundle is what ADR-0174 §1 names as the second half of the new boundary; §11,
  §12 and §13 stand exactly as written.

- **Partially superseded: 2026-08-21** by ADR-0175 — **one sentence of §8, and
  only where a response is still being written.** ADR-0175 is milestone 14's
  surface decision, taken for `track:web-client` (#1230), and it carries every
  message the gateway sends a browser on a **stream**: the body of the response to
  one ordinary request the browser made.

  **Replaced — §8's read-deadline sentence, only as it reaches a connection
  carrying a response the gateway has not finished writing.** "The gateway closes
  it `gateway_read_timeout` after the last complete request it carried." ADR-0175
  §7 rules that such a connection is **not idle** and runs the deadline from the
  completion of the last **response** the connection carried instead, closing no
  connection while a stream on it is open. A reader holding only §8 ends every
  stream ADR-0175 defines thirty seconds after its request arrived — not a stricter
  reading of that surface but a gateway on which it cannot exist — so this fails
  ADR-0070 §1's first limb.

  **Not replaced — every other clause of §8**, on both listeners as ADR-0174 §8
  requires: the ten figures and their load-time refusals, the rule that none of
  them is nullable, the admitted-versus-unadmitted partition, the close on a
  refusal, the one-request bound and `gateway_read_timeout`'s own reach on an
  unadmitted connection, `gateway_max_browser_connections`,
  `gateway_max_pending_connections`, `gateway_max_hub_connections` — which
  ADR-0175 §7 applies to the gateway's delivery connection rather than widening —
  and `gateway_max_request_bytes`, which bounds a request and not a response.
  ADR-0175 §8 adds an eleventh field outside that table, which is the position
  ADR-0174 §8's three were in.

  **Not replaced — §§1–7 and §§9–13, none of them.** §1's biconditional is
  examined in ADR-0175 §12 and found to survive whole: a delivery stream is
  answered from calls on the promoted surface and from nothing else, and §1 makes
  no claim that each request originates one. §3's two pre-session exceptions keep
  their extent; §4's session bounds are applied rather than narrowed, and ADR-0175
  §7 refuses to let a held-open stream refresh the idle timeout for that reason;
  §5's one bootstrap value and one mint per process are untouched and stay
  milestone 16's to revisit; §6's four request classes gain no fifth — a streamed
  turn and a delivery stream are both `assistant-request` — and its record
  enumeration gains nothing beyond ADR-0174 §3's one addition; §7's `Host` and
  `Origin` checks bind unchanged, and its refusal of a connection upgrade is
  applied rather than read as authorising one. §9's legibility is relied on three
  times over. §10's in-repo bundle is what makes ADR-0175 §2 able to leave the
  framing to the implementing lane. §11 and §13 are untouched, and three of §12's
  deferrals — the browser-facing surface with its push carrier, the fan-out of one
  delivery to several browsers, and (with ADR-0174 §11) the streaming carrier — are
  **discharged by the milestone §12 named** rather than replaced, which is
  ADR-0083 §15's stacked addition on its own test. §12's remaining deferrals stand.

- **Amended: 2026-08-22** by ADR-0177 — **§12's fifth deferral is discharged by
  the milestone it names, and no clause of this ADR changes.** That deferral,
  "**Account connection from a browser on another device**", recorded that the
  five connection methods are refused on the hub's remote listener and refused
  client-side, and handed the question to milestone 15. ADR-0177
  (`track:web-client` milestone 15's control-surface decision, #1230, #1365) is
  that milestone's decision and its §3 answers it: **refused**, for the two
  operations that take a `SecretValue`, until ADR-0174 §7's own trigger — a
  transport-layer security arrangement for the remote browser listener — is
  discharged, because a page served over `http://` from a non-loopback overlay
  address is not a potentially trustworthy origin and the browser therefore
  withholds every protection it has for a secret. `disconnect_account`,
  `connected_accounts` and `recent_connection_acts` carry no credential and are
  admitted on both listeners; all five are admitted on the loopback listener; and
  ADR-0151 §13's refusal on the gateway's own hop to the hub is untouched. A
  deferral discharged by the milestone that deferral names is not an amendment of
  the text that deferred it (ADR-0083 §15), so this note records the outcome
  rather than changing §12. Separately, ADR-0177 §1 widens ADR-0175 §6's
  enumeration of browser-reachable operations from five to thirty; that
  supersession is recorded on ADR-0175 and reaches no clause of this ADR — §1's
  biconditional, §6's four request classes and its exclusive record enumeration,
  and §8's figures all bind unchanged (ADR-0177 §12).

- **This is `track:web-client` milestone 13's decision** (#1230). It takes the
  wire seat ADR-0084 §3 and ADR-0094 §2 hold open — a spoke process that reaches
  the hub over the framed wire and exposes the assistant to a browser — and the
  identity question that rides with it, because a browser is not a Tailscale
  device and cannot be enrolled as one.
- **No implementation lands with it.** No `src/`, no `tests/`.
- **It decides no `core/protocols.py` or `core/types.py` surface** (§12), so
  golden rule 5 is not triggered. It does add `Settings` fields (§8), which are
  contract surface in ADR-0054's sense but are not `core` Protocol or type
  surface — the same position ADR-0084 was in for its four transport figures.
- **It supersedes nothing, and it names one supersession it does not write.**
  §13 applies ADR-0070 §1's test clause by clause to every ADR whose text a reader
  might expect this decision to falsify, and finds no record owed on any of them
  but two: **ADR-0004 §3 and §7 are engaged**, because a browser holds its session
  in a browser's storage rather than in the OS keyring, and because the gateway
  reads and verifies that session on a path `permissions/` cannot gate and the
  hub's audit trail does not record. §6 rules that one narrowly scoped
  supersession covering both is a **prerequisite of the implementing lane** — its
  own ADR, merged before any gateway ships — and names the replacements it should
  start from. Nothing implements here, so nothing runs unmet in the interval, and
  that is why this change still touches one file.
- **Two calls were delegated to this lane by #1230 and by `docs/roadmap.md`,
  and both are answered here**: whether this is one ADR or two (§11 — one), and
  whether the front-end bundle lives in this repository or a sibling (§10 —
  this one).

## Context

### What the milestone asks for, and what the tree already has

Milestone 13's exit test is stated in product terms: an `ask` round-trips from a
browser on another Tailscale device, and hub-down is a legible fault in the
browser.

Almost all of the machinery that sentence needs is already ratified and already
shipped. ADR-0084 gives the framed wire, the connect handshake with its
credential slot, the exact-match protocol version and the promoted
`AssistantEngine` Protocol. ADR-0124 authorises the remote hop as a third egress
boundary, fixes the overlay posture, and admits a device on two independent
facts — an identity the overlay attests and a credential the owner minted at the
hub. ADR-0094 fixes that a spoke is one kind of attachment and that the edge
always dials out. The tree carries both transports: `src/ai_assistant/wire/client.py`
holds the loopback client, `src/ai_assistant/wire/remote.py` the overlay one, and
`src/ai_assistant/interfaces/cli.py` picks between them from settings and never
falls back from one to the other.

So the gateway is not a new transport, a new admission scheme or a new contract.
It is a **second adapter** onto a surface that exists — and the whole of what is
genuinely undecided is what happens on the *other* side of it, where a browser
is.

### The hub speaks no HTTP, and that is the shape of the work

There is no HTTP server anywhere in this system. The hub speaks the
length-prefixed JSON envelope and nothing else; the only HTTP in the tree is the
hub and the client each reading their own machine's overlay agent over that
agent's Unix socket, hand-written because ADR-0124 §3 forbids linking the agent
in. Everything a browser needs — a document to load, assets to fetch, a request
shape to send — is surface that does not exist yet and that this decision
authorises someone to create.

### Three doors, and the third has no bit to lean on

The corpus has ruled twice on who may open a connection to this system, and each
ruling turned on what the transport itself already guarantees.

- **Loopback.** ADR-0084 §1 chose a Unix socket over a TCP port explicitly
  because a socket is a filesystem object carrying ADR-0004 §4's `0600` posture,
  which the kernel enforces at `connect()`, where "a TCP loopback port is
  reachable by **every local process and every local user**, and by containers
  sharing the host's network namespace… the only way to make it safe is a
  credential — which §2 deliberately does not ship yet." So the loopback listener
  refuses a credential outright: nothing checks anything, and admitting a
  credentialled connect would manufacture a false belief that something did.
- **The overlay.** ADR-0124 §7 inverts that rule for the remote listener, on
  ADR-0084 §2's own principle: **admission never asserts a check that did not
  happen.** There, a connect frame with no credential is refused, because a
  listener whose whole purpose is that something is checked may not admit a
  client that presented nothing.

A browser is a third door, and it is the first one where neither answer is
available. A browser cannot dial a Unix socket — it speaks HTTP over TCP — so the
gateway must bind a TCP port, and ADR-0084 §1's own sentence is what then binds:
that port is reachable by every local process and every local user, and the only
way to make it safe is a credential. The `0600` bit that carried the loopback
rule is simply not on the table.

### What a browser is not

A browser cannot be enrolled under ADR-0124 §6. Enrolment is an act the owner
performs at the hub, it mints a credential of at least 128 bits, and the client
holds that credential in the OS keyring beside the hub's overlay identity —
`src/ai_assistant/wire/enrolment.py` writes both as one record so a half-written
pair is impossible. A browser has no keyring, no `SecretStore`, and no overlay
identity for ADR-0124 §4 to obtain from the local agent. Nothing about
ADR-0124's two-fact rule has a subject inside a browser tab.

What the browser *is* sitting behind is a process that has both facts. That is
the substantive problem this ADR exists to answer, and it is easy to state
sharply: **the gateway is an amplifier.** It holds one device credential and
serves N callers with it. Every browser it admits speaks to the hub with the
device's whole authority, because the hub cannot tell one browser from another
and — by ADR-0124 §4 and ADR-0131 §4, which forbid a device identity being read
from anything a peer asserts or from any payload — must never be taught to.

### The two calls delegated to this lane

#1230 and `docs/roadmap.md` § `track:web-client` delegate two decisions to this
lane rather than pre-ruling them: whether the gateway seat and web-session
identity are one ADR or two, and whether the front-end bundle lives in this
repository or a sibling. Both are answered in the Decision, at §11 and §10, with
the reasoning rather than only the verdict.

## Decision

We will run the browser gateway as an ordinary spoke that binds a **loopback**
listener for browsers on its own device, admit a browser to it with a **session
the gateway mints and the hub never hears about**, and ship the front end **in
this repository**.

### 1. The gateway is a spoke, it is an adapter, and it authors nothing

> **Normative.** The browser gateway is a spoke under ADR-0094 §1 — an attachment
> reaching the hub across a process boundary over ADR-0084's wire — and it is a
> spoke of the **client** profile, carrying a person. Every obligation ADR-0094
> places on a spoke binds it, and this ADR grants it no exemption from any of
> them.

> **Normative.** The gateway obtains the hub only through the promoted
> `AssistantEngine` Protocol, by the same client the CLI uses and by the same
> selection between the loopback and remote transports. It builds no engine, and
> it never falls back from one transport to the other or to anything else.

> **Normative.** The gateway holds no assistant logic: it composes no behaviour
> the promoted engine surface does not offer, authors no permission ruling, mints
> no confirmation, and opens no store.

> **Normative.** A browser request reaches the promoted engine surface **if and
> only if** the gateway has admitted it under §4 *and* it asks the assistant for
> something — and every request meeting both resolves to calls on that surface and
> to rendering what those calls returned. A static asset, the bootstrap exchange,
> a request §7 refuses and a request §3 refuses reach that surface in no case.

**The routing clause is stated as a biconditional rather than as a rule about
what the gateway forwards, and three rounds of adversarial review are why.** Each
of its one-directional drafts left a class of request obeying one clause of this
ADR by disobeying another: the first sent static assets and the bootstrap
exchange to an engine that has nothing to do with either, and the second sent an
*unadmitted* `ask` there, since it plainly asks the assistant for something and
§3 plainly refuses it. Naming a necessary and sufficient condition covers every
class the gateway can see at once — admitted and assistant-shaped, admitted and
not, unadmitted, pre-session, and refused before the session is read — instead of
covering them one at a time and discovering the next one in review.

**That clause and the one above it are what make golden rule 3 checkable rather
than aspirational**, and they are owed because a long-running HTTP server does not
*look* like a thin adapter. What makes it one is not its lifetime but where the
decisions are: `src/ai_assistant/interfaces/cli.py` already renders, sets exit
codes and holds the device's enrolment secrets, and it authors nothing. The
gateway is that adapter with a different renderer and a different door. The one
thing it adds that is not translation is its own door policy (§3), which is the
same class of thing as the CLI's exit code — a property of the adapter, not of
the assistant.

> **Normative.** The gateway is a subcommand of the existing `assistant` console
> script, not a new one.

**That inverts the standing instinct, and recording why is the point.** ADR-0084
§6 ruled that the hub gets its own console script because a subcommand would put
it in `interfaces`, "which would then have to import `service` — and ADR-0083 §8
forbids anything importing `service` at all", and four later tools joined that
family for the same reason. The rule is about *where the code must live*, and it
does not reach here: a gateway is an interface adapter, its code belongs in
`interfaces` on golden rule 3's own terms, and `interfaces` is exactly what the
`assistant` script already points at. This is the first time that rule has been
examined and found not to fire, which is worth a clause because the instinct now
runs the other way.

### 2. The gateway binds loopback, and the browser is on the gateway's own device

> **Normative.** The gateway's browser-facing listener binds a **loopback**
> address and only a loopback address. It may not bind a wildcard address, an
> address of a physical interface, an overlay address, or any address reachable
> from another device, and no `Settings` value may make it do so. A configuration
> that would have it bind anything else is refused at load rather than bound.

> **Normative.** One gateway serves the browsers on its own device. Reaching a
> gateway's listener from a second device — by an operator-configured proxy, a
> port forward, a tunnel, or any other means — is user data leaving a device, it
> is outside ADR-0124 §1's enumeration of the three authorised boundaries, and no
> clause of this ADR authorises it.

**This is the load-bearing call of the decision, so the arithmetic is worth
showing.** Put the hub on device H and a browser on device B, and there are two
places the gateway can go.

- **On B**, dialling H over the overlay. The browser↔gateway hop never leaves B,
  so it engages no egress clause at all — it is the class ADR-0084 §1 already
  reasoned about, "a loopback listener moves bytes between two processes on one
  machine". The gateway↔hub hop is exactly ADR-0124 §1's third boundary, already
  authorised, already implemented, and already carrying the CLI.
- **On H**, serving B over the overlay. Now the browser↔gateway hop moves user
  data off H, and it is not the hub's remote transport — so under ADR-0124 §1 as
  it stands, "every other egress is a bug". Authorising it means a **fourth
  egress boundary**, superseding a normative enumeration in a ratified ADR.

The first costs nothing and the second costs a supersession, and the milestone's
exit test is satisfied by the first: a browser on B *is* "a browser on another
Tailscale device", and the leg that makes the test a test rather than a rehearsal
— the hop between two commodity machines, which is what ADR-0124 §11 built its
validation plan around — is exercised by the gateway's own connection to the hub.
Taking the boundary that is already ratified is not a compromise here; it is the
same test.

**The proxy clause exists because that is the workaround, and it would be
silent.** `tailscale serve` and an SSH tunnel both terminate on the device and
forward to a loopback port, and either would make a gateway on H reachable from
B without a line of this system's code doing anything. The data still left the
device. Naming it here is what stops a later reader from finding the boundary
technically unbroken because our socket was bound to `127.0.0.1`; whether the
owner may configure their own network is not this ADR's subject, and whether
*this system's* egress ledger covers the result is.

> **Normative.** A gateway serving a browser on a device that cannot itself run a
> gateway is deferred, not decided. It requires a fourth egress boundary and
> therefore its own ratified decision superseding ADR-0124 §1's enumeration, and
> no lane may read this ADR as having granted, prepared or pre-authorised it.

**The condition that fires it is named rather than left to be discovered:** a
browsing device that cannot host a Python process — a phone, which is what
milestone 14's exit test names. That decision belongs to whoever takes that
milestone, it starts from ADR-0124 §§1–8 rather than from scratch, and the cost
of it is exactly what §2 above makes visible in advance instead of at
implementation time.

### 3. A browser session carries the device's whole authority, so it is admitted with that much care

> **Normative.** Exactly two kinds of request are served without a live session,
> and they are the whole of the exception: the front end's own static assets
> (§10), and the single bootstrap exchange of §5. Neither carries assistant
> content, a fact about the hub's state, or a fact about whether the hub is
> reachable.

> **Normative.** Every other browser request is served only when the gateway has
> admitted it under §4, and a request arriving without a live session is refused
> — with a refusal that likewise carries no assistant content, no fact about the
> hub's state, and no fact about whether the hub is reachable.

**The exception is stated as a rule because a bare "serve nothing unadmitted"
cannot be obeyed.** A browser with no session cannot fetch the page from which
it would exchange the bootstrap value, and the exchange itself is by definition a
request no session admits; a rule forbidding both makes §5 unreachable, which is
the shape ADR-0084 §3 rejected in its own terms — "a rule whose own response
violates the adjacent rule is not a rule". Adversarial review found it on the
first round. Enumerating the two rather than carving out "whatever bootstrapping
needs" is what keeps the exception from growing: both are decidable from the
request alone, and neither can carry anything the session exists to protect.

> **Normative.** Nothing about a browser session crosses the wire to the hub. The
> gateway sends no session identity, no session token, and no per-browser
> identifier in any frame; the hub's admission stays exactly ADR-0124 §7's two
> facts about the **device**, and no lane may add a member, an argument or a
> convention by which a browser identity reaches the hub.

> **Normative.** No rule in this corpus may be conditioned on the hub being able
> to tell two browsers behind one gateway apart. It cannot, and ADR-0124 §4 and
> ADR-0131 §4 forbid it being taught to by anything a peer asserts.

**The first clause is the whole of why this ADR could not stop at the transport.**
The gateway passes ADR-0124 §7's two-fact check once, at start, and then answers
whoever reaches its port. An unauthenticated gateway is therefore not a
convenience with a small risk attached — it is a re-export of the device
credential's authority to every local process and every local user on that
machine, performed by a process that itself satisfied the two-fact rule. That is
the two-fact rule defeated one layer out, by a component the rule admitted.

**And it is ADR-0084 §2's principle read a third time.** Admission never asserts
a check that did not happen. On loopback the hub refuses a credential because
nothing checks one; on the overlay it requires one because something does; at the
gateway the port carries no `0600` bit and no overlay identity, so something must
check, and the session is what checks.

### 4. The session is minted at the gateway, held in memory, and dies with the process

> **Normative.** A **web session** is the gateway's own admission record for one
> browser. The gateway mints it, the gateway ends it, and it is the only thing
> that admits a browser request. It is not an enrolment (ADR-0124 §5), not a
> grant (ADR-0097), not a principal (ADR-0099 §1), and no surface may present it
> as any of the three.

> **Normative.** Each half of a session (§6) is at least 128 bits drawn from the
> operating system's cryptographic random source, disclosed to the browser once,
> and compared in constant time against a verifier from which it cannot be
> recovered. The gateway retains the verifiers and never the values themselves.

> **Normative.** The session table is process memory alone. No session, session
> value or verifier is written to any database this system opens, to any file, to
> any log record, to any audit record, or into any error message or diagnostic
> the gateway emits.

> **Normative.** Every session ends when the gateway process ends. A session does
> not survive a gateway restart, and the gateway reconstructs no session from
> anything a browser presents after a restart.

> **Normative.** A session ends at the earlier of its absolute lifetime and its
> idle timeout (§8), and the gateway destroys expired sessions continuously
> rather than at a checkpoint or on the next request that happens to arrive.

> **Normative.** The gateway admits at most `gateway_max_sessions` live sessions
> and **refuses** a mint beyond that ceiling rather than evicting an existing
> session to make room.

**The second and third clauses are ADR-0124 §6's design applied to a smaller
secret**, and taking it verbatim is deliberate: the hub "retains only a verifier
from which the credential cannot be recovered, so the hub holds no device's Tier
0 secret at rest", and the same sentence should be true of the gateway. What it
settles is ADR-0004 §3 **as that clause reaches the gateway's own state, and
nothing further** — a value never written to a store or a file is a value that
clause has nothing to say about (§13). It settles nothing about the values the
*browser* holds: those are Tier 0 outside the OS keyring however little the
gateway retains, §6 rules §3 engaged on them, and the supersession §6 makes a
prerequisite of the implementing lane is owed on them whatever this clause does.
Reading this paragraph as a way to avoid that prerequisite is reading it about a
different subject.

**Refusing rather than evicting is ADR-0131 §2's direction, for its reason.**
That section closes the *second* delivery connection rather than the incumbent
because "newest poll wins" lets anything that can reach the listener evict the
owner's real notifier, and the eviction looks like an ordinary failure. Evicting
the oldest session here would be the same weapon: any local process that can mint
sessions could log the owner out of their own browser, silently. Refusing costs
the caller a legible error and costs the owner nothing, since a session serves a
whole browser rather than a tab.

**Dying with the process is a decision and not an omission, and it is what keeps
this out of `VISION.md`'s way.** A session table that survived a restart would be
durable state on the edge, and ADR-0094 §9's permission is for state that is
"bounded in size and in age, and destroyed continuously rather than at a
checkpoint". Ephemeral sessions satisfy all three of §9's qualifiers as written,
and §13 shows that `VISION.md` §8's stateless-client sentence stays true of them.
Durable ones would owe that argument afresh, which is why they are deferred (§12)
to the milestone that actually asks for them.

### 5. One bootstrap value, disclosed once, exchangeable once

> **Normative.** A gateway process mints one **bootstrap value** at start — at
> least 128 bits from the operating system's cryptographic random source — and
> discloses it exactly once, on its own standard output. It is disclosed nowhere
> else: not in a log record, not in an error, not in a response body, and not in
> any URL a browser transmits to a server.

> **Normative.** The bootstrap value is exchangeable for exactly one session. The
> exchange consumes it, and after it the gateway mints no further session until
> its process is restarted.

> **Normative.** The bootstrap exchange is the only request by which a session is
> minted, and it is the only request other than a static asset the gateway serves
> without one (§3). It carries the bootstrap value and nothing else, it returns
> nothing but the two session values §6 requires, and a failed exchange discloses
> only that it failed — never whether the value was well-formed, whether one is
> still outstanding, or whether a session already exists.

> **Normative.** A gateway that cannot disclose its bootstrap value does not
> start, and reports why.

**"Not in a log record" buys less than it looks like, and saying so is better
than letting a later reader over-read it.** The gateway's structured records go
to standard output too (§6), so the clause keeps the bootstrap value out of the
*structured* stream — out of anything that parses those records, and out of the
redaction chain's reach where a missed key would be the failure — and it does
**not** keep it away from anything capturing the process's output as bytes. A
collector or a redirect receives both. That is the same residual the paragraph
below states for redirection, not a second protection, and it is the reason the
value is single-use rather than durable.

**One value per process life is what makes the exposure argument honest.** The
value sits in the terminal where the owner started the gateway — a place they
already have the standing to read the process's own memory from — it is
single-use, so it is dead the moment they use it, and 128 bits makes guessing it
from the port unavailable to any local process that cannot read that terminal.
An owner who redirects the gateway's standard output into a file has moved the
value somewhere this ADR did not put it; that is the same class of operating act
as a keyring on a shared machine, and it is stated as a residual rather than
defended against.

**One session per process life is a real constraint and it is the honest one for
this milestone.** A second browser means restarting the gateway, and every
session dies with it. The alternative — a durable browser credential the owner
types — is a second Tier 0 secret, a password whose entropy a human chose, and
the shape ADR-0124 §6 argued against on the credential it *did* mint. It becomes
the right conversation when the roadmap asks for it, which it does by name at
milestone 16 ("session persistence"), and §12 defers it there.

### 6. A session is two values, because a cookie is not scoped to a port

> **Normative.** A session is admitted only on **two** values presented together
> — a **cookie half** the gateway set, and a **header half** the front end sends
> — and each is minted with the entropy §4 requires. Neither admits a request
> alone, and a request carrying one and not the other is refused exactly as one
> carrying neither is.

> **Normative.** The cookie half is marked `HttpOnly` and `SameSite=Strict`, is
> set with a path of `/` and no `Domain` attribute, is not readable by any script,
> and carries no persistent expiry.

> **Normative.** A session's lifetime is decided by the gateway alone — §4's
> death with the process and §8's absolute and idle bounds — and by no attribute
> the browser is trusted to honour. No clause of this ADR may be read as making a
> browser's own behaviour part of the guarantee.

**The lifetime clause is separated from the cookie's attributes because an
earlier draft fused them and was wrong about the mechanism.** That draft required
no persistent expiry "so that closing the browser ends it", which a browser
configured to restore its previous session does not do: it can carry both a
session cookie and the origin's storage across a close and reopen, and the
gateway — still running — would admit the restored browser on two halves that
both verify. Adversarial review found it on the third round. The attribute is
kept, because a cookie that asks not to be persisted is still the right thing to
send; what is dropped is the guarantee resting on it. Expiry that the client is
trusted to enforce is not expiry, which is the same reason ADR-0131 §4 refuses to
honour a budget it cannot meet rather than silently shortening one.

> **Normative.** A request carrying a header half that verifies against a live
> session, together with a cookie half that does not verify against that same
> session or more than one cookie of the gateway's own name, is refused with a
> **distinct** fault — reported to the owner as its own condition, and never
> flattened into an expiry, a ceiling refusal or an ordinary absent session.

> **Normative.** The header half is held in browser storage scoped to **scheme,
> host and port** and shared across that origin's tabs, and it is sent only as a
> request header the front end sets. It is never placed in a cookie, in a URL, or
> in storage that outlives the origin's own scope.

> **Normative.** Neither half is placed in any response body except the bootstrap
> exchange's own reply (§5), and neither is placed in a URL, in a log record, or
> in any error the gateway emits.

> **Normative.** Both halves and the bootstrap value are Tier 0 under ADR-0004 §1,
> and two of that ADR's clauses are therefore **engaged**: §3, because they are
> held by the browser rather than in the OS keyring; and §7, because the gateway
> reads and verifies them on the admission path, which `permissions/` cannot gate
> and the hub's audit trail does not record.

> **Normative.** A narrowly scoped supersession of ADR-0004 §3 **and** §7 —
> reaching a browser web session's storage and its admission and nothing else,
> with its replacements named and its record written on ADR-0004 — is a
> **prerequisite of the implementing lane**: its own ADR, merged before any
> gateway ships. This ADR does not write it, and no lane may implement §6 before
> it merges.

> **Normative.** The gateway records its own admission decisions and nothing
> else, and they are two: a session minted, and a request refused on a condition
> of §3, §4, §5, §6 or §7 — a refused mint included. Nothing is recorded for a
> request a live session admits, which is not an admission decision, and nothing
> for a refusal on any other ground, §8's size bound included.

> **Normative.** A refusal is decided on exactly one condition — the first the
> gateway evaluates that the request fails — and every request the gateway
> receives is of exactly one class, out of four: the front end's assets, the
> bootstrap exchange, an assistant request, and any other request. Both are
> enumerations fixed in advance; every record names one class, and every refusal
> record one condition.

> **Normative.** A record carries **only** Tier 2 facts, enumerated: the instant,
> which for a refusal record collapsed under the rate bound below is the interval
> it covers; the request's class; the outcome; and, for a refusal, the condition
> it was refused on and the number of times that class and that condition
> occurred together in that interval.

> **Normative.** No such record carries anything outside that enumeration — no
> session half, bootstrap value or verifier; no request body; no path, query
> string or fragment; no header or cookie; and nothing the hub or a model
> returned.

> **Normative.** Refusal records are rate-bounded rather than written one per
> refused request: within one `gateway_record_interval` (§8) each distinct
> **pair** of class and condition is emitted at most once, so that a caller able
> to drive a refusal cannot drive a record per attempt. A mint record is not
> rate-bounded and needs no bound, because §5 permits one mint per process life.

> **Normative.** The record is emitted through the logging this system already
> configures, and the gateway **retains none of it**. What the gateway holds for
> the clause above is one count per pair of class and condition for the current
> interval and nothing else — a fixed set of integers, reset each interval — and
> it keeps no history of what it emitted.

**The record is scoped to admission decisions and rate-bounded, and both are
corrections rather than refinements.** An earlier draft recorded every admission
and every refusal per request, which is unbounded in the one direction a hostile
local process controls: it can drive refusals as fast as it can open sockets, and
each one obliged a write. That is the failure ADR-0084 §3 spends its ceilings on
and which §8 restates for this process — "a one-shot CLI could shrug this off; a
process that runs for weeks cannot" — reintroduced by a clause of my own. It is
also more edge state than ADR-0094 §9's permission contemplates, since an
unbounded log is bounded in neither size nor age. Recording the *decision* rather
than the request removes the amplification on the admitted path, and the interval
removes it on the refused one. Architecture review found it on the third round.

**The gateway keeps no log, and that is what makes the state question small
rather than a retention policy.** `configure_logging` (`src/ai_assistant/core/logging.py`)
writes structured records through structlog's `PrintLoggerFactory`, whose stream
is the process's standard output, and its `logging.basicConfig` call names no
file — so this system installs no file handler anywhere and **retains no record
it emits**. Where a record then lands and how long it is kept is the operator's,
exactly as it already is for the hub and the CLI. So the admission record adds no store, no
file and no growing artifact. The only state the clauses above create is the
interval's counters — one integer per pair of request class and refusal
condition, reset each interval, which is a fixed set fixed in advance because
both enumerations are. An earlier draft claimed the record was
bounded "in count and in age" like the session table, which was false of a
rate limit and is the wrong frame besides; architecture review was right that a
rate bound is not a size bound, and the answer is that there is nothing retained
for a size bound to apply to. Whether *this system's logging in general* should
carry a retention policy is a project-wide question, not a gateway one, and no
clause here decides it.

**The narrowing is also the closer analogue of what ADR-0124 §7 already does.**
That section has the hub record "each admission and each refusal with the device
it named" — of a *connection*, not of every request carried on one. A session is
this door's connection, so recording its mint and the refusals of the requests it
did not admit is the same act, and recording every request behind a live session
would have been a different and much larger promise. The one place the analogy is
inexact is §7's pre-session refusals, which are decided per request rather than
per session because per request is when they are decidable at all; the interval
bound is what keeps those from becoming the per-request log this paragraph
rejects.

**The record is an enumeration rather than an exclusion list, because an
exclusion list was wrong here and its failure is the instructive kind.** An
earlier draft had the gateway record "the request" and forbade only the session
values — which still admits the utterance out of a refused `ask`, Tier 1 by
ADR-0004 §1, and the bootstrap value out of a failed exchange, Tier 0. ADR-0004
§5 is unqualified that "logs are Tier 2 only" and that Tier 0/1 "must never be
logged", so the draft would have created the leak in the very clause written to
make the access auditable. Architecture review found it. Naming what may appear
is the only form that stays right when a later lane adds a request shape nobody
has thought of yet.

**The collapse key is the pair rather than the condition, and both enumerations
are made total, because a partial one is what kept failing here.** §7 decides a
`Host` or an `Origin` refusal before the request's class matters, so one
condition genuinely spans classes: inside a single interval a static asset, a
bootstrap exchange and an assistant request can each be refused on the same one.
Collapsing on the condition alone then obliges one record to name a singular
class it cannot truthfully name. Keying on the pair costs nothing — the product
of two fixed enumerations is fixed — and it is the move §1's biconditional
already made: cover every case the gateway can distinguish at once, rather than
the cases someone happened to list. Adversarial review found it on the seventh
round.

**Three smaller instances of the same defect were found beside it and are fixed
in the same clauses.** The class list had three values where §1 names four kinds
of request — its own reasoning enumerates "admitted and assistant-shaped,
admitted and not, unadmitted, pre-session", and §12 leaves the request shapes to
the implementing lane — so a refused request that asks the assistant for nothing
had no class to be recorded under; the residual fourth class is what makes the
enumeration total rather than merely long. The condition list named §3, §6 and
§7, while a refused mint fails §4's ceiling or §5's exchange and so failed none
of the three it was required to name. And the rate bound obliged every refusal
record to carry a count that the enumeration — which is exclusive, and says so
twice — did not list, so a required field was a forbidden one. The trigger clause
is now the single statement of which decisions are recorded, and the two
enumerations it draws on are stated once and are total, which is the shape that
stops the next clause from contradicting them.

**That is owed rather than avoidable, and the reason is that no browser session
design escapes it.** Whatever admits a returning browser is a value the browser
holds, and a browser holds it in a browser's storage; a cookie is no more the OS
keyring than web storage is. So the question is not which mechanism avoids the
clause — none does — but whether the clause is left engaged and unmet. ADR-0124
§6 faced exactly this and ruled on the instrument: filing it as a gap "was the
wrong instrument", because "a known violation does not authorise adding another"
and "creating an access that a ratified clause requires to be gated, and shipping
it ungated, changes what that clause governs". Read for storage instead of
access, that is this situation word for word, and ADR-0070 §1 is categorical
about what the instrument then is.

**It is a prerequisite rather than a clause of this ADR because of what this
lane is.** Nothing implements here — no `src/`, no `tests/` — so nothing ships
unmet in the interval, and the corpus's ordinary shape for a dependent ratified
decision is a separate change merged first: golden rule 5 and ADR-0015 §5 for
contract surface, and ADR-0124 §6 for the `SecretStore` Protocol it needed and
declined to mint. The sequencing obligation above is what makes that a
requirement rather than a hope.

**§7 is engaged for the same reason and by the same circularity ADR-0124 §6
identified, which is why it rides in the same prerequisite rather than a
different one.** §7 requires Tier 0 access to be "gated by the `permissions/`
layer and recorded in an **audit trail**", and both are the hub's: `permissions/`
runs inside it and the audit trail is a Tier 1 store it owns exclusively
(ADR-0083). The access this section creates is the one by which a browser becomes
able to reach the hub at all, so gating it there is circular — and worse than in
ADR-0124's case, because §9 requires the gateway to serve its listener whether or
not the hub is reachable, so a hub-gated admission would make "the hub is down" an
answer the browser could never be told. An earlier draft of §13 declared §7
unengaged on the ground that ADR-0124 §6's exemption already covered the
gateway's credential read. It covers that read and expressly nothing else, and a
second access is not inside a narrow exemption because it resembles the first.
Architecture review found it.

**The replacements that lane should start from, so it rules rather than
re-derives**, and which are stated here as its material and not as clauses of
this ADR:

- **One purpose, one path.** The values are read only on the admission path and
  for no other purpose, exactly as ADR-0124 §6 confines the bootstrap credential
  read.
- **Not a long-lived secret.** Each is minted by this system rather than held on
  behalf of a third party, admits only what the owner sitting at that machine can
  already do, is bounded by §8's expiry, and dies with the gateway process — so it
  is not the kind of value §3's examples are ("OAuth tokens, API keys, refresh
  tokens").
- **Custody where a gate cannot run.** On the gateway's side the values never
  leave process memory and are written nowhere (§4); on the browser's side custody
  is the browser profile's own file permissions, which is the operating-system
  custody a file-backed keyring gives on that platform. That is ADR-0124 §6's
  second replacement — the access is gated by the OS where it cannot be gated by
  `permissions/`.
- **Auditable admission, in place of a gated read — and not auditable *use*.**
  The admission-record clause above is ADR-0124 §6's third replacement applied
  here, and it is a clause of *this* ADR because it constrains the gateway
  directly rather than the lane. What it makes auditable is the **session's**
  admission: the mint that created it, and every refusal, a failed verification
  of the halves included. It does not record the successful reads — every request
  a live session admits verifies both halves, and no record is written for one.
  That is the granularity ADR-0124 §7 already audits a *connection* at, and a
  record per admitted request is the promise the clause above was deliberately
  narrowed away from. The lane writing the supersession states the replacement in
  these terms rather than as "auditable use", because the shorter phrase would
  claim a coverage the record does not have.

**The replacements are weaker than §3 and §7, and the difference is stated rather
than smoothed over**, as ADR-0124 §6 stated its own. The gateway's record is its
own log and not the hub's Tier 1 audit trail, so it is not reviewable beside
everything else the assistant did; browser-profile permissions are custody
rather than a policy decision traceable to an answer the owner gave about *this*
access; and the record covers a session's admission rather than each Tier 0 read
the live session then makes, so an auditor sees that a session was minted and
sees every attempt that failed, but not the successful verifications behind it.
Adversarial review named that third shortfall on the eighth round, and it is
stated rather than closed: closing it means a record per admitted request, which
is the unbounded shape architecture review had this same clause narrowed away
from three rounds earlier. Which of the two costs more is a real question, and it
belongs to the lane that writes the supersession — with both halves of it visible
here rather than one. That is the price of a browser being a client at all, it is
bounded to a session's own admission on one machine, and it is paid visibly here
rather than deferred to an issue that would have made it look temporary.

> **Normative.** The front end inserts every value the hub returned into the page
> as **text** and never as markup, and executes nothing derived from one.

> **Normative.** The gateway serves every response with a content security policy
> that permits scripts, styles, fonts, images, media and connections from its own
> origin alone, and permits no inline script.

**Two halves, because a cookie is scoped to a host and not to a port, and one
half alone leaks the device's whole authority to any local process.** This is a
property of the cookie mechanism rather than of an implementation choice: a
cookie set by `http://127.0.0.1:8422` is presented to `http://127.0.0.1:9000` as
well, because the two differ only in a component cookie scope does not have. So
another local user who binds any other port on the same host and gets the owner's
browser to make one request to it receives the session — and §7's checks cannot
help, because that request never reaches the gateway at all. A single-cookie
design would therefore have shipped the exact bypass §3's session exists to
prevent, reachable by a process that never had to guess anything. Adversarial
review found it on the first round.

**The header half closes it because web storage *is* origin-scoped where a
cookie is not**, so the value at `127.0.0.1:8422` is unreadable from
`127.0.0.1:9000`, and a request carrying it is set by the front end rather than
attached by the browser. A page on another local port that dials the gateway
with credentials still fails twice over: §7 refuses its `Origin`, and it has no
header half to send.

**The cookie half is kept rather than dropped, and what it buys is the
exfiltration half of the trade.** A token the front end holds is immune to
cross-site forgery and must live somewhere script can read; a cookie is readable
by no script and must be defended against forgery, which §7 does. The asymmetry
that decides it is what the page renders: an assistant's answer is **model
output**, and a model is not a trusted source of markup. So a value stolen out of
storage — by a front end that one day renders an answer carelessly — is not on
its own a session, because the half that admits alongside it is one no script can
read.

**A cookie's missing port scope cuts both ways, and the second direction is a
denial rather than a disclosure.** Another local port cannot only *receive* the
cookie half; it can *set* one of the same name for the same host, and the browser
will then present the replacement — or, with a narrower path, present both. Our
session is not disclosed by that, but it is denied: the owner's next request
carries a good header half and a bad cookie half and is refused. §4 refuses to
evict a session on the ground that it "hands any local caller a silent lever to
log the owner out", and the clause above is what keeps this lever from being that
one: the refusal is its own named condition, so what the owner reads is that
something replaced their cookie rather than that their session mysteriously
ended. Adversarial review found the inconsistency on the second round.

**The residual it leaves is bounded to denial, and is stated rather than argued
away.** A local process that can repeatedly draw the owner's browser to itself can
keep replacing the cookie, and the remedy is a gateway restart. It never yields
admission — a replaced cookie verifies against nothing — so the failure direction
is an outage the owner can see and act on rather than a session someone else
holds. `Path=/` and no `Domain` are what make the gateway's own cookie
unambiguous about its scope, so that a second cookie of that name is detectable
as the anomaly it is rather than silently preferred.

**The larger residual is stated too: script running on the gateway's own origin
defeats both halves**, because it need not read either — it can simply issue
requests the browser will authenticate. That is true of every browser-resident
credential and is not closable by choosing a different one. What bounds it here
is the text-not-markup and content-security-policy clauses above, the session's
ceiling and expiry (§8), and the fact that it dies with the gateway process (§4).

### 7. Origin and host are checked before the session is consulted

> **Normative.** The gateway refuses any request whose `Host` header is not one
> of the loopback names it bound, and refuses any request or connection upgrade
> carrying an `Origin` that is not its own. Both checks run before the session is
> read, and a request failing either is refused without the session being
> consulted at all.

> **Normative.** The gateway sends no cross-origin resource sharing header on any
> response and honours no cross-origin preflight.

**The host check is what closes DNS rebinding, which is the specific attack a
loopback listener attracts, and being exact about what it does and does not do is
worth more than the shorter sentence.** A page the owner visits from a name the
attacker controls can have that name re-resolve to `127.0.0.1`; the browser then
treats `http://that-name:8422/…` as **same-origin with the attacking page**, so
the page may read the responses. What it does *not* get is a session: the cookie
half is scoped to the host the gateway was reached at and the header half to that
origin's storage, and neither belongs to the attacker's name — so §3 refuses it
already. The `Host` check is what refuses it one step earlier, on a fact decidable
from the request alone rather than on the session logic being right, and it is
what keeps §3's two pre-session exceptions from being readable by a page that is
not the gateway's own. It costs one comparison.

**Running both checks before the session read is not fussiness.** A refusal that
depends on whether a session exists is a refusal that discloses whether one
exists, and the two checks are decidable from the request alone.

### 8. The figures

Named here rather than left to the implementation, on ADR-0084 §3's ground,
which took it from ADR-0083 §7 and ADR-0093 §5: "a 'bounded default' with no
figure is two conforming stores handing the same continuation different history",
and it binds with more force on a limit whose whole job is to refuse.

| `Settings` field | Type | Default |
| --- | --- | --- |
| `gateway_port` | `int` | 8422 |
| `gateway_session_ttl` | `timedelta` | 12 h |
| `gateway_session_idle_timeout` | `timedelta` | 1 h |
| `gateway_max_sessions` | `int` | 8 |
| `gateway_max_hub_connections` | `int` | 8 |
| `gateway_max_request_bytes` | `int` | 1 MiB |
| `gateway_record_interval` | `timedelta` | 1 min |
| `gateway_read_timeout` | `timedelta` | 30 s |
| `gateway_max_browser_connections` | `int` | 64 |
| `gateway_max_pending_connections` | `int` | 8 |

> **Normative.** Every field above is refused at settings load unless it is
> strictly positive, in the `gt=0` / `gt=timedelta(0)` form ADR-0083 §7 adopted.
> None of them is nullable, and none takes a value meaning "off".

> **Normative.** `gateway_port` is additionally refused unless it is a valid
> non-privileged TCP port; `gateway_session_idle_timeout` unless it is no
> greater than `gateway_session_ttl` — an idle bound above the absolute lifetime
> is a limit that can never bind; and `gateway_max_pending_connections` unless it
> is no greater than `gateway_max_browser_connections`, for that same reason.

> **Normative.** A browser connection is **admitted** from the moment it carries
> a request the gateway admitted under §4, and **unadmitted** before that.
> Serving one of §3's two pre-session exceptions does not admit it, and no rule
> of this ADR returns an admitted connection to the unadmitted population.

> **Normative.** The gateway **closes** a connection once it has sent a refusal
> on it — on any of §3's, §4's, §5's, §6's, §7's and §8's conditions alike, and
> whether the connection was admitted or not. §9's report that the hub is
> unreachable is not a refusal and closes nothing.

> **Normative.** An unadmitted connection carries at most one request: the
> gateway closes it once that request's response is complete, and in any case
> `gateway_read_timeout` after it was accepted, whether or not a complete request
> has arrived by then. The gateway holds at most
> `gateway_max_pending_connections` unadmitted connections, and while that many
> exist it refuses to accept a further connection rather than queueing it.

> **Normative.** An admitted connection may carry further requests. The gateway
> closes it `gateway_read_timeout` after the last complete request it carried,
> and holds at most `gateway_max_browser_connections` connections of both kinds
> together, refusing rather than queueing beyond that.

> **Normative.** The gateway holds at most `gateway_max_hub_connections`
> connections to the hub at once. A browser request that would need one beyond
> that is **refused**, and the refusal names the limit. The gateway does not
> queue such a request and does not open a further connection.

> **Normative.** `gateway_max_request_bytes` bounds a browser request **whole** —
> its request line, its headers and its body together, not its body alone. The
> gateway enforces it incrementally and locally, refusing as soon as the bytes it
> has read on a connection exceed the limit and before it buffers past it, rather
> than on a complete request it has already held. The refusal names the limit and
> is applied before any part of the request is forwarded.

**None is nullable for ADR-0084 §3's reason, restated because it is the same
one.** There, "a hub with no frame cap or no read deadline has exactly the
failure §3 exists to prevent, so 'off' is not an available value and a zero is a
misconfiguration rather than a way to express it". A gateway with no session
expiry, no session ceiling and no request bound is a resident process that a
single local caller can exhaust, and ADR-0084 §3's closing argument transfers
verbatim: "A one-shot CLI could shrug this off; a process that runs for weeks
cannot."

**The deadline and the two connection ceilings are ADR-0084 §3's, taken whole,
because the state they bound is reachable here before any rule of this ADR
runs.** A local process can open loopback connections and send an incomplete
request header, or a valid body one byte at a time under
`gateway_max_request_bytes`; none of those has been admitted under §4, none has
asked for a hub connection, and none is refused by §7 — so every limit stated
above it leaves them untouched while they hold descriptors and reader tasks. That
is the exact pair ADR-0084 §3 separates: "a per-frame deadline bounds each
connection but says nothing about how many there may be", and "a connection that
has not completed the handshake has cost the hub a descriptor and a task while
telling it nothing, which is the cheapest state for a misbehaving peer to
accumulate". A connection that has carried no request the gateway admitted is
this door's version of that state, and it gets the tighter budget for the same
reason. Adversarial review found the gap on the tenth round.

**The tighter budget keys on admission rather than on activity, and the round
that followed is why.** The first draft of it bounded connections that had "not
yet delivered a complete request", which a peer leaves by sending one: a complete,
well-formed, session-less request is refused under §3 and costs nothing, and the
connection then sat under the total ceiling alone, renewing its deadline every 29
seconds and holding a slot indefinitely. The bound has to be the thing the peer
cannot fake rather than the thing it can, so it is admission under §4 — which
needs a session, which needs the bootstrap value. That is §1's biconditional
applied to a resource: name the property, and every state falls on one side of
it, instead of enumerating the states someone happened to think of and being
shown the next one.

**A refusal closes the connection rather than demoting it, and the difference is
not stylistic.** The draft between these two rounds had a refused request return
its connection to the unadmitted population, which reads as the symmetrical rule
and is not one: an admitted connection failing §7 would be added to a population
already at its ceiling, so the count and the ceiling could not both hold, and
nothing in the text said which gave way. Architecture review found it on the
round after. Closing has neither problem — the ceiling stays an invariant instead
of a check performed at one moment, because acceptance is then the only thing
that can raise the count, and a peer that spends a slot on a refusal has bought
one request rather than a foothold. It also costs the owner nothing, for the
reason the idle-connection paragraph below gives: a session outlives its
connections, so a closed connection is a reconnect and not a re-admission.

**What it leaves is a denial the owner can see, and that is stated rather than
argued away.** A local peer can still cycle unadmitted connections — one request
each, closed each time — and hold `gateway_max_pending_connections` of them, so it
can delay a *fresh* page load. It cannot reach an admitted connection, because
that needs a session; it cannot accumulate, because each connection it holds is
closed on its own response or its own deadline; and an already-admitted browser
keeps its slot. Cycling is request-rate load, which no ceiling design refuses and
which ADR-0084 §3's identical pending ceiling does not either. It is the same
direction of failure §6 accepts for the cookie half: an outage the owner can see
and act on, never a session someone else holds.

**The gateway owes those three figures with more force than the hub does, not
less.** ADR-0084 §3 was explicit that its own ceilings are "robustness, not
secrecy", because "the `0600` bit already scopes a peer to the owning user".
That bit is precisely what §2 and §3 establish the gateway does not have: its
port is reachable by every local process and every local user, which is the whole
reason a session exists at all. So the peer these ceilings bound is not
hypothetical here, and the cost of omitting them is a browser that cannot
connect — a gateway indistinguishable from one that is down, which is ADR-0083's
ruling 4 failure arriving by the resource path.

**Closing an idle connection costs the browser nothing, which is what makes the
deadline a resource rule rather than a behaviour change.** ADR-0084 §3 grounds
the same clause on the client being stateless, and the browser's position is
better still: a session is held by the gateway and presented on §6's two values,
so it survives the connection being closed and outlives any number of them.
Reconnecting is a reconnect, not a re-admission.

**`gateway_max_hub_connections` exists because the hub's budget is shared and the
gateway is not its only claimant.** The client opens one connection per call and
hangs up, so a browser making many concurrent requests is a browser opening many
hub connections; without a bound, a gateway can consume the whole of
`hub_max_connections` and the owner's CLI reads a refusal it has no way to
attribute. Bounding it at the gateway is what keeps that from looking like a hub
that is down — ADR-0083's ruling 4 applied to a resource.

**It refuses rather than queues, and an earlier draft's "queues or refuses" was
wrong twice over.** It was underdetermined, which is the defect the opening of
this section exists to prevent: two conforming gateways would answer the same
ninth request differently, one with an error and one with a wait. And the
queueing branch was unbounded in the direction that matters — an admitted
browser can submit faster than the hub answers, and a queue with no figure holds
a body per waiting request, up to `gateway_max_request_bytes` each, so the
connection cap and the size cap together stop guaranteeing what this section says
they guarantee. Naming a queue bound would be an eighth figure for a queue
nothing yet needs; refusing is what §4 does with the session ceiling for the same
reason, it is legible under §9, and it is what §9 already requires one hop
later — "does not retry silently, does not queue the request" — when the hub
cannot take the request at all. Whoever measures that the refusal hurts a real
front end can buy the queue and its figure then. Adversarial review found it on
the ninth round.

**`gateway_max_request_bytes` is the gateway's own bound and does not replace the
hub's.** ADR-0084 §3 makes the hub's `hub_max_frame_bytes` authoritative and has
"the client enforces the number it was told"; that stays exactly as it is, and
this bound sits in front of it so that an oversized browser request fails at the
gateway with a legible message instead of being buffered and then refused.

**It bounds the request whole, and an earlier draft that bounded only the body
left the framing open.** A peer inside its 30-second deadline can send an
enormous request line or header — well-formed or unterminated, it makes no
difference — and a bound naming the body has nothing to say while the parser
buffers it. §7's checks cannot intervene either, since they read a `Host` and an
`Origin` out of headers the gateway has not finished parsing, so the pending
ceiling would be eight slots each holding as much memory as the peer cares to
send. That is ADR-0084 §3's shape taken properly: `hub_max_frame_bytes` bounds
the whole frame, envelope included, and its reader "never allocates the declared
length up front" but "reads incrementally against the cap". One cap over the
whole request is the same rule at this door, and it is why a second figure for
headers is not owed. Adversarial review found it on the thirteenth round.

### 9. Hub-down is a legible fault, and the gateway never stands in for the hub

> **Normative.** When the gateway cannot reach the hub for a request that needs
> it, it reports that to the browser as a transport failure, distinguishable from
> a request the hub received and declined. It does not retry silently, does not
> queue the request, does not answer from anything of its own, and never presents
> a transport failure as an answer.

> **Normative.** The gateway starts and serves its own listener whether or not
> the hub is reachable, so that a browser reaching a running gateway learns that
> the hub is down rather than that nothing is there.

**This is ADR-0083's ruling 4 carried one hop further than it has been carried
before.** ADR-0084 §3 already requires the client to keep the distinction — "a
connection-level close is a **transport** failure, which is not the same event as
a request the hub received and declined, and ruling 4's legibility is the reason
the difference survives to the user rather than being flattened into one
message". The gateway is a second flattening opportunity, and the milestone's own
exit test is the second half of that sentence, so the obligation is restated at
the browser rather than inferred.

**The second clause is what makes the first reachable.** A gateway that refused to
start without a hub would present the two failures identically: nothing answers
the port either way, and the owner cannot tell a stopped hub from a stopped
gateway. Serving the listener regardless is what turns one of them into a
message.

### 10. The front-end bundle is in this repository

> **Normative.** The browser front end lives in this repository, is versioned with
> it, and ships inside the same distribution as `ai_assistant`.

> **Normative.** The gateway serves only assets that shipped in the installed
> distribution. It fetches nothing at runtime, and the page it serves loads no
> asset, font, style, script or datum from any origin but the gateway's own.

**The versioning argument is the one that decides it, and it is ADR-0084's own.**
§3 refuses tolerant protocol negotiation because "client and server are the same
`uv` environment on the same machine, installed together and upgraded together;
there is no supported deployment in which they differ except a half-finished
upgrade", and §4 records that the rejected separate wire schema "becomes the
right answer on the day the two halves version independently". A sibling
repository *manufactures* that day for the browser surface, deliberately,
for a pair that has every reason to ship together — one owner, one install, one
upgrade. It would buy decoupling whose only observable consequence is a version
skew nobody wants.

**Everything the corpus uses to hold a change honest is per-repository.** The
gate (ADR-0010), the review loop and its artifacts (ADR-0015, ADR-0027), the ADR
ledger, the citation checker and `lint-imports` all stop at this repository's
edge. A front end in a sibling repository is a front end with none of them, and
it is the half of the system that renders untrusted model output into a page —
which is exactly the half §6's clauses were written for and exactly the half that
would then be unreviewed.

**Packaging it is a solved shape rather than a new one.** ADR-0024 §4 already
puts a non-Python artifact into the wheel and the sdist alike, and its build hook
exists because that artifact is deliberately *outside* version control and has to
be fetched and verified. A bundle that is in version control needs none of that
machinery; it needs to be package data. The precedent that matters is that the
distribution already carries non-Python assets, so nothing structural is being
introduced.

**The honest cost is a front-end toolchain in a Python repository**, and it is
smaller than it sounds for this milestone: nothing in milestone 13's behaviour
requires a build step, and this ADR requires none. Whoever needs one pays for it
then, in the change that needs it.

### 11. One ADR, not two

**The delegated call is answered one way, and the reason is that the second
question has no subject without the first.** A web-session decision taken alone
would be a decision about admitting a browser to a process this corpus has not
authorised; a gateway decision taken alone would be worse — it would ratify §3's
amplifier and leave the control it needs to a later lane, which is precisely the
accept-and-ignore shape ADR-0084 §2 and ADR-0124 §7 both refuse. The one thing a
gateway ADR may not do is ship the door and defer the lock.

**ADR-0124 is the precedent and it is exact.** That decision authorised the hop
*and* ruled on who is admitted to it *and* how they are enrolled and revoked, in
one text, because its §7 admission rule is unreadable without its §1 boundary and
its §1 accountability argument is unsupportable without §§5–8. The same
dependency runs through this one: §2's loopback ruling is what makes §4's
in-memory session sufficient, and §3's amplification is what makes §4 mandatory.

**What would have made it two is a `core` surface split**, which is the seam
ADR-0084 §5 used when it separated the transport decision from the surface ADR
#281 holds — and there is none here. This ADR decides no Protocol, no type and no
wire member (§12), so **the gateway seat and web-session identity have no
contract half to split off from each other**, which is the question #1230
delegated and the whole of what this section answers.

**That is not the same as saying nothing must merge before anything**, and the
distinction is worth stating because the two sentences look alike. §6 makes the
narrowly scoped supersession of ADR-0004 §3 and §7 a prerequisite of the
*implementing* lane, so milestone 13's order is: this ADR, then that supersession, then the
gateway. What §11 rules is that the two questions in *this* text are one
decision; it is not a claim that this text is the only ADR the milestone owes,
and no lane may read it as one.

**The number reserved for the second ADR is therefore unused**, and this change
takes ADR-0168 alone. The supersession above is a different decision about a
different ADR's clause, not the second half of this one, and its number is
whoever dispatches it to assign.

### 12. What this decides no part of

> **Normative.** This ADR decides no `core/protocols.py` and no `core/types.py`
> surface. A lane implementing it that finds it needs either stops and owes its
> own contract ADR, merged first (golden rule 5, ADR-0015 §5).

> **Normative.** This ADR changes no member of the connect exchange, no frame's
> encoding, and no method's arguments or results, and no lane implementing it
> changes `PROTOCOL_VERSION` for it.

> **Normative.** ADR-0094 §10's trigger for spoke surface — an enrolment record, a
> capability descriptor, a band-ceiling field, a spoke identity — is examined here
> and does not fire, and no lane may cite this ADR toward any of that surface.
> The gateway is the client profile carrying a person and exercising push, which
> is what the CLI already is; a second spoke of the same profile with the same
> ceiling shows nothing about what differs per spoke.

> **Normative.** This ADR sets no spoke's band ceiling and raises none. ADR-0094
> §5 binds the gateway exactly as it binds the CLI, and a browser behind a gateway
> reaches no standing the gateway does not have.

> **Normative.** No lane may cite this ADR toward ADR-0094 §10a's clause about a
> producer relying on §9's permission, toward `VISION.md`'s sensor-spectrum
> amendment, or toward #441. The session table this ADR permits is not the
> ephemeral capture buffer those texts are about, and §13 is where its standing is
> argued rather than assumed.

**Deferred, by name, each with the condition that fires it:**

- **The browser-facing surface itself** — the request shapes, the paths, the
  document, and whether a push carrier such as a WebSocket is among them. It is
  not `core` surface, it is not a Protocol, and it ships and versions with the
  bundle in one distribution (§10), so no ADR is owed for it and the implementing
  lane decides it. **The one direction rule it inherits** is ADR-0094 §2's shape
  read at the browser: whatever carries a message to a browser is established by
  the browser, and the gateway writes on it only in answer to something the
  browser asked for. Milestone 13's behaviour needs no server-initiated browser
  message at all, and adding a carrier for one before something emits it is the
  unspiked seam ADR-0042 §5 and ADR-0084 §11 have twice declined.
- **Fanning one delivery out to several browsers.** ADR-0131 §2 gives a device at
  most one delivery connection, ADR-0131 §4 makes the identity that rule turns on
  the one ADR-0124 §4 established at admission, and a gateway is one device — so
  every browser behind one gateway shares one `next_notification` poll and the
  gateway is what distributes the result. That is a real consequence of this
  decision and it is **not decided here**; it fires with milestone 14, which is
  the first consumer of that seam and the decision that will have a browser
  surface in hand. Nothing in this ADR forecloses it.
- **A session that survives a gateway restart** (§4, §5). Durable edge state
  needs the argument §13 makes for ephemeral state made again on harder ground,
  and it wants a durable browser credential this ADR declines to mint. Fires with
  milestone 16, which names session persistence.
- **A browser on a device that cannot run a gateway** (§2). Fires with milestone
  14's phone; owes a fourth egress boundary superseding ADR-0124 §1's
  enumeration.
- **Account connection from a browser on another device.** The five connection
  methods are refused on the hub's remote listener and refused client-side by the
  remote client, and this ADR neither widens that nor decides it. It is inherited
  by milestone 15, which is the milestone that asks for connections.
- **A second gateway on one device.** Two gateway processes on one machine are
  one device to the hub and cannot both hold its delivery slot (ADR-0131 §2), so
  the arrangement is not obviously coherent; nothing here authorises it and
  nothing here forbids it, and the question belongs to whoever first wants one.

### 13. Classification under ADR-0070 §1 and ADR-0082 §1

ADR-0082 §1 requires the judgement to be made in this text, naming the clause and
applying ADR-0070 §1's test: would a reader holding only the earlier text now act
differently, or read one of its clauses more widely than it now holds?

**Two clauses are engaged and are called out as such in the list below —
ADR-0004 §3 and §7, whose record §6 makes a prerequisite of the implementing
lane. No record is owed on any of the rest.**

- **ADR-0084 §1's refusal of a TCP loopback port.** Its subject is stated in its
  own heading and in every reason it gives — the *hub's* transport, chosen so
  that the hub's door reuses ADR-0004 §4's `0600` posture and "cannot be widened
  by a typo". Every sentence stays true: the hub still binds a Unix socket, and a
  reader holding only ADR-0084 still builds one. What this ADR does is take §1's
  own stated consequence — that a TCP port is reachable by every local process
  and "the only way to make it safe is a credential" — and pay that price at a
  different door, because a browser cannot dial the socket §1 chose. Using a
  clause's reasoning where it applies is not reading it more widely. This is the
  ADR-0083 §15 pattern ADR-0084 §12 itself applied to ADR-0017.
- **ADR-0084 §7's stateless client, and §3's "holds no server-side session to
  lose".** §7's subject is continuation tokens and its stated reason is that a
  cached token "would behave differently depending on whether the hub happened to
  restart between two commands"; §3's phrase names *hub* state. A web session
  holds nothing of the hub's, resolves against nothing the hub minted, and is
  identical across a hub restart — the gateway still re-enumerates parks, still
  persists no token, and still reconnects for free. This is ADR-0094 §9's argument
  on a different object, and it comes out the same way for the same reason.
- **`VISION.md` §8's "Every interface should be a **stateless client** of that
  service".** The sentence stays true, and its own next sentence is why: "A
  conversation begun in one place should be resumable in another, because the
  conversation lives in the hub rather than in whatever displayed it." A session
  table cannot make a conversation unresumable — every browser the gateway admits
  reaches the same conversations, because they are the hub's — and §8's enumeration
  of what the resident service owns ("memory, the user model, conversations,
  plans, permissions") contains nothing a session holds. What the gateway holds is
  its own admission decision, which is the same class of thing as the device
  credential the CLI already holds and which nobody reads as state. No amendment
  is owed and #441 is untouched.
- **ADR-0094 §9.** Used as given, as the permission it was written to be, and
  applied to **both** things this ADR lets the gateway hold. The session table is
  bounded in count and in age (§8), destroyed continuously rather than at a
  checkpoint (§4), and never authoritative — nothing the hub does depends on it,
  and the hub is not told it exists (§3). §6's admission record adds no second
  body of edge state to test against §9, because the gateway **retains none of
  it**: the record is emitted through the logging this system already configures,
  which installs no file handler and keeps nothing. What §9 does reach there is the
  interval's counters — one integer per pair of request class and refusal
  condition, reset each interval —
  which are bounded in size by a fixed set, bounded in age by the interval, and
  never authoritative, since no clause here gives them an effect on whether
  anything is admitted. Two earlier drafts were wrong about this in opposite
  directions, and architecture review named both: the first obliged a record per
  request, and the second called a rate limit a bound in size.
- **ADR-0094 §10a's producer clause.** Examined and found not to reach this. Its
  subject is the deferral it marks — the sensor-spectrum amendment, whose content
  §10 states as "the ephemeral buffer, consent-per-capture, and graduated trigger
  autonomy" — and "producer" throughout ADR-0094 means a producer of submitted
  material: §6's edge detector, §8's custody of a released slice, §10's "first
  capture producer". A gateway submits nothing it holds; it relays what a person
  typed, in the moment, and holds no material awaiting a handoff. The clause's
  *concern* — that §9's permission and `VISION.md` §8's sentence not be left to
  drift apart — is met on the merits above rather than sidestepped, which is why
  §12 forbids anyone citing this ADR toward either.
- **ADR-0094 §10's second-spoke trigger.** Examined and found not fired, on
  ADR-0124 §5's reasoning applied to a second process instead of a second machine:
  that section held that "a second *device* is not a second spoke — the CLI
  running on a second laptop is the same profile exercising the same capability —
  so that trigger does not fire here", and a gateway is the same profile
  exercising the same capability as well. §10's stated reason is standing — "one
  spoke cannot show which of these differ per spoke" — and a second spoke that
  differs in nothing supplies none.
- **ADR-0124 §1's enumeration.** Untouched. §2 above keeps the browser hop inside
  one device, so no boundary is added, and the clause that would be needed to add
  one is deferred by name rather than written.
- **ADR-0124 §§4–8.** Used as given. The gateway enrols, is admitted, and is
  revoked as any device is; §3 above forbids anything about a browser reaching
  that machinery.
- **ADR-0124 §10's prohibition on the hub dialling a spoke.** Untouched and
  reinforced: §12's direction rule carries the same prohibition one hop further,
  to the browser.
- **ADR-0131.** Used as given, and nothing it decides is reopened. §12 records the
  one-slot-per-device consequence as inherited rather than deciding the fan-out.
- **ADR-0017 §1.** Already replaced by ADR-0124 §1, which is what §2 above reads;
  §§2–9 are not engaged by a loopback listener and no clause of them is read
  either way.
- **ADR-0004 §1.** Used as given. Both halves of a session and the bootstrap
  value are classified under it rather than around it, and §6 records the
  consequence of that classification rather than avoiding it.
- **ADR-0004 §3 and §7 are the exceptions on this list: both are engaged, and the
  record they need is a prerequisite rather than a finding of no-record-owed.**
  ADR-0070 §1's second limb is met twice. A reader holding only §3 believes every
  Tier 0 secret in this system's world sits in the OS keyring, and after §6 that
  is wrong of the browser's halves. A reader holding only §7 believes every Tier 0
  access is gated by `permissions/` and recorded in the audit trail, and after §6
  that is wrong of a session's admission. §6 states both obligations, states why
  no browser design escapes either, and makes one narrowly scoped supersession
  covering both a **prerequisite of the implementing lane**, with its replacements
  named so that lane starts from a ruling.
- **ADR-0004 §5.** Used as given, and it is what shapes §6's admission record:
  "logs are Tier 2 only" is why that record is an enumeration of permitted Tier 2
  facts rather than a list of excluded secrets. Nothing about it is read more
  widely or more narrowly, and the redaction safety net it names is relied on as
  a net rather than as the rule.
- **What is *not* engaged is §3 or §7 as they reach this system's own
  hub-facing paths.** The gateway holds no Tier 0 value at rest (§4), and the
  device credential it reads to reach the hub stays exactly where ADR-0124 §6 put
  it, under the exemption ADR-0124 §6 already ruled and through the Protocol it
  requires. Nothing here widens that exemption, and §6's is a second one that
  stands or falls on its own record rather than on ADR-0124's.
- **ADR-0042 §5 and ADR-0084 §11's streaming deferral.** Untouched. §12 declines
  to add a carrier for it, on the ground those texts give.
- **ADR-0097 and ADR-0099 §1.** §4's refusals are ADR-0124 §5's, restated for a
  new noun that invites the same mistake. No grant is created, no principal is
  added, and neither ADR's text is read more widely.
- **Golden rule 3.** §1's third clause is the rule applied, not amended: a
  gateway that authored anything would be in breach of it, and the clause is what
  makes the breach detectable.

## Consequences

- **The system gains a second interface adapter**, in `interfaces/`, reached by a
  subcommand of the existing `assistant` script — the first time ADR-0084 §6's
  own-console-script rule has been examined and found not to fire (§1).
- **`core` gains ten `Settings` fields** (§8), each strictly positive at load,
  none nullable. They are contract surface in ADR-0054's sense, which several
  earlier ADRs already were; they are not `core` Protocol or type surface, so
  golden rule 5 is not triggered and no triad is owed.
- **The corpus gains a third admission rule, and one principle now covers all
  three.** Loopback refuses a credential, the remote listener requires one, and
  the gateway requires a session — because admission never asserts a check that
  did not happen, and each door's answer is decided by what its transport already
  guarantees.
- **Milestone 13 gains a second ADR lane, and it is a prerequisite rather than a
  follow-up**: the narrowly scoped supersession of ADR-0004 §3 and §7 for a
  browser-held web session and its admission, merged before any gateway ships
  (§6). It is small — two clauses, one scope, the replacements already named — and
  it is owed because no browser session design avoids holding a credential in a
  browser or verifying it somewhere `permissions/` cannot reach.
- **A session is two values rather than one**, because a cookie is scoped to a
  host and not to a port and would therefore be presented to any other local
  service on `127.0.0.1`. That is a property of the browser's own mechanism, so
  it constrains every later browser-facing surface this track builds and not just
  this one (§6).
- **A browser session is exactly as powerful as the device it sits behind**, and
  the hub cannot tell two of them apart. That is stated as a rule rather than
  left as a property, so that no later lane builds on an isolation that does not
  exist (§3).
- **Milestone 13's exit test is reachable with no new egress boundary**, because
  the browser and the gateway share a device and the interesting hop is the one
  ADR-0124 already authorised (§2).
- **Milestone 14 inherits two named things rather than discovering them**: one
  delivery slot per gateway, to be fanned out by the gateway; and a phone, which
  needs a fourth egress boundary and therefore its own ADR (§12).
- **Milestone 15 inherits one**: the five connection methods are refused on the
  remote listener, so a gateway on a second device cannot offer account
  connection until that is decided (§12).
- **What becomes harder:** the front end is now inside this repository's gate,
  review floor and ADR ledger, so a change to it costs what a change to the rest
  costs. That is the intended trade — it is the half of the system that renders
  model output into a page, and §6's clauses are only worth writing if someone
  reviews them (§10).
- **What becomes harder, second:** every gateway restart logs every browser out,
  and a second browser needs a restart. That is the price of holding no durable
  browser secret in this milestone, it is paid visibly, and milestone 16 is where
  it is revisited (§12).
- **Revisit when** a browsing device cannot host a gateway (§2's fourth boundary);
  when session persistence is asked for (§4, §5); when a second spoke genuinely
  differs from the CLI in profile, capability or ceiling, which is ADR-0094 §10's
  trigger and which this decision does not meet (§12); or when the hub ever gains
  a browser-facing surface of its own, which would make this whole seat
  unnecessary and is refused in Alternatives.

## Alternatives considered

- **Put the browser-facing listener in the hub.** The cheapest path on paper: no
  second process, no second admission rule, no amplifier. *Rejected.* It puts a
  large, untrusted-input-facing HTTP surface inside the one process that holds
  the five databases and the instance lock, which is the opposite of what
  ADR-0083's exclusivity is for; it makes `service` grow an interface adapter,
  which golden rule 3 and ADR-0083 §8 between them have no room for; and it
  would make the browser's reach a property of the hub's listener rather than of
  a spoke, so ADR-0124's device admission would have to be re-argued for a
  caller that has no device.
- **Run the gateway on the hub's machine and serve browsers over the overlay.**
  Genuinely arguable, and the shape most people would build. *Rejected in §2*: it
  is a fourth egress boundary superseding a normative enumeration in ADR-0124 §1,
  bought to satisfy an exit test that the already-authorised arrangement
  satisfies. It becomes the right question when a browsing device cannot host a
  gateway, and §12 defers it there with that condition.
- **Reach a gateway on the hub's machine through `tailscale serve`, an SSH
  tunnel or a reverse proxy.** Requires no code and appears to keep the listener
  on loopback. *Rejected in §2* — the data still leaves the device, and the
  boundary being technically unbroken in our socket options is not the boundary
  holding. Refusing to bless it is what keeps the egress ledger honest.
- **Admit a browser on nothing, because the port is loopback.** *Rejected in §3.*
  ADR-0084 §1 already establishes that a loopback TCP port is reachable by every
  local process and every local user, and the gateway holds the device
  credential — so this is not "a small local risk", it is re-exporting the
  device's whole authority to anything on the machine, performed by a process
  ADR-0124 §7 admitted.
- **Give the browser its own enrolment at the hub.** Attractive because it would
  make browsers first-class and would need no gateway-side session at all.
  *Rejected.* ADR-0124 §6 makes enrolment an act at the hub minting a credential
  the client holds in the OS keyring, and §4 requires an overlay identity the
  local agent attests; a browser has neither, so the two-fact rule has no subject
  inside it. Loosening either fact to accommodate a browser would weaken the rule
  for every device.
- **A durable browser credential the owner types, held in the gateway's
  keyring.** Would survive restarts and admit any number of browsers. *Rejected
  in §5* for this milestone: it is a second Tier 0 secret and a human-chosen one,
  which is the shape ADR-0124 §6 spent a clause arguing against, and durable
  sessions then owe §13's `VISION.md` argument on harder ground. Deferred to
  milestone 16 rather than refused outright.
- **One value, in a cookie alone.** The obvious design and the one an earlier
  draft of §6 carried. *Rejected in §6, on a fact rather than a preference*: a
  cookie is scoped to a host and not to a port, so any other local user who binds
  another port on `127.0.0.1` and draws the owner's browser to it is handed the
  session — and §7 cannot intervene, because that request never reaches the
  gateway. It would have shipped the bypass §3 exists to prevent.
- **One value, in an origin-scoped header alone.** Closes the port leak, and
  needs no cookie. *Rejected in §6*: it must live where script can read it, the
  page renders model output, and that value would then be the device's whole
  authority in one exfiltrable place. Keeping a cookie half that no script can
  read costs one `Set-Cookie` and means a stolen storage value is not a session.
- **Evict the oldest session when the ceiling is reached.** Friendlier. *Rejected
  in §4* on ADR-0131 §2's reasoning: it hands any local caller a silent lever to
  log the owner out, and the eviction is indistinguishable from an ordinary
  expiry.
- **Two ADRs — the gateway seat and web-session identity.** The delegated call,
  and a real option. *Rejected in §11*: the gateway ADR alone would ratify §3's
  amplifier and defer its only control, which is the accept-and-ignore shape
  ADR-0084 §2 and ADR-0124 §7 both refuse, and the session ADR alone would have
  no subject. ADR-0124 is the precedent for holding a boundary and its admission
  rule in one text.
- **A sibling repository for the front end.** *Rejected in §10*: it manufactures
  independent versioning for a pair that ships together — the condition ADR-0084
  §3 and §4 both name as the thing that would change their answers — and it puts
  the half of the system that renders model output outside this repository's
  gate, review floor and ADR ledger.
- **Ship a WebSocket now, so milestone 14 does not have to add one.** *Rejected
  in §12.* Nothing in milestone 13 emits a server-initiated browser message, and
  ratifying a bidirectional surface with nothing to put on it is the unspiked
  seam ADR-0042 §5 declined and ADR-0084 §11 inherited. The direction rule that
  governs whatever carries it is stated in advance instead, which is what keeps
  the addition from being a redesign.
