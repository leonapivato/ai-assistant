# 341. A pure read is a call that writes nothing and does not leave the hub, so looking something up in the assistant's own records does not commit an activation

- Status: Accepted
- Date: 2026-10-21
- Scope: what ADR-0332 counts as a **pure read**, and so where an activation's join window closes. The problem is [#3284](https://github.com/leonapivato/ai-assistant/issues/3284). A per-version recall, a durable store of pending input, and whether the clock is a pure read are not decided here (§4).
- Dependency: [ADR-0332](0332-activations-run-side-by-side-across-places-and-one-at-a-time-within-one-a-new-input-joins-the-running-activation-until-it-acts-and-a-place-waits-a-moment-before-it-starts.md), [ADR-0306](0306-a-capability-declares-what-its-calls-do-every-call-is-checked-by-rule-and-acting-claims-and-records-what-it-does.md) and [ADR-0312](0312-a-tool-that-only-discloses-may-declare-no-effect-the-authorizing-phases-module-takes-another-name-and-planning-always-sees-its-own-activation.md), as their status lines leave them.
- Authorization: the owner, 2026-10-21: "Dont draw the line who ratifies what, Ill just check in and if I see something wrong I'll give input to you". Under that standing delegation the decision is the dispatcher's, the dispatcher assigned 0341, and the dispatcher ratifies it.
- **Changes no contract.** No type in `core/types.py` changes, no Protocol changes, no declaration changes, nothing the wire carries or a record stores changes, and `PROTOCOL_VERSION` does not move. It amends one clause of a contract-surface decision, so both review lenses run on it.
- **Partially supersedes**, in the clause §5's first table names: ADR-0332.

## Context

**The rule as ratified.** ADR-0332 §3:1 defines the term the join window turns on: "A **pure
read** is a call whose capability declares `CapabilityEffect.NONE` and does not leave the hub."
§3:2 has an activation commit "once acting has committed to its first call that is not a pure
read, or to the round's message". §3:5's commitment step runs before acting dispatches "any
call of a round that is not a pure read". Once committed, an activation takes no join, and a
new input on its place waits (§3:3, §3:4).

**What the decision meant.** ADR-0332 converts the walk on proposal #3257, and three of its
own passages say a look-up does not close the window:

- the walk's answer 2, in its Context: the window "closes when acting commits to its first
  call that is not a pure read, or to its message";
- §3's lead: "An activation folds in new input until it commits to something it cannot take
  back";
- its rejected alternative: "**The join window closing as soon as acting begins.** Rejected
  (answer 2): looking something up is not acting."

**What the tree holds.** These facts hold on the tree this decision was written against:

- Planning's look-ups, `SEARCH_MEMORY`, `READ_STORY` and `FOLLOW_UP` in
  `orchestration/lookups.py`, are declared by its `_declared` with `effect=OWN_RECORDS`,
  `leaves_hub=False`, `safe_to_repeat=True`, `side_effecting=True` and `writes=()`. Reading a
  story takes the class's effect under ADR-0306 §3:1 and its paragraph after §3:4, and the
  module gives the memory search and the follow-up the same declaration.
- Acting routes a call by its effect: one whose effect is `OWN_RECORDS` runs through the
  own-records seam, against the store, never through `ToolInvoker` (ADR-0306 §3:3; the
  `CapabilityEffect.OWN_RECORDS` branch in `orchestration/acting.py`).
- ADR-0306 §2:5 and ADR-0312 §2 make a declaration whose effect is not none side-effecting.
  `ToolDefinition`'s validators refuse a declaration whose effect is none and whose `writes`
  is not empty. So a look-up cannot be declared `NONE` without leaving the own-records seam.
- The story calls in `orchestration/story_calls.py` and remembering in
  `orchestration/remembering.py` are declared `OWN_RECORDS` with `writes=(PERSONAL,)`.
  `note_story` is safe to repeat and `remember` is not.
- The web search in `tools/web_search.py` is declared `NONE` with `leaves_hub=True`.
- `is_pure_read` in `orchestration/joining.py` returns `tool.effect is CapabilityEffect.NONE
  and not tool.leaves_hub`, as §3:1 reads. `_commits` in `orchestration/phase_path.py` asks it
  of each allowed call of the round, and `_commitment` runs the commitment step once, before
  acting dispatches anything of the round, where any call of it commits.

