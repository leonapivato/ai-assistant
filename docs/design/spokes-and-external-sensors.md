# Spokes and external sensors

**Current design.** This file states what is decided now. It is rewritten in place
when the design changes; it is not append-only. The ADRs keep *why* each rule was
chosen; this file keeps *what the rules are*. Git history keeps earlier versions.

- Reconciled against: `main` at `82bfcbe0` (2026-09-25)
- Status marks: **built** · **decided** (ratified, not built) · **open** (not decided)

## 1. Terms

| Term | Meaning |
| --- | --- |
| **Spoke** | Any program that reaches the hub across a process boundary, over the local API. There is one kind of spoke. |
| **Profile** | What a spoke does: a *client* carries a person, a *sensor* reads the world, an *actuator* acts on it. A profile is vocabulary, not a type: no rule may depend on which profile a spoke is given. |
| **External sensor** | A spoke acting in the sensor role: it brings input to the hub. |
| **Reader** | A producer running *inside* the hub that reads a source (calendar, email, files). A reader is not a spoke, and nothing in this file binds it. |
| **Device** | A machine admitted to reach the hub remotely. A device is not a spoke: one device may run several spokes. A device is not a principal, and enrolling it is not a grant. |
| **Peer** | Reserved for the transport's other end or a future hub-to-hub link. A spoke is never called a peer. |

Sources: ADR-0094 §1; ADR-0095 §1; ADR-0124 §5.

## 2. The spoke

### 2.1 Connecting — built

- The spoke always opens the connection. The hub never dials a spoke, and a spoke
  never accepts a connection. Anything the hub sends a spoke travels over a
  connection the spoke opened. (ADR-0094 §2; ADR-0274 §6)
- **On the hub's machine** the spoke connects to a local socket readable only by
  the hub's user, and checks the server's identity from the kernel. A credential
  is refused on this path. (ADR-0084 §1–§2)
- **From another machine** the spoke connects over an owner-administered overlay
  network that authenticates and encrypts end to end. The hub learns the device's
  identity from its own overlay agent, never from what the device asserts, and
  the device refuses a hub whose identity is not the one it enrolled with.
  (ADR-0124 §1–§4)
- **Admission takes two independent facts**, neither enough alone: the overlay
  identity names a live enrolment, and the connection presents that enrolment's
  credential. (ADR-0124 §7)

### 2.2 Enrolment and revocation — built

- A device is enrolled only by an explicit owner act at the hub; no connection can
  create, extend or modify an enrolment. The credential is shown once; the hub
  keeps only a verifier. (ADR-0124 §6; ADR-0125)
- Revoking a device stops it being admitted and closes every connection it holds.
  Revocation is prospective: it does not retract what the hub already sent.
  Every spoke on a device is admitted and expelled with that device.
  (ADR-0124 §5, §8)

### 2.3 When the hub is unreachable — built

- A closed door is an instruction, never a fallback: the spoke reports the hub as
  unavailable. There is no autostart, no in-process substitute, and no switching
  to another transport. (ADR-0084 §9; ADR-0168 §1)
- Beyond its connection and frame ceilings the hub refuses rather than queues.
  (ADR-0084 §3; ADR-0124 §7; ADR-0131 §5)
- Nothing is replayed: a disconnect creates no durable job or delivery promise,
  and there is no exactly-once delivery. (ADR-0274 §7)

### 2.4 State held at the edge — decided

- A spoke may hold temporary state, bounded in size and in age and destroyed
  continuously, not at a checkpoint. It is never authoritative: nothing the hub
  does may depend on it, and none of it counts as sent until released.
  (ADR-0094 §9)
- Before any producer relies on this permission, `VISION.md` must be amended
  away from "every interface should be a stateless client" (ADR-0094 §10a;
  see §5).

### 2.5 Intelligence stays in the hub — built

No spoke transcribes, synthesises, summarises or interprets on the hub's behalf.
(VISION §8; ADR-0083; ADR-0200 §2)

## 3. The external sensor

### 3.1 How it reaches the hub

| Mode | Who starts it | What it carries | Status |
| --- | --- | --- | --- |
| **Push** | The sensor | Its input, on a channel | built |
| **Doorbell** | The sensor | Nothing: no content, summary, label, or provenance — not even when it happened | decided |
| **Pull** | The hub, over a connection the sensor opened | Only what the sensor has released | decided; how it rides the wire is **open** |

Sources: ADR-0094 §1–§4. Pull is not expressible on today's serial, spoke-initiated
protocol; it waits on an additive wire ADR (ADR-0094 §2, §10; ADR-0084 §11).

### 3.2 What it sends

- **Only what it has released** — decided. Release is the single gate on
  everything that leaves the sensor; the hub may not widen it. Release is not
  authorisation. What may *cause* a release is **open**. (ADR-0094 §3, §10)
- **The source material, not a derivation of it** — built for speech. A sensor
  may not substitute a lossy, model-dependent derivation: an audio sensor sends
  audio, not a transcript. It may not destroy the material while its submission
  is unresolved. (ADR-0094 §7; ADR-0200 §2)
