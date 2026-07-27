# Roadmap — accumulation first: the user model, observation, and the hub

**Status: working guidance, not a ratified decision.** This document is the
tactical companion to [`VISION.md`](../VISION.md): the *why* and *what* live
there; this covers *how* and *in what order*. Nothing here is binding. Every
artifact that crosses a subsystem boundary (a new `core` type or a Protocol
change) is ratified in its own ADR **before** it is implemented — see
`docs/adr/` and the rules in `CLAUDE.md`. If this roadmap and an ADR disagree,
the ADR wins.

## Why this revision exists

The previous revision of this document tracked the first vertical — seven core
artifacts and one closed learning loop — to completion. That record lives in
this file's git history and, authoritatively, in the ADR ledger and the commit
log; it is not repeated here (ADR-0019, ADR-0067).

What that arc produced is lopsided in a specific way. The trust and state
machinery — permissions, durable confirmation, audit, cancellation and
atomicity guarantees, model-agnosticism as a tested property — is deep
(ADR-0021/0036/0044/0059 and the hardening decisions around them, ADR-0061/0062).
The thing VISION.md names as the moat — **an accumulated, user-controlled model
of one person** — has vocabulary but no engine: `MemorySource` has carried
`OBSERVED` and `INFERRED` provenance since ADR-0005, supersession law for how
inferred beliefs lose to user assertions is ratified (ADR-0038/0040/0050), yet
no code path produces an observed or inferred record, no interaction is ever
recorded, and the user has no way to see what the assistant believes. The loop
that exists learns only what the user explicitly dictates (ADR-0009), which is
the "repeatedly explain preferences" failure VISION.md opens by condemning.

This revision reorients the build around **accumulation**: the assistant builds
its model of the user primarily by observing, and the user steers it by
inspecting and correcting. Everything else — including capability breadth — is
sequenced behind that.

## Design stances

These are premises this roadmap sets, not measurements (ADR-0019 §3). Each
becomes binding only when an ADR ratifies the slice that implements it; the
first leg includes amending `VISION.md`, which today gestures at
interaction-implicit signals but does not own passive observation, the
sensor/actuator split, or the hub-and-spokes shape.

1. **Passive accumulation is the primary mechanism; explicit correction is the
   steering wheel.** The assistant observes interactions (and, later, ingested
   sources) and *proposes* beliefs with `OBSERVED`/`INFERRED` provenance,
   sub-1.0 confidence, and evidence; deterministic policy disposes; the user
   inspects, corrects, and thereby supersedes. This is the existing
   propose/dispose chassis (ADR-0005/0021/0037) given its most important
   producer — not a new architecture.
