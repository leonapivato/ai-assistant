# Roadmap — accumulation, then inhabitation: the user model, the hub, and living in it

**Status: working guidance, not a ratified decision.** This document is the
tactical companion to [`VISION.md`](../VISION.md): the *why* and *what* live
there; this covers *how* and *in what order*. Nothing here is binding. Every
artifact that crosses a subsystem boundary (a new `core` type or a Protocol
change) is ratified in its own ADR **before** it is implemented — see
`docs/adr/` and the rules in `CLAUDE.md`. If this roadmap and an ADR disagree,
the ADR wins.

## Why this revision exists

The previous revision of this document tracked the first vertical — seven core
artifacts and one closed learning loop. That arc's record lives in this file's
git history and, authoritatively, in the ADR ledger and the commit log; it is
not repeated here (ADR-0019, ADR-0067).

The reorientation is a priority decision, not a status report. The first arc
invested in trust and state machinery — permissions, durable confirmation,
audit, cancellation and atomicity guarantees, model-agnosticism as a tested
property (ADR-0021/0036/0044/0059 and the hardening decisions around them,
ADR-0061/0062). VISION.md names the moat elsewhere: **an accumulated,
user-controlled model of one person**. ADR-0005 gave that model its vocabulary
(`OBSERVED`/`INFERRED` provenance), ADR-0038/0040/0050 its supersession law
(inferred beliefs lose to user assertions), and ADR-0009 its first belief
producer — explicit feedback, the user dictating facts about themselves.

This revision's premise is that the decisions worth making next are the ones
that put accumulated beliefs behind that vocabulary *without* dictation — an
episode record for observation to read, an observation producer behind the
propose/dispose gate, and an inspection surface that keeps the result the
user's to steer — because a system that learns only by dictation is the
"repeatedly explain preferences" failure VISION.md opens by condemning.
Everything else, including capability breadth, is sequenced behind
**accumulation**.

