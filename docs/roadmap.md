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
7. **Voice is parked, and its slot follows `track:web-client`** (#879). The
   design is not what is missing: ADR-0094 already unifies client, sensor and
   actuator as capability profiles of one spoke, with the band ceiling and the
   release gate an always-listening edge needs. What opening the slot costs is
   named now rather than discovered then — an ambient capture producer walks
   into a ratified pair. ADR-0075 §2 *reserves* rather than grants the capture
   exemption for buffered ambient capture; ADR-0093 §4 forbids a `Reader`
   proposing an `EpisodicMemory` at all; ADR-0094 §10 states the collision and
   grants nothing either. Whoever opens the slot pays for that decision first.

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

Live record: **#1230**.

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
  The ADR lane is recorded on #1230 and carries two delegated calls: whether the
  decision is one ADR or two (gateway seat vs web-session identity), and in-repo
  vs sibling repo for the front-end bundle (the ruling leans in-repo).
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
- **Hub-owned intent routing.** Design noted for when it comes: `ask` → typed
  operation, one-directional — a typed operation is never re-read — with its own
  confirm rule for non-read-only operations, distinct from the tool seam.
- The hosted/billing plane: a separate service outside the hub's trust boundary,
  needing its own trust ADR. Hosting is currently ruled against for the owner
  (stance 6).
- Voice, whose slot follows this track (stance 7).

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
measured against, and what the next one is shaped by; the pilot it named when
tracks replaced arcs was #1210.

The standing questions the track carries — forgetting, which the complete-intake
ruling names as the destination of the selectivity it removed from intake;
decomposition and iterative retrieval; harness fidelity and grading; the
policy and reconciler cluster; the intake surface — are enumerated on #1231,
which is the census. Issues are labeled `track:memory` as they are touched.

## `track:conversation` — the assistant answers

Live record: **#1312**.

**Purpose:** the hub-side conversational engine — the pipeline's terminal step.
Today the engine listens, remembers and plans, but a plan ending in "compose a
reply" halts at "No tool is available": replying was swept up in "tools are
deferred to MCP" although answering one's own user is not egress — the reply
travels back on the wire the `ask` arrived on, the shape ADR-0131 gave
notifications ("an answer the device asked for"). This track owns making the
assistant *speak*: composing answers from plan + retrieved memory + context,
streaming them, and eventually routing intents to typed operations. It is
hub-side work with **no dependency on `track:web-client`'s gateway**; the CLI
exercises every exit. `track:web-client` milestone 14 (streaming chat in the
browser) consumes this track's output. Milestones are ordered by **dependency
only**, and each closes on a QA-driven exit ruling: a QA run
(`.claude/skills/qa-milestone`) recorded as a `qa` issue, then the owner's ruling
recorded on #1312.

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

**Deferred — stated, not scheduled:**

- **Hub-owned intent routing.** `ask` → typed operation, one-directional — a
  typed operation is never re-read — with its own confirm rule, distinct from the
  tool seam. Conceptually moved here from `track:web-client`'s deferred list;
  #1230's list still names it.
- The **engagement surface** the Gap register names as on-no-track debt. This
  track is its natural eventual home, but it stays undesigned until ruled.

## `track:world` — the assistant sees and acts on the world

Live record: **#1427**.

**Purpose:** the assistant sees and acts on the world — the `readers/` (sensor)
and `tools/` (actuator) seams, hub-side and CLI-driven. The browser client
consumes what lands here (`track:web-client`), voice keeps spoke-as-sensor
(ADR-0094), and what ingested content *becomes* stays with `track:memory`. The
adversary is already named and mostly answered — ADR-0098 (the injection class,
escaping, never-authority, ceilings, detection-is-not-a-gate), ADR-0106 (taint
through consolidation), ADR-0148/0154 (an egress call authorised whole, per
call, with no standing authorisation) — and the one thing all of them name as
unbuilt is **origin**, which is why milestone 23 comes first. Milestones are
ordered by **dependency only**, and each closes on a QA-driven exit ruling
recorded on #1427. Voice holds milestones 19–22 (#1318); this track starts
at 23.

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
  band precedence revisited now a real reader exists (#663).
  *Exit: every read of a source and every egress is reconstructible from the
  audit trail alone, origin included.*
- **25 — closed by construction.** Egress through an injected transport
  capability rather than import contracts (#85); an approved-recipient policy
  beyond the tier ceiling (#68); a budget ceiling on what the world may cost.
  *Exit: a tool that tries to reach the world outside the seam cannot, and the
  test that proves it is the fake transport, not a grep.*

**Deferred — stated, not scheduled:**

- **Breadth, until milestone 23 closes.** The second reader, further actuators,
  the reader-agent split (trigger: a reader that needs its own model call), a
  two-phase planner, any classifier-based defence — ADR-0098's own triggers
  fire with the second reader.
- **The relabel sweep.** A cluster of `backlog` issues sits at these seams;
  they are relabelled `track:world` in one pass once the track's shape is on
  `main`, not issue by issue.

**Concurrency.** This track runs in parallel with `track:web-client` milestone
16 (#1230). The subsystems differ — `core/`, `memory/`, `permissions/`,
`planning/`, `readers/` and `tools/` here, `interfaces/gateway` and `docs/`
there — with **one late collision**: the CONFIRM-card origin rendering touches
the browser assets and the CLI renderer, so that consumer lane is sequenced
after milestone 16's client lanes, never beside them (#1226 §3). Clones and
review quota are one pool, under Concurrency above.

## The backlog

The backlog is a **label, not a track** (#1226 §4, amended). It fails the
definition a track has to meet — no purpose-with-milestones, no driveable exit,
it never closes — because it is the *complement* of the tracks: `backlog` marks
an issue that has been triaged and sits on **no** program of work, which is what
distinguishes it from one nobody has looked at yet. Its content is opportunistic
hardening and debt: correctness findings in shipped subsystems, stale docs and
citations, missing tests, operator-facing gaps, review-loop tooling. It is
picked up when a clone and review quota are free under Concurrency above,
typically as a residuals mini-batch or as one lane alongside another track's
wave. **#1232** is the census and the conventions record. Return-brief items are
not backlog: anything that needs the owner carries `ruling` instead
(`CONTRIBUTING.md` → "The tracker").

## Gap register

Where each `VISION.md` promise stands, as pointers into the ADR ledger and the
tracker — so the claim decays into them rather than into this document.

| VISION promise | Where it stands |
| --- | --- |
| Understood — a persistent user model | ADR-0072 (profile and inferred model are bands of one store), ADR-0005/0038/0040/0050 (provenance and the supersession law), ADR-0077 (the observer proposes beliefs from episodes). The mechanism is decided; how well it holds is `track:memory` (#1231, #1029) |
| In Control — inspect, correct, restrict, delete | *Inspect and correct*: ADR-0073 — the band-scoped read is an enumeration, killing a belief is show-then-confirm, and correcting is `learn`. *Delete*: ADR-0004 §6's whole-installation delete has its surface in ADR-0126 (`ai-assistant-purge`). *Restrict*: ADR-0097/0102/0133/0139's grants, enforced on the facet, ingest and notify paths — ADR-0102 gives them their CLI doors and milestone 15 their browser surface. *Export*'s missing interface is #692 (ADR-0004 §6, ADR-0073 §10) |
| More Capable Over Time | ADR-0009/0022 for the explicit loop, ADR-0077 for the ambient one; ADR-0119/0120 are the instrument that judges it. Whether it is improving is `track:memory`'s pre-registered exits, and the owner's measures gate (#881) is what acts on the answer once real usage exists |
| Context determines usefulness | ADR-0008's facets, fed by readers (ADR-0093/0095/0140) and rendered into the prompt (ADR-0096; #1082 is the gap that had left that arm vacuous). Device as a context facet, a permission input and the audit trail's "approved from where" is #920 |
| Supported — acts across tools | The seam is decided and attested: ADR-0154 designates `tools/` as the egress seam, ADR-0148 rules an egress call authorised as one whole, ADR-0151/0152 give the connection surface and the derived binding, ADR-0157 the flat-form widening. Breadth of connectors is opportunistic (`backlog`), not a milestone. Closing the seam *by construction* — an injected transport capability rather than import contracts (#85), an approved-recipient policy beyond the tier ceiling (#68) — is `track:world` milestone 25 |
| Proactivity that earns its place | ADR-0130 (a notification is a proposal; only a perishable one earns an interruption) and ADR-0131 (it travels as an answer the device asked for), with ADR-0134/0135 around delivery. The first push *consumer* is milestone 14; whether the proactivity is welcome is the owner's deferred experiential ruling (#879); the delivery seam's full contract is #975 |
| Free to choose models | ADR-0002/0011/0013/0061/0062 — decided; on no track |
| Observability and evaluation | ADR-0119/0120 give the instrument: a measure is a rate over the trace stream, read offline while the hub is stopped. The harness and the benchmark exits are `track:memory` (#1029, #1231) |

**Named, but on no track.** An **engagement surface** — nothing here yet makes
the assistant compelling to open tomorrow, and both tracks buy reach or quality
rather than a reason; it stays deliberately undesigned, named so its absence is
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