2. **Sensors before actuators.** Read-only ingestion (calendar-shaped sources
   that feed observation and context) comes early: it carries no
   irreversibility and forces the networked-egress decision (ADR-0017 §3) at
   its lowest-stakes end. Tools that *act* on the world arrive later and in
   bulk (MCP-shaped), behind the contract decisions they force — ranking
   (#241), parameter-schema enforcement (ADR-0029 §7), and the rest of the
   egress conditions.
3. **Hub and spokes, with one spoke for now.** One resident service — the hub —
   owns all state and intelligence; every interface is a stateless client of
   its API. Conversations, memory, and identity live server-side and are
   device-agnostic. **The only spoke for the time being is the CLI on the hub's
   own machine, over a loopback transport.** All large network constraints —
   transport security, device identity and enrolment, push delivery, backup —
   are deliberately deferred until a second physical device matters (see the
   later arc). Slices landing before the hub exists must not bake in
   single-shot or single-client assumptions.
4. **Deepen before broaden.** VISION.md's answer to its own scope risk still
   governs: narrow, complete loops over shallow breadth.

## The accumulation loop

The first vertical proved the *explicit* loop (correction → proposal → policy →
memory → reuse; ADR-0022). This arc's goal is the *ambient* one:

```text
interaction (or ingested source)
  → recorded as episodes
  → observer proposes beliefs (OBSERVED/INFERRED, evidence = episode ids)
  → policy disposes (ADR-0005), supersession law applies (ADR-0038/0040/0050)
  → user inspects the model, corrects what is wrong
  → correction supersedes; retrieval is better next turn
```

Proving this loop end to end — a belief the user never dictated, formed from
observation, visible to them, correctable by them, and improving a later turn —
is worth more than any breadth this roadmap defers.

## The legs, in order

Each leg decomposes into ADR-backed slices when it is dispatched, contract
first (`CLAUDE.md`). An exit test is stated in product terms, honouring the
previous revision's rule: **a gap closes when a user can exercise the
capability, not when a test can.** Legs 1–4 run inside the existing in-process
application; the hub (leg 5) is decided early enough that they are written for
it, and built before anything ambient or polling.

1. **The user model, visible.** The `UserProfile` ADR — what is asserted and
   user-owned versus inferred and revisable, and which the retrieval path
   reads — designed together with the observer (leg 3), since the inferred side
   is otherwise an empty ledger. The `VISION.md` amendment ratifying the design
   stances above. An inspection surface in the CLI: list, show, correct, and
   forget what the assistant believes, with provenance and confidence visible —
   the `MemoryStore` contract already carries `delete`/`export` (ADR-0007) but
   no interface reaches them. *Exit: the user can read the assistant's beliefs
   about them, see why each is held, and kill any of them.*
2. **Conversation and episodic capture.** A conversation becomes a first-class,
   server-side entity — device-agnostic, resumable from any future spoke — and
   every turn is durably recorded as `EpisodicMemory`. This is the substrate
   observation reads; `Provenance.evidence` was designed to cite episode ids
   (ADR-0005). Needs its own ADR: conversation identity and retention are new
   `core` surface. *Exit: the user can continue yesterday's conversation, and
   episodes exist that an observer could cite.*
3. **The observer.** A model-backed producer that reads episodes and proposes
   `OBSERVED`/`INFERRED` memories through the existing `MemoryPolicy` gate. Its
   ADR must decide, explicitly: the scope of observation and what justifies
   retention (VISION.md's selective-memory principle and ADR-0004's posture are
   the constraints, and the propose/dispose gate plus provenance-visible
   inspection is the mechanism that makes watching trustworthy); and **which
   model reads the raw episodes** — the episodic stream is the most sensitive
   data the system holds, the on-device embedder (ADR-0006/0024) is the
   precedent, and the router seam (ADR-0013) makes a local/small-model route a
   named option rather than an accident of configuration. *Exit: the assistant
   holds a correct belief the user never told it, and the user can see where it
   came from.*
4. **Epistemic soundness.** Observation mass-produces exactly the
   low-confidence, conflicting beliefs the current write path mishandles at the
   edges: a memory `ASK_USER` ruling has no resolution path and the conflict is
   silently dropped (#423); a correction contradicting more inferences than
   `conflict_limit` leaves the surplus live (#313/#314); bounded validity
   windows have no ratified retirement semantics (#306, needs an ADR). These
   land before the observer runs at volume. *Exit: a conflicting or
   many-conflict correction leaves the store consistent, and a deferred
   question reaches the user instead of vanishing.*
5. **The hub.** The resident service, as two decisions. The **service ADR**:
   process model and lifecycle (graceful drain of in-flight steps, supervision,
   upgrade-with-state discipline — of which the embedder-change migration,
   #425, is the first instance), and an internal scheduler that finally gives a
   caller to `purge_expired` (ADR-0007), confirmation deadlines (ADR-0059,
   whose wall-clock fragility #277 a resident process makes urgent), and later
   consolidation. The **local API ADR**: the Engine façade (ADR-0042) behind a
   loopback transport with the CLI as its first client — the spoke — with DTO
   and versioning choices made as if remote spokes exist, because they will.
   Hardening tail attached: the execution-id nonce under multi-process reality
   (#305), and the stores' concurrent-access posture. *Exit: the assistant is
   running before the user arrives and after they leave, and the CLI is merely
   a client of it.*
6. **Sensors.** The first read-only ingestion source or two, feeding both
   context facets (ADR-0008 anticipated calendar/tasks as optional fields) and
   the observer's episode stream. This is where ADR-0017 §3's conditions for a
   networked seam are finally met or consciously revised — at read-only stakes.
   MCP-shaped clients are welcome here, but as sensors only; actuators stay in
   the later arc. *Exit: the assistant knows something true about the user's
   day it was never told, from a source the user granted.*
7. **Memory at volume.** Consolidation (many episodes distilled into few
   durable beliefs, run by the hub's scheduler), confidence decay and salience
   so unreinforced beliefs age instead of accumulating, the size caps ADR-0007
   deferred, retrieval ranking under load, and the re-embedding migration
   (#425). *Exit: months of use make retrieval better, not slower and noisier.*
8. **Minimal evaluation.** The `EvaluationTrace` slice — Tier-2 operational
   data, no egress (ADR-0004) — plus a first few of VISION.md's success
   measures: memory precision, correction rate, repeated-explanation rate. This
   is also the hub's operational telemetry; a process that runs for weeks
   cannot be debugged by rerunning it. *Exit: "is the user model getting more
   accurate?" is answered by data, not opinion.*

## The later arc, in order

Named so near-term slices leave room for them; none is scheduled, and each
still needs decomposing into ADR-backed slices.

- **Remote spokes.** The bridge deferred by stance 3, crossed when a second
  physical device matters: network transport and its security posture (an
  overlay network keeping the API off the public internet is the leading
  candidate), device identity and enrolment/revocation — which then feeds three
  existing subsystems: a context facet (device is a VISION §Principle-4 input),
  a permission input (which devices may approve consequential actions —
  ADR-0004's deferred catalogue gains a sibling), and the audit trail's
  "approved from where" — a server-push delivery seam, and encrypted
  backup/restore, which is also the honest test of VISION.md's portable
  context-graph claim. ADR-0042's opaque continuation tokens already support
  cross-device park/resume unchanged.
- **Actuators, in bulk.** MCP-shaped tool breadth, behind the decisions it
  forces: ranking among capable tools (#241 — today a second capable tool
  stalls the step by design, ADR-0037 §1), parameter-schema enforcement
  (ADR-0029 §7), and the full egress conditions (ADR-0017). This is also where
  the permission machinery finally earns its depth: nothing registered today is
  irreversible, disclosing, or consequential.
- **Proactivity.** `NotificationCandidate` and the interruption policy — the
  one proposal artifact of the propose/dispose principle still unbuilt. It
  structurally requires the hub (something must be awake to notice) and a
  delivery channel (remote spokes' push seam).
- **An engagement surface.** The accumulation flywheel needs daily use, and
  nothing on this roadmap yet makes the assistant compelling daily. This entry
  is deliberately undesigned; it is named so its absence is a known debt of the
  plan rather than an oversight.
- **Commitment ledger, full evaluation harness, portable context graph.**

## Parked

- **The design-debt plans** (record mutability #41, enforcement scope, ADR
  governance): queued before this reorientation, explicitly parked behind the
  accumulation legs now. Revisit after leg 3 lands.
- **The test-hardening issue backlog** stays in the tracker and is worked
  opportunistically; none of it is scheduled here. The tracker, not this
  document, owns that list (ADR-0015/0019).
- **Ranking, parameter schemas, networked actuators** — parked *with intent*
  behind the MCP milestone above, not forgotten: they are contract decisions
  that become due the moment actuators do.

## Gap register

Where each VISION.md promise stands against this plan — stated as pointers to
the legs that close them, so the claim decays into the tracker and the ADR
ledger rather than into this document.

| VISION promise | What closes the gap |
| --- | --- |
| Understood — a persistent user model | Legs 1–3 (profile ADR, capture, observer) |
| In Control — inspect, correct, restrict, delete | Leg 1 (inspection surface over ADR-0007's contract) |
| More Capable Over Time | Delivered for explicit correction (ADR-0009/0022); legs 3–4 and 7 extend it to observation |
| Context determines usefulness | Leg 6 feeds facets ADR-0008 anticipated; device context waits on remote spokes |
| Supported — acts across tools | Later arc (actuators); deliberately last |
| Proactivity that earns its place | Later arc; requires the hub |
| Free to choose models | Delivered (ADR-0002/0011/0013/0061/0062) |
| Observability and evaluation | Leg 8, then the full harness |