**That arc closed on 2026-08-09, and this revision adds the one after it.**
Legs 1–8 built the loop and then the instrument that judges it; leg 8's exit
test was ruled met by the operator on 2026-08-09 (#878), on the evidence of the
QA run recorded in #862 and after the two defects that run surfaced were decided
and fixed the same day (#865, ADR-0121, ADR-0122). What the accumulation arc
does *not* have is use. Every mechanism in it has been exercised by an operator
driving a laptop hub deliberately; none of it has accumulated from a life being
lived around it, and a flywheel nobody turns measures the same as one that does
not work. So the binding constraint moves from *can the system accumulate?* to
**is it there to accumulate from** — reach, duty cycle, and a reason to open it
tomorrow. That theme is **inhabitation**, and the operator's ruling of
2026-08-09 that sets it is recorded in #879; the arc section below transcribes
that ruling rather than re-deriving it.

## Design stances

These are premises this roadmap sets, not measurements (ADR-0019 §3). Each
becomes binding only when an ADR ratifies the slice that implements it; the
first leg includes amending `VISION.md` so that it owns passive observation,
the reader/actuator split, and the hub-and-spokes shape, none of which its
interaction-implicit learning language covers.

1. **Passive accumulation is the primary mechanism; explicit correction is the
   steering wheel.** The assistant observes interactions (and, later, ingested
   sources) and *proposes* beliefs with `OBSERVED`/`INFERRED` provenance,
   sub-1.0 confidence, and evidence; deterministic policy disposes; the user
   inspects, corrects, and thereby supersedes. This is the existing
   propose/dispose chassis (ADR-0005/0021/0037) given its most important
   producer — not a new architecture.
2. **Sensors before actuators.** Read-only ingestion (calendar-shaped sources
   that feed observation and context) comes early: it carries no
   irreversibility. **The second half of this stance no longer holds**: it read
   that ingestion also forces the networked-egress decision (ADR-0017 §3) at its
   lowest-stakes end, and leg 6 below records why it does not — a reader opens a
   file the hub can already read, so nothing about §3 is engaged or revised
   there. Tools that *act* on the world arrive later and in bulk (MCP-shaped),
   behind the contract decisions they force — ranking (#241), parameter-schema
   enforcement (ADR-0029 §7), and the rest of the egress conditions; that is
   where the egress decision is now expected to be spent, and it is **leg 12**
   that is now scheduled to spend it.
3. **Hub and spokes, with one spoke for now.** One resident service — the hub —
   owns all state and intelligence; every interface is a stateless client of
   its API. Conversations, memory, and identity live server-side and are
   device-agnostic. **This one is no longer a premise: ADR-0083 and ADR-0084
   ratify it and leg 5 built it**, down to the transport — the only spoke for the
   time being is the
   CLI on the hub's own machine, over a loopback Unix socket in the data
   directory. All large network constraints — transport security, device
   identity and enrolment, push delivery, backup — were deliberately deferred
   until a second physical device matters, and that is **leg 9**, where they now
   come due. ADR-0084 §1 and §11 fix the price of crossing that line: a
   non-loopback hop is user data leaving the device, so it engages ADR-0017 §1
   and owes its own ratified decision — leg 9's first contract question. It is
   not reached by swapping an address family. The caution this
   stance carried before the hub existed — that a slice must not bake in
   single-shot or single-client assumptions — is now the standing rule above
   rather than advice: a subsequent interface is a client of the API or it is not
   an interface.
4. **Deepen before broaden.** VISION.md's answer to its own scope risk still
   governs: narrow, complete loops over shallow breadth.

## The accumulation loop

ADR-0022 ratified the *explicit* loop (correction → proposal → policy →
memory → reuse). This arc's goal is the *ambient* one:

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

## The accumulation arc, in order — legs 1–8, closed 2026-08-09

Each leg decomposes into ADR-backed slices when it is dispatched, contract
first (`CLAUDE.md`). An exit test is stated in product terms, honouring the
previous revision's rule: **a gap closes when a user can exercise the
capability, not when a test can.** After a leg's last slice merges and before
the operator rules its exit, a QA run drives the leg's ruled behaviors
end-to-end through a live hub (`.claude/skills/qa-leg`), recorded as one issue
— per-lane review owns the slices; the run owns the composition seams between
them, which is where a leg's first run found a ruled mechanism no producer
could reach (#827). Legs 1–4 were built inside the in-process
application; the hub (leg 5) was decided early enough that they were written for
it, and built before anything ambient or polling. Everything after leg 5 is built
behind the hub's API.

1. **The user model, visible.** Decided and built. ADR-0072 answers what the
   profile *is*, and the answer is not the artifact this leg was written
   expecting: the profile is a **band** of the one memory store — `ASSERTED` is
   the profile, `DERIVED` the inferred model, `ATTESTED` a third band for what a
   source reported — classified by a total function, with confidence a matter of
   presentation rather than ranking. ADR-0073 decides the surface over it: the
   band-scoped read is an **enumeration**, inspection shows live beliefs only,
   killing one is show-then-confirm, and **correcting is `learn`** rather than a
   second correction path. The `VISION.md` amendment ratifying the design stances
   above landed with ADR-0072 §9, as a new Core Principle. *Exit: the user can
   read the assistant's beliefs about them, see why each is held, and kill any of
   them.* ADR-0073 §4 rules that test met by what it ships, under a floor and two
   gates: no belief may be presented as carrying a warrant the surface cannot
   show, and neither empty band's first producer may land without the explanation
   its band owes. The `DERIVED` gate fell to leg 3, where ADR-0077 §6 ruled what
   a citation that no longer resolves renders. The `ATTESTED` gate still stands,
   on leg 6.

   **The residual is `export`.** This leg is where ADR-0007's `delete` obligation
   first met an interface; its `export` obligation did not, and ADR-0073 §10
   deliberately declined to bundle it, `MemoryStore.export` having existed since
   ADR-0007 and the remaining question being presentational rather than
   contractual.
2. **Conversation and episodic capture.** Decided and built. A conversation is a
   first-class, server-side entity — device-agnostic, resumable from any future
   spoke — and every turn is durably recorded as `EpisodicMemory`. This is the
   substrate observation reads; `Provenance.evidence` was designed to cite
   episode ids (ADR-0005). The `core` surface it needed is ratified across three
   decisions: ADR-0074 (identity, lifecycle, one episode per turn, retention,
   ordered conversation-scoped deletion, and the `ConversationStore` contract),
   ADR-0075 (deterministic capture is exempt from the proposal → policy write
   path), and ADR-0076 (a stamped conversation is enumerable, so a crashed
   deletion can be finished). *Exit: the user can continue yesterday's
   conversation, and episodes exist that an observer could cite.*

   **The residual is a window, not a gap in the surface.** ADR-0074 §11 leaves
   open the cross-store case under a process death — an episode landing after its
   conversation's tombstone was reclaimed — which wants a transaction rather than
   a lock. ADR-0083 §12 keeps it deferred and records that the hub narrows it
   without closing it, because the reclaim runs at every start rather than at
   whenever the user next types a command.
3. **The observer.** Decided and built, with two residuals. A model-backed
   producer reads episodes and proposes `OBSERVED`/`INFERRED` memories through
   the existing `MemoryPolicy` gate. **ADR-0077 decides both questions this leg
   was written to force**: the scope of observation — the producer reads the
   episodes it is handed and can read nothing else, proposes three kinds against
   a utility bar, and is refused for citing its evidence badly (§§1, 2, 5) — and
   **which model reads the raw episodes**, a named route with no fallback and a
   minimal payload (§3), the on-device embedder (ADR-0006/0024) having been the
   precedent and the router seam (ADR-0013) the mechanism. Observation is an
   explicit operation, not ambient machinery (§8); cadence belongs to leg 5's
   scheduler, which ships that job **disabled** until the durable cursor
   ADR-0083 §13 defers exists, because a timer without a cursor re-reads one
   window and reaches nothing new. *Exit: the assistant holds a correct belief
   the user never told it, and the user can see where it came from.*

   **Both residuals are gaps in reach, not undecided questions.** **#462** —
   nothing configures an endpoint, so ADR-0077 §3's on-device route cannot
   actually be named; ADR-0084 §9 rules that an egress-surface question under
   ADR-0004 §2 and ADR-0013 §6, owing its own ADR rather than a settings field.
   **#494** — an observation report cannot say where a deferred proposal went.
4. **Epistemic soundness.** Observation mass-produces exactly the
   low-confidence, conflicting beliefs the write path used to mishandle at the
   edges. All three edges are now decided, and each decision has shipped. A
   memory `ASK_USER` ruling is a **durable question the user answers** for the
   two arms that motivated #423 (ADR-0078), reachable as `assistant questions` /
   `answer` / `forget-question`. A correction contradicting more inferences than
   `conflict_limit` no longer leaves a surplus live — it **resolves every
   conflict it is shown, or it does not land** (ADR-0079, partially superseding
   ADR-0050 §1's over-limit surplus clause), enforced on both writers (#313).
   Retiring a *producer-set bounded* validity window **clamps, and refuses only
   what it cannot represent** (ADR-0080, partially superseding ADR-0045 §4
   step 1's window-close instruction) — ADR-0045 §4 had ratified retirement
   itself, supersession closing the prior record's window, but not that case
   (#306). *Exit: a conflicting or many-conflict correction leaves the store
   consistent, and a deferred question reaches the user instead of vanishing.*
   **Met** — with the qualification ADR-0079 itself attaches to it, and the
   residuals below.

   **#457 is that qualification**, in ADR-0079's own words "the next thing
   standing between leg 4's exit test and an unqualified claim":
   `SqliteMemoryStore.search` can under-serve a conflict query — retired records
   consume its headroom, so the exposure grows with use — and no writer-side rule
   can make the conflict set exhaustive over a store that returns less than all
   of it. **#460** is the other residual: the absolute,
   clock-coherence-independent retirement hide, split out of #306 (ADR-0080 §9).
   And the **secret-tier `ASK_USER` arm is genuinely open, not closed by
   decision** — ADR-0004 §3 forbids Tier 0 content a durable file, so ADR-0078 §1
   deliberately leaves that one arm asking a question the user cannot answer, and
   §11 gates closing it on the `SecretStore` seam `core/protocols.py` does not
   yet have, plus a producer that today does not exist. What is **not** a
   residual, despite an open tracker entry, is **#314**: ADR-0079 §3 promoted
   full-conflict-set retirement into the `MemoryWriter` contract with the shared
   suite and `FakeMemoryWriter` matched, and ADR-0078 §11 records it and #313 as
   "decided, and merged".
5. **The hub.** Decided and built. **ADR-0083 decides the process**: one
   resident instance per data directory, holding an exclusive lock and owning the
   databases in it so that no other process opens them; a fixed startup sequence
   with readiness signalled last; a two-phase shutdown, bounded where bounding is
   safe and unbounded where it is not; exit codes distinguishing "come back" from
   "stay down"; a refusal to start over state this build would serve *silently
   wrongly* — of which the embedder-change migration (#425) is the first instance
   — and the internal scheduler that five earlier decisions had already named as
   the home of a deferred job. **ADR-0084 decides the door**: a loopback Unix
   socket in the data directory, a connect handshake carrying a protocol version
   and a slot for a credential this transport refuses to carry, an envelope whose
   interpretation that version fixes, carried in a length-prefixed JSON frame
   with ceilings and deadlines against a peer that misbehaves, the Engine façade
   (ADR-0042) promoted to a Protocol with its result types promoted to
   `core/types.py` behind it, and the CLI demoted from *being* the application to
   being a client of it. *Exit: the assistant is running before the user arrives
   and after they leave, and the CLI is merely a client of it.* **Met, and
   exercised against the shipped code rather than asserted**: with no hub, the CLI
   refuses legibly at exit 1, spawning nothing and creating no data directory;
   with the hub resident, one client process writes a belief through the socket
   and a *separate* client process reads it back; with the hub killed, the CLI can
   do nothing at all, because ADR-0084's rulings 3 and 5 leave it neither a spawn
   nor an in-process fallback.

   **ADR-0084 §5 fixed the sequence as four changes; it took five, and the fifth
   is a rule about contract order rather than an accident.** ADR-0087 ratifies the
   canonical wire encoding and lands *before* the triad, because the triad ships a
   canonical fake — a second implementation — and two implementations holding an
   unratified byte count can both pass a behavioural conformance suite while
   disagreeing about which calls they refuse. ADR-0084's status line is where the
   amended sequence and the replaced payload-encoding rule are read; this entry
   does not restate them (ADR-0019). Two further contract decisions came out of
   the same implementation contact: **ADR-0085** fixes the promoted surface itself
   — fifteen methods, twenty-four types, one closed graph (#281's scope) — and
   **ADR-0086** bounds a belief's evidence and lands `MemoryStore.get_many`,
   because a bounded frame and an unbounded contract reconcile only through a
   failure the contract itself declares (ADR-0084 §11).

   **The residual is reach; the rest is corpus hygiene, not a gap in what
   shipped.** **#590** — the shared conformance suite lives beside the Protocol's
   first implementation, so the third implementation binds to it through a
   `sys.path` line rather than plainly. All three run the same file today, which is
   what ADR-0084 §4 asks for; the arrangement is what a fourth would trip on. The
   hygiene cluster is what the leg surfaced in the ADR corpus: **#571** (ADR-0087
   §6 and §9 disagree over which change owes an encoder), **#586**, **#589**, and
   **#588** — no gate step can fail on a `docs/adr/**` change, so an ADR's citation
   into the code is the one claim nothing checks.

   **The scheduler's job list is one job shorter than the deferrals naming it
   suggest, and the hardening tail is nearly gone.** Confirmation deadlines are
   not a scheduler job: reclaiming a permanently-parked confirmation is a
   contract ADR-0059 §3 deferred and nothing offers (#333), the lifetime is
   enforced at answer time regardless so nothing goes unenforced, and #277's
   wall-clock fragility is *not* fixed by a resident process (ADR-0083 §7, §9).
   Of the hardening tail, #305 leaves it for ordinary test backlog — ADR-0049 §3
   already applied the fix and exclusivity removes the multi-process premise — and
   the stores' concurrent-access posture is settled by there being no second
   writer: #526's `BEGIN IMMEDIATE` landed across all five stores as consistency
   work, leaving #505's journal-mode durability decision deliberately deferred
   (ADR-0083 §12, ADR-0084 §10).
6. **Readers.** The first read-only ingestion source or two, feeding both
   context facets (ADR-0008 anticipated calendar/tasks as optional fields) and
   the observer's episode stream. The seam is a `Reader`: ADR-0093 specified it
   as a `Sensor`, and ADR-0095 §1 renamed it, freeing "sensor" for the spoke
   profile ADR-0094 §1 uses it for. Stance 2's pairing above and the MCP note
   below carry that freed sense, not this one.
   **This leg does not reach ADR-0017 §3's conditions for a networked seam**,
   which an earlier revision of this entry expected it to meet or consciously
   revise. The owner's ruling scoping the leg is that the first source is a
   **local `.ics` file** (#625), and ADR-0084 §1 has already read both ADR-0017
   clauses for the hub's own socket: §1 governs data that leaves the *device*,
   and §3's fourteen conditions are conditions on designating the `tools/`
   egress seam. A file the hub opens on its own disk leaves no device, and
   ADR-0095 §2 deliberately keeps readers out of `tools/` — so neither clause is
   engaged here either, and examining a clause and finding it unmet changes
   nothing about ADR-0017. A hub with a socket is not a precedent for a network,
   and a reader opening a local file is not one either. Nor is that an artefact
   of the first source being the small one: ADR-0095 names the two source
   patterns that survive the hub moving to a box of its own — files synced onto
   it, and co-located fetchers such as `vdirsyncer` whose output the reader
   reads off disk — and in both the network
   is the fetcher's, never the seam's. So §3 stays unspent, and falls to the
   acting tools stance 2 sequences after this leg.
   MCP-shaped clients are welcome here, but as sensors only; actuators stay in
   the later arc. One precondition is already ratified onto this leg's first
   `EXTERNAL` producer: it may not ship without conveying both the reporting
   source's identity and the time that source reported it, since a belief in the
   `ATTESTED` band must not be readable as the user's own word or as our
   inference, and must not be offered our revision time as the source's. Whether
   `Provenance` grows fields for that is a `core` decision made with the producer
   in hand (ADR-0073 §4, §10). The exit test's second half rests on a surface
   nothing offers yet: `ActionPolicy` governs *actions*, not sources, so "you may
   read my calendar" has nowhere to be recorded, and the grant model is its own
   decision (#629), now scheduled as leg 11. *Exit: the assistant knows something true about
   the user's day it was never told, from a source the user granted.*
7. **Memory at volume.** Decided and built (ADR-0110 through ADR-0116; the
   batch record is #729). Consolidation is a chunked scheduler job resuming
   from a durable cursor the store contract carries (ADR-0111, ADR-0114),
   shipped built but unarmed until the write path's embedding call has a
   deadline (#820); the question this leg was expected to raise — whether
   consolidation makes the scheduler's serial, one-at-a-time shape worth
   revisiting — was answered the other way: the scheduler stays serial and
   chunking is the answer (ADR-0111, amending ADR-0083 §7). Demotion is the
   covered-reading rule — a covered reading's absence closes a window, and a
   clock never does (ADR-0110, ADR-0115) — with currency barred from ranking
   (ADR-0112) and retrieval ordered by relevance through a band-scoped read
   bound before the KNN cut (ADR-0113). The re-embedding migration (#425)
   landed earlier as the offline tool taking the hub's own instance lock
   (ADR-0083 §1, §10). Decay *parameters* stay with leg 8's measurement.
   **The leg is about quality, not size** (ADR-0103 §1): what ages is a second
   quantity, never the evidence a belief was built on, and nothing here destroys
   evidence to reclaim space — which leaves ADR-0007 §5's size-caps slice
   deferred where it already was rather than pulling it into this leg.
   *Exit: months of use make retrieval better, not slower — measured in this
   leg, as retrieval latency and k-shortfall against a synthetically aged store.
   The instrument exists and is runnable on demand (#799, from #789); the
   measurements it produced are recorded in #799's report and #729's close-out,
   not as a committed artifact. Ruled met by the operator (2026-08-07, on
   #729): latency's affine ~1.2 µs/record shape is acceptable at realistic
   volumes, and the k-shortfall mechanism — real, but a threshold driven by
   concentrated window-closure whose real-world incidence nobody has measured —
   is deferred behind a named trigger rather than asserted either way: #824
   arms the #457/#411 mitigation when leg 8's telemetry shows a real store
   developing concentrated closure. The "not noisier"
   half is handed to leg 8 as an entry claim, because it needs
   the memory-precision measure leg 8 builds; a claim this leg has no instrument
   for is one it would assert rather than test.*
8. **Minimal evaluation.** Decided and built (ADR-0119, ADR-0120; the batch
   record is #846). A trace is an event **at a seam** that references what it is
   about and never contains it, which is how Tier-2 operational data stays
   Tier 2 under ADR-0004 (ADR-0119); a measure is a **rate over one window of
   that stream**, computed offline by `ai-assistant-measures` while the hub is
   stopped, so the instrument never competes with the process it measures
   (ADR-0120). The three measures are VISION.md's first few — memory precision,
   correction rate, repeated-explanation rate. The trace store is the hub's
   seventh database, and this is also the hub's operational telemetry; a process
   that runs for weeks cannot be debugged by rerunning it. Memory precision is
   also what answers the half of leg 7's exit test leg 7 hands over — whether
   months of use made retrieval noisier — so that claim entered here rather than
   closing there.
   *Exit: "is the user model getting more accurate?" is answered by data, not
   opinion.* **Ruled met by the operator (2026-08-09, on #878)**, on the QA run
   recorded in #862: every ruled behavior had a reachable producer in a live hub,
   and the first data the instrument produced immediately found two ways the
   model was *not* getting more accurate — which is the exit test working rather
   than a qualification on it.

   **Those two findings were decided and fixed before the arc closed, not
   carried.** #863 — a direct restatement never reinforced, so the
   repeated-explanation rate's numerator had no live producer at a direct seam —
   is decided by **ADR-0121**: an agreeing restatement is ruled agreement, not
   conflict. #864 — `learn --kind correction` minting a proposal whose kind hid
   its target from the kind-scoped conflict probe, leaving the wrong belief
   standing — is decided by **ADR-0122**: a correction's record type is resolved
   from its target, not declared by its caller. Both ADRs and both
   implementations merged 2026-08-09 (#865), so the arc that follows starts from
   the fixed policy rather than measuring around it.

   **The residual is that the measures have not yet been read over a life.** The
   instrument answers, but the window it has answered over is a fourteen-minute
   scratch run driven deliberately by an operator. #829's entry ruling owns what
   comes next and stays an **operating act rather than a leg**: the measurement
   window opens with consolidation **unarmed** so a precision/latency baseline
   accumulates first, and consolidation then arms **mid-window as a dated
   intervention**. That ordering is not fussiness — the first arming on a real
   store is a one-shot natural experiment, because consolidation writes durably
   and unarming later restores no control. #865's close-out (2026-08-09)
   sequences the window's opening immediately behind the fix batch. The boundary
   issues those lanes filed rather than absorbed (#868–#873, #876, #877) stay in
   the tracker; #876 and #868 are together why the repeated-explanation rate is
   read as a lower bound rather than a rate.

**The arc closed here.** Every leg met its exit test, the last of them on
2026-08-09. Their residuals are named in the entries above and live in the
tracker and the ADR ledger rather than in a status line here. What the arc did
not build is any reason for the loop to keep running once the operator stops
driving it — which is what the next one is for.

## The inhabitation arc, in order — legs 9–12

The direction is the operator's ruling of 2026-08-09, recorded in #879. The
rules are the accumulation arc's, unchanged: each leg decomposes into ADR-backed
slices when it is dispatched, contract first, and a gap closes when a user can
exercise the capability rather than when a test can. Exit tests below are this
document's proposals in the usual way — the operator rules them met, as on legs
7 and 8 — except leg 9's, which is the ruling's own.

**The theme is inhabitation.** The accumulation machinery exists and is now
measured; what it lacks is a life to accumulate from. Every leg here buys reach,
duty cycle, or a reason to open the assistant tomorrow, and the arc is ordered so
the cheapest of those comes first.

9. **Reach and daily use.** The leg that makes the hub something the owner lives
   in rather than something they drive. Four things, in this order:

   - **Backup and restore, as the first slice and not a mid-leg one.** Daily
     accumulation is about to happen on one laptop holding the only copy of the
     store; that is the plan's single fragile spot, and it is fragile from the
     day accumulation starts rather than from the day the leg ends. It is also
     the honest test of VISION.md's portable context-graph claim, which nothing
     has yet had to satisfy.
   - **The hop decision.** A spoke off the device moves user data off the
     device, which ADR-0017 §1 governs and which no wire format can
     pre-authorise (ADR-0084 §1, §11). The leading candidate is an **overlay
     network** keeping the API off the public internet — Tailscale specifically,
     whose device identity is also a candidate first occupant of the credential
     slot ADR-0084 reserved and the loopback transport carries nothing in. A
     leading candidate is not the decision: the ADR is this leg's first contract
     question.
   - **A remote listener beside the loopback socket**, not instead of it. The
     three expensive retrofits ADR-0084 bought in advance and leg 5 shipped — a
     versioned connect handshake, a defined place for a credential, a client
     stateless by decision — are what make this additive rather than a rewrite.
   - **A live calendar.** Leg 6's `Reader` gets a source kept fresh by a
     co-located `vdirsyncer` — the stronger of the two source patterns ADR-0095
     names, and one where the network is the fetcher's and never the seam's, so
     ADR-0017 §3 stays unspent here for exactly the reason it did in leg 6.

   *Exit: the assistant is in daily use — ordinary conversations on ordinary
   days, reachable from somewhere other than the hub's own machine, and losing
   the laptop does not lose the model.*

   **What the hop feeds once it lands**, inherited from the later-arc entry this
   leg replaces: a context facet (device is a VISION §Principle-4 input), a
   permission input (which devices may approve consequential actions —
   ADR-0004's deferred catalogue gains a sibling), and the audit trail's
   "approved from where".

   **What is portable across a process — and would be across a device — is the
   durable execution and audit state, not the handle.** ADR-0052 §1 enumerates
   parked executions and re-mints a continuation from durable state, and chose
   that over encoding durable identity into the token deliberately. The
   continuation token stays **process-scoped**: it names an entry in one engine's
   private table (ADR-0042's revisit-if clause, #242), and the hub will not
   persist that table, because ADR-0052 §1 already provides the durable path
   (ADR-0083 §14.7). So a token minted by a previous process life yields one
   specific typed refusal — an unknown continuation, never a denial and never an
   expiry, both of which would report something no policy and no deadline decided
   — and the remedy is `pending_confirmations()` (ADR-0084 §7).
10. **Proactivity.** The push seam, `NotificationCandidate`, and the interruption
    policy — the one proposal artifact of the propose/dispose principle still
    unbuilt. Of its two structural requirements, leg 5 met one: something is
    awake to notice, with a scheduler to notice on (ADR-0083 §7). Leg 9 meets the
    other, because a delivery channel is a push seam over a hop, and a hub that
    notices and cannot reach the user has produced a candidate and delivered
    nothing. The policy is the hard half: what earns an interruption is a
    judgement the propose/dispose chassis has never had to make, because every
    other proposal it gates waits patiently to be read.
    *Exit: the assistant tells the user something they did not ask for and were
    glad to be told, and the user can tune what reaches them.*
11. **Sensor breadth, and the grant model.** More read-only sources — and the
    thing that should have governed the first one. **#629** records the gap
    exactly: a reader may be enabled with no grant at all, so VISION.md's
    "granted, scoped, and revocable" is unmet by construction, and ADR-0093 §7
    already rules that configuration is not a grant and no surface may present it
    as one. `ActionPolicy` governs *actions*, not sources, so "you may read my
    calendar" still has nowhere to be recorded. Leg 6 named this precondition and
    could not close it against one source; breadth is what makes leaving it open
    indefensible, which is why the two are one leg rather than two. ADR-0094 §10
    expects this decision and #441's release ladder to be one decision rather
    than two.
    *Exit: the user can see every source the assistant reads, grant and revoke
    each one, and a revoked source stops reaching the model.*
12. **Actuators, in bulk.** MCP-shaped tool breadth, behind the decisions it
    forces: ranking among capable tools (#241 — a second capable tool stalls the
    step by design, ADR-0037 §1), parameter-schema enforcement (ADR-0029 §7),
    and the deferred egress cluster — ADR-0017 §3's fourteen conditions on
    designating the `tools/` seam, which stance 2 has been sequencing here since
    this document's reorientation and which nothing earlier spends. This is also
    where the permission machinery finally earns its depth: ADR-0048's first
    local tools are read-only and reversible, so the irreversibility and
    disclosure floors have had no live case.
    *Exit: the assistant completes a task that changes something in the world,
    and the user was asked exactly once, at the moment it mattered.*

### Voice: parked, with a slot after leg 10

Ruled 2026-08-09 (#879): voice is **parked, slotted after leg 10, and explicitly
not scheduled** — a slot is not a plan, and the ruling is that it is not worth
the energy now. The design is not what is missing. ADR-0094 waits ready, having
already unified client, sensor and actuator as capability profiles of one spoke,
with the band ceiling and the release gate an always-listening edge needs; its
vocabulary is ratified and unspent.

**What opening the slot costs is named now rather than discovered then.** An
ambient capture producer walks into a ratified pair. ADR-0075 §2 lists "the
buffered ambient capture #441 sketches" among the producers that inherit its
capture exemption from nothing, and *reserves* the argument rather than granting
it; ADR-0093 §4 then forbids a `Reader` proposing an `EpisodicMemory` at all,
an ingested episode having neither a gate it can survive nor an exemption it can
claim. ADR-0094 §10 states the shape of that collision and deliberately does not
grant it either. Whoever opens the slot pays for that decision first, and saying
so here is what keeps the parking honest rather than merely quiet.

### The gate between leg 10 and leg 11

Ruled 2026-08-09 (#879): **if memory precision is flat, or the correction rate is
not falling, through legs 9 and 10, then legs 11 and 12 pause and the arc detours
into learning quality.**

This is the first commitment on this roadmap that a measurement can overrule, and
it is what leg 8 was built to make possible. Breadth is worth buying only if the
accumulation underneath it is improving; if it is not, more sources and more
actions add surface to a model that is not learning, which is the failure mode
"deepen before broaden" names in the abstract and this gate names in figures. The
measures are read as ADR-0120 defines them — rates over one window of the trace
stream, offline — and the window is the one #829 opens.

### The dedicated box is an operating act, not a leg

Ruled 2026-08-09 (#879). The hub will eventually run on an always-on machine of
its own. A VPS is **ruled out**: a host that roots the store is the maximal
ADR-0017 §1 decision, and it sits against the trust thesis rather than merely
costing something.

- No hardware exists, and **nothing in legs 9–12 hard-depends on it.** The
  remote path is testable as two processes on one machine. The box buys duty
  cycle — always-on accumulation, overnight proactivity — not capability, which
  is why it is not sequenced as a leg.
- The migration itself is a data-directory copy under ADR-0083's layout, run
  whenever hardware exists.
- **One constraint, and it is a hard one: it must not land mid-#829-window.**
  The consolidation arming is a one-shot natural experiment, and a migration
  inside the window confounds it. Migrate before the window opens or after it
  closes.
- Until then daily accumulation happens on the laptop hub — which is why leg 9
  fronts backup and restore.

It is done when the hub runs supervised on the dedicated machine with the store
carried over, and this document records the migration as complete. #879 tracks
it until then.

## The later arc, in order

Named so near-term slices leave room for them; none is scheduled, and each
still needs decomposing into ADR-backed slices. Three entries left this list for
the inhabitation arc — remote spokes into leg 9, proactivity into leg 10,
actuators into leg 12 — and what each of them carried is stated there rather
than duplicated here.

- **An engagement surface.** The accumulation flywheel needs daily use, and
  nothing on this roadmap yet makes the assistant compelling daily. Leg 9's exit
  test *asks* for daily use; it does not supply a reason for it, which is why
  this entry stays here rather than moving with the others. It remains
  deliberately undesigned, named so its absence is a known debt of the plan
  rather than an oversight.
- **Commitment ledger, full evaluation harness, portable context graph.**

## Parked

- **The design-debt plans**, queued before this reorientation and parked behind
  the accumulation legs. Two of the three have since been decided on their own:
  record mutability by ADR-0068 (immutability is a property of the types, closing
  #41), and ADR governance by ADR-0070 and ADR-0082 (when a decision may be
  amended in place, when it must be superseded, and where the record goes). What
  remains of the enforcement-scope plan is tracker work, and leg 3 having landed,
  the revisit this entry deferred is due.
- **The test-hardening issue backlog** stays in the tracker and is worked
  opportunistically; none of it is scheduled here. The tracker, not this
  document, owns that list (ADR-0015/0019).
- **Ranking, parameter schemas, networked actuators** — parked *with intent*
  behind leg 12 above, not forgotten: they are contract decisions that become
  due the moment actuators do.

## Gap register

Where each VISION.md promise stands against this plan — stated as pointers to
the legs that close them, so the claim decays into the tracker and the ADR
ledger rather than into this document.

| VISION promise | What closes the gap |
| --- | --- |
| Understood — a persistent user model | Legs 1–3 (the bands, capture, the observer) |
| In Control — inspect, correct, restrict, delete | Leg 1 (inspection surface over ADR-0007's contract); *restrict* waits on leg 11's grant model (#629); `export` still has no interface (ADR-0073 §10) |
| More Capable Over Time | Explicit correction: ADR-0009/0022; legs 3–4 and 7 extend it to observation; leg 8 is what measures whether it is working, and the arc gate before leg 11 is what acts on the answer |
| Context determines usefulness | Leg 6 feeds facets ADR-0008 anticipated; device context waits on leg 9's hop |
| Supported — acts across tools | Leg 12 (actuators, in bulk); deliberately last |
| Proactivity that earns its place | Leg 10; the hub it required is leg 5 and the delivery channel is leg 9's push seam, so what remains is the interruption policy |
| Free to choose models | ADR-0002/0011/0013/0061/0062; no leg needed |
| Observability and evaluation | Leg 8 (ADR-0119/0120), ruled met 2026-08-09; the full harness stays in the later arc |
