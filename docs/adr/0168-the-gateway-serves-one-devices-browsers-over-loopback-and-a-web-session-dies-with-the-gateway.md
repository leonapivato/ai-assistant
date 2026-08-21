# 168. The gateway serves one device's browsers over loopback, and a web session is minted at the gateway and dies with it

- Status: Proposed
- Date: 2026-08-21

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
- **It supersedes nothing.** §13 applies ADR-0070 §1's test clause by clause to
  every ADR whose text a reader might expect this decision to falsify, and finds
  no record owed. That finding is the reason this change touches one file.
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

> **Normative.** The gateway holds no assistant logic. Every request it accepts
> from a browser resolves to calls on the promoted engine surface and to
> rendering what those calls returned; it composes no behaviour the surface does
> not offer, authors no permission ruling, mints no confirmation, and opens no
> store.

**The third clause is what makes golden rule 3 checkable rather than
aspirational**, and it is owed because a long-running HTTP server does not
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
0 secret at rest", and the same sentence should be true of the gateway. It also
settles ADR-0004 §3 without a supersession — a value never written to a store or
a file is a value that clause has nothing to say about (§13).

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
> not readable by any script, and carries no persistent expiry, so that closing
> the browser ends it.

> **Normative.** The header half is held in browser storage scoped to **scheme,
> host and port** and shared across that origin's tabs, and it is sent only as a
> request header the front end sets. It is never placed in a cookie, in a URL, or
> in storage that outlives the origin's own scope.

> **Normative.** Neither half is placed in any response body except the bootstrap
> exchange's own reply (§5), and neither is placed in a URL, in a log record, or
> in any error the gateway emits.

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

**The residual is stated rather than argued away: script running on the gateway's
own origin defeats both halves**, because it need not read either — it can simply
issue requests the browser will authenticate. That is true of every
browser-resident credential and is not closable by choosing a different one. What
bounds it here is the last two clauses, the session's ceiling and expiry (§8),
and the fact that it dies with the gateway process (§4).

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

> **Normative.** Every field above is refused at settings load unless it is
> strictly positive, in the `gt=0` / `gt=timedelta(0)` form ADR-0083 §7 adopted.
> None of them is nullable, and none takes a value meaning "off".

> **Normative.** `gateway_port` is additionally refused unless it is a valid
> non-privileged TCP port, and `gateway_session_idle_timeout` unless it is no
> greater than `gateway_session_ttl` — an idle bound above the absolute lifetime
> is a limit that can never bind.

> **Normative.** The gateway holds at most `gateway_max_hub_connections`
> connections to the hub at once and queues or refuses beyond that rather than
> opening more.

> **Normative.** The gateway refuses a browser request whose body exceeds
> `gateway_max_request_bytes` locally, before any part of it is forwarded, and
> the refusal names the limit.

**None is nullable for ADR-0084 §3's reason, restated because it is the same
one.** There, "a hub with no frame cap or no read deadline has exactly the
failure §3 exists to prevent, so 'off' is not an available value and a zero is a
misconfiguration rather than a way to express it". A gateway with no session
expiry, no session ceiling and no request bound is a resident process that a
single local caller can exhaust, and ADR-0084 §3's closing argument transfers
verbatim: "A one-shot CLI could shrug this off; a process that runs for weeks
cannot."

**`gateway_max_hub_connections` exists because the hub's budget is shared and the
gateway is not its only claimant.** The client opens one connection per call and
hangs up, so a browser making many concurrent requests is a browser opening many
hub connections; without a bound, a gateway can consume the whole of
`hub_max_connections` and the owner's CLI reads a refusal it has no way to
attribute. Bounding it at the gateway is what keeps that from looking like a hub
that is down — ADR-0083's ruling 4 applied to a resource.

**`gateway_max_request_bytes` is the gateway's own bound and does not replace the
hub's.** ADR-0084 §3 makes the hub's `hub_max_frame_bytes` authoritative and has
"the client enforces the number it was told"; that stays exactly as it is, and
this bound sits in front of it so that an oversized browser request fails at the
gateway with a legible message instead of being buffered and then refused.

### 9. Hub-down is a legible fault, and the gateway never stands in for the hub

> **Normative.** When the gateway cannot reach the hub it reports that to the
> browser as a transport failure, distinguishable from a request the hub received
> and declined. It does not retry silently, does not queue the request, does not
> answer from anything of its own, and never presents a transport failure as an
> answer.

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
wire member (§12), so there is no contract half to review as contract surface and
no lane that must merge before another.

**The number reserved for the second ADR is therefore unused**, and this change
takes ADR-0168 alone.

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

**No record is owed, on any of the following.**

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
- **ADR-0094 §9.** Used as given, as the permission it was written to be. The
  session table is bounded in count and in age (§8), destroyed continuously rather
  than at a checkpoint (§4), and never authoritative — nothing the hub does
  depends on it, and the hub is not told it exists (§3).
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
- **ADR-0004 §1 and §3.** Both halves of a session and the bootstrap value are
  Tier 0, and §3's clauses stay true of them word for word: none is stored "in the
  memory database", none reaches "a committed file", and none is read through a
  path §3's `SecretStore` sentence governs, since the gateway holds no Tier 0
  value at rest at all (§4). What the *browser* holds is held by software this
  system neither writes nor chooses the storage of, and §6 bounds it to what the
  browser's own origin scope and session lifetime already destroy. The device credential the gateway *does* read stays
  exactly where ADR-0124 §6 put it, through the Protocol ADR-0124 §6 requires.
  ADR-0004 §7's gating clause is not engaged: no exemption beyond ADR-0124 §6's
  narrow one is taken, claimed or needed.
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
- **`core` gains six `Settings` fields** (§8), each strictly positive at load,
  none nullable. They are contract surface in ADR-0054's sense, which several
  earlier ADRs already were; they are not `core` Protocol or type surface, so
  golden rule 5 is not triggered and no triad is owed.
- **The corpus gains a third admission rule, and one principle now covers all
  three.** Loopback refuses a credential, the remote listener requires one, and
  the gateway requires a session — because admission never asserts a check that
  did not happen, and each door's answer is decided by what its transport already
  guarantees.
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