- **A channel for its input** — built. See §3.4.

### 3.3 What it decides, and what it may not

- **It decides whether to send**: voice detection, wake phrase, bounding,
  thresholding. **It may not decide what the input means**: no summarising,
  classifying, extracting beliefs, or setting provenance. Detection rings the
  doorbell; distillation is the hub's. (ADR-0094 §6) Whether a model-based
  detector at the edge needs further rules is **open** (ADR-0094 §10).
- **It claims no standing.** The hub decides the trust band of what a sensor
  submits; a sensor may not claim or influence it. Every spoke has a band
  ceiling, and a submission above it is *refused*, not downgraded — decided.
  (ADR-0094 §5) Today every admitted caller's input is recorded as the user's own
  word. Where a ceiling is declared is **open**.
- **It claims no audience.** A channel may not raise its own audience, and sensed
  presence never widens what may be said. (ADR-0199 §4, §8)
- **Its labels are only labels.** A source label, claimed speaker or replied-to
  item establishes no authorship, instruction or permission. (ADR-0274 §2, §5;
  ADR-0275 §9)

### 3.4 Channels — built

- A channel is the pair (type, instance). It conveys no authority, audience,
  modality, memory ownership or ownership of work. (ADR-0274 §2)
- Supported combinations, and no others (ADR-0274 §4):

  | Channel type | Instance | Payload | Reply |
  | --- | --- | --- | --- |
  | `conversation` | conversation ID | text | whole or streamed |
  | `conversation` | conversation ID | speech | spoken |
  | `informational_event` | source-local ID | text | none |

- Context (earlier items, `reply_to`) is data. A replied-to ID is not a fetch
  instruction. (ADR-0274 §3)
- An informational event gets a short factual summary as quoted data; no planner,
  goal, tool or notification. It is captured as its own episode. (ADR-0274 §7;
  ADR-0275 §6; ADR-0276)
- Submissions are not idempotent: sending twice runs twice. (ADR-0274 §7;
  ADR-0275 §6)
- There is no file or attachment input.

### 3.5 Captured material — decided, handoff open

- A released slice is held under custody rules, not the temporary-state age bound.
  The hub keeps submitted source material only for a verification window bounded
  by duration and size, enforced by refusing. Raw source material is never an
  episode. (ADR-0094 §7–§8)
- The custody handoff ADR is bound in advance: no acknowledgement before the hub
  holds durable custody; every attempt ends in finite time; unresolved
  submissions are bounded in aggregate by count and bytes; it states whether an
  unresolved submission survives a spoke restart. (ADR-0094 §10a)
- A lost acknowledgement may deliver the same material twice (duplication, never
  loss); deduplication is left to the producer. (ADR-0094 §8)
- The hub retains no audio at all today. (ADR-0200 §8)

## 4. What exists

| Spoke | Profile | Input | Channel |
| --- | --- | --- | --- |
| Command line (`interfaces/cli.py`) | client | text | conversation |
| Browser gateway (`interfaces/gateway/`) | client | text; push-to-talk speech | conversation |
| Any admitted wire caller (`wire/client.py` `receive`) | — | text | informational event (only tests send one) |

No sensor-profile spoke, actuator spoke or capture producer exists. The browser
sits behind the gateway and has no standing the gateway lacks; browser sessions
are an in-memory admission record, not an enrolment. (ADR-0168 §1, §4, §12)

## 5. Open questions

- **Spoke surface in `core`**: a spoke identity, capability descriptor, band-ceiling
  field, released-set representation. Deferred until a second spoke exists
  (ADR-0094 §10). Whether a hub-minted identity should replace a declared one is
  open (ADR-0094 §11).
- **What triggers a release** (#441) and the grant model (#629).
- **Pull on the wire.**
- **Whether being remote lowers a spoke's ceiling.** (ADR-0124 §5)
- **Whether ambient capture may write an episode.** (ADR-0094 §10)
- **Speaker identification** at the edge (#691; ADR-0163 §3).
- **Voice beyond push-to-talk**: streamed speech, barge-in, spoken confirmation,
  a bounded-audience spoken channel. (ADR-0200 §11)

## 6. Known conflicts in the record

Recorded here so no reader rebuilds them; each needs its own fix.

- **Has the second-spoke trigger fired?** ADR-0199 §8 (prose) says the gateway is
  the second spoke. ADR-0168 §12 (normative), ADR-0174 and ADR-0124 §5 say a
  second device of the same profile is not a second spoke. This file follows the
  normative text: the trigger has not fired.
- **Stale "remains Proposed" notes** in ADR-0274 and ADR-0275 about ADR-0275 and
  ADR-0276, both of which are Accepted.
- **ADR-0274 §7's "nothing is stored"** is overtaken by ADR-0275 §6 (an event is
  captured as its own episode); ADR-0274's Status line records the partial
  supersession.
- **`VISION.md` §8 was never amended** as ADR-0094 §10 requires ("every interface
  should be a stateless client").
