# 84. The local API: a loopback socket, a versioned envelope, and the CLI as a client

- Status: Proposed
- Date: 2026-07-31
- **This is the second and last of leg 5's two decisions.** ADR-0083 decided the
  *process* — one resident instance, exclusive ownership of the five databases,
  two-phase shutdown, exit-code classification, the internal scheduler. This one
  decides the *door*: the transport, the handshake, the DTO shape, versioning,
  and the CLI as the first client. ADR-0083 §14 states the boundary in both
  directions and is treated here as constraint, not as material to revisit.
- **New `core` surface, and this time golden rule 5 is triggered literally.** §5
  concludes that ADR-0042 §1's own revisit trigger has fired, so the engine
  façade is promoted to a Protocol in `core/protocols.py` and its result types
  promote to `core/types.py` (§4). **That is a Protocol change, so it owes a
  triad** — Protocol + shared conformance suite + canonical fake in
  `ai_assistant.testing` — which is **a separate lane that merges before any
  client** (golden rule 5, ADR-0015 §5, `CONTRIBUTING.md` → "Adding a
  Protocol"). This ADR ratifies the decision; it does not write the triad.
- **No implementation lands with it.** No `src/`, no `tests/`.
- **This ADR partially supersedes ADR-0042, and the record lands in this
  change.** §12 applies ADR-0070 §1's test clause by clause and finds ADR-0042
  §1's refusal of an engine-facing Protocol and of a `core` result type, and §2's
  and §7's rule that an adapter obtains its engine by calling `build_engine`,
  **contradicted** rather than merely joined by a new obligation. ADR-0042's
  `Status` line and its appended dated note are the whole of the record (ADR-0070
  §1, ADR-0082 §2); no ratified text of ADR-0042 is rewritten. ADR-0083 §14
  anticipated this exactly: "One thing ADR-0084's lane inherits as work, not as a
  constraint… That lane owes ADR-0082 §1's test against ADR-0042, and this ADR
  does not pre-judge it."

## Context

### The CLI is not a client of anything; it *is* the application

`interfaces/cli.py` obtains an engine from exactly one place — `_open_engine`
(`cli.py:629-654`) — which calls `load_settings()`, `configure_logging()`,
`build_engine(settings)` and `await engine.start()`, and each of the eleven entry
points wraps its body in `asyncio.run`. The process that renders the prompt is the
process that opens `memory.db`. There is no wire, no address, no serialisation of
an engine result anywhere in the tree, and `[project.scripts]` declares one
console script, `assistant = "ai_assistant.interfaces.cli:app"`.

ADR-0083 makes that arrangement illegal. Its ruling 4 — "the hub is the only
process that opens the five databases, and the API is the only door" — means the
CLI must stop building an engine, and its §10 sequences the mechanical
enforcement into *this* lane: closing the `interfaces → app` edge "becomes the
mechanical enforcement of exclusivity… That contract edit is sequenced with
ADR-0084's lane, not with this ADR." So the door has to exist before the edge can
close, and both are this decision's consequence.

### The rulings this ADR is built on

Given by the project owner, and treated here as constraints:

1. **The hub eventually runs on a dedicated, always-on machine.** Loopback-first
   is a consequence of that machine not existing yet, not a judgement that
   local-only is the target. **The DTO and the versioning are designed as if
   remote spokes are the next leg, because on this plan they are.**
2. **The hub owns the five SQLite databases exclusively.** The API is the only
   door.
3. **No client-driven autostart.** When the hub is not running, the client fails
   with an instruction. No in-process fallback.
4. **"If the hub is not running, there is a reason, and the reason must be
   legible."**

### What is expensive to retrofit, and what is not

Three things are expensive to add to a shipped protocol: **a connect handshake
with somewhere to put a version**, **somewhere to put a credential it does not
yet use**, and **a genuinely stateless client**. Each of them changes the shape
of every exchange, so adding one later means every deployed pair must be upgraded
in lockstep — which is the one thing a single-user install has no machinery for.

Swapping the address family — a Unix socket for a TCP listener — is nearly free
by comparison: it changes one bind call and one connect call, and touches no
frame. So this ADR spends its care on the three, and treats the transport choice
as the reversible decision it is (§1).

### The DTO question is sharper than it looks

The façade's result types are **frozen `@dataclass(slots=True)`, not pydantic**:
`ContinuationToken` (`engine.py:138`), `Confirmation` (`:159`), `StepOutcome`
(`:189`), `TurnOutcome`, `Belief`, `Question`. ADR-0042 §1 kept them out of
`core/types.py` deliberately — "promotion to `core` is reserved for the day a
subsystem needs to receive one, which this is not" — and #281 is the pre-existing
home for pinning them, deferred from ADR-0042 for want of implementation
contact. That contact now exists.

Two facts constrain what can be done with them. ADR-0068 §1 makes every
boundary-crossing `core` model deeply immutable, with `tuple` collections, so
anything promoted arrives frozen. And #473 records that `Belief`'s evidence tuple
is **unbounded and grows monotonically** — `MemoryIngestor._merge` unions both
records' evidence on every `REINFORCE` (`ingest.py:345`), with nothing capping or
pruning it — so a DTO decision that assumes a bounded payload is designing
against a premise the tree does not hold. Bounding it is #473's own contract
lane, not this one.

## Decision

### 1. The transport is a Unix domain socket inside `data_dir`, at `0600`

**The hub listens on an `AF_UNIX` stream socket at `<data_dir>/hub.sock`**, created
with owner-only permissions (`0600`) and removed on shutdown.

**`0600` on the socket is necessary and not sufficient, and the gap is the
directory.** A mode on the socket *file* restricts `connect()`; it does nothing
about the **directory entry**. If `data_dir` is group- or world-writable, another
local user can `unlink` the live `hub.sock` and bind their own in its place — and
the CLI, following §9's derivation, connects to it and hands over the utterance.
That is Tier 0/1 content going to another user's process (ADR-0004 §1), which no
amount of mode on the replaced file prevents. ADR-0083 D3 does not close this: it
requires `data_dir` to be local, writable, and not shared with another hub, none
of which excludes a mode like `0777`.

**So the data directory itself is constrained, and it is validated at ADR-0083
§3's step 2.** Three conditions, each a `78` when it fails, because none of them
is fixed by restarting:

- **`data_dir` itself is owned by the hub's own uid and is not group- or
  world-writable**, created `0700` when the hub creates it. This is ADR-0004 §4's
  owner-only posture applied to the container rather than only to the contents,
  and it protects the five databases in that directory — which have no handshake
  to fall back on — at least as much as it protects the socket.
- **Every ancestor directory, up to the root, is owned by root or by the hub's
  uid and is not writable by anyone else** — with one exception, an ancestor that
  is other-writable but carries the **sticky bit**, which is precisely what stops
  a user removing or renaming an entry they do not own. The ancestors get the
  weaker of the two conditions **deliberately**: requiring hub-uid ownership all
  the way up would reject the ordinary default, since `/` and `/home` are
  root-owned and always will be, and a rule that fails the deployment everyone
  actually runs is not a security control but an outage. What matters about an
  ancestor is not who owns it but whether an untrusted user can *replace* the
  entry below it. That gap is worth stating because securing the leaf alone looks
  sufficient and is not: with `data_dir=/srv/shared/alice` at `0700` but
  `/srv/shared` at `0777` and not sticky, another user renames `alice`, creates
  their own directory and socket at the configured path, and the leaf's mode
  never comes into it.
- **Absolute and canonical.** `Settings.data_dir` is a `Path` and may be
  relative, which silently breaks the one-setting-locates-both property §9 rests
  on: a hub started at boot with a working directory of `/` and a setting of
  `state` binds `/state/hub.sock`, while a CLI run from a project directory looks
  for `<project>/state/hub.sock` and truthfully reports the hub down. Both read
  the same setting and disagree. A relative value is therefore rejected at
  settings load, and the path is canonicalised before either side derives
  anything from it.
- **Short enough to hold the socket**, which is the next paragraph.

**And the client authenticates the hub after connecting, which is what actually
closes this.** Filesystem checks are a walk over topology the operator controls,
and a walk can be wrong — a bind mount, an ACL, a symlinked ancestor. So the
client does not rely on them alone:

> **After `connect()` and before sending anything, the client reads the peer's
> credentials from the kernel and refuses unless the server's uid is its own.**

**The rule is the check, not the syscall, because the syscall is not portable.**
Linux exposes it as `SO_PEERCRED` via `getsockopt`; macOS and the BSDs expose the
same fact as `getpeereid()` (or `LOCAL_PEERCRED`). The obligation is stated in
terms of the *credential* so that it binds on both, and an implementation selects
the mechanism its platform provides. **A platform offering neither cannot host
this client**, and that is the fail-closed direction on purpose: silently skipping
the check where the call is missing would leave exactly the deployments with the
weakest filesystem guarantees running with no server authentication at all. This
ADR does not otherwise restrict the transport to Linux — where a detail *is*
Linux-specific, as `sun_path`'s 108 bytes and the abstract namespace are, it is
named as such.

That is a direct check on *who is actually on the other end*, not an inference
from who could have written where, and it is free of the time-of-check
time-of-use gap a pre-connect `stat` of the socket would have. A replaced socket
belonging to another user is refused at that point whatever the directory modes
were. The filesystem conditions above stay, as defence in depth and because the
databases in that directory have no equivalent check.

**This does not contradict §2's declining of `SO_PEERCRED`, because it runs in
the other direction.** §2 declines it as the *server* authorising the *client* —
there it would re-derive what the socket mode already guarantees. Here it is the
*client* authenticating the *server*, which nothing else establishes. Same call,
opposite direction, and only one of the two is redundant.

**The socket path is length-checked at the same point, and an overlong one is
also a `78`.** A pathname `AF_UNIX` socket is bounded by `sun_path`, and **the
figure is platform-specific: 108 bytes on Linux, 104 on macOS and the BSDs,
terminator included in both.** The check uses **the running platform's own
limit** rather than a constant — hardcoding 108 would let a 104-byte path pass
validation on macOS and then fail at `bind()`, which is precisely the late,
opaque failure this rule exists to prevent, reintroduced by the check itself.
Meanwhile `data_dir` is operator-configurable through
`ASSISTANT_DATA_DIR` (ADR-0083 §2, and see the note on its spelling in §9). So a
perfectly writable, perfectly valid data directory can have a path no socket can
be bound inside. Left unchecked that failure lands at ADR-0083 §3's **step 6**,
after the lock is held, the five stores are open and the start-up sweeps have
run: the latest and least legible moment available, and a hub that is down for a
reason buried in a `bind` errno is ruling 4's failure.

**So the encoded length of `<data_dir>/hub.sock` is validated at step 2**,
alongside the data-directory resolution and the lock that already happen there,
and a path that cannot hold the socket **exits `78`**, naming the limit, the
encoded length and the directory. ADR-0083 §5's test applies without strain:
restarting unchanged never succeeds, and a human must move the data directory.
The check is on the **encoded byte length** rather than the character count,
because `sun_path` bounds bytes — a directory named in a non-ASCII script spends
more of the budget than it looks like it does.

**ADR-0017 does not constrain this, and the reason is worth writing down because
the opposite reading is available and wrong.** ADR-0017 §1's rule governs data
that "leave[s] the **device**", and §3's fourteen conditions are conditions on
*designating the `tools/` egress seam*. A loopback listener moves bytes between
two processes on one machine; it engages neither clause. This is the ADR-0083 §15
pattern of examining a clause and finding it unmet, and it changes nothing about
ADR-0017.

**But it engages ADR-0017 the moment the transport stops being loopback, and that
is the single most important sentence in this section.** A hub on a dedicated
machine serving a spoke on a laptop *is* user data leaving the device, and the
hub's API is neither `models/` nor a designated `tools/` seam — so under ADR-0017
§1 as it stands, that egress "is a bug". **The remote leg therefore owes its own
ratified egress decision, and it cannot be reached by swapping an address
family.** Ruling 1 asks that the *wire* be remote-ready; it does not and cannot
pre-authorise the remote hop. Naming this now is what stops a future lane from
reading "designed for remote spokes" as permission already granted.

**Why a socket rather than a TCP loopback port**, in the order the reasons bind:

- **A Unix socket reuses a ratified access control; a TCP port has none.**
  ADR-0004 §4 already requires the memory database to be "created with owner-only
  file permissions (`0600`) in the user's data directory". A Unix socket is a
  filesystem object carrying the same permission bits, and on Linux the kernel
  enforces them at `connect()` — so `0600` on `hub.sock` is ADR-0004 §4's
  existing posture applied to the new object, not a new control invented here.
  A TCP loopback port is reachable by **every local process and every local
  user**, and by containers sharing the host's network namespace. Nothing in the
  corpus authorises that, and the only way to make it safe is a credential — which
  §2 deliberately does not ship yet.
- **The data directory already has to be local storage.** ADR-0083 D3 requires
  it, for the instance lock and for journal-mode reasons. A socket placed there
  inherits that constraint rather than adding one.
- **It cannot be reached from off the device by accident.** A TCP listener bound
  to `127.0.0.1` today is one configuration edit from `0.0.0.0`, and that edit
  would silently cross the ADR-0017 line drawn above. A socket cannot be widened
  by a typo.

**The socket's bind is not the instance guard, and this ADR does not let it
become one.** ADR-0083 §14.4 is explicit: "Single-instance enforcement is the
lock, not the bind." That has a concrete consequence for the bind sequence. A
stale `hub.sock` survives a `SIGKILL`, and binding over it requires unlinking it
first — which is only safe because **ADR-0083 §1's exclusive `flock` is already
held by then**, and a held lock always means a live holder. So the order is
fixed: take the lock (ADR-0083 §3 step 2), and only afterwards unlink any stale
socket and bind. Unlinking before the lock would let a losing contender delete a
live hub's socket, which is exactly the failure the lock exists to prevent.

**Lifecycle, threaded into ADR-0083 §3 and §4 without changing either:**

- The listener is created and begins accepting at **step 6** of ADR-0083 §3, and
  not before — discharging ADR-0083 §14.2, "the transport must not accept before
  readiness", so no request is ever served against a half-built engine.
- At the **start of phase A** (ADR-0083 §4) the listener stops accepting and the
  socket file is unlinked. Unlinking there rather than at the end is deliberate:
  it makes "draining" indistinguishable from "not running" to a *new* client,
  which is the correct answer — a new request cannot be served either way, and
  ruling 4's legibility is served by one clear message rather than by a
  connection that hangs for the length of an unbounded phase B.
- Connections already accepted are in-flight work; ADR-0083 §4's phases own them.
  Nothing here bounds them separately.

**The address family is the reversible half of this section.** Replacing the
socket with a TCP listener is a bind and a connect, plus the credential §2 makes
room for and the egress decision named above. That is why this section is short
and §2 and §3 are not.

### 2. Connect is a handshake, and it has a place for a credential it does not carry

**Every connection opens with one client frame and one server frame, before any
request.**

The client sends a connect frame carrying the **protocol version** (§3) and a
**client identifier** (a free-form name for logs — `assistant-cli`). The connect
schema also **defines** a **credential field**, which this transport does not
populate. The server replies with its own protocol version, a **build
identifier**, its readiness, and its **effective maximum frame size** (§3, where
that field earns its place). Only then may a request be sent.

**The credential field is defined by the schema and carries nothing here, and the
server refuses a frame that puts something in it.** This is the whole point of the
section, so the rule is stated as a rule, and stated so that a conforming client
has an encoding:

> The credential field is **optional on the wire**. On this transport a
> conforming client either omits the member or sends it empty, and both are
> accepted. A connect frame carrying a **non-empty** credential is **refused**,
> with a distinct error naming the reason.

Accepting-and-ignoring is the alternative and it is the dangerous one: a client
that presents a credential and is admitted has been told, by admission, that its
credential was checked. Nothing on this transport checks anything — the `0600`
bit is doing the work — so admitting a credentialled connect would manufacture
exactly that false belief, and it would do so silently on the day someone points
a future authenticating client at an old hub. Failing closed costs one error
branch and makes the upgrade legible.

**Peer credentials are available and are deliberately not used as
authorisation.** `SO_PEERCRED` yields the connecting process's uid on Linux, and
it is worth naming because it looks like free security. It is not needed: the
`0600` bit already restricts connection to the owning user, so a `SO_PEERCRED`
check would re-derive the same fact one layer up. It is named because it is
*where* authorisation would attach if a future transport needs a local identity
finer than "the owner", and knowing that seam exists is worth a sentence.

**Why a handshake rather than a version on every message.** The handshake is the
cheapest place to put a fact both sides need exactly once, it is the natural home
for the credential above, and it is the thing §3's refusal needs in order to fail
*before* a request has been half-processed. A per-message version field would pay
the cost on every frame and buy the ability to change versions mid-connection,
which nothing wants.

### 3. One protocol version, exchanged once, matched exactly, refused at connect

**The protocol version is a single integer exchanged in the connect handshake and
nowhere else. It becomes connection state; it is not repeated on subsequent
frames.** Client and server must agree exactly; a mismatch **refuses the
connection** with a message naming both versions and the operator action.

Every frame after the handshake travels in an envelope whose *interpretation* is
fixed by the negotiated version — the version governs the envelope, it is not
carried in it. Stating it that way is not pedantry: it is what makes §2's
"handshake rather than a version on every message" a rule an implementation can
actually satisfy, and it fixes for both halves whether a post-connect frame is
expected to contain the field. It is not.

**Refusing a mismatch is the right answer here, and it is not laziness.** Client
and server are the same `uv` environment on the same machine, installed together
and upgraded together; there is no supported deployment in which they differ
except a half-finished upgrade, and a half-finished upgrade is precisely the
state ruling 4 wants legible rather than papered over. Tolerant negotiation is a
promise to correctly interpret *several* versions, and nothing in this repository
would ever test the old ones — a compatibility surface that is asserted and never
exercised is worse than a refusal, because it fails silently and later.

**The connect exchange is version-invariant, and that is what makes the refusal
above reachable at all.** Refusing with a message naming both versions is only
possible if a v1 hub can decode a v2 client's connect frame far enough to *read*
its version — and nothing guarantees that if a later version is free to change
the bootstrap. Left unstated, a half-upgraded deployment would fall into the
undecodable-frame close specified below, and the operator would see a connection
that dropped instead of the message this section promises: the failure the
section exists to prevent, arriving through the mechanism meant to prevent it. So
one rule is frozen:

> **The length prefix, the UTF-8 JSON codec, and the connect frame's version
> member keep their representation in every protocol version, permanently.** A
> later version may add members to the connect exchange, and may change anything
> it likes after the handshake; it may not change how a connect frame is framed,
> how it is decoded, or where its version is read from.

That costs nothing today and cannot be added later — the same test §2's
credential slot and this section's version already passed, applied to the one
frame that has to survive a version disagreement in order to report one.

**The version exists from day one anyway, and that is the retrofit this ADR is
buying off.** A remote spoke is a deployment where the two halves genuinely can
differ, and the day that arrives the negotiation becomes a change to *what the
handshake does with a number it already exchanges* — not the introduction of a
concept the wire has no room for.

**The envelope's required fields** are a message kind and a correlation id. It
carries **no length member of its own**: the frame's length is the prefix below,
which covers envelope and payload together, so a second length inside the
envelope would be a value that can disagree with the one already read — and a
frame whose two lengths disagree has no defensible interpretation. §4's
unbounded-payload constraint is discharged by the prefix, not by a member.

**The framing and the codec are normative, because two implementations that
satisfy every rule above could still be unable to exchange a frame.** Naming the
envelope's *fields* does not fix their *representation*, and the remote-spoke
seam this ADR is built for is exactly where that gap would surface. So:

- **Framing** is a **4-byte big-endian unsigned length prefix** followed by that
  many bytes. The prefix counts the bytes that follow it — envelope and payload
  together — which also settles what `hub_max_frame_bytes` bounds: that same
  number, so the cap is checked against the prefix before anything is read (§3
  above) and there is one answer to "does the limit include the envelope".
- **The codec is UTF-8 JSON**, and the envelope is a JSON **object** with named
  members carrying the kind, the correlation id and the payload. Member order is
  therefore not significant and no ordering rule is needed — which is worth
  stating rather than leaving to be inferred.
- **Duplicate member names are rejected**, in the envelope and in payload
  objects alike. JSON permits them and decoders disagree about which one wins,
  so `{"kind":"request","kind":"error",…}` could decode as a request in one
  implementation and an error in another — the same bytes, two meanings, which
  is exactly the interoperability failure this subsection exists to prevent.
  Rejecting is also the only option compatible with the rule above that an
  undecodable frame closes the connection: a decoder that silently picked one
  would not be undecodable, merely wrong.
- **Payload encoding follows what the value is**, and the rule is stated only as
  widely as it actually holds — the façade does not return models everywhere:
  - a **request** payload is a JSON object whose members are the call's
    arguments;
  - a **result** payload is a promoted `core` model (§4) serialised through
    pydantic's JSON mode — or `null` where the method returns an optional
    (`belief` returns `Belief | None`), or a JSON array of them where it returns
    a sequence (`beliefs`);
  - **arguments and scalars** — a `str` utterance, a flag, an optional id, a
    `timedelta` budget — take pydantic's JSON-mode form for their type, so a
    duration is an ISO-8601 string rather than a convention invented here;
  - **errors are a distinct message kind**, carrying a typed code and a message,
    never a result payload. That is what lets §7's unknown-continuation and §4's
    oversized-value failures be told apart from a successful response **by kind**
    rather than by inspecting a result for something that looks like an error.

**Not every failure can be a correlated error, and the boundary is the envelope.**
A frame refused on its *prefix* is refused before any envelope has been decoded,
so the server has not learned a correlation id and cannot produce one — which
would make the rule above unsatisfiable on exactly the path §3 most insists on.
So the two classes are separated:

- **If no envelope decodes, the server closes the connection without a
  response.** That covers the whole class rather than a list that would go stale:
  a malformed or oversized length prefix, a read deadline expiring mid-frame,
  bytes that are not valid UTF-8, text that is not valid JSON, JSON that is not
  an object, and an object missing a required member. There is no correlation id
  to quote and **no agreed encoding to reply in** — a peer that has already
  violated the framing is not one to write more framed bytes at, and that is
  precisely where two implementations would diverge. A connection ceiling (§3) is
  refused the same way, before a byte is read.
- **A frame that decodes gets a typed error rather than a silent close —
  provided it is not itself a violation of the connection's own rules**, the one
  exception being the third bullet below. This covers the connect exchange's own
  contents: a version mismatch (§3) and a non-empty credential (§2) are members
  of an envelope that parsed, so they are reported properly and only then does
  the connection close. It is what keeps the handshake's refusals legible —
  ruling 4 would be poorly served by a silent close on a version mismatch, and it
  does not get one.
- **Post-envelope request failures are ordinary correlated errors**: an unknown
  continuation (§7) and an oversized *result* (§4). The envelope has been read,
  so the id is known.
- **The one exception on this side is a second request arriving while one is
  outstanding.** Its envelope decodes, so the rule above would reach it, and it
  must not: a correlated error would carry the *second* request's id, which the
  mismatch rule separately obliges the client to reject — so the refusal could
  never be consumed. It closes the connection instead. Stating the exception
  once, here, is deliberate; it was previously written into one of the two rules
  and not the other, which is how a contract acquires two answers to one input.

**All three bullets scope to the *server* and the frames it receives.** The
client has one rule of its own, and keeping it separate is what stops "the one
exception" from being false: a **response** whose correlation id does not match
the request the client has outstanding is a protocol violation, and the client
closes rather than resynchronising (below). That is a decoded frame answered by a
close too — but it is the client's obligation about a response, not the server's
about a request, and the two never apply to the same frame.

The client renders these differently, and must: a connection-level close is a
**transport** failure, which is not the same event as a request the hub received
and declined, and ruling 4's legibility is the reason the difference survives to
the user rather than being flattened into one message. A close with no response
is reported as what the client was attempting when the connection went away.

Choosing an existing encoding rather than specifying a new one is the whole point
of this subsection: binding to the encoding the stores already depend on is what
makes #421's integer-encodability question **one** question rather than two, and
it is why §4's promotion to pydantic models makes the codec honest rather than
merely convenient. **The per-method mapping of arguments and results onto these
forms is the surface ADR's** (§5, step 2), along with the envelope's member names
and the DTO field layouts — it is exactly the signature-level detail that ADR
exists to fix.

**A connection carries one outstanding request at a time**, and that is a
decision rather than an omission. ADR-0042 §3 made the façade strictly
request/response and §5 kept it there — "v1 is strictly request/response" — so
nothing above this transport has a second concurrent request to issue. Making the
connection serial keeps the wire honest about that instead of implying a
concurrency the engine does not offer.

Two rules fall out, and both are needed because "one at a time" is only a
contract if a violation has a defined answer:

- **A request frame sent while another is outstanding is a protocol violation,
  and the connection is closed** — not queued, not run concurrently, and *not*
  answered with a correlated error. The correlated error is the tempting answer
  and it is unusable: its id would be the second request's, which by the next
  rule the client must treat as a mismatch against the request still outstanding,
  so a conforming client could never consume the refusal it was sent. A rule
  whose own response violates the adjacent rule is not a rule.
- **A response whose correlation id does not match the outstanding request is a
  protocol violation**, and the connection is closed rather than resynchronised.
  A stream that has desynchronised cannot be repaired by guessing.

Closing on both is not severity for its own sake. A client that issues two
concurrent requests on a connection this ADR defines as serial has a bug that no
in-band message will fix, and the client is stateless (§7) — so reconnecting
costs it nothing, which is what makes closing the cheap answer rather than the
harsh one.

**So the correlation id has one job today and one reason to exist tomorrow.**
Today it detects exactly the desynchronisation above. Tomorrow it is what lets
multiplexing or a progress stream be added *additively* — ADR-0042 §5's deferred
extension — without renegotiating a frame that had nowhere to put an id. That is
the same "pay a field now, avoid a flag day later" trade as the version in this
section and the credential slot in §2, and it is the last of the three.

**A declared length is a claim, and the reader must be free to disbelieve it.**
A declared frame length is only safe alongside a ceiling, so the transport
also fixes:

- a **maximum frame size**, which is configuration with a named default;
- a declared length above it is **refused before a byte of payload is read** —
  which is a pre-envelope failure, so it takes the connection-level close
  specified below, not a typed error there is no correlation id to carry;
- the reader **never allocates the declared length up front**; it reads
  incrementally against the cap;
- a connect or a frame that stalls part-way is abandoned on a **read deadline**,
  so a peer that stops sending mid-frame cannot hold a connection open
  indefinitely;
- the same deadline runs while **waiting for the next frame's prefix**, not only
  mid-frame, so a peer that completes the handshake and then sends nothing is
  closed rather than holding a slot against the connection ceiling. Closing an
  idle connection is safe here for a specific reason: the client is stateless
  (§7), so it holds no server-side session to lose and reconnecting costs it
  nothing — which is why an idle timeout is a resource rule rather than a
  behaviour change;
- a **ceiling on concurrent connections**, and a separate, lower ceiling on
  connections that have not yet completed the handshake — both configuration with
  named defaults. Beyond a ceiling the listener **refuses rather than queueing
  without bound**, so the client reads a refusal instead of waiting on something
  it cannot tell apart from a hung hub (ruling 4, again).

**`hub_max_frame_bytes` is the *hub's* setting, and the handshake carries its
effective value to the client.** A limit that each side configured independently
would not be one limit at all: a client configured at 32 MiB against a hub at
16 MiB would accept a 20 MiB utterance that the hub then refuses on its prefix,
and §4's whole move — putting the size bound in the *contract* so both
implementations agree — would be false in the one place it is load-bearing. So
the server's value is authoritative, it is one of the fields the connect reply
returns (§2), and **the client enforces the number it was told** rather than one
of its own. An argument that exceeds it then fails in the client, locally, as
§4's typed contract error naming the limit — not as a connection that closes
mid-request.

This is the third job the handshake does, after the version and the credential
slot, and it is the one that would have been most annoying to retrofit: without a
connect exchange there is nowhere to publish a server-side limit, and every
client would have to discover it by being refused.

**The remaining figures are named here rather than left to the implementation**,
following ADR-0083 §7, which named every scheduler interval for ADR-0074 §9.3's reason: "a
'bounded default' with no figure is two conforming stores handing the same
continuation different history." The same applies with more force to a limit
whose whole job is to refuse:

| `Settings` field | Type | Default |
| --- | --- | --- |
| `hub_max_frame_bytes` | `int` | 16 MiB |
| `hub_read_timeout` | `timedelta` | 30 s |
| `hub_max_connections` | `int` | 64 |
| `hub_max_pending_handshakes` | `int` | 8 |

**Every one is refused at load time unless it is strictly positive**, in the
`gt=0` / `gt=timedelta(0)` form ADR-0083 §7 adopted from `confirmation_ttl` and
`conversation_tombstone_grace` — and two of them carry a second bound each:

- `hub_max_pending_handshakes` is refused unless it is **no greater than
  `hub_max_connections`**, since a pending ceiling above the total is a limit
  that can never bind.
- `hub_max_frame_bytes` is bounded at **both** ends, and both bounds exist
  because a value outside them yields a hub that starts and cannot serve:
  - **Above**, it must be **representable by the framing** — the 4-byte prefix
    caps a frame at `2^32 - 1` bytes and the envelope consumes some of that.
    Without this, a setting of 5 GiB would be accepted at load and would be a
    limit the contract declares (§4) but the wire cannot encode, so the
    in-process engine would accept a value the client provably cannot send —
    the very divergence §4 moved the limit into the contract to prevent.
  - **Below**, it must be **large enough for the mandatory handshake and the
    smallest valid envelope**. A value of `1` is positive and representable and
    still useless: no connect reply carrying a version, a build identifier,
    readiness and the effective frame size fits in one byte, so the hub would
    pass every startup step in ADR-0083 §3 and then refuse every client,
    including the CLI — indistinguishable from a hub that is down, which is
    ruling 4's failure. The exact floor depends on the envelope schema and is
    therefore fixed by the surface ADR (§5, step 2), which is the change that
    knows it.

  A configuration outside either bound is a deployment fault, and load time is
  where it should surface.

**None of them is nullable, and that is the one place this ADR departs from
ADR-0083 §7's convention.** There, `None` means "disabled", because a scheduler
job that never runs is a coherent deployment. Here it is not: a hub with no frame
cap or no read deadline has exactly the failure §3 exists to prevent, so "off" is
not an available value and a zero is a misconfiguration rather than a way to
express it. Validating at load is what keeps a zero from presenting as an outage —
a `hub_max_connections` of 0 would refuse every client, including the CLI, and
would look from outside exactly like a hub that is down, which is ruling 4's
failure produced by a config typo.

**The two ceilings are separate, and the handshake one is lower on purpose.** A
per-frame deadline bounds each connection but says nothing about how many there
may be, so without a connection ceiling a client in a crash loop — or a script
that forgot to close — exhausts descriptors and reader tasks while every
individual connection is still inside its deadline. And a connection that has not
completed the handshake has cost the hub a descriptor and a task while telling it
nothing, which is the cheapest state for a misbehaving peer to accumulate; giving
it a tighter budget than an identified client costs one number.

**The reason is robustness, not secrecy, and saying so keeps the rule honest.**
The `0600` bit already scopes a peer to the owning user (§1), so this is not a
defence against a hostile stranger and should not be sold as one. It is a defence
against the thing ADR-0083 is entirely about: a *resident* process. A hub that
dies on a malformed length, or that is held open by a client which stopped
sending, is a hub that is down — ruling 4's failure, arriving through the one
door this ADR opens. A one-shot CLI could shrug this off; a process that runs for
weeks cannot.

**This cap is a transport limit and is emphatically not #473's bound.** #473 is a
*semantic* question — how large a belief's evidence tuple may legitimately grow —
and it belongs to its own contract lane. The two meet at exactly one point: an
evidence tuple that grew past the transport cap would make a *legitimate* response
unsendable. That is one more reason the semantic bound is owed, and one more
reason §4 refuses to design as though it already existed. So the default is set
generously, and exceeding it surfaces as an error the client can read rather than
as a quietly shortened payload — #473 records that silent truncation is not
available in any case, ADR-0073 §4 forbidding a citation to be dropped silently.

**#421 is answered here, and the honest answer is "partly, and not enough to act
on."** #421 parks cross-process serialization portability until "the deployment
stops being single-user local-first", the concrete mechanism being that
`FrozenJson`'s integer bound is decided by running the real encoder and is
therefore gated by CPython's **process-global** `sys.int_max_str_digits`. The
tempting answer is that loopback does not count. That is wrong on #421's own
words, which name the condition as "**Multiple processes**/hosts may run with
different `int_max_str_digits` configs": a hub plus a CLI *is* multiple
processes, so the multi-process half of the trigger arrives with this ADR even
though the multi-host half does not.

It is still not taken, for three reasons that are about exposure rather than
about the trigger:

- The gap requires a **>4300-digit integer** inside a `FrozenJson` holder to be
  reachable at all.
- Closing it means adopting a fixed application-owned bound across all four paths,
  which #421 states "reverses a ratified design decision" and "needs its own ADR".
  That is not a local-API decision.
- The envelope version above is what makes a later fix negotiable rather than a
  flag day.

**What this ADR does add is one deployment constraint, and it costs nothing:**
the reference deployment does not set `PYTHONINTMAXSTRDIGITS`, so the hub unit and
the user's shell inherit the same interpreter default. That closes the reachable
half by configuration while #421 stays parked for the networked transition it was
written for. It sits alongside ADR-0083's D1–D4 as a deployment obligation, and it
is the only one this ADR adds.

### 4. The façade's result types promote to `core/types.py` as frozen pydantic models

**This is a consequence of §5, not an independent choice, and taking it in that
order is what makes it defensible.** §5 concludes the façade is promoted to a
Protocol in `core/protocols.py`. Golden rule 2 says `core` depends on nothing
else in `ai_assistant`, so a Protocol in `core` **cannot name a return type that
lives in `orchestration`**. The DTOs' location is therefore forced by the
Protocol's location; it is not a free decision made alongside it.

**What promotes:** the result types the promoted surface returns —
`TurnOutcome`, `StepOutcome`, `Confirmation`, `ContinuationToken`, `Belief`,
`Question` and the remaining outcome types the public methods return — **bounded
by one rule: the *transitive closure* of what the Protocol's methods name, not
just the types they return.**

**The transitive half is load-bearing, and naming only the returned types would
have been a golden-rule-2 violation waiting to happen.** A promoted DTO drags
every type its fields reach, and three of those live in `orchestration` today:

- `StepOutcome.disposition` is `Disposition` (`orchestration/runner.py:203`);
- `QueuedQuestion.question_state` is `QuestionState`
  (`engine.py:351`, `orchestration/questions.py:92`);
- `SuccessorLink` (`orchestration/questions.py:171`) is reached the same way and
  its own `state` field is that same enum.

Promote `StepOutcome` to `core/types.py` while `Disposition` stays where it is
and `core` imports `orchestration` — which golden rule 2 forbids outright and
`lint-imports` fails mechanically. So the closure comes too, and **the surface
ADR (§5, step 2) owns the complete graph explicitly** rather than discovering it
mid-implementation.

**Relocating an enum is not redefining it.** `Disposition` keeps its five members
and everything ADR-0037 ratified about them; §8's refusal to add a `FAILED`
member is unaffected by the move, and the same holds for `QuestionState`. What
changes is which module declares them.

**The alternative — mapping these values to primitives at the Protocol boundary —
is rejected**, and for §4's own reason. Encoding `Disposition` as a bare string
the client re-parses would put a second vocabulary on the wire, to be kept in step
with the first by hand, which is exactly the invisible drift that made the
separate wire schema the wrong answer below. A value worth returning is worth
returning as itself.

**The exact set, the field layouts and the method signatures are ratified by a
follow-on contract ADR — not chosen by the implementing lane.** That distinction
is the whole of this paragraph. Pinning a nineteen-method surface and ten DTOs'
fields *here*, in an ADR about a transport, would be the unspiked seam #281 and
`CONTRIBUTING.md`'s spike-first guidance both warn against; but leaving them to a
lane would make that lane the unreviewed author of `core` contract surface, which
golden rule 5 and ADR-0015 §5 exist to prevent. A second `Proposed` contract ADR,
written with implementation contact and reviewed as contract surface, is the only
option that is neither speculative nor unreviewed. **#281 is that ADR's brief** —
it already scopes exactly this work, and its own reasoning names this moment as
the trigger: adapters target one façade's DTOs today, and "a second engine
implementation is what §1's revisit-trigger promotes to a Protocol, **at which
point the DTOs become a ratified contract**."

**What they become:** frozen pydantic models under ADR-0068 §1 — `frozen=True`,
`tuple` collections, nested models frozen. They are already frozen dataclasses
with `slots=True`, so this changes the mechanism and not the semantics; what it
adds is validation and a serialisation form, which is the whole reason for the
move.

**Two properties of the existing types make this cheap, and one makes it
delicate.** Cheap: `Confirmation.parameters` is already a `FrozenJsonMapping`, so
the one field most likely to resist serialisation is JSON by construction; and
`StepOutcome.state` is already `ExecutionState`, a `core` pydantic model frozen by
ADR-0068 §1. Delicate: **the payload is not bounded.** `Belief` carries an
evidence tuple that #473 shows grows monotonically under `REINFORCE` with nothing
capping or pruning it. So the wire must frame with an **explicit length** and the
server must not read into a fixed buffer or assume a frame fits one (§3). The
bound itself belongs to #473's contract lane — this ADR only refuses to design as
though the bound already existed.

**A bounded transport and an unbounded contract are in direct tension, and it is
resolved by naming it rather than by choosing a large enough number.** §3's frame
ceiling means a value that serialises beyond it cannot cross — and the problem is
**symmetric**, which is easy to miss by thinking only about results. On the way
back, `Belief.evidence` is unbounded (#473). On the way in, `converse` takes an
unconstrained `str`, so a large enough utterance is a request frame no client can
send. Either way the same three ways out exist, and only one is available:

- **Silently truncate.** Forbidden — #473 records that ADR-0073 §4 does not
  permit a citation to be dropped silently, and truncating an *utterance* would
  answer a question the user did not ask.
- **Chunk or stream.** That is ADR-0042 §5's deferred streaming extension,
  inherited deferred here (§11). Inventing it now would ratify a streaming
  contract with no stage emitting one, which is the unspiked seam ADR-0042 §5
  rejected in as many words.
- **Fail, visibly and inside the contract.** An oversized value — argument or
  result — raises a typed `AssistantError` naming the limit and the field that
  exceeded it.

**The third is chosen, and the load-bearing half is where the limit lives.** If
the ceiling belonged to the transport alone, the wire client would refuse a
17 MiB utterance that the in-process `Engine` accepts, and the two
implementations §5 makes substitutable would diverge on a value both are handed.
So:

> **The size limit is part of the promoted Protocol's declared contract, not a
> property of the transport, and *every* implementation enforces it** — the
> in-process engine included. The conformance suite (§5) is what holds them to
> it.

That inverts the obvious reading, and deliberately. §3's ceiling stops being "a
thing the socket does" and becomes a bound the contract states, which the socket
then also happens to enforce for its own robustness reasons. A client is then
never silently less capable than the engine it stands in for, in either
direction.

**One residual gap stays open, and it is a sequencing fact rather than a design
hole.** A bound the contract enforces makes the two implementations agree, but it
does not make an unbounded type sensible: a belief whose evidence grew past the
limit becomes unreadable through *any* implementation, which is a memory-contract
problem and not a transport one. **So #473 is a prerequisite of the client lane,
not merely context for it** (§11). Until its bound lands, §3's ceiling is set so
that state is unreachable for any belief this system currently produces — the
observer cites at most `observation_batch_size` episodes, default 20 — rather
than *provably* unreachable. Recording that difference is the point: this ADR
does not get to call the problem solved by picking a big number.

**The two rejected shapes**, both genuinely arguable:

- **Make them pydantic where they live, in `orchestration`.** Rejected because it
  does not survive §5: a `core` Protocol cannot name them, so the Protocol would
  have to return `Any` or live outside `core`, and either defeats the promotion.
- **A separate wire schema in the hub package, mapped to and from the façade
  types.** Rejected, and this is the closer call. It buys real decoupling — the
  façade could evolve without breaking the wire. It costs two shapes that must be
  kept in sync by hand, and the drift would be **invisible**, because both halves
  ship from one environment and one version (§3) so no test ever sees a mismatched
  pair. A decoupling whose violations cannot be observed is not decoupling. It
  becomes the right answer on the day the two halves version independently, which
  is the remote leg, and the envelope version is what leaves that door open.

### 5. ADR-0042 §1's revisit trigger fires: the façade is promoted to a Protocol

**ADR-0042 §1 named this exact moment**, and this section is mostly the work of
showing the trigger is genuinely met rather than merely convenient:

> **Revisit trigger.** If a *second* engine implementation is ever genuinely
> needed — **a remote engine**, a degraded offline engine — the façade is
> promoted to a Protocol *then*, contract-first: its ADR and triad land before
> the second implementation.

A client that satisfies the façade's surface over a transport **is** that second
implementation. And the test is not merely that a second object appears; it is
that ADR-0042 §1's stated *reason for declining* stops holding. Its reasons were
that "there is exactly one orchestration engine", that "the engine has one
implementation and one class of consumer", and that a Protocol "would model a
substitutability that does not exist". After this ADR there are two
implementations — the in-process `Engine` the hub holds, and the client the CLI
holds — and the substitutability is the deliverable, not an abstraction: it is
what lets one adapter run against either, which is what "hub and spokes" means.

**So the promotion is ADR-0042's own instruction being carried out, on the
condition ADR-0042 itself set.** §12 records that this nonetheless owes a record
on ADR-0042, because a reader holding only that ADR would act on sentences that
have become false.

**Placement is `core/protocols.py`**, and ADR-0042's objection to that placement
is answered rather than ignored. It rejected the file on the ground that "every
Protocol is a capability the engine *consumes*; an entry contract is one the
engine *provides*, a different kind of thing." That asymmetry is real but it is
an observation about the file's current contents, not a rule anyone ratified;
`core/protocols.py` is where golden rules 1 and 5 point, it is the floor path the
review process already treats as contract surface, and splitting provided
contracts into a second file would buy a taxonomy at the cost of the one location
every guard and every reviewer already watches.

**`start()` and `aclose()` do not go on the Protocol.** They are the hub's
lifecycle, ADR-0083 §3 and §4 own them, and a client that could call `aclose()`
would be able to shut down the hub from a spoke — which ruling 3's spirit (a
client has no business driving the service's lifecycle) forbids as squarely as it
forbids autostart. The Protocol carries the **request** surface; lifecycle stays
on the concrete class the composition root builds.

**The triad is a separate lane and it merges before the client**, and it is
*preceded* by the contract ADR §4 names. Protocol + shared conformance suite +
canonical fake in `ai_assistant.testing` land as one unit (`CONTRIBUTING.md` →
"Adding a Protocol"), after the surface is ratified and before anything
implements against it (golden rule 5, ADR-0015 §5). The sequencing is therefore
**four** changes, not one:

1. **this ADR** — that the façade is promoted, what promotes, where it lives,
   and the boundary rules the surface must satisfy;
2. **the surface ADR** (#281's scope) — the method signatures, the promoted DTO
   set and their normative fields, **the complete transitive type graph those
   fields reach** (§4), and §8's step-identity field. `Proposed`, reviewed as
   contract surface, ratified before the triad;
3. **the triad** (`core/protocols.py`, `core/types.py`, conformance suite,
   canonical fake);
4. **the hub, the `wire` package, the client, and the `lint-imports` edits** (§6).

Steps 1 and 2 are split rather than merged because they answer different
questions and only one of them can be answered honestly today. *Whether* the
trigger has fired is decided by reading ADR-0042 against the deployment, which is
what this ADR does. *What the surface is* wants contact with a real client, which
does not exist yet — and #281 was filed for precisely that reason.

**The cost is named rather than discovered.** The engine's public surface is
around nineteen methods, so this is a large Protocol and a large conformance
suite — considerably more than the triads the corpus has written so far. That
cost is the reason ADR-0042 declined it in 2026-07, and the reason it is right
now is only that the second implementation has arrived. A smaller Protocol
covering "just what the CLI uses" was considered and rejected: a spoke needs the
whole surface, and a Protocol trimmed to today's caller would be re-widened by
the first adapter that reads beliefs.

### 6. A `wire` package, and the hub's entry point is its own console script

**The wire contract and the client need a home that neither `service` nor
`interfaces` can provide**, and working out which one is forced by a clause of
ADR-0083 that is easy to miss. ADR-0083 §8 places the hub in
`ai_assistant/service/` and rules that "`service` may import `app`… and `core`;
**nothing may import `service`**." So the client cannot live beside the server,
because `interfaces` would then have to import `service`.

**A new top-level package — `ai_assistant/wire/` (name illustrative, as ADR-0042
§2 named `app`) — holds the envelope, the framing, the codec, the error mapping,
and the client that implements the promoted Protocol.** It depends on `core` and
nothing else. `service` imports it for the server half; `interfaces` imports it
for the client half; nothing imports `service`, so ADR-0083 §8 stands unamended.

**The consequence is that the hub gets its own console script, not an `assistant
hub` subcommand.** `[project.scripts]` today declares one entry point into
`interfaces.cli`; a `hub` subcommand there would require `interfaces → service`,
which ADR-0083 §8 forbids. So the hub is a second console script (illustratively
`ai-assistant-hub`) pointing into `service`. This is a genuine constraint falling
out of a ratified rule rather than a preference, and it is recorded here because
the natural instinct is to add a subcommand and the failure would only surface as
a `lint-imports` error late in the implementing lane.

**Two `lint-imports` edits belong to the implementing lane** (§5's change 3), not
to this ADR:

- **Forbid `interfaces → app`**, which ADR-0083 §10 sequenced here: "Closing that
  edge — so no interface adapter can build an engine — becomes the mechanical
  enforcement of exclusivity, and it also forecloses the in-process fallback
  ruling 5 already rejects." It is well-formed only once the CLI has a client to
  obtain instead, which is what this ADR delivers.
- **Forbid everything → `service`**, expressing ADR-0083 §8's rule, which that
  ADR left to "the implementing lane".

`_open_engine` (`cli.py:629-654`) is the single seam this lands on: it is the one
function in the CLI that obtains an engine, so the adapter change is that function
plus the type it returns.

### 7. A continuation token from a previous process life is a distinct, typed refusal

ADR-0083 §14.7 hands this over explicitly, having settled the half that is not
mine: tokens stay process-scoped and **the hub will not persist the table**,
because ADR-0052 §1 already provides the durable path and persisting it would be
new durable state under ADR-0083 §6's discipline, bought for nothing.

**The decision: presenting a token the server cannot resolve yields one specific,
typed refusal — an unknown-continuation error — and never a generic failure, and
never a denial.**

The distinctions are the substance:

- **It is not "denied".** A client that rendered an unresolvable token as a denial
  would be reporting a permission outcome that no policy authored — the failure
  ADR-0042 §4 and §6 exist to prevent, arriving through a new door.
- **It is not "expired".** An expired confirmation is refused at *answer* time by
  `_check_fresh` (ADR-0044 §4), the park is still real, and the remedy is
  different. Collapsing the two would tell a user their answer was too late when
  in fact the hub restarted.
- **One error covers both ways a handle can go missing** — a hub restart, and
  eviction under `max_outstanding_confirmations` — because the client's remedy is
  identical in both cases.

**The remedy is `pending_confirmations()`, and it is verified to work across
processes**, not merely argued to. Driving the shipped CLI end to end on
2026-07-31: `assistant ask` parked a confirmation and its process exited; a
**separate** `assistant resume` process enumerated the park from durable state and
re-minted a token. That is ADR-0052 §1's enumerate-and-re-mint working across a
process boundary today, which is what makes it safe to build the transport's
recovery story on it.

**The client stays stateless with respect to tokens, and under a resident hub that
is now a decision rather than a description.** Today each CLI command has its own
engine, so a token *cannot* outlive a command. Under the hub it can: the engine
lives on, so a token minted while answering one command would still resolve in the
next. The client nonetheless **does not persist tokens**; it re-enumerates. The
reason is ruling 4: a client that cached tokens would behave differently depending
on whether the hub happened to restart between two commands, and "it works unless
something invisible happened" is the opposite of legible. Re-enumerating costs one
bounded read (ADR-0052 §2) and behaves identically either way.

### 8. The disposition is the gate's verdict, not the step's outcome — and #531's premise needs correcting first

**#531 reports a real defect and misdiagnoses it, and the misdiagnosis matters
because the fix it proposes would damage a ratified contract.** The reported
behaviour is real and reproduced: a tool raised, `plans.db` recorded
`status: "failed"` with `kind: "internal"` exactly as ADR-0029 §4 requires, and
the CLI printed a green "Done." and exited `0`.

Three corrections, each checked against the tree at `main`:

- **`Disposition` has five members, not four.** #531 lists "exactly four" and
  omits `AWAITING_CONFIRMATION` (`runner.py:203-229`, whose own docstring says
  "Five members"). ADR-0037 ratified that shape.
- **The façade's vocabulary *can* express "ran and failed".** #531's load-bearing
  claim — "the façade's vocabulary cannot express the step's outcome, so no
  adapter can render it" — is false. `StepOutcome.state` is the full
  `ExecutionState` (`engine.py:189`, assembled at `:2220` from
  `StepDisposition.state`, which the runner documents as "Durable execution state
  after the last transition this pass committed" and which
  `_execute` populates with what the executor committed, `runner.py:1027`).
  `ExecutionState.steps` carries `StepExecution`, whose `status` may be
  `StepStatus.FAILED` and whose `failure: StepFailure` is **required** when it is
  (`core/types.py:2251`, `:2268`). The tool's own `ToolFailureKind` is right
  there.
- **The defect is in the adapter.** `_render_turn` calls
  `_render_disposition(step.disposition, step.tool_id)` (`cli.py:1289`), passing
  two fields and discarding `state`. The renderer maps `EXECUTED` to
  "[green]Done.[/]" (`cli.py:1394`) because that is all it was given.

**So `Disposition` does not grow a `FAILED` member**, and refusing that is a
decision, not a technicality. `Disposition` is documented as "What became of one
plan step **at this stage**" — the selection-and-permission stage — and
`EXECUTED`'s own text already delegates the outcome downward: "The call was
authorised and handed to the executor; ``state`` carries the outcome the executor
committed." Adding `FAILED` would fuse two independent axes (did the gate let it
run / did the run succeed) into one enum, make `EXECUTED` mean "ran and
succeeded" retroactively, and amend ADR-0037's ratified five-member shape to fix
a bug that is not in it.

**What *is* a real contract gap, and what this ADR ratifies:** `StepOutcome` names
no step. It carries `disposition`, `state`, `tool_id` and `confirmation`, and
`state.steps` is the whole tuple — so a client holding a `StepOutcome` has no
contract-supported way to say *which* step this pass drove. `tool_id` is not an
answer: two steps may bind the same tool. Today the CLI does not notice because it
reads neither.

> **`StepOutcome` gains the identity of the step the pass drove**, so that
> `state` becomes addressable, and the ratified rule is: **the disposition is the
> gate's verdict; the named step's `status` and `failure` are the outcome.** A
> client that renders success from the disposition alone is wrong.

This is #531's own second option — "the façade's step result grows a separate
outcome field alongside the disposition", which it calls "probably cleaner" — in
its minimal form. It adds one field rather than duplicating status and failure
onto the outcome, because duplication would create two sources of truth for a
fact `state` already carries correctly.

**What is ratified here is that the identity exists and what the rule is; its
spelling and type are the surface ADR's** (§5, step 2), along with every other
field of a promoted DTO. Splitting it that way is what keeps one lane from
choosing a `core` field unreviewed.

**Why this belongs in *this* ADR rather than a later one.** ADR-0084 is what puts
this façade behind a transport, and §4 promotes `StepOutcome` to `core/types.py`
as a ratified contract. A field added before that promotion is a design decision;
the same field added afterwards is a `core` contract change under golden rule 5,
owing its own ADR. Deferring it would therefore make it strictly more expensive
for no benefit, and every spoke built in between would inherit the blind spot
verbatim.

**The adapter half is the implementing lane's**: rendering a failed step as a
failure, and the exit code. A scripted caller today "cannot tell a successful turn
from a failed one without opening `plans.db`" (#531); once the outcome is
addressable, a non-zero exit on a failed step is an ordinary adapter
responsibility under ADR-0042 §6's "set process exit codes". #531 stays open until
that lands — this ADR settles the contract question it raised, not the defect it
reported.

### 9. One setting locates both the data and the door

**The socket path derives from `Settings.data_dir`** (ADR-0083 §2) as
`<data_dir>/hub.sock`. No new required setting: a client that can find the data
directory can find the hub, and the environment variable already works through
pydantic-settings for both halves. This is deliberately the same field on both
sides — a hub and a client that disagree about the data directory would otherwise
fail with a missing socket rather than with the misconfiguration they actually
have. §1 is what makes "the same field" mean the same directory: without its
absolute-and-canonical rule, two processes with different working directories read
one setting and reach two paths.

**The variable is `ASSISTANT_DATA_DIR`, not `AI_ASSISTANT_DATA_DIR`**, and the
correction is recorded rather than made silently. `Settings` sets
`env_prefix="ASSISTANT_"` (`core/config.py:554`), so the prefixed name is
`ASSISTANT_DATA_DIR`. **ADR-0083 §2 names it `AI_ASSISTANT_DATA_DIR` and is
wrong about it** — an operator following that sentence would set a variable
`Settings` ignores and would silently get the default directory, which for a
decision whose whole subject is where the data lives is worth more than a
footnote. That slip is a *factual* error in a ratified ADR rather than a decision
this ADR changes, so nothing here amends ADR-0083: under ADR-0070 §1 it is a
candidate for a self-amendment — a dated note reconciling an ADR with a fact —
and it is filed as an issue rather than fixed from this lane, whose fence is this
ADR and ADR-0042.

**One optional override** exists for the day the transport is not a socket, and it
is optional precisely so that the common deployment configures nothing. Its
spelling belongs to the implementing lane.

**`base_url` for the observer route is not this.** #462 asks for endpoint
configuration so ADR-0077 §3's on-device observer route becomes reachable; that is
an egress-surface decision under ADR-0004 §2 and ADR-0013 §6 and wants its own
ADR. It is named here only so the two settings are not conflated by a later lane.

**A closed door is an instruction, never a fallback.** When no hub is listening,
the client fails with a message naming the socket path it tried and how to start
the hub, and **exits non-zero**. It does not spawn the hub (ruling 3) and does not
build an in-process engine (ruling 5) — the latter now also being mechanically
impossible once §6's `interfaces → app` edge closes, which is the point of closing
it. This is ruling 4 at the client: the hub being down is a fact the user reads,
not a silent degradation.

### 10. The hardening tail, corrected

The roadmap attaches a hardening tail to this ADR. It is shorter than it reads.

- **#305 is struck from leg 5.** The roadmap lists the execution-id nonce "under
  multi-process reality", but ADR-0049 §3 is titled for #280 **and #305** and
  already applied the fix: the pid is read at allocation
  (`planning/sqlite_store.py:1087`) and `incarnation_factory` is injectable
  (`:266`, `:303`). What remains is an `InMemoryPlanStore` test seam, which is a
  `planning` item. ADR-0083 §12 reached the same conclusion; this ADR records that
  the tail it was attached to does not want it either.
- **#505 (WAL) and #526 (`BEGIN IMMEDIATE` on `SqliteMemoryStore`) are ADR-0083
  §12's, and are inherited unchanged.** Exclusivity is what decides them, and
  exclusivity is ADR-0083's ruling, not this ADR's. Nothing in a loopback
  transport reopens either: **the client never opens a database**, so this ADR
  adds no second writer and does not disturb the premise §12 rests on. Recording
  that explicitly is the point — a hub plus a CLI *looks* like the two-process
  case those issues were waiting for, and it is not.
- **#421** is answered in §3, including the one deployment constraint it produces.

### 11. Deferred, by name

- **Authentication and authorisation.** No credential is defined, only the place
  one goes (§2). The scheme, its storage (`SecretStore` is the obvious home), and
  what an identity means for a single-user system are the remote leg's.
- **The remote transport's egress authorisation.** §1: a non-loopback hop engages
  ADR-0017 §1 and owes a ratified decision. This is the gate on ruling 1's
  dedicated machine, and it is the one piece of it that a wire format cannot
  pre-buy.
- **Streaming and progress.** ADR-0042 §5 deferred it "until a progress-emitting
  stage exists"; none does. The envelope's correlation id is what keeps the
  addition additive (§3).
- **#473's evidence bound.** Its own contract lane, with the memory-contract
  decision about `get_many` — this ADR does not decide the bound. But it is named
  here as a **prerequisite of the client lane**, not merely as context: §4 shows
  that an unbounded result type and §3's bounded frame are reconcilable only by a
  contract-visible failure, and that the residual gap closes when the type is
  bounded and not before.
- **#462's endpoint configuration**, §9.
- **#333's plan-level reclamation**, and the observation cursor — both ADR-0083
  §13's, unchanged.
- **The field layout of the promoted DTOs and the exact method set of the
  Protocol** — deferred to the **surface ADR** of §5's step 2, not to a lane,
  written with implementation contact. That is #281's standing instruction and
  #281 is its brief.

### 12. Amendment records under ADR-0082 §1

ADR-0082 §1 requires the judgement to be made in the later ADR's text, naming the
clause and applying ADR-0070 §1's test: would a reader holding only the earlier
ADR now act differently, or read one of its clauses more widely than it now
holds?

**No record is owed on:**

- **ADR-0083.** This ADR is what its §14 deferred to. A deferral discharged by the
  ADR it named is a stacked addition — ADR-0083 §15's own rule, applied to
  ADR-0083.
- **ADR-0017.** Examined in §1 and found not to engage a loopback listener; the
  remote case is deferred rather than decided. Examining a clause and finding it
  unmet changes nothing (ADR-0083 §15's treatment of ADR-0026).
- **ADR-0004 §4.** §1 applies its `0600` posture to a new object of the same kind.
  Nothing is read more widely: the clause is about owner-only permissions in the
  data directory, and that is exactly what is done.
- **ADR-0037.** §8 declines to change `Disposition`. Its five-member shape and
  every sentence about it stay true.
- **ADR-0052.** §7 uses §1's enumerate-and-re-mint as given, as the mechanism it
  was written to be.
- **ADR-0044 §4.** §7 keeps answer-time freshness exactly where it is and only
  refuses to conflate it with an unresolvable handle.
- **#281's subject matter.** Not an ADR; §4 and §5 discharge it rather than amend
  it.

**ADR-0042 is partially superseded, and this change writes the record.**

Four clauses fail the test, and the first two fail it flatly:

- **§1: "We will not add an engine-facing Protocol to `core/protocols.py`, and we
  will not add a new `core/types.py` type."** §5 adds the Protocol and §4 adds the
  types. The sentence becomes false. A reader holding only ADR-0042 would build an
  adapter against a concrete class and would not look for a contract.
- **§2: "Every adapter (the CLI now, an API later) obtains its engine by calling
  this package's `build_engine` and does no construction or injection itself."**
  After §6 the CLI does not call `build_engine`, and ADR-0083 §10's `lint-imports`
  edit makes the attempt a build failure. A reader acting on this sentence would
  write code that cannot land.
- **§1's "promotion to `core` is reserved for 'the day a subsystem needs to
  receive one,' which this is not."** §4 promotes without a subsystem needing to
  receive one — the transport does. The clause is read more narrowly than it
  states, which is the second limb of the test.

- **§7: "obtains the façade from the composition root"**, and "closing the façade
  on exit". This is §2's fact restated at the adapter level, and it is ruled on
  here rather than folded silently into §2 — a reader consulting §7 alone is
  misled by both phrases. A client obtains a client, and it does not close a
  façade that outlives its command inside the hub. **The rest of §7 survives, and
  the record says so**: "The first adapter is the **CLI**" stays true, relaying
  consent via `resume` stays true, and §7's refusal to make the adapter
  responsible for subsystem construction is strengthened, not weakened, by
  exclusivity.

**The instrument is partial supersession, not an amendment**, and one precedent
that appears to point the other way is addressed rather than ignored:

- **ADR-0070 §1 is categorical.** "An ADR may be amended in place only when the
  amendment changes no decision… **Any change to what was decided requires a new
  ADR that supersedes the old one** — wholly, or partially." "We will not add an
  engine-facing Protocol" is a decision, and it is reversed.
- **ADR-0083 §15's stacked-addition carve-out does not reach it, on its own
  stated test.** That rule holds where "the deferring sentence **stays true** and
  now has an answer" — as ADR-0007 §2's "a future scheduler" and ADR-0074 §8's
  "later by the hub's scheduler" both do, neither becoming false. ADR-0042 §1's
  sentence does not stay true; it is contradicted. A clause saying "we will not
  do X" is not discharged by a later ADR doing X, it is superseded by it.
- **The revisit trigger licenses the change without changing its instrument.**
  §1's "If a second engine implementation is ever genuinely needed… the façade is
  promoted" says *when* to revisit; it does not pre-authorise the reversal or make
  it non-decisional. ADR-0070 §1 carries ADR-0001's rule verbatim — "to change a
  past decision, write a new ADR that supersedes the old one and update the old
  one's status". **A foreseen change is still a change.**

**So ADR-0042's `Status` takes the leading `Partially superseded by` token**, with
the appended dated note ADR-0070 §1 requires in every case. Under ADR-0082 §2 a
leading-token line carries no amendment qualifier beside it — and there is none to
move, ADR-0042's line having been plain `Accepted`. The record is **append-only**:
the superseded sentences are left standing exactly as written, and the note records
that they became false, which clause of this ADR did it, and that §1's own revisit
trigger is what made the outcome legitimate. Rewriting them would be the failure
ADR-0001's append-only rule exists to prevent — a ratified text quietly reshaped to
match a later decision, with no trace it ever said otherwise.

**It lands in this change**, so ADR-0042's `Status` never names an ADR that does
not exist; and while this one is `Proposed` the line names a supersession that is
drafted rather than ratified, the form ADR-0075 established and ADR-0083 §15
re-argued at length. If this change does not land, neither does the record.

**The supersession has a fan-out, and two further ADRs inherit it.** This is the
part that is easy to miss: ADR-0042 §1's "not contract surface" claim was *cited*
by later ADRs to justify their own DTO decisions, and superseding the claim
falsifies the sentences that rest on it. A reader holding only the later ADR never
learns that its premise moved. Applying ADR-0070 §1's test to each:

- **ADR-0078 §8 — a record is owed.** Three sentences fail. "Per ADR-0042 §1 the
  seam is the concrete `orchestration` façade, which is **not** contract surface"
  is false after §5. "`Question` is a **frozen `orchestration` dataclass**…
  it crosses no *subsystem* boundary" is false after §4, which promotes `Question`
  to `core/types.py`. And the operative one: reach 1 "requires the façade's learn
  DTO to carry the deferral id — **an `orchestration` widening, not a contract
  change**". After §4 that DTO is `core` contract surface, reached transitively as
  `LearnOutcome → IngestSummary → QueuedQuestion → QuestionState` (`engine.py:433`,
  `:412`, `:351`), so widening it *is* a contract change owing an ADR under golden
  rule 5. A reader acting on that sentence would ship a `core` change with no ADR
  — the exact process failure ADR-0015 §5 exists to prevent.
- **ADR-0073 — a record is owed.** "**The `Belief` DTO** is a frozen
  `orchestration` dataclass… alongside `TurnOutcome` and `IngestSummary` and for
  their reason: it crosses no *subsystem* boundary, only `interfaces` (ADR-0042
  §1)." §4 promotes `Belief`, and `TurnOutcome` and `IngestSummary` with it. Same
  failure, same reason.
- **ADR-0077 — no record is owed**, and it is checked rather than assumed because
  it uses the same phrase. Its "not contract surface" is about the rule §5 places
  on the shipped `DefaultMemoryPolicy`, a concrete policy — not about the façade.
  Untouched by this ADR, and the sentence stays true.

**Those two records are not written in this change**, and the reason is the fence
rather than the reasoning: this change's scope is this ADR and ADR-0042. The
analysis is recorded here — which is the half ADR-0082 §1 calls operative, "the
judgement is made in the later ADR's text, which is where it is reviewed" — and
the records themselves are owed from whichever change is scoped to carry them,
alongside this one. Recording the fan-out rather than discovering it later is the
point: a supersession of a *premise* propagates to everything that cited it, and
nothing mechanical detects that.

## Consequences

- **The CLI stops being the application and becomes a spoke.** `_open_engine`
  obtains a client instead of building an engine; `interfaces` loses its edge to
  `app`; the hub gets its own console script because ADR-0083 §8 forbids
  `interfaces → service` (§6).
- **`core` gains a Protocol and a family of result types**, so golden rule 5 is
  triggered literally — unlike ADR-0083, which added only `Settings` fields and an
  error class. A triad is owed and is a separate lane merging before any client
  (§5). **Four changes, in order: this ADR; the surface ADR that ratifies the
  method signatures and DTO fields (#281's scope); the triad; the
  implementation.** The middle step exists so no lane authors `core` contract
  surface unreviewed.
- **`core` also gains four `Settings` fields** — the transport's frame, deadline
  and connection ceilings (§3) — each strictly positive at load time, none
  nullable. They are contract surface in ADR-0054's sense, which this ADR already
  was.
- **The system gains a third top-level package**, `wire`, holding the envelope,
  the codec and the client, depending only on `core`. `service` and `interfaces`
  both import it; nothing imports `service`.
- **`StepOutcome` becomes able to say which step it is about**, and the ratified
  rule that the disposition is not the outcome closes #531's contract half before
  the transport can propagate the blind spot to every future spoke (§8).
- **A stale continuation token has one typed answer**, distinguishable from denial
  and from expiry, and the client stays stateless by decision rather than by
  accident (§7).
- **The transport gains frame and connection ceilings, refusals and read
  deadlines** (§3), so a malformed length, a peer that stops sending, or a client
  in a crash loop cannot take a resident hub down. These are transport limits and
  leave #473's semantic bound exactly where it was.
- **The remote leg is one bind away on the wire and one ratified decision away in
  fact.** The envelope carries a version, the handshake has a credential slot, and
  the client is stateless — the three expensive retrofits are bought. What is not
  bought, and is named so nobody assumes it, is authorisation to move user data off
  the device: ADR-0017 §1 governs that and this ADR does not touch it (§1, §11).
- **What is harder:** the DTOs become ratified contract surface, so changing a
  field that was free to change in `orchestration` now costs an ADR. That is the
  intended cost of putting them on a wire, and #281 anticipated it — "a second
  engine implementation is what §1's revisit-trigger promotes to a Protocol, at
  which point the DTOs become a ratified contract."
- **Revisit when** a spoke runs off the device (the transport, the credential, and
  ADR-0017 all move together); when the two halves can version independently (§3's
  refusal becomes a negotiation, and §4's rejected separate wire schema becomes the
  right answer); or when a stage emits progress (ADR-0042 §5's streaming
  extension).

## Alternatives considered

- **TCP on `127.0.0.1`.** Rejected in §1: reachable by every local process and
  user and by host-networked containers, with no ratified access control to lean
  on, where a Unix socket reuses ADR-0004 §4's `0600` posture on an object the
  kernel already enforces it for. It is also one edit from binding a public
  interface, which would cross ADR-0017 §1 silently.
- **An abstract-namespace socket**, which would sidestep `sun_path`'s pathname
  budget entirely and need no unlink. *Rejected*, and it is the obvious escape
  from the length check above, which is why it is written down: an abstract
  socket has **no filesystem presence and therefore no permission bits**, so it
  is reachable by every process in the network namespace and forfeits the exact
  ADR-0004 §4 control that §1's whole argument rests on. It would also be
  Linux-only. Paying a startup validation is much the cheaper side of that trade.
- **Use the socket bind as the single-instance guard.** Rejected because ADR-0083
  §14.4 already decided it — "single-instance enforcement is the lock, not the
  bind" — and because it inverts §1's safe unlink ordering: unlinking a stale
  socket is safe *only* under the lock.
- **A credential field that the server accepts and ignores.** Rejected in §2:
  admission is itself a claim that the credential was checked, and this transport
  checks nothing. Refusing costs one branch and makes the future upgrade legible.
- **`SO_PEERCRED` as the authorisation check.** Rejected in §2 as re-deriving what
  the `0600` bit already guarantees; kept as the named seam for a future local
  identity finer than "the owner".
- **Per-message version fields, or tolerant version negotiation.** Rejected in §3:
  a tolerant negotiation promises to interpret versions nothing in the repository
  would test, and an untested compatibility surface fails silently and late. Exact
  match at connect fails loudly and immediately, which is ruling 4.
- **Take #421's fixed integer bound now.** Rejected in §3: the multi-process half
  of its trigger does arrive with the hub, but the exposure needs a >4300-digit
  integer and the fix "reverses a ratified design decision" needing its own ADR
  (#421). A deployment constraint closes the reachable half meanwhile.
- **Keep the façade concrete and give the CLI a wire-shaped client that is not an
  engine.** Rejected in §5. It would avoid the triad and avoid touching ADR-0042
  §1 — the cheapest path on paper. It fails on ruling 1: every adapter would then
  be written against the wire client, the in-process path would become untested
  dead code, and a spoke would not be "another implementation of the engine" but a
  second parallel front end. ADR-0042 §1 named "a remote engine" as the trigger
  precisely so this would not be improvised.
- **A separate wire schema mapped to and from the façade types.** Rejected in §4,
  and the closest call in this ADR: real decoupling, but two hand-synchronised
  shapes whose drift no test could observe while both halves ship from one
  environment. It becomes right when they version independently.
- **Promote only the methods the CLI uses today.** Rejected in §5: a spoke needs
  the whole surface, so a trimmed Protocol would be re-widened by the first adapter
  that reads beliefs — and widening a `core` Protocol costs an ADR each time.
- **Give `Disposition` a `FAILED` member** (#531's first option). Rejected in §8:
  it fuses the gate's verdict with the invocation's outcome, retroactively changes
  what `EXECUTED` means, and amends ADR-0037's ratified five-member shape to fix a
  defect that lives in `interfaces/cli.py`.
- **Persist the continuation-token table so handles survive a restart.** Rejected
  by ADR-0083 §14.7 before it reached this ADR: new durable state under its §6
  discipline, buying what ADR-0052 §1 already gives.
- **Let the client build an in-process engine when no hub is listening.** Rejected
  by ruling 5, and made mechanically impossible by §6's `interfaces → app` edge
  closing — which is the form ADR-0083 §10 asked for.
