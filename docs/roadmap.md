# Roadmap — direction and milestone navigation

**Status: working guidance, not a ratified architectural decision.** The
product's why and what live in [VISION.md](../VISION.md). This document explains
planning principles, ownership and dependencies; it does not duplicate a live
milestone checklist. Architectural contracts remain governed by
[the ADRs](adr/) and [CONTRIBUTING.md](../CONTRIBUTING.md).

## Where delivery planning lives

[Native GitHub Milestones](https://github.com/leonapivato/ai-assistant/milestones)
are the source of delivery scope, issue membership and acceptance status.
Their descriptions and linked acceptance issues state the outcome, exclusions,
dependencies and evidence required. Read the native milestone and its issues
before proposing a batch; an empty milestone list is not permission to revive
an old plan.

The [owner's planning reset (#2518)](https://github.com/leonapivato/ai-assistant/issues/2518)
governs retirement of the legacy track checklists and numbered milestone plans
across all areas. Historical numbers and acceptance rulings remain references,
not a current schedule. Do not recreate legacy milestones or create provisional
replacements merely to populate the GitHub page. Replacement scope and numbering
are agreed before creation; the new milestone's URL identifies it unambiguously.

Retiring a plan does not declare its unfinished requirements completed, invalidate
its passing tests, or change a ratified ADR. Open findings and design proposals
remain discoverable inputs for future selection. An issue without an assigned
milestone is not an implicit commitment or queue position. Explicit owner-directed
maintenance can proceed without inventing a milestone; record that authorization
on the work item.

## How to define a milestone

- **One user-visible outcome, small enough to demonstrate.** Prefer a complete
  behavior over an assortment of components. Product phases describe
  responsibilities; milestones describe increments of behavior, so one phase
  can span several milestones.
- **Scope and exclusions before implementation.** Name the intended user or
  event path, required dependencies and what remains outside the boundary.
  Do not silently transfer an old milestone's entire scope into its replacement.
- **Acceptance scenarios before slices.** Include ordinary supported inputs,
  relevant follow-ups and failure cases. Inspect responses, persisted state and
  actual operations; passing component tests alone do not prove a reachable
  end-to-end behavior.
- **Reuse demonstrated foundations.** Survey existing code, contracts, tests
  and QA records before deciding what needs changing.
- **Tests accumulate with delivery.** Deterministic integration tests cover
  repeatable mechanisms and safety guarantees; proportionate live-model and
  surface QA assess semantic quality and composition. Do not defer all
  integration evidence to a large final campaign.
- **Acceptance has an explicit record.** A linked acceptance issue records the
  tested revision, evidence, residuals and the owner's exit ruling. A milestone
  completion percentage, merged PR or closed QA run alone is not acceptance.
  Retirement is recorded as retirement, never as a passed exit.

Issues carry the implementation slices, defects and acceptance evidence.
Batch issues can coordinate several slices but are not a second milestone board.
Track labels classify the area of work; they neither allocate capacity nor
authorize dispatch. The wiki explains current/proposed designs, and ADRs govern
the contracts that implementation must obey.

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
   historical voice discussion is on #1318; any new ambient-capture scope must
   be selected explicitly in a native GitHub milestone. The design is not what is
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

## Areas and historical records

These are navigation and responsibility categories, not scheduled work or a
required delivery order. Historical track records retain their discussions and
accepted exits; their unchecked items and “next lane” prose do not schedule work.

| Area | Responsibility | Historical record |
| --- | --- | --- |
| Browser | Gateway, conversations, notifications and user control surfaces | [#1230](https://github.com/leonapivato/ai-assistant/issues/1230) |
| Conversation | Responses, streaming and interpretation of conversational input | [#1312](https://github.com/leonapivato/ai-assistant/issues/1312) |
| Voice | Speech input/output, disclosure and capture design | [#1318](https://github.com/leonapivato/ai-assistant/issues/1318) |
| Memory | Learning, retrieval, reconciliation and measurement | [#1231](https://github.com/leonapivato/ai-assistant/issues/1231); benchmark evidence [#1029](https://github.com/leonapivato/ai-assistant/issues/1029) |
| World | Reading external sources and acting through permissioned integrations | [#1427](https://github.com/leonapivato/ai-assistant/issues/1427) |
| Planning | Understanding, investigation, planning and the task lifecycle | [#1908](https://github.com/leonapivato/ai-assistant/issues/1908), campaign [#2255](https://github.com/leonapivato/ai-assistant/issues/2255) |
| Identity | Person identity, audiences, sessions and placement | [#1718](https://github.com/leonapivato/ai-assistant/issues/1718) |

The [Phase 1 design discussion (#2517)](https://github.com/leonapivato/ai-assistant/issues/2517)
and [proposed wiki explanation](https://github.com/leonapivato/ai-assistant/wiki/Understanding-the-request-proposed-design)
are design inputs, not milestone assignments. Discussion of later phases,
external events, recursive supporting work and standing interests must not be
mistaken for an implementation dispatch.

## Dependencies and work selection

Record dependencies on the milestone or slice that consumes them. Preserve
contract-first sequencing and the subsystem collision rules in
[CONTRIBUTING.md](../CONTRIBUTING.md#coordinating-parallel-work). GitHub's display
order and a milestone's number do not establish dependency order.

Legacy work is reconciled explicitly when defining replacements: reuse an
already demonstrated behavior, carry forward an unresolved requirement, defer
it, or record why it is dropped. Keep links to the original evidence and
decisions. Moving or retiring a milestone does not automatically close defects,
discard regression tests, widen permissions or authorize a change to a contract.

## Backlog and decisions

Issues remain the home for defects, design questions and possible future work.
Use the track/backlog label conventions in
[CONTRIBUTING.md](../CONTRIBUTING.md#the-tracker), with [#1232](https://github.com/leonapivato/ai-assistant/issues/1232)
as the historical backlog convention record. Severity expresses priority, not a
new milestone or authorization to start an old batch. Items needing an owner
decision remain discoverable through the `ruling` label.

## Earlier planning history

The former roadmap's full milestone scopes, gap register and sequencing are
preserved in git history and the linked tracker records. They are not a second
live plan. The transition from arcs to tracks is recorded on
[#1226](https://github.com/leonapivato/ai-assistant/issues/1226); the later transition
to native milestones and the project-wide reset are recorded on
[#2518](https://github.com/leonapivato/ai-assistant/issues/2518).

Earlier accumulation evidence is on [#878](https://github.com/leonapivato/ai-assistant/issues/878)
and QA [#862](https://github.com/leonapivato/ai-assistant/issues/862).
Inhabitation direction and its historical exit records are on
[#879](https://github.com/leonapivato/ai-assistant/issues/879).
Preserving those records does not carry their remaining work into the new plan
without explicit selection.
