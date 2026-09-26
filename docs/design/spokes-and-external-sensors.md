# Spokes and external sensors

**Current design.** This file states the rules in force for spokes and external
sensors, and the questions still open. It is rewritten in place when the design
changes; it is not append-only, and git history keeps earlier versions. The ADRs
keep *why* each rule was chosen. Each bullet cites the marked clauses it restates
(`ADR-0094 §5:1-2` = the first two marked clauses under ADR-0094's §5); ADR-0084
predates clause marks and is cited by section. Clauses of the in-scope ADRs that
this file does not restate are accounted for in
[`spokes-and-external-sensors.ledger`](spokes-and-external-sensors.ledger).

## 1. Terms

| Term | Meaning |
| --- | --- |
| **Spoke** | Any program that reaches the hub across a process boundary, over the local API. There is one kind of spoke. |
| **Profile** | What a spoke does: a *client* carries a person, a *sensor* reads the world, an *actuator* acts on it. A profile is vocabulary, not a type. |
| **Push / doorbell / pull** | The three capabilities a spoke may exercise: send content unsolicited; say "there is something to come for" with no content; answer the hub's request for content the spoke has released. |
| **External sensor** | A spoke in the sensor role. "Sensor" as a profile name is unaffected by the renaming of the in-hub contract to `Reader`. |
| **Reader** | A producer running *inside* the hub that reads a source (calendar, email, files). A reader is not a spoke, and nothing in this file binds it. |
| **Device** | One machine admitted to reach the hub remotely, identified by one overlay identity. A device is not a spoke (one device may run several), not a principal, and enrolling it is not a grant. |
| **Peer** | Reserved for the transport's other end and a future hub-to-hub link. A spoke is never called a peer. |

- No rule may depend on which profile name a spoke is given; each obligation
  names the capabilities it binds, or the whole spoke. (ADR-0094 §1:1-4)
- A reader is not a spoke; "peer" keeps its transport meaning. (ADR-0094 §1:2, §1:5; ADR-0095 §1:3)
- A device is the unit of remote admission and revocation; a spoke is admitted
  and expelled with its device. (ADR-0124 §5:1-2)

## 2. The spoke

### 2.1 Connecting

- The spoke always opens the connection. The hub never dials a spoke and a spoke
  never accepts a connection; an overlay address for a device is not permission
  to dial it. Pull and notifications travel over a connection the spoke opened.
  (ADR-0094 §2:1; ADR-0124 §10:1; ADR-0131 §Context:1, §Context:3; ADR-0174 §10:2)
- The hub writes a frame only in answer to a request the spoke sent; no frame
  kind or path writes to a device unsolicited. (ADR-0131 §1:1)
- **On the hub's machine** the spoke connects to `<data_dir>/hub.sock`, an
  owner-only socket in an owner-only directory. After connecting and before
  sending anything, it checks from the kernel that the server runs as its own
  user, and refuses otherwise. (ADR-0084 §1)
- **Handshake.** Every connection opens with one connect frame each way: protocol
  version, client name, and an optional credential member. The version must match
  exactly or the connection is refused naming both versions. The hub announces its
  frame ceiling and the client enforces that number. (ADR-0084 §2, §3)
- On the loopback socket a credential must be absent, empty or JSON `null`; a
  non-empty one is refused. (ADR-0084 §2; ADR-0124 §7:4; ADR-0131 §6:1)
- **From another machine** the spoke connects to the hub's remote listener over an
  owner-administered overlay network that authenticates every participant and
  encrypts end to end. The listener is off unless configured, binds only an
  overlay address, and nothing depends on one overlay vendor. (ADR-0124 §2:1-4)
- The overlay operator sees device metadata and never a request or response; no
  part of this system talks to the control plane or embeds the overlay agent.
  Self-hosting the control plane is an operating act, not a decision.
  (ADR-0124 §3:1-4)
- The hub learns a device's identity from its own overlay agent, never from what
  the device asserts; the device refuses a hub whose overlay identity is not the
  one it enrolled with, and no setting overrides that identity. (ADR-0124 §4:1-3)
- Whoever queries an overlay agent first checks from the kernel that the agent's
  socket belongs to root or to itself, on every socket path, and reports a
  refusal as the identity being unavailable. (ADR-0131 §7:1-4)
- The remote client sends only the connect frame and the requests it was asked
  to make, to a destination taken from configuration, never from discovery or a
  redirect. (ADR-0124 §1:2)
- **Admission takes two independent facts**: the overlay identity names a live
  enrolment, and the connect frame's credential verifies against it. A missing,
  empty, non-string or malformed credential is refused. Refusals distinguish
  unenrolled, revoked and bad credential, with lowercase codes on the handshake
  path, and never echo the credential. (ADR-0124 §7:1-3, §7:5, §7:7)
- The remote listener is held to the same frame ceiling, read deadline and
  connection ceilings as the loopback one, counted once across both.
  (ADR-0124 §7:6)
- **One request at a time** per connection. A second request while one is
  outstanding, or a response with the wrong correlation id, closes the connection.
  A frame that does not decode closes it with no reply; a decoded bad frame gets a
  typed error. (ADR-0084 §3)
- **Notifications** are fetched by polling: a device keeps one dedicated delivery
  connection that carries nothing else, and a second concurrent poll from the same
  device closes the connection that made it. A device's identity for these rules
  is the one admission established, never a payload field; all loopback
  connections count as one local device. (ADR-0131 §2:1-3, §4:12-13)
- A spoke uses the whole promoted engine surface through the wire client; it
  cannot drive the hub's lifecycle, never builds an engine, and never opens a
  database. (ADR-0084 §5, §6, §10)
- User data leaves a device only through `models/`, the designated `tools/` seam,
  the hub's remote transport to an enrolled device, or the gateway's remote
  browser transport; any other egress is a bug. (ADR-0174 §1:1)
- ADR-0094 itself authorises no spoke off the hub's machine; remote spokes are
  authorised by the remote-transport decision alone. (ADR-0094 §10a:6)
- There is one hub; an enrolled device is served by it and is never a second hub.
  (ADR-0124 §10:4)

### 2.2 Enrolment and revocation

- A device is enrolled only by an explicit owner act at the hub, over loopback or
  a hub-local entry point. No remote connection, model, plan, tool, job, setting
  or migration can create, extend or change an enrolment. (ADR-0124 §6:1)
- Enrolment mints a credential of at least 128 random bits, shown once, and
  discloses the hub's overlay identity with it; a client holding one without the
  other refuses to connect. The hub keeps only a hash verifier, compared in
  constant time, and the credential fits the 256-byte connect bound.
  (ADR-0124 §6:2-5)
- The enrolment record (identity, verifier, enrolled and revoked instants) is hub
  durable state in `data_dir`. A revocation is recorded, not erased (ADR-0126
  narrows this for an act that destroys the record). One live enrolment per
  identity; re-enrolling revokes the old one in the same act. (ADR-0124 §6:6-8)
- On the device the credential and hub identity live only in the OS keyring,
  under the `ENROLMENT` secret scope; the hub identity is the one non-secret the
  keyring seam may hold. The credential never reaches a database, log, audit
  record or error. (ADR-0124 §6:9; ADR-0125 §2:2, §5:3)
- The client reads the credential only on its connect path, through the narrow
  `Secrets` face; enrolment and unenrolment hold `SecretStore`. That one bootstrap
  read is exempt from the permission gate, in exchange for single purpose, OS
  keyring custody, and the hub auditing every admission and refusal.
  (ADR-0124 §6:11-13; ADR-0125 §8:3)
- Revoking is an explicit owner act at the hub. Afterwards the credential admits
  nothing, the device's connections close, no request on them is dispatched, and
  the hub writes no further frame to it, including an unfinished response.
  (ADR-0124 §8:1-4)
- Revocation is prospective: what the device already received it keeps.
  Removing a device from the overlay is a separate act; only the hub's revocation
  binds. A revoked credential is never reinstated. (ADR-0124 §8:5-7)
- The device can unenrol itself, without the hub, which purges its keyring
  entries. Deleting the owner's data at the hub revokes every enrolment and reports
  which devices still hold a credential. (ADR-0124 §8:8-11)

### 2.3 Standing

- The hub decides the trust band of what a spoke submits. A spoke may not claim
  or influence it; a claim in a submission is not evidence. (ADR-0094 §5:1)
- Every spoke has a band ceiling. A submission above it is refused, not
  downgraded. (ADR-0094 §5:2)
- Being remote neither raises a spoke's ceiling nor supplies one. A device adds
  no principal, account or data rights, and enrolment is not a grant.
  (ADR-0124 §5:3-5)
- A spoke's labels are only labels: a source label, claimed speaker or replied-to
  item establishes no authorship, instruction or permission, and a channel label
  never authenticates a sensor. Channel metadata grants no transport authority.
  (ADR-0274 §5:4, §9:2; ADR-0275 §9:7; ADR-0276 §3:6, §4:10)

### 2.4 When the hub is unreachable

- A closed door is an instruction, never a fallback: the client reports the socket
  it tried and how to start the hub, and exits non-zero. No autostart, no
  in-process engine, no switching transport. (ADR-0084 §9; ADR-0168 §1:2)
- Beyond its connection and frame ceilings the hub refuses rather than queues;
  a client can tell a refusal from a hung hub. (ADR-0084 §3; ADR-0124 §7:6)
- A transport failure is reported as such, distinct from a request the hub
  received and declined. (ADR-0084 §3; ADR-0168 §9:1)
- Nothing is replayed. A disconnect creates no durable job or delivery promise, a
  hub restart never replays input, and there is no exactly-once processing.
  (ADR-0274 §7:9, §7:11; ADR-0275 §8:13)
- The client keeps no continuation tokens; after a restart it re-enumerates
  pending confirmations. (ADR-0084 §7)

### 2.5 State held at the edge

- A spoke may hold temporary state, bounded in size and age and destroyed
  continuously. It is never authoritative, and none of it counts as released until
  a promotion puts it there. (ADR-0094 §9:1-2)
- Released material is held under custody rules (§3.5), not the buffer's age
  bound. (ADR-0094 §9:3)
- No producer relying on edge state ships before `VISION.md`'s sensor-spectrum
  amendment is ratified. (ADR-0094 §10a:7)

### 2.6 Intelligence stays in the hub

- No spoke transcribes, synthesises, summarises or interprets on the hub's
  behalf; no adapter calls a speech engine. (ADR-0094 §6:1; ADR-0200 §2:1)
- No lane adds `core` surface for a rule here without its own ADR merged first.
  (ADR-0094 §10a:5)

## 3. The external sensor

### 3.1 How it reaches the hub

| Mode | Who starts it | What it carries |
| --- | --- | --- |
| **Push** | The sensor | Released input, on a channel (§3.4) |
| **Doorbell** | The sensor | Nothing: no content, summary, label, or provenance, not even when it happened |
| **Pull** | The hub, over a connection the sensor opened | Only what the sensor has released |

(ADR-0094 §1:3, §2:1, §4:1) How pull rides the serial protocol is open (§5).

### 3.2 What it sends

- **Only what it has released.** Release is the single gate on push and pull; a
  pull for anything unreleased is refused, and no hub setting or policy may widen
  it. Release is not authorisation. (ADR-0094 §3:1-4)
- **The source material, not a derivation.** An audio sensor sends audio, not a
  transcript. It may not destroy the material while its submission is unresolved;
  it may after a terminal, reported failure. A crash that loses it is a fault.
  (ADR-0094 §7:1-4)
- **Within the size bounds.** A spoken recording is bounded by
  `hub_max_spoken_audio_bytes` (decoded bytes) and refused, not truncated, above
  it; every call counts context and wrappers against the payload limit, and
  nothing is silently dropped. (ADR-0084 §4; ADR-0200 §6:1-2; ADR-0274 §8:1)
- An entry point that parses audio it did not author refuses a bad recording
  without echoing it. (ADR-0200 §9:7)

### 3.3 What it decides, and what it may not

- **It decides whether to send**: voice detection, wake phrase, bounding,
  thresholding. **Not what the input means**: no summarising, classifying,
  belief extraction, or provenance. (ADR-0094 §6:1)
- **It claims no audience.** An output channel with no declared audience is
  unbounded; a channel may not raise its own audience, and no spoke asserts one
  per request. The audience is never derived from the session that admitted the
  call. (ADR-0199 §1:2, §1:4, §8:3; ADR-0200 §3:7)
- **Sensed presence only narrows.** Occupancy, diarization, speaker ID or a
  paired device may move a channel from bounded to unbounded, never back, and no
  biometric match makes anything speakable. Unknown occupancy is unbounded.
  (ADR-0199 §4:1-4)
- **A capturing client names the owner, and only it.** A producer that renders
  distinguishable speakers and knows which is the owner states that speaker's tag,
  byte for byte, as `principal`; nobody derives one later. (ADR-0163 §2:1-2, §3:1)

### 3.4 Channels

- A channel is the pair (type, instance). It conveys no authority, audience,
  modality, memory ownership or ownership of work. (ADR-0274 §2:1)
- Two types exist: `conversation` (instance = conversation ID; typed and spoken
  input share it) and `informational_event` (instance = a source-local ID the hub
  does not register). Any other type is refused. (ADR-0274 §2:2-4)
- The complete admitted combinations; anything else is refused before any
  processing (ADR-0274 §4:2-3):

  | Channel | Payload | Reply |
  | --- | --- | --- |
  | `conversation` | text | whole or streamed |
  | `conversation` | speech | spoken |
  | `informational_event` | text | none |

- Context items (history, `reply_to`) are data; a replied-to ID is local to the
  channel and is not a fetch instruction. Text and transcripts keep their exact
  bytes, and no adapter invents a transcript. (ADR-0274 §3:3-4, §3:7)
- The context a channel supplies is read as it arrives, bounded only by the
  payload limit; the hub keeps no per-channel history. (ADR-0276 §3:2)
- The caller supplies no audience, permission or budget multiplier.
  (ADR-0274 §4:5)
- Replies return only on the call that asked; a reply declaration holds no
  callback or address, and `reply=None` produces nothing later.
  (ADR-0274 §6:4-5)
- No new browser route or unauthenticated event endpoint exists.
  (ADR-0274 §6:10)
- **Informational events** get one short factual summary, treated as quoted
  data: no planner, goal, tool, synthesis or notification. The summary is not a
  verified fact, and nothing is sent back to the source. The event is captured as
  its own standalone episode, not model-eligible, and is rendered later as a
  report received; payload and summary stay out of logs and traces. The pass
  counts as a bounded-audience pass. (ADR-0274 §7:5, §7:7, §7:10; ADR-0275 §6:4,
  §7:1; ADR-0276 §4:8, §4:12)
- Submissions are not idempotent: the activation ID is hub-minted and sending
  twice runs twice. (ADR-0274 §7:11; ADR-0275 §6:1)
- Every channel result reports whether its episode was recorded.
  (ADR-0275 §8:7)

### 3.5 Captured material

- The hub keeps submitted source material only for a verification window bounded
  by duration **and** size, enforced by refusing; after it closes, nothing may
  imply the capture is still correctable. Figures belong to the producer's ADR.
  Raw source material is never an episode. (ADR-0094 §8:1-4, §8:6)
- A spoke keeps no submitted material after its submission resolves. What
  "resolved" means is the custody handoff, which is open. (ADR-0094 §8:5)
- That handoff ADR is bound in advance: no acknowledgement before durable
  custody; every attempt ends in finite time; unresolved submissions are bounded
  in aggregate by count and bytes; it says whether they survive a spoke restart.
  (ADR-0094 §10a:1-4)
- Speech today: no audio, utterance or rendering, is retained anywhere, and no
  setting enables it. (ADR-0200 §8:1; ADR-0275 §4:4)

## 4. The browser gateway (a client spoke)

- The gateway is a client-profile spoke with no exemption. It holds no assistant
  logic and reaches the promoted surface only for admitted requests.
  (ADR-0168 §1:1-4)
- Its browser listener binds loopback only; serving another device's browser
  goes only through the remote browser listener. (ADR-0168 §2:1-3;
  ADR-0174 §1:1)
- Nothing about a browser crosses the wire: no session, token or per-browser
  ID, and no rule may depend on the hub telling browsers apart.
  (ADR-0168 §3:3-4; ADR-0174 §4:5)
- A web session is the gateway's in-memory admission record. It dies with the
  process and is not an enrolment, grant or principal; listing a remote browser
  device is none of those either. (ADR-0168 §4:1, §4:3-4; ADR-0174 §4:4)
- The gateway never dials a browser. (ADR-0174 §10:1)
- Hub connections are capped; beyond the cap it refuses, never queues.
  (ADR-0168 §8:7)
- Hub down: it still serves its listener and reports a transport failure, with no
  silent retry, queue or answer of its own. (ADR-0168 §9:1-2)
- It sets no band ceiling, triggers no spoke surface, and its session table is
  not edge capture state. (ADR-0168 §12:3-5)
- Spoken turns: push-to-talk uploads the whole recording in one request, the page
  uses `MediaRecorder`, never browser speech APIs, and the turn budget is the
  gateway's, never the browser's. (ADR-0200 §10:2-6)
- Playback report: the page reports `COMPLETE` or `INTERRUPTED` with durations
  for the answer it last played, by that answer's episode ID; the gateway
  invents no part of it. (ADR-0205 §7:1-4)
- A report is a device's claim, never verified; `UNKNOWN` is never supplied; it
  carries no audio or text. (ADR-0205 §1:2, §2:5-6, §2:8)
- Spoken output is unbounded-audience; a bounded spoken channel will be its own
  operation, not an argument. (ADR-0200 §3:6-8)

## 5. Open questions

- **Spoke surface in `core`**: spoke identity, capability descriptor, band-ceiling
  field, released-set representation. Deferred until a second spoke exists; the
  gateway is not one (ADR-0168 §12:3). Whether a hub-minted identity should
  replace a declared one is open.
- **Where band ceilings are declared**, and whether being remote should lower one.
- **What triggers a release** (#441) and the grant model (#629).
  (ADR-0094 §3:4)
- **Pull on the wire**, and hub-initiated delivery for proactivity.
  (ADR-0124 §10:3; ADR-0131 §Context:2)
- **Custody handoff**: acknowledgement, resolution, retries, restart recovery.
- **Whether ambient capture may write an episode**, and whether an episode with
  several speakers and no owner marker may be observed; that ruling belongs to
  the ADR admitting such a producer. (ADR-0163 §3:5-6, §6:3)
- **Model-based detectors at the edge**: whether routing and fallback rules
  reach them.
- **Speaker identification** at the edge (#691).
- **Voice beyond push-to-talk**: streamed speech, barge-in, spoken confirmation,
  a bounded-audience spoken channel.

## 6. Known conflicts in the record

Recorded so no reader has to rebuild them; each needs its own fix.

- **Has the second-spoke trigger fired?** ADR-0199 §8 (prose) calls the gateway
  the second spoke; ADR-0168 §12 (normative), ADR-0174 and ADR-0124 §5 say a
  second spoke of the same profile is not. This file follows the normative text:
  it has not fired.
- **Stale "remains Proposed" notes** in ADR-0274's and ADR-0275's headers about
  ADR-0275 and ADR-0276, both Accepted.
- **ADR-0274 §7's "creates no episode" and "nothing written to content stores"**
  are overtaken by ADR-0275 (events are captured as standalone episodes).
  ADR-0274's Status line records it; this file follows ADR-0275.
- **`VISION.md` §8 was never amended**, though ADR-0094 §10 requires it (it
  still says "every interface should be a stateless client"). No producer relying
  on edge state has shipped, so the gate is not yet breached.
- **ADR-0131 quotes clauses as its own.** Its Context section repeats ADR-0124's
  and ADR-0094's marked clauses as marked blockquotes, so they count as ADR-0131
  clauses. ADR-0131's own Context:1 then says "nothing in this ADR, including an
  overlay", which only makes sense in ADR-0124. This file cites the originals and
  treats the quotes as adding nothing.
- **ADR-0163's producer list is stale.** ADR-0163 §3 says exactly two producers
  capture episodes. ADR-0275 §6 added a third (standalone activation capture:
  events, failed or no-words speech) with no record on ADR-0163. The eligibility
  question §3 defers is answered in practice by ADR-0275 §7, since ineligible
  episodes are skipped by the observer. This file follows ADR-0275 (later,
  Accepted) and keeps ADR-0163's deferral open for sensor-captured multi-speaker
  episodes.
- **Not a conflict**: ADR-0094 §10a says it authorises no remote spoke;
  ADR-0124 authorises remote devices. ADR-0124 records that the clause concerns
  only what ADR-0094 itself authorises, so both stand.
