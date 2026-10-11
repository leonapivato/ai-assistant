# 312. A tool that only discloses may declare no effect, the authorizing phase's module takes another name, and planning always sees its own activation

- Status: Proposed
- Date: 2026-10-11
- Scope: the phases after understanding, milestone M43 ([#2815](https://github.com/leonapivato/ai-assistant/issues/2815)): three corrections to [ADR-0306](0306-a-capability-declares-what-its-calls-do-every-call-is-checked-by-rule-and-acting-claims-and-records-what-it-does.md)–[ADR-0309](0309-the-phases-are-built-beside-the-old-path-and-one-cutover-switches-the-controller-over-deletes-the-old-path-and-goes-live-in-one-deploy.md), found while starting to build them. The first two settle contradictions between ratified texts; the third ([#2838](https://github.com/leonapivato/ai-assistant/issues/2838)) settles a literal reading against the owner's ruling it came from.
- Authorization: the dispatcher assigned 0312 and authorized ratifying it once its reviews are green. The owner approved adding the third correction on 2026-10-11. It changes no owner ruling: the web search has no effect in the world (ADR-0309 §4:2), and the owner-only rule governs planning's views of other episodes and stories (ADR-0307 §6:4); §2 makes the first buildable, and §4 confines the second to what it was about.
- **Concerns `core`, so it is a contract-surface decision.** It narrows a `ToolDefinition` validator ADR-0306 §2:5 decides and no lane has built yet. No field, type or `Protocol` changes, and `PROTOCOL_VERSION` does not move for it.
- **Partially supersedes**:
  [ADR-0306](0306-a-capability-declares-what-its-calls-do-every-call-is-checked-by-rule-and-acting-claims-and-records-what-it-does.md) (§2:5's first limb: a declaration that is side-effecting with no effect validates where it writes nothing and discloses something);
  [ADR-0307](0307-a-planning-round-is-one-model-response-that-writes-its-own-message-keeps-episode-notes-and-names-what-it-was-shown-by-label.md) (§6:4's *episode notes are absent*, and §4:4's placement, each for the activation's own episode notes shown to its own planning);
  [ADR-0308](0308-recall-runs-again-on-what-understanding-found-and-outside-content-reaches-planning-only-as-a-digests-evidence.md) (§5:6's placement, for the activation's own evidence shown to its own planning);
  [ADR-0309](0309-the-phases-are-built-beside-the-old-path-and-one-cutover-switches-the-controller-over-deletes-the-old-path-and-goes-live-in-one-deploy.md) (§2:2's module naming: it names the phases, not their files).

## Context

**The search's declaration.** ADR-0016's consistency rules make a tool that declares
`discloses` side-effecting: "It means a web search is side-effecting, because it discloses
the query". `ToolDefinition._effects_are_consistent` enforces it, and `WEB_SEARCH` and
`FORECAST_READ` each declare `side_effecting=True`, `writes=()` and
`discloses=(PERSONAL,)`. ADR-0306 supersedes ADR-0016 only in §1's field list, in the
addition alone, so the rule stands. ADR-0306 §2:5 then refuses a declaration "whose
`side_effecting` is true while its effect is none", and the owner ruled the thin path's
web search to be one "whose effect is none" (ADR-0309 §4:2). The three cannot all hold.

**The authorizing module.** ADR-0309 §2:2 makes each phase "one module in
`orchestration/`" and lists them: "recall, understanding, planning, authorizing, acting and
digesting". §5's list retires today's `orchestration/authorizing.py`, and §5:3 rules that
"No new phase module takes the name of a module this section retires". Read as file names,
§2:2 requires the name §5:3 forbids.

**Planning's own records on a spoken pass.** Where a record placed for the owner alone may
not be shown, as on a spoken pass, ADR-0307 §6:4 makes "story notes and episode notes"
absent from planning's views. Episode notes are placed for the owner alone (ADR-0307
§4:4), and so is an episode's evidence (ADR-0308 §5:6). Read literally, that reaches the
current activation too: on voice, round 2 would not see the notes round 1 wrote, or the
evidence from its own search. The owner's ruling was about planning's views of other
episodes and stories (#2838).

## Decision

We will let a tool whose only side effect is disclosure declare no effect, keeping
ADR-0016's rule; read ADR-0309 §2:2 as naming phases, so the authorizing phase's module
takes another name; and show an activation's own rounds, notes and evidence to its own
planning on every pass.

### 1. Status and delivery

> **Normative.** This document remains `Proposed` until the reviews
> `CONTRIBUTING.md` → "Finishing an ADR PR" requires have returned green on one tree
> and the dispatcher's authorization to ratify stands.

> **Normative.** The lane that builds ADR-0306's `ToolDefinition` validators builds
> §2:5 as §2 below corrects it, and no lane builds §2:5 as first written.

### 2. The effect validator

> **Normative.** A declaration whose effect is not none and whose `side_effecting` is false
> does not validate.

> **Normative.** A declaration whose effect is none and whose `side_effecting` is true
> validates only where its `writes` is empty and its `discloses` is not, so that its one
> side effect is disclosure.

ADR-0016's three consistency rules stand and run beside these, and so do ADR-0231 §9:4,
which forbids narrowing `discloses` to get a search past a check, and ADR-0306 §2:6. The
web search and the forecast each write nothing and disclose `PERSONAL`, so each may
declare effect none. Their `interrupted_outcome` is `indeterminate`, since each is
side-effecting with `idempotency` `NONE`, so §2:6 has each declare that its outcome can be
unknown. A search cut short is reported as unknown (ADR-0307 §3:5); ADR-0306 §5:13 means
acting never retries it, does it another way or reports it as done. A later round, which
ADR-0307 §8:1 runs on that outcome, may plan the search again as a new call, checked and
run as any other.

No validator can tell a search from a send that stores nothing locally: both write nothing
and disclose. Declaring a send's effect none is a mis-declaration, which the hub, as the
declarations' author (ADR-0306 §2:4), does not make.

### 3. The authorizing phase's module

> **Normative.** ADR-0309 §2:2 names the phases and not their modules' file names. The
> authorizing phase's module takes a name other than `authorizing`, chosen by the lane that
> builds it, and ADR-0309 §5:3 binds it as written.

> **Normative.** ADR-0309 §2:3's `independence` contract covers that module under the name
> it takes.

The controller stage keeps the name `authorizing` (ADR-0309 §3:2): it is an enum member,
not a module, and §5:3 does not reach it.

### 4. Planning's own activation

> **Normative.** An activation's own rounds, their episode notes and its own digests'
> evidence are shown to its own planning on every pass, whatever the audience.

> **Normative.** On a pass where a record placed for the owner alone may not be shown,
> ADR-0307 §6:4 governs what planning is shown of other episodes and stories: the earlier
> activations, and the stories, that a view, a window or recall brings.

> **Normative.** The owner-only placement of episode notes and evidence (ADR-0307 §4:4,
> ADR-0308 §5:6) governs every other reader, `project_episode`, the windows and recall
> included.

The owner-only placement keeps those records from later readers on other passes. This
activation's planning wrote the notes and called for the evidence itself, and withholding
them from it would leave a multi-round spoken lookup without its working state. ADR-0307 §6:5's members-only move
and split on such a pass stand.

### 5. Relationship to earlier decisions

| Earlier decision | What changes |
| --- | --- |
| ADR-0016 §1 and its consistency rules | Nothing. Its header record of ADR-0306 summarizes §2:5 as first written, and is read through §2 here |
| ADR-0306 §2:5 | Its first limb: side-effecting with effect none validates where nothing is written and something is disclosed (§2:2). Its second limb stands as §2:1 |
| ADR-0306 §2:6, §5:13 | Nothing: the search and the forecast declare an outcome that can be unknown |
| ADR-0231 §9:4 | Nothing: `discloses` is never narrowed to pass a check |
| ADR-0307 §4:4, §6:4 | §6:4's *episode notes are absent*, and §4:4's placement, for the activation's own episode notes shown to its own planning (§4:1); §6:4 binds the rest as written (§4:2) |
| ADR-0308 §5:6 | Its placement, for the activation's own evidence shown to its own planning (§4:1); every other reader keeps it (§4:3) |
| ADR-0309 §2:2 | Its module naming: it names phases, and the authorizing phase's module takes another name (§3:1) |
| ADR-0309 §2:3, §3:2, §4:2, §5:3 | Nothing |

> **Normative.** This numbered draft records its replacements on the status lines and in a
> dated header note of ADR-0306, ADR-0307, ADR-0308 and ADR-0309, atomically with this ADR
> under ADR-0070 and ADR-0082, preserving their ratified bodies. The replacements take
> effect on this ADR's ratification.

## Consequences

- The thin path's web search, and the forecast, can be declared as the owner ruled them.
- A side-effecting declaration with effect none must name the disclosure it makes, so
  "effect none" never hides a write.
- The authorizing phase's module has a name that does not collide with the module §5
  retires, and the lane that builds it picks it.
- A spoken activation keeps its working state across rounds, and what it wrote stays the
  owner's alone for every later reader.

## Alternatives considered

- **Declaring the search's effect as the world.** Rejected: it contradicts the owner's
  ruling, and would give every search an effect record and a claim.
- **Declaring the search not side-effecting.** Rejected: ADR-0016's rule refuses it, and
  the disclosure is the consequence worth gating.
- **Dropping §2:5 whole.** Rejected: a tool that writes would then validate with no
  effect.
- **Renaming the retiring module first.** Rejected: it touches the old path for a name.
- **Placing a spoken activation's notes and evidence for its audience.** Rejected: the
  owner-only placement is the owner's ruling for later readers, and a later reader may be
  on another pass.