So under the ratified text a round that only searches memory or reads a story commits its
activation, and a correction sent a moment later waits instead of joining. That is the case
answer 2 was given to prevent. The rule built in step 2 ([#3281](https://github.com/leonapivato/ai-assistant/pull/3281))
follows §3:1 as ratified, so this is a fault in the clause, not in the code.

**Why it needs a decision.** §3:1 is a marked clause of an accepted ADR, and it excludes the
look-ups by its words. Changing what it counts is changing what it requires (ADR-0070). The
other way out, redeclaring the look-ups, is not open: a look-up declared `NONE` would leave
the own-records seam that ADR-0306 §3:3 requires it to run through.

**What property separates them.** The look-ups and the story writes share their effect, the
place they run, and, for most story calls, safe to repeat and no effect record. What a look-up
does not do is write: its declaration's `writes` is empty. A write to the hub's own records is
something a join could make wrong, such as a note on a story for a request the next message
corrects, and ADR-0332's paragraph after §3:2 keeps it committing. A read leaves nothing
behind that a corrected understanding would have to take back.

## Decision

We will count as a pure read every call whose capability declares no `writes`, declares its
effect as none or as the assistant's own records, and does not leave the hub. A look-up in
memory or of a story therefore no longer commits an activation, and an input sent while it
runs joins. A call that writes the hub's own records still commits, as does a call that leaves
the hub and a call in the world. Everything else ADR-0332 rules on joining stands.

### 1. Status, scope and delivery

> **Normative.** This document remains `Proposed` until the reviews `CONTRIBUTING.md` →
> "Finishing an ADR PR" requires have returned green on one tree and the authorization to
> ratify stands. An assigned number or a green review alone does not change its status.

> **Normative.** No lane implements this decision before it merges `Accepted` (golden rule 5,
> ADR-0015 §5).

> **Normative.** The implementation is one lane, scoped to `orchestration/` and its tests. It
> changes no file in `core/` and no capability's declaration.

### 2. The pure read

> **Normative.** A **pure read** is a call whose capability declares an empty `writes`,
> declares its effect as `CapabilityEffect.NONE` or `CapabilityEffect.OWN_RECORDS`, and
> declares that it does not leave the hub.

> **Normative.** Whether a call is a pure read is decided from the declaration of the tool
> that tool selection picked for it (ADR-0306 §2:8) and from nothing else: never from the
> call's name, its capability's name, its arguments or a list of either.

> **Normative.** Where ADR-0332 reads *pure read*, in §3:2's committed mark and in §3:5's
> commitment step, it reads §2:1's definition.

A call whose capability declares any `writes`, the effect `CapabilityEffect.WORLD`, or that it
leaves the hub is therefore not a pure read, whatever else it declares. A write to the hub's
own records commits even where it is safe to repeat and gets no effect record, as noting on a
story does. A web search commits because it leaves the hub. Disclosure is not read, as §3:1 did
not read it.

Under the declarations on the tree today:

| Call | Declares | A pure read |
| --- | --- | --- |
| `search_memory`, `read_story`, `follow_up` | own records, no `writes`, does not leave | yes (newly) |
| `note_reliance`, `current_time` | none, no `writes`, does not leave | yes, as under §3:1 |
| the story calls, `remember` | own records, `writes=(PERSONAL,)` | no |
| `web_search`, the forecast | none, leaves the hub | no |
| `send_email`, `book_stay` | the world, leaves the hub | no |

The table illustrates §2:1 against today's declarations. It binds nothing, and a declaration
that changes moves its row.

### 3. What stays as it is

> **Normative.** This decision changes no declaration and no rule ADR-0306 or ADR-0312 states
> about one. A capability declared wrongly is corrected under ADR-0306 §2, and §2:1 reads the
> declaration as it stands.

ADR-0332 §3:2 still has the round's message commit the activation. §3:5's commitment step,
§3:6's join, §3:7's setting a round aside and §3:8's finishing of what was dispatched read as
they stand. A round holding a call that is not a pure read still runs the step before any of
the round's calls, its pure reads included, since §3:7 sets the whole round aside. A round of
pure reads alone still runs no step and commits nothing. A pure read dispatched before a join
is awaited to its end (ADR-0306 §3:3) and its result stays on the episode for the rounds
planned from the new understanding version (ADR-0332 §3:13). Planning may then repeat the
look-up, which is safe to repeat.

A call run under an approval gets an effect record whatever its capability (ADR-0321 §4:10).
That claim is the approval's record and not a write the call's capability declares, so it does
not move the call out of §2:1. It did not under §3:1 either.

### 4. What this decision does not decide

| Not decided here | Where it goes |
| --- | --- |
| Recall run again per understanding version | [#3268](https://github.com/leonapivato/ai-assistant/issues/3268), as ADR-0332 §9 places it |
| A durable store of pending input on the line | [#3267](https://github.com/leonapivato/ai-assistant/issues/3267), as ADR-0332 §9 places it |
| Whether the clock, once planning is offered it, is a pure read | The clock's own lane ([#2942](https://github.com/leonapivato/ai-assistant/issues/2942)): its declaration decides, under §2:1 |

### 5. Relationship to earlier decisions

Superseded in part; every clause the middle column does not name stands:

| Earlier decision | What it replaces | By |
| --- | --- | --- |
| ADR-0332 | §3:1, whole: a pure read is a call whose capability declares an empty `writes`, its effect as none or as the assistant's own records, and that it does not leave the hub | §2:1–§2:3 |

Read through and not superseded:

| Earlier decision | What changes |
| --- | --- |
| ADR-0332 §3:2, §3:5 | Nothing in their words: each reads *pure read* as §2:1 defines it (§2:3) |
| ADR-0332, the paragraph after §3:2 | Nothing: a write to the hub's own records, a call that leaves the hub and writing into the place each still commit. A read of the hub's own records writes nothing, so the paragraph does not reach it |
| ADR-0332 §3:3, §3:6–§3:8, §3:13 | Nothing: an activation that has only read takes joins as an uncommitted one does, and what it read stays on the episode |
| ADR-0332 §4:1, §4:6 | Nothing in their words: an activation that has only read is shown as not committed, and may be taken over |
| ADR-0332 §9 | Nothing: the items it names stay its own |
| ADR-0306 §2, §3:1–§3:4 | Nothing: the five properties, the look-ups' declarations and the own-records seam stand (§3:1) |
| ADR-0312 §2 | Nothing: the effect validator stands |
| ADR-0321 §4:10 | Nothing: a call under an approval still gets an effect record (§3) |

> **Normative.** This decision records its replacement on ADR-0332's status line and in a dated
> header note there, atomically with this ADR under ADR-0070 and ADR-0082, preserving its
> ratified body. The replacement takes effect on this ADR's ratification.

## Consequences

**Easier.** A correction sent while the assistant is looking something up in memory or reading
a story joins the activation, and the answer covers both messages. That is the walk's
answer 2 as it was given.

**Harder.** More activations take joins, so more pay a second understanding call and the
rounds planned after it (ADR-0332's Consequences). A look-up made before a join may be made
again for the new understanding version. Each look-up runs on the hub, so a repeat costs time
and no spend outside it. `join_limit` (ADR-0332 §6:5) bounds the restarts as before. More
activations are shown to the same person's other places as uncommitted, and so more can be
taken over (ADR-0332 §4).

**The cut, for the dispatcher.** One lane in `orchestration/`, after this merges. It changes
`is_pure_read` in `orchestration/joining.py` to §2:1, with its docstring and the module's, and
the docstring of `_commits` in `orchestration/phase_path.py` where it names what commits. Its
tests cover:

- each look-up a pure read;
- a story write, `remember`, the web search and a call in the world not;
- a declaration with the look-ups' properties under another name, which is a pure read
  (§2:2);
- a round of look-ups alone that commits nothing, and an input after it that joins;
- a round mixing a look-up and a story write that runs the step before either, and that a
  join sets aside whole.

`orchestration/joining.py` is also touched by ADR-0332's step 3 ([#3294](https://github.com/leonapivato/ai-assistant/pull/3294)),
so the lane is cut after that merges.

**Revisit when** a capability writes something no declaration's `writes` names, or a read
leaves something behind that a corrected understanding would have to undo. Either would mean
the declarations no longer carry the line §2:1 draws, and the fix belongs to ADR-0306's
declarations before it belongs here.

## Alternatives considered

- **Declare the look-ups' effect none.** Rejected: acting routes by effect, so a look-up
  declared none would run through `ToolInvoker` rather than against the store, which
  ADR-0306 §3:3 forbids. It would also make the look-ups differ from reading a story, whose
  effect ADR-0306 §3:1 rules.
- **Name the look-ups.** A list of capabilities that count as pure reads. Rejected: a list
  misses the next read and admits a renamed write. The declaration already says what a call
  writes (§2:2).
- **Count every call that is safe to repeat and gets no effect record as a pure read.**
  Rejected: noting on a story is both, and it writes the user's records on the strength of an
  understanding a join may correct. ADR-0332's paragraph after §3:2 keeps it committing.
- **Read `side_effecting` instead of `writes`.** Rejected: ADR-0306 §2:5 requires a look-up,
  whose effect is not none, to declare itself side-effecting, so the property cannot tell a
  read from a write.
- **Keep §3:1 as ratified.** Rejected: under it nothing planning can look up in the hub's own
  records leaves the window open, and the walk's answer 2 and ADR-0332's own rejected
  alternative say a look-up should.
