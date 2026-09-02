# Roadmap — the live plan

**Status: working guidance, not a ratified decision.** This document is the
tactical companion to [`VISION.md`](../VISION.md): the *why* and *what* live
there; this covers *how* and *in what order*. Nothing here is binding. Every
artifact that crosses a subsystem boundary (a new `core` type or a Protocol
change) is ratified in its own ADR **before** it is implemented — see
`docs/adr/` and the rules in `CLAUDE.md`. If this roadmap and an ADR disagree,
the ADR wins.

**This is a plan, not a status board.** Work is organised as standing **tracks**
(#1226 §2), and each track's live state — which milestone is open, what closed,
which batch is running — lives on its own GitHub issue. The sections below carry
the *shape* of each track: its purpose, its milestones and their exit tests, and
what it defers. Where a pointer here and the issue it points at disagree, the
issue is newer and wins. History does not live here either: git holds this
file's, and the tracker and the ADR ledger hold the work's (ADR-0019).

**The narrative is bound by that same rule, not just the milestone entries.**
Do not write the state of the code into a sentence here — what is built, what
is not, what a subsystem does today — and dating it is not a way round that. A
track's motivation is its durable *argument* plus a pointer at whatever holds
the state: a ratified ADR, which is dated and append-only (ADR-0019 §4), or the
track's issue, which is live and mutable and governed by the precedence rule
above. Neither home is a sentence in this file. An observation written here
loses the date that made it true, and the precedence rule never fires on it
because it does not read as a pointer that could disagree with anything. This
paragraph is a rule for what gets written, not a certificate that nothing here
breaches it — a document that audited its own contents would be making exactly
the kind of claim it forbids (#1568).

## Design stances

These are premises this roadmap sets, not measurements (ADR-0019 §3). Each
becomes binding only when an ADR ratifies the slice that implements it.

1. **Passive accumulation is the primary mechanism; explicit correction is the
   steering wheel.** The assistant observes interactions and ingested sources
   and *proposes* beliefs with `OBSERVED`/`INFERRED` provenance, sub-1.0
   confidence, and evidence; deterministic policy disposes; the user inspects,
   corrects, and thereby supersedes (ADR-0005/0021/0037, ADR-0077). A belief the
   user never dictated, visible to them and correctable by them, is worth more
   than breadth.
2. **Sensors before actuators, and anything that acts pays at one designated
   seam.** Read-only ingestion carries no irreversibility, so it comes first
   (ADR-0093/0095). Acting on the world is the expensive half, and the egress
   decision ADR-0017 §3 held open is now spent where it was always expected to
   be: ADR-0154 designates the `tools/` egress seam and attests its conditions
   in code, ADR-0148 fixes the confirm rule at it, and ADR-0151/0152 give the
   connection and binding surfaces around it.
3. **Hub and spokes.** One resident service — the hub — owns all state and
   intelligence; every interface is a stateless client of its API, so
   conversations, memory and identity are device-agnostic (ADR-0083/0084). A
   subsequent interface is a client of that API or it is not an interface. Two
   consequences are standing rules rather than advice: the hub never dials a
   spoke (ADR-0124 §10), and a non-loopback hop is user data leaving the device,
   so it engages ADR-0017 §1 and is not reached by swapping an address family
   (ADR-0084 §1/§11, decided by ADR-0124).
4. **Deepen before broaden.** VISION.md's answer to its own scope risk governs:
   narrow, complete loops over shallow breadth.
5. **Design for the end state.** Assume the sensing works, and make the model
   right for that world; "not buildable today" is a scoping answer, not a design
   objection. The counterweight is honesty about evidence — say when a
   discussion has outrun its data rather than deciding on it anyway.
6. **The dedicated box is an operating act, not a milestone** (#879). The hub
   will eventually run on an always-on machine of its own. A **VPS is ruled
   out**: a host that roots the store is the maximal ADR-0017 §1 decision, and
   it sits against the trust thesis rather than merely costing something. No
   track hard-depends on the box — the remote path is testable as two processes
   on one machine, so the box buys duty cycle (always-on accumulation, overnight
   proactivity), not capability. The migration is a data-directory copy under
   ADR-0083's layout, and it has one hard constraint: **it must not land
   mid-#829-window**, because the consolidation arming is a one-shot natural
   experiment a migration inside the window would confound. #879 tracks it until
   the hub runs supervised on that machine with the store carried over.
7. **Ambient capture walks into a ratified pair, and pays for it first.** The
   voice surface's shape is `track:voice` below and its state is #1318; what
   this stance holds is the price of the ambient rung. The design is not what is
   missing: ADR-0094 already unifies client, sensor and actuator as capability
   profiles of one spoke, with the band ceiling and the release gate an
   always-listening edge needs. What that rung costs is named here rather than
   discovered there. ADR-0075 §2 *reserves* rather than grants the capture
   exemption for buffered ambient capture; ADR-0093 §4 forbids a `Reader`
   proposing an `EpisodicMemory` at all; ADR-0094 §10 states the collision and
   grants nothing either. Whoever opens that milestone pays for the decision
   first.

## Concurrency

One rule, and it is global (#1226 §3). Lanes take clones and Codex review quota
**first-come-first-served across all tracks** — there is no main, priority or
background track, and no per-track lane budget. **A lane never edits a subsystem
in which another track has a lane open**: a finding there is filed to the track
that holds it rather than fixed across the fence, because nothing mechanical
detects two lanes colliding (`CONTRIBUTING.md` → "Coordinating parallel work").
Spend is one pool; any ceiling on it is a global operating fact the owner sets,
not a roadmap rule.

## `track:web-client` — the browser client

Live record: **#1230** — which milestones have closed, and the exit ruling
that closed each, are recorded there.

**Purpose:** a spoke that enrols as a device and exposes the hub to a browser —
gateway, chat, notifications, control surfaces. Milestones are ordered by
**dependency only**, and each closes on a QA-driven exit ruling: a QA run drives
the milestone's ruled behaviors end-to-end through a live hub
(`.claude/skills/qa-milestone`), recorded as a `qa` issue, and the owner rules the exit
on #1230. An exit test is stated in product terms — a gap closes when a user can
exercise the capability, not when a test can.

- **13 — the gateway.** Holds open the wire seat ADR-0084 §3 / ADR-0094 §2: a
  spoke process that enrols as a device, speaks the framed wire to the hub
  (loopback or overlay), and exposes WebSocket/HTTP to the browser; web-session
  identity and expiry, because a browser is not a Tailscale device.
  *Exit: an `ask` round-trips from a browser on another Tailscale device, and
  hub-down is a legible fault in the browser.*
- **14 — conversation and notifications.** Streaming chat; conversation list,
  resume and forget; the delivery connection held open (`next_notification`,
  ADR-0131) — the first push consumer.
  *Exit: a conversation and a pushed notification, end to end, on a phone.*
- **15 — control surfaces.** Sources and grants (grant, amend, revoke); beliefs,
  questions, answer, observe, forget; connections plus the CONFIRM prompt for
  actuator sends.
  *Exit: the leg-11 and leg-12 exit tests (#1081, #1159) re-run entirely from
  the browser.*
- **16 — polish and first-run.** Reconnect, error states, session persistence,
  mobile layout, install and first-run docs.
  *Exit: a stranger brings hub, gateway and browser up on a fresh machine from
  the docs alone.*

**Deferred — stated, not scheduled:**

- The operator/admin read surface (status, uptime, jobs, store health, delivery
  slots, connection log), and the remote-safe vs hub-local split of admin acts.
- The hosted/billing plane: a separate service outside the hub's trust boundary,
  needing its own trust ADR. Hosting is currently ruled against for the owner
  (stance 6).
- Voice, which is `track:voice`'s (below, #1318): its first rung rides this
  track's gateway and browser surface rather than queuing behind the track.

## `track:memory` — learning and memory quality

Live record: **#1231**. Pre-registration: **#1029**.

**Purpose:** what the assistant remembers, how it retrieves and reconciles it,
and how that is measured — the learning path and the evaluation harness
together. **Exits are pre-registered benchmark targets** rather than exit tests:
LoCoMo full and the LongMemEval-S slice, each arm pre-registered on #1029 as a
hypothesis and landing there as a hypothesis-vs-outcome addendum. **This track
does not close.**

Work proceeds in **pilots**. Each pilot is a `batch` issue — the probes, the
ADRs, the lanes, the run and the error anatomy — and its results land as an
addendum on #1029; a run aborted on credit is recorded as void rather than
quietly redone. **#1231 names whichever pilot is open**, the baseline it is
measured against, and what the next one is shaped by.

The standing questions the track carries — forgetting, which the complete-intake
ruling names as the destination of the selectivity it removed from intake;
decomposition and iterative retrieval; harness fidelity and grading; the
policy and reconciler cluster; the intake surface — are enumerated on #1231,
which is the census. Issues are labeled `track:memory` as they are touched.

## `track:conversation` — the assistant answers

Live record: **#1312** — which milestones have closed, and the exit ruling
that closed each, are recorded there.

**Purpose:** the hub-side conversational engine — the pipeline's terminal step.
A reply is not a tool, so it does not belong behind "tools are deferred to MCP"
and `tools/` is not on its path: it travels back on the wire the `ask` arrived
on, the shape ADR-0131 gave notifications ("an answer the device asked for").
Where that wire is the hub's remote transport the return is ADR-0124 §1's third
egress boundary, ratified there and traced against all three in ADR-0170. This
track owns making the assistant *speak*: composing answers from plan + retrieved
memory + context, streaming them, and routing intents to typed operations. It
is hub-side work with **no dependency on `track:web-client`'s gateway**; the
CLI exercises every exit. `track:web-client` milestone 14 (streaming chat in
the browser) consumes this track's output. Milestones are ordered by
**dependency only**, and each closes on a QA-driven exit ruling: a QA run
(`.claude/skills/qa-milestone`) recorded as a `qa` issue, then the owner's
ruling recorded on #1312.

- **17 — the assistant answers.** An ADR ruling that a reply is not a tool: the
  pipeline's terminal step composes a natural-language answer (model + memory +
  context) and returns it as the ask's response, distinct from the tool seam
  (ADR-0154) and related to ADR-0131's answer-shaped delivery. Then the
  implementation lane (after the ADR merges, one lane one PR), then QA.
  *Exit: the owner asks "what do you know about me?" from an enrolled device and
  receives a conversational answer that draws on accumulated memory.*
  The ADR lane carries two delegated calls, both recorded on #1312: whether any
  `core` type changes, and how a plan's non-answerable steps — the ones that
  need real tools — degrade into the answer honestly.
- **18 — streaming and the conversation surface.** The hub-side half of
  streaming (chunked reply frames on the wire), conversation resume carrying
  context; what `track:web-client` milestone 14 needs from the hub, built here.
  *Exit: a streamed answer over the wire, resumed mid-conversation, from the
  CLI.*
- **26 — hub-owned intent routing.** `ask` → typed operation: a routing stage
  ahead of planning resolves one utterance onto a closed subset of the engine's
  own operations, one-directional — a typed operation is never re-read — with its
  own confirm rule for the operations that write, distinct from the tool seam
  (ADR-0154, ADR-0148). Conceptually moved here from `track:web-client`'s
  deferred list (#1230). The ADR lands first (golden rule 5), then the
  implementation lanes, then QA.
  *Exit: from an enrolled device, the owner says "forget that I …" in an `ask`,
  is shown what will be forgotten, confirms, and the belief is gone; "what have
  you read lately?" answers from the read trail with no confirmation; and a
  routed operation's result never reaches the model.*

**Deferred — stated, not scheduled:**

- **Multi-step plan driving.** At most a plan's first step is driven (ADR-0170
  §5, #242), so an ask needing two acts gets one. It waits on evidence that the
  one-act limit is a limit anyone hits.
- The **engagement surface** the Gap register names as on-no-track debt. This
  track is its natural eventual home, but it stays undesigned until ruled.

## `track:voice` — the voice surface

Live record: **#1318** — which milestones have closed, and the exit ruling
that closed each, are recorded there.

**Purpose:** talking to the assistant, it talking back, and the ambient-capture
ladder, under the direction ADR-0094 ratifies — client, sensor and actuator are
capability profiles of one spoke, and the rules that unification carries are its
§3 (nothing leaves the edge the spoke has not released), §5 (the hub decides the
band a submission produces, and every spoke has a ceiling it may not submit
above), §6 (a spoke decides *whether* to send, never *what a submission means*)
and §7 (a spoke submits the source material rather than a lossy,
model-dependent derivation of it — audio, not a transcript). The rungs follow
the owner's trigger ladder — talk to it, proactive speech, buffered explicit
capture, suggested capture, autonomous capture — where each rung earns the next,
which is why the ladder is an ordering principle and not a commitment to reach
its top. Milestones are ordered by **dependency only**, and each closes on a
QA-driven exit ruling: a QA run
(`.claude/skills/qa-milestone`) recorded as a `qa` issue, then the owner's
ruling recorded on #1318.

**Two rulings recorded at the track's opening**, both on #1318. **Rung 1 rides
the browser:** milestone 19 is a web-client feature — mic capture and playback
over the gateway — rather than a native spoke, which arrives at 21 where the
rolling buffer needs it; this refines stance 7 below into *riding*
`track:web-client`'s surface rather than merely queuing behind that track.
**The disclosure decision #665 asks for is the track's first lane:** #665 is
the issue holding that spoken read-back is a disclosure surface owed its own
ADR. That ADR is conduct rather than protocol, and #665's own terms require it
ratified before the first spoke that speaks, so authoring and ratifying it is
the lane this track opens with and it waits on nothing else here.

- **19 — talk to it.** Push-to-talk in the browser: mic capture over the
  gateway, hub-side STT (a model in `models/` behind ADR-0013's router;
  inference in worker processes, never the hub process), the composed reply from
  `track:conversation`, spoken back via TTS. Attribution: an explicit press on
  an authenticated web session is the principal — no speaker ID at this rung.
  Disclosure under the ADR #665 asks for, which is why that ADR is the first
  lane above. It depends on `track:conversation` 17–18 (composed and streamed
  answers), `track:web-client` 13–14 (the gateway and the chat surface), and on
  that ADR being ratified first.
  *Exit: the owner holds push-to-talk in a browser on another device, asks aloud
  about their own life, and hears an answer drawing on accumulated memory; a
  content class ruled unspeakable is deflected ("details on your phone"), not
  read aloud.*
- **20 — proactive speech.** Voice as a delivery surface: a pushed notification
  (ADR-0131's answer-shaped delivery) rendered as speech. The disclosure rules
  bite hardest here — an unprompted utterance into a room nobody addressed, so
  occupancy-unknown is the default posture and not the edge case, which ADR-0199
  §4 now rules outright rather than leaving to this milestone. **ADR-0206 is the
  mechanism decision**: the polling device asks for a rendering on
  `next_notification`, the hub produces it inside the call that answers the poll
  and nowhere else, one notification triple is placed speakable on the whole of
  the recorded origin ADR-0199 §3 requires, a withheld notification arrives
  unspoken with nothing audible marking it, and "idle" is a fact about the device
  rather than about the room.
  *Exit: a notification arrives as speech on an idle device, and a class the
  owner ruled unspeakable deflects to an authenticated surface instead.*
- **21 — the native spoke and buffered explicit capture.** The always-listening
  ephemeral rolling buffer (~30s, continuously destroyed) plus "capture that": a
  native voice spoke, because a browser tab can neither hold a mic open nor
  honor buffer discipline; audio-not-transcript across the wire; a capture lands
  `ATTESTED` with the spoke as `reported_by` and capture-triggered provenance.
  ADR-0094 §10 defers the spoke surface until a second spoke exists, and
  `track:web-client`'s gateway is that second spoke, so that surface is a
  prerequisite of this milestone rather than part of it. **What this milestone
  rules before it builds anything**, none of it settled here: the ambient
  collision (stance 7); what may cause a release and the revocable grant model
  beside it, which ADR-0094 §10 defers to the first capture producer and this
  is it — release is not authorisation (§3), so who may say "capture that" in a
  room is a permission question, and it arrives with the `undetermined`
  attribution channel the deferred list below returns here at latest (#691);
  the remote hop, since room audio to a non-local hub is ADR-0017 §1's question
  and transcript-only does not rescue it; the custody terms of ADR-0094 §7–§8 —
  a spoke may not destroy the material a submission was derived from while that
  submission is unresolved, the hub retains it only for a bounded verification
  window, raw source material is never an episode, and the figures (the
  window's, the buffer's, and the custody handoff §8 leaves undecided) are named
  by this milestone's deciding ADR rather than by ADR-0094; and the mixed-origin
  seam, because a captured room carries a third party's speech, which ADR-0098
  §1 rules external content where the owner's own utterance is not — the
  mechanism for a record holding both, and the gate consequence behind it, are
  ADR-0098 §12's first deferral (ADR-0163 §8).
  *Exit: the owner says "capture that"; the preceding ~30s lands as an
  inspectable episode at the hub with who-triggered-retention provenance; and
  the buffer's non-retention outside a capture is demonstrable.*
- **22 — suggested capture.** The classifier proposes, the owner disposes: a
  review queue that expires. Milestone 21's explicit captures are the training
  labels, and the classifier is itself personalized — the moat applies to the
  sensing layer.
  *Exit: the spoke proposes a capture the owner did not trigger; confirming
  keeps it, and an unreviewed proposal expires without a trace.*

**Deferred — stated, not scheduled:**

- **Autonomous salience capture** — the ladder's last rung, and each rung earns
  the next (ADR-0094's direction).
- **Per-utterance speaker identification** — the `undetermined` attribution
  channel (#691). Milestones 19–20 dodge it by construction (push-to-talk on an
  authenticated session); milestone 21's buffer records rooms rather than
  sessions, so it returns there at latest.
- **Multi-person household disclosure** — the matched speaker asking about
  another member's data. #665 names it and defers it, and the first lane defers
  it on the same terms.
- **Wake-word.** The direction is explicitly not wake-word-only; if one ever
  arrives it is detection at the edge under ADR-0094 §6, whose rule is that a
  detector's output may not be meaning, and not a new architecture.

**Concurrency.** Rung 1 rides `track:web-client`'s gateway and browser surface,
so a lane there is sequenced against that track's lanes rather than run beside
them (#1226 §3, Concurrency above); the native spoke from milestone 21 is this
track's own ground. Which lanes that sequencing has bound is on #1318 and #1230.
Clones and review quota are one pool, under Concurrency above.

## `track:world` — the assistant sees and acts on the world

Live record: **#1427** — which milestones have closed, and the exit ruling
that closed each, are recorded there.

**Purpose:** the assistant sees and acts on the world — the `readers/` (sensor)
and `tools/` (actuator) seams, hub-side and CLI-driven. The browser client
consumes what lands here (`track:web-client`), voice keeps spoke-as-sensor
(ADR-0094), and what ingested content *becomes* stays with `track:memory`. The
adversary is already named and mostly answered — ADR-0098 (the injection class,
escaping, never-authority, ceilings, detection-is-not-a-gate), ADR-0106 (taint
through consolidation), ADR-0148/0154 (an egress call authorised as one whole,
at a designated seam). What the lineage and standing-grant gates read is a
**recorded origin**, in two representations: the externality a proposal's
`Provenance` carries, at the lineage gate in `MemoryPolicy` (ADR-0106 §6), and
"a fact the request carries, never an inference about how a model produced it"
(ADR-0154 §4, item (ii)), at the standing-grant gate on the call itself.
Milestone 24's exit names it and the deferred list below waits on it, which is
why it takes this track's first milestone. Milestones are ordered by
**dependency only**, and each closes on a QA-driven exit ruling recorded on
#1427. `track:voice` above holds milestones 19–22; this track starts at 23.

- **23 — the origin seam.** Origin recorded at ingestion and carried unchanged
  through proposal, consolidation, facet assembly and tool-argument
  construction; the lineage gate at `MemoryPolicy` and at the permission check;
  origin per field on the CONFIRM card (CLI and browser). It is `core` surface,
  so the contract ADR lands first (golden rule 5) and the Protocol/type triad
  follows with its primary consumer (ADR-0137 §2). Carries #641 (the
  reader-side threat model) alongside; #668 closes against it.
  *Exit (two arms, pre-registered): a hostile instruction inside ingested
  content **(a)** cannot cause a send — the egress is parked and the CONFIRM
  card shows its origin on the offending field; **(b)** cannot become a belief
  that justifies a later send without that origin being visible at the ruling
  point. Measured: ASR-at-gate, ASR-past-gate = 0, poison rate at k=1/k=10.*
- **24 — the record.** What the world did to the assistant and what the
  assistant did to the world, readable: the read-side audit ledger (#1017,
  ADR-0097 §12's deferral), authorised cloud egress in the audit trail (#747),
  band precedence revisited against a real reader (#663).
  *Exit: every read of a source and every egress is reconstructible from the
  audit trail alone, origin included.*
- **25 — closed by construction.** Egress through an injected transport
  capability rather than import contracts (#85); an approved-recipient policy
  beyond the tier ceiling (#68); a budget ceiling on what the world may cost.
  *Exit: a tool that tries to reach the world outside the seam cannot, and the
  test that proves it is the fake transport, not a grep.*

**Deferred — stated, not scheduled:**

- **Breadth.** The second reader, further actuators, the reader-agent split
  (trigger: a reader that needs its own model call), a two-phase planner, any
  classifier-based defence. ADR-0098's own triggers fire with the second reader;
  which of them have fired, and what the milestone-23 exit ruling released, is on
  #1427.

**Concurrency.** The subsystems this track works in — `core/`, `memory/`,
`permissions/`, `planning/`, `readers/` and `tools/` — are not
`track:web-client`'s, so the two run beside each other under Concurrency above,
with one seam where they meet: the CONFIRM card's origin rendering touches the
browser assets and the CLI renderer, so a lane there is sequenced after that
track's client lanes rather than beside them (#1226 §3). Which lanes that
sequencing has bound is on #1427 and #1230. Clones and review quota are one
pool, under Concurrency above.

## `track:planning` — the planner gets sight

Live record: **#1908** — which milestones have closed, and the exit ruling
that closed each, are recorded there.

**Purpose:** the planner gets sight. A retrieval that fires on the request's
wording before anything has reasoned about it can reach only what that wording
reaches, and a plan made once cannot use what its own first step found — the
order #1844 records, and the plan-once, drive-at-most-one-step shape ADR-0014
and ADR-0037 rule. This track earns, rung by rung, a loop in which the planner
may look again, revise, and reach outward. Milestones are ordered by
**dependency only** and numbered within the track (#1908) rather than
continuing the sequence the tracks above share; each closes on an exit ruling
recorded on #1908.

**The charter caution, recorded at the track's opening** and carried by every
milestone: the loop is not justified by memory-benchmark numbers. Its value is
*task capability* — multi-step tool work, proactive tasks with no backstop and
no deadline (#838), and porch-shaped questions (#1874) that are a structured
read followed by a composed story — so **exits on this track are task-shaped,
not retrieval-shaped**. The replay that priced milestone 1's envelope, and what
it found, are on #1844 rather than here.

**Four invariants every milestone inherits**, recorded on #1908:

- **One envelope, one shape.** The planner emits a request beside its plan; the
  loop services it; what returns is **records carrying provenance, never
  payloads**, so the disclosure filter, the external mark (ADR-0223), the policy
  gate and citations apply unchanged. Later milestones add *kinds* to a closed
  enumeration, on the pattern ADR-0221 §5 sets for its own — no later lane adds
  a case without the ADR that decides it — never a new seam.
- **The namer rule.** The namer may be data, or the user, or the model pointing
  outward — never the model pointing inward. The planner names a label it was
  shown or a structure the system stamped; labels resolve in code to records the
  loop chose; no record id reaches the model and none is accepted from it
  (ADR-0208 §1's ground).
- **One budget, one bound, one audit.** Reads, records and time are accounted in
  one place per turn, and what was asked, what came back and what was dropped is
  recorded. That audit is also the trigger's measuring instrument.
- **The trigger is first-class.** The binding constraint is the planner judging
  that its supply did not suffice, so every milestone that adds a read states
  how its trigger is measured per turn from the first deploy.

**The milestones**, each with the exit that closes it:

- **1 — the sighted envelope.** One inward read, serviced once before compose,
  in two kinds built together rather than sequenced: a **sighted query** (the
  planner names a query; the loop runs `assemble_by_band` and appends — #1732's
  instance) and a **citation hop** (the planner names a belief it can see; the
  loop follows that record's own `Provenance.evidence`). The trigger is judged
  sufficiency (#838's middle layer), defined so that every turn records what its
  precision and recall are computed from. Outward fetch is named and deferred,
  and the adjacent ground is named rather than half-decided: structured keys
  (#1874), hybrid search (ADR-0006 §5), the archive fetch (ADR-0225 §12). It
  changes the planner seam, so the contract ADR lands alone first and the
  implementation follows (golden rule 5): it is the planner-requested second
  retrieval ADR-0208 §8 defers to #1732 by name, and §1's one-site clause is not
  read as prejudging it in either direction. The batch is #1909.
  *Exit: a cross-conversation reply-vocabulary question ("which lender did you
  recommend?") answers through the hop; the trigger's precision and recall are
  on the record; and a turn whose supply sufficed pays no extra read.*
- **2 — the plan becomes revisable.** A read that changes what is known may
  change the plan: an iteration bound, and a per-surface deadline, because a
  voice turn cannot afford three round trips. It partially supersedes the
  plan-once shape of ADR-0014/ADR-0037 — the largest single decision on the
  track — and admits inward kinds only.
  *Exit: a two-step task whose second step depends on what the first found
  completes without the user re-asking; the bound is demonstrably hit, and the
  reply degrades legibly when it is.*
- **3 — the outward fetch.** The planner names a source outside the store.
  **Local files first**, because a steered loop that can only read the owner's
  disk has no channel out; then web search and fetch under the egress seam's
  attested conditions (ADR-0154), with the externality stamp (ADR-0223) as the
  control, so a tainted conversation asks first. Servicing is the envelope plus
  a turn-time reader minting provenance-stamped records — URL, fetched-at,
  external mark, `ATTESTED` band — and not a tool step, because a tool result
  has no provenance to attribute (ADR-0170 §5a). This milestone decides whether
  fetched content persists; the leaning recorded on #1908 is retention by
  address in the source archive (#1907).
  *Exit: "summarise the PDF I saved yesterday" answers from disk; a search
  result is cited as a record, and that conversation's egress asks first
  thereafter.*
- **4 — the planner chooses how to read.** Envelope kinds carrying structure —
  a time window, participants, topics, the person it is about — mapped onto
  `MemoryStore.search` filters over fields the records already carry (#1874,
  whose Protocol triad is `track:memory`'s), and lexical or hybrid search over
  beliefs (ADR-0006 §5, open since; ADR-0225 §7 built the predicate for
  transcripts). The boundary is that this track adds kinds to the envelope and
  each is inert until `track:memory` has ratified the store read it maps to.
  *Exit: a question whose answer shares no wording with the stored record is
  found by structure; and a caption engineered to match unrelated questions is
  never the reason its record is retrieved (#1874's representative inputs).*

**Sequencing.** 1 → 2 → 3 → 4 by design: 3's steered-loop risk needs 2's bound,
and 4 lands on an envelope milestone 1 has proven. Two openings sit outside that
line and both wait on the owner's word — milestone 3's local-files rung, which
may open beside 2, and the archive's feed-back mechanism (ADR-0225 §12), which
is an envelope kind ("address", user-named) additive to milestone 1's shape.
Which of them has been ruled is on #1908.

**Deferred — stated, not scheduled:**

- **The coverage layer.** Whether the trigger is learnable from the supply alone
  or needs coverage estimates (#838's third layer), re-measured against the
  production planner before it is ruled rather than settled from a replay.
- **The spend profile.** Per-turn cost on conversational surfaces, and whether
  proactive retrieval is budgeted differently from a turn the user is waiting on
  (#838).
- **Decomposition of compound questions** — `track:memory`'s standing item, and
  the likely ground of milestone 2 when it opens.
- **#1695**, a stated fact making the planner plan a store step no tool can
  carry. It is a planner defect this track should absorb, not a milestone.

**Concurrency.** The boundaries are with two tracks. `track:memory` owns the
store contracts and event episodes (#1874), so milestone 4's kinds stay inert
until the store read each maps to is ratified there; `track:world` owns egress
and the readers, so milestone 3's fetch is serviced under that track's seam
rather than beside it. What this track owns is what the planner may ask for and
what the loop does with what comes back. A lane here never edits a subsystem
another track has a lane open in (#1226 §3, Concurrency above); which lanes that
sequencing has bound is on #1908, #1231 and #1427. Clones and review quota are
one pool, under Concurrency above.

## The backlog

The backlog is a **label, not a track** (#1226 §4, amended). It fails the
definition a track has to meet — no purpose-with-milestones, no driveable exit,
it never closes — because it is the *complement* of the tracks: a backlog label
marks an issue that has been triaged and sits on **no** program of work, which is
what distinguishes it from one nobody has looked at yet. Its content is
opportunistic hardening and debt: correctness findings in shipped subsystems,
stale docs and citations, missing tests, operator-facing gaps, review-loop
tooling. It is picked up when a clone and review quota are free under Concurrency
above, typically as a residuals mini-batch or as one lane alongside another
track's wave. **#1232** is the census and the conventions record. Return-brief
items are not backlog: anything that needs the owner carries `ruling` instead
(`CONTRIBUTING.md` → "The tracker").

**The label carries a severity, and there is no bare one.** An issue on no
program of work is labeled `backlog:blocker`, `backlog:major`, `backlog:minor`
or `backlog:unknown`; bare `backlog` is retired. The three named severities are
`docs/review/guide.md`'s words, applied to the issue rather than to a review
finding, so a severity means here what it means there. **`unknown` means not yet
sized** — it is the honest default when the issue is filed in passing, and it is
re-sized lazily when the issue is next touched, under the same lazy-labelling
rule as the rest (`CONTRIBUTING.md` → "The tracker"). **`backlog:blocker` means
it enters the next batch**: a blocker against no program of work is a
contradiction, so sizing an issue that way is what schedules it. The ruling
behind all of this is recorded on #1232, named above as the conventions record;
this paragraph is the rule, not the ruling.

## Gap register

Where each `VISION.md` promise stands, as pointers into the ADR ledger and the
tracker — so the claim decays into them rather than into this document.

| VISION promise | Where it stands |
| --- | --- |
| Understood — a persistent user model | ADR-0072 (profile and inferred model are bands of one store), ADR-0005/0038/0040/0050 (provenance and the supersession law), ADR-0077 (the observer proposes beliefs from episodes). The mechanism is decided; how well it holds is `track:memory` (#1231, #1029) |
| In Control — inspect, correct, restrict, delete | *Inspect and correct*: ADR-0073 — the band-scoped read is an enumeration, killing a belief is show-then-confirm, and correcting is `learn`. *Delete*: ADR-0004 §6's whole-installation delete has its surface in ADR-0126 (`ai-assistant-purge`). *Restrict*: ADR-0097/0102/0133/0139's grants, enforced on the facet, ingest and notify paths — ADR-0102 gives them their CLI doors and milestone 15 their browser surface. *Export*'s surface is #692 (ADR-0004 §6, ADR-0073 §10) |
| More Capable Over Time | ADR-0009/0022 for the explicit loop, ADR-0077 for the ambient one; ADR-0119/0120 are the instrument that judges it. Whether it is improving is `track:memory`'s pre-registered exits, and the owner's measures gate (#881) is what acts on the answer once real usage exists |
| Context determines usefulness | ADR-0008's facets, fed by readers (ADR-0093/0095/0140) and rendered into the prompt (ADR-0096; #1082 is the gap that had left that arm vacuous). Device as a context facet, a permission input and the audit trail's "approved from where" is #920 |
| Supported — acts across tools | The seam is decided and attested: ADR-0154 designates `tools/` as the egress seam, ADR-0148 rules an egress call authorised as one whole, ADR-0151/0152 give the connection surface and the derived binding, ADR-0157 the flat-form widening. Breadth of connectors is opportunistic (a `backlog:*` issue), not a milestone. Closing the seam *by construction* — an injected transport capability rather than import contracts (#85), an approved-recipient policy beyond the tier ceiling (#68) — is `track:world` milestone 25 |
| Proactivity that earns its place | ADR-0130 (a notification is a proposal; only a perishable one earns an interruption) and ADR-0131 (it travels as an answer the device asked for), with ADR-0134/0135 around delivery. The first push *consumer* is milestone 14; whether the proactivity is welcome is the owner's deferred experiential ruling (#879); the delivery seam's full contract is #975 |
| Free to choose models | ADR-0002/0011/0013/0061/0062 — decided; on no track |
| Observability and evaluation | ADR-0119/0120 give the instrument: a measure is a rate over the trace stream, read offline while the hub is stopped. The harness and the benchmark exits are `track:memory` (#1029, #1231) |

**Named, but on no track.** An **engagement surface** — no track owns making
the assistant compelling to open tomorrow; the tracks buy reach and quality
rather than a reason. It stays deliberately undesigned, named so its absence is
a known debt of the plan rather than an oversight. A **commitment ledger** and a
**portable context graph** sit beside it, unscheduled.

## Arc records

The arc concept is retired (#1226 §2): tracks are peers, and there is no
arc-level closure to rule. Three arcs ran before that ruling, and each is left
here as a pointer at the issue that holds its rulings — restating any of them
is what this section exists to avoid.

- **The first vertical** — the seven core artifacts and the explicit learning
  loop. No ruling issue: the ADR ledger and this file's git history are its
  record.
- **Accumulation (legs 1–8)** — the exit ruling is on **#878**; the QA run it
  was ruled on is **#862**.
- **Inhabitation (legs 9–12)** — direction, the measures gate and the box
  migration are ruled on **#879**, which also holds each leg's mechanism-exit
  record and the QA runs behind them (#919, #978, #1081, #1159).

#879 is also where the inhabitation arc's **owner-side half** sits — deferred,
not waived: daily use, leg 10's experiential exit, the measures gate (#881), the
#829 consolidation window, and the box migration (stance 6). Those and every
other decision the owner owes are reached the one way the tracker offers,
`gh issue list -l ruling`, rather than from a list kept here.
